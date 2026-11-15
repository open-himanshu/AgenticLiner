# Bug Report — AgenticLiner E2E Audit
**Date:** 2026-11-12  
**Original DB Status:** Untouched (`agenticliner.db` zero mutations)

---

## Part 1: Fixed & Verified Bugs

### BUG-01 [HIGH] — `/participant` Feedback Modal Submit Button Crash (`TypeError`)
- **File:** `frontend/templates/participant.html:299-332`
- **Root Cause:** Inline `<script>` bound `document.getElementById('btnModalSubmitFeedback').addEventListener(...)` synchronously before `<div class="modal fade" id="feedbackModal">` (line 335+) was parsed into the DOM, throwing `Uncaught TypeError: Cannot read properties of null (reading 'addEventListener')` on every `/participant` page load and silently breaking feedback submission.
- **Fix Applied:** Wrapped listener binding in `document.addEventListener('DOMContentLoaded', ...)`, added null safety + `!res.ok` error display before reading `data.analysis`.
- **Verification:** Live browser submitted a 5-star review on `/participant` with `0` console errors; SQLite `feedback` row (`fb_16b6cdd5`, sentiment `positive`) persisted; `tests/test_audit_bugfixes.py::test_participant_feedback_modal_bound_after_dom_ready` passes.

### BUG-02 [HIGH] — Non-JSON `str(list)` Persistence Crashing Participant Recommendations
- **Files:** `backend/modules/module2_scheduling/attendee_manager.py:10, 44, 90`; `backend/modules/module4_participant_xp/recommender.py:10-40, 122-138`
- **Root Cause:** `AttendeeManager.register_student()` serialized `interests` and `preferred_sessions` using Python `str(list)` (`['AI', 'Python']` with single quotes). `ParticipantExperienceEngine.recommend_networking()` called `json.loads(...)`, raising `JSONDecodeError` on legacy/registered students. Missing student branch also returned mismatched keys (`{"peers": [], "speakers": []}` instead of `peer_matches` / `mentor_matches`).
- **Fix Applied:** Switched `attendee_manager.py` to `json.dumps(...)`, added `_parse_interests_list()` (JSON -> `ast.literal_eval` -> comma fallback) in `recommender.py`, and aligned missing-student return schema (`peer_matches`, `mentor_matches`).
- **Verification:** `tests/test_audit_bugfixes.py::test_attendee_manager_stores_valid_json_and_recommender_handles_legacy_lists` passes.

### BUG-03 [MEDIUM] — Analytics Dashboard Hardcoded Defaults, `0.0%` Override & Misleading Engine Label
- **File:** `frontend/templates/analytics.html:20-27, 57, 77-92, 195-215`
- **Root Cause:**
  1. Executive PDF button hardcoded `/api/report/pdf/ev_001` with no event selector dropdown.
  2. Average rating displayed hardcoded `4.8 / 5.0` when `fb_count == 0`.
  3. Sentiment progress bar used Jinja `or 75` / `or 15` / `or 10`, which treated real `0.0%` values (e.g., `0.0% Positive` when all reviews are negative) as falsy and displayed `75% / 15% / 10%` instead.
  4. UI badge falsely claimed `VADER Polarity Engine` while backend `analyzer.py` uses custom Lexicon + Negation + Hinglish rules.
  5. "Autonomous Post-Event AI Advisory" displayed 3 hardcoded hackathon bullets regardless of DB state.
- **Fix Applied:** Dynamic `/api/report/pdf/{{ selected_event_id or 'ev_001' }}` + event `<select>`, `N/A` when `fb_count == 0`, truthful `Lexicon + Hinglish Sentiment Engine` badge, explicit `fb_count > 0` check so `0.0%` renders accurately, and DB-driven advisory bullets.
- **Verification:** Verified against live server (`ANALYTICS_RATING: ['3.8 / 5.0']`, `['80.0% Positive', '0.0% Neutral', '20.0% Negative']`, `ANALYTICS_VADER_PRESENT: False`) and `tests/test_audit_bugfixes.py::test_analytics_honest_zero_and_negative_only_display`.

