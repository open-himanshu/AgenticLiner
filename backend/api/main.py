"""
AgenticLiner FastAPI Main Application (University Edition v2.1).
Complete End-to-End Implementation for all 7 Modules and 17 Screens of SparkX 3.0 Challenge #1.
"""

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

from fastapi import FastAPI, Request, HTTPException, Response, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from pathlib import Path
import os
import json
import uuid
import logging
import secrets

from backend.core.database.connection import get_connection, fetch_all, fetch_one
from backend.core.database.demo_people import HERO_SPEAKER
from backend.core.planner.agent_mode import run_autopilot_with_fallback
from backend.core.planner.natural_intake import (
    validate_prompt_safety,
    extract_event_entities_llm,
    assess_intake_completeness,
    ExtractedEventEntities,
)
from backend.core.planner.dialogue_engine import (
    get_or_create_session,
    get_session,
    reset_session,
    fuse_dialogue_reply,
    MAX_ASK_USER,
    AutopilotDialogueSession,
)
from backend.modules.module1_coplan.task_board import get_event_task_board
from backend.modules.module1_coplan.brief_parser import parse_event_brief, adaptive_intake
from backend.modules.module2_scheduling.attendee_manager import AttendeeManager
from backend.modules.module3_resource_opt.engine import ResourceOptimizer
from backend.modules.module4_participant_xp.recommender import ParticipantExperienceEngine
from backend.modules.module5_comm_agent.agent import CommunicationAgent
from backend.modules.module6_feedback.analyzer import FeedbackAnalyzer
from backend.modules.module7_analytics.generator import EventAnalyticsEngine
from backend.services.admin_service import reset_all_operational_data
from backend.api.auth_routes import router as auth_router, ROLE_DASHBOARDS
from backend.api.inventory_routes import router as inventory_router
from backend.api.event_routes import router as event_router
from backend.api.pass_routes import router as pass_router
from backend.services.pass_service import (
    get_or_create_student_profile,
    get_student_passes,
    get_personalized_recommendations_for_student
)
from backend.services.schedule_service import (
    solve_timetable,
    handle_hero_speaker_cancellation,
    export_schedule_csv
)
from backend.services.analytics_service import (
    get_analytics_dashboard_data,
    record_feedback,
    verify_certificate_by_id
)
from backend.services.agentic_genesis_service import (
    execute_autonomous_event_genesis,
    execute_universal_command
)
from backend.api.dependencies import require_role, get_session_user
from backend.core.safety.kavach import KavachEngine

app = FastAPI(title="AgenticLiner - Academic Event Platform", version="2.2.0")
logger = logging.getLogger(__name__)
kavach = KavachEngine()


def load_session_secret_key() -> str:
    secret_key = os.getenv("SECRET_KEY")
    if secret_key:
        return secret_key
    logger.warning(
        "SECRET_KEY is not configured; generated a random session secret. "
        "Sessions will not persist across server restarts."
    )
    return secrets.token_urlsafe(32)

# Setup Directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Session Middleware Configuration
SECRET_KEY = load_session_secret_key()
SESSION_COOKIE = os.getenv("SESSION_COOKIE_NAME", "agenticliner_session")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE,
    max_age=86400,
    same_site="lax",
    https_only=os.getenv("ALLOW_PUBLIC_TUNNEL") == "1"
)

# Include Authentication Router
app.include_router(auth_router)

# Include Inventory & Catalog Router (Seller-style Add/Export)
app.include_router(inventory_router)

# Include Event Workflow & Approvals Router (Phase 5)
app.include_router(event_router)

# Include Student Pass & QR Scanning Router
app.include_router(pass_router)

