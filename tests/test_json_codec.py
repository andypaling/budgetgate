import json
import uuid

import pytest
from budgetgate.codecs import CODECS, JsonCodec
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
def test_decode_valid(line: bytes, expected: Request, codec: JsonCodec) -> None:
    assert codec.decode(line) == expected


def test_decode_ignores_unknown_fields(codec: JsonCodec) -> None:
    line = b'{"id": 2, "op": "reserve", "key": "k", "amount": 30, "priority": "high"}'
    assert codec.decode(line) == Reserve(id=2, key="k", amount=30)


def test_decode_leaves_value_checks_to_store(codec: JsonCodec) -> None:
    line = b'{"id": 2, "op": "reserve", "key": "k", "amount": -5}'
    assert codec.decode(line) == Reserve(id=2, key="k", amount=-5)


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
def test_decode_error_keeps_request_id(line: bytes, codec: JsonCodec) -> None:
    with pytest.raises(ProtocolError) as excinfo:
        codec.decode(line)
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
def test_decode_error_without_request_id(line: bytes, codec: JsonCodec) -> None:
    with pytest.raises(ProtocolError) as excinfo:
        codec.decode(line)
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
def test_encode(codec: JsonCodec, reply: Reply, expected: dict[str, object]) -> None:
    assert json.loads(codec.encode(reply)) == expected


def test_encode_has_no_framing(codec: JsonCodec) -> None:
    payload = codec.encode(HelloOk(id=0, version=1))
    assert b"\n" not in payload


def test_registry_is_keyed_by_each_codecs_format() -> None:
    assert isinstance(CODECS[b"J"], JsonCodec)
    for fmt, registered in CODECS.items():
        assert fmt == registered.FORMAT
