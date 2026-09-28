"""Memory Check: POST /projects/{pid}/check. Owner: P6.

Paths are relative to /api/v1. Raise AppError, never HTTPException.
"""

from fastapi import APIRouter

router = APIRouter(tags=["check"])
