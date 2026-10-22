"""Drucken aus Kev CAD (Phase 8): Einstellungen, Verbindung, Aufträge und ``PRINTER_STATUS`` an einer Stelle.

Unabhängig von der Kernel-Laufzeit (alles von außen hereingereicht), damit Tests ohne App, Bambu Studio und Drucker
laufen. Die Laufzeit (``laufzeit.py``) verbindet den Dienst mit dem App-Socket, dem Projekt und der Druckvorschau.

Aufträge laufen nacheinander in einem eigenen Faden. Ein neues Vorbereiten bricht ein laufendes Slicen ab. Weg A:
slicen → in ``<projekt>/output`` kopieren → in Bambu Studio öffnen. Weg B (gesperrt): Sperre → slicen → FTPS → MQTT.
"""

from __future__ import annotations

import itertools
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kevcad_kernel.drucker import befehle, schluesselbund, sperre, ssdp
from kevcad_kernel.drucker.mqtt import MqttVerbindung
from kevcad_kernel.drucker.profile import BAMBU_APP, Profile, ProfilFehler
from kevcad_kernel.drucker.slicen import CACHE, Abgebrochen, SliceErgebnis, SlicenFehler
from kevcad_kernel.drucker.slicen import platten_md5, slicen, vorhanden

WEGE = ("a", "b")
MELDE_ABSTAND_S = 0.5
AUFTRAG_ZUSTAENDE = ("wartet", "slict", "bereit", "oeffnet", "geoeffnet", "laedt_hoch", "startet", "gestartet",
                     "fehler", "verworfen")


class QuelleFehler(Exception):
    """Die Platten lassen sich nicht bereitstellen (kein Projekt, keine Druckteile, Druckvorschau fehlt …)."""


@dataclass
class Quelle:
    """Was gesliced wird, bereitgestellt von der Laufzeit (Druckvorschau oder Ersatzweg)."""

    name: str  # Dateiname ohne Endung, z. B. "Kugelschieber-platten"
    eingaben: list[Path]
    ausgabe: Path  # <projekt>/output
    mit_einstellungen: bool = False  # 3MF bringt Bambu-Projekteinstellungen mit
    anordnen: bool = False
    ausrichten: bool = False
    prozess: str | None = None  # Profilname, wenn der Kernel Profile lädt
    filamente: list[str] = field(default_factory=list)
    platte: str | None = None  # Druckplatte (Bambu-Name), sonst die des Druckermodells
    platten: list[int] = field(default_factory=list)  # Plattennummern der Vorschau in Reihenfolge der Ausgabe
    hinweise: list[str] = field(default_factory=list)
    run: int | None = None


@dataclass
class Eintrag:
    """Ein Drucker aus ``drucker.json`` der App (ohne Geheimnisse)."""

    id: str
    name: str = "P1P"
    modell: str = "C11"
    ip: str = ""
    weg: str = "a"
    status_lesen: bool = False
    port_mqtt: int | None = None  # nur Attrappe (127.0.0.1)
    port_ftps: int | None = None

    @classmethod
    def aus(cls, d: dict[str, Any] | None) -> "Eintrag | None":
        if not isinstance(d, dict):
            return None
        did = str(d.get("id") or "")
        schluesselbund.pruefe_id(did)
        weg = str(d.get("weg") or "a").lower()
        if weg not in WEGE:
            weg = "a"
        e = cls(id=did, name=str(d.get("name") or "P1P")[:60], modell=str(d.get("modell") or "C11")[:20],
                ip=str(d.get("ip") or "").strip()[:64], weg=weg, status_lesen=bool(d.get("status_lesen", False)))
        if e.ip in ("127.0.0.1", "localhost", "::1"):  # Ports nur für die Attrappe änderbar
            for k in ("port_mqtt", "port_ftps"):
                v = d.get(k)
                if isinstance(v, int) and 0 < v < 65536:
                    setattr(e, k, v)
        return e


