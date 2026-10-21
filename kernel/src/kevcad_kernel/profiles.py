"""Querschnitte der Stangenware (KATALOG.md, Entscheidung P2): je ``art`` eine Funktion Maße → build123d-Fläche.

Alle Querschnitte liegen in der XY-Ebene mit der Mitte des Hüllrechtecks im Ursprung:

| art | Lage |
|---|---|
| rohr, rund | Kreis(ring) um den Ursprung |
| vierkantrohr, vierkant | Quadrat a × a |
| rechteckrohr | b in X, h in Y |
| flach | b in X, s in Y |
| holz | b in X, h in Y |
| winkel | Schenkel a in Y (links), Schenkel b in X (unten), Wurzelradius r, Kantenradius r/2 an den Enden |
| u_profil | Steg h in Y links, Flansche b in X nach rechts offen |
| nutprofil | a × b (Vorgabe raster × raster) mit T-Nuten je Rasterfeld außen und Kernbohrung je Feld |

``flaeche_mm2`` rechnet geschlossen (ohne build123d). Beim Nutprofil ist die Kontur nur angedeutet; seine Fläche ist
ein Richtwert typischer Aluprofile (leicht 0,34 · Raster², schwer 0,45 · Raster² je Rasterfeld, z. B. 40 × 40 leicht
544 mm² ≈ 1,47 kg/m). ``kg_je_m`` nimmt den Tabellenwert aus dem Katalog, sonst Fläche × Dichte.
"""

from __future__ import annotations

import math
from typing import Any

from kevcad_kernel.catalog import STANGENWARE, TEXT_MASSE, number


def numeric(masse: dict[str, Any]) -> dict[str, float]:
    return {k: v for k, v in ((k, number(v)) for k, v in (masse or {}).items() if k not in TEXT_MASSE)
            if v is not None}


def default_radius(s: float) -> float:
    """Außenradius kalt gefertigter Hohlprofile (EN 10219-2): 2·s bis s = 6, sonst 2,5·s."""
    return 2.0 * s if s <= 6 else 2.5 * s


def _hollow_radii(width: float, height: float, s: float, r: float | None) -> tuple[float, float]:
    ro = default_radius(s) if r is None else r
    ro = max(0.0, min(ro, 0.49 * min(width, height)))
    return ro, max(ro - s, 0.0)


def flaeche_mm2(art: str, masse: dict[str, Any]) -> float:
    """Querschnittsfläche in mm² (Nutprofil: Richtwert, siehe oben)."""
    m = numeric(masse)
    k = 4.0 - math.pi
    if art == "rohr":
        d, s = m["d"], m["s"]
        return math.pi / 4.0 * (d * d - (d - 2 * s) ** 2)
    if art == "vierkantrohr":
        a, s = m["a"], m["s"]
        ro, ri = _hollow_radii(a, a, s, m.get("r"))
        return (a * a - k * ro * ro) - ((a - 2 * s) ** 2 - k * ri * ri)
    if art == "rechteckrohr":
        b, h, s = m["b"], m["h"], m["s"]
        ro, ri = _hollow_radii(b, h, s, m.get("r"))
        return (b * h - k * ro * ro) - ((b - 2 * s) * (h - 2 * s) - k * ri * ri)
    if art == "flach":
        return m["b"] * m["s"]
    if art == "rund":
        return math.pi / 4.0 * m["d"] ** 2
    if art == "vierkant":
        return m["a"] ** 2
    if art == "holz":
        return m["b"] * m["h"]
    if art == "winkel":  # EN 10056-1: Wurzelradius r innen, Kantenradius r/2 an beiden Schenkelenden
        a, b, s, r = m["a"], m["b"], m["s"], m.get("r") or 0.0
        return s * (a + b - s) + (1.0 - math.pi / 4.0) * (r * r - 2.0 * (r / 2.0) ** 2)
    if art == "u_profil":
        return m["h"] * m["s"] + 2.0 * (m["b"] - m["s"]) * m["t"]
    if art == "nutprofil":
        raster = m["raster"]
        cells = max(1, round((m.get("a") or raster) / raster)) * max(1, round((m.get("b") or raster) / raster))
        heavy = str((masse or {}).get("variante") or "leicht").lower() == "schwer"
        return (0.45 if heavy else 0.34) * raster * raster * cells
    raise ValueError(f"art {art!r} hat keinen Querschnitt (keine Stangenware)")


def kg_je_m(item: dict[str, Any], material: dict[str, Any] | None) -> float | None:
    """Gewicht je Meter: Tabellenwert ``kg_je_m`` oder Fläche × Dichte (mm² · g/cm³ / 1000 = kg/m)."""
    table = number(item.get("kg_je_m"))
    if table is not None:
        return table
    if item.get("art") not in STANGENWARE or not material:
        return None
    dichte = number(material.get("dichte"))
    if dichte is None:
        return None
    return flaeche_mm2(item["art"], item.get("masse") or {}) * dichte / 1000.0


