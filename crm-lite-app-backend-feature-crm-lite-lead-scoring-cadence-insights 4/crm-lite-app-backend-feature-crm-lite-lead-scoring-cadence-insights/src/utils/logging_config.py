"""Logging setup.

Every log record is stamped with whichever HTTP request (if any) is
currently being handled (see utils.request_context) — so grepping one
X-Request-Id ties together the request line, any service-level error, and
the response line, across every logger in the app.
"""
import logging

from src.config.config_reader import settings
from src.utils.request_context import get_request_id


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [request_id=%(request_id)s] %(message)s"))
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        handlers=[handler],
        force=True,  # replace any handlers a prior configure_logging() call left behind (--reload)
    )
