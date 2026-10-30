"""SPESEMED API - Dependencies FastAPI.

Auth ibrida (Fase 2):
    1. Authorization: Bearer <jwt>   -> valida con SUPABASE_JWT_SECRET (locale, no network)
    2. X-User-Id: <id>               -> mock fallback per dev/test (non richiede Supabase)
    3. (nessun header)               -> settings.mock_user_id_default ("anonymous")

Vantaggi della validazione JWT locale (vs supabase.auth.get_user remoto):
    - Non blocca l'event loop di FastAPI (supabase-py e' sync)
    - Latenza ~1ms vs ~100-200ms
    - Trade-off: non vede la revocation list (token resta valido fino a exp)

Per produzione: configurare SUPABASE_JWT_SECRET in .env.
"""
from __future__ import annotations

import logging
import re

import jwt
from fastapi import Header, HTTPException, status

from .config import settings
from .jwt_decoder import decode_supabase_jwt

logger = logging.getLogger(__name__)

# SECURITY (FIX C2 — anti path-traversal): valida UUID v1-5 RFC 4122.
# Il sub-claim dei JWT Supabase Auth e' SEMPRE un UUID, quindi la regex
# non rompe nessun happy-path reale. Blocca invece:
#   - Path traversal (/, .., \\)
#   - Injection di caratteri non-hex / lunghezze patologiche
#   - ASCII control chars (\n, \r, \t, \0) — anche se la validazione Pydantic
#     li cattura, sono bloccati qui in difesa-in-profondita'.
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    re.IGNORECASE,
)


async def get_current_user(
    authorization: str = Header(
        default="",
        alias="Authorization",
        description="Bearer JWT di Supabase Auth (validato localmente).",
    ),
    x_user_id: str = Header(
        default="",
        alias="X-User-Id",
        description="(MOCK fallback) Identità utente per dev/test.",
    ),
) -> str:
    """Estrae l'identità utente. Priorita': JWT > X-User-Id > anonymous.

    Returns:
        user_id: stringa identificativa utente (dal JWT 'sub' claim, oppure header, oppure mock).

    Raises:
        HTTPException 401: se il JWT e' presente ma non valido.
        HTTPException 400: se X-User-Id contiene caratteri non validi.
    """
    # 1. JWT via Authorization header
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token vuoto.",
            )
        # Validazione JWT locale (richiede SUPABASE_JWT_SECRET)
        if not settings.supabase_jwt_secret:
            # FAIL-CLOSED (FIX C3): senza SUPABASE_JWT_SECRET non possiamo
            # VERIFICARE il Bearer token. Anche in dev richiediamo opt-in
            # esplicito ALLOW_DEV_MOCK_AUTH=true. Mai True in produzione
            # (identity-spoofing = data breach GDPR categoria speciale).
            if not settings.allow_dev_mock_auth:
                logger.error(
                    "Bearer JWT presente ma SUPABASE_JWT_SECRET vuoto + "
                    "ALLOW_DEV_MOCK_AUTH=false. Auth non disponibile (503)."
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Auth non configurata: SUPABASE_JWT_SECRET mancante.",
                )
            # Opt-in esplicito dev/test: token opaco come user_id (no verifica).
            logger.warning(
                "DEV-MOCK auth attivo (ALLOW_DEV_MOCK_AUTH=true): Bearer "
                "token trattato come user_id opaco senza verifica firma."
            )
            return token
        # decode_supabase_jwt fa routing HS256/ES256 + verifica firma.
        # Già solleva HTTPException 401/503 tipizzate; qui estraiamo solo 'sub'.
        try:
            payload = decode_supabase_jwt(token)
        except jwt.PyJWTError as e:
            # Catch di sicurezza: l'helper dovrebbe aver gia' tradotto in HTTPException,
            # ma se per qualunque motivo escapasse una PyJWTError, la wrappiamo.
            logger.warning("decode_supabase_jwt leaked PyJWTError: %s", type(e).__name__)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token JWT non valido.",
            ) from e
        user_id = payload.get("sub", "")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="JWT senza 'sub' claim.",
            )
        return user_id

    # 2. Mock X-User-Id (dev/test) — solo se opt-in esplicito.
    if x_user_id and x_user_id.strip():
        # SECURITY (FIX C3): X-User-Id mock richiede ALLOW_DEV_MOCK_AUTH=true.
        # Anche con opt-in, il valore deve essere UUID RFC 4122 (FIX C2).
        if not settings.allow_dev_mock_auth:
            logger.error(
                "X-User-Id presente ma ALLOW_DEV_MOCK_AUTH=false. "
                "Header mock non accettato in produzione (503)."
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="X-User-Id non accettato: ALLOW_DEV_MOCK_AUTH=false.",
            )
        cleaned = x_user_id.strip()
        if not _UUID_PATTERN.match(cleaned):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "X-User-Id non e' un UUID valido (atteso formato "
                    "8-4-4-4-12 hex, es. 00000000-0000-4000-8000-000000000001)."
                ),
            )
        return cleaned

    # 3. Fallback anonimo (solo per dev/test con opt-in esplicito ALLOW_DEV_MOCK_AUTH=true)
    if not settings.allow_dev_mock_auth:
        logger.warning(
            "Richiesta senza header di autenticazione ma ALLOW_DEV_MOCK_AUTH=false (401)."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticazione richiesta. Inviare header 'Authorization: Bearer <jwt>'.",
        )

    return settings.mock_user_id_default
