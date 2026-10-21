"""Prüfung Stufe 2: Schweben und Standsicherheit, Einbaubarkeit (Montage durch Demontage, Werkzeugzugang,
eingesperrte Teile), nachgiebige Teile und Erklärungen. Kleine Fälle im Prozess, ohne Laufzeit."""

import numpy as np
import pytest
from build123d import Box, Cylinder, Pos

from kevcad_kernel.pruefung.koerper import koerper_aus_form
from kevcad_kernel.pruefung.kollision import PaarCache
from kevcad_kernel.pruefung.pruefer import pruefe


def k(name, form, **info):
    return koerper_aus_form(name, form, info or None)


def arten(erg, schwere=("fehler", "warnung")):
    return sorted(b["art"] for b in erg["befunde"] if b["schwere"] in schwere)


def schritte(erg):
    return [(s["name"], s["richtung_text"]) for s in erg["montage"]["schritte"]]


# ---------------------------------------------------------------------------------------------------------------------
# Schweben und Standsicherheit


def test_schwebendes_teil():
    platte = k("Platte", Pos(0, 0, 5) * Box(100, 100, 10))
    klotz = k("Klotz", Pos(0, 0, 30) * Box(20, 20, 20))  # Unterkante 20, Platte oben 10: schwebt 10 mm
    erg, _ = pruefe([platte, klotz])
    (b,) = [b for b in erg["befunde"] if b["art"] == "schwebt"]
    assert b["teile"] == ["Klotz"] and b["schwere"] == "fehler"
    assert b["wert"]["fallweg"] == pytest.approx(10.0, abs=0.05) and b["wert"]["auf"] == "Platte"
    assert "10 mm absenken" in b["loesung"]
    # aufgelegt: kein Befund, Gruppe steht
    erg2, _ = pruefe([platte, k("Klotz", Pos(0, 0, 20) * Box(20, 20, 20))])
    assert "schwebt" not in arten(erg2)
    (g,) = erg2["stand"]["gruppen"]
    assert sorted(g["teile"]) == ["Klotz", "Platte"] and g["kippwinkel"] > 30


def test_spielpassung_zaehlt_als_verbindung():
    platte = k("Platte", Pos(0, 0, 5) * Box(100, 100, 10))
    klotz = k("Klotz", Pos(0, 0, 20.3) * Box(20, 20, 20))  # 0,3 mm Luft: Spielpassung, nicht schwebend
    erg, _ = pruefe([platte, klotz])
    assert "schwebt" not in arten(erg)
    assert erg["paare"]["spiel"] == 1 and erg["paare"]["beruehrt"] == 0
    erg2, _ = pruefe([platte, k("Klotz", Pos(0, 0, 20.02) * Box(20, 20, 20))])
    assert erg2["paare"]["beruehrt"] == 1


def test_knapp_stehender_turm_warnt():
    fuss = k("Fuss", Pos(0, 0, 0.5) * Box(20, 20, 1))
    turm = k("Turm", Pos(11, 0, 51) * Box(4, 4, 100))  # steht 1 mm auf dem Fuß, Schwerpunkt knapp vor dem Rand
    erg, _ = pruefe([fuss, turm])
    (b,) = [b for b in erg["befunde"] if b["art"] == "standsicherheit"]
    assert b["schwere"] == "warnung" and "steht knapp" in b["text"] and "°" in b["text"]
    assert 0 < erg["stand"]["gruppen"][0]["kippwinkel"] < 3


def test_kippender_turm():
    fuss = k("Fuss", Pos(0, 0, 1) * Box(20, 20, 2))
    ausleger = k("Ausleger", Pos(95, 0, 7) * Box(200, 10, 10), material="stahl")  # weit über den Fuß hinaus
    erg, _ = pruefe([fuss, ausleger])
    (b,) = [b for b in erg["befunde"] if b["art"] == "kippt"]
    assert b["schwere"] == "fehler" and b["wert"]["rand_abstand"] < -50
    assert "Standfläche verbreitern" in b["loesung"]
    # mittig: steht
    erg2, _ = pruefe([fuss, k("Ausleger", Pos(0, 0, 7) * Box(15, 10, 10))])
    assert "kippt" not in arten(erg2)


