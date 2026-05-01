import type { OwnerInvitationView } from '../services/api';

export type InvitationCountFields = {
  invitation_pending_count?: number | null;
  invitation_accepted_count?: number | null;
  invitation_active_count?: number | null;
  invitation_cancelled_count?: number | null;
};

/** Aligns with InvitationsTabContent `invitationDisplayStatus` for count buckets. */
export function ownerInvitationDisplayBucket(
  inv: OwnerInvitationView
): 'pending' | 'accepted' | 'active' | 'expired' | 'cancelled' {
  const st = (inv.status || 'pending').toLowerCase();
  if (st === 'active') return 'active';
  if (st === 'accepted') return 'accepted';
  if (st === 'expired') return 'expired';
  if (st === 'cancelled' || st === 'revoked') return 'cancelled';
  return 'pending';
}

export function invitationsListAfterOptimisticCancel(
  invitations: OwnerInvitationView[],
  invitationId: number
): OwnerInvitationView[] {
  return invitations.map((i) => (i.id === invitationId ? { ...i, status: 'cancelled' } : i));
}

/** Best-effort property card counts when an invite moves to cancelled (UI only until refetch). */
export function propertyRowAfterOptimisticInviteCancel<T extends InvitationCountFields>(
  prop: T,
  bucket: ReturnType<typeof ownerInvitationDisplayBucket>
): T {
  if (bucket === 'cancelled') return prop;
  const next = { ...prop } as T & InvitationCountFields;
  const dec = (key: keyof InvitationCountFields) => {
    const v = next[key];
    if (typeof v === 'number' && v > 0) (next as InvitationCountFields)[key] = v - 1;
  };
  if (bucket === 'pending') dec('invitation_pending_count');
  if (bucket === 'accepted') dec('invitation_accepted_count');
  if (bucket === 'active') dec('invitation_active_count');
  const cc = next.invitation_cancelled_count;
  if (typeof cc === 'number') next.invitation_cancelled_count = cc + 1;
  else next.invitation_cancelled_count = 1;
  return next as T;
}
