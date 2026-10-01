"""Wire schema for the uniform error envelope. Skeleton.

Lives under models/ (not a separate schemas/ package) — see models/common.py.
"""
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None  # correlation id; matches the failure's log line


class ErrorResponse(BaseModel):
    error: ErrorBody
