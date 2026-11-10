"""
Authentication Routes for AgenticLiner.
Handles login, signup, real email OTP dispatch (Option A), Google One-Tap/OAuth (Option B),
password resets, and role-based redirects.
"""

from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional, Dict, Any
import os
import logging
import json
import ipaddress
import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin.exceptions import FirebaseError

from backend.services.auth_service import (
    authenticate_user,
    create_user,
    create_user_from_google,
    get_user_by_email,
    get_user_by_id,
    create_otp,
    verify_otp,
    reset_user_password,
    validate_strong_password,
    update_user_profile,
    change_user_password,
    update_user_preferences
)
import urllib.parse
from backend.services.email_service import send_email_otp, is_smtp_configured
from backend.api.dependencies import get_session_user
from backend.core.database.connection import execute_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])

def set_user_session(request: Request, user: Dict[str, Any], **extra_claims) -> Dict[str, Any]:
    """Establishes authenticated user session payload in signed session cookie."""
    session_payload = {
        "id": user["id"] if "id" in user else "",
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "full_name": user["full_name"],
        "department": user.get("department") or "School of AI"
    }
    session_payload.update(extra_claims)
    request.session["user"] = session_payload
    return session_payload

class FirebaseAuthConfigurationError(RuntimeError):
    pass

class InvalidFirebaseIDToken(ValueError):
    pass

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ROLE_DASHBOARDS = {
    "supervisor": "/supervisor",
    "organiser": "/organiser",
    "data_manager": "/data-manager",
    "participant": "/participant"
}

def get_firebase_config():
    """Retrieves Firebase project web configuration from environment variables."""
    return {
        "apiKey": os.getenv("FIREBASE_API_KEY", "").strip(),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", "").strip(),
        "projectId": os.getenv("FIREBASE_PROJECT_ID", "").strip(),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", "").strip(),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", "").strip(),
        "appId": os.getenv("FIREBASE_APP_ID", "").strip()
    }

def is_demo_login_enabled(request: Request) -> bool:
    """Returns whether server-side demo login is enabled for this deployment."""
    if (
        os.getenv("ALLOW_DEMO_LOGIN", "").strip() != "1"
        or os.getenv("ALLOW_PUBLIC_TUNNEL", "").strip() == "1"
        or request.client is None
    ):
        return False

    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False

def verify_firebase_id_token(id_token: str):
    """Verifies a Firebase ID token against the configured Firebase project."""
    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    if not project_id:
        raise FirebaseAuthConfigurationError("FIREBASE_PROJECT_ID is not configured.")

    app_name = f"agenticliner-{project_id}"
    try:
        try:
            firebase_app = firebase_admin.get_app(app_name)
        except ValueError:
            firebase_app = firebase_admin.initialize_app(
                options={"projectId": project_id},
                name=app_name
            )
    except Exception as exc:
        raise FirebaseAuthConfigurationError(
            "Firebase Admin SDK could not initialize for the configured project."
        ) from exc

    try:
        return firebase_auth.verify_id_token(id_token, app=firebase_app)
    except (ValueError, firebase_auth.InvalidIdTokenError) as exc:
        raise InvalidFirebaseIDToken("Firebase ID token is invalid.") from exc

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: Optional[str] = None):
    """Renders the unified login page with Google Sign-In and role-based redirect."""
    current_user = get_session_user(request)
    if current_user:
        target = ROLE_DASHBOARDS.get(current_user["role"], "/login")
        return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)

    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None,
            "next": next or "",
            "google_client_id": google_client_id,
            "firebase_config": get_firebase_config(),
            "smtp_configured": is_smtp_configured(),
            "demo_login_enabled": is_demo_login_enabled(request)
        }
    )

