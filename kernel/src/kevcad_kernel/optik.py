"""Kameras und Objektive (KATALOG.md, Abschnitt „Kameras und Objektive“): Katalogeinträge prüfen und Optik rechnen.

Bewusst ohne schwere Importe (kein build123d): läuft im Elternprozess (Katalog, MCP) und im Rechenprozess.

Rechnung wie am Set (PLAN-PHASE5 K3):

- Bildwinkel aus Sensorfläche und Brennweite: ``2 · atan(Seite / (2 · f))`` (Fokus unendlich, wie in Datenblättern).
- Schärfentiefe nach Zerstreuungskreis ``c`` des Formats, Blendenzahl ``N`` und Fokus ``s`` (ab Sensorebene, wie auf
  der Entfernungsskala): hyperfokale Distanz ``H = f² / (N · c) + f``, Nahpunkt ``s (H − f) / (H + s − 2 f)``,
  Fernpunkt ``s (H − f) / (H − s)`` (unendlich ab ``s ≥ H``). Bei Cine-Objektiven steht der T-Wert für ``N``
  (etwas mehr Schärfentiefe als mit der geometrischen Blende, für die Praxis vernachlässigbar).
"""

from __future__ import annotations

import math
import re
from typing import Any

OPTIK_ARTEN: tuple[str, ...] = ("kamera", "objektiv", "kamerazubehoer")
ZUBEHOER_TYPEN: tuple[str, ...] = ("kaefig", "baseplate", "rod", "rosette", "akkuplatte", "akku", "griff", "monitor",
                                  "sonstiges")
BLENDENARTEN = ("f", "t")
COC_TEILER = 1500.0  # Zerstreuungskreis = Diagonale der aktiven Sensorfläche / 1500, wenn das Format keinen angibt


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            x = float(value.strip().replace(",", "."))
        except ValueError:
            return None
        return x if math.isfinite(x) else None
    return None


