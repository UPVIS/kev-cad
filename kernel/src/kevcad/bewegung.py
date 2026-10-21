"""Animation in model.py: ``from kevcad import animation`` (Phase 5, Strang ANI).

Eine Animation besteht aus Spuren auf gezeigten Teilen. Ein Ziel ist ein Teilname oder ein Baugruppenpräfix: "Wagen"
bewegt alle Teile "Wagen/…". Der Kernel rechnet nach dem Lauf je Bild die Lage (4 × 4) jedes betroffenen Teils; die App
spielt sie flüssig ab (nur Matrizen, kein Neuvernetzen), prüft auf Wunsch Kollisionen und gibt Videos aus.

Beispiel (Wagen rollt 2 m, Räder drehen mit, Ball rollt vor dem Schieber)::

    anim = animation(dauer=8, fps=30, name="Fahrt")
    anim.bewege("Rollwagen", nach=(2000, 0, 0), von=0, bis=6, kurve="weich")
    for i in range(1, 5):
        anim.rolle(f"Rollwagen/Lenkrolle {i}/Rad", auf="Rollwagen", radius=50, achse="y")
    anim.folge("Kugelschieber", "Rollwagen")
    anim.rolle("Bowlingball", auf="Rollwagen", radius=108.5)

Spuren (Zeiten in Sekunden zwischen 0 und ``dauer``, Längen in mm, Winkel in Grad):

- ``bewege(name, nach=(dx, dy, dz), von, bis, kurve)``: verschieben um den Vektor.
- ``drehe(name, achse, winkel, von, bis, kurve)``: drehen um eine Achse.
- ``pfad(name, punkte, von, bis, ausrichten=False, spline=False, kurve, bezug=None)``: entlang einer Polylinie oder
  eines Splines durch ``punkte`` fahren (gleichmäßig nach Bogenlänge). Ohne ``bezug`` fährt das Teil die Form des Pfads
  ab seiner Lage nach (Versatz = Pfadpunkt − erster Punkt); mit ``bezug`` sitzt dieser Punkt des Teils auf dem Pfad.
  ``ausrichten`` dreht das Teil mit der Tangente (Z bleibt oben).
- ``rolle(name, auf=None, radius=None, achse=None)``: Rollbedingung, keine Physik: Drehwinkel = zurückgelegte Strecke
  der Mitte / Radius. ``auf``: das bewegte Teil, mit dem es fährt (es folgt ihm, außer es gehört schon zu dessen
  Baugruppe); ohne ``auf`` rollt es mit seinen eigenen Spuren. ``achse``: feste Drehachse (Rad, mit dem Wagen
  mitgedreht); ohne Achse rollt es frei wie eine Kugel (Achse quer zur Fahrtrichtung). ``radius`` ohne Angabe: halbe
  Höhe des Teils.
- ``folge(name, eltern)``: das Teil folgt allen Bewegungen des Elternteils (wie ein Kind im Baum).
- ``gelenk(name, art="dreh"|"schub", achse, werte={zeit: wert}, grenzen=(min, max), eltern=None, kurve)``: Dreh- oder
  Schubgelenk; ``werte`` sind Schlüsselbilder des Gelenkwinkels (Grad) bzw. -wegs (mm). Werte außerhalb der Grenzen
  werden begrenzt (Warnung).
- ``sichtbar(name, an, zeit)``: ab ``zeit`` ein- oder ausgeblendet; davor gilt das Gegenteil des ersten Eintrags.
- ``ansicht(zeit, lage, ziel, bildwinkel=None, mit=None, kurve)``: Schlüsselbild der Viewer-Kamera (Kamerafahrt);
  ``mit`` = Teil, mit dem Lage und Ziel mitfahren.
- ``erlaube(a, b)``: gewollte Berührung zwischen zwei Teilen (oder Baugruppen); die Kollisionsprüfung meldet sie nicht.

``achse``: ``((x, y, z), (dx, dy, dz))`` (Punkt und Richtung), eine build123d-``Axis``, nur eine Richtung
``(dx, dy, dz)`` oder ``"x"``/``"y"``/``"z"`` (dann durch die Mitte des Teils). ``kurve``: ``"linear"``, ``"weich"``
(langsam an und aus), ``"ein"`` (langsam an), ``"aus"`` (langsam aus).

Reihenfolge je Ziel: erst Drehungen (in der Ruhelage, Achsen wie in model.py), dann Verschiebungen und Pfade, dann die
Bewegung des Elternteils. Außerhalb des Kernels (model.py direkt mit Python) passiert nichts.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any

KURVEN = ("linear", "weich", "ein", "aus")
GELENK_ARTEN = ("dreh", "schub")
_EPS = 1e-9


class AnimationError(ValueError):
    """Fehler in einer Animation; ``line`` ist die Zeile in model.py, an der die Spur angelegt wurde."""

    def __init__(self, message: str, line: int | None = None, filename: str | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.filename = filename


@dataclass
class Spur:
    """Eine Spur, wie sie in model.py angelegt wurde (Werte geprüft, Teilnamen noch nicht)."""

    art: str  # bewege | drehe | pfad | rolle | folge | gelenk | sichtbar | ansicht | erlaube
    ziel: str | None
    werte: dict[str, Any]
    line: int | None = None
    filename: str | None = None

    def ort(self) -> str:
        return f" (Zeile {self.line})" if self.line else ""


def _caller() -> tuple[str | None, int | None]:
    """Datei und Zeile des Aufrufs außerhalb dieses Moduls (in der Regel model.py)."""
    here = os.path.realpath(__file__)
    f = sys._getframe(1)
    while f is not None and os.path.realpath(f.f_code.co_filename) == here:
        f = f.f_back
    if f is None:
        return None, None
    return f.f_code.co_filename, f.f_lineno


def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{what} muss eine Zahl sein, nicht {value!r}") from None
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{what} muss eine endliche Zahl sein, nicht {value!r}")
    return v


def _vec(value: Any, what: str) -> tuple[float, float, float]:
    """(x, y, z) aus Tupel, Liste oder build123d-Vector."""
    if hasattr(value, "X") and hasattr(value, "Y") and hasattr(value, "Z"):
        return float(value.X), float(value.Y), float(value.Z)
    try:
        items = list(value)
    except TypeError:
        raise ValueError(f"{what} braucht drei Zahlen (x, y, z), nicht {value!r}") from None
    if len(items) != 3:
        raise ValueError(f"{what} braucht drei Zahlen (x, y, z), nicht {value!r}")
    return tuple(_num(v, what) for v in items)  # type: ignore[return-value]


def _achse(value: Any, what: str = "achse") -> dict[str, Any]:
    """Achse als {"punkt": (x,y,z) | None, "richtung": (dx,dy,dz)}; Punkt None = Mitte des Teils."""
    if value is None:
        raise ValueError(f"{what} fehlt: ((x, y, z), (dx, dy, dz)), Axis oder \"x\"/\"y\"/\"z\"")
    if isinstance(value, str):
        key = value.strip().lower()
        dirs = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0),
                "-x": (-1.0, 0.0, 0.0), "-y": (0.0, -1.0, 0.0), "-z": (0.0, 0.0, -1.0)}
        if key not in dirs:
            raise ValueError(f"{what} {value!r} unbekannt: \"x\", \"y\", \"z\" (auch \"-x\" …) oder Punkt und Richtung")
        return {"punkt": None, "richtung": dirs[key]}
    if hasattr(value, "position") and hasattr(value, "direction"):  # build123d Axis
        return {"punkt": _vec(value.position, what), "richtung": _unit(_vec(value.direction, what), what)}
    try:
        items = list(value)
    except TypeError:
        raise ValueError(f"{what}: ((x, y, z), (dx, dy, dz)), Axis oder \"x\"/\"y\"/\"z\", nicht {value!r}") from None
    if len(items) == 2:
        return {"punkt": _vec(items[0], f"{what} (Punkt)"), "richtung": _unit(_vec(items[1], f"{what} (Richtung)"), what)}
    if len(items) == 3:
        return {"punkt": None, "richtung": _unit(_vec(items, what), what)}
    raise ValueError(f"{what}: ((x, y, z), (dx, dy, dz)), Axis oder \"x\"/\"y\"/\"z\", nicht {value!r}")


def _unit(v: tuple[float, float, float], what: str) -> tuple[float, float, float]:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if n < 1e-12:
        raise ValueError(f"{what}: Richtung (0, 0, 0) hat keine Richtung")
    return v[0] / n, v[1] / n, v[2] / n


def _name(value: Any, what: str = "name") -> str:
    if not isinstance(value, str) or not value.strip().strip("/"):
        raise ValueError(f"{what} muss ein Teilname oder Baugruppenpräfix als Text sein, z. B. \"Wagen\" oder "
                         f"\"Wagen/Rad 1\", nicht {value!r}")
    return value.strip().strip("/")


def _kurve(value: Any) -> str:
    key = str(value).strip().lower() if value is not None else "linear"
    if key not in KURVEN:
        raise ValueError(f"kurve {value!r} unbekannt (erlaubt: {', '.join(repr(k) for k in KURVEN)})")
    return key


class Animation:
    """Spuren einer Animation; anlegen mit ``animation(dauer, fps, name)``. Alle Methoden geben die Animation zurück
    (verkettbar)."""

    def __init__(self, dauer: float, fps: float = 30, name: str | None = None) -> None:
        self.dauer = _num(dauer, "dauer")
        if self.dauer <= 0:
            raise ValueError(f"dauer muss größer als 0 s sein, nicht {dauer!r}")
        if self.dauer > 3600:
            raise ValueError(f"dauer {dauer!r} s ist zu lang (höchstens 3600 s)")
        self.fps = _num(fps, "fps")
        if not 1 <= self.fps <= 240:
            raise ValueError(f"fps {fps!r} liegt außerhalb von 1 bis 240")
        if self.dauer * self.fps > 20_000:
            raise ValueError(f"{self.dauer:g} s × {self.fps:g} fps ergibt zu viele Bilder (höchstens 20.000)")
        self.name = name.strip() if isinstance(name, str) and name.strip() else None
        if name is not None and self.name is None:
            raise ValueError(f"name muss ein Text sein, nicht {name!r}")
        self.spuren: list[Spur] = []
        self.filename, self.line = _caller()

    def __repr__(self) -> str:
        return f"Animation({self.name or 'ohne Namen'!s}, {self.dauer:g} s, {self.fps:g} fps, {len(self.spuren)} Spuren)"

    # -- Hilfen --------------------------------------------------------------------------------------------------------

    def _zeit(self, value: Any, what: str) -> float:
        t = _num(value, what)
        if t < -_EPS or t > self.dauer + _EPS:
            raise ValueError(f"{what}={t:g} liegt außerhalb der Dauer 0 bis {self.dauer:g} s")
        return min(max(t, 0.0), self.dauer)

    def _bereich(self, von: Any, bis: Any) -> tuple[float, float]:
        a = self._zeit(von, "von")
        b = self.dauer if bis is None else self._zeit(bis, "bis")
        if b < a:
            raise ValueError(f"bis={b:g} liegt vor von={a:g}")
        return a, b

    def _add(self, art: str, target: str | None, /, **werte: Any) -> Animation:
        filename, line = _caller()
        self.spuren.append(Spur(art=art, ziel=target, werte=werte, line=line, filename=filename))
        return self

    # -- Spuren --------------------------------------------------------------------------------------------------------

    def bewege(self, name: str, nach: Any, von: float = 0, bis: float | None = None, kurve: str = "linear") -> Animation:
        """Verschiebt ``name`` (Teil oder Baugruppe) zwischen ``von`` und ``bis`` um ``nach`` = (dx, dy, dz) mm."""
        a, b = self._bereich(von, bis)
        return self._add("bewege", _name(name), nach=_vec(nach, "nach"), von=a, bis=b, kurve=_kurve(kurve))

    def drehe(self, name: str, achse: Any, winkel: float, von: float = 0, bis: float | None = None,
              kurve: str = "linear") -> Animation:
        """Dreht ``name`` zwischen ``von`` und ``bis`` um ``winkel`` Grad um ``achse`` (rechte Hand)."""
        a, b = self._bereich(von, bis)
        return self._add("drehe", _name(name), achse=_achse(achse), winkel=_num(winkel, "winkel"), von=a, bis=b,
                         kurve=_kurve(kurve))

    def pfad(self, name: str, punkte: Any, von: float = 0, bis: float | None = None, ausrichten: bool = False,
             spline: bool = False, kurve: str = "linear", bezug: Any = None) -> Animation:
        """Fährt ``name`` entlang ``punkte`` (mindestens 2), als Polylinie oder mit ``spline=True`` als glatte Kurve
        durch alle Punkte."""
        a, b = self._bereich(von, bis)
        try:
            pts = [_vec(p, f"punkte[{i}]") for i, p in enumerate(list(punkte))]
        except TypeError:
            raise ValueError(f"punkte muss eine Liste von Punkten (x, y, z) sein, nicht {punkte!r}") from None
        if len(pts) < 2:
            raise ValueError("pfad braucht mindestens 2 Punkte")
        if all(math.dist(pts[0], p) < 1e-9 for p in pts[1:]):
            raise ValueError("pfad: alle Punkte liegen aufeinander, der Pfad hat keine Länge")
        return self._add("pfad", _name(name), punkte=pts, von=a, bis=b, ausrichten=bool(ausrichten),
                         spline=bool(spline), kurve=_kurve(kurve),
                         bezug=_vec(bezug, "bezug") if bezug is not None else None)

    def rolle(self, name: str, auf: str | None = None, radius: float | None = None, achse: Any = None) -> Animation:
        """Rollbedingung: ``name`` dreht sich um zurückgelegte Strecke / ``radius`` (wie ein Rad oder eine Kugel)."""
        r = None
        if radius is not None:
            r = _num(radius, "radius")
            if r <= 0:
                raise ValueError(f"radius muss größer als 0 mm sein, nicht {radius!r}")
        return self._add("rolle", _name(name), auf=_name(auf, "auf") if auf is not None else None, radius=r,
                         achse=_achse(achse) if achse is not None else None)

    def folge(self, name: str, eltern: str) -> Animation:
        """``name`` folgt allen Bewegungen von ``eltern`` (Teil oder Baugruppe)."""
        kind, elt = _name(name), _name(eltern, "eltern")
        if kind == elt:
            raise ValueError(f"folge: {kind!r} kann nicht sich selbst folgen")
        return self._add("folge", kind, eltern=elt)

    def gelenk(self, name: str, art: str = "dreh", achse: Any = None, werte: Any = None,
               grenzen: Any = None, eltern: str | None = None, kurve: str = "weich") -> Animation:
        """Dreh- oder Schubgelenk: ``werte`` = Schlüsselbilder {zeit: wert} (Grad bzw. mm) oder [(zeit, wert), …]."""
        kind = str(art).strip().lower()
        if kind not in GELENK_ARTEN:
            raise ValueError(f"gelenk: art {art!r} unbekannt (\"dreh\" oder \"schub\")")
        if werte is None:
            raise ValueError("gelenk braucht werte, z. B. werte={0: 0, 2: 90}")
        items = list(werte.items()) if isinstance(werte, dict) else list(werte)
        keys: list[tuple[float, float]] = []
        for item in items:
            try:
                t, v = item
            except (TypeError, ValueError):
                raise ValueError(f"gelenk: Schlüsselbild {item!r} ist kein Paar (zeit, wert)") from None
            keys.append((self._zeit(t, "zeit"), _num(v, "wert")))
        if not keys:
            raise ValueError("gelenk braucht mindestens ein Schlüsselbild in werte")
        keys.sort(key=lambda k: k[0])
        for (t0, _), (t1, _) in zip(keys, keys[1:]):
            if abs(t1 - t0) < _EPS:
                raise ValueError(f"gelenk: zwei Schlüsselbilder bei {t0:g} s")
        lim = None
        if grenzen is not None:
            try:
                lo, hi = grenzen
            except (TypeError, ValueError):
                raise ValueError(f"grenzen braucht (min, max), nicht {grenzen!r}") from None
            lo = -math.inf if lo is None else _num(lo, "grenzen (min)")
            hi = math.inf if hi is None else _num(hi, "grenzen (max)")
            if lo > hi:
                raise ValueError(f"grenzen: min {lo:g} liegt über max {hi:g}")
            lim = (lo, hi)
        return self._add("gelenk", _name(name), gelenk=kind, achse=_achse(achse), werte=keys, grenzen=lim,
                         eltern=_name(eltern, "eltern") if eltern is not None else None, kurve=_kurve(kurve))

    def sichtbar(self, name: str, an: bool = True, zeit: float = 0) -> Animation:
        """Blendet ``name`` ab ``zeit`` ein (``an=True``) oder aus."""
        return self._add("sichtbar", _name(name), an=bool(an), zeit=self._zeit(zeit, "zeit"))

    def ansicht(self, zeit: float, lage: Any, ziel: Any, bildwinkel: float | None = None, mit: str | None = None,
                kurve: str = "weich") -> Animation:
        """Schlüsselbild der Viewer-Kamera: Kamera bei ``lage`` blickt auf ``ziel`` (mm); ``bildwinkel`` vertikal in
        Grad (sonst unverändert); ``mit``: Teil, mit dem die Kamera mitfährt. ``kurve`` gilt für den Weg zu diesem
        Schlüsselbild."""
        p, z = _vec(lage, "lage"), _vec(ziel, "ziel")
        if math.dist(p, z) < 1e-6:
            raise ValueError("ansicht: lage und ziel fallen zusammen")
        fov = None
        if bildwinkel is not None:
            fov = _num(bildwinkel, "bildwinkel")
            if not 1 <= fov <= 170:
                raise ValueError(f"bildwinkel {fov:g}° liegt außerhalb von 1 bis 170°")
        return self._add("ansicht", None, zeit=self._zeit(zeit, "zeit"), lage=p, ziel=z, bildwinkel=fov,
                         mit=_name(mit, "mit") if mit is not None else None, kurve=_kurve(kurve))

    def erlaube(self, a: str, b: str) -> Animation:
        """Gewollte Berührung zwischen ``a`` und ``b`` (Teile oder Baugruppen): keine Kollisionsmeldung."""
        return self._add("erlaube", _name(a, "a"), b=_name(b, "b"))


def animation(dauer: float, fps: float = 30, name: str | None = None) -> Animation:
    """Neue Animation mit ``dauer`` Sekunden und ``fps`` Bildern je Sekunde. Mehrere Animationen je Projekt brauchen
    verschiedene Namen (ohne Namen: "Animation", "Animation 2", …)."""
    anim = Animation(dauer, fps, name)
    from kevcad import _hooks

    hook = _hooks.get("animation")
    if hook is not None:
        hook(anim)
    return anim