### BUG-04 [HIGH] — Confirmation Engine Resource ID Mismatch Creating Orphan Bookings
- **File:** `backend/core/planner/confirmation_engine.py:70-83`
- **Root Cause:** `_FALLBACK_RESOURCE_COSTS` mapped standard equipment/food/volunteers to non-existent IDs (`res_proj_4k`, `res_mic_pair`, `res_mic_lapel`, `res_audio_sound`, `res_light_pack`, `res_snack_box`, `res_vol_desk`) instead of seeded `resources.id` values (`res_projector_4k`, `res_mic_cordless`, `res_mic_collar`, `res_sound_jbl`, `res_led_lights`, `res_food_snack`, `res_volunteer_reg`). Pre-fix live check found `9` orphan `bookings` rows failing `LEFT JOIN resources`.
- **Fix Applied:** Updated `_FALLBACK_RESOURCE_COSTS` IDs to match seeded campus `resources` IDs.
- **Verification:** Re-run of live E2E audit recorded **`orphan_resource_bookings_count: 0`**; `tests/test_audit_bugfixes.py::test_confirmation_fallback_resource_ids_exist_in_seeded_resources` passes.

### BUG-05 [MEDIUM] — Autopilot UI Hidden Budget (`100000`) Overriding Prompt Budget (`20000`)
- **File:** `frontend/templates/autopilot.html:398, 1209, 1388`
- **Root Cause:** Hidden `<input id="agentBudget" value="100000">` caused JS to send `budget_limit: 100000` to `/api/autopilot/session/start`, locking `100000.0` before prompt extraction of `"budget 20000"`.
- **Fix Applied:** Emptied default `value=""` with placeholder and sent `null` unless user enters a positive number.
- **Verification:** Live browser Autopilot run with `"Dance performance, 150 students, next Friday 6 PM, budget 20000"` persisted `budget = 20000.0` in SQLite `events` (`ev_auto_3b38bc7b`), vs `100000.0` pre-fix; `tests/test_audit_bugfixes.py::test_autopilot_budget_input_does_not_hardcode_100000` passes.

### BUG-06 [LOW] — Hardcoded AI Hackathon Branding & QR Target on Event Flyer
- **File:** `frontend/templates/flyer.html:57-89`
- **Root Cause:** Every event flyer rendered hardcoded `School of AI`, AI hackathon subtitle, static `https://galgotiasuniversity.edu.in/event-registration` QR target, and hardcoded AI/PyTorch track badges.
- **Fix Applied:** Bound header category badge, subtitle (`event.brief`), `/register?event_id={{ event.id }}` link/QR data, and highlight chips (`event.event_type`, `venue`, `expected_participants`) to actual event data.
- **Verification:** Live `GET /flyer/ev_001` rendered `Galgotias Campus Innovation Hackathon 2026`, `/register?event_id=ev_001`, and dynamic badges.

### BUG-07 [MEDIUM] — Universal Command Creating Unwanted Events on Read-Only Queries
- **File:** `backend/services/agentic_genesis_service.py:519-540`
- **Root Cause:** `execute_universal_command("Show all available rooms")` had no read-only query branch, fell through to `execute_autonomous_event_genesis(command)`, and inserted a bogus workshop into SQLite.
- **Fix Applied:** Added read-only room/venue/event listing handlers (`VENUES_LISTED` / `EVENTS_LISTED`) when read verbs are used without creation intent.
- **Verification:** Live `POST /api/agent/universal-command` (`"Show all available rooms"`) returned `VENUES_LISTED` with `events: 7 -> 7` (0 events created); `tests/test_audit_bugfixes.py::test_universal_command_read_only_room_query_creates_no_event` passes.

### BUG-08 [HIGH] — Supervisor Dashboard Omitted Auto-Approved Events & Lacked Meaningful Event Details
- **Files:** `backend/api/main.py:1086-1120`, `backend/services/event_workflow_service.py:650-730`, `frontend/templates/supervisor.html`
- **Root Cause:**
  1. The supervisor dashboard endpoint strictly filtered active events with `WHERE e.approval_status = 'approved'`. Events created through Autopilot and Assistant workflows receive `approval_status = 'auto_approved'`, causing the dashboard to show `0` active events and completely empty event listings despite active campus events in SQLite.
  2. The table only displayed 4 shallow columns with no capability to view or inspect event details, agendas, booked venues, requisitions/equipment, or attendees.
  3. `get_event_with_details` had column naming discrepancies with SQLite schema (`res.total_stock` -> `res.stock`, `sp.expertise` -> `sp.department`/`sp.topics`, `st.year_of_study` -> `st.year`), which caused `500 Internal Server Error` on event detail queries.