def test_befestigt_und_boden():
    halter = k("Halter", Pos(0, 0, 500) * Box(20, 20, 20))
    erg, _ = pruefe([halter, k("Boden", Pos(0, 0, 5) * Box(100, 100, 10))])
    assert "schwebt" in arten(erg)
    erkl = {"befestigt": [{"teile": ["Halter"], "grund": "an der Wand verschraubt"}]}
    erg2, _ = pruefe([halter, k("Boden", Pos(0, 0, 5) * Box(100, 100, 10))], erkl)
    assert "schwebt" not in arten(erg2)


# ---------------------------------------------------------------------------------------------------------------------
# Einbaubarkeit


def test_gueltige_montagereihenfolge():
    platte = k("Platte", Pos(0, 0, 5) * (Box(100, 100, 10) - Cylinder(5.2, 12)))
    stift = k("Stift", Pos(0, 0, 15) * Cylinder(5, 30))  # steckt mit 0,2 mm Spiel in der Bohrung
    kappe = k("Kappe", Pos(0, 0, 35) * Box(30, 30, 10))  # liegt oben auf dem Stift
    erg, _ = pruefe([kappe, stift, platte])
    assert arten(erg) == []
    assert erg["montage"]["vollstaendig"] is True
    assert schritte(erg) == [("Platte", "Grundteil"), ("Stift", "von oben"), ("Kappe", "von oben")]


def test_teil_in_geschlossener_kiste():
    kiste = k("Kiste", Pos(0, 0, 25) * (Box(50, 50, 50) - Box(40, 40, 40)))
    inhalt = k("Inhalt", Pos(0, 0, 10) * Box(10, 10, 10))  # liegt auf dem Innenboden (z 5)
    erg, _ = pruefe([kiste, inhalt])
    (b,) = [b for b in erg["befunde"] if b["art"] == "eingesperrt"]
    assert b["teile"] == ["Inhalt", "Kiste"] and b["schwere"] == "fehler"
    assert "Deckel" in b["loesung"]
    # mit Öffnung oben: lässt sich einsetzen
    offen = k("Kiste", Pos(0, 0, 25) * (Box(50, 50, 50) - Pos(0, 0, 5) * Box(40, 40, 40)))
    erg2, _ = pruefe([offen, k("Inhalt", Pos(0, 0, 15) * Box(10, 10, 10))])  # Innenboden jetzt bei z 10
    assert arten(erg2) == [] and schritte(erg2)[-1] == ("Inhalt", "von oben")


def test_gefangener_ring_nur_als_baugruppe():
    # Hantel: Achse mit zwei Köpfen aus einem Stück, Ring dazwischen gefangen
    achse = k("Hantel/Achse", Pos(0, 0, 50) * (Cylinder(4, 60) + Pos(0, 0, 30) * Cylinder(10, 4)
                                                 + Pos(0, 0, -30) * Cylinder(10, 4)))
    ring = k("Hantel/Ring", Pos(0, 0, 50) * (Cylinder(8, 10) - Cylinder(4.2, 12)))
    fuss = k("Fuss", Pos(0, 0, 9) * Box(40, 40, 18))
    erg, _ = pruefe([fuss, achse, ring])
    (b,) = [b for b in erg["befunde"] if b["art"] == "nur_baugruppe"]
    assert set(b["teile"]) == {"Hantel/Achse", "Hantel/Ring"} and "baugruppe=True" in b["loesung"]
    erkl = {"montage": [{"teile": ["Hantel/"], "richtung": [], "nach": [], "baugruppe": True}]}
    erg2, _ = pruefe([fuss, achse, ring], erkl)
    assert [b for b in erg2["befunde"] if b["art"] in ("nur_baugruppe", "nicht_einbaubar")] == []
    assert ("Hantel", "von oben") in schritte(erg2)


