"""Statik Stufe 2 (PLAN-STATIK.md, T-C): Ablauf mit MuJoCo. Szene aus dem Modell (Körper, Gelenke, Formen), Kippen
gegen die Handrechnung a = g·b/h, Ball im Schieber, Suche nach Grenzen mit Rollouts, CoACD mit Zwischenspeicher,
Protokoll (STATICS mit Ablauf), Laufzeit (Hintergrund nach dem Lauf, dynamik, ANIM_DEF)."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.protocol import check_statics_message, pack_statics, statik_beispiel_ablauf, statik_kurz
from kevcad_kernel.statik.anbindung import LETZTER  # noqa: F401 - Modul laden
from kevcad_kernel.statik.dynamik import ablauf as ab
from kevcad_kernel.statik.dynamik import formen as fm
from kevcad_kernel.statik.dynamik import mjcf, prozess, szene
from kevcad_kernel.statik.dynamik import urteil as ut
from kevcad_kernel.statik.szenario import szenario_aus
from test_statik import laufe

# Wagen auf vier Rädern mit hohem Turm und einem Schieber vorn: Schienen an der Vorderkante, Schieber (Querstab auf
# Höhe der Ballmitte) hinter dem Ball, Fänger (niedriger Querstab, 3,5 mm Luft) davor. Der Ball liegt frei auf dem
# Boden. Ohne Bedingungen: was sich berührt, ist ein Körper; Räder drehen um ihre Zylinderachse (Rad im Namen).
WAGEN = '''
from build123d import *
from kevcad import show
import kevcad.statik as st

r = 50
MAT = "multiplex-birke"
show(Pos(0, 0, 2 * r + 10) * Box(600, 400, 20), "Wagen/Platte", material=MAT)
for i, (x, y) in enumerate([(250, 150), (250, -150), (-250, 150), (-250, -150)], 1):
    show(Pos(x, y, r) * Rot(90, 0, 0) * Cylinder(r, 30), f"Wagen/Rad {i}", material=MAT)
show(Pos(0, 0, 120 + 300) * Box(100, 100, 600), "Wagen/Turm", material=MAT)
for sy, seite in ((1, "links"), (-1, "rechts")):
    show(Pos(450, sy * 128, 110) * Box(300, 20, 20), f"Wagen/Schiene {seite}", material=MAT)
    show(Pos(561, sy * 128, 70) * Box(20, 20, 60), f"Wagen/Pfosten {seite}", material=MAT)
show(Pos(321, 0, 110) * Box(20, 236, 20), "Wagen/Schieber", material=MAT)
show(Pos(561, 0, 25) * Box(20, 276, 30), "Wagen/Fänger", material=MAT)
show(Pos(331 + 108.5 + 0.5, 0, 108.5) * Sphere(108.5), "Ball")
'''


def _szene(tmp_path: Path, code: str = WAGEN) -> tuple[dict, dict]:
    from kevcad_kernel.statik import anbindung

    laufe(tmp_path, code, strikt=False)
    return szene.baue(anbindung.LETZTER, {"run": 1})


@pytest.fixture(scope="module")
def wagen(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wagen")
    meta, felder = _szene(tmp)
    return meta, felder, mjcf.formen_je_teil(meta, felder, {})


# ---------------------------------------------------------------------------------------------------------------------
# Geometrie und Masse


def test_traegheit_quader_aus_brep_und_netz():
    from build123d import Box, Pos

    from kevcad_kernel.pruefung.koerper import koerper_aus_form

    k = koerper_aus_form("Quader", Pos(10, 20, 30) * Box(100, 40, 20))
    m = 2.0
    c, I = szene.traegheit_teil(k, m)
    soll = m / 12 * np.diag([40 ** 2 + 20 ** 2, 100 ** 2 + 20 ** 2, 100 ** 2 + 40 ** 2])
    assert np.allclose(c, [10, 20, 30], atol=1e-6) and np.allclose(I, soll, rtol=1e-6, atol=1e-6)
    c2, I2 = szene._traegheit_netz(k.pos, k.tri, m)
    assert np.allclose(c2, c, atol=1e-3) and np.allclose(I2, soll, rtol=1e-3)
    # Steiner: zwei Quader nebeneinander wie ein langer
    mg, cg, Ig = szene.zusammenfassen([(1.0, np.array([-25.0, 0, 0]), 1 / 12 * np.diag([2, 2500 + 1, 2500 + 1])),
                                       (1.0, np.array([25.0, 0, 0]), 1 / 12 * np.diag([2, 2500 + 1, 2500 + 1]))])
    assert mg == 2 and np.allclose(cg, 0) and Ig[1, 1] == pytest.approx(2 / 12 * (100 ** 2 + 1), rel=1e-3)


def test_kugel_drehteil_und_zylinder():
    from build123d import Cylinder, Pos, Rot, Sphere, Torus

    from kevcad_kernel.pruefung.koerper import koerper_aus_form

    kugel = koerper_aus_form("Ball", Pos(0, 0, 108.5) * Sphere(108.5))
    hv, _ = fm.huelle(kugel.pos)
    c, r = fm.kugel(hv)
    assert r == pytest.approx(108.5, rel=0.003) and np.allclose(c, [0, 0, 108.5], atol=0.5)
    # Laufrolle mit Einschnürung (wie am Kugelschieber): die Hülle wäre in der Mitte 5,8 mm zu dick
    R, l = 217.0, 100.0
    r_ende = 12 + R - math.sqrt(R ** 2 - (l / 2) ** 2)
    rolle = Rot(90, 0, 0) * (Cylinder(r_ende, l) - Torus(12 + R, R) - Cylinder(6.35, l + 2))
    k = koerper_aus_form("Rolle", rolle)
    pr = fm.drehprofil(k.pos, np.zeros(3), np.array([0, 1.0, 0]))
    assert pr is not None
    t, rr = pr
    assert rr.min() == pytest.approx(12.0, abs=0.15) and rr.max() == pytest.approx(r_ende, abs=0.1)
    stuecke = fm.drehteil_stuecke(pr, np.zeros(3), np.array([0, 1.0, 0]))
    assert len(stuecke) >= 4 and all(len(s) == 2 * fm.DREH_SEGMENTE for s in stuecke)
    assert fm.zylinder_aus_profil(pr) is None  # gekrümmt: kein Zylinder
    rad = koerper_aus_form("Rad", Rot(90, 0, 0) * Cylinder(50, 30))
    zy = fm.zylinder_aus_profil(fm.drehprofil(rad.pos, np.zeros(3), np.array([0, 1.0, 0])))
    assert zy is not None and zy[1] == pytest.approx(50, abs=0.05) and zy[2] == pytest.approx(15, abs=0.05)
    # kein Drehteil um eine falsche Achse
    assert fm.drehprofil(rad.pos, np.zeros(3), np.array([1.0, 0, 0])) is None


def test_coacd_zerlegt_mulde_und_merkt_es(tmp_path, monkeypatch):
    from build123d import Box, Pos

    from kevcad_kernel.pruefung.koerper import koerper_aus_form

    monkeypatch.setenv("KEVCAD_DYNAMIK_CACHE", str(tmp_path))
    schale = koerper_aus_form("Schale", Box(120, 60, 40) - Pos(0, 0, 10) * Box(100, 70, 40))
    t0 = time.perf_counter()
    stuecke, info = fm.coacd_zerlegen(schale.pos, schale.tri, schale.form)
    ms = (time.perf_counter() - t0) * 1000
    assert not info["aus_cache"] and len(stuecke) >= 3, info
    assert fm.coacd_im_cache(schale.form)
    stuecke2, info2 = fm.coacd_zerlegen(np.zeros((0, 3)), np.zeros((0, 3)), schale.form)
    assert info2["aus_cache"] and len(stuecke2) == len(stuecke) and info2["ms"] < ms
    # kein Stück füllt die Mulde: Mitte der Mulde liegt in keinem Stück
    mitte = np.array([[0.0, 0.0, 15.0]])
    for s in stuecke:
        _, eb = fm.huelle(s)
        assert fm.abstand_zur_huelle(eb, mitte)[0] > 0


def test_szene_mit_mulde_nimmt_coacd(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_DYNAMIK_CACHE", str(tmp_path / "cache"))
    code = '''
from build123d import *
from kevcad import show
show(Pos(0, 0, 30) * (Box(300, 300, 60) - Pos(0, 0, 10) * Box(260, 260, 60)), "Schale", material="multiplex-birke")
show(Pos(0, 0, 10 + 50 + 1) * Sphere(50), "Kugel")
'''
    meta, felder = _szene(tmp_path, code)
    assert meta["kollision"]["Schale"]["art"] == "coacd" and meta["coacd"] == ["Schale"]
    assert meta["kollision"]["Kugel"]["art"] == "kugel"
    assert "n:Schale" in felder and "t:Schale" in felder  # Netz für CoACD im Ablauf-Prozess
    coacd, info = prozess.coacd_stuecke(meta, felder)
    assert info["gerechnet"] == 1 and len(coacd["Schale"]) >= 3
    formen = mjcf.formen_je_teil(meta, felder, coacd)
    assert len(formen["Schale"]) == len(coacd["Schale"])


# ---------------------------------------------------------------------------------------------------------------------
# Szene des Wagens


def test_szene_wagen_koerper_raeder_ball(wagen):
    meta, _, _ = wagen
    K = {k["id"]: k for k in meta["koerper"]}
    an = K[meta["antrieb"]]
    assert an["art"] == "antrieb" and "Wagen/Platte" in an["teile"] and "Wagen/Fänger" in an["teile"]
    raeder = [k for k in K.values() if k["art"] == "dreh"]
    assert len(raeder) == 4 and all(k["eltern"] == an["id"] and k["gelenk"]["rad"] for k in raeder)
    assert all(abs(k["gelenk"]["achse"][1]) > 0.99 for k in raeder)
    ball = next(k for k in K.values() if k["teile"] == ["Ball"])
    assert ball["art"] == "frei" and ball["eltern"] is None
    assert meta["kollision"]["Ball"]["art"] == "kugel"
    assert all(meta["kollision"][f"Wagen/Rad {i}"].get("zylinder") for i in range(1, 5))
    assert ["Wagen/Fänger", "Ball"] in meta["paare"] or ["Ball", "Wagen/Fänger"] in meta["paare"]
    gesamt = sum(k["masse"] for k in K.values())
    assert gesamt == pytest.approx(meta["masse_gesamt"], rel=1e-9)
    assert all(np.all(np.linalg.eigvalsh(np.asarray(k["traegheit"])) > 0) for k in K.values())


def test_kippen_gegen_handrechnung_und_szenario(wagen):
    meta, _, formen = wagen
    mo = ab.baue_modell(meta, formen)
    hand = ut.handrechnung(meta, mo)
    assert 6 < hand["a_kipp"] < 12  # g · b / h mit b ≈ 250 mm, h ≈ 250 mm
    mo0 = ab.baue_modell(meta, formen, ohne_ladung=True)
    assert not mo0.ladung
    erg, info = ab.grenzen(mo0, lambda x: ab.profil(0.4 * x, x),
                           {"ab": lambda b: b.abheben_max > ab.ABHEBEN_MM}, lo=1.0, hi=40.0)
    a_sim = erg["ab"]["wert"]
    assert a_sim == pytest.approx(hand["a_kipp"], rel=0.05), (a_sim, hand)
    assert info["varianten"] >= 8
    # gemächlich: steht, Ball bleibt; abrupt aus 1 m/s (10 m/s² > a_kipp): hebt ab
    ruhig = ab.rechne(mo, ab.profil(0.3, 1.0))
    assert ruhig.bewertung.abheben_max < ab.ABHEBEN_MM and not ab.ladung_verloren(ruhig.bewertung, mo.ladung[0])
    hart = ab.rechne(mo, ab.profil(1.0, 10.0))
    assert hart.bewertung.abheben_max > 5 and hart.bewertung.kipp_max > 0.5
    # Bilder genau auf k / fps (wie ANIM_DEF), Lagen der Körper als 4 × 4
    assert np.allclose(np.diff(hart.zeiten), 1 / 50, atol=1e-9)
    assert hart.lagen.shape[1:] == (len(hart.koerper), 4, 4)


def test_turm_auf_fuss_ohne_raeder(tmp_path):
    """Kein Rad: der Fuß rutscht über den Boden, die Führung greift am Boden an; Abheben über die Ecken des Fußes."""
    code = '''
from build123d import *
from kevcad import show
show(Pos(0, 0, 9) * Box(200, 120, 18), "Turm/Fuß", material="multiplex-birke")
show(Pos(0, 0, 218) * Box(60, 60, 400), "Turm/Block", material="eiche")
'''
    meta, felder = _szene(tmp_path, code)
    formen = mjcf.formen_je_teil(meta, felder, {})
    mo = ab.baue_modell(meta, formen)
    assert meta["antrieb"] and len(mo.fuss) == 4  # vier Ecken der Aufstandsfläche
    hand = ut.handrechnung(meta, mo)
    assert hand["b_mm"] == pytest.approx(100, abs=0.5)
    mo0 = ab.baue_modell(meta, formen, ohne_ladung=True)
    erg, _ = ab.grenzen(mo0, lambda x: ab.profil(0.4 * x, x), {"ab": lambda b: b.abheben_max > ab.ABHEBEN_MM},
                        lo=0.5, hi=40.0)
    assert erg["ab"]["wert"] == pytest.approx(hand["a_kipp"], rel=0.06), (erg, hand)


def test_ablauf_prozess_urteile_und_suche(wagen, tmp_path):
    meta, felder, _ = wagen
    pfad = str(tmp_path / "szene.npz")
    szene.schreibe(meta, felder, pfad)
    meta2, felder2 = szene.lese(pfad)
    assert meta2 == meta and set(felder2) == set(felder)
    abl, f = prozess.rechne_szenario(meta, mjcf.formen_je_teil(meta, felder, {}),
                                     {"name": "Bremsen aus 1 m/s", "geschwindigkeit": 1.0, "bremsen": "abrupt"})
    assert abl["stand"] == "done" and abl["animation"] == "Ablauf: Bremsen aus 1 m/s"
    arten = {u["art"]: u for u in abl["urteile"]}
    assert arten["dyn_kippen"]["ampel"] == "rot" and "kippt nach vorn" in arten["dyn_kippen"]["text"]
    assert "dyn_ladung" in arten and "dyn_rutschen" in arten
    kz = abl["kennzahlen"]
    assert kz["kippreserve"] < 1 and kz["a_abheben"] < 10
    assert kz["rutschgrenze"] == pytest.approx(kz["mu_rad"] * 9.81, rel=0.01) and kz["mu_rad"] == 0.62  # Holz/Beton
    assert kz["ladung"][0]["name"] == "Ball" and kz["ladung"][0]["v_grenze"] is not None
    assert abl["ms"]["varianten"] >= 24 and abl["bilder"] == len(abl["verlauf"]["zeit"]) == len(abl["pfeile"])
    teile = json.loads(bytes(f["teile"]).decode())
    assert "Wagen/Turm" in teile and "Ball" in teile and f["lagen"].shape == (abl["bilder"], len(teile), 4, 4)
    assert abl["text"].startswith("Bremsen aus 1 m/s: rot – Wagen kippt nach vorn")


def test_ablauf_mit_sollbahn_aus_animation(wagen):
    """Sollbahn wie eine Animation (weich, 1,5 m in 3 s); die Suche spielt sie schneller ab (Beschleunigung × f)."""
    meta, felder, formen = wagen
    t = np.arange(0, 3.0 + 1e-9, 1 / 30)
    u = t / 3.0
    weg = 1.5 * u * u * (3 - 2 * u)
    abl, f = prozess.rechne_szenario(meta, formen, {"name": "Fahrt", "bahn": {"name": "Fahrt", "zeiten": t.tolist(),
                                                                              "weg_m": weg.tolist()}})
    kz = abl["kennzahlen"]
    assert abl["stand"] == "done" and kz["geschwindigkeit"] == pytest.approx(0.75, rel=0.02)
    assert kz["verzoegerung"] == pytest.approx(1.0, rel=0.05)  # 6 · s / T² für die weiche Kurve
    assert kz["abheben_max_mm"] < ab.ABHEBEN_MM and kz["kippreserve"] > 1.5
    assert kz["a_abheben"] is not None and kz["v_abheben"] > 0.75
    assert abl["urteile"][0]["ampel"] == "gruen" and "Wagen kippt nicht" in abl["urteile"][0]["text"]
    assert abl["ms"]["varianten"] >= 8 and f["lagen"].shape[0] == abl["bilder"]


def test_szenario_ablauf_aus_modell_und_agent():
    s = szenario_aus({"name": "Bremsen", "geschwindigkeit": 1, "bremsen": "abrupt"})
    assert s.ablauf["verzoegerung"] == pytest.approx(10.0) and s.dynamisch
    assert np.allclose(s.beschleunigung, [-10, 0, 0])  # S0/S1 mit der größten Verzögerung
    assert s.kurz()["ablauf"]["bremsart"].startswith("abrupt")
    s2 = szenario_aus({"name": "Hang", "ablauf": {"geschwindigkeit": 0.5, "bremsen": 2, "fahrtrichtung": "-y"},
                       "stoss": 2})
    assert np.allclose(s2.beschleunigung, [0, 4, 0]) and s2.ablauf["stoss"] == 2
    with pytest.raises(ValueError):
        szenario_aus({"name": "X", "bremsen": "abrupt"})
    with pytest.raises(ValueError):
        szenario_aus({"name": "X", "geschwindigkeit": 1, "bremsen": "sanft"})
    assert ab.bremszeit("anprall", 1.0)[0] == pytest.approx(50.0)


def test_statics_mit_ablauf():
    b = statik_beispiel_ablauf()
    head = pack_statics(b, run=9)
    assert not check_statics_message(head)
    e = head["szenarien"][2]
    assert e["ablauf"]["animation"] == "Ablauf: Bremsen aus 1 m/s" and len(e["ablauf"]["pfeile"]) == 3
    assert e["urteile"][0]["kurz"].startswith("Rollwagen kippt")
    kurz = statik_kurz(b)["szenarien"][2]["ablauf"]
    assert set(kurz) >= {"stand", "ampel", "text", "animation", "kennzahlen"} and "pfeile" not in kurz
    kaputt = json.loads(json.dumps(head))
    kaputt["szenarien"][2]["ablauf"]["verlauf"]["kipp"].append(1.0)
    assert any("verlauf.kipp" in f for f in check_statics_message(kaputt))
    kaputt["szenarien"][2]["ablauf"]["stand"] = "irgendwas"
    assert any("ablauf.stand" in f for f in check_statics_message(kaputt))


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit: Ablauf aus model.py im Hintergrund, dynamik, ANIM_DEF


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcdy", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_laufzeit_ablauf_aus_modell_und_dynamik(env):
    rt, app = env["rt"], env["app"]
    projekt = env["tmp"] / "Wagen"
    assert rt.project_new(str(projekt), "empty")["ok"]
    code = WAGEN + 'st.szenario("Bremsen aus 1 m/s", geschwindigkeit=1, bremsen="abrupt")\n'
    assert rt.model_write(code)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    _, _, st, _ = app.wait_for(lambda h: h["type"] == "STATICS" and any(
        (e.get("ablauf") or {}).get("stand") == "done" for e in h["szenarien"]), start=start, timeout=120)
    assert not check_statics_message(st)
    e = next(x for x in st["szenarien"] if x["name"] == "Bremsen aus 1 m/s")
    assert e["ampel"] == "rot" and any(u["art"] == "dyn_kippen" for u in e["urteile"])
    _, _, anim, payload = app.wait_for(lambda h: h["type"] == "ANIM_DEF" and h.get("ablauf"), start=start, timeout=10)
    assert anim["name"] == "Ablauf: Bremsen aus 1 m/s" and len(payload) == anim["bilder"] * len(anim["teile"]) * 48
    assert anim["bilder"] == round(anim["dauer"] * anim["fps"]) + 1
    assert "Ablauf: Bremsen aus 1 m/s" in [a.name for a in rt.anim_hub.all()]
    # Auf Anfrage: sanft bremsen, ohne Suche
    start = app.mark()
    d = rt.dynamik("Sanft", geschwindigkeit=0.3, bremsen=1.0, suche=False)
    assert d["ok"], d
    assert d["animation"] == "Ablauf: Sanft" and d["ablauf"]["kennzahlen"]["abheben_max_mm"] < 1
    assert {u["art"] for u in d["szenario"]["urteile"]} >= {"dyn_kippen", "dyn_ladung"}
    _, _, st2, _ = app.wait_for(lambda h: h["type"] == "STATICS" and h.get("aktiv") == "Sanft", start=start,
                                timeout=10)
    assert st2["zeigen"] and any(x["name"] == "Sanft" and x["ablauf"]["stand"] == "done" for x in st2["szenarien"])
    # der Ablauf aus model.py bleibt, auch nach einem weiteren Szenario auf Anfrage
    assert any(x["name"] == "Bremsen aus 1 m/s" and (x.get("ablauf") or {}).get("stand") == "done"
               for x in st2["szenarien"])
    assert rt.szenario_rechnen("Stehen", lasten=[{"teil": "Wagen/Turm", "kg": 1}])["ok"]
    ueb = rt.statik()
    assert {e["name"]: e["ampel"] for e in ueb["szenarien"]}["Bremsen aus 1 m/s"] == "rot"
    assert rt.statik("Bremsen aus 1 m/s")["szenario"]["ablauf"]["stand"] == "done"
    assert not rt.dynamik("Ohne Tempo")["ok"]
    # Nächster Lauf: alte Abläufe verschwinden aus der Zeitleiste
    start = app.mark()
    assert rt.model_write(WAGEN)["ok"]
    assert rt.run()["ok"]
    app.wait_for(lambda h: h["type"] == "ANIM_REMOVE" and h.get("name") == "Ablauf: Sanft", start=start, timeout=30)


# ---------------------------------------------------------------------------------------------------------------------
# MCP mit der Attrappe


def test_mcp_dynamik_und_grenze():
    import anyio
    from mcp_testutil import start_server, with_client

    server, fake = start_server()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        res = call("dynamik", {"name": "Bremsen aus 1 m/s", "geschwindigkeit": 1, "bremsen": "abrupt"})
        assert res.is_error and "erst run" in res.content[0].text
        call("run")
        res = call("dynamik", {"name": "Bremsen aus 1 m/s", "geschwindigkeit": 1, "bremsen": "abrupt"})
        text = res.content[0].text
        assert not res.is_error and text.startswith("Bremsen aus 1 m/s: rot – Rollwagen kippt nach vorn")
        assert "Plausibilität: Handrechnung a = g · b / h" in text and "Abweichung -1,3 %" in text
        assert "Bowlingball: bleibt" in text and "springt ab 1,12 m/s heraus" in text
        assert "Zeitleiste: Animation „Ablauf: Bremsen aus 1 m/s“" in text and "Grenzen:" in text
        assert fake.calls_of("dynamik")[-1][0] == ("Bremsen aus 1 m/s", 1.0, "abrupt")
        res = call("szenario_rechnen", {"name": "Bremsen", "dynamik": True, "geschwindigkeit": 0.5, "bremsen": 3})
        assert not res.is_error and fake.calls_of("dynamik")[-1][0] == ("Bremsen", 0.5, 3)
        res = call("dynamik_grenze", {"ohne": "beides"})
        text = res.content[0].text
        assert "Bowlingball: bleibt bis 1,12 m/s im Schieber" in text and "hebt bei dieser Bremsart ab 0,29 m/s" in text
    finally:
        server.stop_thread()
