"""SPESEMED API - FastAPI app entrypoint.

Configurazione globale:
    - Logging strutturato (JSON-ready per produzione)
    - CORS middleware (origini configurabili)
    - SlowAPI rate limiter (Fase 3)
    - Sentry init lazy (Fase 3, se SENTRY_DSN settato)
    - Prometheus /metrics endpoint (Fase 3.5, se PROMETHEUS_METRICS_ENABLED)
    - Admin endpoint POST /admin/auth/reset-jwks-cache (auth: X-Admin-Token)
    - Lifespan: start/stop del JobWorker asincrono (se Supabase configurato)
    - Routers: health, extract, jobs, auth (signup, login, refresh, logout)
    - OpenAPI auto-doc su /docs
"""
from __future__ import annotations

import ipaddress
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .config import settings
from .jwt_decoder import reset_jwks_cache
from .metrics import prometheus_http_metrics
from .metrics_acl import check_metrics_authorization
from .rate_limit import _redact_redis_uri, limiter
from .routes import auth, billing, export, extract, health, jobs, summary, waitlist
from .worker import JobWorker

# Singleton del worker: istanziato al module-load, startato nello lifespan.
_worker = JobWorker()


# =============================================================================
# Logging
# =============================================================================
def _setup_logging() -> None:
    """Configura il logging root."""
    level = logging.DEBUG if settings.api_env == "development" else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Riduci verbosita' di librerie rumorose
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
    logging.getLogger("gotrue").setLevel(logging.WARNING)
    logging.getLogger("postgrest").setLevel(logging.WARNING)
    logging.getLogger("supabase").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("spesemed.api")


# =============================================================================
# Helper: warning multi-worker + memory rate-limit (FIX H1 audit, Fase 4)
# =============================================================================
def _warn_if_multi_worker_memory_rate_limit() -> None:
    """FIX H1 (audit 2025): WARNING di startup se l'API gira con
    API_WORKERS > 1 ma il rate-limit storage e' ancora "memory" (PER-WORKER).

    Foot-gun: un operatore scala a 2+ worker senza Redis e non si accorge
    che i limiti "5/minute" diventano 10/minute (o peggio). Il WARNING
    qui e' early e visibile nei log di avvio a livello WARNING.
    """
    if settings.api_workers <= 1:
        return
    backend = settings.rate_limit_storage_backend.strip()
    if not backend or backend == "memory":
        logger.warning(
            "API_WORKERS=%d ma RATE_LIMIT_STORAGE_BACKEND='%s' (PER-WORKER!). "
            "I limiti di rate saranno moltiplicati x%d worker. "
            "Per consistenza, configurare Redis:\n"
            "  RATE_LIMIT_STORAGE_BACKEND=redis\n"
            "  REDIS_URL=redis://redis:6379/0\n"
            "(Vedi .env.example e docker-compose.prod.yml per setup completo.)",
            settings.api_workers, backend or "memory", settings.api_workers,
        )


# =============================================================================
# Helper: readiness Redis per il rate-limit storage (Fase 4C-A2)
# =============================================================================
def _check_redis_readiness() -> bool:
    """Ping Redis se configurato come storage rate-limit. True = ok / non richiesto.

    Il boot NON viene interrotto se Redis e' irraggiungibile (decisione di
    resilienza: l'app parte, i limiti possono degradare). Il log ERROR e'
    esplicito cosi' l'operatore/SMOKE_TEST se ne accorge subito, invece di
    scoprirlo con 500/429 randomici al primo hit.
    """
    backend = settings.rate_limit_storage_backend.strip()
    if backend in ("", "memory"):
        logger.debug("Redis readiness: storage memory, skip")
        return True

    if backend == "redis":
        url = settings.redis_url.strip()
        if not url:
            logger.error(
                "Redis readiness FALLITA: RATE_LIMIT_STORAGE_BACKEND=redis "
                "ma REDIS_URL e' vuota. Rate-limit multi-worker NON garantito."
            )
            return False
    elif backend.startswith(("redis://", "rediss://")):
        url = backend
    else:
        logger.warning(
            "Redis readiness: backend %r non riconosciuto, skip (fallback memory).",
            backend,
        )
        return True

    safe_target = _redact_redis_uri(url)
    try:
        import redis as redis_lib

        client = redis_lib.from_url(
            url, socket_connect_timeout=2, socket_timeout=2
        )
        client.ping()
        logger.info("Redis readiness OK (%s)", safe_target)
        return True
    except Exception as e:  # noqa: BLE001 - best-effort readiness, mai crash al boot
        logger.error(
            "Redis NON raggiungibile (%s): %s. "
            "Rate-limit multi-worker non garantito.",
            safe_target,
            e,
        )
        return False


