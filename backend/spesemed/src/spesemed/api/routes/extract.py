"""SPESEMED API - POST /api/v1/extract (modalita' IBRIDA: sync <=3, async >3).

Pipeline:
    1. Validazione numero file, estensioni, dimensione.
    2. Validazione dipendenze esterne (OpenRouter API key, Supabase config).
    3. BRANCH:
        - N <= max_sync_files: processa sincrono, ritorna ExtractSyncResponse
        - N >  max_sync_files: crea job asincrono, ritorna 202 + JobPendingResponse

Rate limit (Fase 3): slowapi @limiter.limit(settings.rate_limit_extract).
"""
from __future__ import annotations

import hashlib
import logging
import tempfile
import uuid
from pathlib import Path
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from ...core.extractor import ExtractorError, extract_from_file
from ..config import settings
from ..dependencies import get_current_user
from ..rate_limit import limiter
from ..schemas import (
    ErrorResponse,
    ExtractSyncResponse,
    JobPendingResponse,
)
from .. import supabase_client  # NB: import del MODULO (non dei nomi) per monkeypatch pulito

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extract"])


# Limiti operativi (max_async_files viene da settings per tuning via env)
_FILE_MIN = 1

# Estensioni accettate (allineate al core)
_ACCEPTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Dimensione chunk per streaming uploads (FIX C1, anti-OOM).
# 64KB bilancia: riduce syscall vs RAM, evita allocazioni di mega-buffer.
_UPLOAD_CHUNK_BYTES = 64 * 1024


async def _read_upload_streaming(uploaded: UploadFile, max_bytes: int) -> bytes:
    """Legge un UploadFile in streaming abortendo se supera max_bytes (FIX C1 anti-OOM).

    SECURITY: NON usa `await uploaded.read()` che porterebbe l'intero file in RAM
    PRIMA del size check (vettore OOM DoS: 200 file x 1GB = 200GB, OOM processo).
    La protezione opera su due livelli:
      1. Pre-check su `uploaded.size` (Content-Length header) se il client lo
         dichiara, abort immediato senza scaricare il body.
      2. Stream-read a chunk 64KB con abort non appena si raggiunge max_bytes.

    Args:
        uploaded: file caricato dal client (starlette UploadFile).
        max_bytes: limite esatto in bytes (gia' convertito da MB).

    Returns:
        Bytes completi del file (gia' validati come <= max_bytes).

    Raises:
        HTTPException 413: dimensione del file > max_bytes.
    """
    # 1. Pre-check Content-Length (Starlette lo parsa se presente).
    declared_size = getattr(uploaded, "size", None)
    if declared_size is not None and declared_size > max_bytes:
        filename = uploaded.filename or "unnamed"
        logger.warning(
            "Upload rejected (declared Content-Length): file=%r declared=%d max=%d",
            filename, declared_size, max_bytes,
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File '{filename}' troppo grande: {declared_size} bytes "
                f"(max {max_bytes // (1024 * 1024)} MB)."
            ),
        )

    # 2. Stream-read con abort dinamico su superamento soglia.
    chunks = bytearray()
    bytes_read = 0
    while True:
        chunk = await uploaded.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        bytes_read += len(chunk)
        if bytes_read > max_bytes:
            filename = uploaded.filename or "unnamed"
            logger.warning(
                "Upload aborted mid-stream: file=%r bytes_read=%d max=%d",
                filename, bytes_read, max_bytes,
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File '{filename}' troppo grande: supera "
                    f"{max_bytes} bytes ({max_bytes // (1024 * 1024)} MB) "
                    "durante lo streaming."
                ),
            )
        chunks.extend(chunk)
    return bytes(chunks)


