import React, { useState, useEffect } from 'react';
import { Button } from '../components/UI';
import { SUPPORT_EMAIL, supportMailtoHref } from '../constants/supportContact';

/** Role config with icons (Heroicons paths) */
const ROLES = [
  { id: 'owner', label: 'Owner', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
  { id: 'property_manager', label: 'Property Manager', icon: 'M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z' },
  { id: 'tenant', label: 'Tenant', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { id: 'guest', label: 'Guest', icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' },
];

/** High-quality property/home images (Unsplash – free to use, no watermark) */
const HERO_IMAGES = [
  'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1920&q=80',
  'https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=1920&q=80',
  'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1920&q=80',
  'https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=1920&q=80',
  'https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=1920&q=80',
];

const CAROUSEL_INTERVAL_MS = 5000;

const VALUE_PROPS = [
  {
    title: 'Clear agreements',
    desc: 'Guests sign region-specific agreements so everyone knows the terms of the stay.',
    icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
    color: 'from-blue-500 to-sky-600',
  },
  {
    title: 'Identity verification',
    desc: 'Verify guest identity with Stripe Identity so you know who is staying.',
    icon: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
    color: 'from-emerald-500 to-teal-600',
  },
  {
    title: 'Occupancy & audit trail',
    desc: 'Document vacant vs. occupied status, authorized presence, and every status change with timestamped records.',
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
    color: 'from-violet-500 to-purple-600',
  },
  {
    title: 'Stay limits & alerts',
    desc: 'Region-aware stay limits and status alerts keep your documentation up to date.',
    icon: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
    color: 'from-amber-500 to-orange-600',
  },
];

const STEPS = [
  { label: 'Add property', desc: 'Register your property with address and details' },
  { label: 'Verify identity', desc: 'Complete identity verification for your account' },
  { label: 'Document status', desc: 'Track occupancy and authorized presence' },
  { label: 'Invite when needed', desc: 'Send invitations; guests sign agreements' },
];

type LandingProps = {
  navigate: (view: string) => void;
};

const Landing: React.FC<LandingProps> = ({ navigate }) => {
  const [activeIndex, setActiveIndex] = useState(0);
  const [roleSelector, setRoleSelector] = useState<'signup' | 'login' | null>(null);

  useEffect(() => {
    if (roleSelector) window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [roleSelector]);

  useEffect(() => {
    const t = setInterval(() => {
      setActiveIndex((i) => (i + 1) % HERO_IMAGES.length);
    }, CAROUSEL_INTERVAL_MS);
    return () => clearInterval(t);
  }, []);

  const onRoleSelect = (roleId: string) => {
    if (roleSelector === 'signup') {
      if (roleId === 'owner') navigate('register');
      else if (roleId === 'property_manager') navigate('register/manager');
      else if (roleId === 'tenant') navigate('guest-signup/tenant');
      else if (roleId === 'guest') navigate('guest-signup');
    } else {
      if (roleId === 'guest') navigate('guest-login');
      else if (roleId === 'owner') navigate('login');
      else if (roleId === 'property_manager') navigate('login/property_manager');
      else if (roleId === 'tenant') navigate('login/tenant');
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Hero: full-viewport background carousel + overlay + content */}
      <section className="relative min-h-[90vh] flex items-center justify-center overflow-hidden">
        {/* Demo entrypoint (isolated demo auth flow) */}
        <div className="absolute top-5 right-6 z-20">
          <button
            type="button"
            onClick={() => navigate('demo')}
            className="px-4 py-2 rounded-xl text-sm font-medium border border-white/40 text-white bg-white/10 hover:bg-white/20 backdrop-blur-sm transition-colors"
          >
            Demo
          </button>
        </div>
        {/* Background slideshow */}
        <div className="absolute inset-0">
          {HERO_IMAGES.map((src, i) => (
            <div
              key={src}
              className={`absolute inset-0 bg-cover bg-center transition-opacity duration-1000 ease-out ${
                i === activeIndex ? 'opacity-100 z-0' : 'opacity-0 z-[-1]'
              }`}
              style={{ backgroundImage: `url(${src})` }}
              aria-hidden={i !== activeIndex}
            />
          ))}
          {/* Gradient overlay for text readability */}
          <div className="absolute inset-0 bg-gradient-to-b from-slate-900/70 via-slate-900/60 to-slate-900/80 z-[1]" />
        </div>

        {/* Hero content */}
        <div className="relative z-10 max-w-4xl mx-auto px-6 text-center text-white">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 text-slate-200 text-sm font-medium mb-6">
            <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            Property documentation platform
          </div>
          <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight mb-4 drop-shadow-lg">
            Your property,{' '}
            <span className="text-sky-300">documented.</span>
          </h1>
          <p className="text-base sm:text-lg text-slate-200/90 max-w-2xl mx-auto mb-10 leading-relaxed">
            DocuStay is a neutral documentation platform for property status: occupancy, authorized presence, and an immutable audit trail over time. Guest authorization is one use case among many.
          </p>

          {roleSelector ? (
            <div className="w-full max-w-lg mx-auto">
              <div className="bg-white/95 backdrop-blur-md rounded-2xl shadow-2xl border border-slate-200/80 overflow-hidden">
                <div className="px-8 pt-8 pb-6">
                  <h2 className="text-xl font-semibold text-slate-900 mb-1">
                    {roleSelector === 'signup' ? 'Create an account as' : 'Sign in as'}
                  </h2>
                  <p className="text-sm text-slate-500 mb-6">
                    {roleSelector === 'signup'
                      ? 'Choose your role to get started'
                      : 'Select your account type to continue'}
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    {ROLES.map((r) => (
                      <button
                        key={r.id}
                        onClick={() => onRoleSelect(r.id)}
                        className="group flex items-center gap-3 px-5 py-4 rounded-xl border border-slate-200 bg-slate-50/50 hover:bg-white hover:border-[#6B90F2]/30 hover:shadow-lg hover:shadow-[#6B90F2]/10 transition-all duration-200 text-left"
                      >
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-200/80 group-hover:bg-[#6B90F2]/15 text-slate-600 group-hover:text-[#6B90F2] transition-colors">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={r.icon} />
                          </svg>
                        </span>
                        <span className="font-medium text-slate-800 group-hover:text-slate-900">{r.label}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="px-8 pb-6 pt-2">
                  <button
                    type="button"
                    onClick={() => setRoleSelector(null)}
                    className="flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
                    </svg>
                    Back
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col sm:flex-row justify-center gap-4">
              <Button
                variant="primary"
                onClick={() => setRoleSelector('signup')}
                className="px-8 py-3.5 bg-[#6B90F2] hover:bg-[#5a7ed9] border-0 text-white font-semibold shadow-lg shadow-slate-900/20 rounded-xl hover:shadow-xl hover:shadow-[#6B90F2]/20 transition-all"
              >
                Get started
              </Button>
              <button
                type="button"
                onClick={() => setRoleSelector('login')}
                className="px-8 py-3.5 rounded-xl text-sm font-medium border-2 border-white/80 text-white bg-white/5 hover:bg-white/15 backdrop-blur-sm transition-colors"
              >
                Already have an account?
              </button>
            </div>
          )}
        </div>

        {/* Carousel indicators */}
        <div className="absolute bottom-8 left-0 right-0 z-10 flex justify-center gap-2">
          {HERO_IMAGES.map((_, i) => (
            <button
              key={i}
              onClick={() => setActiveIndex(i)}
              className={`h-2 rounded-full transition-all duration-300 ${
                i === activeIndex ? 'w-8 bg-white' : 'w-2 bg-white/50 hover:bg-white/70'
              }`}
              aria-label={`Slide ${i + 1}`}
            />
          ))}
        </div>
      </section>

      {/* Trust / stats bar */}
      <section className="py-6 px-6 bg-white border-b border-slate-100">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-wrap justify-center gap-x-12 gap-y-4 text-center">
            <div>
              <p className="text-2xl md:text-3xl font-bold text-slate-900">Immutable</p>
              <p className="text-sm text-slate-500">Audit trail</p>
            </div>
            <div className="hidden sm:block w-px bg-slate-200" />
            <div>
              <p className="text-2xl md:text-3xl font-bold text-slate-900">Region-aware</p>
              <p className="text-sm text-slate-500">Agreements</p>
            </div>
            <div className="hidden sm:block w-px bg-slate-200" />
            <div>
              <p className="text-2xl md:text-3xl font-bold text-slate-900">Verified</p>
              <p className="text-sm text-slate-500">Identity</p>
            </div>
            <div className="hidden sm:block w-px bg-slate-200" />
            <div>
              <p className="text-2xl md:text-3xl font-bold text-slate-900">Documented</p>
              <p className="text-sm text-slate-500">Status changes</p>
            </div>
          </div>
        </div>
      </section>

      {/* Value props */}
      <section className="py-20 px-6 bg-gradient-to-b from-slate-50 to-white">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-4">
              Why DocuStay?
            </h2>
            <p className="text-slate-600 max-w-2xl mx-auto text-lg">
              Built for owners who want clear documentation of property status—vacant or occupied, authorized presence, and status changes over time.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8">
            {VALUE_PROPS.map((item) => (
              <div
                key={item.title}
                className="group relative bg-white rounded-2xl border border-slate-200/80 shadow-sm hover:shadow-xl hover:shadow-slate-200/50 hover:border-slate-200 transition-all duration-300 overflow-hidden"
              >
                <div className={`absolute top-0 right-0 w-32 h-32 bg-gradient-to-br ${item.color} opacity-5 group-hover:opacity-10 transition-opacity`} />
                <div className="relative p-6">
                  <div className={`inline-flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br ${item.color} mb-4`}>
                    <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={item.icon} />
                    </svg>
                  </div>
                  <h3 className="font-semibold text-slate-900 mb-2 text-lg">{item.title}</h3>
                  <p className="text-slate-600 text-sm leading-relaxed">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-20 px-6 bg-white">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-4">
              Simple flow for owners
            </h2>
            <p className="text-slate-600 max-w-xl mx-auto text-lg">
              Register your property, verify your identity, document status, and invite guests when needed.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {STEPS.map((step, i) => (
              <div key={step.label} className="relative">
                <div className="bg-slate-50 rounded-2xl border border-slate-200/80 p-6 h-full hover:border-[#6B90F2]/30 hover:shadow-lg hover:shadow-[#6B90F2]/5 transition-all">
                  <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-[#6B90F2] text-white font-bold text-lg mb-4">
                    {i + 1}
                  </span>
                  <h3 className="font-semibold text-slate-900 mb-2">{step.label}</h3>
                  <p className="text-slate-600 text-sm leading-relaxed">{step.desc}</p>
                </div>
                {i < STEPS.length - 1 && (
                  <div className="hidden lg:flex absolute top-1/2 -right-3 transform -translate-y-1/2 z-10">
                    <svg className="w-6 h-6 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative py-24 px-6 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900" />
        <div className="absolute inset-0 bg-[url('data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%23ffffff\' fill-opacity=\'0.03\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E')] opacity-50" />
        <div className="relative max-w-3xl mx-auto text-center text-white">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            Ready to document your property?
          </h2>
          <p className="text-slate-300 text-lg mb-10">
            Join DocuStay and document property status with confidence. Get started in minutes.
          </p>
          <div className="flex flex-col sm:flex-row justify-center gap-4">
            <Button
              variant="primary"
              onClick={() => setRoleSelector('signup')}
              className="px-10 py-4 bg-[#6B90F2] hover:bg-[#5a7ed9] border-0 text-white font-semibold rounded-xl text-base shadow-lg"
            >
              Get started
            </Button>
            <a
              href="#terms"
              className="inline-flex items-center justify-center px-10 py-4 rounded-xl text-sm font-medium border-2 border-white/30 text-white hover:bg-white/10 transition-colors"
            >
              Terms & Privacy
            </a>
          </div>
        </div>
      </section>

      <footer className="py-12 px-6 bg-slate-950">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col md:flex-row justify-between items-center gap-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-[#6B90F2] rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-lg">D</span>
              </div>
              <span className="text-lg font-semibold text-white">DocuStay</span>
            </div>
            <div className="flex flex-wrap justify-center gap-x-8 gap-y-2">
              <a href="#terms" className="text-slate-400 hover:text-white transition-colors text-sm font-medium">Terms of Service</a>
              <a href="#privacy" className="text-slate-400 hover:text-white transition-colors text-sm font-medium">Privacy Policy</a>
            </div>
            <p className="text-slate-400 text-sm text-center md:text-right w-full md:w-auto mt-4 md:mt-0">
              Contact us:{' '}
              <a href={supportMailtoHref()} className="text-[#6B90F2] hover:text-[#8aa8f5] font-medium underline-offset-2 hover:underline break-all">
                {SUPPORT_EMAIL}
              </a>
            </p>
          </div>
          <div className="mt-8 pt-8 border-t border-slate-800 text-center">
            <p className="text-slate-500 text-sm">
              © {new Date().getFullYear()} DocuStay. Documentation platform—not a law firm.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
