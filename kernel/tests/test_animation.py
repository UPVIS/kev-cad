"""Phase 5 (Strang ANI): Animation auswerten, Protokoll der Nutzlast, Kollisionsprüfung, Laufzeit und MCP-Werkzeuge."""

import math
import shutil
import tempfile
import threading
from pathlib import Path

import anyio
import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime
from build123d import Box, Pos
from mcp_testutil import start_server, texts, with_client

from kevcad.bewegung import Animation, AnimationError
from kevcad_kernel.anim_kollision import bewegte_paare, pruefe_kollisionen, rotationssymmetrisch, zusammenfassen
from kevcad_kernel.anim_runtime import stored_from_worker, visibility_at
from kevcad_kernel.animation import (
    evaluate,
    evaluate_all,
    pack_anim_def,
    pack_matrices,
    unpack_anim_def,
    unpack_matrices,
    worker_message,
)

ORDER = ["Wagen/Rahmen", "Wagen/Rad 1", "Wagen/Rad 2", "Ball", "Arm", "Kiste"]
BBOX = {
    "Wagen/Rahmen": ([-300, -200, 100], [300, 200, 150]),
    "Wagen/Rad 1": ([-250, 150, 0], [-150, 182, 100]),
    "Wagen/Rad 2": ([150, 150, 0], [250, 182, 100]),
    "Ball": ([400, -100, 0], [600, 100, 200]),
    "Arm": ([0, -10, 200], [300, 10, 220]),
    "Kiste": ([1000, 0, 0], [1100, 100, 100]),
}


def rot_y_deg(m: np.ndarray) -> float:
    """Drehwinkel um +Y aus einer Lage (Grad, -180…180)."""
    return math.degrees(math.atan2(-m[2, 0], m[0, 0]))


def total_angle_deg(mats: np.ndarray) -> float:
    """Aufsummierter Drehwinkel um +Y über alle Bilder (über ±180° hinweg)."""
    ang = [rot_y_deg(m) for m in mats]
    total = 0.0
    for a, b in zip(ang, ang[1:]):
        d = (b - a + 180.0) % 360.0 - 180.0
        total += d
    return total


# ---------------------------------------------------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------------------------------------------------


def test_roll_condition_full_turn_for_circumference():
    """Strecke 314,16 mm bei Radius 50 → 360° (Rollbedingung A2)."""
    a = Animation(dauer=2, fps=30, name="Rollen")
    a.bewege("Wagen", nach=(100 * math.pi, 0, 0), von=0, bis=2)
    a.rolle("Wagen/Rad 1", auf="Wagen", radius=50, achse="y")
    r = evaluate(a, ORDER, BBOX)
    i = r.teile.index("Wagen/Rad 1")
    mats = r.matrices[:, i]
    assert total_angle_deg(mats) == pytest.approx(360.0, abs=1e-6)
    assert np.allclose(mats[-1][:3, :3], np.eye(3), atol=1e-9)  # volle Umdrehung
    # Mitte des Rads fährt mit dem Wagen
    c = np.array([-200, 166, 50, 1.0])
    assert np.allclose((mats[-1] @ c)[:3], [-200 + 100 * math.pi, 166, 50], atol=1e-6)
    # halbe Strecke: 180°
    assert abs(rot_y_deg(mats[30])) == pytest.approx(180.0, abs=1e-6)
    # Rad 2 rollt nicht (keine Spur), fährt aber im Baum mit
    j = r.teile.index("Wagen/Rad 2")
    assert np.allclose(r.matrices[-1, j][:3, :3], np.eye(3)) and r.matrices[-1, j][0, 3] == pytest.approx(100 * math.pi)
    assert "Wagen/Rad 1" in r.spins  # feste Achse: für die Kollision als Drehung um die eigene Achse bekannt


def test_free_roll_ball_and_default_radius():
    a = Animation(dauer=1, fps=10)
    a.bewege("Ball", nach=(0, 2 * math.pi * 100, 0), von=0, bis=1)  # Umfang bei Radius 100 nach +Y
    a.rolle("Ball")  # ohne Radius: halbe Höhe 100, ohne Achse frei
    r = evaluate(a, ORDER, BBOX)
    m = r.matrices[:, r.teile.index("Ball")]
    assert np.allclose(m[-1][:3, :3], np.eye(3), atol=1e-6)  # eine Umdrehung
    q = m[5][:3, :3] @ np.array([0, 0, 1.0])  # halbe Strecke: Oberseite zeigt nach unten
    assert np.allclose(q, [0, 0, -1], atol=1e-6)
    q = m[2][:3, :3] @ np.array([0, 0, 1.0])  # Rollen nach +Y kippt die Oberseite nach +Y
    assert q[1] > 0.5
    assert "Ball" not in r.spins


