/**
 * DocuStay backend API client.
 * Replaces Gemini service for auth, properties, and invitations.
 * All URLs from .env; no hardcoded localhost (set VITE_API_URL and VITE_APP_ORIGIN in .env for deployment).
 */
import { toUserFriendlyInvitationError } from "../utils/invitationErrors";

export const API_URL = (import.meta as any).env?.VITE_API_URL ?? (typeof window !== "undefined" ? "/api" : "");
/** Frontend app origin for Stripe return_url, invite links, etc. From .env VITE_APP_ORIGIN, or window.location.origin in browser. */
export const APP_ORIGIN =
  (import.meta as any).env?.VITE_APP_ORIGIN ?? (typeof window !== "undefined" ? window.location.origin : "");

/** sessionStorage: pending property ownership transfer token until accept (signup → onboarding → dashboard). */
export const DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY = "docustay_owner_transfer_token";

/**
 * Public invite URL (`#invite/CODE` for InviteLanding). Uses `/#invite/...` with no dashboard pathname
 * so links work when copied from any route and match `VITE_APP_ORIGIN` when set.
 */
export function buildGuestInviteUrl(invitationCode: string, opts?: { isDemo?: boolean }): string {
  const code = (invitationCode || "").trim();
  if (!code) return "";
  const base = (APP_ORIGIN || (typeof window !== "undefined" ? window.location.origin : "")).replace(/\/$/, "");
  const path = opts?.isDemo ? `demo/invite/${code}` : `invite/${code}`;
  return `${base}/#${path}`;
}

/**
 * Backend often returns root-relative paths (e.g. `/public/live/{slug}/poa` for PDFs). Opening those on the SPA
 * origin loads the React shell instead of the API document — prefix with `API_URL` (same as `#check` verify links).
 */
/** Public PDF URL: unsigned guest agreement snapshot for demo-originated invites. */
export function demoStoredUnsignedGuestAgreementPdfUrl(invitationCode: string): string {
  const code = (invitationCode || "").trim().toUpperCase();
  const base = String(API_URL || "").replace(/\/$/, "");
  return `${base}/agreements/invitation/${encodeURIComponent(code)}/demo-stored-unsigned-pdf`;
}

/** Authenticated demo owners: unsigned Master POA PDF (Bearer required — open via fetch+blob). */
export function demoUnsignedPoaPdfRequestPath(): string {
  return "/agreements/demo/unsigned-poa";
}

export function resolveBackendMediaUrl(pathOrUrl: string): string {
  const s = (pathOrUrl || "").trim();
  if (!s) return s;
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith("//") && typeof window !== "undefined") {
    return `${window.location.protocol}${s}`;
  }
  if (!s.startsWith("/")) return s;
  const base = String(API_URL || "").replace(/\/$/, "");
  return `${base}${s}`;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("docustay_token");
}

/** Browser local calendar date YYYY-MM-DD (matches `<input type="date">` / getTodayLocal). */
function getClientCalendarDateYmd(): string {
  if (typeof window === "undefined") return "";
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Request header — some proxies strip custom headers; pair with {@link clientCalendarDateBody} on invite POSTs. */
function clientCalendarDateHeaders(): Record<string, string> {
  const ymd = getClientCalendarDateYmd();
  if (!ymd) return {};
  return { "X-Client-Calendar-Date": ymd };
}

/** JSON field so invite date validation still sees local "today" when X-Client-Calendar-Date is stripped upstream. */
function clientCalendarDateBody(): { client_calendar_date: string } {
  return { client_calendar_date: getClientCalendarDateYmd() };
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem("docustay_token", token);
  else localStorage.removeItem("docustay_token");
}

const CONTEXT_MODE_KEY = "docustay_context_mode";

/** Business: property management scope. Personal: own residence. Privacy rules apply in both — switching modes does NOT unlock tenant-private data. */
export function getContextMode(): "business" | "personal" {
  if (typeof window === "undefined") return "business";
  const m = (localStorage.getItem(CONTEXT_MODE_KEY) || "").toLowerCase();
  return m === "personal" ? "personal" : "business";
}

export function setContextMode(mode: "business" | "personal") {
  if (typeof window === "undefined") return;
  localStorage.setItem(CONTEXT_MODE_KEY, mode);
}

/** Custom event fired when properties are added/edited/bulk-uploaded. OwnerDashboard listens to refetch personal mode units. */
const PROPERTIES_CHANGED_EVENT = "docustay:properties-changed";

export function emitPropertiesChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(PROPERTIES_CHANGED_EVENT));
}

export function onPropertiesChanged(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(PROPERTIES_CHANGED_EVENT, callback);
  return () => window.removeEventListener(PROPERTIES_CHANGED_EVENT, callback);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const contextMode = getContextMode();
  if (contextMode) (headers as Record<string, string>)["X-Context-Mode"] = contextMode;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch (e) {
    const msg = (e as Error)?.message ?? "";
    if (msg === "Failed to fetch" || msg.includes("fetch") || msg.includes("NetworkError")) {
      throw new Error("The server is unavailable. Please try again later.");
    }
    throw e;
  }
  if (res.status === 401) {
    const text = await res.text();
    let detail = "";
    try {
      const j = JSON.parse(text);
      detail = (Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail ?? "")) || "";
    } catch {
      detail = text || "";
    }
    const isLoginRequest = path === "/auth/login";
    const isOnboardingPage =
      typeof window !== "undefined" &&
      (window.location.hash.includes("onboarding/identity") ||
        window.location.hash.includes("onboarding/poa") ||
        window.location.hash.includes("onboarding/identity-complete") ||
        window.location.pathname.includes("onboarding/identity") ||
        window.location.pathname.includes("onboarding/poa"));
    const isManagerInviteSignup =
      typeof window !== "undefined" &&
      (window.location.hash.includes("register/manager") || window.location.pathname.includes("register/manager"));
    const isOwnerPropertyTransferFlow =
      typeof window !== "undefined" &&
      (window.location.hash.includes("property-transfer/") ||
        window.location.hash.includes("register/owner-transfer/") ||
        window.location.hash.includes("login/owner-transfer/") ||
        window.location.hash.includes("demo/property-transfer/"));
    if (!isLoginRequest && typeof window !== "undefined" && !isOnboardingPage && !isManagerInviteSignup && !isOwnerPropertyTransferFlow) {
      setToken(null);
      window.location.hash = "login";
      window.location.reload();
    }
    if (isLoginRequest) {
      throw new Error(detail || "Invalid email or password.");
    }
    // 401 on pending-owner: "try logging in" only for complete-signup (account may exist); otherwise "start over"
    if (path.includes("/auth/pending-owner/")) {
      const d = (detail || "").toLowerCase();
      const isCompleteSignup = path.includes("complete-signup");
      if ((d.includes("signup session not found") || d.includes("session not found")) && isCompleteSignup) {
        throw new Error("Your account may already be created. Try logging in with your email and password.");
      }
      if (d.includes("signup session not found") || d.includes("session not found")) {
        throw new Error("Your signup session was lost. Please start over from registration.");
      }
      if (d.includes("expired") || d.includes("invalid or expired")) {
        throw new Error("Your signup session expired. Please start over from registration or try logging in if you already completed signup.");
      }
      if (d.includes("not authenticated")) {
        throw new Error("Your session was lost. Please start over from registration.");
      }
      throw new Error(detail || "Something went wrong. Please start over from registration.");
    }
    throw new Error(detail || "Session expired. Please log in again.");
  }
  if (!res.ok) {
    const text = await res.text();
    let detail: string | object = text;
    try {
      const j = JSON.parse(text);
      detail = Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail ?? text);
    } catch {
      // use text as-is
    }
    const detailStr = typeof detail === "object" && detail !== null && "detail" in (detail as object)
      ? String((detail as { detail?: string }).detail ?? text)
      : String(detail);
    if (res.status === 403 && typeof window !== "undefined") {
      const d = detailStr.toLowerCase();
      if (d.includes("identity verification")) window.location.hash = "onboarding/identity";
      else if (d.includes("master poa") || d.includes("poa")) window.location.hash = "onboarding/poa";
    }
    const err = new Error(detailStr) as Error & { errorCode?: string; sessionId?: string };
    if (typeof detail === "object" && detail !== null && "error_code" in (detail as object)) {
      err.errorCode = (detail as { error_code?: string }).error_code;
    }
    if (typeof detail === "object" && detail !== null && "session_id" in (detail as object)) {
      err.sessionId = (detail as { session_id?: string }).session_id;
    }
    throw err;
  }
  if (res.status === 204 || res.headers.get("content-length") === "0") return undefined as T;
  return res.json() as Promise<T>;
}

// --- Auth (match reference app expected shapes) ---
export type UserType = "PROPERTY_OWNER" | "PROPERTY_MANAGER" | "TENANT" | "GUEST" | "ADMIN";
export type AccountStatus = "PENDING_VERIFICATION" | "ACTIVE" | "FULLY_VERIFIED";

export interface UserSession {
  user_id: string;
  user_type: UserType;
  user_name: string;
  email: string;
  account_status: AccountStatus;
  token: string;
  identity_verified?: boolean;
  poa_linked?: boolean;
  is_demo?: boolean;
}

interface BackendUser {
  id: number;
  email: string;
  role: "owner" | "property_manager" | "tenant" | "guest" | "admin";
  full_name?: string | null;
  phone?: string | null;
  state?: string | null;
  city?: string | null;
  identity_verified?: boolean;
  poa_linked?: boolean;
  is_demo?: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: BackendUser;
}

export function toUserSession(t: TokenResponse): UserSession {
  const u = t.user;
  const user_type: UserType =
    u.role === "owner" ? "PROPERTY_OWNER"
    : u.role === "property_manager" ? "PROPERTY_MANAGER"
    : u.role === "tenant" ? "TENANT"
    : u.role === "admin" ? "ADMIN"
    : "GUEST";
  return {
    user_id: String(u.id),
    user_type,
    user_name: u.full_name || u.email,
    email: u.email,
    account_status: "ACTIVE",
    token: t.access_token,
    identity_verified: u.identity_verified ?? false,
    poa_linked: u.poa_linked ?? false,
    is_demo: u.is_demo ?? false,
  };
}

