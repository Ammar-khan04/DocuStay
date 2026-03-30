/** Loose but practical check aligned with HTML5 type="email" + backend EmailStr. */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidInviteEmailFormat(email: string): boolean {
  const s = (email || '').trim();
  if (!s || s.length > 254) return false;
  return EMAIL_RE.test(s);
}
