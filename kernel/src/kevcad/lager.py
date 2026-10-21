"""Lagerteile in model.py: ``from kevcad import lager`` (Vertrag in KATALOG.md).

```python
rohr = lager.teil("vierkantrohr", a=40, s=3)          # nach Art und Maßen (genau, sonst Fehler mit Vorschlägen)
rohr = lager.teil("rohr-en10220-42.4x2.0")            # nach id
treffer = lager.suche("vierkantrohr 40")              # Liste von Lagerteilen

bein = rohr.verbauen(laenge=882, name="Gestell/Bein vorn links", gehrung=(0, 0))
show(Pos(0, 0, 0) * bein, "Gestell/Bein vorn links")  # gleicher Name wie in verbauen

platte = lager.teil("platte", s=18, material="multiplex-birke")
deckel = platte.verbauen(breite=800, tiefe=600, name="Deckel")   # oder form=<Sketch/Face>
schraube = lager.teil("schraube", norm="iso4762", groesse="M8-1.25")
s1 = schraube.verbauen(laenge=60, name="Schrauben/M8x60 1")
```

- Stangenware liegt entlang +Z ab z = 0, der Querschnitt mittig (Mitte des Hüllrechtecks auf der Achse). ``laenge``
  ist das Zuschnittmaß an der längsten Kante, ``gehrung=(anfang, ende)`` in Grad um die lokale X-Achse: positiv hält
  die Kante bei +Y lang, negativ die bei -Y. ``drehung`` (Grad um Z) dreht den Querschnitt vorher, etwa damit die
  Gehrung über die andere Seite eines Flachstahls geht.
- Platten liegen in der XY-Ebene ab z = 0, mittig um den Ursprung.
- Schrauben, Muttern und Scheiben kommen aus bd_warehouse (Schraubenkopf auf z = 0, Schaft nach -Z), ohne Gewinde
  (``simple=False`` für Gewinde).
- Jedes ``verbauen`` erscheint in der Stückliste, auch wenn das Teil danach gebohrt oder gekürzt wird.
- Selbst konstruierte Teile, die gedruckt werden: ``lager.druckteil(form, "Halter/Schelle", material="petg")``. Das
  Material muss freigegeben sein und im Katalog ``"druckbar": true`` haben.
- Inventar-Regel (Standard, abschaltbar nur von Kevin in kevcad.json): Jedes gezeigte Teil stammt aus ``verbauen``
  oder ``druckteil``; Materialien nur aus dem Katalog. Vorgeschlagene Einträge (von stock_define/material_define)
  lassen sich erst nach Kevins Freigabe verbauen.
"""

from __future__ import annotations

import difflib
import math
from pathlib import Path
from typing import Any

import kevcad
from kevcad_kernel.catalog import (
    ARTEN,
    KLEINTEILE,
    OPTIONAL_MASSE,
    REQUIRED_MASSE,
    STANGENWARE,
    TEXT_MASSE,
    WARTET,
    Catalog,
    dim_text,
    fold,
    is_free,
    number,
)

__all__ = ["LagerError", "MaterialError", "Lagerteil", "teil", "suche", "druckteil", "katalog", "VERFAHREN"]

MAX_GEHRUNG = 80.0
VERFAHREN = ("3d-druck", "harzdruck")

_fallback: Catalog | None = None


class LagerError(ValueError):
    """Lagerteil nicht gefunden, mehrdeutig, nicht freigegeben oder falsch verbaut (Meldung mit Vorschlägen)."""


class MaterialError(LagerError):
    """Material nicht im Katalog, nicht freigegeben oder nicht druckbar."""


