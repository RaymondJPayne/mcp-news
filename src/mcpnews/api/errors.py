"""API errors carry a catalogue key, never a sentence.

Zero hardcoded English in an API response is a hard rule here. The server says
*which* thing went wrong; the browser, which knows the reader's language, says it
in words. That is also why ``params`` exists: a message with a filename in it
still has to be translatable.
"""
from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, key: str, **params: object):
        super().__init__(status_code=status_code,
                         detail={"error": {"key": key, "params": params}})
        self.key = key
        self.params = params


def not_found(key: str = "err.not_found", **params: object) -> ApiError:
    return ApiError(404, key, **params)


def bad_request(key: str, **params: object) -> ApiError:
    return ApiError(400, key, **params)


def setup_required() -> ApiError:
    return ApiError(409, "err.setup.required")
