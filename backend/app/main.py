"""App factory. Owner: P1."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router, public_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.session import engine
from app.jobs import start_background_jobs, stop_background_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_background_jobs()
    yield
    await stop_background_jobs()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="ProjectPulse API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(public_router)
    app.include_router(api_router)
    return app


app = create_app()
