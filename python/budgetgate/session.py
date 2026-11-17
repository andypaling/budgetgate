import uuid

from budgetgate import (
    BudgetError,
    BudgetExceeded,
    InvalidAmount,
    Store,
    UnknownKey,
    UnknownReservation,
)
from budgetgate.protocol import (
    Commit,
    Hello,
    ProtocolError,
    ProtocolErrorCode,
    Release,
    Reserve,
    SetLimit,
    View,
    decode,
    encode_error,
    encode_ok,
    encode_protocol_error,
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
        self.store = store
        self.greeted = False
        self.owned: set[uuid.UUID] = set()

    def handle_line(self, line: bytes) -> tuple[bytes, bool]:
        """Handle one request line. Returns (reply, close_connection)"""
        try:
            request = decode(line)
            if not self.greeted and not isinstance(request, Hello):
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
        except ProtocolError as e:
            return encode_protocol_error(e), e.close
        except BudgetError as e:
            return encode_error(
                request_id=request.id,
                code=STORE_ERRORS[type(e)],
                message=str(e),
            ), False

    def close(self) -> None:
        """Release every reservation this connection still owns"""
        for reservation_id in self.owned:
            try:
                self.store.release(reservation_id)
            except UnknownReservation:
                pass
        self.owned.clear()

    def _hello(self, request: Hello) -> tuple[bytes, bool]:
        if request.version != PROTOCOL_VERSION:
            raise ProtocolError(
                ProtocolErrorCode.UNSUPPORTED_VERSION,
                f"protocol version {request.version} is not supported",
                request.id,
                close=True,
            )
        self.greeted = True
        return encode_ok(request.id, version=PROTOCOL_VERSION), False

    def _commit(self, request: Commit) -> tuple[bytes, bool]:
        self._check_owned(request.reservation_id, request.id)
        self.store.commit(request.reservation_id, request.actual)
        self.owned.remove(request.reservation_id)
        return encode_ok(request.id), False

    def _release(self, request: Release) -> tuple[bytes, bool]:
        self._check_owned(request.reservation_id, request.id)
        self.store.release(request.reservation_id)
        self.owned.remove(request.reservation_id)
        return encode_ok(request.id), False

    def _reserve(self, request: Reserve) -> tuple[bytes, bool]:
        reservation_id = self.store.reserve(request.key, request.amount)
        self.owned.add(reservation_id)
        return encode_ok(request.id, reservation_id=reservation_id), False

    def _set_limit(self, request: SetLimit) -> tuple[bytes, bool]:
        self.store.set_limit(request.key, request.limit)
        return encode_ok(request.id), False

    def _view(self, request: View) -> tuple[bytes, bool]:
        budget_view = self.store.view(request.key)
        return encode_ok(
            request.id,
            limit=budget_view.limit,
            used=budget_view.used,
            committed=budget_view.committed,
            reserved=budget_view.reserved,
        ), False

    def _check_owned(self, reservation_id: uuid.UUID, request_id: int) -> None:
        """Treat another connection's reservation exactly like one that doesn't exist"""
        if reservation_id not in self.owned:
            raise ProtocolError(
                ProtocolErrorCode.UNKNOWN_RESERVATION,
                "no live reservation with this id",
                request_id,
            )
