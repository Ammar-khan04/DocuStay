"""Module H: Notification service (Mailgun/SendGrid email, optional SMS)."""
import html

from app.config import get_settings
from app.services.notification_templates import (
    render_authorization_record_block,
    render_view_record_link,
    wrap_email_body,
)


def _property_page_url(property_id: int, for_manager: bool = False) -> str:
    """Build frontend URL to property detail page. Owners: #property/{id}. Managers: #manager-dashboard/property/{id}."""
    base = (get_settings().stripe_identity_return_url or get_settings().frontend_base_url or "http://localhost:5173").strip().split("#")[0].rstrip("/")
    path = f"manager-dashboard/property/{property_id}" if for_manager else f"property/{property_id}"
    return f"{base}/#{path}"


def _emails_property_managers_or_owner(owner_email: str, manager_emails: list[str]) -> list[str]:
    """Status confirmation routes to assigned property manager(s) when present; otherwise the owner. Never tenants/guests."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in manager_emails:
        e = (raw or "").strip()
        key = e.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(e)
    if out:
        return out
    o = (owner_email or "").strip()
    return [o] if o else []


def _send_email_to_pm_or_owner(owner_email: str, manager_emails: list[str], subject: str, html: str) -> None:
    for email in _emails_property_managers_or_owner(owner_email, manager_emails):
        send_email(email, subject, html)


def _verify_record_url(invite_code: str, property_address: str | None = None) -> str:
    """Build frontend URL to verify page for this stay record (scoped to invitation token). Shows full record and signed agreement."""
    base = (get_settings().stripe_identity_return_url or get_settings().frontend_base_url or "http://localhost:5173").strip().split("#")[0].rstrip("/")
    from urllib.parse import quote
    if invite_code:
        url = f"{base}/#check?token={quote(invite_code)}"
        if property_address:
            url += f"&address={quote(property_address)}"
        return url
    return base

# Clear settings cache so we use latest .env when sending (fixes server vs script using different config)
def _get_fresh_settings():
    get_settings.cache_clear()
    return get_settings()


def send_email(to_email: str, subject: str, html_content: str, text_content: str | None = None) -> bool:
    """Send email via Mailgun (preferred) or SendGrid. From address is always the app config (MAILGUN_FROM_EMAIL / sendgrid_from_email), never the owner or any user. Returns True if sent (or skipped when unconfigured)."""
    return send_email_with_attachment(to_email, subject, html_content, text_content=text_content)


def send_email_with_attachment(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str | None = None,
    attachment: tuple[str, bytes] | None = None,
) -> bool:
    """Send email via Mailgun or SendGrid. attachment is (filename, bytes) e.g. ('letter.pdf', pdf_bytes). Returns True if sent."""
    settings = get_settings()
    has_key = bool(settings.mailgun_api_key)
    has_domain = bool(settings.mailgun_domain)
    if has_key and has_domain:
        print(f"[Email] Calling Mailgun API: to={to_email} subject={subject} domain={settings.mailgun_domain}", flush=True)
        return _send_email_mailgun(to_email, subject, html_content, text_content=text_content, settings=settings, attachment=attachment)
    if settings.sendgrid_api_key:
        return _send_email_sendgrid(to_email, subject, html_content, text_content=text_content, settings=settings, attachment=attachment)
    print(
        f"[Email] NOT SENT: to={to_email} subject={subject}. MAILGUN_API_KEY={'set' if has_key else 'MISSING'} MAILGUN_DOMAIN={'set' if has_domain else 'MISSING'}. "
        "Set both in .env and restart the server.",
        flush=True,
    )
    return False


MAILGUN_US_BASE = "https://api.mailgun.net"
MAILGUN_EU_BASE = "https://api.eu.mailgun.net"


def _send_email_mailgun(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str | None = None,
    settings=None,
    attachment: tuple[str, bytes] | None = None,
):
    if settings is None:
        settings = get_settings()
    try:
        import httpx

        base = (settings.mailgun_base_url or MAILGUN_US_BASE).strip().rstrip("/")
        domain = (settings.mailgun_domain or "").strip().lower()
        from_addr = (settings.mailgun_from_email or "").strip()
        from_domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""
        if domain and from_domain != domain:
            from_addr = f"noreply@{domain}"
            print(f"[Mailgun] Using from={from_addr} (must match domain {domain} for delivery)", flush=True)
        from_email = f"{settings.mailgun_from_name} <{from_addr}>"
        url = f"{base}/v3/{domain}/messages"
        data = {
            "from": from_email,
            "to": to_email,
            "subject": subject,
            "text": text_content or "",
            "html": html_content or "",
        }
        files = None
        if attachment:
            filename, payload = attachment
            files = {"attachment": (filename, payload, "application/pdf")}
        with httpx.Client(timeout=15.0) as client:
            r = client.post(url, auth=("api", settings.mailgun_api_key), data=data, files=files)
            ok = 200 <= r.status_code < 300
            if ok:
                try:
                    msg_id = (r.json() or {}).get("id", "")
                except Exception:
                    msg_id = ""
                print(
                    f"[Mailgun] API success: to={to_email} status={r.status_code} id={msg_id}",
                    flush=True,
                )
                print(
                    "[Mailgun] If you do not receive the email: (1) Check spam/junk. "
                    "(2) If using a Mailgun SANDBOX domain, add this address in Dashboard > Sending > Authorized recipients.",
                    flush=True,
                )
                return True
            if r.status_code == 401 and base == MAILGUN_US_BASE:
                print("[Mailgun] 401 with US endpoint. Retrying with EU endpoint...", flush=True)
                url_eu = f"{MAILGUN_EU_BASE}/v3/{domain}/messages"
                r2 = client.post(url_eu, auth=("api", settings.mailgun_api_key), data=data, files=files)
                if 200 <= r2.status_code < 300:
                    print(f"[Mailgun] API success (EU): to={to_email}. If email not received, check spam or add recipient in Mailgun sandbox.", flush=True)
                    return True
                print(f"[Mailgun] EU request failed: status={r2.status_code} body={r2.text}", flush=True)
                return False
            err_body = r.text
            print(f"[Mailgun] API failed: status={r.status_code} to={to_email} body={err_body[:500]}", flush=True)
            return False
    except Exception as e:
        print(f"[Mailgun] Exception: to={to_email} error={type(e).__name__}: {e}", flush=True)
        return False


def _send_email_sendgrid(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str | None = None,
    settings=None,
    attachment: tuple[str, bytes] | None = None,
) -> bool:
    if settings is None:
        settings = get_settings()
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
        import base64

        message = Mail(
            from_email=(settings.sendgrid_from_email, settings.sendgrid_from_name),
            to_emails=to_email,
            subject=subject,
            html_content=html_content,
            plain_text_content=text_content or "",
        )
        if attachment:
            filename, payload = attachment
            encoded = base64.b64encode(payload).decode("utf-8")
            message.attachment = Attachment(
                FileContent(encoded),
                FileName(filename),
                FileType("application/pdf"),
                Disposition("attachment"),
            )
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        sg.send(message)
        return True
    except Exception:
        return False


def send_verification_email(to_email: str, code: str) -> bool:
    """Send 6-digit verification code email for signup. Uses same Mailgun path as test-email (send_email -> _send_email_mailgun)."""
    # Use fresh settings so UI flow sees same .env as script (avoids stale cache when server started before .env had Mailgun)
    _get_fresh_settings()
    s = get_settings()
    domain = (s.mailgun_domain or "").strip() or "(none)"
    from_addr = (getattr(s, "mailgun_from_email", None) or "").strip() or "(none)"
    print(f"[Verification] Sending code to {to_email} domain={domain} from={from_addr} code_len={len(code) if code else 0}", flush=True)
    subject = "[DocuStay] Your verification code"
    text_content = f"Your DocuStay verification code is: {code}. It expires in 10 minutes."
    html_content = f"""
    <p>Hello,</p>
    <p>Your DocuStay verification code is: <strong style="font-size:1.2em;letter-spacing:0.2em;">{code}</strong></p>
    <p>This code expires in 10 minutes. If you did not request this, you can ignore this email.</p>
    <p>— DocuStay</p>
    """
    print(f"[Verification] Calling send_email (Mailgun if configured) for {to_email}", flush=True)
    ok = send_email(to_email, subject, html_content, text_content=text_content)
    if ok:
        print(f"[Verification] Sent successfully to {to_email}. If not received, check spam and Mailgun sandbox (add recipient in dashboard).", flush=True)
    return ok


def send_password_reset_email(to_email: str, reset_link: str, role: str) -> bool:
    """Send password reset link. role is 'owner' or 'guest' for copy."""
    account_type = "owner" if role == "owner" else "guest"
    subject = "[DocuStay] Reset your password"
    text_content = f"Use this link to reset your DocuStay {account_type} account password. The link expires in 1 hour.\n\n{reset_link}\n\nIf you did not request this, you can ignore this email.\n— DocuStay"
    html_content = f"""
    <p>Hello,</p>
    <p>You requested a password reset for your DocuStay <strong>{account_type}</strong> account.</p>
    <p><a href="{reset_link}" style="background:#2563eb;color:white;padding:10px 16px;text-decoration:none;border-radius:6px;display:inline-block;">Reset password</a></p>
    <p>Or copy this link: <br/><a href="{reset_link}">{reset_link}</a></p>
    <p>This link expires in 1 hour. If you did not request this, you can ignore this email.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html_content, text_content=text_content)


