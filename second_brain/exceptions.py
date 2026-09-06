# Domain exceptions for SecondBrainSearch.
"""Domain exceptions used by SecondBrainSearch services."""

"""Domain exceptions used by SecondBrainSearch services."""


class SecondBrainError(Exception):
    """Base application error."""


class ValidationError(SecondBrainError):
    """Input fails a business-rule validation."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class ConflictError(SecondBrainError):
    """Requested operation conflicts with current application state."""


class NotReadyError(SecondBrainError):
    """Index or service is not ready for the requested operation."""


class NotFoundError(SecondBrainError):
    """Requested resource does not exist."""


class ConfirmationRequiredError(SecondBrainError):
    """Destructive action requires explicit confirmation."""


class SecurityError(SecondBrainError):
    """A security boundary was violated."""
