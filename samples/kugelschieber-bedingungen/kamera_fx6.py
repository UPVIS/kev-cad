"""Kamerasystem Sony FX6 mit Tilta-Baseplate, 15-mm-Rods, V-Mount-Akku und Cine-Zoom, vereinfacht.

Für den Kamerakatalog von Kev CAD gebaut: je Teil eine Funktion mit der Form in lokalen Koordinaten (mm, Z oben) und
ein Verzeichnis benannter Bezugspunkte (Location).
- Kamera: Ursprung in der Sensormitte, Blickrichtung +x.
- Objektiv: Ursprung in der Mitte der Bajonett-Auflage, optische Achse +x.
Quellen: Sony FX6 Bedienungsanleitung S. 164 „External Dimensions“; Tilta ES-T20-QRBP; 15-mm-LWS-Norm; Fujifilm MK;
IDX DUO-C98P. Was nicht veröffentlicht ist, steht als Annahme am Wert.
"""

from build123d import Align, Box, Cylinder, Location, Part, Pos, Rot, fillet, Axis

# Sony FX6 (ILME-FX6), Sony-Maßzeichnung
FX6_B, FX6_H, FX6_T = 114, 116, 153  # Gehäuse ohne Anbauten
ACHSE_UEBER_BODEN = 74  # Bildachse über der Gehäuseunterseite
ACHSE_LINKS, ACHSE_RECHTS = 62.8, 51.2  # Bildachse zur linken / rechten Gehäuseseite, von hinten gesehen (links = +y)
AUFLAGEMASS = 18.0  # E-Mount: Sensor bis Bajonett-Auflage (Norm)
GEWINDE_14_X, GEWINDE_38_X = 33.0, 61.0  # Stativgewinde unten, hinter der Gehäusevorderkante
HOEHE_MIT_GRIFFEN, LAENGE_MIT_GRIFF = 228, 258
# Tilta-Baseplate und Rods
RODS_ABSTAND = 60  # 15-mm-LWS, Mitte–Mitte
RODS_UNTER_ACHSE = 99  # Annahme (SmallRig-FX6-Kit 99; LWS-Norm 85 passt nicht unter den Body), nachmessen
ROD_D, ROD_L = 15, 150  # zwei Rods liegen der Baseplate bei
BASEPLATE_DICKE = 14  # Annahme

RING_VOR = 4  # Bajonettring steht vor der Gehäusefront; seine Vorderseite ist die Auflage (Annahme)
front_x = AUFLAGEMASS - RING_VOR  # Gehäusevorderkante
hinten_x = front_x - FX6_T
boden_z = -ACHSE_UEBER_BODEN
mitte_y = (ACHSE_LINKS - ACHSE_RECHTS) / 2  # Gehäusemitte liegt 5,8 mm links der Bildachse
voll = (Align.MIN, Align.MIN, Align.MIN)


