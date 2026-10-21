"""Phase 5, Zusammenspiel der Stränge KAM und ANI: Kameras fahren mit animierten Teilen, ihr Körper fährt mit, Video
durch eine benannte Kamera."""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp

from kevcad_kernel.animation import unpack_anim_def
from kevcad_kernel.runner import Runner

MODEL = '''
from build123d import *
from kevcad import animation, lager, show
boden = (Align.CENTER, Align.CENTER, Align.MIN)
show(Pos(0, 0, 100) * Box(600, 400, 50, align=boden), "Wagen/Rahmen")
show(Pos(0, 0, 150) * Box(600, 400, 20, align=boden), "Wagen/Deckel")
fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", fokus=1500, name="FX6")
fx6.an("Wagen/Deckel", punkt=(150, 0, 20 + 20), richtung=(1, 0, 0), bezug="stativ_1_4", lokal=True)
show(fx6.koerper(), "Kamera FX6")
frei = lager.kamera("sony-fx6", objektiv="sony-fe-50-f1.2-gm", format="dci", name="Frei")
frei.setzen((-1500, -1200, 900), blick_auf=(0, 0, 200))
show(frei.koerper(), "Kamera Frei")
fahrt = animation(dauer=2, fps=10, name="Fahrt")
fahrt.bewege("Wagen", nach=(1000, 0, 0), von=0, bis=2)
EXTRA
'''


def _run(tmp: Path, extra: str = "") -> tuple[dict, list[tuple[dict, bytes]]]:
    (tmp / "model.py").write_text(MODEL.replace("EXTRA", extra), encoding="utf-8")
    out: list[tuple[dict, bytes]] = []
    res = Runner(lambda h, p: out.append((h, p))).run({"run": 1, "path": str(tmp / "model.py"), "inventar_regel": False})
    return res, out


def _anim(out: list[tuple[dict, bytes]], name: str) -> dict:
    for h, p in out:
        if h.get("type") == "ANIM" and h["def"]["name"] == name:
            app_len = int(h.get("app_len", len(p)))
            return unpack_anim_def(h["def"], p[:app_len])
    raise AssertionError(f"keine Animation {name}")


def test_camera_follows_part_and_body_rides_along(tmp_path):
    res, out = _run(tmp_path)
    assert res["type"] == "RUN_DONE", res.get("error")
    cams = {c["name"]: c for c in res["cameras"]}
    assert cams["Kamera/FX6"]["teil"] == "Wagen/Deckel" and cams["Kamera/FX6"]["folgt"] == "Wagen/Deckel"
    # freie Kamera folgt ihrem eigenen Gehäuse
    assert cams["Kamera/Frei"]["teil"] is None and cams["Kamera/Frei"]["folgt"] == "Kamera Frei/Gehäuse"
    a = _anim(out, "Fahrt")
    teile = a["teile"]
    assert "Kamera FX6/Gehäuse" in teile and "Kamera FX6/Objektiv" in teile
    assert not any(t.startswith("Kamera Frei") for t in teile)  # nicht angehängt: steht
    deckel = a["matrices"][:, teile.index("Wagen/Deckel")]
    body = a["matrices"][:, teile.index("Kamera FX6/Gehäuse")]
    assert np.allclose(deckel, body, atol=1e-4)
    assert body[-1, 0, 3] == pytest.approx(1000, abs=1e-3)


def test_explicitly_animated_body_is_left_alone(tmp_path):
    res, out = _run(tmp_path, 'fahrt.bewege("Kamera FX6", nach=(0, 0, 100), von=0, bis=1)')
    assert res["type"] == "RUN_DONE", res.get("error")
    a = _anim(out, "Fahrt")
    body = a["matrices"][:, a["teile"].index("Kamera FX6/Gehäuse")]
    assert body[-1, 0, 3] == pytest.approx(0, abs=1e-3) and body[-1, 2, 3] == pytest.approx(100, abs=1e-3)