export const authApi = {
  async demoLogin(data: { role: "owner" | "property_manager" | "tenant" | "guest"; email?: string }): Promise<{ status: string; data: UserSession }> {
    const body = await request<TokenResponse>("/auth/demo/login", {
      method: "POST",
      body: JSON.stringify({ role: data.role, email: data.email ?? null, ...clientCalendarDateBody() }),
      headers: clientCalendarDateHeaders(),
    });
    setToken(body.access_token);
    return { status: "success", data: toUserSession(body) };
  },
  async login(
    email: string,
    password: string,
    role?: "owner" | "property_manager" | "tenant" | "guest" | "admin",
  ): Promise<{ status: string; data: UserSession; message?: string }> {
    const body = await request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, role: role ?? null, ...clientCalendarDateBody() }),
      headers: clientCalendarDateHeaders(),
    });
    setToken(body.access_token);
    return { status: "success", data: toUserSession(body) };
  },
  async register(data: {
    account_type?: 'individual';
    first_name?: string;
    last_name?: string;
    full_name: string;
    email: string;
    phone: string;
    password: string;
    confirm_password: string;
    country: string;
    state: string;
    city: string;
    terms_agreed: boolean;
    privacy_agreed: boolean;
    poa_signature_id?: number | null;
  }): Promise<{
    status: string;
    data?: { user_id: string } | UserSession;
    skipVerification?: boolean;
    message?: string;
    validation?: Record<string, { error?: string }>;
  }> {
    try {
      const body = await request<{ user_id?: number; message?: string } & Partial<TokenResponse>>("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          account_type: data.account_type ?? "individual",
          first_name: data.first_name,
          last_name: data.last_name,
          full_name: data.full_name,
          email: data.email,
          phone: data.phone,
          password: data.password,
          confirm_password: data.confirm_password,
          country: data.country,
          state: data.state,
          city: data.city,
          terms_agreed: data.terms_agreed,
          privacy_agreed: data.privacy_agreed,
          role: "owner",
          poa_signature_id: data.poa_signature_id ?? undefined,
        }),
      });
      if (body.access_token && body.user) {
        setToken(body.access_token);
        return {
          status: "success",
          data: toUserSession(body as TokenResponse),
          skipVerification: true,
        };
      }
      return {
        status: "success",
        data: { user_id: String(body.user_id!) },
      };
    } catch (e: any) {
      const msg = (e?.message && String(e.message).trim()) || "Registration failed. Please try again.";
      const validation: Record<string, { error: string }> = {};
      if (msg.includes("Passwords")) validation.password_match = { error: "Passwords do not match" };
      if (msg.includes("agree")) {
        validation.terms = { error: "You must agree to the Terms of Service" };
        validation.privacy = { error: "You must agree to the Privacy Policy" };
      }
      if (msg.includes("property owner")) validation.email = { error: "This email is already registered as a property owner. Please log in on the Owner Login page." };
      else if (msg.includes("already registered")) validation.email = { error: "Email already registered" };
      if (msg.toLowerCase().includes("phone") || msg.includes("digits")) validation.phone = { error: msg };
      return { status: "error", message: msg, validation };
    }
  },
  logout() {
    setToken(null);
  },
  getToken,
  /** Request password reset email. Role identifies owner vs guest when same email has both accounts. */
  async forgotPassword(email: string, role: "owner" | "guest"): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email: email.trim().toLowerCase(), role }),
    });
    return { status: (res as any)?.status || "ok", message: (res as any)?.message };
  },
  /** Set new password using token from reset email. */
  async resetPassword(token: string, new_password: string, confirm_password: string): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password, confirm_password }),
    });
    return { status: (res as any)?.status || "ok", message: (res as any)?.message };
  },
  /** Accept an invitation as an existing guest/tenant (requires guest or tenant token). */
  async acceptInvite(invitationCode: string, agreementSignatureId?: number | null): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/accept-invite", {
      method: "POST",
      body: JSON.stringify({
        invitation_code: invitationCode.trim().toUpperCase(),
        agreement_signature_id: agreementSignatureId ?? null,
      }),
    });
    return { status: (res as any)?.status || "success", message: (res as any)?.message };
  },
  /** Verify email with code sent after registration. Returns token and sets it. */
  async verifyEmail(userId: string, code: string): Promise<{ status: string; data?: UserSession; message?: string }> {
    try {
      const body = await request<TokenResponse>("/auth/verify-email", {
        method: "POST",
        body: JSON.stringify({ user_id: Number(userId), code: code.trim() }),
      });
      setToken(body.access_token);
      return { status: "success", data: toUserSession(body) };
    } catch (e: any) {
      return { status: "error", message: e?.message ?? "Verification failed" };
    }
  },

  /** Get manager invite details for pre-filling signup form. `already_accepted` when signup finished — use login, not "expired". */
  async getManagerInvite(
    token: string,
  ): Promise<{ email: string; property_name: string; property_id: number; is_demo?: boolean; already_accepted?: boolean }> {
    return request<{
      email: string;
      property_name: string;
      property_id: number;
      is_demo?: boolean;
      already_accepted?: boolean;
    }>(`/auth/manager-invite/${encodeURIComponent(token)}`);
  },
  /** Property manager signup via invite link. */
  async registerManager(data: { invite_token: string; full_name: string; email: string; phone: string; password: string; confirm_password: string }): Promise<{ status: string; data: UserSession; message?: string }> {
    const body = await request<TokenResponse>("/auth/register/manager", {
      method: "POST",
      body: JSON.stringify(data),
    });
    setToken(body.access_token);
    return { status: "success", data: toUserSession(body) };
  },
  /** Accept a manager invitation as an already-logged-in property manager. Requires auth. */
  acceptManagerInvite: (token: string) =>
    request<{ status: string; message?: string }>(`/auth/accept-manager-invite/${encodeURIComponent(token)}`, { method: "POST" }),
  async getPropertyTransferInvite(
    token: string,
  ): Promise<{ email: string; property_name: string; property_id: number; is_demo?: boolean; already_accepted?: boolean }> {
    return request<{
      email: string;
      property_name: string;
      property_id: number;
      is_demo?: boolean;
      already_accepted?: boolean;
    }>(`/auth/property-transfer-invite/${encodeURIComponent(token)}`);
  },
  /** Resend verification code to the user's email. */
  async resendVerification(userId: string): Promise<{ status: string; message?: string }> {
    try {
      await request<{ status?: string; message?: string }>("/auth/resend-verification", {
        method: "POST",
        body: JSON.stringify({ user_id: Number(userId) }),
      });
      return { status: "success", message: "Verification code sent. Check your email." };
    } catch (e: any) {
      return { status: "error", message: e?.message ?? "Failed to resend" };
    }
  },

  /** Get current user (requires token). Used after verify step. */
  async me(): Promise<UserSession | null> {
    try {
      const body = await request<BackendUser>("/auth/me");
      const token = getToken();
      if (!token) return null;
      const user_type: UserType =
        body.role === "owner" ? "PROPERTY_OWNER"
        : body.role === "property_manager" ? "PROPERTY_MANAGER"
        : body.role === "tenant" ? "TENANT"
        : body.role === "admin" ? "ADMIN"
        : "GUEST";
      return {
        user_id: String(body.id),
        user_type,
        user_name: body.full_name || body.email,
        email: body.email,
        account_status: "ACTIVE",
        token,
        identity_verified: body.identity_verified ?? false,
        poa_linked: body.poa_linked ?? false,
      };
    } catch {
      return null;
    }
  },

  /** Link Master POA signature to current owner (after identity verification). Set authorizedAgentCertified true when user is Authorized Agent. */
  async linkOwnerPoa(poaSignatureId: number, authorizedAgentCertified = false): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/owner/link-poa", {
      method: "POST",
      body: JSON.stringify({ poa_signature_id: poaSignatureId, authorized_agent_certified: authorizedAgentCertified }),
    });
    return { status: (res as any)?.status ?? "ok", message: (res as any)?.message };
  },
};

// --- Identity verification (Stripe Identity for owner onboarding) ---
export const identityApi = {
  /** Create a verification session (for existing owner user); returns URL to redirect to Stripe Identity. */
  async createVerificationSession(): Promise<{ client_secret: string; url?: string | null }> {
    return request<{ client_secret: string; url?: string | null }>("/auth/identity/verification-session", {
      method: "POST",
    });
  },
  /** Confirm identity after return from Stripe (for existing owner user). */
  async confirmIdentity(verificationSessionId: string): Promise<{ status?: string; message?: string }> {
    return request<{ status?: string; message?: string }>("/auth/identity/confirm", {
      method: "POST",
      body: JSON.stringify({ verification_session_id: verificationSessionId }),
    });
  },
  /** Get the verification_session_id we stored when creating the session. Use when Stripe redirect omits session_id in URL (manager/owner flow). */
  async getLatestIdentitySession(): Promise<{ verification_session_id: string }> {
    return request<{ verification_session_id: string }>("/auth/identity/latest-session");
  },
};

// --- Pending owner signup flow (after email verify, before user exists in DB) ---
export const pendingOwnerApi = {
  /** Create Stripe Identity session for pending owner. Return URL includes pending_id. */
  async createIdentitySession(): Promise<{ client_secret: string; url?: string | null }> {
    return request<{ client_secret: string; url?: string | null }>("/auth/pending-owner/identity-session", {
      method: "POST",
    });
  },
  /** Confirm identity after Stripe redirect (updates pending record). */
  async confirmIdentity(verificationSessionId: string): Promise<{ status?: string; message?: string }> {
    return request<{ status?: string; message?: string }>("/auth/pending-owner/confirm-identity", {
      method: "POST",
      body: JSON.stringify({ verification_session_id: verificationSessionId }),
    });
  },
  /** Get the verification_session_id we stored when creating the session. Use when Stripe redirect omits session_id in URL. */
  async getLatestIdentitySession(): Promise<{ verification_session_id: string }> {
    return request<{ verification_session_id: string }>("/auth/pending-owner/latest-identity-session");
  },
  /** Get a fresh Stripe Identity URL to retry verification (same session). Returns url for requires_input; already_verified if done. */
  async getIdentityRetryUrl(verificationSessionId: string): Promise<{ url?: string | null; already_verified?: boolean; message?: string }> {
    return request<{ url?: string | null; already_verified?: boolean; message?: string }>("/auth/pending-owner/identity-retry", {
      method: "POST",
      body: JSON.stringify({ verification_session_id: verificationSessionId }),
    });
  },
  /** Get email/full_name/address/account_type for POA modal. */
  async me(): Promise<{ email: string; full_name: string | null; city: string | null; state: string | null; country: string | null; account_type: string | null }> {
    return request<{ email: string; full_name: string | null; city: string | null; state: string | null; country: string | null; account_type: string | null }>("/auth/pending-owner/me");
  },
  /** Create user, link POA, delete pending; returns token + user. */
  async completeSignup(poaSignatureId: number): Promise<{ access_token: string; token_type: string; user: BackendUser }> {
    return request<{ access_token: string; token_type: string; user: BackendUser }>("/auth/pending-owner/complete-signup", {
      method: "POST",
      headers: clientCalendarDateHeaders(),
      body: JSON.stringify({ poa_signature_id: poaSignatureId, ...clientCalendarDateBody() }),
    });
  },
};

// --- Dashboard (owner stays: real data from DB) ---
export type RiskLevel = "low" | "medium" | "high";
export type StayClassification = "guest" | "lodger" | "tenant_risk";

export interface OwnerStayView {
  stay_id: number;
  property_id: number;
  /** Invite ID (invitation code) for this stay. */
  invite_id?: string | null;
  /** Token state: STAGED | BURNED | EXPIRED | REVOKED */
  token_state?: string | null;
  /** True when from CSV BURNED invite with no Stay (tenant has not signed up yet). */
  invitation_only?: boolean;
  guest_name: string;
  property_name: string;
  /** Multi-unit property: unit this stay/invite applies to. */
  unit_label?: string | null;
  stay_start_date: string;
  stay_end_date: string;
  region_code: string;
  legal_classification: StayClassification;
  max_stay_allowed_days: number;
  risk_indicator: RiskLevel;
  applicable_laws: string[];
  revoked_at?: string | null;
  /** When set, stay counts as active for occupancy and Status Confirmation. */
  checked_in_at?: string | null;
  checked_out_at?: string | null;
  cancelled_at?: string | null;
  usat_token_released_at?: string | null;
  dead_mans_switch_enabled?: boolean;
  needs_occupancy_confirmation?: boolean;
  show_occupancy_confirmation_ui?: boolean;
  confirmation_deadline_at?: string | null;
  occupancy_confirmation_response?: string | null;
  /** Set when the owner marked the property inactive (soft-deleted). */
  property_deleted_at?: string | null;
}

export interface OwnerInvitationView {
  id: number;
  invitation_code: string;
  property_id: number;
  property_name: string;
  property_deleted_at?: string | null;
  /** Multi-unit: unit the guest invitation is for. */
  unit_label?: string | null;
  guest_name?: string | null;
  guest_email: string | null;
  stay_start_date: string;
  stay_end_date: string;
  region_code: string;
  status: string;
  invitation_kind?: string;
  /** Token state: STAGED | BURNED | EXPIRED | REVOKED */
  token_state?: string;
  created_at: string | null;
  is_expired?: boolean;
  is_demo?: boolean;
}

