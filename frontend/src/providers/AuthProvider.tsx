'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { User, onIdTokenChanged, signInWithPopup, signOut as firebaseSignOut } from 'firebase/auth';
import { auth, googleProvider } from '@/lib/firebaseClient';

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  token: string | null;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const unsubscribe = onIdTokenChanged(auth, async (firebaseUser) => {
      setUser(firebaseUser);
      if (firebaseUser) {
        const idToken = await firebaseUser.getIdToken();
        setToken(idToken);
      } else {
        setToken(null);
      }
      setLoading(false);
    });

    return () => unsubscribe();
  }, []);

  // ID tokens last an hour. Firebase renews them on its own timer, but that
  // timer stalls while the tab is in the background or the machine sleeps, so
  // the token held above can come back stale. getIdToken() renews it when it's
  // close to expiring, and onIdTokenChanged then stores the new one.
  useEffect(() => {
    if (!user) return;

    const refresh = () => {
      user.getIdToken().catch((err) => console.error('[Auth] Token refresh failed:', err));
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') refresh();
    };

    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', refresh);
    const interval = window.setInterval(refresh, 10 * 60 * 1000);

    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', refresh);
      window.clearInterval(interval);
    };
  }, [user]);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    token,
    signInWithGoogle: async () => {
      await signInWithPopup(auth, googleProvider);
    },
    signOut: async () => {
      await firebaseSignOut(auth);
    },
  }), [user, loading, token]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
