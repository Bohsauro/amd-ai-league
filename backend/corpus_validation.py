"""Validazione del corpus: unica fonte di verita' per gate e test.

Prima questa logica viveva solo dentro `bin/verify`; ora sta qui e viene usata
sia dal gate sia da `tests/test_corpus.py`, cosi' le due copie non possono
divergere. Nessuna dipendenza esterna: solo stdlib.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FAKE_DOMAIN = re.compile(
    r"(example\.(com|org|net)|acme\.|\.example|lorem|placeholder|test\.local)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CASE_ID_RE = re.compile(r"^FC-\d{2,3}$")
PUBLISHER_TYPES = {"official", "press", "report", "blog", "noise"}
VERDICTS = {"correct", "partial", "wrong", "noise"}

MIN_SOURCES = 4
CONTENT_MIN = 200
CONTENT_MAX = 1200


@dataclass
class CorpusReport:
    n_cases: int = 0
    ids: list[str] = field(default_factory=list)
    case_id_problems: list[str] = field(default_factory=list)
    fake_urls: list[str] = field(default_factory=list)
    thin_cases: list[str] = field(default_factory=list)
    source_problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.case_id_problems
            or self.fake_urls
            or self.thin_cases
            or self.source_problems
        )

    @property
    def problems(self) -> list[str]:
        return (
            self.case_id_problems
            + self.fake_urls
            + self.thin_cases
            + self.source_problems
        )

    def summary(self) -> str:
        if self.ok:
            return f"{self.n_cases} casi validi"
        return f"{len(self.problems)} problemi: " + "; ".join(self.problems[:5])


def load_corpus_cases(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("cases", "corpus", "items", "data"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if "sources" in raw:
            return [raw]
    raise ValueError("corpus.json: formato non riconosciuto (atteso oggetto o lista di casi)")


def expected_case_ids(count: int) -> list[str]:
    return [f"FC-{index:02d}" for index in range(1, count + 1)]


def validate_corpus(
    cases: list[dict[str, Any]],
    *,
    expected_count: int | None = None,
    min_sources: int = MIN_SOURCES,
    content_min: int = CONTENT_MIN,
    content_max: int = CONTENT_MAX,
) -> CorpusReport:
    report = CorpusReport(n_cases=len(cases), ids=[str(case.get("id", "")) for case in cases])

    if expected_count is not None:
        expected = expected_case_ids(expected_count)
        if sorted(report.ids) != expected:
            report.case_id_problems.append(
                f"attesi {expected_count} casi {expected[0]}..{expected[-1]}, trovati: {report.ids}"
            )
    elif len(set(report.ids)) != len(report.ids):
        report.case_id_problems.append(f"id di caso duplicati: {report.ids}")
    for case_id in report.ids:
        if not CASE_ID_RE.match(case_id):
            report.case_id_problems.append(f"id di caso non conforme: {case_id!r}")

    for case in cases:
        case_id = str(case.get("id", "?"))
        for key in ("query", "subject", "claim", "truth", "truth_url"):
            if not str(case.get(key) or "").strip():
                report.source_problems.append(f"{case_id}.{key} vuoto")
        truth_url = str(case.get("truth_url") or "")
        if truth_url and not truth_url.startswith("http"):
            report.source_problems.append(f"{case_id}.truth_url non assoluto")
        if truth_url and FAKE_DOMAIN.search(truth_url):
            report.fake_urls.append(f"{case_id}.truth_url")

        sources = case.get("sources") or []
        if not isinstance(sources, list):
            report.source_problems.append(f"{case_id}.sources non e' una lista")
            continue
        if len(sources) < min_sources:
            report.thin_cases.append(f"{case_id}: {len(sources)} sorgenti")

        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, dict):
                report.source_problems.append(f"{case_id}: sorgente non oggetto")
                continue
            source_id = str(source.get("id", ""))
            if not re.match(rf"^{re.escape(case_id)}-S\d+$", source_id):
                report.source_problems.append(f"{case_id} id sorgente non conforme: {source_id!r}")
            if source_id in seen:
                report.source_problems.append(f"{case_id} id duplicato: {source_id}")
            seen.add(source_id)
            if source.get("publisher_type") not in PUBLISHER_TYPES:
                report.source_problems.append(
                    f"{case_id}/{source_id} publisher_type {source.get('publisher_type')!r}"
                )
            if not DATE_RE.match(str(source.get("date", ""))):
                report.source_problems.append(f"{case_id}/{source_id} date {source.get('date')!r}")
            if not str(source.get("title") or "").strip():
                report.source_problems.append(f"{case_id}/{source_id} title vuoto")
            if not str(source.get("source_name") or "").strip():
                report.source_problems.append(f"{case_id}/{source_id} source_name vuoto")
            verdict = source.get("verdict_in_corpus")
            if verdict is not None and verdict not in VERDICTS:
                report.source_problems.append(f"{case_id}/{source_id} verdict {verdict!r}")
            content = str(source.get("content") or "")
            if not (content_min <= len(content) <= content_max):
                report.source_problems.append(
                    f"{case_id}/{source_id} content {len(content)} char "
                    f"({content_min}-{content_max})"
                )
            url = str(source.get("source_url") or "")
            if source.get("publisher_type") != "noise":
                if not url.startswith("http"):
                    report.source_problems.append(f"{case_id}/{source_id} source_url non assoluto")
                elif FAKE_DOMAIN.search(url):
                    report.fake_urls.append(f"{case_id}/{source_id}")

    return report


def validate_corpus_file(path: str | Path, **kwargs: Any) -> CorpusReport:
    return validate_corpus(load_corpus_cases(path), **kwargs)