def test_follow_parent_and_prefix_tree():
    a = Animation(dauer=1, fps=4)
    a.bewege("Wagen", nach=(100, 0, 0))
    a.drehe("Arm", achse=((0, 0, 210), (0, 0, 1)), winkel=90)
    a.folge("Arm", "Wagen")
    a.folge("Kiste", "Arm")
    r = evaluate(a, ORDER, BBOX)
    arm = r.matrices[-1, r.teile.index("Arm")]
    kiste = r.matrices[-1, r.teile.index("Kiste")]
    # Arm: erst um die eigene Achse gedreht, dann mit dem Wagen verschoben
    assert np.allclose(arm @ np.array([300, 0, 210, 1.0]), [100, 300, 210, 1], atol=1e-9)
    # Kiste folgt dem Arm (Drehung um die Armachse plus Wagen)
    assert np.allclose(kiste, arm)
    rahmen = r.matrices[-1, r.teile.index("Wagen/Rahmen")]
    assert np.allclose(rahmen[:3, 3], [100, 0, 0])


def test_follow_cycle_and_unknown_part_errors_have_line():
    a = Animation(dauer=1, fps=4, name="Kreis")
    a.folge("Arm", "Kiste")
    a.folge("Kiste", "Arm")
    with pytest.raises(AnimationError) as exc:
        evaluate(a, ORDER, BBOX)
    assert "Kreis" in str(exc.value) and "→" in str(exc.value)
    b = Animation(dauer=1, fps=4, name="Tippfehler")
    b.bewege("Wagn", nach=(1, 0, 0))
    line = b.spuren[-1].line
    with pytest.raises(AnimationError) as exc:
        evaluate(b, ORDER, BBOX)
    assert exc.value.line == line and exc.value.filename == __file__
    assert "Teil oder Baugruppe 'Wagn' gibt es nicht" in str(exc.value) and "Meinten Sie 'Wagen'" in str(exc.value)


def test_times_outside_duration_and_bad_values_fail_at_call():
    a = Animation(dauer=8, fps=30)
    with pytest.raises(ValueError, match="bis=9 liegt außerhalb der Dauer 0 bis 8 s"):
        a.bewege("Wagen", nach=(1, 0, 0), von=0, bis=9)
    with pytest.raises(ValueError, match="bis=1 liegt vor von=2"):
        a.bewege("Wagen", nach=(1, 0, 0), von=2, bis=1)
    with pytest.raises(ValueError, match="kurve 'zackig' unbekannt"):
        a.drehe("Arm", achse="z", winkel=10, kurve="zackig")
    with pytest.raises(ValueError, match="Richtung"):
        a.drehe("Arm", achse=((0, 0, 0), (0, 0, 0)), winkel=10)
    with pytest.raises(ValueError, match="dauer muss größer als 0"):
        Animation(dauer=0)
    with pytest.raises(ValueError, match="radius muss größer als 0"):
        a.rolle("Ball", radius=-1)


def test_joint_limits_clamp_with_warning_and_slider():
    a = Animation(dauer=4, fps=10, name="Gelenk")
    a.gelenk("Arm", art="dreh", achse=((0, 0, 210), (0, 0, 1)), werte={0: 0, 2: 120, 4: 0}, grenzen=(0, 90),
             kurve="linear")
    a.gelenk("Kiste", art="schub", achse=((0, 0, 0), (1, 0, 0)), werte=[(0, 0), (4, 500)], grenzen=(None, 300),
             kurve="linear", eltern="Arm")
    r = evaluate(a, ORDER, BBOX)
    arm = r.matrices[:, r.teile.index("Arm")]
    winkel = [math.degrees(math.atan2(m[1, 0], m[0, 0])) for m in arm]
    assert max(winkel) == pytest.approx(90.0)  # 120° begrenzt
    assert winkel[10] == pytest.approx(60.0)  # 1 s: 60° (noch unter der Grenze)
    assert any("über der Grenze 90°" in w for w in r.warnungen)
    kiste = r.matrices[:, r.teile.index("Kiste")]
    # Schubweg in Ruhelage längs X, dann mit dem Arm gedreht; am Ende Arm wieder bei 0°, Weg auf 300 begrenzt
    assert np.allclose(kiste[-1][:3, 3], [300, 0, 0], atol=1e-9)
    assert any("Gelenk 'Kiste'" in w and "300 mm" in w for w in r.warnungen)
    assert "Arm" in r.spins  # Drehgelenk um eine Achse


