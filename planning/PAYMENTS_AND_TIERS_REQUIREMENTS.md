# Payments and Tiers – Requirements and Existing App Changes

This document lists **all requirements relevant to payments and pricing tiers** and **what functionality in the existing app must be changed** to support them. It is scoped to tiers and billing only (no entity model, token states, or company flows unless they affect billing).

---

## 1. Payment and tier requirements (from client spec)

### 1.1 Onboarding fee (one-time)

| Item | Requirement |
|------|-------------|
| **Trigger** | Initial property upload (first time owner completes uploading their first batch of properties). |
| **Tier** | Determined by **total units** in that onboarding batch. |
| **Pricing brackets** | 1–5 units → $299 flat; 6–20 → $49/unit; 21–100 → $29/unit; 101–500 → $19/unit; 501–2,000 → $14/unit; 2,001–10,000 → $10/unit; 10,001+ → $7/unit. |
| **Rules** | Charge immediately upon onboarding completion; single invoice line item; non-recurring; tier auto-calculated by total units. |

### 1.2 Monthly subscription

| Item | Requirement |
|------|-------------|
| **Per unit** | $1 baseline ledger fee, recurring monthly. |
| **Shield** | $10/unit/month **if** Shield status = active for that unit. |
| **Total** | Each unit = $1 always + $10 when Shield is on. |

### 1.3 Shield mode billing behavior

| Item | Requirement |
|------|-------------|
| **Stripe** | Per-unit metered billing or quantity-based subscription. |
| **Toggle** | Real-time; immediate proration when Shield turns on; immediate proration when Shield turns off. |
| **Baseline** | $1/unit remains active regardless of Shield. |

### 1.4 Edge cases (state-driven, no manual override)

| Scenario | Required behavior |
|----------|-------------------|
| Units added mid-cycle | Prorate immediately. |
| Units removed | Stop billing immediately (prorated). |
| Shield toggled mid-cycle | Prorate immediately. |

---

## 2. Definitions for implementation

- **Unit** = one property (1 Property = 1 unit). Billing is per property count; no separate “unit” field required for billing logic.
- **Onboarding completion (for billing)** = first time the owner finishes uploading their **initial batch** of properties. This can be:
  - First successful **bulk upload** (total units = number of properties in that CSV), or
  - First **single property add** (total units = 1), or
  - A defined rule, e.g. “first time total property count goes from 0 to N” (first add or first bulk).
- **Account onboarding** (existing) = identity verification + Master POA linked. This is unchanged; it gates access to add properties. **Billing onboarding** is a separate event that happens when they first add properties.

---

## 3. Existing app functionality that must be changed

### 3.1 Data model

| Location | Current state | Change required |
|----------|----------------|-----------------|
| **Billing customer / subscription** | None. Stripe used only for Identity (`User.stripe_verification_session_id`, `app/config.py` Stripe keys). | Add fields to associate an owner (or future entity) with Stripe Billing: e.g. `stripe_customer_id`, `stripe_subscription_id`. Likely on **OwnerProfile** (or future OwnerEntity) so one customer/subscription per owner/entity. |
| **Onboarding fee tracking** | No concept of “first property batch” or “onboarding completed for billing.” | Add fields to record that the one-time onboarding fee has been charged and for how many units, e.g. `onboarding_billing_completed_at`, `onboarding_billing_unit_count` (on OwnerProfile or entity). Prevents charging the onboarding fee more than once. |

**Suggested files:** `app/models/owner.py` (OwnerProfile or Property), or new `app/models/billing.py` if you prefer a separate billing table.

---

### 3.2 Property upload flows (when to charge onboarding fee)

| Location | Current state | Change required |
|----------|----------------|-----------------|
| **`app/routers/owners.py`** | `add_property`: creates one property; `bulk_upload_properties`: creates/updates many. Both run after `require_owner_onboarding_complete` (POA linked). No billing. | After creating new property/ies, detect **first time** this owner goes from 0 to N properties (e.g. count before vs after). If this is the **first batch** (onboarding for billing), call a new **onboarding completion hook** with `total_units` = number of properties just added (or total count, per product rule). Hook will create Stripe customer (if needed), charge onboarding fee, then create subscription. |
| **Idempotency** | N/A | Ensure onboarding fee runs only once per owner (use `onboarding_billing_completed_at` or equivalent). |

**Suggested files:** `app/routers/owners.py` (`add_property`, `bulk_upload_properties`), new `app/services/billing.py` (e.g. `on_onboarding_properties_completed(owner_profile_id, total_units)`).

---

### 3.3 Onboarding fee calculation and charge

| Location | Current state | Change required |
|----------|----------------|-----------------|
| **Backend** | No billing logic. | New service (e.g. `app/services/billing.py`): given `total_units`, return tier and amount (1–5 → $299; 6–20 → $49/unit; etc.). Create Stripe Customer if not exists; create one-time Invoice or PaymentIntent with single line item; charge immediately. Store `onboarding_billing_completed_at` and `onboarding_billing_unit_count` so fee is never charged again. |
| **Config** | `app/config.py` has `stripe_secret_key`, `stripe_publishable_key` for Identity. | Reuse same Stripe account for billing (same secret key) unless product requires a separate billing account. No config change required if reusing. |

**Suggested files:** New `app/services/billing.py`, `app/routers/billing.py` (optional: webhooks for invoice.paid), `app/models/owner.py` (or billing model).

---

### 3.4 Monthly subscription (baseline + Shield)

