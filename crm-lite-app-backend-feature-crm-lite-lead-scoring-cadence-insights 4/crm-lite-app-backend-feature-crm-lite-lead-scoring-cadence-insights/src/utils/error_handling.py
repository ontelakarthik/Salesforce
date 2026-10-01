"""Cross-cutting error handling for service-layer business logic.

`@handle_errors("<operation>")` wraps a service function so that:
- deliberate/already-classified errors (DomainError, HTTP errors, request
  validation errors) pass through unchanged — they already carry the right
  status code and a client-safe message;
- anything else (a bug, a DB error that slipped past a repository, ...) is
  logged at ERROR with a full stack trace, and answered with a 500 whose
  message names the operation that failed.

Outside production the response repeats the underlying exception text, so
the string a developer sees in the browser is the same string in the log —
paste either into a grep and you find the other. In production that text is
logged but NOT returned: the client gets the operation plus the correlation
id (`build_client_message`), because the raw text can carry internals like a
DB host or a failing SQL statement. Support still resolves the report from
the id, which appears both in the message and in `error.request_id`.
"""
import functools
import logging

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config.config_reader import settings
from src.utils.exceptions import DomainError
from src.utils.request_context import get_request_id

_PASSTHROUGH = (DomainError, StarletteHTTPException, RequestValidationError)

# APP_ENV values are local | dev | prod (see config/config.py). Only the real
# deployed environment withholds the exception text; local and dev keep it so
# developers debug against the same string the log carries.
# "production" is accepted alongside "prod" on purpose: this set failing open
# would leak internals, so a deployment that spells the value out in full must
# still be treated as production rather than silently falling through to dev
# behaviour. Deliberately redundant, not dead.
_ENVS_HIDING_INTERNALS = {"prod", "production"}


def build_log_message(operation: str, exc: BaseException) -> str:
    """The full-fidelity message — always logged, never withheld."""
    return f"Couldn't {operation} because of a server error: {exc}"


def build_client_message(operation: str, exc: BaseException) -> str:
    """What the caller is allowed to see, given APP_ENV.

    Outside production this is byte-identical to build_log_message() so the
    two can be correlated by string alone; in production the exception text
    is replaced by the correlation id, which is the safe way to tie a user's
    report back to the logged stack trace.
    """
    if settings.APP_ENV.strip().lower() in _ENVS_HIDING_INTERNALS:
        return (f"Couldn't {operation} because of a server error. "
                f"Please quote reference {get_request_id()} if you report this.")
    return build_log_message(operation, exc)


def handle_errors(operation: str):
    def decorator(fn):
        logger = logging.getLogger(fn.__module__)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except _PASSTHROUGH:
                raise
            except Exception as exc:
                logger.error(build_log_message(operation, exc), exc_info=True)
                raise DomainError(
                    "INTERNAL_ERROR", build_client_message(operation, exc), 500) from exc

        return wrapper

    return decorator
