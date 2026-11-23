import uuid
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import ClassVar, NewType, Self

PROTOCOL_VERSION = 1


class ProtocolErrorCode(StrEnum):
    BAD_REQUEST = auto()
    UNKNOWN_KEY = auto()
    INVALID_AMOUNT = auto()
    BUDGET_EXCEEDED = auto()
    UNKNOWN_RESERVATION = auto()
    HANDSHAKE_REQUIRED = auto()
    UNSUPPORTED_VERSION = auto()

    UNRECOGNISED = (
        auto()
    )  # Client-side only - server sent a code the client doesn't know

    @classmethod
    def from_wire(cls, value: str) -> ProtocolErrorCode:
        try:
            return cls(value)
        except ValueError:
            return cls.UNRECOGNISED


class ProtocolError(Exception):
    def __init__(
        self,
        code: ProtocolErrorCode,
        message: str,
        request_id: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


class Op(StrEnum):
    HELLO = auto()
    SET_LIMIT = auto()
    RESERVE = auto()
    COMMIT = auto()
    RELEASE = auto()
    VIEW = auto()


ReservationId = NewType("ReservationId", uuid.UUID)


@dataclass(frozen=True, kw_only=True, slots=True)
class BaseRequest:
    id: int


@dataclass(frozen=True, kw_only=True, slots=True)
class Hello(BaseRequest):
    OP: ClassVar[Op] = Op.HELLO
    version: int


@dataclass(frozen=True, kw_only=True, slots=True)
class Reserve(BaseRequest):
    OP: ClassVar[Op] = Op.RESERVE
    key: str
    amount: int


@dataclass(frozen=True, kw_only=True, slots=True)
class Commit(BaseRequest):
    OP: ClassVar[Op] = Op.COMMIT
    reservation_id: ReservationId
    actual: int


@dataclass(frozen=True, kw_only=True, slots=True)
class Release(BaseRequest):
    OP: ClassVar[Op] = Op.RELEASE
    reservation_id: ReservationId


@dataclass(frozen=True, kw_only=True, slots=True)
class SetLimit(BaseRequest):
    OP: ClassVar[Op] = Op.SET_LIMIT
    key: str
    limit: int


@dataclass(frozen=True, kw_only=True, slots=True)
class View(BaseRequest):
    OP: ClassVar[Op] = Op.VIEW
    key: str


Request = Hello | SetLimit | Reserve | Commit | Release | View


@dataclass(frozen=True, kw_only=True, slots=True)
class BaseReply:
    id: int


@dataclass(frozen=True, kw_only=True, slots=True)
class HelloOk(BaseReply):
    version: int


@dataclass(frozen=True, kw_only=True, slots=True)
class CommitOk(BaseReply): ...


@dataclass(frozen=True, kw_only=True, slots=True)
class ReserveOk(BaseReply):
    reservation_id: ReservationId


@dataclass(frozen=True, kw_only=True, slots=True)
class ReleaseOk(BaseReply): ...


@dataclass(frozen=True, kw_only=True, slots=True)
class SetLimitOk(BaseReply): ...


@dataclass(frozen=True, kw_only=True, slots=True)
class ViewOk(BaseReply):
    limit: int
    used: int
    committed: int
    reserved: int


@dataclass(frozen=True, kw_only=True, slots=True)
class ErrorReply:
    id: int | None
    code: ProtocolErrorCode
    message: str

    @classmethod
    def from_protocol_error(cls, err: ProtocolError) -> Self:
        return cls(id=err.request_id, code=err.code, message=err.message)


Reply = HelloOk | SetLimitOk | ReserveOk | CommitOk | ReleaseOk | ViewOk | ErrorReply