| Location | Current state | Change required |
|----------|----------------|-----------------|
| **Backend** | No subscription. | After onboarding fee (or in same onboarding hook), create Stripe Subscription with: (1) baseline $1/unit (quantity = total non-deleted properties), (2) Shield $10/unit (quantity = count of properties where `shield_mode_enabled == 1`). Use quantity-based subscription so Stripe prorates on quantity change. Store `stripe_subscription_id` (and optionally subscription item ids for baseline vs Shield) so future updates can change quantities. |
| **Property count** | Properties are per `owner_profile_id`; soft delete via `Property.deleted_at`. | Billing must count only **non-deleted** properties for “units” and only non-deleted with `shield_mode_enabled == 1` for Shield quantity. |

**Suggested files:** `app/services/billing.py`, `app/models/owner.py` (or billing model).

---

### 3.5 Syncing unit count and Shield state to Stripe (proration)

| Location | Current state | Change required |
|----------|----------------|-----------------|
| **Add property** | `app/routers/owners.py` `add_property` creates one property. | After create, if subscription exists: update subscription quantities (total units +1; Shield +1 if new property has `shield_mode_enabled == 1`). Stripe prorates automatically. |
| **Remove / soft-delete property** | Properties can be soft-deleted (`deleted_at`). No bulk “delete many” in spec; assume single property delete or bulk delete exists or will. | When a property is removed (or soft-deleted and excluded from billing): update subscription quantities (units −1; Shield −1 if that property had Shield on). Stop billing for that unit immediately (prorated). |
| **Shield toggle** | `app/routers/owners.py` PATCH property: only allows setting `shield_mode_enabled` to **False** (owner can turn off). `app/services/stay_timer.py` and dashboard flows set `shield_mode_enabled = 1` (system turns on). | Whenever `shield_mode_enabled` changes (either direction): update Stripe subscription Shield quantity to match current count of properties with `shield_mode_enabled == 1`. Proration is immediate. |
| **Cron / consistency** | N/A | Optional: periodic job to reconcile DB unit/Shield counts with Stripe subscription quantities (e.g. if an update failed). |

**Suggested files:** `app/services/billing.py` (e.g. `sync_subscription_quantities(owner_profile_id)`), `app/routers/owners.py` (after add_property, after bulk_upload, in PATCH property for shield_mode_enabled), any property-delete or soft-delete path.

---

### 3.6 Shield mode touchpoints (existing code that affects billing)

| Location | Current state | Change required |
|----------|----------------|-----------------|
| **`app/routers/owners.py`** | PATCH property: `if data.shield_mode_enabled is not None and data.shield_mode_enabled is False: prop.shield_mode_enabled = 0`. | After updating `prop.shield_mode_enabled`, call billing service to sync Shield quantity to Stripe. |
| **`app/services/stay_timer.py`** | Sets `prop.shield_mode_enabled = 1` on last day of stay and when Status Confirmation triggers (UNCONFIRMED). | After setting `shield_mode_enabled = 1`, call billing service to sync Shield quantity (or run sync at end of job for all affected owners). |
| **`app/routers/auth.py`** | When new stay is created / occupancy confirmed, clears Shield: `_prop.shield_mode_enabled = 0`. | After clearing, call billing service to sync Shield quantity for that owner. |
| **`app/routers/dashboard.py`** | Confirm occupancy (vacated/renewed/holdover) and other flows may clear or set Shield. | Any code path that sets or clears `shield_mode_enabled` must trigger a subscription quantity sync for that owner. |

**Suggested approach:** Centralize “after shield or unit count changes” in one place (e.g. `billing.sync_subscription_quantities(owner_profile_id)`) and call it from all touchpoints above.

---

### 3.7 Frontend (optional for “tiers only” scope)

| Location | Current state | Change required |
|----------|----------------|-----------------|
| **Owner dashboard / billing UI** | No billing or subscription UI; static “$10/month” text may exist. | For tiers/billing focus: optional. Can add later: show current plan (unit count, Shield count), next invoice, or link to Stripe Customer Portal. |

---

## 4. Summary: what to build and where

- **New:** `app/services/billing.py` – onboarding fee tier calculation, Stripe customer creation, one-time onboarding charge, subscription create/update, `sync_subscription_quantities(owner_profile_id)`.
- **New (optional):** `app/routers/billing.py` – webhooks (e.g. `invoice.paid`), or read-only “billing status” for frontend.
- **Model:** Add to OwnerProfile (or equivalent): `stripe_customer_id`, `stripe_subscription_id`, `onboarding_billing_completed_at`, `onboarding_billing_unit_count`.
- **Hooks:** From `app/routers/owners.py` (add_property, bulk_upload_properties): on first property batch, call billing onboarding; on every add/remove, call quantity sync. From property PATCH and any code that sets/clears `shield_mode_enabled`: call Shield quantity sync.
- **Config:** Reuse existing Stripe keys in `app/config.py` for billing unless product requires a separate Stripe account.

---

## 5. Assumptions

- 1 Property = 1 unit for all pricing.
- “Onboarding completion” for billing = first time owner has at least one property (first add or first bulk upload); product may refine to “first bulk only” or “first time total units ≥ 1.”
- Existing account onboarding (identity + POA) is unchanged and still required before adding properties; billing onboarding is a separate event that fires when they first add properties.
- All proration and quantity updates are state-driven from DB (property count, `shield_mode_enabled`); no manual billing overrides in scope.