@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(None),
    password: str = Form(None)
):
    """Processes login form submission or JSON payload with role-based redirect."""
    if not email or not password:
        try:
            body = await request.json()
            email = body.get("email")
            password = body.get("password")
        except Exception:
            pass

    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()

    if not email or not password:
        accept = request.headers.get("accept", "")
        if "text/html" in accept or request.headers.get("content-type") == "application/x-www-form-urlencoded":
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error": "Email and password are required.",
                    "next": "",
                    "google_client_id": google_client_id,
                    "firebase_config": get_firebase_config(),
                    "smtp_configured": is_smtp_configured(),
                    "demo_login_enabled": is_demo_login_enabled(request)
                }
            )
        raise HTTPException(status_code=400, detail="Email and password are required.")

    user, error_msg = authenticate_user(email.strip(), password)
    if not user:
        accept = request.headers.get("accept", "")
        if "text/html" in accept or request.headers.get("content-type") == "application/x-www-form-urlencoded":
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error": error_msg or "Invalid email or password. Please try again.",
                    "next": "",
                    "google_client_id": google_client_id,
                    "firebase_config": get_firebase_config(),
                    "smtp_configured": is_smtp_configured(),
                    "demo_login_enabled": is_demo_login_enabled(request)
                }
            )
        raise HTTPException(status_code=401, detail=error_msg or "Invalid credentials.")

    # Set session cookie
    set_user_session(request, user)

    target_url = ROLE_DASHBOARDS.get(user["role"], "/")

    accept = request.headers.get("accept", "")
    if "text/html" in accept or request.headers.get("content-type") == "application/x-www-form-urlencoded":
        return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)

    return JSONResponse(content={
        "success": True,
        "user": user,
        "redirect_url": target_url
    })

@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    """Renders the signup / registration page with role, department, and Google Sign-in."""
    current_user = get_session_user(request)
    if current_user:
        target = ROLE_DASHBOARDS.get(current_user["role"], "/login")
        return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)

    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()

    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={
            "error": None,
            "form_data": {},
            "google_client_id": google_client_id,
            "firebase_config": get_firebase_config(),
            "smtp_configured": is_smtp_configured(),
            "demo_login_enabled": is_demo_login_enabled(request)
        }
    )

