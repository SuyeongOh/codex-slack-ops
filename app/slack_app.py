from __future__ import annotations

import logging

from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

from .exceptions import ApprovalForbidden, ApprovalNotFound
from .services.approval_service import ApprovalService


def build_slack_handler(*, bot_token: str, signing_secret: str, approval_service: ApprovalService) -> AsyncSlackRequestHandler:
    slack_app = AsyncApp(token=bot_token, signing_secret=signing_secret)
    logger = logging.getLogger(__name__)

    @slack_app.action("approve_request")
    async def approve_request(ack, body):
        await ack()
        action = body["actions"][0]
        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]

        try:
            result = await approval_service.approve_request(action["value"], user_id)
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text=result.feedback,
            )
        except ApprovalForbidden:
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text="You are not allowed to approve this request.",
            )
        except ApprovalNotFound:
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text="Approval request not found.",
            )
        except Exception:
            logger.exception("Failed to approve request")
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text="Approval handling failed. Check the service logs.",
            )

    @slack_app.action("reject_request")
    async def reject_request(ack, body):
        await ack()
        action = body["actions"][0]
        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]

        try:
            result = await approval_service.reject_request(action["value"], user_id)
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text=result.feedback,
            )
        except ApprovalForbidden:
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text="You are not allowed to reject this request.",
            )
        except ApprovalNotFound:
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text="Approval request not found.",
            )
        except Exception:
            logger.exception("Failed to reject request")
            await approval_service.slack_service.post_ephemeral_feedback(
                channel_id=channel_id,
                user_id=user_id,
                text="Reject handling failed. Check the service logs.",
            )

    @slack_app.action("view_details")
    async def view_details(ack, body):
        await ack()
        action = body["actions"][0]
        approval = await approval_service.get_request(action["value"])
        await approval_service.slack_service.open_details_modal(
            trigger_id=body["trigger_id"],
            approval=approval,
        )

    return AsyncSlackRequestHandler(slack_app)