def test_eingedruckte_mutter():
    block = k("Halter", Pos(0, 0, 10) * (Box(30, 30, 20) - Box(13.5, 13.5, 6.8)))  # geschlossene Tasche
    mutter = k("Mutter", Pos(0, 0, 10) * Box(13, 13, 6.4))
    erg, _ = pruefe([block, mutter])
    assert "eingesperrt" in arten(erg)
    erkl = {"montage": [{"teile": ["Mutter"], "richtung": [], "nach": [], "eingedruckt": True}]}
    erg2, _ = pruefe([block, mutter], erkl)
    assert arten(erg2) == []
    assert schritte(erg2) == [("Halter mit Mutter", "Grundteil")]


def test_einsatz_in_tasche_zur_innenseite_zweistufig():
    # Kanal (oben geschlossen, an den Enden in Y offen); in der rechten Wand eine Tasche zur Kanalmitte hin
    kanal = Pos(0, 0, 15) * (Box(60, 30, 30) - Box(40, 40, 20)) - Pos(23, 0, 15) * Cylinder(3.2, 6.4, rotation=(0, 90, 0))
    einsatz = k("Einsatz", Pos(23, 0, 15) * Cylinder(3, 6, rotation=(0, 90, 0)))  # x 20 … 26, Taschenboden bei 26,2
    erg, _ = pruefe([k("Kanal", kanal), einsatz])
    assert arten(erg) == [] and erg["montage"]["vollstaendig"]
    (s,) = [x for x in erg["montage"]["schritte"] if x["name"] == "Einsatz"]
    assert s["richtung_text"].startswith("von ") and ", dann " in s["richtung_text"] and "+X" in s["richtung_text"]
    assert s["weg"]["dann"] == [1.0, 0.0, 0.0]


def test_gewinde_sperrt_quer_aber_nicht_entlang_der_achse():
    from kevcad_kernel.pruefung.montage import Planer

    # Sockel mit seitlich offener Mutternfalle; Schraube M6 von oben, Mutter mit Kernloch Ø 5 (Gewindeeingriff)
    sockel = k("Sockel", Pos(0, 0, 10) * Box(40, 40, 20) - Pos(-6.9, 0, 10) * Box(26.4, 10.4, 8)
               - Pos(0, 0, 17) * Cylinder(3.2, 6.2))
    schraube = k("Schraube", Pos(0, 0, 15.5) * Cylinder(3, 17) + Pos(0, 0, 22) * Cylinder(5, 4))
    mutter = k("Mutter", Pos(0, 0, 8.5) * (Box(10, 10, 5) - Cylinder(2.5, 6)))
    erg, _ = pruefe([sockel, schraube, mutter])
    assert arten(erg) == [] and len(erg["gewinde"]) == 1 and erg["montage"]["vollstaendig"]
    assert np.allclose(np.abs(erg["gewinde"][0]["achse"]), [0, 0, 1])
    namen = [n for n, _ in schritte(erg)]
    assert namen.index("Mutter") < namen.index("Schraube")
    ks = {x.name: x for x in (sockel, schraube, mutter)}
    pl = Planer(ks, gewinde={frozenset(("Schraube", "Mutter")): np.array([0.0, 0.0, 1.0])})
    assert pl.sperrt("Mutter", "Schraube", np.array([-1.0, 0.0, 0.0]))  # quer: die Schraube steckt in der Mutter
    assert not pl.sperrt("Mutter", "Schraube", np.array([0.0, 0.0, -1.0]))  # entlang der Achse: abschrauben


def test_schnappverbindung():
    stange = k("Stange", Pos(0, 0, 20) * Box(10, 200, 10))  # liegt quer auf zwei Stützen, Unterkante z 15
    stuetzen = [k(f"Stuetze {i}", Pos(0, y, 7.5) * Box(40, 20, 15)) for i, y in enumerate((-90, 90))]
    # Clip umgreift die Stange in der Mitte, unten nur 6 mm offen (kleiner als die 10 mm der Stange)
    clip = k("Clip", Pos(0, 0, 20) * (Box(16, 8, 16) - Box(10.2, 10, 10.2) - Pos(0, 0, -6) * Box(6, 10, 6)))
    erg, _ = pruefe([*stuetzen, stange, clip])
    assert erg["montage"]["vollstaendig"]
    erkl = {"montage": [{"teile": ["Clip"], "richtung": [[0, 0, 1]], "nach": [], "schnappt": True}]}
    erg2, _ = pruefe([*stuetzen, stange, clip], erkl)
    assert ("Clip", "von unten") in schritte(erg2)


