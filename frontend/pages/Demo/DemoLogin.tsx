import React, { useState, useEffect } from 'react';
import { Button, Card } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout } from '../../components/AuthCardLayout';
import { authApi, type UserSession } from '../../services/api';

type DemoRole = 'owner' | 'property_manager' | 'tenant' | 'guest';

interface DemoLoginProps {
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onLogin: (u: UserSession) => void;
  /** After login, open this hash view (e.g. `invite/CODE` or `register/manager/TOKEN`) instead of a role dashboard. */
  postLoginNavigate?: string;
}

export const DemoLogin: React.FC<DemoLoginProps> = ({ navigate, setLoading, notify, onLogin, postLoginNavigate }) => {
  const [role, setRole] = useState<DemoRole>('owner');
  const [email, setEmail] = useState('');
  const roleLockedToManager = /^register\/manager\//.test(postLoginNavigate || '');

  useEffect(() => {
    if (roleLockedToManager) setRole('property_manager');
  }, [roleLockedToManager]);

  const enterDemo = async () => {
    setLoading(true);
    try {
      const effectiveRole: DemoRole = roleLockedToManager ? 'property_manager' : role;
      const res = await authApi.demoLogin({ role: effectiveRole, email: email.trim() || undefined });
      onLogin(res.data);
      notify('success', 'Demo session started.');
      if (postLoginNavigate) {
        navigate(postLoginNavigate);
        return;
      }
      navigate(
        effectiveRole === 'owner'
          ? 'dashboard'
          : effectiveRole === 'property_manager'
            ? 'manager-dashboard'
            : effectiveRole === 'tenant'
              ? 'tenant-dashboard'
              : 'guest-dashboard'
      );
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Could not start demo.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <HeroBackground className="flex-grow flex items-center justify-center p-6">
      <AuthCardLayout singleColumn maxWidth="2xl">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-slate-900">Demo login</h1>
          <p className="text-slate-600 text-sm mt-2">
            Demo uses a separate login flow and does not change normal signup/login behavior.
          </p>
          {postLoginNavigate && (
            <p className="text-slate-600 text-sm mt-2">
              {roleLockedToManager
                ? 'Sign in with demo to continue your property manager invitation.'
                : 'Sign in with demo to continue with this invitation.'}
            </p>
          )}
        </div>

        <Card className="mt-6 p-5">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Demo email (optional)</p>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#6B90F2]/30 focus:border-[#6B90F2]/40"
          />
          <p className="text-xs text-slate-500 mt-2">
            If you enter an email, the demo account will be created using that email (no password).
          </p>

          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Choose a role</p>
          <div className="grid grid-cols-2 gap-3">
            {(
              [
                { id: 'owner', label: 'Owner' },
                { id: 'property_manager', label: 'Property Manager' },
                { id: 'tenant', label: 'Tenant' },
                { id: 'guest', label: 'Guest' },
              ] as const
            ).map((r) => (
              <label
                key={r.id}
                className={`flex items-center gap-2 rounded-xl border px-4 py-3 transition-colors ${
                  roleLockedToManager && r.id !== 'property_manager'
                    ? 'opacity-50 cursor-not-allowed border-slate-100 bg-slate-50'
                    : `cursor-pointer ${role === r.id ? 'border-[#6B90F2]/60 bg-[#6B90F2]/10' : 'border-slate-200 hover:bg-slate-50'}`
                }`}
              >
                <input
                  type="radio"
                  name="demo_role"
                  value={r.id}
                  checked={roleLockedToManager ? r.id === 'property_manager' : role === r.id}
                  disabled={roleLockedToManager && r.id !== 'property_manager'}
                  onChange={() => setRole(r.id)}
                />
                <span className="text-sm font-medium text-slate-800">{r.label}</span>
              </label>
            ))}
          </div>

          <div className="mt-5 flex flex-col gap-3">
            <Button variant="primary" onClick={enterDemo} className="w-full">
              Enter demo
            </Button>
            <Button variant="outline" onClick={() => navigate('')} className="w-full">
              Back to landing
            </Button>
          </div>
        </Card>
      </AuthCardLayout>
    </HeroBackground>
  );
};

