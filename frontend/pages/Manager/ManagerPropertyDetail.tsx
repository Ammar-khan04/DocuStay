import React, { useState, useEffect, useCallback } from 'react';
import { flushSync } from 'react-dom';
import { Card, Button, Modal } from '../../components/UI';
import { InviteRoleChoiceModal } from '../../components/InviteRoleChoiceModal';
import { InviteTenantModal } from '../../components/InviteTenantModal';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import { UserSession } from '../../types';
import { dashboardApi, getContextMode, setContextMode, openLivePoaPdfInNewTab, APP_ORIGIN, onPropertiesChanged } from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import { ModeSwitcher } from '../../components/ModeSwitcher';
import { DASHBOARD_ALERTS_REFRESH_EVENT } from '../../components/DashboardAlertsPanel';
import { InactivePropertyBanner } from '../../components/InactivePropertyBanner';
import Settings from '../Settings/Settings';
import HelpCenter from '../Support/HelpCenter';
import { JURISDICTION_RULES } from '../../services/jleService';
import { formatStayDuration, formatCalendarDate, formatDateTimeLocal } from '../../utils/dateUtils';
import { scrubAuditLogStateChangeParagraph } from '../../utils/auditLogMessage';
import type { OwnerStayView, OwnerAuditLogEntry, BillingResponse } from '../../services/api';

type ManagerPropertySummary = {
  id: number; name: string | null; address: string;
  street?: string | null; city?: string | null; state?: string | null; zip_code?: string | null;
  occupancy_status: string; unit_count: number; occupied_count: number; region_code?: string | null;
  property_type_label?: string | null; is_multi_unit?: boolean; shield_mode_enabled?: boolean;
  live_slug?: string | null;
  deleted_at?: string | null;
};
type UnitSummary = {
  id: number;
  unit_label: string;
  occupancy_status: string;
  occupied_by?: string | null;
  invite_id?: string | null;
  current_tenant_name?: string | null;
  current_tenant_email?: string | null;
  lease_start_date?: string | null;
  lease_end_date?: string | null;
  lease_cohort_member_count?: number | null;
};

function formatManagerUnitLeaseLine(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return '—';
  if (end) return formatStayDuration(start, end);
  return `${formatCalendarDate(start)} – Open-ended`;
}

