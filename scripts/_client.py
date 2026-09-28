"""Tiny API client shared by the scripts (they call the public API, never the DB)."""

from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("PROJECTPULSE_API", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("APP_ACCESS_TOKEN", "")


def client() -> httpx.Client:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    return httpx.Client(base_url=f"{BASE}/api/v1", headers=headers, timeout=180)


def ok(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        error = response.json().get("error", {}) if response.content else {}
        sys.exit(f"HTTP {response.status_code} {error.get('code')}: {error.get('message')} (request {error.get('request_id')})")
    return response.json()
