# How to Add Stripe in Test Mode

Use **Stripe Test Mode** so no real charges are made. All API calls use test keys and test data.

---

## 1. Get your test API keys

1. Log in to [Stripe Dashboard](https://dashboard.stripe.com).
2. **Turn on Test mode** using the toggle in the top-right (it should say "Test mode" when on).
3. Go to **Developers → API keys**.
4. Copy:
   - **Publishable key** (starts with `pk_test_...`)
   - **Secret key** (starts with `sk_test_...`); click "Reveal" if needed.

---

## 2. Set keys in your app

Add or update your `.env` (project root):

```env
# Stripe (test mode – use pk_test_ and sk_test_ keys from Dashboard → Developers → API keys)
STRIPE_SECRET_KEY=sk_test_...   # paste your Secret key here (never commit real keys)
STRIPE_PUBLISHABLE_KEY=pk_test_...
```

The app already uses these for **Stripe Identity** (KYC). The same keys are used for **billing** (onboarding fee). No extra config is required.

Optional (only if you use Identity flows):

```env
STRIPE_IDENTITY_FLOW_ID=
STRIPE_IDENTITY_RETURN_URL=http://localhost:3000/onboarding/identity-complete
```

---

## 3. Restart the backend

Restart the FastAPI server so it loads the new env vars.

---

## 4. Test the onboarding fee

1. Complete owner signup and link the Master POA (so you can add properties).
2. Add **one property** (single add or bulk upload).
3. Backend will:
   - Create a Stripe **Customer** (test) for the owner.
   - Create an **Invoice** for the onboarding fee (1–5 units → $299).
   - Finalize the invoice.
4. With **charge_automatically**, Stripe will try to charge the customer’s default payment method. New test customers have none, so the invoice stays **open** and you get a **hosted invoice URL** (returned from the billing service; you can expose it via an endpoint or log it for testing).
5. To simulate payment in test mode:
   - **Option A:** Add a test card to the customer in Dashboard (Customers → your test customer → Add payment method) and use test card `4242 4242 4242 4242`, then pay the open invoice.
   - **Option B:** Use [Stripe test cards](https://docs.stripe.com/testing#cards) (e.g. `4242 4242 4242 4242`) when your app has a “Add payment method” or checkout flow.

---

## 5. Verify in Stripe Dashboard (test mode)

- **Customers:** New test customer for the owner.
- **Invoices:** One “DocuStay onboarding fee (N unit(s))” invoice; status Open or Paid.
- **Payments:** If the invoice was paid, it appears under Payments.

---

## 6. (Optional) Webhook for payment logs

To record **Invoice paid** in the owner audit log (Logs tab):

1. In Stripe Dashboard → **Developers → Webhooks** → Add endpoint.
2. URL: `https://your-backend-url/webhooks/stripe` (e.g. `https://api.docustay.example.com/webhooks/stripe`).
3. Select event **invoice.paid**.
4. Copy the **Signing secret** (`whsec_...`) and set in `.env`: `STRIPE_WEBHOOK_SECRET=whsec_...`.
5. Restart the backend. When a customer pays an invoice, Stripe sends the event and the app logs "Invoice paid" under the Billing category in Logs.

---

## 7. Switching to live mode

When you go live:

1. In Dashboard, turn **off** Test mode.
2. Get **live** keys from **Developers → API keys** (`pk_live_...`, `sk_live_...`).
3. Replace `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY` in production `.env` with the live keys.
4. Never commit live keys to the repo; use env vars or a secrets manager.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Dashboard → Test mode ON → Developers → API keys |
| 2 | Set `STRIPE_SECRET_KEY=sk_test_...` and `STRIPE_PUBLISHABLE_KEY=pk_test_...` in `.env` |
| 3 | Restart backend |
| 4 | Add a property as an owner to trigger onboarding invoice (test) |
| 5 | (Optional) Add webhook endpoint for invoice.paid and set `STRIPE_WEBHOOK_SECRET` to log payments in Logs |
