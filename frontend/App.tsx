
import React, { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { AppState, UserType, AccountStatus } from './types';
import { Card, Button, LoadingOverlay, ErrorModal } from './components/UI';
import { authApi, setToken, toUserSession, getContextMode, setContextMode, resolveBackendMediaUrl, type TokenResponse } from './services/api';
import Login from './pages/Auth/Login';
import RegisterOwner from './pages/Auth/RegisterOwner';
import RegisterManager from './pages/Auth/RegisterManager';
import RegisterManagerLanding from './pages/Auth/RegisterManagerLanding';
import { PropertyTransferLanding } from './pages/Auth/PropertyTransferLanding';
import VerifyContact from './pages/Auth/VerifyContact';
import ForgotPassword from './pages/Auth/ForgotPassword';
import ResetPassword from './pages/Auth/ResetPassword';
import OwnerDashboard from './pages/Owner/OwnerDashboard';
import AddProperty from './pages/Owner/AddProperty';
import RegisterFromInvite from './pages/Guest/RegisterFromInvite';
import { GuestDashboard } from './pages/Guest/GuestDashboard';
import { PropertyDetail } from './pages/Owner/PropertyDetail';
import SignAgreement from './pages/Guest/SignAgreement';
import Settings from './pages/Settings/Settings';
import HelpCenter from './pages/Support/HelpCenter';
import GuestSignup from './pages/Guest/GuestSignup';
import GuestLogin from './pages/Guest/GuestLogin';
import InviteLanding from './pages/Guest/InviteLanding';
import OnboardingIdentity from './pages/Onboarding/OnboardingIdentity';
import OnboardingIdentityComplete from './pages/Onboarding/OnboardingIdentityComplete';
import OnboardingPOA from './pages/Onboarding/OnboardingPOA';
import ProviderAuthorityLetter from './pages/Provider/ProviderAuthorityLetter';
import Landing from './pages/Landing';
import { DemoLogin } from './pages/Demo/DemoLogin';
import { DemoInviteGate } from './pages/Demo/DemoInviteGate';
import TermsOfService from './pages/Legal/TermsOfService';
import PrivacyPolicy from './pages/Legal/PrivacyPolicy';
import { LivePropertyPage, LivePropertyPageErrorBoundary } from './pages/LivePropertyPage';
import { PortfolioPage } from './pages/PortfolioPage';
import { VerifyPage } from './pages/Verify/VerifyPage';
import { AdminDashboard } from './pages/Admin/AdminDashboard';
import AdminLogin from './pages/Admin/AdminLogin';
import ManagerDashboard from './pages/Manager/ManagerDashboard';
import ManagerPropertyDetail from './pages/Manager/ManagerPropertyDetail';
import TenantDashboard from './pages/Tenant/TenantDashboard';

const PENDING_VERIFICATION_KEY = 'docustay_pending_verification';
/** Persist how we got to identity verification so identity-complete can send manager to manager-dashboard and owner to POA. */
const IDENTITY_FLOW_KEY = 'docustay_identity_flow';

const setPendingVerificationPersistent = (setState: React.Dispatch<React.SetStateAction<AppState>>) => (data: { userId: string; type: 'email' | 'phone'; expectedCode?: string; generatedAt: string }) => {
  if (typeof window !== 'undefined' && data) {
    try { sessionStorage.setItem(PENDING_VERIFICATION_KEY, JSON.stringify(data)); } catch { /* ignore */ }
  }
  setState(prev => ({ ...prev, pendingVerification: data }));
};

const clearPendingVerificationStorage = () => {
  if (typeof window !== 'undefined') {
    try { sessionStorage.removeItem(PENDING_VERIFICATION_KEY); } catch { /* ignore */ }
  }
};

/** Owner/manager dashboards should always open in business mode after login or session restore (not stale personal mode from localStorage). */
function ensureBusinessContextForManagementUser(userType: string | undefined) {
  if (userType === UserType.PROPERTY_OWNER || userType === UserType.PROPERTY_MANAGER) {
    setContextMode('business');
  }
}

/** Routes where guest invite acceptance runs; hide noisy global "invalid/expired invite" modal from stale checks. */
function isGuestInviteAcceptFlowView(v: string): boolean {
  if (!v) return false;
  return (
    v.startsWith('invite/')
    || v.startsWith('demo/invite/')
    || v.startsWith('demo/register/manager/')
    || v.startsWith('property-transfer/')
    || v.startsWith('demo/property-transfer/')
    || v.startsWith('register-from-invite/')
    || v === 'guest-login'
    || v.startsWith('guest-login/')
    || v === 'guest-signup'
    || v.startsWith('guest-signup/')
    || v === 'sign-agreement'
    || v === 'guest-dashboard'
  );
}

function isSpuriousInviteErrorMessage(message: string): boolean {
  const m = (message || '').toLowerCase();
  return m.includes('invalid or expired invitation') || m.includes('invalid or expired invite');
}

const App: React.FC = () => {
  const [state, setState] = useState<AppState>({
    user: null,
  });

  /** If someone opens a backend PDF path on the SPA host (e.g. /public/live/{slug}/poa), send them to the API URL so the PDF loads instead of React. */
  useLayoutEffect(() => {
    if (typeof window === 'undefined') return;
    const pathname = (window.location.pathname || '').replace(/\/$/, '') || '/';
    if (/^\/public\/live\/[^/]+\/poa$/i.test(pathname)) {
      window.location.replace(resolveBackendMediaUrl(pathname));
    }
  }, []);

  /** Normalize hash to view name (strip query/params: "onboarding/identity-complete&session_id=x" -> "onboarding/identity-complete"). */
  const hashToView = (raw: string) => {
    const h = (raw || '').replace(/^#/, '').trim();
    if (!h) return '';
    const base = h.split('?')[0].split('&')[0];
    return base || h;
  };
  const hasSessionIdInUrl = () => {
    if (typeof window === 'undefined') return false;
    const s = window.location.search || '';
    const h = window.location.hash || '';
    return /[?&]session_id=/.test(s) || /[?&]session_id=/.test(h) || /session_id=/.test(h);
  };
  const isManagerIdentityReturnPath = () =>
    typeof window !== 'undefined' && window.location.pathname.includes('/onboarding/identity-complete/manager');
  const [view, setView] = useState<string>(() => {
    if (typeof window === 'undefined') return '';
    if (hasSessionIdInUrl()) return isManagerIdentityReturnPath() ? 'onboarding/identity-complete/manager' : 'onboarding/identity-complete';
    const hash = window.location.hash;
    if (hash) return hashToView(hash);
    if (window.location.pathname === '/onboarding/identity-complete/manager') return 'onboarding/identity-complete/manager';
    if (window.location.pathname === '/onboarding/identity-complete' && !hash) {
      if (!authApi.getToken()) return 'onboarding/poa';
      return 'onboarding/identity-complete';
    }
    if (window.location.pathname === '/onboarding/identity-complete') return 'onboarding/identity-complete';
    return '';
  });
  const [loading, setLoading] = useState(false);
  const [sessionRestoring, setSessionRestoring] = useState(true); // Track if we're restoring session
  const [notification, setNotification] = useState<{ type: 'success'; message: string } | null>(null);
  const [errorModal, setErrorModal] = useState<{ open: boolean; message: string }>({ open: false, message: '' });
  /** Latest route for notification handlers (avoid stale closure). */
  const viewRef = useRef(view);
  /** Set when identity-complete calls onIdentityVerified; skip one redirect to onboarding/identity so manager-dashboard doesn't loop. */
  const identityJustVerifiedRef = useRef(false);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  // Restore session from localStorage token on page load
  useEffect(() => {
    const SESSION_RESTORE_TIMEOUT_MS = 15000;

    const restoreSession = async () => {
      // Skip session restore on onboarding pages (they use pending-owner tokens) and on manager invite signup (no token yet; avoid 401 → #login).
      const currentView = hashToView(window.location.hash || '');
      const isIdentityCompleteReturn =
        window.location.pathname === '/onboarding/identity-complete' ||
        window.location.pathname.includes('/onboarding/identity-complete/manager') ||
        hasSessionIdInUrl();
      const isOnboardingPage =
        currentView.startsWith('onboarding/') ||
        currentView === 'verify' ||
        currentView === 'check' ||
        isIdentityCompleteReturn;
      const isManagerInviteSignup = currentView === 'register/manager' || currentView.startsWith('register/manager/');
      const isOwnerTransferFlow =
        currentView.startsWith('register/owner-transfer/') ||
        currentView.startsWith('property-transfer/') ||
        currentView.startsWith('demo/property-transfer/') ||
        currentView.startsWith('login/owner-transfer/');
      if (isOnboardingPage || isManagerInviteSignup || isOwnerTransferFlow) {
        setSessionRestoring(false);
        return;
      }

      const token = authApi.getToken();
      if (!token) {
        setSessionRestoring(false);
        return;
      }

      const timeoutId = setTimeout(() => {
        setSessionRestoring(false);
      }, SESSION_RESTORE_TIMEOUT_MS);

      try {
        const user = await authApi.me();
        if (user) {
          ensureBusinessContextForManagementUser(user.user_type);
          setState(prev => ({ ...prev, user }));
          // If user is on login/register page but has valid session, redirect to dashboard
          if (!currentView || currentView === 'login' || currentView.startsWith('login/') || currentView === 'register' || currentView.startsWith('guest-login') || currentView.startsWith('guest-signup')) {
            const targetView = user.user_type === UserType.PROPERTY_OWNER
              ? (!user.identity_verified ? 'onboarding/identity' : !user.poa_linked ? 'onboarding/poa' : 'dashboard')
              : user.user_type === UserType.PROPERTY_MANAGER
                ? (user.identity_verified ? 'manager-dashboard' : 'onboarding/identity')
                : user.user_type === UserType.TENANT
                  ? 'tenant-dashboard'
                  : user.user_type === UserType.ADMIN
                    ? 'admin'
                    : 'guest-dashboard';
            window.location.hash = targetView;
            setView(targetView);
          }
        }
      } catch {
        // Token invalid/expired, clear it
        setToken(null);
      } finally {
        clearTimeout(timeoutId);
        setSessionRestoring(false);
      }
    };

    restoreSession();
  }, []);

  // Restore pending verification from sessionStorage when on verify page after refresh
  useEffect(() => {
    const v = hashToView(window.location.hash || '');
    if (v === 'verify' && !state.pendingVerification && typeof window !== 'undefined') {
      try {
        const stored = sessionStorage.getItem(PENDING_VERIFICATION_KEY);
        if (stored) {
          const data = JSON.parse(stored);
          if (data?.userId && data?.type) setState(prev => ({ ...prev, pendingVerification: data }));
        }
      } catch { /* ignore */ }
    }
  }, [view, state.pendingVerification]);

  // Persist identity flow when we show onboarding/identity so identity-complete knows manager vs owner (survives Stripe redirect).
  useEffect(() => {
    if (view !== 'onboarding/identity') return;
    try {
      if (state.user?.user_type === UserType.PROPERTY_MANAGER) {
        sessionStorage.setItem(IDENTITY_FLOW_KEY, 'manager');
      } else {
        sessionStorage.setItem(IDENTITY_FLOW_KEY, 'owner');
      }
    } catch { /* ignore */ }
  }, [view, state.user?.user_type]);

  // Clear global loading when view changes so a previous page's setLoading(true) doesn't leave overlay stuck
  const prevViewRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevViewRef.current !== null && prevViewRef.current !== view) {
      setLoading(false);
    }
    prevViewRef.current = view;
  }, [view]);

  const navigate = (newView: string) => {
    window.location.hash = newView;
    setView(newView);
  };

  useEffect(() => {
    const syncViewFromUrl = () => {
      if (hasSessionIdInUrl()) {
        setView(isManagerIdentityReturnPath() ? 'onboarding/identity-complete/manager' : 'onboarding/identity-complete');
        return;
      }
      const hash = window.location.hash;
      if (hash) {
        const viewName = hashToView(hash);
        if (viewName === 'guest-identity') {
          window.history.replaceState(null, '', window.location.pathname + window.location.search + '#guest-dashboard');
          setView('guest-dashboard');
          return;
        }
        if (viewName === 'admin-login') {
          window.history.replaceState(null, '', window.location.pathname + window.location.search + '#admin');
          setView('admin');
          return;
        }
        setView(viewName);
        return;
      }
      if (window.location.pathname === '/onboarding/identity-complete/manager') {
        setView('onboarding/identity-complete/manager');
        if (!window.location.hash) {
          const q = window.location.search ? window.location.search : '';
          window.history.replaceState(null, '', window.location.pathname + q + '#onboarding/identity-complete/manager');
        }
        return;
      }
      if (window.location.pathname === '/onboarding/identity-complete') {
        if (!window.location.hash && !hasSessionIdInUrl() && !authApi.getToken()) {
          const q = window.location.search ? window.location.search : '';
          window.history.replaceState(null, '', window.location.pathname + q + '#onboarding/poa');
          setView('onboarding/poa');
          return;
        }
        setView('onboarding/identity-complete');
        if (!window.location.hash) {
          const q = window.location.search ? window.location.search : '';
          window.history.replaceState(null, '', window.location.pathname + q + '#onboarding/identity-complete');
        }
        return;
      }
      setView('');
    };
    syncViewFromUrl();
    window.addEventListener('hashchange', syncViewFromUrl);
    window.addEventListener('popstate', syncViewFromUrl);
    return () => {
      window.removeEventListener('hashchange', syncViewFromUrl);
      window.removeEventListener('popstate', syncViewFromUrl);
    };
  }, []);

  // Do NOT call authApi.me() when on onboarding/identity-complete (or identity/poa). We have a pending-owner token there; /auth/me requires a full user and would 401, then the API client would redirect to #login and break the signup flow. Let OnboardingIdentityComplete confirm with the backend and then navigate to POA.

  // Redirect owner to onboarding step if they try to open dashboard/property before completing onboarding
  useEffect(() => {
    if (state.user?.user_type === UserType.PROPERTY_OWNER && (view.startsWith('dashboard') || view.startsWith('add-property') || view.startsWith('property/'))) {
      if (view === 'add-property' && getContextMode() === 'personal') {
        navigate('dashboard');
        return;
      }
      if (!state.user.identity_verified) navigate('onboarding/identity');
      else if (!state.user.poa_linked) navigate('onboarding/poa');
    }
    if (state.user?.user_type === UserType.PROPERTY_MANAGER) {
      if ((view === 'dashboard' || view.startsWith('dashboard/'))) {
        navigate('manager-dashboard');
      } else if ((view === 'manager-dashboard' || view.startsWith('manager-dashboard/')) && !state.user.identity_verified) {
        if (identityJustVerifiedRef.current) {
          identityJustVerifiedRef.current = false;
        } else if (typeof window !== 'undefined' && sessionStorage.getItem(IDENTITY_FLOW_KEY) === 'manager') {
          // Came from manager identity flow; don't redirect back to identity. Key cleared in OnboardingIdentityComplete on success.
        } else {
          navigate('onboarding/identity');
        }
      }
    }
    if (state.user?.user_type === UserType.TENANT && (view === 'dashboard' || view.startsWith('dashboard/'))) {
      navigate('tenant-dashboard');
    }
  }, [state.user, view]);

  const handleLogin = (userData: any) => {
    ensureBusinessContextForManagementUser(userData.user_type);
    setState(prev => ({ ...prev, user: userData }));
    if (userData.user_type === UserType.PROPERTY_OWNER) {
      if (!userData.identity_verified) {
        try { sessionStorage.setItem(IDENTITY_FLOW_KEY, 'owner'); } catch { /* ignore */ }
        navigate('onboarding/identity');
      } else if (!userData.poa_linked) navigate('onboarding/poa');
      else navigate('dashboard');
    } else if (userData.user_type === UserType.PROPERTY_MANAGER) {
      if (!userData.identity_verified) {
        try { sessionStorage.setItem(IDENTITY_FLOW_KEY, 'manager'); } catch { /* ignore */ }
        navigate('onboarding/identity');
      } else navigate('manager-dashboard');
    } else if (userData.user_type === UserType.TENANT) {
      navigate('tenant-dashboard');
    } else if (userData.user_type === UserType.ADMIN) {
      navigate('admin');
    } else {
      navigate('guest-dashboard');
    }
  };

  const handleLogout = () => {
    authApi.logout();
    setState({ user: null });
    navigate('');
  };

  const showNotification = useCallback((type: 'success' | 'error', message: string) => {
    if (type === 'error') {
      if (isGuestInviteAcceptFlowView(viewRef.current) && isSpuriousInviteErrorMessage(message)) {
        return;
      }
      setErrorModal({ open: true, message });
      return;
    }
    setNotification({ type: 'success', message });
    setTimeout(() => setNotification(null), 5000);
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-b from-blue-100/60 via-blue-50/30 to-sky-50/50 text-gray-800 overflow-x-hidden relative">
      {(loading || sessionRestoring) && <LoadingOverlay />}

      {/* Navigation */}
      <nav className="bg-white border-b border-gray-200 sticky top-0 z-40">
        <div className="w-full px-4 sm:px-5">
          <div className="flex justify-between h-16 items-center">
            <div className="flex items-center gap-3 cursor-pointer" onClick={() => navigate('')}>
              <div className="w-9 h-9 bg-blue-700 rounded-lg flex items-center justify-center">
                <span className="text-white font-semibold text-lg">D</span>
              </div>
              <span className="text-xl font-semibold text-gray-900">DocuStay <span className="text-blue-700 font-normal">AI</span></span>
            </div>
            
            <div className="flex items-center gap-6">
              <button onClick={() => navigate('check')} className="text-gray-600 hover:text-gray-900 font-medium text-sm transition-colors">Verify</button>
              {state.user ? (
                <>
                  <div className="hidden md:block text-right">
                    <p className="text-sm font-semibold text-gray-900">
                      {(() => {
                        const name = state.user.user_name?.trim() || '';
                        const isGeneric = !name || name.toLowerCase() === 'user';
                        return isGeneric ? (state.user.email || 'Account') : name;
                      })()}
                    </p>
                    <p className="text-xs text-gray-500 uppercase tracking-wide">
                      {(state.user.user_type || '').replace('_', ' ')}
                    </p>
                    {state.user.is_demo && (
                      <p className="text-xs text-gray-400 uppercase tracking-wide">demo</p>
                    )}
                  </div>
                  <Button variant="outline" onClick={handleLogout} className="px-5 py-2">Logout</Button>
                </>
              ) : (
                <Button variant="primary" onClick={() => navigate('')} className="px-6 py-2.5 bg-blue-700 hover:bg-blue-800 focus:ring-blue-600">Get Started</Button>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* Success toast – horizontally centered, lower third of screen; auto-dismisses after 5s (errors use ErrorModal below) */}
      {notification && (
        <div className="fixed inset-0 z-50 flex items-end justify-center pb-24 pointer-events-none">
          <div className="pointer-events-auto p-4 rounded-xl shadow-lg border-2 bg-white border-green-200 text-green-800">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-green-500 shrink-0"></div>
              <span className="font-medium text-base">{notification.message}</span>
            </div>
          </div>
        </div>
      )}

      {/* Global error modal – all errors displayed here */}
      <ErrorModal
        open={errorModal.open}
        message={errorModal.message}
        onClose={() => setErrorModal({ open: false, message: '' })}
      />

      {/* Main Content */}
      <main className="flex-grow flex flex-col">
        {(view === 'login' || view.startsWith('login/')) && (
          <Login
            onLogin={handleLogin}
            setLoading={setLoading}
            notify={showNotification}
            navigate={navigate}
            initialRole={view.startsWith('login/property_manager') ? 'property_manager' : view.startsWith('login/tenant') ? 'tenant' : 'owner'}
            managerInviteToken={view.startsWith('login/property_manager/') ? view.split('/')[2] || '' : undefined}
            propertyTransferToken={view.startsWith('login/owner-transfer/') ? view.slice('login/owner-transfer/'.length) || undefined : undefined}
          />
        )}
        {(view === 'forgot-password/owner' || view === 'forgot-password/guest') && (
          <ForgotPassword
            role={view === 'forgot-password/owner' ? 'owner' : 'guest'}
            setLoading={setLoading}
            notify={showNotification}
            navigate={navigate}
          />
        )}
        {view === 'reset-password' && (
          <ResetPassword setLoading={setLoading} notify={showNotification} navigate={navigate} />
        )}
        {view === 'demo' && (
          <DemoLogin
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            onLogin={handleLogin}
          />
        )}
        {view.startsWith('demo/invite/') && (
          <DemoInviteGate
            mode="invite"
            payload={view.slice('demo/invite/'.length)}
            sessionUser={state.user}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            onLogin={handleLogin}
          />
        )}
        {view.startsWith('demo/register/manager/') && (
          <DemoInviteGate
            mode="manager_register"
            payload={view.slice('demo/register/manager/'.length)}
            sessionUser={state.user}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            onLogin={handleLogin}
          />
        )}
        {view.startsWith('invite/') && (
          <InviteLanding
            invitationCode={view.split('/')[1] || ''}
            sessionIsDemo={Boolean(state.user?.is_demo)}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            setPendingVerification={setPendingVerificationPersistent(setState)}
            onLogin={handleLogin}
            onGuestLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('guest-dashboard'); }}
            onTenantLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('tenant-dashboard'); }}
          />
        )}
        {(view === 'guest-login' || view.startsWith('guest-login/')) && (
          <GuestLogin
            inviteCode={view.startsWith('guest-login/') ? view.split('/')[1] : undefined}
            onLogin={handleLogin}
            setLoading={setLoading}
            notify={showNotification}
            navigate={navigate}
            setPendingVerification={setPendingVerificationPersistent(setState)}
            onGuestLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('guest-dashboard'); }}
            onTenantLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('tenant-dashboard'); }}
          />
        )}
        {view.startsWith('register-from-invite/') && (
          <RegisterFromInvite
            invitationId={view.split('/')[1] || ''}
            sessionIsDemo={Boolean(state.user?.is_demo)}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            setPendingVerification={setPendingVerificationPersistent(setState)}
            onGuestLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('guest-dashboard'); }}
            onTenantLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('tenant-dashboard'); }}
          />
        )}
        {view === 'register' && <RegisterOwner setPendingVerification={setPendingVerificationPersistent(setState)} onLogin={handleLogin} navigate={navigate} setLoading={setLoading} notify={showNotification} />}
        {view.startsWith('property-transfer/') && (
          <PropertyTransferLanding
            token={view.slice('property-transfer/'.length)}
            navigate={navigate}
            setLoading={setLoading}
          />
        )}
        {view.startsWith('demo/property-transfer/') && (
          <DemoInviteGate
            mode="property_transfer"
            payload={view.slice('demo/property-transfer/'.length)}
            sessionUser={state.user}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            onLogin={handleLogin}
          />
        )}
        {view.startsWith('register/owner-transfer/') && (
          <RegisterOwner
            setPendingVerification={setPendingVerificationPersistent(setState)}
            onLogin={handleLogin}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            propertyTransferToken={view.slice('register/owner-transfer/'.length)}
          />
        )}
        {view === 'register/manager' && <RegisterManagerLanding navigate={navigate} />}
        {view.startsWith('register/manager/') && (
          <RegisterManager
            inviteToken={view.split('/')[2] || ''}
            onLogin={handleLogin}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
          />
        )}
        {(view === 'guest-signup' || view.startsWith('guest-signup/')) && (
          <GuestSignup
            initialRole={view === 'guest-signup/tenant' ? 'tenant' : undefined}
            initialInviteCode={view.startsWith('guest-signup/') && view !== 'guest-signup/tenant' ? view.split('/')[1] : undefined}
            setPendingVerification={setPendingVerificationPersistent(setState)}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            onGuestLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('guest-dashboard'); }}
            onTenantLogin={(user) => { setState(prev => ({ ...prev, user })); navigate('tenant-dashboard'); }}
          />
        )}
        {view === 'verify' && state.pendingVerification && (
          <VerifyContact
            verification={state.pendingVerification}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            onVerified={(user) => {
              clearPendingVerificationStorage();
              ensureBusinessContextForManagementUser(user.user_type);
              setState(prev => ({ ...prev, user }));
              const next = user.user_type === UserType.PROPERTY_OWNER
                ? (!user.identity_verified ? 'onboarding/identity' : !user.poa_linked ? 'onboarding/poa' : 'dashboard')
                : user.user_type === UserType.TENANT ? 'tenant-dashboard' : 'guest-dashboard';
              if (next === 'onboarding/identity') {
                try { sessionStorage.setItem(IDENTITY_FLOW_KEY, 'owner'); } catch { /* ignore */ }
              }
              setTimeout(() => navigate(next), 0);
            }}
          />
        )}

        {/* Owner onboarding: verify email first (register → verify), then Stripe identity, then POA. Show identity only with token or owner user so we don't call authApi.me() here. */}
        {view === 'onboarding/identity' && (state.user?.user_type === UserType.PROPERTY_OWNER || state.user?.user_type === UserType.PROPERTY_MANAGER || state.user?.user_id === '0' || authApi.getToken()) && (
          <OnboardingIdentity
            isPendingOwner={!state.user || state.user?.user_id === '0'}
            identityReturnPath={state.user?.user_type === UserType.PROPERTY_MANAGER ? 'onboarding/identity-complete/manager' : 'onboarding/identity-complete'}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
          />
        )}
        {(view === 'onboarding/identity-complete' || view === 'onboarding/identity-complete/manager') && (
          <OnboardingIdentityComplete
            isManagerReturn={view === 'onboarding/identity-complete/manager'}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            onIdentityVerified={(user) => {
              identityJustVerifiedRef.current = true;
              ensureBusinessContextForManagementUser(user.user_type);
              setState((prev) => ({ ...prev, user }));
            }}
          />
        )}
        {view === 'onboarding/poa' && (
          <OnboardingPOA
            user={state.user}
            onCompleteSignup={(data: TokenResponse) => {
              setToken(data.access_token);
              const sessionUser = toUserSession(data);
              ensureBusinessContextForManagementUser(sessionUser.user_type);
              setState(prev => ({ ...prev, user: sessionUser }));
              navigate('dashboard');
            }}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
          />
        )}

        {/* Owner Dashboard Views */}
        {(view === 'dashboard' || view.startsWith('dashboard/') || view === 'settings' || view === 'help') && state.user?.user_type === UserType.PROPERTY_OWNER && (
          <OwnerDashboard
            user={state.user}
            navigate={navigate}
            setLoading={setLoading}
            notify={showNotification}
            initialTab={
              view === 'dashboard/properties' ? 'properties'
              : view === 'dashboard/billing' ? 'billing'
              : view === 'dashboard/guests' ? 'guests'
              : view === 'dashboard/invitations' ? 'invitations'
              : view === 'dashboard/logs' ? 'logs'
              : view === 'dashboard/pending-tenants' ? 'pending-tenants'
              : view === 'settings' ? 'settings'
              : view === 'help' ? 'help'
              : undefined
            }
          />
        )}
        {view === 'add-property' && <AddProperty user={state.user} navigate={navigate} setLoading={setLoading} notify={showNotification} />}
        {view === 'settings' && state.user?.user_type !== UserType.PROPERTY_OWNER && <Settings user={state.user} navigate={navigate} />}
        {view === 'help' && state.user?.user_type !== UserType.PROPERTY_OWNER && <HelpCenter navigate={navigate} />}
        {view.startsWith('property/') && state.user?.user_type === UserType.PROPERTY_OWNER && <PropertyDetail propertyId={view.split('/')[1]} user={state.user} navigate={navigate} setLoading={setLoading} notify={showNotification} />}

        {/* Property Manager Dashboard */}
        {view.startsWith('manager-dashboard/property/') && state.user?.user_type === UserType.PROPERTY_MANAGER && (
          <ManagerPropertyDetail propertyId={view.split('/')[2] || ''} user={state.user} navigate={navigate} setLoading={setLoading} notify={showNotification} />
        )}
        {(view === 'manager-dashboard' || (view.startsWith('manager-dashboard/') && !view.startsWith('manager-dashboard/property/'))) && state.user?.user_type === UserType.PROPERTY_MANAGER && (
          <ManagerDashboard user={state.user} navigate={navigate} setLoading={setLoading} notify={showNotification} />
        )}

        {/* Tenant Dashboard */}
        {(view === 'tenant-dashboard' || view.startsWith('tenant-dashboard/')) && state.user?.user_type === UserType.TENANT && (
          <TenantDashboard user={state.user} navigate={navigate} setLoading={setLoading} notify={showNotification} />
        )}

        {/* Public live property page (no auth; URL uses slug, not property id) */}
        {view.startsWith('live/') && (
          <LivePropertyPageErrorBoundary>
            <LivePropertyPage slug={view.replace(/^live\/?/, '').split('/')[0] || ''} />
          </LivePropertyPageErrorBoundary>
        )}

        {/* Public portfolio page (no auth; owner's properties + basic info) */}
        {view.startsWith('portfolio/') && (
          <PortfolioPage slug={view.replace(/^portfolio\/?/, '').split('/')[0] || ''} />
        )}

        {/* Public check portal (no auth; token + address verification, all attempts logged). Uses #check to avoid overlapping with #verify email verification. */}
        {view === 'check' && <VerifyPage />}

        {/* Provider authority letter (public link from email) */}
        {view.startsWith('provider/authority/') && (
          <ProviderAuthorityLetter
            token={view.replace(/^provider\/authority\//, '')}
            notify={showNotification}
          />
        )}

        {/* Guest Flow Views */}
        {view === 'guest-dashboard' && state.user?.user_type === UserType.GUEST && <GuestDashboard user={state.user} navigate={navigate} notify={showNotification} />}
        {view === 'sign-agreement' && state.user?.user_type === UserType.GUEST && <SignAgreement user={state.user} navigate={navigate} notify={showNotification} />}

        {/* Admin: access only via #admin. Shows login when not signed in; dashboard when role=admin. #admin-login redirects to #admin. */}
        {(view === 'admin' || view === 'admin-login' || view.startsWith('admin/')) && (() => {
          if (!state.user) {
            return (
              <AdminLogin
                onLogin={handleLogin}
                setLoading={setLoading}
                notify={showNotification}
                navigate={navigate}
              />
            );
          }
          if (state.user.user_type !== 'ADMIN') {
            const targetView = state.user?.user_type === 'PROPERTY_OWNER' ? 'dashboard'
              : state.user?.user_type === 'PROPERTY_MANAGER' ? 'manager-dashboard'
              : state.user?.user_type === 'TENANT' ? 'tenant-dashboard'
              : 'guest-dashboard';
            return (
              <div className="flex-grow flex items-center justify-center p-8">
                <div className="text-center max-w-md">
                  <h2 className="text-xl font-semibold text-slate-900 mb-2">Access denied</h2>
                  <p className="text-slate-600 mb-4">This area is for administrators only.</p>
                  <Button
                    variant="primary"
                    onClick={() => navigate(targetView)}
                  >
                    Go to my dashboard
                  </Button>
                </div>
              </div>
            );
          }
          return <AdminDashboard user={state.user} navigate={navigate} notify={showNotification} />;
        })()}

        {/* Legal pages – public, no login required */}
        {view === 'terms' && <TermsOfService navigate={navigate} />}
        {view === 'privacy' && <PrivacyPolicy navigate={navigate} />}

        {/* Home / Landing – also fallback when hash is a protected route but user not loaded (avoids blank page) */}
        {(view === '' || (view && !state.user && ['dashboard', 'add-property', 'settings', 'guest-dashboard', 'onboarding/identity'].some((v) => view === v || view.startsWith(v + '/')))) && (
          <Landing navigate={navigate} />
        )}
      </main>

    </div>
  );
};

export default App;
