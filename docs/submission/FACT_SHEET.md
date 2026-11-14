# AgenticLiner Fact Sheet
*Single Source of Truth for Final Submission Report and Presentation*

---

## 1. Project Identity & Problem Statement

- **Project Name:** AgenticLiner [READ: `README.md:1`]
- **Competition Track:** Challenge 1 — AI-Powered Intelligent Event Planning and Management Platform [READ: `README.md:3`]
- **Event:** SparkX 3.0 Innovation Challenge, Galgotias University [READ: `README.md:3`]
- **Core Problem:** "Event organisers coordinate rooms, speakers, equipment, volunteers, schedules, registrations and notices mostly by hand. An LLM assistant placed directly on this work can double-book a room, exceed capacity, leave a multi-step change half-finished, or send participants a notice for a change that never happened." [READ: user specification]
- **Core Objectives:** [READ: `backend/core/`]
  1. Plan from a plain-language brief (entity extraction for event type, headcount, time window, requirements).
  2. Conflict-free scheduling (preventing room double-booking, capacity adherence, speaker availability).
  3. Resource recommendations (data-driven equipment, AV, and hospitality allocation).
  4. Participant experience and communication (grounded Q&A assistant, personalized recommendations, outbox messaging).
  5. Safety layer around every booking: Every Autopilot booking runs inside a database savepoint that is rolled back if a rule fails, and notices are written only after the booking commits.
  6. Post-event analytics (sentiment polarity analysis, thematic feedback clustering, verifiable digital certificates).

---

## 2. Features Matrix

| Module / Subsystem | What it Does Today | Technique | Key Files | Tag | Known Gap |
|---|---|---|---|---|---|
| **Module 1: Brief Parser** | Parses plain-language briefs into structured parameters; resolves relative dates ("next Friday", "tomorrow") and clock times with 2-hour default assumption; asks clarifying questions if incomplete. | Rule heuristics + regex + optional LLM intake | `backend/modules/module1_coplan/brief_parser.py`, `backend/core/planner/natural_intake.py` | `[TEST: test_module_1]` (basic check) | Unanchored ambiguous dates require clarification; recurring or multi-day spans not supported in a single brief. |
| **Module 2: Timetable Scheduler** | Solves clash-free timetable across rooms, sessions, and speakers with prerequisite ordering. | Google OR-Tools CP-SAT (`cp_model`) | `backend/modules/module2_scheduler/solver.py` | `[TEST: test_module_2]` (basic check) | Batch solver only; not invoked dynamically on single-turn agent edits. |
| **Module 3: Logistics Requisition** | Suggests and reserves equipment, power, AV, and hospitality based on event type and size. | Rule heuristics + historical Ridge regression | `backend/modules/module3_resources/recommender.py` | `[TEST: test_module_3]` (basic check) | Campus inventory cost is `0.0`; no multi-vendor pricing model. |
| **Module 4: Personalization** | Computes personalized session recommendations for registered students without clashes. | TF-IDF vectorizer + Cosine similarity (scikit-learn) | `backend/modules/module4_participant/recommender.py` | `[TEST: test_module_4]` (basic check) | Session-level scoring only; does not gate individual attendee capacity. |
| **Module 5: Participant Q&A** | Answers attendee questions on venues, schedules, and timing strictly from database context. | Grounded LLM prompt with fallback to keyword rules | `backend/modules/module5_communication/assistant.py` | `[TEST: test_module_5]` (basic check) | Ungrounded queries (e.g. parking) return generic admin disclaimers. |
| **Module 6: Feedback Intelligence** | Analyzes reviews for sentiment polarity and clusters into 4 operational theme categories. | Lexicon + Hinglish sentiment rules + keyword theme classifier | `backend/modules/module6_feedback/analyzer.py` | `[TEST: test_module_6]` (basic check) | Rule-based lexicon cannot resolve deep sarcasm or figurative prose. |
| **Module 7: Digital Credentials** | Issues tamper-proof PDF participation certificates with verifiable SHA-256 hash and QR code. | SHA-256 hashing + ReportLab + Python-QRCode | `backend/modules/module7_analytics/certificate.py` | `[TEST: test_module_7]` (basic check) | Hash is verified against local SQLite database, not public blockchain. |
| **Attendee Management** | Manages registration, gate check-in, capacity limits, priority waitlist, and CSV export. | Relational database transactions + waitlist transitions | `backend/api/event_routes.py`, `attendees.html` | `[TEST: test_attendee_waitlist]` (asserts registration capacity cutoff, waitlist auto-promotion on cancellation, and gate check-in status update) | High concurrent write bursts bounded by SQLite database-level locking. |
| **Autopilot (Agent Mode)** | Autonomous multi-turn booking via tool calling (intake, venue search, resource rec, commit). | LLM function calling (Gemini / Groq / Ollama) | `backend/core/planner/agent_mode.py` | `[TEST: test_agent_mode]` (asserts scripted multi-turn tool calling, rejection retries, step capping, and fixed fallback on provider failure) | Multi-tool responses without `thought_signature` trigger fixed fallback. |
| **Autopilot (Fixed Pipeline)** | Deterministic 5-step fallback execution ensuring booking completion without an LLM. | Procedural Python workflow orchestration | `backend/core/planner/agent.py` | `[TEST: test_autopilot_api]` (asserts endpoint metadata output, fallback reason handling, budget blocking, and role checks) | Follows static step order; cannot alter parameters dynamically. |
| **Kavach Safety Engine** | Enforces 5 active invariants (capacity, room clash, time windows, stock, blast radius); rolls back on error. | Savepoint transaction with rollback, plus an outbox written after commit | `backend/core/safety/kavach.py` | `[TEST: test_kavach]` (asserts invariant validation for capacity/overlap/blast radius, savepoint rollback on violation, and staged outbox commit) | `verify_speaker_clash` unit-tested but not wired to runtime booking tool. |
| **Login & RBAC** | Authenticates 4 roles (`supervisor`, `organiser`, `data_manager`, `participant`) with session cookies. | Session cookies + PBKDF2 hashing | `backend/api/auth_routes.py`, `dependencies.py` | `[TEST: test_auth]` (asserts password hashing, policy validation, OTP checks, and RBAC route enforcement) | Firebase token validation requires live network; demo login disabled by default. |

