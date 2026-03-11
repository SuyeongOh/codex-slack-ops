from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.slack_ui import build_approval_blocks, build_thread_reply_text


def make_approval(**overrides):
    base = {
        "id": "apr_test_123",
        "title": "Test approval",
        "command": "echo test",
        "rationale": "verify ui",
        "risk_level": "medium",
        "requested_by": "codex-runner",
        "status": "pending",
        "context": {"cwd": "/tmp"},
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "approved_by": None,
        "rejected_by": None,
        "result_summary": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_pending_blocks_include_actions():
    approval = make_approval(status="pending")
    blocks = build_approval_blocks(approval)
    assert any(block["type"] == "actions" for block in blocks)


def test_approved_blocks_replace_actions_with_decision_section():
    approval = make_approval(status="approved", approved_by="U123")
    blocks = build_approval_blocks(approval)
    assert not any(block["type"] == "actions" for block in blocks)
    assert any("Action buttons have been disabled" in block["text"]["text"] for block in blocks if block["type"] == "section")


def test_thread_reply_text_mentions_buttons_disabled():
    approval = make_approval(status="rejected", rejected_by="U456")
    text = build_thread_reply_text(approval)
    assert "Buttons are now disabled" in text