- **Fix Applied:**
  1. Updated the supervisor query to include both `'approved'` and `'auto_approved'` under active events, and added dynamic status filtering (`all`, `pending`, `approved`, `cancelled`) and search.
  2. Implemented a comprehensive Campus Events Directory table displaying Event ID, Title & Brief, Category, Slot Timing, Allocated Venue & Capacity, Organizer Dept & Email, Confirmed / Expected Attendance, Status Badges, and Action buttons.
  3. Built an interactive Event Inspection Modal (`#inspectModal{{ ev.id }}`) that provides supervisors with complete visibility into logistics, budget, equipment requisitions, session agenda with speakers, attendee rosters, and authority actions.
  4. Fixed schema column mappings in `get_event_with_details` and created `tests/test_supervisor_dashboard_events.py` (3 passed).
- **Verification:** `tests/test_supervisor_dashboard_events.py` passed (3/3), verifying that auto-approved events appear, search/filter works, and complete event information is returned.

---

## Part 2: Open Issues & Documented Limitations

### OPEN-01 [MEDIUM / SECURITY] — Destructive Prompts Not Blocked in Fixed-Mode `/api/autopilot/run`
- **File:** `backend/core/planner/agent_mode.py:437-453`
- **Observed Evidence:** While `agent_mode` and `dialogue_engine` block destructive prompts (`cancel all`, `purge database`, `drop table`), `run_autopilot_with_fallback()` short-circuits directly to `AutopilotAgent().run_autopilot()` when `PROVIDER` is unset without calling `_is_destructive(prompt)`. In live E2E re-test (`PROVIDER` unset), `/api/autopilot/run` returned `200 OK` with `success: true, mode: "fixed"` on those 3 destructive strings instead of blocking them.
- **Reason Left Open:** `eval/benchmark/run_evaluation.py` calls `run_autopilot_with_fallback()` to evaluate benchmark Setup B behavior; adding a fixed-mode intake block directly in `run_autopilot_with_fallback()` would alter benchmark assertions in `tests/test_benchmark_fixtures.py`.
- **Recommended Fix:** Gate `/api/autopilot/run` with `_is_destructive()` at the HTTP route handler or explicit `AgentMode`/`AutopilotAgent` policy without changing benchmark harness paths.

### OPEN-02 [MEDIUM / LATENCY] — Direct `genai.Client` & Unset `PROVIDER` Default Causing 20–30s Timeout Fallback
- **Files:** `backend/core/planner/call_llm.py:128`; `backend/services/agentic_genesis_service.py:41-42`
- **Observed Evidence:** `get_provider_config()` defaults unset `PROVIDER` to `"gemini"` when `.env` contains `GEMINI_API_KEY`, and `agentic_genesis_service.py` constructs `genai.Client` directly without respecting `PROVIDER` or setting a short `HttpOptions(timeout=...)`. When Gemini returned `503 UNAVAILABLE` / TLS handshake timeout / `504 Deadline expired`, `/api/agent/genesis` and `/api/assistant/ask` stalled ~20–30 seconds before falling back cleanly.
- **Recommended Fix:** Require explicit opt-in (`PROVIDER=gemini|groq|ollama`) or configure a short request timeout + route `agentic_genesis_service.py` through `call_llm.py`.

### OPEN-03 [LOW / SCOPE] — Fixed-Mode Cost Estimation Not Implemented (`estimated_cost = 0.0`)
- **Files:** `backend/core/planner/agent.py`, `backend/core/database/schema.sql`
- **Observed Evidence:** Fixed Autopilot records `budget` on `events`, sets `estimated_cost = 0.0` on `bookings`, and has no payment or wallet ledger (explicitly disclosed on `/autopilot` UI help text).

### OPEN-04 [LOW] — Attendee & Notices Pages Partially Scoped to `ev_001`
- **Files:** `frontend/templates/attendees.html:23`, `frontend/templates/notices.html:130`
- **Observed Evidence:** Attendee CSV export link (`?event_id=ev_001`) and quick announcement staging (`event_id: 'ev_001'`) target `ev_001` unless parameterized via query/selector.
