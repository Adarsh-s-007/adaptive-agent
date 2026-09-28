"""Run the labelled eval set and write docs/eval-results.md: python scripts/run_eval.py"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from _client import client, ok

with client() as c:
    projects = ok(c.get("/projects"))
    apex = next(p for p in projects if p["name"] == "ApexCart")
    run = ok(c.post(f"/projects/{apex['id']}/eval", json={"set": "default"}))

lines = [
    "# Evaluation results",
    "",
    f"Run: {datetime.now(timezone.utc).isoformat(timespec='minutes')} · models: `{run['models'].get('small')}` (filter) · Hindsight `{run['models'].get('hindsight')}`",
    "",
    f"**Applied-record precision {run['precision']:.2f} · recall {run['recall']:.2f} · forbidden-record rate {run['forbidden_rate']:.2f}** (targets ≥ 0.8 / ≥ 0.8 / 0 — reported as measured).",
    "",
    "| Task | Applied | Expected | Missing labels | Forbidden applied | P | R |",
    "| --- | --- | --- | --- | --- | --- | --- |",
]
for r in run["results"]:
    lines.append(
        f"| {r['id']} {r['task']} | {' '.join(r['applied'])} | {' '.join(r['expected'])} | {' '.join(r['missing_labels'])} | {' '.join(r['forbidden_applied'])} | {r['precision']:.2f} | {r['recall']:.2f} |"
    )
out = Path(__file__).resolve().parents[1] / "docs" / "eval-results.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"precision {run['precision']} recall {run['recall']} forbidden {run['forbidden_rate']} -> {out}")
