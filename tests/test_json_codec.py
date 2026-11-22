import json
import uuid
from dataclasses import dataclass

import pytest
from budgetgate.codecs import CODECS, JsonCodec
from budgetgate.messages import (
    BaseReply,
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

RID = ReservationId(uuid.UUID("8379acfd-0dd3-4ec8-9899-c46ee0b00d51"))


@pytest.fixture
def codec() -> JsonCodec:
    return JsonCodec()


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (b'{"id": 0, "op": "hello", "version": 1}', Hello(id=0, version=1)),
        (
            b'{"id": 1, "op": "set_limit", "key": "k", "limit": 100}',
            SetLimit(id=1, key="k", limit=100),
        ),
        (
            b'{"id": 2, "op": "reserve", "key": "k", "amount": 30}',
            Reserve(id=2, key="k", amount=30),
        ),
        (
            b'{"id": 3, "op": "commit", "reservation_id": "8379acfd-0dd3-4ec8-9899-c46ee0b00d51", "actual": 25}',
            Commit(id=3, reservation_id=RID, actual=25),
        ),
        (
            b'{"id": 4, "op": "release", "reservation_id": "8379acfd-0dd3-4ec8-9899-c46ee0b00d51"}',
            Release(id=4, reservation_id=RID),
        ),
        (b'{"id": 5, "op": "view", "key": "k"}', View(id=5, key="k")),
    ],
)
def test_decode_request_valid(line: bytes, expected: Request, codec: JsonCodec) -> None:
    assert codec.decode_request(line) == expected


def test_decode_request_ignores_unknown_fields(codec: JsonCodec) -> None:
    line = b'{"id": 2, "op": "reserve", "key": "k", "amount": 30, "priority": "high"}'
    assert codec.decode_request(line) == Reserve(id=2, key="k", amount=30)


def test_decode_request_leaves_value_checks_to_store(codec: JsonCodec) -> None:
    line = b'{"id": 2, "op": "reserve", "key": "k", "amount": -5}'
    assert codec.decode_request(line) == Reserve(id=2, key="k", amount=-5)


@pytest.mark.parametrize(
    "line",
    [
        b'{"id": 2, "op": "launch_rocket"}',
        b'{"id": 2, "key": "k", "amount": 30}',
        b'{"id": 2, "op": "reserve", "key": "k"}',
        b'{"id": 2, "op": "reserve", "key": "k", "amount": "30"}',
        b'{"id": 2, "op": "reserve", "key": "k", "amount": 30.0}',
        b'{"id": 2, "op": "reserve", "key": "k", "amount": true}',
        b'{"id": 2, "op": "reserve", "key": 123, "amount": 30}',
        b'{"id": 2, "op": "commit", "reservation_id": "not-a-uuid", "actual": 1}',
    ],
    ids=[
        "unknown-op",
        "missing-op",
        "missing-amount",
        "amount-string",
        "amount-float",
        "amount-bool",
        "key-number",
        "bad-uuid",
    ],
)
def test_decode_request_error_keeps_request_id(line: bytes, codec: JsonCodec) -> None:
    with pytest.raises(ProtocolError) as excinfo:
        codec.decode_request(line)
    assert excinfo.value.code == ProtocolErrorCode.BAD_REQUEST
    assert excinfo.value.request_id == 2


@pytest.mark.parametrize(
    "line",
    [
        b'{"id": 2, "op": "reserve"',
        b"[1, 2, 3]",
        b"",
        b'{"op": "view", "key": "k"}',
        b'{"id": "two", "op": "view", "key": "k"}',
        b'{"id": true, "op": "view", "key": "k"}',
        b"\xff\xfe",
    ],
    ids=[
        "invalid-json",
        "not-an-object",
        "empty-line",
        "missing-id",
        "id-string",
        "id-bool",
        "invalid-utf8",
    ],
)
def test_decode_request_error_without_request_id(line: bytes, codec: JsonCodec) -> None:
    with pytest.raises(ProtocolError) as excinfo:
        codec.decode_request(line)
    assert excinfo.value.code == ProtocolErrorCode.BAD_REQUEST
    assert excinfo.value.request_id is None


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (HelloOk(id=0, version=1), {"id": 0, "ok": True, "version": 1}),
        (SetLimitOk(id=1), {"id": 1, "ok": True}),
        (
            ReserveOk(id=2, reservation_id=RID),
            {"id": 2, "ok": True, "reservation_id": str(RID)},
        ),
        (CommitOk(id=3), {"id": 3, "ok": True}),
        (ReleaseOk(id=4), {"id": 4, "ok": True}),
        (
            ViewOk(id=5, limit=100, used=30, committed=20, reserved=10),
            {
                "id": 5,
                "ok": True,
                "limit": 100,
                "used": 30,
                "committed": 20,
                "reserved": 10,
            },
        ),
        (
            ErrorReply(
                id=7, code=ProtocolErrorCode.BUDGET_EXCEEDED, message="too much"
            ),
            {"id": 7, "ok": False, "error": "budget_exceeded", "message": "too much"},
        ),
        (
            ErrorReply(id=None, code=ProtocolErrorCode.BAD_REQUEST, message="bad"),
            {"id": None, "ok": False, "error": "bad_request", "message": "bad"},
        ),
    ],
    ids=[
        "hello",
        "set-limit",
        "reserve",
        "commit",
        "release",
        "view",
        "error",
        "error-no-id",
    ],
)
def test_encode_reply(
    codec: JsonCodec, reply: Reply, expected: dict[str, object]
) -> None:
    assert json.loads(codec.encode_reply(reply)) == expected


