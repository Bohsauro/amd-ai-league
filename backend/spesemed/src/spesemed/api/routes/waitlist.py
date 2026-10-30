"""SPESEMED API - POST /api/v1/waitlist (Iscrizione Lista d'Attesa).

Endpoint pubblico per registrare nuovi utenti interessati all'accesso
prioritario dalla Landing Page.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from .. import supabase_client
from ..config import settings
from ..rate_limit import limiter
from ..schemas import ErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["waitlist"])


class WaitlistRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Nome completo dell'utente")
    email: EmailStr = Field(..., description="Email dell'utente")
    role: str = Field(..., description="Ruolo: privato, commercialista, assicurazione")


class WaitlistResponse(BaseModel):
    status: str = "ok"
    message: str = "Iscrizione alla lista d'attesa completata con successo."


@router.post(
    "/waitlist",
    status_code=status.HTTP_201_CREATED,
    response_model=WaitlistResponse,
    responses={
        201: {"model": WaitlistResponse, "description": "Iscritto con successo."},
        400: {"model": ErrorResponse, "description": "Dati non validi."},
        429: {"model": ErrorResponse, "description": "Troppe richieste."},
    },
)
@limiter.limit("5/minute")
async def register_waitlist(
    request: Request,
    response: Response,
    body: WaitlistRequest = Body(...),
):
    """Registra una nuova email nella lista d'attesa prioritaria per SPESEMED."""
    # SECURITY (FIX M2 audit): mai loggare email in chiaro (PII / GDPR).
    email_hash = hashlib.sha256(body.email.encode()).hexdigest()[:12]
    logger.info("Nuova iscrizione waitlist: role=%s email_hash=%s", body.role, email_hash)

    # Persistenza opzionale su Supabase se configurato
    client = supabase_client.get_supabase_client()
    if client:
        try:
            client.table("waitlist").insert({
                "name": body.name,
                "email": body.email,
                "role": body.role,
            }).execute()
        except Exception as e:
            logger.warning("Impossibile salvare waitlist in DB: %s (inviata comunque mail/log)", e)

    return WaitlistResponse(
        status="ok",
        message=f"Grazie {body.name}! Ti sei iscritto con successo alla lista d'attesa prioritaria.",
    )