def test_werkzeugzugang_schraube():
    unterlage = k("Unterlage", Pos(0, 0, -20) * (Box(60, 60, 20) - Cylinder(4.5, 22)))
    platte = k("Platte", Pos(0, 0, -5) * (Box(60, 60, 10) - Cylinder(4.5, 12)))
    schraube = k("Schraube", Pos(0, 0, -15) * Cylinder(4, 30) + Pos(0, 0, 4) * Cylinder(6.5, 8),
                 art="schraube", typ="SocketHeadCapScrew", groesse="M8-1.25", d=8.0, achse=[0, 0, 1],
                 ursprung=[0, 0, 0])  # Kopf Ø 13 auf z 0 … 8, Schaft durch Platte und Unterlage
    stuetzen = [k(f"Stuetze {i}", Pos(x, 0, 11.5) * Box(4, 60, 23)) for i, x in enumerate((-28, 28))]
    erkl = {"montage": [{"teile": ["Schraube"], "richtung": [], "nach": ["Deckel"]}]}  # erst Deckel, dann Schraube

    def mit_deckel(loch):
        deckel = k("Deckel", Pos(0, 0, 25) * (Box(60, 60, 4) - Cylinder(loch / 2, 6)))  # 15 mm über dem Kopf
        return pruefe([unterlage, platte, schraube, deckel, *stuetzen], erkl)[0]

    # Durchgang Ø 14: der Kopf (Ø 13) passt durch, der Inbus-Freiraum (Ø 15) nicht
    erg = mit_deckel(14)
    wz = [b for b in erg["befunde"] if b["art"] == "werkzeug"]
    assert len(wz) == 1 and wz[0]["schwere"] == "fehler" and "Deckel" in wz[0]["teile"]
    assert wz[0]["wert"]["werkzeug"] == "Innensechskant 6"
    assert "einfuehren" not in arten(erg)
    # Durchgang Ø 20: Werkzeug kommt hin, Schraube von oben nach dem Deckel
    erg2 = mit_deckel(20)
    assert arten(erg2) == []
    s = {x["name"]: x for x in erg2["montage"]["schritte"]}
    assert s["Schraube"]["werkzeug"] == "Innensechskant 6" and s["Schraube"]["richtung_text"] == "von oben"
    assert s["Schraube"]["nr"] > s["Deckel"]["nr"]


def test_nachgiebiges_teil_wird_verformt():
    boden = k("Boden", Pos(0, 0, 5) * Box(100, 100, 10))
    schaum = k("Schaum", Pos(0, 0, 30) * Box(50, 50, 40), nachgiebig=True)  # 10 … 50
    platte = k("Auflage", Pos(0, 0, 52) * Box(60, 60, 8))  # 48 … 56: drückt 2 mm in den Schaum
    erg, _ = pruefe([boden, schaum, platte])
    (b,) = [b for b in erg["befunde"] if b["art"] == "verformt"]
    assert b["schwere"] == "hinweis" and b["wert"]["tiefe"] == pytest.approx(2.0, abs=0.01)
    assert "durchdringung" not in arten(erg) and "schwebt" not in arten(erg)


def test_wiederholung_schnell_aus_dem_zwischenspeicher():
    import time

    teile = [k(f"Teil {i}", Pos((i % 10) * 12, (i // 10) * 12, 5) * Box(10, 10, 10)) for i in range(50)]
    teile.append(k("Boden", Pos(54, 24, -1) * Box(130, 70, 2)))
    cache = PaarCache()
    erg, _ = pruefe(teile, {}, None, cache)
    assert arten(erg) == [] and erg["montage"]["vollstaendig"]
    t0 = time.perf_counter()
    erg2, _ = pruefe(teile, {}, None, cache)
    dauer = time.perf_counter() - t0
    assert erg2["paare"]["neu_gerechnet"] == 0 and erg2["montage"]["tests"] == 0
    assert dauer < 1.0, dauer
