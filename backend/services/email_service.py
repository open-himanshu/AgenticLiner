"""
Real Email Dispatch Service for AgenticLiner (Option A).
Sends branded campus OTP verification emails via standard SMTP (Gmail / University Mail Server).
"""

import smtplib
import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple, Optional
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

logger = logging.getLogger(__name__)

def is_smtp_configured() -> bool:
    """Returns True if SMTP_USER and SMTP_PASSWORD are set in the environment and not placeholders."""
    user = os.getenv("SMTP_USER", "").strip()
    pwd = os.getenv("SMTP_PASSWORD", "").strip()
    if not user or not pwd:
        return False
    if "your_email" in user.lower() or "your_" in pwd.lower():
        return False
    return True

def send_email_otp(
    to_email: str,
    otp_code: str,
    purpose: str = "signup",
    recipient_name: str = ""
) -> Tuple[bool, Optional[str]]:
    """
    Sends a 6-digit OTP passcode to the recipient's email inbox using SMTP.
    Returns (True, None) on success, or (False, error_message) on failure.
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    # Strip spaces from app password if present (e.g. Gmail 16-character format 'xxxx xxxx xxxx xxxx')
    if len(smtp_password.replace(" ", "")) == 16:
        smtp_password = smtp_password.replace(" ", "")
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "AgenticLiner Galgotias University").strip()
    from_email = smtp_user if smtp_user else os.getenv("SMTP_FROM_EMAIL", "noreply@galgotias.edu").strip()

    if not is_smtp_configured():
        return False, "SMTP is not configured in .env (SMTP_USER/SMTP_PASSWORD missing)."

    # Determine subject and context based on purpose
    if purpose == "password_reset":
        subject = f"🔒 Password Reset Code: {otp_code} - AgenticLiner"
        action_text = "reset your password for your AgenticLiner campus account"
    else:
        subject = f"🎓 Email Verification Code: {otp_code} - AgenticLiner"
        action_text = "verify your campus account registration on AgenticLiner"

    display_name = recipient_name or to_email.split("@")[0]

    # Compose Plain Text Body
    text_content = f"""Hello {display_name},

Your verification code is: {otp_code}

Use this 6-digit code to {action_text}.
This code is valid for 10 minutes and can only be used once.

If you did not request this code, please ignore this email.

Best regards,
Galgotias University SparkX 3.0
Team AgenticLiner
"""

    # Compose HTML Body
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 20px; }}
  .card {{ max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border: 1px solid #e2e8f0; }}
  .header {{ background: linear-gradient(135deg, #1E3A8A 0%, #1e40af 100%); color: #ffffff; padding: 28px 24px; text-align: center; }}
  .content {{ padding: 32px 28px; color: #1e293b; line-height: 1.6; }}
  .otp-box {{ background: #f8fafc; border: 2px dashed #3b82f6; border-radius: 8px; padding: 18px; text-align: center; margin: 24px 0; }}
  .otp-code {{ font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #1e3a8a; font-family: monospace; }}
  .footer {{ padding: 20px; background-color: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b; text-align: center; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h2 style="margin: 0; font-size: 22px;">🚀 AgenticLiner</h2>
    <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.9;">Galgotias University SparkX 3.0 Platform</p>
  </div>
  <div class="content">
    <p style="font-size: 15px; margin-top: 0;">Hello <strong>{display_name}</strong>,</p>
    <p style="font-size: 14px; color: #475569;">Please use the following 6-digit one-time passcode to {action_text}:</p>
    <div class="otp-box">
      <div class="otp-code">{otp_code}</div>
      <div style="font-size: 12px; color: #64748b; margin-top: 6px;">Valid for 10 minutes (Max 5 attempts)</div>
    </div>
    <p style="font-size: 13px; color: #64748b;">If you didn't initiate this request, you can safely ignore this email.</p>
  </div>
  <div class="footer">
    Galgotias University Campus Operations & Event Platform<br>
    SparkX 3.0 Innovation Challenge
  </div>
</div>
</body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f'"{smtp_from_name}" <{from_email}>'
    msg["To"] = to_email

    part1 = MIMEText(text_content, "plain")
    part2 = MIMEText(html_content, "html")
    msg.attach(part1)
    msg.attach(part2)

    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=12)
            server.starttls()
            
        clean_to_email = to_email.strip().lower()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_email, [clean_to_email], msg.as_string())
        server.quit()
        logger.info(f"Successfully dispatched OTP email to {clean_to_email}")
        return True, None
    except smtplib.SMTPAuthenticationError as e:
        err = "SMTP Authentication Failed: Invalid credentials. For Gmail, generate a 16-letter App Password at https://myaccount.google.com/apppasswords."
        logger.error(f"{err} Details: {e}")
        return False, err
    except smtplib.SMTPServerDisconnected as e:
        err = (
            "Google SMTP Disconnected: Google rejected the login credentials and closed the connection. "
            "For Gmail, you CANNOT use your regular Gmail password; you MUST use a 16-letter Google App Password "
            "(format: 'abcd efgh ijkl mnop') generated at: https://myaccount.google.com/apppasswords"
        )
        logger.error(f"{err} Details: {e}")
        return False, err
    except (smtplib.SMTPConnectError, TimeoutError, OSError) as e:
        err = f"SMTP Connection Failed: Unable to reach {smtp_host}:{smtp_port}. Check network or firewall."
        logger.error(f"{err} Details: {e}")
        return False, err
    except Exception as e:
        err = f"Failed to send email: {str(e)}"
        logger.error(err)
        return False, err


def send_stakeholder_email(
    to_email: str,
    subject: str,
    text_content: str,
    html_content: str
) -> Tuple[bool, Optional[str]]:
    """
    Sends rich HTML campus event notification emails to stakeholders (Dean, Organiser, Students).
    Returns (True, None) on success, or (False, error_message) on failure.
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    if len(smtp_password.replace(" ", "")) == 16:
        smtp_password = smtp_password.replace(" ", "")
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "AgenticLiner Galgotias University").strip()
    from_email = smtp_user if smtp_user else os.getenv("SMTP_FROM_EMAIL", "noreply@galgotias.edu").strip()

    if not is_smtp_configured():
        return False, "SMTP is not configured in .env (SMTP_USER/SMTP_PASSWORD missing)."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f'"{smtp_from_name}" <{from_email}>'
    msg["To"] = to_email

    part1 = MIMEText(text_content, "plain")
    part2 = MIMEText(html_content, "html")
    msg.attach(part1)
    msg.attach(part2)

    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=12)
            server.starttls()

        clean_to_email = to_email.strip().lower()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_email, [clean_to_email], msg.as_string())
        server.quit()
        logger.info(f"Successfully dispatched stakeholder notification email to {clean_to_email}")
        return True, None
    except Exception as e:
        err = f"Failed to send stakeholder email: {str(e)}"
        logger.warning(err)
        return False, err


if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("AgenticLiner SMTP Configuration Test Tool")
    print("=" * 60)
    configured = is_smtp_configured()
    print(f"[*] SMTP Configured in environment: {configured}")
    if len(sys.argv) > 1:
        target_email = sys.argv[1].strip()
        print(f"[*] Attempting test OTP dispatch to: {target_email}")
        ok, err = send_email_otp(
            to_email=target_email,
            otp_code="987654",
            purpose="signup",
            recipient_name="Campus Tester"
        )
        if ok:
            print(f"[+] SUCCESS: Test OTP sent successfully to {target_email}!")
        else:
            print(f"[-] FAILED: {err}")
    else:
        print("[*] Usage to send test email: python -m backend.services.email_service your_email@gmail.com")