def test_path_polyline_aligned_and_spline():
    a = Animation(dauer=2, fps=10)
    a.pfad("Kiste", punkte=[(0, 0, 0), (100, 0, 0), (100, 100, 0)], ausrichten=True)
    r = evaluate(a, ORDER, BBOX)
    m = r.matrices[:, r.teile.index("Kiste")]
    center = np.array([1050, 50, 50, 1.0])
    assert np.allclose((m[-1] @ center)[:3], [1150, 150, 50], atol=1e-6)  # Mitte fährt die Pfadform nach
    assert np.allclose(m[-1][:3, :3] @ [1, 0, 0], [0, 1, 0], atol=1e-3)  # am Ende längs der Tangente +Y gedreht
    assert np.allclose((m[10] @ center)[:3], [1150, 50, 50], atol=1e-6)  # halbe Bogenlänge = Knick
    b = Animation(dauer=1, fps=50)
    pts = [(0, 0, 0), (100, 50, 0), (200, 0, 0), (300, 50, 0)]
    b.pfad("Kiste", punkte=pts, spline=True, bezug=(1050, 50, 50))
    r = evaluate(b, ORDER, BBOX)
    m = r.matrices[:, r.teile.index("Kiste")]
    traj = np.array([(mm @ np.array([1050, 50, 50, 1.0]))[:3] for mm in m])
    for p in pts:  # Spline geht durch alle Punkte
        assert np.min(np.linalg.norm(traj - np.array(p), axis=1)) < 4.0
    assert np.allclose(traj[0], pts[0]) and np.allclose(traj[-1], pts[-1], atol=1e-6)


def test_visibility_and_camera_keys():
    a = Animation(dauer=2, fps=10)
    a.sichtbar("Wagen", an=False, zeit=1)
    a.sichtbar("Kiste", an=True, zeit=0.5)
    a.bewege("Wagen", nach=(1000, 0, 0))
    a.ansicht(0, lage=(0, -1000, 500), ziel=(0, 0, 0), kurve="linear")
    a.ansicht(2, lage=(0, -1000, 500), ziel=(0, 0, 0), mit="Wagen/Rahmen", bildwinkel=30, kurve="linear")
    r = evaluate(a, ORDER, BBOX)
    head, payload = pack_anim_def(r, 1)
    assert visibility_at(head, "Wagen/Rad 1", 0.9) and not visibility_at(head, "Wagen/Rad 1", 1.0)
    assert not visibility_at(head, "Kiste", 0.4) and visibility_at(head, "Kiste", 0.5)
    assert visibility_at(head, "Ball", 1.5)
    cam = r.kamera
    assert np.allclose(cam[0], [0, -1000, 500, 0, 0, 0, 0])
    assert np.allclose(cam[-1][:6], [1000, -1000, 500, 1000, 0, 0])  # fährt mit dem Rahmen mit
    assert cam[-1][6] == 30 and cam[10][6] == 30  # Bildwinkel nur am Ziel bekannt: ab dort gültig


def test_several_animations_names_and_default():
    a, b = Animation(1, name="Fahrt"), Animation(2, name="Verstellen")
    a.bewege("Wagen", nach=(1, 0, 0))
    b.drehe("Arm", achse="z", winkel=10)
    res = evaluate_all([a, b], ORDER, BBOX)
    assert [x.name for x in res] == ["Fahrt", "Verstellen"] and res[0].standard and not res[1].standard


# ---------------------------------------------------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------------------------------------------------