# =============================================================================
# Helper: warning loopback-only metrics allowlist (FIX M6)
# =============================================================================
def _warn_if_loopback_only_metrics_in_prod() -> None:
    """FIX M6 (audit 2025): WARNING di startup se /metrics e' esposto solo
    a loopback in produzione.

    Foot-gun: l'operatore deploya Prometheus su host separato e l'app
    risponde 403 senza un chiaro indizio. Il WARNING qui e' early e visibile
    nei log di avvio (livello WARNING => mostrato in produzione, INFO in dev).
    """
    if not settings.prometheus_metrics_enabled or settings.api_env != "production":
        return
    if not settings.metrics_ip_allowlist:
        # Lista vuota: produzione fail-closed a 403 (gia' WARN in ACL).
        # Non duplichiamo qui.
        return
    try:
        nets = [ipaddress.ip_network(e, strict=False) for e in settings.metrics_ip_allowlist]
    except (ValueError, TypeError):
        # ACL malformata: verra' loggata a runtime da check_metrics_authorization.
        return
    # NB: match "esatto" host (127.0.0.1/32, ::1/128). Subnet piu' ampie
    # come 127.0.0.0/8 NON sono considerate loopback-only di proposito (false
    # negative preferibile a false positive che spaventerebbe operator
    # legittimamente multi-host).
    loopback_only = all(
        (n.network_address == ipaddress.IPv4Address("127.0.0.1") and n.prefixlen == 32)
        or (n.network_address == ipaddress.IPv6Address("::1") and n.prefixlen == 128)
        for n in nets
    )
    # Vincolo anche sulla dimensione della lista: con 3+ entry e' molto
    # probabile che l'utente abbia esplicitamente aggiunto lo scraper IP.
    if loopback_only and len(nets) <= 2:
        logger.warning(
            "METRICS_IP_ALLOWLIST contiene solo loopback %s: Prometheus scraper "
            "su host remoti verra' NEGATO con 403. Per multi-host deploy, "
            "aggiungere l'IP/CIDR dello scraper in .env (es. METRICS_IP_ALLOWLIST="
            "['127.0.0.1','::1','10.0.0.5']).",
            settings.metrics_ip_allowlist,
        )


# =============================================================================
# Helper: warning CORS wildcard in produzione (FIX M4 audit 2026)
# =============================================================================
def _warn_if_wildcard_cors_in_prod() -> None:
    """FIX M4: WARNING di startup se CORS_ORIGINS e' wildcard '*' in produzione.

    Foot-gun: deploy in produzione con CORS '*' consente a siti web terzi
    di eseguire richieste verso l'API dal browser dell'utente.
    """
    if settings.api_env == "production" and ("*" in _cors_origins or not settings.cors_origins):
        logger.warning(
            "CORS_ORIGINS e' impostato su wildcard '*' o vuoto in produzione! "
            "Configurare una lista esplicita di domini (es. CORS_ORIGINS=['https://app.spesemed.it'])."
        )


# =============================================================================
# Helper: warning billing config incompleta (Fase 4C-C1)
# =============================================================================
def _warn_if_billing_misconfigured() -> None:
    """ERROR di startup se BILLING_ENABLED=true ma mancano secrets/price.

    Il boot NON viene interrotto (kill switch resiliente): le route billing
    risponderanno 503 e /extract non applichera' il gating. Il log e' ERROR
    perche' un billing "acceso" ma incompleto e' quasi sempre un deploy rotto.
    """
    if not settings.billing_enabled:
        return
    missing = [
        name
        for name, value in (
            ("STRIPE_SECRET_KEY", settings.stripe_secret_key),
            ("STRIPE_WEBHOOK_SECRET", settings.stripe_webhook_secret),
            ("STRIPE_PRICE_ID", settings.stripe_price_id),
        )
        if not value.strip()
    ]
    if missing:
        logger.error(
            "BILLING_ENABLED=true ma configurazione Stripe incompleta: mancano %s. "
            "Le route billing risponderanno 503 e /extract non sara' gated. "
            "Configura le variabili in .env (vedi .env.example) oppure imposta "
            "BILLING_ENABLED=false per disattivare il billing.",
            ", ".join(missing),
        )


