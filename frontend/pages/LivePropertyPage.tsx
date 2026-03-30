import React, { useState, useEffect } from 'react';
import {
  authApi,
  publicApi,
  resolveBackendMediaUrl,
  type LiveCurrentGuestInfo,
  type LiveInvitationSummary,
  type LiveOwnerInfo,
  type LivePropertyManagerInfo,
  type LivePropertyPagePayload,
  type LiveTenantAssignmentInfo,
  type UserSession,
} from '../services/api';

function stayIsTenant(stay: Pick<LiveCurrentGuestInfo, 'stay_kind'>): boolean {
  return (stay.stay_kind ?? 'guest').toLowerCase() === 'tenant';
}

function inviteIsTenant(inv: Pick<LiveInvitationSummary, 'invitation_kind'>): boolean {
  return (inv.invitation_kind ?? 'guest').toLowerCase() === 'tenant';
}

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatDateTime(s: string): string {
  return new Date(s).toLocaleString('en-US', { dateStyle: 'short', timeStyle: 'short' });
}

function statusDisplay(status: string): string {
  const s = (status || 'unknown').toLowerCase();
  if (s === 'vacant') return 'VACANT';
  if (s === 'occupied') return 'OCCUPIED';
  if (s === 'unconfirmed') return 'UNCONFIRMED';
  return 'UNKNOWN';
}

function authDisplay(auth: string): string {
  const a = (auth || 'none').toUpperCase();
  if (a === 'ACTIVE' || a === 'NONE' || a === 'EXPIRED' || a === 'REVOKED') return a;
  return 'NONE';
}

function tenantAssignmentDisplayName(row: LiveTenantAssignmentInfo): string {
  return (row.tenant_full_name || row.tenant_email || '—').trim() || '—';
}

function tenantLeasePeriodLabel(row: LiveTenantAssignmentInfo): string {
  const start = formatDate(row.start_date);
  if (!row.end_date) return `${start} – Open-ended`;
  return `${start} – ${formatDate(row.end_date)}`;
}

function normalizeEmail(s: string): string {
  return (s || '').trim().toLowerCase();
}

