"""SPESEMED API - Async worker per i job pending (N>3 file).

Il worker gira come `asyncio.create_task` dentro il lifespan dell'app FastAPI:
  - Allo startup: recupera eventuali zombie job bloccati in 'processing'
  - In loop: ogni `worker_poll_interval_seconds`, prova a claimare un job
    via RPC `claim_next_job` (atomica, FOR UPDATE SKIP LOCKED)
  - Se claim riuscito: scarica file da Storage, estrae con extract_from_file,
    salva in tabella `extractions`, marca job come `done`
  - Se errore: exponential backoff con jitter, max `worker_max_attempts` retry

Design choices (vedi thinker-with-files):
  - Race condition: risolta da claim_next_job RPC (FOR UPDATE SKIP LOCKED)
  - Idempotency: UNIQUE (user_id, file_hash) su extractions = stessa query
    di SELECT prima di processare
  - Error handling: exponential backoff + jitter per evitare thundering herd
  - Zombie recovery: reset_zombie_jobs al boot + check periodico
  - Sync I/O wrappato in asyncio.to_thread (supabase-py e' bloccante)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..core.extractor import ExtractorError, extract_from_file
from .config import settings
from .supabase_client import get_supabase_client, is_supabase_configured

logger = logging.getLogger(__name__)


# Intervallo di reset zombie (in numero di poll). Ogni ~5 minuti se poll=2s.
_ZOMBIE_RESET_EVERY_N_POLLS = 150


class JobWorker:
    """Background worker che processa i job pending dalla tabella `jobs`.

    Lifecycle:
        worker = JobWorker()
        await worker.start()       # spawna l'asyncio.Task
        ...
        await worker.stop()        # ferma gracefully
    """

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._poll_counter: int = 0

    async def start(self) -> None:
        """Avvia il worker (no-op se Supabase non configurato)."""
        if not is_supabase_configured():
            logger.warning("JobWorker: Supabase non configurato, worker disabilitato")
            return
        # Crea event nel loop corrente
        self._stop_event = asyncio.Event()
        self._poll_counter = 0
        # Reset zombie all'avvio (recupera job orfani da run precedenti)
        try:
            reset_count = await asyncio.to_thread(self._reset_zombie_jobs)
            if reset_count > 0:
                logger.info("JobWorker: %d zombie job resettati a 'pending'", reset_count)
        except Exception as e:
            logger.warning("JobWorker: reset zombie fallito al boot: %s", e)
        # Spawna la task
        self._task = asyncio.create_task(self._poll_loop(), name="spesemed-job-worker")
        logger.info(
            "JobWorker started (poll=%.1fs, max_attempts=%d, zombie_timeout=%dm)",
            settings.worker_poll_interval_seconds,
            settings.worker_max_attempts,
            settings.worker_zombie_timeout_minutes,
        )

    async def stop(self) -> None:
        """Ferma il worker gracefully (attende fine poll corrente)."""
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._stop_event = None
        logger.info("JobWorker stopped")

    # -------------------------------------------------------------------------
    # Loop principale
    # -------------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        """Loop infinito: poll -> claim -> process -> pausa."""
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                processed = await asyncio.to_thread(self._claim_and_process_one)
            except Exception as e:
                logger.exception("JobWorker poll error: %s", e)
                processed = False
            # Ogni N poll, controlla zombie (in aggiunta al reset al boot)
            self._poll_counter += 1
            if self._poll_counter % _ZOMBIE_RESET_EVERY_N_POLLS == 0:
                try:
                    await asyncio.to_thread(self._reset_zombie_jobs)
                except Exception as e:
                    logger.warning("JobWorker: zombie reset periodico fallito: %s", e)
            # Se non c'erano job, aspetta l'intervallo (interrupted by stop)
            if not processed:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=settings.worker_poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

    # -------------------------------------------------------------------------
    # SYNC (chiamate da asyncio.to_thread)
    # -------------------------------------------------------------------------
    def _reset_zombie_jobs(self) -> int:
        """Chiama la RPC reset_zombie_jobs. Ritorna numero di job resettati."""
        client = get_supabase_client()
        if not client:
            return 0
        try:
            res = client.rpc(
                "reset_zombie_jobs",
                {"p_timeout_minutes": settings.worker_zombie_timeout_minutes},
            ).execute()
            return int(res.data or 0)
        except Exception as e:
            logger.warning("reset_zombie_jobs RPC fallita: %s", e)
            return 0

    def _claim_and_process_one(self) -> bool:
        """Claim un job via RPC, processalo. Ritorna True se ha processato."""
        client = get_supabase_client()
        if not client:
            return False
        # Claim via RPC
        try:
            res = client.rpc(
                "claim_next_job",
                {"p_worker_id": f"worker-{uuid.uuid4().hex[:8]}"},
            ).execute()
        except Exception as e:
            logger.warning("claim_next_job RPC fallita: %s", e)
            return False
        if not res.data:
            return False
        job = res.data[0]
        job_id = job["id"]
        user_id = job["user_id"]
        file_hashes = job.get("file_hashes") or []
        model = job.get("model") or settings.openrouter_model
        attempts = job.get("attempts", 1)
        # SECURITY (FIX M2 audit): user_id e' UUID (no PII direttamente),
        # ma evitiamo di loggarlo per limitare cardinality/log noise.
        logger.info(
            "JobWorker: processing job %s (user=%s, %d files, attempt %d/%d)",
            job_id, user_id[:8] + "...", len(file_hashes), attempts, settings.worker_max_attempts,
        )
        try:
            self._process_job(client, user_id, job_id, file_hashes, model)
            # Mark done
            client.table("jobs").update({
                "status": "done",
                "last_error": None,
            }).eq("id", job_id).execute()
            logger.info("JobWorker: job %s done", job_id)
            return True
        except Exception as e:
            self._mark_job_failed(client, job_id, attempts, e)
            return True  # abbiamo processato (fallito), non riprovare subito

    def _process_job(
        self,
        client,
        user_id: str,
        job_id: str,
        file_hashes: list[str],
        model: str,
    ) -> None:
        """Scarica i file da Storage, estrae, salva in extractions."""
        for file_hash in file_hashes:
            # 1. Scarica da Storage in tempfile (risolvendo l'estensione del file)
            res = None
            storage_path = None
            for ext in (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ""):
                candidate_path = f"receipts/{user_id}/{file_hash}{ext}"
                try:
                    res = client.storage.from_(settings.supabase_bucket).download(candidate_path)
                    if res is not None:
                        storage_path = candidate_path
                        break
                except Exception:
                    continue

            if res is None or storage_path is None:
                raise FileNotFoundError(
                    f"File per hash {file_hash[:12]} non trovato in Storage receipts/{user_id}/"
                )

            suffix = Path(storage_path).suffix or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                # Scrivi i bytes scaricati
                tmp_path.write_bytes(res)

                # 2. Verifica hash
                actual_hash = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
                if actual_hash != file_hash:
                    raise ValueError(
                        f"Hash mismatch: atteso {file_hash[:12]}, trovato {actual_hash[:12]}"
                    )
                # 3. Estrai
                spesa = extract_from_file(
                    tmp_path,
                    model=model,
                    api_key=settings.openrouter_api_key,
                )
                # 4. UPSERT in extractions (idempotency: UNIQUE user_id+file_hash)
                client.table("extractions").upsert({
                    "user_id": user_id,
                    "job_id": job_id,
                    "file_hash": file_hash,
                    "storage_path": storage_path,
                    "data": spesa.to_dict(),
                    "model": model,
                }, on_conflict="user_id,file_hash").execute()
                # SECURITY (FIX M2 audit): MAI loggare categoria_spesa/importo_totale
                # (entrambi dato sanitario in chiaro).
                logger.info(
                    "JobWorker: file %s done (extraction successful)",
                    file_hash[:12],
                )
            finally:
                # GDPR: sempre cleanup
                tmp_path.unlink(missing_ok=True)

    def _mark_job_failed(self, client, job_id: str, attempts: int, error: Exception) -> None:
        """Marca il job come failed o lo rimette in pending con backoff+jitter."""
        err_str = f"{type(error).__name__}: {error}"[:500]
        # SECURITY (FIX M2): err_str contiene tipo+msg dell'eccezione;
        # NON loggare path del file (gia' file_hash[:12], OK).
        if attempts >= settings.worker_max_attempts:
            # Max retries raggiunti: failed definitivo
            client.table("jobs").update({
                "status": "failed",
                "last_error": err_str,
            }).eq("id", job_id).execute()
            logger.error(
                "JobWorker: job %s FAILED dopo %d tentativi: %s",
                job_id, attempts, err_str,
            )
        else:
            # Exponential backoff con jitter per evitare thundering herd
            backoff = (2 ** attempts) + random.uniform(0, 1)
            # NB: postgrest-py invia il payload come JSON, NON come SQL raw.
            # In precedenza si usava la stringa SQL "now() + interval '...'"
            # che PostgREST salva come letterale (non valuta) -> colonna
            # timestamptz invalida -> claim_next_job non rispettava il backoff.
            # Fix: calcoliamo il timestamp lato Python in ISO 8601 UTC.
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
            client.table("jobs").update({
                "status": "pending",
                "last_error": err_str,
                "next_retry_at": next_retry_at.isoformat(),
            }).eq("id", job_id).execute()
            logger.warning(
                "JobWorker: job %s fallito (attempt %d/%d), retry in %.1fs: %s",
                job_id, attempts, settings.worker_max_attempts, backoff, err_str,
            )
