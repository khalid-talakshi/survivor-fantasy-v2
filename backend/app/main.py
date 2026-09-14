from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.app.api.health import router as health_router
from backend.app.api.identity import router as identity_router
from backend.app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")
    application.include_router(health_router)
    application.include_router(identity_router)

    frontend_dist = Path(settings.frontend_dist)
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @application.get("/api/v1")
    def api_root() -> dict[str, str]:
        return {"name": settings.app_name, "version": "v1"}

    @application.get("/api/v1/{path:path}", include_in_schema=False)
    def unknown_api(path: str) -> None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Unknown API route: {path}"},
        )

    @application.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> Response:
        index_file = frontend_dist / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return JSONResponse(
            {"name": settings.app_name, "frontend": "not_built", "path": path}
        )

    return application


app = create_app()
