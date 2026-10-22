"""Bestandsdatei eines Projekts (BESTAND.md): laden, prüfen, atomar schreiben, Kennungen vergeben, Buchungen.

- ``<projekt>/bestand.json``: das Material, das Kevin für genau dieses Projekt hat (``KEVCAD_BESTAND_FILE`` übersteuert
  den Pfad, für Tests).
- ``<projekt>/.kevcad/bestand-buchungen.jsonl``: eine Zeile je Buchung (bei ``KEVCAD_BESTAND_FILE`` daneben). Jede
  Buchung besteht aus Änderungen (``aenderungen``), die sich einzeln umkehren lassen.

Änderungen (``aenderungen[i]``, Feld ``op``):

| op | Felder | Wirkung |
|---|---|---|
| ``posten`` | ``posten``, ``vorher``, ``nachher`` (Objekt oder null) | ganzen Posten setzen (Eintragen in App und MCP) |
| ``einstellungen`` | ``vorher``, ``nachher`` | Einstellungen setzen |
| ``ganze`` | ``posten``, ``delta``, ``laenge`` bzw. ``b``/``h`` | ganze Stangen bzw. Platten zu- oder abbuchen |
| ``rest_weg`` | ``posten``, ``rest`` (ganzes Objekt) | Rest verbraucht |
| ``rest_neu`` | ``posten``, ``rest`` | Rest entstanden (neue Kennung) |
| ``stueck`` | ``posten``, ``laenge`` (oder null), ``delta`` | Stückgut zu- oder abbuchen |
| ``spule`` | ``kennung``, ``vorher``, ``nachher`` (Spule oder null) | Filamentspule anlegen, ändern, entfernen |
| ``spule_gramm`` | ``kennung``, ``material``, ``delta`` (g) | Filament einer Spule ab- oder zubuchen |
| ``filament_fuehren`` | ``vorher``, ``nachher`` (bool) | Filament im Projekt führen (Liste ``filament`` anlegen) |

Filament (Strang „Bestand Stufe 2“, 22.10.2026, additiv): Liste ``filament`` neben ``posten``, je Spule
``{"kennung": "S-0001", "material": "petg", "gramm": 640, "gramm_voll": 1000, "name", "hersteller", "farbe", "ort",
"seit"}``. Fehlt die Liste, führt das Projekt kein Filament (die Einkaufsliste nennt dann keine Spulen).

Importiert nichts Schweres; läuft im Elternprozess der Laufzeit und im Ersatz-Kernel.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kevcad_kernel.catalog import KLEINTEILE, STANGENWARE, number

BESTAND_DATEI = "bestand.json"
BUCHUNGEN_DATEI = "bestand-buchungen.jsonl"
VERSION = 1
STANDARD_MINDESTREST_MM = 100.0
STANDARD_SAEGEBLATT_MM = 3.0
MELDUNG_BUCHUNGEN = 50  # so viele Buchungen gehen mit BESTAND an die App
ARTEN = ("eintrag", "gebaut", "korrektur", "rueckgaengig", "gedruckt")  # gedruckt: Filament abgebucht (Stufe 2)
VON = ("kevin", "agent")

POSTEN_FELDER = ("ganze", "reste", "stueck", "mindestrest_mm")
# ``filament`` (additiv, Strang „Druckexport 2“): id eines Filaments aus Kevins Filamentliste (druck/filamente.py)
SPULE_FELDER = ("kennung", "material", "gramm", "gramm_voll", "name", "hersteller", "farbe", "ort", "seit", "filament")
SPULE_STANDARD_G = 1000.0  # Kaufspule, wenn der Katalog keine spule_g nennt
_KENNUNG_RE = re.compile(r"^([RP])-(\d{1,9})$")
_SPULE_RE = re.compile(r"^S-(\d{1,9})$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

Katalog = Callable[[str], "dict[str, Any] | None"]


class BestandError(ValueError):
    """Bestand ungültig, nicht schreibbar oder Buchung nicht möglich (Meldung für Kevin und den Agenten)."""


# ---------------------------------------------------------------------------------------------------------------------
# Pfade und Zahlen


def pfade(projekt: str | Path | None) -> tuple[Path | None, Path | None]:
    """(bestand.json, bestand-buchungen.jsonl) des Projekts; ``KEVCAD_BESTAND_FILE`` übersteuert (Tests)."""
    env = os.environ.get("KEVCAD_BESTAND_FILE")
    if env:
        p = Path(env).expanduser()
        return p, p.with_name(BUCHUNGEN_DATEI)
    if projekt is None:
        return None, None
    base = Path(projekt)
    return base / BESTAND_DATEI, base / ".kevcad" / BUCHUNGEN_DATEI


def zahl(x: Any) -> int | float:
    """Für die Datei: ganze Zahlen ohne Nachkommastellen, sonst auf 0,1 mm."""
    v = float(x)
    r = round(v, 1)
    return int(r) if r == int(r) else r


def mm(x: Any) -> str:
    """Länge für Texte: 430 → "430", 12.5 → "12,5"."""
    v = zahl(x)
    return str(v).replace(".", ",")


def heute() -> str:
    return time.strftime("%Y-%m-%d")


def jetzt_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def leerer_bestand() -> dict[str, Any]:
    return {"version": VERSION,
            "einstellungen": {"mindestrest_mm": zahl(STANDARD_MINDESTREST_MM),
                              "saegeblatt_mm": zahl(STANDARD_SAEGEBLATT_MM)},
            "posten": {}}


def einstellungen(bestand: dict[str, Any] | None) -> dict[str, float]:
    """Einstellungen mit Standardwerten (mindestrest_mm 100, saegeblatt_mm 3)."""
    e = (bestand or {}).get("einstellungen") or {}
    m = number(e.get("mindestrest_mm"))
    s = number(e.get("saegeblatt_mm"))
    return {"mindestrest_mm": STANDARD_MINDESTREST_MM if m is None else m,
            "saegeblatt_mm": STANDARD_SAEGEBLATT_MM if s is None else s}


def mindestrest(bestand: dict[str, Any] | None, posten: dict[str, Any] | None) -> float:
    """Mindestrest des Postens, sonst aus den Einstellungen."""
    m = number((posten or {}).get("mindestrest_mm"))
    return einstellungen(bestand)["mindestrest_mm"] if m is None else m


def ist_platte(obj: dict[str, Any] | None) -> bool:
    return bool(obj) and ("b" in obj or "h" in obj)


# ---------------------------------------------------------------------------------------------------------------------
# Prüfen


def _pos(value: Any, what: str, errors: list[str], *, ganz: bool = False, null_ok: bool = False) -> float | None:
    v = number(value)
    if v is None:
        errors.append(f"{what} fehlt oder ist keine Zahl")
        return None
    if ganz and v != int(v):
        errors.append(f"{what} muss eine ganze Zahl sein (nicht {value!r})")
    if v < 0 or (v == 0 and not null_ok):
        errors.append(f"{what} muss {'≥ 0' if null_ok else 'größer als 0'} sein (nicht {value!r})")
    return v


def pruefe_posten(pid: str, posten: Any, art: str | None = None) -> list[str]:
    """Fehler eines Postens (leer = gültig). ``art``: Art des Katalogeintrags (None = unbekannt, nicht prüfen)."""
    who = f"Posten {pid!r}"
    if not isinstance(posten, dict):
        return [f"{who}: muss ein Objekt sein, z. B. {{\"ganze\": {{\"anzahl\": 2, \"laenge\": 1000}}}}"]
    errors: list[str] = []
    extra = [k for k in posten if k not in POSTEN_FELDER]
    for k in extra:
        close = difflib.get_close_matches(str(k), POSTEN_FELDER, n=1, cutoff=0.6)
        errors.append(f"{who}: Feld {k!r} unbekannt (erlaubt: {', '.join(POSTEN_FELDER)})"
                      + (f"; meinten Sie {close[0]!r}?" if close else ""))
    if posten.get("mindestrest_mm") is not None:
        _pos(posten["mindestrest_mm"], f"{who}: mindestrest_mm", errors, null_ok=True)
    has_bar = posten.get("ganze") is not None or posten.get("reste") is not None
    if has_bar and posten.get("stueck") is not None:
        errors.append(f"{who}: entweder ganze/reste (Stangen, Platten) oder stueck (Stückgut), nicht beides")
    platte: bool | None = None if art is None else art == "platte"
    if art is not None and art not in STANGENWARE and art != "platte" and has_bar:
        errors.append(f"{who}: {art} ist Stückgut; Menge als stueck angeben, z. B. [{{\"anzahl\": 10}}]")
    if art is not None and (art in STANGENWARE or art == "platte") and posten.get("stueck") is not None:
        errors.append(f"{who}: {art} wird in ganzen {'Platten' if art == 'platte' else 'Stangen'} und Resten "
                      "geführt (ganze, reste), nicht als stueck")
    ganze = posten.get("ganze")
    if ganze is not None:
        if not isinstance(ganze, dict):
            errors.append(f"{who}: ganze muss ein Objekt sein, z. B. {{\"anzahl\": 2, \"laenge\": 1000}}")
        else:
            _pos(ganze.get("anzahl"), f"{who}: ganze.anzahl", errors, ganz=True, null_ok=True)
            bad = [k for k in ganze if k not in ("anzahl", "laenge", "b", "h")]
            if bad:
                errors.append(f"{who}: ganze kennt nur anzahl, laenge (Stangen) bzw. b, h (Platten), nicht "
                              f"{', '.join(map(str, bad))}")
            if "laenge" in ganze and ("b" in ganze or "h" in ganze):
                errors.append(f"{who}: ganze hat entweder laenge (Stange) oder b und h (Platte)")
            if ganze.get("laenge") is not None:
                _pos(ganze["laenge"], f"{who}: ganze.laenge", errors)
                if platte:
                    errors.append(f"{who}: Platten haben b und h statt laenge")
            for k in ("b", "h"):
                if ganze.get(k) is not None:
                    _pos(ganze[k], f"{who}: ganze.{k}", errors)
            if ("b" in ganze) != ("h" in ganze):
                errors.append(f"{who}: ganze braucht b und h zusammen")
            if platte is False and ("b" in ganze or "h" in ganze):
                errors.append(f"{who}: Stangenware hat laenge statt b und h")
    reste = posten.get("reste")
    if reste is not None:
        if not isinstance(reste, list):
            errors.append(f"{who}: reste muss eine Liste sein, z. B. [{{\"kennung\": \"R-0001\", \"laenge\": 430}}]")
        else:
            for i, rest in enumerate(reste):
                errors += _pruefe_rest(f"{who}: reste[{i}]", rest, platte)
    stueck = posten.get("stueck")
    if stueck is not None:
        if not isinstance(stueck, list):
            errors.append(f"{who}: stueck muss eine Liste sein, z. B. [{{\"laenge\": 16, \"anzahl\": 40}}]")
        else:
            seen: set[Any] = set()
            for i, row in enumerate(stueck):
                w = f"{who}: stueck[{i}]"
                if not isinstance(row, dict):
                    errors.append(f"{w}: muss ein Objekt {{\"anzahl\": …}} sein")
                    continue
                bad = [k for k in row if k not in ("anzahl", "laenge")]
                if bad:
                    errors.append(f"{w}: kennt nur anzahl und laenge, nicht {', '.join(map(str, bad))}")
                _pos(row.get("anzahl"), f"{w}.anzahl", errors, ganz=True, null_ok=True)
                key = None
                if row.get("laenge") is not None:
                    key = _pos(row["laenge"], f"{w}.laenge", errors)
                    if art is not None and art != "schraube":
                        errors.append(f"{w}: laenge gibt es nur bei Schrauben und Gewindestiften")
                if key in seen:
                    errors.append(f"{w}: {'Länge ' + mm(key) + ' mm' if key is not None else 'ohne Länge'} steht "
                                  "doppelt; Anzahlen zusammenfassen")
                seen.add(key)
    return errors


def _pruefe_rest(who: str, rest: Any, platte: bool | None) -> list[str]:
    if not isinstance(rest, dict):
        return [f"{who}: muss ein Objekt sein, z. B. {{\"kennung\": \"R-0001\", \"laenge\": 430}}"]
    errors: list[str] = []
    bad = [k for k in rest if k not in ("kennung", "laenge", "b", "h", "ort", "seit")]
    if bad:
        errors.append(f"{who}: kennt nur kennung, laenge bzw. b und h, ort, seit (nicht {', '.join(map(str, bad))})")
    flach = "b" in rest or "h" in rest
    if flach:
        _pos(rest.get("b"), f"{who}.b", errors)
        _pos(rest.get("h"), f"{who}.h", errors)
        if "laenge" in rest:
            errors.append(f"{who}: entweder laenge (Stange) oder b und h (Platte)")
        if platte is False:
            errors.append(f"{who}: Stangenware hat laenge statt b und h")
    else:
        _pos(rest.get("laenge"), f"{who}.laenge", errors)
        if platte:
            errors.append(f"{who}: Plattenreste haben b und h statt laenge")
    kennung = rest.get("kennung")
    m = _KENNUNG_RE.match(str(kennung)) if isinstance(kennung, str) else None
    if not m:
        errors.append(f"{who}: kennung fehlt oder hat nicht die Form R-0001 (Stangen) bzw. P-0001 (Platten)")
    elif (m.group(1) == "P") != flach:
        errors.append(f"{who}: kennung {kennung} passt nicht: {'P-' if flach else 'R-'} für "
                      f"{'Platten' if flach else 'Stangen'}")
    if rest.get("ort") is not None and not isinstance(rest.get("ort"), str):
        errors.append(f"{who}: ort muss Text sein")
    if rest.get("seit") is not None and not (isinstance(rest["seit"], str) and _DATUM_RE.match(rest["seit"])):
        errors.append(f"{who}: seit als Datum \"JJJJ-MM-TT\" angeben")
    return errors


def pruefe(data: Any, katalog: Katalog | None = None) -> list[str]:
    """Fehler der ganzen Bestandsdatei (leer = gültig). Mit ``katalog`` werden die Arten gegen den Katalog geprüft."""
    if not isinstance(data, dict):
        return ["bestand.json muss ein Objekt {\"version\": 1, \"einstellungen\": {…}, \"posten\": {…}} sein"]
    errors: list[str] = []
    if data.get("version", VERSION) != VERSION:
        errors.append(f"version {data.get('version')!r} unbekannt (erwartet {VERSION})")
    bad = [k for k in data if k not in ("version", "einstellungen", "posten", "filament")]
    if bad:
        errors.append(f"bestand.json kennt nur version, einstellungen, posten und filament (nicht "
                      f"{', '.join(map(str, bad))})")
    if data.get("filament") is not None:
        errors += pruefe_filament(data["filament"])
    e = data.get("einstellungen")
    if e is not None:
        if not isinstance(e, dict):
            errors.append("einstellungen muss ein Objekt sein")
        else:
            errors += pruefe_einstellungen(e)
    posten = data.get("posten")
    if posten is not None and not isinstance(posten, dict):
        errors.append("posten muss ein Objekt sein: Katalog-id → Posten")
        return errors
    kennungen: dict[str, str] = {}
    for pid, p in (posten or {}).items():
        if not isinstance(pid, str) or not _ID_RE.match(pid):
            errors.append(f"Posten {pid!r}: Schlüssel muss eine Katalog-id sein (Kleinbuchstaben, Bindestriche)")
            continue
        item = katalog(pid) if katalog is not None else None
        errors += pruefe_posten(pid, p, item.get("art") if item else None)
        for rest in (p.get("reste") if isinstance(p, dict) and isinstance(p.get("reste"), list) else []):
            k = rest.get("kennung") if isinstance(rest, dict) else None
            if isinstance(k, str):
                if k in kennungen:
                    errors.append(f"Kennung {k} steht doppelt (in {kennungen[k]!r} und {pid!r}); Kennungen sind im "
                                  "ganzen Bestand eindeutig")
                kennungen[k] = pid
    return errors


def pruefe_spule(who: str, spule: Any) -> list[str]:
    """Fehler einer Filamentspule (leer = gültig)."""
    if not isinstance(spule, dict):
        return [f"{who}: muss ein Objekt sein, z. B. {{\"kennung\": \"S-0001\", \"material\": \"petg\", \"gramm\": 640}}"]
    errors: list[str] = []
    bad = [k for k in spule if k not in SPULE_FELDER]
    if bad:
        errors.append(f"{who}: kennt nur {', '.join(SPULE_FELDER)} (nicht {', '.join(map(str, bad))})")
    k = spule.get("kennung")
    if not (isinstance(k, str) and _SPULE_RE.match(k)):
        errors.append(f"{who}: kennung fehlt oder hat nicht die Form S-0001")
    mat = spule.get("material")
    if not (isinstance(mat, str) and _ID_RE.match(mat)):
        errors.append(f"{who}: material fehlt (Material-id aus dem Katalog, z. B. \"petg\")")
    g = _pos(spule.get("gramm"), f"{who}.gramm", errors, null_ok=True)
    voll = None
    if spule.get("gramm_voll") is not None:
        voll = _pos(spule["gramm_voll"], f"{who}.gramm_voll", errors)
    if g is not None and voll is not None and voll > 0 and g > 1.5 * voll:
        errors.append(f"{who}: gramm {mm(g)} g ist mehr als anderthalb volle Spulen ({mm(voll)} g); Tippfehler?")
    for key in ("name", "hersteller", "farbe", "ort"):
        if spule.get(key) is not None and not isinstance(spule.get(key), str):
            errors.append(f"{who}: {key} muss Text sein")
    fil = spule.get("filament")
    if fil is not None and not (isinstance(fil, str) and re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", fil)):
        errors.append(f"{who}: filament ist die id eines Filaments aus Kevins Liste (z. B. "
                      "\"polymaker-polylite-petg-gelb\")")
    if spule.get("seit") is not None and not (isinstance(spule["seit"], str) and _DATUM_RE.match(spule["seit"])):
        errors.append(f"{who}: seit als Datum \"JJJJ-MM-TT\" angeben")
    return errors


def pruefe_filament(liste: Any) -> list[str]:
    """Fehler der Liste ``filament`` (leer = gültig): Spulen mit eindeutiger Kennung."""
    if not isinstance(liste, list):
        return ["filament muss eine Liste von Spulen sein, z. B. [{\"kennung\": \"S-0001\", \"material\": \"petg\", "
                "\"gramm\": 640, \"gramm_voll\": 1000}]"]
    errors: list[str] = []
    seen: set[str] = set()
    for i, spule in enumerate(liste):
        errors += pruefe_spule(f"filament[{i}]", spule)
        k = spule.get("kennung") if isinstance(spule, dict) else None
        if isinstance(k, str):
            if k in seen:
                errors.append(f"Spule {k} steht doppelt; Kennungen sind im ganzen Bestand eindeutig")
            seen.add(k)
    return errors


def spulen(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Filamentspulen des Bestands (leer, wenn das Projekt kein Filament führt)."""
    liste = (data or {}).get("filament")
    return [s for s in liste if isinstance(s, dict)] if isinstance(liste, list) else []