@dataclass
class Auftrag:
    id: str
    platten: list[int]
    weg: str
    von: str = "kevin"
    zustand: str = "wartet"
    fortschritt: float | None = None
    meldung: str | None = None
    grund: str | None = None
    datei: Path | None = None  # gesliced (Zwischenspeicher)
    ziel: Path | None = None  # Kopie im Projekt (Weg A)
    ergebnis: SliceErgebnis | None = None
    quelle_platten: list[int] = field(default_factory=list)
    run: int | None = None
    optionen: dict[str, Any] = field(default_factory=dict)
    name: str = "platten"  # Dateiname der Ausgabe ohne Endung
    ausgabe: Path | None = None  # <projekt>/output
    erstellt: float = field(default_factory=time.time)

    def als_dict(self) -> dict[str, Any]:
        datei = self.ziel or self.datei
        return {"auftrag": self.id, "zustand": self.zustand, "weg": self.weg, "platten": list(self.platten),
                "fortschritt": None if self.fortschritt is None else round(self.fortschritt, 3),
                "meldung": self.meldung, "datei": str(datei) if datei else None, "von": self.von}


def oeffne_in_bambu_studio(datei: Path, app: Path = BAMBU_APP) -> None:
    """``open -a BambuStudio <datei>``: Studio öffnet die .gcode.3mf in der Vorschau (neues Fenster, wenn es läuft)."""
    res = subprocess.run(["/usr/bin/open", "-a", str(app), str(datei)], capture_output=True, text=True, timeout=30,
                         check=False)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or "open fehlgeschlagen").strip()[:200])


