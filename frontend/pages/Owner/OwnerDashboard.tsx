
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Card, Button, Modal, Input } from '../../components/UI';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import { InviteTenantModal } from '../../components/InviteTenantModal';
import { SendTenantInviteEmailModal } from '../../components/SendTenantInviteEmailModal';
import { ExtendTenantLeaseModal } from '../../components/ExtendTenantLeaseModal';
import { UserSession } from '../../types';
import { dashboardApi, propertiesApi, getContextMode, setContextMode, onPropertiesChanged, buildGuestInviteUrl, demoStoredUnsignedGuestAgreementPdfUrl, DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY, type OwnerStayView, type OwnerInvitationView, type OwnerAuditLogEntry, type Property, type BulkUploadResult, type BillingResponse, type BillingInvoiceView, type BillingPaymentView, type OwnerTenantView } from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import { getTodayLocal, formatStayDuration, formatLedgerTimestamp, formatDateTimeLocal, parseForDisplay, formatCalendarDate } from '../../utils/dateUtils';
import { toUserFriendlyInvitationError } from '../../utils/invitationErrors';
import Settings from '../Settings/Settings';
import HelpCenter from '../Support/HelpCenter';
import { ModeSwitcher } from '../../components/ModeSwitcher';
import { InvitationsTabContent } from '../../components/InvitationsTabContent';
import { DashboardAlertsPanel, DASHBOARD_ALERTS_REFRESH_EVENT } from '../../components/DashboardAlertsPanel';
import { SUPPORT_EMAIL, supportMailtoHref } from '../../constants/supportContact';
import { groupOwnerTenantsByLeaseCohort, isSharedLeaseGroup } from '../../utils/leaseCohortGroups';

