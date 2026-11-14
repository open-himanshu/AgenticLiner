RESULTS
Setup: 50 prompts (15 clean, 15 high-conflict, 2 destructive, 3 bulk-write, 15 ambiguous) on a seeded synthetic campus database. A scripted rule-based planner replaced the LLM so runs are repeatable and offline; the results measure the safety layer, not LLM quality. Three setups received identical, already-complete requests: A (actions written directly, no constraints), B (best-effort plain SQLite constraints and triggers, no Kavach code), C (full pipeline with the Kavach safety layer). An independent checker that shares no code with Kavach inspected each final database.
- Clean requests (15): all three setups committed 15/15; Setup C had 0 false blocks.
- Requests that should be blocked (20): stopped by A 0, B 16, C 17. Setup B stopped 15 of 15 high-conflict prompts and Setup C 12 of 15; C's extra stops come from the 3 bulk-write prompts (write limit) and the destructive filter. Invalid final database states: A 17, B 1, C 0.
- Setup C's 17 stops: 15 by Kavach rules, 1 by the application's destructive filter, 1 by the benchmark's own filter.
- Setup C missed 3 speaker-clash requests: the agent's booking tool carries no speaker assignment, so the speaker rule is not on that path. Setup B missed 3 bulk-write requests and 1 DROP TABLE.
- Ambiguous requests (15): the scripted planner asked for clarification 15/15 (tests routing, not LLM understanding).
- Interpretation: well-written plain SQL constraints stop almost as many invalid bookings as Kavach on this benchmark (16 vs 17 of 20). Kavach's measured additions are the per-request write limit and the destructive-request pre-filter; transactional rollback with an audit log, and notices written only after the booking commits, were not separately measured.
- Live checks: a Gemini ping, a tool call and 3 Q&A questions (each asked twice) worked; answers were identical on repeat and unanswerable questions were declined. Agent mode falls back to the deterministic pipeline, which completed the booking.
- Tests: 343 passed, 0 failed.

LIMITATIONS
1. Benchmark used a scripted planner, not an LLM; data is synthetic; n is small (35 safety + 15 intake prompts), so no percentages or significance claims.
2. One developer (with AI coding tools) wrote prompts, rules, checker and baselines; Setup B was extended after seeing its failures; no independent review.
3. Kavach only catches rules that are coded: speaker clash is not on the agent path; the per-request write limit blocks legitimate bookings with many resource types; retries and the human-review queue were not exercised (0 retries).
4. No cost model: halls and equipment are internal campus resources, so budget limits, cost-based selection and payment are not implemented (future scope).
5. Destructive tests exercise a regex pre-filter only (n=2); the agent has no delete tool.
6. Latency is not reported. Voice input and SMTP email were not verified.
