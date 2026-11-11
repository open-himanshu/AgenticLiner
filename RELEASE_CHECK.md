# Release Check — Fresh Clone Verification from `README.md`

- **Source repository:** `c:\PROJECTS\AgenticLiner` (branch `integrate-ai-app`, cloned `HEAD` commit `29e773b`)
- **Fresh clone directory:** `C:\Users\himan\AppData\Local\Temp\agenticliner_check_20261111_112241`
- **Host environment:** Windows, Python `3.13.16`, `.venv\Scripts\pip.exe` (`pip 26.2.1`)
- **Note on local uncommitted edits:** Working tree `c:\PROJECTS\AgenticLiner\README.md` differs from cloned `HEAD` (`29e773b`) on lines 110, 148, and 257 (wording edits and test count `282 tests` vs `224 tests` in `HEAD`). Findings below reflect the cloned `HEAD` (`29e773b`) followed strictly from `README.md`.

---

## 1. Fresh Clone & Step-by-Step `README.md` Execution

| Step | `README.md` Instruction | Result | Exact Error / Unclear Observation |
|---|---|---|---|
| Prerequisites (`:172-175`) | Python 3.10–3.13, Git | OK | Ran with Git and Python 3.13.16. |
| Step 2.1 (`:178-179`) | `# 1. Clone repository and navigate to root` -> `cd c:\PROJECTS\AgenticLiner` | Unclear | `git clone` command and URL are omitted; path hardcodes a developer-local Windows directory and no non-Windows shell commands are provided. Cloned current branch externally into `%TEMP%\agenticliner_check_20261111_112241`. |
| Step 2.2 (`:182-183`) | `python -m venv .venv` then `.\.venv\Scripts\Activate.ps1` | OK | Virtual environment created and activated cleanly. |
| Step 2.3 (`:186`) | `pip install -r requirements.txt` | Partial / Env-specific | Outside `.venv`, host `pip.exe` (`C:\Users\himan\AppData\Local\Programs\Python\Python313\Scripts\pip.exe`) failed with `Program 'pip.exe' failed to run: An Application Control policy has blocked this file`. Inside activated `.venv`, `.venv\Scripts\pip.exe` succeeded online; offline `--no-index --dry-run` failed with `ERROR: Could not find a version that satisfies the requirement fastapi==0.162.0`. |
| Step 2.4 & 3 (`:189-213`) | `copy .env.example .env`; set `GEMINI_MODEL=gemini-2.5-flash` (`:204`) | Unclear / Mismatch | `.env.example:27` sets `GEMINI_MODEL=gemini-3.1-flash-lite` rather than `gemini-2.5-flash`. Leaving `.env.example` defaults (`PROVIDER=gemini`, `GEMINI_API_KEY=your_gemini_api_key_here`) passes `backend/core/planner/call_llm.py:103-107` truthiness checks and attempts live Gemini HTTP calls at runtime (`ProviderError: Gemini request failed (HTTP 400): API key not valid. Please pass a valid API key.`). Setting `$env:PROVIDER=""` in PowerShell deletes the variable so `load_dotenv(...)` reloads `.env`; offline testing without modifying `.env` required setting an explicit non-empty invalid provider (`$env:PROVIDER="none"`) or setting `os.environ["PROVIDER"] = ""` inside Python. |
| Step 4.1 (`:217-218`) | `# Initialize SQLite tables & seed initial campus data (rooms, resources, speakers)` -> `python -m backend.core.database.init_db` | Mismatch | Printed `Database schema initialized successfully.` and `Database schema initialized in clean zero-state (use --seed-demo for demo seed).` No rooms, resources, speakers, or historical events were seeded without passing `--seed-demo`. Calling `POST /api/autopilot/run` in that state failed at step 2 (`find_free_venues`: `"No hall on campus satisfies requested capacity of 150 students on 2026-11-28. Proposing alternative hall or date."`). |
| Step 4.2 (`:221`) | `python backend/services/seed_users.py` | OK | Seeded 4 users (`admin@galgotias.edu`, `organiser@galgotias.edu`, `datamanager@galgotias.edu`, `student@galgotias.edu`) with generated passwords printed to stdout. |
| Step 5 (`:227-233`) | `python run.py` or `python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload` | OK | `python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000` started and served all routes on `http://127.0.0.1:8000`. |
| Test Console (`:267-272`) | Set `TEST_CONSOLE=1`, open `/dev` | Unclear | `README.md` omits `/dev/login` and default credentials (`admin` / `admin` in `backend/dev/test_console.py:277-278`); requesting `/dev` redirects/requires prior authentication at `/dev/login`. |
| Step 8 (`:257-258`) | `python -m pytest tests/ -q` | Error then OK | Bare `pytest.exe` inside `.venv` failed with `Program 'pytest.exe' failed to run: An Application Control policy has blocked this file`. First run of `python -m pytest -q` immediately post-install exited `1` during collection of `tests/integration/test_api.py` (`from sklearn.linear_model import Ridge`) with `ImportError: DLL load failed while importing _weight_vector: An Application Control policy has blocked this file.` (`1 warning, 1 error in 52.45s`). Re-running `python -m pytest tests/ -q` and `python -m pytest -q` passed. |

