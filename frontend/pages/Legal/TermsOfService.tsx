import React from 'react';
import { SUPPORT_EMAIL, SUPPORT_LEGAL_ENTITY_NAME, supportMailtoHref } from '../../constants/supportContact';

const SECTIONS = [
  { id: 'service', label: 'The DocuStay Service' },
  { id: 'accounts', label: 'Account Registration and Responsibilities' },
  { id: 'use', label: 'Use of the Services' },
  { id: 'disclaimer', label: 'Disclaimer of Legal Advice and Tenancy Determination' },
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
              <p className="text-slate-400 text-sm mt-1">Last Updated: March 11, 2026</p>
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
                  <p className="text-slate-600 leading-relaxed">
                    DocuStay provides a documentation and record-keeping platform for residential property. The Services are designed to allow property owners, tenants, and authorized managers (&quot;Users&quot;) to create, manage, and store records related to property status and the authorized presence of temporary guests. This includes generating and recording guest acknowledgments for defined periods and maintaining a chronological log of property status events.
                  </p>
                </div>
              </section>

              <section id="accounts" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">2</span>
                    Account Registration and Responsibilities
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    You must be at least 18 years old to create an account. You agree to provide accurate and complete information upon registration. You are responsible for all activities that occur under your account, including maintaining the confidentiality of your password. You represent and warrant that you have the full legal authority to provide information regarding the properties and individuals you document on the platform.
                  </p>
                </div>
              </section>

              <section id="use" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">3</span>
                    Use of the Services
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    You agree to use the Services only for their intended purpose as a documentation tool. You are solely responsible for your compliance with all applicable laws, regulations, and any agreements you may have with other parties (including leases, co-tenancy agreements, or guest agreements). You agree not to misuse the Services for any illegal, fraudulent, or unauthorized purpose.
                  </p>
                </div>
              </section>

              <section id="disclaimer" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">4</span>
                    Disclaimer of Legal Advice and Tenancy Determination
                  </h2>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    DocuStay is a documentation platform, not a law firm. We do not provide legal advice, and your use of the Services does not create an attorney-client relationship. The information provided on the platform, including jurisdiction-specific renewal cycle recommendations and template documents, is for informational and documentation purposes only. It is not a substitute for advice from a qualified attorney licensed in your jurisdiction.
                  </p>
                  <p className="text-slate-600 leading-relaxed">
                    The platform does not, and cannot, determine legal tenancy status. The creation of a guest authorization record through the Services does not guarantee that a guest will not be deemed a tenant by a court of law. The legal status of an occupant is determined by the specific facts of the situation and applicable law, not by the records created on this platform. The Services are intended to provide clear evidence of your intent and the agreements you have made, which is one of many factors a court may consider.
                  </p>
                </div>
              </section>

              <section id="liability" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">5</span>
                    Limitation of Liability
                  </h2>
                  <div className="rounded-xl bg-slate-100/80 border border-slate-200 p-4">
                    <p className="text-slate-700 text-sm leading-relaxed font-medium">
                      TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, DOCUSTAY SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS OR REVENUES, WHETHER INCURRED DIRECTLY OR INDIRECTLY, OR ANY LOSS OF DATA, USE, GOODWILL, OR OTHER INTANGIBLE LOSSES, RESULTING FROM (A) YOUR ACCESS TO OR USE OF OR INABILITY TO ACCESS OR USE THE SERVICES; (B) ANY DISPUTE BETWEEN YOU AND A TENANT, GUEST, OR OTHER THIRD PARTY; (C) ANY RELIANCE PLACED BY YOU ON THE COMPLETENESS, ACCURACY, OR EXISTENCE OF ANY DOCUMENTATION OR JURISDICTIONAL INFORMATION PROVIDED BY THE SERVICES. IN NO EVENT SHALL DOCUSTAY&apos;S AGGREGATE LIABILITY EXCEED THE GREATER OF ONE HUNDRED U.S. DOLLARS (U.S. $100.00) OR THE AMOUNT YOU PAID DOCUSTAY, IF ANY, IN THE PAST SIX MONTHS FOR THE SERVICES GIVING RISE TO THE CLAIM.
                    </p>
                  </div>
                </div>
              </section>

              <section id="termination" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">6</span>
                    Account Suspension and Termination
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    We reserve the right to suspend or terminate your account at any time for any reason, including, but not limited to, a violation of these Terms or if your use of the Services creates a risk or potential legal exposure for us. We will make reasonable efforts to notify you by the email address associated with your account.
                  </p>
                </div>
              </section>

              <section id="general" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">7</span>
                    General Provisions
                  </h2>
                  <p className="text-slate-600 leading-relaxed">
                    These Terms shall be governed by the laws of the State of Washington, without regard to its conflict of law provisions. These Terms constitute the entire agreement between you and DocuStay regarding the Services and supersede any prior agreements. We may revise these Terms from time to time, and the most current version will always be posted on our website. By continuing to use the Services after revisions become effective, you agree to be bound by the revised Terms.
                  </p>
                </div>
              </section>

              <section id="contact" className="scroll-mt-24">
                <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm shadow-slate-200/50 p-6 md:p-8">
                  <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 text-sm font-bold">8</span>
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
