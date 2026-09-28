"""Ask and Rulebook: POST /projects/{pid}/ask, GET rulebook, POST rulebook/refresh, GET rulebook/history. Owner: P2.

Paths are relative to /api/v1. Raise AppError, never HTTPException.
"""

from fastapi import APIRouter

router = APIRouter(tags=["reflect"])