---

## 2. `pytest -q` Output in Clone (Last 5 Lines)

Exact command `python -m pytest -q` (run in clean clone `.venv` with LLM provider env vars disabled, after initial post-install DLL collection error cleared):

```text
  C:\Users\himan\AppData\Local\Temp\agenticliner_check_20261111_112241\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
281 passed, 1 warning in 371.10s (0:06:11)
```

Exact `README.md:258` command `python -m pytest tests/ -q`:

```text
  C:\Users\himan\AppData\Local\Temp\agenticliner_check_20261111_112241\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
273 passed, 1 warning in 336.17s (0:05:36)
```

(`eval/test_all_modules.py` accounts for the 8 additional tests collected by `python -m pytest -q`: `8 tests collected in 4.06s`.)

---

## 3. Page & Route Checks Without LLM Key

Tested in the fresh clone using `fastapi.testclient.TestClient(app)` with `TEST_CONSOLE=1`, `ALLOW_PUBLIC_TUNNEL=0`, Test Console authentication (`/dev/login` with `admin`/`admin`), role switches via `POST /dev/switch`, and no live LLM provider (`PROVIDER` set to invalid/disabled value so zero external LLM calls succeeded):

| Page | Request | Test-Console Role | Clean DB (`init_db`) | Seeded DB (`init_db --seed-demo`) |
|---|---|---|---|---|
| `login` | `GET /login` | unauthenticated / `organiser` | `OK` (`200`) | `OK` (`200`) |
| `dev login` | `GET /dev/login` / `POST /dev/login` / `GET /dev` | test console admin | `OK` (`200` / `303` / `200`) | `OK` (`200` / `303` / `200`) |
| `autopilot` | `GET /autopilot` | `organiser` | `OK` (`200`) | `OK` (`200`) |
| `planner` | `GET /organiser/planner` | `organiser` | `OK` (`200`) | `OK` (`200`) |
| `schedule` | `GET /schedule` | `organiser` | `OK` (`200`) | `OK` (`200`) |
| `attendees` | `GET /attendees` | `organiser` | `OK` (`200`) | `OK` (`200`) |
| `notices` | `GET /notices` (`GET /outbox`) | `organiser` | `OK` (`200` / `200`) | `OK` (`200`) |
| `analytics` | `GET /analytics` | `supervisor` | `OK` (`200`) | `OK` (`200`) |
| `participant` | `GET /participant` | `participant` | `OK` (`200`) | `OK` (`200`) |
| `participant Q&A` | `POST /api/assistant/ask` (`{"event_id":"ev_001","query":"Where is the venue?"}`) | `participant` | `OK` (`200`, `mode: "rules_fallback"`) | `OK` (`200`, `mode: "rules_fallback"`) |

---

## 4. Fixed Pipeline Run & Report Lines

