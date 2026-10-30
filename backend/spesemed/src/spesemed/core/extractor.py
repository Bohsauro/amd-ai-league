"""SPESEMED - Motore AI per l'estrazione di dati da ricevute mediche italiane.

==============================================================================
FASE 1: BACKEND EXTRACTOR
==============================================================================

Pipeline completa:
    1. Carica la chiave API di OpenRouter da .env (variabile OPENROUTER_API_KEY)
    2. Pre-processa il file (PDF multipagina / JPG / PNG) in immagini ridimensionate
    3. Invia le immagini a un modello Vision economico (default: Gemini 2.5 Flash Lite)
    4. Forza output JSON via `response_format: {type: json_object}`
    5. Valida l'output contro lo schema Pydantic `SpesaMedica`
    6. Restituisce un oggetto SpesaMedica pronto per la serializzazione

USO DA CLI:
    python extractor.py ricevuta_farmacia.pdf
    python extractor.py scontrino.jpg -o risultato.json
    python extractor.py fatture/*.pdf --batch -o batch_risultati.json
    python extractor.py ricevuta.pdf --model anthropic/claude-3-haiku
    python extractor.py --categorie          # mostra la tassonomia

USO DA CODICE:
    from extractor import extract_from_file
    spesa = extract_from_file("scontrino.jpg")
    print(spesa.to_dict())
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from .file_utils import file_to_images, image_to_base64
from .models import SpesaMedica
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .taxonomy import CATEGORIE_SPESA  # single source of truth


# =============================================================================
# Configurazione
# =============================================================================

# SECURITY (audit pen-test): NON chiamare load_dotenv() a module-level.
# Caricarlo qui sovrascrive os.environ per chiunque importi questo modulo
# (FastAPI server, pytest test runner, librerie third-party), causando
# side-effect su test isolation e su altre app nello stesso processo.
# Il caricamento .env spetta SOLO alla CLI main() qui sotto.
#
# API_URL e': hardcoded (pubblico OpenRouter).
# DEFAULT_MODEL/APP_NAME/APP_URL: inizializzati con default sicuri;
# refresh da os.environ in main() CLI dopo load_dotenv() esplicito.
API_URL: str = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL: str = "google/gemini-2.5-flash-lite"
APP_NAME: str = "SPESEMED"
APP_URL: str = "https://spesemed.local"

# Limiti di retry: 3 tentativi totali con backoff esponenziale.
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: float = 2.0

# Timeout per singola richiesta HTTP.
REQUEST_TIMEOUT_SECONDS: float = 60.0

# Token limite per la risposta del modello (campo è piccolo, 1024 bastano).
MAX_TOKENS: int = 1024


logger = logging.getLogger("spesemed.extractor")


# =============================================================================
# Eccezioni
# =============================================================================

class ExtractorError(Exception):
    """Eccezione base per errori del motore AI."""


class MissingAPIKeyError(ExtractorError):
    """Chiave OpenRouter mancante nel file .env."""


# =============================================================================
# Pipeline: file → immagini → messaggi OpenRouter
# =============================================================================

def build_messages(file_path: str | Path) -> list[dict]:
    """Costruisce la lista di messaggi (system + user con immagini inline)."""
    path = Path(file_path)
    images = file_to_images(path)
    if not images:
        raise ExtractorError(f"Nessuna immagine estratta da '{path}'.")

    logger.info("📷 %d immagine/i da analizzare per '%s'", len(images), path.name)

    user_content: list[dict] = [{"type": "text", "text": USER_PROMPT_TEMPLATE}]
    for idx, image in enumerate(images, start=1):
        b64 = image_to_base64(image)
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
        logger.debug(
            "Immagine %d/%d codificata (%dx%d, %.1f KB base64)",
            idx, len(images), image.size[0], image.size[1], len(b64) / 1024,
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# =============================================================================
# Chiamata HTTP a OpenRouter (con retry esponenziale)
# =============================================================================

def call_openrouter(
    messages: list[dict],
    model: str,
    api_key: Optional[str] = None,
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """Chiama l'API OpenRouter /chat/completions con retry per errori transienti.

    Args:
        messages: lista messaggi OpenAI-compatibili.
        model: ID del modello (es. "google/gemini-2.5-flash-lite").
        max_tokens: limite token per la risposta.

    Returns:
        Il JSON crudo della risposta OpenRouter.

    Raises:
        MissingAPIKeyError: se OPENROUTER_API_KEY non è configurata.
        ExtractorError: per errori non recuperabili o superati i retry.
    """
    # Drift-safe: se il chiamante passa api_key esplicitamente (es. FastAPI
    # dependency), usiamo quello; altrimenti fallback all'env (per CLI).
    effective_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not effective_key:
        raise MissingAPIKeyError(
            "OPENROUTER_API_KEY non trovata. Aggiungila al file .env "
            "(vedi .env.example per il template)."
        )

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},  # Forza output JSON
        "temperature": 0.0,                            # Determinismo per OCR
    }
    headers = {
        "Authorization": f"Bearer {effective_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": APP_URL,   # Richiesto da OpenRouter
        "X-Title": APP_NAME,        # Identifica la nostra app nel ranking
    }

    last_error: Optional[Exception] = None
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "🤖 Chiamata OpenRouter %s (tentativo %d/%d)",
                    model, attempt, MAX_RETRIES,
                )
                response = client.post(API_URL, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                # 4xx (tranne 429 rate-limit) → errore del nostro payload, non ritentare.
                if 400 <= status < 500 and status != 429:
                    # SECURITY (FIX M3 audit): mai loggare body della response
                    # OpenRouter (puo' contenere PII dell'immagine OCR).
                    # Logghiamo solo lunghezza del body + status code.
                    body_len = len(e.response.text)
                    logger.error(
                        "❌ Errore client OpenRouter: status=%d, body_len=%d "
                        "(body NON loggato per privacy/GDPR)",
                        status, body_len,
                    )
                    raise ExtractorError(
                        f"Errore OpenRouter ({status}): body_len={body_len}"
                    ) from e

                # 5xx o 429 → ritenta con backoff.
                logger.warning(
                    "⚠️  Errore server/rate-limit OpenRouter (%d), retry in %.1fs...",
                    status, RETRY_BACKOFF_SECONDS * attempt,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)

            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    "⚠️  Errore di rete verso OpenRouter: %s, retry in %.1fs...",
                    e, RETRY_BACKOFF_SECONDS * attempt,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise ExtractorError(
        f"❌ Fallite tutte le {MAX_RETRIES} chiamate a OpenRouter: {last_error}"
    ) from last_error


# =============================================================================
# Validazione risposta
# =============================================================================

def parse_response(raw: dict) -> SpesaMedica:
    """Estrae il contenuto del modello e lo valida come SpesaMedica."""
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ExtractorError("Risposta OpenRouter malformata (struttura dict inattesa).") from e

    # NB: NON logghiamo il contenuto della risposta per motivi di privacy/GDPR:
    # contiene potenzialmente nome paziente, codice fiscale, importi.
    logger.debug("Risposta modello ricevuta: %d caratteri", len(content))

    # 1) Parsing JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ExtractorError(
            f"❌ Il modello ha restituito JSON non valido (lunghezza content={len(content)})."
        ) from e

    # 2) Validazione Pydantic
    try:
        return SpesaMedica(**data)
    except Exception as e:
        raise ExtractorError(
            f"❌ Validazione Pydantic fallita: {e}\nDati ricevuti: {data}"
        ) from e


# =============================================================================
# API pubblica (usata anche da Fase 2/Streamlit)
# =============================================================================

def extract_from_file(
    file_path: str | Path,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
) -> SpesaMedica:
    """Pipeline completa per un singolo file.

    Args:
        file_path: percorso al file della ricevuta (PDF o immagine).
        model: ID del modello OpenRouter.

    Returns:
        Oggetto SpesaMedica validato.

    Raises:
        ExtractorError: per qualsiasi errore della pipeline.
    """
    file_path = Path(file_path)
    # NON loggiamo file_path.name: in modalita' CLI puo' contenere PII
    # (es. "ricevuta_mario_rossi_CF_2024.pdf"). Il path server-side (tempfile
    # nell'uso API) e' comunque opaco e non utile per debug.
    logger.info("🔍 Estrazione avviata (model=%s)", model)

    messages = build_messages(file_path)
    raw_response = call_openrouter(messages, model=model, api_key=api_key)
    return parse_response(raw_response)


# =============================================================================
# CLI
# =============================================================================

def _format_cli_result(result: SpesaMedica) -> str:
    """Serializza il risultato per la stampa su stdout."""
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def setup_logging(verbose: bool = False) -> None:
    """Configura logging root."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Costruisce il parser CLI."""
    parser = argparse.ArgumentParser(
        prog="spesemed-extractor",
        description=(
            "SPESEMED — Estrae dati strutturati da ricevute mediche italiane "
            "usando un modello Vision su OpenRouter."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Uno o più file di ricevute (PDF, JPG, JPEG, PNG, WEBP, BMP).",
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Modello OpenRouter da usare (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--output", "-o",
        help="File JSON dove salvare TUTTI i risultati (default: stdout per file).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Log di debug (più dettagliato).",
    )
    parser.add_argument(
        "--categorie", "-c",
        action="store_true",
        help="Stampa la lista delle categorie di spesa supportate ed esce.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point della CLI. Ritorna exit code (0 = ok).

    SECURITY: carica .env ESPLICITAMENTE qui (NON a module-level) per non
    inquinare os.environ di chi importa la libreria (test runner, server).
    """
    # SECURITY (audit): load_dotenv SOLO nella CLI, scope limitato.
    # main() e' invocato solo da `python extractor.py ...`, MAI da web/import.
    load_dotenv()

    # Refresh costanti module-level dai env (dopo load_dotenv CLI-side)
    global DEFAULT_MODEL, APP_NAME, APP_URL
    DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    APP_NAME = os.getenv("APP_NAME", APP_NAME)
    APP_URL = os.getenv("APP_URL", APP_URL)

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)

    # Modalità info: solo categorie.
    if args.categorie:
        print(">>> Categorie di spesa supportate da SPESEMED:\n")
        for cat in CATEGORIE_SPESA:
            print(f"  • {cat}")
        print(
            f"\nModello di default: {DEFAULT_MODEL}\n"
            "Per usare un modello diverso: --model <id-modello>"
        )
        return 0

    # Senza file: mostra help.
    if not args.files:
        parser.print_help()
        return 2

    results: list[dict] = []
    errors: list[dict] = []

    for file in args.files:
        try:
            result = extract_from_file(file, model=args.model)
            results.append(result.to_dict())
            # Stampa sempre il singolo risultato su stdout.
            print(_format_cli_result(result))
            print("-" * 60)
        except ExtractorError as e:
            logger.error("[%s] %s", file, e)
            errors.append({"file": file, "errore": str(e)})
        except Exception as e:  # noqa: BLE001 - ultimo livello di sicurezza
            logger.exception("[%s] Errore inatteso: %s", file, e)
            errors.append({"file": file, "errore": repr(e)})

    # Se richiesto, salva tutto (successi + errori) in un file JSON cumulativo.
    if args.output:
        output_data = {
            "modello": args.model,
            "totale_file": len(args.files),
            "successi": len(results),
            "errori": len(errors),
            "risultati": results,
            "errori_dettaglio": errors,
        }
        Path(args.output).write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "💾 %d risultati salvati in '%s' (%d errori)",
            len(results), args.output, len(errors),
        )

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
