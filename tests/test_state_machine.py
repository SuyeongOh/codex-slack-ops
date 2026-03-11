from app.state_machine import (
    APPROVED,
    COMPLETED,
    EXECUTING,
    EXPIRED,
    FAILED,
    PENDING,
    REJECTED,
    apply_transition,
    expire_if_needed,
)


def test_pending_can_be_approved():
    result = apply_transition(PENDING, "approve")
    assert result.changed is True
    assert result.status == APPROVED


def test_pending_can_be_rejected():
    result = apply_transition(PENDING, "reject")
    assert result.changed is True
    assert result.status == REJECTED


def test_pending_expires_before_approval():
    result = apply_transition(PENDING, "approve", is_expired=True)
    assert result.changed is True
    assert result.status == EXPIRED


def test_only_approved_can_start_execution():
    invalid = apply_transition(PENDING, "start_execution")
    assert invalid.changed is False

    valid = apply_transition(APPROVED, "start_execution")
    assert valid.changed is True
    assert valid.status == EXECUTING


def test_only_executing_can_finish():
    success = apply_transition(EXECUTING, "complete_success")
    assert success.changed is True
    assert success.status == COMPLETED

    failure = apply_transition(EXECUTING, "complete_failure")
    assert failure.changed is True
    assert failure.status == FAILED


def test_expire_if_needed_only_changes_pending():
    unchanged = expire_if_needed(APPROVED, is_expired=True)
    assert unchanged.changed is False

    expired = expire_if_needed(PENDING, is_expired=True)
    assert expired.changed is True
    assert expired.status == EXPIRED
