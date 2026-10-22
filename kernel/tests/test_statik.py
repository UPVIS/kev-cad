"""Statik Stufe 1 (PLAN-STATIK.md, T-A und T-B): Materialdaten, Querschnitte, S1 gegen geschlossene Lösungen, S0
(Kippen, Rutschen), Bauteil quer zur Schicht, überdimensioniert, Szenario-API, Protokoll STATICS, MCP und Laufzeit."""

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

from kevcad_kernel.catalog import Catalog, builtin_dir, validate_material
from kevcad_kernel.protocol import check_statics_message, pack_statics, statik_beispiel, statik_kurz
from kevcad_kernel.runner import Runner
from kevcad_kernel.statik import dienst
from kevcad_kernel.statik.bericht import lauf_zeile, statik_text
from kevcad_kernel.statik.modell import Anschluss, Stab, StatikModell, Teil
from kevcad_kernel.statik.stabwerk import rechne
from kevcad_kernel.statik.szenario import Last, Szenario, aus_modell
from kevcad_kernel.statik.werkstoff import Werkstoff, querschnitt, werkstoff

TISCH = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

L, B, H = 800, 500, 700
rohr = lager.teil("vierkantrohr-en10219-40x40x3")
for sx in (1, -1):
    for sy in (1, -1):
        n = f"Tisch/Bein {'vorn' if sy < 0 else 'hinten'} {'rechts' if sx > 0 else 'links'}"
        show(Pos(sx * (L / 2 - 20), sy * (B / 2 - 20), 0) * rohr.verbauen(laenge=H, name=n), n)
for sy, seite in ((-1, "vorn"), (1, "hinten")):
    n = f"Tisch/Zarge {seite}"
    show(Pos(-(L / 2 - 40), sy * (B / 2 - 20), H - 20) * Rot(0, 90, 0) * rohr.verbauen(laenge=L - 80, name=n), n)
for sx, seite in ((-1, "links"), (1, "rechts")):
    n = f"Tisch/Zarge {seite}"
    show(Pos(sx * (L / 2 - 20), -(B / 2 - 40), H - 20) * Rot(-90, 0, 0) * rohr.verbauen(laenge=B - 80, name=n), n)
st.szenario("Last 20 kg", beschreibung="20 kg auf den Längszargen")
st.last(["Tisch/Zarge vorn", "Tisch/Zarge hinten"], kg=20)
'''

HALTER = '''
from build123d import *
from kevcad import lager, show, befestigt
import kevcad.statik as st

show(Pos(-5, 0, 100) * Box(10, 200, 200), "Kulisse/Wand", kulisse=True)
arm = Pos(40, 0, 100) * Box(80, 20, 8)
show(lager.druckteil(arm, "Wandhalter (Druck)", material="petg", ausrichtung=AUSRICHTUNG), "Wandhalter (Druck)",
     material="petg")
befestigt("Wandhalter (Druck)", grund="an die Wand geschraubt")
st.szenario("Haken 2 kg")
st.last("Wandhalter (Druck)", kraft=(0, 0, -20), punkt=(78, 0, 100))
'''

TURM = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

show(Pos(0, 0, 9) * Box(100, 100, 18), "Turm/Fuß", material="multiplex-birke")
show(Pos(0, 0, 218) * Box(60, 60, 400), "Turm/Block", material="eiche")
st.szenario("Anstoßen", beschleunigung=(-6, 0, 0))
'''


