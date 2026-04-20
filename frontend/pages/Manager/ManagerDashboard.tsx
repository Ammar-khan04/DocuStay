import React, { useState, useEffect, useCallback } from 'react';
import { flushSync } from 'react-dom';
import { Card, Button, Modal } from '../../components/UI';
import { InviteRoleChoiceModal } from '../../components/InviteRoleChoiceModal';
import { InviteTenantModal } from '../../components/InviteTenantModal';
import { InviteGuestModal } from '../../components/InviteGuestModal';
import { UserSession } from '../../types';
import { dashboardApi, getContextMode, setContextMode, buildGuestInviteUrl, demoStoredUnsignedGuestAgreementPdfUrl, type OwnerInvitationView, type OwnerAuditLogEntry } from '../../services/api';
import { ModeSwitcher } from '../../components/ModeSwitcher';
import Settings from '../Settings/Settings';
import HelpCenter from '../Support/HelpCenter';
import { InvitationsTabContent } from '../../components/InvitationsTabContent';
import { DashboardAlertsPanel, DASHBOARD_ALERTS_REFRESH_EVENT } from '../../components/DashboardAlertsPanel';
import { InactivePropertyBanner } from '../../components/InactivePropertyBanner';
import { copyToClipboard } from '../../utils/clipboard';
import { formatStayDuration, formatLedgerTimestamp, formatCalendarDate } from '../../utils/dateUtils';

interface PropertySummary {
  id: number;
  name: string | null;
  address: string;
  occupancy_status: string;
  unit_count: number;
  occupied_count: number;
  shield_mode_enabled?: boolean;
  deleted_at?: string | null;
}

interface UnitSummary {
  id: number;
  unit_label: string;
  occupancy_status: string;
}

