"""Statik, Nachbesserung (PLAN-STATIK.md, Zweig „statik-nach“, T30 bis T32): Lastaufteilung auf Halter und Verbinder
nach Steifigkeit (Handrechnung Hebelgesetz bzw. eingespannter Träger), Gelenke mit Bereich als festgestellt,
Kragträger der Verbinder aus den Kräften des Stabwerks, Kraftpaare (innere Kräfte) für Kippen, Rutschen und Bauteile.
"""

from __future__ import annotations

import numpy as np
import pytest

from kevcad_kernel.protocol import check_statics_message, pack_statics, statik_beispiel
from kevcad_kernel.statik import anbindung
from kevcad_kernel.statik.bericht import szenario_text
from kevcad_kernel.statik.szenario import aus_modell, last_aus
from test_statik import laufe, szenario

# ---------------------------------------------------------------------------------------------------------------------
# Querstange in zwei gleichen Haltern an der Wand (geerdet): Lagerkräfte nach Steifigkeit

HALTERPAAR = '''
from build123d import *
from kevcad import lager, show, befestigt
from kevcad.bedingungen import verbinde
import kevcad.statik as st

show(Pos(-5, 0, 100) * Box(10, 800, 200), "Kulisse/Wand", kulisse=True)
for sy, seite in ((1, "links"), (-1, "rechts")):
    n = f"Halter {seite} (Druck)"
    form = Pos(20, sy * 300, 100) * Box(40, 30, 40) - Pos(25, sy * 300, 100) * Rot(90, 0, 0) * Cylinder(10.65, 30)
    show(lager.druckteil(form, n, material="petg", ausrichtung="-z"), n, material="petg")
    befestigt(n, grund="an die Wand geschraubt")
rohr = lager.teil("rohr-en10220-21.3x2.0")
show(Pos(25, -330, 100) * Rot(-90, 0, 0) * rohr.verbauen(laenge=660, name="Stange"), "Stange")
verbinde("Stange", "Halter links (Druck)", art=ART)
verbinde("Stange", "Halter rechts (Druck)", art=ART)
st.szenario("Mitte")
st.last("Stange", kraft=(0, 0, -100), punkt=(25, 0, 100))
st.szenario("Außermittig")
st.last("Stange", kraft=(0, 0, -100), punkt=(25, 150, 100))
'''


def _lagerkraft(e: dict, e0: dict, teil: str) -> np.ndarray:
    """Lagerkraft (N) eines Halters aus der Last allein: Szenario minus Eigengewicht (linear, Überlagerung)."""
    def summe(x: dict) -> np.ndarray:
        return np.sum([a["kraft"] for a in x["auflager"] if a["teil"] == teil], axis=0)
    return summe(e) - summe(e0)


@pytest.mark.parametrize("art", ["steck", "aufliegen"])
def test_halterpaar_mitte_halbe_halbe_aussermittig_nach_steifigkeit(tmp_path, art):
    """100 N in der Mitte: je Halter 50 N. Außermittig (150 mm neben der Mitte): steck (eingespannt) nach dem beidseitig
    eingespannten Träger R_A = P b² (3a + b) / L³, aufliegen (gelenkig) nach dem Hebelgesetz R_A = P b / L. Die
    Abstände kommen aus den Anschlüssen des Modells."""
    _, check, _ = laufe(tmp_path, HALTERPAAR.replace("ART", repr(art)), strikt=False)
    m = anbindung.LETZTER.modell
    s = m.staebe["Stange"]
    t = {a.teile[1]: a.t for a in m.anschluesse if a.stab == "Stange"}
    tl, tr = t["Halter links (Druck)"], t["Halter rechts (Druck)"]
    assert {a.art for a in m.anschluesse if a.stab == "Stange"} == {"fest" if art == "steck" else "gelenkig"}
    e0 = szenario(check, "Eigengewicht")
    mitte = szenario(check, "Mitte")
    ml = _lagerkraft(mitte, e0, "Halter links (Druck)")[2]
    mr = _lagerkraft(mitte, e0, "Halter rechts (Druck)")[2]
    assert ml == pytest.approx(50.0, abs=0.5) and mr == pytest.approx(50.0, abs=0.5)
    # außermittig: Last bei y = 150 (näher am linken Halter)
    aus = szenario(check, "Außermittig")
    fl = _lagerkraft(aus, e0, "Halter links (Druck)")[2]
    fr = _lagerkraft(aus, e0, "Halter rechts (Druck)")[2]
    P = 100.0
    tp = s.t_von(np.array([25.0, 150.0, 100.0]))
    lo, hi = sorted((tl, tr))
    a, b = tp - lo, hi - tp  # a: Abstand zum Halter bei kleinem t (rechts, y = −300), b: zum anderen
    L = a + b
    if art == "steck":
        r_klein, r_gross = P * b * b * (3 * a + b) / L ** 3, P * a * a * (a + 3 * b) / L ** 3
    else:
        r_klein, r_gross = P * b / L, P * a / L
    r_rechts, r_links = (r_klein, r_gross) if tr < tl else (r_gross, r_klein)
    assert fl + fr == pytest.approx(P, rel=1e-3)
    assert fl == pytest.approx(r_links, rel=0.02) and fr == pytest.approx(r_rechts, rel=0.02)
    print(f"Halterpaar {art}: Mitte {ml:.2f}/{mr:.2f} N; außermittig links {fl:.2f} N (Hand {r_links:.2f}), rechts "
          f"{fr:.2f} N (Hand {r_rechts:.2f}), L = {L:.1f} mm, a = {a:.1f} mm")


