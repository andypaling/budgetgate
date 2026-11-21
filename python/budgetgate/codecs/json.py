import dataclasses
import json
import uuid
from typing import Any

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
                obj = {
                    "id": reply.id,
                    "ok": False,
                    "error": reply.code,
                    "message": reply.message,
                }
            case _:
                fields = dataclasses.asdict(reply)
                obj = {
                    "id": fields.pop("id"),
                    "ok": True,
                    **fields,
                }

        return json.dumps(obj, default=_json_default).encode("utf-8")

    # TODO
    def decode_reply[R: BaseReply](
        self, payload: bytes, expected: type[R]
    ) -> R | ErrorReply: ...  # ty: ignore[invalid-implicit-return-in-function-with-stub-body]

    # TODO
    def encode_request(self, request: Request) -> bytes: ...  # ty: ignore[invalid-implicit-return-in-function-with-stub-body]


def _json_default(value: object) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"can't encode {type(value).__name__}")