function daysLeft(endDateStr: string): number {
  const end = parseForDisplay(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.ceil((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  return Math.max(0, diff);
}

function isOverstayed(endDateStr: string): boolean {
  const end = parseForDisplay(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return end.getTime() < today.getTime();
}

function canOfferLeaseExtension(t: OwnerTenantView): boolean {
  return t.id > 0 && (t.status === 'active' || t.status === 'accepted');
}

/** Invite ID token state badge: displays Pending | Active | Expired | Revoked (maps from STAGED | BURNED | EXPIRED | REVOKED) */
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

/** Aggregate unit counts for dashboard cards (API sets per-property counts from effective occupancy). */
function totalOccupiedUnitsAcrossProperties(properties: Property[]): number {
  return properties.reduce((sum, p) => {
    if (p.occupied_unit_count != null) return sum + p.occupied_unit_count;
    const st = (p.occupancy_status || '').toLowerCase();
    if (st === 'occupied') return sum + (p.unit_count ?? 1);
    return sum;
  }, 0);
}

function totalVacantUnitsAcrossProperties(properties: Property[]): number {
  return properties.reduce((sum, p) => {
    if (p.vacant_unit_count != null) return sum + p.vacant_unit_count;
    const st = (p.occupancy_status || '').toLowerCase();
    if (st === 'vacant') return sum + (p.unit_count ?? 1);
    return sum;
  }, 0);
}

/** Merge PUT /properties response into list row without dropping list-only counts when API omits them. */
function mergePropertyAfterUpdate(prev: Property, updated: Property): Property {
  return {
    ...prev,
    ...updated,
    unit_count: updated.unit_count ?? prev.unit_count,
    occupied_unit_count: updated.occupied_unit_count ?? prev.occupied_unit_count,
    vacant_unit_count: updated.vacant_unit_count ?? prev.vacant_unit_count,
  };
}

function propertyStatusSummary(prop: Property): { badgeText: string; badgeTone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown'; detailText: string | null } {
  const status = (prop.occupancy_status || 'vacant').toLowerCase();
  const tone: 'occupied' | 'vacant' | 'unconfirmed' | 'unknown' =
    status === 'occupied' ? 'occupied' :
    status === 'vacant' ? 'vacant' :
    status === 'unconfirmed' ? 'unconfirmed' :
    'unknown';

  if (prop.is_multi_unit) {
    const occ = prop.occupied_unit_count ?? null;
    const vac = prop.vacant_unit_count ?? null;
    const parts: string[] = [];
    if (occ != null) parts.push(`${occ} occupied`);
    if (vac != null) parts.push(`${vac} vacant`);
    const badgeText = parts.length > 0 ? parts.join(' · ') : 'MULTI-UNIT';
    return { badgeText, badgeTone: tone, detailText: parts.length > 0 ? parts.join(' • ') : null };
  }

  return { badgeText: status.toUpperCase(), badgeTone: tone, detailText: null };
}

const OwnerDashboard: React.FC<{ user: UserSession; navigate: (v: string) => void; setLoading?: (l: boolean) => void; notify?: (t: 'success' | 'error', m: string) => void; initialTab?: string }> = ({ user, navigate, setLoading = (_l: boolean) => {}, notify = (_t: 'success' | 'error', _m: string) => {}, initialTab }) => {
  const [activeTab, setActiveTab] = useState(initialTab ?? 'dashboard');
  const [stays, setStays] = useState<OwnerStayView[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [inactiveProperties, setInactiveProperties] = useState<Property[]>([]);
  const [invitations, setInvitations] = useState<OwnerInvitationView[]>([]);
  const [loading, setLoadingState] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [showInviteTenantModal, setShowInviteTenantModal] = useState(false);
  const [sendEmailTenant, setSendEmailTenant] = useState<OwnerTenantView | null>(null);
  const [leaseExtensionTenant, setLeaseExtensionTenant] = useState<OwnerTenantView | null>(null);
  const [revokeConfirmStay, setRevokeConfirmStay] = useState<OwnerStayView | null>(null);
  const [revokeSuccessGuest, setRevokeSuccessGuest] = useState<string | null>(null);
  const [packetModalStay, setPacketModalStay] = useState<OwnerStayView | null>(null);
  const [deleteConfirmProperty, setDeleteConfirmProperty] = useState<Property | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [logs, setLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsFromTs, setLogsFromTs] = useState('');
  const [logsToTs, setLogsToTs] = useState('');
  const [logsCategory, setLogsCategory] = useState('');
  const [logsSearch, setLogsSearch] = useState('');
  const [logMessageModalEntry, setLogMessageModalEntry] = useState<OwnerAuditLogEntry | null>(null);
  const [showBulkUploadModal, setShowBulkUploadModal] = useState(false);
  const [showBulkUploadRulesModal, setShowBulkUploadRulesModal] = useState(false);
  const [bulkUploadResult, setBulkUploadResult] = useState<BulkUploadResult | null>(null);
  const [bulkUploading, setBulkUploading] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ processed: number; total: number }>({ processed: 0, total: 0 });
  const bulkUploadFileInputRef = useRef<HTMLInputElement | null>(null);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [billingLoading, setBillingLoading] = useState(false);
  const [paymentReturnMessage, setPaymentReturnMessage] = useState<string | null>(null);
  const [paymentReturnIsError, setPaymentReturnIsError] = useState(false);
  const [showVoidInvoiceDialog, setShowVoidInvoiceDialog] = useState(false);
  const [showVerifyQRModal, setShowVerifyQRModal] = useState(false);
  const [verifyQRInviteId, setVerifyQRInviteId] = useState<string | null>(null);
  const [detailStay, setDetailStay] = useState<OwnerStayView | null>(null);
  const [verifyQRCopyToast, setVerifyQRCopyToast] = useState<string | null>(null);
  const [tenants, setTenants] = useState<OwnerTenantView[]>([]);
  const [personalModeUnits, setPersonalModeUnits] = useState<number[]>([]);
  const [contextMode, setContextModeState] = useState<'business' | 'personal'>(() => getContextMode());
  type AssignedManagerItem = { user_id: number; email: string; full_name: string | null; has_resident_mode: boolean; resident_unit_id: number | null; resident_unit_label: string | null };
  const [propertyManagersMap, setPropertyManagersMap] = useState<Record<number, AssignedManagerItem[]>>({});
  const [removingManager, setRemovingManager] = useState<{ propertyId: number; userId: number } | null>(null);
  const [removingResidentMode, setRemovingResidentMode] = useState<{ propertyId: number; userId: number } | null>(null);
  const [primaryResidenceTogglingId, setPrimaryResidenceTogglingId] = useState<number | null>(null);
  /** CR-1a: only All | Shield ON in UI; OFF removed while Shield is always on (DO NOT REMOVE 'off' type if policy reverts). */
  const [shieldFilter, setShieldFilter] = useState<'all' | 'on'>('all');
  const [selectedPropertyIds, setSelectedPropertyIds] = useState<Set<number>>(new Set());
  const [bulkShieldLoading, setBulkShieldLoading] = useState(false);
  /** Business mode overview: which list to show when a stat card is clicked (null = show overview CTA only). */
  type OverviewFilter = 'properties' | 'units' | 'occupied' | 'vacant' | 'unknown' | 'shield_on' | null;
  const [overviewFilter, setOverviewFilter] = useState<OverviewFilter>(null);
  const [allUnitsList, setAllUnitsList] = useState<{ propertyId: number; propertyName: string; address: string; unit: { id: number; unit_label: string; occupancy_status: string; occupied_by?: string | null } }[]>([]);
  const [unitsListLoading, setUnitsListLoading] = useState(false);
  /** Properties tab (Business mode): filter list by status or show units. */
  const [propertiesTabFilter, setPropertiesTabFilter] = useState<'all' | 'units' | 'occupied' | 'vacant' | 'unknown' | 'shield_on'>('all');
  const [propertiesTabUnitsList, setPropertiesTabUnitsList] = useState<{ propertyId: number; propertyName: string; address: string; unit: { id: number; unit_label: string; occupancy_status: string; occupied_by?: string | null } }[]>([]);
  const [propertiesTabUnitsLoading, setPropertiesTabUnitsLoading] = useState(false);

  const setLoadingWrapper = (x: boolean) => { setLoadingState(x); setLoading(x); };

  const handleContextModeChange = (mode: 'business' | 'personal') => {
    setContextMode(mode);
    setContextModeState(mode);
    // Clear all list state immediately so stale data doesn't flash before the new fetch completes
    setProperties([]);
    setInactiveProperties([]);
    setStays([]);
    setInvitations([]);
    setTenants([]);
    loadData();
  };

  const loadData = () => {
    setLoadingWrapper(true);
    setError(null);
    // allSettled: one failed request (e.g. 503 under pool pressure) must not wipe the whole dashboard or
    // fire a global error when other calls already returned 200 — Promise.all did that.
    Promise.allSettled([
      dashboardApi.ownerStays(),
      dashboardApi.ownerInvitations(),
      propertiesApi.list(),
      propertiesApi.listInactive(),
      dashboardApi.ownerPersonalModeUnits().catch(() => ({ unit_ids: [] })),
      dashboardApi.ownerTenants().catch(() => [] as OwnerTenantView[]),
    ]).then((results) => {
      const r0 = results[0];
      const r1 = results[1];
      const r2 = results[2];
      const r3 = results[3];
      const r4 = results[4];
      const r5 = results[5];
      setStays(r0.status === 'fulfilled' ? r0.value : []);
      setInvitations(r1.status === 'fulfilled' ? r1.value : []);
      setProperties(r2.status === 'fulfilled' ? r2.value : []);
      setInactiveProperties(r3.status === 'fulfilled' ? r3.value : []);
      setPersonalModeUnits(
        r4.status === 'fulfilled' ? ((r4.value as { unit_ids: number[] })?.unit_ids ?? []) : [],
      );
      setTenants(r5.status === 'fulfilled' ? (r5.value as OwnerTenantView[]) : []);

      const staysFailed = r0.status === 'rejected';
      const listFailed = r2.status === 'rejected';
      if (staysFailed && listFailed) {
        const msg =
          (r0.reason instanceof Error ? r0.reason.message : null) ||
          (r2.reason instanceof Error ? r2.reason.message : null) ||
          'Failed to load dashboard.';
        setError(msg);
        notify('error', msg);
      } else {
        setError(null);
      }
    }).finally(() => setLoadingWrapper(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (user.user_type !== 'PROPERTY_OWNER' || !user.identity_verified || !user.poa_linked) return;
    let token: string | null = null;
    try {
      token = sessionStorage.getItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY);
    } catch {
      return;
    }
    const t = (token || '').trim();
    if (!t) return;
    let cancelled = false;
    propertiesApi
      .acceptPropertyTransfer(t)
      .then((res) => {
        if (cancelled) return;
        try {
          sessionStorage.removeItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY);
        } catch {
          /* ignore */
        }
        const p = res?.property;
        const detail =
          p &&
          `${p.name?.trim() || "the property"}${p.address ? ` (${p.address})` : p.city || p.state ? ` (${[p.street, p.city, p.state].filter(Boolean).join(", ")})` : ""}`;
        notify(
          "success",
          detail ? `You accepted ownership of ${detail}.` : "You accepted ownership of the property.",
        );
        loadData();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      })
      .catch((e) => {
        if (cancelled) return;
        const msg = ((e as Error)?.message || '').toLowerCase();
        if (msg.includes('not found') || msg.includes('expired') || msg.includes('no longer valid')) {
          try {
            sessionStorage.removeItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY);
          } catch {
            /* ignore */
          }
        }
      });
    return () => {
      cancelled = true;
    };
  }, [user.user_type, user.identity_verified, user.poa_linked, user.user_id, notify]);

  useEffect(() => {
    const unsub = onPropertiesChanged(() => loadData());
    return unsub;
  }, []);

  // When user selects "Units" in overview, load all units across properties
  useEffect(() => {
    if (overviewFilter !== 'units' || properties.length === 0) {
      setAllUnitsList([]);
      return;
    }
    setUnitsListLoading(true);
    Promise.all(
      properties.map((p) =>
        propertiesApi.getUnits(p.id).then((units) =>
          (units || []).map((u) => ({
            propertyId: p.id,
            propertyName: p.name || [p.street, p.city, p.state].filter(Boolean).join(', ') || `Property #${p.id}`,
            address: [p.street, p.city, p.state, p.zip_code].filter(Boolean).join(', '),
            unit: { id: u.id, unit_label: u.unit_label || '—', occupancy_status: u.occupancy_status || 'vacant', occupied_by: u.occupied_by },
          }))
        )
      )
    )
      .then((rows) => setAllUnitsList(rows.flat()))
      .catch(() => setAllUnitsList([]))
      .finally(() => setUnitsListLoading(false));
  }, [overviewFilter, properties]);

  // Properties tab: load all units when filter is "units"
  useEffect(() => {
    if (propertiesTabFilter !== 'units' || properties.length === 0) {
      setPropertiesTabUnitsList([]);
      return;
    }
    setPropertiesTabUnitsLoading(true);
    Promise.all(
      properties.map((p) =>
        propertiesApi.getUnits(p.id).then((units) =>
          (units || []).map((u) => ({
            propertyId: p.id,
            propertyName: p.name || [p.street, p.city, p.state].filter(Boolean).join(', ') || `Property #${p.id}`,
            address: [p.street, p.city, p.state, p.zip_code].filter(Boolean).join(', '),
            unit: { id: u.id, unit_label: u.unit_label || '—', occupancy_status: u.occupancy_status || 'vacant', occupied_by: u.occupied_by },
          }))
        )
      )
    )
      .then((rows) => setPropertiesTabUnitsList(rows.flat()))
      .catch(() => setPropertiesTabUnitsList([]))
      .finally(() => setPropertiesTabUnitsLoading(false));
  }, [propertiesTabFilter, properties]);

  useEffect(() => {
    if (initialTab) setActiveTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    if (contextMode === 'personal' && ['billing', 'logs', 'tenants', 'pending-tenants'].includes(activeTab)) setActiveTab('dashboard');
    if (contextMode === 'business' && ['guests'].includes(activeTab)) setActiveTab('dashboard');
  }, [contextMode]);

  useEffect(() => {
    if (activeTab !== 'properties' || properties.length === 0) return;
    const loadManagers = async () => {
      const next: Record<number, AssignedManagerItem[]> = {};
      await Promise.all(
        properties.map(async (prop) => {
          try {
            const list = await propertiesApi.listAssignedManagers(prop.id);
            next[prop.id] = list;
          } catch {
            next[prop.id] = [];
          }
        })
      );
      setPropertyManagersMap(next);
    };
    loadManagers();
  }, [activeTab, properties]);

  // Filtered list for Properties tab (Business mode): by status card or shield
  const propertiesTabFilteredProps = React.useMemo(() => {
    const statusFiltered =
      propertiesTabFilter === 'all' ? properties :
      propertiesTabFilter === 'units' ? [] :
      propertiesTabFilter === 'occupied' ? properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'occupied') :
      propertiesTabFilter === 'vacant' ? properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'vacant') :
      propertiesTabFilter === 'unknown' ? properties.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase())) :
      properties.filter((p) => p.shield_mode_enabled);
    return propertiesTabFilter === 'all'
      ? (shieldFilter === 'all' ? properties : properties.filter((p) => p.shield_mode_enabled))
      : statusFiltered;
  }, [properties, propertiesTabFilter, shieldFilter]);

  // Only checked-in stays count as active for occupancy, current guest, and Status Confirmation
  const activeStays = stays.filter((s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);
  const activeCount = activeStays.length;
  // Overstay = still active (not checked out, not cancelled) but end date has passed
  const overstays = activeStays.filter((s) => isOverstayed(s.stay_end_date));
  const firstOverstay = overstays[0];

  const handleRevokeClick = (stay: OwnerStayView) => {
    setRevokeConfirmStay(stay);
  };

  const [revokeLoading, setRevokeLoading] = useState(false);
  const handleRevokeConfirm = async () => {
    if (!revokeConfirmStay) return;
    setRevokeLoading(true);
    try {
      await dashboardApi.revokeStay(revokeConfirmStay.stay_id);
      notify('success', 'Stay revoked. Guest must vacate within 12 hours. Email sent.');
      setRevokeConfirmStay(null);
      setRevokeSuccessGuest(revokeConfirmStay.guest_name);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to revoke stay.');
    } finally {
      setRevokeLoading(false);
    }
  };

  const handleInitiateRemoval = (stay: OwnerStayView) => {
    setPacketModalStay(stay);
  };

  const [removalLoading, setRemovalLoading] = useState(false);
  const handleRemovalConfirm = async () => {
    if (!packetModalStay) return;
    setRemovalLoading(true);
    try {
      await dashboardApi.initiateRemoval(packetModalStay.stay_id);
      notify('success', 'Removal initiated. Guest and owner notified via email.');
      setPacketModalStay(null);
      loadData();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to initiate removal.');
    } finally {
      setRemovalLoading(false);
    }
  };

  const loadLogs = () => {
    setLogsLoading(true);
    dashboardApi.ownerLogs({
      from_ts: logsFromTs ? new Date(logsFromTs).toISOString() : undefined,
      to_ts: logsToTs ? new Date(logsToTs).toISOString() : undefined,
      category: logsCategory || undefined,
      search: logsSearch.trim() || undefined,
    })
      .then(setLogs)
      .catch(() => setLogs([]))
      .finally(() => setLogsLoading(false));
  };

  useEffect(() => {
    if (activeTab === 'logs') loadLogs();
  }, [activeTab]);

  const loadBilling = () => {
    setBillingLoading(true);
    dashboardApi.billing()
      .then(setBilling)
      .catch(() => setBilling({ invoices: [], payments: [], can_invite: true }))
      .finally(() => setBillingLoading(false));
  };

  useEffect(() => {
    if (activeTab === 'billing') loadBilling();
  }, [activeTab]);

  // When returning from Stripe payment (portal or hosted invoice), refetch billing and show message so user sees paid status without reloading
  useEffect(() => {
    if (activeTab !== 'billing' || typeof window === 'undefined') return;
    const search = window.location.search || '';
    const hash = window.location.hash || '';
    const hasPaymentReturn = /redirect_status=|payment_intent=|payment_intent_client_secret=/.test(search) || /[?&]redirect_status=|[?&]payment_intent=/.test(hash);
    if (!hasPaymentReturn) return;
    const paymentFailed = /redirect_status=failed|payment_failed/.test(search) || /[?&]redirect_status=failed|[?&]payment_failed/.test(hash);
    setBillingLoading(true);
    dashboardApi.billing()
      .then((data) => {
        setBilling(data);
        setPaymentReturnIsError(!!paymentFailed);
        setPaymentReturnMessage(paymentFailed
          ? "Your payment could not be processed. Please update your payment method in the payment portal and try again."
          : "We've refreshed your payment status. If you just paid, your invoice and invite access are now updated.");
        // Clear payment params from URL so we don't re-trigger; keep user on Billing tab
        window.history.replaceState(null, '', window.location.pathname + '#dashboard/billing');
      })
      .catch(() => setBilling((prev) => prev ?? { invoices: [], payments: [], can_invite: true }))
      .finally(() => setBillingLoading(false));
  }, [activeTab]);

  // Load billing once on mount so can_invite is available (required before inviting guests).
  // Defer slightly so we do not stack 6 dashboard + billing + alerts requests in one pool burst (503 under small SQLAlchemy pools).
  useEffect(() => {
    const id = window.setTimeout(() => loadBilling(), 400);
    return () => clearTimeout(id);
  }, []);

  useEffect(() => {
    if (activeTab !== 'billing' || billing?.subscription_status !== 'trialing') return;
    const t = window.setInterval(() => {
      dashboardApi.billing().then(setBilling).catch(() => {});
    }, 60_000);
    return () => window.clearInterval(t);
  }, [activeTab, billing?.subscription_status]);

  const canInvite = billing?.can_invite !== false;

  const pendingTenantCount = useMemo(
    () => tenants.filter((t) => t.status === 'pending' || t.status === 'pending_signup').length,
    [tenants],
  );
  const tenantGroups = useMemo(() => groupOwnerTenantsByLeaseCohort(tenants), [tenants]);
  const pendingTenantGroups = useMemo(
    () => groupOwnerTenantsByLeaseCohort(tenants.filter((t) => t.status === 'pending' || t.status === 'pending_signup')),
    [tenants],
  );

  const tenantStatusBadge = (t: OwnerTenantView) => (
    <span
      className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest ${
        t.status === 'active'
          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
          : t.status === 'accepted'
            ? 'bg-sky-50 text-sky-700 border border-sky-200'
            : t.status === 'pending' || t.status === 'pending_signup'
              ? 'bg-amber-50 text-amber-700 border border-amber-200'
              : 'bg-slate-100 text-slate-500 border border-slate-200'
      }`}
    >
      {t.status === 'active' ? 'Active' : t.status === 'accepted' ? 'Accepted' : t.status === 'pending' || t.status === 'pending_signup' ? 'Pending' : 'Expired'}
    </span>
  );

  const openInviteModalOrNotify = () => {
    if (!canInvite) {
      notify('error', 'Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly.');
      setActiveTab('billing');
      return;
    }
    if (contextMode === 'personal') {
      setShowInviteModal(true);
      return;
    }
    setShowInviteTenantModal(true);
  };

  const openTenantInviteOrNotify = () => {
    if (!canInvite) {
      notify('error', 'Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly.');
      setActiveTab('billing');
      return;
    }
    setShowInviteTenantModal(true);
  };

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar Navigation (fixed width so it does not shrink) */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {[
            { id: 'dashboard', label: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
            { id: 'properties', label: 'My Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
            ...(contextMode === 'personal' ? [{ id: 'guests', label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' }] : []),
            ...(contextMode !== 'personal' ? [{ id: 'tenants', label: 'Tenants', icon: 'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z' }] : []),
            ...(contextMode !== 'personal' ? [{ id: 'pending-tenants', label: 'Pending tenants', icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z' }] : []),
            { id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
            ...(contextMode !== 'personal' ? [{ id: 'billing', label: 'Billing', icon: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2H9v2h2v6a2 2 0 002 2h2a2 2 0 002-2v-6h2V9zm-6 0V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2h4z' }] : []),
            ...(contextMode !== 'personal' ? [{ id: 'logs', label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' }] : []),
            { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
            { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' }
          ].map(item => (
            <button
              key={item.id}
              onClick={() => {
                setActiveTab(item.id);
                if (item.id === 'pending-tenants') navigate('dashboard/pending-tenants');
              }}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${activeTab === item.id ? 'bg-slate-100 text-slate-700 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon}></path></svg>
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex-grow min-h-0" />

        {/* Mode switcher at bottom */}
        <div className="mt-6 pt-6 border-t border-slate-200 flex-shrink-0">
          <ModeSwitcher
            contextMode={contextMode}
            personalModeUnits={personalModeUnits}
            onContextModeChange={handleContextModeChange}
          />
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-grow overflow-y-auto no-scrollbar bg-transparent p-8">
        {/* Mobile tab nav: when sidebar is hidden (below lg), show dropdown so Billing and all tabs are reachable */}
        <div className="lg:hidden mb-6">
          <label htmlFor="mobile-tab-select" className="sr-only">Navigate to</label>
          <select
            id="mobile-tab-select"
            value={activeTab}
            onChange={(e) => {
              const v = e.target.value;
              setActiveTab(v);
              if (v === 'pending-tenants') navigate('dashboard/pending-tenants');
            }}
            className="w-full max-w-xs rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="dashboard">Dashboard</option>
            <option value="properties">My Properties</option>
            {contextMode === 'personal' && <option value="guests">Guests</option>}
            {contextMode !== 'personal' && <option value="tenants">Tenants</option>}
            {contextMode !== 'personal' && <option value="pending-tenants">Pending tenants</option>}
            <option value="invitations">Invitations</option>
            {contextMode !== 'personal' && <option value="billing">Billing</option>}
            {contextMode !== 'personal' && <option value="logs">Event ledger</option>}
            <option value="settings">Settings</option>
            <option value="help">Help Center</option>
          </select>
        </div>
        {/* No duplicate header on Settings/Help – those pages render their own title and content */}
        {activeTab !== 'settings' && activeTab !== 'help' && (
          <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-10 gap-6">
            <div>
              <h1 className="text-4xl font-extrabold text-slate-800 tracking-tight">
                {activeTab === 'properties' ? 'My Properties' : activeTab === 'guests' ? 'Guests' : activeTab === 'tenants' ? 'Tenants' : activeTab === 'pending-tenants' ? 'Pending tenants' : activeTab === 'invitations' ? 'Invitations' : activeTab === 'billing' ? 'Billing' : activeTab === 'logs' ? 'Event ledger' : 'Overview'}
              </h1>
              <p className="text-slate-600 mt-1">
                {activeTab === 'properties' ? 'View, edit, or remove your registered properties.' : activeTab === 'guests' ? 'Guests currently staying at your properties and their stay details.' : activeTab === 'tenants' ? 'Tenants assigned to your properties and their lease details.' : activeTab === 'pending-tenants' ? 'Tenants from CSV or manual invites who have not yet registered. Send each person an email with their invitation link.' : activeTab === 'invitations' ? (contextMode === 'business' ? 'Tenant invitations you have sent.' : 'Pending invitations waiting for guests to accept.') : activeTab === 'billing' ? 'Invoices and payment history. $10 per unit per month after your free trial; subscription charges appear here.' : activeTab === 'logs' ? 'Immutable event ledger: status changes, guest signatures, payment and billing activity, and failed attempts. Filter by time, category, or search.' : 'Documentation and authorization for your properties.'}
              </p>
            </div>
            <div className="flex gap-4 flex-wrap items-center">
              {activeTab !== 'properties' && contextMode === 'personal' && (
                <span className={!canInvite ? 'group relative inline-block cursor-not-allowed' : undefined}>
                  {!canInvite && (
                    <span
                      className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-3 py-2 bg-gray-900 text-white text-xs rounded shadow-lg whitespace-nowrap opacity-0 pointer-events-none transition-opacity duration-150 z-[200] group-hover:opacity-100"
                      role="tooltip"
                    >
                      Billing setup is still in progress. Open Billing to finish subscription setup.
                    </span>
                  )}
                  <Button variant="outline" onClick={openInviteModalOrNotify} className={`px-6 flex items-center gap-2${!canInvite ? ' pointer-events-none' : ''}`} disabled={!canInvite}>
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                    Invite
                  </Button>
                </span>
              )}
              {(activeTab === 'tenants' || activeTab === 'invitations') && contextMode !== 'personal' && (
                <Button variant="outline" onClick={openTenantInviteOrNotify} className="px-6 flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                  Invite Tenant
                </Button>
              )}
              {activeTab === 'properties' && contextMode !== 'personal' && (
                <div className="flex items-center gap-1.5">
                  <Button variant="outline" onClick={openTenantInviteOrNotify} className="px-6 flex items-center gap-2">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                    Invite Tenant
                  </Button>
                  <Button variant="outline" onClick={() => setShowBulkUploadModal(true)} className="px-6 flex items-center gap-2">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                    Upload in bulk
                  </Button>
                  <button
                    type="button"
                    onClick={() => setShowBulkUploadRulesModal(true)}
                    className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                    aria-label="Bulk upload rules"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                  </button>
                </div>
              )}
              {contextMode !== 'personal' && (
                <Button variant="primary" onClick={() => navigate('add-property')} className="px-6">
                  Register Property
                </Button>
              )}
            </div>
          </header>
        )}

        {activeTab !== 'settings' && activeTab !== 'help' && (
          <DashboardAlertsPanel role="owner" className="mb-6" limit={50} />
        )}

        {error && (
          <div className="mb-8 p-6 rounded-2xl bg-slate-50 border border-slate-200 text-center">
            <p className="text-slate-600 mb-4">Something went wrong loading the dashboard.</p>
            <Button variant="primary" onClick={() => { setError(null); loadData(); }}>Try again</Button>
          </div>
        )}

        {loading ? (
          <p className="text-slate-600">Loading dashboard…</p>
        ) : activeTab === 'guests' && contextMode === 'personal' ? (
          /* Guests tab: pending invitations + active & expired stays (personal mode only; never show in business) */
          <div className="space-y-8">
            <p className="text-slate-500 text-sm">
              Pending invitations, active stays, and past/expired stays. Data is loaded from your dashboard.
            </p>

            {/* Pending invitations */}
            {invitations.filter((i) => i.status === 'pending').length > 0 && (
              <Card className="overflow-hidden">
                <div className="p-6 border-b border-slate-200 bg-amber-50">
                  <h3 className="text-xl font-bold text-slate-800">Pending invitations</h3>
                  <p className="text-xs text-slate-500 mt-1">Invites not yet accepted by the guest</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Invited (email)</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Planned stay</th>
                        <th className="px-6 py-4">Region</th>
                        <th className="px-6 py-4">Code</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                      {invitations.filter((i) => i.status === 'pending').map((inv) => (
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
                            {inv.is_expired ? (
                              <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-slate-100 text-slate-600 border border-slate-200">Expired</span>
                            ) : (
                              <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest bg-amber-500/10 text-amber-700 border border-amber-200">Pending</span>
                            )}
                          </td>
                          <td className="px-6 py-5 text-right">
                            <div className="flex flex-wrap justify-end gap-2">
                              {inv.is_demo && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  type="button"
                                  onClick={() => window.open(demoStoredUnsignedGuestAgreementPdfUrl(inv.invitation_code), '_blank')}
                                >
                                  Unsigned PDF
                                </Button>
                              )}
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={async () => {
                                  const url = buildGuestInviteUrl(inv.invitation_code, { isDemo: Boolean(inv.is_demo) });
                                  const ok = await copyToClipboard(url);
                                  if (ok) notify('success', 'Invitation link copied to clipboard.');
                                  else notify('error', 'Could not copy. Please copy the link manually.');
                                }}
                              >
                                Copy link
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            {/* Stays: active and expired */}
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-white/60 backdrop-blur-md">
                <h3 className="text-xl font-bold text-slate-800">Stays (active & past)</h3>
                <p className="text-xs text-slate-500 mt-1">Guests who accepted and their current or past stay</p>
              </div>
              {stays.length === 0 ? (
                <div className="px-6 py-12 text-center text-slate-500">No stays yet. When guests accept an invitation, they appear here.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Guest</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Stay period</th>
                        <th className="px-6 py-4">Region</th>
                        <th className="px-6 py-4">Days left</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                      {stays.map((stay) => {
                        const overstay = isOverstayed(stay.stay_end_date);
                        const dLeft = daysLeft(stay.stay_end_date);
                        const revoked = !!stay.revoked_at;
                        const completed = !!stay.checked_out_at;
                        const cancelled = !!stay.cancelled_at;
                        const isActive = !completed && !cancelled;
                        return (
                          <tr key={stay.stay_id} className="hover:bg-slate-50 transition-colors">
                            <td className="px-6 py-5">
                              <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-sm">
                                  {stay.guest_name.charAt(0)}
                                </div>
                                <div>
                                  <p className="text-sm font-bold text-slate-800">{stay.guest_name}</p>
                                  <p className="text-xs text-slate-500">Stay #{stay.stay_id}</p>
                                </div>
                              </div>
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
                              <span className={`text-sm font-bold ${!isActive ? 'text-slate-500' : revoked ? 'text-amber-600' : overstay ? 'text-red-600' : 'text-green-600'}`}>
                                {completed || cancelled ? '—' : revoked ? '—' : overstay ? '—' : `${dLeft}d`}
                              </span>
                            </td>
                            <td className="px-6 py-5">
                              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest ${
                                stay.invitation_only ? 'bg-amber-50 text-amber-700 border border-amber-200' : completed ? 'bg-slate-100 text-slate-600 border border-slate-200' : cancelled ? 'bg-slate-100 text-slate-500 border border-slate-200' : revoked ? 'bg-amber-50 text-amber-700 border border-amber-500/20' : overstay ? 'bg-red-50 text-red-600 border border-red-500/20' : 'bg-green-50 text-green-700 border border-green-200'
                              }`}>
                                {stay.invitation_only ? 'Pending sign-up' : completed ? 'Completed' : cancelled ? 'Cancelled' : revoked ? 'Revoked' : overstay ? 'Overstayed' : 'Active'}
                              </span>
                            </td>
                            <td className="px-6 py-5 text-right space-x-2">
                              {stay.invite_id && (
                                <Button variant="outline" onClick={() => { setVerifyQRInviteId(stay.invite_id ?? null); setShowVerifyQRModal(true); }} className="text-xs py-2">Verify QR</Button>
                              )}
                              {stay.invitation_only ? (
                                <span className="text-xs text-slate-500"></span>
                              ) : completed || cancelled ? (
                                <span className="text-xs text-slate-500">—</span>
                              ) : revoked ? (
                                <span className="text-xs text-slate-500">Revoked</span>
                              ) : overstay ? (
                                <Button variant="danger" onClick={() => handleInitiateRemoval(stay)} className="text-xs py-2">Remove</Button>
                              ) : (
                                <Button variant="ghost" onClick={() => handleRevokeClick(stay)} className="text-xs py-2 text-red-600 hover:text-red-700">Revoke</Button>
                              )}
                              <Button variant="outline" onClick={() => setDetailStay(stay)} className="text-xs py-2">Details</Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            {stays.length === 0 && invitations.filter((i) => i.status === 'pending').length === 0 && (
              <Card className="p-12 text-center">
                <p className="text-slate-600 mb-6">No guests or pending invites yet. Invite someone to get started.</p>
                <span className={!canInvite ? 'group relative inline-block cursor-not-allowed' : undefined}>
                  {!canInvite && (
                    <span
                      className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-3 py-2 bg-gray-900 text-white text-xs rounded shadow-lg whitespace-nowrap opacity-0 pointer-events-none transition-opacity duration-150 z-[200] group-hover:opacity-100"
                      role="tooltip"
                    >
                      Billing setup is still in progress. Open Billing to finish subscription setup.
                    </span>
                  )}
                  <Button variant="primary" onClick={openInviteModalOrNotify} className={!canInvite ? 'pointer-events-none' : undefined} disabled={!canInvite}>Invite</Button>
                </span>
              </Card>
            )}
          </div>
        ) : activeTab === 'invitations' ? (
          <InvitationsTabContent
            invitations={invitations}
            stays={stays}
            loadData={loadData}
            notify={notify}
            showVerifyQR={true}
            onVerifyQR={(code) => { setVerifyQRInviteId(code); setShowVerifyQRModal(true); }}
            onCancelInvitation={async (id) => { await dashboardApi.cancelInvitation(id); notify('success', 'Invitation cancelled.'); loadData(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }}
            onResendInvitation={contextMode === 'personal' ? async (id) => { await dashboardApi.tenantResendInvitation(id); loadData(); } : undefined}
            introText={contextMode === 'business' ? 'Tenant invitations: pending rows are awaiting tenant registration (links do not expire on a short clock). Guest invitations use a pending window as shown below.' : "Invitations you've sent. Pending invitations are labeled as expired after 72 hours if not accepted."}
          />
        ) : activeTab === 'pending-tenants' && contextMode !== 'personal' ? (
          <div className="space-y-8">
            {pendingTenantCount === 0 ? (
              <Card className="p-12 text-center">
                <p className="text-slate-600 mb-6">No pending tenant signups. Tenants from a CSV bulk upload (occupied rows) or invites without a completed registration appear here.</p>
                <Button variant="outline" onClick={() => { setActiveTab('dashboard'); navigate('dashboard'); }}>Back to overview</Button>
              </Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="p-6 border-b border-slate-200 bg-amber-50/80">
                  <h3 className="text-xl font-bold text-slate-800">Awaiting registration</h3>
                  <p className="text-xs text-slate-500 mt-1">{pendingTenantCount} tenant{pendingTenantCount === 1 ? '' : 's'} need to create an account</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Tenant</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Unit</th>
                        <th className="px-6 py-4">Lease period</th>
                        <th className="px-6 py-4">Invite ID</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {pendingTenantGroups.map((g) => {
                        const shared = isSharedLeaseGroup(g);
                        const primary = g.members[0];
                        return (
                          <tr key={g.cohortKey} className={`hover:bg-slate-50 transition-colors ${shared ? 'bg-sky-50/30' : ''}`}>
                            <td className="px-6 py-5">
                              {shared ? (
                                <div>
                                  <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide bg-sky-100 text-sky-800 border border-sky-200">
                                    Shared lease
                                  </span>
                                  <div className="mt-3 space-y-3">
                                    {g.members.map((t) => (
                                      <div key={t.id} className="flex items-center gap-3">
                                        <div className="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm bg-amber-100 text-amber-700">
                                          {(t.tenant_name || '?').charAt(0).toUpperCase()}
                                        </div>
                                        <div>
                                          <p className="text-sm font-bold text-slate-800">{t.tenant_name}</p>
                                          {t.tenant_email && <p className="text-xs text-slate-500">{t.tenant_email}</p>}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-center gap-3">
                                  <div className="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm bg-amber-100 text-amber-700">
                                    {(primary.tenant_name || '?').charAt(0).toUpperCase()}
                                  </div>
                                  <div>
                                    <p className="text-sm font-bold text-slate-800">{primary.tenant_name}</p>
                                    {primary.tenant_email && <p className="text-xs text-slate-500">{primary.tenant_email}</p>}
                                  </div>
                                </div>
                              )}
                            </td>
                            <td className="px-6 py-5 text-sm font-medium text-slate-800">{primary.property_name}</td>
                            <td className="px-6 py-5 text-sm text-slate-600">{primary.unit_label || '—'}</td>
                            <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                              {primary.start_date && primary.end_date ? formatStayDuration(primary.start_date, primary.end_date) : '—'}
                            </td>
                            <td className="px-6 py-5 text-xs font-mono text-slate-500">
                              {shared ? (
                                <ul className="space-y-1 list-none p-0 m-0">
                                  {g.members.map((t) => (
                                    <li key={t.id}>{t.invitation_code || '—'}</li>
                                  ))}
                                </ul>
                              ) : (
                                primary.invitation_code || '—'
                              )}
                            </td>
                            <td className="px-6 py-5 text-right">
                              {shared ? (
                                <div className="flex flex-col gap-2 items-end">
                                  {g.members.map((t) => (
                                    <Button
                                      key={t.id}
                                      variant="primary"
                                      size="sm"
                                      disabled={!t.invitation_id}
                                      onClick={() => setSendEmailTenant(t)}
                                    >
                                      Send ({(t.tenant_name || t.tenant_email || 'tenant').split(/\s+/)[0]})
                                    </Button>
                                  ))}
                                </div>
                              ) : (
                                <Button
                                  variant="primary"
                                  size="sm"
                                  disabled={!primary.invitation_id}
                                  onClick={() => setSendEmailTenant(primary)}
                                >
                                  Send invite email
                                </Button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </div>
        ) : activeTab === 'tenants' && contextMode !== 'personal' ? (
          <div className="space-y-8">
            {tenants.length === 0 ? (
              <Card className="p-12 text-center">
                <p className="text-slate-600 mb-6">No tenants or tenant invitations for your properties yet.</p>
                <Button variant="outline" onClick={openTenantInviteOrNotify} disabled={!canInvite}>Invite Tenant</Button>
              </Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="p-6 border-b border-slate-200 bg-white/60 backdrop-blur-md">
                  <h3 className="text-xl font-bold text-slate-800">Tenants</h3>
                  <p className="text-xs text-slate-500 mt-1">Active tenants and pending invitations for your properties</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Tenant</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Unit</th>
                        <th className="px-6 py-4">Lease period</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4">Invite code</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {tenantGroups.map((g) => {
                        const shared = isSharedLeaseGroup(g);
                        const primary = g.members[0];
                        return (
                          <tr key={g.cohortKey} className={`hover:bg-slate-50 transition-colors ${shared ? 'bg-sky-50/30' : ''}`}>
                            <td className="px-6 py-5">
                              {shared ? (
                                <div>
                                  <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide bg-sky-100 text-sky-800 border border-sky-200">
                                    Shared lease
                                  </span>
                                  <div className="mt-3 space-y-3">
                                    {g.members.map((t) => (
                                      <div key={t.id} className="flex items-center gap-3">
                                        <div
                                          className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm ${
                                            t.status === 'pending' || t.status === 'pending_signup' ? 'bg-amber-100 text-amber-700' : 'bg-slate-200 text-slate-700'
                                          }`}
                                        >
                                          {(t.tenant_name || '?').charAt(0).toUpperCase()}
                                        </div>
                                        <div>
                                          <p className="text-sm font-bold text-slate-800">{t.tenant_name}</p>
                                          {t.tenant_email && <p className="text-xs text-slate-500">{t.tenant_email}</p>}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-center gap-3">
                                  <div
                                    className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm ${
                                      primary.status === 'pending' || primary.status === 'pending_signup' ? 'bg-amber-100 text-amber-700' : 'bg-slate-200 text-slate-700'
                                    }`}
                                  >
                                    {(primary.tenant_name || '?').charAt(0).toUpperCase()}
                                  </div>
                                  <div>
                                    <p className="text-sm font-bold text-slate-800">{primary.tenant_name}</p>
                                    {primary.tenant_email && <p className="text-xs text-slate-500">{primary.tenant_email}</p>}
                                  </div>
                                </div>
                              )}
                            </td>
                            <td className="px-6 py-5">
                              <p className="text-sm font-medium text-slate-800">{primary.property_name}</p>
                            </td>
                            <td className="px-6 py-5 text-sm text-slate-600">{primary.unit_label || '—'}</td>
                            <td className="px-6 py-5 text-sm text-slate-600 whitespace-nowrap">
                              {primary.start_date && primary.end_date
                                ? formatStayDuration(primary.start_date, primary.end_date)
                                : primary.start_date
                                  ? `From ${formatCalendarDate(primary.start_date)}`
                                  : '—'}
                              {primary.status === 'active' && !primary.end_date && <span className="ml-1 text-xs text-slate-400">(open-ended)</span>}
                              {primary.status === 'accepted' && primary.start_date && <span className="ml-1 text-xs text-slate-400">(not yet started)</span>}
                            </td>
                            <td className="px-6 py-5">
                              {shared ? (
                                <div className="flex flex-col gap-1 items-start">{g.members.map((t) => <span key={t.id}>{tenantStatusBadge(t)}</span>)}</div>
                              ) : (
                                tenantStatusBadge(primary)
                              )}
                            </td>
                            <td className="px-6 py-5 text-xs font-mono text-slate-500">
                              {shared ? (
                                <ul className="space-y-1 list-none p-0 m-0">
                                  {g.members.map((t) => (
                                    <li key={t.id}>{t.invitation_code || '—'}</li>
                                  ))}
                                </ul>
                              ) : (
                                primary.invitation_code || '—'
                              )}
                            </td>
                            <td className="px-6 py-5 text-right align-top">
                              {shared ? (
                                <div className="flex flex-col gap-2 items-end">
                                  {g.members.map((t) =>
                                    canOfferLeaseExtension(t) ? (
                                      <Button
                                        key={t.id}
                                        variant="outline"
                                        className="text-xs px-3 py-1.5"
                                        onClick={() => setLeaseExtensionTenant(t)}
                                      >
                                        Extend lease
                                      </Button>
                                    ) : (
                                      <span key={t.id} className="text-xs text-slate-400">—</span>
                                    ),
                                  )}
                                </div>
                              ) : canOfferLeaseExtension(primary) ? (
                                <Button variant="outline" className="text-xs px-3 py-1.5" onClick={() => setLeaseExtensionTenant(primary)}>
                                  Extend lease
                                </Button>
                              ) : (
                                <span className="text-xs text-slate-400">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </div>
        ) : activeTab === 'properties' ? (
          /* Properties tab: Active list + Inactive section */
          <div className="space-y-8">
            
            {properties.length === 0 && inactiveProperties.length === 0 ? (
              <Card className="p-12 text-center">
                <p className="text-slate-600 mb-6">You haven’t registered any properties yet.</p>
                {contextMode !== 'personal' && (
                  <Button variant="primary" onClick={() => navigate('add-property')}>Register your first property</Button>
                )}
              </Card>
            ) : (
              <>
              {/* Active properties */}
              {properties.length > 0 && (
              <div>
                {contextMode === 'business' && (() => {
                  const totalUnits = properties.reduce((s, p) => s + (p.unit_count ?? 1), 0);
                  const occupiedUnitsCount = totalOccupiedUnitsAcrossProperties(properties);
                  const vacantUnitsCount = totalVacantUnitsAcrossProperties(properties);
                  const unknownCount = properties.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase())).length;
                  const shieldOnCount = properties.filter((p) => p.shield_mode_enabled).length;
                  const filters: { key: typeof propertiesTabFilter; label: string; count: number; border: string }[] = [
                    { key: 'all', label: 'Properties', count: properties.length, border: 'border-blue-500' },
                    { key: 'units', label: 'Units', count: totalUnits, border: 'border-indigo-500' },
                    { key: 'occupied', label: 'Occupied', count: occupiedUnitsCount, border: 'border-emerald-500' },
                    { key: 'vacant', label: 'Vacant', count: vacantUnitsCount, border: 'border-sky-500' },
                    { key: 'unknown', label: 'Unknown', count: unknownCount, border: 'border-slate-400' },
                    { key: 'shield_on', label: 'Shield On', count: shieldOnCount, border: 'border-amber-500' },
                  ];
                  return (
                    <div className="grid md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-6 mb-6">
                      {filters.map(({ key, label, count, border }) => (
                        <Card
                          key={key}
                          role="button"
                          className={`p-6 border-l-4 ${border} hover:scale-[1.02] transition-transform cursor-pointer ${propertiesTabFilter === key ? 'ring-2 ring-slate-400 ring-offset-2' : ''}`}
                          onClick={() => setPropertiesTabFilter(key)}
                        >
                          <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">{label}</p>
                          <p className="text-4xl font-extrabold text-slate-800 mt-1">{count}</p>
                        </Card>
                      ))}
                    </div>
                  );
                })()}
                <h3 className="text-lg font-bold text-slate-800 mb-4">Active properties</h3>
                <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                  <span className="text-slate-500 text-sm">Shield Mode is always on for every property. Filter by monitored properties (all are ON) or use All.</span>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Shield Mode:</span>
                    <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
                      {(['all', 'on'] as const).map((f) => (
                        <button
                          key={f}
                          type="button"
                          onClick={() => setShieldFilter(f)}
                          className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${shieldFilter === f ? 'bg-slate-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                        >
                          {f === 'all' ? 'All' : 'Shield ON'}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {propertiesTabFilteredProps.length > 0 && propertiesTabFilter !== 'units' && (
                  <div className="mb-3 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setSelectedPropertyIds(
                        propertiesTabFilteredProps.every((p) => selectedPropertyIds.has(p.id))
                          ? new Set()
                          : new Set(propertiesTabFilteredProps.map((p) => p.id))
                      )}
                      className="text-sm text-slate-600 hover:text-slate-800 underline"
                    >
                      {propertiesTabFilteredProps.every((p) => selectedPropertyIds.has(p.id)) ? 'Select none' : 'Select all'}
                    </button>
                    <span className="text-slate-400">·</span>
                    <span className="text-sm text-slate-500">({propertiesTabFilteredProps.length} propert{propertiesTabFilteredProps.length === 1 ? 'y' : 'ies'} shown)</span>
                  </div>
                )}
                {selectedPropertyIds.size > 0 && (
                  <div className="mb-4 p-4 rounded-xl bg-slate-100 border border-slate-200 flex flex-wrap items-center justify-between gap-4">
                    <span className="text-sm font-medium text-slate-700">{selectedPropertyIds.size} propert{selectedPropertyIds.size === 1 ? 'y' : 'ies'} selected</span>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => setSelectedPropertyIds(new Set())}>Clear selection</Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={bulkShieldLoading}
                        onClick={async () => {
                          setBulkShieldLoading(true);
                          try {
                            const res = await dashboardApi.bulkShieldMode([...selectedPropertyIds], true);
                            notify('success', res.message || `Shield confirmed on for ${res.updated_count} propert${res.updated_count === 1 ? 'y' : 'ies'}.`);
                            setSelectedPropertyIds(new Set());
                            loadData();
                            window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to update Shield Mode.');
                          } finally {
                            setBulkShieldLoading(false);
                          }
                        }}
                      >
                        {bulkShieldLoading ? 'Updating…' : 'Ensure Shield ON (sync)'}
                      </Button>
                      {/*
                        DO NOT REMOVE — bulk Turn Shield OFF (restore if backend SHIELD_MODE_ALWAYS_ON is False).
                        <Button ... onClick={() => dashboardApi.bulkShieldMode([...selectedPropertyIds], false)}>Turn Shield OFF</Button>
                      */}
                    </div>
                  </div>
                )}
                {contextMode === 'business' && propertiesTabFilter === 'units' && (
                  <Card className="p-6 overflow-hidden">
                    {propertiesTabUnitsLoading ? (
                      <p className="text-slate-500 text-sm">Loading units…</p>
                    ) : propertiesTabUnitsList.length === 0 ? (
                      <p className="text-slate-500 text-sm">No units found.</p>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-slate-100 text-slate-600 uppercase text-xs font-semibold border-b border-slate-200">
                            <tr>
                              <th className="px-4 py-3">Property</th>
                              <th className="px-4 py-3">Unit</th>
                              <th className="px-4 py-3">Status</th>
                              <th className="px-4 py-3">Address</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {propertiesTabUnitsList.map((row) => (
                              <tr key={`${row.propertyId}-${row.unit.id}`} className="hover:bg-slate-50">
                                <td className="px-4 py-3 font-medium text-slate-800">{row.propertyName}</td>
                                <td className="px-4 py-3 text-slate-700">{row.unit.unit_label}</td>
                                <td className="px-4 py-3">
                                  <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                                    (row.unit.occupancy_status || '').toLowerCase() === 'occupied' ? 'bg-emerald-100 text-emerald-800' :
                                    (row.unit.occupancy_status || '').toLowerCase() === 'vacant' ? 'bg-sky-100 text-sky-800' : 'bg-slate-100 text-slate-700'
                                  }`}>
                                    {(row.unit.occupancy_status || 'vacant').toUpperCase()}
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-slate-600 truncate max-w-[200px]">{row.address}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </Card>
                )}
                {contextMode === 'business' && propertiesTabFilteredProps.length === 0 && propertiesTabFilter !== 'units' && (
                  <Card className="p-6">
                    <p className="text-slate-500 text-sm">No properties match this filter.</p>
                  </Card>
                )}
                {!(contextMode === 'business' && propertiesTabFilter === 'units') && (
                <div className="grid gap-6">
                {propertiesTabFilteredProps.map((prop) => {
                  const address = [prop.street, prop.city, prop.state, prop.zip_code].filter(Boolean).join(', ');
                  const displayName = prop.name || address || `Property #${prop.id}`;
                  // Business mode: use property status only (no guest data). Personal mode: can use stays for occupancy.
                  const activeStayForProp = contextMode === 'personal' ? activeStays.find((s) => s.property_id === prop.id) : null;
                  const isOccupied = (prop.occupancy_status || '').toLowerCase() === 'occupied';
                  const shieldStatus = isOccupied ? 'PASSIVE GUARD' : 'ACTIVE MONITORING';
                  const isSelected = selectedPropertyIds.has(prop.id);
                  const statusSummary = propertyStatusSummary(prop);
                  return (
                    <Card key={prop.id} className="p-6 border border-slate-200">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                        <div className="flex items-start gap-3 flex-shrink-0">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => {
                              e.stopPropagation();
                              setSelectedPropertyIds((prev) => {
                                const next = new Set(prev);
                                if (next.has(prop.id)) next.delete(prop.id);
                                else next.add(prop.id);
                                return next;
                              });
                            }}
                            className="mt-1 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                            aria-label={`Select ${displayName}`}
                          />
                        <button
                          type="button"
                          onClick={() => navigate(`property/${prop.id}`)}
                          className="min-w-0 flex-1 text-left hover:opacity-90 transition-opacity"
                        >
                          <div className="flex flex-wrap items-center gap-2 gap-y-1">
                            <h3 className="text-lg font-bold text-slate-800 truncate">{displayName}</h3>
                            {(() => {
                              const displayStatus = isOccupied ? (prop.is_multi_unit ? statusSummary.badgeText : 'OCCUPIED') : statusSummary.badgeText;
                              return (
                                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold uppercase ${
                                  statusSummary.badgeTone === 'occupied' ? 'bg-emerald-100 text-emerald-800' :
                                  statusSummary.badgeTone === 'vacant' ? 'bg-slate-200 text-slate-700' :
                                  statusSummary.badgeTone === 'unconfirmed' ? 'bg-amber-100 text-amber-800' :
                                  'bg-slate-100 text-slate-600'
                                }`}>
                                  <span className={`w-1.5 h-1.5 rounded-full ${
                                    statusSummary.badgeTone === 'occupied' ? 'bg-emerald-500' :
                                    statusSummary.badgeTone === 'vacant' ? 'bg-slate-400' :
                                    statusSummary.badgeTone === 'unconfirmed' ? 'bg-amber-500' : 'bg-slate-400'
                                  }`} />
                                  {displayStatus}
                                </span>
                              );
                            })()}
                          </div>
                          <p className="text-sm text-slate-600 mt-1 truncate">{address || '—'}</p>
                          <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
                            <span>Region: <span className="text-slate-600 font-medium">{prop.region_code}</span></span>
                            {(prop.property_type_label || prop.property_type) && (
                              <span>Type: <span className="text-slate-600 font-medium">{prop.property_type_label || prop.property_type}</span></span>
                            )}
                            {!prop.is_multi_unit && prop.bedrooms && (
                              <span>Bedrooms: <span className="text-slate-600 font-medium">{prop.bedrooms}</span></span>
                            )}
                            {contextMode === 'personal' && isOccupied && activeStayForProp && (
                              <span>
                                Stay end reminders: <span className={activeStayForProp.dead_mans_switch_enabled ? 'text-amber-600 font-medium' : 'text-slate-600 font-medium'}>
                                  {activeStayForProp.dead_mans_switch_enabled ? 'On' : 'Off'}
                                </span>
                              </span>
                            )}
                          </div>
                          <span className="inline-block mt-2 text-xs font-medium text-blue-400">View details →</span>
                        </button>
                        </div>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <Button variant="outline" onClick={() => navigate(`property/${prop.id}`)} className="px-4">
                            View & Edit
                          </Button>
                          {contextMode === 'business' && (
                            <Button
                              variant="ghost"
                              onClick={() => { setDeleteConfirmProperty(prop); setDeleteError(null); }}
                              className="px-4 text-red-600 hover:text-red-700 hover:bg-red-50"
                            >
                              Remove Property
                            </Button>
                          )}
                        </div>
                      </div>
                      {/* Occupancy status: VACANT | OCCUPIED | UNKNOWN | UNCONFIRMED */}
                      <div className="mt-6 pt-6 border-t border-slate-200 rounded-xl bg-slate-50/80 p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Occupancy status</p>
                        <div className="flex items-center gap-3 flex-wrap">
                          {(() => {
                            const displayStatus = isOccupied ? (prop.is_multi_unit ? statusSummary.badgeText : 'OCCUPIED') : statusSummary.badgeText;
                            return (
                          <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium ${
                            statusSummary.badgeTone === 'occupied' ? 'bg-emerald-100 text-emerald-800' :
                            statusSummary.badgeTone === 'vacant' ? 'bg-slate-200 text-slate-700' :
                            statusSummary.badgeTone === 'unconfirmed' ? 'bg-amber-100 text-amber-800' :
                            'bg-slate-100 text-slate-600'
                          }`}>
                            <span className={`w-2 h-2 rounded-full ${
                              statusSummary.badgeTone === 'occupied' ? 'bg-emerald-500' :
                              statusSummary.badgeTone === 'vacant' ? 'bg-slate-400' :
                              statusSummary.badgeTone === 'unconfirmed' ? 'bg-amber-500' : 'bg-slate-400'
                            }`} />
                            {displayStatus}
                          </span>
                            );
                          })()}
                          {prop.is_multi_unit && statusSummary.detailText ? (
                            <span className="text-sm text-slate-600">{statusSummary.detailText}</span>
                          ) : null}
                          {contextMode === 'personal' && isOccupied && activeStayForProp && (
                            <span className="text-sm text-slate-600">
                              Current guest: <span className="font-medium text-slate-800">{activeStayForProp.guest_name}</span>
                              {' · '}
                              Lease end: <span className="font-medium text-slate-800">{activeStayForProp.stay_end_date}</span>
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Primary residence</p>
                        <div className="flex flex-wrap items-center justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium text-slate-800">Show in Personal mode</p>
                            <p className="text-xs text-slate-500 mt-0.5">
                              Turn on to include this property when you use Personal mode (your home and guest invites).
                            </p>
                          </div>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={!!prop.owner_occupied}
                            aria-busy={primaryResidenceTogglingId === prop.id}
                            disabled={primaryResidenceTogglingId === prop.id}
                            onClick={async (e) => {
                              e.stopPropagation();
                              const next = !prop.owner_occupied;
                              setPrimaryResidenceTogglingId(prop.id);
                              try {
                                const updated = await propertiesApi.update(prop.id, { owner_occupied: next });
                                setProperties((list) =>
                                  list.map((p) => (p.id === prop.id ? mergePropertyAfterUpdate(p, updated) : p)),
                                );
                                dashboardApi
                                  .ownerPersonalModeUnits()
                                  .then((pm) =>
                                    setPersonalModeUnits((pm as { unit_ids: number[] }).unit_ids || []),
                                  )
                                  .catch(() => {});
                                notify(
                                  'success',
                                  next ? 'This property will appear in Personal mode.' : 'Removed from Personal mode.',
                                );
                                window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                              } catch (err) {
                                notify('error', (err as Error)?.message ?? 'Could not update primary residence.');
                              } finally {
                                setPrimaryResidenceTogglingId(null);
                              }
                            }}
                            className={`relative inline-flex h-7 w-12 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${
                              prop.owner_occupied ? 'bg-emerald-600' : 'bg-slate-200'
                            }`}
                          >
                            <span
                              className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow ring-0 transition-transform ${
                                prop.owner_occupied ? 'translate-x-5' : 'translate-x-0.5'
                              }`}
                            />
                          </button>
                        </div>
                      </div>

                      {/* CR-1a: Shield always on — DO NOT REMOVE legacy toggle block in git history / PropertyDetail comment. */}
                      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Shield Mode</p>
                        <div className="flex flex-wrap items-center gap-4">
                          <div className="flex items-center gap-2" aria-label="Shield Mode on">
                            <span className="relative inline-flex h-6 w-11 flex-shrink-0 rounded-full bg-emerald-600 border-2 border-transparent">
                              <span className="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 translate-x-5" />
                            </span>
                            <span className="text-sm font-medium text-slate-800">ON (always)</span>
                          </div>
                          <span className="text-sm text-slate-600">
                            Status: <span className="font-semibold text-slate-800">{shieldStatus}</span>
                          </span>
                          <span className="text-xs text-slate-400">Account plan: $10 per unit per month (7-day free trial for new accounts)</span>
                        </div>
                      </div>

                      {/* Property managers: visible in both personal and business; remove only in business */}
                      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                        <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Property managers</p>
                        {(propertyManagersMap[prop.id]?.length ?? 0) === 0 ? (
                          <p className="text-sm text-slate-500">No managers assigned. Invite from property details.</p>
                        ) : (
                          <ul className="space-y-2">
                            {(propertyManagersMap[prop.id] || []).map((m) => (
                              <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-slate-100 last:border-0">
                                <div>
                                  <p className="text-sm font-medium text-slate-800">{m.full_name || m.email}</p>
                                  <p className="text-xs text-slate-500">{m.email}</p>
                                  {m.has_resident_mode && m.resident_unit_label && (
                                    <>
                                      <p className="text-xs text-emerald-600 mt-0.5">On-site resident · Unit {m.resident_unit_label}</p>
                                    </>
                                  )}
                                </div>
                                {contextMode === 'business' && (
                                  <div className="flex items-center gap-2">
                                    {m.has_resident_mode && (
                                      <Button
                                        variant="outline"
                                        onClick={async () => {
                                          setRemovingResidentMode({ propertyId: prop.id, userId: m.user_id });
                                          try {
                                            await propertiesApi.removeManagerResidentMode(prop.id, m.user_id);
                                            notify('success', 'Manager removed as on-site resident. They remain assigned; that unit is now vacant.');
                                            const next = await propertiesApi.listAssignedManagers(prop.id);
                                            setPropertyManagersMap((prev) => ({ ...prev, [prop.id]: next }));
                                            window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                                          } catch (e) {
                                            notify('error', (e as Error)?.message ?? 'Failed.');
                                          } finally {
                                            setRemovingResidentMode(null);
                                          }
                                        }}
                                        disabled={(removingResidentMode?.propertyId === prop.id && removingResidentMode?.userId === m.user_id) || removingManager !== null}
                                      >
                                        {removingResidentMode?.propertyId === prop.id && removingResidentMode?.userId === m.user_id ? 'Removing…' : 'Remove as on-site resident'}
                                      </Button>
                                    )}
                                    <Button
                                      variant="ghost"
                                      onClick={async () => {
                                        setRemovingManager({ propertyId: prop.id, userId: m.user_id });
                                        try {
                                          await propertiesApi.removePropertyManager(prop.id, m.user_id);
                                          notify('success', 'Manager removed from property.');
                                          setPropertyManagersMap((prev) => ({
                                            ...prev,
                                            [prop.id]: (prev[prop.id] || []).filter((x) => x.user_id !== m.user_id),
                                          }));
                                          window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                                        } catch (e) {
                                          notify('error', (e as Error)?.message ?? 'Failed to remove manager.');
                                        } finally {
                                          setRemovingManager(null);
                                        }
                                      }}
                                      disabled={(removingManager?.propertyId === prop.id && removingManager?.userId === m.user_id) || removingResidentMode !== null}
                                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                                    >
                                      {removingManager?.propertyId === prop.id && removingManager?.userId === m.user_id ? 'Removing…' : 'Remove'}
                                    </Button>
                                  </div>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </Card>
                  );
                })}
                </div>
                )}
              </div>
              )}

              {/* Inactive properties */}
              {inactiveProperties.length > 0 && (
              <div>
                <h3 className="text-lg font-bold text-slate-800 mb-4">Inactive properties</h3>
                <p className="text-slate-500 text-sm mb-4">Removed from dashboard; not shown when creating an invite. Data is kept for logs. You can reactivate any time.</p>
                <div className="grid gap-6">
                  {inactiveProperties.map((prop) => {
                    const address = [prop.street, prop.city, prop.state, prop.zip_code].filter(Boolean).join(', ');
                    const displayName = prop.name || address || `Property #${prop.id}`;
                    const displayStatus = (prop.occupancy_status ?? 'vacant').toUpperCase();
                    return (
                      <Card key={prop.id} className="p-6 border border-slate-200 bg-slate-50/50">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2 gap-y-1">
                              <h3 className="text-lg font-bold text-slate-700 truncate">{displayName}</h3>
                              <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold uppercase ${
                                displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
                                displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
                                displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
                                'bg-slate-100 text-slate-600'
                              }`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${
                                  displayStatus === 'OCCUPIED' ? 'bg-emerald-500' :
                                  displayStatus === 'VACANT' ? 'bg-slate-400' :
                                  displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'
                                }`} />
                                {displayStatus}
                              </span>
                            </div>
                            <p className="text-sm text-slate-600 mt-1 truncate">{address || '—'}</p>
                            <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
                              <span>Region: <span className="text-slate-600 font-medium">{prop.region_code}</span></span>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-3 flex-shrink-0">
                            <Button variant="outline" onClick={() => navigate(`property/${prop.id}`)} className="px-4">
                              View
                            </Button>
                            <Button
                              variant="outline"
                              onClick={async () => {
                                try {
                                  await propertiesApi.reactivate(prop.id);
                                  notify('success', 'Property reactivated. It appears in Active properties and in the invite list again.');
                                  loadData();
                                  window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                                } catch (e) {
                                  notify('error', (e as Error)?.message ?? 'Failed to reactivate.');
                                }
                              }}
                              className="px-4"
                            >
                              Reactivate
                            </Button>
                          </div>
                        </div>
                      </Card>
                    );
                  })}
                </div>
              </div>
              )}
              </>
            )}
          </div>
        ) : activeTab === 'billing' ? (
          <div className="space-y-6">
            {paymentReturnMessage && (
              <div className={`flex items-center justify-between gap-4 p-4 rounded-xl text-sm ${paymentReturnIsError ? 'bg-red-50 border border-red-200 text-red-800' : 'bg-emerald-50 border border-emerald-200 text-emerald-800'}`}>
                <span>{paymentReturnMessage}</span>
                <button type="button" onClick={() => { setPaymentReturnMessage(null); setPaymentReturnIsError(false); }} className={paymentReturnIsError ? 'text-red-600 hover:text-red-800 font-medium shrink-0' : 'text-emerald-600 hover:text-emerald-800 font-medium shrink-0'} aria-label="Dismiss">Dismiss</button>
              </div>
            )}
            {!billingLoading && billing?.subscription_status === 'trialing' && billing.trial_days_remaining != null && billing.trial_end_at && (
              <div
                className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-950 shadow-sm"
                role="status"
              >
                <p className="font-semibold text-sky-900">Free trial active</p>
                <p className="mt-1 text-sky-900/90">
                  {billing.trial_days_remaining > 1
                    ? `${billing.trial_days_remaining} days left in your free trial.`
                    : billing.trial_days_remaining === 1
                      ? '1 day left in your free trial.'
                      : 'Your free trial ends today.'}{' '}
                  Billing is $10 per unit per month after the trial. Trial ends{' '}
                  <time dateTime={billing.trial_end_at}>
                    {formatDateTimeLocal(billing.trial_end_at)}
                  </time>
                  . Add a default payment method in Settings (Subscription & Billing) before the trial ends to avoid interruption.
                </p>
              </div>
            )}
            <Card className="p-6">
              <h3 className="text-lg font-bold text-slate-800 mb-2">Billing</h3>
              <p className="text-slate-500 text-sm mb-4">Invoices and payment history. You get a 7-day free trial when your subscription starts; after that, billing is $10 per unit per month. Billing activity is also recorded in Event ledger.</p>
              {billing && (billing.current_unit_count != null || billing.current_shield_count != null) && (
                <p className="text-slate-600 text-sm mb-4 p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <strong>Plan:</strong> $10 per unit per month after the trial.{' '}
                  <strong>Units on account:</strong> {billing.current_unit_count ?? 0} active
                  {(billing.current_shield_count ?? 0) > 0 && (
                    <> · Shield monitoring: {(billing.current_shield_count ?? 0)} propert{(billing.current_shield_count ?? 0) !== 1 ? 'ies' : 'y'}.</>
                  )}
                </p>
              )}
              {billingLoading ? (
                <p className="text-slate-500">Loading billing…</p>
              ) : (
                <>
                  <div className="mb-6">
                    <h4 className="text-sm font-bold text-slate-700 uppercase tracking-wider mb-3">Invoices</h4>
                    {(() => {
                      const displayInvoices = (billing?.invoices ?? []).filter((inv: BillingInvoiceView) => inv.status !== 'draft');
                      return !billing || displayInvoices.length === 0 ? (
                      <p className="text-slate-500 text-sm">No invoices yet. Stripe creates recurring invoices after your trial; one-off charges may appear if you pay via hosted invoice or the billing portal.</p>
                    ) : (
                      <div className="overflow-x-auto border border-slate-200 rounded-lg">
                        <table className="w-full text-left text-sm">
                          <thead className="bg-slate-100 text-slate-600 uppercase text-xs tracking-wider">
                            <tr>
                              <th className="px-4 py-3">Date</th>
                              <th className="px-4 py-3">Number</th>
                              <th className="px-4 py-3">Description</th>
                              <th className="px-4 py-3">Amount</th>
                              <th className="px-4 py-3">Status</th>
                              <th className="px-4 py-3">Action</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-200">
                            {displayInvoices.map((inv: BillingInvoiceView) => (
                              <tr key={inv.id} className="hover:bg-slate-50">
                                <td className="px-4 py-3 text-slate-600">{formatDateTimeLocal(inv.created)}</td>
                                <td className="px-4 py-3 font-mono text-slate-700">{inv.number ?? inv.id.slice(0, 12)}</td>
                                <td className="px-4 py-3 text-slate-600 max-w-xs truncate">{inv.description ?? '—'}</td>
                                <td className="px-4 py-3">${(inv.amount_due_cents / 100).toFixed(2)} {inv.currency.toUpperCase()}</td>
                                <td className="px-4 py-3">
                                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                                    inv.status === 'paid' ? 'bg-emerald-100 text-emerald-800' :
                                    inv.status === 'open' ? 'bg-amber-100 text-amber-800' :
                                    inv.status === 'past_due' ? 'bg-red-100 text-red-800' :
                                    inv.status === 'void' ? 'bg-slate-200 text-slate-600' :
                                    'bg-slate-100 text-slate-700'
                                  }`}>{inv.status === 'past_due' ? 'Payment failed' : inv.status}</span>
                                  {inv.status === 'past_due' && (
                                    <p className="text-xs text-red-600 mt-1">Update your payment method and try again.</p>
                                  )}
                                </td>
                                <td className="px-4 py-3">
                                  {inv.status === 'void' ? (
                                    <button
                                      type="button"
                                      onClick={() => setShowVoidInvoiceDialog(true)}
                                      className="text-blue-600 hover:underline"
                                    >
                                      Pay invoice
                                    </button>
                                  ) : inv.status !== 'paid' ? (
                                    inv.hosted_invoice_url ? (
                                      <a href={inv.hosted_invoice_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">Pay invoice</a>
                                    ) : (
                                      <button
                                        type="button"
                                        onClick={() => {
                                          dashboardApi
                                            .billingPortalSession()
                                            .then((data) => {
                                              window.location.href = data.url;
                                            })
                                            .catch(() => notify('error', 'Could not open payment page. Try again.'));
                                        }}
                                        className="text-blue-600 hover:underline disabled:opacity-50"
                                      >
                                        Pay invoice
                                      </button>
                                    )
                                  ) : inv.hosted_invoice_url ? (
                                    <a href={inv.hosted_invoice_url} target="_blank" rel="noopener noreferrer" className="text-slate-500 hover:underline">View</a>
                                  ) : null}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    );
                    })()}
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-700 uppercase tracking-wider mb-3">Payments</h4>
                    {!billing || billing.payments.length === 0 ? (
                      <p className="text-slate-500 text-sm">No payments yet.</p>
                    ) : (
                      <div className="overflow-x-auto border border-slate-200 rounded-lg">
                        <table className="w-full text-left text-sm">
                          <thead className="bg-slate-100 text-slate-600 uppercase text-xs tracking-wider">
                            <tr>
                              <th className="px-4 py-3">Paid at</th>
                              <th className="px-4 py-3">Description</th>
                              <th className="px-4 py-3">Amount</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-200">
                            {billing.payments.map((pay: BillingPaymentView) => (
                              <tr key={pay.invoice_id} className="hover:bg-slate-50">
                                <td className="px-4 py-3 text-slate-600">{formatDateTimeLocal(pay.paid_at)}</td>
                                <td className="px-4 py-3 text-slate-600 max-w-xs truncate">{pay.description ?? 'Payment'}</td>
                                <td className="px-4 py-3 font-medium">${(pay.amount_cents / 100).toFixed(2)} {pay.currency.toUpperCase()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </>
              )}
            </Card>
          </div>
        ) : activeTab === 'logs' ? (
          <div className="space-y-6">
            <Card className="p-6">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">From (local)</label>
                  <input
                    type="datetime-local"
                    value={logsFromTs}
                    onChange={(e) => setLogsFromTs(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">To (local)</label>
                  <input
                    type="datetime-local"
                    value={logsToTs}
                    onChange={(e) => setLogsToTs(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Category</label>
                  <select
                    value={logsCategory}
                    onChange={(e) => setLogsCategory(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="">All</option>
                    <option value="status_change">Status change</option>
                    <option value="shield_mode">Shield Mode</option>
                    <option value="dead_mans_switch">Stay end reminders</option>
                    <option value="guest_signature">Guest signature</option>
                    <option value="failed_attempt">Failed attempt</option>
                    <option value="billing">Billing</option>
                    <option value="tenant_assignment">Tenant assignment</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Search (title/message)</label>
                  <input
                    type="text"
                    placeholder="Search…"
                    value={logsSearch}
                    onChange={(e) => setLogsSearch(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <Button variant="primary" onClick={loadLogs} disabled={logsLoading} className="mb-4">
                {logsLoading ? 'Loading…' : 'Apply filters'}
              </Button>
            </Card>
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-slate-50">
                <h3 className="text-lg font-bold text-slate-800">Event ledger (append-only)</h3>
                <p className="text-slate-500 text-sm mt-1">Status changes, Shield Mode and stay end reminders on/off, guest signatures, payment and billing activity (invoices created, paid), and failed attempts are recorded. Use the category filter to view Shield Mode, stay end reminders, or Billing events. Records cannot be edited or deleted.</p>
              </div>
              <div className="overflow-x-auto">
                {logsLoading && logs.length === 0 ? (
                  <p className="p-8 text-slate-500 text-center">Loading logs…</p>
                ) : logs.length === 0 ? (
                  <p className="p-8 text-slate-500 text-center">No logs match your filters. Adjust filters and click Apply, or ensure you have property-related activity.</p>
                ) : (
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Time</th>
                        <th className="px-6 py-4">Category</th>
                        <th className="px-6 py-4">Title</th>
                        <th className="px-6 py-4">Property</th>
                        <th className="px-6 py-4">Actor</th>
                        <th className="px-6 py-4">Message</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {logs.map((entry) => (
                        <tr key={entry.id} className="hover:bg-slate-50">
                          <td className="px-6 py-3 text-slate-600 text-sm whitespace-nowrap">
                            {formatLedgerTimestamp(entry.created_at)}
                          </td>
                          <td className="px-6 py-3">
                            <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                              entry.category === 'failed_attempt' ? 'bg-red-100 text-red-800' :
                              entry.category === 'guest_signature' ? 'bg-emerald-100 text-emerald-800' :
                              entry.category === 'shield_mode' ? 'bg-violet-100 text-violet-800' :
                              entry.category === 'dead_mans_switch' ? 'bg-amber-100 text-amber-800' :
                              entry.category === 'billing' ? 'bg-slate-200 text-slate-800' :
                              'bg-sky-100 text-sky-800'
                            }`}>
                              {entry.category === 'shield_mode' ? 'Shield Mode' : entry.category === 'dead_mans_switch' ? 'Stay end reminders' : entry.category === 'billing' ? 'Billing' : entry.category.replace('_', ' ')}
                            </span>
                          </td>
                          <td className="px-6 py-3 font-medium text-slate-800">{entry.title}</td>
                          <td className="px-6 py-3 text-slate-600 text-sm">{entry.property_name ?? '—'}</td>
                          <td className="px-6 py-3 text-slate-600 text-sm">{entry.actor_email ?? '—'}</td>
                          <td className="px-6 py-3 text-slate-600 text-sm max-w-xs">
                            <span className="truncate block">{entry.message}</span>
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
                )}
              </div>
            </Card>
          </div>
        ) : activeTab === 'settings' ? (
          <div className="w-full">
            <Settings
              user={user}
              navigate={navigate}
              embedded
              onOpenBilling={() => setActiveTab('billing')}
              contextMode={contextMode}
              personalModeUnits={personalModeUnits}
              onContextModeChange={handleContextModeChange}
            />
          </div>
        ) : activeTab === 'help' ? (
          <div className="w-full">
            <HelpCenter navigate={navigate} embedded />
          </div>
        ) : (
          <>
            {contextMode === 'personal' ? (
              <>
                {/* Status Alert for Overstays (personal mode only) */}
                {firstOverstay && (
                  <div className="mb-8 p-6 rounded-2xl bg-red-50 border border-red-200 flex flex-col md:flex-row items-center justify-between gap-6">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 rounded-full bg-red-500/20 flex items-center justify-center text-red-600">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                      </div>
                      <div>
                        <h3 className="text-lg font-bold text-slate-800">Overstay Detected</h3>
                        <p className="text-red-700 text-sm">{firstOverstay.guest_name} has exceeded their authorized stay period in {firstOverstay.region_code}.</p>
                      </div>
                    </div>
                    <Button variant="danger" onClick={() => handleInitiateRemoval(firstOverstay)} className="whitespace-nowrap">Initiate Removal</Button>
                  </div>
                )}

                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-10">
                  <Card className="p-6 border-l-4 border-blue-500 hover:scale-[1.02] transition-transform cursor-pointer" onClick={() => setActiveTab('properties')}>
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Properties</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.length}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-green-500 hover:scale-[1.02] transition-transform cursor-pointer">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Guests</p>
                    <p className="text-4xl font-extrabold text-slate-800 mt-1">{activeCount}</p>
                  </Card>
                  <Card className="p-6 border-l-4 border-red-500 hover:scale-[1.02] transition-transform cursor-pointer">
                    <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Overstays</p>
                    <p className="text-4xl font-extrabold text-red-600 mt-1">{overstays.length}</p>
                  </Card>
                </div>

                <Card className="mb-10 overflow-hidden">
                  <div className="p-6 border-b border-slate-200 flex justify-between items-center bg-white/60 backdrop-blur-md">
                    <h3 className="text-xl font-bold text-slate-800">Guests</h3>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                        <tr>
                          <th className="px-6 py-4">Guest Name</th>
                          <th className="px-6 py-4">Property</th>
                          <th className="px-6 py-4">Days Left</th>
                          <th className="px-6 py-4">Status</th>
                          <th className="px-6 py-4 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-800">
                        {activeStays.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="px-6 py-12 text-center text-slate-500">No active stays. Invite a guest to get started.</td>
                          </tr>
                        ) : (
                          activeStays.map((stay) => {
                        const overstay = isOverstayed(stay.stay_end_date);
                        const dLeft = daysLeft(stay.stay_end_date);
                        const revoked = !!stay.revoked_at;
                        return (
                          <tr key={stay.stay_id} className="hover:bg-slate-50 transition-colors group">
                            <td className="px-6 py-5">
                              <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-xs">{stay.guest_name.charAt(0)}</div>
                                <span className="text-sm font-bold text-slate-800">{stay.guest_name}</span>
                              </div>
                            </td>
                            <td className="px-6 py-5 text-sm text-slate-600">{stay.property_name}</td>
                            <td className="px-6 py-5">
                              <span className={`text-sm font-bold ${revoked ? 'text-amber-600' : overstay ? 'text-red-600' : 'text-green-600'}`}>{revoked ? '—' : overstay ? 'EXPIRED' : `${dLeft}d`}</span>
                            </td>
                            <td className="px-6 py-5">
                              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest ${
                                revoked ? 'bg-amber-50 text-amber-700 border border-amber-500/20' : overstay ? 'bg-red-50 text-red-600 border border-red-500/20' : 'bg-green-50 text-green-700 border border-green-200'
                              }`}>
                                {revoked ? 'Revoked' : overstay ? 'Overstayed' : 'Active'}
                              </span>
                            </td>
                            <td className="px-6 py-5 text-right space-x-3">
                              {revoked ? (
                                <span className="text-xs text-slate-500">Revoked</span>
                              ) : overstay ? (
                                <Button variant="danger" onClick={() => handleInitiateRemoval(stay)} className="text-xs py-2">Remove</Button>
                              ) : (
                                <Button variant="ghost" onClick={() => handleRevokeClick(stay)} className="text-xs py-2 text-red-600 hover:text-red-700">Revoke</Button>
                              )}
                              <Button variant="outline" className="text-xs py-2" onClick={() => setDetailStay(stay)}>Details</Button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
              </>
            ) : (
              /* Business mode: property/unit status only, no guest data */
              <div className="space-y-8">
                <p className="text-slate-500 text-sm">Property and unit status. Switch to Personal mode to view guest invitations, stays, and overstays.</p>
                {(() => {
                  const totalUnits = properties.reduce((s, p) => s + (p.unit_count ?? 1), 0);
                  const occupiedUnitsCount = totalOccupiedUnitsAcrossProperties(properties);
                  const vacantUnitsCount = totalVacantUnitsAcrossProperties(properties);
                  const unknownCount = properties.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase())).length;
                  const shieldOnCount = properties.filter((p) => p.shield_mode_enabled).length;
                  const cards: { key: OverviewFilter; label: string; count: number; border: string }[] = [
                    { key: 'properties', label: 'Properties', count: properties.length, border: 'border-blue-500' },
                    { key: 'units', label: 'Units', count: totalUnits, border: 'border-indigo-500' },
                    { key: 'occupied', label: 'Occupied', count: occupiedUnitsCount, border: 'border-emerald-500' },
                    { key: 'vacant', label: 'Vacant', count: vacantUnitsCount, border: 'border-sky-500' },
                    { key: 'unknown', label: 'Unknown', count: unknownCount, border: 'border-slate-400' },
                    { key: 'shield_on', label: 'Shield On', count: shieldOnCount, border: 'border-amber-500' },
                  ];
                  return (
                    <>
                    <div className="grid md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-6">
                      {cards.map(({ key, label, count, border }) => (
                        <Card
                          key={key}
                          role="button"
                          className={`p-6 border-l-4 ${border} hover:scale-[1.02] transition-transform cursor-pointer ${overviewFilter === key ? 'ring-2 ring-slate-400 ring-offset-2' : ''}`}
                          onClick={() => setOverviewFilter(overviewFilter === key ? null : key)}
                        >
                          <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">{label}</p>
                          <p className="text-4xl font-extrabold text-slate-800 mt-1">{count}</p>
                        </Card>
                      ))}
                    </div>
                    <div className="mt-4 max-w-md">
                      <Card
                        role="button"
                        className="p-6 border-l-4 border-orange-500 hover:scale-[1.02] transition-transform cursor-pointer"
                        onClick={() => {
                          setOverviewFilter(null);
                          setActiveTab('pending-tenants');
                          navigate('dashboard/pending-tenants');
                        }}
                      >
                        <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Pending</p>
                        <p className="text-4xl font-extrabold text-slate-800 mt-1">{pendingTenantCount}</p>
                        <p className="text-xs text-slate-500 mt-2">Tenants from CSV or invites who have not registered yet</p>
                      </Card>
                    </div>
                    </>
                  );
                })()}
                <h3 className="text-lg font-bold text-slate-800">Property status overview</h3>
                {overviewFilter == null ? (
                  <Card className="p-6">
                    <p className="text-slate-600 text-sm">Click a card above to see the list of properties or units. View full property details in the Properties tab.</p>
                    <Button variant="outline" onClick={() => setActiveTab('properties')} className="mt-4">View Properties</Button>
                  </Card>
                ) : overviewFilter === 'units' ? (
                  <Card className="p-6 overflow-hidden">
                    {unitsListLoading ? (
                      <p className="text-slate-500 text-sm">Loading units…</p>
                    ) : allUnitsList.length === 0 ? (
                      <p className="text-slate-500 text-sm">No units found.</p>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-slate-100 text-slate-600 uppercase text-xs font-semibold border-b border-slate-200">
                            <tr>
                              <th className="px-4 py-3">Property</th>
                              <th className="px-4 py-3">Unit</th>
                              <th className="px-4 py-3">Status</th>
                              <th className="px-4 py-3">Address</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {allUnitsList.map((row) => (
                              <tr key={`${row.propertyId}-${row.unit.id}`} className="hover:bg-slate-50">
                                <td className="px-4 py-3 font-medium text-slate-800">{row.propertyName}</td>
                                <td className="px-4 py-3 text-slate-700">{row.unit.unit_label}</td>
                                <td className="px-4 py-3">
                                  <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                                    (row.unit.occupancy_status || '').toLowerCase() === 'occupied' ? 'bg-emerald-100 text-emerald-800' :
                                    (row.unit.occupancy_status || '').toLowerCase() === 'vacant' ? 'bg-sky-100 text-sky-800' : 'bg-slate-100 text-slate-700'
                                  }`}>
                                    {(row.unit.occupancy_status || 'vacant').toUpperCase()}
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-slate-600 truncate max-w-[200px]">{row.address}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </Card>
                ) : (
                  (() => {
                    const filtered =
                      overviewFilter === 'properties' ? properties :
                      overviewFilter === 'occupied' ? properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'occupied') :
                      overviewFilter === 'vacant' ? properties.filter((p) => (p.occupancy_status || '').toLowerCase() === 'vacant') :
                      overviewFilter === 'unknown' ? properties.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase())) :
                      properties.filter((p) => p.shield_mode_enabled);
                    return (
                      <Card className="p-6 overflow-hidden">
                        {filtered.length === 0 ? (
                          <p className="text-slate-500 text-sm">No properties match this filter.</p>
                        ) : (
                          <div className="overflow-x-auto">
                            <table className="w-full text-sm text-left">
                              <thead className="bg-slate-100 text-slate-600 uppercase text-xs font-semibold border-b border-slate-200">
                                <tr>
                                  <th className="px-4 py-3">Property</th>
                                  <th className="px-4 py-3">Address</th>
                                  <th className="px-4 py-3">Status</th>
                                  <th className="px-4 py-3">Shield</th>
                                  <th className="px-4 py-3"></th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-100">
                                {filtered.map((p) => {
                                  const addr = [p.street, p.city, p.state, p.zip_code].filter(Boolean).join(', ');
                                  const status = (p.occupancy_status || 'vacant').toUpperCase();
                                  return (
                                    <tr key={p.id} className="hover:bg-slate-50">
                                      <td className="px-4 py-3 font-medium text-slate-800">{p.name || addr || `Property #${p.id}`}</td>
                                      <td className="px-4 py-3 text-slate-600 truncate max-w-[220px]">{addr || '—'}</td>
                                      <td className="px-4 py-3">
                                        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                                          status === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' : status === 'VACANT' ? 'bg-sky-100 text-sky-800' : 'bg-slate-100 text-slate-700'
                                        }`}>{status}</span>
                                      </td>
                                      <td className="px-4 py-3">{p.shield_mode_enabled ? 'On' : 'Off'}</td>
                                      <td className="px-4 py-3">
                                        <Button variant="outline" size="sm" onClick={() => navigate(`property/${p.id}`)}>View</Button>
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </Card>
                    );
                  })()
                )}
              </div>
            )}
          </>
        )}
      </main>

      {/* Bulk upload rules modal (opened by info icon) */}
      <Modal
        open={showBulkUploadRulesModal}
        title="Bulk upload rules"
        onClose={() => setShowBulkUploadRulesModal(false)}
        className="max-w-lg"
      >
        <div className="px-6 py-4 space-y-3 text-slate-600 text-sm">
          <p><strong>Required:</strong> <code className="bg-slate-100 px-1 rounded">Address</code>, <code className="bg-slate-100 px-1 rounded">City</code>, <code className="bg-slate-100 px-1 rounded">State</code>, <code className="bg-slate-100 px-1 rounded">Zip</code>, <code className="bg-slate-100 px-1 rounded">Occupied</code> (YES/NO). If Occupied=YES: <code className="bg-slate-100 px-1 rounded">Tenant Name</code>, <code className="bg-slate-100 px-1 rounded">Lease Start</code>, <code className="bg-slate-100 px-1 rounded">Lease End</code>.</p>
          <p><strong>Shared lease (optional):</strong> Add <code className="bg-slate-100 px-1 rounded">Tenant 2 Name</code> / <code className="bg-slate-100 px-1 rounded">Tenant 2 Email</code> through <code className="bg-slate-100 px-1 rounded">Tenant 12 Name</code> / <code className="bg-slate-100 px-1 rounded">Tenant 12 Email</code> on the <strong>same row</strong> as the primary tenant. Each extra name creates a co-tenant invite on the same unit and lease window (same behavior as “Multiple co-tenants” in the dashboard). Duplicate names on one row are rejected; emails are validated when present.</p>
          <p><strong>Property details (optional):</strong> <code className="bg-slate-100 px-1 rounded">property_name</code>, <code className="bg-slate-100 px-1 rounded">property_type</code> (house, apartment, condo, townhouse, duplex, triplex, quadplex), <code className="bg-slate-100 px-1 rounded">bedrooms</code> (for house/condo), <code className="bg-slate-100 px-1 rounded">units</code> (for apartment/duplex/triplex/quadplex), <code className="bg-slate-100 px-1 rounded">primary_residence_unit</code> (unit number 1, 2, … if owner lives there), <code className="bg-slate-100 px-1 rounded">occupied_unit</code> (which unit is occupied, for multi-unit with Occupied=YES), <code className="bg-slate-100 px-1 rounded">Unit No</code>, <code className="bg-slate-100 px-1 rounded">Shield Mode</code>, <code className="bg-slate-100 px-1 rounded">is_primary_residence</code>, <code className="bg-slate-100 px-1 rounded">tax_id</code>, <code className="bg-slate-100 px-1 rounded">apn</code>.</p>
          <p>Existing properties (same street, city, state) are updated only when values change. Empty optional cells keep existing values.</p>
          <p>If the upload fails partway, rows before the failure are saved.</p>
        </div>
      </Modal>

      {/* Bulk upload modal */}
      <Modal
        open={showBulkUploadModal}
        title="Upload properties in bulk"
        onClose={() => !bulkUploading && setShowBulkUploadModal(false)}
        className="max-w-lg"
      >
        <div className="px-6 py-4 space-y-4">
          <p className="text-slate-600 text-sm">
            Use a CSV with: <strong>Required:</strong> <code className="bg-slate-100 px-1 rounded">Address</code>, <code className="bg-slate-100 px-1 rounded">City</code>, <code className="bg-slate-100 px-1 rounded">State</code>, <code className="bg-slate-100 px-1 rounded">Zip</code>, <code className="bg-slate-100 px-1 rounded">Occupied</code> (YES/NO). <strong>If Occupied=YES:</strong> <code className="bg-slate-100 px-1 rounded">Tenant Name</code>, <code className="bg-slate-100 px-1 rounded">Lease Start</code>, <code className="bg-slate-100 px-1 rounded">Lease End</code>. <strong>Optional — shared lease on one row:</strong> <code className="bg-slate-100 px-1 rounded">Tenant 2 Name</code>, <code className="bg-slate-100 px-1 rounded">Tenant 2 Email</code>, … up to <code className="bg-slate-100 px-1 rounded">Tenant 12</code> (same unit and dates as the primary tenant). <strong>Other optional columns:</strong> <code className="bg-slate-100 px-1 rounded">Unit No</code>, <code className="bg-slate-100 px-1 rounded">Shield Mode</code> (YES/NO, default NO), <code className="bg-slate-100 px-1 rounded">Tax ID</code>, <code className="bg-slate-100 px-1 rounded">APN</code>.
          </p>
          <p className="text-xs text-slate-500">
            Occupied=YES: property token is active, primary tenant invite is created (pending until they register), plus one co-tenant invite per extra name on the row. Occupied=NO: token stays Pending, status VACANT. Shield Mode is always on for all properties (not a separate per-property subscription charge). Subscription billing is $10 per unit per month after your free trial. Existing properties (same address, city, state) are updated when values change.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={() => {
                const header =
                  'Address,Unit No,City,State,Zip,Occupied,Tenant Name,Lease Start,Lease End,Tenant 2 Name,Tenant 2 Email,Tenant 3 Name,Tenant 3 Email,Property Name,Property Type,Units,Bedrooms,Primary Residence Unit,Occupied Unit,Shield Mode,Tax ID,APN';
                const exampleOccupied =
                  '123 Ocean Ave,,Miami,FL,33139,YES,Jane Doe,2025-01-01,2025-12-31,John Partner,john.partner@example.com,,,Miami Beach Condo,house,,3,,,NO,,';
                const exampleVacant = '456 Oak St,,Austin,TX,78701,NO,,,,,,Astro Apartments,apartment,12,,1,,NO,,';
                const blob = new Blob([header + '\n' + exampleOccupied + '\n' + exampleVacant], { type: 'text/csv' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'properties_template.csv';
                a.click();
                URL.revokeObjectURL(a.href);
              }}
            >
              Download CSV template
            </Button>
            <Button
              variant="primary"
              disabled={bulkUploading}
              onClick={() => bulkUploadFileInputRef.current?.click()}
            >
              Choose CSV file
            </Button>
            <input
              ref={bulkUploadFileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (!file) return;
                setShowBulkUploadModal(false);
                setBulkUploading(true);
                setBulkProgress({ processed: 0, total: 0 });
                try {
                  const result = await propertiesApi.bulkUpload(file, (processed, total) => {
                    setBulkProgress({ processed, total });
                  });
                  setBulkUploadResult(result);
                  loadData();
                  window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                  const created = result.created ?? 0;
                  const updated = result.updated ?? 0;
                  const unitsCreated = (result as any).units_created ?? 0;
                  if (created > 0 || updated > 0) {
                    notify('success', result.failed_from_row == null
                      ? `${created} propert${created === 1 ? 'y' : 'ies'} created, ${updated} updated, ${unitsCreated} unit${unitsCreated === 1 ? '' : 's'} added.`
                      : `Uploaded ${created} created, ${updated} updated, ${unitsCreated} unit${unitsCreated === 1 ? '' : 's'} added; some rows failed.`);
                  }
                } catch (err) {
                  notify('error', (err as Error)?.message ?? 'Bulk upload failed.');
                } finally {
                  setBulkUploading(false);
                }
              }}
            />
          </div>
        </div>
      </Modal>

      {/* Bulk upload result modal */}
      <Modal
        open={bulkUploadResult !== null}
        title={bulkUploadResult?.failed_from_row == null ? 'Bulk upload complete' : 'Bulk upload partially completed'}
        onClose={() => setBulkUploadResult(null)}
        className="max-w-md"
      >
        <div className="px-6 py-4 space-y-4">
          {bulkUploadResult != null && (
            bulkUploadResult.failed_from_row == null ? (
              <p className="text-slate-600 text-sm">
                <strong>{bulkUploadResult.created}</strong> propert{bulkUploadResult.created === 1 ? 'y' : 'ies'} created, <strong>{bulkUploadResult.updated}</strong> updated, <strong>{(bulkUploadResult as any).units_created ?? 0}</strong> unit{((bulkUploadResult as any).units_created ?? 0) === 1 ? '' : 's'} added.
              </p>
            ) : bulkUploadResult.created === 0 && bulkUploadResult.updated === 0 ? (
              <p className="text-slate-600 text-sm">
                No properties were uploaded. Row <strong>{bulkUploadResult.failed_from_row}</strong>: {bulkUploadResult.failure_reason ?? 'Unknown error.'}
              </p>
            ) : (
              <p className="text-slate-600 text-sm">
                Properties until row <strong>{bulkUploadResult.failed_from_row - 1}</strong> were uploaded successfully (<strong>{bulkUploadResult.created}</strong> created, <strong>{bulkUploadResult.updated}</strong> updated). The rest failed from row <strong>{bulkUploadResult.failed_from_row}</strong>: {bulkUploadResult.failure_reason ?? 'Unknown error.'}
              </p>
            )
          )}
          <Button onClick={() => setBulkUploadResult(null)}>Done</Button>
        </div>
      </Modal>

      {/* Void invoice: cannot be paid; direct user to contact support */}
      <Modal
        open={showVoidInvoiceDialog}
        title="This invoice cannot be paid"
        onClose={() => setShowVoidInvoiceDialog(false)}
        className="max-w-md"
      >
        <div className="px-6 py-4 space-y-4">
          <p className="text-slate-600 text-sm">
            This invoice is void and cannot be paid. Please contact us at{' '}
            <a href={supportMailtoHref('Void invoice')} className="text-[#6B90F2] font-medium hover:underline break-all">
              {SUPPORT_EMAIL}
            </a>
            .
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="primary"
              onClick={() => {
                setShowVoidInvoiceDialog(false);
                window.location.href = supportMailtoHref('Void invoice');
              }}
            >
              Email support
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setShowVoidInvoiceDialog(false);
                navigate('help');
              }}
            >
              Help Center
            </Button>
            <Button variant="outline" onClick={() => setShowVoidInvoiceDialog(false)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* Progress modal while bulk upload is processing */}
      <Modal open={bulkUploading} title="Uploading properties…" onClose={() => {}} className="max-w-md">
        <div className="px-6 py-5 space-y-4">
          {bulkProgress.total > 0 ? (
            <>
              <div className="w-full bg-slate-200 rounded-full h-3 overflow-hidden">
                <div
                  className="bg-blue-600 h-3 rounded-full transition-all duration-300 ease-out"
                  style={{ width: `${Math.round((bulkProgress.processed / bulkProgress.total) * 100)}%` }}
                />
              </div>
              <p className="text-sm text-slate-600 text-center">
                {bulkProgress.processed} of {bulkProgress.total} rows processed ({Math.round((bulkProgress.processed / bulkProgress.total) * 100)}%)
              </p>
            </>
          ) : (
            <>
              <div className="w-full bg-slate-200 rounded-full h-3 overflow-hidden">
                <div className="bg-blue-600 h-3 rounded-full w-1/6 animate-pulse" />
              </div>
              <p className="text-sm text-slate-500 text-center">Preparing upload…</p>
            </>
          )}
          <p className="text-xs text-slate-400 text-center">Please don't close this page.</p>
        </div>
      </Modal>

      {/* Remove property (soft-delete) confirmation modal */}
      {deleteConfirmProperty && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => { setDeleteConfirmProperty(null); setDeleteError(null); }} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6 border-b border-slate-200">
                <h3 className="text-lg font-bold text-slate-800">Remove Property</h3>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-slate-600 text-sm">
                  Remove <span className="font-bold text-slate-800">{deleteConfirmProperty.name || [deleteConfirmProperty.street, deleteConfirmProperty.city].filter(Boolean).join(', ')}</span> from your dashboard? You can do this even if a guest stay or tenant lease is still on file — nothing is deleted; stays, leases, and the event ledger stay available as history. The property will move to <strong>Inactive properties</strong> and will not appear when creating an invite. You can reactivate it anytime.
                </p>
                {deleteError && <p className="text-sm text-red-600">{deleteError}</p>}
                <div className="flex gap-3">
                  <Button variant="outline" onClick={() => { setDeleteConfirmProperty(null); setDeleteError(null); }} className="flex-1">Cancel</Button>
                  <Button
                    variant="danger"
                    className="flex-1"
                    onClick={async () => {
                      try {
                        await propertiesApi.delete(deleteConfirmProperty.id);
                        setDeleteConfirmProperty(null);
                        setDeleteError(null);
                        notify('success', 'Property removed from dashboard. It has been moved to Inactive properties.');
                        loadData();
                        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                      } catch (e) {
                        const msg = (e as Error)?.message ?? 'Failed to remove property.';
                        setDeleteError(msg);
                        notify('error', msg);
                      }
                    }}
                  >
                    Remove Property
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Guest details modal */}
      {detailStay && (() => {
        const ds = detailStay;
        const revoked = !!ds.revoked_at;
        const overstay = isOverstayed(ds.stay_end_date);
        const completed = !!ds.checked_out_at;
        const cancelled = !!ds.cancelled_at;
        const statusLabel = completed ? 'Completed' : cancelled ? 'Cancelled' : revoked ? 'Revoked' : overstay ? 'Overstayed' : 'Active';
        const statusClass = completed ? 'bg-slate-100 text-slate-600' : cancelled ? 'bg-slate-100 text-slate-500' : revoked ? 'bg-amber-50 text-amber-700' : overstay ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-700';
        const tokenLabel = ds.token_state === 'BURNED' ? 'Active' : ds.token_state === 'STAGED' ? 'Pending' : ds.token_state === 'REVOKED' ? 'Revoked' : ds.token_state === 'EXPIRED' ? 'Expired' : ds.token_state ?? '—';
        return (
          <Modal open onClose={() => setDetailStay(null)} title="Guest Authorization Details" className="max-w-lg">
            <div className="p-6 space-y-5">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-lg">{ds.guest_name.charAt(0)}</div>
                <div>
                  <p className="text-lg font-bold text-slate-800">{ds.guest_name}</p>
                  <p className="text-sm text-slate-500">Stay #{ds.stay_id}</p>
                </div>
                <span className={`ml-auto px-3 py-1 rounded-full text-xs font-bold uppercase tracking-widest ${statusClass}`}>{statusLabel}</span>
              </div>

              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Property</p>
                  <p className="text-slate-800 font-medium">{ds.property_name}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Region</p>
                  <p className="text-slate-800 font-medium">{ds.region_code}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Authorization Start</p>
                  <p className="text-slate-800 font-medium">{ds.stay_start_date}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Authorization End</p>
                  <p className="text-slate-800 font-medium">{ds.stay_end_date}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Days Remaining</p>
                  <p className="text-slate-800 font-medium">{completed || cancelled ? '—' : revoked ? '—' : overstay ? 'Expired' : `${daysLeft(ds.stay_end_date)} day(s)`}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Token Status</p>
                  <p className="text-slate-800 font-medium">{tokenLabel}</p>
                </div>
                {ds.invite_id && (
                  <div className="col-span-2">
                    <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Invite ID</p>
                    <p className="text-slate-800 font-mono text-xs">{ds.invite_id}</p>
                  </div>
                )}
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Risk Level</p>
                  <p className={`font-medium ${ds.risk_indicator === 'high' ? 'text-red-600' : ds.risk_indicator === 'medium' ? 'text-amber-600' : 'text-green-600'}`}>{ds.risk_indicator.charAt(0).toUpperCase() + ds.risk_indicator.slice(1)}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Classification</p>
                  <p className="text-slate-800 font-medium">{ds.legal_classification === 'tenant_risk' ? 'Tenant risk' : ds.legal_classification.charAt(0).toUpperCase() + ds.legal_classification.slice(1)}</p>
                </div>
                {ds.revoked_at && (
                  <div className="col-span-2">
                    <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Revoked At</p>
                    <p className="text-amber-700 font-medium">{formatDateTimeLocal(ds.revoked_at)}</p>
                  </div>
                )}
                {ds.applicable_laws.length > 0 && (
                  <div className="col-span-2">
                    <p className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">Applicable Laws</p>
                    <p className="text-slate-700 text-xs">{ds.applicable_laws.join(', ')}</p>
                  </div>
                )}
              </div>

              <div className="flex justify-end pt-2">
                <Button variant="outline" onClick={() => setDetailStay(null)}>Close</Button>
              </div>
            </div>
          </Modal>
        );
      })()}

      {/* Revoke confirmation modal */}
      {revokeConfirmStay && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setRevokeConfirmStay(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6 border-b border-slate-200">
                <h3 className="text-lg font-bold text-slate-800">Revoke stay authorization</h3>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-slate-600 text-sm">
                  Revoking <span className="font-bold text-slate-800">{revokeConfirmStay.guest_name}</span> will trigger a 12-hour vacate notice. Proceed?
                </p>
                <div className="flex gap-3">
                  <Button variant="outline" onClick={() => setRevokeConfirmStay(null)} className="flex-1" disabled={revokeLoading}>Cancel</Button>
                  <Button variant="danger" onClick={handleRevokeConfirm} className="flex-1" disabled={revokeLoading}>{revokeLoading ? 'Revoking…' : 'Proceed'}</Button>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Revoke success modal */}
      {revokeSuccessGuest && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setRevokeSuccessGuest(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-md">
              <div className="p-6">
                <p className="text-green-600 font-medium mb-4">Revocation successful. Audit trail updated.</p>
                <Button onClick={() => setRevokeSuccessGuest(null)}>Done</Button>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Initiate Removal modal */}
      {packetModalStay && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => !removalLoading && setPacketModalStay(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-lg">
              <div className="p-6 border-b border-slate-200 flex items-center justify-between">
                <h3 className="text-lg font-bold text-red-700">Initiate Removal</h3>
                <button onClick={() => !removalLoading && setPacketModalStay(null)} className="text-slate-600 hover:text-slate-800" disabled={removalLoading}>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-sm text-slate-600">
                  You are about to initiate formal removal for <span className="font-bold text-slate-800">{packetModalStay.guest_name}</span> who is in overstay.
                </p>
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-2">
                  <p className="text-sm font-bold text-red-800">This action will:</p>
                  <ul className="text-sm text-red-700 list-disc list-inside space-y-1">
                    <li>Revoke the guest's stay authorization (access disabled)</li>
                    <li>Send removal notice email to the guest</li>
                    <li>Send confirmation email to you</li>
                    <li>Log all actions in the audit trail</li>
                  </ul>
                </div>
                <div className="text-sm">
                  <p className="text-slate-500 mb-1">Property</p>
                  <p className="text-slate-800">{packetModalStay.property_name}</p>
                </div>
                <div className="text-sm">
                  <p className="text-slate-500 mb-1">Jurisdiction</p>
                  <p className="text-slate-800 font-mono">{packetModalStay.region_code}</p>
                </div>
                <div className="flex gap-3 pt-2">
                  <Button variant="danger" onClick={handleRemovalConfirm} disabled={removalLoading} className="flex-1">
                    {removalLoading ? 'Processing...' : 'Confirm Removal'}
                  </Button>
                  <Button variant="outline" onClick={() => setPacketModalStay(null)} disabled={removalLoading}>
                    Cancel
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Full log message modal */}
      {logMessageModalEntry && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setLogMessageModalEntry(null)} aria-hidden="true" />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="log-message-title">
            <Card className="w-full max-w-lg max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
              <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                <h3 id="log-message-title" className="text-lg font-bold text-slate-800">
                  Full message — {logMessageModalEntry.title}
                </h3>
                <button
                  type="button"
                  onClick={() => setLogMessageModalEntry(null)}
                  className="text-slate-500 hover:text-slate-700 p-1 rounded focus:outline-none focus:ring-2 focus:ring-sky-500"
                  aria-label="Close"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
              <div className="p-4 overflow-y-auto flex-1">
                <p className="text-slate-700 text-sm whitespace-pre-wrap break-words">{logMessageModalEntry.message}</p>
              </div>
              <div className="p-4 border-t border-slate-200">
                <Button variant="outline" onClick={() => setLogMessageModalEntry(null)}>Close</Button>
              </div>
            </Card>
          </div>
        </>
      )}

      {/* Verify with QR code modal – opens #check with token pre-filled */}
      {showVerifyQRModal && verifyQRInviteId && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-sm w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200 relative">
            <button type="button" onClick={() => { setShowVerifyQRModal(false); setVerifyQRInviteId(null); setVerifyQRCopyToast(null); }} className="absolute top-4 right-4 text-slate-400 hover:text-slate-700">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1 text-center">Verify with QR code</h3>
            <p className="text-slate-500 text-sm mb-4 text-center">Scan to open the Verify page with this invite&apos;s token pre-filled.</p>
            <div className="flex justify-center mb-4">
              <div className="bg-slate-50 p-4 rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(`${typeof window !== 'undefined' ? window.location.origin : ''}/#check?token=${encodeURIComponent(verifyQRInviteId)}`)}`}
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
                onClick={() => window.open(`${typeof window !== 'undefined' ? window.location.origin : ''}/#check?token=${encodeURIComponent(verifyQRInviteId)}`, '_blank', 'noopener,noreferrer')}
              >
                Open verify page
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={async () => {
                  const url = `${typeof window !== 'undefined' ? window.location.origin : ''}/#check?token=${encodeURIComponent(verifyQRInviteId)}`;
                  const ok = await copyToClipboard(url);
                  setVerifyQRCopyToast(ok ? 'Verify link copied.' : 'Could not copy.');
                  setTimeout(() => setVerifyQRCopyToast(null), 3000);
                }}
              >
                Copy verify link
              </Button>
            </div>
            {verifyQRCopyToast && (
              <p className={`text-sm text-center mt-2 ${verifyQRCopyToast.startsWith('Verify link') ? 'text-emerald-600' : 'text-amber-600'}`}>
                {verifyQRCopyToast}
              </p>
            )}
          </div>
        </div>
      )}

      <SendTenantInviteEmailModal
        open={!!sendEmailTenant}
        tenant={sendEmailTenant}
        onClose={() => setSendEmailTenant(null)}
        notify={notify}
        onSent={() => {
          loadData();
          window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
        }}
      />

      <ExtendTenantLeaseModal
        open={!!leaseExtensionTenant}
        tenant={leaseExtensionTenant}
        onClose={() => setLeaseExtensionTenant(null)}
        notify={notify}
        onSuccess={() => {
          loadData();
          window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
        }}
      />

      <InviteTenantModal
        open={showInviteTenantModal}
        onClose={() => setShowInviteTenantModal(false)}
        properties={properties.map((p) => ({ id: p.id, name: p.name, street: p.street, address: p.address }))}
        getUnits={(propertyId) => propertiesApi.getUnits(propertyId).then((u) => u.filter((x) => x.id >= 0))}
        createInvitation={async (params) => {
          const unitId = params.unitId ?? 0;
          const body = {
            tenant_name: params.tenant_name,
            tenant_email: params.tenant_email,
            lease_start_date: params.lease_start_date,
            lease_end_date: params.lease_end_date,
            shared_lease: params.shared_lease,
          };
          return unitId > 0
            ? propertiesApi.inviteTenant(unitId, body)
            : propertiesApi.inviteTenantForProperty(params.propertyId, body);
        }}
        notify={notify}
        onSuccess={() => { loadData(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }}
        guestInviteUrlIsDemo={Boolean(user?.is_demo)}
      />

      <InviteGuestModal
        open={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        user={user}
        setLoading={setLoadingWrapper}
        notify={notify}
        onSuccess={() => { loadData(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }}
        navigate={navigate}
      />
    </div>
  );
};

export default OwnerDashboard;
