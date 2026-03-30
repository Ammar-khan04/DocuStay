import React, { useCallback, useEffect, useRef, useState } from "react";
import { Card, Button } from "../../components/UI";
import { authApi, identityApi, pendingOwnerApi, type UserSession } from "../../services/api";
import { UserType } from "../../types";
import { getOwnerSignupErrorFriendly, getStripeIdentityErrorCodeMessage } from "../../utils/ownerSignupErrors";

interface Props {
  /** When true, we landed on the manager-only return URL; only use identityApi (never pendingOwnerApi). */
  isManagerReturn?: boolean;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: "success" | "error", m: string) => void;
  /** Called when a full user (owner/manager) completes identity verification. Passes fresh user from me() so parent can update state before navigate. Prevents manager redirect loop. */
  onIdentityVerified?: (user: UserSession) => void;
}

type ErrorState = { message: string; sessionId: string | null };

/** SessionStorage key set by App when we land on onboarding/identity so we know manager vs owner after Stripe redirect. */
const IDENTITY_FLOW_KEY = "docustay_identity_flow";

/** Landing page after Stripe Identity redirect. Manager return URL: only identityApi. Owner return URL: identityApi then pendingOwnerApi on 401. */
export default function OnboardingIdentityComplete({ isManagerReturn, navigate, setLoading, notify, onIdentityVerified }: Props) {
  const [status, setStatus] = useState<"confirming" | "success" | "error">("confirming");
  const [errorState, setErrorState] = useState<ErrorState>({ message: "", sessionId: null });
  const hasRunRef = useRef(false);

  const onSuccessOwner = useCallback(() => {
    try {
      if (typeof window !== "undefined") sessionStorage.removeItem(IDENTITY_FLOW_KEY);
    } catch { /* ignore */ }
    setStatus("success");
    notify("success", "Identity verified. Completing signup…");
    setLoading(false);
    setTimeout(() => navigate("onboarding/poa"), 1500);
  }, [navigate, notify, setLoading]);

  const onSuccessManager = useCallback(() => {
    try {
      if (typeof window !== "undefined") sessionStorage.removeItem(IDENTITY_FLOW_KEY);
    } catch { /* ignore */ }
    setStatus("success");
    notify("success", "Identity verified.");
    setLoading(false);
    setTimeout(() => navigate("manager-dashboard"), 1500);
  }, [navigate, notify, setLoading]);

  const onSuccess = onSuccessOwner;

  const onFailure = useCallback(
    (errMessage: string, sessionId: string | null, errorCode?: string) => {
      setStatus("error");
      const codeMessage = getStripeIdentityErrorCodeMessage(errorCode);
      const friendly = getOwnerSignupErrorFriendly(codeMessage ?? errMessage);
      setErrorState({ message: codeMessage ?? friendly.message, sessionId });
      notify("error", codeMessage ?? friendly.message);
      setLoading(false);
    },
    [notify, setLoading]
  );

  const handleTryAgain = useCallback(() => {
    const sid = errorState.sessionId;
    const hasToken = authApi.getToken();
    if (!sid) {
      notify("error", "No verification session. Please start verification again.");
      navigate("onboarding/identity?new=1");
      return;
    }
    if (hasToken) {
      navigate("onboarding/identity?new=1");
      return;
    }
    setLoading(true);
    pendingOwnerApi
      .getIdentityRetryUrl(sid)
      .then((r) => {
        if (r.already_verified) {
          onSuccess();
          return;
        }
        if (r.url) {
          window.location.href = r.url;
          return;
        }
        notify("error", r.message ?? "Could not get retry link. Please start verification again.");
        navigate("onboarding/identity?new=1");
      })
      .catch((e) => {
        const msg = (e as Error)?.message ?? "";
        const needsNewSession =
          msg.toLowerCase().includes("no longer valid") ||
          msg.toLowerCase().includes("start verification again") ||
          msg.toLowerCase().includes("expired") ||
          msg.toLowerCase().includes("invalid or expired");
        if (needsNewSession) {
          notify("error", msg);
          navigate("onboarding/identity?new=1");
        } else {
          setErrorState((prev) => ({ ...prev, message: msg }));
          notify("error", msg);
        }
        setLoading(false);
      });
  }, [errorState.sessionId, navigate, notify, onSuccess, setLoading]);

  const doConfirm = useCallback(
    (sessionId: string) => {
      setLoading(true);
      const onConfirmSuccess = () =>
        authApi.me().then((user) => {
          if (user) onIdentityVerified?.(user);
          const flow =
            typeof window !== "undefined" ? sessionStorage.getItem(IDENTITY_FLOW_KEY) : null;
          if (user?.user_type === UserType.PROPERTY_MANAGER) {
            onSuccessManager();
          } else if (flow === "manager") {
            onSuccessManager();
          } else {
            onSuccessOwner();
          }
        });
      // Manager return URL: only identityApi (no pending-owner fallback)
      if (isManagerReturn) {
        identityApi
          .confirmIdentity(sessionId)
          .then(onConfirmSuccess)
          .catch((e) => {
            const err = e as Error & { errorCode?: string; sessionId?: string };
            onFailure(err?.message ?? "Could not confirm identity.", err.sessionId ?? sessionId, err.errorCode);
          });
        return;
      }
      // Owner return URL: try identityApi first, then pendingOwnerApi on 401
      identityApi
        .confirmIdentity(sessionId)
        .then(onConfirmSuccess)
        .catch((e) => {
          const msg = (e as Error)?.message ?? "";
          const isPendingOwnerFlow =
            msg.toLowerCase().includes("pending-owner") ||
            msg.toLowerCase().includes("pending owner") ||
            msg.toLowerCase().includes("use the pending") ||
            msg.includes("Not authenticated");
          if (isPendingOwnerFlow) {
            return pendingOwnerApi
              .confirmIdentity(sessionId)
              .then(onSuccessOwner)
              .catch((err) => {
                const err2 = err as Error & { errorCode?: string; sessionId?: string };
                onFailure(err2?.message ?? "Could not confirm identity.", err2.sessionId ?? sessionId, err2.errorCode);
              });
          }
          const err = e as Error & { errorCode?: string; sessionId?: string };
          onFailure(err?.message ?? "Could not confirm identity.", err.sessionId ?? sessionId, err.errorCode);
        });
    },
    [isManagerReturn, onSuccessOwner, onSuccessManager, onFailure, setLoading, onIdentityVerified]
  );

  useEffect(() => {
    if (hasRunRef.current) return;
    hasRunRef.current = true;

    const search = window.location.search || "";
    const hash = (window.location.hash || "").replace(/^#/, "");
    const params = new URLSearchParams(search);
    const hashQuery = hash.includes("?") ? hash.split("?")[1] : hash.includes("&") ? hash.slice(hash.indexOf("&") + 1) : "";
    const hashParams = hashQuery ? new URLSearchParams(hashQuery) : null;
    const fullUrl = window.location.href;
    const fromHref = (fullUrl.match(/[?&]session_id=([^&?#]+)/) || [])[1];
    const decode = (s: string) => {
      try {
        return decodeURIComponent(s.replace(/%2F/g, "/").trim());
      } catch {
        return s.trim();
      }
    };
    let sid: string | null =
      (params.get("session_id") && decode(params.get("session_id")!)) ||
      (hashParams?.get("session_id") && decode(hashParams.get("session_id")!)) ||
      (fromHref ? decode(fromHref) : null) ||
      null;
    if (sid) sid = sid.trim() || null;

    if (sid) {
      doConfirm(sid);
      return;
    }

    // Full user (owner/manager with Bearer token): Stripe may redirect without session_id in URL. Try backend-stored session first.
    // NOTE: A pending owner also has a token (pending-owner JWT), so we must handle the case where
    // identityApi rejects it with "use the pending-owner flow" and fall back to pendingOwnerApi.
    if (authApi.getToken()) {
      setLoading(true);
      identityApi
        .getLatestIdentitySession()
        .then((r) => {
          const stored = (r?.verification_session_id || "").trim();
          if (stored) doConfirm(stored);
          else {
            setLoading(false);
            onFailure(
              "We couldn't find your verification session. Please go back and start identity verification again.",
              null
            );
          }
        })
        .catch((e) => {
          const msg = (e as Error)?.message ?? "";
          // Pending-owner JWT: the identity API (which requires a full user token) rejects it.
          // Fall back to the pending-owner API so the owner flow can still complete.
          const isPendingFlow =
            msg.toLowerCase().includes("pending-owner") ||
            msg.toLowerCase().includes("pending owner") ||
            msg.toLowerCase().includes("use the pending") ||
            msg.includes("Not authenticated");
          if (!isManagerReturn && isPendingFlow) {
            pendingOwnerApi
              .getLatestIdentitySession()
              .then((r2) => {
                const stored2 = (r2?.verification_session_id || "").trim();
                if (stored2) doConfirm(stored2);
                else {
                  setLoading(false);
                  onFailure(
                    "We couldn't find your verification session. Please go back and start identity verification again.",
                    null
                  );
                }
              })
              .catch((err2) => {
                setLoading(false);
                const msg2 = (err2 as Error)?.message ?? "";
                const notFound2 = /no identity session|no verification|404|not found/i.test(msg2);
                onFailure(
                  notFound2
                    ? "We couldn't find your verification session. Please go back and start identity verification again."
                    : msg2 || "We couldn't load your verification session. Please start verification again.",
                  null
                );
              });
            return;
          }
          setLoading(false);
          const notFound = /no verification session|no identity session|404|not found/i.test(msg);
          onFailure(
            notFound
              ? "We couldn't find your verification session. Please go back and start identity verification again."
              : msg || "We couldn't load your verification session. Please start verification again.",
            null
          );
        });
      return;
    }

    if (isManagerReturn) {
      setLoading(false);
      onFailure(
        "We couldn't find your verification session. Please sign in and start identity verification again.",
        null
      );
      return;
    }

    setLoading(true);
    pendingOwnerApi
      .getLatestIdentitySession()
      .then((r) => {
        const stored = (r?.verification_session_id || "").trim();
        if (stored) doConfirm(stored);
        else {
          setLoading(false);
          onFailure(
            "We couldn't find your verification session. Please go back and start identity verification again.",
            null
          );
        }
      })
      .catch((e) => {
        setLoading(false);
        const msg = (e as Error)?.message ?? "";
        const notFound = /no identity session|no verification|404|not found/i.test(msg);
        onFailure(
          notFound
            ? "We couldn't find your verification session. Please go back and start identity verification again."
            : msg || "We couldn't load your verification session. Please start verification again.",
          null
        );
      });
  }, [doConfirm, isManagerReturn, onFailure, setLoading]);

  return (
    <div className="flex-grow flex flex-col items-center justify-center p-6">
      <Card className="max-w-lg w-full p-8 text-center">
        <h1 className="text-xl font-semibold text-gray-900 mb-2">Verify your identity</h1>
        {status === "confirming" && (
          <p className="text-gray-600">Confirming your identity…</p>
        )}
        {status === "success" && (
          <p className="text-green-700">Identity verified. Redirecting…</p>
        )}
        {status === "error" && (
          <>
            <p className="text-red-600 text-sm mb-4">{errorState.message}</p>
            <p className="text-slate-600 text-sm mb-6">You can try again or start over from signup.</p>
            <div className="flex flex-col gap-3">
              <Button onClick={handleTryAgain} className="w-full">
                Try again
              </Button>
              <button
                type="button"
                onClick={() => navigate("onboarding/identity?new=1")}
                className="text-sm text-slate-600 underline hover:text-slate-800"
              >
                Start verification again
              </button>
              <button
                type="button"
                onClick={() => navigate("register")}
                className="text-sm text-slate-500 underline hover:text-slate-700"
              >
                Back to owner signup
              </button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