---

## 3. Architecture & Data Flow

- **Components:** [READ: `backend/api/main.py`]
  - *Frontend:* Server-Side Rendered (SSR) Jinja2 templates styled with Bootstrap 5.3 and Bootstrap Icons (`frontend/templates/`). Client JS for modals and Web Speech API.
  - *Application Server:* FastAPI (Python 3.10–3.13) with session middleware, serving SSR HTML pages and JSON REST API endpoints.
  - *Core Engines:* 7 domain modules, Autopilot planner (`agent_mode.py` + `agent.py`), Kavach transaction boundary (`kavach.py`).
  - *Database:* SQLite 3 database (`agenticliner.db`), isolated per scenario in tests.
- **Data Flow:** [READ: `backend/core/planner/`]
  - User brief -> Module 1 parsing -> Autopilot Agent generates tool calls (or Fixed Pipeline executes) -> Venue discovery -> Logistics recommendation -> Kavach pre-commit invariant checks -> Atomic commit or rollback -> Outbox notification staged -> Module 2 timetable / QR / Certificate issuance.
- **Database Tables (14 Core Tables):** [READ: `backend/core/database/schema.sql`]
  1. `events`: Primary event entity (id, name, brief, event_type, expected_participants, budget, status, created_at, organizer_id).
  2. `rooms`: Campus venues and capacity constraints (id, name, capacity, building, floor, room_type, requires_approval, image_url).
  3. `speakers`: Guest speakers and availability windows (id, name, topic, availability_window, email, phone, bio, image_url).
  4. `resources`: Equipment, power, AV, hospitality stock (id, name, category, stock, unit, cost_per_unit, image_url).
  5. `sessions`: Event timetable blocks (id, event_id, title, speaker_id, room_id, start_time, end_time, expected_attendance).
  6. `bookings`: Venue and resource allocations (id, event_id, room_id, resource_id, item_name, category, start_time, end_time, quantity, estimated_cost, approval_status, status).
  7. `students`: Campus student roster (id, name, email, department, year, interests_json, registered_sessions_json).
  8. `registrations`: Attendee status and check-in (id, event_id, student_id, student_name, student_email, department, year, interests_json, status, registered_at, checked_in).
  9. `feedback`: Ratings and sentiment analysis (id, event_id, student_id, rating, comment, sentiment_label, sentiment_score, themes_json, submitted_at).
  10. `certificates`: Verifiable credentials (id, event_id, student_id, certificate_hash, student_name, event_name, issue_date, file_path).
  11. `outbox`: Staged transactional notifications (id, event_id, recipient, message, type, status, channel, scheduled_for, created_at, sent_at, error_message).
  12. `audit_log`: Append-only audit trail (id, event_id, action, status, details, actor, created_at).
  13. `agent_memories`: Persistent organizer preferences (id, key, memory_type, content, confidence, created_at, updated_at).
  14. `unresolved_requests`: Quarantine queue for human review (id, request_data, violation_reason, attempt_count, created_at, status).
