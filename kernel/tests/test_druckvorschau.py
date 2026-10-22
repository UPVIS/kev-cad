"""Druckvorschau (DRUCKVORSCHAU.md): Geometrie im Rechenprozess, Empfehlungen, Schätzung und Abgleich, Anordnen,
Vorgaben in druck.json, Laufzeit mit PRINT_PREVIEW/PRINT_SETTINGS/PRINT_EXPORT_REQ, MCP-Werkzeuge, Abdrücke in der
Druckprüfung. Ohne Bambu Studio (Slicer aus); Slicer-Tests stehen in test_druck_slicer.py."""

import json
import math
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import anyio
import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.catalog import Catalog, builtin_dir
from kevcad_kernel.druck import anordnen as ao
from kevcad_kernel.druck import empfehlung as em
from kevcad_kernel.druck import schaetzung as sz
from kevcad_kernel.druck import vorgaben as vg
from kevcad_kernel.druck import vorschau as vs
from kevcad_kernel.druck.vorschau_geo import teil_mit_form
from kevcad_kernel.protocol import check_druck_message, pack_print_preview
from kevcad_kernel.runner import Runner

HEAD = "from build123d import *\nfrom kevcad import lager, show, param\n"
WINKEL = """
winkel = Box(40, 20, 4, align=(Align.MIN, Align.MIN, Align.MIN)) + Box(4, 20, 30, align=(Align.MIN, Align.MIN, Align.MIN))
winkel -= Pos(20, 10, 0) * Cylinder(2.5, 10)
"""
MODELL = HEAD + WINKEL + """
for i in range(8):
    show(Pos(i * 60, 0, 0) * Rot(0, 0, 15 * i) * lager.druckteil(winkel, f"Winkel {i}", material="petg", zweck="tragend"),
         f"Halter/Winkel {i}")
show(Pos(0, 80, 0) * lager.druckteil(Cylinder(10, 40, align=(Align.CENTER, Align.CENTER, Align.MIN)), "Rolle",
                                     material="pla", anzahl=3), "Rolle")
t = Box(60, 20, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
show(Pos(0, -100, 0) * lager.druckteil(Box(20, 20, 30, align=(Align.CENTER, Align.CENTER, Align.MIN)) + Pos(0, 0, 30) * t,
                                        "T", material="petg", ausrichtung="-z"), "T")
"""


