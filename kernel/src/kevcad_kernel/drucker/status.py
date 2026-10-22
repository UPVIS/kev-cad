"""Zustand des Druckers aus den MQTT-Berichten (``device/<SERIAL>/report``) und Aufbereitung für ``PRINTER_STATUS``.

Der P1P schickt nur geänderte Werte (Deltas); ``Bericht`` führt sie zu einem vollständigen Stand zusammen. Woraus der
Kernel den Modus liest (PLAN-PHASE8-DRUCK.md, Recherche):

- ``print.fun`` (Hex-Text): Bit ``0x20000000`` gesetzt = MQTT-Signatur nötig = Developer Mode aus (ha-bambulab,
  ``Print_Fun_Values.MQTT_SIGNATURE_REQUIRED``). Fehlt das Feld, gilt der Modus als unbekannt (gesperrt).
- HMS ``0500-0500-0001-0007``: Der Drucker hat einen unsignierten Befehl abgelehnt; danach geht nichts mehr hinaus.
- ``info.module[name=ota].sw_ver``: Firmware (Antwort auf ``get_version``).

Seriennummer und Zugangscode kommen hier nie vor: Der Bericht enthält sie nicht, und nichts von hier geht an Logs.
"""

from __future__ import annotations

import copy
import time
from typing import Any

FUN_SIGNATUR_NOETIG = 0x20000000
HMS_SIGNATUR_ABGELEHNT = "0500-0500-0001-0007"

# gcode_state → zustand (DRUCKVORSCHAU.md, PRINTER_STATUS.druck.zustand)
ZUSTAENDE: dict[str, str] = {
    "IDLE": "bereit",
    "INIT": "vorbereiten",
    "SLICING": "vorbereiten",
    "PREPARE": "vorbereiten",
    "RUNNING": "druckt",
    "PAUSE": "pausiert",
    "FINISH": "fertig",
    "FAILED": "fehlgeschlagen",
}

# stg_cur → Text (Auswahl nach ha-bambulab CURRENT_STAGE_IDS, MIT)
STUFEN: dict[int, str] = {
    0: "druckt",
    1: "Bett nivellieren",
    2: "Heizbett aufheizen",
    3: "Vibrationskompensation",
    4: "Filament wechseln",
    5: "Pause (M400)",
    6: "Pause: Filament zu Ende",
    7: "Düse aufheizen",
    8: "Extrusion kalibrieren",
    9: "Bett abtasten",
    10: "erste Schicht prüfen",
    11: "Druckplatte erkennen",
    13: "Druckkopf referenzieren",
    14: "Düsenspitze reinigen",
    15: "Extrudertemperatur prüfen",
    16: "Pause durch Benutzer",
    17: "Pause: Frontabdeckung",
    19: "Fluss kalibrieren",
    20: "Pause: Düsentemperatur gestört",
    21: "Pause: Betttemperatur gestört",
    22: "Filament entladen",
    23: "Pause: Schrittverlust",
    24: "Filament laden",
    25: "Motorgeräusch kalibrieren",
    27: "Pause: Lüfter am Hitzeblock zu langsam",
    30: "Pause durch G-Code",
    32: "Pause: Düse mit Filament bedeckt",
    34: "Pause: Fehler in der ersten Schicht",
    35: "Pause: Düse verstopft",
}
GESCHWINDIGKEIT: dict[int, str] = {1: "leise", 2: "standard", 3: "sport", 4: "ludicrous"}
# HMS-Schwere (oberes Wort des Codes): 1 tödlich, 2 ernst, 3 normal, 4 Hinweis
HMS_SCHWERE: dict[int, str] = {1: "fehler", 2: "fehler", 3: "warnung", 4: "hinweis"}
HMS_TEXTE: dict[str, str] = {
    HMS_SIGNATUR_ABGELEHNT: "Der Drucker hat einen Befehl ohne Freigabe abgelehnt (MQTT command verification failed). "
                            "Am Drucker quittieren; Kev CAD sendet bis dahin nichts.",
}


def hms_code(attr: int, code: int) -> str:
    """``0500-0500-0001-0007`` aus ``attr`` und ``code`` eines HMS-Eintrags."""
    attr, code = int(attr) & 0xFFFFFFFF, int(code) & 0xFFFFFFFF
    return f"{attr >> 16:04X}-{attr & 0xFFFF:04X}-{code >> 16:04X}-{code & 0xFFFF:04X}"


def fehler_code(wert: int) -> str:
    wert = int(wert) & 0xFFFFFFFF
    return f"{wert >> 16:04X}-{wert & 0xFFFF:04X}"


def wiki_link(code: str) -> str:
    return "https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/" + code.replace("-", "_")


