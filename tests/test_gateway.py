import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from budgetgate import Store
from budgetgate.framing import MAX_FRAME, make_preamble
from budgetgate.gateway import Gateway
from budgetgate.messages import Op

HOST = "127.0.0.1"
TIMEOUT = 1.0


class Client:
    """A minimal test client speaking the wire protocol.

    Sends the preamble on connect, then length-prefixed JSON frames with
    auto-incrementing ids. Frames bytes itself rather than using
    budgetgate.framing.
    """

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.reader = reader
        self.writer = writer
        self._next_id = 0

    @classmethod
    async def connect(cls, gateway: Gateway, fmt: bytes = b"J") -> Client:
        reader, writer = await asyncio.open_connection(HOST, gateway.port)
        client = cls(reader, writer)
        preamble = make_preamble(fmt)
        await client.send_raw(preamble)
        echoed = await asyncio.wait_for(reader.readexactly(4), TIMEOUT)
        assert echoed == preamble, f"server rejected preamble, sent back {echoed!r}"
        return client

    async def send_frame(self, payload: bytes) -> None:
        await self.send_raw(len(payload).to_bytes(4, "big") + payload)

    async def send_raw(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def send(self, op: str | Op, **fields: Any) -> int:
        """Send one request without waiting for the reply. Returns its id."""
        self._next_id += 1
        request = {"id": self._next_id, "op": op, **fields}
        await self.send_frame(json.dumps(request).encode())
        return self._next_id

    async def recv(self) -> dict[str, Any] | None:
        """Read one reply, or None if the server closed the connection."""
        try:
            header = await asyncio.wait_for(self.reader.readexactly(4), TIMEOUT)
            payload = await asyncio.wait_for(
                self.reader.readexactly(int.from_bytes(header, "big")), TIMEOUT
            )
        except asyncio.IncompleteReadError:
            return None
        return json.loads(payload)

    async def request(self, op, **fields: Any) -> dict[str, Any]:
        """Send one request and return its reply."""
        await self.send(op, **fields)
        reply = await self.recv()
        assert reply is not None, "server closed the connection"
        return reply

    async def hello(self) -> None:
        reply = await self.request("hello", version=1)
        assert reply["ok"], reply

    async def close(self) -> None:
        self.writer.close()
        with contextlib.suppress(ConnectionError):
            await self.writer.wait_closed()


async def eventually(check: Callable[[], bool], timeout: float = TIMEOUT) -> None:
    """Poll until check() is true. Server-side cleanup after a disconnect is async."""
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.01)


@pytest.fixture
async def gateway(store: Store) -> AsyncIterator[Gateway]:
    async with Gateway(store, port=0) as gw:
        yield gw


@pytest.fixture
async def client(gateway: Gateway) -> AsyncIterator[Client]:
    """A connected client that has already said hello"""
    client = await Client.connect(gateway)
    await client.hello()
    yield client
    await client.close()


async def test_reserve_commit_view_round_trip(client: Client) -> None:
    """The basic flow works end to end over a real socket."""
    reserved = await client.request("reserve", key="test_key", amount=3)
    assert reserved["ok"], reserved
    reservation_id = reserved["reservation_id"]

    committed = await client.request("commit", reservation_id=reservation_id, actual=2)
    assert committed["ok"], committed

    view = await client.request("view", key="test_key")
    assert view == {
        "id": view["id"],
        "ok": True,
        "limit": 10,
        "used": 2,
        "committed": 2,
        "reserved": 0,
    }


async def test_replies_come_back_in_request_order(client: Client) -> None:
    """Pipelining: send several requests before reading any replies"""
    ids = [
        await client.send("view", key="test_key"),
        await client.send("reserve", key="test_key", amount=4),
        await client.send("view", key="test_key"),
    ]
    replies = [await client.recv() for _ in ids]

    assert [r["id"] for r in replies if r] == ids
    before, reserved, after = replies
    assert before and before["reserved"] == 0
    assert reserved and reserved["ok"], reserved
    assert after and after["reserved"] == 4


async def test_disconnect_releases_reservations(client: Client, store: Store) -> None:
    """A client  that disconnects gets its live reservations released."""
    reply = await client.request("reserve", key="test_key", amount=3)
    assert reply["ok"], reply

    await client.close()

    await eventually(lambda: store.view("test_key").reserved == 0)


async def test_unsupported_version_replies_then_closes(gateway: Gateway) -> None:
    client = await Client.connect(gateway)

    reply = await client.request("hello", version=-1)

    assert reply["error"] == "unsupported_version", reply
    assert await client.recv() is None


async def test_oversized_frame_is_rejected_then_closed(client: Client) -> None:
    await client.send_raw((MAX_FRAME + 1).to_bytes(4, "big"))

    reply = await client.recv()

    assert reply is not None
    assert reply["id"] is None
    assert reply["error"] == "bad_request"
    assert await client.recv() is None


@pytest.mark.parametrize(
    "preamble",
    [b"GET / HTTP/1.1\r\n\r\n", b"BG\x01P", b"BG\x02J"],
    ids=["not-budgetgate", "unknown-format", "wrong-wire-version"],
)
async def test_bad_preamble_gets_server_preamble_then_eof(
    gateway: Gateway, preamble: bytes
) -> None:
    reader, writer = await asyncio.open_connection(HOST, gateway.port)
    writer.write(preamble)
    await writer.drain()

    assert await asyncio.wait_for(reader.read(), TIMEOUT) == make_preamble(b"J")
    writer.close()


async def test_malformed_request_gets_error_and_connection_stays_open(
    client: Client,
) -> None:
    await client.send_frame(b"not_json")

    reply = await client.recv()

    assert reply is not None
    assert reply["id"] is None
    assert reply["error"] == "bad_request"
    assert (await client.request("view", key="missing"))["error"] == "unknown_key"
