"""SPESEMED API - Billing endpoints (Fase 4C Stripe skeleton).

GET  /api/v1/billing/status    -> stato piano utente (200, auth richiesto)
POST /api/v1/billing/checkout  -> Stripe Checkout Session (200, auth richiesto)
POST /api/v1/billing/webhook   -> riceve eventi Stripe (200, firma verificata)

No-op mode:
    Se STRIPE_SECRET_KEY e' vuota / libreria mancante => /checkout risponde 503
    con messaggio chiaro. Se STRIPE_WEBHOOK_SECRET vuota => /webhook 503.
    Questo permette di deployare il codice PRIMA che Stripe venga configurato,
    senza rompere il resto dell'API (test offline con mock).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from .. import billing, billing_client
from ..config import settings
from ..dependencies import get_current_user
from ..rate_limit import limiter
from ..schemas import BillingStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])


class CheckoutRequest(BaseModel):
    """Body opzionale per POST /billing/checkout.

    L'email serve solo come ``customer_email`` per la ricevuta Stripe: prezzo
    e URL di redirect restano SEMPRE lato server.
    """
    email: str = Field(default="", description="Email per la ricevuta Stripe (opzionale).")


class CheckoutResponse(BaseModel):
    """Response con l'URL di checkout per il redirect del client."""
    checkout_url: str = Field(..., description="URL Stripe Checkout (redirect del browser).")
    session_id: str = Field(..., description="ID della sessione checkout (per polling webhook).")
    mode: str = Field(default="test", description="Modalita' Stripe: test | live.")
    amount_total: int | None = Field(default=None, description="Importo totale in centesimi (se noto).")
    currency: str = Field(default="eur", description="Valuta di fatturazione.")


class WebhookResponse(BaseModel):
    """Ack per /billing/webhook (Stripe si aspetta 2xx)."""
    received: bool = Field(default=True)
    action: str | None = Field(
        default=None,
        description="Azione eseguita: subscription_created | subscription_updated | "
        "subscription_canceled | invoice_paid | ignored.",
    )
    event_type: str | None = Field(
        default=None,
        description="Tipo di evento Stripe processato (per il logging client).",
    )
    replayed: bool = Field(
        default=False,
        description="True se l'evento era gia' stato processato (idempotenza).",
    )


# =============================================================================
# Status (auth): contratto letto dal Profilo del client
# =============================================================================
@router.get(
    "/billing/status",
    response_model=BillingStatusResponse,
    summary="Stato piano dell'utente autenticato (free/pro, scadenza, usage).",
    responses={
        200: {"model": BillingStatusResponse, "description": "Stato piano (anche con billing disabilitato)."},
        401: {"description": "Non autenticato."},
    },
)
@limiter.limit("30/minute")
async def billing_status(
    request: Request,
    response: Response,  # richiesto da slowapi (X-RateLimit headers)
    user_id: str = Depends(get_current_user),
) -> dict:
    """Ritorna lo stato del piano per ``user_id`` letto dal token.

    Con ``BILLING_ENABLED=false`` risponde 200 con ``billing_enabled=false`` e
    piano free: il client NON deve ricevere 5xx ne' 503. Con billing attivo
    legge la riga ``entitlements`` (fallback ``subscriptions``) e degrada a
    free in caso di DB non disponibile.
    """
    return billing.get_user_billing_status(user_id)


# =============================================================================
# Checkout (richiede utente autenticato)
# =============================================================================
@router.post(
    "/billing/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": CheckoutResponse, "description": "Checkout session creata."},
        401: {"description": "Non autenticato."},
        503: {"description": "Billing non configurato (kill switch/secret/price)."},
    },
)
@limiter.limit("10/minute")
async def billing_checkout(
    request: Request,
    response: Response,  # richiesto da slowapi (X-RateLimit headers)
    body: CheckoutRequest | None = None,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Crea una Stripe Checkout Session (modalita' subscription).

    Il client deve redirigere il browser su ``checkout_url``. Il result viene
    notificato via webhook (da configurare lato Stripe).

    Sicurezza: prezzo e URL di redirect arrivano SOLO dalla config server
    (``STRIPE_PRICE_ID`` / ``STRIPE_SUCCESS_URL`` / ``STRIPE_CANCEL_URL``).
    Il client non puo' scegliere il prezzo ne' controllare il redirect.
    """
    if not billing_client.is_billing_configured():
        logger.warning("Billing checkout rifiutato: billing non configurato (user=%s)", user_id[:12])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing non configurato (Stripe). Contatta l'amministratore.",
        )
    email = (body.email if body else "").strip()
    try:
        result = billing_client.create_checkout_session(user_id=user_id, email=email)
        result["mode"] = getattr(settings, "stripe_mode", "test")
        result["currency"] = getattr(settings, "stripe_currency", "eur")
    except billing_client.BillingNotConfiguredError as e:
        logger.warning("Billing checkout rifiutato: %s (user=%s)", e, user_id[:12])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing non configurato (Stripe). Contatta l'amministratore.",
        ) from e
    except Exception as e:  # include stripe.error.StripeError
        logger.error("Checkout Stripe fallito (user=%s): %s", user_id[:12], e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Impossibile creare la sessione di pagamento.",
        ) from e
    return result


# =============================================================================
# Webhook (NO auth: la firma Stripe E' l'autenticazione)
# =============================================================================
@router.post(
    "/billing/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": WebhookResponse, "description": "Evento ricevuto e processato."},
        400: {"description": "Firma Stripe non valida."},
        503: {"description": "Webhook non configurato (STRIPE_WEBHOOK_SECRET mancante)."},
    },
)
@limiter.limit("120/minute")
async def billing_webhook(
    request: Request,
    response: Response,  # richiesto da slowapi (X-RateLimit headers)
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
) -> dict:
    """Riceve eventi Stripe (checkout.session.completed, ...).

    La firma viene verificata con ``stripe.Webhook.construct_event`` usando
    STRIPE_WEBHOOK_SECRET: nessun JWT/Bearer richiesto (by design).

    IMPORTANTE per Stripe Dashboard: configure endpoint
    ``https://<api>/api/v1/billing/webhook`` con almeno gli eventi
    ``checkout.session.completed`` e ``customer.subscription.deleted``.
    """
    payload = await request.body()
    try:
        event = billing.verify_webhook_signature(payload=payload, sig_header=stripe_signature)
    except billing.StripeNotConfiguredError as e:
        logger.warning("Webhook non configurato: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook non configurato (STRIPE_WEBHOOK_SECRET mancante).",
        ) from e
    except Exception as e:
        logger.warning("Webhook Stripe: firma non valida (400). %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook sign check failed.",
        ) from e

    result = await asyncio.to_thread(billing.process_webhook_event, event)
    logger.info(
        "Webhook Stripe processato: type=%s action=%s replayed=%s",
        result.get("event_type"),
        result.get("action"),
        result.get("replayed", False),
    )
    return {"received": True, **result}
