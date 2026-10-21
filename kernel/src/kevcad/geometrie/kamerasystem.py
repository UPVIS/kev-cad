"""Geometrie für Kevins Kamerasystem (Katalog ``kameras.json``): Sony FX6, Tilta-Baseplate, 15-mm-Stangen,
V-Mount-Platten und -Akkus, Fujinon MK18-55.

Platzhalter: Jede Funktion liefert vorerst die vereinfachte Form aus den Katalogmaßen (``kevcad.kamera.standard_*``).
Kevins Projektsitzung (Kugelschieber) ersetzt sie durch genauere Modelle (fx6_gehaeuse, fx6_tragegriff, fx6_monitor,
fx6_handgriff, tilta_baseplate, rod, vmount_platte, vmount_akku, fujinon_mk18_55). Funktionsnamen und Signatur bleiben,
die Bezugspunkte stehen im Katalog und ändern sich dadurch nicht.

Signatur: ``f(eintrag: dict) -> Shape | dict[str, Shape]`` in lokalen Koordinaten (siehe ``kevcad.geometrie``).
"""

from __future__ import annotations

from typing import Any

from kevcad.kamera import standard_gehaeuse, standard_objektiv, standard_zubehoer


def sony_fx6(eintrag: dict[str, Any]) -> dict[str, Any]:
    """FX6-Gehäuse, Ursprung Sensormitte. Später: Gehäuse, Tragegriff, Monitor, Handgriff als eigene Teile."""
    return standard_gehaeuse(eintrag)


def fujinon_mk18_55(eintrag: dict[str, Any]) -> dict[str, Any]:
    """Fujinon MK18-55, Ursprung Bajonett-Auflage, +x zur Frontlinse."""
    return standard_objektiv(eintrag)


STANGE_BOHRUNG = 15.2  # 15-mm-Stange mit 0,1 mm Spiel je Seite: die Stange steckt in der Klemmung, nicht im Material


def tilta_es_t20_qrbp(eintrag: dict[str, Any]) -> dict[str, Any]:
    """Tilta-Baseplate ES-T20-QRBP, Ursprung Kameraauflage am 1/4"-Gewinde der FX6 (Platzhalter-Quader, solange die
    Maße fehlen: 160 × 90 × 20 unter der Auflage), mit durchgehenden Bohrungen für die 15-mm-Stangen an den
    Bezugspunkten ``lws_*``."""
    from build123d import Align, Cylinder, Pos, Rot

    entry = dict(eintrag, masse=eintrag.get("masse") or {"t": 160, "b": 90, "h": 20})
    formen = standard_zubehoer(entry)
    name, platte = next(iter(formen.items()))
    laenge = float(entry["masse"].get("t", 160)) + 20
    farbe = platte.color
    for key, pt in (entry.get("bezugspunkte") or {}).items():
        if not str(key).startswith("lws_") or not isinstance(pt, dict):
            continue
        x, y, z = (float(c) for c in pt.get("pos") or (0, 0, 0))
        bohrung = Pos(x - laenge / 2, y, z) * Rot(0, 90, 0) * Cylinder(
            STANGE_BOHRUNG / 2, laenge, align=(Align.CENTER, Align.CENTER, Align.MIN))
        platte = platte - bohrung
    platte.color = farbe
    return {name: platte}


def lws_stange(eintrag: dict[str, Any]) -> dict[str, Any]:
    """15-mm-Stange, Ursprung hinteres Ende auf der Achse, +x entlang der Stange."""
    return standard_zubehoer(eintrag)


def vmount_platte(eintrag: dict[str, Any]) -> dict[str, Any]:
    """V-Mount-Akkuplatte (Ursprung laut ``ursprung`` des Eintrags)."""
    return standard_zubehoer(eintrag)


def vmount_akku(eintrag: dict[str, Any]) -> dict[str, Any]:
    """V-Mount-Akku, Ursprung Mitte der Anlage, der Akku liegt hinter dem Ursprung (−x)."""
    return standard_zubehoer(eintrag)
