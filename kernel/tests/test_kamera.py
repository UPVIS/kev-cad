"""Kameras (Phase 5, Strang KAM): Katalog, Optik-Rechnung, lager.kamera, Zubehör, Rechenprozess, Laufzeit, Protokoll
und MCP-Werkzeuge."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import threading
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp
from fake_service import PNG, FakeService
from mcp_testutil import start_server, texts, with_client

from kevcad import lager
from kevcad.kamera import KameraError, basis
from kevcad_kernel.catalog import Catalog, validate_item
from kevcad_kernel.optik import bildwinkel, coc_fuer, format_von, hyperfokal, schaerfentiefe
from kevcad_kernel.protocol import FrameReader
from kevcad_kernel.runner import Runner, split_parts

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[1] / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# --------------------------------------------------------------------------------------------------------- Katalog


def test_catalog_loads_cameras_lenses_and_accessories_without_warnings():
    cat = Catalog()
    cat.refresh(force=True)
    assert not [w for w in cat.warnings if "kamera" in w.lower() or "objektiv" in w.lower()]
    assert [i["id"] for i in cat.items("kamera")] == ["sony-fx6"]
    lenses = {i["id"] for i in cat.items("objektiv")}
    assert {"sony-fe-24-105-f4-g-oss", "sony-fe-16-35-f2.8-gm-ii", "sony-fe-50-f1.2-gm", "sigma-ff-hs-24-t1.5-e",
            "sigma-ff-hs-35-t1.5-e", "sigma-ff-hs-50-t1.5-e", "sigma-ff-hs-85-t1.5-e", "fujinon-mk-18-55-t2.9-e",
            "sigma-18-35-t2-e", "dzofilm-catta-35-80-t2.9-e"} <= lenses
    zub = {i["id"] for i in cat.items("kamerazubehoer")}
    assert {"tilta-es-t20-qrbp", "lws-stange-15x150", "arri-rosette-31.8", "idx-duo-c98p"} <= zub
    fx6 = cat.item("sony-fx6")
    assert fx6["auflagemass"] == 18.0 and fx6["gewicht"] == 890
    assert fx6["gehaeuse"]["achse_hoehe"] == 74 and fx6["gehaeuse"]["achse_seitlich"] == 5.8
    assert {f["id"] for f in fx6["formate"]} == {"ff-uhd", "ff-uhd-120", "ff-dci", "ff-hd", "s35-hd"}
    assert fx6["quellen"] and all(isinstance(q, str) for q in fx6["quellen"])
    assert [h["id"] for h in cat.search("fx6", art="kamera")[0]] == ["sony-fx6"]


def test_validation_of_camera_entries():
    ok = {"id": "k", "art": "kamera", "name": "K", "hersteller": "X", "modell": "Y", "bajonett": "sony-e",
          "auflagemass": 18, "gehaeuse": {"b": 1, "h": 1, "t": 1},
          "formate": [{"id": "a", "name": "A", "sensor_mm": [36, 24], "aufloesung": [6000, 4000]}]}
    assert validate_item(ok, None, deep=False) == []
    bad = dict(ok, formate=[{"id": "A b", "name": "", "sensor_mm": [360, 0], "aufloesung": [1.5, 2]}],
               standard_format="z", auflagemass=0)
    errors = " ".join(validate_item(bad, None, deep=False))
    for needle in ("auflagemass", "gültige id", "sensor_mm", "aufloesung", "standard_format"):
        assert needle in errors, needle
    lens = {"id": "o", "art": "objektiv", "name": "O", "hersteller": "X", "bajonett": "sony-e", "brennweite": [50, 24],
            "lichtstaerke": 0.1, "naheinstellgrenze": 300, "bildkreis": 43.3, "laenge": 100, "frontdurchmesser": 80,
            "bezugspunkte": {"Front": {"pos": [1, 2]}}, "geometrie": {"funktion": "x"}}
    errors = " ".join(validate_item(lens, None, deep=False))
    for needle in ("brennweite", "lichtstaerke", "Bezugspunkt 'Front'", "pos", "geometrie"):
        assert needle in errors, needle
    zub = {"id": "z", "art": "kamerazubehoer", "name": "Z", "typ": "laser", "masse": {"x": 1}}
    errors = " ".join(validate_item(zub, None, deep=False))
    assert "typ 'laser'" in errors and "masse.x" in errors


# --------------------------------------------------------------------------------------------------------- Optik


def test_angle_of_view_fx6_full_frame_uhd_35mm():
    fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd")
    # Nachgerechnet: 2 · atan(35,7 / 70) = 54,04°; Höhe 35,7 · 2160 / 3840 = 20,08 mm → 2 · atan(20,08 / 70) = 32,02°.
    # Sigma nennt 54,4° für das 35-mm-Objektiv an 36 mm Breite.
    assert fx6.bildwinkel_h == pytest.approx(math.degrees(2 * math.atan(35.7 / 70)))
    assert fx6.bildwinkel_h == pytest.approx(54.04, abs=0.01)
    assert fx6.sensor_mm == pytest.approx((35.7, 35.7 * 2160 / 3840))
    assert fx6.bildwinkel_v == pytest.approx(math.degrees(2 * math.atan(35.7 * 2160 / 3840 / 70)))
    assert fx6.bildwinkel_v == pytest.approx(32.02, abs=0.01)
    assert fx6.format["sensor_mm_katalog"] == [35.7, 20.1]
    assert bildwinkel(36.0, 35.0) == pytest.approx(54.43, abs=0.01)
    assert fx6.seitenverhaeltnis == pytest.approx(16 / 9)
    dci = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="dci")
    assert dci.format["id"] == "ff-dci" and dci.aufloesung == (4096, 2160)
    assert dci.bildwinkel_h == pytest.approx(fx6.bildwinkel_h)
    s35 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="s35")
    assert s35.format["id"] == "s35-hd" and s35.bildwinkel_h == pytest.approx(2 * math.degrees(math.atan(23.8 / 70)))
    zoom = lager.kamera("sony-fx6", objektiv="sony-fe-24-105-f4-g-oss", brennweite=70)
    assert zoom.bildwinkel_h == pytest.approx(2 * math.degrees(math.atan(35.7 / 140)))


def test_depth_of_field_against_formula():
    f, n, c, s = 35.0, 2.8, 0.027, 1500.0
    h = f * f / (n * c) + f
    near = s * (h - f) / (h + s - 2 * f)
    far = s * (h - f) / (h - s)
    assert hyperfokal(f, n, c) == pytest.approx(h)
    assert schaerfentiefe(f, n, c, s) == pytest.approx((near, far))
    fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", blende=2.8, fokus=1500)
    assert fx6.zerstreuungskreis == 0.027
    assert (fx6.schaerfe_nah, fx6.schaerfe_fern) == pytest.approx((near, far))
    assert fx6.schaerfe_nah == pytest.approx(1375.6, abs=0.1) and fx6.schaerfe_fern == pytest.approx(1649.1, abs=0.1)
    # Auf die hyperfokale Distanz fokussiert: scharf von H/2 (genauer (H - f) / 2 + …) bis unendlich
    hn, hf = schaerfentiefe(f, n, c, h)
    assert math.isinf(hf) and hn == pytest.approx(h * (h - f) / (2 * h - 2 * f))
    assert schaerfentiefe(f, n, c, math.inf) == (pytest.approx(h), math.inf)
    assert coc_fuer((35.7, 20.1)) == 0.027


def test_lens_and_format_checks():
    with pytest.raises(KameraError, match="öffnet nur bis T1,5"):
        lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", blende=1.2)
    with pytest.raises(KameraError, match="außerhalb des Zoombereichs 24 bis 105"):
        lager.kamera("sony-fx6", objektiv="sony-fe-24-105-f4-g-oss", brennweite=200)
    with pytest.raises(KameraError, match="Festbrennweite mit 35 mm"):
        lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", brennweite=50)
    with pytest.raises(KameraError, match="Formate: ff-uhd"):
        lager.kamera("sony-fx6", format="8k", brennweite=35)
    with pytest.raises(KameraError, match="nicht eindeutig"):
        lager.kamera("sony-fx6", objektiv="sigma 35")
    with pytest.raises(KameraError, match="ohne Objektiv brennweite"):
        lager.kamera("sony-fx6")
    ideal = lager.kamera("sony-fx6", brennweite=40)
    assert ideal.objektiv is None and ideal.blende == 2.8
    # Standardblende: 2,8, bei lichtschwächeren Objektiven deren Lichtstärke
    assert lager.kamera("sony-fx6", objektiv="sony-fe-24-105-f4-g-oss", brennweite=24).blende == 4.0
    fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-50-t1.5-e")
    assert fx6.blendenart == "t" and fx6.blende == 2.8
    assert format_von(fx6.eintrag, None)["id"] == "ff-uhd"


def test_super35_lens_vignettes_on_full_frame_only():
    mk_ff = lager.kamera("sony-fx6", objektiv="fujinon-mk-18-55-t2.9-e", brennweite=35)
    assert mk_ff.nachricht()["vignettierung"] is True
    mk_s35 = lager.kamera("sony-fx6", objektiv="fujinon-mk-18-55-t2.9-e", brennweite=35, format="s35")
    assert mk_s35.nachricht()["vignettierung"] is False


# --------------------------------------------------------------------------------------------------------- Lage


def test_pose_look_at_bezug_and_roll():
    fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", name="FX6")
    fx6.setzen((0, 0, 100), blick_auf=(1000, 0, 100))
    assert close(fx6.blick, (1, 0, 0)) and close(fx6.rechts, (0, -1, 0)) and close(fx6.oben, (0, 0, 1))
    assert close(fx6.auge, (35, 0, 100))
    assert fx6.fokus == pytest.approx(1000)  # ohne fokus: Entfernung zum Blickpunkt
    m = fx6.lage()
    assert close(m[0:3], (0, -1, 0)) and close(m[4:7], (0, 0, 1)) and close(m[8:11], (-1, 0, 0))
    assert close(m[12:15], (0, 0, 100)) and m[15] == 1
    fx6.setzen((0, 0, 100), richtung=(1, 0, 0), bezug="bajonett")
    assert close(fx6.position, (-18, 0, 100))
    # Stativgewinde: 33 hinter der Front, Front bündig mit der Auflage (18 vor dem Sensor), 74 unter der Bildachse
    p = fx6.bezugspunkt("stativ_1_4").position
    assert close((p.X, p.Y, p.Z), (-18 + 18 - 33, 0, 100 - 74))
    fx6.setzen((500, 0, 0), richtung=(1, 0, 0), bezug="stativ_1_4")
    assert close(fx6.position, (500 + 15, 0, 74))
    d, r, o = basis((1, 0, 0), roll=90)  # im Uhrzeigersinn von hinten: oben zeigt nach rechts (−y), rechts nach unten
    assert close(d, (1, 0, 0)) and close(o, (0, -1, 0)) and close(r, (0, 0, -1))
    up = lager.kamera("sony-fx6", brennweite=20).setzen((0, 0, 0), richtung=(0, 0, 1))
    assert close(up.blick, (0, 0, 1)) and abs(sum(a * b for a, b in zip(up.oben, up.blick))) < 1e-9
    with pytest.raises(KameraError, match="Bezugspunkt 'stativ'"):
        fx6.setzen((0, 0, 0), bezug="stativ")


def test_body_follows_camera_and_accessory_mates_reference_points():
    fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e").setzen((0, 0, 100), richtung=(1, 0, 0))
    k = fx6.koerper()
    kids = {c.label: c.bounding_box() for c in k.children}
    geh, obj = kids["Gehäuse"], kids["Objektiv"]
    # Front bündig mit der Auflage; der E-Mount-Ring endet an der Auflage, auf der das Objektiv sitzt
    assert geh.max.X == pytest.approx(18)
    teile = {c.label: c for c in k.children}
    assert (teile["Gehäuse"] & teile["Objektiv"]).volume == pytest.approx(0, abs=1e-3)  # Prüfung: keine Durchdringung
    assert geh.min.Z == pytest.approx(100 - 74) and geh.max.Z == pytest.approx(100 - 74 + 116)
    assert geh.max.Y == pytest.approx(62.8, abs=0.01) and geh.min.Y == pytest.approx(-51.2, abs=0.01)
    assert obj.min.X == pytest.approx(18, abs=0.01) and obj.max.X == pytest.approx(18 + 121, abs=0.01)
    assert obj.max.Y - obj.min.Y == pytest.approx(95, abs=0.01)
    platte = lager.kamerazubehoer("tilta-es-t20-qrbp")
    plate = platte.verbauen("Rig/Baseplate", an=fx6.bezugspunkt("stativ_1_4"), bezug="kamera_1_4")
    assert plate.bounding_box().max.Z == pytest.approx(26, abs=0.01)  # liegt unter der Kamera
    links = platte.bezugspunkt("lws_links").position
    assert close((links.X, links.Y, links.Z), (-15, 30, 26 - 11))  # 85 unter der Bildachse
    stange = lager.kamerazubehoer("lws-stange-15x150").verbauen("Rig/Stange", an=platte.bezugspunkt("lws_links"),
                                                                bezug="hinten")
    bb = stange.bounding_box()
    assert bb.min.X == pytest.approx(-15) and bb.max.X == pytest.approx(135) and bb.size.Y == pytest.approx(15)
    assert (stange & plate).volume == pytest.approx(0, abs=1e-3)  # Stange steckt in der Bohrung der Baseplate


def test_split_parts_keeps_location_of_moved_compound():
    from build123d import Box, Compound, Pos

    a = Box(10, 10, 10)
    a.label = "A"
    b = Pos(20, 0, 0) * Box(5, 5, 5)
    b.label = "B"
    moved = Pos(100, 0, 0) * Compound(children=[a, b])
    centers = {n: s.bounding_box().center().X for n, s, _ in split_parts(moved, "G")}
    assert centers == {"G/A": pytest.approx(100), "G/B": pytest.approx(120)}


# --------------------------------------------------------------------------------------------------------- Rechenprozess

MODEL = '''
from build123d import *
from kevcad import lager, show, step, param
x = param("x", 0)
show(lager.druckteil(Pos(x, 0, 0) * Box(600, 400, 150, align=(Align.CENTER, Align.CENTER, Align.MIN)), "Wagen",
                     material="petg"), "Wagen")
fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", blende=2.8, fokus=1500, name="FX6")
fx6.an("Wagen", punkt=(250, 0, 150 + 74 + 11), richtung=(1, 0, 0), bezug="sensor", lokal=True)
show(fx6.koerper(), "Kamera FX6")
platte = lager.kamerazubehoer("tilta-es-t20-qrbp")
show(platte.verbauen("Rig/Baseplate", an=fx6.bezugspunkt("stativ_1_4"), bezug="kamera_1_4"), "Rig/Baseplate")
b = lager.kamera("sony-fx6", objektiv="sony-fe-24-105-f4-g-oss", brennweite=50, name="B")
b.setzen((x - 1000, 800, 1200), blick_auf=(x + 1200, 0, 108))
'''


@pytest.fixture(scope="module")
def runner_tmp():
    tmp = Path(tempfile.mkdtemp(prefix="kckam"))
    (tmp / "model.py").write_text(MODEL, encoding="utf-8")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path, x: float) -> dict:
    out: list = []
    res = Runner(lambda h, p: out.append(h)).run({"run": 1, "path": str(tmp / "model.py"), "params": {"x": x},
                                                  "inventar_regel": True})
    assert res["type"] == "RUN_DONE", res.get("error")
    return res


def test_camera_on_part_follows_part_and_counts_as_inventory(runner_tmp):
    r0, r1 = _run(runner_tmp, 0), _run(runner_tmp, 500)
    c0 = {c["name"]: c for c in r0["cameras"]}
    c1 = {c["name"]: c for c in r1["cameras"]}
    assert set(c0) == {"Kamera/FX6", "Kamera/B"}
    assert c0["Kamera/FX6"]["sensor_pos"] == [250.0, 0.0, 235.0] and c1["Kamera/FX6"]["sensor_pos"] == [750.0, 0.0,
                                                                                                       235.0]
    assert c0["Kamera/FX6"]["teil"] == "Wagen" and c0["Kamera/FX6"]["ausblenden"] == ["Kamera FX6/Objektiv"]
    assert c0["Kamera/FX6"]["schaerfe_nah"] == pytest.approx(1375.628, abs=0.01)
    assert c0["Kamera/B"]["fokus"] == pytest.approx(math.dist((-1000, 800, 1200), (1200, 0, 108)), abs=0.01)
    assert r0["inventar_verstoesse"] == []
    lines = {line["benennung"]: line for line in r0["bom"]["lines"]}
    fx6_line = lines["Sony FX6 (ILME-FX6V)"]
    assert fx6_line["art"] == "kamera" and fx6_line["kg"] == 0.89 and fx6_line["teile"] == ["Kamera FX6/Gehäuse"]
    assert fx6_line["masse_text"] == "114 × 116 × 153 mm"
    assert lines["Sigma 35 mm T1,5 FF High Speed Prime (E-Mount)"]["masse_text"] == "35 mm T1,5"
    assert lines["Tilta Schnellwechsel-Baseplate für Sony FX6 (ES-T20-QRBP)"]["kg"] == 0.435


def test_camera_without_pose_and_missing_part_warn(tmp_path):
    (tmp_path / "model.py").write_text(
        "from kevcad import lager\n"
        "a = lager.kamera('sony-fx6', brennweite=35, name='A')\n"
        "b = lager.kamera('sony-fx6', brennweite=35, name='B').an('Gibt es nicht', lokal=True)\n", encoding="utf-8")
    res = Runner(lambda h, p: None).run({"run": 1, "path": str(tmp_path / "model.py"), "inventar_regel": True})
    text = " ".join(res["warnings"])
    assert "Kamera A: keine Lage" in text and "Gibt es nicht" in text


# --------------------------------------------------------------------------------------------------------- Laufzeit


@pytest.fixture(scope="module")
def rt_app():
    from kevcad_kernel.runtime import KernelRuntime

    tmp = Path(tempfile.mkdtemp(prefix="kcr", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = KernelRuntime(sock, 47998, auto_run=False, run_timeout_s=90)
    assert rt.wait_worker_ready(240)
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    proj = tmp / "Kamerawagen"
    assert rt.project_new(str(proj), "empty")["ok"]
    (proj / "kevcad.json").write_text('{"version": 1, "inventar_regel": false}', encoding="utf-8")
    yield rt, app, proj, sock
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_runtime_sends_cameras_and_renders_camera_images(rt_app):
    rt, app, proj, sock = rt_app
    assert rt.model_write(MODEL)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    assert any("FX6" in k for k in res["kameras"])
    app.wait_for(lambda h: h["type"] == "RUN_END", start=start)
    heads = [h for h in app.since(start) if h["type"] in ("CAMERA_UPSERT", "RUN_END")]
    assert [h["type"] for h in heads][-1] == "RUN_END"
    names = {h["name"] for h in heads if h["type"] == "CAMERA_UPSERT"}
    assert names == {"Kamera/FX6", "Kamera/B"}
    assert {c["name"] for c in rt.cameras()["cameras"]} == names
    assert rt.camera_info("fx6")["camera"]["kurzname"] == "FX6"
    assert rt.camera_info("C")["ok"] is False

    # Kamerabild: Höhe aus dem Seitenverhältnis, Datei unter output/kameras
    start = app.mark()
    img = rt.camera_image("FX6", width=3840)
    assert img["ok"], img
    req = next(h for h in app.since(start) if h["type"] == "SCREENSHOT_REQ")
    assert req["source"] == "camera" and req["camera"] == "Kamera/FX6" and (req["width"], req["height"]) == (3840, 2160)
    path = Path(img["file"])
    assert path.parent == (proj / "output" / "kameras").resolve() and path.read_bytes().startswith(b"\x89PNG")
    assert "png" not in img
    assert rt.camera_image("FX6", width=1920, save=False)["png"].startswith(b"\x89PNG")

    # Blick durch die Kamera und zurück
    start = app.mark()
    assert rt.camera_view("FX6")["ok"]
    assert rt.camera_view(None)["ok"]
    cmds = [h for h in app.since(start) if h["type"] == "VIEW_CMD"]
    assert [c["args"]["name"] for c in cmds] == ["Kamera/FX6", None]

    # Vorschlag aus der App: auf VIEW_CMD camera_suggest schickt die App CAMERA_SUGGEST (hier ein Hilfsfaden)
    suggest = {"type": "CAMERA_SUGGEST", "name": "Kamera/FX6", "sensor_pos": [10, 20, 30], "auge": [45, 20, 30],
               "blick": [1, 0, 0], "oben": [0, 0, 1], "rechts": [0, -1, 0], "roll": 0}
    start = app.mark()

    def answer():
        app.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "camera_suggest", start=start)
        app.send(suggest)

    helper = threading.Thread(target=answer, daemon=True)
    helper.start()
    sug = rt.camera_suggestion("FX6")
    helper.join(5)
    assert sug["ok"] and sug["code"].startswith("fx6.setzen((10, 20, 30), richtung=(1, 0, 0))")
    assert "vorschlag_code" in rt.camera_info("FX6")

    # Neue Verbindung bekommt die Kameras, eine weggefallene Kamera wird entfernt
    app2 = FakeApp(sock)
    app2.wait_for(lambda h: h["type"] == "CAMERA_UPSERT" and h["name"] == "Kamera/B")
    start = app2.mark()
    assert rt.model_write(MODEL.replace('name="B"', 'name="C"'))["ok"]
    assert rt.run()["ok"]
    seen = app2.since(start)
    assert {"type": "CAMERA_REMOVE", "name": "Kamera/B"}.items() <= next(
        h for h in seen if h["type"] == "CAMERA_REMOVE").items()
    assert any(h["type"] == "CAMERA_UPSERT" and h["name"] == "Kamera/C" for h in seen)
    app2.close()


# --------------------------------------------------------------------------------------------------------- Protokoll


def test_camera_fixtures_roundtrip():
    expected = json.loads((FIXTURES / "camera_fixtures.json").read_text(encoding="utf-8"))
    for name, header in expected.items():
        (got, payload), = FrameReader().feed((FIXTURES / f"{name}.frame").read_bytes())
        assert got == header and payload == b""
    up = expected["camera_upsert"]
    assert up["bildwinkel_h"] == pytest.approx(54.043, abs=0.001) and up["aufloesung"] == [3840, 2160]
    m = up["lage"]
    assert close(m[8:11], [-v for v in up["blick"]]) and close(m[12:15], up["sensor_pos"])
    assert expected["camera_upsert_b"]["fokus"] is None and expected["camera_upsert_b"]["schaerfe_fern"] is None


# --------------------------------------------------------------------------------------------------------- MCP

CAM = json.loads((FIXTURES / "camera_fixtures.json").read_text(encoding="utf-8"))["camera_upsert"]


class CameraFake(FakeService):
    def cameras(self):
        self.calls.append(("cameras",))
        return {"ok": True, "cameras": [dict(CAM, vorschlag=None)]}

    def camera_info(self, name):
        self.calls.append(("camera_info", name))
        if name not in ("FX6", "Kamera/FX6"):
            return {"ok": False, "error": f"Kamera {name!r} gibt es nicht. Vorhanden: FX6"}
        return {"ok": True, "camera": CAM, "vorschlag": None}

    def camera_view(self, name, timeout_s=10):
        self.calls.append(("camera_view", name))
        return {"ok": True}

    def camera_image(self, name, width=1920, save=True, return_png=False, overlays=False, timeout_s=60):
        self.calls.append(("camera_image", name, width, save, return_png, overlays))
        out = {"ok": True, "name": "Kamera/FX6", "width": width, "height": round(width * 9 / 16), "kamera": CAM,
               "file": "/tmp/x/output/kameras/FX6_35mm.png" if save else None}
        if return_png or not save:
            out["png"] = PNG
        return out

    def camera_catalog(self, query="", art=None, limit=40):
        self.calls.append(("camera_catalog", query, art))
        cat = Catalog()
        items = [cat.item("sony-fx6"), cat.item("sigma-ff-hs-35-t1.5-e"), cat.item("tilta-es-t20-qrbp")]
        return {"ok": True, "items": items, "total": 3}

    def camera_suggestion(self, name="", timeout_s=10):
        self.calls.append(("camera_suggestion", name))
        return {"ok": True, "name": "Kamera/FX6", "code": "fx6.setzen((1, 2, 3), richtung=(1, 0, 0))"}


@pytest.fixture
def srv():
    server, fake = start_server(CameraFake())
    yield server, fake
    server.stop_thread()


def call(url, name, args=None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_mcp_camera_tools(srv):
    server, fake = srv
    res = call(server.url, "kamera_liste")
    assert not res.is_error and texts(res)[0].startswith("1 Kamera:\n- FX6 · Sony FX6 (ILME-FX6V) · Sigma 35 mm")
    assert "Bildwinkel 54,0° × 32,0°" in texts(res)[0] and "an Wagen" in texts(res)[0]
    res = call(server.url, "kamera_info", {"name": "FX6"})
    assert "Bildwinkel horizontal 54,04°" in texts(res)[0] and "Schärfe 1,38 m bis 1,65 m" in texts(res)[0]
    assert call(server.url, "kamera_info", {"name": "X"}).is_error
    res = call(server.url, "kamera_ansicht", {"name": "FX6"})
    assert texts(res)[0].startswith("Viewer zeigt den Blick durch FX6") and fake.calls[-1] == ("camera_view", "FX6")
    call(server.url, "kamera_ansicht", {"name": "aus"})
    assert fake.calls[-1] == ("camera_view", None)
    # Kamerabild: Standard nur speichern und Pfad nennen, kein Bild im Ergebnis
    res = call(server.url, "kamera_bild", {"name": "FX6", "breite": 3840})
    assert fake.calls[-1] == ("camera_image", "FX6", 3840, True, False, False)
    assert not [c for c in res.content if c.type == "image"]
    assert "Gespeichert: /tmp/x/output/kameras/FX6_35mm.png" in texts(res)[0]
    res = call(server.url, "kamera_bild", {"name": "FX6", "bild_zeigen": True})
    assert [c for c in res.content if c.type == "image"]
    res = call(server.url, "kamera_katalog", {"suche": "fx6"})
    text = texts(res)[0]
    assert "sony-fx6: Sony FX6 (ILME-FX6V) · Bajonett sony-e · Formate: ff-uhd" in text
    assert "sigma-ff-hs-35-t1.5-e" in text and "Bezugspunkte kamera_1_4, lws_links, lws_rechts" in text
    res = call(server.url, "kamera_vorschlag_aus_ansicht", {"name": "FX6"})
    assert "fx6.setzen((1, 2, 3)" in texts(res)[0]
