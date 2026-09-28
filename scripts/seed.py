"""Seed ApexCart and LedgerLite through the public API only. Owner: P3.

Usage (from repo root):
    PROJECTPULSE_API_URL=http://localhost:8000 APP_ACCESS_TOKEN=... python scripts/seed.py

Idempotent: projects are matched by name and records by seed_key, so reruns create nothing.
Needs P2's /projects endpoints to exist.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1] / "seed"
API = os.environ.get("PROJECTPULSE_API_URL", "http://localhost:8000").rstrip("/") + "/api/v1"
TOKEN = os.environ.get("APP_ACCESS_TOKEN", "")


def check(resp: httpx.Response) -> dict | list:
    if resp.status_code >= 400:
        sys.exit(f"{resp.request.method} {resp.request.url} -> {resp.status_code}: {resp.text}")
    return resp.json()


def ensure_project(client: httpx.Client, spec: dict) -> dict:
    for project in check(client.get(f"{API}/projects")):
        if project["name"] == spec["name"]:
            return project
    return check(client.post(f"{API}/projects", json=spec))


def wait_ready(client: httpx.Client, project: dict) -> None:
    for _ in range(30):
        status = check(client.get(f"{API}/projects/{project['id']}")).get("bank_status")
        if status == "ready":
            return
        if status == "error":
            sys.exit(f"Provisioning failed for {project['name']}.")
        time.sleep(1)
    sys.exit(f"{project['name']} never became ready.")


def seed(client: httpx.Client, folder: str) -> None:
    spec = yaml.safe_load((ROOT / folder / "project.yaml").read_text())
    records = yaml.safe_load((ROOT / folder / "records.yaml").read_text())
    project = ensure_project(client, spec)
    wait_ready(client, project)
    failed = 0
    for record in records:
        body = {**record, "source": "seed", "approved_by": "seed"}
        body["decided_at"] = f"{record['decided_at']}T12:00:00Z"
        created = check(client.post(f"{API}/projects/{project['id']}/memories", json=body))
        failed += created["retain_state"] != "retained"
    print(f"{spec['name']}: {len(records)} records, {failed} not yet retained")


def main() -> None:
    with httpx.Client(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60) as client:
        for folder in ("apexcart", "ledgerlite"):
            seed(client, folder)


if __name__ == "__main__":
    main()
