# AgenticLiner
> **Event planning and management platform with safety checks and an optional agent mode**
> *SparkX 3.0 International Innovation Challenge — Challenge #1*

---

## 📁 Project Architecture & Folder Organization

```
AgenticLiner/
├── backend/
│   ├── api/                              # FastAPI Routers & Pydantic Request/Response contracts
│   ├── core/
│   │   ├── database/                     # SQLite connection, schema definition & migrations
│   │   ├── safety/                       # Kavach: Invariant checker, savepoints, rollback, outbox
│   │   ├── planner/                      # LLM loop, Gemini function calling, Autopilot agent
│   │   └── scheduler/                    # Google OR-Tools CP-SAT scheduling model
│   ├── modules/
│   │   ├── module1_coplan/               # M1: Event Planning Copilot (rule-based baseline parsing and intake)
│   │   ├── module2_scheduling/           # M2: Intelligent Scheduling, Flyer & Registration Form
│   │   ├── module3_resource_opt/         # M3: Ridge regression and rule-based baseline resource estimates
│   │   ├── module4_participant_xp/       # M4: Personalized Recommendations (TF-IDF Similarity)
│   │   ├── module5_comm_agent/           # M5: Rule-based baseline Q&A and notification workflows
│   │   ├── module6_feedback/             # M6: Rule-based baseline sentiment and theme classification
│   │   └── module7_analytics/            # M7: Event analytics, certificate lookup and executive PDF
│   └── data/
│       └── synthetic/                    # Synthetic generators (past events, venues, inventory, students)
├── frontend/
│   ├── templates/                        # Server-rendered Jinja2 HTML pages (Bootstrap 5)
│   └── static/
│       └── js/                           # Browser-side interface scripts
├── eval/
│   ├── prompts/                          # 50-Prompt test suite (Clean, Ambiguous, Conflict, Destructive)
│   └── benchmark/                        # Independent checker scripts & metrics logger
├── tests/
│   ├── unit/                             # Unit tests for modules and algorithms
│   ├── integration/                      # End-to-end API pipeline tests
│   └── safety/                           # Kavach safety layer, savepoint & invariant tests
├── docs/                                 # API specifications, User Manual & Architectural diagrams
├── .env.example                          # Environment configuration template
├── requirements.txt                      # Project dependencies
└── README.md                             # Project overview and run guide
```

---

## Role-Based Access Control (RBAC) & Seeded Accounts

The application includes role-based access checks. The seed script (`python backend/services/seed_users.py`) creates up to one account per role and hashes passwords with bcrypt:

| Role | Email Address | Landing Dashboard | Authorized Access |
|---|---|---|---|
| **Supervisor (University Admin)** | `admin@galgotias.edu` | `/supervisor` | Campus event approvals, master calendar, resource limits, audit logs, analytics |
| **Organiser (Club Host)** | `organiser@galgotias.edu` | `/organiser` | Event planning, catalog cart, OR-Tools timetable, attendee roster, outbox broadcasts, rule-based baseline assistant |
| **Data Manager** | `datamanager@galgotias.edu` | `/data-manager` | CSV uploads & template downloads (venues, equipment, speakers, participants, past events) |
| **Participant (Student)** | `student@galgotias.edu` | `/participant` | Event registration, interest-based agenda recommendations, QR check-in, feedback submission |

Set `SUPERVISOR_PASSWORD`, `ORGANISER_PASSWORD`, `DATA_MANAGER_PASSWORD`, and `PARTICIPANT_PASSWORD` in your environment before seeding. When these variables are absent, the seed script generates credentials and writes them to its output; treat that output as sensitive and do not rely on generated credentials outside local development.

## Quickstart & Run Instructions

```bash
# 1. Create and activate a virtual environment (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies before running project commands
pip install -r requirements.txt

# 3. Configure the environment
copy .env.example .env
# Configure provider credentials and the role password variables in your environment as needed.

# 4. Initialize the database schema
python -m backend.core.database.init_db

# 5. Seed role accounts after database initialization
python backend/services/seed_users.py

# 6. Run the authentication tests (optional)
pytest tests/test_auth.py

# 7. Start the web server
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. Unauthenticated requests automatically redirect to `/login`.

Pytest assigns each test a separate temporary SQLite database through `DATABASE_PATH`;
the benchmark runners also use temporary databases and do not modify the application database. The prompt benchmark uses a scripted provider unless explicitly configured to run with a real provider.
