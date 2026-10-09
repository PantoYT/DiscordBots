"""
Synchronizuje plan lekcji (Hebe API) do dedykowanego kalendarza "Lekcje"
w Google Calendar, z kolorem per przedmiot.

WAŻNE (odkryte empirycznie, nie z dokumentacji): Google Calendar API
udostępnia `calendars.labelProperties.eventLabels` (własne kolory hex, do 200
na kalendarz) i dokumentacja nazywa `eventLabelId` polem zapisywalnym na
Event — ale w praktyce PATCH z `eventLabelId` zwraca 200 i **nic nie zapisuje**
(świeży GET po zapisie pokazuje puste pole). Sprawdzone wprost: PATCH →
odczyt → brak zmiany. Nie polegać na tym polu, dopóki Google tego nie naprawi.

Zamiast tego: klasyczne `colorId` (1-11, jedyne realnie zapisywalne pole
koloru). Z 11 kolorów rezerwujemy 2 na zastępstwo/odwołanie i 1 wyrzucamy
(Graphite = szary, wygląda jak brak koloru) — zostaje 8 na przedmioty. Za
mało na 15-26 przedmiotów żeby każdy był unikalny, więc kolorujemy graf:
przedmioty z tego samego dnia nigdy nie dostają tego samego koloru (zero
kolizji tam, gdzie realnie by przeszkadzały), a te co nigdy się nie
spotykają mogą spokojnie dzielić kolor.

Wymaga google_calendar_token.json (patrz calendar_auth.py). Token jest
z aplikacji w trybie Testing — wygasa po ~7 dniach; wtedy ta funkcja rzuca
CalendarAuthError, żeby wołający (main.py) mógł dać znać na Discordzie.

Diffuje po Id lekcji z Hebe (trzymanym w extendedProperties.private) — nie
tworzy duplikatów przy kolejnych synchronizacjach, aktualizuje zmienione
(zastępstwo/odwołanie/zmiana sali) i kasuje zniknięte.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

from client import VulcanClient

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("VRED_DATA_DIR") or ROOT)
TOKEN_FILE = DATA_DIR / "google_calendar_token.json"
CALENDAR_SUMMARY = "Lekcje"  # celowo inna nazwa niz "Plan lekcji" (ta jest zajeta przez subskrypcje .ics — tamta jest tylko-do-odczytu)
CHUNK_DAYS = 28
SOURCE_TAG = "vred"

# Google Calendar colorId: 1 Lavender 2 Sage 3 Grape 4 Flamingo 5 Banana
# 6 Tangerine 7 Peacock 8 Graphite 9 Blueberry 10 Basil 11 Tomato
COLOR_CANCELLED = "11"   # Tomato
COLOR_SUBST = "6"        # Tangerine
SUBJECT_COLOR_IDS = ["1", "2", "3", "4", "5", "7", "9", "10"]  # bez 8 (szary) i bez rezerwowanych


def _assign_colors_graph(lessons: list[dict]) -> dict[str, str]:
    """Koloruje przedmioty tak, zeby zaden dzien nie mial dwoch tej samej
    barwy (graf konfliktow = 'wystepuja tego samego dnia'). Zachlanny
    Welsh-Powell (od najbardziej 'zatloczonego' przedmiotu), deterministyczny
    dzieki sortowaniu po nazwie przy remisach."""
    day_subjects: dict[str, set[str]] = defaultdict(set)
    all_subjects: set[str] = set()
    for l in lessons:
        if l.get("Visible") is False:
            continue
        subj = _lesson_subject(l)
        d = l.get("DateAt")
        if not d:
            continue
        day_subjects[d].add(subj)
        all_subjects.add(subj)

    adjacency: dict[str, set[str]] = defaultdict(set)
    for subs in day_subjects.values():
        subs = list(subs)
        for i in range(len(subs)):
            for j in range(i + 1, len(subs)):
                adjacency[subs[i]].add(subs[j])
                adjacency[subs[j]].add(subs[i])

    order = sorted(all_subjects, key=lambda s: (-len(adjacency[s]), s))
    assigned: dict[str, str] = {}
    for subj in order:
        blocked = {assigned[n] for n in adjacency[subj] if n in assigned}
        free = [c for c in SUBJECT_COLOR_IDS if c not in blocked]
        if free:
            assigned[subj] = free[0]
        else:
            # dzien zatloczony ponad 8 roznych przedmiotow — nie da sie uniknac
            # kolizji, bierz przynajmniej najrzadziej uzywany kolor dotychczas
            usage = Counter(assigned.values())
            assigned[subj] = min(SUBJECT_COLOR_IDS, key=lambda c: usage.get(c, 0))
    return assigned


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


def _event_body(l: dict, subject_colors: dict[str, str]) -> dict | None:
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
    color = COLOR_CANCELLED if ctype == 1 else COLOR_SUBST if ctype == 2 else subject_colors.get(subject, "1")
    return {
        "summary": prefix + subject,
        "location": room or "",
        "description": teacher or "",
        "start": {"dateTime": f"{d}T{t_start}:00", "timeZone": "Europe/Warsaw"},
        "end": {"dateTime": f"{d}T{t_end}:00", "timeZone": "Europe/Warsaw"},
        "colorId": color,
        "extendedProperties": {"private": {"vulcanscope_id": str(lid), "vulcanscope_source": SOURCE_TAG}},
    }


def sync() -> dict:
    """Zwraca podsumowanie {created, updated, deleted, unchanged, total}."""
    access_token = _access_token()
    gcal = GCal(access_token)
    calendar_id = gcal.find_or_create_calendar(CALENDAR_SUMMARY)
    existing = gcal.list_synced_events(calendar_id)

    vc = VulcanClient(str(DATA_DIR / "credentials.json"))
    lessons = _fetch_all_lessons(vc)
    visible = [l for l in lessons if l.get("Visible") is not False]
    subject_colors = _assign_colors_graph(visible)

    seen_ids = set()
    created = updated = unchanged = 0
    for l in visible:
        body = _event_body(l, subject_colors)
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
                or prev.get("colorId") != body["colorId"]
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
