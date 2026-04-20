import React, { useEffect, useState } from "react";
import { Card, Button } from "../../components/UI";
import OwnerPOASignModal from "../../components/OwnerPOASignModal";
import { authApi, pendingOwnerApi } from "../../services/api";
import type { UserSession, TokenResponse } from "../../services/api";
import { getOwnerSignupErrorFriendly } from "../../utils/ownerSignupErrors";

interface Props {
  user: UserSession | null;
  onCompleteSignup?: (data: TokenResponse) => void;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: "success" | "error", m: string) => void;
}

/** Sign Master POA: pending flow (complete-signup) or existing owner (link-poa). Then go to dashboard. */
export default function OnboardingPOA({ user, onCompleteSignup, navigate, setLoading, notify }: Props) {
  const [poaModalOpen, setPoaModalOpen] = useState(false);
  const [linking, setLinking] = useState(false);
  const [pendingData, setPendingData] = useState<{ email: string; full_name: string; city?: string | null; state?: string | null; country?: string | null; account_type?: string | null } | null>(null);
  const [pendingFailed, setPendingFailed] = useState(false);
  const [poaError, setPoaError] = useState<string | null>(null);
  const [lastSignatureId, setLastSignatureId] = useState<number | null>(null);

  useEffect(() => {
    if (user?.user_id === "0" || !user) {
      pendingOwnerApi
        .me()
        .then((d) => setPendingData({ email: d.email, full_name: d.full_name || "", city: d.city, state: d.state, country: d.country, account_type: d.account_type }))
        .catch(() => setPendingFailed(true));
    }
  }, [user]);

  const runCompleteSignup = async (signatureId: number) => {
    setLinking(true);
    setPoaError(null);
    try {
      try {
        const res = await pendingOwnerApi.completeSignup(signatureId);
        notify("success", "Account created. Taking you to your dashboard.");
        onCompleteSignup?.(res);
        navigate("dashboard");
        return;
      } catch (pendingErr: unknown) {
        const msg = (pendingErr as Error)?.message ?? "";
        if (user && (msg.toLowerCase().includes("session expired") || msg.toLowerCase().includes("unauthorized"))) {
          await authApi.linkOwnerPoa(signatureId);
          notify("success", "Authorization linked. Completing setup…");
          navigate("dashboard");
          return;
        }
        throw pendingErr;
      }
    } catch (e) {
      const friendly = getOwnerSignupErrorFriendly((e as Error)?.message ?? "Could not complete signup.");
      setPoaError(friendly.message);
      notify("error", friendly.message);
      if (friendly.redirectTo) {
        navigate(friendly.redirectTo);
      }
    } finally {
      setLinking(false);
    }
  };

  const handleSigned = (signatureId: number) => {
    setPoaModalOpen(false);
    runCompleteSignup(signatureId);
  };

  const email = pendingData?.email ?? user?.email ?? "";
  const fullName = pendingData?.full_name ?? user?.user_name ?? "";

  if (pendingFailed && !user) {
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-6">
        <Card className="max-w-lg w-full p-8 text-center">
          <p className="text-gray-600 mb-4">Your signup session may have expired.</p>
          <Button onClick={() => navigate("register")}>Start over</Button>
        </Card>
      </div>
    );
  }

  if (!pendingData && !user) {
    return (
      <div className="flex-grow flex flex-col items-center justify-center p-6">
        <Card className="max-w-md p-8 text-center">
          <p className="text-gray-600">Loading…</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex-grow flex flex-col items-center justify-center p-6">
      <Card className="max-w-lg w-full p-8 text-center">
        <h1 className="text-xl font-semibold text-gray-900 mb-2">Complete authorization</h1>
        <p className="text-gray-600 mb-6">
          Your identity is verified. Sign the one-time authorization document to complete your account and authorize DocuStay for your properties.
        </p>
        <p className="text-sm text-slate-600 mb-6 bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 text-left">
          When you add properties, your DocuStay subscription includes a <strong className="text-slate-800">7-day free trial</strong>, then{' '}
          <strong className="text-slate-800">$10 per unit per month</strong>.
        </p>
        {poaError && (
          <div className="mb-4 p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm text-left" role="alert">
            {poaError}
          </div>
        )}
        <Button onClick={() => { setPoaError(null); setPoaModalOpen(true); }} disabled={linking} className="w-full">
          Sign authorization document
        </Button>
        <Button
          onClick={() => lastSignatureId != null && runCompleteSignup(lastSignatureId)}
          disabled={linking || lastSignatureId == null}
          variant="outline"
          className="w-full mt-3"
          title={lastSignatureId == null ? "Sign the authorization document first, then click here" : undefined}
        >
          {linking ? "Completing…" : "Complete Verification"}
        </Button>
        <button type="button" onClick={() => navigate("onboarding/identity")} className="mt-3 text-sm text-slate-600 hover:text-slate-900 underline">
          Back to identity
        </button>
      </Card>

      <OwnerPOASignModal
        open={poaModalOpen}
        ownerEmail={email}
        ownerFullName={fullName}
        ownerCity={pendingData?.city}
        ownerState={pendingData?.state}
        ownerCountry={pendingData?.country}
        principalTitle={pendingData?.account_type === "individual" ? "Owner" : pendingData?.account_type === "property_management_company" ? "Property Manager" : pendingData?.account_type === "leasing_company" ? "Property Manager" : "Owner"}
        onClose={() => setPoaModalOpen(false)}
        onSigned={handleSigned}
        notify={notify}
        onSignatureIdKnown={(id) => setLastSignatureId(id)}
      />
    </div>
  );
}
