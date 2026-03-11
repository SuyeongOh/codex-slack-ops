class ApprovalError(Exception):
    """Base approval exception."""


class ApprovalNotFound(ApprovalError):
    """Raised when an approval request does not exist."""


class ApprovalForbidden(ApprovalError):
    """Raised when a user cannot perform an approval action."""


class InvalidApprovalTransition(ApprovalError):
    """Raised when the requested state change is invalid."""
