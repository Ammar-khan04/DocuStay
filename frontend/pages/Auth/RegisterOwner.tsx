import React, { useState, useEffect, useMemo } from 'react';
import { Input, Button, ErrorModal } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout, AuthBullet } from '../../components/AuthCardLayout';
import { authApi, DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY } from '../../services/api';
import { getOwnerSignupErrorFriendly } from '../../utils/ownerSignupErrors';
import { validatePhone, sanitizePhoneInput } from '../../utils/validatePhone';

// Import city data
import US_CITIES_DATA from '@/data/us-cities.json';

const US_CITIES = US_CITIES_DATA as Record<string, string[]>;

const US_STATES = [
  { value: 'AL', label: 'Alabama' }, { value: 'AK', label: 'Alaska' }, { value: 'AZ', label: 'Arizona' },
  { value: 'AR', label: 'Arkansas' }, { value: 'CA', label: 'California' }, { value: 'CO', label: 'Colorado' },
  { value: 'CT', label: 'Connecticut' }, { value: 'DE', label: 'Delaware' }, { value: 'FL', label: 'Florida' },
  { value: 'GA', label: 'Georgia' }, { value: 'HI', label: 'Hawaii' }, { value: 'ID', label: 'Idaho' },
  { value: 'IL', label: 'Illinois' }, { value: 'IN', label: 'Indiana' }, { value: 'IA', label: 'Iowa' },
  { value: 'KS', label: 'Kansas' }, { value: 'KY', label: 'Kentucky' }, { value: 'LA', label: 'Louisiana' },
  { value: 'ME', label: 'Maine' }, { value: 'MD', label: 'Maryland' }, { value: 'MA', label: 'Massachusetts' },
  { value: 'MI', label: 'Michigan' }, { value: 'MN', label: 'Minnesota' }, { value: 'MS', label: 'Mississippi' },
  { value: 'MO', label: 'Missouri' }, { value: 'MT', label: 'Montana' }, { value: 'NE', label: 'Nebraska' },
  { value: 'NV', label: 'Nevada' }, { value: 'NH', label: 'New Hampshire' }, { value: 'NJ', label: 'New Jersey' },
  { value: 'NM', label: 'New Mexico' }, { value: 'NY', label: 'New York' }, { value: 'NC', label: 'North Carolina' },
  { value: 'ND', label: 'North Dakota' }, { value: 'OH', label: 'Ohio' }, { value: 'OK', label: 'Oklahoma' },
  { value: 'OR', label: 'Oregon' }, { value: 'PA', label: 'Pennsylvania' }, { value: 'RI', label: 'Rhode Island' },
  { value: 'SC', label: 'South Carolina' }, { value: 'SD', label: 'South Dakota' }, { value: 'TN', label: 'Tennessee' },
  { value: 'TX', label: 'Texas' }, { value: 'UT', label: 'Utah' }, { value: 'VT', label: 'Vermont' },
  { value: 'VA', label: 'Virginia' }, { value: 'WA', label: 'Washington' }, { value: 'WV', label: 'West Virginia' },
  { value: 'WI', label: 'Wisconsin' }, { value: 'WY', label: 'Wyoming' },
];

interface Props {
  setPendingVerification: (data: any) => void;
  onLogin?: (user: any) => void;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  /** From `#register/owner-transfer/{token}` — persists token for accept after onboarding. */
  propertyTransferToken?: string;
}

