"""Prüfung Stufe 1: Durchdringungen (kevcad_kernel/pruefung), im Prozess und über die Laufzeit mit Test-App."""

import json
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime
from build123d import Box, Cylinder, Pos, Rot

from kevcad_kernel.protocol import encode_frame, FrameReader, pack_check, unpack_check
from kevcad_kernel.pruefung.koerper import koerper_aus_form
from kevcad_kernel.pruefung.kollision import PaarCache, durchdringung, pruefe_paar
from kevcad_kernel.pruefung.pruefer import pruefe


def teile(**formen):
    return [koerper_aus_form(n.replace("_", " "), f) for n, f in formen.items()]


def nur_durchdringung(ks, erkl=None, cache=None):
    erg, geo = pruefe(ks, erkl or {}, {"pruefungen": ("erklaerungen", "durchdringung")}, cache)
    return erg, geo


# ---------------------------------------------------------------------------------------------------------------------
# Einzelfälle


def test_zwei_ueberlappende_quader():
    erg, geo = nur_durchdringung(teile(A=Box(10, 10, 10), B=Pos(8, 0, 0) * Box(10, 10, 10)))
    (b,) = erg["befunde"]
    assert b["art"] == "durchdringung" and b["schwere"] == "fehler" and b["teile"] == ["A", "B"]
    assert b["wert"]["volumen"] == pytest.approx(200.0, rel=1e-6)  # 2 × 10 × 10
    assert b["wert"]["tiefe"] == pytest.approx(2.0, abs=1e-3)
    assert b["ort"] == pytest.approx([4.0, 0.0, 0.0], abs=1e-6)
    assert "um 2,2 mm in" in b["loesung"] and "X" in b["loesung"]
    assert b["geometrie"] == 0 and len(geo) == 1 and len(geo[0][2]) >= 12
    assert erg["zusammenfassung"] == "1 Durchdringung" and erg["zaehler"]["fehler"] == 1


def test_beruehren_ist_kein_befund():
    erg, _ = nur_durchdringung(teile(A=Box(10, 10, 10), B=Pos(10, 0, 0) * Box(10, 10, 10),
                                     C=Pos(0, 0, 10) * Box(10, 10, 10)))
    assert erg["befunde"] == [] and erg["zusammenfassung"] == ""
    assert erg["paare"]["kontakte"] == 3


def test_toleranz_unter_der_schwelle():
    # 0,005 mm tief: Berühren mit Toleranz, kein Befund; 0,05 mm tief: Befund
    ok, _ = nur_durchdringung(teile(A=Box(10, 10, 10), B=Pos(9.995, 0, 0) * Box(10, 10, 10)))
    assert ok["befunde"] == []
    zu, _ = nur_durchdringung(teile(A=Box(10, 10, 10), B=Pos(9.95, 0, 0) * Box(10, 10, 10)))
    assert len(zu["befunde"]) == 1 and zu["befunde"][0]["wert"]["tiefe"] == pytest.approx(0.05, abs=1e-3)


def test_scheiben_und_kopf_sind_keine_ausnahme():
    scheibe = Cylinder(9, 1.6) - Cylinder(3.2, 2)
    s1 = Pos(0, 0, 0.8) * scheibe
    s2 = Pos(0, 0, 1.6) * scheibe  # 0,8 mm ineinander
    kopf = Pos(0, 0, 4.3) * Cylinder(5, 4)  # Kopf sitzt 0,1 mm in Scheibe 2
    erg, _ = nur_durchdringung(teile(Scheibe_1=s1, Scheibe_2=s2, Kopf=kopf))
    paare = sorted(tuple(b["teile"]) for b in erg["befunde"])
    assert paare == [("Scheibe 1", "Scheibe 2"), ("Scheibe 2", "Kopf")] or \
        paare == [("Kopf", "Scheibe 2"), ("Scheibe 1", "Scheibe 2")]


def test_gewindeeingriff_wird_erkannt():
    # M6 (Ø 6) im Kernloch Ø 5: Überlappung nur im Gewindeband → kein Befund
    platte = Box(30, 30, 10) - Cylinder(2.5, 12)
    schraube = Pos(0, 0, 2) * Cylinder(3, 20)
    erg, _ = nur_durchdringung(teile(Platte=platte, Schraube=schraube))
    assert erg["befunde"] == [] and len(erg["gewinde"]) == 1
    assert "Gewindeeingriff M6" in erg["gewinde"][0]["text"]
    # Durchgangsbohrung zu klein für ein Ø-12-Rohr (Presspassung 0,15 mm): kein Gewinde, also Befund
    halter = Box(30, 30, 10) - Cylinder(5.85, 12)
    rohr = Cylinder(6, 40) - Cylinder(5, 42)
    erg2, _ = nur_durchdringung(teile(Halter=halter, Rohr=rohr))
    assert [b["art"] for b in erg2["befunde"]] == ["durchdringung"]
    # Schraube zu weit vorn (Kopf steckt in der Platte): kein reiner Gewindeeingriff
    kopf_drin = Pos(0, 0, 2) * (Cylinder(3, 20) + Pos(0, 0, 0) * Cylinder(5, 4))
    erg3, _ = nur_durchdringung(teile(Platte=platte, Schraube=kopf_drin))
    assert len(erg3["befunde"]) == 1


