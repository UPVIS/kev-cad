"""Manfrotto MVH502AH (502HD) Fluid-Videokopf mit flacher Basis, vereinfacht für den Kamerakatalog von Kev CAD.

Lokale Koordinaten in mm: +x nach vorn (Blickrichtung der Kamera), +y links, +z oben.
Ursprung: Mitte der Unterseite der Basis, dort sitzt das 3/8"-16-Innengewinde. Die Schwenkachse ist die z-Achse.

Gesichert: Höhe 13 cm, Gewicht 1,7 kg, Traglast 7 kg, Federausgleich 4 kg bei 55 mm Schwerpunkthöhe (Manfrotto-
Anleitung MVH502A/MVH502AH); Schnellwechselplatte 504PLONG 140 × 50 × 10,7 mm, 120 g, mit 1/4"- und 3/8"-Schraube
(Manfrotto); Plattenweg 83 mm (Adorama). Manfrotto veröffentlicht keine Maßzeichnung und keine CAD-Daten; alle übrigen
Maße sind an der Strichzeichnung der Anleitung abgeschätzt und am Wert als Annahme markiert.
Lage der Bedienteile wie in der Anleitung: großer Neigeknopf links (+y), Schwenkarm rechts (-y) nach hinten.
"""

from __future__ import annotations

import math

from build123d import Align, Axis, Box, Cylinder, Part, Pos, Rot, Shape, fillet

# Gesicherte Werte
HOEHE = 130.0  # Unterseite Basis bis Oberseite Schnellwechselplatte; Anleitung „13 cm“ (Annahme: inklusive Platte)
PLATTE_L, PLATTE_B, PLATTE_D = 140.0, 50.0, 10.7  # 504PLONG (Manfrotto)
PLATTENWEG = 83.0  # Verschiebeweg der Platte in der Aufnahme (Adorama)
TRAGLAST_KG = 7.0  # Anleitung; einige Händler nennen 10 kg Sicherheitslast
GEGENGEWICHT_KG = 4.0  # Federausgleich (Anleitung)
SCHWERPUNKT_UEBER_PLATTE = 55.0  # Schwerpunkthöhe, für die der Federausgleich gilt (Anleitung)
GEWINDE_3_8_KERN_D = 8.0  # 3/8"-16 UNC, Kernloch (Norm)
GEWINDE_3_8_TIEFE = 10.0  # Annahme

# Abgeschätzte Maße
BASIS_R, BASIS_H = 38.0, 12.0  # Annahme: flache Basis Ø 76
SCHWENKRING_R, SCHWENKRING_H = 40.0, 20.0  # Annahme: gerändelter Ring der Schwenkdämpfung Ø 80
SCHWENK_OBEN = BASIS_H + SCHWENKRING_H  # 32
NEIGEACHSE_Z = 70.0  # Annahme: Mitte des großen Neigeknopfs in der Zeichnung
TROMMEL_R, TROMMEL_HALB_B = 24.0, 34.0  # Annahme: Neigetrommel Ø 48, 68 breit
SATTEL_X, SATTEL_Y = 32.0, 35.0  # Annahme: Lagerbock des Schwenkteils, halbe Länge / Breite
NEIGEKNOPF_R, NEIGEKNOPF_L = 21.0, 24.0  # Annahme: Ø 42, ragt 24 mm seitlich heraus
ROSETTE_R, ROSETTE_L = 17.0, 6.0  # Annahme: Zahnrosette für den Schwenkarm
AUFNAHME_UNTEN = 104.0  # Annahme: Unterseite der Plattenaufnahme
PLATTE_UNTEN = HOEHE - PLATTE_D  # 119,3
AUFNAHME_L, AUFNAHME_HALB_B = 140.0, 37.0  # Annahme: Aufnahme 140 × 74
SCHIENE_OBEN = 124.0  # Annahme: Oberkante der seitlichen Führungsschienen
SCHWENKARM_L = 330.0  # Annahme: Länge vom Rosettenmittelpunkt bis Griffende
SCHWENKARM_R = 7.0  # Annahme: Rohr Ø 14
GRIFF_R, GRIFF_L = 14.0, 110.0  # Annahme: Gummigriff Ø 28, 110 lang
SCHWENKARM_WINKEL = 20.0  # Annahme: Neigung unter die Waagerechte; die Rosette rastet in 10°-Schritten (Anleitung)
ARM_Y = -(TROMMEL_HALB_B + ROSETTE_L + 7.2)  # Rohrmitte in y, -47,2; Rohr berührt die Rosette nicht

voll = (Align.MIN, Align.MIN, Align.MIN)
boden = (Align.CENTER, Align.CENTER, Align.MIN)