const RegisterOwner: React.FC<Props> = ({
  setPendingVerification,
  onLogin,
  navigate,
  setLoading,
  notify,
  propertyTransferToken,
}) => {
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    password: '',
    confirm_password: '',
    country: 'USA',
    state: '',
    city: '',
    terms_agreed: false,
    privacy_agreed: false
  });
  const [errors, setErrors] = useState<any>({});
  const [passwordStrength, setPasswordStrength] = useState(0);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });
  const [transferEmailLocked, setTransferEmailLocked] = useState(false);
  const [transferInvitedEmail, setTransferInvitedEmail] = useState<string | null>(null);

  useEffect(() => {
    const t = (propertyTransferToken || '').trim();
    if (!t) return;
    try {
      sessionStorage.setItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY, t);
    } catch {
      /* ignore */
    }
    let cancelled = false;
    authApi
      .getPropertyTransferInvite(t)
      .then((d) => {
        if (cancelled) return;
        const em = (d.email || '').trim();
        setFormData((prev) => ({ ...prev, email: em }));
        setTransferInvitedEmail(em.toLowerCase());
        setTransferEmailLocked(true);
      })
      .catch(() => {
        if (cancelled) return;
        notify('error', 'This property transfer link is invalid or expired. You can still register, but you may need a new link from the owner.');
      });
    return () => {
      cancelled = true;
    };
  }, [propertyTransferToken, notify]);

  // Derive city options based on selected state
  const cityOptions = useMemo(() => {
    if (!formData.state) return [];
    const cities = US_CITIES[formData.state] || [];
    return cities.map(city => ({ value: city, label: city }));
  }, [formData.state]);

  useEffect(() => {
    let strength = 0;
    if (formData.password.length >= 8) strength++;
    if (/[A-Z]/.test(formData.password)) strength++;
    if (/[0-9]/.test(formData.password)) strength++;
    if (/[^A-Za-z0-9]/.test(formData.password)) strength++;
    setPasswordStrength(strength);
  }, [formData.password]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    const newErrors: Record<string, { error: string }> = {};
    if (!formData.first_name.trim()) newErrors.first_name = { error: 'First name is required.' };
    if (!formData.last_name.trim()) newErrors.last_name = { error: 'Last name is required.' };
    if (!formData.email.trim()) newErrors.email = { error: 'Email is required.' };
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email.trim())) newErrors.email = { error: 'Please enter a valid email address.' };
    if (transferInvitedEmail && formData.email.trim().toLowerCase() !== transferInvitedEmail) {
      newErrors.email = { error: 'Email must match the invited address for this property transfer.' };
    }
    const phoneCheck = validatePhone(formData.phone);
    if (!phoneCheck.valid) newErrors.phone = { error: phoneCheck.error };
    if (!formData.password) newErrors.password = { error: 'Password is required.' };
    if (formData.password && formData.password.length < 8) newErrors.password = { error: 'Password must be at least 8 characters.' };
    if (formData.password !== formData.confirm_password) newErrors.password_match = { error: 'Passwords do not match.' };
    if (!formData.state) newErrors.state = { error: 'Primary state is required.' };
    if (!formData.city.trim()) newErrors.city = { error: 'City is required.' };
    if (!formData.terms_agreed) newErrors.terms = { error: 'You must agree to the Terms of Service.' };
    if (!formData.privacy_agreed) newErrors.privacy = { error: 'You must agree to the Privacy Policy.' };
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    setLoading(true);
    setErrors({});
    try {
      const fullName = `${formData.first_name} ${formData.last_name}`.trim();
      const result = await authApi.register({
        account_type: 'individual',
        first_name: formData.first_name,
        last_name: formData.last_name,
        full_name: fullName,
        email: formData.email,
        phone: formData.phone,
        password: formData.password,
        confirm_password: formData.confirm_password,
        country: formData.country,
        state: formData.state,
        city: formData.city,
        terms_agreed: formData.terms_agreed,
        privacy_agreed: formData.privacy_agreed,
      });
      setLoading(false);
      if (result.status === 'error') {
        const apiMessage = (result.message && result.message.trim()) || "Registration failed. Please try again.";
        const friendly = getOwnerSignupErrorFriendly(apiMessage);
        notify('error', friendly.message);
        if (result.validation && Object.keys(result.validation).length > 0) {
          setErrors(result.validation);
        }
        return;
      }
      if (result.status === 'success' && result.data) {
        if ('user_id' in result.data) {
          setPendingVerification({
            userId: result.data.user_id,
            type: 'email',
            email: formData.email,
            generatedAt: new Date().toISOString(),
          });
          navigate('verify');
        } else if (result.data && 'access_token' in result.data) {
          onLogin?.(result.data as any);
        }
      }
    } catch (err) {
      setLoading(false);
      const friendly = getOwnerSignupErrorFriendly((err as Error)?.message);
      notify('error', friendly.message);
    }
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, checked } = e.target;
    setFormData((prev) => ({ ...prev, [name]: checked }));
  };

  return (
    <HeroBackground className="flex-grow">
      <AuthCardLayout
        maxWidth="6xl"
        minHeight="580px"
        leftPanel={
          <>
            <h2 className="text-2xl font-semibold text-slate-900 mb-3">Create Owner Account</h2>
            <p className="text-slate-600 text-sm mb-8">
              Register to manage your properties, invite guests, and document temporary stays.
            </p>
            <ul className="space-y-3">
              <AuthBullet>Add and manage properties</AuthBullet>
              <AuthBullet>Invite guests and property managers</AuthBullet>
              <AuthBullet>Document temporary stays</AuthBullet>
            </ul>
          </>
        }
      >
          <div className="w-full max-w-3xl min-w-0">
            <h1 className="text-xl font-semibold text-slate-900 mb-4">Create Owner Account</h1>

            <form onSubmit={handleSubmit} className="grid md:grid-cols-2 gap-x-6 gap-y-4 min-w-0">
              <Input
                label="First Name"
                name="first_name"
                value={formData.first_name}
                onChange={e => setFormData({ ...formData, first_name: e.target.value })}
                error={errors.first_name?.error}
                placeholder="John"
                required
              />
              <Input
                label="Last Name"
                name="last_name"
                value={formData.last_name}
                onChange={e => setFormData({ ...formData, last_name: e.target.value })}
                error={errors.last_name?.error}
                placeholder="Miller"
                required
              />
              <Input
                label="Work Email"
                name="email"
                type="email"
                value={formData.email}
                onChange={e => setFormData({ ...formData, email: e.target.value })}
                error={errors.email?.error}
                placeholder="john@example.com"
                required
                disabled={transferEmailLocked}
              />
              <Input
                label="Phone Number"
                name="phone"
                value={formData.phone}
                onChange={e => setFormData({ ...formData, phone: sanitizePhoneInput(e.target.value) })}
                error={errors.phone?.error}
                placeholder="+15551234567 or 5551234567"
                required
              />
              <div className="relative">
                <Input
                  label="Password"
                  name="password"
                  type="password"
                  value={formData.password}
                  onChange={e => setFormData({ ...formData, password: e.target.value })}
                  error={errors.password?.error}
                  placeholder="••••••••"
                  required
                />
                <div className="flex gap-1 mt-1 px-1">
                  {[1, 2, 3, 4].map(i => (
                    <div key={i} className={`h-1 flex-1 rounded-full transition-all duration-300 ${passwordStrength >= i ? (passwordStrength <= 2 ? 'bg-amber-500' : 'bg-green-600') : 'bg-gray-200'}`}></div>
                  ))}
                </div>
                <p className="text-xs text-gray-500 mt-1.5">At least 8 characters with numbers and symbols</p>
              </div>
              <Input
                label="Confirm Password"
                name="confirm_password"
                type="password"
                value={formData.confirm_password}
                onChange={e => setFormData({ ...formData, confirm_password: e.target.value })}
                error={errors.password_match?.error}
                placeholder="••••••••"
                required
              />
              <Input
                label="Primary State"
                name="state"
                value={formData.state}
                onChange={e => {
                  const newState = e.target.value;
                  setFormData({ 
                    ...formData, 
                    state: newState,
                    city: '' // Reset city when state changes
                  });
                }}
                options={US_STATES}
                required
              />
              <Input
                label="City"
                name="city"
                value={formData.city}
                onChange={e => setFormData({ ...formData, city: e.target.value })}
                placeholder={formData.state ? "Select City" : "Select State first"}
                options={cityOptions}
                disabled={!formData.state}
                required
              />
              <div className={`md:col-span-2 space-y-3 mt-2 p-4 rounded-lg bg-slate-50 border ${errors.terms?.error || errors.privacy?.error ? 'border-red-300' : 'border-slate-200'}`}>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" name="terms_agreed" checked={formData.terms_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 text-[#6B90F2] focus:ring-[#6B90F2] shrink-0 mt-0.5" />
                  <span className="text-sm text-slate-600 leading-relaxed">I agree to the <a href="#terms" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-medium hover:underline">Terms of Service</a> and the platform&apos;s documentation and authorization protocols.</span>
                </label>
                {errors.terms?.error && <p className="text-xs text-red-500 pl-8">{errors.terms.error}</p>}
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" name="privacy_agreed" checked={formData.privacy_agreed} onChange={handleCheckboxChange} className="w-5 h-5 rounded border-slate-300 text-[#6B90F2] focus:ring-[#6B90F2] shrink-0 mt-0.5" />
                  <span className="text-sm text-slate-600">I agree to the processing of my data according to the <a href="#privacy" target="_blank" rel="noopener noreferrer" className="text-[#6B90F2] font-medium hover:underline">Privacy Policy</a>.</span>
                </label>
                {errors.privacy?.error && <p className="text-xs text-red-500 pl-8">{errors.privacy.error}</p>}
              </div>
              <div className="md:col-span-2 mt-6 flex flex-col items-center">
                <p className="text-sm text-slate-500 mb-2">After signup you'll complete verification and authorization.</p>
                <Button type="submit" className="w-full md:min-w-[200px] py-3">
                  Create Secure Account
                </Button>
                <p className="mt-4 text-center text-slate-500 text-sm">
                  Already have an account? <button type="button" onClick={() => navigate('login')} className="text-[#6B90F2] font-medium hover:text-[#5a7ed9] hover:underline underline-offset-2">Owner login</button>
                </p>
              </div>
            </form>
          </div>
      </AuthCardLayout>

      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal((p) => ({ ...p, open: false }))}
        actionLabel={errorModal.message.toLowerCase().includes("already registered") ? "Go to login" : undefined}
        onAction={errorModal.message.toLowerCase().includes("already registered") ? () => navigate("login") : undefined}
      />
    </HeroBackground>
  );
};

export default RegisterOwner;