# =============================================================================
# Entry point: auto-routing
# =============================================================================
@router.post(
    "/extract",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": ExtractSyncResponse, "description": "Sync (N<=max_sync_files)."},
        202: {"model": JobPendingResponse, "description": "Async (N>max_sync_files)."},
        400: {"model": ErrorResponse, "description": "N fuori range o estensione non supportata."},
        413: {"model": ErrorResponse, "description": "File troppo grande."},
        422: {"model": ErrorResponse, "description": "Sync: tutti i file falliti."},
        429: {"model": ErrorResponse, "description": "Troppe richieste di estrazione."},
        503: {"model": ErrorResponse, "description": "OpenRouter API key o Supabase mancanti."},
    },
)
@limiter.limit(settings.rate_limit_extract)
async def extract(
    request: Request,
    response: Response,
    files: List[UploadFile] = File(
        ...,
        description=f"Da {_FILE_MIN} a {settings.max_async_files} file (PDF, JPG, JPEG, PNG, WEBP, BMP).",
    ),
    user_id: str = Depends(get_current_user),
):
    """Estrai dati strutturati da N ricevute mediche.

    - N <= max_sync_files (default 3): risposta sincrona con results[].
    - N >  max_sync_files: risposta 202 Accepted con job_id da polledare.
    """
    n = len(files)
    if not _FILE_MIN <= n <= settings.max_async_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Numero file fuori range: da {_FILE_MIN} a {settings.max_async_files}. "
                f"Hai inviato {n}."
            ),
        )

    # Validazione dipendenze esterne
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENROUTER_API_KEY non configurata sul server.",
        )
    if not supabase_client.is_supabase_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase non configurato sul server (richiesto per idempotency + storage).",
        )

    # Branch
    if n > settings.max_sync_files:
        response.status_code = status.HTTP_202_ACCEPTED
        job = await _create_async_job(files, user_id)
        return job
    else:
        return await _process_sync(files, user_id)


# =============================================================================
# SYNC (N <= max_sync_files)
# =============================================================================
async def _process_sync(
    files: List[UploadFile],
    user_id: str,
) -> ExtractSyncResponse:
    """Elabora N<=3 file in modo sincrono, con idempotency + persistenza."""
    client = supabase_client.get_supabase_client()
    if client is None:
        # create_client puo' fallire anche se is_supabase_configured() e' True
        # (es. URL/key malformate o rete down al boot). Usiamo HTTPException
        # invece di `assert` perche' `python -O` rimuove le asserzioni.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Impossibile inizializzare il client Supabase.",
        )

    results: list = []
    file_hashes: list[str] = []
    cached_flags: list[bool] = []
    errors: list[str] = []

    for uploaded in files:
        filename = uploaded.filename or "unnamed"
        try:
            # SECURITY (FIX C1): streaming read con abort su max_upload_size_mb.
            max_bytes = settings.max_upload_size_mb * 1024 * 1024
            contents = await _read_upload_streaming(uploaded, max_bytes)

            suffix = Path(filename).suffix.lower()
            if suffix not in _ACCEPTED_EXTS:
                errors.append(
                    f"{filename}: estensione non supportata '{suffix}' "
                    f"(accettate: {', '.join(sorted(_ACCEPTED_EXTS))})"
                )
                continue

            file_hash = hashlib.sha256(contents).hexdigest()
            file_hashes.append(file_hash)

            # Idempotency check
            cached_rows: list = []
            try:
                cached_res = (
                    client.table("extractions")
                    .select("data, model")
                    .eq("user_id", user_id)
                    .eq("file_hash", file_hash)
                    .limit(1)
                    .execute()
                )
                cached_rows = cached_res.data or []
            except Exception as e:
                logger.warning("Idempotency check failed for %s: %s", file_hash[:12], e)

            if cached_rows:
                from ...core.models import SpesaMedica
                row = cached_rows[0]
                spesa = SpesaMedica(**row["data"])
                results.append(spesa)
                cached_flags.append(True)
                # SECURITY (FIX M2 audit): mai loggare filename utente in
                # cache hit/cold (potrebbe contenere PII/sanitarie).
                # Logghiamo solo file_hash[:12] (correlation_id sicuro).
                logger.info(
                    "CACHE HIT user=%s hash=%s (model=%s)",
                    user_id, file_hash[:12], row.get("model"),
                )
                continue

            cached_flags.append(False)
            with tempfile.NamedTemporaryFile(
                suffix=suffix if suffix else ".bin",
                delete=False,
            ) as tmp:
                tmp.write(contents)
                tmp_path = Path(tmp.name)

            try:
                spesa = extract_from_file(
                    tmp_path,
                    model=settings.openrouter_model,
                    api_key=settings.openrouter_api_key,
                )
                storage_path = f"receipts/{user_id}/{file_hash}{suffix}"
                try:
                    client.storage.from_(settings.supabase_bucket).upload(
                        path=storage_path,
                        file=contents,
                        file_options={"content-type": _content_type(suffix)},
                    )
                except Exception as e:
                    logger.warning(
                        "Storage upload fallito per %s: %s (estrazione salvata comunque)",
                        file_hash[:12], e,
                    )
                    storage_path = None
                try:
                    client.table("extractions").upsert({
                        "user_id": user_id,
                        "file_hash": file_hash,
                        "filename": filename,
                        "storage_path": storage_path,
                        "data": spesa.to_dict(),
                        "model": settings.openrouter_model,
                    }, on_conflict="user_id,file_hash").execute()
                except Exception as e:
                    logger.warning(
                        "Extraction INSERT fallito per %s: %s",
                        file_hash[:12], e,
                    )
                results.append(spesa)
                # SECURITY (FIX M2 audit): MAI loggare filename utente +
                # categoria_spesa/importo_totale (entrambi PII/sanitarie in chiaro
                # nei log = GDPR cat. speciale art. 9). Logghiamo solo:
                #   - user_id (UUID, opaco)
                #   - file_hash[:12] (correlation_id sicuro)
                logger.info(
                    "OK extract user=%s hash=%s",
                    user_id, file_hash[:12],
                )
            finally:
                tmp_path.unlink(missing_ok=True)

        except ExtractorError as e:
            correlation_id = file_hash[:12] if 'file_hash' in locals() else "nohash"
            # SECURITY (FIX M2 audit): rimuovi filename dal log; lascia
            # solo correlation_id (file_hash[:12]).
            logger.warning(
                "Extraction failed user=%s hash=%s err=%s",
                user_id, correlation_id, e,
            )
            errors.append(f"{filename}: errore estrazione (ref={correlation_id})")
        except Exception as e:
            # SECURITY (FIX M2 audit): rimuovi filename, logga solo errore.
            logger.exception("Unexpected error (user=%s, hash=%s)", user_id, file_hash[:12] if 'file_hash' in locals() else "?")
            errors.append(f"{filename}: errore inatteso {type(e).__name__}")

    if not results:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nessuna estrazione riuscita. Errori: {'; '.join(errors) or 'unknown'}",
        )

    if errors:
        logger.warning(
            "Estrazione parziale: %d/%d file OK. Errori: %s",
            len(results), len(files), "; ".join(errors),
        )

    return ExtractSyncResponse(
        results=results,
        count=len(results),
        file_hashes=file_hashes,
        cached=cached_flags,
        model_used=settings.openrouter_model,
    )


