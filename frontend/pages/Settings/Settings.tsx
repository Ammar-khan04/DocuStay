import React, { useState, useEffect, useCallback } from 'react';
import { Card, Button, Input } from '../../components/UI';
import { ModeSwitcher } from '../../components/ModeSwitcher';
import { UserSession } from '../../types';
import { ownerPoaApi, dashboardApi, API_URL, demoUnsignedPoaPdfRequestPath } from '../../services/api';
import type { OwnerPOASignatureResponse } from '../../services/api';
import type { BillingResponse } from '../../services/api';
import { copyToClipboard } from '../../utils/clipboard';
import { formatDateTimeLocal } from '../../utils/dateUtils';

const Settings: React.FC<{
  user: UserSession | null;
  navigate: (v: string) => void;
  embedded?: boolean;
  /** When embedded in owner dashboard, call to switch to Billing tab */
  onOpenBilling?: () => void;
  /** Owner mode switcher (only when embedded in OwnerDashboard) */
  contextMode?: 'business' | 'personal';
  personalModeUnits?: number[];
  onContextModeChange?: (mode: 'business' | 'personal') => void;
}> = ({ user, navigate, embedded, onOpenBilling, contextMode = 'business', personalModeUnits = [], onContextModeChange }) => {
  const [poaSignature, setPoaSignature] = useState<OwnerPOASignatureResponse | null | undefined>(undefined);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [billingLoading, setBillingLoading] = useState(false);
  const [portfolioLink, setPortfolioLink] = useState<{ portfolio_slug: string; portfolio_url: string } | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [portfolioCopyFeedback, setPortfolioCopyFeedback] = useState(false);
  const [billingPortalOpening, setBillingPortalOpening] = useState(false);
  const isOwner = user?.user_type === 'PROPERTY_OWNER';
  useEffect(() => {
    if (!isOwner) return;
    ownerPoaApi.getMySignature()
      .then((s) => setPoaSignature(s ?? null))
      .catch(() => setPoaSignature(null));
  }, [isOwner]);

  const loadBilling = useCallback(() => {
    if (!isOwner) return;
    setBillingLoading(true);
    dashboardApi.billing()
      .then(setBilling)
      .catch(() => setBilling(null))
      .finally(() => setBillingLoading(false));
  }, [isOwner]);

  useEffect(() => {
    loadBilling();
  }, [loadBilling]);

  // Refresh trial countdown periodically (day boundary / clock skew).
  useEffect(() => {
    if (!isOwner || billing?.subscription_status !== 'trialing') return;
    const t = window.setInterval(() => {
      dashboardApi.billing().then(setBilling).catch(() => {});
    }, 60_000);
    return () => window.clearInterval(t);
  }, [isOwner, billing?.subscription_status]);

  useEffect(() => {
    if (!isOwner) return;
    setPortfolioLoading(true);
    dashboardApi.ownerPortfolioLink()
      .then(setPortfolioLink)
      .catch(() => setPortfolioLink(null))
      .finally(() => setPortfolioLoading(false));
  }, [isOwner]);

  const portfolioFullUrl = portfolioLink
    ? `${typeof window !== 'undefined' ? window.location.origin : ''}${typeof window !== 'undefined' ? (window.location.pathname || '') : ''}#${portfolioLink.portfolio_url}`
    : '';

  const openSignedPoaPdf = () => {
    if (!poaSignature?.signature_id) return;
    const token = typeof window !== 'undefined' ? localStorage.getItem('docustay_token') : null;
    if (!token) return;
    const url = `${API_URL}/agreements/owner-poa/signature/${poaSignature.signature_id}/signed-pdf`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const u = URL.createObjectURL(blob);
        window.open(u, '_blank');
      })
      .catch(() => {});
  };

  const openDemoUnsignedPoaPdf = () => {
    if (!user?.is_demo || user.user_type !== 'PROPERTY_OWNER') return;
    const token = typeof window !== 'undefined' ? localStorage.getItem('docustay_token') : null;
    if (!token) return;
    const url = `${API_URL}${demoUnsignedPoaPdfRequestPath()}`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (!r.ok) throw new Error('pdf');
        return r.blob();
      })
      .then((blob) => {
        const u = URL.createObjectURL(blob);
        window.open(u, '_blank');
      })
      .catch(() => {});
  };

  return (
    <div className="w-full max-w-5xl py-4 md:py-6">
      {!embedded && (
        <button
          onClick={() => navigate('dashboard')}
          className="flex items-center gap-2 text-gray-600 hover:text-blue-700 font-medium text-sm uppercase tracking-wider transition-colors mb-6"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back to Dashboard
        </button>
      )}
      <header className="mb-6">
        <h1 className="text-2xl md:text-3xl font-bold text-gray-900 tracking-tight">Settings</h1>
        <p className="text-gray-600 text-sm mt-1">Manage your DocuStay account and preferences.</p>
      </header>

      {isOwner && !billingLoading && billing?.subscription_status === 'trialing' && billing.trial_days_remaining != null && billing.trial_end_at && (
        <div
          className="mb-6 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-950 shadow-sm"
          role="status"
        >
          <p className="font-semibold text-sky-900">Free trial active</p>
          <p className="mt-1 text-sky-900/90">
            {billing.trial_days_remaining > 1
              ? `${billing.trial_days_remaining} days left in your free trial.`
              : billing.trial_days_remaining === 1
                ? '1 day left in your free trial.'
                : 'Your free trial ends today.'}{' '}
            Billing is $10 per unit per month after the trial. Trial ends{' '}
            <time dateTime={billing.trial_end_at}>
              {formatDateTimeLocal(billing.trial_end_at)}
            </time>
            . Add a default payment method below to avoid interruption.
          </p>
        </div>
      )}

      <div className="space-y-8">
        {/* Personal Information – main white card, larger */}
        <Card className="p-8 md:p-10">
          <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-8">Personal Information</h2>
          <div className="grid md:grid-cols-2 gap-6">
            <Input label="Full name" name="name" value={user?.user_name || ''} onChange={() => {}} disabled />
            <Input label="Verified Email" name="email" value={user?.email || ''} onChange={() => {}} disabled />
            <Input label="Phone Number" name="phone" value="+1 (555) 000-0000" onChange={() => {}} />
          </div>
          <div className="mt-8 flex justify-start">
            <Button variant="primary" type="button" className="px-8">
              Update Profile
            </Button>
          </div>
        </Card>

        {/* Mode (owners only, when embedded with props) */}
        {isOwner && onContextModeChange && (
          <Card className="p-8 md:p-10">
            <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Mode</h2>
            <p className="text-gray-600 text-sm mb-4">
              <strong>Personal mode:</strong> Manage your own properties and statuses—multiple properties, primary residence, occupancy (vacant, away, inactive). Use resident features (presence, guest invites) for units where you live.
            </p>
            <p className="text-gray-600 text-sm mb-4">
              <strong>Business mode:</strong> Management scope only. Property status, occupancy, Shield Mode, billing, and event ledger. No personal guest or stay activity is shown.
            </p>
            <ModeSwitcher
              contextMode={contextMode}
              personalModeUnits={personalModeUnits}
              onContextModeChange={onContextModeChange}
              inline
            />
          </Card>
        )}

        {/* Subscription & Billing (owners only, hidden in Personal mode) */}
        {isOwner && contextMode !== 'personal' && (
          <Card className="p-8 md:p-10">
            <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Subscription & Billing</h2>
            {billingLoading ? (
              <p className="text-gray-500 text-sm">Loading…</p>
            ) : billing === null ? (
              <p className="text-gray-500 text-sm">Unable to load billing information. Try the Billing tab or refresh.</p>
            ) : (
              <div className="space-y-4">
                <div className="p-4 rounded-lg bg-slate-50 border border-slate-200">
                  <p className="text-sm font-medium text-gray-800 mb-1">Subscription</p>
                  <p className="text-sm text-gray-600">
                    <strong className="text-gray-900">$10 per unit per month</strong> after a <strong className="text-gray-900">7-day free trial</strong>. Add a default payment method before the trial ends to avoid interruption.
                  </p>
                </div>
                <div className="grid md:grid-cols-2 gap-4">
                  <div className="p-4 rounded-lg bg-gray-50 border border-gray-200">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Active units</p>
                    <p className="text-2xl font-bold text-gray-900">{billing.current_unit_count ?? 0}</p>
                    <p className="text-sm text-gray-600 mt-1">Billed per unit</p>
                  </div>
                  <div className="p-4 rounded-lg bg-gray-50 border border-gray-200">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Shield monitoring</p>
                    <p className="text-2xl font-bold text-gray-900">{billing.current_shield_count ?? 0}</p>
                    <p className="text-sm text-gray-600 mt-1">Counted per property (always on)</p>
                  </div>
                </div>
                {(billing.current_unit_count ?? 0) === 0 && (
                  <p className="text-gray-500 text-sm">Add a unit (by adding a property) to start your subscription and trial.</p>
                )}
                {billing.can_invite === false && (
                  <div className="p-4 rounded-lg bg-amber-50 border border-amber-200">
                    <p className="text-sm font-medium text-amber-800">Billing setup is still in progress.</p>
                    <p className="text-xs text-amber-700 mt-1">Open Billing to finish subscription setup, or try again shortly after adding your first property.</p>
                  </div>
                )}
                <div className="flex flex-wrap gap-3">
                  <Button
                    variant="outline"
                    type="button"
                    disabled={billingPortalOpening}
                    onClick={async () => {
                      setBillingPortalOpening(true);
                      try {
                        // Portal endpoint runs subscription sync once; avoid calling sync + portal (doubles Stripe latency and can hit proxy timeouts).
                        const { url } = await dashboardApi.billingPortalSession();
                        if (url) window.location.href = url;
                      } catch (e) {
                        console.error(e);
                        window.alert((e as Error)?.message ?? 'Could not open payment portal.');
                      } finally {
                        setBillingPortalOpening(false);
                      }
                    }}
                  >
                    {billingPortalOpening ? 'Opening payment portal…' : 'Set default payment method'}
                  </Button>
                  {onOpenBilling && (
                    <Button variant="outline" type="button" onClick={onOpenBilling}>
                      View Billing & Invoices
                    </Button>
                  )}
                </div>
              </div>
            )}
          </Card>
        )}

        {/* Portfolio (owners only) */}
        {isOwner && (
          <Card className="p-8 md:p-10">
            <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-6">Portfolio</h2>
            <p className="text-gray-600 text-sm mb-4">
              Share a public page with your name and list of properties. Anyone with the link can view it—no login required.
            </p>
            {portfolioLoading ? (
              <p className="text-gray-500 text-sm">Loading…</p>
            ) : portfolioLink ? (
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  type="button"
                  onClick={() => window.open(portfolioFullUrl, '_blank')}
                >
                  View portfolio
                </Button>
                <Button
                  variant="outline"
                  type="button"
                  onClick={async () => {
                    const ok = await copyToClipboard(portfolioFullUrl);
                    if (ok) {
                      setPortfolioCopyFeedback(true);
                      setTimeout(() => setPortfolioCopyFeedback(false), 2000);
                    }
                  }}
                >
                  {portfolioCopyFeedback ? 'Copied!' : 'Copy portfolio link'}
                </Button>
              </div>
            ) : (
              <p className="text-gray-500 text-sm">Unable to load portfolio link. Try refreshing.</p>
            )}
          </Card>
        )}

        {/* Master POA (owners only) – same structure as guest agreement section */}
        {isOwner && (
          <Card className="p-8 md:p-10">
            <h2 className="text-lg font-semibold text-gray-900 border-b border-gray-200 pb-3 mb-4">Master Power of Attorney (POA)</h2>
            <p className="text-gray-600 text-sm mb-2">
              The Master POA is a one-time, account-level legal document you signed during onboarding that establishes DocuStay as your legal representative for all property protection activities.
            </p>
            <p className="text-gray-500 text-xs mb-6">
              It designates DocuStay as your Authorized Agent to generate legal evidence packages and maintain audit trails for all properties you add.
            </p>
            {poaSignature === undefined ? (
              <p className="text-gray-500 text-sm">Loading…</p>
            ) : poaSignature ? (
              <div className="space-y-3">
                <p className="text-sm text-gray-700">
                  <span className="font-medium">Signed:</span> {poaSignature.signed_by} on {formatDateTimeLocal(poaSignature.signed_at)}
                </p>
                <Button variant="outline" type="button" onClick={openSignedPoaPdf}>
                  Download signed PDF
                </Button>
              </div>
            ) : (
              <p className="text-sm text-gray-500">No Master POA signature on file for this account.</p>
            )}
            {user?.is_demo && user.user_type === 'PROPERTY_OWNER' && (
              <div className="mt-4 pt-4 border-t border-gray-200">
                <p className="text-xs text-gray-500 mb-2">Demo: view the unsigned Master POA PDF (same template as production, no signature overlay).</p>
                <Button variant="outline" type="button" onClick={openDemoUnsignedPoaPdf}>
                  Download unsigned POA (demo)
                </Button>
              </div>
            )}
          </Card>
        )}

      </div>
    </div>
  );
};

export default Settings;
