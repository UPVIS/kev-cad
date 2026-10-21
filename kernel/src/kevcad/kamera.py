"""Kameras und Kamerazubehör in model.py (KATALOG.md „Kameras und Objektive“, PROTOCOL.md „Phase 5: Kameras“).

```python
from kevcad import lager, show

fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", blende=2.8, fokus=1500,
                   name="FX6")
fx6.setzen((0, -400, 180), blick_auf=(800, 0, 108))            # Sensormitte, Blick auf einen Punkt
fx6.setzen((300, 0, 200), richtung=(1, 0, 0), bezug="bajonett") # Bajonett-Auflage statt Sensormitte
fx6.setzen(platte.bezugspunkt("kamera_1_4"), bezug="stativ_1_4")  # Kamera mit ihrem 1/4"-Gewinde auf eine Location
fx6.an("Kamera FX6/Body", punkt=(8, 0, 52), richtung=(1, 0, 0), lokal=True)  # hängt an einem Teil, folgt ihm
show(fx6.koerper(), "Kamera FX6")       # Gehäuse und Objektiv (Katalogmaße oder Geometrie), zählt als Inventar
print(fx6.bildwinkel_h, fx6.schaerfe_nah, fx6.schaerfe_fern)

platte = lager.kamerazubehoer("tilta-es-t20-qrbp")
show(platte.verbauen("Rig/Baseplate", an=fx6.bezugspunkt("stativ_1_4"), bezug="kamera_1_4"), "Rig/Baseplate")
```

Koordinaten der Katalogeinträge (lokal): x Blickrichtung bzw. nach vorn, y links, z oben, mm. Ursprung bei Kameras die
Sensormitte, bei Objektiven die Bajonett-Auflage, bei Zubehör laut Feld ``ursprung``. Bezugspunkte stehen im Eintrag
(``bezugspunkte``), die Form liefert optional eine Funktion (``geometrie``), sonst ein Quader bzw. Zylinder aus den
Maßen.

- Lage der Kamera: ``bezug`` ist ein Bezugspunkt der Kamera („sensor“, „bajonett“, „stativ_1_4“ …), der an
  ``position`` liegt. Blickrichtung über ``blick_auf`` (Punkt) oder ``richtung`` (Vektor); oben ist Welt-Z, ``roll`` in
  Grad dreht um die Blickachse (positiv im Uhrzeigersinn aus Sicht des Kameramanns). Ist ``position`` eine
  build123d-Location, gibt sie auch die Ausrichtung vor (x Blick, z oben).
- ``an(teil, ...)``: die Kamera hängt an einem gezeigten Teil und folgt ihm (Animation); ``lokal=True``: Angaben in den
  Koordinaten des Teils (seiner Location).
- Bildwinkel aus Sensorfläche und Brennweite, Schärfentiefe aus Blende, Fokus (mm ab Sensorebene) und
  Zerstreuungskreis des Formats (``kevcad_kernel.optik``).
- Im Kernel erscheint jede Kamera als Objekt „Kamera/<name>“ in der App (Pyramide bis zur Fokusebene, Taste 0 schaut
  durch sie hindurch) und über MCP (kamera_liste, kamera_bild …).
"""

from __future__ import annotations

import difflib
import importlib
import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import kevcad
from kevcad_kernel.catalog import is_free
from kevcad_kernel.optik import (
    bildwinkel,
    blende_text,
    brennweiten,
    format_info,
    format_von,
    hyperfokal,
    ist_zoom,
    mm_text,
    schaerfentiefe,
)

__all__ = ["Kamera", "KameraError", "Zubehoer", "kamera", "kamerazubehoer", "ausrichten", "PREFIX",
           "standard_gehaeuse", "standard_objektiv", "standard_zubehoer", "front_x"]

PREFIX = "Kamera/"
STANDARD_BLENDE = 2.8
STANDARD_FOKUS = 3000.0
Vec = tuple[float, float, float]


class KameraError(ValueError):
    """Kamera, Objektiv oder Zubehör nicht im Katalog, nicht passend oder falsch eingestellt (mit Vorschlägen)."""


# ---------------------------------------------------------------------------------------------------------------------
# Vektoren (ohne numpy, damit model.py auch außerhalb des Kernels läuft)


def _is_location(value: Any) -> bool:
    return type(value).__name__ == "Location" and hasattr(value, "wrapped")


def _v(value: Any, what: str) -> Vec:
    if value is None:
        raise KameraError(f"{what} fehlt (Punkt oder Vektor als (x, y, z) in mm)")
    if _is_location(value):
        value = value.position
    if all(hasattr(value, k) for k in ("X", "Y", "Z")):
        return float(value.X), float(value.Y), float(value.Z)
    try:
        x, y, z = (float(c) for c in value)
    except (TypeError, ValueError) as exc:
        raise KameraError(f"{what}: {value!r} ist kein Punkt (x, y, z)") from exc
    if not all(math.isfinite(c) for c in (x, y, z)):
        raise KameraError(f"{what}: {value!r} enthält keine endlichen Zahlen")
    return x, y, z


def _add(a: Vec, b: Vec) -> Vec:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _sub(a: Vec, b: Vec) -> Vec:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _mul(a: Vec, k: float) -> Vec:
    return a[0] * k, a[1] * k, a[2] * k


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _norm(a: Vec) -> Vec:
    n = math.sqrt(_dot(a, a))
    if n < 1e-9:
        raise KameraError("Richtung hat die Länge 0 (Blickpunkt gleich Kameraposition?)")
    return a[0] / n, a[1] / n, a[2] / n


def _r(a: Vec, digits: int = 4) -> list[float]:
    return [round(c, digits) + 0.0 for c in a]


