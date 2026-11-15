# Test Results — AgenticLiner E2E Audit
**Date:** 2026-11-12  
**Test Environment:** Isolated temporary SQLite DBs (`conftest.py` `tmp_path` for `pytest`; `audit_live.sqlite3` seeded via `init_db.py --seed-demo` & `seed_users.py --force` for live server checks). Original `agenticliner.db` untouched.

---

## 1. Automated `pytest` Suite
| Run | Command | Result | Scope |
|---|---|---|---|
| **Baseline (Pre-Fix)** | `python -m pytest -q` | **325 passed, 1 warning** (`349.54s`) | Existing unit, API, security, benchmark, and E2E integration tests |
| **Regression Additions** | `python -m pytest tests/test_audit_bugfixes.py -q` | **6 passed, 1 warning** (`18.94s`) | 6 new tests in `tests/test_audit_bugfixes.py` covering fixed bugs |
| **Supervisor Dashboard Suite** | `python -m pytest tests/test_supervisor_dashboard_events.py -q` | **3 passed** (`17.23s`) | Event directory, complete metadata API, search & status filtering |
| **Final Full Suite (Post-Fix)** | `python -m pytest -q` | **340 passed, 1 warning** | Full regression and feature suite across all 7 core modules |

**Warning:** `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`

---

## 2. Live HTTP API, RBAC & Integration Suite (`audit_e2e_live.py` on `127.0.0.1:8000`)

### A. Authentication, RBAC & IDOR Boundary Checks
- Unauthenticated `GET /organiser` with `Accept: text/html`: **`302 Found -> /login?next=/organiser`**
- Unauthenticated `GET /organiser`, `/supervisor`, `/data-manager`, `/autopilot`, `/schedule`, `/attendees`, `/notices`, `/analytics`, `/participant` (headless without `Accept: text/html`) and protected `/api/*` + `/admin/reset-data`: **`401 Unauthorized`**
- Dev console routes (`/dev`, `/test-console`, `/dev/login`) with `TEST_CONSOLE` disabled: **`404 Not Found`**
- Weak-password signup rejected on `/signup` (`200` error response); invalid OTP on `/verify-otp` returned `422`.
- Student cross-role blocks (`GET /organiser`, `/supervisor`, `/data-manager`, `/analytics`, `POST /api/autopilot/run`, `/api/agent/universal-command`, `/api/events/ev_001/approve`, `/admin/reset-data`): **`403 Forbidden`**
- Organiser cross-role blocks (`GET /supervisor`, `/supervisor/audit-log`, `/data-manager`, `POST /api/events/ev_001/approve`, `/admin/reset-data`): **`403 Forbidden`**
- Student IDOR checks (`/api/participant/stu_01/recommendations`, `POST /api/feedback/submit` as `stu_01`, `POST /api/register` for `other@galgotias.edu`, `/api/certificates/download/CERT-2026-BFAA15CF` owned by another user): **`403 Forbidden`**

### B. 7 Core Modules Live Verification (Post-Fix)
- **Module 1 (Co-Plan & Autopilot):**
  - `POST /api/copilot/parse` -> `200 OK` (`title`, `headcount`, `venue_needed`).
  - `POST /api/autopilot/session/start` -> `draft` -> `delta` -> `confirm` -> `200 OK` (`status: "committed"`, event `ev_467e3ad6`). **Orphan `resource_id` bookings in DB: `0`** (down from `9` pre-fix).
  - `POST /api/agent/genesis` -> `200 OK` (`ev_adbf19f6`, OR-Tools schedule + outbox notice).
  - `POST /api/agent/propose-action` -> `confirm-action` -> `200 OK` (`status: "executed"`, `ev_51a74e13`).
  - `POST /api/agent/universal-command` (`"Show all available rooms"`) -> `200 OK`, `action: "VENUES_LISTED"`, **`events` count unchanged (`7 -> 7`)**.
