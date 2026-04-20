"""Module G & H: Stay timer trigger and notification status."""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.dependencies import get_current_user
from app.services.notifications import send_email
from app.services.stay_timer import run_stay_notification_job

router = APIRouter(prefix="/notifications", tags=["notifications"])
settings = get_settings()

# Default test recipient when none provided
TEST_EMAIL_DEFAULT = "arfamujahid333@gmail.com"


class TestEmailBody(BaseModel):
    to: str | None = None


@router.post("/test-email")
def send_test_email(body: TestEmailBody | None = Body(None)):
    """
    Send a test email via Mailgun. Uses arfamujahid333@gmail.com if 'to' is not provided.
    Requires MAILGUN_API_KEY and MAILGUN_DOMAIN (and optionally MAILGUN_BASE_URL) in .env.
    """
    if not settings.mailgun_api_key or not settings.mailgun_domain:
        raise HTTPException(
            status_code=503,
            detail="Mailgun is not configured. Set MAILGUN_API_KEY and MAILGUN_DOMAIN in .env.",
        )
    to_email = (body.to if body and body.to else TEST_EMAIL_DEFAULT).strip()
    subject = "[DocuStay] Test email – Mailgun is working"
    html_content = """
    <p>Hello,</p>
    <p>This is a test email from <strong>DocuStay</strong> sent via the Mailgun API.</p>
    <p>If you received this, Mailgun is configured correctly and the backend is calling it as expected.</p>
    <p>— DocuStay</p>
    """
    text_content = "This is a test email from DocuStay sent via the Mailgun API. If you received this, Mailgun is configured correctly."
    ok = send_email(to_email, subject, html_content, text_content=text_content)
    if not ok:
        raise HTTPException(status_code=502, detail="Mailgun request failed. Check server logs and MAILGUN_* settings.")
    return {"status": "ok", "message": f"Test email sent to {to_email}."}


@router.post("/run-stay-warnings")
def trigger_stay_warnings(current_user=Depends(get_current_user)):
    """Manually trigger the stay legal warning job (Module G). Sends emails for stays approaching limit."""
    run_stay_notification_job()
    return {"status": "ok", "message": "Stay warning job completed."}
