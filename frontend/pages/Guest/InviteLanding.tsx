import React, { useState, useEffect } from 'react';
import { authApi, invitationsApi, isPropertyTenantInviteKind, type InvitationDetails } from '../../services/api';
import RegisterFromInvite from './RegisterFromInvite';
import GuestLogin from './GuestLogin';
import type { UserSession } from '../../types';

interface InviteLandingProps {
  invitationCode: string;
  /** When false and the invite is demo-originated, redirect to `#demo/invite/...` first. */
  sessionIsDemo?: boolean;
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
  sessionIsDemo = false,
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
  const [demoRedirecting, setDemoRedirecting] = useState(false);
  const [demoTenantAutoAccepting, setDemoTenantAutoAccepting] = useState(false);
  const [demoGuestAutoAccepting, setDemoGuestAutoAccepting] = useState(false);
  const code = (invitationCode || '').trim().toUpperCase();

  useEffect(() => {
    setDemoTenantAutoAccepting(false);
    setDemoGuestAutoAccepting(false);
  }, [code]);

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

  useEffect(() => {
    if (loadingDetails || !details?.valid || !details.is_demo || sessionIsDemo || !code) return;
    setDemoRedirecting(true);
    navigate(`demo/invite/${code}`);
  }, [loadingDetails, details, sessionIsDemo, code, navigate]);

  // Demo behavior: tenant invites should be accepted automatically (no signup/agreement flow).
  // Must run unconditionally (same hook order every render) — do not place after early returns.
  useEffect(() => {
    if (loadingDetails) return;
    if (!sessionIsDemo) return;
    if (!details?.valid) return;
    const tenantInvite =
      isPropertyTenantInviteKind(details.invitation_kind) || Boolean(details.is_tenant_invite);
    if (!tenantInvite) return;
    if (!code) return;
    if (demoTenantAutoAccepting) return;
    setDemoTenantAutoAccepting(true);
    setLoading(true);
    authApi
      .acceptInvite(code, null)
      .then(async () => {
        const me = await authApi.me();
        if (me && onTenantLogin) onTenantLogin(me);
        notify('success', 'Demo invitation accepted.');
        navigate('tenant-dashboard');
      })
      .catch((e) => {
        notify('error', (e as Error)?.message ?? 'Could not accept invitation.');
        setDemoTenantAutoAccepting(false);
      })
      .finally(() => setLoading(false));
  }, [
    loadingDetails,
    sessionIsDemo,
    details,
    code,
    demoTenantAutoAccepting,
    setLoading,
    notify,
    navigate,
    onTenantLogin,
  ]);

  // Demo behavior: guest invites should be accepted automatically (no signup/agreement flow).
  // Backend records the same agreement document + PDF as production typed signing.
  useEffect(() => {
    if (loadingDetails) return;
    if (!sessionIsDemo) return;
    if (!details?.valid) return;
    const tenantInvite = isPropertyTenantInviteKind(details.invitation_kind) || Boolean(details.is_tenant_invite);
    if (tenantInvite) return;
    if (!code) return;
    if (demoGuestAutoAccepting) return;
    setDemoGuestAutoAccepting(true);
    setLoading(true);
    authApi
      .acceptInvite(code, null)
      .then(async () => {
        const me = await authApi.me();
        if (me && onGuestLogin) onGuestLogin(me);
        notify('success', 'Demo invitation accepted.');
        navigate('guest-dashboard');
      })
      .catch((e) => {
        notify('error', (e as Error)?.message ?? 'Could not accept invitation.');
        setDemoGuestAutoAccepting(false);
      })
      .finally(() => setLoading(false));
  }, [
    loadingDetails,
    sessionIsDemo,
    details,
    code,
    demoGuestAutoAccepting,
    setLoading,
    notify,
    navigate,
    onGuestLogin,
  ]);

  if (loadingDetails) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px]">
        <p className="text-slate-500 text-sm">Loading invitation…</p>
      </div>
    );
  }

  if (demoRedirecting) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px]">
        <p className="text-slate-500 text-sm">Redirecting to demo sign-in…</p>
      </div>
    );
  }

  const isTenantInvite = isPropertyTenantInviteKind(details?.invitation_kind) || Boolean(details?.is_tenant_invite);

  if (demoTenantAutoAccepting) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px]">
        <p className="text-slate-500 text-sm">Accepting demo invitation…</p>
      </div>
    );
  }

  if (demoGuestAutoAccepting) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px]">
        <p className="text-slate-500 text-sm">Accepting demo invitation…</p>
      </div>
    );
  }

  if (isTenantInvite) {
    return (
      <RegisterFromInvite
        invitationId={code}
        sessionIsDemo={sessionIsDemo}
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
