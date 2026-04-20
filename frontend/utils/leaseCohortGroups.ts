import type { LiveTenantAssignmentInfo, OwnerTenantView } from '../services/api';

/** One visual group: either a shared-lease cohort or a single tenant row. */
export type OwnerTenantGroup = { cohortKey: string; members: OwnerTenantView[] };

/** All /dashboard/owner/tenants rows that apply to a unit tile (same rules as dashboard pick helpers). */
export function tenantsPoolForUnitCard(
  propertyTenants: OwnerTenantView[],
  unitId: number,
  unitLabel: string,
  isMultiUnit: boolean,
): OwnerTenantView[] {
  const uid = unitId > 0 ? unitId : null;
  let pool: OwnerTenantView[];
  if (isMultiUnit && uid != null) {
    pool = propertyTenants.filter((t) => Number(t.unit_id) === uid);
  } else {
    const noUnit = propertyTenants.filter((t) => t.unit_id == null || Number(t.unit_id) === 0);
    pool = noUnit.length ? noUnit : propertyTenants;
    const byLabel = pool.filter((t) => (t.unit_label || '1').trim() === String(unitLabel).trim());
    if (byLabel.length) pool = byLabel;
  }
  return pool;
}

/** Stable sort for tenant groups (property, unit, lease start). */
function sortTenantGroups(groups: OwnerTenantGroup[]): OwnerTenantGroup[] {
  return [...groups].sort((a, b) => {
    const pa = a.members[0]?.property_name ?? '';
    const pb = b.members[0]?.property_name ?? '';
    if (pa !== pb) return pa.localeCompare(pb);
    const ua = a.members[0]?.unit_label ?? '';
    const ub = b.members[0]?.unit_label ?? '';
    if (ua !== ub) return ua.localeCompare(ub, undefined, { numeric: true });
    const sa = a.members[0]?.start_date ?? '';
    const sb = b.members[0]?.start_date ?? '';
    return sa.localeCompare(sb);
  });
}

/**
 * Group owner/manager tenant rows that share a lease cohort (overlapping co-tenants).
 * Singletons each get their own group with cohortKey `single-${id}`.
 */
export function groupOwnerTenantsByLeaseCohort(rows: OwnerTenantView[]): OwnerTenantGroup[] {
  const consumed = new Set<number>();
  const out: OwnerTenantGroup[] = [];
  for (const r of rows) {
    if (consumed.has(r.id)) continue;
    const cid = r.lease_cohort_id;
    if (cid && (r.cohort_member_count ?? 1) > 1) {
      const members = rows.filter((x) => x.lease_cohort_id === cid);
      members.forEach((m) => consumed.add(m.id));
      out.push({ cohortKey: cid, members });
    } else {
      consumed.add(r.id);
      out.push({ cohortKey: `single-${r.id}`, members: [r] });
    }
  }
  return sortTenantGroups(out);
}

export function isSharedLeaseGroup(group: OwnerTenantGroup): boolean {
  return group.members.length > 1;
}

export function formatOwnerTenantGroupNames(group: OwnerTenantGroup): string {
  return group.members.map((m) => m.tenant_name || m.tenant_email || '—').join(' · ');
}

/** Display names for co-tenant peers on the tenant dashboard (`/dashboard/tenant/unit`). */
export function formatCoTenantPeerLine(peers: Array<{ name?: string | null; email?: string | null }>): string {
  return peers.map((p) => (p.name || p.email || '').trim() || '—').join(' · ');
}

export type LiveTenantRowGroup = { cohortKey: string; rows: LiveTenantAssignmentInfo[] };

export function groupLiveTenantRowsByCohort(rows: LiveTenantAssignmentInfo[]): LiveTenantRowGroup[] {
  const byCid = new Map<string, LiveTenantAssignmentInfo[]>();
  const out: LiveTenantRowGroup[] = [];
  for (const r of rows) {
    const cid = r.lease_cohort_id;
    const n = r.lease_cohort_member_count ?? 1;
    if (cid && n > 1) {
      if (!byCid.has(cid)) byCid.set(cid, []);
      byCid.get(cid)!.push(r);
    }
  }
  const inCohort = new Set<string>();
  for (const [ck, cluster] of byCid) {
    cluster.forEach((r) =>
      inCohort.add([r.assignment_id ?? '', r.stay_id ?? '', r.tenant_email ?? '', r.unit_label].join('|')),
    );
    out.push({ cohortKey: ck, rows: cluster });
  }
  for (const r of rows) {
    const cid = r.lease_cohort_id;
    const n = r.lease_cohort_member_count ?? 1;
    if (cid && n > 1) continue;
    const key = [r.assignment_id ?? '', r.stay_id ?? '', r.tenant_email ?? '', r.unit_label].join('|');
    if (inCohort.has(key)) continue;
    out.push({
      cohortKey: `single-${r.assignment_id ?? r.stay_id ?? r.tenant_email ?? key}`,
      rows: [r],
    });
  }
  return out.sort((a, b) => {
    const ua = a.rows[0]?.unit_label ?? '';
    const ub = b.rows[0]?.unit_label ?? '';
    if (ua !== ub) return ua.localeCompare(ub, undefined, { numeric: true });
    return (a.rows[0]?.start_date ?? '').localeCompare(b.rows[0]?.start_date ?? '');
  });
}
