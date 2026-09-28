"""G2 loop check: import S-104 → extract → approve → brief → compare → check, via the API.

python scripts/demo_loop.py            # uses the seeded ApexCart project
Compare needs GROQ_API_KEY on the server; without it the script stops after the brief.
"""

from __future__ import annotations

from _client import client, ok

HERO = "Add a POST /api/auth/login route and the client code that keeps the user signed in across reloads."

with client() as c:
    seeded = ok(c.post("/admin/seed", json={"project": "apexcart"}))
    pid = seeded["project_id"]
    sessions = ok(c.get(f"/projects/{pid}/sessions"))
    s104 = next(s for s in sessions if s["title"].startswith("S-104"))
    extracted = ok(c.post(f"/projects/{pid}/sessions/{s104['id']}/extract"))
    print(f"extracted {len(extracted['candidates'])} candidates, filtered {len(extracted['filtered'])}")
    for cand in extracted["candidates"]:
        res = ok(c.post(f"/projects/{pid}/candidates/{cand['id']}/approve", json={"reviewer": "demo_loop"}))
        print(f"  approved {res['record']['pill']} {res['record']['title']}")
    brief = ok(c.post(f"/projects/{pid}/brief", json={"task": HERO}))
    print(f"brief: {brief['status']} · applied {[a['record']['pill'] for a in brief['applied']]} · recall {brief['recall_ms']} ms")
    status = ok(c.get("/status"))
    if status["llm"]["status"] != "ok":
        raise SystemExit("LLM not configured — skipping Compare (set GROQ_API_KEY).")
    result = ok(c.post(f"/projects/{pid}/compare?wait=true", json={"task": HERO, "repeats": 1}))
    print(f"violations: baseline {result['violations_baseline']} → memory {result['violations_memory']}")
    print(result["fairness"].get("line"))
