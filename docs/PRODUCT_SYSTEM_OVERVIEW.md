# DocuStay Product & System Overview

This document describes **what the system does** and **how each feature works** from a product and logic perspective—for use by product, support, and stakeholders. It does not include code-level details.

### Platform scope (guests vs tenants)
DocuStay handles **guest authorization records**, **guest expirations**, **guest revocations**, and related documentation. The platform does **not** revoke tenants, expire tenants, or send tenant revocation/expiration notifications. Tenant lease and legal removal is outside DocuStay’s scope. Tenant assignments can be **cancelled by the tenant** (self-cancel); the system does not revoke them.

---

## 1. Shield Mode

### What it is
Shield Mode is a per-property setting that provides enhanced protection and evidence posture for a unit. When on, it is billed at an additional $10/unit/month (see Billing).

### How it gets turned ON
- **Manually:** The owner can turn Shield Mode **on** at any time from the dashboard (property card or property detail). The toggle is available regardless of occupancy.
- **Automatically (last day of stay):** For any property where a guest has an active stay that **ends today**, the system automatically turns Shield Mode **on** for that property. The owner receives an email that Shield Mode was activated (last day of stay).
- **Automatically (Status Confirmation):** When this flow runs and the owner has not confirmed occupancy by the deadline (48 hours after lease end), the system flips the property to **UNCONFIRMED** and turns Shield Mode **on**. The owner receives emails about auto-execution and Shield Mode activation.

### How it gets turned OFF
- **Manually:** The owner can turn Shield Mode **off** at any time from the dashboard.
- **When a new guest accepts an invitation:** As soon as a guest accepts an invitation (signup-with-invite or accept-invite) and a stay is created for that property, Shield Mode is turned **off** for that property.
- **When the owner confirms “Unit Vacated”:** In the occupancy confirmation flow, if the owner selects “Unit Vacated,” Shield Mode is turned **off** for that property.
- **When the guest checks in:** If Shield was on, it is turned **off** at guest check-in (same moment occupancy is set to OCCUPIED).

### Billing impact
Whenever Shield is turned on or off (by any of the above), the system syncs the owner’s Stripe subscription so that the **Shield quantity** equals the number of properties with Shield Mode on. Stripe applies **immediate proration** (no manual override). Baseline $1/unit is unchanged; only the Shield line item quantity changes.

---

## 2. Status Confirmation (stay end reminders)

### Purpose
The Status Confirmation ensures that if a stay ends and the owner does **not** confirm what happened (vacated / renewed / holdover), the system records that silence and flips the property to **UNCONFIRMED**, activating Shield and related protections. It is a safeguard against owner inaction after a guest’s lease end date.

### Requirement 11 – Status Confirmation timing (spec)
- **Occupied units:** 48 hours before lease end → first confirmation prompt; lease end date → **no automatic change**; 48 hours after lease end with no owner action → status flips to **UNCONFIRMED**.
- **Vacant units (if owner enables monitoring):** Prompts at defined intervals; no response → flips to **UNCONFIRMED**.

### When it applies (occupied units)
- Only to stays where the guest has **checked in** (checked_in_at is set).
- Status Confirmation is **enabled** for the stay: in production it is turned **on** automatically **48 hours before** the stay end date (not at stay creation or check-in). Until then the stay has Status Confirmation off.

### Occupied units – timeline (production)
1. **48 hours before lease end**
   - Status Confirmation is turned **on** for that stay (if not already on).
   - Owner receives an email: “Status Confirmation: 48h before lease end” (guest name, property, end date).
   - An audit log entry is created.

2. **On lease end day**
   - Owner receives an **urgent** email: “Status Confirmation: lease ends today” (same info).
   **No automatic change** to occupancy status; urgent reminder email and audit log only.

3. **48 hours after lease end**
   - If the owner has **not** responded (no vacated / renewed / holdover):
     - Stay is marked with `dead_mans_switch_triggered_at`.
     - Property occupancy status is set to **UNCONFIRMED** (recorded silence = forensic evidence).
     - Property USAT token (if released) is moved back to **STAGED**.
     - **Shield Mode is turned ON** for the property.
     - Owner receives: “Status Confirmation: auto-executed” and “Shield Mode activated (triggered by Status Confirmation).”
   - If the owner **has** already confirmed (vacated, renewed, or holdover), nothing further runs for that stay.

### Test mode
When Status Confirmation test mode is enabled, the “effective” lease end is a short time (e.g. 2 minutes) after stay creation. Alerts and auto-execute run on that shortened timeline so the flow can be tested quickly.

### Owner response
The owner can always respond before the 48h-after deadline (and after) by using **Confirm occupancy** and choosing:
- **Unit Vacated** → checkout recorded, Shield off, invite token EXPIRED, occupancy VACANT.
- **Lease Renewed** → new end date set, occupancy stays OCCUPIED, invite token stays BURNED.
- **Holdover** → occupancy stays OCCUPIED, no date change.

Once any of these is recorded, the Status Confirmation auto-execute step will not run for that stay.

### Vacant units – monitoring (if owner enables)
- The owner can enable **vacant-unit monitoring** for a property that is **VACANT**. When enabled: the system sends **confirmation prompts at defined intervals** (e.g. every N days, configurable); the owner responds via **Confirm still vacant** (dashboard); if there is **no response by the response deadline** after a prompt, the property status flips to **UNCONFIRMED** and Shield Mode is turned on. Intervals and response deadline are configurable (e.g. prompt every 7 days, response due within 7 days).

---

## 3. Source-of-Truth Jurisdiction Documents (Database)

### What is stored
Jurisdiction and legal content are stored in the database as the **source of truth** (no AI summarization of law):

- **Jurisdictions:** One row per region (e.g. NYC, FL, CA, TX, WA). Each has: region_code, state_code, name, max_stay_days, tenancy_threshold_days, warning_days, agreement_type, removal_guest_text, removal_tenant_text, stay_classification_label, risk_level, allow_extended_if_owner_occupied.
- **Jurisdiction statutes:** Multiple rows per region. Each has: region_code, citation (e.g. statute reference), plain_english (optional, human-written), use_in_authority_package, sort_order.
- **Jurisdiction zip mapping:** Maps zip codes (or zip prefixes) to region_code so the system can resolve “this property’s zip” → “this region” deterministically.

