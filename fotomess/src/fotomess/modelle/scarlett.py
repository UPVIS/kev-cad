"""Focusrite Scarlett 2i2 (4. Generation) als Messmodell (build123d), nach Kevins Video IMG_5186.MOV.

Hersteller: 180 x 117 x 47,5 mm (Breite x Tiefe x Höhe), 595 g; offen ist, ob Tiefe und Höhe die Drehknöpfe bzw.
die Füße einschließen. Das Modell trennt deshalb das Gehäuse von den Überständen:

- Gehäuse: stranggepresstes Aluminiumrohr, das in der Tiefe (Y) verläuft. Der Querschnitt (Breite x Höhe, XZ) ist ein
  Rechteck mit gerundeten Ecken (Radius `kanten_r`), die vier Kanten entlang der Tiefe sind also gerundet; die Kanten
  an Vorder- und Rückseite sind scharf (Kontrollbild und Object-Capture-Netz vom 22.10.2026). Vorn und hinten sitzt
  je eine schwarze Blende um `blende_t` vertieft, mit einem roten Rand der Breite `rand` darum (die Rot-Schwarz-Kante
  ist im Bild eine starke Kante und gehört deshalb ins Modell).
- Vorn (-Y) die Überstände: zwei Gain-Knöpfe und der Kopfhörerknopf (Überstand `knopf_h`), der große
  Output-Knopf (`gross_h`), die vergoldete Kopfhörerbuchse (fest). Lage und Durchmesser aus dem Object-Capture-Netz
  und der Draufsicht (fest, relativ zu Breite und Höhe).
- Unten vier Gummifüße (`fuss_h`). Die Unterseite ist im Video nie zu sehen, die Füße sind von oben verdeckt:
  `fuss_h` ist aus den Bildern nicht messbar und bleibt fest (Annahme 1,5 mm).
- Rückseite: XLR-Kombibuchsen, Klinken, USB-C und Kensington liegen bündig in der Blende (kein Überstand).

Koordinaten: Auflage z = 0 (Unterseite der Füße), Gehäusemitte bei x = y = 0, x entlang der Breite, Vorderseite
(Knöpfe) zeigt nach -y. Bauer für fotocad.cad_netz: scarlett_netz(p) -> Compound mit benannten Teilen.
"""
from __future__ import annotations

from build123d import Align, Axis, Box, Compound, Cylinder, Pos, Rot, fillet

P = dict(
    breite=180.0,       # Hersteller, Maßstab (das Rohr hat seitlich keine Anbauten)
    tiefe=110.0,        # Gehäusetiefe ohne Knöpfe (Start zwischen 117 und dem Object-Capture-Wert)
    hoehe=46.0,         # Gehäusehöhe ohne Füße
    kanten_r=5.0,       # Radius der vier Kanten entlang der Tiefe
    knopf_h=12.0,       # Überstand Gain-Knöpfe und Kopfhörerknopf vor der Gehäusevorderkante
    gross_h=12.0,       # Überstand großer Output-Knopf
    fuss_h=1.5,         # Gummifüße (nicht messbar, siehe oben)
    rand=3.0,           # roter Rand um die Blenden (Wandstärke des Rohrs)
    blende_t=0.5,       # Blende gegenüber der Rohrkante vertieft
    buchse_h=10.0,      # Überstand Kopfhörerbuchse (vergoldet)
)

# Knöpfe: (Name, x relativ zur halben Breite, z relativ zur Gehäusehöhe, Durchmesser, Überstand-Parameter)
KNOEPFE = (
    ("Knopf-Gain1", -0.794, 0.67, 12.5, "knopf_h"),
    ("Knopf-Gain2", -0.528, 0.67, 12.5, "knopf_h"),
    ("Knopf-Output", 0.300, 0.52, 25.0, "gross_h"),
    ("Knopf-Kopfhoerer", 0.806, 0.80, 11.0, "knopf_h"),
    ("Buchse-Kopfhoerer", 0.806, 0.40, 9.0, "buchse_h"),
)
FUSS_D, FUSS_RAND_X, FUSS_RAND_Y = 10.0, 18.0, 15.0

GEHAEUSE = "Gehaeuse"


def _rohr(b, t, h, r):
    """Quader b x t x h (Mitte im Ursprung) mit gerundeten Kanten entlang Y."""
    k = Box(b, t, h)
    if r > 0.05:
        k = fillet(k.edges().filter_by(Axis.Y), radius=min(r, b / 2 - 0.1, h / 2 - 0.1))
    return k


def scarlett(p=P):
    p = dict(P, **p)
    b, t, h, r = p["breite"], p["tiefe"], p["hoehe"], p["kanten_r"]
    z0 = p["fuss_h"]
    zm = z0 + h / 2
    geh = Pos(0, 0, zm) * _rohr(b, t, h, r)
    # Blenden vorn und hinten um blende_t vertieft (Taschen mit dem Innenmaß des Rohrs)
    bi, hi, ri = b - 2 * p["rand"], h - 2 * p["rand"], max(r - p["rand"], 0.3)
    for sy in (-1, 1):
        tasche = _rohr(bi, 2 * p["blende_t"], hi, ri)
        geh -= Pos(0, sy * t / 2, zm) * tasche
    geh.label = GEHAEUSE
    teile = [geh]
    vorn = -t / 2
    for name, fx, fz, d, ueber in KNOEPFE:
        laenge = p[ueber] + p["blende_t"] + 0.5           # 0,5 mm in der Blende versenkt
        mitte_y = vorn - p[ueber] + laenge / 2
        k = Pos(fx * b / 2, mitte_y, z0 + fz * h) * Rot(90, 0, 0) * Cylinder(d / 2, laenge)
        k.label = name
        teile.append(k)
    for i, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        f = Pos(sx * (b / 2 - FUSS_RAND_X), sy * (t / 2 - FUSS_RAND_Y), 0) * \
            Cylinder(FUSS_D / 2, z0 + 0.3, align=(Align.CENTER, Align.CENTER, Align.MIN))
        f.label = f"Fuss{i + 1}"
        teile.append(f)
    return Compound(label="Focusrite Scarlett 2i2 4th Gen", children=teile)


def scarlett_netz(p, **_):
    return scarlett(p)


def rote_dreiecke(netz):
    """Dreiecke des roten Aluminiums (Gehäuse ohne die vertieften schwarzen Blenden) eines fotomess.ParamNetz, für
    die Farbteil-Prüfung der Startlagen (Ausgleich.iou_farbe). Blende = Fläche mit Normale entlang Y, die um
    blende_t hinter der Rohrkante liegt."""
    import numpy as np
    V, T = netz.V0, netz.tris
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    cy = (a[:, 1] + b[:, 1] + c[:, 1]) / 3
    halb = float(netz.p0.get("tiefe", P["tiefe"])) / 2
    blende = (np.abs(n[:, 1]) > 0.9) & (np.abs(cy) < halb - 0.5 * float(netz.p0.get("blende_t", P["blende_t"])))
    gehaeuse = np.array([netz.teile[i] == GEHAEUSE for i in netz.tri_teil])
    return gehaeuse & ~blende


def gesamt(p=P):
    """Hüllmaße mit Überständen: Tiefe mit dem weitesten Knopf, Höhe mit Füßen."""
    p = dict(P, **p)
    ueber = max(p["knopf_h"], p["gross_h"], p["buchse_h"])
    return dict(breite=p["breite"], tiefe=p["tiefe"] + ueber, hoehe=p["hoehe"] + p["fuss_h"], ueberstand_vorn=ueber)


DATEI = __file__ + ":scarlett_netz"
