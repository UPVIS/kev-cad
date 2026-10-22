"""Topologieoptimierung in model.py: ``from kevcad import topologie`` (PLAN-TOPOLOGIE.md).

```python
from kevcad import lager, show, topologie

halter = lager.druckteil(form, "Halter", material="petg")
halter = topologie.optimieren(halter, szenario="Ball drückt 100 N", behalten=0.4, ueberhang=True)
show(Pos(0, 0, 10) * halter, "Halter")
```

- ``optimieren`` gibt den optimierten Körper zurück, sobald es ihn gibt (``<projekt>/topologie/<teil>-<schlüssel>.brep``),
  sonst das Ausgangsteil unverändert. Fehlt das Ergebnis, rechnet Kev CAD es nach dem Lauf im Hintergrund (eigener
  Prozess, etwa eine Minute) und startet danach den Lauf neu; der Lauf selbst wartet nie darauf.
- Lager und Lasten kommen aus der Statik (``kevcad.statik``): Kontaktflächen zu tragenden Nachbarn, ``st.last`` auf
  dem Teil, Kraftpaare, Lagerkräfte von Stäben. ``szenario``: Name des Lastfalls (ohne Angabe der mit der größten
  Ausnutzung des Teils).
- ``behalten``: Volumenanteil, der bleibt (0,4 = 40 %; Schutzzonen zählen mit). ``ueberhang=True``: keine neuen
  Überhänge über 45° in Druckrichtung (Bambu Lab P1P). ``steg``: kleinste Stegbreite in Linienbreiten (6 × 0,42 mm).
  ``fein=True``: etwa dreimal so viele Voxel. ``bett=True``: geschlossene Bodenhaut in Stegdicke.
- Schutzzonen von selbst: Bohrungen mit Wandring, Gewindeeinsätze mit Mindestwand, Last- und Klemmflächen
  (``bohrungen``, ``einsaetze``, ``kontakt`` abschaltbar); dazu ``schutz=[form, fläche, …]``: build123d-Körper (was
  darin liegt, bleibt) oder Flächen des Teils (eine Haut darunter bleibt), in den Koordinaten des Teils.
- Der Körper ist ein gewöhnliches Druckteil (Stückliste, Druckprüfung, Export); Masse und Preis folgen dem neuen
  Volumen. Näherung, kein Festigkeitsnachweis: Kev CAD rechnet das Ergebnis mit der Festkörper-FEM nach (MCP
  ``topologie_ergebnis``, App: Abschnitt „Optimieren“).
- ``automatisch=False``: nichts im Hintergrund starten, nur ein vorhandenes Ergebnis laden.

Außerhalb des Kernels gibt ``optimieren`` das Teil unverändert zurück.
"""

from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path
from typing import Any

__all__ = ["optimieren", "aus_datei"]


def _zeile() -> int | None:
    frame = sys._getframe(2)
    while frame is not None and frame.f_code.co_filename.endswith("topologie.py"):
        frame = frame.f_back
    return frame.f_lineno if frame is not None and frame.f_code.co_filename.endswith("model.py") else None


def _brep_text(shape: Any, ohne_lage: bool = False) -> str:
    from OCP.BRepTools import BRepTools
    from OCP.TopLoc import TopLoc_Location

    import io

    s = shape.wrapped if hasattr(shape, "wrapped") else shape
    if ohne_lage:
        s = s.Located(TopLoc_Location())
    bio = io.BytesIO()
    BRepTools.Write_s(s, bio)
    return base64.b64encode(bio.getvalue()).decode("ascii")


def _schutz_liste(schutz: Any) -> list[dict[str, Any]]:
    from build123d import Face, Shape, ShapeList

    if schutz is None:
        return []
    if isinstance(schutz, (Shape, ShapeList)) and not isinstance(schutz, (list, tuple)):
        schutz = [schutz]
    out = []
    for s in schutz:
        if isinstance(s, ShapeList):
            out += _schutz_liste(list(s))
            continue
        if not isinstance(s, Shape):
            raise ValueError(f"topologie.optimieren: schutz braucht build123d-Körper oder Flächen, nicht "
                             f"{type(s).__name__}")
        art = "flaeche" if isinstance(s, Face) else "form"
        b = _brep_text(s)
        out.append({"art": art, "brep": b, "hash": hashlib.sha1(b.encode()).hexdigest()[:16]})
    return out


