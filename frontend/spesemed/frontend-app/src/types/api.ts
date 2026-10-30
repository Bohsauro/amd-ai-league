/**
 * SPESEMED Frontend — Type definitions matching backend FastAPI schemas.
 * Derived from:
 *   - src/spesemed/core/models.py
 *   - src/spesemed/api/schemas.py
 *   - src/spesemed/api/routes/*.py
 */

export const CATEGORIE_SPESA = [
  'Farmaci',
  'Visita Specialistica',
  'Dispositivo Medico',
  'Esami',
  'Altro',
] as const;

export type CategoriaSpesa = (typeof CATEGORIE_SPESA)[number];

/**
 * Modello SpesaMedica (models.py).
 * Tutti i campi sono tolleranti/opzionali ad eccezione di categoria_spesa (default 'Altro').
 */
export interface SpesaMedica {
  data_spesa: string | null; // YYYY-MM-DD
  esercente: string | null;
  importo_totale: number | null;
  codice_fiscale_paziente: string | null;
  categoria_spesa: CategoriaSpesa;
  // Campi UI estesi per tracciamento locale della ricevuta
  id?: string;
  source_file_name?: string;
  file_hash?: string;
  status?: 'validated' | 'pending' | 'draft';
}

/**
 * Health check response (GET /api/v1/health)
 */
export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  openrouter_configured: boolean;
}

/**
 * Sync extraction response (POST /api/v1/extract, N <= 3)
 */
export interface ExtractSyncResponse {
  results: SpesaMedica[];
  count: number;
  file_hashes: string[];
  cached: boolean[];
  model_used: string;
}

/**
 * Async extraction accepted (POST /api/v1/extract, N > 3, HTTP 202)
 */
export interface JobPendingResponse {
  job_id: string;
  status: string;
  file_count: number;
  poll_url: string;
}

export type ExtractionResponse =
  | { kind: 'sync'; data: ExtractSyncResponse }
  | { kind: 'async'; data: JobPendingResponse };

/**
 * Job status response (GET /api/v1/jobs/{job_id})
 */
export interface JobStatusResponse {
  job_id: string;
  status: 'pending' | 'processing' | 'done' | 'failed' | string;
  file_count: number;
  completed_count: number;
  results?: SpesaMedica[] | null;
  error?: string | null;
}

/**
 * Item in jobs list (GET /api/v1/jobs)
 */
export interface JobListItem {
  job_id: string;
  status: string;
  file_count: number;
  created_at?: string | null;
  updated_at?: string | null;
  last_error?: string | null;
}

/**
 * Paginated jobs list response (GET /api/v1/jobs)
 */
export interface JobListResponse {
  jobs: JobListItem[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * Category total aggregate for summary
 */
export interface CategoryTotal {
  categoria: string;
  importo: number;
  count: number;
}

/**
 * Summary / Profile usage response (GET /api/v1/summary)
 */
export interface UsageSummaryResponse {
  total_spese: number;
  totale_importo: number;
  total_jobs: number;
  jobs_done: number;
  jobs_failed: number;
  jobs_in_progress: number;
  per_categoria: CategoryTotal[];
}

/**
 * Auth request payload (POST /api/v1/auth/signup, /login)
 */
export interface AuthRequest {
  email: string;
  password: string;
}

/**
 * Refresh request payload (POST /api/v1/auth/refresh)
 */
export interface RefreshRequest {
  refresh_token: string;
}

/**
 * Auth response (POST /api/v1/auth/signup, /login, /refresh)
 */
export interface AuthResponse {
  access_token: string;
  user_id: string;
  refresh_token?: string | null;
  expires_in?: number | null;
}

/**
 * Export request payload (POST /api/v1/export)
 */
export interface ExportRequest {
  job_id?: string | null;
  file_hashes?: string[] | null;
}

/**
 * Waitlist request payload (POST /api/v1/waitlist)
 */
export interface WaitlistRequest {
  name: string;
  email: string;
  role: string;
}

/**
 * Waitlist response (POST /api/v1/waitlist)
 */
export interface WaitlistResponse {
  status: string;
  message: string;
}

export interface BillingStatusResponse {
  billing_enabled: boolean;
  plan: string;
  status: string;
  period_end?: string | null;
  extractions_limit: number;
  extractions_used: number;
}

export interface BillingCheckoutResponse {
  checkout_url: string;
  session_id: string;
  mode?: string;
}

/**
 * Standard backend error response (RFC 7807-ish)
 */
export interface ErrorResponse {
  detail: string;
  code?: string | null;
  retry_after_seconds?: number | null;
}
