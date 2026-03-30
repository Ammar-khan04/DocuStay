import React from 'react';
import { SUPPORT_EMAIL, SUPPORT_LEGAL_ENTITY_NAME, supportMailtoHref } from '../../constants/supportContact';

const SECTIONS = [
  { id: 'collect', label: 'Information We Collect' },
  { id: 'use', label: 'How We Use Your Information' },
  { id: 'security', label: 'Data Security' },
  { id: 'retention', label: 'Data Retention' },
  { id: 'sharing', label: 'Information Sharing' },
  { id: 'rights', label: 'Your Rights and Choices' },
  { id: 'contact', label: 'Contact Us' },
];

const PrivacyPolicy: React.FC<{ navigate: (v: string) => void }> = ({ navigate }) => {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-50">
      {/* Header banner */}
      <header className="relative overflow-hidden bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%23ffffff\' fill-opacity=\'0.03\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E')] opacity-50" />
        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-12 md:py-16">
          <div className="flex items-center gap-4 mb-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white/10 backdrop-blur-sm border border-white/20">
              <svg className="w-7 h-7 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">Privacy Policy</h1>
              <p className="text-slate-400 text-sm mt-1">Last Updated: March 11, 2026</p>
            </div>
          </div>
          <p className="text-slate-300 max-w-2xl text-sm md:text-base leading-relaxed">
            DOCUSTAY LLC (&quot;DocuStay,&quot; &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;) is committed to protecting your privacy. This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our documentation platform and related services (the &quot;Services&quot;).
          </p>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-12 md:py-16">
        <div className="flex flex-col lg:flex-row gap-12">
          {/* Sticky table of contents */}
          <aside className="lg:w-64 shrink-0">
            <nav className="lg:sticky lg:top-24 space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-4">On this page</p>
              {SECTIONS.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  onClick={(e) => { e.preventDefault(); document.getElementById(s.id)?.scrollIntoView({ behavior: 'smooth' }); }}
                  className="block py-2 text-sm text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors rounded-lg px-3 -mx-3"
                >
                  {s.label}
                </a>
              ))}
            </nav>
          </aside>

          {/* Main content */}
          <main className="flex-1 min-w-0">
            <div className="space-y-8">
              <section id="collect" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">1</span>
                    Information We Collect
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">We collect information to provide and improve our Services.</p>
                  <ul className="space-y-3 mb-4">
                    <li className="flex gap-2">
                      <span className="text-[#6B90F2] mt-1">•</span>
                      <span className="text-slate-600"><strong className="text-slate-800">Account Information:</strong> When you create a DocuStay account, we collect your name, email address, and password. For business accounts, we may collect the legal entity name and business address.</span>
                    </li>
                    <li className="flex gap-2">
                      <span className="text-[#6B90F2] mt-1">•</span>
                      <span className="text-slate-600"><strong className="text-slate-800">Property and Occupancy Data:</strong> We collect and store the information you provide about your properties (e.g., address) and the authorization records you create, which may include guest names and the start/end dates of authorized stays.</span>
                    </li>
                    <li className="flex gap-2">
                      <span className="text-[#6B90F2] mt-1">•</span>
                      <span className="text-slate-600"><strong className="text-slate-800">Identity Verification:</strong> In some cases, we may request information to verify your identity for security and fraud prevention purposes.</span>
                    </li>
                    <li className="flex gap-2">
                      <span className="text-[#6B90F2] mt-1">•</span>
                      <span className="text-slate-600"><strong className="text-slate-800">Usage Information:</strong> We automatically collect data about how you interact with our Services, such as your IP address, browser type, and actions taken on the platform.</span>
                    </li>
                  </ul>
                </div>
              </section>

              <section id="use" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">2</span>
                    How We Use Your Information
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">We use the information we collect to:</p>
                  <ul className="space-y-2 mb-4">
                    <li className="flex gap-2 text-slate-600"><span className="text-emerald-500 mt-1">✓</span>Provide, operate, and maintain the Services.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-emerald-500 mt-1">✓</span>Create and manage your account.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-emerald-500 mt-1">✓</span>Send you service-related communications, including security alerts and support messages.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-emerald-500 mt-1">✓</span>Monitor and analyze usage to improve the user experience.</li>
                    <li className="flex gap-2 text-slate-600"><span className="text-emerald-500 mt-1">✓</span>Enforce our Terms of Service and comply with legal obligations.</li>
                  </ul>
                </div>
              </section>

              <section id="security" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">3</span>
                    Data Security
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    We implement industry-standard security measures to protect your information. Data is encrypted in transit and at rest. Access to personally identifiable information is restricted to authorized personnel who require it to perform their job functions.
                  </p>
                </div>
              </section>

              <section id="retention" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">4</span>
                    Data Retention
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    We retain your information for as long as your account is active or as necessary to provide you with the Services. Documentation records, including property status logs and guest authorization timelines, are core components of the Service and are retained as part of your account history. We will also retain information as necessary to comply with our legal obligations, resolve disputes, and enforce our agreements.
                  </p>
                </div>
              </section>

              <section id="sharing" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">5</span>
                    Information Sharing
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    We do not sell your personal information. We may share your information with third-party service providers who perform services on our behalf (e.g., cloud hosting, payment processing), but only to the extent necessary for them to provide such services. We may also disclose information if required by law or in response to a valid legal process.
                  </p>
                </div>
              </section>

              <section id="rights" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">6</span>
                    Your Rights and Choices
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    Depending on your jurisdiction, you may have rights to access, correct, or delete your personal information. You can manage your account information through your account settings. For other requests, please contact us at the email address below.
                  </p>
                </div>
              </section>

              <section id="contact" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">7</span>
                    Contact Us
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    If you have any questions about this Privacy Policy, please contact us at:
                  </p>
                  <div className="rounded-xl bg-slate-50 border border-slate-200 p-4">
                    <p className="text-slate-800 font-semibold">{SUPPORT_LEGAL_ENTITY_NAME}</p>
                    <p className="text-slate-600">Email: <a href={supportMailtoHref()} className="text-[#6B90F2] hover:underline">{SUPPORT_EMAIL}</a></p>
                  </div>
                </div>
              </section>
            </div>

            {/* Footer CTA */}
            <div className="mt-12 rounded-2xl bg-gradient-to-br from-slate-800 to-slate-900 p-8 md:p-10 text-white">
              <h3 className="text-lg font-semibold mb-2">Related documents</h3>
              <p className="text-slate-300 text-sm mb-6">Review our Terms of Service for the full agreement governing your use of DocuStay.</p>
              <div className="flex flex-wrap gap-4">
                <button onClick={() => navigate('terms')} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 font-medium text-sm transition-colors">
                  Terms of Service
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" /></svg>
                </button>
                <button onClick={() => navigate('')} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-slate-300 hover:text-white hover:bg-white/10 font-medium text-sm transition-colors">
                  Back to Home
                </button>
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
};

export default PrivacyPolicy;