### How it’s used
- **Property jurisdiction:** For a given property (zip and optional region_code), the system looks up the region and loads that region’s jurisdiction plus its statutes (where use_in_authority_package is true). This drives:
  - **Guest invitation agreement:** The agreement text is built from this jurisdiction (statutes, removal text, max stay, etc.) and is stable for hashing/signing.
  - **Live property page (authority wrap):** The public live page shows the applicable jurisdiction wrap: state name, applicable statutes, removal text—all from the DB.
  - **JLE (Jurisdiction / Legal Engine):** Classification and risk for stays use this data (and region rules) for display and logic.
- **No AI:** Statute text is stored and merged into templates; there is no AI interpretation of law in this path.

---

## 4. Owner Signup and Stripe Identity Verification

### Owner signup flow (product level)
1. **Register:** Owner signs up with email, password, and any required profile fields. The account is created in a **pending** state until onboarding is complete.
2. **Verify email:** The owner must verify their email (link or code sent to the email address). Until verified, they cannot proceed to the next steps.
3. **Identity verification (Stripe Identity):** After email verification, the owner must complete **identity verification** before signing the Master POA or adding properties. See below.
4. **Sign Master POA:** Once identity is verified, the owner is shown the Master POA and must sign it to complete onboarding. The signature is stored and linked to the owner.
5. **Onboarding fee (first properties):** When the owner adds their first property or properties (single add or CSV bulk upload), the system creates the **onboarding invoice** (see §7). The owner must pay this invoice (or have a payment method charged) before they can **invite guests**. Until the onboarding invoice is paid, the "Invite Guest" action is disabled (e.g. with a tooltip directing them to Billing).
6. **Full access:** After POA is signed and (when an onboarding fee was charged) the onboarding invoice is paid, the owner has full dashboard access: add or edit properties, create invitations, view stays and audit logs, manage billing.

### Stripe Identity Verification (who and when)
- **Who:** Owners (and authorized agents), not guests.
- **When:** During **pending owner** signup, after email verification and before the owner can sign the Master POA and add properties.

### What happens
- The system creates a **Stripe Identity Verification Session** (document type: government ID + optional selfie/liveness as configured).
- The user is redirected to Stripe’s hosted flow to submit ID and complete verification.
- On return, the frontend calls a **confirm-identity** endpoint with the verification session id. The backend checks with Stripe that the session status is **verified** and that the session belongs to the current pending registration.
- On success, the pending registration is marked identity-verified (and the verification session id is stored for audit). The user can then proceed to sign the Master POA and complete signup.

### After signup
- For existing owners, identity verification can be done from Settings (or equivalent). Until identity is verified, the owner cannot access certain operations (e.g. POA, property add, full dashboard) depending on product rules.

### Important
- Identity verification is **required** before signing the Master POA and before adding properties. The system blocks POA and property/dashboard access until verification is complete.

---

## 5. Guest Invite Flow

### Creating an invitation
- **Who:** Owner (after onboarding is complete and, if applicable, onboarding invoice is paid).
- **Inputs:** Property, guest name, check-in date, check-out date; optional guest email. Purpose and relationship have defaults (e.g. travel, friend).
- **Output:** An invitation is created with status **pending**, token_state **STAGED**, and a unique **invitation code**. Status Confirmation is enabled for the resulting stay (alerts by email and dashboard). The owner receives a **link** they can share: `#invite/{invitation_code}`.

### Invitation expiry (pending, not accepted in time)
- **Normal mode:** Pending **guest** invitations that are not accepted within **12 hours** are marked **expired** (status=expired, token_state=EXPIRED) by a scheduled cleanup job that runs every hour.
- **Test mode** (when `TEST_MODE=true` in .env): The same logic applies but the window is **5 minutes** instead of 12 hours, and the cleanup job runs **every minute** so expired invites are updated soon after the window.
- **Tenant invitations are excluded** from expiry; DocuStay does not expire tenants. Tenant lease/legal removal is outside the platform’s scope.
- The owner dashboard uses the same rule to show which pending guest invites are expired (5 min or 12 h depending on mode).

### How a guest can accept
1. **New guest (signup with invite link)**  
   - Guest opens the invite link, goes to guest signup, and enters details (name, email, password, acknowledgments, etc.). They can optionally **sign the agreement** in the same flow if the invite code and agreement signature id are provided.  
   - On submit:  
     - A **guest user** is created (and email verification may be required depending on config).  
     - If they **signed** the agreement (valid invitation code + valid signature): a **Stay** is created, invitation status → **accepted**, invitation token_state → **BURNED**, and Shield Mode for the property is turned **off** if it was on.  
     - If they did **not** sign yet: the invitation is added to their **pending invites** so they can sign from the guest dashboard later.  
   - Occupancy is set to **OCCUPIED** only when the guest later clicks **Check in** (on or after the stay start date).

2. **Existing guest (login then accept)**  
   - Guest logs in, then uses the invite link or pastes the invitation code and submits **Accept invite** with the **agreement signature id** (from signing the agreement).  
   - Same effect: Stay created, invitation accepted, token BURNED, Shield off for the property. Check-in still required for occupancy.

3. **Existing guest (accept from dashboard)**  
   - Guest has a pending invite (e.g. signed up with code but didn’t sign in that step). On the guest dashboard they see the pending invite, open the agreement, sign it, and submit.  
   - Backend creates the Stay, marks invitation accepted, token BURNED, and turns Shield off.

### Invitation and agreement signing flow (end-to-end)

1. **Owner creates an invitation**  
   Owner selects property, guest name, stay dates (and optionally email), and creates the invite. The system generates a unique **invitation code** and an **invite link** (`#invite/{code}`) the owner can share (e.g. by email or message).

2. **Guest receives the link or code**  
   - **New guest:** Clicks the invite link and is taken to **guest signup**. They create an account (name, email, password, acknowledgments). They can sign the agreement in that flow or leave it for later; if they don’t sign yet, the invite is added to their **pending invites** after signup.  
   - **Existing guest:** Logs in and either uses the same invite link or, on the **guest dashboard**, pastes the invitation link/code in “Add invitation” and submits. The invite is added to their pending list.

