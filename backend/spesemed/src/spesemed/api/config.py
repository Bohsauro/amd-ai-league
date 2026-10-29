"""SPESEMED API - Configurazione via pydantic-settings.

Tutte le impostazioni sono env-driven (con default sensati per sviluppo).
Vedi .env.example per la lista completa delle variabili supportate.
"""
from __future__ import annotations

from typing import Any, List, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurazione globale dell'API, letta da .env / variabili ambiente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Permette sia OPENROUTER_API_KEY che openrouter_api_key (case-insensitive).
    )

    # =====================================================================
    # OpenRouter (modello AI)
    # =====================================================================
    openrouter_api_key: str = Field(
        default="",
        description="API key di OpenRouter (https://openrouter.ai/keys).",
    )
    openrouter_model: str = Field(
        default="google/gemini-2.5-flash-lite",
        description="Modello Vision da usare. Default: gemini-2.5-flash-lite (economico).",
    )
    app_name: str = Field(
        default="SPESEMED",
        description="Nome app inviato a OpenRouter (X-Title header).",
    )
    app_url: str = Field(
        default="https://spesemed.local",
        description="URL app inviato a OpenRouter (HTTP-Referer header).",
    )

    # =====================================================================
    # Server / CORS
    # =====================================================================
    cors_origins: Union[List[str], str] = Field(
        # SECURITY (FIX M4 audit): default localhost-only + Streamlit.
        # Mai "["*"]" come default perche' combinato con credentials
        # = classico misconfiguration da security review.
        # Override in .env con la lista domini produzione.
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8501",  # Streamlit dashboard
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8501",
        ],
        description=(
            "Origini CORS permesse. Default: localhost-only (localhost:3000, "
            "localhost:8501) per dev. In produzione: lista domini esplicita "
            "via env CORS_ORIGINS (mai wildcard '*')."
        ),
    )
    cors_allow_credentials: bool = Field(
        default=False,
        description="Se true, CORS accetta cookie/auth headers. Default false per * origins.",
    )

    # =====================================================================
    # Upload limits
    # =====================================================================
    max_upload_size_mb: int = Field(
        default=20,
        description="Dimensione massima per singolo file (MB).",
    )
    max_sync_files: int = Field(
        default=3,
        description="Numero massimo di file in sync mode (N>3 andrà in async — Fase 3).",
    )

    # =====================================================================
    # Auth (Fase 2)
    # =====================================================================
    mock_user_id_default: str = Field(
        default="anonymous",
        description="User ID usato se mancano header auth (mock fallback).",
    )
    allow_signup: bool = Field(
        default=True,
        description="Se False, /auth/signup ritorna 403. Da disabilitare in produzione se "
                    "l'onboarding e' gestito via invito admin.",
    )
    allow_dev_mock_auth: bool = Field(
        default=False,
        description=(
            "OPT-IN esplicito per modalita' mock-auth (dev/test). Se False, l'app "
            "fall-closes (503) quando SUPABASE_JWT_SECRET manca, ANCHE in dev. "
            "Mai True in produzione: esporrebbe identity-spoofing. Default False."
        ),
    )
    max_async_files: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Numero massimo di file per job async (N>max_sync_files e N<=max_async_files).",
    )

    # =====================================================================
    # Supabase (Fase 2): PostgreSQL + Storage + Auth
    # =====================================================================
    supabase_url: str = Field(
        default="",
        description="Project URL di Supabase (es. https://xxx.supabase.co).",
    )
    supabase_service_key: str = Field(
        default="",
        description="Service role key di Supabase (bypassa RLS, MAI esporre al client).",
    )
    supabase_bucket: str = Field(
        default="receipts",
        description="Bucket Storage dove salvare le ricevute originali.",
    )
    supabase_jwt_secret: str = Field(
        default="",
        description="JWT secret di Supabase (Settings → API → JWT Secret). "
                    "Usato SOLO per token HS256 (legacy/symmetric). Progetti "
                    "Supabase moderni usano ES256 con JWKS: in quel caso "
                    "basta configurare SUPABASE_URL.",
    )
    supabase_jwks_url: str = Field(
        default="",
        description="Endpoint JWKS di Supabase per verifica ES256 (EC P-256 "
                    "asimmetrico). Default: auto-derivato da SUPABASE_URL "
                    "<URL>/auth/v1/.well-known/jwks.json. Override solo se "
                    "usi un proxy CDN o un mirror.",
    )

    # =====================================================================
    # Worker async (Fase 2)
    # =====================================================================
    worker_poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=60.0,
        description="Intervallo di polling del worker (secondi).",
    )
    worker_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Numero massimo di retry per job prima di marcarlo 'failed'.",
    )
    worker_zombie_timeout_minutes: int = Field(
        default=10,
        ge=1,
        description="Minuti dopo i quali un job 'processing' viene considerato zombie.",
    )

    # =====================================================================
    # Rate limiting (Fase 3 + Fase 4 Redis multi-worker)
    # =====================================================================
    rate_limit_extract: str = Field(
        default="10/minute",
        description="Limite rate per POST /api/v1/extract (per user o IP).",
    )
    rate_limit_jobs: str = Field(
        default="60/minute",
        description="Limite rate per GET /api/v1/jobs/{id} (polling client).",
    )
    rate_limit_login: str = Field(
        default="5/minute",
        description="Limite rate per /auth/login (anti brute-force).",
    )
    rate_limit_signup: str = Field(
        default="2/hour",
        description="Limite rate per /auth/signup (anti account-spam).",
    )
    rate_limit_refresh: str = Field(
        default="30/minute",
        description="Limite rate per /auth/refresh.",
    )
    rate_limit_logout: str = Field(
        default="20/minute",
        description="Limite rate per /auth/logout.",
    )
    rate_limit_export: str = Field(
        default="10/minute",
        description="Limite rate per POST /api/v1/export (generazione ZIP per commercialista).",
    )
    rate_limit_storage_backend: str = Field(
        default="memory",
        description=(
            "Backend storage per slowapi. Valori accettati:\n"
            "  - 'memory' (default): in-memory, PER-WORKER (OK solo per API_WORKERS=1).\n"
            "  - 'redis://host:port': Redis URI diretta (es. redis://redis:6379/0).\n"
            "  - 'redis': usa REDIS_URL come URI (comodo per docker-compose).\n"
            "In produzione multi-worker (API_WORKERS>1), OBBLIGATORIO usare Redis "
            "per evitare che i limiti vengano moltiplicati × N worker."
        ),
    )
    redis_url: str = Field(
        default="",
        description=(
            "Redis connection URL (es. redis://localhost:6379/0). "
            "Usato quando RATE_LIMIT_STORAGE_BACKEND='redis'. "
            "Richiesto in produzione multi-worker per rate-limit condiviso."
        ),
    )

    # =====================================================================
    # Monitoring (Fase 3 + Fase 3.5 Prometheus metrics)
    # =====================================================================
    prometheus_metrics_enabled: bool = Field(
        default=True,
        description="Esposizione /metrics abilitata. Default True. "
                    "Disabilitare solo dietro reverse proxy con auth custom.",
    )
    metrics_ip_allowlist: Union[List[str], str] = Field(
        # SECURITY (FIX M6 audit 2025): defense-in-depth per /metrics anche
        # quando il reverse proxy (Caddy/nginx) e' assente o misconfigurato.
        # Default: solo loopback (127.0.0.1 + ::1) — Prometheus scraper
        # locale nel container stesso + reverse proxy nello stesso host.
        # Override in .env con CIDR/IP aggiuntivi per Prometheus remoto:
        #   METRICS_IP_ALLOWLIST=["127.0.0.1","::1","10.0.0.0/24"]
        default_factory=lambda: ["127.0.0.1", "::1"],
        description=(
            "IP o CIDR (IPv4/IPv6) autorizzati a chiamare GET /metrics. "
            "Leave default (loopback) se Prometheus gira nello stesso host/container. "
            "Lista vuota + API_ENV=production = fail-closed (403)."
        ),
    )
    metrics_trust_xff: bool = Field(
        default=False,
        description=(
            "Se True, onora X-Forwarded-For per identificare il client reale, "
            "MA solo quando la connessione diretta (peer TCP) e' autorizzata "
            "in metrics_ip_allowlist. Default False: in produzione, se hai un "
            "reverse proxy trusted, abilitalo esplicitamente."
        ),
    )
    admin_token: str = Field(
        default="",
        description="Token statico per endpoint admin (es. POST /admin/auth/reset-jwks-cache). "
                    "Header atteso: X-Admin-Token. Vuoto = endpoint disabilitato (403). "
                    "Genera con: python -c \"import secrets; print(secrets.token_urlsafe(32))\".",
    )
    sentry_dsn: str = Field(
        default="",
        description="DSN Sentry per error tracking (vuoto = disabilitato).",
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Frazione di transazioni da tracciare su Sentry (0.0-1.0).",
    )

    # =====================================================================
    # API metadata
    # =====================================================================
    api_version: str = "0.3.0"
    api_env: str = Field(
        default="development",
        description="Ambiente: development | production. Cambia logging verbosity.",
    )
    api_workers: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Numero di worker uvicorn (solo produzione; in dev usa 1).",
    )

    @field_validator("cors_origins", "metrics_ip_allowlist", mode="after")
    @classmethod
    def parse_list_from_env(cls, v: Any) -> List[str]:
        """Parsa stringhe da env in liste, gestendo sia JSON che valori separati da virgole."""
        import json
        if isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                return []
            if v_str.startswith("[") and v_str.endswith("]"):
                try:
                    res = json.loads(v_str)
                    if isinstance(res, list):
                        return [str(x).strip() for x in res if str(x).strip()]
                except Exception:
                    pass
            return [item.strip() for item in v_str.split(",") if item.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []


# Singleton: importabile come `from .config import settings`
settings = Settings()