def quader(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    return Pos(x0, y0, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=voll)


def achse_x(r: float, x0: float, x1: float, y: float = 0, z: float = 0) -> Part:
    """Zylinder entlang x von x0 bis x1."""
    return Pos(x0, y, z) * Rot(0, 90, 0) * Cylinder(r, x1 - x0, align=(Align.CENTER, Align.CENTER, Align.MIN))


def fx6_gehaeuse() -> Part:
    g = quader(hinten_x, front_x, -ACHSE_RECHTS, ACHSE_LINKS, boden_z, boden_z + FX6_H)
    g = fillet(g.edges().filter_by(Axis.X), radius=8)
    g += achse_x(31, front_x - 0.5, AUFLAGEMASS) - achse_x(23, front_x - 1, AUFLAGEMASS + 1)  # E-Mount-Ring
    return g


def fx6_tragegriff() -> Part:
    """Smart Handle mit Audioteil vorn; Höhe und Länge aus den Gesamtmaßen, Form geschätzt."""
    oben = boden_z + HOEHE_MIT_GRIFFEN
    vorn = hinten_x + LAENGE_MIT_GRIFF
    g = quader(-112, -92, -12, 12, boden_z + FX6_H, oben - 18)  # hinterer Pfosten, steht auf dem Gehäuse
    g += quader(-12, 8, -12, 12, boden_z + FX6_H, oben - 18)  # vorderer Pfosten
    g += quader(-118, vorn, -13, 13, oben - 19, oben)  # Bügel
    g += quader(vorn - 42, vorn, -13, 13, oben - 48, oben - 18.5)  # Audioteil mit XLR
    return g


def fx6_monitor() -> Part:
    oben = boden_z + HOEHE_MIT_GRIFFEN
    vorn = hinten_x + LAENGE_MIT_GRIFF
    return quader(vorn - 60, vorn - 42, 13, 108, oben - 62, oben)  # links am Bügel, Bildschirm nach hinten


def fx6_handgriff() -> Part:
    h = quader(front_x - 62, front_x - 2, -ACHSE_RECHTS - 48, -ACHSE_RECHTS, boden_z + 4, boden_z + 114)
    return fillet(h.edges().filter_by(Axis.Z), radius=14)


def tilta_baseplate() -> Part:
    """Tilta ES-T20-QRBP, vereinfacht: Platte unter dem Body, Rod-Block hinten, Rosetten links und rechts."""
    p = quader(hinten_x + 8, front_x - 6, mitte_y - 48, mitte_y + 48, boden_z - BASEPLATE_DICKE, boden_z)
    rz = -RODS_UNTER_ACHSE
    p += quader(hinten_x + 8, hinten_x + 43, -RODS_ABSTAND / 2 - 14, RODS_ABSTAND / 2 + 14, rz - 11,
                boden_z - BASEPLATE_DICKE + 0.5)
    for y in (RODS_ABSTAND / 2, -RODS_ABSTAND / 2):
        p -= achse_x(ROD_D / 2 + 0.1, hinten_x + 7, hinten_x + 44, y, rz)
    # ARRI-Rosetten (Ø 31,8, 60 Zähne, M6) links und rechts: nur als Bezugspunkte, ihre Höhe ist nicht bekannt
    return p


def rod(y: float) -> Part:
    """15-mm-Rod, steckt hinten im Rod-Block und läuft nach vorn unter dem Body."""
    return achse_x(ROD_D / 2, hinten_x + 8, hinten_x + 8 + ROD_L, y, -RODS_UNTER_ACHSE)


def vmount_platte() -> Part:
    """Tilta-Akkuplatte V-Mount (Typ I im BP-U-Schacht), Maße geschätzt; 0,36–0,4 kg."""
    return quader(hinten_x - 22, hinten_x, mitte_y - 45, mitte_y + 45, -60, 60)  # liegt hinten am Gehäuse an


def vmount_akku() -> Part:
    """Beispiel-Akku IDX DUO-C98P: 95 × 146 × 39 mm, 640 g."""
    return quader(hinten_x - 22 - 39, hinten_x - 22, mitte_y - 47.5, mitte_y + 47.5, -80, 66)  # an der Platte


def fujinon_mk18_55() -> Part:
    """Fujinon MK18-55 T2.9, E-Mount: 206,3 lang, Front-Ø 85, 980 g. Ursprung Bajonett-Auflage, Achse +x."""
    l = 206.3
    o = achse_x(30, 0, 12) + achse_x(38, 11, 166) + achse_x(42.5, 165, l)
    o -= achse_x(36, l - 6, l + 1)  # Frontlinse liegt vertieft
    for x0 in (38, 78, 118):  # Fokus, Zoom, Blende mit 0,8-Modul-Zahnkranz, vereinfacht als Ring
        o += achse_x(42, x0, x0 + 14) - achse_x(37.9, x0 - 1, x0 + 15)
    return o


MASSEN = {  # g; Annahmen markiert
    "Gehäuse": 890, "Tragegriff": 260, "Monitor": 150, "Handgriff": 150,  # Griff, Monitor: Annahme
    "Tilta-Baseplate": 435, "Rod links": 45, "Rod rechts": 45, "V-Mount-Platte": 380, "V-Mount-Akku": 640,
    "Objektiv": 980,
}


def fx6_system() -> tuple[dict, dict, dict]:
    """Alle Teile im Kamera-System (Ursprung Sensormitte, +x Blickrichtung), Bezugspunkte und Massen."""
    bajonett = Location((AUFLAGEMASS, 0, 0))
    teile = {
        "Gehäuse": fx6_gehaeuse(), "Tragegriff": fx6_tragegriff(), "Monitor": fx6_monitor(),
        "Handgriff": fx6_handgriff(), "Tilta-Baseplate": tilta_baseplate(),
        "Rod links": rod(RODS_ABSTAND / 2), "Rod rechts": rod(-RODS_ABSTAND / 2),
        "V-Mount-Platte": vmount_platte(), "V-Mount-Akku": vmount_akku(),
        "Objektiv": bajonett * fujinon_mk18_55(),
    }
    bezug = {
        "sensor": Location((0, 0, 0)),
        "bajonett": bajonett,
        "front": Location((AUFLAGEMASS + 206.3, 0, 0)),  # Objektivfront
        "stativ_1_4": Location((front_x - GEWINDE_14_X, 0, boden_z), (180, 0, 0)),  # Annahme: unter der Bildachse
        "stativ_3_8": Location((front_x - GEWINDE_38_X, 0, boden_z), (180, 0, 0)),
        "front_unten": Location((front_x, 0, boden_z), (180, 0, 0)),
        "akkuschacht": Location((hinten_x, 0, 0), (0, -90, 0)),
        "rods": Location((hinten_x + 8 + ROD_L / 2, 0, -RODS_UNTER_ACHSE)),
        "rosette_links": Location((-60, mitte_y + 51, boden_z - BASEPLATE_DICKE / 2), (-90, 0, 0)),
        "rosette_rechts": Location((-60, mitte_y - 51, boden_z - BASEPLATE_DICKE / 2), (90, 0, 0)),
    }
    return teile, bezug, MASSEN
