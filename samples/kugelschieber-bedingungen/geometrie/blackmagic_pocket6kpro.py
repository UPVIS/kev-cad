"""Blackmagic Pocket Cinema Camera 6K Pro (aktiver EF-Mount) und Platzhalter-Objektiv, vereinfacht.

Für den Kamerakatalog von Kev CAD: lokale Koordinaten in mm, +x nach vorn (Blickrichtung), +y links, +z oben.
- Kamera: Ursprung in der Sensormitte. Bildachse = x-Achse.
- Objektiv: Ursprung in der Mitte der Bajonett-Auflage, optische Achse +x.

Gesichert (Blackmagic, Maßbild der Tech Specs): Breite 7,08 in = 179,8 mm, Tiefe 4,41 in = 112,0 mm (Monitor bis
Bajonett-Vorderkante), Höhe 4,84 in = 122,9 mm (mit Griff, ohne Sucher), 2,73 lb = 1238 g; aktiver EF-Mount mit
Auflagemaß 44 mm, 5"-Touchscreen 1920 × 1080 (neig- und klappbar), ein NP-F570-Akku im Griff (der optionale Battery
Pro Grip nimmt zwei weitere auf), Super-35-Sensor 23,10 × 12,99 mm.
Gemessen am Maßbild (Pixel, Maßstab aus den Gesamtmaßen, etwa ±2 mm): Bildachse 65 mm über der Unterseite,
70,3 mm von der linken und 109,5 mm von der rechten Seite (Griffseite). Blackmagic veröffentlicht keine CAD-Daten.
"""

from __future__ import annotations

from build123d import Align, Axis, Box, Cylinder, Part, Pos, Rot, Shape, fillet

# Gesicherte Werte (Blackmagic)
BREITE, TIEFE, HOEHE = 179.8, 112.0, 122.9
AUFLAGEMASS = 44.0  # EF: Bajonett-Auflage bis Sensor (Norm)
SENSOR_B, SENSOR_H = 23.10, 12.99

# Am Maßbild gemessen (etwa ±2 mm)
ACHSE_UEBER_BODEN = 65.0
ACHSE_LINKS = 70.3  # Bildachse zur linken Gehäuseseite (+y), von hinten gesehen
ACHSE_RECHTS = BREITE - ACHSE_LINKS  # 109,5 zur rechten Seite mit Griff (-y)
BUCKEL_H = 14.4  # Aufbau oben über dem Bajonett (Lüftung, Blitzschuh-Bereich)

front_x = AUFLAGEMASS  # Vorderkante Bajonett = Auflagefläche
hinten_x = front_x - TIEFE  # -68, Rückseite des Monitors
boden_z = -ACHSE_UEBER_BODEN  # -65
oben_z = boden_z + HOEHE  # 57,9
links_y = ACHSE_LINKS  # 70,3
rechts_y = -ACHSE_RECHTS  # -109,5

# Abgeschätzt am Maßbild (Annahme, nachmessen)
MONITOR_D = 11.0  # Annahme: Dicke des Klappmonitors
gehaeuse_hinten_x = hinten_x + MONITOR_D  # -57
gehaeuse_vorn_x = 22.0  # Annahme: Vorderseite neben und unter dem Bajonettaufbau (Seitenansicht 14 bis 26)
gehaeuse_oben_z = oben_z - BUCKEL_H  # 43,5
griff_innen_y = -70.0  # Annahme: Grenze Gehäuse / Griff (Rückansicht: Monitor endet bei -69,7)
GRIFF_VORN_X = 27.0  # Annahme: Griffvorderseite (Seitenansicht)
GRIFF_HINTEN_X = -64.0  # Annahme
GRIFF_OBEN_Z = 41.0  # Annahme: Frontansicht
AUFBAU_VORN_X = 39.7  # Annahme: Front des Bajonettaufbaus, 4,3 mm hinter der Auflage (Seitenansicht)
AUFBAU_Y = (-42.5, 43.0)  # Annahme: Bajonettaufbau in der Frontansicht
AUFBAU_UNTEN_Z = -44.0  # Annahme
BAJONETT_R_INNEN = 27.0  # EF-Öffnung Ø 54 (Norm)
BAJONETT_R_AUSSEN = 33.0  # Annahme: Bajonettring Ø 66
MONITOR_Y = (-69.7, 65.5)  # gemessen an der Rückansicht
MONITOR_Z = (boden_z + 2.4, boden_z + 98.0)  # gemessen an der Rückansicht
STATIV_X = 0.0  # Annahme: 1/4"-20-Gewinde unter der Sensorebene, nicht veröffentlicht, nachmessen
STATIV_Y = 0.0  # Annahme: unter der Bildachse

