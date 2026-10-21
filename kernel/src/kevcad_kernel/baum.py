"""Baugruppen (Compound mit benannten Kindern): Kinder an ihrer echten Lage, Baum speichern und wiederherstellen.

build123d verschiebt bei ``Pos(...) * baugruppe`` nur die Gesamtform; ``baugruppe.children`` bleiben Kopien an der
alten Stelle. ``kinder()`` liefert die Kinder deshalb aus der Topologie der Gesamtform (gleiche Reihenfolge wie
``children``) mit Name, Farbe und Material der Vorlage. ``baum_meta``/``baum_bauen`` speichern den Baum neben einer
BREP-Datei (die nur Topologie kennt) und bauen ihn wieder auf.

Nur im Rechenprozess und beim Import im Elternprozess (lädt build123d).
"""

from __future__ import annotations

from typing import Any

VORLAGE = "_kevcad_vorlage"


def teilformen(wrapped: Any) -> list[Any]:
    """Direkte Unterformen einer TopoDS-Form an ihrer Lage (TopoDS_Iterator)."""
    from OCP.TopoDS import TopoDS_Iterator

    out = []
    if wrapped is None:
        return out
    it = TopoDS_Iterator(wrapped)
    while it.More():
        out.append(it.Value())
        it.Next()
    return out


def _cast(wrapped: Any):
    from build123d import Shape

    return Shape.cast(wrapped)


def _copy_attrs(src: Any, dst: Any) -> None:
    for attr in ("label", "color"):
        try:
            value = getattr(src, attr, None)
            if value is not None:
                setattr(dst, attr, value)
        except Exception:  # noqa: BLE001
            pass
    try:
        mat = getattr(src, "material", None)
        if mat is not None:
            dst.material = mat
    except Exception:  # noqa: BLE001
        pass
    for attr in ("kevcad_grob",):
        if hasattr(src, attr):
            setattr(dst, attr, getattr(src, attr))


def kinder(obj: Any) -> list[Any]:
    """Kinder einer Baugruppe an der Lage der Gesamtform. Passt die Topologie nicht zu ``children`` (andere Anzahl),
    gelten die ``children`` unverändert."""
    vorlage = getattr(obj, VORLAGE, None) or obj
    kids = list(getattr(vorlage, "children", ()) or ())
    if not kids:
        return []
    subs = teilformen(getattr(obj, "wrapped", None))
    if len(subs) != len(kids):
        return kids
    out = []
    for kid, sub in zip(kids, subs):
        try:
            new = _cast(sub)
        except Exception:  # noqa: BLE001
            return kids
        _copy_attrs(kid, new)
        if list(getattr(kid, "children", ()) or ()):
            setattr(new, VORLAGE, kid)
        out.append(new)
    return out


def _color(shape: Any) -> list[float] | None:
    try:
        c = shape.color
        return [round(float(x), 5) for x in c] if c is not None else None
    except Exception:  # noqa: BLE001
        return None


def baum_meta(shape: Any) -> dict[str, Any]:
    """Name, Farbe und Kinder (rekursiv, Reihenfolge der Topologie) als JSON-taugliches Objekt."""
    out: dict[str, Any] = {"label": str(getattr(shape, "label", "") or ""), "color": _color(shape)}
    kids = kinder(shape)
    if kids:
        out["kinder"] = [baum_meta(k) for k in kids]
    return out


def baum_bauen(wrapped: Any, meta: dict[str, Any] | None):
    """build123d-Form aus einer TopoDS-Form und ``baum_meta``: Blätter als Solid/Shell/…, Baugruppen als Compound mit
    benannten Kindern (neue Objekte, gleiche Topologie)."""
    from build123d import Color, Compound

    meta = meta or {}
    kids_meta = meta.get("kinder") or []
    subs = teilformen(wrapped) if kids_meta else []
    if kids_meta and len(subs) == len(kids_meta):
        children = [baum_bauen(sub, km) for sub, km in zip(subs, kids_meta)]
        shape = Compound(children=children)
    else:
        shape = _cast(wrapped)
    if meta.get("label"):
        shape.label = meta["label"]
    if meta.get("color"):
        try:
            shape.color = Color(*meta["color"])
        except Exception:  # noqa: BLE001
            pass
    return shape


def transformieren(shape: Any, location: Any = None, trsf: Any = None):
    """Form verschieben/drehen (``location``) oder allgemein transformieren (``trsf``, z. B. Skalieren) und den Baum
    mit Namen und Farben erhalten."""
    meta = baum_meta(shape)
    wrapped = shape.wrapped
    if trsf is not None:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

        wrapped = BRepBuilderAPI_Transform(wrapped, trsf, True).Shape()
    if location is not None:
        wrapped = wrapped.Moved(location.wrapped)
    out = baum_bauen(wrapped, meta)
    try:
        if getattr(shape, "material", None) is not None:
            out.material = shape.material
    except Exception:  # noqa: BLE001
        pass
    return out


def markieren(shape: Any, attr: str, value: Any) -> None:
    """Attribut an der Form und allen Kindern setzen (z. B. grobe Tessellierung)."""
    setattr(shape, attr, value)
    for k in list(getattr(shape, "children", ()) or ()):
        markieren(k, attr, value)
