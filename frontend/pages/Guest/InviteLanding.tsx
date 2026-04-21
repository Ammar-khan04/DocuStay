import React, { useState, useEffect } from 'react';
import { Button } from '../../components/UI';
import { authApi, invitationsApi, isPropertyTenantInviteKind, type InvitationDetails } from '../../services/api';
import RegisterFromInvite from './RegisterFromInvite';
import GuestLogin from './GuestLogin';
import type { UserSession } from '../../types';
import { formatCalendarDate } from '../../utils/dateUtils';

interface InviteLandingProps {
  invitationCode: string;
  /** When false and the invite is demo-originated, redirect to `#demo/invite/...` first. */
  sessionIsDemo?: boolean;
  /** Logged in as a demo tenant (after DemoInviteGate); show explicit accept instead of silent auto-accept. */
  demoTenantSession?: boolean;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  setPendingVerification: (data: { userId: string; type: 'email'; generatedAt: string }) => void;
  onLogin: (user: any) => void;
  onGuestLogin?: (user: UserSession) => void;
  onTenantLogin?: (user: UserSession) => void;
}

/**
 * When user opens #invite/CODE we fetch invite details.
 * - Production tenant invite: RegisterFromInvite (signup / sign-in then accept elsewhere as needed).
 * - Demo tenant after `#demo/invite/CODE` sign-in: explicit "Accept invitation" (no silent accept on load).
 * - Guest invites: GuestLogin or demo guest auto-accept as before.
 */
const InviteLanding: React.FC<InviteLandingProps> = ({
  invitationCode,
  sessionIsDemo = false,
  demoTenantSession = false,
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
  const [demoGuestAutoAccepting, setDemoGuestAutoAccepting] = useState(false);
  const [demoTenantAcceptSubmitting, setDemoTenantAcceptSubmitting] = useState(false);
  const code = (invitationCode || '').trim().toUpperCase();

  useEffect(() => {
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

  if (sessionIsDemo && demoTenantSession && details?.valid && isTenantInvite && code) {
    const handleDemoTenantAccept = () => {
      setDemoTenantAcceptSubmitting(true);
      setLoading(true);
      authApi
        .acceptInvite(code, null)
        .then(async () => {
          const me = await authApi.me();
          if (me && onTenantLogin) onTenantLogin(me);
          notify('success', 'Invitation accepted.');
          navigate('tenant-dashboard');
        })
        .catch((e) => {
          notify('error', (e as Error)?.message ?? 'Could not accept invitation.');
        })
        .finally(() => {
          setDemoTenantAcceptSubmitting(false);
          setLoading(false);
        });
    };

    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px] px-4">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-sm text-center space-y-4">
          <h1 className="text-xl font-semibold text-slate-900">Tenant invitation</h1>
          <p className="text-sm text-slate-600">
            {details.property_name ? (
              <>
                Accept access to <span className="font-medium text-slate-800">{details.property_name}</span>
                {details.stay_start_date && details.stay_end_date ? (
                  <>
                    {' '}
                    for <span className="font-medium">{formatCalendarDate(details.stay_start_date)}</span> –{' '}
                    <span className="font-medium">{formatCalendarDate(details.stay_end_date)}</span>
                  </>
                ) : null}
                .
              </>
            ) : (
              'Review the lease dates below, then accept to continue (same as production).'
            )}
          </p>
          <Button
            type="button"
            variant="primary"
            className="w-full"
            disabled={demoTenantAcceptSubmitting}
            onClick={handleDemoTenantAccept}
          >
            {demoTenantAcceptSubmitting ? 'Accepting…' : 'Accept invitation'}
          </Button>
          <p className="text-xs text-slate-500">
            The invite is only completed after you accept here (same as production).
          </p>
        </div>
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
