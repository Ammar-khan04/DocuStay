import React, { useState, useEffect, useMemo } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout, AuthBullet } from '../../components/AuthCardLayout';
import { authApiGuest, invitationsApi } from '../../services/api';
import { STATE_OPTIONS } from '../../services/jleService';
import { validatePhone, sanitizePhoneInput } from '../../utils/validatePhone';
import AgreementSignModal, { type GuestInviteFormData } from '../../components/AgreementSignModal';

// Import city data
import US_CITIES_DATA from '@/data/us-cities.json';

const US_CITIES = US_CITIES_DATA as Record<string, string[]>;

interface GuestSignupProps {
  initialRole?: 'guest' | 'tenant';
  initialInviteCode?: string;
  setPendingVerification?: (data: { userId: string; type: 'email'; generatedAt: string }) => void;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onGuestLogin?: (user: any) => void;
  onTenantLogin?: (user: any) => void;
}

function inviteVerificationMessage(details: { expired?: boolean; used?: boolean; already_accepted?: boolean; revoked?: boolean; cancelled?: boolean; reason?: string }): string {
  if (details.expired)
    return 'This invitation has expired. Please ask your host for a new invitation.';
  if (details.used || details.already_accepted)
    return 'This invitation has already been accepted and cannot be used again. If you already registered, please sign in instead.';
  if ((details as any).revoked)
    return 'This invitation has been revoked by the property owner. Please contact your host for a new invitation.';
  if ((details as any).cancelled)
    return 'This invitation has been cancelled. Please contact your host for a new invitation.';
  if (details.reason === 'not_found')
    return 'This invitation code was not found. Please double-check the link or code and try again.';
  return 'This invitation link is invalid. Please check the link or contact your host.';
}

