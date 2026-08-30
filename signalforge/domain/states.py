"""Shared domain state-machine errors."""


class InvalidStateTransition(ValueError):
    """Raised when a domain entity is asked to perform an illegal state transition."""
