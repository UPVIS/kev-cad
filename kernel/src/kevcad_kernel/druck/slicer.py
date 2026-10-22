"""Bambu Studio im Hintergrund: Profile, STL, Slicen, Anordnen, 3MF (Druckvorschau, DRUCKVORSCHAU.md).

Bambu Studio 2.07 lässt sich ohne Fenster bedienen (``--slice``, ``--arrange``, ``--export-3mf``,
``--load-assemble-list``). Diese Datei kapselt das:

- **Profile:** Drucker-, Prozess- und Filamentprofile aus dem App-Bundle (``Contents/Resources/profiles/BBL``) und
  Kevins Benutzerprofile (``~/Library/Application Support/BambuStudio/user/<id>/``), Vererbung (``inherits``) aufgelöst.
  Kevins Dateien werden nur gelesen; alles, was der Slicer bekommt, liegt als Kopie im Arbeitsordner.
- **Slicen** einer Gruppe (ein Teil in Druckausrichtung) und ganzer Platten (Montageliste mit festen Lagen und
  Einstellungen je Teil). Ergebnis aus ``result.json`` des Slicers: Druckzeit, Filament, Zeiten je Merkmal.
- **Anordnen** mit ``--arrange`` (genau, mit Drehen) und **3MF** der Platten mit allen Einstellungen.

Höchstens ein Slicer-Prozess gleichzeitig auf dem Rechner (Dateisperre im Zwischenspeicher), niedrige Priorität
(``nice``), Abbruch über ein ``threading.Event``. Ohne Bambu Studio (Mac mini) liefert ``verfuegbar()`` False.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import plistlib
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

FILAMENT_QUERSCHNITT_CM2 = math.pi * 0.0875 ** 2   # 1,75 mm
CM3_JE_M = FILAMENT_QUERSCHNITT_CM2 * 100          # 2,405 cm³ je Meter
PLATTENABSTAND = 256.0 * 1.2                       # Bambu legt Platte n um 1,2 Bettbreiten versetzt ab
ZEITLIMIT_S = 300.0

PROZESSE: dict[float, str] = {
    0.08: "0.08mm Extra Fine @BBL P1P", 0.12: "0.12mm Fine @BBL P1P", 0.16: "0.16mm Optimal @BBL P1P",
    0.2: "0.20mm Standard @BBL P1P", 0.24: "0.24mm Draft @BBL P1P", 0.28: "0.28mm Extra Draft @BBL P1P",
}
MASCHINE = "Bambu Lab P1P 0.4 nozzle"
DRUCKER = {"p1p-0.4": {"name": "Bambu Lab P1P 0.4", "maschine": MASCHINE, "bett": "Textured PEI Plate"}}
# Filament je Material: Reihenfolge = Vorrang (Kevins Profil zuerst); Projekt-Einstellung druck.filament geht vor
FILAMENTE: dict[str, tuple[str, ...]] = {
    "pla": ("Amazon Basics PLA", "Bambu PLA Basic @BBL P1P"),
    "petg": ("Bambu PETG Basic @BBL X1C", "Generic PETG @BBL P1P"),
    "tpu-95a": ("Bambu TPU 95A @BBL P1P", "Generic TPU @BBL P1P"),
    "abs": ("Bambu ABS @BBL P1P", "Generic ABS @BBL P1P"),
    "asa": ("Generic ASA @BBL P1P",),
    "pc-filament": ("Bambu PC @BBL P1P", "Generic PC @BBL P1P"),
    "pa": ("Generic PA @BBL P1P",),
    "pa-cf": ("Bambu PA-CF @BBL P1P", "Generic PA-CF @BBL P1P"),
    "pla-cf": ("Bambu PLA-CF @BBL P1P", "Generic PLA-CF @BBL P1P"),
}
MUSTER_BAMBU = {"gyroid": "gyroid", "grid": "grid", "cubic": "cubic", "honeycomb": "honeycomb",
                "rectilinear": "zig-zag", "zigzag": "zig-zag", "line": "line", "concentric": "concentric",
                "triangles": "triangles", "crosshatch": "crosshatch", "lightning": "lightning"}
STUETZEN_BAMBU = {"baum": "tree(auto)", "normal": "normal(auto)"}
NAHT_BAMBU = {"hinten": "back", "ausgerichtet": "aligned", "nah": "nearest", "zufall": "random"}
OBERFLAECHE_BAMBU = {"monoton_linie": "monotonicline", "monoton": "monotonic", "linie": "zig-zag",
                     "konzentrisch": "concentric"}


class SlicerFehler(RuntimeError):
    pass


class Abgebrochen(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------------------------------
# Orte


def app_pfad() -> Path:
    return Path(os.environ.get("KEVCAD_BAMBU_APP", "/Applications/BambuStudio.app"))


def programm() -> Path | None:
    p = app_pfad() / "Contents" / "MacOS" / "BambuStudio"
    return p if p.is_file() and os.access(p, os.X_OK) else None


def verfuegbar() -> bool:
    return programm() is not None and system_ordner().is_dir()


def version() -> str | None:
    try:
        with open(app_pfad() / "Contents" / "Info.plist", "rb") as f:
            info = plistlib.load(f)
        return str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "") or None
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def system_ordner() -> Path:
    return app_pfad() / "Contents" / "Resources" / "profiles" / "BBL"


def benutzer_ordner() -> list[Path]:
    basis = Path(os.environ.get("KEVCAD_BAMBU_USER", str(Path.home() / "Library/Application Support/BambuStudio/user")))
    if not basis.is_dir():
        return []
    return sorted(p for p in basis.iterdir() if p.is_dir())


def cache_ordner() -> Path:
    p = Path(os.environ.get("KEVCAD_DRUCK_CACHE", str(Path.home() / "Library/Caches/de.upvis.kevcad/druck")))
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------------------------------------------------
# Profile


_INDEX: dict[tuple[str, str], Path] | None = None
_INDEX_LOCK = threading.Lock()


def _index() -> dict[tuple[str, str], Path]:
    """(Art, Name) → Datei; Benutzerprofile gehen vor (sie überschreiben gleichnamige nicht, haben eigene Namen)."""
    global _INDEX
    with _INDEX_LOCK:
        if _INDEX is not None:
            return _INDEX
        idx: dict[tuple[str, str], Path] = {}
        for ordner in benutzer_ordner():
            for art in ("machine", "process", "filament"):
                for p in sorted((ordner / art).glob("*.json")) if (ordner / art).is_dir() else []:
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if isinstance(d, dict) and d.get("name"):
                        idx.setdefault((art, str(d["name"])), p)
        basis = system_ordner()
        if basis.is_dir():  # Systemprofile heißen wie ihre Datei: nur Namen lesen (schnell)
            for art in ("machine", "process", "filament"):
                for wurzel, _, dateien in os.walk(basis / art):
                    for d in sorted(dateien):
                        if d.endswith(".json"):
                            idx.setdefault((art, d[:-5]), Path(wurzel) / d)
        _INDEX = idx
        return idx


def _index_voll(art: str, name: str) -> Path | None:
    """Langsamer Weg: Systemprofile lesen, deren Name nicht dem Dateinamen entspricht."""
    basis = system_ordner() / art
    if not basis.is_dir():
        return None
    for p in sorted(basis.rglob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("name") == name:
            with _INDEX_LOCK:
                if _INDEX is not None:
                    _INDEX[(art, name)] = p
            return p
    return None


def index_leeren() -> None:
    """Profilverzeichnis neu lesen (anderes Bambu Studio, neue Benutzerprofile); auch die Zwischenspeicher der
    Kompatibilität und der Filamentwahl."""
    global _INDEX
    with _INDEX_LOCK:
        _INDEX = None
    _KOMPATIBEL.clear()
    try:
        from kevcad_kernel.druck import filamentwahl

        filamentwahl.cache_leeren()
    except ImportError:  # pragma: no cover
        pass


# Schlüssel einer Vorlage (``include``), die nicht in das einbindende Profil gehören
_VORLAGE_META = ("name", "type", "from", "instantiation", "setting_id", "inherits", "include", "filament_id")


def profil(art: str, name: str) -> dict[str, Any]:
    """Profil mit aufgelöster Vererbung (``inherits``) und eingebundenen Vorlagen (``include``); ``SlicerFehler``,
    wenn es fehlt.

    ``include`` (seit Bambu Studio 2.x): Vorlagen, deren Werte das Profil übernimmt, etwa beim „Bambu Lab P1P 0.4
    nozzle“ den Start-, End-, Filamentwechsel- und Schichtwechsel-G-Code („… template machine_start_gcode“). Reihenfolge
    wie in Bambu Studio: Eltern, dann die Vorlagen, dann die eigenen Werte. Ohne das blieb bis 22.10.2026 der allgemeine
    Start-G-Code aus „fdm_machine_common“ stehen (Düse fest ``M109 S205``, ohne das P1P-Vorprogramm), in jedem
    geslicten G-Code und in den Projekt-Einstellungen jedes exportierten 3MF."""
    p = _index().get((art, name)) or _index_voll(art, name)
    if p is None:
        raise SlicerFehler(f"Bambu-Studio-Profil {art} „{name}“ nicht gefunden")
    eigen = json.loads(p.read_text(encoding="utf-8"))
    eltern = eigen.get("inherits")
    d: dict[str, Any] = profil(art, str(eltern)) if eltern else {}
    vorlagen = eigen.get("include") or []
    for v in [vorlagen] if isinstance(vorlagen, str) else vorlagen:
        try:
            t = profil(art, str(v))
        except SlicerFehler:
            continue  # Vorlage fehlt: Bambu Studio lädt das Profil trotzdem
        d.update({k: x for k, x in t.items() if k not in _VORLAGE_META})
    d.update(eigen)
    d.pop("inherits", None)
    d.pop("include", None)
    d["type"] = art
    return d


def profil_vorhanden(art: str, name: str) -> bool:
    return (art, name) in _index()


# Filamenttyp im Profil (filament_type) je Kev-CAD-Material
FILAMENT_TYP = {"pla": "PLA", "petg": "PETG", "tpu-95a": "TPU", "abs": "ABS", "asa": "ASA", "pc-filament": "PC",
                "pa": "PA", "pa-cf": "PA-CF", "pla-cf": "PLA-CF"}
_KOMPATIBEL: dict[tuple[str, str], bool] = {}


def maschinen_name(drucker: str = "p1p-0.4") -> str:
    return DRUCKER.get(drucker, DRUCKER["p1p-0.4"])["maschine"]


def kompatibel(filament: str, drucker: str = "p1p-0.4") -> bool:
    """Passt das Filamentprofil (samt Vererbung) laut ``compatible_printers`` zum Drucker? Leere Liste = alle (so
    behandelt Bambu Studio Benutzerprofile ohne eigene Liste)."""
    maschine = maschinen_name(drucker)
    key = (filament, maschine)
    if key not in _KOMPATIBEL:
        try:
            cp = profil("filament", filament).get("compatible_printers") or []
        except (SlicerFehler, OSError, ValueError):
            _KOMPATIBEL[key] = False
        else:
            _KOMPATIBEL[key] = not cp or maschine in cp
    return _KOMPATIBEL[key]


def _filament_suche(material: str, drucker: str) -> list[str]:
    """Alle Systemfilamente des Materialtyps, die zum Drucker passen: „@BBL P1P“ zuerst, dann Bambu, dann andere."""
    typ = FILAMENT_TYP.get(material)
    if not typ:
        return []
    treffer = []
    for (art, name) in list(_index()):
        if art != "filament" or typ.split("-")[0].lower() not in name.lower() or name.startswith("fdm_"):
            continue
        try:
            d = profil("filament", name)
        except (SlicerFehler, OSError, ValueError):
            continue
        ft = d.get("filament_type")
        ft = ft[0] if isinstance(ft, list) and ft else ft
        if str(ft) == typ and str(d.get("instantiation", "true")) != "false" and kompatibel(name, drucker):
            treffer.append(name)
    return sorted(treffer, key=lambda n: ("@BBL P1P" not in n or "nozzle" in n, not n.startswith("Bambu"),
                                          "Support" in n, n))


def filament_name(material: str, wunsch: str | None = None, drucker: str = "p1p-0.4") -> str:
    """Filamentprofil für ein Material, das laut ``compatible_printers`` zum Drucker passt (sonst markiert Bambu Studio
    es in der Oberfläche als unpassend): Wunsch aus den Projekt-Einstellungen (genau, mit „ @BBL P1P“ oder als Anfang
    eines Profilnamens), sonst die Liste ``FILAMENTE``, sonst das beste passende Systemprofil gleichen Typs."""
    kandidaten: list[str] = []
    if wunsch:
        kandidaten += [wunsch, f"{wunsch} @BBL P1P", f"{wunsch} @BBL X1C"]
        kandidaten += sorted(n for (a, n) in _index() if a == "filament" and n.startswith(wunsch)
                             and "nozzle" not in n)
    kandidaten += list(FILAMENTE.get(material, ()))
    for k in kandidaten:
        if profil_vorhanden("filament", k) and kompatibel(k, drucker):
            return k
    treffer = _filament_suche(material, drucker)
    if treffer:
        return treffer[0]
    raise SlicerFehler(f"kein Bambu-Studio-Filamentprofil für {material!r} passt zum {maschinen_name(drucker)}"
                       + (f" ({wunsch!r})" if wunsch else ""))


# Druckplatten (curr_bed_type) und die Temperatur im Filamentprofil, die sie braucht (0 = nicht geeignet)
PLATTEN = {"Textured PEI Plate": "textured_plate_temp", "Cool Plate": "cool_plate_temp",
           "Engineering Plate": "eng_plate_temp", "High Temp Plate": "hot_plate_temp",
           "Supertack Plate": "supertack_plate_temp"}
PLATTE_STANDARD = "Textured PEI Plate"
_PLATTEN_ALIAS = {"textured pei plate": "Textured PEI Plate", "textured pei": "Textured PEI Plate",
                  "textured": "Textured PEI Plate", "texturiert": "Textured PEI Plate", "pei": "Textured PEI Plate",
                  "cool plate": "Cool Plate", "cool": "Cool Plate", "engineering plate": "Engineering Plate",
                  "engineering": "Engineering Plate", "high temp plate": "High Temp Plate",
                  "smooth pei plate": "High Temp Plate", "smooth pei": "High Temp Plate", "glatt": "High Temp Plate",
                  "high temp": "High Temp Plate", "supertack plate": "Supertack Plate", "supertack": "Supertack Plate"}


def platte_name(wert: Any) -> str:
    """Bambu-Studio-Name der Druckplatte (``kevcad.json`` ``druck.platte``); None = Texturplatte (Kevins P1P)."""
    if wert is None or str(wert).strip() == "":
        return PLATTE_STANDARD
    s = str(wert).strip()
    if s in PLATTEN:
        return s
    t = _PLATTEN_ALIAS.get(s.lower())
    if t is None:
        raise SlicerFehler(f"Druckplatte {wert!r} unbekannt (erlaubt: {', '.join(PLATTEN)})")
    return t


def platte_passt(filament: Filament, platte: str) -> bool:
    """Kann das Filament auf dieser Platte gedruckt werden (Plattentemperatur im Profil nicht 0)?"""
    try:
        v = filament_daten(filament).get(PLATTEN.get(platte, ""))
    except (SlicerFehler, OSError, ValueError):
        return True
    v = v[0] if isinstance(v, list) and v else v
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return True


def prozess_name(schicht: float) -> str:
    beste = min(PROZESSE, key=lambda h: abs(h - float(schicht)))
    return PROZESSE[beste]


def prozess_einstellungen(einstellungen: dict[str, Any]) -> dict[str, str]:
    """Kev-CAD-Einstellungen (DRUCK_EINSTELLUNGEN) als Bambu-Studio-Prozesswerte (Texte wie in den Profilen)."""
    e = einstellungen
    out: dict[str, str] = {}
    if e.get("schicht_mm") is not None:
        out["layer_height"] = f"{float(e['schicht_mm']):g}"
    if e.get("waende") is not None:
        out["wall_loops"] = str(int(e["waende"]))
    if e.get("decken") is not None:
        out["top_shell_layers"] = str(int(e["decken"]))
        out["top_shell_thickness"] = "0"
    if e.get("boeden") is not None:
        out["bottom_shell_layers"] = str(int(e["boeden"]))
        out["bottom_shell_thickness"] = "0"
    if e.get("fuellung") is not None:
        out["sparse_infill_density"] = f"{round(float(e['fuellung']) * 100):d}%"
    if e.get("muster"):
        out["sparse_infill_pattern"] = MUSTER_BAMBU.get(str(e["muster"]), str(e["muster"]))
    st = e.get("stuetzen")
    if st is not None:
        out["enable_support"] = "0" if st == "keine" else "1"
        if st in STUETZEN_BAMBU:
            out["support_type"] = STUETZEN_BAMBU[st]
    if e.get("brim") is not None:
        out["brim_type"] = "outer_only" if e["brim"] else "no_brim"
        if e["brim"]:
            out["brim_width"] = f"{float(e.get('brim_mm') or 5):g}"
    # Paket B (druck/druckfertig.py): druckfertig je Objekt
    if e.get("stuetzen_nur_platte") is not None and st not in (None, "keine"):
        out["support_on_build_plate_only"] = "1" if e["stuetzen_nur_platte"] else "0"
    if e.get("stuetzen_abstand_mm") is not None and st not in (None, "keine"):
        out["support_top_z_distance"] = f"{float(e['stuetzen_abstand_mm']):g}"
    if e.get("naht"):
        out["seam_position"] = NAHT_BAMBU.get(str(e["naht"]), str(e["naht"]))
    if e.get("buegeln") is not None:
        out["ironing_type"] = "top" if e["buegeln"] else "no ironing"
    if e.get("oberflaeche"):
        out["top_surface_pattern"] = OBERFLAECHE_BAMBU.get(str(e["oberflaeche"]), str(e["oberflaeche"]))
    for k, b in (("loch_kompensation_mm", "xy_hole_compensation"), ("kontur_kompensation_mm",
                                                                     "xy_contour_compensation"),
                 ("elefantenfuss_mm", "elefant_foot_compensation")):
        if e.get(k) is not None:
            out[b] = f"{float(e[k]):g}"
    return out


def prozess_profil(einstellungen: dict[str, Any], bett: str = "Textured PEI Plate") -> tuple[str, dict[str, Any]]:
    name = prozess_name(float(einstellungen.get("schicht_mm") or 0.2))
    d = profil("process", name)
    d.update(prozess_einstellungen(einstellungen))
    if einstellungen.get("_global"):
        # Platte mit Objekten: Global „kein Brim“ schaltet auch den Brim je Objekt ab (geprüft mit 2.07.01.62).
        # Global bleibt der Profilwert (auto_brim), je Objekt entscheiden print_params.
        basis = profil("process", name)
        for k in ("brim_type", "brim_width"):
            if k in basis:
                d[k] = basis[k]
            else:
                d.pop(k, None)  # Vorgabe von Bambu Studio (auto_brim)
    d["curr_bed_type"] = bett
    d["print_settings_id"] = name
    d["name"] = name
    return name, d


def maschinen_profil(drucker: str = "p1p-0.4") -> dict[str, Any]:
    name = DRUCKER.get(drucker, DRUCKER["p1p-0.4"])["maschine"]
    d = profil("machine", name)
    d["printer_settings_id"] = name
    d["name"] = name
    return d


Filament = str | dict  # Name eines Bambu-Profils oder Preset (druck/filamente.py ``preset_spec``)


def filament_name_von(f: Filament) -> str:
    return str(f.get("name") or f.get("basis")) if isinstance(f, dict) else str(f)


def filament_daten(f: Filament) -> dict[str, Any]:
    """Aufgelöstes Filamentprofil zu einem Profilnamen oder einem Preset ``{"name", "basis", "werte", "farbe",
    "inherits"}``: Basisprofil (mit Vererbung und Vorlagen), darüber die Abweichungen (``werte``, Bambu-Schlüssel).
    Ein Preset geht vollständig aufgelöst an Bambu Studio (die Kommandozeile löst ``inherits`` nicht selbst auf und
    nähme sonst Vorgabewerte, geprüft am 22.10.2026); ``inherits`` nennt nur das Systemprofil, von dem es abstammt,
    damit Bambu Studio es als Projekt-Preset mit diesem Elternteil führt (``inherits_group``)."""
    if not isinstance(f, dict):
        return profil("filament", str(f))
    d = profil("filament", str(f["basis"]))
    d.update(f.get("werte") or {})
    if f.get("farbe"):
        d["filament_colour"] = [str(f["farbe"])]
        d["default_filament_colour"] = [str(f["farbe"])]
    d["from"] = "User"
    if f.get("inherits"):
        d["inherits"] = str(f["inherits"])
    return d


def filament_profil(f: Filament) -> dict[str, Any]:
    """Filamentprofil für ``--load-filaments``: aufgelöst, Name und ``filament_settings_id`` = Profil- bzw.
    Preset-Name."""
    d = filament_daten(f)
    name = filament_name_von(f)
    d["filament_settings_id"] = [name]
    d["name"] = name
    return d


def filament_dichte(d: dict[str, Any]) -> float:
    v = d.get("filament_density")
    if isinstance(v, list):
        v = v[0] if v else None
    try:
        return float(v)
    except (TypeError, ValueError):
        return 1.24


def filament_wert(d: dict[str, Any], key: str, standard: float) -> float:
    v = d.get(key)
    if isinstance(v, list):
        v = v[0] if v else None
    try:
        return float(str(v).rstrip("%"))
    except (TypeError, ValueError):
        return standard


# ---------------------------------------------------------------------------------------------------------------------
# STL


def schreibe_stl(pfad: Path, punkte: np.ndarray, dreiecke: np.ndarray, name: str = "kevcad") -> None:
    """Binäres STL (Normalen aus den Ecken)."""
    P = np.asarray(punkte, dtype=np.float64).reshape(-1, 3)
    T = np.asarray(dreiecke, dtype=np.int64).reshape(-1, 3)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 1e-12)
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("x", "<u2")])
    rec["n"], rec["a"], rec["b"], rec["c"] = n, a, b, c
    kopf = name.encode("ascii", "replace")[:80].ljust(80, b" ")
    with open(pfad, "wb") as f:
        f.write(kopf)
        f.write(struct.pack("<I", len(T)))
        f.write(rec.tobytes())


def lies_stl(pfad: Path) -> np.ndarray:
    """Dreiecke (m, 3, 3) eines binären STL."""
    data = Path(pfad).read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    rec = np.frombuffer(data, dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3),
                                     ("x", "<u2")], count=n, offset=84)
    return np.stack([rec["a"], rec["b"], rec["c"]], axis=1).astype(np.float64)


def schreibe_stl_dreiecke(pfad: Path, tris: np.ndarray, name: str = "kevcad") -> None:
    m = len(tris)
    schreibe_stl(pfad, tris.reshape(-1, 3), np.arange(m * 3).reshape(m, 3), name)


def netz_der_form(shape: Any, toleranz: float = 0.01, winkel: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
    """Feines Dreiecksnetz einer build123d-Form (Weltlage) für den Slicer; vernetzt eine Kopie."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    topo = getattr(shape, "wrapped", shape)
    kopie = BRepBuilderAPI_Copy(topo, True, False).Shape()
    BRepMesh_IncrementalMesh(kopie, toleranz, False, winkel, True)
    punkte: list[np.ndarray] = []
    dreiecke: list[np.ndarray] = []
    basis = 0
    exp = TopExp_Explorer(kopie, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        exp.Next()
        if tri is None:
            continue
        trsf = loc.Transformation()
        n = tri.NbNodes()
        P = np.empty((n, 3))
        for i in range(1, n + 1):
            p = tri.Node(i).Transformed(trsf)
            P[i - 1] = (p.X(), p.Y(), p.Z())
        m = tri.NbTriangles()
        T = np.empty((m, 3), dtype=np.int64)
        for i in range(1, m + 1):
            a, b, c = tri.Triangle(i).Get()
            T[i - 1] = (a - 1, b - 1, c - 1)
        if face.Orientation() == TopAbs_REVERSED:
            T = T[:, [0, 2, 1]]
        punkte.append(P)
        dreiecke.append(T + basis)
        basis += n
    if not punkte:
        raise SlicerFehler("Form ohne Flächen (nichts zu vernetzen)")
    return np.vstack(punkte), np.vstack(dreiecke)


def stl_in_druckausrichtung(shape: Any, geo: dict[str, Any], pfad: Path, toleranz: float = 0.01) -> dict[str, Any]:
    """STL eines gezeigten Teils (Weltlage) in Druckausrichtung: ``p = matrix · (p_welt − t) − versatz`` (aus
    ``druck/vorschau_geo.py``), Auflage bei z = 0, Mitte des Hüllrechtecks bei (0, 0). Liefert Hüllmaß und
    Dreieckszahl."""
    P, T = netz_der_form(shape, toleranz=toleranz)
    A = np.asarray(geo["matrix"], dtype=np.float64)
    t = np.asarray(geo["t"], dtype=np.float64)
    v = np.asarray(geo["versatz"], dtype=np.float64)
    Q = (P - t) @ A.T - v
    dz = float(Q[:, 2].min())
    Q[:, 2] -= dz  # das feine Netz liegt genau auf dem Bett (dieselbe Verschiebung gilt für die Modifier)
    if abs(np.linalg.det(A) + 1) < 1e-6:  # gespiegelt: Umlaufsinn umkehren
        T = T[:, [0, 2, 1]]
    schreibe_stl(pfad, Q, T, name=str(geo.get("form") or "kevcad")[:60])
    lo, hi = Q.min(axis=0), Q.max(axis=0)
    return {"groesse": [round(float(x), 3) for x in hi - lo], "min": [round(float(x), 3) for x in lo],
            "dreiecke": int(len(T)), "z_korrektur": round(-dz, 6)}


def zylinder_netz(unten: Any, oben: Any, radius: float, n: int = 48) -> tuple[np.ndarray, np.ndarray]:
    """Geschlossener Zylinder (Punkte, Dreiecke nach außen) von ``unten`` nach ``oben`` mit ``radius``."""
    a = np.asarray(unten, dtype=np.float64)
    b = np.asarray(oben, dtype=np.float64)
    ax = b - a
    lang = float(np.linalg.norm(ax))
    if lang < 1e-9 or radius <= 0:
        raise SlicerFehler("Modifier ohne Länge oder Radius")
    ax = ax / lang
    hilf = np.array([1.0, 0.0, 0.0]) if abs(ax[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(ax, hilf)
    u /= np.linalg.norm(u)
    v = np.cross(ax, u)
    w = np.linspace(0.0, 2 * math.pi, n, endpoint=False)
    ring = radius * (np.cos(w)[:, None] * u + np.sin(w)[:, None] * v)
    P = np.vstack([a + ring, b + ring, a, b])
    cu, co = 2 * n, 2 * n + 1
    T = []
    for i in range(n):
        j = (i + 1) % n
        T += [(i, j, n + j), (i, n + j, n + i), (cu, j, i), (co, n + i, n + j)]
    return P, np.asarray(T, dtype=np.int64)


def schreibe_modifier_stl(m: dict[str, Any], pfad: Path, z_korrektur: float = 0.0) -> Path:
    """STL eines Modifiers (``druckfertig._modifier``) in den Koordinaten des Teil-STL (``stl_in_druckausrichtung``:
    dieselbe Verschiebung in z)."""
    dz = np.array([0.0, 0.0, float(z_korrektur)])
    P, T = zylinder_netz(np.asarray(m["unten"], dtype=np.float64) + dz, np.asarray(m["oben"], dtype=np.float64) + dz,
                         float(m["radius"]))
    schreibe_stl(pfad, P, T, name=str(m.get("name") or "modifier")[:60])
    return pfad


# ---------------------------------------------------------------------------------------------------------------------
# Ausführen


@contextlib.contextmanager
def _sperre(abbruch: threading.Event | None):
    """Rechnerweit höchstens ein Slicer (Dateisperre); wartet, bricht bei ``abbruch`` ab."""
    pfad = cache_ordner() / "slicer.lock"
    f = open(pfad, "a+")
    try:
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if abbruch is not None and abbruch.wait(0.2):
                    raise Abgebrochen("neuer Lauf") from None
                if abbruch is None:
                    time.sleep(0.2)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()


def ausfuehren(args: list[str], ordner: Path, abbruch: threading.Event | None = None,
               zeitlimit_s: float = ZEITLIMIT_S) -> dict[str, Any]:
    """Bambu Studio mit ``args`` im Arbeitsordner (dort landet auch ``result.json``); liefert result.json."""
    exe = programm()
    if exe is None:
        raise SlicerFehler("Bambu Studio nicht gefunden (/Applications/BambuStudio.app)")
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "result.json").unlink(missing_ok=True)
    with _sperre(abbruch):
        if abbruch is not None and abbruch.is_set():
            raise Abgebrochen("neuer Lauf")
        cmd = ["nice", "-n", "15", str(exe), "--debug", "1", *args, "--outputdir", str(ordner)]
        proc = subprocess.Popen(cmd, cwd=str(ordner), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env={**os.environ, "HOME": str(Path.home())})
        t0 = time.monotonic()
        try:
            while True:
                try:
                    proc.wait(0.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if abbruch is not None and abbruch.is_set():
                    proc.kill()
                    proc.wait(5)
                    raise Abgebrochen("neuer Lauf")
                if time.monotonic() - t0 > zeitlimit_s:
                    proc.kill()
                    proc.wait(5)
                    raise SlicerFehler(f"Bambu Studio antwortet nicht (über {zeitlimit_s:g} s)")
        finally:
            if proc.poll() is None:
                proc.kill()
        ausgabe = (proc.stdout.read() if proc.stdout else b"").decode("utf-8", "replace")
    try:
        res = json.loads((ordner / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res = {}
    rc = res.get("return_code", proc.returncode)
    if rc not in (0, None) or proc.returncode not in (0, None):
        zeilen = [z for z in ausgabe.splitlines() if "error" in z.lower() or "fehl" in z.lower()]
        meldung = res.get("error_string") or (zeilen[-1] if zeilen else ausgabe.strip()[-300:])
        raise SlicerFehler(f"Bambu Studio meldet Fehler {rc}: {meldung}")
    res["_dauer_s"] = round(time.monotonic() - t0, 2)
    return res


@dataclass
class Profile:
    """Die drei Profile eines Slicer-Laufs als Dateien im Arbeitsordner."""

    maschine: Path
    prozess: Path
    filamente: list[Path]
    prozess_name: str
    filament_namen: list[str]
    dichten: list[float]
    werte: dict[str, Any] = field(default_factory=dict)


def schreibe_profile(ordner: Path, einstellungen: dict[str, Any], filamente: list[Filament],
                     drucker: str = "p1p-0.4", platte: str | None = None) -> Profile:
    ordner.mkdir(parents=True, exist_ok=True)
    m = maschinen_profil(drucker)
    pname, p = prozess_profil(einstellungen, platte_name(platte or DRUCKER.get(drucker, DRUCKER["p1p-0.4"])["bett"]))
    mp, pp = ordner / "maschine.json", ordner / "prozess.json"
    mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    pp.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    fpfade, dichten = [], []
    for i, name in enumerate(filamente):
        f = filament_profil(name)
        fp = ordner / f"filament{i + 1}.json"
        fp.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
        fpfade.append(fp)
        dichten.append(filament_dichte(f))
    return Profile(mp, pp, fpfade, pname, [filament_name_von(f) for f in filamente], dichten)


def _profil_args(pr: Profile) -> list[str]:
    return ["--load-settings", f"{pr.maschine};{pr.prozess}", "--load-filaments", ";".join(str(p) for p in pr.filamente)]


def _platten_ergebnis(res: dict[str, Any], dichten: list[float]) -> list[dict[str, Any]]:
    out = []
    for pl in res.get("sliced_plates") or []:
        vol_cm3 = 0.0
        for f in pl.get("filaments") or []:
            i = int(f.get("id") or 1) - 1
            d = dichten[i] if 0 <= i < len(dichten) else dichten[0]
            vol_cm3 += float(f.get("total_used_g") or 0.0) / d
        merkmale = {k: round(float(v), 1) for k, v in (pl.get("feature_type_times") or {}).items()}
        out.append({"platte": int(pl.get("id") or len(out) + 1),
                    "zeit_s": round(float(pl.get("total_predication") or 0.0), 1),
                    "volumen_cm3": round(vol_cm3, 4), "m": round(vol_cm3 / CM3_JE_M, 3),
                    "g_bambu": round(sum(float(f.get("total_used_g") or 0.0) for f in pl.get("filaments") or []), 3),
                    "merkmale": merkmale, "start_s": merkmale.get("Custom", 0.0),
                    "objekte": [o.get("name") for o in pl.get("objects") or []],
                    "warnung": pl.get("warning_message") or ""})
    return out


def slice_teil(stl: Path, einstellungen: dict[str, Any], filament: Filament, ordner: Path,
               abbruch: threading.Event | None = None, drucker: str = "p1p-0.4",
               platte: str | None = None, modifier: list[ModifierTeil] | None = None) -> dict[str, Any]:
    """Ein Teil (STL in Druckausrichtung) slicen: ``zeit_s``, ``volumen_cm3``, ``m``, ``merkmale`` … Mit ``modifier``
    (Strang „Rest Druck“) über eine Montageliste, das Teil in der Mitte der Platte samt seinen Modifiern."""
    pr = schreibe_profile(ordner, einstellungen, [filament], drucker, platte)
    if modifier:
        liste = montageliste([[PlattenObjekt(stl=stl, x=128.0, y=128.0, drehung=0.0, einstellungen=einstellungen,
                                             name=stl.stem, modifier=list(modifier))]], ordner)
        res = ausfuehren([*_profil_args(pr), "--load-assemble-list", str(liste), "--slice", "0"], ordner, abbruch)
    else:
        res = ausfuehren([*_profil_args(pr), "--slice", "0", str(stl)], ordner, abbruch)
    platten = _platten_ergebnis(res, pr.dichten)
    for g in ordner.glob("*.gcode"):
        g.unlink(missing_ok=True)
    if not platten:
        raise SlicerFehler("Bambu Studio hat nichts geslict")
    erg = platten[0]
    erg.update({"prozess": pr.prozess_name, "filament": filament_name_von(filament), "dauer_s": res.get("_dauer_s")})
    return erg


# ---------------------------------------------------------------------------------------------------------------------
# Anordnen und Platten


def _matrix_aus_3mf(text: str) -> np.ndarray:
    v = [float(x) for x in text.split()]
    m = np.eye(4)
    m[:3, :3] = np.array(v[:9]).reshape(3, 3).T if len(v) >= 12 else np.eye(3)
    if len(v) >= 12:
        m[:3, 3] = v[9:12]
    return m


def lies_anordnung(pfad_3mf: Path) -> list[dict[str, Any]]:
    """Platten eines von Bambu Studio geschriebenen 3MF: je Platte die Objekte mit Name, Drehung (Grad um Z) und
    Lage (Mitte, Plattenkoordinaten)."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(pfad_3mf) as z:
        modell = ET.fromstring(z.read("3D/3dmodel.model"))
        einst = ET.fromstring(z.read("Metadata/model_settings.config"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    lagen: dict[str, np.ndarray] = {}
    for item in modell.findall(".//m:build/m:item", ns):
        lagen[item.get("objectid") or ""] = _matrix_aus_3mf(item.get("transform") or "1 0 0 0 1 0 0 0 1 0 0 0")
    namen: dict[str, str] = {}
    for obj in einst.findall("object"):
        for md in obj.findall("metadata"):
            if md.get("key") == "name":
                namen[obj.get("id") or ""] = md.get("value") or ""
    platten = []
    for pl in einst.findall("plate"):
        nr = 0
        for md in pl.findall("metadata"):
            if md.get("key") == "plater_id":
                nr = int(md.get("value") or 0)
        objekte = []
        for inst in pl.findall("model_instance"):
            oid = ""
            for md in inst.findall("metadata"):
                if md.get("key") == "object_id":
                    oid = md.get("value") or ""
            m = lagen.get(oid)
            if m is None:
                continue
            objekte.append({"objekt": oid, "name": namen.get(oid, ""), "matrix": m})
        platten.append({"nr": nr, "objekte": objekte})
    platten.sort(key=lambda p: p["nr"])
    n = len(platten)
    spalten = max(1, math.ceil(math.sqrt(n)))
    for i, pl in enumerate(platten):
        ox, oy = (i % spalten) * PLATTENABSTAND, -(i // spalten) * PLATTENABSTAND
        for o in pl["objekte"]:
            m = o["matrix"]
            o["x"], o["y"] = float(m[0, 3] - ox), float(m[1, 3] - oy)
            o["drehung"] = round(math.degrees(math.atan2(m[1, 0], m[0, 0])), 3)
    return platten


def anordnen(objekte: list[tuple[Path, int]], ordner: Path, abbruch: threading.Event | None = None,
             filament: Filament | None = None, drucker: str = "p1p-0.4", abstand_mm: float | None = None,
             platte: str | None = None) -> list[dict]:
    """``objekte``: (STL, Anzahl). Bambu Studio ordnet an (mit Drehen, Sperrzone aus dem Maschinenprofil) und legt bei
    Bedarf weitere Platten an. Ergebnis wie ``lies_anordnung``; Namen „<stl-stamm>_<n>“."""
    e = {"schicht_mm": 0.2}
    pr = schreibe_profile(ordner, e, [filament or FILAMENTE["pla"][-1]], drucker, platte)
    if abstand_mm is not None:
        d = json.loads(pr.prozess.read_text())
        d["min_object_distance"] = f"{abstand_mm:g}"
        pr.prozess.write_text(json.dumps(d))
    ziel = ordner / "anordnung.3mf"
    ziel.unlink(missing_ok=True)
    args = [*_profil_args(pr), "--arrange", "1", "--allow-rotations",
            "--clone-objects", ",".join(str(max(1, int(n))) for _, n in objekte),
            "--export-3mf", ziel.name, *[str(p) for p, _ in objekte]]
    ausfuehren(args, ordner, abbruch)
    if not ziel.exists():
        raise SlicerFehler("Bambu Studio hat keine Anordnung geschrieben")
    return lies_anordnung(ziel)


def drehe_stl(tris: np.ndarray, grad: float) -> tuple[np.ndarray, np.ndarray]:
    """Dreiecke um Z drehen und das Hüllrechteck wieder auf die Mitte legen: (Dreiecke, Verschiebung der Mitte)."""
    w = math.radians(grad)
    c, s = math.cos(w), math.sin(w)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    P = tris.reshape(-1, 3) @ R.T
    lo, hi = P.min(axis=0), P.max(axis=0)
    mitte = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    return (P - mitte).reshape(-1, 3, 3), mitte


@dataclass
class PlattenObjekt:
    stl: Path            # STL in Druckausrichtung, Mitte des Hüllrechtecks bei (0, 0), Auflage bei z = 0
    x: float             # Mitte auf der Platte
    y: float
    drehung: float       # Grad um Z
    filament: int = 1    # Nummer des Filaments (1 …)
    einstellungen: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    # Strang „Rest Druck“: Modifier um Gewindeeinsätze und Kernlöcher, STL in den Koordinaten von ``stl``
    modifier: list["ModifierTeil"] = field(default_factory=list)


@dataclass
class ModifierTeil:
    stl: Path            # Zylinder in den Koordinaten des Teil-STL
    einstellungen: dict[str, Any] = field(default_factory=dict)   # waende, fuellung
    name: str = "Modifier"


NAME_MAX = 60  # Zeichen; länger wird die Objektliste von Bambu Studio unübersichtlich


def kurzer_name(name: str, max_len: int = NAME_MAX) -> str:
    """Objektname für Bambu Studio aus dem Teilnamen (``show()``): vollständig, solange er kurz genug ist; sonst ohne
    die mittleren Baugruppen („Kugelschieber/…/Lenksperre links (Druck)“), dann nur der letzte Teil, zuletzt
    abgeschnitten mit „…“."""
    name = " ".join(str(name or "").split())
    if len(name) <= max_len:
        return name
    teile = [t for t in name.split("/") if t]
    if len(teile) > 2:
        kurz = f"{teile[0]}/…/{teile[-1]}"
        if len(kurz) <= max_len:
            return kurz
    letzter = teile[-1] if teile else name
    if len(letzter) <= max_len:
        return letzter
    return letzter[:max_len - 1].rstrip() + "…"


def objekt_namen(objekte: list[PlattenObjekt]) -> list[str]:
    """Namen der Objekte im 3MF in ihrer Reihenfolge (alle Platten nacheinander): ``kurzer_name`` des Teilnamens,
    ohne Namen der STL-Stamm; kommt ein Name mehrfach vor (Ersatzteile, ``anzahl=``), zählen die weiteren mit
    „(2)“, „(3)“ …"""
    namen = [kurzer_name(o.name) or Path(o.stl).stem for o in objekte]
    gesehen: dict[str, int] = {}
    out = []
    for n in namen:
        gesehen[n] = gesehen.get(n, 0) + 1
        out.append(n if gesehen[n] == 1 else f"{n} ({gesehen[n]})")
    return out


_OBJEKT_BLOCK = re.compile(r'<object id="\d+">.*?</object>', re.S)
_ASSEMBLE_NAME = re.compile(r'<metadata key="name" value="assemble_(\d+)"\s*/>')
_TEIL_NAME = re.compile(r'(<part id="\d+"[^>]*>\s*<metadata key="name" value=)"[^"]*"')
_MODIFIER_NAME = re.compile(r'(<part id="\d+" subtype="modifier_part">\s*<metadata key="name" value=)"[^"]*"')


def objekte_benennen(pfad_3mf: Path, namen: list[str], modifier_namen: list[list[str]] | None = None) -> int:
    """Teilnamen in ein von Bambu Studio geschriebenes 3MF setzen (nach ``--load-assemble-list``).

    Bambu Studio nennt die Objekte einer Montageliste „assemble_<n>“ (n = ``assemble_index``, hier die laufende
    Nummer über alle Platten) und die Teile darin nach der STL-Datei. Den Namen in der Objektliste liest es aus
    ``Metadata/model_settings.config`` (``<object>`` und ``<part>``, ``metadata key="name"``); ein ``name`` an den
    Objekten in ``3D/3dmodel.model`` übergeht es bei eigenen Projekten (geprüft mit 2.07.01.62). Geändert wird deshalb
    nur diese Datei, alles andere im Archiv bleibt Byte für Byte gleich. Zugeordnet wird über die Nummer in
    „assemble_<n>“, nicht über die Reihenfolge: die ``<object>``-Blöcke stehen nicht immer in der Reihenfolge der
    Montageliste (nachgeprüft über die Lage in der Matrix jedes Teils). Liefert die Zahl der umbenannten Objekte."""
    from xml.sax.saxutils import escape

    pfad_3mf = Path(pfad_3mf)
    with zipfile.ZipFile(pfad_3mf) as z:
        eintraege = [(i, z.read(i.filename)) for i in z.infolist()]
    cfg_name = "Metadata/model_settings.config"
    idx = next((k for k, (i, _) in enumerate(eintraege) if i.filename == cfg_name), None)
    if idx is None:
        return 0
    text = eintraege[idx][1].decode("utf-8")
    gezaehlt = [0]

    def ersetze(m: re.Match) -> str:
        block = m.group(0)
        a = _ASSEMBLE_NAME.search(block)
        if a is None:
            return block
        k = int(a.group(1))
        if not 1 <= k <= len(namen):
            return block
        neu = '"' + escape(namen[k - 1], {'"': "&quot;"}) + '"'
        block = block[:a.start()] + f'<metadata key="name" value={neu}/>' + block[a.end():]
        block = _TEIL_NAME.sub(lambda t: t.group(1) + neu, block, count=1)
        mn = (modifier_namen[k - 1] if modifier_namen and k - 1 < len(modifier_namen) else None) or []
        if mn:  # Modifier (Strang „Rest Druck“) in der Reihenfolge der Montageliste
            nummer = [0]

            def mod_name(t: re.Match) -> str:
                i = nummer[0]
                nummer[0] += 1
                if i >= len(mn):
                    return t.group(0)
                return t.group(1) + '"' + escape(mn[i], {'"': "&quot;"}) + '"'

            block = _MODIFIER_NAME.sub(mod_name, block)
        gezaehlt[0] += 1
        return block

    neu_text = _OBJEKT_BLOCK.sub(ersetze, text)
    if gezaehlt[0] == 0:
        return 0
    eintraege[idx] = (eintraege[idx][0], neu_text.encode("utf-8"))
    tmp = pfad_3mf.with_name(pfad_3mf.name + ".namen")
    with zipfile.ZipFile(tmp, "w") as z:
        for info, daten in eintraege:
            z.writestr(info, daten)
    tmp.replace(pfad_3mf)
    return gezaehlt[0]


def montageliste(platten: list[list[PlattenObjekt]], ordner: Path,
                 platten_namen: list[str] | None = None) -> Path:
    """Montageliste (``--load-assemble-list``) mit festen Lagen; gedrehte Teile als eigene STL-Kopien.
    ``platten_namen``: Namen der Platten in Bambu Studio (sonst „Platte 1“ …)."""
    gedreht: dict[tuple[str, float], Path] = {}
    liste: dict[str, Any] = {"plates": []}
    nr = 0
    for i, objekte in enumerate(platten, start=1):
        eintraege = []
        for o in objekte:
            nr += 1
            pfad = o.stl
            dx = dy = 0.0
            mitte_main = np.zeros(3)
            g = round(float(o.drehung) % 360.0, 3)
            if g not in (0.0, 360.0):
                key = (str(o.stl), g)
                tris, mitte = drehe_stl(lies_stl(o.stl), g)
                if key not in gedreht:
                    p = ordner / f"{o.stl.stem}_d{str(g).replace('.', '_')}.stl"
                    schreibe_stl_dreiecke(p, tris)
                    gedreht[key] = p
                pfad = gedreht[key]
                dx, dy = float(mitte[0]), float(mitte[1])
                mitte_main = np.asarray(mitte, dtype=np.float64)
            eintrag: dict[str, Any] = {"path": str(pfad), "count": 1, "filaments": [int(o.filament)],
                                       "assemble_index": [nr], "pos_x": [round(o.x + dx, 4)],
                                       "pos_y": [round(o.y + dy, 4)], "pos_z": [0]}
            pp = prozess_einstellungen(o.einstellungen)
            if pp:
                eintrag["print_params"] = pp
            eintraege.append(eintrag)
            # Modifier (Strang „Rest Druck“): Teil desselben Objekts (gleicher assemble_index), Typ modifier_part;
            # Bambu Studio behält die Lage des STL und verschiebt um pos, wie beim Teil (geprüft mit 2.07.01.62)
            for k, mt in enumerate(o.modifier, start=1):
                mpfad = mt.stl
                if g not in (0.0, 360.0):  # dieselbe Drehung und Verschiebung wie das Teil (drehe_stl)
                    mpfad = ordner / f"{mt.stl.stem}_o{nr}_d{str(g).replace('.', '_')}.stl"
                    w_ = math.radians(g)
                    c_, s_ = math.cos(w_), math.sin(w_)
                    Rm = np.array([[c_, -s_, 0], [s_, c_, 0], [0, 0, 1.0]])
                    pm = lies_stl(mt.stl).reshape(-1, 3) @ Rm.T - mitte_main
                    schreibe_stl_dreiecke(mpfad, pm.reshape(-1, 3, 3))
                eintraege.append({"path": str(mpfad), "count": 1, "filaments": [int(o.filament)],
                                  "subtype": "modifier_part", "assemble_index": [nr],
                                  "pos_x": [round(o.x + dx, 4)], "pos_y": [round(o.y + dy, 4)], "pos_z": [0],
                                  "print_params": prozess_einstellungen(mt.einstellungen)})
        pname = platten_namen[i - 1] if platten_namen and i <= len(platten_namen) else f"Platte {i}"
        liste["plates"].append({"plate_name": pname, "need_arrange": False, "objects": eintraege})
    pfad = ordner / "montageliste.json"
    pfad.write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
    return pfad


def slice_platten(platten: list[list[PlattenObjekt]], filamente: list[Filament], ordner: Path,
                  einstellungen: dict[str, Any] | None = None, abbruch: threading.Event | None = None,
                  drucker: str = "p1p-0.4", platte: str | None = None) -> list[dict[str, Any]]:
    """Platten mit festen Lagen slicen (je Platte Zeit und Filament)."""
    pr = schreibe_profile(ordner, global_einstellungen(einstellungen), filamente, drucker, platte)
    liste = montageliste(platten, ordner)
    res = ausfuehren([*_profil_args(pr), "--load-assemble-list", str(liste), "--slice", "0"], ordner, abbruch)
    for g in ordner.glob("*.gcode"):
        g.unlink(missing_ok=True)
    return _platten_ergebnis(res, pr.dichten)


def global_einstellungen(e: dict[str, Any] | None) -> dict[str, Any]:
    """Einstellungen für das Prozessprofil einer Platte (die Werte je Objekt kommen über ``print_params``)."""
    return {**(e or {"schicht_mm": 0.2}), "_global": True}


SLICER_WARNUNG_TEXT = {
    "floating cantilever": "schwebender Überhang (Teil neu ausrichten oder Stützen)",
    "floating regions": "schwebende Bereiche",
    "support": "Stützen nötig",
    "collision": "Kollision",
    "outside": "außerhalb der Platte",
}


def pruefe_slicen(pfad: Path, ordner: Path, abbruch: threading.Event | None = None) -> dict[str, Any]:
    """Das fertige 3MF so slicen, wie Kevin es in Bambu Studio öffnet (``--slice 0``, Projekt-Einstellungen aus der
    Datei), und die Meldungen auswerten: {"ok", "warnungen": [{"platte", "text", "art"}], "platten": [{"platte",
    "zeit_s", "g", "merkmale"}], "fehler"}. Der G-Code wird verworfen."""
    exe = programm()
    if exe is None:
        return {"ok": False, "warnungen": [], "platten": [], "fehler": "Bambu Studio nicht gefunden"}
    ordner.mkdir(parents=True, exist_ok=True)
    try:
        res = ausfuehren(["--slice", "0", str(pfad)], ordner, abbruch)
    except SlicerFehler as exc:
        return {"ok": False, "warnungen": [], "platten": [], "fehler": str(exc)}
    finally:
        for g in ordner.glob("*.gcode"):
            g.unlink(missing_ok=True)
    warnungen, platten = [], []
    for pl in res.get("sliced_plates") or []:
        nr = int(pl.get("id") or len(platten) + 1)
        w = str(pl.get("warning_message") or "").strip()
        if w:
            art = next((a for k, a in SLICER_WARNUNG_TEXT.items() if k in w.lower()), "Warnung")
            warnungen.append({"platte": nr, "text": w, "art": art})
        platten.append({"platte": nr, "zeit_s": round(float(pl.get("total_predication") or 0.0), 1),
                        "g": round(sum(float(f.get("total_used_g") or 0.0) for f in pl.get("filaments") or []), 2),
                        "merkmale": {k: round(float(v), 1) for k, v in (pl.get("feature_type_times") or {}).items()}})
    return {"ok": not warnungen, "warnungen": warnungen, "platten": platten, "fehler": None}


def export_3mf(platten: list[list[PlattenObjekt]], filament: Filament, ziel: Path, ordner: Path,
               einstellungen: dict[str, Any] | None = None, abbruch: threading.Event | None = None,
               drucker: str = "p1p-0.4", farbe: str | None = None, platte: str | None = None,
               platten_namen: list[str] | None = None) -> dict[str, Any]:
    """3MF der Platten eines Materials als Bambu-Projekt (ohne Slicen): Drucker-, Prozess- und Filamentprofil in
    ``Metadata/project_settings.config``, Einstellungen je Teil in ``Metadata/model_settings.config``; danach zur
    Kontrolle mit ``--info`` geladen. Die Objekte tragen die Teilnamen (``objekt_namen``, gesetzt mit
    ``objekte_benennen``; Bambu Studio selbst nennt sie „assemble_1“ …), die Platten ``platten_namen``.
    Liefert {"pfad", "objekte", "geprueft", "namen", "benannt"}.

    Ein Filament je Datei: Bambu Studio 2.07 schreibt Projekte mit mehreren ``--load-filaments`` so, dass es sie beim
    erneuten Laden nur mit Filament 1 (und nach Ergänzen der Listen gar nicht) slicen kann; der P1P ohne AMS druckt
    ohnehin ein Material je Platte."""
    pr = schreibe_profile(ordner, global_einstellungen(einstellungen), [filament], drucker, platte)
    if farbe and not (isinstance(filament, dict) and filament.get("farbe")):  # Farbe des Filaments geht vor
        d = json.loads(pr.filamente[0].read_text(encoding="utf-8"))
        d["filament_colour"] = [farbe]
        d["default_filament_colour"] = [farbe]
        pr.filamente[0].write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    for liste_ in platten:
        for o in liste_:
            o.filament = 1
    liste = montageliste(platten, ordner, platten_namen)
    name = "platten.3mf"
    (ordner / name).unlink(missing_ok=True)
    ausfuehren([*_profil_args(pr), "--load-assemble-list", str(liste), "--export-3mf", name], ordner, abbruch)
    erzeugt = ordner / name
    if not erzeugt.exists():
        raise SlicerFehler("Bambu Studio hat kein 3MF geschrieben")
    alle = [o for liste_ in platten for o in liste_]
    namen = objekt_namen(alle)
    benannt = objekte_benennen(erzeugt, namen, [[mt.name for mt in o.modifier] for o in alle])
    objekte = pruefe_3mf(erzeugt, ordner / "pruefung", abbruch)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(erzeugt, ziel)
    modifier = sum(len(o.modifier) for o in alle)
    return {"pfad": str(ziel), "objekte": objekte, "geprueft": True, "namen": namen, "benannt": benannt,
            "modifier": modifier}


def pruefe_3mf(pfad: Path, ordner: Path, abbruch: threading.Event | None = None) -> int:
    """3MF in Bambu Studio laden (``--info``); Anzahl der Objekte oder ``SlicerFehler``."""
    exe = programm()
    if exe is None:
        raise SlicerFehler("Bambu Studio nicht gefunden")
    ordner.mkdir(parents=True, exist_ok=True)
    with _sperre(abbruch):
        r = subprocess.run(["nice", "-n", "15", str(exe), "--info", str(pfad)], cwd=str(ordner), capture_output=True,
                           text=True, timeout=120)
    n = len(re.findall(r"^number_of_facets\s*=", r.stdout, flags=re.M))
    if r.returncode != 0 or n == 0:
        raise SlicerFehler(f"Bambu Studio kann das 3MF nicht laden ({r.returncode}): {r.stdout[-300:]}")
    return n


def arbeitsordner(prefix: str = "lauf") -> Path:
    basis = cache_ordner() / "tmp"
    basis.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix + "-", dir=str(basis)))


def schluessel(*teile: Any) -> str:
    return hashlib.sha1(json.dumps(teile, sort_keys=True, default=str).encode()).hexdigest()[:20]
