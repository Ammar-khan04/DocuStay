/**
 * Date/time display and API helpers.
 * - API stores and returns instants in UTC (ISO 8601).
 * - Calendar fields (stay start/end) are often YYYY-MM-DD without timezone; parse as local calendar dates to avoid day shift.
 * - Display uses the browser's local timezone with consistent en-US formatting.
 */

const CALENDAR: Intl.DateTimeFormatOptions = {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
};

/** Same calendar shape, explicitly local (for date-only inputs). */
export function formatCalendarDateLocal(y: number, m0: number, d: number): string {
  return new Date(y, m0, d).toLocaleDateString('en-US', CALENDAR);
}

/**
 * True if the string is exactly YYYY-MM-DD (no time / timezone).
 * These must be interpreted as local dates, not UTC midnight.
 */
export function isDateOnlyString(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s.trim());
}

/**
 * Parse API or form strings for display. Date-only → local noon avoids DST edge weirdness when re-formatting.
 */
export function parseForDisplay(iso: string): Date {
  const t = iso.trim();
  if (isDateOnlyString(t)) {
    const [y, m, d] = t.split('-').map(Number);
    return new Date(y, m - 1, d, 12, 0, 0, 0);
  }
  return new Date(iso);
}

/** Calendar date: Mar 30, 2026 — for lease/stay boundaries and date-only fields. */
export function formatCalendarDate(iso: string | Date | null | undefined): string {
  if (iso == null || iso === '') return '—';
  const d = typeof iso === 'string' ? parseForDisplay(iso) : iso;
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', CALENDAR);
}

/**
 * Instant from API (UTC ISO): show in the user's local timezone (browser default).
 * No timeZone option → wall clock is local. Omit timeZoneName so ICU does not append
 * opaque labels like "GMT+5" (still local time, but reads as a UTC offset).
 * Example: Mar 30, 2026, 3:45 PM
 */
export function formatDateTimeLocal(iso: string | Date | null | undefined): string {
  if (iso == null || iso === '') return '—';
  const d = typeof iso === 'string' ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** Alias for event ledger / audit tables. */
export function formatLedgerTimestamp(iso: string | Date | null | undefined): string {
  return formatDateTimeLocal(iso);
}

/** Modal / detail: slightly longer form optional. */
export function formatDateTimeLocalMedium(iso: string | Date | null | undefined): string {
  if (iso == null || iso === '') return '—';
  const d = typeof iso === 'string' ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  });
}

/** Start of selected local calendar day as UTC ISO for ?from_ts= */
export function localDateInputToUtcStartIso(yyyyMmDd: string): string {
  const [y, m, d] = yyyyMmDd.split('-').map(Number);
  return new Date(y, m - 1, d, 0, 0, 0, 0).toISOString();
}

/** End of selected local calendar day as UTC ISO for ?to_ts= */
export function localDateInputToUtcEndIso(yyyyMmDd: string): string {
  const [y, m, d] = yyyyMmDd.split('-').map(Number);
  return new Date(y, m - 1, d, 23, 59, 59, 999).toISOString();
}

/** Today's date in local timezone as YYYY-MM-DD (for min date, validation, etc.). */
export function getTodayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Add whole calendar years to a YYYY-MM-DD string (local calendar; for default lease end, etc.). */
export function addCalendarYears(ymd: string, years: number): string {
  const parts = ymd.split('-').map((x) => parseInt(x, 10));
  const y = parts[0];
  const m = parts[1];
  const d = parts[2];
  if (!y || !m || !d) return ymd;
  const dt = new Date(y, m - 1, d);
  dt.setFullYear(dt.getFullYear() + years);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}

/** Format stay date range and duration. Handles invalid ranges (end < start) by swapping for display. */
export function formatStayDuration(startStr: string, endStr: string): string {
  let start = parseForDisplay(startStr);
  let end = parseForDisplay(endStr);
  if (end.getTime() < start.getTime()) {
    [start, end] = [end, start];
  }
  const days = Math.max(1, Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)));
  const fmt = (d: Date) => d.toLocaleDateString('en-US', CALENDAR);
  return `${fmt(start)} – ${fmt(end)} (${days} day${days !== 1 ? 's' : ''})`;
}
