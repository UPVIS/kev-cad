"""Topologieoptimierung (PLAN-TOPOLOGIE.md): Bausteine gegen Handrechnung bzw. direkte Lösung, klassische Formen
(Kragträger, MBB-Balken), Überhang- und Dichtefilter mit Ableitungen, Oberfläche, Bohrungen, Prozess am Winkelhalter,
model.py anpassen, Protokoll, Laufzeit mit model.py und MCP.

Gmsh läuft nur im Topo-Prozess bzw. in ``rechne`` (eigener Testprozess für die langen Fälle)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.catalog import Catalog, builtin_dir
from kevcad_kernel.protocol import (
    check_topo_app,
    check_topo_feld,
    check_topo_message,
    pack_topo,
    pack_topo_feld,
    topo_beispiel,
    topo_beispiel_feld,
    unpack_topo_feld,
)
from kevcad_kernel.statik.festkoerper.werkstoff import steifigkeit
from kevcad_kernel.topologie import einstellungen, modell_schluessel
from kevcad_kernel.topologie import oberflaeche as ob
from kevcad_kernel.topologie import raster
from kevcad_kernel.topologie.mehrgitter import Mehrgitter, hex8_ke
from kevcad_kernel.topologie.simp import Dichtefilter, Optimierer, Ueberhangfilter

KE1 = hex8_ke(steifigkeit(1.0, 0.3))


@pytest.fixture(autouse=True)
def eigener_speicher(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_TOPOLOGIE_CACHE", str(tmp_path / "topo-cache"))
    monkeypatch.setenv("KEVCAD_FESTKOERPER_CACHE", str(tmp_path / "fem-cache"))


# -- Mehrgitter ------------------------------------------------------------------------------------------------------


def test_hex8_starrkoerper_und_symmetrie():
    w = np.linalg.eigvalsh(KE1)
    assert np.abs(KE1 - KE1.T).max() < 1e-14
    assert np.sum(np.abs(w) < 1e-10) == 6 and w.min() > -1e-10  # sechs Starrkörperbewegungen, sonst positiv


def _direkt(mg: Mehrgitter, F: np.ndarray) -> np.ndarray:
    """Vergleich: assemblierte Matrix der feinsten Ebene, feste Freiheitsgrade gestrichen, direkt gelöst."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    e0 = mg.ebenen[0]
    n = int(np.prod(e0.nn))
    K = mg.s0.reshape(-1)[mg.akt0][:, None, None] * mg.KE[None]
    dof = (mg.enode0[:, :, None] * 3 + np.arange(3)[None, None, :]).reshape(len(mg.akt0), 24)
    A = sp.coo_matrix((K.reshape(-1), (np.repeat(dof, 24, 1).reshape(-1), np.tile(dof, (1, 24)).reshape(-1))),
                      shape=(3 * n, 3 * n)).tocsr()
    frei = np.flatnonzero(np.transpose(e0.frei.reshape(3, n)).reshape(-1))
    b = np.transpose(F.reshape(3, n)).reshape(-1)
    x = np.zeros(3 * n)
    x[frei] = spla.spsolve(A[frei][:, frei].tocsc(), b[frei])
    return np.transpose(x.reshape(n, 3)).reshape(F.shape)


