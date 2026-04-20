import React, { useState, useEffect, useMemo } from 'react';
import { Input, Button } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { authApiGuest, invitationsApi, isPropertyTenantInviteKind, type InvitationDetails } from '../../services/api';
import { STATE_OPTIONS } from '../../services/jleService';
import { validatePhone, sanitizePhoneInput } from '../../utils/validatePhone';
import { UserSession } from '../../types';
import AgreementSignModal from '../../components/AgreementSignModal';
import { formatCalendarDate } from '../../utils/dateUtils';

// Import city data
import US_CITIES_DATA from '@/data/us-cities.json';

const US_CITIES = US_CITIES_DATA as Record<string, string[]>;

interface Props {
  invitationId: string;
  sessionIsDemo?: boolean;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  setPendingVerification: (data: any) => void;
  onGuestLogin?: (user: UserSession) => void;
  onTenantLogin?: (user: UserSession) => void;
}

const RegisterFromInvite: React.FC<Props> = ({
  invitationId,
  sessionIsDemo = false,
  navigate,
  setLoading,
  notify,
  setPendingVerification,
  onGuestLogin,
  onTenantLogin,
}) => {
  const [inviteDetails, setInviteDetails] = useState<InvitationDetails | null>(null);
  const [inviteLoading, setInviteLoading] = useState(true);
  const normalizedCode = invitationId.trim().toUpperCase();
  const isTenantInvite =
    isPropertyTenantInviteKind(inviteDetails?.invitation_kind) || Boolean(inviteDetails?.is_tenant_invite);
  const [agreementOpen, setAgreementOpen] = useState(false);
  const [agreementSignatureId, setAgreementSignatureId] = useState<number | null>(null);
  const [formData, setFormData] = useState({
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
    vacate_acknowledged: false
  });

  // Derive city options based on selected state
  const cityOptions = useMemo(() => {
    if (!formData.permanent_state) return [];
    const cities = US_CITIES[formData.permanent_state] || [];
    return cities.map(city => ({ value: city, label: city }));
  }, [formData.permanent_state]);

  const invitedEmail = (inviteDetails?.guest_email || '').trim();
  const emailLockedToInvite = Boolean(invitedEmail) && !isTenantInvite;

  useEffect(() => {
    if (!inviteDetails?.valid || !invitedEmail) return;
    setFormData((prev) => ({ ...prev, email: invitedEmail }));
  }, [inviteDetails?.valid, invitedEmail]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const baseRequired =
      formData.full_name.trim() &&
      formData.email.trim() &&
      formData.phone.trim() &&
      formData.password &&
      formData.confirm_password;
    const addressRequired =
      formData.permanent_address.trim() &&
      formData.permanent_city.trim() &&
      formData.permanent_state.trim() &&
      formData.permanent_zip.trim();
    const requiredFilled = isTenantInvite ? baseRequired : baseRequired && addressRequired;
    const guestAcksChecked =
      formData.guest_status_acknowledged &&
      formData.no_tenancy_acknowledged &&
      formData.vacate_acknowledged;
    const allCheckboxesChecked =
      formData.terms_agreed &&
      formData.privacy_agreed &&
      (isTenantInvite ? true : guestAcksChecked);
    if (!requiredFilled || !allCheckboxesChecked) {
      notify('error', isTenantInvite
        ? 'Please fill in all required fields and accept the Terms of Service and Privacy Policy.'
        : 'Please fill in all required fields and accept all acknowledgments and agreements before continuing.');
      return;
    }
    if (!isTenantInvite && !agreementSignatureId) {
      notify('error', 'You must review and sign the agreement to continue.');
      setAgreementOpen(true);
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email.trim())) {
      notify('error', 'Please enter a valid email address.');
      return;
    }
    if (formData.password.length < 8) {
      notify('error', 'Password must be at least 8 characters.');
      return;
    }
    if (formData.password !== formData.confirm_password) {
      notify('error', 'Passwords do not match.');
      return;
    }
    const phoneCheck = validatePhone(formData.phone);
    if (!phoneCheck.valid) {
      notify('error', phoneCheck.error ?? 'Invalid phone number.');
      return;
    }
    setLoading(true);
    try {
      const result = await authApiGuest.register({
        role: isTenantInvite ? 'tenant' : 'guest',
        invitation_id: normalizedCode,
        invitation_code: normalizedCode,
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
        guest_status_acknowledged: isTenantInvite ? false : formData.guest_status_acknowledged,
        no_tenancy_acknowledged: isTenantInvite ? false : formData.no_tenancy_acknowledged,
        vacate_acknowledged: isTenantInvite ? false : formData.vacate_acknowledged,
        agreement_signature_id: isTenantInvite ? null : agreementSignatureId,
      });
      setLoading(false);
      if (result.status === 'success' && result.data) {
        const d = result.data as any;
        if (d.verificationRequired && d.user_id && setPendingVerification) {
          // Save invite code so TenantDashboard can process it after email verification.
          // For pre-signed flow this lets the dashboard detect the invite was accepted; for
          // non-signed flow it triggers the signing modal.
          if (normalizedCode) sessionStorage.setItem('docustay_pending_invite_code', normalizedCode);
          setPendingVerification({ userId: d.user_id, type: 'email', generatedAt: new Date().toISOString() });
          navigate('verify');
          return;
        }
        notify('success', 'Registration successful!');
        if (isTenantInvite && onTenantLogin) {
          onTenantLogin(result.data);
          navigate('tenant-dashboard');
        } else if (onGuestLogin) {
          onGuestLogin(result.data);
          navigate('guest-dashboard');
        } else {
          navigate(isTenantInvite ? 'tenant-dashboard' : 'guest-dashboard');
        }
      } else {
        notify('error', result.message || 'Registration failed.');
      }
    } catch (err) {
      setLoading(false);
      notify('error', (err as Error)?.message || 'Registration failed.');
    }
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.checked });
  };

  useEffect(() => {
    if (!normalizedCode) {
      setInviteLoading(false);
      setInviteDetails({ valid: false });
      return;
    }
    invitationsApi.getDetails(normalizedCode)
      .then((d) => {
        if (d.valid && d.is_demo && !sessionIsDemo) {
          navigate(`demo/invite/${normalizedCode}`);
          return;
        }
        setInviteDetails(d);
        if (!d.valid) {
          if (d.expired) notify('error', 'This invitation has expired. Please ask your host for a new invitation.');
          else if (d.used || d.already_accepted) notify('error', 'This invitation has already been accepted. If you already registered, please sign in instead.');
          else if (d.revoked) notify('error', 'This invitation has been revoked by the property owner. Please contact your host.');
          else if (d.cancelled) notify('error', 'This invitation has been cancelled. Please contact your host.');
          else if (d.reason === 'not_found') notify('error', 'This invitation code was not found. Please double-check the link or code.');
          else notify('error', 'This invitation link is invalid. Please check the link or contact your host.');
        }
      })
      .catch((err) => {
        setInviteDetails({ valid: false });
        const msg = (err as Error)?.message ?? '';
        notify('error', msg || 'Could not verify invitation. Please check the link and try again.');
      })
      .finally(() => setInviteLoading(false));
  }, [normalizedCode, notify, navigate, sessionIsDemo]);

  if (inviteLoading) {
    return (
      <HeroBackground className="flex-grow">
        <div className="max-w-4xl mx-auto w-full rounded-2xl bg-white/80 backdrop-blur-md border border-slate-200/80 shadow-xl p-10">
          <p className="text-slate-600">Loading invitation…</p>
        </div>
      </HeroBackground>
    );
  }
  if (inviteDetails && !inviteDetails.valid) {
    return (
      <HeroBackground className="flex-grow">
        <div className="max-w-4xl mx-auto w-full rounded-2xl bg-white/80 backdrop-blur-md border border-slate-200/80 shadow-xl p-8 text-center">
          <p className="text-slate-600 mb-4">
            {inviteDetails.expired
              ? 'This invitation has expired (it was not accepted in time). Please ask your host for a new invitation.'
              : inviteDetails.used || inviteDetails.already_accepted
                ? 'This invitation has already been accepted and cannot be used again. If you already registered, please sign in instead.'
                : inviteDetails.revoked
                  ? 'This invitation has been revoked by the property owner. Please contact your host for a new invitation.'
                  : inviteDetails.cancelled
                    ? 'This invitation has been cancelled. Please contact your host for a new invitation.'
                    : inviteDetails.reason === 'not_found'
                      ? 'This invitation code was not found. Please double-check the link or code.'
                      : 'This invitation link is invalid. Please check the link or contact your host.'}
          </p>
          <button onClick={() => navigate(isTenantInvite ? 'guest-signup/tenant' : 'guest-signup')} className="text-[#6B90F2] hover:text-[#5a7ed9] font-medium underline underline-offset-2">Enter a different code</button>
        </div>
      </HeroBackground>
    );
  }

  return (
    <HeroBackground className="flex-grow">
      <div className="max-w-4xl mx-auto w-full rounded-2xl overflow-hidden bg-white/80 backdrop-blur-md border border-slate-200/80 shadow-xl">
        {/* Invitation Banner */}
        <div className="bg-gradient-to-r from-slate-800 to-slate-900 p-8 md:p-12 text-white relative">
           <div className="absolute top-0 right-0 w-64 h-full bg-[#6B90F2]/20 blur-[60px] rounded-full"></div>
           <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-8">
              <div>
                 <span className="inline-block px-3 py-1 rounded-full bg-[#6B90F2]/30 text-blue-300 text-xs font-bold uppercase tracking-widest mb-4">{isTenantInvite ? 'Tenant Invitation' : 'Official Invitation'}</span>
                 <h1 className="text-4xl font-extrabold mb-2">{isTenantInvite ? "You're Invited as a Tenant." : "You're Invited to Stay."}</h1>
                 <p className="text-slate-300 text-lg">Hosted by <span className="text-white font-bold">{inviteDetails?.host_name || 'Your host'}</span></p>
              </div>
              <div className="bg-white/10 backdrop-blur-md rounded-2xl p-6 border border-white/10 min-w-[280px]">
                 <div className="flex items-center gap-3 mb-4">
                    <svg className="w-5 h-5 text-[#6B90F2]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                    <span className="font-bold">{inviteDetails?.property_name || 'Property'}</span>
                 </div>
                 <div className="grid grid-cols-2 gap-4 text-xs font-medium text-slate-300">
                    <div>
                       <p className="uppercase tracking-widest mb-1 opacity-60">{isTenantInvite ? 'Start date' : 'Check-in'}</p>
                       <p className="text-white text-sm">{formatCalendarDate(inviteDetails?.stay_start_date)}</p>
                    </div>
                    <div>
                       <p className="uppercase tracking-widest mb-1 opacity-60">{isTenantInvite ? 'End date' : 'Check-out'}</p>
                       <p className="text-white text-sm">{formatCalendarDate(inviteDetails?.stay_end_date)}</p>
                    </div>
                 </div>
              </div>
           </div>
        </div>

        <div className="p-8 md:p-12 bg-slate-50/90 backdrop-blur-sm">
          <form onSubmit={handleSubmit} className="grid md:grid-cols-2 gap-x-12 gap-y-2">
            <div>
              <h3 className="text-2xl font-bold text-slate-800 mb-6 flex items-center gap-2">
                 <div className="w-8 h-8 rounded-full bg-[#6B90F2]/20 flex items-center justify-center text-[#6B90F2] text-sm font-bold">1</div>
                 {isTenantInvite ? 'Your details' : 'Guest Profile'}
              </h3>
              <div className="space-y-4">
                <Input label="Full name" name="full_name" value={formData.full_name} onChange={e => setFormData({...formData, full_name: e.target.value})} required />
                <Input
                  label="Email Address"
                  name="email"
                  type="email"
                  value={formData.email}
                  onChange={e => setFormData({ ...formData, email: e.target.value })}
                  required
                  readOnly={emailLockedToInvite}
                />
                {emailLockedToInvite && (
                  <p className="text-xs text-slate-500 -mt-2">Use the address this invitation was sent to.</p>
                )}
                <Input label="Phone Number" name="phone" value={formData.phone} onChange={e => setFormData({...formData, phone: sanitizePhoneInput(e.target.value)})} placeholder="+15551234567 or 5551234567" required />
                <div className="grid grid-cols-2 gap-4">
                   <Input label="Password" name="password" type="password" value={formData.password} onChange={e => setFormData({...formData, password: e.target.value})} required />
                   <Input label="Confirm" name="confirm_password" type="password" value={formData.confirm_password} onChange={e => setFormData({...formData, confirm_password: e.target.value})} required />
                </div>
              </div>
            </div>

            {!isTenantInvite && (
            <div>
              <h3 className="text-2xl font-bold text-slate-800 mb-6 flex items-center gap-2">
                 <div className="w-8 h-8 rounded-full bg-[#6B90F2]/20 flex items-center justify-center text-[#6B90F2] text-sm font-bold">2</div>
                 Permanent Residence
              </h3>
              <p className="text-xs text-slate-500 mb-6 italic">Required to confirm you have a primary residence elsewhere and are not seeking tenancy.</p>
              <div className="space-y-4">
                <Input label="Street Address" name="permanent_address" value={formData.permanent_address} onChange={e => setFormData({...formData, permanent_address: e.target.value})} placeholder="Your actual home address" required />
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
                    onChange={e => setFormData({...formData, permanent_city: e.target.value})}
                    placeholder={formData.permanent_state ? "Select City" : "Select State first"}
                    options={cityOptions}
                    disabled={!formData.permanent_state}
                    required
                  />
                </div>
                <Input label="ZIP Code" name="permanent_zip" value={formData.permanent_zip} onChange={e => setFormData({...formData, permanent_zip: e.target.value})} required />
              </div>
            </div>
            )}

            <div className={isTenantInvite ? 'mt-12' : 'md:col-span-2 mt-12'}>
              <h3 className="text-2xl font-bold text-slate-800 mb-8 flex items-center gap-2">
                 <div className="w-8 h-8 rounded-full bg-[#6B90F2]/20 flex items-center justify-center text-[#6B90F2] text-sm font-bold">{isTenantInvite ? 2 : 3}</div>
                 {isTenantInvite ? 'Agreements' : 'Stay acknowledgments'}
              </h3>
              
              {!isTenantInvite && (
              <div className="grid md:grid-cols-3 gap-6 mb-12">
                {[
                  { name: 'guest_status_acknowledged', label: 'Temporary Guest Status', desc: 'I acknowledge I am a guest only, not a tenant or resident.' },
                  { name: 'no_tenancy_acknowledged', label: 'Temporary stay', desc: 'I acknowledge this stay is temporary and does not grant tenancy.' },
                  { name: 'vacate_acknowledged', label: 'Agreement to Vacate', desc: 'I agree to vacate the property by the scheduled checkout date.' }
                ].map(ack => (
                  <div key={ack.name} className={`p-6 rounded-3xl border transition-all duration-300 ${formData[ack.name] ? 'bg-slate-50 border-slate-300 shadow-md' : 'bg-white border-slate-200'}`}>
                    <label className="flex flex-col gap-4 cursor-pointer h-full">
                       <div className="flex justify-between items-start">
                          <span className={`text-sm font-bold ${formData[ack.name] ? 'text-slate-800' : 'text-slate-700'}`}>{ack.label}</span>
                          <input 
                            type="checkbox" 
                            name={ack.name} 
                            checked={formData[ack.name]} 
                            onChange={handleCheckboxChange} 
                            className="w-5 h-5 rounded border-slate-300 bg-white text-[#6B90F2] focus:ring-[#6B90F2] shrink-0 mt-0.5" 
                            required 
                          />
                       </div>
                       <p className="text-xs text-slate-500 leading-relaxed">{ack.desc}</p>
                    </label>
                  </div>
                ))}
              </div>
              )}

              <div className="pt-8 border-t border-slate-200 space-y-4">
                <label className="flex items-start gap-3 cursor-pointer group w-full max-w-2xl">
                  <input type="checkbox" name="terms_agreed" checked={formData.terms_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0 mt-0.5" required />
                  <span className="text-sm text-slate-600 group-hover:text-slate-800 pt-0.5">I agree to the <a href="#terms" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-semibold hover:underline">Terms of Service</a>.</span>
                </label>
                <label className="flex items-start gap-3 cursor-pointer group w-full max-w-2xl">
                  <input type="checkbox" name="privacy_agreed" checked={formData.privacy_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500 shrink-0 mt-0.5" required />
                  <span className="text-sm text-slate-600 group-hover:text-slate-800 pt-0.5">I agree to the <a href="#privacy" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-semibold hover:underline">Privacy Policy</a>.</span>
                </label>

                {!isTenantInvite && (
                <div className="flex flex-col items-center gap-3 mt-6 text-center">
                  <Button
                    type="button"
                    variant={agreementSignatureId ? 'secondary' : 'outline'}
                    className="w-full max-w-xl py-4"
                    onClick={() => setAgreementOpen(true)}
                  >
                    {agreementSignatureId ? 'Agreement Signed ✓ (View)' : 'Review & Sign Agreement (Required)'}
                  </Button>
                  {!agreementSignatureId ? (
                    <p className="text-xs text-slate-500">Your signup cannot be completed until the agreement is signed.</p>
                  ) : null}
                </div>
                )}
                <div className="flex flex-col items-center mt-6">
                  <Button type="submit" disabled={!isTenantInvite && !agreementSignatureId} className="w-full md:w-auto px-20 py-5 text-xl">{isTenantInvite ? 'Create Account & Accept Tenant Invitation' : 'Create Account & Accept Invitation'}</Button>
                  <p className="text-sm text-slate-600 mt-6">
                    Already have an account?{' '}
                    <button type="button" onClick={() => {
                      if (normalizedCode) {
                        sessionStorage.setItem('docustay_pending_invite_code', normalizedCode);
                      }
                      navigate(isTenantInvite ? `login/tenant` : `guest-login/${normalizedCode}`);
                    }} className="text-[#6B90F2] font-semibold hover:text-[#5a7ed9] underline underline-offset-4">
                      Sign in
                    </button>
                  </p>
                </div>
              </div>
            </div>
          </form>
        </div>
      </div>

      <AgreementSignModal
        open={agreementOpen}
        invitationCode={normalizedCode}
        guestEmail={formData.email}
        guestFullName={formData.full_name}
        onClose={() => setAgreementOpen(false)}
        onSigned={(id) => setAgreementSignatureId(id)}
        notify={notify}
        inviteAcceptMode
        prefilledGuestInfo={agreementOpen ? {
          full_name: formData.full_name.trim(),
          email: formData.email.trim(),
          phone: formData.phone.trim(),
          permanent_address: [formData.permanent_address, formData.permanent_city, formData.permanent_state, formData.permanent_zip].filter(Boolean).join(', '),
        } : undefined}
      />
    </HeroBackground>
  );
};

export default RegisterFromInvite;
