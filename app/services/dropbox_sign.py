"""Dropbox Sign (HelloSign) API integration for e-signatures and signed PDFs."""
from __future__ import annotations

from app.config import get_settings

settings = get_settings()
BASE_URL = "https://api.hellosign.com/v3"


def _auth() -> tuple[str, str]:
    """Basic auth: API key as username, empty password."""
    key = (settings.dropbox_sign_api_key or "").strip()
    return (key, "")


def send_signature_request(
    pdf_bytes: bytes,
    title: str,
    signer_email: str,
    signer_name: str,
    subject: str = "DocuStay – Please sign the agreement",
    message: str = "Please sign this agreement to complete your stay authorization.",
) -> tuple[str | None, str | None]:
    """
    Send a signature request via Dropbox Sign.
    Returns (signature_request_id, signer_signature_id) on success, (None, None) on failure.
    The signer receives an email; signer_signature_id is used to get the embedded sign URL.
    """
    if not settings.dropbox_sign_api_key:
        return (None, None)
    try:
        import httpx

        url = f"{BASE_URL}/signature_request/send"
        files = [("files[]", ("agreement.pdf", pdf_bytes, "application/pdf"))]
        data = {
            "title": title[:255],
            "subject": subject[:255],
            "message": message[:5000],
            "signers[0][email_address]": signer_email,
            "signers[0][name]": (signer_name or signer_email)[:255],
        }
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, auth=_auth(), data=data, files=files)
        if r.status_code != 200:
            return (None, None)
        out = r.json()
        req = out.get("signature_request") or {}
        request_id = req.get("signature_request_id")
        signatures = req.get("signatures") or []
        signer_sig_id = signatures[0].get("signature_id") if signatures else None
        if not signer_sig_id and request_id:
            req_full = get_signature_request(request_id)
            if req_full:
                sigs = req_full.get("signatures") or []
                signer_sig_id = sigs[0].get("signature_id") if sigs else None
        return (request_id, signer_sig_id)
    except Exception:
        return (None, None)


def get_embedded_sign_url(signer_signature_id: str) -> str | None:
    """
    Get the embedded sign URL for the given signer signature_id.
    The URL can be opened in a new tab for the user to sign.
    """
    if not settings.dropbox_sign_api_key or not signer_signature_id:
        return None
    try:
        import httpx

        url = f"{BASE_URL}/embedded/sign_url/{signer_signature_id}"
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, auth=_auth())
        if r.status_code != 200:
            return None
        out = r.json()
        embedded = out.get("embedded") or {}
        return embedded.get("sign_url")
    except Exception:
        return None


def get_signature_request(signature_request_id: str) -> dict | None:
    """Get signature request status. Returns dict with is_complete, signatures, etc."""
    if not settings.dropbox_sign_api_key:
        return None
    try:
        import httpx

        url = f"{BASE_URL}/signature_request/{signature_request_id}"
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, auth=_auth())
        if r.status_code != 200:
            return None
        return r.json().get("signature_request")
    except Exception:
        return None


def get_signed_pdf(signature_request_id: str) -> bytes | None:
    """Download the combined signed PDF. Returns None if not complete or error."""
    req = get_signature_request(signature_request_id)
    if not req or not req.get("is_complete"):
        return None
    try:
        import httpx

        url = f"{BASE_URL}/signature_request/files/{signature_request_id}"
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, auth=_auth(), params={"file_type": "pdf"})
        if r.status_code != 200:
            return None
        return r.content
    except Exception:
        return None