const parseInviteCode = (raw: string): string => {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const fromDemoHash = trimmed.includes('#demo/invite/') ? trimmed.split('#demo/invite/').pop() || '' : '';
  const fromHash = trimmed.includes('#invite/') ? trimmed.split('#invite/').pop() || '' : '';
  const fromPath = trimmed.includes('invite/') ? trimmed.split('invite/').pop() || '' : '';
  const code = (fromDemoHash || fromHash || fromPath || trimmed).split(/[?#]/)[0];
  return code.trim().toUpperCase();
};

const GuestSignup: React.FC<GuestSignupProps> = ({ initialRole, initialInviteCode, setPendingVerification, navigate, setLoading, notify, onGuestLogin, onTenantLogin }) => {
  const [role, setRole] = useState<'guest' | 'tenant'>(initialRole ?? 'guest');
  const [roleLocked, setRoleLocked] = useState(false);
  useEffect(() => {
    if (initialRole) setRole(initialRole);
  }, [initialRole]);
  const [inviteAcceptModalOpen, setInviteAcceptModalOpen] = useState(false);
  const [inviteAcceptCode, setInviteAcceptCode] = useState('');
  const [pendingInviteFormData, setPendingInviteFormData] = useState<GuestInviteFormData | null>(null);
  const [formData, setFormData] = useState({
    invitation_link: (initialInviteCode || '').trim(),
    full_name: '',
    email: '',
    phone: '',
    password: '',
    confirm_password: '',
    permanent_address: '',
    permanent_city: '',
    permanent_state: '',
    permanent_zip: '',
    terms_agreed: false,
    privacy_agreed: false,
    guest_status_acknowledged: false,
    no_tenancy_acknowledged: false,
    vacate_acknowledged: false,
  });
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });

  // Derive city options based on selected state
  const cityOptions = useMemo(() => {
    if (!formData.permanent_state) return [];
    const cities = US_CITIES[formData.permanent_state] || [];
    return cities.map(city => ({ value: city, label: city }));
  }, [formData.permanent_state]);

  useEffect(() => {
    const code = initialInviteCode || parseInviteCode(formData.invitation_link);
    if (!code || code.length < 5) {
      setRoleLocked(false);
      return;
    }
    invitationsApi.getDetails(code).then((d) => {
      if (!d.valid) return;
      const kind = d.invitation_kind || (d.is_tenant_invite ? 'tenant' : 'guest');
      if (kind === 'tenant') {
        setRole('tenant');
        setRoleLocked(true);
      } else {
        setRole('guest');
        setRoleLocked(true);
      }
    }).catch(() => {});
  }, [initialInviteCode, formData.invitation_link]);

  const showError = (message: string) => setErrorModal({ open: true, message });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const inviteCode = parseInviteCode(formData.invitation_link);
    const baseRequired = {
      full_name: formData.full_name.trim(),
      email: formData.email.trim(),
      phone: formData.phone.trim(),
      password: formData.password,
      confirm_password: formData.confirm_password,
    };
    const addressRequired =
      formData.permanent_address.trim() &&
      formData.permanent_city.trim() &&
      formData.permanent_state.trim() &&
      formData.permanent_zip.trim();
    const allFieldsFilled =
      Object.values(baseRequired).every(Boolean) &&
      (role === 'tenant' ? true : !!addressRequired);
    const guestAcksChecked =
      formData.guest_status_acknowledged &&
      formData.no_tenancy_acknowledged &&
      formData.vacate_acknowledged;
    const allCheckboxesChecked =
      formData.terms_agreed &&
      formData.privacy_agreed &&
      (role === 'tenant' ? true : guestAcksChecked);

    if (!allFieldsFilled || !allCheckboxesChecked) {
      showError(role === 'tenant'
        ? 'Please fill in all required fields and accept the Terms of Service and Privacy Policy.'
        : 'Please fill in all required fields and accept all acknowledgments and agreements before continuing.');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email.trim())) {
      showError('Please enter a valid email address.');
      return;
    }
    if (formData.password.length < 8) {
      showError('Password must be at least 8 characters.');
      return;
    }
    if (formData.password !== formData.confirm_password) {
      showError('Passwords do not match.');
      return;
    }
    const phoneCheck = validatePhone(formData.phone);
    if (!phoneCheck.valid) {
      showError(phoneCheck.error ?? 'Invalid phone number.');
      return;
    }
    if (inviteCode && inviteCode.length >= 5) {
      try {
        const inviteDetails = await invitationsApi.getDetails(inviteCode);
        if (!inviteDetails.valid) {
          showError(inviteVerificationMessage(inviteDetails));
          return;
        }
      } catch (err) {
        const msg = (err as Error)?.message ?? '';
        showError(msg || 'This invitation link could not be verified. Please check the link or sign up without it.');
        return;
      }
    }

    setLoading(true);
    try {
      const result = await authApiGuest.register({
        role,
        invitation_id: inviteCode,
        invitation_code: inviteCode,
        full_name: formData.full_name,
        email: formData.email,
        phone: formData.phone,
        password: formData.password,
        confirm_password: formData.confirm_password,
        permanent_address: formData.permanent_address || '',
        permanent_city: formData.permanent_city || '',
        permanent_state: formData.permanent_state || '',
        permanent_zip: formData.permanent_zip || '',
        terms_agreed: formData.terms_agreed,
        privacy_agreed: formData.privacy_agreed,
        guest_status_acknowledged: role === 'guest' ? formData.guest_status_acknowledged : false,
        no_tenancy_acknowledged: role === 'guest' ? formData.no_tenancy_acknowledged : false,
        vacate_acknowledged: role === 'guest' ? formData.vacate_acknowledged : false,
        agreement_signature_id: inviteCode ? 0 : null,
      });
      setLoading(false);
      if (result.status === 'success' && result.data) {
        const d = result.data as any;
        // Store invite code BEFORE any navigation so it's available after email verification
        if (inviteCode) sessionStorage.setItem('docustay_pending_invite_code', inviteCode);
        if (d.verificationRequired && d.user_id && setPendingVerification) {
          setPendingVerification({ userId: d.user_id, type: 'email', generatedAt: new Date().toISOString() });
          navigate('verify');
          return;
        }
        notify('success', role === 'tenant' ? 'Account created successfully.' : inviteCode ? 'Account created. Sign the agreement on your dashboard to accept the invitation.' : 'Account created successfully.');
        if (role === 'tenant' && onTenantLogin) onTenantLogin(result.data);
        else if (onGuestLogin) onGuestLogin(result.data);
        navigate(role === 'tenant' ? 'tenant-dashboard' : 'guest-dashboard');
      } else {
        showError(result.message || 'Registration failed. Please correct the errors and try again.');
      }
    } catch (err) {
      setLoading(false);
      const msg = (err as Error)?.message ?? 'Registration failed. Please try again.';
      showError(msg);
    }
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.checked });
  };

  return (
    <HeroBackground className="flex-grow flex flex-col items-center py-8">
      <AuthCardLayout maxWidth="7xl" minHeight="640px" leftPanel={
        <>
          <h2 className="text-2xl font-semibold text-slate-900 mb-3">Tenant / Guest Signup</h2>
          <p className="text-slate-600 text-sm mb-8">Create your account to access stays and invitations.</p>
          <ul className="space-y-3">
            <AuthBullet>Sign up as Guest or Tenant</AuthBullet>
            <AuthBullet>{role === 'tenant' ? 'Accept Terms of Service and Privacy Policy' : 'Add permanent residence details'}</AuthBullet>
            <AuthBullet>{role === 'tenant' ? 'Use platform to manage guest authorizations' : 'Accept guest stay acknowledgments (guests only)'}</AuthBullet>
          </ul>
        </>
      }>
          <div className="mb-8">
            <h1 className="text-2xl font-semibold text-slate-900 tracking-tight lg:hidden">Tenant / Guest Signup</h1>
            <p className="text-slate-600 mt-1 text-base">Create your account to get started.</p>
            <div className="mt-6">
              <span className="block text-sm font-medium text-slate-700 mb-3">Sign up as</span>
              <div className="grid grid-cols-2 gap-4">
                <label
                  className={`relative flex ${roleLocked ? 'cursor-default' : 'cursor-pointer'} flex-col items-center rounded-2xl border p-5 text-center transition-all duration-300 focus-within:ring-2 focus-within:ring-[#6B90F2]/40 focus-within:ring-offset-2 ${
                    role === 'tenant'
                      ? 'border-[#6B90F2]/40 bg-gradient-to-b from-[#6B90F2]/10 to-[#6B90F2]/5 shadow-[0_0_0_1px_rgba(107,144,242,0.12)]'
                      : 'border-slate-200/90 bg-slate-50/50 hover:border-slate-300 hover:bg-slate-50'
                  } ${roleLocked && role !== 'tenant' ? 'opacity-40 pointer-events-none' : ''}`}
                >
                  <input
                    type="radio"
                    name="role"
                    value="tenant"
                    checked={role === 'tenant'}
                    onChange={() => !roleLocked && setRole('tenant')}
                    disabled={roleLocked}
                    className="sr-only"
                  />
                  {role === 'tenant' && (
                    <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-[#6B90F2]/20">
                      <svg className="h-3 w-3 text-[#6B90F2]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    </span>
                  )}
                  <span className={`text-lg font-semibold ${role === 'tenant' ? 'text-[#6B90F2]' : 'text-slate-700'}`}>Tenant</span>
                  <span className={`mt-1 text-xs ${role === 'tenant' ? 'text-slate-600' : 'text-slate-500'}`}>Renting a property</span>
                </label>
                <label
                  className={`relative flex ${roleLocked ? 'cursor-default' : 'cursor-pointer'} flex-col items-center rounded-2xl border p-5 text-center transition-all duration-300 focus-within:ring-2 focus-within:ring-[#6B90F2]/40 focus-within:ring-offset-2 ${
                    role === 'guest'
                      ? 'border-[#6B90F2]/40 bg-gradient-to-b from-[#6B90F2]/10 to-[#6B90F2]/5 shadow-[0_0_0_1px_rgba(107,144,242,0.12)]'
                      : 'border-slate-200/90 bg-slate-50/50 hover:border-slate-300 hover:bg-slate-50'
                  } ${roleLocked && role !== 'guest' ? 'opacity-40 pointer-events-none' : ''}`}
                >
                  <input
                    type="radio"
                    name="role"
                    value="guest"
                    checked={role === 'guest'}
                    onChange={() => !roleLocked && setRole('guest')}
                    disabled={roleLocked}
                    className="sr-only"
                  />
                  {role === 'guest' && (
                    <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-[#6B90F2]/20">
                      <svg className="h-3 w-3 text-[#6B90F2]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    </span>
                  )}
                  <span className={`text-lg font-semibold ${role === 'guest' ? 'text-[#6B90F2]' : 'text-slate-700'}`}>Guest</span>
                  <span className={`mt-1 text-xs ${role === 'guest' ? 'text-slate-600' : 'text-slate-500'}`}>Short-term stay</span>
                </label>
              </div>
              {roleLocked && (
                <p className="mt-3 text-xs text-slate-500 italic">
                  Role is determined by your invitation and cannot be changed.
                </p>
              )}
            </div>
          </div>
          <div className="p-0">
            <form onSubmit={handleSubmit} className="grid md:grid-cols-2 gap-x-10 gap-y-6">
              <div className="md:col-span-2">
                <Input
                  label="Invitation link (optional, for guests)"
                  name="invitation_link"
                  value={formData.invitation_link}
                  onChange={e => setFormData({ ...formData, invitation_link: e.target.value })}
                  placeholder="Paste invitation link or code if you have one"
                />
                {role === 'guest' && (initialInviteCode || parseInviteCode(formData.invitation_link).length >= 5) && (
                  <div className="mt-3">
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full md:w-auto"
                      onClick={() => {
                        const code = initialInviteCode || parseInviteCode(formData.invitation_link);
                        if (code) {
                          setInviteAcceptCode(code);
                          setInviteAcceptModalOpen(true);
                        }
                      }}
                    >
                      Accept this invitation (property address + your details + sign)
                    </Button>
                  </div>
                )}
              </div>
              <div>
                <h3 className="text-sm font-semibold text-slate-900 mb-4 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-[#6B90F2]/20 text-[#6B90F2] flex items-center justify-center text-xs font-medium">1</span>
                  Guest Profile
                </h3>
                <div className="space-y-4">
                  <Input label="Full name" name="full_name" value={formData.full_name} onChange={e => setFormData({ ...formData, full_name: e.target.value })} required />
                  <Input label="Email Address" name="email" type="email" value={formData.email} onChange={e => setFormData({ ...formData, email: e.target.value })} required />
                  <Input label="Phone Number" name="phone" value={formData.phone} onChange={e => setFormData({ ...formData, phone: sanitizePhoneInput(e.target.value) })} placeholder="+15551234567 or 5551234567" required />
                  <div className="grid grid-cols-2 gap-4">
                    <Input label="Password" name="password" type="password" value={formData.password} onChange={e => setFormData({ ...formData, password: e.target.value })} required />
                    <Input label="Confirm" name="confirm_password" type="password" value={formData.confirm_password} onChange={e => setFormData({ ...formData, confirm_password: e.target.value })} required />
                  </div>
                </div>
              </div>

              {role === 'guest' && (
              <div>
                <h3 className="text-sm font-semibold text-slate-900 mb-4 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-[#6B90F2]/20 text-[#6B90F2] flex items-center justify-center text-xs font-medium">2</span>
                  Permanent Residence
                </h3>
                <p className="text-xs text-slate-500 mb-4">Required to confirm you have a primary residence elsewhere.</p>
                <div className="space-y-4">
                  <Input label="Street Address" name="permanent_address" value={formData.permanent_address} onChange={e => setFormData({ ...formData, permanent_address: e.target.value })} placeholder="Your actual home address" required />
                  <div className="grid grid-cols-2 gap-4">
                    <Input
                      label="State" name="permanent_state" value={formData.permanent_state}
                      onChange={e => {
                        const newState = e.target.value;
                        setFormData({
                          ...formData,
                          permanent_state: newState,
                          permanent_city: '' // Reset city when state changes
                        });
                      }}
                      options={STATE_OPTIONS}
                      required
                    />
                    <Input
                      label="City" name="permanent_city" value={formData.permanent_city}
                      onChange={e => setFormData({ ...formData, permanent_city: e.target.value })}
                      placeholder={formData.permanent_state ? "Select City" : "Select State first"}
                      options={cityOptions}
                      disabled={!formData.permanent_state}
                      required
                    />
                  </div>
                  <Input label="ZIP Code" name="permanent_zip" value={formData.permanent_zip} onChange={e => setFormData({ ...formData, permanent_zip: e.target.value })} required />
                </div>
              </div>
              )}

              <div className={`md:col-span-2 mt-8 ${role === 'tenant' ? '' : ''}`}>
                <h3 className="text-sm font-semibold text-slate-900 mb-4 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-[#6B90F2]/20 text-[#6B90F2] flex items-center justify-center text-xs font-medium">{role === 'tenant' ? 2 : 3}</span>
                  {role === 'tenant' ? 'Agreements' : 'Stay acknowledgments'}
                </h3>
                {role === 'guest' && (
                <div className="grid md:grid-cols-3 gap-4 mb-6">
                  {[
                    { name: 'guest_status_acknowledged', label: 'Temporary Guest Status', desc: 'I acknowledge I am a guest only, not a tenant or resident.' },
                    { name: 'no_tenancy_acknowledged', label: 'Temporary stay', desc: 'I acknowledge this stay is temporary and does not grant tenancy.' },
                    { name: 'vacate_acknowledged', label: 'Agreement to Vacate', desc: 'I agree to vacate by the scheduled checkout date.' },
                  ].map(ack => (
                    <div key={ack.name} className={`p-4 rounded-lg border ${formData[ack.name as keyof typeof formData] ? 'bg-slate-50 border-slate-300' : 'bg-white border-slate-200'}`}>
                      <label className="flex flex-col gap-2 cursor-pointer h-full">
                        <div className="flex justify-between items-start">
                          <span className="text-sm font-medium text-slate-900">{ack.label}</span>
                          <input type="checkbox" name={ack.name} checked={!!formData[ack.name as keyof typeof formData]} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 text-[#6B90F2] focus:ring-[#6B90F2] shrink-0 mt-0.5" required />
                        </div>
                        <p className="text-xs text-gray-500 leading-relaxed">{ack.desc}</p>
                      </label>
                    </div>
                  ))}
                </div>
                )}

                <div className={`pt-6 ${role === 'guest' ? 'border-t border-slate-200' : ''} space-y-3`}>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">Agreements</p>
                  <label className="flex items-start gap-4 cursor-pointer p-4 rounded-xl border border-slate-200 bg-white/80 hover:border-slate-300 hover:bg-white transition-colors focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2 focus-within:border-blue-400">
                    <input type="checkbox" name="terms_agreed" checked={formData.terms_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0 shrink-0 mt-0.5 accent-blue-600" required />
                    <span className="text-sm text-slate-700 leading-relaxed">
                      I agree to the <a href="#terms" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-semibold hover:text-[#5a7ed9] hover:underline underline-offset-2 transition-colors">Terms of Service</a>.
                    </span>
                  </label>
                  <label className="flex items-start gap-4 cursor-pointer p-4 rounded-xl border border-slate-200 bg-white/80 hover:border-slate-300 hover:bg-white transition-colors focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2 focus-within:border-blue-400">
                    <input type="checkbox" name="privacy_agreed" checked={formData.privacy_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0 shrink-0 mt-0.5 accent-blue-600" required />
                    <span className="text-sm text-slate-700 leading-relaxed">
                      I agree to the <a href="#privacy" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-semibold hover:text-[#5a7ed9] hover:underline underline-offset-2 transition-colors">Privacy Policy</a>.
                    </span>
                  </label>
                </div>

                <div className="mt-8 flex flex-col items-center gap-1">
                  <Button type="submit" className="w-full md:min-w-[200px] py-3">
                    {role === 'tenant' ? 'Create Tenant Account' : 'Create Guest Account'}
                  </Button>
                  <p className="mt-4 text-center text-slate-500 text-sm">
                    Already have an account?{' '}
                    {role === 'tenant' ? (
                      <button type="button" onClick={() => navigate('login/tenant')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">Tenant login</button>
                    ) : (
                      <button type="button" onClick={() => navigate('guest-login')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">Guest login</button>
                    )}
                  </p>
                </div>
              </div>
            </form>
          </div>
      </AuthCardLayout>

      {inviteAcceptCode && (
        <AgreementSignModal
          open={inviteAcceptModalOpen}
          invitationCode={inviteAcceptCode}
          guestEmail=""
          guestFullName=""
          onClose={() => {
            setInviteAcceptModalOpen(false);
            setInviteAcceptCode('');
            setPendingInviteFormData(null);
          }}
          onSigned={async (signatureId) => {
            if (!pendingInviteFormData || !inviteAcceptCode) return;
            const code = inviteAcceptCode.trim().toUpperCase();
            const isTenant = pendingInviteFormData.isTenantInvite;
            setLoading(true);
            try {
              const result = await authApiGuest.register({
                ...pendingInviteFormData,
                role: isTenant ? 'tenant' : 'guest',
                invitation_id: code,
                invitation_code: code,
                agreement_signature_id: signatureId,
                guest_status_acknowledged: isTenant ? false : true,
                no_tenancy_acknowledged: isTenant ? false : true,
                vacate_acknowledged: isTenant ? false : true,
              });
              setLoading(false);
              setInviteAcceptModalOpen(false);
              setInviteAcceptCode('');
              setPendingInviteFormData(null);
              if (result.status === 'success' && result.data) {
                const d = result.data as any;
                if (d.verificationRequired && d.user_id && setPendingVerification) {
                  setPendingVerification({ userId: d.user_id, type: 'email', generatedAt: new Date().toISOString() });
                  navigate('verify');
                  return;
                }
                notify('success', 'Registration successful!');
                if (isTenant && onTenantLogin) onTenantLogin(result.data);
                else if (onGuestLogin) onGuestLogin(result.data);
                navigate(isTenant ? 'tenant-dashboard' : 'guest-dashboard');
              } else {
                notify('error', result.message || 'Registration failed.');
              }
            } catch (err) {
              setLoading(false);
              notify('error', (err as Error)?.message || 'Registration failed.');
            }
          }}
          notify={notify}
          inviteAcceptMode
          onContinueToSign={async (formData) => {
            if (formData.isTenantInvite) {
              const code = inviteAcceptCode.trim().toUpperCase();
              setLoading(true);
              try {
                const result = await authApiGuest.register({
                  ...formData,
                  role: 'tenant',
                  invitation_id: code,
                  invitation_code: code,
                  agreement_signature_id: null,
                  guest_status_acknowledged: false,
                  no_tenancy_acknowledged: false,
                  vacate_acknowledged: false,
                });
                setLoading(false);
                setInviteAcceptModalOpen(false);
                setInviteAcceptCode('');
                setPendingInviteFormData(null);
                if (result.status === 'success' && result.data) {
                  const d = result.data as any;
                  if (d.verificationRequired && d.user_id && setPendingVerification) {
                    setPendingVerification({ userId: d.user_id, type: 'email', generatedAt: new Date().toISOString() });
                    navigate('verify');
                    return;
                  }
                  notify('success', 'Registration successful!');
                  if (onTenantLogin) onTenantLogin(result.data);
                  navigate('tenant-dashboard');
                } else {
                  notify('error', result.message || 'Registration failed.');
                }
              } catch (err) {
                setLoading(false);
                notify('error', (err as Error)?.message || 'Registration failed.');
              }
            } else {
              setPendingInviteFormData(formData);
            }
          }}
        />
      )}

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
      />
    </HeroBackground>
  );
};

export default GuestSignup;
