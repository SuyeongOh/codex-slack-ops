from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import List
from sqlalchemy import select, update

from ..config import Settings
from ..db import Database
from ..exceptions import ApprovalForbidden, ApprovalNotFound, InvalidApprovalTransition
from ..locks import RedisLockManager
from ..models import ApprovalRequest, ensure_utc, utcnow
from ..schemas import ApprovalCreateRequest, ExecutionUpdateRequest
from ..state_machine import (
    APPROVED,
    COMPLETED,
    EXECUTING,
    FAILED,
    PENDING,
    REJECTED,
    apply_transition,
    expire_if_needed,
)
from .slack_service import SlackService


@dataclass
class DecisionResult:
    approval: ApprovalRequest
    feedback: str
    changed: bool


class ApprovalService:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        slack_service: SlackService,
        lock_manager: RedisLockManager,
    ) -> None:
        self.settings = settings
        self.database = database
        self.slack_service = slack_service
        self.lock_manager = lock_manager

    async def create_request(self, payload: ApprovalCreateRequest) -> ApprovalRequest:
        channel_id = payload.channel_id or self.settings.slack_default_channel_id
        if not channel_id:
            raise InvalidApprovalTransition("channel_id is required when no default Slack channel is configured")

        approval = ApprovalRequest(
            title=payload.title,
            command=payload.command,
            rationale=payload.rationale,
            risk_level=payload.risk_level,
            requested_by=payload.requested_by,
            context=payload.context,
            expires_at=utcnow() + timedelta(seconds=self.settings.approval_ttl_seconds),
        )

        async with self.database.session() as session:
            session.add(approval)
            await session.commit()
            await session.refresh(approval)

        slack_channel_id, slack_message_ts = await self.slack_service.post_approval_message(approval, channel_id)

        async with self.database.session() as session:
            await session.execute(
                update(ApprovalRequest)
                .where(ApprovalRequest.id == approval.id)
                .values(
                    slack_channel_id=slack_channel_id,
                    slack_message_ts=slack_message_ts,
                    updated_at=utcnow(),
                )
            )
            await session.commit()

        return await self.get_request(approval.id)

    async def get_request(self, approval_id: str) -> ApprovalRequest:
        async with self.database.session() as session:
            approval = await session.get(ApprovalRequest, approval_id)
            if approval is None:
                raise ApprovalNotFound(f"approval {approval_id} not found")
            expired = await self._expire_if_needed(session, approval)
            if expired:
                await session.refresh(approval)
            return approval

    async def approve_request(self, approval_id: str, user_id: str) -> DecisionResult:
        self._validate_approver(user_id)
        return await self._decide(approval_id=approval_id, user_id=user_id, action="approve")

    async def reject_request(self, approval_id: str, user_id: str) -> DecisionResult:
        self._validate_approver(user_id)
        return await self._decide(approval_id=approval_id, user_id=user_id, action="reject")

    async def record_execution_update(
        self,
        approval_id: str,
        payload: ExecutionUpdateRequest,
    ) -> ApprovalRequest:
        async with self.database.session() as session:
            approval = await session.get(ApprovalRequest, approval_id)
            if approval is None:
                raise ApprovalNotFound(f"approval {approval_id} not found")

            transition = apply_transition(approval.status, self._action_for_execution_update(payload.status))
            if not transition.changed:
                raise InvalidApprovalTransition(transition.reason)

            now = utcnow()
            values = {
                "status": transition.status,
                "result_summary": payload.result_summary,
                "updated_at": now,
            }
            if transition.status == EXECUTING:
                values["executed_at"] = now
            if transition.status in {COMPLETED, FAILED}:
                values["completed_at"] = now

            await session.execute(
                update(ApprovalRequest)
                .where(ApprovalRequest.id == approval_id, ApprovalRequest.status == approval.status)
                .values(**values)
            )
            await session.commit()

        approval = await self.get_request(approval_id)
        await self.slack_service.refresh_approval_message(approval)
        await self.slack_service.post_status_reply(approval)
        return approval

    async def expire_pending_requests(self) -> List[ApprovalRequest]:
        async with self.database.session() as session:
            now = utcnow()
            rows = await session.execute(
                select(ApprovalRequest.id).where(
                    ApprovalRequest.status == PENDING,
                    ApprovalRequest.expires_at <= now,
                )
            )
            approval_ids = list(rows.scalars().all())
            if not approval_ids:
                return []

            await session.execute(
                update(ApprovalRequest)
                .where(ApprovalRequest.id.in_(approval_ids), ApprovalRequest.status == PENDING)
                .values(status="expired", decided_at=now, updated_at=now)
            )
            await session.commit()

        expired_approvals = []
        for approval_id in approval_ids:
            approval = await self.get_request(approval_id)
            await self.slack_service.refresh_approval_message(approval)
            await self.slack_service.post_status_reply(approval)
            expired_approvals.append(approval)
        return expired_approvals

    async def _decide(self, *, approval_id: str, user_id: str, action: str) -> DecisionResult:
        lock = await self.lock_manager.acquire(f"approval:{approval_id}:decision")
        if not lock.acquired:
            approval = await self.get_request(approval_id)
            return DecisionResult(approval=approval, feedback="Another decision is already being processed.", changed=False)

        try:
            async with self.database.session() as session:
                approval = await session.get(ApprovalRequest, approval_id)
                if approval is None:
                    raise ApprovalNotFound(f"approval {approval_id} not found")

                expired = await self._expire_if_needed(session, approval)
                if expired:
                    await session.refresh(approval)
                    await self.slack_service.refresh_approval_message(approval)
                    return DecisionResult(approval=approval, feedback="Approval window already expired.", changed=False)

                transition = apply_transition(approval.status, action)
                if not transition.changed:
                    return DecisionResult(approval=approval, feedback=transition.reason, changed=False)

                now = utcnow()
                values = {
                    "status": transition.status,
                    "decided_at": now,
                    "updated_at": now,
                }
                if transition.status == APPROVED:
                    values["approved_by"] = user_id
                if transition.status == REJECTED:
                    values["rejected_by"] = user_id

                await session.execute(
                    update(ApprovalRequest)
                    .where(ApprovalRequest.id == approval_id, ApprovalRequest.status == PENDING)
                    .values(**values)
                )
                await session.commit()

            approval = await self.get_request(approval_id)
            await self.slack_service.refresh_approval_message(approval)
            await self.slack_service.post_status_reply(approval)
            feedback = "Approval recorded." if action == "approve" else "Request rejected."
            return DecisionResult(approval=approval, feedback=feedback, changed=True)
        finally:
            await lock.release()

    async def _expire_if_needed(self, session, approval: ApprovalRequest) -> bool:
        transition = expire_if_needed(
            approval.status,
            is_expired=ensure_utc(approval.expires_at) <= utcnow(),
        )
        if not transition.changed:
            return False

        await session.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == approval.id, ApprovalRequest.status == PENDING)
            .values(status=transition.status, decided_at=utcnow(), updated_at=utcnow())
        )
        await session.commit()
        return True

    def _validate_approver(self, user_id: str) -> None:
        allowed = self.settings.allowed_approver_ids
        if allowed and user_id not in allowed:
            raise ApprovalForbidden(f"user {user_id} is not allowed to approve")

    @staticmethod
    def _action_for_execution_update(status: str) -> str:
        if status == EXECUTING:
            return "start_execution"
        if status == COMPLETED:
            return "complete_success"
        return "complete_failure"
