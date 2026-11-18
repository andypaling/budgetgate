from budgetgate.codecs.base import Codec
from budgetgate.codecs.json import JsonCodec

CODECS: dict[bytes, Codec] = {codec.FORMAT: codec for codec in (JsonCodec(),)}
DEFAULT_FORMAT = JsonCodec.FORMAT

__all__ = ["CODECS", "DEFAULT_FORMAT", "Codec", "JsonCodec"]
