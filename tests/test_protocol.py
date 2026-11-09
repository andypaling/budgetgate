import json
import uuid

import pytest
from budgetgate.protocol import (
    Commit,
    Hello,
    ProtocolError,
    ProtocolErrorCode,
    Release,
    Request,
    ReservationId,
    Reserve,
    SetLimit,
    View,
    decode,
    encode_error,
    encode_ok,
)

RID = ReservationId(uuid.UUID("8379acfd-0dd3-4ec8-9899-c46ee0b00d51"))


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
def test_decode_valid(line: bytes, expected: Request) -> None:
    assert decode(line) == expected


def test_decode_ignores_unknown_fields() -> None:
    line = b'{"id": 2, "op": "reserve", "key": "k", "amount": 30, "priority": "high"}'
    assert decode(line) == Reserve(id=2, key="k", amount=30)


def test_decode_accepts_trailing_newline() -> None:
    line = b'{"id": 2, "op": "reserve", "key": "k", "amount": 30}\n'
    assert decode(line) == Reserve(id=2, key="k", amount=30)


def test_decode_leaves_value_checks_to_store() -> None:
    line = b'{"id": 2, "op": "reserve", "key": "k", "amount": -5}'
    assert decode(line) == Reserve(id=2, key="k", amount=-5)


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
def test_decode_error_keeps_request_id(line: bytes) -> None:
    with pytest.raises(ProtocolError) as excinfo:
        decode(line)
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
def test_decode_error_without_request_id(line: bytes) -> None:
    with pytest.raises(ProtocolError) as excinfo:
        decode(line)
    assert excinfo.value.code == ProtocolErrorCode.BAD_REQUEST
    assert excinfo.value.request_id is None


def test_encode_ok_plain() -> None:
    assert json.loads(encode_ok(1)) == {"id": 1, "ok": True}


def test_encode_ok_with_uuid() -> None:
    assert json.loads(encode_ok(2, reservation_id=RID)) == {
        "id": 2,
        "ok": True,
        "reservation_id": str(RID),
    }


def test_encode_ok_rejects_reserved_names() -> None:
    with pytest.raises(ValueError):
        encode_ok(1, id=5)


def test_encode_error_with_id() -> None:
    reply = json.loads(encode_error(7, ProtocolErrorCode.BUDGET_EXCEEDED, "too much"))
    assert reply == {
        "id": 7,
        "ok": False,
        "error": "budget_exceeded",
        "message": "too much",
    }


def test_encode_error_without_id() -> None:
    reply = json.loads(encode_error(None, ProtocolErrorCode.BAD_REQUEST, "bad"))
    assert reply["id"] is None


@pytest.mark.parametrize(
    "line",
    [encode_ok(1), encode_error(1, ProtocolErrorCode.BAD_REQUEST, "bad")],
    ids=["ok", "error"],
)
def test_encoded_lines_end_with_newline(line: bytes) -> None:
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
