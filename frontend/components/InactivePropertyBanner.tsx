import React from 'react';

/** Single headline for every inactive / unmanaged-property banner (must match across roles and layouts). */
export const INACTIVE_PROPERTY_HEADLINE = 'NO LONGER MANAGED BY DOCUSTAY';

export type InactivePropertyBannerRole = 'owner' | 'manager' | 'tenant' | 'guest';

const MESSAGES: Record<InactivePropertyBannerRole, string> = {
  owner:
    'This property is inactive on your dashboard. Guest stays, tenant leases, and the event ledger remain as read-only history.',
  manager:
    'The owner has removed this property from active management in DocuStay. Your assignment and history remain as read-only.',
  tenant:
    'This property is no longer actively managed in DocuStay. Your lease and guest records stay visible as read-only history.',
  guest:
    'This property is no longer actively managed in DocuStay. Your stay record remains as read-only history.',
};

type Props = {
  role: InactivePropertyBannerRole;
  className?: string;
  /** Tighter padding for embedding in list cards. */
  compact?: boolean;
};

export const InactivePropertyBanner: React.FC<Props> = ({ role, className = '', compact }) => (
  <div
    className={`rounded-xl border-2 border-amber-200 bg-amber-50 text-center shadow-sm ${
      compact ? 'px-3 py-2 mb-2' : 'px-4 py-4 mb-0'
    } ${className}`}
    role="status"
  >
    <p className="text-sm font-bold tracking-[0.12em] text-amber-950">
      {INACTIVE_PROPERTY_HEADLINE}
    </p>
    <p
      className={`text-amber-900/80 mt-1 max-w-xl mx-auto ${compact ? 'text-[10px] leading-snug' : 'text-xs'}`}
    >
      {MESSAGES[role]}
    </p>
  </div>
);