def _zahl(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _ganz(v: Any) -> int | None:
    z = _zahl(v)
    return None if z is None else int(z)


def _mischen(ziel: dict[str, Any], neu: dict[str, Any]) -> None:
    """Delta in den Stand einmischen: Objekte rekursiv, alles andere (auch Listen) ersetzt."""
    for k, v in neu.items():
        if isinstance(v, dict) and isinstance(ziel.get(k), dict):
            _mischen(ziel[k], v)
        else:
            ziel[k] = copy.deepcopy(v)


class Bericht:
    """Vollständiger Stand aus den Deltas einer Verbindung. ``neue_verbindung()`` vergisst alles Gelernte, was den Modus
    betrifft (``fun`` muss in jeder Verbindung neu kommen)."""

    def __init__(self) -> None:
        self.druck: dict[str, Any] = {}
        self.firmware: str | None = None
        self.zuletzt: float | None = None
        self.fun_gesehen = False
        self.anzahl = 0

    def neue_verbindung(self) -> None:
        self.druck = {}
        self.firmware = None
        self.zuletzt = None
        self.fun_gesehen = False
        self.anzahl = 0

    def aufnehmen(self, nachricht: dict[str, Any], jetzt: float | None = None) -> bool:
        """Eine Nachricht vom Thema ``report`` aufnehmen; True, wenn sich der Stand geändert haben kann."""
        if not isinstance(nachricht, dict):
            return False
        geaendert = False
        p = nachricht.get("print")
        if isinstance(p, dict):
            if "fun" in p:
                self.fun_gesehen = True
            _mischen(self.druck, p)
            geaendert = True
        info = nachricht.get("info")
        if isinstance(info, dict) and info.get("command") == "get_version":
            for m in info.get("module") or []:
                if isinstance(m, dict) and m.get("name") == "ota" and m.get("sw_ver"):
                    self.firmware = str(m["sw_ver"])
                    geaendert = True
        if geaendert:
            self.zuletzt = time.time() if jetzt is None else jetzt
            self.anzahl += 1
        return geaendert

    # ------------------------------------------------------------------------------------------------------------
    # Abgeleitete Werte

    @property
    def fun(self) -> int | None:
        roh = self.druck.get("fun") if self.fun_gesehen else None
        if roh is None or roh == "":
            return None
        try:
            return int(str(roh), 16)
        except ValueError:
            return None

    @property
    def entwicklermodus(self) -> bool | None:
        """True: Developer Mode an (keine Signatur nötig); False: aus; None: unbekannt (``fun`` nicht gesehen)."""
        f = self.fun
        if f is None:
            return None
        return (f & FUN_SIGNATUR_NOETIG) == 0

    def hms(self) -> list[dict[str, Any]]:
        out = []
        for e in self.druck.get("hms") or []:
            if not isinstance(e, dict):
                continue
            try:
                code = hms_code(int(e.get("attr", 0)), int(e.get("code", 0)))
            except (TypeError, ValueError):
                continue
            stufe = (int(e.get("code", 0)) >> 16) & 0xFFFF
            text = HMS_TEXTE.get(code) or f"Meldung {code} des Druckers, Erklärung: {wiki_link(code)}"
            out.append({"code": code, "text": text, "schwere": HMS_SCHWERE.get(stufe, "warnung"), "art": "hms"})
        return out

    @property
    def signatur_abgelehnt(self) -> bool:
        return any(e["code"] == HMS_SIGNATUR_ABGELEHNT for e in self.hms())

    def fehler(self) -> list[dict[str, Any]]:
        out = self.hms()
        pe = _ganz(self.druck.get("print_error"))
        if pe:
            code = fehler_code(pe)
            out.append({"code": code, "text": f"Druckfehler {code}, Erklärung: {wiki_link(code)}", "schwere": "fehler",
                        "art": "print_error"})
        return out

    def druck_status(self) -> dict[str, Any] | None:
        d = self.druck
        if not d:
            return None
        state = str(d.get("gcode_state") or "").upper() or None
        prozent = _zahl(d.get("mc_percent"))
        rest_min = _zahl(d.get("mc_remaining_time"))
        stufe_nr = _ganz(d.get("stg_cur"))
        stufe = None
        if stufe_nr is not None and stufe_nr >= 0:
            stufe = STUFEN.get(stufe_nr, f"Stufe {stufe_nr}")
        spd = _ganz(d.get("spd_lvl"))
        return {
            "zustand": ZUSTAENDE.get(state or "", "unbekannt"),
            "gcode_state": state,
            "fortschritt": None if prozent is None else max(0.0, min(1.0, prozent / 100.0)),
            "schicht": _ganz(d.get("layer_num")),
            "schichten": _ganz(d.get("total_layer_num")),
            "restzeit_s": None if rest_min is None else int(rest_min * 60),
            "aufgabe": d.get("subtask_name") or None,
            "datei": d.get("gcode_file") or None,
            "stufe": stufe,
            "geschwindigkeit": GESCHWINDIGKEIT.get(spd) if spd is not None else None,
        }

    def temperaturen(self) -> dict[str, Any] | None:
        d = self.druck
        werte = {"duese": _zahl(d.get("nozzle_temper")), "duese_ziel": _zahl(d.get("nozzle_target_temper")),
                 "bett": _zahl(d.get("bed_temper")), "bett_ziel": _zahl(d.get("bed_target_temper"))}
        if all(v is None for v in werte.values()):
            return None
        return {k: (None if v is None else round(v, 1)) for k, v in werte.items()}

    @property
    def signal(self) -> str | None:
        s = self.druck.get("wifi_signal")
        return str(s) if s else None
