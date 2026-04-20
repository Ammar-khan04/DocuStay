import React, { useState, useEffect } from 'react';
import { Input, Button, ErrorModal, SuccessModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout, AuthBullet } from '../../components/AuthCardLayout';
import { authApi, invitationsApi, propertiesApi, DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY } from '../../services/api';
import { PENDING_INVITE_STORAGE_KEY } from '../Guest/GuestLogin';

const parseInviteCode = (raw: string): string => {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromDemoHash = trimmed.includes('#demo/invite/') ? trimmed.split('#demo/invite/').pop() || '' : '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromDemoHash || fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
};

interface LoginProps {
  onLogin: (user: any) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  navigate: (v: string) => void;
  initialRole?: 'owner' | 'property_manager' | 'tenant' | 'guest';
  managerInviteToken?: string;
  propertyTransferToken?: string;
}

type LoginRole = "owner" | "property_manager" | "tenant" | "guest";

const Login: React.FC<LoginProps> = ({
  onLogin,
  setLoading,
  notify,
  navigate,
  initialRole = 'owner',
  managerInviteToken,
  propertyTransferToken,
}) => {
  const [formData, setFormData] = useState({ email: '', password: '', role: initialRole as LoginRole, invitation_link: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [inviteCheck, setInviteCheck] = useState<{ loading: boolean; valid: boolean; expired?: boolean; used?: boolean } | null>(null);
  const [managerInviteInfo, setManagerInviteInfo] = useState<{ property_name: string } | null>(null);
  const [propertyTransferInviteInfo, setPropertyTransferInviteInfo] = useState<{ property_name: string } | null>(null);
  useEffect(() => {
    setFormData((prev) => ({ ...prev, role: initialRole as LoginRole }));
  }, [initialRole]);
  useEffect(() => {
    const pt = (propertyTransferToken || '').trim();
    if (!pt) {
      setPropertyTransferInviteInfo(null);
      return;
    }
    setFormData((prev) => ({ ...prev, role: 'owner' }));
    authApi
      .getPropertyTransferInvite(pt)
      .then((d) => {
        if (d.is_demo && pt) {
          navigate(`demo/property-transfer/${pt}`);
          return;
        }
        setFormData((prev) => ({ ...prev, email: d.email }));
        setPropertyTransferInviteInfo({ property_name: d.property_name });
      })
      .catch(() => setPropertyTransferInviteInfo(null));
  }, [propertyTransferToken, navigate]);
  useEffect(() => {
    if (managerInviteToken && initialRole === 'property_manager') {
      authApi.getManagerInvite(managerInviteToken)
        .then((d) => {
          if (d.is_demo && managerInviteToken) {
            navigate(`demo/register/manager/${managerInviteToken}`);
            return;
          }
          setFormData((prev) => ({ ...prev, email: d.email }));
          setManagerInviteInfo({ property_name: d.property_name });
        })
        .catch(() => setManagerInviteInfo(null));
    } else {
      setManagerInviteInfo(null);
    }
  }, [managerInviteToken, initialRole, navigate]);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });
  const [successModal, setSuccessModal] = useState<{ open: boolean; message: string; user?: any }>({ open: false, message: '' });

  const inviteCode = parseInviteCode(formData.invitation_link);

  useEffect(() => {
    if (formData.role !== 'tenant' || !inviteCode || inviteCode.length < 5) {
      if (!inviteCode) setInviteCheck(null);
      return;
    }
    setInviteCheck((prev) => (prev?.valid === true && !prev?.expired ? prev : { loading: true, valid: true }));
    invitationsApi.getDetails(inviteCode)
      .then((d) => {
        if (d.valid && d.is_demo && inviteCode) {
          navigate(`demo/invite/${inviteCode}`);
          return;
        }
        setInviteCheck({ loading: false, valid: d.valid, expired: d.expired, used: d.used });
      })
      .catch(() => setInviteCheck({ loading: false, valid: false }));
  }, [inviteCode, formData.role, navigate]);

  const showError = (message: string) => setErrorModal({ open: true, message });

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
    if (formData.role === 'tenant' && inviteCode && inviteCheck?.valid === false) {
      showError(
        inviteCheck?.expired ? 'This invitation has expired and cannot be used. Ask your host for a new invitation.'
        : inviteCheck?.used ? 'This invitation link has already been used.'
        : 'This invitation link is invalid.'
      );
      return;
    }
    setLoading(true);
    try {
      const apiRole = formData.role;
      const result = await authApi.login(email, password, apiRole);
      if (result.status === 'success' && result.data) {
        if (formData.role === 'property_manager' && managerInviteToken) {
          try {
            await authApi.acceptManagerInvite(managerInviteToken);
            const propertyName = managerInviteInfo?.property_name || 'the property';
            setLoading(false);
            setSuccessModal({
              open: true,
              message: `You have been successfully assigned to manage ${propertyName}.`,
              user: result.data,
            });
          } catch (acceptErr) {
            notify('error', (acceptErr as Error)?.message ?? 'Failed to accept invitation.');
            setLoading(false);
            onLogin(result.data);
            return;
          }
        } else if (formData.role === 'owner' && propertyTransferToken) {
          try {
            try {
              sessionStorage.setItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY, propertyTransferToken);
            } catch {
              /* ignore */
            }
            const transferRes = await propertiesApi.acceptPropertyTransfer(propertyTransferToken);
            try {
              sessionStorage.removeItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY);
            } catch {
              /* ignore */
            }
            setLoading(false);
            const p = transferRes?.property;
            const line =
              p &&
              `${p.name?.trim() || "this property"}${p.address ? ` (${p.address})` : p.city || p.state ? ` (${[p.street, p.city, p.state].filter(Boolean).join(", ")})` : ""}`;
            notify(
              "success",
              line ? `You are now the owner of ${line} in DocuStay.` : "You are now the owner of this property in DocuStay.",
            );
            onLogin(result.data);
            return;
          } catch (acceptErr) {
            const raw = ((acceptErr as Error)?.message || '').toLowerCase();
            if (raw.includes('not found') || raw.includes('expired') || raw.includes('no longer valid')) {
              try {
                sessionStorage.removeItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY);
              } catch {
                /* ignore */
              }
              notify('error', (acceptErr as Error)?.message ?? 'This transfer link is no longer valid.');
            }
          }
        } else if (formData.role === 'tenant' && inviteCode && inviteCheck?.valid !== false) {
          sessionStorage.setItem(PENDING_INVITE_STORAGE_KEY, inviteCode.trim().toUpperCase());
          notify('success', 'Signed in. You can sign the invitation agreement on your dashboard.');
        } else if (!managerInviteToken && !propertyTransferToken) {
          notify('success', 'Logged in successfully.');
        } else if (propertyTransferToken && formData.role === 'owner') {
          notify('success', 'Signed in. Finish any onboarding steps, then accept the ownership transfer from your dashboard.');
        }
        setLoading(false);
        if (!(formData.role === 'property_manager' && managerInviteToken)) {
          onLogin(result.data);
        }
      } else {
        setLoading(false);
        showError(result.message || 'Login failed. Please check your email and password.');
      }
    } catch (err) {
      setLoading(false);
      showError((err as Error)?.message || 'Login failed. Please try again.');
    }
  };

  const roleTitle = formData.role === 'owner' ? 'Owner login' : formData.role === 'property_manager' ? 'Property Manager login' : formData.role === 'tenant' ? 'Tenant login' : 'Guest login';

  return (
    <HeroBackground className="flex-grow">
      <AuthCardLayout
        leftPanel={
          <>
            <h2 className="text-2xl font-semibold text-slate-900 mb-3">{roleTitle}</h2>
            <p className="text-slate-600 text-sm mb-8">
              {formData.role === 'guest' ? 'Access your stays and invitations.' : 'Manage properties, invitations, and stays in one place.'}
            </p>
            <ul className="space-y-3">
              <AuthBullet>Jurisdiction-aware agreements</AuthBullet>
              <AuthBullet>Guest verification</AuthBullet>
              <AuthBullet>Stay documentation</AuthBullet>
            </ul>
          </>
        }
      >
          <div className="max-w-sm mx-auto w-full">
            <h1 className="text-xl font-semibold text-slate-900 mb-1 lg:hidden">{roleTitle}</h1>
            <p className="text-slate-600 text-sm mb-6">
              {managerInviteInfo ? (
                <>Sign in to accept your invitation to manage <strong>{managerInviteInfo.property_name}</strong>.</>
              ) : propertyTransferInviteInfo ? (
                <>
                  Sign in as an owner with the invited email to accept ownership of{' '}
                  <strong>{propertyTransferInviteInfo.property_name}</strong>.
                </>
              ) : (
                'Sign in to your account.'
              )}
            </p>
            
            <form onSubmit={handleSubmit} className="space-y-6">
              <Input
                label="Sign in as"
                name="role"
                value={formData.role}
                onChange={e => setFormData({ ...formData, role: e.target.value as LoginRole })}
                options={[
                  { value: 'owner', label: 'Owner' },
                  { value: 'property_manager', label: 'Property Manager' },
                  { value: 'tenant', label: 'Tenant' },
                  { value: 'guest', label: 'Guest' },
                ]}
                disabled={Boolean(propertyTransferToken)}
              />
              {formData.role === 'tenant' && (
                <Input
                  label="Invitation link (optional)"
                  name="invitation_link"
                  value={formData.invitation_link}
                  onChange={e => setFormData({ ...formData, invitation_link: e.target.value })}
                  placeholder="Paste invitation link or code if you have one"
                />
              )}
              <Input 
                label="Work Email" 
                name="email" 
                type="email" 
                value={formData.email} 
                onChange={e => setFormData({ ...formData, email: e.target.value })} 
                placeholder="name@company.com"
                required
              />
              <div className="relative">
                <Input 
                  label="Password" 
                  name="password" 
                  type={showPassword ? "text" : "password"} 
                  value={formData.password} 
                  onChange={e => setFormData({ ...formData, password: e.target.value })} 
                  placeholder="••••••••"
                  required
                />
                <button 
                  type="button" 
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-[34px] text-slate-400 hover:text-slate-600 transition-colors"
                >
                  {showPassword ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18"></path></svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                  )}
                </button>
              </div>
              
              <div className="flex items-center justify-between text-sm">
                <label className="flex items-center gap-2 cursor-pointer text-slate-600">
                  <input type="checkbox" className="w-4 h-4 rounded border-slate-300 text-[#6B90F2] focus:ring-[#6B90F2]" />
                  Remember me
                </label>
                <button type="button" onClick={() => navigate('forgot-password/owner')} className="text-[#6B90F2] hover:text-[#5a7ed9] font-medium">Forgot password?</button>
              </div>
              
              <Button type="submit" className="w-full py-2.5">Sign in</Button>
            </form>

            <div className="mt-8 space-y-2 text-center text-slate-500 text-sm">
              {(formData.role === 'owner') && (
                <p>
                  Don&apos;t have an account?{' '}
                  <button type="button" onClick={() => navigate('register')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">
                    Register as Owner
                  </button>
                </p>
              )}
              {formData.role === 'property_manager' && (
                <p>
                  Don&apos;t have an account? Property managers receive invitations from property owners. Check your email for an invite link to register, or ask your property owner to send you an invitation.
                </p>
              )}
              {formData.role === 'tenant' && (
                <p>
                  Don&apos;t have an account?{' '}
                  <button type="button" onClick={() => navigate('guest-signup/tenant')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">Register as Tenant</button>
                </p>
              )}
              {formData.role === 'guest' && (
                <p>
                  Don&apos;t have an account?{' '}
                  <button type="button" onClick={() => navigate('guest-signup')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">Guest Signup</button>
                </p>
              )}
            </div>
          </div>
      </AuthCardLayout>

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
      />
      <SuccessModal
        open={successModal.open}
        title="Property Assigned Successfully"
        message={successModal.message}
        onClose={() => {
          if (successModal.user) onLogin(successModal.user);
          setSuccessModal({ open: false, message: '' });
        }}
      />
    </HeroBackground>
  );
};

export default Login;
