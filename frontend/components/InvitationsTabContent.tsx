import React from 'react';
import { Card, Button } from './UI';
import { copyToClipboard } from '../utils/clipboard';
import { formatStayDuration, getTodayLocal, parseForDisplay } from '../utils/dateUtils';
import { buildGuestInviteUrl, demoStoredUnsignedGuestAgreementPdfUrl, type OwnerInvitationView, type OwnerStayView } from '../services/api';

function TokenStateBadge({ tokenState }: { tokenState?: string | null }) {
  const state = (tokenState || 'STAGED').toUpperCase();
  const classes =
    state === 'BURNED'
      ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
      : state === 'STAGED'
        ? 'bg-sky-100 text-sky-700 border-sky-200'
        : state === 'EXPIRED'
          ? 'bg-slate-100 text-slate-600 border-slate-200'
          : state === 'REVOKED'
            ? 'bg-amber-100 text-amber-700 border-amber-200'
            : state === 'CANCELLED'
              ? 'bg-slate-100 text-slate-600 border-slate-200'
              : 'bg-slate-100 text-slate-600 border-slate-200';
  const displayLabel = state === 'BURNED' ? 'Active' : state === 'STAGED' ? 'Pending' : state === 'REVOKED' ? 'Revoked' : state === 'CANCELLED' ? 'Cancelled' : state === 'EXPIRED' ? 'Expired' : state;
  return (
    <span className={`inline-flex px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-widest border ${classes}`}>
      {displayLabel}
    </span>
  );
}

