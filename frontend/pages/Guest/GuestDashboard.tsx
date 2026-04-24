import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Button, Input, Modal } from '../../components/UI';
import { UserSession } from '../../types';
import { dashboardApi, authApi, agreementsApi, openLivePoaPdfInNewTab, APP_ORIGIN, type GuestStayView, type GuestPendingInviteView, type OwnerAuditLogEntry } from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import AgreementSignModal, { type PrefilledGuestInfo } from '../../components/AgreementSignModal';
import PendingSignatureModal from '../../components/PendingSignatureModal';
import HelpCenter from '../Support/HelpCenter';
import { DashboardAlertsPanel, DASHBOARD_ALERTS_REFRESH_EVENT } from '../../components/DashboardAlertsPanel';
import { InactivePropertyBanner } from '../../components/InactivePropertyBanner';
import { PENDING_INVITE_STORAGE_KEY } from './GuestLogin';
import { SUPPORT_EMAIL, supportMailtoHref } from '../../constants/supportContact';
import {
  formatCalendarDate,
  formatDateTimeLocal,
  formatLedgerTimestamp,
  localDateInputToUtcEndIso,
  localDateInputToUtcStartIso,
  parseForDisplay,
} from '../../utils/dateUtils';
import { scrubAuditLogStateChangeParagraph } from '../../utils/auditLogMessage';
import {
  filterOpenGuestFacingStays,
  guestFacingCompletedStays,
  guestDashboardStayRowKey,
  guestStayRowDisplayForGuestView,
  GUEST_STAY_INLINE_BADGE_CLASS,
  isGuestStayPhysicallyCheckedIn,
} from '../../utils/guestStayState';
import { JURISDICTION_CONTEXT_DISCLAIMER } from '../../utils/jurisdictionUiCopy';

type GuestTab = 'stays' | 'invitations' | 'ledger' | 'help';

const DROPBOX_REDIRECT_INVITATION_CODE = 'docustay_dropbox_redirect_invitation_code';
const DROPBOX_REDIRECT_SIGNATURE_ID = 'docustay_dropbox_redirect_signature_id';

function parseInviteCode(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
}

