"""
Synchronizuje plan lekcji (Hebe API) do dedykowanego kalendarza "Lekcje"
w Google Calendar, z NAPRAWDĘ unikalnym kolorem per przedmiot.

Google Calendar ma tylko 11 wbudowanych colorId — za mało na 15-20 przedmiotów
bez powtórek. Zamiast tego używamy calendars.labelProperties.eventLabels
(funkcja z czerwca 2026) — własne etykiety z dowolnym kolorem hex, do 200 na
kalendarz, przypięte do wydarzenia przez eventLabelId. Każdy przedmiot dostaje
kolor z 20-kolorowej palety wygenerowanej równomiernie na kole barw (HSL),
wybrany stabilnym hashem nazwy — nowy przedmiot dostaje kolor automatycznie,
a istniejące nie przeskakują koloru przy kolejnych synchronizacjach.

Wymaga google_calendar_token.json (patrz calendar_auth.py). Token jest
z aplikacji w trybie Testing — wygasa po ~7 dniach; wtedy ta funkcja rzuca
CalendarAuthError, żeby wołający (main.py) mógł dać znać na Discordzie.

Diffuje po Id lekcji z Hebe (trzymanym w extendedProperties.private) — nie
tworzy duplikatów przy kolejnych synchronizacjach, aktualizuje zmienione
(zastępstwo/odwołanie/zmiana sali) i kasuje zniknięte.
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

from client import VulcanClient

ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / "google_calendar_token.json"
LABELS_FILE = ROOT / "calendar_labels.json"
CALENDAR_SUMMARY = "Lekcje"  # celowo inna nazwa niz "Plan lekcji" (ta jest zajeta przez subskrypcje .ics — tamta jest tylko-do-odczytu)
CHUNK_DAYS = 28
SOURCE_TAG = "vred"

LABEL_CANCELLED = "Odwołane"
LABEL_SUBST = "Zastępstwo"
COLOR_CANCELLED = "#e53935"  # czerwony, poza pulą przedmiotow
COLOR_SUBST = "#fb8c00"      # pomaranczowy, poza pulą przedmiotow

PALETTE_SIZE = 24


def _make_palette(n: int = PALETTE_SIZE, s: float = 0.62, l: float = 0.50) -> list[str]:
    """N kolorow rownomiernie rozlozonych na kole barw — stala pula, zeby dodanie
    nowego przedmiotu nigdy nie przesuwalo kolorow juz przypisanym innym."""
    colors = []
    for i in range(n):
        r, g, b = colorsys.hls_to_rgb(i / n, l, s)
        colors.append("#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255)))
    return colors


SUBJECT_PALETTE = _make_palette()


def _assign_colors(subjects: set[str]) -> dict[str, str]:
    """Przydziela kolor kazdemu przedmiotowi z bieżącego zbioru, gwarantujac brak
    kolizji. Paleta rosnie do liczby przedmiotow, gdy jest ich wiecej niz
    PALETTE_SIZE — inaczej przy kolizji zabraklo by wolnego slotu (nieskonczona
    petla). Start od stabilnego hashu nazwy, przy kolizji szuka najblizszego
    wolnego slotu (deterministycznie, w kolejnosci alfabetycznej) — kolor moze
    sie przesunac o pare przedmiotow gdy zbior przedmiotow sie zmieni (nowy
    semestr), w zamian za zero powtorzen kolorow naraz. Świadomy kompromis:
    unikalnosc teraz > stabilnosc w czasie."""
    n = max(PALETTE_SIZE, len(subjects))
    palette = SUBJECT_PALETTE if n == PALETTE_SIZE else _make_palette(n)
    taken: set[int] = set()
    result: dict[str, str] = {}
    for name in sorted(subjects):
        idx = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % n
        probe = idx
        while probe in taken:
            probe = (probe + 1) % n
        taken.add(probe)
        result[name] = palette[probe]
    return result


class CalendarAuthError(RuntimeError):
    """Refresh token wygasł/odrzucony — trzeba ponownie odpalić calendar_auth.py."""


def _period_bounds(p: dict) -> tuple[str, str]:
    start = p.get("StartAt") or p["Start"]["Date"]
    end = p.get("EndAt") or p["End"]["Date"]
    return start, end


def _access_token() -> str:
    with open(TOKEN_FILE, encoding="utf-8") as f:
        tok = json.load(f)
    r = requests.post(tok["token_uri"], data={
        "refresh_token": tok["refresh_token"],
        "client_id": tok["client_id"],
        "client_secret": tok["client_secret"],
        "grant_type": "refresh_token",
    }, timeout=15)
    if r.status_code == 400 and "invalid_grant" in r.text:
        raise CalendarAuthError("refresh_token wygasl lub zostal odrzucony")
    r.raise_for_status()
    return r.json()["access_token"]


class GCal:
    def __init__(self, access_token: str):
        self._h = {"Authorization": f"Bearer {access_token}"}
        self._base = "https://www.googleapis.com/calendar/v3"

    def _req(self, method: str, path: str, **kw) -> dict:
        r = requests.request(method, f"{self._base}{path}", headers=self._h, timeout=20, **kw)
        if r.status_code == 401:
            raise CalendarAuthError(f"access token odrzucony: {r.text[:200]}")
        r.raise_for_status()
        return r.json() if r.text else {}

    def find_or_create_calendar(self, summary: str) -> str:
        page_token = None
        while True:
            data = self._req("GET", "/users/me/calendarList", params={"pageToken": page_token} if page_token else {})
            for cal in data.get("items", []):
                if cal.get("summary") == summary:
                    return cal["id"]
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        created = self._req("POST", "/calendars", json={"summary": summary, "timeZone": "Europe/Warsaw"})
        return created["id"]

    def list_synced_events(self, calendar_id: str) -> dict[str, dict]:
        out = {}
        page_token = None
        while True:
            params = {
                "privateExtendedProperty": f"vulcanscope_source={SOURCE_TAG}",
                "maxResults": 2500,
                "singleEvents": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._req("GET", f"/calendars/{calendar_id}/events", params=params)
            for ev in data.get("items", []):
                lid = ev.get("extendedProperties", {}).get("private", {}).get("vulcanscope_id")
                if lid:
                    out[lid] = ev
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    def ensure_labels(self, calendar_id: str, names_colors: dict[str, str]) -> dict[str, str]:
        """Zapewnia, ze kazda nazwa w names_colors ma etykiete na kalendarzu z podanym
        kolorem, zachowujac istniejace id (zeby juz przypisane eventLabelId nie osierocialy
        sie przy kazdej synchronizacji). Zwraca mape nazwa -> label_id."""
        try:
            with open(LABELS_FILE, encoding="utf-8") as f:
                known_ids: dict[str, str] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            known_ids = {}

        event_labels = []
        for name, color in names_colors.items():
            entry = {"name": name, "backgroundColor": color}
            if name in known_ids:
                entry["id"] = known_ids[name]
            event_labels.append(entry)

        result = self._req("PATCH", f"/calendars/{calendar_id}", json={
            "labelProperties": {"eventLabels": event_labels}
        })

        new_ids = {lbl["name"]: lbl["id"] for lbl in result.get("labelProperties", {}).get("eventLabels", [])}
        with open(LABELS_FILE, "w", encoding="utf-8") as f:
            json.dump(new_ids, f, indent=2, ensure_ascii=False)
        return new_ids

    def insert_event(self, calendar_id: str, body: dict):
        self._req("POST", f"/calendars/{calendar_id}/events", json=body)

    def update_event(self, calendar_id: str, event_id: str, body: dict):
        self._req("PATCH", f"/calendars/{calendar_id}/events/{event_id}", json=body)

    def delete_event(self, calendar_id: str, event_id: str):
        try:
            self._req("DELETE", f"/calendars/{calendar_id}/events/{event_id}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 410:
                return  # already gone
            raise


def _fetch_all_lessons(vc: VulcanClient) -> list[dict]:
    lessons = []
    for p in vc.periods:
        start, end = _period_bounds(p)
        cursor, d_end = date.fromisoformat(start), date.fromisoformat(end)
        while cursor <= d_end:
            win_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), d_end)
            lessons += vc.get_schedule_changes(cursor.isoformat(), win_end.isoformat(), p["Id"]) or []
            cursor = win_end + timedelta(days=1)
    return lessons


def _lesson_subject(l: dict) -> str:
    return (l.get("Subject") or {}).get("Name", "?")


def _lesson_label_name(l: dict) -> str:
    ch = l.get("Change") or None
    ctype = ch.get("Type") if ch else 0
    if ctype == 1:
        return LABEL_CANCELLED
    if ctype == 2:
        return LABEL_SUBST
    return _lesson_subject(l)


def _event_body(l: dict, label_map: dict[str, str]) -> dict | None:
    lid = l.get("Id")
    d = l.get("DateAt", "")
    ts = l.get("TimeSlot") or {}
    t_start, t_end = ts.get("Start"), ts.get("End")
    if lid is None or not (d and t_start and t_end):
        return None
    subject = _lesson_subject(l)
    room = (l.get("Room") or {}).get("Code") if l.get("Room") else None
    teacher = (l.get("TeacherPrimary") or {}).get("DisplayName") if l.get("TeacherPrimary") else None
    ch = l.get("Change") or None
    ctype = ch.get("Type") if ch else 0
    prefix = "❌ " if ctype == 1 else "⚠ " if ctype == 2 else ""
    label_id = label_map.get(_lesson_label_name(l))
    body = {
        "summary": prefix + subject,
        "location": room or "",
        "description": teacher or "",
        "start": {"dateTime": f"{d}T{t_start}:00", "timeZone": "Europe/Warsaw"},
        "end": {"dateTime": f"{d}T{t_end}:00", "timeZone": "Europe/Warsaw"},
        "extendedProperties": {"private": {"vulcanscope_id": str(lid), "vulcanscope_source": SOURCE_TAG}},
    }
    if label_id:
        body["eventLabelId"] = label_id
    return body


def sync() -> dict:
    """Zwraca podsumowanie {created, updated, deleted, unchanged, total}."""
    access_token = _access_token()
    gcal = GCal(access_token)
    calendar_id = gcal.find_or_create_calendar(CALENDAR_SUMMARY)
    existing = gcal.list_synced_events(calendar_id)

    vc = VulcanClient()
    lessons = _fetch_all_lessons(vc)
    visible = [l for l in lessons if l.get("Visible") is not False]

    subjects = {_lesson_subject(l) for l in visible if l.get("Id") is not None}
    names_colors = _assign_colors(subjects)
    names_colors[LABEL_CANCELLED] = COLOR_CANCELLED
    names_colors[LABEL_SUBST] = COLOR_SUBST
    label_map = gcal.ensure_labels(calendar_id, names_colors)

    seen_ids = set()
    created = updated = unchanged = 0
    for l in visible:
        body = _event_body(l, label_map)
        if body is None:
            continue
        lid = body["extendedProperties"]["private"]["vulcanscope_id"]
        if lid in seen_ids:
            continue
        seen_ids.add(lid)
        prev = existing.get(lid)
        if prev is None:
            gcal.insert_event(calendar_id, body)
            created += 1
        else:
            def _same_time(existing_dt: str, new_dt: str) -> bool:
                return existing_dt.startswith(new_dt)  # Google zwraca z dopisanym offsetem strefy

            changed = (
                prev.get("summary") != body["summary"]
                or prev.get("eventLabelId") != body.get("eventLabelId")
                or prev.get("location", "") != body["location"]
                or not _same_time(prev.get("start", {}).get("dateTime", ""), body["start"]["dateTime"])
                or not _same_time(prev.get("end", {}).get("dateTime", ""), body["end"]["dateTime"])
            )
            if changed:
                gcal.update_event(calendar_id, prev["id"], body)
                updated += 1
            else:
                unchanged += 1

    deleted = 0
    for lid, ev in existing.items():
        if lid not in seen_ids:
            gcal.delete_event(calendar_id, ev["id"])
            deleted += 1

    return {"created": created, "updated": updated, "deleted": deleted, "unchanged": unchanged, "total": len(seen_ids)}


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        result = sync()
        print(f"[calendar_sync] {result}")
    except CalendarAuthError as e:
        print(f"[calendar_sync] AUTORYZACJA WYGASLA: {e}")
        print("Odpal ponownie: py -3.12 calendar_auth.py")
        sys.exit(2)
