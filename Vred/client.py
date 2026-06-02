"""
Hebe API client for eduvulcan.pl
Based on reverse engineering of hebece (https://github.com/hypedevss/hebece)
"""
import hashlib
import base64
import json
import re
import uuid
from datetime import datetime, timedelta
from email.utils import formatdate
from urllib.parse import quote
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# --- Constants matching the mobile app ---
USER_AGENT   = "Dart/3.3 (dart:io)"
OPERATING_SYSTEM = "Android"
VERSION_CODE = "621"
VAPI         = "1"
DEVICE_MODEL = "Xiaomi MI 9"
APP_VERSION  = "25.02.14 (G)"
BASE_URL     = "https://lekcjaplus.vulcan.net.pl"


# ---------------------------------------------------------------------------
# Request signing
# ---------------------------------------------------------------------------

def _canonical_url(url: str) -> str:
    match = re.search(r"(api/mobile/.+)", url)
    if not match:
        raise ValueError(f"URL does not contain api/mobile/ path: {url}")
    return quote(match.group(1), safe="").lower()


def _digest(body_str: str | None) -> str:
    if body_str is None:
        return ""
    return base64.b64encode(hashlib.sha256(body_str.encode()).digest()).decode()


def _sign(fingerprint: str, private_key_b64: str, body_str: str | None, url: str, date_utc: str) -> dict:
    canonical = _canonical_url(url)
    digest = _digest(body_str)

    sign_headers = ["vCanonicalUrl"]
    sign_values  = canonical

    if body_str is not None:
        sign_headers.append("Digest")
        sign_values += digest

    sign_headers.append("vDate")
    sign_values += date_utc

    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        + "\n".join(private_key_b64[i:i+64] for i in range(0, len(private_key_b64), 64))
        + "\n-----END PRIVATE KEY-----"
    )
    private_key = serialization.load_pem_private_key(pem.encode(), password=None)
    sig_bytes = private_key.sign(sign_values.encode(), padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(sig_bytes).decode()

    return {
        "digest":       f"SHA-256={digest}",
        "canonicalUrl": canonical,
        "signature":    f'keyId="{fingerprint}",headers="{" ".join(sign_headers)}",algorithm="sha256withrsa",signature=Base64(sha256withrsa({sig_b64}))',
    }


def _build_headers(fingerprint: str, private_key_b64: str, body: dict | None, url: str) -> dict:
    date_utc = formatdate(usegmt=True)
    body_str = json.dumps(body, separators=(",", ":")) if body is not None else None
    sig = _sign(fingerprint, private_key_b64, body_str, url, date_utc)

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
        "signature":       sig["signature"],
        "vcanonicalurl":   sig["canonicalUrl"],
    }
    if sig["digest"] != "SHA-256=":
        headers["digest"] = sig["digest"]
    return headers


# ---------------------------------------------------------------------------
# VulcanClient
# ---------------------------------------------------------------------------

class VulcanClient:
    def __init__(self, credentials_path: str = "credentials.json"):
        with open(credentials_path, encoding="utf-8") as f:
            creds = json.load(f)
        self._fingerprint = creds["fingerprint"]
        self._private_key = creds["privateKey"]
        self._rest_url    = creds["restUrl"]      # e.g. https://lekcjaplus.vulcan.net.pl/symbol
        self._pupil       = creds["pupil"]         # PupilEnvelope dict
        self._session     = requests.Session()

    def _get(self, url: str) -> dict:
        headers = _build_headers(self._fingerprint, self._private_key, None, url)
        r = self._session.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("Status", {}).get("Code", 0) != 0:
            raise RuntimeError(f"API error: {data['Status']}")
        return data

    def _pupil_id(self)  -> int: return self._pupil["Pupil"]["Id"]
    def _unit_id(self)   -> int: return self._pupil["Unit"]["Id"]
    def _symbol(self)    -> str: return self._pupil["Unit"]["Symbol"]
    def _period_id(self) -> int:
        for p in self._pupil["Periods"]:
            if p["Current"]:
                return p["Id"]
        return self._pupil["Periods"][-1]["Id"]

    def get_lessons(self, date_from: datetime, date_to: datetime) -> list:
        df = date_from.strftime("%Y-%m-%d")
        dt = date_to.strftime("%Y-%m-%d")
        url = (
            f"{self._rest_url}/{self._symbol()}/api/mobile/schedule/byPupil"
            f"?unitId={self._unit_id()}&pupilId={self._pupil_id()}"
            f"&periodId={self._period_id()}&dateFrom={df}&dateTo={dt}&pageSize=100"
        )
        return self._get(url)["Envelope"]

    def get_exams(self, date_from: datetime, date_to: datetime) -> list:
        df = date_from.strftime("%Y-%m-%d")
        dt = date_to.strftime("%Y-%m-%d")
        url = (
            f"{self._rest_url}/{self._symbol()}/api/mobile/exam/byPupil"
            f"?unitId={self._unit_id()}&pupilId={self._pupil_id()}"
            f"&dateFrom={df}&dateTo={dt}&pageSize=100"
        )
        return self._get(url)["Envelope"]

    def get_lucky_number(self) -> int | None:
        today = datetime.now().strftime("%Y-%m-%d")
        constituent_id = self._pupil.get("ConstituentUnit", {}).get("Id", 0)
        url = (
            f"{self._rest_url}/{self._symbol()}/api/mobile/school/lucky"
            f"?unitId={self._unit_id()}&constituentId={constituent_id}&day={today}"
        )
        try:
            return self._get(url)["Envelope"]["Number"]
        except Exception:
            return None