export interface OwnerTenantView {
  id: number;
  /** Database invitation id (set for pending CSV / manual tenant invites). */
  invitation_id?: number | null;
  tenant_name: string;
  tenant_email: string | null;
  property_name: string;
  /** Street, city, state, zip — for display (e.g. pending CSV invite modal). */
  property_address_line?: string | null;
  property_id: number | null;
  unit_label: string | null;
  unit_id: number;
  start_date: string | null;
  end_date: string | null;
  active: boolean;
  /** Overall status for tenant lease row. Source of truth: invite_status + assignment_status + stay_status. */
  status: 'pending' | 'accepted' | 'active' | 'expired' | 'pending_signup';
  invitation_code: string | null;
  created_at: string | null;
  invite_status?: 'pending' | 'accepted' | 'cancelled' | 'revoked' | 'expired' | 'unknown';
  assignment_status?: 'none' | 'pending' | 'accepted' | 'active' | 'expired';
  stay_status?: 'none' | 'upcoming' | 'checked_in' | 'checked_out' | 'cancelled' | 'revoked' | 'ended';
  /** Shared with other rows when co-tenants overlap on the same unit (server-computed). */
  lease_cohort_id?: string | null;
  cohort_member_count?: number;
}

export interface TenantSignedDocument {
  signature_id: number;
  invitation_code: string;
  document_title: string;
  signed_at: string | null;
  signed_by: string;
  has_signed_pdf: boolean;
  property_name: string | null;
  stay_start_date: string | null;
  stay_end_date: string | null;
  /** self = you signed as guest; guest_invited_by_you = a guest signed an invite you created */
  record_type?: 'self' | 'guest_invited_by_you';
}

export interface GuestStayView {
  stay_id: number;
  /** stay = normal Stay row; agreement_archive = signed agreement on file but no Stay (e.g. invite expired before accept). */
  record_kind?: "stay" | "agreement_archive";
  /** When record_kind is agreement_archive, use with guestAgreementSignedPdfBlob. */
  agreement_signature_id?: number | null;
  /** Invite ID (invitation code) for this stay. */
  invite_id?: string | null;
  /** Token state: STAGED | BURNED | EXPIRED | REVOKED */
  token_state?: string | null;
  /** Slug for live property page URL (#live/<slug>). */
  property_live_slug?: string | null;
  property_name: string;
  /** Unit the guest is invited to (e.g. "5" for multi-unit building). */
  unit_label?: string | null;
  approved_stay_start_date: string;
  approved_stay_end_date: string;
  region_code: string;
  region_classification: string;
  legal_notice: string;
  statute_reference?: string | null;
  plain_english_explanation?: string | null;
  applicable_laws: string[];
  /** Jurisdiction wrap from SOT (same as live property page). */
  jurisdiction_state_name?: string | null;
  jurisdiction_statutes?: { citation: string; plain_english?: string | null }[];
  removal_guest_text?: string | null;
  removal_tenant_text?: string | null;
  usat_token?: string | null;
  revoked_at?: string | null;
  vacate_by?: string | null;
  /** When set, stay is active (occupancy / Status Confirmation). Guest can Check in on or after start date. */
  checked_in_at?: string | null;
  checked_out_at?: string | null;
  cancelled_at?: string | null;
  /** True when invited by a tenant, checked in, active: guest may request longer stay (notifies inviter only). */
  can_request_extension?: boolean;
  /** Property owner / host display name (from stay.owner_id). */
  residence_assigned_by_name?: string | null;
  /** Guest who accepted the stay (from stay guest user or agreement signature). */
  stay_accepted_by_name?: string | null;
  property_deleted_at?: string | null;
}

/** Tenant dashboard: guest asked to extend a stay (approve/decline). */
export interface TenantGuestExtensionRequestView {
  id: number;
  stay_id: number;
  property_id: number;
  property_name: string;
  unit_id?: number | null;
  unit_label?: string | null;
  guest_name: string;
  guest_email: string;
  stay_start_date: string;
  stay_end_date: string;
  message?: string | null;
  status: string;
  created_at: string;
  responded_at?: string | null;
  tenant_note?: string | null;
}

export interface GuestPendingInviteView {
  invitation_code: string;
  property_name: string;
  property_deleted_at?: string | null;
  /** Unit the guest is invited to (e.g. "5" for multi-unit building). */
  unit_label?: string | null;
  stay_start_date: string;
  stay_end_date: string;
  host_name: string | null;
  region_code: string;
  /** True when guest sent agreement to Dropbox but has not yet completed signing; stay cannot be confirmed until signed. */
  needs_dropbox_signature?: boolean;
  pending_signature_id?: number | null;
  /** When set, signature is complete but invite not yet accepted; frontend should call acceptInvite to create stay. */
  accept_now_signature_id?: number | null;
}

export interface OwnerAuditLogEntry {
  id: number;
  property_id: number | null;
  stay_id: number | null;
  invitation_id: number | null;
  category: string;
  title: string;
  message: string;
  actor_user_id: number | null;
  /** Display name for the actor (legacy API key `actor_email`; not a mailbox). */
  actor_email: string | null;
  ip_address: string | null;
  created_at: string;
  property_name: string | null;
}

export interface BillingInvoiceView {
  id: string;
  number: string | null;
  description: string | null;
  amount_due_cents: number;
  amount_paid_cents: number;
  currency: string;
  status: string;
  created: string;
  hosted_invoice_url: string | null;
}

export interface BillingPaymentView {
  invoice_id: string;
  amount_cents: number;
  currency: string;
  paid_at: string;
  description: string | null;
}

// --- Public live property page (no auth) ---
export interface LivePropertyInfo {
  name: string | null;
  street: string;
  city: string;
  state: string;
  zip_code: string | null;
  region_code: string;
  occupancy_status: string;
  shield_mode_enabled: boolean;
  /** staged | released – for Quick Decision layer */
  token_state?: string;
  tax_id?: string | null;
  apn?: string | null;
  /** Owner-listed primary residence (dashboard personal mode); public live page uses plain wording. */
  owner_occupied?: boolean;
  /** Why occupancy reads as it does: guest stay vs tenant lease vs owner residence. */
  occupancy_summary_detail?: string;
}

export interface LiveOwnerInfo {
  full_name: string | null;
  email: string;
  phone: string | null;
}

export interface LivePropertyManagerInfo {
  full_name: string | null;
  email: string;
}

export interface LiveCurrentGuestInfo {
  stay_id: number;
  guest_name: string;
  stay_start_date: string;
  stay_end_date: string;
  checked_out_at: string | null;
  dead_mans_switch_enabled: boolean;
  signed_agreement_available?: boolean;
  signed_agreement_url?: string | null;
  /** guest | tenant — from linked invitation when present */
  stay_kind?: string;
  /** Invite ID linked to this stay */
  invitation_code?: string | null;
  /** STAGED, BURNED, EXPIRED, … from linked invitation */
  invitation_token_state?: string | null;
}

export interface LiveStaySummary {
  guest_name: string;
  stay_start_date: string;
  stay_end_date: string;
  checked_out_at?: string | null;
  /** guest | tenant — from invitation on the stay */
  stay_kind?: string;
}

/** Currently occupying tenant (occupancy priority matches owner/manager dashboard). */
export interface LiveTenantAssignmentInfo {
  assignment_id?: number | null;
  stay_id?: number | null;
  unit_label: string;
  tenant_full_name: string | null;
  tenant_email: string | null;
  start_date: string;
  end_date: string | null;
  created_at: string;
  lease_cohort_id?: string | null;
  lease_cohort_member_count?: number | null;
}

/** Invitation summary – invite states indicate stay status (STAGED/BURNED/EXPIRED/REVOKED). */
export interface LiveInvitationSummary {
  invitation_code: string;
  guest_label: string | null;
  stay_start_date: string;
  stay_end_date: string;
  status: string;
  token_state: string;
  signed_agreement_available?: boolean;
  signed_agreement_url?: string | null;
  /** guest | tenant */
  invitation_kind?: string;
}

export interface LiveLogEntry {
  category: string;
  title: string;
  message: string;
  created_at: string;
  /** Immutable attribution from server (actor_user_id + property); do not infer role from message text alone. */
  actor_user_id?: number | null;
  actor_role?: string | null;
  actor_role_label?: string | null;
  actor_name?: string | null;
  actor_email?: string | null;
}

export interface JurisdictionStatuteView {
  citation: string;
  plain_english?: string | null;
}

export interface JurisdictionWrap {
  state_name: string;
  applicable_statutes: JurisdictionStatuteView[];
  removal_guest_text?: string | null;
  removal_tenant_text?: string | null;
  agreement_type?: string | null;
}

export interface LivePropertyPagePayload {
  has_current_guest: boolean;
  property: LivePropertyInfo;
  owner: LiveOwnerInfo;
  property_managers?: LivePropertyManagerInfo[];
  current_guest: LiveCurrentGuestInfo | null;
  current_guests?: LiveCurrentGuestInfo[];
  last_stay: LiveStaySummary | null;
  upcoming_stays: LiveStaySummary[];
  invitations: LiveInvitationSummary[];
  logs: LiveLogEntry[];
  authorization_state: string; // ACTIVE | NONE | EXPIRED | REVOKED
  record_id: string;
  generated_at: string;
  poa_signed_at: string | null;
  poa_signature_id: number | null;
  poa_typed_signature?: string | null;
  jurisdiction_wrap?: JurisdictionWrap | null;
  current_tenant_assignments?: LiveTenantAssignmentInfo[];
  tenant_summary_assignee?: string | null;
  tenant_summary_assignment_period?: string | null;
}

/** Public portfolio page (owner): basic info + properties list. */
export interface PortfolioPropertyItem {
  id: number;
  name: string | null;
  city: string;
  state: string;
  region_code: string;
  property_type_label?: string | null;
  bedrooms?: string | null;
  is_multi_unit?: boolean;
  unit_count?: number | null;
}

export interface PortfolioOwnerInfo {
  full_name: string | null;
  email: string;
  phone?: string | null;
  state?: string | null;
}

export interface PortfolioPagePayload {
  owner: PortfolioOwnerInfo;
  properties: PortfolioPropertyItem[];
}

/** Request for POST /public/verify (token = Invitation ID; property address optional). */
export interface VerifyRequest {
  token_id: string;
  property_address?: string | null;
  name?: string | null;
  phone?: string | null;
}

/** Response from POST /public/verify. Read-only, live state. Full record when invitation/stay exists. */
export interface VerifyAssignedTenant {
  name: string;
}

export interface VerifyGuestAuthorization {
  authorization_number: number;
  guest_name: string;
  start_date?: string | null;
  end_date?: string | null;
  status: string; // ACTIVE | REVOKED | EXPIRED | CANCELLED | COMPLETED | PENDING
  revoked_at?: string | null;
  expired_at?: string | null;
  cancelled_at?: string | null;
  checked_out_at?: string | null;
}

export interface VerifyResponse {
  valid: boolean;
  reason?: string | null;
  property_name?: string | null;
  property_address?: string | null;
  occupancy_status?: string | null;
  token_state?: string | null;
  stay_start_date?: string | null;
  stay_end_date?: string | null;
  guest_name?: string | null;
  poa_signed_at?: string | null;
  live_slug?: string | null;
  generated_at?: string | null;
  audit_entries: LiveLogEntry[];
  status?: string | null;
  checked_in_at?: string | null;
  checked_out_at?: string | null;
  revoked_at?: string | null;
  cancelled_at?: string | null;
  signed_agreement_available?: boolean;
  signed_agreement_url?: string | null;
  assigned_tenants?: VerifyAssignedTenant[];
  poa_url?: string | null;
  ledger_url?: string | null;
  verified_at?: string | null;
  verification_source?: string;
  authorization_history?: VerifyGuestAuthorization[];
}

export interface BillingResponse {
  invoices: BillingInvoiceView[];
  payments: BillingPaymentView[];
  /** False while billing onboarding is incomplete (e.g. subscription still being created after first property). */
  can_invite: boolean;
  /** Active unit count (billed per unit). */
  current_unit_count?: number | null;
  /** Properties with Shield on (Shield is per property). */
  current_shield_count?: number | null;
  /** Stripe subscription.status when loaded (e.g. trialing, active). */
  subscription_status?: string | null;
  /** ISO datetime when trial ends (UTC from API). */
  trial_end_at?: string | null;
  /** Calendar days remaining in trial (UTC date logic); present when trialing. */
  trial_days_remaining?: number | null;
}

