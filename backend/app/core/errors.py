"""Application error raised by services and mapped to the JSON envelope."""

from typing import Any


class ApiError(Exception):
    """A failure the client can correct or retry, with an HTTP status and a message.

    The handler turns this into ErrorResponse. The message is the text in errors[0].msg.
    """

    def __init__(self, status_code: int, message: str, session: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.message = message
        self.session = session or {}
        super().__init__(message)
