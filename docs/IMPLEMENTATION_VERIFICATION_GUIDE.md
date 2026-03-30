# DocuStay Implementation Verification Guide

## 1. Revocation Emails & Record Access

- **Where:** Owner Dashboard (Personal mode) → Guests tab → active stay → **Revoke**; overstayed stay → **Initiate removal**
- **Verify page:** `/#check` or `/#check?token=INV-XXXX`
- **Check:** Email has property address, guest name, dates, status, revocation date, working link to verify page; verify page shows full record + signed agreement PDF link

---

## 2. Stay End Reminders

- **Where:** Personal mode → Invitations → Create guest invite (toggle Stay end reminders on); Tenant Dashboard → Create guest invite
- **Check:** Owner receives email when invite created with toggle on; wording says "Stay end reminders" not "Dead Man's Switch"

---

## 3. Tenant Scope Clarification

- **Where:** Tenant Dashboard → Cancel future assignment; Event ledger, Verify page, stay cards for token states
- **Check:** No "Revoke tenant" or "Expire tenant" anywhere; REVOKED = guest revoked by owner; CANCELLED = tenant self-cancel; guest invites can expire, tenant invites do not

---

## 4. User-Facing Terminology

- **Terms:** Stay end reminders (not Dead Man's Switch), Revoke (not Kill Switch), Active/Pending/Revoked (not BURNED/STAGED)
- **Where:** Dashboard, buttons, emails, Help Center, Verify page, Event ledger
- **Check:** No old terminology in UI

---

## 5. Revocation Email Recipients

- Revoke → Guest gets vacate 12h notice
- Initiate removal → Guest gets removal notice, Owner gets confirmation

---

## 6. Landing, Terms, Privacy Policy

- **Where:** `/#` (landing), `/#terms`, `/#privacy` or footer links
- **Check:** Footer links work; pages render fully

---

## 7. Personal vs. Business Mode (Privacy Lanes)

- **Where:** Owner/Manager Dashboard → Mode switcher (Business/Personal)
- **Business mode:** Properties, Billing, Event ledger only — no Guests or Invitations; units show Occupied/Vacant only (no names)
- **Personal mode:** + Guests, Invitations tabs; owner sees only their own invites/stays (never tenant-invited guest data)
- **Check:** Event ledger has no tenant guest events; public live page shows "Guest" not real name for tenant-invited guests