def send_owner_welcome_email(to_email: str, full_name: str | None = None) -> bool:
    """Send welcome email when owner successfully signs up (after email verification)."""
    name = (full_name or "").strip() or "there"
    subject = "[DocuStay] Welcome – your account is verified"
    text = f"Hi {name}, welcome to DocuStay. Your account is verified and you can now sign in and manage your properties."
    html = f"""
    <p>Hi {name},</p>
    <p>Welcome to <strong>DocuStay</strong>. Your account is verified and you're all set.</p>
    <p>You can now sign in to create properties, send invitations, and manage temporary stays with clear documentation.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html, text_content=text)


def send_manager_welcome_email(to_email: str, full_name: str | None = None, property_name: str = "your assigned properties") -> bool:
    """Send welcome email when property manager signs up via invite."""
    name = (full_name or "").strip() or "there"
    subject = "[DocuStay] Welcome – your Property Manager account is ready"
    html = f"""
    <p>Hi {name},</p>
    <p>Welcome to <strong>DocuStay</strong>. Your Property Manager account is ready.</p>
    <p>You can now sign in to manage <strong>{property_name}</strong>, view units, invite tenants, and view activity logs.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html, text_content=f"Hi {name}, welcome to DocuStay. Your Property Manager account is ready. Sign in to manage {property_name}.")


def send_guest_signup_welcome_email(to_email: str, full_name: str | None = None) -> bool:
    """Send welcome email when a guest signs up (no stay yet – e.g. no invite or invite not yet accepted)."""
    name = (full_name or "").strip() or "there"
    subject = "[DocuStay] Welcome – your account is ready"
    text = f"Hi {name}, welcome to DocuStay. Your guest account is ready. Sign in to add invitation links from your hosts and manage your stays."
    html = f"""
    <p>Hi {name},</p>
    <p>Welcome to <strong>DocuStay</strong>. Your guest account is ready.</p>
    <p>Sign in to add invitation links from your hosts, view and sign agreements, and manage your temporary stays with legal clarity.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html, text_content=text)


def send_guest_welcome_email(
    to_email: str,
    full_name: str | None = None,
    property_name: str = "the property",
    stay_end_date: str | None = None,
) -> bool:
    """Send welcome email when guest successfully signs up with an accepted invite (stay created)."""
    name = (full_name or "").strip() or "there"
    end_line = f" Your authorized stay ends on <strong>{stay_end_date}</strong>." if stay_end_date else ""
    subject = "[DocuStay] Welcome – you're registered"
    text = f"Hi {name}, welcome to DocuStay. You're registered for {property_name}.{end_line}"
    html = f"""
    <p>Hi {name},</p>
    <p>Welcome to <strong>DocuStay</strong>. You're successfully registered for <strong>{property_name}</strong>.</p>
    <p>{end_line or "You can sign in to view your stay details and authorization."}</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html, text_content=text)