# Custom Exception Handlers for Strict RBAC & Unauthenticated Redirects
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    accept = request.headers.get("accept", "")
    if exc.status_code == 403:
        if "text/html" in accept:
            return templates.TemplateResponse(
                request=request,
                name="errors/403.html",
                context={"detail": exc.detail},
                status_code=403
            )
        return JSONResponse(status_code=403, content={"detail": exc.detail})
    elif exc.status_code in (401, 307):
        if "text/html" in accept:
            return RedirectResponse(url=f"/login?next={request.url.path}", status_code=status.HTTP_302_FOUND)
        return JSONResponse(status_code=401, content={"detail": exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# Core Engines
attendee_mgr = AttendeeManager()
resource_opt = ResourceOptimizer()
participant_xp = ParticipantExperienceEngine()
comm_agent = CommunicationAgent()
feedback_analyzer = FeedbackAnalyzer()
analytics_engine = EventAnalyticsEngine()

# --- Request Models ---
class ParseIntentRequest(BaseModel):
    prompt: str
    voice_mode: bool = False

class DialogueStartRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    voice_mode: bool = False

class DialogueReplyRequest(BaseModel):
    session_id: str
    reply: str
    voice_mode: bool = False

class DialogueResetRequest(BaseModel):
    session_id: str

class AutopilotRequest(BaseModel):
    prompt: str
    date: str = "2026-11-25"
    start_time: str = "09:00:00"
    end_time: str = "17:00:00"
    budget: float = Field(gt=0)

class StudentRegistrationRequest(BaseModel):
    event_id: str = "ev_001"
    name: str
    email: str
    department: str
    year: int
    interests: List[str]
    preferred_sessions: Optional[List[str]] = None

class StageAnnouncementRequest(BaseModel):
    event_id: str = "ev_001"
    recipient: str
    subject: str
    message: str
    type: str = "announcement"

class AskAssistantRequest(BaseModel):
    event_id: str
    query: str

class FeedbackSubmission(BaseModel):
    event_id: str
    student_id: Optional[str] = None
    rating: int
    comment: str

class CopilotParseRequest(BaseModel):
    brief: str

class CertificateGenerateRequest(BaseModel):
    student_id: str
    student_name: str
    event_id: str = "ev_001"
    event_name: str = "Galgotias Campus Innovation Hackathon"

class AgentGenesisRequest(BaseModel):
    prompt: str
    organizer_email: Optional[str] = "organiser@galgotias.edu"
    organizer_department: Optional[str] = "School of Computing Science"

class UniversalCommandRequest(BaseModel):
    command: str

# --- HTML Page Routes with Strict RBAC (Server-rendered Jinja2 UI) ---

@app.get("/", response_class=HTMLResponse)
async def root_gateway(request: Request):
    """Root Gateway: Redirects to role dashboard if authenticated, else /login."""
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    target = ROLE_DASHBOARDS.get(user.get("role"), "/login")
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)

@app.get("/supervisor", response_class=HTMLResponse)
async def supervisor_dashboard(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["supervisor"]))
):
    """Supervisor Dashboard: University Admin & Dean Authority"""
    pending_count = fetch_one("SELECT count(*) as count FROM events WHERE approval_status = 'pending_dean_approval'")["count"]
    active_count = fetch_one("SELECT count(*) as count FROM events WHERE approval_status = 'approved'")["count"]
    rooms_count = fetch_one("SELECT count(*) as count FROM rooms")["count"]
    resources_count = fetch_one("SELECT count(*) as count FROM resources")["count"]
    
    pending_events = fetch_all("""
        SELECT e.*, 
               (SELECT r.name FROM bookings b JOIN rooms r ON b.room_id = r.id WHERE b.event_id = e.id LIMIT 1) as venue_name,
               (SELECT count(*) FROM bookings b WHERE b.event_id = e.id AND b.resource_id IS NOT NULL) as req_count
        FROM events e 
        WHERE e.approval_status = 'pending_dean_approval' 
        ORDER BY e.created_at DESC LIMIT 10
    """)
    approved_events = fetch_all("""
        SELECT e.*, 
               (SELECT r.name FROM bookings b JOIN rooms r ON b.room_id = r.id WHERE b.event_id = e.id LIMIT 1) as venue_name
        FROM events e 
        WHERE e.approval_status = 'approved' 
        ORDER BY e.created_at DESC LIMIT 10
    """)

    return templates.TemplateResponse(
        request=request,
        name="supervisor.html",
        context={
            "user": user,
            "pending_count": pending_count,
            "active_count": active_count,
            "rooms_count": rooms_count,
            "resources_count": resources_count,
            "pending_events": pending_events,
            "approved_events": approved_events
        }
    )

@app.get("/supervisor/audit-log", response_class=HTMLResponse)
async def supervisor_audit_log(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["supervisor"]))
):
    """Supervisor View: Immutable System Audit Trail"""
    logs = fetch_all("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 100")
    return templates.TemplateResponse(
        request=request,
        name="supervisor.html",
        context={
            "user": user,
            "audit_logs": logs,
            "show_audit": True
        }
    )

