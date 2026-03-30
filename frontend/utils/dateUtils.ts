/** Today's date in local timezone as YYYY-MM-DD (for min date, validation, etc.). */
export function getTodayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Format stay date range and duration. Handles invalid ranges (end < start) by swapping for display. */
export function formatStayDuration(startStr: string, endStr: string): string {
  let start = new Date(startStr);
  let end = new Date(endStr);
  if (end.getTime() < start.getTime()) {
    [start, end] = [end, start];
  }
  const days = Math.max(1, Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)));
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return `${fmt(start)} – ${fmt(end)} (${days} day${days !== 1 ? 's' : ''})`;
}
