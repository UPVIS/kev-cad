"""Druckvorschau mit Bambu Studio (DRUCKVORSCHAU.md): Profile, Slicen einer Gruppe, Abgleich, genaue Anordnung,
Platten und 3MF-Export als Bambu-Projekt (nachgeslict wie in der Vorschau). Nur mit /Applications/BambuStudio.app
(auf dem Mac mini übersprungen)."""

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.druck import slicer as sl

pytestmark = pytest.mark.skipif(not sl.verfuegbar(), reason="Bambu Studio nicht installiert")

HEAD = "from build123d import *\nfrom kevcad import lager, show, param\n"
CODE = HEAD + """
winkel = Box(40, 20, 4, align=(Align.MIN, Align.MIN, Align.MIN)) + Box(4, 20, 30, align=(Align.MIN, Align.MIN, Align.MIN))
winkel -= Pos(20, 10, 0) * Cylinder(2.5, 10)
for i in range(4):
    show(Pos(i * 60, 0, 0) * lager.druckteil(winkel, f"Winkel {i}", material="petg", zweck="tragend"), f"Halter/Winkel {i}")
show(Pos(0, 80, 0) * lager.druckteil(Box(30, 30, 6), "Deckel", material="petg", zweck="zier", anzahl=2), "Deckel")
"""


def test_profile_aufgeloest():
    assert sl.filament_name("petg") == "Bambu PETG Basic @BBL X1C"
    assert sl.filament_name("pla") in ("Amazon Basics PLA", "Bambu PLA Basic @BBL P1P")
    assert sl.prozess_name(0.16) == "0.16mm Optimal @BBL P1P"
    name, p = sl.prozess_profil({"schicht_mm": 0.2, "waende": 4, "fuellung": 0.25, "muster": "gyroid",
                                 "stuetzen": "baum", "brim": True})
    assert name == "0.20mm Standard @BBL P1P" and "inherits" not in p
    assert (p["wall_loops"], p["sparse_infill_density"], p["sparse_infill_pattern"]) == ("4", "25%", "gyroid")
    assert (p["enable_support"], p["support_type"], p["brim_type"]) == ("1", "tree(auto)", "outer_only")
    m = sl.maschinen_profil()
    assert m["printable_area"] == ["0x0", "256x0", "256x256", "0x256"] and m["bed_exclude_area"][2] == "18x28"
    assert sl.version()


@pytest.fixture(scope="module")
def env():
    alt = {k: os.environ.get(k) for k in ("KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH")}
    tmp = Path(tempfile.mkdtemp(prefix="kcds", dir=tempfile.gettempdir()))
    os.environ.update({"KEVCAD_DRUCK_CACHE": str(tmp / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(tmp / "abgleich.json")})
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


def test_slicer_im_hintergrund_und_export(env):
    rt, app, tmp = env["rt"], env["app"], env["tmp"]
    assert rt.project_new(str(tmp / "Slicer"), "empty")["ok"]
    assert rt.model_write(CODE)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    _, _, erst, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h["run"] == res["run"], start=start)
    assert erst["stand"] == "schaetzung" and erst["slicer"]["zustand"] in ("wartet", "rechnet")
    _, _, v, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h["slicer"]["zustand"] in ("fertig", "fehler"),
                              start=start, timeout=300)
    assert v["slicer"]["zustand"] == "fertig" and v["slicer"]["meldung"] is None, v["slicer"]
    assert v["stand"] == "slicer" and v["slicer"]["version"]
    for t in v["teile"]:
        assert t["stand"] == "slicer" and t["abweichung"] is not None and abs(t["abweichung"]) < 0.35, t
    assert all(p["anordnung"] == "slicer" and p["stand"] == "slicer" for p in v["platten"])
    assert sum(len(p["teile"]) for p in v["platten"]) == 6
    ab = json.loads((tmp / "abgleich.json").read_text())
    assert any(k.endswith("|petg") for k in ab["faktoren"])
    # Zwischenspeicher: gleicher Stand noch einmal, sofort aus dem Speicher
    start = app.mark()
    res2 = rt.run()
    _, _, v2, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h["run"] == res2["run"]
                               and h["slicer"]["zustand"] == "fertig", start=start, timeout=60)
    assert v2["summe"]["zeit_s"] == v["summe"]["zeit_s"]
    # 3MF als Bambu-Projekt: nachgeslict wie in der Vorschau
    ex = rt.druck_export(str(tmp / "platten.3mf"))
    assert ex["ok"] and ex["geprueft"] and ex["fehler"] is None and ex["pfade"] == [ex["pfad"]], ex
    with zipfile.ZipFile(ex["pfad"]) as z:
        ps = json.loads(z.read("Metadata/project_settings.config"))
        einst = z.read("Metadata/model_settings.config").decode()
    assert ps["printer_settings_id"] == "Bambu Lab P1P 0.4 nozzle"
    assert ps["filament_settings_id"] == ["Bambu PETG Basic @BBL X1C"]
    assert 'key="wall_loops" value="4"' in einst and 'key="sparse_infill_pattern" value="gyroid"' in einst
    aus = tmp / "nachgeslict"
    aus.mkdir()
    r = subprocess.run([str(sl.programm()), "--slice", "0", "--min-save", "--outputdir", str(aus), ex["pfad"]],
                       cwd=str(aus), capture_output=True, text=True, timeout=180)
    for g in aus.glob("*.gcode"):
        g.unlink()
    ergebnis = json.loads((aus / "result.json").read_text())
    assert r.returncode == 0, ergebnis.get("error_string")
    zeiten = [p["total_predication"] for p in ergebnis["sliced_plates"]]
    assert len(zeiten) == len(v["platten"])
    for p, z in zip(v["platten"], zeiten):
        assert abs(z / p["zeit_s"] - 1) < 0.02, (p["zeit_s"], z)
