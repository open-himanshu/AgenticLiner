"""Test Console Router & Security Gate.

Mounted only when TEST_CONSOLE == "1" at application startup.
Guarded by require_test_mode: returns 404 if public tunnel is active,
if TEST_CONSOLE != "1" at request time, or if client is not localhost.
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import itsdangerous
from itsdangerous.exc import BadSignature
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.core.database.connection import fetch_one, get_db
from backend.core.safety.kavach import KavachEngine
from backend.api.auth_routes import set_user_session, ROLE_DASHBOARDS

kavach = KavachEngine()

ALLOWED_ROLES = {"organiser", "supervisor", "data_manager", "participant"}

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"


def is_test_mode_active(request: Request) -> bool:
    """Evaluates whether test console mode is strictly active for this request."""
    if os.getenv("ALLOW_PUBLIC_TUNNEL") == "1":
        return False

    if os.getenv("TEST_CONSOLE") != "1":
        return False

    client_host = request.client.host if request.client else None
    if client_host not in {"127.0.0.1", "::1", "testclient"}:
        return False

    return True


def test_mode_context_processor(request: Request) -> Dict[str, Any]:
    """Exposes require_test_mode logic as template variable test_mode_active."""
    return {"test_mode_active": is_test_mode_active(request)}


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[test_mode_context_processor])


def require_test_mode(request: Request) -> None:
    """Security dependency guarding all /dev routes.

    Returns HTTP 404 (never 403) if:
    1. ALLOW_PUBLIC_TUNNEL == "1"
    2. TEST_CONSOLE != "1" at request time
    3. request.client.host not in {"127.0.0.1", "::1", "testclient"}
    """
    if not is_test_mode_active(request):
        raise HTTPException(status_code=404, detail="Not Found")


# --- In-Memory Rate Limiting for Dev Login ---
_FAILED_ATTEMPTS: dict[str, list[float]] = {}
_LOCKOUTS: dict[str, float] = {}


def reset_rate_limits() -> None:
    """Helper to clear in-memory rate-limit state between tests."""
    _FAILED_ATTEMPTS.clear()
    _LOCKOUTS.clear()


def _check_rate_limit(client_ip: str) -> None:
    now = time.time()
    lockout_until = _LOCKOUTS.get(client_ip, 0.0)
    if now < lockout_until:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please wait 60 seconds."
        )
    if client_ip in _LOCKOUTS:
        del _LOCKOUTS[client_ip]


def _record_failed_attempt(client_ip: str) -> None:
    now = time.time()
    attempts = _FAILED_ATTEMPTS.get(client_ip, [])
    # Sliding window of 60 seconds
    attempts = [t for t in attempts if now - t < 60.0]
    attempts.append(now)
    _FAILED_ATTEMPTS[client_ip] = attempts
    if len(attempts) >= 5:
        _LOCKOUTS[client_ip] = now + 60.0
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please wait 60 seconds."
        )


# --- Cookie Signing Helpers ---
def _get_signer() -> itsdangerous.TimestampSigner:
    from backend.api.main import SECRET_KEY
    return itsdangerous.TimestampSigner(str(SECRET_KEY))


def _sign_cookie_payload(payload: str = "console_authenticated") -> str:
    signer = _get_signer()
    return signer.sign(payload.encode("utf-8")).decode("utf-8")


def _verify_cookie_payload(cookie_val: Optional[str], max_age: int = 8 * 3600) -> bool:
    if not cookie_val:
        return False
    signer = _get_signer()
    try:
        signer.unsign(cookie_val.encode("utf-8"), max_age=max_age)
        return True
    except BadSignature:
        return False


async def _extract_credentials(request: Request) -> Tuple[str, str]:
    content_type = request.headers.get("content-type", "")
    username = ""
    password = ""
    if "application/json" in content_type:
        try:
            body = await request.json()
            username = body.get("username") or body.get("user") or body.get("email") or ""
            password = body.get("password") or ""
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            username = form.get("username") or form.get("user") or form.get("email") or ""
            password = form.get("password") or ""
        except Exception:
            pass
    return str(username), str(password)


router = APIRouter(prefix="/dev", dependencies=[Depends(require_test_mode)])


@router.get("/ping")
async def dev_ping() -> dict[str, str]:
    """Health check for dev test console."""
    return {"status": "ok", "mode": "test_console"}


def render_dev_login_html(error: Optional[str] = None, username: str = "") -> str:
    """Renders styled Bootstrap 5 login page for dev test console."""
    error_html = ""
    if error:
        error_html = f"""
        <div class="alert alert-danger py-2 px-3 small d-flex align-items-center gap-2 mb-3" role="alert">
            <i class="bi bi-exclamation-triangle-fill flex-shrink-0"></i>
            <div><strong>Error:</strong> {error}</div>
        </div>
        """

    safe_username = username.replace('"', '&quot;')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AgenticLiner - Test Console Login</title>
    <!-- Bootstrap 5 CSS via CDN -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
        body {{
            background-color: #0f172a;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .card-dev {{
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
        }}
        .form-control {{
            background-color: #0f172a;
            border-color: #334155;
            color: #f8fafc;
        }}
        .form-control:focus {{
            background-color: #0f172a;
            border-color: #dc3545;
            color: #fff;
            box-shadow: 0 0 0 0.25rem rgba(220, 53, 69, 0.25);
        }}
    </style>
</head>
<body class="p-3">
    <div style="max-width: 440px; width: 100%;">
        <div class="card card-dev">
            <div class="card-body p-4">
                <div class="text-center mb-4">
                    <span class="badge bg-danger text-white px-2 py-1 fw-bold mb-2">DEV / TEST MODE</span>
                    <h3 class="fw-bold text-white mb-1">&#128736;&#65039; Test Console Login</h3>
                    <p class="text-white-50 small mb-0">Local development &amp; persona testing only.</p>
                </div>

                {error_html}

                <div class="alert alert-dark border-secondary py-2 px-3 small text-white-50 mb-3">
                    <div class="d-flex align-items-center justify-content-between mb-1">
                        <span class="fw-semibold text-white">Default Credentials:</span>
                        <button type="button" class="btn btn-sm btn-outline-info py-0 px-2 small" onclick="autoFill()" style="font-size: 0.75rem;">
                            Auto-fill
                        </button>
                    </div>
                    <div>User: <code class="text-info">admin</code> | Pass: <code class="text-info">admin</code></div>
                </div>

                <form method="POST" action="/dev/login">
                    <div class="mb-3">
                        <label for="username" class="form-label small text-white-50">Username or Email</label>
                        <input type="text" id="username" name="username" class="form-control" placeholder="admin" value="{safe_username}" required autofocus />
                    </div>
                    <div class="mb-4">
                        <label for="password" class="form-label small text-white-50">Password</label>
                        <input type="password" id="password" name="password" class="form-control" placeholder="admin" required />
                    </div>
                    <button type="submit" class="btn btn-danger w-100 py-2 fw-semibold mb-3">
                        Sign In to Console
                    </button>
                    <div class="text-center">
                        <a href="/" class="text-white-50 small text-decoration-none">&larr; Return to App</a>
                    </div>
                </form>
            </div>
        </div>
    </div>
    <script>
        function autoFill() {{
            document.getElementById('username').value = 'admin';
            document.getElementById('password').value = 'admin';
        }}
    </script>
</body>
</html>"""