@app.post("/admin/reset-data")
async def admin_reset_data(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["supervisor"]))
):
    """
    Supervisor Admin Action: Purges all business data and resets database to clean zero-state.
    Enforces confirmation and records an immutable audit log entry.
    """
    supervisor_email = user.get("email", "admin@galgotias.edu")
    result = reset_all_operational_data(supervisor_email)

    accept = request.headers.get("accept", "")
    if "text/html" in accept or request.headers.get("content-type") == "application/x-www-form-urlencoded":
        return RedirectResponse(url="/supervisor?reset_success=1", status_code=status.HTTP_302_FOUND)

    return JSONResponse(content=result)

@app.get("/organiser", response_class=HTMLResponse)
async def organiser_dashboard(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser"]))
):
    """Organiser Dashboard: Club Event Host Hub"""
    my_events_count = fetch_one("SELECT count(*) as count FROM events")["count"]
    total_reg = fetch_one("SELECT count(*) as count FROM registrations WHERE status = 'confirmed'")["count"]
    waitlisted = fetch_one("SELECT count(*) as count FROM registrations WHERE status = 'waitlisted'")["count"]
    outbox_count = fetch_one("SELECT count(*) as count FROM outbox WHERE status = 'held'")["count"]
    my_events = fetch_all("""
        SELECT e.*, 
               (SELECT r.name FROM bookings b JOIN rooms r ON b.room_id = r.id WHERE b.event_id = e.id LIMIT 1) as venue_name,
               (SELECT count(*) FROM registrations reg WHERE reg.event_id = e.id AND reg.status = 'confirmed') as confirmed_count
        FROM events e 
        ORDER BY e.created_at DESC LIMIT 10
    """)

    return templates.TemplateResponse(
        request=request,
        name="organiser.html",
        context={
            "user": user,
            "my_events_count": my_events_count,
            "total_registered": total_reg,
            "waitlisted_count": waitlisted,
            "outbox_count": outbox_count,
            "my_events": my_events
        }
    )

@app.get("/organiser/planner", response_class=HTMLResponse)
async def organiser_planner(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser"]))
):
    """Organiser Event Planning Copilot & Logistics Inventory Cart"""
    catalog = fetch_all("SELECT * FROM resources")
    rooms = fetch_all("SELECT * FROM rooms")
    events = fetch_all("SELECT * FROM events ORDER BY created_at DESC LIMIT 5")
    tasks = get_event_task_board("hackathon")
    return templates.TemplateResponse(
        request=request,
        name="planner.html",
        context={
            "user": user,
            "catalog": catalog,
            "rooms": rooms,
            "events": events,
            "tasks": tasks
        }
    )

@app.get("/data-manager", response_class=HTMLResponse)
async def data_manager_dashboard(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["data_manager"]))
):
    """Data Manager Dashboard: Master CSV Datasets & Campus Records"""
    venues_count = fetch_one("SELECT count(*) as count FROM rooms")["count"]
    equipment_count = fetch_one("SELECT count(*) as count FROM resources")["count"]
    speakers_count = fetch_one("SELECT count(*) as count FROM speakers")["count"]
    past_events_count = fetch_one("SELECT count(*) as count FROM historical_events")["count"]

    venues = fetch_all("SELECT * FROM rooms ORDER BY name")
    equipment = fetch_all("SELECT * FROM resources ORDER BY category, name")
    speakers = fetch_all("SELECT * FROM speakers ORDER BY name")
    past_events = fetch_all("SELECT * FROM historical_events")

    return templates.TemplateResponse(
        request=request,
        name="data_manager.html",
        context={
            "user": user,
            "venues_count": venues_count,
            "equipment_count": equipment_count,
            "speakers_count": speakers_count,
            "past_events_count": past_events_count,
            "venues": venues,
            "equipment": equipment,
            "speakers": speakers,
            "past_events": past_events
        }
    )

