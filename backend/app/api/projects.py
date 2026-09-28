"""Projects and provisioning: POST/GET /projects, GET /projects/{pid}, POST /projects/{pid}/provision. Owner: P2.

Paths are relative to /api/v1. Raise AppError, never HTTPException.
"""

from fastapi import APIRouter

router = APIRouter(tags=["projects"])
