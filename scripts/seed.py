"""Seed the demo projects through the public API: python scripts/seed.py [--reset]."""

from __future__ import annotations

import argparse

from _client import client, ok

parser = argparse.ArgumentParser()
parser.add_argument("--reset", action="store_true", help="wipe governance data and recreate the banks")
args = parser.parse_args()

with client() as c:
    for dataset in ("apexcart", "ledgerlite"):
        result = ok(c.post("/admin/seed", json={"project": dataset, "reset": args.reset}))
        print(f"{result['project_name']:<12} {result['records_created']:>2} records · {result['transcripts_imported']} transcripts · bank {result['bank_status']} · {result['project_id']}")
