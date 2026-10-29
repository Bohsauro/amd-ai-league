/**
 * SPESEMED — Auth storage & session manager.
 *
 * TRADE-OFF ARCHITETTURALE (requisito TASK.md line 75):
 * ---------------------------------------------------
 * Memorizzazione Token: Memoria di runtime (stato React) + localStorage come persistenza.
 *
 * Pro:
 * 1. Resilienza ai reload della pagina: l'utente mantiene la sessione senza dover rifare il login.
 * 2. Immunità a CSRF: le chiamate API usano header 'Authorization: Bearer <token>',
 *    non cookie impliciti inviati dal browser.
 * 3. Supporta Cross-Origin API: il frontend può girare su un dominio/porta diverso dal backend
 *    senza vincoli complessi di third-party cookies.
 *
 * Contro e Mitigazioni:
 * 1. Rischio XSS: i dati in localStorage sono accessibili da script eseguiti nel medesimo origin.
 *    Mitigazione: l'app non include librerie di terze parti non controllate,
 *    i token di accesso hanno una scadenza breve (~1 ora), e il backend adotta
 *    il "Refresh Token Rotation" che invalida il refresh token vecchio ad ogni rinnovo.
 * 2. Invalidation: al logout o su 401 irreversibile, sia la memoria che localStorage vengono
 *    immediatamente ripuliti prima del redirect a /login.
 */

import { AuthResponse } from '../types/api';

const TOKEN_KEY = 'spesemed_access_token';
const REFRESH_KEY = 'spesemed_refresh_token';
const USER_KEY = 'spesemed_user_id';
const EMAIL_KEY = 'spesemed_user_email';
const EXPIRES_KEY = 'spesemed_expires_at';

export interface UserSession {
  accessToken: string;
  refreshToken: string | null;
  userId: string;
  email: string | null;
  expiresAt: number | null; // epoch ms
}

class AuthStore {
  private session: UserSession | null = null;

  constructor() {
    this.session = this.loadFromStorage();
  }

  private loadFromStorage(): UserSession | null {
    try {
      const accessToken = localStorage.getItem(TOKEN_KEY);
      const userId = localStorage.getItem(USER_KEY);
      if (!accessToken || !userId) {
        return null;
      }
      const refreshToken = localStorage.getItem(REFRESH_KEY);
      const email = localStorage.getItem(EMAIL_KEY);
      const expiresAtRaw = localStorage.getItem(EXPIRES_KEY);
      const expiresAt = expiresAtRaw ? parseInt(expiresAtRaw, 10) : null;

      return {
        accessToken,
        refreshToken,
        userId,
        email,
        expiresAt,
      };
    } catch {
      return null;
    }
  }

  public getSession(): UserSession | null {
    return this.session;
  }

  public getAccessToken(): string | null {
    return this.session?.accessToken ?? null;
  }

  public getRefreshToken(): string | null {
    return this.session?.refreshToken ?? null;
  }

  public getUserId(): string | null {
    return this.session?.userId ?? null;
  }

  public getEmail(): string | null {
    return this.session?.email ?? null;
  }

  public setSession(auth: AuthResponse, emailFallback?: string): UserSession {
    const expiresAt = auth.expires_in
      ? Date.now() + auth.expires_in * 1000
      : null;

    const email = emailFallback ?? this.session?.email ?? null;

    this.session = {
      accessToken: auth.access_token,
      refreshToken: auth.refresh_token ?? this.session?.refreshToken ?? null,
      userId: auth.user_id,
      email,
      expiresAt,
    };

    try {
      localStorage.setItem(TOKEN_KEY, this.session.accessToken);
      localStorage.setItem(USER_KEY, this.session.userId);
      if (this.session.refreshToken) {
        localStorage.setItem(REFRESH_KEY, this.session.refreshToken);
      } else {
        localStorage.removeItem(REFRESH_KEY);
      }
      if (this.session.email) {
        localStorage.setItem(EMAIL_KEY, this.session.email);
      }
      if (this.session.expiresAt) {
        localStorage.setItem(EXPIRES_KEY, this.session.expiresAt.toString());
      }
    } catch (e) {
      console.warn('Impossibile salvare token in localStorage:', e);
    }

    return this.session;
  }

  public clearSession(): void {
    this.session = null;
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_KEY);
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(EMAIL_KEY);
      localStorage.removeItem(EXPIRES_KEY);
    } catch (e) {
      console.warn('Errore durante la pulizia di localStorage:', e);
    }
  }

  public isTokenExpired(): boolean {
    if (!this.session?.expiresAt) return false;
    // Buffer di sicurezza di 30 secondi prima dell'effettiva scadenza
    return Date.now() >= this.session.expiresAt - 30_000;
  }
}

export const authStore = new AuthStore();