class DruckerDienst:
    def __init__(self, *, senden: Callable[[dict[str, Any]], bool], quelle: Callable[[list[int], Path], Quelle],
                 log: Callable[[str], None] | None = None, app: Path = BAMBU_APP, cache: Path = CACHE,
                 zugang_lesen: Callable[[str], schluesselbund.Zugang] = schluesselbund.lesen,
                 oeffnen: Callable[[Path], None] | None = None, ssdp_an: bool = True, ca_datei: str | None = None,
                 profile: Callable[[], Profile] | None = None, mqtt_zeitlimit_s: float = 10.0) -> None:
        self._senden_fn = senden
        self._quelle_fn = quelle
        self._log = log or (lambda _t: None)
        self.app = Path(app)
        self.cache = Path(cache)
        self._zugang_lesen = zugang_lesen
        self._oeffnen = oeffnen or (lambda p: oeffne_in_bambu_studio(p, self.app))
        self._ca = ca_datei
        self._profile_fn = profile or (lambda: Profile(self.app))
        self._mqtt_zeitlimit_s = mqtt_zeitlimit_s
        self._lock = threading.RLock()
        self.eintrag: Eintrag | None = None
        self._mqtt: MqttVerbindung | None = None
        self._kennung: str | None = None  # Hash der Seriennummer der laufenden Verbindung (für SSDP)
        self._verbindungsfehler: str | None = None
        self._auftrag: Auftrag | None = None
        self._auftraege = itertools.count(1)
        self._fragen = itertools.count(1)
        self._arbeit: queue.Queue = queue.Queue()
        self._abbruch = threading.Event()
        self._letzte_meldung = 0.0
        self._melde_timer: threading.Timer | None = None
        self._zu = False
        self._lauscher = ssdp.Lauscher(self._melden, log=self._log) if ssdp_an else None
        self._ssdp_gestartet = False
        self._faden = threading.Thread(target=self._arbeiten, name="kevcad-drucker", daemon=True)
        self._faden.start()

    # =================================================================================================================
    # Einstellungen und Verbindung

    def konfigurieren(self, daten: dict[str, Any] | None) -> tuple[bool, str]:
        """``PRINTER_CONFIG``: Eintrag übernehmen, Verbindung neu aufbauen, wenn sich Verbindungsdaten ändern."""
        try:
            neu = Eintrag.aus(daten)
        except schluesselbund.SchluesselbundFehler as exc:
            return False, str(exc)
        self._ssdp_starten()
        with self._lock:
            alt = self.eintrag
            self.eintrag = neu
            verbinden_neu = (alt is None or neu is None or (alt.id, alt.ip, alt.status_lesen, alt.port_mqtt)
                             != (neu.id, neu.ip, neu.status_lesen, neu.port_mqtt))
        if verbinden_neu:
            self._verbindung_neu()
        self._melden()
        if neu is None:
            return True, "Kein Drucker eingestellt"
        return True, f"Drucker {neu.name} eingestellt (Weg {neu.weg.upper()})"

    def _ssdp_starten(self) -> None:
        if self._lauscher is not None and not self._ssdp_gestartet:
            self._ssdp_gestartet = True
            self._lauscher.starten()

    def _verbindung_neu(self) -> None:
        with self._lock:
            alt, self._mqtt = self._mqtt, None
            self._kennung = None
            self._verbindungsfehler = None
            e = self.eintrag
        if alt is not None:
            alt.stoppen()
        if e is None or not e.status_lesen or not e.ip:
            return
        threading.Thread(target=self._verbinden, args=(e,), name="kevcad-drucker-verbinden", daemon=True).start()

    def _verbinden(self, e: Eintrag) -> None:
        try:
            zugang = self._zugang_lesen(e.id)
        except schluesselbund.SchluesselbundFehler as exc:
            with self._lock:
                self._verbindungsfehler = str(exc)
            self._melden()
            return
        except Exception:  # noqa: BLE001 – nie Inhalte aus dem Fehler weitergeben
            with self._lock:
                self._verbindungsfehler = "Schlüsselbund nicht lesbar"
            self._melden()
            return
        with self._lock:
            if self.eintrag is not e or self._zu:
                return
            v = MqttVerbindung(e.ip, zugang, bei_aenderung=self._melden, lage=self._lage_fuer_mqtt,
                               port=e.port_mqtt or 8883, ca_datei=self._ca_fuer(e), zeitlimit_s=self._mqtt_zeitlimit_s,
                               log=self._log)
            self._mqtt = v
            self._kennung = ssdp.kennung(zugang.seriennummer)
        del zugang
        v.starten()

    def _ca_fuer(self, e: Eintrag) -> str | None:
        """Eigene CA nur für die Attrappe auf 127.0.0.1; echte Drucker immer gegen die Bambu-CAs."""
        return self._ca if self._ca and e.ip in ("127.0.0.1", "localhost", "::1") else None

    def _ssdp_modus(self) -> str | None:
        f = self._fund()
        return f.verbindung if f is not None else None

    def _fund(self) -> ssdp.Fund | None:
        if self._lauscher is None:
            return None
        with self._lock:
            kennung = self._kennung
            ip = self.eintrag.ip if self.eintrag else None
        funde = self._lauscher.funde()
        for f in funde:
            if kennung and f.kennung == kennung:
                return f
        for f in funde:
            if ip and f.ip == ip:
                return f
        return None

    def _lage_fuer_mqtt(self) -> tuple[str, str | None]:
        with self._lock:
            weg = self.eintrag.weg if self.eintrag else "a"
        return weg, self._ssdp_modus()

    def lage(self) -> sperre.Lage:
        with self._lock:
            v = self._mqtt
            weg = self.eintrag.weg if self.eintrag else "a"
        if v is None:
            from kevcad_kernel.drucker.status import Bericht

            return sperre.lage_aus(weg, False, Bericht(), self._ssdp_modus())
        return sperre.lage_aus(weg, v.verbindung == "verbunden", v.bericht, self._ssdp_modus())

    # =================================================================================================================
    # Status

    def status(self) -> dict[str, Any]:
        with self._lock:
            e = self.eintrag
            v = self._mqtt
            fehler_verbindung = self._verbindungsfehler
            auftrag = self._auftrag.als_dict() if self._auftrag else None
        lage = self.lage()
        bericht = v.bericht if v is not None else None
        if e is None:
            verbindung, meldung = "aus", "Kein Drucker eingestellt (Drucker-Einstellungen). Weg A geht trotzdem."
        elif not e.status_lesen:
            verbindung, meldung = "aus", "„Status lesen“ ist aus; Kev CAD öffnet die Platten trotzdem in Bambu Studio."
        elif not e.ip:
            verbindung, meldung = "aus", "IP-Adresse fehlt (Drucker-Einstellungen)."
        elif fehler_verbindung:
            verbindung, meldung = "fehler", fehler_verbindung
        elif v is None:
            verbindung, meldung = "verbindet", "Zugangsdaten werden gelesen …"
        else:
            verbindung, meldung = v.verbindung, v.meldung
        fund = self._fund()
        drucker = None
        if e is not None:
            modus = fund.verbindung if fund and fund.verbindung else None
            if modus is None and lage.entwicklermodus:
                modus = "lan"
            drucker = {"id": e.id, "name": e.name, "modell": ssdp.MODELLE.get(e.modell, e.modell or "P1P"),
                       "ip": e.ip or (fund.ip if fund else None),
                       "firmware": bericht.firmware if bericht else None, "modus": modus or "unbekannt",
                       "entwicklermodus": lage.entwicklermodus, "signal": bericht.signal if bericht else None}
        grund_b = sperre.grund_weg_b(lage)
        a_moeglich = vorhanden(self.app)
        wege = {"a": {"moeglich": a_moeglich,
                      "grund": None if a_moeglich else f"Bambu Studio fehlt ({self.app})."},
                "b": {"moeglich": grund_b is None, "grund": grund_b, "anleitung": list(sperre.ANLEITUNG_WEG_B)}}
        steuern = e is not None and sperre.pruefe_steuern(lage) is None
        hat_bericht = bericht is not None and bool(bericht.druck)
        funde = self._lauscher.funde() if self._lauscher is not None else []
        return {
            "konfiguriert": e is not None, "verbindung": verbindung, "meldung": meldung, "drucker": drucker,
            "weg": e.weg if e else "a", "wege": wege, "steuern": steuern,
            "druck": bericht.druck_status() if hat_bericht else None,
            "temperaturen": bericht.temperaturen() if hat_bericht else None,
            "fehler": bericht.fehler() if hat_bericht else [],
            "kamera": False,
            "gefunden": [f.als_dict() for f in funde],
            "auftrag": auftrag,
            "aktualisiert": round(time.time(), 3),
        }

    def _melden(self) -> None:
        """``PRINTER_STATUS`` an die App, höchstens alle 0,5 s (der letzte Stand kommt immer an)."""
        with self._lock:
            if self._zu:
                return
            jetzt = time.monotonic()
            warte = self._letzte_meldung + MELDE_ABSTAND_S - jetzt
            if warte > 0:
                if self._melde_timer is None:
                    self._melde_timer = threading.Timer(warte, self._melden_jetzt)
                    self._melde_timer.daemon = True
                    self._melde_timer.start()
                return
            self._letzte_meldung = jetzt
        self._senden({"type": "PRINTER_STATUS", **self.status()})

    def _melden_jetzt(self) -> None:
        with self._lock:
            self._melde_timer = None
            self._letzte_meldung = time.monotonic()
            if self._zu:
                return
        self._senden({"type": "PRINTER_STATUS", **self.status()})

    def _senden(self, header: dict[str, Any]) -> bool:
        try:
            return bool(self._senden_fn(header))
        except Exception as exc:  # noqa: BLE001
            self._log(f"[drucker] Senden an die App fehlgeschlagen: {type(exc).__name__}")
            return False

    # =================================================================================================================
    # Aufträge

    def auftrag(self) -> Auftrag | None:
        with self._lock:
            return self._auftrag

    def anfragen(self, platten: list[int] | None, weg: str, grund: str | None) -> Auftrag:
        """MCP ``drucken``: Auftrag anlegen, der auf Kevins Bestätigung wartet (``PRINT_JOB_ASK`` schickt die Laufzeit)."""
        weg = weg if weg in WEGE else "a"
        a = Auftrag(id=f"j-{next(self._auftraege)}", platten=[int(p) for p in (platten or [])], weg=weg, von="agent",
                    zustand="wartet", grund=grund, meldung="Wartet auf Kevins Bestätigung in Kev CAD.")
        with self._lock:
            self._auftrag = a
        self._melden()
        return a

    def auftrag_anfordern(self, header: dict[str, Any], antworten: Callable[[dict[str, Any]], None]) -> tuple[bool, str]:
        """``PRINT_JOB_REQ``: prüfen, Auftrag anlegen bzw. fortführen und in den Arbeitsfaden stellen."""
        weg = str(header.get("weg") or "a").lower()
        if weg not in WEGE:
            return False, f"Weg {weg!r} unbekannt (a oder b)"
        bestaetigt = header.get("bestaetigt") is True
        platten = [int(p) for p in (header.get("platten") or []) if isinstance(p, int | float)]
        optionen = header.get("optionen") if isinstance(header.get("optionen"), dict) else {}
        with self._lock:
            e = self.eintrag
            if weg == "b":
                if e is None or e.weg != "b":
                    return False, ("Weg B ist nicht eingestellt. Kevin hat Weg A gewählt; Weg B braucht LAN Only Mode "
                                   "und Developer Mode am Drucker und Weg B in den Drucker-Einstellungen.")
                if bestaetigt and len(platten) != 1:
                    return False, "Weg B startet genau eine Platte; bitte eine Platte wählen."
            aid = str(header.get("auftrag") or "")
            a = self._auftrag if self._auftrag is not None and aid and self._auftrag.id == aid else None
            if aid and a is None:
                return False, f"Auftrag {aid} gibt es nicht mehr"
            if a is not None and a.zustand in ("verworfen",):
                return False, f"Auftrag {aid} wurde verworfen"
            if a is None:
                a = Auftrag(id=f"j-{next(self._auftraege)}", platten=platten, weg=weg, von="kevin")
            neu_slicen = a.platten != platten or a.weg != weg or a.datei is None or a.zustand == "fehler"
            a.platten, a.weg, a.optionen = platten, weg, dict(optionen)
            if neu_slicen:
                a.datei = None
                a.ergebnis = None
            self._auftrag = a
            if not bestaetigt:
                self._abbruch.set()  # laufendes Vorbereiten abbrechen, das neue gilt
        self._arbeit.put((a, bestaetigt, header.get("id"), antworten))
        return True, ("Wird vorbereitet" if not bestaetigt else
                      "Wird in Bambu Studio geöffnet" if weg == "a" else "Wird an den Drucker geschickt")

    def verwerfen(self, aid: str | None) -> tuple[bool, str]:
        with self._lock:
            a = self._auftrag
            if a is None or (aid and a.id != aid):
                return False, "Kein solcher Auftrag"
            if a.zustand in ("gestartet", "laedt_hoch", "startet"):
                return False, "Der Auftrag läuft schon am Drucker"
            a.zustand = "verworfen"
            a.meldung = "Von Kevin verworfen."
            self._abbruch.set()
        self._melden()
        return True, "Auftrag verworfen"

    def steuern(self, aktion: str) -> tuple[bool, str]:
        """``PRINT_CONTROL``: aktualisieren (lesen) oder pause/fortsetzen/abbrechen (nur Weg B, Sperre)."""
        with self._lock:
            v = self._mqtt
        if aktion == "aktualisieren":
            if v is None:
                return False, "Keine Verbindung zum Drucker."
            grund = v.lesen_anfordern(pushall=True)
            return (grund is None), (grund or "Bericht angefordert")
        befehl = {"pause": befehle.pause, "fortsetzen": befehle.fortsetzen, "abbrechen": befehle.abbrechen}.get(aktion)
        if befehl is None:
            return False, f"Aktion {aktion!r} unbekannt"
        grund = sperre.pruefe_steuern(self.lage())
        if grund:
            return False, grund
        if v is None:
            return False, "Keine Verbindung zum Drucker."
        grund = v.steuern(befehl())
        self._melden()
        return (grund is None), (grund or {"pause": "Pause gesendet", "fortsetzen": "Fortsetzen gesendet",
                                           "abbrechen": "Abbruch gesendet"}[aktion])

    # -----------------------------------------------------------------------------------------------------------------

    def _setze(self, a: Auftrag, zustand: str, meldung: str | None = None, fortschritt: float | None = None) -> None:
        with self._lock:
            a.zustand = zustand
            a.meldung = meldung
            a.fortschritt = fortschritt
        self._melden()

    def _arbeiten(self) -> None:
        while True:
            eintrag = self._arbeit.get()
            if eintrag is None:
                return
            a, bestaetigt, rid, antworten = eintrag
            if not bestaetigt and not self._arbeit.empty():
                continue  # ein neueres Vorbereiten wartet schon
            self._abbruch.clear()
            t0 = time.monotonic()
            try:
                res = self._ausfuehren(a, bestaetigt)
                res["ms"] = int((time.monotonic() - t0) * 1000)
            except Abgebrochen:
                continue
            except (SlicenFehler, QuelleFehler, ProfilFehler, RuntimeError, OSError) as exc:
                self._setze(a, "fehler", str(exc))
                res = {"ok": False, "fehler": str(exc), "schritt": None, "hinweise": [],
                       "ms": int((time.monotonic() - t0) * 1000)}
            except Exception as exc:  # noqa: BLE001
                self._log(f"[drucker] Auftrag {a.id}: {type(exc).__name__}: {exc}")
                self._setze(a, "fehler", f"{type(exc).__name__}: {exc}")
                res = {"ok": False, "fehler": f"{type(exc).__name__}: {exc}", "schritt": None, "hinweise": [],
                       "ms": int((time.monotonic() - t0) * 1000)}
            datei = a.ziel or a.datei
            antwort = {"type": "PRINT_JOB_RES", "reply_to": rid, "ok": bool(res.get("ok")), "auftrag": a.id,
                       "weg": a.weg, "schritt": res.get("schritt"), "datei": str(datei) if datei else None,
                       "platten": list(a.platten), "fehler": res.get("fehler"), "hinweise": res.get("hinweise") or [],
                       "ms": res.get("ms", 0)}
            if a.ergebnis is not None:
                antwort["ergebnis"] = a.ergebnis.als_dict()
            try:
                antworten(antwort)
            except Exception:  # noqa: BLE001
                pass

    def _vorbereiten(self, a: Auftrag) -> SliceErgebnis:
        if a.datei is not None and a.ergebnis is not None and a.datei.exists():
            return a.ergebnis
        if not vorhanden(self.app):  # vor dem Export: ohne Bambu Studio kein fertiges Slicen
            raise SlicenFehler(f"Bambu Studio fehlt ({self.app}); ohne Bambu Studio kann Kev CAD nicht fertig "
                               "slicen. „Platten als 3MF …“ in der Druckvorschau geht trotzdem.")
        self._setze(a, "slict", "Platten werden bereitgestellt …")
        quelle = self.cache / "quelle"
        shutil.rmtree(quelle, ignore_errors=True)  # Eingänge früherer Aufträge (Platte ist knapp)
        ordner = quelle / a.id
        ordner.mkdir(parents=True, exist_ok=True)
        try:
            q = self._quelle_fn(list(a.platten), ordner)
            einst: list[Path] = []
            fil: list[Path] = []
            if not q.mit_einstellungen:
                prof = self._profile_fn()
                einst, fil = prof.schreiben(ordner / "profile", q.prozess or prof.prozess_fuer(None),
                                            q.filamente or [prof.filament_fuer("pla")], platte=q.platte)
            self._setze(a, "slict", "Bambu Studio slict die Platten …")
            erg = slicen(q.eingaben, q.name, einstellungen=einst, filamente=fil, anordnen=q.anordnen,
                         ausrichten=q.ausrichten, app=self.app, cache=self.cache, abbruch=self._abbruch,
                         log=self._log)
        finally:
            shutil.rmtree(ordner, ignore_errors=True)  # das Ergebnis liegt im Zwischenspeicher
        erg.hinweise = list(q.hinweise) + list(erg.hinweise)
        with self._lock:
            a.ergebnis = erg
            a.datei = erg.datei
            a.run = q.run
            a.quelle_platten = list(q.platten)
            a.ziel = None
            a.ausgabe = q.ausgabe
            a.name = q.name
        return erg

    def _ausfuehren(self, a: Auftrag, bestaetigt: bool) -> dict[str, Any]:
        if a.zustand == "verworfen":
            return {"ok": False, "fehler": "Auftrag verworfen", "schritt": None}
        if a.weg == "b" and bestaetigt:
            grund = sperre.pruefe_steuern(self.lage(), start=True, bestaetigt=True)
            if grund:  # vor dem Slicen und vor jedem Byte an den Drucker
                self._setze(a, "fehler", grund)
                return {"ok": False, "fehler": grund, "schritt": None}
        erg = self._vorbereiten(a)
        zeit = sum(p.zeit_s for p in erg.platten)
        text = (f"{len(erg.platten)} Platte(n) gesliced ({_dauer(zeit)}, "
                f"{sum(p.g for p in erg.platten):.0f} g){' aus dem Zwischenspeicher' if erg.aus_zwischenspeicher else ''}.")
        if not bestaetigt:
            self._setze(a, "bereit", text)
            return {"ok": True, "schritt": "vorbereitet", "hinweise": erg.hinweise}
        if a.weg == "a":
            return self._weg_a(a, erg)
        return self._weg_b(a, erg)

    def _weg_a(self, a: Auftrag, erg: SliceErgebnis) -> dict[str, Any]:
        ziel = erg.datei
        if a.ausgabe is not None:
            a.ausgabe.mkdir(parents=True, exist_ok=True)
            ziel = a.ausgabe / f"{a.name}.gcode.3mf"
            shutil.copy2(erg.datei, ziel)
        with self._lock:
            a.ziel = ziel
        self._setze(a, "oeffnet", "Bambu Studio wird geöffnet …")
        self._oeffnen(ziel)
        self._setze(a, "geoeffnet", "In Bambu Studio geöffnet: dort „Platte drucken“ (bzw. „Alle drucken“) und "
                                    "„Senden“ klicken.")
        return {"ok": True, "schritt": "geoeffnet", "hinweise": erg.hinweise}

    def _weg_b(self, a: Auftrag, erg: SliceErgebnis) -> dict[str, Any]:
        """Gesperrt und nicht ausgebaut: nur gegen Attrappen getestet."""
        from kevcad_kernel.drucker import ftps

        if len(erg.platten) != 1:
            raise RuntimeError("Weg B startet genau eine Platte")
        nr = erg.platten[0].nr
        with self._lock:
            e = self.eintrag
            v = self._mqtt
        grund = sperre.pruefe_steuern(self.lage(), start=True, bestaetigt=True)
        if grund or e is None or v is None:
            grund = grund or "Keine Verbindung zum Drucker."
            self._setze(a, "fehler", grund)
            return {"ok": False, "fehler": grund, "schritt": None}
        zugang = self._zugang_lesen(e.id)
        ziel_name = f"kevcad-{a.id}.gcode.3mf"
        self._setze(a, "laedt_hoch", "Datei wird zum Drucker geladen …", 0.0)
        try:
            ftps.hochladen(e.ip, zugang, erg.datei, ziel_name, port=e.port_ftps or ftps.PORT, ca_datei=self._ca_fuer(e),
                           fortschritt=lambda f: self._setze(a, "laedt_hoch", "Datei wird zum Drucker geladen …", f))
        except ftps.UploadFehler as exc:
            raise RuntimeError(str(exc)) from None
        finally:
            del zugang
        self._setze(a, "startet", "Druck wird gestartet …")
        opt = a.optionen
        befehl = befehle.project_file(ziel_name, nr, platten_md5(erg.datei, nr), a.name,
                                      bett_nivellieren=bool(opt.get("bett_nivellieren", True)),
                                      flussrate=bool(opt.get("flussrate", True)),
                                      zeitraffer=bool(opt.get("zeitraffer", False)))
        grund = v.steuern(befehl, start=True, bestaetigt=True)
        if grund:
            self._setze(a, "fehler", grund)
            return {"ok": False, "fehler": grund, "schritt": None}
        self._setze(a, "gestartet", "Druck gestartet.")
        return {"ok": True, "schritt": "gestartet", "hinweise": erg.hinweise}

    # =================================================================================================================

    def stoppen(self) -> None:
        with self._lock:
            self._zu = True
            v, self._mqtt = self._mqtt, None
            t, self._melde_timer = self._melde_timer, None
        self._abbruch.set()
        self._arbeit.put(None)
        if t is not None:
            t.cancel()
        if v is not None:
            v.stoppen()
        if self._lauscher is not None:
            self._lauscher.stoppen()


def _dauer(s: int) -> str:
    h, m = divmod(int(s) // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"
