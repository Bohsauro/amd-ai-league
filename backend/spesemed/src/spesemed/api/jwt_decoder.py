"""SPESEMED API - JWT decoder with dual algorithm support.

Supports Supabase Auth in entrambi i suoi schemi di firma:
  - HS256 (legacy/symmetric): usa SUPABASE_JWT_SECRET dall'API dashboard.
  - ES256 (modern/asymmetric): EC P-256 via JWKS endpoint Supabase
    (https://<proj>.supabase.co/auth/v1/.well-known/jwks.json).

SECURITY DESIGN:
  - Algoritmo PINATO per token via peek dell'header (`jwt.get_unverified_header`).
    Niente allow-list dinamica: il token dichiara il proprio alg, e SOLO quello
    viene passato a `jwt.decode(algorithms=[alg])`. Difesa in profondita' contro
    algorithm confusion (es. token 'none' o HS256 iniettato in flusso ES256).
  - FAIL-CLOSED su config mancante: un token ES256 senza SUPABASE_URL/JWKS_URL
    configurati produce 503 (errore di config server-side), non 401 (errore
    client). L'app non deve MAI verificare in modo insicuro.
  - JWKS client caching: `PyJWKClient` con `cache_keys=True + cache_jwk_set=True`
    + lifespan 1h. Evita network round-trip per ogni richiesta autenticata.
  - Whitelist algoritmi ristretta: solo HS256 ed ES256 sono accettati.
    Algoritmi diversi (RS256, ES384, 'none', HS512...) sono rifiutati
    senza alcuna verifica: meglio un 401 trasparente che un buco di sicurezza.
  - `iss` claim validation CONDIZIONALE: quando `SUPABASE_URL` e' settato,
    verifichiamo `iss == "{supabase_url}/auth/v1"` per bloccare token cross-project.
    Senza `SUPABASE_URL`, il check Iss e' skippato (placeholder test/dev).
    NOTA SICUREZZA: skip iss SOLO per legacy HS256-only projects (senza
    SUPABASE_URL). Trade-off accettabile perche' il JWT_SECRET simmetrico
    e' gia' univoco per progetto Supabase, quindi cross-project token reuse
    e' gia' bloccato a livello di firma. Per setup moderni (ES256 + SUPABASE_URL),
    iss e' sempre validato.
  - `role` claim FILTER: rifiuta token con `role=service_role` (o altri ruoli
    admin) perche' bypassano RLS server-side. Solo `authenticated` + `anon`
    sono accettati come autenticazione utente.
  - `leeway=10s` per tollerare NTP drift realistici (~5-10s su container PAAS).

OBSERVABILITY (Fase 3.5):
  - Ogni fallimento incrementa `spesemed_jwt_failures_total{reason="..."}`.
    Le label reason sono enumerate (11 valori finiti) per evitare OOM Prometheus
    su label unbounded. `kid` e' loggato ma MAI esposto come label.
  - Latenza osservata in `spesemed_jwt_decode_duration_seconds` (Histogram).
  - Spike di `reason="jwks_lookup_failed"` indica Supabase JWKS key rotation
    non recepita dalla cache (remediation: `POST /admin/auth/reset-jwks-cache`).
"""
from __future__ import annotations

import logging
from typing import Any

import jwt
from fastapi import HTTPException, status

from .config import settings
from .metrics import jwt_decode_timer, record_failure

logger = logging.getLogger(__name__)

# Algoritmi accettati. Aggiungere qui solo dopo attenta review (es. RS256 se
# Supabase introducesse supporto nativo).
_ALLOWED_ALGORITHMS: frozenset[str] = frozenset({"HS256", "ES256"})

# Leeway per validazione `exp`/`nbf`/`iat`: 10s bilancia tolleranza NTP drift
# realistica senza aprire finestre di replay troppo ampie.
_EXP_LEEWAY_SECONDS: int = 10

# Cache dei client JWKS per URL. PyJWKClient ha cache_keys/cache_jwk_set
# interni, ma istanziarne uno per request e' comunque costo > 0.
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


