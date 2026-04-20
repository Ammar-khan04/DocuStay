
import React, { useState, useEffect } from 'react';
import { Card, Input, Button } from '../../components/UI';
import { invitationsApi, propertiesApi, buildGuestInviteUrl } from '../../services/api';
import { UserSession } from '../../types';
import { copyToClipboard } from '../../utils/clipboard';
import { toUserFriendlyInvitationError } from '../../utils/invitationErrors';
import { isValidInviteEmailFormat } from '../../utils/emailValidation';

const InviteGuest: React.FC<{ user: UserSession | null, navigate: (v: string) => void, setLoading: (l: boolean) => void, notify: (t: 'success' | 'error', m: string) => void }> = ({ user, navigate, setLoading, notify }) => {
  const [formData, setFormData] = useState({ guest_name: '', guest_email: '', checkin_date: '', checkout_date: '' });
  const [inviteLink, setInviteLink] = useState('');
  const [showInviteModal, setShowInviteModal] = useState(false);

  const [properties, setProperties] = useState<Array<{ id: number; name: string | null; street: string; city: string; state: string; zip_code: string | null }>>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  useEffect(() => {
    propertiesApi.list()
      .then((list) => {
        setProperties(list);
        if (list.length > 0 && !propertyId) setPropertyId(list[0].id);
      })
      .catch(() => {});
  }, []);
  const selectedProperty = properties.find((p) => p.id === propertyId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!propertyId) {
      notify('error', 'Please add a property first, then create an invitation.');
      return;
    }
    setLoading(true);
    try {
      const guestEmailTrim = (formData.guest_email || '').trim();
      if (!guestEmailTrim) {
        notify('error', 'Guest email is required.');
        setLoading(false);
        return;
      }
      if (!isValidInviteEmailFormat(guestEmailTrim)) {
        notify('error', 'Please enter a valid email address.');
        setLoading(false);
        return;
      }
      if (!formData.checkin_date || !formData.checkout_date) {
        notify('error', 'Please select both start and end dates for the stay.');
        setLoading(false);
        return;
      }
      if (formData.checkout_date <= formData.checkin_date) {
        notify('error', 'End date must be after start date.');
        return;
      }
      const result = await invitationsApi.create({
        owner_id: user?.user_id ?? '',
        property_id: propertyId ?? undefined,
        guest_name: formData.guest_name,
        guest_email: guestEmailTrim,
        checkin_date: formData.checkin_date,
        checkout_date: formData.checkout_date,
      });
      setLoading(false);
      if (result.status === 'success' && result.data?.invitation_code) {
        notify('success', 'Invitation generated and sent!');
        const inviteCode = result.data.invitation_code;
        const link = buildGuestInviteUrl(inviteCode, { isDemo: Boolean(user?.is_demo) });
        setInviteLink(link);
        setShowInviteModal(true);
      } else {
        notify('error', result.message || 'We couldn\'t create a valid invitation link. Please try again.');
      }
    } catch (err) {
      setLoading(false);
      notify('error', toUserFriendlyInvitationError((err as Error)?.message ?? 'Invitation failed.'));
    }
  };

  const closeInviteModal = () => {
    setShowInviteModal(false);
    setInviteLink('');
    navigate('dashboard');
  };

  const handleCopyLink = async () => {
    const ok = await copyToClipboard(inviteLink);
    if (ok) notify('success', 'Invite link copied to clipboard.');
    else notify('error', 'Copy failed. Please copy the link manually.');
  };

  return (
    <div className="max-w-5xl mx-auto py-8 px-4">
      {/* Back Button */}
      <button onClick={() => navigate('dashboard')} className="flex items-center gap-2 text-slate-600 hover:text-slate-800 mb-8 font-bold text-sm uppercase tracking-widest transition-colors">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7"></path></svg>
        Back to Dashboard
      </button>

      <div className="flex flex-col lg:flex-row gap-8">
        {/* Main Form */}
        <div className="lg:w-2/3">
          <Card className="p-10">
            <h2 className="text-3xl font-bold text-slate-800 mb-2">Invite a Temporary Guest</h2>
            <p className="text-slate-500 mb-10">This will generate a guest registration link for your property. The guest will sign authorization and stay documentation.</p>
            
            <form onSubmit={handleSubmit} className="space-y-8">
               <div className="bg-white/65 backdrop-blur-xl border border-slate-200 rounded-2xl p-6 mb-8">
                  <label className="block text-xs uppercase tracking-widest font-bold text-slate-500 mb-2">Target Property</label>
                  {properties.length === 0 ? (
                    <div className="flex items-center gap-4 text-amber-600">
                      <svg className="w-6 h-6 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                      <p className="text-sm">Add a property first to invite a guest.</p>
                      <Button variant="outline" type="button" onClick={() => navigate('add-property')} className="flex-shrink-0">Add Property</Button>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center gap-4 mb-3">
                        <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center text-white">
                          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"></path></svg>
                        </div>
                        <div>
                          <h4 className="font-bold text-slate-800 text-lg">{selectedProperty?.name || [selectedProperty?.street, selectedProperty?.city, selectedProperty?.state].filter(Boolean).join(', ') || 'Property'}</h4>
                          <p className="text-sm text-slate-600">{[selectedProperty?.street, selectedProperty?.city, selectedProperty?.state, selectedProperty?.zip_code].filter(Boolean).join(', ') || '—'}</p>
                        </div>
                      </div>
                      {properties.length > 1 && (
                        <select
                          value={propertyId ?? ''}
                          onChange={(e) => setPropertyId(Number(e.target.value))}
                          className="w-full mt-2 px-4 py-2 bg-white border border-slate-300 rounded-lg text-slate-800 text-sm"
                        >
                          {properties.map((p) => (
                            <option key={p.id} value={p.id}>{p.name || `${p.city}, ${p.state}`}</option>
                          ))}
                        </select>
                      )}
                    </>
                  )}
               </div>

              <div className="space-y-4">
                <Input label="Guest name" name="guest_name" value={formData.guest_name} onChange={e => setFormData({ ...formData, guest_name: e.target.value })} placeholder="Full name of your guest" />
                <div>
                  <Input label="Guest email (required)" name="guest_email" type="email" value={formData.guest_email} onChange={e => setFormData({ ...formData, guest_email: e.target.value })} placeholder="email@example.com" required />
                  <p className="text-xs text-slate-500 mt-1.5">Only this email can sign up or sign in to accept the invitation.</p>
                </div>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <Input label="Stay start date" name="checkin_date" type="date" value={formData.checkin_date} onChange={e => setFormData({ ...formData, checkin_date: e.target.value })} required />
                <Input label="Stay end date" name="checkout_date" type="date" value={formData.checkout_date} onChange={e => setFormData({ ...formData, checkout_date: e.target.value })} required />
              </div>
              <p className="text-sm text-slate-500 ml-1">These dates will be shown to the guest and used for the stay agreement.</p>

              <p className="text-xs text-slate-600 rounded-xl border border-slate-200 bg-slate-50 p-4">Stay end reminders are always on: if the stay end date passes without you updating (checkout or renewal), you&apos;ll get alerts 48h before and on the end date, then the system will auto-set the property to vacant after 48h. Alerts are sent by email and dashboard notification.</p>

              <div className="pt-6 border-t border-slate-200 flex gap-4">
                <Button variant="outline" onClick={() => navigate('dashboard')} className="flex-1">Discard</Button>
                <Button type="submit" className="flex-2 py-4 text-xl" disabled={properties.length === 0}>Generate invitation</Button>
              </div>
            </form>
          </Card>
        </div>

        {/* Side panel */}
        <div className="lg:w-1/3">
          <Card className="p-6 bg-gradient-to-br from-slate-100 to-blue-50">
            <p className="text-sm text-slate-600">Share the generated link with your guest. They will sign in or create an account, then read and sign the agreement on their dashboard to confirm the stay.</p>
          </Card>
        </div>
      </div>

      {showInviteModal && (
        <>
          <div className="fixed inset-0 bg-slate-900/60 z-40" onClick={closeInviteModal}></div>
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-xl">
              <div className="p-6 border-b border-gray-800 flex items-center justify-between bg-white/60 backdrop-blur-md">
                <h3 className="text-lg font-bold text-white">Guest Invite Link</h3>
                <button onClick={closeInviteModal} className="text-gray-400 hover:text-white">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-sm text-slate-600">Share this link with your guest to complete registration.</p>
                <div className="bg-slate-100 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 break-all">
                  {inviteLink}
                </div>
                <div className="flex gap-3">
                  <Button variant="outline" onClick={handleCopyLink} className="flex-1">Copy Link</Button>
                  <Button onClick={closeInviteModal} className="flex-1">Done</Button>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
};

export default InviteGuest;
