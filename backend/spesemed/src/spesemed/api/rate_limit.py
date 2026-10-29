"""SPESEMED API - Rate limiting con slowapi (Fase 3).

Configurazione centralizzata:
    - Limiter singleton importabile da `api.rate_limit.limiter`
    - Key function: IP remoto per /auth/*, user_id (o IP) per /extract
    - Storage: in-memory (default). Per multi-worker futuro: Redis.

Utilizzo nei router:
    from ..rate_limit import limiter

    @router.post(\"/extract\")
    @limiter.limit(\"10/minute\")  # <-- order: limiter DOPO router.post ma PRIMA della func
    async def extract(request: Request, ...): ...

NB: slowapi richiede `request: Request` come parametro esplicito
    affinche' la key_func possa usare request.client.host.

Il 429 handler custom (in main.py) converte RateLimitExceeded in ErrorResponse
JSON (no HTML). Vedi api.main._register_rate_limit_handler.
"""
from __future__ import annotations

import logging
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings

logger = logging.getLogger(__name__)


def _build_storage_uri() -> str:
    """Risolve l'URI dello storage per slowapi da `rate_limit_storage_backend`.

    Valori supportati:
        - ``"memory"`` (default)  -> ``"memory://"`` (in-process, single-worker OK).
        - ``"redis://host:port"`` -> URI diretta (multi-worker, produzione).
        - ``"redis"``             -> usa `REDIS_URL` env var come URI.

    Fallback: se la configurazione e' ambigua o mancante, logga WARNING
    e ritorna ``"memory://"``. L'app NON crasha al boot per un Redis down:
    il backend tenta la connessione al primo hit di rate-limit.

    Returns:
        URI di storage nel formato accettato da `limits` (``"memory://"``
        oppure ``"redis://..."``).
    """
    backend = settings.rate_limit_storage_backend.strip()

    # Memory (default, nessuna dipendenza esterna).
    if not backend or backend == "memory":
        logger.info("Rate limiter storage: memory (single-worker, dev)")
        return "memory://"

    # Redis URI diretta (es. "redis://redis:6379/0").
    if backend.startswith("redis://") or backend.startswith("rediss://"):
        logger.info("Rate limiter storage: Redis URI diretta %s", _redact_redis_uri(backend))
        return backend

    # Keyword "redis": risolvi da REDIS_URL.
    if backend == "redis":
        redis_url = settings.redis_url.strip()
        if redis_url:
            logger.info("Rate limiter storage: Redis via REDIS_URL %s", _redact_redis_uri(redis_url))
            return redis_url
        logger.warning(
            "RATE_LIMIT_STORAGE_BACKEND=redis ma REDIS_URL non configurata. "
            "Fallback a memory. I limiti saranno PER-WORKER (NON condivisi)."
        )
        return "memory://"

    # Valore non riconosciuto: fallback safe.
    logger.warning(
        "RATE_LIMIT_STORAGE_BACKEND=%r non riconosciuto. "
        "Attesi: 'memory', 'redis', o 'redis://host:port'. Fallback a memory.",
        backend,
    )
    return "memory://"


def _redact_redis_uri(uri: str) -> str:
    """Redatta password/username da URI Redis per log sicuri.

    Esempio: ``redis://:password@host:6379/0`` -> ``redis://:***@host:6379/0``.
    """
    # Pattern: redis://[user]:[pass]@host:port/db
    if "@" not in uri:
        return uri
    try:
        scheme, rest = uri.split("://", 1)
        if "@" not in rest:
            return uri
        creds, hostpart = rest.rsplit("@", 1)
        if ":" in creds:
            user, _password = creds.split(":", 1)
            return f"{scheme}://{user}:***@{hostpart}"
        # Solo username, nessuna password: non redact.
        return uri
    except (ValueError, IndexError):
        return uri


def _key_by_user_or_ip(request: Request) -> str:
    """Key function ibrida per rate-limit: user_id verificato > IP.

    SECURITY (CRIT-1 fix Fase 3):
        In produzione (SUPABASE_JWT_SECRET configurato), il sub del JWT viene
        ESTRATTO SOLO DOPO verifica firma HMAC. Senza verifica, un attaccante
        potrebbe inviare un JWT con un `sub` arbitrario per "rubare" il bucket
        rate-limit di un altro utente (soprattutto dietro NAT aziendale).

        In development (senza JWT secret), accettiamo il sub non verificato
        per consentire mock/test senza configurare Supabase. Trade-off
        documentato: il dev mode NON va esposto a internet.

        X-User-Id fallback SOLO in development: in produzione viene IGNORATO
        (per evitare che un attaccante possa scegliere un bucket arbitrario).
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        # AUTH CONFIGURATA (HS256 secret OPPURE SUPABASE_URL per ES256/JWKS):
        # verifica firma obbligatoria prima di usare il sub come rate-limit key.
        if settings.supabase_jwt_secret or settings.supabase_url:
            try:
                from .jwt_decoder import decode_supabase_jwt
                payload = decode_supabase_jwt(token)
                sub = payload.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                # JWT invalido/fallito verifica (HTTPException o altro):
                # fallback su IP (SICURO). NB: evita escalation di privilegi
                # via token malformati.
                pass
        # DEVELOPMENT no-config: best-effort senza verifica (mock puro).
        elif settings.api_env == "development":
            try:
                import jwt as _jwt  # noqa: WPS433 - lazy import
                payload = _jwt.decode(token, options={"verify_signature": False})
                sub = payload.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                pass
    # X-User-Id mock header SOLO in development (non esposto in produzione).
    if settings.api_env == "development":
        x_user = request.headers.get("x-user-id", "").strip()
        if x_user:
            return f"user:{x_user}"
    # IP come fallback finale (sempre sicuro in produzione).
    return f"ip:{get_remote_address(request)}"


# Limiter singleton con storage configurabile (memory o Redis).
# Il backend Redis e' richiesto per multi-worker (API_WORKERS > 1)
# perche' lo storage in-memory e' PER-WORKER e non condiviso.
_storage_uri = _build_storage_uri()
limiter = Limiter(
    key_func=_key_by_user_or_ip,
    headers_enabled=True,  # aggiunge X-RateLimit-* headers alle response
    strategy="fixed-window",  # piu' semplice del moving-window (no warmup)
    storage_uri=_storage_uri,
)

logger.debug(
    "Rate limiter istanziato (key=user_or_ip, strategy=fixed-window, storage=%s)",
    _storage_uri.split("://")[0] if "://" in _storage_uri else _storage_uri,
)