def test_erlaubte_ueberlappung_nur_mit_grund():
    ks = teile(A=Box(10, 10, 10), B=Pos(8, 0, 0) * Box(10, 10, 10))
    mit = {"erlaubt": [{"a": ["A"], "b": ["B"], "grund": "Presspassung"}]}
    erg, _ = nur_durchdringung(ks, mit)
    assert erg["befunde"] == [] and erg["erlaubt"][0]["grund"] == "Presspassung"
    ohne = {"erlaubt": [], "warnungen": [{"teil": "A", "text": "erlaubt_ueberlappung ohne Grund gilt nicht",
                                          "loesung": "Grund angeben"}]}
    erg2, _ = nur_durchdringung(ks, ohne)
    assert sorted(b["art"] for b in erg2["befunde"]) == ["durchdringung", "erklaerung"]


def test_zwischenspeicher_nach_relativer_lage():
    cache = PaarCache()
    a, b = Box(10, 10, 10), Pos(8, 0, 0) * Box(10, 10, 10)
    pruefe_paar(*teile(A=a, B=b), cache)
    assert cache.neu == 1
    # beide Teile gemeinsam verschoben und gedreht: gleiches Paar, kein neues Rechnen, Ort wandert mit
    lage = Pos(100, 50, 20) * Rot(0, 0, 90)
    p = pruefe_paar(*teile(A=lage * a, B=lage * b), cache)
    assert cache.neu == 1 and cache.treffer == 1
    assert p.ort == pytest.approx([100.0, 54.0, 20.0], abs=1e-6)
    assert p.durchdringt and p.tiefe == pytest.approx(2.0, abs=1e-3)


def test_durchdringung_fuer_die_animation():
    from build123d import Location

    a, b = Box(10, 10, 10), Box(10, 10, 10)
    assert durchdringung(a, b, Location((20, 0, 0)), None) is None
    d = durchdringung(a, b, Location((7, 0, 0)), None)
    assert d is not None and d.volumen == pytest.approx(300.0, rel=1e-6) and d.tiefe == pytest.approx(3.0, abs=1e-3)
    assert d.achse == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)  # a muss in +X heraus
    t0 = time.perf_counter()
    for _ in range(50):  # gleiche Stellung: aus dem Zwischenspeicher
        durchdringung(a, b, Location((7, 0, 0)), None, schluessel_a="a", schluessel_b="b")
    assert time.perf_counter() - t0 < 0.5


def test_check_rahmen_hin_und_zurueck():
    erg, geo = nur_durchdringung(teile(A=Box(10, 10, 10), B=Pos(8, 0, 0) * Box(10, 10, 10)))
    header, payload = pack_check(run=4, state="done", ergebnis=erg, geometrie=geo, seq=9)
    (h, p), = FrameReader().feed(encode_frame(header, payload))
    assert h["type"] == "CHECK" and h["run"] == 4 and h["zusammenfassung"] == "1 Durchdringung"
    assert h["geometrie"][0]["befund"] == h["befunde"][0]["id"] == "du1"
    (g,) = unpack_check(h, p)
    assert len(g["positions"]) == h["geometrie"][0]["vert"] and g["triangles"].max() < len(g["positions"])
    assert np.all(g["positions"][:, 0] >= 2.99) and np.all(g["positions"][:, 0] <= 5.01)  # Überlappung x 3 … 5


# ---------------------------------------------------------------------------------------------------------------------
# Über die Laufzeit: jeder Lauf prüft, run meldet, App bekommt CHECK, Export gesperrt


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcpr", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


HEAD = "from build123d import *\nfrom kevcad import show, step, param, erlaubt_ueberlappung\n"
MODELL = HEAD + """
versatz = param("versatz", 8)
show(Box(10, 10, 10), "Block A", material="pla")
show(Pos(versatz, 0, 0) * Box(10, 10, 10), "Block B", material="pla")
show(Pos(0, 0, 10) * Box(10, 10, 10), "Deckel", material="pla")
"""


