import json
import uuid
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any, ClassVar, NewType

ReservationId = NewType("ReservationId", uuid.UUID)


class Op(StrEnum):
    HELLO = auto()
    SET_LIMIT = auto()
    RESERVE = auto()
    COMMIT = auto()
    RELEASE = auto()
    VIEW = auto()


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


class ProtocolErrorCode(StrEnum):
    BAD_REQUEST = auto()
    UNKNOWN_KEY = auto()
    INVALID_AMOUNT = auto()
    BUDGET_EXCEEDED = auto()
    UNKNOWN_RESERVATION = auto()
    HANDSHAKE_REQUIRED = auto()
    UNSUPPORTED_VERSION = auto()


class ProtocolError(Exception):
    def __init__(
        self, code: ProtocolErrorCode, message: str, request_id: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


def _parse_object(line: bytes) -> dict[str, Any]:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, "message is not valid UTF-8"
        ) from None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, f"Invalid JSON {e.msg}"
        ) from None
    if not isinstance(obj, dict):
        raise ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, "message must be a JSON object"
        )

    return obj


def _read_id(obj: dict[str, Any]) -> int:
    request_id = obj.get("id")
    if type(request_id) is not int:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, "'id' must be an integer")
    return request_id


def _int(key: str, value: Any) -> int:
    if type(value) is not int:
        raise ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, f"'{key}' must be an integer"
        )
    return value


def _str(key: str, value: Any) -> str:
    if type(value) is not str:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, f"'{key}' must be an string")
    return value


def _uuid(key: str, value: Any) -> ReservationId:
    if type(value) is not str:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, f"'{key}' must be an string")
    try:
        return ReservationId(uuid.UUID(value))
    except ValueError as e:
        raise ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, f"Unable to parse '{key}' as uuid: {e}"
        )


def decode(line: bytes) -> Request:
    obj = _parse_object(line)
    request_id = _read_id(obj)

    try:
        op = Op(obj.get("op"))
    except ValueError:
        e = ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, f"unknown op: {obj.get('op')!r}"
        )
        e.request_id = request_id
        raise e from None

    try:
        match op:
            case op.HELLO:
                return Hello(
                    id=request_id,
                    version=_int("version", obj.get("version")),
                )
            case op.RESERVE:
                return Reserve(
                    id=request_id,
                    key=_str("key", obj.get("key")),
                    amount=_int("amount", obj.get("amount")),
                )
            case op.COMMIT:
                return Commit(
                    id=request_id,
                    reservation_id=_uuid("reservation_id", obj.get("reservation_id")),
                    actual=_int("actual", obj.get("actual")),
                )
            case op.RELEASE:
                return Release(
                    id=request_id,
                    reservation_id=_uuid("reservation_id", obj.get("reservation_id")),
                )
            case op.SET_LIMIT:
                return SetLimit(
                    id=request_id,
                    key=_str("key", obj.get("key")),
                    limit=_int("limit", obj.get("limit")),
                )
            case op.VIEW:
                return View(
                    id=request_id,
                    key=_str("key", obj.get("key")),
                )
    except ProtocolError as e:
        e.request_id = request_id
        raise


def encode_ok(request_id: int, **fields: object) -> bytes:
    """Encode a success reply, e.g. encode_ok(2, reservation_id=rid)."""
    keys = fields.keys()
    if "ok" in keys or "id" in keys:
        raise ValueError("reply fields can't be named 'id' or 'ok'")

    reply = {"id": request_id, "ok": True, **fields}
    return json.dumps(reply, default=str).encode("utf-8") + b"\n"


def encode_error(
    request_id: int | None, code: ProtocolErrorCode, message: str
) -> bytes:
    """Encode an error reply. request is None if the request couldn't be read"""
    reply = {"id": request_id, "ok": False, "error": code, "message": message}
    return json.dumps(reply, default=str).encode("utf-8") + b"\n"


def encode_protocol_error(err: ProtocolError) -> bytes:
    return encode_error(err.request_id, err.code, err.message)
