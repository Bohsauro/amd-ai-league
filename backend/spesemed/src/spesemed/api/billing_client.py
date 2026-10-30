"""SPESEMED API - Wrapper Stripe DI-friendly (Fase 4C).

Pattern identico a ``supabase_client.py``: il modulo importa ``stripe`` una
sola volta e tutte le funzioni passano dal modulo, cosi' i test offline possono
sostituirlo con un fake senza toccare la rete.

Regole di sicurezza:
    - nessun secret hardcoded: tutto arriva da ``settings`` (env/.env deploy);
    - nessuna chiave o payload webhook viene loggata (PII / credenziali);
    - se la libreria ``stripe`` non e' installata il modulo resta importabile
      e il billing risulta semplicemente disabilitato (graceful degradation).

Il kill switch e' ``BILLING_ENABLED`` (default False): con il flag spento
``is_billing_configured()`` e' False e nessuna chiamata di rete parte.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .config import settings

logger = logging.getLogger(__name__)

try:  # pragma: no cover - dipende dall'ambiente di installazione
    import stripe  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - graceful degradation senza dipendenza
    stripe = None  # type: ignore[assignment]


class BillingNotConfiguredError(RuntimeError):
    """Billing spento o configurazione Stripe incompleta."""


# =============================================================================
# Configurazione
# =============================================================================


def is_billing_configured() -> bool:
    """True solo se kill switch ON e tutte le chiavi Stripe sono presenti.

    ``billing_enabled`` e' letto con ``getattr`` per restare compatibile anche
    con settings piu' vecchi (in quel caso il default e' OFF, mai fail-open).
    """
    if stripe is None:
        return False
    return bool(
        getattr(settings, "billing_enabled", False)
        and getattr(settings, "stripe_secret_key", "").strip()
        and getattr(settings, "stripe_webhook_secret", "").strip()
        and getattr(settings, "stripe_price_id", "").strip()
    )


def _require_stripe() -> Any:
    if stripe is None:
        raise BillingNotConfiguredError(
            "Libreria `stripe` non installata: billing disabilitato."
        )
    return stripe


# =============================================================================
# Checkout Session
# =============================================================================


def _success_url() -> str:
    configured = (
        getattr(settings, "billing_success_url", "")
        or getattr(settings, "stripe_success_url", "")
    ).strip()
    if configured:
        return configured
    app_url = getattr(settings, "app_url", "").rstrip("/")
    return f"{app_url}/app/profilo?billing=success"


def _cancel_url() -> str:
    configured = (
        getattr(settings, "billing_cancel_url", "")
        or getattr(settings, "stripe_cancel_url", "")
    ).strip()
    if configured:
        return configured
    app_url = getattr(settings, "app_url", "").rstrip("/")
    return f"{app_url}/app/profilo?billing=cancel"


def create_checkout_session(user_id: str, email: str) -> Dict[str, str]:
    """Crea una Checkout Session subscription e ritorna URL + session id.

    ``client_reference_id`` e ``metadata.user_id`` legano la sessione
    all'utente applicativo, cosi' il webhook puo' fare l'upsert corretto.

    Raises:
        BillingNotConfiguredError: kill switch OFF o configurazione incompleta.
    """
    stripe_module = _require_stripe()
    if not is_billing_configured():
        raise BillingNotConfiguredError("Billing non configurato.")

    stripe_module.api_key = getattr(settings, "stripe_secret_key", "")
    session = stripe_module.checkout.Session.create(
        mode="subscription",
        customer_email=email,
        line_items=[
            {"price": getattr(settings, "stripe_price_id", ""), "quantity": 1}
        ],
        client_reference_id=user_id,
        metadata={"user_id": user_id},
        success_url=_success_url(),
        cancel_url=_cancel_url(),
    )
    logger.info("Checkout session Stripe creata (user=%s).", _short(user_id))
    return {"checkout_url": session.url, "session_id": session.id}


# =============================================================================
# Webhook
# =============================================================================


def parse_webhook_event(payload: bytes, sig_header: str) -> Any:
    """Verifica la firma del webhook e ritorna l'evento Stripe.

    Raises:
        BillingNotConfiguredError: libreria/chiavi mancanti.
        Exception: firma non valida (propagata: la route la mappa a 400).
    """
    stripe_module = _require_stripe()
    stripe_module.api_key = getattr(settings, "stripe_secret_key", "")
    return stripe_module.Webhook.construct_event(
        payload,
        sig_header,
        getattr(settings, "stripe_webhook_secret", ""),
    )


def map_event_to_entitlement(event: Any) -> Optional[Dict[str, Any]]:
    """Traduce un evento Stripe in una riga di upsert per ``entitlements``.

    Ritorna ``None`` per eventi fuori scope o senza ``user_id``: la route li
    ack-a con 200 senza toccare il DB.
    """
    etype = _event_type(event)
    data = _event_object(event)
    if not etype or not data:
        return None

    user_id = _event_user_id(data)
    if not user_id:
        return None

    if etype == "checkout.session.completed":
        status = "trialing" if _get_field(data, "subscription_status") == "trialing" else "active"
        return {
            "user_id": user_id,
            "plan": "pro",
            "status": status,
            "current_period_start": now_iso(),
            "current_period_end": period_end(data),
            "extractions_limit": _extractions_limit(),
            "extractions_used": 0,
            "stripe_customer_id": _get_field(data, "customer"),
            "stripe_subscription_id": _get_field(data, "subscription"),
        }

    if etype == "customer.subscription.updated":
        status = _get_field(data, "status") or "active"
        mapping = {
            "user_id": user_id,
            "plan": "pro",
            "status": status,
            "current_period_end": period_end(data),
            "stripe_customer_id": _get_field(data, "customer"),
            "stripe_subscription_id": _get_field(data, "id"),
        }
        if status in ("active", "trialing", "past_due"):
            mapping["extractions_limit"] = _extractions_limit()
            return mapping
        if status in ("canceled", "unpaid", "incomplete_expired"):
            mapping["status"] = "none"
            mapping["extractions_limit"] = 0
            return mapping
        return None

    if etype == "invoice.paid":
        return {
            "user_id": user_id,
            "plan": "pro",
            "status": "active",
            "current_period_end": period_end(data),
            "extractions_limit": _extractions_limit(),
            "extractions_used": 0,
            "stripe_customer_id": _get_field(data, "customer"),
            "stripe_subscription_id": _get_field(data, "subscription"),
        }

    return None


def upsert_entitlement(client: Any, mapping: Dict[str, Any]) -> None:
    """Upsert idempotente su ``entitlements`` (chiave ``user_id``)."""
    client.table("entitlements").upsert(mapping, on_conflict="user_id").execute()


# =============================================================================
# Helper di estrazione / date
# =============================================================================


def _short(value: Any) -> str:
    text = str(value or "")
    return text[:12]


def _extractions_limit() -> int:
    return int(getattr(settings, "billing_extractions_limit", 100))


def _get_field(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    if hasattr(obj, "get"):
        try:
            return obj.get(name)
        except Exception:  # noqa: BLE001 - StripeObject puo' sollevare su chiavi assenti
            pass
    return getattr(obj, name, None)


def _event_type(event: Any) -> str:
    return _get_field(event, "type") or ""


def _event_object(event: Any) -> Any:
    data = _get_field(event, "data")
    if data is None:
        return {}
    return _get_field(data, "object") or {}


def _event_user_id(data: Any) -> Optional[str]:
    metadata = _get_field(data, "metadata")
    if metadata is None:
        subscription_details = _get_field(data, "subscription_details")
        metadata = _get_field(subscription_details, "metadata")
    return (
        _get_field(data, "client_reference_id")
        or _get_field(metadata, "user_id")
    )


def _to_iso(value: Any) -> Optional[str]:
    """Converte timestamp Unix (int/str) in ISO-8601 UTC; None se invalido."""
    if value is None or value == "":
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def later_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def period_end(data: Any) -> str:
    """Estrae la fine periodo da subscription/invoice, con fallback +30 giorni.

    Gestisce sia il campo top-level ``current_period_end`` (API Stripe
    storica) sia ``items.data[0].current_period_end`` / ``lines.data[0].period.end``
    (API recenti).
    """
    candidates = [_get_field(data, "current_period_end")]
    for collection_name in ("items", "lines"):
        collection = _get_field(data, collection_name)
        entries = _get_field(collection, "data") if collection is not None else None
        if not entries:
            continue
        first = entries[0]
        candidates.append(_get_field(first, "current_period_end"))
        period = _get_field(first, "period")
        if period is not None:
            candidates.append(_get_field(period, "end"))

    for candidate in candidates:
        iso = _to_iso(candidate)
        if iso:
            return iso
    return later_iso()
