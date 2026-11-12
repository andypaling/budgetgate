import json
from typing import Any

import budgetgate._budgetcore
import pytest
from budgetgate import BudgetError, Store
from budgetgate.server import STORE_ERRORS, Session


def send(session: Session, request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Send one request to a session; return the parsed reply and the close flag."""
    reply, close = session.handle_line(json.dumps(request).encode())
    return json.loads(reply), close


def hello(session: Session) -> None:
    reply, _ = send(session, {"id": 0, "op": "hello", "version": 1})
    assert reply["ok"]


def reserve(session: Session, amount: int) -> str:
    reply, _ = send(
        session, {"id": 1, "op": "reserve", "key": "test_key", "amount": amount}
    )
    assert reply["ok"]
    return reply["reservation_id"]


def view(session: Session) -> dict[str, Any]:
    reply, _ = send(session, {"id": 9, "op": "view", "key": "test_key"})
    return reply


@pytest.fixture
def greeted(store: Store) -> Session:
    """A session on the shared `store` fixture that has already said hello."""
    session = Session(store)
    hello(session)
    return session


def test_hello_succeeds(store: Store) -> None:
    reply, close = send(Session(store), {"id": 0, "op": "hello", "version": 1})
    assert reply == {"id": 0, "ok": True, "version": 1}
    assert not close


def test_request_before_hello_is_rejected(store: Store) -> None:
    reply, close = send(Session(store), {"id": 1, "op": "view", "key": "test_key"})
    assert reply["error"] == "handshake_required"
    assert reply["id"] == 1
    assert not close


def test_wrong_version_closes(store: Store) -> None:
    reply, close = send(Session(store), {"id": 0, "op": "hello", "version": 2})
    assert reply["error"] == "unsupported_version"
    assert close


def test_reserve_tracks_ownership(greeted: Session) -> None:
    reservation_id = reserve(greeted, 4)
    assert {str(rid) for rid in greeted.owned} == {reservation_id}


def test_commit_by_another_session_is_rejected(greeted: Session, store: Store) -> None:
    reservation_id = reserve(greeted, 4)
    other = Session(store)
    hello(other)

    reply, _ = send(
        other,
        {"id": 2, "op": "commit", "reservation_id": reservation_id, "actual": 1},
    )

    assert reply["error"] == "unknown_reservation"
    assert view(greeted)["reserved"] == 4


def test_failed_commit_keeps_ownership(greeted: Session) -> None:
    reservation_id = reserve(greeted, 4)

    reply, _ = send(
        greeted,
        {"id": 2, "op": "commit", "reservation_id": reservation_id, "actual": 99},
    )
    assert reply["error"] == "invalid_amount"
    assert len(greeted.owned) == 1

    reply, _ = send(
        greeted, {"id": 3, "op": "release", "reservation_id": reservation_id}
    )
    assert reply["ok"]


def test_commit_removes_ownership(greeted: Session) -> None:
    reservation_id = reserve(greeted, 4)
    commit = {"id": 2, "op": "commit", "reservation_id": reservation_id, "actual": 4}

    first, _ = send(greeted, commit)
    second, _ = send(greeted, commit)

    assert first["ok"]
    assert second["error"] == "unknown_reservation"
    assert not greeted.owned


def test_store_error_maps_to_code(greeted: Session) -> None:
    reply, close = send(
        greeted, {"id": 5, "op": "reserve", "key": "test_key", "amount": 99}
    )
    assert reply["error"] == "budget_exceeded"
    assert reply["id"] == 5
    assert not close


def test_bad_line_does_not_close(greeted: Session) -> None:
    reply, close = greeted.handle_line(b"not json\n")
    assert json.loads(reply)["error"] == "bad_request"
    assert json.loads(reply)["id"] is None
    assert not close


def test_every_store_error_has_a_wire_code() -> None:
    store_errors = {
        obj
        for obj in vars(budgetgate._budgetcore).values()
        if isinstance(obj, type)
        and issubclass(obj, BudgetError)
        and obj is not BudgetError
    }
    assert store_errors == set(STORE_ERRORS)


def test_close_releases_everything(greeted: Session) -> None:
    reserve(greeted, 3)
    reserve(greeted, 4)

    greeted.close()

    assert view(greeted)["reserved"] == 0
    assert not greeted.owned


def test_close_leaves_other_sessions_alone(greeted: Session, store: Store) -> None:
    other = Session(store)
    hello(other)
    reserve(greeted, 3)
    reserve(other, 4)

    greeted.close()

    assert view(other)["reserved"] == 4


@pytest.mark.parametrize(
    "amount", [2**63, -(2**62) - 1], ids=["above-max", "below-min"]
)
def test_out_of_range_amount_is_invalid_amount(greeted: Session, amount):
    reply, close = send(
        greeted, {"id": 5, "op": "reserve", "key": "test_key", "amount": amount}
    )

    assert reply["ok"] is False
    assert reply["error"] == "invalid_amount"
    assert reply["id"] == 5
    assert not close
    assert not greeted.owned