const ManagerDashboard: React.FC<{
  user: UserSession;
  navigate: (v: string) => void;
  setLoading?: (l: boolean) => void;
  notify?: (t: 'success' | 'error', m: string) => void;
}> = ({ user, navigate, setLoading = (_l: boolean) => {}, notify = (_t: 'success' | 'error', _m: string) => {} }) => {
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [loading, setLoadingState] = useState(true);
  const [expandedPropertyId, setExpandedPropertyId] = useState<number | null>(null);
  const [units, setUnits] = useState<UnitSummary[]>([]);
  const [unitsLoading, setUnitsLoading] = useState(false);
  type ManagerTab = 'properties' | 'guests' | 'invitations' | 'logs' | 'billing' | 'settings' | 'help';
  const [activeTab, setActiveTab] = useState<ManagerTab>('properties');
  const [stays, setStays] = useState<any[]>([]);
  const [invitations, setInvitations] = useState<OwnerInvitationView[]>([]);
  const [logs, setLogs] = useState<OwnerAuditLogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsFromTs, setLogsFromTs] = useState('');
  const [logsToTs, setLogsToTs] = useState('');
  const [logsCategory, setLogsCategory] = useState('');
  const [logsSearch, setLogsSearch] = useState('');
  const [logMessageModalEntry, setLogMessageModalEntry] = useState<OwnerAuditLogEntry | null>(null);
  const [billing, setBilling] = useState<any>(null);
  const [personalModeUnits, setPersonalModeUnits] = useState<number[]>([]);
  const [contextMode, setContextModeState] = useState<'business' | 'personal'>(() => getContextMode());
  const [inviteRoleChoiceUnit, setInviteRoleChoiceUnit] = useState<{ unitId: number; unitLabel: string } | null>(null);
  const [showSelectPropertyUnitModal, setShowSelectPropertyUnitModal] = useState(false);
  const [inviteSelectPropertyId, setInviteSelectPropertyId] = useState<number | null>(null);
  const [inviteSelectUnits, setInviteSelectUnits] = useState<UnitSummary[]>([]);
  const [inviteSelectUnitId, setInviteSelectUnitId] = useState<number | null>(null);
  const [inviteSelectUnitsLoading, setInviteSelectUnitsLoading] = useState(false);
  const [inviteTenantModal, setInviteTenantModal] = useState<{ unitId: number; unitLabel: string } | null>(null);
  const [inviteGuestOpen, setInviteGuestOpen] = useState(false);
  const [inviteGuestUnitId, setInviteGuestUnitId] = useState<number | null>(null);
  /** CR-1a: Shield always on — OFF filter removed from UI (DO NOT REMOVE 'off' in types if policy reverts). */
  const [shieldFilter, setShieldFilter] = useState<'all' | 'on'>('all');
  const [propertiesCountFilter, setPropertiesCountFilter] = useState<null | 'properties' | 'occupied' | 'vacant' | 'unknown' | 'shield_on'>(null);
  const [selectedPropertyIds, setSelectedPropertyIds] = useState<Set<number>>(new Set());
  const [bulkShieldLoading, setBulkShieldLoading] = useState(false);

  const managerOccupiedUnitsTotal = React.useMemo(
    () => properties.reduce((s, p) => s + (p.occupied_count ?? 0), 0),
    [properties]
  );
  const managerVacantUnitsTotal = React.useMemo(
    () =>
      properties.reduce((s, p) => {
        const uc = p.unit_count ?? 1;
        const oc = p.occupied_count ?? 0;
        return s + Math.max(0, uc - oc);
      }, 0),
    [properties]
  );

  const managerFilteredProperties = React.useMemo(() => {
    let list = shieldFilter === 'all' ? properties : properties.filter((p) => p.shield_mode_enabled);
    if (propertiesCountFilter === 'occupied') list = list.filter((p) => (p.occupancy_status || '').toLowerCase() === 'occupied');
    else if (propertiesCountFilter === 'vacant') list = list.filter((p) => (p.occupancy_status || '').toLowerCase() === 'vacant');
    else if (propertiesCountFilter === 'unknown') list = list.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase()));
    else if (propertiesCountFilter === 'shield_on') list = list.filter((p) => p.shield_mode_enabled);
    return list;
  }, [properties, shieldFilter, propertiesCountFilter]);

  const setLoadingWrapper = (x: boolean) => {
    setLoadingState(x);
    setLoading(x);
  };

  const loadData = useCallback(async () => {
    setLoadingWrapper(true);
    try {
      const [propsData, pmUnits, staysData, invitationsData] = await Promise.all([
        dashboardApi.managerProperties(),
        dashboardApi.managerPersonalModeUnits().catch(() => ({ unit_ids: [] })),
        dashboardApi.managerStays().catch(() => []),
        dashboardApi.managerInvitations().catch(() => []),
      ]);
      setProperties(propsData || []);
      setPersonalModeUnits((pmUnits as { unit_ids: number[] }).unit_ids || []);
      setStays(staysData || []);
      setInvitations(invitationsData || []);
    } catch (e) {
      notify('error', (e as Error)?.message || 'Failed to load dashboard');
    } finally {
      setLoadingWrapper(false);
    }
  }, [notify]);

  useEffect(() => {
    loadData();
  }, [loadData]);
  useEffect(() => {
    try {
      const tab = typeof window !== 'undefined' ? sessionStorage.getItem('manager_initial_tab') : null;
      if (tab === 'guests' || tab === 'invitations') {
        sessionStorage.removeItem('manager_initial_tab');
        setActiveTab(tab);
      }
    } catch { /* ignore */ }
  }, []);

  const loadInvitationsAndStays = useCallback(() => {
    Promise.all([
      dashboardApi.managerStays().catch(() => []),
      dashboardApi.managerInvitations().catch(() => []),
    ]).then(([staysData, invitationsData]) => {
      setStays(staysData || []);
      setInvitations(invitationsData || []);
    });
  }, []);
  useEffect(() => {
    if (activeTab === 'guests' || activeTab === 'invitations') loadInvitationsAndStays();
  }, [activeTab, loadInvitationsAndStays]);
  useEffect(() => {
    if (contextMode === 'personal' && (activeTab === 'billing' || activeTab === 'logs')) setActiveTab('properties');
    if (contextMode === 'business' && (activeTab === 'guests' || activeTab === 'invitations')) setActiveTab('properties');
  }, [contextMode, activeTab]);
  const loadLogs = useCallback(() => {
    setLogsLoading(true);
    dashboardApi.managerLogs({
      from_ts: logsFromTs ? new Date(logsFromTs).toISOString() : undefined,
      to_ts: logsToTs ? new Date(logsToTs).toISOString() : undefined,
      category: logsCategory || undefined,
      search: logsSearch.trim() || undefined,
    })
      .then(setLogs)
      .catch(() => setLogs([]))
      .finally(() => setLogsLoading(false));
  }, [logsFromTs, logsToTs, logsCategory, logsSearch]);

  useEffect(() => {
    if (activeTab === 'logs') loadLogs();
  }, [activeTab]);
  useEffect(() => {
    if (activeTab === 'billing') dashboardApi.managerBilling().then(setBilling).catch(() => setBilling(null));
  }, [activeTab]);

  useEffect(() => {
    if (!showSelectPropertyUnitModal || !inviteSelectPropertyId) {
      setInviteSelectUnits([]);
      setInviteSelectUnitId(null);
      return;
    }
    setInviteSelectUnitsLoading(true);
    dashboardApi.managerUnits(inviteSelectPropertyId)
      .then((u) => {
        setInviteSelectUnits(u || []);
        setInviteSelectUnitId((u && u[0]?.id) ?? null);
      })
      .catch(() => setInviteSelectUnits([]))
      .finally(() => setInviteSelectUnitsLoading(false));
  }, [showSelectPropertyUnitModal, inviteSelectPropertyId]);

  const handleContextModeChange = useCallback((mode: 'business' | 'personal') => {
    setContextMode(mode);
    flushSync(() => {
      setContextModeState(mode);
      if (mode === 'personal' && (activeTab === 'billing' || activeTab === 'logs')) setActiveTab('properties');
      if (mode === 'business' && (activeTab === 'guests' || activeTab === 'invitations')) setActiveTab('properties');
      // Clear guest-related state immediately so no data carries over between modes
      if (mode === 'business') {
        setStays([]);
        setInvitations([]);
      }
    });
    loadData();
  }, [activeTab, loadData]);

  const loadUnits = async (propertyId: number) => {
    if (expandedPropertyId === propertyId) {
      setExpandedPropertyId(null);
      return;
    }
    setUnitsLoading(true);
    try {
      const data = await dashboardApi.managerUnits(propertyId);
      setUnits(data || []);
      setExpandedPropertyId(propertyId);
    } catch (e) {
      notify('error', (e as Error)?.message || 'Failed to load units');
    } finally {
      setUnitsLoading(false);
    }
  };

  const statusBadge = (status: string) => {
    const s = (status || '').toLowerCase();
    const cls =
      s === 'occupied' ? 'bg-emerald-100 text-emerald-700'
      : s === 'vacant' ? 'bg-sky-100 text-sky-700'
      : s === 'unconfirmed' ? 'bg-amber-100 text-amber-700'
      : 'bg-slate-100 text-slate-600';
    return <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{status}</span>;
  };

  const activeStays = stays.filter((s: any) => s.checked_in_at && !s.checked_out_at && !s.cancelled_at);

  const sidebarNavBase: { id: ManagerTab; label: string; icon: string }[] = [
    { id: 'properties', label: 'Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    ...(contextMode === 'personal' ? [{ id: 'guests' as ManagerTab, label: 'Guests', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' }] : []),
    ...(contextMode === 'personal' ? [{ id: 'invitations' as ManagerTab, label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' }] : []),
    ...(contextMode !== 'personal' ? [{ id: 'logs' as ManagerTab, label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' }] : []),
    ...(contextMode !== 'personal' ? [{ id: 'billing' as ManagerTab, label: 'Billing', icon: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2H9v2h2v6a2 2 0 002 2h2a2 2 0 002-2v-6h2V9zm-6 0V7a2 2 0 00-2-2H5a2 2 0 00-2 2v2h4z' }] : []),
    { id: 'settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    { id: 'help', label: 'Help Center', icon: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  ];
  const sidebarNav = sidebarNavBase;

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar – same layout as Owner dashboard */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {sidebarNav.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${activeTab === item.id ? 'bg-slate-100 text-slate-700 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon}></path></svg>
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
            canUsePersonal={personalModeUnits.length > 0 || properties.length > 0}
          />
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-grow overflow-y-auto no-scrollbar bg-transparent p-8">
        {/* Mobile tab nav when sidebar is hidden */}
        <div className="lg:hidden mb-6">
          <label htmlFor="manager-mobile-tab" className="sr-only">Navigate to</label>
          <select
            id="manager-mobile-tab"
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value as ManagerTab)}
            className="w-full max-w-xs rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            {sidebarNav.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </div>

        {activeTab === 'settings' ? (
          <div className="w-full">
            <Settings user={user} navigate={navigate} embedded />
          </div>
        ) : activeTab === 'help' ? (
          <div className="w-full">
            <HelpCenter navigate={navigate} embedded />
          </div>
        ) : (
          <>
            <header className="flex flex-col sm:flex-row justify-between items-start gap-4 mb-8">
              <div>
                <h1 className="text-4xl font-extrabold text-slate-800 tracking-tight">
                  {activeTab === 'properties' ? 'Properties' : activeTab === 'guests' ? 'Guests' : activeTab === 'invitations' ? 'Invitations' : activeTab === 'logs' ? 'Event ledger' : 'Billing'}
                </h1>
                <p className="text-slate-600 mt-1">
                  {activeTab === 'properties' ? 'Properties assigned to you.' : activeTab === 'guests' ? 'Guests currently staying at managed properties and their stay details.' : activeTab === 'invitations' ? 'Pending invitations for properties you manage.' : activeTab === 'logs' ? 'Event ledger for managed properties.' : 'Billing visibility for the properties you manage.'}
                </p>
              </div>
              {(activeTab === 'properties' || activeTab === 'guests' || activeTab === 'invitations') && properties.length > 0 && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setInviteSelectPropertyId(properties[0]?.id ?? null);
                    setInviteSelectUnitId(null);
                    setShowSelectPropertyUnitModal(true);
                  }}
                  className="px-6 flex items-center gap-2 shrink-0"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" /></svg>
                  Invite
                </Button>
              )}
            </header>

      {activeTab !== 'settings' && activeTab !== 'help' && (
        <DashboardAlertsPanel role="property_manager" className="mb-6" limit={50} />
      )}

      {activeTab === 'guests' && contextMode === 'personal' && (
        <div className="space-y-8">
          <p className="text-slate-500 text-sm">
            Pending invitations and guests who accepted (current or past stays) at properties you manage.
          </p>

          {invitations.filter((i) => i.status === 'pending').length > 0 && (
            <Card className="overflow-hidden">
              <div className="p-6 border-b border-slate-200 bg-amber-50">
                <h3 className="text-xl font-bold text-slate-800">Pending invitations</h3>
                <p className="text-xs text-slate-500 mt-1">Invites not yet accepted by the guest — use Copy link to share the invite URL</p>
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

          <Card className="p-6">
            <h2 className="font-semibold text-gray-900 mb-4">Stays</h2>
            <p className="text-slate-500 text-sm mb-4">Guests who accepted and their current or past stay at properties you manage.</p>
            {stays.filter((s: any) => !s.invitation_only).length === 0 ? (
              <p className="text-slate-500 text-sm">No stays yet. When guests accept an invitation, they appear here.</p>
            ) : (
              <ul className="space-y-2">
                {stays.filter((s: any) => !s.invitation_only).map((s: any) => (
                  <li key={s.stay_id} className="flex justify-between items-center py-2 border-b border-slate-100 last:border-0">
                    <span className="text-sm">{s.guest_name} · {s.property_name} · {formatStayDuration(s.stay_start_date, s.stay_end_date)}</span>
                    {s.checked_in_at && !s.checked_out_at && !s.cancelled_at && <span className="text-xs font-medium text-emerald-700">Active</span>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}

      {activeTab === 'invitations' && contextMode === 'personal' && (
        <InvitationsTabContent
          invitations={invitations}
          stays={stays}
          loadData={loadInvitationsAndStays}
          notify={notify}
          showVerifyQR={false}
          onCancelInvitation={async (id) => {
            await dashboardApi.cancelInvitation(id);
            notify('success', 'Invitation cancelled.');
            loadInvitationsAndStays();
            window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
          }}
          introText="Pending invitations for properties you manage. Invitations expire if not accepted within the configured window."
        />
      )}

      {activeTab === 'logs' && (
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
                            {entry.category === 'shield_mode' ? 'Shield Mode' : entry.category === 'dead_mans_switch' ? 'Stay end reminders' : entry.category === 'billing' ? 'Billing' : entry.category?.replace('_', ' ') ?? '—'}
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
      )}

      {activeTab === 'billing' && (
        <Card className="p-6">
          <h2 className="font-semibold text-gray-900 mb-2">Billing (read-only)</h2>
          <p className="text-slate-500 text-sm mb-4">Billing visibility for the properties you manage. You cannot modify billing or payment methods. Contact the property owner for changes.</p>
          {billing?.invoices?.length ? (
            <ul className="space-y-2">
              {billing.invoices.slice(0, 10).map((inv: any) => (
                <li key={inv.id} className="text-sm py-2 border-b border-slate-100">{inv.number || inv.id} · ${((inv.amount_paid_cents || 0) / 100).toFixed(2)}</li>
              ))}
            </ul>
          ) : <p className="text-slate-500 text-sm">No invoices.</p>}
        </Card>
      )}

      {activeTab === 'properties' && (
        <div className="space-y-6">
          {loading ? (
            <div className="text-center py-12 text-slate-500">Loading...</div>
          ) : properties.length === 0 ? (
            <Card className="p-8 text-center">
              <p className="text-slate-600">No properties assigned yet.</p>
              <p className="text-sm text-slate-500 mt-2">Owners can assign you to manage their properties.</p>
            </Card>
          ) : (
            <>
          {contextMode === 'business' && (
            <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-6 mb-6">
              <Card
              role="button"
              className={`p-6 border-l-4 border-blue-500 cursor-pointer hover:scale-[1.02] transition-transform ${propertiesCountFilter === 'properties' ? 'ring-2 ring-slate-400 ring-offset-2' : ''}`}
              onClick={() => setPropertiesCountFilter(propertiesCountFilter === 'properties' ? null : 'properties')}
            >
                <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Properties</p>
                <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.length}</p>
              </Card>
              <Card
              role="button"
              className={`p-6 border-l-4 border-emerald-500 cursor-pointer hover:scale-[1.02] transition-transform ${propertiesCountFilter === 'occupied' ? 'ring-2 ring-slate-400 ring-offset-2' : ''}`}
              onClick={() => setPropertiesCountFilter(propertiesCountFilter === 'occupied' ? null : 'occupied')}
            >
                <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Occupied</p>
                <p className="text-4xl font-extrabold text-slate-800 mt-1">{managerOccupiedUnitsTotal}</p>
              </Card>
              <Card
              role="button"
              className={`p-6 border-l-4 border-sky-500 cursor-pointer hover:scale-[1.02] transition-transform ${propertiesCountFilter === 'vacant' ? 'ring-2 ring-slate-400 ring-offset-2' : ''}`}
              onClick={() => setPropertiesCountFilter(propertiesCountFilter === 'vacant' ? null : 'vacant')}
            >
                <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Vacant</p>
                <p className="text-4xl font-extrabold text-slate-800 mt-1">{managerVacantUnitsTotal}</p>
              </Card>
              <Card
              role="button"
              className={`p-6 border-l-4 border-slate-400 cursor-pointer hover:scale-[1.02] transition-transform ${propertiesCountFilter === 'unknown' ? 'ring-2 ring-slate-400 ring-offset-2' : ''}`}
              onClick={() => setPropertiesCountFilter(propertiesCountFilter === 'unknown' ? null : 'unknown')}
            >
                <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Unknown</p>
                <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => !['occupied', 'vacant', 'unconfirmed'].includes((p.occupancy_status || '').toLowerCase())).length}</p>
              </Card>
              <Card
              role="button"
              className={`p-6 border-l-4 border-amber-500 cursor-pointer hover:scale-[1.02] transition-transform ${propertiesCountFilter === 'shield_on' ? 'ring-2 ring-slate-400 ring-offset-2' : ''}`}
              onClick={() => setPropertiesCountFilter(propertiesCountFilter === 'shield_on' ? null : 'shield_on')}
            >
                <p className="text-slate-600 text-sm font-bold uppercase tracking-wider">Shield On</p>
                <p className="text-4xl font-extrabold text-slate-800 mt-1">{properties.filter((p) => p.shield_mode_enabled).length}</p>
              </Card>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <span className="text-slate-500 text-sm">Shield Mode is always on. Use filters to narrow the list; all properties count as Shield ON.</span>
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
          {managerFilteredProperties.length > 0 && (
              <div className="mb-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedPropertyIds(managerFilteredProperties.every((p) => selectedPropertyIds.has(p.id)) ? new Set() : new Set(managerFilteredProperties.map((p) => p.id)))}
                  className="text-sm text-slate-600 hover:text-slate-800 underline"
                >
                  {managerFilteredProperties.every((p) => selectedPropertyIds.has(p.id)) ? 'Select none' : 'Select all'}
                </button>
                <span className="text-slate-400">·</span>
                <span className="text-sm text-slate-500">({managerFilteredProperties.length} propert{managerFilteredProperties.length === 1 ? 'y' : 'ies'} shown)</span>
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
                  DO NOT REMOVE — bulk Turn Shield OFF when backend allows optional Shield again.
                  <Button ... bulkShieldMode(..., false)>Turn Shield OFF</Button>
                */}
              </div>
            </div>
          )}
          {managerFilteredProperties.length === 0 && (
            <p className="text-slate-500 text-center py-8">No properties match the current filter. Clear the count bar selection or change Shield Mode filter to see more.</p>
          )}
          <div className="grid gap-6">
            {managerFilteredProperties.map((p) => {
              // Business mode: use property status only (no guest data). Personal mode: can use stays for occupancy.
              const activeStayForProp = contextMode === 'personal' ? activeStays.find((s: any) => s.property_id === p.id) : null;
              const isOccupied = contextMode === 'business'
                ? (p.occupancy_status || '').toLowerCase() === 'occupied'
                : !!activeStayForProp;
              const displayStatus = isOccupied ? 'OCCUPIED' : (p.occupancy_status ?? 'vacant').toUpperCase();
              const displayName = p.name || p.address || `Property #${p.id}`;
              const isSelected = selectedPropertyIds.has(p.id);
              return (
                <Card key={p.id} className="p-6 border border-slate-200">
                  {!!p.deleted_at && (
                    <div className="mb-4">
                      <InactivePropertyBanner role="manager" />
                    </div>
                  )}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                    <div className="flex items-start gap-3 flex-shrink-0">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => {
                          e.stopPropagation();
                          setSelectedPropertyIds((prev) => {
                            const next = new Set(prev);
                            if (next.has(p.id)) next.delete(p.id);
                            else next.add(p.id);
                            return next;
                          });
                        }}
                        className="mt-1 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                        aria-label={`Select ${displayName}`}
                      />
                    <button
                      type="button"
                      onClick={() => navigate(`manager-dashboard/property/${p.id}`)}
                      className="min-w-0 flex-1 text-left hover:opacity-90 transition-opacity"
                    >
                      <div className="flex flex-wrap items-center gap-2 gap-y-1">
                        <h3 className="text-lg font-bold text-slate-800 truncate">{displayName}</h3>
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
                      <p className="text-sm text-slate-600 mt-1 truncate">{p.address || '—'}</p>
                      <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-500">
                        <span>{p.occupied_count}/{p.unit_count} units occupied</span>
                        {contextMode === 'personal' && isOccupied && activeStayForProp && (
                          <span>Current guest: <span className="font-medium text-slate-700">{activeStayForProp.guest_name}</span></span>
                        )}
                      </div>
                      <span className="inline-block mt-2 text-xs font-medium text-blue-400">View details →</span>
                    </button>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <Button variant="outline" onClick={() => navigate(`manager-dashboard/property/${p.id}`)} className="px-4">
                        View details
                      </Button>
                      <Button variant="ghost" type="button" onClick={(e) => { e.stopPropagation(); loadUnits(p.id); }} className="px-4">
                        {expandedPropertyId === p.id ? 'Hide units' : 'View units'}
                      </Button>
                    </div>
                  </div>
                  {/* Occupancy status – same UI as owner */}
                  <div className="mt-6 pt-6 border-t border-slate-200 rounded-xl bg-slate-50/80 p-4">
                    <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Occupancy status</p>
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium ${
                        displayStatus === 'OCCUPIED' ? 'bg-emerald-100 text-emerald-800' :
                        displayStatus === 'VACANT' ? 'bg-slate-200 text-slate-700' :
                        displayStatus === 'UNCONFIRMED' ? 'bg-amber-100 text-amber-800' :
                        'bg-slate-100 text-slate-600'
                      }`}>
                        <span className={`w-2 h-2 rounded-full ${
                          displayStatus === 'OCCUPIED' ? 'bg-emerald-500' :
                          displayStatus === 'VACANT' ? 'bg-slate-400' :
                          displayStatus === 'UNCONFIRMED' ? 'bg-amber-500' : 'bg-slate-400'
                        }`} />
                        {displayStatus}
                      </span>
                      {contextMode === 'personal' && isOccupied && activeStayForProp && (
                        <span className="text-sm text-slate-600">
                          Lease end: <span className="font-medium text-slate-800">{formatCalendarDate(activeStayForProp.stay_end_date)}</span>
                        </span>
                      )}
                      <span className={`text-sm ${p.shield_mode_enabled ? 'text-emerald-600 font-medium' : 'text-slate-500'}`}>
                        Shield: {p.shield_mode_enabled ? 'ON' : 'OFF'}
                      </span>
                    </div>
                  </div>
                  {/* Units – expandable, same function as owner property detail */}
                  {expandedPropertyId === p.id && (
                    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/50 p-4">
                      <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Units</p>
                      {unitsLoading ? (
                        <p className="text-sm text-slate-500">Loading units...</p>
                      ) : (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                          {units.map((u) => (
                            <div key={u.id} className="bg-white rounded-lg p-3 border border-slate-200 flex flex-col gap-2">
                              <p className="font-medium text-slate-900">Unit {u.unit_label}</p>
                              {statusBadge(u.occupancy_status)}
                              {(u.occupancy_status || '').toLowerCase() === 'vacant' && u.id > 0 && (
                                <Button
                                  variant="outline"
                                  onClick={() => {
                                    if (contextMode === 'personal') {
                                      setInviteGuestUnitId(u.id);
                                      setInviteGuestOpen(true);
                                    } else {
                                      setInviteRoleChoiceUnit({ unitId: u.id, unitLabel: u.unit_label });
                                    }
                                  }}
                                >
                                  Invite
                                </Button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
            </>
          )}
        </div>
      )}

      {showSelectPropertyUnitModal && (
        <Modal
          open
          onClose={() => { setShowSelectPropertyUnitModal(false); setInviteSelectPropertyId(null); setInviteSelectUnitId(null); }}
          title="Select property and unit"
          className="max-w-md"
        >
          <div className="p-6 space-y-4">
            <label className="block text-sm font-medium text-slate-700">Property</label>
            <select
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900"
              value={inviteSelectPropertyId ?? ''}
              onChange={(e) => {
                const id = Number(e.target.value) || null;
                setInviteSelectPropertyId(id);
                setInviteSelectUnitId(null);
              }}
            >
              <option value="">Select property</option>
              {properties.map((p) => (
                <option key={p.id} value={p.id}>{p.name || p.address || `Property #${p.id}`}</option>
              ))}
            </select>
            <label className="block text-sm font-medium text-slate-700">Unit</label>
            <select
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900"
              value={inviteSelectUnitId ?? ''}
              onChange={(e) => setInviteSelectUnitId(Number(e.target.value) || null)}
              disabled={inviteSelectUnitsLoading || !inviteSelectPropertyId}
            >
              <option value="">Select unit</option>
              {inviteSelectUnits.filter((u) => u.id > 0).map((u) => (
                <option key={u.id} value={u.id}>Unit {u.unit_label}</option>
              ))}
            </select>
            <div className="flex gap-3 pt-2">
              <Button variant="outline" onClick={() => { setShowSelectPropertyUnitModal(false); setInviteSelectPropertyId(null); setInviteSelectUnitId(null); }} className="flex-1">Cancel</Button>
              <Button
                className="flex-1"
                onClick={() => {
                  const unitId = inviteSelectUnitId ?? inviteSelectUnits[0]?.id;
                  const unit = inviteSelectUnits.find((u) => u.id === unitId);
                  if (unitId && unit) {
                    if (contextMode === 'personal') {
                      setInviteGuestUnitId(unitId);
                      setInviteGuestOpen(true);
                    } else {
                      setInviteRoleChoiceUnit({ unitId, unitLabel: unit.unit_label });
                    }
                    setShowSelectPropertyUnitModal(false);
                    setInviteSelectPropertyId(null);
                    setInviteSelectUnitId(null);
                  } else {
                    notify('error', 'Please select a property and unit.');
                  }
                }}
                disabled={!inviteSelectUnitId && inviteSelectUnits.length === 0}
              >
                Continue
              </Button>
            </div>
          </div>
        </Modal>
      )}

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
          if (inviteRoleChoiceUnit?.unitId) setInviteGuestUnitId(inviteRoleChoiceUnit.unitId);
          setInviteGuestOpen(true);
          setInviteRoleChoiceUnit(null);
        }}
      />

      <InviteTenantModal
        open={!!inviteTenantModal}
        onClose={() => setInviteTenantModal(null)}
        properties={properties.map((p) => ({ id: p.id, name: p.name, address: p.address }))}
        getUnits={(id) => dashboardApi.managerUnits(id).then((u) => (u || []).filter((x) => x.id >= 0).map((x) => ({ id: x.id, unit_label: x.unit_label })))}
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
        onSuccess={() => { loadInvitationsAndStays(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }}
        guestInviteUrlIsDemo={Boolean(user?.is_demo)}
      />

      <InviteGuestModal
        open={inviteGuestOpen}
        onClose={() => {
          setInviteGuestOpen(false);
          setInviteGuestUnitId(null);
        }}
        user={user}
        setLoading={setLoadingWrapper}
        notify={notify}
        onSuccess={() => { loadInvitationsAndStays(); window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT)); }}
        propertiesLoader={() => dashboardApi.managerProperties()}
        unitsLoader={(id) => dashboardApi.managerUnits(id)}
        unitId={inviteGuestUnitId}
      />

      {logMessageModalEntry && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setLogMessageModalEntry(null)} aria-hidden="true" />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="log-message-title">
            <Card className="w-full max-w-lg max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
              <div className="p-6 flex-1 overflow-y-auto">
                <h3 id="log-message-title" className="text-lg font-semibold text-slate-800 mb-4">
                  Full message — {logMessageModalEntry.title}
                </h3>
                <p className="text-slate-700 text-sm whitespace-pre-wrap break-words">{logMessageModalEntry.message}</p>
              </div>
              <div className="p-4 border-t border-slate-200">
                <Button variant="outline" onClick={() => setLogMessageModalEntry(null)}>Close</Button>
              </div>
            </Card>
          </div>
        </>
      )}
          </>
        )}
      </main>
    </div>
  );
};

export default ManagerDashboard;
