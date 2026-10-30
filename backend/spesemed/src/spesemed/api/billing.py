"""SPESEMED API - Integrazione Stripe billing (Fase 4C).

Skeleton operativo con **no-op mode** senza secrets:

    - Se ``STRIPE_SECRET_KEY`` e' vuota (o la libreria `stripe` non e'
      installata/impoortabile) => billing DISABILITATO: le route ritornano
      503 e nessuna chiamata di rete parte.
    - Nessun secret reale nel codice: tutto arriva da env/.env del deploy.

Endpoints esposti (vedi routes/billing.py):
    GET  /api/v1/billing/plan      - info pubbliche del piano (NESSUN secret).
    POST /api/v1/billing/checkout  - crea una Stripe Checkout Session (auth).
    POST /api/v1/billing/webhook   - riceve eventi Stripe (firma verificata).

Design:
    - Import LAZY di `stripe` (primo uso): il modulo e' importabile anche
      senza la libreria installata (no-op mode che risponde 503 con un
      messaggio chiaro per l'operatore).
    - Webhook: verifica firma con ``stripe.Webhook.construct_event``.
    - Persistenza: alla ``checkout.session.completed`` la subscription viene
      scritta best-effort nella tabella `subscriptions` (vedi
      migrations/004_billing.sql). Se Supabase/DB non e'
      disponibile, l'evento viene comunque ack-ato con un log (idempotenza
      garantita dal fare retry piu' tardi).

Cosa serve per ATTIVARE il billing (niente di questo e' nel workspace):
    1. Account Stripe + API keys (publishable + secret) in modalita' test.
    2. UN Product + Price ricorrente (es. 9.99 EUR/mese) -> STRIPE_PRICE_ID.
    3. Webhook endpoint https://<api>/api/v1/billing/webhook con eventi
       abilitati: checkout.session.completed, customer.subscription.deleted.
    4. La Secret con "whsec_..." -> STRIPE_WEBHOOK_SECRET.
    5. Redirect URLs raggiungibili -> STRIPE_SUCCESS_URL / STRIPE_CANCEL_URL.
    6. (Opzionale) migration 004 applicata su Supabase.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .config import settings
from . import supabase_client

logger = logging.getLogger(__name__)


# =============================================================================
# Catalogo piani (meta pubblico, NESSUNA informazione sensibile)
# =============================================================================
# In uno skeleton basta un piano; l'estensione multi-piano passa dall'aggiunta
# di altri dizionari + env STRIPE_PRICE_ID_* dedicati.
PLAN_CATALOG = {
    "pro": {
        "name": "SPESEMED PRO",
        "price_id": "",  # valorizzato runtime da settings.stripe_price_id
        "currency": "eur",
        "period": "month",
        "features": [
            "Estrazioni illimitate",
            "Export Excel/ZIP per il commercialista",
            "Supporto prioritario",
        ],
    },
}


class StripeNotConfiguredError(RuntimeError):
    """Stripe non configurato (secret mancante o libreria non importabile).

    Le route la convertono in HTTP 503 con messaggio per l'operatore.
    """


# =============================================================================
# Stato configurazione
# =============================================================================


def is_stripe_configured() -> bool:
    """True se il billing e' attivo (secret presente + libreria importabile)."""
    if not settings.stripe_secret_key.strip():
        return False
    try:
        _get_stripe_module()
    except StripeNotConfiguredError:
        return False
    return True


def is_webhook_configured() -> bool:
    """True se la verifica firma dei webhook e' attiva (whsec presente)."""
    return bool(settings.stripe_webhook_secret.strip())


# =============================================================================
# Lazy import della libreria
# =============================================================================

_stripe_module_cache: Optional[Any] = None


def _get_stripe_module() -> Any:
    """Import lazy di `stripe`, cached.

    Raises:
        StripeNotConfiguredError: se la libreria non e' installata o se
            STRIPE_SECRET_KEY e' vuota.
    """
    global _stripe_module_cache
    if _stripe_module_cache is not None:
        return _stripe_module_cache
    if not settings.stripe_secret_key.strip():
        raise StripeNotConfiguredError("STRIPE_SECRET_KEY non configurata (billing disabilitato).")
    try:
        import stripe
    except ImportError as e:  # pragma: no cover - dipende dall'installazione
        logger.warning("Libreria `stripe` non installata: billing disabilitato. %s", e)
        raise StripeNotConfiguredError(
            "Libreria `stripe` non installata (pip install stripe)."
        ) from e
    # Bucket versions notevoli: in produzione pinnare `stripe.api_version`
    # per evitare drift breaking con eventi futuri.
    stripe.api_key = settings.stripe_secret_key
    _stripe_module_cache = stripe
    logger.info("Stripe inizializzato (billing attivo).")
    return stripe


def _reset_stripe_module_cache() -> None:
    """Reset della cache lazy (per test / cambio runtime config)."""
    global _stripe_module_cache
    _stripe_module_cache = None