def fuehrt_filament(data: dict[str, Any] | None) -> bool:
    """Führt das Projekt Filament (Liste ``filament`` vorhanden, auch leer)?"""
    return isinstance((data or {}).get("filament"), list)


def gramm_text(x: Any) -> str:
    """Gramm für Texte: 640 → "640 g", 548.25 → "548,3 g"."""
    return f"{mm(x)} g"


def spule_nr(k: Any) -> int:
    m = _SPULE_RE.match(k) if isinstance(k, str) else None
    return int(m.group(1)) if m else 0


def pruefe_einstellungen(e: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    bad = [k for k in e if k not in ("mindestrest_mm", "saegeblatt_mm")]
    if bad:
        errors.append(f"einstellungen kennt nur mindestrest_mm und saegeblatt_mm (nicht {', '.join(map(str, bad))})")
    if e.get("mindestrest_mm") is not None:
        _pos(e["mindestrest_mm"], "einstellungen.mindestrest_mm", errors, null_ok=True)
    if e.get("saegeblatt_mm") is not None:
        s = _pos(e["saegeblatt_mm"], "einstellungen.saegeblatt_mm", errors, null_ok=True)
        if s is not None and s > 20:
            errors.append(f"einstellungen.saegeblatt_mm {mm(s)} mm ist unplausibel (Schnittbreite, meist 1 bis 4 mm)")
    return errors


# ---------------------------------------------------------------------------------------------------------------------
# Kennungen


def _kennung_nr(k: Any, prefix: str) -> int:
    m = _KENNUNG_RE.match(str(k)) if isinstance(k, str) else None
    return int(m.group(2)) if m and m.group(1) == prefix else 0


def hoechste_kennungen(data: dict[str, Any] | None, buchungen: list[dict[str, Any]] = ()) -> dict[str, int]:
    """Höchste vergebene Nummer je Präfix (R, P, S für Spulen) aus Bestand und Buchungen (verbrauchte Reste und leere
    Spulen zählen mit, damit keine Kennung zweimal vorkommt)."""
    best = {"R": 0, "P": 0, "S": 0}

    def see(rest: Any) -> None:
        if isinstance(rest, dict):
            for p in ("R", "P"):
                best[p] = max(best[p], _kennung_nr(rest.get("kennung"), p))

    for p in ((data or {}).get("posten") or {}).values():
        for rest in (p or {}).get("reste") or []:
            see(rest)
    for sp in spulen(data):
        best["S"] = max(best["S"], spule_nr(sp.get("kennung")))
    for b in buchungen:
        for op in b.get("aenderungen") or []:
            see(op.get("rest"))
            if str(op.get("op", "")).startswith("spule"):
                best["S"] = max(best["S"], spule_nr(op.get("kennung")))
            for side in ("vorher", "nachher"):
                for rest in ((op.get(side) or {}).get("reste") or []) if isinstance(op.get(side), dict) else []:
                    see(rest)
    return best


class Kennungen:
    """Vergibt fortlaufende Kennungen (R-0001 für Stangen, P-0001 für Platten)."""

    def __init__(self, hoechste: dict[str, int]) -> None:
        self._n = dict(hoechste)

    def neu(self, platte: bool) -> str:
        p = "P" if platte else "R"
        self._n[p] = self._n.get(p, 0) + 1
        return f"{p}-{self._n[p]:04d}"

    def spule(self) -> str:
        """Nächste Spulenkennung: S-0001, S-0002 …"""
        self._n["S"] = self._n.get("S", 0) + 1
        return f"S-{self._n['S']:04d}"


# ---------------------------------------------------------------------------------------------------------------------
# Änderungen anwenden und umkehren


def _posten_von(data: dict[str, Any], pid: str, anlegen: bool = True) -> dict[str, Any] | None:
    posten = data.setdefault("posten", {})
    p = posten.get(pid)
    if p is None and anlegen:
        p = posten[pid] = {}
    return p


def _rest_text(rest: dict[str, Any]) -> str:
    if ist_platte(rest):
        return f"{rest.get('kennung')} ({mm(rest.get('b', 0))} × {mm(rest.get('h', 0))} mm)"
    return f"{rest.get('kennung')} ({mm(rest.get('laenge', 0))} mm)"


def anwenden(data: dict[str, Any], op: dict[str, Any]) -> None:
    """Eine Änderung auf ``data`` anwenden (in place). Konflikte → BestandError."""
    art = op.get("op")
    pid = op.get("posten")
    if art == "posten":
        posten = data.setdefault("posten", {})
        aktuell = posten.get(pid)
        if op.get("pruefen_vorher", True) and _norm(aktuell) != _norm(op.get("vorher")):
            raise BestandError(f"Posten {pid!r} wurde inzwischen geändert; erst die neueren Buchungen rückgängig machen")
        if op.get("nachher") is None:
            posten.pop(pid, None)
        else:
            posten[pid] = copy.deepcopy(op["nachher"])
    elif art == "einstellungen":
        data["einstellungen"] = copy.deepcopy(op.get("nachher") or {})
    elif art == "ganze":
        p = _posten_von(data, pid)
        assert p is not None
        ganze = p.get("ganze")
        delta = int(op.get("delta") or 0)
        if ganze is None:
            if delta < 0:
                raise BestandError(f"Posten {pid!r}: keine ganzen Stangen oder Platten mehr im Bestand")
            ganze = p["ganze"] = {"anzahl": 0}
            for k in ("laenge", "b", "h"):
                if op.get(k) is not None:
                    ganze[k] = op[k]
        neu = int(number(ganze.get("anzahl")) or 0) + delta
        if neu < 0:
            raise BestandError(f"Posten {pid!r}: nur noch {ganze.get('anzahl')} ganze im Bestand, {-delta} gebraucht")
        ganze["anzahl"] = neu
    elif art == "rest_weg":
        p = _posten_von(data, pid, anlegen=False)
        rest = op.get("rest") or {}
        reste = (p or {}).get("reste") or []
        keep = [r for r in reste if r.get("kennung") != rest.get("kennung")]
        if p is None or len(keep) == len(reste):
            raise BestandError(f"Rest {_rest_text(rest)} ist nicht mehr im Bestand von {pid!r}")
        p["reste"] = keep
    elif art == "rest_neu":
        p = _posten_von(data, pid)
        assert p is not None
        rest = copy.deepcopy(op.get("rest") or {})
        reste = p.setdefault("reste", [])
        if any(r.get("kennung") == rest.get("kennung") for r in reste):
            raise BestandError(f"Rest {rest.get('kennung')} gibt es in {pid!r} schon")
        reste.append(rest)
        reste.sort(key=lambda r: (str(r.get("kennung", ""))[:1], _kennung_nr(r.get("kennung"), "R")
                                  + _kennung_nr(r.get("kennung"), "P")))
    elif art == "stueck":
        p = _posten_von(data, pid)
        assert p is not None
        rows = p.setdefault("stueck", [])
        laenge = op.get("laenge")
        row = next((r for r in rows if _same_len(r.get("laenge"), laenge)), None)
        delta = int(op.get("delta") or 0)
        if row is None:
            if delta < 0:
                raise BestandError(f"Posten {pid!r}: kein Stückgut{_len_text(laenge)} im Bestand")
            row = {"laenge": laenge, "anzahl": 0} if laenge is not None else {"anzahl": 0}
            rows.append(row)
        neu = int(number(row.get("anzahl")) or 0) + delta
        if neu < 0:
            raise BestandError(f"Posten {pid!r}: nur noch {row.get('anzahl')} Stück{_len_text(laenge)} im Bestand, "
                               f"{-delta} gebraucht")
        row["anzahl"] = neu
    elif art == "spule":
        liste = data.get("filament")
        if not isinstance(liste, list):
            liste = data["filament"] = []
        k = op.get("kennung")
        idx = next((i for i, sp in enumerate(liste) if isinstance(sp, dict) and sp.get("kennung") == k), None)
        aktuell = liste[idx] if idx is not None else None
        if op.get("pruefen_vorher", True) and _norm(aktuell) != _norm(op.get("vorher")):
            raise BestandError(f"Spule {k} wurde inzwischen geändert; erst die neueren Buchungen rückgängig machen")
        if op.get("nachher") is None:
            if idx is not None:
                liste.pop(idx)
        elif idx is None:
            liste.append(copy.deepcopy(op["nachher"]))
        else:
            liste[idx] = copy.deepcopy(op["nachher"])
        liste.sort(key=lambda sp: spule_nr(sp.get("kennung")) if isinstance(sp, dict) else 0)
    elif art == "filament_fuehren":
        if op.get("nachher"):
            if not isinstance(data.get("filament"), list):
                data["filament"] = []
        elif spulen(data):
            raise BestandError("Filament lässt sich nicht abschalten, solange Spulen im Bestand sind")
        else:
            data.pop("filament", None)
    elif art == "spule_gramm":
        k = op.get("kennung")
        sp = next((x for x in spulen(data) if x.get("kennung") == k), None)
        if sp is None:
            raise BestandError(f"Spule {k} ist nicht mehr im Bestand")
        neu_g = float(number(sp.get("gramm")) or 0) + float(op.get("delta") or 0)
        if neu_g < -0.05:
            raise BestandError(f"Spule {k}: nur noch {gramm_text(sp.get('gramm') or 0)}, "
                               f"{gramm_text(-float(op.get('delta') or 0))} gebraucht")
        sp["gramm"] = zahl(max(0.0, neu_g))
    else:
        raise BestandError(f"Änderung {art!r} unbekannt")


def umkehren(op: dict[str, Any]) -> dict[str, Any]:
    """Gegenstück einer Änderung."""
    art = op.get("op")
    out = copy.deepcopy(op)
    if art in ("posten", "einstellungen", "spule", "filament_fuehren"):
        out["vorher"], out["nachher"] = op.get("nachher"), op.get("vorher")
    elif art in ("ganze", "stueck"):
        out["delta"] = -int(op.get("delta") or 0)
    elif art == "spule_gramm":
        out["delta"] = zahl(-float(op.get("delta") or 0))
    elif art == "rest_weg":
        out["op"] = "rest_neu"
    elif art == "rest_neu":
        out["op"] = "rest_weg"
    return out


def _same_len(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 1e-6


def _len_text(laenge: Any) -> str:
    return f" mit {mm(laenge)} mm Länge" if laenge is not None else ""


def _norm(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------------------------------------------------
# Texte


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def posten_aenderungen(pid: str, vorher: dict[str, Any] | None, nachher: dict[str, Any] | None) -> list[dict]:
    """Ein ganzer Posten als feine Änderungen (nur für Texte)."""
    v, n = vorher or {}, nachher or {}
    ops: list[dict[str, Any]] = []
    gv = int(number((v.get("ganze") or {}).get("anzahl")) or 0)
    gn = int(number((n.get("ganze") or {}).get("anzahl")) or 0)
    if gv != gn:
        g = n.get("ganze") or v.get("ganze") or {}
        ops.append({"op": "ganze", "posten": pid, "delta": gn - gv, **{k: g[k] for k in ("laenge", "b", "h") if k in g}})
    rv = {r.get("kennung"): r for r in v.get("reste") or [] if isinstance(r, dict)}
    rn = {r.get("kennung"): r for r in n.get("reste") or [] if isinstance(r, dict)}
    for k, r in rv.items():
        if k not in rn or _norm(rn[k]) != _norm(r):
            ops.append({"op": "rest_weg", "posten": pid, "rest": r})
    for k, r in rn.items():
        if k not in rv or _norm(rv[k]) != _norm(r):
            ops.append({"op": "rest_neu", "posten": pid, "rest": r})
    sv = {(None if r.get("laenge") is None else float(r["laenge"])): int(number(r.get("anzahl")) or 0)
          for r in v.get("stueck") or [] if isinstance(r, dict)}
    sn = {(None if r.get("laenge") is None else float(r["laenge"])): int(number(r.get("anzahl")) or 0)
          for r in n.get("stueck") or [] if isinstance(r, dict)}
    for key in sorted(set(sv) | set(sn), key=lambda x: (x is None, x or 0)):
        d = sn.get(key, 0) - sv.get(key, 0)
        if d:
            ops.append({"op": "stueck", "posten": pid, "laenge": key, "delta": d})
    mv, mn = v.get("mindestrest_mm"), n.get("mindestrest_mm")
    if mv != mn:
        ops.append({"op": "mindestrest", "posten": pid, "vorher": mv, "nachher": mn})
    return ops


def _fein(aenderungen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for op in aenderungen:
        if op.get("op") == "posten":
            out += posten_aenderungen(str(op.get("posten")), op.get("vorher"), op.get("nachher"))
        else:
            out.append(op)
    return out


def zusammenfassung(aenderungen: list[dict[str, Any]]) -> str:
    """Kurztext einer Buchung, z. B. „2 Reste weg, 1 ganze Stange weg, 1 Rest neu (R-0012, 144 mm)“."""
    ops = _fein(aenderungen)
    weg = [op for op in ops if op.get("op") == "rest_weg"]
    neu = [op for op in ops if op.get("op") == "rest_neu"]
    parts: list[str] = []
    if weg:
        parts.append(f"{_plural(len(weg), 'Rest', 'Reste')} weg")
    for sign, word in ((-1, "weg"), (1, "dazu")):
        bars = sum(abs(op["delta"]) for op in ops if op.get("op") == "ganze" and op["delta"] * sign > 0
                   and not ist_platte(op))
        plates = sum(abs(op["delta"]) for op in ops if op.get("op") == "ganze" and op["delta"] * sign > 0
                     and ist_platte(op))
        if bars:
            parts.append(f"{_plural(bars, 'ganze Stange', 'ganze Stangen')} {word}")
        if plates:
            parts.append(f"{_plural(plates, 'ganze Platte', 'ganze Platten')} {word}")
        st = sum(abs(op["delta"]) for op in ops if op.get("op") == "stueck" and op["delta"] * sign > 0)
        if st:
            parts.append(f"{st} Stück {word}")
    if neu:
        details = ", ".join(_rest_text(op.get("rest") or {}).replace(" (", " ").rstrip(")") for op in neu[:4])
        more = " …" if len(neu) > 4 else ""
        parts.append(f"{_plural(len(neu), 'Rest', 'Reste')} neu ({details}{more})")
    parts += _spulen_zusammenfassung(ops)
    for op in ops:
        if op.get("op") == "mindestrest":
            parts.append(f"Mindestrest {op.get('posten')}: {_mm_or(op.get('vorher'))} → {_mm_or(op.get('nachher'))}")
        if op.get("op") == "einstellungen":
            v, n = op.get("vorher") or {}, op.get("nachher") or {}
            for key, label in (("mindestrest_mm", "Mindestrest"), ("saegeblatt_mm", "Sägeblatt")):
                if v.get(key) != n.get(key):
                    parts.append(f"{label} {_mm_or(v.get(key))} → {_mm_or(n.get(key))}")
    return ", ".join(parts) or "keine Änderung"


def _mm_or(v: Any) -> str:
    return "Standard" if v is None else f"{mm(v)} mm"


def _spule_leer(sp: Any) -> bool:
    return isinstance(sp, dict) and float(number(sp.get("gramm")) or 0) <= 0.05


def _spulen_zusammenfassung(ops: list[dict[str, Any]]) -> list[str]:
    """„548,2 g Filament verbraucht, 1 Spule leer, 1 Spule neu (S-0004 452 g)“."""
    parts: list[str] = []
    deltas = [float(op.get("delta") or 0) for op in ops if op.get("op") == "spule_gramm"]
    weg_g = -sum(d for d in deltas if d < 0)
    dazu_g = sum(d for d in deltas if d > 0)
    if weg_g > 0:
        parts.append(f"{gramm_text(weg_g)} Filament verbraucht")
    if dazu_g > 0:
        parts.append(f"{gramm_text(dazu_g)} Filament zurück")
    sp = [op for op in ops if op.get("op") == "spule"]
    leer = [op for op in sp if op.get("nachher") is None and _spule_leer(op.get("vorher"))]
    weg = [op for op in sp if op.get("nachher") is None and op.get("vorher") is not None and op not in leer]
    neu = [op for op in sp if op.get("vorher") is None and op.get("nachher") is not None]
    geaendert = [op for op in sp if op.get("vorher") is not None and op.get("nachher") is not None]
    if leer:
        parts.append(_plural(len(leer), "Spule", "Spulen") + " leer")
    if weg:
        parts.append(_plural(len(weg), "Spule", "Spulen") + " weg (" + ", ".join(str(op.get("kennung"))
                                                                              for op in weg) + ")")
    if neu:
        parts.append(_plural(len(neu), "Spule", "Spulen") + " neu (" + ", ".join(
            f"{op.get('kennung')} {gramm_text((op.get('nachher') or {}).get('gramm') or 0)}" for op in neu[:4])
            + (" …" if len(neu) > 4 else "") + ")")
    for op in geaendert:
        v, n = op.get("vorher") or {}, op.get("nachher") or {}
        if number(v.get("gramm")) != number(n.get("gramm")):
            parts.append(f"Spule {op.get('kennung')}: {gramm_text(v.get('gramm') or 0)} → "
                         f"{gramm_text(n.get('gramm') or 0)}")
        else:
            parts.append(f"Spule {op.get('kennung')} geändert")
    for op in ops:
        if op.get("op") == "filament_fuehren":
            parts.append("Filament wird geführt" if op.get("nachher") else "Filament wird nicht mehr geführt")
    return parts


def spule_text(sp: dict[str, Any]) -> str:
    """„S-0001 Bambu PETG Basic schwarz, 640 von 1.000 g, Regal 3“."""
    teile = [str(sp.get("kennung"))]
    bez = sp.get("name") or " ".join(str(x) for x in (sp.get("hersteller"), sp.get("farbe")) if x)
    if bez:
        teile[0] += f" {bez}"
    g = gramm_text(sp.get("gramm") or 0)
    if sp.get("gramm_voll"):
        g = f"{mm(sp.get('gramm') or 0)} von {gramm_text(sp['gramm_voll'])}"
    teile.append(g)
    if sp.get("ort"):
        teile.append(str(sp["ort"]))
    return ", ".join(teile)


def _spulen_zeilen(op: dict[str, Any], material_name: Callable[[str], str]) -> list[str]:
    art = op.get("op")
    k = op.get("kennung")
    if art == "spule_gramm":
        mat = material_name(str(op.get("material") or ""))
        d = float(op.get("delta") or 0)
        return [f"Filament {mat}: {gramm_text(abs(d))} von Spule {k} {'verbraucht' if d < 0 else 'zurückgebucht'}"]
    v, n = op.get("vorher"), op.get("nachher")
    mat = material_name(str((n or v or {}).get("material") or ""))
    if v is None and n is not None:
        return [f"Filament {mat}: Spule {spule_text(n)} dazu"]
    if n is None and v is not None:
        return [f"Filament {mat}: Spule {k} {'leer, entfernt' if _spule_leer(v) else 'weg'}"]
    if v is None or n is None:
        return []
    aend = []
    if number(v.get("gramm")) != number(n.get("gramm")):
        aend.append(f"{gramm_text(v.get('gramm') or 0)} → {gramm_text(n.get('gramm') or 0)}")
    for key, label in (("gramm_voll", "volle Spule"), ("name", "Name"), ("hersteller", "Hersteller"),
                       ("farbe", "Farbe"), ("ort", "Ort"), ("material", "Material")):
        if v.get(key) != n.get(key):
            alt = v.get(key) if v.get(key) is not None else "–"
            neu = n.get(key) if n.get(key) is not None else "–"
            aend.append(f"{label} {alt} → {neu}")
    return [f"Filament {mat}: Spule {k} " + (", ".join(aend) if aend else "unverändert")]


def aenderungen_text(aenderungen: list[dict[str, Any]], benennung: Callable[[str], str] | None = None,
                     material_name: Callable[[str], str] | None = None) -> list[str]:
    """Jede Änderung als eigene Zeile (für die Antwort an Kevin)."""
    name = benennung or (lambda pid: pid)
    mat_name = material_name or (lambda mid: mid)
    lines: list[str] = []
    for op in _fein(aenderungen):
        art = op.get("op")
        pid = str(op.get("posten") or "")
        if art in ("spule", "spule_gramm"):
            lines += _spulen_zeilen(op, mat_name)
            continue
        if art == "filament_fuehren":
            lines.append("Filament: wird in diesem Projekt geführt (Spulen, Einkauf, Abbuchen)" if op.get("nachher")
                         else "Filament: wird in diesem Projekt nicht mehr geführt")
            continue
        if art == "ganze":
            what = "ganze Platte" if ist_platte(op) else "ganze Stange"
            whats = "ganze Platten" if ist_platte(op) else "ganze Stangen"
            dims = (f" à {mm(op['b'])} × {mm(op['h'])} mm" if ist_platte(op) and op.get("b") is not None
                    else (f" à {mm(op['laenge'])} mm" if op.get("laenge") is not None else ""))
            d = int(op["delta"])
            lines.append(f"{name(pid)}: {_plural(abs(d), what, whats)}{dims} {'dazu' if d > 0 else 'weg'}")
        elif art in ("rest_weg", "rest_neu"):
            rest = op.get("rest") or {}
            ort = f", Ort {rest['ort']}" if rest.get("ort") else ""
            lines.append(f"{name(pid)}: Rest {_rest_text(rest)}{ort} {'weg' if art == 'rest_weg' else 'dazu'}")
        elif art == "stueck":
            d = int(op["delta"])
            lines.append(f"{name(pid)}: {abs(d)} Stück{_len_text(op.get('laenge'))} {'dazu' if d > 0 else 'weg'}")
        elif art == "mindestrest":
            lines.append(f"{name(pid)}: Mindestrest {_mm_or(op.get('vorher'))} → {_mm_or(op.get('nachher'))}")
        elif art == "einstellungen":
            lines.append("Einstellungen: " + zusammenfassung([op]))
    return lines


# ---------------------------------------------------------------------------------------------------------------------
# Datei


def _lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = _LOCKS[key] = threading.RLock()
        return lk


def _atomar(path: Path, text: str) -> None:
    """Schreibt erst eine Temp-Datei im selben Ordner und ersetzt dann (os.replace): nie eine halbe Datei."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class BestandDatei:
    """bestand.json und das Buchungsprotokoll eines Projekts."""

    def __init__(self, pfad: str | Path, buchungen: str | Path | None = None, projekt: str = "",
                 katalog: Katalog | None = None) -> None:
        self.pfad = Path(pfad)
        self.buchungen_pfad = Path(buchungen) if buchungen is not None else self.pfad.with_name(BUCHUNGEN_DATEI)
        self.projekt = projekt
        self.katalog = katalog
        self.lock = _lock(self.pfad)

    @classmethod
    def fuer_projekt(cls, projekt: str | Path, name: str = "", katalog: Katalog | None = None) -> BestandDatei:
        p, b = pfade(projekt)
        assert p is not None
        return cls(p, b, name or Path(projekt).name, katalog)

    # -- Lesen ---------------------------------------------------------------------------------------------------------

    @property
    def existiert(self) -> bool:
        return self.pfad.is_file()

    def signatur(self) -> tuple:
        sig = []
        for p in (self.pfad, self.buchungen_pfad):
            try:
                st = p.stat()
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        return tuple(sig)

    def stand(self) -> str | None:
        """Änderungszeit der Datei als ISO-Zeit (lokal), None ohne Datei."""
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.pfad.stat().st_mtime))
        except OSError:
            return None

    def lesen(self) -> dict[str, Any]:
        """Inhalt (leerer Bestand, wenn die Datei fehlt). Kaputtes JSON oder ungültiger Inhalt → BestandError."""
        with self.lock:
            if not self.pfad.exists():
                return leerer_bestand()
            try:
                data = json.loads(self.pfad.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise BestandError(f"{self.pfad.name}: kein gültiges JSON (Zeile {exc.lineno}, Spalte {exc.colno}: "
                                   f"{exc.msg})") from exc
            except OSError as exc:
                raise BestandError(f"{self.pfad.name}: nicht lesbar ({exc})") from exc
            errors = pruefe(data)
            if errors:
                raise BestandError(f"{self.pfad.name}: " + "; ".join(errors))
            data.setdefault("version", VERSION)
            data.setdefault("einstellungen", leerer_bestand()["einstellungen"])
            data.setdefault("posten", {})
            return data

    def buchungen(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Buchungen, neueste zuerst, je mit ``zusammenfassung`` und ``rueckgaengig_durch``."""
        rows = self._alle_buchungen()
        undone: dict[str, str] = {}
        for b in rows:
            if b.get("art") == "rueckgaengig" and b.get("bezug"):
                undone[str(b["bezug"])] = str(b.get("id"))
        out = []
        for b in reversed(rows):
            row = dict(b)
            row["zusammenfassung"] = zusammenfassung(b.get("aenderungen") or [])
            row["rueckgaengig_durch"] = undone.get(str(b.get("id")))
            out.append(row)
            if limit is not None and len(out) >= limit:
                break
        return out

    def buchung(self, bid: str) -> dict[str, Any] | None:
        return next((b for b in self.buchungen() if b.get("id") == bid), None)

    def _alle_buchungen(self) -> list[dict[str, Any]]:
        try:
            text = self.buchungen_pfad.read_text(encoding="utf-8")
        except OSError:
            return []
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # angefangene Zeile nach einem Absturz: überspringen
            if isinstance(row, dict) and row.get("id"):
                rows.append(row)
        return rows

    # -- Schreiben -----------------------------------------------------------------------------------------------------

    def schreiben(self, data: dict[str, Any]) -> None:
        """Prüft und schreibt atomar. Ungültig → BestandError (Datei bleibt unverändert)."""
        errors = pruefe(data, self.katalog)
        if errors:
            raise BestandError("\n".join(errors))
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        try:
            _atomar(self.pfad, text)
        except OSError as exc:
            raise BestandError(f"{self.pfad} nicht schreibbar: {exc}") from exc

    def kennungen(self, data: dict[str, Any] | None = None) -> Kennungen:
        return Kennungen(hoechste_kennungen(data if data is not None else self.lesen(), self._alle_buchungen()))

    def buchen(self, art: str, aenderungen: list[dict[str, Any]], *, von: str = "kevin", grund: str = "",
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Änderungen anwenden, Datei schreiben, Buchung anhängen. Rückgabe: die Buchung (mit Zusammenfassung)."""
        if art not in ARTEN:
            raise BestandError(f"Buchungsart {art!r} unbekannt ({', '.join(ARTEN)})")
        if von not in VON:
            raise BestandError(f"von {von!r} unbekannt (kevin oder agent)")
        if not aenderungen:
            raise BestandError("Keine Änderung: nichts zu buchen")
        with self.lock:
            alt_text = self.pfad.read_text(encoding="utf-8") if self.pfad.exists() else None
            data = self.lesen()
            for op in aenderungen:
                anwenden(data, op)
            self.schreiben(data)
            rows = self._alle_buchungen()
            nr = max((int(m.group(1)) for b in rows if (m := re.match(r"^B-(\d+)$", str(b.get("id"))))),
                     default=0) + 1
            row = {"id": f"B-{nr:04d}", "zeit": jetzt_iso(), "art": art, "projekt": self.projekt,
                   "aenderungen": [_ohne_intern(op) for op in aenderungen], "von": von, "grund": grund or "",
                   **(extra or {})}
            try:
                self.buchungen_pfad.parent.mkdir(parents=True, exist_ok=True)
                with open(self.buchungen_pfad, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as exc:
                # Ohne Protokoll keine Änderung: alten Stand zurück
                try:
                    if alt_text is None:
                        self.pfad.unlink(missing_ok=True)
                    else:
                        _atomar(self.pfad, alt_text)
                except OSError:
                    pass
                raise BestandError(f"Buchungsprotokoll {self.buchungen_pfad} nicht schreibbar: {exc}") from exc
            return {**row, "zusammenfassung": zusammenfassung(row["aenderungen"]), "rueckgaengig_durch": None}

    def rueckgaengig(self, bid: str, *, von: str = "kevin", grund: str = "") -> dict[str, Any]:
        """Bucht die Umkehrung einer Buchung (art ``rueckgaengig``, ``bezug`` = id)."""
        with self.lock:
            rows = self.buchungen()
            ziel = next((b for b in rows if b.get("id") == bid), None)
            if ziel is None:
                ids = [b.get("id") for b in rows[:8]]
                raise BestandError(f"Buchung {bid!r} gibt es nicht" + (f" (letzte: {', '.join(ids)})" if ids else ""))
            if ziel.get("rueckgaengig_durch"):
                raise BestandError(f"Buchung {bid} ist schon rückgängig gemacht (durch {ziel['rueckgaengig_durch']})")
            ops = [umkehren(op) for op in reversed(ziel.get("aenderungen") or [])]
            try:
                return self.buchen("rueckgaengig", ops, von=von, grund=grund or f"{bid} rückgängig",
                                   extra={"bezug": bid})
            except BestandError as exc:
                raise BestandError(f"Buchung {bid} lässt sich nicht rückgängig machen: {exc}") from exc


def _ohne_intern(op: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in op.items() if k != "pruefen_vorher"}
