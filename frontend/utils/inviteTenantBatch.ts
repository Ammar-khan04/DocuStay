export type CoTenantInviteRow = { tenant_name: string; tenant_email: string };

function normalizeEmailKey(email: string): string {
  return (email || '').trim().toLowerCase();
}

export function validateCoTenantRows(rows: CoTenantInviteRow[]): string | null {
  if (rows.length < 2) {
    return 'Add at least two co-tenants, or switch to one tenant.';
  }
  const seen = new Set<string>();
  for (let i = 0; i < rows.length; i += 1) {
    const name = rows[i].tenant_name.trim();
    const email = rows[i].tenant_email.trim();
    if (!name) return `Co-tenant ${i + 1}: enter a name.`;
    if (!email) return `Co-tenant ${i + 1}: enter an email.`;
    const key = normalizeEmailKey(email);
    if (seen.has(key)) return 'Each co-tenant must use a different email address.';
    seen.add(key);
  }
  return null;
}
