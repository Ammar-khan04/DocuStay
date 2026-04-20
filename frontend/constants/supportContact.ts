/**
 * Canonical support contact for DocuStay (must match Privacy Policy & Terms of Service).
 * Optional override: set VITE_SUPPORT_EMAIL in .env (baked in at Vite build time).
 */
export const SUPPORT_EMAIL: string =
  (typeof import.meta !== 'undefined' && (import.meta as { env?: { VITE_SUPPORT_EMAIL?: string } }).env?.VITE_SUPPORT_EMAIL) ||
  'michael@docustay.online';

/** Legal entity name shown next to support email on legal pages. */
export const SUPPORT_LEGAL_ENTITY_NAME = 'DOCUSTAY LLC';

export function supportMailtoHref(subject?: string): string {
  const base = `mailto:${SUPPORT_EMAIL}`;
  if (!subject?.trim()) return base;
  return `${base}?subject=${encodeURIComponent(subject)}`;
}
