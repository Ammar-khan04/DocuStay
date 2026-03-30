/**
 * Maps API/technical error messages to user-understandable messages for invitation
 * and agreement flows. Use when showing errors to the user (toast, modal, inline).
 */

/**
 * Returns a user-friendly error message for invitation/create/agreement errors.
 * Falls back to a generic message if no mapping matches.
 */
export function toUserFriendlyInvitationError(apiMessage: string | undefined | null): string {
  const raw = (apiMessage ?? "").trim().toLowerCase();
  const orig = (apiMessage ?? "").trim();

  // Pass through backend validation messages (already user-friendly)
  if (
    orig.length > 0 &&
    orig.length <= 200 &&
    !orig.includes("detail") &&
    (orig.endsWith(".") || orig.includes("required") || orig.includes("cannot") || orig.includes("must be") || orig.includes("Invalid") || orig.includes("stay starts") || orig.includes("stay ends"))
  ) {
    return orig;
  }

  // Jurisdiction / legal limit: show backend message so user sees max days and reason
  if (
    orig.length > 0 &&
    orig.length <= 500 &&
    (raw.includes("exceeds") && (raw.includes("maximum allowed") || raw.includes("renewal cycle") || raw.includes("jurisdiction") || raw.includes("days")))
  ) {
    return orig;
  }

  if (raw.includes("overlap")) {
    return orig.length > 0 && orig.length <= 500 ? orig : "A tenant lease already exists for this property that overlaps with the selected dates. Please choose different dates.";
  }

  // Invitation not found / expired / invalid (agreement 404)
  if (raw.includes("not found") || raw.includes("not pending") || raw.includes("expired")) {
    return "This invite has expired. Please contact your host to request a new one.";
  }

  // Server didn't return invitation code (create succeeded but no code in response)
  if (raw.includes("did not return") || raw.includes("invitation code")) {
    return "We couldn't create a valid invitation link. Please try again.";
  }

  // Network / server unavailable
  if (raw.includes("unavailable") || raw.includes("fetch") || raw.includes("network")) {
    return "The server is unavailable. Please check your connection and try again.";
  }

  // Session / auth
  if (raw.includes("session expired") || raw.includes("log in again")) {
    return "Your session expired. Please log in again.";
  }
  if (raw.includes("not authenticated") || raw.includes("unauthorized")) {
    return "Please log in to continue.";
  }

  // Validation (dates, property, unit)
  if ((raw.includes("check-in") || raw.includes("authorization start")) && raw.includes("past")) {
    return "Authorization start date cannot be in the past.";
  }
  if (raw.includes("checkout") && raw.includes("before")) {
    return "End date must be after start date.";
  }
  if (raw.includes("property") && (raw.includes("not found") || raw.includes("inactive"))) {
    return "This property is no longer available. Please choose another property.";
  }
  if (raw.includes("select a unit") || raw.includes("unit not found")) {
    return "Please select a unit.";
  }
  if (raw.includes("guest name") && raw.includes("required")) {
    return "Guest name is required.";
  }
  if (raw.includes("start and end dates")) {
    return "Start and end dates are required.";
  }
  if (raw.includes("end date must be after start")) {
    return "End date must be after start date.";
  }
  if (raw.includes("stay starts") || raw.includes("stay ends")) {
    return orig.length > 0 && orig.length <= 200 ? orig : "Guest authorization dates must fall within your stay.";
  }

  // One email = one account type (registration)
  if (
    raw.includes("each email can only be used for one account type") ||
    raw.includes("registration is already in progress for this email")
  ) {
    return orig.length > 0 && orig.length <= 600 ? orig : "This email can't be used for this signup. Sign in with your existing account or use a different email.";
  }

  // Pydantic/validation (field required, type errors, etc.)
  if (raw.includes("field required") || raw.includes("value error") || raw.includes("input should be")) {
    return "Please fill in all required fields and try again.";
  }

  // Generic fallbacks
  if (raw.includes("invitation failed") || raw.includes("create invitation")) {
    return "We couldn't create the invitation. Please try again.";
  }

  return "Something went wrong. Please try again.";
}
