from budgetgate.codecs.base import ClientCodec, Codec, ServerCodec
from budgetgate.codecs.json import JsonCodec

CODECS: dict[bytes, Codec] = {codec.FORMAT: codec for codec in (JsonCodec(),)}
DEFAULT_FORMAT = JsonCodec.FORMAT

__all__ = [
    "CODECS",
    "DEFAULT_FORMAT",
    "ClientCodec",
    "Codec",
    "JsonCodec",
    "ServerCodec",
]
