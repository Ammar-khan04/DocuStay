/**
 * Validates phone number for owner/guest signup.
 * Format: optional + at start, then only digits. No spaces, dashes, or parentheses.
 * Requires 10–15 digits (E.164 style).
 */
const MIN_DIGITS = 10;
const MAX_DIGITS = 15;

/** Regex: optional + at start, then only digits. */
const PHONE_FORMAT = /^\+?\d+$/;

export function normalizePhone(input: string | null | undefined): string {
  const s = (input ?? "").trim();
  const hasPlus = s.startsWith("+");
  const digits = s.replace(/\D/g, "");
  return hasPlus ? `+${digits}` : digits;
}

/** Sanitizes input as user types: keeps only optional + at start and digits. Use in onChange. */
export function sanitizePhoneInput(value: string): string {
  const s = (value ?? "").trimStart();
  const hasPlus = s.startsWith("+");
  const digits = s.replace(/\D/g, "");
  return hasPlus ? `+${digits}` : digits;
}

export function validatePhone(input: string | null | undefined): { valid: boolean; error?: string } {
  const s = (input ?? "").trim();
  if (!s) {
    return { valid: false, error: "Phone number is required." };
  }
  if (!PHONE_FORMAT.test(s)) {
    return { valid: false, error: "Phone number can only contain digits. A + at the start is optional (e.g. +15551234567 or 5551234567)." };
  }
  const digitsOnly = s.replace(/\D/g, "");
  if (digitsOnly.length < MIN_DIGITS) {
    return { valid: false, error: `Enter at least ${MIN_DIGITS} digits (e.g. 5551234567 or +15551234567).` };
  }
  if (digitsOnly.length > MAX_DIGITS) {
    return { valid: false, error: `Phone number cannot exceed ${MAX_DIGITS} digits.` };
  }
  return { valid: true };
}
