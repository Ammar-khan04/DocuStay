# DocuStay


FastAPI + PostgreSQL backend with a **Vite + React** frontend. Implements Auth (owner & guest registration), Owner/Guest Onboarding, Properties, Invitations, Stays, Region Rules, JLE, Dashboard, Stay Timer, and Notifications.

## Prerequisites

- **Python 3.10+** (backend)
- **Node.js 18+** (frontend)
- **PostgreSQL** (for backend database)

## Setup

### 1. Backend

1. **Virtual environment** (recommended):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # macOS/Linux
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment**: Create a `.env` file in the project root and set:
   - `DATABASE_URL` – PostgreSQL connection (e.g. `postgresql://postgres:postgres@localhost:5432/docustay_demo`)
   - `JWT_SECRET_KEY` – a long random string for JWT signing (min 32 chars)
   - `JWT_ALGORITHM` – e.g. `HS256`
   - `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` – e.g. `60`

   **Email (optional)**:
   - **Mailgun** (preferred): `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_FROM_EMAIL`, `MAILGUN_FROM_NAME`
   - **SendGrid** (fallback): `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `SENDGRID_FROM_NAME`

4. **Database**: Create the database in PostgreSQL (e.g. `docustay_demo`). Tables and region rules are created automatically on backend startup. The schema is defined in `app/models/`; `Base.metadata.create_all()` runs on startup. For fresh databases, all schema is in the models; no migration scripts are required.

5. **Test users (when verification email is not configured)**  
   If you are not using Mailgun/SendGrid, verification emails will not be sent and you cannot complete signup via the UI. Create an owner and a guest user directly in the database:

   ```bash
   python scripts/create_test_users.py
   ```

   This creates:
   - **Owner**: `owner@docustay.demo` / `Password123!` — use **Owner Login** (or Login page).
   - **Guest**: `guest@docustay.demo` / `Password123!` — use **Guest Login** page.

   The script is idempotent: running it again skips users that already exist and prints the same credentials.

### 2. Frontend

1. **Install dependencies** (from project root):
   ```bash
   cd frontend
   npm install
   ```

2. **Env** (optional): Copy `frontend/.env.example` to `frontend/.env`. For local dev the app uses `/api` (proxied by Vite to the backend). For production build see [Frontend production build](#frontend-production-build) below.

## Run the app

Run **backend** and **frontend** in two terminals.

### Terminal 1 – Backend

From the **project root** (with venv activated):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- API: http://127.0.0.1:8000  
- API docs: http://127.0.0.1:8000/docs  

### Terminal 2 – Frontend

From the **project root**:

```bash
cd frontend
npm run dev
```

- App: http://localhost:3000  

### Frontend production build

When deploying, build the frontend and serve the `frontend/dist` folder (e.g. with nginx). So that Vite doesn’t cause issues:

1. **Create `frontend/.env.production`** (or set env when running `npm run build`) with values that match your backend and server:
   - **`VITE_APP_ORIGIN`** – same as backend `FRONTEND_BASE_URL` / `STRIPE_IDENTITY_RETURN_URL` origin (no trailing slash). Example: `http://13.58.166.68` or `https://your-domain.com`.
   - **`VITE_API_URL`** – use `/api` if the same server proxies `/api` to the backend (recommended). Only use a full URL if the API is on a different host.

2. **Build**: From `frontend/`, run `npm run build`. The built app will use these values; if they’re unset, it falls back to `/api` and `window.location.origin`, which is fine when the app is served from the same host that proxies `/api` to the backend.

3. **Backend .env**: Ensure `FRONTEND_BASE_URL` and `STRIPE_IDENTITY_RETURN_URL` are set to your app URL (e.g. `http://13.58.166.68`).

### Quick test

1. Open http://localhost:3000  
2. **Register as owner**: Get Started → Create Owner Account (full name, email, phone, password, state, city, terms).  
3. **Verify**: Enter demo code `123456` on the verify step.  
4. **Owner flow**: Add a property, then invite a guest (invitation link is shown in an alert).  
5. **Guest flow**: Open the invite link (e.g. `#invite/INV-...`), register as guest with permanent address and acknowledgments, then verify with `123456`.  

## Scripts

From the **project root** (with venv activated):