- **Missing CLI command in `README.md`:** `README.md` contains no CLI command to invoke the fixed pipeline standalone (`backend/core/planner/agent.py` has no `if __name__ == "__main__":` entrypoint). Starting the web server with `README.md` commands and invoking `POST /api/autopilot/run` runs `AutopilotAgent().run_autopilot(...)` via `run_autopilot_with_fallback` (`backend/core/planner/agent_mode.py:431-487`). Unlike `legacy_team/backend/planner/fixed_pipeline.py:446` (`=== FINAL REPORT ===`), `backend/core/planner/agent.py` returns structured JSON (`success`, `event_id`, `event_name`, `venue`, `timeline`, `recommendations`, `allocation_details`) with no `final_report` field or console report lines.
- **Run 1 — Clean zero-state DB (`init_db` without `--seed-demo`):** `POST /api/autopilot/run` returned HTTP `200` with `mode: "fixed_fallback"`, `success: false`, `final_report: null`, stopped at step 2:
  - `step 1 (adaptive_intake, completed)`: `Extracted: Event Type='Hackathon', Headcount=150 students, Slot=2026-11-28 (09:00:00 - 17:00:00).`
  - `step 2 (find_free_venues, rolled_back)`: `No hall on campus satisfies requested capacity of 150 students on 2026-11-28. Proposing alternative hall or date.`
- **Run 2 — Seeded DB (`init_db --seed-demo`, `os.environ["PROVIDER"] = ""`):** `POST /api/autopilot/run` returned HTTP `200` (`mode: "fixed"`). Exact final summary fields and timeline lines from JSON response:

```text
success: true
event_id: "ev_auto_4fc005fe"
event_name: "Campus AI Hackathon"
venue: "Main Auditorium A (C-Block)"
mode: "fixed"
provider: ""
model: ""
tokens_used: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
timeline[1] (adaptive_intake | completed): Extracted: Event Type='Hackathon', Headcount=150 students, Slot=2026-11-28 (09:00:00 - 17:00:00).
timeline[2] (find_free_venues | completed): Discovered 1 available campus halls. Allocated 'Main Auditorium A (C-Block)' (Seats: 500) (Requires Dean Sign-off).
timeline[3] (recommend_from_history | completed): Synthesized 3 campus logistics recommendations: 'Heavy Duty Extension Spike Boards' (Past Hackathons: 100% of student coding teams required extra multi-socket power strips.).
timeline[4] (requisition_campus_resources | committed): Kavach Safety checks passed. Confirmed allocation of 'Main Auditorium A (C-Block)' and 3 resource bundles.
timeline[5] (dispatch_outbox_notices | completed): Released official notification broadcast from Outbox to event coordinators and department head.
```

---

## 5. `README.md` Claims Not Reproduced

