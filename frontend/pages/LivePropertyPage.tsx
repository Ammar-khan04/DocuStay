import React, { useState, useEffect } from 'react';
import {
  authApi,
  dashboardApi,
  propertiesApi,
  publicApi,
  openLivePoaPdfInNewTab,
  resolveBackendMediaUrl,
  type LiveCurrentGuestInfo,
  type LiveInvitationSummary,
  type LiveOwnerInfo,
  type LivePropertyManagerInfo,
  type LiveLogEntry,
  type LivePropertyInfo,
  type LivePropertyPagePayload,
  type LiveTenantAssignmentInfo,
  type OwnerTenantView,
  type UserSession,
  isPropertyTenantInviteKind,
} from '../services/api';
import { formatCoTenantPeerLine, groupLiveTenantRowsByCohort } from '../utils/leaseCohortGroups';
import { formatCalendarDate, formatDateTimeLocal, getTodayLocal, parseForDisplay } from '../utils/dateUtils';
import { scrubAuditLogStateChangeParagraph } from '../utils/auditLogMessage';
import { PROPERTY_INVITATION_COUNTS_FOOTNOTE, propertyInvitationCountsLine } from '../utils/propertyInvitationSummary';
import { JURISDICTION_CONTEXT_DISCLAIMER } from '../utils/jurisdictionUiCopy';

function stayIsTenant(stay: Pick<LiveCurrentGuestInfo, 'stay_kind'>): boolean {
  return (stay.stay_kind ?? 'guest').toLowerCase() === 'tenant';
}

function inviteIsTenant(inv: Pick<LiveInvitationSummary, 'invitation_kind'>): boolean {
  return isPropertyTenantInviteKind(inv.invitation_kind);
}

function statusDisplay(status: string): string {
  const s = (status || 'vacant').toLowerCase();
  if (s === 'vacant') return 'VACANT';
  if (s === 'occupied') return 'OCCUPIED';
  if (s === 'unconfirmed') return 'UNCONFIRMED';
  return 'UNKNOWN';
}

/** Same badge text / tone / detail as `propertyStatusSummary` on OwnerDashboard for multi-unit. */
function livePropertyOccupancySummary(prop: LivePropertyInfo): {
  badgeText: string;
  badgeTone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown';
  detailText: string | null;
} {
  const status = (prop.occupancy_status || 'vacant').toLowerCase();
  const badgeTone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown' =
    status === 'occupied'
      ? 'occupied'
      : status === 'vacant'
        ? 'vacant'
        : status === 'unconfirmed'
          ? 'unconfirmed'
          : 'unknown';

  if (prop.is_multi_unit) {
    const occ = prop.occupied_unit_count ?? null;
    const vac = prop.vacant_unit_count ?? null;
    const parts: string[] = [];
    if (occ != null) parts.push(`${occ} occupied`);
    if (vac != null) parts.push(`${vac} vacant`);
    const badgeText = parts.length > 0 ? parts.join(' · ') : 'MULTI-UNIT';
    return { badgeText, badgeTone, detailText: parts.length > 0 ? parts.join(' • ') : null };
  }

  return { badgeText: statusDisplay(prop.occupancy_status || 'vacant'), badgeTone, detailText: null };
}

function liveOccupancyBadgeClasses(tone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown'): string {
  switch (tone) {
    case 'occupied':
      return 'bg-emerald-100 text-emerald-800';
    case 'vacant':
      return 'bg-slate-200 text-slate-700';
    case 'unconfirmed':
      return 'bg-amber-100 text-amber-800';
    default:
      return 'bg-slate-100 text-slate-600';
  }
}

function liveOccupancyBadgeDotClasses(tone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown'): string {
  switch (tone) {
    case 'occupied':
      return 'bg-emerald-500';
    case 'vacant':
      return 'bg-slate-400';
    case 'unconfirmed':
      return 'bg-amber-500';
    default:
      return 'bg-slate-400';
  }
}

function buildHeaderUnitStatusBadges(
  prop: LivePropertyInfo,
  unitLabelScopeSet?: Set<string> | null,
  strictScoped: boolean = false,
): Array<{ label: string; tone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown' }> {
  const scope = new Set([...(unitLabelScopeSet ?? new Set<string>())].map((s) => (s || '').trim()).filter(Boolean));
  if (strictScoped && scope.size === 0) return [];
  const unitStatuses = (prop.unit_statuses ?? [])
    .filter((u) => scope.size === 0 || scope.has((u.unit_label || '').trim()))
    .map((u) => {
      const raw = (u.occupancy_status || '').trim().toLowerCase();
      const tone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown' =
        raw === 'occupied' || raw === 'vacant' || raw === 'unconfirmed' ? raw : 'unknown';
      const unitLabel = (u.unit_label || '').trim() || '—';
      return { label: `Unit ${unitLabel} · ${statusDisplay(raw || 'unknown')}`, tone };
    });
  if (unitStatuses.length > 0) return unitStatuses;
  return [
    {
      label: `Unit 1 · ${statusDisplay(prop.occupancy_status || 'vacant')}`,
      tone: (['occupied', 'vacant', 'unconfirmed'].includes((prop.occupancy_status || '').toLowerCase())
        ? (prop.occupancy_status || '').toLowerCase()
        : 'unknown') as 'occupied' | 'vacant' | 'unconfirmed' | 'unknown',
    },
  ];
}

/** When the verified owner opens their own live link: occupancy copy is tenant vs owner residence only (no guest wording). */
function buildOwnerOwnLiveOccupancyContext(
  occupancyStatus: string | undefined,
  ownerOccupied: boolean | undefined,
  tenantCheckedInStayCount: number,
  tenantAssignmentRowCount: number,
): string {
  const occ = (occupancyStatus || 'unknown').toLowerCase();
  const ownerOcc = Boolean(ownerOccupied);

  if (occ === 'vacant') {
    if (tenantCheckedInStayCount > 0) {
      return (
        'Vacant on the property record while checked-in tenant stay(s) still appear on this page — ' +
        'verify the tenant section below.'
      );
    }
    if (tenantAssignmentRowCount > 0) {
      return (
        'Vacant on the property record while tenant assignment row(s) still appear below — ' +
        'verify dates and unit against your records.'
      );
    }
    return (
      'Vacant — no active tenant assignment is shown on this page. ' +
      'Any other occupancy activity is managed in your owner dashboard, not summarized here.'
    );
  }

  if (occ === 'unconfirmed') {
    return (
      'Unconfirmed — occupancy has not been confirmed on the property record. ' +
      'Use tenant invitation states and the audit timeline below to verify.'
    );
  }

  if (occ === 'unknown') {
    return 'Unknown — occupancy has not been classified on the property record.';
  }

  const bits: string[] = [];
  if (tenantCheckedInStayCount > 0) {
    bits.push(
      `${tenantCheckedInStayCount} checked-in tenant stay${tenantCheckedInStayCount !== 1 ? 's' : ''}`,
    );
  }
  if (tenantAssignmentRowCount > 0 && tenantCheckedInStayCount === 0) {
    bits.push(
      `active tenant assignment${tenantAssignmentRowCount !== 1 ? 's' : ''} on file (${tenantAssignmentRowCount})`,
    );
  }

  if (bits.length > 0) {
    let lead = `Occupied — ${bits.join('; ')}.`;
    if (ownerOcc) {
      lead += ' You have also listed this address as a primary residence on file.';
    } else {
      lead += ' See tenant sections below for names and dates.';
    }
    return lead;
  }

  if (ownerOcc) {
    return (
      'Occupied — owner primary residence. This address is listed as your primary residence on file. ' +
      'No checked-in tenant stay or tenant assignment appears on this page.'
    );
  }

  return (
    'Occupied on the property record — no checked-in tenant stay or tenant assignment appears on this page. ' +
    'Verify tenant invitation states and the audit timeline below.'
  );
}

function tenantAssignmentDisplayName(row: LiveTenantAssignmentInfo): string {
  return (row.tenant_full_name || row.tenant_email || '—').trim() || '—';
}

function tenantLeaseInviteResolvedSummary(rows: LiveTenantAssignmentInfo[]): string {
  const labels = rows.map((r) => (r.lease_invite_resolved_status || '').trim()).filter(Boolean);
  if (!labels.length) return '—';
  return [...new Set(labels)].join(' · ');
}

function resolvedLeaseStatusKey(row: LiveTenantAssignmentInfo): 'active' | 'accepted' | 'pending' | null {
  const resolved = (row.lease_invite_resolved_status || '').trim().toLowerCase();
  if (!resolved) {
    // Backend sometimes omits the resolved label for assignment rows; infer from assignment window.
    if (row.assignment_id != null && row.assignment_id > 0 && row.start_date) {
      const today = getTodayLocal();
      const start = leaseCalendarYmd(row.start_date);
      const end = leaseCalendarYmd(row.end_date);
      if (start && today < start) return 'accepted';
      if (calendarDateInLeaseWindow(today, row.start_date, row.end_date)) return 'active';
      if (end && today > end) return null;
    }
    return null;
  }
  // Backend resolver labels are phrases (e.g. "Active lease", "Accepted — outside active lease window today").
  if (resolved.includes('pending')) return 'pending';
  if (resolved.includes('accepted')) return 'accepted';
  if (resolved.includes('active')) return 'active';
  if (resolved.includes('expired') || resolved.includes('cancelled') || resolved.includes('revoked')) {
    return null;
  }
  return null;
}

function leaseInviteResolvedIsActiveOrAccepted(row: LiveTenantAssignmentInfo): boolean {
  const key = resolvedLeaseStatusKey(row);
  return key === 'active' || key === 'accepted';
}

/**
 * Tenant live page: show every shared-lease cohort row in summary / record trail when at least one
 * member is active or accepted (peers may still be pending registration).
 */
function includeTenantSummaryCohortPeerRow(
  row: LiveTenantAssignmentInfo,
  scoped: LiveTenantAssignmentInfo[],
  viewerIsTenant: boolean,
): boolean {
  if (leaseInviteResolvedIsActiveOrAccepted(row)) return true;
  if (!viewerIsTenant) return false;
  const cid = (row.lease_cohort_id ?? '').trim();
  const n = row.lease_cohort_member_count ?? 1;
  if (!cid || n < 2) return false;
  const cohortRows = scoped.filter((r) => (r.lease_cohort_id ?? '').trim() === cid);
  if (cohortRows.length < 2) return false;
  return cohortRows.some((r) => leaseInviteResolvedIsActiveOrAccepted(r));
}

function leaseStatusBadgeForRow(row: LiveTenantAssignmentInfo): { label: 'Active' | 'Accepted' | 'Pending'; className: string } {
  const key = resolvedLeaseStatusKey(row);
  if (key === 'active') {
    return { label: 'Active', className: 'bg-emerald-100 text-emerald-800 border border-emerald-200' };
  }
  if (key === 'pending') {
    return { label: 'Pending', className: 'bg-amber-100 text-amber-800 border border-amber-200' };
  }
  return { label: 'Accepted', className: 'bg-sky-100 text-sky-800 border border-sky-200' };
}

/** Owner dashboard merge rows omit API resolver strings — derive pending copy from lane fields (aligned with backend `public_label`). */
function leaseInviteResolvedStatusFromOwnerTenantView(row: OwnerTenantView): string | undefined {
  const inv = row.invite_status;
  const asg = row.assignment_status;
  const overall = row.status;
  if (inv === 'pending' || asg === 'pending') return 'Pending Record';
  if (overall === 'pending' || overall === 'pending_signup') return 'Pending Record';
  return undefined;
}

/** Unit cards: show compact "Pending" when resolver signals pending (avoid bare em dash). */
function unitCardLeaseInviteResolvedDisplay(line: string): string {
  const trimmed = line.trim();
  const lower = trimmed.toLowerCase();
  if (lower === 'pending invitation' || lower.startsWith('pending')) return 'Pending';
  return trimmed;
}

/** Resolver omitted active/accepted badge but tenant lease invite is still pending on payload invitations. */
function liveTenantAssignmentFallbackShowsPending(
  row: LiveTenantAssignmentInfo,
  tenantInvitations: LiveInvitationSummary[],
  todayYmd: string,
  guestOpenStayInviteCodes: Set<string>,
): boolean {
  if ((row.lease_invite_resolved_status || '').trim()) return false;
  if (resolvedLeaseStatusKey(row) != null) return false;
  const email = normalizeEmail(row.tenant_email || '');
  if (!email) return false;
  return tenantInvitations.some((inv) => {
    const lab = (inv.guest_label || '').trim();
    if (!lab.includes('@') || normalizeEmail(lab) !== email) return false;
    return resolveInvitationDisplayStatus(inv, todayYmd, guestOpenStayInviteCodes) === 'pending';
  });
}

function leaseStatusBadgesFromSummary(tenantSummaryLeaseInviteLine: string): Array<'Active' | 'Accepted'> {
  const normalized = (tenantSummaryLeaseInviteLine || '').trim().toLowerCase();
  if (!normalized || normalized === '—') return [];
  const out: Array<'Active' | 'Accepted'> = [];
  if (normalized.includes('active')) out.push('Active');
  if (normalized.includes('accepted')) out.push('Accepted');
  return out;
}

function tenantLeasePeriodLabel(row: LiveTenantAssignmentInfo): string {
  const start = formatCalendarDate(row.start_date);
  if (!row.end_date) return `${start} – Open-ended`;
  return `${start} – ${formatCalendarDate(row.end_date)}`;
}

function normalizeEmail(s: string): string {
  return (s || '').trim().toLowerCase();
}

