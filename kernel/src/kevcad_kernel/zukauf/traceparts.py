"""CAD-Suche: TraceParts-API (einzige automatische Quelle, PLAN-PHASE3-ZUKAUF.md Z2) und Deep-Links zu Herstellerportalen
für den halbautomatischen Weg (Z3: Kevin lädt mit seinem Konto herunter, Kev CAD übernimmt aus ``~/Downloads``).

TraceParts (https://developers.traceparts.com/), Basis ``https://api-gateway.traceparts.com``:

1. ``POST /v2/RequestToken`` ``{"tenantUid", "apiKey"}`` → ``{"token", "expiryDate"}`` (JWT, als Bearer gesendet)
2. ``GET /v2/Search/PartNumber/Availability?partNumber=…&catalog=…&removeChar=true`` → ``partFamilyCode``,
   ``classificationCode``, ``partNumber``, ``selectionPath``, ``version``
3. ``GET /v3/Product/CadDataAvailability?partFamilyCode=…&selectionPath=…&cultureInfo=de`` → ``cadFormatList``
   (``cadFormatId``, ``cadFormatName``, ``deliveryMethod`` 1 = Datei-URL)
4. ``POST /v3/Product/cadRequest`` ``{"userEmail", "cultureInfo", "cadFormatId", "partFamilyCode", "selectionPath"}``
   → ``cadRequestId`` (Zahl)
5. ``GET /v2/Product/cadFileUrl?cadRequestId=…`` → 204 (noch nicht fertig, später erneut) oder 200 mit der URL

Zugang aus ``~/Library/Application Support/de.upvis.kevcad/secrets.env`` (nur für Kevin lesbar; für Tests
``KEVCAD_SECRETS_FILE``): ``TRACEPARTS_API_KEY``, ``TRACEPARTS_TENANT_UID``, ``TRACEPARTS_USER_EMAIL`` (Bedingung von
TraceParts: Name/E-Mail beim Download). Der Schlüssel erscheint nie in Logs, Fehlertexten oder MCP-Antworten.
Bedingungen: „powered by TraceParts“ anzeigen, keine Massenabrufe (ein Teil je Aufruf, wenige Abfragen).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE = "https://api-gateway.traceparts.com"
DEFAULT_SECRETS = Path.home() / "Library" / "Application Support" / "de.upvis.kevcad" / "secrets.env"
POWERED = "powered by TraceParts"
USER_AGENT = "KevCAD/0.1 (+TraceParts-API)"
STEP_WORTE = ("step ap242", "step ap214", "step ap203", "step", "stp")

# (status, json-or-text, bytes) = transport(method, url, headers, body_bytes)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any, bytes]]


class TracePartsFehler(RuntimeError):
    """Fehler der API (ohne Schlüssel im Text)."""


def secrets_path() -> Path:
    env = os.environ.get("KEVCAD_SECRETS_FILE")
    return Path(env).expanduser() if env else DEFAULT_SECRETS


def secrets(path: Path | None = None) -> dict[str, str]:
    """KEY=wert-Zeilen (Kommentare mit #, Anführungszeichen erlaubt). Fehlt die Datei: leer."""
    path = path or secrets_path()
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass
class Zugang:
    api_key: str
    tenant_uid: str
    user_email: str | None = None

    def __repr__(self) -> str:  # nie den Schlüssel zeigen
        return f"Zugang(tenant_uid={self.tenant_uid[:4]}…, user_email={'gesetzt' if self.user_email else 'fehlt'})"


def zugang(path: Path | None = None) -> tuple[Zugang | None, str | None]:
    """(Zugang, None) oder (None, Grund) – der Grund nennt nur fehlende Namen, nie Werte."""
    s = secrets(path)
    key, tenant = s.get("TRACEPARTS_API_KEY"), s.get("TRACEPARTS_TENANT_UID")
    if not key:
        return None, "Kein TraceParts-Schlüssel (TRACEPARTS_API_KEY in secrets.env): CAD halbautomatisch über Links"
    if not tenant:
        return None, "TRACEPARTS_TENANT_UID fehlt in secrets.env: CAD halbautomatisch über Links"
    return Zugang(key, tenant, s.get("TRACEPARTS_USER_EMAIL") or None), None


def _urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - feste https-Adresse der API
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        status = exc.code
    except urllib.error.URLError as exc:
        raise TracePartsFehler(f"TraceParts nicht erreichbar ({exc.reason})") from None
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = None
    return status, data, raw


class TraceParts:
    """Kleiner Client für die fünf Aufrufe oben. ``transport`` ist für Tests austauschbar (Attrappe)."""

    def __init__(self, zugang: Zugang, transport: Transport | None = None, *, base: str = BASE,
                 kultur: str = "de", sleep: Callable[[float], None] = time.sleep) -> None:
        self._z = zugang
        self._t = transport or _urllib_transport
        self._base = base.rstrip("/")
        self.kultur = kultur
        self._token: str | None = None
        self._token_bis = 0.0
        self._sleep = sleep
        self.aufrufe = 0

    def _call(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None,
              auth: bool = True) -> tuple[int, Any, bytes]:
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        if auth:
            headers["Authorization"] = f"Bearer {self._token_holen()}"
        self.aufrufe += 1
        status, payload, raw = self._t(method, url, headers, data)
        if status in (401, 403) and auth:
            raise TracePartsFehler(f"TraceParts lehnt den Zugang ab (HTTP {status}): Schlüssel oder Tenant prüfen")
        return status, payload, raw

    def _token_holen(self) -> str:
        if self._token and time.time() < self._token_bis - 60:
            return self._token
        status, data, _ = self._call("POST", "/v2/RequestToken", auth=False,
                                     body={"tenantUid": self._z.tenant_uid, "apiKey": self._z.api_key})
        if status != 200 or not isinstance(data, dict) or not data.get("token"):
            raise TracePartsFehler(f"TraceParts-Anmeldung fehlgeschlagen (HTTP {status}): Schlüssel und Tenant in "
                                   "secrets.env prüfen")
        self._token = str(data["token"])
        self._token_bis = time.time() + 3600
        exp = data.get("expiryDate")
        if isinstance(exp, str):
            try:
                from datetime import datetime

                self._token_bis = datetime.fromisoformat(exp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return self._token

    def verfuegbar(self, mpn: str, katalog: str) -> dict[str, Any] | None:
        """Teil im TraceParts-Katalog des Herstellers (None = nicht gefunden)."""
        status, data, _ = self._call("GET", "/v2/Search/PartNumber/Availability",
                                     params={"partNumber": mpn, "catalog": katalog, "removeChar": "true"})
        if status in (204, 404):
            return None
        if status != 200:
            raise TracePartsFehler(f"TraceParts-Suche fehlgeschlagen (HTTP {status})")
        if not isinstance(data, dict) or not (data.get("partFamilyCode") or data.get("partNumber")):
            return None
        return data

    def formate(self, teil: dict[str, Any]) -> list[dict[str, Any]]:
        params = {"cultureInfo": self.kultur}
        if teil.get("partFamilyCode"):
            params.update(partFamilyCode=teil["partFamilyCode"], selectionPath=teil.get("selectionPath"))
        else:
            params.update(classificationCode=teil.get("classificationCode"), partNumber=teil.get("partNumber"))
        status, data, _ = self._call("GET", "/v3/Product/CadDataAvailability", params=params)
        if status != 200 or not isinstance(data, dict):
            raise TracePartsFehler(f"TraceParts liefert keine CAD-Formate (HTTP {status})")
        return list(data.get("cadFormatList") or [])

    @staticmethod
    def step_format(formate: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Bestes STEP-Format mit direkter Datei-URL (deliveryMethod 1)."""
        direkt = [f for f in formate if int(f.get("deliveryMethod") or 0) == 1]
        for wort in STEP_WORTE:
            for f in direkt:
                if wort in str(f.get("cadFormatName") or "").lower():
                    return f
        return None

    def anfordern(self, teil: dict[str, Any], format_id: int) -> int:
        if not self._z.user_email:
            raise TracePartsFehler("TRACEPARTS_USER_EMAIL fehlt in secrets.env (TraceParts verlangt eine E-Mail je "
                                   "Download)")
        body: dict[str, Any] = {"userEmail": self._z.user_email, "cultureInfo": self.kultur, "cadFormatId": format_id}
        if teil.get("partFamilyCode"):
            body["partFamilyCode"] = teil["partFamilyCode"]
            if teil.get("selectionPath"):
                body["selectionPath"] = teil["selectionPath"]
        else:
            body.update(classificationCode=teil.get("classificationCode"), partNumber=teil.get("partNumber"))
        status, data, raw = self._call("POST", "/v3/Product/cadRequest", body=body)
        rid = data if isinstance(data, int) else (int(raw) if raw.strip().isdigit() else None)
        if status != 200 or rid is None:
            raise TracePartsFehler(f"TraceParts nimmt die CAD-Anfrage nicht an (HTTP {status})")
        return int(rid)

    def datei_url(self, request_id: int, *, versuche: int = 8, warten_s: float = 3.0) -> str:
        """Wartet, bis TraceParts die Datei erzeugt hat (204 = noch nicht), höchstens ``versuche`` Abfragen."""
        for i in range(versuche):
            status, data, raw = self._call("GET", "/v2/Product/cadFileUrl", params={"cadRequestId": request_id})
            if status == 200:
                url = data if isinstance(data, str) else raw.decode("utf-8", "replace").strip().strip('"')
                if url.startswith("http"):
                    return url
                raise TracePartsFehler("TraceParts liefert keine Datei-URL")
            if status != 204:
                raise TracePartsFehler(f"TraceParts-Datei nicht verfügbar (HTTP {status})")
            self._sleep(warten_s * (1 + i * 0.5))
        raise TracePartsFehler("TraceParts erzeugt die Datei noch: später erneut cad_suchen aufrufen")

    def laden(self, url: str, ziel_dir: Path, name: str) -> Path:
        """Datei-URL herunterladen (ohne Bearer: die URL ist schon signiert)."""
        status, _, raw = self._t("GET", url, {}, None)
        self.aufrufe += 1
        if status != 200 or not raw:
            raise TracePartsFehler(f"Download der CAD-Datei fehlgeschlagen (HTTP {status})")
        ziel_dir.mkdir(parents=True, exist_ok=True)
        ext = ".zip" if raw[:2] == b"PK" else ".step"
        path = ziel_dir / f"{re.sub(r'[^A-Za-z0-9._-]+', '_', name)}{ext}"
        path.write_bytes(raw)
        return path

    def holen(self, mpn: str, katalog: str, ziel_dir: Path, name: str) -> dict[str, Any]:
        """Ganzer Ablauf: suchen, STEP-Format wählen, anfordern, warten, laden. Rückgabe {"datei", "teil",
        "format"} oder {"gefunden": False}."""
        teil = self.verfuegbar(mpn, katalog)
        if teil is None:
            return {"gefunden": False}
        fmt = self.step_format(self.formate(teil))
        if fmt is None:
            return {"gefunden": True, "teil": teil, "format": None}
        rid = self.anfordern(teil, int(fmt["cadFormatId"]))
        url = self.datei_url(rid)
        path = self.laden(url, ziel_dir, name)
        return {"gefunden": True, "teil": teil, "format": fmt, "datei": str(path)}


# ---------------------------------------------------------------------------------------------------------------------
# Deep-Links (halbautomatisch)

# Suchadressen der Portale; die Muster sind beim ersten Einsatz im Browser zu prüfen (Portale ändern ihre Pfade)
PORTALE: dict[str, tuple[str, str]] = {
    "traceparts": ("TraceParts", "https://www.traceparts.com/de/search?Keywords={q}"),
    "3dfindit": ("3Dfindit (CADENAS/PARTcommunity)", "https://www.3dfindit.com/de/?q={q}"),
    "misumi": ("MISUMI", "https://de.misumi-ec.com/vona2/result/?Keyword={q}"),
    "item": ("item", "https://www.item24.com/de-de/search/?q={q}"),
    "igus": ("igus", "https://www.igus.de/search?q={q}"),
    "mcmaster": ("McMaster-Carr", "https://www.mcmaster.com/{q}/"),
    "suche": ("Websuche", "https://duckduckgo.com/?q={q}"),
}
_HERSTELLER_PORTAL = {"misumi": "misumi", "item": "item", "igus": "igus", "mcmaster": "mcmaster",
                      "mcmaster-carr": "mcmaster", "mcmastercarr": "mcmaster"}


def _q(text: str) -> str:
    return urllib.parse.quote_plus(text.strip())


def cad_links(entry: dict[str, Any]) -> list[dict[str, str]]:
    """Links zum Öffnen im Browser (``{titel, url}``): Produktseite, Herstellerportal, TraceParts, 3Dfindit, Websuche."""
    mpn = str(entry.get("mpn") or entry.get("shop_nr") or "").strip()
    hersteller = str(entry.get("hersteller") or "").strip()
    links: list[dict[str, str]] = []
    if entry.get("url"):
        links.append({"titel": "Produktseite (CAD-Download oft dort)", "url": str(entry["url"])})
    key = re.sub(r"[^a-z]", "", hersteller.lower())
    portal = next((p for h, p in _HERSTELLER_PORTAL.items() if key.startswith(h.replace("-", ""))), None)
    query = " ".join(x for x in (hersteller, mpn) if x) or str(entry.get("name") or "")
    if portal and mpn:
        titel, muster = PORTALE[portal]
        links.append({"titel": f"{titel}: CAD zu {mpn}", "url": muster.format(q=_q(mpn) if portal != "mcmaster"
                                                                             else urllib.parse.quote(mpn))})
    if query:
        for p in ("traceparts", "3dfindit"):
            titel, muster = PORTALE[p]
            links.append({"titel": f"{titel}: {query}", "url": muster.format(q=_q(query))})
        titel, muster = PORTALE["suche"]
        links.append({"titel": f"{titel}: {query} STEP", "url": muster.format(q=_q(f"{query} STEP CAD download"))})
    seen: set[str] = set()
    out = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            out.append(link)
    return out
