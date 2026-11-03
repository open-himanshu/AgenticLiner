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
   * **Multi-Provider Switcher (`call_llm.py`):** Select provider via `PROVIDER=gemini|groq|ollama` with dynamic models from `GEMINI_MODEL`, `GROQ_MODEL`, or `OLLAMA_MODEL`. Features automatic exponential backoff on HTTP 429/503.

2. **Fixed Pipeline Fallback (`agent.py`):**
   * If the configured LLM provider is unavailable or rate-limited, the system seamlessly falls back to the deterministic pipeline (`mode: fixed_fallback`), guaranteeing zero downtime during evaluations.

3. **Voice & Natural Language Intake (Pillar 1 - Web Speech STT/TTS & Entity Engine):**
   * **Hands-Free Speech-to-Text (STT):** Organisers can click the interactive 🎙️ mic button or speak in English, Hindi, or Hinglish (e.g., *"Kal shaam ko 4 baje 80 bacho ke liye robotics workshop book kardo"*). Interim speech results stream live into the prompt box.
   * **Relative Datetime & Entity Engine (`natural_intake.py`):** Translates colloquial expressions (*"tomorrow"*, *"this Friday evening"*, *"parso"*, *"18:00:00"*) to exact ISO timestamps and categorizes event types without rigid regexes.
   * **Proactive Clarifying Counter-Questions:** Missing critical fields (dates, scale) trigger conversational counter-questions before attempting venue lock.
   * **Text-to-Speech (TTS) Voice Feedback:** Speaks out confirmations and status updates via native browser SpeechSynthesis (with audio ON/MUTE toggle).

4. **Conversational Multi-Turn Dialogue & Loop Circuit Breaker (Pillar 2 - Dialogue Engine):**
   * **Stateful Dialogue Sessions (`dialogue_engine.py`):** Multi-turn clarification loop tracking accumulated entities, questions asked, and dialogue history via `/api/autopilot/session/start` and `/reply`.
   * **STRICT LOOP CIRCUIT BREAKER (`MAX_ASK_USER = 2`):** Prevents infinite clarifying loops or repetitive agent questioning. If parameters remain ambiguous after 2 turns, the agent automatically terminates questioning, fills sensible Galgotias campus defaults (upcoming Friday 10:00 AM, 100 headcount, standard logistics package), logs assumptions in the activity timeline, and commits directly to venue booking.
   * **Interactive Dialogue Card & Quick-Reply Chips (`autopilot.html`):** Renders interactive chat bubbles with turn badges (*"Turn 1 of 2"*), 1-click quick-reply chips (*"This Friday 10 AM"*, *"Tomorrow 5 PM"*, *"100 Students"*), inline microphone for spoken replies, and a 1-click campus defaults skip button.

5. **Organiser Memory & Persistent Preference Store (Pillar 3 - Memory Engine):**
   * **Persistent Habit Retention (`memory_store.py` & `memory_engine.py`):** Retains preferred venues, standard logistics packages, preferred days/time slots, and rolling turnout metrics in SQLite `agent_memories`.
   * **Intake & Dialogue Enrichment:** Incomplete or ambiguous prompts automatically recall the organiser's typical batch size and favourite gear, eliminating redundant counter-questions and personalizing quick-reply suggestion chips.
   * **Privacy & User Control:** Strict per-organiser isolation with `GET /api/autopilot/memory` and `POST /reset` endpoints, alongside an interactive memory badge and inspection modal on `autopilot.html`.

6. **Kavach Transaction Sandboxing (`kavach.py`):**
   * Uses SQLite savepoints (`SAVEPOINT sp_...`) to isolate all changes during a planning run.
   * Enforces 6 campus invariants: No room overlaps, capacity compliance, speaker simultaneity, stock availability, budget compliance, and notification recipient limits.
   * Staged outbox notices are held until successful commit (`status = 'held' -> 'sent'`). If an invariant fails, state is atomically rolled back to the savepoint and logged in `audit_log`.

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

### 2. Environment Setup (Windows PowerShell)
```powershell
# 1. Clone repository and navigate to root
cd c:\PROJECTS\AgenticLiner

# 2. Create and activate a clean virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install all required dependencies
pip install -r requirements.txt

# 4. Create your local environment configuration
copy .env.example .env
```

### 3. Configure `.env`
Edit your `.env` file to set your preferred provider credentials and test passwords:
```ini
# Role passwords for seeding
SUPERVISOR_PASSWORD=Admin@Galgotias2026
ORGANISER_PASSWORD=Organiser@Galgotias2026
DATA_MANAGER_PASSWORD=DataMgr@Galgotias2026
PARTICIPANT_PASSWORD=Student@Galgotias2026

# Provider selection: gemini, groq, or ollama
PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Groq (alternative provider)
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Ollama (local offline provider)
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_HOST=http://localhost:11434
```

### 4. Initialize Database & Seed Accounts
```powershell
# Initialize SQLite tables & seed initial campus data (rooms, resources, speakers)
python -m backend.core.database.init_db

# Seed role accounts with hashed passwords
python backend/services/seed_users.py
```

### 5. Start the Web Server
Easiest command (recommended):
```powershell
python run.py
```
Or directly via uvicorn:
```powershell
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## 🎨 Frontend & UI Developer Guide

- **Templates:** Stored in `frontend/templates/`. Uses Jinja2 inheritance with `base.html`.
- **Styling:** Bootstrap 5.3 + Bootstrap Icons (`bi-*`).
- **Autopilot UI (`frontend/templates/autopilot.html`):**
  - Includes a dynamic budget input box (`#agentBudget`).
  - An `#executionMetadata` card displays execution details:
    - **Mode:** `agent` or `fixed_fallback`
    - **Provider & Model:** e.g., `gemini` / `gemini-2.5-flash`
    - **Tokens Used:** Total, prompt, and completion token metrics
    - **Fallback Reason:** Explains why fallback occurred if the provider failed
- **Adding / Modifying Screens:** Keep templates responsive, use Bootstrap utility classes, and ensure form submissions include proper role authentication or CSRF tokens where applicable.

---

## 🧪 Testing & Quality Assurance

All tests run completely offline without making external network or LLM API calls (using deterministic fake callers and isolated temporary SQLite databases):

```powershell
# Run the entire test suite
pytest -q

# Run specific functional test suites
pytest tests/test_agent_mode.py -q          # Autopilot Agent tool loop & fallback tests
pytest tests/test_autopilot_api.py -q       # Autopilot API endpoint integration tests
pytest tests/test_auth.py -q                # Authentication, sessions & RBAC tests
pytest tests/safety/test_kavach.py -q       # Kavach invariant transaction tests
```
