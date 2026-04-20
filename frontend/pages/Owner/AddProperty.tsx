
import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Card, Input, Button } from '../../components/UI';
import { propertiesApi, emitPropertiesChanged } from '../../services/api';
import { UserSession } from '../../types';

// Import city data
import US_CITIES_DATA from '@/data/us-cities.json';

const US_CITIES = US_CITIES_DATA as Record<string, string[]>;

interface Props {
  user: UserSession | null;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
}

const ALLOWED_PROOF_TYPES = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png'];
const MAX_PROOF_SIZE = 10 * 1024 * 1024; // 10MB
const STEP_LABELS = ['Location', 'Details', 'Proof'];
const TOTAL_STEPS = 3;

function isAllowedProofFile(file: File): boolean {
  const ok = ALLOWED_PROOF_TYPES.includes(file.type) && file.size <= MAX_PROOF_SIZE;
  return ok;
}

function isStep1Valid(formData: { property_name: string; street_address: string; city: string; state: string; zip_code: string }): boolean {
  return (
    (formData.property_name || '').trim().length > 0 &&
    (formData.street_address || '').trim().length > 0 &&
    (formData.city || '').trim().length > 0 &&
    (formData.state || '').trim().length > 0 &&
    (formData.zip_code || '').trim().length > 0
  );
}

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

/** Default labels for multi-unit registration; users may override per field. */
function makeDefaultUnitLabels(count: number): string[] {
  return Array.from({ length: count }, (_, i) => `Unit ${i + 1}`);
}

function resolvedUnitLabelsForSubmit(unitLabels: string[], unitCount: number): string[] {
  return Array.from({ length: unitCount }, (_, i) => {
    const t = (unitLabels[i] ?? '').trim();
    return t || `Unit ${i + 1}`;
  });
}

function isStep2Valid(
  formData: { property_type: string; unit_count: string; unit_labels: string[]; primary_residence_unit: string },
  isMultiUnitType: boolean
): boolean {
  if (isMultiUnitType) {
    const uc = parseInt(formData.unit_count, 10);
    if (!formData.unit_count.trim() || isNaN(uc) || uc < 1) return false;
    if (uc > 500) return false;
    if (formData.primary_residence_unit) {
      const pu = parseInt(formData.primary_residence_unit, 10);
      if (isNaN(pu) || pu < 1 || pu > uc) return false;
    }
  }
  return true;
}

function isStep3Valid(proofFile: File | null): boolean {
  return proofFile != null;
}

