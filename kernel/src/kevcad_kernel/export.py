"""Export der Teile des aktuellen Stands nach ``<projekt>/output/``: STEP (Baugruppe mit Namen und Farben), STL,
3MF (je Teil ein Objekt mit Name und Farbe) und GLB.

Grundlage sind die BRep-Formen aus der Szene (refs.PartRecord), also exakt das, was zuletzt gezeigt wurde. Skizzen aus
``execute`` (``Skizze/…``) werden nur exportiert, wenn sie ausdrücklich in ``parts`` stehen.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

from build123d import Color, Compound, Shape, export_gltf, export_step, export_stl
from build123d.mesher import Mesher
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

from kevcad_kernel.refs import PartRecord
from kevcad_kernel.tessellate import mesh_quality

FORMATS = ("step", "stl", "3mf", "glb")
EXTENSIONS = {"step": "step", "stl": "stl", "3mf": "3mf", "glb": "glb"}


class ExportError(ValueError):
    pass


def safe_name(name: str) -> str:
    s = re.sub(r"[^\w\-. äöüÄÖÜß]+", "_", name, flags=re.UNICODE).strip(" ._")
    return s or "modell"


def _leaf(rec: PartRecord, label: str) -> Shape:
    """Neue Hülle um die Form (die zwischengespeicherte Form der Szene bleibt unverändert)."""
    shape = Shape.cast(rec.shape.wrapped)
    shape.label = label
    shape.color = Color(*rec.color)
    return shape


def _has_solid(shape: Shape) -> bool:
    return TopExp_Explorer(shape.wrapped, TopAbs_SOLID).More()


def assembly(records: list[PartRecord], root_label: str) -> Compound:
    """Baum aus den Teilnamen ("Halter/Lasche" → Gruppe Halter mit Kind Lasche)."""
    tree: dict[str, Any] = {}
    for rec in records:
        node = tree
        parts = rec.name.split("/")
        for seg in parts[:-1]:
            node = node.setdefault(seg, {})
        node[parts[-1] if parts[-1] not in node else rec.name] = rec

    def build(label: str, node: dict[str, Any]) -> Compound:
        children = []
        for key, value in node.items():
            children.append(build(key, value) if isinstance(value, dict) else _leaf(value, key))
        return Compound(label=label, children=children)

    return build(root_label, tree)


def _deflection(records: list[PartRecord]) -> tuple[float, float]:
    """Feinere Vernetzung als im Viewer (für Druck und Weitergabe): ein Viertel der Anzeige-Abweichung, 1 µm bis 0,05 mm."""
    mins = [min(r.bbox["min"][i] for r in records) for i in range(3)]
    maxs = [max(r.bbox["max"][i] for r in records) for i in range(3)]
    q = mesh_quality(*(b - a for a, b in zip(mins, maxs)), 0.1) / 4
    return max(0.001, min(0.05, q)), 0.1


def export_records(records: list[PartRecord], formats: list[str], out_dir: Path, base_name: str) -> tuple[list[str], list[str]]:
    """Schreibt die Dateien. Rückgabe (absolute Pfade, Warnungen). Unbekanntes Format → ExportError."""
    fmts = []
    for f in formats or []:
        key = str(f).lower().lstrip(".")
        key = "step" if key == "stp" else key
        if key not in FORMATS:
            raise ExportError(f"Format {f!r} unbekannt (erlaubt: {', '.join(FORMATS)}).")
        if key not in fmts:
            fmts.append(key)
    if not fmts:
        raise ExportError("Kein Format angegeben (erlaubt: step, stl, 3mf, glb).")
    if not records:
        raise ExportError("Keine Teile zum Exportieren (erst rechnen).")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = safe_name(base_name)
    lin, ang = _deflection(records)
    files: list[str] = []
    notes: list[str] = []
    solids = [r for r in records if _has_solid(r.shape)]
    for fmt in fmts:
        path = (out_dir / f"{base}.{EXTENSIONS[fmt]}").resolve()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                if fmt == "step":
                    ok = export_step(assembly(records, base), str(path))
                elif fmt == "glb":
                    ok = export_gltf(assembly(records, base), str(path), binary=True, linear_deflection=lin,
                                     angular_deflection=ang)
                elif fmt == "stl":
                    if not solids:
                        notes.append("STL: keine Körper (nur Flächen oder Kanten), nichts geschrieben")
                        continue
                    ok = export_stl(Compound([_leaf(r, r.name) for r in solids]), str(path), tolerance=lin,
                                    angular_tolerance=ang)
                else:  # 3mf
                    if not solids:
                        notes.append("3MF: keine Körper (nur Flächen oder Kanten), nichts geschrieben")
                        continue
                    mesher = Mesher()
                    for r in solids:
                        mesher.add_shape(_leaf(r, r.name), linear_deflection=lin, angular_deflection=ang)
                    mesher.write(str(path))
                    ok = path.exists()
            for w in caught[:5]:
                notes.append(f"{fmt.upper()}: {w.message}")
            if ok is False or not path.exists():
                notes.append(f"{fmt.upper()}: Datei wurde nicht geschrieben")
                continue
            files.append(str(path))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{fmt.upper()}: {type(exc).__name__}: {exc}")
    skipped = len(records) - len(solids)
    if skipped and any(f in fmts for f in ("stl", "3mf")) and solids:
        notes.append(f"STL/3MF: {skipped} Teil(e) ohne Körper ausgelassen")
    return files, notes