@app.get("/autopilot", response_class=HTMLResponse)
async def autopilot_page(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Hero Screen: Autopilot Agent Activity Panel (Live Timeline)"""
    return templates.TemplateResponse(
        request=request,
        name="autopilot.html",
        context={"user": user}
    )

@app.get("/schedule", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor", "participant"]))
):
    """OR-Tools Timetable Grid & Hero Speaker-Cancellation Demo"""
    rooms = fetch_all("SELECT * FROM rooms")
    speakers = fetch_all("SELECT * FROM speakers")
    initial_solution = solve_timetable()
    return templates.TemplateResponse(
        request=request,
        name="schedule.html",
        context={
            "user": user,
            "rooms": rooms,
            "speakers": speakers,
            "initial_solution": initial_solution,
            "hero_speaker": HERO_SPEAKER["name"],
            "substitute_speaker": HERO_SPEAKER["substitute_name"]
        }
    )

@app.get("/attendees", response_class=HTMLResponse)
async def attendees_page(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Screen #9: Attendee Management & Automatic Waitlist Engine"""
    attendees = fetch_all("""
        SELECT r.id, s.name, s.email, s.department, s.year, r.status, r.registered_at
        FROM registrations r
        JOIN students s ON r.student_id = s.id
        ORDER BY r.registered_at DESC
    """)
    return templates.TemplateResponse(
        request=request,
        name="attendees.html",
        context={"user": user, "attendees": attendees}
    )

@app.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["participant"]))
):
    """Screen #8: Public Student Registration Portal"""
    user = get_session_user(request)
    events = fetch_all("SELECT id, name, event_type, expected_participants FROM events WHERE approval_status IN ('approved', 'auto_approved') ORDER BY created_at DESC")
    if not events:
        events = fetch_all("SELECT id, name, event_type, expected_participants FROM events ORDER BY created_at DESC")
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"user": user, "events": events}
    )

@app.get("/outbox", response_class=HTMLResponse)
@app.get("/notices", response_class=HTMLResponse)
async def outbox_page(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Screen #12: Outbox Notification Center"""
    notices = fetch_all("SELECT * FROM outbox ORDER BY created_at DESC")
    return templates.TemplateResponse(
        request=request,
        name="notices.html",
        context={"user": user, "notices": notices}
    )

@app.get("/participant", response_class=HTMLResponse)
async def participant_page(
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["participant", "supervisor"]))
):
    """Personalized Recommendations, Clash-Free Agenda & Live Digital QR Passes"""
    email = user.get("email", "student@galgotias.edu")
    student = get_or_create_student_profile(email, name=user.get("full_name", "Student Participant"))
    
    base_url = str(request.base_url).rstrip("/")
    passes = get_student_passes(email, base_url=base_url)
    recommendations = get_personalized_recommendations_for_student(student)
    
    return templates.TemplateResponse(
        request=request,
        name="participant.html",
        context={
            "user": user,
            "student": student,
            "passes": passes,
            "recommendations": recommendations.get("recommended_sessions", []),
            "peers": recommendations.get("recommended_peers", [])
        }
    )

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    event_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_role(["supervisor", "organiser"]))
):
    """Feedback Insights, Post-Event Attendance Metrics & Verifiable Credentials"""
    events = fetch_all("SELECT id, name FROM events")
    analytics_data = get_analytics_dashboard_data(event_id=event_id)
    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={
            "user": user,
            "events": events,
            "selected_event_id": event_id or "",
            **analytics_data
        }
    )

@app.get("/flyer/{event_id}", response_class=HTMLResponse)
async def view_flyer(
    event_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser", "participant", "supervisor"]))
):
    """Module 2: Auto-Generated Printable Campus Flyer with QR Code"""
    event = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        event = {"id": "ev_demo", "name": "Campus AI Innovation Summit 2026", "event_type": "Hackathon", "expected_participants": 180}
    
    return templates.TemplateResponse(
        request=request,
        name="flyer.html",
        context={
            "event": event,
            "venue": "Main Auditorium A (Block C)",
            "date": "25 & 26 November 2026",
            "time": "09:30 AM - 05:30 PM",
            "coordinators": "School of Artificial Intelligence & Data Science"
        }
    )

# --- REST APIs ---

@app.post("/api/register")
async def register_student_api(
    req: StudentRegistrationRequest,
    user: Dict[str, Any] = Depends(require_role(["participant"]))
):
    """Registers student with capacity guard & priority waitlist queuing."""
    if req.email.strip().lower() != user["email"].strip().lower():
        raise HTTPException(status_code=403, detail="Participants may only register themselves.")
    res = attendee_mgr.register_student(
        event_id=req.event_id,
        name=user.get("full_name") or req.name,
        email=user["email"],
        department=user.get("department") or req.department,
        year=req.year,
        interests=req.interests,
        preferred_sessions=req.preferred_sessions
    )
    return JSONResponse(content=res)