@router.post("/signup")
async def signup_submit(
    request: Request,
    full_name: str = Form(None),
    email: str = Form(None),
    password: str = Form(None),
    confirm_password: str = Form(None),
    role: str = Form("participant"),
    department: str = Form("School of AI")
):
    """
    Validates user registration, verifies strong password,
    sends real SMTP email OTP (Option A), and forwards to /verify-otp.
    """
    if not email or not password:
        try:
            body = await request.json()
            full_name = body.get("full_name")
            email = body.get("email")
            password = body.get("password")
            confirm_password = body.get("confirm_password") or password
            role = body.get("role", "participant")
            department = body.get("department", "School of AI")
        except Exception:
            pass

    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    # Security Policy: Public registration always provisions Participant role to prevent privilege escalation.
    role = "participant"
    form_data = {
        "full_name": full_name or "",
        "email": email or "",
        "role": role,
        "department": department or "School of AI"
    }

    if not full_name or not email or not password:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": "All fields are required.",
                "form_data": form_data,
                "google_client_id": google_client_id,
                "smtp_configured": is_smtp_configured(),
                "demo_login_enabled": is_demo_login_enabled(request)
            }
        )

    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": "Passwords do not match.",
                "form_data": form_data,
                "google_client_id": google_client_id,
                "smtp_configured": is_smtp_configured(),
                "demo_login_enabled": is_demo_login_enabled(request)
            }
        )

    # Validate strong password
    is_strong, pass_err = validate_strong_password(password)
    if not is_strong:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": pass_err,
                "form_data": form_data,
                "google_client_id": google_client_id,
                "smtp_configured": is_smtp_configured(),
                "demo_login_enabled": is_demo_login_enabled(request)
            }
        )

    # Check if user already exists
    existing_user = get_user_by_email(email.strip())
    if existing_user:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": f"An account with email '{email}' already exists. Please log in.",
                "form_data": form_data,
                "google_client_id": google_client_id,
                "smtp_configured": is_smtp_configured(),
                "demo_login_enabled": is_demo_login_enabled(request)
            }
        )

    # Store registration info in OTP verification record
    clean_email = email.strip().lower()
    clean_name = full_name.strip()
    signup_payload = {
        "full_name": clean_name,
        "email": clean_email,
        "password": password,
        "role": role,
        "department": department.strip()
    }

    otp_code = create_otp(email=clean_email, purpose="signup", payload=signup_payload)

    # Option A: Attempt real email dispatch via SMTP
    email_sent = False
    if is_smtp_configured():
        email_sent, err_msg = send_email_otp(
            to_email=clean_email,
            otp_code=otp_code,
            purpose="signup",
            recipient_name=clean_name
        )
        if not email_sent:
            logger.warning(f"Could not send email via SMTP: {err_msg}")

    # Build redirect URL
    redirect_params = [
        f"email={clean_email}",
        "purpose=signup",
        f"email_sent={1 if email_sent else 0}",
        f"smtp_configured={1 if is_smtp_configured() else 0}"
    ]
    # Only append demo_code if email was not sent (for testing fallback)
    if not email_sent:
        redirect_params.append(f"demo_code={otp_code}")

    return RedirectResponse(
        url=f"/verify-otp?{'&'.join(redirect_params)}",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/verify-otp", response_class=HTMLResponse)
async def verify_otp_page(
    request: Request,
    email: str,
    purpose: str = "signup",
    demo_code: Optional[str] = None,
    email_sent: Optional[str] = None,
    smtp_configured: Optional[str] = None
):
    """Renders OTP verification page with real inbox notification or demo code fallback."""
    return templates.TemplateResponse(
        request=request,
        name="verify_otp.html",
        context={
            "email": email,
            "purpose": purpose,
            "demo_code": demo_code,
            "email_sent": email_sent == "1",
            "smtp_configured": smtp_configured == "1" or is_smtp_configured(),
            "error": None
        }
    )

@router.post("/verify-otp")
async def verify_otp_submit(
    request: Request,
    email: str = Form(...),
    purpose: str = Form("signup"),
    otp_code: str = Form(...)
):
    """Verifies the 6-digit OTP. On success, completes user registration or password reset."""
    is_valid, err_msg, payload = verify_otp(email=email.strip(), otp_code=otp_code.strip(), purpose=purpose)
    
    if not is_valid:
        return templates.TemplateResponse(
            request=request,
            name="verify_otp.html",
            context={
                "email": email,
                "purpose": purpose,
                "demo_code": None,
                "email_sent": False,
                "smtp_configured": is_smtp_configured(),
                "error": err_msg or "Invalid verification code."
            }
        )

    if purpose == "signup":
        try:
            user = create_user(
                email=payload["email"],
                password=payload["password"],
                role=payload["role"],
                full_name=payload["full_name"],
                department=payload.get("department", "School of AI")
            )
            request.session["user"] = user
            target_url = ROLE_DASHBOARDS.get(user["role"], "/")
            return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
        except Exception as e:
            return templates.TemplateResponse(
                request=request,
                name="verify_otp.html",
                context={
                    "email": email,
                    "purpose": purpose,
                    "demo_code": None,
                    "email_sent": False,
                    "smtp_configured": is_smtp_configured(),
                    "error": str(e)
                }
            )

    elif purpose == "password_reset":
        request.session["reset_verified_email"] = email.strip().lower()
        return RedirectResponse(url=f"/reset-password?email={email.strip().lower()}", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@router.post("/resend-otp")
async def resend_otp(
    request: Request,
    email: str = Form(...),
    purpose: str = Form("signup")
):
    """Regenerates a new 6-digit OTP code and dispatches via email if configured."""
    from backend.core.database.connection import fetch_one
    clean_email = email.strip().lower()
    existing = fetch_one(
        "SELECT payload_json FROM otp_verifications WHERE email = ? AND purpose = ?",
        (clean_email, purpose)
    )
    payload = json.loads(existing["payload_json"]) if existing and existing["payload_json"] else {}
    
    new_code = create_otp(email=clean_email, purpose=purpose, payload=payload)

    email_sent = False
    if is_smtp_configured():
        recipient_name = payload.get("full_name", "")
        email_sent, _ = send_email_otp(
            to_email=clean_email,
            otp_code=new_code,
            purpose=purpose,
            recipient_name=recipient_name
        )

    redirect_params = [
        f"email={clean_email}",
        f"purpose={purpose}",
        f"email_sent={1 if email_sent else 0}",
        f"smtp_configured={1 if is_smtp_configured() else 0}",
        "resent=1"
    ]
    if not email_sent:
        redirect_params.append(f"demo_code={new_code}")

    return RedirectResponse(
        url=f"/verify-otp?{'&'.join(redirect_params)}",
        status_code=status.HTTP_302_FOUND
    )

# --- Option B: Google One-Tap & OAuth Authentication ---

@router.post("/auth/google")
@router.post("/api/auth/firebase-login")
async def google_auth_callback(request: Request):
    """
    Handles Real Google / Firebase Sign-In.
    Verifies token or payload, establishes server session,
    and maps the user to their role and department in the database.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    credential = data.get("credential") or data.get("id_token")
    is_demo = data.get("demo_google") is True
    demo_role = None

    if is_demo:
        if not is_demo_login_enabled(request):
            raise HTTPException(
                status_code=403,
                detail="Demo sign-in is disabled for this deployment."
            )
        google_email = data.get("email")
        google_name = data.get("name")
        department = data.get("department", "School of AI")
        candidate_role = data.get("role")
        if candidate_role in {"organiser", "supervisor", "data_manager", "participant"}:
            demo_role = candidate_role
    else:
        if not isinstance(credential, str) or not credential.strip():
            raise HTTPException(status_code=401, detail="A Firebase ID token is required.")
        try:
            token_data = verify_firebase_id_token(credential)
        except InvalidFirebaseIDToken:
            logger.warning("Firebase ID token verification failed.")
            raise HTTPException(status_code=401, detail="Firebase ID token verification failed.")
        except FirebaseAuthConfigurationError:
            logger.exception("Firebase authentication is not configured correctly.")
            raise HTTPException(status_code=503, detail="Firebase authentication is unavailable.")
        except FirebaseError:
            logger.exception("Firebase ID token verification is unavailable.")
            raise HTTPException(status_code=503, detail="Firebase authentication is unavailable.")
        except ValueError:
            logger.warning("Firebase ID token verification failed.")
            raise HTTPException(status_code=401, detail="Firebase ID token verification failed.")

        google_email = token_data.get("email")
        google_name = token_data.get("name")
        department = token_data.get("department", "School of AI")
        if token_data.get("email_verified") is not True:
            raise HTTPException(status_code=401, detail="A verified Firebase email is required.")

    if not isinstance(google_email, str) or not google_email.strip():
        raise HTTPException(status_code=401, detail="A verified email address is required.")

    # Create or retrieve user from database
    user = create_user_from_google(
        email=google_email,
        full_name=google_name or google_email.split("@")[0],
        role="participant",
        department=department
    )

    if is_demo and demo_role:
        if user.get("role") != demo_role:
            execute_query(
                "UPDATE users SET role = ? WHERE email = ?",
                (demo_role, google_email.strip().lower())
            )
            user["role"] = demo_role

    # Establish session cookie
    set_user_session(request, user)
    target_url = ROLE_DASHBOARDS.get(user["role"], "/")

    return JSONResponse(content={
        "success": True,
        "user": user,
        "redirect_url": target_url
    })

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Renders forgot password request form."""
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={"error": None, "success": None}
    )

@router.post("/forgot-password")
async def forgot_password_submit(
    request: Request,
    email: str = Form(...)
):
    """Validates email and sends 6-digit OTP for password reset via real email or fallback."""
    clean_email = email.strip().lower()
    user = get_user_by_email(clean_email)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={"error": "No account registered with this email address.", "success": None}
        )

    otp_code = create_otp(email=clean_email, purpose="password_reset", payload={"user_id": user["id"]})

    email_sent = False
    if is_smtp_configured():
        email_sent, _ = send_email_otp(
            to_email=clean_email,
            otp_code=otp_code,
            purpose="password_reset",
            recipient_name=user.get("full_name", "")
        )

    redirect_params = [
        f"email={clean_email}",
        "purpose=password_reset",
        f"email_sent={1 if email_sent else 0}",
        f"smtp_configured={1 if is_smtp_configured() else 0}"
    ]
    if not email_sent:
        redirect_params.append(f"demo_code={otp_code}")

    return RedirectResponse(
        url=f"/verify-otp?{'&'.join(redirect_params)}",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, email: str):
    """Renders set new password page for verified user."""
    verified_email = request.session.get("reset_verified_email")
    if not verified_email or verified_email.lower() != email.strip().lower():
        return RedirectResponse(url="/forgot-password?error=unauthorized", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={"email": email, "error": None}
    )

