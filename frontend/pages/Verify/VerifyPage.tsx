import React, { useState, useEffect } from 'react';
import { publicApi, resolveBackendMediaUrl, type VerifyResponse } from '../../services/api';
import { validatePhone, sanitizePhoneInput } from '../../utils/validatePhone';
import { formatCalendarDate, formatDateTimeLocal } from '../../utils/dateUtils';

const APP_ORIGIN = typeof window !== 'undefined' ? window.location.origin : '';

function hasRecord(result: VerifyResponse): boolean {
  return !!(result.property_name || result.property_address);
}

const STATUS_COLORS: Record<string, string> = {
  ACTIVE: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
  PENDING: 'bg-amber-50 text-amber-700 border border-amber-200',
  REVOKED: 'bg-red-50 text-red-700 border border-red-200',
  EXPIRED: 'bg-slate-100 text-slate-600 border border-slate-200',
  COMPLETED: 'bg-blue-50 text-blue-700 border border-blue-200',
  CANCELLED: 'bg-slate-100 text-slate-600 border border-slate-200',
};

export const VerifyPage: React.FC = () => {
  const [tokenId, setTokenId] = useState('');
  const [propertyAddress, setPropertyAddress] = useState('');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<VerifyResponse | null>(null);
  const [showLedger, setShowLedger] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const hash = window.location.hash || '';
    const fromHash = new URLSearchParams(hash.split('?')[1] || '');
    const fromSearch = new URLSearchParams(window.location.search || '');
    const token = (fromHash.get('token') || fromHash.get('token_id') || fromSearch.get('token') || fromSearch.get('token_id') || '').trim();
    const addressRaw =
      fromHash.get('address') ||
      fromHash.get('property_address') ||
      fromSearch.get('address') ||
      fromSearch.get('property_address') ||
      '';
    const address = addressRaw ? decodeURIComponent(addressRaw.replace(/\+/g, ' ')) : '';
    if (token) setTokenId(token);
    if (address) setPropertyAddress(address);

    // Opened from guest/tenant dashboard QR or shared link: show verification result immediately.
    if (!token) return;
    let cancelled = false;
    setSubmitting(true);
    setError(null);
    setResult(null);
    setShowLedger(false);
    publicApi
      .verify({
        token_id: token,
        property_address: address.trim() || undefined,
      })
      .then((res) => {
        if (!cancelled) setResult(res);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error)?.message ?? 'Verification failed.');
      })
      .finally(() => {
        if (!cancelled) setSubmitting(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setShowLedger(false);
    if (!(tokenId ?? '').trim()) { setError('Token ID is required.'); return; }
    const phoneVal = (phone ?? '').trim();
    if (phoneVal) {
      const phoneCheck = validatePhone(phoneVal);
      if (!phoneCheck.valid) { setError(phoneCheck.error ?? 'Invalid phone number.'); return; }
    }
    setSubmitting(true);
    try {
      const res = await publicApi.verify({
        token_id: (tokenId ?? '').trim(),
        property_address: (propertyAddress ?? '').trim() || undefined,
        name: (name ?? '').trim() || undefined,
        phone: (phone ?? '').trim() || undefined,
      });
      setResult(res);
    } catch (err) {
      setError((err as Error)?.message ?? 'Verification failed.');
    } finally {
      setSubmitting(false);
    }
  };

  const inputClass = 'w-full px-4 py-2.5 rounded-lg border border-gray-300 text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors';

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-100/60 via-blue-50/30 to-sky-50/50 text-gray-800 print:bg-white print:min-h-0">
      <div className="max-w-xl mx-auto px-4 sm:px-6 py-8 sm:py-10 space-y-6 print:py-6">
        <header className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Verify authorization</h1>
          <p className="text-gray-600 mt-1 text-sm">
            Enter the token (Invitation ID) to check the current status of this property.
          </p>
        </header>

        {/* --- Search form (hidden when printing) --- */}
        <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 space-y-4 print:hidden">
          <div>
            <label htmlFor="verify-token" className="block text-sm font-medium text-gray-700 mb-1.5">Token ID <span className="text-red-500">*</span></label>
            <input id="verify-token" type="text" value={tokenId} onChange={(e) => setTokenId(e.target.value)} placeholder="e.g. INV-XXXX" className={inputClass} required />
          </div>
          <div>
            <label htmlFor="verify-address" className="block text-sm font-medium text-gray-600 mb-1.5">Property address <span className="text-gray-400 font-normal">(optional)</span></label>
            <textarea id="verify-address" value={propertyAddress} onChange={(e) => setPropertyAddress(e.target.value)} placeholder="Street, city, state, ZIP" rows={2} className={`${inputClass} resize-none`} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="verify-name" className="block text-sm font-medium text-gray-600 mb-1.5">Name (optional)</label>
              <input id="verify-name" type="text" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label htmlFor="verify-phone" className="block text-sm font-medium text-gray-600 mb-1.5">Phone (optional)</label>
              <input id="verify-phone" type="text" value={phone} onChange={(e) => setPhone(sanitizePhoneInput(e.target.value))} placeholder="+15551234567" className={inputClass} />
            </div>
          </div>
          {error && (
            <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex items-center gap-2">
              <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
              {error}
            </p>
          )}
          <button type="submit" disabled={submitting} className="w-full sm:w-auto min-w-[140px] px-6 py-2.5 rounded-lg bg-blue-700 text-white font-medium hover:bg-blue-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
            {submitting ? <span className="inline-flex items-center gap-2"><svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>Verifying…</span> : 'Verify'}
          </button>
        </form>

        {/* --- Result section --- */}
        {result && (
          <section id="verify-result" className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden print:shadow-none print:border print:break-inside-avoid">
            {/* Print header */}
            <div className="hidden print:block px-6 py-3 border-b border-gray-200">
              <h2 className="text-lg font-bold text-gray-900">DocuStay Verification Record</h2>
              <p className="text-sm text-gray-500 mt-0.5">{result.verified_at ? `Verified: ${formatDateTimeLocal(result.verified_at)}` : ''}</p>
              <p className="text-xs text-gray-400">Source: {result.verification_source || 'DocuStay Verification Portal'}</p>
            </div>

            {/* Status banner */}
            <div className={`px-6 py-4 border-b ${result.valid ? 'bg-emerald-50 border-emerald-100' : hasRecord(result) ? 'bg-slate-50 border-slate-200' : 'bg-amber-50 border-amber-100'} print:bg-gray-50 print:border-gray-200`}>
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold uppercase tracking-wider text-gray-700 print:text-base">Property Status</h2>
              </div>
            </div>

            <div className="p-6 sm:p-8 space-y-6">
              {/* Status badge */}
              {result.valid ? (
                <div className="inline-flex items-center gap-2.5 px-4 py-2.5 rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-200">
                  <svg className="w-5 h-5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" /></svg>
                  <span className="font-semibold">Active authorization</span>
                </div>
              ) : hasRecord(result) ? (
                <div className="inline-flex items-center gap-2.5 px-4 py-2.5 rounded-lg bg-slate-100 text-slate-800 border border-slate-200">
                  <span className="font-semibold">Verification record</span>
                  {result.status && <span className={`px-2.5 py-1 rounded text-xs font-semibold uppercase tracking-wide ${STATUS_COLORS[result.status] || 'bg-gray-100 text-gray-600'}`}>{result.status}</span>}
                </div>
              ) : (
                <div className="inline-flex items-center gap-2.5 px-4 py-2.5 rounded-lg bg-amber-50 text-amber-800 border border-amber-200">
                  <svg className="w-5 h-5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
                  <span className="font-semibold">No record found</span>
                </div>
              )}
              {!hasRecord(result) && result.reason && <p className="text-gray-700">{result.reason}</p>}

              {hasRecord(result) && (
                <>
                  {result.reason && <p className="text-sm text-gray-700 -mt-2 font-medium">{result.reason}</p>}

                  {/* Property information */}
                  <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-4 print:bg-white print:border-gray-300">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">Property information</h3>
                    <p className="text-base font-semibold text-gray-900">{result.property_name || '—'}</p>
                    <p className="text-sm text-gray-700 mt-1 leading-relaxed">{result.property_address || '—'}</p>
                  </div>

                  {/* Assigned tenants */}
                  {result.assigned_tenants && result.assigned_tenants.length > 0 && (
                    <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-4 print:bg-white print:border-gray-300">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">Assigned tenants</h3>
                      <ul className="space-y-1.5 list-disc list-inside text-sm font-medium text-gray-900">
                        {result.assigned_tenants.map((t, i) => (
                          <li key={i}>{t.name}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Guest authorization */}
                  {result.guest_name && (
                    <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-4 print:bg-white print:border-gray-300">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">Guest authorization</h3>
                      <div className="space-y-3 text-sm">
                        <div className="flex justify-between gap-4">
                          <span className="text-gray-500">Guest</span>
                          <span className="text-gray-900 font-medium">{result.guest_name}</span>
                        </div>
                        {result.status && (
                          <div className="flex justify-between gap-4">
                            <span className="text-gray-500">Status</span>
                            <span className={`font-semibold uppercase tracking-wide text-xs px-2.5 py-1 rounded ${STATUS_COLORS[result.status] || 'bg-gray-100 text-gray-600'}`}>{result.status}</span>
                          </div>
                        )}
                        {result.stay_start_date && (
                          <div className="flex justify-between gap-4">
                            <span className="text-gray-500">Authorized</span>
                            <span className="text-gray-900 font-medium">
                              {formatCalendarDate(result.stay_start_date)}{result.stay_end_date ? ` – ${formatCalendarDate(result.stay_end_date)}` : ''}
                            </span>
                          </div>
                        )}
                        {result.checked_in_at && (
                          <div className="flex justify-between gap-4">
                            <span className="text-gray-500">Became active</span>
                            <span className="text-gray-900 font-medium">{formatDateTimeLocal(result.checked_in_at)}</span>
                          </div>
                        )}
                        {result.status === 'REVOKED' && result.revoked_at && (
                          <div className="flex justify-between gap-4">
                            <span className="text-gray-500">Revoked at</span>
                            <span className="text-gray-900 font-medium">{formatDateTimeLocal(result.revoked_at)}</span>
                          </div>
                        )}
                        {result.status === 'COMPLETED' && result.checked_out_at && (
                          <div className="flex justify-between gap-4">
                            <span className="text-gray-500">Ended at</span>
                            <span className="text-gray-900 font-medium">{formatDateTimeLocal(result.checked_out_at)}</span>
                          </div>
                        )}
                        {result.cancelled_at && (
                          <div className="flex justify-between gap-4">
                            <span className="text-gray-500">Cancelled at</span>
                            <span className="text-gray-900 font-medium">{formatDateTimeLocal(result.cancelled_at)}</span>
                          </div>
                        )}
                        {result.status === 'EXPIRED' && result.stay_end_date && (
                          <div className="flex justify-between gap-4">
                            <span className="text-gray-500">Expired</span>
                            <span className="text-gray-900 font-medium">{formatCalendarDate(result.stay_end_date)}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Authorization history (archived records) */}
                  {result.authorization_history && result.authorization_history.length > 1 && (
                    <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-4 print:bg-white print:border-gray-300">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">Authorization history</h3>
                      <div className="space-y-2">
                        {result.authorization_history.map((auth) => (
                          <div key={auth.authorization_number} className="flex items-center justify-between text-sm p-2 rounded-lg bg-white border border-gray-100">
                            <div>
                              <span className="font-medium text-gray-800">Authorization #{auth.authorization_number}</span>
                              <span className="text-gray-500 ml-2">{auth.guest_name}</span>
                              {auth.start_date && <span className="text-gray-400 ml-2 text-xs">{formatCalendarDate(auth.start_date)}{auth.end_date ? ` – ${formatCalendarDate(auth.end_date)}` : ''}</span>}
                            </div>
                            <span className={`text-xs font-semibold uppercase tracking-wide px-2 py-0.5 rounded ${STATUS_COLORS[auth.status] || 'bg-gray-100 text-gray-600'}`}>{auth.status}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Documents section */}
                  <div className="rounded-lg border-2 border-blue-200 bg-blue-50/30 p-4 print:border-blue-300 print:bg-blue-50/50">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-blue-800 mb-3">Documents</h3>
                    <div className="flex flex-wrap gap-3">
                      {result.signed_agreement_available && result.signed_agreement_url && (
                        <a href={resolveBackendMediaUrl(result.signed_agreement_url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                          View Authorization Agreement
                        </a>
                      )}
                      {result.poa_url && (
                        <a href={resolveBackendMediaUrl(result.poa_url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
                          View Power of Attorney
                        </a>
                      )}
                      <button type="button" onClick={() => setShowLedger(!showLedger)} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-600 text-white text-sm font-semibold hover:bg-slate-700 transition-colors">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
                        {showLedger ? 'Hide' : 'View'} Activity Ledger
                      </button>
                      <button type="button" onClick={() => window.print()} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-700 text-white text-sm font-semibold hover:bg-gray-800 transition-colors print:hidden">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
                        Print Evidence Snapshot
                      </button>
                    </div>
                    {!result.signed_agreement_available && !result.poa_url && (
                      <p className="text-sm text-gray-500 mt-2">No signed documents available for this record.</p>
                    )}
                  </div>

                  {/* Authority & links */}
                  <div className="space-y-3 pt-2 border-t border-gray-200">
                    {result.poa_signed_at && (
                      <p className="text-sm text-gray-600">Property documented under Master POA (signed {formatCalendarDate(result.poa_signed_at)}).</p>
                    )}
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      {result.live_slug && (
                        <a href={`${APP_ORIGIN}/#live/${result.live_slug}`} target="_blank" rel="noopener noreferrer" className="text-blue-700 hover:text-blue-800 font-medium hover:underline inline-flex items-center gap-1">
                          Open full evidence page
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                        </a>
                      )}
                    </div>
                  </div>

                  {/* Verification timestamp */}
                  <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-center">
                    <p className="text-sm font-semibold text-slate-700">
                      {result.verified_at ? `Verified: ${formatDateTimeLocal(result.verified_at)}` : ''}
                    </p>
                    <p className="text-xs text-slate-500 mt-0.5">Source: {result.verification_source || 'DocuStay Verification Portal'}</p>
                    {result.live_slug && <p className="text-xs text-slate-400 mt-0.5">Record ID: {result.live_slug}</p>}
                  </div>
                </>
              )}
            </div>

            {/* Activity ledger (toggled) */}
            {hasRecord(result) && (showLedger || false) && result.audit_entries && result.audit_entries.length > 0 && (
              <div className="border-t border-gray-200 px-6 py-4 bg-gray-50/50 print:bg-white print:block">
                <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">Activity ledger</h3>
                <ul className="space-y-2 text-sm text-gray-700 max-h-72 overflow-y-auto print:max-h-none">
                  {result.audit_entries.map((entry, i) => (
                    <li key={i} className="flex gap-3 items-start">
                      <span className="text-gray-400 shrink-0 text-xs whitespace-nowrap">{entry.created_at ? formatDateTimeLocal(entry.created_at) : '—'}</span>
                      <span>{entry.message || entry.title}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Always show ledger in print */}
            {hasRecord(result) && !showLedger && result.audit_entries && result.audit_entries.length > 0 && (
              <div className="hidden print:block border-t border-gray-200 px-6 py-4 bg-white">
                <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">Activity ledger</h3>
                <ul className="space-y-2 text-sm text-gray-700">
                  {result.audit_entries.map((entry, i) => (
                    <li key={i} className="flex gap-3 items-start">
                      <span className="text-gray-400 shrink-0 text-xs whitespace-nowrap">{entry.created_at ? formatDateTimeLocal(entry.created_at) : '—'}</span>
                      <span>{entry.message || entry.title}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        <footer className="text-center text-xs text-gray-500 pt-6 print:pt-2">
          <p className="font-medium text-gray-600">DocuStay Verify</p>
          <p className="mt-0.5 text-gray-400">Read-only · All attempts are logged</p>
        </footer>
      </div>
    </div>
  );
};