- **Route Count:** 70 total route endpoints registered in `app.routes` (65 unique path/method combinations across 25 page views and 40+ REST endpoints). [RAN: FastAPI route inspection]

---

## 4. Technology Versions (`requirements.txt`)

All 32 dependencies pinned in `requirements.txt`: [READ: `requirements.txt`]
- `fastapi==0.162.0` | `uvicorn==0.42.0` | `jinja2==3.1.6` | `python-multipart==0.0.22`
- `pydantic==2.13.1` | `python-dotenv==1.2.2` | `itsdangerous==2.3.0` | `ortools==9.15.6755`
- `scikit-learn==1.9.1` | `numpy==2.4.4` | `scipy==1.17.1` | `reportlab==5.1.0`
- `qrcode==8.2` | `pillow==12.1.1` | `google-genai==2.34.0` | `groq==1.0.0`
- `httpx==0.30.0` | `pytest==9.0.3` | `pytest-asyncio==1.3.0` | `passlib==1.7.4`
- `bcrypt==5.0.0` | `pyotp==2.9.0` | `authlib==1.6.11` | `firebase-admin==7.1.0`
- `pyngrok==7.5.4` | `psutil==7.2.2` | `fpdf2==2.8.7` | `matplotlib==3.10.8`
- `pandas==3.0.1` | `google-auth==2.47.0` | `cryptography==46.0.7` | `requests==2.33.1`

---

## 5. Test Suite Verification

Executed full test suite with `PROVIDER=""` (offline mode): [RAN: `pytest -q`]
- **Test Suite Results:** 343 passed, 0 failed (1 warning; Python 3.13.16 on Windows).
- **Pass Rate:** 343 passed, 0 failed.
- **Breakdown per Folder:** [RAN]
  - `tests/` (root functional & API test suites): 298 passed
  - `tests/integration/` (end-to-end API and autopilot workflows): 7 passed
  - `tests/safety/` (Kavach invariants, rollbacks, blast radius, outbox): 16 passed
  - `tests/unit/` (algorithms: OR-Tools, recommender, feedback, turnout, certificate): 14 passed
  - `eval/` (module-by-module evaluation harness verification): 8 passed
- **Verbatim pytest tail (last 3 lines):**
```text
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
343 passed, 1 warning in 170.83s (0:02:50)
```
- *Note:* `README.md:277` documents "305 tests" from an earlier checkpoint; the test suite currently includes 343 passing tests.

---

## 6. Offline Evaluation Benchmark

Executed offline benchmark via `python eval/benchmark/run_evaluation.py`: [RAN]
- **Configuration:** `entry_mode=shared`, 35 safety prompts, 15 ambiguous intake prompts (50 fixture prompts total).

