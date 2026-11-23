import asyncio
import contextlib
from asyncio import StreamReader, StreamWriter
from types import TracebackType
from typing import Self

from budgetgate import BudgetView
from budgetgate.codecs import ClientCodec, Codec, JsonCodec
from budgetgate.errors import error_from_reply
from budgetgate.framing import make_preamble, read_frame, write_frame
from budgetgate.messages import (
    PROTOCOL_VERSION,
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
    Request,
    ReservationId,
    Reserve,
    ReserveOk,
    SetLimit,
    SetLimitOk,
    View,
    ViewOk,
)


class Client:
    """A connection to a budgetgate gateway. One request is in flight at a time."""

    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        codec: ClientCodec,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._codec = codec
        self._lock = asyncio.Lock()
        self._next_id = 0

    @classmethod
    async def connect(
        cls, host: str = "127.0.0.1", port: int = 7878, *, codec: Codec | None = None
    ) -> Self:
        """Open a connection, swap preambled and say hello.

        Raises ConnectionError is the gateway rejects the preamble of closes.
        """
        codec = codec or JsonCodec()
        reader, writer = await asyncio.open_connection(host, port)
        client = cls(reader, writer, codec)

        try:
            preamble = make_preamble(codec.FORMAT)
            writer.write(preamble)
            await writer.drain()
            echoed = await reader.readexactly(len(preamble))
            if echoed != preamble:
                raise ConnectionError(f"gateway rejected preamble, offered {echoed!r}")
            await client._call(
                Hello(id=client._new_id(), version=PROTOCOL_VERSION), HelloOk
            )
        except BaseException:
            await client.close()
            raise
        return client

    async def close(self) -> None:
        """Close the connection. Safe to call more than once"""
        self._writer.close()
        with contextlib.suppress(ConnectionError):
            await self._writer.wait_closed()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # operations

    async def set_limit(self, key: str, limit: int) -> None:
        await self._call(
            SetLimit(
                id=self._new_id(),
                key=key,
                limit=limit,
            ),
            SetLimitOk,
        )

    async def reserve(self, key: str, amount: int) -> ReservationId:
        reply = await self._call(
            Reserve(id=self._new_id(), key=key, amount=amount), ReserveOk
        )
        return reply.reservation_id

    async def commit(self, reservation_id: ReservationId, actual: int) -> None:
        await self._call(
            Commit(id=self._new_id(), reservation_id=reservation_id, actual=actual),
            expected=CommitOk,
        )

    async def release(self, reservation_id: ReservationId) -> None:
        await self._call(
            Release(id=self._new_id(), reservation_id=reservation_id), ReleaseOk
        )

    async def view(self, key: str) -> BudgetView:
        reply = await self._call(View(id=self._new_id(), key=key), ViewOk)
        return BudgetView(
            limit=reply.limit,
            used=reply.used,
            reserved=reply.reserved,
            committed=reply.committed,
        )

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _call[R: BaseReply](self, request: Request, expected: type[R]) -> R:
        async with self._lock:
            await write_frame(self._writer, self._codec.encode_request(request))
            try:
                payload = await read_frame(self._reader)
            except asyncio.IncompleteReadError:
                raise ConnectionError("gateway closed the connection") from None

        reply = self._codec.decode_reply(payload, expected)
        if reply.id != request.id:
            raise ProtocolError(
                ProtocolErrorCode.BAD_REQUEST,
                f"reply id {reply.id} doesn't match request id {request.id}",
            )

        if isinstance(reply, ErrorReply):
            raise error_from_reply(reply)

        return reply
