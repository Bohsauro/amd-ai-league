from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent / "corpus.json"

PUBLISHER_TYPE_MAP = {
    "official": "official",
    "primary": "official",
    "filing": "official",
    "sec": "official",
    "regulator": "official",
    "government": "official",
    "transcript": "official",
    "press": "press",
    "press_release": "press",
    "press-release": "press",
    "news": "press",
    "newswire": "press",
    "report": "report",
    "research": "report",
    "analyst": "report",
    "blog": "blog",
    "opinion": "blog",
    "social": "blog",
    "noise": "noise",
    "spam": "noise",
    "seo": "noise",
    "contentfarm": "noise",
    "content-farm": "noise",
}


def normalize_publisher_type(value: str) -> str:
    return PUBLISHER_TYPE_MAP.get((value or "").lower(), "blog")


@dataclass
class Snippet:
    id: str
    source_url: str
    source_name: str
    publisher_type: str
    date: str
    content: str
    title: str
    case_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("extra", None)
        return data


def _corpus_cases(raw: Any) -> list[dict[str, Any]]:
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


def load_corpus(path: str | Path | None = None) -> list[dict[str, Any]]:
    corpus_path = Path(path) if path else DEFAULT_CORPUS_PATH
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"corpus non trovato: {corpus_path}. BOH-4 deve produrre backend/corpus.json "
            "oppure passa --corpus <path>."
        )
    with corpus_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return _corpus_cases(raw)


def _case_id(case: dict[str, Any], index: int) -> str:
    return str(case.get("id") or case.get("case_id") or f"CASE-{index + 1}")


def _source_to_snippet(source: dict[str, Any], case: dict[str, Any], case_id: str, index: int) -> Snippet:
    source_id = str(source.get("id") or source.get("source_id") or f"S{index + 1}")
    if case_id and not source_id.startswith(f"{case_id}-"):
        source_id = f"{case_id}-{source_id}"
    url = str(source.get("source_url") or source.get("url") or "")
    name = str(
        source.get("source_name")
        or source.get("publisher")
        or source.get("domain")
        or source.get("site")
        or "unknown"
    )
    publisher_type = normalize_publisher_type(str(source.get("publisher_type") or source.get("type") or "unknown"))
    date = str(source.get("date") or source.get("published_at") or source.get("published") or "")
    content = str(source.get("content") or source.get("text") or source.get("snippet") or "")
    title = str(source.get("title") or source.get("headline") or case.get("subject") or "")
    known = {
        "id", "source_id", "source_url", "url", "source_name", "publisher", "domain", "site",
        "publisher_type", "type", "date", "published_at", "published", "content", "text",
        "snippet", "title", "headline", "verdict_in_corpus",
    }
    extra = {k: v for k, v in source.items() if k not in known}
    return Snippet(
        id=source_id,
        source_url=url,
        source_name=name,
        publisher_type=publisher_type,
        date=date,
        content=content,
        title=title,
        case_id=case_id,
        extra=extra,
    )


def snippets_from_case(case: dict[str, Any], index: int = 0) -> list[Snippet]:
    case_id = _case_id(case, index)
    sources = case.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError(f"{case_id}: campo sources non è una lista")
    return [
        _source_to_snippet(source, case, case_id, source_index)
        for source_index, source in enumerate(sources)
        if isinstance(source, dict)
    ]


def pool_snippets(cases: list[dict[str, Any]]) -> list[Snippet]:
    pooled: list[Snippet] = []
    for index, case in enumerate(cases):
        pooled.extend(snippets_from_case(case, index))
    for snippet in pooled:
        if snippet.case_id and not snippet.id.startswith(f"{snippet.case_id}-"):
            snippet.id = f"{snippet.case_id}-{snippet.id}"
    return pooled


def select_case(cases: list[dict[str, Any]], query: str) -> tuple[dict[str, Any] | None, list[Snippet], str]:
    needle = (query or "").strip().lower()
    if not needle:
        raise ValueError("query vuota")
    for index, case in enumerate(cases):
        case_id = _case_id(case, index).lower()
        if needle == case_id or needle == case_id.replace("-", ""):
            return case, snippets_from_case(case, index), "case_id"
    for index, case in enumerate(cases):
        case_id = _case_id(case, index)
        case_query = str(case.get("query") or "").strip()
        subject = str(case.get("subject") or "").strip()
        haystack = f"{case_query} {subject}".lower()
        if case_query and (needle in haystack or haystack in needle):
            return case, snippets_from_case(case, index), "case_query"
    if re.fullmatch(r"fc-?\d{1,3}", needle):
        return None, [], "missing_case"
    pooled: list[Snippet] = []
    for index, case in enumerate(cases):
        pooled.extend(snippets_from_case(case, index))
    return None, pooled, "free_query"


def load_live_snippets(path: str | Path | None = None) -> list[Snippet]:
    live_path = path or os.environ.get("LIVE_RESULTS_JSON")
    if not live_path:
        return []
    candidate = Path(live_path)
    if not candidate.exists():
        return []
    with candidate.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    items = raw.get("sources") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [
        _source_to_snippet(item, {}, "LIVE", index)
        for index, item in enumerate(items)
        if isinstance(item, dict)
    ]


def retrieve(
    query: str,
    corpus_path: str | Path | None = None,
    live_path: str | Path | None = None,
) -> list[Snippet]:
    cases = load_corpus(corpus_path)
    _case, snippets, _mode = select_case(cases, query)
    return snippets + load_live_snippets(live_path)


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "FC-01"
    for snippet in retrieve(q):
        print(json.dumps(snippet.to_dict(), ensure_ascii=False, indent=2))
