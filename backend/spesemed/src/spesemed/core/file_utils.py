"""SPESEMED - Utility per la gestione di file immagine e PDF di ricevute.

Funzionalità:
    - Apertura di immagini (JPG, PNG, WEBP, BMP) con ridimensionamento automatico
    - Conversione PDF multipagina in lista di immagini (via pdf2image)
    - Codifica base64 JPEG per l'API multimodale di OpenRouter

Note:
    - I modelli Vision gestiscono male immagini sopra ~2048px lato → resize.
    - PDF: richiede `poppler` installato a livello di OS (vedi README).
"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image


logger = logging.getLogger(__name__)


# =============================================================================
# Costanti
# =============================================================================

# Limite sopra il quale l'immagine viene ridimensionata.
# I modelli Vision OpenRouter gestiscono nativamente fino a ~2048px lato;
# immagini più grandi causano degrado delle performance e aumenti di costo.
MAX_DIMENSION = 2048

# Qualità JPEG per la codifica base64 (compromesso qualità/byte).
JPEG_QUALITY = 85

# DPI per la conversione PDF → immagine (200 è uno standard OCR-friendly).
PDF_DPI = 200

SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_PDF_EXT = {".pdf"}


# Messaggio statico riusato nell'errore poppler (per non duplicare la stringa).
_POPPLER_HINT = (
    "Poppler (motore di rendering PDF) non è installato o non è nel PATH.\n"
    "Installalo per il tuo sistema:\n"
    "  • Windows: scarica da https://github.com/oschwartz10612/poppler-windows "
    "e aggiungi la cartella bin/ al PATH.\n"
    "  • macOS:   brew install poppler\n"
    "  • Ubuntu:  sudo apt install poppler-utils\n"
    "Consulta il README di SPESEMED per i dettagli."
)


# =============================================================================
# API pubblica
# =============================================================================

def file_to_images(file_path: str | Path) -> list[Image.Image]:
    """Carica un file di ricevuta e restituisce una lista di immagini PIL.

    Args:
        file_path: percorso al file (PDF o immagine singola).

    Returns:
        Lista di immagini PIL. Per un'immagine singola contiene 1 elemento;
        per un PDF multipagina contiene N elementi (uno per pagina).

    Raises:
        FileNotFoundError: se il file non esiste.
        ValueError: se l'estensione non è supportata.
        RuntimeError: se la conversione PDF fallisce (es. poppler mancante).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {path}")

    suffix = path.suffix.lower()

    if suffix in SUPPORTED_IMAGE_EXT:
        logger.debug("Apertura immagine singola: %s", path.name)
        return [_apri_e_ridimensiona(path)]

    if suffix in SUPPORTED_PDF_EXT:
        logger.debug("Conversione PDF: %s", path.name)
        return _pdf_a_immagini(path)

    raise ValueError(
        f"Formato non supportato: '{suffix}'. "
        f"Accettati: immagini ({', '.join(sorted(SUPPORTED_IMAGE_EXT))}) "
        f"o PDF ({', '.join(sorted(SUPPORTED_PDF_EXT))})."
    )


def image_to_base64(image: Image.Image) -> str:
    """Converte un'immagine PIL in stringa base64 (formato JPEG)."""
    image_normalizzata = _normalizza_modalita(image)
    buffer = io.BytesIO()
    image_normalizzata.save(
        buffer,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
    )
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    logger.debug(
        "Immagine codificata: %dx%d → %d bytes base64",
        image_normalizzata.size[0],
        image_normalizzata.size[1],
        len(encoded),
    )
    return encoded


# =============================================================================
# Helpers interni
# =============================================================================

def _apri_e_ridimensiona(path: Path) -> Image.Image:
    """Apre un'immagine da disco e la ridimensiona se necessario."""
    img = Image.open(path)
    # `Image.open` è lazy: forziamo il caricamento per liberare subito il file.
    img.load()
    return _ridimensiona_se_necessario(img)


def _ridimensiona_se_necessario(image: Image.Image) -> Image.Image:
    """Ridimensiona l'immagine se supera MAX_DIMENSION, mantenendo l'aspect ratio."""
    larghezza, altezza = image.size
    if max(larghezza, altezza) <= MAX_DIMENSION:
        return image
    scala = MAX_DIMENSION / max(larghezza, altezza)
    nuova_larghezza = int(larghezza * scala)
    nuova_altezza = int(altezza * scala)
    logger.debug(
        "Resize immagine: %dx%d → %dx%d",
        larghezza, altezza, nuova_larghezza, nuova_altezza,
    )
    return image.resize((nuova_larghezza, nuova_altezza), Image.Resampling.LANCZOS)


def _normalizza_modalita(image: Image.Image) -> Image.Image:
    """Converte RGBA/LA/P in RGB (richiesto per JPEG).

    Le immagini con canale alpha (PNG trasparenti) vengono composte su sfondo
    bianco, evitando così la perdita di informazioni nei pixel semi-trasparenti.
    """
    if image.mode == "RGB":
        return image

    if image.mode in ("RGBA", "LA"):
        sfondo = Image.new("RGB", image.size, (255, 255, 255))
        sfondo.paste(image, mask=image.split()[-1])
        return sfondo

    if image.mode == "P":
        return image.convert("RGB")

    # Grayscale, CMYK, ecc.
    return image.convert("RGB")


def _pdf_a_immagini(path: Path) -> list[Image.Image]:
    """Converte un PDF in una lista di immagini (una per pagina).

    Solleva un errore amichevole se poppler non è installato nel sistema
    o se la libreria pdf2image manca.
    """
    # Import lazy per non forzare la dipendenza se l'utente usa solo immagini singole.
    try:
        from pdf2image import convert_from_path
    except ImportError as e:
        raise RuntimeError(
            "Libreria 'pdf2image' non installata. Esegui: pip install pdf2image\n"
            f"Dettaglio: {e}"
        ) from e

    logger.info(
        "Conversione PDF '%s' (dpi=%d) in corso... (potrebbe richiedere qualche secondo)",
        path.name, PDF_DPI,
    )
    try:
        immagini = convert_from_path(path, dpi=PDF_DPI)
    except Exception as e:
        # pdf2image solleva errori criptici quando manca poppler; noi li
        # riscriviamo in un messaggio actionable per l'utente finale.
        raise RuntimeError(
            f"Impossibile convertire il PDF '{path.name}'.\n"
            + _POPPLER_HINT
            + f"\nErrore tecnico originale: {type(e).__name__}: {e}"
        ) from e

    return [_ridimensiona_se_necessario(img) for img in immagini]
