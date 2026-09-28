"""Admin: HINDSIGHT_FORCE_OFFLINE toggle under /admin. Owner: P2.

Paths are relative to /api/v1. Raise AppError, never HTTPException.
"""

from fastapi import APIRouter

router = APIRouter(tags=["admin"])