def released_material(name: str, *, druckbar: bool = False, cat: Catalog | None = None) -> dict[str, Any]:
    """Freigegebenes Katalogmaterial nach id oder Alias; sonst MaterialError mit Vorschlägen."""
    cat = cat or katalog()
    mat = cat.find_material(name, include_proposed=True)
    if mat is None:
        tips = cat.material_suggestions(str(name))
        raise MaterialError(f"Material {name!r} gibt es im Katalog nicht"
                            + (f". Meinten Sie {', '.join(repr(t) for t in tips)}?" if tips else "")
                            + " Freigegebene Materialien zeigt material_list; fehlt eins, Kevin fragen.")
    if not is_free(mat):
        raise MaterialError(f"Material {mat['id']!r} ist vorgeschlagen und {WARTET}.")
    if druckbar and mat.get("druckbar") is not True:
        printable = [m["id"] for m in cat.printable_materials()]
        raise MaterialError(f"Material {mat['id']!r} ist nicht druckbar (im Katalog fehlt \"druckbar\": true)."
                            + (f" Druckbar: {', '.join(printable)}." if printable else " Es gibt noch kein druckbares "
                               "Material im Katalog; Kevin fragen."))
    return mat


def katalog() -> Catalog:
    """Katalog des laufenden Projekts (im Kernel), sonst Standardordner und katalog.json im aktuellen Ordner."""
    global _fallback
    hook = kevcad._hooks.get("catalog")
    if hook is not None:
        return hook()
    if _fallback is None:
        _fallback = Catalog(project=Path.cwd())
    return _fallback


def _register(piece: Any, shape: Any) -> None:
    hook = kevcad._hooks.get("lager")
    if hook is not None:
        hook(piece, shape)


def _warn(text: str) -> None:
    hook = kevcad._hooks.get("warn")
    if hook is not None:
        hook(text)


def _masse_text(entry: dict[str, Any]) -> str:
    return ", ".join(f"{k}={dim_text(number(v)) if number(v) is not None else v}"
                     for k, v in (entry.get("masse") or {}).items())