# ---------------------------------------------------------------------------------------------------------------------
# Querstange in zwei Schlitten auf zwei auskragenden Seitenstangen (wie am Kugelschieber): Verbinder zwischen Stäben

SCHLITTEN = '''
from build123d import *
from kevcad import lager, show
from kevcad.bedingungen import verbinde, schiebegelenk, bezug
import kevcad.statik as st

R = 21.3 / 2
YS, ZS, ZQ, XS = 150, 100, 60, 500
rohr = lager.teil("rohr-en10220-21.3x2.0")
for sy, seite in ((1, "links"), (-1, "rechts")):
    sockel = (Pos(30, sy * YS, (ZS + 30) / 2) * Box(60, 50, ZS + 30)
              - Pos(0, sy * YS, ZS) * Rot(0, 90, 0) * Cylinder(R, 200))
    show(sockel, f"Sockel {seite}", material="multiplex-birke")
    show(Pos(0, sy * YS, ZS) * Rot(0, 90, 0) * rohr.verbauen(laenge=620, name=f"Seitenstange {seite}"),
         f"Seitenstange {seite}")
    verbinde(f"Seitenstange {seite}", f"Sockel {seite}", art="steck")
    schlitten = (Pos(XS, sy * YS, (ZS + ZQ) / 2) * Box(40, 50, 90)
                 - Pos(XS, sy * YS, ZS) * Rot(0, 90, 0) * Cylinder(R, 100)
                 - Pos(XS, sy * YS, ZQ) * Rot(90, 0, 0) * Cylinder(R, 100))
    show(lager.druckteil(schlitten, f"Schlitten {seite} (Druck)", material="petg", ausrichtung="-z"),
         f"Schlitten {seite} (Druck)", material="petg")
show(Pos(XS, -(YS + 25), ZQ) * Rot(-90, 0, 0) * rohr.verbauen(laenge=2 * (YS + 25), name="Querstange"), "Querstange")
verbinde("Querstange", "Schlitten links (Druck)", art="steck")
verbinde("Querstange", "Schlitten rechts (Druck)", art="steck")
verbinde("Schlitten rechts (Druck)", "Seitenstange rechts", art="klemmung")
achse = Axis((XS, YS, ZS), (1, 0, 0))
schiebegelenk(bezug("Schlitten links (Druck)", "Achse", achse), bezug("Seitenstange links", "Achse", achse),
              bereich=BEREICH)
st.szenario("Ball drückt 100 N")
st.last("Querstange", kraft=(100, 0, 0), punkt=(XS, 0, ZQ))
st.szenario("Außermittig")
st.last("Querstange", kraft=(100, 0, 0), punkt=(XS, 75, ZQ))
'''


def _verbinder(e: dict, e0: dict, teil: str, stab: str) -> np.ndarray:
    def kraft(x: dict) -> np.ndarray:
        return np.asarray(next(v["kraft"] for v in x["verbinder"] if v["teil"] == teil and v["stab"] == stab))
    return kraft(e) - kraft(e0)


