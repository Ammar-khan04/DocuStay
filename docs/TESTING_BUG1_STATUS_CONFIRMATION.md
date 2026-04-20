# Testing: Bug 1 — Status Confirmation & Bug 2 — Guest end-of-stay / extension

This document describes how to verify **Bug 1**: correct Status Confirmation trigger, user-facing language, no-response outcome, recipient routing, and tenant/guest messaging when a **tenant-invited guest** stay ends—and **Bug 2**: guest end-of-stay email must be informational only (not property status), plus the **guest → tenant** extension request flow. It also covers **Product Change 1**: **Shield Mode always on** (CR-1a) and **Product Change 2**: **$10/month flat + 7-day free trial** (CR-3a–c), including how to confirm each from the UI.

**Scope note (Bug 1):** Status Confirmation applies to **property/management-lane** stays (owner or property manager invited the occupier). It does **not** run for **tenant-lane** stays (guest invited by a tenant). See Bug 1a.

---

## Prerequisites

- Backend running with a real database and email configured (or watch server logs / Mailgun output).
- Test users: **owner** (or PM with personal guest scope), **tenant** (assigned unit), **guest** accounts as needed.
- Optional: `DMS_TEST_MODE=true` in `.env` for a **short** timeline (effective “lease end” minutes after check-in) on **property-lane** Status Confirmation only. Tenant-lane stays are still excluded from that flow. **Tenant/guest “guest stay ending” emails use real calendar dates (`today` / `today+2`) and still send when `DMS_TEST_MODE=true`.**

---

## Run the jobs manually (without waiting for cron)

From the repository root, with the same environment as the API (venv, `.env` loaded):

```bash
python -c "from app.database import SessionLocal; from app.services.stay_timer import run_dead_mans_switch_job, run_tenant_lane_guest_stay_ending_notifications, run_status_confirmation_daily_reminder_job; db=SessionLocal(); run_dead_mans_switch_job(db); run_tenant_lane_guest_stay_ending_notifications(db); run_status_confirmation_daily_reminder_job(db); db.close()"
```

For the full daily chain (legal warnings, overstays, etc.), use `run_stay_notification_job` if `notification_cron_enabled` is true in settings.

---

## Bug 1a — Wrong trigger (guest stay vs tenant lease)

**Intent:** Status Confirmation must **not** fire because a **tenant-invited guest** stay ended. It **may** still fire for **owner/manager-invited** stays (tenant lease or guest), depending on product rules.

### How to test (tenant-invited guest — must NOT trigger)

1. As **tenant**, create a **guest** invitation (guest kind), dates that include “2 days before end,” “end today,” and “48h after end” as needed.
2. As **guest**, accept, sign, **check in**.
3. Run the stay timer jobs (command above) on days that match those milestones (or adjust `stay_end_date` in the DB for a controlled test).
4. **Pass if:**
   - No “Confirm property status” / Status Confirmation emails go to **property manager or owner** for that stay.
   - No `dms_48h` / `dms_urgent` / `dms_executed` dashboard alerts for **owner/PM** tied to this stay for Status Confirmation (see Bug 1e for what *should* fire for tenant/guest).

### How to test (owner/manager-invited lease — should still trigger)

1. As **owner** or **PM**, create/accept flows so there is a **property-lane** stay (typical **tenant** lease invitation from owner/manager), guest/tenant **checked in**, `dead_mans_switch` behavior enabled per normal prod rules (DMS turns on 48h before lease end in production).
2. Align `stay_end_date` so the job hits 48h-before, end day, and 48h-after-deadline as needed.
3. Run `run_dead_mans_switch_job`.
4. **Pass if:** PM or owner receives Status Confirmation emails (see 1d) and the flow progresses through the expected stages—these stays are **not** tenant-lane and are **in** scope.

---

## Bug 1b — Wrong language (“Dead Man’s Switch”)