def basis(blick: Vec, roll: float = 0.0, oben: Vec | None = None) -> tuple[Vec, Vec, Vec]:
    """(blick, rechts, oben) als Einheitsvektoren. Oben folgt ``oben`` (sonst Welt-Z, beim Blick senkrecht nach oben
    oder unten Welt-Y); ``roll`` dreht rechts und oben um die Blickachse (rechte Hand um ``blick``, also im
    Uhrzeigersinn von hinten gesehen)."""
    d = _norm(blick)
    ref: Vec = oben if oben is not None else ((0.0, 0.0, 1.0) if abs(d[2]) < 0.999 else (0.0, 1.0, 0.0))
    if math.sqrt(_dot(_cross(d, ref), _cross(d, ref))) < 1e-6:
        ref = (0.0, 1.0, 0.0) if abs(d[1]) < 0.999 else (1.0, 0.0, 0.0)
    rechts = _norm(_cross(d, ref))
    up = _cross(rechts, d)
    if roll:
        a = math.radians(roll)
        c, s = math.cos(a), math.sin(a)
        rechts, up = (_norm(_add(_mul(rechts, c), _mul(_cross(d, rechts), s))),
                      _norm(_add(_mul(up, c), _mul(_cross(d, up), s))))
    return d, rechts, up


def _apply(m: list[list[float]], p: Vec, w: float = 1.0) -> Vec:
    """3 × 4-Matrix (zeilenweise) auf Punkt (w = 1) oder Richtung (w = 0)."""
    return tuple(m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] + m[r][3] * w for r in range(3))  # type: ignore


def location_matrix(obj: Any) -> list[list[float]]:
    """3 × 4-Matrix (zeilenweise) der Location einer build123d-Form oder einer Location."""
    loc = obj if _is_location(obj) else getattr(obj, "location", None)
    if loc is None:
        raise KameraError(f"{type(obj).__name__} hat keine Location")
    t = loc.wrapped.Transformation()
    return [[t.Value(r, c) for c in range(1, 5)] for r in range(1, 4)]


def _frame_location(origin: Vec, x_dir: Vec, z_dir: Vec):
    from build123d import Location, Plane

    return Location(Plane(origin=origin, x_dir=x_dir, z_dir=z_dir))


def ausrichten(an: Any, bezug: Any):
    """Location, die ein Teil so setzt, dass sein lokaler Bezugspunkt ``bezug`` (Location) auf ``an`` (Location oder
    Punkt) liegt, mit gleichen Achsen: ``an * bezug⁻¹``."""
    from build123d import Location

    target = an if _is_location(an) else Location(_v(an, "an"))
    return target * bezug.inverse()


# ---------------------------------------------------------------------------------------------------------------------
# Katalog


def _catalog():
    from kevcad.lager import katalog

    return katalog()


def _find(art: str, wunsch: Any) -> dict[str, Any]:
    """Katalogeintrag nach id oder Suchtext (eindeutig), nur freigegebene."""
    what = {"kamera": "Kamera", "objektiv": "Objektiv"}.get(art, "Kamerazubehör")
    if isinstance(wunsch, dict) and wunsch.get("art") == art:
        return wunsch
    if not isinstance(wunsch, str) or not wunsch.strip():
        raise KameraError(f"{what}: id aus dem Katalog angeben (kamera_katalog bzw. stock_search mit art {art!r})")
    cat = _catalog()
    key = wunsch.strip()
    it = cat.item(key)
    if it is not None and it.get("art") != art:
        raise KameraError(f"{key!r} ist ein Lagerteil der Art {it.get('art')!r}, kein {what}")
    if it is None:
        hits, _ = cat.search(key, art=art, limit=10)
        if len(hits) == 1:
            it = hits[0]
        else:
            ids = [i["id"] for i in cat.items(art)]
            close = difflib.get_close_matches(key, ids, n=3, cutoff=0.5)
            tips = list(dict.fromkeys([h["id"] for h in hits] + close))[:6]
            if hits:
                raise KameraError(f"{what} {key!r} ist nicht eindeutig: {', '.join(tips)}")
            raise KameraError(f"{what} {key!r} gibt es im Katalog nicht"
                              + (f". Meinten Sie {', '.join(repr(t) for t in tips)}?" if tips else
                                 f". Vorhanden: {', '.join(ids) or 'keine'}"))
    if not is_free(it):
        raise KameraError(f"{what} {it['id']!r} ist vorgeschlagen und wartet auf Kevins Freigabe im Lagerkatalog.")
    return it


def _num(x: Any, what: str) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError) as exc:
        raise KameraError(f"{what}: {x!r} ist keine Zahl") from exc
    if math.isnan(v):
        raise KameraError(f"{what}: keine Zahl")
    return v


def _warn(text: str) -> None:
    hook = kevcad._hooks.get("warn")
    if hook is not None:
        hook(text)


def front_x(entry: dict[str, Any]) -> float:
    """x der Gehäusefront einer Kamera ab Sensorebene: Auflagemaß minus Vorstand der Bajonett-Auflage."""
    geh = entry.get("gehaeuse") or {}
    return float(entry.get("auflagemass") or 0.0) - float(geh.get("bajonett_vorstand") or 0.0)


def _local_point(entry: dict[str, Any], name: str, builtin: dict[str, Vec] | None = None) -> Vec:
    """Lokaler Bezugspunkt eines Eintrags (``"von": "front"``: x ab der Gehäusefront); unbekannt → KameraError."""
    pts = dict(builtin or {})
    for key, pt in (entry.get("bezugspunkte") or {}).items():
        if isinstance(pt, dict) and isinstance(pt.get("pos"), (list, tuple)):
            x, y, z = (float(c) for c in pt["pos"])
            if pt.get("von") == "front":
                x += front_x(entry)
            pts[str(key)] = (x, y, z)
    if name not in pts:
        close = difflib.get_close_matches(str(name), list(pts), n=3, cutoff=0.4)
        raise KameraError(f"Bezugspunkt {name!r} gibt es bei {entry.get('name') or entry.get('id')} nicht"
                          + (f". Meinten Sie {', '.join(repr(c) for c in close)}?" if close else "")
                          + f" Vorhanden: {', '.join(sorted(pts)) or 'keine'}")
    return pts[name]


