
import React, { useState, useEffect, useRef } from 'react';
import { Card, Button } from '../../components/UI';
import { authApi } from '../../services/api';
import { getOwnerSignupErrorFriendly } from '../../utils/ownerSignupErrors';
import {
  EMAIL_VERIFICATION_CHECK_SPAM_TOAST,
  EMAIL_VERIFICATION_RESEND_TOAST,
} from '../../utils/verificationMessages';

interface Props {
  verification: {
    userId: string;
    type: 'email' | 'phone';
    expectedCode?: string;
    generatedAt: string;
  };
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
  onVerified: (user: any) => void;
}

const VerifyContact: React.FC<Props> = ({ verification, navigate, setLoading, notify, onVerified }) => {
  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [timer, setTimer] = useState(60);
  const [attempts, setAttempts] = useState(0);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  /** One toast per pending verification (sessionStorage survives refresh so we don't spam). */
  useEffect(() => {
    if (verification.type !== 'email') return;
    try {
      const key = `ds_verify_email_spam_hint_${verification.userId}`;
      if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, '1');
    } catch {
      /* ignore storage errors */
    }
    notify('success', EMAIL_VERIFICATION_CHECK_SPAM_TOAST);
  }, [verification.type, verification.userId, notify]);

  useEffect(() => {
    if (timer > 0) {
      const interval = setInterval(() => setTimer(t => t - 1), 1000);
      return () => clearInterval(interval);
    }
  }, [timer]);

  const handleChange = (index: number, value: string) => {
    if (isNaN(Number(value))) return;
    const newOtp = [...otp];
    newOtp[index] = value.slice(-1);
    setOtp(newOtp);

    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const data = e.clipboardData.getData('text').slice(0, 6).split('');
    if (data.every(d => !isNaN(Number(d)))) {
      const newOtp = [...otp];
      data.forEach((d, i) => newOtp[i] = d);
      setOtp(newOtp);
      inputRefs.current[5]?.focus();
    }
  };

  const handleVerify = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const code = otp.join('');
    if (code.length < 6) return;
    if (verifying) return;

    setInlineError(null);
    setVerifying(true);
    setLoading(true);
    try {
      const result = await authApi.verifyEmail(verification.userId, code);
      setLoading(false);
      setVerifying(false);
      // Only treat as success when API returned success and we have valid session data (token + user).
      const hasValidSession = result.status === 'success' && result.data && result.data.token && result.data.user_id;
      if (hasValidSession) {
        notify('success', 'Verification successful! You’ll complete the next step shortly.');
        onVerified(result.data);
      } else {
        setAttempts(prev => prev + 1);
        const friendly = getOwnerSignupErrorFriendly(result.message || 'Verification failed.');
        setInlineError(friendly.message);
        notify('error', friendly.message);
        setOtp(['', '', '', '', '', '']);
        inputRefs.current[0]?.focus();
      }
    } catch (err) {
      setLoading(false);
      setVerifying(false);
      setAttempts(prev => prev + 1);
      const friendly = getOwnerSignupErrorFriendly((err as Error)?.message);
      setInlineError(friendly.message);
      notify('error', friendly.message);
      setOtp(['', '', '', '', '', '']);
      inputRefs.current[0]?.focus();
    }
  };

  useEffect(() => {
    if (otp.join('').length === 6) {
      handleVerify();
    }
  }, [otp]);

  return (
    <div className="flex-grow flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md mb-4">
        <button onClick={() => navigate('register')} className="flex items-center gap-2 text-slate-600 hover:text-slate-800 font-bold text-sm uppercase tracking-widest transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7"></path></svg>
          Back to Registration
        </button>
      </div>
      <Card className="max-w-md w-full p-10 text-center relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-600 via-purple-600 to-pink-600"></div>
        
        <div className="w-20 h-20 bg-blue-500/10 text-blue-500 rounded-3xl flex items-center justify-center mx-auto mb-8 shadow-inner">
          {verification.type === 'email' ? (
            <svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
          ) : (
            <svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"></path></svg>
          )}
        </div>
        
        <h2 className="text-3xl font-bold text-slate-800 mb-2">Verify Your Account</h2>
        <p className="text-slate-600 mb-6 leading-relaxed">
          Enter the 6-digit verification code we sent to your <span className="text-slate-800 font-bold">{verification.type}</span>.
        </p>
        {verification.type === 'email' && (
          <p className="text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-6 text-left">
            <strong className="font-semibold">Can&apos;t find the email?</strong> Check your{' '}
            <span className="font-semibold">spam or junk</span> folder — verification messages often land there.
          </p>
        )}

        {inlineError && (
          <div className="mb-4 p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm" role="alert">
            {inlineError}
          </div>
        )}
        <div className="flex justify-between gap-3 mb-10" onPaste={handlePaste}>
          {otp.map((digit, i) => (
            <input
              key={i}
              ref={el => { inputRefs.current[i] = el; }}
              type="text"
              inputMode="numeric"
              maxLength={1}
              value={digit}
              onChange={e => handleChange(i, e.target.value)}
              onKeyDown={e => handleKeyDown(i, e)}
              className="w-12 h-16 md:w-14 md:h-20 bg-slate-100 border-2 border-slate-300 rounded-2xl text-center text-2xl font-bold text-slate-800 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-sm"
            />
          ))}
        </div>
        
        <div className="space-y-6">
          <Button onClick={() => handleVerify()} disabled={otp.join('').length < 6 || verifying} className="w-full py-4 text-lg">Verify & Proceed</Button>
          
          <div className="flex flex-col items-center gap-4">
            <div className="text-sm text-slate-500">
              Didn't receive the code? 
              {timer > 0 ? (
                <span className="text-slate-600 ml-1">Resend in <span className="font-bold">{timer}s</span></span>
              ) : (
                <button 
                  type="button"
                  onClick={async () => {
                    const res = await authApi.resendVerification(verification.userId);
                    setTimer(60);
                    if (res.status === 'success')
                      notify(
                        'success',
                        res.message && res.message.trim()
                          ? `${res.message.trim()} ${EMAIL_VERIFICATION_RESEND_TOAST}`
                          : EMAIL_VERIFICATION_RESEND_TOAST,
                      );
                    else notify('error', res.message ?? 'Failed to resend.');
                  }}
                  className="text-blue-600 font-bold hover:text-blue-700 ml-1 transition-colors underline"
                >
                  Resend now
                </button>
              )}
            </div>
          </div>
        </div>
        
        <div className="mt-8 pt-6 border-t border-slate-200 flex items-center justify-center gap-2 text-[10px] text-slate-500 uppercase tracking-widest font-bold">
           <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M2.166 4.9L10 9.503l7.834-4.603A2 2 0 0016 4H4a2 2 0 00-1.834.9zM18 6.641l-7.51 4.417a1 1 0 01-1.01 0L2 6.641V14a2 2 0 002 2h12a2 2 0 002-2V6.641z" clipRule="evenodd"></path></svg>
           Secure AI Verification Active
        </div>
      </Card>
    </div>
  );
};

export default VerifyContact;
