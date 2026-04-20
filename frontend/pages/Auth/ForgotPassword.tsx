import React, { useState } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout, AuthBullet } from '../../components/AuthCardLayout';
import { authApi } from '../../services/api';

export type ForgotPasswordRole = 'owner' | 'guest';

interface ForgotPasswordProps {
  role: ForgotPasswordRole;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  navigate: (v: string) => void;
}

const ForgotPassword: React.FC<ForgotPasswordProps> = ({ role, setLoading, notify, navigate }) => {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  const showError = (message: string) => setErrorModal({ open: true, message });
  const isOwner = role === 'owner';
  const signInView = isOwner ? 'login' : 'guest-login';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      showError('Please enter your email address.');
      return;
    }
    setLoading(true);
    try {
      const result = await authApi.forgotPassword(trimmedEmail, role);
      setLoading(false);
      if (result.status === 'ok') {
        setSubmitted(true);
        notify('success', result.message || 'If an account exists for this email, you will receive a password reset link shortly.');
      } else {
        showError(result.message || 'Something went wrong. Please try again.');
      }
    } catch (err) {
      setLoading(false);
      showError((err as Error)?.message || 'Request failed. Please try again.');
    }
  };

  const title = isOwner ? 'Owner' : 'Guest';
  const subtitle = isOwner
    ? 'Reset the password for your property owner account.'
    : 'Reset the password for your guest account.';

  return (
    <HeroBackground className="flex-grow">
      <AuthCardLayout minHeight="420px" leftPanel={
        <>
          <h2 className="text-2xl font-semibold text-slate-900 mb-3">{title} – Forgot password</h2>
          <p className="text-slate-600 text-sm mb-8">{subtitle}</p>
          <ul className="space-y-3">
            <AuthBullet>Check your email for the reset link</AuthBullet>
            <AuthBullet>Link expires in 1 hour</AuthBullet>
            <AuthBullet>Use the same sign-in page you started from</AuthBullet>
          </ul>
        </>
      }>
          <div className="max-w-sm mx-auto w-full">
            <h1 className="text-xl font-semibold text-slate-900 mb-1 lg:hidden">{title} – Forgot password</h1>
            <p className="text-slate-600 text-sm mb-6">{subtitle}</p>

            {submitted ? (
              <div className="space-y-4">
                <p className="text-slate-700 text-sm">
                  You will receive a password reset link shortly on <strong>{email}</strong>. Check your inbox and spam folder.
                </p>
                <p className="text-slate-600 text-sm">
                  <button
                    type="button"
                    onClick={() => navigate(signInView)}
                    className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] underline underline-offset-2"
                  >
                    Back to {isOwner ? 'Owner' : 'Guest'} sign in
                  </button>
                </p>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-6">
                <Input
                  label="Email"
                  name="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={isOwner ? 'name@company.com' : 'you@example.com'}
                  required
                />
                <Button type="submit" className="w-full py-2.5">Send reset link</Button>
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
            )}
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

export default ForgotPassword;
