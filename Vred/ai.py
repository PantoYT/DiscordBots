"""
Groq (free tier, no card) — gpt-oss-120b with the built-in browser_search, so the
answer is grounded in search results and comes with sources.

Free-tier limits read from the response headers (2026-10-19, rechecked
2026-11-11): 1000 requests/day, 8000 tokens/min per model. The rate-limits page
(console.groq.com/docs/rate-limits, 2026-11-11) also lists 200K tokens/day per
model, which matches a 19-min 429 hit after a day of tests. One request with
search costs 10-60k tokens, so a 429 is normal — we wait for retry-after, and
the daily cap means roughly 4-8 revisions per model per day.
A JSON request without search (quiz) costs ~2-3k tokens.
"""
import json
import os
import time

import requests

import logic

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL   = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")
# Language of the AI's answers. The bot UI is English, but the exams are Polish,
# so revisions default to Polish terminology.
LANGUAGE = os.getenv("AI_LANGUAGE", "Polish")
MAX_WAIT = 90   # total seconds of waiting on 429, then give up

SYSTEM = (
    "You are a tutor for a Polish secondary-school student. Before answering, search the web "
    f"and base the answer on the pages you found. Write in {LANGUAGE}, concisely, in Markdown that "
    "Discord renders (bold, lists, ### headings). Do NOT use tables, HTML or LaTeX — write formulas "
    "as plain text, e.g. f(x) = a(x − p)² + q. Do not invent facts that are not in the sources."
)


class AIError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _post(key: str, body: dict) -> requests.Response:
    return requests.post(API_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120)


def _run(make_body) -> dict:
    """POST with 429 handling. The tokens/min limit is per model, so on a long block
    we switch to FALLBACK instead of making the user wait minutes."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise AIError("GROQ_API_KEY is missing from .env")
    longest = 0.0
    timed_out = False
    for model in dict.fromkeys((MODEL, FALLBACK)):
        body = make_body(model)
        waited = 0.0
        r = None
        while True:
            try:
                r = _post(key, body)
            except requests.Timeout:
                # a search answer occasionally takes over 2 min (seen 2026-11-11) — try the fallback
                timed_out = True
                break
            # The model decided there is nothing to search (e.g. "asd") — forcing gives 400.
            if r.status_code == 400 and "tool_use_failed" in r.text and body.get("tool_choice") == "required":
                body["tool_choice"] = "auto"
                continue
            if r.status_code != 429:
                break
            wait = float(r.headers.get("retry-after") or 20) + 1
            if waited + wait > MAX_WAIT:
                longest = max(longest, wait)
                break
            time.sleep(wait)
            waited += wait
        if r is None or r.status_code == 429:
            continue
        if not r.ok:
            raise AIError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]
    if timed_out and not longest:
        raise AIError("Groq did not answer in time — try again in a minute")
    raise AIError(f"free Groq limit reached — try again in about {max(1, round(longest / 60))} min")


def ask(prompt: str, max_tokens: int = 1500) -> tuple[str, list[tuple[str, str]]]:
    """(text with [n] footnotes, [(title, url), ...]). Blocking — call via to_thread."""
    msg = _run(lambda model: {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "tools": [{"type": "browser_search"}],
        "tool_choice": "required",
        "max_completion_tokens": max_tokens,
    })
    text, sources = logic.cite_sources(msg.get("content") or "", msg.get("executed_tools") or [])
    return logic.tables_to_lists(text), sources


def ask_json(prompt: str, max_tokens: int = 4000) -> dict:
    """JSON mode, no search — for structured output such as a quiz."""
    msg = _run(lambda model: {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": max_tokens,
    })
    try:
        return json.loads(msg.get("content") or "")
    except json.JSONDecodeError as e:
        raise AIError(f"model returned invalid JSON: {e}") from e
