"""Build the Project Report as a PDF using only docs/submission/FACT_SHEET.md,
docs/submission/RESULTS_AND_LIMITATIONS.md and docs/submission/TEAM.md.

Output: docs/submission/out/OPEN_OUTLIERS_AgenticLiner.pdf (20 to 30 pages, under 8 MB)
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import sys
import zlib
from pathlib import Path
from PIL import Image

import reportlab.rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph as _OrigParagraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image as RLImage,
)

def Paragraph(text, *args, **kwargs):
    if isinstance(text, str):
        text = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", text)
    return _OrigParagraph(text, *args, **kwargs)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Group

# Disable compression so text extraction is transparent
reportlab.rl_config.pageCompression = 0

ROOT = Path(__file__).resolve().parents[2]
DOCS_SUBMISSION = ROOT / "docs" / "submission"
OUT_DIR = DOCS_SUBMISSION / "out"
OUT_IMG_DIR = OUT_DIR / "img"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

PDF_OUTPUT_PATH = OUT_DIR / "OPEN_OUTLIERS_AgenticLiner.pdf"
PDF_BACKUP_PATH = OUT_DIR / "OPEN.OUTLIERS_AgenticLiner.pdf"

FACT_SHEET_PATH = DOCS_SUBMISSION / "FACT_SHEET.md"
RESULT_PATH = DOCS_SUBMISSION / "RESULTS_AND_LIMITATIONS.md"
if not RESULT_PATH.exists():
    RESULT_PATH = DOCS_SUBMISSION / "RESULT_AND_LIMITATION.md"
TEAM_PATH = DOCS_SUBMISSION / "TEAM.md"
SCREENSHOTS_DIR = ROOT / "docs" / "screenshots"

BANNED_WORDS = [
    "guarantee",
    "zero",
    "100%",
    "seamless",
    "robust",
    "real-time",
    "state-of-the-art",
    "revolutionary",
    "two-phase",
    "signed",
]


def extract_allowed_numbers() -> set[str]:
    """Extract all numbers from the three source files."""
    sources = [
        FACT_SHEET_PATH,
        RESULT_PATH,
        DOCS_SUBMISSION / "RESULT_AND_LIMITATION.md",
        TEAM_PATH,
    ]
    all_text = ""
    for src in sources:
        if src.exists():
            all_text += src.read_text(encoding="utf-8") + "\n"
    tokens = set(re.findall(r"\b\d+(?:\.\d+)*\b", all_text))
    int_tokens = set(re.findall(r"\d+", all_text))
    return tokens.union(int_tokens)


def optimize_screenshots() -> dict[str, Path]:
    """Downscale screenshots to JPEG quality 80 in out/img/ to ensure small file size."""
    converted = {}
    for p in sorted(SCREENSHOTS_DIR.glob("*.png")):
        im = Image.open(p).convert("RGB")
        if im.width > 1400:
            new_height = int(im.height * (1400 / im.width))
            im = im.resize((1400, new_height), Image.Resampling.LANCZOS)
        target = OUT_IMG_DIR / (p.stem + ".jpg")
        im.save(target, format="JPEG", quality=80, optimize=True)
        converted[p.name] = target
    return converted


def make_styles():
    base_styles = getSampleStyleSheet()

    styles = {
        "CoverTitle": ParagraphStyle(
            "CoverTitle",
            parent=base_styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=32,
            textColor=colors.HexColor("#1e293b"),
            alignment=1,
            spaceAfter=15,
        ),
        "CoverSubtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#475569"),
            alignment=1,
            spaceAfter=25,
        ),
        "CoverMeta": ParagraphStyle(
            "CoverMeta",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=16,
            textColor=colors.HexColor("#334155"),
            alignment=1,
        ),
        "Heading1": ParagraphStyle(
            "CustomHeading1",
            parent=base_styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=0,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "Heading2": ParagraphStyle(
            "CustomHeading2",
            parent=base_styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            spaceBefore=8,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "Body": ParagraphStyle(
            "CustomBody",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12.5,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=6,
        ),
        "BodyBold": ParagraphStyle(
            "CustomBodyBold",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12.5,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
        ),
        "Bullet": ParagraphStyle(
            "CustomBullet",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#1e293b"),
            leftIndent=12,
            firstLineIndent=-8,
            spaceAfter=3,
        ),
        "CodeText": ParagraphStyle(
            "CodeText",
            parent=base_styles["Normal"],
            fontName="Courier",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#0f172a"),
        ),
        "TableHead": ParagraphStyle(
            "TableHead",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.white,
            alignment=0,
        ),
        "TableCell": ParagraphStyle(
            "TableCell",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0f172a"),
        ),
        "TableCellBold": ParagraphStyle(
            "TableCellBold",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0f172a"),
        ),
        "TableCellCenter": ParagraphStyle(
            "TableCellCenter",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0f172a"),
            alignment=1,
        ),
        "Caption": ParagraphStyle(
            "Caption",
            parent=base_styles["Italic"],
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#475569"),
            spaceBefore=3,
            spaceAfter=6,
        ),
        "ScreenshotMeta": ParagraphStyle(
            "ScreenshotMeta",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#334155"),
            spaceBefore=2,
            spaceAfter=4,
        ),
    }
    return styles


def build_architecture_diagram() -> Drawing:
    """Build a vector drawing of the multi-tier system architecture."""
    dwg = Drawing(504, 210)

    # Outer canvas border
    dwg.add(
        Rect(
            0,
            0,
            504,
            210,
            rx=4,
            ry=4,
            fillColor=colors.HexColor("#f8fafc"),
            strokeColor=colors.HexColor("#cbd5e1"),
            strokeWidth=1,
        )
    )

    # Tier 1: Client Layer
    dwg.add(
        Rect(
            12,
            165,
            480,
            34,
            rx=3,
            ry=3,
            fillColor=colors.HexColor("#e0e7ff"),
            strokeColor=colors.HexColor("#6366f1"),
            strokeWidth=1,
        )
    )
    dwg.add(
        String(
            252,
            177,
            "Client Tier: Jinja2 SSR Views, Bootstrap 5.3, Web Speech API",
            textAnchor="middle",
            fontName="Helvetica-Bold",
            fontSize=9.5,
            fillColor=colors.HexColor("#1e1b4b"),
        )
    )

    # Tier 2: Gateway & RBAC
    dwg.add(
        Rect(
            12,
            124,
            480,
            32,
            rx=3,
            ry=3,
            fillColor=colors.HexColor("#e0f2fe"),
            strokeColor=colors.HexColor("#0284c7"),
            strokeWidth=1,
        )
    )
    dwg.add(
        String(
            252,
            135,
            "API Gateway & Security: FastAPI, Session Middleware, 4 RBAC Roles",
            textAnchor="middle",
            fontName="Helvetica-Bold",
            fontSize=9.5,
            fillColor=colors.HexColor("#0369a1"),
        )
    )

    # Tier 3: Dual-Mode Autopilot Orchestration
    dwg.add(
        Rect(
            12,
            83,
            234,
            32,
            rx=3,
            ry=3,
            fillColor=colors.HexColor("#fef3c7"),
            strokeColor=colors.HexColor("#d97706"),
            strokeWidth=1,
        )
    )
    dwg.add(
        String(
            129,
            94,
            "Autopilot: Agent Mode (LLM Tools)",
            textAnchor="middle",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            fillColor=colors.HexColor("#92400e"),
        )
    )

    dwg.add(
        Rect(
            258,
            83,
            234,
            32,
            rx=3,
            ry=3,
            fillColor=colors.HexColor("#fef3c7"),
            strokeColor=colors.HexColor("#d97706"),
            strokeWidth=1,
        )
    )
    dwg.add(
        String(
            375,
            94,
            "Autopilot: Fixed Pipeline Fallback (5 Steps)",
            textAnchor="middle",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            fillColor=colors.HexColor("#92400e"),
        )
    )

    # Tier 4: Kavach Transactional Safety Shield
    dwg.add(
        Rect(
            12,
            44,
            480,
            30,
            rx=3,
            ry=3,
            fillColor=colors.HexColor("#fee2e2"),
            strokeColor=colors.HexColor("#dc2626"),
            strokeWidth=1,
        )
    )
    dwg.add(
        String(
            252,
            54,
            "Kavach Safety Layer: Invariant Validation & Savepoint Rollback",
            textAnchor="middle",
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=colors.HexColor("#991b1b"),
        )
    )

    # Tier 5: Persistence Layer
    dwg.add(
        Rect(
            12,
            8,
            480,
            28,
            rx=3,
            ry=3,
            fillColor=colors.HexColor("#f1f5f9"),
            strokeColor=colors.HexColor("#64748b"),
            strokeWidth=1,
        )
    )
    dwg.add(
        String(
            252,
            17,
            "Persistence Tier: SQLite Database (14 Tables), Outbox, Audit Log",
            textAnchor="middle",
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=colors.HexColor("#334155"),
        )
    )

    return dwg


def build_pdf_flowables(styles, img_map: dict[str, Path]) -> list:
    """Build the flowable elements for the entire PDF across exactly 24 pages."""
    story = []

    # =========================================================================
    # PAGE 1: TITLE PAGE
    # =========================================================================
    story.append(Spacer(1, 40))
    header_table = Table(
        [
            [
                Paragraph("<b>SPARKX 3.0 INNOVATION CHALLENGE</b>", styles["Caption"]),
                Paragraph("<b>TRACK: CHALLENGE 1</b>", styles["Caption"]),
            ]
        ],
        colWidths=[252, 252],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 45))

    story.append(Paragraph("AgenticLiner", styles["CoverTitle"]))
    story.append(
        Paragraph(
            "AI-Powered Intelligent Event Planning and Management Platform",
            styles["CoverSubtitle"],
        )
    )
    story.append(Spacer(1, 15))

    sep_table = Table([[""]], colWidths=[504], rowHeights=[2])
    sep_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0284c7")),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(sep_table)
    story.append(Spacer(1, 35))

    meta_data = [
        [
            Paragraph("<b>Competition Event:</b>", styles["TableCellBold"]),
            Paragraph("SparkX 3.0 Innovation Challenge", styles["TableCell"]),
        ],
        [
            Paragraph("<b>Host Institution:</b>", styles["TableCellBold"]),
            Paragraph("Galgotias University", styles["TableCell"]),
        ],
        [
            Paragraph("<b>Assigned Track:</b>", styles["TableCellBold"]),
            Paragraph(
                "Challenge 1: AI-Powered Intelligent Event Planning and Management Platform",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("<b>Team Name:</b>", styles["TableCellBold"]),
            Paragraph("OPEN.OUTLIERS", styles["TableCell"]),
        ],
        [
            Paragraph("<b>Team Lead:</b>", styles["TableCellBold"]),
            Paragraph(
                "Himanshu Gupta (B.Tech AIML, School of Artificial Intelligence)",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("<b>Team Members:</b>", styles["TableCellBold"]),
            Paragraph(
                "Diya Varshney (B.Sc CS Data Science), Ashish Kumar Singh (B.Tech AIML)",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("<b>Submission Date:</b>", styles["TableCellBold"]),
            Paragraph("14-11-2026", styles["TableCell"]),
        ],
    ]
    t_meta = Table(meta_data, colWidths=[150, 354])
    t_meta.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.append(t_meta)

    story.append(PageBreak())

    # =========================================================================
    # PAGE 2: ABSTRACT & 1. PROBLEM STATEMENT
    # =========================================================================
    story.append(Paragraph("Abstract", styles["Heading1"]))

    abstract_text = (
        "AgenticLiner addresses manual friction and reliability failure modes in university campus event planning. "
        "In manual campus operations, organisers coordinate halls, resources, schedules, attendee registrations, "
        "and notifications without unified transactional enforcement. Direct language model deployment introduces "
        "operational risks, including room double-booking, capacity violations, partial state updates, and "
        "phantom notifications for uncommitted changes. AgenticLiner resolves these issues through a dual-mode "
        "architecture: an autonomous Autopilot agent utilizing tool-calling capabilities with automatic fallback to a "
        "deterministic sequential pipeline, paired with the Kavach safety layer. Kavach enforces invariant validation "
        "across capacity limits, timetable clashes, inventory stocks, time boundaries, and notification blast radius limits "
        "within a savepoint transaction with rollback, plus an outbox written after commit. "
        "The offline benchmark used a scripted planner on synthetic data; in our live Gemini test, agent mode fell back to the deterministic pipeline."
    )
    story.append(Paragraph(abstract_text, styles["Body"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("1. Problem Statement", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>Core Problem:</b> <i>\"Event organisers coordinate rooms, speakers, equipment, volunteers, schedules, registrations and notices mostly by hand. An LLM assistant placed directly on this work can double-book a room, exceed capacity, leave a multi-step change half-finished, or send participants a notice for a change that never happened.\"</i>",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "University event management across campus departments is characterized by high manual coordination overhead. "
            "Student clubs, faculty organizers, and academic administrators manage physical spaces and assets across isolated spreadsheets, "
            "informal message threads, and physical sign-offs. This fragmented process creates recurring operational failure modes: "
            "hall collisions, resource starvation during concurrent events, and inaccurate timetable distribution.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "While conversational AI and Large Language Models (LLMs) provide natural language comprehension, placing an unconstrained "
            "LLM directly in charge of university operational databases introduces critical operational vulnerabilities:",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Capacity and Safety Violations:</b> Language models optimize for textual fluency rather than arithmetic verification, "
            "frequently booking 150 students into smaller rooms or exceeding physical capacity without validating physical limits.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Schedule Collisions:</b> Autonomous agents executing direct database writes can double-book venues when temporal overlaps "
            "are not evaluated against relational constraint engines.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Partial Mutation Corruption:</b> Multi-step operations (e.g. reserving a venue, allocating 3 resource bundles, and dispatching notices) "
            "frequently fail mid-sequence, leaving orphaned bookings and database state corruption.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Premature Notification Dispatch:</b> Conversational agents dispatch communications prior to database verification, notifying attendees "
            "of schedule or venue updates that were rolled back or never finalized.",
            styles["Bullet"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 3: 2. OBJECTIVES & 3. PROPOSED SOLUTION
    # =========================================================================
    story.append(Paragraph("2. Objectives", styles["Heading1"]))
    story.append(
        Paragraph(
            "To solve these operational challenges without compromising safety, AgenticLiner establishes 6 primary technical objectives:",
            styles["Body"],
        )
    )
    objectives_list = [
        (
            "1. Plain-Language Planning",
            "Extract structured event parameters (event type, attendee headcount, target date, and time intervals) directly from unstructured briefs using rule-based parsing and adaptive intake.",
        ),
        (
            "2. Conflict-Free Timetable Scheduling",
            "Enforce mathematical constraint satisfaction using Google OR-Tools CP-SAT to ensure no room double-booking, strict capacity adherence, and speaker availability window enforcement.",
        ),
        (
            "3. Data-Driven Logistics Requisition",
            "Synthesize equipment, audio-visual, and catering allocations through historical event pattern lookup and scikit-learn regression models.",
        ),
        (
            "4. Participant Communication & Experience",
            "Provide grounded question-answering strictly derived from confirmed database schedules and generate interest-aligned session recommendations.",
        ),
        (
            "5. Kavach Transactional Safety Shield",
            "Every Autopilot booking runs inside a database savepoint that is rolled back if a rule fails, and notices are written only after the booking commits.",
        ),
        (
            "6. Post-Event Feedback & Verifiable Credentials",
            "Analyze attendee feedback using rule-based sentiment classification and issue tamper-evident SHA-256 PDF certificates with a SHA-256 hash recorded in the database and checked on the verify page (a hash, not a digital signature) and scannable QR verification.",
        ),
    ]
    for title, desc in objectives_list:
        story.append(
            Paragraph(
                f"- <b>{title}:</b> {desc}",
                styles["Bullet"],
            )
        )
    story.append(Spacer(1, 6))

    story.append(Paragraph("3. Proposed Solution", styles["Heading1"]))
    story.append(
        Paragraph(
            "AgenticLiner is an intelligent campus event planning platform engineered specifically for university operational governance. "
            "The platform bridges natural language planning and deterministic relational integrity through two synchronized core subsystems: "
            "the <b>Autopilot Engine</b> and the <b>Kavach Safety Shield</b>.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Autonomous Tool-Calling Agent Mode:</b> The organiser submits a plain-language prompt. The system initializes a multi-turn "
            "tool-calling loop (up to 5 steps) utilizing Google GenAI Gemini, Groq, or local Ollama instances. The agent calls tools for intake "
            "analysis, venue discovery, resource recommendations, and booking requisition.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Deterministic Fixed Pipeline Fallback:</b> If provider quotas, network disconnects, or tool-calling schema errors occur "
            "(such as missing thought signatures on multi-tool returns), the system automatically falls back to a deterministic 5-step Python pipeline "
            "that ensures end-to-end plan execution without external API dependencies.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Kavach Savepoint Safety Shield:</b> Every booking and resource allocation must pass 5 hard invariant checks within an active "
            "database savepoint. If any check fails, the transaction immediately rolls back, recording an append-only audit log entry.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Staged Transactional Outbox Pattern:</b> Stakeholder notifications (for deans, student coordinators, and participants) are staged "
            "in an internal outbox table with status 'held'. Notices transition to 'sent' only after the database transaction successfully commits.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "<b>Internal Campus Scope:</b> The platform books internal campus infrastructure: university auditoriums, seminar halls, computing labs, "
            "audio equipment, and stage lighting, where items carry an internal estimated cost of 0.0. Monetary budgets and payment collection are not implemented. "
            "Access is governed across 4 RBAC roles: Organiser, Supervisor, Data Manager, and Participant.",
            styles["Body"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 4: 4. METHODOLOGY
    # =========================================================================
    story.append(Paragraph("4. Methodology", styles["Heading1"]))
    story.append(
        Paragraph(
            "The development and evaluation of AgenticLiner adhere to formal software engineering principles designed to prevent "
            "unreliable agentic behavior in production environments.",
            styles["Body"],
        )
    )

    story.append(Paragraph("Core Design Principle", styles["Heading2"]))
    story.append(
        Paragraph(
            "<b>\"the LLM understands and writes, deterministic code checks and decides\"</b>",
            styles["BodyBold"],
        )
    )
    story.append(
        Paragraph(
            "This principle establishes strict operational boundaries between probabilistic generative models and deterministic system software: "
            "Large Language Models are utilized where linguistic flexibility is advantageous: the LLM is used in the Autopilot tool-calling loop and the participant Q&A. "
            "Conversely, deterministic code checks and decides every operational state mutation: mathematical timetable conflict solving, venue capacity validation, "
            "inventory decrementing, ACID transactional rollback, and outbox notification release. The LLM never writes directly to relational database tables without validation.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(Paragraph("Development Approach", styles["Heading2"]))
    story.append(
        Paragraph(
            "<b>\"the lead directed AI coding assistants that wrote most of the source code, and verified the result with automated tests, a fresh-clone run, live checks and an independent benchmark checker\"</b>",
            styles["BodyBold"],
        )
    )
    story.append(
        Paragraph(
            "1. <b>Architectural Direction:</b> The team lead formulated the domain scope, database schema invariants, Kavach safety rules, "
            "and review gates, directing Google Antigravity coding agents to author modular Python implementations.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "2. <b>Automated Test Verification:</b> Tests were added alongside each change, accumulating 343 passing automated tests "
            "covering unit logic, safety invariants, API endpoints, and end-to-end workflows.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "3. <b>Fresh-Clone Verification:</b> Release stability was evaluated by executing a clean clone in an isolated temporary environment, "
            "validating every setup instruction, CLI script, and dependency installation without developer-local state.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "4. <b>Bounded Live Provider Checks:</b> Real LLM connectivity was validated using bounded API test scripts against Google GenAI Gemini, "
            "verifying ping responses, model availability, tool-calling response structures, and repeated Q&A consistency.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "5. <b>Separate Benchmark Checker:</b> A separate checker script (IndependentDBChecker) that shares no code with Kavach "
            "was deployed to independently inspect SQLite database tables after execution.",
            styles["Bullet"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(Paragraph("Evaluation Method", styles["Heading2"]))
    story.append(
        Paragraph(
            "System safety was evaluated through an automated benchmark suite (run_evaluation.py) executing 50 prompt scenarios "
            "(15 clean, 15 high-conflict, 2 destructive, 3 bulk-write, and 15 ambiguous) against isolated SQLite database instances. "
            "To measure the safety layer rather than non-deterministic LLM variance, a scripted rule-based planner replaced the LLM, "
            "executing identical action plans across three comparative architectures:",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Setup A (Direct Planned Actions):</b> Represents an unconstrained agent executing SQL writes with SQLite foreign keys and check constraints disabled.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Setup B (SQLite Constraints Only):</b> Evaluates defense provided strictly by standard relational database constraints and triggers without application safety code.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Setup C (Kavach Agent Pipeline):</b> Evaluates the full AgenticLiner pipeline incorporating rule-based intake, destructive regex filtering, and Kavach savepoint transaction invariants with rollback.",
            styles["Bullet"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 5: 5. TECHNOLOGIES USED
    # =========================================================================
    story.append(Paragraph("5. Technologies Used", styles["Heading1"]))
    story.append(
        Paragraph(
            "All software components in AgenticLiner are pinned to explicit dependency versions defined in `requirements.txt`. "
            "The system requires Python 3.10 to 3.13 and operates entirely offline by default.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    tech_data = [
        [
            Paragraph("<b>Package</b>", styles["TableHead"]),
            Paragraph("<b>Version</b>", styles["TableHead"]),
            Paragraph("<b>Role in Platform</b>", styles["TableHead"]),
            Paragraph("<b>Package</b>", styles["TableHead"]),
            Paragraph("<b>Version</b>", styles["TableHead"]),
            Paragraph("<b>Role in Platform</b>", styles["TableHead"]),
        ],
        [
            Paragraph("fastapi", styles["TableCellBold"]),
            Paragraph("0.162.0", styles["TableCellCenter"]),
            Paragraph("Core ASGI REST API & SSR", styles["TableCell"]),
            Paragraph("httpx", styles["TableCellBold"]),
            Paragraph("0.30.0", styles["TableCellCenter"]),
            Paragraph("Async HTTP client for LLM API", styles["TableCell"]),
        ],
        [
            Paragraph("uvicorn", styles["TableCellBold"]),
            Paragraph("0.42.0", styles["TableCellCenter"]),
            Paragraph("High-performance ASGI server", styles["TableCell"]),
            Paragraph("pytest", styles["TableCellBold"]),
            Paragraph("9.0.3", styles["TableCellCenter"]),
            Paragraph("Automated test framework", styles["TableCell"]),
        ],
        [
            Paragraph("jinja2", styles["TableCellBold"]),
            Paragraph("3.1.6", styles["TableCellCenter"]),
            Paragraph("Server-Side HTML template rendering", styles["TableCell"]),
            Paragraph("pytest-asyncio", styles["TableCellBold"]),
            Paragraph("1.3.0", styles["TableCellCenter"]),
            Paragraph("Async endpoint test runner", styles["TableCell"]),
        ],
        [
            Paragraph("python-multipart", styles["TableCellBold"]),
            Paragraph("0.0.22", styles["TableCellCenter"]),
            Paragraph("HTTP form and file upload parser", styles["TableCell"]),
            Paragraph("passlib", styles["TableCellBold"]),
            Paragraph("1.7.4", styles["TableCellCenter"]),
            Paragraph("Password hashing utilities", styles["TableCell"]),
        ],
        [
            Paragraph("pydantic", styles["TableCellBold"]),
            Paragraph("2.13.1", styles["TableCellCenter"]),
            Paragraph("Data schema validation & settings", styles["TableCell"]),
            Paragraph("bcrypt", styles["TableCellBold"]),
            Paragraph("5.0.0", styles["TableCellCenter"]),
            Paragraph("Blowfish password cipher", styles["TableCell"]),
        ],
        [
            Paragraph("python-dotenv", styles["TableCellBold"]),
            Paragraph("1.2.2", styles["TableCellCenter"]),
            Paragraph("Environment configuration loader", styles["TableCell"]),
            Paragraph("pyotp", styles["TableCellBold"]),
            Paragraph("2.9.0", styles["TableCellCenter"]),
            Paragraph("Time-based OTP token service", styles["TableCell"]),
        ],
        [
            Paragraph("itsdangerous", styles["TableCellBold"]),
            Paragraph("2.3.0", styles["TableCellCenter"]),
            Paragraph("Cryptographic cookie signing", styles["TableCell"]),
            Paragraph("authlib", styles["TableCellBold"]),
            Paragraph("1.6.11", styles["TableCellCenter"]),
            Paragraph("OAuth2 and OpenID protocol suite", styles["TableCell"]),
        ],
        [
            Paragraph("ortools", styles["TableCellBold"]),
            Paragraph("9.15.6755", styles["TableCellCenter"]),
            Paragraph("Google CP-SAT constraint solver", styles["TableCell"]),
            Paragraph("firebase-admin", styles["TableCellBold"]),
            Paragraph("7.1.0", styles["TableCellCenter"]),
            Paragraph("Firebase token verification", styles["TableCell"]),
        ],
        [
            Paragraph("scikit-learn", styles["TableCellBold"]),
            Paragraph("1.9.1", styles["TableCellCenter"]),
            Paragraph("TF-IDF & Ridge logistics models", styles["TableCell"]),
            Paragraph("pyngrok", styles["TableCellBold"]),
            Paragraph("7.5.4", styles["TableCellCenter"]),
            Paragraph("Tunneling for test webhooks", styles["TableCell"]),
        ],
        [
            Paragraph("numpy", styles["TableCellBold"]),
            Paragraph("2.4.4", styles["TableCellCenter"]),
            Paragraph("Vector mathematics array engine", styles["TableCell"]),
            Paragraph("psutil", styles["TableCellBold"]),
            Paragraph("7.2.2", styles["TableCellCenter"]),
            Paragraph("Process and system monitor", styles["TableCell"]),
        ],
        [
            Paragraph("scipy", styles["TableCellBold"]),
            Paragraph("1.17.1", styles["TableCellCenter"]),
            Paragraph("Sparse matrices & distance metrics", styles["TableCell"]),
            Paragraph("fpdf2", styles["TableCellBold"]),
            Paragraph("2.8.7", styles["TableCellCenter"]),
            Paragraph("Alternative PDF generation", styles["TableCell"]),
        ],
        [
            Paragraph("reportlab", styles["TableCellBold"]),
            Paragraph("5.1.0", styles["TableCellCenter"]),
            Paragraph("Vector report & certificate engine", styles["TableCell"]),
            Paragraph("matplotlib", styles["TableCellBold"]),
            Paragraph("3.10.8", styles["TableCellCenter"]),
            Paragraph("Static chart and plot renderer", styles["TableCell"]),
        ],
        [
            Paragraph("qrcode", styles["TableCellBold"]),
            Paragraph("8.2", styles["TableCellCenter"]),
            Paragraph("2D Quick-Response code generator", styles["TableCell"]),
            Paragraph("pandas", styles["TableCellBold"]),
            Paragraph("3.0.1", styles["TableCellCenter"]),
            Paragraph("Tabular CSV catalog sync engine", styles["TableCell"]),
        ],
        [
            Paragraph("pillow", styles["TableCellBold"]),
            Paragraph("12.1.1", styles["TableCellCenter"]),
            Paragraph("Raster image manipulation library", styles["TableCell"]),
            Paragraph("google-auth", styles["TableCellBold"]),
            Paragraph("2.47.0", styles["TableCellCenter"]),
            Paragraph("Google identity token library", styles["TableCell"]),
        ],
        [
            Paragraph("google-genai", styles["TableCellBold"]),
            Paragraph("2.34.0", styles["TableCellCenter"]),
            Paragraph("Official Google Gemini SDK", styles["TableCell"]),
            Paragraph("cryptography", styles["TableCellBold"]),
            Paragraph("46.0.7", styles["TableCellCenter"]),
            Paragraph("Low-level cryptographic ciphers", styles["TableCell"]),
        ],
        [
            Paragraph("groq", styles["TableCellBold"]),
            Paragraph("1.0.0", styles["TableCellCenter"]),
            Paragraph("Groq LPU cloud client library", styles["TableCell"]),
            Paragraph("requests", styles["TableCellBold"]),
            Paragraph("2.33.1", styles["TableCellCenter"]),
            Paragraph("Synchronous HTTP client library", styles["TableCell"]),
        ],
    ]
    t_tech = Table(tech_data, colWidths=[65, 45, 142, 65, 45, 142])
    t_tech.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_tech)
    story.append(Paragraph("Source: docs/submission/FACT_SHEET.md", styles["Caption"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("Key Technological Subsystems", styles["Heading2"]))
    story.append(
        Paragraph(
            "- <b>FastAPI Web Application:</b> Delivers asynchronous request handling across 70 registered endpoints. "
            "Session authentication uses session middleware with PBKDF2 password hashing.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Google OR-Tools CP-SAT Solver:</b> Solves timetable allocations as mathematical constraint satisfaction problems, "
            "modeling room occupancy intervals, capacity thresholds, and prerequisite dependencies.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Scikit-Learn Machine Learning:</b> Provides TF-IDF vectorization and cosine similarity calculations for participant track recommendations "
            "and historical Ridge regression for logistics estimates.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>ReportLab Document Engine:</b> Generates tamper-evident PDF digital credentials with a SHA-256 hash recorded in the database and checked on the verify page (a hash, not a digital signature) and a verification QR code.",
            styles["Bullet"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 6: 6. IMPLEMENTATION - SYSTEM ARCHITECTURE
    # =========================================================================
    story.append(Paragraph("6. Implementation", styles["Heading1"]))
    story.append(
        Paragraph(
            "AgenticLiner is constructed as a modular system organized across 6 distinct functional tiers: "
            "Presentation, API Gateway & Security, Autopilot Orchestration, Domain Modules, Kavach Safety Shield, and Persistence.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(Paragraph("System Architecture Diagram", styles["Heading2"]))
    story.append(build_architecture_diagram())
    story.append(Spacer(1, 8))

    story.append(Paragraph("Architectural Tier Walkthrough", styles["Heading2"]))
    arch_tiers = [
        (
            "Tier 1: Presentation & Client Interface",
            "Built using Jinja2 Server-Side Rendered (SSR) HTML5 templates styled with Bootstrap 5.3 and Bootstrap Icons. "
            "Client-side JavaScript provides interactive modals, scenario quick-fills, and microphone capture via the browser Web Speech API. "
            "The UI provides dedicated dashboard portals for Organisers, Supervisors, Data Managers, and Participants.",
        ),
        (
            "Tier 2: API Gateway & Security",
            "FastAPI ASGI application server managing session-based authentication and role-based route guards. "
            "Password verification utilizes PBKDF2-HMAC-SHA256. Public tunnel safeguards prohibit demo authentication when public network ingress is detected.",
        ),
        (
            "Tier 3: Autopilot Orchestration",
            "Coordinates multi-step campus planning. Supports <b>Agent Mode</b> using multi-turn LLM tool calling (Gemini, Groq, Ollama) "
            "and <b>Fixed Pipeline Fallback</b>, which executes an automated 5-step Python sequence without external network dependencies.",
        ),
        (
            "Tier 4: Core Domain Modules",
            "Specialized Python packages executing discrete planning tasks: brief parsing, constraint scheduling, resource allocation, "
            "participant personalization, live grounded Q&A, sentiment analysis, and verifiable credential generation.",
        ),
        (
            "Tier 5: Kavach Safety Shield",
            "Enforces savepoint transaction invariants with rollback directly above SQLite. Validates physical venue capacity, room double-booking, "
            "time intervals, equipment stocks, and notification blast radius limits within active database savepoints.",
        ),
        (
            "Tier 6: Persistence & Audit Layer",
            "Embedded SQLite 3 database (agenticliner.db) structured across 14 relational tables. Outbox notifications and append-only audit "
            "log entries are recorded transactionally to ensure state traceability.",
        ),
    ]
    for a_title, a_desc in arch_tiers:
        story.append(
            Paragraph(
                f"- <b>{a_title}:</b> {a_desc}",
                styles["Bullet"],
            )
        )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 7: 6. IMPLEMENTATION - CORE DOMAIN MODULES
    # =========================================================================
    story.append(Paragraph("Core Domain Modules", styles["Heading1"]))
    story.append(
        Paragraph(
            "The platform implements 7 domain modules alongside specialized attendee and safety engines. "
            "Rule-based subsystems are explicitly designated as rule-based below:",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    mod_data = [
        [
            Paragraph("<b>Module / Subsystem</b>", styles["TableHead"]),
            Paragraph("<b>What it Does</b>", styles["TableHead"]),
            Paragraph("<b>Technique</b>", styles["TableHead"]),
            Paragraph("<b>Key Repository Files</b>", styles["TableHead"]),
            Paragraph("<b>Known Operational Gap</b>", styles["TableHead"]),
        ],
        [
            Paragraph("<b>Module 1</b><br/>Brief Parser", styles["TableCellBold"]),
            Paragraph(
                "Extracts event parameters; prompts clarification",
                styles["TableCell"],
            ),
            Paragraph(
                "Rule-based heuristics, regex, optional LLM",
                styles["TableCell"],
            ),
            Paragraph("brief_parser.py", styles["CodeText"]),
            Paragraph(
                "Resolves relative weekdays ('next Friday') and clock times; unanchored ambiguous dates require clarification.",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Module 2</b><br/>Scheduler", styles["TableCellBold"]
            ),
            Paragraph(
                "Solves conflict-free room and session schedules",
                styles["TableCell"],
            ),
            Paragraph("Google OR-Tools CP-SAT solver", styles["TableCell"]),
            Paragraph("solver.py", styles["CodeText"]),
            Paragraph(
                "Batch solver only; not dynamic per single tool call",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Module 3</b><br/>Requisition", styles["TableCellBold"]
            ),
            Paragraph(
                "Recommends equipment, power, AV, and hospitality",
                styles["TableCell"],
            ),
            Paragraph(
                "Rule-based heuristics + Ridge regression", styles["TableCell"]
            ),
            Paragraph("recommender.py", styles["CodeText"]),
            Paragraph(
                "Campus items cost 0.0; no multi-vendor pricing",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Module 4</b><br/>Personalization", styles["TableCellBold"]
            ),
            Paragraph(
                "Computes student session recommendations", styles["TableCell"]
            ),
            Paragraph(
                "TF-IDF vectorizer + Cosine similarity", styles["TableCell"]
            ),
            Paragraph("recommender.py", styles["CodeText"]),
            Paragraph(
                "Session-level scoring; no individual seat gating",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Module 5</b><br/>Participant Q&A", styles["TableCellBold"]
            ),
            Paragraph(
                "Answers venue, timing, and schedule questions",
                styles["TableCell"],
            ),
            Paragraph(
                "Grounded LLM + rule-based keyword fallback",
                styles["TableCell"],
            ),
            Paragraph("assistant.py", styles["CodeText"]),
            Paragraph(
                "Ungrounded queries return administrative disclaimers",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Module 6</b><br/>Feedback Intel", styles["TableCellBold"]
            ),
            Paragraph(
                "Analyzes reviews for sentiment and 4 themes",
                styles["TableCell"],
            ),
            Paragraph(
                "Rule-based lexicon sentiment + regex heuristics",
                styles["TableCell"],
            ),
            Paragraph("analyzer.py", styles["CodeText"]),
            Paragraph(
                "Rule-based lexicon cannot resolve deep figurative prose",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Module 7</b><br/>Credentials", styles["TableCellBold"]
            ),
            Paragraph(
                "Issues verifiable PDF certificates with QR code",
                styles["TableCell"],
            ),
            Paragraph(
                "SHA-256 hash + ReportLab + Python-QRCode", styles["TableCell"]
            ),
            Paragraph("certificate.py", styles["CodeText"]),
            Paragraph(
                "Hash verified in SQLite, not public blockchain",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Attendee Hub</b><br/>Waitlist Engine",
                styles["TableCellBold"],
            ),
            Paragraph(
                "Student registration, check-in, auto-promotion",
                styles["TableCell"],
            ),
            Paragraph(
                "Relational transactions + waitlist transitions",
                styles["TableCell"],
            ),
            Paragraph("event_routes.py", styles["CodeText"]),
            Paragraph(
                "High write bursts bounded by SQLite database locking",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Autopilot</b><br/>Agent Mode", styles["TableCellBold"]
            ),
            Paragraph(
                "Autonomous multi-turn booking via tool calling",
                styles["TableCell"],
            ),
            Paragraph(
                "LLM function calling (Gemini/Groq/Ollama)", styles["TableCell"]
            ),
            Paragraph("agent_mode.py", styles["CodeText"]),
            Paragraph(
                "Multi-tool responses without thought signature trigger fallback",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Autopilot</b><br/>Fixed Pipeline", styles["TableCellBold"]
            ),
            Paragraph(
                "Deterministic 5-step fallback execution", styles["TableCell"]
            ),
            Paragraph(
                "Rule-based sequential Python orchestration",
                styles["TableCell"],
            ),
            Paragraph("agent.py", styles["CodeText"]),
            Paragraph(
                "Static execution order; cannot adapt dynamically",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph(
                "<b>Kavach</b><br/>Safety Engine", styles["TableCellBold"]
            ),
            Paragraph(
                "Enforces 5 invariants; transactional rollback",
                styles["TableCell"],
            ),
            Paragraph(
                "Savepoint transaction with rollback, plus an outbox written after commit", styles["TableCell"]
            ),
            Paragraph("kavach.py", styles["CodeText"]),
            Paragraph(
                "Speaker clash helper not wired to runtime booking tool",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("<b>Login & RBAC</b><br/>Security", styles["TableCellBold"]),
            Paragraph(
                "Authenticates 4 roles via session cookies", styles["TableCell"]
            ),
            Paragraph(
                "Session cookies + PBKDF2 hashing", styles["TableCell"]
            ),
            Paragraph("auth_routes.py", styles["CodeText"]),
            Paragraph(
                "Firebase token check requires live network; demo login disabled",
                styles["TableCell"],
            ),
        ],
    ]
    t_mod = Table(mod_data, colWidths=[76, 114, 104, 78, 132])
    t_mod.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t_mod)
    story.append(Paragraph("Source: docs/submission/FACT_SHEET.md", styles["Caption"]))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 8: 6. IMPLEMENTATION - KAVACH RULES & AUTOPILOT MODES
    # =========================================================================
    story.append(Paragraph("Kavach Invariants & Autopilot Modes", styles["Heading1"]))
    story.append(
        Paragraph(
            "To safeguard university database integrity, the Kavach safety shield defines explicit invariants. "
            "Each invariant's exact implementation status is audited and classified below:",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(Paragraph("Kavach Invariant Status Matrix", styles["Heading2"]))
    kavach_data = [
        [
            Paragraph("<b>Campus Safety Invariant</b>", styles["TableHead"]),
            Paragraph("<b>Validation Check Logic</b>", styles["TableHead"]),
            Paragraph("<b>Implementation Status</b>", styles["TableHead"]),
            Paragraph(
                "<b>Operational Enforcement Location</b>", styles["TableHead"]
            ),
        ],
        [
            Paragraph("Venue Capacity Limit", styles["TableCellBold"]),
            Paragraph(
                "Validates attendee headcount against room capacity; prevents overbooking",
                styles["TableCell"],
            ),
            Paragraph("<b>on the Autopilot path</b>", styles["TableCellCenter"]),
            Paragraph(
                "kavach.py: verify_capacity(), tool_requisition_campus_resources()",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("Room Collision / Double-Booking", styles["TableCellBold"]),
            Paragraph(
                "Verifies requested hall is unbooked during selected time window",
                styles["TableCell"],
            ),
            Paragraph("<b>on the Autopilot path</b>", styles["TableCellCenter"]),
            Paragraph(
                "kavach.py: verify_room_conflict(), tools.py",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("Valid Operational Time Window", styles["TableCellBold"]),
            Paragraph(
                "Requires start time < end time and rejects historical past dates",
                styles["TableCell"],
            ),
            Paragraph("<b>on the Autopilot path</b>", styles["TableCellCenter"]),
            Paragraph(
                "kavach.py: verify_time_window()", styles["TableCell"]
            ),
        ],
        [
            Paragraph("Resource Inventory Stock Limit", styles["TableCellBold"]),
            Paragraph(
                "Prevents equipment allocation from exceeding physical campus stock",
                styles["TableCell"],
            ),
            Paragraph("<b>on the Autopilot path</b>", styles["TableCellCenter"]),
            Paragraph(
                "kavach.py: verify_resource_stock()", styles["TableCell"]
            ),
        ],
        [
            Paragraph("Notification Blast Radius Limit", styles["TableCellBold"]),
            Paragraph(
                "Caps mass notification recipients per transaction (default 400)",
                styles["TableCell"],
            ),
            Paragraph("<b>on the Autopilot path</b>", styles["TableCellCenter"]),
            Paragraph(
                "kavach.py: verify_blast_radius(), notification_engine.py",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("Speaker Availability Window", styles["TableCellBold"]),
            Paragraph(
                "Detects overlapping assignments for a single speaker",
                styles["TableCell"],
            ),
            Paragraph("<b>unit-tested only</b>", styles["TableCellCenter"]),
            Paragraph(
                "kavach.py: verify_speaker_clash(); enforced by Module 2 CP-SAT",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("Retry & Human Review Escalation", styles["TableCellBold"]),
            Paragraph(
                "Routes failed requests to quarantine queue after 3 retries",
                styles["TableCell"],
            ),
            Paragraph("<b>unit-tested only</b>", styles["TableCellCenter"]),
            Paragraph(
                "kavach.py: KavachRetryEngine; live Autopilot calls agent directly",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("Budget & Cost Constraint", styles["TableCellBold"]),
            Paragraph(
                "Validates allocations against monetary event budget",
                styles["TableCell"],
            ),
            Paragraph("<b>not implemented</b>", styles["TableCellCenter"]),
            Paragraph(
                "Campus items cost 0.0; budget fields removed from user views",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("Payment Gateway & Wallet Ledger", styles["TableCellBold"]),
            Paragraph(
                "Processes commercial monetary payments and disbursements",
                styles["TableCell"],
            ),
            Paragraph("<b>not implemented</b>", styles["TableCellCenter"]),
            Paragraph(
                "No payment gateway or wallet tables exist in schema.sql",
                styles["TableCell"],
            ),
        ],
    ]
    t_kav = Table(kavach_data, colWidths=[114, 156, 104, 130])
    t_kav.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_kav)
    story.append(Paragraph("Source: docs/submission/FACT_SHEET.md", styles["Caption"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("Autopilot Execution Modes & Live-Check Result", styles["Heading2"]))
    story.append(
        Paragraph(
            "- <b>Agent Mode:</b> Uses an autonomous multi-turn tool-calling loop (up to 5 turns). "
            "Supported providers: Google GenAI Gemini (gemini-3.1-flash-lite), Groq, and local Ollama. "
            "The model iteratively calls tools (adaptive_intake, find_free_venues, recommend_from_history, requisition_campus_resources, "
            "dispatch_outbox_notices). Every tool requisition execution is wrapped inside a Kavach transaction savepoint.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Fixed Pipeline (Fallback Mode):</b> When an LLM provider is not configured, encounters quota limits, or returns unexpected "
            "multi-part schemas, run_autopilot_with_fallback immediately transfers control to the deterministic 5-step fixed pipeline. "
            "The fixed pipeline processes intake heuristics, queries available halls, generates logistics bundles, validates through Kavach, "
            "and stages notifications without making network calls.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Live-Check Result:</b> Tested prompt 'Dance performance, 150 students, next Friday 6 PM...'. Turn 1 returned tool call find_free_venues; "
            "Turn 2 returned HTTP 400 (missing thought_signature in functionCall parts), triggering clean fallback to the deterministic fixed pipeline "
            "(mode: 'fixed_fallback'). Both runs completed the booking, allocating Auditorium B in Run a and Main Auditorium A in Run b, staging outbox notices "
            "with status 'sent', and recording 0.0 paid.",
            styles["Body"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 9: 7. OUTCOMES - AUTOMATED TEST SUITE VERIFICATION
    # =========================================================================
    story.append(Paragraph("7. Outcomes", styles["Heading1"]))
    story.append(
        Paragraph(
            "System verification is established through three independent empirical methodologies: "
            "automated test suite execution, an offline 50-scenario benchmark, and live LLM/Agent provider checks.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(Paragraph("Automated Test Suite Verification", styles["Heading2"]))
    story.append(
        Paragraph(
            "The automated test suite was executed offline using Python 3.13.16 on Windows with PROVIDER unset. "
            "All tests run against isolated temporary SQLite databases with deterministic mocked callers, ensuring complete repeatability without network dependencies.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "<b>Test Execution Summary:</b> 343 passed, 0 failed (1 warning; Python 3.13.16 on Windows). Complete pass rate: 343 of 343 passed.",
            styles["BodyBold"],
        )
    )
    story.append(Spacer(1, 4))

    test_data = [
        [
            Paragraph("<b>Test Directory / Suite</b>", styles["TableHead"]),
            Paragraph("<b>Tests</b>", styles["TableHead"]),
            Paragraph("<b>Focus & Verification Scope</b>", styles["TableHead"]),
            Paragraph("<b>Sample Test Files</b>", styles["TableHead"]),
        ],
        [
            Paragraph("<b>tests/</b><br/>(Top-Level Suite)", styles["TableCellBold"]),
            Paragraph("298", styles["TableCellCenter"]),
            Paragraph(
                "Functional endpoints, auth sessions, RBAC, agent mode, audit fixes, attendee waitlists",
                styles["TableCell"],
            ),
            Paragraph(
                "test_auth.py, test_agent_mode.py, test_attendee_waitlist.py",
                styles["CodeText"],
            ),
        ],
        [
            Paragraph("<b>tests/safety/</b><br/>(Kavach Suite)", styles["TableCellBold"]),
            Paragraph("16", styles["TableCellCenter"]),
            Paragraph(
                "Kavach transactional invariants, savepoint rollbacks, blast radius caps, outbox atomicity",
                styles["TableCell"],
            ),
            Paragraph(
                "test_kavach_capacity_overrun_rollback, test_blast_radius",
                styles["CodeText"],
            ),
        ],
        [
            Paragraph("<b>tests/unit/</b><br/>(Algorithms)", styles["TableCellBold"]),
            Paragraph("14", styles["TableCellCenter"]),
            Paragraph(
                "OR-Tools CP-SAT conflict solver, TF-IDF session recommender, Lexicon feedback analyzer",
                styles["TableCell"],
            ),
            Paragraph(
                "test_conflict_free_scheduling, test_sentiment_analysis",
                styles["CodeText"],
            ),
        ],
        [
            Paragraph("<b>eval/</b><br/>(Module Harness)", styles["TableCellBold"]),
            Paragraph("8", styles["TableCellCenter"]),
            Paragraph(
                "End-to-end evaluation harness verifying Modules 1 through 7 and audit logging",
                styles["TableCell"],
            ),
            Paragraph(
                "test_module_1, test_module_2, ..., test_safety_and_audit",
                styles["CodeText"],
            ),
        ],
        [
            Paragraph("<b>tests/integration/</b><br/>(Workflows)", styles["TableCellBold"]),
            Paragraph("7", styles["TableCellCenter"]),
            Paragraph(
                "Multi-module integration flows, Autopilot lifecycle, catalog discovery, feedback submission",
                styles["TableCell"],
            ),
            Paragraph(
                "test_autopilot_successful_execution, test_page_routes",
                styles["CodeText"],
            ),
        ],
        [
            Paragraph("<b>Total Test Suite</b>", styles["TableCellBold"]),
            Paragraph("<b>343</b>", styles["TableCellCenter"]),
            Paragraph(
                "<b>Complete pass rate across all test suites (0 failures, 0 errors)</b>",
                styles["TableCellBold"],
            ),
            Paragraph("<b>343 of 343 passed</b>", styles["TableCellBold"]),
        ],
    ]
    t_test = Table(test_data, colWidths=[110, 44, 210, 140])
    t_test.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_test)
    story.append(Paragraph("Source: docs/submission/FACT_SHEET.md", styles["Caption"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Test Suite Analysis & Observations", styles["Heading2"]))
    story.append(
        Paragraph(
            "- <b>Offline SQLite Isolation:</b> Every test creates an isolated in-memory or temporary file-based SQLite database seeded with "
            "campus fixtures. Tests run completely decoupled from production database state.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Historical Count Comparison:</b> Earlier checkpoints documented 305 tests; recent security hardening, "
            "attendee waitlist engine tests, and supervisor dashboard inspection suites expanded the passing test count to 343.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Warning Disclosure:</b> 1 warning was emitted: a StarletteDeprecationWarning regarding httpx integration in fastapi.testclient.TestClient.",
            styles["Bullet"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 10: 7. OUTCOMES - OFFLINE BENCHMARK RESULTS
    # =========================================================================
    story.append(Paragraph("Offline Benchmark Evaluation", styles["Heading1"]))
    story.append(
        Paragraph(
            "The offline benchmark used a scripted planner on synthetic data (50 prompts: 35 safety, 15 ambiguous) across "
            "three comparative setups: Setup A (direct actions), Setup B (SQLite constraints only), and Setup C (Kavach agent pipeline). "
            "A scripted rule-based planner replaced the LLM so runs are repeatable and offline; the results measure the safety layer, not LLM quality.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 2))

    story.append(Paragraph("Category x Setup x Stopped_By Breakdown", styles["Heading2"]))
    bench_stop_data = [
        [
            Paragraph("<b>Category</b>", styles["TableHead"]),
            Paragraph("<b>Setup</b>", styles["TableHead"]),
            Paragraph("<b>intake</b>", styles["TableHead"]),
            Paragraph("<b>destructive_filter</b>", styles["TableHead"]),
            Paragraph("<b>kavach</b>", styles["TableHead"]),
            Paragraph("<b>db_constraint</b>", styles["TableHead"]),
            Paragraph("<b>none</b>", styles["TableHead"]),
            Paragraph("<b>Total</b>", styles["TableHead"]),
        ],
        [
            Paragraph("clean", styles["TableCellBold"]),
            Paragraph("setup_a", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
        ],
        [
            Paragraph("clean", styles["TableCellBold"]),
            Paragraph("setup_b", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
        ],
        [
            Paragraph("clean", styles["TableCellBold"]),
            Paragraph("setup_c", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
        ],
        [
            Paragraph("high_conflict", styles["TableCellBold"]),
            Paragraph("setup_a", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
        ],
        [
            Paragraph("high_conflict", styles["TableCellBold"]),
            Paragraph("setup_b", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
        ],
        [
            Paragraph("high_conflict", styles["TableCellBold"]),
            Paragraph("setup_c", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("12", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
        ],
        [
            Paragraph("destructive", styles["TableCellBold"]),
            Paragraph("setup_a", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("2", styles["TableCellCenter"]),
            Paragraph("2", styles["TableCellCenter"]),
        ],
        [
            Paragraph("destructive", styles["TableCellBold"]),
            Paragraph("setup_b", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("1", styles["TableCellCenter"]),
            Paragraph("1", styles["TableCellCenter"]),
            Paragraph("2", styles["TableCellCenter"]),
        ],
        [
            Paragraph("destructive", styles["TableCellBold"]),
            Paragraph("setup_c", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("2", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("2", styles["TableCellCenter"]),
        ],
        [
            Paragraph("bulk", styles["TableCellBold"]),
            Paragraph("setup_a", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
        ],
        [
            Paragraph("bulk", styles["TableCellBold"]),
            Paragraph("setup_b", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
        ],
        [
            Paragraph("bulk", styles["TableCellBold"]),
            Paragraph("setup_c", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
        ],
    ]
    t_bstop = Table(bench_stop_data, colWidths=[80, 54, 52, 90, 52, 76, 50, 50])
    t_bstop.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(t_bstop)
    story.append(Paragraph("Source: eval/benchmark/results.json (scripted planner, synthetic data)", styles["Caption"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("Setup Performance Metrics & Ambiguous Intake Testing", styles["Heading2"]))
    perf_data = [
        [
            Paragraph("<b>Benchmark Setup</b>", styles["TableHead"]),
            Paragraph("<b>Wrong States</b>", styles["TableHead"]),
            Paragraph("<b>Errors Caught</b>", styles["TableHead"]),
            Paragraph("<b>Errors Missed</b>", styles["TableHead"]),
            Paragraph("<b>Valid Blocked</b>", styles["TableHead"]),
            Paragraph("<b>Retries</b>", styles["TableHead"]),
        ],
        [
            Paragraph("Setup A (Direct Planned Actions)", styles["TableCellBold"]),
            Paragraph("20", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("20", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
        ],
        [
            Paragraph("Setup B (SQLite Constraints Only)", styles["TableCellBold"]),
            Paragraph("4", styles["TableCellCenter"]),
            Paragraph("16", styles["TableCellCenter"]),
            Paragraph("4", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
        ],
        [
            Paragraph("Setup C (Kavach Agent Pipeline)", styles["TableCellBold"]),
            Paragraph("3", styles["TableCellCenter"]),
            Paragraph("17", styles["TableCellCenter"]),
            Paragraph("3", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
        ],
    ]
    t_perf = Table(perf_data, colWidths=[184, 64, 64, 64, 64, 64])
    t_perf.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t_perf)
    story.append(Paragraph("Source: eval/benchmark/results.json (scripted planner, synthetic data)", styles["Caption"]))
    story.append(Spacer(1, 3))

    intake_data = [
        [
            Paragraph("<b>Category</b>", styles["TableHead"]),
            Paragraph("<b>Prompts</b>", styles["TableHead"]),
            Paragraph("<b>Clarified</b>", styles["TableHead"]),
            Paragraph("<b>intake</b>", styles["TableHead"]),
            Paragraph("<b>destructive_filter</b>", styles["TableHead"]),
            Paragraph("<b>kavach</b>", styles["TableHead"]),
            Paragraph("<b>none</b>", styles["TableHead"]),
            Paragraph("<b>product</b>", styles["TableHead"]),
            Paragraph("<b>harness</b>", styles["TableHead"]),
        ],
        [
            Paragraph("ambiguous", styles["TableCellBold"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("0", styles["TableCellCenter"]),
            Paragraph("15", styles["TableCellCenter"]),
        ],
    ]
    t_intake = Table(intake_data, colWidths=[70, 50, 54, 48, 86, 50, 46, 50, 50])
    t_intake.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(t_intake)
    story.append(Paragraph("Source: eval/benchmark/results.json (scripted planner, synthetic data)", styles["Caption"]))
    story.append(Spacer(1, 3))

    story.append(Paragraph("Benchmark Findings & Interpretation", styles["Heading2"]))
    story.append(
        Paragraph(
            "- <b>Clean Requests (15):</b> All three setups committed 15 of 15 requests; Setup C experienced 0 false blocks.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>High-Conflict Prompts & Stops Breakdown:</b> Setup B stopped 15 of 15 high-conflict prompts and Setup C stopped 12 of 15. "
            "Setup C's extra stops come from the 3 bulk-write prompts (write limit) and the destructive filter. "
            "Setup C's 17 total stops are classified as: 15 by Kavach rules, 1 by the application's destructive filter, and 1 by the benchmark's own filter.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Missed Requests Disclosure:</b> Setup C missed 3 speaker-clash requests because the agent's requisition tool carries no speaker assignment, "
            "so the speaker rule is not on that path. Setup B missed 3 bulk-write requests and 1 DROP TABLE.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Interpretation:</b> Plain SQL constraints stop almost as many invalid bookings as Kavach on this benchmark (16 vs 17 of 20). "
            "Kavach's measured additions are the per-request write limit and the destructive-request pre-filter; transactional rollback with an audit log, "
            "and notices written only after the booking commits, were not separately measured.",
            styles["Bullet"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 11: 7. OUTCOMES - LIVE PROVIDER CHECKS
    # =========================================================================
    story.append(Paragraph("Empirical Live Provider Checks", styles["Heading1"]))
    story.append(
        Paragraph(
            "Live provider checks were conducted on 11-11-2026 under strictly bounded call budgets to empirically verify "
            "connectivity, tool-calling response structures, Q&A consistency, and fallback behaviors.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(Paragraph("Live LLM Connectivity Verification (LIVE_LLM_CHECK.md)", styles["Heading2"]))
    story.append(
        Paragraph(
            "- <b>Execution Context:</b> Evaluated on 11-11-2026 using Google GenAI SDK (google-genai==2.34.0). Provider: gemini, model: gemini-3.1-flash-lite. Provider call budget: 9 of 15 calls used. Halted on 429/quota/timeout: No.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Provider Ping Test:</b> 'Say OK' with empty tools returned 'OK' (5 tokens).",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Provider Model Listing:</b> Client query returned 62 available models, including 27 containing 'flash', confirming active availability of gemini-3.1-flash-lite.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Tool-Calling Ping:</b> Executed call_llm with dummy tool get_venue_status. Returned structured tool call for get_venue_status(venue_name='Main Auditorium A') (98 tokens).",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Participant Q&A Consistency Check:</b> 3 questions asked twice; answers identical on repeat, and unanswerable questions were declined:",
            styles["Bullet"],
        )
    )
    qna_data = [
        [
            Paragraph("<b>Question Prompt</b>", styles["TableHead"]),
            Paragraph("<b>Call 1 Response</b>", styles["TableHead"]),
            Paragraph("<b>Call 2 Response</b>", styles["TableHead"]),
            Paragraph("<b>Fact Match</b>", styles["TableHead"]),
        ],
        [
            Paragraph("Where can I park my car?", styles["TableCellBold"]),
            Paragraph(
                "Declined ungrounded info; directed to security",
                styles["TableCell"],
            ),
            Paragraph(
                "Declined ungrounded info; directed to security",
                styles["TableCell"],
            ),
            Paragraph("Matched", styles["TableCellCenter"]),
        ],
        [
            Paragraph(
                "Robotics workshop kis hall mein hai?", styles["TableCellBold"]
            ),
            Paragraph(
                "Stated no Robotics workshop in schedule",
                styles["TableCell"],
            ),
            Paragraph(
                "Stated no Robotics workshop in schedule",
                styles["TableCell"],
            ),
            Paragraph("Matched", styles["TableCellCenter"]),
        ],
        [
            Paragraph("Keynote kitne baje hai?", styles["TableCellBold"]),
            Paragraph(
                "Confirmed Opening Keynote in Main Auditorium A",
                styles["TableCell"],
            ),
            Paragraph(
                "Confirmed Opening Keynote in Main Auditorium A",
                styles["TableCell"],
            ),
            Paragraph("Matched", styles["TableCellCenter"]),
        ],
    ]
    t_qna = Table(qna_data, colWidths=[130, 160, 160, 54])
    t_qna.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_qna)
    story.append(Paragraph("Source: docs/submission/FACT_SHEET.md", styles["Caption"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("Live Agent-Mode Verification (LIVE_AGENT_CHECK.md)", styles["Heading2"]))
    story.append(
        Paragraph(
            "- <b>Execution Context:</b> Evaluated on 11-11-2026 with PROVIDER=gemini, model gemini-3.1-flash-lite, and TEST_CONSOLE=0. "
            "Provider call budget: 4 of 10 calls used across two sequential runs in a seeded temporary database. Halted on 429/quota/timeout: No.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Run (a) & Run (b) Execution:</b> Tested prompt 'Dance performance, 150 students, next Friday 6 PM...'. Turn 1 returned tool call find_free_venues. "
            "Turn 2 encountered HTTP 400 (missing thought_signature in functionCall parts), triggering clean fallback to the deterministic fixed pipeline "
            "(mode: 'fixed_fallback'), allocating Auditorium B in Run a and Main Auditorium A in Run b, staging outbox notices with status 'sent', and recording 0.0 paid.",
            styles["Bullet"],
        )
    )
    story.append(
        Paragraph(
            "- <b>Empirical Agent Finding:</b> In live testing, agent mode falls back to the deterministic pipeline upon multi-tool schema errors, "
            "which completed the booking.",
            styles["Bullet"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 12: 8. LIMITATIONS AND FUTURE SCOPE
    # =========================================================================
    story.append(Paragraph("8. Limitations & Future Scope", styles["Heading1"]))
    story.append(
        Paragraph(
            "In adherence to rigorous engineering disclosure, all verified limitations and architectural boundaries "
            "are documented below directly from the submission review:",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(Paragraph("Documented Technical Limitations", styles["Heading2"]))
    limitations_list = [
        (
            "1. Scripted Planner & Synthetic Data",
            "Benchmark used a scripted planner, not an LLM; data is synthetic; n is small (35 safety + 15 intake prompts), so no percentages or significance claims.",
        ),
        (
            "2. Baseline Authoring",
            "One developer (with AI coding tools) wrote prompts, rules, checker and baselines; Setup B was extended after seeing its failures; no independent review.",
        ),
        (
            "3. Rule Scope & Unexercised Queues",
            "Kavach only catches rules that are coded: speaker clash is not on the agent path; the per-request write limit blocks legitimate bookings with many resource types; retries and the human-review queue were not exercised (0 retries).",
        ),
        (
            "4. Internal Cost Model & Absence of Payment",
            "No cost model: halls and equipment are internal campus resources, so budget limits, cost-based selection and payment are not implemented (future scope).",
        ),
        (
            "5. Destructive Request Filtering",
            "Destructive tests exercise a regex pre-filter only (n=2); the agent has no delete tool.",
        ),
        (
            "6. Unverified Components Offline",
            "Latency is not reported. Voice input and SMTP email were not verified.",
        ),
    ]
    for l_title, l_desc in limitations_list:
        story.append(
            Paragraph(
                f"- <b>{l_title}:</b> {l_desc}",
                styles["Bullet"],
            )
        )
    story.append(Spacer(1, 8))

    story.append(Paragraph("Future Architectural Scope", styles["Heading2"]))
    future_scope = [
        (
            "Runtime Speaker Clash Integration",
            "Wire verify_speaker_clash directly into tool_requisition_campus_resources so that single-turn agent allocations enforce speaker schedule limits alongside the batch solver.",
        ),
        (
            "Dynamic Single-Turn Solver Invocations",
            "Expose the Google OR-Tools CP-SAT scheduler as a callable agent tool, allowing multi-turn agents to dynamically solve timetable conflicts during conversational replanning.",
        ),
        (
            "Production SMTP Transmission & Webhook Bridges",
            "Incorporate background worker processes with verified SMTP credentials and campus webhook integrations to dispatch staged outbox notices across external networks.",
        ),
        (
            "Enterprise Concurrency Hardening",
            "Migrate from embedded single-writer SQLite storage to PostgreSQL with row-level locking to support high-concurrency student registration spikes.",
        ),
    ]
    for f_title, f_desc in future_scope:
        story.append(
            Paragraph(
                f"- <b>{f_title}:</b> {f_desc}",
                styles["Bullet"],
            )
        )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 13: 9. SDG ALIGNMENT
    # =========================================================================
    story.append(Paragraph("9. SDG Alignment", styles["Heading1"]))
    story.append(
        Paragraph(
            "AgenticLiner aligns directly with United Nations Sustainable Development Goals (SDGs), focusing on institutional digital "
            "infrastructure, responsible resource utilization, and quality technical education.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            "Primary Alignment: SDG 9 — Industry, Innovation, and Infrastructure",
            styles["Heading2"],
        )
    )
    story.append(
        Paragraph(
            "<b>Building Resilient, Verifiable Digital Infrastructure:</b><br/>"
            "Universities require dependable operational software to coordinate complex academic, technical, and extracurricular programs. "
            "AgenticLiner upgrades fragile, paper-based campus logistics into a modern, verifiable digital platform. "
            "By implementing the Kavach safety layer, where every Autopilot booking runs inside a database savepoint that is rolled back if a rule fails, and notices are written only after the booking commits, the platform establishes an open architecture for safe autonomous agent integration. "
            "Furthermore, Module 7's participation certificates with a SHA-256 hash recorded in the database and checked on the verify page (a hash, not a digital signature) and QR verification provide tamper-evident credentials without reliance on proprietary external vendor subscriptions.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "Contributing Alignment (Not Measured): SDG 12 — Responsible Consumption and Production",
            styles["Heading2"],
        )
    )
    story.append(
        Paragraph(
            "<b>Aims to reduce over-requisitioning (not measured across university operations):</b><br/>"
            "Campus events frequently suffer from inefficient resource requisitioning: over-ordering of catering packs, unneeded audio/visual equipment "
            "sitting idle, and redundant stage lighting consuming campus electrical grids. "
            "AgenticLiner's Module 3 employs data-driven historical patterns and Ridge regression models to recommend equipment allocations proportional "
            "to verified attendee headcount. Kavach's strict inventory stock limits and Attendee Management capacity caps limit over-requisitioning within a booking; the effect on waste was not measured.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "Contributing Alignment (Not Measured): SDG 4 — Quality Education",
            styles["Heading2"],
        )
    )
    story.append(
        Paragraph(
            "<b>Facilitates access to practical academic events and workshops (not measured):</b><br/>"
            "Extracurricular student hackathons, coding workshops, and guest lectures represent vital practical learning avenues for engineering students. "
            "AgenticLiner facilitates access to these educational opportunities through Module 4's personalized session recommendations, "
            "matching student academic interests to relevant workshops without timetable clashes. "
            "Moreover, the platform supports equitable access through waitlist transitions on cancellations and issues verifiable skill certificates "
            "that validate practical student participation.",
            styles["Body"],
        )
    )
    story.append(PageBreak())

    # =========================================================================
    # PAGE 14: 10. TEAM & CONTRIBUTIONS
    # =========================================================================
    story.append(Paragraph("10. Team", styles["Heading1"]))
    story.append(
        Paragraph(
            "AgenticLiner was developed by Team <b>OPEN.OUTLIERS</b> for the SparkX 3.0 Innovation Challenge at Galgotias University. "
            "Team member roles and contributions are documented below directly from TEAM.md:",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    team_members = [
        (
            "Himanshu Gupta",
            "Team Lead",
            "B.Tech AIML, School of Artificial Intelligence",
            "Defined the problem, scope and name; chose Challenge 1 and prepared the idea submission, the project brief and a build plan with review gates. "
            "Designed the architecture and the safety-layer concept (rule checks, savepoint rollback, notices written only after the booking commits, audit log). "
            "Directed AI coding assistants (Antigravity), which wrote most of the source code, and reviewed the result: explained and checked the safety layer, "
            "agent mode and workflow service, carried out security hardening and added a localhost-only test console. Designed and ran the evaluation: "
            "automated test suite, an independent benchmark checker, a three-setup benchmark, live LLM checks and a fresh-clone release check. "
            "Prepared the README, project report, presentation and demo video.",
        ),
        (
            "Diya Varshney",
            "Member 2",
            "B.Sc CS (Data Science), School of Computer Applications and Technology",
            "Report few bugs to the lead",
        ),
        (
            "Ashish Kumar Singh",
            "Member 3",
            "B.Tech AIML",
            "independent testing and reports to the lead",
        ),
    ]

    for name, role, dept, contrib in team_members:
        member_table_data = [
            [
                Paragraph(f"<b>{name}</b> — {role}", styles["TableCellBold"]),
                Paragraph(f"<i>{dept}</i>", styles["TableCell"]),
            ],
            [
                Paragraph(
                    f"<b>Contribution:</b> {contrib}",
                    styles["TableCell"],
                ),
                "",
            ],
        ]
        t_member = Table(member_table_data, colWidths=[360, 144])
        t_member.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 1), (1, 1)),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(t_member)
        story.append(Spacer(1, 6))


    story.append(PageBreak())

    # =========================================================================
    # PAGE 15: APPENDIX A: HOW TO RUN
    # =========================================================================
    story.append(Paragraph("Appendix A: How to Run", styles["Heading1"]))
    story.append(
        Paragraph(
            "This reproduction guide details the step-by-step setup and execution instructions verified during the clean-clone release check. "
            "The platform operates offline by default without requiring external API keys.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 4))

    run_steps = [
        (
            "Step 1: Clone Repository & Navigate to Directory",
            "git clone https://github.com/open-himanshu/AgenticLiner.git\n"
            "cd AgenticLiner",
        ),
        (
            "Step 2: Create and Activate Virtual Environment",
            "python -m venv .venv\n"
            "# Windows (PowerShell): .\\.venv\\Scripts\\Activate.ps1\n"
            "# macOS / Linux (bash): source .venv/bin/activate",
        ),
        (
            "Step 3: Install Pinned Dependencies",
            "# Install pinned dependencies (python -m pip avoids launcher blocks)\n"
            "python -m pip install -r requirements.txt",
        ),
        (
            "Step 4: Copy Default Environment Template (Offline Mode)",
            "# Windows: copy .env.example .env\n"
            "# macOS / Linux: cp .env.example .env",
        ),
        (
            "Step 5: Initialize Database Tables & Seed Demo Campus Inventory",
            "python -m backend.core.database.init_db --seed-demo\n"
            "python backend/services/seed_users.py",
        ),
        (
            "Step 6: Start Application Server",
            "python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload\n"
            "# Access http://127.0.0.1:8000 in your browser\n"
            "# Login: seed_users.py prints generated passwords once; for local review set TEST_CONSOLE=1 and open /dev (admin / admin; localhost only; never enable it for public use).",
        ),
        (
            "Step 7: Execute Complete Test Suite Offline (343 tests)",
            "python -m pytest -q",
        ),
    ]

    for s_title, s_code in run_steps:
        s_table_data = [
            [Paragraph(f"<b>{s_title}</b>", styles["TableCellBold"])],
            [Paragraph(s_code.replace("\n", "<br/>"), styles["CodeText"])],
        ]
        t_step = Table(s_table_data, colWidths=[504])
        t_step.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#fafafa")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t_step)
        story.append(Spacer(1, 3))
    story.append(PageBreak())

    # =========================================================================
    # PAGES 16 to 22: APPENDIX B: SCREENSHOTS, CAPTIONED (14 images, 2 per page)
    # =========================================================================
    screenshot_entries = [
        # Page 16
        (
            "login.png",
            "Public Authentication Portal",
            "Figure B.1: /login — Campus authentication portal with Google sign-in and email authentication.",
        ),
        (
            "autopilot.png",
            "Autopilot Agentic Booking Engine",
            "Figure B.2: /autopilot — Autopilot committed 5-step booking in Auditorium B with staged outbox notices.",
        ),
        # Page 17
        (
            "autopilot_rejected.png",
            "Kavach Invariant Safety Rejection",
            "Figure B.3: /autopilot — Kavach safety layer rejection when requested headcount exceeds campus venue capacity.",
        ),
        (
            "planner.png",
            "Event Intake & Logistics Requisition",
            "Figure B.4: /organiser/planner — Module 1 intake form, campus inventory catalog, and category presets.",
        ),
        # Page 18
        (
            "schedule.png",
            "Timetable Scheduler & Conflict Solver",
            "Figure B.5: /schedule — Module 2 Google OR-Tools CP-SAT timetable solver with OPTIMAL status and session blocks.",
        ),
        (
            "attendees.png",
            "Attendee Management & Waitlist Engine",
            "Figure B.6: /attendees — Attendee roster table, confirmed/checked-in counters, and waitlist transitions.",
        ),
        # Page 19
        (
            "notices.png",
            "Outbox Notification Center",
            "Figure B.7: /notices — Transactional outbox dashboard showing staged notifications and dispatch controls.",
        ),
        (
            "organiser.png",
            "Student Club Organiser Dashboard",
            "Figure B.8: /organiser — Organiser dashboard overview with active events and quick AI planning bar.",
        ),
        # Page 20
        (
            "supervisor.png",
            "University Supervisor Dashboard",
            "Figure B.9: /supervisor — Dean Office executive oversight, event approvals, and audit trail link.",
        ),
        (
            "analytics.png",
            "Feedback Intelligence & Credentials",
            "Figure B.10: /analytics — Gate turnout, Lexicon + Hinglish sentiment distribution bar, feedback theme tags, and certificates.",
        ),
        # Page 21
        (
            "data_manager.png",
            "Campus Inventory & Catalog Manager",
            "Figure B.11: /data-manager — Master catalog inventory tracking 7 venues, 13 equipment items, and 5 guest speakers.",
        ),
        (
            "register.png",
            "Campus Event Registration Portal",
            "Figure B.12: /register — Student event registration portal with event dropdown and branch selectors.",
        ),
        # Page 22
        (
            "participant.png",
            "Campus Event Assistant (Participant Q&A)",
            "Figure B.13: /participant — Student digital QR pass and grounded assistant answering keynote timing query.",
        ),
        (
            "certificate_verify.png",
            "Digital Credential Verification Portal",
            "Figure B.14: /verify — Verified digital credential page for CERT-2026-13BF5E10 with QR code and tamper-evident SHA-256 hash.",
        ),
    ]

    for idx, item in enumerate(screenshot_entries):
        fn, title, caption_text = item
        img_path = img_map.get(fn)

        story.append(Paragraph(f"<b>Screenshot: {title}</b>", styles["Heading2"]))
        if img_path and img_path.exists():
            story.append(RLImage(str(img_path), width=480, height=185))

        story.append(Paragraph(f"{caption_text} (Source: docs/screenshots/INDEX.md)", styles["Caption"]))
        story.append(Spacer(1, 4))

        if idx % 2 == 1:
            story.append(PageBreak())

    # =========================================================================
    # PAGES 23 & 24: APPENDIX C: API ROUTES
    # =========================================================================
    story.append(Paragraph("Appendix C: API Routes", styles["Heading1"]))
    story.append(
        Paragraph(
            "The platform registers 70 total route endpoints (65 unique path/method combinations) in `app.routes` "
            "across 25 page views and 40+ REST endpoints. The route catalog is structured across application view routes and operational REST API endpoints:",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 3))

    story.append(Paragraph("Application View Routes (HTML Interface Pages)", styles["Heading2"]))
    view_routes = [
        [
            Paragraph("<b>HTTP Method</b>", styles["TableHead"]),
            Paragraph("<b>Path Route</b>", styles["TableHead"]),
            Paragraph("<b>Target Persona / Authorized Role</b>", styles["TableHead"]),
            Paragraph("<b>Page Purpose & Rendered View</b>", styles["TableHead"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/", styles["CodeText"]),
            Paragraph("Public (All users)", styles["TableCell"]),
            Paragraph("Root entrypoint; redirects authenticated users to role dashboard", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/login", styles["CodeText"]),
            Paragraph("Public (Unauthenticated)", styles["TableCell"]),
            Paragraph("User authentication portal with campus email and Google sign-in", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/login", styles["CodeText"]),
            Paragraph("Public (Unauthenticated)", styles["TableCell"]),
            Paragraph("Form authentication endpoint validating PBKDF2 password hashes", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/logout", styles["CodeText"]),
            Paragraph("Authenticated (All roles)", styles["TableCell"]),
            Paragraph("Session invalidation endpoint clearing session cookies", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/register", styles["CodeText"]),
            Paragraph("Public / Participant", styles["TableCell"]),
            Paragraph("Student event registration form with capacity and interest capture", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/autopilot", styles["CodeText"]),
            Paragraph("Organiser, Supervisor", styles["TableCell"]),
            Paragraph("Autonomous Autopilot natural language booking engine studio", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/organiser", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Student club organiser primary event management dashboard", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/organiser/planner", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Module 1 event intake brief parser and logistics requisition studio", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/schedule", styles["CodeText"]),
            Paragraph("Organiser, Supervisor", styles["TableCell"]),
            Paragraph("Module 2 Google OR-Tools CP-SAT conflict solver timetable portal", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/attendees", styles["CodeText"]),
            Paragraph("Organiser, Supervisor", styles["TableCell"]),
            Paragraph("Attendee management roster, waitlist transitions, and check-in", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/notices", styles["CodeText"]),
            Paragraph("Organiser, Supervisor", styles["TableCell"]),
            Paragraph("Transactional outbox monitor and broadcast announcement composer", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/analytics", styles["CodeText"]),
            Paragraph("Supervisor, Organiser", styles["TableCell"]),
            Paragraph("Module 6 & 7 feedback intelligence and certificate issuance analytics", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/participant", styles["CodeText"]),
            Paragraph("Participant", styles["TableCell"]),
            Paragraph("Student event hub with Module 5 grounded Q&A conversational assistant", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/data-manager", styles["CodeText"]),
            Paragraph("Data Manager", styles["TableCell"]),
            Paragraph("Campus inventory and catalog management console with CSV sync", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/supervisor", styles["CodeText"]),
            Paragraph("Supervisor (Dean)", styles["TableCell"]),
            Paragraph("University supervisor dashboard for event approvals and oversight", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/settings", styles["CodeText"]),
            Paragraph("Authenticated (All roles)", styles["TableCell"]),
            Paragraph("User profile preferences and secure password change interface", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/dev/login", styles["CodeText"]),
            Paragraph("Localhost Developer Only", styles["TableCell"]),
            Paragraph("Development test console login (active when TEST_CONSOLE=1)", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/dev", styles["CodeText"]),
            Paragraph("Localhost Developer Only", styles["TableCell"]),
            Paragraph("Development console for instant role switching and test seeding", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/verify-certificate", styles["CodeText"]),
            Paragraph("Public (All users)", styles["TableCell"]),
            Paragraph("Online certificate verification portal validating SHA-256 hashes", styles["TableCell"]),
        ],
    ]
    t_vroutes = Table(view_routes, colWidths=[65, 120, 135, 184])
    t_vroutes.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_vroutes)
    story.append(Paragraph("Source: docs/submission/FACT_SHEET.md", styles["Caption"]))
    story.append(PageBreak())

    story.append(Paragraph("Operational REST API Endpoints", styles["Heading1"]))
    story.append(
        Paragraph(
            "REST API endpoints provide programmatic access to platform services, planning tools, and safety checks. "
            "The Autopilot booking and resource requisition path runs inside a Kavach savepoint; other writes (registration, feedback, catalog edits) use ordinary database transactions.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 3))

    api_routes = [
        [
            Paragraph("<b>HTTP Method</b>", styles["TableHead"]),
            Paragraph("<b>Endpoint Path</b>", styles["TableHead"]),
            Paragraph("<b>Authorized Role</b>", styles["TableHead"]),
            Paragraph("<b>Operation Description & Underlying Module</b>", styles["TableHead"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/autopilot/run", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Executes Autopilot Agent mode with fallback to 5-step fixed pipeline", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/api/autopilot/memory", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Retrieves persistent organiser preferences and memory entries", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/autopilot/memory/reset", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Resets persistent organiser memory table entries", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/intake/parse", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Module 1: Rule-based entity extraction and clarification generation", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/schedule/solve", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Module 2: Solves timetable using Google OR-Tools CP-SAT constraint solver", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/resources/estimate", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Module 3: Generates logistics bundle recommendations from event size", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/participant/recommend", styles["CodeText"]),
            Paragraph("Participant", styles["TableCell"]),
            Paragraph("Module 4: Computes personalized session timetable via TF-IDF similarity", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/assistant/ask", styles["CodeText"]),
            Paragraph("Participant", styles["TableCell"]),
            Paragraph("Module 5: Answers attendee queries strictly using confirmed database context", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/feedback/submit", styles["CodeText"]),
            Paragraph("Participant", styles["TableCell"]),
            Paragraph("Module 6: Submits review; evaluates sentiment polarity and 4 theme tags", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/certificates/generate", styles["CodeText"]),
            Paragraph("Supervisor", styles["TableCell"]),
            Paragraph("Module 7: Generates tamper-evident SHA-256 PDF certificate with QR code", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/events/register", styles["CodeText"]),
            Paragraph("Participant", styles["TableCell"]),
            Paragraph("Attendee Hub: Registers student; handles automatic waitlist promotion", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/api/events/export-csv", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Exports attendee registration roster as a formatted CSV file", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/outbox/dispatch", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Transactional Outbox: Dispatches held notices to confirmed attendees", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/api/outbox", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Returns list of staged and dispatched outbox notifications", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/api/human-review", styles["CodeText"]),
            Paragraph("Supervisor", styles["TableCell"]),
            Paragraph("Kavach: Lists quarantined requests needing administrative review", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/events/cancel", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Cancels event booking; rolls back state and promotes waitlisted attendees", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/api/events/delete", styles["CodeText"]),
            Paragraph("Organiser", styles["TableCell"]),
            Paragraph("Deletes unconfirmed event draft; validates organiser ownership", styles["TableCell"]),
        ],
        [
            Paragraph("GET", styles["TableCellCenter"]),
            Paragraph("/api/supervisor/events", styles["CodeText"]),
            Paragraph("Supervisor", styles["TableCell"]),
            Paragraph("Returns detailed university-wide event records with booking details", styles["TableCell"]),
        ],
        [
            Paragraph("POST", styles["TableCellCenter"]),
            Paragraph("/dev/switch", styles["CodeText"]),
            Paragraph("Developer Only", styles["TableCell"]),
            Paragraph("Switches active persona cookie instantly in local development", styles["TableCell"]),
        ],
    ]
    t_apiroutes = Table(api_routes, colWidths=[65, 125, 115, 199])
    t_apiroutes.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_apiroutes)
    story.append(Paragraph("Source: docs/submission/FACT_SHEET.md — The Autopilot booking and resource requisition path runs inside a Kavach savepoint; other writes (registration, feedback, catalog edits) use ordinary database transactions.", styles["Caption"]))

    return story


def extract_page_text_from_pdf(pdf_path: Path) -> str:
    """Extract decoded text strictly from Page /Contents objects in ReportLab PDF."""
    with open(pdf_path, "rb") as f:
        data = f.read()

    obj_dict = {}
    for m in re.finditer(
        rb"(\d+)\s+0\s+obj\s*<<(.*?)>>\s*(?:stream\r?\n(.*?)endstream)?\s*endobj",
        data,
        re.DOTALL,
    ):
        oid = int(m.group(1))
        obj_dict[oid] = (m.group(2), m.group(3))

    content_ids = []
    for oid, (h, s) in obj_dict.items():
        if b"/Type /Page" in h or b"/Type/Page" in h:
            cm = re.search(rb"/Contents\s+(\d+)\s+0\s+R", h)
            if cm:
                content_ids.append(int(cm.group(1)))

    extracted_pieces = []
    for cid in content_ids:
        h, s = obj_dict.get(cid, (b"", None))
        if not s:
            continue
        s_clean = s.strip()
        try:
            if not s_clean.endswith(b"~>"):
                s_clean += b"~>"
            decomp = zlib.decompress(base64.a85decode(s_clean, adobe=True))
        except Exception:
            try:
                decomp = zlib.decompress(s_clean)
            except Exception:
                decomp = s_clean

        for bt in re.finditer(rb"BT(.*?)ET", decomp, re.DOTALL):
            block = bt.group(1)
            for m in re.finditer(rb"\((.*?)\)\s*Tj", block):
                raw = m.group(1)
                # Unescape PDF escapes
                raw_clean = re.sub(rb"\\[0-7]{3}", b"", raw)
                raw_clean = (
                    raw_clean.replace(b"\\(", b"(")
                    .replace(b"\\)", b")")
                    .replace(b"\\\\", b"\\")
                )
                extracted_pieces.append(raw_clean.decode("latin1", errors="ignore"))
            for m in re.finditer(rb"\[(.*?)\]\s*TJ", block, re.DOTALL):
                for part in re.findall(rb"\((.*?)\)", m.group(1)):
                    part_clean = re.sub(rb"\\[0-7]{3}", b"", part)
                    part_clean = (
                        part_clean.replace(b"\\(", b"(")
                        .replace(b"\\)", b")")
                        .replace(b"\\\\", b"\\")
                    )
                    extracted_pieces.append(
                        part_clean.decode("latin1", errors="ignore")
                    )

    return " ".join(extracted_pieces)


def get_pdf_page_count(pdf_path: Path) -> int:
    """Extract page count from PDF binary catalog."""
    with open(pdf_path, "rb") as f:
        data = f.read()
    match = re.search(rb"/Type\s*/Pages.*?/Count\s+(\d+)", data, re.DOTALL)
    if match:
        return int(match.group(1))
    pages = re.findall(rb"/Type\s*/Page\b", data)
    return len(pages)


def main():
    print("=" * 60)
    print("Building Project Report PDF for Team OPEN.OUTLIERS...")
    print("=" * 60)

    # 1. Optimize screenshots
    print("Step 1: Downscaling/optimizing screenshots...")
    img_map = optimize_screenshots()
    print(f"  Optimized {len(img_map)} screenshots in {OUT_IMG_DIR}")

    # 2. Build PDF
    print("Step 2: Compiling ReportLab PDF document...")
    styles = make_styles()
    doc = SimpleDocTemplate(
        str(PDF_OUTPUT_PATH),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    story = build_pdf_flowables(styles, img_map)
    doc.build(story)
    print(f"  PDF generated at: {PDF_OUTPUT_PATH}")

    # Also copy to backup filename if needed
    shutil.copy2(PDF_OUTPUT_PATH, PDF_BACKUP_PATH)

    # 3. Analyze PDF
    print("Step 3: Extracting PDF text and running strict validation...")
    extracted_text = extract_page_text_from_pdf(PDF_OUTPUT_PATH)
    file_size_bytes = PDF_OUTPUT_PATH.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)
    page_count = get_pdf_page_count(PDF_OUTPUT_PATH)

    # (a) Check banned words
    banned_found = []
    for bw in BANNED_WORDS:
        pattern = rf"\b{re.escape(bw)}\b" if not bw.endswith("%") else re.escape(bw)
        matches = re.findall(pattern, extracted_text, re.IGNORECASE)
        if matches:
            banned_found.extend(matches)

    # (b) Check "&;" or stray ";" artifacts
    stray_semicolon_artifacts = re.findall(r"&[a-zA-Z0-9]*;", extracted_text)
    and_semicolons = re.findall(r"&;", extracted_text)

    # (c) Check leftover tags starting with "["
    leftover_tags = re.findall(r"\[[^\]]*\]", extracted_text)

    # Allowed numbers check
    allowed_numbers = extract_allowed_numbers()
    pdf_numbers = set(re.findall(r"\b\d+(?:\.\d+)*\b", extracted_text))
    pdf_integers = set(re.findall(r"\d+", extracted_text))
    all_pdf_numbers = pdf_numbers.union(pdf_integers)
    extraneous_numbers = [num for num in sorted(all_pdf_numbers) if num not in allowed_numbers]

    print("\n" + "=" * 60)
    print("PDF VERIFICATION REPORT:")
    print("=" * 60)
    print(f"Output File: {PDF_OUTPUT_PATH}")
    print(f"Page Count: {page_count} pages (Requirement: 20 to 30 pages)")
    print(f"File Size: {file_size_mb:.2f} MB ({file_size_bytes} bytes, Requirement: under 8 MB)")
    print(f"\n(a) Banned words found: {banned_found if banned_found else 'None'}")
    print(f"(b) Stray ';' or '&;' artifacts: {stray_semicolon_artifacts if stray_semicolon_artifacts else 'None'}")
    print(f"(c) Leftover tags starting with '[': {leftover_tags if leftover_tags else 'None'}")
    print(f"(d) Numbers outside source files: {extraneous_numbers if extraneous_numbers else 'None'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
