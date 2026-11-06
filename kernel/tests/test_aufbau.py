"""Aufbau-Videos (aufbau.py, Werkzeug aufbau_video): Plan rein gerechnet, dann mit echtem Rechenprozess und App-Attrappe."""

import json
import shutil
import tempfile
import threading
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.animation import unpack_anim_def
from kevcad_kernel.aufbau import AufbauFehler, anheben, plan, schritte_aufloesen

TEILE = ["Drohne/Rahmen/Unterplatte", "Drohne/Rahmen/Arm 1", "Drohne/Rahmen/Arm 2", "Drohne/Motor 1/Glocke",
         "Drohne/Motor 1/Stator", "Drohne/Motor 2/Glocke", "Drohne/GoPro", "Boden"]
HUELLEN = {t: ([i * 10.0, 0.0, 0.0], [100.0 + i * 10, 80.0, 20.0 + i]) for i, t in enumerate(TEILE)}


def test_schritte_automatisch_nach_baugruppen_ohne_gemeinsamen_pfad():
    s = schritte_aufloesen(None, TEILE[:-1])
    assert [x.titel for x in s] == ["Drohne/Rahmen", "Drohne/Motor 1", "Drohne/Motor 2", "Drohne/GoPro"]
    assert s[1].teile == ["Drohne/Motor 1/Glocke", "Drohne/Motor 1/Stator"]
    # Teile ohne Baugruppe einzeln
    assert [x.teile for x in schritte_aufloesen(None, ["A", "B"])] == [["A"], ["B"]]


def test_schritte_mit_praefix_muster_und_rest():
    s = schritte_aufloesen(["Drohne/Motor *", "Drohne/Rahmen/Arm*"], TEILE[:-1])
    assert s[0].teile == ["Drohne/Motor 1/Glocke", "Drohne/Motor 1/Stator", "Drohne/Motor 2/Glocke"]
    assert s[1].teile == ["Drohne/Rahmen/Arm 1", "Drohne/Rahmen/Arm 2"]
    assert s[2].teile == ["Drohne/Rahmen/Unterplatte", "Drohne/GoPro"]  # nicht genannt: zum Schluss
    with pytest.raises(AufbauFehler, match="kein gezeigtes Teil"):
        schritte_aufloesen(["Propeller"], TEILE[:-1])
    with pytest.raises(AufbauFehler, match="schon in früheren"):
        schritte_aufloesen(["Drohne", "Drohne/GoPro"], TEILE[:-1])


def test_zeitplan_endet_mit_halten_und_kulisse_bleibt_draussen():
    p = plan({"dauer": 12, "halten_s": 2}, TEILE, HUELLEN, ausgenommen={"Boden"})
    assert all("Boden" not in s.teile for s in p.schritte)
    assert p.schritte[0].zeit == pytest.approx(0.4)
    assert p.schritte[-1].landet == pytest.approx(12 - 2)
    zeiten = [s.zeit for s in p.schritte]
    assert zeiten == sorted(zeiten)
    assert set(p.versatz) == set(TEILE[:-1]) and all(v == (0, 0, pytest.approx(0.6 * p.radius)) for v in
                                                    p.versatz.values())
    with pytest.raises(AufbauFehler, match="reicht nicht"):
        plan({"dauer": 3, "halten_s": 3}, TEILE, HUELLEN)


