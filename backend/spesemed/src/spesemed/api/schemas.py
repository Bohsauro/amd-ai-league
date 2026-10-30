"""SPESEMED API - Pydantic schemas per request/response.

Definisce i contratti JSON dell'API. Le SpesaMedica del core engine sono
riusate direttamente (sono già Pydantic e serializzabili).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from spesemed.core.models import SpesaMedica


# =============================================================================
# /api/v1/health
# =============================================================================

class HealthResponse(BaseModel):
    """Response per GET /api/v1/health."""
    status: str = Field(default="ok", description="Liveness status.")
    service: str = Field(default="spesemed-api", description="Service name.")
    version: str = Field(default="0.1.0", description="API version.")
    openrouter_configured: bool = Field(
        ...,
        description="True se OPENROUTER_API_KEY è impostata e non vuota.",
    )


# =============================================================================
# /api/v1/extract (sync, N<=3)
# =============================================================================

class ExtractSyncResponse(BaseModel):
    """Response per POST /api/v1/extract in modalità sync (N<=3 file)."""
    results: List[SpesaMedica] = Field(
        ...,
        description="Array di SpesaMedica estratti (1 elemento per file processato).",
    )
    count: int = Field(
        ...,
        description="Numero di risultati (= numero di file elaborati con successo).",
    )
    file_hashes: List[str] = Field(
        default_factory=list,
        description="SHA-256 di ogni file (per idempotency cache in Fase 2).",
    )
    cached: List[bool] = Field(
        default_factory=list,
        description="True se il risultato viene dalla cache extractions (no nuova chiamata AI).",
    )
    model_used: str = Field(
        ...,
        description="ID del modello OpenRouter usato per l'estrazione.",
    )


class JobPendingResponse(BaseModel):
    """Response per POST /api/v1/extract in modalità async (N>3, non ancora in Fase 1)."""
    job_id: str = Field(..., description="UUID del job async.")
    status: str = Field(default="pending", description="Stato iniziale.")
    file_count: int = Field(..., description="Numero di file nel job.")
    poll_url: str = Field(..., description="URL per fare polling dello stato.")


# =============================================================================
# /api/v1/jobs/{id} (stub — implementazione in Fase 3)
# =============================================================================

class JobStatusResponse(BaseModel):
    """Response per GET /api/v1/jobs/{id}."""
    job_id: str
    status: str = Field(..., description="pending | processing | done | failed")
    file_count: int = 0
    completed_count: int = 0
    results: Optional[List[SpesaMedica]] = None
    error: Optional[str] = None


class JobListItem(BaseModel):
    """Riga leggera per GET /api/v1/jobs (storico utente)."""
    job_id: str
    status: str
    file_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_error: Optional[str] = None


class JobListResponse(BaseModel):
    """Response per GET /api/v1/jobs (lista job dell'utente)."""
    jobs: List[JobListItem]
    total: int = 0
    limit: int = 20
    offset: int = 0


# =============================================================================
# Errori standard
# =============================================================================

class ErrorResponse(BaseModel):
    """Standard error response (RFC 7807-ish, semplificato)."""
    detail: str = Field(..., description="Messaggio leggibile per l'utente.")
    code: Optional[str] = Field(default=None, description="Codice errore (per i18n lato client).")


# =============================================================================
# /api/v1/auth/* (signup, login, refresh, logout)
# =============================================================================

class AuthResponse(BaseModel):
    """Response per /auth/signup, /auth/login, /auth/refresh."""
    access_token: str = Field(..., description="JWT da usare come Bearer token.")
    user_id: str = Field(..., description="UUID dell'utente (sub claim del JWT).")
    refresh_token: Optional[str] = Field(default=None, description="Token per rinnovare la sessione.")
    expires_in: Optional[int] = Field(default=None, description="Secondi prima della scadenza del token.")


# =============================================================================
# /api/v1/export (Fase 4B)
# =============================================================================

class ExportRequest(BaseModel):
    """Request per POST /api/v1/export.

    Filtri opzionali: se nessuno è indicato, vengono esportate TUTTE le
    estrazioni dell'utente. `job_id` esporta solo le estrazioni di un job;
    `file_hashes` esporta solo i file specificati (per idempotency key).
    """
    job_id: Optional[str] = Field(
        default=None,
        description="UUID del job async di cui esportare le estrazioni.",
    )
    file_hashes: Optional[List[str]] = Field(
        default=None,
        description="Lista di SHA-256 dei file da esportare (filtro opzionale).",
    )


# =============================================================================
# /api/v1/summary (Profilo utente / usage)
# =============================================================================

class CategoryTotal(BaseModel):
    """Totale di una singola categoria di spesa."""
    categoria: str = Field(..., description="Nome categoria (Farmaci, Visita, ...).")
    importo: float = Field(0.0, description="Somma importi per la categoria.")
    count: int = Field(0, description="Numero di spese nella categoria.")


class UsageSummaryResponse(BaseModel):
    """Response per GET /api/v1/summary: riepilogo spese + usage utente.

    Aggrega le `extractions` (spese) e i `jobs` dell'utente autenticato per
    la schermata Profilo del client.
    """
    total_spese: int = Field(0, description="Numero totale di spese estratte.")
    totale_importo: float = Field(0.0, description="Somma totale degli importi (EUR).")
    total_jobs: int = Field(0, description="Numero totale di job (elaborazioni).")
    jobs_done: int = Field(0, description="Job completati con successo.")
    jobs_failed: int = Field(0, description="Job falliti.")
    jobs_in_progress: int = Field(0, description="Job in coda o in elaborazione.")
    per_categoria: List[CategoryTotal] = Field(
        default_factory=list,
        description="Totali per categoria, ordinati per importo decrescente.",
    )


class BillingStatusResponse(BaseModel):
    """Response per GET /api/v1/billing/status (contratto frontend Profilo).

    ``billing_enabled=false`` non e' un errore: il client riceve comunque 200
    con piano free e limiti a zero, cosi' la UI non si rompe quando Stripe non
    e' configurato.
    """
    billing_enabled: bool = Field(
        default=False,
        description="True se il billing Stripe e' attivo (kill switch BILLING_ENABLED).",
    )
    plan: str = Field(default="free", description="Piano utente: free | pro.")
    status: str = Field(
        default="none",
        description="Stato abbonamento: none | active | trialing | past_due | canceled.",
    )
    period_end: Optional[str] = Field(
        default=None,
        description="Fine periodo corrente (ISO 8601), None se piano free.",
    )
    extractions_limit: int = Field(
        default=0,
        description="Estrazioni incluse nel periodo corrente (0 per il piano free).",
    )
    extractions_used: int = Field(
        default=0,
        description="Estrazioni consumate nel periodo corrente.",
    )


class RateLimitResponse(BaseModel):
    """Response standard per 429 (rate limit exceeded)."""
    detail: str = Field(default="Troppe richieste. Riprova piu' tardi.", description="Messaggio leggibile.")
    code: str = Field(default="rate_limit_exceeded", description="Codice errore (per i18n lato client).")
    retry_after_seconds: Optional[int] = Field(
        default=None, description="Secondi da aspettare prima del prossimo tentativo."
    )
