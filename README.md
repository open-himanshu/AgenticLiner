# AgenticLiner 🚀
> **Autonomous Campus Event Planning & Operations Platform with Kavach Transaction Safety, Multi-Provider LLM Tool Calling, and Real-Time Logistics Sandboxing**  
> *SparkX 3.0 International Innovation Challenge — Challenge #1*

---

## 📋 Table of Contents
1. [Project Overview](#-project-overview)
2. [Architecture & Folder Structure](#-architecture--folder-structure)
3. [The 7 Functional Modules](#-the-7-functional-modules)
4. [Autopilot Engine: Agent Mode & Kavach Safety](#-autopilot-engine-agent-mode--kavach-safety)
5. [Role-Based Access Control (RBAC) & Seed Accounts](#-role-based-access-control-rbac--seed-accounts)
6. [Team Quickstart & Setup Guide](#-team-quickstart--setup-guide)
7. [Frontend & UI Developer Guide](#-frontend--ui-developer-guide)
8. [Testing & Quality Assurance](#-testing--quality-assurance)

---

## 🌟 Project Overview

**AgenticLiner** is a comprehensive academic operations and intelligent event management platform built for universities. It replaces fragmented paper requisitions and ad-hoc spreadsheets with:
- **Autonomous Multi-Turn Tool Calling:** Models (Gemini, Groq, Ollama) dynamically discover campus venues, inspect logistics inventory, consult historical trends, and draft bookings.
- **Kavach Safety & Invariant Sandboxing:** Every state mutation executes within isolated SQLite savepoints that enforce room capacity, time overlaps, stock quotas, and strict budget caps. Any violation instantly rolls back state.
- **7 End-to-End Operational Modules:** Brief parsing, conflict-free timetable scheduling (Google OR-Tools CP-SAT), Flipkart-seller style inventory management, TF-IDF personalized attendee matchmaking, grounded communications outbox, feedback sentiment analysis, and verifiable PDF certificates with QR codes.

---

## 📁 Architecture & Folder Structure

```
AgenticLiner/
├── backend/
│   ├── api/                              # FastAPI Routers, RBAC dependencies & contracts
│   │   ├── auth_routes.py                # Login, signup, OTP verification, Google OAuth & settings
│   │   ├── event_routes.py               # Event lifecycle, Dean approvals & planning submissions
│   │   ├── inventory_routes.py           # Catalog management (venues, equipment, speakers, CSV exports)
│   │   ├── pass_routes.py                # Student gate QR code verification & mobile scanning
│   │   └── main.py                       # Application entrypoint & consolidated API routing
│   ├── core/
│   │   ├── database/                     # SQLite connection pool, schema.sql & seeders
│   │   ├── safety/                       # Kavach invariant engine, transaction sandboxing & audit log
│   │   ├── planner/                      # Autopilot engine, call_llm provider switcher & deterministic tools
│   │   └── scheduler/                    # Google OR-Tools CP-SAT conflict-free timetable solver
│   ├── modules/
│   │   ├── module1_coplan/               # M1: Co-Planner (Brief to JSON, Adaptive Intake)
│   │   ├── module2_scheduling/           # M2: Intelligent Scheduling & Attendee Waitlist Manager
│   │   ├── module3_resource_opt/         # M3: Logistics Predictor & Inventory Optimizer
│   │   ├── module4_participant_xp/       # M4: Personalized Recommendations (TF-IDF Similarity)
│   │   ├── module5_comm_agent/           # M5: Grounded Q&A Assistant & Communication Outbox
│   │   ├── module6_feedback/             # M6: Automated Feedback Intelligence (Sentiment & Themes)
│   │   └── module7_analytics/            # M7: Executive Reports, Verifiable Certificates & QR Codes
│   └── services/                         # Reusable service layer (auth, passes, scheduling, analytics)
├── frontend/
│   ├── templates/                        # Server-rendered Jinja2 HTML templates (Bootstrap 5)
│   │   ├── autopilot.html                # Autopilot Agent Live Activity & Timeline Screen
│   │   ├── supervisor.html               # Dean / University Admin Control Panel
│   │   ├── organiser.html                # Club Organiser Hub & Event Workspace
│   │   ├── data_manager.html             # Master Datasets, CSV Uploads & Catalog Cart
│   │   ├── participant.html              # Student Digital Gate Pass & Personalized Recommendations
│   │   ├── schedule.html                 # 2D Grid Room-Slot Timetable & Hero Speaker Cancel Demo
│   │   ├── analytics.html                # Post-Event Feedback Analytics & Certificate Issuance
│   │   └── base.html                     # Responsive navbar, role-aware navigation & linear avatar
│   └── static/                           # Client-side JavaScript, assets & generated badges
├── eval/
│   ├── prompts/                          # 50-Prompt challenge benchmark suite
│   └── benchmark/                        # Independent checker scripts & metrics logger
├── tests/
│   ├── test_agent_mode.py                # Autopilot agent multi-turn tool calling & fallback tests
│   ├── test_autopilot_api.py             # End-to-end /api/autopilot/run endpoint integration tests
│   ├── test_auth.py                      # RBAC, session cookie & password security tests
│   ├── safety/test_kavach.py             # Kavach invariant checks & savepoint rollback tests
│   └── test_phase*.py                    # Phase-by-phase regression and feature test suites
├── docs/                                 # API specifications, User Manual & Diagrams
├── .env.example                          # Environment variable configuration template
├── requirements.txt                      # Python runtime and testing dependencies
└── README.md                             # Project documentation and run guide
```

---

## 🧩 The 7 Functional Modules

| Module | Core Functionality | Primary UI Route | Key API Endpoints |
|---|---|---|---|
| **Module 1: Co-Plan** | Event brief parser, entity extractor & adaptive intake | `/organiser/planner` | `POST /api/copilot/parse` |
| **Module 2: Scheduling** | OR-Tools CP-SAT conflict-free timetable, flyer generation & waitlist | `/schedule`, `/attendees`, `/flyer/{id}` | `POST /api/schedule/solve`, `POST /api/register` |
| **Module 3: Logistics** | Resource estimation, inventory cart & auto CSV exports | `/data-manager` | `GET /api/catalog`, `POST /api/inventory/venues` |
| **Module 4: Participant XP** | TF-IDF session recommendations & peer networking match | `/participant` | `GET /api/participant/{id}/recommendations` |
| **Module 5: Comm Agent** | Grounded Q&A assistant & transactional staged outbox | `/notices`, `/outbox` | `POST /api/assistant/ask`, `POST /api/outbox/stage` |
| **Module 6: Feedback** | Post-event sentiment scoring & thematic clustering | `/analytics` | `POST /api/feedback/submit` |
| **Module 7: Analytics** | Verifiable PDF certificates with QR codes & executive PDF report | `/analytics`, `/verify/{cert_id}` | `POST /api/certificates/generate`, `GET /verify/{cert_id}` |

---

## 🤖 Autopilot Engine: Agent Mode & Kavach Safety

The Autopilot engine operates in two coordinated modes with automatic fallback:

1. **Autonomous Agent Mode (`agent_mode.py`):**
   * Multi-turn tool loop where the model calls:
     - `find_free_venues`: Queries non-overlapping campus rooms matching capacity.
     - `check_equipment`: Checks stock availability across categories.
     - `recommend_from_history`: Synthesizes equipment needs from historical campus events.
     - `ask_user`: Clarifies missing facts (strictly capped at 2 questions).
     - `requisition`: Executes atomic room and resource allocation through Kavach.
   * **In-Code Hard Limits:** Max 8 conversation steps, hard budget caps, recipient limits, and instant blocking of destructive instructions (`cancel all`, `purge`, `delete all`).
   * **Multi-Provider Switcher (`call_llm.py`):** Leave `PROVIDER` unset/empty for offline mode (default), or set `PROVIDER=gemini|groq|ollama` with models from `GEMINI_MODEL`, `GROQ_MODEL`, or `OLLAMA_MODEL`. Unreplaced template placeholders (e.g., `your_gemini_api_key_here`) are treated as unset keys before making outbound requests. Features automatic exponential backoff on HTTP 429/503.

2. **Offline Deterministic Pipeline (`agent.py`, `AutopilotAgent`):**
   * When `PROVIDER` is unset or empty (the default offline configuration), the API routes Autopilot requests to `AutopilotAgent` (`mode: fixed`). When an enabled external LLM provider is unavailable or rate-limited, it falls back automatically (`mode: fixed_fallback`). There is no standalone CLI entry point for the fixed pipeline.

3. **Voice & Natural Language Intake (Pillar 1 - Web Speech STT/TTS & Entity Engine):** *(Browser Web Speech STT/TTS is not verified offline)*
   * **Hands-Free Speech-to-Text (STT):** Organisers can click the interactive 🎙️ mic button or speak in English, Hindi, or Hinglish (e.g., *"Kal shaam ko 4 baje 80 bacho ke liye robotics workshop book kardo"*). Interim speech results stream live into the prompt box.
   * **Relative Datetime & Entity Engine (`natural_intake.py`):** Translates colloquial expressions (*"tomorrow"*, *"this Friday evening"*, *"parso"*, *"18:00:00"*) to exact ISO timestamps and categorizes event types using combined regex patterns and relative datetime heuristic parsing.
   * **Proactive Clarifying Counter-Questions:** Missing critical fields (dates, scale) trigger conversational counter-questions before attempting venue lock.
   * **Text-to-Speech (TTS) Voice Feedback:** Speaks out confirmations and status updates via native browser SpeechSynthesis (with audio ON/MUTE toggle).

4. **Conversational Multi-Turn Dialogue & Loop Circuit Breaker (Pillar 2 - Dialogue Engine):**
   * **Stateful Dialogue Sessions (`dialogue_engine.py`):** Multi-turn clarification loop tracking accumulated entities, questions asked, and dialogue history via `/api/autopilot/session/start` and `/reply`.
   * **STRICT LOOP CIRCUIT BREAKER (`MAX_ASK_USER = 2`):** Prevents infinite clarifying loops or repetitive agent questioning. If parameters remain ambiguous after 2 turns, the agent stops questioning, fills campus defaults (`assumptions_made`), transitions the session to `ready_to_plan`, and opens the Pre-Commit Confirmation Card (`#preCommitConfirmationCard` via `POST /api/autopilot/draft`) for user approval before `POST /api/autopilot/confirm`.
   * **Interactive Dialogue Card & Quick-Reply Chips (`autopilot.html`):** Renders interactive chat bubbles with turn badges (*"Turn 1 of 2"*), 1-click quick-reply chips (*"This Friday 10 AM"*, *"Tomorrow 5 PM"*, *"100 Students"*), inline microphone for spoken replies, and a 1-click campus defaults skip button.

5. **Organiser Memory & Persistent Preference Store (Pillar 3 - Memory Engine):**
   * **Persistent Habit Retention (`memory_store.py` & `memory_engine.py`):** Retains preferred venues, standard logistics packages, preferred days/time slots, and rolling turnout metrics in SQLite `agent_memories`.
   * **Intake & Dialogue Enrichment:** Incomplete or ambiguous prompts automatically recall the organiser's typical batch size and favourite gear, eliminating redundant counter-questions and personalizing quick-reply suggestion chips.
   * **Privacy & User Control:** Strict per-organiser isolation with `GET /api/autopilot/memory`, `POST /api/autopilot/memory/note`, and `POST /api/autopilot/memory/reset` endpoints, alongside an interactive memory badge and inspection modal on `autopilot.html`.

6. **Netflix / Flipkart-Style Historical Recommendation Engine (Pillar 4 - Recommendation Engine):**
   * **Netflix Past Blueprint Matching (`recommendation_engine.py`):** Mines `historical_events` for past successful campus events matching format and scale, computing multidimensional vector distance, match percentage badges (80%–98%), and student satisfaction ratings (4.5★–4.9★).
   * **Flipkart Frequently Booked Together (FBT):** Market Basket association matrix computing conditional item probabilities with social proof tags (*"Booked by 95% of campus hackathon organisers"*), dynamic headcount scaling, and duplicate deduction.
   * **Curated Turnkey Logistics Bundles:** 1-click curated kits ("Hackathon Developer & Power Pack", "Cultural Stage & Audio Gala Pack", "Executive Keynote Kit", "Refreshment Pack") with budget validation against Kavach limits (`fits_budget: bool`).
   * **Conversational Dialogue & Natural Speech Integration:** Proactively surfaces bundles during clarification questions and detects natural language or voice requests (*"Please add the hackathon power bundle"*), merging resources into the brief.
   * **Interactive Autopilot UI (`autopilot.html`):** Renders `#recommendationSection` with Netflix blueprint match banners, match % badges, 1-click bundle cards (`[ + Add Bundle to Event ]`), and individual accessory carousels.

7. **Pre-Commit Interactive Confirmation Card & Voice Review (Pillar 5):** *(Browser voice synthesis and barge-in are not verified offline)*
   * **Semantic Full-Duplex Barge-In (`voice_engine.js`):** When the user speaks, active agent speech synthesis immediately aborts (`speechSynthesis.cancel()`), allowing natural, unhindered conversational interruptions.
   * **Fast-Path Micro-Intent Recognition (`fast_intent.py`):** Sub-10ms deterministic regex & phonetic classifier recognizing English, Hindi, and Hinglish affirmations (*"haan"*, *"ha"*, *"kar do"*, *"lock karo"*, *"yes"*, *"confirm"*), cancellations, and parameter deltas without high-latency LLM roundtrips.
   * **Speculative Background Draft Engine (`confirmation_engine.py`):** Pre-computes venue availability, equipment costs, and Dean approvals in memory before commit (0 database mutations until explicit confirmation).
   * **ChatGPT-Style Interactive Voice Orb & Card UI (`autopilot.html`):** Renders fluid animated neon sphere with 5 reactive physical states (`idle`, `listening`, `thinking`, `speaking`, `confirmed`) alongside itemized logistics tables and Dean sign-off warnings.

8. **Autonomous Multi-Stakeholder Notification & Outbox Dispatch (Pillar 6):**
   * **Tripartite Audience Dispatch (`notification_engine.py`):** Generates customized contextual notifications for all three campus constituencies in the step immediately following a confirmed booking:
     - **University Dean / Supervisor (`admin@galgotias.edu`):** Executive briefing on venue, scale, and budget with approval call-to-action (`[Action Required: Dean Approval]`).
     - **Event Manager / Organiser (`organiser@galgotias.edu`):** Itemized booking receipt, equipment pickup checklist, and direct timetable link (`/schedule`).
     - **Registered Students / Attendees:** Campus event invitation with dynamic Digital QR Gate Pass verification links (`/participant?event_id=...`).
   * **Direct Outbox Recording & Audit Trail:** After booking commit, `notification_engine.py` inserts stakeholder notices directly into SQLite `outbox` with `status='sent'` and logs `STAKEHOLDER_BROADCAST` in `audit_log`. If a requisition rolls back, the notification step is skipped and 0 notice rows are inserted.
   * **Production SMTP Bridge (`email_service.py`):** Supports email transmission via Google App Passwords / campus SMTP servers when configured *(not verified offline)*.
   * **Live UI Outbox Feed (`autopilot.html`):** Renders `#summaryStakeholdersBox` showing dispatch timestamps, recipient emails, and delivery status badges alongside spoken audio confirmation.

9. **Kavach Transaction Sandboxing (`kavach.py`):**
   * Uses SQLite savepoints (`SAVEPOINT sp_...`) to isolate all changes during a planning or confirmation run.
   * Enforces runtime campus invariants on bookings: valid time windows (`end > start`), no room overlaps, room capacity compliance, equipment stock availability, budget compliance, notification recipient limits, and agent blast-radius caps. *(A `verify_speaker_clash` helper exists in `kavach.py`, but runtime booking routes do not invoke it.)*
   * Within `tool_requisition_campus_resources`, a confirmation row is inserted with `status='held'` inside the savepoint so any invariant failure rolls back all state (leaving 0 notification rows) and logs the rejection in `audit_log`.

---

## 🔐 Role-Based Access Control (RBAC) & Seed Accounts

All operational routes enforce server-side session checks via signed cookies. The database seeder creates standard accounts with bcrypt-hashed passwords:

| Role | Email Address | Landing Dashboard | Primary Capabilities |
|---|---|---|---|
| **Supervisor (University Dean)** | `admin@galgotias.edu` | `/supervisor` | Approve/reject events, inspect audit logs, system-wide analytics & administrative resets |
| **Organiser (Club Host)** | `organiser@galgotias.edu` | `/organiser` | Autopilot planning, resource requisition cart, schedule generation, attendee roster & broadcasts |
| **Data Manager** | `datamanager@galgotias.edu` | `/data-manager` | Add/delete campus halls, equipment, speakers, upload photos, download master CSV exports |
| **Participant (Student)** | `student@galgotias.edu` | `/participant` | Event registration, personalized agenda, digital QR gate pass & feedback submission |

---

## ⚡ Team Quickstart & Setup Guide

### 1. Prerequisites
- Python 3.10, 3.11, 3.12, or 3.13
- Git

### 2. Clone & Environment Setup

**Windows (PowerShell):**
```powershell
# 1. Clone repository and navigate to root
git clone https://github.com/open-himanshu/AgenticLiner.git
cd AgenticLiner

# 2. Create and activate a clean virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install all required dependencies (python -m pip avoids Windows launcher blocks)
python -m pip install -r requirements.txt

# 4. Copy the environment template (configured for offline mode by default)
copy .env.example .env
```

**macOS / Linux (`bash` / `zsh`):**
```bash
# 1. Clone repository and navigate to root
git clone https://github.com/open-himanshu/AgenticLiner.git
cd AgenticLiner

# 2. Create and activate a clean virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install all required dependencies
python -m pip install -r requirements.txt

# 4. Copy the environment template (configured for offline mode by default)
cp .env.example .env
```

### 3. Configure `.env` (Offline Mode Is Default)
A fresh copy of `.env.example` runs in **offline mode** out of the box (`PROVIDER=` empty and no API keys required): Autopilot uses the deterministic fixed pipeline (`mode: fixed`) and Participant Q&A uses `rules_fallback` with 0 outbound network calls. Only fill in provider credentials if you want to enable live cloud/local LLM calls:
```ini
# Role passwords for initial seeding (leave empty for random generated tokens or use defaults)
SUPERVISOR_PASSWORD=your_secure_supervisor_password
ORGANISER_PASSWORD=your_secure_organiser_password
DATA_MANAGER_PASSWORD=your_secure_datamgr_password
PARTICIPANT_PASSWORD=your_secure_student_password

# Leave PROVIDER empty for offline mode, or set: gemini | groq | ollama
PROVIDER=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite

# Groq (optional alternative cloud provider)
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# Ollama (optional local offline provider)
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_HOST=http://localhost:11434
```

### 4. Initialize Database & Seed Accounts

> **Important:** Running `init_db` without `--seed-demo` creates empty tables in a clean zero-state (where Autopilot will stop at `find_free_venues` because no venues exist). Pass `--seed-demo` to load the demo campus venues, equipment, historical events, and speakers.

**Windows (PowerShell) & macOS / Linux (inside activated `.venv`):**
```bash
# Initialize SQLite tables & load demo campus venues, resources, and speakers
python -m backend.core.database.init_db --seed-demo

# Seed role accounts with hashed passwords
python backend/services/seed_users.py
```

### 5. Start the Web Server
**Windows (PowerShell) & macOS / Linux:**
```bash
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload
```
*(Or run `python run.py`, which launches the same uvicorn server on `127.0.0.1:8000`.)*  
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## 🎨 Frontend & UI Developer Guide

- **Templates:** Stored in `frontend/templates/`. Uses Jinja2 inheritance with `base.html`.
- **Styling:** Bootstrap 5.3 + Bootstrap Icons (`bi-*`).
- **Autopilot UI (`frontend/templates/autopilot.html`):**
  - `#agentBudget` exists in the form inside a hidden container (`d-none`) and defaults to `100000` for university logistics mode.
  - `#executionMetadata` displays execution details after a run:
    - **Mode:** `agent`, `fixed`, or `fixed_fallback`
    - **Provider & Model:** e.g., `gemini` / `gemini-3.1-flash-lite` (when an LLM provider is enabled)
    - **Tokens Used:** Total, prompt, and completion token metrics
    - **Fallback Reason:** Explains why fallback occurred if the provider failed
- **Adding / Modifying Screens:** Keep templates responsive, use Bootstrap utility classes, and ensure form submissions include proper role authentication or CSRF tokens where applicable.

---

## 🧪 Testing & Quality Assurance

All tests run offline without making external network or LLM API calls (using deterministic mocked callers and isolated temporary SQLite databases):

```bash
# Run the entire test suite (305 tests, offline SQLite isolation)
python -m pytest -q

# Run specific functional test suites
python -m pytest tests/test_agent_mode.py -q          # Autopilot Agent tool loop & fallback tests
python -m pytest tests/test_autopilot_api.py -q       # Autopilot API endpoint integration tests
python -m pytest tests/test_auth.py -q                # Authentication, sessions & RBAC tests
python -m pytest tests/safety/test_kavach.py -q       # Kavach invariant transaction tests
```

**Test console (dev only):** Set `TEST_CONSOLE=1` on localhost and sign in at `/dev/login` with default dev credentials `admin` / `admin` (`TEST_ADMIN_USER` / `TEST_ADMIN_PASSWORD`) to switch roles at `/dev`; keep `TEST_CONSOLE` unset or `0` outside local dev.
