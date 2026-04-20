import React, { useState, useEffect } from 'react';
import { Modal, Input, Button } from './UI';
import type { OwnerTenantView } from '../services/api';
import { propertiesApi } from '../services/api';
import { copyToClipboard } from '../utils/clipboard';
import { addCalendarYears, formatCalendarDate, getTodayLocal } from '../utils/dateUtils';

function propertyDisplayLine(t: OwnerTenantView): string {
  const addr = (t.property_address_line || '').trim();
  const name = (t.property_name || '').trim();
  const base = addr || name;
  if (!base) return '';
  if (t.unit_label) return `${base} · Unit ${t.unit_label}`;
  return base;
}

function minNewLeaseEndYmd(t: OwnerTenantView): string {
  if (t.end_date) {
    const [y, m, d] = t.end_date.split('-').map(Number);
    if (!y || !m || !d) return getTodayLocal();
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + 1);
    return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  }
  if (t.start_date) {
    const [y, m, d] = t.start_date.split('-').map(Number);
    if (!y || !m || !d) return getTodayLocal();
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + 1);
    return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  }
  return getTodayLocal();
}

function defaultNewLeaseEndYmd(t: OwnerTenantView): string {
  if (t.end_date) return addCalendarYears(t.end_date, 1);
  if (t.start_date) return addCalendarYears(t.start_date, 1);
  return '';
}

export const ExtendTenantLeaseModal: React.FC<{
  open: boolean;
  tenant: OwnerTenantView | null;
  onClose: () => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onSuccess?: () => void;
}> = ({ open, tenant, onClose, notify, onSuccess }) => {
  const [leaseDate, setLeaseDate] = useState('');
  const [sendEmail, setSendEmail] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [inviteLink, setInviteLink] = useState('');

  useEffect(() => {
    if (open && tenant && tenant.id > 0) {
      const def = defaultNewLeaseEndYmd(tenant);
      const min = minNewLeaseEndYmd(tenant);
      setLeaseDate(def && def >= min ? def : min);
      setSendEmail(true);
      setFormError(null);
      setInviteLink('');
    }
  }, [open, tenant]);

  const handleClose = () => {
    setLeaseDate('');
    setSendEmail(true);
    setFormError(null);
    setInviteLink('');
    onClose();
  };

  const handleSubmit = async () => {
    setFormError(null);
    if (!tenant || tenant.id <= 0) {
      notify('error', 'Invalid tenant row. Refresh and try again.');
      return;
    }
    const ymd = leaseDate.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(ymd)) {
      setFormError('Choose a valid new lease end date.');
      return;
    }
    const minY = minNewLeaseEndYmd(tenant);
    if (ymd < minY) {
      setFormError(`The new end date must be on or after ${formatCalendarDate(minY)}.`);
      return;
    }
    setSubmitting(true);
    try {
      const res = await propertiesApi.createTenantLeaseExtension(tenant.id, {
        lease_end_date: ymd,
        send_email: sendEmail,
      });
      notify('success', res.message || 'Lease extension invitation created.');
      setInviteLink((res.invite_link || '').trim());
      onSuccess?.();
    } catch (e) {
      notify('error', (e as Error)?.message || 'Could not create lease extension invitation.');
    } finally {
      setSubmitting(false);
    }
  };

  if (!tenant || tenant.id <= 0) {
    return null;
  }

  const displayName = (tenant.tenant_name || tenant.tenant_email || 'Tenant').trim();
  const propLine = propertyDisplayLine(tenant);
  const currentLease =
    tenant.start_date && tenant.end_date
      ? `${formatCalendarDate(tenant.start_date)} – ${formatCalendarDate(tenant.end_date)}`
      : tenant.start_date
        ? `${formatCalendarDate(tenant.start_date)} – Open-ended`
        : '';

  return (
    <Modal open={open} onClose={handleClose} title="Extend lease" className="max-w-lg">
      <div className="p-6 space-y-4">
        {inviteLink ? (
          <>
            <p className="text-sm text-slate-600">
              The tenant signs in and accepts this invitation to confirm the new end date. The existing lease assignment is updated — no second lease row is created.
            </p>
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
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm space-y-1">
              <p className="font-semibold text-slate-900">{displayName}</p>
              {propLine ? <p className="text-slate-600">{propLine}</p> : null}
              {currentLease ? <p className="text-slate-500">Current: {currentLease}</p> : null}
            </div>
            <p className="text-sm text-slate-600">
              Set the new lease end date. We create a pending invitation; when the tenant accepts (while signed in), their current lease end date updates.
            </p>
            <Input
              name="lease_end_date"
              label="New lease end date"
              type="date"
              value={leaseDate}
              min={minNewLeaseEndYmd(tenant)}
              onChange={(e) => {
                setFormError(null);
                setLeaseDate(e.target.value);
              }}
              required
            />
            <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer select-none">
              <input
                type="checkbox"
                className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                checked={sendEmail}
                onChange={(e) => setSendEmail(e.target.checked)}
              />
              Send email to tenant with accept link
            </label>
            {formError && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 font-medium">
                {formError}
              </div>
            )}
            <div className="flex gap-3 pt-2">
              <Button variant="outline" className="flex-1" onClick={handleClose} disabled={submitting}>
                Cancel
              </Button>
              <Button variant="primary" className="flex-1" disabled={submitting || !leaseDate.trim()} onClick={handleSubmit}>
                {submitting ? 'Creating…' : 'Create invitation'}
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};
