from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from backend.app.api.health import router as health_router
from backend.app.api.identity import router as identity_router
from backend.app.api.leagues import router as leagues_router
from backend.app.core.config import get_settings
from backend.app.core.context import current_request_id, reset_request_id, set_request_id
from backend.app.core.errors import DatabaseUnavailableError, DomainError, ValidationError


def _error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    details: object = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_identifier = getattr(request.state, "request_id", None)
    if request_identifier is None:
        request_identifier = current_request_id()
    request_identifier = str(request_identifier)
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_identifier
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": request_identifier,
        },
        headers=response_headers,
    )


def _request_id(header: str | None) -> UUID:
    if header is not None:
        try:
            return UUID(header)
        except ValueError:
            pass
    return uuid4()


def _default_http_error_code(status_code: int) -> str:
    return {
        status.HTTP_401_UNAUTHORIZED: "unauthenticated",
        status.HTTP_403_FORBIDDEN: "permission_denied",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
        status.HTTP_503_SERVICE_UNAVAILABLE: "database_unavailable",
    }.get(status_code, "conflict")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_identifier = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_identifier
        token = set_request_id(request_identifier)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = str(current_request_id())
            return response
        finally:
            reset_request_id(token)

    @application.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return _error_response(request, exc.code, exc.message, exc.status_code, exc.details)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            ValidationError.code,
            ValidationError.default_message,
            ValidationError.status_code,
            {"errors": jsonable_encoder(exc.errors())},
        )

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = _default_http_error_code(exc.status_code)
        return _error_response(
            request,
            code,
            "The request could not be completed.",
            exc.status_code,
            headers=exc.headers,
        )

    @application.exception_handler(OperationalError)
    async def database_error_handler(request: Request, _: OperationalError) -> JSONResponse:
        return _error_response(
            request,
            DatabaseUnavailableError.code,
            DatabaseUnavailableError.default_message,
            DatabaseUnavailableError.status_code,
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _: Exception) -> JSONResponse:
        return _error_response(request, "internal_error", "An unexpected error occurred.", 500)

    application.include_router(health_router)
    application.include_router(identity_router)
    application.include_router(leagues_router)

    frontend_dist = Path(settings.frontend_dist)
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @application.get("/api/v1")
    def api_root() -> dict[str, str]:
        return {"name": settings.app_name, "version": "v1"}

    @application.api_route(
        "/api/v1/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    def unknown_api(path: str) -> None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )

    @application.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> Response:
        index_file = frontend_dist / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return JSONResponse({"name": settings.app_name, "frontend": "not_built", "path": path})

    return application


app = create_app()
