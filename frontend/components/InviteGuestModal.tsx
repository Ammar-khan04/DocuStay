import React, { useState, useEffect, useRef } from 'react';
import { Modal, Input, Button } from './UI';
import { invitationsApi, propertiesApi, dashboardApi, buildGuestInviteUrl, getContextMode } from '../services/api';
import { copyToClipboard } from '../utils/clipboard';
import { getTodayLocal } from '../utils/dateUtils';
import { toUserFriendlyInvitationError } from '../utils/invitationErrors';
import { isValidInviteEmailFormat } from '../utils/emailValidation';
import type { UserSession } from '../types';
import { UserType } from '../types';

interface InviteGuestModalProps {
  open: boolean;
  onClose: () => void;
  user: UserSession | null;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onSuccess?: () => void;
  navigate?: (v: string) => void;
  /** When opening from a property page, preselect this property */
  initialPropertyId?: number | null;
  /** When provided (e.g. tenant or owner personal mode), use this unit and skip property selector */
  unitId?: number | null;
  /** When provided with unitId, show this label in modal title/body so invite is clearly "per property/stay" */
  propertyOrStayLabel?: string | null;
  /** When provided (tenant view), guest dates must fall within tenant's stay. Used for min/max on date inputs. */
  tenantStayStartDate?: string | null;
  tenantStayEndDate?: string | null;
  /** When provided, on success we call this with the link and close the modal instead of showing link in-place. Use for parent to show link in a separate modal. */
  onLinkGenerated?: (link: string) => void;
  /** When provided (e.g. manager), load properties via this instead of propertiesApi.list() */
  propertiesLoader?: () => Promise<Array<{ id: number; name?: string | null; street?: string; city?: string; state?: string; is_multi_unit?: boolean }>>;
  /** When provided (e.g. manager), load units via this instead of propertiesApi.getUnits(propertyId) */
  unitsLoader?: (propertyId: number) => Promise<Array<{ id: number; unit_label: string }>>;
  /** When opening (e.g. after approving extension), pre-fill guest fields. */
  prefillGuestEmail?: string | null;
  prefillGuestName?: string | null;
}