@pytest.fixture(scope="module")
def rt_app():
    from kevcad_kernel.runtime import KernelRuntime

    tmp = Path(tempfile.mkdtemp(prefix="kcka", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = KernelRuntime(sock, 47996, auto_run=False, run_timeout_s=90)
    assert rt.wait_worker_ready(240)
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    proj = tmp / "Kamerafahrt"
    assert rt.project_new(str(proj), "empty")["ok"]
    (proj / "kevcad.json").write_text('{"version": 1, "inventar_regel": false}', encoding="utf-8")
    yield rt, app, proj
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_video_through_named_camera(rt_app):
    rt, app, proj = rt_app
    assert rt.model_write(MODEL.replace("EXTRA", ""))["ok"]
    res = rt.run()
    assert res["ok"], res.get("error")
    assert res["animationen"][0]["kameras"] == ["FX6"]
    assert rt.animation_list()["animationen"][0]["kameras"] == ["FX6"]
    stop = threading.Event()
    seen: list[dict] = []

    def answer():
        mark = app.mark()
        while not stop.is_set():
            try:
                i, _, h, _ = app.wait_for(lambda h: h["type"] == "ANIM_VIDEO_REQ", start=mark, timeout=0.5)
            except AssertionError:
                continue
            mark = i + 1
            seen.append(h)
            Path(h["path"]).write_bytes(b"\x00\x00\x00\x18ftypmp42")
            app.send({"type": "ANIM_VIDEO_RES", "reply_to": h["id"], "ok": True, "path": h["path"], "frames": 21,
                      "ms": 500, "message": None, "kamera": h["kamera"] or "Viewer"})

    t = threading.Thread(target=answer, daemon=True)
    t.start()
    try:
        r = rt.animation_video("Fahrt", 1280, kamera="FX6")
        assert r["ok"], r
        assert seen[-1]["kamera"] == "Kamera/FX6" and r["kamera"] == "Kamera/FX6"
        assert (r["width"], r["height"]) == (1280, 720)  # UHD 3840 × 2160
        assert r["path"].endswith("output/animationen/Fahrt_FX6.mp4")
        r = rt.animation_video("Fahrt", 1280, kamera="Frei")  # DCI 4096 × 2160
        assert r["ok"] and r["height"] == 674 and seen[-1]["kamera"] == "Kamera/Frei"
        r = rt.animation_video("Fahrt", 640, kamera="Gibtsnicht")
        assert r["ok"] is False and "FX6" in r["error"]
        r = rt.animation_video("Fahrt", 640)
        assert r["ok"] and r["height"] == 360 and seen[-1]["kamera"] is None
    finally:
        stop.set()
        t.join(2)


# --------------------------------------------------------------------------------------------- Prüfung und Animation

ERLAUBT_MODEL = '''
from build123d import *
from kevcad import animation, erlaubt_ueberlappung, show
show(Box(100, 100, 100), "Block")
show(Pos(300, 0, 0) * Box(100, 100, 100), "Schieber/Platte")
show(Pos(300, 0, 80) * Box(20, 20, 20), "Schieber/Griff")
erlaubt_ueberlappung("Block", "Schieber", grund="Schaumstoff gibt nach")
erlaubt_ueberlappung("Block", "Schieber/Platte")  # ohne Grund: gilt nicht
fahrt = animation(dauer=1, fps=4, name="Fahrt")
fahrt.bewege("Schieber", nach=(-250, 0, 0), von=0, bis=1)
'''


def test_pruef_allowance_counts_in_animation(tmp_path):
    """Eine in der Prüfung erlaubte Überlappung (erlaubt_ueberlappung mit Grund) zählt in der Animation nicht als
    Kollision: sie steht wie anim.erlaube im Kopf der Animation."""
    (tmp_path / "model.py").write_text(ERLAUBT_MODEL, encoding="utf-8")
    out: list[tuple[dict, bytes]] = []
    res = Runner(lambda h, p: out.append((h, p))).run({"run": 1, "path": str(tmp_path / "model.py"),
                                                       "inventar_regel": False})
    assert res["type"] == "RUN_DONE", res.get("error")
    head = next(h for h, _ in out if h.get("type") == "ANIM")
    # nur die Erlaubnis mit Grund; Gruppe „Schieber“ = alle Teile darunter
    assert head["erlaubt"] == [[["Block"], ["Schieber/Platte", "Schieber/Griff"]]]