# ---------------------------------------------------------------------------------------------------------------------
# Flächen (build123d)


def querschnitt(art: str, masse: dict[str, Any]):
    """build123d-Fläche (Face, beim Nutprofil eine Fläche mit Löchern) mit der Mitte des Hüllrechtecks im Ursprung."""
    from build123d import Circle, Pos, Rectangle, RectangleRounded

    m = numeric(masse)
    if art == "rohr":
        d, s = m["d"], m["s"]
        shape = Circle(d / 2) - Circle(d / 2 - s)
    elif art == "vierkantrohr":
        a, s = m["a"], m["s"]
        ro, ri = _hollow_radii(a, a, s, m.get("r"))
        outer = RectangleRounded(a, a, ro) if ro > 1e-6 else Rectangle(a, a)
        inner = RectangleRounded(a - 2 * s, a - 2 * s, ri) if ri > 1e-6 else Rectangle(a - 2 * s, a - 2 * s)
        shape = outer - inner
    elif art == "rechteckrohr":
        b, h, s = m["b"], m["h"], m["s"]
        ro, ri = _hollow_radii(b, h, s, m.get("r"))
        outer = RectangleRounded(b, h, ro) if ro > 1e-6 else Rectangle(b, h)
        inner = RectangleRounded(b - 2 * s, h - 2 * s, ri) if ri > 1e-6 else Rectangle(b - 2 * s, h - 2 * s)
        shape = outer - inner
    elif art == "flach":
        shape = Rectangle(m["b"], m["s"])
    elif art == "rund":
        shape = Circle(m["d"] / 2)
    elif art == "vierkant":
        shape = Rectangle(m["a"], m["a"])
    elif art == "holz":
        shape = Rectangle(m["b"], m["h"])
    elif art == "winkel":
        a, b, s, r = m["a"], m["b"], m["s"], m.get("r") or 0.0
        x0, y0 = -b / 2, -a / 2
        shape = Pos(x0 + b / 2, y0 + s / 2) * Rectangle(b, s) + Pos(x0 + s / 2, y0 + a / 2) * Rectangle(s, a)
        if r > 1e-6:
            fill = Pos(x0 + s + r / 2, y0 + s + r / 2) * Rectangle(r, r) - Pos(x0 + s + r, y0 + s + r) * Circle(r)
            shape = shape + fill
            t = r / 2  # Kantenradius an den Schenkelenden (innen)
            for cx, cy in ((x0 + b, y0 + s), (x0 + s, y0 + a)):
                shape = shape - (Pos(cx - t / 2, cy - t / 2) * Rectangle(t, t) - Pos(cx - t, cy - t) * Circle(t))
    elif art == "u_profil":
        h, b, s, t = m["h"], m["b"], m["s"], m["t"]
        x0 = -b / 2
        shape = Pos(x0 + s / 2, 0) * Rectangle(s, h)
        for y in (h / 2 - t / 2, -h / 2 + t / 2):
            shape = shape + Pos(x0 + s + (b - s) / 2, y) * Rectangle(b - s, t)
    elif art == "nutprofil":
        shape = _nutprofil(m, str((masse or {}).get("variante") or "leicht").lower())
    else:
        raise ValueError(f"art {art!r} hat keinen Querschnitt (keine Stangenware)")
    faces = shape.faces()
    return faces[0] if len(faces) == 1 else shape


def _nutprofil(m: dict[str, float], variante: str):
    """Vereinfachte Kontur eines Aluprofils: Rechteck a × b, je Rasterfeld außen eine T-Nut, je Feld eine
    Kernbohrung (Ø 0,85 × Nut, passend zum Gewindekern). Das Gewicht kommt aus kg_je_m im Katalog."""
    from build123d import Circle, Pos, Rectangle, Rot

    raster, nut = m["raster"], m["nut"]
    a, b = m.get("a") or raster, m.get("b") or raster
    nx, ny = max(1, round(a / raster)), max(1, round(b / raster))
    lip = 0.10 * raster * (1.2 if variante == "schwer" else 1.0)  # Stärke der Nutlippe
    depth = 0.15 * raster * (0.8 if variante == "schwer" else 1.0)  # Tiefe der Hinterschneidung
    width = min(1.8 * nut, 0.35 * raster)  # Breite der Hinterschneidung
    eps = 0.5
    slot = (Pos(0, -(lip + eps) / 2 + eps, 0) * Rectangle(nut, lip + eps + depth / 2)
            + Pos(0, -lip - depth / 2, 0) * Rectangle(width, depth))  # Öffnung bei y = 0 nach +y, Nut nach -y

    shape = Rectangle(a, b)
    cuts = []
    xs = [-a / 2 + raster * (i + 0.5) for i in range(nx)]
    ys = [-b / 2 + raster * (j + 0.5) for j in range(ny)]
    for x in xs:
        cuts.append(Pos(x, b / 2) * slot)
        cuts.append(Pos(x, -b / 2) * Rot(0, 0, 180) * slot)
    for y in ys:
        cuts.append(Pos(a / 2, y) * Rot(0, 0, -90) * slot)
        cuts.append(Pos(-a / 2, y) * Rot(0, 0, 90) * slot)
    for x in xs:
        for y in ys:
            cuts.append(Pos(x, y) * Circle(0.425 * nut))
    for c in cuts:
        shape = shape - c
    return shape


