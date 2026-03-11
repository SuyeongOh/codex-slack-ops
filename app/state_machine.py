from __future__ import annotations

from dataclasses import dataclass


PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"
EXECUTING = "executing"
COMPLETED = "completed"
FAILED = "failed"


@dataclass(frozen=True)
class TransitionResult:
    status: str
    changed: bool
    reason: str


def expire_if_needed(status: str, *, is_expired: bool) -> TransitionResult:
    if status == PENDING and is_expired:
        return TransitionResult(status=EXPIRED, changed=True, reason="approval expired")
    return TransitionResult(status=status, changed=False, reason="not expired")


def apply_transition(status: str, action: str, *, is_expired: bool = False) -> TransitionResult:
    if status == PENDING and is_expired:
        return TransitionResult(status=EXPIRED, changed=True, reason="approval expired")

    if action == "approve":
        if status == PENDING:
            return TransitionResult(status=APPROVED, changed=True, reason="approved")
        return TransitionResult(status=status, changed=False, reason="only pending requests can be approved")

    if action == "reject":
        if status == PENDING:
            return TransitionResult(status=REJECTED, changed=True, reason="rejected")
        return TransitionResult(status=status, changed=False, reason="only pending requests can be rejected")

    if action == "start_execution":
        if status == APPROVED:
            return TransitionResult(status=EXECUTING, changed=True, reason="execution started")
        return TransitionResult(status=status, changed=False, reason="only approved requests can execute")

    if action == "complete_success":
        if status == EXECUTING:
            return TransitionResult(status=COMPLETED, changed=True, reason="execution completed")
        return TransitionResult(status=status, changed=False, reason="only executing requests can complete")

    if action == "complete_failure":
        if status == EXECUTING:
            return TransitionResult(status=FAILED, changed=True, reason="execution failed")
        return TransitionResult(status=status, changed=False, reason="only executing requests can fail")

    raise ValueError("unknown action")
