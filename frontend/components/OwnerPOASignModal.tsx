import React, { Fragment, useEffect, useMemo, useState } from "react";
import { Button, Input, Modal } from "./UI";
import { ownerPoaApi, type OwnerPOADocResponse } from "../services/api";
import { getOwnerSignupErrorFriendly } from "../utils/ownerSignupErrors";
import { formatDateTimeLocal } from "../utils/dateUtils";

type AckKey = "read" | "temporary" | "vacate" | "electronic";

/** Default/fallback POA content when API returns none. */
const DUMMY_POA_CONTENT = `**Limited Power of Attorney and Agent Authorization**
This Limited Power of Attorney and Agent Authorization ("Authorization") is made effective as of the date of electronic signature below.

**1. Parties**
• The Principal: [User's Full Legal Name or Entity Name]
[User's Full Address]
(Hereinafter "Principal")
• The Agent: DOCUSTAY LLC, a Washington limited liability company
950 South Ash St, Apt 303, Spokane, WA 99204
(Hereinafter "Agent" or "DocuStay")

**2. Recitals**
WHEREAS, Principal owns or is the duly authorized property manager for the real properties listed in the Principal's DocuStay account (the "Properties"); and
WHEREAS, Principal desires to appoint Agent for the sole and limited purpose of acting as Principal's attorney-in-fact to create, maintain, and present documentation related to the occupancy and status of the Properties.

**3. Grant of Limited Power of Attorney**
Principal hereby appoints Agent as Principal's true and lawful attorney-in-fact, to act in Principal's name, place, and stead for the limited purposes and with the limited powers set forth in this Authorization.

**4. Enumerated Limited Powers**
Generate occupancy documentation; maintain status ledger; assemble documentation packages; and act as third-party record keeper.

**5. Limitations on Authority**
DocuStay has no authority to lease/sell property, manage funds, conduct legal actions, bind unrelated financial obligations, or act as broker/legal representative.

**6. Term and Revocation**
Effective on electronic execution; remains active until revoked by written notice via platform or email to michael@docustay.online.

**7. Durability**
This is a durable Power of Attorney and does not terminate upon incapacity.

**8. Governing Law**
State of Washington.

**9. Indemnification and Limitation of Liability**
Principal indemnifies Agent for good-faith performance; liability is limited as stated in the Authorization.

**10. Acknowledgment and Signature**
By signing, Principal confirms authority to grant this Authorization and agrees electronic signature is legally equivalent to a manual signature.

PRINCIPAL:
Signature: [Electronic Signature]
Printed Name: [User's Full Legal Name]
Title: Owner
Date: [Date of Signature]`;

/** Render one line: **bold** as <strong>, and entire-line **...** as heading. */
function renderLine(line: string, lineIndex: number, isFirstLine: boolean) {
  const trimmed = line.trim();
  const wholeLineBold = /^\*\*(.+)\*\*\s*$/.exec(trimmed);
  if (wholeLineBold) {
    const inner = wholeLineBold[1];
    return (
      <div
        key={lineIndex}
        className={`font-semibold text-slate-900 ${isFirstLine ? "mt-0" : "mt-4"} text-base`}
      >
        {inner}
      </div>
    );
  }
  const parts = trimmed.split(/\*\*(.+?)\*\*/g);
  if (parts.length === 1) return <Fragment key={lineIndex}>{trimmed || "\u00A0"}</Fragment>;
  return (
    <span key={lineIndex}>
      {parts.map((seg, j) =>
        j % 2 === 1 ? <strong key={j} className="font-semibold text-slate-900">{seg}</strong> : seg
      )}
    </span>
  );
}

/** Render document content with headings and **bold**. Normalizes line endings. */
function renderDocContent(content: string) {
  const normalized = (content || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          {renderLine(line, i, i === 0)}
        </Fragment>
      ))}
    </div>
  );
}

