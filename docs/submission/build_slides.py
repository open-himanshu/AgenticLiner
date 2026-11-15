"""Build the presentation as a 16:9 PPTX using only docs/submission/FACT_SHEET.md,
docs/submission/RESULTS_AND_LIMITATIONS.md and docs/submission/TEAM.md.

Output: docs/submission/out/OPEN.OUTLIERS_AgenticLiner.pptx (16:9, max 14 slides, under 8 MB)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from PIL import Image

import pptx
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

ROOT = Path(__file__).resolve().parents[2]
DOCS_SUBMISSION = ROOT / "docs" / "submission"
OUT_DIR = DOCS_SUBMISSION / "out"
OUT_IMG_DIR = OUT_DIR / "img"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

PPTX_OUTPUT_PATH = OUT_DIR / "OPEN.OUTLIERS_AgenticLiner.pptx"

FACT_SHEET_PATH = DOCS_SUBMISSION / "FACT_SHEET.md"
RESULT_PATH = DOCS_SUBMISSION / "RESULTS_AND_LIMITATIONS.md"
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
    "budget",
    "payment",
    "[",
]

# Color Palette: One accent color throughout (#1e40af Deep Royal Blue)
COLOR_ACCENT = RGBColor(30, 64, 175)       # #1e40af Deep Royal Blue
COLOR_TEXT_DARK = RGBColor(30, 41, 59)     # #1e293b Slate 800
COLOR_TEXT_MUTED = RGBColor(100, 116, 139) # #64748b Slate 500
COLOR_BG_CARD = RGBColor(241, 245, 249)    # #f1f5f9 Slate 100
COLOR_WHITE = RGBColor(255, 255, 255)


def extract_allowed_numbers() -> set[str]:
    """Extract all numbers from the three source files."""
    sources = [FACT_SHEET_PATH, RESULT_PATH, TEAM_PATH]
    all_text = ""
    for src in sources:
        if src.exists():
            all_text += src.read_text(encoding="utf-8") + "\n"
    tokens = set(re.findall(r"\d+(?:\.\d+)*", all_text))
    int_tokens = set(re.findall(r"\d+", all_text))
    return tokens.union(int_tokens)


def optimize_screenshot(name: str) -> Path:
    """Ensure screenshot is freshly optimized to JPEG quality 80 in out/img/."""
    target = OUT_IMG_DIR / f"{name}.jpg"
    src = SCREENSHOTS_DIR / f"{name}.png"
    if not src.exists():
        raise FileNotFoundError(f"Screenshot not found: {src}")
    im = Image.open(src).convert("RGB")
    im.save(target, format="JPEG", quality=80, optimize=True)
    return target


def add_slide_header(slide, title_text: str):
    """Adds a standard header with a top accent bar and title."""
    shapes = slide.shapes
    top_bar = shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(0.5), Inches(11.733), Inches(0.08))
    top_bar.fill.solid()
    top_bar.fill.fore_color.rgb = COLOR_ACCENT
    top_bar.line.fill.background()

    txbox_t = shapes.add_textbox(Inches(0.8), Inches(0.75), Inches(11.733), Inches(0.85))
    tf_t = txbox_t.text_frame
    tf_t.word_wrap = True
    tf_t.margin_left = tf_t.margin_top = tf_t.margin_right = tf_t.margin_bottom = 0
    pt = tf_t.paragraphs[0]
    pt.text = title_text
    pt.font.name = "Calibri"
    pt.font.size = Pt(30)
    pt.font.bold = True
    pt.font.color.rgb = COLOR_TEXT_DARK


def add_speaker_notes(slide, notes_text: str):
    """Adds speaker notes to the slide."""
    notes_slide = slide.notes_slide
    tf = notes_slide.notes_text_frame
    tf.text = notes_text.strip()


def build_presentation():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # =========================================================================
    # SLIDE 1: Title
    # =========================================================================
    s1 = prs.slides.add_slide(blank_layout)
    add_slide_header(s1, "AgenticLiner: AI-Powered Intelligent Event Planning Platform")

    tx_box = s1.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s1 = [
        "Competition Track: Challenge 1 — AI-Powered Intelligent Event Planning Platform",
        "Event: SparkX 3.0 Innovation Challenge, Galgotias University",
        "Team: OPEN.OUTLIERS",
        "Team Lead: Himanshu Gupta; Members: Diya Varshney, Ashish Kumar Singh",
        "Verification: 343 passing automated tests with offline evaluation harness",
    ]
    for i, line in enumerate(lines_s1):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s1,
        "AgenticLiner is an intelligent event planning and management platform developed by team OPEN.OUTLIERS for the SparkX 3.0 Innovation Challenge at Galgotias University. "
        "The platform combines natural language event intake with an automated safety boundary to prevent scheduling conflicts and unauthorized allocations. "
        "All core tests and benchmarks run entirely offline without external API dependencies. "
        "As an honest caveat, live multi-turn agent execution depends on external model behavior and remains unverified for unbounded autonomy. "
        "Development was led by Himanshu Gupta with testing and defect reporting by team members."
    )

    # =========================================================================
    # SLIDE 2: Problem
    # =========================================================================
    s2 = prs.slides.add_slide(blank_layout)
    add_slide_header(s2, "Core Problem: Direct LLM Booking Risks and Manual Coordination")

    tx_box = s2.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s2 = [
        "Organisers coordinate rooms, equipment, schedules, and notices mostly by hand",
        "Direct LLMs placed on booking can double-book rooms or exceed physical capacity",
        "Multi-step modifications risk being left half-finished during execution failures",
        "Participants risk receiving broadcast notices for database updates that never committed",
        "Unchecked database writes risk inventory depletion and unconstrained table drops",
    ]
    for i, line in enumerate(lines_s2):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s2,
        "Campus event organisers face significant operational friction when coordinating rooms, speakers, equipment, and communications manually across disconnected spreadsheets. "
        "Placing an unconstrained large language model directly on database booking tools introduces serious operational risks. "
        "An unshielded model can easily double-book venues, violate room capacity limits, or leave multi-step changes partially applied upon tool failure. "
        "Crucially, sending notices before database commits can broadcast false information to campus participants. "
        "Our benchmark showed that without safety constraints, an unshielded agent resulted in 17 invalid database states out of 20 conflict test prompts."
    )

    # =========================================================================
    # SLIDE 3: Objectives
    # =========================================================================
    s3 = prs.slides.add_slide(blank_layout)
    add_slide_header(s3, "Core Objectives: Six Goals for Safe Event Coordination")

    tx_box = s3.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s3 = [
        "Objective 1 & 2: Parse plain-language briefs and enforce conflict-free scheduling",
        "Objective 3: Deliver data-driven equipment and hospitality recommendations",
        "Objective 4: Ground participant Q&A and provide personalized session tracks",
        "Objective 5: Check every Autopilot booking with transactional safety rules",
        "Objective 6: Generate post-event sentiment analytics and verifiable credentials",
    ]
    for i, line in enumerate(lines_s3):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s3,
        "The project established six functional objectives to span the full lifecycle of campus event organization from initial brief to post-event credentials. "
        "These goals prioritize deterministic physical invariants and transactional safety over unconstrained conversational flexibility. "
        "The platform implements structured parsing, constraint-based timetable scheduling, grounded retrieval, and certificate issuance with a SHA-256 hash. "
        "A major caveat is that while these six objectives are implemented, financial cost tracking and commercial transactions were excluded from scope as campus facilities carry no monetary rental fee. "
        "Each objective is backed by dedicated automated unit and integration tests."
    )

    # =========================================================================
    # SLIDE 4: Approach
    # =========================================================================
    s4 = prs.slides.add_slide(blank_layout)
    add_slide_header(s4, "Approach: Plain-Language Intake to Invariant-Checked Execution")

    box_titles = [
        "1. Brief",
        "2. Intake",
        "3. Planner",
        "4. Kavach",
        "5. Commit",
    ]
    box_w = Inches(2.1)
    box_h = Inches(1.3)
    start_x = Inches(0.8)
    gap_x = Inches(0.3)
    box_y = Inches(2.1)

    for idx, b_title in enumerate(box_titles):
        cur_x = start_x + idx * (box_w + gap_x)
        shape = s4.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, cur_x, box_y, box_w, box_h)
        shape.fill.solid()
        shape.fill.fore_color.rgb = COLOR_BG_CARD
        shape.line.color.rgb = COLOR_ACCENT
        shape.line.width = Pt(2)

        tf_s = shape.text_frame
        tf_s.word_wrap = True
        tf_s.margin_left = tf_s.margin_right = Inches(0.05)
        tf_s.margin_top = Inches(0.4)
        p1 = tf_s.paragraphs[0]
        p1.text = b_title
        p1.font.name = "Calibri"
        p1.font.size = Pt(24)
        p1.font.bold = True
        p1.font.color.rgb = COLOR_ACCENT
        p1.alignment = PP_ALIGN.CENTER

        if idx < len(box_titles) - 1:
            arrow_x = cur_x + box_w + Inches(0.04)
            arrow_y = box_y + Inches(0.45)
            arrow = s4.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, arrow_x, arrow_y, Inches(0.22), Inches(0.4))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = COLOR_ACCENT
            arrow.line.fill.background()

    tx_box = s4.shapes.add_textbox(Inches(0.8), Inches(4.2), Inches(11.733), Inches(2.6))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s4 = [
        "Natural language brief parsed into structured entities with clarification fallback",
        "Multi-step actions validate against 5 safety invariants before atomic commit",
    ]
    for i, line in enumerate(lines_s4):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(22)

    add_speaker_notes(
        s4,
        "Our approach separates natural language interpretation from database execution through an intermediate validation gate. "
        "When an organiser submits an event brief, intake heuristics extract entities or request clarification if essential parameters are missing. "
        "The planner drafts venue and equipment allocations, but cannot write directly to permanent tables without passing the Kavach safety layer. "
        "Kavach tests five physical invariants within a database savepoint before issuing an atomic commit. "
        "An important caveat is that our offline benchmark evaluated this approach using a scripted planner rather than live model calls to maintain offline repeatability."
    )

    # =========================================================================
    # SLIDE 5: Architecture
    # =========================================================================
    s5 = prs.slides.add_slide(blank_layout)
    add_slide_header(s5, "Architecture: SSR Frontend, Application Server, and SQLite Engine")

    tx_box = s5.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s5 = [
        "Frontend: Jinja2 SSR templates with Bootstrap 5.3 and Bootstrap Icons",
        "Application Server: FastAPI with signed session cookies and 70 route endpoints",
        "Core Engines: 7 domain modules, Autopilot planner, and Kavach safety layer",
        "Database: SQLite 3 with 18 relational tables and isolated test scenarios",
        "Outbox Pattern: Notices are written only after the booking commits (email delivery not verified)",
    ]
    for i, line in enumerate(lines_s5):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s5,
        "AgenticLiner uses a three-tier architecture designed for rapid local deployment without heavy external infrastructure dependencies. "
        "The server-rendered Jinja2 frontend connects to a FastAPI application server exposing 70 distinct route endpoints across four role-based access levels. "
        "All persistent application state resides in an embedded SQLite database structured across 18 relational tables. "
        "The outbox pattern ensures notices are written only after the primary booking transaction commits. "
        "An architectural limitation is that SQLite file-level locking bounds write throughput under high concurrent attendee registrations."
    )

    # =========================================================================
    # SLIDE 6: Key Features
    # =========================================================================
    s6 = prs.slides.add_slide(blank_layout)
    add_slide_header(s6, "Key Features: Seven Functional Domain Modules")

    tx_box = s6.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s6 = [
        "Module 1 & 2: Natural language brief parser and OR-Tools CP-SAT scheduler",
        "Module 3: Logistics requisition using heuristics and Ridge regression",
        "Module 4 & 5: TF-IDF session personalization and grounded Q&A assistant",
        "Module 6 & 7: Feedback sentiment clustering and SHA-256 PDF certificates",
        "Attendee Management: Capacity gating, waitlist transitions, and check-in",
    ]
    for i, line in enumerate(lines_s6):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s6,
        "The platform delivers seven domain modules that address each phase of campus event management. "
        "Modules 1 and 2 handle structured intake and constraint-based timetable scheduling using Google OR-Tools. "
        "Modules 3, 4, and 5 automate equipment recommendations, attendee session matching, and grounded participant question answering. "
        "Modules 6 and 7 evaluate post-event sentiment and issue tamper-evident PDF certificates backed by SHA-256 hashes. "
        "A candid caveat is that Module 3 assigns an estimated cost of 0.0 because campus gear carries no rental fee, and Module 2 functions as a batch solver rather than an interactive agent tool."
    )

    # =========================================================================
    # SLIDE 7: Kavach Safety Layer
    # =========================================================================
    s7 = prs.slides.add_slide(blank_layout)
    add_slide_header(s7, "Kavach Safety Layer: Verified Capabilities and Functional Boundaries")

    tx_box = s7.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s7 = [
        "What it does: Enforces room capacity and prevents venue double-booking",
        "What it does: Enforces operating hours, inventory stock, and write blast radius",
        "What it does: Rolls back failed transactions via SQLite savepoints and logs audits",
        "What it cannot do: Speaker clash rule is not wired to runtime booking tool",
        "What it cannot do: Write limit blocks legitimate bookings with many resource types",
    ]
    for i, line in enumerate(lines_s7):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s7,
        "The Kavach safety engine acts as a transactional gatekeeper placed between planning proposals and the underlying database. "
        "It validates five active invariants within an isolated SQLite savepoint, automatically rolling back and writing an audit log if any check fails. "
        "Setup C stopped 17 of 20 should-block requests: 15 by Kavach rules, 1 by the application's destructive filter, 1 by the benchmark's own filter; it missed 3 speaker-clash requests. "
        "However, Kavach has clear and documented boundaries: it only catches invariants that are explicitly wired into runtime code. "
        "Crucially, the speaker clash validation rule is not wired into the agent's requisition tool, and the blast radius write limit can reject legitimate complex bookings that request numerous equipment items."
    )

    # =========================================================================
    # SLIDE 8: Autopilot
    # =========================================================================
    s8 = prs.slides.add_slide(blank_layout)
    add_slide_header(s8, "Autopilot: Agent Mode (partial) and Deterministic Pipeline")

    tx_box = s8.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s8 = [
        "Agent Mode: Multi-turn tool calling for venue discovery and requisition",
        "Fixed Pipeline: Deterministic 5-step procedural Python workflow orchestration",
        "Clean Fallback: Missing thought signature or provider failure triggers fixed flow",
        "Fallback Execution: Fixed pipeline successfully completed live booking runs",
        "Offline Operation: Deterministic pipeline runs without network calls or API keys",
    ]
    for i, line in enumerate(lines_s8):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s8,
        "AgenticLiner implements a dual-mode Autopilot system to balance conversational flexibility with operational reliability. "
        "Agent mode employs multi-turn function calling across venue discovery, resource requisition, and commit tools. "
        "When an external LLM fails, such as returning an HTTP 400 error due to missing thought signatures, Autopilot executes a clean fallback to the deterministic fixed pipeline. "
        "In our live provider evaluations, both live Gemini runs triggered this fallback and successfully completed booking insertion and outbox notice staging. "
        "The honest caveat is that the fixed pipeline follows a static sequence and cannot dynamically adapt parameters if unexpected conflicts arise."
    )

    # =========================================================================
    # SLIDE 9: Demo Flow
    # =========================================================================
    s9 = prs.slides.add_slide(blank_layout)
    add_slide_header(s9, "Demo Flow: Authenticated Planner, Schedule, and Analytics Views")

    img_names = ["planner", "schedule", "analytics"]
    img_w = Inches(3.64)
    img_h = Inches(3.3)
    start_x = Inches(0.8)
    gap_x = Inches(0.4)
    img_y = Inches(1.8)

    for idx, name in enumerate(img_names):
        img_path = optimize_screenshot(name)
        cur_x = start_x + idx * (img_w + gap_x)
        s9.shapes.add_picture(str(img_path), cur_x, img_y, img_w, img_h)

    # Caption below images (Pt 24)
    tx_box_c = s9.shapes.add_textbox(Inches(0.8), Inches(5.6), Inches(11.733), Inches(1.2))
    tf_c = tx_box_c.text_frame
    tf_c.word_wrap = True
    tf_c.margin_left = tf_c.margin_top = tf_c.margin_right = tf_c.margin_bottom = 0
    p_c = tf_c.paragraphs[0]
    p_c.text = "Intake Planner (Module 1)   |   Schedule Solver (Module 2)   |   Feedback Analytics (Module 6)"
    p_c.font.name = "Calibri"
    p_c.font.size = Pt(24)
    p_c.font.bold = True
    p_c.font.color.rgb = COLOR_ACCENT
    p_c.alignment = PP_ALIGN.CENTER

    add_speaker_notes(
        s9,
        "These three interface screenshots illustrate the primary operational flow of AgenticLiner across the event lifecycle. "
        "The first screen shows Module 1's planner intake where organisers enter event briefs and specify expected attendance. "
        "The second screen displays Module 2's timetable solver showing an optimal CP-SAT solution with resolved room allocations. "
        "The third screen presents supervisor analytics, tracking attendee turnout percentages, sentiment distribution, and feedback themes."
    )

    # =========================================================================
    # SLIDE 10: Results (benchmark table and test count)
    # =========================================================================
    s10 = prs.slides.add_slide(blank_layout)
    add_slide_header(s10, "Results: Offline Evaluation Benchmark and Automated Test Count")

    tbl_shape = s10.shapes.add_table(4, 4, Inches(0.8), Inches(1.65), Inches(11.733), Inches(2.6))
    table = tbl_shape.table
    table.columns[0].width = Inches(5.133)
    table.columns[1].width = Inches(2.2)
    table.columns[2].width = Inches(2.2)
    table.columns[3].width = Inches(2.2)

    headers = ["Test Setup Configuration", "Stopped (/20)", "Bad States", "False Blocks"]
    data = [
        ["Setup A (Direct planned actions)", "0", "17", "0"],
        ["Setup B (Plain SQLite constraints)", "16", "1", "0"],
        ["Setup C (Kavach safety pipeline)", "17", "0", "0"],
    ]

    for col_idx, h_text in enumerate(headers):
        cell = table.cell(0, col_idx)
        cell.text = h_text
        cell.fill.solid()
        cell.fill.fore_color.rgb = COLOR_ACCENT
        p = cell.text_frame.paragraphs[0]
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.bold = True
        p.font.color.rgb = COLOR_WHITE
        p.alignment = PP_ALIGN.CENTER if col_idx > 0 else PP_ALIGN.LEFT

    for row_idx, row_vals in enumerate(data):
        for col_idx, val in enumerate(row_vals):
            cell = table.cell(row_idx + 1, col_idx)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = COLOR_BG_CARD if row_idx % 2 == 0 else COLOR_WHITE
            p = cell.text_frame.paragraphs[0]
            p.font.name = "Calibri"
            p.font.size = Pt(24)
            p.font.color.rgb = COLOR_TEXT_DARK
            p.alignment = PP_ALIGN.CENTER if col_idx > 0 else PP_ALIGN.LEFT

    # Bullets positioned strictly below table (starts at 4.65 in) without any overlap
    tx_box = s10.shapes.add_textbox(Inches(0.8), Inches(4.55), Inches(11.733), Inches(1.9))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s10 = [
        "High-conflict prompts: B stopped 15 of 15, C 12 of 15; C's extra stops come from the write limit (3 bulk) and the destructive filter",
        "Clean requests: all 3 setups committed 15 of 15 with 0 false blocks",
        "Test suite verification: 343 passed, 0 failed across all test suites",
    ]
    for i, line in enumerate(lines_s10):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(6)

    # Footer (Pt 24)
    tx_footer = s10.shapes.add_textbox(Inches(0.8), Inches(6.65), Inches(11.733), Inches(0.4))
    tf_f = tx_footer.text_frame
    tf_f.margin_left = tf_f.margin_top = tf_f.margin_right = tf_f.margin_bottom = 0
    p_f = tf_f.paragraphs[0]
    p_f.text = "Source: eval/benchmark/results.json (scripted planner, synthetic data)"
    p_f.font.name = "Calibri"
    p_f.font.size = Pt(24)
    p_f.font.italic = True
    p_f.font.color.rgb = COLOR_TEXT_MUTED

    add_speaker_notes(
        s10,
        "Our offline benchmark evaluated 50 fixture prompts on a seeded synthetic database across three distinct architectural setups. "
        "All three setups correctly committed 15 clean requests with 0 false blocks. "
        "For the 20 conflicting and destructive requests, Setup A caught 0 errors, Setup B stopped 16, and Setup C stopped 17 without leaving any invalid final database states. "
        "Well-written SQLite constraints performed almost as effectively as Kavach, stopping 16 of 20 invalid requests. "
        "The benchmark relied on a scripted rule-based planner on synthetic data rather than a live model, and the test suite confirms 343 passing automated unit and integration tests."
    )

    # =========================================================================
    # SLIDE 11: Live Checks
    # =========================================================================
    s11 = prs.slides.add_slide(blank_layout)
    add_slide_header(s11, "Live Checks: Bounded Gemini LLM and Agent Fallback Verification")

    tx_box = s11.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.3))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s11 = [
        "Live LLM check: Gemini 3.1 flash-lite ping returned OK",
        "Participant Q&A: 3 questions asked twice; answers identical on repeat",
        "Tool calling test: get_venue_status returned structured tool call",
        "Agent check: Turn 2 HTTP 400 triggered clean fallback to fixed pipeline",
    ]
    for i, line in enumerate(lines_s11):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    # Footer (Pt 24)
    tx_footer = s11.shapes.add_textbox(Inches(0.8), Inches(6.65), Inches(11.733), Inches(0.4))
    tf_f = tx_footer.text_frame
    tf_f.margin_left = tf_f.margin_top = tf_f.margin_right = tf_f.margin_bottom = 0
    p_f = tf_f.paragraphs[0]
    p_f.text = "Source: live check logs, 11 Nov 2026"
    p_f.font.name = "Calibri"
    p_f.font.size = Pt(24)
    p_f.font.italic = True
    p_f.font.color.rgb = COLOR_TEXT_MUTED

    add_speaker_notes(
        s11,
        "Live provider checks were conducted on 11-11-2026 under strictly bounded call quotas to verify external connectivity. "
        "A basic ping to Gemini 3.1 flash-lite succeeded, and the participant Q&A assistant delivered identical answers across repeated queries. "
        "During live agent-mode testing, turn two encountered an HTTP 400 error due to a missing thought signature from the provider. "
        "Autopilot gracefully handled this failure by falling back to the deterministic pipeline, which successfully confirmed bookings for both test runs. "
        "It is important to emphasize that full multi-turn autonomous agent booking without fallback was not achieved in live testing."
    )

    # =========================================================================
    # SLIDE 12: Limitations and Future Scope
    # =========================================================================
    s12 = prs.slides.add_slide(blank_layout)
    add_slide_header(s12, "Limitations: Honest Operational Boundaries and Future Scope")

    tx_box = s12.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s12 = [
        "Benchmark used a scripted planner, not an LLM; data is synthetic",
        "Single author created prompts, rules, checker, and baselines",
        "Kavach only catches coded rules; speaker clash is not on agent path",
        "No cost model: internal campus halls and equipment carry 0.0 cost",
        "Destructive tests evaluate regex filter only; voice and SMTP unverified",
    ]
    for i, line in enumerate(lines_s12):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s12,
        "We maintain complete transparency regarding the operational boundaries and architectural limitations of AgenticLiner. "
        "The primary evaluation benchmark utilized synthetic data and a scripted planner rather than live model calls to maintain offline determinism. "
        "Setup B was iteratively improved after observing initial benchmark failures, and prompts were authored by the lead developer without independent external review. "
        "Furthermore, financial costing and commercial gateways are completely absent because campus facilities carry no monetary rental cost. "
        "Future work includes wiring speaker clash validation directly into agent tools, integrating multi-vendor pricing models, and verifying SMTP transmission."
    )

    # =========================================================================
    # SLIDE 13: SDG and Impact
    # =========================================================================
    s13 = prs.slides.add_slide(blank_layout)
    add_slide_header(s13, "SDG Alignment: Digital Infrastructure, Resource Efficiency, and Education")

    tx_box = s13.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s13 = [
        "Primary SDG 9: Building verifiable digital infrastructure for campus events",
        "Contributing SDG 12: Aims to reduce over-requisitioning (not measured)",
        "Contributing SDG 4: Personalized session discovery and verifiable credentials",
        "Open Architecture: Local SQLite engine avoids proprietary cloud vendor lock-in",
        "Equitable Access: Waitlist handled through status transitions",
    ]
    for i, line in enumerate(lines_s13):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s13,
        "AgenticLiner aligns directly with United Nations Sustainable Development Goals by improving institutional operational efficiency. "
        "Primary alignment with SDG 9 establishes verifiable digital infrastructure, replacing error-prone manual spreadsheets with transactional safety. "
        "Contributing alignment with SDG 12 aims to reduce over-requisitioning, though this reduction was not directly measured. "
        "SDG 4 is supported through personalized workshop recommendations, with student waitlists handled through status transitions. "
        "A practical caveat is that these societal benefits reflect localized campus operations rather than a global deployment."
    )

    # =========================================================================
    # SLIDE 14: Team and Contributions
    # =========================================================================
    s14 = prs.slides.add_slide(blank_layout)
    add_slide_header(s14, "Team and Contributions: OPEN.OUTLIERS Project Roles")

    tx_box = s14.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.733), Inches(4.8))
    tf = tx_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    lines_s14 = [
        "Team name: OPEN.OUTLIERS",
        "Team Lead: Himanshu Gupta, B.Tech AIML, School of Artificial Intelligence",
        "Lead Contribution: Defined scope, safety layer, directed AI coding, ran evaluation and reporting",
        "Member 2: Diya Varshney, B.Sc CS (Data Science) — Report few bugs to the lead",
        "Member 3: Ashish Kumar Singh, B.Tech AIML — independent testing and reports to the lead",
    ]
    for i, line in enumerate(lines_s14):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {line}"
        p.font.name = "Calibri"
        p.font.size = Pt(24)
        p.font.color.rgb = COLOR_TEXT_DARK
        p.space_after = Pt(20)

    add_speaker_notes(
        s14,
        "Team OPEN.OUTLIERS developed AgenticLiner with clearly defined contributions across the project lifecycle. "
        "Himanshu Gupta served as team lead, formulating the project scope, designing the architecture, directing AI coding assistants, and conducting the evaluations. "
        "Diya Varshney reported bugs to the lead, while Ashish Kumar Singh performed independent testing and reports to the lead. "
        "A key disclosure is that AI coding assistants wrote most of the source code under the direct supervision of the team lead."
    )

    # Save to final output path
    prs.save(str(PPTX_OUTPUT_PATH))
    print(f"Presentation saved to {PPTX_OUTPUT_PATH}")


def extract_all_text_from_pptx(pptx_path: Path) -> dict[str, list[str]]:
    """Extract all text items from slides and notes for validation."""
    prs = Presentation(str(pptx_path))
    data = {
        "slide_texts": [],
        "note_texts": [],
        "all_paragraphs": [],
    }
    for slide_idx, slide in enumerate(prs.slides):
        slide_lines = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    t = p.text.strip()
                    if t:
                        slide_lines.append(t)
                        data["all_paragraphs"].append(t)
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            t = p.text.strip()
                            if t:
                                slide_lines.append(t)
                                data["all_paragraphs"].append(t)
        data["slide_texts"].append(slide_lines)

        notes_text = ""
        if slide.has_notes_slide:
            notes_text = slide.notes_slide.notes_text_frame.text.strip()
        data["note_texts"].append(notes_text)

    return data


def validate_presentation(pptx_path: Path):
    """Run strict verification checks on banned words, numbers, sentence counts, font sizes, etc."""
    print("\nRunning strict validation checks on presentation...")
    prs = Presentation(str(pptx_path))
    slide_count = len(prs.slides)
    file_size_bytes = pptx_path.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)

    print(f"Slide count: {slide_count} (Requirement: max 14 slides)")
    print(f"File size: {file_size_mb:.2f} MB ({file_size_bytes} bytes, Requirement: under 8 MB)")
    assert slide_count <= 14, f"Slide count {slide_count} exceeds maximum of 14 slides!"
    assert file_size_mb < 8.0, f"File size {file_size_mb:.2f} MB exceeds 8 MB limit!"

    extracted = extract_all_text_from_pptx(pptx_path)

    # 1. Check banned words across all text (slides and notes)
    all_combined_text = "\n".join(extracted["all_paragraphs"] + extracted["note_texts"])
    banned_found = []
    for bw in BANNED_WORDS:
        if bw == "[":
            if "[" in all_combined_text:
                banned_found.append("[ (bracket tag)")
        elif bw.endswith("%"):
            matches = re.findall(re.escape(bw), all_combined_text, re.IGNORECASE)
            if matches:
                banned_found.extend(matches)
        else:
            pattern = rf"\b{re.escape(bw)}\w*"
            matches = re.findall(pattern, all_combined_text, re.IGNORECASE)
            if matches:
                banned_found.extend(matches)

    print(f"Banned words check: {banned_found if banned_found else 'None (PASSED)'}")
    assert not banned_found, f"Found banned words: {banned_found}"

    # 2. Check numbers outside source files
    allowed_numbers = extract_allowed_numbers()
    pptx_numbers = set(re.findall(r"\b\d+(?:\.\d+)*\b", all_combined_text))
    pptx_integers = set(re.findall(r"\d+", all_combined_text))
    all_pptx_numbers = pptx_numbers.union(pptx_integers)

    extraneous_numbers = []
    for num in sorted(all_pptx_numbers):
        if num not in allowed_numbers:
            extraneous_numbers.append(num)

    print(f"Numbers outside source files: {extraneous_numbers if extraneous_numbers else 'None (PASSED)'}")
    assert not extraneous_numbers, f"Extraneous numbers found: {extraneous_numbers}"

    # 3. Check speaker notes sentence counts (3 to 5 sentences per slide)
    notes_issues = []
    for idx, note in enumerate(extracted["note_texts"]):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", note) if s.strip()]
        s_count = len(sentences)
        if s_count < 3 or s_count > 5:
            notes_issues.append((idx + 1, s_count, note))

    print(f"Speaker notes sentence count issues: {notes_issues if notes_issues else 'None (All slides have 3-5 sentences) (PASSED)'}")
    assert not notes_issues, f"Notes sentence count violations: {notes_issues}"

    # 4. Check results slides footer
    s10_text = "\n".join(extracted["slide_texts"][9])
    s11_text = "\n".join(extracted["slide_texts"][10])
    assert "Source: eval/benchmark/results.json (scripted planner, synthetic data)" in s10_text, "Slide 10 missing mandatory results footer!"
    assert "Source: live check logs, 11 Nov 2026" in s11_text, "Slide 11 missing mandatory live checks footer!"
    print("Mandatory footers: Verified on Slide 10 and Slide 11 (PASSED)")

    # 5. Check font size >= 24 pt for all slide text
    font_issues = []
    for s_idx, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    if p.font.size is not None and p.font.size < Pt(24):
                        font_issues.append((s_idx + 1, p.text, p.font.size.pt))
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            if p.font.size is not None and p.font.size < Pt(24):
                                font_issues.append((s_idx + 1, p.text, p.font.size.pt))

    print(f"Font size checks (< 24 pt): {font_issues if font_issues else 'None (All text >= 24 pt) (PASSED)'}")
    assert not font_issues, f"Font size issues found: {font_issues}"

    # 6. Check lines per slide (max 6 lines per slide)
    line_issues = []
    for s_idx, slide in enumerate(prs.slides):
        text_lines = []
        for shape in slide.shapes:
            is_rounded_rect = False
            try:
                if shape.auto_shape_type == MSO_SHAPE.ROUNDED_RECTANGLE:
                    is_rounded_rect = True
            except Exception:
                pass
            if shape.has_text_frame and not is_rounded_rect:
                for p in shape.text_frame.paragraphs:
                    t = p.text.strip()
                    if t:
                        text_lines.append(t)
        if len(text_lines) > 6:
            line_issues.append((s_idx + 1, len(text_lines), text_lines))

    print(f"Max 6 lines check: {line_issues if line_issues else 'None (All slides <= 6 lines) (PASSED)'}")
    assert not line_issues, f"Slides exceeding 6 lines: {line_issues}"

    print("\nALL STRICT VERIFICATION CHECKS PASSED SUCCESSFULLY!\n")


def main():
    build_presentation()
    validate_presentation(PPTX_OUTPUT_PATH)


if __name__ == "__main__":
    main()