# =============================================================================
# Sentry (opzionale, Fase 3)
# =============================================================================
def _init_sentry() -> None:
    """Inizializza Sentry solo se SENTRY_DSN e' configurato.

    NB: in dev Sentry resta vuoto (no error tracking esterno).
    Per produzione: configurare SENTRY_DSN=https://...@sentry.io/...
    """
    if not settings.sentry_dsn:
        logger.debug("Sentry non inizializzato (SENTRY_DSN vuoto)")
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            environment=settings.api_env,
            release=f"spesemed-api@{settings.api_version}",
            # Profiling opzionale (richiede sentry-sdk[performance])
            # profiles_sample_rate=0.1,
        )
        logger.info(
            "Sentry inizializzato (env=%s, sample_rate=%.2f)",
            settings.api_env, settings.sentry_traces_sample_rate,
        )
    except Exception as e:
        # Best-effort: non bloccare boot per un errore Sentry
        logger.warning("Sentry init fallito: %s", e)


# =============================================================================
# Lifespan (startup/shutdown events)
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events del FastAPI app.

    - Startup: Sentry init + worker start (se Supabase configurato).
    - Shutdown: worker stop gracefully.
    """
    logger.info(
        "SPESEMED API v%s starting up (env=%s, model=%s, workers=%d)",
        settings.api_version,
        settings.api_env,
        settings.openrouter_model,
        settings.api_workers,
    )
    if settings.openrouter_api_key:
        logger.info("OpenRouter API key: configurata (lunghezza %d)", len(settings.openrouter_api_key))
    else:
        logger.warning("OpenRouter API key: NON configurata (/extract 503)")

    if settings.supabase_url:
        logger.info("Supabase: configurato (bucket=%s)", settings.supabase_bucket)
    else:
        logger.warning("Supabase: NON configurato (worker disabilitato, /extract/jobs/auth 503)")

    # SECURITY (FIX H1 audit 2025 — Fase 4 Redis): se l'API gira con
    # API_WORKERS > 1 ma RATE_LIMIT_STORAGE_BACKEND e' ancora "memory",
    # i limiti di rate vengono moltiplicati x N worker (es. "5/minute"
    # con 2 worker = 10/minute effettivi per utente). Logghiamo un
    # WARNING di startup cosi' l'operatore se ne accorge subito e
    # configura Redis (REDIS_URL + RATE_LIMIT_STORAGE_BACKEND=redis).
    _warn_if_multi_worker_memory_rate_limit()

    # Fase 4C-A2: readiness Redis per il rate-limit storage. Se Redis e'
    # configurato ma irraggiungibile, log ERROR chiaro al boot (mai crash:
    # l'app parte e i limiti possono degradare, ma l'operatore viene avvisato).
    _check_redis_readiness()

    # SECURITY (FIX M6 audit 2025): se la allowlist di /metrics contiene
    # solo loopback in produzione, gli scraper Prometheus remoti saranno
    # NEGATI con 403 senza nessun indizio evidente. Logghiamo un WARNING
    # di startup cosi' l'operatore se ne accorge subito e aggiunge l'IP
    # dello scraper in .env (METRICS_IP_ALLOWLIST=[..., "10.0.0.5"]).
    _warn_if_loopback_only_metrics_in_prod()

    # SECURITY (FIX M4 audit 2026): warning se CORS wildcard in produzione.
    _warn_if_wildcard_cors_in_prod()

    # Fase 4C-C1: billing "acceso" ma incompleto (secrets/price mancanti).
    _warn_if_billing_misconfigured()

    if settings.sentry_dsn:
        _init_sentry()

    # Avvia il worker
    await _worker.start()

    yield

    # Shutdown
    logger.info("SPESEMED API shutting down")
    await _worker.stop()


# =============================================================================
# App
# =============================================================================
app = FastAPI(
    title="SPESEMED API",
    description=(
        "OCR per ricevute mediche italiane via OpenRouter Vision.\n\n"
        "**Fase 3 features (current):**\n"
        "- Auth completa: signup, login, refresh token rotation, logout\n"
        "- Rate limiting: slowapi con limit per IP o user_id\n"
        "- Estrazione ibrida: sync per N<=3, async con job per N>3\n"
        "- Persistenza: Storage Supabase + tabelle `jobs` e `extractions`\n"
        "- Idempotency: cache (user_id, file_hash) per evitare doppi addebiti\n"
        "- Worker async: polling tabella jobs con retry+jitter\n"
        "- Monitoring: Sentry (opzionale) + Prometheus /metrics (default on)\n"
        "\n"
        "**Fase 4C features:**\n"
        "- Redis rate-limit storage opzionale (multi-worker) con fallback memory\n"
        "- /metrics Prometheus con HTTP metrics (cardinalita' bassa, no user data)\n"
        "- Stripe billing skeleton: plan, checkout, webhook (no-op mode senza secrets)"
    ),
    version=settings.api_version,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "health", "description": "Liveness e readiness check."},
        {"name": "auth", "description": "Signup, login, refresh, logout."},
        {"name": "extract", "description": "Estrazione OCR ibrida (sync/async)."},
        {"name": "jobs", "description": "Stato dei job asincroni."},
        {"name": "export", "description": "Export Excel/ZIP per il commercialista."},
        {"name": "summary", "description": "Riepilogo spese + usage utente (Profilo)."},
        {"name": "metrics", "description": "Prometheus exposition + admin endpoints."},
    ],
)

# CORS: accetta qualsiasi origine se '*' e' specificato o se lista vuota/dev
_cors_origins = settings.cors_origins if (settings.cors_origins and "*" not in settings.cors_origins) else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiter (slowapi): singleton + middleware per Security Headers.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


# =============================================================================
# Prometheus HTTP metrics middleware (Fase 4C)
# =============================================================================
@app.middleware("http")
async def _prometheus_http_metrics(request: Request, call_next):
    """Registra metriche HTTP RED (method + status_class, NO path/utente).

    Kill-switch: con PROMETHEUS_METRICS_ENABLED=False non si raccoglie nulla
    (oltre a non esporre /metrics), cosi' il monitoring spento non aggiunge
    overhead ne' sample orfani. L'ACL IP di /metrics resta invariata.

    Path /metrics escluso (lo scraper non deve inquinare i suoi stessi conteggi).
    """
    if not settings.prometheus_metrics_enabled:
        return await call_next(request)
    return await prometheus_http_metrics(request, call_next)


# =============================================================================
# 429 handler: ritorna ErrorResponse JSON (no HTML di default di slowapi)
# =============================================================================
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Converte RateLimitExceeded in ErrorResponse JSON.

    Default di slowapi ritorna HTML/text. Noi vogliamo JSON strutturato
    affine al ErrorResponse schema dell'API.
    """
    from fastapi.responses import JSONResponse
    logger.warning(
        "Rate limit exceeded: path=%s, client=%s, detail=%s",
        request.url.path, request.client.host if request.client else "?",
        exc.detail,
    )
    retry_seconds = None
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "Troppe richieste. Riprova piu' tardi.",
            "code": "rate_limit_exceeded",
            "retry_after_seconds": retry_seconds,
        },
    )
    response.headers["Retry-After"] = str(retry_seconds) if retry_seconds else "60"
    return response


