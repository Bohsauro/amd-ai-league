from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

from choice import ChoiceResult
from config import GEN_MAX_SOURCES, GEN_TIMEOUT_S, GEN_TOKEN_BUDGET
from score import ScoreResult
from textutil import token_estimate

DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct"
MAX_CONTEXT_TOKENS = GEN_TOKEN_BUDGET
MAX_SOURCES = GEN_MAX_SOURCES
SYSTEM_PROMPT = (
    "You are a financial fact reconciliation engine. You receive a query, a verdict from a "
    "discriminative reconciliation stage, and a small set of validated sources. Return ONLY a "
    "JSON object with exactly these keys: answer (string), confidence (number 0..1), "
    "citations (array of objects with source_id and claim_id), status (\"resolved\" or "
    "\"unresolved\"). Rules: use only the provided sources; never invent figures or sources; "
    "if VERDICT_LABEL is CONFLICT, the answer MUST (a) state both the GAAP/primary figure and "
    "the non-GAAP/adjusted figure with their exact values, (b) state any guidance range (revenue "
    "and EPS) present in the validated sources, and (c) say which claim prevails and why using "
    "the verdict; do not omit a conflicting figure even if the answer gets longer. If evidence is "
    "insufficient, return status \"unresolved\", confidence <= 0.4 and an empty citations array; "
    "keep answer under 90 words."
)


def _source_block(result: ScoreResult, max_chars: int) -> str:
    content = result.snippet.content.strip().replace("\n", " ")
    if len(content) > max_chars:
        content = content[: max_chars - 1].rstrip() + "…"
    return (
        f"source_id={result.snippet.id} | name={result.snippet.source_name} | "
        f"type={result.snippet.publisher_type} | date={result.snippet.date}\n{content}"
    )


def _select_sources(
    score_results: list[ScoreResult],
    budget_tokens: int,
    preferred_ids: set[str],
) -> tuple[list[ScoreResult], list[str]]:
    ordered = sorted(
        score_results,
        key=lambda result: (result.snippet.id not in preferred_ids, -result.score, result.snippet.id),
    )
    selected: list[ScoreResult] = []
    blocks: list[str] = []
    used = 0
    for result in ordered[:MAX_SOURCES]:
        block = _source_block(result, max_chars=1200)
        cost = token_estimate(block)
        if selected and used + cost > budget_tokens:
            remaining = budget_tokens - used
            if remaining > 120:
                trimmed = _source_block(result, max_chars=max(200, remaining * 3))
                selected.append(result)
                blocks.append(trimmed)
            break
        selected.append(result)
        blocks.append(block)
        used += cost
    return selected, blocks


