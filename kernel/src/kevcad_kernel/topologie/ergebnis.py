"""Ergebnis der Topologieoptimierung als Körper und Dateien.

- **Körper aus dem Netz:** Das geglättete, ausgedünnte Dreiecksnetz wird mit ``BRepBuilderAPI_MakeShapeOnMesh`` eine
  B-Rep mit einer ebenen Dreiecksfläche je Dreieck (gemeinsame Kanten, geschlossene Schale, Volumenkörper). Das geht in
  Millisekunden, ist exakt so groß wie das Netz und für Kev CAD ein gewöhnlicher Körper: Stückliste, Prüfung,
  Druckvorschau, Export (STEP, STL, 3MF) und Festkörper verstehen ihn ohne Sonderweg. Flächen bleiben eben, die Form ist
  so glatt wie das Netz (etwa 4 000 bis 12 000 Dreiecke).
- **Dateien im Projekt:** ``<projekt>/topologie/<teil>-<schlüssel>.brep`` (BRep binär, Teilkoordinaten wie die Form
  in model.py) und ``.json`` (Einstellungen, Kennzahlen vorher und nachher, Lastfall). model.py lädt den Körper über
  ``kevcad.topologie.optimieren`` bzw. ``lager.druckteil_aus_datei``; die Dateien gehören zu den Versionen.
- **Aufrufe aus model.py** (``.kevcad/topologie/aufrufe/<schlüssel>.json``, nicht in den Versionen): Welche Teile das
  Modell optimiert haben will; die Laufzeit rechnet fehlende Ergebnisse nach dem Lauf im Hintergrund.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

ORDNER = "topologie"
AUFRUFE = Path(".kevcad") / "topologie" / "aufrufe"


def slug(text: str) -> str:
    s = text.strip().replace("/", " ").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-._")
    return s[:60] or "teil"


def dateiname(teil: str, schluessel: str) -> str:
    return f"{slug(teil)}-{schluessel[:12]}"


def pfade(projekt: str | Path, teil: str, schluessel: str) -> dict[str, Path]:
    basis = Path(projekt) / ORDNER / dateiname(teil, schluessel)
    return {"brep": basis.with_suffix(".brep"), "json": basis.with_suffix(".json")}


def solid_aus_netz(punkte: np.ndarray, dreiecke: np.ndarray) -> Any:
    """TopoDS_Solid aus einem geschlossenen, nach außen orientierten Dreiecksnetz."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeShapeOnMesh, BRepBuilderAPI_MakeSolid
    from OCP.BRepGProp import BRepGProp
    from OCP.gp import gp_Pnt
    from OCP.GProp import GProp_GProps
    from OCP.Poly import Poly_Triangle, Poly_Triangulation
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Shell

    p = np.asarray(punkte, float)
    d = np.asarray(dreiecke, np.int64)
    tri = Poly_Triangulation(len(p), len(d), False)
    for i, q in enumerate(p):
        tri.SetNode(i + 1, gp_Pnt(float(q[0]), float(q[1]), float(q[2])))
    for i, t in enumerate(d):
        tri.SetTriangle(i + 1, Poly_Triangle(int(t[0]) + 1, int(t[1]) + 1, int(t[2]) + 1))
    mk = BRepBuilderAPI_MakeShapeOnMesh(tri)
    mk.Build()
    sh = mk.Shape()
    bb = BRep_Builder()
    schale = TopoDS_Shell()
    bb.MakeShell(schale)
    ex = TopExp_Explorer(sh, TopAbs_FACE)
    n = 0
    while ex.More():
        bb.Add(schale, ex.Current())
        n += 1
        ex.Next()
    if n == 0:
        raise ValueError("Netz ohne Flächen")
    schale.Closed(True)
    solid = BRepBuilderAPI_MakeSolid(schale).Solid()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, props) if hasattr(BRepGProp, "VolumeProperties_s") else \
        BRepGProp.VolumeProperties(solid, props)
    if props.Mass() < 0:
        solid.Reverse()
    return solid


def schreibe_brep(shape: Any, pfad: str | Path) -> None:
    from OCP.BinTools import BinTools, BinTools_FormatVersion

    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    bio = io.BytesIO()
    BinTools.Write_s(shape, bio, False, False, BinTools_FormatVersion.BinTools_FormatVersion_CURRENT)
    tmp = pfad.with_name(pfad.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(bio.getvalue())
    os.replace(tmp, pfad)


def lies_brep(pfad: str | Path) -> Any:
    from OCP.BinTools import BinTools
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    BinTools.Read_s(shape, io.BytesIO(Path(pfad).read_bytes()))
    _ = BRep_Builder
    return shape


def schreibe_json(pfad: str | Path, daten: dict[str, Any]) -> None:
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    os.replace(tmp, pfad)


def lies_json(pfad: str | Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def aufruf_schreiben(projekt: str | Path, daten: dict[str, Any]) -> Path:
    """Aufruf aus model.py vermerken (je Modellschlüssel eine Datei; ``zeit`` zeigt, ob er zum letzten Lauf gehört)."""
    pfad = Path(projekt) / AUFRUFE / f"{daten['schluessel']}.json"
    schreibe_json(pfad, {**daten, "zeit": time.time()})
    return pfad


def aufrufe(projekt: str | Path, seit: float | None = None) -> list[dict[str, Any]]:
    ordner = Path(projekt) / AUFRUFE
    out = []
    if not ordner.is_dir():
        return out
    for p in sorted(ordner.glob("*.json")):
        d = lies_json(p)
        if not d:
            continue
        if seit is not None and float(d.get("zeit") or 0.0) < seit:
            continue
        d["_datei"] = str(p)
        out.append(d)
    return out
