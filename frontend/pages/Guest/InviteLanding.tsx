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
  const [demoGuestAutoAccepting, setDemoGuestAutoAccepting] = useState(false);
  const [demoTenantAcceptSubmitting, setDemoTenantAcceptSubmitting] = useState(false);
  const code = (invitationCode || '').trim().toUpperCase();
  const awaitingDemoInviteSignInGate =
    !loadingDetails &&
    Boolean(details?.valid && details.is_demo && !sessionIsDemo && code.length >= 5);

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
    if (!awaitingDemoInviteSignInGate) return;
    navigate(`demo/invite/${code}`);
  }, [awaitingDemoInviteSignInGate, code, navigate]);

  // Demo-only: guest invites from demo hosts auto-accept (same backend signing as prod).
  // Requires API ``is_demo`` so production invites never use this path—even if the viewer session is demo.
  useEffect(() => {
    if (loadingDetails) return;
    if (!sessionIsDemo) return;
    if (!details?.valid || !details.is_demo) return;
    const tenantInv =
      isPropertyTenantInviteKind(details.invitation_kind) || Boolean(details.is_tenant_invite);
    if (tenantInv) return;
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

  if (awaitingDemoInviteSignInGate) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px]">
        <p className="text-slate-500 text-sm">Redirecting to demo sign-in…</p>
      </div>
    );
  }

  const resolvedTenantInvite =
    Boolean(details?.valid) &&
    (isPropertyTenantInviteKind(details.invitation_kind) || Boolean(details.is_tenant_invite));

  if (sessionIsDemo && demoTenantSession && details?.valid && resolvedTenantInvite && code) {
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

  if (sessionIsDemo && Boolean(details?.is_demo) && details?.valid && code && !resolvedTenantInvite) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[320px]">
        <p className="text-slate-500 text-sm">
          {demoGuestAutoAccepting ? 'Accepting demo invitation…' : 'Preparing demo invitation…'}
        </p>
      </div>
    );
  }

  if (resolvedTenantInvite) {
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