def test_feste_landezeiten_auf_schlaegen_und_strich_davor():
    schritte = [{"auf": "Drohne/Rahmen", "landet": 2.78}, "Drohne/Motor 1", {"auf": "Drohne/Motor 2", "landet": 6.46},
                {"auf": "Drohne/GoPro", "landet": 9.68}]
    z = {"vor": "Drohne/GoPro", "punkte": [[0, 0, 30], [50, 0, 30]], "dauer_s": 1.6}
    p = plan({"dauer": 12, "schritte": schritte, "einflug_s": 0.5, "zeichnen": [z]}, TEILE, HUELLEN,
             ausgenommen={"Boden"})
    landet = [round(s.landet, 3) for s in p.schritte]
    assert landet == [2.78, 4.62, 6.46, 9.68]  # ohne Zeit: mitten zwischen den Nachbarn
    assert p.schritte[0].zeit == pytest.approx(2.28)
    st = p.striche[0]
    assert st.bis == pytest.approx(9.68 - 0.5 - 0.25) and st.von == pytest.approx(st.bis - 1.6)
    with pytest.raises(AufbauFehler, match="nicht nach"):
        plan({"dauer": 12, "schritte": [{"auf": "Drohne/Rahmen", "landet": 5}, {"auf": "Drohne/GoPro", "landet": 4}]},
             TEILE, HUELLEN)
    with pytest.raises(AufbauFehler, match="passt nicht vor"):
        plan({"dauer": 12, "schritte": schritte, "zeichnen": [{**z, "von": 9.0}]}, TEILE, HUELLEN)


def test_viele_teile_werden_zusammengelegt():
    teile = [f"Schraube {i}" for i in range(300)]
    huellen = {t: ([i, 0, 0], [i + 1, 1, 1]) for i, t in enumerate(teile)}
    p = plan({"dauer": 6, "halten_s": 1}, teile, huellen)
    assert len(p.schritte) < 300
    assert sum(len(s.teile) for s in p.schritte) == 300
    assert min(b.zeit - a.zeit for a, b in zip(p.schritte, p.schritte[1:])) >= 0.08 - 1e-9


def test_strich_vor_schritt_und_doppelt():
    z = {"vor": "Drohne/GoPro", "punkte": [[0, 0, 30], [50, 0, 30], [50, 40, 30]], "dauer_s": 1.2}
    p = plan({"dauer": 12, "zeichnen": [z]}, TEILE, HUELLEN, ausgenommen={"Boden"})
    st = p.striche[0]
    gopro = next(s for s in p.schritte if s.titel == "Drohne/GoPro")
    assert st.bis == pytest.approx(st.von + 1.2) and gopro.zeit == pytest.approx(st.bis + 0.25)
    assert st.weg == pytest.approx(gopro.landet + 0.35)
    with pytest.raises(AufbauFehler, match="steht schon ein Strich"):
        plan({"dauer": 12, "zeichnen": [z, {**z, "vor": "Drohne/GoPro"}]}, TEILE, HUELLEN)
    with pytest.raises(AufbauFehler, match="passt zu keinem Schritt"):
        plan({"dauer": 12, "zeichnen": [{**z, "vor": "Propeller"}]}, TEILE, HUELLEN)


def test_strich_hebt_sich_durch_die_naechste_flaeche_ab():
    platte = (np.array([-22.0, -50, 7]), np.array([22.0, 50, 9]))
    q = anheben(np.array([0.0, 40, 9]), [platte], 2.0)
    assert q == pytest.approx([0, 40, 11])  # auf der Platte gezeichnet: nach oben
    frei = anheben(np.array([0.0, 80, 30]), [platte], 2.0)
    assert frei == pytest.approx([0, 80, 30])  # weit weg: bleibt


def test_orbit_abstand_konstant_und_schnitt_auf_bildern():
    p = plan({"dauer": 10, "blickwinkel": ["orbit", "iso", "schnitt"], "wechsel_s": 2.5}, TEILE, HUELLEN,
             ausgenommen={"Boden"})
    assert [f.titel for f in p.fahrten] == ["Orbit", "Iso", "Schnitt"]
    mitte = np.asarray(p.mitte)
    orbit = p.fahrten[0].schluessel
    d = [np.linalg.norm(np.asarray(lage) - mitte) for _, lage, _ in orbit]
    assert max(d) - min(d) < 1e-6 and min(d) > p.radius
    az = [np.degrees(np.arctan2(lage[1] - mitte[1], lage[0] - mitte[0])) for _, lage, _ in orbit]
    assert az[0] == pytest.approx(-60) and orbit[-1][0] == pytest.approx(10)
    schnitt = p.fahrten[2]
    assert schnitt.schnitte and all(abs(c * 30 - round(c * 30)) < 1e-9 for c in schnitt.schnitte)
    zeiten = [k[0] for k in schnitt.schluessel]
    assert all(b > a for a, b in zip(zeiten, zeiten[1:]))  # keine zwei Schlüsselbilder zur selben Zeit
    with pytest.raises(AufbauFehler, match="gibt es nicht"):
        plan({"dauer": 10, "blickwinkel": ["seitlich"]}, TEILE, HUELLEN)


