"""Bereich „Simulation“, offene Grenzen geschlossen (PLAN-SIMULATION.md, Zweig ``simulation2``): Lager je Lastfall,
gleitende Lager in beliebiger Richtung (Stabwerk und FEM), gelenkige Lager auf einer Fläche in der FEM (RBE3-artig),
Last auf der ganzen Fläche (gleichmäßig und als Druck), Untergrund je Lastfall im Ablauf, „Grenze suchen“ mit der FEM.
Wo es um Mechanik geht, gegen die Handrechnung.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.simulation import datei as dt
from kevcad_kernel.simulation import kraft as kr
from kevcad_kernel.statik import anbindung
from test_simulation import ROHR, _durchbiegung, _rohr, _sim
from test_statik import laufe, szenario

G = 9.81


# ---------------------------------------------------------------------------------------------------------------------
# Format: Lager je Lastfall, Gleitrichtung, Last auf der ganzen Fläche


def _ort(flaeche: int = 5, a: float = 800.0, n=(0, 0, 1)) -> dict:
    return {"flaeche": flaeche, "punkt": [40, 0, 60], "normale": list(n),
            "signatur": {"t": "plane", "a": a, "n": list(n), "c": [40, 0, 60]}}


def test_format_lager_je_lastfall_und_gleiten():
    doc, m = dt.anwenden(dt.leer(), [
        {"op": "lastfall_neu", "name": "A"}, {"op": "lastfall_neu", "name": "B"},
        {"op": "lager_setzen", "lager": {"teil": "Halter", "art": "fest", "ort": _ort(), "szenarien": ["A"]}},
        {"op": "lager_setzen", "lager": {"teil": "Halter", "art": "gleitend", "ort": _ort(),
                                         "gleiten": {"art": "richtung", "richtung": [0, 2, 0], "quelle": "kante",
                                                     "kante": 7}}},
        {"op": "lager_setzen", "lager": {"teil": "Halter", "art": "gleitend", "ort": {"punkt": [0, 0, 0]},
                                         "gleiten": "-x"}},
    ])
    a1, a2, a3 = doc["lager"]
    assert a1["szenarien"] == ["A"] and "nur in „A“" in m[2]
    assert a2["szenarien"] is None and a2["gleiten"] == {"art": "richtung", "richtung": [0, 1, 0], "quelle": "kante",
                                                        "kante": 7}
    assert a3["gleiten"]["richtung"] == [-1, 0, 0] and a3["gleiten"]["quelle"] == "achse"  # ohne Fläche: Richtung reicht
    # umbenennen folgt, löschen lässt das Lager „in keinem Lastfall“
    doc, _ = dt.anwenden(doc, [{"op": "lastfall_umbenennen", "name": "A", "neu": "A2"}])
    assert doc["lager"][0]["szenarien"] == ["A2"]
    doc, m = dt.anwenden(doc, [{"op": "lastfall_loeschen", "name": "A2"}])
    assert doc["lager"][0]["szenarien"] == [] and "in keinem Lastfall" in m[0]
    # unbekannter Lastfall: abgelehnt, sobald die Szenarien des Laufs bekannt sind
    with pytest.raises(dt.SimulationFehler, match="gibt es nicht"):
        dt.anwenden(doc, [{"op": "lager_setzen", "lager": {"teil": "Halter", "art": "fest", "ort": _ort(),
                                                            "szenarien": ["Zauber"]}}], {"Eigengewicht": {}})
    # gleiten nur für gleitende Lager; ohne Normale und ohne Richtung abgelehnt
    doc2, _ = dt.anwenden(dt.leer(), [{"op": "lager_setzen", "lager": {"teil": "T", "art": "fest", "ort": _ort(),
                                                                       "gleiten": "+x"}}])
    assert "gleiten" not in doc2["lager"][0]
    with pytest.raises(dt.SimulationFehler, match="Gleitrichtung"):
        dt.anwenden(dt.leer(), [{"op": "lager_setzen", "lager": {"teil": "T", "art": "gleitend",
                                                                  "ort": {"punkt": [0, 0, 0]}}}])


def test_format_last_auf_der_ganzen_flaeche():
    # Druck 0,05 N/mm² auf 800 mm², senkrecht in die Fläche: 40 N
    doc, m = dt.anwenden(dt.leer(), [
        {"op": "lastfall_neu", "name": "Druck"},
        {"op": "last_setzen", "lastfall": "Druck", "last": {"teil": "Halter", "ort": _ort(), "verteilung": "flaeche",
                                                           "richtung": {"art": "normale"}, "betrag": 0.05,
                                                           "einheit": "N/mm²"}},
        {"op": "last_setzen", "lastfall": "Druck", "last": {"teil": "Halter", "ort": _ort(), "verteilung": "flaeche",
                                                           "richtung": {"art": "achse", "achse": "+y"},
                                                           "betrag": 30, "einheit": "N"}}])
    l1, l2 = doc["lastfaelle"][0]["lasten"]
    assert l1["einheit"] == "N/mm2" and l1["verteilung"] == "flaeche" and l1["kraft"] == pytest.approx([0, 0, -40])
    assert "N/mm² auf die ganze Fläche = 40 N" in m[1]
    assert l2["kraft"] == pytest.approx([0, 30, 0]) and "auf die ganze Fläche" in m[2]
    with pytest.raises(dt.SimulationFehler, match="senkrecht"):
        dt.anwenden(doc, [{"op": "last_setzen", "lastfall": "Druck", "last": {
            "teil": "Halter", "ort": _ort(), "verteilung": "flaeche", "richtung": {"art": "achse"}, "betrag": 1,
            "einheit": "N/mm2"}}])
    with pytest.raises(dt.SimulationFehler, match="ganze Fläche"):
        dt.anwenden(doc, [{"op": "last_setzen", "lastfall": "Druck", "last": {
            "teil": "Halter", "ort": _ort(), "richtung": {"art": "normale"}, "betrag": 1, "einheit": "N/mm2"}}])
    with pytest.raises(dt.SimulationFehler, match="Fläche anklicken"):
        dt.anwenden(doc, [{"op": "last_setzen", "lastfall": "Druck", "last": {
            "teil": "Halter", "ort": {"punkt": [0, 0, 0]}, "verteilung": "flaeche", "betrag": 1}}])
    assert kr.kraft_aus({"art": "normale", "umkehren": True}, 0.1, "N/mm2", (0, 0, 1), flaeche_mm2=200).tolist() \
        == pytest.approx([0, 0, 20])
    with pytest.raises(kr.KraftFehler, match="Flächeninhalt"):
        kr.kraft_aus({"art": "normale"}, 0.1, "N/mm2", (0, 0, 1))


# ---------------------------------------------------------------------------------------------------------------------
# Gleitendes Lager schräg (Stabwerk) gegen die Handrechnung


def test_gleitendes_lager_schraeg_im_stabwerk(tmp_path):
    """Rohr 21,3 × 2, 1000 mm, links gelenkig, rechts auf einer um α = 30° geneigten Ebene gleitend (Normale
    (−sin α, 0, cos α)), 200 N in der Mitte. Die Lagerkraft rechts steht senkrecht auf der Ebene: R = (F + q L) /
    (2 cos α), waagrecht R sin α, die das gelenkige Lager links aufnimmt. Gerundet auf die nächste Achse (bisher) wäre
    die waagrechte Kraft 0."""
    a = math.radians(30)
    n = (-math.sin(a), 0.0, math.cos(a))
    lager = ('st.lager("Rohr", punkt=(0, 0, 500), art="gelenkig")\n'
             f'st.lager("Rohr", punkt=(1000, 0, 500), art="gleitend", normale={n})')
    check, EI, q, L = _rohr(tmp_path, lager)
    e = szenario(check, "Last")
    k = {x["teil"]: x["kraft"] for x in e["auflager"]}
    V = 200 + q * L
    R = V / (2 * math.cos(a))
    assert k["Lager: M2"] == pytest.approx([-R * math.sin(a), 0, R * math.cos(a)], abs=0.05)
    assert k["Lager: M1"] == pytest.approx([R * math.sin(a), 0, V / 2], abs=0.05)
    # Kraft auf die schräge Ebene steht senkrecht auf ihr
    r = np.asarray(k["Lager: M2"])
    assert abs(float(np.dot(r, [math.cos(a), 0, math.sin(a)]))) < 0.05
    w_hand = 200 * L ** 3 / (48 * EI) + 5 * q * L ** 4 / (384 * EI)
    assert _durchbiegung(e) == pytest.approx(w_hand, rel=0.03)
    # dasselbe als Schiene entlang der Ebene (gleiten = Tangente): hält senkrecht zur Ebene und quer (y)
    lager2 = ('st.lager("Rohr", punkt=(0, 0, 500), art="gelenkig")\n'
              f'st.lager("Rohr", punkt=(1000, 0, 500), art="gleitend", gleiten=({math.cos(a)}, 0, {math.sin(a)}))')
    check2, *_ = _rohr(tmp_path, lager2, run=2)
    k2 = {x["teil"]: x["kraft"] for x in szenario(check2, "Last")["auflager"]}
    assert k2["Lager: M2"] == pytest.approx(k["Lager: M2"], abs=0.05)
    sim = check2["statik"]["simulation"]
    gl = next(x for x in sim["lager"] if x["id"] == "M2")
    assert gl["gleiten"]["quelle"] == "frei" and len(gl["gehalten"]) == 2
    print(f"Gleitend schräg 30°: rechts {np.round(k['Lager: M2'], 2).tolist()} N (Hand "
          f"{[-round(R * math.sin(a), 2), 0, round(R * math.cos(a), 2)]}), links {np.round(k['Lager: M1'], 2).tolist()}")


# ---------------------------------------------------------------------------------------------------------------------
# Lager je Lastfall gegen die Handrechnung

ZWEI_FAELLE = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

rohr = lager.teil("rohr-en10220-21.3x2.0")
show(Pos(0, 0, 500) * Rot(0, 90, 0) * rohr.verbauen(laenge=1000, name="Rohr"), "Rohr")
st.szenario("Kragarm")
st.last("Rohr", kraft=(0, 0, -20), punkt=(1000, 0, 500))
st.szenario("Gestützt")
st.last("Rohr", kraft=(0, 0, -20), punkt=(1000, 0, 500))
'''


def test_lager_je_lastfall(tmp_path):
    """Rohr links fest (alle Lastfälle), rechts ein gleitendes Lager nur im Lastfall „Gestützt“ (aus der App).
    „Kragarm“: w = F L³ / (3 E I) + q L⁴ / (8 E I), keine Kraft rechts. „Gestützt“ (eingespannt und gestützt): die
    Last steht über dem Lager, R_B = F + 3 q L / 8, Durchbiegung fast null."""
    def lager(x: float, art: str, szen=None) -> dict:
        d = {"teil": "Rohr", "art": art, "auf": "punkt", "ort": {"punkt": [x, 0, 500], "normale": [0, 0, 1]}}
        if szen is not None:
            d["szenarien"] = szen
        return d

    _sim(tmp_path, [], [lager(0, "fest"), lager(1000, "gleitend", ["Gestützt"])])
    _, check, _ = laufe(tmp_path, ZWEI_FAELLE, strikt=False)
    st = anbindung.LETZTER
    s = st.modell.staebe["Rohr"]
    EI = float(s.werkstoff.E) * float(s.q.I_lang)
    q = st.modell.teile["Rohr"].masse_kg * G / s.laenge
    L = s.laenge
    krag, gest = szenario(check, "Kragarm"), szenario(check, "Gestützt")
    assert krag["lager_ids"] == ["A1"] and gest["lager_ids"] == ["A1", "A2"]
    assert {a["teil"] for a in krag["auflager"]} == {"Lager: A1"}
    w_krag = 20 * L ** 3 / (3 * EI) + q * L ** 4 / (8 * EI)
    assert _durchbiegung(krag) == pytest.approx(w_krag, rel=0.02)
    rb = next(a for a in gest["auflager"] if a["teil"] == "Lager: A2")["kraft"][2]
    assert rb == pytest.approx(20 + 3 * q * L / 8, rel=0.01)
    assert _durchbiegung(gest) < 0.05 * w_krag
    assert st.modell_fuer("Gestützt") is not st.modell and len(st.modell_fuer("Gestützt").lager_explizit) == 2
    assert len(st.modell_fuer("Kragarm").lager_explizit) == 1
    # STATICS trägt die Lager je Szenario, SIM die Lastfälle des Lagers
    from kevcad_kernel.protocol import check_statics_message, pack_statics

    h = pack_statics(check["statik"], run=1)
    assert not check_statics_message(h)
    assert next(x for x in h["szenarien"] if x["name"] == "Gestützt")["lager"] == ["A1", "A2"]
    sim = check["statik"]["simulation"]
    assert sim["zustand"]["lager"]["A2"]["szenarien"] == ["Gestützt"]
    # ohne Lauf neu rechnen (Lager jetzt für alle): beide Lastfälle gestützt
    doc = dt.lies(tmp_path)
    doc["lager"][1]["szenarien"] = None
    dt.schreibe(tmp_path, doc)
    erg = anbindung.neu_mit_simulation()
    assert all(e["lager_ids"] == ["A1", "A2"] for e in erg["szenarien"])
    assert anbindung.LETZTER.modell_fuer("Kragarm") is anbindung.LETZTER.modell
    print(f"Lager je Lastfall: Kragarm w = {_durchbiegung(krag):.2f} mm (Hand {w_krag:.2f}), gestützt R_B = {rb:.2f} N "
          f"(Hand {20 + 3 * q * L / 8:.2f})")


# ---------------------------------------------------------------------------------------------------------------------
# Festkörper-FEM: gelenkige und gleitende Lager, Last auf der ganzen Fläche (Prozess direkt, Netz im Speicher je Test)


def _ebene(pfad: Path, mitte, normale, groesse: float = 400.0) -> str:
    """Nachbarnetz „Lagerfläche“: Quadrat in der Ebene durch ``mitte`` senkrecht zu ``normale``."""
    n = np.asarray(normale, float) / np.linalg.norm(normale)
    a = np.cross(n, [0, 0, 1.0]) if abs(n[2]) < 0.9 else np.cross(n, [1.0, 0, 0])
    a /= np.linalg.norm(a)
    b = np.cross(n, a)
    m = np.asarray(mitte, float)
    g = groesse / 2
    pos = np.array([m - a * g - b * g, m + a * g - b * g, m + a * g + b * g, m - a * g + b * g])
    np.savez(pfad, pos=pos, tri=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64))
    return str(pfad)


def _flaeche_npz(pfad: Path, face) -> str:
    """Netz einer build123d-Fläche (Lastfläche) wie ``zuordnung.flaechen_netz``."""
    pts, tris = face.tessellate(0.05)
    np.savez(pfad, pos=np.array([[p.X, p.Y, p.Z] for p in pts], float), tri=np.asarray(tris, dtype=np.int64))
    return str(pfad)


def _balken(tmp: Path, lager_art: str):
    """Balken 200 × 20 × 20 mm (PLA aus dem Katalog), Stirnflächen gelagert, 100 N gleichmäßig auf der ganzen
    Oberseite."""
    from build123d import Axis, Box, Location
    from test_festkoerper import _brep, _rechne, _teil, mechanik

    me = mechanik("pla")
    E, nu = float(me["e_modul"]), float(me.get("querkontraktion") or 0.3)
    L, b, h, F = 200.0, 20.0, 20.0, 100.0
    form = Box(L, b, h).moved(Location((L / 2, 0, h / 2)))
    brep = _brep(form, tmp / "balken.brep")
    oben = form.faces().sort_by(Axis.Z)[-1]
    nachbarn = {}
    for name, x, n in (("Lager: L", 0.0, (-1, 0, 0)), ("Lager: R", L, (1, 0, 0))):
        nb = {"datei": _ebene(tmp / f"{name[-1]}.npz", (x, 0, h / 2), n), "tol": 0.3}
        if lager_art == "gelenkig":
            nb.update({"art": "gelenkig", "drehachsen": [list(n)]})
        nachbarn[name] = nb
    w = {"E": E, "nu": nu, "E_z": None, "f": float(me["zugfestigkeit"]), "q": None, "name": "PLA"}
    teil = _teil("Balken", brep, w, L * b * h, (0, -10, 0), (L, 10, h), nachbarn, h_mm=4.0)
    fall = {"id": "0.0", "szenario": "Last", "teil": "Balken", "ziel": 2.0, "schluessel": f"balken-{lager_art}",
            "lasten": [{"kraft": [0, 0, -F], "moment": None, "punkt": [L / 2, 0, h],
                        "flaeche": {"index": 5, "flaeche_mm2": L * b},
                        "flaeche_datei": _flaeche_npz(tmp / "oben.npz", oben)}],
            "lager": ["Lager: L", "Lager: R"], "feld": [0, 0, 0]}
    out, dauer = _rechne(tmp, teil, [fall])
    r = out["faelle"][0]
    assert r["stand"] == "done", r
    with np.load(r["feld"]) as z:
        P, U = z["punkte"].astype(float), z["verschiebung"].astype(float)
    I = b * h ** 3 / 12
    G_ = E / (2 * (1 + nu))
    kappa = 10 * (1 + nu) / (12 + 11 * nu)
    return {"r": r, "P": P, "U": U, "E": E, "I": I, "F": F, "L": L, "h": h, "schub": F * L / (8 * kappa * G_ * b * h),
            "dauer": dauer}


def _mitte_w(d: dict) -> float:
    """Durchbiegung in Feldmitte auf der neutralen Faser (Seitenfläche y = −10, z = 10)."""
    P, U = d["P"], d["U"]
    sel = (np.abs(P[:, 0] - d["L"] / 2) < 3) & (np.abs(P[:, 2] - d["h"] / 2) < 3) & (np.abs(P[:, 1] + 10) < 1e-3)
    assert sel.any()
    return float(-U[sel, 2].mean())


def _endwinkel(d: dict) -> float:
    """Drehung der linken Stirnfläche (rad): (u_x oben − u_x unten) / h (oben wandert ins Feld)."""
    P, U = d["P"], d["U"]
    ende = np.abs(P[:, 0]) < 1e-3
    oben = ende & (np.abs(P[:, 2] - d["h"]) < 1e-3)
    unten = ende & (np.abs(P[:, 2]) < 1e-3)
    return float((U[oben, 0].mean() - U[unten, 0].mean()) / d["h"])


def test_gelenkiges_lager_in_der_fem_und_flaechenlast(tmp_path):
    """Balken auf zwei gelenkigen Stirnflächen (RBE3-artig: Fläche hält im Mittel, dreht frei um die Querachsen,
    um ihre Normale gehalten), 100 N gleichmäßig auf der ganzen Oberseite: Durchbiegung in Feldmitte
    w = 5 F L³ / (384 E I) + F L / (8 κ G A) (Timoshenko, κ nach Cowper), Endverdrehung θ = F L² / (24 E I), je Lager
    F / 2. Gegenprobe beidseitig fest: w = F L³ / (384 E I) + F L / (8 κ G A), keine Endverdrehung."""
    (tmp_path / "g").mkdir()
    (tmp_path / "f").mkdir()
    g = _balken(tmp_path / "g", "gelenkig")
    f = _balken(tmp_path / "f", "fest")
    E, I, F, L = g["E"], g["I"], g["F"], g["L"]
    w_g = 5 * F * L ** 3 / (384 * E * I) + g["schub"]
    w_f = F * L ** 3 / (384 * E * I) + f["schub"]
    assert _mitte_w(g) == pytest.approx(w_g, rel=0.04)
    assert _mitte_w(f) == pytest.approx(w_f, rel=0.12)  # Einspannung der ganzen Stirnfläche: etwas steifer
    assert _mitte_w(g) > 3.5 * _mitte_w(f)
    theta = F * L ** 2 / (24 * E * I)
    assert _endwinkel(g) == pytest.approx(theta, rel=0.06)
    assert abs(_endwinkel(f)) < 0.05 * theta
    lk = g["r"]["lagerkraefte"]
    for name in ("Lager: L", "Lager: R"):
        assert lk[name] == pytest.approx([0, 0, F / 2], abs=0.02 * F)
    assert g["r"]["lagerarten"] == {"Lager: L": "gelenkig", "Lager: R": "gelenkig"}
    assert g["r"]["lastflaechen_mm2"][0] == pytest.approx(L * 20, rel=0.01)  # ganze Oberseite
    assert g["r"]["gleichgewicht_n"] < 1e-6
    print(f"Gelenkig (FEM): w {_mitte_w(g):.4f} mm (Hand {w_g:.4f}), θ {_endwinkel(g) * 1e3:.3f} mrad (Hand "
          f"{theta * 1e3:.3f}); fest: w {_mitte_w(f):.4f} mm (Hand {w_f:.4f}); Lager {lk}, {g['r']['netz']}")


def test_gleitende_lager_schraeg_in_der_fem(tmp_path):
    """Würfel 40 mm, um 30° um Y gekippt, liegt in einer reibungsfreien Ecke aus drei gleitenden Lagern (Unterseite,
    Vorderseite, Seite; je nur senkrecht gehalten, schräg zu den Achsen). Unter dem Eigengewicht W überträgt jede
    Fläche nur eine Kraft senkrecht zu sich: Σ Rᵢ (−nᵢ) = −W, also R_unten = W cos α, R_vorn = W sin α, R_seite = 0.
    Auf die nächste Achse gerundet (bisher) gäbe es R = W senkrecht und nichts waagrecht."""
    from build123d import Box, Rot
    from test_festkoerper import _brep, _rechne, _teil

    a = math.radians(30)
    form = Rot(0, 30, 0) * Box(40, 40, 40)
    brep = _brep(form, tmp_path / "klotz.brep")
    faces = list(form.faces())

    def normale(fc):
        n = fc.normal_at(fc.center())
        return np.array([n.X, n.Y, n.Z])

    unten = min(faces, key=lambda fc: normale(fc)[2])
    vorn = max(faces, key=lambda fc: normale(fc)[0])
    seite = min(faces, key=lambda fc: normale(fc)[1])
    nachbarn, ns = {}, {}
    for name, fc in (("Lager: U", unten), ("Lager: V", vorn), ("Lager: S", seite)):
        n = normale(fc)
        c = fc.center()
        ns[name] = n
        nachbarn[name] = {"datei": _ebene(tmp_path / f"{name[-1]}.npz", (c.X, c.Y, c.Z), n), "tol": 0.3,
                          "gehalten": [n.tolist()], "normale": n.tolist()}
    w = {"E": 3500.0, "nu": 0.35, "E_z": None, "f": 50.0, "q": None, "name": "PLA"}
    bb = form.bounding_box()
    teil = _teil("Klotz", brep, w, 64000.0, (bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z), nachbarn,
                 h_mm=5.0)
    teil["masse_kg"] = 10.0
    fall = {"id": "0.0", "szenario": "Ecke", "teil": "Klotz", "ziel": 2.0, "schluessel": "ecke-1", "lasten": [],
            "lager": list(nachbarn), "feld": [0, 0, -G]}
    out, _ = _rechne(tmp_path, teil, [fall])
    r = out["faelle"][0]
    assert r["stand"] == "done", r
    W = 10.0 * G
    Nm = np.stack([-ns[k] for k in nachbarn], axis=1)  # Kräfte auf den Klotz längs der Innennormalen
    R = np.linalg.solve(Nm, -np.array([0, 0, -W]))
    assert R == pytest.approx([W * math.cos(a), W * math.sin(a), 0.0], abs=1e-6)
    for k, Rk in zip(nachbarn, R):
        assert r["lagerkraefte"][k] == pytest.approx((-ns[k] * Rk).tolist(), abs=0.01 * W)
    assert r["zwang"]["schraeg"] >= 2
    # nur zwei der drei Flächen: in Richtung Y verschiebbar, nicht gehalten
    teil2 = dict(teil, nachbarn={k: v for k, v in nachbarn.items() if k != "Lager: S"})
    out2, _ = _rechne(tmp_path, teil2, [dict(fall, lager=["Lager: U", "Lager: V"], schluessel="ecke-2")])
    r2 = out2["faelle"][0]
    assert r2["stand"] == "failed" and "verschiebbar in (0,00; 1,00; 0,00)" in r2["meldung"]
    print(f"Ecke schräg: Lagerkräfte {r['lagerkraefte']} (Hand R = {np.round(R, 3).tolist()} N)")


def test_druck_auf_der_ganzen_flaeche_in_der_fem(tmp_path):
    """Würfel 20 mm, unten fest, oben Druck 0,5 N/mm²: Resultierende p · A = 200 N, die das Lager aufnimmt; die
    Lastfläche ist die ganze Oberseite."""
    from build123d import Axis, Box, Location
    from test_festkoerper import _brep, _rechne, _teil

    form = Box(20, 20, 20).moved(Location((0, 0, 10)))
    brep = _brep(form, tmp_path / "w.brep")
    oben = form.faces().sort_by(Axis.Z)[-1]
    nachbarn = {"Lager: B": {"datei": _ebene(tmp_path / "b.npz", (0, 0, 0), (0, 0, -1)), "tol": 0.3}}
    w = {"E": 3500.0, "nu": 0.35, "E_z": None, "f": 50.0, "q": None, "name": "PLA"}
    teil = _teil("Würfel", brep, w, 8000.0, (-10, -10, 0), (10, 10, 20), nachbarn, h_mm=3.0)
    fall = {"id": "0.0", "szenario": "Druck", "teil": "Würfel", "ziel": 2.0, "schluessel": "druck-1",
            "lasten": [{"kraft": [0, 0, -200.0], "moment": None, "punkt": [0, 0, 20],
                        "flaeche": {"index": 5, "flaeche_mm2": 400.0, "druck": 0.5},
                        "flaeche_datei": _flaeche_npz(tmp_path / "oben.npz", oben)}],
            "lager": ["Lager: B"], "feld": [0, 0, 0]}
    out, _ = _rechne(tmp_path, teil, [fall])
    r = out["faelle"][0]
    assert r["stand"] == "done", r
    assert r["kraft_n"] == pytest.approx([0, 0, -200.0], abs=0.01)
    assert r["lagerkraefte"]["Lager: B"] == pytest.approx([0, 0, 200.0], abs=0.5)
    assert r["lastflaechen_mm2"][0] == pytest.approx(400.0, rel=1e-3)
    # gleichmäßiger Druck auf einem Würfel: σ_z = −p im ganzen Teil (ohne Querdehnungsbehinderung oben)
    with np.load(r["feld"]) as z:
        P, U = z["punkte"], z["verschiebung"]
    oben_u = float(U[np.abs(P[:, 2] - 20) < 1e-3, 2].mean())
    assert oben_u < 0
    print(f"Druck: Lagerkraft {r['lagerkraefte']['Lager: B']} N, Senkung oben {oben_u:.5f} mm")
