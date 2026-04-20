import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Button, Input, Modal } from '../../components/UI';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import HelpCenter from '../Support/HelpCenter';
import { formatCoTenantPeerLine } from '../../utils/leaseCohortGroups';
import { DashboardAlertsPanel, DASHBOARD_ALERTS_REFRESH_EVENT } from '../../components/DashboardAlertsPanel';
import { InactivePropertyBanner } from '../../components/InactivePropertyBanner';
import { UserSession } from '../../types';
import { dashboardApi, authApi, invitationsApi, APP_ORIGIN, API_URL, buildGuestInviteUrl, demoStoredUnsignedGuestAgreementPdfUrl, resolveBackendMediaUrl, openLivePoaPdfInNewTab } from '../../services/api';
import type {
  OwnerInvitationView,
  OwnerStayView,
  OwnerAuditLogEntry,
  GuestPendingInviteView,
  GuestStayView,
  TenantSignedDocument,
  TenantGuestExtensionRequestView,
} from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import { PENDING_INVITE_STORAGE_KEY } from '../Guest/GuestLogin';
import { SUPPORT_EMAIL, supportMailtoHref } from '../../constants/supportContact';
import {
  formatCalendarDate,
  formatDateTimeLocal,
  formatLedgerTimestamp,
  localDateInputToUtcEndIso,
  localDateInputToUtcStartIso,
  parseForDisplay,
} from '../../utils/dateUtils';

type TenantTab = 'stays' | 'property' | 'invitations' | 'logs' | 'documents' | 'help';


/** One "stay" for tenant = their assigned unit (here/away is per property/unit). */
type TenantUnitCard = {
  unit_id: number;
  unit_label: string;
  property_name: string;
  property_address: string;
  stay_start_date: string | null;
  stay_end_date: string | null;
  token_state: string | null;
  /** True for tenant-invite rows not yet accepted; lease is not "active" until cleared. */
  pending_acceptance?: boolean;
  lease_cohort_id?: string | null;
  cohort_member_count?: number | null;
  co_tenants?: Array<{ name?: string | null; email?: string | null }>;
  property_deleted_at?: string | null;
};

type StayFilter = 'all' | 'active' | 'future' | 'completed' | 'future_invites';

function parseInviteCode(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
}

