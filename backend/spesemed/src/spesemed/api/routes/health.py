"""SPESEMED API - GET /api/v1/health (liveness check)."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check base. Verifica che l'app sia viva e che la chiave OpenRouter sia configurata.

    In Fase 4 verra' esteso per:
        - Pingare OpenRouter (verifica connettivita' reale)
        - Pingare Supabase (verifica DB accessibile)
        - Restituire 503 se qualche dipendenza e' giu'
    """
    return HealthResponse(
        status="ok",
        service="spesemed-api",
        version=settings.api_version,
        openrouter_configured=bool(settings.openrouter_api_key),
    )
