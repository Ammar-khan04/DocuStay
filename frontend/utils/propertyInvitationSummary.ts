/** Copy for property cards / live page: invitation pipeline vs unit occupancy. */

export type PropertyInvitationCountFields = {
  invitation_pending_count?: number | null;
  invitation_accepted_count?: number | null;
  invitation_active_count?: number | null;
  invitation_cancelled_count?: number | null;
};

export function propertyInvitationCountsLine(p: PropertyInvitationCountFields): string {
  const pend = p.invitation_pending_count ?? 0;
  const acc = p.invitation_accepted_count ?? 0;
  const act = p.invitation_active_count ?? 0;
  const end = p.invitation_cancelled_count ?? 0;
  return `${pend} pending · ${acc} accepted · ${act} active · ${end} ended`;
}

export const PROPERTY_INVITATION_COUNTS_FOOTNOTE =
  'Invitation counts are separate from occupied units. “Accepted” vs “active” follows the same lease/invite rules as the dashboard: tenant invites use the assignment lease window when present; guest invites use the invitation stay window. “Ended” includes cancelled, expired, or revoked invites.';
