"""ALUTEC-Rollwagen 05200 für Eurobehälter 600 x 400 als Messmodell (build123d), nach Kevins Video.

Belegt (Hersteller): Außenmaß 610 x 410 mm, vier Lenkrollen Ø 100 mm. Alles andere wird gemessen. Aufbau wie im
Modell der Kev-CAD-Sitzung (Neues Projekt/model.py), vereinfacht auf das, was im Bild Kanten macht:
- Rahmen: Platte mit achteckiger Öffnung, außen und um die Öffnung eine Schürze nach unten, an den Ecken ein Dom
  unter der Platte, oben ein aufgestellter Rand an den Längsseiten (außenbündig, vor den Ecken unterbrochen; die
  Stirnseiten haben keinen, anders als im Modell der Sitzung), Außenecken gefast.
- Lenkrollen: Drehkopf, Gabel, Rad; je Rolle ein Gelenk (Schwenkwinkel um die senkrechte Achse, je Bild frei).
Koordinaten: Boden z = 0 (Räder stehen darauf), Mitte des Wagens im Ursprung, x entlang der Länge.

Bauer für fotocad.cad_netz: rollwagen_netz(p) -> Compound mit benannten Teilen.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Compound, Cylinder, Polygon, Pos, Rot, extrude, offset, Kind

P = dict(
    wagen_l=610.0, wagen_b=410.0, rad_d=100.0,          # Hersteller
    rolle_h=128.0,      # Bauhöhe der Lenkrolle = Unterkante Rahmen über dem Boden (Annahme der Sitzung: 128)
    rahmen_h=35.0,      # Unterkante Schürze bis Oberseite Platte (Annahme: 35)
    steg=45.0,          # Breite des Rahmens zwischen Außenkante und Öffnung (Annahme: 45)
    oeff_fase=100.0,    # Schenkel der Eckschrägen der Öffnung
    eck_fase=20.0,      # Außenecken 45 Grad gefast
    rand_h=19.0, rand_d=5.0, rand_ende=28.0,            # aufgestellter Rand, endet vor der Ecke
    platte_d=4.0, wand_d=4.0, dom_d=80.0,
    schraube_rand=63.0,  # Achse der Lenkrolle von beiden Außenkanten
    rad_b=32.0, drehkopf_d=63.0, kopf_h=14.0, nachlauf=26.0,
)

RAHMEN = "Rahmen"


def achteck(l, b, fx, fy):
    hx, hy = l / 2, b / 2
    pkt = [(hx - fx, hy), (hx, hy - fy), (hx, -hy + fy), (hx - fx, -hy), (-hx + fx, -hy), (-hx, -hy + fy),
           (-hx, hy - fy), (-hx + fx, hy)]
    return Polygon(*reversed(pkt), align=None)


def rollen_lagen(p):
    return [(sx * (p["wagen_l"] / 2 - p["schraube_rand"]), sy * (p["wagen_b"] / 2 - p["schraube_rand"]))
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1))]


def rollwagen(p=P):
    p = dict(P, **p)
    L, B = p["wagen_l"], p["wagen_b"]
    unten = p["rolle_h"]
    oben = unten + p["rahmen_h"]
    umriss = achteck(L, B, p["eck_fase"], p["eck_fase"])
    ol, ob = L - 2 * p["steg"], B - 2 * p["steg"]
    oeffnung = achteck(ol, ob, p["oeff_fase"], p["oeff_fase"])
    platte = Pos(0, 0, oben - p["platte_d"]) * extrude(umriss - oeffnung, amount=p["platte_d"])
    ring_aussen = umriss - offset(umriss, amount=-p["wand_d"], kind=Kind.INTERSECTION)
    ring_innen = offset(oeffnung, amount=p["wand_d"], kind=Kind.INTERSECTION) - oeffnung
    schuerze_h = p["rahmen_h"] - p["platte_d"] + 0.5
    rahmen = platte + Pos(0, 0, unten) * extrude(ring_aussen + ring_innen, amount=schuerze_h)
    for x, y in rollen_lagen(p):
        rahmen += Pos(x, y, unten) * Cylinder(p["dom_d"] / 2, schuerze_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    teile = [rahmen.locate(rahmen.location)]
    teile[0].label = RAHMEN
    rand = []
    for sy in (1, -1):        # nur an den Längsseiten (Kontrollbild 21.10.: die Stirnseiten haben keinen Rand)
        rand.append(Pos(0, sy * (B / 2 - p["rand_d"] / 2), oben - 0.5) *
                    Box(L - 2 * p["rand_ende"], p["rand_d"], p["rand_h"] + 0.5, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    r = rand[0]
    for t in rand[1:]:
        r += t
    r.label = "Rand"
    teile.append(r)
    achse_z = p["rad_d"] / 2
    for i, (x, y) in enumerate(rollen_lagen(p)):
        kopf = Pos(x, y, unten - p["kopf_h"]) * Cylinder(p["drehkopf_d"] / 2, p["kopf_h"], align=(Align.CENTER, Align.CENTER, Align.MIN))
        kopf.label = f"Rolle{i + 1}-Kopf"
        bruecke_z = unten - p["kopf_h"] - 4
        gabel = Pos(x - p["nachlauf"] / 2, y, bruecke_z) * Box(p["nachlauf"] + 40, p["rad_b"] + 12, 4.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
        for sy in (1, -1):
            gabel += Pos(x - p["nachlauf"], y + sy * (p["rad_b"] / 2 + 4), achse_z - 15) * \
                Box(40, 4, bruecke_z + 0.5 - (achse_z - 15), align=(Align.CENTER, Align.CENTER, Align.MIN))
        gabel.label = f"Rolle{i + 1}-Gabel"
        rad = Pos(x - p["nachlauf"], y, achse_z) * Rot(90, 0, 0) * Cylinder(p["rad_d"] / 2, p["rad_b"])
        rad.label = f"Rolle{i + 1}-Rad"
        teile += [kopf, gabel, rad]
    return Compound(label="Rollwagen ALUTEC 05200", children=teile)


def rollwagen_netz(p, **_):
    return rollwagen(p)


def gelenke(p=P):
    """Schwenkgelenk je Lenkrolle (Gabel und Rad drehen um die senkrechte Achse durch die Rollenschraube)."""
    from ..modell import Gelenk
    out = []
    for i, (x, y) in enumerate(rollen_lagen(dict(P, **p))):
        sx, sy = math.copysign(1, x), math.copysign(1, y)
        out.append(Gelenk(f"Rolle {i + 1}", (f"rolle{i + 1}-gabel", f"rolle{i + 1}-rad"), (x, y, 0.0), (0.0, 0.0, 1.0),
                          punkt_ableitung={"schraube_rand": (-sx, -sy, 0.0), "wagen_l": (sx / 2, 0.0, 0.0),
                                           "wagen_b": (0.0, sy / 2, 0.0)}))
    return out


DATEI = __file__ + ":rollwagen_netz"
