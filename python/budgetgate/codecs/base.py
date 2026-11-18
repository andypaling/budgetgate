from abc import ABC, abstractmethod
from typing import ClassVar

from budgetgate.messages import Reply, Request


class Codec(ABC):
    """Turns one message's payload bytes into a Request, and a Reply into bytes

    A codec knows nothing about framing: it never adds or strips delimiters or
    length prefixes. Codecs are stateless, so one instance is shared by every
    connection.
    """

    FORMAT: ClassVar[bytes]
    """The format code sent in the connection preamble"""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        fmt = getattr(cls, "FORMAT", None)
        if not isinstance(fmt, bytes) or len(fmt) != 1:
            raise TypeError(f"{cls.__name__}.FORMAT must be a single byte")

    @abstractmethod
    def decode(self, payload: bytes) -> Request:
        """Decode exactly one request

        Raises ProtocolError (code bad_request) if the payload isn't a valid
        request. Sets request_id when the id could be read, else None.
        """
        ...

    @abstractmethod
    def encode(self, reply: Reply) -> bytes:
        """Encode exactly one reply. Never fails for a valid Reply."""
        ...
