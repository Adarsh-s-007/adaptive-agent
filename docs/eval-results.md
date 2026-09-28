# Evaluation results

Run: 2026-09-28T19:58+00:00 · models: `heuristic-v1` (filter) · Hindsight `https://api.hindsight.vectorize.io`

> Filter mode for this run: **heuristic** (no `GROQ_API_KEY` configured), so these numbers measure the deterministic fallback, not `gpt-oss-20b`. L3 is missing because S-131 had not been approved yet. Re-run `python scripts/run_eval.py` after setting the key.

**Applied-record precision 0.63 · recall 0.63 · forbidden-record rate 0.00** (targets ≥ 0.8 / ≥ 0.8 / 0 — reported as measured).

| Task | Applied | Expected | Missing labels | Forbidden applied | P | R |
| --- | --- | --- | --- | --- | --- | --- |
| E1 Add POST /api/auth/login and keep the user signed in across reloads | A03 A02 L2 L1 A12 | L1 L2 A02 A12 |  |  | 0.80 | 1.00 |
| E2 Handle Stripe payment_intent.succeeded | A05 | A05 A02 |  |  | 1.00 | 0.50 |
| E3 Add an admin endpoint to delete an order | A01 A09 | A09 A02 A03 |  |  | 0.50 | 0.33 |
| E4 Checkout times out under load — configure the DB client | A08 | A06 | L3 |  | 0.00 | 0.00 |
| E5 Keep a guest's cart when they come back next week | A08 | A08 |  |  | 1.00 | 1.00 |
| E6 Add a dark-mode toggle to the header | A11 | A11 |  |  | 1.00 | 1.00 |
| E7 Show order totals with a percentage discount | A01 A09 | A01 |  |  | 0.50 | 1.00 |
| E8 Add a gift_message column to orders and ship it | A09 | A10 |  |  | 0.00 | 0.00 |
| E9 Log failed login attempts for debugging | A04 A12 | A04 A12 |  |  | 1.00 | 1.00 |
| E10 Fix: coupon applied twice at checkout | A08 A13 | A13 A01 |  |  | 0.50 | 0.50 |
