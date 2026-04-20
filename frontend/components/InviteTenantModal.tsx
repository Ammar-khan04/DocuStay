import React, { useState, useEffect } from 'react';
import { Modal, Input, Button } from './UI';
import { copyToClipboard } from '../utils/clipboard';
import { addCalendarYears, formatCalendarDate, getTodayLocal } from '../utils/dateUtils';
import { toUserFriendlyInvitationError } from '../utils/invitationErrors';
import { buildGuestInviteUrl } from '../services/api';
import { validateCoTenantRows, type CoTenantInviteRow } from '../utils/inviteTenantBatch';

export type InviteTenantProperty = { id: number; name?: string | null; street?: string; address?: string };
export type InviteTenantUnit = { id: number; unit_label: string };

const MAX_COTENANTS = 12;

const emptyCohortRows = (): CoTenantInviteRow[] => [
  { tenant_name: '', tenant_email: '' },
  { tenant_name: '', tenant_email: '' },
];

export interface InviteTenantModalProps {
  open: boolean;
  onClose: () => void;
  /** List of properties to choose from (owner or manager list). Ignored when preselectedUnit is set. */
  properties: InviteTenantProperty[];
  /** Load units for a property (owner: propertiesApi.getUnits, manager: dashboardApi.managerUnits). Ignored when preselectedUnit is set. */
  getUnits: (propertyId: number) => Promise<InviteTenantUnit[]>;
  /** When set (e.g. manager chose unit from "Select property & unit"), skip property/unit dropdowns and use this unit. */
  preselectedUnit?: { unitId: number; unitLabel: string } | null;
  /**
   * With `preselectedUnit`: tenant can only enter name(s) / email(s) and send. Unit is fixed.
   * Lease uses `lockedLeaseDates` when both start and end are set (e.g. existing tenant on the unit);
   * otherwise falls back to today → today + 1 year when this flag is true.
   */
  restrictToTenantFieldsOnly?: boolean;
  /** Required for matching an existing lease (co-tenant invite from unit). ISO date strings YYYY-MM-DD. */
  lockedLeaseDates?: { start: string; end: string } | null;
  /** Create the tenant invitation (owner: propertiesApi.inviteTenant/inviteTenantForProperty, manager: dashboardApi.managerInviteTenant) */
  createInvitation: (params: {
    propertyId: number;
    unitId: number | null;
    tenant_name: string;
    tenant_email: string;
    lease_start_date: string;
    lease_end_date: string;
    shared_lease: boolean;
  }) => Promise<{ invitation_code: string }>;
  notify: (t: 'success' | 'error', m: string) => void;
  onSuccess?: () => void;
  /** When the inviter is a demo account, copy links use `#demo/invite/...`. */
  guestInviteUrlIsDemo?: boolean;
}

