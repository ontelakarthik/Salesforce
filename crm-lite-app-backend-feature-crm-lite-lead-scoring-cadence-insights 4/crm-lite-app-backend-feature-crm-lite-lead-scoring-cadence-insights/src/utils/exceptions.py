"""Domain error type + uniform error envelope {"error":{code,message}}."""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.utils.request_context import get_request_id

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Raise from services for business-rule violations."""
    def __init__(self, code: str, message: str,
                 status_code: int = status.HTTP_400_BAD_REQUEST):
        self.code, self.message, self.status_code = code, message, status_code


def _error_response(status_code: int, body: dict) -> JSONResponse:
    """Every error carries the correlation id in both the envelope and the
    X-Request-Id header, so the id a user reports from the UI is the one that
    finds the matching stack trace in the server log. The header alone isn't
    enough for a browser client: the UI is a different origin from this API,
    so JS can only read X-Request-Id because CORS exposes it explicitly (see
    server/__init__.py) — the body field works regardless."""
    request_id = get_request_id()
    body["error"]["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=body,
                        headers={"X-Request-Id": request_id})


def _serializable_field_errors(errors: list[dict]) -> list[dict]:
    """A @field_validator that raises a plain ValueError (see
    crm_models._check_contact_email) ends up with that exception instance
    itself under ctx.error in Pydantic's error dict — not JSON-serializable
    as-is, unlike everything else `.errors()` returns. Stringify just that
    one field rather than dropping the whole ctx, so callers relying on
    ctx's other keys (e.g. min_length) are unaffected."""
    cleaned = []
    for e in errors:
        ctx = e.get("ctx")
        if isinstance(ctx, dict) and isinstance(ctx.get("error"), Exception):
            e = dict(e)
            e["ctx"] = {**ctx, "error": str(ctx["error"])}
        cleaned.append(e)
    return cleaned


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return _error_response(
            exc.status_code, {"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        d = exc.detail
        body = {"error": dict(d)} if isinstance(d, dict) and "code" in d \
            else {"error": {"code": "HTTP_ERROR", "message": str(d)}}
        return _error_response(exc.status_code, body)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"error": {"code": "VALIDATION_ERROR",
                       "message": "Request validation failed.",
                       "fields": _serializable_field_errors(exc.errors())}})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        # Safety net for anything that escapes a decorated service function
        # (see utils.error_handling.handle_errors) — a bug in a dependency
        # provider, a repository call made outside a decorated function,
        # etc. Business-logic functions should already turn failures into a
        # DomainError with an operation-specific message before they get
        # here; this exists so that if one doesn't, the failure is still
        # logged with a stack trace and a traceable request id instead of
        # surfacing to the client as a bare, unlogged 500.
        # Imported here rather than at module scope: utils.error_handling
        # imports DomainError from this module, so a top-level import back
        # would be circular.
        from src.utils.error_handling import build_client_message, build_log_message

        operation = "complete the request"
        logger.error(build_log_message(operation, exc), exc_info=True)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            {"error": {"code": "INTERNAL_ERROR",
                       "message": build_client_message(operation, exc)}})
