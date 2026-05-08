import { useState, useEffect, useCallback } from "react";
import {
  getAuthEmail,
  getAuthToken,
  setAuthSession,
  clearAuthSession,
  exchangeGmailCode,
  getGmailAuthUrl,
  getApiUrl,
  fetchCurrentSession,
  loginWithPassword,
  logoutSession,
  signupWithPassword,
} from "@/lib/api-client";

export interface AuthState {
  authenticated: boolean;
  email: string | null;
  loading: boolean;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    authenticated: false,
    email: null,
    loading: true,
  });

  useEffect(() => {
    let active = true;

    async function hydrateAuth() {
      const token = getAuthToken();
      const apiUrl = getApiUrl();
      const cachedEmail = getAuthEmail();

      if (!token) {
        if (active) {
          setState({ authenticated: false, email: null, loading: false });
        }
        return;
      }

      if (!apiUrl) {
        if (active) {
          setState({
            authenticated: true,
            email: cachedEmail,
            loading: false,
          });
        }
        return;
      }

      try {
        const session = await fetchCurrentSession();
        if (!active) return;
        if (session.authenticated && session.user?.email) {
          setAuthSession(token, session.user.email);
          setState({
            authenticated: true,
            email: session.user.email,
            loading: false,
          });
          return;
        }
      } catch {
        // fall through and clear the stale session below
      }

      clearAuthSession();
      if (active) {
        setState({ authenticated: false, email: null, loading: false });
      }
    }

    void hydrateAuth();

    return () => {
      active = false;
    };
  }, []);

  const loginWithGoogleCode = useCallback(async (code: string) => {
    const res = await exchangeGmailCode(code);
    setAuthSession(res.access_token, res.email);
    setState({ authenticated: true, email: res.email, loading: false });
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await loginWithPassword(email, password);
    setAuthSession(res.token, res.user.email);
    setState({ authenticated: true, email: res.user.email, loading: false });
  }, []);

  const signUp = useCallback(async (fullName: string, email: string, password: string) => {
    const res = await signupWithPassword(fullName, email, password);
    setAuthSession(res.token, res.user.email);
    setState({ authenticated: true, email: res.user.email, loading: false });
  }, []);

  const loginRedirect = useCallback(async () => {
    const url = await getGmailAuthUrl();
    window.location.href = url;
  }, []);

  const logout = useCallback(async () => {
    try {
      if (getApiUrl() && getAuthToken()) {
        await logoutSession();
      }
    } catch {
      // Always clear local auth state, even if the backend is unavailable.
    }
    clearAuthSession();
    setState({ authenticated: false, email: null, loading: false });
  }, []);

  return {
    ...state,
    login: loginWithGoogleCode,
    signIn,
    signUp,
    loginRedirect,
    logout,
    apiConfigured: !!getApiUrl(),
  };
}
