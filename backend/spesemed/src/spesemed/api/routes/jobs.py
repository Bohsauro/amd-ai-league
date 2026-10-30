"""SPESEMED API - GET /api/v1/jobs (storico) + GET /api/v1/jobs/{id} (dettaglio).

GET /api/v1/jobs      -> lista paginata dei job dell'utente (max 20).
GET /api/v1/jobs/{id} -> stato corrente di un job async con risultati.

Quando status='done', i results sono popolati dalla tabella `extractions`
filtrata per job_id.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...core.models import SpesaMedica
from ..config import settings
from ..dependencies import get_current_user
from ..rate_limit import limiter
from ..schemas import ErrorResponse, JobStatusResponse, JobListItem, JobListResponse
from .. import supabase_client  # NB: import del MODULO (non dei nomi) per monkeypatch pulito

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


# =============================================================================
# GET /api/v1/jobs — lista paginata dei job dell'utente
# =============================================================================
@router.get(
    "/jobs",
    response_model=JobListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        429: {"model": ErrorResponse, "description": "Troppe richieste."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit(settings.rate_limit_jobs)
async def list_jobs(
    response: Response,
    request: Request,
    user_id: str = Depends(get_current_user),
    limit: int = 20,
    offset: int = 0,
) -> JobListResponse:
    """Ritorna la lista paginata dei job dell'utente, ordinati per data."""
    # SECURITY: sanitize per evitare query massive (max 100 risultati).
    limit = min(max(1, limit), 100)
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

    try:
        job_res = (
            client.table("jobs")
            .select("id, user_id, status, file_count, created_at, updated_at, last_error", count="exact")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception as e:
        logger.exception("Jobs list SELECT failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Errore del server. Riprova piu' tardi.",
        ) from e

    rows = job_res.data or []
    total = job_res.count or len(rows)

    jobs = [
        JobListItem(
            job_id=row["id"],
            status=row.get("status", "unknown"),
            file_count=row.get("file_count", 0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_error=row.get("last_error"),
        )
        for row in rows
    ]

    return JobListResponse(
        jobs=jobs,
        total=total,
        limit=limit,
        offset=offset,
    )


# =============================================================================
# GET /api/v1/jobs/{id} — dettaglio job
# =============================================================================
@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Job non trovato."},
        429: {"model": ErrorResponse, "description": "Troppe richieste di polling."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit(settings.rate_limit_jobs)
async def get_job_status(
    response: Response,  # NB: slowapi necessita di Response per X-RateLimit headers.
    request: Request,
    job_id: str,
    user_id: str = Depends(get_current_user),
) -> JobStatusResponse:
    """Ritorna lo stato corrente di un job asincrono.

    Quando status='done', i results contengono le SpesaMedica estratte.
    Altrimenti solo lo status + contatori.
    """
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

    try:
        job_res = (
            client.table("jobs")
            .select("id, user_id, status, file_count, file_hashes, last_error, created_at, updated_at")
            .eq("id", job_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("Jobs SELECT failed for %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Errore del server. Riprova piu' tardi.",
        ) from e

    if not job_res.data:
        # Security: NON rivelare se il job esiste ma appartiene a un altro user.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} non trovato.",
        )
    job = job_res.data[0]

    results = None
    completed_count = 0
    if job["status"] == "done":
        try:
            extr_res = (
                client.table("extractions")
                .select("data")
                .eq("job_id", job_id)
                .execute()
            )
            results = [SpesaMedica(**row["data"]) for row in (extr_res.data or [])]
            completed_count = len(results)
        except Exception as e:
            logger.warning(
                "Jobs: impossibile leggere extractions per job %s: %s",
                job_id, e,
            )
            completed_count = 0
    elif job["status"] == "processing":
        completed_count = 0

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        file_count=job["file_count"],
        completed_count=completed_count,
        results=results,
        error=job.get("last_error"),
    )