# =============================================================================
# Root
# =============================================================================
@app.get("/", tags=["meta"])
def root() -> dict:
    """Root endpoint con info API."""
    return {
        "service": "SPESEMED API",
        "version": settings.api_version,
        "phase": "4C (Redis rate-limit storage, Prometheus /metrics, Stripe billing skeleton)",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/api/v1/health",
        "metrics": "/metrics (se PROMETHEUS_METRICS_ENABLED=True)",
        "billing": (
            "Stripe billing: GET /api/v1/billing/status (auth), GET /api/v1/billing/plan, "
            "POST /api/v1/billing/checkout, POST /api/v1/billing/webhook "
            "(no-op finche' STRIPE_SECRET_KEY non e' configurata)"
        ),
        "endpoints": {
            "auth": [
                "POST /api/v1/auth/signup", "POST /api/v1/auth/login",
                "POST /api/v1/auth/refresh", "POST /api/v1/auth/logout",
            ],
            "extract": "POST /api/v1/extract (auto-routing sync/async)",
            "jobs": "GET /api/v1/jobs/{id}",
            "export": "POST /api/v1/export (ZIP Excel + ricevute per commercialista)",
            "summary": "GET /api/v1/summary (riepilogo spese + usage per il Profilo)",
            "billing": [
                "GET /api/v1/billing/status",
                "GET /api/v1/billing/plan",
                "POST /api/v1/billing/checkout",
                "POST /api/v1/billing/webhook",
            ],
        },
    }


