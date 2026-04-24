/**
 * Guest stay list + row labels aligned with backend `state_resolver` (same invitation calendar SOT as tenant lease).
 */
import { parseForDisplay } from './dateUtils';
import type { GuestStayView, OwnerStayView } from '../services/api';

/** Normalized row for lifecycle + badges (owner stay rows and guest `/guest/stays` rows). */
export type StayLifecycleRowInput = {
  lifecycle_state?: string | null;
  stay_status?: string | null;
  stay_start_date: string;
  stay_end_date: string;
  checked_in_at?: string | null;
  checked_out_at?: string | null;
  cancelled_at?: string | null;
  revoked_at?: string | null;
};

export function ownerStayToLifecycleRow(s: OwnerStayView): StayLifecycleRowInput {
  return {
    lifecycle_state: s.lifecycle_state,
    stay_status: s.stay_status,
    stay_start_date: String(s.stay_start_date),
    stay_end_date: String(s.stay_end_date),
    checked_in_at: s.checked_in_at ?? null,
    checked_out_at: s.checked_out_at ?? null,
    cancelled_at: s.cancelled_at ?? null,
    revoked_at: s.revoked_at ?? null,
  };
}

export function guestStayViewToLifecycleRow(s: GuestStayView): StayLifecycleRowInput {
  return {
    lifecycle_state: s.lifecycle_state,
    stay_status: s.stay_status,
    stay_start_date: String(s.approved_stay_start_date),
    stay_end_date: String(s.approved_stay_end_date),
    checked_in_at: s.checked_in_at ?? null,
    checked_out_at: s.checked_out_at ?? null,
    cancelled_at: s.cancelled_at ?? null,
    revoked_at: s.revoked_at ?? null,
  };
}