@router.get("/login", response_class=HTMLResponse)
async def dev_login_page(request: Request):
    """Renders test console login form."""
    cookie_val = request.cookies.get("test_console")
    if _verify_cookie_payload(cookie_val):
        return RedirectResponse(url="/dev", status_code=status.HTTP_302_FOUND)

    return HTMLResponse(content=render_dev_login_html(), status_code=200)


@router.post("/login")
async def dev_login(request: Request):
    """Authenticates against TEST_ADMIN_USER / TEST_ADMIN_PASSWORD and sets signed cookie."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    username, password = await _extract_credentials(request)

    expected_user = (os.getenv("TEST_ADMIN_USER") or "admin").strip()
    expected_pass = (os.getenv("TEST_ADMIN_PASSWORD") or "admin").strip()

    clean_user = username.strip()
    clean_pass = password.strip()

    valid_user = secrets.compare_digest(clean_user, expected_user) or secrets.compare_digest(clean_user.lower(), expected_user.lower())
    if not valid_user and expected_user == "admin" and secrets.compare_digest(clean_user.lower(), "admin@galgotias.edu"):
        valid_user = True

    valid_pass = secrets.compare_digest(clean_pass, expected_pass)

    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    is_html_request = "text/html" in accept

    if not (valid_user and valid_pass):
        _record_failed_attempt(client_ip)
        if is_html_request:
            return HTMLResponse(
                content=render_dev_login_html(error="Invalid test admin credentials", username=clean_user),
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        return PlainTextResponse("Invalid test admin credentials", status_code=status.HTTP_401_UNAUTHORIZED)

    # Success: reset rate limiting for this client
    _FAILED_ATTEMPTS.pop(client_ip, None)
    _LOCKOUTS.pop(client_ip, None)

    signed_token = _sign_cookie_payload("console_authenticated")

    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type or ("application/json" in accept and "text/html" not in accept):
        response = JSONResponse({"status": "ok", "message": "logged_in", "redirect": "/dev"}, status_code=status.HTTP_200_OK)
    else:
        response = RedirectResponse(url="/dev", status_code=status.HTTP_303_SEE_OTHER)

    response.set_cookie(
        key="test_console",
        value=signed_token,
        max_age=8 * 3600,
        httponly=True,
        samesite="strict",
        path="/"
    )
    return response


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dev_console_home(request: Request):
    """Test console dashboard page."""
    cookie_val = request.cookies.get("test_console")
    if not _verify_cookie_payload(cookie_val):
        return RedirectResponse(url="/dev/login", status_code=status.HTTP_302_FOUND)

    session_user = request.session.get("user")
    current_role = session_user.get("role") if session_user else "none"

    return templates.TemplateResponse(
        request=request,
        name="dev_console.html",
        context={
            "current_role": current_role,
            "session_user": session_user,
        }
    )


@router.post("/logout")
async def dev_logout(request: Request):
    """Clears the test_console cookie."""
    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type or ("application/json" in accept and "text/html" not in accept):
        response = JSONResponse({"status": "ok", "message": "logged_out"}, status_code=status.HTTP_200_OK)
    else:
        response = RedirectResponse(url="/dev/login", status_code=status.HTTP_302_FOUND)

    response.delete_cookie(key="test_console", path="/")
    return response


@router.post("/switch")
async def dev_switch_role(request: Request):
    """Switches active session role to the seeded persona via real session mechanism."""
    cookie_val = request.cookies.get("test_console")
    if not _verify_cookie_payload(cookie_val):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/dev/login", status_code=status.HTTP_302_FOUND)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Test console authentication required"
        )

    # Extract role from form or json
    content_type = request.headers.get("content-type", "")
    role = ""
    if "application/json" in content_type:
        try:
            body = await request.json()
            role = str(body.get("role", "")).strip()
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            role = str(form.get("role", "")).strip()
        except Exception:
            pass

    if role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{role}'. Must be one of {sorted(ALLOWED_ROLES)}"
        )

    # Load seeded user from DB (default student for participant)
    if role == "participant":
        user_row = fetch_one(
            "SELECT * FROM users WHERE role = 'participant' AND (email = 'student@galgotias.edu' OR username = 'student') LIMIT 1"
        )
        if not user_row:
            user_row = fetch_one(
                "SELECT * FROM users WHERE role = 'participant' ORDER BY id ASC LIMIT 1"
            )
    else:
        user_row = fetch_one(
            "SELECT * FROM users WHERE role = ? ORDER BY id ASC LIMIT 1",
            (role,)
        )

    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run init_db and seed_users first"
        )

    # Establish real session using the same helper normal login uses with extra claim
    set_user_session(request, user_row, via_test_console=True)

    # Write audit log row using existing KavachEngine.log_audit
    with get_db() as conn:
        kavach.log_audit(
            conn=conn,
            actor="test_console",
            action="role_switch",
            result=role,
        )

    target_url = ROLE_DASHBOARDS.get(role, "/")
    accept = request.headers.get("accept", "")
    if "application/json" in content_type or ("application/json" in accept and "text/html" not in accept):
        return JSONResponse(
            {"status": "ok", "role": role, "redirect_url": target_url},
            status_code=status.HTTP_200_OK
        )
    return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)


@router.post("/exit")
async def dev_exit_role(request: Request):
    """Clears normal session cookie and redirects to /dev."""
    cookie_val = request.cookies.get("test_console")
    if not _verify_cookie_payload(cookie_val):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/dev/login", status_code=status.HTTP_302_FOUND)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Test console authentication required"
        )

    request.session.clear()

    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type or ("application/json" in accept and "text/html" not in accept):
        response = JSONResponse({"status": "ok", "message": "role_session_cleared", "redirect": "/dev"}, status_code=status.HTTP_200_OK)
    else:
        response = RedirectResponse(url="/dev", status_code=status.HTTP_302_FOUND)

    session_cookie_name = os.getenv("SESSION_COOKIE_NAME", "agenticliner_session")
    response.delete_cookie(key=session_cookie_name, path="/")
    return response