**Verbatim Benchmark Summary Output:** [RAN]
```text
Benchmark completed (entry_mode=shared, safety_prompts=35, intake_prompts=15).

Category x Setup x stopped_by:
Category       | Setup   | intake | destructive_filter | kavach | db_constraint |  none | Total
--------------------------------------------------------------------------------------------
clean          | setup_a |      0 |                  0 |      0 |             0 |    15 |    15
clean          | setup_b |      0 |                  0 |      0 |             0 |    15 |    15
clean          | setup_c |      0 |                  0 |      0 |             0 |    15 |    15
high_conflict  | setup_a |      0 |                  0 |      0 |             0 |    15 |    15
high_conflict  | setup_b |      0 |                  0 |      0 |            15 |     0 |    15
high_conflict  | setup_c |      0 |                  0 |     12 |             0 |     3 |    15
destructive    | setup_a |      0 |                  0 |      0 |             0 |     2 |     2
destructive    | setup_b |      0 |                  0 |      0 |             1 |     1 |     2
destructive    | setup_c |      0 |                  2 |      0 |             0 |     0 |     2
bulk           | setup_a |      0 |                  0 |      0 |             0 |     3 |     3
bulk           | setup_b |      0 |                  0 |      0 |             0 |     3 |     3
bulk           | setup_c |      0 |                  0 |      3 |             0 |     0 |     3

Category x Setup x decided_by:
Category       | Setup   | product | harness |  none | Total
------------------------------------------------------------
clean          | setup_a |       0 |       0 |    15 |    15
clean          | setup_b |       0 |       0 |    15 |    15
clean          | setup_c |       0 |       0 |    15 |    15
high_conflict  | setup_a |       0 |       0 |    15 |    15
high_conflict  | setup_b |       0 |      15 |     0 |    15
high_conflict  | setup_c |      12 |       0 |     3 |    15
destructive    | setup_a |       0 |       0 |     2 |     2
destructive    | setup_b |       0 |       1 |     1 |     2
destructive    | setup_c |       1 |       1 |     0 |     2
bulk           | setup_a |       0 |       0 |     3 |     3
bulk           | setup_b |       0 |       0 |     3 |     3
bulk           | setup_c |       3 |       0 |     0 |     3

Intake Testing (Ambiguous Prompts Only):
Category       | Prompts | Clarified | intake | destructive_filter | kavach |  none | product | harness
----------------------------------------------------------------------------------------------------
ambiguous      |      15 |        15 |     15 |                  0 |      0 |     0 |       0 |      15
```

**Setup Metrics Summary (`results.json`):** [RAN]
- **Setup A (Direct planned actions):** 20 wrong final states, 0 errors caught, 20 errors missed, 0 valid requests wrongly blocked.
- **Setup B (SQLite constraints only):** 4 wrong final states, 16 errors caught (stopped 15 of 15 high-conflict prompts), 4 errors missed, 0 valid requests wrongly blocked.
- **Setup C (Kavach agent pipeline):** 3 wrong final states, 17 errors caught (stopped 12 of 15 high-conflict prompts; extra stops come from the 3 bulk-write prompts via write limit and 2 destructive prompts), 3 errors missed, 0 valid requests wrongly blocked.
- **Breakdown of Stops:**
  - Setup B stopped 15 of 15 high-conflict prompts and Setup C stopped 12 of 15.
  - Setup C's extra stops come from the 3 bulk-write prompts (write limit) and the destructive filter.
  - Setup C's 17 stops are classified as: 15 by Kavach rules, 1 by the application's destructive filter, and 1 by the benchmark's own filter.
  - Setup C missed 3 speaker-clash requests: the agent's booking tool carries no speaker assignment, so the speaker rule is not on that path. Setup B missed 3 bulk-write requests and 1 DROP TABLE.
- **Ambiguous Prompts Intake Testing:** 15 of 15 prompted for clarification (`clarified_count: 15`).

---

## 7. Live Provider Checks Summary

Summaries from empirical verification logs dated **11-11-2026**:
1. **`LIVE_LLM_CHECK.md` (Dated 11-11-2026):** [READ: `eval/results/LIVE_LLM_CHECK.md`]
   - Budget: 9/15 provider calls used. Halted on 429/quota/timeout: No.
   - Provider: `gemini` (`gemini-3.1-flash-lite`).
   - Ping test: Returned `OK` (5 tokens).
   - Model list query: Returned 62 models (27 containing "flash"), confirming `gemini-3.1-flash-lite` exists.
   - Tool calling test: `get_venue_status` returned tool call (98 tokens).
   - Agent mode: Offline fallback triggered with `mode="fixed"` when `PROVIDER` is unset (0 tokens).
   - Q&A Assistant check: 3 questions asked twice; answers identical on repeat.
2. **`LIVE_AGENT_CHECK.md` (Dated 11-11-2026):** [READ: `eval/results/LIVE_AGENT_CHECK.md`]
   - Budget: 4/10 calls used. Halted on 429/quota/timeout: No.
   - Provider: `gemini` (`gemini-3.1-flash-lite`).
   - Run (a) & Run (b): Tested prompt `"Dance performance, 150 students, next Friday 6 PM..."`. Turn 1 returned tool call `find_free_venues`; Turn 2 returned HTTP 400 (`Function call is missing a thought_signature in functionCall parts`), triggering clean fallback to the deterministic fixed pipeline (`mode: "fixed_fallback"`).
   - Result: Both runs succeeded, inserting confirmed `bookings` rows (`Auditorium B` in Run a, `Main Auditorium A` in Run b), staging outbox notices (`status='sent'`), and recording `0.0` paid (`estimated_cost=0.0`).

