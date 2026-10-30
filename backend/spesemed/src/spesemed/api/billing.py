"""SPESEMED API - Integrazione Stripe billing (Fase 4C).

Skeleton operativo con **no-op mode** senza secrets:

    - Se ``STRIPE_SECRET_KEY`` e' vuota (o la libreria `stripe` non e'
      installata/impoortabile) => billing DISABILITATO: le route ritornano
      503 e nessuna chiamata di rete parte.
    - Nessun secret reale nel codice: tutto arriva da env/.env del deploy.

Endpoints esposti (vedi routes/billing.py):
    GET  /api/v1/billing/status    - stato piano dell'utente (auth).
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

import datetime
import logging
from typing import Any, Dict, Optional

from .config import settings
from . import supabase_client

logger = logging.getLogger(__name__)


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


def process_webhook_event(event: Any) -> Dict[str, Any]:
    """Processa un evento verificato con idempotenza su ``billing_events``.

    Il primo arrivo dell'evento viene registrato (PK ``event_id``) e poi
    dispatchato. Un replay (event_id gia' presente) risponde 200 senza
    rieseguire gli upsert. Se Supabase non e' disponibile l'evento viene
    comunque processato best-effort: meglio un ack che un retry infinito.
    """
    client = supabase_client.get_supabase_client()
    if not _record_billing_event(client, event):
        return {
            "action": "ignored",
            "event_type": _event_type(event),
            "replayed": True,
        }
    result = handle_webhook_event(event, client=client)
    result.setdefault("replayed", False)
    return result


def handle_webhook_event(event: Any, client: Any = None) -> Dict[str, Any]:
    """Dispatch dell'evento verificato.

    Supportati (Fase 4C):
        - ``checkout.session.completed``: registra la subscription;
        - ``customer.subscription.updated/deleted``: aggiorna stato e periodo;
        - ``invoice.paid``: rinnova il periodo della subscription.
    Eventi non gestiti vengono ack-ati come ``ignored``.

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
            client=client,
        )
        return {"action": "subscription_created", "customer_id": customer_id, "plan": "pro"}

    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        subscription = _event_object(event)
        customer_id = _get_field(subscription, "customer")
        subscription_id = _get_field(subscription, "id")
        deleted = event_type.endswith(".deleted")
        status_value = "canceled" if deleted else (_get_field(subscription, "status") or "active")
        _update_subscription(
            client=client,
            customer_id=customer_id,
            subscription_id=subscription_id,
            values={
                "status": status_value,
                "current_period_end": _unix_to_iso(_get_field(subscription, "current_period_end")),
                "stripe_subscription_id": str(subscription_id) if subscription_id else None,
            },
        )
        action = "subscription_canceled" if deleted else "subscription_updated"
        return {"action": action, "event_type": event_type, "status": status_value}

    if event_type == "invoice.paid":
        invoice = _event_object(event)
        _update_subscription(
            client=client,
            customer_id=_get_field(invoice, "customer"),
            subscription_id=_get_field(invoice, "subscription"),
            values={
                "status": "active",
                "current_period_end": _unix_to_iso(_get_field(invoice, "period_end")),
            },
        )
        return {"action": "invoice_paid", "event_type": event_type}

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


def _is_duplicate_key_error(exc: Exception) -> bool:
    """True se l'errore Supabase/Postgres e' una violazione di PK/unique."""
    code = getattr(exc, "code", None)
    if code in ("23505", "409"):
        return True
    message = str(exc).lower()
    return "23505" in message or "duplicate key" in message or "already exists" in message


def _record_billing_event(client: Any, event: Any) -> bool:
    """Registra l'evento su ``billing_events``. True = nuovo, False = replay.

    L'INSERT con PK su ``event_id`` e' atomico: due consegne concorrenti dello
    stesso evento producono una sola riga e un solo processing. Se la tabella
    non esiste / il DB e' giu', degradiamo processando l'evento (best-effort).
    """
    if client is None:
        return True
    event_id = _get_field(event, "id")
    event_type = _event_type(event)
    if not event_id:
        logger.warning("Webhook Stripe senza event.id: idempotenza non garantita.")
        return True
    try:
        client.table("billing_events").insert(
            {"event_id": str(event_id), "type": event_type}
        ).execute()
        return True
    except Exception as e:  # noqa: BLE001 - best-effort, non blocca l'ack
        if _is_duplicate_key_error(e):
            logger.info("Webhook Stripe replay ignorato (id=%s, type=%s).", event_id, event_type)
            return False
        logger.warning(
            "Persistenza billing_event fallita (id=%s, type=%s): %s. Evento processato comunque.",
            event_id,
            event_type,
            e,
        )
        return True


def _unix_to_iso(value: Any) -> Optional[str]:
    """Converte un timestamp Unix (Stripe) in ISO 8601 UTC, senza sollevare."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return _iso_or_none(value)


def _update_subscription(
    client: Any,
    customer_id: Any,
    subscription_id: Any,
    values: Dict[str, Any],
) -> bool:
    """Aggiorna la subscription Stripe per id subscription o customer."""
    if client is None:
        logger.warning("Supabase non disponibile: subscription non aggiornata.")
        return False
    clean_values = {key: value for key, value in values.items() if value is not None}
    if not clean_values:
        return False
    try:
        if subscription_id:
            (
                client.table("subscriptions")
                .update(clean_values)
                .eq("stripe_subscription_id", str(subscription_id))
                .execute()
            )
        elif customer_id:
            (
                client.table("subscriptions")
                .update(clean_values)
                .eq("stripe_customer_id", str(customer_id))
                .execute()
            )
        else:
            logger.warning("Evento subscription senza customer/subscription id: skip update.")
            return False
        logger.info("Subscription aggiornata (stato=%s).", clean_values.get("status"))
        return True
    except Exception as e:  # noqa: BLE001 - best-effort, non blocca l'ack
        logger.warning("Aggiornamento subscription fallito: %s", e)
        return False


def _record_subscription(
    user_id: Optional[str],
    customer_id: Any,
    subscription_id: Any,
    plan: str,
    client: Any = None,
) -> bool:
    """Scrive la subscription su Supabase (best-effort, non blocca l'ack).

    Richiede la tabella `subscriptions` (migrations/004_billing.sql).
    Se Supabase/DB non e' disponibile, logga un WARNING e torna False:
    il webhook Stripe ritenta in automatico fino a successo.
    """
    if not user_id:
        logger.warning("Webhook checkout.completed senza client_reference_id: skip persistenza.")
        return False
    if client is None:
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