@pytest.fixture(autouse=True)
def eigene_ablage(tmp_path, monkeypatch):
    """Zwischenspeicher und Abgleich im Testordner; Bambu Studio „fehlt“ (Mac mini)."""
    monkeypatch.setenv("KEVCAD_DRUCK_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("KEVCAD_DRUCK_ABGLEICH", str(tmp_path / "abgleich.json"))
    monkeypatch.setenv("KEVCAD_BAMBU_APP", str(tmp_path / "kein-bambu.app"))
    yield


def laufe(tmp_path: Path, code: str):
    (tmp_path / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": True}))
    model = tmp_path / "model.py"
    model.write_text(code, encoding="utf-8")
    runner = Runner(lambda h, p=b"": None)
    res = runner.run({"run": 1, "path": str(model), "code": code, "params": {}, "inventar_regel": True,
                      "catalog": {"builtin": str(builtin_dir()), "own": str(tmp_path / "eigen")}})
    assert res["type"] == "RUN_DONE", res.get("error")
    check, _ = runner.pruefe(1)
    assert check["state"] == "done", check
    return check, runner


# ---------------------------------------------------------------------------------------------------------------------
# Rechenprozess: Geometrie je Druckteil


def test_geometrie_in_druckausrichtung(tmp_path):
    check, _ = laufe(tmp_path, MODELL)
    v = check["druck"]["vorschau"]
    assert not v["fehler"] and set(v["teile"]) == {f"Halter/Winkel {i}" for i in range(8)} | {"Rolle", "T"}
    g0, g3 = teil_mit_form(v, "Halter/Winkel 0"), teil_mit_form(v, "Halter/Winkel 3")
    assert g0["fid"] == g3["fid"], "gleiche Form, gleiche Druckausrichtung: eine Formtabelle"
    assert len(v["formen"]) == 3
    assert g0["groesse"] == pytest.approx([40, 20, 30], abs=0.05)
    assert g0["volumen"] == pytest.approx(5201.46, rel=1e-3) and g0["zweck"] == "tragend" and g0["anzahl"] is None
    assert g0["auflage"] == pytest.approx(780.4, abs=1) and g0["oben"] == pytest.approx(780.4, abs=1)
    assert g0["umriss_flaeche"] == pytest.approx(800, abs=1)
    # Ein Weltpunkt des gedrehten Teils landet in Druckkoordinaten im Hüllquader (Matrix, t, Versatz stimmen)
    lo = np.array([-20, -10, 0]) - 0.01
    hi = np.array([20, 10, 30]) + 0.01
    for name in ("Halter/Winkel 3", "Halter/Winkel 5"):
        g = teil_mit_form(v, name)
        A, t, ver = np.array(g["matrix"]), np.array(g["t"]), np.array(g["versatz"])
        ecken = np.array([[0, 0, 0], [40, 20, 4], [4, 20, 30]], dtype=float)
        i = int(name[-1])
        w = math.radians(15 * i)
        R = np.array([[math.cos(w), -math.sin(w), 0], [math.sin(w), math.cos(w), 0], [0, 0, 1]])
        welt = ecken @ R.T + [i * 60, 0, 0]
        p = (welt - t) @ A.T - ver
        assert np.all(p >= lo) and np.all(p <= hi), (name, p)
    rolle = teil_mit_form(v, "Rolle")
    assert rolle["anzahl"] == 3 and rolle["material"] == "pla"
    t_ = teil_mit_form(v, "T")
    assert t_["stuetzflaeche"] > 500 and t_["ueberhang_hoehe"] == pytest.approx(30, abs=0.5)
    assert sum(t_["seite_baender"]) == pytest.approx(t_["seite"], rel=1e-6)


# ---------------------------------------------------------------------------------------------------------------------
# Empfehlungen, Schätzung, Abgleich


def _geo(**kw):
    g = {"volumen": 20000.0, "seite": 4000.0, "oben": 800.0, "unten": 0.0, "auflage": 800.0,
         "groesse": [40.0, 20.0, 30.0], "stuetzflaeche": 0.0, "ueberhang_hoehe": 0.0, "umriss_umfang": 120.0,
         "auflage_pruefung": 800.0, "seite_baender": [200.0] * 20, "waag_baender": [800.0] + [0.0] * 18 + [800.0],
         "ausrichtung_text": "−Z-Seite unten", "liegt_auf": "Halter#f2"}
    g.update(kw)
    return g


def test_empfehlung_je_zweck_und_vorgaben():
    e = em.empfehle(_geo(), "petg", "tragend")
    assert e["einstellungen"]["waende"] == 4 and e["einstellungen"]["fuellung"] == 0.25
    assert e["einstellungen"]["muster"] == "gyroid" and e["einstellungen"]["stuetzen"] == "keine"
    assert not e["einstellungen"]["brim"] and not e["zweck_geschaetzt"]
    assert any("Last längs der Schichten" in b for b in e["begruendung"])
    z = em.empfehle(_geo(), "pla", "zier")["einstellungen"]
    assert z["schicht_mm"] == 0.16 and z["waende"] == 2 and z["decken"] >= 7  # Decken ≥ 1 mm
    f = em.empfehle(_geo(), "petg", None)
    assert f["zweck"] == "funktion" and f["zweck_geschaetzt"] and f["einstellungen"]["waende"] == 3
    # kleine Auflage, schlank: Brim; Stützen aus der Stützfläche der Druckprüfung
    s = em.empfehle(_geo(auflage_pruefung=12.0, groesse=[5, 5, 60], stuetzflaeche=140.0, ueberhang_hoehe=30.0),
                    "petg", "funktion")
    assert s["einstellungen"]["brim"] and s["einstellungen"]["stuetzen"] == "baum"
    v = em.empfehle(_geo(), "petg", "tragend", {"waende": 6, "muster": "cubic"})
    assert v["einstellungen"]["waende"] == 6 and v["einstellungen"]["muster"] == "cubic"
    assert set(v["fest"]) == {"waende", "muster"}


def test_hinweise_druckpraxis():
    e = em.empfehle(_geo(stuetzflaeche=200.0, ueberhang_hoehe=20), "petg", "bewegt")["einstellungen"]
    r, gruende = em.risiko(_geo(stuetzflaeche=200.0), e, "petg", 3600)
    h = em.hinweise(_geo(stuetzflaeche=200.0), e, "petg", "bewegt", {"stuetzen_g": 1.2}, 4, r, gruende,
                    ["Rolle#f7"])
    arten = {x["art"] for x in h}
    assert {"trocknen", "stuetzen", "festigkeit"} <= arten
    assert any("Rolle#f7" in x["text"] for x in h if x["art"] == "stuetzen")
    abs_ = em.hinweise(_geo(), em.empfehle(_geo(), "abs", "funktion")["einstellungen"], "abs", "funktion", {}, 1,
                       0.3, ["ABS offen gedruckt"])
    assert any(x["art"] == "verzug" and x["schwere"] == "warnung" for x in abs_)
    assert any(x["art"] == "risiko" for x in abs_)
    cf = em.hinweise(_geo(), em.empfehle(_geo(), "pla-cf", "funktion")["einstellungen"], "pla-cf", "funktion", {}, 1,
                     0.02, [])
    assert any(x["art"] == "duese" for x in cf)
    aussen = em.hinweise(_geo(), em.empfehle(_geo(), "pla", "aussen")["einstellungen"], "pla", "aussen", {}, 1, 0, [])
    assert any(x["art"] == "material" and "draußen" in x["text"] for x in aussen)
    g = em.globale_hinweise(["petg", "pla"], {"petg": 1200.0, "pla": 10.0}, [{"nr": 1, "zeit_s": 50000}], ["X"])
    assert {x["art"] for x in g} == {"ams", "material", "platte", "bauraum"}


def test_schaetzung_plausibel_und_monoton():
    geo = _geo()
    a = sz.schaetze(geo, {"schicht_mm": 0.2, "waende": 2, "fuellung": 0.15, "muster": "grid"}, "petg")
    b = sz.schaetze(geo, {"schicht_mm": 0.2, "waende": 4, "fuellung": 0.25, "muster": "gyroid"}, "petg")
    assert 0 < a["g"] < b["g"] and a["zeit_s"] < b["zeit_s"]
    assert a["m"] == pytest.approx(a["volumen_cm3"] / sz.CM3_JE_M, rel=1e-3)
    assert a["g"] == pytest.approx(a["volumen_cm3"] * 1.27, rel=1e-3)
    voll = sz.schaetze(geo, {"schicht_mm": 0.2, "waende": 2, "fuellung": 1.0}, "petg")
    assert voll["volumen_cm3"] <= 20.0 * 1.01  # nie mehr als das Volumen
    st = sz.schaetze(_geo(stuetzflaeche=400.0, ueberhang_hoehe=25.0), {"stuetzen": "baum"}, "petg")
    assert st["stuetzen_g"] > 0 and st["g"] > sz.schaetze(_geo(), {}, "petg")["g"]
    f = sz.schaetze(geo, {}, "petg", {"zeit": 2.0, "material": 0.5})
    o = sz.schaetze(geo, {}, "petg")
    assert f["zeit_s"] == pytest.approx(2 * o["zeit_s"], rel=1e-3) and f["g"] == pytest.approx(o["g"] / 2, rel=1e-2)
    # Kühlung: ein dünner hoher Stift braucht mindestens Mindestschichtzeit · Schichten (gedeckelt durch v_min)
    stift = _geo(volumen=4712.0, seite=1885.0, oben=78.5, auflage=78.5, groesse=[10, 10, 60],
                 seite_baender=[94.25] * 20, waag_baender=[78.5] + [0.0] * 18 + [78.5])
    s = sz.schaetze(stift, {"waende": 2}, "petg")
    assert s["anteile"]["kuehl_s"] > 0 and s["zeit_s"] > 300 * 5


def test_abgleich_nachfuehren(tmp_path):
    k = ("p1p-0.4", "0.20mm Standard @BBL P1P", "petg")
    assert sz.faktoren(sz.lies_abgleich(), *k) == {"zeit": 1.0, "material": 1.0, "n": 0}
    r = sz.abgleich_nachfuehren(*k, {"zeit_s": 1000, "volumen_cm3": 10}, {"zeit_s": 1200, "volumen_cm3": 9})
    assert r["nachher"] == {"zeit": 1.2, "material": 0.9, "n": 1}
    sz.abgleich_nachfuehren(*k, {"zeit_s": 1000, "volumen_cm3": 10}, {"zeit_s": 1000, "volumen_cm3": 10})
    f = sz.faktoren(sz.lies_abgleich(), *k)
    assert f["n"] == 2 and 1.0 < f["zeit"] < 1.2
    d = json.loads((tmp_path / "abgleich.json").read_text())
    assert "p1p-0.4|0.20mm Standard @BBL P1P|petg" in d["faktoren"]
    # Reglerwerte: nichts speichern
    sz.abgleich_nachfuehren(*k, {"zeit_s": 1, "volumen_cm3": 1}, {"zeit_s": 2, "volumen_cm3": 2}, speichern=False)
    assert json.loads((tmp_path / "abgleich.json").read_text()) == d


# ---------------------------------------------------------------------------------------------------------------------
# Anordnen


def _rechteck(w, h):
    return [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]


def _ueberlappen(a, b):
    (ax0, ay0), (ax1, ay1) = np.min(a, axis=0), np.max(a, axis=0)
    (bx0, by0), (bx1, by1) = np.min(b, axis=0), np.max(b, axis=0)
    return ax0 < bx1 - 1e-6 and bx0 < ax1 - 1e-6 and ay0 < by1 - 1e-6 and by0 < ay1 - 1e-6


def test_acht_gleiche_halter_auf_eine_platte():
    st = [ao.Stueck("g1", f"Halter {i}", "petg", 62, 38, _rechteck(62, 38), 62 * 38) for i in range(8)]
    platten = ao.anordne(st)
    assert len(platten) == 1 and len(platten[0].lagen) == 8
    umrisse = [l_.umriss() for l_ in platten[0].lagen]
    for i, a in enumerate(umrisse):
        a = np.array(a)
        assert a.min() >= -1e-6 and a.max() <= 256 + 1e-6
        assert not _ueberlappen(a, np.array([[0, 0], [18, 28]])), "Sperrzone vorn links"
        for b in umrisse[i + 1:]:
            assert not _ueberlappen(a, np.array(b))
    assert 0 < platten[0].auslastung() < 1


def test_viele_teile_mehrere_platten_und_materialien():
    st = [ao.Stueck("g1", f"A{i}", "petg", 100, 80, _rechteck(100, 80), 8000) for i in range(9)]
    st += [ao.Stueck("g2", f"B{i}", "pla", 20, 20, _rechteck(20, 20), 400, rand=5.0) for i in range(5)]
    st += [ao.Stueck("g3", "Riese", "petg", 300, 40, _rechteck(300, 40), 12000)]
    platten = ao.anordne(st)
    petg = [p for p in platten if p.material == "petg" and not p.passt_nicht]
    assert len(petg) == 2 and sum(len(p.lagen) for p in petg) == 9
    assert [p.material for p in platten if any(l_.stueck.material == "pla" for l_ in p.lagen)] == ["pla"]
    riese = [p for p in platten if p.passt_nicht]
    assert len(riese) == 1 and riese[0].lagen[0].stueck.name == "Riese"


# ---------------------------------------------------------------------------------------------------------------------
# Vorschau bauen


def test_vorschau_aus_der_pruefung(tmp_path):
    check, _ = laufe(tmp_path, MODELL)
    cat = Catalog()
    t0 = time.perf_counter()
    v, gr, platten = vs.baue(1, check["druck"], check["befunde"], {}, {}, cat.material)
    ms = (time.perf_counter() - t0) * 1000
    assert ms < 1000
    assert check_druck_message(pack_print_preview(v)) == []
    json.dumps(v, allow_nan=False)
    teile = {t["name"]: t for t in v["teile"]}
    assert teile["Winkel"]["anzahl"] == 8 and teile["Winkel"]["zweck"] == "tragend"
    assert teile["Winkel"]["einstellungen"]["waende"] == 4 and teile["Winkel"]["stand"] == "schaetzung"
    assert teile["Rolle"]["anzahl"] == 3 and teile["Rolle"]["zweck_geschaetzt"]
    assert teile["T"]["einstellungen"]["stuetzen"] == "baum"
    assert any(h["art"] == "stuetzen" for h in teile["T"]["hinweise"])
    assert teile["Winkel"]["g"] == pytest.approx(8 * teile["Winkel"]["je_stueck"]["g"], abs=0.2)
    # Platten: PETG und PLA getrennt, alle Winkel zusammen, Ersatzrollen markiert
    mats = [p["material"][0]["material"] for p in v["platten"]]
    assert sorted(set(mats)) == ["petg", "pla"]
    p_petg = [p for p in v["platten"] if p["material"][0]["material"] == "petg"]
    assert len(p_petg) == 1 and sum(1 for t in p_petg[0]["teile"] if t["gruppe"] == teile["Winkel"]["gruppe"]) == 8
    rollen = [t for p in v["platten"] for t in p["teile"] if t["name"] == "Rolle"]
    assert len(rollen) == 3 and sum(1 for t in rollen if t["ersatz"]) == 2
    s = v["summe"]
    assert s["platten"] == len(v["platten"]) == 2
    assert s["zeit_mit_wechsel_s"] == s["zeit_s"] + 120
    assert s["kosten"] == pytest.approx(sum(s["kosten_teile"].values()), abs=0.011)
    assert {m["material"] for m in s["material"]} == {"petg", "pla"}
    assert v["slicer"]["zustand"] == "aus"
    assert any(h["art"] == "ams" for h in v["hinweise"])
    kurz = vs.kurz(v)
    assert all("umriss" not in t for p in kurz["platten"] for t in p["teile"])
    from kevcad_kernel.druck.vorschau_text import text
    assert "Platte 1" in text(v) and "Winkel ×8" in text(v)


def test_projekt_einstellungen_druckplatte():
    d = vs.projekt_einstellungen({"druck": {"platte": "glatt", "strompreis_kwh": 0.4}})
    assert d["platte"] == "High Temp Plate" and d["strompreis_kwh"] == 0.4 and d["leistung_w"] == 150.0
    assert vs.projekt_einstellungen({})["platte"] == "Textured PEI Plate"
    falsch = vs.projekt_einstellungen({"druck": {"platte": "Glasplatte"}})
    assert falsch["platte"] == "Textured PEI Plate" and "Glasplatte" in falsch["platte_fehler"]


def test_vorgaben_in_druck_json(tmp_path):
    d = vg.setze(tmp_path, ["A", "B"], einstellungen={"waende": 5, "fuellung": 30}, von="kevin")
    assert d["teile"]["A"]["einstellungen"] == {"waende": 5, "fuellung": 0.3}
    assert d["teile"]["A"]["von"] == {"waende": "kevin", "fuellung": "kevin"}
    d = vg.setze(tmp_path, ["A"], einstellungen={"fuellung": 0.4}, zweck="tragend", von="agent")
    assert d["teile"]["A"]["von"] == {"waende": "kevin", "fuellung": "agent", "zweck": "agent"}
    d = vg.setze(tmp_path, ["A"], einstellungen={"waende": None})
    assert d["teile"]["A"]["einstellungen"] == {"fuellung": 0.4} and "waende" not in d["teile"]["A"]["von"]
    d = vg.setze(tmp_path, ["B"], zuruecksetzen=True)
    assert "B" not in d["teile"]
    assert vg.lies(tmp_path)["teile"]["A"]["zweck"] == "tragend"
    for falsch in ({"schicht_mm": 0.5}, {"muster": "sterne"}, {"stuetzen": "viele"}, {"waende": 0},
                   {"ausrichtung": "-z"}, {"farbe": "rot"}):
        with pytest.raises(vg.VorgabeFehler):
            vg.setze(tmp_path, ["A"], einstellungen=falsch)
    with pytest.raises(vg.VorgabeFehler):
        vg.setze(tmp_path, ["A"], zweck="schoen")
    # alte Dateien mit einem Wert für alles
    assert vg.von_je_schluessel({"einstellungen": {"waende": 4}, "zweck": "zier", "von": "agent"}) == \
        {"waende": "agent", "zweck": "agent"}


def test_vorgaben_wirken_in_der_vorschau(tmp_path):
    check, _ = laufe(tmp_path, MODELL)
    vorg = vg.setze(tmp_path, [f"Halter/Winkel {i}" for i in range(8)], einstellungen={"waende": 6}, von="agent")
    vorg = vg.setze(tmp_path, ["Rolle"], zweck="bewegt", von="kevin")
    v, _, _ = vs.baue(1, check["druck"], check["befunde"], vorg, {}, Catalog().material)
    teile = {t["name"]: t for t in v["teile"]}
    assert teile["Winkel"]["einstellungen"]["waende"] == 6 and teile["Winkel"]["fest"] == ["waende"]
    assert teile["Winkel"]["fest_von"] == {"waende": "agent"}
    assert teile["Rolle"]["zweck"] == "bewegt" and not teile["Rolle"]["zweck_geschaetzt"]
    assert teile["Rolle"]["fest_von"] == {"zweck": "kevin"}


def test_druckteil_zweck_und_anzahl_werden_geprueft(tmp_path):
    from kevcad.lager import LagerError, _pruefe_zweck_anzahl

    assert _pruefe_zweck_anzahl("Außen", 3, "x") == ("aussen", 3)
    with pytest.raises(LagerError, match="tragend"):
        _pruefe_zweck_anzahl("tragen", None, "x")
    for falsch in (0, -1, 1.5, True, "2"):
        with pytest.raises(LagerError):
            _pruefe_zweck_anzahl(None, falsch, "x")


# ---------------------------------------------------------------------------------------------------------------------
# Druckprüfung: Abdrücke fremder Teile im Schichtraster


def test_abdruecke_fremder_teile_gebuendelt(tmp_path):
    code = HEAD + """
rohr = Pos(0, 0, 10.3) * lager.teil("vierkantrohr-alu-20x20x1.5").verbauen(laenge=100, name="Rahmen/Rohr")
show(rohr, "Rahmen/Rohr")
bb = rohr.bounding_box()
block = Pos(bb.center().X, bb.center().Y, 0) * Box(bb.size.X + 20, 40, 20.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
for v in ((0, 0, 0), (0.25, 0, 0), (-0.25, 0, 0), (0, 0.25, 0), (0, -0.25, 0), (0, 0, 0.25), (0, 0, -0.25)):
    block -= Pos(*v) * rohr
block += Pos(bb.center().X, 30, 0) * Box(10, 10, 7.3, align=(Align.CENTER, Align.CENTER, Align.MIN))
show(lager.druckteil(block, "Halter", material="petg", ausrichtung="-z"), "Halter")
"""
    check, _ = laufe(tmp_path, code)
    raster = [b for b in check["befunde"] if b["art"] == "druck_schichtraster"]
    abdruck = [b for b in check["befunde"] if b["art"] == "druck_schichtraster_abdruck"]
    assert len(abdruck) == 1 and abdruck[0]["schwere"] == "hinweis" and abdruck[0]["teile"] == ["Halter"]
    assert "aus der Aussparung für Rohr" in abdruck[0]["text"] and "unkritisch, Passung prüfen" in abdruck[0]["text"]
    assert abdruck[0]["wert"]["abdruck_von"] == "Rahmen/Rohr" and len(abdruck[0]["wert"]["flaechen"]) >= 2
    assert len(raster) == 1 and "7,3" in raster[0]["text"] and "10,05" not in raster[0]["text"]
    assert not set(raster[0]["wert"]["flaechen"]) & set(abdruck[0]["wert"]["flaechen"])


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit und App


@pytest.fixture(scope="module")
def env():
    alt = {k: os.environ.get(k) for k in ("KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH", "KEVCAD_BAMBU_APP")}
    tmp = Path(tempfile.mkdtemp(prefix="kcdv", dir=tempfile.gettempdir()))
    os.environ.update({"KEVCAD_DRUCK_CACHE": str(tmp / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(tmp / "abgleich.json"),
                       "KEVCAD_BAMBU_APP": str(tmp / "kein-bambu.app")})
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)
    for k, v in alt.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_laufzeit_vorschau_einstellungen_export(env, monkeypatch):
    for k in ("KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH", "KEVCAD_BAMBU_APP"):
        monkeypatch.setenv(k, os.environ[k] if k != "KEVCAD_DRUCK_CACHE" else str(env["tmp"] / "cache"))
    monkeypatch.setenv("KEVCAD_BAMBU_APP", str(env["tmp"] / "kein-bambu.app"))
    rt, app = env["rt"], env["app"]
    projekt = env["tmp"] / "Druck"
    assert rt.project_new(str(projekt), "empty")["ok"]
    code = HEAD + 'n = param("n", 4)\n' + WINKEL + """
for i in range(n):
    show(Pos(i * 60, 0, 0) * lager.druckteil(winkel, f"Winkel {i}", material="petg", zweck="tragend"), f"Halter/Winkel {i}")
show(Pos(0, 80, 0) * lager.druckteil(Box(30, 30, 6), "Deckel", material="petg"), "Deckel")
"""
    assert rt.model_write(code)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    _, _, v, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h["run"] == res["run"], start=start)
    assert check_druck_message(v) == [] and v["slicer"]["zustand"] == "aus" and not v["regler"]
    assert "Bambu Studio nicht gefunden" in v["slicer"]["meldung"]
    assert {t["name"]: t["anzahl"] for t in v["teile"]} == {"Winkel": 4, "Deckel": 1}
    d = rt.druckvorschau()
    assert d["ok"] and d["run"] == res["run"] and "umriss" not in d["platten"][0]["teile"][0]
    assert "umriss" in rt.druckvorschau(detail=True)["platten"][0]["teile"][0]
    # Anfrage der App
    m = app.mark()
    app.send({"type": "PRINT_PREVIEW_REQ", "id": "a-1"})
    _, _, antwort, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h.get("reply_to") == "a-1", start=m)
    assert antwort["run"] == res["run"]
    # feste Vorgabe: ACK, druck.json, neue Vorschau mit fest und fest_von
    gid = next(t["gruppe"] for t in v["teile"] if t["name"] == "Winkel")
    m = app.mark()
    app.send({"type": "PRINT_SETTINGS", "id": "a-2", "gruppe": gid, "einstellungen": {"waende": 5, "fuellung": 0.3}})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-2", start=m)
    assert ack["ok"] and "Wände 5" in ack["message"], ack
    _, _, v2, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and any(
        t.get("fest") for t in h["teile"]), start=m)
    w = next(t for t in v2["teile"] if t["name"] == "Winkel")
    assert w["einstellungen"]["waende"] == 5 and set(w["fest"]) == {"waende", "fuellung"}
    assert w["fest_von"] == {"waende": "kevin", "fuellung": "kevin"}
    dj = json.loads((projekt / "druck.json").read_text())
    assert dj["teile"]["Halter/Winkel 0"]["einstellungen"] == {"waende": 5, "fuellung": 0.3}
    m = app.mark()
    app.send({"type": "PRINT_SETTINGS", "id": "a-3", "teil": "Halter/Winkel 0", "einstellungen": {"farbe": 1}})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-3", start=m)
    assert not ack["ok"]
    # Agent (MCP-Weg)
    r = rt.druck_einstellen("Deckel", zweck="zier")
    assert r["ok"] and r["gruppe"]["zweck"] == "zier" and r["gruppe"]["fest_von"] == {"zweck": "agent"}
    assert not rt.druck_einstellen("Gibtsnicht", zweck="zier")["ok"]
    # neuer Lauf: Vorgaben überleben
    res = rt.run()
    v3 = rt.druckvorschau()
    assert v3["run"] == res["run"]
    assert next(t for t in v3["teile"] if t["name"] == "Winkel")["einstellungen"]["waende"] == 5
    # Reglerwerte: nur Schätzung, Slicer aus, markiert
    res_r = rt.run(params={"n": 6})
    vr = rt.druckvorschau()
    assert vr["run"] == res_r["run"] and vr["regler"] and vr["slicer"]["zustand"] == "aus"
    # die neuen Winkel 4 und 5 haben keine Vorgabe: eigene Gruppe
    assert sorted(t["anzahl"] for t in vr["teile"] if t["name"] == "Winkel") == [2, 4]
    rt.run()
    # 3MF ohne Bambu Studio: selbst geschrieben, Platten in model_settings.config
    m = app.mark()
    ziel = env["tmp"] / "platten.3mf"
    app.send({"type": "PRINT_EXPORT_REQ", "id": "a-4", "platten": [], "ziel": str(ziel)})
    _, _, ex, _ = app.wait_for(lambda h: h["type"] == "PRINT_EXPORT_RES" and h["reply_to"] == "a-4", start=m)
    assert check_druck_message(ex) == [] and ex["ok"] and ex["pfad"] == str(ziel) and ex["platten"] == [1]
    assert ex["fehler"] is None and ex["geprueft"] is False
    with zipfile.ZipFile(ziel) as z:
        assert {"3D/3dmodel.model", "Metadata/model_settings.config", "[Content_Types].xml"} <= set(z.namelist())
        einst = z.read("Metadata/model_settings.config").decode()
    assert einst.count("<plate>") == 1 and einst.count("<model_instance>") == 5
    falsch = rt.druck_export(platten=[7])
    assert not falsch["ok"] and falsch["fehler"] and "Platte 7" in falsch["fehler"]
    # Standardziel im Ausgabeordner
    std = rt.druck_export()
    assert std["ok"] and Path(std["pfad"]).name == "Druck-druck.3mf" and Path(std["pfad"]).exists()


def call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_mcp_werkzeuge():
    server, fake = start_server()
    try:
        url = server.url
        r = call(url, "druckvorschau")
        assert r.is_error  # noch kein Lauf
        call(url, "run")
        r = call(url, "druckvorschau")
        text = "\n".join(texts(r))
        assert not r.is_error and "Druckvorschau Lauf" in text and "Platte 1" in text and "Stangenhalter" in text
        assert "umriss" not in json.dumps(r.structured_content["platten"][0]["teile"][0])
        r = call(url, "druckvorschau", {"detail": True})
        assert "umriss" in r.structured_content["platten"][0]["teile"][0]
        r = call(url, "druck_einstellen", {"teil": "g1", "einstellungen": {"waende": 5}})
        assert not r.is_error and "Wände 5" in texts(r)[0]
        assert fake.calls_of("druck_einstellen")[-1] == (("g1", {"waende": 5}, None, "agent", False), {})
        assert call(url, "druck_einstellen", {"teil": "Nix", "zweck": "zier"}).is_error
        r = call(url, "druck_export", {"platten": [1]})
        assert not r.is_error and "3MF mit 1 Platte" in texts(r)[0]
    finally:
        server.stop_thread()