3. **Opening the agreement**  
   On the guest dashboard, the guest sees **Future invites** (and, when applicable, **Pending actions**). They click **Review & sign** or **Complete signing** for an invite. The **Agreement modal** (“Guest Acknowledgment and Revocable License to Occupy”) opens and loads the agreement built from the jurisdiction SOT for that property (see §16). The guest can view the document and a **Preview/Download PDF** link (unsigned).

4. **Signing with Dropbox Sign**  
   The guest enters their full name and optional IP, checks the four acknowledgments, and clicks **Sign with Dropbox Sign**. The system sends the agreement to **Dropbox Sign** (e-signature provider) and either:  
   - **Redirect:** Guest is sent to Dropbox’s signing page in the same tab (or opens it from the link we provide).  
   - **New tab:** Dropbox’s signing page opens in a new tab.  
   The **modal closes** as soon as the request is sent (email is sent to the guest from Dropbox). The dashboard **refetches** so the same invite appears under **Pending actions** with “Awaiting your signature in Dropbox” until signing is complete.

5. **Completing the signature in Dropbox**  
   The guest signs on Dropbox’s page. The system **does not** treat any in-app–generated PDF as the signed document; only the **PDF returned by Dropbox** after signing is stored and shown as the signed agreement (see §16).

6. **Stay confirmed only after Dropbox signing**  
   - Until the guest has **completed signing in Dropbox**, the invite remains in **Pending actions** and the **stay is not created**.  
   - When the guest returns to the app (or refreshes), the system checks Dropbox for the signed document. If it is complete: the signed PDF is stored, the invite is **accepted** (Stay created, invitation token **BURNED**, Shield off for the property), and the stay appears under **Current or upcoming stays**.  
   - If the guest closes the modal without signing, or leaves Dropbox without signing, the invite stays in Pending actions; they can open the agreement again and complete signing later.

7. **Occupancy and Status Confirmation**  
   **Occupancy** is set to **OCCUPIED** only when the guest clicks **Check in** (on or after stay start date). **Status Confirmation** for the new stay is **off** at stay creation; it is turned **on** 48 hours before the stay end date (or in test mode after a short delay from check-in).

### Agreement and stay (summary)
- The **invitation agreement** is built from the jurisdiction source of truth (property zip → region → statutes, removal text, max stay). The guest must **complete signing in Dropbox** to accept the invitation. When that is done, the signature (and Dropbox-signed PDF) is stored, the invitation is accepted, the token is **BURNED**, and the Stay is created.
- The guest can later **download the signed agreement PDF** for their stay from the dashboard; that PDF is always the one from Dropbox (never a pre-filled in-app copy).

---

## 6. Billing Overview

### Two parts
1. **One-time onboarding fee** (first property upload).
2. **Monthly subscription** (baseline + Shield).

All billing is done via **Stripe**. There is no internal cron for recurring charges; Stripe creates and pays recurring invoices. Our system creates/updates the subscription and quantities; Stripe handles invoice generation and charging.

---

## 7. Initial Billing Invoice (Onboarding Fee)

### When it’s created
- When the owner **first** adds one or more properties (either by adding a single property or by completing a **bulk CSV upload** that creates or updates properties).
- The system detects that this is the **first batch** (onboarding): it calls the onboarding billing hook with the **total unit count** (number of non-deleted properties) at that time.

### Idempotency
- Onboarding fee is charged **only once** per owner. The system records that onboarding billing has been completed (e.g. `onboarding_billing_completed_at` and unit count). Further property adds do not trigger another onboarding charge.

### How the amount is calculated (tiers)
- The fee depends **only** on **total number of units** (properties) in that first batch:
  - **1–5 units:** $299 **flat**.
  - **6–20 units:** $49 **per unit**.
  - **21–100 units:** $29 per unit.
  - **101–500 units:** $19 per unit.
  - **501–2,000 units:** $14 per unit.
  - **2,001–10,000 units:** $10 per unit.
  - **10,001+ units:** $7 per unit.

### What the system does
- Creates or reuses a **Stripe Customer** for the owner.
- Creates a **one-time Stripe Invoice** with a single line item (the onboarding fee), attaches metadata (e.g. owner_profile_id, onboarding_units), and **finalizes** the invoice.
- Collection is typically **charge_automatically**: if the customer has a payment method, Stripe charges it; otherwise the invoice remains open and the owner can pay via the **hosted invoice URL** (e.g. from Billing in the dashboard).
- The system stores the hosted invoice URL and returns it so the owner can pay. It does **not** create the monthly subscription at this point; the subscription is created **after** the onboarding invoice is **paid** (see Stripe webhook).

### After payment
- When Stripe sends **invoice.paid** and the invoice metadata indicates it is the **onboarding** invoice (e.g. `onboarding_units` present), the system:
  - Marks the owner profile as **onboarding invoice paid**.
  - **Creates the monthly subscription** (see below). So the first invoice the owner sees is only the one-time tier fee; the first recurring invoice is generated later by Stripe according to the subscription cycle.

---

## 8. Subscription (Monthly Recurring)

### When it’s created
- **After** the onboarding invoice is **paid** (handled in the Stripe **invoice.paid** webhook). If no onboarding fee was ever charged (e.g. Stripe disabled or 0 units), subscription creation may still happen when the first properties are added, depending on configuration.
- Also when the owner goes from **zero** to **one or more** properties again (e.g. after reactivating), so they have an active subscription.

### How the amount is calculated
- **Baseline:** **$1 per unit per month.** One “unit” = one non-deleted property.
- **Shield:** **$10 per unit per month** for each property that has **Shield Mode on**.
- So for each property: **$1 always** + **$10 if Shield is on**. Total subscription = (number of units × $1) + (number of units with Shield on × $10).

