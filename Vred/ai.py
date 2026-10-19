"""
Groq (darmowy prog, bez karty) — gpt-oss-120b z wbudowanym browser_search,
czyli odpowiedz oparta na wynikach wyszukiwania, ze zrodlami.

Limity free tier odczytane z naglowkow (2026-10-19): 1000 zapytan/dzien,
8000 tokenow/min. Jedno zapytanie z wyszukiwaniem to 10-60 tys. tokenow,
wiec 429 jest normalne — czekamy wg retry-after.
"""
import os
import time

import requests

import logic

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL   = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")
MAX_WAIT = 90   # lacznie sekund czekania na 429, potem poddajemy sie

SYSTEM = (
    "Jesteś korepetytorem polskiego ucznia szkoły średniej. Zanim odpowiesz, wyszukaj "
    "w internecie i oprzyj się na znalezionych stronach. Pisz po polsku, zwięźle, w Markdownie "
    "zrozumiałym dla Discorda (pogrubienia, listy, nagłówki ###). NIE używaj tabel, HTML-a ani LaTeX-a — wzory pisz zwykłym "
    "tekstem, np. f(x) = a(x − p)² + q. Nie wymyślaj faktów, których nie ma w źródłach."
)


class AIError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _post(key: str, body: dict) -> requests.Response:
    return requests.post(API_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120)


def ask(prompt: str, max_tokens: int = 1500) -> tuple[str, list[tuple[str, str]]]:
    """(tekst z przypisami [n], [(tytul, url), ...]). Blokujace — wolac przez to_thread.
    Limit tokenow/min jest osobny dla kazdego modelu, wiec przy dlugiej blokadzie
    przechodzimy na FALLBACK zamiast kazac czekac kilka minut."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise AIError("brak GROQ_API_KEY w .env")
    longest = 0.0
    for model in dict.fromkeys((MODEL, FALLBACK)):
        body = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "tools": [{"type": "browser_search"}],
            "tool_choice": "required",
            "max_completion_tokens": max_tokens,
        }
        waited = 0.0
        while True:
            r = _post(key, body)
            # Model uznal, ze nie ma czego szukac (np. "asd") — wymuszenie daje 400.
            if r.status_code == 400 and "tool_use_failed" in r.text and body["tool_choice"] == "required":
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
        if r.status_code == 429:
            continue
        if not r.ok:
            raise AIError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
        msg = r.json()["choices"][0]["message"]
        text, sources = logic.cite_sources(msg.get("content") or "", msg.get("executed_tools") or [])
        return logic.tables_to_lists(text), sources
    raise AIError(f"limit darmowego Groq — spróbuj za ok. {max(1, round(longest / 60))} min")