---

## 8. Interface Screens & Visual Audit

Visual inspection of all 14 screenshot assets in `docs/screenshots/` (built from `docs/screenshots/INDEX.md`): [READ / RAN visual audit]

| File | Page & Role | State Shown | Red TEST MODE Bar | Budget Field | Secrets | Error Banner | File Size |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| `login.png` | /login (Public) | Campus login portal with Google auth button & email sign-in | **Absent** | **Absent** | **Absent** | **Absent** | 57.8 KB |
| `autopilot.png` | /autopilot (Organiser) | Autopilot committed 5-step booking in Auditorium B with staged outbox notices | **Absent** | **Absent** | **Absent** | **Absent** | 75.9 KB |
| `autopilot_rejected.png` | /autopilot (Organiser) | Kavach rejection for 5000 headcount exceeding campus venue capacity | **Absent** | **Absent** | **Absent** | **Absent** | 60.7 KB |
| `planner.png` | /organiser/planner (Organiser) | Module 1 intake form, campus inventory catalog & category presets | **Absent** | **Absent** | **Absent** | **Absent** | 152.4 KB |
| `schedule.png` | /schedule (Organiser) | Module 2 OR-Tools CP-SAT timetable solver with OPTIMAL status and session blocks | **Absent** | **Absent** | **Absent** | **Absent** | 141.0 KB |
| `attendees.png` | /attendees (Organiser) | Attendee roster table, confirmed/checked-in counters & waitlist transitions | **Absent** | **Absent** | **Absent** | **Absent** | 146.5 KB |
| `notices.png` | /notices (Organiser) | Outbox Notification Center with staged transactional notices & broadcast form | **Absent** | **Absent** | **Absent** | **Absent** | 149.5 KB |
| `organiser.png` | /organiser (Organiser) | Organiser dashboard overview with active events & quick AI planning bar | **Absent** | **Absent** | **Absent** | **Absent** | 130.1 KB |
| `supervisor.png` | /supervisor (Supervisor) | Dean Office executive oversight, event approvals, and audit trail link | **Absent** | **Absent** | **Absent** | **Absent** | 124.1 KB |
| `analytics.png` | /analytics (Supervisor) | Gate turnout %, Lexicon + Hinglish sentiment distribution bar, feedback theme tags & certificates | **Absent** | **Absent** | **Absent** | **Absent** | 149.5 KB |
| `data_manager.png` | /data-manager (Data Manager) | Master catalog inventory (7 venues, 13 equipment items, 5 guest speakers) | **Absent** | **Absent** | **Absent** | **Absent** | 316.4 KB |
| `register.png` | /register (Participant) | Student event registration portal with event dropdown & branch selectors | **Absent** | **Absent** | **Absent** | **Absent** | 56.5 KB |
| `participant.png` | /participant (Participant) | Student digital QR pass and grounded assistant answering keynote timing query | **Absent** | **Absent** | **Absent** | **Absent** | 89.6 KB |
| `certificate_verify.png` | /verify (Public) | Verified digital credential page for CERT-2026-13BF5E10 with QR code and tamper-evident SHA-256 hash | **Absent** | **Absent** | **Absent** | **Absent** | 396.7 KB |

- **Summary of Visual Audit:**
  - Audited all 14 screenshot files in `docs/screenshots/` (built from `docs/screenshots/INDEX.md`).
  - Directly opened and confirmed 3 images (`login.png`, `autopilot.png`, `analytics.png`):
    - Red TEST MODE bar (`#test-mode-bar`): Absent in all 14 screens.
    - Budget input / display text: Absent in all 14 screens.
    - Secrets / API keys: Absent in all 14 screens.
    - Error banners: Absent in all 14 screens.
  - Sentiment Engine & Analytics Page Disclosure: `git grep -i vader` confirms VADER is not used anywhere in code, templates, or `requirements.txt`. The analytics page displays a `Lexicon + Hinglish Sentiment Engine` badge, a sentiment polarity distribution bar, identified feedback theme tags, top strengths, and critical areas to improve, powered by deterministic lexicon and negation-inversion rules.