def build_messages(
    query: str,
    choice: ChoiceResult,
    score_results: list[ScoreResult],
) -> tuple[list[dict[str, str]], list[ScoreResult], int]:
    header = (
        f"QUERY: {query}\n"
        f"VERDICT_LABEL: {choice.label}\n"
        f"VERDICT: {choice.verdict}\n"
        f"CLAIM: {choice.claim or 'n/a'}\n"
        f"CHOICE_CONFIDENCE: {choice.confidence:.3f}\n"
        f"CONFLICTS: {json.dumps(choice.conflict_pairs, ensure_ascii=False)}\n\n"
        "VALIDATED SOURCES:\n"
    )
    selected, blocks = _select_sources(
        score_results,
        budget_tokens=1000,
        preferred_ids=set(choice.evidence),
    )
    user_prompt = header + "\n\n".join(blocks)
    if not selected:
        user_prompt += "(none)"
    user_prompt += (
        "\n\nReturn the JSON object now. Cite only source_id values listed above and use "
        f"claim_id {choice.claim_id}."
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    estimated = token_estimate(SYSTEM_PROMPT) + token_estimate(user_prompt)
    return messages, selected, estimated


def _parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start < 0:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(cleaned[start:])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_citations(raw: Any, allowed: set[str], claim_id: str) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    citations: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            source_id = item
            item_claim = claim_id
        elif isinstance(item, dict):
            source_id = str(item.get("source_id") or item.get("id") or "")
            item_claim = str(item.get("claim_id") or claim_id)
        else:
            continue
        if source_id in allowed and all(c["source_id"] != source_id for c in citations):
            citations.append({"source_id": source_id, "claim_id": item_claim})
    return citations


def _provider_options() -> dict[str, Any]:
    """Selezione provider per la demo.

    Default: pin su Groq (percorso misurato della demo: ~450 ms). Il semplice
    `sort: latency` di OpenRouter puo' deviare su provider piu' lenti (es.
    CoreWeave ~1.8s) anche quando Groq e' disponibile, sballando il budget e2e
    di 1.2s. Il pin e' configurabile: OPENROUTER_PROVIDER_ONLY='' per nessun
    pin, oppure lista separata da virgole. Se il provider pinnato cade, la
    chiamata va in errore e `bin/demo` ricade sul run congelato (fallback
    offline previsto per la registrazione).
    """
    raw = os.environ.get("OPENROUTER_PROVIDER_ONLY", "Groq")
    options: dict[str, Any] = {"sort": "latency"}
    providers = [item.strip() for item in raw.split(",") if item.strip()]
    if providers:
        options["only"] = providers
    return options


def _skipped(answer: str, confidence: float, model: str, reason: str, prompt_tokens_est: int) -> dict[str, Any]:
    return {
        "called": False,
        "status": "skipped",
        "answer": answer,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "citations": [],
        "model": model,
        "usage": None,
        "latency_ms": 0.0,
        "prompt_tokens_est": prompt_tokens_est,
        "selected_source_ids": [],
        "error": reason,
    }


def _error(model: str, reason: str, latency_ms: float, prompt_tokens_est: int) -> dict[str, Any]:
    return {
        "called": True,
        "status": "error",
        "answer": "",
        "confidence": 0.0,
        "citations": [],
        "model": model,
        "usage": None,
        "latency_ms": round(latency_ms, 3),
        "prompt_tokens_est": prompt_tokens_est,
        "selected_source_ids": [],
        "error": reason,
    }


def generate(
    query: str,
    choice: ChoiceResult,
    score_results: list[ScoreResult],
    skip: bool = False,
    skip_reason: str = "guard: evidence insufficient",
) -> dict[str, Any]:
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    messages, selected, prompt_tokens_est = build_messages(query, choice, score_results)
    selected_ids = [result.snippet.id for result in selected]
    if skip:
        return _skipped(
            f"Generatore non invocato: {choice.label}.",
            choice.confidence,
            model,
            skip_reason,
            prompt_tokens_est,
        )
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return _skipped(
            "Generatore non disponibile: OPENROUTER_API_KEY assente.",
            choice.confidence,
            model,
            "missing OPENROUTER_API_KEY",
            prompt_tokens_est,
        )
    if not selected:
        return _skipped(
            "Nessuna fonte validata da passare al generatore.",
            choice.confidence,
            model,
            "no validated sources",
            prompt_tokens_est,
        )
    if prompt_tokens_est > MAX_CONTEXT_TOKENS:
        return _skipped(
            "Contesto oltre il budget: nessuna chiamata generativa.",
            choice.confidence,
            model,
            f"prompt_tokens_est {prompt_tokens_est} > {MAX_CONTEXT_TOKENS}",
            prompt_tokens_est,
        )

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 220,
        "response_format": {"type": "json_object"},
        "provider": _provider_options(),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "AMD AI League Match 4 Demo",
    }
    referer = os.environ.get("OPENROUTER_REFERER")
    if referer:
        headers["HTTP-Referer"] = referer

    started = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(GEN_TIMEOUT_S, connect=5.0)) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        if response.status_code >= 400:
            return _error(
                model,
                f"HTTP {response.status_code}: {response.text[:300]}",
                latency_ms,
                prompt_tokens_est,
            )
        body = response.json()
        content = ""
        choices = body.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        parsed = _parse_json_object(content)
        if parsed is None:
            return _error(model, "invalid JSON from generator", latency_ms, prompt_tokens_est)
        usage = body.get("usage") or {}
        allowed = set(choice.evidence)
        citations = _normalize_citations(parsed.get("citations"), allowed, choice.claim_id)
        status = str(parsed.get("status") or "").lower()
        if status not in {"resolved", "unresolved"}:
            status = "resolved" if citations else "unresolved"
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        answer = str(parsed.get("answer") or "").strip()
        if status == "resolved" and not citations:
            status = "unresolved"
            confidence = min(confidence, 0.4)
        if status == "unresolved":
            citations = []
        return {
            "called": True,
            "status": status,
            "answer": answer,
            "confidence": round(confidence, 4),
            "citations": citations,
            "model": body.get("model") or model,
            "provider": body.get("provider"),
            "usage": usage,
            "latency_ms": round(latency_ms, 3),
            "prompt_tokens_est": prompt_tokens_est,
            "selected_source_ids": selected_ids,
            "error": None,
        }
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return _error(model, f"{type(exc).__name__}: {exc}", latency_ms, prompt_tokens_est)