# =============================================================================
# Checkout Session
# =============================================================================


def create_checkout_session(
    user_id: str,
    price_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Crea una Stripe Checkout Session in modalita' subscription.

    Args:
        user_id: identificativo utente (sub JWT). Finisce in
                 `client_reference_id` + metadata per ricollegare il webhook.
        price_id: override del Price ID (default: settings.stripe_price_id).

    Returns:
        Dict con ``{checkout_url, session_id}``.

    Raises:
        StripeNotConfiguredError: billing disabilitato.
        HTTPException(400/503): dai layer superiori (route) — qui propaghiamo
            StripeError come errore generico con status coerente.
    """
    stripe = _get_stripe_module()
    price = (price_id or settings.stripe_price_id).strip()
    if not price:
        raise StripeNotConfiguredError(
            "STRIPE_PRICE_ID non configurata: impossibile creare checkout."
        )

    session = stripe.checkout.Session.create(  # type: ignore[attr-defined]
        mode="subscription",
        client_reference_id=user_id,
        metadata={"user_id": user_id, "plan": "pro"},
        line_items=[{"price": price, "quantity": 1}],
        success_url=(
            settings.billing_success_url
            or f"{settings.app_url}/app/profilo?billing=success"
        ),
        cancel_url=(
            settings.billing_cancel_url
            or f"{settings.app_url}/app/profilo?billing=cancel"
        ),
    )
    return {
        "checkout_url": session.url,
        "session_id": session.id,
        "amount_total": getattr(session, "amount_total", None),
        "currency": settings.stripe_currency,
    }


# =============================================================================
# Webhook: verifica firma + dispatch
# =============================================================================


def verify_webhook_signature(
    payload: bytes,
    sig_header: str,
) -> Any:
    """Verifica la firma di un webhook Stripe e ritorna l'evento.

    Raises:
        StripeNotConfiguredError: whsec non configurata.
        ValueError/Exception: firma non valida (la route la mappa in 400).
    """
    stripe = _get_stripe_module()
    if not is_webhook_configured():
        raise StripeNotConfiguredError("STRIPE_WEBHOOK_SECRET non configurata.")
    return stripe.Webhook.construct_event(  # type: ignore[attr-defined]
        payload=payload,
        sig_header=sig_header,
        secret=settings.stripe_webhook_secret,
    )


def handle_webhook_event(event: Any) -> Dict[str, Any]:
    """Dispatch dell'evento verificato.

    Supportati (skeleton Fase 4C):
        - ``checkout.session.completed``: registra la subscription (best-effort);
          eventi non gestiti vengono ack-ati come ``ignored``.

    Accepts sia un oggetto ``stripe.Event`` (dict-like) sia un dict puro
    (utile nei test e per pipeline che serializzano l'evento).
    """
    event_type = _event_type(event)
    if event_type == "checkout.session.completed":
        session = _event_object(event)
        customer_id = _get_field(session, "customer")
        user_id = _get_field(session, "client_reference_id")
        subscription_id = _get_field(session, "subscription")
        _record_subscription(
            user_id=user_id,
            customer_id=customer_id,
            subscription_id=subscription_id,
            plan="pro",
        )
        return {"action": "subscription_created", "customer_id": customer_id, "plan": "pro"}

    logger.info("Webhook Stripe: evento %r ignorato (nessun handler).", event_type)
    return {"action": "ignored", "event_type": event_type}


def _event_type(event: Any) -> str:
    """Legge `type` da un evento Stripe (dict oppure oggetto dict-like)."""
    if isinstance(event, dict):
        return event.get("type", "")
    return getattr(event, "type", "")


def _event_object(event: Any) -> Any:
    """Estrae `data.object` (la sessione checkout) da un evento Stripe."""
    data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
    if isinstance(data, dict):
        return data.get("object", {})
    return getattr(data, "object", {})


def _get_field(obj: Any, name: str) -> Any:
    """Legge un campo da una StripeObject o dict, senza sollevare."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _record_subscription(
    user_id: Optional[str],
    customer_id: Any,
    subscription_id: Any,
    plan: str,
) -> bool:
    """Scrive la subscription su Supabase (best-effort, non blocca l'ack).

    Richiede la tabella `subscriptions` (migrations/004_billing.sql).
    Se Supabase/DB non e' disponibile, logga un WARNING e torna False:
    il webhook Stripe ritenta in automatico fino a successo.
    """
    if not user_id:
        logger.warning("Webhook checkout.completed senza client_reference_id: skip persistenza.")
        return False
    client = supabase_client.get_supabase_client()
    if client is None:
        logger.warning("Supabase non disponibile: subscription non persistita (user=%s).", user_id[:12])
        return False
    try:
        client.table("subscriptions").upsert(
            {
                "user_id": user_id,
                "stripe_customer_id": str(customer_id) if customer_id else None,
                "stripe_subscription_id": str(subscription_id) if subscription_id else None,
                "plan": plan,
                "status": "active",
            },
            on_conflict="user_id",
        ).execute()
        logger.info("Subscription persistita (user=%s, plan=%s).", user_id[:12], plan)
        return True
    except Exception as e:  # pragma: no cover - dipende dal runtime DB
        logger.warning("Persistenza subscription fallita (user=%s): %s", user_id[:12], e)
        return False


def build_public_plan_info() -> Dict[str, Any]:
    """Info pubbliche del piano per GET /billing/plan (noc secret)."""
    pro = dict(PLAN_CATALOG["pro"])
    pro["name"] = settings.billing_plan_name or pro["name"]
    pro["price_id"] = settings.stripe_price_id  # l'id price e' pubblico (non-secret)
    pro["currency"] = settings.stripe_currency
    pro["configured"] = is_stripe_configured()
    return {
        "stripe_configured": is_stripe_configured(),
        "webhook_configured": is_webhook_configured(),
        "currency": settings.stripe_currency,
        "plans": [pro],
    }

# =============================================================================
# Stato billing per il client (GET /billing/status)
# =============================================================================


def _iso_or_none(value: Any) -> Optional[str]:
    """Serializza una data (str/datetime) in ISO 8601 senza sollevare."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:  # pragma: no cover - difensivo su tipi esotici
            pass
    return str(value)


def _as_int(value: Any, default: int = 0) -> int:
    """Converte un valore DB in int, con fallback sicuro (mai 5xx)."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _free_status(billing_enabled: bool) -> Dict[str, Any]:
    """Payload di default: utente free / nessuna riga di entitlement."""
    return {
        "billing_enabled": billing_enabled,
        "plan": "free",
        "status": "none",
        "period_end": None,
        "extractions_limit": 0,
        "extractions_used": 0,
    }


def _select_single_row(client: Any, table: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Legge una singola riga per ``user_id``. Qualsiasi errore => None.

    La route /billing/status non deve MAI rispondere 5xx: se la tabella non
    esiste ancora (migration non applicata) o Supabase e' giu', degradiamo a
    piano free con un WARNING (senza loggare PII o segreti).
    """
    try:
        result = (
            client.table(table)
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if isinstance(rows, list) and rows:
            row = rows[0]
            if isinstance(row, dict):
                return row
    except Exception as e:  # noqa: BLE001 - best-effort, mai 5xx al client
        logger.warning(
            "Billing status: lettura %s fallita per user=%s: %s",
            table,
            user_id[:12],
            e,
        )
    return None


def _map_entitlement_row(row: Dict[str, Any], billing_enabled: bool) -> Dict[str, Any]:
    """Mappa una riga ``entitlements`` sul contratto BillingStatusResponse."""
    plan = str(row.get("plan") or "free")
    status_value = str(row.get("status") or "none")
    period_end = _iso_or_none(
        row.get("current_period_end") or row.get("period_end") or row.get("expire_at")
    )
    raw_limit = row.get("extractions_limit")
    if raw_limit is None:
        limit = settings.billing_extractions_limit if plan != "free" else 0
    else:
        limit = _as_int(raw_limit, 0)
    return {
        "billing_enabled": billing_enabled,
        "plan": plan,
        "status": status_value,
        "period_end": period_end,
        "extractions_limit": limit,
        "extractions_used": _as_int(row.get("extractions_used"), 0),
    }


def _map_subscription_row(row: Dict[str, Any], billing_enabled: bool) -> Dict[str, Any]:
    """Mappa una riga ``subscriptions`` (skeleton legacy) sul contratto status."""
    status_value = str(row.get("status") or "none")
    is_active = status_value in ("active", "trialing", "past_due")
    plan = str(row.get("plan") or "pro") if is_active else "free"
    return {
        "billing_enabled": billing_enabled,
        "plan": plan,
        "status": status_value,
        "period_end": _iso_or_none(row.get("current_period_end")),
        "extractions_limit": settings.billing_extractions_limit if is_active else 0,
        "extractions_used": _as_int(row.get("extractions_used"), 0),
    }


def get_user_billing_status(user_id: str) -> Dict[str, Any]:
    """Stato piano dell'utente autenticato (contratto GET /billing/status).

    - Kill switch OFF (default): risponde subito free senza toccare il DB.
    - Tabella ``entitlements`` (piano Fase 4C) oppure ``subscriptions``
      (skeleton gia' deployato) come fallback.
    - Nessuna eccezione propagata: il client riceve sempre un payload valido.
    """
    enabled = bool(settings.billing_enabled)
    if not enabled:
        return _free_status(False)

    client = supabase_client.get_supabase_client()
    if client is None:
        logger.warning(
            "Billing status: Supabase non disponibile, risposta free (user=%s).",
            user_id[:12],
        )
        return _free_status(True)

    row = _select_single_row(client, "entitlements", user_id)
    if row is not None:
        return _map_entitlement_row(row, True)

    row = _select_single_row(client, "subscriptions", user_id)
    if row is not None:
        return _map_subscription_row(row, True)

    return _free_status(True)