### How quantities are updated
- The system keeps **two** subscription line items in Stripe: one for baseline (quantity = unit count), one for Shield (quantity = number of properties with Shield on).
- Whenever **unit count** or **Shield count** changes, the system calls a **sync** function that updates the Stripe subscription item quantities. Stripe **prorates** automatically:
  - Adding a property → baseline quantity +1; Shield quantity +1 if that property has Shield on.
  - Removing/soft-deleting a property → both quantities decreased as needed.
  - Turning Shield on or off → only Shield quantity changes.
- If the owner has **zero** units (all properties deleted), the subscription is **cancelled** (prorated) so they are not billed until they have properties again.

### Who triggers sync
- After adding a property (single or bulk).
- After updating a property (e.g. Shield toggle, or any path that changes Shield or unit count).
- After owner confirms **Unit Vacated** (Shield off for that unit).
- When a new guest **accepts an invitation** (Shield off for that property).
- In the **stay timer / Status Confirmation** job when Shield is turned on (last day of stay or Status Confirmation auto-execute).
- After **guest check-in** if Shield was on.

No manual override: all quantity and proration behavior is driven by actual unit and Shield state.

---

## 9. QR Code and Live Link

### Live link
- Each property has a unique **live slug** (system-generated, stable). The **live link** is: `/#live/{live_slug}` (frontend) and the backend serves the live property payload at `GET /api/public/live/{slug}`.
- The live page is **public** (no login). It shows:
  - Property info (name, address, city, state, zip, region).
  - Occupancy status and Shield Mode (on/off).
  - **Jurisdiction wrap:** state name, applicable statutes, removal text (from the jurisdiction source of truth by property zip/region).
  - Property identifier (Tax ID, APN when available).
  - Token state (e.g. staged / released).
  - Current or last guest stay and audit/log context as designed for the “authority package” for that door.

### QR code
- The owner (and in some flows the guest) can open a **QR code** modal that encodes the **full live link URL** (app origin + `#live/{live_slug}`). The QR image is generated from a public QR service using that URL. Anyone who scans the QR code is taken to the live property page in the browser—no login required.

### Use
- The live link is the **property-level authority link** that owners/agents can share or post. The QR code is a convenient way to open that same link (e.g. at the property).

### Verify portal
- A **public, no-login** **Verify** page (`/#check`) lets anyone check whether a **token (Invitation ID)** has an **active authorization** (guest stay) right now. The page is linked from the main app navigation (e.g. "Verify") so verifiers (e.g. utility providers, partners) can reach it without an account. (Email verification after signup uses `/#verify`; token/authorization check uses `/#check` to avoid overlap.)
- **Input:** Required: **Token ID** (the invitation code, e.g. INV-XXXX). Optional: property address (if provided, must match the property for this token), name and phone—submitted and logged only; not used for validity.
- **Validity:** The token is the **Invitation ID**. A result is **valid** only if: the invitation exists, its token_state is **BURNED**, a linked stay exists and is active (not revoked, not checked out, not cancelled), and the stay end date has not passed. If a property address is submitted, it must match the property for this token.
- Every verify attempt is **logged** in the audit log (valid or invalid). Failed or mismatched attempts (e.g. wrong address, token not found, authorization ended) are recorded with a title such as **Identity Conflict** or **Verify attempt – no match** . No owner notification or escalation is triggered by verify attempts.
- **Valid result:** The response shows a verified authority summary: property name, address, occupancy status (or "occupied" when there is an active authorization even if the property record has not yet been updated), authorization state, guest name when active, Record ID, timestamp, and a **live link for re-verification**. The verifier can open the **full evidence page** (`/#live/{live_slug}`) from the result. The page is read-only and printable.
- **Invalid result:** The response shows “No active authorization found” (or similar), timestamp, and a short reason (e.g. Token not found, Address does not match, Authorization ended). Internal details are not exposed.
---

## 10. Owner Portfolio View

### What it is
- A **public, no-login** page that shows one owner’s profile and a list of their active properties. It is intended for sharing (e.g. with partners, agents, or prospects) so they can see who the owner is and which properties they have—without logging in or seeing occupancy, Shield, or per-property live links.

### How the owner gets the link
- In **Settings**, the owner has a **Portfolio** section. They can request or view their **portfolio link**. The system assigns the owner a unique **portfolio slug** (created on first use) and returns the URL in the form `/#portfolio/{slug}` (e.g. `https://app.example.com/#portfolio/abc123`). The owner can **open the portfolio page** in a new tab or **copy the link** to share.

### What is visible on the portfolio page
- **No authentication:** Anyone with the link can open the page; no login is required.
- **Owner card (top of page):**
  - **Name** (owner full name, or email if no name, or “Property Owner” as fallback).
  - **Tagline:** “DocuStay verified property owner.”
  - **Contact (if present):** Email (clickable mailto), Phone (clickable tel), State. Only fields that are set are shown.
- **Properties section:**
  - Lists **all non-deleted properties** for that owner, in creation order.
  - For **each property** the page shows:
    - **Name** (property name, or “City, State” if no name).
    - **Location:** City, State.
    - **Region code** (e.g. FL, NYC) as a badge.
    - **Property type** (e.g. entire_home, private_room), if set.
    - **Bedrooms** (e.g. “2 beds”), if set.
  - **Not shown:** Street address, zip, occupancy status, Shield Mode, live link, Tax ID, APN, invitations, stays, or any audit data. This is a public, high-level overview only.
- **Empty state:** If the owner has no (non-deleted) properties, the page shows a message such as “No properties listed yet” with optional “Check back later.”
- **Footer:** “Powered by DocuStay” and a docustay.com link.

### When the page is not found
- If the slug is missing, invalid, or does not match any owner profile, the user sees a **“Portfolio not found”** message (and optionally the error detail). No data is returned.

---

## 11. Uploading Properties via CSV (Bulk Upload)

### When it’s available
- After owner onboarding is complete (identity verified, Master POA signed). The same dependency as adding a single property.

### File and format
- **File type:** CSV, UTF-8 encoded.
- **Required columns:** Address (or street_address/street), City, State, Zip, **Occupied** (YES/NO).
- **If Occupied = YES:** Tenant Name, Lease Start, Lease End are required.
- **Optional columns:** Unit No, Shield Mode (YES/NO, default NO), Tax ID, APN (or parcel).

