"""SPESEMED - Export Excel/ZIP per il commercialista (Fase 4B).

==============================================================================
FASE 4B: EXPORT
==============================================================================

Genera gli artefatti che chiudono il ciclo d'uso per il commercialista:

    1. **Excel riepilogativo** (`.xlsx`): un foglio "Riepilogo" con tutte le
       spese (una riga per ricevuta, colonne: data, esercente, importo,
       categoria, CF) + un foglio "Per Categoria" con i totali per categoria
       (le stesse del 730). Formattazione openpyxl: header bold, freeze panes,
       colonne autosize, totali evidenziati.
    2. **ZIP per commercialista**: Excel + copie delle ricevute originali
       rinominate con pattern `YYYY-MM-DD_esercente_importoCAT.ext`
       (es. `2024-03-15_Farmacia-Centrale_45.50EUR_FAR.pdf`) — pronte da
       allegare al 730.

USO DA CLI:
    python -m spesemed.core.exporter spese.json -o export.xlsx
    python -m spesemed.core.exporter spese.json -o export.zip --receipts-dir ./ricevute
    python -m spesemed.core.exporter spese.json -o export.zip --receipts-dir ./ricevute --no-excel

USO DA CODICE:
    from spesemed.core.exporter import export_excel, export_zip
    export_excel(spese, Path("export.xlsx"))
    export_zip(spese, {filename: bytes}, Path("export.zip"))

INPUT JSON (spese.json): array di oggetti SpesaMedica come prodotti da
`extract_from_file` / `POST /api/v1/extract` (stessa struttura Pydantic).
==============================================================================
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import SpesaMedica
from .taxonomy import CATEGORIE_SPESA

logger = logging.getLogger("spesemed.exporter")


# =============================================================================
# Codici categoria (per il pattern filename importoCAT)
# =============================================================================
_CATEGORIA_CODES: Dict[str, str] = {
    "Farmaci": "FAR",
    "Visita Specialistica": "VIS",
    "Dispositivo Medico": "DIS",
    "Esami": "ESA",
    "Altro": "ALT",
}

_DEFAULT_EXCEL_FILENAME = "riepilogo_spese.xlsx"
_DEFAULT_EXPORT_FILENAME = "spesemed_export.zip"

# Nome folder dentro lo ZIP per le ricevute rinumerate.
_ZIP_RECEIPTS_DIR = "ricevute"


# =============================================================================
# Helpers
# =============================================================================

def categoria_code(categoria: str) -> str:
    """Ritorna il codice breve della categoria (FAR, VIS, ...). Fallback ALT."""
    return _CATEGORIA_CODES.get(categoria, "ALT")


def _sanitize_esercente(esercente: Optional[str]) -> str:
    """Sanitizza il nome dell'esercente per filename: solo [A-Za-z0-9 ._-]."""
    if not esercente:
        return "sconosciuto"
    cleaned = re.sub(r"[^A-Za-z0-9 ._\-]+", "-", esercente.strip())
    cleaned = re.sub(r"[ _\-]+", "-", cleaned).strip("-")
    # Rimuovi punti/trattini finali (es. "& C." -> "C", "SRL." -> "SRL").
    cleaned = cleaned.rstrip(".").rstrip("-")
    return cleaned or "sconosciuto"


def _sanitize_data(data_spesa: Optional[str]) -> str:
    """Ritorna la data in YYYY-MM-DD oppure 'senza-data' se illeggibile."""
    if data_spesa and re.match(r"^\d{4}-\d{2}-\d{2}$", data_spesa):
        return data_spesa
    return "senza-data"


def _format_importo(importo: Optional[float]) -> str:
    """Importo formattato come 45.50EUR (pattern importoCAT)."""
    if importo is None:
        return "0.00EUR"
    return f"{importo:.2f}EUR"


def build_receipt_filename(
    spesa: SpesaMedica,
    original_suffix: str = ".pdf",
) -> str:
    """Costruisce il filename rinominato per la ricevuta.

    Pattern: ``YYYY-MM-DD_esercente_importoCAT.ext``
    Esempio: ``2024-03-15_Farmacia-Centrale_45.50EUR_FAR.pdf``

    Args:
        spesa: la spesa estratta (usa data, esercente, importo, categoria).
        original_suffix: estensione originale del file (es. ".pdf", ".jpg").

    Returns:
        Filename sicuro (solo [A-Za-z0-9 ._()-]).
    """
    suffix = (original_suffix or ".pdf").lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return (
        f"{_sanitize_data(spesa.data_spesa)}_"
        f"{_sanitize_esercente(spesa.esercente)}_"
        f"{_format_importo(spesa.importo_totale)}_"
        f"{categoria_code(spesa.categoria_spesa)}"
        f"{suffix}"
    )


