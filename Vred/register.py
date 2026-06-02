"""
One-time registration for Vred bot.
Opens a real browser window — log in manually, then the script saves credentials.

Run once: py -3.12 register.py
"""
import asyncio
import json
import uuid
import re
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
import requests

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
import base64

from playwright.async_api import async_playwright

APP_VERSION  = "25.02.14 (G)"
USER_AGENT   = "Dart/3.3 (dart:io)"
VAPI         = "1"
DEVICE_MODEL = "Xiaomi MI 9"
OPERATING_SYSTEM = "Android"
VERSION_CODE = "621"
BASE_URL     = "https://lekcjaplus.vulcan.net.pl"


# ---------------------------------------------------------------------------
# Key pair generation
# ---------------------------------------------------------------------------

def generate_key_pair() -> dict:
    private_key = rsa.generate_private_key(65537, 2048, default_backend())

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "APP_CERTIFICATE CA Certificate"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365 * 20))
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    fingerprint = cert.fingerprint(hashes.SHA1()).hex()

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    cert_b64 = (
        cert_pem
        .replace("-----BEGIN CERTIFICATE-----\n", "")
        .replace("-----END CERTIFICATE-----\n", "")
        .replace("\n", "")
        .strip()
    )

    key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    key_b64 = (
        key_pem
        .replace("-----BEGIN PRIVATE KEY-----\n", "")
        .replace("-----END PRIVATE KEY-----\n", "")
        .replace("\n", "")
        .strip()
    )

    return {"fingerprint": fingerprint, "privateKey": key_b64, "certificate": cert_b64}


# ---------------------------------------------------------------------------
# Signing (same as client.py — duplicated intentionally to keep register standalone)
# ---------------------------------------------------------------------------

def _canonical_url(url: str) -> str:
    from urllib.parse import quote
    match = re.search(r"(api/mobile/.+)", url)
    if not match:
        raise ValueError(f"URL does not contain api/mobile/ path: {url}")
    return quote(match.group(1), safe="").lower()


def _sign_request(keypair: dict, body: dict | None, url: str) -> dict:
    from urllib.parse import quote
    date_utc = formatdate(usegmt=True)
    body_str = json.dumps(body, separators=(",", ":")) if body is not None else None

    canonical = _canonical_url(url)
    digest_raw = (
        base64.b64encode(hashlib.sha256(body_str.encode()).digest()).decode()
        if body_str else ""
    )

    sign_headers = ["vCanonicalUrl"]
    sign_values  = canonical
    if body_str:
        sign_headers.append("Digest")
        sign_values += digest_raw
    sign_headers.append("vDate")
    sign_values += date_utc

    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        + "\n".join(keypair["privateKey"][i:i+64] for i in range(0, len(keypair["privateKey"]), 64))
        + "\n-----END PRIVATE KEY-----"
    )
    pk = serialization.load_pem_private_key(pem.encode(), password=None)
    sig_bytes = pk.sign(sign_values.encode(), padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(sig_bytes).decode()

    headers = {
        "accept":          "*/*",
        "accept-charset":  "UTF-8",
        "accept-encoding": "gzip",
        "connection":      "Keep-Alive",
        "content-type":    "application/json",
        "host":            "lekcjaplus.vulcan.net.pl",
        "user-agent":      USER_AGENT,
        "vapi":            VAPI,
        "vdate":           date_utc,
        "vdevicemodel":    DEVICE_MODEL,
        "vos":             OPERATING_SYSTEM,
        "vversioncode":    VERSION_CODE,
        "signature":       f'keyId="{keypair["fingerprint"]}",headers="{" ".join(sign_headers)}",algorithm="sha256withrsa",signature=Base64(sha256withrsa({sig_b64}))',
        "vcanonicalurl":   canonical,
    }
    if digest_raw:
        headers["digest"] = f"SHA-256={digest_raw}"
    return headers, date_utc


# ---------------------------------------------------------------------------
# Registration flow
# ---------------------------------------------------------------------------

def parse_ap(html: str) -> dict:
    # value attribute may use single OR double quotes; match the right closing delimiter
    match = (
        re.search(r"id='ap'[^>]*value='([^']+)'", html) or
        re.search(r"value='([^']+)'[^>]*id='ap'", html) or
        re.search(r'id="ap"[^>]*value="([^"]+)"', html) or
        re.search(r'value="([^"]+)"[^>]*id="ap"', html)
    )
    if not match:
        raise RuntimeError("Could not find <input id='ap'> in /api/ap response — are you logged in?")
    raw = match.group(1).replace("&quot;", '"').replace("&#34;", '"')
    return json.loads(raw)


def _jwt_tenant(token: str) -> str:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64)).get("tenant", "")