const AddProperty: React.FC<Props> = ({ user, navigate, setLoading, notify }) => {
  const [step, setStep] = useState(1);
  const [proofFile, setProofFile] = useState<File | null>(null);
  const proofInputRef = useRef<HTMLInputElement>(null);
  const [formData, setFormData] = useState({
    property_name: '',
    street_address: '',
    address_line_2: '',
    city: '',
    state: '',
    zip_code: '',
    country: 'USA',
    property_type: 'house',
    bedrooms: '1',
    unit_count: '',
    unit_labels: [] as string[],
    is_primary_residence: false,
    primary_residence_unit: '' as string,
    proof_type: 'deed',
  });

  const isMultiUnitType = ['apartment', 'duplex', 'triplex', 'quadplex'].includes(formData.property_type);
  const defaultUnitCount: Record<string, string> = { duplex: '2', triplex: '3', quadplex: '4' };
  const parsedUnitCount = parseInt(formData.unit_count, 10);
  const validUnitCount = !isNaN(parsedUnitCount) && parsedUnitCount > 0 && parsedUnitCount <= 500 ? parsedUnitCount : 0;

  // Derive city options based on selected state
  const cityOptions = useMemo(() => {
    if (!formData.state) return [];
    const cities = US_CITIES[formData.state] || [];
    return cities.map(city => ({ value: city, label: city }));
  }, [formData.state]);

  const canProceedStep1 = isStep1Valid(formData);
  const canProceedStep2 = isStep2Valid(formData, isMultiUnitType);
  const canProceedStep3 = isStep3Valid(proofFile);
  const canProceed = step === 1 ? canProceedStep1 : step === 2 ? canProceedStep2 : canProceedStep3;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (step < TOTAL_STEPS) {
      if (step === 1 && !canProceedStep1) {
        notify('error', 'Please fill in all required fields: Property Label, Street Address, City, State, and ZIP Code.');
        return;
      }
      if (step === 2 && !canProceedStep2) {
        notify('error', isMultiUnitType
          ? 'Enter how many units or bedrooms you own in this building (1–500).'
          : 'Please complete all required property details.');
        return;
      }
      if (step === 3 && !canProceedStep3) {
        notify('error', 'Please upload proof of ownership (PDF or image) before finishing.');
        return;
      }
      setStep(step + 1);
      return;
    }

    if (!proofFile) {
      notify('error', 'Please upload proof of ownership (PDF or image) in the Proof step before finishing.');
      return;
    }

    if (isMultiUnitType) {
      const uc = parseInt(formData.unit_count, 10);
      if (!formData.unit_count.trim() || isNaN(uc) || uc < 1) {
        notify('error', 'Enter how many units or bedrooms you own in this building (at least 1).');
        return;
      }
    }

    setLoading(true);
    try {
      const streetWithLine2 = formData.address_line_2.trim()
        ? `${formData.street_address.trim()}, ${formData.address_line_2.trim()}`
        : formData.street_address.trim();
      const payload: Parameters<typeof propertiesApi.add>[0] = {
        property_name: formData.property_name || undefined,
        street_address: streetWithLine2,
        city: formData.city,
        state: formData.state,
        zip_code: formData.zip_code || undefined,
        country: formData.country,
        property_type: formData.property_type,
        bedrooms: formData.bedrooms,
        is_primary_residence: false,
      };
      if (isMultiUnitType && formData.unit_count) {
        const uc = parseInt(formData.unit_count, 10);
        if (!isNaN(uc) && uc > 0) {
          payload.unit_count = uc;
          payload.unit_labels = resolvedUnitLabelsForSubmit(formData.unit_labels, uc);
        }
      }
      const prop = await propertiesApi.add(payload);
      await propertiesApi.uploadOwnershipProof(prop.id, formData.proof_type, proofFile);
      setLoading(false);
      emitPropertiesChanged();
      notify('success', 'Property added.');
      navigate(`property/${prop.id}`);
    } catch (err) {
      setLoading(false);
      notify('error', (err as Error)?.message || 'Failed to add property.');
    }
  };

  const propertyTypes = [
    { id: 'house', name: 'House', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
    { id: 'apartment', name: 'Apartment', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'condo', name: 'Condo', icon: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z' },
    { id: 'townhouse', name: 'Townhouse', icon: 'M3 21h18M3 7h18M5 3h14a2 2 0 012 2v16H3V5a2 2 0 012-2z' },
    { id: 'duplex', name: 'Duplex', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'triplex', name: 'Triplex', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'quadplex', name: 'Quadplex', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
  ];

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <button onClick={() => navigate('dashboard')} className="flex items-center gap-2 text-slate-600 hover:text-slate-800 mb-8 font-bold text-sm uppercase tracking-widest transition-colors">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7"></path></svg>
        Back to Dashboard
      </button>

      <div className="mb-12">
        <div className="flex items-center justify-between mb-4">
          {STEP_LABELS.map((s, i) => (
            <div key={s} className="flex flex-col items-center gap-2 relative z-10">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-500 ${step > i + 1 ? 'bg-green-500 text-white' : step === i + 1 ? 'bg-blue-600 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] scale-110' : 'bg-slate-200 text-slate-500'}`}>
                {step > i + 1 ? (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7"></path></svg>
                ) : i + 1}
              </div>
              <span className={`text-xs uppercase tracking-widest font-bold ${step === i + 1 ? 'text-blue-600' : 'text-slate-500'}`}>{s}</span>
            </div>
          ))}
        </div>
        <div className="h-1 bg-slate-200 w-full absolute -z-0 max-w-4xl rounded-full translate-y-[-44px]">
          <div className="h-full bg-gradient-to-r from-blue-600 to-green-500 transition-all duration-700 rounded-full" style={{ width: `${((step - 1) / Math.max(1, TOTAL_STEPS - 1)) * 100}%` }}></div>
        </div>
      </div>

      <Card className="p-10 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-64 h-64 bg-blue-600/5 blur-[80px] rounded-full pointer-events-none"></div>

        <form onSubmit={handleSubmit}>
          {step === 1 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h2 className="text-3xl font-bold text-slate-800 mb-2">Property Location</h2>
              <p className="text-slate-500 mb-8">Tell us where the property is located to apply the correct jurisdiction logic.</p>
              <div className="grid md:grid-cols-2 gap-6">
                <div className="md:col-span-2">
                  <Input label="Property Label (e.g., 'Miami Beach Condo')" name="property_name" value={formData.property_name} onChange={e => setFormData({...formData, property_name: e.target.value})} placeholder="Give this property a nickname" required />
                </div>
                <div className="md:col-span-2">
                  <Input label="Street Address" name="street_address" value={formData.street_address} onChange={e => setFormData({...formData, street_address: e.target.value})} placeholder="123 Ocean Drive" required />
                </div>
                <div className="md:col-span-2">
                  <Input label="Address Line 2 (Apt, Suite, Unit)" name="address_line_2" value={formData.address_line_2} onChange={e => setFormData({...formData, address_line_2: e.target.value})} placeholder="Apt 303, Suite B, etc." />
                </div>
                <Input
                  label="State" name="state" value={formData.state} 
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
                  label="City" name="city" value={formData.city} 
                  onChange={e => setFormData({...formData, city: e.target.value})} 
                  placeholder={formData.state ? "Select City" : "Select State first"}
                  options={cityOptions}
                  disabled={!formData.state}
                  required 
                />
                <Input label="ZIP Code" name="zip_code" value={formData.zip_code} onChange={e => setFormData({...formData, zip_code: e.target.value})} placeholder="33139" required />
                <Input label="Country" name="country" value={formData.country} onChange={() => {}} options={[{value: 'USA', label: 'United States'}]} disabled />
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h2 className="text-3xl font-bold text-slate-800 mb-2">Property Details</h2>
              <p className="text-slate-500 mb-8">
                For a single-family home or condo, choose bedrooms. For a building with multiple units you own (apartment, duplex, triplex, quadplex), enter{' '}
                <strong>how many units or bedrooms you own</strong> at that address—we label them Unit 1, Unit 2, … automatically, and you can rename them below if you like.
                To register a large building with many units at once, use <strong>Bulk upload (CSV)</strong> from the dashboard instead.
              </p>
              <label className="block text-sm font-medium text-slate-600 mb-4 ml-1">Property Type</label>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                {propertyTypes.map(type => (
                  <div
                    key={type.id}
                    onClick={() => {
                      const newUnitCount = defaultUnitCount[type.id] ?? '';
                      const nc = parseInt(newUnitCount, 10);
                      const safeCount = !isNaN(nc) && nc > 0 ? nc : 0;
                      setFormData({
                        ...formData,
                        property_type: type.id,
                        unit_count: newUnitCount,
                        unit_labels: safeCount > 0 ? makeDefaultUnitLabels(safeCount) : [],
                        primary_residence_unit: '',
                      });
                    }}
                    className={`cursor-pointer p-6 rounded-2xl border-2 transition-all duration-300 flex flex-col items-center gap-3 ${formData.property_type === type.id ? 'bg-blue-50 border-blue-400 shadow-lg shadow-blue-500/10' : 'bg-slate-100 border-slate-200 hover:border-slate-300'}`}
                  >
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center transition-colors ${formData.property_type === type.id ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-600'}`}>
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={type.icon}></path></svg>
                    </div>
                    <span className={`text-sm font-bold ${formData.property_type === type.id ? 'text-blue-600' : 'text-slate-500'}`}>{type.name}</span>
                  </div>
                ))}
              </div>
              <div className="space-y-6">
                <div className="grid md:grid-cols-2 gap-8">
                  {isMultiUnitType ? (
                    <div className="md:col-span-2 space-y-2 max-w-md">
                      <Input
                        label="How many units or bedrooms do you own in this building?"
                        name="unit_count"
                        value={formData.unit_count}
                        onChange={e => {
                          const newCount = e.target.value;
                          const nc = parseInt(newCount, 10);
                          const safeCount = !isNaN(nc) && nc > 0 && nc <= 500 ? nc : 0;
                          const newLabels = Array.from({ length: safeCount }, (_, i) => {
                            const prev = formData.unit_labels[i];
                            if (prev !== undefined && String(prev).trim() !== '') return prev;
                            return `Unit ${i + 1}`;
                          });
                          setFormData({
                            ...formData,
                            unit_count: newCount,
                            unit_labels: newLabels,
                            primary_residence_unit: '',
                          });
                        }}
                        placeholder={defaultUnitCount[formData.property_type] || 'e.g. 4'}
                        required
                        className="mb-0"
                      />
                      <p className="text-xs text-slate-500">
                        We create labels Unit 1, Unit 2, … automatically. Optional: change them below to match your door numbers (e.g. Apt 303).
                      </p>
                    </div>
                  ) : (
                    <Input label="Number of Bedrooms" name="bedrooms" value={formData.bedrooms} onChange={e => setFormData({...formData, bedrooms: e.target.value})} options={[
                      {value: '1', label: '1 Bedroom'}, {value: '2', label: '2 Bedrooms'}, {value: '3', label: '3 Bedrooms'}, {value: '4', label: '4 Bedrooms'}, {value: '5', label: '5+ Bedrooms'}
                    ]} />
                  )}
                </div>

                {isMultiUnitType && validUnitCount > 0 && (
                  <div className="space-y-4">
                    <div>
                      <p className="text-sm font-bold text-slate-700 mb-1">Customize unit labels (optional)</p>
                      <p className="text-xs text-slate-500">
                        Defaults are already set to Unit 1, Unit 2, … Edit only the ones you want to match your building (e.g. Apt 101, Suite B).
                      </p>
                    </div>
                    <div className={`grid gap-3 ${validUnitCount <= 4 ? 'md:grid-cols-2' : validUnitCount <= 9 ? 'md:grid-cols-3' : 'md:grid-cols-4'}`}>
                      {Array.from({ length: validUnitCount }, (_, i) => (
                        <div key={i}>
                          <label className="block text-xs font-medium text-slate-500 mb-1">Unit {i + 1}</label>
                          <input
                            type="text"
                            value={formData.unit_labels[i] ?? `Unit ${i + 1}`}
                            onChange={e => {
                              const newLabels = [...formData.unit_labels];
                              newLabels[i] = e.target.value;
                              setFormData({ ...formData, unit_labels: newLabels });
                            }}
                            placeholder={`Unit ${i + 1}`}
                            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                          />
                        </div>
                      ))}
                    </div>

                  </div>
                )}
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h2 className="text-3xl font-bold text-slate-800 mb-2">Ownership Verification</h2>
              <p className="text-slate-500 mb-8">Upload proof of ownership.</p>
              <Input
                label="Type of Proof" name="proof_type" value={formData.proof_type} onChange={e => setFormData({...formData, proof_type: e.target.value})}
                options={[
                  { value: 'deed', label: 'Property Deed (Recommended)' },
                  { value: 'tax_bill', label: 'Property Tax Bill' },
                  { value: 'utility_bill', label: 'Recent Utility Bill' },
                  { value: 'mortgage_statement', label: 'Mortgage Statement' }
                ]}
              />
              <div
                className="mt-8 border-2 border-dashed border-slate-300 rounded-3xl p-12 text-center bg-white/55 backdrop-blur-lg group hover:border-blue-400/50 transition-all cursor-pointer"
                onClick={() => proofInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const file = e.dataTransfer?.files?.[0];
                  if (file && isAllowedProofFile(file)) setProofFile(file);
                  else if (file) notify('error', file.size > MAX_PROOF_SIZE ? 'File too large. Max 10MB.' : 'Please upload a PDF or image (JPEG, PNG).');
                }}
              >
                <input
                  ref={proofInputRef}
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file && isAllowedProofFile(file)) setProofFile(file);
                    else if (file) notify('error', file.size > MAX_PROOF_SIZE ? 'File too large. Max 10MB.' : 'Please upload a PDF or image (JPEG, PNG).');
                    e.target.value = '';
                  }}
                />
                <div className="w-16 h-16 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mx-auto mb-6 group-hover:scale-110 transition-transform">
                  <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                </div>
                <h4 className="text-xl font-bold text-slate-800 mb-2">Upload Proof of Ownership</h4>
                <p className="text-sm text-slate-500 mb-6">Drag and drop your file here, or click to browse. PDF or image (JPEG, PNG), max 10MB.</p>
                <Button type="button" variant="outline" className="px-8" onClick={(e) => { e.stopPropagation(); proofInputRef.current?.click(); }}>Select File</Button>
                {proofFile ? (
                  <div className="mt-6 flex items-center justify-center gap-2 text-green-600 font-bold text-sm bg-green-50 py-2 px-4 rounded-full w-fit mx-auto">
                    <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                    {proofFile.name}
                  </div>
                ) : (
                  <p className="mt-6 text-sm text-slate-500">No file selected</p>
                )}
              </div>
            </div>
          )}

          <div className="mt-12 pt-8 border-t border-slate-200 flex gap-4">
            {step > 1 ? (
              <Button type="button" variant="outline" onClick={() => setStep(step - 1)} className="px-10">Back</Button>
            ) : (
              <Button type="button" variant="outline" onClick={() => navigate('dashboard')} className="px-10">Cancel</Button>
            )}
            <Button
              type="submit"
              className="flex-1 py-4 text-xl"
              disabled={!canProceed}
            >
              {step === 3 ? 'Add property' : 'Continue to next step'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
};

export default AddProperty;