def laufe(tmp_path: Path, code: str, run: int = 1, strikt: bool = True):
    (tmp_path / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": strikt}))
    (tmp_path / "model.py").write_text(code, encoding="utf-8")
    runner = Runner(lambda h, p=b"": None)
    res = runner.run({"run": run, "path": str(tmp_path / "model.py"), "code": code, "params": {},
                      "inventar_regel": strikt,
                      "catalog": {"builtin": str(builtin_dir()), "own": str(tmp_path / "eigen")}})
    assert res["type"] == "RUN_DONE", res.get("error")
    check, _ = runner.pruefe(run)
    assert check["state"] in ("done", "teilweise"), check
    return res, check, runner


def szenario(check: dict, name: str) -> dict:
    return next(e for e in check["statik"]["szenarien"] if e["name"] == name)


# ---------------------------------------------------------------------------------------------------------------------
# Katalog: Mechanik und Reibwerte (T6)


def test_katalog_mechanik_und_reibwerte(tmp_path):
    c = Catalog(own=tmp_path)
    assert not c.warnings
    w = werkstoff(c, "stahl-s235")
    assert (w.E, w.streckgrenze, w.zug) == (210000, 235, 360) and "10025" in w.quelle
    petg = werkstoff(c, "petg")
    assert petg.quer == 0.4 and petg.grenze == 34 and "PETG HF" in petg.quelle and "querkontraktion" in petg.geschaetzt
    holz = werkstoff(c, "fichte-tanne")
    assert holz.holz and holz.grenze == 24 and "C24" in holz.annahme
    # Reibwerte je Paarung, über Gruppen und Reibgruppen
    assert c.reibwert("gummi", "beton")["haft"] == 0.6
    assert c.reibwert("edelstahl", "stahl")["paarung"] == ["Stahl", "Stahl"]
    assert c.reibwert("petg", "alu")["geschaetzt"] is True
    # Prüfung der Mechanikdaten
    m = dict(c.material("stahl-s235"), mechanik={"e_modul": -1, "quelle": ""})
    fehler = validate_material(m)
    assert any("e_modul" in f for f in fehler) and any("quelle" in f for f in fehler)


def test_querschnitte_geschlossen():
    q = querschnitt("rohr", {"d": 12, "s": 1.0})
    assert q.A == pytest.approx(math.pi / 4 * (144 - 100), rel=1e-6)
    assert q.I_lang == pytest.approx(math.pi / 64 * (12 ** 4 - 10 ** 4), rel=1e-6) and q.isotrop
    r = querschnitt("holz", {"b": 60, "h": 40})
    assert (r.I_lang, r.I_quer) == (pytest.approx(40 * 60 ** 3 / 12), pytest.approx(60 * 40 ** 3 / 12))
    n = querschnitt("nutprofil", {"raster": 40, "nut": 8})
    assert 60000 < n.I_lang < 100000  # 40 × 40 leicht: Herstellerwerte um 7 bis 8 cm⁴


# ---------------------------------------------------------------------------------------------------------------------
# S1 gegen geschlossene Lösungen


ALU = Werkstoff("alu-6060", "Alu", "Aluminium", 2.7, 70000, 27000, 0.3, 160, 215)


def _modell(L: float = 1000.0, lager=(("fest", 0.0),), richtung=(1, 0, 0)) -> StatikModell:
    q = querschnitt("rohr", {"d": 12, "s": 1.0})
    m = StatikModell()
    d = np.array(richtung, float)
    m.staebe["Rohr"] = Stab("Rohr", "x", "rohr", {"d": 12, "s": 1.0}, ALU, q, np.zeros(3), d * L,
                            np.array([0, 1.0, 0]) if d[2] == 0 else np.array([1.0, 0, 0]), 1e-9)
    m.teile["Rohr"] = Teil("Rohr", 1e-9, d * L / 2, np.zeros(3), d * L)
    for art, t in lager:
        m.anschluesse.append(Anschluss("Rohr", t, art, ("boden",), np.array(d), ("Rohr", "Boden"), "test"))
    return m


def test_s1_kragarm_einfeld_knicken():
    I = querschnitt("rohr", {"d": 12, "s": 1.0}).I_lang
    W = querschnitt("rohr", {"d": 12, "s": 1.0}).W_lang
    e = rechne(_modell(), [Szenario("L", lasten=[Last(["Rohr"], np.array([0, 0, -100.0]), np.array([1000.0, 0, 0]))])])
    r = e["L"].staebe["Rohr"]
    assert r.durchbiegung == pytest.approx(100 * 1000 ** 3 / (3 * 70000 * I), rel=1e-4)
    assert r.spannung_max == pytest.approx(100 * 1000 / W, rel=1e-4)
    assert r.grenze_durchbiegung == pytest.approx(10.0)  # Kragarm: 2 · Länge / 200
    e = rechne(_modell(lager=(("gelenkig", 0.0), ("gelenkig", 1000.0))),
               [Szenario("L", lasten=[Last(["Rohr"], np.array([0, 0, -100.0]), np.array([500.0, 0, 0]))])])
    r = e["L"].staebe["Rohr"]
    assert r.durchbiegung == pytest.approx(100 * 1000 ** 3 / (48 * 70000 * I), rel=1e-4)
    assert r.spannung_max == pytest.approx(100 * 1000 / 4 / W, rel=1e-4)
    # Kragstütze: Pk = π² E I / (2 L)²
    e = rechne(_modell(L=500, richtung=(0, 0, 1)),
               [Szenario("D", lasten=[Last(["Rohr"], np.array([0, 0, -10.0]), np.array([0, 0, 500.0]))])])
    assert e["D"].knicken == pytest.approx(math.pi ** 2 * 70000 * I / (4 * 500 ** 2) / 10, rel=1e-3)
    assert e["D"].knick_stab == "Rohr"


def test_s1_mechanismus_wird_gemeldet_und_s0_rechnet_einfache_traeger():
    from kevcad_kernel.statik import s0
    from kevcad_kernel.statik.bewertung import bewerte

    m = _modell(lager=(("gelenkig", 0.0),))  # nur ein Gelenk: beweglich
    sz = Szenario("L", lasten=[Last(["Rohr"], np.array([0, 0, -10.0]), np.array([1000.0, 0, 0]))])
    e = rechne(m, [sz])
    assert not e["L"].ok and "beweglich" in e["L"].meldung
    t = s0.traeger(m, sz)[0]  # Ersatz: Kragarm über die ganze Länge
    W = querschnitt("rohr", {"d": 12, "s": 1.0}).W_lang
    assert t["moment_nmm"] == pytest.approx(10 * 1000, rel=1e-3) and t["spannung"] == pytest.approx(10000 / W, rel=1e-3)
    urteil = bewerte(sz, {"traeger": [t]}, e["L"], [], m)
    assert urteil["kennzahlen"]["sicherheit"] == pytest.approx(160 / (10000 / W), rel=1e-3)


# ---------------------------------------------------------------------------------------------------------------------
# Szenario-API (T3)


def test_szenario_ereignisse_und_standard():
    ereignisse = [
        {"was": "szenario", "name": "Bremsen", "beschleunigung": [-3, 0, 0], "zeile": 4},
        {"was": "last", "teile": ["A"], "kraft": [0, 0, -100], "punkt": None, "szenario": "Bremsen"},
        {"was": "last", "teile": ["B"], "kraft": [0, 0, -9.81], "kg": 1, "szenario": None},
        {"was": "szenario", "name": "Schräg", "neigung": {"grad": 10, "richtung": "+y"}},
        {"was": "stoss", "faktor": 2.0, "szenario": "Schräg"},
        {"was": "last", "teile": ["A"], "kraft": ["x"], "szenario": "Schräg", "zeile": 9},
    ]
    szen, einst = aus_modell(ereignisse)
    namen = {s.name: s for s in szen}
    assert set(namen) == {"Bremsen", "Nutzlast", "Schräg"}
    assert namen["Bremsen"].dynamisch and namen["Bremsen"].ziel_fuer(True) == 6.0
    assert namen["Bremsen"].feld == pytest.approx([3.0, 0.0, -9.81])
    f = namen["Schräg"].feld
    assert f[1] == pytest.approx(9.81 * math.sin(math.radians(10))) and namen["Schräg"].stoss_faktor == 2.0
    assert einst["warnungen"] and einst["warnungen"][0]["zeile"] == 9


# ---------------------------------------------------------------------------------------------------------------------
# Ende zu Ende (Runner im Testprozess)


def test_ueberdimensionierter_rahmen_bekommt_leichteres_lagerteil(tmp_path):
    t0 = time.perf_counter()
    _, check, _ = laufe(tmp_path, TISCH)
    e = szenario(check, "Last 20 kg")
    assert e["ampel"] == "gruen" and e["kennzahlen"]["sicherheit"] > 10
    ueber = [u for u in e["urteile"] if u["art"] == "ueberdimensioniert"]
    assert ueber, e["urteile"]
    alt = ueber[0]["alternative"]
    assert alt["stock_id"].startswith("vierkantrohr-en10219-") and alt["stock_id"] != "vierkantrohr-en10219-40x40x3"
    assert alt["ersparnis_kg"] > 1 and alt["ersparnis_eur"] > 0 and alt["sicherheit"] >= 2
    assert "aus dem Lager reicht" in ueber[0]["text"] and "spart" in ueber[0]["text"]
    b = [b for b in check["befunde"] if b["art"] == "statik_ueberdimensioniert"]
    assert b and b[0]["schwere"] == "hinweis"
    # Eigengewicht allein meldet nichts Überdimensioniertes
    assert not [u for u in szenario(check, "Eigengewicht")["urteile"] if u["art"] == "ueberdimensioniert"]
    assert time.perf_counter() - t0 < 60


def test_druckhalter_quer_zur_schicht_rot_mit_drehen_oder_verstaerken(tmp_path):
    _, check, _ = laufe(tmp_path, HALTER.replace("AUSRICHTUNG", '"-x"'))
    e = szenario(check, "Haken 2 kg")
    u = next(u for u in e["urteile"] if u["art"] == "bauteil")
    assert e["ampel"] == "rot" and u["ampel"] == "rot" and u["quer_zur_schicht"] and u["schichtfaktor"] == 0.4
    assert u["ziel"] == 4.0
    assert u["loesung"].startswith("Drehen:") and "verstärken" in u["loesung"] and 'ausrichtung="-z"' in u["loesung"]
    assert any(b["art"] == "statik_bauteil" and b["schwere"] == "warnung" for b in check["befunde"])
    flach_tmp = tmp_path / "flach"
    flach_tmp.mkdir()
    _, flach, _ = laufe(flach_tmp, HALTER.replace("AUSRICHTUNG", '"-z"'))
    ef = szenario(flach, "Haken 2 kg")
    assert ef["ampel"] == "gruen" and ef["kennzahlen"]["sicherheit"] == pytest.approx(
        e["kennzahlen"]["sicherheit"] / 0.4, rel=0.02)


def test_kippen_je_richtung_und_reserve(tmp_path):
    _, check, _ = laufe(tmp_path, TURM, strikt=False)
    e = szenario(check, "Anstoßen")
    k = next(u for u in e["urteile"] if u["art"] == "kippen")
    assert k["ampel"] == "rot" and e["kennzahlen"]["kippreserve"] < 1
    eg = szenario(check, "Eigengewicht")
    assert eg["ampel"] in ("gruen", "grau")
    st = check["statik"]
    assert st["aktiv"] == "Anstoßen"


def test_szenario_auf_anfrage_unter_einer_sekunde(tmp_path):
    _, check, _ = laufe(tmp_path, TISCH)
    t0 = time.perf_counter()
    pfad = dienst.auftrag(json.dumps({"szenario": {"name": "Aufstützen 80 kg", "lasten": [
        {"teil": "Tisch/Zarge vorn", "kg": 80}]}}))
    ms = (time.perf_counter() - t0) * 1000
    erg = json.loads(Path(pfad).read_text())
    Path(pfad).unlink()
    assert erg["stand"] == "done" and erg["aktiv"] == "Aufstützen 80 kg" and ms < 1000
    e = erg["szenarien"][0]
    assert e["name"] == "Aufstützen 80 kg" and e["kennzahlen"]["sicherheit"] > 2
    falsch = json.loads(Path(dienst.auftrag(json.dumps({"szenario": {"name": "X", "lasten": [
        {"teil": "Tisch/Zarge vonr", "kg": 1}]}}))).read_text())
    assert falsch["stand"] == "failed" and "Zarge vorn" in falsch["meldung"]


# ---------------------------------------------------------------------------------------------------------------------
# Protokoll und Texte


def test_statics_nachricht_und_kurzfassung():
    b = statik_beispiel()
    head = pack_statics(b, run=7)
    assert not check_statics_message(head)
    assert head["szenarien"][0]["kippen"][0]["je_richtung"]["+X"]["kippwinkel"] == 31.0
    kaputt = pack_statics({**b, "szenarien": [dict(b["szenarien"][0], ampel="lila")]}, run=7)
    assert any("lila" in f for f in check_statics_message(kaputt))
    kurz = statik_kurz(b)
    assert "staebe" not in kurz["szenarien"][0] and kurz["szenarien"][1]["ampel"] == "rot"
    assert lauf_zeile(kurz) == "Statik: Eigengewicht grün · Aufstützen 30 kg rot (Sicherheit 0,2)"
    text = statik_text({"run": 7, "szenarien": b["szenarien"], "grenzen": b["grenzen"],
                        "vereinfachungen": b["vereinfachungen"]})
    assert "Aufstützen 30 kg: rot" in text and "Kein Ersatz für einen Statiker" in text


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit: STATICS an die App, statik und szenario_rechnen


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcst", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_laufzeit_statics_statik_und_szenario_rechnen(env):
    rt, app = env["rt"], env["app"]
    projekt = env["tmp"] / "Tisch"
    assert rt.project_new(str(projekt), "empty")["ok"]
    # Der Test-Katalog der Laufzeit kennt Stahl ohne Mechanik: im Projekt-Katalog mit den mitgelieferten Werten
    stahl = Catalog(builtin=builtin_dir(), own=env["tmp"] / "leer").material("stahl-s235")
    stahl = {k: v for k, v in stahl.items() if k not in ("ebene", "status")}
    (projekt / "katalog.json").write_text(json.dumps({"version": 1, "materialien": [stahl]}), encoding="utf-8")
    assert rt.model_write(TISCH)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    assert res["pruefung"]["statik"]["szenarien"][0]["name"] == "Eigengewicht"
    _, _, st, _ = app.wait_for(lambda h: h["type"] == "STATICS", start=start, timeout=60)
    assert not check_statics_message(st) and st["run"] == res["run"]
    _, _, check, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h["state"] in ("done", "teilweise"),
                                  start=start, timeout=60)
    assert "staebe" not in check["statik"]["szenarien"][0]  # im CHECK nur die Kurzfassung
    uebersicht = rt.statik()
    assert uebersicht["ok"] and {e["name"] for e in uebersicht["szenarien"]} >= {"Eigengewicht", "Last 20 kg"}
    detail = rt.statik("Last 20 kg")
    assert detail["szenario"]["stabwerte"] and detail["szenario"]["auflager"]
    assert not rt.statik("Lats 20 kg")["ok"]
    start = app.mark()
    t0 = time.perf_counter()
    neu = rt.szenario_rechnen("Draufsetzen 90 kg", lasten=[{"teil": "Tisch/Zarge vorn", "kg": 45},
                                                         {"teil": "Tisch/Zarge hinten", "kg": 45}])
    dauer = time.perf_counter() - t0
    assert neu["ok"], neu
    assert neu["szenario"]["name"] == "Draufsetzen 90 kg" and neu["gezeigt"] and dauer < 2.0
    _, _, st2, _ = app.wait_for(lambda h: h["type"] == "STATICS" and h.get("aktiv") == "Draufsetzen 90 kg",
                                start=start, timeout=30)
    assert any(e["name"] == "Draufsetzen 90 kg" for e in st2["szenarien"])