# =============================================================================
# ASYNC (N > max_sync_files)
# =============================================================================
async def _create_async_job(
    files: List[UploadFile],
    user_id: str,
) -> JobPendingResponse:
    """Upload TUTTI i file su Storage, INSERT job, ritorna JobPendingResponse."""
    client = supabase_client.get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Impossibile inizializzare il client Supabase.",
        )

    file_hashes: list[str] = []
    upload_errors: list[str] = []

    for uploaded in files:
        filename = uploaded.filename or "unnamed"
        try:
            # SECURITY (FIX C1): streaming read con abort su max_upload_size_mb.
            max_bytes = settings.max_upload_size_mb * 1024 * 1024
            contents = await _read_upload_streaming(uploaded, max_bytes)
            suffix = Path(filename).suffix.lower()
            if suffix not in _ACCEPTED_EXTS:
                upload_errors.append(f"{filename}: estensione non supportata")
                continue
            file_hash = hashlib.sha256(contents).hexdigest()
            file_hashes.append(file_hash)
            storage_path = f"receipts/{user_id}/{file_hash}{suffix}"
            try:
                client.storage.from_(settings.supabase_bucket).upload(
                    path=storage_path,
                    file=contents,
                    file_options={"content-type": _content_type(suffix)},
                )
            except Exception as e:
                upload_errors.append(f"{filename}: upload fallito ({type(e).__name__})")
                logger.warning("Async upload fallito per %s: %s", file_hash[:12], e)
        except Exception as e:
            upload_errors.append(f"{filename}: errore lettura ({type(e).__name__})")
            # SECURITY (FIX M2 audit): rimuovi filename dal log exception.
            logger.exception("Async read error (user=%s)", user_id)

    if not file_hashes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Nessun file valido per il job. Errori: {'; '.join(upload_errors)}",
        )

    job_id = str(uuid.uuid4())
    try:
        client.table("jobs").insert({
            "id": job_id,
            "user_id": user_id,
            "status": "pending",
            "file_count": len(file_hashes),
            "file_hashes": file_hashes,
            "model": settings.openrouter_model,
        }).execute()
    except Exception as e:
        logger.exception("Job INSERT fallito")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Impossibile creare il job: {type(e).__name__}",
        ) from e

    logger.info(
        "Async job %s creato (user=%s, %d files, %d errori upload)",
        job_id, user_id, len(file_hashes), len(upload_errors),
    )

    return JobPendingResponse(
        job_id=job_id,
        status="pending",
        file_count=len(file_hashes),
        poll_url=f"/api/v1/jobs/{job_id}",
    )


# =============================================================================
# Helpers
# =============================================================================
def _content_type(suffix: str) -> str:
    """Mappa estensione -> Content-Type per Storage upload."""
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix.lower(), "application/octet-stream")