/** Remove ``dms`` as a word/token from live-page evidence copy (defense in depth vs API text). */
function scrubLiveEvidenceText(raw: string | null | undefined): string {
  return (raw || '')
    .replace(/\bdms[\w.-]*\b/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function logEntryMentionsAnyUnitLabel(entry: LiveLogEntry, unitLabels: Set<string>): boolean {
  const labels = new Set([...(unitLabels ?? new Set<string>())].map((s) => (s || '').trim().toLowerCase()).filter(Boolean));
  if (labels.size === 0) return true;
  const haystack = [
    entry.title,
    entry.message,
    entry.category,
    entry.business_meaning_on_record,
    entry.trigger_on_record,
    entry.state_change_on_record,
  ]
    .map((v) => (v || '').toLowerCase())
    .join(' ');
  const unitRe = /\bunit\s*([a-z0-9-]+)\b/gi;
  const mentions: string[] = [];
  let m: RegExpExecArray | null = null;
  while ((m = unitRe.exec(haystack)) !== null) {
    mentions.push((m[1] || '').trim().toLowerCase());
  }
  if (mentions.some((mLabel) => labels.has(mLabel))) return true;
  // Plain labels (e.g. "for 101") — presence and other copy often omit the word "Unit".
  for (const lab of labels) {
    if (!lab) continue;
    if (lab.length >= 3) {
      if (haystack.includes(lab)) return true;
    } else {
      try {
        const re = new RegExp(`(?:^|[^a-z0-9])${lab.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:[^a-z0-9]|$)`, 'i');
        if (re.test(haystack)) return true;
      } catch {
        /* ignore invalid pattern */
      }
    }
  }
  return false;
}

/** Tenant/guest scoped views: presence timeline lines must be tenant or guest lane (never owner/manager). */
function presenceEntryAllowedForResidentScopedView(entry: LiveLogEntry): boolean {
  if ((entry.category || '').toLowerCase().trim() !== 'presence') return true;
  const r = (entry.actor_role || '').toLowerCase().trim();
  return r === 'tenant' || r === 'guest';
}

/** Strip owner portfolio / CSV bulk copy if it appears on cached or edge payloads (API filters ledger by action_type). */
function tenantLiveTimelineEntryIsOwnerBulkOrPortfolioLeak(entry: LiveLogEntry): boolean {
  const src = (entry.event_source || '').trim().toLowerCase();
  if (src === 'import (csv)') return true;
  const blob = `${entry.title || ''} ${entry.message || ''} ${entry.business_meaning_on_record || ''}`.toLowerCase();
  if (/\bcsv\s+bulk\b/.test(blob) || /\bbulk\s+upload\b/.test(blob)) return true;
  if (blob.includes('ownership proof')) return true;
  if (blob.includes('pending tenant:') && blob.includes('invitation email')) return true;
  if (blob.includes('lease extension offered')) return true;
  return false;
}

function ownerLiveShouldHidePresenceTimelineEntry(entry: LiveLogEntry): boolean {
  const blob = [
    entry.category,
    entry.title,
    entry.message,
    entry.business_meaning_on_record,
    entry.trigger_on_record,
    entry.state_change_on_record,
  ]
    .map((v) => (v || '').toLowerCase())
    .join(' ');
  return /presence|resident_presence|stay_presence|check.?in|check.?out|checked in|checked out/i.test(blob);
}

/** Renders server-resolved actor (role + name + email); timeline text may still contain legacy wording. */
function LiveAuditActorAttribution({ entry }: { entry: LiveLogEntry }) {
  const role = (entry.actor_role || '').toLowerCase();
  const label = scrubLiveEvidenceText((entry.actor_role_label || '').trim());
  const name = scrubLiveEvidenceText((entry.actor_name || '').trim());
  const email = scrubLiveEvidenceText((entry.actor_email || '').trim());
  const eventSrc = scrubLiveEvidenceText((entry.event_source || '').trim());
  if (role === 'system') {
    return (
      <div className="text-xs text-slate-600 mt-1 space-y-0.5">
        <p>Actor: System</p>
        {eventSrc ? <p>Event source: {eventSrc}</p> : null}
      </div>
    );
  }
  if (!label && !name && !email && !eventSrc) {
    return null;
  }
  return (
    <div className="text-xs text-slate-600 mt-1 space-y-0.5">
      <p>
        <span className="font-semibold text-slate-800">{label || 'Actor'}</span>
        {name ? <span>: {name}</span> : null}
        {email ? <span className="text-slate-500 break-all"> · {email}</span> : null}
      </p>
      {eventSrc ? <p>Event source: {eventSrc}</p> : null}
    </div>
  );
}

/** Shown under condensed and full audit timelines on the live page. */
function LiveAuditTimelineRecordFootnote() {
  return (
    <p className="mt-4 pt-4 border-t border-violet-100 text-xs text-slate-600 leading-relaxed">
      This audit timeline is a chronological record of user-provided information and system-logged events. It is not a
      statement of the legal situation at the property.
    </p>
  );
}

/** Top-of-page framing for the public live / verification view. */
function LivePageRecordFramingBanner() {
  return (
    <div
      role="note"
      className="rounded-xl border border-indigo-200/90 bg-indigo-50/90 px-4 py-3 sm:px-5 sm:py-3.5 shadow-sm print:border-slate-300 print:bg-slate-50"
    >
      <p className="text-sm text-slate-800 leading-relaxed">
        This record reflects user-provided information and system-generated logs. It is not a legal determination of
        occupancy status, tenancy, or rights. DocuStay does not verify, adjudicate, or enforce legal claims.
      </p>
    </div>
  );
}

function normalizeLooseName(s: string): string {
  return (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function dedupeLiveTenantAssignments(rows: LiveTenantAssignmentInfo[]): LiveTenantAssignmentInfo[] {
  const seen = new Set<string>();
  const out: LiveTenantAssignmentInfo[] = [];
  for (const row of rows) {
    /** Prefer stable DB ids so co-tenants on the same lease window are never collapsed together. */
    let key: string;
    if (row.assignment_id != null && Number(row.assignment_id) > 0) {
      key = `assignment:${row.assignment_id}`;
    } else if (row.stay_id != null && Number(row.stay_id) > 0) {
      key = `stay:${row.stay_id}`;
    } else {
      key = [
        (row.unit_label || '').trim(),
        normalizeEmail(row.tenant_email || ''),
        normalizeLooseName(row.tenant_full_name || ''),
        (row.start_date || '').trim(),
        (row.end_date || '').trim(),
        String(row.lease_cohort_id ?? ''),
      ].join('|');
    }
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

/** Ordered labels for owner multi-unit cards: API rows first, then assignments; pad numeric 1..unit_count when counts imply missing vacant rows. */
function collectOwnerUnitLabelsForOwnerLive(
  prop: LivePropertyInfo,
  assignmentRows: LiveTenantAssignmentInfo[],
): string[] {
  const deduped = dedupeLiveTenantAssignments(assignmentRows);
  const fromAssign = [...new Set(deduped.map((r) => (r.unit_label || '').trim()).filter(Boolean))];

  const seen = new Set<string>();
  const ordered: string[] = [];

  for (const u of prop.unit_statuses ?? []) {
    const lab = (u.unit_label || '').trim() || '—';
    if (!seen.has(lab)) {
      seen.add(lab);
      ordered.push(lab);
    }
  }

  for (const lab of fromAssign.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))) {
    if (!seen.has(lab)) {
      seen.add(lab);
      ordered.push(lab);
    }
  }

  const uc = prop.unit_count ?? 0;
  if (
    uc > 0 &&
    ordered.length < uc &&
    (ordered.length === 0 || ordered.every((l) => /^\d+$/.test(l)))
  ) {
    for (let i = 1; i <= uc; i++) {
      const lab = String(i);
      if (!seen.has(lab)) {
        seen.add(lab);
        ordered.push(lab);
      }
    }
  }

  return [...ordered].sort((a, b) => {
    if (/^\d+$/.test(a) && /^\d+$/.test(b)) {
      return parseInt(a, 10) - parseInt(b, 10);
    }
    return a.localeCompare(b, undefined, { numeric: true });
  });
}

/** Owner live page: one card per unit (vacant or occupied); leases grouped by unit_label. */
function buildOwnerUnitSummaryCards(
  prop: LivePropertyInfo,
  assignmentRows: LiveTenantAssignmentInfo[],
): Array<{
  unitLabel: string;
  tone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown';
  statusLabel: string;
  leases: LiveTenantAssignmentInfo[];
}> {
  if (!prop.is_multi_unit) return [];

  const labels = collectOwnerUnitLabelsForOwnerLive(prop, assignmentRows);
  if (labels.length === 0) return [];

  const deduped = dedupeLiveTenantAssignments(assignmentRows);
  const byUnit = new Map<string, LiveTenantAssignmentInfo[]>();
  for (const r of deduped) {
    const ul = (r.unit_label || '').trim() || '—';
    if (!byUnit.has(ul)) byUnit.set(ul, []);
    byUnit.get(ul)!.push(r);
  }

  const statusMap = new Map<string, string>();
  for (const u of prop.unit_statuses ?? []) {
    const lab = (u.unit_label || '').trim() || '—';
    statusMap.set(lab, ((u.occupancy_status || 'vacant').trim() || 'vacant').toLowerCase());
  }

  return labels.map((label) => {
    const occRaw = statusMap.has(label) ? statusMap.get(label)! : 'vacant';
    const raw = occRaw.toLowerCase();
    const tone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown' =
      raw === 'occupied' || raw === 'vacant' || raw === 'unconfirmed' ? raw : 'unknown';
    const statusLabel = statusDisplay(occRaw);
    const leases = byUnit.get(label) ?? [];
    return { unitLabel: label, tone, statusLabel, leases };
  });
}

/** Map owner dashboard tenant row to live-page assignment shape. Display-only. */
function ownerTenantViewToLiveAssignmentInfo(row: OwnerTenantView): LiveTenantAssignmentInfo {
  const created = row.created_at || new Date().toISOString();
  const start =
    (row.start_date && row.start_date.trim()) ||
    (created.includes('T') ? created.split('T')[0] : created) ||
    new Date().toISOString().split('T')[0];
  return {
    assignment_id: row.id > 0 ? row.id : null,
    stay_id: null,
    unit_label: (row.unit_label && row.unit_label.trim()) || '—',
    tenant_full_name: row.tenant_name || null,
    tenant_email: row.tenant_email || null,
    start_date: start,
    end_date: row.end_date ?? null,
    created_at: created,
    lease_cohort_id: row.lease_cohort_id ?? null,
    lease_cohort_member_count: row.cohort_member_count ?? null,
    lease_invite_resolved_status: leaseInviteResolvedStatusFromOwnerTenantView(row) ?? undefined,
  };
}

function tenantRowMatchesViewer(row: LiveTenantAssignmentInfo, viewer: UserSession): boolean {
  const ve = normalizeEmail(viewer.email);
  if (row.tenant_email && normalizeEmail(row.tenant_email) === ve) return true;
  const assignee = (row.tenant_full_name || '').trim();
  if (assignee && normalizeLooseName(assignee) === normalizeLooseName(viewer.user_name)) return true;
  return false;
}

function guestStayMatchesViewer(
  stay: LiveCurrentGuestInfo,
  invitations: LiveInvitationSummary[],
  viewer: UserSession,
): boolean {
  const ve = normalizeEmail(viewer.email);
  const inv = stay.invitation_code
    ? invitations.find((i) => i.invitation_code === stay.invitation_code)
    : undefined;
  const label = (inv?.guest_label || '').trim();
  if (label && label.includes('@') && normalizeEmail(label) === ve) return true;
  if (normalizeLooseName(stay.guest_name) === normalizeLooseName(viewer.user_name)) return true;
  if (label && normalizeLooseName(label) === normalizeLooseName(viewer.user_name)) return true;
  return false;
}

/** Live page: tenant/guest authorization label from their invitation; other roles see "-". */
function invitationMatchesViewer(
  inv: LiveInvitationSummary,
  viewer: UserSession,
  kind: 'tenant' | 'guest',
): boolean {
  if (kind === 'tenant' && !inviteIsTenant(inv)) return false;
  if (kind === 'guest' && inviteIsTenant(inv)) return false;
  const ve = normalizeEmail(viewer.email);
  const label = (inv.guest_label || '').trim();
  if (label && label.includes('@') && normalizeEmail(label) === ve) return true;
  if (label && normalizeLooseName(label) === normalizeLooseName(viewer.user_name || '')) return true;
  return false;
}

function pickViewerInvitation(
  invitations: LiveInvitationSummary[],
  viewer: UserSession,
  kind: 'tenant' | 'guest',
  preferredCode?: string | null,
): LiveInvitationSummary | null {
  if (preferredCode) {
    const byCode = invitations.find((i) => i.invitation_code === preferredCode);
    if (byCode && invitationMatchesViewer(byCode, viewer, kind)) return byCode;
  }
  const matches = invitations.filter((i) => invitationMatchesViewer(i, viewer, kind));
  return matches[0] ?? null;
}

/** Normalize API date strings to local calendar YYYY-MM-DD (matches tenant dashboard lease logic). */
function leaseCalendarYmd(isoOrYmd: string | null | undefined): string | null {
  if (isoOrYmd == null || String(isoOrYmd).trim() === '') return null;
  const t = String(isoOrYmd).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return t;
  if (/^\d{4}-\d{2}-\d{2}/.test(t)) return t.slice(0, 10);
  const d = parseForDisplay(t);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Guest stays currently on the live payload (not checked out) → treat linked invite as accepted if the row lags. */
function collectGuestOpenStayInvitationCodes(stays: LiveCurrentGuestInfo[]): Set<string> {
  const out = new Set<string>();
  for (const stay of stays) {
    if (stayIsTenant(stay)) continue;
    if (stay.checked_out_at) continue;
    const c = (stay.invitation_code ?? '').trim().toUpperCase();
    if (c) out.add(c);
  }
  return out;
}

function resolveInvitationDisplayStatus(
  inv: LiveInvitationSummary,
  _todayYmd: string,
  guestOpenStayInviteCodes?: Set<string>,
): 'pending' | 'accepted' | 'active' | 'expired' | 'cancelled' {
  // Source of truth is backend `resolve_invitation_display_status` (plus current-stay linkage).
  const st = (inv.status || 'pending').trim().toLowerCase();
  if (st === 'active' || st === 'accepted' || st === 'expired' || st === 'cancelled') return st;
  const code = (inv.invitation_code ?? '').trim().toUpperCase();
  if (code && guestOpenStayInviteCodes?.has(code)) return 'active';
  return 'pending';
}

/** Associated unit for the invitation-states table (payload ``unit_label``; sole unit when single-building). */
function liveInvitationTableUnitLabel(inv: LiveInvitationSummary, propertyIsMultiUnit: boolean): string {
  const u = (inv.unit_label || '').trim();
  if (u) return u;
  if (!propertyIsMultiUnit) return '1';
  return '—';
}

function mapInvitationToAuthorizationLabel(
  inv: LiveInvitationSummary,
  todayYmd: string,
  guestOpenStayInviteCodes?: Set<string>,
): string {
  const resolved = resolveInvitationDisplayStatus(inv, todayYmd, guestOpenStayInviteCodes);
  if (resolved === 'cancelled') return 'CANCELLED';
  if (resolved === 'active') return 'ACTIVE';
  if (resolved === 'accepted') return 'ACCEPTED';
  if (resolved === 'expired') return 'EXPIRED';
  return 'PENDING';
}

function liveInviteStatusDisplayLabel(
  inv: LiveInvitationSummary,
  todayYmd: string,
  guestOpenStayInviteCodes?: Set<string>,
): string {
  const s = resolveInvitationDisplayStatus(inv, todayYmd, guestOpenStayInviteCodes);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function liveInviteStatusDisplayClass(
  inv: LiveInvitationSummary,
  todayYmd: string,
  guestOpenStayInviteCodes?: Set<string>,
): string {
  const s = resolveInvitationDisplayStatus(inv, todayYmd, guestOpenStayInviteCodes);
  if (s === 'active') return 'bg-emerald-100 text-emerald-800';
  if (s === 'accepted') return 'bg-sky-100 text-sky-800';
  if (s === 'cancelled') return 'bg-orange-100 text-orange-900';
  if (s === 'expired') return 'bg-red-100 text-red-800';
  if (s === 'pending') return 'bg-amber-100 text-amber-800';
  return 'bg-slate-100 text-slate-700';
}

type UnitInviteCountCtx = {
  tenantInvitations: LiveInvitationSummary[];
  todayYmd: string;
  guestOpenStayInviteCodes: Set<string>;
  /** When false, tenant invites without ``unit_label`` still match the sole unit row (owner / QDL). */
  propertyIsMultiUnit?: boolean;
};

function resolvedLeaseStatusKeyWithInviteFallback(
  row: LiveTenantAssignmentInfo,
  ctx?: UnitInviteCountCtx,
): 'active' | 'accepted' | 'pending' | null {
  let resolved = resolvedLeaseStatusKey(row);
  if (resolved == null && ctx) {
    if (
      liveTenantAssignmentFallbackShowsPending(row, ctx.tenantInvitations, ctx.todayYmd, ctx.guestOpenStayInviteCodes)
    ) {
      resolved = 'pending';
    }
  }
  return resolved;
}

function invitationAssigneeMatchesLiveAssignmentRow(
  inv: LiveInvitationSummary,
  row: LiveTenantAssignmentInfo,
): boolean {
  const lab = (inv.guest_label || '').trim();
  if (!lab) return false;
  const re = normalizeEmail(row.tenant_email || '');
  if (lab.includes('@')) {
    return !!re && normalizeEmail(lab) === re;
  }
  const rn = normalizeLooseName(row.tenant_full_name || '');
  return !!rn && normalizeLooseName(lab) === rn;
}

function liveTenantInvitationMatchesUnit(
  inv: LiveInvitationSummary,
  unitLabelNormalized: string,
  ctx: UnitInviteCountCtx,
): boolean {
  const w = unitLabelNormalized.trim();
  const u = (inv.unit_label || '').trim();
  if (u) return u === w;
  if (ctx.propertyIsMultiUnit === false && w) return true;
  return false;
}

/** Same assignee row already reflects lease/invite state — do not double-count the invitation. */
function rowCoversLiveTenantInvitationCounts(
  row: LiveTenantAssignmentInfo,
  inv: LiveInvitationSummary,
  ctx: UnitInviteCountCtx,
): boolean {
  if (!invitationAssigneeMatchesLiveAssignmentRow(inv, row)) return false;
  const rk = resolvedLeaseStatusKeyWithInviteFallback(row, ctx);
  return rk === 'active' || rk === 'accepted' || rk === 'pending';
}

/** Pending tenant invitations on this unit that match the assignee row (for owner unit summary). */
function pendingTenantInvitationsMatchingLiveAssignment(
  row: LiveTenantAssignmentInfo,
  unitLabel: string,
  ctx: UnitInviteCountCtx,
): LiveInvitationSummary[] {
  return ctx.tenantInvitations.filter((inv) => {
    if (!inviteIsTenant(inv)) return false;
    if (!liveTenantInvitationMatchesUnit(inv, unitLabel, ctx)) return false;
    if (!invitationAssigneeMatchesLiveAssignmentRow(inv, row)) return false;
    return resolveInvitationDisplayStatus(inv, ctx.todayYmd, ctx.guestOpenStayInviteCodes) === 'pending';
  });
}

function buildUnitActiveAcceptedInviteCounts(
  unitLabel: string,
  rows: LiveTenantAssignmentInfo[],
  ctx?: UnitInviteCountCtx,
): { active: number; accepted: number; pending: number } {
  const normalizedUnitLabel = unitLabel.trim();
  if (!normalizedUnitLabel) return { active: 0, accepted: 0, pending: 0 };

  const unitRows = rows.filter((row) => (row.unit_label || '').trim() === normalizedUnitLabel);

  let active = 0;
  let accepted = 0;
  let pending = 0;
  for (const row of unitRows) {
    const resolved = resolvedLeaseStatusKeyWithInviteFallback(row, ctx);
    if (resolved === 'active') active += 1;
    else if (resolved === 'accepted') accepted += 1;
    else if (resolved === 'pending') pending += 1;
  }

  if (ctx) {
    for (const inv of ctx.tenantInvitations) {
      if (!inviteIsTenant(inv)) continue;
      if (!liveTenantInvitationMatchesUnit(inv, normalizedUnitLabel, ctx)) continue;
      if (unitRows.some((row) => rowCoversLiveTenantInvitationCounts(row, inv, ctx))) continue;
      const st = resolveInvitationDisplayStatus(inv, ctx.todayYmd, ctx.guestOpenStayInviteCodes);
      if (st === 'pending') pending += 1;
      else if (st === 'active') active += 1;
      else if (st === 'accepted') accepted += 1;
    }
  }

  return { active, accepted, pending };
}

function unitLabelFromHeaderBadgeLabel(label: string): string | null {
  const m = label.match(/^Unit\s+(.+?)\s+·/i);
  if (!m) return null;
  const out = (m[1] || '').trim();
  return out || null;
}

/** Inclusive local calendar-day window. Uses only dates tied to the resolved stay/invitation (not other assignment rows). */
function calendarDateInLeaseWindow(todayYmd: string, startYmd: string, endYmd: string | null | undefined): boolean {
  const td = leaseCalendarYmd(todayYmd) || todayYmd.trim();
  const sd = leaseCalendarYmd(startYmd);
  if (!td || !sd) return false;
  if (td < sd) return false;
  const ed = leaseCalendarYmd(endYmd);
  if (ed && td > ed) return false;
  return true;
}

/** Manager: viewer email matches a property manager row on this live payload (active assignment on file). */
function managerHasActivePropertyAssignment(viewer: UserSession, managers: LivePropertyManagerInfo[]): boolean {
  if (viewer.user_type !== 'PROPERTY_MANAGER') return false;
  const ve = normalizeEmail(viewer.email);
  if (!ve) return false;
  return managers.some((m) => normalizeEmail(m.email) === ve);
}

/**
 * Tenant: ACTIVE lease only — today within [start_date, end_date] on an assignment row for this viewer,
 * or the same window on a matching checked-in tenant stay (single-unit / no assignment row).
 */
function tenantHasActiveLeaseOnLivePage(
  viewer: UserSession,
  todayYmd: string,
  tenantAssignmentRows: LiveTenantAssignmentInfo[],
  activeOccupants: LiveCurrentGuestInfo[],
  invitations: LiveInvitationSummary[],
): boolean {
  const inWin = (start: string | null | undefined, end: string | null | undefined) =>
    calendarDateInLeaseWindow(todayYmd, start ?? '', end);
  for (const row of tenantAssignmentRows) {
    if (tenantRowMatchesViewer(row, viewer) && inWin(row.start_date, row.end_date)) return true;
  }
  const tenantStays = activeOccupants.filter(stayIsTenant);
  const matchingStay = tenantStays.find((s) => guestStayMatchesViewer(s, invitations, viewer));
  return !!(matchingStay && inWin(matchingStay.stay_start_date, matchingStay.stay_end_date));
}

/** Guest: today within [stay_start_date, stay_end_date] on a matching current stay (authorization window only). */
function guestHasActiveStayOnLivePage(
  viewer: UserSession,
  todayYmd: string,
  activeOccupants: LiveCurrentGuestInfo[],
  invitations: LiveInvitationSummary[],
): boolean {
  const guestStays = activeOccupants.filter((g) => !stayIsTenant(g));
  const matchingStay = guestStays.find((s) => guestStayMatchesViewer(s, invitations, viewer));
  if (!matchingStay) return false;
  return calendarDateInLeaseWindow(todayYmd, matchingStay.stay_start_date, matchingStay.stay_end_date);
}

/**
 * Quick Decision / tenant card "Property authorization (page)": single resolver.
 * - Owner (verified, own property live link): ACTIVE for this snapshot.
 * - Manager: ACTIVE iff listed on this property’s manager roster (payload = active assignment on file).
 * - Tenant: ACTIVE iff lease window start <= today <= end on viewer’s assignment or occupying tenant stay.
 * - Guest: ACTIVE iff a matching current stay has start <= today <= end (invite token not used for this gate).
 */
function resolveLivePagePropertyAuthorizationDisplay(
  viewer: UserSession | null,
  invitations: LiveInvitationSummary[],
  activeOccupants: LiveCurrentGuestInfo[],
  ctx: {
    todayYmd: string;
    tenantAssignmentRows: LiveTenantAssignmentInfo[];
    propertyManagers: LivePropertyManagerInfo[];
    ownerViewingOwnLivePage: boolean;
  },
): string {
  if (!viewer) return '-';

  if (viewer.user_type === 'PROPERTY_OWNER') {
    if (!ctx.ownerViewingOwnLivePage) return '-';
    return 'ACTIVE';
  }

  if (viewer.user_type === 'PROPERTY_MANAGER') {
    return managerHasActivePropertyAssignment(viewer, ctx.propertyManagers) ? 'ACTIVE' : 'NONE';
  }

  if (viewer.user_type === 'TENANT') {
    return tenantHasActiveLeaseOnLivePage(
      viewer,
      ctx.todayYmd,
      ctx.tenantAssignmentRows,
      activeOccupants,
      invitations,
    )
      ? 'ACTIVE'
      : 'NONE';
  }

  if (viewer.user_type === 'GUEST') {
    return guestHasActiveStayOnLivePage(viewer, ctx.todayYmd, activeOccupants, invitations) ? 'ACTIVE' : 'NONE';
  }

  return '-';
}

function liveAuthBadgeClasses(label: string): string {
  if (label === '-') return 'bg-slate-100 text-slate-500 font-medium normal-case';
  const base = 'text-sm font-semibold uppercase';
  switch (label) {
    case 'NONE':
      return `bg-slate-200 text-slate-700 ${base}`;
    case 'ACTIVE':
      return `bg-emerald-100 text-emerald-800 ${base}`;
    case 'PENDING':
      return `bg-sky-100 text-sky-800 ${base}`;
    case 'CANCELLED':
      return `bg-orange-100 text-orange-900 ${base}`;
    case 'REVOKED':
      return `bg-red-100 text-red-800 ${base}`;
    case 'EXPIRED':
      return `bg-amber-100 text-amber-800 ${base}`;
    default:
      return `bg-slate-100 text-slate-700 ${base}`;
  }
}

/** Row shape returned by GET /dashboard/tenant/unit (only fields needed for live-page merge). */
type TenantDashboardUnitLeaseRow = {
  live_slug: string | null;
  unit: { id: number; unit_label: string; occupancy_status: string } | null;
  stay_start_date: string | null;
  stay_end_date: string | null;
  lease_cohort_id?: string | null;
  cohort_member_count?: number | null;
  co_tenants?: Array<{ name?: string | null; email?: string | null }>;
};

function resolvedLeaseStatusForPersonFromApiRows(
  person: { name?: string | null; email?: string | null },
  unitLabel: string,
  apiRows: LiveTenantAssignmentInfo[],
): string | null {
  const email = normalizeEmail(person.email || '');
  const name = normalizeLooseName(person.name || '');
  for (const row of apiRows) {
    if ((row.unit_label || '').trim() !== unitLabel.trim()) continue;
    const rowEmail = normalizeEmail(row.tenant_email || '');
    const rowName = normalizeLooseName(row.tenant_full_name || '');
    const emailMatch = !!email && !!rowEmail && rowEmail === email;
    const nameMatch = !!name && !!rowName && rowName === name;
    if (!emailMatch && !nameMatch) continue;
    const resolved = (row.lease_invite_resolved_status || '').trim();
    return resolved || null;
  }
  return null;
}

function resolvedLeaseStatusForPersonFromInvitations(
  person: { name?: string | null; email?: string | null },
  invitations: LiveInvitationSummary[],
  todayYmd: string,
  guestOpenStayInviteCodes: Set<string>,
): string | null {
  const email = normalizeEmail(person.email || '');
  const name = normalizeLooseName(person.name || '');
  const tenantInvs = invitations.filter(inviteIsTenant);
  let hasAccepted = false;
  for (const inv of tenantInvs) {
    const label = (inv.guest_label || '').trim();
    const labelEmail = label.includes('@') ? normalizeEmail(label) : '';
    const labelName = normalizeLooseName(label);
    const emailMatch = !!email && !!labelEmail && labelEmail === email;
    const nameMatch = !!name && !!labelName && labelName === name;
    if (!emailMatch && !nameMatch) continue;
    const resolved = resolveInvitationDisplayStatus(inv, todayYmd, guestOpenStayInviteCodes);
    if (resolved === 'active') return 'Active lease';
    if (resolved === 'accepted') hasAccepted = true;
  }
  return hasAccepted ? 'Accepted — outside active lease window today' : null;
}

/**
 * For a tenant viewing their property live link: enrich public payload rows with co-tenants from the
 * tenant dashboard lease payload (same source as TenantDashboard). Display-only; does not affect
 * Quick Decision authorization (`resolveLivePagePropertyAuthorizationDisplay`: owner self-view → ACTIVE; tenant = in-window lease/stay; guest = in-window stay; manager = on roster).
 */
function buildDisplayTenantAssignmentsForTenantLivePage(
  apiRows: LiveTenantAssignmentInfo[],
  viewer: UserSession | null,
  liveSlug: string,
  mirror: TenantDashboardUnitLeaseRow | null,
  invitations: LiveInvitationSummary[],
  todayYmd: string,
  guestOpenStayInviteCodes: Set<string>,
): LiveTenantAssignmentInfo[] {
  if (!viewer || viewer.user_type !== 'TENANT' || !mirror || (mirror.live_slug || '').trim() !== liveSlug.trim()) {
    return apiRows;
  }
  const peers = (mirror.co_tenants ?? []).filter((p) => (p.name || p.email || '').trim());
  if (!peers.length) {
    return apiRows;
  }

  const unitLabel = mirror.unit?.unit_label ?? '—';
  const start = mirror.stay_start_date ?? '';
  const end = mirror.stay_end_date ?? null;
  if (!start) {
    return apiRows;
  }

  const cohortId =
    (mirror.lease_cohort_id && String(mirror.lease_cohort_id).trim()) ||
    (mirror.unit?.id != null ? `tenant-dash-unit-${mirror.unit.id}` : null);
  if (!cohortId) {
    return apiRows;
  }

  const cohortLeaseInviteStatus =
    apiRows.find((r) => r.unit_label === unitLabel && (r.lease_invite_resolved_status || '').trim())
      ?.lease_invite_resolved_status ?? null;

  const memberCount = Math.max(mirror.cohort_member_count ?? 0, peers.length + 1);
  if (memberCount < 2) {
    return apiRows;
  }

  const rowKey = (email: string, name: string) =>
    `${normalizeEmail(email)}|${normalizeLooseName(name)}`;

  let rows: LiveTenantAssignmentInfo[] = apiRows.map((r) => {
    if (r.unit_label !== unitLabel || !tenantRowMatchesViewer(r, viewer)) {
      return r;
    }
    if (r.lease_cohort_id && (r.lease_cohort_member_count ?? 1) > 1) {
      return r;
    }
    return { ...r, lease_cohort_id: cohortId, lease_cohort_member_count: memberCount };
  });

  const createdFallback =
    rows.find((r) => tenantRowMatchesViewer(r, viewer) && r.unit_label === unitLabel)?.created_at ??
    new Date().toISOString();

  const seen = new Set(rows.map((r) => rowKey(r.tenant_email || '', r.tenant_full_name || '')));
  seen.add(rowKey(viewer.email, viewer.user_name));

  const hasViewerRow = rows.some((r) => tenantRowMatchesViewer(r, viewer) && r.unit_label === unitLabel);
  if (!hasViewerRow) {
    const viewerResolved =
      resolvedLeaseStatusForPersonFromApiRows(
        { name: viewer.user_name, email: viewer.email },
        unitLabel,
        apiRows,
      ) ??
      resolvedLeaseStatusForPersonFromInvitations(
        { name: viewer.user_name, email: viewer.email },
        invitations,
        todayYmd,
        guestOpenStayInviteCodes,
      ) ??
      null;
    rows.push({
      assignment_id: null,
      stay_id: null,
      unit_label: unitLabel,
      tenant_full_name: viewer.user_name ?? null,
      tenant_email: viewer.email ?? null,
      start_date: start,
      end_date: end,
      created_at: createdFallback,
      lease_cohort_id: cohortId,
      lease_cohort_member_count: memberCount,
      lease_invite_resolved_status: viewerResolved,
    });
  }

  for (const peer of peers) {
    const em = (peer.email || '').trim();
    const nm = (peer.name || '').trim();
    if (!em && !nm) {
      continue;
    }
    const k = rowKey(em, nm);
    if (seen.has(k)) {
      continue;
    }
    seen.add(k);
    const peerResolved =
      resolvedLeaseStatusForPersonFromApiRows(
        { name: nm, email: em },
        unitLabel,
        apiRows,
      ) ??
      resolvedLeaseStatusForPersonFromInvitations(
        { name: nm, email: em },
        invitations,
        todayYmd,
        guestOpenStayInviteCodes,
      ) ??
      null;
    rows.push({
      assignment_id: null,
      stay_id: null,
      unit_label: unitLabel,
      tenant_full_name: nm || null,
      tenant_email: em || null,
      start_date: start,
      end_date: end,
      created_at: createdFallback,
      lease_cohort_id: cohortId,
      lease_cohort_member_count: memberCount,
      lease_invite_resolved_status: peerResolved,
    });
  }

  return rows;
}

export const LivePropertyPage: React.FC<{ slug: string }> = ({ slug }) => {
  const [data, setData] = useState<LivePropertyPagePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewerSession, setViewerSession] = useState<UserSession | null>(null);
  const [tenantDashboardLeaseRow, setTenantDashboardLeaseRow] = useState<TenantDashboardUnitLeaseRow | null>(null);
  const [ownerDashboardRowsForLive, setOwnerDashboardRowsForLive] = useState<OwnerTenantView[] | null>(null);
  const [poaOpenError, setPoaOpenError] = useState<string | null>(null);
  const [poaOpening, setPoaOpening] = useState(false);

  useEffect(() => {
    if (!slug) {
      setError('This live link is incomplete. Check that you used the full URL from your host (including the property code after "live/").');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    publicApi
      .getLivePage(slug)
      .then(setData)
      .catch((e) => setError((e as Error)?.message ?? 'Failed to load'))
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    if (!authApi.getToken()) {
      setViewerSession(null);
      return;
    }
    let cancelled = false;
    authApi
      .me()
      .then((s) => {
        if (!cancelled) setViewerSession(s ?? null);
      })
      .catch(() => {
        if (!cancelled) setViewerSession(null);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    if (viewerSession?.user_type !== 'TENANT' || !slug || !authApi.getToken()) {
      setTenantDashboardLeaseRow(null);
      return;
    }
    let cancelled = false;
    dashboardApi
      .tenantUnit()
      .then((res) => {
        if (cancelled) return;
        const match = res.units.find((u) => u.live_slug != null && u.live_slug === slug);
        setTenantDashboardLeaseRow(match ?? null);
      })
      .catch(() => {
        if (!cancelled) setTenantDashboardLeaseRow(null);
      });
    return () => {
      cancelled = true;
    };
  }, [slug, viewerSession?.user_type]);

  useEffect(() => {
    const o = data?.owner as (LiveOwnerInfo & { Email?: string }) | undefined;
    const ownerNorm = typeof o?.email === 'string' ? o.email.trim() : typeof o?.Email === 'string' ? o.Email.trim() : '';
    const owns =
      viewerSession?.user_type === 'PROPERTY_OWNER' &&
      ownerNorm.length > 0 &&
      normalizeEmail(viewerSession.email) === normalizeEmail(ownerNorm);
    if (!data || !slug || loading || !owns || !authApi.getToken()) {
      setOwnerDashboardRowsForLive(null);
      return;
    }
    let cancelled = false;
    Promise.all([propertiesApi.list(), dashboardApi.ownerTenants()])
      .then(([properties, tenants]) => {
        if (cancelled) return;
        const propId = properties.find((p) => (p.live_slug || '').trim() === slug.trim())?.id;
        if (propId == null) {
          setOwnerDashboardRowsForLive([]);
          return;
        }
        setOwnerDashboardRowsForLive(tenants.filter((t) => t.property_id === propId));
      })
      .catch(() => {
        if (!cancelled) setOwnerDashboardRowsForLive(null);
      });
    return () => {
      cancelled = true;
    };
  }, [slug, viewerSession, data, loading]);

  const viewerIsGuest = viewerSession?.user_type === 'GUEST';
  const viewerIsOwner = viewerSession?.user_type === 'PROPERTY_OWNER';
  const viewerIsTenant = viewerSession?.user_type === 'TENANT';
  const tenantLinkAudience = (data?.link_audience || '').toLowerCase() === 'tenant';
  const guestLinkAudience = (data?.link_audience || '').toLowerCase() === 'guest';
  const tenantScopeEnabled = viewerIsTenant || tenantLinkAudience || guestLinkAudience;

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50/70 via-white to-slate-100/60 flex items-center justify-center p-6 print:bg-white">
        <div className="text-center">
          <div className="inline-block w-10 h-10 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-4" />
          <p className="text-slate-700 font-medium">Loading property information…</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    const message = error ?? 'This link may be invalid or no longer available.';
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50/70 via-white to-slate-100/60 flex items-center justify-center p-6 print:bg-white">
        <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border border-indigo-100 p-10 text-center">
          <div className="w-14 h-14 rounded-full bg-indigo-100 flex items-center justify-center mx-auto mb-4">
            <svg className="w-7 h-7 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-slate-800 mb-2">Unable to load this property page</h1>
          <p className="text-slate-600 leading-relaxed">{message}</p>
          <p className="text-sm text-slate-500 mt-4 leading-relaxed">
            If someone shared this link with you, ask them to confirm the URL or send an updated live link from their DocuStay dashboard.
          </p>
        </div>
      </div>
    );
  }

  const {
    property: prop,
    owner,
    has_current_guest,
    current_guest,
    current_guests,
    last_stay,
    upcoming_stays,
    invitations,
    logs,
    record_id,
    generated_at,
    poa_signed_at,
    poa_signature_id,
    jurisdiction_wrap,
    property_managers,
    current_tenant_assignments,
    tenant_summary_assignee,
    tenant_summary_assignment_period,
  } = data;

  const activeGuests: LiveCurrentGuestInfo[] =
    current_guests && current_guests.length > 0
      ? current_guests
      : current_guest
        ? [current_guest]
        : [];

  const activeTenants = activeGuests.filter(stayIsTenant);
  const activeGuestsOnly = activeGuests.filter((g) => !stayIsTenant(g));
  const hasActiveOccupants = has_current_guest && activeGuests.length > 0;

  const address = [prop.street, prop.city, prop.state, prop.zip_code].filter(Boolean).join(', ');
  /** API is snake_case; tolerate accidental camelCase in cached payloads. */
  const ownerEmailNormalized = (() => {
    const o = owner as LiveOwnerInfo & { Email?: string };
    const v = o.email ?? o.Email ?? '';
    return typeof v === 'string' ? v.trim() : '';
  })();
  /** Owner viewing their own live link: hide guest-stay surfaces and stay check-in/checkout style occupant cards — tenant/unit assignments stay visible. */
  const ownerViewingOwnLivePage =
    viewerIsOwner &&
    !!viewerSession &&
    ownerEmailNormalized.length > 0 &&
    normalizeEmail(viewerSession.email) === normalizeEmail(ownerEmailNormalized);
  const occupancySummary = livePropertyOccupancySummary(prop);
  const statusLabel = occupancySummary.badgeText;
  const occupancyBadgeTone = occupancySummary.badgeTone;
  const occupancyDetailText = occupancySummary.detailText;
  const isVacant = (prop.occupancy_status || '').toLowerCase() === 'vacant' && !has_current_guest;
  const liveLink = typeof window !== 'undefined' ? window.location.href : `#live/${slug}`;
  const hasPoaOnRecord = poa_signature_id != null;

  const handleOpenLivePoaPdf = async () => {
    setPoaOpenError(null);
    setPoaOpening(true);
    try {
      const r = await openLivePoaPdfInNewTab(slug);
      if (!r.ok) setPoaOpenError(r.userMessage);
    } finally {
      setPoaOpening(false);
    }
  };

  const upcomingStaysForOwnerView = ownerViewingOwnLivePage ? upcoming_stays.filter(stayIsTenant) : upcoming_stays;
  const lastStayForOwnerView =
    !ownerViewingOwnLivePage ? last_stay : last_stay && stayIsTenant(last_stay) ? last_stay : null;

  const upcomingSectionTitle =
    upcomingStaysForOwnerView.length > 0
      ? (() => {
          const kinds = new Set(
            upcomingStaysForOwnerView.map((s) =>
              (s.stay_kind ?? 'guest').toLowerCase() === 'tenant' ? 'tenant' : 'guest',
            ),
          );
          if (kinds.has('guest') && kinds.has('tenant')) return 'Upcoming guest & tenant stays';
          if (kinds.has('tenant')) return 'Upcoming tenant stays';
          return 'Upcoming guest stays';
        })()
      : lastStayForOwnerView
        ? (lastStayForOwnerView.stay_kind ?? 'guest').toLowerCase() === 'tenant'
          ? 'Last tenant stay'
          : 'Last guest stay'
        : 'Stays';

  const poaTimestampFormatted = poa_signed_at ? formatDateTimeLocal(poa_signed_at) : null;
  const tenantLeaseUnitLabelHint =
    tenantScopeEnabled
      ? (tenantDashboardLeaseRow?.unit?.unit_label || '').trim() ||
        ((current_tenant_assignments ?? []).find((r) => viewerSession && tenantRowMatchesViewer(r, viewerSession))
          ?.unit_label || '').trim() ||
        null
      : null;

  const upcomingTenantStays = upcoming_stays.filter((s) => stayIsTenant(s));
  const upcomingTenantStaysForView =
    tenantScopeEnabled && viewerSession
      ? upcomingTenantStays.filter((s) => {
          const gn = (s.guest_name || '').trim();
          if (!gn) return false;
          if (gn.includes('@')) return normalizeEmail(gn) === normalizeEmail(viewerSession.email);
          return normalizeLooseName(gn) === normalizeLooseName(viewerSession.user_name);
        })
      : upcomingTenantStays;
  const lastTenantStay = last_stay && stayIsTenant(last_stay) ? last_stay : null;
  const lastTenantStayForView =
    tenantScopeEnabled && viewerSession && lastTenantStay
      ? (() => {
          const gn = (lastTenantStay.guest_name || '').trim();
          if (!gn) return null;
          if (gn.includes('@')) {
            return normalizeEmail(gn) === normalizeEmail(viewerSession.email) ? lastTenantStay : null;
          }
          return normalizeLooseName(gn) === normalizeLooseName(viewerSession.user_name) ? lastTenantStay : null;
        })()
      : lastTenantStay;
  const invitationsForDisplay = viewerIsGuest
    ? invitations.filter((inv) => !inviteIsTenant(inv))
    : ownerViewingOwnLivePage
      ? invitations.filter(inviteIsTenant)
      : tenantScopeEnabled
        ? invitations.filter((inv) => {
            if (!inviteIsTenant(inv)) return false;
            if (!viewerSession) return true;
            const lab = (inv.guest_label || '').trim();
            if (lab.includes('@')) return normalizeEmail(lab) === normalizeEmail(viewerSession.email);
            return true;
          })
      : invitations;
  const tenantInvitations = invitationsForDisplay.filter(inviteIsTenant);
  const propertyManagersForAuthority: LivePropertyManagerInfo[] = tenantScopeEnabled
    ? []
    : (property_managers ?? []).filter((m) => typeof m?.email === 'string' && m.email.trim().length > 0);
  const viewerTenantShareUnitLabels =
    viewerIsTenant && viewerSession
      ? new Set(
          (current_tenant_assignments ?? [])
            .filter((r) => tenantRowMatchesViewer(r, viewerSession))
            .map((r) => (r.unit_label || '').trim())
            .filter(Boolean),
        )
      : null;
  const currentTenantAssignments: LiveTenantAssignmentInfo[] =
    viewerIsTenant && viewerSession && viewerTenantShareUnitLabels && viewerTenantShareUnitLabels.size > 0
      ? (current_tenant_assignments ?? []).filter((r) =>
          viewerTenantShareUnitLabels!.has((r.unit_label || '').trim()),
        )
      : (current_tenant_assignments ?? []);
  const propertySummaryLine = tenantScopeEnabled
    ? address || '—'
    : [prop.name || '', address].filter(Boolean).join(' — ') || address || '—';

  const baseAssignmentsForDisplay =
    ownerViewingOwnLivePage && ownerDashboardRowsForLive !== null
      ? dedupeLiveTenantAssignments([
          ...currentTenantAssignments,
          ...ownerDashboardRowsForLive.map(ownerTenantViewToLiveAssignmentInfo),
        ])
      : currentTenantAssignments;

  const livePageTodayYmd = getTodayLocal();
  const liveGuestOpenStayInviteCodes = collectGuestOpenStayInvitationCodes(activeGuests);
  const displayTenantAssignments = buildDisplayTenantAssignmentsForTenantLivePage(
    baseAssignmentsForDisplay,
    viewerSession,
    slug,
    tenantDashboardLeaseRow,
    invitations,
    livePageTodayYmd,
    liveGuestOpenStayInviteCodes,
  );
  const tenantActiveAcceptedUnitLabels = new Set(
    dedupeLiveTenantAssignments(displayTenantAssignments)
      .filter(leaseInviteResolvedIsActiveOrAccepted)
      .map((r) => (r.unit_label || '').trim())
      .filter(Boolean),
  );
  const tenantLeaseUnitLabels =
    tenantScopeEnabled
      ? (guestLinkAudience
          ? new Set(
              (data?.scoped_unit_labels ?? [])
                .map((s) => (s || '').trim())
                .filter(Boolean),
            )
          : new Set(
              [
                ...((data?.scoped_unit_labels ?? []).map((s) => (s || '').trim()).filter(Boolean)),
                tenantLeaseUnitLabelHint || '',
                ...(viewerSession
                  ? displayTenantAssignments
                      .filter((r) => tenantRowMatchesViewer(r, viewerSession))
                      .map((r) => (r.unit_label || '').trim())
                  : displayTenantAssignments.map((r) => (r.unit_label || '').trim())),
              ]
                .filter(Boolean)
                .filter((l) => tenantActiveAcceptedUnitLabels.has(l)),
            ))
      : new Set<string>();
  const displayTenantAssignmentsScoped =
    tenantScopeEnabled
      ? (tenantLeaseUnitLabels.size > 0
          ? displayTenantAssignments.filter((r) => tenantLeaseUnitLabels.has((r.unit_label || '').trim()))
          : [])
      : displayTenantAssignments;
  const tenantAssignmentsForTenantSummary = dedupeLiveTenantAssignments(displayTenantAssignmentsScoped).filter((r) =>
    includeTenantSummaryCohortPeerRow(r, displayTenantAssignmentsScoped, viewerIsTenant),
  );
  const apiOccupancySummaryDetail = (prop.occupancy_summary_detail || '').trim();
  const occupancyContextDetail = ownerViewingOwnLivePage
    ? `${statusLabel} on this snapshot. Invitation status: ${prop.invitation_pending_count ?? 0} pending, ${prop.invitation_accepted_count ?? 0} accepted, ${prop.invitation_active_count ?? 0} active.`
    : tenantScopeEnabled
      ? tenantLeaseUnitLabels.size > 0
        ? guestLinkAudience
          ? `Occupancy references on this page are limited to your stay unit(s): ${[...tenantLeaseUnitLabels].join(', ')}.`
          : `Occupancy references on this page are limited to your lease unit(s): ${[...tenantLeaseUnitLabels].join(', ')}.`
        : ''
      : apiOccupancySummaryDetail;
  const headerUnitStatusBadges = tenantScopeEnabled
    ? buildHeaderUnitStatusBadges(prop, tenantLeaseUnitLabels, tenantLeaseUnitLabels.size > 0)
    : buildHeaderUnitStatusBadges(prop, tenantLeaseUnitLabels, false);
  const ownerUnitSummaryCards = ownerViewingOwnLivePage
    ? buildOwnerUnitSummaryCards(prop, displayTenantAssignments)
    : [];
  const unitInviteCountCtx: UnitInviteCountCtx = {
    tenantInvitations,
    todayYmd: livePageTodayYmd,
    guestOpenStayInviteCodes: liveGuestOpenStayInviteCodes,
    propertyIsMultiUnit: !!prop.is_multi_unit,
  };
  const qdlUnitInviteCounts = new Map(
    [...new Set(headerUnitStatusBadges.map((b) => unitLabelFromHeaderBadgeLabel(b.label)).filter(Boolean) as string[])].map(
      (unitLabel) => [
        unitLabel,
        buildUnitActiveAcceptedInviteCounts(
          unitLabel,
          tenantScopeEnabled ? displayTenantAssignmentsScoped : displayTenantAssignments,
          unitInviteCountCtx,
        ),
      ],
    ),
  );
  const ownerUnitInviteCounts = new Map(
    ownerUnitSummaryCards.map((card) => [
      card.unitLabel,
      buildUnitActiveAcceptedInviteCounts(card.unitLabel, displayTenantAssignments, unitInviteCountCtx),
    ]),
  );
  const authLabel = resolveLivePagePropertyAuthorizationDisplay(viewerSession, invitationsForDisplay, activeGuests, {
    todayYmd: livePageTodayYmd,
    tenantAssignmentRows: displayTenantAssignmentsScoped,
    propertyManagers: propertyManagersForAuthority,
    ownerViewingOwnLivePage,
  });
  const occupancyRecordAssertion = tenantScopeEnabled
    ? tenantLeaseUnitLabels.size > 0
      ? guestLinkAudience
        ? `Record indicates status for your stay unit(s) (${[...tenantLeaseUnitLabels].join(', ')}) on this snapshot.`
        : `Record indicates status for your leased unit(s) (${[...tenantLeaseUnitLabels].join(', ')}) on this snapshot.`
      : guestLinkAudience
        ? 'Building-wide occupancy is not displayed for your guest session; see Tenant summary for tenant assignment context.'
        : 'Building-wide occupancy is not displayed for your tenant session; see Tenant summary for your assignment record.'
    : `Record indicates the stored occupancy field for this property is reported as "${statusLabel}" at the time this page was generated (see context below).`;
  const authorizationRecordAssertion = !viewerSession
    ? 'Record indicates no signed-in session was used to personalize the authorization readout on this snapshot.'
    : `Record indicates this snapshot's authorization readout for your signed-in role is "${authLabel}" within the dates evaluated on this page; it is not a legal determination.`;
  const logsForLivePage =
    tenantScopeEnabled
      ? (tenantLeaseUnitLabels.size > 0
          ? logs
              .filter((entry) => logEntryMentionsAnyUnitLabel(entry, tenantLeaseUnitLabels))
              .filter(presenceEntryAllowedForResidentScopedView)
              .filter((entry) => !tenantLiveTimelineEntryIsOwnerBulkOrPortfolioLeak(entry))
          : [])
      : logs;
  const tenantPresenceVisible = viewerIsTenant || tenantLinkAudience;
  const logsForAuditTimeline = tenantPresenceVisible
    ? logsForLivePage
    : logsForLivePage.filter((entry) => !ownerLiveShouldHidePresenceTimelineEntry(entry));
  // Condensed Audit Timeline (Part B): POA signed, property onboarded, status changes (active/expired/revoked)
  const oldestLog = logsForAuditTimeline.length > 0 ? logsForAuditTimeline[logsForAuditTimeline.length - 1] : null;
  const propertyOnboardedAt = oldestLog ? formatDateTimeLocal(oldestLog.created_at) : null;
  const statusChangeLogs = logsForAuditTimeline.filter(
    (e) =>
      e.category === 'status_change' ||
      (e.category || '').toLowerCase() === 'presence' ||
      /status|vacant|occupancy|confirmed|vacated|check.?in|checkout|presence|away|resident|absent|returned/i.test(
        e.title || '',
      ) ||
      /status|vacant|occupancy|confirmed|vacated|presence|away|resident|absent|returned/i.test(e.message || ''),
  );
  const tokenEventLogs = logsForAuditTimeline.filter(
    (e) =>
      /invitation|invite|stay|token|burn|expire|revoke|signed|agreement|checkout|check.?in/i.test(e.category || '') ||
      /invitation|invite|stay|token|burn|expire|revoke|signed|agreement|checkout|check.?in/i.test(e.title || '')
  );
  const authorityTenantAssignmentsUnique = dedupeLiveTenantAssignments(displayTenantAssignmentsScoped);
  const authorityTenantAssignmentsForRecordTrail = authorityTenantAssignmentsUnique.filter((r) =>
    includeTenantSummaryCohortPeerRow(r, authorityTenantAssignmentsUnique, viewerIsTenant),
  );
  const authorityTenantAssignmentGroups = groupLiveTenantRowsByCohort(authorityTenantAssignmentsForRecordTrail);
  const tenantClientGroups = groupLiveTenantRowsByCohort(tenantAssignmentsForTenantSummary);

  const assigneeNamesFromDisplayGroups =
    tenantAssignmentsForTenantSummary.length > 0
      ? tenantClientGroups.map((grp) => grp.rows.map((r) => tenantAssignmentDisplayName(r)).join(' · ')).join('; ')
      : '';
  const tenantSummaryAssigneeLine = tenantScopeEnabled
    ? assigneeNamesFromDisplayGroups || (tenant_summary_assignee && tenant_summary_assignee.trim()) || '—'
    : (tenant_summary_assignee && tenant_summary_assignee.trim()) || assigneeNamesFromDisplayGroups || '—';
  const tenantSummaryPeriodLine =
    tenantScopeEnabled && tenantAssignmentsForTenantSummary.length > 1
      ? (tenant_summary_assignment_period && tenant_summary_assignment_period.trim()) || 'Multiple (see Assigned Tenant Record)'
      : (tenant_summary_assignment_period && tenant_summary_assignment_period.trim()) ||
        (tenantAssignmentsForTenantSummary.length === 1
          ? tenantLeasePeriodLabel(tenantAssignmentsForTenantSummary[0])
          : tenantAssignmentsForTenantSummary.length > 1
            ? 'Multiple (see Assigned Tenant Record)'
            : upcomingTenantStaysForView.length > 0
              ? `${formatCalendarDate(upcomingTenantStaysForView[0].stay_start_date)} – ${formatCalendarDate(upcomingTenantStaysForView[0].stay_end_date)} (upcoming stay)`
              : lastTenantStayForView
                ? `${formatCalendarDate(lastTenantStayForView.stay_start_date)} – ${formatCalendarDate(lastTenantStayForView.stay_end_date)} (last stay)`
                : '—');
  const tenantSummaryLeaseInviteLine = tenantLeaseInviteResolvedSummary(tenantAssignmentsForTenantSummary);
  const fallbackLeaseStatusBadges = leaseStatusBadgesFromSummary(tenantSummaryLeaseInviteLine);
  const activeTenantAssignmentsInSummaryWindow = tenantAssignmentsForTenantSummary.filter(
    (r) => resolvedLeaseStatusKey(r) === 'active',
  );
  const acceptedTenantAssignmentsOutsideActiveWindow = tenantAssignmentsForTenantSummary.filter(
    (r) => resolvedLeaseStatusKey(r) === 'accepted',
  );
  const pendingScopedLeaseRows = dedupeLiveTenantAssignments(displayTenantAssignmentsScoped).filter((r) => {
    const k = resolvedLeaseStatusKey(r);
    if (k === 'pending') return true;
    if (k != null) return false;
    return liveTenantAssignmentFallbackShowsPending(r, tenantInvitations, livePageTodayYmd, liveGuestOpenStayInviteCodes);
  });
  const tenantAssignmentStatusSummaryLine =
    tenantAssignmentsForTenantSummary.length > 0
      ? `${activeTenantAssignmentsInSummaryWindow.length} active · ${acceptedTenantAssignmentsOutsideActiveWindow.length} accepted · ${pendingScopedLeaseRows.length} pending${
          tenantAssignmentsForTenantSummary.length > 1 &&
          tenantClientGroups.length < tenantAssignmentsForTenantSummary.length
            ? ` (${tenantClientGroups.length} shared-lease group${tenantClientGroups.length !== 1 ? 's' : ''})`
            : ''
        }`
      : upcomingTenantStaysForView.length > 0
        ? `Pending · ${upcomingTenantStaysForView.length} upcoming tenant stay${upcomingTenantStaysForView.length > 1 ? 's' : ''}`
        : lastTenantStayForView
          ? 'Expired · last tenant stay on record has ended'
          : 'None · no tenant assignment on this snapshot';
  const invitingTenantLines: Array<{ name: string; email: string }> = [];
  if (guestLinkAudience) {
    const seenInvitingTenants = new Set<string>();
    invitationsForDisplay
      .filter((inv) => ((inv.invited_by_role || '').trim().toLowerCase() === 'tenant'))
      .forEach((inv) => {
        const nm = (inv.invited_by_name || '').trim() || '—';
        const em = (inv.invited_by_email || '').trim() || '—';
        const key = `${nm}|${em}`;
        if (seenInvitingTenants.has(key)) return;
        seenInvitingTenants.add(key);
        invitingTenantLines.push({ name: nm, email: em });
      });
  }

  const sessionAuthorityChainLines: { key: string; prefix: string; name: string; email: string }[] = [];
  if (viewerSession) {
    if (viewerSession.user_type === 'GUEST') {
      const roleBucketOrder = ['owner', 'property_manager', 'tenant'] as const;
      const roleBuckets: Record<(typeof roleBucketOrder)[number], Array<{ key: string; prefix: string; name: string; email: string }>> = {
        owner: [],
        property_manager: [],
        tenant: [],
      };
      const seenByRole = new Set<string>();
      activeGuestsOnly
        .filter((stay) => guestStayMatchesViewer(stay, invitations, viewerSession))
        .forEach((stay, idx) => {
          const code = (stay.invitation_code || '').trim().toUpperCase();
          if (!code) return;
          const inv = invitations.find((x) => (x.invitation_code || '').trim().toUpperCase() === code);
          if (!inv) return;
          const roleRaw = (inv.invited_by_role || '').trim().toLowerCase();
          const roleKey =
            roleRaw === 'owner' || roleRaw === 'property_owner'
              ? 'owner'
              : roleRaw === 'property_manager' || roleRaw === 'manager'
                ? 'property_manager'
                : roleRaw === 'tenant'
                  ? 'tenant'
                  : null;
          if (!roleKey) return;
          const ownerName = (inv.invited_by_name || '').trim() || '—';
          const ownerEmail = (inv.invited_by_email || '').trim() || '—';
          const dedupeKey = `${roleKey}|${ownerName}|${ownerEmail}`;
          if (seenByRole.has(dedupeKey)) return;
          seenByRole.add(dedupeKey);
          roleBuckets[roleKey].push({
            key: `chain-rel-${code}-${idx}`,
            prefix: roleKey === 'owner' ? 'Owner' : roleKey === 'property_manager' ? 'Property manager' : 'Tenant',
            name: ownerName,
            email: ownerEmail,
          });
        });
      roleBucketOrder.forEach((r) => {
        roleBuckets[r].forEach((line) => sessionAuthorityChainLines.push(line));
      });
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50/70 via-white to-slate-100/60 print:bg-white print:min-h-0">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6 print:py-6 print:max-w-none">
        <LivePageRecordFramingBanner />
        {/* Meta bar: record, timestamp, link, print */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm bg-white/90 backdrop-blur rounded-xl border border-indigo-100 px-4 py-3 shadow-sm print:bg-white print:border-slate-200">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-slate-600">
            <span className="inline-flex items-center gap-1.5">
              <span className="font-medium text-indigo-700">Record</span>
              <span className="font-mono text-slate-800 bg-slate-100 px-1.5 py-0.5 rounded">{record_id}</span>
            </span>
            <span className="text-slate-500">Generated {formatDateTimeLocal(generated_at)}</span>
            <a href={liveLink} className="text-indigo-600 hover:text-indigo-700 font-medium hover:underline break-all" target="_blank" rel="noopener noreferrer">Live link</a>
          </div>
          <div className="flex flex-wrap items-center gap-2 print:hidden">
            <button
              type="button"
              onClick={() => void handleOpenLivePoaPdf()}
              disabled={poaOpening}
              className="inline-flex items-center justify-center px-4 py-2 rounded-lg border border-indigo-200 bg-white text-indigo-700 text-sm font-semibold hover:bg-indigo-50 shadow-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {poaOpening ? 'Opening…' : 'View owner authorization (PDF)'}
            </button>
            <button
              type="button"
              onClick={() => window.print()}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 shadow-sm transition-colors"
            >
              Print page
            </button>
          </div>
        </div>

        {poaOpenError && (
          <div
            role="alert"
            className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3"
          >
            <p className="leading-relaxed">{poaOpenError}</p>
            <button
              type="button"
              onClick={() => setPoaOpenError(null)}
              className="shrink-0 text-amber-900 font-medium underline underline-offset-2 hover:text-amber-950"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Top Section – Quick Decision Layer (rapid field clarity) */}
        <header className="bg-white rounded-2xl shadow-md border border-slate-200 overflow-hidden print:rounded print:shadow-none print:border border-l-4 border-l-indigo-500">
          <div className="px-6 py-3.5 sm:px-8 bg-gradient-to-r from-indigo-50 to-slate-50 border-b border-indigo-100/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-indigo-800">Quick Decision Layer</h2>
          </div>
          <div className="p-6 sm:p-8">
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600 mb-1">Property address</p>
            <h1 className="text-xl sm:text-2xl font-bold text-slate-900 mb-3">{address || '—'}</h1>
            <p className="text-sm text-slate-600 mb-4">
              <span className="font-medium text-slate-700">Verified owner entity</span>
              <span className="text-slate-600"> · {owner.full_name ?? '—'}</span>
              {!tenantScopeEnabled && ownerEmailNormalized ? (
                <span className="text-slate-600 break-all"> · {ownerEmailNormalized}</span>
              ) : null}
            </p>
            <div className="flex flex-wrap gap-4 sm:gap-6 mb-4">
              <div>
                <p className="text-xs font-medium text-slate-500 mb-0.5">
                  {tenantScopeEnabled && tenantLeaseUnitLabels.size > 0
                    ? guestLinkAudience
                      ? `Your stay unit(s) (${[...tenantLeaseUnitLabels].join(', ')})`
                      : `Your leased unit(s) (${[...tenantLeaseUnitLabels].join(', ')})`
                    : tenantScopeEnabled
                      ? guestLinkAudience
                        ? 'Your stay context'
                        : 'Your lease context'
                      : 'Current property status'}
                </p>
                {tenantScopeEnabled && tenantLeaseUnitLabels.size === 0 ? (
                  <p className="text-xs text-slate-600">
                    {guestLinkAudience ? (
                      <>
                        No active or accepted guest stay is linked to a unit for your account on this snapshot - building-wide
                        occupancy is not shown. See <span className="font-medium text-slate-800">Tenant summary</span> for
                        tenant assignment and invitation context.
                      </>
                    ) : (
                      <>
                        No active or accepted lease on a unit for your account on this snapshot - building-wide occupancy is
                        not shown. See <span className="font-medium text-slate-800">Tenant summary</span> for your assignment
                        and invitation state.
                      </>
                    )}
                  </p>
                ) : (tenantScopeEnabled && headerUnitStatusBadges.length > 0) || headerUnitStatusBadges.length > 1 ? (
                  <div className="flex flex-wrap gap-2">
                    {headerUnitStatusBadges.map((b, i) => (
                      <div key={`hdr-unit-badge-${i}-${b.label}`} className="inline-flex flex-col gap-1">
                        <span
                          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold uppercase ${liveOccupancyBadgeClasses(b.tone)}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${liveOccupancyBadgeDotClasses(b.tone)}`} />
                          {b.label}
                        </span>
                        {(() => {
                          if (guestLinkAudience) return null;
                          const unitLabel = unitLabelFromHeaderBadgeLabel(b.label);
                          if (!unitLabel) return null;
                          const counts = qdlUnitInviteCounts.get(unitLabel) ?? { active: 0, accepted: 0, pending: 0 };
                          return (
                            <p className="text-[11px] text-slate-600 px-0.5">
                              {counts.pending} pending invites · {counts.active} active invites · {counts.accepted}{' '}
                              accepted invites
                            </p>
                          );
                        })()}
                      </div>
                    ))}
                  </div>
                ) : tenantScopeEnabled ? null : (
                  <span
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold uppercase ${liveOccupancyBadgeClasses(occupancyBadgeTone)}`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${liveOccupancyBadgeDotClasses(occupancyBadgeTone)}`}
                    />
                    {statusLabel}
                  </span>
                )}
                {prop.is_multi_unit && occupancyDetailText && !tenantScopeEnabled ? (
                  <p className="text-sm text-slate-600 mt-1.5">{occupancyDetailText}</p>
                ) : null}
                {occupancyContextDetail ? (
                  <p className="text-sm text-slate-600 mt-2 max-w-2xl leading-relaxed">{occupancyContextDetail}</p>
                ) : null}
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 mb-0.5">Authorization state</p>
                <p className="text-sm text-slate-700 mb-2 max-w-2xl leading-relaxed">{authorizationRecordAssertion}</p>
                <span
                  className={`inline-flex items-center px-3 py-1.5 rounded-lg ${liveAuthBadgeClasses(authLabel)}`}
                >
                  {authLabel}
                </span>
              </div>
            </div>
            {!tenantScopeEnabled && (
            <div className="mt-4 pt-4 border-t border-slate-200">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Invitation pipeline</p>
              <p className="text-sm text-slate-800 font-medium">{propertyInvitationCountsLine(prop)}</p>
              <p className="text-xs text-slate-500 mt-1.5 max-w-2xl leading-relaxed">{PROPERTY_INVITATION_COUNTS_FOOTNOTE}</p>
            </div>
            )}
            {hasActiveOccupants && !ownerViewingOwnLivePage && !tenantScopeEnabled && (
              <div className="mt-4 pt-4 border-t border-slate-200 space-y-6">
                {activeTenants.length > 0 && (
                  <div className="space-y-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-violet-700">
                      {activeTenants.length > 1 ? 'Current tenants' : 'Current tenant'}
                    </p>
                    <div className="flex flex-wrap gap-4 sm:gap-6">
                      {activeTenants.map((t) => (
                        <div
                          key={t.stay_id}
                          className="flex-1 min-w-[12rem] max-w-md rounded-xl border border-violet-200 bg-violet-50/80 p-4 shadow-sm"
                        >
                          <p className="text-slate-900 font-medium">{t.guest_name}</p>
                          <p className="text-slate-600 text-sm mt-0.5">
                            {formatCalendarDate(t.stay_start_date)} – {formatCalendarDate(t.stay_end_date)}
                          </p>
                          {t.signed_agreement_available && typeof t.stay_id === 'number' ? (
                            <a
                              href={publicApi.getLiveSignedAgreementUrl(slug, t.stay_id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex mt-2 text-sm font-medium text-violet-800 hover:text-violet-900 underline underline-offset-2"
                            >
                              View signed agreement (PDF)
                            </a>
                          ) : (
                            <p className="text-xs text-slate-500 mt-2">
                              Signed agreement will appear here once the tenant completes signing.
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {activeGuestsOnly.length > 0 && (
                  <div className="bg-emerald-50/60 -mx-6 sm:-mx-8 px-6 sm:px-8 py-4 rounded-lg border border-emerald-100 space-y-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
                      {activeGuestsOnly.length > 1 ? 'Current guests (active authorizations)' : 'Current guest'}
                    </p>
                    {activeGuestsOnly.map((g) => (
                      <div key={g.stay_id} className="border-b border-emerald-100/80 last:border-0 last:pb-0 pb-4 last:mb-0">
                        <p className="text-slate-900 font-medium">{g.guest_name}</p>
                        <p className="text-slate-600 text-sm">
                          {formatCalendarDate(g.stay_start_date)} – {formatCalendarDate(g.stay_end_date)}
                        </p>
                        {g.signed_agreement_available && typeof g.stay_id === 'number' ? (
                          <a
                            href={publicApi.getLiveSignedAgreementUrl(slug, g.stay_id)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex mt-2 text-sm font-medium text-emerald-800 hover:text-emerald-900 underline underline-offset-2"
                          >
                            View signed guest agreement (PDF)
                          </a>
                        ) : (
                          <p className="text-xs text-slate-500 mt-2">
                            Signed agreement will appear here once the guest completes signing.
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </header>

        {/* Owner authorization on file + jurisdiction (moved up for context) */}
        <section className="bg-white rounded-2xl shadow-md border border-slate-200 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-indigo-50 to-slate-50 border-b border-indigo-100/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-indigo-800">Owner authorization on file</h2>
          </div>
          <div className="p-6 sm:p-8 space-y-4">
            <p className="text-slate-700">
              {hasPoaOnRecord ? (
                <>
                  DocuStay&apos;s record for this property includes <strong>signed owner authorization documentation</strong> (the
                  executed file is available below).
                </>
              ) : (
                <>
                  When the property owner completes <strong>authorization signing</strong>, DocuStay can retain the signed file as
                  part of its records. <span className="text-slate-600">If signing is complete, you can open the PDF below; otherwise you may see a short notice.</span>
                </>
              )}
            </p>
            {poa_signed_at && (
              <p className="text-slate-700">
                Authorization signed: <strong>{formatCalendarDate(poa_signed_at)}</strong>. Owner: <strong>{owner.full_name ?? '—'}</strong>.
              </p>
            )}
            <p className="text-slate-600 text-sm">
              DocuStay maintains append-only records based on authorization and activity the property owner and users provide in the
              platform. DocuStay does not exercise independent legal authority.
            </p>
            <div className="space-y-2 print:hidden">
              <button
                type="button"
                onClick={() => void handleOpenLivePoaPdf()}
                disabled={poaOpening}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 text-white font-medium hover:bg-indigo-700 shadow-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {poaOpening ? 'Opening…' : 'View owner authorization (PDF)'}
              </button>
              {hasPoaOnRecord ? (
                <p className="text-sm text-slate-600">
                  Signed by <strong>{owner.full_name ?? '—'}</strong>. The document you open contains the full signature.
                </p>
              ) : (
                <p className="text-sm text-slate-500">
                  If the PDF does not open, the owner may still need to complete authorization signing in DocuStay (Settings or onboarding).
                </p>
              )}
            </div>
            <p className="text-xs text-slate-500 print:block hidden print:text-slate-600">
              Use &quot;View owner authorization (PDF)&quot; in the browser before printing if you need the authorization file; print view does not attach the PDF.
            </p>
            <div className="pt-4 border-t border-slate-200">
              <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600/90">Property identifier</p>
              <p className="text-slate-900 mt-0.5">{address || '—'}</p>
              {!tenantScopeEnabled && (prop.apn || prop.tax_id) ? (
                <p className="text-slate-600 text-sm mt-1">
                  {prop.apn && <span>APN: {prop.apn}</span>}
                  {prop.apn && prop.tax_id && ' · '}
                  {prop.tax_id && <span>Tax ID: {prop.tax_id}</span>}
                </p>
              ) : null}
            </div>
            {jurisdiction_wrap && jurisdiction_wrap.applicable_statutes?.length > 0 && (
              <div className="pt-4 border-t border-slate-200">
                <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600/90">Legal context — {jurisdiction_wrap.state_name}</p>
                <p className="text-xs text-slate-500 mt-2 leading-relaxed border border-slate-200 bg-slate-50/80 rounded-lg px-3 py-2">
                  {JURISDICTION_CONTEXT_DISCLAIMER}
                </p>
                <ul className="mt-3 space-y-2">
                  {jurisdiction_wrap.applicable_statutes.map((s, i) => (
                    <li key={i} className="text-sm text-slate-700">
                      <span className="font-medium text-slate-900">{s.citation}</span>
                      {s.plain_english && (
                        <span className="block text-slate-500 mt-0.5 text-xs leading-relaxed">
                          Reference summary (informational): {s.plain_english}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>

        {/* Evidence Summary – machine-readable summary for verification */}
        <section className="bg-white rounded-2xl shadow-md border border-emerald-200/80 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-emerald-50 to-slate-50 border-b border-emerald-200/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-emerald-800">Summary</h2>
            <p className="text-xs text-emerald-700/90 mt-0.5">Machine-readable summary for verification</p>
          </div>
          <div className="p-6 sm:p-8 space-y-4">
            <div className="grid gap-x-6 gap-y-2 text-sm">
              <p><span className="font-semibold text-slate-700">Property:</span> {propertySummaryLine}</p>
              <p>
                <span className="font-semibold text-slate-700">Status (stored field):</span>{' '}
                <span
                  className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold uppercase align-middle ${liveOccupancyBadgeClasses(occupancyBadgeTone)}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${liveOccupancyBadgeDotClasses(occupancyBadgeTone)}`} />
                  {statusLabel}
                </span>
                {prop.is_multi_unit && occupancyDetailText && !tenantScopeEnabled ? (
                  <span className="block text-slate-600 mt-1 text-sm">{occupancyDetailText}</span>
                ) : null}
                <span className="block text-slate-600 mt-1 text-sm font-normal">{occupancyRecordAssertion}</span>
              </p>
              {occupancyContextDetail ? (
                <p className="text-slate-600">
                  <span className="font-semibold text-slate-700">Occupancy context:</span> {occupancyContextDetail}
                </p>
              ) : null}
              {!tenantScopeEnabled ? (
                <p>
                  <span className="font-semibold text-slate-700">Owner email:</span>{' '}
                  <span className="break-all text-slate-800">{ownerEmailNormalized || '—'}</span>
                </p>
              ) : null}
              <p>
                <span className="font-semibold text-slate-700">Last updated:</span>{' '}
                {formatCalendarDate(livePageTodayYmd)}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Record trail</p>
              <ul className="list-disc pl-5 space-y-0.5 text-sm text-slate-700">
                <li>
                  Owner verified: {owner.full_name ?? '—'}
                  {!tenantScopeEnabled && ownerEmailNormalized ? (
                    <span className="text-slate-600 break-all"> · {ownerEmailNormalized}</span>
                  ) : null}
                </li>
                {poa_signed_at && (
                  <li>Owner authorization signed: {formatCalendarDate(poa_signed_at)}</li>
                )}
                {!tenantScopeEnabled
                  ? propertyManagersForAuthority.map((m, idx) => (
                      <li key={`${m.email}-${idx}`}>
                        Property manager: {m.full_name ?? '—'}
                        <span className="text-slate-600 break-all"> · {m.email.trim()}</span>
                      </li>
                    ))
                  : null}
                {authorityTenantAssignmentGroups.map((g, idx) => (
                  <li key={`tenant-auth-grp-${g.cohortKey}-${idx}`}>
                    {g.rows.length > 1 ? (
                      <>
                        <span className="font-medium text-slate-800">Co-tenants (Unit {g.rows[0].unit_label}):</span>{' '}
                        {g.rows.map((row, j) => (
                          <span key={`${row.assignment_id ?? ''}-${row.stay_id ?? ''}-${j}`}>
                            {tenantAssignmentDisplayName(row)}
                            {row.tenant_email ? (
                              <span className="text-slate-600 break-all"> ({row.tenant_email})</span>
                            ) : null}
                            <span
                              className={`ml-2 inline-flex px-2 py-0.5 rounded text-[11px] font-semibold align-middle ${leaseStatusBadgeForRow(row).className}`}
                            >
                              {leaseStatusBadgeForRow(row).label}
                            </span>
                            {j < g.rows.length - 1 ? <span className="text-slate-500"> · </span> : null}
                          </span>
                        ))}
                      </>
                    ) : (
                      <>
                        {(() => {
                          const row = g.rows[0];
                          return (
                            <>
                              Tenant (Unit {row.unit_label}): {tenantAssignmentDisplayName(row)}
                            </>
                          );
                        })()}
                        {g.rows[0].tenant_email ? (
                          <span className="text-slate-600 break-all"> · {g.rows[0].tenant_email}</span>
                        ) : null}
                        <span
                          className={`ml-2 inline-flex px-2 py-0.5 rounded text-[11px] font-semibold align-middle ${leaseStatusBadgeForRow(g.rows[0]).className}`}
                        >
                          {leaseStatusBadgeForRow(g.rows[0]).label}
                        </span>
                      </>
                    )}
                  </li>
                ))}
                {authorityTenantAssignmentsForRecordTrail.length === 0 &&
                fallbackLeaseStatusBadges.length > 0 &&
                tenant_summary_assignee ? (
                  <li>
                    Tenant: {tenant_summary_assignee.trim() || '—'}
                    {tenant_summary_assignment_period ? (
                      <span className="text-slate-600"> · {tenant_summary_assignment_period}</span>
                    ) : null}
                    {fallbackLeaseStatusBadges.map((label) => (
                      <span
                        key={`fallback-lease-status-${label}`}
                        className={`ml-2 inline-flex px-2 py-0.5 rounded text-[11px] font-semibold align-middle ${
                          label === 'Active'
                            ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                            : 'bg-sky-100 text-sky-800 border border-sky-200'
                        }`}
                      >
                        {label}
                      </span>
                    ))}
                  </li>
                ) : null}
                {sessionAuthorityChainLines.map((line) => (
                  <li key={line.key}>
                    {line.prefix}: {line.name}
                    <span className="text-slate-600 break-all"> · {line.email}</span>
                  </li>
                ))}
              </ul>
            </div>
            {jurisdiction_wrap && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Legal context</p>
                <p className="font-semibold text-slate-700">{jurisdiction_wrap.state_name}</p>
                <p className="text-xs text-slate-500 mt-2 leading-relaxed border border-slate-200 bg-slate-50/80 rounded-lg px-3 py-2">
                  {JURISDICTION_CONTEXT_DISCLAIMER}
                </p>
                {jurisdiction_wrap.applicable_statutes?.length > 0 && (
                  <ul className="list-disc pl-5 mt-2 space-y-0.5 text-sm text-slate-600">
                    {jurisdiction_wrap.applicable_statutes.map((s, i) => (
                      <li key={i}>
                        <span className="font-medium text-slate-800">{s.citation}</span>
                        {s.plain_english ? (
                          <span className="block text-slate-500 text-xs mt-0.5 not-italic">
                            Reference summary (informational): {s.plain_english}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <p className="text-sm text-slate-700 pt-1">
              {hasActiveOccupants && !tenantScopeEnabled ? (
                <span>
                  {ownerViewingOwnLivePage ? (
                    activeTenants.length > 0 ? (
                      <>
                        {activeTenants.length > 1
                          ? 'Active tenant assignments (current stays).'
                          : 'Active tenant assignment (current stay).'}{' '}
                        Signed agreements on this page are only for these active authorizations; prior agreements appear
                        in the audit timeline below.
                      </>
                    ) : (
                      <>
                        Active occupancy on this property is managed in your owner dashboard; this summary shows tenant
                        lease and residence-listing context only.{' '}
                        Signed agreements on this page are only for active authorizations shown above; prior agreements
                        appear in the audit timeline below.
                      </>
                    )
                  ) : (
                    <>
                      {activeTenants.length > 0 && activeGuestsOnly.length > 0
                        ? 'Active tenant and guest assignments (current stays).'
                        : activeTenants.length > 0
                          ? activeTenants.length > 1
                            ? 'Active tenant assignments (current stays).'
                            : 'Active tenant assignment (current stay).'
                          : activeGuests.length > 1
                            ? 'Active guest assignments (current stays).'
                            : 'Active guest assignment (current stay).'}{' '}
                      Signed agreements on this page are only for these active authorizations; prior agreements appear in
                      the audit timeline below.
                    </>
                  )}
                </span>
              ) : tenantScopeEnabled && hasActiveOccupants ? (
                <span>
                  Active stay authorizations exist on this property for other parties. Your tenant lane on this page is
                  limited to the <span className="font-medium text-slate-800">Tenant summary</span> and your scoped
                  assignment rows.
                </span>
              ) : tenantAssignmentsForTenantSummary.length > 0 ? (
                <span>
                  Active tenant lease assignment(s) on file for this property (see Tenant summary).{' '}
                  {ownerViewingOwnLivePage ? (
                    <>
                      No checked-in tenant stay is currently recorded on this live view. Prior activity appears in the
                      audit timeline below.
                    </>
                  ) : (
                    <>
                      No guest-stay check-in is currently recorded on this live record. Prior activity appears in the
                      audit timeline below.
                    </>
                  )}
                </span>
              ) : sessionAuthorityChainLines.length > 0 ? (
                <span>
                  Your role on this property is listed in the authority chain above. See the Quick Decision layer and
                  Tenant summary for full occupancy context.
                </span>
              ) : ownerViewingOwnLivePage ? (
                <span>No active tenant assignments appear on this summary. Verify the audit timeline or your owner dashboard.</span>
              ) : (
                <span>No active guest or tenant assignments.</span>
              )}
            </p>
          </div>
        </section>

        {ownerUnitSummaryCards.length > 0 ? (
          <section className="mt-6 bg-white rounded-2xl shadow-md border border-emerald-200/80 overflow-hidden print:rounded print:shadow-none print:border">
            <div className="px-6 py-3.5 bg-gradient-to-r from-emerald-50 to-slate-50 border-b border-emerald-200/80 print:bg-slate-50">
              <h2 className="text-sm font-bold uppercase tracking-wider text-emerald-800">Unit summary</h2>
              <p className="text-xs text-emerald-700/90 mt-0.5">Per-unit occupancy and lease assignments on this snapshot</p>
            </div>
            <div className="p-6 sm:p-8">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {ownerUnitSummaryCards.map((card) => (
                  <div
                    key={`unit-card-${card.unitLabel}`}
                    className="rounded-xl border border-emerald-200/80 bg-gradient-to-b from-white to-emerald-50/50 p-4 shadow-sm text-sm"
                  >
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <p className="font-bold text-slate-800">Unit {card.unitLabel}</p>
                      <span
                        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase shrink-0 ${liveOccupancyBadgeClasses(card.tone)}`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${liveOccupancyBadgeDotClasses(card.tone)}`} />
                        {card.statusLabel}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-600 mb-2.5">
                      {(() => {
                        const counts = ownerUnitInviteCounts.get(card.unitLabel) ?? {
                          active: 0,
                          accepted: 0,
                          pending: 0,
                        };
                        return `${counts.pending} pending invites · ${counts.active} active invites · ${counts.accepted} accepted invites`;
                      })()}
                    </p>
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Lease / assignment</p>
                    {card.leases.length === 0 ? (
                      <p className="text-slate-600 text-sm">No tenant assignment on file for this unit on this snapshot.</p>
                    ) : (
                      <div className="space-y-3">
                        {groupLiveTenantRowsByCohort(card.leases).map((grp, gidx) => (
                          <div
                            key={`unit-${card.unitLabel}-cohort-${grp.cohortKey}-${gidx}`}
                            className={
                              grp.rows.length > 1
                                ? 'rounded-lg border border-emerald-200/70 bg-emerald-50/35 p-3 space-y-2'
                                : ''
                            }
                          >
                            {grp.rows.length > 1 ? (
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-900">
                                Shared lease · {grp.rows.length} tenants
                              </p>
                            ) : null}
                            <ul className="space-y-2.5">
                              {grp.rows.map((row, idx) => {
                                const resolvedKey = resolvedLeaseStatusKey(row);
                                const resolvedText = (row.lease_invite_resolved_status || '').trim();
                                const badge = leaseStatusBadgeForRow(row);
                                return (
                                  <li
                                    key={`unit-${card.unitLabel}-lease-${row.assignment_id ?? ''}-${row.stay_id ?? ''}-${grp.cohortKey}-${idx}`}
                                    className={
                                      idx > 0 ? 'border-t border-emerald-100/90 pt-2.5 mt-0.5' : ''
                                    }
                                  >
                                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                                      <span className="font-medium text-slate-800">{tenantAssignmentDisplayName(row)}</span>
                                    </div>
                                    {resolvedText ? (
                                      <p className="text-[11px] text-slate-700 mt-1 leading-snug">
                                        {unitCardLeaseInviteResolvedDisplay(resolvedText)}
                                      </p>
                                    ) : resolvedKey ? (
                                      <span
                                        className={`inline-flex mt-1 px-2 py-0.5 rounded text-[11px] font-semibold align-middle ${badge.className}`}
                                      >
                                        {badge.label}
                                      </span>
                                    ) : liveTenantAssignmentFallbackShowsPending(
                                        row,
                                        tenantInvitations,
                                        livePageTodayYmd,
                                        liveGuestOpenStayInviteCodes,
                                      ) ? (
                                      <p className="text-[11px] text-slate-700 mt-1 font-medium">Pending</p>
                                    ) : (
                                      <p className="text-[11px] text-slate-500 mt-1">—</p>
                                    )}
                                    <p className="text-xs text-slate-600 mt-0.5">{tenantLeasePeriodLabel(row)}</p>
                                    {row.tenant_email ? (
                                      <p className="text-xs text-slate-500 break-all mt-0.5">{row.tenant_email.trim()}</p>
                                    ) : null}
                                    {(() => {
                                      const pendingForTenant = pendingTenantInvitationsMatchingLiveAssignment(
                                        row,
                                        card.unitLabel,
                                        unitInviteCountCtx,
                                      );
                                      if (pendingForTenant.length === 0) return null;
                                      return (
                                        <p className="text-[11px] text-amber-900/90 mt-1.5 leading-snug">
                                          <span className="font-semibold">
                                            {pendingForTenant.length === 1
                                              ? '1 pending invite'
                                              : `${pendingForTenant.length} pending invites`}
                                          </span>
                                          <span className="text-slate-600">
                                            {' '}
                                            · Invite ID{pendingForTenant.length === 1 ? '' : 's'}:{' '}
                                          </span>
                                          <span className="font-mono text-slate-800">
                                            {pendingForTenant.map((i) => i.invitation_code).join(', ')}
                                          </span>
                                        </p>
                                      );
                                    })()}
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        {/* Tenant summary – same card pattern as Summary; violet accent for tenant lane */}
        <section className="bg-white rounded-2xl shadow-md border border-violet-200/80 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-violet-50 to-slate-50 border-b border-violet-200/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-violet-800">Tenant summary</h2>
            <p className="text-xs text-violet-700/90 mt-0.5">Machine-readable tenant context for verification</p>
            <p className="text-xs text-violet-600/80 mt-1 max-w-2xl">
              If you are <strong>signed in as a tenant</strong> for this property, this card shows <strong>your</strong>{' '}
              assignment on file. Otherwise it follows public occupancy rules (guest stay / invite / manager can hide
              the leaseholder on a unit). Properties without unit rows use checked-in tenant-lane stays when present.
            </p>
          </div>
          <div className="p-6 sm:p-8 space-y-4">
            {guestLinkAudience && invitingTenantLines.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Inviting tenant</p>
                <div className="space-y-2">
                  {invitingTenantLines.map((line, idx) => (
                    <div
                      key={`inviting-tenant-${line.email}-${idx}`}
                      className="rounded-lg border border-violet-200 bg-violet-50/50 px-3 py-2 text-sm text-slate-800"
                    >
                      <p>
                        <span className="font-semibold text-slate-700">Name:</span> {line.name}
                      </p>
                      <p>
                        <span className="font-semibold text-slate-700">Email:</span>{' '}
                        <span className="break-all">{line.email}</span>
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {tenantAssignmentsForTenantSummary.length > 0 && (
              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Assigned Tenant Record</p>
                <div className="space-y-4">
                  {tenantClientGroups.map((g, idx) => (
                    <div
                      key={`${g.cohortKey}-${idx}`}
                      className="rounded-xl border border-violet-200 bg-violet-50/60 p-4 sm:p-5 space-y-2 text-sm text-slate-800 shadow-sm"
                    >
                      <p className="text-xs font-semibold uppercase tracking-wider text-violet-800">
                        {g.rows.length > 1
                          ? 'Co-tenants (shared lease)'
                          : tenantClientGroups.length > 1
                            ? `Record Summary ${idx + 1}`
                            : 'Record Summary'}
                      </p>
                      {g.rows.length > 1 ? (
                        <p className="text-xs text-violet-900/90">
                          {g.rows.length} tenants on overlapping assignments for Unit {g.rows[0].unit_label}
                        </p>
                      ) : null}
                      {g.rows.map((row, j) => (
                        <div key={`${row.assignment_id ?? ''}-${row.stay_id ?? ''}-${j}`} className={j > 0 ? 'pt-3 mt-3 border-t border-violet-100' : ''}>
                          {row.assignment_id != null && row.assignment_id > 0 ? (
                            <p>
                              <span className="font-semibold text-slate-700">Tenant assignment ID:</span>{' '}
                              <span className="font-mono text-xs text-slate-900">{row.assignment_id}</span>
                            </p>
                          ) : null}
                          {!ownerViewingOwnLivePage && row.stay_id != null && row.stay_id > 0 ? (
                            <p>
                              <span className="font-semibold text-slate-700">Stay record (occupying):</span>{' '}
                              <span className="font-mono text-xs text-slate-900">{row.stay_id}</span>
                            </p>
                          ) : null}
                          <p>
                            <span className="font-semibold text-slate-700">Unit:</span>{' '}
                            <span className="font-mono text-xs text-slate-900">{row.unit_label}</span>
                          </p>
                          <p>
                            <span className="font-semibold text-slate-700">Name on record:</span>{' '}
                            {tenantAssignmentDisplayName(row)}
                          </p>
                          {row.tenant_email ? (
                            <p>
                              <span className="font-semibold text-slate-700">Email:</span>{' '}
                              <span className="break-all text-slate-800">{row.tenant_email}</span>
                            </p>
                          ) : null}
                          <p>
                            <span className="font-semibold text-slate-700">Lease window:</span> {tenantLeasePeriodLabel(row)}
                          </p>
                          <p>
                            <span className="font-semibold text-slate-700">Invite / lease resolved:</span>{' '}
                            <span className="text-slate-800">
                              {(row.lease_invite_resolved_status || '').trim() || '—'}
                            </span>
                          </p>
                          <p>
                            <span className="font-semibold text-slate-700">Assignment created:</span>{' '}
                            {formatDateTimeLocal(row.created_at)}
                          </p>
                        </div>
                      ))}
                      <p>
                        <span className="font-semibold text-slate-700">Property authorization (page):</span> {authLabel}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="grid gap-x-6 gap-y-2 text-sm">
              <p>
                <span className="font-semibold text-slate-700">Property:</span> {propertySummaryLine}
              </p>
              <p>
                <span className="font-semibold text-slate-700">Tenant assignment status:</span>{' '}
                {tenantAssignmentStatusSummaryLine}
              </p>
              <p>
                <span className="font-semibold text-slate-700">Assignee name:</span>{' '}
                {tenantSummaryAssigneeLine}
              </p>
              <p>
                <span className="font-semibold text-slate-700">Assignment period:</span>{' '}
                {tenantSummaryPeriodLine}
              </p>
              {!tenantScopeEnabled ? (
                <p>
                  <span className="font-semibold text-slate-700">Tenant invitations on record:</span>{' '}
                  {tenantInvitations.length > 0 ? `${tenantInvitations.length}` : '0'}
                </p>
              ) : null}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Assignee chain</p>
              <ul className="list-disc pl-5 space-y-0.5 text-sm text-slate-700">
                <li>
                  Owner verified: {owner.full_name ?? '—'}
                  {!tenantScopeEnabled && ownerEmailNormalized ? (
                    <span className="text-slate-600 break-all"> · {ownerEmailNormalized}</span>
                  ) : null}
                </li>
                {viewerIsTenant &&
                (tenantDashboardLeaseRow?.co_tenants ?? []).filter((p) => (p.name || p.email || '').trim()).length >
                  0 ? (
                  <li className="text-slate-600">
                    <span className="font-medium text-slate-800">Co-tenants (lease record):</span>{' '}
                    {formatCoTenantPeerLine(
                      (tenantDashboardLeaseRow?.co_tenants ?? []).filter((p) => (p.name || p.email || '').trim()),
                    )}
                  </li>
                ) : null}
                {activeTenantAssignmentsInSummaryWindow.length > 0 ? (
                  <li className="text-slate-600">
                    Active tenant(s) in lease window: {activeTenantAssignmentsInSummaryWindow.length} — see{' '}
                    <span className="font-medium text-slate-700">Assigned Tenant Record</span> for names and dates.
                  </li>
                ) : tenantAssignmentsForTenantSummary.length > 0 ? (
                  <li className="text-slate-600">
                    No active tenant in the current lease window — accepted assignment(s) on file; see{' '}
                    <span className="font-medium text-slate-700">Assigned Tenant Record</span>.
                  </li>
                ) : (
                  <li>No active tenant on file (another party may be occupying under a guest stay or manager resident).</li>
                )}
                {upcomingTenantStaysForView.slice(0, 3).map((s, i) => (
                  <li key={`up-${i}-${s.stay_start_date}`}>
                    Upcoming tenant (stay): {s.guest_name} · {formatCalendarDate(s.stay_start_date)} –{' '}
                    {formatCalendarDate(s.stay_end_date)}
                  </li>
                ))}
                {lastTenantStayForView && tenantAssignmentsForTenantSummary.length === 0 ? (
                  <li>
                    Last tenant (stay): {lastTenantStayForView.guest_name} ·{' '}
                    {formatCalendarDate(lastTenantStayForView.stay_start_date)} –{' '}
                    {formatCalendarDate(lastTenantStayForView.stay_end_date)}
                    {lastTenantStayForView.checked_out_at
                      ? ` · ended ${formatCalendarDate(lastTenantStayForView.checked_out_at)}`
                      : null}
                  </li>
                ) : null}
              </ul>
            </div>
            {jurisdiction_wrap && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Legal context</p>
                <p className="font-semibold text-slate-700">{jurisdiction_wrap.state_name}</p>
                <p className="text-xs text-slate-500 mt-2 leading-relaxed border border-slate-200 bg-slate-50/80 rounded-lg px-3 py-2">
                  {JURISDICTION_CONTEXT_DISCLAIMER}
                </p>
                {jurisdiction_wrap.applicable_statutes?.length > 0 && (
                  <ul className="list-disc pl-5 mt-2 space-y-0.5 text-sm text-slate-600">
                    {jurisdiction_wrap.applicable_statutes.map((s, i) => (
                      <li key={i}>
                        <span className="font-medium text-slate-800">{s.citation}</span>
                        {s.plain_english ? (
                          <span className="block text-slate-500 text-xs mt-0.5">
                            Reference summary (informational): {s.plain_english}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <p className="text-sm text-slate-700 pt-1">
              {tenantAssignmentsForTenantSummary.length > 0 ? (
                <span>
                  Details above match your session when you are the assigned tenant for this property; otherwise they
                  follow public occupancy rules (see header). Invitation states and the audit timeline add full history.
                  {viewerIsTenant && tenantDashboardLeaseRow?.co_tenants?.length
                    ? ' Co-tenant names on this card match your signed-in tenant lease record when this live link is tied to that unit.'
                    : null}
                </span>
              ) : (
                <span>
                  No tenant summary row for this view—either no assignment on file for your account on this property,
                  or public occupancy did not resolve a leaseholder tenant for the unit(s). Check invitations and the
                  Quick Decision layer for active stays.
                </span>
              )}
            </p>
          </div>
        </section>

        {/* Third Section – Condensed Audit Timeline (Part B) */}
        <section className="bg-white rounded-2xl shadow-md border border-slate-200 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-violet-50 to-slate-50 border-b border-violet-100/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-violet-800">Condensed Audit Timeline</h2>
          </div>
          <div className="p-6 sm:p-8">
            <ul className="space-y-2 text-sm text-slate-700">
              <li><span className="font-medium text-slate-900">Owner authorization signed</span> – {poaTimestampFormatted ?? '—'}</li>
              <li><span className="font-medium text-slate-900">Property onboarded</span> – {propertyOnboardedAt ?? '—'}</li>
              <li>
                <span className="font-medium text-slate-900">Status changes</span> –
                {statusChangeLogs.length > 0
                  ? ` ${statusChangeLogs.slice(0, 5).map((e) => formatDateTimeLocal(e.created_at)).join(', ')}${statusChangeLogs.length > 5 ? ' …' : ''}`
                  : ' —'}
              </li>
              <li>
                <span className="font-medium text-slate-900">Status changes (active / expired / revoked)</span> –
                {tokenEventLogs.length > 0
                  ? ` ${tokenEventLogs.slice(0, 5).map((e) => formatDateTimeLocal(e.created_at)).join(', ')}${tokenEventLogs.length > 5 ? ' …' : ''}`
                  : ' —'}
              </li>
            </ul>
            <LiveAuditTimelineRecordFootnote />
          </div>
        </section>

        {/* Invitation states – stay status */}
        <section className="bg-white rounded-2xl shadow-md border border-teal-200/80 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-teal-50 to-slate-50 border-b border-teal-200/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-teal-800">Invitation states</h2>
            <p className="text-xs text-teal-700/90 mt-0.5">
              Invite ID, associated unit, assignee, and assignment state map each invitation to a stay on this snapshot.
            </p>
          </div>
          <div className="p-6 sm:p-8">
            {ownerViewingOwnLivePage && (
              <p className="text-xs text-teal-900/90 mb-4 rounded-lg border border-teal-100 bg-teal-50/60 px-3 py-2">
                Guest invitations and guest stay confirmations are not listed here. Use <strong>DocuStay → Guests</strong>{' '}
                for short-term guest flow; this table shows tenant lease invitations only.
              </p>
            )}
            <details className="mb-4 group">
              <summary className="cursor-pointer text-xs font-semibold text-teal-700 list-none flex items-center gap-1 hover:text-teal-800">
                <span className="group-open:rotate-90 transition-transform text-teal-600">▶</span> Assignment states legend
              </summary>
              <ul className="mt-2 pl-4 space-y-0.5 text-xs text-slate-600 border-l-2 border-teal-200">
                <li><strong>PENDING</strong> — Record indicates the invite is pending acceptance (no in-window authorization readout yet).</li>
                <li><strong>ACCEPTED</strong> — Record indicates acceptance before the lease start date (no in-window authorization readout yet).</li>
                <li><strong>ACTIVE</strong> — Record indicates acceptance and today falls within the stored lease window on this snapshot.</li>
                <li><strong>EXPIRED</strong> — Record indicates the stored window ended or the invite was closed; no current in-window readout.</li>
                <li><strong>REVOKED</strong> — Record indicates the host revoked guest authorization on file.</li>
                <li><strong>CANCELLED</strong> — Record indicates the tenant cancelled the assignment (DocuStay does not revoke tenants).</li>
              </ul>
            </details>
            {(!invitationsForDisplay || invitationsForDisplay.length === 0) ? (
              <p className="text-slate-500 text-sm">No invitations recorded for this property.</p>
            ) : (
              <div className="overflow-x-auto -mx-1 rounded-lg border border-teal-100 overflow-hidden">
                <table className="w-full text-sm border-collapse min-w-[38rem]">
                  <thead>
                    <tr className="bg-teal-50/80 border-b-2 border-teal-200">
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Invite ID</th>
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Type</th>
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Unit</th>
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Assignee</th>
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Authorization period</th>
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Status</th>
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Assignment state</th>
                      <th className="text-left py-3 font-semibold text-teal-800">Signed agreement</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invitationsForDisplay.map((inv, i) => (
                      <tr key={inv.invitation_code + i} className={`border-b border-slate-100 last:border-0 transition-colors ${i % 2 === 0 ? 'bg-white' : 'bg-teal-50/30'} hover:bg-teal-50/60`}>
                        <td className="py-3 pr-4 font-mono text-slate-800 text-xs">{inv.invitation_code}</td>
                        <td className="py-3 pr-4">
                          <span
                            className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${
                              inviteIsTenant(inv) ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-700'
                            }`}
                          >
                            {inviteIsTenant(inv) ? 'Tenant' : 'Guest'}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-slate-800 font-medium tabular-nums whitespace-nowrap">
                          {liveInvitationTableUnitLabel(inv, !!prop.is_multi_unit)}
                        </td>
                        <td className="py-3 pr-4 text-slate-700">{inv.guest_label ?? '—'}</td>
                        <td className="py-3 pr-4 text-slate-700 whitespace-nowrap">
                          {formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}
                        </td>
                        <td className="py-3 pr-4">
                          <span
                            className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${liveInviteStatusDisplayClass(inv, livePageTodayYmd, liveGuestOpenStayInviteCodes)}`}
                          >
                            {liveInviteStatusDisplayLabel(inv, livePageTodayYmd, liveGuestOpenStayInviteCodes)}
                          </span>
                        </td>
                        <td className="py-3 pr-4">
                          {(() => {
                            const label = mapInvitationToAuthorizationLabel(inv, livePageTodayYmd, liveGuestOpenStayInviteCodes);
                            const cls = label === 'ACTIVE' ? 'bg-emerald-100 text-emerald-800'
                              : label === 'ACCEPTED' ? 'bg-sky-100 text-sky-800'
                              : label === 'EXPIRED' ? 'bg-amber-100 text-amber-800'
                              : label === 'PENDING' ? 'bg-amber-50 text-amber-700'
                              : 'bg-slate-100 text-slate-700';
                            return (
                              <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${cls}`}>
                                {label === 'ACTIVE' ? 'Active' : label === 'ACCEPTED' ? 'Accepted' : label === 'EXPIRED' ? 'Expired' : label === 'PENDING' ? 'Pending' : label === 'CANCELLED' ? 'Cancelled' : label === 'REVOKED' ? 'Revoked' : label}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="py-3">
                          {inv.signed_agreement_available && inv.signed_agreement_url ? (
                            <a
                              href={resolveBackendMediaUrl(inv.signed_agreement_url)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-sm font-medium text-teal-800 hover:text-teal-900 underline underline-offset-2"
                            >
                              View PDF
                            </a>
                          ) : (
                            <span className="text-xs text-slate-400">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>

        {/* Audit timeline */}
        <section className="bg-white rounded-2xl shadow-md border border-violet-200/80 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-violet-50 to-slate-50 border-b border-violet-200/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-violet-800">Audit timeline</h2>
          </div>
          <div className="p-6 sm:p-8">
            {logsForAuditTimeline.length === 0 ? (
              <p className="text-slate-500 text-sm">No activity recorded yet.</p>
            ) : (
              <ul className="space-y-0 max-h-[26rem] overflow-y-auto pr-1 print:max-h-none">
                {logsForAuditTimeline.map((entry, i) => (
                  <li key={i} className="relative pl-6 pb-5 last:pb-0">
                    {i < logsForAuditTimeline.length - 1 && (
                      <span className="absolute left-[5px] top-2 bottom-0 w-px bg-violet-200" />
                    )}
                    <span className="absolute left-0 top-0.5 w-2.5 h-2.5 rounded-full bg-violet-500 border-2 border-white shadow-sm" />
                    <div className="pt-0.5">
                      <p className="font-medium text-slate-800">{scrubLiveEvidenceText(entry.title)}</p>
                      <p className="text-slate-600 text-sm mt-0.5">
                        {scrubLiveEvidenceText(scrubAuditLogStateChangeParagraph(entry.message))}
                      </p>
                      <LiveAuditActorAttribution entry={entry} />
                      <p className="text-xs text-slate-400 mt-2 flex items-center gap-2 flex-wrap">
                        <span className="inline-flex px-1.5 py-0.5 rounded bg-violet-100 text-violet-800 font-medium">
                          {scrubLiveEvidenceText(entry.category.replace(/_/g, ' '))}
                        </span>
                        <span className="text-slate-500">{formatDateTimeLocal(entry.created_at)}</span>
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <LiveAuditTimelineRecordFootnote />
          </div>
        </section>

        {/* Last / upcoming (when no current guest) */}
        {!tenantScopeEnabled &&
          !has_current_guest &&
          (lastStayForOwnerView || upcomingStaysForOwnerView.length > 0) && (
          <section className="bg-white rounded-2xl shadow-md border border-sky-200/80 overflow-hidden print:rounded print:shadow-none print:border">
            <div className="px-6 py-3.5 bg-gradient-to-r from-sky-50 to-slate-50 border-b border-sky-200/80">
              <h2 className="text-sm font-bold uppercase tracking-wider text-sky-800">{upcomingSectionTitle}</h2>
            </div>
            <div className="p-6 flex flex-wrap gap-6 sm:gap-8 text-sm">
              {lastStayForOwnerView && (
                <div className="flex-1 min-w-[12rem] rounded-lg bg-slate-50 border border-slate-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-0.5">
                    {(lastStayForOwnerView.stay_kind ?? 'guest').toLowerCase() === 'tenant' ? 'Tenant' : 'Guest'}
                  </p>
                  <p className="text-slate-900 font-medium">{lastStayForOwnerView.guest_name}</p>
                  <p className="text-slate-600">{formatCalendarDate(lastStayForOwnerView.stay_start_date)} – {formatCalendarDate(lastStayForOwnerView.stay_end_date)}</p>
                </div>
              )}
              {upcomingStaysForOwnerView.slice(0, 3).map((s, i) => (
                <div key={i} className="flex-1 min-w-[12rem] rounded-lg bg-sky-50/60 border border-sky-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-0.5">
                    {(s.stay_kind ?? 'guest').toLowerCase() === 'tenant' ? 'Upcoming tenant stay' : 'Upcoming guest stay'}
                  </p>
                  <p className="text-slate-900 font-medium">{s.guest_name}</p>
                  <p className="text-slate-600">{formatCalendarDate(s.stay_start_date)} – {formatCalendarDate(s.stay_end_date)}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        <footer className="pt-6 pb-10 text-center border-t border-indigo-100 print:pt-2 print:pb-4 print:border-0">
          <p className="text-xs text-slate-500 leading-relaxed max-w-5xl mx-auto">
            Record indicates this page is a read-only snapshot of DocuStay data as of the timestamp above. It does not certify legal rights, occupancy, or authority. Where agreements or owner authorization documents are referenced, the underlying signed files are separate artifacts; this view summarizes what DocuStay stored at generation time. Audit entries below are append-only rows (they are not edited or removed through this interface after creation).
          </p>
          <p className="text-xs text-slate-600 font-medium">DocuStay · Live evidence page · Read-only</p>
          <p className="text-xs text-slate-400 mt-1">Record {record_id} · {formatDateTimeLocal(generated_at)}</p>
        </footer>
      </div>

      <style>{`
        @media print {
          body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
          .print\\:bg-white { background: white !important; }
          .print\\:max-h-none { max-height: none !important; }
        }
      `}</style>
    </div>
  );
};

/** Catches render/runtime errors so the public live page never shows a blank React error screen. */
export class LivePropertyPageErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-gradient-to-br from-indigo-50/70 via-white to-slate-100/60 flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border border-indigo-100 p-10 text-center">
            <div className="w-14 h-14 rounded-full bg-indigo-100 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <h1 className="text-xl font-semibold text-slate-800 mb-2">Something went wrong on this page</h1>
            <p className="text-slate-600 leading-relaxed">
              An unexpected error occurred while displaying the live property record. Try refreshing the page.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-6 px-5 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 shadow-sm transition-colors"
            >
              Refresh page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}


