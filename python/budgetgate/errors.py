from budgetgate import (
    BudgetError,
    BudgetExceeded,
    InvalidAmount,
    UnknownKey,
    UnknownReservation,
)
from budgetgate.messages import ErrorReply, ProtocolError, ProtocolErrorCode

STORE_ERRORS: dict[type[BudgetError], ProtocolErrorCode] = {
    UnknownKey: ProtocolErrorCode.UNKNOWN_KEY,
    InvalidAmount: ProtocolErrorCode.INVALID_AMOUNT,
    BudgetExceeded: ProtocolErrorCode.BUDGET_EXCEEDED,
    UnknownReservation: ProtocolErrorCode.UNKNOWN_RESERVATION,
}
"""Store expection -> wire code (server side)"""

_CODE_ERRORS = {code: exc for exc, code in STORE_ERRORS.items()}


def error_from_reply(reply: ErrorReply):
    """Wire error -> exception (client side): store errors become the same
    exception the local Store would raise; everything else is a ProtocolError.
    """
    exc_type = _CODE_ERRORS.get(reply.code)
    if exc_type is not None:
        return exc_type(reply.message)
    return ProtocolError(reply.code, reply.message, reply.id)
