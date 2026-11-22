import json
import uuid
from dataclasses import asdict
from typing import Any, Literal, overload

from budgetgate import messages
from budgetgate.codecs.base import Codec
from budgetgate.messages import (
    BaseReply,
    Commit,
    ErrorReply,
    Hello,
    Op,
    ProtocolError,
    ProtocolErrorCode,
    Release,
    Reply,
    Request,
    ReservationId,
    Reserve,
    SetLimit,
    View,
)


def _parse_object(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
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


@overload
def _read_id(obj: dict[str, Any], *, allow_null: Literal[False] = False) -> int: ...
@overload
def _read_id(obj: dict[str, Any], *, allow_null: Literal[True]) -> int | None: ...
def _read_id(obj: dict[str, Any], *, allow_null: bool = False) -> int | None:
    """Read the message id. With allow_null, an explicit null is accepted (error
    replies to unreadable requests); a missing id is always an error."""
    if "id" not in obj:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, "missing `id`")

    message_id = obj["id"]
    if message_id is None and allow_null:
        return None
    if type(message_id) is not int:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, "'id' must be an integer")
    return message_id


def _read_ok(obj: dict[str, Any]) -> bool:
    if "ok" not in obj:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, "missing `ok`")

    ok = obj["ok"]
    if type(ok) is not bool:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, "'ok' must be an bool")
    return ok


def _int(key: str, value: Any) -> int:
    if type(value) is not int:
        raise ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, f"'{key}' must be an integer"
        )
    return value


def _str(key: str, value: Any) -> str:
    if type(value) is not str:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, f"'{key}' must be a string")
    return value


def _uuid(key: str, value: Any) -> ReservationId:
    if type(value) is not str:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, f"'{key}' must be a string")
    try:
        return ReservationId(uuid.UUID(value))
    except ValueError as e:
        raise ProtocolError(
            ProtocolErrorCode.BAD_REQUEST, f"Unable to parse '{key}' as uuid: {e}"
        ) from None


def _error_code(value: Any) -> ProtocolErrorCode:
    if type(value) is not str:
        raise ProtocolError(ProtocolErrorCode.BAD_REQUEST, "`error` must be a string")
    return ProtocolErrorCode.from_wire(value)


class JsonCodec(Codec):
    FORMAT = b"J"

    def decode_request(self, payload: bytes) -> Request:
        obj = _parse_object(payload)
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
                case Op.HELLO:
                    return Hello(
                        id=request_id,
                        version=_int("version", obj.get("version")),
                    )
                case Op.RESERVE:
                    return Reserve(
                        id=request_id,
                        key=_str("key", obj.get("key")),
                        amount=_int("amount", obj.get("amount")),
                    )
                case Op.COMMIT:
                    return Commit(
                        id=request_id,
                        reservation_id=_uuid(
                            "reservation_id", obj.get("reservation_id")
                        ),
                        actual=_int("actual", obj.get("actual")),
                    )
                case Op.RELEASE:
                    return Release(
                        id=request_id,
                        reservation_id=_uuid(
                            "reservation_id", obj.get("reservation_id")
                        ),
                    )
                case Op.SET_LIMIT:
                    return SetLimit(
                        id=request_id,
                        key=_str("key", obj.get("key")),
                        limit=_int("limit", obj.get("limit")),
                    )
                case Op.VIEW:
                    return View(
                        id=request_id,
                        key=_str("key", obj.get("key")),
                    )
        except ProtocolError as e:
            e.request_id = request_id
            raise

    def encode_reply(self, reply: Reply) -> bytes:
        match reply:
            case ErrorReply():
                if reply.code is ProtocolErrorCode.UNRECOGNISED:
                    raise ValueError("the server never sends UNRECOGNISED")
                obj = {
                    "id": reply.id,
                    "ok": False,
                    "error": reply.code,
                    "message": reply.message,
                }
            case _:
                fields = asdict(reply)
                obj = {
                    "id": fields.pop("id"),
                    "ok": True,
                    **fields,
                }

        return json.dumps(obj, default=_json_default).encode("utf-8")

    def decode_reply[R: BaseReply](
        self, payload: bytes, expected: type[R]
    ) -> R | ErrorReply:
        obj = _parse_object(payload)

        ok = _read_ok(obj)

        if not ok:
            return _error_reply(obj)
        else:
            id = _read_id(obj)
            try:
                return expected(id=id, **_ok_fields(obj, expected))
            except ProtocolError as e:
                e.request_id = id
                raise

    def encode_request(self, request: Request) -> bytes:
        fields = asdict(request)
        obj = {"id": fields.pop("id"), "op": request.OP, **fields}
        return json.dumps(obj, default=_json_default).encode("utf-8")


def _json_default(value: object) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"can't encode {type(value).__name__}")


def _error_reply(obj: dict[str, Any]) -> ErrorReply:
    id = _read_id(obj, allow_null=True)
    try:
        error = _str("error", obj.get("error"))
        message = _str("message", obj.get("message"))
    except ProtocolError as e:
        e.request_id = id
        raise
    return ErrorReply(id=id, code=ProtocolErrorCode.from_wire(error), message=message)


_VIEW_FIELDS = ("limit", "used", "committed", "reserved")


def _ok_fields(obj: dict[str, Any], expected: type[BaseReply]) -> dict[str, Any]:
    """Validate the fields of a success reply of type `expected` (all bar id)."""
    match expected:
        case messages.HelloOk:
            return {"version": _int("version", obj.get("version"))}
        case messages.ReserveOk:
            return {
                "reservation_id": _uuid("reservation_id", obj.get("reservation_id"))
            }
        case messages.ViewOk:
            return {name: _int(name, obj.get(name)) for name in _VIEW_FIELDS}
        case messages.CommitOk | messages.ReleaseOk | messages.SetLimitOk:
            return {}
        case _:
            raise TypeError(f"{expected.__name__} is not a reply type")