def extent_y(face) -> tuple[float, float]:
    bb = face.bounding_box()
    return float(bb.min.Y), float(bb.max.Y)


# ---------------------------------------------------------------------------------------------------------------------
# Stangenware mit Gehrung


def bar(face, laenge: float, gehrung: tuple[float, float] = (0.0, 0.0)):
    """Extrudiert ``face`` entlang +Z ab z = 0. ``laenge`` ist das Maß an der längsten Kante; ``gehrung`` sind die
    Winkel der Schnittflächen an Anfang und Ende in Grad um die X-Achse (0 = gerade).

    Positiver Winkel: die Kante bei +Y bleibt lang, zur -Y-Seite hin wird gekürzt (wie eine Rahmenleiste mit der
    Außenkante bei +Y); negativer Winkel umgekehrt."""
    from build123d import Keep, Plane, extrude, split

    w0, w1 = (float(gehrung[0]), float(gehrung[1]))
    y_min, y_max = extent_y(face)
    hy = y_max - y_min

    def offsets(w: float) -> tuple[float, float]:
        """Kürzung bei (y_max, y_min) für den Winkel w."""
        t = math.tan(math.radians(abs(w)))
        if w > 0:
            return 0.0, hy * t
        if w < 0:
            return hy * t, 0.0
        return 0.0, 0.0

    a_hi, a_lo = offsets(w0)
    b_hi, b_lo = offsets(w1)
    raw = laenge + min(a_hi + b_hi, a_lo + b_lo)
    shortest = raw - max(a_hi + b_hi, a_lo + b_lo)
    if shortest <= 0.5:
        raise ValueError(f"Gehrung {w0:g}°/{w1:g}° ist für {laenge:g} mm bei {hy:g} mm Profilhöhe zu steil: die kurze "
                         "Kante wäre nicht mehr da")
    solid = extrude(face, amount=raw)
    if abs(w0) > 1e-9:
        r = math.radians(w0)
        plane = Plane(origin=(0, y_max if w0 > 0 else y_min, 0), x_dir=(1, 0, 0),
                      z_dir=(0, math.sin(r), math.cos(r)))
        solid = split(solid, bisect_by=plane, keep=Keep.TOP)
    if abs(w1) > 1e-9:
        r = math.radians(w1)
        plane = Plane(origin=(0, y_max if w1 > 0 else y_min, raw), x_dir=(1, 0, 0),
                      z_dir=(0, -math.sin(r), math.cos(r)))
        solid = split(solid, bisect_by=plane, keep=Keep.BOTTOM)
    return solid


# ---------------------------------------------------------------------------------------------------------------------
# Schrauben, Muttern, Scheiben (bd_warehouse)


def fastener_class(art: str, typ: str):
    """bd_warehouse-Klasse für ``typ`` (z. B. SocketHeadCapScrew); prüft, dass sie zur Art passt."""
    from bd_warehouse import fastener as fm

    base = {"schraube": fm.Screw, "mutter": fm.Nut, "scheibe": fm.Washer}[art]
    choices = _subclasses(base)
    cls = choices.get(typ)
    if cls is None:
        import difflib

        close = difflib.get_close_matches(typ, list(choices), n=3, cutoff=0.4)
        raise ValueError(f"typ {typ!r} ist keine bd_warehouse-Klasse für {art}"
                         + (f"; meinten Sie {', '.join(close)}?" if close else f" (z. B. {', '.join(sorted(choices)[:6])})"))
    return cls


def _subclasses(base) -> dict[str, Any]:
    out: dict[str, Any] = {}
    stack = list(base.__subclasses__())
    while stack:
        c = stack.pop()
        out[c.__name__] = c
        stack.extend(c.__subclasses__())
    return out


def fastener(art: str, masse: dict[str, Any], laenge: float | None = None, simple: bool = True):
    """Schraube (mit Länge), Mutter oder Scheibe als build123d-Part, so ausgerichtet wie in bd_warehouse."""
    cls = fastener_class(art, str(masse["typ"]))
    size, norm = str(masse["groesse"]), str(masse["norm"])
    if art == "schraube":
        if laenge is None:
            raise ValueError("Schrauben brauchen laenge (Schaftlänge in mm), z. B. verbauen(laenge=60)")
        return cls(size, float(laenge), norm, simple=simple)
    if art == "mutter":
        return cls(size, norm, simple=simple)
    return cls(size, norm)
