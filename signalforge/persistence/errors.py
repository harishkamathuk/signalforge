"""SQL-free errors exposed by the SignalForge persistence boundary."""


class PersistenceError(RuntimeError):
    """Base error for persistence-boundary failures."""


class PersistenceConflictError(PersistenceError):
    """Stored state contradicts the requested logical write."""


class ContradictoryFactError(PersistenceConflictError):
    """An immutable logical identity is already bound to different facts."""


class PersistenceDependencyError(PersistenceError):
    """A required persisted parent or provenance record is absent."""
