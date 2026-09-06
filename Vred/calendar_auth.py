"""
Jednorazowa autoryzacja OAuth do Google Calendar (projekt "vred-calendar",
konto testowe = własne). Zapisuje refresh_token do google_calendar_token.json.

Ważne: to jest aplikacja w trybie Testing — Google wygasza refresh_token po
7 dniach. Ten skrypt trzeba więc uruchamiać ponownie za każdym razem, gdy
calendar_sync.py zgłosi invalid_grant (Vred da znać na Discordzie).

Użycie:
    py -3.12 calendar_auth.py
"""
from __future__ import annotations

import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

ROOT = Path(__file__).resolve().parent
CLIENT_SECRET_FILE = ROOT / "google_client_secret.json"
TOKEN_FILE = ROOT / "google_calendar_token.json"
REDIRECT_PORT = 8766
SCOPE = "https://www.googleapis.com/auth/calendar"  # calendar.events samo nie wystarcza — calendarList/calendars.insert wymaga pelnego

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_client() -> dict:
    with open(CLIENT_SECRET_FILE, encoding="utf-8") as f:
        return json.load(f)["installed"]


def run():
    client = load_client()
    redirect_uri = f"http://localhost:{REDIRECT_PORT}"
    state = secrets.token_urlsafe(16)

    auth_url = client["auth_uri"] + "?" + urlencode({
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })

    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if qs.get("state", [None])[0] != state:
                self.wfile.write("<h1>Zly state — mozesz zamknac karte i sprobowac ponownie.</h1>".encode())
                result["error"] = "state_mismatch"
                return
            if "code" in qs:
                result["code"] = qs["code"][0]
                self.wfile.write("<h1>Gotowe — mozesz zamknac te karte.</h1>".encode())
            else:
                result["error"] = qs.get("error", ["unknown"])[0]
                self.wfile.write(f"<h1>Blad: {result['error']}</h1>".encode())

        def log_message(self, fmt, *args):
            pass

    print("Otwieram przegladarke do logowania Google...")
    print(f"Jesli nie otworzy sie sama, wklej URL:\n{auth_url}\n")
    webbrowser.open(auth_url)

    httpd = HTTPServer(("localhost", REDIRECT_PORT), Handler)
    while "code" not in result and "error" not in result:
        httpd.handle_request()

    if "error" in result:
        print(f"[calendar_auth] Autoryzacja nieudana: {result['error']}")
        sys.exit(1)

    resp = requests.post(client["token_uri"], data={
        "code": result["code"],
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()

    if "refresh_token" not in tokens:
        print("[calendar_auth] Brak refresh_token w odpowiedzi — Google go nie wydal.")
        print("Sprobuj ponownie; jesli problem sie powtarza, usun dostep aplikacji w")
        print("myaccount.google.com/permissions i uruchom ten skrypt jeszcze raz.")
        sys.exit(1)

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "refresh_token": tokens["refresh_token"],
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "token_uri": client["token_uri"],
        }, f, indent=2)

    print(f"[calendar_auth] Zapisano {TOKEN_FILE}. Autoryzacja wazna ~7 dni (tryb Testing).")


if __name__ == "__main__":
    run()
