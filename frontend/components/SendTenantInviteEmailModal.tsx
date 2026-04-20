import React, { useState, useEffect } from 'react';
import { Modal, Input, Button } from './UI';
import type { OwnerTenantView } from '../services/api';
import { propertiesApi, buildGuestInviteUrl } from '../services/api';
import { copyToClipboard } from '../utils/clipboard';

/** Lease line like "Lease 2025-04-01 – 2026-03-31" (ISO dates from API). */
function formatLeaseLine(start: string | null, end: string | null): string {
  if (!start || !end) return '';
  return `Lease ${start} – ${end}`;
}

/** Property line: "400 Elm Street, Austin, TX · Unit 1" (fallback to property name). */
function propertyDisplayLine(t: OwnerTenantView): string {
  const addr = (t.property_address_line || '').trim();
  const name = (t.property_name || '').trim();
  const base = addr || name;
  if (!base) return '';
  if (t.unit_label) {
    return `${base} · Unit ${t.unit_label}`;
  }
  return base;
}

export const SendTenantInviteEmailModal: React.FC<{
  open: boolean;
  tenant: OwnerTenantView | null;
  onClose: () => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onSent?: () => void;
}> = ({ open, tenant, onClose, notify, onSent }) => {
  const [tenantName, setTenantName] = useState('');
  const [email, setEmail] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [inviteLink, setInviteLink] = useState('');

  useEffect(() => {
    if (open && tenant) {
      setTenantName((tenant.tenant_name || '').trim());
      setEmail((tenant.tenant_email || '').trim());
      setFormError(null);
      setInviteLink('');
    }
  }, [open, tenant]);

  const handleClose = () => {
    setTenantName('');
    setEmail('');
    setFormError(null);
    setInviteLink('');
    onClose();
  };

  const invitationId = tenant?.invitation_id;
  const invitationCode = tenant?.invitation_code;

  const handleSubmit = async () => {
    setFormError(null);
    if (!invitationId) {
      notify('error', 'Missing invitation. Refresh and try again.');
      return;
    }
    const name = tenantName.trim();
    const em = email.trim();
    if (!name || !em) {
      setFormError('Please fill in tenant name and tenant email.');
      return;
    }
    if (!em.includes('@')) {
      setFormError('Enter a valid email address.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await propertiesApi.sendTenantInviteEmail(invitationId, { email: em, tenant_name: name });
      notify('success', res.message || 'Invitation email sent.');
      const link = res.invite_link;
      if (link) {
        setInviteLink(link);
      } else if (invitationCode) {
        setInviteLink(buildGuestInviteUrl(invitationCode));
      }
      onSent?.();
    } catch (e) {
      notify('error', (e as Error)?.message || 'Failed to send email.');
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit =
    Boolean(invitationId) &&
    tenantName.trim().length > 0 &&
    email.trim().length > 0 &&
    email.includes('@');

  if (!tenant) {
    return null;
  }

  const displayName = tenantName.trim() || tenant.tenant_name || '—';
  const propLine = propertyDisplayLine(tenant);
  const leaseLine = formatLeaseLine(tenant.start_date, tenant.end_date);

  return (
    <Modal open={open} onClose={handleClose} title="Invite tenant" className="max-w-lg">
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
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm space-y-1">
              <p className="font-semibold text-slate-900">{displayName}</p>
              {propLine ? <p className="text-slate-600">{propLine}</p> : null}
              {leaseLine ? <p className="text-slate-500">{leaseLine}</p> : null}
              {invitationCode ? (
                <p className="text-xs font-mono text-slate-500 pt-1">Invite ID {invitationCode}</p>
              ) : null}
            </div>
            <p className="text-sm text-slate-600">
              The invite link is already created for this lease. Enter the tenant’s name and email to send it by email, or copy the link after sending.
            </p>
            <Input
              name="tenant_name"
              label="Tenant name"
              value={tenantName}
              onChange={(e) => {
                setFormError(null);
                setTenantName(e.target.value);
              }}
              placeholder="Full name"
              required
            />
            <Input
              name="tenant_email"
              label="Tenant email"
              type="email"
              value={email}
              onChange={(e) => {
                setFormError(null);
                setEmail(e.target.value);
              }}
              placeholder="email@example.com"
              required
            />
            {formError && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 font-medium">
                {formError}
              </div>
            )}
            <div className="flex gap-3 pt-2">
              <Button variant="outline" className="flex-1" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                className="flex-1"
                disabled={!canSubmit || submitting || !invitationId}
                onClick={handleSubmit}
              >
                {submitting ? 'Sending…' : 'Send email'}
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};
