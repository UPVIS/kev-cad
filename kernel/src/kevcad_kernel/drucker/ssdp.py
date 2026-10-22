"""Bambu-Drucker im LAN passiv erkennen: SSDP-Ankündigungen (``NOTIFY``) auf UDP 2021 mithören.

Nur zuhören, nichts senden (keine M-SEARCH-Anfrage, keine Portscans). Der Drucker schickt etwa alle 5 s einen Broadcast
mit ``Location`` (IPv4), ``USN`` (Seriennummer), ``DevModel.bambu.com`` (P1P = ``C11``), ``DevName.bambu.com``,
``DevConnect.bambu.com`` (``lan``/``cloud``) u. a. (open-bamboo-networking, Bambu-Forum). Die Seriennummer verlässt
dieses Modul nie: nach außen geht nur ``kennung`` (die ersten 12 Hex-Zeichen von SHA-256).
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PORT = 2021
MODELLE: dict[str, str] = {
    "C11": "P1P", "C12": "P1S", "C13": "X1E", "BL-P001": "X1C", "BL-P002": "X1", "N1": "A1 mini", "N2S": "A1",
    "3DPrinter-X1-Carbon": "X1C", "3DPrinter-X1": "X1",
}  # Codes aus den Maschinenprofilen von Bambu Studio (model_id); unbekannte Codes erscheinen unverändert
VERFALL_S = 120.0  # nicht mehr gehört → aus der Liste


def kennung(seriennummer: str) -> str:
    return hashlib.sha256(seriennummer.strip().encode("utf-8")).hexdigest()[:12]


@dataclass
class Fund:
    name: str
    modell: str
    ip: str
    verbindung: str | None
    kennung: str
    zuletzt: float

    def als_dict(self) -> dict[str, Any]:
        return {"name": self.name, "modell": self.modell, "ip": self.ip, "verbindung": self.verbindung,
                "kennung": self.kennung}


def lies_notify(daten: bytes, absender_ip: str | None = None, jetzt: float | None = None) -> Fund | None:
    """Ein SSDP-Paket lesen; None, wenn es keine Ankündigung eines Bambu-Druckers ist."""
    try:
        text = daten.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    zeilen = text.replace("\r\n", "\n").split("\n")
    if not zeilen or not zeilen[0].upper().startswith("NOTIFY"):
        return None
    kopf: dict[str, str] = {}
    for z in zeilen[1:]:
        if ":" in z:
            k, v = z.split(":", 1)
            kopf[k.strip().lower()] = v.strip()
    if "bambulab" not in kopf.get("nt", "").lower() and "devmodel.bambu.com" not in kopf:
        return None
    usn = kopf.get("usn", "")
    if not usn:
        return None
    ip = kopf.get("location", "") or (absender_ip or "")
    ip = ip.replace("http://", "").split("/")[0].split(":")[0]
    modell_code = kopf.get("devmodel.bambu.com", "")
    verbindung = kopf.get("devconnect.bambu.com", "").lower() or None
    if verbindung not in (None, "lan", "cloud"):
        verbindung = None
    return Fund(name=kopf.get("devname.bambu.com", "") or MODELLE.get(modell_code, "Bambu-Drucker"),
                modell=MODELLE.get(modell_code, modell_code or "?"), ip=ip, verbindung=verbindung,
                kennung=kennung(usn), zuletzt=time.time() if jetzt is None else jetzt)


class Lauscher:
    """Hört im Hintergrund auf UDP 2021 (SO_REUSEPORT, damit Bambu Studio daneben weiter hört)."""

    def __init__(self, bei_aenderung: Callable[[], None], *, port: int = PORT,
                 log: Callable[[str], None] | None = None) -> None:
        self.port = port
        self._bei_aenderung = bei_aenderung
        self._log = log or (lambda _t: None)
        self._lock = threading.Lock()
        self._funde: dict[str, Fund] = {}
        self._sock: socket.socket | None = None
        self._faden: threading.Thread | None = None
        self._halt = threading.Event()
        self.fehler: str | None = None

    def starten(self) -> None:
        if self._faden is not None:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.bind(("", self.port))
            s.settimeout(1.0)
        except OSError as exc:
            self.fehler = f"SSDP-Port {self.port} nicht frei ({exc.strerror or exc})"
            self._log(f"[drucker] {self.fehler}")
            return
        self._sock = s
        self._halt.clear()
        self._faden = threading.Thread(target=self._schleife, name="kevcad-drucker-ssdp", daemon=True)
        self._faden.start()

    def stoppen(self) -> None:
        self._halt.set()
        f, self._faden = self._faden, None
        if f is not None:
            f.join(timeout=2.0)
        s, self._sock = self._sock, None
        if s is not None:
            s.close()

    def aufnehmen(self, fund: Fund) -> None:
        with self._lock:
            alt = self._funde.get(fund.kennung)
            self._funde[fund.kennung] = fund
            neu = alt is None or (alt.ip, alt.verbindung, alt.name) != (fund.ip, fund.verbindung, fund.name)
        if neu:
            self._bei_aenderung()

    def funde(self, jetzt: float | None = None) -> list[Fund]:
        jetzt = time.time() if jetzt is None else jetzt
        with self._lock:
            for k in [k for k, f in self._funde.items() if jetzt - f.zuletzt > VERFALL_S]:
                del self._funde[k]
            return sorted(self._funde.values(), key=lambda f: (f.name, f.ip))

    def _schleife(self) -> None:
        while not self._halt.is_set():
            s = self._sock
            if s is None:
                return
            try:
                daten, (ip, _port) = s.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            fund = lies_notify(daten, ip)
            if fund is not None:
                self.aufnehmen(fund)
