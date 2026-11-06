"""Aufgaben des Benchmarks: Auftrag wie von Kevin, Ausgangsmodell (bei Änderungen), Musterlösung und Orakel.

Die Musterlösung ist nur für Stufe A (ohne Sprachmodell): Sie prüft das Orakel selbst und ist die Größe, mit der sich
andere Darstellungen derselben Konstruktion vergleichen lassen. Kein Agent bekommt sie zu sehen.

Alle Aufgaben folgen der Inventar-Regel (Druckteile aus PETG, Rohre aus dem Lager), so wie Kevin baut.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from orakel import Bogen, Teil, bohrungen, kegel, lochkreis, schnittvolumen, teile

KOPF = "from build123d import *\nfrom kevcad import lager, show, step, param\n\n"

# Gleicher Zusatz für jede Variante: Im Benchmark ist niemand da, der antwortet.
RAHMEN = ("\n\n(Kevin ist gerade nicht am Rechner. Stell keine Rückfragen und warte nicht auf ihn, triff sinnvolle "
          "Annahmen und nenne sie am Ende kurz. Das Projekt ist schon offen.)")


@dataclass
class Aufgabe:
    id: str
    titel: str
    art: str  # "neu" oder "aenderung"
    auftrag: str
    pruefen: Callable[[Any], Bogen]
    referenz: str
    vorlage: str | None = None  # model.py, das zu Beginn offen ist (Änderungen)
    schwer: int = 1  # 1 einfach, 2 mittel, 3 komplex
    merkmale: list[str] = field(default_factory=list)

    @property
    def prompt(self) -> str:
        return self.auftrag + RAHMEN


def _ein(bogen: Bogen, rt: Any, anzahl: int = 1) -> list[Teil]:
    t = teile(rt)
    bogen.pruefe(f"{anzahl} Teil(e)", len(t) == anzahl, len(t), anzahl)
    return t


def _senkrecht(gruppen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in gruppen if abs(g["achse"][2]) > 0.999]


# ---------------------------------------------------------------------------------------------------------------------
# T1 Montageplatte (neu, einfach)

T1_REF = KOPF + '''breite = param("breite", 120)
tiefe = param("tiefe", 80)
dicke = param("dicke", 6)
loch_d = param("loch_d", 6.6)
abstand_x = param("abstand_x", 100)
abstand_y = param("abstand_y", 60)
radius = param("radius", 5)

step("Platte mit vier Bohrungen")
with BuildPart() as platte:
    with BuildSketch():
        RectangleRounded(breite, tiefe, radius)
    extrude(amount=dicke)
    with Locations((0, 0, dicke)):
        with GridLocations(abstand_x, abstand_y, 2, 2):
            Hole(loch_d / 2)
show(lager.druckteil(platte.part, "Montageplatte", material="petg"), "Montageplatte")
'''


def _platte(rt: Any, breite: float, dicke: float, ax: float) -> Bogen:
    b = Bogen()
    t = _ein(b, rt)
    if not t:
        return b
    p = t[0]
    b.masse("Maße", p, (breite, 80, dicke))
    loecher = _senkrecht(bohrungen(p.form, 6.6))
    b.pruefe("4 Bohrungen Ø 6,6", len(loecher) == 4, len(loecher), 4)
    mx, my, _ = p.mitte()
    xs = sorted(round(g["fuss"][0] - mx, 2) for g in loecher)
    ys = sorted(round(g["fuss"][1] - my, 2) for g in loecher)
    if len(loecher) == 4:
        b.nahe("Lochabstand Breite", xs[-1] - xs[0], ax, 0.2)
        b.nahe("Lochabstand Tiefe", ys[-1] - ys[0], 60, 0.2)
        b.nahe("Bohrungen mittig", abs(sum(xs)) + abs(sum(ys)), 0, 0.4)
        # Fasen an den Lochkanten (Bettfase nach Kevins Druckregeln) verkürzen die Zylinderfläche: bis 1 mm erlaubt
        b.pruefe("Bohrungen durchgehend", all(dicke - 1.0 <= g["laenge"] <= dicke + 0.05 for g in loecher),
                 [round(g["laenge"], 2) for g in loecher], dicke)
    ecken = _senkrecht(bohrungen(p.form, 10, tol=0.1, innen=False))
    b.pruefe("Ecken R 5", len(ecken) == 4, len(ecken), 4)
    soll = breite * 80 * dicke - 4 * (25 - math.pi * 25 / 4) * dicke - 4 * math.pi * 3.3 ** 2 * dicke
    b.nahe("Volumen", p.volumen, soll, 0.01, relativ=True)
    b.pruefe("Material PETG", "petg" in p.material.lower(), p.material, "petg")
    return b


T1 = Aufgabe(
    "t1", "Montageplatte", "neu",
    "Bau mir eine Montageplatte als 3D-Druckteil aus PETG: 120 × 80 mm, 6 mm dick, mit vier Durchgangsbohrungen "
    "Ø 6,6 mm im Rechteck 100 × 60 mm, mittig. Die vier senkrechten Ecken mit Radius 5 verrunden.",
    lambda rt: _platte(rt, 120, 6, 100), T1_REF, schwer=1, merkmale=["Skizze", "Extrusion", "Lochraster", "Radius"])

# ---------------------------------------------------------------------------------------------------------------------
# T2 Flansch (neu, mittel)

T2_REF = KOPF + '''scheibe_d = param("scheibe_d", 90)
scheibe_h = param("scheibe_h", 8)
ansatz_d = param("ansatz_d", 40)
hoehe = param("hoehe", 25)
bohrung_d = param("bohrung_d", 30)
loch_d = param("loch_d", 5.5)
lochkreis_d = param("lochkreis_d", 70)
anzahl = int(param("anzahl", 6))
fase = param("fase", 1)

step("Scheibe mit Ansatz")
with BuildPart() as flansch:
    Cylinder(scheibe_d / 2, scheibe_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    chamfer(flansch.edges().filter_by(GeomType.CIRCLE).sort_by(Axis.Z)[-1], fase)
    with Locations((0, 0, scheibe_h)):
        Cylinder(ansatz_d / 2, hoehe - scheibe_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    step("Bohrungen")
    with Locations((0, 0, hoehe)):
        Hole(bohrung_d / 2)
    with Locations((0, 0, scheibe_h)):
        with PolarLocations(lochkreis_d / 2, anzahl):
            Hole(loch_d / 2)
show(lager.druckteil(flansch.part, "Flansch", material="petg"), "Flansch")
'''


def _flansch(rt: Any, scheibe_h: float, loch_d: float, anzahl: int, lk: float) -> Bogen:
    b = Bogen()
    t = _ein(b, rt)
    if not t:
        return b
    f = t[0]
    b.masse("Maße", f, (90, 90, 25))
    mx, my, _ = f.mitte()
    mitte = [g for g in _senkrecht(bohrungen(f.form, 30, tol=0.1)) if math.hypot(g["fuss"][0] - mx, g["fuss"][1] - my) < 0.2]
    b.pruefe("Bohrung Ø 30 mittig", len(mitte) == 1, len(mitte), 1)
    if mitte:
        b.pruefe("Bohrung durchgehend", 24.0 <= mitte[0]["laenge"] <= 25.05, round(mitte[0]["laenge"], 2), 25)
    ansatz = _senkrecht(bohrungen(f.form, 40, tol=0.1, innen=False))
    b.pruefe("Ansatz Ø 40", len(ansatz) == 1, len(ansatz), 1)
    loecher = _senkrecht(bohrungen(f.form, loch_d))
    b.pruefe(f"{anzahl} Bohrungen Ø {loch_d}", len(loecher) == anzahl, len(loecher), anzahl)
    if loecher:
        radien, schritte = lochkreis(loecher, (mx, my))
        b.pruefe(f"Lochkreis Ø {lk}", all(abs(2 * r - lk) < 0.3 for r in radien), [round(2 * r, 2) for r in radien], lk)
        b.pruefe("gleichmäßig verteilt", all(abs(s - 360 / anzahl) < 1 for s in schritte), schritte, 360 / anzahl)
        b.pruefe(f"Scheibe {scheibe_h} dick (Löcher so lang)",
                 all(scheibe_h - 1.0 <= g["laenge"] <= scheibe_h + 0.05 for g in loecher),
                 [round(g["laenge"], 2) for g in loecher], scheibe_h)
    b.pruefe("Fase an der Außenkante", kegel(f.form) >= 1, kegel(f.form), ">= 1")
    soll = (math.pi * 45 ** 2 * scheibe_h - 0.5 * 2 * math.pi * (45 - 1 / 3) + math.pi * 20 ** 2 * (25 - scheibe_h)
            - math.pi * 15 ** 2 * 25 - anzahl * math.pi * (loch_d / 2) ** 2 * scheibe_h)
    b.nahe("Volumen", f.volumen, soll, 0.01, relativ=True)
    b.pruefe("Material PETG", "petg" in f.material.lower(), f.material, "petg")
    return b


T2 = Aufgabe(
    "t2", "Flansch", "neu",
    "Konstruiere einen Flansch als Druckteil aus PETG: eine Scheibe Ø 90 mm, 8 mm dick, darauf mittig ein Rohransatz "
    "Ø 40 mm außen, so dass das Teil insgesamt 25 mm hoch ist. Mittig eine durchgehende Bohrung Ø 30 mm. In der "
    "Scheibe sechs Bohrungen Ø 5,5 mm, gleichmäßig auf einem Lochkreis Ø 70 mm. Die obere Außenkante der Scheibe mit "
    "1 mm Fase.",
    lambda rt: _flansch(rt, 8, 5.5, 6, 70), T2_REF, schwer=2,
    merkmale=["Zylinder", "Bohrung", "Lochkreis", "Fase", "Boolesch"])

# ---------------------------------------------------------------------------------------------------------------------
# T3 Gehäuse mit Deckel (neu, komplex, zwei Teile)

T3_REF = KOPF + '''laenge = param("laenge", 100)
breite = param("breite", 60)
hoehe = param("hoehe", 40)
wand = param("wand", 2)
dom_d = param("dom_d", 7)
dom_loch = param("dom_loch", 2.5)
dom_tief = param("dom_tief", 10)
deckel_s = param("deckel_s", 3)
deckel_loch = param("deckel_loch", 3.4)

ex = laenge / 2 - wand - dom_d / 2
ey = breite / 2 - wand - dom_d / 2
ecken = [(sx * ex, sy * ey) for sx in (-1, 1) for sy in (-1, 1)]

step("Unterteil")
with BuildPart() as unter:
    Box(laenge, breite, hoehe, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((0, 0, wand)):
        Box(laenge - 2 * wand, breite - 2 * wand, hoehe, align=(Align.CENTER, Align.CENTER, Align.MIN),
            mode=Mode.SUBTRACT)
    with Locations(*[(x, y, wand) for x, y in ecken]):
        Cylinder(dom_d / 2, hoehe - wand, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(*[(x, y, hoehe) for x, y in ecken]):
        Hole(dom_loch / 2, depth=dom_tief)
show(lager.druckteil(unter.part, "Gehäuse/Unterteil", material="petg"), "Gehäuse/Unterteil")

step("Deckel")
with BuildPart() as deckel:
    with Locations((0, 0, hoehe)):
        Box(laenge, breite, deckel_s, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(*[(x, y, hoehe + deckel_s) for x, y in ecken]):
        Hole(deckel_loch / 2)
show(lager.druckteil(deckel.part, "Gehäuse/Deckel", material="petg"), "Gehäuse/Deckel")
'''


def _gehaeuse(rt: Any) -> Bogen:
    b = Bogen()
    t = _ein(b, rt, 2)
    if len(t) != 2:
        return b
    unter, deckel = sorted(t, key=lambda x: x.masse()[2], reverse=True)
    b.masse("Unterteil 100 × 60 × 40", unter, (100, 60, 40))
    b.masse("Deckel 100 × 60 × 3", deckel, (100, 60, 3))
    dom = _senkrecht(bohrungen(unter.form, 2.5, tol=0.1))
    b.pruefe("4 Bohrungen Ø 2,5 in den Domen", len(dom) == 4, len(dom), 4)
    if dom:
        b.pruefe("10 mm tief", all(9.0 <= g["laenge"] <= 10.3 for g in dom), [round(g["laenge"], 2) for g in dom], 10)
    oben = _senkrecht(bohrungen(deckel.form, 3.4, tol=0.1))
    b.pruefe("4 Bohrungen Ø 3,4 im Deckel", len(oben) == 4, len(oben), 4)
    if len(dom) == 4 and len(oben) == 4:
        abw = max(min(math.dist(a["fuss"][:2], c["fuss"][:2]) for c in oben) for a in dom)
        b.nahe("Deckellöcher über den Domen", abw, 0, 0.5)
    (_, _, dz0), (_, _, _) = deckel.box()
    (_, _, _), (_, _, uz1) = unter.box()
    b.nahe("Deckel liegt auf", dz0, uz1, 0.2)
    b.nahe("keine Durchdringung", schnittvolumen(unter.form, deckel.form), 0, 1.0)
    soll_u = 100 * 60 * 40 - 96 * 56 * 38 + 4 * math.pi * 3.5 ** 2 * 38 - 4 * math.pi * 1.25 ** 2 * 10
    b.nahe("Volumen Unterteil (Wand 2)", unter.volumen, soll_u, 0.03, relativ=True)
    b.nahe("Volumen Deckel", deckel.volumen, 100 * 60 * 3 - 4 * math.pi * 1.7 ** 2 * 3, 0.01, relativ=True)
    return b


T3 = Aufgabe(
    "t3", "Gehäuse mit Deckel", "neu",
    "Baue ein Elektronikgehäuse aus zwei Druckteilen (PETG). Unterteil außen 100 × 60 × 40 mm, Wand und Boden 2 mm "
    "dick. Innen in jeder Ecke ein Dom Ø 7 mm vom Boden bis zur Oberkante, mit einer Bohrung Ø 2,5 mm, 10 mm tief, "
    "für Schrauben. Deckel 100 × 60 × 3 mm mit vier Durchgangsbohrungen Ø 3,4 mm genau über den Domen; der Deckel "
    "liegt auf dem Unterteil.",
    _gehaeuse, T3_REF, schwer=3, merkmale=["Schale", "Dome", "Sacklöcher", "zwei Teile", "Lagebeziehung"])

# ---------------------------------------------------------------------------------------------------------------------
# T4 Gestell aus Lagerteilen (Baugruppe)

T4_REF = KOPF + '''rohr_l = param("rohr_l", 300)
abstand_x = param("abstand_x", 160)
abstand_y = param("abstand_y", 110)
platte_x = param("platte_x", 200)
platte_y = param("platte_y", 150)
platte_s = param("platte_s", 20)
loch_d = param("loch_d", 12.2)
loch_t = param("loch_t", 15)

rohr = lager.teil("rohr-alu-12x1.0")
ecken = [(sx * abstand_x / 2, sy * abstand_y / 2) for sx in (-1, 1) for sy in (-1, 1)]
unten_z = platte_s - loch_t  # Rohrende unten

step("Platten")
for name, z0, von_oben in (("unten", 0, True), ("oben", unten_z + rohr_l - loch_t, False)):
    with BuildPart() as p:
        with Locations((0, 0, z0)):
            Box(platte_x, platte_y, platte_s, align=(Align.CENTER, Align.CENTER, Align.MIN))
        if von_oben:
            lagen = [Location((x, y, z0 + platte_s)) for x, y in ecken]
        else:  # Sacklöcher der oberen Platte von unten
            lagen = [Location((x, y, z0), (180, 0, 0)) for x, y in ecken]
        with Locations(*lagen):
            Hole(loch_d / 2, depth=loch_t)
    show(lager.druckteil(p.part, f"Gestell/Platte {name}", material="petg"), f"Gestell/Platte {name}")

step("Rohre")
for i, (x, y) in enumerate(ecken, 1):
    teil = rohr.verbauen(rohr_l, f"Gestell/Rohr {i}")
    show(teil.moved(Location((x, y, unten_z))), f"Gestell/Rohr {i}")
'''


def _gestell(rt: Any) -> Bogen:
    b = Bogen()
    t = teile(rt)
    rohre = [x for x in t if sorted(x.masse())[2] > 250 and sorted(x.masse())[0] < 15]
    platten = [x for x in t if x not in rohre]
    b.pruefe("4 Rohre", len(rohre) == 4, len(rohre), 4)
    b.pruefe("2 Platten", len(platten) == 2, len(platten), 2)
    for r in rohre:
        b.masse(f"{r.name} 12 × 300", r, (12, 12, 300), tol=0.1)
    if len(platten) == 2:
        for p in platten:
            b.masse(f"{p.name} 200 × 150 × 20", p, (200, 150, 20))
            lo = _senkrecht(bohrungen(p.form, 12.2, tol=0.05))
            b.pruefe(f"{p.name}: 4 Sacklöcher Ø 12,2", len(lo) == 4, len(lo), 4)
            if lo:
                b.pruefe(f"{p.name}: 15 tief", all(14.0 <= g["laenge"] <= 15.2 for g in lo),
                         [round(g["laenge"], 2) for g in lo], 15)
    if rohre and platten:
        alle = rohre + platten
        z0 = min(x.box()[0][2] for x in alle)
        z1 = max(x.box()[1][2] for x in alle)
        b.nahe("Gesamthöhe 310", z1 - z0, 310, 0.3)
        mx, my, _ = platten[0].mitte()
        lagen = sorted((round(r.mitte()[0] - mx, 1), round(r.mitte()[1] - my, 1)) for r in rohre)
        b.pruefe("Rohrmitten im Rechteck 160 × 110",
                 len(lagen) == 4 and all(abs(abs(x) - 80) < 0.3 and abs(abs(y) - 55) < 0.3 for x, y in lagen),
                 lagen, "±80, ±55")
        drin = max((schnittvolumen(r.form, p.form) for r in rohre for p in platten), default=0.0)
        b.nahe("Rohre ohne Durchdringung", drin, 0, 1.0)
        b.pruefe("Rohre stecken 15 mm in den Platten",
                 all(min(abs(r.box()[0][2] - z0 - 5), abs(r.box()[1][2] - z1 + 5)) < 0.3 for r in rohre),
                 [round(r.box()[0][2] - z0, 2) for r in rohre], 5)
    stueck = rt.bom() if hasattr(rt, "bom") else {}
    zeilen = [z for z in (stueck.get("lines") or stueck.get("zeilen") or []) if "rohr-alu-12x1.0" in str(z)]
    b.pruefe("Rohre aus dem Lager (Stückliste)", bool(zeilen), len(zeilen), ">= 1")
    return b


T4 = Aufgabe(
    "t4", "Gestell aus Lagerteilen", "neu",
    "Baue mir ein Gestell: vier senkrechte Alurohre 12 × 1 aus dem Lager, je 300 mm lang, die Rohrmitten in den Ecken "
    "eines Rechtecks 160 × 110 mm. Oben und unten je eine Platte als Druckteil aus PETG, 200 × 150 × 20 mm, mittig "
    "darüber, mit Sacklöchern Ø 12,2 mm, 15 mm tief, in denen die Rohre stecken.",
    _gestell, T4_REF, schwer=2, merkmale=["Lagerteile", "Baugruppe", "Sacklöcher", "Lagebeziehung"])

# ---------------------------------------------------------------------------------------------------------------------
# T5 Flansch ändern, T6 Platte ändern (gezielte Änderungen am offenen Modell)

T5 = Aufgabe(
    "t5", "Flansch ändern", "aenderung",
    "Ändere den Flansch: acht statt sechs Bohrungen, Ø 6,6 statt 5,5 mm, auf einem Lochkreis Ø 72 mm. Die Scheibe "
    "soll 10 mm dick werden, die Gesamthöhe bleibt 25 mm.",
    lambda rt: _flansch(rt, 10, 6.6, 8, 72), T2_REF.replace('param("anzahl", 6)', 'param("anzahl", 8)'),
    vorlage=T2_REF, schwer=1, merkmale=["Änderung", "Parameter", "Lochkreis"])

T6 = Aufgabe(
    "t6", "Platte ändern", "aenderung",
    "Mach die Platte 150 mm breit und 8 mm dick; der Lochabstand in der Breite wird 130 mm.",
    lambda rt: _platte(rt, 150, 8, 130), T1_REF, vorlage=T1_REF, schwer=1, merkmale=["Änderung", "Parameter"])

# ---------------------------------------------------------------------------------------------------------------------
# T7 Kugelschieber ändern (großes Modell: 134 Teile, model.py 78.000 Zeichen; Kopie, Kevins Projekt bleibt unberührt)

KUGEL = Path.home() / "Documents" / "Kev CAD" / "Kugelschieber Variante B"
REFERENZEN = Path(__file__).resolve().parent / "referenzen"


def _wie_referenz(aufgabe_id: str, tol: float = 0.05) -> Callable[[Any], Bogen]:
    """Orakel für Änderungen an großen Modellen: jedes Teil wie in der Referenz (dasselbe model.py mit dem Zielwert
    gerechnet), Hüllquader auf ``tol`` mm, Volumen auf 0,1 %. Die Referenz schreibt Stufe A (``--referenz``)."""
    def pruefen(rt: Any) -> Bogen:
        b = Bogen()
        datei = REFERENZEN / f"{aufgabe_id}.json"
        if not datei.is_file():
            b.pruefe(f"Referenz fehlt: erst lauf.py --referenz --aufgaben {aufgabe_id}", False)
            return b
        ref = json.loads(datei.read_text(encoding="utf-8"))
        ist = {x.name: x for x in teile(rt)}
        b.pruefe("dieselben Teile", set(ist) == set(ref), sorted(set(ist) ^ set(ref))[:8], len(ref))
        abw = []
        for name in sorted(set(ist) & set(ref)):
            lo, hi = ist[name].box()
            box = [*lo, *hi]
            if any(abs(a - c) > tol for a, c in zip(box, ref[name]["box"])) or \
                    abs(ist[name].volumen - ref[name]["vol"]) > max(1.0, 0.001 * ref[name]["vol"]):
                abw.append(name)
        b.pruefe("alle Teile wie die Referenz", not abw, abw[:6], 0)
        return b
    return pruefen


def fingerabdruck(rt: Any) -> dict[str, Any]:
    out = {}
    for x in teile(rt):
        lo, hi = x.box()
        out[x.name] = {"box": [round(v, 4) for v in (*lo, *hi)], "vol": round(x.volumen, 3)}
    return out


T7 = Aufgabe(
    "t7", "Kugelschieber ändern", "aenderung",
    "Die Laufrollen am Kugelschieber sollen 90 mm lang werden statt 100.",
    _wie_referenz("t7"), "", schwer=2, merkmale=["großes Modell", "Änderung", "Parameter"])
T7.vorlage_ordner = KUGEL  # type: ignore[attr-defined]

ALLE = {a.id: a for a in (T1, T2, T3, T4, T5, T6, T7)}


# ---------------------------------------------------------------------------------------------------------------------
# Stufe D: Ketten. Erst ein Neubau, dann eine Änderung daran; die Änderung läuft zweimal am gleichen Stand: in derselben
# Sitzung (``--resume``, der Agent kennt sein Modell) und frisch an einer Kopie des Projekts (er muss es sich holen).


@dataclass
class Kette:
    id: str
    titel: str
    erste: Aufgabe
    zweite: Aufgabe
    art: str = "kette"


K1 = Kette("k1", "Platte bauen, dann ändern", T1, T6)
K2 = Kette("k2", "Flansch bauen, dann ändern", T2, T5)
KETTEN = {k.id: k for k in (K1, K2)}

# Musterlösungen der Änderungen (nur Stufe A): Parameterwerte, die die Änderung herstellen
REFERENZ_PARAMS = {
    "t5": {"anzahl": 8, "loch_d": 6.6, "lochkreis_d": 72, "scheibe_h": 10},
    "t6": {"breite": 150, "dicke": 8, "abstand_x": 130},
    "t7": {"laufrolle_l": 90},
}