export default function OwnerPOASignModal(props: {
  open: boolean;
  ownerEmail: string;
  ownerFullName: string;
  ownerCity?: string | null;
  ownerState?: string | null;
  ownerCountry?: string | null;
  principalTitle?: string | null;
  onClose: () => void;
  onSigned: (signatureId: number) => void;
  notify: (t: "success" | "error", m: string) => void;
  /** When provided, called whenever we have a signature id (from doc load or after Sign with Dropbox) so parent can enable "Complete Verification". */
  onSignatureIdKnown?: (signatureId: number) => void;
}) {
  const { open, ownerEmail, ownerFullName, ownerCity, ownerState, ownerCountry, principalTitle, onClose, onSigned, notify, onSignatureIdKnown } = props;

  const [doc, setDoc] = useState<OwnerPOADocResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [signing, setSigning] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [signError, setSignError] = useState<string | null>(null);
  const [typedSignature, setTypedSignature] = useState(ownerFullName || "");
  const [acks, setAcks] = useState<Record<AckKey, boolean>>({
    read: false,
    temporary: false,
    vacate: false,
    electronic: false,
  });

  const allAcks = useMemo(() => Object.values(acks).every(Boolean), [acks]);

  useEffect(() => {
    if (!open) return;
    setTypedSignature(ownerFullName || "");
    setAcks({ read: false, temporary: false, vacate: false, electronic: false });
    setLoadError(null);
    setSignError(null);

    setLoading(true);
    ownerPoaApi
      .getDocument(ownerEmail?.trim() || undefined, ownerFullName?.trim() || undefined, { city: ownerCity, state: ownerState, country: ownerCountry }, principalTitle)
      .then((d) => {
        setDoc(d);
        setLoadError(null);
        if (d?.signature_id != null) onSignatureIdKnown?.(d.signature_id);
      })
      .catch((e) => {
        const friendly = getOwnerSignupErrorFriendly((e as Error)?.message ?? "Could not load Master POA document.");
        setLoadError(friendly.message);
        notify("error", friendly.message);
      })
      .finally(() => setLoading(false));
  }, [open, ownerEmail, ownerFullName, ownerCity, ownerState, ownerCountry, principalTitle, notify]);

  const handleSign = async () => {
    setSignError(null);
    if (!ownerEmail?.trim()) {
      const msg = "Enter your email first.";
      notify("error", msg);
      return;
    }
    if (!typedSignature?.trim()) {
      const msg = "Type your full name to sign.";
      notify("error", msg);
      return;
    }
    if (!doc) {
      const msg = "Document is not loaded yet. Please wait or try again.";
      notify("error", msg);
      return;
    }
    if (!allAcks) {
      const msg = "Please acknowledge all items to proceed.";
      notify("error", msg);
      return;
    }

    setSigning(true);
    try {
      const res = await ownerPoaApi.signWithDropbox({
        owner_email: ownerEmail.trim(),
        owner_full_name: ownerFullName?.trim() || typedSignature.trim(),
        typed_signature: typedSignature.trim(),
        acks,
        document_hash: doc.document_hash,
        owner_city: ownerCity || undefined,
        owner_state: ownerState || undefined,
        owner_country: ownerCountry || undefined,
        principal_title: principalTitle || undefined,
      });
      onSignatureIdKnown?.(res.signature_id);
      if (res.sign_url) {
        window.open(res.sign_url, "_blank", "noopener");
        notify("success", "We've opened Dropbox Sign in a new tab. Complete signing there, then return here and click Complete Verification below.");
      } else {
        notify("success", "Master POA sent to Dropbox Sign. Check your email to complete signing, then return here and click Complete Verification below.");
      }
      onClose();
    } catch (e) {
      const friendly = getOwnerSignupErrorFriendly((e as Error)?.message ?? "Could not sign Master POA.");
      setSignError(friendly.message);
      notify("error", friendly.message);
    } finally {
      setSigning(false);
    }
  };

  const shortTitle = doc?.title ?? "Authorization document";

  return (
    <Modal open={open} onClose={onClose} title={shortTitle} className="max-w-5xl">
      <div className="p-6 md:p-8 space-y-6 bg-slate-50/50">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm text-slate-600">
              One-time, account-level document signed during onboarding. Establishes DocuStay as your Authorized Agent for all property protection activities.
            </p>
            <p className="text-xs text-slate-500 italic">DocuStay is a documentation platform, not a law firm.</p>
          </div>
          {doc?.document_id ? (
            <span className="text-xs text-slate-500 font-mono">{doc.document_id}</span>
          ) : null}
        </div>

        {doc?.already_signed && doc?.has_dropbox_signed_pdf && (
          <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-emerald-700 font-bold">✓ Signed</span>
            <span className="text-slate-600 text-sm">
              {doc.signed_by} on {doc.signed_at ? formatDateTimeLocal(doc.signed_at) : ""}
            </span>
            <Button
              onClick={() => doc?.signature_id != null && onSigned(doc.signature_id)}
              disabled={doc?.signature_id == null}
            >
              Use this signature and complete signup
            </Button>
          </div>
        )}
        {doc?.already_signed && !doc?.has_dropbox_signed_pdf && (
          <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-amber-800 font-bold">Awaiting your signature in Dropbox</span>
            <span className="text-slate-600 text-sm">
              Complete signing in the link we sent you (email or the tab we opened). Then close this and click <strong>Complete Verification</strong> below.
            </span>
          </div>
        )}

        {loadError && (
          <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm" role="alert">
            {loadError}
          </div>
        )}
        {signError && (
          <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm" role="alert">
            {signError}
          </div>
        )}
        <div className="grid lg:grid-cols-5 gap-6">
          {/* Document content – same layout as guest agreement */}
          <div className="lg:col-span-3">
            <div className="border border-slate-200 rounded-xl bg-white overflow-hidden shadow-sm flex flex-col max-h-[70vh]">
              <div className="px-4 py-3 border-b border-slate-200 shrink-0">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Master POA — Documentation &amp; records</p>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <div className="px-6 py-5 max-w-prose mx-auto">
                  <div className="text-base text-slate-800 leading-loose tracking-normal selection:bg-blue-100">
                    {loading
                      ? "Loading document…"
                      : renderDocContent(doc?.content ?? DUMMY_POA_CONTENT)}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="lg:col-span-2 space-y-4">
            <div className="border border-slate-200 rounded-xl bg-white p-5 space-y-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Acknowledgments</p>
              {(
                [
                  ["read", "I have read the entire document"],
                  ["temporary", "I acknowledge this is a one-time account-level authorization"],
                  ["vacate", "I understand this covers all properties I add now and in the future"],
                  ["electronic", "I consent to electronic signature"],
                ] as Array<[AckKey, string]>
              ).map(([key, label]) => (
                <label key={key} className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acks[key]}
                    onChange={(e) => setAcks((p) => ({ ...p, [key]: e.target.checked }))}
                    className="mt-0.5 w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0"
                  />
                  <span className="text-sm text-slate-700">{label}</span>
                </label>
              ))}
            </div>

            <div className="border border-slate-200 rounded-xl bg-white p-5 space-y-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Signature</p>
              {doc?.already_signed && doc?.has_dropbox_signed_pdf ? (
                <p className="text-sm text-slate-600">This document is signed. Use the button above to complete signup, or close and click Complete Verification below.</p>
              ) : doc?.already_signed ? (
                <p className="text-sm text-slate-600">Complete signing in Dropbox, then close this and click Complete Verification on the page.</p>
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
                  <p className="text-xs text-slate-500 uppercase tracking-wide font-semibold">
                    By signing, you agree to the terms of this document.
                  </p>
                  <div className="flex flex-col gap-3 pt-1">
                    <div className="flex gap-3">
                      <Button variant="outline" onClick={onClose} className="flex-1 py-3">
                        Cancel
                      </Button>
                      <Button
                        onClick={handleSign}
                        disabled={signing || loading || !allAcks}
                        className="flex-1 py-3"
                        title={!allAcks ? "Check all acknowledgments above to enable signing" : undefined}
                      >
                        {signing ? "Sending…" : "Sign with Dropbox Sign"}
                      </Button>
                    </div>
                    <p className="text-xs text-slate-500 leading-relaxed">
                      You will receive an email from Dropbox Sign with a link to sign. After signing there, you can download the signed PDF in Settings.
                    </p>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}