/** In-platform dashboard alert (status changes: nearing expiration, renewed, revoked, expired). */
export interface DashboardAlertView {
  id: number;
  alert_type: string;
  title: string;
  message: string;
  severity: string;
  property_id?: number | null;
  stay_id?: number | null;
  invitation_id?: number | null;
  read_at?: string | null;
  created_at: string;
  meta?: Record<string, unknown> | null;
}

export const dashboardApi = {
  /** List dashboard alerts for the current user. */
  getAlerts: (params?: { unread_only?: boolean; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.unread_only) sp.set("unread_only", "true");
    if (params?.limit != null) sp.set("limit", String(params.limit));
    const q = sp.toString();
    return request<DashboardAlertView[]>(`/dashboard/alerts${q ? `?${q}` : ""}`);
  },
  markAlertRead: (alertId: number) =>
    request<DashboardAlertView>(`/dashboard/alerts/${alertId}/read`, { method: "PATCH" }),
  ownerPersonalModeUnits: () => request<{ unit_ids: number[] }>("/dashboard/owner/personal-mode-units"),
  ownerPropertyPersonalModeUnit: (propertyId: number) =>
    request<{ unit_id: number | null }>(`/dashboard/owner/properties/${propertyId}/personal-mode-unit`),
  ownerStays: () => request<OwnerStayView[]>("/dashboard/owner/stays"),
  ownerInvitations: () => request<OwnerInvitationView[]>("/dashboard/owner/invitations"),
  ownerTenants: () => request<OwnerTenantView[]>("/dashboard/owner/tenants"),
  managerPersonalModeUnits: () => request<{ unit_ids: number[] }>("/dashboard/manager/personal-mode-units"),
  managerStays: () => request<OwnerStayView[]>("/dashboard/manager/stays"),
  managerInvitations: () => request<OwnerInvitationView[]>("/dashboard/manager/invitations"),
  managerLogs: (params?: { from_ts?: string; to_ts?: string; category?: string; search?: string; property_id?: number }) => {
    const sp = new URLSearchParams();
    if (params?.from_ts) sp.set("from_ts", params.from_ts);
    if (params?.to_ts) sp.set("to_ts", params.to_ts);
    if (params?.property_id != null) sp.set("property_id", String(params.property_id));
    if (params?.category) sp.set("category", params.category);
    if (params?.search) sp.set("search", params.search);
    const q = sp.toString();
    return request<OwnerAuditLogEntry[]>(`/dashboard/manager/logs${q ? `?${q}` : ""}`, {
      headers: clientCalendarDateHeaders(),
    });
  },
  managerBilling: () => request<BillingResponse>("/dashboard/manager/billing"),
  managerProperties: () => request<{ id: number; name: string | null; address: string; occupancy_status: string; unit_count: number; occupied_count: number }[]>("/managers/properties"),
  getManagerProperty: (propertyId: number) =>
    request<{
      id: number;
      name: string | null;
      address: string;
      street?: string | null;
      city?: string | null;
      state?: string | null;
      zip_code?: string | null;
      occupancy_status: string;
      unit_count: number;
      occupied_count: number;
      region_code?: string | null;
      property_type_label?: string | null;
      is_multi_unit?: boolean;
      shield_mode_enabled?: boolean;
      live_slug?: string | null;
    }>(`/managers/properties/${propertyId}`),
  managerUnits: (propertyId: number) =>
    request<
      {
        id: number;
        unit_label: string;
        occupancy_status: string;
        occupied_by?: string | null;
        invite_id?: string | null;
        current_tenant_name?: string | null;
        current_tenant_email?: string | null;
        lease_start_date?: string | null;
        lease_end_date?: string | null;
        lease_cohort_member_count?: number | null;
      }[]
    >(`/managers/properties/${propertyId}/units`),
  /** Manager self-service: register as on-site resident for a unit (links Business assignment to Personal Mode for that unit). */
  registerMyResidentMode: (propertyId: number, unitId?: number | null) =>
    request<{ status: string; message?: string; unit_id?: number }>(`/managers/properties/${propertyId}/my-resident-mode`, {
      method: "POST",
      body: JSON.stringify({ unit_id: unitId != null && unitId > 0 ? unitId : null }),
    }),
  /** Manager removes own on-site registration; management assignment unchanged. */
  removeMyResidentMode: (propertyId: number) =>
    request<{ status: string; message?: string }>(`/managers/properties/${propertyId}/my-resident-mode`, { method: "DELETE" }),
  managerInviteTenant: (
    unitId: number,
    data: {
      tenant_name: string;
      tenant_email: string;
      lease_start_date: string;
      lease_end_date: string;
      shared_lease?: boolean;
    },
  ) =>
    request<{ invitation_code: string }>(`/managers/units/${unitId}/invite-tenant`, {
      method: "POST",
      headers: { ...clientCalendarDateHeaders() },
      body: JSON.stringify({ ...data, shared_lease: Boolean(data.shared_lease), ...clientCalendarDateBody() }),
    }),
  /** Invoices and payments for owner billing section. */
  billing: () => request<BillingResponse>("/dashboard/owner/billing"),
  /** Reconcile Stripe subscription with current property count (debugging / explicit sync). Portal open uses `/portal-session`, which syncs internally. */
  syncBillingSubscription: () =>
    request<{
      ok: boolean;
      properties_billed: number;
      monthly_total_cents: number;
      per_property_cents: number;
      stripe_modification_requests: Record<string, unknown>[];
    }>("/dashboard/owner/billing/sync-subscription", { method: "POST" }),
  /** Create Stripe Billing Portal session (runs subscription sync server-side). Longer timeout — multiple Stripe API calls before redirect. */
  billingPortalSession: () =>
    request<{ url: string }>("/dashboard/owner/billing/portal-session", {
      method: "POST",
      signal:
        typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function"
          ? AbortSignal.timeout(120_000)
          : undefined,
    }),
  /** Get or create owner portfolio slug and URL for sharing. Owner only. */
  ownerPortfolioLink: () =>
    request<{ portfolio_slug: string; portfolio_url: string }>("/dashboard/owner/portfolio-link"),
  /** Cancel a pending invitation (owner only). */
  cancelInvitation: (invitationId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/owner/invitations/${invitationId}/cancel`, { method: "POST" }),
  /** Append-only audit logs for owner's properties. Filter by time (ISO UTC), category, search, property_id. */
  ownerLogs: (params?: { from_ts?: string; to_ts?: string; category?: string; search?: string; property_id?: number }) => {
    const sp = new URLSearchParams();
    if (params?.from_ts) sp.set("from_ts", params.from_ts);
    if (params?.to_ts) sp.set("to_ts", params.to_ts);
    if (params?.category) sp.set("category", params.category);
    if (params?.search) sp.set("search", params.search);
    if (params?.property_id != null) sp.set("property_id", String(params.property_id));
    const q = sp.toString();
    return request<OwnerAuditLogEntry[]>(`/dashboard/owner/logs${q ? `?${q}` : ""}`, {
      headers: clientCalendarDateHeaders(),
    });
  },
  tenantDebug: () =>
    request<{ tenant_assignments_count: number; stays_count: number }>("/dashboard/tenant/debug"),
  tenantUnit: () => request<{
    units: Array<{
      unit: { id: number; unit_label: string; occupancy_status: string } | null;
      property: { id: number; name: string; address: string } | null;
      invite_id: string | null;
      token_state: string | null;
      stay_start_date: string | null;
      stay_end_date: string | null;
      live_slug: string | null;
      region_code: string | null;
      jurisdiction_state_name: string | null;
      jurisdiction_statutes: Array<{ citation: string; plain_english?: string | null }>;
      removal_guest_text: string | null;
      removal_tenant_text: string | null;
      assigned_by_name?: string | null;
      accepted_by_name?: string | null;
      pending_acceptance?: boolean;
      dead_mans_switch_enabled?: boolean;
      lease_cohort_id?: string | null;
      cohort_member_count?: number | null;
      co_tenants?: Array<{ name?: string | null; email?: string | null }>;
    }>;
  }>("/dashboard/tenant/unit"),
  tenantSetDeadMansSwitch: (unitId: number, deadMansSwitchEnabled: boolean) =>
    request<{ status: string; dead_mans_switch_enabled: boolean; updated_count: number; message?: string }>(
      "/dashboard/tenant/dead-mans-switch",
      {
        method: "POST",
        body: JSON.stringify({ unit_id: unitId, dead_mans_switch_enabled: deadMansSwitchEnabled }),
      }
    ),
  /** End the tenant's active assignment (checkout): set end_date to today. Pass unitId when tenant has multiple. */
  tenantEndAssignment: (unitId?: number) =>
    request<{ status: string; message?: string }>(
      `/dashboard/tenant/end-assignment${unitId != null ? `?unit_id=${unitId}` : ""}`,
      { method: "POST" }
    ),
  tenantResendInvitation: (invitationId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/tenant/invitations/${invitationId}/resend`, {
      method: "POST",
    }),
  tenantCreateInvitation: async (data: {
    unit_id: number;
    guest_name: string;
    guest_email: string;
    checkin_date: string;
    checkout_date: string;
  }): Promise<{ status: string; data?: { invitation_code: string }; message?: string }> => {
    try {
      const res = await request<{ invitation_code?: string; data?: { invitation_code?: string } }>("/dashboard/tenant/invitations", {
        method: "POST",
        headers: { ...clientCalendarDateHeaders() },
        body: JSON.stringify({ ...data, ...clientCalendarDateBody() }),
      });
      const code = (res as any)?.invitation_code ?? (res as any)?.data?.invitation_code;
      if (!code || typeof code !== "string") {
        return {
          status: "error",
          message: "We couldn't create a valid invitation link. Please try again.",
        };
      }
      return { status: "success", data: { invitation_code: code } };
    } catch (e: any) {
      return {
        status: "error",
        message: toUserFriendlyInvitationError(e?.message ?? "Invitation failed"),
      };
    }
  },
  tenantInvitations: () => request<OwnerInvitationView[]>("/dashboard/tenant/invitations"),
  tenantGuestHistory: () => request<OwnerStayView[]>("/dashboard/tenant/guest-history"),
  tenantSignedDocuments: () => request<TenantSignedDocument[]>("/dashboard/tenant/signed-documents"),
  tenantPropertyVerification: () =>
    request<{
      poa_signed_at: string | null;
      poa_url: string | null;
      guest_agreements: Array<{
        signature_id: number;
        invitation_code: string;
        document_title: string;
        guest_name: string;
        signed_at: string | null;
        stay_start_date: string | null;
        stay_end_date: string | null;
        token_state: string | null;
      }>;
      property_status: string | null;
    }>("/dashboard/tenant/property-verification"),
  /** Event ledger for tenant: assigned property, tenant's actions, invitations tenant created. */
  tenantLogs: (params?: { from_ts?: string; to_ts?: string; category?: string; search?: string; property_id?: number }) => {
    const sp = new URLSearchParams();
    if (params?.from_ts) sp.set("from_ts", params.from_ts);
    if (params?.to_ts) sp.set("to_ts", params.to_ts);
    if (params?.category) sp.set("category", params.category);
    if (params?.search) sp.set("search", params.search);
    if (params?.property_id != null) sp.set("property_id", String(params.property_id));
    const q = sp.toString();
    return request<OwnerAuditLogEntry[]>(`/dashboard/tenant/logs${q ? `?${q}` : ""}`, {
      headers: clientCalendarDateHeaders(),
    });
  },
  getPresence: (unitId: number) =>
    request<{ status: string; unit_id: number; away_started_at: string | null; away_ended_at: string | null; guests_authorized_during_away: boolean }>(
      `/dashboard/presence?unit_id=${unitId}`
    ),
  setPresence: (unitId: number, status: "present" | "away", guestsAuthorizedDuringAway?: boolean) =>
    request<{ status: string; presence: string; unit_id: number; away_started_at?: string | null; away_ended_at?: string | null; guests_authorized_during_away?: boolean }>(
      "/dashboard/presence",
      {
        method: "POST",
        body: JSON.stringify({
          unit_id: unitId,
          status,
          ...(guestsAuthorizedDuringAway !== undefined && { guests_authorized_during_away: guestsAuthorizedDuringAway }),
        }),
      }
    ),
  /** Guest stay presence (for an active checked-in stay). */
  getStayPresence: (stayId: number) =>
    request<{ status: string; stay_id: number; away_started_at: string | null; away_ended_at: string | null; guests_authorized_during_away: boolean }>(
      `/dashboard/guest/presence?stay_id=${stayId}`
    ),
  setStayPresence: (stayId: number, status: "present" | "away", guestsAuthorizedDuringAway?: boolean) =>
    request<{ status: string; presence: string; stay_id: number; away_started_at?: string | null; away_ended_at?: string | null; guests_authorized_during_away?: boolean }>(
      "/dashboard/guest/presence",
      {
        method: "POST",
        body: JSON.stringify({
          stay_id: stayId,
          status,
          ...(guestsAuthorizedDuringAway !== undefined && { guests_authorized_during_away: guestsAuthorizedDuringAway }),
        }),
      }
    ),
  guestStays: () =>
    request<GuestStayView[]>("/dashboard/guest/stays", { headers: clientCalendarDateHeaders() }),
  /** Guest profile (full_legal_name, permanent_home_address). Guest only. */
  guestProfile: () =>
    request<{ id: number; full_legal_name: string; permanent_home_address: string; gps_checkin_acknowledgment: boolean } | null>("/guests/profile"),
  guestPendingInvites: () => request<GuestPendingInviteView[]>("/dashboard/guest/pending-invites"),
  guestAddPendingInvite: (invitationCode: string) =>
    request<GuestPendingInviteView>("/dashboard/guest/pending-invites", {
      method: "POST",
      body: JSON.stringify({ invitation_code: invitationCode.trim().toUpperCase() }),
    }),
  /** Get signed guest agreement PDF for a stay. Guest only. Returns blob. */
  guestStaySignedAgreementBlob: async (stayId: number): Promise<Blob> => {
    const res = await fetch(`${API_URL}/dashboard/guest/stays/${stayId}/signed-agreement-pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (res.status === 404) throw new Error("No signed agreement found for this stay.");
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load signed agreement."));
    return res.blob();
  },
  /** Signed agreement by signature id (agreement_archive rows). Guest only. */
  guestAgreementSignedPdfBlob: async (signatureId: number): Promise<Blob> => {
    const res = await fetch(`${API_URL}/dashboard/guest/signatures/${signatureId}/signed-agreement-pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (res.status === 404) throw new Error("No signed agreement found.");
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load signed agreement."));
    return res.blob();
  },
  /** End an active stay (sets end date to today). Guest only. */
  guestEndStay: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/guest/stays/${stayId}/end`, { method: "POST" }),
  /** Record check-in: sets checked_in_at and property occupancy to OCCUPIED. Guest only; available on or after stay start date. */
  guestCheckIn: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/guest/stays/${stayId}/check-in`, { method: "POST" }),
  /** Cancel a future stay. Guest only. */
  guestCancelStay: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/guest/stays/${stayId}/cancel`, { method: "POST" }),
  guestRequestStayExtension: (stayId: number, body?: { message?: string | null }) =>
    request<{ status: string; message?: string }>(`/dashboard/guest/stays/${stayId}/request-extension`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  /** Activity logs (audit trail) for the guest's stays. Guest only. Optional stay_id restricts to one stay. */
  guestLogs: (params?: { from_ts?: string; to_ts?: string; category?: string; search?: string; stay_id?: number }) => {
    const sp = new URLSearchParams();
    if (params?.from_ts) sp.set("from_ts", params.from_ts);
    if (params?.to_ts) sp.set("to_ts", params.to_ts);
    if (params?.category) sp.set("category", params.category);
    if (params?.search) sp.set("search", params.search);
    if (params?.stay_id != null) sp.set("stay_id", String(params.stay_id));
    const q = sp.toString();
    return request<OwnerAuditLogEntry[]>(`/dashboard/guest/logs${q ? `?${q}` : ""}`, {
      headers: clientCalendarDateHeaders(),
    });
  },
  /** Revoke stay (Kill Switch). Owner only. Guest must vacate in 12 hours; email sent to guest. */
  revokeStay: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/owner/stays/${stayId}/revoke`, { method: "POST" }),
  /** Tenant revokes a guest stay they invited (kill switch; same 12h vacate as owner). */
  tenantRevokeGuestStay: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/tenant/stays/${stayId}/revoke`, { method: "POST" }),
  tenantGuestExtensionRequests: (params?: { pending_only?: boolean }) => {
    const sp = new URLSearchParams();
    if (params?.pending_only) sp.set("pending_only", "true");
    const q = sp.toString();
    return request<TenantGuestExtensionRequestView[]>(`/dashboard/tenant/guest-extension-requests${q ? `?${q}` : ""}`);
  },
  tenantApproveGuestExtension: (requestId: number, body: { invitation_code: string; message?: string | null }) =>
    request<{ status: string; message?: string }>(`/dashboard/tenant/guest-extension-requests/${requestId}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  tenantDeclineGuestExtension: (requestId: number, body?: { message?: string | null }) =>
    request<{ status: string; message?: string }>(`/dashboard/tenant/guest-extension-requests/${requestId}/decline`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  /** Signed guest agreement PDF for a stay the tenant invited (tenant lane). Returns blob. */
  tenantInvitedGuestStaySignedAgreementBlob: async (stayId: number): Promise<Blob> => {
    const res = await fetch(`${API_URL}/dashboard/tenant/guest-stays/${stayId}/signed-agreement-pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (res.status === 404) {
      const t = await res.text().catch(() => "");
      throw new Error(t || "No signed agreement found for this stay yet.");
    }
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load signed agreement."));
    return res.blob();
  },
  /** Signed agreement PDF by signature id (guest invited by tenant; e.g. signed before stay is created). */
  tenantInvitedGuestSignatureSignedAgreementBlob: async (signatureId: number): Promise<Blob> => {
    const res = await fetch(`${API_URL}/dashboard/tenant/guest-signatures/${signatureId}/signed-agreement-pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (res.status === 404) {
      const t = await res.text().catch(() => "");
      throw new Error(t || "No signed agreement available yet.");
    }
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load signed agreement."));
    return res.blob();
  },
  /** Initiate formal removal for overstayed guest. Revokes stay authorization, sends emails to guest and owner. */
  initiateRemoval: (stayId: number) =>
    request<{ status: string; message?: string; usat_revoked?: boolean }>(`/dashboard/owner/stays/${stayId}/initiate-removal`, { method: "POST" }),
  /** Confirm vacant unit still vacant (owner or manager). */
  confirmVacant: (propertyId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/owner/properties/${propertyId}/confirm-vacant`, { method: "POST" }),
  /** Bulk update Shield Mode for selected properties. Owner or manager. */
  bulkShieldMode: (propertyIds: number[], shieldModeEnabled: boolean) =>
    request<{ status: string; updated_count: number; message?: string }>("/dashboard/properties/bulk-shield-mode", {
      method: "POST",
      body: JSON.stringify({ property_ids: propertyIds, shield_mode_enabled: shieldModeEnabled }),
    }),
  /** Owner/manager confirms occupancy: Vacant/Occupied (same as vacated/holdover), or Lease renewed with new end date. */
  confirmOccupancyStatus: (
    stayId: number,
    action: "vacant" | "occupied" | "vacated" | "renewed" | "holdover",
    newLeaseEndDate?: string,
  ) =>
    request<{ status: string; message?: string; occupancy_status?: string; new_lease_end_date?: string }>(
      `/dashboard/owner/stays/${stayId}/confirm-occupancy`,
      {
        method: "POST",
        body: JSON.stringify(
          action === "renewed" ? { action, new_lease_end_date: newLeaseEndDate } : { action }
        ),
      }
    ),
  /** Mark unread lease-end confirmation alerts (48h / end day) for this stay after responding. */
  markOccupancyPromptAlertsRead: (stayId: number) =>
    request<{ status: string; marked_count: number }>(`/dashboard/alerts/mark-occupancy-prompt-read/${stayId}`, {
      method: "POST",
    }),
  /** Owner/manager: Vacant or Occupied for a tenant unit lease (no guest Stay). Marks matching notification alerts read. */
  confirmTenantAssignmentOccupancy: (tenantAssignmentId: number, action: "vacant" | "occupied") =>
    request<{ status: string; message?: string; occupancy_status?: string }>(
      `/dashboard/tenant-assignments/${tenantAssignmentId}/confirm-occupancy`,
      { method: "POST", body: JSON.stringify({ action }) },
    ),
};

/** Admin API (requires role=admin). Read-only lists. */
export interface AdminUserView {
  id: number;
  email: string;
  role: string;
  full_name: string | null;
  created_at: string | null;
}
export interface AdminAuditLogEntry {
  id: number;
  property_id: number | null;
  stay_id: number | null;
  invitation_id: number | null;
  category: string;
  title: string;
  message: string;
  actor_user_id: number | null;
  actor_email: string | null;
  ip_address: string | null;
  created_at: string;
  property_name: string | null;
}
export interface AdminPropertyView {
  id: number;
  owner_profile_id: number;
  owner_email: string | null;
  name: string | null;
  street: string;
  city: string;
  state: string;
  zip_code: string | null;
  region_code: string;
  occupancy_status: string | null;
  deleted_at: string | null;
  created_at: string | null;
}
export interface AdminStayView {
  id: number;
  property_id: number;
  guest_id: number;
  owner_id: number;
  guest_email: string | null;
  owner_email: string | null;
  property_name: string | null;
  stay_start_date: string;
  stay_end_date: string;
  region_code: string;
  checked_in_at: string | null;
  checked_out_at: string | null;
  cancelled_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
}
export interface AdminInvitationView {
  id: number;
  invitation_code: string;
  owner_id: number;
  property_id: number;
  owner_email: string | null;
  property_name: string | null;
  guest_name: string | null;
  guest_email: string | null;
  stay_start_date: string;
  stay_end_date: string;
  status: string;
  token_state: string;
  created_at: string | null;
}

export const adminApi = {
  users: (params?: { search?: string; role?: string; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.search) sp.set("search", params.search);
    if (params?.role) sp.set("role", params.role);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    const q = sp.toString();
    return request<AdminUserView[]>(`/admin/users${q ? `?${q}` : ""}`);
  },
  auditLogs: (params?: {
    from_ts?: string;
    to_ts?: string;
    category?: string;
    property_id?: number;
    actor_user_id?: number;
    search?: string;
    limit?: number;
    offset?: number;
  }) => {
    const sp = new URLSearchParams();
    if (params?.from_ts) sp.set("from_ts", params.from_ts);
    if (params?.to_ts) sp.set("to_ts", params.to_ts);
    if (params?.category) sp.set("category", params.category);
    if (params?.property_id != null) sp.set("property_id", String(params.property_id));
    if (params?.actor_user_id != null) sp.set("actor_user_id", String(params.actor_user_id));
    if (params?.search) sp.set("search", params.search);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    const q = sp.toString();
    return request<AdminAuditLogEntry[]>(`/admin/audit-logs${q ? `?${q}` : ""}`);
  },
  /** Distinct property states for filter dropdowns */
  filterStates: () => request<string[]>("/admin/filters/states"),
  properties: (params?: { search?: string; region_code?: string; state?: string; include_deleted?: boolean; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.search) sp.set("search", params.search);
    if (params?.region_code) sp.set("region_code", params.region_code);
    if (params?.state) sp.set("state", params.state);
    if (params?.include_deleted) sp.set("include_deleted", "true");
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    const q = sp.toString();
    return request<AdminPropertyView[]>(`/admin/properties${q ? `?${q}` : ""}`);
  },
  stays: (params?: { property_id?: number; owner_id?: number; guest_id?: number; state?: string; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.property_id != null) sp.set("property_id", String(params.property_id));
    if (params?.owner_id != null) sp.set("owner_id", String(params.owner_id));
    if (params?.guest_id != null) sp.set("guest_id", String(params.guest_id));
    if (params?.state) sp.set("state", params.state);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    const q = sp.toString();
    return request<AdminStayView[]>(`/admin/stays${q ? `?${q}` : ""}`);
  },
  invitations: (params?: { property_id?: number; owner_id?: number; status?: string; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.property_id != null) sp.set("property_id", String(params.property_id));
    if (params?.owner_id != null) sp.set("owner_id", String(params.owner_id));
    if (params?.status) sp.set("status", params.status);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    const q = sp.toString();
    return request<AdminInvitationView[]>(`/admin/invitations${q ? `?${q}` : ""}`);
  },
};

/** Extract FastAPI `detail` from JSON error body for optional user-facing copy (never return raw JSON). */
function detailFromFastApiErrorBody(bodyText: string): string | null {
  const raw = (bodyText || "").trim();
  if (!raw.startsWith("{")) return null;
  try {
    const j = JSON.parse(raw) as { detail?: unknown };
    const d = j?.detail;
    if (typeof d === "string" && d.length > 0 && d.length <= 400) return d;
    if (Array.isArray(d)) {
      const msgs = d
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item && typeof (item as { msg: unknown }).msg === "string") {
            return (item as { msg: string }).msg;
          }
          return null;
        })
        .filter((x): x is string => Boolean(x));
      if (msgs.length) return msgs.join(" ");
    }
  } catch {
    return null;
  }
  return null;
}

function looksLikeHtmlOrTechnical(s: string): boolean {
  return /<[!?]?[a-z]/i.test(s) || /traceback|stack trace|internal server error/i.test(s) || s.length > 600;
}

/** Short, safe copy for live page load failures (avoids dumping JSON/HTML into the UI). */
function userFacingLivePageLoadError(status: number, bodyText: string): string {
  const detail = detailFromFastApiErrorBody(bodyText);
  const safeDetail = detail && !looksLikeHtmlOrTechnical(detail) ? detail : null;

  if (status === 404) {
    return "We couldn’t find a property for this link. The URL may be wrong, expired, or the owner may have stopped publishing this page.";
  }
  if (status === 401 || status === 403) {
    return safeDetail && safeDetail.length < 200 ? safeDetail : "You don’t have permission to view this page.";
  }
  if (status === 429) {
    return "Too many requests. Please wait a moment and try again.";
  }
  if (status >= 500) {
    return "DocuStay couldn’t load this page right now. Please try again in a few minutes.";
  }
  if (safeDetail && safeDetail.length < 280) {
    return safeDetail;
  }
  return "Something went wrong while loading this page. Please try again.";
}

function normalizeLivePropertyPagePayload(parsed: unknown): LivePropertyPagePayload {
  if (!parsed || typeof parsed !== "object") {
    throw new Error("This page returned incomplete data. Please try again later.");
  }
  const p = parsed as Record<string, unknown>;
  if (!p.property || typeof p.property !== "object" || !p.owner || typeof p.owner !== "object") {
    throw new Error("This page returned incomplete data. Please try again later.");
  }
  const out = { ...(parsed as LivePropertyPagePayload) };
  if (!Array.isArray(out.upcoming_stays)) out.upcoming_stays = [];
  if (!Array.isArray(out.invitations)) out.invitations = [];
  if (!Array.isArray(out.logs)) out.logs = [];
  if (out.current_guests != null && !Array.isArray(out.current_guests)) out.current_guests = [];
  return out;
}

/** Public API (no auth). Live property page by slug – evidence view. */
export const publicApi = {
  getLivePage: async (slug: string): Promise<LivePropertyPagePayload> => {
    const token = getToken();
    const headers: HeadersInit = { Accept: "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(`${API_URL}/public/live/${encodeURIComponent(slug)}`, {
        headers,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (/failed to fetch|network|load failed|internet/i.test(msg)) {
        throw new Error("We couldn’t reach DocuStay. Check your connection and try again.");
      }
      throw new Error("Something went wrong while loading this page. Please try again.");
    }
    const bodyText = await res.text().catch(() => "");
    if (!res.ok) {
      throw new Error(userFacingLivePageLoadError(res.status, bodyText));
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(bodyText);
    } catch {
      throw new Error("This page returned an unexpected response. Please try again later.");
    }
    return normalizeLivePropertyPagePayload(parsed);
  },
  /** URL to open signed Master POA PDF for this live slug (no auth). */
  getLivePoaPdfUrl: (slug: string): string =>
    resolveBackendMediaUrl(`/public/live/${encodeURIComponent(slug)}/poa`),
  /** Signed guest agreement PDF for a stay that is currently active on the live page (no auth). */
  getLiveSignedAgreementUrl: (slug: string, stayId: number): string =>
    resolveBackendMediaUrl(
      `/public/live/${encodeURIComponent(slug)}/signed-agreement?stay_id=${encodeURIComponent(String(stayId))}`,
    ),
  /** Signed guest agreement PDF by invitation code (public; same as verify portal). */
  getVerifySignedAgreementUrl: (invitationCode: string): string =>
    resolveBackendMediaUrl(
      `/public/verify/${encodeURIComponent(invitationCode.trim())}/signed-agreement`,
    ),
  /** Public portfolio page by owner slug (no auth). */
  getPortfolio: async (slug: string): Promise<PortfolioPagePayload> => {
    const res = await fetch(`${API_URL}/public/portfolio/${encodeURIComponent(slug)}`, {
      headers: { Accept: "application/json" },
    });
    if (res.status === 404) throw new Error("Portfolio not found.");
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load."));
    return res.json();
  },
  /** Public verify: check token (Invitation ID) + property address for active authorization. No auth; every attempt logged. */
  verify: async (body: VerifyRequest): Promise<VerifyResponse> => {
    const res = await fetch(`${API_URL}/public/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        token_id: (body.token_id ?? "").trim(),
        property_address: body.property_address != null ? String(body.property_address).trim() || null : null,
        name: body.name != null ? String(body.name).trim() || null : null,
        phone: body.phone != null ? String(body.phone).trim() || null : null,
      }),
    });
    if (!res.ok) throw new Error(await res.text().catch(() => "Verification failed."));
    return res.json();
  },
};

