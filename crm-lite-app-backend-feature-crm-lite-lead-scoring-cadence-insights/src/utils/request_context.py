"""Request-scoped correlation id.

Propagated via a contextvar (set by RequestContextMiddleware) rather than
threaded through every function signature, so any logger call — in a
service, a repository, or a global exception handler — can be tied back to
the HTTP request that triggered it. Sync route handlers still see it: AnyIO's
threadpool (what FastAPI runs sync `def` endpoints on) copies the current
context into the worker thread.
"""
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str:
    return _request_id.get()