@pytest.mark.parametrize("muster", ["voll", "simp"])
def test_mehrgitter_wie_direkt(muster):
    nx, ny, nz = 16, 8, 8
    aktiv = np.ones((nx, ny, nz), dtype=bool)
    aktiv[6:10, 2:6, 3:5] = False  # Loch im Bauraum
    fest = np.zeros((3, nx + 1, ny + 1, nz + 1), dtype=bool)
    fest[:, 0] = True
    mg = Mehrgitter(KE1, 1.5, aktiv, fest, grob_max=600)
    assert mg.stufen >= 2
    s = np.ones((nx, ny, nz)) if muster == "voll" else 1e-6 + np.random.default_rng(1).random((nx, ny, nz)) ** 3
    mg.setze(np.where(aktiv, s, 0.0))
    F = np.zeros((3, nx + 1, ny + 1, nz + 1))
    F[2, nx, :, nz // 2] = -1.0
    U, info = mg.loese(F, tol=1e-9, maxiter=500)
    Ud = _direkt(mg, F)
    assert info["iterationen"] < (40 if muster == "voll" else 120), info
    # die feinste Ebene rechnet ihre Produkte einfach genau: Abweichung etwa 1e-4 (für die Empfindlichkeiten genug)
    assert np.linalg.norm(U - Ud) / np.linalg.norm(Ud) < 2e-3


# -- Filter ----------------------------------------------------------------------------------------------------------


def test_dichtefilter_ist_selbstadjungiert():
    rng = np.random.default_rng(2)
    aktiv = rng.random((9, 7, 6)) > 0.2
    f = Dichtefilter(aktiv, 2.2)
    x, y = rng.random(aktiv.shape), rng.random(aktiv.shape)
    assert abs(np.vdot(f.vor(x), y) - np.vdot(x, f.rueck(y))) < 1e-10
    assert np.allclose(f.vor(np.where(aktiv, 0.37, 0.0))[aktiv], 0.37)  # konstante Dichte bleibt


def test_ueberhangfilter_stuetzt_und_ableitung():
    aktiv = np.ones((5, 4, 6), dtype=bool)
    am = Ueberhangfilter(aktiv)
    xt = np.zeros(aktiv.shape)
    xt[:, :, 0] = 1.0  # Bett
    xt[2, 2, 1:] = 1.0  # senkrechte Säule: gestützt
    xt[4, 0, 4] = 1.0  # schwebendes Element: nicht gestützt
    xh = am.vor(xt)
    assert xh[2, 2, 5] > 0.95 and xh[4, 0, 4] < 0.05
    # 45°: je Schicht ein Element weiter (Kreuz) bleibt gestützt
    xt2 = np.zeros(aktiv.shape)
    xt2[:, :, 0] = 1.0
    for k in range(1, 5):
        xt2[k - 1, 1, k] = 1.0
    assert am.vor(xt2)[3, 1, 4] > 0.95
    # Ableitung gegen Differenzenquotient
    rng = np.random.default_rng(3)
    x = 0.2 + 0.6 * rng.random(aktiv.shape)
    g = rng.random(aktiv.shape)
    am.vor(x)
    d = am.rueck(g)
    i = (2, 1, 3)
    e = 1e-6
    xp, xm = x.copy(), x.copy()
    xp[i] += e
    xm[i] -= e
    fd = (np.vdot(g, am.vor(xp)) - np.vdot(g, am.vor(xm))) / (2 * e)
    assert abs(fd - d[i]) < 1e-5 * max(1.0, abs(fd))


# -- klassische Formen -----------------------------------------------------------------------------------------------


def test_kragtraeger_fachwerk_und_volumen():
    """Kragträger 48 × 12 × 16, links eingespannt, rechts mittig belastet: Ober- und Untergurt an der Einspannung,
    dazwischen leer (Fachwerk statt Vollwand), Volumen genau 30 %."""
    nx, ny, nz = 48, 12, 16
    aktiv = np.ones((nx, ny, nz), dtype=bool)
    fest = np.zeros((3, nx + 1, ny + 1, nz + 1), dtype=bool)
    fest[:, 0] = True
    F = np.zeros((3, nx + 1, ny + 1, nz + 1))
    F[2, nx, :, nz // 2] = -1.0 / (ny + 1)
    opt = Optimierer(aktiv, np.zeros_like(aktiv), KE1, 1.0, 1.0, fest, [F], 0.3, 1.8)
    r = opt.lauf(max_iter=50, min_iter=20)
    xh = opt.xh
    assert abs(r["volumen"] - 0.3) < 0.005, r
    c = [v["c"] for v in opt.verlauf]
    assert c[-1] < 0.25 * c[0]
    seite = xh.mean(axis=1)  # über die Breite gemittelt (x, z)
    assert seite[1, -1] > 0.6 and seite[1, 0] > 0.6  # Ober- und Untergurt an der Einspannung
    assert seite[1, nz // 2] < 0.3  # Mitte der Einspannung leer
    assert seite[nx // 4, nz // 2] < 0.3  # Steg im ersten Feld leer (Fachwerk)


def test_mbb_balken():
    """Halber MBB-Balken (Symmetrie links, Auflager rechts unten, Last links oben): Druckgurt oben, Zuggurt unten,
    Diagonalen dazwischen."""
    nx, ny, nz = 60, 2, 20
    aktiv = np.ones((nx, ny, nz), dtype=bool)
    fest = np.zeros((3, nx + 1, ny + 1, nz + 1), dtype=bool)
    fest[0, 0, :, :] = True  # Symmetrie: x fest an x = 0
    fest[2, nx, :, 0] = True  # Rollenlager rechts unten
    fest[1] = True  # eben (keine Verschiebung quer)
    F = np.zeros((3, nx + 1, ny + 1, nz + 1))
    F[2, 0, :, nz] = -1.0
    opt = Optimierer(aktiv, np.zeros_like(aktiv), KE1, 1.0, 1.0, fest, [F], 0.5, 1.5)
    r = opt.lauf(max_iter=60, min_iter=25)
    xh = opt.xh[:, 0, :]
    assert abs(r["volumen"] - 0.5) < 0.005
    assert xh[: 2 * nx // 3, -1].mean() > 0.9 and xh[-3:, -1].mean() < 0.2  # Obergurt von der Last bis etwa 3/4
    assert xh[nx // 2:, 0].mean() > 0.6  # Untergurt zum Lager hin
    innen = xh[5:nx - 5, 5:nz - 5]
    assert ((innen > 0.2) & (innen < 0.8)).mean() < 0.35 and (innen < 0.2).mean() > 0.2  # Löcher zwischen Stäben


# -- Oberfläche und Raster -------------------------------------------------------------------------------------------


def test_marching_cubes_geschlossen():
    x = np.linspace(-1.2, 1.2, 33)
    X, Y, Z = np.meshgrid(x, x, x, indexing="ij")
    p, d = ob.marching_cubes(np.sqrt(X ** 2 + Y ** 2 + Z ** 2) - 1.0, x[1] - x[0], (-1.2,) * 3)
    assert ob.offene_kanten(d) == 0
    assert abs(ob.volumen(p, d) / (4 / 3 * np.pi) - 1) < 0.01
    rng = np.random.default_rng(4)
    g = rng.standard_normal((14, 14, 14))
    g[[0, -1]] = 1
    g[:, [0, -1]] = 1
    g[:, :, [0, -1]] = 1
    p, d = ob.marching_cubes(g)
    assert ob.offene_kanten(d) == 0 and ob.volumen(p, d) > 0  # auch mehrdeutige Fälle geschlossen und außen


def test_netzkoerper_als_brep_weich_und_ohne_netzkanten():
    """Körper aus dem Netz (B-Rep mit Dreiecksflächen): gültig, Volumen wie das Netz; im Viewer weich schattiert und
    nur mit scharfen Kanten (die Kanten zwischen fast ebenen Nachbarn bleiben leer, ihre Nummern bleiben)."""
    from build123d import Shape

    from kevcad_kernel.tessellate import tessellate_shape
    from kevcad_kernel.topologie.ergebnis import solid_aus_netz

    x = np.linspace(-1.3, 1.3, 30) * 20
    X, Y, Z = np.meshgrid(x, x, x, indexing="ij")
    p, d = ob.marching_cubes(np.sqrt(X ** 2 + Y ** 2 + Z ** 2) - 20.0, x[1] - x[0], (x[0],) * 3)
    s = Shape.cast(solid_aus_netz(p, d))
    assert s.is_valid and abs(s.volume - ob.volumen(p, d)) < 1e-6 * abs(ob.volumen(p, d))
    g = tessellate_shape(s, cache=None).geometry
    assert len(g.edge_offsets) - 1 == len(s.edges())
    assert (np.diff(g.edge_offsets) > 0).sum() < 0.05 * len(s.edges())  # Kugel: keine scharfen Kanten
    n = g.normals / np.linalg.norm(g.normals, axis=1, keepdims=True)
    r = g.positions / np.linalg.norm(g.positions, axis=1, keepdims=True)
    assert np.mean(np.einsum("ij,ij->i", n, r)) > 0.999  # weich: Normale fast radial, nicht je Dreieck


def test_innen_und_bohrungen():
    from build123d import Align, Box, Cylinder, Pos, Rot

    teil = Box(60, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    teil -= Pos(-20, 0, 0) * Cylinder(3, 30)
    teil -= Pos(20, 0, 0) * Cylinder(2, 30)
    teil -= Pos(0, 0, 5) * Rot(0, 90, 0) * Cylinder(1.5, 80)
    teil = teil.fillet(1.0, teil.edges().filter_by(lambda e: abs(e.center().Z - 10) < 1e-6 and e.length > 30))
    P, T, F = raster.brep_netz(teil.wrapped)
    xs, ys, zs = np.linspace(-29, 29, 30), np.linspace(-19, 19, 20), np.linspace(0.5, 9.5, 10)
    innen = raster.innen_gitter(P, T, xs, ys, zs)
    assert abs(innen.mean() - 1.0) < 0.12 and not innen[np.argmin(abs(xs + 20)), np.argmin(abs(ys)), 5]
    b = raster.bohrungen(teil.wrapped)
    durch = sorted(round(2 * x.radius, 2) for x in b)
    assert durch == [3.0, 4.0, 6.0]  # Rundungen (90°) zählen nicht
    quer = next(x for x in b if abs(x.radius - 1.5) < 1e-6)
    assert abs(abs(quer.achse[0]) - 1) < 1e-9 and abs(quer.t1 - quer.t0 - 60) < 1e-6


# -- Prozess am Winkelhalter ------------------------------------------------------------------------------------------


def _winkelhalter(ordner: Path, last=(0, 15, 50), einst=None) -> dict:
    """Auftrag wie im Reel: Grundplatte mit vier Schraubenlöchern (Lager: Schrauben), Steg mit Bolzenloch (Last)."""
    from build123d import Align, Box, Cylinder, Pos, Rot
    from OCP.BRepTools import BRepTools

    basis = Box(80, 50, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
    steg = Pos(0, -20, 0) * Box(40, 10, 60, align=(Align.CENTER, Align.CENTER, Align.MIN))
    teil = basis + steg
    schrauben = None
    for x in (-30, 30):
        for y in (-15, 15):
            teil -= Pos(x, y, 0) * Cylinder(2.75, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
            s = Pos(x, y, -5) * Cylinder(2.75, 18, align=(Align.CENTER, Align.CENTER, Align.MIN))
            schrauben = s if schrauben is None else schrauben + s
    teil -= Pos(0, -20, 48) * Rot(90, 0, 0) * Cylinder(6, 40)
    brep = ordner / "teil.brep"
    BRepTools.Write_s(teil.wrapped, str(brep))
    P, T, _ = raster.brep_netz(schrauben.wrapped)
    np.savez(ordner / "nachbar.npz", pos=P, tri=T)
    w = {"id": "petg", "name": "PETG", "E": 2000.0, "nu": 0.38, "E_z": 1700.0, "f": 45.0, "q": 0.6}
    return {"version": 1, "teil": "Halter", "form": None, "brep": str(brep), "lage": np.eye(4).tolist(),
            "oben": [0.0, 0.0, 1.0], "volumen": float(teil.volume), "masse_kg": float(teil.volume) * 1.27e-6,
            "werkstoff": w, "material_id": "petg", "bmin": [-40, -25, 0], "bmax": [40, 25, 60],
            "nachbarn": {"Schrauben": {"datei": str(ordner / "nachbar.npz"), "tol": 0.3, "schluessel": "s"}},
            "klemmen": [], "schutz": [],
            "faelle": [{"szenario": "Bolzen 50 N", "ziel": 4.0, "lager": ["Schrauben"],
                        "lasten": [{"kraft": list(last), "moment": None, "punkt": [0, -20, 48], "quelle": "Bolzen"}],
                        "feld": [0, 0, -9.81]}],
            "einstellungen": einst or {"behalten": 0.42}, "lastfall": "t", "schluessel": "t-halter", "hinweise": []}


@pytest.mark.timeout(900)
def test_prozess_winkelhalter(tmp_path, monkeypatch):
    """Ende zu Ende ohne Laufzeit (kleines Gitter): Volumen −55 % bis −60 %, Schutzzonen an den Bohrungen, Körper
    geschlossen und als B-Rep lesbar, vorher und nachher gerechnet, Lastfläche auf dem Bolzenloch gleich groß."""
    monkeypatch.setenv("KEVCAD_TOPOLOGIE_VOXEL", "25000")
    from kevcad_kernel.topologie.ergebnis import lies_brep
    from kevcad_kernel.topologie.prozess import rechne, speicher

    A = _winkelhalter(tmp_path)
    t0 = time.perf_counter()
    e = rechne(A, speicher())
    dauer = time.perf_counter() - t0
    kz = e["kennzahlen"]
    assert 55 <= kz["ersparnis"]["volumen_prozent"] <= 61, kz["ersparnis"]
    assert sum(1 for z in e["schutz"]["zonen"] if z["art"] == "Bohrung") == 5  # vier Schraubenlöcher und der Bolzen
    assert e["netz"]["offen"] == 0 and e["netz"]["dreiecke"] <= 12_000
    assert e["netz"]["bohrungen_geschnitten"] == 5  # Bohrungen genau nachgeschnitten (Zylinderflächen)
    from build123d import Shape

    s = Shape.cast(lies_brep(e["dateien"]["brep"]))
    assert abs(s.volume - kz["nachher"]["volumen_mm3"]) < 0.01 * kz["nachher"]["volumen_mm3"]
    from build123d import GeomType

    zyl = [f for f in s.faces() if f.geom_type == GeomType.CYLINDER]
    assert sorted({round(f.radius, 2) for f in zyl}) == [2.75, 6.0]
    v, n = e["faelle"]["vorher"][0], e["faelle"]["nachher"][0]
    assert v["sicherheit"] and n["sicherheit"]
    assert abs(n["lastflaechen_mm2"][0] / v["lastflaechen_mm2"][0] - 1) < 0.35  # gleiche Lastfläche (Bolzenloch)
    assert kz["nachher"]["filament_g"] < kz["vorher"]["filament_g"]
    assert e["optimierung"]["iterationen"] >= 20 and dauer < 400


# -- model.py anpassen ------------------------------------------------------------------------------------------------


def test_einfuegen_hinter_dem_druckteil():
    from kevcad_kernel.topologie.laufzeit import einfuegen

    code = ("from build123d import *\nfrom kevcad import lager, show\n\nform = Box(10, 10, 10)\n"
            "halter = lager.druckteil(form, \"Halter\",\n                         material=\"petg\")\n"
            "show(halter, \"Halter\")\n")
    st = {"teil": "Halter", "szenario": "Bolzen 50 N", "einstellungen": einstellungen(behalten=0.42, ueberhang=True)}
    neu, zeile = einfuegen(code, st)
    assert neu is not None, zeile
    assert "from kevcad import topologie\n" in neu
    zeilen = neu.splitlines()
    i = zeilen.index('                         material="petg")')
    assert zeilen[i + 1].startswith("halter = topologie.optimieren(halter, szenario='Bolzen 50 N', behalten=0.42, "
                                    "ueberhang=True)")
    compile(neu, "model.py", "exec")
    assert einfuegen(code.replace('"Halter"', '"Anderes"'), st)[0] is None


def test_schluessel_gleich_fuer_gleiche_wuensche():
    a = modell_schluessel("f1", "Halter", "S", einstellungen(behalten=0.4))
    assert a == modell_schluessel("f1", "Halter", "S", {"behalten": 0.40000001, "steg": 6.0})
    assert a != modell_schluessel("f1", "Halter", "S", einstellungen(behalten=0.5))
    assert a != modell_schluessel("f2", "Halter", "S", {})


# -- Protokoll -------------------------------------------------------------------------------------------------------


def test_protokoll_topo():
    for s in ("done", "laeuft"):
        assert not check_topo_message(pack_topo(topo_beispiel(s), run=3))
    kaputt = pack_topo({**topo_beispiel("done"), "ergebnis": None}, run=3)
    assert check_topo_message(kaputt)
    for art in ("nachher", "dichte", "schutz"):
        k, f = topo_beispiel_feld(art)
        h, p = pack_topo_feld(k, f)
        assert not check_topo_feld(h, p)
        u = unpack_topo_feld(h, p)
        assert np.allclose(u["punkte"], f["punkte"])
    assert not check_topo_app({"type": "TOPO_START", "behalten": 0.4}) and check_topo_app({"type": "TOPO_X"})
    with pytest.raises(ValueError):
        pack_topo_feld({"art": "unbekannt"}, topo_beispiel_feld("dichte")[1])


# -- Laufzeit mit model.py --------------------------------------------------------------------------------------------

MODELL = '''
from build123d import *
from kevcad import lager, show, befestigt, topologie
import kevcad.statik as st

show(Pos(0, 0, -5) * Box(120, 90, 10), "Kulisse/Platte", kulisse=True)
for i, (x, y) in enumerate([(-30, -15), (30, -15), (-30, 15), (30, 15)]):
    show(Pos(x, y, -2) * Cylinder(2.75, 14, align=(Align.CENTER, Align.CENTER, Align.MIN)), f"Kulisse/Schraube {i + 1}",
         kulisse=True)
basis = Box(80, 50, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
steg = Pos(0, -20, 0) * Box(40, 10, 60, align=(Align.CENTER, Align.CENTER, Align.MIN))
form = basis + steg
for x in (-30, 30):
    for y in (-15, 15):
        form = form - Pos(x, y, 0) * Cylinder(2.75, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
form = form - Pos(0, -20, 48) * Rot(90, 0, 0) * Cylinder(6, 40)
halter = lager.druckteil(form, "Halter", material="petg", ausrichtung="-z", zweck="tragend")
halter = topologie.optimieren(halter, szenario="Bolzen 50 N", behalten=0.42)
show(halter, "Halter")
befestigt("Halter", grund="mit vier Schrauben auf die Platte geschraubt")
st.szenario("Bolzen 50 N")
st.last("Halter", kraft=(0, 15, 50), punkt=(0, -20, 48))
'''


@pytest.mark.timeout(900)
def test_laufzeit_modell_hintergrund_und_neuer_lauf(monkeypatch):
    """model.py ruft topologie.optimieren: der erste Lauf zeigt das Ausgangsteil und meldet die Rechnung im Hintergrund,
    TOPO läuft mit Dichte (TOPO_FIELD), danach liegt das Ergebnis im Projekt und der Lauf startet neu mit dem
    optimierten Körper (kleineres Volumen, Druckteil in der Stückliste)."""
    monkeypatch.setenv("KEVCAD_TOPOLOGIE_VOXEL", "15000")
    tmp = Path(tempfile.mkdtemp(prefix="kctp", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, run_timeout_s=240)
    try:
        assert rt.wait_worker_ready(240)
        app = FakeApp(sock)
        app.wait_for(lambda h: h["type"] == "HELLO")
        pfad = tmp / "Halter"
        assert rt.project_new(str(pfad), "empty")["ok"]
        m = Catalog(builtin=builtin_dir(), own=Path(tempfile.mkdtemp())).material("petg")
        (pfad / "katalog.json").write_text(json.dumps({"version": 1, "materialien": [
            {k: v for k, v in m.items() if k not in ("ebene", "status")}]}), encoding="utf-8")
        assert rt.model_write(MODELL)["ok"]
        start = app.mark()
        res = rt.run(timeout_s=240)
        assert res["ok"], res
        assert any("im Hintergrund optimiert" in w for w in res.get("warnings") or [])
        vol0 = next(p["volume"] for p in rt.parts() if p["name"] == "Halter")
        _, _, fd, pl = app.wait_for(lambda h: h["type"] == "TOPO_FIELD" and h["art"] == "dichte", start=start,
                                    timeout=300)
        assert not check_topo_feld(fd, pl)
        _, _, fertig, _ = app.wait_for(lambda h: h["type"] == "TOPO" and h["stand"] in ("done", "failed"),
                                       start=start, timeout=600)
        assert fertig["stand"] == "done", fertig.get("meldung")
        assert not check_topo_message(fertig)
        assert (pfad / fertig["ergebnis"]["datei"]).exists()
        arten = {h["art"] for h in app.since(start) if h["type"] == "TOPO_FIELD"}
        assert {"dichte", "koerper", "vorher", "nachher"} <= arten
        _, _, ende, _ = app.wait_for(lambda h: h["type"] == "RUN_END" and h.get("run", 0) > res["run"], start=start,
                                     timeout=300)
        vol1 = next(p["volume"] for p in rt.parts() if p["name"] == "Halter")
        assert 0.35 < vol1 / vol0 < 0.5, (vol0, vol1)
        erg = rt.topologie_ergebnis()
        assert erg["ok"] and erg["ergebnis"]["im_modell"] and "Näherung" in erg["text"]
        assert rt.topologie_abbrechen()["ok"]
        app.close()
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_mcp_topologie():
    import anyio
    from mcp_testutil import start_server, with_client

    server, fake = start_server()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        res = call("topologie_optimieren", {"teil": "Halter"})
        assert res.is_error and "erst run" in res.content[0].text
        call("run")
        res = call("topologie_optimieren", {"teil": "Halter", "behalten": 0.42})
        assert not res.is_error and "Hintergrund" in res.content[0].text
        res = call("topologie_ergebnis", {"warten_s": 1})
        assert not res.is_error and "Volumen −58 %" in res.content[0].text
        res = call("topologie_optimieren", {"abbrechen": True})
        assert not res.is_error and "keine Topologieoptimierung" in res.content[0].text
        res = call("topologie_uebernehmen", {})
        assert not res.is_error and "Variante" in res.content[0].text
    finally:
        server.stop_thread()
