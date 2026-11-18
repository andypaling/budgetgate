from typing import assert_never

from budgetgate import (
    BudgetError,
    BudgetExceeded,
    InvalidAmount,
    Store,
    UnknownKey,
    UnknownReservation,
)
from budgetgate.messages import (
    Commit,
    CommitOk,
    ErrorReply,
    Hello,
    HelloOk,
    ProtocolError,
    ProtocolErrorCode,
    Release,
    ReleaseOk,
    Reply,
    Request,
    ReservationId,
    Reserve,
    ReserveOk,
    SetLimit,
    SetLimitOk,
    View,
    ViewOk,
)

STORE_ERRORS: dict[type[BudgetError], ProtocolErrorCode] = {
    UnknownKey: ProtocolErrorCode.UNKNOWN_KEY,
    InvalidAmount: ProtocolErrorCode.INVALID_AMOUNT,
    BudgetExceeded: ProtocolErrorCode.BUDGET_EXCEEDED,
    UnknownReservation: ProtocolErrorCode.UNKNOWN_RESERVATION,
}

PROTOCOL_VERSION = 1


class Session:
    """One client connection: handshake state and the reservation it owns."""

    def __init__(self, store: Store):
        self._store = store
        self._greeted = False
        self.owned: set[ReservationId] = set()
        self.should_close: bool = False

    def handle(self, request: Request) -> Reply:
        """Handle one decoded request and return its reply.

        Never raises for protocol or store errors: both came back as an ErrorReply.
        Sets should_close when the connection must end after this reply.
        """
        try:
            if not self._greeted and not isinstance(request, Hello):
                raise ProtocolError(
                    ProtocolErrorCode.HANDSHAKE_REQUIRED,
                    "send hello before any other request",
                    request.id,
                )

            match request:
                case Hello():
                    return self._hello(request)
                case Commit():
                    return self._commit(request)
                case Release():
                    return self._release(request)
                case Reserve():
                    return self._reserve(request)
                case SetLimit():
                    return self._set_limit(request)
                case View():
                    return self._view(request)
                case _:
                    assert_never(request)
        except ProtocolError as e:
            return ErrorReply.from_protocol_error(e)
        except BudgetError as e:
            return ErrorReply(id=request.id, code=STORE_ERRORS[type(e)], message=str(e))

    def close(self) -> None:
        """Release every reservation this connection still owns"""
        for reservation_id in self.owned:
            try:
                self._store.release(reservation_id)
            except UnknownReservation:
                pass
        self.owned.clear()

    def _hello(self, request: Hello) -> HelloOk:
        if request.version != PROTOCOL_VERSION:
            self.should_close = True
            raise ProtocolError(
                ProtocolErrorCode.UNSUPPORTED_VERSION,
                f"protocol version {request.version} is not supported",
                request.id,
            )
        self._greeted = True
        return HelloOk(id=request.id, version=PROTOCOL_VERSION)

    def _commit(self, request: Commit) -> CommitOk:
        self._check_owned(request.reservation_id, request.id)
        self._store.commit(request.reservation_id, request.actual)
        self.owned.remove(request.reservation_id)
        return CommitOk(id=request.id)

    def _release(self, request: Release) -> ReleaseOk:
        self._check_owned(request.reservation_id, request.id)
        self._store.release(request.reservation_id)
        self.owned.remove(request.reservation_id)
        return ReleaseOk(id=request.id)

    def _reserve(self, request: Reserve) -> ReserveOk:
        reservation_id = ReservationId(self._store.reserve(request.key, request.amount))
        self.owned.add(reservation_id)
        return ReserveOk(id=request.id, reservation_id=reservation_id)

    def _set_limit(self, request: SetLimit) -> SetLimitOk:
        self._store.set_limit(request.key, request.limit)
        return SetLimitOk(id=request.id)

    def _view(self, request: View) -> ViewOk:
        budget_view = self._store.view(request.key)
        return ViewOk(
            id=request.id,
            limit=budget_view.limit,
            used=budget_view.used,
            committed=budget_view.committed,
            reserved=budget_view.reserved,
        )

    def _check_owned(self, reservation_id: ReservationId, request_id: int) -> None:
        """Treat another connection's reservation exactly like one that doesn't exist"""
        if reservation_id not in self.owned:
            raise ProtocolError(
                ProtocolErrorCode.UNKNOWN_RESERVATION,
                "no live reservation with this id",
                request_id,
            )