const LIVE_POA_UNAVAILABLE_MSG =
  "No signed Master POA is on file for this property yet. The property owner must complete Master POA signing in DocuStay (Settings or onboarding). After that, the PDF will open here.";

async function blobLooksLikePdf(blob: Blob): Promise<boolean> {
  if ((blob.type || "").toLowerCase().includes("pdf")) return true;
  const slice = await blob.slice(0, 4).arrayBuffer();
  const u = new Uint8Array(slice);
  return u.length >= 4 && u[0] === 0x25 && u[1] === 0x50 && u[2] === 0x44 && u[3] === 0x46;
}

/**
 * Load public Master POA via fetch and open in a new tab (blob URL). Avoids navigating to a JSON 404 body
 * when the owner has not signed POA yet.
 */
export async function openLivePoaPdfInNewTab(
  slug: string,
): Promise<{ ok: true } | { ok: false; userMessage: string }> {
  const trimmed = (slug || "").trim();
  if (!trimmed) {
    return { ok: false, userMessage: "Missing property link." };
  }
  const url = publicApi.getLivePoaPdfUrl(trimmed);
  try {
    const token = getToken();
    const headers: HeadersInit = {
      Accept: "application/pdf;q=1, application/json;q=0.9, */*;q=0.8",
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) {
      let userMessage = LIVE_POA_UNAVAILABLE_MSG;
      const text = await res.text().catch(() => "");
      if (text.trim().startsWith("{")) {
        try {
          const j = JSON.parse(text) as { detail?: unknown };
          const d = j.detail;
          const detailStr = typeof d === "string" ? d : "";
          if (/property not found|^not found$/i.test(detailStr)) {
            userMessage = "This property link is not valid or the property is no longer available.";
          } else if (/poa not on file|poa not available|not available/i.test(detailStr)) {
            userMessage = LIVE_POA_UNAVAILABLE_MSG;
          } else if (detailStr && detailStr.length < 240) {
            userMessage = detailStr;
          }
        } catch {
          /* keep default */
        }
      }
      return { ok: false, userMessage };
    }

    const blob = await res.blob();
    if (blob.size === 0) {
      return { ok: false, userMessage: LIVE_POA_UNAVAILABLE_MSG };
    }
    if (!(await blobLooksLikePdf(blob))) {
      return { ok: false, userMessage: LIVE_POA_UNAVAILABLE_MSG };
    }

    const toOpen =
      (blob.type || "").toLowerCase().includes("pdf")
        ? blob
        : new Blob([await blob.arrayBuffer()], { type: "application/pdf" });
    const objectUrl = URL.createObjectURL(toOpen);
    const w = window.open(objectUrl, "_blank", "noopener,noreferrer");
    if (!w) {
      URL.revokeObjectURL(objectUrl);
      return {
        ok: false,
        userMessage: "Your browser blocked the new tab. Allow pop-ups for this site and try again.",
      };
    }
    setTimeout(() => URL.revokeObjectURL(objectUrl), 120_000);
    return { ok: true };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/failed to fetch|network|load failed/i.test(msg)) {
      return {
        ok: false,
        userMessage: "Could not reach DocuStay. Check your connection and API URL, then try again.",
      };
    }
    return { ok: false, userMessage: "Could not open the POA PDF. Please try again." };
  }
}