class Lagerteil:
    """Ein Eintrag aus dem Katalog mit seinem Material. ``verbauen(...)`` liefert das build123d-Teil."""

    def __init__(self, entry: dict[str, Any], material: dict[str, Any] | None) -> None:
        self.eintrag = entry
        self.id: str = entry["id"]
        self.art: str = entry["art"]
        self.name: str = entry.get("name") or entry["id"]
        self.norm: str | None = entry.get("norm")
        self.masse: dict[str, Any] = dict(entry.get("masse") or {})
        self.material_id: str = entry.get("material", "")
        self.material: dict[str, Any] | None = material
        self.ebene: str = entry.get("ebene", "mitgeliefert")
        self.stangenlaenge: float | None = number(entry.get("stangenlaenge"))
        self.preis: dict[str, Any] = dict(entry.get("preis") or {})

    # -- Werte ---------------------------------------------------------------------------------------------------------

    @property
    def material_name(self) -> str:
        return (self.material or {}).get("name") or self.material_id

    @property
    def farbe(self) -> str | None:
        return (self.material or {}).get("farbe")

    @property
    def kg_je_m(self) -> float | None:
        from kevcad_kernel.profiles import kg_je_m

        return kg_je_m(self.eintrag, self.material)

    @property
    def querschnitt_mm2(self) -> float | None:
        from kevcad_kernel.profiles import flaeche_mm2

        return flaeche_mm2(self.art, self.masse) if self.art in STANGENWARE else None

    def querschnitt(self, drehung: float = 0):
        """Querschnitt als build123d-Fläche in der XY-Ebene (nur Stangenware)."""
        if self.art not in STANGENWARE:
            raise LagerError(f"{self.name}: nur Stangenware hat einen Querschnitt (art {self.art!r})")
        from build123d import Rot

        from kevcad_kernel.profiles import querschnitt

        face = querschnitt(self.art, self.masse)
        return Rot(0, 0, drehung) * face if drehung else face

    def __repr__(self) -> str:
        wait = "" if is_free(self.eintrag) else ", vorgeschlagen"
        return f"<Lagerteil {self.id!r}: {self.name}, {self.material_name}, {self.ebene}{wait}>"

    # -- Verbauen ------------------------------------------------------------------------------------------------------

    def verbauen(self, laenge: float | None = None, name: str | None = None, gehrung: Any = (0, 0), *,
                 breite: float | None = None, tiefe: float | None = None, form: Any = None, drehung: float = 0,
                 simple: bool = True):
        """build123d-Teil mit label (= name), Farbe des Materials und Stücklistenzeile. Siehe Moduldoku."""
        from build123d import Color

        from kevcad_kernel.bom import Piece, piece_values

        label = str(name).strip().strip("/").replace("#", "-") if name is not None and str(name).strip() else self.name
        if self.material is None:
            raise LagerError(f"{self.name}: Material {self.material_id!r} fehlt im Katalog (Kevin bitten, es anzulegen)")
        if not is_free(self.eintrag):
            raise LagerError(f"Lagerteil {self.id!r} ist vorgeschlagen und {WARTET}.")
        if not is_free(self.material):
            raise LagerError(f"{self.name}: Material {self.material_id!r} ist vorgeschlagen und {WARTET}.")
        values: dict[str, Any]
        extra: dict[str, Any] = {}
        if self.art in STANGENWARE:
            if breite is not None or tiefe is not None or form is not None:
                raise LagerError(f"{self.name}: Stangenware braucht laenge (und gehrung), nicht breite/tiefe/form")
            length = number(laenge)
            if length is None or length <= 0:
                raise LagerError(f"{self.name}: laenge in mm angeben (Zuschnittmaß an der längsten Kante), z. B. "
                                 "verbauen(laenge=882, name=\"Gestell/Bein\")")
            g = _gehrung(gehrung, self.name)
            from kevcad_kernel.profiles import bar

            try:
                shape = bar(self.querschnitt(drehung), length, g)
            except ValueError as exc:
                raise LagerError(f"{self.name}: {exc}") from exc
            values = piece_values(self.eintrag, self.material, laenge=length)
            extra = {"laenge": length, "gehrung": g, "stangenlaenge": self.stangenlaenge}
        elif self.art == "platte":
            if laenge is not None:
                raise LagerError(f"{self.name}: Platten brauchen breite und tiefe (oder form=), nicht laenge")
            shape, extra = self._platte(breite, tiefe, form)
            values = piece_values(self.eintrag, self.material, flaeche_m2=extra["flaeche_m2"])
        elif self.art in KLEINTEILE:
            from kevcad_kernel.profiles import fastener

            if self.art == "schraube":
                length = number(laenge)
                if length is None or length <= 0:
                    raise LagerError(f"{self.name}: Schrauben brauchen laenge (Schaftlänge in mm), z. B. "
                                     "verbauen(laenge=60, name=\"Schrauben/M8x60 1\")")
            else:
                if laenge is not None:
                    raise LagerError(f"{self.name}: {self.art} hat keine Länge")
                length = None
            try:
                shape = fastener(self.art, self.masse, length, simple=simple)
            except (ValueError, KeyError) as exc:
                raise LagerError(f"{self.name}: {exc}") from exc
            values = piece_values(self.eintrag, self.material, volume_mm3=float(shape.volume))
            extra = {"laenge": length, "groesse": str(self.masse.get("groesse"))}
        else:  # pragma: no cover - ARTEN ist vollständig abgedeckt
            raise LagerError(f"{self.name}: art {self.art!r} lässt sich nicht verbauen")

        shape.label = label
        try:
            shape.material = None  # Material kommt aus dem Katalog (bd_warehouse setzt sonst Baustahl)
        except Exception:  # noqa: BLE001
            pass
        if self.farbe:
            try:
                shape.color = Color(self.farbe)
            except Exception:  # noqa: BLE001
                pass
        try:
            shape.lagerteil = self
            shape.lager_name = label
        except Exception:  # noqa: BLE001
            pass
        piece = Piece(seq=0, name=label, stock_id=self.id, art=self.art, benennung=self.name, norm=self.norm,
                      material_id=self.material_id, material_name=self.material_name, ebene=self.ebene,
                      **extra, **values)
        _register(piece, shape)
        return shape

    def _platte(self, breite: Any, tiefe: Any, form: Any) -> tuple[Any, dict[str, Any]]:
        from build123d import Align, Box, extrude

        s = number(self.masse.get("s"))
        assert s is not None
        if form is not None:
            if breite is not None or tiefe is not None:
                raise LagerError(f"{self.name}: entweder breite/tiefe oder form angeben")
            try:
                faces = form.faces()
            except AttributeError as exc:
                raise LagerError(f"{self.name}: form muss eine build123d-Skizze oder Fläche sein (z. B. "
                                 "Rectangle(800, 600) - Circle(40))") from exc
            if not faces:
                raise LagerError(f"{self.name}: form enthält keine Fläche")
            bb = form.bounding_box()
            if bb.size.Z > 1e-6:
                raise LagerError(f"{self.name}: form muss in der XY-Ebene liegen")
            shape = extrude(form, amount=s)
            area = sum(float(f.area) for f in faces)
            b, t = float(bb.size.X), float(bb.size.Y)
            extra = {"breite": b, "tiefe": t, "flaeche_m2": area / 1e6, "form": True}
        else:
            b, t = number(breite), number(tiefe)
            if b is None or t is None or b <= 0 or t <= 0:
                raise LagerError(f"{self.name}: Platten brauchen breite und tiefe in mm (oder form=), z. B. "
                                 "verbauen(breite=800, tiefe=600, name=\"Deckel\")")
            shape = Box(b, t, s, align=(Align.CENTER, Align.CENTER, Align.MIN))
            extra = {"breite": b, "tiefe": t, "flaeche_m2": b * t / 1e6}
        fmt = self.eintrag.get("platte")
        if isinstance(fmt, list) and len(fmt) == 2:
            fb, fh = number(fmt[0]) or 0, number(fmt[1]) or 0
            if not ((b <= fb and t <= fh) or (b <= fh and t <= fb)):
                _warn(f"{self.name}: Zuschnitt {dim_text(b)} × {dim_text(t)} mm ist größer als das Standardformat "
                      f"{dim_text(fb)} × {dim_text(fh)} mm")
        return shape, extra


