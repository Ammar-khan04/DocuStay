import React, { useState, useEffect } from 'react';
import { Card, Button } from '../../components/UI';
import { agreementsApi, API_URL, type AuthorityLetterDocResponse } from '../../services/api';

interface Props {
  token: string;
  notify: (t: 'success' | 'error', m: string) => void;
}

const ProviderAuthorityLetter: React.FC<Props> = ({ token, notify }) => {
  const [doc, setDoc] = useState<AuthorityLetterDocResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);
  const [signed, setSigned] = useState(false);
  const [form, setForm] = useState({
    signer_email: '',
    signer_name: '',
    acks: { read: false, temporary: false, vacate: false, electronic: false },
  });

  useEffect(() => {
    if (!token) {
      setError('Invalid link');
      setLoading(false);
      return;
    }
    agreementsApi
      .getAuthorityLetterByToken(token)
      .then((data) => {
        setDoc(data);
        if (data.already_signed) setSigned(true);
      })
      .catch((e) => {
        setError((e as Error)?.message ?? 'Failed to load authority letter');
      })
      .finally(() => setLoading(false));
  }, [token]);

  const handleSignWithDropbox = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!doc || !token) return;
    const allAcks = Object.values(form.acks).every(Boolean);
    if (!allAcks) {
      notify('error', 'Please accept all acknowledgments to sign.');
      return;
    }
    if (!form.signer_email?.trim() || !form.signer_name?.trim()) {
      notify('error', 'Please enter your name and email.');
      return;
    }
    setSigning(true);
    try {
      await agreementsApi.signAuthorityLetterWithDropbox(token, {
        signer_email: form.signer_email.trim(),
        signer_name: form.signer_name.trim(),
        acks: form.acks,
      });
      setSigned(true);
      notify('success', 'Check your email to complete signing. You will receive a link from Dropbox Sign.');
    } catch (e) {
      notify('error', (e as Error)?.message ?? 'Failed to send signature request.');
    } finally {
      setSigning(false);
    }
  };

  const openSignedPdf = () => {
    window.open(`${API_URL}/agreements/authority-letter/${encodeURIComponent(token)}/signed-pdf`, '_blank', 'noopener');
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto py-16 px-4 text-center">
        <p className="text-slate-600">Loading authority letter…</p>
      </div>
    );
  }
  if (error || !doc) {
    return (
      <div className="max-w-3xl mx-auto py-16 px-4 text-center">
        <p className="text-red-600">{error || 'Authority letter not found or link expired.'}</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto py-10 px-4">
      <Card className="p-6 border-slate-200 mb-6">
        <h1 className="text-xl font-bold text-slate-900 mb-1">DocuStay Authority Letter</h1>
        <p className="text-sm text-slate-600">
          To: <strong>{doc.provider_name}</strong>
          {doc.provider_type && (
            <span className="ml-2 capitalize">({doc.provider_type})</span>
          )}
        </p>
        {doc.property_name && (
          <p className="text-sm text-slate-600 mt-1">Property: {doc.property_name}</p>
        )}
        {doc.property_address && (
          <p className="text-sm text-slate-600">{doc.property_address}</p>
        )}
      </Card>

      <Card className="p-6 border-slate-200 mb-6">
        <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500 mb-3">Letter content</h2>
        <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans bg-slate-50 p-4 rounded-lg overflow-x-auto">
          {doc.content}
        </pre>
      </Card>

      {signed || doc.already_signed ? (
        <Card className="p-6 border-slate-200">
          <p className="text-slate-700 font-medium mb-2">
            {doc.signed_at ? `Signed on ${new Date(doc.signed_at).toLocaleDateString()}` : 'This letter has been signed.'}
          </p>
          {(doc.has_dropbox_signed_pdf ?? doc.already_signed) && (
            <Button variant="primary" onClick={openSignedPdf}>
              View signed PDF
            </Button>
          )}
        </Card>
      ) : (
        <Card className="p-6 border-slate-200">
          <h2 className="text-lg font-bold text-slate-900 mb-4">Sign this authority letter</h2>
          <p className="text-sm text-slate-600 mb-4">
            Enter your details and accept the acknowledgments below. You will receive an email from Dropbox Sign to complete the signature.
          </p>
          <form onSubmit={handleSignWithDropbox} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Your name</label>
              <input
                type="text"
                value={form.signer_name}
                onChange={(e) => setForm((f) => ({ ...f, signer_name: e.target.value }))}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-slate-900"
                placeholder="Full name"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Your email</label>
              <input
                type="email"
                value={form.signer_email}
                onChange={(e) => setForm((f) => ({ ...f, signer_email: e.target.value }))}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-slate-900"
                placeholder="email@example.com"
                required
              />
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium text-slate-700">Acknowledgments</p>
              {[
                { id: 'read', label: 'I have read the authority letter' },
                { id: 'temporary', label: 'I acknowledge this is for temporary occupancy authorization' },
                { id: 'vacate', label: 'I agree to the terms regarding vacate and removal' },
                { id: 'electronic', label: 'I consent to electronic signature' },
              ].map(({ id, label }) => (
                <label key={id} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.acks[id as keyof typeof form.acks]}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        acks: { ...f.acks, [id]: e.target.checked },
                      }))
                    }
                    className="rounded border-slate-300 text-blue-600"
                  />
                  <span className="text-sm text-slate-700">{label}</span>
                </label>
              ))}
            </div>
            <Button type="submit" variant="primary" disabled={signing}>
              {signing ? 'Sending…' : 'Sign with Dropbox Sign'}
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
};

export default ProviderAuthorityLetter;
