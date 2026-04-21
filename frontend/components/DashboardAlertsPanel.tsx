import React, { useState, useEffect, useCallback } from 'react';
import { dashboardApi, emitPropertiesChanged, type DashboardAlertView, type OwnerAuditLogEntry } from '../services/api';
import { formatDateTimeLocal } from '../utils/dateUtils';
import { scrubAuditLogStateChangeParagraph } from '../utils/auditLogMessage';
import { Button } from './UI';

/** Dispatch this event to refresh alerts immediately (e.g. after revoke, confirm occupancy). */
export const DASHBOARD_ALERTS_REFRESH_EVENT = 'docustay-dashboard-alerts-refresh';

const POLL_INTERVAL_MS = 25_000; // 25 seconds – realtime without hammering the API

/** Ledger notification titles to hide in the notifications section. */
const HIDDEN_LEDGER_TITLES = new Set([
  'Onboarding invoice created',
  'Invoice created',
  'Subscription started (free trial)',
  'Ownership proof uploaded',
  'ManagerInvited',
  'Property registered',
  'Invitation created',
  'User logged in',
]);

/** Ledger-only rows: show on Event ledger tab, not in the Notifications panel. */
function hideLedgerTitleFromNotifications(title: string | undefined): boolean {
  const t = (title || '').trim();
  if (HIDDEN_LEDGER_TITLES.has(t)) return true;
  if (t.startsWith('CSV bulk upload:')) return true;
  if (t.startsWith('Pending tenant:')) return true;
  return false;
}

const severityStyles: Record<string, string> = {
  urgent: 'bg-red-50 border-red-200 text-red-800',
  warning: 'bg-amber-50 border-amber-200 text-amber-800',
  info: 'bg-sky-50 border-sky-200 text-sky-800',
};

