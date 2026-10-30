"""SPESEMED - Tassonomia centralizzata delle categorie di spesa medica.

Single source of truth per la tassonomia: importata sia da `models.py`
(per il Literal type-check di Pydantic) sia da `prompts.py` (per il system
prompt dell'AI). Evita drift tra schema e prompt.

Come aggiungere una nuova categoria:
    1. Aggiungerla sia in CATEGORIE_SPESA che in CATEGORIE_DESC qui sotto.
    2. Aggiornare il Literal in `models.py`.
    3. L'assert di coerenza in `models.py` catturerà ogni mismatch all'import.

Le categorie rispecchiano le tipologie riconosciute dal 730 italiano
per le detrazioni delle spese sanitarie.
"""
from __future__ import annotations


# =============================================================================
# Categorie ammesse
# =============================================================================
# Importante: la tupla DEVE essere in sync con `CategoriaSpesa` (Literal)
# in models.py. L'assert all'import di models.py verifica la coerenza.
CATEGORIE_SPESA: tuple[str, ...] = (
    "Farmaci",
    "Visita Specialistica",
    "Dispositivo Medico",
    "Esami",
    "Altro",
)


# =============================================================================
# Descrizioni (usate dal prompt AI per guidare la classificazione)
# =============================================================================
CATEGORIE_DESC: dict[str, str] = {
    "Farmaci": (
        "Acquisto di medicinali (anche con ricetta), farmaci da banco, "
        "integratori. Esempio tipico: scontrino parlante di farmacia."
    ),
    "Visita Specialistica": (
        "Parcella di medico (anche dentista, psicologo, nutrizionista, "
        "oculista). Addebito per prestazione professionale."
    ),
    "Dispositivo Medico": (
        "Acquisto di dispositivi medici: occhiali, lenti a contatto, protesi, "
        "apparecchi acustici, sedia a rotelle, plantari."
    ),
    "Esami": (
        "Esami diagnostici: analisi di laboratorio, radiografia, ecografia, "
        "risonanza magnetica, ECG, visita medico sportivo, mammografia."
    ),
    "Altro": (
        "Qualsiasi altra spesa medica non classificabile sopra: ticket SSN, "
        "day hospital, intramoenia, ticket Pronto Soccorso."
    ),
}