// --- Properties ---
export interface Property {
  id: number;
  /** Unique public slug for live link page (#live/<slug>). */
  live_slug?: string | null;
  name: string | null;
  street: string;
  city: string;
  state: string;
  zip_code: string | null;
  region_code: string;
  owner_occupied: boolean;
  property_type: string | null;
  property_type_label: string | null;
  bedrooms: string | null;
  usat_token?: string | null;
  usat_token_state?: string;
  usat_token_released_at?: string | null;
  deleted_at?: string | null;
  /** Shield Mode: independent of vacant/occupied. Owner can turn ON or OFF anytime. Auto ON: last day of a property-lane tenant stay (not tenant-invited guest stays). Status Confirmation does not enable Shield. Auto OFF: when new guest accepts invitation. */
  shield_mode_enabled?: boolean;
  occupancy_status?: string;  // vacant | occupied | unknown | unconfirmed
  /** True when property has multiple units (apartment, duplex, triplex, quadplex). */
  is_multi_unit?: boolean;
  /** Number of units (1 for single-unit; backend may include this for list). */
  unit_count?: number | null;
  /** Multi-unit: how many units are effectively occupied/vacant (for consistent status display). */
  occupied_unit_count?: number | null;
  vacant_unit_count?: number | null;
  ownership_proof_filename?: string | null;
  ownership_proof_type?: string | null;
  ownership_proof_uploaded_at?: string | null;
  tax_id?: string | null;
  apn?: string | null;
  /** From JurisdictionInfo SOT for Documentation tab (region name, stay limits, warning days). */
  jurisdiction_documentation?: {
    name: string;
    region_code: string;
    max_stay_days: number;
    warning_days: number;
    tenancy_threshold_days?: number | null;
  } | null;
}

export interface BulkUploadResult {
  created: number;
  updated: number;
  units_created?: number;
  failed_from_row: number | null;
  failure_reason: string | null;
}

/** Utility Bucket: providers and authority letters for a property. */
export interface PropertyUtilityProviderItem {
  id: number;
  provider_name: string;
  provider_type: string;
  utilityapi_id: string | null;
  contact_phone: string | null;
  contact_email: string | null;
}

