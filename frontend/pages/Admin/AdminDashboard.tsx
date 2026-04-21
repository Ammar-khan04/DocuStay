import React, { useState, useEffect, useCallback } from 'react';
import { Button, Card } from '../../components/UI';
import { UserSession } from '../../types';
import {
  adminApi,
  type AdminUserView,
  type AdminAuditLogEntry,
  type AdminPropertyView,
  type AdminStayView,
  type AdminInvitationView,
} from '../../services/api';
import { formatDateTimeLocal, localDateInputToUtcStartIso, localDateInputToUtcEndIso } from '../../utils/dateUtils';
import { scrubAuditLogStateChangeParagraph } from '../../utils/auditLogMessage';

type AdminTab = 'users' | 'logs' | 'properties' | 'stays' | 'invitations';

const SIDEBAR_ITEMS: { id: AdminTab; label: string; icon: string }[] = [
  { id: 'users', label: 'Users', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
  { id: 'logs', label: 'Event ledger', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  { id: 'properties', label: 'Properties', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
  { id: 'stays', label: 'Stays', icon: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z' },
  { id: 'invitations', label: 'Invitations', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
];

/** Audit log categories (value, label) for dropdown - matches backend _CATEGORY_TO_ACTION_TYPES */
const AUDIT_LOG_CATEGORIES: { value: string; label: string }[] = [
  { value: '', label: 'All categories' },
  { value: 'status_change', label: 'Status change' },
  { value: 'guest_signature', label: 'Guest signature' },
  { value: 'failed_attempt', label: 'Failed attempt' },
  { value: 'shield_mode', label: 'Shield mode' },
  { value: 'dead_mans_switch', label: 'Stay end reminders' },
  { value: 'billing', label: 'Billing' },
  { value: 'presence', label: 'Presence / Away' },
  { value: 'verify_attempt', label: 'Verify attempt' },
  { value: 'tenant_assignment', label: 'Tenant assignment' },
];

/** Supported states for admin filters (Florida, New York, California, Texas) */
const SUPPORTED_STATES = ['FL', 'NY', 'CA', 'TX'];

export const AdminDashboard: React.FC<{
  user: UserSession;
  navigate: (v: string) => void;
  notify: (t: 'success' | 'error', m: string) => void;
}> = ({ user, navigate, notify }) => {
  const [tab, setTab] = useState<AdminTab>('users');
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [logs, setLogs] = useState<AdminAuditLogEntry[]>([]);
  const [properties, setProperties] = useState<AdminPropertyView[]>([]);
  const [stays, setStays] = useState<AdminStayView[]>([]);
  const [invitations, setInvitations] = useState<AdminInvitationView[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [logCategory, setLogCategory] = useState('');
  const [logSearch, setLogSearch] = useState('');
  const [logFromDate, setLogFromDate] = useState('');
  const [logToDate, setLogToDate] = useState('');
  const [propertyStateFilter, setPropertyStateFilter] = useState('');
  const [stayStateFilter, setStayStateFilter] = useState('');
  const [logMessageModalEntry, setLogMessageModalEntry] = useState<AdminAuditLogEntry | null>(null);
  const [logPropertyId, setLogPropertyId] = useState<number | ''>('');
  const [logActorUserId, setLogActorUserId] = useState<number | ''>('');

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.users({
        search: search.trim() || undefined,
        role: roleFilter || undefined,
        limit: 200,
      });
      setUsers(data);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [search, roleFilter, notify]);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const from_ts = logFromDate ? localDateInputToUtcStartIso(logFromDate) : undefined;
      const to_ts = logToDate ? localDateInputToUtcEndIso(logToDate) : undefined;
      const data = await adminApi.auditLogs({
        from_ts,
        to_ts,
        category: logCategory.trim() || undefined,
        search: logSearch.trim() || undefined,
        property_id: typeof logPropertyId === 'number' ? logPropertyId : undefined,
        actor_user_id: typeof logActorUserId === 'number' ? logActorUserId : undefined,
        limit: 200,
      });
      setLogs(data);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  }, [logCategory, logSearch, logFromDate, logToDate, logPropertyId, logActorUserId, notify]);

  const loadProperties = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.properties({
        state: propertyStateFilter.trim() || undefined,
        limit: 200,
      });
      setProperties(data);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to load properties');
    } finally {
      setLoading(false);
    }
  }, [propertyStateFilter, notify]);

  const loadStays = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.stays({
        state: stayStateFilter.trim() || undefined,
        limit: 200,
      });
      setStays(data);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to load stays');
    } finally {
      setLoading(false);
    }
  }, [stayStateFilter, notify]);

  const loadInvitations = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.invitations({ limit: 200 });
      setInvitations(data);
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to load invitations');
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    if (tab === 'users') loadUsers();
    else if (tab === 'logs') {
      loadLogs();
      loadProperties();
      loadUsers();
    } else if (tab === 'properties') loadProperties();
    else if (tab === 'stays') loadStays();
    else if (tab === 'invitations') loadInvitations();
  }, [tab, loadUsers, loadLogs, loadProperties, loadStays, loadInvitations]);

  const tabTitles: Record<AdminTab, string> = {
    users: 'Users',
    logs: 'Event ledger',
    properties: 'Properties',
    stays: 'Stays',
    invitations: 'Invitations',
  };
  const tabDescriptions: Record<AdminTab, string> = {
    users: 'All platform users. Filter by role or search by email or name.',
    logs: 'Global event ledger. Filter by category or search in title and message.',
    properties: 'All registered properties across owners.',
    stays: 'All stays. Filter by property, owner, or guest in API.',
    invitations: 'All invitations and their status.',
  };

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-transparent">
      {/* Sidebar – same layout as Owner dashboard */}
      <aside className="hidden lg:flex w-72 min-w-[18rem] flex-shrink-0 flex-col bg-white/70 backdrop-blur-xl border-r border-slate-200 p-6">
        <div className="space-y-2 flex-shrink-0">
          {SIDEBAR_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${tab === item.id ? 'bg-slate-100 text-slate-700 border border-slate-300' : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon} />
              </svg>
              {item.label}
            </button>
          ))}
        </div>
        <div className="mt-6 pt-6 border-t border-slate-200 flex-shrink-0">
          <p className="text-xs font-bold uppercase tracking-widest text-slate-500 px-1">Admin</p>
          <p className="text-sm text-slate-600 mt-1 px-1 truncate" title={user.email}>{user.email}</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-grow overflow-y-auto no-scrollbar bg-transparent p-8">
        {/* Mobile tab nav */}
        <div className="lg:hidden mb-6">
          <label htmlFor="admin-mobile-tab" className="sr-only">Navigate to</label>
          <select
            id="admin-mobile-tab"
            value={tab}
            onChange={(e) => setTab(e.target.value as AdminTab)}
            className="w-full max-w-xs rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            {SIDEBAR_ITEMS.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </div>

        <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-10 gap-6">
          <div>
            <h1 className="text-4xl font-extrabold text-slate-800 tracking-tight">{tabTitles[tab]}</h1>
            <p className="text-slate-600 mt-1">{tabDescriptions[tab]}</p>
          </div>
        </header>

        {tab === 'users' && (
          <Card className="overflow-hidden">
            <div className="p-6 border-b border-slate-200 bg-slate-50">
              <div className="flex flex-wrap gap-3 items-center">
                <input
                  type="text"
                  placeholder="Search email or name"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 w-48"
                />
                <select
                  value={roleFilter}
                  onChange={(e) => setRoleFilter(e.target.value)}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                >
                  <option value="">All roles</option>
                  <option value="owner">Owner</option>
                  <option value="guest">Guest</option>
                  <option value="admin">Admin</option>
                </select>
                <Button variant="outline" onClick={loadUsers} disabled={loading} className="px-6">
                  {loading ? 'Loading…' : 'Refresh'}
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                  <tr>
                    <th className="py-3 px-4">ID</th>
                    <th className="py-3 px-4">Email</th>
                    <th className="py-3 px-4">Role</th>
                    <th className="py-3 px-4">Name</th>
                    <th className="py-3 px-4">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {users.map((u) => (
                    <tr key={u.id} className="bg-white hover:bg-slate-50/80">
                      <td className="py-3 px-4 text-slate-700">{u.id}</td>
                      <td className="py-3 px-4 text-slate-700">{u.email}</td>
                      <td className="py-3 px-4 text-slate-700">{u.role}</td>
                      <td className="py-3 px-4 text-slate-700">{u.full_name ?? '—'}</td>
                      <td className="py-3 px-4 text-slate-600">{formatDateTimeLocal(u.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'logs' && (
          <Card className="overflow-hidden">
            <div className="p-6 border-b border-slate-200 bg-slate-50">
              <div className="flex flex-wrap gap-3 items-center">
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wider">From date</label>
                <input
                  type="date"
                  value={logFromDate}
                  onChange={(e) => setLogFromDate(e.target.value)}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                />
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wider">To date</label>
                <input
                  type="date"
                  value={logToDate}
                  onChange={(e) => setLogToDate(e.target.value)}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                />
                <select
                  value={logCategory}
                  onChange={(e) => setLogCategory(e.target.value)}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 min-w-[10rem]"
                >
                  {AUDIT_LOG_CATEGORIES.map((c) => (
                    <option key={c.value || 'all'} value={c.value}>{c.label}</option>
                  ))}
                </select>
                <select
                  value={logPropertyId}
                  onChange={(e) => setLogPropertyId(e.target.value === '' ? '' : Number(e.target.value))}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 min-w-[10rem]"
                >
                  <option value="">All properties</option>
                  {properties.map((p) => (
                    <option key={p.id} value={p.id}>{p.name ?? p.id}</option>
                  ))}
                </select>
                <select
                  value={logActorUserId}
                  onChange={(e) => setLogActorUserId(e.target.value === '' ? '' : Number(e.target.value))}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 min-w-[10rem]"
                >
                  <option value="">All actors</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{u.email}</option>
                  ))}
                </select>
                <input
                  type="text"
                  placeholder="Search title/message"
                  value={logSearch}
                  onChange={(e) => setLogSearch(e.target.value)}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 w-48"
                />
                <Button variant="outline" onClick={loadLogs} disabled={loading} className="px-6">
                  {loading ? 'Loading…' : 'Refresh'}
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto max-h-[60vh] overflow-y-auto">
              <table className="w-full text-sm text-left">
                <thead className="sticky top-0 bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200 z-10">
                  <tr>
                    <th className="py-3 px-4">Time</th>
                    <th className="py-3 px-4">Property</th>
                    <th className="py-3 px-4">Category</th>
                    <th className="py-3 px-4">Title</th>
                    <th className="py-3 px-4">Message</th>
                    <th className="py-3 px-4">Actor</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {logs.map((r) => (
                    <tr key={r.id} className="bg-white hover:bg-slate-50/80">
                      <td className="py-3 px-4 whitespace-nowrap text-slate-600">{formatDateTimeLocal(r.created_at)}</td>
                      <td className="py-3 px-4 text-slate-700">{r.property_name ?? (r.property_id != null ? `#${r.property_id}` : '—')}</td>
                      <td className="py-3 px-4 text-slate-700">{r.category}</td>
                      <td className="py-3 px-4 text-slate-700">{r.title}</td>
                      <td className="py-3 px-4 text-slate-700 max-w-xs">
                        <span className="truncate block">{scrubAuditLogStateChangeParagraph(r.message)}</span>
                        <button
                          type="button"
                          onClick={() => setLogMessageModalEntry(r)}
                          className="text-sky-600 hover:text-sky-800 text-xs mt-0.5 focus:outline-none focus:underline"
                        >
                          View full message
                        </button>
                      </td>
                      <td className="py-3 px-4 text-slate-700">{r.actor_email ?? r.actor_user_id ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'properties' && (
          <Card className="overflow-hidden">
            <div className="p-6 border-b border-slate-200 bg-slate-50 flex flex-wrap gap-3 items-center">
              <label className="text-xs font-medium text-slate-500 uppercase tracking-wider">State</label>
              <select
                value={propertyStateFilter}
                onChange={(e) => setPropertyStateFilter(e.target.value)}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 min-w-[8rem]"
              >
                <option value="">All states</option>
                {SUPPORTED_STATES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <Button variant="outline" onClick={loadProperties} disabled={loading} className="px-6">
                {loading ? 'Loading…' : 'Refresh'}
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                  <tr>
                    <th className="py-3 px-4">ID</th>
                    <th className="py-3 px-4">Owner</th>
                    <th className="py-3 px-4">Name</th>
                    <th className="py-3 px-4">Address</th>
                    <th className="py-3 px-4">Region</th>
                    <th className="py-3 px-4">Occupancy</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {properties.map((p) => (
                    <tr key={p.id} className="bg-white hover:bg-slate-50/80">
                      <td className="py-3 px-4 text-slate-700">{p.id}</td>
                      <td className="py-3 px-4 text-slate-700">{p.owner_email ?? '—'}</td>
                      <td className="py-3 px-4 text-slate-700">{p.name ?? '—'}</td>
                      <td className="py-3 px-4 text-slate-700">{[p.street, p.city, p.state].filter(Boolean).join(', ')}</td>
                      <td className="py-3 px-4 text-slate-700">{p.region_code ?? '—'}</td>
                      <td className="py-3 px-4 text-slate-700">{p.occupancy_status ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'stays' && (
          <Card className="overflow-hidden">
            <div className="p-6 border-b border-slate-200 bg-slate-50 flex flex-wrap gap-3 items-center">
              <label className="text-xs font-medium text-slate-500 uppercase tracking-wider">State</label>
              <select
                value={stayStateFilter}
                onChange={(e) => setStayStateFilter(e.target.value)}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 min-w-[8rem]"
              >
                <option value="">All states</option>
                {SUPPORTED_STATES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <Button variant="outline" onClick={loadStays} disabled={loading} className="px-6">
                {loading ? 'Loading…' : 'Refresh'}
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                  <tr>
                    <th className="py-3 px-4">ID</th>
                    <th className="py-3 px-4">Property</th>
                    <th className="py-3 px-4">Guest</th>
                    <th className="py-3 px-4">Dates</th>
                    <th className="py-3 px-4">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {stays.map((s) => (
                    <tr key={s.id} className="bg-white hover:bg-slate-50/80">
                      <td className="py-3 px-4 text-slate-700">{s.id}</td>
                      <td className="py-3 px-4 text-slate-700">{s.property_name ?? s.property_id}</td>
                      <td className="py-3 px-4 text-slate-700">{s.guest_email ?? s.guest_id}</td>
                      <td className="py-3 px-4 text-slate-700">{s.stay_start_date} – {s.stay_end_date}</td>
                      <td className="py-3 px-4 text-slate-700">
                        {s.revoked_at ? 'Revoked' : s.cancelled_at ? 'Cancelled' : s.checked_out_at ? 'Ended' : 'Active'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'invitations' && (
          <Card className="overflow-hidden">
            <div className="p-6 border-b border-slate-200 bg-slate-50 flex flex-wrap gap-3 items-center">
              <Button variant="outline" onClick={loadInvitations} disabled={loading} className="px-6">
                {loading ? 'Loading…' : 'Refresh'}
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-widest font-extrabold border-b border-slate-200">
                  <tr>
                    <th className="py-3 px-4">Code</th>
                    <th className="py-3 px-4">Property</th>
                    <th className="py-3 px-4">Guest</th>
                    <th className="py-3 px-4">Dates</th>
                    <th className="py-3 px-4">Status / Token</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {invitations.map((inv) => (
                    <tr key={inv.id} className="bg-white hover:bg-slate-50/80">
                      <td className="py-3 px-4 font-mono text-xs text-slate-700">{inv.invitation_code}</td>
                      <td className="py-3 px-4 text-slate-700">{inv.property_name ?? inv.property_id}</td>
                      <td className="py-3 px-4 text-slate-700">{inv.guest_name ?? inv.guest_email ?? '—'}</td>
                      <td className="py-3 px-4 text-slate-700">{inv.stay_start_date} – {inv.stay_end_date}</td>
                      <td className="py-3 px-4 text-slate-700">{inv.status} / {inv.token_state}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </main>

      {/* Full log message modal */}
      {logMessageModalEntry && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={() => setLogMessageModalEntry(null)} aria-hidden="true" />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="admin-log-message-title">
            <Card className="w-full max-w-lg max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
              <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                <h3 id="admin-log-message-title" className="text-lg font-bold text-slate-800">
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
                <p className="text-slate-700 text-sm whitespace-pre-wrap break-words">
                  {scrubAuditLogStateChangeParagraph(logMessageModalEntry.message)}
                </p>
              </div>
              <div className="p-4 border-t border-slate-200">
                <Button variant="outline" onClick={() => setLogMessageModalEntry(null)}>Close</Button>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
};
