from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List

from .models import ApprovalRequest, ensure_utc


STATUS_LABELS = {
    "pending": ":hourglass_flowing_sand: Pending approval",
    "approved": ":white_check_mark: Approved",
    "rejected": ":x: Rejected",
    "expired": ":alarm_clock: Expired",
    "executing": ":runner: Executing",
    "completed": ":large_green_circle: Completed",
    "failed": ":red_circle: Failed",
}


def _truncate(text: str, limit: int = 100) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_context(context: Dict[str, Any]) -> str:
    if not context:
        return "_none_"
    parts = []
    for key, value in context.items():
        parts.append(f"*{key}:* `{value}`")
    return "\n".join(parts)


def build_approval_blocks(approval: ApprovalRequest) -> List[dict]:
    expires_text = ensure_utc(approval.expires_at).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header = (
        f"*Codex approval required*\n"
        f"*Status:* {STATUS_LABELS.get(approval.status, approval.status)}\n"
        f"*Risk:* `{approval.risk_level}`\n"
        f"*Requested by:* `{approval.requested_by}`\n"
        f"*Expires:* `{expires_text}`"
    )
    summary = (
        f"*Title:* {approval.title}\n"
        f"*Rationale:* {approval.rationale}\n"
        f"*Command:* `{_truncate(approval.command, 140)}`"
    )
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Context*\n{_format_context(approval.context)}"}},
    ]

    if approval.status == "pending":
        blocks.append(
            {
                "type": "actions",
                "block_id": "approval_actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_request",
                        "value": approval.id,
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Approve command?"},
                            "text": {
                                "type": "mrkdwn",
                                "text": "This will allow the external runner to execute the proposed command.",
                            },
                            "confirm": {"type": "plain_text", "text": "Approve"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": "reject_request",
                        "value": approval.id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Details"},
                        "action_id": "view_details",
                        "value": approval.id,
                    },
                ],
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Decision*\n{_decision_text(approval)}",
                },
            }
        )

    return blocks


def build_details_modal(approval: ApprovalRequest) -> dict:
    return {
        "type": "modal",
        "callback_id": "approval_details",
        "title": {"type": "plain_text", "text": "Approval details"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Title:* {approval.title}\n"
                        f"*Status:* {STATUS_LABELS.get(approval.status, approval.status)}\n"
                        f"*Risk:* `{approval.risk_level}`\n"
                        f"*Requested by:* `{approval.requested_by}`"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Rationale:*\n{approval.rationale}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Command:*\n```{approval.command}```",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Context:*\n{_format_context(approval.context)}",
                },
            },
        ],
    }


def build_fallback_text(approval: ApprovalRequest) -> str:
    return (
        f"Codex approval required: {approval.title} "
        f"[risk={approval.risk_level}, status={approval.status}]"
    )


def build_thread_reply_text(approval: ApprovalRequest) -> str:
    if approval.status == "approved":
        return (
            f":white_check_mark: Approval recorded for *{approval.title}*.\n"
            f"Approved by <@{approval.approved_by}>.\n"
            "Buttons are now disabled. Runner execution can proceed."
        )
    if approval.status == "rejected":
        return (
            f":x: Request rejected for *{approval.title}*.\n"
            f"Rejected by <@{approval.rejected_by}>.\n"
            "Buttons are now disabled."
        )
    if approval.status == "expired":
        return (
            f":alarm_clock: Approval window expired for *{approval.title}*.\n"
            "Buttons are now disabled."
        )
    if approval.status == "executing":
        return f":runner: Execution started for *{approval.title}*."
    if approval.status == "completed":
        detail = _truncate(approval.result_summary or "Execution completed.", 600)
        return f":large_green_circle: Execution completed for *{approval.title}*.\n```{detail}```"
    if approval.status == "failed":
        detail = _truncate(approval.result_summary or "Execution failed.", 600)
        return f":red_circle: Execution failed for *{approval.title}*.\n```{detail}```"
    return f"Status updated to `{approval.status}` for *{approval.title}*."


def _decision_text(approval: ApprovalRequest) -> str:
    if approval.status == "approved":
        return f"Approved by <@{approval.approved_by}>. Action buttons have been disabled."
    if approval.status == "rejected":
        return f"Rejected by <@{approval.rejected_by}>. Action buttons have been disabled."
    if approval.status == "expired":
        return "Approval window expired. Action buttons have been disabled."
    if approval.status == "executing":
        return "Execution is in progress. Action buttons have been disabled."
    if approval.status in {"completed", "failed"} and approval.result_summary:
        return f"Execution finished. Action buttons have been disabled.\n```{_truncate(approval.result_summary, 400)}```"
    return f"Status is `{approval.status}`."