**Intent:** End users must not see “Dead Man’s Switch” in email subjects/bodies or in surfaced event labels that users read.

### How to test

1. Trigger any Status Confirmation email (property-lane stay, stages above) and open the message.
2. Open the **Event ledger** or audit UI that shows human-readable action titles for DMS-related events.
3. **Pass if:**
   - Subjects/bodies use **Status Confirmation** / **Confirm property status** (or equivalent), not “Dead Man’s Switch.”
   - Ledger display titles for DMS action types use user-appropriate wording (see `app/services/event_ledger.py`).

---

## Bug 1c — Wrong no-response outcome (vacant + Shield)

**Intent:** If there is no confirmation by the deadline, occupancy becomes **Unknown**; the system does **not** set vacant, does **not** enable Shield Mode, and does **not** stage USAT as part of this step. Reminders continue.

### How to test

1. Use a **property-lane** stay past “48h after lease end” with **no** `occupancy_confirmation_response`, DMS still on, not checked out.
2. Run `run_dead_mans_switch_job` once.
3. **Pass if:**
   - Property `occupancy_status` is **`unknown`** (not `unconfirmed` from this flow alone).
   - `shield_mode_enabled` is **unchanged** by this step (remains off unless something else turned it on).
   - No email claiming the system set vacancy or turned Shield on because of no response.
4. Run `run_status_confirmation_daily_reminder_job` on subsequent calendar days (UTC).
5. **Pass if:** PM/owner receive **reminder** emails / `dms_reminder` alerts until someone confirms (vacated / renewed / holdover).

---

## Bug 1d — Wrong recipient (tenant/guest vs PM/owner)

**Intent:** Status Confirmation prompts go to **assigned property manager(s)** if any; otherwise **owner**. Not to tenant or guest.

### How to test (PM assigned)

1. Property has at least one **PropertyManagerAssignment** with a manager who has a distinct email from the owner.
2. Trigger Status Confirmation (48h-before or urgent) for a property-lane stay on that property.
3. **Pass if:** Email goes to **manager mailbox(es)** and **not** to the owner **when managers exist** (and not to tenant/guest).

### How to test (no PM)

1. Same property with **no** manager assignments.
2. Trigger the same emails.
3. **Pass if:** Email goes to **owner** only (for that routing rule), not tenant/guest.

---

## Bug 1e — Wrong guest messaging (tenant-invited guest stay ending)

**Intent:** When a **tenant-invited guest** stay is ending: **tenant** gets an alert about their guest; **guest** gets **dates only**. Neither receives a **property status** prompt.

### How to test

1. Tenant-lane guest stay **checked in**; `stay_end_date` = **today + 2 days** or **today** (for the two windows implemented).
2. Run `run_tenant_lane_guest_stay_ending_notifications` (or full notification job).
3. **Pass if:**
   - **Tenant** receives email + in-app alert type `guest_stay_ending` (if alerts are enabled) about the guest’s stay ending; copy is **not** “confirm property status.”
   - **Guest** receives email with **stay start/end dates** only, no property-status confirmation language.
   - **Owner/PM** do **not** receive Status Confirmation emails **for this stay** (same as 1a).

---

## Bug 2 — Guest end-of-stay email & extension request (tenant lane)

**Intent:** Guests must not receive property status / “confirm occupancy” style email when their **tenant-invited** stay is ending. The scheduled guest email must be informational: **“Your stay runs from [start] to [end].”** Optionally, the guest may request a longer stay; that request must reach **only the tenant who invited them**, not the owner or property manager.

### Bug 2a — Guest end-of-stay email copy

**Where it runs:** `run_tenant_lane_guest_stay_ending_notifications` in `app/services/stay_timer.py` sends `send_guest_authorization_dates_only_email` in `app/services/notifications.py`.

### How to test (2a)

