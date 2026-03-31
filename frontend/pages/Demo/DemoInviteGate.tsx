import React, { useEffect } from 'react';
import { DemoLogin } from './DemoLogin';
import type { UserSession } from '../../services/api';

interface DemoInviteGateProps {
  mode: 'invite' | 'manager_register';
  payload: string;
  sessionUser: UserSession | null;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onLogin: (u: UserSession) => void;
}

/**
 * Opening `#demo/invite/CODE` or `#demo/register/manager/TOKEN` requires a demo session first;
 * then continues to the normal invite / manager registration flow.
 */
export const DemoInviteGate: React.FC<DemoInviteGateProps> = ({
  mode,
  payload,
  sessionUser,
  navigate,
  setLoading,
  notify,
  onLogin,
}) => {
  const safePayload = (payload || '').trim();
  const targetView = mode === 'invite' ? `invite/${safePayload}` : `register/manager/${safePayload}`;

  useEffect(() => {
    if (sessionUser?.is_demo && safePayload) {
      navigate(targetView);
    }
  }, [sessionUser?.is_demo, safePayload, targetView, navigate]);

  if (sessionUser?.is_demo) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[240px]">
        <p className="text-slate-500 text-sm">Opening invitation…</p>
      </div>
    );
  }

  if (!safePayload) {
    return (
      <div className="flex-grow flex items-center justify-center min-h-[240px]">
        <p className="text-slate-500 text-sm">Invalid demo invitation link.</p>
      </div>
    );
  }

  return (
    <DemoLogin
      navigate={navigate}
      setLoading={setLoading}
      notify={notify}
      onLogin={onLogin}
      postLoginNavigate={targetView}
    />
  );
};
