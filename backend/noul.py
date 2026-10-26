from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Any
from urllib.parse import urlparse

from config import NOUL_DROP_TARGET
from retriever import Snippet
from textutil import TfidfIndex, content_tokens, token_estimate

BOILERPLATE_PATTERNS = [
    r"\bsubscribe\b",
    r"\bsign\s*up\b",
    r"\bnewsletter\b",
    r"\bcookies?\b",
    r"\ball rights reserved\b",
    r"\badvertisement\b",
    r"\bsponsored\b",
    r"\bclick here\b",
    r"\bread more\b",
    r"\bshare this\b",
    r"\bfollow us\b",
    r"\bprivacy policy\b",
    r"\bterms of service\b",
    r"\byou may also like\b",
    r"\brelated articles?\b",
    r"\bdownload (?:our|the) app\b",
    r"\baccept all\b",
]
BOILERPLATE_RE = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)

BLACKLIST_DOMAINS = {
    "contentfarm.example",
    "seo-spam.example",
    "clickbait.example",
    "newsaggregator.example",
    "viral-now.example",
}
BLACKLIST_NAME_HINTS = ("content farm", "seo spam", "clickbait", "spam", "scraper")
NOISE_PUBLISHER_TYPES = {"noise", "spam", "seo", "contentfarm", "content-farm"}


@dataclass
class NoulResult:
    snippet: Snippet
    keep: bool
    confidence: float
    reason: str
    similarity: float
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = self.snippet.to_dict()
        data.update(
            {
                "keep": self.keep,
                "confidence": round(self.confidence, 4),
                "reason": self.reason,
                "similarity": round(self.similarity, 4),
                "signals": self.signals,
            }
        )
        return data


def _domain(snippet: Snippet) -> str:
    if snippet.source_url:
        try:
            return urlparse(snippet.source_url).netloc.lower()
        except ValueError:
            return ""
    return ""


def _boilerplate_hits(text: str) -> int:
    return len(BOILERPLATE_RE.findall(text or ""))


def _drop(snippet: Snippet, reason: str, confidence: float, similarity: float, signals: dict[str, Any]) -> NoulResult:
    return NoulResult(
        snippet=snippet,
        keep=False,
        confidence=confidence,
        reason=reason,
        similarity=similarity,
        signals=signals,
    )


def evaluate(
    snippet: Snippet,
    query: str,
    index: TfidfIndex,
    median_words: float,
) -> NoulResult:
    text = f"{snippet.title} {snippet.content}".strip()
    tokens = content_tokens(text)
    words = len(tokens)
    domain = _domain(snippet)
    name = (snippet.source_name or "").lower()
    publisher_type = (snippet.publisher_type or "").lower()
    hits = _boilerplate_hits(text)
    similarity = index.similarity(query, text)
    length_ratio = words / median_words if median_words else 1.0
    signals = {
        "words": words,
        "length_ratio": round(length_ratio, 3),
        "boilerplate_hits": hits,
        "domain": domain,
        "publisher_type": publisher_type,
        "tokens_est": token_estimate(text),
    }

    if publisher_type in NOISE_PUBLISHER_TYPES:
        reason = "seo" if publisher_type in {"seo", "contentfarm", "content-farm"} else "spam"
        return _drop(snippet, reason, 0.97, similarity, signals)

    if domain in BLACKLIST_DOMAINS or any(hint in name for hint in BLACKLIST_NAME_HINTS):
        return _drop(snippet, "seo", 0.96, similarity, signals)

    if words < max(8, median_words * 0.18):
        return _drop(snippet, "spam", 0.88, similarity, signals)

    if hits >= 3 or (hits >= 2 and hits / max(1, words) > 0.05):
        return _drop(snippet, "boilerplate", 0.86, similarity, signals)

    keep_confidence = 0.58 + min(0.35, similarity * 2.5) + min(0.05, length_ratio * 0.02)
    return NoulResult(
        snippet=snippet,
        keep=True,
        confidence=min(0.99, keep_confidence),
        reason="keep",
        similarity=similarity,
        signals=signals,
    )


QUOTA_MIN_POOL = 10


def _keep_target(total: int) -> int:
    """Quanti snippet tenere per rispettare il target di scarto 60-70%.

    La quota e' una proprieta' di un *pool* di ricerca, non di un insieme gia'
    selezionato: applicarla a 4 sorgenti di un singolo caso vorrebbe dire
    buttare evidenza pertinente e chiamarla "off-topic". Sotto QUOTA_MIN_POOL
    non si taglia nulla; sopra, si tiene il 35% circa (34 sorgenti -> 12).
    """
    if total < QUOTA_MIN_POOL:
        return total
    target_drop = sum(NOUL_DROP_TARGET) / 2.0
    return max(1, int(round(total * (1.0 - target_drop))))



def _offtopic_confidence(similarity: float) -> float:
    return round(max(0.50, min(0.94, 0.62 + (0.10 - similarity))), 4)


def gate(snippets: list[Snippet], query: str) -> list[NoulResult]:
    if not snippets:
        return []
    documents = [f"{s.title} {s.content}".strip() for s in snippets]
    index = TfidfIndex(documents)
    lengths = [len(content_tokens(doc)) for doc in documents]
    median_words = float(median(lengths)) if lengths else 1.0
    results = [evaluate(snippet, query, index, median_words) for snippet in snippets]

    survivors = [result for result in results if result.keep]
    target = _keep_target(len(results))
    if len(survivors) <= target:
        return results

    survivors.sort(key=lambda result: (-result.similarity, result.snippet.id))
    keep_ids = {result.snippet.id for result in survivors[:target]}
    gated: list[NoulResult] = []
    for result in results:
        if result.keep and result.snippet.id not in keep_ids:
            gated.append(
                _drop(
                    result.snippet,
                    "off-topic",
                    _offtopic_confidence(result.similarity),
                    result.similarity,
                    result.signals,
                )
            )
        else:
            gated.append(result)
    return gated


if __name__ == "__main__":
    import json
    import sys

    from retriever import retrieve

    query = sys.argv[1] if len(sys.argv) > 1 else "FC-01"
    results = gate(retrieve(query), query)
    for result in results:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    print(
        f"keep {sum(r.keep for r in results)}/{len(results)} "
        f"drop {sum(not r.keep for r in results)}"
    )
