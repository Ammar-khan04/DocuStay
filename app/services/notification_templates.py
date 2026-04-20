"""
Shared email templates for DocuStay notifications.
Use these when building notification emails so record blocks and links stay consistent.
Add new notification types by composing these blocks with notification-specific content.
"""


# Shared styles for email compatibility (inline, widely supported)
EMAIL_FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
EMAIL_BODY_STYLE = f"margin:0; font-family: {EMAIL_FONT_FAMILY}; font-size: 16px; line-height: 1.5; color: #1e293b;"
EMAIL_SECTION_STYLE = "margin: 20px 0; padding: 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;"
EMAIL_LABEL_STYLE = "font-weight: 600; color: #475569; font-size: 14px;"
EMAIL_VALUE_STYLE = "color: #0f172a;"
EMAIL_BUTTON_STYLE = "display: inline-block; padding: 12px 24px; background: #2563eb; color: white !important; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;"
EMAIL_LINK_HINT_STYLE = "font-size: 14px; color: #64748b; margin-top: 8px;"


def render_authorization_record_block(
    *,
    property_address: str = "",
    guest_name: str = "",
    stay_start_date: str = "",
    stay_end_date: str = "",
    status: str = "",
    revoked_at: str = "",
    cancelled_at: str = "",
    checked_out_at: str = "",
) -> str:
    """
    Render the authorization record block for inclusion in notification emails.
    All fields are optional; only non-empty values are shown.
    Use for revocation, removal, checkout, and other stay-related notifications.
    """
    rows: list[str] = []
    if property_address:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Property</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{property_address}</td></tr>')
    if guest_name:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Guest</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{guest_name}</td></tr>')
    if stay_start_date and stay_end_date:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Authorization period</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{stay_start_date} – {stay_end_date}</td></tr>')
    elif stay_start_date:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Start date</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{stay_start_date}</td></tr>')
    elif stay_end_date:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">End date</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{stay_end_date}</td></tr>')
    if status:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Status</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{status}</td></tr>')
    if revoked_at:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Revoked</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{revoked_at}</td></tr>')
    if cancelled_at:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Cancelled</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{cancelled_at}</td></tr>')
    if checked_out_at:
        rows.append(f'<tr><td style="{EMAIL_LABEL_STYLE} padding: 6px 12px 6px 0; vertical-align: top;">Checked out</td><td style="{EMAIL_VALUE_STYLE} padding: 6px 0;">{checked_out_at}</td></tr>')

    if not rows:
        return ""

    table_rows = "\n      ".join(rows)
    return f"""
    <div style="{EMAIL_SECTION_STYLE}">
      <p style="margin: 0 0 12px; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: #475569;">Authorization record</p>
      <table style="width: 100%; border-collapse: collapse;">
        {table_rows}
      </table>
    </div>
"""


def render_view_record_link(
    record_url: str,
    *,
    button_text: str = "View record & signed agreement",
    link_hint: str = "View the full authorization record and print your signed agreement at the link above.",
) -> str:
    """
    Render the CTA block with a button linking to the verify/record page.
    Use whenever a stay record can be viewed (revocation, removal, etc.).
    """
    return f"""
    <div style="margin: 24px 0;">
      <a href="{record_url}" style="{EMAIL_BUTTON_STYLE}">{button_text}</a>
      <p style="{EMAIL_LINK_HINT_STYLE}">{link_hint}</p>
    </div>
"""


def wrap_email_body(inner_html: str) -> str:
    """
    Wrap notification content in a consistent email shell with DocuStay styling.
    Use for all notification emails.
    """
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="{EMAIL_BODY_STYLE}">
  <div style="max-width: 560px; margin: 0 auto; padding: 24px;">
    <div style="margin-bottom: 24px; padding-bottom: 16px; border-bottom: 2px solid #2563eb;">
      <span style="font-size: 24px; font-weight: 700; color: #2563eb; letter-spacing: -0.02em;">DocuStay</span>
    </div>
    {inner_html}
    <p style="margin: 24px 0 0; color: #64748b; font-size: 14px;">— DocuStay</p>
  </div>
</body>
</html>
"""