def _sanitize_cell_value(val: Optional[str]) -> str:
    """Sanitizza valori stringa per celle Excel evitando Formula Injection (CSV/XLSX Injection).

    Se una stringa non vuota inizia con =, +, -, @, \\t, o \\r, viene prefissata con un
    apostrofo ('), impedendo a Microsoft Excel di eseguirla come formula.
    """
    if not val:
        return ""
    val_str = str(val)
    if val_str.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{val_str}"
    return val_str


# =============================================================================
# Excel (openpyxl)
# =============================================================================

def _build_workbook(spese_list: List[SpesaMedica]):
    """Costruisce il Workbook condiviso (fogli 'Riepilogo' + 'Per Categoria').

    Unico punto di costruzione dell'Excel: sia l'export standalone
    (`export_excel`) sia l'embedding nello ZIP (`build_excel_bytes`) usano
    questo builder, così i due artefatti restano identici e non possono
    divergere (stesso header, stessi colori per categoria, stesso totale).
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as e:  # pragma: no cover - dipendenza opzionale
        raise ImportError(
            "openpyxl non installato. Eseguire: pip install -e \".[dev]\" "
            "oppure pip install openpyxl"
        ) from e

    wb = Workbook()

    # ── Foglio 1: Riepilogo ────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Riepilogo"
    headers = ["Data", "Esercente", "Importo (EUR)", "Categoria", "Codice Fiscale"]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="00796B", end_color="00796B", fill_type="solid")
    category_fills = {
        "Farmaci": PatternFill(start_color="C8E6C9", end_color="C8E6C9", fill_type="solid"),
        "Visita Specialistica": PatternFill(start_color="BBDEFB", end_color="BBDEFB", fill_type="solid"),
        "Dispositivo Medico": PatternFill(start_color="FFF9C4", end_color="FFF9C4", fill_type="solid"),
        "Esami": PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid"),
        "Altro": PatternFill(start_color="ECEFF1", end_color="ECEFF1", fill_type="solid"),
    }
    total_font = Font(bold=True)

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A2"

    grand_total = 0.0
    for row_idx, spesa in enumerate(spese_list, start=2):
        ws.cell(row=row_idx, column=1, value=_sanitize_cell_value(spesa.data_spesa))
        ws.cell(row=row_idx, column=2, value=_sanitize_cell_value(spesa.esercente))
        ws.cell(row=row_idx, column=3, value=spesa.importo_totale or 0.0)
        ws.cell(row=row_idx, column=4, value=_sanitize_cell_value(spesa.categoria_spesa))
        ws.cell(row=row_idx, column=5, value=_sanitize_cell_value(spesa.codice_fiscale_paziente))
        # Tinta di riga per categoria (leggibilità a colpo d'occhio).
        fill = category_fills.get(spesa.categoria_spesa)
        if fill:
            for col_idx in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col_idx).fill = fill
        grand_total += spesa.importo_totale or 0.0

    # Riga totale.
    total_row = len(spese_list) + 2
    ws.cell(row=total_row, column=2, value="TOTALE")
    ws.cell(row=total_row, column=3, value=round(grand_total, 2))
    for col_idx in range(1, len(headers) + 1):
        ws.cell(row=total_row, column=col_idx).font = total_font

    # Autosize colonne (stima ragionevole per leggibilità).
    for col_idx in range(1, len(headers) + 1):
        max_len = len(str(headers[col_idx - 1]))
        for row_idx in range(2, total_row + 1):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 48)

    # ── Foglio 2: Per Categoria ────────────────────────────────────────────
    ws_cat = wb.create_sheet("Per Categoria")
    ws_cat.cell(row=1, column=1, value="Categoria").font = header_font
    ws_cat.cell(row=1, column=2, value="Totale (EUR)").font = header_font
    ws_cat.cell(row=1, column=3, value="Numero spese").font = header_font
    for col_idx in range(1, 4):
        ws_cat.cell(row=1, column=col_idx).fill = header_fill
    ws_cat.freeze_panes = "A2"

    totals: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for spesa in spese_list:
        cat = spesa.categoria_spesa
        totals[cat] = totals.get(cat, 0.0) + (spesa.importo_totale or 0.0)
        counts[cat] = counts.get(cat, 0) + 1

    cat_row = 2
    for cat in CATEGORIE_SPESA:
        if cat not in totals:
            continue
        ws_cat.cell(row=cat_row, column=1, value=cat)
        ws_cat.cell(row=cat_row, column=2, value=round(totals[cat], 2))
        ws_cat.cell(row=cat_row, column=3, value=counts[cat])
        fill = category_fills.get(cat)
        if fill:
            for col_idx in range(1, 4):
                ws_cat.cell(row=cat_row, column=col_idx).fill = fill
        cat_row += 1

    # Totale generale nel foglio categorie.
    ws_cat.cell(row=cat_row, column=1, value="TOTALE").font = total_font
    ws_cat.cell(row=cat_row, column=2, value=round(grand_total, 2)).font = total_font
    ws_cat.cell(row=cat_row, column=3, value=len(spese_list)).font = total_font
    ws_cat.column_dimensions["A"].width = 24
    ws_cat.column_dimensions["B"].width = 14
    ws_cat.column_dimensions["C"].width = 14

    return wb


def export_excel(
    spese: Iterable[SpesaMedica],
    output_path: Path,
) -> Path:
    """Genera l'Excel riepilogativo con fogli 'Riepilogo' + 'Per Categoria'.

    Args:
        spese: iterabile di SpesaMedica da esportare.
        output_path: percorso del file .xlsx da scrivere.

    Returns:
        Il Path del file generato (== output_path).
    """
    spese_list = list(spese)
    wb = _build_workbook(spese_list)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    grand_total = sum((s.importo_totale or 0.0) for s in spese_list)
    logger.info(
        "Excel generato: %s (%d spese, totale %.2f EUR)",
        output_path, len(spese_list), grand_total,
    )
    return output_path


# =============================================================================
# ZIP (Excel + ricevute rinominate)
# =============================================================================

def export_zip(
    spese: Iterable[SpesaMedica],
    receipts: Dict[str, bytes],
    output_path: Path,
    excel_path: Optional[Path] = None,
    include_excel: bool = True,
) -> Path:
    """Genera lo ZIP per il commercialista: Excel + ricevute rinominate.

    Args:
        spese: iterabile di SpesaMedica (allineato per indice con receipts).
        receipts: mappa {filename_originale: bytes} delle ricevute. Le chiavi
            devono corrispondere all'ordine/indice delle spese passate in
            `spese` per un naming corretto (si usa il filename originale
            solo per l'estensione; il nome finale deriva dai campi SpesaMedica).
        output_path: percorso del file .zip da scrivere.
        excel_path: opzionale, percorso di un Excel già generato da includere.
            Se None, viene generato in-memory dentro lo ZIP.
        include_excel: se False, lo ZIP contiene solo le ricevute (--no-excel).

    Returns:
        Il Path del file ZIP generato (== output_path).
    """
    spese_list = list(spese)
    receipt_items = list(receipts.items())

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    zip_bytes = build_zip_bytes(
        spese_list,
        receipts,
        excel_path=excel_path,
        include_excel=include_excel,
    )
    output_path.write_bytes(zip_bytes)
    n_files = len(receipt_items) + (1 if include_excel else 0)
    logger.info("ZIP generato: %s (%d file)", output_path, n_files)
    return output_path


def build_zip_bytes(
    spese: Iterable[SpesaMedica],
    receipts: Dict[str, bytes],
    excel_path: Optional[Path] = None,
    excel_bytes: Optional[bytes] = None,
    include_excel: bool = True,
) -> bytes:
    """Genera lo ZIP (in-memory) per API/download: Excel + ricevute rinominate.

    Args:
        spese: iterabile di SpesaMedica (allineato per indice con receipts).
        receipts: mappa {filename_originale: bytes}. Il naming finale deriva
            dai campi SpesaMedica; il filename originale serve solo per
            l'estensione.
        excel_path: percorso Excel già generato da includere (alternativa a
            excel_bytes).
        excel_bytes: bytes Excel già generati (build_excel_bytes). Se entrambi
            None, l'Excel viene generato in-memory dalle spese.
        include_excel: se False, lo ZIP contiene solo le ricevute (--no-excel).

    Returns:
        I bytes del file ZIP.
    """
    spese_list = list(spese)
    receipt_items = list(receipts.items())
    if len(spese_list) != len(receipt_items):
        logger.warning(
            "Mismatch spese (%d) vs receipts (%d): lo ZIP userà il naming "
            "posizionale e i file senza corrispondenza verranno inclusi con "
            "il nome originale sanitizzato.",
            len(spese_list), len(receipt_items),
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) Excel riepilogativo (salta se include_excel=False).
        if include_excel:
            if excel_path is not None:
                zf.write(excel_path, arcname=excel_path.name)
            elif excel_bytes is not None:
                zf.writestr(_DEFAULT_EXCEL_FILENAME, excel_bytes)
            else:
                zf.writestr(_DEFAULT_EXCEL_FILENAME, build_excel_bytes(spese_list))

        # 2) Ricevute rinominate (dedup: 2 ricevute identiche della stessa
        #    farmacia nello stesso giorno → suffisso _2, _3, ...).
        used_names: set[str] = set()
        for idx, (original_name, content) in enumerate(receipt_items):
            suffix = Path(original_name or "").suffix or ".bin"
            spesa = spese_list[idx] if idx < len(spese_list) else None
            if spesa is not None:
                new_name = build_receipt_filename(spesa, suffix)
            else:
                new_name = f"ricevuta-{idx + 1}{suffix}"
            new_name = _dedupe_name(new_name, used_names)
            used_names.add(new_name)
            zf.writestr(f"{_ZIP_RECEIPTS_DIR}/{new_name}", content)

    return buf.getvalue()


def _dedupe_name(name: str, used: set[str]) -> str:
    """Rende univoco un filename ZIP aggiungendo `_2`, `_3`, ... in caso di collisione.

    Scenario reale: due ricevute della stessa farmacia nello stesso giorno con
    lo stesso importo producono lo stesso nome — nel ZIP finirebbero due entry
    duplicate. Con il suffisso numerico ogni entry resta univoca e tracciabile.
    """
    if name not in used:
        return name
    # rpartition: difensivo anche se il nome non avesse estensione
    # (in tal caso dot e' vuoto e il suffisso numerico viene appeso in coda).
    stem, dot, ext = name.rpartition(".")
    counter = 2
    candidate = f"{stem}_{counter}{dot}{ext}" if dot else f"{name}_{counter}"
    while candidate in used:
        counter += 1
        candidate = f"{stem}_{counter}{dot}{ext}" if dot else f"{name}_{counter}"
    return candidate


def build_excel_bytes(spese: List[SpesaMedica]) -> bytes:
    """Genera l'Excel in-memory (BytesIO) per includerlo nello ZIP.

    Usa lo stesso `_build_workbook` di `export_excel`: i fogli generati
    (Riepilogo + Per Categoria) sono identici all'export standalone.
    """
    wb = _build_workbook(list(spese))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# =============================================================================
# CLI
# =============================================================================

def _load_spese(path: Path) -> List[SpesaMedica]:
    """Carica spese.json (array di SpesaMedica) e valida con Pydantic."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # Tolleranza: accetta anche {"results": [...]} (output di /extract).
        data = data.get("results", data)
    if not isinstance(data, list):
        raise ValueError("Input JSON deve essere un array di spese (o {results: [...]}).")
    spese = [SpesaMedica(**item) if isinstance(item, dict) else item for item in data]
    return spese


def build_arg_parser() -> argparse.ArgumentParser:
    """Parser CLI per l'export."""
    parser = argparse.ArgumentParser(
        prog="spesemed-exporter",
        description=(
            "SPESEMED — Genera Excel riepilogativo e ZIP per il commercialista "
            "dalle spese mediche estratte."
        ),
    )
    parser.add_argument("input", help="File JSON con le spese (array SpesaMedica).")
    parser.add_argument("-o", "--output", default=_DEFAULT_EXPORT_FILENAME,
                        help=f"Percorso output (default: {_DEFAULT_EXPORT_FILENAME}). "
                             "Estensione .xlsx = solo Excel, .zip = ZIP completo.")
    parser.add_argument("--receipts-dir", default=None,
                        help="Cartella con le ricevute originali da rinominare nello ZIP.")
    parser.add_argument("--no-excel", action="store_true",
                        help="Escludi l'Excel dallo ZIP (solo ricevute rinominate).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log di debug.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point CLI. Ritorna exit code (0 = ok)."""
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        spese = _load_spese(Path(args.input))
        if not spese:
            logger.error("Nessuna spesa trovata nel file input.")
            return 1

        output = Path(args.output)
        is_zip = output.suffix.lower() == ".zip"

        if is_zip:
            receipts: Dict[str, bytes] = {}
            if args.receipts_dir:
                receipts_dir = Path(args.receipts_dir)
                if not receipts_dir.is_dir():
                    logger.error("--receipts-dir '%s' non è una cartella valida.", args.receipts_dir)
                    return 1
                for f in sorted(receipts_dir.iterdir()):
                    if f.is_file():
                        receipts[f.name] = f.read_bytes()
            elif not args.no_excel:
                logger.warning(
                    "--receipts-dir non indicato: lo ZIP conterrà solo l'Excel "
                    "(usa --no-excel per escluderlo)."
                )

            # Guard unificato: --no-excel con zero ricevute (cartella assente
            # o vuota) produrrebbe uno ZIP vuoto → errore chiaro, exit 1.
            if args.no_excel and not receipts:
                logger.error(
                    "--no-excel ma nessuna ricevuta disponibile "
                    "(--receipts-dir assente o vuoto): lo ZIP sarebbe vuoto."
                )
                return 1

            export_zip(
                spese,
                receipts,
                output,
                excel_path=None,
                include_excel=not args.no_excel,
            )
        else:
            export_excel(spese, output)

        logger.info("✅ Export completato: %s", output.resolve())
        return 0
    except Exception as e:  # noqa: BLE001 - CLI: ultimo livello di sicurezza
        logger.exception("Export fallito: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