def test_hochformat_rahmt_nach_der_breite():
    quer = plan({"dauer": 10, "blickwinkel": ["iso"]}, TEILE, HUELLEN, ausgenommen={"Boden"})
    hoch = plan({"dauer": 10, "blickwinkel": ["iso"], "seitenverhaeltnis": 9 / 16}, TEILE, HUELLEN,
                ausgenommen={"Boden"})
    d = [np.linalg.norm(np.asarray(f.fahrten[0].schluessel[0][1]) - np.asarray(f.mitte)) for f in (quer, hoch)]
    assert d[1] > d[0] * 1.3  # schmales Bild: weiter weg, damit das breite Modell hineinpasst


def test_detail_rahmt_nur_die_baugruppe():
    huellen = {**HUELLEN, "Drohne/GoPro": ([40.0, 30.0, 20.0], [60.0, 50.0, 30.0])}
    p = plan({"dauer": 10, "details": [{"auf": "Drohne/GoPro", "richtung": "iso_hinten_links"}]}, TEILE, huellen,
             ausgenommen={"Boden"})
    assert [f.titel for f in p.fahrten] == ["Orbit", "Detail GoPro"]
    lo, hi = np.asarray(huellen["Drohne/GoPro"][0]), np.asarray(huellen["Drohne/GoPro"][1])
    _, lage, ziel = p.fahrten[1].schluessel[0]
    assert np.allclose(ziel, (lo + hi) / 2)
    d_detail = np.linalg.norm(np.asarray(lage) - np.asarray(ziel))
    d_ganz = np.linalg.norm(np.asarray(p.fahrten[0].schluessel[0][1]) - np.asarray(p.mitte))
    assert d_detail < d_ganz
    with pytest.raises(AufbauFehler, match="passt zu keinem"):
        plan({"dauer": 10, "details": [{"auf": "Propeller"}]}, TEILE, HUELLEN)


# ---------------------------------------------------------------------------------------------------------------------
# Mit Rechenprozess
# ---------------------------------------------------------------------------------------------------------------------

MODEL = '''from build123d import *
from kevcad import show
show(Box(200, 200, 10), "Drohne/Rahmen/Platte")
show(Pos(80, 80, 20) * Cylinder(14, 20), "Drohne/Motor 1")
show(Pos(-80, 80, 20) * Cylinder(14, 20), "Drohne/Motor 2")
show(Pos(0, 0, 30) * Box(60, 40, 40), "Drohne/GoPro")
show(Pos(0, 0, -10) * Box(800, 800, 10), "Boden", kulisse=True)
'''


