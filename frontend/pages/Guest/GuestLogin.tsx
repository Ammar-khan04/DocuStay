import React, { useState, useEffect } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout, AuthBullet } from '../../components/AuthCardLayout';
import { authApi, invitationsApi } from '../../services/api';

const parseInviteCode = (raw: string): string => {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
};

interface GuestLoginProps {
  inviteCode?: string;
  onLogin: (user: any) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  navigate: (v: string) => void;
  setPendingVerification?: (data: { userId: string; type: 'email'; generatedAt: string }) => void;
  onGuestLogin?: (user: any) => void;
  onTenantLogin?: (user: any) => void;
}

const PENDING_INVITE_STORAGE_KEY = 'docustay_pending_invite_code';

const GuestLogin: React.FC<GuestLoginProps> = ({ inviteCode: inviteCodeFromUrl, onLogin, setLoading, notify, navigate, setPendingVerification, onGuestLogin, onTenantLogin }) => {
  const [formData, setFormData] = useState({ email: '', password: '', invitation_link: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });
  const [inviteCheck, setInviteCheck] = useState<{ loading: boolean; valid: boolean; expired?: boolean; used?: boolean; already_accepted?: boolean; revoked?: boolean; cancelled?: boolean; reason?: string; invitation_kind?: string } | null>(null);

  const inviteCode = inviteCodeFromUrl || parseInviteCode(formData.invitation_link);
  const showError = (message: string) => setErrorModal({ open: true, message });

  useEffect(() => {
    if (!inviteCode || inviteCode.length < 5) {
      if (!inviteCode) setInviteCheck(null);
      return;
    }
    setInviteCheck((prev) => (prev?.valid === true && !prev?.expired ? prev : { loading: true, valid: true }));
    invitationsApi.getDetails(inviteCode)
      .then((d) => {
        const kind = d.invitation_kind || (d.is_tenant_invite ? 'tenant' : 'guest');
        if (d.valid && kind === 'tenant') {
          navigate(`register-from-invite/${inviteCode}`);
          return;
        }
        setInviteCheck({ loading: false, valid: d.valid, expired: d.expired, used: d.used, already_accepted: d.already_accepted, revoked: d.revoked, cancelled: d.cancelled, reason: d.reason, invitation_kind: kind });
      })
      .catch(() => setInviteCheck({ loading: false, valid: false }));
  }, [inviteCode, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = formData.email.trim();
    const password = formData.password;
    if (!email || !password) {
      showError('Please enter your email and password.');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      showError('Please enter a valid email address.');
      return;
    }
    if (inviteCode && inviteCheck?.valid === false) {
      showError(
        inviteCheck?.expired ? 'This invitation has expired. Please ask your host for a new invitation.'
        : inviteCheck?.used || inviteCheck?.already_accepted ? 'This invitation has already been accepted. If you already registered, please sign in.'
        : inviteCheck?.revoked ? 'This invitation has been revoked by the property owner. Please contact your host.'
        : inviteCheck?.cancelled ? 'This invitation has been cancelled. Please contact your host.'
        : inviteCheck?.reason === 'not_found' ? 'This invitation code was not found. Please double-check the link or code.'
        : 'This invitation link is invalid. Please check the link or contact your host.'
      );
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.login(email, password, "guest");
      setLoading(false);
      if (result.status !== 'success' || !result.data) {
        showError(result.message || 'Login failed. Please check your email and password.');
        return;
      }
      if (inviteCode && inviteCheck?.valid !== false) {
        sessionStorage.setItem(PENDING_INVITE_STORAGE_KEY, inviteCode.trim().toUpperCase());
        const isTenant = inviteCheck?.invitation_kind === 'tenant';
        notify('success', isTenant ? 'Signed in. Your invitation will be processed on your dashboard.' : 'Signed in. You can sign the invitation agreement on your dashboard.');
      } else if (inviteCode && inviteCheck?.valid === false) {
        notify('error',
          inviteCheck?.expired ? 'This invitation has expired. Please ask your host for a new invitation.'
          : inviteCheck?.used || inviteCheck?.already_accepted ? 'This invitation has already been accepted.'
          : inviteCheck?.revoked ? 'This invitation has been revoked by the property owner.'
          : inviteCheck?.cancelled ? 'This invitation has been cancelled.'
          : 'This invitation link is invalid.'
        );
      } else {
        notify('success', 'Signed in successfully.');
      }
      onLogin(result.data);
      navigate('guest-dashboard');
    } catch (err) {
      setLoading(false);
      const msg = (err as Error)?.message || 'Login failed.';
      if (inviteCode && (msg.toLowerCase().includes('invalid') || msg.toLowerCase().includes('password'))) {
        showError("No guest account found for this email and password. If you haven't registered yet, use \"Create account\" below, then sign the agreement on your dashboard.");
      } else {
        showError(msg);
      }
    }
  };

  return (
    <HeroBackground className="flex-grow">
      <AuthCardLayout
        leftPanel={
          <>
            <h2 className="text-2xl font-semibold text-slate-900 mb-3">Guest login</h2>
            <p className="text-slate-600 text-sm mb-8">Access your stays and invitations.</p>
            <ul className="space-y-3">
              <AuthBullet>View approved stays</AuthBullet>
              <AuthBullet>Accept invitations</AuthBullet>
              <AuthBullet>Stay documentation</AuthBullet>
            </ul>
          {inviteCode && inviteCheck && !inviteCheck.loading && !inviteCheck.valid && (
            <div className="mt-8 p-4 rounded-lg bg-amber-50 border border-amber-300/80">
              <p className="text-sm text-amber-800 font-medium">
                {inviteCheck.expired ? 'This invitation has expired. Please ask your host for a new invitation.'
                  : inviteCheck.used || inviteCheck.already_accepted ? 'This invitation has already been accepted. If you already registered, please sign in instead.'
                  : inviteCheck.revoked ? 'This invitation has been revoked by the property owner. Please contact your host.'
                  : inviteCheck.cancelled ? 'This invitation has been cancelled. Please contact your host.'
                  : inviteCheck.reason === 'not_found' ? 'This invitation code was not found. Please double-check the link.'
                  : 'This invitation link is invalid. Please check the link or contact your host.'}
              </p>
            </div>
          )}
          {inviteCode && inviteCheck?.valid === true && (
            <div className="mt-8 p-4 rounded-lg bg-white/70 border border-blue-300/80">
              <p className="text-sm text-gray-700">You have an invitation. Sign in and we’ll accept it.</p>
            </div>
          )}
          {inviteCode && inviteCheck?.loading && (
            <div className="mt-8 p-4 rounded-lg bg-white/70 border border-blue-300/80">
              <p className="text-sm text-gray-600">Checking invitation…</p>
            </div>
          )}
          </>
        }
      >
          <div className="max-w-sm mx-auto w-full">
            <h1 className="text-xl font-semibold text-slate-900 mb-1 lg:hidden">Guest login</h1>
            <p className="text-slate-600 text-sm mb-6">
              {inviteCode ? (inviteCheck?.invitation_kind === 'tenant' ? 'Sign in to accept your tenant invitation.' : 'Sign in to continue. You’ll sign the agreement on your dashboard.') : 'Enter your credentials.'}
            </p>

            <form onSubmit={handleSubmit} className="space-y-6">
              <Input
                label="Invitation link (optional)"
                name="invitation_link"
                value={formData.invitation_link}
                onChange={(e) => setFormData({ ...formData, invitation_link: e.target.value })}
                placeholder="Paste invitation link or code if you have one"
              />
              <Input
                label="Email"
                name="email"
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                placeholder="you@example.com"
                required
              />
              <div className="relative">
                <Input
                  label="Password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  placeholder="••••••••"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-[34px] text-slate-400 hover:text-[#6B90F2] transition-colors"
                >
                  {showPassword ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" /></svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                  )}
                </button>
              </div>

              <div className="flex justify-end text-sm">
                <button type="button" onClick={() => navigate('forgot-password/guest')} className="text-[#6B90F2] hover:text-[#5a7ed9] font-medium">Forgot password?</button>
              </div>

              <Button type="submit" className="w-full py-2.5">Sign in</Button>
            </form>

            <div className="mt-8 space-y-2 text-center text-slate-500 text-sm">
              {inviteCode && inviteCheck?.valid === true && (
                <p>
                  First time?{' '}
                  <button
                    type="button"
                    onClick={() => navigate(`register-from-invite/${inviteCode}`)}
                    className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2"
                  >
                    Create account & accept invitation
                  </button>
                </p>
              )}
              {inviteCode && (!inviteCheck || inviteCheck.valid !== true) && (
                <p>
                  First time?{' '}
                  <button type="button" onClick={() => navigate(`register-from-invite/${inviteCode}`)} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">Create account</button>
                </p>
              )}
              <p>
                Don&apos;t have an account?{' '}
                <button type="button" onClick={() => navigate('guest-signup')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">Guest Signup</button>
              </p>
            </div>
          </div>
      </AuthCardLayout>

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
      />
    </HeroBackground>
  );
};

export default GuestLogin;
export { PENDING_INVITE_STORAGE_KEY };
