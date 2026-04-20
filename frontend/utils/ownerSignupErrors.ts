/**
 * User-friendly error messages and redirect targets for Owner signup flow.
 * Maps backend/API error messages to clear copy and suggests where to send the user.
 */

export type RedirectTarget = "register" | "verify" | "login" | "onboarding/identity" | "onboarding/poa" | null;

/** Stripe Identity last_error.code values we may get from the backend on confirm-identity 400. */
const STRIPE_IDENTITY_ERROR_CODES: Record<string, string> = {
  document_expired: "Your document has expired. Please use a valid, current ID and try again.",
  selfie_face_mismatch: "The selfie didn't match your document. Please try again and ensure your face is clearly visible.",
  document_unverified_other: "We couldn't verify your document. Please use a valid government-issued ID and try again.",
  abandoned: "Verification wasn't completed. You can try again.",
};

/**
 * Returns a short user-friendly message for a Stripe Identity error code (from confirm-identity 400 body).
 * Returns null if no mapping exists (caller can fall back to API detail message).
 */
export function getStripeIdentityErrorCodeMessage(code: string | undefined | null): string | null {
  if (!code || typeof code !== "string") return null;
  const key = code.trim().toLowerCase();
  return STRIPE_IDENTITY_ERROR_CODES[key] ?? null;
}

export interface OwnerSignupErrorResult {
  /** Message to show in UI (toast, inline, or modal). */
  message: string;
  /** Where to navigate after showing the error (null = stay on current page). */
  redirectTo: RedirectTarget;
}

/**
 * Returns a user-friendly message and optional redirect for owner signup/onboarding errors.
 */