def _quader(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    return Pos(x0, y0, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=voll)


def _zyl_x(r: float, x0: float, x1: float, y: float = 0.0, z: float = 0.0) -> Part:
    """Zylinder entlang x von x0 bis x1."""
    return Pos(x0, y, z) * Rot(0, 90, 0) * Cylinder(r, x1 - x0, align=boden)


def _zyl_y(r: float, y0: float, y1: float, x: float = 0.0, z: float = 0.0) -> Part:
    """Zylinder entlang y von y0 bis y1."""
    return Pos(x, y0, z) * Rot(-90, 0, 0) * Cylinder(r, y1 - y0, align=boden)


def _zyl_z(r: float, z0: float, z1: float, x: float = 0.0, y: float = 0.0) -> Part:
    return Pos(x, y, z0) * Cylinder(r, z1 - z0, align=boden)


def _arm_richtung(winkel: float) -> tuple[float, float, float]:
    """Einheitsvektor des Schwenkarms: nach hinten (-x) und um winkel Grad nach unten."""
    w = math.radians(winkel)
    return (-math.cos(w), 0.0, -math.sin(w))


def _basis() -> Part:
    b = _zyl_z(BASIS_R, 0, BASIS_H)
    b -= _zyl_z(GEWINDE_3_8_KERN_D / 2, -1, GEWINDE_3_8_TIEFE)  # 3/8"-16-Innengewinde, als Kernloch
    return b


def _schwenkteil() -> Part:
    """Schwenkring mit Dämpfung und Lagerbock, in dem die Neigetrommel liegt."""
    s = _zyl_z(SCHWENKRING_R, BASIS_H, SCHWENK_OBEN)
    bock = _quader(-SATTEL_X, SATTEL_X, -SATTEL_Y, SATTEL_Y, SCHWENK_OBEN, NEIGEACHSE_Z)
    bock = fillet(bock.edges().filter_by(Axis.Z), radius=8)  # senkrechte Kanten runden
    s += bock
    s -= _zyl_y(TROMMEL_R + 0.5, -SATTEL_Y - 5, SATTEL_Y + 5, z=NEIGEACHSE_Z)  # Lagerschale, 0,5 mm Luft
    s += _zyl_x(6, SCHWENKRING_R - 1, SCHWENKRING_R + 12, z=BASIS_H + 10)  # Schwenkklemme vorn, Annahme
    return s


def _neigeteil() -> Part:
    """Neigetrommel mit Hals zur Plattenaufnahme, großem Neigeknopf (links) und Zahnrosette (rechts)."""
    n = _zyl_y(TROMMEL_R, -TROMMEL_HALB_B, TROMMEL_HALB_B, z=NEIGEACHSE_Z)
    n += _quader(-28, 28, -30, 30, NEIGEACHSE_Z + 12, AUFNAHME_UNTEN)  # Hals, Annahme
    n += _zyl_y(NEIGEKNOPF_R, TROMMEL_HALB_B, TROMMEL_HALB_B + NEIGEKNOPF_L, z=NEIGEACHSE_Z)
    n += _zyl_y(ROSETTE_R, -TROMMEL_HALB_B - ROSETTE_L, -TROMMEL_HALB_B, z=NEIGEACHSE_Z)
    return n


def _plattenaufnahme() -> Part:
    a = _quader(-AUFNAHME_L / 2, AUFNAHME_L / 2, -AUFNAHME_HALB_B, AUFNAHME_HALB_B, AUFNAHME_UNTEN, PLATTE_UNTEN)
    schiene_innen = PLATTE_B / 2 + 0.3  # 0,3 mm Luft zur Platte
    for y0, y1 in ((schiene_innen, AUFNAHME_HALB_B), (-AUFNAHME_HALB_B, -schiene_innen)):
        a += _quader(-AUFNAHME_L / 2, AUFNAHME_L / 2, y0, y1, PLATTE_UNTEN, SCHIENE_OBEN)
    a += _zyl_y(8, -AUFNAHME_HALB_B - 10, -AUFNAHME_HALB_B + 1, x=45, z=112)  # Plattenklemme, Annahme
    return a


def _schnellwechselplatte(versatz: float) -> Part:
    """504PLONG, Länge in x. Das Langloch nimmt die 1/4"- bzw. 3/8"-Kameraschraube auf."""
    p = _quader(-PLATTE_L / 2, PLATTE_L / 2, -PLATTE_B / 2, PLATTE_B / 2, PLATTE_UNTEN, HOEHE)
    p -= _quader(-40, 40, -3.5, 3.5, PLATTE_UNTEN - 1, HOEHE + 1)  # Langloch 80 × 7, Annahme
    return Pos(versatz, 0, 0) * p


def _schwenkarm(winkel: float) -> Part:
    """Klemmscheibe an der Rosette, Rohr nach hinten unten, Gummigriff am Ende."""
    a = _zyl_y(ROSETTE_R, ARM_Y - 7, -TROMMEL_HALB_B - ROSETTE_L, z=NEIGEACHSE_Z)  # Klemmscheibe
    a += _zyl_y(11, ARM_Y - 17, ARM_Y - 7, z=NEIGEACHSE_Z)  # Klemmknopf, Annahme
    lage = Pos(0, ARM_Y, NEIGEACHSE_Z) * Rot(0, 180 - winkel, 0)  # +x des Rohrs zeigt nach hinten unten
    a += lage * _zyl_x(SCHWENKARM_R, 0, SCHWENKARM_L)
    a += lage * _zyl_x(GRIFF_R, SCHWENKARM_L - GRIFF_L, SCHWENKARM_L)
    return a


def manfrotto_mvh502ah(eintrag: dict | None = None) -> dict[str, Shape]:
    """Fluid-Videokopf als Unterteile. Ursprung Mitte Unterseite der Basis (3/8"-Gewinde), +x vorn, +z oben.

    Optionale Felder im Katalogeintrag:
    - "platte_versatz": Verschiebung der Schnellwechselplatte nach vorn in mm, begrenzt auf ±PLATTENWEG/2.
    - "schwenkarm_winkel": Neigung des Schwenkarms unter die Waagerechte in Grad (Vorgabe 20).
    """
    e = eintrag or {}
    versatz = max(-PLATTENWEG / 2, min(PLATTENWEG / 2, float(e.get("platte_versatz", 0.0))))
    winkel = float(e.get("schwenkarm_winkel", SCHWENKARM_WINKEL))
    return {
        "Basis": _basis(),
        "Schwenkteil": _schwenkteil(),
        "Neigeteil": _neigeteil(),
        "Plattenaufnahme": _plattenaufnahme(),
        "Schnellwechselplatte": _schnellwechselplatte(versatz),
        "Schwenkarm": _schwenkarm(winkel),
    }


def bezugspunkte() -> dict[str, dict]:
    """Benannte Punkte in Kopf-Koordinaten (Vorgabestellung: Platte mittig, Schwenkarm 20° nach unten)."""
    d = _arm_richtung(SCHWENKARM_WINKEL)
    griff = [round(d[0] * (SCHWENKARM_L - GRIFF_L / 2), 1), ARM_Y,
             round(NEIGEACHSE_Z + d[2] * (SCHWENKARM_L - GRIFF_L / 2), 1)]
    return {
        "basis_gewinde_3_8": {"pos": [0.0, 0.0, 0.0], "richtung": [0.0, 0.0, -1.0],
                              "hinweis": "Mitte der Unterseite der Basis, 3/8\"-16-Innengewinde; zeigt zum Stativ"},
        "schwenkachse": {"pos": [0.0, 0.0, 0.0], "richtung": [0.0, 0.0, 1.0],
                         "hinweis": "Schwenkachse (Pan), senkrecht durch die Basismitte"},
        "neigeachse": {"pos": [0.0, 0.0, NEIGEACHSE_Z], "richtung": [0.0, 1.0, 0.0],
                       "hinweis": "Neigeachse (Tilt), Höhe 70 mm ist Annahme aus der Zeichnung; Neigeknopf auf +y"},
        "kameraauflage": {"pos": [0.0, 0.0, HOEHE], "richtung": [0.0, 0.0, 1.0],
                          "hinweis": "Mitte Oberseite der Schnellwechselplatte 504PLONG (Platte mittig); hier "
                                     "greift die 1/4\"- oder 3/8\"-Kameraschraube, Plattenweg ±41,5 mm in x"},
        "schwenkarm_griff": {"pos": griff, "richtung": [round(v, 4) for v in d],
                             "hinweis": "Mitte des Gummigriffs am Schwenkarm, Richtung entlang des Arms"},
    }


MASSEN = {  # g; Summe 1700 g laut Anleitung (Händler: 1600 bis 1691 g). Aufteilung ist Annahme, außer Platte
    "Basis": 150,
    "Schwenkteil": 520,
    "Neigeteil": 420,
    "Plattenaufnahme": 250,
    "Schnellwechselplatte": 120,  # Manfrotto 504PLONG
    "Schwenkarm": 240,
}

QUELLEN = [
    "https://nyw.cap.gov/assets/files/dept/dos/ap/cameras/instructions_Manfrotto_MVH502A-MVH502AH_GB.pdf",
    "https://www.manfrotto.com/global-ja/video-camera-plate-504plong/",
    "https://www.adorama.com/bgmvh502aha.html",
    "https://www.markertek.com/product/man-mvh502ah/manfrotto-mvh502ah-502hd-pro-fluid-video-head-flat-base",
    "https://www.wexphotovideo.com/manfrotto-mvh502ah-pro-video-head-1533216/",
    "https://manfrottospares.com/es/mvh502ah-parts.html",
]