/** Today as YYYY-MM-DD for date comparisons. */
function getTodayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Normalize API date strings to local calendar YYYY-MM-DD (handles ISO datetimes and date-only). */
function leaseCalendarYmd(isoOrYmd: string | null | undefined): string | null {
  if (isoOrYmd == null || String(isoOrYmd).trim() === '') return null;
  const t = String(isoOrYmd).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return t;
  if (/^\d{4}-\d{2}-\d{2}/.test(t)) return t.slice(0, 10);
  const d = parseForDisplay(t);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Inclusive local calendar window; open-ended when end is null/empty. */
function tenantLeaseInCalendarWindow(todayYmd: string, start: string | null, end: string | null, cancelled: boolean): boolean {
  if (cancelled) return false;
  const sd = leaseCalendarYmd(start);
  if (!sd) return false;
  const td = leaseCalendarYmd(todayYmd) || todayYmd;
  if (td < sd) return false;
  const ed = leaseCalendarYmd(end);
  if (ed && td > ed) return false;
  return true;
}

function tenantLeaseAcceptedOnCard(card: TenantUnitCard): boolean {
  return !card.pending_acceptance;
}

/** True if this tenant-invited guest row is a real Stay that can be revoked (kill switch). */
function tenantCanRevokeGuestStay(h: OwnerStayView): boolean {
  if (h.invitation_only || h.stay_id <= 0) return false;
  if (h.revoked_at || h.checked_out_at || h.cancelled_at) return false;
  return true;
}

/** Ended guest authorization label: revoke vs cancel vs checkout vs expired invite (no stay). */
function endedGuestAuthorizationBadge(h: OwnerStayView): { label: string; className: string } {
  const ts = (h.token_state || '').toUpperCase();
  if (h.revoked_at) {
    return { label: 'Revoked', className: 'bg-amber-50 text-amber-800 border border-amber-200' };
  }
  if (h.cancelled_at) {
    return { label: h.invitation_only ? 'Invitation cancelled' : 'Cancelled', className: 'bg-slate-100 text-slate-700 border border-slate-200' };
  }
  if (h.invitation_only && ts === 'EXPIRED' && h.checked_out_at) {
    return { label: 'Expired', className: 'bg-slate-100 text-slate-600 border border-slate-200' };
  }
  if (h.checked_out_at) {
    return { label: 'Checked out', className: 'bg-slate-100 text-slate-600 border border-slate-200' };
  }
  return { label: 'Ended', className: 'bg-slate-100 text-slate-600 border border-slate-200' };
}

/** Signed doc row for a pending invite the tenant sent (matches invitation code). */
function tenantSignedAgreementForInviteCode(
  invitationCode: string,
  docs: TenantSignedDocument[]
): TenantSignedDocument | undefined {
  const code = (invitationCode || '').trim().toUpperCase();
  if (!code) return undefined;
  return docs.find(
    (d) =>
      d.record_type === 'guest_invited_by_you' &&
      (d.invitation_code || '').trim().toUpperCase() === code &&
      !!d.signed_at
  );
}

function daysLeft(endDateStr: string): number {
  const end = new Date(endDateStr);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  end.setHours(0, 0, 0, 0);
  return Math.max(0, Math.ceil((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)));
}

/** List of YYYY-MM-DD strings from start (inclusive) to end (inclusive). */
function dateRange(startStr: string, endStr: string): string[] {
  const out: string[] = [];
  const start = new Date(startStr);
  const end = new Date(endStr);
  const cur = new Date(start);
  while (cur <= end) {
    const y = cur.getFullYear();
    const m = String(cur.getMonth() + 1).padStart(2, '0');
    const d = String(cur.getDate()).padStart(2, '0');
    out.push(`${y}-${m}-${d}`);
    cur.setDate(cur.getDate() + 1);
  }
  return out;
}

/** True if [start1, end1] overlaps [start2, end2] (dates as YYYY-MM-DD or parseable strings). */
function datesOverlap(start1: string, end1: string, start2: string, end2: string): boolean {
  const a1 = parseForDisplay(start1).getTime();
  const a2 = parseForDisplay(end1).getTime();
  const b1 = parseForDisplay(start2).getTime();
  const b2 = parseForDisplay(end2).getTime();
  return a1 < b2 && a2 > b1;
}

/** One list: accepted guest stays + pending/active invites (same authorization lifecycle). */
type TenantGuestAuthActiveRow =
  | { kind: 'accepted'; key: string; stay: OwnerStayView }
  | { kind: 'pending_invite'; key: string; inv: OwnerInvitationView };

function buildTenantGuestAuthRows(
  invitations: OwnerInvitationView[],
  guestHistory: OwnerStayView[],
  propertyId: number | null
): { active: TenantGuestAuthActiveRow[]; ended: OwnerStayView[] } {
  if (propertyId == null) {
    return { active: [], ended: [] };
  }
  const historyForProperty = guestHistory.filter((h) => h.property_id === propertyId);
  const invitesForProperty = invitations.filter(
    (inv) =>
      inv.property_id === propertyId &&
      (inv.status === 'pending' || inv.status === 'ongoing' || inv.status === 'active' || inv.status === 'accepted') &&
      !inv.is_expired
  );
  const activeStays = historyForProperty.filter(
    (h) =>
      !h.invitation_only &&
      !h.checked_out_at &&
      !h.revoked_at &&
      !h.cancelled_at
  );
  // Any real Stay for an invite (including revoked/checked out) means "pending invite" row must not duplicate it.
  const usedCodes = new Set<string>();
  for (const h of historyForProperty) {
    if (h.invitation_only || h.stay_id <= 0 || !h.invite_id) continue;
    usedCodes.add(h.invite_id.trim().toUpperCase());
  }
  const active: TenantGuestAuthActiveRow[] = activeStays.map((stay) => ({
    kind: 'accepted' as const,
    key: `stay-${stay.stay_id}`,
    stay,
  }));
  for (const inv of invitesForProperty) {
    if (usedCodes.has((inv.invitation_code || '').trim().toUpperCase())) continue;
    active.push({ kind: 'pending_invite' as const, key: `inv-${inv.id}`, inv });
  }
  active.sort((a, b) => {
    const da = a.kind === 'accepted' ? a.stay.stay_start_date : a.inv.stay_start_date;
    const db = b.kind === 'accepted' ? b.stay.stay_start_date : b.inv.stay_start_date;
    return db.localeCompare(da);
  });
  const ended = historyForProperty.filter((h) => h.checked_out_at || h.revoked_at || h.cancelled_at);
  return { active, ended };
}

const TenantDashboard: React.FC<{
  user: UserSession;
  navigate: (v: string) => void;
  setLoading?: (l: boolean) => void;
  notify?: (t: 'success' | 'error', m: string) => void;
}> = ({ user, navigate, setLoading = () => {}, notify = (_t: 'success' | 'error', _m: string) => {} }) => {
  const [unitsData, setUnitsData] = useState<Array<{
    unit: { id: number; unit_label: string; occupancy_status: string } | null;
    property: { id: number; name: string; address: string } | null;
    invite_id: string | null;
    token_state: string | null;
    stay_start_date: string | null;
    stay_end_date: string | null;
    live_slug: string | null;
    region_code: string | null;
    jurisdiction_state_name: string | null;
    jurisdiction_statutes: Array<{ citation: string; plain_english?: string | null }>;
    removal_guest_text: string | null;
    removal_tenant_text: string | null;
    assigned_by_name?: string | null;
    accepted_by_name?: string | null;
    pending_acceptance?: boolean;
    dead_mans_switch_enabled?: boolean;
    lease_cohort_id?: string | null;
    cohort_member_count?: number | null;
    co_tenants?: Array<{ name?: string | null; email?: string | null }>;
    property_deleted_at?: string | null;
    property_owner_transfer_notice?: string | null;
  }>>([]);
  const [loading, setLoadingState] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedUnit, setSelectedUnit] = useState<TenantUnitCard | null>(null);
  const [invitations, setInvitations] = useState<OwnerInvitationView[]>([]);
  const [stays, setStays] = useState<GuestStayView[]>([]);
  const [guestHistory, setGuestHistory] = useState<OwnerStayView[]>([]);
  const [inviteLinkInput, setInviteLinkInput] = useState('');
  const [inviteModalOpen, setInviteModalOpen] = useState(false);
  const [inviteModalPrefill, setInviteModalPrefill] = useState<{ email: string; name: string } | null>(null);
  const [guestExtensionRequests, setGuestExtensionRequests] = useState<TenantGuestExtensionRequestView[]>([]);
  const [extensionDecision, setExtensionDecision] = useState<{
    req: TenantGuestExtensionRequestView;
    action: 'approve' | 'decline';
  } | null>(null);
  const [extensionDecisionNote, setExtensionDecisionNote] = useState('');
  const [extensionApproveInviteCode, setExtensionApproveInviteCode] = useState('');
  const [extensionDecisionSubmitting, setExtensionDecisionSubmitting] = useState(false);
  const [revokeConfirmStay, setRevokeConfirmStay] = useState<OwnerStayView | null>(null);
  const [revokeLoading, setRevokeLoading] = useState(false);
  const [revokeSuccessGuest, setRevokeSuccessGuest] = useState<string | null>(null);
  const [inviteRevokeConfirm, setInviteRevokeConfirm] = useState<OwnerInvitationView | null>(null);
  const [inviteRevokeLoading, setInviteRevokeLoading] = useState(false);
  // Presence per selected unit (here/away per property)
  const [presence, setPresence] = useState<'present' | 'away'>('present');
  const [awayStartedAt, setAwayStartedAt] = useState<string | null>(null);
  const [guestsAuthorizedDuringAway, setGuestsAuthorizedDuringAway] = useState(false);
  const [presenceUpdating, setPresenceUpdating] = useState(false);
  const [showAwayConfirm, setShowAwayConfirm] = useState(false);
  const [awayGuestsAuthorized, setAwayGuestsAuthorized] = useState(false);
  const [propertyLogs, setPropertyLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [propertyLogsLoading, setPropertyLogsLoading] = useState(false);
  const [propertyLogsLoadedOnce, setPropertyLogsLoadedOnce] = useState(false);
  const [logsFromDate, setLogsFromDate] = useState('');
  const [logsToDate, setLogsToDate] = useState('');
  const [logsCategory, setLogsCategory] = useState('');
  const [logsSearch, setLogsSearch] = useState('');
  const [logMessageModalEntry, setLogMessageModalEntry] = useState<OwnerAuditLogEntry | null>(null);
  const [addingInvite, setAddingInvite] = useState(false);
  const [showLiveLinkModal, setShowLiveLinkModal] = useState(false);
  const [liveLinkSlug, setLiveLinkSlug] = useState<string | null>(null);
  const [showVerifyQRModal, setShowVerifyQRModal] = useState(false);
  const [verifyQRInviteId, setVerifyQRInviteId] = useState<string | null>(null);
  const [copyToast, setCopyToast] = useState<string | null>(null);
  const [signedDocs, setSignedDocs] = useState<TenantSignedDocument[]>([]);
  const [verificationRecord, setVerificationRecord] = useState<{
    poa_signed_at: string | null;
    poa_url: string | null;
    guest_agreements: Array<{
      signature_id: number;
      invitation_code: string;
      document_title: string;
      guest_name: string;
      signed_at: string | null;
      stay_start_date: string | null;
      stay_end_date: string | null;
      token_state: string | null;
    }>;
    property_status: string | null;
  } | null>(null);
  const [activeTab, setActiveTab] = useState<TenantTab>('stays');
  const [stayFilter, setStayFilter] = useState<StayFilter>('all');
  const [pendingInvites, setPendingInvites] = useState<GuestPendingInviteView[]>([]);
  const [selectedStay, setSelectedStay] = useState<GuestStayView | null>(null);
  const [checkingInStay, setCheckingInStay] = useState<GuestStayView | null>(null);
  const [endStayConfirm, setEndStayConfirm] = useState<GuestStayView | null>(null);
  const [endingGuestStay, setEndingGuestStay] = useState(false);
  const [cancelStayConfirm, setCancelStayConfirm] = useState<GuestStayView | null>(null);
  const [cancellingGuestStay, setCancellingGuestStay] = useState(false);
  const [generatedInviteLink, setGeneratedInviteLink] = useState<string | null>(null);
  const acceptFailedRef = useRef<Set<string>>(new Set());
  const acceptInFlightRef = useRef<Set<string>>(new Set());
  const acceptedInviteRef = useRef<Set<string>>(new Set());

  // Tenant invite confirmation modal state
  const [confirmInviteModal, setConfirmInviteModal] = useState<{
    code: string;
    property_name: string;
    property_address: string;
    stay_start_date: string;
    stay_end_date: string;
    host_name: string;
    /** When set (guest invite already signed), pass to acceptInvite to create Stay. */
    accept_now_signature_id?: number | null;
  } | null>(null);
  const [confirmTermsAgreed, setConfirmTermsAgreed] = useState(false);
  const [confirmPrivacyAgreed, setConfirmPrivacyAgreed] = useState(false);
  const [confirmAccepting, setConfirmAccepting] = useState(false);


  const loadData = useCallback(async () => {
    setError(null);
    try {
      const data = await dashboardApi.tenantUnit();
      setUnitsData(data.units || []);
      const [invites, history, pendingData, docs, verRecord, extReqs] = await Promise.all([
        dashboardApi.tenantInvitations().catch(() => []),
        dashboardApi.tenantGuestHistory().catch(() => [] as OwnerStayView[]),
        dashboardApi.guestPendingInvites().catch(() => [] as GuestPendingInviteView[]),
        dashboardApi.tenantSignedDocuments().catch(() => [] as TenantSignedDocument[]),
        dashboardApi.tenantPropertyVerification().catch(() => null),
        dashboardApi.tenantGuestExtensionRequests().catch(() => [] as TenantGuestExtensionRequestView[]),
      ]);
      setInvitations(invites);
      setGuestHistory(history);
      setPendingInvites(pendingData);
      /* Tenants use /tenant/guest-history for guests they invited; /guest/stays is guest-role only (backend returns []). */
      setStays([]);
      setSignedDocs(docs);
      setVerificationRecord(verRecord);
      setGuestExtensionRequests(extReqs);
    } catch (e) {
      const msg = (e as Error)?.message || 'Failed to load dashboard.';
      setError(msg);
      notify('error', msg);
    } finally {
      setLoadingState(false);
    }
  }, [notify]);

  const handleTenantRevokeConfirm = useCallback(async () => {
    if (!revokeConfirmStay || revokeConfirmStay.stay_id <= 0) return;
    setRevokeLoading(true);
    try {
      await dashboardApi.tenantRevokeGuestStay(revokeConfirmStay.stay_id);
      const name = revokeConfirmStay.guest_name;
      notify('success', 'Stay revoked. Guest must vacate within 12 hours. Email sent.');
      setRevokeConfirmStay(null);
      setRevokeSuccessGuest(name);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to revoke stay.');
    } finally {
      setRevokeLoading(false);
    }
  }, [revokeConfirmStay, notify, loadData]);

  const handleTenantInviteRevokeConfirm = useCallback(async () => {
    if (!inviteRevokeConfirm) return;
    setInviteRevokeLoading(true);
    try {
      await dashboardApi.cancelInvitation(inviteRevokeConfirm.id);
      notify('success', 'Invitation cancelled.');
      setInviteRevokeConfirm(null);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to revoke invitation.');
    } finally {
      setInviteRevokeLoading(false);
    }
  }, [inviteRevokeConfirm, notify, loadData]);

  const openInviteForExtensionRequest = useCallback(
    (req: TenantGuestExtensionRequestView) => {
      const ud = unitsData.find((u) => u.unit?.id != null && req.unit_id != null && u.unit.id === req.unit_id);
      if (ud?.unit && ud.property) {
        setSelectedUnit({
          unit_id: ud.unit.id,
          unit_label: ud.unit.unit_label,
          property_name: ud.property.name || 'Property',
          property_address: ud.property.address || '',
          stay_start_date: ud.stay_start_date,
          stay_end_date: ud.stay_end_date,
          token_state: ud.token_state,
        });
      }
      setInviteModalPrefill({ email: req.guest_email, name: req.guest_name });
      setInviteModalOpen(true);
      setActiveTab('stays');
    },
    [unitsData]
  );

  const submitExtensionDecision = useCallback(async () => {
    if (!extensionDecision) return;
    setExtensionDecisionSubmitting(true);
    const note = extensionDecisionNote.trim();
    try {
      if (extensionDecision.action === 'approve') {
        const approvedReq = extensionDecision.req;
        const rawInvite = extensionApproveInviteCode.trim();
        if (!parseInviteCode(rawInvite)) {
          notify('error', 'Paste the new invitation link or Invite ID for the extended stay.');
          return;
        }
        await dashboardApi.tenantApproveGuestExtension(approvedReq.id, {
          invitation_code: rawInvite,
          ...(note ? { message: note } : {}),
        });
        notify('success', 'Approved. The guest has been emailed with the new invitation link.');
        setExtensionDecision(null);
        setExtensionDecisionNote('');
        setExtensionApproveInviteCode('');
        await loadData();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      } else {
        await dashboardApi.tenantDeclineGuestExtension(extensionDecision.req.id, note ? { message: note } : {});
        notify('success', 'Decline saved. The guest has been notified.');
        setExtensionDecision(null);
        setExtensionDecisionNote('');
        setExtensionApproveInviteCode('');
        loadData();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      }
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not update request.');
    } finally {
      setExtensionDecisionSubmitting(false);
    }
  }, [extensionDecision, extensionDecisionNote, extensionApproveInviteCode, notify, loadData]);

  const openTenantGuestSignedAgreementForStay = useCallback(
    async (stayId: number) => {
      try {
        const blob = await dashboardApi.tenantInvitedGuestStaySignedAgreementBlob(stayId);
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank', 'noopener,noreferrer');
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      } catch (e) {
        notify('error', (e as Error)?.message ?? 'Could not open agreement.');
      }
    },
    [notify]
  );

  const openTenantGuestSignedAgreementForSignature = useCallback(
    async (signatureId: number) => {
      try {
        // Use the same endpoint as the Documents tab to avoid state/permission mismatches.
        window.open(`${API_URL}/agreements/signature/${signatureId}/signed-pdf`, '_blank', 'noopener,noreferrer');
      } catch (e) {
        notify('error', (e as Error)?.message ?? 'Could not open agreement.');
      }
    },
    [notify]
  );

  const openConfirmInviteModal = useCallback(async (code: string, inviteData?: GuestPendingInviteView) => {
    if (inviteData) {
      setConfirmInviteModal({
        code,
        property_name: inviteData.property_name || 'Property',
        property_address: inviteData.unit_label ? `Unit ${inviteData.unit_label}` : '',
        stay_start_date: inviteData.stay_start_date || '',
        stay_end_date: inviteData.stay_end_date || '',
        host_name: inviteData.host_name || '',
        accept_now_signature_id: inviteData.accept_now_signature_id ?? null,
      });
      setConfirmTermsAgreed(false);
      setConfirmPrivacyAgreed(false);
      return;
    }
    try {
      const details = await invitationsApi.getDetails(code);
      if (!details.valid) {
        const msg = details.expired
          ? 'This invitation has expired. Please ask your host for a new invitation.'
          : details.used || details.already_accepted
            ? 'This invitation has already been accepted.'
            : 'This invitation link is invalid or could not be found.';
        notify('error', msg);
        if (details.already_accepted) loadData();
        return;
      }
      setConfirmInviteModal({
        code,
        property_name: details.property_name || 'Property',
        property_address: details.property_address || '',
        stay_start_date: details.stay_start_date || '',
        stay_end_date: details.stay_end_date || '',
        host_name: details.host_name || '',
        accept_now_signature_id: null,
      });
      setConfirmTermsAgreed(false);
      setConfirmPrivacyAgreed(false);
    } catch {
      notify('error', 'Could not load invitation details. Please try again.');
    }
  }, [notify, loadData]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // When pending invites arrive, show the confirmation modal for the first unprocessed one
  useEffect(() => {
    if (!pendingInvites.length || confirmInviteModal) return;
    const first = pendingInvites.find((inv) => !acceptFailedRef.current.has(inv.invitation_code) && !acceptInFlightRef.current.has(inv.invitation_code) && !acceptedInviteRef.current.has(inv.invitation_code));
    if (first) {
      openConfirmInviteModal(first.invitation_code, first);
    }
  }, [pendingInvites, confirmInviteModal, openConfirmInviteModal]);

  // Process invite code stored during login/signup (e.g. after email verification).
  // Show confirmation modal instead of auto-accepting.
  useEffect(() => {
    const code = sessionStorage.getItem(PENDING_INVITE_STORAGE_KEY);
    if (!code) return;
    sessionStorage.removeItem(PENDING_INVITE_STORAGE_KEY);

    invitationsApi.getDetails(code)
      .then(async (details) => {
        if (details.already_accepted) {
          loadData();
          return;
        }
        if (!details.valid) {
          loadData();
          const msg = details.expired
            ? 'This invitation has expired. Please ask your host for a new invitation.'
            : details.used
              ? 'This invitation link has already been used.'
              : 'This invitation link is invalid or could not be found.';
          notify('error', msg);
          return;
        }
        try {
          await dashboardApi.guestAddPendingInvite(code);
        } catch { /* may fail if already added */ }
        openConfirmInviteModal(code);
        loadData();
      })
      .catch(() => {
        loadData();
        notify('error', 'Could not verify this invitation link. Please try pasting it on your dashboard.');
      });
  }, [loadData, notify, openConfirmInviteModal]);

  // When unit data loads, set selected unit to the first one if we have it
  useEffect(() => {
    const first = unitsData.find((u) => u.unit && u.property);
    if (first?.unit && first?.property && !selectedUnit) {
      setSelectedUnit({
        unit_id: first.unit.id,
        unit_label: first.unit.unit_label,
        property_name: first.property.name || 'Property',
        property_address: first.property.address || '',
        stay_start_date: first.stay_start_date,
        stay_end_date: first.stay_end_date,
        token_state: first.token_state,
      });
    }
  }, [unitsData, selectedUnit]);

  // Fetch presence for the selected unit (here/away per property)
  useEffect(() => {
    if (!selectedUnit?.unit_id) {
      setPresence('present');
      setAwayStartedAt(null);
      setGuestsAuthorizedDuringAway(false);
      setShowAwayConfirm(false);
      return;
    }
    dashboardApi.getPresence(selectedUnit.unit_id).then((p) => {
      setPresence((p.status as 'present' | 'away') || 'present');
      setAwayStartedAt(p.away_started_at || null);
      setGuestsAuthorizedDuringAway(p.guests_authorized_during_away ?? false);
    }).catch(() => {});
  }, [selectedUnit?.unit_id]);

  const loadPropertyLogs = useCallback(() => {
    setPropertyLogsLoading(true);
    const from_ts = logsFromDate ? localDateInputToUtcStartIso(logsFromDate) : undefined;
    const to_ts = logsToDate ? localDateInputToUtcEndIso(logsToDate) : undefined;
    const property_id = selectedUnit
      ? unitsData.find((u) => u.unit?.id === selectedUnit.unit_id)?.property?.id
      : undefined;
    dashboardApi.tenantLogs({
      from_ts,
      to_ts,
      category: logsCategory.trim() || undefined,
      search: logsSearch.trim() || undefined,
      ...(property_id != null ? { property_id } : {}),
    })
      .then(setPropertyLogs)
      .catch(() => setPropertyLogs([]))
      .finally(() => {
        setPropertyLogsLoading(false);
        setPropertyLogsLoadedOnce(true);
      });
  }, [logsFromDate, logsToDate, logsCategory, logsSearch, selectedUnit, unitsData]);

  useEffect(() => {
    if (activeTab === 'logs') loadPropertyLogs();
  }, [activeTab, loadPropertyLogs]);

  const doSetPresence = useCallback(async (status: 'present' | 'away', guestsAuthorized?: boolean) => {
    if (!selectedUnit?.unit_id) return;
    setPresenceUpdating(true);
    setShowAwayConfirm(false);
    try {
      const res = await dashboardApi.setPresence(selectedUnit.unit_id, status, guestsAuthorized);
      setPresence((res.presence as 'present' | 'away') || status);
      setAwayStartedAt(res.away_started_at ?? null);
      setGuestsAuthorizedDuringAway(res.guests_authorized_during_away ?? false);
      notify('success', `Status set to ${status}`);
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message || 'Failed to update status');
    } finally {
      setPresenceUpdating(false);
    }
  }, [selectedUnit?.unit_id, notify]);

  const handlePresenceToggle = useCallback(() => {
    if (!selectedUnit?.unit_id) return;
    if (presence === 'present') {
      setShowAwayConfirm(true);
      setAwayGuestsAuthorized(false);
      return;
    }
    doSetPresence('present');
  }, [selectedUnit?.unit_id, presence, doSetPresence]);

  const handleAddInviteLink = useCallback(async () => {
    const code = parseInviteCode(inviteLinkInput);
    if (!code) {
      notify('error', 'Please enter a valid invitation link or code.');
      return;
    }
    setAddingInvite(true);
    try {
      await dashboardApi.guestAddPendingInvite(code);
      setInviteLinkInput('');
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      openConfirmInviteModal(code);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Invalid or expired invitation. Please check the link.');
    } finally {
      setAddingInvite(false);
    }
  }, [inviteLinkInput, loadData, notify, openConfirmInviteModal]);

  const handleConfirmAcceptInvite = useCallback(async () => {
    if (!confirmInviteModal) return;
    if (!confirmTermsAgreed || !confirmPrivacyAgreed) {
      notify('error', 'Please agree to the Terms of Service and Privacy Policy to continue.');
      return;
    }
    setConfirmAccepting(true);
    const code = confirmInviteModal.code;
    const sigId = confirmInviteModal.accept_now_signature_id ?? null;
    try {
      await dashboardApi.guestAddPendingInvite(code).catch(() => {});
      await authApi.acceptInvite(code, sigId);
      acceptedInviteRef.current.add(code);
      notify('success', 'Invitation accepted.');
      setConfirmInviteModal(null);
      await loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      setActiveTab('stays');
      setStayFilter('all');
    } catch (e) {
      const msg = (e as Error)?.message ?? '';
      if (msg.toLowerCase().includes('already')) {
        acceptedInviteRef.current.add(code);
        notify('success', 'Invitation already accepted.');
        setConfirmInviteModal(null);
        await loadData();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
        setActiveTab('stays');
        setStayFilter('all');
      } else {
        notify('error', msg || 'Could not accept invitation. Please try again.');
      }
    } finally {
      setConfirmAccepting(false);
    }
  }, [confirmInviteModal, confirmTermsAgreed, confirmPrivacyAgreed, notify, loadData]);

  const handleGuestCheckIn = useCallback(async (s: GuestStayView) => {
    setCheckingInStay(s);
    try {
      await dashboardApi.guestCheckIn(s.stay_id);
      notify('success', 'You are checked in. Your stay is now active.');
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not check in.');
    } finally {
      setCheckingInStay(null);
    }
  }, [loadData, notify]);

  const handleGuestEndStay = useCallback(async () => {
    if (!endStayConfirm) return;
    setEndingGuestStay(true);
    try {
      await dashboardApi.guestEndStay(endStayConfirm.stay_id);
      notify('success', 'Checkout complete. Your stay has ended.');
      setEndStayConfirm(null);
      setSelectedStay(null);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not end stay.');
    } finally {
      setEndingGuestStay(false);
    }
  }, [endStayConfirm, loadData, notify]);

  const handleGuestCancelStay = useCallback(async () => {
    if (!cancelStayConfirm) return;
    setCancellingGuestStay(true);
    try {
      await dashboardApi.guestCancelStay(cancelStayConfirm.stay_id);
      notify('success', 'Stay cancelled. Your upcoming stay has been removed.');
      setCancelStayConfirm(null);
      setSelectedStay(null);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not cancel stay.');
    } finally {
      setCancellingGuestStay(false);
    }
  }, [cancelStayConfirm, loadData, notify]);

  if (loading) {
    return (
      <div className="flex-grow w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8 flex items-center justify-center min-h-[200px]">
        <p className="text-slate-500 text-sm">Loading…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-grow w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8">
        <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <p className="text-slate-600 text-sm mb-4">Something went wrong loading your dashboard.</p>
          <Button variant="primary" className="rounded-lg font-medium" onClick={() => { setError(null); setLoadingState(true); loadData(); }}>Try again</Button>
        </div>
      </div>
    );
  }

  const isEmpty = unitsData.length === 0 && stays.length === 0 && pendingInvites.length === 0;
  const unitCards: TenantUnitCard[] = unitsData
    .filter((u) => u.unit && u.property)
    .map((u) => ({
      unit_id: u.unit!.id,
      unit_label: u.unit!.unit_label,
      property_name: u.property!.name || 'Property',
      property_address: u.property!.address || '',
      stay_start_date: u.stay_start_date,
      stay_end_date: u.stay_end_date,
      token_state: u.token_state,
      pending_acceptance: u.pending_acceptance === true,
      lease_cohort_id: u.lease_cohort_id,
      cohort_member_count: u.cohort_member_count,
      co_tenants: u.co_tenants,
      property_deleted_at: u.property_deleted_at ?? null,
    }));
  const today = getTodayStr();
  const selectedUnitData = selectedUnit ? unitsData.find((u) => u.unit?.id === selectedUnit.unit_id) : null;
  const unitDetailGuestAuthBundle =
    selectedUnitData?.property?.id != null
      ? buildTenantGuestAuthRows(invitations, guestHistory, selectedUnitData.property.id)
      : { active: [] as TenantGuestAuthActiveRow[], ended: [] as OwnerStayView[] };
  const startDate = selectedUnitData?.stay_start_date ?? null;
  const endDate = selectedUnitData?.stay_end_date ?? null;

  const pendingGuestExtensionRequests = guestExtensionRequests.filter((r) => r.status === 'pending');
  const pendingGuestExtensionForSelectedProperty =
    selectedUnitData?.property?.id != null
      ? pendingGuestExtensionRequests.filter((r) => r.property_id === selectedUnitData.property.id)
      : [];

  const scrollToTenantExtensionRequests = () => {
    document.getElementById('tenant-extension-requests')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const activeStays = stays.filter(
    (s) =>
      !s.checked_out_at &&
      !s.cancelled_at &&
      s.approved_stay_start_date <= today &&
      s.approved_stay_end_date >= today
  );
  const futureStays = stays.filter(
    (s) => !s.checked_out_at && !s.cancelled_at && s.approved_stay_start_date > today
  );
  const completedStays = stays.filter(
    (s) =>
      s.checked_out_at != null ||
      s.cancelled_at != null ||
      (s.approved_stay_end_date < today && !s.checked_out_at && !s.cancelled_at)
  );

  const isLeaseCancelled = (c: TenantUnitCard) => c.token_state === 'REVOKED' || c.token_state === 'CANCELLED';
  /** Accepted lease and today inside [start, end] (inclusive; open end if no end date). */
  const isCardActive = (c: TenantUnitCard) => {
    if (isLeaseCancelled(c)) return false;
    if (!tenantLeaseAcceptedOnCard(c)) return false;
    return tenantLeaseInCalendarWindow(today, c.stay_start_date, c.stay_end_date, false);
  };
  const isCardCompleted = (c: TenantUnitCard) => {
    if (isLeaseCancelled(c)) return true;
    const endY = leaseCalendarYmd(c.stay_end_date);
    return !!(endY && today > endY);
  };
  /** Not current/completed: upcoming dates or invite not yet accepted. */
  const isCardFuture = (c: TenantUnitCard) => {
    if (isCardActive(c) || isCardCompleted(c)) return false;
    const sdY = leaseCalendarYmd(c.stay_start_date);
    if (c.pending_acceptance) return true;
    return !!(sdY && today < sdY);
  };
  const activeCount = unitCards.filter(isCardActive).length + activeStays.length;
  const futureCount = unitCards.filter(isCardFuture).length + futureStays.length;
  const completedCount = unitCards.filter(isCardCompleted).length + completedStays.length;
  const futureInvites = pendingInvites.filter((inv) => {
    if (stays.some((s) => datesOverlap(inv.stay_start_date, inv.stay_end_date, s.approved_stay_start_date, s.approved_stay_end_date))) return false;
    if (unitsData.some((u) => u.stay_start_date && u.stay_end_date &&
        datesOverlap(inv.stay_start_date, inv.stay_end_date, u.stay_start_date, u.stay_end_date))) return false;
    return true;
  });
  const futureInvitesCount = futureInvites.length;
  const filteredStays: GuestStayView[] =
    stayFilter === 'all'
      ? stays
      : stayFilter === 'active'
        ? activeStays
        : stayFilter === 'future'
          ? futureStays
          : stayFilter === 'completed'
            ? completedStays
            : [];
  const filteredUnitCards: TenantUnitCard[] =
    stayFilter === 'all'
      ? unitCards
      : stayFilter === 'active'
        ? unitCards.filter(isCardActive)
        : stayFilter === 'future'
          ? unitCards.filter(isCardFuture)
          : stayFilter === 'completed'
            ? unitCards.filter(isCardCompleted)
            : [];
  const filterButtons: { id: StayFilter; label: string; count: number }[] = [
    { id: 'all', label: 'All', count: unitCards.length + stays.length },
    { id: 'active', label: 'Active', count: activeCount },
    { id: 'future', label: 'Future', count: futureCount },
    { id: 'completed', label: 'Completed', count: completedCount },
    { id: 'future_invites', label: 'Future invites', count: futureInvitesCount },
  ];
  const selected = selectedUnit ?? (stayFilter === 'future_invites' ? null : filteredUnitCards[0] ?? unitCards[0]) ?? null;
  const dLeft = selected && startDate && endDate && today <= endDate ? daysLeft(endDate) : 0;
  const totalDays = selected && startDate && endDate ? Math.max(1, Math.ceil((new Date(endDate).getTime() - new Date(startDate).getTime()) / (1000 * 60 * 60 * 24))) : 1;
  const elapsedDays = Math.max(0, totalDays - dLeft);
  const progressPercent = selected && startDate && endDate ? Math.min(100, (elapsedDays / totalDays) * 100) : 0;

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-[#f0f4ff]/50">
      {/* Sidebar */}
      <aside className="hidden lg:flex w-64 min-w-[16rem] flex-shrink-0 flex-col bg-white/80 backdrop-blur-xl border-r border-slate-200 p-5">
        <nav className="space-y-1">
          {[
            { id: 'stays' as TenantTab, label: 'Lease & guests', icon: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
            { id: 'property' as TenantTab, label: 'Property info', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
            { id: 'invitations' as TenantTab, label: 'Add invitation', icon: 'M12 6v6m0 0v6m0-6h6m-6 0H6' },
            { id: 'logs' as TenantTab, label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
            { id: 'documents' as TenantTab, label: 'Documents', icon: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z' },
            { id: 'help' as TenantTab, label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${activeTab === item.id ? 'bg-slate-100 text-slate-800 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon} /></svg>
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
        <div className="lg:hidden mb-4">
          <select
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value as TenantTab)}
            className="w-full max-w-xs rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm"
          >
            <option value="stays">Lease & guests</option>
            <option value="property">Property info</option>
            <option value="invitations">Add invitation</option>
            <option value="logs">Event ledger</option>
            <option value="documents">Documents</option>
            <option value="help">Help Center</option>
          </select>
        </div>

        {activeTab !== 'help' && <DashboardAlertsPanel role="tenant" className="mb-6" limit={50} />}

        {activeTab !== 'help' && (
          <section
            id="tenant-extension-requests"
            className="mb-6 rounded-2xl border border-[#6B90F2]/40 bg-[#6B90F2]/5 p-6 shadow-sm"
          >
            <h2 className="text-lg font-semibold text-slate-900 mb-1">Guest extension requests</h2>
            <p className="text-sm text-slate-600 mb-4">
              This is where you open, approve, or decline a guest’s longer-stay ask. Notifications above only remind you—they don’t replace this list. Approving emails the guest; you still send a new invitation with new dates from Invite a guest. Owner and managers are not notified.
            </p>
            {guestExtensionRequests.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-200 bg-white/70 px-4 py-3 text-sm text-slate-600">
                <p className="font-medium text-slate-800 mb-1">No extension requests in DocuStay yet</p>
                <p>
                  If you only see a notification but no row here, that notice may be from before requests were stored here. Ask the guest to tap <strong>Request extension</strong> again on their stay, or confirm the API database has a row in <code className="text-xs bg-slate-100 px-1 py-0.5 rounded">guest_extension_requests</code> for your tenant account.
                </p>
              </div>
            ) : (
            <ul className="space-y-3">
              {guestExtensionRequests.map((req) => (
                <li
                  key={req.id}
                  className={`rounded-xl border p-4 ${
                    req.status === 'pending' ? 'border-amber-200 bg-white' : 'border-slate-200 bg-white/80'
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-slate-900">{req.guest_name}</span>
                        <span className="text-sm text-slate-500">{req.guest_email}</span>
                        <span
                          className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${
                            req.status === 'pending'
                              ? 'bg-amber-100 text-amber-900 border border-amber-200'
                              : req.status === 'approved'
                                ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                                : 'bg-slate-200 text-slate-700 border border-slate-300'
                          }`}
                        >
                          {req.status === 'pending' ? 'Needs response' : req.status === 'approved' ? 'Approved' : 'Declined'}
                        </span>
                      </div>
                      <p className="text-sm text-slate-700">
                        {req.property_name}
                        {req.unit_label ? ` · Unit ${req.unit_label}` : ''}
                      </p>
                      <p className="text-sm text-slate-600">
                        Stay dates: {formatCalendarDate(req.stay_start_date)} – {formatCalendarDate(req.stay_end_date)}
                      </p>
                      {req.message ? (
                        <p className="text-sm text-slate-700 mt-2">
                          <span className="font-medium text-slate-800">Guest note:</span> {req.message}
                        </p>
                      ) : null}
                      {req.status !== 'pending' && req.tenant_note ? (
                        <p className="text-sm text-slate-600 mt-1">
                          <span className="font-medium">Your note to guest:</span> {req.tenant_note}
                        </p>
                      ) : null}
                      <p className="text-xs text-slate-400 mt-1">Requested {formatDateTimeLocal(req.created_at)}</p>
                    </div>
                    {req.status === 'pending' ? (
                      <div className="flex flex-wrap gap-2 shrink-0">
                        <Button
                          type="button"
                          variant="primary"
                          className="rounded-lg text-sm"
                          onClick={() => {
                            setExtensionDecision({ req, action: 'approve' });
                            setExtensionDecisionNote('');
                            setExtensionApproveInviteCode('');
                          }}
                        >
                          Approve
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="rounded-lg text-sm border-red-200 text-red-700 hover:bg-red-50"
                          onClick={() => {
                            setExtensionDecision({ req, action: 'decline' });
                            setExtensionDecisionNote('');
                            setExtensionApproveInviteCode('');
                          }}
                        >
                          Decline
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
            )}
          </section>
        )}

        {/* Property info tab */}
        {activeTab === 'property' && (
          <div className="space-y-6 w-full">
            {/* Property address & unit */}
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-900 mb-4">Property information</h2>
              {selectedUnitData?.property_deleted_at ? (
                <div className="mb-4">
                  <InactivePropertyBanner role="tenant" />
                </div>
              ) : null}
              {selectedUnitData?.property ? (
                <div className="space-y-3">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">Property address</p>
                    <p className="text-base font-medium text-slate-800">{selectedUnitData.property.name}</p>
                    <p className="text-sm text-slate-600 mt-0.5">{selectedUnitData.property.address}</p>
                  </div>
                  {selectedUnitData.unit && (
                    <div>
                      <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">Unit</p>
                      <p className="text-base font-medium text-slate-800">{selectedUnitData.unit.unit_label}</p>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No property assigned.</p>
              )}
            </div>

            {/* Assigned tenants */}
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-900 mb-4">Assigned tenants</h2>
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 border border-slate-100">
                  <span className="text-sm font-medium text-slate-800">{user.user_name || user.email}</span>
                  <span className={`text-xs font-semibold uppercase tracking-wide px-2 py-0.5 rounded ${presence === 'away' ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'bg-emerald-50 text-emerald-700 border border-emerald-200'}`}>
                    {presence === 'away' ? 'Away' : 'Present'}
                  </span>
                </div>
              </div>
              <p className="text-xs text-slate-400 mt-3">Multiple tenants may be assigned to the same unit. Each tenant has their own account and can trigger actions independently.</p>
            </div>

            {/* Resident status */}
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-900 mb-4">Resident status</h2>
              <div className="flex items-center gap-4">
                <span className={`text-lg font-bold ${presence === 'away' ? 'text-amber-600' : 'text-emerald-600'}`}>
                  {presence === 'away' ? 'Away' : 'Present'}
                </span>
                {awayStartedAt && presence === 'away' && (
                  <span className="text-sm text-slate-500">since {formatDateTimeLocal(awayStartedAt)}</span>
                )}
              </div>
              {guestsAuthorizedDuringAway && presence === 'away' && (
                <p className="text-sm text-slate-600 mt-2">Guests authorized during this away period.</p>
              )}
            </div>

            {/* Property status */}
            {verificationRecord?.property_status && (
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-slate-900 mb-4">Property status</h2>
                <div className="flex items-center gap-3">
                  <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold ${
                    verificationRecord.property_status === 'occupied' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
                    verificationRecord.property_status === 'vacant' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
                    'bg-slate-100 text-slate-600 border border-slate-200'
                  }`}>
                    <span className={`w-2 h-2 rounded-full ${
                      verificationRecord.property_status === 'occupied' ? 'bg-emerald-500' :
                      verificationRecord.property_status === 'vacant' ? 'bg-amber-500' : 'bg-slate-400'
                    }`} />
                    {verificationRecord.property_status === 'occupied' ? 'Occupied' :
                     verificationRecord.property_status === 'vacant' ? 'Vacant' : 'Unknown'}
                  </span>
                </div>
              </div>
            )}

            {/* Verification record */}
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-900 mb-2">Verification record</h2>
              <p className="text-sm text-slate-500 mb-4">Property authorization documents and guest agreements from invitations you created for this property.</p>

              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-100">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold text-slate-800">Power of Attorney (POA)</h3>
                    {verificationRecord?.poa_signed_at ? (
                      <span className="inline-flex items-center gap-1 text-xs text-emerald-700 font-medium bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                        Signed
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400 font-medium">Not available</span>
                    )}
                  </div>
                  {verificationRecord?.poa_signed_at && (
                    <p className="text-xs text-slate-500 mb-2">Signed on {formatDateTimeLocal(verificationRecord.poa_signed_at)}</p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {verificationRecord?.poa_url && (
                      <Button
                        type="button"
                        variant="outline"
                        className="text-sm h-9 px-4 rounded-lg"
                        onClick={() =>
                          window.open(resolveBackendMediaUrl(verificationRecord.poa_url!), '_blank', 'noopener,noreferrer')
                        }
                      >
                        View POA (file)
                      </Button>
                    )}
                    {selectedUnitData?.live_slug && (
                      <Button
                        type="button"
                        variant="outline"
                        className="text-sm h-9 px-4 rounded-lg"
                        onClick={() => {
                          void openLivePoaPdfInNewTab(selectedUnitData.live_slug!).then((r) => {
                            if (!r.ok) notify('error', r.userMessage);
                          });
                        }}
                      >
                        View POA (public PDF)
                      </Button>
                    )}
                  </div>
                  {!verificationRecord?.poa_url && !selectedUnitData?.live_slug && (
                    <p className="text-xs text-slate-500">
                      The property owner&apos;s Power of Attorney is not linked here yet. Use verification or ask your host when it is on file.
                    </p>
                  )}
                </div>

                {(verificationRecord?.guest_agreements ?? []).length > 0 && (
                  <div>
                    <h3 className="text-sm font-semibold text-slate-800 mb-2">Guest agreements you invited</h3>
                    <div className="space-y-2">
                      {(verificationRecord?.guest_agreements ?? []).map((ga) => (
                        <div key={ga.signature_id} className="p-3 rounded-lg bg-slate-50 border border-slate-100">
                          <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-slate-800">{ga.guest_name}</span>
                              {ga.token_state && (
                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${
                                  ga.token_state === 'BURNED' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
                                  ga.token_state === 'REVOKED' ? 'bg-red-50 text-red-700 border border-red-200' :
                                  ga.token_state === 'EXPIRED' ? 'bg-slate-100 text-slate-600 border border-slate-200' :
                                  ga.token_state === 'CANCELLED' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
                                  'bg-slate-100 text-slate-600 border border-slate-200'
                                }`}>
                                  {ga.token_state === 'BURNED' ? 'Active' : ga.token_state === 'STAGED' ? 'Pending' : ga.token_state}
                                </span>
                              )}
                            </div>
                            <span className="inline-flex items-center gap-1 text-xs text-emerald-700 font-medium bg-emerald-50 px-2 py-0.5 rounded-full">
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                              Signed
                            </span>
                          </div>
                          <p className="text-xs text-slate-500">
                            {ga.document_title}
                            {ga.stay_start_date && ga.stay_end_date && ` · ${formatCalendarDate(ga.stay_start_date)} – ${formatCalendarDate(ga.stay_end_date)}`}
                          </p>
                          {ga.signed_at && (
                            <p className="text-xs text-slate-400 mt-0.5">Signed on {formatDateTimeLocal(ga.signed_at)}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {(verificationRecord?.guest_agreements ?? []).length === 0 && (
                  <p className="text-sm text-slate-500">No guest agreements have been signed yet for invitations you created. When a guest signs, it will appear here and under Documents.</p>
                )}
              </div>
            </div>

            {/* Invite a guest */}
            {selectedUnitData?.unit && (
              <div className="rounded-2xl border border-[#6B90F2]/30 bg-[#6B90F2]/5 p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-slate-900 mb-2">Invite a guest</h2>
                <p className="text-sm text-slate-600 mb-4">
                  Generate an invitation link for a guest to sign and stay at this property. A new invite for the same guest supersedes the old one once they accept.
                </p>
                <Button variant="primary" className="rounded-lg font-medium" onClick={() => setInviteModalOpen(true)}>
                  Invite guest to this property
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Documents tab */}
        {activeTab === 'documents' && (
          <div className="space-y-6 w-full">
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-900 mb-4">Documents</h2>
              <p className="text-sm text-slate-600 mb-4">
                Agreements you signed as a guest, and agreements guests signed for stays you invited them to at this property.
              </p>
              <div className="space-y-3">
                {signedDocs.length > 0 ? (
                  signedDocs.map((doc) => {
                    const isGuestInvite = doc.record_type === 'guest_invited_by_you';
                    return (
                      <div key={doc.signature_id} className="p-4 rounded-lg bg-slate-50 border border-slate-100">
                        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                          <p className="font-medium text-slate-800 text-sm">{doc.document_title}</p>
                          <div className="flex flex-wrap items-center gap-2">
                            {isGuestInvite ? (
                              <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-sky-50 text-sky-800 border border-sky-200">
                                Guest you invited
                              </span>
                            ) : (
                              <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
                                Your signature
                              </span>
                            )}
                            <span className="inline-flex items-center gap-1 text-xs text-emerald-700 font-medium bg-emerald-50 px-2 py-0.5 rounded-full">
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                              Signed
                            </span>
                          </div>
                        </div>
                        {doc.property_name && (
                          <p className="text-xs text-slate-600 mb-1"><span className="font-medium text-slate-700">Property:</span> {doc.property_name}</p>
                        )}
                        {doc.stay_start_date && doc.stay_end_date && (
                          <p className="text-xs text-slate-600 mb-1">
                            <span className="font-medium text-slate-700">Stay:</span> {formatCalendarDate(doc.stay_start_date)} – {formatCalendarDate(doc.stay_end_date)}
                          </p>
                        )}
                        <div className="flex flex-wrap items-center justify-between gap-2 mt-2">
                          <p className="text-xs text-slate-500">
                            {isGuestInvite ? (
                              <>Guest signed as <span className="font-medium text-slate-700">{doc.signed_by}</span>{doc.signed_at ? ` on ${formatDateTimeLocal(doc.signed_at)}` : ''}</>
                            ) : (
                              <>Signed by you ({doc.signed_by}){doc.signed_at ? ` on ${formatDateTimeLocal(doc.signed_at)}` : ''}</>
                            )}
                          </p>
                          <div className="flex items-center gap-2">
                            {doc.has_signed_pdf && (
                              <Button
                                type="button"
                                variant="outline"
                                className="text-xs h-7 px-2 rounded-lg shrink-0"
                                onClick={() => window.open(`${API_URL}/agreements/signature/${doc.signature_id}/signed-pdf`, '_blank', 'noopener,noreferrer')}
                              >
                                View PDF
                              </Button>
                            )}
                            <p className="text-xs text-slate-400">Invite {doc.invitation_code}</p>
                          </div>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <p className="text-sm text-slate-500">
                    No signed documents yet. When you sign an agreement as a guest, or a guest signs an invitation you created, it will appear here.
                  </p>
                )}
                <div className="pt-3 border-t border-slate-100">
                  <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Master Power of Attorney</p>
                  <p className="text-sm text-slate-600 mb-3">
                    The owner-signed Master POA is system-wide documentation authority for this property—not tied to your role. You can open it whenever it is on file.
                  </p>
                  {(() => {
                    const liveSlug = (selectedUnitData?.live_slug ?? '').trim() || null;
                    const hasMediaPoa = Boolean(verificationRecord?.poa_url);
                    const signedAt = verificationRecord?.poa_signed_at;
                    return (
                      <div className="p-3 rounded-lg bg-slate-50 border border-slate-100 mt-2 space-y-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-medium text-slate-800">Power of Attorney (POA)</p>
                            {signedAt ? (
                              <p className="text-xs text-slate-500">Signed on {formatDateTimeLocal(signedAt)}</p>
                            ) : (
                              <p className="text-xs text-slate-500">Status: not on file in your dashboard yet</p>
                            )}
                          </div>
                          <div className="flex flex-wrap gap-2 justify-end">
                            {hasMediaPoa && (
                              <Button
                                type="button"
                                variant="outline"
                                className="text-xs h-8 px-3 rounded-lg shrink-0"
                                onClick={() =>
                                  window.open(
                                    resolveBackendMediaUrl(verificationRecord!.poa_url!),
                                    '_blank',
                                    'noopener,noreferrer',
                                  )
                                }
                              >
                                View POA (file)
                              </Button>
                            )}
                            {liveSlug && (
                              <Button
                                type="button"
                                variant="outline"
                                className="text-xs h-8 px-3 rounded-lg shrink-0"
                                onClick={() => {
                                  void openLivePoaPdfInNewTab(liveSlug).then((r) => {
                                    if (!r.ok) notify('error', r.userMessage);
                                  });
                                }}
                              >
                                View POA (public PDF)
                              </Button>
                            )}
                          </div>
                        </div>
                        {!hasMediaPoa && !liveSlug && (
                          <p className="text-xs text-slate-500">
                            No POA link is available here yet. Your host or property contact can complete verification, or try again after the property publishes a live page.
                          </p>
                        )}
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Invitations tab */}
        {activeTab === 'invitations' && (
          <div className="space-y-6 w-full">
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-900 mb-1">Add invitation</h2>
              <p className="text-sm text-slate-600 mb-4">
                {isEmpty ? 'Paste an invitation link from your host to view and sign the agreement.' : 'Have another link? Add it below to review and sign.'}
              </p>
              <div className="flex flex-col sm:flex-row gap-3">
                <div className="flex-1 min-w-0">
                  <Input
                    label="Invitation link or code"
                    name="invite_link"
                    value={inviteLinkInput}
                    onChange={(e) => setInviteLinkInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddInviteLink(); } }}
                    placeholder="Paste link or code (e.g. INV-XXXX)"
                  />
                </div>
                <Button
                  type="button"
                  className="shrink-0 self-stretch sm:self-auto sm:mt-7 h-10 px-5 rounded-lg font-medium text-white border-0 bg-[#6B90F2] hover:bg-[#5a7ed9]"
                  onClick={handleAddInviteLink}
                  disabled={addingInvite || !parseInviteCode(inviteLinkInput)}
                >
                  {addingInvite ? 'Loading…' : 'Review invitation'}
                </Button>
              </div>
            </div>
            {pendingInvites.length > 0 && (
              <div className="rounded-2xl border border-blue-200 bg-blue-50/80 p-6 shadow-sm">
                <h2 className="text-base font-semibold text-slate-900 mb-1">Pending invitations</h2>
                <p className="text-sm text-slate-600 mb-4">Accept these invitations to confirm your assignments.</p>
                <ul className="space-y-3">
                  {pendingInvites.map((inv) => (
                    <li key={inv.invitation_code} className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl border border-blue-100 bg-white">
                      <div className="min-w-0 flex-1">
                        {inv.property_deleted_at ? <InactivePropertyBanner role="tenant" compact className="text-left mb-3" /> : null}
                        <p className="font-semibold text-slate-900">{inv.property_name}{inv.unit_label ? ` — Unit ${inv.unit_label}` : ''}</p>
                        <p className="text-sm text-slate-500 mt-0.5">{formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}</p>
                      </div>
                      <Button variant="primary" className="shrink-0 h-10 rounded-lg font-medium px-4" onClick={() => openConfirmInviteModal(inv.invitation_code, inv)}>Review & accept</Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-base font-semibold text-slate-900 mb-1">Future invites</h2>
              <p className="text-sm text-slate-500 mb-4">Invitations that don&apos;t overlap your existing stays.</p>
              {futureInvites.length === 0 ? (
                <p className="text-slate-500 text-sm">No future invites. Add an invitation link above.</p>
              ) : (
                <ul className="space-y-3">
                  {futureInvites.map((inv) => (
                    <li key={inv.invitation_code} className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl border border-slate-200 bg-slate-50/50">
                      <div className="min-w-0 flex-1">
                        {inv.property_deleted_at ? <InactivePropertyBanner role="tenant" compact className="text-left mb-3" /> : null}
                        <p className="font-semibold text-slate-900">{inv.property_name}{inv.unit_label ? ` — Unit ${inv.unit_label}` : ''}</p>
                        <p className="text-sm text-slate-500 mt-0.5">{formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}</p>
                      </div>
                      <Button variant="primary" className="shrink-0 h-10 rounded-lg font-medium px-4" onClick={() => openConfirmInviteModal(inv.invitation_code, inv)}>
                        Review & accept
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {/* Event ledger tab */}
        {activeTab === 'logs' && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900 mb-2">Event ledger</h2>
            <p className="text-sm text-slate-500 mb-4">Activity for your property, your actions, and invitations you created.</p>
            <div className="flex flex-wrap gap-3 items-center mb-4">
              <input type="date" value={logsFromDate} onChange={(e) => setLogsFromDate(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <input type="date" value={logsToDate} onChange={(e) => setLogsToDate(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              <select value={logsCategory} onChange={(e) => setLogsCategory(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm min-w-[10rem]">
                <option value="">All categories</option>
                <option value="status_change">Status change</option>
                <option value="presence">Presence / Away</option>
                <option value="guest_signature">Guest signature</option>
                <option value="billing">Billing</option>
              </select>
              <input type="text" placeholder="Search…" value={logsSearch} onChange={(e) => setLogsSearch(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm w-40" />
              <Button variant="outline" onClick={loadPropertyLogs} disabled={propertyLogsLoading}>{propertyLogsLoading ? 'Loading…' : 'Apply filters'}</Button>
            </div>
            {propertyLogsLoading && propertyLogs.length === 0 ? (
              <p className="p-6 text-slate-500 text-center text-sm">Loading…</p>
            ) : propertyLogsLoadedOnce && propertyLogs.length === 0 ? (
              <p className="p-6 text-slate-500 text-center text-sm">No events.</p>
            ) : propertyLogs.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                    <tr>
                      <th className="px-4 py-3">Time</th>
                      <th className="px-4 py-3">Category</th>
                      <th className="px-4 py-3">Title</th>
                      <th className="px-4 py-3">Actor</th>
                      <th className="px-4 py-3">Message</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {propertyLogs.map((entry) => (
                      <tr key={entry.id} className="hover:bg-slate-50">
                        <td className="px-4 py-2 text-slate-600 text-sm whitespace-nowrap">{formatLedgerTimestamp(entry.created_at)}</td>
                        <td className="px-4 py-2">
                          <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                            entry.category === 'failed_attempt' ? 'bg-red-100 text-red-800' :
                            entry.category === 'guest_signature' ? 'bg-emerald-100 text-emerald-800' :
                            entry.category === 'shield_mode' ? 'bg-violet-100 text-violet-800' :
                            entry.category === 'dead_mans_switch' ? 'bg-amber-100 text-amber-800' :
                            entry.category === 'billing' ? 'bg-slate-200 text-slate-800' :
                            entry.category === 'presence' ? 'bg-teal-100 text-teal-800' : 'bg-sky-100 text-sky-800'
                          }`}>
                            {entry.category === 'shield_mode' ? 'Shield Mode' : entry.category === 'dead_mans_switch' ? 'Stay end reminders' : entry.category === 'billing' ? 'Billing' : entry.category === 'presence' ? 'Presence' : entry.category.replace('_', ' ')}
                          </span>
                        </td>
                        <td className="px-4 py-2 font-medium text-slate-800 text-sm">{entry.title}</td>
                        <td className="px-4 py-2 text-slate-600 text-sm">{entry.actor_email ?? '—'}</td>
                        <td className="px-4 py-2 text-slate-600 text-sm max-w-xs">
                          <span className="truncate block">{entry.message}</span>
                          <button type="button" onClick={() => setLogMessageModalEntry(entry)} className="text-sky-600 hover:text-sky-800 text-xs mt-0.5 focus:outline-none focus:underline">View full message</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        )}

        {/* Help tab */}
        {activeTab === 'help' && (
          <div className="max-w-3xl">
            <HelpCenter navigate={() => {}} embedded />
          </div>
        )}

        {/* Stays tab */}
        {activeTab === 'stays' && (
        <div className="flex flex-col lg:flex-row gap-6 lg:gap-8">
          <div className="lg:w-80 xl:w-96 flex-shrink-0 space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs text-slate-600 mb-3 leading-relaxed">
                <span className="font-semibold text-slate-800">Lease</span> is your long-term unit assignment.
                <span className="font-semibold text-slate-800"> Guest visits</span> are short-term authorizations where you were invited as a visitor.
              </p>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">Filter</h3>
              <div className="flex flex-wrap gap-2">
                {filterButtons.map(({ id, label, count }) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => { setStayFilter(id); if (id !== 'future_invites') { setSelectedUnit(null); setSelectedStay(null); } }}
                    className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${stayFilter === id ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                  >
                    {label} ({count})
                  </button>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden max-h-[calc(100vh-20rem)] overflow-y-auto">
              <div className="p-4">
              {stayFilter === 'future_invites' ? (
                futureInvites.length === 0 ? (
                  <p className="text-slate-500 text-sm py-4">No future invites. Add an invitation link in the Add invitation tab.</p>
                ) : (
                  <ul className="space-y-2">
                    {futureInvites.map((inv) => (
                      <li key={inv.invitation_code} className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
                        {inv.property_deleted_at ? <InactivePropertyBanner role="tenant" compact className="text-left mb-2" /> : null}
                        <p className="font-semibold text-slate-900 text-sm">{inv.property_name}{inv.unit_label ? ` — Unit ${inv.unit_label}` : ''}</p>
                        <p className="text-xs text-slate-500 mt-0.5">{formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}</p>
                        <Button variant="primary" className="mt-2 w-full text-xs h-8 py-1.5" onClick={() => openConfirmInviteModal(inv.invitation_code, inv)}>
                          Review & accept
                        </Button>
                      </li>
                    ))}
                  </ul>
                )
              ) : (filteredUnitCards.length === 0 && filteredStays.length === 0) ? (
                <div className="py-4 space-y-2">
                  <p className="text-slate-600 text-sm">
                    {stayFilter === 'all' ? 'No assignments yet.' : stayFilter === 'completed' ? 'No completed assignments.' : `No ${stayFilter} assignments.`} Add an invitation link in the Add invitation tab.
                  </p>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const d = await dashboardApi.tenantDebug();
                        notify('success', `Backend has ${d.tenant_assignments_count} unit assignment(s) and ${d.stays_count} stay(s) for your account.`);
                      } catch {
                        notify('error', 'Could not fetch debug info.');
                      }
                    }}
                    className="text-xs text-slate-500 hover:text-slate-700 underline"
                  >
                    Check if my accepted invite is in the database
                  </button>
                </div>
              ) : (
            <div className="flex flex-col gap-2">
              {filteredUnitCards.length > 0 && (
                <>
                  <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 px-1 pt-1">Your lease</h4>
                  {filteredUnitCards.map((card) => {
                    const td = getTodayStr();
                    const sd = card.stay_start_date ?? null;
                    const ed = card.stay_end_date ?? null;
                    const isCancelled = card.token_state === 'REVOKED' || card.token_state === 'CANCELLED';
                    const accepted = tenantLeaseAcceptedOnCard(card);
                    const inWindow = tenantLeaseInCalendarWindow(td, sd, ed, isCancelled);
                    const sdY = leaseCalendarYmd(sd);
                    const edY = leaseCalendarYmd(ed);
                    const isFuture = !isCancelled && !!sdY && td < sdY;
                    const isPast = !isCancelled && !!edY && td > edY;
                    const isActive = accepted && inWindow;
                    const pendingInWindow = !!card.pending_acceptance && !isCancelled && inWindow;
                    const statusLabel = isCancelled
                      ? 'CANCELLED'
                      : isFuture
                        ? 'FUTURE'
                        : isActive
                          ? 'ACTIVE'
                          : pendingInWindow
                            ? 'PENDING'
                            : 'ENDED';
                    const statusClass = isCancelled
                      ? 'bg-slate-100 text-slate-600 border border-slate-200'
                      : isFuture
                        ? 'bg-sky-200 text-white border-0'
                        : isActive
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-100'
                          : pendingInWindow
                            ? 'bg-amber-50 text-amber-800 border border-amber-200'
                            : 'bg-slate-100 text-slate-600 border border-slate-200';
                    const isSelected = !selectedStay && selected?.unit_id === card.unit_id;
                    const cardUnitData = unitsData.find((u) => u.unit?.id === card.unit_id);
                    const addressDisplay = card.property_address || `${card.property_name}${card.unit_label ? ` — Unit ${card.unit_label}` : ''}`;
                    return (
                      <div
                        key={`unit-${card.unit_id}-${card.stay_start_date ?? ''}-${card.stay_end_date ?? ''}`}
                        className={`rounded-xl border bg-white text-left transition-all ${
                          isSelected
                            ? 'border-slate-300 border-l-4 border-l-[#6B90F2] bg-[#6B90F2]/10 shadow-sm'
                            : 'border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => { setSelectedUnit(isSelected ? null : card); setSelectedStay(null); }}
                          className="w-full text-left p-4"
                        >
                          {card.property_deleted_at ? (
                            <InactivePropertyBanner role="tenant" compact className="text-left mb-3" />
                          ) : null}
                          <div className="flex items-center gap-2 mb-2 flex-wrap">
                            <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide ${statusClass}`}>
                              {statusLabel}
                            </span>
                            {cardUnitData?.region_code && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium text-slate-600 bg-slate-100 border border-slate-200">
                                {cardUnitData.region_code}
                              </span>
                            )}
                          </div>
                          <p className="text-sm font-semibold text-slate-900">{addressDisplay}</p>
                          <p className="text-sm text-slate-500 mt-0.5">
                            {sd && ed ? `${formatCalendarDate(sd)} – ${formatCalendarDate(ed)}` : sd ? `${formatCalendarDate(sd)} – Open-ended` : 'Your assigned unit'}
                          </p>
                          {(card.cohort_member_count ?? 1) > 1 && card.co_tenants && card.co_tenants.length > 0 && (
                            <p className="text-xs text-violet-800 mt-2 pt-2 border-t border-violet-100">
                              <span className="font-semibold">Co-tenants:</span> {formatCoTenantPeerLine(card.co_tenants)}
                            </p>
                          )}
                        </button>
                      </div>
                    );
                  })}
                </>
              )}
              {filteredStays.length > 0 && (
                <>
                  <h4
                    className={`text-[10px] font-bold uppercase tracking-wider text-slate-500 px-1 ${filteredUnitCards.length > 0 ? 'pt-3 mt-1 border-t border-slate-100' : 'pt-1'}`}
                  >
                    Guest visits
                  </h4>
                  {filteredStays.map((s) => {
                    const isStayActive = !!(s.checked_in_at && s.approved_stay_start_date <= today && s.approved_stay_end_date >= today);
                    const isStayFuture = s.approved_stay_start_date > today;
                    const isStayUpcoming = !s.checked_in_at && !s.checked_out_at && !s.cancelled_at && s.approved_stay_start_date <= today && s.approved_stay_end_date >= today;
                    const canCheckIn = isStayUpcoming;
                    const hasCheckedIn = !!(s.checked_in_at != null && s.checked_in_at !== '');
                    const canCheckout = (hasCheckedIn || s.revoked_at != null) && !s.checked_out_at && !s.cancelled_at && s.approved_stay_end_date >= today;
                    const canCancel = isStayFuture && !s.cancelled_at;
                    const isSelected = selectedStay?.stay_id === s.stay_id;
                    return (
                      <div
                        key={s.stay_id}
                        className={`rounded-xl border bg-white text-left transition-all ${
                          isSelected
                            ? 'border-slate-300 border-l-4 border-l-[#6B90F2] bg-[#6B90F2]/10 shadow-sm'
                            : 'border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => { setSelectedStay(isSelected ? null : s); setSelectedUnit(null); }}
                          className="w-full text-left p-4"
                        >
                          {s.property_deleted_at ? (
                            <InactivePropertyBanner role="tenant" compact className="text-left mb-3" />
                          ) : null}
                          <div className="flex items-center gap-2 mb-2 flex-wrap">
                            {(s.revoked_at || s.vacate_by) && (
                              <span className="px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide bg-red-50 text-red-700 border border-red-100">Revoked</span>
                            )}
                            <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide ${
                              s.cancelled_at ? 'bg-amber-50 text-amber-700 border border-amber-100' : s.checked_out_at ? 'bg-slate-100 text-slate-600 border border-slate-200' : isStayActive ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : isStayUpcoming ? 'bg-[#FFC107] text-slate-900 border-0' : isStayFuture ? 'bg-slate-200 text-slate-700 border-0' : 'bg-slate-100 text-slate-600'
                            }`}>
                              {s.cancelled_at ? 'Cancelled' : s.checked_out_at ? 'Completed' : isStayActive ? 'Active' : isStayUpcoming ? 'UPCOMING' : isStayFuture ? 'FUTURE' : 'Previous'}
                            </span>
                            <span className="text-slate-400 text-xs">{s.region_code}</span>
                          </div>
                          <p className="text-sm text-slate-600">
                            {s.property_name}{s.unit_label ? ` — Unit ${s.unit_label}` : ''}
                          </p>
                          <p className="text-sm text-slate-500 mt-0.5">
                            {formatCalendarDate(s.approved_stay_start_date)} – {formatCalendarDate(s.approved_stay_end_date)}
                          </p>
                        </button>
                        {canCheckIn && (
                          <div className="px-4 pb-4 pt-0">
                            <button
                              type="button"
                              disabled={!!checkingInStay}
                              className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-[#6F42C1] hover:bg-[#5e35a8] disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
                              onClick={(e) => { e.stopPropagation(); handleGuestCheckIn(s); }}
                            >
                              {checkingInStay?.stay_id === s.stay_id ? 'Checking in…' : 'Check in'}
                            </button>
                          </div>
                        )}
                        {canCheckout && (
                          <div className="px-4 pb-4 pt-0">
                            <button
                              type="button"
                              className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2"
                              onClick={(e) => { e.stopPropagation(); setEndStayConfirm(s); }}
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                              Checkout
                            </button>
                          </div>
                        )}
                        {canCancel && (
                          <div className="px-4 pb-4 pt-0">
                            <button
                              type="button"
                              className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors flex items-center justify-center gap-2"
                              onClick={(e) => { e.stopPropagation(); setCancelStayConfirm(s); }}
                            >
                              <span className="text-red-500 font-semibold">X</span> Cancel stay
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </>
              )}
            </div>
              )}
              </div>
            </div>
          </div>

          {/* Detail panel placeholder */}
          {!selected && !selectedStay && stayFilter !== 'future_invites' && (
            <div className="flex-1 min-w-0 flex items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50/50 p-12">
              <p className="text-slate-500 text-sm text-center">Select your unit or a guest stay to view details and actions.</p>
            </div>
          )}

      {/* Full-width detail when a guest visit is selected (Lease & guests tab; user is the invited guest) */}
      {selectedStay && stayFilter !== 'future_invites' && (() => {
        const stay = selectedStay;
        const detailHasCheckedIn = !!(stay.checked_in_at != null && stay.checked_in_at !== '');
        const stayDLeft = daysLeft(stay.approved_stay_end_date);
        const stayTotalDays = Math.max(1, Math.ceil((new Date(stay.approved_stay_end_date).getTime() - new Date(stay.approved_stay_start_date).getTime()) / (1000 * 60 * 60 * 24)));
        const stayElapsedDays = Math.max(0, stayTotalDays - stayDLeft);
        const stayProgressPercent = Math.min(100, (stayElapsedDays / stayTotalDays) * 100);
        return (
        <div className="flex-1 min-w-0 space-y-6 overflow-y-auto">
          {stay.revoked_at || stay.vacate_by ? (
            <div className="rounded-2xl border border-red-200 bg-red-50/80 p-5">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-lg bg-red-100 flex items-center justify-center flex-shrink-0">
                  <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                </div>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold text-red-900">Authorization Revoked</h3>
                  {stay.revoked_at && (
                    <p className="text-xs text-red-700 mt-1 font-medium">Effective date: {formatDateTimeLocal(stay.revoked_at)}</p>
                  )}
                  <p className="text-sm text-red-800 mt-2">The Property Owner has revoked your authorization to occupy the property. You are required to vacate the premises immediately.</p>
                  {stay.vacate_by && (
                    <p className="text-sm text-red-700 mt-2 font-medium">Vacate by: {formatDateTimeLocal(stay.vacate_by)}</p>
                  )}
                </div>
              </div>
            </div>
          ) : null}
          <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-8 shadow-sm">
            <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-8">
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-4 flex-wrap">
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-semibold uppercase tracking-wide ${
                    stay.cancelled_at
                      ? 'bg-amber-50 text-amber-700 border border-amber-100'
                      : stay.checked_out_at
                        ? 'bg-slate-100 text-slate-600'
                        : detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-100'
                          : !detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                            ? 'bg-[#FFC107] text-slate-900 border-0'
                            : stay.approved_stay_start_date > today
                              ? 'bg-slate-200 text-slate-700 border-0'
                              : 'bg-slate-100 text-slate-600'
                  }`}>
                    {stay.cancelled_at
                      ? 'Cancelled'
                      : stay.checked_out_at
                        ? 'Completed'
                        : detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                          ? 'Active'
                          : !detailHasCheckedIn && stay.approved_stay_start_date <= today && stay.approved_stay_end_date >= today
                            ? 'UPCOMING'
                            : stay.approved_stay_start_date > today
                              ? 'FUTURE'
                              : 'Ended'}
                  </span>
                  <span className="text-slate-400">·</span>
                  <span className="text-slate-500 text-sm">{stay.property_name}{stay.unit_label ? ` — Unit ${stay.unit_label}` : ''}</span>
                  <span className="text-slate-400 text-sm">({stay.region_code})</span>
                  {stay.invite_id && (
                    <>
                      <span className="text-slate-400">·</span>
                      <span className="text-slate-500 text-sm font-mono">Invite ID: {stay.invite_id}</span>
                      {stay.token_state && (
                        <span className={`ml-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                          stay.token_state === 'BURNED' ? 'bg-[#28A745] text-white' :
                          stay.token_state === 'EXPIRED' ? 'bg-slate-100 text-slate-600' :
                          stay.token_state === 'REVOKED' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'
                        }`}>
                          {stay.token_state === 'BURNED' ? 'Active' : stay.token_state === 'STAGED' ? 'Pending' : stay.token_state === 'EXPIRED' ? 'Expired' : stay.token_state === 'REVOKED' ? 'Revoked' : stay.token_state}
                        </span>
                      )}
                    </>
                  )}
                </div>
                <h1 className="text-2xl md:text-3xl font-bold text-slate-900 tracking-tight">
                  {stay.cancelled_at ? 'Stay cancelled' : stay.checked_out_at ? 'Stay completed' : stay.approved_stay_end_date < today ? 'Stay ended' : stay.approved_stay_start_date > today ? 'Upcoming stay' : 'Current stay'}
                </h1>
                <div className="flex gap-6 mt-4">
                  <div>
                    <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">CHECK-IN</p>
                    <p className="text-slate-900 font-medium mt-0.5">{formatCalendarDate(stay.approved_stay_start_date)}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">CHECK-OUT</p>
                    <p className="text-slate-900 font-medium mt-0.5">{formatCalendarDate(stay.approved_stay_end_date)}</p>
                  </div>
                </div>
              </div>
              <div className="md:w-56 flex flex-col gap-4 shrink-0">
                <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-slate-800 rounded-full transition-all duration-500" style={{ width: `${stayProgressPercent}%` }} />
                </div>
                <p className="text-xs text-slate-400 font-medium">Stay progress</p>
                {stay.property_live_slug && (
                  <Button
                    type="button"
                    className="w-full h-11 rounded-lg font-medium text-white border-0 bg-[#007BFF] hover:bg-[#006ee6] focus:ring-[#007BFF]"
                    onClick={() => { setLiveLinkSlug(stay.property_live_slug ?? null); setShowLiveLinkModal(true); }}
                  >
                    Open live link
                  </Button>
                )}
                {stay.property_live_slug && (
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full h-11 rounded-lg font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      void openLivePoaPdfInNewTab(stay.property_live_slug!).then((r) => {
                        if (!r.ok) notify('error', r.userMessage);
                      });
                    }}
                  >
                    View property POA (PDF)
                  </Button>
                )}
                {stay.invite_id && (
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full h-11 rounded-lg font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-50"
                    onClick={() => { setVerifyQRInviteId(stay.invite_id ?? null); setShowVerifyQRModal(true); }}
                  >
                    Verify with QR code
                  </Button>
                )}
                {!stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && stay.approved_stay_start_date <= today && !detailHasCheckedIn && (
                  <button
                    type="button"
                    disabled={!!checkingInStay}
                    className="w-full h-11 rounded-lg font-medium text-white bg-[#6F42C1] hover:bg-[#5e35a8] disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
                    onClick={() => handleGuestCheckIn(stay)}
                  >
                    {checkingInStay?.stay_id === stay.stay_id ? 'Checking in…' : 'Check in'}
                  </button>
                )}
                {!stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && (detailHasCheckedIn || stay.revoked_at != null) && (
                  <button
                    type="button"
                    className="w-full h-11 rounded-lg font-medium text-white bg-emerald-600 hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2"
                    onClick={() => setEndStayConfirm(stay)}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                    Complete checkout
                  </button>
                )}
                {!stay.cancelled_at && stay.approved_stay_start_date > today && (
                  <button
                    type="button"
                    className="w-full h-11 rounded-lg font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors flex items-center justify-center gap-2"
                    onClick={() => setCancelStayConfirm(stay)}
                  >
                    <span className="text-red-500 font-semibold">X</span> Cancel stay
                  </button>
                )}
              </div>
            </div>
          </section>
          {!stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && (() => {
            const allDays = dateRange(stay.approved_stay_start_date, stay.approved_stay_end_date);
            const total = allDays.length;
            const maxShow = 42;
            const showDays = total <= maxShow ? allDays : allDays.slice(-maxShow);
            return (
              <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-8 shadow-sm">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700 mb-4">TIME LEFT ON YOUR STAY</h3>
                <div className="flex flex-col sm:flex-row sm:items-center gap-8">
                  <div className="flex-shrink-0">
                    <div className="inline-flex flex-col items-center justify-center rounded-2xl bg-white border border-slate-200 shadow-inner px-8 py-6 min-w-[140px]">
                      <span className="text-4xl md:text-5xl font-bold tabular-nums text-slate-900">
                        {stayDLeft}
                      </span>
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-600 mt-1">
                        {stayDLeft === 0 ? 'DAY (CHECK-OUT TODAY)' : stayDLeft === 1 ? 'DAY LEFT' : 'DAYS LEFT'}
                      </span>
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-slate-500 mb-2">
                      Stay timeline – {formatCalendarDate(stay.approved_stay_start_date)} → {formatCalendarDate(stay.approved_stay_end_date)}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {showDays.map((dayStr) => {
                        const isToday = dayStr === today;
                        const isEnd = dayStr === stay.approved_stay_end_date;
                        const isPast = dayStr < today;
                        const dayNum = new Date(dayStr + 'T12:00:00').getDate();
                        return (
                          <div
                            key={dayStr}
                            title={`${dayStr}${isToday ? ' (today)' : ''}${isEnd ? ' (check-out)' : ''}`}
                            className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium transition-all ${
                              isToday
                                ? 'bg-[#6F42C1] text-white ring-2 ring-[#6F42C1]/30 ring-offset-1'
                                : isEnd
                                  ? 'bg-[#FFC107] text-slate-900 font-semibold'
                                  : isPast
                                    ? 'bg-slate-200 text-slate-500'
                                    : 'bg-slate-100 text-slate-700 border border-slate-200'
                            }`}
                          >
                            {dayNum}
                          </div>
                        );
                      })}
                    </div>
                    {total > maxShow && (
                      <p className="text-xs text-slate-400 mt-2">Showing last {maxShow} days of stay</p>
                    )}
                  </div>
                </div>
              </section>
            );
          })()}
        </div>
        );
      })()}

      {/* Unit detail when a unit is selected */}
      {selected && selectedUnitData && !selectedStay && stayFilter !== 'future_invites' && (
        <div className="flex-1 min-w-0 space-y-6 overflow-y-auto">
          {/* Hero: Current stay card - same layout as reference (badge, address, Invite ID, BURNED, CHECK-IN/OUT, Stay progress, Open live link, Verify QR, Check in) */}
          <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-8 shadow-sm">
            {selectedUnitData.property_deleted_at ? (
              <div className="mb-6">
                <InactivePropertyBanner role="tenant" />
              </div>
            ) : null}
            {(() => {
              const today = getTodayStr();
              const startDate = selectedUnitData.stay_start_date ?? null;
              const endDate = selectedUnitData.stay_end_date ?? null;
              const isCancelled = selectedUnitData.token_state === 'REVOKED' || selectedUnitData.token_state === 'CANCELLED';
              const leaseAccepted = selectedUnitData.pending_acceptance !== true;
              const startY = leaseCalendarYmd(startDate);
              const endY = leaseCalendarYmd(endDate);
              const inLeaseWindow = tenantLeaseInCalendarWindow(today, startDate, endDate, isCancelled);
              const isUpcoming = !isCancelled && !!startY && today < startY;
              const isPast = !isCancelled && !!endY && today > endY;
              const isActiveLease = leaseAccepted && inLeaseWindow && !isCancelled && !isUpcoming;
              const pendingInWindow = selectedUnitData.pending_acceptance === true && !isCancelled && inLeaseWindow;
              const progressPercent = startDate && endDate
                ? (() => {
                    const start = new Date(startDate).getTime();
                    const end = new Date(endDate).getTime();
                    const now = new Date().getTime();
                    if (now <= start) return 0;
                    if (now >= end) return 100;
                    return Math.round(((now - start) / (end - start)) * 100);
                  })()
                : 100;
              const leaseHeadlineBadge =
                isCancelled
                  ? { label: 'CANCELLED' as const, cls: 'bg-slate-100 text-slate-600 border border-slate-200' }
                  : isUpcoming
                    ? { label: 'UPCOMING' as const, cls: 'bg-amber-200 text-amber-900' }
                    : isActiveLease
                      ? { label: 'ACTIVE' as const, cls: 'bg-emerald-50 text-emerald-700 border border-emerald-100' }
                      : pendingInWindow
                        ? { label: 'PENDING' as const, cls: 'bg-amber-50 text-amber-800 border border-amber-200' }
                        : isPast
                          ? { label: 'ENDED' as const, cls: 'bg-slate-100 text-slate-600 border border-slate-200' }
                          : { label: 'ENDED' as const, cls: 'bg-slate-100 text-slate-600 border border-slate-200' };
              /** BURNED = invite accepted/signed, not necessarily “occupancy active”; only show Active inside the lease window. */
              const invTs = (selectedUnitData.token_state || '').toUpperCase();
              let inviteTokenLabel: string;
              let inviteTokenCls: string;
              if (selectedUnitData.pending_acceptance) {
                inviteTokenLabel = 'Pending';
                inviteTokenCls = 'bg-slate-100 text-slate-600';
              } else if (invTs === 'REVOKED' || invTs === 'CANCELLED') {
                inviteTokenLabel = 'Cancelled';
                inviteTokenCls = 'bg-slate-100 text-slate-600';
              } else if (invTs === 'EXPIRED') {
                inviteTokenLabel = 'Expired';
                inviteTokenCls = 'bg-slate-100 text-slate-600';
              } else if (invTs === 'STAGED') {
                inviteTokenLabel = 'Pending';
                inviteTokenCls = 'bg-slate-100 text-slate-600';
              } else if (invTs === 'BURNED') {
                if (isActiveLease) {
                  inviteTokenLabel = 'Active';
                  inviteTokenCls = 'bg-emerald-100 text-emerald-800';
                } else if (isUpcoming) {
                  inviteTokenLabel = 'Accepted';
                  inviteTokenCls = 'bg-sky-100 text-sky-900 border border-sky-200';
                } else if (isPast) {
                  inviteTokenLabel = 'Ended';
                  inviteTokenCls = 'bg-slate-100 text-slate-600 border border-slate-200';
                } else {
                  inviteTokenLabel = 'Accepted';
                  inviteTokenCls = 'bg-slate-100 text-slate-600';
                }
              } else {
                inviteTokenLabel = selectedUnitData.token_state || '—';
                inviteTokenCls = 'bg-slate-100 text-slate-600';
              }
              return (
                <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-8">
                  <div className="min-w-0">
                    {/* Target: single horizontal line — UPCOMING / Cancelled · address (FL) · Invite ID: INV-XXX · REVOKED */}
                    <div className="flex items-center gap-2 mb-4 flex-nowrap overflow-x-hidden min-h-[2rem]">
                      <span className={`inline-flex items-center shrink-0 px-2.5 py-1 rounded-lg text-xs font-semibold uppercase tracking-wide ${leaseHeadlineBadge.cls}`}>
                        {leaseHeadlineBadge.label}
                      </span>
                      <span className="text-slate-400 shrink-0">·</span>
                      <span className="text-slate-500 text-sm shrink-0 min-w-0 truncate">
                        {selected.property_address || selected.property_name}{selected.unit_label ? ` — Unit ${selected.unit_label}` : ''}{selectedUnitData.region_code ? ` (${selectedUnitData.region_code})` : ''}
                      </span>
                      {selectedUnitData.invite_id && (
                        <>
                          <span className="text-slate-400 shrink-0">·</span>
                          <span className="text-slate-500 text-sm shrink-0">
                            <span className="text-slate-500">Invite ID: </span>
                            <span className="text-slate-600 font-medium font-mono">{selectedUnitData.invite_id}</span>
                          </span>
                          {selectedUnitData.token_state && (
                            <span className={`shrink-0 ml-0.5 px-1.5 py-0.5 rounded text-xs font-medium ${inviteTokenCls}`}>
                              {inviteTokenLabel}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                    <h1 className="text-2xl md:text-3xl font-bold text-slate-900 tracking-tight">
                      {selectedUnitData.assigned_by_name != null || selectedUnitData.accepted_by_name != null
                        ? selectedUnitData.pending_acceptance
                          ? `Assigned residence by ${selectedUnitData.assigned_by_name ?? '—'} (pending acceptance)`
                          : `Assigned residence by ${selectedUnitData.assigned_by_name ?? '—'} and accepted by ${selectedUnitData.accepted_by_name ?? '—'}`
                        : 'Assigned residence'}
                    </h1>
                    {selectedUnitData.property_owner_transfer_notice ? (
                      <p className="text-sm text-slate-600 mt-2">{selectedUnitData.property_owner_transfer_notice}</p>
                    ) : null}
                    <div className="flex gap-6 mt-4">
                      <div>
                        <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">START DATE</p>
                        <p className="text-slate-900 font-medium mt-0.5">{startDate ? formatCalendarDate(startDate) : '—'}</p>
                      </div>
                      <div>
                        <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">END DATE</p>
                        <p className="text-slate-900 font-medium mt-0.5">{endDate ? formatCalendarDate(endDate) : 'Open-ended'}</p>
                      </div>
                    </div>
                    {(selectedUnitData.cohort_member_count ?? 1) > 1 &&
                      selectedUnitData.co_tenants &&
                      selectedUnitData.co_tenants.length > 0 && (
                        <div className="mt-4 p-4 rounded-xl border border-violet-100 bg-violet-50/60">
                          <p className="text-xs font-semibold uppercase tracking-wide text-violet-800 mb-1">Co-tenants on this lease</p>
                          <p className="text-sm text-slate-800">{formatCoTenantPeerLine(selectedUnitData.co_tenants)}</p>
                        </div>
                      )}
                  </div>
                  <div className="md:w-56 flex flex-col gap-4 shrink-0">
                    <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div className="h-full bg-slate-800 rounded-full transition-all duration-500" style={{ width: `${progressPercent}%` }} />
                    </div>
                    <p className="text-xs text-slate-400 font-medium">Residency progress</p>
                    {selectedUnitData.live_slug && (
                      <Button
                        type="button"
                        className="w-full h-11 rounded-lg font-medium text-white border-0 bg-[#007BFF] hover:bg-[#006ee6] focus:ring-[#007BFF]"
                        onClick={() => { setLiveLinkSlug(selectedUnitData.live_slug ?? null); setShowLiveLinkModal(true); }}
                      >
                        Open live link
                      </Button>
                    )}
                    {selectedUnitData.live_slug && (
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full h-11 rounded-lg font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-50"
                        onClick={() => {
                          void openLivePoaPdfInNewTab(selectedUnitData.live_slug!).then((r) => {
                            if (!r.ok) notify('error', r.userMessage);
                          });
                        }}
                      >
                        View property POA (PDF)
                      </Button>
                    )}
                    {selectedUnitData.invite_id && (
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full h-11 rounded-lg font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-60 disabled:cursor-not-allowed"
                        onClick={() => { setVerifyQRInviteId(selectedUnitData.invite_id ?? null); setShowVerifyQRModal(true); }}
                      >
                        Verify with QR code
                      </Button>
                    )}
                    {!selectedUnitData.invite_id && (
                      <Button type="button" variant="outline" disabled className="w-full h-11 rounded-lg font-medium bg-white border border-slate-300 text-slate-400">
                        Verify with QR code
                      </Button>
                    )}
                    {isPast && !isCancelled && (
                      <p className="text-sm text-slate-500 font-medium">Residency ended</p>
                    )}
                    {isCancelled && (
                      <p className="text-sm text-slate-600 font-medium">This assignment was cancelled.</p>
                    )}
                  </div>
                </div>
              );
            })()}
          </section>

          {pendingGuestExtensionForSelectedProperty.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50/90 px-4 py-3 text-sm text-amber-950">
              <span className="font-semibold">
                {pendingGuestExtensionForSelectedProperty.length === 1
                  ? '1 guest extension request'
                  : `${pendingGuestExtensionForSelectedProperty.length} guest extension requests`}{' '}
                need a response
              </span>
              {' · '}
              <button
                type="button"
                className="text-[#6B90F2] font-semibold underline hover:no-underline"
                onClick={scrollToTenantExtensionRequests}
              >
                Jump to Guest extension requests
              </button>
            </div>
          )}

          {/* Guest authorizations: pending invites + accepted stays in one list */}
          {(unitDetailGuestAuthBundle.active.length > 0 || unitDetailGuestAuthBundle.ended.length > 0) && (
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              {selectedUnitData.property_deleted_at ? (
                <div className="mb-4">
                  <InactivePropertyBanner role="tenant" compact />
                </div>
              ) : null}
              <h3 className="text-base font-semibold text-slate-900 mb-4">Guest authorizations</h3>
              <p className="text-sm text-slate-500 mb-4">
                Each row is one guest authorization: a pending invite link or an accepted stay. Revoke ends authorization before or after the guest accepts.
                If a guest needs new dates, create a new invitation from here—when they accept, it replaces their previous authorization.
              </p>
              <div className="space-y-6">
                {unitDetailGuestAuthBundle.active.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Pending &amp; active</h4>
                    <ul className="space-y-2">
                      {unitDetailGuestAuthBundle.active.map((row) =>
                        row.kind === 'accepted' ? (
                          <li key={row.key} className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-slate-100 last:border-0 text-sm">
                            <div>
                              <span className="font-medium text-slate-900">{row.stay.guest_name}</span>
                              <span className="text-slate-500"> · {formatCalendarDate(row.stay.stay_start_date)} – {formatCalendarDate(row.stay.stay_end_date)}</span>
                              {row.stay.unit_label ? (
                                <span className="text-slate-500"> · Unit {row.stay.unit_label}</span>
                              ) : null}
                              <span className="ml-1.5 px-1.5 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-700">Accepted</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-2 shrink-0">
                              {(() => {
                                // Single source of truth: if it's in Signed documents, open that same PDF here.
                                const code = (row.stay.invite_id || '').trim();
                                const sigDoc = code ? tenantSignedAgreementForInviteCode(code, signedDocs) : undefined;
                                if (sigDoc) {
                                  return (
                                    <Button
                                      type="button"
                                      variant="outline"
                                      className="text-xs h-8 px-3 shrink-0"
                                      onClick={() => openTenantGuestSignedAgreementForSignature(sigDoc.signature_id)}
                                    >
                                      View agreement
                                    </Button>
                                  );
                                }
                                // Fallback: if we have a real stay row, open by stay_id.
                                if (!row.stay.invitation_only && row.stay.stay_id > 0) {
                                  return (
                                    <Button
                                      type="button"
                                      variant="outline"
                                      className="text-xs h-8 px-3 shrink-0"
                                      onClick={() => openTenantGuestSignedAgreementForStay(row.stay.stay_id)}
                                    >
                                      View agreement
                                    </Button>
                                  );
                                }
                                return null;
                              })()}
                              {tenantCanRevokeGuestStay(row.stay) && (
                                <Button type="button" variant="outline" className="text-xs h-8 px-3 text-red-600 border-red-200 hover:bg-red-50 shrink-0" onClick={() => setRevokeConfirmStay(row.stay)}>
                                  Revoke stay
                                </Button>
                              )}
                            </div>
                          </li>
                        ) : (
                          <li key={row.key} className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-slate-100 last:border-0 text-sm">
                            <span className="text-slate-700">
                              {row.inv.guest_name || row.inv.guest_email || '—'} · {row.inv.status}
                              {row.inv.unit_label ? (
                                <span className="text-slate-500"> · Unit {row.inv.unit_label}</span>
                              ) : null}
                              {row.inv.stay_start_date && row.inv.stay_end_date && (
                                <span className="text-slate-500 text-xs block"> {formatCalendarDate(row.inv.stay_start_date)} – {formatCalendarDate(row.inv.stay_end_date)}</span>
                              )}
                            </span>
                            <div className="flex flex-wrap items-center gap-2 shrink-0">
                              {(() => {
                                const sigDoc = tenantSignedAgreementForInviteCode(row.inv.invitation_code, signedDocs);
                                return sigDoc ? (
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    className="rounded-lg text-xs h-8 px-3"
                                    onClick={() => openTenantGuestSignedAgreementForSignature(sigDoc.signature_id)}
                                  >
                                    View agreement
                                  </Button>
                                ) : null;
                              })()}
                              {row.inv.is_demo && (
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="rounded-lg text-xs h-8 px-3"
                                  onClick={() => window.open(demoStoredUnsignedGuestAgreementPdfUrl(row.inv.invitation_code), '_blank')}
                                >
                                  Unsigned PDF
                                </Button>
                              )}
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="rounded-lg text-xs h-8 px-3"
                                onClick={async (e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  const url = buildGuestInviteUrl(row.inv.invitation_code, { isDemo: Boolean(row.inv.is_demo) });
                                  const ok = await copyToClipboard(url);
                                  if (ok) notify('success', 'Invitation link copied.');
                                  else notify('error', 'Could not copy.');
                                }}
                              >
                                Copy link
                              </Button>
                              <Button
                                variant="outline"
                                className="rounded-lg text-xs h-8 px-3 text-red-600 border-red-200 hover:bg-red-50"
                                onClick={() => setInviteRevokeConfirm(row.inv)}
                              >
                                Revoke
                              </Button>
                            </div>
                          </li>
                        )
                      )}
                    </ul>
                  </div>
                )}
                {unitDetailGuestAuthBundle.ended.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Ended</h4>
                    <ul className="space-y-2">
                      {unitDetailGuestAuthBundle.ended.map((h) => (
                        <li key={`${h.property_id}-${h.stay_id}-${h.invite_id ?? ''}`} className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-slate-100 last:border-0 text-sm">
                          <div>
                            <span className="font-medium text-slate-900">{h.guest_name}</span>
                            <span className="text-slate-500"> · {formatCalendarDate(h.stay_start_date)} – {formatCalendarDate(h.stay_end_date)}</span>
                            {h.unit_label ? (
                              <span className="text-slate-500"> · Unit {h.unit_label}</span>
                            ) : null}
                            {(() => {
                              const b = endedGuestAuthorizationBadge(h);
                              return (
                                <span className={`ml-1.5 px-1.5 py-0.5 rounded text-xs font-medium ${b.className}`}>
                                  {b.label}
                                </span>
                              );
                            })()}
                          </div>
                          {(() => {
                            const code = (h.invite_id || '').trim();
                            const sigDoc = code ? tenantSignedAgreementForInviteCode(code, signedDocs) : undefined;
                            if (sigDoc) {
                              return (
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="text-xs h-8 px-3 shrink-0"
                                  onClick={() => openTenantGuestSignedAgreementForSignature(sigDoc.signature_id)}
                                >
                                  View agreement
                                </Button>
                              );
                            }
                            if (!h.invitation_only && h.stay_id > 0) {
                              return (
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="text-xs h-8 px-3 shrink-0"
                                  onClick={() => openTenantGuestSignedAgreementForStay(h.stay_id)}
                                >
                                  View agreement
                                </Button>
                              );
                            }
                            return null;
                          })()}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </section>
          )}

          <div className="grid lg:grid-cols-3 gap-6">
            {/* Left: Presence (here/away) + Invite guest */}
            <div className="lg:col-span-2 space-y-6">
              {/* Presence - same UI as Guest: here/away for this property (tenant keeps this) */}
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h4 className="font-semibold text-slate-900 mb-3">Presence at this property</h4>
                <p className="text-sm text-slate-600 mb-4">Let your host know if you are at the property or away.</p>
                <div className="flex flex-wrap items-center gap-4">
                  <div className={`px-4 py-2 rounded-lg ${presence === 'present' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                    {presence === 'present' ? 'You are here' : awayStartedAt ? `Away since ${formatDateTimeLocal(awayStartedAt)}` : 'Away'}
                  </div>
                  {presence === 'away' && guestsAuthorizedDuringAway && (
                    <span className="text-sm text-slate-600">Guests authorized during this period</span>
                  )}
                  <Button variant="outline" onClick={handlePresenceToggle} disabled={presenceUpdating} className="rounded-lg">
                    Set to {presence === 'present' ? 'Away' : 'Present'}
                  </Button>
                </div>
                {showAwayConfirm && (
                  <div className="mt-4 p-4 rounded-lg bg-slate-50 border border-slate-200">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={awayGuestsAuthorized} onChange={(e) => setAwayGuestsAuthorized(e.target.checked)} className="rounded" />
                      <span className="text-sm text-slate-700">Guests authorized during this period</span>
                    </label>
                    <div className="flex gap-2 mt-3">
                      <Button onClick={() => doSetPresence('away', awayGuestsAuthorized)} disabled={presenceUpdating}>Confirm Away</Button>
                      <Button variant="outline" onClick={() => setShowAwayConfirm(false)}>Cancel</Button>
                    </div>
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h3 className="text-base font-semibold text-slate-900 mb-1">Invite a guest to this property</h3>
                <p className="text-sm text-slate-500 mb-2">{selected.property_name}{selected.unit_label ? ` — Unit ${selected.unit_label}` : ''}</p>
                <p className="text-sm text-slate-600 mb-4">
                  Generate an invitation link for a guest to sign and stay at this property. A new invite for the same guest supersedes the old one once they accept.
                </p>
                <Button variant="primary" className="rounded-lg font-medium" onClick={() => setInviteModalOpen(true)}>
                  Invite guest to this property
                </Button>
              </div>
            </div>

            {/* Right: Need help + applicable law */}
            <div className="space-y-6">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h4 className="font-semibold text-slate-900 mb-3">Need help?</h4>
                <p className="text-xs text-slate-600 mb-3">
                  Contact us at{' '}
                  <a href={supportMailtoHref()} className="text-[#6B90F2] font-medium hover:underline break-all">
                    {SUPPORT_EMAIL}
                  </a>
                </p>
                <div className="flex flex-col gap-2">
                  <Button type="button" variant="outline" className="w-full justify-center h-10 rounded-lg text-sm font-medium">Message host</Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-center h-10 rounded-lg text-sm font-medium"
                    onClick={() => {
                      window.location.href = supportMailtoHref();
                    }}
                  >
                    Contact support
                  </Button>
                </div>
              </div>
              {/* Applicable law from Jurisdiction SOT (same as guest dashboard and live property page) */}
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-700 mb-2">
                  APPLICABLE LAW {selectedUnitData?.jurisdiction_state_name || selectedUnitData?.region_code ? `(${(selectedUnitData?.jurisdiction_state_name ?? selectedUnitData?.region_code ?? 'State').toUpperCase()})` : ''}
                </p>
                {(selectedUnitData?.jurisdiction_statutes && selectedUnitData.jurisdiction_statutes.length > 0) ? (
                  <>
                    <ul className="mt-2 space-y-2">
                      {selectedUnitData.jurisdiction_statutes.map((s, i) => (
                        <li key={i} className="text-sm text-slate-700">
                          <span className="font-medium text-slate-900">{s.citation}</span>
                          {s.plain_english && <span className="block text-slate-600 mt-0.5">{s.plain_english}</span>}
                        </li>
                      ))}
                    </ul>
                    {selectedUnitData.removal_guest_text && (
                      <p className="text-slate-600 text-sm mt-2">
                        <span className="font-medium text-slate-700">Guest removal: </span>{selectedUnitData.removal_guest_text}
                      </p>
                    )}
                    {selectedUnitData.removal_tenant_text && (
                      <p className="text-slate-600 text-sm mt-0.5">
                        <span className="font-medium text-slate-700">Tenant eviction: </span>{selectedUnitData.removal_tenant_text}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-slate-500">Jurisdiction and statutes for this property are available from your host or on the live property page.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
        </div>
        )}

      </main>

      {/* Tenant invite confirmation modal */}
      {confirmInviteModal && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-lg w-full rounded-2xl bg-white shadow-xl border border-slate-200 overflow-hidden">
            <div className="bg-gradient-to-r from-slate-800 to-slate-900 p-6 text-white relative">
              <div className="absolute top-0 right-0 w-40 h-full bg-[#6B90F2]/20 blur-[40px] rounded-full"></div>
              <div className="relative z-10">
                <span className="inline-block px-3 py-1 rounded-full bg-[#6B90F2]/30 text-blue-300 text-xs font-bold uppercase tracking-widest mb-3">Tenant Invitation</span>
                <h2 className="text-2xl font-bold">Accept this invitation?</h2>
                {confirmInviteModal.host_name && (
                  <p className="text-slate-300 text-sm mt-1">Invited by <span className="text-white font-semibold">{confirmInviteModal.host_name}</span></p>
                )}
              </div>
            </div>

            <div className="p-6 space-y-5">
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-4 space-y-3">
                <div className="flex items-start gap-3">
                  <svg className="w-5 h-5 text-[#6B90F2] mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                  <div>
                    <p className="font-semibold text-slate-900">{confirmInviteModal.property_name}</p>
                    {confirmInviteModal.property_address && <p className="text-sm text-slate-500">{confirmInviteModal.property_address}</p>}
                  </div>
                </div>
                {(confirmInviteModal.stay_start_date || confirmInviteModal.stay_end_date) && (
                  <div className="flex items-center gap-3 pl-8">
                    <svg className="w-4 h-4 text-slate-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
                    <p className="text-sm text-slate-600">
                      {confirmInviteModal.stay_start_date ? formatCalendarDate(confirmInviteModal.stay_start_date) : '—'}
                      {' — '}
                      {confirmInviteModal.stay_end_date ? formatCalendarDate(confirmInviteModal.stay_end_date) : 'Open-ended'}
                    </p>
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Agreements</p>
                <label className="flex items-start gap-3 cursor-pointer p-3 rounded-xl border border-slate-200 bg-white hover:border-slate-300 transition-colors">
                  <input
                    type="checkbox"
                    checked={confirmTermsAgreed}
                    onChange={(e) => setConfirmTermsAgreed(e.target.checked)}
                    className="w-5 h-5 rounded border-slate-300 text-[#6B90F2] focus:ring-[#6B90F2] shrink-0 mt-0.5"
                  />
                  <span className="text-sm text-slate-700">I agree to the <a href="#terms" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-semibold hover:underline">Terms of Service</a>.</span>
                </label>
                <label className="flex items-start gap-3 cursor-pointer p-3 rounded-xl border border-slate-200 bg-white hover:border-slate-300 transition-colors">
                  <input
                    type="checkbox"
                    checked={confirmPrivacyAgreed}
                    onChange={(e) => setConfirmPrivacyAgreed(e.target.checked)}
                    className="w-5 h-5 rounded border-slate-300 text-[#6B90F2] focus:ring-[#6B90F2] shrink-0 mt-0.5"
                  />
                  <span className="text-sm text-slate-700">I agree to the <a href="#privacy" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-semibold hover:underline">Privacy Policy</a>.</span>
                </label>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  className="flex-1 h-11 rounded-lg font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors"
                  onClick={() => setConfirmInviteModal(null)}
                  disabled={confirmAccepting}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={!confirmTermsAgreed || !confirmPrivacyAgreed || confirmAccepting}
                  className="flex-1 h-11 rounded-lg font-medium text-white bg-[#6B90F2] hover:bg-[#5a7ed9] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
                  onClick={handleConfirmAcceptInvite}
                >
                  {confirmAccepting ? 'Accepting…' : 'Confirm & Accept'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Log message modal */}
      <Modal
        open={!!logMessageModalEntry}
        onClose={() => setLogMessageModalEntry(null)}
        title={logMessageModalEntry?.title ?? 'Log entry'}
        className="max-w-lg"
      >
        {logMessageModalEntry && (
          <div className="p-6">
            <p className="text-slate-700 whitespace-pre-wrap text-sm">{logMessageModalEntry.message}</p>
            <p className="text-slate-500 text-xs mt-4">
              {logMessageModalEntry.created_at ? formatDateTimeLocal(logMessageModalEntry.created_at) : ''}
              {logMessageModalEntry.actor_email && ` · ${logMessageModalEntry.actor_email}`}
            </p>
          </div>
        )}
      </Modal>

      {/* Live link modal – same as Guest */}
      {showLiveLinkModal && liveLinkSlug && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-sm w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200 relative">
            <button type="button" onClick={() => { setShowLiveLinkModal(false); setLiveLinkSlug(null); setCopyToast(null); }} className="absolute top-4 right-4 text-slate-400 hover:text-slate-700">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1 text-center">Live link page</h3>
            <p className="text-slate-500 text-sm mb-4 text-center">Scan or share this link to open the property info page (no login).</p>
            <div className="flex justify-center mb-4">
              <div className="bg-slate-50 p-4 rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${liveLinkSlug}`)}`}
                  alt="QR code for live link"
                  className="w-40 h-40 rounded-lg"
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                variant="primary"
                className="w-full"
                onClick={() => window.open(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${liveLinkSlug}`, '_blank', 'noopener,noreferrer')}
              >
                Open live page
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={async (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const url = `${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${liveLinkSlug}`;
                  const ok = await copyToClipboard(url);
                  setCopyToast(ok ? 'Live link copied to clipboard.' : 'Could not copy.');
                  setTimeout(() => setCopyToast(null), 3000);
                }}
              >
                Copy live link
              </Button>
            </div>
            {copyToast && (
              <p className={`text-sm text-center mt-2 ${copyToast.startsWith('Live link') ? 'text-emerald-600' : 'text-amber-600'}`}>
                {copyToast}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Verify with QR code modal – same as Guest */}
      {showVerifyQRModal && verifyQRInviteId && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-sm w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200 relative">
            <button type="button" onClick={() => { setShowVerifyQRModal(false); setVerifyQRInviteId(null); setCopyToast(null); }} className="absolute top-4 right-4 text-slate-400 hover:text-slate-700">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1 text-center">Verify with QR code</h3>
            <p className="text-slate-500 text-sm mb-4 text-center">Scan to open the Verify page with this stay&apos;s token pre-filled.</p>
            <div className="flex justify-center mb-4">
              <div className="bg-slate-50 p-4 rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#check?token=${encodeURIComponent(verifyQRInviteId)}`)}`}
                  alt="QR code for verify page"
                  className="w-40 h-40 rounded-lg"
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                variant="primary"
                className="w-full"
                onClick={() => window.open(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#check?token=${encodeURIComponent(verifyQRInviteId)}`, '_blank', 'noopener,noreferrer')}
              >
                Open verify page
              </Button>
            </div>
          </div>
        </div>
      )}

      {endStayConfirm && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
            <h3 className="text-lg font-bold text-slate-900 mb-2">Checkout of this stay?</h3>
            <p className="text-slate-600 text-sm mb-6">
              This will end your stay at <strong>{endStayConfirm.property_name}</strong>. This action cannot be undone.
            </p>
            <div className="flex gap-3">
              <button type="button" className="flex-1 h-11 rounded-lg font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50" onClick={() => setEndStayConfirm(null)}>
                Go back
              </button>
              <button
                type="button"
                disabled={endingGuestStay}
                className="flex-1 h-11 rounded-lg font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 flex items-center justify-center"
                onClick={handleGuestEndStay}
              >
                {endingGuestStay ? 'Ending…' : 'Checkout'}
              </button>
            </div>
          </div>
        </div>
      )}

      {cancelStayConfirm && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
            <h3 className="text-lg font-bold text-slate-900 mb-2">Cancel this stay?</h3>
            <p className="text-slate-600 text-sm mb-6">
              This will cancel your upcoming stay at <strong>{cancelStayConfirm.property_name}</strong>. This action cannot be undone.
            </p>
            <div className="flex gap-3">
              <button type="button" className="flex-1 h-11 rounded-lg font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50" onClick={() => setCancelStayConfirm(null)}>
                Go back
              </button>
              <button
                type="button"
                disabled={cancellingGuestStay}
                className="flex-1 h-11 rounded-lg font-medium text-white bg-slate-700 hover:bg-slate-800 disabled:opacity-60 flex items-center justify-center"
                onClick={handleGuestCancelStay}
              >
                {cancellingGuestStay ? 'Cancelling…' : 'Cancel stay'}
              </button>
            </div>
          </div>
        </div>
      )}


      <Modal
        open={!!extensionDecision}
        title={extensionDecision?.action === 'approve' ? 'Approve extension request' : 'Decline extension request'}
        onClose={() => {
          if (!extensionDecisionSubmitting) {
            setExtensionDecision(null);
            setExtensionDecisionNote('');
            setExtensionApproveInviteCode('');
          }
        }}
        disableBackdropClose={extensionDecisionSubmitting}
        className="max-w-lg"
      >
        {extensionDecision && (
          <div className="p-6 space-y-4">
            <p className="text-sm text-slate-600">
              <span className="font-semibold text-slate-900">{extensionDecision.req.guest_name}</span>
              {' · '}
              {formatCalendarDate(extensionDecision.req.stay_start_date)} – {formatCalendarDate(extensionDecision.req.stay_end_date)}
            </p>
            {extensionDecision.action === 'approve' ? (
              <div className="space-y-3">
                <p className="text-sm text-slate-600">
                  Extensions use a new guest invitation. Create one with the extended dates (same guest email), then paste its link or Invite ID below. The guest will be emailed that you approved and will receive this link to accept the new stay.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  className="rounded-lg text-sm w-full sm:w-auto"
                  disabled={extensionDecisionSubmitting}
                  onClick={() => openInviteForExtensionRequest(extensionDecision.req)}
                >
                  Open Invite guest (prefilled)
                </Button>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                    New invitation link or Invite ID <span className="text-red-600">*</span>
                  </label>
                  <Input
                    value={extensionApproveInviteCode}
                    onChange={(e) => setExtensionApproveInviteCode(e.target.value)}
                    placeholder="Paste full invite URL or code (e.g. ABC123)"
                    disabled={extensionDecisionSubmitting}
                    className="w-full"
                  />
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-600">
                The guest will receive an email that you are not extending their stay at this time. You can add an optional message below.
              </p>
            )}
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Optional message to guest (included in email)
              </label>
              <textarea
                className="w-full min-h-[88px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#6B90F2]"
                maxLength={1000}
                value={extensionDecisionNote}
                onChange={(e) => setExtensionDecisionNote(e.target.value)}
                placeholder={extensionDecision.action === 'decline' ? 'e.g. lease ends this month; unable to host longer' : 'e.g. I will send a new invite with updated checkout'}
              />
              <p className="text-xs text-slate-400 mt-1">{extensionDecisionNote.length}/1000</p>
            </div>
            <div className="flex flex-wrap gap-3 justify-end pt-2">
              <Button
                variant="outline"
                className="rounded-lg"
                disabled={extensionDecisionSubmitting}
                onClick={() => {
                  setExtensionDecision(null);
                  setExtensionDecisionNote('');
                  setExtensionApproveInviteCode('');
                }}
              >
                Cancel
              </Button>
              <Button
                variant={extensionDecision.action === 'decline' ? 'danger' : 'primary'}
                className="rounded-lg"
                disabled={
                  extensionDecisionSubmitting ||
                  (extensionDecision.action === 'approve' && !parseInviteCode(extensionApproveInviteCode))
                }
                onClick={() => { void submitExtensionDecision(); }}
              >
                {extensionDecisionSubmitting
                  ? 'Saving…'
                  : extensionDecision.action === 'approve'
                    ? 'Approve & notify guest'
                    : 'Decline & notify guest'}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <InviteGuestModal
        open={inviteModalOpen}
        onClose={() => {
          setInviteModalOpen(false);
          setInviteModalPrefill(null);
        }}
        user={user}
        setLoading={setLoading}
        notify={notify}
        navigate={navigate}
        onSuccess={() => { loadData(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }}
        unitId={selectedUnitData?.unit?.id ?? null}
        propertyOrStayLabel={selected ? `${selected.property_name}${selected.unit_label ? ` — Unit ${selected.unit_label}` : ''}` : null}
        tenantStayStartDate={selectedUnitData?.stay_start_date ?? null}
        tenantStayEndDate={selectedUnitData?.stay_end_date ?? null}
        prefillGuestEmail={inviteModalPrefill?.email ?? null}
        prefillGuestName={inviteModalPrefill?.name ?? null}
        onLinkGenerated={(link) => {
          setInviteModalOpen(false);
          setInviteModalPrefill(null);
          setGeneratedInviteLink(link);
        }}
      />

      <Modal
        open={!!inviteRevokeConfirm}
        title="Cancel this invitation?"
        onClose={() => !inviteRevokeLoading && setInviteRevokeConfirm(null)}
        disableBackdropClose={inviteRevokeLoading}
        className="max-w-md"
      >
        <div className="p-6 space-y-4">
          <p className="text-slate-600 text-sm">
            This will cancel the pending invitation for{' '}
            <span className="font-semibold text-slate-900">{inviteRevokeConfirm?.guest_name || inviteRevokeConfirm?.guest_email || 'the guest'}</span>
            . They will no longer be able to accept this link. This does not apply after a guest has already accepted — use &quot;Revoke stay&quot; on their accepted row instead.
          </p>
          <div className="flex flex-wrap gap-3 justify-end">
            <Button variant="outline" onClick={() => setInviteRevokeConfirm(null)} disabled={inviteRevokeLoading} className="rounded-lg">
              Back
            </Button>
            <Button variant="danger" onClick={handleTenantInviteRevokeConfirm} disabled={inviteRevokeLoading} className="rounded-lg">
              {inviteRevokeLoading ? 'Cancelling…' : 'Cancel invitation'}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={!!revokeConfirmStay}
        title="Revoke guest stay authorization"
        onClose={() => !revokeLoading && setRevokeConfirmStay(null)}
        disableBackdropClose={revokeLoading}
        className="max-w-md"
      >
        <div className="p-6 space-y-4">
          <p className="text-slate-600 text-sm">
            Revoking <span className="font-semibold text-slate-900">{revokeConfirmStay?.guest_name}</span> will end their authorization and send a 12-hour vacate notice (same as when a property owner revokes a stay). Proceed?
          </p>
          <div className="flex flex-wrap gap-3 justify-end">
            <Button variant="outline" onClick={() => setRevokeConfirmStay(null)} disabled={revokeLoading} className="rounded-lg">
              Cancel
            </Button>
            <Button variant="danger" onClick={handleTenantRevokeConfirm} disabled={revokeLoading} className="rounded-lg">
              {revokeLoading ? 'Revoking…' : 'Revoke stay'}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={!!revokeSuccessGuest}
        title="Stay revoked"
        onClose={() => setRevokeSuccessGuest(null)}
        className="max-w-md"
      >
        <div className="p-6 space-y-4">
          <p className="text-slate-600 text-sm">
            Stay authorization for <span className="font-semibold text-slate-900">{revokeSuccessGuest}</span> has been revoked. They must vacate within 12 hours. A confirmation is in your dashboard notifications.
          </p>
          <Button className="w-full rounded-lg" onClick={() => setRevokeSuccessGuest(null)}>
            Done
          </Button>
        </div>
      </Modal>

      {generatedInviteLink && (
        <Modal
          open={!!generatedInviteLink}
          onClose={() => { setGeneratedInviteLink(null); loadData(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }}
          title="Invitation link generated"
          className="max-w-lg"
        >
          <div className="p-6 space-y-4">
            <p className="text-sm text-slate-600">Share this link with your guest. They will sign in or create an account, then sign the agreement on their dashboard.</p>
            <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 break-all">
              {generatedInviteLink}
            </div>
            <div className="flex gap-3">
              <Button variant="outline" onClick={async () => { const ok = await copyToClipboard(generatedInviteLink); notify(ok ? 'success' : 'error', ok ? 'Link copied to clipboard.' : 'Copy failed.'); }} className="flex-1">Copy link</Button>
              <Button onClick={() => { setGeneratedInviteLink(null); loadData(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }} className="flex-1">Done</Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};

export default TenantDashboard;
