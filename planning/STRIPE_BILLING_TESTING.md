# Stripe Billing – How to Test and Verify from the Frontend

This guide describes how to confirm that all four parts of the **STRIPE BILLING LOGIC SPEC** are implemented and working, using the owner dashboard and backend behavior.

---

## How the monthly subscription is handled in code (no background job)

- **There is no cron or background job in our code for recurring billing.** Stripe does it.
- We create a **Stripe Subscription** when the owner completes onboarding (first property add) or when they reactivate a property after having zero units. See `app/services/billing.py`: `ensure_subscription()` calls `stripe.Subscription.create()` with two items (baseline $1/unit and Shield $10/unit).
- **Stripe** then:
  - Generates invoices on the subscription’s billing cycle (e.g. monthly).
  - Charges the customer’s default payment method.
  - Sends `invoice.paid` (and other) webhooks; we log `invoice.paid` and set `onboarding_invoice_paid_at` when the onboarding invoice is paid.
- Our code only **updates** the subscription when unit count or Shield count changes: `sync_subscription_quantities()` is called from property add/remove, Shield toggle, reactivate, and dashboard “Unit vacated”. Stripe prorates automatically. So: **subscription creation and quantity updates are in our code; recurring invoice generation and charging are entirely handled by Stripe.**

---

## How Stripe charges, adding properties, and open invoices

### How Stripe charges

- **Onboarding (one-time):** We create a **one-time Stripe Invoice**, add one line item (the onboarding fee), and finalize it. Stripe then either charges the customer’s default payment method immediately (`charge_automatically`) or keeps the invoice open so they can pay via the Billing Portal / hosted page. No recurring schedule.
- **Monthly subscription:** We create a **Stripe Subscription** with two line items (baseline $1/unit, Shield $10/unit). Stripe generates **recurring invoices** on the subscription’s billing cycle (e.g. monthly) and charges the default payment method. We do not run a cron; Stripe creates and pays those invoices.

### If the user adds more properties, are they charged less?

- **No.** Adding more properties **increases** what they pay, but in a prorated way.
- **Onboarding:** Charged **only once** (first time they go from 0 → N properties). If they add more properties **later**, we do **not** create a second onboarding invoice (`onboarding_billing_completed_at` is already set). So they are not charged onboarding again when adding more properties.
- **Subscription:** When they add a property, we call `sync_subscription_quantities()`, which updates the subscription’s quantities (more units, and possibly more Shield). **Stripe prorates**: they are charged **more** for the extra unit(s) for the **remainder of the current billing period**. So they pay more when they add properties, not less; the extra amount is prorated.

### What if the user adds more properties while they already have an open invoice?

- **Open onboarding invoice:** If the owner has an **unpaid onboarding invoice** (e.g. $299 for 1 unit) and then adds more properties:
  - We **do not** create a second onboarding invoice. Onboarding is idempotent: we only run it when `onboarding_billing_completed_at` is `None`. So the existing open invoice stays as-is (same amount).
  - We **do** update the subscription: after the first property we already created the subscription; when they add more, we call `sync_subscription_quantities()` and the subscription’s **quantities** go up. Stripe will reflect that on the **subscription’s** next (or current) invoice with proration. The **onboarding invoice** is a separate, one-time invoice; it is not changed when they add more properties.
- **Open subscription invoice:** If Stripe has already generated an **open subscription invoice** (e.g. monthly invoice not yet paid) and the owner then adds a property, we update the subscription quantities. Stripe typically **adds a proration line** to that open subscription invoice for the new unit(s), so the amount due on that invoice **increases**. When they pay, they pay the updated total (original lines + proration for the new unit(s)).

So: **onboarding invoice = fixed, one-time, never updated when they add more properties. Subscription = updated when they add/remove properties or toggle Shield; Stripe prorates and may add to the current open subscription invoice.**

---

## Prerequisites

