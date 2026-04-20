import React from "react";
import { Modal } from "./UI";
import { API_URL } from "../services/api";
import { formatCalendarDate } from "../utils/dateUtils";

export interface PendingSignatureModalProps {
  open: boolean;
  onClose: () => void;
  /** Invitation code for the pending signature */
  invitationCode: string;
  /** Property name or address to display */
  propertyName: string;
  stayStartDate: string;
  stayEndDate: string;
  /** Guest email for PDF link (optional) */
  guestEmail?: string;
  /** Guest full name for PDF link (optional) */
  guestFullName?: string;
}

export default function PendingSignatureModal({
  open,
  onClose,
  invitationCode,
  propertyName,
  stayStartDate,
  stayEndDate,
  guestEmail,
  guestFullName,
}: PendingSignatureModalProps) {
  const pdfUrl = `${API_URL}/agreements/invitation/${encodeURIComponent(invitationCode.trim().toUpperCase())}/pdf${(() => {
    const params = [
      guestEmail?.trim() && `guest_email=${encodeURIComponent(guestEmail.trim())}`,
      guestFullName?.trim() && `guest_full_name=${encodeURIComponent(guestFullName.trim())}`,
    ].filter(Boolean);
    return params.length ? `?${params.join("&")}` : "";
  })()}`;

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} title="Pending actions" className="max-w-lg">
      <div className="p-6 space-y-5">
        <p className="text-slate-700">
          You need to sign the document sent via email. Your stay will not be confirmed until the agreement is signed.
        </p>

        <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 space-y-2">
          <p className="font-semibold text-slate-900">{propertyName}</p>
          <p className="text-sm text-slate-600">
            {formatCalendarDate(stayStartDate)} – {formatCalendarDate(stayEndDate)}
          </p>
          <p className="text-xs font-medium text-amber-700 mt-1">Awaiting your signature in Dropbox</p>
        </div>

        <a
          href={pdfUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block text-sm font-semibold text-blue-600 hover:text-blue-700 underline underline-offset-2"
        >
          View / Download agreement
        </a>
      </div>
    </Modal>
  );
}
