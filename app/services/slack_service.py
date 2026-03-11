from __future__ import annotations

from typing import Tuple

from slack_sdk.web.async_client import AsyncWebClient

from ..models import ApprovalRequest
from ..slack_ui import (
    build_approval_blocks,
    build_details_modal,
    build_fallback_text,
    build_thread_reply_text,
)


class SlackService:
    def __init__(self, bot_token: str) -> None:
        self.client = AsyncWebClient(token=bot_token)

    async def post_approval_message(self, approval: ApprovalRequest, channel_id: str) -> Tuple[str, str]:
        response = await self.client.chat_postMessage(
            channel=channel_id,
            text=build_fallback_text(approval),
            blocks=build_approval_blocks(approval),
        )
        return response["channel"], response["ts"]

    async def refresh_approval_message(self, approval: ApprovalRequest) -> None:
        if not approval.slack_channel_id or not approval.slack_message_ts:
            return
        await self.client.chat_update(
            channel=approval.slack_channel_id,
            ts=approval.slack_message_ts,
            text=build_fallback_text(approval),
            blocks=build_approval_blocks(approval),
        )

    async def post_ephemeral_feedback(self, *, channel_id: str, user_id: str, text: str) -> None:
        await self.client.chat_postEphemeral(channel=channel_id, user=user_id, text=text)

    async def open_details_modal(self, *, trigger_id: str, approval: ApprovalRequest) -> None:
        await self.client.views_open(trigger_id=trigger_id, view=build_details_modal(approval))

    async def post_status_reply(self, approval: ApprovalRequest) -> None:
        if not approval.slack_channel_id or not approval.slack_message_ts:
            return
        await self.client.chat_postMessage(
            channel=approval.slack_channel_id,
            thread_ts=approval.slack_message_ts,
            text=build_thread_reply_text(approval),
        )
