/**
 * SPESEMED API Client — Typed HTTP client consuming FastAPI endpoints.
 *
 * Requirements:
 * - Base URL from `VITE_API_BASE_URL` (default http://localhost:8000)
 * - Prefix `/api/v1`
 * - Automatic Authorization header injection (Bearer token)
 * - Dev fallback to X-User-Id if enabled and no JWT is present
 * - Auto-refresh on 401 with concurrency lock
 * - Graceful error handling (standard ErrorResponse parsing)
 * - Binary blob handling for POST /export (ZIP download)
 */

import {
  AuthRequest,
  AuthResponse,
  ErrorResponse,
  ExportRequest,
  ExtractionResponse,
  ExtractSyncResponse,
  HealthResponse,
  JobListResponse,
  JobPendingResponse,
  JobStatusResponse,
  RefreshRequest,
  UsageSummaryResponse,
  WaitlistRequest,
  WaitlistResponse,
} from '../types/api';
import { authStore } from './auth';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
const API_V1 = `${API_BASE_URL}/api/v1`;
const DEV_MOCK_USER_ID = import.meta.env.VITE_DEV_MOCK_USER_ID || '';

export class ApiError extends Error {
  public status: number;
  public code?: string | null;
  public detail: string;
  public retryAfterSeconds?: number | null;