@pytest.fixture(scope="module")
def rt_app():
    tmp = Path(tempfile.mkdtemp(prefix="kcb", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    proj = tmp / "Drohne"
    assert rt.project_new(str(proj), "empty")["ok"]
    (proj / "kevcad.json").write_text('{"version": 1, "inventar_regel": false}', encoding="utf-8")
    yield rt, app, proj
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_aufbau_video_mit_strich_und_zwei_blickwinkeln(rt_app):
    rt, app, proj = rt_app
    assert rt.model_write(MODEL)["ok"]
    assert rt.run()["ok"]
    stop = threading.Event()
    anfragen: list[dict] = []

    def antworten():
        seen = app.mark()
        while not stop.is_set():
            try:
                i, _, h, _ = app.wait_for(lambda h: h["type"] == "ANIM_VIDEO_REQ", start=seen, timeout=0.5)
            except AssertionError:
                continue
            seen = i + 1
            anfragen.append(h)
            Path(h["path"]).write_bytes(b"\x00\x00\x00\x18ftypmp42")
            app.send({"type": "ANIM_VIDEO_RES", "reply_to": h["id"], "ok": True, "path": h["path"], "frames": 301,
                      "ms": 500, "message": None, "kamera": "Viewer"})

    t = threading.Thread(target=antworten, daemon=True)
    t.start()
    start = app.mark()
    try:
        wunsch = {"name": "Aufbau", "dauer": 10, "fps": 30, "blickwinkel": ["orbit", "schnitt"],
                  "schritte": ["Drohne/Rahmen", "Drohne/Motor *"],
                  "zeichnen": [{"vor": "Drohne/GoPro", "punkte": [[-30, -20, 50], [30, -20, 50], [30, 20, 50]]}]}
        r = rt.aufbau_video(wunsch, 640)
    finally:
        stop.set()
        t.join(2)
    assert r["ok"], r
    assert [v["titel"] for v in r["videos"]] == ["Orbit", "Schnitt"]
    assert [a["name"] for a in anfragen] == ["Aufbau Orbit", "Aufbau Schnitt"]
    video = Path(r["videos"][0]["path"])
    assert video.parent == (proj / "output" / "animationen").resolve() and video.name in ("Aufbau Orbit.mp4",
                                                                                         "Aufbau_Orbit.mp4")
    plan_ = r["zeitplan"]
    assert [s["titel"] for s in plan_["schritte"]] == ["Drohne/Rahmen", "Drohne/Motor *", "Drohne/GoPro"]
    assert plan_["striche"][0]["schritt"] == "Drohne/GoPro"
    gespeichert = json.loads(Path(r["zeitplan_datei"]).read_text(encoding="utf-8"))
    assert gespeichert["videos"][0]["path"] == r["videos"][0]["path"]
    # Striche als Kulisse gezeigt, Animationen mit Einblenden und Kamerafahrt
    status = rt.status()["last_run"]
    namen = [p["name"] for p in status["parts"]]
    assert any(n.startswith("Skizze/Strich 1/") for n in namen)
    _, _, kopf, nutzlast = app.wait_for(lambda h: h["type"] == "ANIM_DEF" and h.get("name") == "Aufbau Orbit",
                                        start=start)
    back = unpack_anim_def(kopf, nutzlast)
    assert back["kamera"] is not None and back["kamera"].shape[0] == back["bilder"]
    gruppen = {tuple(e["teile"]): e["zeiten"] for e in back["sichtbar"]}
    gopro = next(z for k, z in gruppen.items() if "Drohne/GoPro" in k)
    assert gopro[0][1] is False and gopro[-1][1] is True
    i = back["teile"].index("Drohne/GoPro")
    assert back["matrices"][-1, i, 2, 3] == pytest.approx(0, abs=1e-3)  # gelandet
    ankunft = int(round(gopro[-1][0] * 30))
    assert back["matrices"][ankunft, i, 2, 3] > 50  # kommt von oben
    # der nächste normale Lauf löst die Aufbau-Animationen ab
    assert rt.run()["ok"]
    assert not any(a["name"].startswith("Aufbau") for a in rt.animation_list()["animationen"])


def test_aufbau_video_fehler_im_wunsch_kommt_als_text(rt_app):
    rt, app, proj = rt_app
    assert rt.model_write(MODEL)["ok"]
    r = rt.aufbau_video({"name": "Aufbau", "dauer": 10, "schritte": ["Propeller"]}, 640)
    assert r["ok"] is False and "Propeller" in r["error"]
