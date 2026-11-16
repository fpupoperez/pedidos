"""FastAPI application. JSON routes return the shared envelope."""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.openapi import OPENAPI_DESCRIPTION, OPENAPI_TAGS
from app.api.v1.health import router as health_router
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.logging import configure_logging
from app.core.telemetry import configure_telemetry
from app.schemas.envelope import dump_envelope, failure

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logs and traces. The worker configures its own provider."""
    settings = get_settings()
    configure_logging(settings.otel_service_name)
    configure_telemetry(settings, settings.otel_service_name)
    yield


def create_app() -> FastAPI:
    """Build the API. Tests construct this after pointing settings at a safe database."""
    app = FastAPI(
        title="Orders",
        version="0.1.0",
        description=OPENAPI_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api/v1")
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
    FastAPIInstrumentor.instrument_app(app)
    return app


def _session(request: Request) -> dict[str, Any]:
    """The caller session attached by auth, or an empty object."""
    session = getattr(request.state, "session", None)
    if isinstance(session, dict):
        return session
    return {}


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    """Map ApiError onto the envelope."""
    assert isinstance(exc, ApiError)
    body = failure(exc.status_code, exc.message, exc.session or _session(request))
    return JSONResponse(status_code=exc.status_code, content=dump_envelope(body))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Validation failures use the envelope, not a top-level detail array."""
    assert isinstance(exc, RequestValidationError)
    body = failure(422, _validation_message(exc), _session(request))
    return JSONResponse(status_code=422, content=dump_envelope(body))


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    """Starlette HTTP errors use the same envelope."""
    assert isinstance(exc, StarletteHTTPException)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    body = failure(exc.status_code, message, _session(request))
    return JSONResponse(status_code=exc.status_code, content=dump_envelope(body))


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Hide unexpected exception text. The traceback stays in the server log."""
    logger.exception("Unhandled error")
    body = failure(500, "Unexpected failure.", _session(request))
    return JSONResponse(status_code=500, content=dump_envelope(body))


def _validation_message(exc: RequestValidationError) -> str:
    """Name the first invalid field and the reason."""
    errors = exc.errors()
    if not errors:
        return "The request failed validation."
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    msg = str(first.get("msg", "invalid"))
    if loc:
        return f"{loc}: {msg}"
    return msg


app = create_app()