def _get_jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Factory lazy + cached di `PyJWKClient` per `jwks_url`."""
    client = _jwks_clients.get(jwks_url)
    if client is None:
        client = jwt.PyJWKClient(
            jwks_url,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=3600,  # 1h: chiavi Supabase ruotano di rado
        )
        _jwks_clients[jwks_url] = client
    return client


def _effective_jwks_url() -> str:
    """URL JWKS effettivo: env var esplicita OPPURE auto-derivato da supabase_url.

    Supabase espone il JWKS al well-known path standard per OAuth2/OIDC.
    Se l'utente non ha impostato SUPABASE_JWKS_URL esplicitamente (es.
    proxy CDN personalizzato), lo deriviamo automaticamente.
    """
    if settings.supabase_jwks_url:
        return settings.supabase_jwks_url
    if settings.supabase_url:
        return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return ""


def _effective_issuer() -> str | None:
    """Issuer atteso per claim `iss`. None se `supabase_url` non configurato.

    Supabase firma `iss = <project_url>/auth/v1`. Se l'utente NON ha
    SUPABASE_URL (es. JWT_SECRET-only legacy project), skippiamo iss check
    (e' comunque verificabile via `aud=authenticated` + signature).
    """
    if not settings.supabase_url:
        return None
    return f"{settings.supabase_url.rstrip('/')}/auth/v1"


def decode_supabase_jwt(token: str) -> dict[str, Any]:
    """Decodifica + verifica un JWT Supabase, supportando HS256 e ES256.

    Algoritmo selezionato dinamicamente dall'header del token (PIN), poi
    verificato con la chiave corretta per quell'algoritmo (stringa simmetrica
    per HS256, EC public key via JWKS per ES256).

    Returns:
        Payload dict (con claim 'sub', 'exp', 'aud', 'iss', ...).

    Raises:
        HTTPException 401: JWT malformato / alg non supportato / scaduto /
            firma invalida / kid non trovato nel JWKS / iss claim mismatch.
        HTTPException 503: Config mancante per l'algoritmo ricevuto
            (HS256 senza secret, ES256 senza JWKS URL).
    """
    with jwt_decode_timer():
        return _decode_supabase_jwt_impl(token)


def _decode_supabase_jwt_impl(token: str) -> dict[str, Any]:
    """Logica interna di decode (separata da timer per testabilita' e pulizia)."""
    # 1. Peek header (NON verificato, serve solo per routing + key selection).
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        logger.warning("JWT header malformato: %s", type(e).__name__)
        record_failure("header_malformed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT non valido.",
        ) from e

    alg = header.get("alg", "")
    kid = header.get("kid")

    # 2. Whitelist check (rifiuta 'none', HS512, RS256, ES384, ...).
    if alg not in _ALLOWED_ALGORITHMS:
        logger.warning(
            "JWT con alg=%r rifiutato (whitelist=%s)",
            alg, sorted(_ALLOWED_ALGORITHMS),
        )
        record_failure("alg_unsupported")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT non valido.",
        )

    # 3. Risoluzione chiave per algoritmo (fail-closed su config mancante).
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            logger.error(
                "Token HS256 ricevuto ma SUPABASE_JWT_SECRET non configurato (503).",
            )
            record_failure("config_missing")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth HS256 non configurata: SUPABASE_JWT_SECRET mancante.",
            )
        key: Any = settings.supabase_jwt_secret
    else:  # ES256
        jwks_url = _effective_jwks_url()
        if not jwks_url:
            logger.error(
                "Token ES256 ricevuto ma SUPABASE_URL/SUPABASE_JWKS_URL non "
                "configurati (503).",
            )
            record_failure("config_missing")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth ES256 non configurata: SUPABASE_URL o "
                       "SUPABASE_JWKS_URL mancanti.",
            )
        try:
            signing_key = _get_jwks_client(jwks_url).get_signing_key_from_jwt(token)
            key = signing_key.key
        except Exception as e:
            logger.warning(
                "ES256 JWKS lookup fallito (kid=%s, url=%s): %s",
                kid, jwks_url, type(e).__name__,
            )
            record_failure("jwks_lookup_failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token JWT non valido.",
            ) from e

    # 4. Verifica con alg PINATO al valore header (defense-in-depth).
    expected_issuer = _effective_issuer()
    require_claims = ["exp", "sub"]
    decode_kwargs: dict[str, Any] = {
        "algorithms": [alg],  # PIN, non allow-list.
        "audience": "authenticated",
        "options": {"require": require_claims},
        "leeway": _EXP_LEEWAY_SECONDS,
    }
    if expected_issuer is not None:
        decode_kwargs["issuer"] = expected_issuer
        decode_kwargs["options"]["require"].append("iss")

    try:
        payload = jwt.decode(token, key, **decode_kwargs)
    except jwt.ExpiredSignatureError as e:
        record_failure("expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT scaduto.",
        ) from e
    except jwt.InvalidSignatureError as e:
        # Distingui HS256 (secret) da ES256 (JWKS) per label counter.
        if alg == "HS256":
            record_failure("hs256_invalid_signature")
        else:
            record_failure("jwks_invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT non valido.",
        ) from e
    except jwt.InvalidIssuerError as e:
        record_failure("issuer_mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT non valido.",
        ) from e
    except jwt.MissingRequiredClaimError as e:
        record_failure("missing_required_claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT non valido.",
        ) from e
    except jwt.PyJWTError as e:
        # Catch-all per altri errori PyJWT (es. InvalidAudienceError, ImmatureSignatureError).
        record_failure("general_decode_error")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT non valido.",
        ) from e

    # Post-decode filter sul `role`: blocca service_role e altri ruoli admin
    # che bypassano RLS Supabase server-side. SECURITY (FIX M5 audit pen-test):
    # accettiamo SOLO "authenticated". "anon" e' la anon-key pubblica di
    # Supabase che chiunque puo' ottenere; accettarla come autenticazione
    # utente aprirebbe un'exploit classico (anon con X-Title spoofing =
    # accesso al backend con credenziali pubbliche).
    role = payload.get("role")
    if role != "authenticated":
        logger.warning(
            "JWT con role=%r rifiutato (solo 'authenticated' ammesso)",
            role,
        )
        record_failure("role_unauthorized")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT non valido.",
        )

    return payload


def reset_jwks_cache() -> None:
    """Reset della cache JWKS (per test, o rotazione chiavi Supabase forzaata).

    Chiamare questo se Supabase annuncia una rotazione chiavi che la cache
    locale non ha ancora recepito (es. kid 'kid-new' mai visto).
    Esposto anche via endpoint HTTP POST /admin/auth/reset-jwks-cache
    per le Ops in produzione (vedi api.main.admin_router).
    """
    _jwks_clients.clear()
