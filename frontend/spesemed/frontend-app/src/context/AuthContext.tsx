import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { authStore, UserSession } from '../lib/auth';
import { api, onAuthFailure } from '../lib/api';
import { AuthRequest } from '../types/api';

interface AuthContextType {
  session: UserSession | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  userEmail: string;
  userId: string;
  login: (credentials: AuthRequest) => Promise<void>;
  signup: (credentials: AuthRequest) => Promise<void>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<UserSession | null>(() => authStore.getSession());
  const [isLoading, setIsLoading] = useState<boolean>(false);

  useEffect(() => {
    // Registra listener per logout automatico in caso di 401/403 irreversibile
    const unsubscribe = onAuthFailure(() => {
      setSession(null);
    });
    return unsubscribe;
  }, []);

  const login = useCallback(async (credentials: AuthRequest) => {
    setIsLoading(true);
    try {
      await api.login(credentials);
      setSession(authStore.getSession());
    } finally {
      setIsLoading(false);
    }
  }, []);

  const signup = useCallback(async (credentials: AuthRequest) => {
    setIsLoading(true);
    try {
      await api.signup(credentials);
      setSession(authStore.getSession());
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    setIsLoading(true);
    try {
      await api.logout();
    } finally {
      setSession(null);
      setIsLoading(false);
    }
  }, []);

  const refreshToken = useCallback(async () => {
    const currentRefresh = authStore.getRefreshToken();
    if (!currentRefresh) {
      throw new Error('Nessun refresh token disponibile.');
    }
    setIsLoading(true);
    try {
      await api.refresh(currentRefresh);
      setSession(authStore.getSession());
    } finally {
      setIsLoading(false);
    }
  }, []);

  const userEmail = session?.email || (session?.userId ? `utente-${session.userId.slice(0, 6)}@spesemed.local` : 'Ospite');
  const userId = session?.userId || '';

  return (
    <AuthContext.Provider
      value={{
        session,
        isAuthenticated: !!session?.accessToken,
        isLoading,
        userEmail,
        userId,
        login,
        signup,
        logout,
        refreshToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
