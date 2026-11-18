from asyncio import StreamReader, StreamWriter

MAGIC = b"BG"
WIRE_VERSION = 1
PREAMBLE_SIZE = 4
MAX_FRAME = 64 * 1024


class FramingError(Exception): ...


class FrameTooLarge(FramingError):
    """A frame header declared a length over the allowed maximum."""

    def __init__(self, size: int, max_size: int) -> None:
        super().__init__(f"frame of {size} bytes exceeds {max_size}")
        self.size = size
        self.max_size = max_size


class BadPreamble(FramingError): ...


def make_preamble(fmt: bytes) -> bytes:
    return MAGIC + bytes([WIRE_VERSION]) + fmt


async def read_preamble(reader: StreamReader) -> bytes:
    """Read and check the 4-byte preamble; return the format byte."""
    data = await reader.readexactly(PREAMBLE_SIZE)
    if data[:2] != MAGIC:
        raise BadPreamble("not a budgetgate client")
    if data[2] != WIRE_VERSION:
        raise BadPreamble(f"unsupported wire version {data[2]}")
    return data[3:4]


async def write_preamble(writer: StreamWriter, fmt: bytes) -> None:
    writer.write(make_preamble(fmt))
    await writer.drain()


async def read_frame(reader: StreamReader) -> bytes:
    header = await reader.readexactly(4)
    n = int.from_bytes(header, "big")
    if n > MAX_FRAME:
        raise FrameTooLarge(n, MAX_FRAME)
    return await reader.readexactly(n)


async def write_frame(writer: StreamWriter, payload: bytes) -> None:
    writer.write(len(payload).to_bytes(4, "big") + payload)
    await writer.drain()