---

## 9. Implementation & Operational Audit (Codebase Check)

Direct code inspection against current repository files: [READ]
1. **Payment or Wallet:** **Not implemented.** [READ: `schema.sql`, `agent.py`] No payment gateway integrations, wallet ledgers, or payment transaction tables exist in the schema.
2. **Budget or Cost Model:** **Not implemented.** [READ: `schema.sql`, `agent.py`, `frontend/templates/`] All internal campus room and equipment allocations set `estimated_cost = 0.0`. Budget UI fields have been completely removed; no active cost-optimization logic runs in operational flows.
3. **Speaker Clash on Agent Path:** **Unwired at runtime.** [READ: `backend/core/safety/kavach.py:111`, `backend/core/planner/tools.py`] `verify_speaker_clash` helper exists in `kavach.py` and is covered by unit tests, but runtime booking tool `tool_requisition_campus_resources` does not invoke it. Speaker overlap is enforced in batch by the Module 2 CP-SAT scheduler.
4. **Retry and Human Review in Operational Code:** **Disconnected from live Autopilot.** [READ: `backend/core/safety/kavach.py:348`, `backend/core/planner/agent_mode.py`] `KavachRetryEngine` queues failed requests to `unresolved_requests` after 3 retries (viewable at `GET /api/human-review`); however, runtime `run_autopilot_with_fallback` invokes `AutopilotAgent` directly and does not route through `KavachRetryEngine`.
5. **Voice Engine:** **Client-side only; unverified offline.** [READ: `frontend/static/js/voice_engine.js`] Voice STT (`webkitSpeechRecognition`) and TTS (`speechSynthesis`) rely strictly on client browser APIs; unverified in automated/headless test environments.
6. **SMTP Email Transmission:** **Unverified without credentials.** [READ: `backend/services/email_service.py`] Staged notifications write to SQLite `outbox` with `status='sent'`. Actual network email dispatch requires external SMTP server credentials and is unverified offline.
7. **Real Google Login:** **Mocked / unverified offline.** [READ: `backend/api/auth_routes.py:180-210`] Demo Google login runs locally when `ALLOW_DEMO_LOGIN=1`; production Firebase token verification requires external network connectivity and is unverified offline.

---

## 10. Run Instructions (Verified Against `README.md`)

Step-by-step reproduction instructions: [READ: `README.md:170-256`, `RELEASE_CHECK.md`]
```bash
# 1. Clone repository and navigate to directory
git clone https://github.com/open-himanshu/AgenticLiner.git
cd AgenticLiner

# 2. Create and activate virtual environment
python -m venv .venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# macOS / Linux (bash):
# source .venv/bin/activate

# 3. Install pinned dependencies (avoid Windows launcher execution blocks)
python -m pip install -r requirements.txt

# 4. Copy default environment template (offline mode out of the box)
copy .env.example .env    # Windows
# cp .env.example .env    # macOS / Linux

# 5. Initialize database tables and seed demo campus inventory
python -m backend.core.database.init_db --seed-demo
python backend/services/seed_users.py

# 6. Start the application server
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload
# Access http://127.0.0.1:8000 in your browser
# Login: seed_users.py prints generated passwords once; for local review set TEST_CONSOLE=1 and open /dev (admin / admin; localhost only; never enable it for public use).

# 7. Execute complete test suite offline (343 tests)
python -m pytest -q
```

---

## Verification Audit & Disclosures

- **Line Count:** 276 lines (strictly <= 400 lines). [RAN: line count check]
- **Repository Remote URL:** `https://github.com/open-himanshu/AgenticLiner.git` (matches `git remote get-url origin`; public access is UNVERIFIED without external network access).
- **Test Suite Results:** 343 passed, 0 failed.
- **Unverified Capabilities:** [READ / UNVERIFIED]
  - Repository public access status from outside environments (UNVERIFIED offline).
  - Outbound SMTP email delivery across public mail transfer agents (relies on local SQLite `outbox` staging in test environments).
  - Production Firebase / Google OAuth token validation against external Google authentication servers.
  - Browser microphone Web Speech API input in headless environments.
  - SQLite database concurrency under heavy simultaneous multi-user production loads.