# Platzhalter-Objektiv Sigma 18-35 mm F1.8 DC HSM Art (EF): Ø 78 × 121 mm, 810 g, Filter Ø 72 (Sigma)
OBJ_L, OBJ_D, OBJ_FILTER_D = 121.0, 78.0, 72.0  # Länge von der Bajonett-Auflage bis zur Filterfläche

voll = (Align.MIN, Align.MIN, Align.MIN)
boden = (Align.CENTER, Align.CENTER, Align.MIN)


def _quader(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    return Pos(x0, y0, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=voll)


def _zyl_x(r: float, x0: float, x1: float, y: float = 0.0, z: float = 0.0) -> Part:
    """Zylinder entlang x von x0 bis x1."""
    return Pos(x0, y, z) * Rot(0, 90, 0) * Cylinder(r, x1 - x0, align=boden)


def _gehaeuse() -> Part:
    """Grundkörper zwischen Monitor und Griff, Bajonettaufbau vorn, Aufbau oben."""
    g = _quader(gehaeuse_hinten_x, gehaeuse_vorn_x, griff_innen_y, links_y, boden_z, gehaeuse_oben_z)
    g = fillet(g.edges(), radius=5)
    a = _quader(gehaeuse_vorn_x - 1, AUFBAU_VORN_X, AUFBAU_Y[0], AUFBAU_Y[1], AUFBAU_UNTEN_Z, gehaeuse_oben_z)
    a = fillet(a.edges().filter_by(Axis.X), radius=8)
    g += a
    buckel = _quader(-36, 32, -30, 30, gehaeuse_oben_z - 1, oben_z)  # Annahme: 68 × 60 unten
    buckel = fillet([k for k in buckel.edges() if k.center().Z > gehaeuse_oben_z], radius=6)
    g += buckel
    g -= _zyl_x(BAJONETT_R_INNEN, 30, AUFBAU_VORN_X + 1)  # Bajonettöffnung, Annahme 10 mm tief
    return g


def _handgriff() -> Part:
    """Griff rechts (-y) mit Fach für einen NP-F570, vereinfacht als gerundeter Block."""
    h = _quader(GRIFF_HINTEN_X, GRIFF_VORN_X, rechts_y, griff_innen_y, boden_z, GRIFF_OBEN_Z)
    return fillet(h.edges(), radius=9)


def _monitor() -> Part:
    """5"-Klappmonitor in Ruhelage an der Rückseite."""
    m = _quader(hinten_x, gehaeuse_hinten_x, MONITOR_Y[0], MONITOR_Y[1], MONITOR_Z[0], MONITOR_Z[1])
    return fillet(m.edges(), radius=3)


def _bajonett() -> Part:
    """EF-Bajonettring; seine Vorderfläche ist die Auflage (x = 44)."""
    return _zyl_x(BAJONETT_R_AUSSEN, AUFBAU_VORN_X, front_x) - _zyl_x(BAJONETT_R_INNEN, AUFBAU_VORN_X - 1, front_x + 1)


def bmpcc_6k_pro(eintrag: dict | None = None) -> dict[str, Shape]:
    """Kamera als Unterteile. Ursprung Sensormitte, +x Blickrichtung, +y links, +z oben.

    Der Katalogeintrag wird derzeit nicht ausgewertet (Monitor immer eingeklappt).
    """
    return {
        "Gehäuse": _gehaeuse(),
        "Handgriff": _handgriff(),
        "Monitor": _monitor(),
        "Bajonett": _bajonett(),
    }


def sigma_18_35_art_ef(eintrag: dict | None = None) -> Shape:
    """Platzhalter-EF-Objektiv Sigma 18-35 mm F1.8 DC HSM Art. Ursprung Mitte der Bajonett-Auflage, Achse +x.

    Optionale Felder im Katalogeintrag, um den Platzhalter für andere EF-Objektive zu nutzen:
    "laenge" (Auflage bis Front, mm), "durchmesser" (größter Ø, mm), "filter" (Filtergewinde Ø, mm).
    """
    e = eintrag or {}
    l = float(e.get("laenge", OBJ_L))
    r = float(e.get("durchmesser", OBJ_D)) / 2
    rf = float(e.get("filter", OBJ_FILTER_D)) / 2
    o = _zyl_x(24, -8, 0.5)  # Annahme: hinterer Tubus taucht 8 mm ins Bajonett
    o += _zyl_x(31, 0, 6)  # Annahme: Bajonettseite des Objektivs
    o += _zyl_x(r - 1.5, 5.5, l)  # Tubus
    for x0, x1 in ((0.20 * l, 0.42 * l), (0.55 * l, 0.85 * l)):  # Annahme: zwei Ringe (Zoom, Fokus) mit größtem Ø
        o += _zyl_x(r, x0, x1)
    o -= _zyl_x(min(rf - 2, r - 4), l - 3, l + 1)  # vertiefte Frontlinse im Filtergewinde, Annahme
    return o


def bezugspunkte(teil: str = "kamera") -> dict[str, dict]:
    """Benannte Punkte. teil="kamera": Kamera-Koordinaten (Sensormitte); teil="objektiv": Objektiv-Koordinaten."""
    if teil == "objektiv":
        return {
            "bajonett": {"pos": [0.0, 0.0, 0.0], "richtung": [-1.0, 0.0, 0.0],
                         "hinweis": "Mitte der Bajonett-Auflage des Objektivs, zeigt zur Kamera; auf den "
                                    "Kamerapunkt 'bajonett' setzen"},
            "front": {"pos": [OBJ_L, 0.0, 0.0], "richtung": [1.0, 0.0, 0.0],
                      "hinweis": "Mitte der Filterfläche (Filtergewinde Ø 72), Sigma 18-35 Art"},
        }
    return {
        "sensor": {"pos": [0.0, 0.0, 0.0], "richtung": [1.0, 0.0, 0.0],
                   "hinweis": "Sensormitte, Bildachse nach vorn; Super 35, 23,10 × 12,99 mm"},
        "bajonett": {"pos": [front_x, 0.0, 0.0], "richtung": [1.0, 0.0, 0.0],
                     "hinweis": "Mitte der EF-Bajonett-Auflage, 44 mm vor dem Sensor; hier sitzt der Ursprung "
                                "des Objektivs"},
        "stativ_1_4": {"pos": [STATIV_X, STATIV_Y, boden_z], "richtung": [0.0, 0.0, -1.0],
                       "hinweis": "1/4\"-20-Stativgewinde an der Unterseite, zeigt nach unten; Höhe gemessen "
                                  "(65 mm unter der Bildachse), Lage in x und y ist Annahme (unter Sensor/Bildachse)"},
        "front_unten": {"pos": [GRIFF_VORN_X, 0.0, boden_z], "richtung": [0.0, 0.0, -1.0],
                        "hinweis": "Vorderkante der Unterseite in der Bildachsen-Ebene (vorderster Punkt des "
                                   "Bodens, Griffvorderseite x = 27, Annahme); Anschlag für eine Platte"},
        "oben_mitte": {"pos": [0.0, 0.0, round(oben_z, 2)], "richtung": [0.0, 0.0, 1.0],
                       "hinweis": "Oberseite des Aufbaus über dem Sensor, 122,9 mm über der Unterseite"},
    }


MASSEN = {  # g; Kamera 1238 g laut Blackmagic, ohne Akku. Aufteilung auf die Unterteile ist Annahme
    "Gehäuse": 760,
    "Handgriff": 250,
    "Monitor": 180,
    "Bajonett": 48,
    "Objektiv": 810,  # Sigma 18-35 Art (Sigma, DXOMARK)
    "Akku NP-F570": 125,  # Annahme, nicht modelliert
}

QUELLEN = [
    "https://www.blackmagicdesign.com/products/blackmagicpocketcinemacamera/techspecs/W-CIN-01",
    "https://images.blackmagicdesign.com/images/products/blackmagicpocketcinemacamera/techspecs/"
    "physical-specifications/blackmagic-pocket-cinema-camera-6k-pro-imperial-sm.jpg",
    "https://www.fdtimes.com/2021/02/18/blackmagic-pocket-cinema-camera-6k-pro/",
    "https://www.sigma-global.com/en/lenses/a013_18_35_18/",
    "https://www.dxomark.com/Lenses/Sigma/Sigma-18-35mm-F18-DC-HSM-A-Canon-mounted-on-Canon-EOS-7D---Specifications__619",
    "https://imaging-resource.com/lenses/sigma/18-35mm-f1.8-dc-hsm-a/specifications",
]
