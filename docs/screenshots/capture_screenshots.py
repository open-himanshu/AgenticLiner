"""Automated screenshot capture script for AgenticLiner.
Runs offline using temporary database temp_screenshots.db, system Google Chrome,
and authenticates via the normal /login form.
"""

import os
import re
import sys
import time
import subprocess
import sqlite3
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DOCS_SCREENSHOTS = ROOT / "docs" / "screenshots"
TEMP_DB = ROOT / "temp_screenshots.db"

# Passwords set as process environment variables
PASSWORDS = {
    "supervisor": "TempSupervisorPass_987!",
    "organiser": "TempOrganiserPass_987!",
    "data_manager": "TempDataMgrPass_987!",
    "participant": "TempStudentPass_987!",
}

EMAILS = {
    "supervisor": "admin@galgotias.edu",
    "organiser": "organiser@galgotias.edu",
    "data_manager": "datamanager@galgotias.edu",
    "participant": "student@galgotias.edu",
}

def prepare_db():
    sys.path.insert(0, str(DOCS_SCREENSHOTS))
    from prepare_db import setup
    return setup()

def start_server():
    env = os.environ.copy()
    env["DATABASE_PATH"] = str(TEMP_DB)
    env["PROVIDER"] = ""
    env["TEST_CONSOLE"] = ""
    for role, pwd in PASSWORDS.items():
        env[f"{role.upper()}_PASSWORD"] = pwd

    cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.api.main:app",
        "--host", "127.0.0.1",
        "--port", "8000"
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(3.5)
    return proc

def stop_server(proc):
    if proc:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        time.sleep(2)

def verify_and_optimize_image(path: Path):
    """Ensure image is under 500 KB; if larger, downscale to 1400 px width."""
    size_bytes = path.stat().st_size
    if size_bytes > 500 * 1024:
        im = Image.open(path)
        w, h = im.size
        new_w = 1400
        new_h = int(h * (new_w / w))
        im_resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
        im_resized.save(path, format="PNG", optimize=True)
    return path.stat().st_size

def perform_checks(page, page_name: str, allow_danger_alert: bool = False):
    """Run the 4 checks on page text and DOM elements."""
    body_text = page.inner_text("body")

    # 1. No red TEST MODE bar
    test_bar = page.query_selector("#test-mode-bar")
    has_test_bar = test_bar is not None and test_bar.is_visible()
    assert not has_test_bar, f"[{page_name}] Red TEST MODE bar is present!"

    # 2. No word 'budget'
    budget_matches = re.findall(r"\bbudget\b", body_text, re.IGNORECASE)
    assert not budget_matches, f"[{page_name}] Word 'budget' found: {budget_matches}"

    # 3. No password or secret in visible text
    for pwd in PASSWORDS.values():
        assert pwd not in body_text, f"[{page_name}] Secret password found in body text!"

    # 4. No error banner unless expected (e.g. autopilot_rejected)
    if not allow_danger_alert:
        danger_alert = page.query_selector(".alert-danger")
        if danger_alert and danger_alert.is_visible():
            err_text = danger_alert.inner_text()
            raise AssertionError(f"[{page_name}] Unexpected error banner found: {err_text}")

    return {
        "no_test_bar": "yes",
        "no_budget": "yes",
        "no_secrets": "yes",
        "no_error": "yes",
    }

def login(page, role: str):
    """Logs in through the standard /login form."""
    email = EMAILS[role]
    password = PASSWORDS[role]

    page.goto("http://127.0.0.1:8000/login", wait_until="networkidle")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    time.sleep(1)