function normalizeLooseName(s: string): string {
  return (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
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

export const LivePropertyPage: React.FC<{ slug: string }> = ({ slug }) => {
  const [data, setData] = useState<LivePropertyPagePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewerSession, setViewerSession] = useState<UserSession | null>(null);

  useEffect(() => {
    if (!slug) {
      setError('Invalid link');
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

  const viewerIsGuest = viewerSession?.user_type === 'GUEST';

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
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50/70 via-white to-slate-100/60 flex items-center justify-center p-6 print:bg-white">
        <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border border-indigo-100 p-10 text-center">
          <div className="w-14 h-14 rounded-full bg-indigo-100 flex items-center justify-center mx-auto mb-4">
            <svg className="w-7 h-7 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-slate-800 mb-2">Property not found</h1>
          <p className="text-slate-600">{error ?? 'This link may be invalid or expired.'}</p>
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
    authorization_state,
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
  const statusLabel = statusDisplay(prop.occupancy_status);
  const authLabel = authDisplay(authorization_state);
  const isVacant = (prop.occupancy_status || '').toLowerCase() === 'vacant' && !has_current_guest;
  const liveLink = typeof window !== 'undefined' ? window.location.href : `#live/${slug}`;
  const poaPdfUrl = publicApi.getLivePoaPdfUrl(slug);

  const upcomingSectionTitle =
    upcoming_stays.length > 0
      ? (() => {
          const kinds = new Set(
            upcoming_stays.map((s) =>
              (s.stay_kind ?? 'guest').toLowerCase() === 'tenant' ? 'tenant' : 'guest',
            ),
          );
          if (kinds.has('guest') && kinds.has('tenant')) return 'Upcoming guest & tenant stays';
          if (kinds.has('tenant')) return 'Upcoming tenant stays';
          return 'Upcoming guest stays';
        })()
      : last_stay
        ? (last_stay.stay_kind ?? 'guest').toLowerCase() === 'tenant'
          ? 'Last tenant stay'
          : 'Last guest stay'
        : 'Stays';

  const poaTimestampFormatted = poa_signed_at ? formatDateTime(poa_signed_at) : null;

  // Condensed Audit Timeline (Part B): POA signed, property onboarded, status changes (active/expired/revoked)
  const oldestLog = logs.length > 0 ? logs[logs.length - 1] : null;
  const propertyOnboardedAt = oldestLog ? formatDateTime(oldestLog.created_at) : null;
  const statusChangeLogs = logs.filter(
    (e) =>
      e.category === 'status_change' ||
      /status|vacant|occupancy|confirmed|vacated|check.?in|checkout/i.test(e.title || '') ||
      /status|vacant|occupancy|confirmed|vacated/i.test(e.message || '')
  );
  const tokenEventLogs = logs.filter(
    (e) =>
      /invitation|invite|stay|token|burn|expire|revoke|signed|agreement|checkout|check.?in/i.test(e.category || '') ||
      /invitation|invite|stay|token|burn|expire|revoke|signed|agreement|checkout|check.?in/i.test(e.title || '')
  );

  const upcomingTenantStays = upcoming_stays.filter((s) => stayIsTenant(s));
  const lastTenantStay = last_stay && stayIsTenant(last_stay) ? last_stay : null;
  const invitationsForDisplay = viewerIsGuest
    ? invitations.filter((inv) => !inviteIsTenant(inv))
    : invitations;
  const tenantInvitations = invitationsForDisplay.filter(inviteIsTenant);
  const propertyManagersForAuthority: LivePropertyManagerInfo[] = (property_managers ?? []).filter(
    (m) => typeof m?.email === 'string' && m.email.trim().length > 0,
  );
  const currentTenantAssignments: LiveTenantAssignmentInfo[] = current_tenant_assignments ?? [];
  const propertySummaryLine = [prop.name || '', address].filter(Boolean).join(' — ') || address || '—';

  const authorityTenantAssignmentsUnique = (() => {
    const seen = new Set<string>();
    const out: LiveTenantAssignmentInfo[] = [];
    for (const row of currentTenantAssignments) {
      const key = [
        (row.unit_label || '').trim(),
        normalizeEmail(row.tenant_email || ''),
        normalizeLooseName(row.tenant_full_name || ''),
        (row.start_date || '').trim(),
        (row.end_date || '').trim(),
      ].join('|');
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(row);
    }
    return out;
  })();

  const sessionAuthorityChainLines: { key: string; prefix: string; name: string; email: string }[] = [];
  if (viewerSession) {
    if (viewerSession.user_type === 'GUEST') {
      activeGuestsOnly
        .filter((stay) => guestStayMatchesViewer(stay, invitations, viewerSession))
        .forEach((stay, idx) => {
          sessionAuthorityChainLines.push({
            key: `chain-g-${stay.stay_id}-${idx}`,
            prefix: 'Guest (active authorization)',
            name: stay.guest_name,
            email: viewerSession.email.trim() || '—',
          });
        });
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50/70 via-white to-slate-100/60 print:bg-white print:min-h-0">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6 print:py-6 print:max-w-none">
        {/* Meta bar: record, timestamp, link, print */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm bg-white/90 backdrop-blur rounded-xl border border-indigo-100 px-4 py-3 shadow-sm print:bg-white print:border-slate-200">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-slate-600">
            <span className="inline-flex items-center gap-1.5">
              <span className="font-medium text-indigo-700">Record</span>
              <span className="font-mono text-slate-800 bg-slate-100 px-1.5 py-0.5 rounded">{record_id}</span>
            </span>
            <span className="text-slate-500">Generated {formatDateTime(generated_at)}</span>
            <a href={liveLink} className="text-indigo-600 hover:text-indigo-700 font-medium hover:underline break-all" target="_blank" rel="noopener noreferrer">Live link</a>
          </div>
          <button
            type="button"
            onClick={() => window.print()}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 shadow-sm print:hidden transition-colors"
          >
            Print page
          </button>
        </div>

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
              {ownerEmailNormalized ? (
                <span className="text-slate-600 break-all"> · {ownerEmailNormalized}</span>
              ) : null}
            </p>
            <div className="flex flex-wrap gap-4 sm:gap-6 mb-4">
              <div>
                <p className="text-xs font-medium text-slate-500 mb-0.5">Current property status</p>
                <span
                  className={`inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-semibold uppercase ${
                    statusLabel === 'OCCUPIED'
                      ? 'bg-emerald-100 text-emerald-800'
                      : statusLabel === 'VACANT'
                        ? 'bg-sky-100 text-sky-800'
                        : 'bg-slate-100 text-slate-700'
                  }`}
                >
                  {statusLabel}
                </span>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 mb-0.5">Authorization state</p>
                <span
                  className={`inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-semibold uppercase ${
                    authLabel === 'ACTIVE'
                      ? 'bg-emerald-100 text-emerald-800'
                      : authLabel === 'REVOKED'
                        ? 'bg-red-100 text-red-800'
                        : authLabel === 'EXPIRED'
                          ? 'bg-amber-100 text-amber-800'
                          : 'bg-slate-100 text-slate-700'
                  }`}
                >
                  {authLabel}
                </span>
              </div>
            </div>
            {hasActiveOccupants && (
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
                            {formatDate(t.stay_start_date)} – {formatDate(t.stay_end_date)}
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
                          {formatDate(g.stay_start_date)} – {formatDate(g.stay_end_date)}
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

        {/* Authority layer – POA and jurisdiction (moved up for context) */}
        <section className="bg-white rounded-2xl shadow-md border border-slate-200 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-indigo-50 to-slate-50 border-b border-indigo-100/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-indigo-800">Authority</h2>
          </div>
          <div className="p-6 sm:p-8 space-y-4">
            <p className="text-slate-700">
              This property is documented under a signed <strong>Master Power of Attorney (POA)</strong>.
            </p>
            {poa_signed_at && (
              <p className="text-slate-700">
                POA signed: <strong>{formatDate(poa_signed_at)}</strong>. Owner: <strong>{owner.full_name ?? '—'}</strong>.
              </p>
            )}
            <p className="text-slate-600 text-sm">
              DocuStay operates under the granted documentation authority of the owner. Records are immutable and append-only.
            </p>
            {poa_signature_id != null && (
              <div className="space-y-2">
                <a
                  href={poaPdfUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 text-white font-medium hover:bg-indigo-700 shadow-sm transition-colors print:no-underline print:text-slate-900 print:border print:border-slate-300 print:bg-transparent"
                >
                  View POA
                </a>
                <p className="text-sm text-slate-600">
                  Signed by <strong>{owner.full_name ?? '—'}</strong>. The signed POA document (linked above) contains the full signature.
                </p>
              </div>
            )}
            <div className="pt-4 border-t border-slate-200">
              <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600/90">Property identifier</p>
              <p className="text-slate-900 mt-0.5">{address || '—'}</p>
              {(prop.apn || prop.tax_id) && (
                <p className="text-slate-600 text-sm mt-1">
                  {prop.apn && <span>APN: {prop.apn}</span>}
                  {prop.apn && prop.tax_id && ' · '}
                  {prop.tax_id && <span>Tax ID: {prop.tax_id}</span>}
                </p>
              )}
            </div>
            {jurisdiction_wrap && jurisdiction_wrap.applicable_statutes?.length > 0 && (
              <div className="pt-4 border-t border-slate-200">
                <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600/90">Applicable law ({jurisdiction_wrap.state_name})</p>
                <ul className="mt-2 space-y-2">
                  {jurisdiction_wrap.applicable_statutes.map((s, i) => (
                    <li key={i} className="text-sm text-slate-700">
                      <span className="font-medium text-slate-900">{s.citation}</span>
                      {s.plain_english && <span className="block text-slate-600 mt-0.5">{s.plain_english}</span>}
                    </li>
                  ))}
                </ul>
                {jurisdiction_wrap.removal_guest_text && (
                  <p className="text-slate-600 text-sm mt-2">
                    <span className="font-medium text-slate-700">Guest removal: </span>{jurisdiction_wrap.removal_guest_text}
                  </p>
                )}
                {jurisdiction_wrap.removal_tenant_text && (
                  <p className="text-slate-600 text-sm mt-0.5">
                    <span className="font-medium text-slate-700">Tenant eviction: </span>{jurisdiction_wrap.removal_tenant_text}
                  </p>
                )}
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
              <p><span className="font-semibold text-slate-700">Status:</span> {statusLabel}</p>
              <p>
                <span className="font-semibold text-slate-700">Owner email:</span>{' '}
                <span className="break-all text-slate-800">{ownerEmailNormalized || '—'}</span>
              </p>
              <p>
                <span className="font-semibold text-slate-700">Last confirmed:</span>{' '}
                {hasActiveOccupants
                  ? activeGuests.length === 1
                    ? `Current (through ${formatDate(activeGuests[0].stay_end_date)})`
                    : (() => {
                        const parts: string[] = [];
                        if (activeTenants.length > 0) {
                          parts.push(
                            `${activeTenants.length} active tenant${activeTenants.length > 1 ? 's' : ''}`,
                          );
                        }
                        if (activeGuestsOnly.length > 0) {
                          parts.push(
                            `${activeGuestsOnly.length} guest authorization${activeGuestsOnly.length > 1 ? 's' : ''}`,
                          );
                        }
                        return parts.length > 0 ? `Current — ${parts.join(', ')}` : `Current — ${activeGuests.length} active`;
                      })()
                  : last_stay
                    ? formatDate(last_stay.checked_out_at || last_stay.stay_end_date)
                    : formatDate(generated_at)}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Authority chain</p>
              <ul className="list-disc pl-5 space-y-0.5 text-sm text-slate-700">
                <li>
                  Owner verified: {owner.full_name ?? '—'}
                  {ownerEmailNormalized ? (
                    <span className="text-slate-600 break-all"> · {ownerEmailNormalized}</span>
                  ) : null}
                </li>
                {poa_signed_at && (
                  <li>Master POA executed: {formatDate(poa_signed_at)}</li>
                )}
                {propertyManagersForAuthority.map((m, idx) => (
                  <li key={`${m.email}-${idx}`}>
                    Property manager: {m.full_name ?? '—'}
                    <span className="text-slate-600 break-all"> · {m.email.trim()}</span>
                  </li>
                ))}
                {authorityTenantAssignmentsUnique.map((row, idx) => (
                  <li key={`tenant-auth-${row.assignment_id ?? ''}-${row.stay_id ?? ''}-${row.unit_label}-${idx}`}>
                    {(() => {
                      return (
                        <>
                          Tenant (Unit {row.unit_label}): {tenantAssignmentDisplayName(row)}
                        </>
                      );
                    })()}
                    {row.tenant_email ? (
                      <span className="text-slate-600 break-all"> · {row.tenant_email}</span>
                    ) : null}
                  </li>
                ))}
                {authorityTenantAssignmentsUnique.length === 0 && tenant_summary_assignee ? (
                  <li>
                    Tenant: {tenant_summary_assignee.trim() || '—'}
                    {tenant_summary_assignment_period ? (
                      <span className="text-slate-600"> · {tenant_summary_assignment_period}</span>
                    ) : null}
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
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Jurisdiction</p>
                <p className="font-semibold text-slate-700">{jurisdiction_wrap.state_name}</p>
                {jurisdiction_wrap.applicable_statutes?.length > 0 && (
                  <ul className="list-disc pl-5 mt-1 space-y-0.5 text-sm text-slate-600">
                    {jurisdiction_wrap.applicable_statutes.map((s, i) => (
                      <li key={i}>{s.citation}{s.plain_english ? `: ${s.plain_english}` : ''}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <p className="text-sm text-slate-700 pt-1">
              {hasActiveOccupants ? (
                <span>
                  {activeTenants.length > 0 && activeGuestsOnly.length > 0
                    ? 'Active tenant and guest assignments (current stays).'
                    : activeTenants.length > 0
                      ? activeTenants.length > 1
                        ? 'Active tenant assignments (current stays).'
                        : 'Active tenant assignment (current stay).'
                      : activeGuests.length > 1
                        ? 'Active guest assignments (current stays).'
                        : 'Active guest assignment (current stay).'}{' '}
                  Signed agreements on this page are only for these active authorizations; prior agreements appear in the audit timeline below.
                </span>
              ) : currentTenantAssignments.length > 0 ? (
                <span>
                  Active tenant lease assignment(s) on file for this property (see Tenant summary).{' '}
                  No guest-stay check-in is currently recorded on this live record.{' '}
                  Prior activity appears in the audit timeline below.
                </span>
              ) : sessionAuthorityChainLines.length > 0 ? (
                <span>
                  Your role on this property is listed in the authority chain above. See the Quick Decision layer and
                  Tenant summary for full occupancy context.
                </span>
              ) : (
                <span>No active guest or tenant assignments.</span>
              )}
            </p>
          </div>
        </section>

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
            {currentTenantAssignments.length > 0 && (
              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Current client</p>
                <div className="space-y-4">
                  {currentTenantAssignments.map((row, idx) => (
                    <div
                      key={`${row.assignment_id ?? ''}-${row.stay_id ?? ''}-${idx}`}
                      className="rounded-xl border border-violet-200 bg-violet-50/60 p-4 sm:p-5 space-y-2 text-sm text-slate-800 shadow-sm"
                    >
                      <p className="text-xs font-semibold uppercase tracking-wider text-violet-800">
                        {currentTenantAssignments.length > 1 ? `Tenant client ${idx + 1}` : 'Tenant client'}
                      </p>
                      {row.assignment_id != null && row.assignment_id > 0 ? (
                        <p>
                          <span className="font-semibold text-slate-700">Tenant assignment ID:</span>{' '}
                          <span className="font-mono text-xs text-slate-900">{row.assignment_id}</span>
                        </p>
                      ) : null}
                      {row.stay_id != null && row.stay_id > 0 ? (
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
                        <span className="font-semibold text-slate-700">Assignment created:</span>{' '}
                        {formatDateTime(row.created_at)}
                      </p>
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
                {currentTenantAssignments.length > 0
                  ? currentTenantAssignments.length > 1
                    ? `CURRENT — ${currentTenantAssignments.length} occupying tenant(s)`
                    : 'CURRENT — 1 occupying tenant'
                  : upcomingTenantStays.length > 0
                    ? `UPCOMING — ${upcomingTenantStays.length} scheduled stay (invitation)${upcomingTenantStays.length > 1 ? 's' : ''}`
                    : lastTenantStay
                      ? 'NO OCCUPYING TENANT (last tenant stay ended)'
                      : 'NO OCCUPYING TENANT ON FILE'}
              </p>
              <p>
                <span className="font-semibold text-slate-700">Assignee name:</span>{' '}
                {(tenant_summary_assignee && tenant_summary_assignee.trim()) ||
                  (currentTenantAssignments.length > 0
                    ? currentTenantAssignments.map((r) => tenantAssignmentDisplayName(r)).join(' · ')
                    : '—')}
              </p>
              <p>
                <span className="font-semibold text-slate-700">Assignment period:</span>{' '}
                {(tenant_summary_assignment_period && tenant_summary_assignment_period.trim()) ||
                  (currentTenantAssignments.length === 1
                    ? tenantLeasePeriodLabel(currentTenantAssignments[0])
                    : currentTenantAssignments.length > 1
                      ? 'Multiple (see Current client)'
                      : upcomingTenantStays.length > 0
                        ? `${formatDate(upcomingTenantStays[0].stay_start_date)} – ${formatDate(upcomingTenantStays[0].stay_end_date)} (upcoming stay)`
                        : lastTenantStay
                          ? `${formatDate(lastTenantStay.stay_start_date)} – ${formatDate(lastTenantStay.stay_end_date)} (last stay)`
                          : '—')}
              </p>
              <p>
                <span className="font-semibold text-slate-700">Tenant invitations on record:</span>{' '}
                {tenantInvitations.length > 0 ? `${tenantInvitations.length}` : '0'}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Assignee chain</p>
              <ul className="list-disc pl-5 space-y-0.5 text-sm text-slate-700">
                <li>
                  Owner verified: {owner.full_name ?? '—'}
                  {ownerEmailNormalized ? (
                    <span className="text-slate-600 break-all"> · {ownerEmailNormalized}</span>
                  ) : null}
                </li>
                {currentTenantAssignments.length > 0 ? (
                  <li className="text-slate-600">
                    Occupying tenant(s): see <span className="font-medium text-slate-700">Current client</span> (matches
                    unit occupancy priority).
                  </li>
                ) : (
                  <li>No occupying tenant on file (another party may be occupying under a guest stay or manager resident).</li>
                )}
                {upcomingTenantStays.slice(0, 3).map((s, i) => (
                  <li key={`up-${i}-${s.stay_start_date}`}>
                    Upcoming tenant (stay): {s.guest_name} · {formatDate(s.stay_start_date)} –{' '}
                    {formatDate(s.stay_end_date)}
                  </li>
                ))}
                {lastTenantStay && currentTenantAssignments.length === 0 ? (
                  <li>
                    Last tenant (stay): {lastTenantStay.guest_name} ·{' '}
                    {formatDate(lastTenantStay.stay_start_date)} – {formatDate(lastTenantStay.stay_end_date)}
                    {lastTenantStay.checked_out_at
                      ? ` · ended ${formatDate(lastTenantStay.checked_out_at)}`
                      : null}
                  </li>
                ) : null}
              </ul>
            </div>
            {jurisdiction_wrap && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Jurisdiction</p>
                <p className="font-semibold text-slate-700">{jurisdiction_wrap.state_name}</p>
                {jurisdiction_wrap.applicable_statutes?.length > 0 && (
                  <ul className="list-disc pl-5 mt-1 space-y-0.5 text-sm text-slate-600">
                    {jurisdiction_wrap.applicable_statutes.map((s, i) => (
                      <li key={i}>
                        {s.citation}
                        {s.plain_english ? `: ${s.plain_english}` : ''}
                      </li>
                    ))}
                  </ul>
                )}
                {jurisdiction_wrap.removal_tenant_text ? (
                  <p className="text-slate-600 text-sm mt-2">
                    <span className="font-medium text-slate-700">Tenant eviction: </span>
                    {jurisdiction_wrap.removal_tenant_text}
                  </p>
                ) : null}
              </div>
            )}
            <p className="text-sm text-slate-700 pt-1">
              {currentTenantAssignments.length > 0 ? (
                <span>
                  Details above match your session when you are the assigned tenant for this property; otherwise they
                  follow public occupancy rules (see header). Invitation states and the audit timeline add full history.
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
              <li><span className="font-medium text-slate-900">POA signed</span> – {poaTimestampFormatted ?? '—'}</li>
              <li><span className="font-medium text-slate-900">Property onboarded</span> – {propertyOnboardedAt ?? '—'}</li>
              <li>
                <span className="font-medium text-slate-900">Status changes</span> –
                {statusChangeLogs.length > 0
                  ? ` ${statusChangeLogs.slice(0, 5).map((e) => formatDateTime(e.created_at)).join(', ')}${statusChangeLogs.length > 5 ? ' …' : ''}`
                  : ' —'}
              </li>
              <li>
                <span className="font-medium text-slate-900">Status changes (active / expired / revoked)</span> –
                {tokenEventLogs.length > 0
                  ? ` ${tokenEventLogs.slice(0, 5).map((e) => formatDateTime(e.created_at)).join(', ')}${tokenEventLogs.length > 5 ? ' …' : ''}`
                  : ' —'}
              </li>
            </ul>
          </div>
        </section>

        {/* Invitation states – stay status */}
        <section className="bg-white rounded-2xl shadow-md border border-teal-200/80 overflow-hidden print:rounded print:shadow-none print:border">
          <div className="px-6 py-3.5 bg-gradient-to-r from-teal-50 to-slate-50 border-b border-teal-200/80 print:bg-slate-50">
            <h2 className="text-sm font-bold uppercase tracking-wider text-teal-800">Invitation states</h2>
            <p className="text-xs text-teal-700/90 mt-0.5">Invite ID and assignment state map each invitation to a stay.</p>
          </div>
          <div className="p-6 sm:p-8">
            <details className="mb-4 group">
              <summary className="cursor-pointer text-xs font-semibold text-teal-700 list-none flex items-center gap-1 hover:text-teal-800">
                <span className="group-open:rotate-90 transition-transform text-teal-600">▶</span> Assignment states legend
              </summary>
              <ul className="mt-2 pl-4 space-y-0.5 text-xs text-slate-600 border-l-2 border-teal-200">
                <li><strong>PENDING</strong> — Invite sent, not yet accepted (no stay).</li>
                <li>
                  <strong>ONGOING</strong> — The unit is occupied for the dates shown. This stays in place until those dates pass or the owner updates the record.
                </li>
                <li><strong>ACTIVE</strong> — Assignee accepted and signed; stay created (authorization active or past).</li>
                <li><strong>EXPIRED</strong> — Stay ended or guest checked out; no current authorization. (Guests only; DocuStay does not expire tenants.)</li>
                <li><strong>REVOKED</strong> — Guest authorization revoked by owner.</li>
                <li><strong>CANCELLED</strong> — Tenant assignment cancelled by tenant. (DocuStay does not revoke tenants.)</li>
              </ul>
            </details>
            {(!invitationsForDisplay || invitationsForDisplay.length === 0) ? (
              <p className="text-slate-500 text-sm">No invitations recorded for this property.</p>
            ) : (
              <div className="overflow-x-auto -mx-1 rounded-lg border border-teal-100 overflow-hidden">
                <table className="w-full text-sm border-collapse min-w-[32rem]">
                  <thead>
                    <tr className="bg-teal-50/80 border-b-2 border-teal-200">
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Invite ID</th>
                      <th className="text-left py-3 pr-4 font-semibold text-teal-800">Type</th>
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
                        <td className="py-3 pr-4 text-slate-700">{inv.guest_label ?? '—'}</td>
                        <td className="py-3 pr-4 text-slate-700 whitespace-nowrap">
                          {formatDate(inv.stay_start_date)} – {formatDate(inv.stay_end_date)}
                        </td>
                        <td className="py-3 pr-4">
                          <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                            inv.status === 'accepted' ? 'bg-emerald-100 text-emerald-800' :
                            inv.status === 'cancelled' ? 'bg-red-100 text-red-800' :
                            inv.status === 'ongoing' ? 'bg-amber-100 text-amber-800' :
                            'bg-slate-100 text-slate-700'
                          }`}>
                            {inv.status}
                          </span>
                        </td>
                        <td className="py-3 pr-4">
                          <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${
                            inv.token_state === 'BURNED' ? 'bg-emerald-100 text-emerald-800' :
                            inv.token_state === 'EXPIRED' ? 'bg-amber-100 text-amber-800' :
                            (inv.token_state === 'REVOKED' || inv.token_state === 'CANCELLED') ? 'bg-slate-100 text-slate-700' :
                            'bg-slate-100 text-slate-700'
                          }`}>
                            {inv.token_state === 'BURNED' ? 'Active' : (inv.token_state === 'REVOKED' || inv.token_state === 'CANCELLED') ? 'Cancelled' : inv.token_state === 'STAGED' ? 'Pending' : inv.token_state === 'EXPIRED' ? 'Expired' : inv.token_state}
                          </span>
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
            {logs.length === 0 ? (
              <p className="text-slate-500 text-sm">No activity recorded yet.</p>
            ) : (
              <ul className="space-y-0 max-h-[26rem] overflow-y-auto pr-1 print:max-h-none">
                {logs.map((entry, i) => (
                  <li key={i} className="relative pl-6 pb-5 last:pb-0">
                    {i < logs.length - 1 && (
                      <span className="absolute left-[5px] top-2 bottom-0 w-px bg-violet-200" />
                    )}
                    <span className="absolute left-0 top-0.5 w-2.5 h-2.5 rounded-full bg-violet-500 border-2 border-white shadow-sm" />
                    <div className="pt-0.5">
                      <p className="font-medium text-slate-800">{entry.title}</p>
                      <p className="text-slate-600 text-sm mt-0.5">{entry.message}</p>
                      <p className="text-xs text-slate-400 mt-2 flex items-center gap-2 flex-wrap">
                        <span className="inline-flex px-1.5 py-0.5 rounded bg-violet-100 text-violet-800 font-medium">
                          {entry.category.replace(/_/g, ' ')}
                        </span>
                        {formatDateTime(entry.created_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Last / upcoming (when no current guest) */}
        {!has_current_guest && (last_stay || upcoming_stays.length > 0) && (
          <section className="bg-white rounded-2xl shadow-md border border-sky-200/80 overflow-hidden print:rounded print:shadow-none print:border">
            <div className="px-6 py-3.5 bg-gradient-to-r from-sky-50 to-slate-50 border-b border-sky-200/80">
              <h2 className="text-sm font-bold uppercase tracking-wider text-sky-800">{upcomingSectionTitle}</h2>
            </div>
            <div className="p-6 flex flex-wrap gap-6 sm:gap-8 text-sm">
              {last_stay && (
                <div className="flex-1 min-w-[12rem] rounded-lg bg-slate-50 border border-slate-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-0.5">
                    {(last_stay.stay_kind ?? 'guest').toLowerCase() === 'tenant' ? 'Tenant' : 'Guest'}
                  </p>
                  <p className="text-slate-900 font-medium">{last_stay.guest_name}</p>
                  <p className="text-slate-600">{formatDate(last_stay.stay_start_date)} – {formatDate(last_stay.stay_end_date)}</p>
                </div>
              )}
              {upcoming_stays.slice(0, 3).map((s, i) => (
                <div key={i} className="flex-1 min-w-[12rem] rounded-lg bg-sky-50/60 border border-sky-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-0.5">
                    {(s.stay_kind ?? 'guest').toLowerCase() === 'tenant' ? 'Upcoming tenant stay' : 'Upcoming guest stay'}
                  </p>
                  <p className="text-slate-900 font-medium">{s.guest_name}</p>
                  <p className="text-slate-600">{formatDate(s.stay_start_date)} – {formatDate(s.stay_end_date)}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        <footer className="pt-6 pb-10 text-center border-t border-indigo-100 print:pt-2 print:pb-4 print:border-0">
          <p className="text-xs text-slate-600 font-medium">DocuStay · Live evidence page · Read-only</p>
          <p className="text-xs text-slate-400 mt-1">Record {record_id} · {formatDateTime(generated_at)}</p>
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