### Logic per row
- Each row is matched to an existing property by **address + city + state** (and optionally zip). If a match exists, the row **updates** that property; otherwise a **new** property is **created**.
- **Address:** Required; Unit No is appended to address if provided.
- **Occupied:**
  - **NO:** Property occupancy status = **VACANT**. USAT token state = **STAGED**. No stay or invitation created for that row.
  - **YES:** Property occupancy status = **OCCUPIED**. USAT token state = **RELEASED**. The system creates an **invitation** with token_state **BURNED** for the tenant name and lease start/end dates. No **Stay** or guest account exists until the tenant uses the invite link to sign up and sign the agreement. Until then, that invitation appears in the **Invitations** list and also in the **Stays** section of the property (and in the owner's stays list) as a documented occupancy, shown as **Pending sign-up**. Status Confirmation is enabled for the resulting stay once the tenant signs; the owner can cancel the invitation from the Invitations tab if needed.
- **Shield Mode:** If YES, the property is created or updated with Shield on (independent of Occupied). Shield can also be toggled anytime in the dashboard.
- **Tax ID / APN:** Stored when provided.

### Billing
- After a successful bulk upload (at least one row created or updated), the same billing rules as single-property add apply:
  - If this is the **first** time the owner has properties → **onboarding fee** is created (and optionally subscription after payment).
  - If the owner already had onboarding completed and subscription exists → **subscription quantities** are synced (unit count and Shield count). Proration is automatic.

### Errors
- If a row fails (e.g. missing required column or invalid data), the response includes the **first failing row number** and a **failure reason**. Rows before that may have been committed (created/updated); rows after are not processed.

---

## 12. Editing a Property (Which Fields the Owner Can Update)

The owner can update a property via the property update (PUT/PATCH) endpoint. The following fields are **updatable** (product-level list; exact field names may differ in UI):

- **Property name**
- **Street address** (street)
- **City**
- **State**
- **Zip code**
- **Region code** (normalized, e.g. upper case, length limit)
- **Owner occupied** (or “is primary residence”)
- **Property type** (enum and/or label, e.g. house, apartment, condo, townhouse)
- **Bedrooms**
- **Shield Mode** (on/off)—owner can turn on or off anytime
- **Tax ID**
- **APN**

Changes are audited: an audit log entry records “Property updated” with the list of changed fields (old → new). If Shield Mode was toggled, a separate Shield Mode audit entry is created and the **subscription quantities are synced** so Stripe reflects the new Shield count (with proration).

---

## 13. USAT Token (Property Lifecycle Anchor Token)

### What it is
- A **per-property** token (e.g. “USAT-…”) created when the property is registered. It represents the property’s “authority” lifecycle and is used for evidence and utility/authority flows.

### States
- **STAGED:** Token exists but is not released to a guest/stay. Property is typically VACANT or UNCONFIRMED.
- **RELEASED:** Token has been released to the current occupancy (e.g. bulk upload with Occupied=YES, or when the system links the token to the active stay). The live page and backend can show token_state as “released.”

### When it’s released
- **Bulk upload:** If a row has Occupied=YES, the property’s USAT token state is set to **RELEASED** for that property.
- **Stay-level release:** A stay can have a “usat_token_released_at” timestamp; when set, it means the owner has released the property’s token to that stay. The guest-facing API may or may not expose the actual token value; the **state** (e.g. released) can be shown on the live page.

### When it’s revoked / staged again
- **Owner confirms Unit Vacated** → property token state back to **STAGED**, property usat_token_released_at cleared.
- **Guest checks out** (guest-end stay) → same for that property if no other active stay.
- **Guest cancels stay** (future stay) → same if no other active stay.
- **Initiate removal** (overstay) → stay’s release timestamp cleared, property token state → STAGED and released_at cleared.
- **Status Confirmation auto-execute** → property token state → STAGED and released_at cleared, Shield on.

---

## 14. Property States and Invitation (Invite ID) States

The system tracks **property states** and **invitation states** (by invite ID / invitation code). These drive UI, billing, and what actions are allowed.

### Property states

Each property has two state dimensions:

**1. Occupancy status** (unit status)

| Value | Meaning | When it’s set |
|-------|--------|----------------|
| **vacant** | No current guest. | New property (default or from CSV Occupied=NO); owner confirms “Unit Vacated”; guest checks out or cancels and no other active stay. |
| **occupied** | Current guest in unit. | Guest **checks in**; or bulk upload with Occupied=YES; or owner confirms “Lease Renewed” or “Holdover.” |
| **unknown** | Not yet set or legacy. | Default for new property when no occupancy has been recorded. |
| **unconfirmed** | Owner did not confirm after lease end (recorded silence). | Status Confirmation auto-execute: 48h after lease end with no owner response (vacated/renewed/holdover). Shield turns on; token staged. |

**2. USAT token state** (property-level)

| Value | Meaning | When it’s set |
|-------|--------|----------------|
| **staged** | Token exists but is not released to a guest/stay. | New property; CSV Occupied=NO; or after vacated/checkout/cancel/removal/Status Confirmation (token revoked back to property). |
| **released** | Token released to current occupancy. | CSV bulk upload with Occupied=YES; or when the system links the token to the active stay. |

---

### Invitation (Invite ID) states

Each invitation has **status** and **token_state**. The invitation code (invite ID) is the stable identifier; token_state is the “invite-as-token” lifecycle.

**1. Invitation status**

| Value | Meaning | When it’s set |
|-------|--------|----------------|
| **pending** | Invite created, not yet accepted. | Owner creates invite (manual or via dashboard). |
| **ongoing** | Used for display when a stay exists or invite is accepted (unit occupied). | Display logic; backend may keep status as pending even after accept; “ongoing” indicates active use. |
| **accepted** | Guest accepted (stay created). | Set when stay is created from accept flow (optional depending on implementation). |
| **cancelled** | Owner cancelled the invite. | Owner cancels a pending/ongoing invitation. |
| **expired** | Invite not accepted in time. | Cleanup job: pending invitations older than the configured window (12 hours normally; 5 minutes when TEST_MODE=true) → status=expired, token_state=EXPIRED. |

**2. Invitation token_state** (invite-as-token lifecycle)

| Value | Meaning | When it’s set |
|-------|--------|----------------|
| **STAGED** | Invite created; link can be used to sign and accept. | Owner creates invitation (manual flow). |
| **BURNED** | Guest signed agreement and accepted; stay created. One-time use consumed. Or (CSV) invitation created for documented tenant who has not yet signed up. | Guest accepts (signup-with-invite or accept-invite with valid signature). Also when owner confirms “Lease Renewed” (stays BURNED). **CSV bulk upload:** When Occupied=YES with tenant name and dates, the system creates an invitation in BURNED state so the tenant is documented; no Stay or guest account until the tenant uses the invite link. |
| **EXPIRED** | Stay ended normally (checkout or owner confirmed vacated). | Owner confirms “Unit Vacated”; or guest checks out (guest-end stay). **Guests only;** DocuStay does not expire tenants. |
| **REVOKED** | Guest authorization revoked by owner. | Owner cancels guest invitation; or owner revokes guest stay (Kill Switch); or guest cancels future stay. **Guests only;** DocuStay does not revoke tenants. |
| **CANCELLED** | Tenant assignment cancelled by tenant. | Tenant self-cancels their assignment. DocuStay does not revoke tenants; tenant lease/legal removal is outside scope. |

**Display:** In the owner dashboard, invitations are shown with a combined display status (e.g. pending / ongoing / cancelled / expired) that considers both status and token_state (e.g. BURNED + pending may show as “ongoing” when a stay exists).

---

## 15. Occupancy Status and Confirmation

### Property occupancy statuses (reference)
- **VACANT:** No current guest; token typically STAGED.
- **OCCUPIED:** Current guest; set when the guest **checks in** (or when bulk upload has Occupied=YES and a stay/invite is created).
- **UNCONFIRMED:** Set by the system when the Status Confirmation runs and the owner has not confirmed (vacated/renewed/holdover) by 48 hours after lease end. Recorded silence; Shield is turned on and token staged.

### Owner confirmation (after lease end)
- When a stay has passed its end date and Status Confirmation is on, the owner is prompted to **confirm occupancy** with one of:
  - **Unit Vacated** → Stay checked out, property VACANT, Shield off, invite token EXPIRED.
  - **Lease Renewed** → New lease end date set, property stays OCCUPIED, invite token stays BURNED.
  - **Holdover** → Guest still in unit, property stays OCCUPIED, no date change.
- If the owner does **not** respond by the deadline, the Status Confirmation auto-execute runs and the property is set to **UNCONFIRMED** with Shield on.

---

## 16. Invitation Agreement and Signing

### How templates are created and how they work (product level)

The **Guest Acknowledgment** document is the agreement the guest must sign to accept an invitation. It is built from a **fixed structure** plus **jurisdiction-specific** wording. Templates are **not** stored in the database; they are defined in the application and assembled at runtime using data from the invitation, property, and jurisdiction source of truth (SOT). No external legal API is used—all text is either fixed or from internal data (UPL safeguard).

**Template choice (which variant is used):**

1. When an agreement is needed (e.g. guest opens invite link or signs), the system looks up the **invitation** and its **property** (address, zip, region).
2. **Jurisdiction** is resolved from the **property’s zip code and region code** using the jurisdiction SOT (same lookup as the live page and JLE). That returns a region (e.g. CA, FL, NYC, TX, WA) and, when available, statute citations and state name.
3. The system picks the **template variant** by region:
   - **California (CA)** → California template: section 3 is “transient occupancy” (14 days in 6 months / 7 consecutive nights; Cal. Civ. Code § 1940).
   - **Florida (FL)** → Florida template: section 3 is the four acknowledgments under F.S. § 82.036 (not tenant, not owner/family, temporary occupancy, removal by law enforcement).
   - **New York (NYC / NY)** → New York template: section 3 is 29 consecutive days / 30-day tenancy reference under New York law.
   - **Texas, Washington, or any other region** → **Generic** template: section 3 references “maximum permitted guest stay” under applicable state/local law, using the first statute citation from the jurisdiction SOT when available.

**How the document is constructed:**

- **Title:** “Guest Acknowledgment and Revocable License to Occupy” (same for all regions).
- **Header block:** Property address, Guest (name or “[Guest Name]” until signed), Authorized Stay (check-in to check-out dates). All of these are **dynamically filled** from the invitation and property.
- **Six numbered sections** (same order everywhere; only section 3 and the disclaimer wording vary by region):
  1. **Acknowledgment of Authority** — Owner granted limited POA to DocuStay to maintain records of property status, including guest occupancy.
  2. **Grant of Revocable License** — Revocable license, no tenancy; personal, non-assignable; no sublet.
  3. **Jurisdiction-specific clause** — As above (CA / FL / NY / generic).
  4. **No Right to Hold Over** — No right to remain after End Date; holding over may subject to legal action.
  5. **Revocation** — License revocable at will; owner may terminate at any time, for any reason, without notice.
  6. **Disclaimer** — “Not a lease; no tenant rights under [California law / Florida Residential Landlord and Tenant Act / New York Real Property Law / applicable state and local law]; DocuStay is not a law firm and does not provide legal advice.” The bracketed part is chosen by region.
- **Signature block:** “Guest Signature” and “Date” with blank lines for the guest to fill at signing. Optional “IP Address” for audit. When the guest signs, the system fills these in the stored copy and in the PDF.
- **Dynamic data sources (no AI):** Property address (from property), guest name (from input or placeholder), stay start/end (from invitation), statute citation and state name in disclaimer (from jurisdiction SOT). The same property and invitation always produce the same agreement text so the hash is deterministic for signing and verification.

**Presentation (UI and PDF):**

- The same **content string** is used for both the in-app view and the PDF. Labels and section headings are marked with a simple **bold** convention in the text (e.g. `**Property:**`). The **UI** (agreement modal) renders that as bold and preserves line breaks so the document is readable. The **PDF** generator interprets the same markers and renders those parts in bold and keeps the same layout. So the document looks consistent and presentable in both places.

**Fallback:**

- If jurisdiction cannot be resolved (e.g. unknown zip/region), the system still produces an agreement using the **generic** template with “applicable state and local law” and no specific statute. The guest can still sign; the document remains valid and deterministic.

### Building the agreement
- The **invitation agreement** is built from the **jurisdiction source of truth**: property zip → region → jurisdiction + statutes (and removal text, max stay, etc.). So the same property always gets the same legal “wrap” for that region.
- The document includes: property address, guest name placeholder, check-in/check-out dates, host name, applicable statutes and removal text. It is **deterministic** for hashing and signing (no AI).

### Signing (Dropbox Sign)
- The guest **must complete signing in Dropbox Sign** to **accept** the invitation. We use **Dropbox Sign** (e-signature provider) for the legal signature; we do **not** treat an in-app–generated PDF as the signed document.
- **Flow:** When the guest clicks “Sign with Dropbox Sign,” we create a **signature** record (invitation code, guest email, document hash, IP, etc.), send the agreement PDF to Dropbox Sign, and give the guest a link to open Dropbox’s signing page (redirect or new tab). We **do not** store our own filled PDF as “signed”; we only store the **PDF returned by Dropbox** after the guest has signed there.
- **Pending state:** Until Dropbox reports the document as signed, the invite appears in **Pending actions** on the guest dashboard (“Awaiting your signature in Dropbox”). The stay is **not** created and the invitation is **not** accepted until the signed PDF is available from Dropbox.
- **Acceptance:** When the guest (or the system on refresh/return) calls **accept-invite** with the agreement signature id, the backend verifies that the signature has a **completed signed PDF from Dropbox** (fetches from Dropbox if not yet stored). Only then: Stay created, invitation accepted, token BURNED, Shield off.
- **Download:** The guest can download the **signed agreement PDF** for their stay from the dashboard; that PDF is always the one from Dropbox (never a pre-filled in-app copy). The same rule applies to the guest stay signed-PDF endpoint: when a signature was sent to Dropbox, we always prefer (and store) the PDF from Dropbox.

---

## 17. Master POA (Power of Attorney)

### What it is
- A **one-time**, account-level document that establishes DocuStay as the owner’s representative for property protection activities. One Master POA per owner (or authorized agent); all properties under that owner are governed by it.

### When it’s signed
- During **owner onboarding**: after **identity verification** (Stripe Identity), the owner is shown the Master POA and must sign it before completing signup (and before adding properties). The signature is stored and linked to the user.
- Existing owners who have not yet signed can be directed to a “link POA” or “sign POA” flow from the dashboard or settings.

### Live page and jurisdiction wrap
- The **live property page** presents DocuStay as operating under this authority. The “authority package” for a given property combines: Master POA (by owner), **jurisdiction wrap** (from zip → region → statutes in DB), and **property identifier** (Tax ID/APN). No AI is used to interpret law; all text is from the DB or fixed templates.

---

## 18. Overstay and Initiate Removal

### Overstay detection
- A stay is considered **overstay** when: guest has **checked in**, **stay end date has passed**, and the guest has **not** checked out and the stay is **not** cancelled. A daily (or on-demand) job finds such stays, sends **overstay alerts** (email to owner and guest), and logs “Overstay occurred.”

### Revoke stay (Kill Switch)
- The owner can **revoke** any stay (not only overstay). Effect: stay’s **revoked_at** is set; guest must vacate within **12 hours** (vacate_by = revoked_at + 12h). Invitation token state → **REVOKED**. The guest receives an urgent 12-hour vacate notice and sees **vacate_by** on their dashboard. Revoke does not require the stay to be in overstay.

### Initiate removal (overstay)
- For an **overstayed** guest (stay end date in the past, not checked out), the owner can **initiate removal**. The system:
  - Revokes the USAT token for that stay (and property if released).
  - Sets the stay’s **revoked_at** (same 12-hour vacate_by as revoke).
  - Sends removal notices to guest and owner and creates an audit log entry.
- The guest sees the **vacate_by** deadline and revocation on their dashboard/live context.

---

## 19. Guest Check-In and Check-Out

### Check-in
- Available **on or after** the stay start date. The guest clicks **Check in** for that stay.
- Effects: Stay’s **checked_in_at** is set; property **occupancy status** → **OCCUPIED**; if Shield was on, it is turned **off**. Status Confirmation for this stay is turned **on** 48 hours before stay end (or in test mode after a short delay).
- Until check-in, the stay is “upcoming”; Status Confirmation and occupancy logic use checked_in_at.

### Check-out (guest-end stay)
- Guest can **end stay** (check out) when the stay has started (start date ≤ today) and not already ended. The system sets stay end date to today, **checked_out_at**, and invite token → **EXPIRED**. If no other active stay at the property, property occupancy → **VACANT** and USAT token state → **STAGED**. Owner and guest receive checkout confirmation emails.

### Cancel (future stay)
- For a **future** stay (start date in the future), the guest can **cancel**. The stay is marked cancelled (end date set to day before start, cancelled_at set), invite token → **REVOKED**. If no other active stay, property → VACANT and token → STAGED. Owner is notified.

---

## 20. Audit Log and Billing Log

- **Audit log:** Append-only. Key events (status changes, Shield, Status Confirmation, property updates, invitation created/accepted/cancelled, check-in/check-out, revocation, occupancy confirmation, billing) are logged with category, title, description, property/stay/invitation ids, actor, IP, user-agent, and optional metadata. Used for evidence and support.
- **Billing:** Invoice paid events from Stripe are logged (invoice.paid). Onboarding payment is recorded and triggers subscription creation. The owner can see invoices and payments in the Billing area; “can invite” is typically gated on onboarding invoice paid when an onboarding fee was charged.

---

## 21. Summary Table (Quick Reference)

| Feature | How it works (product level) |
|--------|------------------------------|
| **Shield ON** | Owner toggle; or auto on last day of stay; or auto on when Status Confirmation runs (no owner response). |
| **Shield OFF** | Owner toggle; or when new guest accepts invite; or when owner confirms Unit Vacated; or at guest check-in. |
| **Status Confirmation (occupied)** | 48h before lease end → first prompt; lease end day → no automatic change; 48h after with no response → UNCONFIRMED + Shield on. Owner confirms Vacated / Renewed / Holdover. |
| **Jurisdiction SOT** | Stored in DB (regions, statutes, zip→region). Used for agreements, live page wrap, JLE. No AI. |
| **Stripe Identity** | Required before POA and property add; Stripe hosted flow; confirm on return. |
| **Guest invite** | Owner creates invite → link shared → guest signs agreement → accept (signup or login) → Stay created, token BURNED, Shield off. |
| **Guest Acknowledgment templates** | Fixed 6-section structure; template variant by region (CA/FL/NY/generic); dynamic data from invitation + property + jurisdiction SOT; same content for UI and PDF with bold labels. See §16. |
| **Onboarding fee** | First property add (single or bulk); tier by total units (e.g. 1–5 $299, 6–20 $49/unit, …); one-time invoice; idempotent. |
| **Subscription** | Created after onboarding invoice paid; $1/unit + $10/Shield unit; quantities synced on property/Shield changes; Stripe prorates. |
| **Live link / QR** | Per-property slug → public page with jurisdiction wrap and evidence; QR encodes same URL. |
| **Verify portal** | Public no-login page (nav "Verify"). Token = Invitation ID; valid if BURNED + active stay; optional address match. All attempts logged. Valid result: authority summary, live link; invalid: reason only. See §9. |
| **CSV upload** | Required: Address, City, State, Zip, Occupied; if Occupied=YES: Tenant, Lease Start/End. Creates/updates properties; for Occupied=YES creates BURNED invitation (no Stay until tenant signs up); invitation appears in Invitations and Stays as "Pending sign-up." Billing as for single add. See §11. |
| **Property edit** | Owner can update name, address, city, state, zip, region, owner_occupied, property_type, bedrooms, Shield, vacant_monitoring_enabled (vacant only), tax_id, apn. |
| **USAT token** | Per property; STAGED vs RELEASED; released when occupied (e.g. bulk YES); revoked on vacated/checkout/removal/Status Confirmation. |
| **Occupancy confirm** | Owner chooses Vacated / Renewed / Holdover after lease end; no response → Status Confirmation runs → UNCONFIRMED. |
| **Revoke (Kill Switch)** | Owner can revoke any stay → 12h vacate deadline, invite token REVOKED; overstay “initiate removal” also revokes USAT and sets same 12h. |
| **Property states** | **Occupancy:** vacant, occupied, unknown, unconfirmed. **USAT token:** staged, released. See §14. |
| **Invite ID states** | **Status:** pending, ongoing, accepted, cancelled, expired. **token_state:** STAGED, BURNED, EXPIRED, REVOKED. See §14. |
| **Owner portfolio view** | Public page by owner slug (no login). Owner gets link in Settings. Shows owner name, contact (email, phone, state), list of properties (name, city, state, region, type, bedrooms). See §10. |
| **Vacant monitoring** | Owner enables for a vacant unit; system prompts at defined intervals (e.g. every 7 days); owner responds via **Confirm still vacant**; no response by deadline → UNCONFIRMED + Shield on. See §2. |
| **Admin** | Separate role (owner / guest / admin). Go to #admin for login/dashboard (not linked in main nav). Read-only: users, audit logs, properties, stays, invitations. First admin via script. See §22. |

This document is intended to stay at a **product and logic** level; for implementation details, refer to the codebase and technical docs.

---

## 22. Admin (Internal)

### What it is
- **Admin** is a separate **user role** (alongside owner and guest). Admin users are intended for internal support and operations: viewing system-wide data, not for customer-facing actions.
- Admins do **not** own properties or receive invitations; they use a dedicated **admin login** and **admin dashboard** to view users, audit logs, properties, stays, and invitations across the platform.

### Access and security
- **Login:** Admins go to **`/#admin`**. That URL shows the admin **login** form when not signed in, and the admin dashboard when signed in as an admin. This page is **not linked** from the main app navigation; access is by direct URL only (e.g. `http://yourapp.com/#admin`).
- **Auth:** The same JWT/login flow is used, but the backend returns the user’s **role** (e.g. `user_type: ADMIN`). The frontend only allows entry to the admin dashboard if the logged-in user has role **admin**; otherwise it shows an error (e.g. “This account is not an admin”).
- **API:** All admin API routes (e.g. `/api/admin/*`) require the current user to have **role = admin**. If a non-admin calls these endpoints, the API returns 403.

### Creating the first admin
- The **admin** value exists on the `userrole` enum (in the `User` model). On startup, `seed_admin_user` creates or updates the default admin user (e.g. `admin@docustay.com` / `DreamsOfDreams89`).
- All verification flags are set for the admin (email verified, identity/POA waived) so they can log in without owner flows.
- Override via `.env`: `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_FULL_NAME`.

### What admins can do (read-only)
The admin dashboard and API are **read-only**. No create/update/delete of users, properties, stays, or invitations is exposed to admins through this UI.

| Area | What the admin sees / can filter |
|------|----------------------------------|
| **Users** | List all users with optional search (email, full name) and filter by role (owner, guest, admin). Columns: id, email, role, full name, created date. |
| **Audit logs** | Global audit log with filters: date range (from/to), category, property id, actor user id, and search in title/message. Shows time, category, title, message, actor (email or user id), and optional property name. |
| **Properties** | List all properties with optional search (name, street, city, state), filter by region code, and option to include soft-deleted properties. Shows id, owner email, name, address, region, occupancy status, deleted_at, created_at. |
| **Stays** | List all stays with optional filters: property id, owner id, guest id. Shows id, property, guest/owner emails, dates, region, check-in/check-out/revoked/cancelled timestamps, created_at. |
| **Invitations** | List all invitations with optional filters: property id, owner id, status. Shows id, invitation code, owner/property, guest name/email, stay dates, status, token state, created_at. |

### Logout
- From the admin dashboard, the admin can **Logout**. They are then sent back to `#admin` (the admin login form). They do not land on the main owner/guest login unless they use the “Back to main login” link on the admin login form.