def test_payload_roundtrip_matrices_and_camera():
    a = Animation(dauer=1, fps=8, name="Rundreise")
    a.bewege("Wagen", nach=(250, -40, 10), kurve="weich")
    a.rolle("Wagen/Rad 1", auf="Wagen", radius=50, achse="y")
    a.drehe("Arm", achse=((10, 0, 210), (0.3, 0.4, 0.866)), winkel=137)
    a.ansicht(0, lage=(1, 2, 3), ziel=(4, 5, 6))
    r = evaluate(a, ORDER, BBOX)
    head, payload = pack_anim_def(r, 9)
    assert head["type"] == "ANIM_DEF" and head["bilder"] == 9 and head["kamera"] is True
    assert len(payload) == 9 * len(r.teile) * 12 * 4 + 9 * 7 * 4
    back = unpack_anim_def(head, payload)
    assert np.allclose(back["matrices"], r.matrices, atol=1e-3)
    assert np.allclose(back["kamera"], r.kamera, atol=1e-4)
    # spaltenweise: die Verschiebung steht in den letzten drei Werten
    vals = np.frombuffer(payload, dtype="<f4", count=12)
    assert np.allclose(vals[9:12], r.matrices[0, 0, :3, 3])
    m = np.random.default_rng(1).normal(size=(3, 2, 4, 4))
    m[:, :, 3] = [0, 0, 0, 1]
    assert np.allclose(unpack_matrices(pack_matrices(m), 3, 2), m, atol=1e-5)
    # Nachricht des Rechenprozesses mit den Angaben für die Kollisionsprüfung
    wh, wp = worker_message(r, 9)
    st = stored_from_worker(wh, wp)
    assert st.name == "Rundreise" and st.payload == payload and st.teile == r.teile
    assert set(st.nospin) == {"Wagen/Rad 1", "Arm"} and np.allclose(st.nospin["Arm"], np.repeat(np.eye(4)[None], 9, 0))
    assert np.allclose(st.matrices, r.matrices, atol=1e-3)


# ---------------------------------------------------------------------------------------------------------------------
# Kollision
# ---------------------------------------------------------------------------------------------------------------------


def _slide(n: int, dx: float) -> np.ndarray:
    m = np.repeat(np.eye(4)[None], n, axis=0)
    m[:, 0, 3] = np.linspace(0, dx, n)
    return m


def test_collision_detected_and_not_detected():
    formen = {"Schieber": Box(100, 100, 100), "Wand": Pos(500, 0, 0) * Box(20, 200, 200)}
    zeiten = np.linspace(0, 2, 21)
    # 380 mm: Vorderkante bei 430, Wand ab 490 → frei
    befunde, stats = pruefe_kollisionen(formen, {"Schieber": _slide(21, 380)}, zeiten)
    assert befunde == [] and stats["paare"] == 1
    # 480 mm: Vorderkante bei 530 → bis 40 mm in der Wand
    befunde, _ = pruefe_kollisionen(formen, {"Schieber": _slide(21, 480)}, zeiten)
    assert befunde and befunde[0].teile == ("Schieber", "Wand")
    first = befunde[0]
    assert first.zeit == pytest.approx(1.9)  # bei 456 mm: 16 mm drin
    assert first.volumen == pytest.approx(16 * 100 * 100, rel=1e-3)
    assert first.tiefe == pytest.approx(16, abs=1e-3)
    assert first.ort[0] == pytest.approx(498, abs=1e-3)
    spans = zusammenfassen(befunde, range(21))
    assert len(spans) == 1 and spans[0]["von"] == pytest.approx(1.9) and spans[0]["bis"] == pytest.approx(2.0)
    assert spans[0]["tiefe"] == pytest.approx(20, abs=1e-3)  # am Ende 40 mm drin, die Wand ist nur 20 dick
    # Berühren ist erlaubt: genau bis an die Wand
    befunde, _ = pruefe_kollisionen(formen, {"Schieber": _slide(21, 440)}, zeiten)
    assert befunde == []


def test_rigid_pairs_are_skipped_and_symmetric_spin_detected():
    from build123d import Cylinder, Rot

    n = 5
    move = _slide(n, 100)
    lagen = {"A": move, "B": move}
    assert bewegte_paare(["A", "B", "C"], lagen, range(n)) == [("A", "C"), ("B", "C")]
    rad = Pos(0, 0, 50) * Rot(90, 0, 0) * Cylinder(50, 30)
    assert rotationssymmetrisch(rad, (0.05, 0, 50.04), (0, 1, 0))  # Punkt leicht neben der Achse (Netz)
    assert not rotationssymmetrisch(Box(10, 20, 30), (0, 0, 0), (0, 0, 1))


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit mit Rechenprozess und Test-App
# ---------------------------------------------------------------------------------------------------------------------

MODEL = '''
from build123d import *
from kevcad import show, step, param, animation
show(Pos(0, 0, 60) * Box(600, 400, 20), "Wagen/Platte")
show(Pos(-200, 0, 50) * Rot(90, 0, 0) * Cylinder(50, 30), "Wagen/Rad")
show(Pos(1200, 0, 100) * Box(100, 100, 200), "Pfosten")
fahrt = animation(dauer=2, fps=15, name="Fahrt")
fahrt.bewege("Wagen", nach=(STRECKE, 0, 0), von=0, bis=2)
fahrt.rolle("Wagen/Rad", auf="Wagen", radius=50, achse="y")
'''