def register_jwt(keypair: dict, tokens: list[str], base_urls: list[str]) -> list[dict]:
    now = datetime.now(timezone.utc)
    body = {
        "AppName":    "DzienniczekPlus 3.0",
        "AppVersion": APP_VERSION,
        "Envelope": {
            "OS":                    OPERATING_SYSTEM,
            "DeviceModel":           DEVICE_MODEL,
            "Certificate":           keypair["certificate"],
            "CertificateType":       "X509",
            "CertificateThumbprint": keypair["fingerprint"],
            "Tokens":                tokens,
            "selfIdentifier":        str(uuid.uuid4()),
        },
        "NotificationToken": "",
        "API":               int(VAPI),
        "RequestId":         str(uuid.uuid4()),
        "Timestamp":         int(now.timestamp()),
        "TimestampFormatted": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Serialize ONCE — same string for both signing and sending (digest must match)
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

    results = []
    for base in base_urls:
        url = f"{base}/api/mobile/register/jwt"
        headers, _ = _sign_request(keypair, body, url)
        r = requests.post(url, headers=headers, data=body_str.encode("utf-8"), timeout=15)
        print(f"   [{url}] → {r.status_code}")
        if r.status_code >= 400:
            print(f"   Response: {r.text[:300]}")
        r.raise_for_status()
        data = r.json()
        if data.get("Status", {}).get("Code", 0) != 0:
            raise RuntimeError(f"register/jwt error: {data['Status']}")
        results.append(data["Envelope"])
    return results


def fetch_pupils(keypair: dict, rest_url: str) -> list[dict]:
    url = f"{rest_url}/api/mobile/register/hebe?mode=2"
    headers, _ = _sign_request(keypair, None, url)
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("Status", {}).get("Code", 0) != 0:
        raise RuntimeError(f"register/hebe error: {data['Status']}")
    return data["Envelope"]


async def main():
    print("=== Vred — Rejestracja ===\n")
    print("Otwieram przeglądarkę. Zaloguj się ręcznie na eduvulcan.pl.")
    print("Po zalogowaniu wróć tu i naciśnij Enter.\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=100)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://eduvulcan.pl/logowanie")

        input(">>> Zaloguj się w przeglądarce, a potem naciśnij Enter tutaj...")

        # Wyciągnij tenant z aktualnego URL przeglądarki (np. /powiattomaszowskilubelskie/App/...)
        current_url = page.url
        print(f"   URL po logowaniu: {current_url}")
        from urllib.parse import urlparse
        path_parts = urlparse(current_url).path.strip("/").split("/")
        url_tenant = path_parts[0] if path_parts and path_parts[0] else None
        print(f"   Wykryty tenant: {url_tenant}")

        # Extract cookies from browser and use requests — avoids redirect issues
        print("\nPobieram tokeny z /api/ap...")
        all_cookies = await ctx.cookies()
        await browser.close()

    session = requests.Session()
    for c in all_cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

    r = session.get(
        "https://eduvulcan.pl/api/ap",
        headers={"User-Agent": USER_AGENT},
        allow_redirects=False,
        timeout=15,
    )
    if r.status_code in (301, 302, 303, 307, 308):
        # Try with redirects — sometimes needed
        r = session.get("https://eduvulcan.pl/api/ap", headers={"User-Agent": USER_AGENT}, timeout=15)

    html = r.text
    print(f"[DEBUG /api/ap] status={r.status_code} url={r.url}")
    print(f"[DEBUG /api/ap] pierwsze 500 znaków:\n{html[:500]}\n")
    ap = parse_ap(html)
    print(f"✅ Zalogowano jako: {ap.get('GivenName', '?')} {ap.get('Surname', '?')}")

    tokens = ap["Tokens"]

    # Tenant z JWT (hebece: `BASE_URL + decodeJwt(token).tenant`)
    tenants = list({_jwt_tenant(t) for t in tokens if "." in t} - {""})
    if not tenants:
        # fallback: spróbuj tenant z URL przeglądarki
        tenants = [url_tenant] if url_tenant and url_tenant != "logowanie" else []
    if not tenants:
        raise RuntimeError("Nie udało się wyciągnąć tenant z tokenów JWT")
    base_urls = [f"{BASE_URL}/{t}" for t in tenants]
    print(f"   Base URLs: {base_urls}")

    print("\nGeneruję parę kluczy RSA...")
    keypair = generate_key_pair()
    print(f"   Fingerprint: {keypair['fingerprint']}")

    print("Rejestruję klucz w Hebe API...")
    jwt_envelopes = register_jwt(keypair, tokens, base_urls)

    # Collect all RestURLs from jwt_envelopes
    rest_urls = list({e["RestURL"] for e in jwt_envelopes if e.get("RestURL")})
    if not rest_urls:
        rest_urls = base_urls
        print("⚠️  Brak RestURL w odpowiedzi — używam domyślnego BASE_URL")

    print("Pobieram dane ucznia...")
    pupils = []
    chosen_rest = rest_urls[0]
    for rest in rest_urls:
        try:
            pupils = fetch_pupils(keypair, rest)
            chosen_rest = rest
            break
        except Exception as e:
            print(f"   {rest} → {e}")

    if not pupils:
        raise RuntimeError("Nie udało się pobrać danych ucznia z żadnego RestURL")

    # Pick pupil (usually just one)
    if len(pupils) > 1:
        for i, p in enumerate(pupils):
            print(f"  [{i}] {p['Pupil']['FirstName']} {p['Pupil']['Surname']} — {p['Unit']['Name']}")
        idx = int(input("Wybierz ucznia (numer): "))
    else:
        idx = 0

    pupil = pupils[idx]
    print(f"✅ Wybrany uczeń: {pupil['Pupil']['FirstName']} {pupil['Pupil']['Surname']}")

    creds = {
        "fingerprint": keypair["fingerprint"],
        "privateKey":  keypair["privateKey"],
        "certificate": keypair["certificate"],
        "restUrl":     chosen_rest,
        "pupil":       pupil,
    }
    with open("credentials.json", "w", encoding="utf-8") as f:
        json.dump(creds, f, ensure_ascii=False, indent=2)

    print("\n✅ credentials.json zapisany. Możesz teraz uruchomić: py -3.12 main.py")


asyncio.run(main())