export function getOwnerSignupErrorFriendly(
  apiMessage: string | undefined | null
): OwnerSignupErrorResult {
  const raw = (apiMessage ?? "").trim().toLowerCase();

  // --- Signup form (duplicate email, validation) ---
  if (raw.includes("each email can only be used for one account type") || raw.includes("one account type on docustay")) {
    return {
      message:
        apiMessage?.trim() ||
        "This email is already used for another account type. Sign in with that account or use a different email.",
      redirectTo: null,
    };
  }
  if (raw.includes("registration is already in progress")) {
    return {
      message:
        apiMessage?.trim() ||
        "A signup with this email is already in progress. Check your email for the code, wait for it to expire, or use a different email.",
      redirectTo: null,
    };
  }
  if (raw.includes("property owner") || raw.includes("already registered as a property owner")) {
    return {
      message: "This email is already registered as a property owner. Please log in on the Owner Login page.",
      redirectTo: null,
    };
  }
  if (raw.includes("already registered")) {
    return { message: "This email is already registered. Try logging in or use a different email.", redirectTo: null };
  }
  if (raw.includes("passwords do not match") || raw.includes("password")) {
    return { message: "Passwords do not match. Please check and try again.", redirectTo: null };
  }
  if (raw.includes("agree") || raw.includes("terms") || raw.includes("privacy")) {
    return { message: "Please agree to the Terms of Service and Privacy Policy to continue.", redirectTo: null };
  }
  if (raw.includes("could not send the verification email") || raw.includes("verification email")) {
    return {
      message: "We couldn't send the verification email. Check that MAILGUN_API_KEY and MAILGUN_DOMAIN are set in .env, restart the server, and try again. You can run: python scripts/test_verification_email.py your@email.com",
      redirectTo: null,
    };
  }
  if (raw.includes("email verification is required") || raw.includes("mailgun")) {
    return {
      message: "Email verification is temporarily unavailable. Set MAILGUN_API_KEY and MAILGUN_DOMAIN in .env, restart the server, then try again.",
      redirectTo: null,
    };
  }

  // --- Verify email (wrong or expired code) ---
  // IMPORTANT: These must come BEFORE phone number check to avoid false matches on "digits"
  if (raw.includes("verification code must be exactly 6 digits") || (raw.includes("6 digits") && raw.includes("code"))) {
    return { message: "Please enter all 6 digits from your verification email.", redirectTo: null };
  }
  if (raw.includes("invalid or expired verification code") || raw.includes("invalid or expired code")) {
    return {
      message: "That code isn't correct. Check the 6-digit code from your email and try again.",
      redirectTo: null,
    };
  }
  if (raw.includes("verification code has expired") || (raw.includes("code") && raw.includes("expired")) || raw.includes("please request a new one")) {
    return {
      message: "This verification code has expired. Please click 'Resend now' below to get a new code.",
      redirectTo: null,
    };
  }
  if ((raw.includes("wrong") || raw.includes("incorrect")) && raw.includes("code")) {
    return {
      message: "That code isn't correct. Please check the 6-digit code from your email and try again.",
      redirectTo: null,
    };
  }
  if (raw.includes("invalid or expired")) {
    return {
      message: "That code isn't correct or has expired. Please try again or request a new code.",
      redirectTo: null,
    };
  }
  if (
    raw.includes("verification session not found") ||
    raw === "invalid request" ||
    (raw.includes("invalid") && raw.includes("request"))
  ) {
    return {
      message: "Please go back to registration and sign up again.",
      redirectTo: "register",
    };
  }

  // --- Phone number validation (must come AFTER verification code checks) ---
  if (raw.includes("phone") || (raw.includes("digits") && !raw.includes("verification") && !raw.includes("code"))) {
    return {
      message: "Please enter a valid phone number (digits only, optional + at start, e.g. 5551234567 or +15551234567).",
      redirectTo: null,
    };
  }

  // --- 503 errors (service unavailable) ---
  if (raw.includes("503")) {
    return {
      message: "This service is temporarily unavailable. Please try again later.",
      redirectTo: null,
    };
  }

  // --- Stripe Identity (failure on identity-complete page: show message and "Back to owner signup", no redirect loop) ---
  if (raw.includes("document is invalid") || raw.includes("document_unverified") || raw.includes("The document is invalid")) {
    return {
      message: "Stripe Identity verification failed. The document could not be verified. Please try again with a valid ID or go back to sign up.",
      redirectTo: null,
    };
  }
  if (raw.includes("verification not completed") || raw.includes("requires_input") || raw.includes("not completed")) {
    return {
      message: "Stripe Identity verification was not completed. Please try again with a valid government-issued ID, or go back to sign up.",
      redirectTo: null,
    };
  }
  if (raw.includes("invalid verification session") || raw.includes("session_id")) {
    return {
      message: "We couldn't confirm your verification. Please start identity verification again from the previous step.",
      redirectTo: "onboarding/identity",
    };
  }
  if (raw.includes("no identity session") || raw.includes("no verification session")) {
    return {
      message: "We couldn't find your verification session. Please go back and start identity verification again.",
      redirectTo: "onboarding/identity",
    };
  }
  if (raw.includes("identity verification is not configured")) {
    return {
      message: "Identity verification is temporarily unavailable. Please try again later.",
      redirectTo: "onboarding/identity",
    };
  }
  if (raw.includes("identity not verified")) {
    return {
      message: "Identity verification is required before you can continue. Please complete the identity step first.",
      redirectTo: "onboarding/identity",
    };
  }

  // --- Email verified (required before identity/POA) ---
  if (raw.includes("email not verified")) {
    return {
      message: "Please verify your email first. You'll be taken to the verification page. Check your inbox for the 6-digit code.",
      redirectTo: "verify",
    };
  }

  // --- POA / complete-signup ---
  if (
    raw.toLowerCase().includes("complete signing in dropbox") ||
    (raw.toLowerCase().includes("dropbox") && raw.toLowerCase().includes("before completing signup"))
  ) {
    return {
      message:
        "You must sign the document we sent via email (from Dropbox Sign) before you can complete verification. Open the email, sign the document, then click Complete Verification again.",
      redirectTo: null,
    };
  }
  if (raw.includes("master poa signature") && raw.includes("already used")) {
    return {
      message: "This Master POA signature was already used for another account. Please sign the document again to create a new signature.",
      redirectTo: null,
    };
  }
  if (raw.includes("email does not match") || raw.includes("signature email")) {
    return {
      message: "The email on the Master POA doesn't match your account. Please sign using the same email you registered with.",
      redirectTo: null,
    };
  }
  if (raw.includes("invalid master poa") || (raw.includes("invalid") && raw.includes("poa"))) {
    return {
      message: "We couldn't use this signature. Please sign the Master POA again.",
      redirectTo: null,
    };
  }
  if (raw.includes("document has changed")) {
    return { message: "The document was updated. Please refresh the page and sign again.", redirectTo: null };
  }
  if (raw.includes("account may already be created") || raw.includes("try logging in")) {
    return {
      message: "Your account may already be created. Try logging in with your email and password.",
      redirectTo: "login",
    };
  }
  if (raw.includes("session expired") || raw.includes("unauthorized")) {
    return {
      message: "Your session has expired. Please log in again or start over from registration.",
      redirectTo: "register",
    };
  }

  // Verification flow: friendly generic so we don't show technical backend text
  if (raw.includes("verification") || raw.includes("verify") || raw.includes("code") || raw.includes("expired")) {
    return {
      message: "We couldn't verify your code. Please check the 6-digit code from your email and try again, or click 'Resend now' to get a new code.",
      redirectTo: null,
    };
  }

  // Default: show API message if it's short and readable, otherwise generic
  const fallback =
    apiMessage && apiMessage.length <= 200 && !apiMessage.startsWith("{")
      ? apiMessage
      : "Something went wrong. Please try again or contact support.";
  return { message: fallback, redirectTo: null };
}