def test_lauf_prueft_meldet_und_sperrt_export(env):
    rt, app = env["rt"], env["app"]
    path = env["tmp"] / "Bloecke"
    assert rt.project_new(str(path), "empty")["ok"]
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    assert rt.model_write(MODELL)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    pr = res["pruefung"]
    assert pr["state"] == "done" and pr["zusammenfassung"] == "1 Durchdringung"
    (b,) = [b for b in pr["befunde"] if b["schwere"] == "fehler"]
    assert b["teile"] == ["Block A", "Block B"] and b["loesung"]
    # App: erst „läuft“, dann das Ergebnis mit Schnittkörper
    _, _, laeuft, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h["state"] == "running", start=start)
    _, _, fertig, nutz = app.wait_for(lambda h: h["type"] == "CHECK" and h["state"] == "done", start=start)
    assert laeuft["run"] == fertig["run"] == res["run"] and len(unpack_check(fertig, nutz)) == 1
    # MCP-Text: Fehler mit Lösung
    from kevcad_kernel.mcp_tools.format import run_summary

    text, data, failed = run_summary(res)
    assert failed and text.startswith("Prüfung: 1 Durchdringung") and "Lösung:" in text
    # Export gesperrt, Status nennt die Prüfung
    ex = rt.export(["stl"])
    assert not ex["ok"] and "Export verweigert. Prüfung: 1 Durchdringung" in ex["error"]
    assert rt.status()["pruefung"]["zusammenfassung"] == "1 Durchdringung"
    # Behoben: kein Befund, Export geht
    res2 = rt.run(params={"versatz": 10})
    assert res2["ok"] and res2["pruefung"]["befunde"] == []
    assert run_summary(res2)[2] is False
    assert rt.export(["stl"])["ok"]


def test_erlaubnis_im_modell(env):
    rt = env["rt"]
    code = MODELL + 'erlaubt_ueberlappung("Block A", "Block B", grund="Presspassung, mit Kevin abgestimmt")\n'
    assert rt.model_write(code)["ok"]
    res = rt.run()
    assert res["ok"] and res["pruefung"]["befunde"] == [] and len(res["pruefung"]["erlaubt"]) == 1
    code2 = MODELL + 'erlaubt_ueberlappung("Block A", "Block B")\n'
    assert rt.model_write(code2)["ok"]
    res2 = rt.run()
    arten = sorted(b["art"] for b in res2["pruefung"]["befunde"])
    assert arten == ["durchdringung", "erklaerung"]


def test_wiederholung_aus_dem_zwischenspeicher(env):
    rt = env["rt"]
    teile_code = HEAD + "\n".join(
        f'show(Pos({(i % 10) * 12}, {(i // 10) * 12}, 0) * Box(10, 10, 10), "Teil {i}", material="pla")'
        for i in range(50)) + '\nshow(Pos(5, 0, 0) * Box(10, 10, 10), "Stoerer", material="pla")\n'
    assert rt.model_write(teile_code)["ok"]
    res = rt.run()
    assert res["ok"] and res["pruefung"]["zusammenfassung"] == "2 Durchdringungen"  # Teil 0 und Teil 1
    res2 = rt.run(params={"x": 1})  # gleicher Stand, neuer Lauf: alle Paare aus dem Zwischenspeicher
    st = res2["pruefung"]["statistik"]
    assert st["paare"]["neu_gerechnet"] == 0
    assert res2["pruefung"]["duration_ms"] < 1000


def test_pruefen_und_ansichten_ueber_die_laufzeit(env):
    rt, app = env["rt"], env["app"]
    assert rt.model_write(MODELL)["ok"]
    res = rt.run()
    pr = rt.pruefen()
    assert pr["ok"] and pr["run"] == res["run"] and pr["zusammenfassung"] == res["pruefung"]["zusammenfassung"]
    assert pr["montage"]["schritte"] and pr["stand"]["gruppen"]
    start = app.mark()
    bilder = rt.ansichten([{"name": "iso", "standard": "iso", "darstellung": "xray"},
                           {"name": "schräg", "richtung": [1, 1, -1], "punkt": [4, 0, 0], "radius": 30}], 320, 200)
    assert bilder["ok"] and [b["name"] for b in bilder["bilder"]] == ["iso", "schräg"]
    reqs = [h for h in app.since(start) if h["type"] == "SCREENSHOT_REQ"]
    assert [r["source"] for r in reqs] == ["offscreen", "offscreen"] and reqs[0]["width"] == 320
    assert reqs[0]["ansicht"]["darstellung"] == "xray" and reqs[1]["ansicht"]["richtung"] == [1, 1, -1]
