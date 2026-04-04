import React, { useState } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout, AuthBullet } from '../../components/AuthCardLayout';
import { authApi } from '../../services/api';

interface RegisterManagerLandingProps {
  navigate: (v: string) => void;
}

/** Extracts invite token from a pasted invite link or raw token. */
function extractInviteToken(input: string): string | null {
  const s = (input || '').trim();
  if (!s) return null;
  // Full URL with hash: ...#register/manager/TOKEN or .../register/manager/TOKEN
  const hashMatch = s.match(/#register\/manager\/([^?#&]+)/);
  if (hashMatch) return hashMatch[1];
  const pathMatch = s.match(/\/register\/manager\/([^?#&/]+)/);
  if (pathMatch) return pathMatch[1];
  // Plain token (alphanumeric)
  if (/^[a-zA-Z0-9_-]+$/.test(s)) return s;
  return null;
}

const RegisterManagerLanding: React.FC<RegisterManagerLandingProps> = ({ navigate }) => {
  const [inviteInput, setInviteInput] = useState('');
  const [error, setError] = useState('');
  const [validating, setValidating] = useState(false);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const token = extractInviteToken(inviteInput);
    if (!token) {
      setError('Please paste your invite link from the property owner email, or enter your invite code.');
      return;
    }
    setValidating(true);
    try {
      const info = await authApi.getManagerInvite(token);
      if (info.already_accepted) {
        navigate(info.is_demo ? 'demo' : `login/property_manager/${token}`);
        return;
      }
      navigate(`register/manager/${token}`);
    } catch {
      setError('This invite link is invalid or has expired. Please use the link from your invitation email.');
    } finally {
      setValidating(false);
    }
  };

  return (
    <HeroBackground className="flex-grow">
      <AuthCardLayout singleColumn maxWidth="2xl" leftPanel={
        <>
          <h2 className="text-2xl font-semibold text-slate-900 mb-3">Property Manager Signup</h2>
          <p className="text-slate-600 text-sm mb-8">Property managers receive invitations from property owners.</p>
          <ul className="space-y-3">
            <AuthBullet>Check your email for the invite link</AuthBullet>
            <AuthBullet>Paste the link or code below</AuthBullet>
            <AuthBullet>Create your account and get started</AuthBullet>
          </ul>
        </>
      }>
          <h1 className="text-xl font-semibold text-slate-900 mb-2 lg:hidden">Property Manager Signup</h1>
          <p className="text-slate-600 text-sm mb-6">
            Paste your invite link from the email to create your account.
          </p>
          <form onSubmit={handleSubmit} className="space-y-5">
            <Input
              label="Invite link or code"
              name="invite_link"
              value={inviteInput}
              onChange={(e) => setInviteInput(e.target.value)}
              placeholder="Paste invite link from email"
              error={error}
            />
            <Button type="submit" className="w-full py-2.5" disabled={validating}>{validating ? 'Checking…' : 'Continue'}</Button>
          </form>
          <p className="mt-6 text-center text-slate-500 text-sm">
            Already have an account?{' '}
            <button type="button" onClick={() => navigate('login/property_manager')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline">
              Log in
            </button>
          </p>
          <p className="mt-4 text-center">
            <button type="button" onClick={() => navigate('')} className="text-sm text-slate-500 hover:text-slate-700 underline underline-offset-2">
              Back
            </button>
          </p>
      </AuthCardLayout>
      <ErrorModal open={errorModal.open} message={errorModal.message} onClose={() => setErrorModal((p) => ({ ...p, open: false }))} />
    </HeroBackground>
  );
};

export default RegisterManagerLanding;
