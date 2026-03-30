"""
Send authority letter email to a utility provider with the letter as a PDF attachment.

The email is always sent FROM the app's configured DocuStay address (MAILGUN_FROM_EMAIL / sendgrid_from_email),
never from the property owner's email. It includes DocuStay branding, a short intro, and the authority letter as a PDF attachment. No sign link.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.property_utility import PropertyAuthorityLetter
from app.services.agreements import agreement_content_to_pdf
from app.services.notifications import send_email_with_attachment


def _email_html_body(provider_name: str, property_label: str) -> str:
    """HTML body: DocuStay branding and short intro only. The actual letter is in the PDF attachment only."""
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; font-size: 16px; line-height: 1.5; color: #1e293b;">
  <div style="max-width: 560px; margin: 0 auto; padding: 24px;">
    <div style="margin-bottom: 24px; padding-bottom: 16px; border-bottom: 2px solid #2563eb;">
      <span style="font-size: 24px; font-weight: 700; color: #2563eb; letter-spacing: -0.02em;">DocuStay</span>
    </div>
    <p style="margin: 0 0 16px;">Hello,</p>
    <p style="margin: 0 0 16px;">
      Please find attached a <strong>PDF attachment</strong> containing the authority letter from DocuStay for <strong>{provider_name}</strong> regarding the property at <strong>{property_label}</strong>.
    </p>
    <p style="margin: 0 0 16px;">
      The full letter is in the PDF attachment only. Please open the attachment to read the letter.
    </p>
    <p style="margin: 24px 0 0;">Thank you,<br/><strong>DocuStay</strong></p>
  </div>
</body>
</html>
"""


def send_authority_letter_to_provider(
    db: Session,
    letter: PropertyAuthorityLetter,
    to_email: str,
    provider_name: str,
    property_name: str | None = None,
    resend: bool = False,
) -> bool:
    """
    Generate a PDF of the authority letter and send it to the provider as an email attachment.
    Email has DocuStay branding and intro; no sign link. Returns True if email was sent.
    When resend=True (e.g. user clicked "Email authority letters to providers"), send even if already sent.
    """
    to_email = (to_email or "").strip().lower()
    if not to_email:
        return False

    if letter.email_sent_at and not resend:
        return False

    property_label = (property_name or "the property").strip() or "the property"
    subject = f"DocuStay – Authority letter for {provider_name} ({property_label})"
    # Body is intro only; the actual letter content is only in the PDF attachment (never in body).
    text = (
        f"Hello,\n\n"
        f"Please find attached a PDF containing the authority letter from DocuStay for {provider_name} regarding the property at {property_label}.\n\n"
        f"The full letter is in the PDF attachment only. Please open the attachment to read the letter.\n\n"
        f"Thank you,\nDocuStay"
    )
    html = _email_html_body(provider_name, property_label)

    title = f"DocuStay Authority Letter – {provider_name}"
    pdf_bytes = agreement_content_to_pdf(title, letter.letter_content)
    filename = f"DocuStay-Authority-Letter-{provider_name.replace(' ', '-')}.pdf"
    attachment = (filename, pdf_bytes)

    ok = send_email_with_attachment(to_email, subject, html, text_content=text, attachment=attachment)
    if ok:
        letter.email_sent_at = datetime.now(timezone.utc)
        db.commit()
        return True
    return False
