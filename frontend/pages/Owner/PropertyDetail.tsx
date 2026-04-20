
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, Button, Input, Modal, ErrorModal } from '../../components/UI';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import { UserSession } from '../../types';
import { JURISDICTION_RULES } from '../../services/jleService';
import { propertiesApi, dashboardApi, APP_ORIGIN, buildGuestInviteUrl, emitPropertiesChanged, onPropertiesChanged, getContextMode, setContextMode, type Property, type OwnerStayView, type OwnerTenantView, type OwnerAuditLogEntry, type BillingResponse } from '../../services/api';
import { ModeSwitcher } from '../../components/ModeSwitcher';
import { DASHBOARD_ALERTS_REFRESH_EVENT } from '../../components/DashboardAlertsPanel';
import { InactivePropertyBanner } from '../../components/InactivePropertyBanner';
import { copyToClipboard } from '../../utils/clipboard';
import { addCalendarYears, getTodayLocal, formatStayDuration, formatCalendarDate, formatDateTimeLocal, formatLedgerTimestamp, parseForDisplay } from '../../utils/dateUtils';
import { toUserFriendlyInvitationError } from '../../utils/invitationErrors';
import { tenantsPoolForUnitCard, groupOwnerTenantsByLeaseCohort, formatOwnerTenantGroupNames } from '../../utils/leaseCohortGroups';
import { validateCoTenantRows, type CoTenantInviteRow } from '../../utils/inviteTenantBatch';

// Import city data
import US_CITIES_DATA from '@/data/us-cities.json';

const US_CITIES = US_CITIES_DATA as Record<string, string[]>;

const US_STATES = [
  { value: 'AL', label: 'Alabama' }, { value: 'AK', label: 'Alaska' }, { value: 'AZ', label: 'Arizona' },
  { value: 'AR', label: 'Arkansas' }, { value: 'CA', label: 'California' }, { value: 'CO', label: 'Colorado' },
  { value: 'CT', label: 'Connecticut' }, { value: 'DE', label: 'Delaware' }, { value: 'FL', label: 'Florida' },
  { value: 'GA', label: 'Georgia' }, { value: 'HI', label: 'Hawaii' }, { value: 'ID', label: 'Idaho' },
  { value: 'IL', label: 'Illinois' }, { value: 'IN', label: 'Indiana' }, { value: 'IA', label: 'Iowa' },
  { value: 'KS', label: 'Kansas' }, { value: 'KY', label: 'Kentucky' }, { value: 'LA', label: 'Louisiana' },
  { value: 'ME', label: 'Maine' }, { value: 'MD', label: 'Maryland' }, { value: 'MA', label: 'Massachusetts' },
  { value: 'MI', label: 'Michigan' }, { value: 'MN', label: 'Minnesota' }, { value: 'MS', label: 'Mississippi' },
  { value: 'MO', label: 'Missouri' }, { value: 'MT', label: 'Montana' }, { value: 'NE', label: 'Nebraska' },
  { value: 'NV', label: 'Nevada' }, { value: 'NH', label: 'New Hampshire' }, { value: 'NJ', label: 'New Jersey' },
  { value: 'NM', label: 'New Mexico' }, { value: 'NY', label: 'New York' }, { value: 'NC', label: 'North Carolina' },
  { value: 'ND', label: 'North Dakota' }, { value: 'OH', label: 'Ohio' }, { value: 'OK', label: 'Oklahoma' },
  { value: 'OR', label: 'Oregon' }, { value: 'PA', label: 'Pennsylvania' }, { value: 'RI', label: 'Rhode Island' },
  { value: 'SC', label: 'South Carolina' }, { value: 'SD', label: 'South Dakota' }, { value: 'TN', label: 'Tennessee' },
  { value: 'TX', label: 'Texas' }, { value: 'UT', label: 'Utah' }, { value: 'VT', label: 'Vermont' },
  { value: 'VA', label: 'Virginia' }, { value: 'WA', label: 'Washington' }, { value: 'WV', label: 'West Virginia' },
  { value: 'WI', label: 'Wisconsin' }, { value: 'WY', label: 'Wyoming' },
];

const PROPERTY_TYPES = [
  { id: 'house', name: 'House' },
  { id: 'apartment', name: 'Apartment' },
  { id: 'condo', name: 'Condo' },
  { id: 'townhouse', name: 'Townhouse' },
  { id: 'duplex', name: 'Duplex' },
  { id: 'triplex', name: 'Triplex' },
  { id: 'quadplex', name: 'Quadplex' },
  { id: 'entire_home', name: 'Entire home' },
  { id: 'private_room', name: 'Private room' },
];
const MULTI_UNIT_TYPES = ['apartment', 'duplex', 'triplex', 'quadplex'];

