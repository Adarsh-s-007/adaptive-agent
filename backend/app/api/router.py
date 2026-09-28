"""Router registry. Owner: P1.

Every router module already exists, so owners never need to edit this file. Each module
exposes `router = APIRouter()` with paths relative to /api/v1.
"""

from fastapi import APIRouter, Depends

from app.api import (
    admin_hindsight,  # P2
    admin_seed,  # P3
    brief,  # P5
    candidates,  # P4
    check,  # P6
    compare,  # P6
    eval,  # P5
    health,  # P1
    memories,  # P3
    metrics,  # P3
    projects,  # P2
    reflect,  # P2
    runs,  # P5
    sessions,  # P4
    timeline,  # P3
    workspace,  # P5
)
from app.core.security import require_access_token, require_demo_mode

public_router = APIRouter()
public_router.include_router(health.router)

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_access_token)])
for module in (
    projects,
    reflect,
    sessions,
    candidates,
    memories,
    timeline,
    metrics,
    brief,
    runs,
    workspace,
    eval,
    check,
    compare,
):
    api_router.include_router(module.router)

admin = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_demo_mode)])
admin.include_router(admin_seed.router)
admin.include_router(admin_hindsight.router)
api_router.include_router(admin)
