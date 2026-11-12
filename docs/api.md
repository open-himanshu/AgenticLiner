# AgenticLiner API Contract Specification (v2.0)
> **SparkX 3.0 Innovation Challenge — Challenge #1 (Galgotias University)**

---

## 1. Overview
The AgenticLiner backend exposes both REST API endpoints and interactive server-rendered web interfaces. Event planning, supervisor approval/rejection, schedule-change notices, and outbox release are sandboxed and monitored by the **Kavach Safety Engine**.

API endpoints enforce server-side session checks and Role-Based Access Control (RBAC):
- **Organiser (`organiser`) & Supervisor (`supervisor`):** Autonomous planning, schedule generation, resource requisition, attendee rosters, and staged outbox dispatches.
- **Data Manager (`data_manager`):** Campus catalog maintenance (rooms, equipment, speakers) and master CSV exports.
- **Participant (`participant`):** Personal session recommendations, digital gate pass, check-in, and feedback submission.
- **Public:** Certificate verification (`GET /verify/{cert_id}`) and OAuth login callbacks.

Certificate QR codes and the analytics-page "Verify QR" link use `GET /verify/{cert_id}`. Set `PUBLIC_BASE_URL` to the externally reachable application origin (e.g., `https://events.example.edu`); when unset, certificate generation uses the incoming request origin.

All planner actions accept a numeric `budget` that is recorded on the event; cost estimation is not implemented for Autopilot booking rows (`estimated_cost` defaults to `0.0`), budget limits are not enforced automatically, and there is no payment step or wallet table. Kavach limits outbox recipients using `KAVACH_MAX_RECIPIENTS` (default `500`), and planner operations that fail invariants after retries queue into the supervisor-only `GET /api/human-review` response.

---

## 2. Core Endpoints

### 2.1 Autopilot Agent Execution
- **Endpoint:** `POST /api/autopilot/run`
- **RBAC Role:** `organiser`, `supervisor`
- **Description:** Runs autonomous event planning through multi-turn tool calling with live timeline tracing and deterministic fallback.
- **Request Body:**
  ```json
  {
    "prompt": "Organize a campus coding hackathon for 150 students with budget 45000",
    "budget": 45000.0,
    "date": "2026-11-25",
    "start_time": "09:00:00",
    "end_time": "17:00:00"
  }
  ```
- **Response (Agent Mode):**
  ```json
  {
    "success": true,
    "mode": "agent",
    "provider": "gemini",
    "model": "gemini-3.1-flash-lite",
    "tokens_used": {
      "prompt_tokens": 120,
      "completion_tokens": 45,
      "total_tokens": 165
    },
    "event_id": "ev_auto_b88b2a12",
    "event_name": "Campus Coding Hackathon",
    "venue": "Main Auditorium A (C-Block)",
    "total_cost": 29800.0,
    "timeline": [
      {
        "step": 1,
        "tool": "find_free_venues",
        "status": "completed",
        "summary": "Discovered available campus halls. Allocated 'Main Auditorium A'."
      },
      {
        "step": 2,
        "tool": "requisition",
        "status": "committed",
        "summary": "Kavach Safety checks passed. Requisitioned venue and equipment."
      }
    ],
    "fallback_reason": null
  }
  ```

---

### 2.2 Conversational Dialogue & Confirmation (Pillars 2 & 5)
- **Start Session:** `POST /api/autopilot/session/start`
  - Body: `{"prompt": "Need a hall for workshop"}`
  - Returns: Session state, extracted parameters, pending clarifying questions, and quick-reply suggestion chips.
- **Reply to Agent:** `POST /api/autopilot/session/reply`
  - Body: `{"session_id": "...", "reply": "Tomorrow 10 AM, 50 students"}`
  - Enforces loop circuit breaker (`MAX_ASK_USER = 2`).
- **Speculative Draft:** `POST /api/autopilot/draft`
  - Returns pre-commit confirmation card with itemized costs, venue lock, and Dean approval flags without mutating SQLite.
- **Confirm & Commit:** `POST /api/autopilot/confirm`
  - Atomically commits the draft under Kavach savepoint protection.

---

### 2.3 Marketplace & Catalog
- **Endpoint:** `GET /api/catalog`
- **RBAC Role:** Any authenticated user
- **Description:** Returns campus resources (venues, equipment, food, volunteers, transport).
- **Response:**
  ```json
  {
    "catalog": [
      {
        "id": "res_mic_cordless",
        "category": "equipment",
        "name": "Wireless Handheld Mic Set (Pair)",
        "price": 400.0,
        "stock": 10,
        "unit": "pair"
      }
    ]
  }
  ```

---

### 2.4 Intelligent Timetable Constraint Solver (OR-Tools)
- **Endpoint:** `POST /api/schedule/solve`
- **RBAC Role:** `organiser`, `supervisor`
- **Description:** Formulates and solves room conflict, speaker availability windows, and prerequisite dependency constraints using Google OR-Tools CP-SAT.
- **Response:**
  ```json
  {
    "success": true,
    "status": "OPTIMAL",
    "total_sessions_scheduled": 4,
    "schedule": [
      {
        "session_id": "sess_01",
        "session_title": "Opening Keynote & Welcome",
        "room_name": "Main Auditorium A (C-Block)",
        "slot_time": "09:30-11:00"
      }
    ]
  }
  ```

---

### 2.5 Personalized Participant Recommendations
- **Endpoint:** `GET /api/participant/{student_id}/recommendations`
- **RBAC Role:** `participant` (self-bound), `organiser`, `supervisor`
- **Description:** Calculates TF-IDF interest vector cosine similarities and filters clashing parallel agenda slots.

---

### 2.6 Grounded Event Assistant
- **Endpoint:** `POST /api/assistant/ask`
- **RBAC Role:** Any authenticated user
- **Description:** Grounded Q&A engine referencing official campus schedule, speaker, and venue records with strict off-topic boundaries.
- **Request Body:**
  ```json
  {
    "event_id": "ev_001",
    "query": "Where is the keynote taking place?"
  }
  ```
- **Response:**
  ```json
  {
    "found": true,
    "answer": "The Opening Keynote & Welcome is scheduled in Main Auditorium A (C-Block) from 09:30 AM to 11:00 AM.",
    "mode": "llm",
    "provider": "gemini"
  }
  ```

---

### 2.7 Feedback Intelligence & Thematic Clustering
- **Endpoint:** `POST /api/feedback/submit`
- **RBAC Role:** `participant`
- **Description:** Lexicon sentiment polarity scoring with 2-token negation lookback, Hinglish vocabulary, and thematic classification (Venue, Content, Hospitality, Organization).

---

### 2.8 Outbox Dispatches & Notifications (Pillar 6)
- **Endpoint:** `GET /api/autopilot/outbox/{event_id}`
- **RBAC Role:** `organiser`, `supervisor`
- **Description:** Returns all staged and dispatched stakeholder notices (Dean, Organiser, Students) from SQLite `outbox`.

---

### 2.9 Public Certificate Verification
- **Endpoint:** `GET /verify/{cert_id}`
- **RBAC Role:** Public (Unauthenticated)
- **Description:** Read-only certificate authenticity verification page accessed via dynamic QR code.