# =============================================================================
# Prometheus metrics endpoint (Fase 3.5)
# =============================================================================
@app.get(
    "/metrics",
    tags=["metrics"],
    summary="Prometheus exposition format (autorizzato via IP allowlist).",
    response_class=Response,
)
def prometheus_metrics(request: Request) -> Response:
    """Espone i counter e histogram Prometheus in formato text/plain.

    SECURITY (FIX M6 audit 2025):
      - NON richiede JWT (per design: se JWKS rotation rompe le JWT auth,
        Prometheus DEVE poter scrapare /metrics per alertare). Protezione
        demandata a:
          1. **Caddyfile/nginx.conf**: IP allowlist edge (primario).
          2. **`metrics_acl.check_metrics_authorization`**: IP allowlist
             in-process (defense-in-depth, funziona anche se il proxy
             e' assente o misconfigurato come nel finding [E3] smoke test).
          3. **`prometheus_metrics_enabled=False`**: kill-switch totale.
      - Espone solo metriche SPESEMED_* + process_* + python_gc_* (default
        prometheus_client). NON espone path label o user label (cardinalita').
      - `X-Forwarded-For` viene onorato SOLO se anche il peer TCP diretto
        (reverse proxy) e' whitelistato E `METRICS_TRUST_XFF=true`.
    """
    if not settings.prometheus_metrics_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="/metrics disabilitato (PROMETHEUS_METRICS_ENABLED=False).",
        )
    # IP-allowlist enforcement (defense-in-depth). Solleva 403 se non autorizzato.
    check_metrics_authorization(request)

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# =============================================================================
# Admin endpoint: reset JWKS cache (key rotation remediation)
# =============================================================================
@app.post(
    "/admin/auth/reset-jwks-cache",
    tags=["metrics"],
    summary="Reset manuale della cache JWKS Supabase.",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("5/minute")  # SECURITY (FIX H2 audit): anti brute-force X-Admin-Token
def admin_reset_jwks_cache(
    request: Request,  # richiesto da slowapi (key_func)
    response: Response,  # richiesto da slowapi (X-RateLimit headers)
    x_admin_token: str = Header(
        default="",
        alias="X-Admin-Token",
        description="Token statico configurato in ADMIN_TOKEN .env.",
    ),
) -> dict:
    """Reset della cache JWKS per forzare re-fetch al prossimo hit.

    USE CASE: Supabase annuncia una rotazione chiavi (`kid` nuovo non
    ancora nella cache locale) e l'app sta rifiutando tutti i JWT.

    AUTH: confronto diretto in `secrets.compare_digest` per evitare timing attack.
    Restituisce 403 se ADMIN_TOKEN non configurato o se il valore non matcha.
    """
    import secrets
    from .metrics import jwks_cache_resets_total

    if not settings.admin_token:
        # Endpoint disabilitato di default (fail-closed).
        logger.warning("Tentativo reset JWKS cache ma ADMIN_TOKEN vuoto (403).")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin endpoint disabilitato (ADMIN_TOKEN vuoto).",
        )
    if not secrets.compare_digest(x_admin_token, settings.admin_token):
        logger.warning(
            "Tentativo reset JWKS cache con X-Admin-Token invalido (403).",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Admin-Token invalido.",
        )
    reset_jwks_cache()
    jwks_cache_resets_total.inc()
    logger.info("JWKS cache resettata via admin endpoint.")
    return {
        "status": "ok",
        "action": "reset_jwks_cache",
        "next_request_will_refetch": True,
    }


# =============================================================================
# Mount routers
# =============================================================================
# NB: l'ordine non conta per FastAPI, ma logghiamolo per chiarezza.
app.include_router(health.router, prefix="/api/v1")
app.include_router(extract.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(summary.router, prefix="/api/v1")
app.include_router(waitlist.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")

# Mount Landing Page
from pathlib import Path
from fastapi.staticfiles import StaticFiles

# Landing page: cerca in due posizioni possibili
# 1. Dev locale: landing/ nella root del progetto (relativo a src/spesemed/api/main.py → 4 livelli su)
# 2. Docker prod: /app/landing (WORKDIR /app + COPY landing ./landing)
_landing_dir = Path(__file__).resolve().parent.parent.parent.parent / "landing"
if not _landing_dir.exists():
    _landing_dir = Path("/app/landing")
if _landing_dir.exists():
    app.mount("/landing", StaticFiles(directory=str(_landing_dir), html=True), name="landing")