1. **`README.md:217-218` ("seed initial campus data (rooms, resources, speakers)"):** `python -m backend.core.database.init_db` initializes empty tables (`clean zero-state`); `--seed-demo` must be passed manually.
2. **`README.md:257` ("224 tests, 100% pass rate, offline SQLite isolation"):** Cloned `HEAD` (`29e773b`) collected and ran `273` tests via `python -m pytest tests/ -q` and `281` tests via `python -m pytest -q`. Right after `pip install -r requirements.txt`, initial `python -m pytest -q` failed collection with `ImportError: DLL load failed while importing _weight_vector: An Application Control policy has blocked this file.`, and bare `pytest.exe` / outside-venv `pip.exe` were blocked by Application Control policy.
3. **`README.md:189, 202-204` (`copy .env.example .env`, `GEMINI_MODEL=gemini-2.5-flash`):** `.env.example:27` sets `GEMINI_MODEL=gemini-3.1-flash-lite`, not `gemini-2.5-flash`. With `.env` copied verbatim and no live key, `/api/assistant/ask` and `/api/autopilot/run` still attempt a live Gemini API call (`HTTP 400: API key not valid`) because `.env.example` sets non-empty placeholder `GEMINI_API_KEY=your_gemini_api_key_here`.
4. **`README.md:22, 99-107` (Live Gemini / Groq / Ollama tool calling):** Not reproducible in an offline environment without API keys or a running local Ollama instance (`http://localhost:11434`).
5. **`README.md:109` (Fixed Pipeline Fallback `agent.py`):** No CLI command in `README.md` or `__main__` entrypoint in `backend/core/planner/agent.py` exists to run the fixed pipeline directly; no `FINAL REPORT` text lines are produced.
6. **`README.md:152` (Kavach "Enforces 6 campus invariants ... speaker simultaneity"):** `verify_speaker_clash` (`backend/core/safety/kavach.py:111`) is not invoked by any runtime route, agent tool, or scheduling handler outside unit tests.
7. **`README.md:146, 153` ("Staged outbox notices are held until successful commit (`status = 'held' -> 'sent'`)"):** In Pillar 6 (`backend/core/planner/notification_engine.py:441-445`), `dispatch_stakeholder_notifications` inserts rows directly with `status = 'sent'`.
8. **`README.md:120` (Loop breaker after 2 turns "commits directly to venue booking"):** `_apply_loop_breaker` (`backend/core/planner/dialogue_engine.py:524-525`) sets `session.status = "ready_to_plan"` without DB writes, and `frontend/templates/autopilot.html:954-957` opens the Pre-Commit Confirmation Card (`#preCommitConfirmationCard`).
9. **`README.md:242` (`autopilot.html` "Includes a dynamic budget input box (`#agentBudget`)"):** `#agentBudget`'s container div (`frontend/templates/autopilot.html:396`) has `class="mb-3 d-none"`, hiding it in the UI.
10. **`README.md:126` (`GET /api/autopilot/memory and POST /reset`):** No `POST /reset` route exists; the implemented endpoint is `POST /api/autopilot/memory/reset` (`backend/api/main.py:1039`).
11. **`README.md:147` ("Production SMTP Bridge (`email_service.py`): Supports real email transmission"):** Not reproducible offline or without external SMTP server credentials (`SMTP_USER` / `SMTP_PASSWORD`).
12. **`README.md:113-116, 136` (Microphone Web Speech STT/TTS voice barge-in):** Depends on browser Web Speech APIs (`SpeechRecognition` / `speechSynthesis`) and microphone hardware; not reproduced in automated browser capture.
13. **`README.md:267-272` (Test console `/dev`):** `README.md` does not state default login credentials (`admin` / `admin` in `backend/dev/test_console.py:277-278`) or that `/dev/login` must be submitted before accessing `/dev`.

---

## 6. Screenshots Saved in `docs/screenshots/`

Captured from the running seeded clone on `http://127.0.0.1:8000` (`TEST_CONSOLE=1`, `PROVIDER=none`, no LLM key) and verified against host browser facts:

| File | Route Captured | Active Persona / State | Size (bytes) |
|---|---|---|---|
| `docs/screenshots/login.png` | `/login` | unauthenticated | 74626 |
| `docs/screenshots/autopilot.png` | `/autopilot` | `organiser` | 171125 |
| `docs/screenshots/planner.png` | `/organiser/planner` | `organiser` | 188461 |
| `docs/screenshots/schedule.png` | `/schedule` | `organiser` | 215576 |
| `docs/screenshots/attendees.png` | `/attendees` | `organiser` | 194950 |
| `docs/screenshots/notices.png` | `/notices` | `organiser` | 154652 |
| `docs/screenshots/analytics.png` | `/analytics` | `supervisor` | 220340 |
| `docs/screenshots/participant.png` | `/participant` | `participant` (submitted `"Where is the venue?"` Q&A) | 134702 |
| `docs/screenshots/register.png` | `/register` | `participant` | 129621 |
| `docs/screenshots/data_manager.png` | `/data-manager` | `data_manager` | 272901 |
| `docs/screenshots/organiser.png` | `/organiser` | `organiser` | 218560 |
| `docs/screenshots/supervisor.png` | `/supervisor` | `supervisor` | 184018 |
