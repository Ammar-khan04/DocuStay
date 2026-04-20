import React, { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, Modal } from "./UI";
import { agreementsApi, invitationsApi, API_URL, isPropertyTenantInviteKind, type AgreementDocResponse, type InvitationDetails } from "../services/api";
import { STATE_OPTIONS } from "../services/jleService";
import { validatePhone, sanitizePhoneInput } from "../utils/validatePhone";
import { toUserFriendlyInvitationError } from "../utils/invitationErrors";
import { formatCalendarDate, formatDateTimeLocal } from "../utils/dateUtils";

// Import city data
import US_CITIES_DATA from '@/data/us-cities.json';

const US_CITIES = US_CITIES_DATA as Record<string, string[]>;

/** Form data for guest or tenant invite accept (step 1). Exported for parent to call register after sign. Password not collected in modal. */
export interface GuestInviteFormData {
  full_name: string;
  email: string;
  phone: string;
  password: string;
  confirm_password: string;
  permanent_address: string;
  permanent_city: string;
  permanent_state: string;
  permanent_zip: string;
  terms_agreed: boolean;
  privacy_agreed: boolean;
  guest_status_acknowledged: boolean;
  no_tenancy_acknowledged: boolean;
  vacate_acknowledged: boolean;
  /** True when invitation is for tenant (primary resident). Parent uses this for role when calling register. */
  isTenantInvite?: boolean;
}

/** Prefilled guest info (from DB) for read-only display in step 1. No password. */
export interface PrefilledGuestInfo {
  full_name: string;
  email: string;
  phone: string;
  permanent_address: string;
}

type AckKey = "read" | "temporary" | "vacate" | "electronic";

/** Today's date for agreement display (local timezone, same shape as elsewhere in the app). */
function todayDisplayDate(): string {
  return formatCalendarDate(new Date());
}

/**
 * Apply display-only placeholders: guest name, date, and optional IP.
 * Does not change the underlying doc content used for hashing.
 */
function contentForDisplay(
  content: string,
  guestName: string,
  ipAddress: string
): string {
  let out = content.replace(/\[Guest Name\]/g, guestName || "[Guest Name]");
  out = out.replace(/\[Tenant Name\]/g, guestName || "[Tenant Name]");
  // Fill Date line ( **Date:** ___________________ )
  out = out.replace(
    /\*\*Date:\*\*\s*_+\s*/g,
    `**Date:** ${todayDisplayDate()}\n`
  );
  if (ipAddress.trim()) {
    out = out.replace(
      /IP Address:\s*_+\s*/g,
      `IP Address: ${ipAddress.trim()}\n`
    );
  }
  return out;
}

/** Render agreement content with **bold** segments as <strong>. Preserves newlines. */
function renderAgreementContent(content: string) {
  return content.split("\n").map((line, i) => (
    <Fragment key={i}>
      {i > 0 && <br />}
      {line.split(/\*\*(.+?)\*\*/g).map((seg, j) =>
        j % 2 === 1 ? <strong key={j}>{seg}</strong> : seg
      )}
    </Fragment>
  ));
}

const INITIAL_GUEST_FORM: GuestInviteFormData = {
  full_name: "",
  email: "",
  phone: "",
  password: "",
  confirm_password: "",
  permanent_address: "",
  permanent_city: "",
  permanent_state: "",
  permanent_zip: "",
  terms_agreed: false,
  privacy_agreed: false,
  guest_status_acknowledged: false,
  no_tenancy_acknowledged: false,
  vacate_acknowledged: false,
};