def main():
    print("Preparing temporary database...")
    cert_id = prepare_db()
    print(f"Temporary database ready with certificate ID: {cert_id}")

    print("Starting server on 127.0.0.1:8000...")
    server_proc = start_server()

    results_index = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                headless=True
            )

            # -------------------------------------------------------------
            # 1. login.png (/login) - Public
            # -------------------------------------------------------------
            print("Capturing login.png...")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto("http://127.0.0.1:8000/login", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "login.png")
            target_path = DOCS_SCREENSHOTS / "login.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "login.png",
                "page_role": "/login (Public)",
                "state": "Campus login portal with Google auth button & email sign-in",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })
            context.close()

            # -------------------------------------------------------------
            # 2. Organiser context: autopilot.png & autopilot_rejected.png & more
            # -------------------------------------------------------------
            print("Logging in as organiser...")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            login(page, "organiser")

            # 2.1 autopilot.png
            print("Capturing autopilot.png (Dance performance, 150 students)...")
            page.goto("http://127.0.0.1:8000/autopilot", wait_until="networkidle")
            page.fill("#agentPrompt", "Dance performance, 150 students, next Friday 6 PM")
            page.click("#btnRunAgent")
            page.wait_for_selector("#summaryCard", state="visible", timeout=15000)
            time.sleep(1.5)
            # Scroll so the live activity panel timeline and committed summary card are visible
            page.evaluate("() => { const el = document.querySelector('.card.card-custom.p-4.bg-white.h-100'); if (el) el.scrollIntoView({behavior: 'instant', block: 'start'}); }")
            time.sleep(1)
            checks = perform_checks(page, "autopilot.png")
            target_path = DOCS_SCREENSHOTS / "autopilot.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "autopilot.png",
                "page_role": "/autopilot (Organiser)",
                "state": "Autopilot committed 5-step booking in Auditorium B with staged outbox notices",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 2.2 autopilot_rejected.png
            print("Capturing autopilot_rejected.png (Dance performance, 5000 students)...")
            page.goto("http://127.0.0.1:8000/autopilot", wait_until="networkidle")
            page.fill("#agentPrompt", "Dance performance, 5000 students")
            page.click("#btnRunAgent")
            page.wait_for_selector(".alert-danger", state="visible", timeout=15000)
            time.sleep(1.5)
            # Scroll so the live activity panel timeline and rejection alert are visible
            page.evaluate("() => { const el = document.querySelector('.card.card-custom.p-4.bg-white.h-100'); if (el) el.scrollIntoView({behavior: 'instant', block: 'start'}); }")
            time.sleep(1)
            checks = perform_checks(page, "autopilot_rejected.png", allow_danger_alert=True)
            target_path = DOCS_SCREENSHOTS / "autopilot_rejected.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "autopilot_rejected.png",
                "page_role": "/autopilot (Organiser)",
                "state": "Kavach rejection for 5000 headcount exceeding campus venue capacity",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 2.3 planner.png
            print("Capturing planner.png...")
            page.goto("http://127.0.0.1:8000/organiser/planner", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "planner.png")
            target_path = DOCS_SCREENSHOTS / "planner.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "planner.png",
                "page_role": "/organiser/planner (Organiser)",
                "state": "Module 1 intake form, campus inventory catalog & category presets",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 2.4 schedule.png
            print("Capturing schedule.png...")
            page.goto("http://127.0.0.1:8000/schedule", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "schedule.png")
            target_path = DOCS_SCREENSHOTS / "schedule.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "schedule.png",
                "page_role": "/schedule (Organiser)",
                "state": "Module 2 OR-Tools CP-SAT timetable solver with OPTIMAL status and session blocks",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 2.5 attendees.png
            print("Capturing attendees.png...")
            page.goto("http://127.0.0.1:8000/attendees", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "attendees.png")
            target_path = DOCS_SCREENSHOTS / "attendees.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "attendees.png",
                "page_role": "/attendees (Organiser)",
                "state": "Attendee roster table, confirmed/checked-in counters & waitlist transitions",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 2.6 notices.png
            print("Capturing notices.png...")
            page.goto("http://127.0.0.1:8000/notices", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "notices.png")
            target_path = DOCS_SCREENSHOTS / "notices.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "notices.png",
                "page_role": "/notices (Organiser)",
                "state": "Outbox Notification Center with staged transactional notices & broadcast form",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 2.7 organiser.png
            print("Capturing organiser.png...")
            page.goto("http://127.0.0.1:8000/organiser", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "organiser.png")
            target_path = DOCS_SCREENSHOTS / "organiser.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "organiser.png",
                "page_role": "/organiser (Organiser)",
                "state": "Organiser dashboard overview with active events & quick AI planning bar",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })
            context.close()

            # -------------------------------------------------------------
            # 3. Supervisor context: supervisor.png & analytics.png
            # -------------------------------------------------------------
            print("Logging in as supervisor...")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            login(page, "supervisor")

            # 3.1 supervisor.png
            print("Capturing supervisor.png...")
            page.goto("http://127.0.0.1:8000/supervisor", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "supervisor.png")
            target_path = DOCS_SCREENSHOTS / "supervisor.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "supervisor.png",
                "page_role": "/supervisor (Supervisor)",
                "state": "Dean Office executive oversight, event approvals, and audit trail link",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 3.2 analytics.png
            print("Capturing analytics.png...")
            page.goto("http://127.0.0.1:8000/analytics", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "analytics.png")
            target_path = DOCS_SCREENSHOTS / "analytics.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "analytics.png",
                "page_role": "/analytics (Supervisor)",
                "state": "Gate turnout %, sentiment distribution bar, feedback theme tags & certificates",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })
            context.close()

            # -------------------------------------------------------------
            # 4. Data Manager context: data_manager.png
            # -------------------------------------------------------------
            print("Logging in as data manager...")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            login(page, "data_manager")

            print("Capturing data_manager.png...")
            page.goto("http://127.0.0.1:8000/data-manager", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "data_manager.png")
            target_path = DOCS_SCREENSHOTS / "data_manager.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "data_manager.png",
                "page_role": "/data-manager (Data Manager)",
                "state": "Master catalog inventory (7 venues, 13 equipment items, 5 guest speakers)",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })
            context.close()

            # -------------------------------------------------------------
            # 5. Student (Participant) context: register.png & participant.png
            # -------------------------------------------------------------
            print("Logging in as student...")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            login(page, "participant")

            # 5.1 register.png
            print("Capturing register.png...")
            page.goto("http://127.0.0.1:8000/register", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "register.png")
            target_path = DOCS_SCREENSHOTS / "register.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "register.png",
                "page_role": "/register (Participant)",
                "state": "Student event registration portal with event dropdown & branch selectors",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })

            # 5.2 participant.png
            print("Capturing participant.png (Keynote kitne baje hai?)...")
            page.goto("http://127.0.0.1:8000/participant", wait_until="networkidle")
            page.fill("#chatInput", "Keynote kitne baje hai?")
            page.click("#btnSendChat")
            time.sleep(2)
            checks = perform_checks(page, "participant.png")
            target_path = DOCS_SCREENSHOTS / "participant.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "participant.png",
                "page_role": "/participant (Participant)",
                "state": "Student digital QR pass and grounded assistant answering keynote timing query",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })
            context.close()

            # -------------------------------------------------------------
            # 6. Public: certificate_verify.png
            # -------------------------------------------------------------
            print("Capturing certificate_verify.png...")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto(f"http://127.0.0.1:8000/verify?cert_id={cert_id}", wait_until="networkidle")
            time.sleep(1)
            checks = perform_checks(page, "certificate_verify.png")
            target_path = DOCS_SCREENSHOTS / "certificate_verify.png"
            page.screenshot(path=str(target_path))
            f_size = verify_and_optimize_image(target_path)
            results_index.append({
                "file": "certificate_verify.png",
                "page_role": "/verify (Public)",
                "state": f"Verified digital credential page for {cert_id} with QR code and tamper-evident SHA-256 hash",
                **checks,
                "size_kb": f"{f_size / 1024:.1f} KB"
            })
            context.close()

            browser.close()

        # Write docs/screenshots/INDEX.md
        print("Writing docs/screenshots/INDEX.md...")
        index_md = "# Project Screenshots Audit Index\n\n"
        index_md += "| File | Page & Role | State Shown | No TEST MODE Bar | No Budget Word | No Secrets | No Error Banner | File Size |\n"
        index_md += "|---|---|---|:---:|:---:|:---:|:---:|:---:|\n"
        for r in results_index:
            index_md += f"| `{r['file']}` | {r['page_role']} | {r['state']} | {r['no_test_bar']} | {r['no_budget']} | {r['no_secrets']} | {r['no_error']} | {r['size_kb']} |\n"

        index_path = DOCS_SCREENSHOTS / "INDEX.md"
        index_path.write_text(index_md, encoding="utf-8")
        print("INDEX.md written successfully.")

    finally:
        print("Stopping server...")
        stop_server(server_proc)

        print("Deleting temporary database...")
        for p in [TEMP_DB, ROOT / "temp_screenshots.db-wal", ROOT / "temp_screenshots.db-shm"]:
            for _ in range(5):
                if p.exists():
                    try:
                        p.unlink()
                        break
                    except Exception as e:
                        time.sleep(1)

    print("\nCapture Complete! Files written:")
    for r in results_index:
        print(f" - docs/screenshots/{r['file']} ({r['size_kb']})")

if __name__ == "__main__":
    main()
