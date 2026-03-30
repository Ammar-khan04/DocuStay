import React, { useState, useEffect } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout } from '../../components/AuthCardLayout';
import { authApi } from '../../services/api';

interface ResetPasswordProps {
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  navigate: (v: string) => void;
}

/** Parse token and role from hash: #reset-password?token=...&role=owner */
function getResetParamsFromHash(): { token: string; role: 'owner' | 'guest' } | null {
  if (typeof window === 'undefined') return null;
  const hash = window.location.hash || '';
  const queryPart = hash.includes('?') ? hash.split('?')[1] : '';
  if (!queryPart) return null;
  const params = new URLSearchParams(queryPart);
  const token = params.get('token')?.trim();
  const role = (params.get('role') || '').toLowerCase();
  if (!token || (role !== 'owner' && role !== 'guest')) return null;
  return { token, role: role as 'owner' | 'guest' };
}

const ResetPassword: React.FC<ResetPasswordProps> = ({ setLoading, notify, navigate }) => {
  const [params, setParams] = useState<{ token: string; role: 'owner' | 'guest' } | null>(null);
  const [formData, setFormData] = useState({ newPassword: '', confirmPassword: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [success, setSuccess] = useState(false);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  useEffect(() => {
    setParams(getResetParamsFromHash());
  }, []);

  const showError = (message: string) => setErrorModal({ open: true, message });
  const signInView = params?.role === 'owner' ? 'login' : 'guest-login';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!params?.token) {
      showError('Invalid or missing reset link. Please use the link from your email or request a new one.');
      return;
    }
    if (!formData.newPassword || !formData.confirmPassword) {
      showError('Please enter and confirm your new password.');
      return;
    }
    if (formData.newPassword.length < 8) {
      showError('Password must be at least 8 characters.');
      return;
    }
    if (formData.newPassword !== formData.confirmPassword) {
      showError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.resetPassword(params.token, formData.newPassword, formData.confirmPassword);
      setLoading(false);
      if (result.status === 'ok') {
        setSuccess(true);
        notify('success', result.message || 'Password updated. You can sign in now.');
      } else {
        showError(result.message || 'Failed to update password. The link may have expired.');
      }
    } catch (err) {
      setLoading(false);
      showError((err as Error)?.message || 'Failed to update password. The link may have expired. Please request a new one.');
    }
  };

  if (params === null) {
    return (
      <HeroBackground className="flex-grow">
        <AuthCardLayout singleColumn maxWidth="2xl">
          <p className="text-slate-600 text-sm">Loading…</p>
        </AuthCardLayout>
      </HeroBackground>
    );
  }

  if (!params.token) {
    return (
      <HeroBackground className="flex-grow">
        <AuthCardLayout singleColumn maxWidth="2xl">
          <h1 className="text-xl font-semibold text-slate-900 mb-2">Invalid reset link</h1>
          <p className="text-slate-600 text-sm mb-4">
            This link is invalid or has expired. Please request a new password reset from the sign-in page.
          </p>
          <button
            type="button"
            onClick={() => navigate(params?.role === 'owner' ? 'login' : 'guest-login')}
            className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] underline underline-offset-2"
          >
            Back to sign in
          </button>
        </AuthCardLayout>
      </HeroBackground>
    );
  }

  if (success) {
    return (
      <HeroBackground className="flex-grow">
        <AuthCardLayout singleColumn maxWidth="2xl">
          <h1 className="text-xl font-semibold text-slate-900 mb-2">Password updated</h1>
          <p className="text-slate-600 text-sm mb-4">You can sign in now with your new password.</p>
          <Button onClick={() => navigate(signInView)} className="w-full py-2.5">
            Sign in
          </Button>
        </AuthCardLayout>
      </HeroBackground>
    );
  }

  const isOwner = params.role === 'owner';

  return (
    <HeroBackground className="flex-grow">
      <AuthCardLayout singleColumn maxWidth="2xl">
        <h1 className="text-xl font-semibold text-slate-900 mb-1">Set new password</h1>
        <p className="text-slate-600 text-sm mb-6">
          Enter a new password for your {isOwner ? 'owner' : 'guest'} account.
        </p>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="relative">
            <Input
              label="New password"
              name="newPassword"
              type={showPassword ? 'text' : 'password'}
              value={formData.newPassword}
              onChange={(e) => setFormData({ ...formData, newPassword: e.target.value })}
              placeholder="••••••••"
              required
              minLength={8}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-[34px] text-slate-400 hover:text-slate-600 transition-colors"
            >
              {showPassword ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" /></svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
              )}
            </button>
          </div>
          <Input
            label="Confirm new password"
            name="confirmPassword"
            type="password"
            value={formData.confirmPassword}
            onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
            placeholder="••••••••"
            required
            minLength={8}
          />
          <Button type="submit" className="w-full py-2.5">Update password</Button>
          <p className="text-center text-sm text-slate-500">
            <button
              type="button"
              onClick={() => navigate(signInView)}
              className="text-[#6B90F2] hover:text-[#5a7ed9] underline underline-offset-2"
            >
              Back to sign in
            </button>
          </p>
        </form>
      </AuthCardLayout>

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
      />
    </HeroBackground>
  );
};

export default ResetPassword;