def geometrie(entry: dict[str, Any], standard: str) -> dict[str, Any] | None:
    """Form aus dem Feld ``geometrie`` (Funktion ``f(eintrag) -> Shape | dict[str, Shape]`` in lokalen Koordinaten),
    als {Teilname: Form}; None, wenn der Eintrag keine Geometrie nennt. ``standard`` ist der Teilname für eine einzelne
    Form."""
    geo = entry.get("geometrie")
    if not isinstance(geo, dict):
        return None
    fn_name = str(geo.get("funktion") or "")
    try:
        if geo.get("modul"):
            mod = importlib.import_module(str(geo["modul"]))
        else:
            src = _catalog().source("teil", entry["id"])
            base = src[1].parent if src is not None else Path.cwd()
            path = (base / str(geo["datei"])).resolve()
            name = f"kevcad_geometrie_{abs(hash(str(path)))}"
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"{path} nicht ladbar")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        fn = getattr(mod, fn_name)
    except Exception as exc:  # noqa: BLE001 - Meldung mit Ursache, Lauf bricht ab
        raise KameraError(f"Geometrie von {entry.get('id')!r} nicht ladbar ({geo}): {type(exc).__name__}: {exc}") from exc
    res = fn(dict(entry))
    if isinstance(res, dict):
        return {str(k): v for k, v in res.items()}
    return {standard: res}


def _piece(entry: dict[str, Any], *, name: str, art: str, groesse: str, token: str):
    from kevcad_kernel.bom import Piece

    preis = entry.get("preis") if isinstance(entry.get("preis"), dict) else {}
    return Piece(seq=0, name=name, stock_id=entry["id"], art=art, benennung=str(entry.get("name") or entry["id"]),
                 norm=entry.get("norm"), ebene=entry.get("ebene", "mitgeliefert"), groesse=groesse,
                 kg=float(entry["gewicht"]) / 1000 if entry.get("gewicht") else None,
                 preis=float(preis["je_stueck"]) if preis.get("je_stueck") is not None else None,
                 preis_stand=preis.get("stand"), preis_quelle=preis.get("quelle"), token=token)


def _register(piece: Any, shape: Any) -> None:
    hook = kevcad._hooks.get("lager")
    if hook is not None:
        hook(piece, shape)


def _place(shapes: dict[str, Any], loc: Any, token_of) -> list[Any]:
    """Formen mit ``loc`` setzen, beschriften und mit lager_token versehen (übersteht Kopieren beim Verschieben)."""
    kids = []
    for label, shape in shapes.items():
        placed = loc * shape
        placed.label = label
        try:
            placed.color = shape.color
        except Exception:  # noqa: BLE001
            pass
        placed.lager_token = token_of(label)
        kids.append(placed)
    return kids


# ---------------------------------------------------------------------------------------------------------------------
# Vereinfachte Formen aus den Katalogmaßen (wenn ein Eintrag keine geometrie hat; auch Platzhalter in
# kevcad.geometrie.kamerasystem). Lokale Koordinaten: x nach vorn, y links, z oben.


def standard_gehaeuse(entry: dict[str, Any]) -> dict[str, Any]:
    """Kameragehäuse als verrundeter Quader aus ``gehaeuse`` (Ursprung Sensormitte, Bildachse entlang +x), dazu der
    Bajonettring (``gehaeuse.ring_vorstand`` vor der Front)."""
    from build123d import Align, Box, Color, Cylinder, Pos, Rot

    geh = entry.get("gehaeuse") or {}
    b, h, t = float(geh.get("b") or 100), float(geh.get("h") or 100), float(geh.get("t") or 150)
    achse_h = float(geh.get("achse_hoehe") if geh.get("achse_hoehe") is not None else h / 2)
    seitlich = float(geh.get("achse_seitlich") or 0.0)
    front = front_x(entry)
    # Achse rechts der Mitte (von hinten) → Gehäusemitte links der Achse (+y)
    body = Pos(front, seitlich, -achse_h) * Box(t, b, h, align=(Align.MAX, Align.CENTER, Align.MIN))
    try:
        from build123d import Axis, fillet

        body = fillet(body.edges().filter_by(Axis.X), radius=min(6.0, b / 10, h / 10))
    except Exception:  # noqa: BLE001 - Verrundung ist nur Optik
        pass
    ring_l = float(geh.get("ring_vorstand") or geh.get("bajonett_vorstand") or 0.0)
    if ring_l > 0:
        base = (Align.CENTER, Align.CENTER, Align.MIN)
        ring = Rot(0, 90, 0) * (Cylinder(30, ring_l + 0.5, align=base) - Cylinder(23.05, ring_l + 2, align=base))
        body = body + Pos(front - 0.5, 0, 0) * ring
    body.color = Color("#2B2D30")
    return {"Gehäuse": body}


def standard_objektiv(entry: dict[str, Any]) -> dict[str, Any]:
    """Objektiv als Zylinder aus ``laenge`` und ``frontdurchmesser`` (Ursprung Bajonett-Auflage, +x zur Frontlinse),
    hinten etwas schlanker, vorn mit vertiefter Frontlinse."""
    from build123d import Align, Color, Cylinder, Pos, Rot

    d = float(entry.get("frontdurchmesser") or 70)
    length = float(entry.get("laenge") or 80)
    rear = 0.3 * length
    base = (Align.CENTER, Align.CENTER, Align.MIN)
    lens = Rot(0, 90, 0) * Cylinder(0.44 * d, rear + 0.5, align=base)
    lens += Pos(rear, 0, 0) * Rot(0, 90, 0) * Cylinder(d / 2, length - rear, align=base)
    lens -= Pos(length - 3, 0, 0) * Rot(0, 90, 0) * Cylinder(0.4 * d, 4, align=base)
    lens.color = Color("#151617")
    return {"Objektiv": lens}