def _pair(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        a, b = _num(value[0]), _num(value[1])
        if a is not None and b is not None:
            return a, b
    return None


# ---------------------------------------------------------------------------------------------------------------------
# Prüfen


def _text(entry: dict[str, Any], key: str, who: str, errors: list[str], required: bool = True) -> None:
    v = entry.get(key)
    if v is None:
        if required:
            errors.append(f"{who}: Feld {key} fehlt (Text)")
        return
    if not isinstance(v, str) or not v.strip():
        errors.append(f"{who}: {key} muss Text sein")


def _positive(entry: dict[str, Any], key: str, who: str, errors: list[str], required: bool = True,
              unit: str = "mm") -> None:
    v = entry.get(key)
    if v is None:
        if required:
            errors.append(f"{who}: Feld {key} fehlt (Zahl in {unit})")
        return
    x = _num(v)
    if x is None or x <= 0:
        errors.append(f"{who}: {key} muss eine Zahl > 0 sein ({unit})")


def validate_format(fmt: Any, who: str) -> list[str]:
    if not isinstance(fmt, dict):
        return [f"{who}: jedes Format ist ein Objekt mit id, name, sensor_mm und aufloesung"]
    errors: list[str] = []
    fid = fmt.get("id")
    if not isinstance(fid, str) or not re.match(r"^[a-z0-9][a-z0-9._-]*$", fid):
        errors.append(f"{who}: Format ohne gültige id (Kleinbuchstaben, Ziffern, Bindestriche, z. B. \"ff-uhd\")")
        fid = "?"
    w = f"{who}, Format {fid}"
    _text(fmt, "name", w, errors)
    sensor = _pair(fmt.get("sensor_mm"))
    res = fmt.get("aufloesung")
    if sensor is None or min(sensor) <= 0:
        errors.append(f"{w}: sensor_mm als [breite, hoehe] der aktiven Sensorfläche in mm angeben, z. B. [35.7, 20.1]")
    elif max(sensor) > 80:
        errors.append(f"{w}: sensor_mm {sensor} ist unplausibel (Angabe in mm, Vollformat etwa 36 × 24)")
    elif isinstance(res, (list, tuple)) and len(res) == 2 and all(isinstance(v, int) and v > 0 for v in res):
        if abs(sensor[0] / sensor[1] - res[0] / res[1]) / (res[0] / res[1]) > 0.03:
            errors.append(f"{w}: sensor_mm {list(sensor)} passt nicht zum Seitenverhältnis der Auflösung {list(res)} "
                          "(mehr als 3 % Abweichung)")
    res = fmt.get("aufloesung")
    if not (isinstance(res, (list, tuple)) and len(res) == 2 and all(isinstance(v, int) and not isinstance(v, bool)
                                                                     and v > 0 for v in res)):
        errors.append(f"{w}: aufloesung als [breite, hoehe] in Pixeln angeben, z. B. [3840, 2160]")
    for key in ("zerstreuungskreis", "fps_max"):
        if fmt.get(key) is not None:
            x = _num(fmt.get(key))
            if x is None or x <= 0:
                errors.append(f"{w}: {key} muss eine Zahl > 0 sein")
    coc = _num(fmt.get("zerstreuungskreis"))
    if coc is not None and coc > 0.2:
        errors.append(f"{w}: zerstreuungskreis {coc:g} mm ist unplausibel (üblich 0,01 bis 0,05 mm)")
    if fmt.get("modus") is not None and not isinstance(fmt.get("modus"), str):
        errors.append(f"{w}: modus muss Text sein")
    return errors


def _vec3(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(_num(v) is not None for v in value)


def validate_bezugspunkte(entry: dict[str, Any], who: str) -> list[str]:
    """``bezugspunkte``: {name: {"pos": [x, y, z], "richtung": [x, y, z]?, "hinweis": "…"?}} in lokalen Koordinaten des
    Eintrags (x Blickrichtung bzw. nach vorn, y links, z oben)."""
    pts = entry.get("bezugspunkte")
    if pts is None:
        return []
    if not isinstance(pts, dict):
        return [f"{who}: bezugspunkte muss ein Objekt {{name: {{\"pos\": [x, y, z]}}}} sein"]
    errors: list[str] = []
    for name, pt in pts.items():
        if not re.match(r"^[a-z0-9][a-z0-9_]*$", str(name)):
            errors.append(f"{who}: Bezugspunkt {name!r}: Name nur aus Kleinbuchstaben, Ziffern und _")
        if not isinstance(pt, dict) or not _vec3(pt.get("pos")):
            errors.append(f"{who}: Bezugspunkt {name!r} braucht pos [x, y, z] in mm")
            continue
        if pt.get("richtung") is not None and not _vec3(pt.get("richtung")):
            errors.append(f"{who}: Bezugspunkt {name!r}: richtung als [x, y, z]")
        if pt.get("von") is not None and (pt.get("von") != "front" or entry.get("art") != "kamera"):
            errors.append(f"{who}: Bezugspunkt {name!r}: von kennt nur \"front\" (bei Kameras: x ab der Gehäusefront)")
    return errors


def validate_geometrie(entry: dict[str, Any], who: str) -> list[str]:
    """``geometrie``: {"modul": "kevcad.geometrie.…", "funktion": "…"} oder {"datei": "geometrie/x.py", "funktion": "…"}
    (Datei relativ zur Katalogdatei)."""
    geo = entry.get("geometrie")
    if geo is None:
        return []
    if not isinstance(geo, dict) or not isinstance(geo.get("funktion"), str) or not geo["funktion"].isidentifier():
        return [f"{who}: geometrie braucht funktion (Name einer Python-Funktion) und modul oder datei"]
    has_mod = isinstance(geo.get("modul"), str) and bool(geo["modul"].strip())
    has_file = isinstance(geo.get("datei"), str) and geo["datei"].strip().endswith(".py")
    if has_mod == has_file:
        return [f"{who}: geometrie mit genau einem von modul (importierbar, z. B. \"kevcad.geometrie.kamerasystem\") "
                "oder datei (.py relativ zur Katalogdatei)"]
    return []


def validate_kamera(entry: dict[str, Any], who: str) -> list[str]:
    errors: list[str] = []
    for key in ("hersteller", "modell", "bajonett"):
        _text(entry, key, who, errors)
    _text(entry, "kurzname", who, errors, required=False)
    _positive(entry, "auflagemass", who, errors)
    formate = entry.get("formate")
    if not isinstance(formate, list) or not formate:
        errors.append(f"{who}: formate fehlt (Liste der Aufnahmeformate mit sensor_mm und aufloesung)")
    else:
        seen: set[str] = set()
        for f in formate:
            errors += validate_format(f, who)
            if isinstance(f, dict) and isinstance(f.get("id"), str):
                if f["id"] in seen:
                    errors.append(f"{who}: Format-id {f['id']!r} doppelt")
                seen.add(f["id"])
        std = entry.get("standard_format")
        if std is not None and std not in seen:
            errors.append(f"{who}: standard_format {std!r} steht nicht in formate ({', '.join(sorted(seen))})")
    geh = entry.get("gehaeuse")
    if not isinstance(geh, dict):
        errors.append(f"{who}: gehaeuse fehlt ({{\"b\": Breite, \"h\": Höhe, \"t\": Tiefe}} in mm)")
    else:
        for key in ("b", "h", "t"):
            _positive(geh, key, f"{who}, gehaeuse", errors)
        for key in ("achse_hoehe", "achse_seitlich", "bajonett_vorstand"):
            if geh.get(key) is not None and _num(geh.get(key)) is None:
                errors.append(f"{who}, gehaeuse: {key} muss eine Zahl sein (mm)")
    _positive(entry, "gewicht", who, errors, required=False, unit="g")
    if entry.get("schwerpunkt") is not None and not _vec3(entry.get("schwerpunkt")):
        errors.append(f"{who}: schwerpunkt als [x, y, z] in mm (lokal)")
    return errors


def validate_zubehoer(entry: dict[str, Any], who: str) -> list[str]:
    errors: list[str] = []
    _text(entry, "hersteller", who, errors, required=False)
    typ = entry.get("typ")
    if typ not in ZUBEHOER_TYPEN:
        errors.append(f"{who}: typ {typ!r} unbekannt (erlaubt: {', '.join(ZUBEHOER_TYPEN)})")
    masse = entry.get("masse")
    if masse is not None:
        if not isinstance(masse, dict) or not masse:
            errors.append(f"{who}: masse als Objekt in mm, z. B. {{\"b\": 95, \"h\": 146, \"t\": 39}} oder "
                          "{\"d\": 15, \"l\": 150}")
        else:
            for k, v in masse.items():
                x = _num(v)
                if k not in ("b", "h", "t", "d", "l") or x is None or x <= 0:
                    errors.append(f"{who}: masse.{k} unbekannt oder nicht > 0 (erlaubt b, h, t, d, l in mm)")
    _positive(entry, "gewicht", who, errors, required=False, unit="g")
    _text(entry, "ursprung", who, errors, required=False)
    if entry.get("schwerpunkt") is not None and not _vec3(entry.get("schwerpunkt")):
        errors.append(f"{who}: schwerpunkt als [x, y, z] in mm (lokal)")
    return errors


def validate_objektiv(entry: dict[str, Any], who: str) -> list[str]:
    errors: list[str] = []
    for key in ("hersteller", "bajonett"):
        _text(entry, key, who, errors)
    bw = entry.get("brennweite")
    rng = _pair(bw)
    if rng is not None:
        if rng[0] <= 0 or rng[1] <= rng[0]:
            errors.append(f"{who}: brennweite als [kurz, lang] mit 0 < kurz < lang angeben, z. B. [24, 105]")
    elif _num(bw) is None or _num(bw) <= 0:
        errors.append(f"{who}: brennweite fehlt (mm; Festbrennweite als Zahl, Zoom als [kurz, lang])")
    ls = _num(entry.get("lichtstaerke"))
    if ls is None or not 0.5 <= ls <= 64:
        errors.append(f"{who}: lichtstaerke fehlt (kleinste Blendenzahl, z. B. 2.8 oder 1.5 für T1,5)")
    if entry.get("blendenart") is not None and entry.get("blendenart") not in BLENDENARTEN:
        errors.append(f"{who}: blendenart muss \"f\" (Fotoobjektiv) oder \"t\" (Cine, T-Blende) sein")
    if entry.get("blende_max") is not None:
        mx = _num(entry.get("blende_max"))
        if mx is None or (ls is not None and mx < ls):
            errors.append(f"{who}: blende_max muss eine Zahl ≥ lichtstaerke sein (z. B. 22)")
    for key in ("naheinstellgrenze", "bildkreis", "laenge", "frontdurchmesser"):
        _positive(entry, key, who, errors)
    for key in ("filter",):
        _positive(entry, key, who, errors, required=False)
    _positive(entry, "gewicht", who, errors, required=False, unit="g")
    return errors


def validate_optik(entry: dict[str, Any]) -> list[str]:
    """Fehler eines Katalogeintrags mit ``art`` "kamera" oder "objektiv" (ohne id/name/preis/tags/status, die prüft
    ``catalog.validate_item``)."""
    who = f"Lagerteil {entry.get('id')!r}" if isinstance(entry.get("id"), str) else "Lagerteil"
    errors = validate_bezugspunkte(entry, who) + validate_geometrie(entry, who)
    if entry.get("hinweis") is not None and not isinstance(entry.get("hinweis"), str):
        errors.append(f"{who}: hinweis muss Text sein")
    if entry.get("art") == "kamera":
        return errors + validate_kamera(entry, who)
    if entry.get("art") == "kamerazubehoer":
        return errors + validate_zubehoer(entry, who)
    return errors + validate_objektiv(entry, who)


# ---------------------------------------------------------------------------------------------------------------------
# Rechnen


def bildwinkel(seite_mm: float, brennweite_mm: float) -> float:
    """Bildwinkel in Grad über eine Sensorseite (oder die Diagonale) bei Fokus unendlich."""
    return math.degrees(2.0 * math.atan(seite_mm / (2.0 * brennweite_mm)))


def hyperfokal(brennweite_mm: float, blende: float, coc_mm: float) -> float:
    """Hyperfokale Distanz in mm (ab Sensorebene)."""
    return brennweite_mm ** 2 / (blende * coc_mm) + brennweite_mm


def schaerfentiefe(brennweite_mm: float, blende: float, coc_mm: float, fokus_mm: float) -> tuple[float, float]:
    """(Nahpunkt, Fernpunkt) in mm ab Sensorebene; Fernpunkt ``math.inf``, wenn der Fokus auf oder hinter der
    hyperfokalen Distanz liegt. ``fokus_mm`` ``math.inf`` ergibt (H, inf)."""
    f = brennweite_mm
    h = hyperfokal(f, blende, coc_mm)
    s = fokus_mm
    if not math.isfinite(s):
        return h, math.inf
    near = s * (h - f) / (h + s - 2 * f)
    far = s * (h - f) / (h - s) if s < h else math.inf
    return near, far


def coc_fuer(sensor_mm: tuple[float, float]) -> float:
    """Zerstreuungskreis aus der Diagonale der aktiven Sensorfläche (d / 1500), auf 0,001 mm gerundet."""
    return round(math.hypot(*sensor_mm) / COC_TEILER, 3)


def brennweiten(entry: dict[str, Any]) -> tuple[float, float]:
    """(kürzeste, längste) Brennweite eines Objektivs; Festbrennweite: beide gleich."""
    rng = _pair(entry.get("brennweite"))
    if rng is not None:
        return rng
    f = _num(entry.get("brennweite")) or 0.0
    return f, f


def ist_zoom(entry: dict[str, Any]) -> bool:
    a, b = brennweiten(entry)
    return b > a


def format_von(entry: dict[str, Any], wunsch: str | None) -> dict[str, Any]:
    """Format einer Kamera nach id oder Stichwort ("uhd", "dci", "s35", "Vollformat UHD"); None = Standardformat.
    Unbekannt → ValueError mit den vorhandenen Formaten."""
    formate = [f for f in entry.get("formate") or [] if isinstance(f, dict)]
    if not formate:
        raise ValueError(f"Kamera {entry.get('id')!r} hat keine Formate im Katalog")
    if wunsch is None or not str(wunsch).strip():
        std = entry.get("standard_format")
        return next((f for f in formate if f.get("id") == std), formate[0])
    key = str(wunsch).strip().lower()
    for f in formate:
        if f.get("id") == key:
            return f
    tokens = [t for t in re.split(r"[\s_/·,-]+", key.replace("×", "x")) if t]

    def words(f: dict[str, Any]) -> str:
        bits = [f.get("id", ""), f.get("name", ""), f.get("modus", "")]
        res = f.get("aufloesung")
        if isinstance(res, list) and len(res) == 2:
            bits += [f"{res[0]}x{res[1]}", str(res[0])]
        return " ".join(str(b) for b in bits).lower().replace("×", "x").replace(" x ", "x")

    hits = [f for f in formate if all(t in words(f) for t in tokens)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        std = entry.get("standard_format")
        pick = next((f for f in hits if f.get("id") == std), None)
        if pick is not None:
            return pick
        shortest = min(hits, key=lambda f: len(str(f.get("id"))))
        return shortest
    listing = ", ".join(f"{f.get('id')} ({f.get('name')})" for f in formate)
    raise ValueError(f"Format {wunsch!r} gibt es für {entry.get('name') or entry.get('id')} nicht. Formate: {listing}")


def format_info(fmt: dict[str, Any]) -> dict[str, Any]:
    """Format mit berechneten Werten: Seitenverhältnis, Diagonale, Zerstreuungskreis (angegeben oder d/1500).

    Die aktive Höhe folgt aus der Breite und dem Seitenverhältnis der Auflösung (quadratische Pixel), damit
    Bildwinkel, Formatrahmen und Kamerabild genau zusammenpassen; die Katalogangabe steht in ``sensor_mm_katalog``
    (Datenblätter runden die Höhe, z. B. 18,8 statt 18,83 mm)."""
    sb, sh_angabe = _pair(fmt.get("sensor_mm")) or (0.0, 0.0)
    res = fmt.get("aufloesung") or [0, 0]
    sh = sb * res[1] / res[0] if res[0] and res[1] else sh_angabe
    coc = _num(fmt.get("zerstreuungskreis"))
    return {
        "id": fmt.get("id"), "name": fmt.get("name"), "modus": fmt.get("modus"),
        "sensor_mm": [sb, sh], "sensor_mm_katalog": [sb, sh_angabe], "aufloesung": [int(res[0]), int(res[1])],
        "seitenverhaeltnis": round(res[0] / res[1], 4) if res[1] else (round(sb / sh, 4) if sh else None),
        "diagonale_mm": round(math.hypot(sb, sh), 3),
        "zerstreuungskreis": coc if coc is not None else coc_fuer((sb, sh)),
        "fps_max": _num(fmt.get("fps_max")),
        "hinweis": fmt.get("hinweis"),
    }


def mm_text(mm: float | None) -> str:
    """Entfernung für Texte: unter 1 m in cm, sonst m mit zwei Stellen, unendlich als ∞."""
    if mm is None or not math.isfinite(mm):
        return "∞"
    if mm < 1000:
        return f"{mm / 10:.1f} cm".replace(".", ",")
    return f"{mm / 1000:.2f} m".replace(".", ",")


def blende_text(blende: float, art: str = "f") -> str:
    text = f"{blende:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"T{text}" if art == "t" else f"f/{text}"