function isOverstayed(endDateStr: string): boolean {
  const end = parseForDisplay(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return end.getTime() < today.getTime();
}

/** All units, or the single unit when the property only has one row in the list. */
function onsiteSelectionCoversWholeProperty(
  sel: number | 'all',
  units: Array<{ id: number }>,
): boolean {
  if (sel === 'all') return true;
  if (units.length !== 1) return false;
  return units[0].id === sel;
}

function tenantStatusRank(s: OwnerTenantView['status']): number {
  if (s === 'active') return 0;
  if (s === 'pending_signup') return 1;
  if (s === 'future') return 2;
  return 3;
}

/**
 * Rows to show on unit cards / unit modal. Ended / vacated leases stay in /dashboard/owner/tenants for history
 * but must not appear on the tile once the unit is vacant.
 */
function filterTenantRowsForLiveUnitDisplay(pool: OwnerTenantView[]): OwnerTenantView[] {
  return pool.filter(
    (t) =>
      t.status === 'active' ||
      t.status === 'future' ||
      t.status === 'pending_signup' ||
      t.assignment_status === 'future' ||
      (t.assignment_status === 'active' && t.active),
  );
}

function pickTenantFromFilteredPool(pool: OwnerTenantView[]): OwnerTenantView | null {
  if (!pool.length) return null;
  return [...pool].sort((a, b) => tenantStatusRank(a.status) - tenantStatusRank(b.status))[0];
}

function occupantNamesFromTenantPool(pool: OwnerTenantView[]): string | null {
  if (!pool.length) return null;
  return groupOwnerTenantsByLeaseCohort(pool).map(formatOwnerTenantGroupNames).join('; ');
}

function tenantEmailsFromPool(pool: OwnerTenantView[]): string | null {
  const emails = [...new Set(pool.map((t) => (t.tenant_email || '').trim()).filter(Boolean))];
  return emails.length ? emails.join(', ') : null;
}

/** At least one lease row on the unit is live (co-tenant may still be pending). */
function unitPoolHasActiveLease(pool: OwnerTenantView[]): boolean {
  return pool.some(
    (t) => t.status === 'active' || (t.assignment_status === 'active' && t.active),
  );
}

/**
 * Unit list API can lag behind tenant rows after signup. Drive the card badge from tenant status when we know better.
 */
function effectiveUnitOccupancyLower(
  unitOccupancyFromApi: string | undefined,
  pool: OwnerTenantView[],
): string {
  if (unitPoolHasActiveLease(pool)) return 'occupied';
  return (unitOccupancyFromApi ?? 'vacant').toLowerCase();
}

const MAX_PROPERTY_INVITE_COTENANTS = 12;
const emptyPropertyInviteCohortRows = (): CoTenantInviteRow[] => [
  { tenant_name: '', tenant_email: '' },
  { tenant_name: '', tenant_email: '' },
];

type AssignedMgr = {
  user_id: number;
  email: string;
  full_name: string | null;
  has_resident_mode: boolean;
  resident_unit_id: number | null;
  resident_unit_ids?: number[];
};

/** Managers assigned to the whole property (no on-site scope) apply to every unit; on-site managers only to their unit(s). */
function managersForUnitCard(managers: AssignedMgr[], unitId: number, isMultiUnit: boolean): AssignedMgr[] {
  return managers.filter((m) => {
    if (!m.has_resident_mode) return true;
    const ids =
      m.resident_unit_ids && m.resident_unit_ids.length > 0
        ? m.resident_unit_ids
        : m.resident_unit_id != null
          ? [m.resident_unit_id]
          : [];
    if (ids.length === 0) return true;
    if (!isMultiUnit || unitId <= 0) {
      return true;
    }
    return ids.includes(unitId);
  });
}

function managerDisplayName(m: AssignedMgr): string {
  return (m.full_name || '').trim() || m.email || 'Manager';
}

function stayMatchesUnit(s: OwnerStayView, unit: { unit_label: string }, isMultiUnit: boolean): boolean {
  const uLabel = String(unit.unit_label ?? '1').trim();
  const sLabel = (s.unit_label || '').trim();
  if (!isMultiUnit) {
    if (!sLabel) return true;
    return sLabel === uLabel;
  }
  return sLabel === uLabel;
}

function humanizeInviteTokenState(ts: string | null | undefined): string {
  if (!ts) return '—';
  return ts.replace(/_/g, ' ');
}

/** Normalize API / form date to YYYY-MM-DD for lease fields. */
function toLeaseDateOnly(s: string | null | undefined): string {
  if (!s) return '';
  const t = String(s).trim();
  return t.length >= 10 ? t.slice(0, 10) : t;
}

/**
 * Lease window for co-tenant / roommate invite from unit detail: prefer tenant assignment dates, else guest stay.
 */
function leaseDatesForUnitInviteFromDetail(derived: {
  tenant: OwnerTenantView | null;
  displayStay: OwnerStayView | null;
}): { start: string; end: string } | null {
  const tenant = derived.tenant;
  const stay = derived.displayStay;
  if (tenant?.start_date) {
    const start = toLeaseDateOnly(tenant.start_date);
    const end = toLeaseDateOnly(tenant.end_date) || (start ? addCalendarYears(start, 1) : '');
    if (start && end) return { start, end };
    return null;
  }
  if (stay?.stay_start_date) {
    const start = toLeaseDateOnly(stay.stay_start_date);
    const end = toLeaseDateOnly(stay.stay_end_date) || (start ? addCalendarYears(start, 1) : '');
    if (start && end) return { start, end };
    return null;
  }
  return null;
}

function unitStayDurationSummary(stays: OwnerStayView[], tenant: OwnerTenantView | null): string {
  const active = stays.find((s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);
  if (active?.stay_start_date && active?.stay_end_date) {
    return `Guest stay (checked in): ${formatStayDuration(active.stay_start_date, active.stay_end_date)}`;
  }
  const upcoming = stays.find((s) => !s.checked_in_at && !s.checked_out_at && !s.cancelled_at);
  if (upcoming?.stay_start_date && upcoming?.stay_end_date) {
    return `Scheduled guest stay: ${formatStayDuration(upcoming.stay_start_date, upcoming.stay_end_date)}`;
  }
  if (tenant?.start_date && tenant?.end_date) {
    return `Lease: ${formatStayDuration(tenant.start_date, tenant.end_date)}`;
  }
  if (tenant?.start_date) {
    return `Lease starts ${formatCalendarDate(tenant.start_date)}`;
  }
  return '—';
}

function inviteStatusForUnitModal(tenant: OwnerTenantView | null, stay: OwnerStayView | null): string {
  if (stay?.token_state) {
    const base = humanizeInviteTokenState(stay.token_state);
    return stay.invitation_only ? `${base} (invitation only)` : base;
  }
  if (!tenant) return '—';
  const bits: string[] = [];
  if (tenant.invite_status) bits.push(`Invite: ${tenant.invite_status}`);
  if (tenant.assignment_status && tenant.assignment_status !== 'none') {
    bits.push(`Assignment: ${tenant.assignment_status}`);
  }
  if (tenant.stay_status && tenant.stay_status !== 'none') {
    bits.push(`Stay: ${tenant.stay_status}`);
  }
  if (bits.length) return bits.join(' · ');
  return tenant.status.replace(/_/g, ' ');
}

export const PropertyDetail: React.FC<{ propertyId: string; user: UserSession; navigate: (v: string) => void; setLoading?: (l: boolean) => void; notify?: (t: 'success' | 'error', m: string) => void }> = ({ propertyId, user, navigate, setLoading: setGlobalLoading = () => {}, notify = (_t: 'success' | 'error', _m: string) => {} }) => {
  const [activeTab, setActiveTab] = useState('overview');
  const [property, setProperty] = useState<Property | null>(null);
  const [stays, setStays] = useState<OwnerStayView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  /** When set, guest invite is scoped to this unit (multi-unit); null = let modal resolve (single-unit). */
  const [inviteGuestUnitId, setInviteGuestUnitId] = useState<number | null>(null);
  const [inviteGuestLabel, setInviteGuestLabel] = useState<string | null>(null);
  const [showInviteTenantModal, setShowInviteTenantModal] = useState(false);
  const [inviteTenantForm, setInviteTenantForm] = useState({
    tenant_name: '',
    tenant_email: '',
    lease_start_date: '',
    lease_end_date: '',
    shared_lease: false,
  });
  const [inviteTenantUnitId, setInviteTenantUnitId] = useState<number | null>(null);
  const [inviteTenantSubmitting, setInviteTenantSubmitting] = useState(false);
  const [inviteTenantLink, setInviteTenantLink] = useState<string | null>(null);
  const [inviteTenantMode, setInviteTenantMode] = useState<'single' | 'co_tenants'>('single');
  const [inviteCohortRows, setInviteCohortRows] = useState<CoTenantInviteRow[]>(emptyPropertyInviteCohortRows);
  const [inviteFirstCohortSharedLease, setInviteFirstCohortSharedLease] = useState(false);
  const [inviteTenantBatchLinks, setInviteTenantBatchLinks] = useState<{ tenant_name: string; link: string }[] | null>(null);
  const [inviteTenantFormError, setInviteTenantFormError] = useState<string | null>(null);
  /** Opened from unit detail "Send invite": unit & lease fixed; only name/email + send. */
  const [inviteTenantFromUnitCard, setInviteTenantFromUnitCard] = useState(false);
  const [showInviteManagerModal, setShowInviteManagerModal] = useState(false);
  const [inviteManagerEmail, setInviteManagerEmail] = useState('');
  const [inviteManagerSending, setInviteManagerSending] = useState(false);
  const [inviteManagerRemoveOthersConfirm, setInviteManagerRemoveOthersConfirm] = useState<string | null>(null);
  const [showTransferOwnershipModal, setShowTransferOwnershipModal] = useState(false);
  const [transferOwnershipEmail, setTransferOwnershipEmail] = useState('');
  const [transferOwnershipSending, setTransferOwnershipSending] = useState(false);
  const [transferOwnershipLink, setTransferOwnershipLink] = useState<string | null>(null);
  const [transferOwnershipError, setTransferOwnershipError] = useState<string | null>(null);
  const [unitDetailModal, setUnitDetailModal] = useState<{
    id: number;
    unit_label: string;
    occupancy_status?: string;
  } | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteSaving, setDeleteSaving] = useState(false);
  const [reactivating, setReactivating] = useState(false);
  const [primaryResidenceUpdating, setPrimaryResidenceUpdating] = useState(false);
  const [editForm, setEditForm] = useState({
    property_name: '',
    street_address: '',
    city: '',
    state: '',
    zip_code: '',
    region_code: '',
    property_type: 'house',
    bedrooms: '1',
    unit_count: '',
    unit_labels: [] as string[],
    primary_residence_unit: '' as string,
    is_primary_residence: false,
    tax_id: '',
    apn: '',
  });
  const [editError, setEditError] = useState<string | null>(null);
  const [proofLoading, setProofLoading] = useState(false);
  const [confirmingOccupancy, setConfirmingOccupancy] = useState(false);
  const [confirmOccupancyAction, setConfirmOccupancyAction] = useState<'vacated' | 'renewed' | 'holdover' | null>(null);
  const [renewEndDate, setRenewEndDate] = useState('');
  const [showLiveLinkQR, setShowLiveLinkQR] = useState(false);
  const [copyToast, setCopyToast] = useState<string | null>(null);
  const [showVerifyQRModal, setShowVerifyQRModal] = useState(false);
  const [verifyQRInviteId, setVerifyQRInviteId] = useState<string | null>(null);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [personalModeUnits, setPersonalModeUnits] = useState<number[]>([]);
  const [contextMode, setContextModeState] = useState<'business' | 'personal'>(() => getContextMode());
  const [propertyLogs, setPropertyLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [propertyLogsLoading, setPropertyLogsLoading] = useState(false);
  const [logMessageModalEntry, setLogMessageModalEntry] = useState<OwnerAuditLogEntry | null>(null);
  const [assignedManagers, setAssignedManagers] = useState<
    Array<{
      user_id: number;
      email: string;
      full_name: string | null;
      has_resident_mode: boolean;
      resident_unit_id: number | null;
      resident_unit_label: string | null;
      resident_unit_ids?: number[];
    }>
  >([]);
  const [ownerTenantsRows, setOwnerTenantsRows] = useState<OwnerTenantView[]>([]);
  const [propertyUnits, setPropertyUnits] = useState<Array<{ id: number; unit_label: string; occupancy_status?: string; is_primary_residence?: boolean; occupied_by?: string | null; invite_id?: string | null }>>([]);
  const [addResidentModeForManager, setAddResidentModeForManager] = useState<Record<number, number | 'all'>>({});
  const [addResidentModeSaving, setAddResidentModeSaving] = useState(false);
  const [removeResidentModeSaving, setRemoveResidentModeSaving] = useState<number | null>(null);
  const [allUnitsOnsiteConfirm, setAllUnitsOnsiteConfirm] = useState<{
    managerUserId: number;
    selection: number | 'all';
  } | null>(null);
  const id = Number(propertyId);

  // Derive city options based on selected state for editing
  const cityOptions = useMemo(() => {
    if (!editForm.state) return [];
    const cities = US_CITIES[editForm.state] || [];
    return cities.map(city => ({ value: city, label: city }));
  }, [editForm.state]);

  const canInvite = billing?.can_invite !== false;

  const stateKey = property?.state ?? 'FL';
  const jDoc = property?.jurisdiction_documentation;
  const jFallback = JURISDICTION_RULES[stateKey as keyof typeof JURISDICTION_RULES] ?? JURISDICTION_RULES.FL;
  const jurisdictionInfo = {
    name: jDoc?.name ?? jFallback.name,
    legalThresholdDays: jDoc?.legal_threshold_days ?? jFallback.legalThresholdDays,
    platformRenewalCycleDays: jDoc?.platform_renewal_cycle_days ?? jFallback.platformRenewalCycleDays,
    reminderDaysBefore: jDoc?.reminder_days_before ?? jFallback.reminderDaysBefore,
    jurisdictionGroup: jDoc?.jurisdiction_group ?? jFallback.group,
  };
  const propertyStays = stays.filter((s) => s.property_id === id);
  // Only checked-in stays (guest clicked Check in) count as active for occupancy and Status Confirmation
  const activeStaysForProperty = propertyStays.filter((s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);
  const activeStays = stays.filter((s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);
  const activeStay = activeStaysForProperty.find((s) => !isOverstayed(s.stay_end_date)) ?? activeStaysForProperty[0];
  // Business mode: use property status only (no guest data). Personal mode: use stays for occupancy.
  const isOccupiedForDisplay = contextMode === 'business'
    ? (property?.occupancy_status || '').toLowerCase() === 'occupied'
    : activeStaysForProperty.length > 0;
  const isOccupied = activeStaysForProperty.length > 0;
  // CR-1a: Shield is always on; API exposes `shield_mode_enabled` true — display does not use a toggle.
  const shieldStatus = isOccupiedForDisplay ? 'PASSIVE GUARD' : 'ACTIVE MONITORING';
  const isInactive = !!(property?.deleted_at);
  // Display status: active stay → OCCUPIED; else use property.occupancy_status (vacant | occupied | unknown | unconfirmed)
  const displayStatus = isOccupiedForDisplay ? 'OCCUPIED' : (property?.occupancy_status ?? 'vacant').toUpperCase();
  const stayNeedingConfirmation = propertyStays.find((s) => s.show_occupancy_confirmation_ui);
  /** Stay to use for vacated/renewed/holdover: confirmation prompt stay, or any checked-in active stay on this property */
  const stayForOccupancyActions = stayNeedingConfirmation ?? (activeStaysForProperty.length > 0 ? activeStay ?? null : null);
  /** Upcoming stay (not yet checked in) for Status Confirmation copy */
  const upcomingStayForProperty = propertyStays.find((s) => !s.checked_in_at && !s.checked_out_at && !s.cancelled_at);

  const tenantsForThisProperty = useMemo(
    () => ownerTenantsRows.filter((t) => t.property_id != null && t.property_id === property?.id),
    [ownerTenantsRows, property?.id],
  );

  const unitDetailDerived = useMemo(() => {
    if (!unitDetailModal || !property) return null;
    const u = unitDetailModal;
    const isMulti = !!property.is_multi_unit;
    const poolRaw = tenantsPoolForUnitCard(tenantsForThisProperty, u.id, u.unit_label || '1', isMulti);
    const pool = filterTenantRowsForLiveUnitDisplay(poolRaw);
    const tenant = pickTenantFromFilteredPool(pool);
    const unitStays = propertyStays.filter((s) => stayMatchesUnit(s, u, isMulti));
    const displayStay =
      unitStays.find((s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at) ??
      unitStays.find((s) => !s.checked_in_at && !s.checked_out_at && !s.cancelled_at) ??
      null;
    const inviteCode =
      (displayStay?.invite_id || tenant?.invitation_code || '').trim() || null;
    const inviteUrl = inviteCode ? buildGuestInviteUrl(inviteCode, { isDemo: Boolean(user.is_demo) }) : '';
    const occ = effectiveUnitOccupancyLower(u.occupancy_status, poolRaw);
    const statusLabel = occ ? occ.charAt(0).toUpperCase() + occ.slice(1) : 'Unknown';
    const fromPool = occupantNamesFromTenantPool(pool);
    return {
      tenant,
      displayStay,
      unitStays,
      inviteCode,
      inviteUrl,
      statusLabel,
      durationLine: unitStayDurationSummary(unitStays, tenant),
      inviteStatusLine: inviteStatusForUnitModal(tenant, displayStay),
      occupantName: fromPool || tenant?.tenant_name || displayStay?.guest_name || null,
      tenantEmailsDisplay: tenantEmailsFromPool(pool) || tenant?.tenant_email || null,
    };
  }, [unitDetailModal, property, tenantsForThisProperty, propertyStays, user.is_demo]);

  const loadData = useCallback(() => {
    if (!id || isNaN(id)) {
      const msg = 'Invalid property';
      setError(msg);
      notify('error', msg);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([
      propertiesApi.get(id),
      dashboardApi.ownerStays(),
      dashboardApi.ownerTenants().catch(() => [] as OwnerTenantView[]),
      dashboardApi.ownerPersonalModeUnits().catch(() => ({ unit_ids: [] })),
    ])
      .then(([prop, staysData, tenantsData, pmUnits]) => {
        setProperty(prop);
        setStays(staysData);
        setOwnerTenantsRows(Array.isArray(tenantsData) ? tenantsData : []);
        setPersonalModeUnits((pmUnits as { unit_ids: number[] }).unit_ids || []);
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? 'Failed to load property.';
        setError(msg);
        notify('error', msg);
      })
      .finally(() => setLoading(false));
  }, [id, notify]);

  const submitManagerOnsiteResident = useCallback(
    async (managerUserId: number, sel: number | 'all', confirmRemoveOtherManagers: boolean) => {
      if (!property) return;
      const coversWholeProperty = onsiteSelectionCoversWholeProperty(sel, propertyUnits);
      setAddResidentModeSaving(true);
      try {
        const res =
          sel === 'all'
            ? await propertiesApi.addManagerResidentMode(property.id, managerUserId, null, {
                allUnits: true,
                confirmRemoveOtherManagers,
              })
            : await propertiesApi.addManagerResidentMode(property.id, managerUserId, sel, {
                confirmRemoveOtherManagers,
              });
        notify('success', res.message ?? 'Manager added as on-site resident.');
        setAddResidentModeForManager((prev) => {
          const p = { ...prev };
          delete p[managerUserId];
          return p;
        });
        setAllUnitsOnsiteConfirm(null);
        propertiesApi.listAssignedManagers(property.id).then(setAssignedManagers).catch(() => {});
        loadData();
        emitPropertiesChanged();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      } catch (e) {
        const msg = String((e as Error)?.message ?? '');
        if (
          !confirmRemoveOtherManagers &&
          coversWholeProperty &&
          (msg.includes('OTHER_MANAGERS_PRESENT') || msg.includes('confirm_remove_other_managers'))
        ) {
          setAllUnitsOnsiteConfirm({ managerUserId, selection: sel });
        } else {
          notify('error', msg || 'Failed.');
        }
      } finally {
        setAddResidentModeSaving(false);
      }
    },
    [property, notify, loadData, propertyUnits],
  );

  const submitInviteManager = useCallback(
    async (email: string, confirmRemoveOtherManagers: boolean) => {
      if (!property) return;
      setInviteManagerSending(true);
      try {
        const res = await propertiesApi.inviteManager(property.id, email, { confirmRemoveOtherManagers });
        if (typeof window !== 'undefined' && res?.invite_link) {
          console.log('%c[DocuStay] Property manager invite link (test mode):', 'color: #059669; font-weight: bold;', res.invite_link);
        }
        notify('success', 'Invitation sent. The manager will receive an email with a signup link.');
        setInviteManagerRemoveOthersConfirm(null);
        setShowInviteManagerModal(false);
        setInviteManagerEmail('');
        propertiesApi.listAssignedManagers(property.id).then(setAssignedManagers).catch(() => {});
        emitPropertiesChanged();
        loadData();
        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      } catch (e) {
        const msg = String((e as Error)?.message ?? '');
        if (
          !confirmRemoveOtherManagers &&
          (msg.includes('OTHER_MANAGERS_PRESENT') || msg.includes('confirm_remove_other_managers'))
        ) {
          setInviteManagerRemoveOthersConfirm(email);
        } else {
          notify('error', msg || 'Failed to send invitation.');
        }
      } finally {
        setInviteManagerSending(false);
      }
    },
    [property, notify, loadData],
  );

  const handleContextModeChange = useCallback((mode: 'business' | 'personal') => {
    setContextMode(mode);
    setContextModeState(mode);
    setActiveTab((prev) => (mode === 'business' && (prev === 'stay' || prev === 'guests') ? 'overview' : prev));
    if (mode === 'business') setStays([]);
    loadData();
  }, [loadData]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /** Former owner loses access when transfer is accepted; poll so we leave this page without a manual refresh. */
  useEffect(() => {
    if (!id || Number.isNaN(id)) return;
    const intervalMs = 20000;
    const handle = window.setInterval(() => {
      propertiesApi.get(id).catch((e) => {
        const raw = String((e as Error)?.message ?? "").toLowerCase();
        if (
          raw.includes("not found") ||
          raw.includes("404") ||
          raw.includes("no owner profile") ||
          raw.includes("forbidden") ||
          raw.includes("403")
        ) {
          try {
            emitPropertiesChanged();
          } catch {
            /* ignore */
          }
          window.location.hash = "dashboard";
          window.location.reload();
        }
      });
    }, intervalMs);
    return () => window.clearInterval(handle);
  }, [id]);

  useEffect(() => {
    const unsub = onPropertiesChanged(() => {
      loadData();
    });
    const onAlertsRefresh = () => loadData();
    window.addEventListener(DASHBOARD_ALERTS_REFRESH_EVENT, onAlertsRefresh);
    return () => {
      unsub();
      window.removeEventListener(DASHBOARD_ALERTS_REFRESH_EVENT, onAlertsRefresh);
    };
  }, [loadData]);

  useEffect(() => {
    dashboardApi.billing()
      .then(setBilling)
      .catch(() => setBilling({ invoices: [], payments: [], can_invite: true }));
  }, []);

  const loadPropertyLogs = useCallback(() => {
    if (!property?.id) return;
    setPropertyLogsLoading(true);
    dashboardApi.ownerLogs({ property_id: property.id })
      .then(setPropertyLogs)
      .catch(() => setPropertyLogs([]))
      .finally(() => setPropertyLogsLoading(false));
  }, [property?.id]);

  useEffect(() => {
    if (activeTab === 'logs') loadPropertyLogs();
  }, [activeTab, loadPropertyLogs]);

  useEffect(() => {
    if (contextMode === 'business' && (activeTab === 'stay' || activeTab === 'guests')) setActiveTab('overview');
  }, [contextMode, activeTab]);

  useEffect(() => {
    if (!property?.id) return;
    propertiesApi.listAssignedManagers(property.id).then(setAssignedManagers).catch(() => setAssignedManagers([]));
    if (property.is_multi_unit) {
      propertiesApi.getUnits(property.id).then((u) => setPropertyUnits(u.filter((x) => x.id > 0))).catch(() => setPropertyUnits([]));
    } else {
      setPropertyUnits([]);
    }
  }, [property?.id, property?.is_multi_unit]);

  /** When edit modal opens, always pre-fill form from current property so existing values are retained. */
  const syncEditFormFromProperty = useCallback(() => {
    if (!property) return;
    const typeRaw = property.property_type_label ?? property.property_type ?? 'house';
    const typeNorm = String(typeRaw).toLowerCase().trim().replace(/\s+/g, '_');
    const isMulti = property.is_multi_unit ?? MULTI_UNIT_TYPES.includes(typeNorm);
    const unitCount = isMulti && propertyUnits.length > 0 ? String(propertyUnits.length) : '';
    const labels = isMulti ? propertyUnits.map((u) => u.unit_label || '') : [];
    const primaryIdx = isMulti && propertyUnits.length > 0
      ? String(propertyUnits.findIndex((u) => u.is_primary_residence) + 1)
      : '';
    setEditForm({
      property_name: property.name ?? '',
      street_address: property.street ?? '',
      city: property.city ?? '',
      state: property.state ?? '',
      zip_code: property.zip_code ?? '',
      region_code: property.region_code ?? '',
      property_type: typeNorm || 'house',
      bedrooms: property.bedrooms ?? '1',
      unit_count: unitCount,
      unit_labels: labels,
      primary_residence_unit: primaryIdx === '0' ? '' : primaryIdx,
      is_primary_residence: property.owner_occupied ?? false,
      tax_id: property.tax_id ?? '',
      apn: property.apn ?? '',
    });
  }, [property, propertyUnits]);

  const openEdit = () => {
    if (property) {
      syncEditFormFromProperty();
      setEditError(null);
      setEditOpen(true);
    }
  };

  /** Keep form in sync with current property whenever the edit modal is open (e.g. so existing values are shown). */
  useEffect(() => {
    if (editOpen && property) {
      syncEditFormFromProperty();
    }
  }, [editOpen, property, syncEditFormFromProperty]);

  const saveEdit = async () => {
    if (!property) return;
    const street = editForm.street_address?.trim();
    const city = editForm.city?.trim();
    const state = editForm.state?.trim();
    if (!street || !city || !state) {
      setEditError('Street address, city, and state are required.');
      return;
    }
    const isMulti = MULTI_UNIT_TYPES.includes(editForm.property_type);
    if (isMulti) {
      const uc = parseInt(editForm.unit_count, 10);
      if (!editForm.unit_count.trim() || isNaN(uc) || uc < 1) {
        setEditError('For multi-unit properties, enter a valid number of units (at least 1).');
        return;
      }
    }
    setEditSaving(true);
    setEditError(null);
    try {
      const payload: Record<string, unknown> = {
        street_address: street,
        city,
        state,
        property_name: editForm.property_name?.trim() || undefined,
        zip_code: editForm.zip_code?.trim() || undefined,
        region_code: editForm.region_code?.trim() ? editForm.region_code.trim().toUpperCase().slice(0, 20) : undefined,
        property_type: editForm.property_type || undefined,
        bedrooms: editForm.bedrooms || undefined,
        tax_id: editForm.tax_id?.trim() || undefined,
        apn: editForm.apn?.trim() || undefined,
      };
      if (isMulti) {
        const uc = parseInt(editForm.unit_count, 10);
        if (!isNaN(uc) && uc >= 1) payload.unit_count = uc;
        if (editForm.unit_labels.length > 0) payload.unit_labels = editForm.unit_labels;
      }
      const updated = await propertiesApi.update(property.id, payload as Parameters<typeof propertiesApi.update>[1]);
      setProperty(updated);
      setEditOpen(false);
      emitPropertiesChanged();
      if (updated.is_multi_unit) {
        propertiesApi.getUnits(property.id).then((u) => setPropertyUnits(u.filter((x) => x.id > 0))).catch(() => {});
      }
      notify('success', 'Property updated.');
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      const msg = (e as Error)?.message ?? 'Failed to update property.';
      setEditError(msg);
      notify('error', msg);
    } finally {
      setEditSaving(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!property) return;
    setDeleteSaving(true);
    setDeleteError(null);
    try {
      await propertiesApi.delete(property.id);
      setDeleteConfirmOpen(false);
      notify('success', 'Property removed from dashboard. It has been moved to Inactive properties.');
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
      navigate('dashboard/properties');
    } catch (e) {
      const msg = (e as Error)?.message ?? 'Failed to remove property.';
      setDeleteError(msg);
      notify('error', msg);
    } finally {
      setDeleteSaving(false);
    }
  };

  const address = property ? [property.street, property.city, property.state, property.zip_code].filter(Boolean).join(', ') : '';

  const sidebarNavAll = [
    { id: 'dashboard', label: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
    { id: 'properties', label: 'My Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'guests', label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
    { id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
    { id: 'billing', label: 'Billing', icon: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2H9v2h2v6a2 2 0 002 2h2a2 2 0 002-2v-6h2V9zm-6 0V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2h4z' },
    { id: 'logs', label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
    { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  ];
  const sidebarNav = contextMode === 'personal'
    ? sidebarNavAll.filter((i) => i.id !== 'logs' && i.id !== 'invitations')
    : sidebarNavAll;

  const onNav = (itemId: string) => {
    if (itemId === 'settings') navigate('settings');
    else if (itemId === 'help') navigate('help');
    else if (itemId === 'properties') navigate('dashboard/properties');
    else if (itemId === 'billing') navigate('dashboard/billing');
    else if (itemId === 'guests') navigate('dashboard/guests');
    else if (itemId === 'invitations') navigate('dashboard/invitations');
    else if (itemId === 'logs') navigate('dashboard/logs');
    else navigate('dashboard');
  };

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar - same as OwnerDashboard (fixed width so it does not shrink) */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {sidebarNav.map((item) => (
            <button
              key={item.id}
              onClick={() => onNav(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${item.id === 'properties' ? 'bg-slate-100 text-slate-700 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon} /></svg>
              {item.label}
            </button>
          ))}
        </div>
        {contextMode === 'personal' && (
        <div className="mt-6 pt-6 border-t border-slate-200 flex-grow min-h-0 flex flex-col">
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-3 px-1">Your guests</h3>
          {loading ? (
            <p className="text-slate-500 text-sm">Loading…</p>
          ) : activeStays.length === 0 ? (
            <p className="text-slate-500 text-sm">No active guests.</p>
          ) : (
            <ul className="space-y-3 overflow-y-auto no-scrollbar pr-1">
              {activeStays.map((stay) => (
                <li key={stay.stay_id} className="rounded-xl p-3 border border-slate-200 bg-slate-100 hover:bg-slate-100">
                  <div className="flex items-start gap-2">
                    <div className="w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-xs flex-shrink-0">
                      {stay.guest_name.charAt(0)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-slate-800 truncate">{stay.guest_name}</p>
                      <p className="text-xs text-slate-600 truncate mt-0.5">{stay.property_name}</p>
                      <p className="text-xs text-slate-500 mt-1">{formatStayDuration(stay.stay_start_date, stay.stay_end_date)}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        )}

        {/* Mode switcher at bottom (same as OwnerDashboard) */}
        <div className="mt-6 pt-6 border-t border-slate-200 flex-shrink-0">
          <ModeSwitcher
            contextMode={contextMode}
            personalModeUnits={personalModeUnits}
            onContextModeChange={handleContextModeChange}
          />
        </div>
      </aside>

      <main className="flex-grow overflow-y-auto bg-transparent p-6 lg:p-8">
        {loading ? (
          <p className="text-slate-600">Loading property…</p>
        ) : error || !property ? (
          <Card className="p-8 text-center max-w-md mx-auto border-slate-200">
            <p className="text-slate-600 mb-4">Something went wrong loading this property.</p>
            <div className="flex gap-3 justify-center">
              <Button variant="outline" onClick={() => navigate('dashboard/properties')}>Back to My Properties</Button>
              <Button variant="primary" onClick={() => { setError(null); loadData(); }}>Try again</Button>
            </div>
          </Card>
        ) : (
          <>
      {isInactive && (
        <div className="mb-8">
          <InactivePropertyBanner role="owner" />
        </div>
      )}
      <header className="mb-8">
        <button onClick={() => navigate('dashboard/properties')} className="flex items-center gap-2 text-slate-600 hover:text-slate-800 mb-6 text-sm font-medium transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" /></svg>
          Back to My Properties
        </button>
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl lg:text-3xl font-bold text-slate-800 tracking-tight">{property.name || address || 'Property'}</h1>
              {isInactive && (
                <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold uppercase tracking-wider bg-amber-100 text-amber-800 border border-amber-200">
                  Inactive
                </span>
              )}
            </div>
            <p className="text-slate-600 mt-1">{address || '—'}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" onClick={openEdit}>Edit Property</Button>
            {!isInactive && contextMode === 'personal' && (
              <span className={!canInvite ? 'group relative inline-block cursor-not-allowed' : undefined}>
                {!canInvite && (
                  <span
                    className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-3 py-2 bg-gray-900 text-white text-xs rounded shadow-lg whitespace-nowrap opacity-0 pointer-events-none transition-opacity duration-150 z-[200] group-hover:opacity-100"
                    role="tooltip"
                  >
                    Billing setup is still in progress. Open Billing to finish subscription setup.
                  </span>
                )}
                <Button
                  variant="primary"
                  onClick={() => {
                    if (!canInvite) {
                      notify('error', 'Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly.');
                      navigate('dashboard/billing');
                      return;
                    }
                    setInviteGuestUnitId(null);
                    setInviteGuestLabel(null);
                    setShowInviteModal(true);
                  }}
                  disabled={!canInvite}
                  className={!canInvite ? 'pointer-events-none' : undefined}
                >
                  Invite
                </Button>
              </span>
            )}
            {!isInactive && contextMode === 'business' && (
              <>
                <Button
                  variant="outline"
                  onClick={() => {
                    if (!canInvite) {
                      notify('error', 'Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly.');
                      navigate('dashboard/billing');
                      return;
                    }
                    const units = property?.is_multi_unit && propertyUnits.length > 0 ? propertyUnits : (property ? [{ id: 0, unit_label: '1', occupancy_status: property.occupancy_status ?? 'vacant' }] : []);
                    const firstUnitId = units[0]?.id ?? 0;
                    setInviteTenantUnitId(firstUnitId || null);
                    setInviteTenantForm({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '', shared_lease: false });
                    setInviteTenantMode('single');
                    setInviteCohortRows(emptyPropertyInviteCohortRows());
                    setInviteFirstCohortSharedLease(false);
                    setInviteTenantLink(null);
                    setInviteTenantBatchLinks(null);
                    setInviteTenantFormError(null);
                    setInviteTenantFromUnitCard(false);
                    setShowInviteTenantModal(true);
                  }}
                >
                  Invite Tenant
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setInviteManagerEmail('');
                    setShowInviteManagerModal(true);
                  }}
                >
                  Invite Manager
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    if (!canInvite) {
                      notify('error', 'Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly.');
                      navigate('dashboard/billing');
                      return;
                    }
                    setTransferOwnershipEmail('');
                    setTransferOwnershipLink(null);
                    setTransferOwnershipError(null);
                    setShowTransferOwnershipModal(true);
                  }}
                  title="Generate a secure link so another person can accept ownership of this property in DocuStay."
                >
                  Transfer ownership
                </Button>
              </>
            )}
            {isInactive ? (
              <Button
                variant="primary"
                disabled={reactivating}
                onClick={async () => {
                  if (!property) return;
                  setReactivating(true);
                  try {
                    await propertiesApi.reactivate(property.id);
                    notify('success', 'Property reactivated. It appears in My Properties and in the invite list again.');
                    loadData();
                    window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                  } catch (e) {
                    notify('error', (e as Error)?.message ?? 'Failed to reactivate.');
                  } finally {
                    setReactivating(false);
                  }
                }}
              >
                {reactivating ? 'Reactivating…' : 'Reactivate property'}
              </Button>
            ) : contextMode !== 'personal' ? (
              <Button
                variant="ghost"
                onClick={() => { setDeleteConfirmOpen(true); setDeleteError(null); }}
                title="Remove from dashboard (moves to Inactive properties). Stays and leases stay on file for your records and event ledger."
                className="text-red-600 hover:text-red-700 hover:bg-red-50"
              >
                Remove Property
              </Button>
            ) : null}
          </div>
        </div>
      </header>

      <div className="flex border-b border-slate-200 mb-8 overflow-x-auto no-scrollbar">
        {(contextMode === 'personal'
          ? (['Overview', 'Stay', 'Guests', 'Documentation', 'Event ledger'] as const)
          : (['Overview', 'Documentation', 'Event ledger'] as const)).map((tab) => {
          const tabId = tab === 'Event ledger' ? 'logs' : tab.toLowerCase();
          return (
            <button
              key={tabId}
              onClick={() => setActiveTab(tabId)}
              className={`px-6 py-3 text-sm font-medium whitespace-nowrap transition-all border-b-2 ${activeTab === tabId ? 'text-slate-800 border-slate-800' : 'text-slate-500 border-transparent hover:text-slate-700'}`}
            >
              {tab}
            </button>
          );
        })}
      </div>

      <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">
        {activeTab === 'overview' && (
          <div className="space-y-8">
            <div className="space-y-8">
              {property && (
                <>
                {contextMode === 'personal' && (
                <Card className="p-6 border-slate-200 border-sky-100 bg-sky-50/40">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Personal mode</h3>
                  <p className="text-sm text-slate-700">
                    Use <strong>Invite</strong> for short-term guest stays. Tenant and manager invitations are in{' '}
                    <strong>Business</strong> mode. Use <strong>Show in Personal mode</strong> below to mark this property as your residence.
                  </p>
                </Card>
                )}

                {!isInactive && (
                  <Card className="p-6 border-slate-200">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Primary residence</h3>
                    <div className="flex flex-wrap items-center justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-slate-800">Show in Personal mode</p>
                        <p className="text-xs text-slate-500 mt-0.5">
                          When on, this property appears in Personal mode (your home, guest invites, and related alerts).
                        </p>
                      </div>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={!!property.owner_occupied}
                        aria-busy={primaryResidenceUpdating}
                        disabled={primaryResidenceUpdating}
                        onClick={async () => {
                          if (!property) return;
                          const next = !property.owner_occupied;
                          setPrimaryResidenceUpdating(true);
                          try {
                            const updated = await propertiesApi.update(property.id, { owner_occupied: next });
                            setProperty((prev) =>
                              prev && prev.id === updated.id
                                ? {
                                    ...prev,
                                    ...updated,
                                    unit_count: updated.unit_count ?? prev.unit_count,
                                    occupied_unit_count: updated.occupied_unit_count ?? prev.occupied_unit_count,
                                    vacant_unit_count: updated.vacant_unit_count ?? prev.vacant_unit_count,
                                  }
                                : updated,
                            );
                            const unitRefresh = updated.is_multi_unit
                              ? propertiesApi
                                  .getUnits(property.id)
                                  .then((u) => setPropertyUnits(u.filter((x) => x.id > 0)))
                                  .catch(() => {})
                              : Promise.resolve();
                            const pmRefresh = dashboardApi
                              .ownerPersonalModeUnits()
                              .then((pm) =>
                                setPersonalModeUnits((pm as { unit_ids: number[] }).unit_ids || []),
                              )
                              .catch(() => {});
                            await Promise.all([unitRefresh, pmRefresh]);
                            notify(
                              'success',
                              next ? 'This property will appear in Personal mode.' : 'Removed from Personal mode.',
                            );
                            window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Could not update primary residence.');
                          } finally {
                            setPrimaryResidenceUpdating(false);
                          }
                        }}
                        className={`relative inline-flex h-7 w-12 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${
                          property.owner_occupied ? 'bg-emerald-600' : 'bg-slate-200'
                        }`}
                      >
                        <span
                          className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow ring-0 transition-transform ${
                            property.owner_occupied ? 'translate-x-5' : 'translate-x-0.5'
                          }`}
                        />
                      </button>
                    </div>
                  </Card>
                )}

                <Card className="p-6 border-slate-200">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Address & property details</h3>
                  <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6">
                    {[
                      { label: 'Street', value: property.street },
                      { label: 'City', value: property.city },
                      { label: 'State', value: property.state },
                      { label: 'ZIP code', value: property.zip_code },
                      { label: 'Region', value: property.region_code },
                      { label: 'Property type', value: property.property_type_label || property.property_type },
                      ...(property.is_multi_unit
                        ? [{ label: 'Units', value: propertyUnits.length > 0 ? String(propertyUnits.length) : '—' }]
                        : [{ label: 'Bedrooms', value: property.bedrooms }]),
                    ].map(({ label, value }) => (
                      <div key={label} className="flex flex-col gap-1">
                        <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</dt>
                        <dd className="text-sm font-medium text-slate-800">{value ?? '—'}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>
                {((property.is_multi_unit && propertyUnits.length > 0) || (!property.is_multi_unit && property)) && (
                  <Card className="p-6 border-slate-200">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Units</h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {(property.is_multi_unit ? propertyUnits : [{ id: 0, unit_label: '1', occupancy_status: property.occupancy_status ?? 'vacant' }]).map((u) => {
                        const poolRaw = tenantsPoolForUnitCard(
                          tenantsForThisProperty,
                          u.id,
                          u.unit_label || '1',
                          !!property.is_multi_unit,
                        );
                        const status = effectiveUnitOccupancyLower(u.occupancy_status, poolRaw);
                        const pool = filterTenantRowsForLiveUnitDisplay(poolRaw);
                        const statusCls = status === 'occupied' ? 'bg-emerald-100 text-emerald-700' : status === 'vacant' ? 'bg-sky-100 text-sky-700' : status === 'unconfirmed' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600';
                        const label = status ? status.charAt(0).toUpperCase() + status.slice(1) : (u.occupancy_status ?? 'vacant');
                        const tenantRow = pickTenantFromFilteredPool(pool);
                        const tenantLabel =
                          occupantNamesFromTenantPool(pool) ||
                          (tenantRow ? tenantRow.tenant_name || tenantRow.tenant_email || null : null);
                        const poolEmailsLine = tenantEmailsFromPool(pool);
                        const managersHere = managersForUnitCard(assignedManagers, u.id, !!property.is_multi_unit);
                        const managersLine =
                          managersHere.length > 0 ? managersHere.map(managerDisplayName).join(', ') : null;
                        return (
                          <button
                            key={u.id}
                            type="button"
                            onClick={() =>
                              setUnitDetailModal({
                                id: u.id,
                                unit_label: u.unit_label || '1',
                                occupancy_status: u.occupancy_status,
                              })
                            }
                            className="bg-slate-50 rounded-lg p-3 border border-slate-200 flex flex-col gap-2 w-full text-left cursor-pointer transition-shadow hover:shadow-md hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#6B90F2] focus:ring-offset-2"
                            aria-label={`Open details for unit ${u.unit_label}`}
                          >
                            <p className="font-medium text-slate-900">Unit {u.unit_label}</p>
                            <span className={`px-2 py-0.5 rounded text-xs font-medium w-fit ${statusCls}`}>{label}</span>
                            {managersLine && (
                              <p className="text-xs text-slate-600">
                                Managed by: <span className="font-medium text-slate-800">{managersLine}</span>
                              </p>
                            )}
                            {tenantLabel && tenantRow && (
                              <div className="text-xs text-slate-700 space-y-0.5 border-t border-slate-200/80 pt-2 mt-0.5">
                                <p className="font-medium text-slate-800">Tenants: {tenantLabel}</p>
                                {pool.length === 1 && tenantRow.tenant_name && tenantRow.tenant_email && (
                                  <p className="text-slate-500">{tenantRow.tenant_email}</p>
                                )}
                                {pool.length > 1 && poolEmailsLine && (
                                  <p className="text-slate-500 break-all">{poolEmailsLine}</p>
                                )}
                                {(tenantRow.start_date || tenantRow.end_date) && (
                                  <p className="text-slate-600">
                                    Lease {formatCalendarDate(tenantRow.start_date)} –{' '}
                                    {tenantRow.end_date ? formatCalendarDate(tenantRow.end_date) : 'Open-ended'}
                                  </p>
                                )}
                                {pool.some((t) => t.status === 'pending_signup') &&
                                  (unitPoolHasActiveLease(poolRaw) ? (
                                    <p className="text-amber-700">Co-tenant pending signup</p>
                                  ) : (
                                    <p className="text-amber-700">Pending signup</p>
                                  ))}
                              </div>
                            )}
                            {contextMode === 'personal' && status === 'occupied' && u.occupied_by && (
                              <p className="text-xs text-slate-600">Occupied by {u.occupied_by}</p>
                            )}
                            {contextMode === 'personal' && status === 'occupied' && u.invite_id && (
                              <p className="text-xs text-slate-500">Invite ID {u.invite_id}</p>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </Card>
                )}

                <Modal
                  open={unitDetailModal != null}
                  title={unitDetailModal ? `Unit ${unitDetailModal.unit_label}` : 'Unit'}
                  onClose={() => setUnitDetailModal(null)}
                  className="max-w-lg"
                >
                  {unitDetailDerived && unitDetailModal && (
                    <div className="px-6 py-5 space-y-4 text-sm text-slate-800">
                      <dl className="space-y-4">
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Unit status</dt>
                          <dd className="font-medium text-slate-900">{unitDetailDerived.statusLabel}</dd>
                        </div>
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Unit number / ID</dt>
                          <dd>
                            <span className="font-medium">Label: {unitDetailModal.unit_label || '—'}</span>
                            
                          </dd>
                        </div>
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Current stay / lease duration</dt>
                          <dd className="text-slate-700">{unitDetailDerived.durationLine}</dd>
                        </div>
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Tenant / occupant name</dt>
                          <dd className="font-medium">{unitDetailDerived.occupantName ?? '—'}</dd>
                        </div>
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Tenant email</dt>
                          <dd className="break-all">{unitDetailDerived.tenantEmailsDisplay ?? '—'}</dd>
                        </div>
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Invite ID</dt>
                          <dd className="font-mono text-xs break-all">{unitDetailDerived.inviteCode ?? '—'}</dd>
                        </div>
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Invite link</dt>
                          <dd className="space-y-2">
                            {unitDetailDerived.inviteUrl ? (
                              <>
                                <p className="text-xs break-all text-slate-600">{unitDetailDerived.inviteUrl}</p>
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="text-xs py-1.5 px-3"
                                  onClick={async () => {
                                    const ok = await copyToClipboard(unitDetailDerived.inviteUrl);
                                    if (ok) notify('success', 'Invite link copied.');
                                    else notify('error', 'Could not copy link.');
                                  }}
                                >
                                  Copy link
                                </Button>
                              </>
                            ) : (
                              '—'
                            )}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Invite / invitation status</dt>
                          <dd className="text-slate-700 capitalize">{unitDetailDerived.inviteStatusLine}</dd>
                        </div>
                      </dl>
                      {!isInactive && (
                        <div className="border-t border-slate-200 pt-4 mt-4 flex flex-wrap gap-2">
                          {contextMode === 'personal' && (
                            <span className={!canInvite ? 'group relative inline-block cursor-not-allowed' : undefined}>
                              <Button
                                variant="primary"
                                type="button"
                                disabled={!canInvite}
                                className={!canInvite ? 'pointer-events-none' : undefined}
                                onClick={() => {
                                  if (!canInvite) {
                                    notify('error', 'Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly.');
                                    navigate('dashboard/billing');
                                    return;
                                  }
                                  const uid = unitDetailModal.id > 0 ? unitDetailModal.id : null;
                                  const label = `Unit ${unitDetailModal.unit_label || '—'}`;
                                  setUnitDetailModal(null);
                                  setInviteGuestUnitId(uid);
                                  setInviteGuestLabel(label);
                                  setShowInviteModal(true);
                                }}
                              >
                                Send invite
                              </Button>
                            </span>
                          )}
                          {contextMode === 'business' && (
                            <Button
                              variant="primary"
                              type="button"
                              onClick={() => {
                                if (!canInvite) {
                                  notify('error', 'Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly.');
                                  navigate('dashboard/billing');
                                  return;
                                }
                                const tid = unitDetailModal.id >= 0 ? unitDetailModal.id : 0;
                                const leasePair = leaseDatesForUnitInviteFromDetail(unitDetailDerived);
                                setUnitDetailModal(null);
                                setInviteTenantUnitId(tid);
                                setInviteTenantMode('single');
                                setInviteCohortRows(emptyPropertyInviteCohortRows());
                                setInviteFirstCohortSharedLease(false);
                                setInviteTenantLink(null);
                                setInviteTenantBatchLinks(null);
                                setInviteTenantFormError(null);
                                if (leasePair) {
                                  setInviteTenantForm({
                                    tenant_name: '',
                                    tenant_email: '',
                                    lease_start_date: leasePair.start,
                                    lease_end_date: leasePair.end,
                                    shared_lease: true,
                                  });
                                  setInviteTenantFromUnitCard(true);
                                } else {
                                  setInviteTenantForm({
                                    tenant_name: '',
                                    tenant_email: '',
                                    lease_start_date: '',
                                    lease_end_date: '',
                                    shared_lease: false,
                                  });
                                  setInviteTenantFromUnitCard(false);
                                }
                                setShowInviteTenantModal(true);
                              }}
                            >
                              Send invite
                            </Button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </Modal>

                {assignedManagers.length > 0 && (
                  <Card className="p-6 border-slate-200">
                    <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-4">Assigned managers</h3>
                    <ul className="space-y-3">
                      {assignedManagers.map((m) => (
                        <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-slate-100 last:border-0">
                          <div>
                            <p className="text-sm font-medium text-slate-800">{m.full_name || m.email}</p>
                            <p className="text-xs text-slate-500">{m.email}</p>
                            {m.has_resident_mode && m.resident_unit_label && (
                              <>
                                <p className="text-xs text-emerald-600 mt-0.5">
                                  {m.resident_unit_ids && m.resident_unit_ids.length > 1
                                    ? `On-site resident · All units (${m.resident_unit_ids.length}): ${m.resident_unit_label}`
                                    : `On-site resident · Unit ${m.resident_unit_label}`}
                                </p>
                              </>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            {m.has_resident_mode ? (
                              <Button
                                variant="outline"
                                disabled={removeResidentModeSaving === m.user_id}
                                onClick={async () => {
                                  if (!property) return;
                                  setRemoveResidentModeSaving(m.user_id);
                                  try {
                                    const res = await propertiesApi.removeManagerResidentMode(property.id, m.user_id);
                                    notify('success', res.message ?? 'Manager removed as on-site resident.');
                                    propertiesApi.listAssignedManagers(property.id).then(setAssignedManagers).catch(() => {});
                                    loadData();
                                    window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                                  } catch (e) {
                                    notify('error', (e as Error)?.message ?? 'Failed.');
                                  } finally {
                                    setRemoveResidentModeSaving(null);
                                  }
                                }}
                              >
                                {removeResidentModeSaving === m.user_id ? 'Removing…' : 'Remove as on-site resident'}
                              </Button>
                            ) : property?.is_multi_unit && propertyUnits.length > 0 ? (
                              <>
                                <select
                                  value={
                                    addResidentModeForManager[m.user_id] === 'all'
                                      ? 'all'
                                      : addResidentModeForManager[m.user_id]
                                        ? String(addResidentModeForManager[m.user_id])
                                        : ''
                                  }
                                  onChange={(e) => {
                                    const v = e.target.value;
                                    const uid = m.user_id;
                                    const others = assignedManagers.filter((x) => x.user_id !== uid);
                                    if (v === '') {
                                      setAddResidentModeForManager((prev) => {
                                        const next = { ...prev };
                                        delete next[uid];
                                        return next;
                                      });
                                      setAllUnitsOnsiteConfirm((prev) => (prev?.managerUserId === uid ? null : prev));
                                      return;
                                    }
                                    const sel: number | 'all' = v === 'all' ? 'all' : Number(v);
                                    setAddResidentModeForManager((prev) => ({ ...prev, [uid]: sel }));
                                    const coversWhole = onsiteSelectionCoversWholeProperty(sel, propertyUnits);
                                    if (coversWhole && others.length > 0) {
                                      setAllUnitsOnsiteConfirm({ managerUserId: uid, selection: sel });
                                    } else {
                                      setAllUnitsOnsiteConfirm((prev) => (prev?.managerUserId === uid ? null : prev));
                                    }
                                  }}
                                  className="text-sm border border-slate-300 rounded-lg px-2 py-1.5"
                                >
                                  <option value="">Select unit</option>
                                  <option value="all">All units</option>
                                  {propertyUnits.map((u) => (
                                    <option key={u.id} value={u.id}>Unit {u.unit_label}</option>
                                  ))}
                                </select>
                                <Button
                                  variant="outline"
                                  disabled={addResidentModeSaving || addResidentModeForManager[m.user_id] == null}
                                  onClick={() => {
                                    const sel = addResidentModeForManager[m.user_id];
                                    if (!property || sel == null) return;
                                    const otherManagers = assignedManagers.filter((x) => x.user_id !== m.user_id);
                                    const coversWhole = onsiteSelectionCoversWholeProperty(sel, propertyUnits);
                                    if (otherManagers.length > 0 && coversWhole) {
                                      setAllUnitsOnsiteConfirm({ managerUserId: m.user_id, selection: sel });
                                      return;
                                    }
                                    void submitManagerOnsiteResident(m.user_id, sel, false);
                                  }}
                                >
                                  Add as on-site
                                </Button>
                              </>
                            ) : null}
                          </div>
                        </li>
                      ))}
                    </ul>
                    <p className="text-xs text-slate-500 mt-3">
                      On-site residents get Personal Mode (guest invites for their unit). A manager can register themselves from{' '}
                      <strong className="text-slate-600">their</strong> property page in Business mode—same link; you do not have to be the one to add them.
                    </p>
                  </Card>
                )}
                {property.live_slug && (
                  <Card className="p-6 border-slate-200">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Live link page</h3>
                    <p className="text-sm text-slate-600 mb-4">Anyone with this link can view property info, owner contact, current or last stay, and activity log (no login required).</p>
                    <Button
                      type="button"
                      variant="primary"
                      className="w-full sm:w-auto"
                      onClick={() => setShowLiveLinkQR(true)}
                    >
                      Open live link
                    </Button>
                  </Card>
                )}
                <Card className="p-6 border-slate-200">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Ownership proof</h3>
                  {property.ownership_proof_filename ? (
                    <div className="space-y-2">
                      <p className="text-sm text-slate-600">
                        {property.ownership_proof_filename}
                        {property.ownership_proof_type && (
                          <span className="ml-2 text-slate-500">({property.ownership_proof_type.replace(/_/g, ' ')})</span>
                        )}
                      </p>
                      <Button
                        variant="outline"
                        disabled={proofLoading}
                        className="text-sm px-4 py-2"
                        onClick={async () => {
                          if (!property) return;
                          setProofLoading(true);
                          try {
                            const blob = await propertiesApi.getOwnershipProofBlob(property.id);
                            const url = URL.createObjectURL(blob);
                            window.open(url, '_blank', 'noopener,noreferrer');
                            setTimeout(() => URL.revokeObjectURL(url), 60000);
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to load proof.');
                          } finally {
                            setProofLoading(false);
                          }
                        }}
                      >
                        {proofLoading ? 'Loading…' : 'View proof'}
                      </Button>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500">You do not have any proof uploaded.</p>
                  )}
                </Card>
                {stayForOccupancyActions && (
                  <Card className={`mb-6 p-5 md:p-6 ${stayNeedingConfirmation ? 'border-amber-200 bg-amber-50/80' : 'border-slate-200'}`}>
                    <h3 className={`text-xs font-bold uppercase tracking-wider mb-2 ${stayNeedingConfirmation ? 'text-amber-800' : 'text-slate-600'}`}>
                      {stayNeedingConfirmation ? 'Confirm occupancy status' : 'Update stay or confirm occupancy'}
                    </h3>
                    {stayNeedingConfirmation ? (
                      <p className="text-sm text-amber-900 mb-3">
                        <strong>Is this unit/property now VACANT or OCCUPIED?</strong>{' '}
                        {stayNeedingConfirmation.needs_occupancy_confirmation
                          ? `Please respond before ${stayNeedingConfirmation.confirmation_deadline_at ? formatDateTimeLocal(stayNeedingConfirmation.confirmation_deadline_at) : 'the deadline'}. If we do not hear from you in time, occupancy may be set to Unknown.`
                          : 'No response was received by the deadline. Status is UNCONFIRMED. Please confirm now.'}
                      </p>
                    ) : (
                      <p className="text-sm text-slate-600 mb-3">
                        <strong>Is this unit/property now VACANT or OCCUPIED?</strong> You can also extend the lease for{' '}
                        <strong>{stayForOccupancyActions.guest_name}</strong> below.
                      </p>
                    )}
                    <div className="flex flex-wrap gap-3">
                      <Button
                        variant="outline"
                        className={stayNeedingConfirmation ? 'border-amber-600 text-amber-800 hover:bg-amber-100' : ''}
                        disabled={confirmingOccupancy}
                        onClick={async () => {
                          if (!stayForOccupancyActions) return;
                          setConfirmOccupancyAction('vacated');
                          setConfirmingOccupancy(true);
                          try {
                            await dashboardApi.confirmOccupancyStatus(stayForOccupancyActions.stay_id, 'vacant');
                            await dashboardApi.markOccupancyPromptAlertsRead(stayForOccupancyActions.stay_id).catch(() => {});
                            notify('success', 'Marked as vacant.');
                            loadData();
                            window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to confirm.');
                          } finally {
                            setConfirmingOccupancy(false);
                            setConfirmOccupancyAction(null);
                          }
                        }}
                      >
                        Vacant
                      </Button>
                      <Button
                        variant="outline"
                        className={stayNeedingConfirmation ? 'border-amber-600 text-amber-800 hover:bg-amber-100' : ''}
                        disabled={confirmingOccupancy}
                        onClick={async () => {
                          if (!stayForOccupancyActions) return;
                          setConfirmOccupancyAction('holdover');
                          setConfirmingOccupancy(true);
                          try {
                            await dashboardApi.confirmOccupancyStatus(stayForOccupancyActions.stay_id, 'occupied');
                            await dashboardApi.markOccupancyPromptAlertsRead(stayForOccupancyActions.stay_id).catch(() => {});
                            notify('success', 'Marked as occupied.');
                            loadData();
                            window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                          } catch (e) {
                            notify('error', (e as Error)?.message ?? 'Failed to confirm.');
                          } finally {
                            setConfirmingOccupancy(false);
                            setConfirmOccupancyAction(null);
                          }
                        }}
                      >
                        Occupied
                      </Button>
                      <Button
                        variant="outline"
                        className={stayNeedingConfirmation ? 'border-amber-600 text-amber-800 hover:bg-amber-100' : ''}
                        disabled={confirmingOccupancy}
                        onClick={() => setConfirmOccupancyAction('renewed')}
                      >
                        Lease renewed
                      </Button>
                    </div>
                    {confirmOccupancyAction === 'renewed' && (
                      <div className="mt-4 flex flex-wrap items-center gap-3">
                        <input
                          type="date"
                          value={renewEndDate}
                          onChange={(e) => setRenewEndDate(e.target.value)}
                          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                          min={stayForOccupancyActions?.stay_end_date ?? undefined}
                        />
                        <Button
                          variant="outline"
                          disabled={!renewEndDate || confirmingOccupancy}
                          onClick={async () => {
                            if (!stayForOccupancyActions || !renewEndDate) return;
                            setConfirmingOccupancy(true);
                            try {
                              await dashboardApi.confirmOccupancyStatus(stayForOccupancyActions.stay_id, 'renewed', renewEndDate);
                              await dashboardApi.markOccupancyPromptAlertsRead(stayForOccupancyActions.stay_id).catch(() => {});
                              notify('success', 'Lease renewed.');
                              setRenewEndDate('');
                              setConfirmOccupancyAction(null);
                              window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                              loadData();
                            } catch (e) {
                              notify('error', (e as Error)?.message ?? 'Failed to confirm.');
                            } finally {
                              setConfirmingOccupancy(false);
                            }
                          }}
                        >
                          Confirm renewal
                        </Button>
                        <button
                          type="button"
                          className="text-sm text-slate-600 hover:text-slate-800"
                          onClick={() => { setConfirmOccupancyAction(null); setRenewEndDate(''); }}
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </Card>
                )}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6">
                  <Card className="p-5 md:p-6 border-slate-200 bg-slate-50/80 flex flex-col">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Occupancy status</h3>
                    <div className="flex flex-col gap-3 flex-1 min-h-0">
                      <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium w-fit ${
                        displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
                        displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
                        displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
                        'bg-slate-100 text-slate-600'
                      }`}>
                        <span className={`w-2 h-2 rounded-full shrink-0 ${
                          displayStatus === 'OCCUPIED' ? 'bg-emerald-500' :
                          displayStatus === 'VACANT' ? 'bg-slate-400' :
                          displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'
                        }`} />
                        {displayStatus}
                      </span>
                      {contextMode === 'personal' && isOccupied && activeStay && (
                        <div className="text-sm text-slate-600 space-y-0.5">
                          <p>Current guest: <span className="font-medium text-slate-800">{activeStay.guest_name}</span></p>
                          <p>Lease end: <span className="font-medium text-slate-800">{activeStay.stay_end_date}</span></p>
                        </div>
                      )}
                      {displayStatus === 'UNCONFIRMED' && (
                        <p className="text-xs text-amber-700">Confirmation requested but no response received by deadline. Use the confirmation options above.</p>
                      )}
                      {displayStatus === 'UNKNOWN' && (
                        <p className="text-xs text-slate-600">Occupancy was set to Unknown after no response by the deadline. Use Vacant or Occupied above to correct the record.</p>
                      )}
                    </div>
                  </Card>
                  <Card className="p-5 md:p-6 border-slate-200 flex flex-col">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Shield Mode</h3>
                    <div className="flex flex-col gap-3 flex-1 min-h-0">
                      <p className="text-sm text-slate-700">
                        <span className="font-semibold text-emerald-700">Always on</span>
                        {/* Former copy: Status Confirmation (Dead Man&apos;s Switch) runs when leases or stays end. */}
                        {' — '}properties stay in monitored mode. Status Confirmation runs when leases or stays end. The on/off control is temporarily removed (CR-1a).
                      </p>
                      <div className="flex items-center gap-2" aria-label="Shield Mode on">
                        <span className="relative inline-flex h-6 w-11 flex-shrink-0 rounded-full bg-emerald-600 border-2 border-transparent">
                          <span className="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform translate-x-5" />
                        </span>
                        <span className="text-sm font-medium text-slate-800">ON</span>
                      </div>
                      <span className="text-sm text-slate-600">Status: <span className="font-semibold text-slate-800">{shieldStatus}</span></span>
                      {/*
                        DO NOT REMOVE — legacy Shield toggle (restore if SHIELD_MODE_ALWAYS_ON is lifted in backend).
                        <button type="button" role="switch" ... onClick={() => propertiesApi.update(property.id, { shield_mode_enabled: !shieldOn })} />
                      */}
                    </div>
                  </Card>
                  <Card className="p-5 md:p-6 border-slate-200 flex flex-col">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Stay end reminders</h3>
                    <div className="flex flex-col gap-2 flex-1 min-h-0">
                      {contextMode === 'personal' && isOccupied && activeStay ? (
                        <>
                          <span className={`text-sm font-medium ${activeStay.dead_mans_switch_enabled ? 'text-amber-700' : 'text-slate-600'}`}>
                            {activeStay.dead_mans_switch_enabled ? 'On' : 'Off'}
                          </span>
                          <p className="text-xs text-slate-500">Alerts you if the stay ends without checkout or renewal. Shown for current guest stay.</p>
                        </>
                      ) : contextMode === 'personal' && upcomingStayForProperty ? (
                        <>
                          <span className="text-sm font-medium text-slate-600">Off</span>
                          <p className="text-xs text-slate-500">Activates when the guest checks in. Alerts you if the stay ends without checkout or renewal.</p>
                        </>
                      ) : (
                        <span className="text-sm text-slate-500">No active stay at this property.</span>
                      )}
                    </div>
                  </Card>
                </div>
                </>
              )}
            </div>
          </div>
        )}

        {activeTab === 'stay' && contextMode === 'personal' && (
          <Card className="overflow-hidden border-slate-200">
            <div className="p-6">
              <h3 className="text-lg font-semibold text-slate-800 mb-4">Stay (Invite token)</h3>
              {propertyStays.length === 0 ? (
                <p className="text-slate-500">No stays for this property yet. When you invite a guest and they accept, the current stay will appear here with its Invite ID and assignment state.</p>
              ) : (
                <div className="space-y-6">
                  {propertyStays.map((stay) => {
                    const isActive = !stay.checked_out_at && !stay.cancelled_at;
                    const stateLabel = (stay.token_state ?? '—').toUpperCase();
                    const stateClass =
                      stateLabel === 'BURNED'
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : stateLabel === 'STAGED'
                          ? 'bg-sky-50 text-sky-700 border-sky-200'
                          : stateLabel === 'EXPIRED'
                            ? 'bg-slate-100 text-slate-600 border-slate-200'
                            : stateLabel === 'REVOKED'
                              ? 'bg-amber-50 text-amber-700 border-amber-200'
                              : stateLabel === 'CANCELLED'
                                ? 'bg-slate-100 text-slate-600 border-slate-200'
                                : 'bg-slate-100 text-slate-600 border-slate-200';
                    const displayLabel = stateLabel === 'BURNED' ? 'Active' : stateLabel === 'STAGED' ? 'Pending' : stateLabel === 'REVOKED' ? 'Revoked' : stateLabel === 'CANCELLED' ? 'Cancelled' : stateLabel === 'EXPIRED' ? 'Expired' : stateLabel;
                    return (
                      <div key={stay.stay_id} className={`rounded-xl border p-5 ${isActive ? 'border-slate-200 bg-slate-50/50' : 'border-slate-100 bg-white'}`}>
                        <div className="flex flex-wrap items-center gap-2 mb-3">
                          <span className={`inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-semibold uppercase tracking-wide border ${stateClass}`}>
                            {displayLabel}
                          </span>
                          {stay.invitation_only && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">Pending sign-up</span>
                          )}
                          {stay.invite_id && (
                            <span className="text-slate-500 text-sm font-mono">Invite ID: {stay.invite_id}</span>
                          )}
                          {isActive && !stay.invitation_only && <span className="text-xs text-emerald-600 font-medium">Current stay</span>}
                        </div>
                        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                          <div>
                            <dt className="text-slate-500">Guest</dt>
                            <dd className="font-medium text-slate-800">{stay.guest_name}</dd>
                          </div>
                          <div>
                            <dt className="text-slate-500">Check-in</dt>
                            <dd className="font-medium text-slate-800">{stay.stay_start_date}</dd>
                          </div>
                          <div>
                            <dt className="text-slate-500">Check-out</dt>
                            <dd className="font-medium text-slate-800">{stay.stay_end_date}</dd>
                          </div>
                          <div>
                            <dt className="text-slate-500">Status</dt>
                            <dd className="font-medium text-slate-800">
                              {stay.invitation_only ? 'Pending sign-up' : stay.cancelled_at ? 'Cancelled' : stay.checked_out_at ? 'Completed' : stay.revoked_at ? 'Revoked' : isOverstayed(stay.stay_end_date) ? 'Overstayed' : 'Active'}
                            </dd>
                          </div>
                        </dl>
                        {stay.invite_id && (
                          <div className="mt-3 pt-3 border-t border-slate-100">
                            <Button variant="outline" className="text-sm" onClick={() => { setVerifyQRInviteId(stay.invite_id ?? null); setShowVerifyQRModal(true); }}>Verify with QR code</Button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </Card>
        )}

        {activeTab === 'guests' && contextMode === 'personal' && (
          <Card className="overflow-hidden border-slate-200">
            <table className="w-full text-left">
              <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-black">
                <tr>
                  <th className="px-6 py-4 text-center w-20">Risk</th>
                  <th className="px-6 py-4">Guest</th>
                  <th className="px-6 py-4">Check-in</th>
                  <th className="px-6 py-4">Check-out</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {propertyStays.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-500">No guests at this property.</td>
                  </tr>
                ) : (
                  propertyStays.map((stay) => {
                    const overstay = isOverstayed(stay.stay_end_date);
                    return (
                      <tr key={stay.stay_id} className="hover:bg-slate-50 transition-colors group">
                        <td className="px-6 py-5 text-center">
                          <div className={`w-3 h-3 rounded-full mx-auto ${stay.risk_indicator === 'high' ? 'bg-red-500' : stay.risk_indicator === 'medium' ? 'bg-yellow-500' : 'bg-green-500'} shadow-[0_0_8px_rgba(34,197,94,0.6)]`}></div>
                        </td>
                        <td className="px-6 py-5">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-full bg-blue-600/20 text-blue-600 flex items-center justify-center font-black text-xs">{stay.guest_name.charAt(0)}</div>
                            <div>
                              <p className="text-sm font-bold text-slate-800">{stay.guest_name}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-5 text-sm text-slate-600 font-mono">{stay.stay_start_date}</td>
                        <td className="px-6 py-5 text-sm text-slate-600 font-mono">{stay.stay_end_date}</td>
                        <td className="px-6 py-5">
                          <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border ${stay.invitation_only ? 'bg-amber-50 text-amber-600 border-amber-200' : overstay ? 'bg-red-50 text-red-600 border-red-200' : 'bg-green-50 text-green-600 border-green-200'}`}>
                            {stay.invitation_only ? 'Pending sign-up' : overstay ? 'Overstayed' : 'Active'}
                          </span>
                        </td>
                        <td className="px-6 py-5 text-right flex justify-end gap-2">
                          {stay.invite_id && (
                            <Button variant="outline" className="text-xs" onClick={() => { setVerifyQRInviteId(stay.invite_id ?? null); setShowVerifyQRModal(true); }}>Verify QR</Button>
                          )}
                          {!stay.invitation_only && <Button variant="ghost" className="text-xs">Revoke</Button>}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </Card>
        )}

        {activeTab === 'documentation' && (
          <div className="max-w-3xl space-y-8">
            <h3 className="text-3xl font-black text-slate-800 tracking-tighter">Region documentation: {jurisdictionInfo.name}</h3>

            <section>
              <h4 className="text-lg font-bold text-slate-700 mb-4 uppercase tracking-wider">Jurisdiction threshold</h4>
              <p className="text-slate-600 leading-relaxed mb-4">
                {jurisdictionInfo.legalThresholdDays != null
                  ? <>The legal tenancy threshold for {jurisdictionInfo.name} is <strong>{jurisdictionInfo.legalThresholdDays} days</strong>. The platform creates renewed authorization records every <strong>{jurisdictionInfo.platformRenewalCycleDays} days</strong> to interrupt continuity and maintain a defensible audit trail.</>
                  : <>Tenancy in {jurisdictionInfo.name} is {jurisdictionInfo.jurisdictionGroup === 'D' ? 'behavior-based' : 'lease-defined'} (no fixed day threshold). The platform uses a <strong>{jurisdictionInfo.platformRenewalCycleDays}-day</strong> renewal cycle as the default authorization period.</>
                }
              </p>
            </section>

            <section className="p-6 rounded-xl border border-slate-200 bg-slate-50/50">
              <h4 className="text-lg font-bold text-slate-800 mb-4 uppercase tracking-wider">Authorization status categories</h4>
              <div className="grid gap-4 text-sm">
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
                  <span className="font-semibold text-slate-700 mr-2">Within cycle:</span>
                  <span className="text-slate-600">Authorization period under {jurisdictionInfo.platformRenewalCycleDays - jurisdictionInfo.reminderDaysBefore} days. Full documentation active.</span>
                </div>
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
                  <span className="font-semibold text-slate-700 mr-2">Approaching renewal:</span>
                  <span className="text-slate-600">Within {jurisdictionInfo.reminderDaysBefore} days of cycle end. Renewal prompts are sent.</span>
                </div>
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
                  <span className="font-semibold text-slate-700 mr-2">Past cycle:</span>
                  <span className="text-slate-600">Authorization exceeds the {jurisdictionInfo.platformRenewalCycleDays}-day renewal cycle for {jurisdictionInfo.name}. Status and actions are recorded in the audit trail.</span>
                </div>
              </div>
            </section>
          </div>
        )}

        {activeTab === 'logs' && (
          <Card className="overflow-hidden border-slate-200">
            <div className="p-6">
              <h3 className="text-lg font-semibold text-slate-800 mb-2">Event ledger for this property</h3>
              <p className="text-slate-500 text-sm mb-4">Status changes, Shield Mode, guest signatures, and activity for this property. Records cannot be edited or deleted.</p>
              <Button variant="outline" onClick={loadPropertyLogs} disabled={propertyLogsLoading} className="mb-4">
                {propertyLogsLoading ? 'Loading…' : 'Refresh'}
              </Button>
              {propertyLogsLoading && propertyLogs.length === 0 ? (
                <p className="p-8 text-slate-500 text-center">Loading logs…</p>
              ) : propertyLogs.length === 0 ? (
                <p className="p-8 text-slate-500 text-center">No events for this property.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                      <tr>
                        <th className="px-6 py-4">Time</th>
                        <th className="px-6 py-4">Category</th>
                        <th className="px-6 py-4">Title</th>
                        <th className="px-6 py-4">Actor</th>
                        <th className="px-6 py-4">Message</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {propertyLogs.map((entry) => (
                        <tr key={entry.id} className="hover:bg-slate-50">
                          <td className="px-6 py-3 text-slate-600 text-sm whitespace-nowrap">
                            {entry.created_at ? formatLedgerTimestamp(entry.created_at) : '—'}
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
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

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

      <ErrorModal
        open={allUnitsOnsiteConfirm !== null}
        title="Error"
        disableBackdropClose={addResidentModeSaving}
        primaryDisabled={addResidentModeSaving}
        message={
          allUnitsOnsiteConfirm ? (
            <div className="space-y-3 text-sm text-slate-700">
              <p>
                On-site access for <strong>every unit</strong> on this property (including <strong>All units</strong> or the only unit in the list) allows only{' '}
                <strong>one</strong> property manager. To continue, the other assigned manager(s) must be removed from this property. They will lose management access and any Personal Mode links here.
              </p>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Managers who will be removed</p>
                <ul className="list-disc pl-5 space-y-1 text-slate-800">
                  {assignedManagers
                    .filter((x) => x.user_id !== allUnitsOnsiteConfirm.managerUserId)
                    .map((x) => (
                      <li key={x.user_id}>{x.full_name || x.email}</li>
                    ))}
                </ul>
              </div>
            </div>
          ) : (
            ''
          )
        }
        onClose={() => {
          if (addResidentModeSaving) return;
          const mid = allUnitsOnsiteConfirm?.managerUserId;
          setAllUnitsOnsiteConfirm(null);
          if (mid != null) {
            setAddResidentModeForManager((prev) => {
              const next = { ...prev };
              delete next[mid];
              return next;
            });
          }
        }}
        cancelLabel="Cancel"
        actionLabel={addResidentModeSaving ? 'Working…' : 'Remove other managers'}
        onAction={async () => {
          if (!allUnitsOnsiteConfirm || !property) return;
          await submitManagerOnsiteResident(
            allUnitsOnsiteConfirm.managerUserId,
            allUnitsOnsiteConfirm.selection,
            true,
          );
        }}
      />

      <ErrorModal
        open={inviteManagerRemoveOthersConfirm !== null}
        title="Error"
        disableBackdropClose={inviteManagerSending}
        primaryDisabled={inviteManagerSending}
        message={
          inviteManagerRemoveOthersConfirm ? (
            <div className="space-y-3 text-sm text-slate-700">
              <p>
                This property has <strong>only one unit</strong> (or is a single-unit listing). Only <strong>one</strong> property manager can be assigned.
                To invite <strong>{inviteManagerRemoveOthersConfirm}</strong>, the current manager(s) must be removed from this property. They will lose management access and any Personal Mode links here.
              </p>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Managers who will be removed</p>
                <ul className="list-disc pl-5 space-y-1 text-slate-800">
                  {assignedManagers.map((x) => (
                    <li key={x.user_id}>{x.full_name || x.email}</li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            ''
          )
        }
        onClose={() => {
          if (inviteManagerSending) return;
          setInviteManagerRemoveOthersConfirm(null);
        }}
        cancelLabel="Cancel"
        actionLabel={inviteManagerSending ? 'Working…' : 'Remove other managers'}
        onAction={async () => {
          if (!inviteManagerRemoveOthersConfirm || !property) return;
          await submitInviteManager(inviteManagerRemoveOthersConfirm, true);
        }}
      />

      {/* Remove property (soft-delete) - same behaviour as dashboard */}
      <Modal
        open={deleteConfirmOpen && !!property}
        title="Remove Property"
        onClose={() => !deleteSaving && (setDeleteConfirmOpen(false), setDeleteError(null))}
        className="max-w-md"
      >
        <div className="px-6 py-4 space-y-4">
          <p className="text-slate-600 text-sm">
            Remove <span className="font-bold text-slate-800">{property?.name || address || 'this property'}</span> from your dashboard? You can do this even if a guest stay or tenant lease is still on file — nothing is deleted; stays, leases, and the event ledger stay available as history. The property will move to <strong>Inactive properties</strong> and will not appear when creating an invite. You can reactivate it anytime.
          </p>
          {deleteError && <p className="text-sm text-red-600">{deleteError}</p>}
          <div className="flex gap-3">
            <Button variant="outline" onClick={() => { setDeleteConfirmOpen(false); setDeleteError(null); }} disabled={deleteSaving} className="flex-1">Cancel</Button>
            <Button variant="danger" onClick={handleDeleteConfirm} disabled={deleteSaving} className="flex-1">
              {deleteSaving ? 'Removing…' : 'Remove Property'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Edit property modal */}
      <Modal
        open={editOpen && !!property}
        title="Edit Property"
        onClose={() => setEditOpen(false)}
        className="max-w-2xl max-h-[90vh] flex flex-col"
      >
        <div className="px-6 py-4 overflow-y-auto flex-1 min-h-0">
          {editError && <p className="text-sm text-red-600 mb-4">{editError}</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
            {/* Left column: Address */}
            <div className="space-y-3">
              <Input
                label="Property name (optional)"
                name="property_name"
                value={editForm.property_name}
                onChange={(e) => setEditForm({ ...editForm, property_name: e.target.value })}
                placeholder="e.g. Miami Beach Condo"
                className="mb-0"
              />
              <Input
                label="Street address"
                name="street_address"
                value={editForm.street_address}
                onChange={(e) => setEditForm({ ...editForm, street_address: e.target.value })}
                placeholder="123 Main St"
                required
                className="mb-0"
              />
              <div className="grid grid-cols-3 gap-2">
                <Input
                  label="State"
                  name="state"
                  value={editForm.state}
                  onChange={(e) => {
                    const newState = e.target.value;
                    setEditForm({
                      ...editForm,
                      state: newState,
                      city: '' // Reset city when state changes
                    });
                  }}
                  options={US_STATES}
                  required
                  className="mb-0"
                />
                <Input
                  label="City"
                  name="city"
                  value={editForm.city}
                  onChange={(e) => setEditForm({ ...editForm, city: e.target.value })}
                  placeholder={editForm.state ? "Select City" : "Select State first"}
                  options={cityOptions}
                  disabled={!editForm.state}
                  required
                  className="mb-0"
                />
                <Input
                  label="ZIP"
                  name="zip_code"
                  value={editForm.zip_code}
                  onChange={(e) => setEditForm({ ...editForm, zip_code: e.target.value })}
                  placeholder="33139"
                  className="mb-0"
                />
              </div>
              <Input
                label="Region code (optional)"
                name="region_code"
                value={editForm.region_code}
                onChange={(e) => setEditForm({ ...editForm, region_code: e.target.value })}
                placeholder="e.g. FL, CA"
                className="mb-0"
              />
            </div>
            {/* Right column: Property details */}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Property type</label>
                <div className="flex flex-wrap gap-1.5">
                  {PROPERTY_TYPES.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => {
                        const defaultUnits: Record<string, string> = { duplex: '2', triplex: '3', quadplex: '4' };
                        const newUnitCount = MULTI_UNIT_TYPES.includes(t.id) ? (defaultUnits[t.id] ?? editForm.unit_count) : editForm.unit_count;
                        const nc = parseInt(newUnitCount, 10);
                        const safeCount = !isNaN(nc) && nc > 0 ? nc : 0;
                        const newLabels = Array.from({ length: safeCount }, (_, i) => editForm.unit_labels[i] ?? '');
                        setEditForm({ ...editForm, property_type: t.id, unit_count: newUnitCount, unit_labels: newLabels, primary_residence_unit: '' });
                      }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${editForm.property_type === t.id ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-600 hover:text-slate-800'}`}
                    >
                      {t.name}
                    </button>
                  ))}
                </div>
              </div>
              {MULTI_UNIT_TYPES.includes(editForm.property_type) ? (() => {
                const uc = parseInt(editForm.unit_count, 10);
                const validCount = !isNaN(uc) && uc > 0 && uc <= 500 ? uc : 0;
                return (
                <>
                  <Input
                    label="How many units does this property have?"
                    name="unit_count"
                    value={editForm.unit_count}
                    onChange={(e) => {
                      const newCount = e.target.value;
                      const nc = parseInt(newCount, 10);
                      const safeCount = !isNaN(nc) && nc > 0 && nc <= 500 ? nc : 0;
                      const newLabels = Array.from({ length: safeCount }, (_, i) => editForm.unit_labels[i] ?? '');
                      setEditForm({ ...editForm, unit_count: newCount, unit_labels: newLabels, primary_residence_unit: '' });
                    }}
                    placeholder="e.g. 8"
                    className="mb-0"
                  />
                  {validCount > 0 && (
                    <div className="space-y-3">
                      <div>
                        <p className="text-sm font-medium text-slate-700 mb-1">Name each unit</p>
                        <p className="text-xs text-slate-500">Enter the identifier for each unit (e.g., "Apt 101", "Suite 3B").</p>
                      </div>
                      <div className={`grid gap-2 ${validCount <= 4 ? 'grid-cols-2' : validCount <= 9 ? 'grid-cols-3' : 'grid-cols-4'}`}>
                        {Array.from({ length: validCount }, (_, i) => (
                          <input
                            key={i}
                            type="text"
                            value={editForm.unit_labels[i] ?? ''}
                            onChange={(e) => {
                              const newLabels = [...editForm.unit_labels];
                              newLabels[i] = e.target.value;
                              setEditForm({ ...editForm, unit_labels: newLabels });
                            }}
                            placeholder={`Unit ${i + 1}`}
                            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </>
                );
              })() : (
                <>
                  <Input
                    label="Bedrooms"
                    name="bedrooms"
                    value={editForm.bedrooms}
                    onChange={(e) => setEditForm({ ...editForm, bedrooms: e.target.value })}
                    options={[
                      { value: '1', label: '1' },
                      { value: '2', label: '2' },
                      { value: '3', label: '3' },
                      { value: '4', label: '4' },
                      { value: '5', label: '5+' },
                    ]}
                    className="mb-0"
                  />
                </>
              )}
              <Input
                label="Tax ID (optional)"
                name="tax_id"
                value={editForm.tax_id}
                onChange={(e) => setEditForm({ ...editForm, tax_id: e.target.value })}
                placeholder="Property tax ID"
                className="mb-0"
              />
              <Input
                label="APN / Parcel (optional)"
                name="apn"
                value={editForm.apn}
                onChange={(e) => setEditForm({ ...editForm, apn: e.target.value })}
                placeholder="Assessor parcel number"
                className="mb-0"
              />
            </div>
          </div>
        </div>
        <div className="px-6 py-4 border-t border-gray-200 flex gap-3 shrink-0">
          <Button variant="outline" onClick={() => setEditOpen(false)} className="flex-1">Cancel</Button>
          <Button variant="primary" onClick={saveEdit} disabled={editSaving || !editForm.street_address?.trim() || !editForm.city?.trim() || !editForm.state?.trim()} className="flex-1">
            {editSaving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </Modal>

          </>
        )}
      </main>

      {/* Tenant invite modal (owner) */}
      {showInviteTenantModal && (
        <Modal
          open
          onClose={() => {
            setShowInviteTenantModal(false);
            setInviteTenantUnitId(null);
            setInviteTenantLink(null);
            setInviteTenantBatchLinks(null);
            setInviteTenantFormError(null);
            setInviteTenantMode('single');
            setInviteCohortRows(emptyPropertyInviteCohortRows());
            setInviteFirstCohortSharedLease(false);
            setInviteTenantFromUnitCard(false);
            setInviteTenantForm({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '', shared_lease: false });
          }}
          title="Invite tenant"
          className={inviteTenantMode === 'co_tenants' && !inviteTenantLink && !(inviteTenantBatchLinks && inviteTenantBatchLinks.length > 0) ? 'max-w-xl' : 'max-w-lg'}
        >
          <div className="p-6 space-y-4">
            {inviteTenantBatchLinks && inviteTenantBatchLinks.length > 0 ? (
              <>
                {inviteTenantFormError ? (
                  <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-900 font-medium">
                    {inviteTenantFormError}
                  </div>
                ) : null}
                <p className="text-sm text-slate-600">
                  Each co-tenant must use their own link to register. Copy and send individually.
                </p>
                <ul className="space-y-3 max-h-[min(24rem,50vh)] overflow-y-auto pr-1">
                  {inviteTenantBatchLinks.map((item) => (
                    <li key={`${item.tenant_name}-${item.link}`} className="rounded-xl border border-slate-200 bg-slate-50/80 p-3">
                      <p className="text-xs font-semibold text-slate-700 mb-1">{item.tenant_name}</p>
                      <p className="text-xs text-slate-600 break-all font-mono">{item.link}</p>
                      <Button
                        variant="outline"
                        className="mt-2 w-full text-xs h-8"
                        onClick={async () => {
                          const ok = await copyToClipboard(item.link);
                          if (ok) notify('success', 'Link copied.');
                          else notify('error', 'Copy failed.');
                        }}
                      >
                        Copy link
                      </Button>
                    </li>
                  ))}
                </ul>
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={async () => {
                      const blob = inviteTenantBatchLinks.map((b) => `${b.tenant_name}\t${b.link}`).join('\n');
                      const ok = await copyToClipboard(blob);
                      if (ok) notify('success', 'All lines copied (name + tab + link).');
                      else notify('error', 'Copy failed.');
                    }}
                  >
                    Copy all
                  </Button>
                  <Button
                    className="flex-1"
                    onClick={() => {
                      setShowInviteTenantModal(false);
                      setInviteTenantUnitId(null);
                      setInviteTenantLink(null);
                      setInviteTenantBatchLinks(null);
                      setInviteTenantFormError(null);
                      setInviteTenantMode('single');
                      setInviteCohortRows(emptyPropertyInviteCohortRows());
                      setInviteFirstCohortSharedLease(false);
                      setInviteTenantFromUnitCard(false);
                      setInviteTenantForm({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '', shared_lease: false });
                    }}
                  >
                    Done
                  </Button>
                </div>
              </>
            ) : inviteTenantLink ? (
              <>
                <p className="text-sm text-slate-600">Share this link with the tenant. They will use it to sign up and get access to this unit.</p>
                <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 break-all">
                  {inviteTenantLink}
                </div>
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    onClick={async () => {
                      const ok = await copyToClipboard(inviteTenantLink);
                      if (ok) notify('success', 'Link copied to clipboard.');
                      else notify('error', 'Copy failed. Please copy the link manually.');
                    }}
                    className="flex-1"
                  >
                    Copy link
                  </Button>
                  <Button
                    onClick={() => {
                      setShowInviteTenantModal(false);
                      setInviteTenantUnitId(null);
                      setInviteTenantLink(null);
                      setInviteTenantBatchLinks(null);
                      setInviteTenantFormError(null);
                      setInviteTenantMode('single');
                      setInviteCohortRows(emptyPropertyInviteCohortRows());
                      setInviteFirstCohortSharedLease(false);
                      setInviteTenantFromUnitCard(false);
                      setInviteTenantForm({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '', shared_lease: false });
                    }}
                    className="flex-1"
                  >
                    Done
                  </Button>
                </div>
              </>
            ) : (
              <>
                {!inviteTenantFromUnitCard && (
                  <>
                    <div className="flex rounded-lg border border-slate-200 p-1 bg-slate-50 gap-1">
                      <button
                        type="button"
                        className={`flex-1 rounded-md py-2 px-3 text-sm font-medium transition-colors ${
                          inviteTenantMode === 'single' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                        }`}
                        onClick={() => {
                          setInviteTenantMode('single');
                          setInviteTenantFormError(null);
                        }}
                      >
                        One tenant
                      </button>
                      <button
                        type="button"
                        className={`flex-1 rounded-md py-2 px-3 text-sm font-medium transition-colors ${
                          inviteTenantMode === 'co_tenants' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                        }`}
                        onClick={() => {
                          setInviteTenantMode('co_tenants');
                          setInviteTenantFormError(null);
                        }}
                      >
                        Multiple co-tenants
                      </button>
                    </div>
                    {inviteTenantMode === 'co_tenants' && (
                      <p className="text-sm text-slate-600">
                        Same lease dates for everyone. The first new invite uses the option below; each additional person is invited as a shared-lease co-tenant automatically.
                      </p>
                    )}
                  </>
                )}
                {inviteTenantFromUnitCard && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-700 space-y-1">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Unit</p>
                    <p className="font-medium text-slate-900">
                      {property?.is_multi_unit && propertyUnits.length > 0
                        ? `Unit ${propertyUnits.find((u) => u.id === inviteTenantUnitId)?.unit_label ?? inviteTenantUnitId}`
                        : 'Whole property'}
                    </p>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 pt-2">Lease period</p>
                    <p className="text-slate-800">
                      {inviteTenantForm.lease_start_date && inviteTenantForm.lease_end_date
                        ? `${formatCalendarDate(inviteTenantForm.lease_start_date)} – ${formatCalendarDate(inviteTenantForm.lease_end_date)}`
                        : '—'}
                    </p>
                    <p className="text-xs text-slate-500 pt-1">
                      Lease matches the current tenant or stay on this unit. Add the new person&apos;s name and email below, then send the invite.
                    </p>
                  </div>
                )}
                {(property?.is_multi_unit && propertyUnits.length > 0) && !inviteTenantFromUnitCard ? (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">Unit</label>
                    <select
                      value={inviteTenantUnitId ?? ''}
                      onChange={(e) => setInviteTenantUnitId(Number(e.target.value) || null)}
                      className="w-full px-4 py-2.5 bg-white border border-gray-300 rounded-lg text-gray-900"
                    >
                      <option value="">Select unit</option>
                      {propertyUnits.map((u) => (
                        <option key={u.id} value={u.id}>Unit {u.unit_label}</option>
                      ))}
                    </select>
                  </div>
                ) : null}
                {inviteTenantMode === 'single' ? (
                  <>
                    <Input name="tenant_name" label="Tenant name" value={inviteTenantForm.tenant_name} onChange={(e) => { setInviteTenantFormError(null); setInviteTenantForm({ ...inviteTenantForm, tenant_name: e.target.value }); }} placeholder="Full name" required />
                    <Input name="tenant_email" label="Tenant email" type="email" value={inviteTenantForm.tenant_email} onChange={(e) => { setInviteTenantFormError(null); setInviteTenantForm({ ...inviteTenantForm, tenant_email: e.target.value }); }} placeholder="email@example.com" required />
                  </>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-slate-800">Co-tenants</span>
                      <Button
                        type="button"
                        variant="outline"
                        className="text-xs h-8"
                        disabled={inviteCohortRows.length >= MAX_PROPERTY_INVITE_COTENANTS}
                        onClick={() => {
                          setInviteTenantFormError(null);
                          setInviteCohortRows([...inviteCohortRows, { tenant_name: '', tenant_email: '' }]);
                        }}
                      >
                        Add person
                      </Button>
                    </div>
                    <div className="space-y-3 max-h-[min(14rem,40vh)] overflow-y-auto pr-1">
                      {inviteCohortRows.map((row, idx) => (
                        <div key={`prop-cohort-${idx}`} className="rounded-xl border border-slate-200 bg-white p-3 space-y-2">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Person {idx + 1}</span>
                            {inviteCohortRows.length > 2 && (
                              <button
                                type="button"
                                className="text-xs font-medium text-red-600 hover:text-red-700"
                                onClick={() => {
                                  setInviteTenantFormError(null);
                                  setInviteCohortRows(inviteCohortRows.filter((_, j) => j !== idx));
                                }}
                              >
                                Remove
                              </button>
                            )}
                          </div>
                          <Input
                            name={`prop_cohort_name_${idx}`}
                            label="Name"
                            value={row.tenant_name}
                            onChange={(e) => {
                              setInviteTenantFormError(null);
                              const next = [...inviteCohortRows];
                              next[idx] = { ...next[idx], tenant_name: e.target.value };
                              setInviteCohortRows(next);
                            }}
                            placeholder="Full name"
                          />
                          <Input
                            name={`prop_cohort_email_${idx}`}
                            label="Email"
                            type="email"
                            value={row.tenant_email}
                            onChange={(e) => {
                              setInviteTenantFormError(null);
                              const next = [...inviteCohortRows];
                              next[idx] = { ...next[idx], tenant_email: e.target.value };
                              setInviteCohortRows(next);
                            }}
                            placeholder="email@example.com"
                          />
                        </div>
                      ))}
                    </div>
                    <label className="flex items-start gap-3 cursor-pointer rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3">
                      <input
                        type="checkbox"
                        className="mt-1 rounded border-gray-300"
                        checked={inviteFirstCohortSharedLease}
                        onChange={(e) => {
                          setInviteTenantFormError(null);
                          setInviteFirstCohortSharedLease(e.target.checked);
                        }}
                      />
                      <span className="text-sm text-slate-700">
                        <span className="font-medium text-slate-900">First invite overlaps an existing lease or invite</span>
                        <span className="block text-slate-600 mt-0.5">
                          Check if someone already holds or has a pending invite for these dates. Leave unchecked when the unit is empty and everyone listed is new to this window.
                        </span>
                      </span>
                    </label>
                  </div>
                )}
                {!inviteTenantFromUnitCard && (
                  <>
                    <Input name="lease_start_date" label="Lease start" type="date" min={getTodayLocal()} value={inviteTenantForm.lease_start_date} onChange={(e) => { setInviteTenantFormError(null); setInviteTenantForm({ ...inviteTenantForm, lease_start_date: e.target.value }); }} required />
                    <Input name="lease_end_date" label="Lease end" type="date" min={inviteTenantForm.lease_start_date || getTodayLocal()} value={inviteTenantForm.lease_end_date} onChange={(e) => { setInviteTenantFormError(null); setInviteTenantForm({ ...inviteTenantForm, lease_end_date: e.target.value }); }} required />
                  </>
                )}
                {inviteTenantMode === 'single' && !inviteTenantFromUnitCard && (
                  <label className="flex items-start gap-3 cursor-pointer rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3">
                    <input
                      type="checkbox"
                      className="mt-1 rounded border-gray-300"
                      checked={inviteTenantForm.shared_lease}
                      onChange={(e) => {
                        setInviteTenantFormError(null);
                        setInviteTenantForm({ ...inviteTenantForm, shared_lease: e.target.checked });
                      }}
                    />
                    <span className="text-sm text-slate-700">
                      <span className="font-medium text-slate-900">Additional occupant (shared lease)</span>
                      <span className="block text-slate-600 mt-0.5">
                        Allow this invite when another tenant already occupies these dates (co-tenant / roommate).
                      </span>
                    </span>
                  </label>
                )}
                {inviteTenantFormError && !(inviteTenantBatchLinks && inviteTenantBatchLinks.length > 0) && (
                  <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 font-medium">{inviteTenantFormError}</div>
                )}
                <div className="flex gap-3 pt-2">
                  <Button variant="outline" onClick={() => { setShowInviteTenantModal(false); setInviteTenantUnitId(null); setInviteTenantFormError(null); setInviteTenantFromUnitCard(false); }} className="flex-1">Cancel</Button>
                  <Button
                    onClick={async () => {
                      const unitId = inviteTenantUnitId ?? (property?.is_multi_unit ? propertyUnits[0]?.id : 0) ?? (property ? 0 : null);
                      if (unitId == null && property == null) {
                        setInviteTenantFormError('Please select a unit.');
                        return;
                      }
                      if (property?.is_multi_unit && propertyUnits.length > 0 && (inviteTenantUnitId == null || inviteTenantUnitId === 0)) {
                        setInviteTenantFormError('Please select a unit.');
                        return;
                      }
                      if (!inviteTenantFromUnitCard) {
                        if (inviteTenantForm.lease_start_date && inviteTenantForm.lease_start_date < getTodayLocal()) {
                          setInviteTenantFormError('Lease start date cannot be in the past.');
                          return;
                        }
                        if (
                          inviteTenantForm.lease_end_date &&
                          inviteTenantForm.lease_start_date &&
                          parseForDisplay(inviteTenantForm.lease_end_date).getTime() <= parseForDisplay(inviteTenantForm.lease_start_date).getTime()
                        ) {
                          setInviteTenantFormError('Lease end date must be after lease start date.');
                          return;
                        }
                      }
                      if (
                        inviteTenantFromUnitCard &&
                        inviteTenantForm.lease_start_date &&
                        inviteTenantForm.lease_end_date &&
                        parseForDisplay(inviteTenantForm.lease_end_date).getTime() <= parseForDisplay(inviteTenantForm.lease_start_date).getTime()
                      ) {
                        setInviteTenantFormError('Lease end date must be after lease start date.');
                        return;
                      }

                      const postInvite = async (body: {
                        tenant_name: string;
                        tenant_email: string;
                        lease_start_date: string;
                        lease_end_date: string;
                        shared_lease: boolean;
                      }) => {
                        if (unitId === 0 && property) {
                          return propertiesApi.inviteTenantForProperty(property.id, body);
                        }
                        if (unitId != null && unitId > 0) {
                          return propertiesApi.inviteTenant(unitId, body);
                        }
                        throw new Error('Please select a unit.');
                      };

                      if (inviteTenantMode === 'co_tenants') {
                        const ve = validateCoTenantRows(inviteCohortRows);
                        if (ve) {
                          setInviteTenantFormError(ve);
                          return;
                        }
                        setInviteTenantFormError(null);
                        setInviteTenantSubmitting(true);
                        const rows = inviteCohortRows.map((r) => ({
                          tenant_name: r.tenant_name.trim(),
                          tenant_email: r.tenant_email.trim(),
                        }));
                        const results: { tenant_name: string; link: string }[] = [];
                        try {
                          for (let i = 0; i < rows.length; i += 1) {
                            const shared_lease = i === 0 ? inviteFirstCohortSharedLease : true;
                            try {
                              const res = await postInvite({
                                tenant_name: rows[i].tenant_name,
                                tenant_email: rows[i].tenant_email,
                                lease_start_date: inviteTenantForm.lease_start_date,
                                lease_end_date: inviteTenantForm.lease_end_date,
                                shared_lease,
                              });
                              const code = res?.invitation_code;
                              if (!code) {
                                throw new Error('Server did not return an invitation code.');
                              }
                              results.push({
                                tenant_name: rows[i].tenant_name,
                                link: buildGuestInviteUrl(code, { isDemo: Boolean(user.is_demo) }),
                              });
                            } catch (e) {
                              const raw = (e as Error)?.message ?? '';
                              if (results.length > 0) {
                                setInviteTenantBatchLinks(results);
                                setInviteTenantFormError(
                                  raw.includes('overlap') || raw.includes('tenant')
                                    ? raw
                                    : `${toUserFriendlyInvitationError(raw || 'Failed.')} (${results.length} invitation(s) were created; copy those links below.)`,
                                );
                                notify('error', `Stopped at co-tenant ${i + 1}. Earlier links are shown below.`);
                              } else {
                                setInviteTenantFormError(toUserFriendlyInvitationError(raw || 'Failed to create invitation.'));
                              }
                              return;
                            }
                          }
                          setInviteTenantBatchLinks(results);
                          setInviteTenantFormError(null);
                          setInviteCohortRows(emptyPropertyInviteCohortRows());
                          notify('success', `Created ${results.length} tenant invitations.`);
                          loadData();
                          window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                        } finally {
                          setInviteTenantSubmitting(false);
                        }
                        return;
                      }

                      if (!inviteTenantForm.tenant_name.trim() || !inviteTenantForm.tenant_email.trim()) {
                        setInviteTenantFormError('Please enter tenant name and email.');
                        return;
                      }
                      setInviteTenantFormError(null);
                      setInviteTenantSubmitting(true);
                      try {
                        const res = await postInvite(inviteTenantForm);
                        const code = res?.invitation_code;
                        if (code) {
                          setInviteTenantLink(buildGuestInviteUrl(code, { isDemo: Boolean(user.is_demo) }));
                          notify('success', 'Tenant invitation created. Share the invite link with the tenant.');
                          setInviteTenantUnitId(null);
                          setInviteTenantFromUnitCard(false);
                          setInviteTenantForm({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '', shared_lease: false });
                          loadData();
                          window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                        } else {
                          setInviteTenantFormError("We couldn't create a valid invitation link. Please try again.");
                        }
                      } catch (e) {
                        setInviteTenantFormError(toUserFriendlyInvitationError((e as Error)?.message ?? 'Failed to create invitation.'));
                      } finally {
                        setInviteTenantSubmitting(false);
                      }
                    }}
                    disabled={
                      inviteTenantSubmitting ||
                      !inviteTenantForm.lease_start_date ||
                      !inviteTenantForm.lease_end_date ||
                      (!inviteTenantFromUnitCard && property?.is_multi_unit && propertyUnits.length > 0 && (inviteTenantUnitId == null || inviteTenantUnitId === 0)) ||
                      (inviteTenantMode === 'single'
                        ? !inviteTenantForm.tenant_name.trim() || !inviteTenantForm.tenant_email.trim()
                        : !inviteCohortRows.every((r) => r.tenant_name.trim() && r.tenant_email.trim()) || inviteCohortRows.length < 2)
                    }
                    className="flex-1"
                  >
                    {inviteTenantSubmitting
                      ? 'Creating…'
                      : inviteTenantMode === 'co_tenants'
                        ? `Create ${inviteCohortRows.length} invitations`
                        : 'Create invitation'}
                  </Button>
                </div>
              </>
            )}
          </div>
        </Modal>
      )}

      <InviteGuestModal
        open={showInviteModal}
        onClose={() => {
          setShowInviteModal(false);
          setInviteGuestUnitId(null);
          setInviteGuestLabel(null);
        }}
        user={user}
        setLoading={setGlobalLoading}
        notify={notify}
        navigate={navigate}
        initialPropertyId={id}
        unitId={inviteGuestUnitId}
        propertyOrStayLabel={inviteGuestLabel}
      />

      {/* Transfer ownership modal */}
      {showTransferOwnershipModal && property && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-6 shadow-xl border border-slate-200 relative">
            <button
              type="button"
              onClick={() => {
                setShowTransferOwnershipModal(false);
                setTransferOwnershipLink(null);
                setTransferOwnershipError(null);
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-700"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1">Transfer property ownership</h3>
            <p className="text-slate-500 text-sm mb-4">
              Enter the new owner&apos;s email. They must use that same email to register or sign in as a DocuStay owner and accept the transfer.
              Manager assignments, guest stays, tenant leases, and the rest of the property record stay as-is; only who holds owner access in DocuStay changes.
            </p>
            {transferOwnershipLink ? (
              <div className="space-y-3">
                <p className="text-sm text-slate-700">Share this link with the new owner (also sent by email when delivery is configured):</p>
                <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs break-all font-mono text-slate-800">{transferOwnershipLink}</div>
                <div className="flex gap-2">
                  <Button
                    variant="primary"
                    onClick={async () => {
                      const ok = await copyToClipboard(transferOwnershipLink);
                      notify(ok ? 'success' : 'error', ok ? 'Link copied.' : 'Could not copy.');
                    }}
                  >
                    Copy link
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowTransferOwnershipModal(false);
                      setTransferOwnershipLink(null);
                    }}
                  >
                    Done
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <Input
                  label="New owner email"
                  name="transfer_ownership_email"
                  type="email"
                  value={transferOwnershipEmail}
                  onChange={(e) => setTransferOwnershipEmail(e.target.value)}
                  placeholder="newowner@example.com"
                />
                {transferOwnershipError && (
                  <p className="text-sm text-red-600 mt-2">{transferOwnershipError}</p>
                )}
                <div className="flex gap-2 mt-4">
                  <Button
                    variant="primary"
                    disabled={transferOwnershipSending || !transferOwnershipEmail.trim() || !transferOwnershipEmail.includes('@')}
                    onClick={async () => {
                      const email = transferOwnershipEmail.trim();
                      if (!email.includes('@')) return;
                      setTransferOwnershipSending(true);
                      setTransferOwnershipError(null);
                      try {
                        const res = await propertiesApi.createPropertyTransferInvite(property.id, email);
                        const link = res.invite_link || '';
                        if (link) {
                          setTransferOwnershipLink(link);
                          notify('success', res.message || 'Transfer invitation created.');
                          loadData();
                          window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                        } else {
                          setTransferOwnershipError('No link returned. Try again.');
                        }
                      } catch (e) {
                        setTransferOwnershipError((e as Error)?.message || 'Failed to create transfer invitation.');
                      } finally {
                        setTransferOwnershipSending(false);
                      }
                    }}
                  >
                    {transferOwnershipSending ? 'Creating…' : 'Generate link'}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowTransferOwnershipModal(false);
                      setTransferOwnershipError(null);
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Invite Manager modal */}
      {showInviteManagerModal && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-6 shadow-xl border border-slate-200 relative">
            <button
              type="button"
              onClick={() => {
                setShowInviteManagerModal(false);
                setInviteManagerRemoveOthersConfirm(null);
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-700"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1">Invite Property Manager</h3>
            <p className="text-slate-500 text-sm mb-4">
              Enter the manager&apos;s email. They will receive an invitation to sign up and manage this property.
              The same email can be used for different account types (guest/tenant/manager) across DocuStay, but a
              manager can never manage a property they are a tenant or guest of.
            </p>
            <Input
              label="Manager email"
              name="invite_manager_email"
              type="email"
              value={inviteManagerEmail}
              onChange={(e) => setInviteManagerEmail(e.target.value)}
              placeholder="manager@example.com"
            />
            <div className="flex gap-2 mt-4">
              <Button
                variant="primary"
                disabled={inviteManagerSending || !inviteManagerEmail.trim() || !inviteManagerEmail.includes('@')}
                onClick={async () => {
                  const email = inviteManagerEmail.trim();
                  if (!property || !email.includes('@')) return;
                  if (
                    assignedManagers.some(
                      (m) => (m.email || '').trim().toLowerCase() === email.toLowerCase(),
                    )
                  ) {
                    notify('error', 'This manager is already assigned to this property.');
                    return;
                  }
                  const soleScope = !property.is_multi_unit || propertyUnits.length <= 1;
                  if (soleScope && assignedManagers.length > 0) {
                    setInviteManagerRemoveOthersConfirm(email);
                    return;
                  }
                  await submitInviteManager(email, false);
                }}
              >
                {inviteManagerSending ? 'Sending…' : 'Send invitation'}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setShowInviteManagerModal(false);
                  setInviteManagerRemoveOthersConfirm(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Live link QR code modal (same pattern as guest side) */}
      {showLiveLinkQR && property?.live_slug && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-sm w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200 relative">
            <button type="button" onClick={() => setShowLiveLinkQR(false)} className="absolute top-4 right-4 text-slate-400 hover:text-slate-700">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1 text-center">Live link page</h3>
            <p className="text-slate-500 text-sm mb-4 text-center">Scan or share this link to open the property info page (no login).</p>
            <div className="flex justify-center mb-4">
              <div className="bg-slate-50 p-4 rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${property.live_slug}`)}`}
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
                onClick={() => window.open(`${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${property.live_slug}`, '_blank', 'noopener,noreferrer')}
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
                  const url = `${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${property.live_slug}`;
                  const ok = await copyToClipboard(url);
                  setCopyToast(ok ? 'Live link copied to clipboard.' : 'Could not copy. Try selecting the link manually.');
                  setTimeout(() => setCopyToast(null), 3000);
                }}
              >
                Copy live link
              </Button>
              {copyToast && (
                <p className={`text-sm text-center mt-2 ${copyToast.startsWith('Live link') ? 'text-emerald-600' : 'text-amber-600'}`}>
                  {copyToast}
                </p>
              )}
            </div>
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
                onClick={async () => {
                  const url = `${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#check?token=${encodeURIComponent(verifyQRInviteId)}`;
                  const ok = await copyToClipboard(url);
                  setCopyToast(ok ? 'Verify link copied.' : 'Could not copy.');
                  setTimeout(() => setCopyToast(null), 3000);
                }}
              >
                Copy verify link
              </Button>
            </div>
            {copyToast && copyToast.startsWith('Verify link') && (
              <p className="text-sm text-center mt-2 text-emerald-600">{copyToast}</p>
            )}
            {copyToast && copyToast.startsWith('Could not') && (
              <p className="text-sm text-center mt-2 text-amber-600">{copyToast}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
