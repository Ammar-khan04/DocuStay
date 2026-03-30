import React, { useState, useEffect } from 'react';
import { Modal, Input, Button } from './UI';
import { copyToClipboard } from '../utils/clipboard';
import { getTodayLocal } from '../utils/dateUtils';
import { toUserFriendlyInvitationError } from '../utils/invitationErrors';
import { buildGuestInviteUrl } from '../services/api';

export type InviteTenantProperty = { id: number; name?: string | null; street?: string; address?: string };
export type InviteTenantUnit = { id: number; unit_label: string };

export interface InviteTenantModalProps {
  open: boolean;
  onClose: () => void;
  /** List of properties to choose from (owner or manager list). Ignored when preselectedUnit is set. */
  properties: InviteTenantProperty[];
  /** Load units for a property (owner: propertiesApi.getUnits, manager: dashboardApi.managerUnits). Ignored when preselectedUnit is set. */
  getUnits: (propertyId: number) => Promise<InviteTenantUnit[]>;
  /** When set (e.g. manager chose unit from "Select property & unit"), skip property/unit dropdowns and use this unit. */
  preselectedUnit?: { unitId: number; unitLabel: string } | null;
  /** Create the tenant invitation (owner: propertiesApi.inviteTenant/inviteTenantForProperty, manager: dashboardApi.managerInviteTenant) */
  createInvitation: (params: {
    propertyId: number;
    unitId: number | null;
    tenant_name: string;
    tenant_email: string;
    lease_start_date: string;
    lease_end_date: string;
  }) => Promise<{ invitation_code: string }>;
  notify: (t: 'success' | 'error', m: string) => void;
  onSuccess?: () => void;
}

export const InviteTenantModal: React.FC<InviteTenantModalProps> = ({
  open,
  onClose,
  properties,
  getUnits,
  preselectedUnit = null,
  createInvitation,
  notify,
  onSuccess,
}) => {
  const [formData, setFormData] = useState({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [unitId, setUnitId] = useState<number | null>(null);
  const [units, setUnits] = useState<InviteTenantUnit[]>([]);
  const [unitsLoading, setUnitsLoading] = useState(false);
  const [inviteLink, setInviteLink] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setInviteLink('');
      setFormError(null);
      setFormData({ tenant_name: '', tenant_email: '', lease_start_date: '', lease_end_date: '' });
      setPropertyId(properties.length > 0 ? properties[0].id : null);
      setUnitId(null);
      setUnits([]);
      return;
    }
    if (preselectedUnit) return;
    if (properties.length > 0 && !propertyId) setPropertyId(properties[0].id);
  }, [open, properties, propertyId, preselectedUnit]);

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
    onClose();
    onSuccess?.();
  };

  const handleSubmit = async () => {
    setFormError(null);
    const effectivePropertyId = preselectedUnit ? 0 : propertyId;
    const effectiveUnitId = preselectedUnit ? preselectedUnit.unitId : (unitId ?? null);
    if (!preselectedUnit && !effectivePropertyId) {
      setFormError('Please select a property.');
      return;
    }
    if (!formData.tenant_name.trim() || !(formData.tenant_email || '').trim() || !formData.lease_start_date || !formData.lease_end_date) {
      setFormError('Please fill in tenant name, tenant email, and lease dates.');
      return;
    }
    if (formData.lease_start_date < getTodayLocal()) {
      setFormError('Lease start date cannot be in the past.');
      return;
    }
    if (new Date(formData.lease_end_date) <= new Date(formData.lease_start_date)) {
      setFormError('Lease end date must be after lease start date.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await createInvitation({
        propertyId: effectivePropertyId ?? 0,
        unitId: effectiveUnitId,
        tenant_name: formData.tenant_name.trim(),
        tenant_email: formData.tenant_email.trim(),
        lease_start_date: formData.lease_start_date,
        lease_end_date: formData.lease_end_date,
      });
      const code = res?.invitation_code;
      if (code) {
        setInviteLink(buildGuestInviteUrl(code));
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

  const effectiveUnitId = preselectedUnit ? preselectedUnit.unitId : (unitId ?? (units.length > 0 ? units[0].id : null));
  const canSubmit =
    formData.tenant_name.trim() &&
    formData.lease_start_date &&
    formData.lease_end_date &&
    (preselectedUnit ? true : (propertyId && (units.length === 0 || effectiveUnitId !== null)));

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Invite tenant"
      className="max-w-lg"
    >
      <div className="p-6 space-y-4">
        {inviteLink ? (
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
        ) : (
          <>
            {preselectedUnit ? (
              <p className="text-sm text-slate-600">Unit {preselectedUnit.unitLabel}. The tenant will receive an invite link to register.</p>
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
            <Input
              name="tenant_name"
              label="Tenant name"
              value={formData.tenant_name}
              onChange={(e) => { setFormError(null); setFormData({ ...formData, tenant_name: e.target.value }); }}
              placeholder="Full name"
              required
            />
            <Input
              name="tenant_email"
              label="Tenant email"
              type="email"
              value={formData.tenant_email}
              onChange={(e) => { setFormError(null); setFormData({ ...formData, tenant_email: e.target.value }); }}
              placeholder="email@example.com"
              required
            />
            <Input
              name="lease_start_date"
              label="Lease start"
              type="date"
              min={getTodayLocal()}
              value={formData.lease_start_date}
              onChange={(e) => { setFormError(null); setFormData({ ...formData, lease_start_date: e.target.value }); }}
              required
            />
            <Input
              name="lease_end_date"
              label="Lease end"
              type="date"
              min={formData.lease_start_date || getTodayLocal()}
              value={formData.lease_end_date}
              onChange={(e) => { setFormError(null); setFormData({ ...formData, lease_end_date: e.target.value }); }}
              required
            />
            {formError && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 font-medium">
                {formError}
              </div>
            )}
            <div className="flex gap-3 pt-2">
              <Button variant="outline" onClick={onClose} className="flex-1">
                Cancel
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={submitting || !canSubmit}
                className="flex-1"
              >
                {submitting ? 'Creating…' : 'Create invitation'}
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};
