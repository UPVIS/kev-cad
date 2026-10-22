"""Katalog für Materialien und Lagerteile (KATALOG.md): drei Ebenen laden, zusammenführen, prüfen, suchen, speichern.

Ebenen in dieser Reihenfolge (spätere ersetzt frühere bei gleicher ``id``, ``"entfernt": true`` blendet aus):

1. ``mitgeliefert``: ``kernel/src/kevcad/katalog/*.json`` (für Tests per ``KEVCAD_CATALOG_BUILTIN_DIR`` übersteuerbar)
2. ``eigen``: ``~/Library/Application Support/de.upvis.kevcad/katalog/*.json``, per ``KEVCAD_CATALOG_DIR`` übersteuerbar.
   Liegt der Socket der App in einem Ordner ``…/de.upvis.kevcad*/`` (Testvarianten der App), gilt der Ordner
   ``katalog`` daneben; für die installierte App ist das genau der Pfad oben.
3. ``projekt``: ``<projekt>/katalog.json``

Die Klasse ist threadsicher und lädt neu, sobald sich eine der Dateien ändert (Prüfung bei jedem Zugriff über
Änderungszeit und Größe). Importiert nichts Schweres: Sie läuft im Elternprozess und im Rechenprozess.
"""

from __future__ import annotations

import copy
import difflib
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.optik import OPTIK_ARTEN, validate_optik

ARTEN: tuple[str, ...] = (
    "rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil", "nutprofil", "holz",
    "platte", "schraube", "mutter", "scheibe",
    # Phase 5 (KAM): Kameras und Objektive (KATALOG.md, Abschnitt „Kameras und Objektive“), geprüft in optik.py
    "kamera", "objektiv", "kamerazubehoer",
)
STANGENWARE = frozenset(ARTEN[:10])
# Zukaufteile (Phase 3, kevcad_kernel.zukauf): eigene Felder statt Querschnitt und Material; Kameras, Objektive und
# Kamera-Zubehör kommen als weitere Sonderformen dazu
ZUKAUF_ARTEN: tuple[str, ...] = ("zukaufteil",)
ALLE_ARTEN: tuple[str, ...] = ARTEN + ZUKAUF_ARTEN
KLEINTEILE = frozenset({"schraube", "mutter", "scheibe"})
# Zukaufteile, Kameras, Objektive und Kamera-Zubehör führt der Bestand als Stückgut wie die Kleinteile (BESTAND.md,
# Strang „Feinschliff 2“): eine Anzahl je Lagerteil, ohne Länge
STUECKGUT_ZUKAUF = frozenset({"zukaufteil", "kamera", "objektiv", "kamerazubehoer"})
STUECKGUT = KLEINTEILE | STUECKGUT_ZUKAUF
EBENEN: tuple[str, ...] = ("mitgeliefert", "eigen", "projekt")
WRITABLE = ("eigen", "projekt")
KINDS = {"teil": "teil", "teile": "teil", "item": "teil", "stock": "teil", "lagerteil": "teil",
         "material": "material", "materialien": "material", "materials": "material"}

ART_NAMEN = {
    "rohr": "Rohr", "vierkantrohr": "Vierkantrohr", "rechteckrohr": "Rechteckrohr", "flach": "Flachstahl",
    "rund": "Rundstahl", "vierkant": "Vierkantstahl", "winkel": "Winkel", "u_profil": "U-Profil",
    "nutprofil": "Nutprofil", "holz": "Holz", "platte": "Platte", "schraube": "Schraube", "mutter": "Mutter",
    "scheibe": "Scheibe", "kamera": "Kamera", "objektiv": "Objektiv",
    "kamerazubehoer": "Kamerazubehör", "zukaufteil": "Zukaufteil",
}

# Zusätzliche Suchwörter je Art (klein, ohne Umlaute)
ART_SYNONYME = {
    "rohr": "rundrohr gewinderohr siederohr",
    "vierkantrohr": "quadratrohr hohlprofil vierkant rohr",
    "rechteckrohr": "rechteck hohlprofil rohr",
    "flach": "flachstahl flacheisen flachmaterial flachprofil",
    "rund": "rundstahl rundmaterial welle rundeisen",
    "vierkant": "vierkantstahl vierkantmaterial",
    "winkel": "winkelstahl l-profil lprofil winkelprofil",
    "u_profil": "u-profil uprofil upn u-stahl",
    "nutprofil": "aluprofil alu-profil systemprofil item konstruktionsprofil profil",
    "holz": "kantholz kvh latte brett balken bohle leiste",
    "platte": "blech tafel plattenware zuschnitt",
    "schraube": "schrauben",
    "mutter": "muttern",
    "scheibe": "scheiben unterlegscheibe",
    "kamera": "kameras camera cine filmkamera body gehaeuse sensor",
    "objektiv": "objektive linse lens optik festbrennweite zoom cine-objektiv",
    "kamerazubehoer": "zubehoer rig kaefig cage baseplate rods lws stange rosette akku v-mount platte",
}

REQUIRED_MASSE: dict[str, tuple[str, ...]] = {
    "rohr": ("d", "s"), "vierkantrohr": ("a", "s"), "rechteckrohr": ("b", "h", "s"), "flach": ("b", "s"),
    "rund": ("d",), "vierkant": ("a",), "winkel": ("a", "b", "s"), "u_profil": ("h", "b", "s", "t"),
    "nutprofil": ("raster", "nut"), "holz": ("b", "h"), "platte": ("s",),
    "schraube": ("typ", "norm", "groesse"), "mutter": ("typ", "norm", "groesse"), "scheibe": ("typ", "norm", "groesse"),
    "kamera": (), "objektiv": (), "kamerazubehoer": (),  # Kameras und Objektive haben eigene Felder statt masse (optik.py)
}
OPTIONAL_MASSE: dict[str, tuple[str, ...]] = {
    "vierkantrohr": ("r",), "rechteckrohr": ("r",), "winkel": ("r",), "nutprofil": ("variante", "a", "b"),
}
TEXT_MASSE = frozenset({"typ", "norm", "groesse", "variante"})
PREIS_KEYS = ("je_m", "je_m2", "je_stueck")
FREI = "frei"
VORGESCHLAGEN = "vorgeschlagen"
STATUS = (FREI, VORGESCHLAGEN)
WARTET = "wartet auf Kevins Freigabe im Lagerkatalog"

DEFAULT_OWN_DIR = Path.home() / "Library" / "Application Support" / "de.upvis.kevcad" / "katalog"
OWN_FILE = "eigene.json"
PROJECT_FILE = "katalog.json"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class CatalogError(ValueError):
    """Eintrag ungültig oder Datei nicht schreibbar (Meldung für Agent und App)."""


# ---------------------------------------------------------------------------------------------------------------------
# Pfade


def builtin_dir() -> Path:
    env = os.environ.get("KEVCAD_CATALOG_BUILTIN_DIR")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[1] / "kevcad" / "katalog"


def own_dir(socket_path: str | None = None) -> Path:
    """Ordner des eigenen Katalogs: KEVCAD_CATALOG_DIR, sonst neben dem App-Socket einer Kev-CAD-Variante, sonst
    ~/Library/Application Support/de.upvis.kevcad/katalog."""
    env = os.environ.get("KEVCAD_CATALOG_DIR")
    if env:
        return Path(env).expanduser()
    if socket_path:
        parent = Path(socket_path).expanduser().resolve().parent
        if parent.name.startswith("de.upvis.kevcad"):
            return parent / "katalog"
    return DEFAULT_OWN_DIR


