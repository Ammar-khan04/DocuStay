import React from 'react';
import { SUPPORT_EMAIL, SUPPORT_LEGAL_ENTITY_NAME, supportMailtoHref } from '../../constants/supportContact';

const SECTIONS = [
  { id: 'service', label: 'The DocuStay Service' },
  { id: 'accounts', label: 'Account Registration and Responsibilities' },
  { id: 'use', label: 'Use of the Services' },
  { id: 'disclaimer', label: 'Disclaimer of Legal Advice and No Tenancy Determination' },
  { id: 'platform', label: 'Platform Role; No Agency or Fiduciary Relationship' },
  { id: 'reliance', label: 'Reliance and Third-Party Use' },
  { id: 'liability', label: 'Limitation of Liability' },
  { id: 'termination', label: 'Account Suspension and Termination' },
  { id: 'general', label: 'General Provisions' },
  { id: 'contact', label: 'Contact Us' },
];

const TermsOfService: React.FC<{ navigate: (v: string) => void }> = ({ navigate }) => {

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-50">
      {/* Header banner */}
      <header className="relative overflow-hidden bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%23ffffff\' fill-opacity=\'0.03\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E')] opacity-50" />
        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-12 md:py-16">
          <div className="flex items-center gap-4 mb-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white/10 backdrop-blur-sm border border-white/20">
              <svg className="w-7 h-7 text-sky-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">Terms of Service</h1>
              <p className="text-slate-400 text-sm mt-1">Last Updated: April 24, 2026</p>
            </div>
          </div>
          <p className="text-slate-300 max-w-2xl text-sm md:text-base leading-relaxed">
            Welcome to DocuStay. These Terms of Service (&quot;Terms&quot;) govern your access to and use of the DocuStay platform and services (the &quot;Services&quot;), operated by DOCUSTAY LLC (&quot;DocuStay,&quot; &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;). By creating an account or using our Services, you agree to be bound by these Terms.
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
              <section id="service" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">1</span>
                    The DocuStay Service
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay provides a documentation and record-keeping platform for residential property use. The Services are designed to allow property owners, tenants, and authorized users (&quot;Users&quot;) to create, manage, and store records related to property status and the authorized presence of individuals at a property.
                  </p>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    The Services include the generation and storage of guest acknowledgments, authorization records, and a chronological log of property-related events (the &quot;Event Ledger&quot;). These records are generated based on user-provided inputs and system-logged activity.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    DocuStay operates solely as a neutral documentation and record-keeping system. The Services are not intended to establish, modify, or determine legal rights, occupancy status, tenancy status, or property interests.
                  </p>
                </div>
              </section>

              <section id="accounts" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">2</span>
                    Account Registration and Responsibilities
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    You must be at least 18 years of age to create an account. You agree to provide accurate, current, and complete information and to maintain the security of your account credentials. You represent and warrant that you have the legal authority to provide information regarding the property, individuals, and authorizations entered into the platform.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    You acknowledge that DocuStay does not independently verify the accuracy of user-provided information and relies on Users for the completeness and correctness of all submitted data.
                  </p>
                </div>
              </section>

              <section id="use" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">3</span>
                    Use of the Services
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    You agree to use the Services solely for their intended purpose as a documentation tool. You are solely responsible for:
                  </p>
                  <ul className="list-disc pl-5 space-y-2 text-slate-600 leading-relaxed mb-4">
                    <li>your compliance with applicable laws and regulations;</li>
                    <li>the legality and enforceability of any agreements you enter into outside the platform; and</li>
                    <li>the accuracy and completeness of the information you provide.</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    You agree not to use the Services for any unlawful, fraudulent, misleading, or unauthorized purpose.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    You further acknowledge that the creation of documentation through the Services does not, by itself, create legal authorization, tenancy rights, or enforceable occupancy status.
                  </p>
                </div>
              </section>

              <section id="disclaimer" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">4</span>
                    Disclaimer of Legal Advice and No Tenancy Determination
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay is not a law firm and does not provide legal advice. Your use of the Services does not create an attorney-client relationship.
                  </p>
                  <p className="text-slate-600 leading-relaxed mb-2">
                    All information provided through the platform, including:
                  </p>
                  <ul className="list-disc pl-5 space-y-1 text-slate-600 leading-relaxed mb-4">
                    <li>jurisdiction-specific information,</li>
                    <li>renewal cycle references,</li>
                    <li>authorization records, and</li>
                    <li>system-generated outputs,</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    is provided for informational and documentation purposes only and should not be relied upon as legal advice.
                  </p>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay does not determine, adjudicate, or represent the legal status of any occupant, guest, or tenant. The legal status of any individual in relation to a property is determined by applicable law and the specific facts of each situation, not by the records created within the platform.
                  </p>
                  <p className="text-slate-600 leading-relaxed mb-2">
                    The creation or existence of any record within the Services:
                  </p>
                  <ul className="list-disc pl-5 space-y-2 text-slate-600 leading-relaxed mb-4">
                    <li>does not guarantee that an individual will not be deemed a tenant;</li>
                    <li>does not establish legal authorization enforceable against third parties; and</li>
                    <li>does not replace the need for legally compliant agreements or legal counsel.</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed">
                    Platform records are intended to serve as evidence of user actions and stated intent only and are one of many factors a court or authority may consider.
                  </p>
                </div>
              </section>

              <section id="platform" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">5</span>
                    Platform Role; No Agency or Fiduciary Relationship
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay acts solely as a neutral technology provider. Nothing in the Services creates:
                  </p>
                  <ul className="list-disc pl-5 space-y-2 text-slate-600 leading-relaxed mb-4">
                    <li>an agency relationship,</li>
                    <li>a property management relationship,</li>
                    <li>a fiduciary duty, or</li>
                    <li>enforcement authority on the part of DocuStay.</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed">
                    Any authority granted through user-generated documents, including any power of attorney, is created between Users and is not exercised independently by DocuStay. DocuStay does not act on behalf of Users in dealings with third parties, law enforcement, or governmental authorities.
                  </p>
                </div>
              </section>

              <section id="reliance" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">6</span>
                    Reliance and Third-Party Use
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-2">You acknowledge that:</p>
                  <ul className="list-disc pl-5 space-y-2 text-slate-600 leading-relaxed mb-4">
                    <li>third parties may view or rely on documentation generated through the Services; and</li>
                    <li>such reliance is outside the control of DocuStay.</li>
                  </ul>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay makes no representations or warranties regarding how any third party, including courts, law enforcement, or administrative bodies, will interpret or rely upon platform records.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    You agree that any use of platform-generated documentation in disputes or proceedings is at your sole risk.
                  </p>
                </div>
              </section>

              <section id="liability" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">7</span>
                    Limitation of Liability
                  </h2>
                  <div className="rounded-xl bg-slate-100/80 border border-slate-200 p-4 space-y-3">
                    <p className="text-slate-700 text-sm leading-relaxed font-medium">
                      TO THE MAXIMUM EXTENT PERMITTED BY LAW, DOCUSTAY SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS, DATA, USE, OR GOODWILL.
                    </p>
                    <p className="text-slate-700 text-sm leading-relaxed font-medium">
                      THIS INCLUDES, WITHOUT LIMITATION:
                    </p>
                    <ul className="list-disc pl-5 space-y-1 text-slate-700 text-sm leading-relaxed font-medium">
                      <li>ANY DISPUTE BETWEEN USERS OR THIRD PARTIES;</li>
                      <li>ANY DETERMINATION OF TENANCY OR OCCUPANCY STATUS;</li>
                      <li>ANY ACTION TAKEN OR NOT TAKEN BASED ON PLATFORM RECORDS; OR</li>
                      <li>ANY RELIANCE ON THE COMPLETENESS OR ACCURACY OF DOCUMENTATION GENERATED THROUGH THE SERVICES.</li>
                    </ul>
                    <p className="text-slate-700 text-sm leading-relaxed font-medium">
                      IN NO EVENT SHALL DOCUSTAY&apos;S TOTAL LIABILITY EXCEED THE GREATER OF:
                    </p>
                    <ul className="list-disc pl-5 space-y-1 text-slate-700 text-sm leading-relaxed font-medium">
                      <li>ONE HUNDRED U.S. DOLLARS ($100), OR</li>
                      <li>THE AMOUNT PAID BY YOU TO DOCUSTAY IN THE SIX (6) MONTHS PRECEDING THE CLAIM.</li>
                    </ul>
                  </div>
                </div>
              </section>

              <section id="termination" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">8</span>
                    Account Suspension and Termination
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-3">
                    We reserve the right to suspend or terminate accounts at any time where:
                  </p>
                  <ul className="list-disc pl-5 space-y-2 text-slate-600 leading-relaxed">
                    <li>there is a violation of these Terms;</li>
                    <li>there is misuse of the platform; or</li>
                    <li>continued use presents legal or operational risk.</li>
                  </ul>
                </div>
              </section>

              <section id="general" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">9</span>
                    General Provisions
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    These Terms are governed by the laws of the State of Washington. DocuStay may update these Terms from time to time. Continued use of the Services constitutes acceptance of the revised Terms.
                  </p>
                </div>
              </section>

              <section id="contact" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 min-w-8 px-1 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-xs font-bold">10</span>
                    Contact Us
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    If you have any questions about these Terms of Service, please contact us at:
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
              <p className="text-slate-300 text-sm mb-6">Review our Privacy Policy to understand how we collect, use, and protect your data.</p>
              <div className="flex flex-wrap gap-4">
                <button onClick={() => navigate('privacy')} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 font-medium text-sm transition-colors">
                  Privacy Policy
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

export default TermsOfService;
