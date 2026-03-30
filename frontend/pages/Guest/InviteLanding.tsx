import React, { useState, useEffect } from 'react';
import { invitationsApi, type InvitationDetails } from '../../services/api';
import RegisterFromInvite from './RegisterFromInvite';
import GuestLogin from './GuestLogin';
import type { UserSession } from '../../types';

interface InviteLandingProps {
  invitationCode: string;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  setPendingVerification: (data: { userId: string; type: 'email'; generatedAt: string }) => void;
  onLogin: (user: any) => void;
  onGuestLogin?: (user: UserSession) => void;
  onTenantLogin?: (user: UserSession) => void;
}

/**
 * When user opens #invite/CODE we fetch invite details. If it's a tenant invite we show
 * RegisterFromInvite (full form + agreement). Otherwise we show GuestLogin (sign in or create account).
 */
const InviteLanding: React.FC<InviteLandingProps> = ({
  invitationCode,
  navigate,
  setLoading,
  notify,
  setPendingVerification,
  onLogin,
  onGuestLogin,
  onTenantLogin,
}) => {
  const [details, setDetails] = useState<InvitationDetails | null>(null);
  const [loadingDetails, setLoadingDetails] = useState(true);
  const code = (invitationCode || '').trim().toUpperCase();

  useEffect(() => {
    if (!code || code.length < 5) {
      setLoadingDetails(false);
      setDetails({ valid: false });
      return;
    }
    invitationsApi
      .getDetails(code)
      .then((d) => setDetails(d))
      .catch(() => setDetails({ valid: false }))
      .finally(() => setLoadingDetails(false));
  }, [code]);

  if (loadingDetails) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px]">
        <p className="text-slate-500 text-sm">Loading invitation…</p>
      </div>
    );
  }

  const isTenantInvite = details?.invitation_kind === 'tenant' || Boolean(details?.is_tenant_invite);

  if (isTenantInvite) {
    return (
      <RegisterFromInvite
        invitationId={code}
        navigate={navigate}
        setLoading={setLoading}
        notify={notify}
        setPendingVerification={setPendingVerification}
        onGuestLogin={onGuestLogin}
        onTenantLogin={onTenantLogin}
      />
    );
  }

  return (
    <GuestLogin
      inviteCode={code}
      onLogin={onLogin}
      setLoading={setLoading}
      notify={notify}
      navigate={navigate}
      setPendingVerification={setPendingVerification}
      onGuestLogin={(user) => {
        if (onGuestLogin) onGuestLogin(user);
        else onLogin(user);
      }}
    />
  );
};

export default InviteLanding;
