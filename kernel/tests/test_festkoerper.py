"""Statik Stufe 3 (PLAN-STATIK.md, T-D): Festkörper-FEM. Steifigkeit gegen scikit-fem, Kragbalken gegen die
Handrechnung, Lochplatte gegen den Kerbfaktor, Druckteil quer zur Schicht (Wandhalter) gegen Handrechnung und
Kragträger S0, Lager eines Stabs, Zwischenspeicher, Protokoll (STATICS mit Festkörper, STATICS_FIELD), Laufzeit
(Hintergrund nach dem Lauf, festigkeit, Abbruch) und MCP.

Gmsh läuft nur im FEM-Prozess (eigener Prozess, wie in Kev CAD); der Testprozess lädt build123d und OCP und schreibt
nur die Formen."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.catalog import Catalog, builtin_dir
from kevcad_kernel.protocol import (
    check_statics_feld,
    check_statics_message,
    pack_statics,
    pack_statics_feld,
    statik_beispiel_feld,
    statik_beispiel_festkoerper,
    statik_kurz,
    unpack_statics_feld,
)
from kevcad_kernel.statik.festkoerper import kontakt
from kevcad_kernel.statik.festkoerper import urteil as fu
from kevcad_kernel.statik.festkoerper import werkstoff as fw
from test_statik import HALTER, laufe

PROZESS = [sys.executable, "-m", "kevcad_kernel.statik.festkoerper.prozess"]


def mechanik(mid: str) -> dict:
    """Werkstoffwerte aus dem mitgelieferten Katalog (nicht fest eintragen: der Katalog darf sich ändern)."""
    return Catalog(builtin=builtin_dir(), own=Path(tempfile.mkdtemp())).material(mid)["mechanik"]


@pytest.fixture(autouse=True)
def eigener_speicher(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_FESTKOERPER_CACHE", str(tmp_path / "fem-cache"))


def _brep(form, pfad: Path) -> str:
    from OCP.BRepTools import BRepTools

    BRepTools.Write_s(form.wrapped, str(pfad))
    return str(pfad)


def _wand(pfad: Path, x: float, groesse: float = 1000.0) -> str:
    """Nachbarnetz „Wand“: Quadrat in der Ebene x = const."""
    g = groesse
    pos = np.array([[x, -g, -g], [x, g, -g], [x, g, g], [x, -g, g]], dtype=float)
    np.savez(pfad, pos=pos, tri=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64))
    return str(pfad)


def _rechne(tmp: Path, teil: dict, faelle: list[dict], fein: bool = False) -> tuple[dict, float]:
    auftrag = {"version": 1, "fein": fein, "teile": [{**teil, "faelle": faelle}]}
    a = tmp / "auftrag.json"
    a.write_text(json.dumps(auftrag), encoding="utf-8")
    t0 = time.perf_counter()
    r = subprocess.run(PROZESS + [str(a), str(tmp / "ergebnis.json")], capture_output=True, text=True, timeout=600)
    dauer = time.perf_counter() - t0
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads((tmp / "ergebnis.json").read_text())
    return out, dauer


def _felder(pfad: str) -> dict:
    with np.load(pfad) as z:
        return {k: z[k] for k in z.files if k != "info"}


def _teil(name: str, brep: str, w: dict, volumen: float, bmin, bmax, nachbarn: dict, **kw) -> dict:
    return {"id": 0, "name": name, "brep": brep, "schluessel_teil": name + str(kw.get("h_mm")), "volumen": volumen,
            "masse_kg": 0.0, "werkstoff": w, "druckteil": False, "schicht": None, "ausrichtungen": {},
            "bmin": list(bmin), "bmax": list(bmax), "nachbarn": nachbarn, **kw}


# ---------------------------------------------------------------------------------------------------------------------
# Bausteine


def test_steifigkeit_gleich_scikit_fem():
    """Der eigene P2-Kern baut dieselbe Matrix wie skfem.asm(linear_elasticity)."""
    from skfem import MeshTet, asm
    from skfem.models.elasticity import lame_parameters, linear_elasticity

    from kevcad_kernel.statik.festkoerper import loeser

    m = MeshTet.init_tensor(np.linspace(0, 30, 4), np.linspace(0, 10, 3), np.linspace(0, 8, 3))
    N = loeser.Netz(m.p.T, m.t.T)
    E, nu = 2580.0, 0.36
    K = N.steifigkeit(fw.steifigkeit(E, nu))
    K0 = asm(linear_elasticity(*lame_parameters(E, nu)), N.basis)
    assert abs(K - K0).max() < 1e-9 * abs(K0).max()
    # transversal isotrop mit E_z = E ist isotrop; gedreht bleibt die Matrix symmetrisch positiv
    assert np.allclose(fw.steifigkeit(E, nu, E, np.array([0, 1.0, 0])), fw.steifigkeit(E, nu))
    C = fw.steifigkeit(E, nu, 0.8 * E, np.array([1.0, 1.0, 0]) / math.sqrt(2))
    assert np.allclose(C, C.T) and np.all(np.linalg.eigvalsh(C) > 0)
    # Volumenlast konsistent: Summe = b · V
    f = N.last_volumen(np.array([0, 0, -2.0]))
    assert sum(f[N.basis.nodal_dofs[2]]) + sum(f[N.basis.edge_dofs[2]]) == pytest.approx(-2.0 * 30 * 10 * 8)


def test_kontakt_punkt_dreieck_gegen_abtastung():
    rng = np.random.default_rng(3)
    T = rng.normal(size=(40, 3, 3)) * 5
    P = rng.normal(size=(40, 3)) * 6
    d = kontakt.punkt_dreieck(P, T[:, 0], T[:, 1], T[:, 2])
    u, v = np.meshgrid(np.linspace(0, 1, 120), np.linspace(0, 1, 120))
    m = (u + v) <= 1
    u, v = u[m], v[m]
    for i in range(len(P)):
        Q = T[i, 0] + u[:, None] * (T[i, 1] - T[i, 0]) + v[:, None] * (T[i, 2] - T[i, 0])
        assert d[i] <= np.linalg.norm(Q - P[i], axis=1).min() + 1e-9
        assert d[i] >= np.linalg.norm(Q - P[i], axis=1).min() - 0.15
    pos = T.reshape(-1, 3)
    tri = np.arange(len(pos)).reshape(-1, 3)
    a = kontakt.abstand(P, pos, tri, tol=1e9)
    assert np.allclose(a, [d_.min() for d_ in [kontakt.punkt_dreieck(np.repeat(P[i:i + 1], 40, 0), T[:, 0], T[:, 1],
                                                                       T[:, 2]) for i in range(len(P))]])


def test_schichtkriterium():
    """Einachsiger Zug quer zur Schicht: Index σ / (q f); in der Schicht: von Mises."""
    s = np.array([[0, 0, 10.0, 0, 0, 0]])
    i_m, i_s = fw.index(s, 40.0, 0.5, np.array([0, 0, 1.0]))
    assert i_m[0] == pytest.approx(0.25) and i_s[0] == pytest.approx(0.5)
    i_m, i_s = fw.index(s, 40.0, 0.5, np.array([1.0, 0, 0]))
    assert i_s[0] == pytest.approx(0.0)
    tau = np.array([[0, 0, 0, 0, 5.0, 0]])  # Schub in der Fuge xz bei Normale z
    _, i_s = fw.index(tau, 40.0, 0.5, np.array([0, 0, 1.0]))
    assert i_s[0] == pytest.approx(math.sqrt(3) * 5 / 20)


# ---------------------------------------------------------------------------------------------------------------------
# Plausibilität gegen Handrechnung


def test_kragbalken_gegen_handrechnung(tmp_path):
    """Kragbalken 100 × 10 × 10 mm aus PLA (Werte aus dem Katalog), an der Wand eingespannt, 100 N am Ende:
    Durchbiegung F L³ / (3 E I), Biegespannung M / W, je höchstens 5 % Abweichung (feines Netz)."""
    from build123d import Box, Location

    me = mechanik("pla")
    E, nu = float(me["e_modul"]), float(me.get("querkontraktion") or 0.3)
    L, b, h, F = 100.0, 10.0, 10.0, 100.0
    brep = _brep(Box(L, b, h).moved(Location((L / 2, 0, h / 2))), tmp_path / "balken.brep")
    w = {"E": E, "nu": nu, "E_z": None, "f": float(me["zugfestigkeit"]), "q": None, "name": "PLA"}
    teil = _teil("Balken", brep, w, L * b * h, (0, -5, 0), (100, 5, 10),
                 {"Wand": {"datei": _wand(tmp_path / "wand.npz", 0.0), "tol": 0.3}}, h_mm=2.5)
    fall = {"id": "0.0", "szenario": "Last", "teil": "Balken", "ziel": 2.0, "schluessel": "balken-1",
            "lasten": [{"kraft": [0, 0, -F], "moment": None, "punkt": [L, 0, h / 2]}], "lager": ["Wand"],
            "feld": [0, 0, 0]}
    out, dauer = _rechne(tmp_path, teil, [fall])
    r = out["faelle"][0]
    assert r["stand"] == "done", r
    I = b * h ** 3 / 12
    W = b * h ** 2 / 6
    f_hand = F * L ** 3 / (3 * E * I)
    assert r["verformung_max_mm"] == pytest.approx(f_hand, rel=0.05)
    assert r["gleichgewicht_n"] < 1e-6 and r["kraft_n"] == pytest.approx([0, 0, -F])
    # Randfaser bei x = 25 (M = F · 75) und an der Einspannung (gewertet ab dem ersten Knoten neben der Wand)
    fd = _felder(r["feld"])
    p, sv = fd["punkte"], fd["spannung"]
    oben = (np.abs(p[:, 2] - h) < 1e-3) & (np.abs(p[:, 0] - 25) < 2.6)
    sigma_25 = float(np.mean(sv[oben]))
    assert sigma_25 == pytest.approx(F * 75 / W, rel=0.05)
    sigma_ort = F * (L - r["ort"][0]) / W
    assert r["spannung_max"] == pytest.approx(sigma_ort, rel=0.05)
    assert r["spannung_max"] == pytest.approx(F * L / W, rel=0.05)
    assert r["sicherheit"] == pytest.approx(w["f"] / r["spannung_ort"], rel=1e-3)
    assert dauer < 30
    print(f"Kragbalken: f FEM {r['verformung_max_mm']:.3f} / Hand {f_hand:.3f} mm, σ(25) {sigma_25:.2f} / "
          f"{F * 75 / W:.2f}, σmax {r['spannung_max']:.2f} / {F * L / W:.2f} N/mm², {r['netz']}, {dauer:.1f} s")


def test_lochplatte_gegen_kerbfaktor(tmp_path):
    """Platte 400 × 100 × 5 mm mit Loch Ø 20 unter Zug: größte Spannung am Lochrand gegen K_t σ_netto mit
    K_t = 2 + (1 − d/W)³ (Heywood), höchstens 5 % Abweichung."""
    from build123d import Box, Cylinder, Location

    W_, d, t, F = 100.0, 20.0, 5.0, 1000.0
    form = Box(400, W_, t).moved(Location((0, 0, t / 2))) - Cylinder(d / 2, t).moved(Location((0, 0, t / 2)))
    brep = _brep(form, tmp_path / "platte.brep")
    w = {"E": 70000.0, "nu": 0.3, "E_z": None, "f": 160.0, "q": None, "name": "Alu"}
    teil = _teil("Platte", brep, w, 400 * W_ * t - math.pi * 100 * t, (-200, -50, 0), (200, 50, 5),
                 {"Wand": {"datei": _wand(tmp_path / "wand.npz", -200.0), "tol": 0.3}}, h_mm=4.0)
    fall = {"id": "0.0", "szenario": "Zug", "teil": "Platte", "ziel": 2.0, "schluessel": "platte-1",
            "lasten": [{"kraft": [F, 0, 0], "moment": None, "punkt": [200, 0, t / 2]}], "lager": ["Wand"],
            "feld": [0, 0, 0]}
    out, dauer = _rechne(tmp_path, teil, [fall], fein=True)
    r = out["faelle"][0]
    assert r["stand"] == "done", r
    kt = 2 + (1 - d / W_) ** 3
    soll = kt * F / ((W_ - d) * t)
    fd = _felder(r["feld"])
    am_loch = np.abs(np.linalg.norm(fd["punkte"][:, :2], axis=1) - d / 2) < 0.05
    assert float(fd["spannung"][am_loch].max()) == pytest.approx(soll, rel=0.05)
    assert r["spannung_max"] == pytest.approx(soll, rel=0.05)
    assert abs(np.linalg.norm(r["ort"][:2]) - d / 2) < 0.1  # die größte Spannung sitzt am Lochrand
    print(f"Lochplatte: σmax {r['spannung_max']:.3f} / K_t σ_netto {soll:.3f} N/mm² "
          f"({100 * (r['spannung_max'] / soll - 1):+.1f} %), {r['netz']}, {r['loeser']}, {dauer:.1f} s")


# ---------------------------------------------------------------------------------------------------------------------
# Abbruch eines laufenden FEM-Prozesses


def test_abbruch_beendet_den_prozess(tmp_path):
    """Die Laufzeit beendet den FEM-Prozess (neuer Lauf, STATICS_CANCEL, festigkeit(abbrechen=True)): Abgebrochen,
    binnen Sekunden, ohne Ergebnis."""
    import threading

    from build123d import Box, Cylinder, Location

    from kevcad_kernel.statik.festkoerper.laufzeit import Abgebrochen, FestkoerperRuntime

    form = Box(400, 100, 5).moved(Location((0, 0, 2.5))) - Cylinder(10, 5).moved(Location((0, 0, 2.5)))
    brep = _brep(form, tmp_path / "platte.brep")
    w = {"E": 70000.0, "nu": 0.3, "E_z": None, "f": 160.0, "q": None, "name": "Alu"}
    teil = _teil("Platte", brep, w, 199000.0, (-200, -50, 0), (200, 50, 5),
                 {"Wand": {"datei": _wand(tmp_path / "wand.npz", -200.0), "tol": 0.3}}, h_mm=3.0)
    fall = {"id": "0.0", "szenario": "Zug", "teil": "Platte", "ziel": 2.0, "schluessel": "abbruch-1",
            "lasten": [{"kraft": [1000.0, 0, 0], "moment": None, "punkt": [200, 0, 2.5]}], "lager": ["Wand"],
            "feld": [0, 0, 0]}
    (tmp_path / "auftrag.json").write_text(json.dumps({"version": 1, "fein": True, "teile": [{**teil,
                                                                                          "faelle": [fall]}]}))
    rt = FestkoerperRuntime()
    gesehen = threading.Event()
    fehler: list[BaseException] = []

    def lauf() -> None:
        try:
            rt._fk_prozess({"ordner": str(tmp_path), "auftrag": str(tmp_path / "auftrag.json")},
                           lambda x, t: gesehen.set(), timeout_s=120)
        except BaseException as exc:  # noqa: BLE001
            fehler.append(exc)

    t = threading.Thread(target=lauf)
    t.start()
    assert gesehen.wait(60)
    t0 = time.perf_counter()
    assert rt._fk_abbrechen_intern()
    t.join(30)
    assert not t.is_alive() and time.perf_counter() - t0 < 10
    assert fehler and isinstance(fehler[0], Abgebrochen)
    assert not (tmp_path / "ergebnis.json").exists()


# ---------------------------------------------------------------------------------------------------------------------
# Aus dem Modell: Druckteil quer zur Schicht, Lager eines Stabs, Zwischenspeicher


def _auftrag_und_prozess(tmp: Path, wunsch: dict) -> tuple[dict, dict, float]:
    from kevcad_kernel.statik import anbindung
    from kevcad_kernel.statik.festkoerper import auftrag

    a = auftrag.schreibe(anbindung.LETZTER, wunsch)
    t0 = time.perf_counter()
    r = subprocess.run(PROZESS + [a["auftrag"], str(tmp / "erg.json")], capture_output=True, text=True, timeout=600)
    dauer = time.perf_counter() - t0
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads((tmp / "erg.json").read_text())
    shutil.rmtree(a["ordner"], ignore_errors=True)
    return a, out, dauer


def test_wandhalter_quer_zur_schicht_mit_fem_beleg(tmp_path):
    """Gedruckter Wandhalter (PETG) 80 × 20 × 8 mm, 20 N am Ende, stehend gedruckt (Schichten quer zur Last):
    rot mit „drehen“ als FEM-Beleg; Sicherheit gegen die Handrechnung q f / (M / W) und den Kragträger S0."""
    _, check, _ = laufe(tmp_path, HALTER.replace("AUSRICHTUNG", '"-x"'))
    e = next(e for e in check["statik"]["szenarien"] if e["name"] == "Haken 2 kg")
    b = next(b for b in e["bauteile"] if b["teil"] == "Wandhalter (Druck)")
    assert b["nachbarn"] == ["Kulisse/Wand"] and b["punkt_gegeben"] and b["kraft"] == [0, 0, -20]
    a, out, dauer = _auftrag_und_prozess(tmp_path, {"auto": True})
    assert [f["teil"] for f in a["faelle"]] == ["Wandhalter (Druck)"]
    r = out["faelle"][0]
    assert r["stand"] == "done", r
    me = mechanik("petg")
    q, f = float(me["quer_zur_schicht"]), float(me["zugfestigkeit"])
    F, hebel, W = 20.0, 78.0, 20 * 8 ** 2 / 6
    s_hand = q * f / (F * hebel / W)
    assert r["kriterium"] == "schicht" and r["q"] == q
    assert r["sicherheit"] == pytest.approx(s_hand, rel=0.08)
    assert r["sicherheit"] == pytest.approx(b["sicherheit"], rel=0.15)  # Kragträger S0 rechnet ähnlich
    # Steifigkeit quer zur Schicht aus e_modul_z: Durchbiegung mit E_z
    I = 20 * 8 ** 3 / 12
    f_hand = F * hebel ** 2 * (3 * 80 - hebel) / (6 * float(me["e_modul_z"]) * I)  # Spitze, Last bei 78 von 80 mm
    assert r["verformung_max_mm"] == pytest.approx(f_hand, rel=0.1)
    t = fu.teil_kurz(r)
    assert t["ampel"] == "rot" and t["ausrichtung_beste"] in ("-z", "-y")
    assert t["ausrichtungen"][t["ausrichtung_beste"]] > 4.0  # flach gedruckt: grün
    u = fu.urteil_fuer(t)
    assert u["art"] == "festkoerper" and u["quer_zur_schicht"] and u["loesung"].startswith("Drehen:")
    assert "(FEM, gleiche Last)" in u["loesung"]
    assert dauer < 20
    # gleicher Auftrag noch einmal: alles aus dem Zwischenspeicher
    a2, out2, dauer2 = _auftrag_und_prozess(tmp_path, {"auto": True})
    assert out2["faelle"][0]["aus_speicher"] and out2["faelle"][0]["sicherheit"] == r["sicherheit"]
    assert a2["faelle"][0]["schluessel"] == a["faelle"][0]["schluessel"] and dauer2 < 5
    print(f"Wandhalter: FEM {r['sicherheit']:.2f}, Hand {s_hand:.2f}, S0 {b['sicherheit']:.2f}, gedreht "
          f"{t['ausrichtungen']}, {r['netz']}, {dauer:.1f} s, Speicher {dauer2:.1f} s")


STANGE = '''
from build123d import *
from kevcad import lager, show, befestigt
from kevcad.bedingungen import verbinde
import kevcad.statik as st

show(Pos(-5, 0, 100) * Box(10, 600, 200), "Kulisse/Wand", kulisse=True)
for sy, seite in ((1, "links"), (-1, "rechts")):
    n = f"Halter {seite} (Druck)"
    form = Pos(20, sy * 200, 100) * Box(40, 30, 40) - Pos(25, sy * 200, 100) * Rot(90, 0, 0) * Cylinder(10.65, 30)
    show(lager.druckteil(form, n, material="petg", ausrichtung="-z"), n, material="petg")
    befestigt(n, grund="an die Wand geschraubt")
rohr = lager.teil("rohr-en10220-21.3x2.0")
show(Pos(25, 0, 100) * Rot(90, 0, 0) * rohr.verbauen(laenge=500, name="Stange"), "Stange")
verbinde("Stange", "Halter links (Druck)", art="steck")
verbinde("Stange", "Halter rechts (Druck)", art="steck")
st.szenario("Kleiderstange 20 kg")
st.last("Stange", kg=20)
'''


def test_lager_eines_stabs_ueber_die_kontaktflaeche(tmp_path):
    """Stange (Stahlrohr) in zwei gedruckten Haltern: Die Lagerkräfte des Stabwerks gehen über die Bohrung in den
    Halter, das Lager ist die Wand. Summe der Lasten = Lagerkraft aus S1."""
    _, check, _ = laufe(tmp_path, STANGE, strikt=False)
    e = next(e for e in check["statik"]["szenarien"] if e["name"] == "Kleiderstange 20 kg")
    lager = [a for a in e["auflager"] if "Halter" in (a.get("teil") or "")]
    assert lager, e["auflager"]
    a, out, _ = _auftrag_und_prozess(tmp_path, {"auto": True})
    faelle = {f["teil"]: f for f in out["faelle"]}
    assert set(faelle) == {"Halter links (Druck)", "Halter rechts (Druck)"}
    for n, r in faelle.items():
        assert r["stand"] == "done", r
        assert r["lager"] == ["Kulisse/Wand"] and r["lasten"][0]["kontakt_mit"] == "Stange"
        soll = -np.sum([a_["kraft"] for a_ in lager if a_["teil"] == n], axis=0)
        assert np.allclose(np.asarray(r["kraft_n"]) - np.asarray(r["eigengewicht_n"]), soll, atol=1e-3)
        assert r["lastflaechen_mm2"][0] > 100 and r["lagerflaeche_mm2"] > 1000
        assert r["sicherheit"] > 4


ECKE = '''
from build123d import *
from kevcad import lager, show, befestigt
from kevcad.bedingungen import verbinde
import kevcad.statik as st

rohr = lager.teil("rohr-en10220-21.3x2.0")
show(rohr.verbauen(laenge=500, name="Pfosten"), "Pfosten")
befestigt("Pfosten", grund="an der Wand verschraubt")
form = (Pos(0, 0, 505) * Box(40, 40, 70) - Pos(0, 0, 485) * Cylinder(10.65, 30)
        - Pos(5, 0, 520) * Rot(0, 90, 0) * Cylinder(10.65, 30))
show(lager.druckteil(form, "Eckverbinder (Druck)", material="petg", ausrichtung="-z"), "Eckverbinder (Druck)",
     material="petg")
show(Pos(-10, 0, 520) * Rot(0, 90, 0) * rohr.verbauen(laenge=300, name="Arm"), "Arm")
verbinde("Pfosten", "Eckverbinder (Druck)", art="steck")
verbinde("Arm", "Eckverbinder (Druck)", art="steck")
st.szenario("Last am Arm")
st.last("Arm", kraft=(0, 0, -50), punkt=(285, 0, 520))
'''


def test_verbinder_zwischen_staeben(tmp_path):
    """Gedruckter Eckverbinder zwischen Pfosten und Arm (im Stabwerk starr): Kraft und Moment des Arms aus S1 gehen
    über die Bohrung in den Verbinder, gehalten vom Pfosten (stärkster Stab); Gleichgewicht der Verbinderkräfte mit dem
    Gewicht des Verbinders."""
    _, check, _ = laufe(tmp_path, ECKE, strikt=False)
    e = next(e for e in check["statik"]["szenarien"] if e["name"] == "Last am Arm")
    v = {x["stab"]: x for x in e.get("verbinder") or [] if x["teil"] == "Eckverbinder (Druck)"}
    assert set(v) == {"Pfosten", "Arm"}, e.get("verbinder")
    from kevcad_kernel.statik import anbindung

    t = anbindung.LETZTER.modell.teile["Eckverbinder (Druck)"]
    g = np.array([0, 0, -9.81]) * t.masse_kg
    summe = np.sum([x["kraft"] for x in v.values()], axis=0)
    assert np.allclose(summe + g, 0, atol=0.05)  # Starrkörper im Gleichgewicht
    arm = anbindung.LETZTER.modell.teile["Arm"]
    assert v["Arm"]["kraft"][2] == pytest.approx(-(50 + arm.masse_kg * 9.81), rel=0.01)
    a, out, _ = _auftrag_und_prozess(tmp_path, {"auto": True})
    r = next(f for f in out["faelle"] if f["teil"] == "Eckverbinder (Druck)")
    assert r["stand"] == "done", r
    assert r["lager"] == ["Pfosten"] and r["lager_aus_last"] == "Pfosten"
    assert [l["kontakt_mit"] for l in r["lasten"]] == ["Arm"] and r["lastflaechen_mm2"][0] > 300
    assert r["gleichgewicht_n"] < 1e-6 and r["sicherheit"] > 0
    print(f"Eckverbinder: Sicherheit {r['sicherheit']}, {r['kriterium']}, Last {r['kraft_n']} N, "
          f"Moment {v['Arm']['moment']} Nmm, {r['netz']}")


def test_kontaktkraefte_aus_dem_ablauf_in_der_ruhelage():
    """Kontaktkräfte eines Ablaufs (S2): Bild mit der größten Summe, alle Kontakte des Teils in diesem Bild, Punkt und
    Kraft über die Lage des Teils im Bild zurück in die Ruhelage (der Wagen ist schon gefahren); Mehrteil-Körper und
    Boden zählen nicht als Teil."""
    from types import SimpleNamespace

    from kevcad_kernel.statik.festkoerper.laufzeit import FestkoerperRuntime

    def lage(dx: float, drehung: bool = False) -> np.ndarray:
        M = np.eye(4)
        if drehung:  # 90° um z
            M[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        M[0, 3] = dx
        return M

    pfeile = [
        [{"punkt": [310.0, 0, 20], "kraft": [-30.0, 0, 0], "paar": ["Rolle", "Ball"]}],
        [{"punkt": [400.0, 0, 20], "kraft": [-80.0, 0, -10], "paar": ["Ball", "Rolle"]},
         {"punkt": [401.0, 0, 0], "kraft": [0.0, 0, 40], "paar": ["Boden", "Rolle"]},
         {"punkt": [0.0, 0, 0], "kraft": [0.0, 0, 500], "paar": ["Boden", "Wagen (12 Teile)"]}],
    ]
    anim = SimpleNamespace(teile=["Rolle"], matrices=np.stack([lage(300.0)[None], lage(390.0, True)[None]]))
    rt = FestkoerperRuntime()
    rt.anim_hub = SimpleNamespace(get=lambda n: anim if n == "Ablauf: Bremsen" else None)
    voll = {"szenarien": [{"name": "Bremsen", "ablauf": {"stand": "done", "animation": "Ablauf: Bremsen",
                                                          "pfeile": pfeile}}]}
    alle, _ = rt._fk_ablauf_lasten(voll, None, "Bremsen")
    assert {l["teil"] for l in alle} == {"Rolle", "Ball"}  # einzelne Teile, nicht der Wagen und nicht der Boden
    lasten, hinweise = rt._fk_ablauf_lasten(voll, "Rolle", "Bremsen")
    assert not hinweise and {l["teil"] for l in lasten} == {"Rolle"}
    assert [l["bild"] for l in lasten] == [1, 1]  # Bild 1: 81 + 40 N
    ball = next(l for l in lasten if l["kontakt_mit"] == "Ball")
    boden = next(l for l in lasten if l["kontakt_mit"] is None)
    # Ruhelage: Punkt = Rᵀ (p − t), Kraft = Rᵀ F (90° um z zurückgedreht)
    assert np.allclose(ball["punkt"], [0, -10, 20]) and np.allclose(ball["kraft"], [0, 80, -10])
    assert np.allclose(boden["punkt"], [0, -11, 0]) and np.allclose(boden["kraft"], [0, 0, 40])


# ---------------------------------------------------------------------------------------------------------------------
# Protokoll und Urteile


def test_statics_mit_festkoerper_und_feld():
    b = statik_beispiel_festkoerper()
    head = pack_statics(b, run=3)
    assert not check_statics_message(head)
    sz = next(e for e in head["szenarien"] if e["name"] == "Haken 2 kg")
    assert sz["festkoerper"]["teile"][0]["feld"] == "d0f84561664942f7ae15"
    kurz = statik_kurz(b)
    k = next(e for e in kurz["szenarien"] if e["name"] == "Haken 2 kg")
    assert k["festkoerper"]["teile"] == [{"teil": "Wandhalter (Druck)", "stand": "done", "ampel": "rot",
                                          "sicherheit": 1.87}]
    kaputt = pack_statics({**b, "szenarien": [dict(sz, festkoerper={"stand": "kaputt"})]}, run=3)
    assert any("festkoerper.stand" in f for f in check_statics_message(kaputt))
    kopf, felder = statik_beispiel_feld()
    h, payload = pack_statics_feld(kopf, felder, run=3)
    assert not check_statics_feld(h, payload) and h["punkte"] == 8 and h["dreiecke"] == 12
    zurueck = unpack_statics_feld(h, payload)
    assert np.allclose(zurueck["verschiebung"], felder["verschiebung"])
    assert check_statics_feld({**h, "punkte": 7}, payload)


def test_einbauen_ersetzt_kragtraeger():
    e = {"name": "Haken 2 kg", "ampel": "rot", "kennzahlen": {"sicherheit": 1.98},
         "urteile": [{"art": "bauteil", "teil": "H", "ampel": "rot", "text": "H hält nicht", "sicherheit": 1.98}],
         "teile": [{"name": "H", "ausnutzung": 2.02, "ampel": "rot", "sicherheit": 1.98}]}
    r = {"stand": "done", "teil": "H", "sicherheit": 5.2, "ziel": 4.0, "spannung_max": 3.0, "kriterium": "mises",
         "ort": [1, 2, 3], "verformung_max_mm": 0.4, "q": 0.4, "ausrichtungen": {"-z": 5.2}, "s0": {"sicherheit": 1.98},
         "schluessel": "abc", "netz": {}, "ms": {"teil": 900.0}}
    t = fu.teil_kurz(r)
    neu = fu.einbauen(e, {"stand": "done", "teile": [t]})
    assert neu["ampel"] == "gruen" and not [u for u in neu["urteile"] if u["art"] == "bauteil"]
    assert neu["teile"][0]["sicherheit"] == 5.2 and neu["teile"][0]["fem"]
    assert neu["kennzahlen"]["sicherheit"] == 5.2 and neu["festkoerper"]["teile"][0]["feld"] == "abc"


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit: Hintergrund nach dem Lauf, festigkeit, STATICS_FIELD, Abbruch


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcfk", dir=tempfile.gettempdir()))
    os.environ["KEVCAD_FESTKOERPER_CACHE"] = str(tmp / "fem-cache")
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _projekt_mit_petg(rt, pfad: Path) -> None:
    assert rt.project_new(str(pfad), "empty")["ok"]
    mats = []
    for mid in ("petg",):
        m = Catalog(builtin=builtin_dir(), own=Path(tempfile.mkdtemp())).material(mid)
        mats.append({k: v for k, v in m.items() if k not in ("ebene", "status")})
    (pfad / "katalog.json").write_text(json.dumps({"version": 1, "materialien": mats}), encoding="utf-8")


def test_laufzeit_hintergrund_festigkeit_und_feld(env):
    rt, app = env["rt"], env["app"]
    _projekt_mit_petg(rt, env["tmp"] / "Halter")
    assert rt.model_write(HALTER.replace("AUSRICHTUNG", '"-x"'))["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    # erst „läuft“, dann gerechnet: STATICS mit Festkörper und ein STATICS_FIELD
    _, _, st, _ = app.wait_for(lambda h: h["type"] == "STATICS" and any(
        (e.get("festkoerper") or {}).get("stand") == "laeuft" for e in h["szenarien"]), start=start, timeout=60)
    assert not check_statics_message(st)
    _, _, fertig, _ = app.wait_for(lambda h: h["type"] == "STATICS" and any(
        (e.get("festkoerper") or {}).get("stand") == "done" for e in h["szenarien"]), start=start, timeout=120)
    assert not check_statics_message(fertig)
    e = next(e for e in fertig["szenarien"] if e["name"] == "Haken 2 kg")
    t = e["festkoerper"]["teile"][0]
    assert t["ampel"] == "rot" and t["kriterium"] == "schicht" and e["ampel"] == "rot"
    assert any(u["art"] == "festkoerper" for u in e["urteile"])
    assert not any(u["art"] == "bauteil" and u["teil"] == "Wandhalter (Druck)" for u in e["urteile"])
    _, _, fh, payload = app.wait_for(lambda h: h["type"] == "STATICS_FIELD", start=start, timeout=30)
    assert not check_statics_feld(fh, payload) and fh["feld"] == t["feld"] and fh["teil"] == "Wandhalter (Druck)"
    assert fh["ueberhoehung"] >= 1 and fh["run"] == res["run"]
    # festigkeit (MCP): aus dem Zwischenspeicher, schnell, mit Text und Befund
    t0 = time.perf_counter()
    f = rt.festigkeit("Wandhalter (Druck)", "Haken 2 kg")
    assert f["ok"], f
    assert time.perf_counter() - t0 < 10
    assert f["teile"][0]["aus_speicher"] and f["teile"][0]["ampel"] == "rot"
    assert any(b["art"] == "statik_festkoerper" for b in f["befunde"])
    from kevcad_kernel.statik.bericht import festkoerper_text

    text = festkoerper_text(f)
    assert "hält nicht (Festkörper-FEM)" in text and "Drehen:" in text and "Grenzen:" in text
    detail = rt.statik("Haken 2 kg")
    assert detail["szenario"]["festkoerper"]["stand"] == "done"
    assert not rt.festigkeit("Wandhalter (Druck)", "Hakn 2 kg")["ok"]
    # Abbruch: nichts läuft
    assert rt.festigkeit_abbrechen()["ok"]


def test_mcp_festigkeit():
    import anyio
    from mcp_testutil import start_server, with_client

    server, fake = start_server()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        res = call("festigkeit", {"teil": "Wandhalter (Druck)"})
        assert res.is_error and "erst run" in res.content[0].text
        call("run")
        res = call("festigkeit", {"teil": "Wandhalter (Druck)", "szenario": "Haken 2 kg"})
        text = res.content[0].text
        assert not res.is_error and text.startswith("[rot] Wandhalter (Druck) hält nicht"), text
        assert "Sicherheit je Drucklage" in text and "Grenzen:" in text
        assert fake.calls_of("festigkeit")[-1][0] == ("Wandhalter (Druck)", "Haken 2 kg", False, False)
        res = call("festigkeit", {"abbrechen": True})
        assert not res.is_error and "keine Festkörper-Rechnung" in res.content[0].text
    finally:
        server.stop_thread()