def test_encode_reply_has_no_framing(codec: JsonCodec) -> None:
    payload = codec.encode_reply(HelloOk(id=0, version=1))
    assert b"\n" not in payload


def test_registry_is_keyed_by_each_codecs_format() -> None:
    assert isinstance(CODECS[b"J"], JsonCodec)
    for fmt, registered in CODECS.items():
        assert fmt == registered.FORMAT


REQUEST_CASES: list[tuple[Request, dict[str, object]]] = [
    (Hello(id=0, version=1), {"id": 0, "op": "hello", "version": 1}),
    (
        SetLimit(id=1, key="k", limit=100),
        {"id": 1, "op": "set_limit", "key": "k", "limit": 100},
    ),
    (
        Reserve(id=2, key="k", amount=30),
        {"id": 2, "op": "reserve", "key": "k", "amount": 30},
    ),
    (
        Commit(id=3, reservation_id=RID, actual=25),
        {"id": 3, "op": "commit", "reservation_id": str(RID), "actual": 25},
    ),
    (
        Release(id=4, reservation_id=RID),
        {"id": 4, "op": "release", "reservation_id": str(RID)},
    ),
    (View(id=5, key="k"), {"id": 5, "op": "view", "key": "k"}),
]
REQUESTS: list[Request] = [request for request, _ in REQUEST_CASES]

OkReply = HelloOk | SetLimitOk | ReserveOk | CommitOk | ReleaseOk | ViewOk
OK_REPLIES: list[OkReply] = [
    HelloOk(id=0, version=1),
    SetLimitOk(id=1),
    ReserveOk(id=2, reservation_id=RID),
    CommitOk(id=3),
    ReleaseOk(id=4),
    ViewOk(id=5, limit=100, used=30, committed=25, reserved=5),
]


def _name(value: object) -> str:
    return type(value).__name__


@pytest.mark.parametrize(
    ("r", "expected"), REQUEST_CASES, ids=[_name(r) for r in REQUESTS]
)
def test_encode_request(codec: JsonCodec, r: Request, expected: dict[str, object]):
    encoded = codec.encode_request(r)
    assert b"\n" not in encoded
    assert json.loads(encoded) == expected


@pytest.mark.parametrize("r", REQUESTS, ids=_name)
def test_encode_decode_request_round_trip(codec: JsonCodec, r: Request):
    assert codec.decode_request(codec.encode_request(r)) == r


@pytest.mark.parametrize("reply", OK_REPLIES, ids=_name)
def test_ok_reply_round_trip(codec: JsonCodec, reply: OkReply) -> None:
    assert codec.decode_reply(codec.encode_reply(reply), type(reply)) == reply


@pytest.mark.parametrize("reply_id", [7, None])
def test_error_reply_round_trip(codec: JsonCodec, reply_id: int | None) -> None:
    reply = ErrorReply(id=reply_id, code=ProtocolErrorCode.BUDGET_EXCEEDED, message="m")
    assert codec.decode_reply(codec.encode_reply(reply), ReserveOk) == reply


def test_decode_reply_unrecognised_code(codec: JsonCodec) -> None:
    payload = b'{"id": 1, "ok": false, "error": "rate_limited", "message": "slow"}'
    assert codec.decode_reply(payload, CommitOk) == ErrorReply(
        id=1, code=ProtocolErrorCode.UNRECOGNISED, message="slow"
    )


def test_decode_reply_ignores_unknown_fields(codec: JsonCodec) -> None:
    payload = b'{"id": 1, "ok": true, "extra": 5}'
    assert codec.decode_reply(payload, CommitOk) == CommitOk(id=1)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"id": 1}',
        b'{"id": 1, "ok": 1}',
        b'{"ok": true}',
        b'{"id": null, "ok": true}',
        b'{"id": 1, "ok": true}',
        b'{"id": 1, "ok": false, "error": 5, "message": "m"}',
    ],
    ids=[
        "no-ok",
        "ok-not-bool",
        "no-id",
        "null-id-on-ok",
        "missing-field",
        "error-not-str",
    ],
)
def test_decode_reply_malformed(codec: JsonCodec, payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        codec.decode_reply(payload, ReserveOk)


def test_decode_reply_error_keeps_id(codec: JsonCodec) -> None:
    payload = b'{"id": 7, "ok": true, "reservation_id": "nope"}'
    with pytest.raises(ProtocolError) as e:
        codec.decode_reply(payload, ReserveOk)
    assert e.value.request_id == 7


def test_decode_reply_rejects_non_reply_type(codec: JsonCodec) -> None:
    @dataclass(frozen=True, kw_only=True, slots=True)
    class NotAReply(BaseReply): ...

    with pytest.raises(TypeError):
        codec.decode_reply(b'{"id": 1, "ok": true}', NotAReply)


def test_encode_reply_refuses_unrecognised(codec: JsonCodec) -> None:
    reply = ErrorReply(id=1, code=ProtocolErrorCode.UNRECOGNISED, message="m")
    with pytest.raises(ValueError):
        codec.encode_reply(reply)


def test_error_code_from_wire() -> None:
    assert (
        ProtocolErrorCode.from_wire("budget_exceeded")
        is ProtocolErrorCode.BUDGET_EXCEEDED
    )
    assert ProtocolErrorCode.from_wire("rate_limited") is ProtocolErrorCode.UNRECOGNISED


def test_codec_format_must_be_one_byte() -> None:
    with pytest.raises(TypeError):

        class BadCodec(JsonCodec):
            FORMAT = b"JJ"
