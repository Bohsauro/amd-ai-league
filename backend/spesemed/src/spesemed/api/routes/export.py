"""SPESEMED API - POST /api/v1/export (Fase 4B: ZIP per il commercialista).

Pipeline:
    1. Autenticazione (get_current_user) + rate limit.
    2. Fetch delle extractions dell'utente (filtri opzionali: job_id, file_hashes).
    3. Download dei file originali da Supabase Storage (bucket privato).
    4. Generazione ZIP in-memory (Excel riepilogativo + ricevute rinominate
       `YYYY-MM-DD_esercente_importoCAT.ext`) via `spesemed.core.exporter`.
    5. Response `application/zip` con Content-Disposition attachment.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

from ...core.exporter import build_zip_bytes
from ...core.models import SpesaMedica
from .. import supabase_client  # NB: import del MODULO (non dei nomi) per monkeypatch pulito
from ..config import settings
from ..dependencies import get_current_user
from ..rate_limit import limiter
from ..schemas import ErrorResponse, ExportRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])

# Nome del file ZIP scaricato dal client.
_EXPORT_FILENAME_PREFIX = "spesemed_export"


# =============================================================================
# POST /api/v1/export
# =============================================================================
@router.post(
    "/export",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "ZIP con Excel riepilogativo + ricevute rinominate."},
        400: {"model": ErrorResponse, "description": "Nessuna estrazione da esportare."},
        401: {"model": ErrorResponse, "description": "Non autenticato."},
        429: {"model": ErrorResponse, "description": "Troppe richieste di export."},
        503: {"model": ErrorResponse, "description": "Supabase non configurato."},
    },
)
@limiter.limit(settings.rate_limit_export)
async def export_data(
    response: Response,  # NB: slowapi necessita di Response per X-RateLimit headers.
    request: Request,
    body: Optional[ExportRequest] = Body(default=None),
    user_id: str = Depends(get_current_user),
) -> Response:
    """Genera e restituisce lo ZIP per il commercialista.

    Il body è opzionale: con `{}` vengono esportate TUTTE le estrazioni
    dell'utente. Con `{"job_id": ...}` o `{"file_hashes": [...]}` viene
    esportato solo il sottoinsieme richiesto.
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

    # ── 1. Fetch extractions (in thread: supabase-py è sync) ──────────────
    try:
        rows = await asyncio.to_thread(
            _fetch_extractions,
            client,
            user_id,
            body.job_id if body else None,
            body.file_hashes if body else None,
        )
    except Exception as e:
        logger.exception("Export SELECT extractions failed (user=%s)", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Errore del server. Riprova più tardi.",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nessuna estrazione da esportare per questo utente.",
        )

    # ── 2. Build coppie allineate (spesa, filename, content) ──────────────
    # NB: spesa e ricevuta vengono incluse SOLO INSIEME (niente disallineamento
    # posizionale se un download storage fallisce: la ricevuta della riga N
    # verrebbe rinominata con i dati della spesa N-1 — errore di integrità).
    entries: list[tuple] = []  # (SpesaMedica, filename_originale, bytes)
    skipped = 0
    for row in rows:
        try:
            spesa = SpesaMedica(**row.get("data", {}))
        except Exception as e:
            skipped += 1
            logger.warning(
                "Export: riga extractions non parsabile (user=%s): %s",
                user_id, type(e).__name__,
            )
            continue

        storage_path = row.get("storage_path")
        filename = row.get("filename") or "ricevuta"
        if not storage_path:
            skipped += 1
            logger.warning(
                "Export: nessun storage_path per %s (file originale non disponibile).",
                filename,
            )
            continue

        # SECURITY (defense-in-depth): verifica che storage_path appartenga al prefisso dell'utente.
        # Evita download cross-tenant tramite service_role qualora la riga DB fosse malformata.
        expected_prefix = f"receipts/{user_id}/"
        if not storage_path.startswith(expected_prefix) and not storage_path.startswith(f"{user_id}/"):
            skipped += 1
            logger.warning(
                "Export: storage_path non autorizzato '%s' per user=%s (skip).",
                storage_path, user_id,
            )
            continue

        try:
            content = await asyncio.to_thread(
                client.storage.from_(settings.supabase_bucket).download,
                storage_path,
            )
        except Exception as e:
            skipped += 1
            logger.warning(
                "Export: download storage fallito per %s: %s",
                filename, type(e).__name__,
            )
            continue
        entries.append((spesa, filename, content))

    if not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nessuna estrazione valida da esportare.",
        )

    if skipped:
        logger.warning(
            "Export parziale: %d/%d righe esportate (%d saltate) user=%s",
            len(entries), len(rows), skipped, user_id,
        )

    # ── 3. Genera ZIP in-memory (spese allineate alle ricevute) ────────────
    spese = [e[0] for e in entries]
    # NB: chiavi univoche con prefisso indice: due righe possono avere lo
    # stesso `filename` originale (es. due upload di "Scan.pdf") e un dict
    # con chiave duplicata collasserebbe, disallineando il pairing posizionale
    # con `spese`. Il suffisso (estensione) resta quello del file originale.
    receipts = {f"{i:03d}_{e[1]}": e[2] for i, e in enumerate(entries)}
    zip_bytes = await asyncio.to_thread(
        build_zip_bytes,
        spese,
        receipts,
    )

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"{_EXPORT_FILENAME_PREFIX}_{today}.zip"
    logger.info(
        "Export generato: user=%s, %d spese, %d ricevute, %d KB",
        user_id, len(spese), len(receipts), len(zip_bytes) // 1024,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# =============================================================================
# Helpers (sync, wrappate in asyncio.to_thread dal route handler)
# =============================================================================
def _fetch_extractions(
    client,
    user_id: str,
    job_id: Optional[str] = None,
    file_hashes: Optional[List[str]] = None,
) -> list:
    """Fetch delle extractions dell'utente con filtri opzionali.

    Ritorna le righe complete (data, storage_path, filename, file_hash).
    """
    query = (
        client.table("extractions")
        .select("data, storage_path, filename, file_hash")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )
    if job_id:
        query = query.eq("job_id", job_id)
    if file_hashes:
        query = query.in_("file_hash", file_hashes)
    res = query.execute()
    return res.data or []
