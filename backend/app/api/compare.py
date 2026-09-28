"""Compare: POST /projects/{pid}/compare, GET /projects/{pid}/compare/{cmp_id}. Owner: P6.

Paths are relative to /api/v1. Raise AppError, never HTTPException.
"""

from fastapi import APIRouter

router = APIRouter(tags=["compare"])
