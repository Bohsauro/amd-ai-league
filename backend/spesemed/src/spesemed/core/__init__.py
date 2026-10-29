"""SPESEMED core - Motore AI per l'estrazione di dati da ricevute mediche.

Questo package contiene la logica di business riutilizzabile (non legata
all'API HTTP). È importabile da qualunque frontend (FastAPI, CLI, GUI).

Moduli:
    extractor: pipeline completa file → OpenRouter → SpesaMedica
    models: schema Pydantic + validatori tolerant
    file_utils: PDF/imagine → base64 per modelli Vision
    prompts: system prompt italiano con tassonomia categorie
    taxonomy: single source of truth per le categorie di spesa
"""
from .extractor import ExtractorError, MissingAPIKeyError, extract_from_file
from .models import SpesaMedica
from .taxonomy import CATEGORIE_DESC, CATEGORIE_SPESA

__all__ = [
    "extract_from_file",
    "ExtractorError",
    "MissingAPIKeyError",
    "SpesaMedica",
    "CATEGORIE_SPESA",
    "CATEGORIE_DESC",
]
