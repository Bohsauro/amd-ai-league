from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
FIGURE_RE = re.compile(
    r"(?<![\w.])(?P<sign>[- (]?)\s*"
    r"(?:(?P<currency>[$€£]|usd|eur|gbp)\s*)?"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)"
    r"\s*(?P<unit>percentage points?|percent|basis points?|bps|billion|million|trillion|"
    r"bn|mn|gib|tib|mib|gb/s|tb/s|gb|tb|mb|compute units?|cents per share|cents?|kw|w|k|x|b|m|t)?"
    r"(?![a-z])",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "could", "did", "do", "does",
    "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has",
    "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same",
    "she", "should", "so", "some", "such", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "this", "those", "through",
    "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you",
    "your", "yours", "yourself", "yourselves", "said", "says", "according", "reported",
    "report", "reports", "new", "news", "year", "years", "day", "days", "time",
}

GENERIC_CONTEXT = {
    "company", "companies", "source", "sources", "article", "articles", "story",
    "stories", "report", "reports", "reported", "said", "says", "according", "year",
    "years", "quarter", "quarterly", "fiscal", "results", "result", "today", "week",
    "month", "first", "second", "third", "fourth", "last", "next", "total", "around",
    "about", "nearly", "approximately", "update", "million", "billion", "trillion",
    "percent", "percentage", "bps", "basis", "point", "points",
}

UNIT_ALIASES = {
    "%": "%",
    "percent": "%",
    "percentage point": "pp",
    "percentage points": "pp",
    "bps": "bps",
    "basis point": "bps",
    "basis points": "bps",
    "billion": "b",
    "bn": "b",
    "b": "b",
    "million": "m",
    "mn": "m",
    "m": "m",
    "trillion": "t",
    "t": "t",
    "k": "k",
    "x": "x",
    "gb": "gb",
    "gib": "gb",
    "tb": "tb",
    "tib": "tb",
    "mb": "mb",
    "mib": "mb",
    "gb/s": "gb/s",
    "tb/s": "tb/s",
    "w": "w",
    "kw": "kw",
    "compute unit": "cu",
    "compute units": "cu",
    "cu": "cu",
    "cent": "cents",
    "cents": "cents",
    "cents per share": "cents",
}

UNIT_MULTIPLIERS: dict[str, float] = {}

METRIC_RULES = (
    ("bandwidth", ("bandwidth", "tb/s", "gb/s")),
    ("memory", ("hbm", "memory", "gib", "gb", "tib", "tb", "mb")),
    ("power", ("power", "watt", "tdp", "w", "kw")),
    ("compute_units", ("compute unit", "compute units", "cu")),
    ("eps", ("eps", "earnings per share", "per share", "cents per share")),
    ("revenue", ("revenue", "sales")),
    ("net_income", ("net income", "net loss", "profit", "loss")),
    ("net_debt", ("net debt", "debt")),
    ("workforce", ("jobs", "workforce", "employees")),
    ("dividend", ("dividend",)),
    ("deal_value", ("acquire", "acquisition", "deal", "pay", "paid", "price", "value", "cost", "consideration", "transaction")),
    ("consensus", ("consensus", "expected", "estimate")),
)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def content_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


def sentence_split(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_RE.split(text or "") if p.strip()]
    return parts or [text or ""]


def token_estimate(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    match = DATE_RE.search(raw)
    if match and match.group(0) != raw:
        return parse_date(match.group(0))
    return None


class TfidfIndex:
    def __init__(self, documents: Iterable[str]):
        self.documents = list(documents)
        self.doc_tokens = [tokenize(d) for d in self.documents]
        self.idf = self._build_idf(self.doc_tokens)

    @staticmethod
    def _build_idf(doc_tokens: list[list[str]]) -> dict[str, float]:
        n = len(doc_tokens)
        df: Counter[str] = Counter()
        for tokens in doc_tokens:
            df.update(set(tokens))
        return {term: math.log((1 + n) / (1 + count)) + 1.0 for term, count in df.items()}

    def vector(self, text: str) -> dict[str, float]:
        tokens = tokenize(text)
        counts = Counter(tokens)
        vec: dict[str, float] = {}
        for term, count in counts.items():
            weight = (1.0 + math.log(count)) * self.idf.get(term, math.log(len(self.documents) + 1) + 1.0)
            vec[term] = weight
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm:
            vec = {k: v / norm for k, v in vec.items()}
        return vec

    def similarity(self, text_a: str, text_b: str) -> float:
        return cosine(self.vector(text_a), self.vector(text_b))


def cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    return sum(weight * vec_b.get(term, 0.0) for term, weight in vec_a.items())


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class FigureClaim:
    value: float
    unit: str
    raw: str
    sentence: str
    context: frozenset[str]

    @property
    def key(self) -> tuple[str, float]:
        return (self.unit, self.value)

    @property
    def label(self) -> str:
        value = self.value
        if self.unit in UNIT_MULTIPLIERS:
            value = self.value / UNIT_MULTIPLIERS[self.unit]
        if value == int(value):
            rendered = f"{int(value):,}"
        else:
            rendered = f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{rendered}{self.unit}" if self.unit else rendered


def _normalize_figure(number: str, unit: str | None) -> tuple[float, str] | None:
    cleaned = number.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if unit:
        normalized_unit = UNIT_ALIASES.get(unit.lower(), unit.lower())
    else:
        normalized_unit = ""
    return value, normalized_unit


def extract_figures(text: str) -> list[FigureClaim]:
    claims: list[FigureClaim] = []
    for sentence in sentence_split(text):
        context = frozenset(
            t for t in content_tokens(sentence) if t not in GENERIC_CONTEXT and not t.isdigit() and len(t) > 2
        )
        for match in FIGURE_RE.finditer(sentence):
            prefix = sentence[max(0, match.start() - 48):match.start()].lower()
            if re.search(r"\b(prior|previous|earlier|old)\b", prefix):
                continue
            unit_raw = match.group("unit")
            parsed = _normalize_figure(match.group("number"), unit_raw)
            if parsed is None:
                continue
            value, unit = parsed
            if not unit and not match.group("currency"):
                continue
            claims.append(
                FigureClaim(
                    value=value,
                    unit=unit,
                    raw=match.group(0).strip(),
                    sentence=sentence.strip(),
                    context=context,
                )
            )
    return claims


def figures_conflict(a: FigureClaim, b: FigureClaim) -> bool:
    if a.key == b.key:
        return False
    if a.unit != b.unit:
        return False
    shared = a.context & b.context
    if not shared:
        return False
    return jaccard(a.context, b.context) >= 0.2 or len(shared) >= 2


def figures_agree(a: FigureClaim, b: FigureClaim) -> bool:
    if a.key != b.key:
        return False
    return jaccard(a.context, b.context) >= 0.15 or bool(a.context & b.context)


def extract_dates(text: str) -> set[str]:
    dates = set()
    for match in DATE_RE.finditer(text or ""):
        parsed = parse_date(match.group(0))
        dates.add(parsed.date().isoformat() if parsed else match.group(0).lower())
    return dates


def best_sentence(text: str, terms: set[str]) -> str:
    sentences = sentence_split(text)
    if not sentences:
        return ""
    scored = []
    for sentence in sentences:
        tokens = set(content_tokens(sentence))
        scored.append((len(tokens & terms), len(sentence), sentence))
    scored.sort(reverse=True)
    return scored[0][2]
