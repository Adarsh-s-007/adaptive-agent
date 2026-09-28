"""Sessions: create/list/detail, import, close, extract (not /messages). Owner: P4.

Paths are relative to /api/v1. Raise AppError, never HTTPException.
"""

from fastapi import APIRouter

router = APIRouter(tags=["sessions"])
