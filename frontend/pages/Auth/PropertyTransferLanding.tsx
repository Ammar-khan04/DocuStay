import React, { useEffect, useState } from 'react';
import { Button } from '../../components/UI';
import { HeroBackground } from '../../components/HeroBackground';
import { AuthCardLayout } from '../../components/AuthCardLayout';
import { authApi, DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY } from '../../services/api';

interface Props {
  token: string;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
}

/**
 * Public landing: owner offered a property via transfer link. Sign up (owner) or log in, then accept from dashboard.
 */
export const PropertyTransferLanding: React.FC<Props> = ({ token, navigate, setLoading }) => {
  const [info, setInfo] = useState<{
    email: string;
    property_name: string;
    already_accepted?: boolean;
    is_demo?: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = (token || '').trim();
    if (!t) {
      setError('Invalid link.');
      return;
    }
    setLoading(true);
    setError(null);
    authApi
      .getPropertyTransferInvite(t)
      .then((d) => {
        setInfo({
          email: d.email,
          property_name: d.property_name,
          already_accepted: d.already_accepted,
          is_demo: d.is_demo,
        });
      })
      .catch(() => {
        setError('This transfer link is invalid or has expired. Ask the current owner for a new link.');
      })
      .finally(() => setLoading(false));
  }, [token, setLoading]);

  const safeToken = (token || '').trim();

  return (
    <HeroBackground className="flex-grow">
      <AuthCardLayout
        leftPanel={
          <>
            <h2 className="text-2xl font-semibold text-slate-900 mb-3">Property ownership transfer</h2>
            <p className="text-slate-600 text-sm mb-8">
              The current owner has invited you to become the DocuStay owner of record for this property. Use the same
              email address you were invited with.
            </p>
          </>
        }
      >
        <div className="max-w-md w-full mx-auto space-y-4">
          {error && <p className="text-red-600 text-sm font-medium">{error}</p>}
          {!error && !info && <p className="text-slate-500 text-sm">Loading…</p>}
          {info && (
            <>
              <p className="text-slate-700 text-sm">
                Property: <strong>{info.property_name}</strong>
              </p>
              <p className="text-slate-700 text-sm">
                Invited email: <strong>{info.email}</strong>
              </p>
              {info.already_accepted ? (
                <p className="text-slate-600 text-sm">This transfer has already been completed. Sign in to your owner account to view your properties.</p>
              ) : (
                <p className="text-slate-600 text-sm">
                  Create an owner account or sign in. After you finish onboarding (if required), open your dashboard and accept the
                  transfer there.
                </p>
              )}
              <div className="flex flex-col sm:flex-row gap-3 pt-2">
                {!info.already_accepted && (
                  <Button
                    variant="primary"
                    className="flex-1"
                    onClick={() => {
                      try {
                        sessionStorage.setItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY, safeToken);
                      } catch {
                        /* ignore */
                      }
                      navigate(`register/owner-transfer/${safeToken}`);
                    }}
                  >
                    Create owner account
                  </Button>
                )}
                <Button
                  variant={info.already_accepted ? 'primary' : 'outline'}
                  className="flex-1"
                  onClick={() => {
                    try {
                      sessionStorage.setItem(DOCUSTAY_OWNER_TRANSFER_TOKEN_KEY, safeToken);
                    } catch {
                      /* ignore */
                    }
                    navigate(`login/owner-transfer/${safeToken}`);
                  }}
                >
                  {info.already_accepted ? 'Owner login' : 'Log in as owner'}
                </Button>
              </div>
            </>
          )}
        </div>
      </AuthCardLayout>
    </HeroBackground>
  );
};
