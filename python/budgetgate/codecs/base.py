from abc import ABC, abstractmethod
from typing import ClassVar

from budgetgate.messages import BaseReply, ErrorReply, Reply, Request


class ServerCodec(ABC):
    """The server's half of a codec: decode requests, encode replies.

    A codec knows nothing about framing: it never adds or strips delimiters or
    length prefixes. Codecs are stateless, so one instance is shared by every
    connection.
    """

    @abstractmethod
    def decode_request(self, payload: bytes) -> Request:
        """Decode exactly one request

        Raises ProtocolError (code bad_request) if the payload isn't a valid
        request. Sets request_id when the id could be read, else None.
        Unknown fields are ignored.
        """
        ...

    @abstractmethod
    def encode_reply(self, reply: Reply) -> bytes:
        """Encode exactly one reply. Never fails for a valid Reply."""
        ...


class ClientCodec(ABC):
    """The clients half of a codec: encode requests, decode replies.

    A codec knows nothing about framing: it never adds or strips delimiters or
    length prefixes.
    """

    @abstractmethod
    def decode_reply[R: BaseReply](
        self, payload: bytes, expected: type[R]
    ) -> R | ErrorReply:
        """Decode exactly one reply to a request whose sucess reply is expected

        The wire doesn't always say which reply type a payload is, so the caller
        passes the type it expects for the request it sent.

        Returns an ErrorReply if the server reported an error. An error the client
        doesn't recognise must not raise: newer servers may add codes, and clients
        treat unknown ones as a generic failure.

        Raises ProtocolError if the payload is't a valid reply of that type.
        Unknown feilds are ignored. Doesn't check the reply's id against the request;
        the client does that.
        """
        ...

    @abstractmethod
    def encode_request(self, request: Request) -> bytes:
        """Encode exactly one reply. Never fails for a valid Request."""
        ...


class Codec(ServerCodec, ClientCodec):
    """Both halves of one wire format, so encoding rules live in one place.

    Codecs are stateless, so one instance is shared by every connection.
    The gateway depends only on ServerCodec and the client only on ClientCodec.
    """

    FORMAT: ClassVar[bytes]
    """The format code sent in the connection preamble"""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        fmt = getattr(cls, "FORMAT", None)
        if not isinstance(fmt, bytes) or len(fmt) != 1:
            raise TypeError(f"{cls.__name__}.FORMAT must be a single byte")