  constructor(status: number, detail: string, code?: string | null, retryAfterSeconds?: number | null) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

// Mutex per refresh token concorrente
let isRefreshing = false;
let refreshPromise: Promise<string | null> | null = null;

// Callback per notificare logout forzato (es. refresh fallito)
type LogoutListener = () => void;
const logoutListeners: Set<LogoutListener> = new Set();

export function onAuthFailure(listener: LogoutListener): () => void {
  logoutListeners.add(listener);
  return () => logoutListeners.delete(listener);
}

function notifyLogout() {
  authStore.clearSession();
  logoutListeners.forEach((fn) => {
    try {
      fn();
    } catch (e) {
      console.error('Errore listener logout:', e);
    }
  });
}

/**
 * Tenta il refresh token coordinato
 */
async function performTokenRefresh(): Promise<string | null> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  const currentRefreshToken = authStore.getRefreshToken();
  if (!currentRefreshToken) {
    notifyLogout();
    return null;
  }

  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_V1}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: currentRefreshToken } as RefreshRequest),
      });

      if (!res.ok) {
        throw new Error('Refresh fallito');
      }

      const data: AuthResponse = await res.json();
      authStore.setSession(data);
      return data.access_token;
    } catch (err) {
      console.warn('Sessione scaduta o non valida durante refresh:', err);
      notifyLogout();
      return null;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Wrapper HTTP standard con auto-refresh e gestione errori
 */
async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  isRetry = false
): Promise<T> {
  const url = endpoint.startsWith('http') ? endpoint : `${API_V1}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
  const headers = new Headers(options.headers || {});

  // Iniezione Token o Mock
  const token = authStore.getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  } else if (DEV_MOCK_USER_ID) {
    headers.set('X-User-Id', DEV_MOCK_USER_ID);
  }

  const fetchOptions: RequestInit = {
    ...options,
    headers,
  };

  let response: Response;
  try {
    response = await fetch(url, fetchOptions);
  } catch (netErr: unknown) {
    const msg = netErr instanceof Error ? netErr.message : 'Errore di connessione di rete';
    console.warn(`SPESEMED API non raggiungibile (${API_BASE_URL}):`, msg);
    throw new ApiError(
      0,
      'Server non raggiungibile. Controlla la connessione e riprova tra poco.',
      'network_error'
    );
  }

  // Auto-refresh su 401 (solo una volta)
  if (response.status === 401 && !isRetry && !endpoint.includes('/auth/')) {
    const newAccessToken = await performTokenRefresh();
    if (newAccessToken) {
      return request<T>(endpoint, options, true);
    }
    throw new ApiError(401, 'Sessione scaduta. Effettua nuovamente l’accesso.', 'unauthorized');
  }

  if (response.status === 403 && !endpoint.includes('/auth/signup')) {
    // 403 permanente su risorsa protetta
    notifyLogout();
    throw new ApiError(403, 'Accesso non consentito per questa risorsa.', 'forbidden');
  }

  if (!response.ok) {
    let detail = `Errore HTTP ${response.status}`;
    let code: string | null = null;
    let retryAfterSeconds: number | null = null;

    try {
      const errJson = (await response.json()) as ErrorResponse;
      if (typeof errJson.detail === 'string' && errJson.detail.trim()) detail = errJson.detail;
      if (errJson.code) code = errJson.code;
      if (errJson.retry_after_seconds) retryAfterSeconds = errJson.retry_after_seconds;
    } catch {
      // Body non-JSON (es. 502/504 Bad Gateway HTML da reverse proxy)
      const text = await response.text().catch(() => '');
      if (text) detail = text.slice(0, 160);
    }

    throw new ApiError(response.status, detail, code, retryAfterSeconds);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  // ── Health ─────────────────────────────────────────────────────────────
  async health(): Promise<HealthResponse> {
    return request<HealthResponse>('/health');
  },

  // ── Auth ───────────────────────────────────────────────────────────────
  async signup(data: AuthRequest): Promise<AuthResponse> {
    const res = await request<AuthResponse>('/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    authStore.setSession(res, data.email);
    return res;
  },

  async login(data: AuthRequest): Promise<AuthResponse> {
    const res = await request<AuthResponse>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    authStore.setSession(res, data.email);
    return res;
  },

  async refresh(refreshToken: string): Promise<AuthResponse> {
    const res = await request<AuthResponse>('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    authStore.setSession(res);
    return res;
  },

  async logout(): Promise<void> {
    const token = authStore.getAccessToken();
    try {
      if (token) {
        await fetch(`${API_V1}/auth/logout`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
      }
    } catch (e) {
      console.warn('Logout server-side fallito (best-effort):', e);
    } finally {
      authStore.clearSession();
    }
  },

  // ── Extract (Sync o Async) ─────────────────────────────────────────────
  async extract(files: File[]): Promise<ExtractionResponse> {
    const formData = new FormData();
    for (const f of files) {
      formData.append('files', f);
    }

    const headers = new Headers();
    const token = authStore.getAccessToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    } else if (DEV_MOCK_USER_ID) {
      headers.set('X-User-Id', DEV_MOCK_USER_ID);
    }

    let res: Response;
    try {
      res = await fetch(`${API_V1}/extract`, {
        method: 'POST',
        headers,
        body: formData,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Connessione non riuscita';
      console.warn(`Estrazione: rete/upload non riuscito:`, msg);
      throw new ApiError(0, 'Server non raggiungibile. Controlla la connessione e riprova tra poco.', 'network_error');
    }

    if (res.status === 401) {
      const newToken = await performTokenRefresh();
      if (newToken) {
        // Riprova con nuovo token
        headers.set('Authorization', `Bearer ${newToken}`);
        res = await fetch(`${API_V1}/extract`, {
          method: 'POST',
          headers,
          body: formData,
        });
      }
    }

    if (res.status === 401) {
      // Refresh fallito o rifiutato: sessione non più valida
      notifyLogout();
      throw new ApiError(401, 'Sessione scaduta. Effettua nuovamente l’accesso.', 'unauthorized');
    }

    if (res.status === 403) {
      notifyLogout();
      throw new ApiError(403, 'Accesso non consentito per questa risorsa.', 'forbidden');
    }

    if (!res.ok) {
      let detail = `Errore estrazione (${res.status})`;
      let code: string | null = null;
      try {
        const errJson = (await res.json()) as ErrorResponse;
        if (typeof errJson.detail === 'string' && errJson.detail.trim()) detail = errJson.detail;
        if (errJson.code) code = errJson.code;
      } catch {
        const txt = await res.text().catch(() => '');
        if (txt) detail = txt.slice(0, 160);
      }
      throw new ApiError(res.status, detail, code);
    }

    if (res.status === 202) {
      const asyncData = (await res.json()) as JobPendingResponse;
      return { kind: 'async', data: asyncData };
    }

    const syncData = (await res.json()) as ExtractSyncResponse;
    return { kind: 'sync', data: syncData };
  },

  // ── Jobs ───────────────────────────────────────────────────────────────
  async getJob(jobId: string): Promise<JobStatusResponse> {
    return request<JobStatusResponse>(`/jobs/${encodeURIComponent(jobId)}`);
  },

  async listJobs(limit = 20, offset = 0): Promise<JobListResponse> {
    return request<JobListResponse>(`/jobs?limit=${limit}&offset=${offset}`);
  },

  // ── Summary ────────────────────────────────────────────────────────────
  async getSummary(): Promise<UsageSummaryResponse> {
    return request<UsageSummaryResponse>('/summary');
  },

  // ── Export (ZIP binary blob) ───────────────────────────────────────────
  async exportZip(payload?: ExportRequest): Promise<{ blob: Blob; filename: string }> {
    const headers = new Headers({
      'Content-Type': 'application/json',
    });
    const token = authStore.getAccessToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    } else if (DEV_MOCK_USER_ID) {
      headers.set('X-User-Id', DEV_MOCK_USER_ID);
    }

    const doFetch = async (authHeader?: string) => {
      const finalHeaders = new Headers(headers);
      if (authHeader) {
        finalHeaders.set('Authorization', authHeader);
      } else if (token) {
        finalHeaders.set('Authorization', `Bearer ${token}`);
      }
      return fetch(`${API_V1}/export`, {
        method: 'POST',
        headers: finalHeaders,
        body: payload ? JSON.stringify(payload) : JSON.stringify({}),
      });
    };

    let res: Response;
    try {
      res = await doFetch();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Connessione non riuscita';
      console.warn(`Export: rete non raggiungibile:`, msg);
      throw new ApiError(0, 'Server non raggiungibile. Controlla la connessione e riprova tra poco.', 'network_error');
    }

    if (res.status === 401 && token) {
      const newToken = await performTokenRefresh();
      if (newToken) {
        res = await doFetch(`Bearer ${newToken}`);
      }
    }

    if (res.status === 401) {
      notifyLogout();
      throw new ApiError(401, 'Sessione scaduta. Effettua nuovamente l’accesso.', 'unauthorized');
    }

    if (res.status === 403) {
      notifyLogout();
      throw new ApiError(403, 'Accesso non consentito per questa risorsa.', 'forbidden');
    }

    if (!res.ok) {
      let detail = `Errore durante l'esportazione (${res.status})`;
      let code: string | null = null;
      try {
        const err = (await res.json()) as ErrorResponse;
        if (typeof err.detail === 'string' && err.detail.trim()) detail = err.detail;
        if (err.code) code = err.code;
      } catch {
        const txt = await res.text().catch(() => '');
        if (txt) detail = txt.slice(0, 160);
      }
      throw new ApiError(res.status, detail, code);
    }

    // Estrai il nome file dal Content-Disposition se presente
    let filename = 'spesemed_export.zip';
    const disposition = res.headers.get('content-disposition');
    if (disposition && disposition.includes('filename=')) {
      const match = disposition.match(/filename="?([^";]+)"?/);
      if (match && match[1]) {
        filename = match[1];
      }
    }

    const blob = await res.blob();
    return { blob, filename };
  },

  // ── Waitlist ───────────────────────────────────────────────────────────
  async joinWaitlist(data: WaitlistRequest): Promise<WaitlistResponse> {
    return request<WaitlistResponse>('/waitlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
};