- **Stripe Test Mode**: Use test API keys in `.env` (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`). See `planning/STRIPE_TEST_MODE.md` if needed.
- **Owner account**: Completed account onboarding (identity + Master POA) so you can add properties.
- **Stripe Dashboard**: Open [Stripe Dashboard → Customers](https://dashboard.stripe.com/test/customers) and [Subscriptions](https://dashboard.stripe.com/test/subscriptions) in test mode to verify charges and subscription items.

---

## 1. Onboarding Fee (One-Time Charge)

**Spec:** Charged at initial property upload; tier by total units in that batch; single line item; non-recurring; charge immediately (or hosted invoice URL if no payment method).

### How to test from the frontend

1. **First-time owner (0 → 1+ properties)**  
   - Log in as an owner who has **no properties** yet.  
   - Add **one property** (Add Property flow) and complete it.  
   - **Expect:**  
     - Backend creates Stripe Customer (if not exists), creates one-time invoice for onboarding, finalizes it.  
     - **Billing tab:** New invoice appears (e.g. “DocuStay onboarding fee (1 unit)” → **$299**).  
     - If no default payment method: “Pay invoice” link opens Stripe hosted checkout.  
     - After paying (or if auto-charge succeeds), invoice status becomes “paid”.  
   - In **Stripe Dashboard → Customers** → select the customer → **Invoices**: one invoice, one line item, **$299**, non-recurring.

2. **Tier by unit count (bulk upload)**  
   - Use an owner with **no properties**.  
   - **Bulk upload** a CSV with e.g. **7 properties** (same owner).  
   - **Expect:**  
     - One onboarding invoice for **7 units** at **$49/unit** = **$343** (tier 6–20).  
     - Only **one** onboarding invoice ever for that owner; adding more properties later does **not** create a second onboarding invoice.  
   - In Stripe: one invoice, single line, amount matching the tier (e.g. 7 × $49).

3. **Tier table check**  
   - Optionally run backend logic with different unit counts to confirm tiers (or inspect `app/services/billing.py` `_ONBOARDING_TIERS`):  
     - 1–5 → $299 flat  
     - 6–20 → $49/unit  
     - 21–100 → $29/unit  
     - 101–500 → $19/unit  
     - 501–2,000 → $14/unit  
     - 2,001–10,000 → $10/unit  
     - 10,001+ → $7/unit  

**Frontend verification:**  
- **Billing** tab shows the onboarding invoice and “Pay invoice” / “View” as appropriate.  
- **Logs** tab shows a “Billing” entry for “Onboarding invoice created” with amount and unit count.

**Pay invoice and Klarna redirect:**  
- “Pay invoice” uses the **Stripe Customer Billing Portal** (not the raw hosted invoice URL). That way, after payment—including when paying with **Klarna** or other redirect methods—Stripe redirects the user back to your app (`STRIPE_IDENTITY_RETURN_URL` + `/owner`). If you previously landed on `pay.test.klarna.com` with no way back, that was because the hosted invoice page does not support a custom return URL; the portal flow fixes this.  
- Ensure **Stripe Dashboard → Settings → Billing → Customer portal** is configured so the portal is available.  
- In test mode, you can also use card `4242 4242 4242 4242` to avoid redirect-based methods.

---

## 2. Monthly Subscription Billing

**Spec:** $1/unit baseline (recurring monthly) + $10/unit when Shield is active.

### How to test from the frontend

1. **Subscription created after onboarding**  
   - After the first property add (or bulk upload), backend creates a Stripe Subscription with two items:  
     - Baseline: $1/unit, quantity = active unit count.  
     - Shield: $10/unit, quantity = count of properties with Shield on.  
   - **Billing tab:** After onboarding, you may see a subscription invoice when Stripe generates it (e.g. at period end or when proration runs).  
   - **Stripe Dashboard → Subscriptions:** One subscription per owner; two line items (Baseline, Shield) with correct quantities.

2. **Quantities match**  
   - In the app, note **number of active (non-deleted) properties** and **how many have Shield ON**.  
   - In Stripe subscription detail: Baseline quantity = unit count, Shield quantity = Shield count.  
   - Frontend does not need to show these numbers; verifying in Stripe is enough to confirm state-driven billing.

**Frontend verification:**  
- Billing tab shows subscription-related invoices when Stripe creates them.  
- Logs may show “Invoice paid” for subscription invoices (if webhook is configured).

---

## 3. Shield Mode Billing Behavior

**Spec:** Real-time toggle; immediate proration when Shield turns on or off; $1 baseline always active.

**Implementation verification (all touchpoints call `sync_subscription_quantities`):**

| Shield change | Where | Sync called? |
|---------------|--------|---------------|
| **Shield ON** (last day of stay) | `app/services/stay_timer.py` – sets `shield_mode_enabled = 1` | Yes, same flow (~266) |
| **Shield ON** (Status Confirmation triggered, no owner response) | `app/services/stay_timer.py` – sets `shield_mode_enabled = 1` | Yes, same flow (~378) |
| **Shield OFF** (owner turns off in UI) | `app/routers/owners.py` PATCH property – sets `shield_mode_enabled = 0` | Yes, when `shield_mode_enabled` in changes_meta (~1269) |
| **Shield OFF** (owner confirms Unit Vacated) | `app/routers/dashboard.py` confirm_occupancy vacated – sets `shield_mode_enabled = 0` | Yes, same flow (~512) |
| **Shield OFF** (guest accepts invite / stay created) | `app/routers/auth.py` – sets `_prop.shield_mode_enabled = 0` (3 paths: signup-accept, login-accept, existing guest accept) | Yes, each path calls sync (~449, ~1017, ~1239) |

Subscription structure: two line items — **Baseline** $1/unit (quantity = total non-deleted units) and **Shield** $10/unit (quantity = units with `shield_mode_enabled == 1`). When we call `stripe.Subscription.modify(..., items=[{quantity: units}, {quantity: shield_units}])`, Stripe applies **immediate proration** by default ([Stripe prorations](https://docs.stripe.com/billing/subscriptions/prorations)). The $1 baseline is unchanged when Shield toggles; only the Shield line quantity changes.

### How to test from the frontend

1. **Shield ON (e.g. last day of stay or Status Confirmation)**
   - Have a property with an active stay where Shield gets turned **on** (e.g. last day of stay job or Status Confirmation trigger).
   - **Expect:** Backend sets `shield_mode_enabled = 1` and calls `sync_subscription_quantities`; Stripe subscription Shield quantity increases; next invoice (or proration) includes extra $10/unit for that unit.  
   - **Stripe Dashboard → Subscription:** Shield line quantity increases by 1 (or by number of units that got Shield on).

2. **Shield OFF (owner turns off)**  
   - In **Properties** (or property settings), turn **Shield Mode OFF** for a property that had it on.  
   - **Expect:** Backend sets `shield_mode_enabled = 0` and syncs; Stripe Shield quantity decreases; proration credits for the remainder of the period.  
   - **Stripe Dashboard → Subscription:** Shield quantity decreases; upcoming invoice or activity shows proration.

3. **Vacated → Shield off**  
   - For a stay where the property had Shield on, use **Confirm occupancy → Unit Vacated**.  
   - **Expect:** Backend clears Shield for that property and syncs; Shield quantity drops; billing reflects no $10 for that unit going forward (prorated).

**Frontend verification:**  
- Turning Shield off in the UI should not error; Billing/Logs can be checked for consistency.  
- Confirming “Unit Vacated” when Shield was on should not error; Stripe subscription quantities should drop as above.

---

## 4. Edge Case Handling (State-Driven, Proration)

**Spec:** Units added mid-cycle → prorate immediately; units removed → stop billing immediately (prorated); Shield toggled mid-cycle → prorate immediately. No manual override.

### How to test from the frontend

1. **Units added mid-cycle**  
   - Owner already has a subscription (e.g. 2 properties).  
   - **Add one more property** (single add or bulk).  
   - **Expect:** Backend calls `sync_subscription_quantities`; Stripe subscription baseline (and Shield if new unit has Shield) quantity increases; Stripe prorates for the rest of the period.  
   - **Stripe Dashboard → Subscription:** Quantities go up; invoice preview or next invoice shows prorated amount for the new unit(s).

2. **Units removed (soft-delete)**  
   - **Remove** a property from the dashboard (soft-delete: move to Inactive).  
   - **Expect:** Backend sets `deleted_at`, then `sync_subscription_quantities`; baseline (and Shield for that unit) quantity decreases; Stripe prorates (credit) for the remainder.  
   - If that was the **last** unit, subscription is **cancelled** (prorated); no further subscription charges until they add a property again.

3. **Reactivate property**  
   - **Reactivate** an inactive property.  
   - **Expect:** Backend clears `deleted_at`, then syncs; if there was no subscription (all units were removed), a new subscription is created when they have ≥1 unit again; quantities match current units and Shield count.

4. **Shield toggled mid-cycle**  
   - Covered in §3 (Shield ON/OFF and Vacated).  
   - **Expect:** Every Shield change triggers sync; Stripe subscription Shield quantity updates and proration is applied.

**Frontend verification:**  
- Add property → no error; Billing/Stripe show updated quantities and proration.  
- Remove (deactivate) property → no error; subscription quantities decrease or subscription cancels if 0 units.  
- Reactivate → no error; subscription exists again with correct quantities.  
- Toggle Shield or confirm vacated → no error; Stripe quantities and proration as above.

---

## Quick Checklist (Frontend + Stripe)

| Requirement | What to do in the app | What to check |
|-------------|------------------------|----------------|
| **1. Onboarding fee** | First add or bulk upload (first batch only) | Billing tab: one onboarding invoice; Stripe: one invoice, correct tier amount |
| **2. Monthly subscription** | After first properties added | Stripe: subscription with Baseline ($1/unit) + Shield ($10/unit) items |
| **3. Shield billing** | Turn Shield off; confirm vacated when Shield was on; let Shield turn on (last day / Status Confirmation) | Stripe: Shield quantity changes; proration on next invoice/activity |
| **4. Add unit** | Add property mid-cycle | Stripe: quantities increase; proration |
| **4. Remove unit** | Deactivate (remove) property | Stripe: quantities decrease or subscription cancelled; proration |
| **4. Reactivate** | Reactivate inactive property | Stripe: subscription (re)created, quantities correct |

---

## Logs and Billing Tab

- **Logs** (owner dashboard): Filter by “Billing” to see “Onboarding invoice created”, “Invoice paid”, etc.  
- **Billing** tab: Lists invoices (onboarding + subscription) and payment history from the backend; “Pay invoice” / “View” links use Stripe hosted URLs when available.

Using the above flows and the Stripe test dashboard, you can confirm that onboarding, subscription, Shield, and edge cases are all implemented and state-driven with immediate proration.