const ManagerPropertyDetail: React.FC<{
  propertyId: string;
  user: UserSession;
  navigate: (v: string) => void;
  setLoading?: (l: boolean) => void;
  notify?: (t: 'success' | 'error', m: string) => void;
}> = ({ propertyId, user, navigate, setLoading: setGlobalLoading = (_l: boolean) => {}, notify = (_t: 'success' | 'error', _m: string) => {} }) => {
  const id = Number(propertyId);
  const [property, setProperty] = useState<ManagerPropertySummary | null>(null);
  const [units, setUnits] = useState<UnitSummary[]>([]);
  const [stays, setStays] = useState<OwnerStayView[]>([]);
  const [logs, setLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [personalModeUnits, setPersonalModeUnits] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  type Section = 'overview' | 'guests' | 'invitations' | 'documentation' | 'logs' | 'settings' | 'help';
  const [activeSection, setActiveSection] = useState<Section>('overview');
  const [propertyLogsLoading, setPropertyLogsLoading] = useState(false);
  const [inviteRoleChoiceUnit, setInviteRoleChoiceUnit] = useState<{ unitId: number; unitLabel: string } | null>(null);
  const [inviteTenantModal, setInviteTenantModal] = useState<{ unitId: number; unitLabel: string } | null>(null);
  const [contextMode, setContextModeState] = useState<'business' | 'personal'>(() => getContextMode());
  const [inviteGuestOpen, setInviteGuestOpen] = useState(false);
  const [inviteGuestUnitId, setInviteGuestUnitId] = useState<number | null>(null);
  const [inviteGuestStayLabel, setInviteGuestStayLabel] = useState<string | null>(null);
  const [unitDetailModal, setUnitDetailModal] = useState<UnitSummary | null>(null);
  const [residenceUnitChoice, setResidenceUnitChoice] = useState<number | null>(null);
  const [registerResidenceSaving, setRegisterResidenceSaving] = useState(false);
  const [removeResidenceSaving, setRemoveResidenceSaving] = useState(false);
  const [showLiveLinkQR, setShowLiveLinkQR] = useState(false);
  const [liveLinkCopyToast, setLiveLinkCopyToast] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!id || isNaN(id)) {
      setError('Invalid property');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [prop, unitsData, staysData, logsData, billingData, pmUnits] = await Promise.all([
        dashboardApi.getManagerProperty(id),
        dashboardApi.managerUnits(id),
        dashboardApi.managerStays(),
        dashboardApi.managerLogs({ property_id: id }),
        dashboardApi.managerBilling(),
        dashboardApi.managerPersonalModeUnits().catch(() => ({ unit_ids: [] })),
      ]);
      setProperty(prop);
      setUnits(unitsData || []);
      setStays(staysData || []);
      setLogs(logsData || []);
      setBilling(billingData || null);
      setPersonalModeUnits((pmUnits as { unit_ids: number[] }).unit_ids || []);
    } catch (e) {
      setError((e as Error)?.message ?? 'Failed to load property');
      notify('error', (e as Error)?.message ?? 'Failed to load property');
    } finally {
      setLoading(false);
      setGlobalLoading(false);
    }
  }, [id, notify, setGlobalLoading]);

  useEffect(() => {
    loadData();
  }, [loadData]);

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

  const realUnits = units.filter((u) => u.id > 0);
  useEffect(() => {
    if (realUnits.length === 0) {
      setResidenceUnitChoice(null);
      return;
    }
    setResidenceUnitChoice((prev) => (prev != null && realUnits.some((u) => u.id === prev) ? prev : realUnits[0].id));
  }, [id, units]);

  const loadPropertyLogs = useCallback(async () => {
    setPropertyLogsLoading(true);
    try {
      const l = await dashboardApi.managerLogs({ property_id: id });
      setLogs(l);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to refresh logs');
    } finally {
      setPropertyLogsLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    if (contextMode === 'personal' && activeSection === 'logs') setActiveSection('overview');
    if (contextMode === 'business' && (activeSection === 'guests' || activeSection === 'invitations')) setActiveSection('overview');
  }, [contextMode, activeSection]);

  const propertyStays = stays.filter((s) => s.property_id === id);
  const activeStaysForProperty = propertyStays.filter((s) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);
  const isOccupied = activeStaysForProperty.length > 0;
  const activeStay = activeStaysForProperty[0];
  const upcomingStayForProperty = propertyStays.find((s) => !s.checked_in_at && !s.cancelled_at);
  // Business mode: use property status only (no guest data). Personal mode: use stays for occupancy.
  const isOccupiedForDisplay = contextMode === 'business'
    ? (property?.occupancy_status || '').toLowerCase() === 'occupied'
    : activeStaysForProperty.length > 0;
  const displayStatus = isOccupiedForDisplay ? 'OCCUPIED' : (property?.occupancy_status ?? 'vacant').toUpperCase();
  const propertyLogs = logs.filter((l) => l.property_id === id);
  const hasPersonalModeUnitHere = units.some((u) => u.id > 0 && personalModeUnits.includes(u.id));

  const statusBadge = (status: string) => {
    const s = (status || '').toLowerCase();
    const cls = s === 'occupied' ? 'bg-emerald-100 text-emerald-700' : s === 'vacant' ? 'bg-sky-100 text-sky-700' : s === 'unconfirmed' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600';
    const label = s ? s.charAt(0).toUpperCase() + s.slice(1) : (status || '');
    return <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{label}</span>;
  };

  const handleContextModeChange = useCallback((mode: 'business' | 'personal') => {
    setContextMode(mode);
    flushSync(() => {
      setContextModeState(mode);
      if (mode === 'personal' && activeSection === 'logs') setActiveSection('overview');
      if (mode === 'business' && (activeSection === 'guests' || activeSection === 'invitations')) setActiveSection('overview');
      if (mode === 'business') setStays([]);
    });
    loadData();
  }, [activeSection, loadData]);

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
        <main className="flex-grow flex items-center justify-center p-8">
          <p className="text-slate-600">Loading property…</p>
        </main>
      </div>
    );
  }
  if (error || !property) {
    return (
      <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
        <main className="flex-grow overflow-y-auto p-8">
          <Card className="p-8 text-center max-w-md mx-auto border-slate-200">
            <p className="text-slate-600 mb-4">{error ?? 'Property not found.'}</p>
            <div className="flex gap-3 justify-center">
              <Button variant="outline" onClick={() => navigate('manager-dashboard')}>Back to dashboard</Button>
              <Button variant="primary" onClick={() => loadData()}>Try again</Button>
            </div>
          </Card>
        </main>
      </div>
    );
  }

  const displayName = property.name || property.address || `Property #${property.id}`;

  const contentTabs: Section[] = contextMode === 'personal'
    ? ['overview', 'guests', 'invitations', 'documentation']
    : ['overview', 'documentation', 'logs'];
  const regionKey = property?.region_code === 'NYC' ? 'NY' : (property?.region_code || 'FL');
  const jFallback = JURISDICTION_RULES[regionKey as keyof typeof JURISDICTION_RULES] ?? JURISDICTION_RULES.FL;
  const jurisdictionInfo = {
    name: jFallback.name,
    legalThresholdDays: jFallback.legalThresholdDays,
    platformRenewalCycleDays: jFallback.platformRenewalCycleDays,
    reminderDaysBefore: jFallback.reminderDaysBefore,
    jurisdictionGroup: jFallback.group,
  };

  // In personal mode use the same sidebar as ManagerDashboard: Properties, Guests, Invitations, Settings, Help Center, Mode (no Overview/Documentation/Event ledger)
  const sidebarNavPersonal: { id: Section | 'properties' | 'guests' | 'invitations'; label: string; icon: string }[] = [
    { id: 'properties', label: 'Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'guests', label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
    { id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
    { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  ];
  const sidebarNavBase: { id: Section | 'properties'; label: string; icon: string }[] = [
    { id: 'properties', label: 'Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'overview', label: 'Overview', icon: 'M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z' },
    ...(contextMode === 'personal' ? [{ id: 'guests' as Section, label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' }] : []),
    ...(contextMode === 'personal' ? [{ id: 'invitations' as Section, label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' }] : []),
    { id: 'documentation', label: 'Documentation', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
    ...(contextMode !== 'personal' ? [{ id: 'logs' as Section, label: 'Event ledger', icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' }] : []),
    { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  ];
  const sidebarNav = contextMode === 'personal' ? sidebarNavPersonal : sidebarNavBase;

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {sidebarNav.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                if (item.id === 'properties') {
                  navigate('manager-dashboard');
                } else if (contextMode === 'personal' && (item.id === 'guests' || item.id === 'invitations')) {
                  try { sessionStorage.setItem('manager_initial_tab', item.id); } catch { /* ignore */ }
                  navigate('manager-dashboard');
                } else {
                  setActiveSection(item.id as Section);
                }
              }}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${item.id !== 'properties' && item.id !== 'guests' && item.id !== 'invitations' && activeSection === item.id ? 'bg-slate-100 text-slate-700 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon} /></svg>
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex-grow min-h-0" />
        <div className="mt-6 pt-6 border-t border-slate-200 flex-shrink-0">
          <ModeSwitcher
            contextMode={contextMode}
            personalModeUnits={personalModeUnits}
            onContextModeChange={handleContextModeChange}
            canUsePersonal={true}
          />
        </div>
      </aside>
      <main className="flex-grow overflow-y-auto no-scrollbar bg-transparent p-6 lg:p-8">
        {activeSection === 'settings' ? (
          <div className="w-full"><Settings user={user} navigate={navigate} embedded /></div>
        ) : activeSection === 'help' ? (
          <div className="w-full"><HelpCenter navigate={navigate} embedded /></div>
        ) : (
    <>
      {property.deleted_at ? (
        <div className="mb-6">
          <InactivePropertyBanner role="manager" />
        </div>
      ) : null}
      <header className="mb-8">
        <button
          onClick={() => navigate('manager-dashboard')}
          className="flex items-center gap-2 text-slate-600 hover:text-slate-800 mb-6 text-sm font-medium transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" /></svg>
          Back to dashboard
        </button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl lg:text-3xl font-bold text-slate-800 tracking-tight">{displayName}</h1>
          <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold uppercase ${
            displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
            displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
            displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
            'bg-slate-100 text-slate-600'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${displayStatus === 'OCCUPIED' ? 'bg-emerald-500' : displayStatus === 'VACANT' ? 'bg-slate-400' : displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'}`} />
            {displayStatus}
          </span>
        </div>
        <p className="text-slate-600 mt-1">{property.address || '—'}</p>
        <p className="text-xs text-slate-500 mt-2">{property.occupied_count}/{property.unit_count} units occupied</p>
        <nav className="flex flex-wrap gap-1 mt-6 border-b border-slate-200 -mb-px">
          {contentTabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveSection(tab)}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
                activeSection === tab
                  ? 'border-slate-700 text-slate-800 bg-white'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      {activeSection === 'overview' && (
        <div className="space-y-8">
          {/* Address & property details – same structure as owner */}
          <Card className="p-6 border-slate-200">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Address & property details</h3>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6">
              {[
                { label: 'Street', value: property.street ?? property.address ?? '—' },
                { label: 'City', value: property.city },
                { label: 'State', value: property.state },
                { label: 'ZIP code', value: property.zip_code },
                { label: 'Region', value: property.region_code },
                { label: 'Property type', value: (property.property_type_label ?? '').replace(/_/g, ' ') || '—' },
                ...(property.is_multi_unit
                  ? [{ label: 'Units', value: units.length > 0 ? String(units.length) : String(property.unit_count ?? '—') }]
                  : []),
              ].map(({ label, value }) => (
                <div key={label} className="flex flex-col gap-1">
                  <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</dt>
                  <dd className="text-sm font-medium text-slate-800">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </Card>

          {property.live_slug && (
            <Card className="p-6 border-slate-200">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Live link page</h3>
              <p className="text-sm text-slate-600 mb-4">
                Anyone with this link can view property info, owner contact, current or last stay, and activity log (no login required).
              </p>
              <Button type="button" variant="primary" className="w-full sm:w-auto" onClick={() => setShowLiveLinkQR(true)}>
                Open live link
              </Button>
            </Card>
          )}
          <Card className="p-6 border-slate-200">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Master Power of Attorney</h3>
            {property.live_slug ? (
              <div className="space-y-2">
                <p className="text-sm text-slate-600">
                  Master POA (PDF)
                  <span className="ml-2 text-slate-500">(owner signed)</span>
                </p>
                <Button
                  variant="outline"
                  className="text-sm px-4 py-2"
                  onClick={() => {
                    void openLivePoaPdfInNewTab(property.live_slug!).then((r) => {
                      if (r.ok === false) notify('error', r.userMessage);
                    });
                  }}
                >
                  View POA
                </Button>
              </div>
            ) : (
              <p className="text-sm text-slate-500">No live link is set for this property yet; the POA PDF is available from the live page once the owner completes signing.</p>
            )}
          </Card>

          {/* Occupancy status, Shield Mode, Stay end reminders – same 3-card layout as owner (manager view is read-only for Shield) */}
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
                  <p className="text-xs text-amber-700">Confirmation requested but no response received by deadline. Owner can use the confirmation options.</p>
                )}
              </div>
            </Card>
            <Card className="p-5 md:p-6 border-slate-200 flex flex-col">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Shield Mode</h3>
              <div className="flex flex-col gap-3 flex-1 min-h-0">
                <p className="text-sm text-slate-700">
                  <span className="font-semibold text-emerald-700">Always on</span>
                  {' — '}monitored mode for this property. Managers cannot turn Shield off while this policy is in effect (CR-1a).
                </p>
                <div className="flex items-center gap-2" aria-label="Shield Mode on">
                  <span className="relative inline-flex h-6 w-11 flex-shrink-0 rounded-full bg-emerald-600 border-2 border-transparent">
                    <span className="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 translate-x-5" />
                  </span>
                  <span className="text-sm font-medium text-slate-800">ON</span>
                </div>
                {/*
                  DO NOT REMOVE — manager Shield toggle via bulkShieldMode([id], !shieldOn)
                  <button type="button" role="switch" ... />
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
                    <p className="text-xs text-slate-500">Alerts owner if the stay ends without checkout or renewal. Shown for current guest stay.</p>
                  </>
                ) : contextMode === 'personal' && upcomingStayForProperty ? (
                  <>
                    <span className="text-sm font-medium text-slate-600">Off</span>
                    <p className="text-xs text-slate-500">Activates when the guest checks in. Alerts owner if the stay ends without checkout or renewal.</p>
                  </>
                ) : (
                  <span className="text-sm text-slate-500">No active stay at this property.</span>
                )}
              </div>
            </Card>
          </div>

          {/* Business: manager links assigned property to Personal Mode (on-site resident) — self-service or owner can do the same */}
          {contextMode === 'business' && (
            <Card className="p-6 border-slate-200 border-[#6B90F2]/30 bg-[#f8faff]">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Your residence (Personal Mode)</h3>
              <p className="text-sm text-slate-700 mb-3">
                <strong className="text-slate-900">Business mode</strong> is your management access to this property. <strong className="text-slate-900">Personal mode</strong> is for the unit where you actually live (guest invites for your unit).
                The only link between the two is registering yourself as an <strong className="text-slate-900">on-site resident</strong> for one unit—here, or the owner can do it from their dashboard.
              </p>
              {hasPersonalModeUnitHere ? (
                <div className="space-y-3">
                  <p className="text-sm text-slate-800">
                    You are registered as living on-site for{' '}
                    <span className="font-semibold">
                      Unit {units.find((u) => u.id > 0 && personalModeUnits.includes(u.id))?.unit_label ?? '—'}
                    </span>
                    . Switch to <strong>Personal</strong> in the sidebar for guest tools.
                  </p>
                  <p className="text-xs text-slate-600">Removing this only drops your personal residence link—you stay assigned as property manager.</p>
                  <Button
                    variant="outline"
                    className="border-red-200 text-red-800 hover:bg-red-50"
                    disabled={removeResidenceSaving}
                    onClick={async () => {
                      if (!window.confirm('Remove your on-site resident registration for this property? You will remain assigned as manager. Personal Mode for this unit will end.')) return;
                      setRemoveResidenceSaving(true);
                      try {
                        await dashboardApi.removeMyResidentMode(id);
                        notify('success', 'On-site registration removed. You are still assigned as property manager.');
                        loadData();
                        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                      } catch (e) {
                        notify('error', (e as Error)?.message ?? 'Failed to remove registration.');
                      } finally {
                        setRemoveResidenceSaving(false);
                      }
                    }}
                  >
                    {removeResidenceSaving ? 'Removing…' : 'Remove my on-site registration'}
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  <p className="text-sm text-slate-700">
                    {property.is_multi_unit && realUnits.length > 1 ? (
                      <>Choose the unit you live in, then register. You can only link <strong>one</strong> unit per property.</>
                    ) : (
                      <>Register to connect this assignment to Personal Mode for {realUnits.length === 1 ? `Unit ${realUnits[0].unit_label}` : 'your unit'}.</>
                    )}
                  </p>
                  {property.is_multi_unit && realUnits.length > 1 && (
                    <div className="max-w-xs">
                      <label className="block text-xs font-medium text-slate-600 mb-1">Unit you occupy</label>
                      <select
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
                        value={residenceUnitChoice ?? ''}
                        onChange={(e) => setResidenceUnitChoice(Number(e.target.value) || null)}
                      >
                        {realUnits.map((u) => (
                          <option key={u.id} value={u.id}>
                            Unit {u.unit_label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <Button
                    variant="primary"
                    className="bg-[#6B90F2] hover:bg-[#5a7ed9] border-0"
                    disabled={registerResidenceSaving || (property.is_multi_unit && realUnits.length > 1 && residenceUnitChoice == null)}
                    onClick={async () => {
                      const uid = property.is_multi_unit && realUnits.length > 1 ? residenceUnitChoice : (realUnits[0]?.id ?? null);
                      setRegisterResidenceSaving(true);
                      try {
                        const res = await dashboardApi.registerMyResidentMode(id, uid);
                        notify('success', res.message ?? 'Registered as on-site resident.');
                        loadData();
                        window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
                      } catch (e) {
                        notify('error', (e as Error)?.message ?? 'Registration failed.');
                      } finally {
                        setRegisterResidenceSaving(false);
                      }
                    }}
                  >
                    {registerResidenceSaving ? 'Saving…' : 'Register as on-site resident'}
                  </Button>
                  <p className="text-xs text-slate-500">
                    After registering, use the mode switcher to open <strong>Personal</strong> and this property will appear for your unit only.
                  </p>
                </div>
              )}
            </Card>
          )}

          {/* Presence – only on individual property: in Personal Mode when manager has a personal-mode unit at this property */}
          {contextMode === 'personal' && !hasPersonalModeUnitHere && (
            <Card className="p-6 border-slate-200 border-amber-200 bg-amber-50/50">
              <h3 className="font-medium text-slate-900 mb-2">Personal Mode for this property</h3>
              <p className="text-sm text-slate-700 mb-2">
                To use guest features for your unit, you need an on-site resident link for this property first.
              </p>
              <p className="text-sm text-slate-600">
                Switch to <strong>Business</strong> in the sidebar, open this property, and under <strong>Your residence (Personal Mode)</strong> choose <strong>Register as on-site resident</strong>.
                The property owner can also add you from their property page—either path works.
              </p>
            </Card>
          )}

          {/* Units */}
          <Card className="p-6 border-slate-200">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Units</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {units.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => setUnitDetailModal(u)}
                  className="bg-slate-50 rounded-lg p-3 border border-slate-200 flex flex-col gap-2 w-full text-left cursor-pointer transition-shadow hover:shadow-md hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#6B90F2] focus:ring-offset-2"
                  aria-label={`Open details for unit ${u.unit_label}`}
                >
                  <p className="font-medium text-slate-900">Unit {u.unit_label}</p>
                  {statusBadge(u.occupancy_status)}
                  {contextMode === 'personal' && u.occupied_by && <p className="text-xs text-slate-600">Occupied by {u.occupied_by}</p>}
                  {contextMode === 'personal' && u.invite_id && <p className="text-xs text-slate-500">Invite ID {u.invite_id}</p>}
                  {(u.current_tenant_name || u.current_tenant_email || u.lease_start_date) && (
                    <div className="mt-1 pt-2 border-t border-slate-200/90 space-y-1 text-xs text-slate-600">
                      <p className="font-semibold text-slate-700 uppercase tracking-wide text-[10px]">Current tenant</p>
                      {typeof u.lease_cohort_member_count === 'number' && u.lease_cohort_member_count > 1 ? (
                        <p className="text-[10px] font-semibold text-violet-700 bg-violet-50 border border-violet-100 rounded px-1.5 py-0.5 w-fit">
                          Shared lease · {u.lease_cohort_member_count} tenants
                        </p>
                      ) : null}
                      {u.current_tenant_name ? (
                        <p>
                          <span className="text-slate-500">Name</span>{' '}
                          <span className="font-medium text-slate-800">{u.current_tenant_name}</span>
                        </p>
                      ) : null}
                      {u.current_tenant_email ? (
                        <p className="break-all">
                          <span className="text-slate-500">Email</span>{' '}
                          <span className="font-medium text-slate-800">{u.current_tenant_email}</span>
                        </p>
                      ) : null}
                      {u.lease_start_date ? (
                        <p>
                          <span className="text-slate-500">Lease</span>{' '}
                          <span className="font-medium text-slate-800">{formatManagerUnitLeaseLine(u.lease_start_date, u.lease_end_date)}</span>
                        </p>
                      ) : null}
                    </div>
                  )}
                  {(u.occupancy_status || '').toLowerCase() === 'vacant' && u.id > 0 && (
                    <Button
                      variant="outline"
                      type="button"
                      className="w-full"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (contextMode === 'personal') {
                          setInviteGuestUnitId(u.id);
                          setInviteGuestStayLabel(`Unit ${u.unit_label}`);
                          setInviteGuestOpen(true);
                        } else {
                          setInviteRoleChoiceUnit({ unitId: u.id, unitLabel: u.unit_label });
                        }
                      }}
                    >
                      Invite
                    </Button>
                  )}
                </button>
              ))}
            </div>
          </Card>
        </div>
      )}

      {activeSection === 'guests' && contextMode === 'personal' && (
        <Card className="p-6 overflow-x-auto">
          <h2 className="font-semibold text-slate-900 mb-2">Guests</h2>
          <p className="text-slate-500 text-sm mb-4">View-only. Guest stays at this property.</p>
          {propertyStays.length === 0 ? (
            <p className="text-slate-500 text-sm">No guests.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-600">
                  <th className="pb-2 pr-4">Risk</th>
                  <th className="pb-2 pr-4">Guest</th>
                  <th className="pb-2 pr-4">Check-in</th>
                  <th className="pb-2 pr-4">Check-out</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {propertyStays.map((s) => {
                  const risk = (s.risk_indicator || 'unknown').toLowerCase();
                  const riskClass = risk === 'high' ? 'text-red-600' : risk === 'medium' ? 'text-amber-600' : 'text-slate-600';
                  const status = s.revoked_at ? 'Revoked' : s.checked_out_at ? 'Checked out' : s.checked_in_at ? 'Active' : s.cancelled_at ? 'Cancelled' : 'Upcoming';
                  return (
                    <tr key={s.stay_id} className="border-b border-slate-100 last:border-0">
                      <td className={`py-3 pr-4 capitalize font-medium ${riskClass}`}>{risk}</td>
                      <td className="py-3 pr-4">{s.guest_name}</td>
                      <td className="py-3 pr-4">{s.stay_start_date}</td>
                      <td className="py-3 pr-4">{s.stay_end_date}</td>
                      <td className="py-3">{status}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {activeSection === 'invitations' && contextMode === 'personal' && (
        <Card className="p-6">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <div>
              <h2 className="font-semibold text-slate-900">Invitations</h2>
              <p className="text-slate-500 text-sm">Guest invitation links for this property. Create an invite and share the link.</p>
            </div>
            <Button
              variant="primary"
              onClick={() => {
                if (contextMode === 'personal') {
                  setInviteGuestUnitId(null);
                  setInviteGuestStayLabel(null);
                  setInviteGuestOpen(true);
                } else {
                  setInviteRoleChoiceUnit({ unitId: 0, unitLabel: '' });
                }
              }}
            >
              Invite
            </Button>
          </div>
          {(() => {
            const invitationStays = propertyStays.filter((s) => s.invitation_only || (s.token_state || '').toUpperCase() === 'STAGED' || (s.token_state || '').toUpperCase() === 'BURNED');
            if (invitationStays.length === 0) {
              return <p className="text-slate-500 text-sm">No invitations yet. Use &quot;Invite&quot; to add a guest.</p>;
            }
            return (
              <ul className="space-y-4">
                {invitationStays.map((s) => {
                  const state = (s.token_state || (s.invitation_only ? 'BURNED' : '')).toUpperCase();
                  const stateBadge =
                    state === 'STAGED' ? 'bg-amber-100 text-amber-800' :
                    state === 'BURNED' ? 'bg-emerald-100 text-emerald-800' :
                    state === 'EXPIRED' ? 'bg-slate-200 text-slate-700' :
                    state === 'REVOKED' ? 'bg-red-100 text-red-800' : 'bg-slate-100 text-slate-600';
                  const displayLabel = state === 'BURNED' ? 'Active' : state === 'STAGED' ? 'Pending' : state === 'REVOKED' ? 'Revoked' : state === 'EXPIRED' ? 'Expired' : state === 'CANCELLED' ? 'Cancelled' : state;
                  return (
                    <li key={s.stay_id} className="p-4 rounded-xl border border-slate-200 bg-slate-50/50">
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span className="font-medium text-slate-900">{s.guest_name}</span>
                        {state && <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${stateBadge}`}>{displayLabel}</span>}
                        {s.checked_in_at && !s.checked_out_at && !s.cancelled_at && (
                          <span className="text-xs font-medium text-emerald-700">Active</span>
                        )}
                      </div>
                      <p className="text-sm text-slate-600">
                        {formatStayDuration(s.stay_start_date, s.stay_end_date)}
                        {' · '}Check-in: {s.stay_start_date} · Check-out: {s.stay_end_date}
                      </p>
                      {s.invite_id && <p className="text-xs text-slate-500 mt-1">Invite: {s.invite_id}</p>}
                    </li>
                  );
                })}
              </ul>
            );
          })()}
        </Card>
      )}

      {activeSection === 'documentation' && (
        <div className="space-y-8">
          <h3 className="text-3xl font-black text-slate-800 tracking-tighter">Region documentation: {jurisdictionInfo.name}</h3>
          <section>
            <p className="text-slate-600 leading-relaxed mb-4">
              {jurisdictionInfo.legalThresholdDays != null
                ? <>The legal tenancy threshold for {jurisdictionInfo.name} is <strong>{jurisdictionInfo.legalThresholdDays} days</strong>. The platform renews authorizations every <strong>{jurisdictionInfo.platformRenewalCycleDays} days</strong> to maintain a defensible audit trail.</>
                : <>Tenancy in {jurisdictionInfo.name} is {jurisdictionInfo.jurisdictionGroup === 'D' ? 'behavior-based' : 'lease-defined'}. The platform uses a <strong>{jurisdictionInfo.platformRenewalCycleDays}-day</strong> renewal cycle.</>
              }
            </p>
          </section>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200">
              <p className="font-semibold text-emerald-800">Within cycle</p>
              <span className="text-slate-600">Authorization under {jurisdictionInfo.platformRenewalCycleDays - jurisdictionInfo.reminderDaysBefore} days. Full documentation active.</span>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
              <p className="font-semibold text-slate-800">Approaching renewal</p>
              <span className="text-slate-600">Within {jurisdictionInfo.reminderDaysBefore} days of cycle end. Renewal prompts sent.</span>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
              <p className="font-semibold text-slate-800">Past cycle</p>
              <span className="text-slate-600">Authorization exceeds the {jurisdictionInfo.platformRenewalCycleDays}-day cycle for {jurisdictionInfo.name}. Recorded in audit trail.</span>
            </div>
          </div>
        </div>
      )}

      {activeSection === 'logs' && (
        <Card className="p-6">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <div>
              <h2 className="font-semibold text-slate-900">Event ledger for this property</h2>
              <p className="text-slate-500 text-sm">Audit trail for status changes, guest activity, and related events. View-only.</p>
            </div>
            <Button variant="outline" onClick={loadPropertyLogs} disabled={propertyLogsLoading}>{propertyLogsLoading ? 'Refreshing…' : 'Refresh'}</Button>
          </div>
          {propertyLogs.length === 0 ? (
            <p className="text-slate-500 text-sm">No events.</p>
          ) : (
            <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white border-b border-slate-200">
                  <tr className="text-left text-slate-600">
                    <th className="pb-2 pr-4">Time</th>
                    <th className="pb-2 pr-4">Category</th>
                    <th className="pb-2 pr-4">Title</th>
                    <th className="pb-2 pr-4">Actor</th>
                    <th className="pb-2">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {propertyLogs.map((r) => (
                    <tr key={r.id} className="border-b border-slate-100 last:border-0">
                      <td className="py-2 pr-4 text-slate-500 whitespace-nowrap">{r.created_at ? formatDateTimeLocal(r.created_at) : '—'}</td>
                      <td className="py-2 pr-4">{r.category || '—'}</td>
                      <td className="py-2 pr-4 font-medium">{r.title}</td>
                      <td className="py-2 pr-4">{r.actor_email || (r.actor_user_id != null ? `User #${r.actor_user_id}` : '—')}</td>
                      <td className="py-2">{scrubAuditLogStateChangeParagraph(r.message) || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <Modal
        open={unitDetailModal != null}
        title={unitDetailModal ? `Unit ${unitDetailModal.unit_label}` : 'Unit'}
        onClose={() => setUnitDetailModal(null)}
        className="max-w-lg"
      >
        {unitDetailModal && (
          <div className="px-6 py-5 space-y-4 text-sm text-slate-800">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</span>
              {statusBadge(unitDetailModal.occupancy_status)}
            </div>
            {contextMode === 'personal' && unitDetailModal.occupied_by && (
              <p className="text-xs text-slate-600">Occupied by {unitDetailModal.occupied_by}</p>
            )}
            {contextMode === 'personal' && unitDetailModal.invite_id && (
              <p className="text-xs text-slate-500">Invite ID {unitDetailModal.invite_id}</p>
            )}
            {(unitDetailModal.current_tenant_name || unitDetailModal.current_tenant_email || unitDetailModal.lease_start_date) && (
              <div className="pt-2 border-t border-slate-200 space-y-1 text-xs text-slate-600">
                <p className="font-semibold text-slate-700 uppercase tracking-wide text-[10px]">Current tenant</p>
                {typeof unitDetailModal.lease_cohort_member_count === 'number' && unitDetailModal.lease_cohort_member_count > 1 ? (
                  <p className="text-[10px] font-semibold text-violet-700 bg-violet-50 border border-violet-100 rounded px-1.5 py-0.5 w-fit">
                    Shared lease · {unitDetailModal.lease_cohort_member_count} tenants
                  </p>
                ) : null}
                {unitDetailModal.current_tenant_name ? (
                  <p>
                    <span className="text-slate-500">Name</span>{' '}
                    <span className="font-medium text-slate-800">{unitDetailModal.current_tenant_name}</span>
                  </p>
                ) : null}
                {unitDetailModal.current_tenant_email ? (
                  <p className="break-all">
                    <span className="text-slate-500">Email</span>{' '}
                    <span className="font-medium text-slate-800">{unitDetailModal.current_tenant_email}</span>
                  </p>
                ) : null}
                {unitDetailModal.lease_start_date ? (
                  <p>
                    <span className="text-slate-500">Lease</span>{' '}
                    <span className="font-medium text-slate-800">{formatManagerUnitLeaseLine(unitDetailModal.lease_start_date, unitDetailModal.lease_end_date)}</span>
                  </p>
                ) : null}
              </div>
            )}
            <div className="border-t border-slate-200 pt-4 mt-2 flex flex-wrap gap-2">
              {(unitDetailModal.occupancy_status || '').toLowerCase() === 'vacant' && unitDetailModal.id > 0 && (
                <Button
                  variant="primary"
                  type="button"
                  onClick={() => {
                    const u = unitDetailModal;
                    setUnitDetailModal(null);
                    if (contextMode === 'personal') {
                      setInviteGuestUnitId(u.id);
                      setInviteGuestStayLabel(`Unit ${u.unit_label}`);
                      setInviteGuestOpen(true);
                    } else {
                      setInviteRoleChoiceUnit({ unitId: u.id, unitLabel: u.unit_label });
                    }
                  }}
                >
                  Send invite
                </Button>
              )}
            </div>
          </div>
        )}
      </Modal>

      <InviteRoleChoiceModal
        open={!!inviteRoleChoiceUnit}
        onClose={() => setInviteRoleChoiceUnit(null)}
        contextLabel={inviteRoleChoiceUnit?.unitId ? `Unit ${inviteRoleChoiceUnit.unitLabel}` : undefined}
        onSelectTenant={() => {
          if (inviteRoleChoiceUnit) {
            setInviteTenantModal({ unitId: inviteRoleChoiceUnit.unitId, unitLabel: inviteRoleChoiceUnit.unitLabel });
          }
          setInviteRoleChoiceUnit(null);
        }}
        onSelectGuest={() => {
          if (inviteRoleChoiceUnit?.unitId && inviteRoleChoiceUnit.unitId > 0) {
            setInviteGuestUnitId(inviteRoleChoiceUnit.unitId);
            setInviteGuestStayLabel(`Unit ${inviteRoleChoiceUnit.unitLabel}`);
          } else {
            setInviteGuestUnitId(null);
            setInviteGuestStayLabel(null);
          }
          setInviteGuestOpen(true);
          setInviteRoleChoiceUnit(null);
        }}
      />

      <InviteTenantModal
        open={!!inviteTenantModal}
        onClose={() => setInviteTenantModal(null)}
        properties={property ? [{ id: property.id, name: property.name, address: property.address }] : []}
        getUnits={() => Promise.resolve((units || []).filter((u) => u.id >= 0).map((u) => ({ id: u.id, unit_label: u.unit_label })))}
        preselectedUnit={inviteTenantModal ?? undefined}
        createInvitation={(params) =>
          dashboardApi.managerInviteTenant(params.unitId!, {
            tenant_name: params.tenant_name,
            tenant_email: params.tenant_email,
            lease_start_date: params.lease_start_date,
            lease_end_date: params.lease_end_date,
            shared_lease: params.shared_lease,
          }).then((r) => ({ invitation_code: r.invitation_code }))
        }
        notify={notify}
        onSuccess={loadData}
        guestInviteUrlIsDemo={Boolean(user?.is_demo)}
      />

      <InviteGuestModal
        open={inviteGuestOpen}
        onClose={() => {
          setInviteGuestOpen(false);
          setInviteGuestUnitId(null);
          setInviteGuestStayLabel(null);
        }}
        user={user}
        setLoading={(x) => { setGlobalLoading(x); }}
        notify={notify}
        onSuccess={loadData}
        initialPropertyId={property?.id ?? null}
        unitId={inviteGuestUnitId}
        propertyOrStayLabel={inviteGuestStayLabel}
        propertiesLoader={() => dashboardApi.managerProperties()}
        unitsLoader={(pid) => dashboardApi.managerUnits(pid)}
      />

      {showLiveLinkQR && property?.live_slug && (
        <div className="fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
          <div className="max-w-sm w-full rounded-2xl bg-white p-8 shadow-xl border border-slate-200 relative">
            <button
              type="button"
              onClick={() => {
                setShowLiveLinkQR(false);
                setLiveLinkCopyToast(null);
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-700"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-900 mb-1 text-center">Live link page</h3>
            <p className="text-slate-500 text-sm mb-4 text-center">Scan or share this link to open the property info page (no login).</p>
            <div className="flex justify-center mb-4">
              <div className="bg-slate-50 p-4 rounded-xl">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(
                    `${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${property.live_slug}`,
                  )}`}
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
                onClick={() =>
                  window.open(
                    `${typeof window !== 'undefined' ? window.location.origin : APP_ORIGIN}/#live/${property.live_slug}`,
                    '_blank',
                    'noopener,noreferrer',
                  )
                }
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
                  setLiveLinkCopyToast(
                    ok ? 'Live link copied to clipboard.' : 'Could not copy. Try selecting the link manually.',
                  );
                  setTimeout(() => setLiveLinkCopyToast(null), 3000);
                }}
              >
                Copy live link
              </Button>
              {liveLinkCopyToast && (
                <p
                  className={`text-sm text-center mt-2 ${liveLinkCopyToast.startsWith('Live link') ? 'text-emerald-600' : 'text-amber-600'}`}
                >
                  {liveLinkCopyToast}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </>
        )}
      </main>
    </div>
  );
};

export default ManagerPropertyDetail;