- **Module 2 (Scheduling & Waitlist):**
  - `POST /api/schedule/solve` -> `200 OK` (`status: "OPTIMAL"`).
  - `GET /api/schedule/export.csv` (`200 OK`, `text/csv`, `681` bytes), `GET /api/export/attendees.csv?event_id=ev_001` (`200 OK`, `text/csv`, `82` bytes).
  - `POST /api/events/plan` (`room_audi_a`, `250` pax) -> `approval_status: "pending_dean_approval"` -> Supervisor `POST /api/events/{id}/approve` -> `302 Found`, DB updated to **`approved`**.
  - **Waitlist Auto-Promotion (`check_waitlist_and_agent.py`):** Capacity-1 room: Student 1 `confirmed`, Student 2 `waitlisted`; `cancel_registration(r1)` promoted Student 2 (`r2_after_cancel_status: "confirmed"`).
- **Module 3 (Resource Opt):** `GET /api/recommendations/resources?event_type=hackathon&headcount=250` -> `200 OK` (`rooms`, `volunteers`, `mics`, `food_packs`, `extension_boards`, etc.).
- **Module 4 (Participant XP):** `GET /api/participant/{student_id}/recommendations` -> `200 OK` (TF-IDF session recommendations + networking).
- **Module 5 (Comm Agent):**
  - `POST /api/assistant/ask` (`"What time is the Opening Keynote?"`) -> `200 OK`, `mode: "llm"`, `provider: "gemini"` (accurate answer from DB schedule).
  - `POST /api/assistant/ask` (`"What is the secret WiFi password..."`) -> `200 OK`, refused out-of-scope private question.
- **Module 6 (Feedback):** 4 API submissions (ratings `5`, `1`, `3`, `5` including Hinglish `"Bahut accha event tha..."`) -> `200 OK` (`fb_*` saved, accurate `positive` / `negative` sentiments and themes).
- **Module 7 (Analytics, PDFs & Certificates):**
  - `GET /analytics` rendered real DB values (`3.8 / 5.0`, `5 student reviews submitted`, `80.0% Positive | 0.0% Neutral | 20.0% Negative`, `Lexicon + Hinglish Sentiment Engine`, `/api/report/pdf/ev_001`).
  - `GET /flyer/ev_001` rendered `Galgotias Campus Innovation Hackathon 2026`, `/register?event_id=ev_001`.
  - `GET /api/report/pdf/ev_001` returned valid `%PDF-1.4` (`2887` bytes).
- **Kavach Rollbacks & Open Fixed-Mode Gap:**
  - `past_date_run` (`2026-11-07`) and `overcapacity_900_run` (`900` students) -> `success: false` (blocked/rolled back).
  - *Open Gap Recorded:* Fixed-mode `/api/autopilot/run` (`PROVIDER` unset) did not block destructive prompts (`"cancel all..."`, `"purge database..."`) and returned `success: true, mode: "fixed"` (`OPEN-01` in `BUG_REPORT.md`).

---

## 3. Bounded Live Agent Mode Check (`PROVIDER=gemini`)
- Single run via `run_autopilot_with_fallback(prompt="Organize an AI Seminar for 60 students...", budget=25000)`:
  - `seconds: 27.43`, `provider: "gemini"`, `model: "gemini-3.1-flash-lite"`
  - `mode: "fixed_fallback"`, `fallback_reason: "Gemini request failed (HTTP 504): Deadline expired before operation could complete."`
  - Fixed fallback completed all 5 pipeline steps cleanly (`success: true`).

---

## 4. Live Browser UI Verification (Post-Fix)
- **Participant Portal (`/participant`) & Feedback Modal:** Logged in as `student@galgotias.edu`, submitted 5-star review for `ev_001` (`"Great hands-on sessions and clear schedule!"`) via modal `#btnModalSubmitFeedback` -> `0` browser JS console errors; server logged `POST /api/feedback/submit 200 OK` and SQLite persisted row `fb_16b6cdd5` (`positive`).
- **Autopilot Studio (`/autopilot`):** Logged in as organiser, executed `"Dance performance, 150 students, next Friday 6 PM, budget 20000"` -> `0` console errors; SQLite persisted event `ev_auto_3b38bc7b` with exact `budget = 20000.0` (verified fixed).
- **Original DB Verification:** `agenticliner.db` unchanged (`users: 6, rooms: 7, resources: 13, speakers: 5, events: 4, sessions: 4, bookings: 13, students: 50, feedback: 0, outbox: 4, registrations: 0`).