@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    email: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Applies strong password checks and updates password hash."""
    verified_email = request.session.get("reset_verified_email")
    if not verified_email or verified_email.lower() != email.strip().lower():
        return RedirectResponse(url="/forgot-password", status_code=status.HTTP_302_FOUND)

    if new_password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            context={"email": email, "error": "Passwords do not match."}
        )

    success, err_msg = reset_user_password(email.strip(), new_password)
    if not success:
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            context={"email": email, "error": err_msg or "Failed to reset password."}
        )

    request.session.pop("reset_verified_email", None)
    return RedirectResponse(url="/login?reset_success=1", status_code=status.HTTP_302_FOUND)

@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    """Logs out user by clearing the session cookie and redirecting to /login."""
    request.session.clear()
    accept = request.headers.get("accept", "")
    if "text/html" in accept or request.method == "GET":
        return RedirectResponse(url="/login?logged_out=1", status_code=status.HTTP_302_FOUND)
    return JSONResponse(content={"success": True, "message": "Logged out successfully."})


# ==========================================
# Comprehensive Settings & Profile Routes
# ==========================================

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, tab: str = "profile", success: Optional[str] = None, error: Optional[str] = None):
    """Renders the comprehensive user settings and profile management page."""
    current_user = get_session_user(request)
    if not current_user:
        return RedirectResponse(url="/login?next=/settings", status_code=status.HTTP_302_FOUND)

    user_data = get_user_by_id(current_user["id"]) or current_user

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "user": user_data,
            "active_tab": tab,
            "success_msg": success,
            "error_msg": error
        }
    )

@router.post("/settings/profile")
async def update_profile_submit(
    request: Request,
    full_name: str = Form(...),
    department: str = Form("General"),
    phone: Optional[str] = Form(None),
    bio: Optional[str] = Form(None)
):
    """Updates user personal details."""
    current_user = get_session_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    try:
        updated = update_user_profile(
            user_id=current_user["id"],
            full_name=full_name,
            department=department,
            phone=phone,
            bio=bio
        )
        if "user" in request.session:
            request.session["user"]["full_name"] = updated["full_name"]
            request.session["user"]["department"] = updated["department"]
        return RedirectResponse(url="/settings?tab=profile&success=Profile+updated+successfully!", status_code=status.HTTP_302_FOUND)
    except Exception as e:
        return RedirectResponse(url=f"/settings?tab=profile&error={urllib.parse.quote_plus(str(e))}", status_code=status.HTTP_302_FOUND)

@router.post("/settings/change-password")
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Changes password for logged in user."""
    current_user = get_session_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if new_password != confirm_password:
        return RedirectResponse(url="/settings?tab=security&error=New+passwords+do+not+match.", status_code=status.HTTP_302_FOUND)

    success, err_msg = change_user_password(
        user_id=current_user["id"],
        current_password=current_password,
        new_password=new_password
    )
    if not success:
        return RedirectResponse(url=f"/settings?tab=security&error={urllib.parse.quote_plus(err_msg or 'Failed to update password.')}", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url="/settings?tab=security&success=Password+changed+successfully!", status_code=status.HTTP_302_FOUND)

@router.post("/settings/preferences")
async def update_preferences_submit(
    request: Request,
    preferred_language: str = Form("en"),
    notifications_enabled: Optional[str] = Form(None)
):
    """Updates user notification and language preferences."""
    current_user = get_session_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    is_notif = True if notifications_enabled in ("on", "1", "true") else False
    updated = update_user_preferences(
        user_id=current_user["id"],
        preferred_language=preferred_language,
        notifications_enabled=is_notif
    )
    if "user" in request.session:
        request.session["user"]["preferred_language"] = updated.get("preferred_language", "en")
    return RedirectResponse(url="/settings?tab=preferences&success=Preferences+saved+successfully!", status_code=status.HTTP_302_FOUND)