export interface PropertyAuthorityLetterItem {
  id: number;
  provider_name: string;
  provider_type?: string;
  letter_content: string;
  email_sent_at?: string | null;
  signed_at?: string | null;
  has_signed_pdf?: boolean;
}

/** User-added provider not in list; verification from background job. */
export interface PendingProviderItem {
  id: number;
  provider_name: string;
  provider_type: string;
  verification_status: string; // pending | in_progress | approved | rejected
}

export interface PropertyUtilitiesResponse {
  providers: PropertyUtilityProviderItem[];
  authority_letters: PropertyAuthorityLetterItem[];
  pending_providers?: PendingProviderItem[];
}

/** Verify address + get utility options (for add-property flow). */
export interface VerifyAddressAndUtilitiesResponse {
  standardized_address: {
    delivery_line_1?: string | null;
    city_name?: string | null;
    state_abbreviation?: string | null;
    zipcode?: string | null;
    latitude?: number | null;
    longitude?: number | null;
  } | null;
  providers_by_type: Record<string, { name: string; phone: string | null }[]>;
}

export const propertiesApi = {
  /** Active properties only (dashboard main list and invite dropdown). */
  list: () => request<Property[]>("/owners/properties"),
  /** Inactive (soft-deleted) properties only. */
  listInactive: () => request<Property[]>("/owners/properties?inactive=1"),
  add: (data: {
    property_name?: string;
    street_address: string;
    city: string;
    state: string;
    zip_code?: string;
    country?: string;
    property_type?: string;
    bedrooms?: string;
    unit_count?: number;
    unit_labels?: string[];
    primary_residence_unit?: number;
    is_primary_residence: boolean;
    tax_id?: string;
    apn?: string;
  }) =>
    request<Property>("/owners/properties", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  get: (id: number) => request<Property>(`/owners/properties/${id}`),
  /** List units for a property. Used when inviting guests to multi-unit properties. */
  getUnits: (propertyId: number) =>
    request<{ id: number; unit_label: string; occupancy_status: string; is_primary_residence?: boolean; occupied_by?: string | null; invite_id?: string | null }[]>(`/owners/properties/${propertyId}/units`),
  /** Create a tenant invitation for a unit. Owner must own the property. Use for multi-unit. */
  inviteTenant: (
    unitId: number,
    data: {
      tenant_name: string;
      tenant_email: string;
      lease_start_date: string;
      lease_end_date: string;
      shared_lease?: boolean;
    },
  ) =>
    request<{ invitation_code: string; status?: string; message?: string }>(`/owners/units/${unitId}/invite-tenant`, {
      method: "POST",
      headers: { ...clientCalendarDateHeaders() },
      body: JSON.stringify({ ...data, shared_lease: Boolean(data.shared_lease), ...clientCalendarDateBody() }),
    }),
  /** Create a tenant invitation for a single-unit property (no unit rows). */
  inviteTenantForProperty: (
    propertyId: number,
    data: {
      tenant_name: string;
      tenant_email: string;
      lease_start_date: string;
      lease_end_date: string;
      shared_lease?: boolean;
    },
  ) =>
    request<{ invitation_code: string; status?: string; message?: string }>(`/owners/properties/${propertyId}/invite-tenant`, {
      method: "POST",
      headers: { ...clientCalendarDateHeaders() },
      body: JSON.stringify({ ...data, shared_lease: Boolean(data.shared_lease), ...clientCalendarDateBody() }),
    }),
  /** Email an existing tenant invitation link (e.g. CSV bulk). Saves name and email on the invitation. */
  sendTenantInviteEmail: (invitationId: number, data: { email: string; tenant_name: string }) =>
    request<{ status: string; message?: string; invite_link?: string }>(`/owners/invitations/${invitationId}/send-tenant-invite-email`, {
      method: "POST",
      body: JSON.stringify({ email: data.email.trim().toLowerCase(), tenant_name: data.tenant_name.trim() }),
    }),
  /** Pending invite; tenant accepts while logged in. Updates the same assignment (no extra DB column). */
  createTenantLeaseExtension: (
    tenantAssignmentId: number,
    data: { lease_end_date: string; send_email?: boolean },
  ) =>
    request<{
      status: string;
      message?: string;
      invitation_code: string;
      invite_link: string;
      email_sent: boolean;
    }>(`/owners/tenant-assignments/${tenantAssignmentId}/lease-extension`, {
      method: "POST",
      headers: { ...clientCalendarDateHeaders() },
      body: JSON.stringify({
        lease_end_date: data.lease_end_date.trim(),
        send_email: data.send_email !== false,
        ...clientCalendarDateBody(),
      }),
    }),
  /** Invite a property manager to manage this property. In test mode, response includes invite_link for console display. */
  inviteManager: (propertyId: number, email: string, options?: { confirmRemoveOtherManagers?: boolean }) =>
    request<{ status: string; message?: string; invite_link?: string }>(`/owners/properties/${propertyId}/invite-manager`, {
      method: "POST",
      body: JSON.stringify({
        email: email.trim().toLowerCase(),
        confirm_remove_other_managers: options?.confirmRemoveOtherManagers === true,
      }),
    }),
  createPropertyTransferInvite: (propertyId: number, email: string) =>
    request<{ status: string; message?: string; invite_link?: string }>(`/owners/properties/${propertyId}/transfer-invite`, {
      method: "POST",
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    }),
  acceptPropertyTransfer: (token: string) =>
    request<{
      status: string;
      message?: string;
      property?: {
        id: number;
        name?: string | null;
        street?: string | null;
        city?: string | null;
        state?: string | null;
        zip_code?: string | null;
        address?: string | null;
      };
    }>(`/owners/accept-property-transfer/${encodeURIComponent(token)}`, {
      method: "POST",
    }),
  listAssignedManagers: (propertyId: number) =>
    request<{ user_id: number; email: string; full_name: string | null; has_resident_mode: boolean; resident_unit_id: number | null; resident_unit_label: string | null; resident_unit_ids?: number[] }[]>(
      `/owners/properties/${propertyId}/assigned-managers`
    ),
  removePropertyManager: (propertyId: number, managerUserId: number) =>
    request<{ status: string; message?: string }>(`/owners/properties/${propertyId}/managers/remove`, {
      method: "POST",
      body: JSON.stringify({ manager_user_id: managerUserId }),
    }),
  addManagerResidentMode: (
    propertyId: number,
    managerUserId: number,
    unitId: number | null,
    options?: { allUnits?: boolean; confirmRemoveOtherManagers?: boolean },
  ) =>
    request<{ status: string; message?: string; unit_ids?: number[]; removed_other_managers?: number }>(
      `/owners/properties/${propertyId}/managers/add-resident-mode`,
      {
        method: "POST",
        body: JSON.stringify(
          options?.allUnits
            ? {
                manager_user_id: managerUserId,
                all_units: true,
                confirm_remove_other_managers: options.confirmRemoveOtherManagers === true,
              }
            : {
                manager_user_id: managerUserId,
                unit_id: unitId,
                confirm_remove_other_managers: options.confirmRemoveOtherManagers === true,
              },
        ),
      },
    ),
  removeManagerResidentMode: (propertyId: number, managerUserId: number) =>
    request<{ status: string; message?: string }>(`/owners/properties/${propertyId}/managers/remove-resident-mode`, {
      method: "POST",
      body: JSON.stringify({ manager_user_id: managerUserId }),
    }),
  /** Utility Bucket: providers and authority letters for this property. */
  getUtilities: (id: number) => request<PropertyUtilitiesResponse>(`/owners/properties/${id}/utilities`),
  /** Verify address (Smarty) and fetch utility options by type. For add-property utilities step. */
  verifyAddressAndUtilities: (data: { street_address: string; city: string; state: string; zip_code?: string }) =>
    request<VerifyAddressAndUtilitiesResponse>("/owners/verify-address-and-utilities", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  /** Save owner-selected utility providers and generate authority letters. */
  setPropertyUtilities: (propertyId: number, data: { selected: { provider_type: string; provider_name: string }[]; pending: { provider_type: string; provider_name: string }[] }) =>
    request<PropertyUtilitiesResponse>(`/owners/properties/${propertyId}/utilities`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  /** Start background lookup for provider contact emails (electric/gas/internet with null email). Returns 202 Accepted. */
  lookupProviderContacts: (propertyId: number, providerIds?: number[]) =>
    request<{ message: string }>(`/owners/properties/${propertyId}/provider-contacts/lookup`, {
      method: "POST",
      body: JSON.stringify(providerIds != null ? { provider_ids: providerIds } : {}),
    }),
  /** Owner config (e.g. test provider email for development). */
  getOwnerConfig: () => request<{ test_provider_email: string | null }>("/owners/config"),
  /** Send authority letters to providers by email (in dev: to TEST_PROVIDER_EMAIL). */
  emailAuthorityLettersToProviders: (propertyId: number) =>
    request<{ message: string; sent_count: number }>(`/owners/properties/${propertyId}/email-providers`, {
      method: "POST",
    }),
  /** Get signed PDF for an authority letter (owner auth). Returns blob URL for opening in new tab. */
  getAuthorityLetterSignedPdfUrl: async (propertyId: number, letterId: number): Promise<string> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/owners/properties/${propertyId}/authority-letters/${letterId}/signed-pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(await res.text().then((t) => t || res.statusText));
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  update: (id: number, data: {
    property_name?: string;
    street_address?: string;
    city?: string;
    state?: string;
    zip_code?: string;
    region_code?: string;
    property_type?: string;
    bedrooms?: string;
    unit_count?: number;
    primary_residence_unit?: number;
    is_primary_residence?: boolean;
    owner_occupied?: boolean;
    shield_mode_enabled?: boolean;
    tax_id?: string;
    apn?: string;
  }) =>
    request<Property>(`/owners/properties/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  delete: (id: number) =>
    request<{ status: string; message: string }>(`/owners/properties/${id}`, {
      method: "DELETE",
    }),
  /** Reactivate an inactive (soft-deleted) property. */
  reactivate: (id: number) =>
    request<Property>(`/owners/properties/${id}/reactivate`, { method: "POST" }),
  /** Get ownership proof URL for viewing (opens in new tab). Returns blob URL; caller should revoke when done. */
  getOwnershipProofBlob: async (propertyId: number): Promise<Blob> => {
    const token = getToken();
    const headers: HeadersInit = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_URL}/owners/properties/${propertyId}/ownership-proof`, { headers });
    if (res.status === 404) throw new Error("No ownership proof uploaded for this property.");
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load proof."));
    return res.blob();
  },
  /** Upload ownership proof (deed, tax bill, etc.) for a property. */
  uploadOwnershipProof: async (propertyId: number, proofType: string, file: File): Promise<Property> => {
    const token = getToken();
    const headers: HeadersInit = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const form = new FormData();
    form.append("proof_type", proofType);
    form.append("proof_file", file);
    const res = await fetch(`${API_URL}/owners/properties/${propertyId}/ownership-proof`, {
      method: "POST",
      headers,
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        detail = Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail || text);
      } catch {
        // use text
      }
      throw new Error(detail);
    }
    return res.json() as Promise<Property>;
  },
  /** Bulk upload properties from CSV. Uses async processing to avoid timeouts on large files.
   *  Submits CSV, then polls for completion. Calls onProgress with (processed, total) during processing. */
  bulkUpload: async (file: File, onProgress?: (processed: number, total: number) => void): Promise<BulkUploadResult> => {
    const token = getToken();
    const headers: HeadersInit = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const contextMode = getContextMode();
    if (contextMode) headers["X-Context-Mode"] = contextMode;
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/owners/properties/bulk-upload-async`, {
      method: "POST",
      headers,
      body: form,
    });
    if (res.status === 401) {
      throw new Error("Session expired. Please log in again.");
    }
    const text = await res.text();
    if (!res.ok) {
      let detail = text;
      try {
        const j = JSON.parse(text);
        detail = Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail || text);
      } catch { /* use text */ }
      throw new Error(detail);
    }
    const parsed = JSON.parse(text) as { job_id: string; total_rows?: number };
    const { job_id } = parsed;
    const initialTotal = typeof parsed.total_rows === "number" && parsed.total_rows > 0 ? parsed.total_rows : 0;
    if (initialTotal > 0) {
      onProgress?.(0, initialTotal);
    }
    let polls = 0;
    let lastProcessed = -1;
    let stallCount = 0;
    const STALL_LIMIT = 60; // give up only after 60 consecutive polls with zero progress (~5 min at 5s intervals)
    while (true) {
      await new Promise(r => setTimeout(r, polls < 5 ? 1000 : polls < 20 ? 2000 : 5000));
      polls++;
      const statusRes = await request<{ status: string; total_rows: number; processed_rows: number; created: number; updated: number; units_created?: number; failed_from_row: number | null; failure_reason: string | null; error_message: string | null }>(
        `/owners/properties/bulk-upload-status/${encodeURIComponent(job_id)}`
      );
      if (statusRes.status === "processing" && onProgress && statusRes.total_rows > 0) {
        onProgress(statusRes.processed_rows, statusRes.total_rows);
      }
      if (statusRes.status === "completed") {
        onProgress?.(statusRes.total_rows, statusRes.total_rows);
        return {
          created: statusRes.created,
          updated: statusRes.updated,
          units_created: statusRes.units_created ?? statusRes.processed_rows ?? 0,
          failed_from_row: statusRes.failed_from_row ?? null,
          failure_reason: statusRes.failure_reason ?? null,
        };
      }
      if (statusRes.status === "failed") {
        throw new Error(statusRes.error_message || "Bulk upload failed. Please try again.");
      }
      // Only timeout if progress has completely stalled
      if (statusRes.processed_rows > lastProcessed) {
        lastProcessed = statusRes.processed_rows;
        stallCount = 0;
      } else {
        stallCount++;
        if (stallCount >= STALL_LIMIT) {
          throw new Error("Upload appears stuck — no progress for several minutes. Please try again or use a smaller file.");
        }
      }
    }
  },
};

// --- Invitations ---
export interface InvitationDetails {
  valid: boolean;
  /** True when the invitation code exists but is expired (not accepted in time). */
  expired?: boolean;
  /** True when the invitation link was already used (guest accepted; one-time use). */
  used?: boolean;
  /** True when the invitation was already accepted (e.g. auto-accepted at email verification for a pre-signed tenant invite). Stay may already be on dashboard. */
  already_accepted?: boolean;
  /** True when the invitation was revoked by the property owner. */
  revoked?: boolean;
  /** True when the invitation was cancelled. */
  cancelled?: boolean;
  /** Machine-readable reason: not_found | already_accepted | revoked | cancelled | expired | invalid_status */
  reason?: string;
  /** From DB: guest | tenant | tenant_cotenant (shared lease / additional occupant). */
  invitation_kind?: 'guest' | 'tenant' | 'tenant_cotenant';
  property_name?: string | null;
  property_address?: string | null;
  stay_start_date?: string;
  stay_end_date?: string;
  region_code?: string;
  host_name?: string;
  guest_name?: string | null;
  guest_email?: string | null;
  /** Derived: true for tenant and tenant_cotenant signup links. */
  is_tenant_invite?: boolean;
  /** Invitation was created by a demo user — use demo login flow. */
  is_demo?: boolean;
}

/** Property-issued tenant signup (standard lease or co-tenant). */
export function isPropertyTenantInviteKind(kind: string | undefined | null): boolean {
  const k = (kind || '').toLowerCase();
  return k === 'tenant' || k === 'tenant_cotenant';
}

export const invitationsApi = {
  getDetails: (code: string) =>
    request<InvitationDetails>(`/owners/invitation-details?code=${encodeURIComponent(code)}`),
  async create(data: {
    owner_id?: string | number;
    property_id?: number;
    unit_id?: number;
    guest_name: string;
    guest_email: string;
    checkin_date: string;
    checkout_date: string;
    dead_mans_switch_enabled?: boolean;
    dead_mans_switch_alert_email?: boolean;
    dead_mans_switch_alert_sms?: boolean;
    dead_mans_switch_alert_dashboard?: boolean;
    dead_mans_switch_alert_phone?: boolean;
  }): Promise<{ status: string; data?: { invitation_code: string }; message?: string }> {
    try {
      const res = await request<{ invitation_code?: string; data?: { invitation_code?: string } }>("/owners/invitations", {
        method: "POST",
        headers: { ...clientCalendarDateHeaders() },
        body: JSON.stringify({ ...data, ...clientCalendarDateBody() }),
      });
      const code = (res as any)?.invitation_code ?? (res as any)?.data?.invitation_code;
      if (!code || typeof code !== "string") {
        return {
          status: "error",
          message: "We couldn't create a valid invitation link. Please try again.",
        };
      }
      return { status: "success", data: { invitation_code: code } };
    } catch (e: any) {
      return {
        status: "error",
        message: toUserFriendlyInvitationError(e?.message ?? "Invitation failed"),
      };
    }
  },
};

// --- Agreements (invite signing) ---
export interface AgreementDocResponse {
  document_id: string;
  region_code: string;
  title: string;
  content: string;
  document_hash: string;
  property_address?: string | null;
  stay_start_date?: string | null;
  stay_end_date?: string | null;
  host_name?: string | null;
  already_signed?: boolean;
  signed_at?: string | null;
  signed_by?: string | null;
  signature_id?: number | null;
  has_dropbox_signed_pdf?: boolean;
}

export const agreementsApi = {
  getInvitationAgreement: (invitationCode: string, guestEmail?: string | null, guestFullName?: string | null) => {
    const code = invitationCode.trim().toUpperCase();
    const params = new URLSearchParams();
    if (guestEmail?.trim()) params.set("guest_email", guestEmail.trim());
    if (guestFullName?.trim()) params.set("guest_full_name", guestFullName.trim());
    const qs = params.toString();
    return request<AgreementDocResponse>(`/agreements/invitation/${encodeURIComponent(code)}${qs ? `?${qs}` : ""}`);
  },
  signInvitationAgreement: (data: {
    invitation_code: string;
    guest_email: string;
    guest_full_name: string;
    typed_signature: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
    document_hash: string;
  }) =>
    request<{ signature_id: number }>("/agreements/sign", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  signInvitationAgreementWithDropbox: (data: {
    invitation_code: string;
    guest_email: string;
    guest_full_name: string;
    typed_signature: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
    document_hash: string;
    ip_address?: string | null;
    is_tenant_invite?: boolean;
  }) =>
    request<{ signature_id: number; sign_url?: string | null }>("/agreements/sign-with-dropbox", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  /** Check if agreement has been fully signed in Dropbox (signed PDF available). Used to poll until complete. */
  getSignatureStatus: (signatureId: number) =>
    request<{ completed: boolean }>(`/agreements/signature/${signatureId}/status`),
  /** Authority letter (provider sign flow, public link by token). */
  getAuthorityLetterByToken: (token: string) =>
    request<AuthorityLetterDocResponse>(`/agreements/authority-letter/${encodeURIComponent(token)}`),
  signAuthorityLetterWithDropbox: (token: string, data: {
    signer_email: string;
    signer_name: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
  }) =>
    request<{ signature_id: number }>(`/agreements/authority-letter/${encodeURIComponent(token)}/sign-with-dropbox`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

export interface AuthorityLetterDocResponse {
  letter_id: number;
  provider_name: string;
  provider_type: string;
  content: string;
  property_address?: string | null;
  property_name?: string | null;
  already_signed?: boolean;
  signed_at?: string | null;
  has_dropbox_signed_pdf?: boolean;
}

// --- Owner Master POA (signup) ---
export interface OwnerPOADocResponse {
  document_id: string;
  title: string;
  content: string;
  document_hash: string;
  already_signed?: boolean;
  signed_at?: string | null;
  signed_by?: string | null;
  signature_id?: number | null;
  has_dropbox_signed_pdf?: boolean;
}

export interface OwnerPOASignatureResponse {
  signature_id: number;
  signed_at: string;
  signed_by: string;
  document_title: string;
  document_id: string;
  has_dropbox_signed_pdf?: boolean;
}

export const ownerPoaApi = {
  getDocument: (ownerEmail?: string | null, ownerFullName?: string | null, address?: { city?: string | null; state?: string | null; country?: string | null } | null, principalTitle?: string | null) => {
    const parts: string[] = [];
    if (ownerEmail?.trim()) parts.push(`owner_email=${encodeURIComponent(ownerEmail.trim())}`);
    if (ownerFullName?.trim()) parts.push(`owner_full_name=${encodeURIComponent(ownerFullName.trim())}`);
    if (address?.city?.trim()) parts.push(`owner_city=${encodeURIComponent(address.city.trim())}`);
    if (address?.state?.trim()) parts.push(`owner_state=${encodeURIComponent(address.state.trim())}`);
    if (address?.country?.trim()) parts.push(`owner_country=${encodeURIComponent(address.country.trim())}`);
    if (principalTitle?.trim()) parts.push(`principal_title=${encodeURIComponent(principalTitle.trim())}`);
    const params = parts.length ? `?${parts.join("&")}` : "";
    return request<OwnerPOADocResponse>(`/agreements/owner-poa${params}`);
  },
  signWithDropbox: (data: {
    owner_email: string;
    owner_full_name: string;
    typed_signature: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
    document_hash: string;
    owner_city?: string | null;
    owner_state?: string | null;
    owner_country?: string | null;
    principal_title?: string | null;
  }) =>
    request<{ signature_id: number; sign_url?: string | null }>("/agreements/owner-poa/sign-with-dropbox", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getMySignature: () =>
    request<OwnerPOASignatureResponse | null>("/agreements/owner-poa/my-signature"),
};

// --- Guest registration (from invite link) ---
export const authApiGuest = {
  async register(data: {
    role?: "guest" | "tenant";
    invitation_id?: string;
    invitation_code?: string;
    full_name: string;
    email: string;
    phone: string;
    password: string;
    confirm_password: string;
    permanent_address: string;
    permanent_city: string;
    permanent_state: string;
    permanent_zip: string;
    terms_agreed: boolean;
    privacy_agreed: boolean;
    guest_status_acknowledged: boolean;
    no_tenancy_acknowledged: boolean;
    vacate_acknowledged: boolean;
    agreement_signature_id?: number | null;
  }): Promise<{
    status: string;
    data?: UserSession | { user_id: string; verificationRequired: true };
    message?: string;
    validation?: Record<string, { error?: string }>;
  }> {
    try {
      const body = await request<TokenResponse & { user_id?: number; message?: string }>("/auth/register/guest", {
        method: "POST",
        body: JSON.stringify(data),
      });
      if (body.user_id != null && !body.access_token) {
        return {
          status: "success",
          data: { user_id: String(body.user_id), verificationRequired: true },
          message: body.message || "Check your email for the verification code.",
        };
      }
      setToken(body.access_token);
      return {
        status: "success",
        data: toUserSession(body as TokenResponse),
      };
    } catch (e: any) {
      const msg = e?.message || "Registration failed";
      const validation: Record<string, { error: string }> = {};
      if (msg.includes("Passwords")) validation.password_match = { error: "Passwords do not match" };
      if (msg.includes("agree")) {
        validation.terms = { error: "You must agree to the Terms of Service and Privacy Policy" };
        validation.privacy = { error: "You must agree to the Terms of Service and Privacy Policy" };
      }
      if (msg.includes("acknowledge")) validation.acknowledgments = { error: "You must acknowledge all guest and vacate terms" };
      if (msg.includes("already registered")) validation.email = { error: "Email already registered" };
      if (msg.includes("Invalid or no longer valid")) validation.invitation = { error: "Invalid or no longer valid invitation code." };
      else if (msg.includes("Invalid or expired") || msg.includes("Invitation code")) validation.invitation = { error: "Invalid or expired invitation code." };
      return { status: "error", message: msg, validation };
    }
  },
};