@pytest.fixture(scope="module")
def rt_app():
    tmp = Path(tempfile.mkdtemp(prefix="kca", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    proj = tmp / "Wagen"
    assert rt.project_new(str(proj), "empty")["ok"]
    (proj / "kevcad.json").write_text('{"version": 1, "inventar_regel": false}', encoding="utf-8")
    yield rt, app, proj
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_runtime_sends_anim_def_after_run_end_and_checks_collisions(rt_app):
    rt, app, proj = rt_app
    assert rt.model_write(MODEL.replace("STRECKE", "500"))["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    assert res["animationen"][0]["name"] == "Fahrt" and res["animationen"][0]["bilder"] == 31
    assert res["animationen"][0]["auswertung_ms"] < 1000
    _, _, head, payload = app.wait_for(lambda h: h["type"] == "ANIM_DEF", start=start)
    types = [h["type"] for h in app.since(start) if h["type"] in ("RUN_END", "BOM", "ANIM_DEF")]
    assert types.index("RUN_END") < types.index("ANIM_DEF")
    back = unpack_anim_def(head, payload)
    assert back["teile"] == ["Wagen/Platte", "Wagen/Rad"]
    assert back["matrices"][-1, 0, 0, 3] == pytest.approx(500, abs=1e-3)
    c = rt.collision_check("Fahrt", 3)
    assert c["ok"] and c["kollisionen"] == [] and "Wagen/Rad" in c["geprueft"]["symmetrisch"]
    lst = rt.animation_list()
    assert lst["animationen"][0]["kollisionen"] == 0

    # 1100 mm: die Platte fährt in den Pfosten
    assert rt.model_write(MODEL.replace("STRECKE", "1100"))["ok"]
    assert rt.run()["ok"]
    start = app.mark()
    c = rt.collision_check("Fahrt", 3)
    assert c["ok"]
    pairs = {tuple(k["teile"]) for k in c["kollisionen"]}
    assert ("Pfosten", "Wagen/Platte") in pairs
    k = next(k for k in c["kollisionen"] if k["teile"] == ["Pfosten", "Wagen/Platte"])
    assert 1.0 < k["von"] < 2.0 and k["bis"] == pytest.approx(2.0) and k["tiefe"] > 0
    app.wait_for(lambda h: h["type"] == "ANIM_COLLISIONS" and h["name"] == "Fahrt", start=start)
    # App fragt selbst
    start = app.mark()
    app.send({"type": "ANIM_COLLISIONS_REQ", "id": "a-1", "name": "Fahrt", "schritt": 5})
    _, _, h, _ = app.wait_for(lambda h: h.get("reply_to") == "a-1", start=start)
    assert h["type"] == "ANIM_COLLISIONS" and h["geprueft"]["schritt"] == 5


def test_runtime_error_line_for_unknown_part_and_remove(rt_app):
    rt, app, proj = rt_app
    code = MODEL.replace("STRECKE", "100") + 'fahrt.folge("Pfostn", "Wagen")\n'
    assert rt.model_write(code)["ok"]
    res = rt.run()
    assert res["ok"] is False
    err = res["error"]
    assert err["line"] == code.splitlines().index('fahrt.folge("Pfostn", "Wagen")') + 1
    assert "Teil oder Baugruppe 'Pfostn' gibt es nicht" in err["message"] and "Meinten Sie 'Pfosten'" in err["message"]
    assert ">" in err["excerpt"] and "Pfostn" in err["excerpt"]
    # Animation umbenannt: die alte wird entfernt
    assert rt.model_write(MODEL.replace("STRECKE", "100").replace('name="Fahrt"', 'name="Neu"'))["ok"]
    rt.run()  # Fahrt aus dem letzten guten Lauf
    assert rt.model_write(MODEL.replace("STRECKE", "100"))["ok"]
    assert rt.run()["ok"]
    start = app.mark()
    assert rt.model_write(MODEL.replace("STRECKE", "100").replace('name="Fahrt"', 'name="Neu"'))["ok"]
    assert rt.run()["ok"]
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "ANIM_REMOVE", start=start)
    assert h["name"] == "Fahrt"
    assert [a["name"] for a in rt.animation_list()["animationen"]] == ["Neu"]
    # doppelter Name: Fehler mit Zeile
    dup = MODEL.replace("STRECKE", "100") + 'animation(dauer=1, name="Fahrt")\n'
    assert rt.model_write(dup)["ok"]
    res = rt.run()
    assert res["ok"] is False and "gibt es schon" in res["error"]["message"] and res["error"]["line"]


def test_runtime_play_seek_video_go_to_app(rt_app):
    rt, app, proj = rt_app
    assert rt.model_write(MODEL.replace("STRECKE", "300"))["ok"]
    assert rt.run()["ok"]
    stop = threading.Event()

    def answer():
        seen = app.mark()
        while not stop.is_set():
            try:
                i, _, h, _ = app.wait_for(lambda h: h["type"] in ("ANIM_PLAY", "ANIM_SEEK", "ANIM_VIDEO_REQ"),
                                          start=seen, timeout=0.5)
            except AssertionError:
                continue
            seen = i + 1
            if h["type"] == "ANIM_VIDEO_REQ":
                Path(h["path"]).write_bytes(b"\x00\x00\x00\x18ftypmp42")
                app.send({"type": "ANIM_VIDEO_RES", "reply_to": h["id"], "ok": True, "path": h["path"], "frames": 31,
                          "ms": 900, "message": None, "kamera": "Viewer"})
            else:
                app.send({"type": "ACK", "reply_to": h["id"], "ok": True, "message": h["type"]})

    t = threading.Thread(target=answer, daemon=True)
    t.start()
    try:
        r = rt.animation_play("Fahrt", True, True, 2.0)
        assert r["ok"] and r["schleife"] and r["geschwindigkeit"] == 2.0
        assert rt.animation_play("Gibtsnicht")["ok"] is False
        r = rt.animation_seek(1.0)
        assert r["ok"] and r["bild"] == 15
        assert rt.animation_seek(5.0)["ok"] is False
        app.send({"type": "ANIM_STATE", "name": "Fahrt", "zeit": 1.0, "bild": 15, "spielt": False, "schleife": True,
                  "geschwindigkeit": 2.0})
        r = rt.animation_video("Fahrt", 640)
        assert r["ok"] and r["path"].endswith("output/animationen/Fahrt.mp4") and r["height"] == 360
        assert Path(r["path"]).parent == (proj / "output" / "animationen").resolve()
        assert rt.animation_video("Fahrt", 640, format="avi")["ok"] is False
        assert rt.animation_list()["stand"]["zeit"] == 1.0
    finally:
        stop.set()
        t.join(2)


# ---------------------------------------------------------------------------------------------------------------------
# MCP-Werkzeuge (Attrappe)
# ---------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def srv():
    server, fake = start_server()
    yield server, fake
    server.stop_thread()


def call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_mcp_animation_tools(srv):
    server, fake = srv
    res = call(server.url, "animation_liste")
    text = texts(res)[0]
    assert "1 Animation:" in text and "Fahrt: 8 s, 30 fps (241 Bilder), 12 bewegte Teile, mit Kamerafahrt" in text
    assert "In der App: Fahrt bei 2,5 s (angehalten)" in text
    res = call(server.url, "animation_abspielen", {"schleife": True})
    assert res.is_error is False and "spielt" in texts(res)[0] and "in Schleife" in texts(res)[0]
    assert fake.calls_of("animation_play")[0][0] == (None, True, True, 1.0, False)
    assert call(server.url, "animation_abspielen", {"name": "X"}).is_error is True
    res = call(server.url, "animation_springen", {"zeit": 2})
    assert "bei 2 s (Bild 60)" in texts(res)[0]
    assert call(server.url, "animation_springen", {"zeit": 9}).is_error is True
    res = call(server.url, "animation_video", {"breite": 1280})
    assert texts(res)[0].startswith("Video /tmp/Kev CAD/Wandhalter/output/animationen/Fahrt.mp4 (1280 × 720 px")
    assert fake.calls_of("animation_video")[0][0] == (None, 1280, None, None, None, "mp4")
    res = call(server.url, "kollision_pruefen", {"schritt": 2})
    text = texts(res)[0]
    assert "1 Kollision (jede muss gelöst werden)" in text and "Bowlingball ↔ Pfosten" in text
    assert "Eindringtiefe 12,5 mm" in text and "5,1 s bis 5,6 s" in text
    assert fake.calls_of("collision_check")[0][0] == (None, 2)
