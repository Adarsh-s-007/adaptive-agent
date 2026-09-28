"""Inbox: GET candidates, POST approve, POST reject. Owner: P4.

Paths are relative to /api/v1. Raise AppError, never HTTPException.
"""

from fastapi import APIRouter

router = APIRouter(tags=["candidates"])
