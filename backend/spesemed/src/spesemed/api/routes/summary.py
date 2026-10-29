"""SPESEMED API - GET /api/v1/summary (Profilo utente / usage).

Aggrega le `extractions` (spese) e i `jobs` dell'utente autenticato in un
riepilogo leggero per la schermata Profilo del client:

    {
      "total_spese": 12,
      "totale_importo": 843.55,
      "total_jobs": 5,
      "jobs_done": 4,
      "jobs_failed": 1,
      "jobs_in_progress": 0,
      "per_categoria": [
        {"categoria": "Farmaci", "importo": 120.30, "count": 4},
        ...
      ]
    }

Rate limit: riusa `rate_limit_jobs` (letture frequenti dello storico).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...core.models import SpesaMedica
from .. import supabase_client  # NB: import del MODULO (non dei nomi) per monkeypatch pulito
from ..config import settings
from ..dependencies import get_current_user
from ..rate_limit import limiter
from ..schemas import CategoryTotal, ErrorResponse, UsageSummaryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["summary"])


# =============================================================================
# GET /api/v1/summary
# =============================================================================
@router.get(
    "/summary",
    response_model=UsageSummaryResponse,
    status_code=status.HTTP_200_OK,
    responses={
        429: {"model": ErrorResponse, "description": "Troppe richieste."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit(settings.rate_limit_jobs)
async def get_summary(
    response: Response,  # NB: slowapi necessita di Response per X-RateLimit headers.
    request: Request,
    user_id: str = Depends(get_current_user),
) -> UsageSummaryResponse:
    """Ritorna il riepilogo spese + usage dell'utente autenticato."""
    if not supabase_client.is_supabase_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase non configurato sul server.",
        )

    client = supabase_client.get_supabase_client()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Impossibile inizializzare Supabase client.",
        )

    # ── 1. Fetch extractions (in thread: supabase-py è sync) ─────────────
    try:
        extr_rows = await asyncio.to_thread(_fetch_extractions, client, user_id)
    except Exception as e:
        logger.exception("Summary SELECT extractions failed (user=%s)", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Errore del server. Riprova più tardi.",
        ) from e

    # ── 2. Aggrega spese ────────────────────────────────────────────────
    total_spese = 0
    totale_importo = 0.0
    per_cat: Dict[str, List[float]] = {}
    for row in extr_rows:
        try:
            spesa = SpesaMedica(**row.get("data", {}))
        except Exception as e:
            logger.warning(
                "Summary: riga extractions non parsabile (user=%s): %s",
                user_id, type(e).__name__,
            )
            continue
        total_spese += 1
        importo = spesa.importo_totale or 0.0
        totale_importo += importo
        per_cat.setdefault(spesa.categoria_spesa, []).append(importo)

    per_categoria: List[CategoryTotal] = []
    for cat, importi in per_cat.items():
        per_categoria.append(
            CategoryTotal(
                categoria=cat,
                importo=round(sum(importi), 2),
                count=len(importi),
            )
        )
    # Ordina per importo decrescente (più visibile in cima al profilo).
    per_categoria.sort(key=lambda c: c.importo, reverse=True)

    # ── 3. Fetch job stats (in thread) ──────────────────────────────────
    try:
        job_rows = await asyncio.to_thread(_fetch_jobs, client, user_id)
    except Exception as e:
        logger.exception("Summary SELECT jobs failed (user=%s)", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Errore del server. Riprova più tardi.",
        ) from e

    total_jobs = len(job_rows)
    jobs_done = sum(1 for r in job_rows if r.get("status") == "done")
    jobs_failed = sum(1 for r in job_rows if r.get("status") == "failed")
    jobs_in_progress = total_jobs - jobs_done - jobs_failed

    logger.info(
        "Summary user=%s: %d spese (%.2f EUR), %d jobs",
        user_id, total_spese, totale_importo, total_jobs,
    )
    return UsageSummaryResponse(
        total_spese=total_spese,
        totale_importo=round(totale_importo, 2),
        total_jobs=total_jobs,
        jobs_done=jobs_done,
        jobs_failed=jobs_failed,
        jobs_in_progress=jobs_in_progress,
        per_categoria=per_categoria,
    )


# =============================================================================
# Helpers (sync, wrappate in asyncio.to_thread dal route handler)
# =============================================================================
def _fetch_extractions(client, user_id: str) -> list:
    """Fetch di tutte le extractions dell'utente (solo campo data)."""
    return (
        client.table("extractions")
        .select("data")
        .eq("user_id", user_id)
        .execute()
    ).data or []


def _fetch_jobs(client, user_id: str) -> list:
    """Fetch degli status di tutti i job dell'utente."""
    return (
        client.table("jobs")
        .select("status")
        .eq("user_id", user_id)
        .execute()
    ).data or []