export default function AgreementSignModal(props: {
  open: boolean;
  invitationCode: string;
  guestEmail: string;
  guestFullName: string;
  onClose: () => void;
  onSigned: (signatureId: number) => void;
  notify: (t: "success" | "error", m: string) => void;
  /** When provided and we get a sign_url, we call this and the parent redirects the user to Dropbox (same tab). */
  onRedirectToDropbox?: (invitationCode: string, signatureId: number, signUrl: string) => void;
  /** Invite-accept flow: show step 1 (property address + guest form + acknowledgments) before agreement/sign. */
  inviteAcceptMode?: boolean;
  /** Called when user completes step 1. For guest: parent stores form data and user proceeds to sign. For tenant: parent registers immediately (no signing). */
  onContinueToSign?: (formData: GuestInviteFormData) => void;
  /** When set (e.g. dashboard): show this info read-only from DB; no form, no password. */
  prefilledGuestInfo?: PrefilledGuestInfo | null;
}) {
  const { open, invitationCode, guestEmail, guestFullName, onClose, onSigned, notify, onRedirectToDropbox, inviteAcceptMode, onContinueToSign, prefilledGuestInfo } = props;
  const normalizedCode = invitationCode.trim().toUpperCase();

  const notifyRef = useRef(notify);
  const onSignedRef = useRef(onSigned);
  notifyRef.current = notify;
  onSignedRef.current = onSigned;

  const [doc, setDoc] = useState<AgreementDocResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);
  const [typedSignature, setTypedSignature] = useState(guestFullName || "");
  const [ipAddress, setIpAddress] = useState("");
  const [acks, setAcks] = useState<Record<AckKey, boolean>>({
    read: false,
    temporary: false,
    vacate: false,
    electronic: false,
  });
  const [signError, setSignError] = useState<string | null>(null);
  /** After Sign with Dropbox: we wait for user to complete in Dropbox; modal stays open and we poll. */
  const [pendingDropboxSignatureId, setPendingDropboxSignatureId] = useState<number | null>(null);
  const [pendingSignUrl, setPendingSignUrl] = useState<string | null>(null);

  /** Invite-accept mode: step 1 = details form, step 2 = agreement + sign */
  const [inviteStep, setInviteStep] = useState<"details" | "sign">("details");
  const [inviteDetails, setInviteDetails] = useState<InvitationDetails | null>(null);
  const [inviteDetailsLoading, setInviteDetailsLoading] = useState(false);
  const [step1FormData, setStep1FormData] = useState<GuestInviteFormData>(INITIAL_GUEST_FORM);
  const [step1Error, setStep1Error] = useState<string | null>(null);

  // Derive city options based on selected state
  const cityOptions = useMemo(() => {
    if (!step1FormData.permanent_state) return [];
    const cities = US_CITIES[step1FormData.permanent_state] || [];
    return cities.map(city => ({ value: city, label: city }));
  }, [step1FormData.permanent_state]);

  /** Track which invite we opened so we only reset to step 1 when modal opens or code changes, not on every re-render (avoids Dropbox error loop). */
  const lastInviteDetailsKeyRef = useRef<string | null>(null);
  /** Once user has gone to step "sign", don't reset to "details" until modal closes (avoids reverting to Accept invitation after Sign with Dropbox error). */
  const hasReachedSignStepRef = useRef(false);

  const isTenantInvite =
    isPropertyTenantInviteKind(inviteDetails?.invitation_kind) || Boolean(inviteDetails?.is_tenant_invite) || doc?.title === "Tenant Invitation Acceptance";
  const allAcks = useMemo(
    () =>
      isTenantInvite
        ? acks.read && acks.electronic
        : Object.values(acks).every(Boolean),
    [acks, isTenantInvite]
  );

  /** Effective guest email/name: from step 1 form or prefilled when in invite mode step 2, else from props */
  const effectiveGuestEmail =
    inviteAcceptMode && inviteStep === "sign"
      ? (prefilledGuestInfo?.email ?? step1FormData.email ?? "").trim()
      : (guestEmail ?? "").trim();
  const effectiveGuestFullName =
    inviteAcceptMode && inviteStep === "sign"
      ? (prefilledGuestInfo?.full_name ?? step1FormData.full_name ?? "").trim()
      : (guestFullName ?? "").trim();

  const signatureIdToPoll =
    pendingDropboxSignatureId ??
    (doc?.already_signed && doc?.signature_id != null && !doc?.has_dropbox_signed_pdf ? doc.signature_id ?? null : null);

  useEffect(() => {
    if (!open || signatureIdToPoll == null) return;
    const id = signatureIdToPoll;
    const t = setInterval(() => {
      agreementsApi.getSignatureStatus(id).then((res) => {
        if (res.completed) {
          setPendingDropboxSignatureId(null);
          setPendingSignUrl(null);
          onSignedRef.current(id);
          onClose();
        }
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [open, signatureIdToPoll]);

  // When the agreement is already fully signed via Dropbox (PDF available) and we are in
  // inviteAcceptMode, auto-trigger onSigned so the invite gets accepted without re-signing.
  useEffect(() => {
    if (
      open &&
      inviteAcceptMode &&
      doc?.already_signed &&
      doc?.has_dropbox_signed_pdf &&
      doc?.signature_id != null
    ) {
      onSignedRef.current(doc.signature_id);
      onClose();
    }
  }, [open, inviteAcceptMode, doc?.already_signed, doc?.has_dropbox_signed_pdf, doc?.signature_id, onClose]);

  /** Fetch invite details when in invite-accept mode step 1. Only reset to step 1 when modal opens or code changes (not on every re-render) to avoid reverting to "Accept invitation" after e.g. Sign with Dropbox error. */
  useEffect(() => {
    if (!open || !inviteAcceptMode || !normalizedCode) {
      if (!open) {
        lastInviteDetailsKeyRef.current = null;
        hasReachedSignStepRef.current = false;
      }
      return;
    }
    const key = `${normalizedCode}`;
    if (lastInviteDetailsKeyRef.current === key) return;
    if (hasReachedSignStepRef.current) return;
    lastInviteDetailsKeyRef.current = key;
    setInviteStep("details");
    setStep1FormData(INITIAL_GUEST_FORM);
    setInviteDetails(null);
    setInviteDetailsLoading(true);
    invitationsApi
      .getDetails(normalizedCode)
      .then((d) => setInviteDetails(d))
      .catch(() => setInviteDetails({ valid: false }))
      .finally(() => setInviteDetailsLoading(false));
  }, [open, inviteAcceptMode, normalizedCode]);

  useEffect(() => {
    if (!open) return;
    setTypedSignature(guestFullName || "");
    setIpAddress("");
    setAcks({ read: false, temporary: false, vacate: false, electronic: false });
    setLoadError(null);
    setSignError(null);
    setStep1Error(null);

    if (!normalizedCode) return;
    if (inviteAcceptMode && inviteStep !== "sign") return;
    const email =
      inviteAcceptMode && inviteStep === "sign"
        ? (prefilledGuestInfo?.email ?? step1FormData.email ?? "").trim()
        : (guestEmail ?? "").trim();
    const name =
      inviteAcceptMode && inviteStep === "sign"
        ? (prefilledGuestInfo?.full_name ?? step1FormData.full_name ?? "").trim()
        : (guestFullName ?? "").trim();
    if (!email && !name) return;

    setLoading(true);
    setDoc(null);
    setPendingDropboxSignatureId(null);
    setPendingSignUrl(null);
    agreementsApi
      .getInvitationAgreement(normalizedCode, email || undefined, name || undefined)
      .then((d) => {
        setDoc(d);
        setLoadError(null);
        // Do NOT auto-call onSigned here: stay must only be created when the user completes the sign flow in this session (in-app sign or return from Dropbox). Auto-calling caused stays to be created and token burned despite the user seeing an error (e.g. stale Dropbox redirect state).
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? "";
        const userMsg = toUserFriendlyInvitationError(msg) || "Could not load agreement.";
        setLoadError(userMsg);
        setDoc(null);
        notifyRef.current("error", userMsg);
      })
      .finally(() => setLoading(false));
  }, [open, normalizedCode, guestFullName, guestEmail, inviteAcceptMode, inviteStep, step1FormData.email, step1FormData.full_name, prefilledGuestInfo?.email, prefilledGuestInfo?.full_name]);

  const handleStep1Continue = (e?: React.MouseEvent) => {
    e?.preventDefault();
    e?.stopPropagation();
    setStep1Error(null);
    if (prefilledGuestInfo) {
      const d = step1FormData;
      if (!d.terms_agreed || !d.privacy_agreed) {
        setStep1Error("Please agree to the Terms of Service and Privacy Policy to continue.");
        notify("error", "Please agree to the Terms of Service and Privacy Policy to continue.");
        return;
      }
      hasReachedSignStepRef.current = true;
      setInviteStep("sign");
      return;
    }
    const d = step1FormData;
    const isTenant = isPropertyTenantInviteKind(inviteDetails?.invitation_kind) || inviteDetails?.is_tenant_invite;
    const addressFilled =
      d.permanent_address.trim() &&
      d.permanent_city.trim() &&
      d.permanent_state.trim() &&
      d.permanent_zip.trim();
    const requiredFilled =
      d.full_name.trim() &&
      d.email.trim() &&
      d.phone.trim() &&
      (isTenant ? true : addressFilled);
    if (!requiredFilled || !d.terms_agreed || !d.privacy_agreed) {
      const msg = "Please fill in all required fields and agree to the Terms of Service and Privacy Policy.";
      setStep1Error(msg);
      notify("error", msg);
      return;
    }
    const phoneCheck = validatePhone(d.phone);
    if (!phoneCheck.valid) {
      setStep1Error(phoneCheck.error ?? "Invalid phone number.");
      notify("error", phoneCheck.error ?? "Invalid phone number.");
      return;
    }
    const formDataWithRole = { ...step1FormData, isTenantInvite: isTenant };
    onContinueToSign?.(formDataWithRole);
    if (isTenant) {
      // Tenant does not sign. Parent registers immediately and closes modal.
      return;
    }
    hasReachedSignStepRef.current = true;
    setInviteStep("sign");
  };

  const handleSign = async () => {
    setSignError(null);
    if (!normalizedCode) {
      notify("error", "Invitation code is missing.");
      return;
    }
    const email = effectiveGuestEmail || guestEmail?.trim();
    const name = effectiveGuestFullName || guestFullName?.trim();
    if (!email) {
      notify("error", "Enter your email first.");
      return;
    }
    if (!typedSignature?.trim()) {
      notify("error", "Type your full name to sign.");
      return;
    }
    if (!doc) {
      notify("error", "Agreement is not loaded yet.");
      return;
    }
    if (!allAcks) {
      const msg = isTenantInvite
        ? "Please check all required acknowledgments above before signing."
        : "Please check all four acknowledgments above before signing.";
      setSignError(msg);
      notify("error", msg);
      return;
    }

    setSigning(true);
    try {
      const signAcks = isTenantInvite
        ? { ...acks, temporary: true, vacate: true }
        : acks;
      const res = await agreementsApi.signInvitationAgreementWithDropbox({
        invitation_code: normalizedCode,
        guest_email: email,
        guest_full_name: name || typedSignature.trim(),
        typed_signature: typedSignature.trim(),
        acks: signAcks,
        document_hash: doc.document_hash,
        ip_address: ipAddress.trim() || undefined,
        is_tenant_invite: isTenantInvite,
      });
      if (res.sign_url && onRedirectToDropbox) {
        onRedirectToDropbox(normalizedCode, res.signature_id, res.sign_url);
        return;
      }
      if (res.sign_url && res.signature_id != null) {
        setPendingDropboxSignatureId(res.signature_id);
        setPendingSignUrl(res.sign_url);
        window.open(res.sign_url, "_blank", "noopener");
        notify("success", "Complete signing in the new tab. This will close automatically when you're done.");
      } else if (res.signature_id != null) {
        // Dropbox will send a signing link by email — keep polling so we can auto-accept once complete.
        setPendingDropboxSignatureId(res.signature_id);
        setPendingSignUrl(null);
        notify("success", "Agreement sent to Dropbox Sign. Check your email to complete signing. This will update automatically when done.");
      } else {
        notify("success", "Agreement sent. Check your email to complete signing.");
        onClose();
      }
    } catch (e) {
      const msg = (e as Error)?.message || "Could not sign agreement.";
      if (msg.toLowerCase().includes("check your email")) {
        notify("success", msg);
        onClose();
        return;
      }
      setSignError(msg);
      notify("error", msg);
    } finally {
      setSigning(false);
    }
  };

  const shortTitle = doc?.title?.includes("(") ? doc.title.slice(0, doc.title.indexOf("(")).trim() || doc.title : (doc?.title || "Review & Sign Agreement");
  const modalTitle = inviteAcceptMode && inviteStep === "details" ? "Accept invitation" : shortTitle;

  /** Step 1: Property address + guest form + acknowledgments (invite-accept only) */
  const renderStep1 = () => {
    if (inviteDetailsLoading) {
      return (
        <div className="p-6 md:p-8 text-center text-slate-600">
          Loading invitation…
        </div>
      );
    }
    if (inviteDetails && !inviteDetails.valid) {
      return (
        <div className="p-6 md:p-8 text-center">
          <p className="text-slate-600 mb-4">
            {inviteDetails.expired ? "This invitation has expired." : inviteDetails.used ? "This invitation has already been used." : "This invitation could not be loaded."}
          </p>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </div>
      );
    }
    const d = step1FormData;
    const isReadOnly = !!prefilledGuestInfo;
    return (
      <form
        className="p-6 md:p-8 space-y-6 bg-slate-50/50 max-h-[85vh] overflow-y-auto"
        onSubmit={(e) => { e.preventDefault(); e.stopPropagation(); }}
        noValidate
      >
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">Property (reference only)</p>
          <p className="text-slate-800 font-medium">{inviteDetails?.property_address || inviteDetails?.property_name || "—"}</p>
          {inviteDetails?.stay_start_date && inviteDetails?.stay_end_date && (
            <p className="text-sm text-slate-500 mt-1">
              {formatCalendarDate(inviteDetails.stay_start_date)} – {formatCalendarDate(inviteDetails.stay_end_date)}
            </p>
          )}
        </div>

        {isReadOnly ? (
          <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-3">
            <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Your information (from your account)</p>
            <p className="text-slate-800"><span className="text-slate-500 text-sm">Full name</span> {prefilledGuestInfo.full_name}</p>
            <p className="text-slate-800"><span className="text-slate-500 text-sm">Email</span> {prefilledGuestInfo.email}</p>
            <p className="text-slate-800"><span className="text-slate-500 text-sm">Phone</span> {prefilledGuestInfo.phone || "—"}</p>
            <p className="text-slate-800"><span className="text-slate-500 text-sm">Permanent residence</span> {prefilledGuestInfo.permanent_address}</p>
          </div>
        ) : (
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Your information</p>
              <Input label="Full name" value={d.full_name} onChange={(e) => setStep1FormData({ ...d, full_name: e.target.value })} required />
              <Input label="Email" type="email" value={d.email} onChange={(e) => setStep1FormData({ ...d, email: e.target.value })} required />
              <Input label="Phone" value={d.phone} onChange={(e) => setStep1FormData({ ...d, phone: sanitizePhoneInput(e.target.value) })} placeholder="+15551234567 or 5551234567" required />
            </div>
            {!(isPropertyTenantInviteKind(inviteDetails?.invitation_kind) || inviteDetails?.is_tenant_invite) && (
            <div className="space-y-4">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Permanent residence</p>
              <Input label="Street address" value={d.permanent_address} onChange={(e) => setStep1FormData({ ...d, permanent_address: e.target.value })} required />
              <div className="grid grid-cols-2 gap-3">
                <Input
                  label="State" name="permanent_state" value={d.permanent_state}
                  onChange={(e) => {
                    const newState = e.target.value;
                    setStep1FormData({
                      ...d,
                      permanent_state: newState,
                      permanent_city: '' // Reset city when state changes
                    });
                  }}
                  options={STATE_OPTIONS}
                  required
                />
                <Input
                  label="City" value={d.permanent_city}
                  onChange={(e) => setStep1FormData({ ...d, permanent_city: e.target.value })}
                  placeholder={d.permanent_state ? "Select City" : "Select State first"}
                  options={cityOptions}
                  disabled={!d.permanent_state}
                  required
                />
              </div>
              <Input label="ZIP" value={d.permanent_zip} onChange={(e) => setStep1FormData({ ...d, permanent_zip: e.target.value })} required />
            </div>
            )}
          </div>
        )}

        <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-3">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Agreements</p>
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={d.terms_agreed}
              onChange={(e) => setStep1FormData({ ...d, terms_agreed: e.target.checked })}
              className="mt-0.5 w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500 shrink-0"
            />
            <span className="text-sm text-slate-700">I agree to the <a href="#terms" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-medium hover:underline" onClick={(e) => e.stopPropagation()}>Terms of Service</a>.</span>
          </label>
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={d.privacy_agreed}
              onChange={(e) => setStep1FormData({ ...d, privacy_agreed: e.target.checked })}
              className="mt-0.5 w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500 shrink-0"
            />
            <span className="text-sm text-slate-700">I agree to the <a href="#privacy" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-medium hover:underline" onClick={(e) => e.stopPropagation()}>Privacy Policy</a>.</span>
          </label>
        </div>

        {step1Error && <p className="text-sm text-red-600 font-medium" role="alert">{step1Error}</p>}
        <div className="flex gap-3">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="button" onClick={(e) => handleStep1Continue(e)}>
            {isPropertyTenantInviteKind(inviteDetails?.invitation_kind) || inviteDetails?.is_tenant_invite
              ? "Accept invitation & Create account"
              : "Continue to review & sign"}
          </Button>
        </div>
      </form>
    );
  };

  return (
    <Modal open={open} onClose={onClose} title={modalTitle} className="max-w-5xl">
      {inviteAcceptMode && inviteStep === "details" ? (
        renderStep1()
      ) : (
      <div className="p-6 md:p-8 space-y-6 bg-slate-50/50">
        {/* Meta row */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm text-slate-600">
              Invitation: <span className="font-semibold text-slate-800">{normalizedCode}</span>
              {doc?.region_code ? (
                <> · Region: <span className="font-semibold text-slate-800">{doc.region_code}</span></>
              ) : null}
            </p>
            <p className="text-xs text-slate-500 italic">DocuStay is a documentation platform, not a law firm.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {doc?.document_id ? (
              <span className="text-xs text-slate-500 font-mono">{doc.document_id}</span>
            ) : null}
            {doc && !loading && (
              <a
                href={`${API_URL}/agreements/invitation/${encodeURIComponent(normalizedCode)}/pdf${(() => {
                  const params = [
                    (effectiveGuestEmail || guestEmail?.trim()) && `guest_email=${encodeURIComponent((effectiveGuestEmail || guestEmail?.trim() || ""))}`,
                    (effectiveGuestFullName || guestFullName || typedSignature)?.trim() && `guest_full_name=${encodeURIComponent((effectiveGuestFullName || guestFullName || typedSignature || "").trim())}`,
                  ].filter(Boolean);
                  return params.length ? `?${params.join("&")}` : "";
                })()}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 underline underline-offset-2"
              >
                View / Download PDF
              </a>
            )}
          </div>
        </div>

        {doc?.already_signed && doc?.has_dropbox_signed_pdf && (
          <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-emerald-700 font-bold">✓ Signed</span>
            <span className="text-slate-600 text-sm">
              {doc.signed_by} on {doc.signed_at ? formatDateTimeLocal(doc.signed_at) : ""}
            </span>
            {doc.signature_id != null && (
              <a
                href={`${API_URL}/agreements/signature/${doc.signature_id}/signed-pdf`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 underline underline-offset-2"
              >
                Download signed PDF (Dropbox Sign)
              </a>
            )}
          </div>
        )}
        {doc?.already_signed && !doc?.has_dropbox_signed_pdf && (
          <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-amber-800 font-bold">Awaiting your signature in Dropbox</span>
            <span className="text-slate-600 text-sm">
              Complete signing in the link we sent you by email, or use the button below when you open this from the same session.
            </span>
          </div>
        )}

        <div className="grid lg:grid-cols-5 gap-6">
          {/* Agreement content – readable document area */}
          <div className="lg:col-span-3">
            <div className="border border-slate-200 rounded-xl bg-white overflow-hidden shadow-sm flex flex-col max-h-[70vh]">
              <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-2 shrink-0">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Agreement</p>
                {doc?.property_address ? (
                  <p className="text-xs text-slate-500 truncate max-w-[60%]" title={doc.property_address}>
                    {doc.property_address}
                  </p>
                ) : null}
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <div className="px-6 py-5 max-w-prose mx-auto">
                  <div className="text-base text-slate-800 leading-loose tracking-normal selection:bg-blue-100">
                    {loading
                      ? "Loading agreement…"
                      : loadError
                        ? loadError
                        : doc?.content
                          ? renderAgreementContent(
                              contentForDisplay(
                                doc.content,
                                effectiveGuestFullName || guestFullName || typedSignature || "[Guest Name]",
                                ipAddress
                              )
                            )
                          : "Agreement unavailable."}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Acknowledgments + Signature */}
          <div className="lg:col-span-2 space-y-4">
            <div className="border border-slate-200 rounded-xl bg-white p-5 space-y-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Acknowledgments</p>
              {(
                isTenantInvite
                  ? [
                      ["read", "I have read the entire agreement"],
                      ["electronic", "I consent to electronic signature"],
                    ]
                  : [
                      ["read", "I have read the entire agreement"],
                      ["temporary", "I acknowledge my stay is temporary"],
                      ["vacate", "I agree to vacate by the checkout date"],
                      ["electronic", "I consent to electronic signature"],
                    ]
              ).map(([key, label]) => (
                <label key={key} className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acks[key]}
                    onChange={(e) => {
                      setAcks((p) => ({ ...p, [key]: e.target.checked }));
                      setSignError(null);
                    }}
                    className="mt-0.5 w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0"
                  />
                  <span className="text-sm text-slate-700">{label}</span>
                </label>
              ))}
            </div>

            <div className="border border-slate-200 rounded-xl bg-white p-5 space-y-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Signature</p>
              {doc?.already_signed && doc?.has_dropbox_signed_pdf ? (
                <p className="text-sm text-slate-600">This agreement is already signed. You can close this window.</p>
              ) : signatureIdToPoll != null ? (
                <div className="space-y-3">
                  <p className="text-sm font-medium text-slate-700">
                    Complete signing in Dropbox. This modal will close automatically when we detect your signature.
                  </p>
                  {pendingSignUrl && (
                    <Button
                      variant="outline"
                      onClick={() => window.open(pendingSignUrl!, "_blank", "noopener")}
                      className="w-full py-3"
                    >
                      Open Dropbox to sign
                    </Button>
                  )}
                  <p className="text-xs text-slate-500">You can close this modal; your stay will stay in pending actions until signing is complete.</p>
                </div>
              ) : (
                <>
                  <Input
                    label="Type full name *"
                    name="typed_signature"
                    value={typedSignature}
                    onChange={(e) => setTypedSignature(e.target.value)}
                    placeholder="First Last"
                    required
                  />
                  <Input
                    label="IP Address (optional)"
                    name="ip_address"
                    value={ipAddress}
                    onChange={(e) => setIpAddress(e.target.value)}
                    placeholder="e.g. 192.168.1.1"
                  />
                  {signError && (
                    <p className="text-sm text-red-600 font-medium" role="alert">
                      {signError}
                    </p>
                  )}
                  <p className="text-xs text-slate-500 uppercase tracking-wide font-semibold">
                    By signing, you agree to the terms of this agreement.
                  </p>
                  <div className="flex flex-col gap-3 pt-1">
                    <div className="flex gap-3">
                      <Button variant="outline" onClick={onClose} className="flex-1 py-3">
                        Cancel
                      </Button>
                      <Button
                        type="button"
                        onClick={handleSign}
                        disabled={signing || loading || !allAcks}
                        className="flex-1 py-3"
                        title={!allAcks ? "Check all acknowledgments above to enable signing" : undefined}
                      >
                        {signing ? "Sending…" : "Sign with Dropbox Sign"}
                      </Button>
                    </div>
                    <p className="text-xs text-slate-500 leading-relaxed">
                      You will receive an email from Dropbox Sign with a link to sign. After signing there, you can download the signed PDF here.
                    </p>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
      )}
    </Modal>
  );
}