def test_schlitten_teilen_die_last_halbe_halbe(tmp_path):
    """Kugelschieber-Befund: Ein Schlitten sitzt über ein Schiebegelenk mit Bereich (Einstellung, mit Klemme
    festgestellt), der andere über verbinde(…, klemmung). Beide tragen 50 N; die Kräfte je Anschluss kommen aus dem
    Stabwerk und gehen in den Kragträger und den Festkörper beider Schlitten."""
    _, check, _ = laufe(tmp_path, SCHLITTEN.replace("BEREICH", "(-100, 50)"), strikt=False)
    m = anbindung.LETZTER.modell
    arten = {a.teile[1]: (a.art, a.quelle) for a in m.anschluesse if a.stab.startswith("Seitenstange")}
    assert arten["Schlitten links (Druck)"][0] == "fest" and "festgestellt" in arten["Schlitten links (Druck)"][1]
    e = szenario(check, "Ball drückt 100 N")
    e0 = szenario(check, "Eigengewicht")
    links = _verbinder(e, e0, "Schlitten links (Druck)", "Querstange")
    rechts = _verbinder(e, e0, "Schlitten rechts (Druck)", "Querstange")
    assert links[0] == pytest.approx(50.0, abs=0.5) and rechts[0] == pytest.approx(50.0, abs=0.5)
    # Gegenstück: die Seitenstange hält den Schlitten mit derselben Kraft (Starrkörper im Gleichgewicht)
    assert _verbinder(e, e0, "Schlitten links (Druck)", "Seitenstange links")[0] == pytest.approx(-50.0, abs=0.5)
    # Kragträger der Verbinder (S0/S1): beide nachgewiesen, gehalten von ihrer Seitenstange, belastet mit 50 N
    vb = {b["teil"]: b for b in e["bauteile"] if b.get("aus_verbinder")}
    assert set(vb) == {"Schlitten links (Druck)", "Schlitten rechts (Druck)"}
    for seite in ("links", "rechts"):
        b = vb[f"Schlitten {seite} (Druck)"]
        assert b["aus_verbinder"] == f"Seitenstange {seite}" and b["nachbarn"] == [f"Seitenstange {seite}"]
        assert b["kraft"][0] == pytest.approx(50.0, abs=1.0) and b["sicherheit"] > 0
    # gleiche Last, gleicher Hebel; die Sicherheit weicht nur ab, weil der Kragträger einen Schnitt durch die Bohrung
    # einseitig nimmt (grob, S0). Genauer rechnet der Festkörper.
    assert vb["Schlitten links (Druck)"]["hebel_mm"] == pytest.approx(vb["Schlitten rechts (Druck)"]["hebel_mm"])
    assert vb["Schlitten links (Druck)"]["sicherheit"] == pytest.approx(vb["Schlitten rechts (Druck)"]["sicherheit"],
                                                                        rel=0.2)
    # Festkörper (S3): die Fälle bekommen dieselben Kräfte je Anschluss, Lager ist die Seitenstange
    from kevcad_kernel.statik.festkoerper.auftrag import faelle

    fs = {f["teil"]: f for f in faelle(anbindung.LETZTER, {"szenarien": ["Ball drückt 100 N"]})}
    for seite in ("links", "rechts"):
        f = fs[f"Schlitten {seite} (Druck)"]
        stab = {l["kontakt_mit"]: l for l in f["lasten"]}
        assert stab["Querstange"]["kraft"][0] == pytest.approx(50.0, abs=1.0)
        assert f["s0"]["aus_verbinder"] == f"Seitenstange {seite}"
    text = szenario_text(_auszug(e), detail=True)
    assert "Verbinder Schlitten links (Druck): Querstange" in text
    # außermittig (75 mm neben der Mitte, zum linken Schlitten hin): nach Steifigkeit. Handrechnung: Querstange als
    # Träger auf zwei starren Stützen (die Seitenstangen sind in x 25-mal steifer als die Querstange in Biegung) mit
    # Drehfedern k = E I / L_s an den Enden (Biegung der auskragenden Seitenstange um z); dazwischen liegen das
    # Hebelgesetz (k = 0) und der beidseitig eingespannte Träger (k → ∞).
    s, q = m.staebe["Seitenstange links"], m.staebe["Querstange"]
    EI = float(q.werkstoff.E) * q.q.I_lang
    t_s = {a.teile[1]: a.t for a in m.anschluesse if a.stab == "Seitenstange links"}
    k = float(s.werkstoff.E) * s.q.I_lang / (t_s["Schlitten links (Druck)"] - t_s["Sockel links"])
    t_q = {a.teile[1]: a.t for a in m.anschluesse if a.stab == "Querstange"}
    L = t_q["Schlitten links (Druck)"] - t_q["Schlitten rechts (Druck)"]
    a = q.t_von(np.array([500.0, 75.0, 60.0])) - t_q["Schlitten rechts (Druck)"]
    b = L - a
    P = 100.0
    th_a0, th_b0 = P * a * b * (L + b) / (6 * EI * L), P * a * b * (L + a) / (6 * EI * L)
    # Federmomente M = k θ mit θ = θ0 − M L / (3 E I) − M_andere L / (6 E I)
    A = np.array([[1 / k + L / (3 * EI), L / (6 * EI)], [L / (6 * EI), 1 / k + L / (3 * EI)]])
    m_a, m_b = np.linalg.solve(A, [th_a0, th_b0])
    r_rechts, r_links = P * b / L + (m_a - m_b) / L, P * a / L - (m_a - m_b) / L
    aus = szenario(check, "Außermittig")
    links = _verbinder(aus, e0, "Schlitten links (Druck)", "Querstange")[0]
    rechts = _verbinder(aus, e0, "Schlitten rechts (Druck)", "Querstange")[0]
    assert links + rechts == pytest.approx(P, rel=1e-3)
    assert links == pytest.approx(r_links, rel=0.03) and rechts == pytest.approx(r_rechts, rel=0.03)
    assert P * a / L < links < P * a * a * (a + 3 * b) / L ** 3  # zwischen Hebelgesetz und Einspannung
    print(f"Schlitten außermittig: links {links:.2f} N (Hand {r_links:.2f}), rechts {rechts:.2f} N (Hand "
          f"{r_rechts:.2f}); Hebelgesetz {P * a / L:.1f}, eingespannt {P * a * a * (a + 3 * b) / L ** 3:.1f}")


