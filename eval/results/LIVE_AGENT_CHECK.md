[RAN] # Live Agent-Mode Bounded Check
[RAN] ## Environment & Budget Summary
[RAN] - `PROVIDER` (process-only): `gemini`
[RAN] - `GEMINI_MODEL` (from `.env` via `dotenv`): `gemini-3.1-flash-lite`
[RAN] - `TEST_CONSOLE`: `0` (off)
[RAN] - Database: temporary SQLite database initialized once with `python -m backend.core.database.init_db --seed-demo` (`4` seeded `bookings` rows before Run (a); sequential Runs (a) then (b) in the same temp DB, removed afterwards)
[RAN] - Provider call budget: `4 / 10` total calls used (`2` in Run (a), `2` in Run (b))
[RAN] - Halted on 429 / quota / timeout: `no`

[RAN] ## Run (a): `"Dance performance, 150 students, next Friday 6 PM, budget 20000"` (`budget` kwarg omitted / default `None`)
[RAN] - **mode**: `fixed_fallback`
[RAN] - **provider**: `gemini`
[RAN] - **model**: `gemini-3.1-flash-lite`
[RAN] - **success**: `True`
[RAN] - **fallback_reason**: ``Gemini request failed (HTTP 400): Function call is missing a thought_signature in functionCall parts. This is required for tools to work correctly, and missing thought_signature may lead to degraded model performance. Additional data, function call `default_api:find_free_venues` , position 2. Please refer to https://aistudio.google.com/docs/thought-signatures for more details.``
[RAN] - **tokens**: `prompt_tokens=0, completion_tokens=0, total_tokens=0` (returned by `run_autopilot_with_fallback`; `agent_mode.py` sets `tokens_used` to `0` on `fixed_fallback` after turn 2 raised `ProviderError` following 1 tool-calling turn)
[RAN] - **seconds**: `3.612`
[RAN] - **provider calls used**: `2` (turn 1 returned `find_free_venues`; turn 2 failed HTTP 400)
[RAN] - **timeline steps**:
[RAN]   1. tool=`adaptive_intake` | status=`completed` | summary=`Extracted: Event Type='Cultural', Headcount=150 students, Slot=2026-11-13 (18:00:00 - 20:00:00). Assumption: 2-hour default window (18:00:00 - 20:00:00) because no end time was specified.`
[RAN]   2. tool=`find_free_venues` | status=`completed` | summary=`Discovered 2 available campus halls. Allocated 'Auditorium B (Mini Hall)' (Seats: 220) (Auto-Approved).`
[RAN]   3. tool=`recommend_from_history` | status=`completed` | summary=`Synthesized 3 campus logistics recommendations: 'Stage LED Par Lights & Spotlights' (Stage illumination required for auditorium stage performances.).`
[RAN]   4. tool=`requisition_campus_resources` | status=`committed` | summary=`Kavach Safety checks passed. Confirmed allocation of 'Auditorium B (Mini Hall)' and 3 resource bundles.`
[RAN]   5. tool=`dispatch_outbox_notices` | status=`completed` | summary=`Released official notification broadcast from Outbox to event coordinators and department head.`
[RAN] - **booking row exists afterwards**: `yes` (`event_id='ev_auto_645e7bcf'`, `events.budget=20000.0`, `events.status='allocated'`; `4` new confirmed `bookings` rows inserted, increasing total `bookings` in DB from `4` to `8`: `bk_f872cea7` `'Auditorium B (Mini Hall)'` `auto_approved`, `bk_61af29eb` `'Stage LED Par Lights & Spotlights'` qty `2`, `bk_ddd3aac3` `'JBL High-Power Sound & PA System'` qty `1`, `bk_6bac3cbe` `'Campus Special Lunch Box / Buffet'` qty `165`; all for `2026-11-13 18:00:00` to `2026-11-13 20:00:00`)
[RAN] - **outbox status**: `sent` (`1` row in `outbox` for `ev_auto_645e7bcf`: `id='notif_e94e6045'`, `type='confirmation'`, `status='sent'`, `sent_at='2026-11-11 11:31:14'`, `error_message=None`)
[RAN] - **anything paid**: `no` (every booking row for `ev_auto_645e7bcf` has `estimated_cost=0.0`, sum=`0.0`, and no payment/transaction/wallet table exists in the database schema)

