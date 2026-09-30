"""HTTP middleware.

Attaches a request id (from an incoming X-Request-Id header, or a fresh
uuid4) to the response and to a contextvar (utils.request_context) so every
log line emitted anywhere while handling this request can be tied back to
it. Also logs each request's outcome. The gateway performs auth upstream;
identity resolution from headers lives in utils.security (per-request
dependency), not here.
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.utils.request_context import set_request_id

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id
        set_request_id(request_id)
        started = time.monotonic()
        # No try/except here: an exception raised below is turned into the
        # uniform JSON envelope (and logged once, with a stack trace) by
        # install_error_handlers in utils.exceptions. Logging it here too
        # would double every 500 in the console.
        response = await call_next(request)
        duration_ms = (time.monotonic() - started) * 1000
        logger.info("%s %s -> %s (%.1fms)",
                    request.method, request.url.path, response.status_code, duration_ms)
        response.headers["X-Request-Id"] = request_id
        return response
