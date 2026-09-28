from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.db.database import Base, engine

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="ProjectPulse API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ProjectPulse API",
        "hindsight_configured": bool(settings.hindsight_api_key),
        "groq_configured": bool(settings.groq_api_key),
    }