def send_guest_stay_added_email(
    to_email: str,
    full_name: str | None,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Notify existing guest when they accept a new invitation (stay added)."""
    name = (full_name or "").strip() or "there"
    subject = "[DocuStay] New stay added – " + property_name
    html = f"""
    <p>Hi {name},</p>
    <p>A new stay has been added to your account at <strong>{property_name}</strong>.</p>
    <p><strong>Authorized end date:</strong> {stay_end_date}</p>
    <p>Sign in to view your stay details.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_tenant_invite_email(
    to_email: str,
    invite_link: str,
    tenant_name: str,
    property_name: str = "your property",
) -> bool:
    """Email a tenant their registration link (CSV bulk or owner-invited). Link stays valid until they complete signup."""
    safe_name = (tenant_name or "there").strip() or "there"
    safe_prop = (property_name or "your property").strip() or "your property"
    subject = f"[DocuStay] You've been invited to register as a tenant — {safe_prop}"
    html = f"""
    <p>Hello {safe_name},</p>
    <p>You've been invited to create your tenant account for <strong>{safe_prop}</strong> on DocuStay.</p>
    <p>Click the link below to register and complete your invitation:</p>
    <p><a href="{invite_link}" style="background:#2563eb;color:white;padding:10px 16px;text-decoration:none;border-radius:6px;display:inline-block;">Complete registration</a></p>
    <p>Or copy this link:<br/><a href="{invite_link}">{invite_link}</a></p>
    <p>This invitation remains valid until you complete registration.</p>
    <p>— DocuStay</p>
    """
    text = f"You've been invited to register as a tenant for {safe_prop} on DocuStay. Complete registration: {invite_link}"
    return send_email(to_email, subject, html, text_content=text)


def send_tenant_lease_extension_email(
    to_email: str,
    invite_link: str,
    tenant_name: str,
    property_name: str = "your property",
    *,
    new_end_date: str,
) -> bool:
    """Email an existing tenant to sign in and accept a lease extension (same assignment row)."""
    safe_name = (tenant_name or "there").strip() or "there"
    safe_prop = (property_name or "your property").strip() or "your property"
    subject = f"[DocuStay] Lease extension — {safe_prop}"
    html = f"""
    <p>Hello {safe_name},</p>
    <p>Your landlord has offered a lease extension for <strong>{safe_prop}</strong> through <strong>{new_end_date}</strong>.</p>
    <p>Sign in to your tenant account and open the link below to review and accept. This updates your current lease — you do not register again.</p>
    <p><a href="{invite_link}" style="background:#2563eb;color:white;padding:10px 16px;text-decoration:none;border-radius:6px;display:inline-block;">Review lease extension</a></p>
    <p>Or copy this link:<br/><a href="{invite_link}">{invite_link}</a></p>
    <p>— DocuStay</p>
    """
    text = f"Lease extension for {safe_prop} through {new_end_date}. Sign in and accept: {invite_link}"
    return send_email(to_email, subject, html, text_content=text)


def send_manager_invite_email(to_email: str, invite_link: str, property_name: str = "a property") -> bool:
    """Send property manager invitation email with signup link."""
    subject = "[DocuStay] You've been invited as a Property Manager"
    html = f"""
    <p>Hello,</p>
    <p>You've been invited to manage <strong>{property_name}</strong> on DocuStay.</p>
    <p>Click the link below to create your account and get started:</p>
    <p><a href="{invite_link}" style="background:#2563eb;color:white;padding:10px 16px;text-decoration:none;border-radius:6px;display:inline-block;">Accept invitation</a></p>
    <p>Or copy this link: <br/><a href="{invite_link}">{invite_link}</a></p>
    <p>This link expires in 3 days. If you did not expect this invitation, you can ignore this email.</p>
    <p>— DocuStay</p>
    """
    text = f"You've been invited to manage {property_name} on DocuStay. Create your account: {invite_link}"
    return send_email(to_email, subject, html, text_content=text)


def send_property_transfer_invite_email(
    to_email: str,
    invite_link: str,
    property_name: str = "a property",
    *,
    expire_days: int = 7,
) -> bool:
    """Email a prospective owner their property ownership transfer link."""
    safe_prop = (property_name or "a property").strip() or "a property"
    subject = f"[DocuStay] You've been offered ownership of {safe_prop}"
    html = f"""
    <p>Hello,</p>
    <p>The current owner has started transferring ownership of <strong>{safe_prop}</strong> to you on DocuStay.</p>
    <p>Open the link below to sign in or create an owner account with this email address, complete onboarding if needed, then accept the transfer from your dashboard.</p>
    <p><a href="{invite_link}" style="background:#2563eb;color:white;padding:10px 16px;text-decoration:none;border-radius:6px;display:inline-block;">Review transfer</a></p>
    <p>Or copy this link:<br/><a href="{invite_link}">{invite_link}</a></p>
    <p>This link expires in {expire_days} days. If you did not expect this, you can ignore this email.</p>
    <p>— DocuStay</p>
    """
    text = f"You've been offered ownership of {safe_prop} on DocuStay. Open: {invite_link}"
    return send_email(to_email, subject, html, text_content=text)


def send_stay_ending_soon(
    to_email: str,
    guest_name: str,
    stay_end_date: str,
    region_code: str,
    is_owner: bool,
    property_name: str = "Property",
) -> bool:
    """Friendly reminder when a guest's stay is coming to an end (within configured days)."""
    if is_owner:
        subject = f"[DocuStay] Reminder: {guest_name}'s stay ends soon – {region_code}"
        intro = f"A stay for <strong>{guest_name}</strong> at <strong>{property_name}</strong> is coming to an end."
    else:
        subject = f"[DocuStay] Reminder: your stay ends soon – {region_code}"
        intro = f"Your authorized stay at <strong>{property_name}</strong> is coming to an end."
    html = f"""
    <p>Hello,</p>
    <p>{intro}</p>
    <p><strong>End date:</strong> {stay_end_date}</p>
    <p><strong>Region:</strong> {region_code}</p>
    <p>Please ensure checkout by this date to stay within your authorized period.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_overstay_alert(
    to_email: str,
    guest_name: str,
    stay_end_date: str,
    region_code: str,
    is_owner: bool,
    property_name: str = "Property",
) -> bool:
    """Alert when a stay has passed its end date (overstay triggered)."""
    if is_owner:
        subject = f"[DocuStay] Overstay alert: {guest_name} – {region_code}"
        body = (
            f"The authorized stay for <strong>{guest_name}</strong> at <strong>{property_name}</strong> "
            f"ended on <strong>{stay_end_date}</strong>. The guest may still be at the property."
        )
    else:
        subject = f"[DocuStay] Overstay notice: your stay has ended – {region_code}"
        body = (
            f"Your authorized stay at <strong>{property_name}</strong> ended on <strong>{stay_end_date}</strong>. "
            "Please vacate and complete checkout by the documented end date."
        )
    html = f"""
    <p>Hello,</p>
    <p>{body}</p>
    <p><strong>Region:</strong> {region_code}</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_vacate_12h_notice(
    to_email: str,
    guest_name: str,
    property_name: str,
    vacate_by_iso: str,
    region_code: str = "",
    *,
    property_address: str = "",
    stay_start_date: str = "",
    stay_end_date: str = "",
    revoked_at: str = "",
    invite_code: str = "",
    revoker: str = "owner",
) -> bool:
    """Email to guest when stay is revoked (Kill Switch): must vacate within 12 hours.
    revoker: 'owner' (property owner) or 'host' (tenant who invited the guest)."""
    subject = "[DocuStay] Urgent: You must vacate the property within 12 hours"
    record_url = _verify_record_url(invite_code, property_address) if invite_code else ""
    record_block = render_authorization_record_block(
        property_address=property_address,
        guest_name=guest_name,
        stay_start_date=stay_start_date,
        stay_end_date=stay_end_date,
        status="Revoked",
        revoked_at=revoked_at,
    )
    view_link = render_view_record_link(record_url) if record_url else ""
    revoker_phrase = (
        "your host (the tenant who invited you)"
        if (revoker or "").strip().lower() == "host"
        else "the property owner"
    )
    inner = f"""
    <p style="margin: 0 0 16px;">Hello {guest_name},</p>
    <p style="margin: 0 0 16px;">Your stay authorization at <strong>{property_name}</strong> has been revoked by {revoker_phrase}.</p>
    <p style="margin: 0 0 16px;"><strong>You must vacate the property within 12 hours.</strong></p>
    <p style="margin: 0 0 16px;"><strong>Vacate by:</strong> {vacate_by_iso}</p>
    {record_block}
    {view_link}
    <p style="margin: 0 0 16px;">Please remove all belongings and complete checkout by this time to avoid further action.</p>
    """
    html = wrap_email_body(inner)
    text = f"Hello {guest_name}, your stay at {property_name} has been revoked by {revoker_phrase}. You must vacate within 12 hours. Vacate by: {vacate_by_iso}. "
    if record_url:
        text += f"View your record and signed agreement: {record_url} "
    text += "— DocuStay"
    return send_email(to_email, subject, html, text_content=text)


def send_removal_notice_to_guest(
    to_email: str,
    guest_name: str,
    property_name: str,
    region_code: str = "",
    *,
    property_address: str = "",
    stay_start_date: str = "",
    stay_end_date: str = "",
    revoked_at: str = "",
    invite_code: str = "",
) -> bool:
    """Email to guest when owner initiates formal removal for overstay. Includes authorization record details and link to view/print signed agreement."""
    subject = "[DocuStay] NOTICE: Removal Initiated – You must vacate immediately"
    record_url = _verify_record_url(invite_code, property_address) if invite_code else ""
    record_block = render_authorization_record_block(
        property_address=property_address,
        guest_name=guest_name,
        stay_start_date=stay_start_date,
        stay_end_date=stay_end_date,
        status="Revoked",
        revoked_at=revoked_at,
    )
    view_link = render_view_record_link(record_url) if record_url else ""
    inner = f"""
    <p style="margin: 0 0 16px;">Hello {guest_name},</p>
    <p style="margin: 0 0 16px;">The property owner has revoked your stay authorization for <strong>{property_name}</strong>.</p>
    <p style="margin: 0 0 16px;"><strong>Your utility access (USAT token) has been revoked.</strong></p>
    <p style="margin: 0 0 16px;">Your stay authorization has ended. Please vacate the property and remove all belongings.</p>
    {record_block}
    {view_link}
    """
    html = wrap_email_body(inner)
    text = f"Hello {guest_name}, the owner has initiated removal for {property_name}. Your USAT token has been revoked. You must vacate immediately. "
    if record_url:
        text += f"View your record and signed agreement: {record_url} "
    text += "— DocuStay"
    return send_email(to_email, subject, html, text_content=text)


def send_removal_confirmation_to_owner(
    owner_email: str,
    guest_name: str,
    property_name: str,
    region_code: str = "",
    *,
    property_address: str = "",
    stay_start_date: str = "",
    stay_end_date: str = "",
    revoked_at: str = "",
    invite_code: str = "",
) -> bool:
    """Email to owner confirming removal has been initiated. Includes authorization record details and link to view record."""
    subject = f"[DocuStay] Removal Initiated – {guest_name} at {property_name}"
    record_url = _verify_record_url(invite_code, property_address) if invite_code else ""
    record_block = render_authorization_record_block(
        property_address=property_address,
        guest_name=guest_name,
        stay_start_date=stay_start_date,
        stay_end_date=stay_end_date,
        status="Revoked",
        revoked_at=revoked_at,
    )
    view_link = render_view_record_link(
        record_url,
        link_hint="View the full authorization record and signed agreement for this stay.",
    ) if record_url else ""
    inner = f"""
    <p style="margin: 0 0 16px;">Hello,</p>
    <p style="margin: 0 0 16px;">You have revoked stay authorization for <strong>{guest_name}</strong> at <strong>{property_name}</strong>.</p>
    <p style="margin: 0 0 16px;"><strong>Actions taken:</strong></p>
    <ul style="margin: 0 0 16px; padding-left: 1.5em;">
        <li>Guest's USAT token has been revoked (utility access disabled)</li>
        <li>Guest has been notified via email to vacate immediately</li>
        <li>All actions logged in the audit trail</li>
    </ul>
    {record_block}
    {view_link}
    """
    html = wrap_email_body(inner)
    text = f"Hello, you have initiated removal for {guest_name} at {property_name}. USAT token revoked. Guest notified. "
    if record_url:
        text += f"View record: {record_url} "
    text += "— DocuStay"
    return send_email(owner_email, subject, html, text_content=text)


def send_owner_guest_checkout_email(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Email to owner when a guest completes checkout (ends their stay)."""
    subject = f"[DocuStay] Guest checked out – {guest_name} at {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>{guest_name}</strong> has completed checkout for their stay at <strong>{property_name}</strong>.</p>
    <p><strong>Checkout date:</strong> {stay_end_date}</p>
    <p>The stay is now ended and all statuses have been updated.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_guest_checkout_confirmation_email(
    guest_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Email to guest confirming their checkout."""
    subject = f"[DocuStay] Checkout Confirmed – {property_name}"
    html = f"""
    <p>Hello {guest_name},</p>
    <p>Your checkout from <strong>{property_name}</strong> has been confirmed.</p>
    <p><strong>Checkout date:</strong> {stay_end_date}</p>
    <p>Thank you for using DocuStay. Your stay record has been updated.</p>
    <p>— DocuStay</p>
    """
    return send_email(guest_email, subject, html)


def send_owner_guest_cancelled_stay_email(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_start_date: str,
) -> bool:
    """Email to owner when a guest cancels a future stay."""
    subject = f"[DocuStay] Guest cancelled stay – {guest_name} at {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>{guest_name}</strong> has cancelled their upcoming stay at <strong>{property_name}</strong> (was scheduled to start {stay_start_date}).</p>
    <p>The stay is no longer active.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_stay_legal_warning(
    to_email: str,
    guest_name: str,
    stay_end_date: str,
    region_code: str,
    statute_ref: str,
    is_owner: bool,
) -> bool:
    """Module G: Stay limit reminder email (region, documented end date)."""
    subject = f"[DocuStay] Stay approaching end date – {region_code}"
    html = f"""
    <p>Hello,</p>
    <p>Reminder: the documented stay for <strong>{guest_name}</strong> is approaching its end date.</p>
    <p><strong>Stay end date:</strong> {stay_end_date}</p>
    <p><strong>Region:</strong> {region_code}</p>
    <p><strong>Region reference:</strong> {statute_ref}</p>
    <p>Please ensure checkout by the end date so the stay record stays accurate.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_dead_mans_switch_48h_before(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Status Confirmation: 48 hours before tenant lease end (property/management lane only; internal jobs gate tenant-lane guest stays)."""
    subject = f"[DocuStay] Confirm property status – lease ends in 2 days – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Status Confirmation:</strong> The documented stay/lease for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends in 2 days.</p>
    <p><strong>Lease end date:</strong> {stay_end_date}</p>
    <p><strong>Is this unit/property now VACANT or OCCUPIED?</strong> Please sign in to DocuStay and tap <strong>Vacant</strong> or <strong>Occupied</strong> in Notifications (or on the property page). To extend the lease with a new end date, use <strong>Lease renewed</strong> there. Only an assigned property manager or the owner can respond. If we do not hear from you within 48 hours after the lease end date, occupancy will be marked <strong>Unknown</strong> until you respond; we will keep sending reminders. DocuStay does not change Shield Mode or set the unit to vacant on your behalf.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_dead_mans_switch_48h_before_to_owner_and_managers(
    owner_email: str,
    manager_emails: list[str],
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> None:
    """Status Confirmation: 48h before lease end – property manager(s) if assigned, otherwise owner."""
    subject = f"[DocuStay] Confirm property status – lease ends in 2 days – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Status Confirmation:</strong> The documented stay/lease for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends in 2 days.</p>
    <p><strong>Lease end date:</strong> {stay_end_date}</p>
    <p><strong>Is this unit/property now VACANT or OCCUPIED?</strong> Please sign in to DocuStay and tap <strong>Vacant</strong> or <strong>Occupied</strong> in Notifications (or on the property page). To extend the lease with a new end date, use <strong>Lease renewed</strong> there. Only an assigned property manager or the owner can respond. If we do not hear from you within 48 hours after the lease end date, occupancy will be marked <strong>Unknown</strong> until you respond; we will keep sending reminders. DocuStay does not change Shield Mode or set the unit to vacant on your behalf.</p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_dead_mans_switch_urgent_today(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Status Confirmation: on tenant lease end date."""
    subject = f"[DocuStay] URGENT – Confirm property status – lease ends today – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Status Confirmation – urgent:</strong> The documented stay/lease for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends <strong>today</strong> ({stay_end_date}).</p>
    <p><strong>Is this unit/property now VACANT or OCCUPIED?</strong> Please update DocuStay now — use <strong>Vacant</strong> or <strong>Occupied</strong> in Notifications or on the property page (or <strong>Lease renewed</strong> with a new end date). If we do not hear from you within 48 hours after the lease end date, occupancy will be marked <strong>Unknown</strong> until you respond, and reminders will continue. DocuStay does not enable Shield Mode or set vacancy automatically.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_dead_mans_switch_urgent_today_to_owner_and_managers(
    owner_email: str,
    manager_emails: list[str],
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> None:
    """Status Confirmation: lease ends today – PM(s) if assigned, else owner."""
    subject = f"[DocuStay] URGENT – Confirm property status – lease ends today – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Status Confirmation – urgent:</strong> The documented stay/lease for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends <strong>today</strong> ({stay_end_date}).</p>
    <p><strong>Is this unit/property now VACANT or OCCUPIED?</strong> Please update DocuStay now — use <strong>Vacant</strong> or <strong>Occupied</strong> in Notifications or on the property page (or <strong>Lease renewed</strong> with a new end date). If we do not hear from you within 48 hours after the lease end date, occupancy will be marked <strong>Unknown</strong> until you respond, and reminders will continue. DocuStay does not enable Shield Mode or set vacancy automatically.</p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_shield_mode_activated_email(
    owner_email: str,
    property_name: str,
    *,
    triggered_by_dead_mans_switch: bool = False,
    last_day_of_stay: bool = False,
    guest_name: str | None = None,
) -> bool:
    """Notify owner when Shield Mode is activated (e.g. last day of tenant lease)."""
    if triggered_by_dead_mans_switch:
        subject = f"[DocuStay] Shield Mode activated – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been automatically activated</strong> for <strong>{property_name}</strong>.</p>
    <p>This path is reserved for manual or other automated rules. Status Confirmation alone does not enable Shield Mode.</p>
    <p>You can turn Shield Mode off anytime in your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    elif last_day_of_stay:
        guest = f" ({guest_name})" if guest_name else ""
        subject = f"[DocuStay] Shield Mode activated – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been automatically activated</strong> for <strong>{property_name}</strong>.</p>
    <p>Today is the last day of your guest's stay{guest}. Shield Mode is now on. DocuStay is actively monitoring status.</p>
    <p>You can turn Shield Mode off anytime in your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    else:
        subject = f"[DocuStay] Shield Mode activated – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been activated</strong> for <strong>{property_name}</strong>.</p>
    <p>DocuStay is now actively monitoring and enforcing for this property. You can turn it off anytime in your dashboard.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_vacant_monitoring_prompt(
    owner_email: str,
    property_name: str,
    response_due_date: str,
) -> bool:
    """Vacant-unit monitoring: prompt owner to confirm unit is still vacant. Response due by response_due_date."""
    subject = f"[DocuStay] Confirm vacancy – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p>You have <strong>vacant-unit monitoring</strong> enabled for <strong>{property_name}</strong>.</p>
    <p>Please confirm that this unit is still vacant by <strong>{response_due_date}</strong> in your DocuStay dashboard. If we do not receive your confirmation, the property status will be set to UNCONFIRMED and Shield Mode will be activated.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_vacant_monitoring_flipped(
    owner_email: str,
    property_name: str,
) -> bool:
    """Vacant-unit monitoring: no response by deadline – status flipped to UNCONFIRMED, Shield on."""
    subject = f"[DocuStay] Vacant monitoring – status set to UNCONFIRMED – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p>No response was received by the deadline for your vacant-unit monitoring prompt for <strong>{property_name}</strong>.</p>
    <p>The system has set occupancy status to <strong>UNCONFIRMED</strong> and activated <strong>Shield Mode</strong> for this property. You can confirm occupancy or adjust settings in your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_shield_mode_turned_on_notification(
    owner_email: str,
    manager_emails: list[str],
    property_name: str,
    *,
    turned_on_by: str = "property owner",
) -> None:
    """Notify property manager(s) if assigned, else owner, when Shield Mode is turned on."""
    subject = f"[DocuStay] Shield Mode turned on – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been turned on</strong> for <strong>{property_name}</strong> by the {turned_on_by}.</p>
    <p>DocuStay is now actively monitoring this property. You can turn it off anytime in your dashboard.</p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_shield_mode_turned_off_notification(
    owner_email: str,
    manager_emails: list[str],
    property_name: str,
    *,
    turned_off_by: str = "property owner",
) -> None:
    """Notify property manager(s) if assigned, else owner, when Shield Mode is turned off."""
    subject = f"[DocuStay] Shield Mode turned off – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been turned off</strong> for <strong>{property_name}</strong> by the {turned_off_by}.</p>
    <p>DocuStay is no longer actively monitoring this property. You can turn it back on anytime in your dashboard.</p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_dead_mans_switch_enabled_notification(
    owner_email: str,
    manager_emails: list[str],
    property_name: str,
    guest_name: str,
    stay_end_date: str,
) -> None:
    """Notify PM(s) or owner when Status Confirmation reminders are scheduled for a tenant lease at the property."""
    subject = f"[DocuStay] Status Confirmation scheduled – tenant lease – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Status Confirmation</strong> reminders are enabled for the tenant stay at <strong>{property_name}</strong>.</p>
    <p>Tenant / lease name on file: <strong>{guest_name}</strong>. Lease end date: <strong>{stay_end_date}</strong>.</p>
    <p>You will receive prompts 48 hours before and on the lease end date. If no confirmation is received within 48 hours after the lease ends, occupancy will show as <strong>Unknown</strong> until you respond, and reminders will continue. DocuStay will not set vacancy or enable Shield Mode automatically.</p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_dms_triggered_set_status_notification(
    owner_email: str,
    manager_emails: list[str],
    property_name: str,
    property_id: int,
    guest_name: str,
    stay_end_date: str,
) -> None:
    """After deadline with no response: occupancy Unknown; deep link for PM or owner to confirm."""
    owner_url = _property_page_url(property_id, for_manager=False)
    manager_url = _property_page_url(property_id, for_manager=True)
    subject = f"[DocuStay] Confirm property status – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Status Confirmation:</strong> No response was received within 48 hours after the lease end date ({stay_end_date}) for <strong>{guest_name}</strong> at <strong>{property_name}</strong>.</p>
    <p><strong>Is the property currently occupied or vacant?</strong> Occupancy is <strong>Unknown</strong> until you confirm in DocuStay (Vacated, Renewed, or Holdover). We will keep sending reminders until you respond. Shield Mode is not turned on by this step.</p>
    <p><strong>Property owners:</strong> <a href="{owner_url}">Open property page</a></p>
    <p><strong>Property managers:</strong> <a href="{manager_url}">Open property page</a></p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_status_confirmation_daily_reminder_email(
    owner_email: str,
    manager_emails: list[str],
    property_name: str,
    property_id: int,
    guest_name: str,
    stay_end_date: str,
) -> None:
    """Ongoing reminder while occupancy is Unknown and lease confirmation is still pending."""
    owner_url = _property_page_url(property_id, for_manager=False)
    manager_url = _property_page_url(property_id, for_manager=True)
    subject = f"[DocuStay] Reminder: confirm property status – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p>This is a reminder to confirm occupancy for <strong>{property_name}</strong> (guest/tenant on file: <strong>{guest_name}</strong>, stay/lease ended {stay_end_date}).</p>
    <p><strong>Is the property currently occupied or vacant?</strong> Occupancy remains <strong>Unknown</strong> until you choose Vacated, Renewed, or Holdover in DocuStay. We will continue sending reminders until you respond.</p>
    <p><strong>Property owners:</strong> <a href="{owner_url}">Open property page</a></p>
    <p><strong>Property managers:</strong> <a href="{manager_url}">Open property page</a></p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_tenant_guest_authorization_ending_notice(
    tenant_email: str,
    guest_name: str,
    property_name: str,
    stay_start_date: str,
    stay_end_date: str,
    *,
    ends_today: bool,
) -> bool:
    """Tenant invited this guest – alert that the guest's authorization period is ending (not a property status prompt)."""
    if ends_today:
        subject = f"[DocuStay] Your guest's stay ends today – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p>The guest stay you authorized for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends <strong>today</strong> ({stay_end_date}).</p>
    <p><strong>Stay period:</strong> {stay_start_date} – {stay_end_date}</p>
    <p>This is an informational notice only. Property status confirmation goes to your property manager or owner separately for tenant leases.</p>
    <p>— DocuStay</p>
    """
    else:
        subject = f"[DocuStay] Your guest's stay ends in 2 days – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p>The guest stay you authorized for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends in 2 days ({stay_end_date}).</p>
    <p><strong>Stay period:</strong> {stay_start_date} – {stay_end_date}</p>
    <p>This is an informational notice only.</p>
    <p>— DocuStay</p>
    """
    return send_email(tenant_email, subject, html)


def send_tenant_guest_jurisdiction_threshold_approaching_notice(
    tenant_email: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Tenant who invited the guest: alert that the stay is approaching the jurisdiction threshold (2-day buffer rule)."""
    subject = f"[DocuStay] Your guest's stay is approaching the jurisdiction threshold – {property_name}"
    html = f"""
<p>Hello,</p>
<p><strong>Your guest's stay is approaching the threshold.</strong></p>
<p>Based on the documented stay end date ({stay_end_date}) for <strong>{property_name}</strong>, this stay is within the final 2-day buffer before the jurisdiction threshold.</p>
<p>You can let it expire naturally, or sign in to DocuStay and issue a <strong>new guest invitation</strong>. When your guest accepts a new invitation, it replaces the previous authorization.</p>
<p>— DocuStay</p>
"""
    return send_email(tenant_email, subject, html)


def send_guest_authorization_dates_only_email(
    guest_email: str,
    stay_start_date: str,
    stay_end_date: str,
    *,
    ends_today: bool,
) -> bool:
    """Guest: informational only—authorized stay period. No property status or owner/manager prompts."""
    if ends_today:
        subject = "[DocuStay] Reminder: your authorized stay ends today"
        core = f"""    <p>Your stay runs from <strong>{stay_start_date}</strong> to <strong>{stay_end_date}</strong>.</p>"""
    else:
        subject = "[DocuStay] Reminder: your authorized stay is ending soon"
        core = f"""    <p>Your stay runs from <strong>{stay_start_date}</strong> to <strong>{stay_end_date}</strong>.</p>"""
    body = f"""
    <p>Hello,</p>
{core}
    <p>— DocuStay</p>
    """
    return send_email(guest_email, subject, body)


def send_guest_extension_request_to_tenant_email(
    tenant_email: str,
    guest_name: str,
    property_name: str,
    stay_start_date: str,
    stay_end_date: str,
    guest_note: str | None = None,
) -> bool:
    """Tenant who invited the guest: extension interest routes here only (not owner/PM)."""
    note_block = ""
    if guest_note and str(guest_note).strip():
        note_block = f"<p><strong>Note from guest:</strong> {html.escape(str(guest_note).strip())}</p>"
    subject = f"[DocuStay] Your guest asked about extending their stay – {property_name}"
    body = f"""
    <p>Hello,</p>
    <p><strong>{html.escape(guest_name)}</strong> is asking about a longer stay at <strong>{html.escape(property_name)}</strong>.</p>
    <p>Their current stay runs from <strong>{html.escape(stay_start_date)}</strong> to <strong>{html.escape(stay_end_date)}</strong>.</p>
    {note_block}
    <p>If you can accommodate new dates, sign in to DocuStay and <strong>create a new guest invitation</strong> from your tenant dashboard. When your guest accepts it, it replaces the previous authorization.</p>
    <p>This message went to you as the person who invited them, not to the property owner or manager.</p>
    <p>— DocuStay</p>
    """
    return send_email(tenant_email, subject, body)


def send_guest_extension_approved_email(
    guest_email: str,
    property_name: str,
    *,
    current_stay_start: str,
    current_stay_end: str,
    new_stay_start: str,
    new_stay_end: str,
    invite_url: str,
    invitation_code: str,
    host_note: str | None = None,
) -> bool:
    """Guest: tenant approved extension and attached the new invitation link (extension = new invite)."""
    prop_safe = html.escape(property_name)
    raw_note = (str(host_note).strip() if host_note else "") or ""
    note_html = ""
    note_text = ""
    if raw_note:
        esc = html.escape(raw_note)
        note_html = f"<p><strong>Note from your host:</strong> {esc}</p>"
        note_text = f"Note from your host: {raw_note}\n\n"
    safe_url = html.escape(invite_url, quote=True)
    code_stripped = (invitation_code or "").strip()
    safe_code = html.escape(code_stripped, quote=True)
    subject = f"[DocuStay] Your host agreed you can extend – {property_name}"
    text_content = f"""Hello,

Your host approved your longer stay at {property_name}. Use the link below to open DocuStay-Sign and accept your new invitation for the extended dates.

Your current authorization (until you accept the new invite): {current_stay_start} to {current_stay_end}
New stay dates on the invitation: {new_stay_start} to {new_stay_end}

{note_text}DocuStay-Sign — new invitation (accept and sign):
{invite_url}

Invite ID: {code_stripped}

Open the link, sign in if prompted, and complete acceptance and any signing steps. When you finish, this authorization replaces your previous one for the new dates.

— DocuStay
"""
    body = f"""
    <p>Hello,</p>
    <p>Your host has <strong>approved</strong> your longer stay at <strong>{prop_safe}</strong>. Below is your <strong>new guest invitation</strong> for the extended dates — use <strong>DocuStay-Sign</strong> to accept and complete any signing steps.</p>
    <p><strong>Your current authorization (until you accept the new invite):</strong> {html.escape(current_stay_start)} to {html.escape(current_stay_end)}</p>
    <p><strong>New stay dates on the invitation:</strong> {html.escape(new_stay_start)} to {html.escape(new_stay_end)}</p>
    {note_html}
    <p style="margin:20px 0;"><a href="{safe_url}" style="background:#2563eb;color:white;padding:12px 20px;text-decoration:none;border-radius:6px;display:inline-block;font-weight:600;">DocuStay-Sign</a></p>
    <p><strong>New invitation link</strong> (copy and paste if the button does not open):<br/>
    <a href="{safe_url}">{safe_url}</a></p>
    <p><strong>Invite ID:</strong> {safe_code}</p>
    <p>When you finish in DocuStay-Sign, this authorization replaces your previous one for the new dates.</p>
    <p>— DocuStay</p>
    """
    return send_email(guest_email, subject, body, text_content=text_content)


def send_guest_extension_declined_email(
    guest_email: str,
    property_name: str,
    stay_start_date: str,
    stay_end_date: str,
    *,
    host_note: str | None = None,
) -> bool:
    """Guest: tenant is not extending / declined the request."""
    note = ""
    if host_note and str(host_note).strip():
        note = f"<p><strong>Note from your host:</strong> {html.escape(str(host_note).strip())}</p>"
    else:
        note = "<p>Please refer to your original stay dates below.</p>"
    subject = f"[DocuStay] Update on your stay extension request – {property_name}"
    body = f"""
    <p>Hello,</p>
    <p>Your host is <strong>not approving</strong> an extension for your stay at <strong>{html.escape(property_name)}</strong> at this time.</p>
    <p>Your current stay remains <strong>{html.escape(stay_start_date)}</strong> to <strong>{html.escape(stay_end_date)}</strong> unless you receive a new invitation from them.</p>
    {note}
    <p>— DocuStay</p>
    """
    return send_email(guest_email, subject, body)


def send_dms_turned_off_notification(
    owner_email: str,
    manager_emails: list[str],
    property_name: str,
    guest_name: str,
    stay_end_date: str,
    reason: str = "occupancy confirmed",
) -> None:
    """Notify PM(s) or owner when Status Confirmation reminders are turned off for a tenant stay."""
    subject = f"[DocuStay] Status Confirmation reminders off – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Status Confirmation</strong> reminders have been turned off for the tenant stay at <strong>{property_name}</strong>.</p>
    <p>Tenant / guest on file: <strong>{guest_name}</strong>. Stay end date: <strong>{stay_end_date}</strong>.</p>
    <p>Reason: {reason}.</p>
    <p>— DocuStay</p>
    """
    _send_email_to_pm_or_owner(owner_email, manager_emails, subject, html)


def send_tenant_guest_accepted_invite(
    tenant_email: str,
    guest_name: str,
    property_name: str,
) -> bool:
    """Notify tenant when a guest accepts an invitation they created."""
    subject = f"[DocuStay] Guest accepted your invitation – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>{guest_name}</strong> has accepted your invitation for <strong>{property_name}</strong>.</p>
    <p>The stay is now active. You can view details in your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    return send_email(tenant_email, subject, html)


def send_sms(to_phone: str, body: str) -> bool:
    """Optional SMS via Twilio."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(body=body, from_=settings.twilio_from_phone_number, to=to_phone)
        return True
    except Exception:
        return False