def standard_zubehoer(entry: dict[str, Any]) -> dict[str, Any]:
    """Zubehör aus ``masse``: Stangen als Zylinder ab dem Ursprung entlang +x, Rosetten als Scheibe hinter dem
    Ursprung, Baseplates als Quader unter dem Ursprung, sonst ein Quader hinter dem Ursprung (x von −t bis 0)."""
    from build123d import Align, Box, Color, Cylinder, Rot

    name = str(entry.get("name") or entry.get("id"))
    typ = str(entry.get("typ") or "sonstiges")
    m = {k: float(v) for k, v in (entry.get("masse") or {}).items()}
    if "d" in m:
        length = m.get("l", 5.0 if typ == "rosette" else 20.0)
        shape = Rot(0, 90, 0) * Cylinder(m["d"] / 2, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
        if typ == "rosette":
            shape = Rot(0, 180, 0) * shape
    else:
        b, h, t = m.get("b", 40.0), m.get("h", 40.0), m.get("t", 20.0)
        align = ((Align.CENTER, Align.CENTER, Align.MAX) if typ == "baseplate"
                 else (Align.MAX, Align.CENTER, Align.CENTER))
        shape = Box(t, b, h, align=align)
        if not m:
            _warn(f"{name}: keine Maße im Katalog, als Platzhalter-Quader {t:g} × {b:g} × {h:g} mm gezeigt")
    shape.color = Color("#B9BEC4" if typ == "rod" else "#5A5E64")
    return {name: shape}


# ---------------------------------------------------------------------------------------------------------------------
# Kamera


class Kamera:
    """Kamera mit Objektiv, Format, Brennweite, Blende, Fokus und Lage. Erzeugt mit ``lager.kamera(...)``."""

    def __init__(self, entry: dict[str, Any], objektiv: dict[str, Any] | None, *, name: str) -> None:
        self.eintrag = entry
        self.objektiv = objektiv
        self.id: str = entry["id"]
        self.name = name
        self._format: dict[str, Any] = format_info(format_von(entry, None))
        self._brennweite = 0.0
        self._blende = STANDARD_BLENDE
        self._blende_gesetzt = False
        self._fokus: float | None = None
        self._coc: float | None = None
        self._sensor: Vec = (0.0, 0.0, 0.0)
        self._basis = basis((1.0, 0.0, 0.0))
        self.gesetzt = False
        self._blickpunkt: Vec | None = None
        self.teil: str | None = None
        self._lokal: dict[str, Any] | None = None
        self._koerper = None
        self._tokens: dict[str, str] = {}
        self._lens_labels: list[str] = []
        self.ausblenden: list[str] = []  # gezeigte Teile des eigenen Objektivs (füllt der Kernel am Laufende)

    # -- Einstellungen ------------------------------------------------------------------------------------------------

    def einstellen(self, *, brennweite: Any = None, blende: Any = None, fokus: Any = None, format: Any = None,  # noqa: A002
                   zerstreuungskreis: Any = None) -> Kamera:
        """Format, Brennweite (mm), Blende (Blendenzahl bzw. T-Wert), Fokus (mm ab Sensorebene, ``"unendlich"`` oder
        ``math.inf``) und Zerstreuungskreis (mm) ändern; geprüft gegen Objektiv und Kamera. Gibt die Kamera zurück."""
        if format is not None:
            try:
                self._format = format_info(format_von(self.eintrag, format))
            except ValueError as exc:
                raise KameraError(str(exc)) from exc
        if brennweite is not None or not self._brennweite:
            self._brennweite = self._check_brennweite(brennweite)
        if blende is not None:
            self._blende = self._check_blende(_num(blende, "blende"))
            self._blende_gesetzt = True
        elif not self._blende_gesetzt and self.objektiv is not None:
            self._blende = self._check_blende(max(STANDARD_BLENDE, float(self.objektiv.get("lichtstaerke") or 0)))
        if fokus is not None:
            self._fokus = self._check_fokus(fokus)
        if zerstreuungskreis is not None:
            c = _num(zerstreuungskreis, "zerstreuungskreis")
            if not 0.001 <= c <= 0.2:
                raise KameraError(f"zerstreuungskreis {c:g} mm ist unplausibel (üblich 0,015 bis 0,035 mm)")
            self._coc = c
        return self

    def _check_brennweite(self, value: Any) -> float:
        if self.objektiv is None:
            if value is None:
                raise KameraError(f"Kamera {self.name}: ohne Objektiv brennweite angeben (ideales Objektiv), besser "
                                  "ein Objektiv aus dem Katalog: objektiv=\"…\"")
            f = _num(value, "brennweite")
            if f <= 0:
                raise KameraError("brennweite muss größer als 0 sein (mm)")
            return f
        lo, hi = brennweiten(self.objektiv)
        if value is None:
            if ist_zoom(self.objektiv):
                _warn(f"Kamera {self.name}: Zoom {self.objektiv.get('name')} ohne brennweite, gerechnet mit {lo:g} mm")
            return lo
        f = _num(value, "brennweite")
        if not lo - 1e-6 <= f <= hi + 1e-6:
            if lo == hi:
                raise KameraError(f"{self.objektiv.get('name')} ist eine Festbrennweite mit {lo:g} mm, nicht {f:g} mm")
            raise KameraError(f"{self.objektiv.get('name')}: brennweite {f:g} mm außerhalb des Zoombereichs "
                              f"{lo:g} bis {hi:g} mm")
        return f

    def _check_blende(self, n: float) -> float:
        if self.objektiv is not None:
            lo = float(self.objektiv.get("lichtstaerke") or 0)
            hi = float(self.objektiv.get("blende_max") or 64)
            art = self.blendenart
            if n < lo - 1e-6:
                raise KameraError(f"{self.objektiv.get('name')} öffnet nur bis {blende_text(lo, art)}, nicht "
                                  f"{blende_text(n, art)}")
            if n > hi + 1e-6:
                raise KameraError(f"{self.objektiv.get('name')} schließt nur bis {blende_text(hi, art)}")
        elif not 0.5 <= n <= 64:
            raise KameraError(f"blende {n:g} ist unplausibel (0,5 bis 64)")
        return n

    def _check_fokus(self, value: Any) -> float:
        if isinstance(value, str) and value.strip().lower() in ("unendlich", "inf", "∞", "infinity"):
            return math.inf
        s = _num(value, "fokus")
        if s <= 0:
            raise KameraError("fokus in mm ab Sensorebene angeben, größer als 0")
        nah = float((self.objektiv or {}).get("naheinstellgrenze") or 0)
        if math.isfinite(s) and nah and s < nah - 1e-6:
            _warn(f"Kamera {self.name}: fokus {mm_text(s)} liegt unter der Naheinstellgrenze von "
                  f"{(self.objektiv or {}).get('name')} ({mm_text(nah)})")
        return s

    # -- Werte --------------------------------------------------------------------------------------------------------

    @property
    def objekt_name(self) -> str:
        """Name des Objekts in App und Protokoll: „Kamera/<name>“."""
        return PREFIX + self.name

    @property
    def brennweite(self) -> float:
        return self._brennweite

    @property
    def blende(self) -> float:
        return self._blende

    @property
    def blendenart(self) -> str:
        return str((self.objektiv or {}).get("blendenart") or "f")

    @property
    def format(self) -> dict[str, Any]:  # noqa: A003
        return dict(self._format)

    @property
    def sensor_mm(self) -> tuple[float, float]:
        b, h = self._format["sensor_mm"]
        return float(b), float(h)

    @property
    def aufloesung(self) -> tuple[int, int]:
        w, h = self._format["aufloesung"]
        return int(w), int(h)

    @property
    def seitenverhaeltnis(self) -> float:
        w, h = self.aufloesung
        return w / h

    @property
    def zerstreuungskreis(self) -> float:
        return float(self._coc if self._coc is not None else self._format["zerstreuungskreis"])

    @property
    def auflagemass(self) -> float:
        return float(self.eintrag.get("auflagemass") or 0.0)

    @property
    def fokus(self) -> float:
        """Fokus in mm ab Sensorebene; ohne Angabe die Entfernung zum Blickpunkt (blick_auf), sonst 3 m."""
        if self._fokus is not None:
            return self._fokus
        if self._blickpunkt is not None:
            return max(math.dist(self._blickpunkt, self.position), 1.0)
        return STANDARD_FOKUS

    @property
    def bildwinkel_h(self) -> float:
        return bildwinkel(self.sensor_mm[0], self.brennweite)

    @property
    def bildwinkel_v(self) -> float:
        return bildwinkel(self.sensor_mm[1], self.brennweite)

    @property
    def bildwinkel_d(self) -> float:
        return bildwinkel(math.hypot(*self.sensor_mm), self.brennweite)

    @property
    def hyperfokal(self) -> float:
        return hyperfokal(self.brennweite, self.blende, self.zerstreuungskreis)

    @property
    def schaerfe_nah(self) -> float:
        return schaerfentiefe(self.brennweite, self.blende, self.zerstreuungskreis, self.fokus)[0]

    @property
    def schaerfe_fern(self) -> float:
        return schaerfentiefe(self.brennweite, self.blende, self.zerstreuungskreis, self.fokus)[1]

    @property
    def schaerfentiefe(self) -> float:
        return self.schaerfe_fern - self.schaerfe_nah

    @property
    def position(self) -> Vec:
        """Sensormitte in Weltkoordinaten (mm)."""
        return self._sensor

    @property
    def blick(self) -> Vec:
        return self._basis[0]

    @property
    def rechts(self) -> Vec:
        return self._basis[1]

    @property
    def oben(self) -> Vec:
        return self._basis[2]

    @property
    def auge(self) -> Vec:
        """Projektionszentrum für Ansicht und Bild: Sensormitte plus Brennweite in Blickrichtung (Fokus unendlich)."""
        return _add(self._sensor, _mul(self.blick, self.brennweite))

    @property
    def objektiv_vorne(self) -> float:
        """Abstand Sensorebene bis Frontlinse in mm (Auflagemaß plus Objektivlänge), ohne Objektiv das Auflagemaß."""
        return self.auflagemass + float((self.objektiv or {}).get("laenge") or 0.0)

    def _builtin_points(self) -> dict[str, Vec]:
        return {"sensor": (0.0, 0.0, 0.0), "bajonett": (self.auflagemass, 0.0, 0.0),
                "auge": (self.brennweite, 0.0, 0.0), "front": (self.objektiv_vorne, 0.0, 0.0)}

    def bezugspunkte(self) -> list[str]:
        """Namen der Bezugspunkte (eingebaut: sensor, bajonett, auge, front; dazu die aus dem Katalog)."""
        return sorted(set(self._builtin_points()) | set((self.eintrag.get("bezugspunkte") or {}).keys()))

    def _world(self, local: Vec) -> Vec:
        links = _mul(self.rechts, -1.0)
        return _add(self._sensor, _add(_add(_mul(self.blick, local[0]), _mul(links, local[1])),
                                       _mul(self.oben, local[2])))

    def bezugspunkt(self, name: str):
        """Bezugspunkt der Kamera als build123d-Location in Weltkoordinaten, Achsen wie die Kamera (x Blick, z oben)."""
        p = self._world(_local_point(self.eintrag, name, self._builtin_points()))
        return _frame_location(p, self.blick, self.oben)

    def lage(self) -> list[float]:
        """4 × 4-Matrix spaltenweise (16 Zahlen): Spalten rechts, oben, hinten (= −blick), Sensormitte. Die Kamera
        blickt entlang ihrer lokalen −Z-Achse, oben ist +Y (wie OpenGL und Blender)."""
        r, o, d = self.rechts, self.oben, self.blick
        p = self._sensor
        return [*r, 0.0, *o, 0.0, -d[0], -d[1], -d[2], 0.0, *p, 1.0]

    # -- Lage ---------------------------------------------------------------------------------------------------------

    def _pose(self, punkt: Vec, richtung: Vec | None, blick_auf: Vec | None, roll: float, bezug: str,
              oben: Vec | None = None) -> None:
        local = _local_point(self.eintrag, bezug, self._builtin_points())
        if blick_auf is not None and richtung is not None:
            raise KameraError("entweder blick_auf (Punkt) oder richtung (Vektor) angeben, nicht beides")
        if blick_auf is None and richtung is None:
            richtung = self.blick if self.gesetzt else (1.0, 0.0, 0.0)
        d = _norm(_sub(blick_auf, punkt) if blick_auf is not None else richtung)  # type: ignore[arg-type]
        self._basis = basis(d, float(roll or 0.0), oben)
        self._sensor = (0.0, 0.0, 0.0)
        offset = self._world(local)  # Bezugspunkt relativ zur Sensormitte, in Weltachsen
        self._sensor = _sub(punkt, offset)
        self._blickpunkt = blick_auf
        self.gesetzt = True

    def setzen(self, position: Any, blick_auf: Any = None, *, richtung: Any = None, roll: float = 0,
               bezug: str = "sensor") -> Kamera:
        """Kamera frei in den Raum setzen: Bezugspunkt ``bezug`` (Standard Sensormitte) liegt an ``position``. Blick
        über ``blick_auf`` (Punkt) oder ``richtung``; ``roll`` in Grad. Eine Location als ``position`` gibt ohne
        blick_auf/richtung auch die Ausrichtung vor (x Blick, z oben). Gibt die Kamera zurück."""
        p = _v(position, "position")
        oben = None
        r = _v(richtung, "richtung") if richtung is not None else None
        b = _v(blick_auf, "blick_auf") if blick_auf is not None else None
        if _is_location(position) and r is None and b is None:
            from build123d import Plane

            pl = Plane(position)
            r, oben = _v(pl.x_dir, "x"), _v(pl.z_dir, "z")
        self._pose(p, r, b, roll, bezug, oben)
        self.teil, self._lokal = None, None
        self._update_koerper()
        return self

    def an(self, teil: Any, punkt: Any = (0, 0, 0), richtung: Any = None, *, blick_auf: Any = None, roll: float = 0,
           bezug: str = "bajonett", lokal: bool = False) -> Kamera:
        """Kamera an einem Teil befestigen (folgt ihm). ``teil``: Name wie in ``show()`` oder die build123d-Form.
        ``punkt`` ist die Lage des Bezugspunkts ``bezug`` (Standard: Bajonett), ``richtung`` die Blickrichtung
        (Standard +X) oder ``blick_auf`` ein Punkt. ``lokal=True``: Angaben in den Koordinaten des Teils."""
        name = teil if isinstance(teil, str) else (getattr(teil, "label", "") or None)
        if isinstance(teil, str) and not teil.strip():
            raise KameraError("an(): Teilname angeben, z. B. an(\"Kamera FX6/Body\", ...)")
        p = _v(punkt, "punkt")
        r = _v(richtung, "richtung") if richtung is not None else None
        b = _v(blick_auf, "blick_auf") if blick_auf is not None else None
        if r is None and b is None:
            r = (1.0, 0.0, 0.0)
        self.teil = str(name).strip().strip("/") if name else None
        self._lokal = None
        if lokal and isinstance(teil, str):
            hook = kevcad._hooks.get("teil_location")
            m = hook(self.teil) if hook is not None else None
            if m is not None:  # Teil schon gezeigt: gleich in Weltkoordinaten
                self._pose(_apply(m, p), _apply(m, r, 0.0) if r is not None else None,
                           _apply(m, b) if b is not None else None, roll, bezug)
            else:  # Auflösung am Laufende, sobald die Location des gezeigten Teils bekannt ist
                self._lokal = {"punkt": p, "richtung": r, "blick_auf": b, "roll": roll, "bezug": bezug}
                self._pose(p, r, b, roll, bezug)  # vorläufig (falls das Teil nicht gezeigt wird)
        elif lokal:
            m = location_matrix(teil)
            self._pose(_apply(m, p), _apply(m, r, 0.0) if r is not None else None,
                       _apply(m, b) if b is not None else None, roll, bezug)
        else:
            self._pose(p, r, b, roll, bezug)
        self._update_koerper()
        return self

    def aufloesen(self, locations: dict[str, list[list[float]]]) -> str | None:
        """Lokale Befestigung mit der Location des gezeigten Teils auflösen (Kernel, Laufende). Meldung oder None."""
        if self._lokal is None or self.teil is None:
            return None
        m = locations.get(self.teil)
        if m is None:
            return (f"Kamera {self.name}: Teil {self.teil!r} wurde nicht gezeigt, die Kamera steht an den lokalen "
                    "Koordinaten (wie im Weltsystem)")
        lk = self._lokal
        r, b = lk["richtung"], lk["blick_auf"]
        self._pose(_apply(m, lk["punkt"]), _apply(m, r, 0.0) if r is not None else None,
                   _apply(m, b) if b is not None else None, lk["roll"], lk["bezug"])
        self._lokal = None
        if self._koerper is not None:
            self._update_koerper()
            return (f"Kamera {self.name}: an({self.teil!r}, lokal=True) steht vor show({self.teil!r}); Körper und "
                    "Bezugspunkte der Kamera lagen im Skript noch an den lokalen Koordinaten. an() nach dem show() "
                    "des Teils aufrufen")
        return None

    # -- Körper -------------------------------------------------------------------------------------------------------

    def koerper(self):
        """Gehäuse und Objektiv an der Lage der Kamera als Compound mit den Kindern „Gehäuse“ und „Objektiv“ (bzw. den
        Teilen der Geometrie aus dem Katalog). Mit ``show(fx6.koerper(), "Kamera FX6")`` zeigen; beide stehen als
        Inventar in der Stückliste. Beim Blick durch die Kamera blendet die App sie aus."""
        if self._koerper is None:
            self._koerper = self._build_koerper()
            self._register_pieces()
        return self._koerper

    def _gehaeuse_formen(self) -> dict[str, Any]:
        formen = geometrie(self.eintrag, "Gehäuse")
        return formen if formen is not None else standard_gehaeuse(self.eintrag)

    def _objektiv_formen(self) -> dict[str, Any]:
        """Objektiv in seinen lokalen Koordinaten (Ursprung Bajonett-Auflage, +x zur Frontlinse)."""
        if self.objektiv is None:
            return {}
        formen = geometrie(self.objektiv, "Objektiv")
        return formen if formen is not None else standard_objektiv(self.objektiv)

    def _build_koerper(self):
        from build123d import Compound, Pos

        sensor_loc = _frame_location(self._sensor, self.blick, self.oben)
        body_token, lens_token = f"kamera:{id(self)}:gehaeuse", f"kamera:{id(self)}:objektiv"
        self._tokens = {"gehaeuse": body_token, "objektiv": lens_token}
        kids = _place(self._gehaeuse_formen(), sensor_loc, lambda _label: body_token)
        lens = self._objektiv_formen()
        self._lens_labels = list(lens)
        kids += _place(lens, sensor_loc * Pos(self.auflagemass, 0, 0), lambda _label: lens_token)
        return Compound(label=self.objekt_name, children=kids)

    def _update_koerper(self) -> None:
        """Nach einer neuen Lage: schon gebauten Körper neu setzen (die Stückliste findet ihn über lager_token)."""
        if self._koerper is not None:
            self._koerper = self._build_koerper()

    def _register_pieces(self) -> None:
        geh = self.eintrag.get("gehaeuse") or {}
        kids = list(self._koerper.children)
        lens_labels = set(self._lens_labels)
        body_kids = [k for k in kids if k.label not in lens_labels]
        lens_kids = [k for k in kids if k.label in lens_labels]
        size = " × ".join(f"{float(geh.get(k) or 0):g}" for k in ("b", "h", "t")).replace(".", ",")
        if body_kids:
            _register(_piece(self.eintrag, name=f"{self.objekt_name}/{body_kids[0].label}", art="kamera",
                             groesse=f"{size} mm", token=body_kids[0].lager_token), body_kids[0])
        if self.objektiv is not None and lens_kids:
            o = self.objektiv
            lo, hi = brennweiten(o)
            f_text = f"{lo:g}–{hi:g} mm" if hi > lo else f"{lo:g} mm"
            groesse = f"{f_text} {blende_text(float(o.get('lichtstaerke') or 0), self.blendenart)}"
            _register(_piece(o, name=f"{self.objekt_name}/{lens_kids[0].label}", art="objektiv",
                             groesse=groesse.replace(".", ","), token=lens_kids[0].lager_token), lens_kids[0])

    # -- Ausgabe ------------------------------------------------------------------------------------------------------

    def nachricht(self) -> dict[str, Any]:
        """Kopf von CAMERA_UPSERT ohne type/run (PROTOCOL.md, Phase 5)."""

        def fin(x: float) -> float | None:
            return round(x, 3) if math.isfinite(x) else None

        o = self.objektiv
        obj = None
        if o is not None:
            lo, hi = brennweiten(o)
            obj = {"id": o["id"], "name": o.get("name"), "brennweite": [lo, hi] if hi > lo else lo,
                   "lichtstaerke": o.get("lichtstaerke"), "blendenart": self.blendenart,
                   "naheinstellgrenze": o.get("naheinstellgrenze"), "bildkreis": o.get("bildkreis"),
                   "laenge": o.get("laenge"), "frontdurchmesser": o.get("frontdurchmesser")}
        fmt = self._format
        bildkreis = float((o or {}).get("bildkreis") or 0)
        return {
            "name": self.objekt_name,
            "kurzname": self.name,
            "kamera": {"id": self.id, "name": self.eintrag.get("name"), "bajonett": self.eintrag.get("bajonett"),
                       "auflagemass": self.auflagemass},
            "objektiv": obj,
            "format": {"id": fmt["id"], "name": fmt["name"], "modus": fmt.get("modus")},
            "lage": [round(v, 6) + 0.0 for v in self.lage()],
            "sensor_pos": _r(self._sensor), "auge": _r(self.auge), "blick": _r(self.blick, 6),
            "oben": _r(self.oben, 6), "rechts": _r(self.rechts, 6),
            "sensor_mm": [round(v, 3) for v in self.sensor_mm], "aufloesung": list(self.aufloesung),
            "seitenverhaeltnis": round(self.seitenverhaeltnis, 5),
            "brennweite": round(self.brennweite, 3),
            "bildwinkel_h": round(self.bildwinkel_h, 3), "bildwinkel_v": round(self.bildwinkel_v, 3),
            "bildwinkel_d": round(self.bildwinkel_d, 3),
            "blende": round(self.blende, 3), "blendenart": self.blendenart,
            "fokus": fin(self.fokus), "schaerfe_nah": fin(self.schaerfe_nah), "schaerfe_fern": fin(self.schaerfe_fern),
            "hyperfokal": fin(self.hyperfokal), "zerstreuungskreis": self.zerstreuungskreis,
            "teil": self.teil,
            "ausblenden": list(dict.fromkeys(self.ausblenden)),
            "objektiv_vorne": round(self.objektiv_vorne, 3),
            "vignettierung": bool(bildkreis and bildkreis + 1e-6 < math.hypot(*self.sensor_mm)),
        }

    def text(self) -> str:
        """Kurzbeschreibung: „FX6 · Vollformat UHD 3840 × 2160 · 35 mm · T2,8 · Fokus 1,50 m …“."""
        def deg(x: float) -> str:
            return f"{x:.1f}".replace(".", ",")

        return (f"{self.name} · {self._format['name']} · {self.brennweite:g} mm · "
                f"{blende_text(self.blende, self.blendenart)} · Fokus {mm_text(self.fokus)} · "
                f"Bildwinkel {deg(self.bildwinkel_h)}° × {deg(self.bildwinkel_v)}° · "
                f"Schärfe {mm_text(self.schaerfe_nah)} bis {mm_text(self.schaerfe_fern)}")

    def __repr__(self) -> str:
        obj = (self.objektiv or {}).get("name") or "ohne Objektiv"
        return f"<Kamera {self.objekt_name}: {self.eintrag.get('name')}, {obj}, {self.text()}>"


# ---------------------------------------------------------------------------------------------------------------------
# Zubehör


class Zubehoer:
    """Kamerazubehör aus dem Katalog (Käfig, Baseplate, Stangen, Rosette, Akkuplatte, Akku …). Erzeugt mit
    ``lager.kamerazubehoer(id)``; ``verbauen`` setzt es (auch an einen Bezugspunkt) und meldet die Stücklistenzeile."""

    def __init__(self, entry: dict[str, Any]) -> None:
        self.eintrag = entry
        self.id: str = entry["id"]
        self.name: str = str(entry.get("name") or entry["id"])
        self.typ: str = str(entry.get("typ") or "sonstiges")
        self.gewicht: float | None = float(entry["gewicht"]) if entry.get("gewicht") else None
        self.lage = None  # Location des zuletzt verbauten Stücks
        self._n = 0

    def bezugspunkte(self) -> list[str]:
        return sorted((self.eintrag.get("bezugspunkte") or {}).keys()) + ["ursprung"]

    def bezugspunkt(self, name: str, *, lokal: bool = False):
        """Bezugspunkt als Location: nach ``verbauen`` in Weltkoordinaten (zuletzt verbautes Stück), sonst lokal."""
        from build123d import Location

        p = (0.0, 0.0, 0.0) if name == "ursprung" else _local_point(self.eintrag, name)
        local = Location(p)
        if lokal or self.lage is None:
            return local
        return self.lage * local

    def form(self) -> dict[str, Any]:
        """Formen in lokalen Koordinaten: aus ``geometrie`` oder vereinfacht aus ``masse`` (``standard_zubehoer``)."""
        formen = geometrie(self.eintrag, self.name)
        return formen if formen is not None else standard_zubehoer(self.eintrag)

    def verbauen(self, name: str, *, an: Any = None, bezug: str | None = None, lage: Any = None,
                 drehung: tuple[float, float, float] | None = None):
        """Zubehör setzen: ``an`` (Location oder Punkt) mit dem eigenen Bezugspunkt ``bezug`` (Achsen gleich), oder
        ``lage`` (Location). ``drehung`` (Grad um x, y, z) dreht vorher um den Bezugspunkt. Gibt die Form (bei
        mehreren Teilen einen Compound) mit label = name zurück und meldet die Stücklistenzeile an."""
        from build123d import Compound, Location, Rot

        if not isinstance(name, str) or not name.strip():
            raise KameraError(f"{self.name}: verbauen braucht einen Namen, z. B. verbauen(\"Rig/Baseplate\", ...)")
        label = name.strip().strip("/").replace("#", "-")
        if an is not None and lage is not None:
            raise KameraError("verbauen: entweder an= (mit bezug=) oder lage= angeben")
        rot = Rot(*drehung) if drehung else Location()
        if an is not None:
            pt = self.bezugspunkt(bezug or "ursprung", lokal=True)
            loc = ausrichten(an, pt * rot.inverse())
        elif lage is not None:
            loc = (lage if _is_location(lage) else Location(_v(lage, "lage"))) * rot
        else:
            loc = rot
        self._n += 1
        token = f"zubehoer:{id(self)}:{self._n}"
        formen = self.form()
        kids = _place(formen, loc, lambda _label: token)
        if len(kids) == 1:
            shape = kids[0]
            shape.label = label
        else:
            shape = Compound(label=label, children=kids)
            shape.lager_token = token
        m = self.eintrag.get("masse") or {}
        groesse = (" × ".join(f"{float(m[k]):g}" for k in ("b", "h", "t") if k in m)
                   or (f"Ø {float(m['d']):g}" + (f" × {float(m['l']):g}" if "l" in m else "") if "d" in m else ""))
        _register(_piece(self.eintrag, name=label, art="kamerazubehoer",
                         groesse=(f"{groesse} mm" if groesse else self.typ).replace(".", ","), token=token), shape)
        self.lage = loc
        return shape

    def __repr__(self) -> str:
        return f"<Kamerazubehör {self.id!r}: {self.name}, {self.typ}>"


# ---------------------------------------------------------------------------------------------------------------------


def kamera(kamera_id: str, objektiv: str | None = None, *, brennweite: float | None = None, format: str | None = None,  # noqa: A002
           blende: float | None = None, fokus: float | str | None = None, name: str | None = None,
           zerstreuungskreis: float | None = None) -> Kamera:
    """Kamera aus dem Katalog (id oder eindeutiger Suchtext, z. B. "sony-fx6" oder "fx6") mit Objektiv (id oder
    Suchtext), Format (id wie "ff-uhd" oder Stichwort "dci", "s35"), Brennweite (mm, bei Zoom innerhalb des Bereichs),
    Blende (Blendenzahl bzw. T-Wert, Standard 2,8 oder die Lichtstärke), Fokus (mm ab Sensorebene, Standard: Entfernung
    zum Blickpunkt) und Namen (Standard: Kurzname der Kamera, z. B. "FX6"). Lage danach mit ``.setzen(...)`` oder
    ``.an(...)``."""
    entry = _find("kamera", kamera_id)
    lens = _find("objektiv", objektiv) if objektiv is not None else None
    if lens is not None and lens.get("bajonett") != entry.get("bajonett"):
        raise KameraError(f"{lens.get('name')} hat Bajonett {lens.get('bajonett')!r}, {entry.get('name')} "
                          f"{entry.get('bajonett')!r}. Ein Adapter steht nicht im Inventar.")
    label = str(name or entry.get("kurzname") or entry["id"]).strip().strip("/").replace("#", "-").replace("/", "-")
    if not label:
        raise KameraError("name darf nicht leer sein")
    cam = Kamera(entry, lens, name=label)
    cam.einstellen(format=format, brennweite=brennweite, blende=blende, fokus=fokus,
                   zerstreuungskreis=zerstreuungskreis)
    if lens is not None:
        bk = float(lens.get("bildkreis") or 0)
        diag = math.hypot(*cam.sensor_mm)
        if bk and bk + 1e-6 < diag:
            _warn(f"Kamera {label}: Bildkreis von {lens.get('name')} ({bk:g} mm) ist kleiner als die Diagonale des "
                  f"Formats {cam.format['name']} ({diag:.1f} mm): die Ecken vignettieren")
    hook = kevcad._hooks.get("kamera")
    if hook is not None:
        hook(cam)
    return cam


def kamerazubehoer(zubehoer_id: str) -> Zubehoer:
    """Kamerazubehör aus dem Katalog (id oder eindeutiger Suchtext, z. B. "tilta-es-t20-qrbp" oder "lws 15x150")."""
    return Zubehoer(_find("kamerazubehoer", zubehoer_id))