1. Same setup as **Bug 1e**: **tenant** creates a **guest** invite; **guest** accepts, signs, **checks in**.
2. Set the stay’s `stay_end_date` (DB or natural time) to **today + 2 days** or **today**, matching the job’s two windows.
3. Run the job (same one-liner as in [Run the jobs manually](#run-the-jobs-manually-without-waiting-for-cron); the function is `run_tenant_lane_guest_stay_ending_notifications`).
4. Open the email to the **guest** (or inspect the HTML the app would send).
5. **Pass if:**
   - Subject is along the lines of **`[DocuStay] Your stay dates`** (informational, not “confirm property status” or “authorization ends”).
   - Body states **only** that the stay runs **from start date to end date** (plus greeting/sign-off). No prompts to confirm property status, no instructions for owners/managers.
   - **Owner/PM** mailboxes do **not** get this guest informational email.

*(Idempotency: the job logs audit titles `Guest notice: authorization ends in 2 days` / `Guest notice: authorization ends today` per stay so you may need a fresh stay or new dates to re-trigger.)*

### Bug 2b — Guest extension request → tenant only

**Where it runs:** `POST /dashboard/guest/stays/{stay_id}/request-extension` in `app/routers/dashboard.py`; email `send_guest_extension_request_to_tenant_email` in `app/services/notifications.py`; tenant dashboard alert type **`guest_extension_request`**.

### How to test (2b)

1. **Tenant-invited guest**, **checked in**, stay **not** checked out, cancelled, or revoked (`can_request_extension` should be **true** on `GET /dashboard/guest/stays`).
2. As **guest**, open the guest dashboard: confirm **“Request extension from host”** appears (list and/or detail for that stay).
3. Submit the modal with an optional short note (or empty).
4. **Pass if:**
   - Response is success (`Your host has been notified` or equivalent).
   - **Tenant** (inviter) receives the extension email; dashboard shows a **`guest_extension_request`** alert for the tenant.
   - **Owner** and **assigned property managers** do **not** receive this email and do **not** get an alert for this event.
   - Guest activity / tenant activity logs (as applicable) show a **Guest requested stay extension**–style ledger entry; owner/manager property logs remain consistent with privacy lane rules (no tenant-guest extension noise in owner lane).
5. **Cooldown:** Call the same endpoint again within **24 hours** for the same stay. **Pass if** the API returns **429** with a message about waiting before another request.
6. **Negative checks:**
   - **Owner-invited guest** stay (property lane): `can_request_extension` should be **false**; `POST .../request-extension` should return **403** (extension only when invited by a resident on DocuStay).
   - Not checked in: **400** with a check-in message.

**Product note for testers:** Extending dates is implemented by the **tenant** creating a **new** guest invitation from their dashboard; when the guest accepts, it replaces the prior authorization. That’s described in-app on the tenant dashboard next to guest invite flows.

---

## Product Change 1 — Shield Mode always on (CR-1a)

**Intent:** Shield Mode is **hardcoded on** for every property: owners and managers **cannot** turn it off from the product UI, and API responses should show Shield as **ON**. The underlying column and legacy “turn off” code paths remain in the codebase for a future toggle (`SHIELD_MODE_ALWAYS_ON` in `app/services/shield_mode_policy.py`). Status Confirmation on eligible stays does **not** depend on flipping a Shield switch off.

**Note when re-running Bug 1c:** Older text assumed Shield could stay **off** after the no-response step. Under Product Change 1, `shield_mode_enabled` should remain **on** for all properties; the important parts of Bug **1c** are still occupancy → **unknown**, **no** auto-vacant from that step, and **continuing reminders**—not Shield going off.

### How to test (Owner — UI)

1. Sign in as an **owner** and switch to **Business mode** (Shield and property billing context are business-scoped).
2. **Properties** tab (Active properties):
   - **Pass if** copy explains that Shield is **always on** (or equivalent).
   - **Pass if** the Shield filter shows only **All** and **Shield ON** (no **Shield OFF** option).
   - Select one or more properties and open the bulk actions bar: **Pass if** there is **no** “Turn Shield OFF” button (only an optional “Ensure Shield ON (sync)” or similar). If you still have an old build with the OFF button, clicking it should fail (API **400**).
3. Open **View & Edit** on any property → **Property detail** page:
   - **Pass if** the **Shield Mode** card shows **Always on** (or equivalent), a **read-only** ON indicator, and **no** working switch / role=switch control that changes Shield.
   - **Pass if** **PASSIVE GUARD** / **ACTIVE MONITORING** still reflects occupancy (occupied vs vacant/unknown), not “Shield off.”
4. **Settings** (or billing summary, if shown): **Pass if** help text does **not** tell the user to “toggle Shield” to change pricing; it should reflect that Shield applies across properties (wording may vary).

### How to test (Property Manager — UI)

1. Sign in as a **property manager** with assigned properties.
2. On the manager **properties** list: same expectations as owner step 2 (**no Shield OFF filter**, **no bulk Turn Shield OFF**).
3. Open a **manager property detail** page:
   - **Pass if** **Shield Mode** is **read-only** (“Always on” / static ON) and **not** a clickable toggle.

### Optional checks (API / DB)

- `PUT /owners/properties/{id}` with body `{"shield_mode_enabled": false}` should still result in Shield staying **on** (persisted `1` and/or response shows `shield_mode_enabled: true` depending on schema).
- `POST /dashboard/properties/bulk-shield-mode` with `"shield_mode_enabled": false` should return **400** with a message that Shield cannot be turned off.
- DB: new properties default `shield_mode_enabled` to **1**; existing rows may be healed when properties are updated or via CSV policy.

### Quick checklist (Product Change 1)

| Item | What to verify (UI) |
|------|---------------------|
| PC1a | No Shield OFF filter; no bulk Shield OFF; property detail Shield is read-only “always on” |
| PC1b | Manager dashboard matches owner expectations for Shield UI |
| PC1c | (Optional) Bulk/API attempts to turn Shield off are rejected or ineffective |

---

## Product Change 2 — Pricing: $10/month flat + 7-day free trial (CR-3a, CR-3b, CR-3c)

**Intent:** Subscription pricing is **$10/month flat** (not per property, no tiered unit pricing). New owners get a **7-day free trial**; recurring billing starts after the trial (**day 8 onward** in Stripe terms). There is **no separate one-time onboarding invoice** in the current product flow.

**Backend (reference):** `app/services/billing.py` (`SUBSCRIPTION_FLAT_AMOUNT_CENTS`, `SUBSCRIPTION_TRIAL_DAYS`, `ensure_subscription`, `charge_onboarding_fee` / `on_onboarding_properties_completed`). Stripe product name for new subs: **DocuStay Subscription (monthly)**. Legacy accounts may still have old two-line subscriptions until migrated in Stripe; sync logic supports both.

### How to test (Owner — signup / first property)

1. Complete owner onboarding (identity, POA) as usual.
2. Add **one or more** properties (single add or CSV bulk—the first batch should trigger billing setup).
3. **Pass if:**
   - You are **not** blocked on a **large one-time “onboarding fee”** invoice to invite guests (unless Stripe failed and `can_invite` is still false—then you should see messaging about billing setup in progress, not “pay onboarding invoice”).
   - **Billing** tab and **Settings → Subscription & Billing** describe **$10/month flat**, **7-day free trial**, and **no per-property** subscription pricing.
   - **Event ledger** (category Billing) can show **Subscription started** in the audit log and a ledger row titled **Subscription started (free trial)** when setup succeeds.
4. In **Stripe Dashboard** (test mode): for the customer, the subscription should show a **trial** (7 days) and a single recurring price of **$10/month** (flat), not separate $1/unit + $10/Shield line items **for newly created subscriptions**.

### How to test (UI — when the $10 subscription exists & trial countdown)

The **$10/month flat** Stripe subscription is created when the owner’s **first active property** is saved (single **Add property** or **bulk CSV**), **not** at POA/identity alone. The app then starts billing onboarding: customer + subscription with **7-day trial** (if Stripe is configured).

Use this checklist in the **browser** (Stripe test mode + real API recommended):

1. **Baseline (optional):** Sign in as a **new owner** who has finished identity + POA but has **no properties** yet. Open **Settings** (`#dashboard/settings` or **Settings** in the sidebar).
   - **Pass if:** There is **no** blue **“Free trial active”** banner under the Settings title (no subscription yet). **Subscription & Billing** (visible in **Business mode** only) may say to add a property to start the plan/trial.

2. **Trigger:** In **Business mode**, add **one** property (**My Properties** → add flow, or CSV upload) and wait until the property appears and no error toast appears.

3. **Settings — trial banner:** Open **Settings** again (works in **Business** or **Personal** mode).
   - **Pass if:** A **sky/blue banner** appears directly under **“Settings”** / **“Manage your DocuStay account…”** with **“Free trial active”**, **“X days left in your free trial”** (typically **6 or 7** days right after creation, depending on time-of-day vs Stripe `trial_end`), the **trial end date/time** in your local timezone, and copy about **$10/month flat** after the trial.
   - The banner **refreshes every ~60 seconds** while you stay on the page (day rollover).

4. **Settings — plan copy:** Scroll to **Subscription & Billing** (only if **Business mode**).
   - **Pass if:** Text still describes **$10/month flat** and **7-day trial** (consistent with the banner).

5. **Billing tab:** Open **Billing** (`#dashboard/billing` or **Billing** in the sidebar).
   - **Pass if:** Summary mentions **flat $10/mo after trial**; you may see **no** recurring invoice yet during trial (normal—Stripe bills after trial depending on configuration). You are **not** asked to pay a **separate large onboarding fee** to invite guests.

6. **Invites:** Confirm **Invite guest / Invite tenant** is enabled (no “billing setup in progress” tooltip blocking you), matching **`can_invite`** after setup completes.

7. **Event ledger (optional):** **Event ledger** tab → category **Billing** (or scan rows).
   - **Pass if:** You can see ledger copy such as **Subscription started (free trial)** / audit **Subscription started** after the first property add (when Stripe succeeded).

8. **Stripe (optional cross-check):** **Customers** → your test customer → **Subscriptions**: status **Trialing**, one price **$10/month**, trial end ~7 days out.

**Legacy migration script:** If you ran `scripts/migrate_legacy_subscription_to_flat.py` for an account, after a successful run the **same Settings trial banner** and billing behavior apply when the new subscription is **`trialing`**.

### How to test (Owner — invites during trial)

1. After billing setup succeeds (`can_invite` true), open **Guests** / **Tenants** and start an invite.
2. **Pass if:** Invites work **without** paying a separate onboarding invoice first (trial is not gated on a one-time fee).

### How to test (Owner — billing copy)

1. Open **Billing** tab: summary text should mention **flat $10/mo after trial**, not “baseline $1 × units” or “Shield $10 × units” as the pricing model.
2. Open **Settings** in **Business mode** → **Subscription & Billing**: same expectations; **Shield** should **not** be described as an add-on **per property** for subscription price.
3. On **My Properties**, the Shield card helper line should **not** say “$10/month per property” for subscription.

### How to test (Reactivate property — no second trial)

1. Remove all active properties so the subscription is cancelled (or use an account that had zero properties and a cancelled sub), then **reactivate** a property.
2. **Pass if:** A new subscription is created **without** a second 7-day trial (verify in Stripe: `trial_end` absent or billing aligns with `allow_trial=False` on recreate). *Exact Stripe UI fields may vary by API version.*

### Quick checklist (Product Change 2)

| Item | What to verify (UI / Stripe) |
|------|------------------------------|
| PC2a | Copy says **$10/mo flat**, **7-day trial**, **not per property** (Billing, Settings, properties helper text) |
| PC2b | First property add starts subscription + trial; **no** mandatory tiered onboarding invoice for new flow |
| PC2c | Invites allowed during trial once billing setup completes (`can_invite`) |
| PC2d | **Settings** shows **“Free trial active”** banner (days left + end date) after first property; banner visible in Personal or Business mode |

### Related code (Product Change 2)

- Flat subscription + trial: `app/services/billing.py`
- Webhook (legacy onboarding invoice paid → flat sub **without** trial): `app/routers/billing_webhook.py`
- First property / bulk: `app/routers/owners.py` (`on_onboarding_properties_completed`, `ensure_subscription`, `sync_subscription_quantities`)
- Invite gate + billing API: `app/routers/dashboard.py` (`GET /dashboard/owner/billing`)
- Ledger label: `ACTION_BILLING_SUBSCRIPTION_STARTED` in `app/services/event_ledger.py`
- UI: `frontend/pages/Owner/OwnerDashboard.tsx`, `frontend/pages/Owner/PropertyDetail.tsx`, `frontend/pages/Settings/Settings.tsx`
- Legacy → flat + new trial (CLI): `scripts/migrate_legacy_subscription_to_flat.py`

---

## Quick checklist (Bug 1)

| Item | What to verify |
|------|----------------|
| 1a | Tenant-invited guest stay: no owner/PM Status Confirmation; owner-invited stay: flow still runs |
| 1b | No “Dead Man’s Switch” in user-facing email copy or user-visible ledger titles |
| 1c | After deadline: `unknown`, no auto Shield/vacant from this step; daily reminders continue |
| 1d | Emails/alerts to PM if assigned, else owner; never tenant/guest for Status Confirmation |
| 1e | Tenant + guest get guest-ending messaging only; no property status prompt to them |

## Quick checklist (Bug 2)

| Item | What to verify |
|------|----------------|
| 2a | Guest email: subject/body informational (“Your stay runs from … to …”); no property status / confirm language |
| 2b | Extension POST notifies tenant only; `guest_extension_request` alert; 403 property-lane / 429 cooldown; UI on guest + tenant copy about new invite |

---

## Related code (reference)

- Lane detection: `app/services/privacy_lanes.py` (`is_tenant_lane_stay`)
- Status Confirmation jobs: `app/services/stay_timer.py`
- Email copy and PM-first routing: `app/services/notifications.py`
- PM-first dashboard alerts: `app/services/dashboard_alerts.py` (`create_alert_for_property_managers_or_owner`)
- Owner/manager stay UI (confirmation when `unknown`): `app/routers/dashboard.py`
- Bug 2 guest email: `send_guest_authorization_dates_only_email`, `send_guest_extension_request_to_tenant_email` in `app/services/notifications.py`
- Bug 2 tenant-lane guest ending job: `run_tenant_lane_guest_stay_ending_notifications` in `app/services/stay_timer.py`
- Bug 2 extension API + `can_request_extension` on `GuestStayView`: `app/routers/dashboard.py` (`POST /dashboard/guest/stays/{stay_id}/request-extension`)
- Bug 2 tenant alert allowlist: `_ALERT_TYPES_BY_ROLE` in `app/routers/dashboard.py` (`guest_extension_request`)
- Product Change 1 (Shield always on): `app/services/shield_mode_policy.py`; owner property responses `app/schemas/owner.py`; bulk Shield `POST /dashboard/properties/bulk-shield-mode` in `app/routers/dashboard.py`; legacy Shield-off paths gated in `app/routers/dashboard.py`, `app/routers/auth.py`; UI: `frontend/pages/Owner/PropertyDetail.tsx`, `OwnerDashboard.tsx`, `Manager/ManagerDashboard.tsx`, `ManagerPropertyDetail.tsx`