def _auszug(e: dict) -> dict:
    from kevcad_kernel.statik.laufzeit import _szenario_auszug

    return _szenario_auszug(e, detail=True)


def test_schiebegelenk_ohne_bereich_bleibt_frei(tmp_path):
    """Gegenprobe: Ein Schiebegelenk ohne Bereich läuft frei (Hülse); dann geht die Kraft längs der Führung ganz über
    den anderen Schlitten. So wie es vorher auch mit Bereich gerechnet wurde."""
    _, check, _ = laufe(tmp_path, SCHLITTEN.replace("BEREICH", "None"), strikt=False)
    e = szenario(check, "Ball drückt 100 N")
    e0 = szenario(check, "Eigengewicht")
    links = _verbinder(e, e0, "Schlitten links (Druck)", "Querstange")
    rechts = _verbinder(e, e0, "Schlitten rechts (Druck)", "Querstange")
    assert abs(links[0]) < 0.5 and rechts[0] == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------------------------------------------------
# Kraftpaare (innere Kräfte)

PAAR = '''
from build123d import *
from kevcad import lager, show
from kevcad.bedingungen import verbinde
import kevcad.statik as st

show(Pos(0, 0, 9) * Box(300, 200, 18), "Wagen/Platte", material="multiplex-birke")
arm = Pos(120, 0, 38) * Box(60, 20, 40)
show(lager.druckteil(arm, "Wagen/Fänger (Druck)", material="petg", ausrichtung="-z"), "Wagen/Fänger (Druck)",
     material="petg")
verbinde("Wagen/Fänger (Druck)", "Wagen/Platte", art="kleben")
show(Pos(260, 0, 50) * Sphere(50), "Ball")  # liegt frei auf dem Boden, 60 mm vor dem Fänger
st.szenario("Ball drückt")
st.last("Wagen/Fänger (Druck)", kraft=(-60, 0, 0), punkt=(150, 0, 50)GEGEN)
'''


