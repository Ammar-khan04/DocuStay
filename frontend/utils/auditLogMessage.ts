/**
 * Removes ledger "State change on record:" paragraphs (prior/new JSON snapshots)
 * from audit log `message` text for dashboard, notifications, and similar UI.
 */
export function scrubAuditLogStateChangeParagraph(raw: string | null | undefined): string {
  const s = (raw || '').trim();
  if (!s) return '';
  const blocks = s.split(/\n\n+/);
  const kept = blocks.filter((b) => !/^State change on record:/i.test(b.trim()));
  return kept.join('\n\n').trim();
}