export const InviteGuestModal: React.FC<InviteGuestModalProps> = ({
  open,
  onClose,
  user,
  setLoading,
  notify,
  onSuccess,
  navigate = (_: string) => {},
  initialPropertyId = null,
  unitId = null,
  propertyOrStayLabel = null,
  tenantStayStartDate = null,
  tenantStayEndDate = null,
  onLinkGenerated,
  propertiesLoader,
  unitsLoader,
  prefillGuestEmail = null,
  prefillGuestName = null,
}) => {
  const [formData, setFormData] = useState({ guest_name: '', guest_email: '', checkin_date: '', checkout_date: '' });
  const [inviteLink, setInviteLink] = useState('');
  const [showLinkResult, setShowLinkResult] = useState(false);
  const [properties, setProperties] = useState<Array<{ id: number; name: string | null; street: string; city: string; state: string; zip_code: string | null; owner_occupied?: boolean; is_multi_unit?: boolean }>>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [units, setUnits] = useState<Array<{ id: number; unit_label: string; occupancy_status: string; is_primary_residence?: boolean }>>([]);
  const [unitsLoading, setUnitsLoading] = useState(false);
  const [propertiesLoading, setPropertiesLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const linkGeneratedRef = useRef(false);

  useEffect(() => {
    if (!open || (!prefillGuestEmail?.trim() && !prefillGuestName?.trim())) return;
    setFormData((prev) => ({
      ...prev,
      guest_email: prefillGuestEmail?.trim() || prev.guest_email,
      guest_name: prefillGuestName?.trim() || prev.guest_name,
    }));
  }, [open, prefillGuestEmail, prefillGuestName]);

  useEffect(() => {
    if (!open) {
      // Only reset when modal is closed AND we're not showing a link
      if (!linkGeneratedRef.current) {
        setShowLinkResult(false);
        setInviteLink('');
      }
      setFormData({ guest_name: '', guest_email: '', checkin_date: '', checkout_date: '' });
      setFormError(null);
      setSelectedUnitId(null);
      setUnits([]);
      setPropertiesLoading(false);
      setUnitsLoading(false);
      linkGeneratedRef.current = false;
      return;
    }
    // When unitId is provided (tenant or owner personal mode), skip loading properties
    if (unitId != null) {
      setPropertiesLoading(false);
      return;
    }
    // When opening from a property page, preselect that property immediately so the form is usable
    if (initialPropertyId != null) {
      setPropertyId(initialPropertyId);
    }
    setPropertiesLoading(true);
    const loadProps = propertiesLoader
      ? propertiesLoader().then((list) => {
          const arr = list || [];
          setProperties(arr);
          if (arr.length > 0) {
            const preferred =
              initialPropertyId != null && arr.some((p) => p.id === initialPropertyId)
                ? initialPropertyId
                : arr[0].id;
            setPropertyId(preferred);
          } else {
            setPropertyId(null);
          }
        })
      : propertiesApi.list().then((list) => {
          const isPersonal = getContextMode() === 'personal';
          const isOwner = (user?.user_type ?? '') === UserType.PROPERTY_OWNER;
          let inviteable = list;
          if (isOwner && isPersonal) {
            inviteable = list.filter((p) => !!p.owner_occupied);
          } else if (isOwner && !isPersonal) {
            inviteable = list.filter((p) => !p.owner_occupied);
          }
          setProperties(inviteable);
          if (inviteable.length > 0) {
            if (initialPropertyId != null && inviteable.some((p) => p.id === initialPropertyId)) {
              setPropertyId(initialPropertyId);
            } else if (initialPropertyId != null && isOwner && isPersonal && !inviteable.some((p) => p.id === initialPropertyId)) {
              return propertiesApi.get(initialPropertyId).then((prop) => {
                setProperties([prop]);
                setPropertyId(prop.id);
              });
            } else {
              const preferred =
                initialPropertyId != null && inviteable.some((p) => p.id === initialPropertyId)
                  ? initialPropertyId
                  : inviteable[0].id;
              setPropertyId(preferred);
            }
          } else if (initialPropertyId != null) {
            return propertiesApi.get(initialPropertyId).then((prop) => {
              const okForOwner =
                !isOwner ||
                (isPersonal ? true : !prop.owner_occupied);
              if (okForOwner) {
                setProperties([prop]);
                setPropertyId(prop.id);
              } else {
                setPropertyId(null);
              }
            });
          } else {
            setPropertyId(null);
          }
        });
    loadProps
      .catch(() => {
        if (initialPropertyId != null && !propertiesLoader) {
          const isPersonal = getContextMode() === 'personal';
          const isOwner = (user?.user_type ?? '') === UserType.PROPERTY_OWNER;
          propertiesApi
            .get(initialPropertyId)
            .then((prop) => {
              const okForOwner =
                !isOwner ||
                (isPersonal ? true : !prop.owner_occupied);
              if (okForOwner) {
                setProperties([prop]);
                setPropertyId(prop.id);
              } else {
                setPropertyId(null);
              }
            })
            .catch(() => setPropertyId(null));
        } else {
          setProperties([]);
          setPropertyId(null);
        }
      })
      .finally(() => setPropertiesLoading(false));
  }, [open, initialPropertyId, unitId, propertiesLoader, user?.user_type]);

  // When property changes, fetch units (multi-unit for owner, or when unitsLoader provided for manager)
  useEffect(() => {
    if (unitId != null || !propertyId) {
      setUnits([]);
      setSelectedUnitId(null);
      return;
    }
    const prop = properties.find((p) => p.id === propertyId);
    const shouldLoadUnits = unitsLoader ? true : !!prop?.is_multi_unit;
    if (!shouldLoadUnits) {
      setUnits([]);
      setSelectedUnitId(null);
      return;
    }
    setUnitsLoading(true);
    const load = unitsLoader
      ? unitsLoader(propertyId)
      : propertiesApi.getUnits(propertyId);
    load
      .then((list) => {
        const withRealIds = (list || []).filter((u) => u.id > 0);
        const ownerPersonal =
          getContextMode() === 'personal' && (user?.user_type ?? '') === UserType.PROPERTY_OWNER && !unitsLoader;
        let usable = withRealIds;
        if (ownerPersonal) {
          const primaryOnly = withRealIds.filter((u) => !!(u as { is_primary_residence?: boolean }).is_primary_residence);
          const fromPropertyPage = initialPropertyId != null && propertyId === initialPropertyId;
          usable = fromPropertyPage
            ? (primaryOnly.length > 0 ? primaryOnly : withRealIds)
            : (primaryOnly.length > 0 ? primaryOnly : (prop?.owner_occupied ? withRealIds : primaryOnly));
        }
        setUnits(usable);
        setSelectedUnitId(usable.length > 0 ? usable[0].id : null);
      })
      .catch(() => {
        setUnits([]);
        setSelectedUnitId(null);
      })
      .finally(() => setUnitsLoading(false));
  }, [propertyId, unitId, properties, unitsLoader, user?.user_type, initialPropertyId]);

  const selectedProperty = properties.find((p) => p.id === propertyId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (unitId == null && !propertyId) {
      setFormError('Please add a property first, then create an invitation.');
      return;
    }
    const prop = properties.find((p) => p.id === propertyId);
    if (unitId == null && propertyId && prop?.is_multi_unit && (!selectedUnitId || selectedUnitId === 0)) {
      setFormError('Please select which unit to invite the guest to.');
      return;
    }
    const guestEmailTrim = (formData.guest_email || '').trim();
    if (!guestEmailTrim) {
      setFormError('Guest email is required.');
      return;
    }
    if (!isValidInviteEmailFormat(guestEmailTrim)) {
      setFormError('Please enter a valid email address.');
      return;
    }
    if (!formData.checkin_date || !formData.checkout_date) {
      setFormError('Please select both start and end dates.');
      return;
    }
    // Compare as ISO date strings (avoid UTC midnight parsing from new Date('YYYY-MM-DD')).
    if (formData.checkout_date <= formData.checkin_date) {
      setFormError('End date must be after start date.');
      return;
    }
    const todayStr = getTodayLocal();
    if (formData.checkin_date < todayStr) {
      setFormError('Authorization start date cannot be in the past.');
      return;
    }
    if (tenantStayStartDate && formData.checkin_date < tenantStayStartDate) {
      setFormError(`Guest authorization start date cannot be before your stay starts (${tenantStayStartDate}).`);
      return;
    }
    if (tenantStayEndDate && formData.checkout_date > tenantStayEndDate) {
      setFormError(`Guest authorization end date cannot be after your stay ends (${tenantStayEndDate}).`);
      return;
    }
    setSubmitting(true);
    try {
      const isTenant = (user?.user_type ?? '').toUpperCase() === 'TENANT';
      const effectiveUnitId = unitId ?? (selectedUnitId && selectedUnitId > 0 ? selectedUnitId : undefined);
      if (isTenant && !effectiveUnitId) {
        setFormError('Could not determine your assigned unit for this invitation.');
        setSubmitting(false);
        return;
      }
      const result = isTenant
        ? await dashboardApi.tenantCreateInvitation({
            unit_id: effectiveUnitId as number,
            guest_name: formData.guest_name,
            guest_email: guestEmailTrim,
            checkin_date: formData.checkin_date,
            checkout_date: formData.checkout_date,
          })
        : await invitationsApi.create({
            owner_id: user?.user_id ?? undefined,
            property_id: unitId == null ? (propertyId ?? undefined) : undefined,
            unit_id: effectiveUnitId ?? undefined,
            guest_name: formData.guest_name,
            guest_email: guestEmailTrim,
            checkin_date: formData.checkin_date,
            checkout_date: formData.checkout_date,
          });
      if (result.status === 'success' && result.data?.invitation_code) {
        const link = buildGuestInviteUrl(result.data.invitation_code, { isDemo: Boolean(user?.is_demo) });
        linkGeneratedRef.current = true;
        setFormError(null);
        notify('success', 'Invitation link generated.');
        if (onLinkGenerated) {
          onLinkGenerated(link);
          handleClose();
        } else {
          setInviteLink(link);
          setShowLinkResult(true);
        }
      } else {
        setFormError(result.message || 'We couldn\'t create a valid invitation link. Please try again.');
      }
    } catch (err) {
      setFormError(toUserFriendlyInvitationError((err as Error)?.message ?? 'Invitation failed.'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyLink = async () => {
    const ok = await copyToClipboard(inviteLink);
    if (ok) notify('success', 'Link copied to clipboard.');
    else notify('error', 'Copy failed. Please copy the link manually.');
  };

  const handleClose = () => {
    const wasShowingLink = linkGeneratedRef.current;
    linkGeneratedRef.current = false;
    setShowLinkResult(false);
    setInviteLink('');
    onClose();
    if (wasShowingLink && onSuccess) onSuccess();
  };

  const modalTitle = propertyOrStayLabel
    ? `Invite a guest to this property`
    : 'Invite a guest';

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={modalTitle}
      className="max-w-lg"
      disableBackdropClose={submitting || showLinkResult}
    >
      <div className="p-6" key={showLinkResult ? 'link' : 'form'}>
        {propertyOrStayLabel && (
          <p className="text-sm text-slate-600 mb-4 font-medium">{propertyOrStayLabel}</p>
        )}
        {showLinkResult ? (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">Share this link with your guest. They will sign in or create an account, then sign the agreement on their dashboard.</p>
            <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 break-all">
              {inviteLink}
            </div>
            <div className="flex gap-3">
              <Button variant="outline" onClick={handleCopyLink} className="flex-1">Copy link</Button>
              <Button onClick={handleClose} className="flex-1">Done</Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5" noValidate>
            {unitId != null ? (
              <p className="text-sm text-slate-600">
                {propertyOrStayLabel ? `Inviting a guest to ${propertyOrStayLabel}.` : 'Inviting a guest to your unit.'}
              </p>
            ) : (
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Property</label>
              {propertiesLoading && properties.length === 0 ? (
                <p className="text-sm text-slate-500 py-2">Loading property…</p>
              ) : properties.length === 0 ? (
                <div className="flex items-center gap-3 p-4 rounded-xl bg-amber-50 border border-amber-200">
                  <p className="text-sm text-amber-800">Add a property first.</p>
                  <Button variant="outline" type="button" onClick={() => { handleClose(); navigate('add-property'); }} className="shrink-0">Add property</Button>
                </div>
              ) : (
                <>
                  {properties.length > 1 ? (
                    <select
                      value={propertyId ?? ''}
                      onChange={(e) => setPropertyId(Number(e.target.value))}
                      className="w-full px-4 py-2.5 bg-white border border-slate-300 rounded-lg text-slate-800 text-sm"
                    >
                      {properties.map((p) => (
                        <option key={p.id} value={p.id}>{p.name || `${p.city}, ${p.state}`}</option>
                      ))}
                    </select>
                  ) : (
                    <p className="text-sm text-slate-700 font-medium">{selectedProperty?.name || [selectedProperty?.street, selectedProperty?.city].filter(Boolean).join(', ') || 'Property'}</p>
                  )}
                  {(selectedProperty?.is_multi_unit || (unitsLoader && units.length > 0)) && (
                    <div className="mt-4">
                      <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Unit</label>
                      {unitsLoading ? (
                        <p className="text-sm text-slate-500 py-2">Loading units…</p>
                      ) : units.length > 0 ? (
                        <select
                          value={selectedUnitId ?? ''}
                          onChange={(e) => setSelectedUnitId(Number(e.target.value))}
                          className="w-full px-4 py-2.5 bg-white border border-slate-300 rounded-lg text-slate-800 text-sm"
                        >
                          {units.map((u) => (
                            <option key={u.id} value={u.id}>Unit {u.unit_label}</option>
                          ))}
                        </select>
                      ) : (
                        <p className="text-sm text-slate-500">No units found.</p>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
            )}

            <Input
              label="Guest name"
              name="guest_name"
              value={formData.guest_name}
              onChange={(e) => { setFormError(null); setFormData({ ...formData, guest_name: e.target.value }); }}
              placeholder="Full name of your guest"
            />
            <div>
              <Input
                label="Guest email (required)"
                name="guest_email"
                type="email"
                value={formData.guest_email}
                onChange={(e) => { setFormError(null); setFormData({ ...formData, guest_email: e.target.value }); }}
                placeholder="email@example.com"
                required
              />
              <p className="text-xs text-slate-500 mt-1.5">
                Only this email can sign up or sign in to accept the invitation.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <Input
                label="Start date"
                name="checkin_date"
                type="date"
                min={tenantStayStartDate ? (tenantStayStartDate > getTodayLocal() ? tenantStayStartDate : getTodayLocal()) : getTodayLocal()}
                max={tenantStayEndDate ?? undefined}
                value={formData.checkin_date}
                onChange={(e) => { setFormError(null); setFormData({ ...formData, checkin_date: e.target.value }); }}
                required
              />
              <Input
                label="End date"
                name="checkout_date"
                type="date"
                min={formData.checkin_date || getTodayLocal()}
                max={tenantStayEndDate ?? undefined}
                value={formData.checkout_date}
                onChange={(e) => { setFormError(null); setFormData({ ...formData, checkout_date: e.target.value }); }}
                required
              />
            </div>
            {unitId != null && tenantStayStartDate && (
              <p className="text-xs text-slate-500">
                Guests can only stay during your stay ({tenantStayStartDate} – {tenantStayEndDate ?? 'open-ended'}).
              </p>
            )}

            {formError && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700 font-medium">
                {formError}
              </div>
            )}

            <div className="flex gap-3 pt-2">
              <Button variant="outline" type="button" onClick={handleClose} className="flex-1" disabled={submitting}>Cancel</Button>
              <Button type="submit" className="flex-1" disabled={(unitId == null && properties.length === 0) || submitting}>
                {submitting ? 'Generating…' : 'Generate invite link'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </Modal>
  );
};