def test_kraftpaar_rutschen_verschwindet_bauteil_bleibt(tmp_path):
    """Der Ball drückt mit 60 N gegen den Fänger auf einem leichten Wagen. Als äußere Last rutscht der Wagen (nötig μ
    weit über dem Reibwert); als Kraftpaar mit dem Ball heben sich Kraft und Gegenkraft für das Ganze auf: kein
    Rutschen, kein Kippen, die Spannung im Fänger bleibt gleich."""
    _, aussen, _ = laufe(tmp_path, PAAR.replace("GEGEN", ""), strikt=False)
    ea = szenario(aussen, "Ball drückt")
    assert any(u["art"] == "rutschen" and u["ampel"] == "rot" for u in ea["urteile"]), ea["urteile"]
    ba = next(b for b in ea["bauteile"] if b["teil"] == "Wagen/Fänger (Druck)")
    paar_tmp = tmp_path / "paar"
    paar_tmp.mkdir()
    _, innen, _ = laufe(paar_tmp, PAAR.replace("GEGEN", ', gegen="Ball"'), strikt=False)
    ei = szenario(innen, "Ball drückt")
    assert not [u for u in ei["urteile"] if u["art"] in ("rutschen", "kippen")], ei["urteile"]
    assert not any(b["art"] == "statik_rutschen" for b in innen["befunde"])
    bi = next(b for b in ei["bauteile"] if b["teil"] == "Wagen/Fänger (Druck)")
    assert bi["sicherheit"] == pytest.approx(ba["sicherheit"], rel=1e-6)
    assert bi["kraftpaar"] == {"gegen": ["Ball"], "gegenkraft": False}
    # im Ergebnis als Paar erkennbar: Szenario und Lasten mit gegen und paar
    last = ei["szenario"]["lasten"][0]
    assert last["gegen"] == ["Ball"] and last["paar"] is True
    anz = ei["lasten"][0]
    assert anz["paar"] and anz["gegen"] == ["Ball"] and anz["punkt"] == [150.0, 0.0, 50.0]
    # STATICS an die App trägt die Lasten mit dem Paar
    head = pack_statics(innen["statik"], run=1)
    assert not check_statics_message(head)
    hl = next(e for e in head["szenarien"] if e["name"] == "Ball drückt")["lasten"][0]
    assert hl["paar"] and hl["gegen"] == ["Ball"]
    text = szenario_text(_auszug(ei), detail=True)
    assert "Kraftpaar: (-60; 0; 0) N auf Fänger (Druck), Gegenkraft auf Ball" in text


def test_kraftpaar_api_und_szenario_ereignisse():
    ereignisse = [
        {"was": "szenario", "name": "Ball drückt"},
        {"was": "last", "teile": ["Kugelschieber/Querstange vorn (Rohr 3)"], "kraft": [100, 0, 0], "punkt": None,
         "gegen": ["Bowlingball"], "szenario": "Ball drückt", "zeile": 7},
    ]
    szen, einst = aus_modell(ereignisse)
    assert not einst["warnungen"]
    sz = next(s for s in szen if s.name == "Ball drückt")
    assert sz.lasten[0].gegen == ["Bowlingball"] and sz.lasten[0].paar
    assert sz.kurz()["lasten"][0]["paar"] is True
    with pytest.raises(ValueError, match="anderes Teil"):
        last_aus({"teil": "A", "kraft": [1, 0, 0], "gegen": "A"})


def test_statics_mit_lasten_und_kraftpaar():
    b = statik_beispiel()
    head = pack_statics(b, run=3)
    assert not check_statics_message(head)
    sz = next(e for e in head["szenarien"] if e["name"] == "Aufstützen 30 kg")
    paar = [l for l in sz["lasten"] if l.get("paar")]
    assert len(sz["lasten"]) == 2 and paar and paar[0]["gegen"] == ["Ball"]
    kaputt = pack_statics({**b, "szenarien": [dict(b["szenarien"][1], lasten=[{"teile": ["X"], "kraft": [1, 0],
                                                                               "punkt": [0, 0, 0], "paar": True}])]},
                          run=3)
    fehler = check_statics_message(kaputt)
    assert any("kraft" in f for f in fehler) and any("ohne gegen" in f for f in fehler)
