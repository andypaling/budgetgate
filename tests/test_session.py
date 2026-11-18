import budgetgate._budgetcore
import pytest
from budgetgate import BudgetError, Store
from budgetgate.messages import (
    Commit,
    ErrorReply,
    Hello,
    HelloOk,
    ProtocolErrorCode,
    Release,
    ReleaseOk,
    Reply,
    ReservationId,
    Reserve,
    ReserveOk,
    View,
    ViewOk,
)
from budgetgate.session import STORE_ERRORS, Session

KEY = "test_key"


def hello(session: Session) -> None:
    assert session.handle(Hello(id=0, version=1)) == HelloOk(id=0, version=1)


def reserve(session: Session, amount: int) -> ReservationId:
    reply = session.handle(Reserve(id=1, key=KEY, amount=amount))
    assert isinstance(reply, ReserveOk), reply
    return ReservationId(reply.reservation_id)


def view(session: Session) -> ViewOk:
    reply = session.handle(View(id=9, key=KEY))
    assert isinstance(reply, ViewOk), reply
    return reply


def error_code(reply: Reply) -> ProtocolErrorCode:
    assert isinstance(reply, ErrorReply), reply
    return reply.code


@pytest.fixture
def greeted(store: Store) -> Session:
    """A session on the shared `store` fixture that has already said hello."""
    session = Session(store)
    hello(session)
    return session


def test_hello_succeeds(store: Store) -> None:
    session = Session(store)
    assert session.handle(Hello(id=0, version=1)) == HelloOk(id=0, version=1)
    assert not session.should_close


def test_request_before_hello_is_rejected(store: Store) -> None:
    session = Session(store)
    reply = session.handle(View(id=1, key=KEY))
    assert error_code(reply) == ProtocolErrorCode.HANDSHAKE_REQUIRED
    assert reply.id == 1
    assert not session.should_close


def test_wrong_version_closes(store: Store) -> None:
    session = Session(store)
    reply = session.handle(Hello(id=0, version=2))
    assert error_code(reply) == ProtocolErrorCode.UNSUPPORTED_VERSION
    assert session.should_close


def test_reserve_tracks_ownership(greeted: Session) -> None:
    reservation_id = reserve(greeted, 4)
    assert greeted.owned == {reservation_id}


def test_commit_by_another_session_is_rejected(greeted: Session, store: Store) -> None:
    reservation_id = reserve(greeted, 4)
    other = Session(store)
    hello(other)

    reply = other.handle(Commit(id=2, reservation_id=reservation_id, actual=1))

    assert error_code(reply) == ProtocolErrorCode.UNKNOWN_RESERVATION
    assert view(greeted).reserved == 4


def test_failed_commit_keeps_ownership(greeted: Session) -> None:
    reservation_id = reserve(greeted, 4)

    reply = greeted.handle(Commit(id=2, reservation_id=reservation_id, actual=99))
    assert error_code(reply) == ProtocolErrorCode.INVALID_AMOUNT
    assert greeted.owned == {reservation_id}

    reply = greeted.handle(Release(id=3, reservation_id=reservation_id))
    assert reply == ReleaseOk(id=3)


def test_commit_removes_ownership(greeted: Session) -> None:
    reservation_id = reserve(greeted, 4)
    commit = Commit(id=2, reservation_id=reservation_id, actual=4)

    first = greeted.handle(commit)
    second = greeted.handle(commit)

    assert not isinstance(first, ErrorReply), first
    assert error_code(second) == ProtocolErrorCode.UNKNOWN_RESERVATION
    assert not greeted.owned


def test_store_error_maps_to_code(greeted: Session) -> None:
    reply = greeted.handle(Reserve(id=5, key=KEY, amount=99))
    assert error_code(reply) == ProtocolErrorCode.BUDGET_EXCEEDED
    assert reply.id == 5
    assert not greeted.should_close


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

    assert view(greeted).reserved == 0
    assert not greeted.owned


def test_close_leaves_other_sessions_alone(greeted: Session, store: Store) -> None:
    other = Session(store)
    hello(other)
    reserve(greeted, 3)
    reserve(other, 4)

    greeted.close()

    assert view(other).reserved == 4


@pytest.mark.parametrize(
    "amount", [2**63, -(2**62) - 1], ids=["above-max", "below-min"]
)
def test_out_of_range_amount_is_invalid_amount(greeted: Session, amount: int) -> None:
    reply = greeted.handle(Reserve(id=5, key=KEY, amount=amount))

    assert error_code(reply) == ProtocolErrorCode.INVALID_AMOUNT
    assert reply.id == 5
    assert not greeted.should_close
    assert not greeted.owned