@app.post("/api/attendees/{reg_id}/cancel")
async def cancel_attendee_api(
    reg_id: str,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Cancels registration and triggers Automatic Waitlist Promotion."""
    res = attendee_mgr.cancel_registration(reg_id)
    return JSONResponse(content=res)

@app.post("/api/attendees/{reg_id}/checkin")
async def checkin_attendee_api(
    reg_id: str,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Marks attendee checked in at gate."""
    res = attendee_mgr.check_in_attendee(reg_id)
    return JSONResponse(content=res)

@app.get("/api/export/attendees.csv")
async def export_attendees_csv(
    event_id: str = "ev_001",
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Downloads full roster as CSV."""
    csv_data = attendee_mgr.generate_attendees_csv(event_id)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=attendees_{event_id}.csv"}
    )

@app.post("/api/outbox/stage")
async def stage_outbox_message(
    req: StageAnnouncementRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Stages notification in outbox."""
    msg_id = f"notif_{uuid.uuid4().hex[:8]}"
    operation_id = f"op_{uuid.uuid4().hex}"

    def stage_notice(conn):
        kavach.verify_recipient_limit(conn, [req.recipient])
        conn.execute(
            """INSERT INTO outbox
               (id, event_id, recipient, subject, message, type, status, operation_id)
               VALUES (?, ?, ?, ?, ?, ?, 'held', ?)""",
            (
                msg_id,
                req.event_id,
                req.recipient,
                req.subject,
                req.message,
                req.type,
                operation_id,
            ),
        )
        return {"notification_id": msg_id}

    with get_connection() as conn:
        result = kavach.execute_with_kavach(
            conn,
            req.event_id,
            user["email"],
            "stage_outbox_message",
            stage_notice,
            operation_id=operation_id,
            release_staged_notices=False,
        )
    if result["status"] != "committed":
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Could not stage notification."),
        )
    return {
        "success": True,
        "notification_id": result["details"]["notification_id"],
        "status": "held",
    }

@app.post("/api/outbox/release-all")
async def release_all_outbox(
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Releases all held outbox notifications to sent."""
    with get_connection() as conn:
        result = kavach.execute_with_kavach(
            conn,
            "SYSTEM",
            user["email"],
            "release_outbox",
            lambda transaction: {
                "dispatched_count": transaction.execute(
                    """UPDATE outbox SET status = 'sent', sent_at = CURRENT_TIMESTAMP
                       WHERE status = 'held'"""
                ).rowcount
            },
        )
    if result["status"] != "committed":
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Could not release outbox notifications."),
        )
    return {"success": True, **result["details"]}


@app.get("/api/human-review")
async def list_human_review_requests(
    user: Dict[str, Any] = Depends(require_role(["supervisor"]))
):
    """Lists pending planner requests that need supervisor review."""
    requests = fetch_all(
        """SELECT id, event_id, actor, operation_name, request_json, attempts,
                  last_error, status, created_at
           FROM human_review_queue
           WHERE status = 'pending'
           ORDER BY created_at ASC"""
    )
    return {"requests": requests}

@app.get("/api/report/pdf/{event_id}")
async def download_executive_report_pdf(
    event_id: str,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Downloads one-click Executive Event Summary PDF Report."""
    pdf_path = analytics_engine.generate_executive_report_pdf(event_id)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"Executive_Report_{event_id}.pdf"
    )

@app.post("/api/agent/genesis")
async def api_agent_genesis(
    req: AgentGenesisRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """End-to-end autonomous event auto-genesis from one natural language prompt."""
    res = execute_autonomous_event_genesis(
        prompt=req.prompt,
        organizer_email=req.organizer_email or "organiser@galgotias.edu",
        organizer_department=req.organizer_department or "School of Computing Science"
    )
    return JSONResponse(content=res)

@app.post("/api/agent/universal-command")
async def api_universal_command(
    req: UniversalCommandRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Executes on-the-fly natural language operational commands anywhere on campus platform."""
    res = execute_universal_command(command=req.command)
    return JSONResponse(content=res)

@app.post("/api/autopilot/parse-intent")
async def parse_autopilot_intent(
    req: ParseIntentRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """
    Pillar 1 - Section 2: Parses natural language / voice input,
    extracts structured event entities without rigid regex, and assesses completeness.
    """
    # 1. Safety validation (Kavach filter)
    is_safe, safety_err = validate_prompt_safety(req.prompt)
    if not is_safe:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "is_safe": False,
                "error": safety_err,
                "tts_response": "This request was blocked by safety policy."
            }
        )

    # 2. Extract entities using LLM (with deterministic fallback)
    user_context = {
        "name": user.get("full_name") or user.get("username"),
        "department": user.get("department", "School of AI")
    }
    entities = extract_event_entities_llm(prompt=req.prompt, user_context=user_context)

    # 3. Assess completeness & counter-questions
    is_ready, counter_questions, tts_text = assess_intake_completeness(entities)

    return JSONResponse(
        content={
            "success": True,
            "is_safe": True,
            "is_ready_for_planning": is_ready,
            "entities": entities.model_dump(),
            "counter_questions": counter_questions,
            "tts_response": tts_text
        }
    )

@app.post("/api/autopilot/session/start")
async def start_dialogue_session(
    req: DialogueStartRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """
    Pillar 2 - Turn 0/1: Ingests initial prompt, checks safety, creates/resumes session,
    and returns initial analysis + clarifying counter-questions if incomplete.
    """
    is_safe, safety_err = validate_prompt_safety(req.prompt)
    if not is_safe:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "is_safe": False,
                "error": safety_err,
                "tts_response": "This request was blocked by safety policy."
            }
        )

    user_context = {
        "name": user.get("full_name") or user.get("username"),
        "department": user.get("department", "School of AI")
    }

    session, is_new = get_or_create_session(
        prompt=req.prompt,
        user_id=user.get("email", "organiser"),
        user_context=user_context,
        session_id=req.session_id
    )

    return JSONResponse(
        content={
            "success": True,
            "session_id": session.session_id,
            "status": session.status,
            "turn_count": session.turn_count,
            "max_turns": session.max_turns,
            "is_ready_for_planning": session.status == "ready_to_plan",
            "current_question": session.current_question,
            "quick_replies": session.quick_replies,
            "tts_response": session.tts_response,
            "entities": session.accumulated_entities.model_dump(),
            "assumptions_made": session.assumptions_made,
            "turns": [t.model_dump() for t in session.turns]
        }
    )


@app.post("/api/autopilot/session/reply")
async def reply_dialogue_session(
    req: DialogueReplyRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """
    Pillar 2 - Multi-Turn Reply Handler:
    Fuses user's spoken or typed reply into accumulated entities.
    STRICT LOOP CIRCUIT BREAKER: If turn_count >= 2, automatically fills campus defaults
    and transitions to 'ready_to_plan'. Prevents infinite clarification loops.
    """
    session = get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Dialogue session not found or expired.")

    is_safe, safety_err = validate_prompt_safety(req.reply)
    if not is_safe:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "is_safe": False,
                "error": safety_err,
                "tts_response": "This input was blocked by safety policy."
            }
        )

    user_context = {
        "name": user.get("full_name") or user.get("username"),
        "department": user.get("department", "School of AI")
    }

    session = fuse_dialogue_reply(
        session=session,
        user_reply=req.reply,
        user_context=user_context
    )

    return JSONResponse(
        content={
            "success": True,
            "session_id": session.session_id,
            "status": session.status,
            "turn_count": session.turn_count,
            "max_turns": session.max_turns,
            "is_ready_for_planning": session.status == "ready_to_plan",
            "current_question": session.current_question,
            "quick_replies": session.quick_replies,
            "tts_response": session.tts_response,
            "entities": session.accumulated_entities.model_dump(),
            "assumptions_made": session.assumptions_made,
            "turns": [t.model_dump() for t in session.turns]
        }
    )


@app.post("/api/autopilot/session/reset")
async def reset_dialogue_session_api(
    req: DialogueResetRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Resets an active dialogue session."""
    did_reset = reset_session(req.session_id)
    return JSONResponse(content={"success": did_reset, "session_id": req.session_id})


@app.post("/api/autopilot/run")
@app.post("/agent/run", dependencies=[Depends(require_role(["organiser", "supervisor"]))])
async def run_autopilot_api(
    req: AutopilotRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Runs autonomous event planning with provider fallback and live timeline logging."""
    res = run_autopilot_with_fallback(
        prompt=req.prompt,
        date=req.date,
        start_time=req.start_time,
        end_time=req.end_time,
        budget=req.budget,
    )
    return JSONResponse(content=res)

@app.post("/api/copilot/parse")
async def parse_copilot_brief(
    req: CopilotParseRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Module 1: Parses natural language event brief and applies Adaptive Intake verification."""
    parsed = parse_event_brief(req.brief)
    intake = adaptive_intake(req.brief)
    task_board = get_event_task_board(parsed.get("event_type", "hackathon"))
    return {
        "success": True,
        "parsed": parsed,
        "adaptive_intake": intake,
        "tasks": task_board
    }

@app.post("/api/certificates/generate")
async def generate_certificate_api(
    req: CertificateGenerateRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Module 7: Generates verified landscape PDF certificate with embedded QR verification."""
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base_url:
        public_base_url = str(request.base_url).rstrip("/")
    cert_data = analytics_engine.generate_certificate(
        student_id=req.student_id,
        student_name=req.student_name,
        event_id=req.event_id,
        event_name=req.event_name,
        verify_base_url=f"{public_base_url}/verify"
    )
    return JSONResponse(content=cert_data)

@app.get("/api/certificates/download/{cert_id}")
async def download_certificate_pdf(
    cert_id: str,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Module 7: Downloads the generated certificate PDF."""
    cert = fetch_one("SELECT pdf_path FROM certificates WHERE id = ?", (cert_id,))
    if not cert or not cert.get("pdf_path") or not os.path.exists(cert["pdf_path"]):
        raise HTTPException(status_code=404, detail="Certificate PDF not found.")
    return FileResponse(
        path=cert["pdf_path"],
        media_type="application/pdf",
        filename=f"Certificate_{cert_id}.pdf"
    )

@app.get("/api/catalog")
async def get_catalog(
    user: Dict[str, Any] = Depends(require_role(["data_manager", "organiser", "supervisor"]))
):
    """Returns campus resources, categories, and inventory stock."""
    items = fetch_all("SELECT * FROM resources")
    return {"catalog": items}

@app.get("/api/recommendations/resources")
async def get_resource_recommendations(
    event_type: str = "hackathon",
    headcount: int = 150,
    user: Dict[str, Any] = Depends(require_role(["data_manager", "organiser", "supervisor"]))
):
    """Module 3: Resource predictions & smart campus logistics bundles."""
    preds = resource_opt.estimate_resources(headcount=headcount, duration_hours=6.0, event_type=event_type)
    recs = resource_opt.get_smart_recommendations(event_type=event_type, headcount=headcount)
    plan = resource_opt.build_requisition_plan(preds)
    return {
        "predictions": preds,
        "recommendations": recs,
        "requisition_plan": plan
    }

@app.post("/api/schedule/solve")
async def solve_schedule_api(
    payload: Optional[Dict[str, Any]] = None,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Module 2: Solves conflict-free timetable using Google OR-Tools CP-SAT."""
    payload = payload or {}
    sessions = payload.get("sessions")
    slots = payload.get("slots")
    custom_rooms = payload.get("rooms")
    result = solve_timetable(sessions=sessions, slots=slots, custom_rooms=custom_rooms)
    return JSONResponse(content=result)

@app.post("/api/schedule/hero-speaker-cancel")
async def hero_speaker_cancellation_demo(
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Hero Demo: Speaker cancellation, replacement matching, re-scheduling, and Outbox alert."""
    result = handle_hero_speaker_cancellation()
    return JSONResponse(content=result)

@app.get("/api/schedule/export.csv")
async def export_schedule_csv_endpoint(
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Downloads timetable schedule as CSV."""
    solve_res = solve_timetable()
    csv_str = export_schedule_csv(solve_res.get("schedule", []))
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=timetable_export.csv"}
    )

@app.get("/api/participant/{student_id}/recommendations")
async def get_student_recommendations(
    student_id: str,
    user: Dict[str, Any] = Depends(require_role(["participant"]))
):
    """Module 4: Personalized sessions & networking matching using TF-IDF."""
    student_profile = get_or_create_student_profile(
        email=user["email"],
        name=user.get("full_name", "Student Participant"),
        department=user.get("department", "Computer Science")
    )
    if student_id != student_profile["id"]:
        raise HTTPException(status_code=403, detail="Participants may only view their own recommendations.")
    student = fetch_one("SELECT interests FROM students WHERE id = ?", (student_profile["id"],))
    interests = json.loads(student["interests"]) if (student and student["interests"]) else []

    sample_sessions = [
        {"id": "s1", "title": "Generative AI & LLM Systems", "track": "AI/ML", "slot_time": "10:00 - 11:30", "expected_attendance": 150},
        {"id": "s2", "title": "Advanced Web3 & DeFi Architecture", "track": "Blockchain", "slot_time": "10:00 - 11:30", "expected_attendance": 40},
        {"id": "s3", "title": "Building Autonomous Agents with Python", "track": "AI/ML", "slot_time": "12:00 - 13:30", "expected_attendance": 100},
        {"id": "s4", "title": "Cyber Threat Modeling & Bug Bounty", "track": "Cybersecurity", "slot_time": "14:30 - 16:00", "expected_attendance": 60}
    ]

    recs = participant_xp.recommend_sessions(interests, sample_sessions, top_k=3)
    networking = participant_xp.recommend_networking(student_id)

    return {
        "student_id": student_id,
        "interests": interests,
        "recommended_sessions": recs,
        "networking": networking
    }

@app.post("/api/assistant/ask")
async def ask_assistant(
    req: AskAssistantRequest,
    user: Dict[str, Any] = Depends(require_role(["organiser", "participant", "supervisor"]))
):
    """Module 5: Grounded Q&A Assistant without hallucinations."""
    ans = comm_agent.answer_query(req.event_id, req.query)
    return JSONResponse(content=ans)

@app.post("/api/feedback/submit")
async def submit_feedback(
    fb: FeedbackSubmission,
    user: Dict[str, Any] = Depends(require_role(["participant"]))
):
    """Module 6: Feedback submission, sentiment scoring, and theme detection."""
    student = get_or_create_student_profile(
        email=user["email"],
        name=user.get("full_name", "Student Participant"),
        department=user.get("department", "Computer Science")
    )
    if fb.student_id and fb.student_id != student["id"]:
        raise HTTPException(status_code=403, detail="Participants may only submit their own feedback.")
    result = record_feedback(
        event_id=fb.event_id,
        rating=fb.rating,
        comment=fb.comment,
        student_id=student["id"]
    )
    return JSONResponse(content={
        "status": "saved",
        "feedback_id": result["feedback_id"],
        "analysis": {"sentiment": result["sentiment"], "score": result["sentiment_score"]},
        "themes": result["themes"]
    })

@app.get("/api/analytics/{event_id}")
async def get_event_analytics(
    event_id: str,
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Module 7: Full event metrics, attendance rate, and future recommendations."""
    metrics = analytics_engine.compute_event_metrics(event_id)
    raw_feedbacks = fetch_all("SELECT id, rating, comment FROM feedback WHERE event_id = ?", (event_id,))
    feedback_insights = feedback_analyzer.analyze_batch(raw_feedbacks)
    return {
        "metrics": metrics,
        "feedback_intelligence": feedback_insights
    }

@app.get("/api/outbox")
async def get_outbox(
    user: Dict[str, Any] = Depends(require_role(["organiser", "supervisor"]))
):
    """Lists staged and sent campus notifications."""
    notices = fetch_all("SELECT * FROM outbox ORDER BY created_at DESC LIMIT 25")
    return {"outbox": notices}

@app.get("/verify/{cert_id}", response_class=HTMLResponse)
async def verify_certificate(cert_id: str, request: Request):
    """Online Verification Endpoint for certificates."""
    cert_info = verify_certificate_by_id(cert_id)
    return templates.TemplateResponse(
        request=request,
        name="verify_certificate.html",
        context={
            "cert_id": cert_id,
            "cert": cert_info
        },
        status_code=200 if cert_info else 404
    )



if __name__ == "__main__":
    import uvicorn
    print("=" * 65)
    print("[*] Starting AgenticLiner Live Server on http://127.0.0.1:8000")
    print("=" * 65)
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=8000, reload=True)