[RAN] ## Run (b): `"Dance performance, 150 students, next Friday 6 PM, budget 20000"` with `budget=100`
[RAN] - **mode**: `fixed_fallback`
[RAN] - **provider**: `gemini`
[RAN] - **model**: `gemini-3.1-flash-lite`
[RAN] - **success**: `True`
[RAN] - **fallback_reason**: ``Gemini request failed (HTTP 400): Function call is missing a thought_signature in functionCall parts. This is required for tools to work correctly, and missing thought_signature may lead to degraded model performance. Additional data, function call `default_api:find_free_venues` , position 2. Please refer to https://aistudio.google.com/docs/thought-signatures for more details.``
[RAN] - **tokens**: `prompt_tokens=0, completion_tokens=0, total_tokens=0` (returned by `run_autopilot_with_fallback`; `agent_mode.py` sets `tokens_used` to `0` on `fixed_fallback` after turn 2 raised `ProviderError` following 1 tool-calling turn)
[RAN] - **seconds**: `2.346`
[RAN] - **provider calls used**: `2` (turn 1 returned `find_free_venues`; turn 2 failed HTTP 400)
[RAN] - **timeline steps**:
[RAN]   1. tool=`adaptive_intake` | status=`completed` | summary=`Extracted: Event Type='Cultural', Headcount=150 students, Slot=2026-11-13 (18:00:00 - 20:00:00). Assumption: 2-hour default window (18:00:00 - 20:00:00) because no end time was specified.`
[RAN]   2. tool=`find_free_venues` | status=`completed` | summary=`Discovered 1 available campus halls. Allocated 'Main Auditorium A (C-Block)' (Seats: 500) (Requires Dean Sign-off).`
[RAN]   3. tool=`recommend_from_history` | status=`completed` | summary=`Synthesized 3 campus logistics recommendations: 'Stage LED Par Lights & Spotlights' (Stage illumination required for auditorium stage performances.).`
[RAN]   4. tool=`requisition_campus_resources` | status=`committed` | summary=`Kavach Safety checks passed. Confirmed allocation of 'Main Auditorium A (C-Block)' and 3 resource bundles.`
[RAN]   5. tool=`dispatch_outbox_notices` | status=`completed` | summary=`Released official notification broadcast from Outbox to event coordinators and department head.`
[RAN] - **booking row exists afterwards**: `yes` (`event_id='ev_auto_3ee82a40'`, `events.budget=100.0`, `events.status='allocated'`; `4` new confirmed `bookings` rows inserted, increasing total `bookings` in DB from `8` to `12`: `bk_7b66455f` `'Main Auditorium A (C-Block)'` `pending_dean_approval`, `bk_5b8165ea` `'Stage LED Par Lights & Spotlights'` qty `2`, `bk_6aedeb8c` `'JBL High-Power Sound & PA System'` qty `1`, `bk_9afb30ce` `'Campus Special Lunch Box / Buffet'` qty `165`; all for `2026-11-13 18:00:00` to `2026-11-13 20:00:00`)
[RAN] - **outbox status**: `sent` (`1` row in `outbox` for `ev_auto_3ee82a40`: `id='notif_cd15f853'`, `type='confirmation'`, `status='sent'`, `sent_at='2026-11-11 11:31:17'`, `error_message=None`)
[RAN] - **anything paid**: `no` (every booking row for `ev_auto_3ee82a40` has `estimated_cost=0.0`, sum=`0.0`, so `budget=100.0` was not exceeded; no payment/transaction/wallet table exists in the database schema)
