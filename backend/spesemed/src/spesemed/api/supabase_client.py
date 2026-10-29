"""SPESEMED API - Supabase client singleton con graceful degradation.

Fornisce `get_supabase_client()` che ritorna:
  - Client Supabase inizializzato, se SUPABASE_URL + SUPABASE_SERVICE_KEY sono settate
  - None altrimenti (gli endpoint che richiedono Supabase devono gestire 503)

Pattern di graceful degradation:
  - L'API puo' partire anche senza Supabase (utile per dev locale)
  - Endpoint /health funziona comunque (legge da settings.supabase_configured)
  - Endpoint /extract, /jobs, /auth ritornano 503 se Supabase non configurato
"""
from __future__ import annotations

import logging
from typing import Optional

from supabase import Client, create_client

from .config import settings

logger = logging.getLogger(__name__)


# Singleton: riusato da tutti i moduli
_client: Optional[Client] = None


def get_supabase_client() -> Optional[Client]:
    """Ritorna il client Supabase o None se non configurato.

    Idempotente: la prima chiamata crea il client, le successive lo riusano.

    NB: le chiamate supabase-py sono SINCRONE e bloccanti. In contesti async
    (worker, endpoint FastAPI) wrappare con `await asyncio.to_thread(...)`.
    """
    global _client
    if _client is not None:
        return _client
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    try:
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
        logger.info(
            "Supabase client inizializzato (bucket=%s, url=%s)",
            settings.supabase_bucket,
            settings.supabase_url[:40] + "..." if len(settings.supabase_url) > 40 else settings.supabase_url,
        )
    except Exception as e:
        logger.error("Impossibile inizializzare Supabase client: %s", e)
        return None
    return _client


def is_supabase_configured() -> bool:
    """True se Supabase e' configurato (env vars presenti)."""
    return bool(settings.supabase_url and settings.supabase_service_key)


def reset_supabase_client() -> None:
    """Reset del singleton (per test)."""
    global _client
    _client = None
