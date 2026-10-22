"""Feste Druckeinstellungen je Teil: ``<projekt>/druck.json`` (Druckvorschau, DRUCKVORSCHAU.md).

Kevin (App, ``PRINT_SETTINGS``) oder der Agent (MCP ``druck_einstellen``) legen Zweck und Einstellungen je Teil fest;
sie überleben Läufe und gehören zu den Projektdateien (und damit zu den Versionen). Gespeichert wird je Teilname aus
``show()``, damit eine Vorgabe Formänderungen übersteht; eine Gruppe schreibt alle ihre Teile.

Format::

    {"version": 1, "teile": {"Kugelschieber/Fangrolle (Druck)": {"zweck": "bewegt",
                                                                "einstellungen": {"waende": 5, "fuellung": 0.3},
                                                                "von": {"zweck": "kevin", "waende": "kevin",
                                                                        "fuellung": "agent"},
                                                                "stand": "2026-10-22T09:12:00"}}}

``von`` sagt je Vorgabe, wer sie gesetzt hat (``kevin`` aus der App, ``agent`` über MCP); ältere Dateien mit einem
einzelnen Wert gelten für alle Vorgaben des Teils.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.protocol import DRUCK_MUSTER, DRUCK_STUETZEN, DRUCK_ZWECKE

DATEI = "druck.json"
SCHICHTEN = (0.08, 0.12, 0.16, 0.2, 0.24, 0.28)


class VorgabeFehler(ValueError):
    pass


def pfad(projekt: str | Path) -> Path:
    return Path(projekt) / DATEI


def lies(projekt: str | Path | None) -> dict[str, Any]:
    if projekt is None:
        return {"version": 1, "teile": {}}
    try:
        d = json.loads(pfad(projekt).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "teile": {}}
    except (OSError, ValueError) as exc:
        return {"version": 1, "teile": {}, "fehler": f"druck.json nicht lesbar: {exc}"}
    if not isinstance(d, dict) or not isinstance(d.get("teile", {}), dict):
        return {"version": 1, "teile": {}, "fehler": "druck.json muss {\"version\": 1, \"teile\": {…}} sein"}
    d.setdefault("version", 1)
    d.setdefault("teile", {})
    return d


def von_je_schluessel(t: dict[str, Any]) -> dict[str, str]:
    """Wer welche Vorgabe gesetzt hat ({schlüssel: "kevin" | "agent"}); ältere Dateien mit einem Wert für alles."""
    v = t.get("von")
    schluessel = list((t.get("einstellungen") or {}).keys()) + (["zweck"] if t.get("zweck") else [])
    if isinstance(v, dict):
        return {k: str(w) for k, w in v.items() if k in schluessel}
    if isinstance(v, str):
        return {k: v for k in schluessel}
    return {k: "kevin" for k in schluessel}


def pruefe_einstellungen(e: dict[str, Any]) -> dict[str, Any]:
    """Werte prüfen und vereinheitlichen; ``None`` bleibt (nimmt die Vorgabe zurück)."""
    out: dict[str, Any] = {}
    for k, v in (e or {}).items():
        if v is None:
            out[k] = None
            continue
        if k == "schicht_mm":
            h = float(v)
            beste = min(SCHICHTEN, key=lambda s: abs(s - h))
            if abs(beste - h) > 0.011:
                raise VorgabeFehler(f"Schicht {h:g} mm gibt es im P1P-Profil nicht (0,08 bis 0,28 mm)")
            out[k] = beste
        elif k in ("waende", "decken", "boeden"):
            n = int(v)
            if not (0 <= n <= 20) or (k == "waende" and n < 1):
                raise VorgabeFehler(f"{k} {v!r} liegt außerhalb von {'1' if k == 'waende' else '0'} bis 20")
            out[k] = n
        elif k == "fuellung":
            f = float(v)
            if f > 1.0:  # in Prozent angegeben
                f /= 100.0
            if not 0.0 <= f <= 1.0:
                raise VorgabeFehler(f"Füllung {v!r} muss zwischen 0 und 1 (oder 0–100 %) liegen")
            out[k] = round(f, 3)
        elif k == "muster":
            if str(v) not in DRUCK_MUSTER:
                raise VorgabeFehler(f"Muster {v!r} unbekannt (erlaubt: {', '.join(DRUCK_MUSTER)})")
            out[k] = str(v)
        elif k == "stuetzen":
            if str(v) not in DRUCK_STUETZEN:
                raise VorgabeFehler(f"Stützen {v!r} unbekannt (erlaubt: {', '.join(DRUCK_STUETZEN)})")
            out[k] = str(v)
        elif k == "brim":
            out[k] = bool(v)
        elif k == "ausrichtung":
            raise VorgabeFehler("Die Ausrichtung legt die Druckprüfung fest: in model.py lager.druckteil(…, "
                                "ausrichtung=\"-z\" / \"+x\" / Flächennummer …) angeben")
        else:
            raise VorgabeFehler(f"Einstellung {k!r} unbekannt")
    return out


def setze(projekt: str | Path, namen: list[str], *, einstellungen: dict[str, Any] | None = None,
          zweck: str | None = None, zuruecksetzen: bool = False, von: str = "kevin") -> dict[str, Any]:
    """Vorgaben für die Teile ``namen`` ändern und speichern; liefert den neuen Inhalt."""
    if zweck is not None and zweck not in DRUCK_ZWECKE:
        raise VorgabeFehler(f"Zweck {zweck!r} unbekannt (erlaubt: {', '.join(DRUCK_ZWECKE)})")
    neu_e = pruefe_einstellungen(einstellungen or {})
    d = lies(projekt)
    d.pop("fehler", None)
    teile = d["teile"]
    for name in namen:
        t = dict(teile.get(name) or {})
        if zuruecksetzen:
            t = {}
        e = dict(t.get("einstellungen") or {})
        wer = von_je_schluessel(t)
        for k, v in neu_e.items():
            if v is None:
                e.pop(k, None)
                wer.pop(k, None)
            else:
                e[k] = v
                wer[k] = von
        if e:
            t["einstellungen"] = e
        else:
            t.pop("einstellungen", None)
        if zweck is not None:
            t["zweck"] = zweck
            wer["zweck"] = von
        wer = {k: w for k, w in wer.items() if k in e or (k == "zweck" and t.get("zweck"))}
        if t.get("einstellungen") or t.get("zweck"):
            t["von"] = wer
            t["stand"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            teile[name] = t
        else:
            teile.pop(name, None)
    p = pfad(projekt)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)
    return d