function daysLeft(endDateStr: string): number {
  const end = parseForDisplay(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.max(0, Math.ceil((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)));
}

/** True if [start1, end1] overlaps [start2, end2] (dates as YYYY-MM-DD or parseable strings). */
function datesOverlap(
  start1: string,
  end1: string,
  start2: string,
  end2: string
): boolean {
  const a1 = parseForDisplay(start1).getTime();
  const a2 = parseForDisplay(end1).getTime();
  const b1 = parseForDisplay(start2).getTime();
  const b2 = parseForDisplay(end2).getTime();
  return a1 < b2 && a2 > b1;
}

/** Today's date in local timezone as YYYY-MM-DD (so check-in on "today" shows as active, not upcoming). */
function getTodayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
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

/** Human-friendly countdown: "X days", "1 day", "Ends today", "Ended". */
function countdownLabel(endDateStr: string, todayStr: string): { label: string; sublabel?: string } {
  const days = daysLeft(endDateStr);
  if (days === 0) return { label: 'Ends today', sublabel: 'Check-out is today' };
  if (days === 1) return { label: '1 day left', sublabel: 'until check-out' };
  if (days > 0 && days <= 7) return { label: `${days} days left`, sublabel: 'until check-out' };
  if (days > 7) {
    const weeks = Math.floor(days / 7);
    const remainder = days % 7;
    if (remainder === 0) return { label: `${weeks} week${weeks !== 1 ? 's' : ''} left`, sublabel: `${days} days until check-out` };
    return { label: `${days} days left`, sublabel: `${weeks} week${weeks !== 1 ? 's' : ''} and ${remainder} day${remainder !== 1 ? 's' : ''} until check-out` };
  }
  return { label: 'Stay ended', sublabel: undefined };
}

type StayFilter = 'all' | 'active' | 'future' | 'previous' | 'future_invites';

function isAgreementArchive(s: GuestStayView): boolean {
  return s.record_kind === "agreement_archive";
}

function normGuestPropertyName(name: string): string {
  return name.trim().toLowerCase();
}

/** If both sides have a unit label, they must match; missing label on one side still matches (legacy rows). */
function guestStayUnitsCompatible(a: GuestStayView, b: GuestStayView): boolean {
  const ua = (a.unit_label ?? '').trim();
  const ub = (b.unit_label ?? '').trim();
  if (!ua || !ub) return true;
  return ua.toLowerCase() === ub.toLowerCase();
}

function archiveSupersededByRealStay(arch: GuestStayView, realCandidate: GuestStayView): boolean {
  if (!isAgreementArchive(arch) || isAgreementArchive(realCandidate)) return false;
  if (normGuestPropertyName(arch.property_name) !== normGuestPropertyName(realCandidate.property_name)) return false;
  if (!guestStayUnitsCompatible(arch, realCandidate)) return false;
  return datesOverlap(
    arch.approved_stay_start_date,
    arch.approved_stay_end_date,
    realCandidate.approved_stay_start_date,
    realCandidate.approved_stay_end_date,
  );
}

/** When the list row is a redundant archive, show the real stay in the detail panel instead. */
function resolveGuestDetailStay(row: GuestStayView | null, allStays: GuestStayView[]): GuestStayView | null {
  if (!row) return null;
  if (!isAgreementArchive(row)) return row;
  const superseder = allStays.find((s) => !isAgreementArchive(s) && archiveSupersededByRealStay(row, s));
  return superseder ?? row;
}

function preferredFirstInFilteredList(rows: GuestStayView[]): GuestStayView | undefined {
  if (!rows.length) return undefined;
  const firstReal = rows.find((s) => !isAgreementArchive(s));
  return firstReal ?? rows[0];
}

export const GuestDashboard: React.FC<{ user: UserSession; navigate: (v: string) => void; notify: (t: 'success' | 'error', m: string) => void }> = ({ user, navigate, notify }) => {
  const [stays, setStays] = useState<GuestStayView[]>([]);
  const [pendingInvites, setPendingInvites] = useState<GuestPendingInviteView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStay, setSelectedStay] = useState<GuestStayView | null>(null);
  const [activeTab, setActiveTab] = useState<GuestTab>('stays');
  const [stayFilter, setStayFilter] = useState<StayFilter>('all');
  const [endStayConfirm, setEndStayConfirm] = useState<GuestStayView | null>(null);
  const [endingStay, setEndingStay] = useState(false);
  const [cancelStayConfirm, setCancelStayConfirm] = useState<GuestStayView | null>(null);
  const [cancellingStay, setCancellingStay] = useState(false);
  const [extensionModalStay, setExtensionModalStay] = useState<GuestStayView | null>(null);
  const [extensionMessage, setExtensionMessage] = useState('');
  const [extensionSubmitting, setExtensionSubmitting] = useState(false);
  const [agreementModalCode, setAgreementModalCode] = useState<string | null>(null);
  const [inviteLinkInput, setInviteLinkInput] = useState('');
  const [addingInvite, setAddingInvite] = useState(false);
  const [agreementDownloading, setAgreementDownloading] = useState(false);
  const [showLiveLinkModal, setShowLiveLinkModal] = useState(false);
  const [liveLinkSlug, setLiveLinkSlug] = useState<string | null>(null);
  const [showVerifyQRModal, setShowVerifyQRModal] = useState(false);
  const [verifyQRInviteId, setVerifyQRInviteId] = useState<string | null>(null);
  const [copyToast, setCopyToast] = useState<string | null>(null);
  const [checkingInStay, setCheckingInStay] = useState<GuestStayView | null>(null);
  const [prefilledGuestInfoForModal, setPrefilledGuestInfoForModal] = useState<PrefilledGuestInfo | null>(null);
  const [pendingSignatureModalInvite, setPendingSignatureModalInvite] = useState<GuestPendingInviteView | null>(null);
  const [guestLogs, setGuestLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [guestLogsLoading, setGuestLogsLoading] = useState(false);
  const [guestLogsLoadedOnce, setGuestLogsLoadedOnce] = useState(false);
  const [guestLedgerLogs, setGuestLedgerLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [guestLedgerLoading, setGuestLedgerLoading] = useState(false);
  const [guestLedgerLoadedOnce, setGuestLedgerLoadedOnce] = useState(false);
  const [guestLedgerFromDate, setGuestLedgerFromDate] = useState('');
  const [guestLedgerToDate, setGuestLedgerToDate] = useState('');
  const [guestLedgerCategory, setGuestLedgerCategory] = useState('');
  const [guestLedgerSearch, setGuestLedgerSearch] = useState('');
  const [logMessageModalEntry, setLogMessageModalEntry] = useState<OwnerAuditLogEntry | null>(null);
  const [stayPresence, setStayPresence] = useState<'present' | 'away'>('present');
  const [stayPresenceAwayStartedAt, setStayPresenceAwayStartedAt] = useState<string | null>(null);
  const [stayPresenceGuestsAuthorized, setStayPresenceGuestsAuthorized] = useState(false);
  const [stayPresenceUpdating, setStayPresenceUpdating] = useState(false);
  const [stayShowAwayConfirm, setStayShowAwayConfirm] = useState(false);
  const [stayAwayGuestsAuthorized, setStayAwayGuestsAuthorized] = useState(false);
  /** Track accept-invite attempts that failed so we don't retry in a loop (same invite+signature). */
  const acceptFailedRef = useRef<Set<string>>(new Set());

  const openAgreementModal = useCallback((code: string) => {
    // Clear any stale Dropbox redirect state so we don't accept an invite from a previous attempt
    try {
      sessionStorage.removeItem(DROPBOX_REDIRECT_INVITATION_CODE);
      sessionStorage.removeItem(DROPBOX_REDIRECT_SIGNATURE_ID);
    } catch { /* ignore */ }
    dashboardApi.guestProfile()
      .then((profile) => {
        setPrefilledGuestInfoForModal({
          full_name: (profile?.full_legal_name || user?.user_name || '').trim(),
          email: (user?.email || '').trim(),
          phone: (user as { phone?: string })?.phone ?? '',
          permanent_address: (profile?.permanent_home_address || '').trim(),
        });
        setAgreementModalCode(code);
      })
      .catch(() => {
        setPrefilledGuestInfoForModal(null);
        setAgreementModalCode(code);
      });
  }, [user]);

  const loadData = useCallback((): Promise<[GuestStayView[], GuestPendingInviteView[]]> => {
    return Promise.all([
      dashboardApi.guestStays(),
      dashboardApi.guestPendingInvites().catch(() => []),
    ])
      .then(([staysData, pendingData]) => {
        const uniqueStays = [
          ...new Map(
            staysData.map((s) => [guestDashboardStayRowKey(s), s] as const)
          ).values(),
        ];
        const inviteCodesFromRealStays = new Set(
          uniqueStays
            .filter((s) => s.record_kind !== 'agreement_archive' && s.invite_id && String(s.invite_id).trim())
            .map((s) => String(s.invite_id).trim().toUpperCase()),
        );
        const realStays = uniqueStays.filter((s) => s.record_kind !== 'agreement_archive');
        const staysWithoutRedundantArchive = uniqueStays.filter((s) => {
          if (s.record_kind !== 'agreement_archive') return true;
          const code = (s.invite_id || '').trim().toUpperCase();
          if (code && inviteCodesFromRealStays.has(code)) return false;
          const superseded = realStays.some((r) => archiveSupersededByRealStay(s, r));
          if (superseded) return false;
          return true;
        });
        setStays(staysWithoutRedundantArchive);
        setPendingInvites(pendingData);
        return [staysWithoutRedundantArchive, pendingData] as [GuestStayView[], GuestPendingInviteView[]];
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? 'Failed to load data.';
        setError(msg);
        notify('error', msg);
        throw e;
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // When backend reports signature complete but not yet accepted (e.g. just fetched from Dropbox), accept so stay appears
  useEffect(() => {
    if (!pendingInvites.length) return;
    const toAccept = pendingInvites.filter(
      (inv): inv is GuestPendingInviteView & { accept_now_signature_id: number } => {
        const sid = (inv as GuestPendingInviteView).accept_now_signature_id;
        if (typeof sid !== 'number') return false;
        const key = `${inv.invitation_code}:${sid}`;
        if (acceptFailedRef.current.has(key)) return false; // already tried and failed, don't retry
        return true;
      }
    );
    if (toAccept.length === 0) return;
    Promise.all(
      toAccept.map((inv) => authApi.acceptInvite(inv.invitation_code, inv.accept_now_signature_id))
    ).then(async () => {
      try {
        const [staysData] = await loadData();
        const firstInv = toAccept[0];
        const newStay = staysData.find(
          (s) =>
            s.approved_stay_start_date === firstInv.stay_start_date &&
            s.approved_stay_end_date === firstInv.stay_end_date &&
            s.property_name === firstInv.property_name
        );
        if (newStay) {
          setSelectedStay(newStay);
          setStayFilter('all');
        }
        notify('success', 'Your stay is confirmed. It will appear in your current or upcoming stays.');
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      } catch {
        loadData();
        notify('success', 'Your stay is confirmed. It will appear in your current or upcoming stays.');
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      }
    }).catch((e) => {
      toAccept.forEach((inv) => acceptFailedRef.current.add(`${inv.invitation_code}:${inv.accept_now_signature_id}`));
      notify('error', (e as Error)?.message ?? 'Could not confirm your stay.');
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    });
  }, [pendingInvites, loadData, notify]);

  // After redirect back from Dropbox: poll signature until completed, then accept invite so stay shows in current/upcoming
  useEffect(() => {
    const code = sessionStorage.getItem(DROPBOX_REDIRECT_INVITATION_CODE);
    const sigIdStr = sessionStorage.getItem(DROPBOX_REDIRECT_SIGNATURE_ID);
    if (!code || !sigIdStr) return;
    const sigId = parseInt(sigIdStr, 10);
    if (!Number.isFinite(sigId)) {
      sessionStorage.removeItem(DROPBOX_REDIRECT_INVITATION_CODE);
      sessionStorage.removeItem(DROPBOX_REDIRECT_SIGNATURE_ID);
      return;
    }
    const POLL_INTERVAL_MS = 3000;
    const MAX_POLLS = 40; // ~2 min
    let pollCount = 0;
    const t = setInterval(() => {
      pollCount += 1;
      agreementsApi.getSignatureStatus(sigId).then((res) => {
        if (res.completed) {
          clearInterval(t);
          sessionStorage.removeItem(DROPBOX_REDIRECT_INVITATION_CODE);
          sessionStorage.removeItem(DROPBOX_REDIRECT_SIGNATURE_ID);
          authApi.acceptInvite(code, sigId).then(async () => {
            try {
              const [staysData] = await loadData();
              const newStay = staysData.find((s) => s.invite_id === code);
              if (newStay) {
                setSelectedStay(newStay);
                setStayFilter('all');
              }
              notify('success', 'Your stay is confirmed. It will appear in your current or upcoming stays.');
              window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
            } catch {
              loadData();
              notify('success', 'Your stay is confirmed. It will appear in your current or upcoming stays.');
              window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
            }
          }).catch((e) => {
            notify('error', (e as Error)?.message ?? 'Could not confirm your stay.');
          });
        }
      }).catch(() => {});

      if (pollCount >= MAX_POLLS) {
        clearInterval(t);
        sessionStorage.removeItem(DROPBOX_REDIRECT_INVITATION_CODE);
        sessionStorage.removeItem(DROPBOX_REDIRECT_SIGNATURE_ID);
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [loadData, notify]);

  // When user returns to the tab (e.g. after signing in Dropbox in another tab), refetch so backend can re-check Dropbox and we accept/create stay
  useEffect(() => {
    const hasPendingDropbox = () => pendingInvites.some((inv) => inv.needs_dropbox_signature);
    if (!hasPendingDropbox()) return;
    const onFocus = () => loadData();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [pendingInvites, loadData]);

  // Delayed refetch when there are pending Dropbox invites: backend may not have signed PDF on first load (Dropbox delay). Refetch after 5s so stay can appear after signing.
  useEffect(() => {
    const hasPendingDropbox = pendingInvites.some((inv) => inv.needs_dropbox_signature);
    if (!hasPendingDropbox) return;
    const t = setTimeout(() => loadData(), 5000);
    return () => clearTimeout(t);
  }, [pendingInvites, loadData]);

  // When "Complete signing" modal is open: poll signature status; when completed, accept invite so stay appears and close modal
  useEffect(() => {
    const inv = pendingSignatureModalInvite;
    const sigId = inv?.pending_signature_id;
    if (!inv || sigId == null || typeof sigId !== 'number') return;
    const POLL_MS = 3000;
    const MAX_POLLS = 80; // ~4 min
    let count = 0;
    const t = setInterval(() => {
      count += 1;
      agreementsApi.getSignatureStatus(sigId).then((res) => {
        if (res.completed) {
          clearInterval(t);
          authApi.acceptInvite(inv.invitation_code, sigId).then(async () => {
            setPendingSignatureModalInvite(null);
            try {
              const [staysData] = await loadData();
              const newStay = staysData.find(
                (s) =>
                  s.approved_stay_start_date === inv.stay_start_date &&
                  s.approved_stay_end_date === inv.stay_end_date &&
                  s.property_name === inv.property_name
              );
              if (newStay) {
                setSelectedStay(newStay);
                setStayFilter('all');
              }
              notify('success', 'Your stay is confirmed. It will appear in your current or upcoming stays.');
              window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
            } catch {
              notify('error', 'Could not load your stay. Please refresh the page.');
              loadData();
              window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
            }
          }).catch((e) => {
            notify('error', (e as Error)?.message ?? 'Could not confirm your stay.');
            loadData();
            window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
          });
        }
      }).catch(() => {});
      if (count >= MAX_POLLS) clearInterval(t);
    }, POLL_MS);
    return () => clearInterval(t);
  }, [pendingSignatureModalInvite, loadData, notify]);

  useEffect(() => {
    const code = sessionStorage.getItem(PENDING_INVITE_STORAGE_KEY);
    if (!code) return;
    sessionStorage.removeItem(PENDING_INVITE_STORAGE_KEY);
    dashboardApi.guestAddPendingInvite(code)
      .then(() => {
        loadData();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
        openAgreementModal(code);
      })
      .catch((e) => {
        loadData();
        notify('error', (e as Error)?.message ?? 'Invalid or expired invitation.');
      });
  }, [loadData, notify, openAgreementModal]);

  const isActiveCheckedInStay = (s: GuestStayView | null) =>
    !!s &&
    !isAgreementArchive(s) &&
    !!s.stay_id &&
    isGuestStayPhysicallyCheckedIn(s) &&
    !s.checked_out_at &&
    !s.cancelled_at &&
    !s.revoked_at;

  useEffect(() => {
    if (!selectedStay || !isActiveCheckedInStay(selectedStay)) {
      setStayPresence('present');
      setStayPresenceAwayStartedAt(null);
      setStayPresenceGuestsAuthorized(false);
      setStayShowAwayConfirm(false);
      return;
    }
    dashboardApi.getStayPresence(selectedStay.stay_id).then((p) => {
      setStayPresence((p.status as 'present' | 'away') || 'present');
      setStayPresenceAwayStartedAt(p.away_started_at || null);
      setStayPresenceGuestsAuthorized(p.guests_authorized_during_away ?? false);
    }).catch(() => {});
  }, [
    selectedStay?.stay_id,
    selectedStay?.checked_in_at,
    selectedStay?.checked_out_at,
    selectedStay?.cancelled_at,
    selectedStay?.revoked_at,
    selectedStay?.stay_status,
  ]);

  const doSetStayPresence = useCallback(async (status: 'present' | 'away', guestsAuthorized?: boolean) => {
    if (!selectedStay || !isActiveCheckedInStay(selectedStay)) return;
    setStayPresenceUpdating(true);
    setStayShowAwayConfirm(false);
    try {
      const res = await dashboardApi.setStayPresence(selectedStay.stay_id, status, guestsAuthorized);
      setStayPresence((res.presence as 'present' | 'away') || status);
      setStayPresenceAwayStartedAt(res.away_started_at ?? null);
      setStayPresenceGuestsAuthorized(res.guests_authorized_during_away ?? false);
      notify('success', `Status set to ${status}`);
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to update status');
    } finally {
      setStayPresenceUpdating(false);
    }
  }, [selectedStay, notify]);

  const handleStayPresenceToggle = useCallback(() => {
    if (!selectedStay || !isActiveCheckedInStay(selectedStay)) return;
    if (stayPresence === 'present') {
      setStayShowAwayConfirm(true);
      setStayAwayGuestsAuthorized(false);
      return;
    }
    doSetStayPresence('present');
  }, [selectedStay, stayPresence, doSetStayPresence]);

  const handleAgreementSigned = useCallback(async (signatureId: number) => {
    if (!agreementModalCode) return;
    try {
      await authApi.acceptInvite(agreementModalCode, signatureId);
      notify('success', 'Invitation accepted. Your stay is confirmed.');
      setAgreementModalCode(null);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not accept invitation.');
    }
  }, [agreementModalCode, loadData, notify]);

  const handleEndStay = useCallback(async () => {
    if (!endStayConfirm) return;
    setEndingStay(true);
    try {
      await dashboardApi.guestEndStay(endStayConfirm.stay_id);
      notify('success', 'Checkout complete. Your stay has ended and status has been updated.');
      setEndStayConfirm(null);
      setSelectedStay(null);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not end stay.');
    } finally {
      setEndingStay(false);
    }
  }, [endStayConfirm, loadData, notify]);

  const handleCancelStay = useCallback(async () => {
    if (!cancelStayConfirm) return;
    setCancellingStay(true);
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
      setCancellingStay(false);
    }
  }, [cancelStayConfirm, loadData, notify]);

  const handleExtensionRequest = useCallback(async () => {
    if (!extensionModalStay) return;
    setExtensionSubmitting(true);
    try {
      const msg = extensionMessage.trim();
      await dashboardApi.guestRequestStayExtension(
        extensionModalStay.stay_id,
        msg ? { message: msg } : {},
      );
      notify('success', 'Your host has been notified.');
      setExtensionModalStay(null);
      setExtensionMessage('');
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not send request.');
    } finally {
      setExtensionSubmitting(false);
    }
  }, [extensionModalStay, extensionMessage, notify]);

  const handleCheckIn = useCallback(async (s: GuestStayView) => {
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

  const loadGuestLogs = useCallback((stayId?: number) => {
    setGuestLogsLoading(true);
    dashboardApi.guestLogs(stayId != null ? { stay_id: stayId } : undefined)
      .then(setGuestLogs)
      .catch(() => setGuestLogs([]))
      .finally(() => {
        setGuestLogsLoading(false);
        setGuestLogsLoadedOnce(true);
      });
  }, []);

  const loadGuestLedger = useCallback(() => {
    setGuestLedgerLoading(true);
    const from_ts = guestLedgerFromDate ? localDateInputToUtcStartIso(guestLedgerFromDate) : undefined;
    const to_ts = guestLedgerToDate ? localDateInputToUtcEndIso(guestLedgerToDate) : undefined;
    dashboardApi
      .guestLogs({
        from_ts,
        to_ts,
        category: guestLedgerCategory.trim() || undefined,
        search: guestLedgerSearch.trim() || undefined,
      })
      .then(setGuestLedgerLogs)
      .catch(() => setGuestLedgerLogs([]))
      .finally(() => {
        setGuestLedgerLoading(false);
        setGuestLedgerLoadedOnce(true);
      });
  }, [guestLedgerFromDate, guestLedgerToDate, guestLedgerCategory, guestLedgerSearch]);

  useEffect(() => {
    if (activeTab === 'ledger') loadGuestLedger();
  }, [activeTab, loadGuestLedger]);

  const fetchSignedAgreementPdf = useCallback(async (s: GuestStayView) => {
    if (isAgreementArchive(s) && s.agreement_signature_id != null) {
      return dashboardApi.guestAgreementSignedPdfBlob(s.agreement_signature_id);
    }
    if (!s.stay_id) throw new Error("No signed agreement available for this record.");
    return dashboardApi.guestStaySignedAgreementBlob(s.stay_id);
  }, []);

  const handleAddInviteLink = useCallback(() => {
    const code = parseInviteCode(inviteLinkInput);
    if (!code) {
      notify('error', 'Please enter a valid invitation link or code.');
      return;
    }
    setAddingInvite(true);
    dashboardApi.guestAddPendingInvite(code)
      .then(() => {
        setInviteLinkInput('');
        loadData();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
        openAgreementModal(code);
        notify('success', 'Invitation added. Review and sign the agreement below.');
      })
      .catch((e) => {
        notify('error', (e as Error)?.message ?? 'Invalid or expired invitation. Please check the link.');
      })
      .finally(() => setAddingInvite(false));
  }, [inviteLinkInput, loadData, notify, openAgreementModal]);

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
          <Button variant="primary" className="rounded-lg font-medium" onClick={() => { setError(null); loadData(); }}>Try again</Button>
        </div>
      </div>
    );
  }
  const isEmpty = stays.length === 0 && pendingInvites.length === 0;
  const today = getTodayStr();

  const openGuestStays = filterOpenGuestFacingStays(stays);
  const activeStays = openGuestStays.filter((s) => {
    const inWindow =
      s.approved_stay_start_date <= today && s.approved_stay_end_date >= today;
    const overstaying =
      isGuestStayPhysicallyCheckedIn(s) && s.approved_stay_end_date < today;
    return inWindow || overstaying;
  });
  const futureStays = openGuestStays.filter((s) => s.approved_stay_start_date > today);
  const completedStays = guestFacingCompletedStays(stays, openGuestStays);

  const filteredStays: GuestStayView[] =
    stayFilter === 'all'
      ? stays
      : stayFilter === 'active'
        ? activeStays
        : stayFilter === 'future'
          ? futureStays
          : stayFilter === 'previous'
            ? completedStays
            : [];

  const futureInvites = pendingInvites.filter((inv) =>
    !stays.some((s) => datesOverlap(inv.stay_start_date, inv.stay_end_date, s.approved_stay_start_date, s.approved_stay_end_date))
  );

  const guestEmail = user?.email ?? '';
  const guestFullName = user?.user_name ?? '';
  const listRowForDetail =
    selectedStay ?? (stayFilter === 'future_invites' ? null : preferredFirstInFilteredList(filteredStays) ?? null);
  const stay = resolveGuestDetailStay(listRowForDetail, stays);
  const dLeft = stay ? daysLeft(stay.approved_stay_end_date) : 0;
  const totalDays = stay ? Math.max(1, Math.ceil((new Date(stay.approved_stay_end_date).getTime() - new Date(stay.approved_stay_start_date).getTime()) / (1000 * 60 * 60 * 24))) : 1;
  const elapsedDays = Math.max(0, totalDays - dLeft);
  const progressPercent = stay ? Math.min(100, (elapsedDays / totalDays) * 100) : 0;

  const filterButtons: { id: StayFilter; label: string; count: number }[] = [
    { id: 'all', label: 'All stays', count: stays.length },
    { id: 'active', label: 'Active stay', count: activeStays.length },
    { id: 'future', label: 'Future stay', count: futureStays.length },
    { id: 'previous', label: 'Completed', count: completedStays.length },
    { id: 'future_invites', label: 'Future invites', count: futureInvites.length },
  ];

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-[#f0f4ff]/50">
      {/* Sidebar */}
      <aside className="hidden lg:flex w-64 min-w-[16rem] flex-shrink-0 flex-col bg-white/80 backdrop-blur-xl border-r border-slate-200 p-5">
        <nav className="space-y-1">
          {[
            { id: 'stays' as GuestTab, label: 'My stays', icon: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
            { id: 'invitations' as GuestTab, label: 'Add invitation', icon: 'M12 6v6m0 0v6m0-6h6m-6 0H6' },
            { id: 'ledger' as GuestTab, label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
            { id: 'help' as GuestTab, label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
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
        {/* Mobile tab selector */}
        <div className="lg:hidden mb-4">
          <select
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value as GuestTab)}
            className="w-full max-w-xs rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm"
          >
            <option value="stays">My stays</option>
            <option value="invitations">Add invitation</option>
            <option value="ledger">Event ledger</option>
            <option value="help">Help Center</option>
          </select>
        </div>

        {activeTab !== 'help' && <DashboardAlertsPanel role="guest" className="mb-6" limit={50} />}

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
                    placeholder="Paste link or code (e.g. INV-XXXX)"
                  />
                </div>
                <Button
                  type="button"
                  className="shrink-0 self-stretch sm:self-auto sm:mt-7 h-10 px-5 rounded-lg font-medium text-white border-0 bg-[#6B90F2] hover:bg-[#5a7ed9]"
                  onClick={handleAddInviteLink}
                  disabled={addingInvite || !parseInviteCode(inviteLinkInput)}
                >
                  {addingInvite ? 'Adding…' : 'View & sign'}
                </Button>
              </div>
            </div>
            {pendingInvites.filter((inv) => inv.needs_dropbox_signature).length > 0 && (
              <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-6 shadow-sm">
                <h2 className="text-base font-semibold text-slate-900 mb-1">Pending actions</h2>
                <p className="text-sm text-slate-600 mb-2">Complete signing in Dropbox to confirm these stays.</p>
                <p className="text-sm text-slate-500 mb-4">
                  Already signed? <button type="button" onClick={() => loadData()} className="text-blue-600 hover:text-blue-800 font-medium underline">Check again</button>
                </p>
                <ul className="space-y-3">
                  {pendingInvites.filter((inv) => inv.needs_dropbox_signature).map((inv) => (
                    <li key={inv.invitation_code} className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl border border-amber-100 bg-white">
                      <div className="min-w-0 flex-1">
                        {inv.property_deleted_at ? <InactivePropertyBanner role="guest" compact className="text-left mb-3" /> : null}
                        <p className="font-semibold text-slate-900">{inv.property_name}{inv.unit_label ? ` — Unit ${inv.unit_label}` : ''}</p>
                        <p className="text-sm text-slate-500 mt-0.5">{formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}</p>
                        <p className="text-xs text-amber-700 font-medium mt-1">Awaiting your signature in Dropbox</p>
                      </div>
                      <Button variant="primary" className="shrink-0 h-10 rounded-lg font-medium px-4" onClick={() => setPendingSignatureModalInvite(inv)}>Complete signing</Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {pendingInvites.filter((inv) =>
              stays.some((s) => datesOverlap(inv.stay_start_date, inv.stay_end_date, s.approved_stay_start_date, s.approved_stay_end_date))
            ).length > 0 && (
              <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-6 shadow-sm">
                <h2 className="text-base font-semibold text-slate-900 mb-1">Overlapping invitations</h2>
                <p className="text-sm text-slate-600 mb-4">These overlap with an accepted stay and cannot be accepted.</p>
                <ul className="space-y-3">
                  {pendingInvites
                    .filter((inv) =>
                      stays.some((s) => datesOverlap(inv.stay_start_date, inv.stay_end_date, s.approved_stay_start_date, s.approved_stay_end_date))
                    )
                    .map((inv) => (
                      <li key={inv.invitation_code} className="flex flex-wrap items-center justify-between gap-4 p-4 bg-white rounded-xl border border-amber-100">
                        <div className="min-w-0 flex-1">
                          {inv.property_deleted_at ? <InactivePropertyBanner role="guest" compact className="text-left mb-3" /> : null}
                          <p className="font-semibold text-slate-900">{inv.property_name}{inv.unit_label ? ` — Unit ${inv.unit_label}` : ''}</p>
                          <p className="text-sm text-slate-500 mt-0.5">{formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}</p>
                          <p className="text-xs text-amber-700 font-medium mt-1">Overlaps existing stay</p>
                        </div>
                        <span className="text-sm font-medium text-slate-400 shrink-0">Cannot accept</span>
                      </li>
                    ))}
                </ul>
              </div>
            )}
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-base font-semibold text-slate-900 mb-1">Future invites</h2>
              <p className="text-sm text-slate-500 mb-4">Invitations that don&apos;t overlap your existing stays. Sign the agreement to accept.</p>
              {futureInvites.length === 0 ? (
                <p className="text-slate-500 text-sm">No future invites. Add an invitation link above.</p>
              ) : (
                <ul className="space-y-3">
                  {futureInvites.map((inv) => (
                    <li key={inv.invitation_code} className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl border border-slate-200 bg-slate-50/50">
                      <div className="min-w-0 flex-1">
                        {inv.property_deleted_at ? <InactivePropertyBanner role="guest" compact className="text-left mb-3" /> : null}
                        <p className="font-semibold text-slate-900">{inv.property_name}{inv.unit_label ? ` — Unit ${inv.unit_label}` : ''}</p>
                        <p className="text-sm text-slate-500 mt-0.5">{formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}</p>
                      </div>
                      <Button variant="primary" className="shrink-0 h-10 rounded-lg font-medium px-4" onClick={() => (inv.needs_dropbox_signature ? setPendingSignatureModalInvite(inv) : openAgreementModal(inv.invitation_code))}>
                        {inv.needs_dropbox_signature ? 'Complete signing' : 'Review & sign'}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {/* Event ledger tab (same table/layout as tenant Event ledger) */}
        {activeTab === 'ledger' && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900 mb-2">Event ledger</h2>
            <p className="text-sm text-slate-500 mb-4">
              Your authorization timeline: invitation created, accepted, active, revoked, expired, signatures, check-in/out, and related events. Only your stays and invitations are visible here.
            </p>
            <div className="flex flex-wrap gap-3 items-center mb-4">
              <input
                type="date"
                value={guestLedgerFromDate}
                onChange={(e) => setGuestLedgerFromDate(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                type="date"
                value={guestLedgerToDate}
                onChange={(e) => setGuestLedgerToDate(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <select
                value={guestLedgerCategory}
                onChange={(e) => setGuestLedgerCategory(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm min-w-[10rem]"
              >
                <option value="">All categories</option>
                <option value="status_change">Status change</option>
                <option value="presence">Presence / Away</option>
                <option value="guest_signature">Guest signature</option>
                <option value="billing">Billing</option>
              </select>
              <input
                type="text"
                placeholder="Search…"
                value={guestLedgerSearch}
                onChange={(e) => setGuestLedgerSearch(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm w-40"
              />
              <Button variant="outline" onClick={loadGuestLedger} disabled={guestLedgerLoading}>
                {guestLedgerLoading ? 'Loading…' : 'Apply filters'}
              </Button>
            </div>
            {guestLedgerLoading && guestLedgerLogs.length === 0 ? (
              <p className="p-6 text-slate-500 text-center text-sm">Loading…</p>
            ) : guestLedgerLoadedOnce && guestLedgerLogs.length === 0 ? (
              <p className="p-6 text-slate-500 text-center text-sm">No events.</p>
            ) : guestLedgerLogs.length > 0 ? (
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
                    {guestLedgerLogs.map((entry) => (
                      <tr key={entry.id} className="hover:bg-slate-50">
                        <td className="px-4 py-2 text-slate-600 text-sm whitespace-nowrap">
                          {formatLedgerTimestamp(entry.created_at)}
                        </td>
                        <td className="px-4 py-2">
                          <span
                            className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                              entry.category === 'failed_attempt'
                                ? 'bg-red-100 text-red-800'
                                : entry.category === 'guest_signature'
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : entry.category === 'shield_mode'
                                    ? 'bg-violet-100 text-violet-800'
                                    : entry.category === 'dead_mans_switch'
                                      ? 'bg-amber-100 text-amber-800'
                                      : entry.category === 'billing'
                                        ? 'bg-slate-200 text-slate-800'
                                        : entry.category === 'presence'
                                          ? 'bg-teal-100 text-teal-800'
                                          : 'bg-sky-100 text-sky-800'
                            }`}
                          >
                            {entry.category === 'shield_mode'
                              ? 'Shield Mode'
                              : entry.category === 'dead_mans_switch'
                                ? 'Stay end reminders'
                                : entry.category === 'billing'
                                  ? 'Billing'
                                  : entry.category === 'presence'
                                    ? 'Presence'
                                    : entry.category.replace('_', ' ')}
                          </span>
                        </td>
                        <td className="px-4 py-2 font-medium text-slate-800 text-sm">{entry.title}</td>
                        <td className="px-4 py-2 text-slate-600 text-sm">{entry.actor_email ?? '—'}</td>
                        <td className="px-4 py-2 text-slate-600 text-sm max-w-xs">
                          <span className="truncate block">{scrubAuditLogStateChangeParagraph(entry.message)}</span>
                          <button
                            type="button"
                            onClick={() => setLogMessageModalEntry(entry)}
                            className="text-sky-600 hover:text-sky-800 text-xs mt-0.5 focus:outline-none focus:underline"
                          >
                            View full message
                          </button>
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
          {/* Filters + Stay list */}
          <div className="lg:w-80 xl:w-96 flex-shrink-0 space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">Filter</h3>
              <div className="flex flex-wrap gap-2">
                {filterButtons.map(({ id, label, count }) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => { setStayFilter(id); if (id !== 'future_invites') setSelectedStay(null); }}
                    className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      stayFilter === id ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
                    }`}
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
                        {inv.property_deleted_at ? <InactivePropertyBanner role="guest" compact className="text-left mb-2" /> : null}
                        <p className="font-semibold text-slate-900 text-sm">{inv.property_name}{inv.unit_label ? ` — Unit ${inv.unit_label}` : ''}</p>
                        <p className="text-xs text-slate-500 mt-0.5">{formatCalendarDate(inv.stay_start_date)} – {formatCalendarDate(inv.stay_end_date)}</p>
                        <Button variant="primary" className="mt-2 w-full text-xs h-8 py-1.5" onClick={() => (inv.needs_dropbox_signature ? setPendingSignatureModalInvite(inv) : openAgreementModal(inv.invitation_code))}>
                          {inv.needs_dropbox_signature ? 'Complete signing' : 'Review & sign'}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )
              ) : filteredStays.length === 0 ? (
                <p className="text-slate-600 text-sm py-4">
                  {stayFilter === 'all' ? 'No stays yet.' : stayFilter === 'previous' ? 'No completed stays.' : `No ${stayFilter} stays.`} Add an invitation link in the Add invitation tab.
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                    {filteredStays.map((s) => {
                      const isArch = isAgreementArchive(s);
                      const inWindow =
                        s.approved_stay_start_date <= today && s.approved_stay_end_date >= today;
                      const isFutureCal = s.approved_stay_start_date > today;
                      const checkedIn = isGuestStayPhysicallyCheckedIn(s);
                      const canCheckIn =
                        !isArch &&
                        inWindow &&
                        !checkedIn &&
                        !s.checked_out_at &&
                        !s.cancelled_at &&
                        !s.revoked_at;
                      const canCheckout =
                        !isArch &&
                        (checkedIn || s.revoked_at != null) &&
                        !s.checked_out_at &&
                        !s.cancelled_at;
                      const canCancel = !isArch && isFutureCal && !s.cancelled_at && !s.checked_out_at;
                      const rowDisplay = !isArch ? guestStayRowDisplayForGuestView(s) : null;
                      const isSelected = !!(
                        selectedStay &&
                        guestDashboardStayRowKey(selectedStay) === guestDashboardStayRowKey(s)
                      );
                      return (
                      <div
                        key={guestDashboardStayRowKey(s)}
                        className={`rounded-xl border bg-white text-left transition-all ${
                          isSelected
                            ? 'border-slate-300 border-l-4 border-l-[#6B90F2] bg-[#6B90F2]/10 shadow-sm'
                            : 'border-slate-200 hover:border-slate-300'
                        }`}
                      >
                          <button
                            type="button"
                            onClick={() => setSelectedStay(isSelected ? null : s)}
                            className="w-full text-left p-4"
                          >
                            {s.property_deleted_at ? <InactivePropertyBanner role="guest" compact className="text-left mb-3" /> : null}
                            <div className="flex items-center gap-2 mb-2 flex-wrap">
                              {isArch ? (
                                <span className="px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide bg-amber-50 text-amber-900 border border-amber-200">
                                  Agreement record
                                </span>
                              ) : rowDisplay ? (
                              <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide ${GUEST_STAY_INLINE_BADGE_CLASS[rowDisplay.tone]}`}>
                                {rowDisplay.statusLabel}
                              </span>
                              ) : null}
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
                                onClick={(e) => { e.stopPropagation(); handleCheckIn(s); }}
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
                          {s.can_request_extension && (
                            <div className="px-4 pb-4 pt-0">
                              <button
                                type="button"
                                className="w-full py-2 px-4 rounded-lg text-sm font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setExtensionModalStay(s);
                                  setExtensionMessage('');
                                }}
                              >
                                Request extension from host
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
                </div>
              )}
              </div>
            </div>
          </div>

          {/* Stay detail panel - show placeholder when no stay selected */}
          {!stay && stayFilter !== 'future_invites' && (
            <div className="flex-1 min-w-0 flex items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50/50 p-12">
              <p className="text-slate-500 text-sm text-center">Select a stay from the list to view details and actions.</p>
            </div>
          )}
          {stay && stayFilter !== 'future_invites' && (() => {
        const detailCheckedIn = isGuestStayPhysicallyCheckedIn(stay);
        const detailRow = !isAgreementArchive(stay) ? guestStayRowDisplayForGuestView(stay) : null;
        return (
        <div className="flex-1 min-w-0 space-y-6 overflow-y-auto">
      {/* Revoked: Authorization Revoked per guidance */}
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

      {isAgreementArchive(stay) && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-5">
          <p className="text-sm text-amber-900 font-medium">The invitation window ended before this stay was fully confirmed in the app.</p>
          <p className="text-sm text-amber-800 mt-1">Your signed agreement and planned dates stay on file below — you can open or download the PDF at any time.</p>
        </div>
      )}

      {/* Hero: Stay overview */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-8 shadow-sm">
            <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-8">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-4 flex-wrap">
              {isAgreementArchive(stay) ? (
                <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-semibold uppercase tracking-wide bg-amber-50 text-amber-900 border border-amber-200">
                  Agreement record
                </span>
              ) : detailRow ? (
              <span className={`inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-semibold uppercase tracking-wide ${GUEST_STAY_INLINE_BADGE_CLASS[detailRow.tone]}`}>
                {detailRow.statusLabel}
              </span>
              ) : null}
              <span className="text-slate-400">·</span>
              <span className="text-slate-500 text-sm">{stay.property_name}{stay.unit_label ? ` — Unit ${stay.unit_label}` : ''}</span>
              <span className="text-slate-400 text-sm">({stay.region_code})</span>
              {stay.invite_id && (
                <>
                  <span className="text-slate-400">·</span>
                  <span className="text-slate-500 text-sm font-mono">Invite ID: {stay.invite_id}</span>
                  {stay.token_state &&
                    stay.token_state !== 'BURNED' &&
                    stay.token_state !== 'STAGED' && (
                    <span className={`ml-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                      stay.token_state === 'EXPIRED' ? 'bg-slate-100 text-slate-600' :
                      stay.token_state === 'REVOKED' ? 'bg-amber-50 text-amber-700' :
                      'bg-slate-100 text-slate-600'
                    }`}>
                      {stay.token_state === 'EXPIRED' ? 'Expired' : stay.token_state === 'REVOKED' ? 'Revoked' : stay.token_state}
                    </span>
                  )}
                </>
              )}
            </div>
            <h1 className="text-2xl md:text-3xl font-bold text-slate-900 tracking-tight">
              {isAgreementArchive(stay)
                ? 'Signed agreement on file'
                : stay.cancelled_at
                  ? 'Stay cancelled'
                  : stay.checked_out_at
                    ? 'Stay completed'
                    : detailCheckedIn && !stay.checked_out_at && !stay.cancelled_at
                      ? 'Current stay'
                      : stay.approved_stay_end_date < today
                        ? 'Stay ended'
                        : stay.approved_stay_start_date > today
                          ? (() => {
                              const host =
                                (stay.residence_assigned_by_name && stay.residence_assigned_by_name.trim()) ||
                                'your host';
                              const accepted =
                                (stay.stay_accepted_by_name && stay.stay_accepted_by_name.trim()) ||
                                guestFullName.trim() ||
                                (guestEmail || '').trim() ||
                                'Guest';
                              return `Assigned residence by ${host} and accepted by ${accepted}`;
                            })()
                          : 'Current stay'}
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
            {!isAgreementArchive(stay) && (
              <>
            <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-slate-800 rounded-full transition-all duration-500" style={{ width: `${progressPercent}%` }} />
            </div>
            <p className="text-xs text-slate-400 font-medium">Stay progress</p>
              </>
            )}
            {isAgreementArchive(stay) && (
              <p className="text-xs text-slate-500 leading-relaxed">This row is a permanent record. Check-in and live verification apply once a stay is confirmed.</p>
            )}
            {!isAgreementArchive(stay) && stay.property_live_slug && (
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
                View owner authorization (PDF)
              </Button>
            )}
            {!isAgreementArchive(stay) && stay.invite_id && (
              <Button
                type="button"
                variant="outline"
                className="w-full h-11 rounded-lg font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-50"
                onClick={() => { setVerifyQRInviteId(stay.invite_id != null ? String(stay.invite_id) : null); setShowVerifyQRModal(true); }}
              >
                Verify with QR code
              </Button>
            )}
            {!isAgreementArchive(stay) && !stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && stay.approved_stay_start_date <= today && !detailCheckedIn && (
              <button
                type="button"
                disabled={!!checkingInStay}
                className="w-full h-11 rounded-lg font-medium text-white bg-[#6F42C1] hover:bg-[#5e35a8] disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
                onClick={() => handleCheckIn(stay)}
              >
                {checkingInStay?.stay_id === stay.stay_id ? 'Checking in…' : 'Check in'}
              </button>
            )}
            {!isAgreementArchive(stay) && !stay.checked_out_at && !stay.cancelled_at && (detailCheckedIn || stay.revoked_at != null) && (
              <button
                type="button"
                className="w-full h-11 rounded-lg font-medium text-white bg-emerald-600 hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2"
                onClick={() => setEndStayConfirm(stay)}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                Complete checkout
              </button>
            )}
            {!isAgreementArchive(stay) && !stay.cancelled_at && stay.approved_stay_start_date > today && (
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

      {/* Countdown & calendar: time left in a pretty view (only when stay is current or upcoming and not ended) */}
      {stay && !isAgreementArchive(stay) && !stay.checked_out_at && !stay.cancelled_at && stay.approved_stay_end_date >= today && (() => {
        const allDays = dateRange(stay.approved_stay_start_date, stay.approved_stay_end_date);
        const total = allDays.length;
        const maxShow = 42; // ~6 weeks
        const showDays = total <= maxShow ? allDays : allDays.slice(-maxShow);
        return (
          <section className="rounded-2xl border border-slate-200 bg-white p-6 md:p-8 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700 mb-4">TIME LEFT ON YOUR STAY</h3>
            <div className="flex flex-col sm:flex-row sm:items-center gap-8">
              <div className="flex-shrink-0">
                <div className="inline-flex flex-col items-center justify-center rounded-2xl bg-white border border-slate-200 shadow-inner px-8 py-6 min-w-[140px]">
                  <span className="text-4xl md:text-5xl font-bold tabular-nums text-slate-900">
                    {dLeft}
                  </span>
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-600 mt-1">
                    {dLeft === 0 ? 'DAY (CHECK-OUT TODAY)' : dLeft === 1 ? 'DAY LEFT' : 'DAYS LEFT'}
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
                <div className="flex flex-wrap gap-4 mt-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-[#6F42C1]" /> Today
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-[#FFC107]" /> Check-out day
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-slate-200" /> Past
                  </span>
                </div>
              </div>
            </div>
          </section>
        );
      })()}

      {/* Authorization status */}
      <section className={`rounded-2xl border p-6 shadow-sm ${
        stay.token_state === 'BURNED' ? 'border-emerald-200 bg-emerald-50/50' :
        stay.token_state === 'REVOKED' ? 'border-red-200 bg-red-50/50' :
        stay.token_state === 'EXPIRED' ? 'border-slate-200 bg-slate-50/50' :
        stay.token_state === 'CANCELLED' ? 'border-amber-200 bg-amber-50/50' :
        'border-slate-200 bg-white'
      }`}>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700 mb-3">AUTHORIZATION STATUS</h3>
        <div className="flex items-center gap-4">
          <span className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold ${
            stay.token_state === 'BURNED' ? 'bg-emerald-100 text-emerald-800' :
            stay.token_state === 'REVOKED' ? 'bg-red-100 text-red-800' :
            stay.token_state === 'EXPIRED' ? 'bg-slate-200 text-slate-700' :
            stay.token_state === 'CANCELLED' ? 'bg-amber-100 text-amber-800' :
            stay.token_state === 'STAGED' ? 'bg-blue-100 text-blue-800' :
            'bg-slate-200 text-slate-700'
          }`}>
            <span className={`w-2.5 h-2.5 rounded-full ${
              stay.token_state === 'BURNED' ? 'bg-emerald-500' :
              stay.token_state === 'REVOKED' ? 'bg-red-500' :
              stay.token_state === 'EXPIRED' ? 'bg-slate-400' :
              stay.token_state === 'CANCELLED' ? 'bg-amber-500' :
              stay.token_state === 'STAGED' ? 'bg-blue-500' :
              'bg-slate-400'
            }`} />
            {stay.token_state === 'BURNED' ? 'Invitation confirmed' :
             stay.token_state === 'REVOKED' ? 'Revoked' :
             stay.token_state === 'EXPIRED' ? 'Expired' :
             stay.token_state === 'CANCELLED' ? 'Cancelled' :
             stay.token_state === 'STAGED' ? 'Pending' :
             stay.token_state ?? 'Unknown'}
          </span>
          {stay.invite_id && (
            <span className="text-sm text-slate-500 font-mono">Token: {stay.invite_id}</span>
          )}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Authorization start</p>
            <p className="text-sm font-medium text-slate-800 mt-0.5">{formatCalendarDate(stay.approved_stay_start_date)}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Authorization end</p>
            <p className="text-sm font-medium text-slate-800 mt-0.5">{formatCalendarDate(stay.approved_stay_end_date)}</p>
          </div>
          {stay.checked_in_at && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Became active</p>
              <p className="text-sm font-medium text-slate-800 mt-0.5">{formatDateTimeLocal(stay.checked_in_at)}</p>
            </div>
          )}
          {stay.revoked_at && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Revoked at</p>
              <p className="text-sm font-medium text-red-700 mt-0.5">{formatDateTimeLocal(stay.revoked_at)}</p>
            </div>
          )}
          {stay.checked_out_at && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Checked out</p>
              <p className="text-sm font-medium text-slate-800 mt-0.5">{formatDateTimeLocal(stay.checked_out_at)}</p>
            </div>
          )}
        </div>
      </section>

      {!isAgreementArchive(stay) && stay.can_request_extension && (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-base font-semibold text-slate-900 mb-2">Need different dates?</h3>
          <p className="text-sm text-slate-600 mb-4">
            If you need a longer stay, you can notify the resident who invited you. They can send a new guest invitation from their tenant dashboard when ready—which replaces your current authorization when you accept it. Property managers and owners are not copied on this request.
          </p>
          <Button
            variant="outline"
            onClick={() => {
              setExtensionModalStay(stay);
              setExtensionMessage('');
            }}
          >
            Request extension from your host
          </Button>
        </section>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Left: Authorization & documentation */}
        <div className="lg:col-span-2 space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-base font-semibold text-slate-900 mb-4">Signed agreement</h3>
            <p className="text-sm text-slate-600 mb-4">Review and download your signed guest agreement for this stay.</p>
            <Button
              variant="outline"
              disabled={agreementDownloading}
              onClick={async () => {
                if (!stay) return;
                setAgreementDownloading(true);
                try {
                  const blob = await fetchSignedAgreementPdf(stay);
                  const url = URL.createObjectURL(blob);
                  window.open(url, '_blank');
                  setTimeout(() => URL.revokeObjectURL(url), 60000);
                } catch (e) {
                  notify('error', (e as Error)?.message ?? 'No signed agreement found for this stay.');
                } finally {
                  setAgreementDownloading(false);
                }
              }}
            >
              {agreementDownloading ? 'Loading…' : 'Download signed agreement'}
            </Button>
          </div>

          {/* Verification record */}
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-base font-semibold text-slate-900 mb-2">Verification record</h3>
            <p className="text-sm text-slate-500 mb-4">Documents associated with your authorization at this property.</p>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 border border-slate-100">
                <div>
                  <p className="text-sm font-medium text-slate-800">Your signed agreement</p>
                  <p className="text-xs text-slate-500">Temporary stay acknowledgment for this authorization</p>
                </div>
                <Button
                  variant="outline"
                  className="text-xs h-8 px-3 rounded-lg shrink-0"
                  disabled={agreementDownloading}
                  onClick={async () => {
                    if (!stay) return;
                    setAgreementDownloading(true);
                    try {
                      const blob = await fetchSignedAgreementPdf(stay);
                      const url = URL.createObjectURL(blob);
                      window.open(url, '_blank');
                      setTimeout(() => URL.revokeObjectURL(url), 60000);
                    } catch (e) {
                      notify('error', (e as Error)?.message ?? 'No signed agreement found.');
                    } finally {
                      setAgreementDownloading(false);
                    }
                  }}
                >
                  View
                </Button>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-slate-50 border border-slate-100">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-800">Owner authorization (POA)</p>
                  <p className="text-xs text-slate-500">
                    DocuStay&apos;s records can include owner-provided authorization for this property. That record is not specific to your guest role.
                  </p>
                </div>
                {stay.property_live_slug ? (
                  <Button
                    variant="outline"
                    className="text-xs h-8 px-3 rounded-lg shrink-0"
                    onClick={() => {
                      const slug = stay.property_live_slug;
                      if (!slug) return;
                      void openLivePoaPdfInNewTab(slug).then((r) => {
                        if (!r.ok) notify('error', r.userMessage);
                      });
                    }}
                  >
                    View owner authorization (PDF)
                  </Button>
                ) : (
                  <p className="text-xs text-slate-500 shrink-0 max-w-[14rem] text-right">
                    A public authorization PDF link is not available from this stay yet. Ask your host or check back after the property publishes a live page.
                  </p>
                )}
              </div>
              {!isAgreementArchive(stay) && stay.invite_id && (
                <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 border border-slate-100">
                  <div>
                    <p className="text-sm font-medium text-slate-800">Verify authorization</p>
                    <p className="text-xs text-slate-500">Open the public verification page for this stay</p>
                  </div>
                  <Button
                    variant="outline"
                    className="text-xs h-8 px-3 rounded-lg shrink-0"
                    onClick={() => { setVerifyQRInviteId(stay.invite_id != null ? String(stay.invite_id) : null); setShowVerifyQRModal(true); }}
                  >
                    Verify
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* Jurisdiction reference (same source as live property page; UI framing only) */}
          {stay && (stay.jurisdiction_state_name || (stay.jurisdiction_statutes && stay.jurisdiction_statutes.length > 0)) && (
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-700">Legal context — {(stay.jurisdiction_state_name ?? (stay.region_code || 'State')).toUpperCase()}</p>
              <p className="text-xs text-slate-500 mt-2 leading-relaxed border border-slate-200 bg-slate-50/80 rounded-lg px-3 py-2">
                {JURISDICTION_CONTEXT_DISCLAIMER}
              </p>
              <ul className="mt-3 space-y-2">
                {(stay.jurisdiction_statutes ?? []).map((s, i) => (
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

          {/* Audit trail: guest can view their audit trail for this stay */}
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-base font-semibold text-slate-900 mb-2">Activity for this stay</h3>
            <p className="text-sm text-slate-500 mb-4">Status changes, signatures, and related events for your stay. View-only.</p>
            {isAgreementArchive(stay) ? (
              <p className="text-slate-500 text-sm">Activity timeline is available after a stay is confirmed. Your agreement above is your record for this invitation.</p>
            ) : (
            <>
            <Button variant="outline" onClick={() => loadGuestLogs(stay?.stay_id)} disabled={guestLogsLoading} className="mb-4">
              {guestLogsLoading ? 'Loading…' : 'View activity'}
            </Button>
            {guestLogsLoading && guestLogs.length === 0 ? (
              <p className="text-slate-500 text-sm">Loading…</p>
            ) : guestLogsLoadedOnce && guestLogs.length === 0 ? (
              <p className="text-slate-500 text-sm">No log entries for this stay.</p>
            ) : guestLogs.length > 0 ? (
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
                    {guestLogs.map((entry) => (
                      <tr key={entry.id} className="hover:bg-slate-50">
                        <td className="px-4 py-2 text-slate-600 text-sm whitespace-nowrap">
                          {formatLedgerTimestamp(entry.created_at)}
                        </td>
                        <td className="px-4 py-2">
                          <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                            entry.category === 'failed_attempt' ? 'bg-red-100 text-red-800' :
                            entry.category === 'guest_signature' ? 'bg-emerald-100 text-emerald-800' :
                            entry.category === 'shield_mode' ? 'bg-violet-100 text-violet-800' :
                            entry.category === 'dead_mans_switch' ? 'bg-amber-100 text-amber-800' :
                            entry.category === 'billing' ? 'bg-slate-200 text-slate-800' :
                            entry.category === 'presence' ? 'bg-teal-100 text-teal-800' :
                            'bg-sky-100 text-sky-800'
                          }`}>
                            {entry.category === 'shield_mode' ? 'Shield Mode' : entry.category === 'dead_mans_switch' ? 'Stay end reminders' : entry.category === 'billing' ? 'Billing' : entry.category === 'presence' ? 'Presence' : entry.category.replace('_', ' ')}
                          </span>
                        </td>
                        <td className="px-4 py-2 font-medium text-slate-800 text-sm">{entry.title}</td>
                        <td className="px-4 py-2 text-slate-600 text-sm">{entry.actor_email ?? '—'}</td>
                        <td className="px-4 py-2 text-slate-600 text-sm max-w-xs">
                          <span className="truncate block">{scrubAuditLogStateChangeParagraph(entry.message)}</span>
                          <button
                            type="button"
                            onClick={() => setLogMessageModalEntry(entry)}
                            className="text-sky-600 hover:text-sky-800 text-xs mt-0.5 focus:outline-none focus:underline"
                          >
                            View full message
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            </>
            )}
          </section>
        </div>

        {/* Right: Presence (active checked-in stay) + Help */}
        <div className="space-y-6">
          {!isAgreementArchive(stay) && detailCheckedIn && !stay.checked_out_at && !stay.cancelled_at && !stay.revoked_at && (
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h4 className="font-semibold text-slate-900 mb-3">Presence at this property</h4>
              <p className="text-sm text-slate-600 mb-4">Set here or away for this stay. Each property you’re invited to has its own status.</p>
              <div className="flex flex-wrap items-center gap-4">
                <div className={`px-4 py-2 rounded-lg ${stayPresence === 'present' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                  {stayPresence === 'present' ? 'You are here' : stayPresenceAwayStartedAt ? `Away since ${formatDateTimeLocal(stayPresenceAwayStartedAt)}` : 'Away'}
                </div>
                {stayPresence === 'away' && stayPresenceGuestsAuthorized && (
                  <span className="text-sm text-slate-600">Guests authorized during this period</span>
                )}
                <Button variant="outline" onClick={handleStayPresenceToggle} disabled={stayPresenceUpdating} className="rounded-lg">
                  Set to {stayPresence === 'present' ? 'Away' : 'Present'}
                </Button>
              </div>
              {stayShowAwayConfirm && (
                <div className="mt-4 p-4 rounded-lg bg-slate-50 border border-slate-200">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={stayAwayGuestsAuthorized} onChange={(e) => setStayAwayGuestsAuthorized(e.target.checked)} className="rounded" />
                    <span className="text-sm text-slate-700">Guests authorized during this period</span>
                  </label>
                  <div className="flex gap-2 mt-3">
                    <Button onClick={() => doSetStayPresence('away', stayAwayGuestsAuthorized)} disabled={stayPresenceUpdating}>Confirm Away</Button>
                    <Button variant="outline" onClick={() => setStayShowAwayConfirm(false)}>Cancel</Button>
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h4 className="font-semibold text-slate-900 mb-3">Need help?</h4>
            <p className="text-xs text-slate-600 mb-3">
              Contact us at{' '}
              <a href={supportMailtoHref()} className="text-[#6B90F2] font-medium hover:underline break-all">
                {SUPPORT_EMAIL}
              </a>
            </p>
            <div className="flex flex-col gap-2">
              <Button variant="outline" className="w-full justify-center h-10 rounded-lg text-sm font-medium">Message host</Button>
              <Button
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
        </div>
      </div>

      {/* Live link QR modal (same as owner: one button opens this, modal has QR + Open live page + Copy live link) */}
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

      {/* Verify with QR code modal – opens #check with token pre-filled */}
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
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={async (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const url = `${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#check?token=${encodeURIComponent(verifyQRInviteId)}`;
                  const ok = await copyToClipboard(url);
                  setCopyToast(ok ? 'Verify link copied.' : 'Could not copy.');
                  setTimeout(() => setCopyToast(null), 3000);
                }}
              >
                Copy verify link
              </Button>
            </div>
            {copyToast && (
              <p className={`text-sm text-center mt-2 ${copyToast.startsWith('Verify link') ? 'text-emerald-600' : 'text-amber-600'}`}>
                {copyToast}
              </p>
            )}
          </div>
        </div>
      )}
        </div>
  );
})()}
        </div>
        )}
      </main>

      {/* Checkout confirmation */}
      {endStayConfirm && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">Checkout</h3>
            <p className="text-sm text-slate-600 mb-4">
              Have you vacated the property? Completing checkout will end your stay and set your checkout date to today ({formatCalendarDate(today)}). This cannot be undone.
            </p>
            <p className="text-sm font-medium text-slate-700 mb-6">{endStayConfirm.property_name}{endStayConfirm.unit_label ? ` — Unit ${endStayConfirm.unit_label}` : ''}</p>
            <div className="flex gap-3">
              <Button variant="outline" className="flex-1 h-11 rounded-lg font-medium" onClick={() => setEndStayConfirm(null)} disabled={endingStay}>
                Cancel
              </Button>
              <button
                type="button"
                disabled={endingStay}
                className="flex-1 h-11 rounded-lg font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 flex items-center justify-center"
                onClick={handleEndStay}
              >
                {endingStay ? 'Completing…' : 'Complete checkout'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cancel stay confirmation */}
      {extensionModalStay && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">Request extension</h3>
            <p className="text-sm text-slate-600 mb-4">
              We will email your host and show them an alert in DocuStay. Optional note (max 500 characters):
            </p>
            <p className="text-sm font-medium text-slate-700 mb-2">
              {extensionModalStay.property_name}
              {extensionModalStay.unit_label ? ` — Unit ${extensionModalStay.unit_label}` : ''}
            </p>
            <textarea
              className="w-full min-h-[96px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#6B90F2] focus:border-transparent"
              placeholder="e.g. hoping to stay through next weekend…"
              maxLength={500}
              value={extensionMessage}
              onChange={(e) => setExtensionMessage(e.target.value)}
            />
            <p className="text-xs text-slate-500 mt-1">{extensionMessage.length}/500</p>
            <div className="flex gap-3 mt-6">
              <Button
                variant="outline"
                className="flex-1 h-11 rounded-lg font-medium"
                onClick={() => {
                  setExtensionModalStay(null);
                  setExtensionMessage('');
                }}
                disabled={extensionSubmitting}
              >
                Cancel
              </Button>
              <button
                type="button"
                disabled={extensionSubmitting}
                className="flex-1 h-11 rounded-lg font-medium text-white bg-[#6B90F2] hover:bg-[#5a7ed9] disabled:opacity-60"
                onClick={() => { void handleExtensionRequest(); }}
              >
                {extensionSubmitting ? 'Sending…' : 'Send request'}
              </button>
            </div>
          </div>
        </div>
      )}

      {cancelStayConfirm && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">Cancel stay</h3>
            <p className="text-sm text-slate-600 mb-4">
              Cancel your upcoming stay? This will remove the stay from your dashboard and notify the host. This cannot be undone.
            </p>
            <p className="text-sm font-medium text-slate-700 mb-6">{cancelStayConfirm.property_name}{cancelStayConfirm.unit_label ? ` — Unit ${cancelStayConfirm.unit_label}` : ''}</p>
            <div className="flex gap-3">
              <Button variant="outline" className="flex-1 h-11 rounded-lg font-medium" onClick={() => setCancelStayConfirm(null)} disabled={cancellingStay}>
                Keep stay
              </Button>
              <button
                type="button"
                disabled={cancellingStay}
                className="flex-1 h-11 rounded-lg font-medium text-white bg-slate-700 hover:bg-slate-800 disabled:opacity-60 flex items-center justify-center"
                onClick={handleCancelStay}
              >
                {cancellingStay ? 'Cancelling…' : 'Cancel stay'}
              </button>
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
            <p className="text-slate-700 whitespace-pre-wrap text-sm">
              {scrubAuditLogStateChangeParagraph(logMessageModalEntry.message)}
            </p>
            <p className="text-slate-500 text-xs mt-4">
              {logMessageModalEntry.created_at ? formatDateTimeLocal(logMessageModalEntry.created_at) : ''}
              {logMessageModalEntry.actor_email && ` · ${logMessageModalEntry.actor_email}`}
            </p>
          </div>
        )}
      </Modal>

      {pendingSignatureModalInvite && (
        <PendingSignatureModal
          open={!!pendingSignatureModalInvite}
          onClose={() => setPendingSignatureModalInvite(null)}
          invitationCode={pendingSignatureModalInvite.invitation_code}
          propertyName={pendingSignatureModalInvite.property_name}
          stayStartDate={pendingSignatureModalInvite.stay_start_date}
          stayEndDate={pendingSignatureModalInvite.stay_end_date}
          guestEmail={guestEmail}
          guestFullName={guestFullName}
        />
      )}

      {agreementModalCode && (
        <AgreementSignModal
          open={!!agreementModalCode}
          invitationCode={agreementModalCode}
          guestEmail=""
          guestFullName=""
          onClose={() => {
            setAgreementModalCode(null);
            setPrefilledGuestInfoForModal(null);
            loadData();
          }}
          onSigned={handleAgreementSigned}
          notify={notify}
          onRedirectToDropbox={(invitationCode, signatureId, signUrl) => {
            sessionStorage.setItem(DROPBOX_REDIRECT_INVITATION_CODE, invitationCode);
            sessionStorage.setItem(DROPBOX_REDIRECT_SIGNATURE_ID, String(signatureId));
            window.location.href = signUrl;
          }}
          inviteAcceptMode
          onContinueToSign={() => {}}
          prefilledGuestInfo={prefilledGuestInfoForModal}
        />
      )}
    </div>
  );
};
