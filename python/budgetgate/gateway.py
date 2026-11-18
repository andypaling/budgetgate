import asyncio
import contextlib
from types import TracebackType
from typing import Self

from budgetgate import Store
from budgetgate.codecs import CODECS, DEFAULT_FORMAT
from budgetgate.framing import (
    BadPreamble,
    FrameTooLarge,
    read_frame,
    read_preamble,
    write_frame,
    write_preamble,
)
from budgetgate.messages import ErrorReply, ProtocolError, ProtocolErrorCode
from budgetgate.session import Session

DEFAULT_PORT = 7878


class Gateway:
    def __init__(
        self, store: Store, host: str = "127.0.0.1", port: int = DEFAULT_PORT
    ) -> None:
        self._store = store
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

    async def __aenter__(self) -> Self:
        if self._server is not None:
            raise RuntimeError("gateway already started")
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        server, self._server = self._server, None

        if server is None:
            return

        server.close()
        server.close_clients()
        await server.wait_closed()

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("gateway not started")
        return self._server.sockets[0].getsockname()[1]

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("gateway not started")
        await self._server.serve_forever()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        session = Session(self._store)
        try:
            try:
                fmt = await read_preamble(reader)
            except BadPreamble:
                fmt = None
            codec = CODECS.get(fmt) if fmt else None
            if codec is None:
                await write_preamble(writer, DEFAULT_FORMAT)
                return
            await write_preamble(writer, codec.FORMAT)

            while True:
                try:
                    payload = await read_frame(reader)
                except FrameTooLarge as e:
                    reply = ErrorReply(
                        id=None, code=ProtocolErrorCode.BAD_REQUEST, message=str(e)
                    )
                    await write_frame(writer, codec.encode(reply))
                    break

                try:
                    request = codec.decode(payload)
                except ProtocolError as e:
                    reply = ErrorReply.from_protocol_error(e)
                else:
                    reply = session.handle(request)

                await write_frame(writer, codec.encode(reply))
                if session.should_close:
                    break
        except ConnectionError, asyncio.IncompleteReadError:
            pass  # client went away: between frames, mid-frame or mid-preamble
        finally:
            session.close()
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