function leaseCalendarYmd(isoOrYmd: string | null | undefined): string | null {
  if (isoOrYmd == null || String(isoOrYmd).trim() === '') return null;
  const t = String(isoOrYmd).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return t;
  if (/^\d{4}-\d{2}-\d{2}/.test(t)) return t.slice(0, 10);
  const d = parseForDisplay(t);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function calendarDateInLeaseWindow(todayYmd: string, startYmd: string, endYmd: string | null | undefined): boolean {
  const td = leaseCalendarYmd(todayYmd) || todayYmd.trim();
  const sd = leaseCalendarYmd(startYmd);
  if (!td || !sd) return false;
  if (td < sd) return false;
  const ed = leaseCalendarYmd(endYmd);
  if (ed && td > ed) return false;
  return true;
}

/** Same 4-state model as live page: accepted = before lease start; active = today in [start, end]. */
function resolveOwnerInvitationEffectiveStatus(inv: OwnerInvitationView): 'pending' | 'accepted' | 'active' | 'expired' {
  const ts = (inv.token_state || 'STAGED').toUpperCase();
  const st = (inv.status || 'pending').toLowerCase();
  if (ts === 'REVOKED' || ts === 'CANCELLED' || st === 'cancelled') return 'expired';
  if (ts === 'EXPIRED' || st === 'expired') return 'expired';
  const todayYmd = getTodayLocal();
  const sd = inv.stay_start_date;
  const ed = inv.stay_end_date;
  const endPassed = ed && leaseCalendarYmd(ed) && leaseCalendarYmd(ed)! < todayYmd;
  if (endPassed) return 'expired';
  const isAccepted = ts === 'BURNED' || st === 'accepted' || st === 'ongoing' || st === 'active';
  const inWindow = calendarDateInLeaseWindow(todayYmd, sd, ed);
  if (inWindow && isAccepted) return 'active';
  if (inWindow && !isAccepted) return 'pending';
  const startYmd = leaseCalendarYmd(sd);
  if (startYmd && startYmd > todayYmd) return isAccepted ? 'accepted' : 'pending';
  return st === 'pending' || ts === 'STAGED' ? 'pending' : 'expired';
}

/** Invite ID column: BURNED is not always “Active” — before lease start show Accepted. */
function acceptedSectionInviteIdBadge(inv: OwnerInvitationView): { label: string; className: string } {
  const ts = (inv.token_state || 'STAGED').toUpperCase();
  const resolved = resolveOwnerInvitationEffectiveStatus(inv);
  if (ts === 'REVOKED') return { label: 'Revoked', className: 'bg-amber-100 text-amber-700 border-amber-200' };
  if (ts === 'CANCELLED') return { label: 'Cancelled', className: 'bg-slate-100 text-slate-600 border-slate-200' };
  if (ts === 'EXPIRED') return { label: 'Expired', className: 'bg-slate-100 text-slate-600 border-slate-200' };
  if (ts === 'STAGED') return { label: 'Pending', className: 'bg-sky-100 text-sky-700 border-sky-200' };
  if (ts === 'BURNED') {
    if (resolved === 'accepted') return { label: 'Accepted', className: 'bg-sky-100 text-sky-800 border-sky-200' };
    if (resolved === 'active') return { label: 'Active', className: 'bg-emerald-100 text-emerald-700 border-emerald-200' };
    if (resolved === 'expired') return { label: 'Completed', className: 'bg-slate-100 text-slate-600 border-slate-200' };
  }
  return { label: ts || '—', className: 'bg-slate-100 text-slate-600 border-slate-200' };
}

function acceptedSectionRowStatus(inv: OwnerInvitationView): { label: string; className: string } {
  const resolved = resolveOwnerInvitationEffectiveStatus(inv);
  const ts = (inv.token_state || 'STAGED').toUpperCase();
  if (resolved === 'accepted') {
    return { label: 'Accepted', className: 'bg-sky-100 text-sky-800 border-sky-200' };
  }
  if (resolved === 'active') {
    return { label: 'Active', className: 'bg-emerald-100 text-emerald-700 border-emerald-200' };
  }
  if (resolved === 'expired') {
    if (ts === 'REVOKED') return { label: 'Revoked', className: 'bg-amber-100 text-amber-700 border-amber-200' };
    if (ts === 'CANCELLED') return { label: 'Cancelled', className: 'bg-slate-100 text-slate-600 border-slate-200' };
    return { label: 'Completed', className: 'bg-slate-100 text-slate-600 border-slate-200' };
  }
  return { label: 'Pending', className: 'bg-amber-100 text-amber-700 border-amber-200' };
}

function DemoUnsignedAgreementPdfButton({ invitationCode, isDemo }: { invitationCode: string; isDemo?: boolean }) {
  if (!isDemo) return null;
  return (
    <Button
      variant="outline"
      size="sm"
      type="button"
      onClick={() => window.open(demoStoredUnsignedGuestAgreementPdfUrl(invitationCode), '_blank')}
    >
      Unsigned PDF
    </Button>
  );
}

export interface InvitationsTabContentProps {
  invitations: OwnerInvitationView[];
  stays: OwnerStayView[];
  loadData: () => void;
  notify: (t: 'success' | 'error', m: string) => void;
  /** When true, show "Verify QR" button and call onVerifyQR when clicked. Manager typically false. */
  showVerifyQR?: boolean;
  onVerifyQR?: (invitationCode: string) => void;
  /** Cancel invitation (owner or manager as inviter). Component calls this then parent should call loadData. */
  onCancelInvitation: (invitationId: number) => Promise<void>;
  /** Re-send invitation (tenant only). Component calls this then parent should call loadData. */
  onResendInvitation?: (invitationId: number) => Promise<void>;
  /** Optional intro text below the tab (e.g. "Invitations you've sent...") */
  introText?: string;
  /** Show or hide "Cancelled by guest" stays section inside Cancelled card. */
  showCancelledGuestStays?: boolean;
}

export const InvitationsTabContent: React.FC<InvitationsTabContentProps> = ({
  invitations,
  stays,
  notify,
  showVerifyQR = false,
  onVerifyQR,
  onCancelInvitation,
  onResendInvitation,
  introText = "Invitations you've sent. Pending invitations are labeled as expired after 72 hours if not accepted.",
  showCancelledGuestStays = true,
}) => {
  const cancelledInvitations = invitations.filter((i) => i.status === 'cancelled');
  const cancelledGuestStays = stays.filter((s) => s.cancelled_at);
  const showCancelledCard = showCancelledGuestStays
    ? (cancelledInvitations.length > 0 || cancelledGuestStays.length > 0)
    : true;

  const handleCopyLink = async (inv: OwnerInvitationView) => {
    const url = buildGuestInviteUrl(inv.invitation_code, { isDemo: Boolean(inv.is_demo) });
    const ok = await copyToClipboard(url);
    if (ok) notify('success', 'Invitation link copied to clipboard.');
    else notify('error', 'Could not copy. Please copy the link manually.');
  };

  const handleCancel = async (inv: OwnerInvitationView) => {
    try {
      await onCancelInvitation(inv.id);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to cancel.');
    }
  };

  const handleResend = async (inv: OwnerInvitationView) => {
    if (!onResendInvitation) return;
    try {
      await onResendInvitation(inv.id);
      notify('success', 'Invitation expiry reset. You can now share the link again.');
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to re-send.');
    }
  };

  return (
    <div className="space-y-8">
      {introText && <p className="text-slate-500 text-sm">{introText}</p>}

      {/* Pending (within 72h window) */}
      <Card className="overflow-hidden">
        <div className="p-6 border-b border-slate-200 bg-amber-50">
          <h3 className="text-xl font-bold text-slate-800">Pending</h3>
          <p className="text-xs text-slate-500 mt-1">Invites not yet accepted (within 72-hour window)</p>
        </div>
        <div className="overflow-x-auto">
          {invitations.filter((i) => i.status === 'pending' && !i.is_expired).length === 0 ? (
            <p className="p-6 text-slate-500 text-sm">No pending invitations.</p>
          ) : (
            <table className="w-full text-left">
              <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                <tr>
                  <th className="px-6 py-4">Invited (email)</th>
                  <th className="px-6 py-4">Property</th>
                  <th className="px-6 py-4">Planned stay</th>
                  <th className="px-6 py-4">Region</th>
                  <th className="px-6 py-4">Invitation code</th>
                  <th className="px-6 py-4">Invite ID status</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {invitations.filter((i) => i.status === 'pending' && !i.is_expired).map((inv) => (
                  <tr key={inv.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-5">
                      <span className="text-sm font-medium text-slate-800">{inv.guest_name || inv.guest_email || '—'}</span>
                    </td>
                    <td className="px-6 py-5">
                      <p className="text-sm font-medium text-slate-800">{inv.property_name}</p>
                      <p className="text-xs text-slate-500">{inv.region_code}</p>
                    </td>
                    <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                      {formatStayDuration(inv.stay_start_date, inv.stay_end_date)}
                    </td>
                    <td className="px-6 py-5 text-sm text-slate-600">{inv.region_code}</td>
                    <td className="px-6 py-5 text-xs font-mono text-slate-600">{inv.invitation_code}</td>
                    <td className="px-6 py-5">
                      <TokenStateBadge tokenState={inv.token_state} />
                    </td>
                    <td className="px-6 py-5">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-amber-500/10 text-amber-700 border border-amber-200">Pending</span>
                    </td>
                    <td className="px-6 py-5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <DemoUnsignedAgreementPdfButton invitationCode={inv.invitation_code} isDemo={inv.is_demo} />
                        <Button variant="outline" size="sm" onClick={() => handleCopyLink(inv)}>Copy link</Button>
                        {showVerifyQR && onVerifyQR && (
                          <Button variant="outline" size="sm" onClick={() => onVerifyQR(inv.invitation_code)}>Verify QR</Button>
                        )}
                        <Button variant="outline" size="sm" onClick={() => handleCancel(inv)}>Cancel invite</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* Expired */}
      <Card className="overflow-hidden">
        <div className="p-6 border-b border-slate-200 bg-slate-100">
          <h3 className="text-xl font-bold text-slate-800">Expired invites</h3>
          <p className="text-xs text-slate-500 mt-1">Pending guest invites whose 72-hour window was exceeded (not accepted in time). Tenant invitations are not expired by DocuStay.</p>
        </div>
        <div className="overflow-x-auto">
          {invitations.filter((i) => i.is_expired).length === 0 ? (
            <p className="p-6 text-slate-500 text-sm">No expired invitations.</p>
          ) : (
            <table className="w-full text-left">
              <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                <tr>
                  <th className="px-6 py-4">Invited (email)</th>
                  <th className="px-6 py-4">Property</th>
                  <th className="px-6 py-4">Planned stay</th>
                  <th className="px-6 py-4">Region</th>
                  <th className="px-6 py-4">Invitation code</th>
                  <th className="px-6 py-4">Invite ID status</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {invitations.filter((i) => i.is_expired).map((inv) => (
                  <tr key={inv.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-5">
                      <span className="text-sm font-medium text-slate-800">{inv.guest_name || inv.guest_email || '—'}</span>
                    </td>
                    <td className="px-6 py-5">
                      <p className="text-sm font-medium text-slate-800">{inv.property_name}</p>
                      <p className="text-xs text-slate-500">{inv.region_code}</p>
                    </td>
                    <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                      {formatStayDuration(inv.stay_start_date, inv.stay_end_date)}
                    </td>
                    <td className="px-6 py-5 text-sm text-slate-600">{inv.region_code}</td>
                    <td className="px-6 py-5 text-xs font-mono text-slate-600">{inv.invitation_code}</td>
                    <td className="px-6 py-5">
                      <TokenStateBadge tokenState={inv.token_state} />
                    </td>
                    <td className="px-6 py-5">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-100 text-slate-600 border border-slate-200">Expired</span>
                    </td>
                    <td className="px-6 py-5 text-right">
                      <div className="flex items-center justify-end gap-2 flex-wrap">
                        <DemoUnsignedAgreementPdfButton invitationCode={inv.invitation_code} isDemo={inv.is_demo} />
                        {onResendInvitation && (
                          <Button variant="outline" size="sm" onClick={() => handleResend(inv)}>Re-send</Button>
                        )}
                        <Button variant="outline" size="sm" onClick={() => handleCopyLink(inv)}>Copy link</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
      {/* Accepted / Active */}
      <Card className="overflow-hidden">
        <div className="p-6 border-b border-slate-200 bg-emerald-50">
          <h3 className="text-xl font-bold text-slate-800">Accepted / Active</h3>
          <p className="text-xs text-slate-500 mt-1">
            Invites accepted (invite used / stay created). Accepted = lease start is still in the future; Active = today is
            within the planned stay dates (aligned with live link invitation states).
          </p>
        </div>
        <div className="overflow-x-auto">
          {invitations.filter((i) => i.status === 'accepted' || i.status === 'ongoing' || i.status === 'active').length === 0 ? (
            <p className="p-6 text-slate-500 text-sm">No accepted or active invitations.</p>
          ) : (
            <table className="w-full text-left">
              <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                <tr>
                  <th className="px-6 py-4">Invited (email)</th>
                  <th className="px-6 py-4">Property</th>
                  <th className="px-6 py-4">Planned stay</th>
                  <th className="px-6 py-4">Region</th>
                  <th className="px-6 py-4">Invitation code</th>
                  <th className="px-6 py-4">Invite ID status</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {invitations.filter((i) => i.status === 'accepted' || i.status === 'ongoing' || i.status === 'active').map((inv) => {
                  const inviteBadge = acceptedSectionInviteIdBadge(inv);
                  const rowStatus = acceptedSectionRowStatus(inv);
                  return (
                    <tr key={inv.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-5">
                        <span className="text-sm font-medium text-slate-800">{inv.guest_name || inv.guest_email || '—'}</span>
                      </td>
                      <td className="px-6 py-5">
                        <p className="text-sm font-medium text-slate-800">{inv.property_name}</p>
                        <p className="text-xs text-slate-500">{inv.region_code}</p>
                      </td>
                      <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                        {formatStayDuration(inv.stay_start_date, inv.stay_end_date)}
                      </td>
                      <td className="px-6 py-5 text-sm text-slate-600">{inv.region_code}</td>
                      <td className="px-6 py-5 text-xs font-mono text-slate-600">{inv.invitation_code}</td>
                      <td className="px-6 py-5">
                        <span
                          className={`inline-flex px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-widest border ${inviteBadge.className}`}
                        >
                          {inviteBadge.label}
                        </span>
                      </td>
                      <td className="px-6 py-5">
                        <span
                          className={`inline-flex px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border ${rowStatus.className}`}
                        >
                          {rowStatus.label}
                        </span>
                      </td>
                      <td className="px-6 py-5">
                        <div className="flex items-center gap-2 flex-wrap">
                          <DemoUnsignedAgreementPdfButton invitationCode={inv.invitation_code} isDemo={inv.is_demo} />
                          <Button variant="outline" size="sm" onClick={() => handleCopyLink(inv)}>Copy link</Button>
                          {showVerifyQR && onVerifyQR && (
                            <Button variant="outline" size="sm" onClick={() => onVerifyQR(inv.invitation_code)}>Verify QR</Button>
                          )}
                          {/* Accepted/active invitations are not cancellable; owner must use revoke flow. */}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* Cancelled */}
      {showCancelledCard && <Card className="overflow-hidden">
        <div className="p-6 border-b border-slate-200 bg-slate-50">
          <h3 className="text-xl font-bold text-slate-800">Cancelled</h3>
          <p className="text-xs text-slate-500 mt-1">
            {showCancelledGuestStays ? 'Invites cancelled by you and stays cancelled by guests' : 'Invites cancelled by you'}
          </p>
        </div>
        <div className="divide-y divide-slate-200">
          <div className="p-6">
            <h4 className="text-sm font-bold text-slate-700 mb-2">Cancelled by you</h4>
            <p className="text-xs text-slate-500 mb-3">Invitations you cancelled before the tenant accepted.</p>
            {cancelledInvitations.length === 0 ? (
              <p className="text-slate-500 text-sm">No cancelled invitations.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                    <tr>
                      <th className="px-6 py-4">Invited (email)</th>
                      <th className="px-6 py-4">Property</th>
                      <th className="px-6 py-4">Planned stay</th>
                      <th className="px-6 py-4">Region</th>
                      <th className="px-6 py-4">Invitation code</th>
                      <th className="px-6 py-4">Invite ID status</th>
                      <th className="px-6 py-4">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {cancelledInvitations.map((inv) => (
                      <tr key={inv.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-5">
                          <span className="text-sm font-medium text-slate-800">{inv.guest_name || inv.guest_email || '—'}</span>
                        </td>
                        <td className="px-6 py-5">
                          <p className="text-sm font-medium text-slate-800">{inv.property_name}</p>
                          <p className="text-xs text-slate-500">{inv.region_code}</p>
                        </td>
                        <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                          {formatStayDuration(inv.stay_start_date, inv.stay_end_date)}
                        </td>
                        <td className="px-6 py-5 text-sm text-slate-600">{inv.region_code}</td>
                        <td className="px-6 py-5 text-xs font-mono text-slate-600">{inv.invitation_code}</td>
                        <td className="px-6 py-5">
                          <TokenStateBadge tokenState={inv.token_state} />
                        </td>
                        <td className="px-6 py-5">
                          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-200 text-slate-600 border border-slate-300">Cancelled by you</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {showCancelledGuestStays && <div className="p-6">
            <h4 className="text-sm font-bold text-slate-700 mb-2">Cancelled by guest</h4>
            <p className="text-xs text-slate-500 mb-3">Stays that the guest cancelled after accepting your invitation.</p>
            {cancelledGuestStays.length === 0 ? (
              <p className="text-slate-500 text-sm">No stays cancelled by guests.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                    <tr>
                      <th className="px-6 py-4">Guest</th>
                      <th className="px-6 py-4">Property</th>
                      <th className="px-6 py-4">Planned stay</th>
                      <th className="px-6 py-4">Region</th>
                      <th className="px-6 py-4">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {cancelledGuestStays.map((stay) => (
                      <tr key={stay.stay_id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-5">
                          <span className="text-sm font-medium text-slate-800">{stay.guest_name}</span>
                        </td>
                        <td className="px-6 py-5">
                          <p className="text-sm font-medium text-slate-800">{stay.property_name}</p>
                          <p className="text-xs text-slate-500">{stay.region_code}</p>
                        </td>
                        <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                          {formatStayDuration(stay.stay_start_date, stay.stay_end_date)}
                        </td>
                        <td className="px-6 py-5 text-sm text-slate-600">{stay.region_code}</td>
                        <td className="px-6 py-5">
                          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-200 text-slate-500 border border-slate-300">Cancelled by guest</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>}
        </div>
      </Card>}
    </div>
  );
};
