import uuid

import pytest
from budgetgate import (
    BudgetError,
    BudgetExceeded,
    BudgetView,
    InvalidAmount,
    Store,
    UnknownKey,
    UnknownReservation,
)


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda s: s.reserve("missing", 1), UnknownKey),
        (lambda s: s.reserve("test_key", 11), BudgetExceeded),
        (lambda s: s.reserve("test_key", 0), InvalidAmount),
        (lambda s: s.reserve("test_key", -1), InvalidAmount),
        (lambda s: s.release(uuid.uuid4()), UnknownReservation),
    ],
    ids=["unknown-key", "exceeded", "zero-amount", "negative-limit", "forgot-id"],
)
def test_errors_map_to_exceptions(store: Store, call, expected) -> None:
    with pytest.raises(expected) as excinfo:
        call(store)

    assert isinstance(excinfo.value, BudgetError)


def test_reserve_returns_uuid(store: Store) -> None:
    assert isinstance(store.reserve("test_key", 5), uuid.UUID)


def test_reserve_commit_view_round_trip(store: Store) -> None:
    reservation_id = store.reserve("test_key", 5)
    store.commit(reservation_id, actual=4)
    assert store.view("test_key") == BudgetView(
        limit=10, used=4, committed=4, reserved=0
    )


def test_failed_commit_keeps_reservation_live(store: Store) -> None:
    reservation_id = store.reserve("test_key", 5)
    with pytest.raises(InvalidAmount):
        store.commit(reservation_id, 6)

    assert store.view("test_key") == BudgetView(
        limit=10, used=5, committed=0, reserved=5
    )

    store.release(reservation_id)

    assert store.view("test_key") == BudgetView(
        limit=10, used=0, committed=0, reserved=0
    )


def test_repr(store: Store) -> None:
    assert (
        repr(store.view("test_key"))
        == "BudgetView(limit=10, used=0, committed=0, reserved=0)"
    )


LOWER_BOUND_ERR = 2**63
UPPER_BOUND_ERR = -(2**63) - 1


@pytest.mark.parametrize(
    ("call"),
    [
        (lambda s: s.reserve("test_key", LOWER_BOUND_ERR)),
        (lambda s: s.reserve("test_key", UPPER_BOUND_ERR)),
        (lambda s: s.commit(uuid.uuid4(), LOWER_BOUND_ERR)),
        (lambda s: s.commit(uuid.uuid4(), UPPER_BOUND_ERR)),
        (lambda s: s.set_limit("test_key", LOWER_BOUND_ERR)),
        (lambda s: s.set_limit("test_key", UPPER_BOUND_ERR)),
    ],
    ids=[
        "reserve-lower",
        "reserve-upper",
        "commit-lower",
        "commit-upper",
        "set-limit-lower",
        "set-limit-upper",
    ],
)
def test_out_of_range_i64_raises_invalid_amount(store: Store, call) -> None:

    with pytest.raises(InvalidAmount, match="64-bit"):
        call(store)