export const InviteTenantModal: React.FC<InviteTenantModalProps> = ({
  open,
  onClose,
  properties,
  getUnits,
  preselectedUnit = null,
  restrictToTenantFieldsOnly = false,
  lockedLeaseDates = null,
  createInvitation,
  notify,
  onSuccess,
  guestInviteUrlIsDemo = false,
}) => {
  const leaseAndUnitLocked = Boolean(preselectedUnit && restrictToTenantFieldsOnly);
  const [inviteMode, setInviteMode] = useState<'single' | 'co_tenants'>('single');
  const [formData, setFormData] = useState({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
  const [cohortRows, setCohortRows] = useState<CoTenantInviteRow[]>(emptyCohortRows);
  const [firstInviteSharedLease, setFirstInviteSharedLease] = useState(false);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [unitId, setUnitId] = useState<number | null>(null);
  const [units, setUnits] = useState<InviteTenantUnit[]>([]);
  const [unitsLoading, setUnitsLoading] = useState(false);
  const [inviteLink, setInviteLink] = useState('');
  const [inviteBatchLinks, setInviteBatchLinks] = useState<{ tenant_name: string; link: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [batchProgress, setBatchProgress] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [sharedLease, setSharedLease] = useState(false);

  useEffect(() => {
    if (!open) {
      setInviteLink('');
      setInviteBatchLinks([]);
      setFormError(null);
      setSharedLease(false);
      setInviteMode('single');
      setCohortRows(emptyCohortRows());
      setFirstInviteSharedLease(false);
      setBatchProgress(null);
      setFormData({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
      setPropertyId(properties.length > 0 ? properties[0].id : null);
      setUnitId(null);
      setUnits([]);
      return;
    }
    if (preselectedUnit) {
      if (restrictToTenantFieldsOnly) {
        const ls = (lockedLeaseDates?.start || '').trim().slice(0, 10);
        const le = (lockedLeaseDates?.end || '').trim().slice(0, 10);
        const start = ls && le ? ls : getTodayLocal();
        const end = ls && le ? le : addCalendarYears(getTodayLocal(), 1);
        setFormData({ tenant_name: '', tenant_email: '', lease_start_date: start, lease_end_date: end });
        setInviteMode('single');
        setCohortRows(emptyCohortRows());
        setSharedLease(false);
        setFirstInviteSharedLease(false);
        setFormError(null);
      } else {
        setFormData({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
      }
      return;
    }
    if (properties.length > 0 && !propertyId) setPropertyId(properties[0].id);
  }, [open, properties, propertyId, preselectedUnit?.unitId, restrictToTenantFieldsOnly, lockedLeaseDates?.start, lockedLeaseDates?.end]);

  useEffect(() => {
    if (preselectedUnit || !open || !propertyId) {
      if (!preselectedUnit) {
        setUnits([]);
        setUnitId(null);
      }
      return;
    }
    setUnitsLoading(true);
    getUnits(propertyId)
      .then((list) => {
        const withRealIds = (list || []).filter((u) => u.id >= 0);
        setUnits(withRealIds);
        setUnitId(withRealIds.length > 0 ? withRealIds[0].id : null);
      })
      .catch(() => {
        setUnits([]);
        setUnitId(null);
      })
      .finally(() => setUnitsLoading(false));
  }, [open, propertyId, getUnits, preselectedUnit]);

  const handleClose = () => {
    setInviteLink('');
    setInviteBatchLinks([]);
    onClose();
    onSuccess?.();
  };

  const effectivePropertyId = preselectedUnit ? 0 : propertyId;
  const effectiveUnitId = preselectedUnit ? preselectedUnit.unitId : (unitId ?? null);

  const runCreateWithParams = async (args: {
    tenant_name: string;
    tenant_email: string;
    shared_lease: boolean;
  }) =>
    createInvitation({
      propertyId: effectivePropertyId ?? 0,
      unitId: effectiveUnitId,
      tenant_name: args.tenant_name,
      tenant_email: args.tenant_email,
      lease_start_date: formData.lease_start_date,
      lease_end_date: formData.lease_end_date,
      shared_lease: args.shared_lease,
    });

  const handleSubmit = async () => {
    setFormError(null);
    setBatchProgress(null);
    if (!preselectedUnit && !effectivePropertyId) {
      setFormError('Please select a property.');
      return;
    }
    if (!leaseAndUnitLocked) {
      if (formData.lease_start_date < getTodayLocal()) {
        setFormError('Lease start date cannot be in the past.');
        return;
      }
      if (formData.lease_end_date <= formData.lease_start_date) {
        setFormError('Lease end date must be after lease start date.');
        return;
      }
    }

    if (inviteMode === 'co_tenants') {
      const cohortErr = validateCoTenantRows(cohortRows);
      if (cohortErr) {
        setFormError(cohortErr);
        return;
      }
      setSubmitting(true);
      try {
        const results: { tenant_name: string; link: string }[] = [];
        const rows = cohortRows.map((r) => ({ tenant_name: r.tenant_name.trim(), tenant_email: r.tenant_email.trim() }));
        for (let i = 0; i < rows.length; i += 1) {
          setBatchProgress(`Creating invitation ${i + 1} of ${rows.length}…`);
          const shared_lease = i === 0 ? firstInviteSharedLease : true;
          try {
            const res = await runCreateWithParams({
              tenant_name: rows[i].tenant_name,
              tenant_email: rows[i].tenant_email,
              shared_lease,
            });
            const code = res?.invitation_code;
            if (!code) {
              throw new Error('Server did not return an invitation code.');
            }
            results.push({
              tenant_name: rows[i].tenant_name,
              link: buildGuestInviteUrl(code, { isDemo: guestInviteUrlIsDemo }),
            });
          } catch (e) {
            const raw = (e as Error)?.message ?? '';
            if (results.length > 0) {
              setInviteBatchLinks(results);
              setFormError(
                raw.includes('overlap')
                  ? raw
                  : `${toUserFriendlyInvitationError(raw || 'Failed.')} (${results.length} invitation(s) were created; copy those links below, then fix remaining co-tenants.)`,
              );
              notify('error', `Stopped at co-tenant ${i + 1}. Earlier invitation links are shown below.`);
            } else {
              setFormError(raw.includes('overlap') ? raw : toUserFriendlyInvitationError(raw || 'Failed to create invitation.'));
            }
            setBatchProgress(null);
            return;
          }
        }
        setInviteBatchLinks(results);
        setFormError(null);
        setBatchProgress(null);
        notify('success', `Created ${results.length} tenant invitations. Share each link with the right person.`);
        setCohortRows(emptyCohortRows());
      } finally {
        setSubmitting(false);
        setBatchProgress(null);
      }
      return;
    }

    if (!formData.tenant_name.trim() || !(formData.tenant_email || '').trim()) {
      setFormError('Please fill in tenant name and email.');
      return;
    }
    if (!formData.lease_start_date || !formData.lease_end_date) {
      setFormError(
        leaseAndUnitLocked
          ? 'Lease dates are missing. Close and reopen the invite.'
          : 'Please fill in lease start and end dates.',
      );
      return;
    }

    setSubmitting(true);
    try {
      const res = await runCreateWithParams({
        tenant_name: formData.tenant_name.trim(),
        tenant_email: formData.tenant_email.trim(),
        shared_lease: sharedLease,
      });
      const code = res?.invitation_code;
      if (code) {
        setInviteLink(buildGuestInviteUrl(code, { isDemo: guestInviteUrlIsDemo }));
        setFormError(null);
        notify('success', 'Tenant invitation created. Share the invite link with the tenant.');
        setFormData({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
      } else {
        setFormError("We couldn't create a valid invitation link. Please try again.");
      }
    } catch (e) {
      const raw = (e as Error)?.message ?? '';
      setFormError(raw.includes('overlap') ? raw : toUserFriendlyInvitationError(raw || 'Failed to create invitation.'));
    } finally {
      setSubmitting(false);
    }
  };

  const effectiveUnitIdResolved = preselectedUnit ? preselectedUnit.unitId : (unitId ?? (units.length > 0 ? units[0].id : null));
  const canSubmitSingle =
    formData.tenant_name.trim() &&
    (formData.tenant_email || '').trim() &&
    formData.lease_start_date &&
    formData.lease_end_date &&
    (preselectedUnit ? true : propertyId && (units.length === 0 || effectiveUnitIdResolved !== null));

  const canSubmitCohort =
    cohortRows.every((r) => r.tenant_name.trim() && r.tenant_email.trim()) &&
    cohortRows.length >= 2 &&
    formData.lease_start_date &&
    formData.lease_end_date &&
    (preselectedUnit ? true : propertyId && (units.length === 0 || effectiveUnitIdResolved !== null));

  const canSubmit = inviteMode === 'single' ? canSubmitSingle : canSubmitCohort;

  const showSuccess = Boolean(inviteLink || inviteBatchLinks.length > 0);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Invite tenant"
      className={inviteMode === 'co_tenants' && !showSuccess ? 'max-w-xl' : 'max-w-lg'}
    >
      <div className="p-6 space-y-4">
        {showSuccess ? (
          <>
            {inviteBatchLinks.length > 0 ? (
              <>
                {formError ? (
                  <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-900 font-medium">
                    {formError}
                  </div>
                ) : null}
                <p className="text-sm text-slate-600">
                  Each co-tenant must use their own link to register. Copy and send individually.
                </p>
                <ul className="space-y-3 max-h-[min(24rem,50vh)] overflow-y-auto pr-1">
                  {inviteBatchLinks.map((item) => (
                    <li key={item.link} className="rounded-xl border border-slate-200 bg-slate-50/80 p-3">
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
                      const blob = inviteBatchLinks.map((b) => `${b.tenant_name}\t${b.link}`).join('\n');
                      const ok = await copyToClipboard(blob);
                      if (ok) notify('success', 'All lines copied (name + tab + link).');
                      else notify('error', 'Copy failed.');
                    }}
                  >
                    Copy all
                  </Button>
                  <Button className="flex-1" onClick={handleClose}>
                    Done
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-slate-600">Share this link with the tenant to complete registration.</p>
                <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-800 break-all font-mono">
                  {inviteLink}
                </div>
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={async () => {
                      const ok = await copyToClipboard(inviteLink);
                      if (ok) notify('success', 'Link copied to clipboard.');
                      else notify('error', 'Copy failed. Please copy the link manually.');
                    }}
                  >
                    Copy link
                  </Button>
                  <Button className="flex-1" onClick={handleClose}>
                    Done
                  </Button>
                </div>
              </>
            )}
          </>
        ) : (
          <>
            {!leaseAndUnitLocked && (
              <div className="flex rounded-lg border border-slate-200 p-1 bg-slate-50 gap-1">
                <button
                  type="button"
                  className={`flex-1 rounded-md py-2 px-3 text-sm font-medium transition-colors ${
                    inviteMode === 'single' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                  }`}
                  onClick={() => {
                    setInviteMode('single');
                    setFormError(null);
                  }}
                >
                  One tenant
                </button>
                <button
                  type="button"
                  className={`flex-1 rounded-md py-2 px-3 text-sm font-medium transition-colors ${
                    inviteMode === 'co_tenants' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                  }`}
                  onClick={() => {
                    setInviteMode('co_tenants');
                    setFormError(null);
                  }}
                >
                  Multiple co-tenants
                </button>
              </div>
            )}
            {inviteMode === 'co_tenants' && !leaseAndUnitLocked && (
              <p className="text-sm text-slate-600">
                Every person shares the same lease dates below. DocuStay creates one invitation per email; later invites in the batch are marked as shared-lease automatically so they can overlap the first.
              </p>
            )}
            {preselectedUnit ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-700 space-y-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Unit</p>
                <p className="font-medium text-slate-900">Unit {preselectedUnit.unitLabel}</p>
                {leaseAndUnitLocked && formData.lease_start_date && formData.lease_end_date && (
                  <>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 pt-2">Lease period</p>
                    <p className="text-slate-800">
                      {formatCalendarDate(formData.lease_start_date)} – {formatCalendarDate(formData.lease_end_date)}
                    </p>
                    <p className="text-xs text-slate-500 pt-1">
                      {lockedLeaseDates?.start && lockedLeaseDates?.end
                        ? 'Lease matches the current lease on file for this unit. You can only add name and email here.'
                        : 'You can only add the tenant&apos;s name and email from here.'}
                    </p>
                  </>
                )}
                {!leaseAndUnitLocked && (
                  <p className="text-xs text-slate-500 pt-1">The tenant will receive an invite link to register.</p>
                )}
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Property</label>
                  <select
                    value={propertyId ?? ''}
                    onChange={(e) => {
                      const pid = Number(e.target.value) || null;
                      setPropertyId(pid);
                      setUnitId(null);
                    }}
                    className="w-full px-4 py-2.5 bg-white border border-gray-300 rounded-lg text-gray-900"
                  >
                    <option value="">Select property</option>
                    {properties.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name || p.street || p.address || `Property ${p.id}`}
                      </option>
                    ))}
                  </select>
                </div>
                {units.length > 0 && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">Unit</label>
                    <select
                      value={unitId ?? ''}
                      onChange={(e) => setUnitId(Number(e.target.value) || null)}
                      className="w-full px-4 py-2.5 bg-white border border-gray-300 rounded-lg text-gray-900"
                    >
                      <option value="">Select unit</option>
                      {units.map((u) => (
                        <option key={u.id} value={u.id}>
                          Unit {u.unit_label}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {propertyId && units.length === 0 && !unitsLoading && (
                  <p className="text-sm text-slate-600">Single-unit property — invitation will be for the whole property.</p>
                )}
              </>
            )}
            {inviteMode === 'single' ? (
              <>
                <Input
                  name="tenant_name"
                  label="Tenant name"
                  value={formData.tenant_name}
                  onChange={(e) => {
                    setFormError(null);
                    setFormData({ ...formData, tenant_name: e.target.value });
                  }}
                  placeholder="Full name"
                  required
                />
                <Input
                  name="tenant_email"
                  label="Tenant email"
                  type="email"
                  value={formData.tenant_email}
                  onChange={(e) => {
                    setFormError(null);
                    setFormData({ ...formData, tenant_email: e.target.value });
                  }}
                  placeholder="email@example.com"
                  required
                />
              </>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-800">Co-tenants</span>
                  <Button
                    type="button"
                    variant="outline"
                    className="text-xs h-8"
                    disabled={cohortRows.length >= MAX_COTENANTS}
                    onClick={() => {
                      setFormError(null);
                      setCohortRows([...cohortRows, { tenant_name: '', tenant_email: '' }]);
                    }}
                  >
                    Add person
                  </Button>
                </div>
                <div className="space-y-3 max-h-[min(14rem,40vh)] overflow-y-auto pr-1">
                  {cohortRows.map((row, idx) => (
                    <div
                      key={`cohort-${idx}`}
                      className="rounded-xl border border-slate-200 bg-white p-3 space-y-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Person {idx + 1}</span>
                        {cohortRows.length > 2 && (
                          <button
                            type="button"
                            className="text-xs font-medium text-red-600 hover:text-red-700"
                            onClick={() => {
                              setFormError(null);
                              setCohortRows(cohortRows.filter((_, j) => j !== idx));
                            }}
                          >
                            Remove
                          </button>
                        )}
                      </div>
                      <Input
                        name={`cohort_name_${idx}`}
                        label="Name"
                        value={row.tenant_name}
                        onChange={(e) => {
                          setFormError(null);
                          const next = [...cohortRows];
                          next[idx] = { ...next[idx], tenant_name: e.target.value };
                          setCohortRows(next);
                        }}
                        placeholder="Full name"
                      />
                      <Input
                        name={`cohort_email_${idx}`}
                        label="Email"
                        type="email"
                        value={row.tenant_email}
                        onChange={(e) => {
                          setFormError(null);
                          const next = [...cohortRows];
                          next[idx] = { ...next[idx], tenant_email: e.target.value };
                          setCohortRows(next);
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
                    checked={firstInviteSharedLease}
                    onChange={(e) => {
                      setFormError(null);
                      setFirstInviteSharedLease(e.target.checked);
                    }}
                  />
                  <span className="text-sm text-slate-700">
                    <span className="font-medium text-slate-900">First invite overlaps an existing lease or invite</span>
                    <span className="block text-slate-600 mt-0.5">
                      Check this if someone already holds (or has a pending invite for) these dates. Leave unchecked when the unit is empty and everyone in the list is new to this lease window.
                    </span>
                  </span>
                </label>
              </div>
            )}
            {!leaseAndUnitLocked && (
              <>
                <Input
                  name="lease_start_date"
                  label="Lease start"
                  type="date"
                  min={getTodayLocal()}
                  value={formData.lease_start_date}
                  onChange={(e) => {
                    setFormError(null);
                    setFormData({ ...formData, lease_start_date: e.target.value });
                  }}
                  required
                />
                <Input
                  name="lease_end_date"
                  label="Lease end"
                  type="date"
                  min={formData.lease_start_date || getTodayLocal()}
                  value={formData.lease_end_date}
                  onChange={(e) => {
                    setFormError(null);
                    setFormData({ ...formData, lease_end_date: e.target.value });
                  }}
                  required
                />
              </>
            )}
            {inviteMode === 'single' && !leaseAndUnitLocked && (
              <label className="flex items-start gap-3 cursor-pointer rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3">
                <input
                  type="checkbox"
                  className="mt-1 rounded border-gray-300"
                  checked={sharedLease}
                  onChange={(e) => {
                    setFormError(null);
                    setSharedLease(e.target.checked);
                  }}
                />
                <span className="text-sm text-slate-700">
                  <span className="font-medium text-slate-900">Additional occupant (shared lease)</span>
                  <span className="block text-slate-600 mt-0.5">
                    Allow this invite even when the unit already has a tenant on overlapping dates. Use only when this person is a co-tenant or roommate on the same lease window.
                  </span>
                </span>
              </label>
            )}
            {batchProgress && (
              <p className="text-sm text-slate-500 font-medium">{batchProgress}</p>
            )}
            {formError && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 font-medium">
                {formError}
              </div>
            )}
            <div className="flex gap-3 pt-2">
              <Button variant="outline" onClick={onClose} className="flex-1">
                Cancel
              </Button>
              <Button onClick={handleSubmit} disabled={submitting || !canSubmit} className="flex-1">
                {submitting ? 'Creating…' : inviteMode === 'co_tenants' ? `Create ${cohortRows.filter((r) => r.tenant_name.trim() && r.tenant_email.trim()).length || cohortRows.length} invitations` : 'Create invitation'}
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};