/** Category-based accent and icon for ledger entries. */
const categoryAccent: Record<string, { border: string; bg: string; icon: string }> = {
  status_change: { border: 'border-l-sky-500', bg: 'bg-sky-50/80', icon: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  shield_mode: { border: 'border-l-violet-500', bg: 'bg-violet-50/80', icon: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.187-.382-3.314z' },
  billing: { border: 'border-l-amber-500', bg: 'bg-amber-50/80', icon: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  dead_mans_switch: { border: 'border-l-rose-500', bg: 'bg-rose-50/80', icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z' },
  presence: { border: 'border-l-emerald-500', bg: 'bg-emerald-50/80', icon: 'M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z' },
  guest_signature: { border: 'border-l-teal-500', bg: 'bg-teal-50/80', icon: 'M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z' },
  tenant_assignment: { border: 'border-l-indigo-500', bg: 'bg-indigo-50/80', icon: 'M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z' },
  failed_attempt: { border: 'border-l-red-500', bg: 'bg-red-50/80', icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z' },
  default: { border: 'border-l-slate-400', bg: 'bg-slate-50/80', icon: 'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9' },
};

function getCategoryStyle(category: string | undefined) {
  if (!category) return categoryAccent.default;
  const key = category.replace(/\s/g, '_');
  return categoryAccent[key as keyof typeof categoryAccent] ?? categoryAccent.default;
}

function formatAlertTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return formatDateTimeLocal(d);
  } catch {
    return '';
  }
}

/** Role for notifications: when set, the panel shows event ledger entries (same data as Event ledger tab) in notification format. */
export type NotificationsRole = 'owner' | 'property_manager' | 'tenant' | 'guest';

interface DashboardAlertsPanelProps {
  /** When set, notifications show event ledger data (same API as Event ledger). Owner/manager Personal mode uses a guest-residence-only ledger slice (no portfolio/tenant/manager rows). */
  role?: NotificationsRole;
  /** Max items to show (default 50). */
  limit?: number;
  /** Only for legacy alerts mode (when role is not set): show only unread. */
  unreadOnly?: boolean;
  /** Callback when an alert is marked read (legacy alerts mode only). */
  onAlertsChange?: () => void;
  /** Optional class for the container. */
  className?: string;
}

export const DashboardAlertsPanel: React.FC<DashboardAlertsPanelProps> = ({
  role,
  limit = 50,
  unreadOnly = false,
  onAlertsChange,
  className = '',
}) => {
  const [alerts, setAlerts] = useState<DashboardAlertView[]>([]);
  const [ledgerEntries, setLedgerEntries] = useState<OwnerAuditLogEntry[]>([]);
  const [occupancyActionAlerts, setOccupancyActionAlerts] = useState<DashboardAlertView[]>([]);
  const [tenantLeaseActionAlerts, setTenantLeaseActionAlerts] = useState<DashboardAlertView[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [markingId, setMarkingId] = useState<number | null>(null);
  const [occupancySubmitting, setOccupancySubmitting] = useState<number | null>(null);
  const [tenantLeaseSubmitting, setTenantLeaseSubmitting] = useState<number | null>(null);
  const [occupancyError, setOccupancyError] = useState<string | null>(null);

  const loadLedger = useCallback(async (silent = false) => {
    if (!role) return;
    if (!silent) setLoading(true);
    const fromTs = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
    try {
      let list: OwnerAuditLogEntry[] = [];
      if (role === 'owner') {
        list = await dashboardApi.ownerLogs({ from_ts: fromTs });
      } else if (role === 'property_manager') {
        list = await dashboardApi.managerLogs({ from_ts: fromTs });
      } else if (role === 'tenant') {
        list = await dashboardApi.tenantLogs({ from_ts: fromTs });
      } else if (role === 'guest') {
        list = await dashboardApi.guestLogs({ from_ts: fromTs });
      }
      setLedgerEntries(list.slice(0, limit));
      if (role === 'owner' || role === 'property_manager') {
        try {
          const dashAlerts = await dashboardApi.getAlerts({ limit: 50 });
          const occ = dashAlerts.filter(
            (a) =>
              (a.alert_type === 'dms_48h' ||
                a.alert_type === 'dms_urgent' ||
                a.alert_type === 'dms_reminder') &&
              typeof a.stay_id === 'number' &&
              !a.read_at,
          );
          const byStay = new Map<number, DashboardAlertView>();
          for (const a of occ.sort(
            (x, y) => new Date(y.created_at).getTime() - new Date(x.created_at).getTime(),
          )) {
            const sid = a.stay_id as number;
            if (!byStay.has(sid)) byStay.set(sid, a);
          }
          setOccupancyActionAlerts(Array.from(byStay.values()));
          const taLease = dashAlerts.filter(
            (a) =>
              (a.alert_type === 'tenant_lease_48h' || a.alert_type === 'tenant_lease_urgent') && !a.read_at,
          );
          const byTa = new Map<number, DashboardAlertView>();
          for (const a of taLease.sort(
            (x, y) => new Date(y.created_at).getTime() - new Date(x.created_at).getTime(),
          )) {
            const tid =
              typeof a.meta?.tenant_assignment_id === 'number'
                ? (a.meta.tenant_assignment_id as number)
                : a.id;
            if (!byTa.has(tid)) byTa.set(tid, a);
          }
          setTenantLeaseActionAlerts(Array.from(byTa.values()));
        } catch {
          setOccupancyActionAlerts([]);
          setTenantLeaseActionAlerts([]);
        }
      } else {
        setOccupancyActionAlerts([]);
        setTenantLeaseActionAlerts([]);
      }
    } catch {
      if (!silent) setLedgerEntries([]);
      setOccupancyActionAlerts([]);
      setTenantLeaseActionAlerts([]);
    } finally {
      setLoading(false);
    }
  }, [role, limit]);

  const loadAlerts = useCallback(async (silent = false) => {
    if (role) return;
    if (!silent) setLoading(true);
    try {
      const list = await dashboardApi.getAlerts({ limit, unread_only: unreadOnly });
      setAlerts(list);
    } catch {
      if (!silent) setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, [limit, unreadOnly, role]);

  const load = useCallback(
    async (silent = false) => {
      if (role) {
        await loadLedger(silent);
      } else {
        await loadAlerts(silent);
      }
    },
    [role, loadLedger, loadAlerts]
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const id = setInterval(() => load(true), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') load(true);
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [load]);

  useEffect(() => {
    const onRefresh = () => load(true);
    window.addEventListener(DASHBOARD_ALERTS_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(DASHBOARD_ALERTS_REFRESH_EVENT, onRefresh);
  }, [load]);

  const markRead = async (alert: DashboardAlertView) => {
    if (alert.read_at) return;
    setMarkingId(alert.id);
    try {
      await dashboardApi.markAlertRead(alert.id);
      setAlerts((prev) => prev.map((a) => (a.id === alert.id ? { ...a, read_at: new Date().toISOString() } : a)));
      setTenantLeaseActionAlerts((prev) =>
        prev.map((a) => (a.id === alert.id ? { ...a, read_at: new Date().toISOString() } : a)),
      );
      onAlertsChange?.();
    } finally {
      setMarkingId(null);
    }
  };

  const respondOccupancy = async (stayId: number, kind: 'vacant' | 'occupied') => {
    setOccupancyError(null);
    setOccupancySubmitting(stayId);
    try {
      await dashboardApi.confirmOccupancyStatus(stayId, kind);
      await dashboardApi.markOccupancyPromptAlertsRead(stayId).catch(() => {});
      await load(true);
      emitPropertiesChanged();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      setOccupancyError((e as Error)?.message ?? 'Could not update occupancy.');
    } finally {
      setOccupancySubmitting(null);
    }
  };

  const respondTenantLeaseOccupancy = async (tenantAssignmentId: number, kind: 'vacant' | 'occupied') => {
    setOccupancyError(null);
    setTenantLeaseSubmitting(tenantAssignmentId);
    try {
      await dashboardApi.confirmTenantAssignmentOccupancy(tenantAssignmentId, kind);
      await load(true);
      emitPropertiesChanged();
      window.dispatchEvent(new CustomEvent(DASHBOARD_ALERTS_REFRESH_EVENT));
    } catch (e) {
      setOccupancyError((e as Error)?.message ?? 'Could not update occupancy.');
    } finally {
      setTenantLeaseSubmitting(null);
    }
  };

  const useLedger = Boolean(role);
  const filteredLedgerEntries = useLedger
    ? ledgerEntries.filter((e) => !hideLedgerTitleFromNotifications(e.title))
    : [];
  const items = useLedger ? filteredLedgerEntries : alerts;
  const unreadCount = useLedger ? 0 : alerts.filter((a) => !a.read_at).length;

  if (loading && items.length === 0) {
    return (
      <div className={`rounded-2xl border border-slate-200/80 bg-white shadow-sm p-6 ${className}`}>
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-slate-100 animate-pulse" />
          <div className="flex-1 space-y-2">
            <div className="h-3.5 w-32 rounded bg-slate-100 animate-pulse" />
            <div className="h-3 w-24 rounded bg-slate-50 animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-2xl border border-slate-200/80 bg-white shadow-sm overflow-hidden ${className}`}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left bg-gradient-to-r from-slate-50 to-white hover:from-slate-100 hover:to-slate-50 transition-colors border-b border-slate-100"
      >
        <span className="font-semibold text-slate-800 flex items-center gap-2.5">
          <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-slate-100 text-slate-600">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
          </span>
          Notifications
          {!useLedger && unreadCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-amber-500 text-white text-xs font-bold shadow-sm">
              {unreadCount}
            </span>
          )}
        </span>
        <svg
          className={`w-5 h-5 text-slate-400 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded &&
        (useLedger ? (
          items.length === 0 && occupancyActionAlerts.length === 0 && tenantLeaseActionAlerts.length === 0 ? (
            <div className="border-t border-slate-100 px-5 py-8 text-center bg-slate-50/50">
              <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
                </svg>
              </div>
              <p className="text-slate-600 font-medium">No recent activity</p>
              <p className="text-slate-400 text-sm mt-0.5">Event updates will appear here</p>
            </div>
          ) : (
            <>
            {(occupancyActionAlerts.length > 0 || tenantLeaseActionAlerts.length > 0) && (
              <div className="border-t border-amber-200 bg-amber-50/50 px-3 py-3 space-y-3">
                <p className="text-xs font-bold uppercase tracking-wider text-amber-900 px-2">
                  Action required — lease ending
                </p>
                {occupancyError && (
                  <p className="text-sm text-red-700 px-2">{occupancyError}</p>
                )}
                {tenantLeaseActionAlerts.filter((a) => !a.read_at).map((alert) => {
                  const taId =
                    typeof alert.meta?.tenant_assignment_id === 'number'
                      ? (alert.meta.tenant_assignment_id as number)
                      : null;
                  const taKey = taId ?? alert.id;
                  const busy = taId != null && tenantLeaseSubmitting === taId;
                  return (
                    <div
                      key={`tenant-lease-prompt-${taKey}`}
                      className="rounded-xl border border-amber-200 bg-white p-4 shadow-sm mx-0.5"
                    >
                      <p className="font-semibold text-sm text-slate-900">Confirm occupancy</p>
                      <p className="text-sm text-slate-600 mt-1.5 leading-relaxed">{alert.message}</p>
                      <div className="flex flex-wrap gap-2 mt-3">
                        <Button
                          variant="outline"
                          className="border-amber-600 text-amber-900 hover:bg-amber-50 text-xs py-2"
                          disabled={taId == null || busy}
                          onClick={() => taId != null && respondTenantLeaseOccupancy(taId, 'vacant')}
                        >
                          {busy ? '…' : 'Vacant'}
                        </Button>
                        <Button
                          variant="outline"
                          className="border-amber-600 text-amber-900 hover:bg-amber-50 text-xs py-2"
                          disabled={taId == null || busy}
                          onClick={() => taId != null && respondTenantLeaseOccupancy(taId, 'occupied')}
                        >
                          {busy ? '…' : 'Occupied'}
                        </Button>
                      </div>
                      <p className="text-xs text-slate-500 mt-2">
                        To extend the lease with a new end date, open the property and use <strong>Lease renewed</strong>.
                      </p>
                    </div>
                  );
                })}
                {occupancyActionAlerts.map((alert) => (
                  <div
                    key={`occ-prompt-${alert.stay_id}`}
                    className="rounded-xl border border-amber-200 bg-white p-4 shadow-sm mx-0.5"
                  >
                    <p className="font-semibold text-sm text-slate-900">Confirm occupancy</p>
                    <p className="text-sm text-slate-600 mt-1.5 leading-relaxed">{alert.message}</p>
                    <div className="flex flex-wrap gap-2 mt-3">
                      <Button
                        variant="outline"
                        className="border-amber-600 text-amber-900 hover:bg-amber-50 text-xs py-2"
                        disabled={occupancySubmitting === alert.stay_id}
                        onClick={() => alert.stay_id != null && respondOccupancy(alert.stay_id, 'vacant')}
                      >
                        {occupancySubmitting === alert.stay_id ? '…' : 'Vacant'}
                      </Button>
                      <Button
                        variant="outline"
                        className="border-amber-600 text-amber-900 hover:bg-amber-50 text-xs py-2"
                        disabled={occupancySubmitting === alert.stay_id}
                        onClick={() => alert.stay_id != null && respondOccupancy(alert.stay_id, 'occupied')}
                      >
                        {occupancySubmitting === alert.stay_id ? '…' : 'Occupied'}
                      </Button>
                    </div>
                    <p className="text-xs text-slate-500 mt-2">
                      To extend the lease with a new end date, open the property and use <strong>Lease renewed</strong>.
                    </p>
                  </div>
                ))}
              </div>
            )}
            {items.length === 0 ? null : (
            <ul className="border-t border-slate-100 max-h-[360px] overflow-y-auto py-2 px-3">
              {items.map((entry) => {
                const style = getCategoryStyle(entry.category);
                return (
                  <li key={entry.id} className="px-2 py-2">
                    <div className={`rounded-xl border border-slate-200/80 border-l-4 ${style.border} ${style.bg} shadow-sm hover:shadow transition-shadow duration-200 overflow-hidden`}>
                      <div className="p-4 flex gap-3">
                        <span className="flex-shrink-0 w-9 h-9 rounded-lg bg-white/80 border border-slate-200/80 flex items-center justify-center text-slate-600">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={style.icon} />
                          </svg>
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold text-slate-900 text-sm leading-snug">
                            {entry.actor_email ? `${entry.title} by ${entry.actor_email}` : entry.title}
                          </p>
                          {entry.property_name && (
                            <p className="text-sm mt-1.5 font-medium text-slate-700 flex items-start gap-1.5">
                              <svg className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                              </svg>
                              <span>{entry.property_name}</span>
                            </p>
                          )}
                          {entry.message && (entry.message !== entry.title || !entry.property_name) && (
                            <p className="text-sm mt-1.5 text-slate-600 leading-relaxed">
                              {scrubAuditLogStateChangeParagraph(entry.message)}
                            </p>
                          )}
                          <div className="flex flex-wrap items-center gap-2 mt-2.5">
                            {(entry.category || entry.actor_email) && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-white/70 border border-slate-200/80 text-xs font-medium text-slate-600">
                                {entry.category?.replace(/_/g, ' ') ?? ''}
                                {entry.actor_email ? `${entry.category ? ' · ' : ''}${entry.actor_email}` : ''}
                              </span>
                            )}
                            <span className="inline-flex items-center text-xs text-slate-500 font-medium">
                              {formatAlertTime(entry.created_at)}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
            )}
            </>
          )
        ) : items.length === 0 ? (
          <div className="border-t border-slate-100 px-5 py-8 text-center bg-slate-50/50">
            <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
              </svg>
            </div>
            <p className="text-slate-600 font-medium">No new notifications</p>
            <p className="text-slate-400 text-sm mt-0.5">Status updates and alerts will appear here</p>
          </div>
        ) : (
          <ul className="border-t border-slate-100 max-h-[360px] overflow-y-auto py-2 px-3">
            {alerts.map((alert) => (
              <li key={alert.id} className="px-2 py-2">
                <div className={`rounded-xl border border-slate-200/80 shadow-sm overflow-hidden ${severityStyles[alert.severity] || severityStyles.info} ${!alert.read_at ? 'ring-1 ring-amber-200/50' : ''}`}>
                  <div className="p-4 flex justify-between items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-sm text-slate-900">{alert.title}</p>
                      <p className="text-sm mt-1 text-slate-600 leading-relaxed">{alert.message}</p>
                      <div className="flex items-center gap-2 mt-2.5">
                        <span className="text-xs font-medium text-slate-500">{formatAlertTime(alert.created_at)}</span>
                      </div>
                    </div>
                    {!alert.read_at && (
                      <button
                        type="button"
                        onClick={() => markRead(alert)}
                        disabled={markingId === alert.id}
                        className="flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/80 border border-slate-200/80 text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
                      >
                        {markingId === alert.id ? '…' : 'Mark read'}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
};