# ---------------------------------------------------------------------------------------------------------------------
# Zahlen und Texte


def number(value: Any) -> float | None:
    """Zahl aus int/float oder Text mit Komma oder Punkt; sonst None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        text = value.strip().replace(",", ".").replace(" ", "")
        try:
            x = float(text)
        except ValueError:
            return None
        return x if math.isfinite(x) else None
    return None


def dim_text(x: float) -> str:
    """Maß ohne überflüssige Nullen: 42.4 → "42.4", 2.0 → "2"."""
    text = f"{x:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def fold(text: str) -> str:
    """Für die Suche: klein, Umlaute ausgeschrieben, ×/* → x, Komma in Zahlen → Punkt, Ø entfernt."""
    t = str(text).lower().strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("×", "x"), ("*", "x"), ("ø", ""), ("⌀", "")):
        t = t.replace(a, b)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    t = re.sub(r"(\d)\s*x\s*(?=\d)", r"\1x", t)
    return t


def month_now() -> str:
    return time.strftime("%Y-%m")


# ---------------------------------------------------------------------------------------------------------------------
# Prüfen


def _check_id(entry: dict[str, Any], what: str) -> list[str]:
    eid = entry.get("id")
    if not isinstance(eid, str) or not eid.strip():
        return [f"{what}: Feld id fehlt (eindeutig, Kleinbuchstaben und Bindestriche, z. B. \"rohr-edelstahl-33.7x2\")"]
    if not _ID_RE.match(eid):
        tip = re.sub(r"[^a-z0-9._-]+", "-", fold(eid)).strip("-.")
        return [f"{what} {eid!r}: id nur aus Kleinbuchstaben, Ziffern, Bindestrichen und Punkten"
                + (f" (Vorschlag: {tip!r})" if tip else "")]
    return []


def status_of(entry: dict[str, Any] | None) -> str:
    """Freigabe eines Eintrags: "frei" (Standard, auch ohne Feld) oder "vorgeschlagen"."""
    return str((entry or {}).get("status") or FREI)


def is_free(entry: dict[str, Any] | None) -> bool:
    return entry is not None and status_of(entry) == FREI


def _check_status(entry: dict[str, Any], who: str) -> list[str]:
    st = entry.get("status")
    if st is not None and st not in STATUS:
        return [f"{who}: status {st!r} unbekannt (frei oder vorgeschlagen)"]
    return []


def validate_material(entry: Any) -> list[str]:
    """Fehler eines Materials (leer = gültig)."""
    if not isinstance(entry, dict):
        return ["Material muss ein JSON-Objekt sein"]
    errors = _check_id(entry, "Material")
    who = f"Material {entry.get('id')!r}" if isinstance(entry.get("id"), str) else "Material"
    for key in ("name", "gruppe"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            errors.append(f"{who}: Feld {key} fehlt (Text)")
    d = number(entry.get("dichte"))
    if d is None:
        errors.append(f"{who}: dichte fehlt (g/cm³, z. B. 7.85 für Stahl)")
    elif not 0.01 <= d <= 25:
        errors.append(f"{who}: dichte {d:g} g/cm³ ist unplausibel (erwartet 0,01 bis 25, Stahl 7,85, Holz um 0,5)")
    farbe = entry.get("farbe")
    if not isinstance(farbe, str) or not _HEX_RE.match(farbe.strip()):
        errors.append(f"{who}: farbe fehlt oder ist kein sRGB-Hex wie \"#8A9099\"")
    for key in ("metallisch", "rauheit"):
        if key in entry and entry[key] is not None:
            v = number(entry[key])
            if v is None or not 0 <= v <= 1:
                errors.append(f"{who}: {key} muss zwischen 0 und 1 liegen")
    if entry.get("preis_je_kg") is not None:
        v = number(entry.get("preis_je_kg"))
        if v is None or v < 0:
            errors.append(f"{who}: preis_je_kg muss eine Zahl ≥ 0 sein (€ netto je kg)")
    if "aliase" in entry and entry["aliase"] is not None:
        al = entry["aliase"]
        if not isinstance(al, list) or not all(isinstance(a, str) and a.strip() for a in al):
            errors.append(f"{who}: aliase muss eine Liste von Texten sein")
    if entry.get("preis_stand") is not None and not _MONTH_RE.match(str(entry["preis_stand"])):
        errors.append(f"{who}: preis_stand als Monat \"JJJJ-MM\" angeben")
    if entry.get("druckbar") is not None and not isinstance(entry.get("druckbar"), bool):
        errors.append(f"{who}: druckbar muss true oder false sein")
    if entry.get("spule_g") is not None:  # Strang „Bestand Stufe 2“: Kaufspule für die Einkaufsliste
        v = number(entry.get("spule_g"))
        if v is None or not 0 < v <= 20000:
            errors.append(f"{who}: spule_g muss eine Zahl zwischen 0 und 20000 sein (g Filament je Kaufspule)")
    if entry.get("mechanik") is not None:
        errors += validate_mechanik(entry["mechanik"], who)
    if entry.get("render") is not None:  # Phase 7: Darstellung im Rendering (render/materialien.py)
        from kevcad_kernel.render.materialien import validate_render

        errors += validate_render(entry["render"], who)
    errors += _check_status(entry, who)
    return errors


# Statik (PLAN-STATIK.md, T6): Werkstoffkennwerte je Material in ``mechanik`` (KATALOG.md, Abschnitt „Mechanik“)
MECHANIK_ZAHLEN = ("e_modul", "schubmodul", "streckgrenze", "zugfestigkeit", "biegefestigkeit", "druckfestigkeit",
                   "e_modul_z", "zugfestigkeit_z")


def validate_mechanik(mech: Any, who: str = "Material") -> list[str]:
    """Fehler im Feld ``mechanik`` eines Materials (leer = gültig). Spannungen und Moduln in N/mm² (MPa)."""
    if not isinstance(mech, dict):
        return [f"{who}: mechanik muss ein Objekt sein"]
    errors: list[str] = []
    for key in MECHANIK_ZAHLEN:
        if key in mech and mech[key] is not None:
            v = number(mech[key])
            if v is None or v <= 0:
                errors.append(f"{who}: mechanik.{key} muss eine Zahl > 0 sein (N/mm²)")
    if number(mech.get("e_modul")) is None:
        errors.append(f"{who}: mechanik.e_modul fehlt (N/mm², z. B. 210000 für Stahl)")
    if not any(number(mech.get(k)) for k in ("streckgrenze", "zugfestigkeit", "biegefestigkeit")):
        errors.append(f"{who}: mechanik braucht streckgrenze, zugfestigkeit oder biegefestigkeit (N/mm²)")
    nu = mech.get("querkontraktion")
    if nu is not None and (number(nu) is None or not 0 <= float(number(nu)) < 0.5):
        errors.append(f"{who}: mechanik.querkontraktion muss zwischen 0 und 0,5 liegen")
    q = mech.get("quer_zur_schicht")
    if q is not None and (number(q) is None or not 0 < float(number(q)) <= 1):
        errors.append(f"{who}: mechanik.quer_zur_schicht muss zwischen 0 und 1 liegen (Anteil der Festigkeit)")
    if not isinstance(mech.get("quelle"), str) or not mech["quelle"].strip():
        errors.append(f"{who}: mechanik.quelle fehlt (Norm oder Datenblatt; Schätzungen in geschaetzt nennen)")
    if mech.get("stand") is not None and not _MONTH_RE.match(str(mech["stand"])):
        errors.append(f"{who}: mechanik.stand als Monat \"JJJJ-MM\" angeben")
    g = mech.get("geschaetzt")
    if g is not None and not isinstance(g, bool) and not (isinstance(g, list) and all(isinstance(x, str) for x in g)):
        errors.append(f"{who}: mechanik.geschaetzt ist true oder eine Liste der geschätzten Felder")
    return errors


def validate_reibwert(entry: Any) -> list[str]:
    """Fehler eines Reibwerts (Paarung zweier Materialien oder Gruppen, leer = gültig)."""
    if not isinstance(entry, dict):
        return ["Reibwert muss ein JSON-Objekt sein"]
    who = f"Reibwert {entry.get('a')!r}/{entry.get('b')!r}"
    errors = []
    for key in ("a", "b"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            errors.append(f"{who}: Feld {key} fehlt (Material-id oder Gruppe)")
    v = number(entry.get("haft"))
    if v is None or not 0 < v <= 3:
        errors.append(f"{who}: haft muss eine Zahl zwischen 0 und 3 sein (Haftreibungszahl)")
    if entry.get("gleit") is not None and (number(entry.get("gleit")) is None or not 0 < float(entry["gleit"]) <= 3):
        errors.append(f"{who}: gleit muss eine Zahl zwischen 0 und 3 sein")
    if not isinstance(entry.get("quelle"), str) or not entry["quelle"].strip():
        errors.append(f"{who}: quelle fehlt")
    return errors


def _reib_key(a: str, b: str) -> tuple[str, str]:
    x, y = fold(a), fold(b)
    return (x, y) if x <= y else (y, x)


# Statik (Strang „Bestand Stufe 2“): Auszugkraft von Gewindeeinsätzen in Druckteilen (KATALOG.md, „Gewindeeinsätze“)
_GROESSE_RE = re.compile(r"^\s*[mM]\s*(\d+(?:[.,]\d+)?)")


def einsatz_groesse(text: Any) -> str | None:
    """„M3“ aus „M3“, „m3“, „M3-0.5“ oder 3.0; None, wenn nichts passt."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        v = float(text)
        return f"M{v:g}" if v > 0 else None
    m = _GROESSE_RE.match(str(text or ""))
    if not m:
        return None
    return f"M{float(m.group(1).replace(',', '.')):g}"


def validate_einsatz_auszug(entry: Any) -> list[str]:
    """Fehler einer Auszugkraft (Gewindeeinsatz je Größe und Druckmaterial, leer = gültig)."""
    if not isinstance(entry, dict):
        return ["Auszugkraft muss ein JSON-Objekt sein"]
    who = f"Auszugkraft {entry.get('groesse')!r}/{entry.get('material')!r}"
    errors = []
    if einsatz_groesse(entry.get("groesse")) is None:
        errors.append(f"{who}: groesse fehlt (z. B. \"M3\")")
    if not isinstance(entry.get("material"), str) or not entry["material"].strip():
        errors.append(f"{who}: material fehlt (Material-id, z. B. \"pla\")")
    v = number(entry.get("kraft_n"))
    if v is None or not 0 < v <= 100000:
        errors.append(f"{who}: kraft_n muss eine Zahl über 0 sein (N, axial)")
    if not isinstance(entry.get("quelle"), str) or not entry["quelle"].strip():
        errors.append(f"{who}: quelle fehlt (Versuch oder Datenblatt mit Datum)")
    if entry.get("stand") is not None and not _MONTH_RE.match(str(entry["stand"])):
        errors.append(f"{who}: stand als Monat \"JJJJ-MM\" angeben")
    return errors


def _num_field(masse: dict[str, Any], key: str) -> float | None:
    return number(masse.get(key))


def validate_item(entry: Any, material_ids: set[str] | None = None, deep: bool = True) -> list[str]:
    """Fehler eines Lagerteils (leer = gültig). ``material_ids``: bekannte Materialien (None = nicht prüfen);
    ``deep``: Schrauben, Muttern und Scheiben gegen bd_warehouse prüfen (lädt build123d)."""
    if not isinstance(entry, dict):
        return ["Lagerteil muss ein JSON-Objekt sein"]
    if entry.get("art") in ZUKAUF_ARTEN:
        from kevcad_kernel.zukauf.eintrag import validate_zukauf

        return validate_zukauf(entry, material_ids)
    errors = _check_id(entry, "Lagerteil")
    who = f"Lagerteil {entry.get('id')!r}" if isinstance(entry.get("id"), str) else "Lagerteil"
    art = entry.get("art")
    if art not in ARTEN:
        close = difflib.get_close_matches(str(art), ARTEN, n=2, cutoff=0.5)
        errors.append(f"{who}: art {art!r} unbekannt (erlaubt: {', '.join(ARTEN)})"
                      + (f"; meinten Sie {' oder '.join(repr(c) for c in close)}?" if close else ""))
    if not isinstance(entry.get("name"), str) or not entry["name"].strip():
        errors.append(f"{who}: Feld name fehlt (Anzeige mit deutschem Komma und „×“, z. B. \"Rohr 42,4 × 2,0\")")
    if entry.get("norm") is not None and not isinstance(entry.get("norm"), str):
        errors.append(f"{who}: norm muss Text sein")
    optik = art in OPTIK_ARTEN  # Kameras und Objektive: eigene Felder, Material und masse sind freiwillig
    mat = entry.get("material")
    if optik and mat is None:
        pass
    elif not isinstance(mat, str) or not mat.strip():
        errors.append(f"{who}: Feld material fehlt (id eines Materials, z. B. \"stahl-s235\")")
    elif material_ids is not None and mat not in material_ids:
        close = difflib.get_close_matches(mat, sorted(material_ids), n=3, cutoff=0.5)
        errors.append(f"{who}: Material {mat!r} gibt es im Katalog nicht"
                      + (f"; meinten Sie {', '.join(repr(c) for c in close)}?" if close
                         else " (erst mit material_define anlegen)"))
    masse = entry.get("masse")
    if optik:
        errors.extend(validate_optik(entry))
    elif not isinstance(masse, dict):
        errors.append(f"{who}: masse fehlt (Objekt mit den Maßen in mm, z. B. {{\"d\": 42.4, \"s\": 2.0}})")
    elif art in ARTEN:
        errors.extend(_validate_masse(who, art, masse, deep))
    for key in ("kg_je_m", "stangenlaenge"):
        if entry.get(key) is not None:
            v = number(entry.get(key))
            if v is None or v <= 0:
                errors.append(f"{who}: {key} muss eine Zahl > 0 sein")
    if entry.get("stangenlaenge") is not None and art in STANGENWARE:
        v = number(entry.get("stangenlaenge"))
        if v is not None and v < 100:
            errors.append(f"{who}: stangenlaenge {v:g} mm ist unplausibel (Angabe in mm, z. B. 6000)")
    if entry.get("platte") is not None:
        p = entry.get("platte")
        if not (isinstance(p, list) and len(p) == 2 and all((number(v) or 0) > 0 for v in p)):
            errors.append(f"{who}: platte als Standardformat [breite, hoehe] in mm angeben, z. B. [2500, 1250]")
    preis = entry.get("preis")
    if preis is not None:
        if not isinstance(preis, dict):
            errors.append(f"{who}: preis muss ein Objekt sein, z. B. {{\"je_m\": 4.8, \"quelle\": \"Richtwert\", "
                          "\"stand\": \"2026-10\"}")
        else:
            found = [k for k in PREIS_KEYS if preis.get(k) is not None]
            if not found:
                errors.append(f"{who}: preis braucht je_m, je_m2 oder je_stueck")
            for k in found:
                v = number(preis.get(k))
                if v is None or v < 0:
                    errors.append(f"{who}: preis.{k} muss eine Zahl ≥ 0 sein (€ netto)")
            if preis.get("stand") is not None and not _MONTH_RE.match(str(preis["stand"])):
                errors.append(f"{who}: preis.stand als Monat \"JJJJ-MM\" angeben")
    if entry.get("tags") is not None:
        tags = entry["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            errors.append(f"{who}: tags muss eine Liste von Texten sein")
    bq = entry.get("bezugsquelle")  # BESTAND.md: Link in der Einkaufsliste
    if bq is not None and not (isinstance(bq, dict) and isinstance(bq.get("url"), str)
                               and re.match(r"^https?://\S+$", bq["url"].strip())
                               and (bq.get("name") is None or isinstance(bq.get("name"), str))):
        errors.append(f"{who}: bezugsquelle als {{\"url\": \"https://…\", \"name\": \"Händler\"}} angeben")
    errors += _check_status(entry, who)
    return errors


def _validate_masse(who: str, art: str, masse: dict[str, Any], deep: bool = True) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_MASSE[art]:
        if key in TEXT_MASSE:
            if not isinstance(masse.get(key), str) or not masse[key].strip():
                errors.append(f"{who}: masse.{key} fehlt (Text)")
        elif _num_field(masse, key) is None:
            errors.append(f"{who}: masse.{key} fehlt (Zahl in mm)")
    for key in OPTIONAL_MASSE.get(art, ()):
        if key in masse and masse[key] is not None:
            if key in TEXT_MASSE:
                if not isinstance(masse[key], str):
                    errors.append(f"{who}: masse.{key} muss Text sein")
            elif _num_field(masse, key) is None:
                errors.append(f"{who}: masse.{key} muss eine Zahl sein")
    known = set(REQUIRED_MASSE[art]) | set(OPTIONAL_MASSE.get(art, ()))
    extra = [k for k in masse if k not in known]
    if extra:
        errors.append(f"{who}: masse kennt für art {art!r} nur {', '.join(sorted(known))} (nicht {', '.join(extra)})")
    if errors:
        return errors
    m = {k: _num_field(masse, k) for k in known if k not in TEXT_MASSE and masse.get(k) is not None}
    for k, v in m.items():
        if v is not None and v <= 0:
            errors.append(f"{who}: masse.{k} muss größer als 0 sein")
    if errors:
        return errors
    if art == "rohr" and m["s"] * 2 >= m["d"]:
        errors.append(f"{who}: Wand s = {m['s']:g} ist zu dick für d = {m['d']:g} (s < d/2)")
    if art == "vierkantrohr":
        if m["s"] * 2 >= m["a"]:
            errors.append(f"{who}: Wand s = {m['s']:g} ist zu dick für a = {m['a']:g} (s < a/2)")
        if m.get("r") is not None and m["r"] * 2 >= m["a"]:
            errors.append(f"{who}: Außenradius r = {m['r']:g} ist zu groß (r < a/2)")
    if art == "rechteckrohr":
        if m["s"] * 2 >= min(m["b"], m["h"]):
            errors.append(f"{who}: Wand s = {m['s']:g} ist zu dick für {m['b']:g} × {m['h']:g}")
        if m.get("r") is not None and m["r"] * 2 >= min(m["b"], m["h"]):
            errors.append(f"{who}: Außenradius r = {m['r']:g} ist zu groß (r < kleinere Seite/2)")
    if art == "winkel":
        if m["s"] >= min(m["a"], m["b"]):
            errors.append(f"{who}: Schenkeldicke s = {m['s']:g} muss kleiner als beide Schenkel sein")
        if m.get("r") is not None and m["r"] + m["s"] >= min(m["a"], m["b"]):
            errors.append(f"{who}: Innenradius r = {m['r']:g} ist zu groß für die Schenkel")
    if art == "u_profil":
        if m["s"] >= m["b"]:
            errors.append(f"{who}: Stegdicke s = {m['s']:g} muss kleiner als die Breite b = {m['b']:g} sein")
        if m["t"] * 2 >= m["h"]:
            errors.append(f"{who}: Flanschdicke t = {m['t']:g} ist zu groß für h = {m['h']:g} (t < h/2)")
    if art == "nutprofil":
        raster, nut = m["raster"], m["nut"]
        if nut >= raster * 0.5:
            errors.append(f"{who}: Nut {nut:g} ist zu breit für Raster {raster:g} (Nut < Raster/2)")
        for key in ("a", "b"):
            if m.get(key) is not None:
                n = m[key] / raster
                if abs(n - round(n)) > 1e-6 or round(n) < 1:
                    errors.append(f"{who}: masse.{key} = {m[key]:g} ist kein Vielfaches des Rasters {raster:g}")
        var = masse.get("variante")
        if var is not None and str(var).lower() not in ("leicht", "schwer"):
            errors.append(f"{who}: variante {var!r} unbekannt (leicht oder schwer)")
    if art in KLEINTEILE and deep:
        errors.extend(_validate_fastener(who, art, masse))
    return errors


def _validate_fastener(who: str, art: str, masse: dict[str, Any]) -> list[str]:
    """Typ, Norm und Größe gegen bd_warehouse prüfen (lädt bd_warehouse erst hier)."""
    try:
        from kevcad_kernel.profiles import fastener_class
    except Exception as exc:  # noqa: BLE001
        return [f"{who}: bd_warehouse nicht verfügbar ({exc})"]
    try:
        cls = fastener_class(art, str(masse["typ"]))
    except ValueError as exc:
        return [f"{who}: {exc}"]
    norm = str(masse["norm"])
    try:
        norms = sorted(cls.types())
    except Exception:  # noqa: BLE001
        norms = []
    if norms and norm not in norms:
        return [f"{who}: Norm {norm!r} gibt es für {cls.__name__} nicht (vorhanden: {', '.join(norms)})"]
    try:
        sizes = list(cls.sizes(norm))
    except Exception:  # noqa: BLE001
        sizes = []
    groesse = str(masse["groesse"])
    if sizes and groesse not in sizes:
        close = [s for s in sizes if s.split("-")[0].lower() == groesse.split("-")[0].lower()]
        tip = f" Meinten Sie {close[0]!r}?" if close else f" (z. B. {', '.join(sizes[:6])})"
        return [f"{who}: Größe {groesse!r} gibt es für {cls.__name__} {norm} nicht.{tip}"]
    return []


def item_notes(entry: dict[str, Any]) -> list[str]:
    """Hinweise, die das Speichern nicht verhindern (Preisart passt nicht zur Art, fehlende Quelle)."""
    notes: list[str] = []
    art = entry.get("art")
    preis = entry.get("preis") if isinstance(entry.get("preis"), dict) else None
    if preis:
        expected = "je_m" if art in STANGENWARE else ("je_m2" if art == "platte" else "je_stueck")
        if preis.get(expected) is None:
            notes.append(f"Preis: für art {art!r} wird preis.{expected} benutzt; angegeben ist "
                         f"{', '.join(k for k in PREIS_KEYS if preis.get(k) is not None)}")
    return notes


# ---------------------------------------------------------------------------------------------------------------------
# Suche


def dims(entry: dict[str, Any]) -> list[list[float]]:
    """Maßfolgen, die eine Suche wie "40x40x3" treffen kann."""
    art = entry.get("art")
    m = {k: number(v) for k, v in (entry.get("masse") or {}).items() if k not in TEXT_MASSE}
    g = lambda *keys: [m[k] for k in keys]  # noqa: E731
    try:
        if art == "rohr":
            return [g("d", "s"), g("d")]
        if art == "vierkantrohr":
            return [[m["a"], m["a"], m["s"]], [m["a"], m["a"]], g("a", "s"), g("a")]
        if art == "rechteckrohr":
            return [g("b", "h", "s"), g("h", "b", "s"), g("b", "h"), g("h", "b")]
        if art == "flach":
            return [g("b", "s"), g("s", "b")]
        if art == "rund":
            return [g("d")]
        if art == "vierkant":
            return [g("a"), [m["a"], m["a"]]]
        if art == "winkel":
            out = [g("a", "b", "s"), g("b", "a", "s"), g("a", "b")]
            if m["a"] == m["b"]:
                out.append(g("a", "s"))
            return out
        if art == "u_profil":
            return [g("h"), g("h", "b"), g("h", "b", "s")]
        if art == "nutprofil":
            r = m["raster"]
            a, b = m.get("a") or r, m.get("b") or r
            return [[a, b], [b, a], [r]] if a != b else [[a, b], [a]]
        if art == "holz":
            return [g("b", "h"), g("h", "b")]
        if art == "platte":
            out = [g("s")]
            p = entry.get("platte")
            if isinstance(p, list) and len(p) == 2:
                out.append([number(p[0]), number(p[1]), m["s"]])
            return out
    except (KeyError, TypeError):
        return []
    return []


def _haystack(entry: dict[str, Any], material: dict[str, Any] | None) -> str:
    bits = [entry.get("id", ""), entry.get("name", ""), entry.get("norm") or "", entry.get("art", ""),
            ART_NAMEN.get(entry.get("art", ""), ""), ART_SYNONYME.get(entry.get("art", ""), ""),
            " ".join(entry.get("tags") or []), str(entry.get("material", ""))]
    bits += [str(entry.get(k) or "") for k in ("hersteller", "mpn", "gtin", "shop_nr")]  # Zukaufteile
    if entry.get("art") in OPTIK_ARTEN:
        bits += [str(entry.get(k) or "") for k in ("hersteller", "modell", "kurzname", "bajonett", "typ")]
    masse = entry.get("masse") or {}
    for key in TEXT_MASSE:
        if masse.get(key):
            bits.append(str(masse[key]))
            if key == "groesse":
                bits.append(str(masse[key]).split("-")[0])
    if material:
        bits += [material.get("name", ""), material.get("gruppe", ""), " ".join(material.get("aliase") or [])]
    text = fold(" ".join(str(b) for b in bits))
    return text + " " + text.replace(" ", "")


_DIM_TOKEN = re.compile(r"^\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)+$")
_NUM_TOKEN = re.compile(r"^\d+(?:\.\d+)?$")
_M_TOKEN = re.compile(r"^(m\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?$")


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 1e-6


def match_score(entry: dict[str, Any], material: dict[str, Any] | None, tokens: list[str]) -> float:
    """0 = kein Treffer; sonst höher = besser. Alle Wörter müssen passen."""
    if not tokens:
        return 1.0
    hay = _haystack(entry, material)
    seqs = dims(entry)
    eid = fold(entry.get("id", ""))
    score = 0.0
    for tok in tokens:
        if tok in ("mm", "x", "×"):
            continue
        hit = 0.0
        if tok == eid:
            hit = 100.0
        elif _DIM_TOKEN.match(tok):
            nums = [float(v) for v in tok.split("x")]
            if any(len(s) == len(nums) and all(_close(a, b) for a, b in zip(s, nums)) for s in seqs):
                hit = 4.0
            elif tok in hay:
                hit = 1.0
        elif _NUM_TOKEN.match(tok[:-2] if tok.endswith("mm") else tok):
            t = tok[:-2] if tok.endswith("mm") else tok
            if any(_close(v, float(t)) for s in seqs for v in s):
                hit = 2.0
            elif re.search(rf"(?<![\d.]){re.escape(t)}(?![\d])", hay):
                hit = 1.0
        else:
            mt = _M_TOKEN.match(tok)
            if mt and entry.get("art") in KLEINTEILE:
                g = fold(str((entry.get("masse") or {}).get("groesse", ""))).split("-")[0]
                if g == mt.group(1):
                    hit = 3.0
            elif tok in hay:
                hit = 2.0 if re.search(rf"\b{re.escape(tok)}", hay) else 1.0
        if hit <= 0:
            return 0.0
        score += hit
    return score


def material_score(mat: dict[str, Any], tokens: list[str]) -> float:
    if not tokens:
        return 1.0
    hay = fold(" ".join([mat.get("id", ""), mat.get("name", ""), mat.get("gruppe", ""),
                         " ".join(mat.get("aliase") or [])]))
    score = 0.0
    for tok in tokens:
        if tok not in hay:
            return 0.0
        score += 2.0 if re.search(rf"\b{re.escape(tok)}", hay) else 1.0
    return score


def tokenize(query: str | None) -> list[str]:
    return [t for t in re.split(r"[\s;]+", fold(query or "")) if t]


def sort_key(entry: dict[str, Any]) -> tuple:
    art = entry.get("art")
    order = ARTEN.index(art) if art in ARTEN else len(ARTEN)
    seq = dims(entry)
    first = tuple(v or 0 for v in seq[0]) if seq else ()
    return order, first, str(entry.get("name", "")).lower()


# ---------------------------------------------------------------------------------------------------------------------
# Katalog


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"{path.name}: kein gültiges JSON (Zeile {exc.lineno}, Spalte {exc.colno}: {exc.msg})"
    except OSError as exc:
        return None, f"{path.name}: nicht lesbar ({exc})"
    if not isinstance(data, dict):
        return None, f"{path.name}: muss ein Objekt {{\"version\": 1, \"materialien\": [...], \"teile\": [...]}} sein"
    return data, None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class Catalog:
    """Zusammengeführter Katalog aus den drei Ebenen. Alle Rückgaben sind Kopien mit zusätzlichem Feld ``ebene``."""

    def __init__(self, builtin: str | Path | None = None, own: str | Path | None = None,
                 project: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._builtin = Path(builtin) if builtin is not None else builtin_dir()
        self._own = Path(own) if own is not None else own_dir()
        self._project = Path(project) if project is not None else None
        self._sig: tuple | None = None
        self._materials: dict[str, dict[str, Any]] = {}
        self._items: dict[str, dict[str, Any]] = {}
        self._source: dict[tuple[str, str], tuple[str, Path]] = {}  # (kind, id) → (ebene, Datei)
        self._aliases: dict[str, str] = {}
        self._reibwerte: dict[tuple[str, str], dict[str, Any]] = {}  # Statik: Paarung → Reibwert (KATALOG.md)
        self._reibgruppen: dict[str, str] = {}
        self._einsatz: dict[tuple[str, str], dict[str, Any]] = {}  # Statik: (Größe, Material) → Auszugkraft
        self.warnings: list[str] = []
        self.loaded_at = 0.0

    # -- Konfiguration -------------------------------------------------------------------------------------------------

    @property
    def dirs(self) -> dict[str, str | None]:
        return {"builtin": str(self._builtin), "own": str(self._own),
                "project": str(self._project) if self._project else None}

    def configure(self, builtin: str | Path | None = None, own: str | Path | None = None,
                  project: str | Path | None = "unchanged") -> None:
        with self._lock:
            if builtin is not None:
                self._builtin = Path(builtin)
            if own is not None:
                self._own = Path(own)
            if project != "unchanged":
                self._project = Path(project) if project else None
            # Die Signatur enthält die Ordner: der nächste Zugriff lädt bei Bedarf neu

    def set_project(self, project: str | Path | None) -> None:
        self.configure(project=project)

    @property
    def own_file(self) -> Path:
        return self._own / OWN_FILE

    @property
    def project_file(self) -> Path | None:
        return self._project / PROJECT_FILE if self._project else None

    # -- Laden ---------------------------------------------------------------------------------------------------------

    def _files(self) -> list[tuple[str, Path]]:
        out: list[tuple[str, Path]] = []
        for ebene, d in (("mitgeliefert", self._builtin), ("eigen", self._own)):
            try:
                files = sorted(p for p in d.glob("*.json") if p.is_file() and not p.name.startswith("."))
            except OSError:
                files = []
            out += [(ebene, p) for p in files]
        pf = self.project_file
        if pf is not None and pf.is_file():
            out.append(("projekt", pf))
        return out

    def _signature(self, files: list[tuple[str, Path]]) -> tuple:
        sig = []
        for ebene, p in files:
            try:
                st = p.stat()
                sig.append((ebene, str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((ebene, str(p), 0, 0))
        return (str(self._builtin), str(self._own), str(self._project), tuple(sig))

    def refresh(self, force: bool = False) -> bool:
        """Neu laden, wenn sich Dateien geändert haben. True, wenn neu geladen wurde."""
        with self._lock:
            files = self._files()
            sig = self._signature(files)
            if not force and sig == self._sig:
                return False
            self._load(files)
            self._sig = sig
            return True

    def _load(self, files: list[tuple[str, Path]]) -> None:
        materials: dict[str, dict[str, Any]] = {}
        items: dict[str, dict[str, Any]] = {}
        source: dict[tuple[str, str], tuple[str, Path]] = {}
        warnings: list[str] = []
        reib: dict[tuple[str, str], dict[str, Any]] = {}
        reibgruppen: dict[str, str] = {}
        einsatz: dict[tuple[str, str], dict[str, Any]] = {}
        seen_in_level: dict[tuple[str, str, str], Path] = {}
        for ebene, path in files:
            data, err = _read_json(path)
            label = f"{ebene}/{path.name}"
            if err:
                warnings.append(f"Katalog {ebene}: {err}")
                continue
            assert data is not None
            # Statik: Reibwerte je Paarung und Zuordnung von Gruppen (spätere Ebene ersetzt dieselbe Paarung)
            for row in data.get("reibwerte") or []:
                errors = validate_reibwert(row)
                if errors:
                    warnings.append(f"{label}: " + "; ".join(errors) + " – übersprungen")
                    continue
                reib[_reib_key(row["a"], row["b"])] = {**copy.deepcopy(row), "ebene": ebene}
            gruppen = data.get("reibgruppen") or {}
            if isinstance(gruppen, dict):
                reibgruppen.update({fold(str(k)): str(v) for k, v in gruppen.items() if isinstance(v, str)})
            # Auszugkraft von Gewindeeinsätzen je Größe und Druckmaterial (spätere Ebene ersetzt dieselbe Paarung)
            for row in data.get("einsatz_auszug") or []:
                errors = validate_einsatz_auszug(row)
                if errors:
                    warnings.append(f"{label}: " + "; ".join(errors) + " – übersprungen")
                    continue
                key = (str(einsatz_groesse(row["groesse"])), fold(row["material"]))
                einsatz[key] = {**copy.deepcopy(row), "groesse": key[0], "ebene": ebene}
            for kind, key, target, check in (("material", "materialien", materials, validate_material),
                                              ("teil", "teile", items, None)):
                rows = data.get(key) or []
                if not isinstance(rows, list):
                    warnings.append(f"{label}: {key} muss eine Liste sein")
                    continue
                for row in rows:
                    if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                        warnings.append(f"{label}: Eintrag ohne id in {key} übersprungen")
                        continue
                    eid = row["id"]
                    dup = seen_in_level.get((ebene, kind, eid))
                    if dup is not None and dup != path:
                        warnings.append(f"{label}: id {eid!r} steht auch in {dup.name} (gleiche Ebene); "
                                        f"{path.name} gilt")
                    seen_in_level[(ebene, kind, eid)] = path
                    if row.get("entfernt") is True:
                        target.pop(eid, None)
                        source.pop((kind, eid), None)
                        continue
                    errors = check(row) if check is not None else validate_item(row, None, deep=False)
                    if errors:
                        warnings.append(f"{label}: " + "; ".join(errors) + " – übersprungen")
                        continue
                    entry = copy.deepcopy(row)
                    entry["ebene"] = ebene
                    entry.setdefault("status", FREI)
                    target[eid] = entry
                    source[(kind, eid)] = (ebene, path)
        mids = set(materials)
        for eid, it in items.items():
            if it.get("art") in OPTIK_ARTEN and not it.get("material"):
                continue
            optional = it.get("art") in ZUKAUF_ARTEN and it.get("material") is None  # Zukaufteile ohne Material
            if it.get("material") not in mids and not optional:
                warnings.append(f"Lagerteil {eid!r}: Material {it.get('material')!r} fehlt im Katalog")
        aliases: dict[str, str] = {}
        for mid, mat in materials.items():
            for name in [mat.get("name", "")] + list(mat.get("aliase") or []):
                key = _mat_key(name)
                if key and key not in materials:
                    if key in aliases and aliases[key] != mid:
                        warnings.append(f"Material-Alias {name!r} gehört zu {aliases[key]!r} und {mid!r}; "
                                        f"{mid!r} gilt")
                    aliases[key] = mid
        self._materials, self._items, self._source, self._aliases = materials, items, source, aliases
        self._reibwerte, self._reibgruppen = reib, reibgruppen
        self._einsatz = einsatz
        self.warnings = warnings
        self.loaded_at = time.time()

    # -- Lesen ---------------------------------------------------------------------------------------------------------

    def materials(self) -> list[dict[str, Any]]:
        with self._lock:
            self.refresh()
            return [copy.deepcopy(m) for m in sorted(self._materials.values(),
                                                     key=lambda m: (str(m.get("gruppe", "")), m["id"]))]

    def items(self, art: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self.refresh()
            rows = [it for it in self._items.values() if art is None or it.get("art") == art]
            return [copy.deepcopy(it) for it in sorted(rows, key=sort_key)]

    def material(self, mid: str) -> dict[str, Any] | None:
        with self._lock:
            self.refresh()
            m = self._materials.get(mid)
            return copy.deepcopy(m) if m is not None else None

    def item(self, iid: str) -> dict[str, Any] | None:
        with self._lock:
            self.refresh()
            it = self._items.get(iid)
            return copy.deepcopy(it) if it is not None else None

    def item_ids(self) -> list[str]:
        with self._lock:
            self.refresh()
            return list(self._items)

    def material_ids(self) -> set[str]:
        with self._lock:
            self.refresh()
            return set(self._materials)

    def find_material(self, name: Any, include_proposed: bool = False) -> dict[str, Any] | None:
        """Material nach id, Alias oder Name (Groß-/Kleinschreibung, Leerzeichen und Unterstriche egal). Vorgeschlagene
        Materialien nur mit ``include_proposed``."""
        if not isinstance(name, str) or not name.strip():
            return None
        with self._lock:
            self.refresh()
            raw = name.strip()
            mid = raw if raw in self._materials else None
            if mid is None:
                key = _mat_key(raw)
                mid = key if key in self._materials else self._aliases.get(key)
            if mid is None:
                return None
            mat = self._materials[mid]
            if not include_proposed and not is_free(mat):
                return None
            return copy.deepcopy(mat)

    def printable_materials(self) -> list[dict[str, Any]]:
        """Freigegebene Materialien mit ``"druckbar": true``."""
        return [m for m in self.materials() if is_free(m) and m.get("druckbar") is True]

    # -- Statik (KATALOG.md, Abschnitt „Mechanik“) ----------------------------------------------------------------------

    def reibwerte(self) -> list[dict[str, Any]]:
        """Alle Reibwerte (Paarungen), sortiert."""
        with self._lock:
            self.refresh()
            return [copy.deepcopy(r) for _, r in sorted(self._reibwerte.items())]

    def reibwert(self, a: Any, b: Any) -> dict[str, Any] | None:
        """Reibwert der Paarung zweier Materialien (Eintrag, id oder Name). Gesucht wird id/id, id/Gruppe, Gruppe/id,
        Gruppe/Gruppe, jeweils auch mit der Reibgruppe (Edelstahl → Stahl, Holzwerkstoff → Holz). Mit ``paarung``
        (wie gefunden) oder None."""

        def kandidaten(x: Any) -> list[str]:
            m = x if isinstance(x, dict) else (self.find_material(x, include_proposed=True) if x else None)
            if m is None:
                return [str(x)] if isinstance(x, str) and x else []
            out = [m["id"]]
            g = str(m.get("gruppe") or "")
            if g:
                out.append(g)
                rg = self._reibgruppen.get(fold(g))
                if rg:
                    out.append(rg)
            return out

        with self._lock:
            self.refresh()
            for x in kandidaten(a):
                for y in kandidaten(b):
                    r = self._reibwerte.get(_reib_key(x, y))
                    if r is not None:
                        return {**copy.deepcopy(r), "paarung": [x, y]}
        return None

    def einsatz_auszuege(self) -> list[dict[str, Any]]:
        """Alle Auszugkräfte von Gewindeeinsätzen, sortiert nach Material und Größe."""
        with self._lock:
            self.refresh()
            return [copy.deepcopy(r) for _, r in sorted(self._einsatz.items(),
                                                        key=lambda kv: (kv[0][1], float(kv[0][0][1:])))]

    def einsatz_auszug(self, groesse: Any, material: Any) -> dict[str, Any] | None:
        """Auszugkraft eines Gewindeeinsatzes der Größe ``groesse`` („M3“, 3) im Druckmaterial ``material`` (Eintrag,
        id, Alias oder Name); None, wenn nichts belegt ist (dann ist der Einsatz nicht nachgewiesen)."""
        g = einsatz_groesse(groesse)
        if g is None or not material:
            return None
        m = material if isinstance(material, dict) else self.find_material(material, include_proposed=True)
        kandidaten = [m["id"]] if m else [str(material)]
        with self._lock:
            self.refresh()
            for mid in kandidaten:
                r = self._einsatz.get((g, fold(mid)))
                if r is not None:
                    return copy.deepcopy(r)
        return None

    def material_suggestions(self, name: str, n: int = 3) -> list[str]:
        with self._lock:
            self.refresh()
            names = list(self._materials) + list(self._aliases)
        return difflib.get_close_matches(_mat_key(name), names, n=n, cutoff=0.6)

    def source(self, kind: str, eid: str) -> tuple[str, Path] | None:
        with self._lock:
            self.refresh()
            return self._source.get((kind, eid))

    def search(self, query: str | None = "", art: str | None = None, limit: int | None = 30) -> tuple[list[dict], int]:
        """(Treffer, Gesamtzahl). Volltext über id, Name, Norm, Tags, Art und Material; Maße wie "40x40x3"."""
        tokens = tokenize(query)
        with self._lock:
            self.refresh()
            scored = []
            for it in self._items.values():
                if art and it.get("art") != art:
                    continue
                s = match_score(it, self._materials.get(it.get("material", "")), tokens)
                if s > 0:
                    scored.append((s, it))
        scored.sort(key=lambda p: (-p[0], sort_key(p[1])))
        total = len(scored)
        rows = scored if not limit else scored[:limit]
        return [copy.deepcopy(it) for _, it in rows], total

    def search_materials(self, query: str | None = "") -> list[dict[str, Any]]:
        tokens = tokenize(query)
        with self._lock:
            self.refresh()
            scored = [(material_score(m, tokens), m) for m in self._materials.values()]
        scored = [p for p in scored if p[0] > 0]
        scored.sort(key=lambda p: (-p[0], str(p[1].get("gruppe", "")), p[1]["id"]))
        return [copy.deepcopy(m) for _, m in scored]

    # -- Schreiben -----------------------------------------------------------------------------------------------------

    def _level_files(self, ebene: str) -> list[Path]:
        if ebene == "eigen":
            try:
                return sorted(p for p in self._own.glob("*.json") if p.is_file() and not p.name.startswith("."))
            except OSError:
                return []
        pf = self.project_file
        return [pf] if pf is not None and pf.is_file() else []

    def _target_file(self, ebene: str) -> Path:
        if ebene == "eigen":
            return self.own_file
        if self._project is None:
            raise CatalogError("Kein Projekt offen: Projekt-Katalog (katalog.json) geht erst mit offenem Projekt.")
        return self._project / PROJECT_FILE

    @staticmethod
    def _check_level(ebene: str) -> str:
        if ebene not in WRITABLE:
            raise CatalogError(f"Ebene {ebene!r} ist nicht beschreibbar (erlaubt: eigen, projekt). Der mitgelieferte "
                               "Katalog wird nicht geändert; eigene Einträge mit gleicher id überschreiben ihn.")
        return ebene

    def save(self, kind: str, entry: dict[str, Any], ebene: str = "eigen", *, proposal: bool = False,
             by: str = "agent") -> tuple[dict[str, Any], Path, list[str]]:
        """Eintrag anlegen oder ersetzen. Rückgabe (gespeicherter Eintrag, Datei, Hinweise). Fehler → CatalogError.

        ``proposal=True`` (MCP-Werkzeuge): speichert mit ``"status": "vorgeschlagen"``; bis Kevin ihn freigibt, lässt
        sich der Eintrag nicht verbauen. Einen freigegebenen Eintrag ersetzt ein Vorschlag nicht. Ohne ``proposal``
        (Kevin in der App) wird gespeichert, was kommt; fehlt status, gilt "frei"."""
        kind = _kind(kind)
        ebene = self._check_level(ebene)
        if not isinstance(entry, dict):
            raise CatalogError("Eintrag muss ein JSON-Objekt sein")
        clean = {k: copy.deepcopy(v) for k, v in entry.items() if k != "ebene" and not str(k).startswith("_")
                 and k != "berechnet"}
        notes: list[str] = []
        if proposal:
            clean["status"] = VORGESCHLAGEN
            clean["vorgeschlagen_am"] = time.strftime("%Y-%m-%d")
            clean["vorgeschlagen_von"] = by
        elif clean.get("status") == FREI:
            clean.pop("vorgeschlagen_am", None)
            clean.pop("vorgeschlagen_von", None)
        with self._lock:
            self.refresh()
            existing = (self._materials if kind == "material" else self._items).get(str(clean.get("id")))
            if proposal and existing is not None and is_free(existing):
                what = "Material" if kind == "material" else "Lagerteil"
                raise CatalogError(f"{what} {clean['id']!r} ist freigegeben (Ebene {existing.get('ebene')}); "
                                   "Änderungen daran macht Kevin im Lagerkatalog. Für einen neuen Eintrag eine neue id "
                                   "wählen.")
            if kind == "material":
                errors = validate_material(clean)
                if not errors and clean.get("preis_je_kg") is not None:
                    if not clean.get("preis_stand"):
                        clean["preis_stand"] = month_now()
                        notes.append(f"preis_stand fehlte: {clean['preis_stand']} eingetragen")
                    if not clean.get("preis_quelle"):
                        clean["preis_quelle"] = "eigene Angabe"
                        notes.append("preis_quelle fehlte: „eigene Angabe“ eingetragen")
                if not errors and isinstance(clean.get("aliase"), list):
                    clean["aliase"] = [a.strip().lower() for a in clean["aliase"]]
            else:
                errors = validate_item(clean, set(self._materials))
                if not errors:
                    notes += item_notes(clean)
                    preis = clean.get("preis")
                    if isinstance(preis, dict):
                        if not preis.get("stand"):
                            preis["stand"] = month_now()
                            notes.append(f"preis.stand fehlte: {preis['stand']} eingetragen")
                        if not preis.get("quelle"):
                            preis["quelle"] = "eigene Angabe"
                            notes.append("preis.quelle fehlte: „eigene Angabe“ eingetragen")
            if errors:
                raise CatalogError("\n".join(errors))
            key = "materialien" if kind == "material" else "teile"
            target = None
            for path in self._level_files(ebene):
                data, err = _read_json(path)
                if data and any(isinstance(r, dict) and r.get("id") == clean["id"] for r in data.get(key) or []):
                    target = path
            target = target or self._target_file(ebene)
            data, err = _read_json(target) if target.exists() else ({"version": 1}, None)
            if err:
                raise CatalogError(f"{target}: {err}. Datei bitte erst reparieren, sonst gehen Einträge verloren.")
            assert data is not None
            rows = [r for r in (data.get(key) or []) if not (isinstance(r, dict) and r.get("id") == clean["id"])]
            replaced = len(rows) != len(data.get(key) or [])
            rows.append(clean)
            data.setdefault("version", 1)
            data[key] = rows
            try:
                _write_json(target, data)
            except OSError as exc:
                raise CatalogError(f"{target} nicht schreibbar: {exc}") from exc
            prev = self._source.get((kind, clean["id"]))
            self.refresh(force=True)
            if replaced:
                notes.insert(0, f"Eintrag {clean['id']!r} in {target.name} ersetzt")
            elif prev is not None and prev[0] != ebene:
                notes.insert(0, f"überschreibt den Eintrag gleicher id aus der Ebene {prev[0]}")
            saved = copy.deepcopy(clean)
            saved["ebene"] = ebene
            return saved, target, notes

    def delete(self, kind: str, eid: str, ebene: str = "eigen") -> tuple[Path, str]:
        """Löscht den Eintrag in der Ebene. Gibt es ihn dort nicht, aber in einer früheren Ebene, wird er mit
        ``"entfernt": true`` ausgeblendet. Rückgabe (Datei, Meldung). Unbekannt → CatalogError."""
        kind = _kind(kind)
        ebene = self._check_level(ebene)
        key = "materialien" if kind == "material" else "teile"
        what = "Material" if kind == "material" else "Lagerteil"
        with self._lock:
            self.refresh()
            removed_from: Path | None = None
            for path in self._level_files(ebene):
                data, err = _read_json(path)
                if err or data is None:
                    continue
                rows = data.get(key) or []
                keep = [r for r in rows if not (isinstance(r, dict) and r.get("id") == eid)]
                if len(keep) != len(rows):
                    data[key] = keep
                    try:
                        _write_json(path, data)
                    except OSError as exc:
                        raise CatalogError(f"{path} nicht schreibbar: {exc}") from exc
                    removed_from = path
            if removed_from is not None:
                self.refresh(force=True)
                visible = (self._materials if kind == "material" else self._items).get(eid)
                if visible is not None:
                    return removed_from, (f"{what} {eid!r} aus {removed_from.name} gelöscht; jetzt gilt wieder der "
                                          f"Eintrag aus der Ebene {visible.get('ebene')}.")
                return removed_from, f"{what} {eid!r} aus {removed_from.name} gelöscht."
            visible = (self._materials if kind == "material" else self._items).get(eid)
            if visible is None:
                pool = list(self._materials if kind == "material" else self._items)
                close = difflib.get_close_matches(eid, pool, n=3, cutoff=0.5)
                raise CatalogError(f"{what} {eid!r} gibt es nicht"
                                   + (f"; meinten Sie {', '.join(repr(c) for c in close)}?" if close else "."))
            if EBENEN.index(visible["ebene"]) > EBENEN.index(ebene):
                raise CatalogError(f"{what} {eid!r} steht in der Ebene {visible['ebene']}; dort löschen "
                                   f"(ebene=\"{visible['ebene']}\").")
            target = self._target_file(ebene)
            data, err = _read_json(target) if target.exists() else ({"version": 1}, None)
            if err or data is None:
                raise CatalogError(f"{target}: {err}")
            data.setdefault("version", 1)
            data[key] = list(data.get(key) or []) + [{"id": eid, "entfernt": True}]
            try:
                _write_json(target, data)
            except OSError as exc:
                raise CatalogError(f"{target} nicht schreibbar: {exc}") from exc
            self.refresh(force=True)
            return target, (f"{what} {eid!r} stammt aus der Ebene {visible['ebene']} und ist jetzt in "
                            f"{target.name} ausgeblendet (\"entfernt\": true).")


def _mat_key(name: str) -> str:
    return re.sub(r"[\s_]+", "-", str(name).strip().lower())


def _kind(kind: str) -> str:
    k = KINDS.get(str(kind).strip().lower())
    if k is None:
        raise CatalogError(f"kind {kind!r} unbekannt (erlaubt: teil, material)")
    return k