def optimieren(teil: Any, szenario: str | None = None, behalten: float = 0.4, schutz: Any = None,
               ueberhang: bool = False, fein: bool = False, steg: float = 6, bett: bool = False,
               bohrungen: bool = True, einsaetze: bool = True, kontakt: bool = True, iterationen: int = 60,
               automatisch: bool = True) -> Any:
    """Topologieoptimiertes Druckteil (siehe Moduldoku): das Ergebnis, sobald es berechnet ist, sonst ``teil``."""
    import kevcad
    from kevcad.lager import LagerError

    if kevcad._hooks.get("lager") is None:  # außerhalb des Kernels
        return teil
    piece = getattr(teil, "kevcad_druckteil", None)
    if piece is None:
        raise LagerError("topologie.optimieren: nur Druckteile aus lager.druckteil(…) lassen sich optimieren (das "
                         "Ergebnis vor dem Verschieben übergeben, also vor Pos(…) * teil)")
    from kevcad_kernel.topologie import einstellungen, form_signatur, modell_schluessel
    from kevcad_kernel.topologie.ergebnis import aufruf_schreiben, finde, lies_brep, lies_json

    einst = einstellungen(behalten=behalten, ueberhang=ueberhang, fein=fein, steg=steg, bett=bett,
                          bohrungen=bohrungen, einsaetze=einsaetze, kontakt=kontakt, iterationen=iterationen)
    sl = _schutz_liste(schutz)
    name = piece.name
    form = form_signatur(teil.wrapped)
    schluessel = modell_schluessel(form, name, szenario, einst, [s["hash"] for s in sl])
    projekt = Path.cwd()
    pf = finde(projekt, name, schluessel)
    vorhanden = pf["brep"].exists()
    try:
        aufruf_schreiben(projekt, {"schluessel": schluessel, "teil": name, "form": form, "szenario": szenario,
                                   "einstellungen": einst, "schutz": [{k: v for k, v in s.items() if k != "hash"}
                                                                      for s in sl],
                                   "zeile": _zeile(), "automatisch": bool(automatisch), "vorhanden": vorhanden,
                                   "form_brep": _brep_text(teil, ohne_lage=True)})
    except OSError:
        pass
    warn = kevcad._hooks.get("warn")
    if not vorhanden:
        if warn is not None and automatisch:
            warn(f"Topologie: {name} wird nach dem Lauf im Hintergrund optimiert (behalten "
                 f"{einst['behalten'] * 100:.0f} %); bis dahin zeigt das Modell das Ausgangsteil")
        return teil
    from build123d import Shape

    try:
        roh = lies_brep(pf["brep"])
    except Exception as exc:  # noqa: BLE001
        if warn is not None:
            warn(f"Topologie: Ergebnis von {name} nicht lesbar ({exc}); das Modell zeigt das Ausgangsteil")
        return teil
    roh.Location(teil.wrapped.Location())
    res = Shape.cast(roh)
    meta = lies_json(pf["json"]) or {}
    _uebernehmen(piece, teil, res, meta)
    return res


def _uebernehmen(piece: Any, teil: Any, res: Any, meta: dict[str, Any]) -> None:
    """Das Stück des Druckteils auf den neuen Körper umstellen (Stückliste, Masse, Preis, Zuordnung im Lauf)."""
    from kevcad_kernel.bom import _solids

    res.label = getattr(teil, "label", None) or piece.name
    try:
        res.color = teil.color
    except Exception:  # noqa: BLE001
        pass
    vol = float(res.volume)
    if piece.volume and piece.kg:
        piece.kg = piece.kg * vol / float(piece.volume)
        if piece.preis is not None:
            piece.preis = piece.preis * vol / float(piece.volume)
    piece.volume = vol
    bb = res.bounding_box()
    piece.size = [round(float(bb.size.X), 3), round(float(bb.size.Y), 3), round(float(bb.size.Z), 3)]
    piece.shape = res.wrapped
    piece.solids = _solids(res)
    res.kevcad_druckteil = piece
    res.kevcad_topologie = {k: meta.get(k) for k in ("schluessel", "teil", "szenarien", "einstellungen", "lastfall")}


def aus_datei(pfad: str | Path, name: str, material: str, **druckteil: Any) -> Any:
    """Druckteil aus einer Datei im Projekt (``.brep`` aus der Topologie, binär oder Text, oder ``.step``), etwa ein
    fest übernommenes Ergebnis: ``topologie.aus_datei("topologie/Halter-1a2b3c4d5e6f.brep", "Halter", "petg")``.
    Weitere Angaben wie bei ``lager.druckteil`` (``ausrichtung``, ``zweck`` …)."""
    from build123d import Shape, import_step

    from kevcad import lager

    p = Path(pfad)
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        raise lager.LagerError(f"topologie.aus_datei: {pfad} gibt es nicht")
    if p.suffix.lower() in (".step", ".stp"):
        form = import_step(str(p))
    else:
        try:
            from kevcad_kernel.topologie.ergebnis import lies_brep

            form = Shape.cast(lies_brep(p))
        except Exception:  # noqa: BLE001 - Text-BREP
            from build123d import import_brep

            form = import_brep(str(p))
    return lager.druckteil(form, name, material=material, **druckteil)
