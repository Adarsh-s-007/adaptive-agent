from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.v1 import v1_router
from app.config import get_settings
from app.core.errors import AppError
from app.db.database import Base, engine
import app.db.governed_models  # noqa: F401
from app.services.hindsight_service import HindsightService
from fastapi.responses import JSONResponse

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="ProjectPulse API", version="1.0.0")


@app.exception_handler(AppError)
async def app_error_handler(request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(v1_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ProjectPulse API",
        "hindsight_configured": bool(settings.hindsight_api_key),
        "groq_configured": bool(settings.groq_api_key),
    }


@app.get("/health/hindsight")
async def hindsight_health():
    """Read-only Hindsight connectivity check for local setup verification."""
    return await HindsightService().probe()
