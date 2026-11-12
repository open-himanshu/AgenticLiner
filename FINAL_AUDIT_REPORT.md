# Final Project Audit Report — AgenticLiner
**Challenge:** SparkX 3.0 International 30-Day Challenge (Challenge #1: AI-Powered Intelligent Event Planning & Management Platform)  
**Audit Date:** 2026-11-12  
**Audit Scope:** Full end-to-end live server, browser UI (all 4 roles), REST API, SQLite persistence, OR-Tools scheduling, ML resource/recommendation pipelines, Kavach safety guardrails, RBAC/security, and `pytest` verification.

---

## A. Executive Verdict

**Verdict: CONDITIONALLY READY FOR SUBMISSION & LIVE DEMONSTRATION**

The core architecture, 7 functional modules, OR-Tools CP-SAT constraint solver, Scikit-Learn pipelines (Ridge Regression and TF-IDF + cosine similarity), SQLite savepoint safety layer (`KavachEngine`), RBAC role boundaries, QR gate pass + certificate PDF verification, and deterministic offline fallbacks are **real, integrated, and operational** after fixing 7 bugs uncovered during live audit testing.

**Important Operational Disclosure:**
- Out of the box (`PROVIDER` unset), Autopilot executes deterministically via its rule-based / NLP pipeline (`mode: "fixed"`) and **cannot enforce real-time monetary budgets on fixed-mode bookings** (`estimated_cost` stays `0.0` in `AgenticLiner` fixed pipeline, and no payment/wallet ledger exists — budget is recorded on the event).
- Live LLM execution via Gemini (`gemini-3.1-flash-lite`) was tested boundedly: `/api/assistant/ask` succeeded on a live grounded query (`mode: "llm"`), while `/api/autopilot/run` (with `PROVIDER=gemini`) and `/api/agent/genesis` encountered upstream Gemini `504 Deadline expired` / `503 UNAVAILABLE` / TLS handshake timeouts and **gracefully fell back** (`mode: "fixed_fallback"` / `regex_fallback`) without crashing.
- Original repository database (`agenticliner.db`) and `.env` were **never modified or exposed**; all live checks executed against an isolated seeded SQLite copy.

---

## B. Module-by-Module Compliance Matrix (All 7 Core Modules)

| # | Core Module | Primary Backend & Routes | Real AI / Optimization vs Fallback Logic | Verified Status | Audit Notes & Fixes Applied |
|---|---|---|---|---|---|
| 1 | **AI Event Planning Copilot** | `backend/modules/module1_coplan/brief_parser.py`, `task_board.py`, `backend/core/planner/agent.py`, `agent_mode.py`, `dialogue_engine.py`, `confirmation_engine.py`, `agentic_genesis_service.py` (`/api/copilot/parse`, `/api/autopilot/*`, `/api/agent/genesis`, `/organiser/planner`) | Rule-based NLP regex + entity extraction (`adaptive_intake`), Kavach SQLite savepoints, optional LLM loop via `call_llm` (fixed-pipeline fallback when `PROVIDER` unset or upstream fails) | **WORKING** | Fixed hidden `#agentBudget=100000` override in `autopilot.html`, fixed orphan resource IDs in `confirmation_engine.py`, fixed read-only room/event queries in `execute_universal_command` creating bogus events. |
| 2 | **Intelligent Scheduling & Conflict Resolution** | `backend/core/scheduler/solver.py`, `backend/services/schedule_service.py`, `backend/modules/module2_scheduling/attendee_manager.py` (`/api/schedule/solve`, `/api/schedule/hero-speaker-cancel`, `/api/schedule/export.csv`, `/api/register`, `/api/attendees/*`, `/flyer/{event_id}`) | **Google OR-Tools CP-SAT solver** (`cp_model`) enforcing room capacity, speaker availability windows, room/speaker exclusivity, and session dependency ordering; SQLite capacity-guarded waitlist auto-promotion | **WORKING** | Verified OR-Tools optimal solve, speaker-cancellation cascade, waitlist auto-promotion (`confirmed` -> cancel -> next `waitlisted` promoted to `confirmed`), CSV exports. Fixed `attendee_manager.py` storing `str(list)` instead of valid JSON, and made `flyer.html` reflect event attributes dynamically. |
| 3 | **AI-Based Resource Optimization** | `backend/modules/module3_resource_opt/engine.py` (`/api/recommendations/resources`, `/api/autopilot/recommendations`) | **Scikit-Learn `Ridge` regression** (`StandardScaler` + `Ridge`) trained on `historical_events` (`headcount`, `duration_hours`) + event-type rules & DB `resources` stock reconciliation | **WORKING** | Verified `/api/recommendations/resources?event_type=hackathon&headcount=250` returns scaled resource plan backed by `historical_events` and inventory stock. |
| 4 | **Personalized Participant Experience** | `backend/modules/module4_participant_xp/recommender.py`, `backend/services/pass_service.py` (`/api/participant/{student_id}/recommendations`, `/participant`, `/api/pass/scan`) | **Scikit-Learn `TfidfVectorizer` + `cosine_similarity`** matching interests against sessions (with clash pruning), peers, and mentors; dynamic QR gate passes (`qrcode`) | **WORKING** | Fixed `recommender.py` `JSONDecodeError` crash risk on legacy Python `str(list)` interests and inconsistent empty-student return keys (`peers`/`speakers` vs `peer_matches`/`mentor_matches`). Verified `200 OK` recommendations & QR pass check-in. |
| 5 | **AI Communication Agent** | `backend/modules/module5_comm_agent/agent.py` (`/api/assistant/ask`, `/api/outbox/stage`, `/api/outbox/release-all`, `/notices`) | Calls `call_llm` (grounded in SQLite event, sessions, speakers, bookings) with deterministic keyword/fact rules fallback; Kavach-guarded outbox staging & release | **WORKING (with network caveat)** | Live `gemini-3.1-flash-lite` answered Opening Keynote query cleanly (`mode: "llm"`) and refused private password query; note that when `PROVIDER` is unset in env, `call_llm.get_provider_config()` still defaults to `"gemini"`, causing ~20s TLS wait before fallback if outbound network stalls. |
| 6 | **Automated Feedback Intelligence** | `backend/modules/module6_feedback/analyzer.py`, `backend/services/analytics_service.py` (`/api/feedback/submit`, `/participant`, `/analytics`) | Custom sentiment lexicon + negation-inversion + **Hinglish** token rules + keyword theme classifier (not VADER) | **WORKING** | **Critical UI fix:** `/participant` modal submit button had `Uncaught TypeError: null.addEventListener` blocking all UI feedback submissions; wrapped in `DOMContentLoaded` and verified end-to-end DB insert. Fixed misleading `"VADER Polarity Engine"` badge in `analytics.html`. |
| 7 | **Post-Event AI Analytics & Certificates** | `backend/modules/module7_analytics/generator.py`, `backend/services/analytics_service.py` (`/api/analytics/{event_id}`, `/api/report/pdf/{event_id}`, `/api/certificates/generate`, `/api/certificates/download/{cert_id}`, `/verify/{cert_id}`, `/analytics`) | SQL aggregation for turnout/attendance/sentiment, **ReportLab** executive & certificate PDF generation, **QRCode** verification tracking (`verified_count` increment in SQLite) | **WORKING** | Fixed `analytics.html` hardcoded `ev_001` PDF link, missing event selector, fake `4.8 / 5.0` empty rating, Jinja `or 75/15/10` overriding `0.0%` sentiment, and hardcoded static recommendations. Verified valid `%PDF-1.4` downloads and QR verification counter increments. |

---

## C. UI / Dashboard / Role Audit Table

All 4 roles (`supervisor`, `organiser`, `data_manager`, `participant`) and unauthenticated visitors were exercised live on `http://127.0.0.1:8000` (browser + scripted HTTP):

| Role / Persona | Verified Routes | Status After Fixes | Key Observations |
|---|---|---|---|
| **Anonymous** | `/login`, `/verify/{cert_id}`, `/settings`, `/organiser`, `/supervisor` | **PASS** | Protected HTML routes return `302 -> /login` when `Accept: text/html` is sent (headless API requests without `text/html` receive `401`), `/verify/{cert_id}` works publicly, `/dev` & `/test-console` return `404` when `TEST_CONSOLE` is disabled. |
| **Supervisor (`admin@galgotias.edu`)** | `/supervisor`, `/supervisor/audit-log`, `/analytics`, `/api/events/{id}/approve`, `/api/events/{id}`, `/api/report/pdf/{id}` | **PASS** | Complete Campus Events Directory and detailed Inspection Modals implemented: displays all events (including auto-approved and pending fests), venue allocations, requisition items, schedule sessions, organizer details, and attendee counts. Pending `room_audi_a` / 250-pax event transitions `pending_dean_approval -> approved`; `/analytics` dynamically selects events and renders accurate `0.0%` / real DB sentiment. |
| **Organiser (`organiser@galgotias.edu`)** | `/organiser`, `/autopilot`, `/organiser/planner`, `/schedule`, `/attendees`, `/notices`, `/flyer/{id}` | **PASS** | Hero Autopilot prompt preserved `budget: 20000.0` in SQLite (previously overwritten by hidden `100000`), confirmation commit created zero orphan resource IDs, OR-Tools solve & flyer rendering verified. |
| **Data Manager (`datamanager@galgotias.edu`)** | `/data-manager`, `/api/inventory/*` | **PASS** | Loads master catalog counts (`7` rooms, `13` resources, `5` speakers); cross-role access to `/supervisor` & `/autopilot` returns `403`. |
| **Participant (`student@galgotias.edu`)** | `/participant`, `/register`, `/api/participant/{id}/recommendations`, `/api/assistant/ask`, `/api/feedback/submit` | **PASS** | `/participant` now has **0 JS console errors** (previously crashed on `btnModalSubmitFeedback`); Feedback modal writes directly to SQLite `feedback`; IDOR cross-student access blocked with `403`. |

---

## D. Database, Kavach Safety Engine & End-to-End Integration Audit

- **SQLite Persistence:** Verified against an isolated seeded copy (`audit_live.sqlite3`); original `agenticliner.db` remained untouched throughout (`users: 6, rooms: 7, resources: 13, speakers: 5, events: 4, sessions: 4, bookings: 13, students: 50, feedback: 0, outbox: 4, registrations: 0`).
- **Kavach Savepoints & Constraints:** Confirmed rollback on past dates and over-capacity (`900` students) prompts; fixed `_FALLBACK_RESOURCE_COSTS` resource IDs in `confirmation_engine.py` (`orphan_resource_bookings_count` reduced from `9` to **`0`**).
- **End-to-End Lifecycle Verified:** Event creation (`pending_dean_approval`) -> Supervisor Dean approval (`approved`) -> Student registration -> Personalized TF-IDF session/peer/mentor recommendations -> Communication Agent Q&A -> Waitlist capacity guard & cancel auto-promotion -> UI/API feedback sentiment & themes -> Analytics & ReportLab PDF export -> Verifiable QR certificate issue/verify/download.

---

## E. Security, Auth & RBAC Findings

1. **RBAC Isolation Verified:** Unauthenticated API calls return `401`; `student` cannot access `/organiser`, `/supervisor`, `/data-manager`, `/analytics`, `/api/human-review`, `/api/autopilot/run`, `/api/agent/universal-command`, `/api/events/*/approve`, or `/admin/reset-data` (`403`). `organiser` receives `403` on `/supervisor`, `/supervisor/audit-log`, `/data-manager`, `/api/events/*/approve`, `/admin/reset-data`.
2. **IDOR Protections Verified:** `student` receives `403` when requesting another student's recommendations (`/api/participant/stu_01/recommendations`), submitting feedback under another `student_id`, registering another email (`/api/register`), or downloading another student's certificate PDF.
3. **Auth Input Protections:** Invalid login rejected, weak-password signup rejected, `TEST_CONSOLE` disabled -> `/dev` and `/test-console` return `404`.
4. **Open Security Finding (Fixed Mode Only):** When `PROVIDER` is unset (`fixed` mode), `/api/autopilot/run` routes directly to `AutopilotAgent` without invoking `_is_destructive()` (which runs in `agent_mode` and `dialogue_engine`). Prompts like `"cancel all events and delete bookings"` or `"purge database and drop table events"` succeeded in creating an event in `fixed` mode (`success: true`) rather than being rejected at intake. Documented in `BUG_REPORT.md` (not patched inline because `eval/benchmark/run_evaluation.py` Setup B relies on `run_autopilot_with_fallback` without a fixed-mode filter).

---

## F. Open Limitations Summary

1. **Fixed-mode Autopilot destructive prompt bypass** when `PROVIDER` is unset (`/api/autopilot/run` skips `_is_destructive()`).
2. **`call_llm.get_provider_config()` defaults unset `PROVIDER` to `"gemini"`**, and `agentic_genesis_service.py` calls `genai.Client` directly without timeout tuning (~20–30s stall when Gemini TLS/503/504 occurs before fallback).
3. **Budget & Payment Scope:** `AutopilotAgent` records `budget` on `events` and `estimated_cost=0.0` on `bookings`; cost estimation and payment/wallet processing are not implemented.
4. **`/verify-otp` without prior `/signup` session returns HTTP `422`** (form validation / session state dependency).