| Script | Purpose |
|--------|---------|
| `python scripts/create_test_users.py` | Create an owner and a guest user (no email verification). Use when Mailgun/SendGrid is not set up. See [Test users](#5-test-users-when-verification-email-is-not-configured) above. |
| `python scripts/delete_pending_invitations.py` | Delete all invitations in pending state from the database. |
| `python scripts/seed_region_rules.py` | Create tables and seed region rules (NYC, FL, CA, TX). |
| `python scripts/test_api.py` | Run backend API tests. |

## API overview

| Module | Prefix | Description |
|--------|--------|-------------|
| A – Auth | `/auth` | Register owner, Register guest (from invite), Login, GET /me |
| B1 – Owners | `/owners` | List/add properties; POST /invitations (guest invite) |
| B2 – Guests | `/guests` | GET/PUT profile (full_legal_name, permanent_home_address, gps_ack) |
| C – Stays | `/stays` | Create stay, list, get |
| D – Region rules | `/region-rules` | List/get region rules (NYC, FL, CA, TX) |
| E – JLE | `/jle/resolve` | POST → legal classification, max days, compliance |
| F – Dashboard | `/dashboard/owner/stays`, `/dashboard/guest/stays` | Owner/guest stay views |
| G – Stay timer | (cron / `POST /notifications/run-stay-warnings`) | Legal warning emails |
| H – Notifications | (internal) | SendGrid email; optional Twilio SMS |

## Audit log (append-only)

DocuStay keeps an **immutable audit trail** (Rule 803(6)): every status change, guest signature, and failed attempt is logged and cannot be edited or deleted. Owners view logs in the dashboard under **Logs** (filter by time, category, search). Logs are written in `app/services/audit_log.py` via `create_log()` and stored in the `audit_logs` table.

### When logs are created and saved

#### 1. Stays (`app/routers/stays.py`)

| When | Category | Title |
|------|----------|--------|
| After a stay is successfully created (POST `/stays/`) | status_change | Stay created |

#### 2. Dashboard (`app/routers/dashboard.py`)

| When | Category | Title |
|------|----------|--------|
| Guest adds pending invite with **invalid or expired** invitation code (POST `/dashboard/guest/pending-invites`) | failed_attempt | Invalid or expired invitation code |
| Owner revokes a stay (POST `/dashboard/owner/stays/{stay_id}/revoke`) | status_change | Stay revoked |
| Guest checks out / ends stay (POST `/dashboard/guest/stays/{stay_id}/end`) | status_change | Guest checked out |
| Guest cancels a future stay (POST `/dashboard/guest/stays/{stay_id}/cancel`) | status_change | Stay cancelled by guest |

#### 2b. Stay timer / overstay (`app/services/stay_timer.py`)

| When | Category | Title |
|------|----------|--------|
| Overstay detected (daily job): stay end date passed, guest has not checked out or cancelled; emails sent to owner and guest | status_change | Overstay occurred |

#### 3. Agreements (`app/routers/agreements.py`)

| When | Category | Title |
|------|----------|--------|
| Sign attempt with **invalid or expired** invitation code (POST `/agreements/sign`) | failed_attempt | Agreement sign: invalid or expired invitation |
| Sign attempt with **document hash mismatch** (POST `/agreements/sign`) | failed_attempt | Agreement sign: document hash mismatch |
| Guest **successfully** signs agreement – typed (POST `/agreements/sign`) | guest_signature | Agreement signed |
| Sign attempt with **invalid or expired** invitation code (POST `/agreements/sign-with-dropbox`) | failed_attempt | Agreement sign (Dropbox): invalid or expired invitation |
| Sign attempt with **document hash mismatch** (POST `/agreements/sign-with-dropbox`) | failed_attempt | Agreement sign (Dropbox): document hash mismatch |
| Guest **successfully** signs via Dropbox Sign (POST `/agreements/sign-with-dropbox`) | guest_signature | Agreement signed (Dropbox Sign) |

#### 4. Auth (`app/routers/auth.py`)

| When | Category | Title |
|------|----------|--------|
| **Login failed** – wrong email or password (POST `/auth/login`) | failed_attempt | Login failed |
| **Email verification failed** – invalid or wrong code (POST `/auth/verify-email`) | failed_attempt | Email verification failed |
| **Email verification failed** – expired code (POST `/auth/verify-email`) | failed_attempt | Email verification failed |
| Guest **register** with **invalid or expired** invitation code (POST `/auth/register/guest`) | failed_attempt | Guest register: invalid or expired invitation code |
| Guest **registers and accepts** invitation (stay created) (POST `/auth/register/guest`) | status_change | Invitation accepted (stay created) |
| **Accept invite**: invalid or expired invitation code (POST `/auth/accept-invite`) | failed_attempt | Accept invite: invalid or expired invitation code |
| **Accept invite**: missing or invalid signature (POST `/auth/accept-invite`) | failed_attempt | Accept invite: missing or invalid signature |
| **Accept invite**: signature does not match invitation (POST `/auth/accept-invite`) | failed_attempt | Accept invite: signature does not match invitation |
| **Accept invite**: signature email does not match current user (POST `/auth/accept-invite`) | failed_attempt | Accept invite: signature email does not match |
| **Accept invite**: signature already used (POST `/auth/accept-invite`) | failed_attempt | Accept invite: signature already used |
| **Accept invite**: not all acknowledgments accepted (POST `/auth/accept-invite`) | failed_attempt | Accept invite: not all acknowledgments accepted |
| **Existing guest** accepts invitation (stay created) (POST `/auth/accept-invite`) | status_change | Invitation accepted |

#### 5. Owners (`app/routers/owners.py`)

| When | Category | Title |
|------|----------|--------|
| Owner **creates an invitation** (POST `/owners/invitations`) | status_change | Invitation created |
| Owner **updates property info** (PUT `/owners/properties/{property_id}`) | status_change | Property updated |
| Owner **deletes a property** (DELETE `/owners/properties/{property_id}`) | status_change | Property deleted |
| Owner **cancels a pending invitation** (POST `/dashboard/owner/invitations/{id}/cancel`) | status_change | Invitation cancelled |

### Summary by category

- **Status change (12):** Stay created, Stay revoked, Guest checked out, Stay cancelled by guest, **Overstay occurred**, Invitation created, Invitation accepted (new guest), Invitation accepted (existing guest), **Property updated**, **Property deleted**, **Invitation cancelled**.
- **Guest signature (2):** Agreement signed (typed), Agreement signed (Dropbox Sign).
- **Failed attempt (14):** Login failed; Email verification failed (×2); invalid/expired invite on register and accept; agreement sign failures (invalid invite, hash mismatch ×2); accept-invite failures (invalid code, bad signature, mismatches, already used, incomplete acks).

---

## Property occupancy status state machine

Every property has an `occupancy_status` that reflects the unit's current state. The dashboard displays one of four states at all times.

### States

| State | Description |
|-------|-------------|
| **VACANT** | Owner confirmed the unit is empty (e.g. guest checked out or owner confirmed "Unit Vacated"). |
| **OCCUPIED** | Unit has an active guest stay, or owner confirmed "Lease Renewed" or "Holdover". |
| **UNKNOWN** | Only after **Status Confirmation** (stay end reminders): lease ended, no owner confirmation (or follow-on unconfirmed path). Not a default—new/empty units are **VACANT**. |
| **UNCONFIRMED** | The system asked for confirmation (Status Confirmation) and received **no response** by the deadline. Recorded silence is forensic evidence. |

### Transitions

| From | To | Condition |
|------|-----|-----------|
| (any) | **OCCUPIED** | Guest accepts an invitation and a stay is created. |
| (any) | **OCCUPIED** | Owner explicitly confirms **Lease Renewed** (with new lease end date) or **Holdover**. |
| OCCUPIED | **VACANT** | Guest checks out (ends stay), or owner confirms **Unit Vacated**. |
| (any) | **UNCONFIRMED** | Status Confirmation: 48 hours **after** lease end date with no owner action. The system flips to UNCONFIRMED instead of leaving the old label. |
| UNCONFIRMED | VACANT / OCCUPIED | **Only** when an authenticated owner explicitly confirms (Unit Vacated, Lease Renewed, or Holdover). No automatic reversion. |

<!-- Former heading: ### Dead Man's Switch confirmation flow -->
### Status Confirmation (stay end reminders) flow

1. **48 hours before** lease end: First confirmation prompt (email to owner).  
2. **Lease end date**: No automatic status change.  
3. **48 hours after** lease end: If owner has not responded, status flips to **UNCONFIRMED** (logged; Shield Mode activated).  

The owner must choose one of:

- **Unit Vacated** → status becomes VACANT  
- **Lease Renewed** → new lease end date required; status stays OCCUPIED  
- **Holdover** → guest still in unit without formal renewal; status stays OCCUPIED  

If no selection is made before the deadline, the system transitions to UNCONFIRMED. That transition is logged; verified identity, timestamp, and previous/new status are recorded for all explicit confirmations.

---

## Module flow

1. **Owner**: Register → verify (demo code `123456`) → add **properties** → create **invitations** (guest gets link).  
2. **Guest**: Open invite link → register with permanent address & acknowledgments → verify → guest dashboard.  
3. **Stays**: Create stays (property, dates, purpose, relationship); JLE enforces max stay days per region.  
4. **Dashboard**: Owner sees stays and legal classification; guest sees approved stays and legal notice.  
5. **Notifications**: Optional cron or `POST /notifications/run-stay-warnings` for legal warning emails near stay limits.