def _gehrung(value: Any, who: str) -> tuple[float, float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        pair = (float(value), float(value))
    elif isinstance(value, (tuple, list)) and len(value) == 2 and all(number(v) is not None for v in value):
        pair = (float(number(value[0])), float(number(value[1])))  # type: ignore[arg-type]
    elif value is None:
        pair = (0.0, 0.0)
    else:
        raise LagerError(f"{who}: gehrung als (anfang, ende) in Grad angeben, z. B. gehrung=(45, 45)")
    for w in pair:
        if not math.isfinite(w) or abs(w) > MAX_GEHRUNG:
            raise LagerError(f"{who}: Gehrung {w:g}° außerhalb von ±{MAX_GEHRUNG:g}°")
    return pair


# ---------------------------------------------------------------------------------------------------------------------
# Suchen


def _value_matches(key: str, want: Any, have: Any) -> bool:
    if key in TEXT_MASSE:
        a, b = fold(str(want)).replace(" ", ""), fold(str(have)).replace(" ", "")
        if a == b:
            return True
        return key == "groesse" and "-" not in a and b.split("-")[0] == a
    x, y = number(want), number(have)
    return x is not None and y is not None and abs(x - y) < 1e-6


def teil(auswahl: str, /, *, material: str | None = None, **masse: Any) -> Lagerteil:
    """Lagerteil nach id (``teil("rohr-en10220-42.4x2.0")``) oder nach Art und Maßen
    (``teil("vierkantrohr", a=40, s=3)``, ``teil("platte", s=18, material="multiplex-birke")``)."""
    if not isinstance(auswahl, str) or not auswahl.strip():
        raise LagerError("lager.teil braucht eine id oder eine Art, z. B. lager.teil(\"vierkantrohr\", a=40, s=3)")
    cat = katalog()
    key = auswahl.strip()
    if not masse and material is None:
        it = cat.item(key)
        if it is not None:
            return _released(cat, it)
    art = key.lower()
    if art in ARTEN:
        return _by_art(cat, art, material, masse)
    if masse or material is not None:
        close = difflib.get_close_matches(art, ARTEN, n=2, cutoff=0.5)
        raise LagerError(f"Art {auswahl!r} unbekannt (erlaubt: {', '.join(ARTEN)})"
                         + (f". Meinten Sie {' oder '.join(repr(c) for c in close)}?" if close else ""))
    hits, _ = cat.search(key, limit=5)
    close = difflib.get_close_matches(key, cat.item_ids(), n=3, cutoff=0.6)
    tips = list(dict.fromkeys(close + [h["id"] for h in hits]))[:5]
    raise LagerError(f"Lagerteil {auswahl!r} gibt es nicht."
                     + (f" Meinten Sie: {', '.join(repr(t) for t in tips)}?" if tips else
                        " lager.suche(\"…\") oder stock_search zeigt, was es gibt."))


def _by_art(cat: Catalog, art: str, material: str | None, masse: dict[str, Any]) -> Lagerteil:
    allowed = set(REQUIRED_MASSE[art]) | set(OPTIONAL_MASSE.get(art, ()))
    unknown = [k for k in masse if k not in allowed]
    if unknown:
        raise LagerError(f"Maß {', '.join(unknown)} gibt es für art {art!r} nicht (erlaubt: "
                         f"{', '.join(sorted(allowed))})")
    rows = cat.items(art)
    mat_id = None
    if material is not None:
        mat = cat.find_material(material, include_proposed=True)
        if mat is None:
            tips = cat.material_suggestions(str(material))
            raise LagerError(f"Material {material!r} gibt es im Katalog nicht"
                             + (f". Meinten Sie {', '.join(repr(t) for t in tips)}?" if tips else ""))
        mat_id = mat["id"]
        rows = [r for r in rows if r.get("material") == mat_id]
    hits = [r for r in rows if all(k in (r.get("masse") or {}) and _value_matches(k, v, r["masse"][k])
                                   for k, v in masse.items())]
    want = ", ".join(f"{k}={v}" for k, v in masse.items()) + (f", material={material}" if material else "")
    free = [h for h in hits if is_free(h)]
    if hits and not free:
        ids = ", ".join(h["id"] for h in hits[:5])
        raise LagerError(f"Lagerteil {ids} für {art} {want} ist vorgeschlagen und {WARTET}.")
    hits = free
    if len(hits) == 1:
        return _released(cat, hits[0])
    if len(hits) > 1:
        listing = "; ".join(f"{h['id']} ({h.get('name')}, {h.get('material')})" for h in hits[:8])
        raise LagerError(f"{len(hits)} Lagerteile passen zu {art} {want}: {listing}. Mit id, material= oder weiteren "
                         "Maßen eindeutig machen.")
    if not rows:
        raise LagerError(f"Im Katalog gibt es keine Lagerteile der Art {art!r}"
                         + (f" aus {material!r}" if material else "") + ".")
    nums = {k: number(v) for k, v in masse.items() if k not in TEXT_MASSE and number(v) is not None}

    def distance(r: dict[str, Any]) -> float:
        rm = r.get("masse") or {}
        d = 0.0
        for k, v in nums.items():
            have = number(rm.get(k))
            d += abs((have if have is not None else 1e6) - v) / max(abs(v), 1.0)
        for k, v in masse.items():
            if k in TEXT_MASSE and not _value_matches(k, v, rm.get(k, "")):
                d += 10.0
        return d

    near = sorted(rows, key=distance)[:5]
    listing = "; ".join(f"{r['id']} ({_masse_text(r)})" for r in near)
    raise LagerError(f"Kein Lagerteil {art} mit {want}. Ähnlich: {listing}. Neues Lagerteil nur auf Kevins Wunsch "
                     "mit stock_define anlegen.")


def _released(cat: Catalog, entry: dict[str, Any]) -> Lagerteil:
    if not is_free(entry):
        raise LagerError(f"Lagerteil {entry['id']!r} ist vorgeschlagen und {WARTET}.")
    mat = cat.material(entry.get("material", ""))
    if mat is not None and not is_free(mat):
        raise LagerError(f"Lagerteil {entry['id']!r}: Material {mat['id']!r} ist vorgeschlagen und {WARTET}.")
    return Lagerteil(entry, mat)


def suche(text: str = "", art: str | None = None, limit: int = 30) -> list[Lagerteil]:
    """Lagerteile nach Text und Maßen ("vierkantrohr 40x40x3", "edelstahl rohr 33,7", "m8")."""
    cat = katalog()
    hits, _ = cat.search(text, art=art, limit=limit)
    return [Lagerteil(h, cat.material(h.get("material", ""))) for h in hits]


# ---------------------------------------------------------------------------------------------------------------------
# Druckteile (Eigenfertigung)


def druckteil(form: Any, name: str, material: str, verfahren: str = "3d-druck"):
    """Selbst konstruiertes Teil, das gedruckt wird: registriert es für die Stückliste (Masse aus Volumen × Dichte,
    Kosten über preis_je_kg) und gibt es mit Name, Farbe und Material zurück. ``material`` muss freigegeben und
    druckbar sein; ``verfahren`` "3d-druck" oder "harzdruck"."""
    from build123d import BuildPart, Color, Shape

    from kevcad_kernel.bom import Piece

    if verfahren not in VERFAHREN:
        raise LagerError(f"Verfahren {verfahren!r} ist nicht erlaubt (erlaubt: {', '.join(VERFAHREN)}). Andere "
                         "Fertigung nur mit Lagerteilen aus dem Katalog.")
    if not isinstance(name, str) or not name.strip():
        raise LagerError("druckteil braucht einen Namen, z. B. lager.druckteil(form, \"Halter/Schelle\", "
                         "material=\"petg\")")
    shape = form.part if isinstance(form, BuildPart) else form
    if not isinstance(shape, Shape):
        raise LagerError(f"druckteil: form muss ein build123d-Körper sein (Part, Solid, BuildPart), nicht "
                         f"{type(form).__name__}")
    volume = float(shape.volume)
    if volume <= 1e-9:
        raise LagerError(f"druckteil {name!r}: form hat kein Volumen (erst mit extrude() zum Körper machen)")
    mat = released_material(material, druckbar=True)
    label = name.strip().strip("/").replace("#", "-")
    shape.label = label
    try:
        shape.material = None
    except Exception:  # noqa: BLE001
        pass
    if mat.get("farbe"):
        try:
            shape.color = Color(mat["farbe"])
        except Exception:  # noqa: BLE001
            pass
    dichte = number(mat.get("dichte")) or 0.0
    kg = volume * dichte / 1e6
    pkg = number(mat.get("preis_je_kg"))
    bb = shape.bounding_box()
    piece = Piece(seq=0, name=label, stock_id=None, art="druckteil", benennung=label, material_id=mat["id"],
                  material_name=mat.get("name") or mat["id"], ebene=mat.get("ebene", "mitgeliefert"), kg=kg,
                  preis=kg * pkg if pkg is not None else None, preis_stand=mat.get("preis_stand"),
                  preis_quelle=mat.get("preis_quelle"), verfahren=verfahren, volume=volume,
                  size=[round(float(bb.size.X), 3), round(float(bb.size.Y), 3), round(float(bb.size.Z), 3)])
    _register(piece, shape)
    return shape
