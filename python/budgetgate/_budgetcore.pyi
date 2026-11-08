from typing import SupportsIndex, final
from uuid import UUID

__all__ = [
    "BudgetError",
    "BudgetExceeded",
    "BudgetView",
    "InvalidAmount",
    "Store",
    "UnknownKey",
    "UnknownReservation",
]

@final
class BudgetView:
    """
    A snapshot of one budget.
    """
    def __eq__(self, value: object, /) -> bool: ...
    def __hash__(self, /) -> int: ...
    def __ne__(self, value: object, /) -> bool: ...
    def __new__(
        cls,
        /,
        limit: SupportsIndex,
        used: SupportsIndex,
        committed: SupportsIndex,
        reserved: SupportsIndex,
    ) -> BudgetView: ...
    def __repr__(self, /) -> str: ...
    @property
    def committed(self, /) -> int: ...
    @property
    def limit(self, /) -> int: ...
    @property
    def reserved(self, /) -> int: ...
    @property
    def used(self, /) -> int: ...

@final
class Store:
    """
    Shared budgets.
    """
    def __new__(cls, /) -> Store: ...
    def commit(self, /, id: UUID, actual: SupportsIndex) -> None: ...
    def release(self, /, id: UUID) -> None: ...
    def reserve(self, /, key: str, amount: SupportsIndex) -> UUID: ...
    def set_limit(self, /, key: str, limit: SupportsIndex) -> None:
        """
        Create or change a limit.
        """
        ...
    def view(self, /, key: str) -> BudgetView: ...

class BudgetError(Exception):
    """Base class for all budget errors."""

class UnknownKey(BudgetError):
    """No limit has been set for this key."""

class InvalidAmount(BudgetError):
    """An amount or limit was out of range."""

class BudgetExceeded(BudgetError):
    """The reservation would exceed the limit."""

class UnknownReservation(BudgetError):
    """No live reservation has this ID."""
