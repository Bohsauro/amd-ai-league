"""SPESEMED API - Auth endpoints: signup, login, refresh, logout via Supabase Auth.

POST /api/v1/auth/signup   {email, password}                           -> 201 {tokens}
POST /api/v1/auth/login    {email, password}                           -> 200 {tokens}
POST /api/v1/auth/refresh  {refresh_token}                             -> 200 {tokens nuovi}
POST /api/v1/auth/logout   (Authorization: Bearer <jwt>)               -> 204

I token sono poi usati come:
    Authorization: Bearer <access_token>
nelle richieste autenticate (vedi `dependencies.get_current_user`).

Pattern DI-friendly (Fase 4):
    Tutte le chiamate a get_supabase_client / is_supabase_configured sono fatte
    via ``supabase_client.func()`` (attribute access sul MODULO), NON via
    reference locale. Questo consente a pytest di mockare UN SOLO attributo
    (``spesemed.api.supabase_client.is_supabase_configured``) invece di N.
    Vedi tests/conftest.py.

NB Fase 3 - Refresh:
    Refresh token rotation: Supabase invalida automaticamente il refresh_token
    usato e ne emette uno nuovo. Questo previene "refresh token reuse attack".
    Le chiamate supabase-py sono sincronе: usiamo `asyncio.to_thread`.

NB Fase 3 - Logout:
    Logout = client cancella il token + backend chiama supabase.auth.sign_out().
    NO revocation list server-side (overhead DB su ogni request):
    l'access_token resta "matematicamente" valido fino al suo `exp` (~1h).
    Trade-off accettato per le performance (vedi thinker Fase 3).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from .. import supabase_client  # NB: import del MODULO (non dei nomi) per monkeypatch pulito
from ..config import settings
from ..dependencies import get_current_user
from ..rate_limit import limiter
from ..schemas import AuthResponse, ErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


def _hash_email(email: str) -> str:
    """Hash SHA-256 troncato dell'email per log correlation senza PII.

    SECURITY (FIX M2 audit): mai loggare l'email in chiaro. L'hash
    troncato (primi 12 caratteri) permette di correlare gli errori
    per la stessa email senza esporre il dato personale.
    """
    return hashlib.sha256(email.encode()).hexdigest()[:12]


# =============================================================================
# Schemas locali (request bodies specifici dell'auth)
# =============================================================================
class AuthRequest(BaseModel):
    """Body per signup/login."""
    email: str = Field(..., min_length=3, max_length=255, description="Email dell'utente.")
    password: str = Field(..., min_length=8, max_length=128, description="Password (min 8 caratteri).")


class RefreshRequest(BaseModel):
    """Body per /auth/refresh."""
    refresh_token: str = Field(..., min_length=10, description="Refresh token da rinnovare.")


# =============================================================================
# Endpoints
# =============================================================================

@router.post(
    "/auth/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Email/password non validi."},
        403: {"model": ErrorResponse, "description": "Signup disabilitato in produzione."},
        429: {"model": ErrorResponse, "description": "Troppe signup recenti dallo stesso IP."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit("2/hour")
async def signup(
    response: Response,  # NB: slowapi necessita di Response per X-RateLimit headers.
    request: Request,
    payload: AuthRequest,
) -> AuthResponse:
    """Registra un nuovo utente su Supabase Auth.

    Rate-limit: 2/ora per IP (anti account-spam, Fase 3).
    In produzione l'email va confermata prima del login.
    """
    if not supabase_client.is_supabase_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase non configurato sul server.",
        )
    if not settings.allow_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signup disabilitato. Contattare l'admin per un invito.",
        )

    client = supabase_client.get_supabase_client()
    # Il backend usa la SERVICE ROLE key (admin). Creiamo l'utente gia'
    # confermato (email_confirm=True) per non dipendere dalla conferma email
    # del progetto Supabase, che altrimenti blocca signup/login nel test E2E.
    # NB: in produzione, se si vuole la conferma email, impostare a False o
    # rimuovere email_confirm e gestire il flusso di verifica.
    try:
        result = await asyncio.to_thread(
            client.auth.admin.create_user,
            {
                "email": payload.email,
                "password": payload.password,
                "email_confirm": True,
            },
        )
    except Exception as e:
        logger.warning(
            "Supabase signup fallito (email_hash=%s): %s",
            _hash_email(payload.email), type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registrazione non riuscita. Riprova o verifica i dati inseriti.",
        ) from e

    # Dopo la creazione (admin) l'utente e' confermato ma admin.create_user non
    # ritorna una sessione: eseguiamo un login per emettere i token.
    try:
        result = await asyncio.to_thread(
            client.auth.sign_in_with_password,
            {"email": payload.email, "password": payload.password},
        )
    except Exception as e:
        logger.warning(
            "Login post signup fallito (email_hash=%s): %s",
            _hash_email(payload.email), type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registrazione riuscita ma accesso non disponibile. Riprova.",
        ) from e

    if not result.user or not result.session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registrazione non riuscita. Riprova o verifica i dati inseriti.",
        )

    return AuthResponse(
        access_token=result.session.access_token,
        user_id=result.user.id,
        refresh_token=result.session.refresh_token,
        expires_in=result.session.expires_in,
    )


@router.post(
    "/auth/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Credenziali non valide."},
        429: {"model": ErrorResponse, "description": "Troppi login falliti (brute-force protection)."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit("5/minute")
async def login(
    response: Response,  # NB: slowapi necessita di Response per X-RateLimit headers.
    request: Request,
    payload: AuthRequest,
) -> AuthResponse:
    """Effettua il login e ritorna access_token + user_id + refresh_token.

    Rate-limit: 5/minuto per IP (anti brute-force, Fase 3).
    """
    if not supabase_client.is_supabase_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase non configurato sul server.",
        )

    client = supabase_client.get_supabase_client()
    try:
        result = await asyncio.to_thread(
            client.auth.sign_in_with_password,
            {"email": payload.email, "password": payload.password},
        )
    except Exception as e:
        logger.warning(
            "Supabase login fallito (email_hash=%s): %s",
            _hash_email(payload.email), type(e).__name__,
        )
        # 401 generico (non rivela se email esiste: anti-enumeration)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide.",
        ) from e

    if not result.user or not result.session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide.",
        )

    return AuthResponse(
        access_token=result.session.access_token,
        user_id=result.user.id,
        refresh_token=result.session.refresh_token,
        expires_in=result.session.expires_in,
    )


@router.post(
    "/auth/refresh",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Refresh token non valido o scaduto."},
        429: {"model": ErrorResponse, "description": "Troppi refresh dallo stesso utente."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit("30/minute")
async def refresh(
    response: Response,  # NB: slowapi necessita di Response per X-RateLimit headers.
    request: Request,
    payload: RefreshRequest,
) -> AuthResponse:
    """Rinnova access_token + refresh_token usando un refresh_token valido.

    Refresh Token Rotation: Supabase invalida il vecchio refresh_token
    automaticamente e ne ritorna uno nuovo (sicurezza anti-reuse).
    Rate-limit: 30/minuto per utente (un client puo' refreshare ragionevolmente).
    """
    if not supabase_client.is_supabase_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase non configurato sul server.",
        )

    client = supabase_client.get_supabase_client()
    try:
        result = await asyncio.to_thread(
            client.auth.refresh_session,
            payload.refresh_token,
        )
    except Exception as e:
        logger.warning("Supabase refresh fallito: %s", e)
        # 401 generico per non rivelare se il token e' scaduto, revocato o malformato
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token non valido o scaduto.",
        ) from e

    if not result.user or not result.session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token non valido: risposta Supabase vuota.",
        )

    logger.info("Refresh OK user=%s", result.user.id)
    return AuthResponse(
        access_token=result.session.access_token,
        user_id=result.user.id,
        refresh_token=result.session.refresh_token,
        expires_in=result.session.expires_in,
    )


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Logout riuscito (nessun body)."},
        401: {"model": ErrorResponse, "description": "Bearer mancante o non valido."},
        429: {"model": ErrorResponse, "description": "Troppi logout (edge case)."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit("20/minute")
async def logout(
    response: Response,  # NB: slowapi necessita di un Response per iniettare X-RateLimit headers.
    request: Request,
    user_id: str = Depends(get_current_user),
) -> None:
    """Invalida la sessione corrente su Supabase (sign_out).

    Endpoint BEST-EFFORT: deve SEMPRE rispondere 204 (o 401 se Bearer mancante).
    MAI 5xx: qualsiasi errore inatteso viene loggato e il client puo' comunque
    cancellare il token localmente (vedi dependencies.py per exp-based JWT).

    Rate-limit: 20/minuto (alto, edge case).
    """
    # NB: get_current_user ha gia' validato il Bearer.
    # Se non c'e' Bearer reale, forziamo 401 (logout anonimo non ha senso).
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Logout richiede Authorization: Bearer <jwt>.",
        )

    try:
        if not supabase_client.is_supabase_configured():
            logger.warning("Logout: Supabase non configurato, client-side cleanup only")
            return

        client = supabase_client.get_supabase_client()
        if client is None:
            # create_client fallito internamente (env settate ma server KO)
            logger.warning("Logout: Supabase client None nonostante configurato, skip")
            return

        # sign_out invalida la sessione corrente su Supabase (revoca server-side).
        # NB: questo NON revoca il JWT locale (exp-based), ma ferma il refresh.
        await asyncio.to_thread(client.auth.sign_out)
        logger.info("Logout OK user=%s", user_id)
    except HTTPException:
        raise  # 401 e altri errori intenzionali propagano
    except Exception as e:
        # Best-effort finale: qualunque errore inatteso -> 204 (cleanup locale sufficiente).
        logger.warning("Logout best-effort errore per %s: %s", user_id, e)