export function guestStayDaysLeft(endDateStr: string): number {
  const end = parseForDisplay(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.ceil((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  return Math.max(0, diff);
}

/** Whole days until stay_start_date (0 = starts today; negative = already started). */
export function guestStayDaysUntilStart(startDateStr: string): number {
  const start = parseForDisplay(startDateStr);
  start.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((start.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

export function guestStayIsOverstayed(endDateStr: string): boolean {
  const end = parseForDisplay(endDateStr);
  end.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return end.getTime() < today.getTime();
}

export function guestLifecycleIsTerminal(lc: string): boolean {
  return lc === 'EXPIRED' || lc === 'CANCELLED';
}

export function guestLifecycleRank(lc: string): number {
  if (lc === 'PENDING_STAGED') return 0;
  if (lc === 'PENDING_INVITED') return 1;
  if (lc === 'ACCEPTED') return 2;
  if (lc === 'ACTIVE' || lc === 'OWNER_RESIDENT') return 3;
  return 9;
}

const UNIFIED_LC = new Set([
  'PENDING_STAGED',
  'PENDING_INVITED',
  'ACCEPTED',
  'ACTIVE',
  'EXPIRED',
  'OWNER_RESIDENT',
  'CANCELLED',
]);

/** Prefer backend ``lifecycle_state``; otherwise map resolver ``stay_status`` + terminals only (no client date rules). */
export function guestStayLifecycleForDisplayRow(row: StayLifecycleRowInput): string {
  const raw = (row.lifecycle_state ?? '').trim().toUpperCase();
  if (raw && UNIFIED_LC.has(raw)) return raw;
  if (row.cancelled_at || row.revoked_at) return 'CANCELLED';
  if (row.checked_out_at) return 'EXPIRED';
  const ss = (row.stay_status ?? '').trim().toLowerCase();
  if (ss === 'cancelled' || ss === 'revoked') return 'CANCELLED';
  if (ss === 'checked_out' || ss === 'ended') return 'EXPIRED';
  if (ss === 'checked_in') return 'ACTIVE';
  if (ss === 'upcoming') return 'ACCEPTED';
  return 'PENDING_STAGED';
}

export function guestStayLifecycleForDisplay(stay: OwnerStayView): string {
  return guestStayLifecycleForDisplayRow(ownerStayToLifecycleRow(stay));
}

/** Guest `/dashboard/guest/stays` rows (same resolver fields as owner when API provides them). */
export function guestFacingStayLifecycle(s: GuestStayView): string {
  return guestStayLifecycleForDisplayRow(guestStayViewToLifecycleRow(s));
}

export function isStayPhysicallyCheckedInRow(row: StayLifecycleRowInput): boolean {
  if ((row.stay_status || '').toLowerCase() === 'checked_in') return true;
  return !!row.checked_in_at;
}

export function isStayPhysicallyCheckedIn(stay: OwnerStayView): boolean {
  return isStayPhysicallyCheckedInRow(ownerStayToLifecycleRow(stay));
}

export function isGuestStayPhysicallyCheckedIn(s: GuestStayView): boolean {
  return isStayPhysicallyCheckedInRow(guestStayViewToLifecycleRow(s));
}

export type GuestStayRowTone = 'revoked' | 'cancelled' | 'overstay' | 'active' | 'accepted' | 'pending' | 'expired';

export function guestStayRowDisplayRow(row: StayLifecycleRowInput): {
  daysText: string;
  daysCls: string;
  statusLabel: string;
  tone: GuestStayRowTone;
  showRevoke: boolean;
  showRemove: boolean;
} {
  const lc = guestStayLifecycleForDisplayRow(row);
  const checkedIn = isStayPhysicallyCheckedInRow(row);
  const dLeft = guestStayDaysLeft(row.stay_end_date);
  const untilStart = guestStayDaysUntilStart(row.stay_start_date);

  if (row.revoked_at || lc === 'CANCELLED' || row.cancelled_at) {
    return {
      daysText: '—',
      daysCls: 'text-amber-600',
      statusLabel: row.revoked_at ? 'Revoked' : 'Cancelled',
      tone: row.revoked_at ? 'revoked' : 'cancelled',
      showRevoke: false,
      showRemove: false,
    };
  }
  const overstay = checkedIn && guestStayIsOverstayed(row.stay_end_date);
  if (overstay) {
    return {
      daysText: 'EXPIRED',
      daysCls: 'text-red-600',
      statusLabel: 'Overstayed',
      tone: 'overstay',
      showRevoke: false,
      showRemove: true,
    };
  }
  if (lc === 'ACTIVE' || lc === 'OWNER_RESIDENT') {
    const daysText = checkedIn ? `${dLeft}d` : untilStart > 0 ? `Starts in ${untilStart}d` : `${dLeft}d left`;
    const daysCls = checkedIn ? 'text-green-600' : untilStart > 0 ? 'text-sky-600' : 'text-slate-600';
    return { daysText, daysCls, statusLabel: 'Active', tone: 'active', showRevoke: true, showRemove: false };
  }
  if (lc === 'ACCEPTED') {
    return {
      daysText: untilStart > 0 ? `Starts in ${untilStart}d` : `${dLeft}d left`,
      daysCls: untilStart > 0 ? 'text-sky-600' : 'text-slate-600',
      statusLabel: 'Accepted',
      tone: 'accepted',
      showRevoke: true,
      showRemove: false,
    };
  }
  if (lc === 'PENDING_INVITED' || lc === 'PENDING_STAGED') {
    return {
      daysText: untilStart > 0 ? `Starts in ${untilStart}d` : `${dLeft}d left`,
      daysCls: 'text-slate-500',
      statusLabel: 'Pending',
      tone: 'pending',
      showRevoke: true,
      showRemove: false,
    };
  }
  return { daysText: '—', daysCls: 'text-slate-500', statusLabel: 'Expired', tone: 'expired', showRevoke: false, showRemove: false };
}

export function guestStayRowDisplay(stay: OwnerStayView): ReturnType<typeof guestStayRowDisplayRow> {
  return guestStayRowDisplayRow(ownerStayToLifecycleRow(stay));
}

export function guestStayRowDisplayForGuestView(s: GuestStayView): ReturnType<typeof guestStayRowDisplayRow> {
  return guestStayRowDisplayRow(guestStayViewToLifecycleRow(s));
}

/** Owner / manager personal dashboard: non-terminal pipeline + checked-in overstays. */
export function filterOpenGuestStaysForDashboard(stays: OwnerStayView[]): OwnerStayView[] {
  return stays.filter((s) => {
    if (s.checked_out_at || s.cancelled_at || s.revoked_at) return false;
    if (isStayPhysicallyCheckedIn(s)) return true;
    const lc = guestStayLifecycleForDisplayRow(ownerStayToLifecycleRow(s));
    return !guestLifecycleIsTerminal(lc);
  });
}

/** Guest dashboard: non-terminal real stays + checked-in overstays (agreement_archive excluded). */
export function filterOpenGuestFacingStays(stays: GuestStayView[]): GuestStayView[] {
  return stays.filter((s) => {
    if (s.record_kind === 'agreement_archive') return false;
    if (s.checked_out_at || s.cancelled_at || s.revoked_at) return false;
    if (isGuestStayPhysicallyCheckedIn(s)) return true;
    const lc = guestFacingStayLifecycle(s);
    return !guestLifecycleIsTerminal(lc);
  });
}

export function guestDashboardStayRowKey(s: GuestStayView): string {
  return s.record_kind === 'agreement_archive' && s.agreement_signature_id != null
    ? `arch:${s.agreement_signature_id}`
    : `stay:${s.stay_id}`;
}

/** Completed / history rows: archives + anything not in the open guest pipeline. */
export function guestFacingCompletedStays(all: GuestStayView[], open: GuestStayView[]): GuestStayView[] {
  const keys = new Set(open.map(guestDashboardStayRowKey));
  return all.filter((s) => {
    if (s.record_kind === 'agreement_archive') return true;
    return !keys.has(guestDashboardStayRowKey(s));
  });
}

export function filterPhysicallyCheckedInOpenStays(stays: OwnerStayView[]): OwnerStayView[] {
  return stays.filter(
    (s) => isStayPhysicallyCheckedIn(s) && !s.checked_out_at && !s.cancelled_at && !s.revoked_at
  );
}

export function sortGuestStayDashboardRows(stays: OwnerStayView[]): OwnerStayView[] {
  return stays.slice().sort((a, b) => {
    const ao = isStayPhysicallyCheckedIn(a) && guestStayIsOverstayed(String(a.stay_end_date));
    const bo = isStayPhysicallyCheckedIn(b) && guestStayIsOverstayed(String(b.stay_end_date));
    if (ao !== bo) return ao ? -1 : 1;
    const lr = guestLifecycleRank(guestStayLifecycleForDisplayRow(ownerStayToLifecycleRow(a))) -
      guestLifecycleRank(guestStayLifecycleForDisplayRow(ownerStayToLifecycleRow(b)));
    if (lr !== 0) return lr;
    const la = guestStayLifecycleForDisplayRow(ownerStayToLifecycleRow(a));
    const lb = guestStayLifecycleForDisplayRow(ownerStayToLifecycleRow(b));
    if (la === 'ACTIVE' && lb === 'ACTIVE') {
      const aci = isStayPhysicallyCheckedIn(a);
      const bci = isStayPhysicallyCheckedIn(b);
      if (aci !== bci) return aci ? 1 : -1;
    }
    return String(a.stay_start_date).localeCompare(String(b.stay_start_date));
  });
}

export const GUEST_STAY_TABLE_BADGE_CLASS: Record<GuestStayRowTone, string> = {
  revoked: 'bg-amber-50 text-amber-700 border border-amber-500/20',
  cancelled: 'bg-amber-50 text-amber-800 border border-amber-500/20',
  overstay: 'bg-red-50 text-red-600 border border-red-500/20',
  active: 'bg-green-50 text-green-700 border border-green-200',
  accepted: 'bg-sky-50 text-sky-800 border border-sky-200',
  pending: 'bg-slate-100 text-slate-700 border border-slate-200',
  expired: 'bg-slate-100 text-slate-500 border border-slate-200',
};

/** Compact badge for tenant dashboard guest rows. */
export const GUEST_STAY_INLINE_BADGE_CLASS: Record<GuestStayRowTone, string> = {
  revoked: 'bg-amber-50 text-amber-800 border border-amber-200',
  cancelled: 'bg-slate-100 text-slate-700 border border-slate-200',
  overstay: 'bg-red-50 text-red-700 border border-red-200',
  active: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
  accepted: 'bg-sky-50 text-sky-800 border border-sky-200',
  pending: 'bg-amber-50 text-amber-800 border border-amber-200',
  expired: 'bg-slate-100 text-slate-600 border border-slate-200',
};
