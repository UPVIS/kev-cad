"""Phase 4: Referenzen (kevcad_kernel/referenz). Bausteine einzeln (Übernehmen in model.py, Protokoll, Netz und
Kameras, Anlegen, Befehl für kevcad-capture, Variantenbau aus model.py) und der Ablauf in der Laufzeit mit
Ersatzprogrammen für kevcad-capture und fotomess (gleiche Schnittstellen, rechnen aber nichts)."""

from __future__ import annotations

import json
import math
import os
import pickle
import shutil
import stat
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.protocol import (
    check_ref_message,
    encode_frame,
    pack_ref_netz,
    referenz_beispiele,
    unpack_ref_netz,
)
from kevcad_kernel.referenz import ablage, capture, netz, varianten, vermessen
from kevcad_kernel.referenz.ablage import ReferenzFehler
from kevcad_kernel.referenz.uebernehmen import UebernahmeFehler, param_stellen, uebernehmen

MODELL = '''"""Kiste als Messmodell (Test)."""
from build123d import *
from kevcad import param, show, step

breite = param("breite", 100)
tiefe = param("tiefe", 60.0)  # Kommentar bleibt
hoehe = param("hoehe", 40)
deckel = param("deckel", -2)

step("Kiste")
show(Box(breite, tiefe, hoehe, align=(Align.CENTER, Align.CENTER, Align.MIN)), "Kiste/Korpus", color="#B3121D")
show(Pos(0, -tiefe / 2 - 5, hoehe / 2) * Box(20, 10, 10), "Kiste/Griff", color="#222222")
show(Box(400, 400, 1, align=(Align.CENTER, Align.CENTER, Align.MAX)), "Boden", kulisse=True)


def messmodell(p):
    return dict(farbteile=["Kiste/Korpus"], zwillinge=["z180"], frei=["tiefe", "hoehe"], bekannt={"breite": 100},
                maske=dict(farbe_hsv=[[168, 4], 70, 25], gehaeuse=True), vorgaben={"tiefe": (60, 20)})
'''


# ----------------------------------------------------------------------------------------------- Übernehmen

def test_uebernehmen_ersetzt_nur_die_zahl():
    neu, aend = uebernehmen(MODELL, {"tiefe": 57.26, "hoehe": 41.04, "deckel": -1.5})
    assert 'tiefe = param("tiefe", 57.3)  # Kommentar bleibt' in neu
    assert 'hoehe = param("hoehe", 41)' in neu
    assert 'deckel = param("deckel", -1.5)' in neu
    assert 'breite = param("breite", 100)' in neu
    assert [a["name"] for a in aend] == ["tiefe", "hoehe", "deckel"]
    assert aend[0]["vorher"] == "60.0" and aend[0]["nachher"] == "57.3"
    assert len(neu.splitlines()) == len(MODELL.splitlines())
    with pytest.raises(UebernahmeFehler, match="gibt es kein param"):
        uebernehmen(MODELL, {"laenge": 3})
    assert set(param_stellen(MODELL)) == {"breite", "tiefe", "hoehe", "deckel"}


# ----------------------------------------------------------------------------------------------- Protokoll

def test_referenz_beispiele_sind_gueltig():
    for name, kopf, nutz in referenz_beispiele():
        assert check_ref_message(kopf) == [], name
        json.dumps(kopf)  # JSON-tauglich
        assert encode_frame(kopf, nutz)
    netz_kopf = next(k for n, k, _ in referenz_beispiele() if n == "ref_upsert")
    nutz = next(p for n, _, p in referenz_beispiele() if n == "ref_upsert")
    arr = unpack_ref_netz(netz_kopf, nutz)
    assert arr["positions"].shape == (5, 3) and arr["triangles"].shape == (6, 3)
    assert check_ref_message({"type": "REF_PHOTOS", "referenz": "x", "satz": "irgendwas", "fotos": []})


def test_ref_netz_prueft_eingaben():
    with pytest.raises(ValueError, match="Normalen"):
        pack_ref_netz(name="x", positions=np.zeros((3, 3)), normals=np.zeros((2, 3)), triangles=[[0, 1, 2]])
    with pytest.raises(ValueError, match="die es nicht gibt"):
        pack_ref_netz(name="x", positions=np.zeros((3, 3)), normals=np.zeros((3, 3)), triangles=[[0, 1, 3]])


# ----------------------------------------------------------------------------------------------- Netz und Kameras

def _kamera(C, ziel, f=1500.0, w=1920, h=1080):
    """OpenCV-Kamera bei C mit Blick auf ziel, Z oben."""
    C, ziel = np.asarray(C, float), np.asarray(ziel, float)
    vorn = ziel - C
    vorn /= np.linalg.norm(vorn)
    rechts = np.cross(vorn, [0, 0, 1.0])
    rechts /= np.linalg.norm(rechts)
    unten = np.cross(vorn, rechts)
    R = np.vstack([rechts, unten, vorn])
    return {"R": R.tolist(), "t": (-R @ C).tolist(), "f": f, "cx": w / 2, "cy": h / 2, "w": w, "h": h}


def _obj(pfad: Path, groesse=(100, 60, 40)) -> None:
    b, t, h = groesse
    v = [(x, y, z) for z in (0, h) for y in (-t / 2, t / 2) for x in (-b / 2, b / 2)]
    f = [(1, 3, 4, 2), (5, 6, 8, 7), (1, 2, 6, 5), (3, 7, 8, 4), (1, 5, 7, 3), (2, 4, 8, 6)]
    pfad.write_text("# test\n" + "".join(f"v {x} {y} {z}\n" for x, y, z in v) + "vt 0 0\nvn 0 0 1\n"
                    + "".join("f " + " ".join(f"{i}/1/1" for i in q) + "\n" for q in f))


def test_obj_lesen_normalen_nach_aussen(tmp_path):
    _obj(tmp_path / "k.obj")
    m = netz.lies_obj(tmp_path / "k.obj")
    assert m["positions"].shape == (8, 3) and m["triangles"].shape == (12, 3)
    # Ecke oben rechts hinten: Normale zeigt nach außen
    i = int(np.argmax(m["positions"].sum(1)))
    assert (m["normals"][i] > 0).all()
    assert netz.huelle(m["positions"])["max"] == [50.0, 30.0, 40.0]


def test_anlegen_findet_drehung_und_verschiebung():
    """Netz in einem um 180° gedrehten und verschobenen System: Kamerapaare gleicher Zeit legen es zurück."""
    A = np.array([[-1.0, 0, 0], [0, -1.0, 0], [0, 0, 1]])
    b = np.array([12.0, -30.0, 0.0])
    zeiten = np.linspace(0, 20, 21)
    modell_kams, capture_posen = [], []
    for t in zeiten:
        w = t / 20 * 2 * math.pi
        C = np.array([500 * math.cos(w), 500 * math.sin(w), 250 + 50 * math.sin(3 * w)])
        k_modell = _kamera(C, [0, 0, 20])
        modell_kams.append({"zeit": float(t), "kamera": k_modell})
        # Capture-System: X_c = A^T (X_m - b)
        Cc = A.T @ (C - b)
        capture_posen.append({"name": f"bild_{int(t)}", "bild": "", "zeit": float(t) + 0.0,
                              "kamera": _kamera(Cc, A.T @ (np.array([0, 0, 20.0]) - b))})
    lage = netz.anlegen(capture_posen, modell_kams[::3], netz_mitte=A.T @ (np.array([0, 0, 20.0]) - b))
    assert lage is not None and lage["paare"] == 7
    assert abs(abs(lage["drehung_z"]) - 180) < 0.5
    assert lage["rest_mm"] < 1.0
    p = np.array([10.0, 20.0, 5.0])
    assert np.allclose(lage["A"] @ (A.T @ (p - b)) + lage["b"], p, atol=0.5)
    # Kamera mitbewegt: Zentrum landet beim Modell
    kb = netz.bewegt(capture_posen[3]["kamera"], lage["A"], lage["b"])
    assert np.allclose(netz.zentrum(kb), netz.zentrum(modell_kams[3]["kamera"]), atol=0.5)


def test_feinanlegen_an_der_oberflaeche(tmp_path):
    """Netz um 3° und (6; −4; 1) mm versetzt: ICP legt es wieder auf das Modell (auch mit einem Bodenrest)."""
    _obj(tmp_path / "m.obj", (180, 105, 46))
    m = netz.lies_obj(tmp_path / "m.obj")
    # dichteres Netz als Referenz: Punkte auf der Oberfläche plus ein Streifen „Boden“ daneben
    rng = np.random.default_rng(1)
    P, _ = netz._flaechenpunkte(m["positions"], m["triangles"], 6000, rng)
    boden = np.column_stack([rng.uniform(-120, 120, 800), rng.uniform(60, 90, 800), np.zeros(800)])
    w = math.radians(3)
    R = np.array([[math.cos(w), -math.sin(w), 0], [math.sin(w), math.cos(w), 0], [0, 0, 1]])
    versatz = np.array([6.0, -4.0, 1.0])
    ref = np.concatenate([P, boden]) @ R.T + versatz  # so liegt das Referenznetz im eigenen System
    fein = netz.feinanlegen(ref, m["positions"], m["triangles"], np.eye(3), np.zeros(3))
    assert fein is not None
    zurueck = (ref[:6000] @ fein["A"].T + fein["b"])
    assert np.abs(zurueck - P).max() < 0.8, np.abs(zurueck - P).max()
    assert fein["rest_mm"] < 0.5


def test_kamera_skaliert_und_zeit_aus_name():
    k = _kamera([0, -500, 200], [0, 0, 0], f=3000, w=3840, h=2160)
    s = netz.skaliert(k, 1920, 1080)
    assert s["f"] == 1500 and s["cx"] == 960 and s["w"] == 1920
    assert netz.zeit_aus_name("IMG_5186_014.833") == pytest.approx(14.833)


# ----------------------------------------------------------------------------------------------- kevcad-capture

def test_capture_befehl_und_fortschritt(tmp_path):
    prog = tmp_path / "kevcad-capture"
    prog.write_text("#!/bin/sh\n")
    prog.chmod(0o755)
    cmd = capture.befehl("/v/IMG.MOV", tmp_path / "aus", masz={"laenge": 180}, auflage=True, von=2, bis=21.5,
                         programm=prog)
    assert cmd[:3] == [str(prog), "lauf", "/v/IMG.MOV"]
    assert ["--bilder", "60"] == cmd[5:7] and "--auflage" in cmd and "laenge=180" in cmd
    assert cmd[cmd.index("--von") + 1] == "2" and cmd[cmd.index("--bis") + 1] == "21.5"
    genau = capture.befehl("/v/a.mov", tmp_path, einstellung="genau", programm=prog)
    assert genau[genau.index("--kante") + 1] == "2880" and genau[genau.index("--detail") + 1] == "medium"
    with pytest.raises(ReferenzFehler, match="unbekannt"):
        capture.befehl("/v/a.mov", tmp_path, masz={"umfang": 3}, programm=prog)
    assert capture.gesamt_anteil({"phase": "reconstruction", "fraction": 0.5}) == pytest.approx(0.515)
    assert capture.gesamt_anteil({"phase": "post", "fraction": 1}) == pytest.approx(1.0)


def test_name_und_ablage(tmp_path):
    assert ablage.sicherer_name("IMG 5186: Küche/oben") == "IMG 5186- Küche-oben"
    ablage.schreibe_meta(tmp_path, "A", {"art": "video", "quelle": "/x.mov"})
    assert ablage.freier_name(tmp_path, "A") == "A 2"
    assert ablage.lese_meta(tmp_path, "A")["format"] == ablage.FORMAT
    assert ablage.finde(tmp_path, "a") == "A"
    with pytest.raises(ReferenzFehler, match="gibt es nicht"):
        ablage.finde(tmp_path, "Zzz")


# ----------------------------------------------------------------------------------------------- Varianten

@pytest.fixture(scope="module")
def kiste(tmp_path_factory):
    d = tmp_path_factory.mktemp("kiste")
    (d / "model.py").write_text(MODELL)
    (d / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": False}))
    return d


def test_varianten_aus_model_py(kiste):
    erg = varianten.baue({"modell": str(kiste / "model.py"), "params": {}, "frei": [],
                          "ausgabe": str(kiste / "v.pkl"), "catalog": {}})
    assert erg["ok"], erg
    assert erg["frei"] == ["tiefe", "hoehe"] and erg["bekannt"] == {"breite": 100.0}
    assert erg["teile"] == ["Kiste/Korpus", "Kiste/Griff"]  # Kulisse bleibt draußen
    assert erg["farbteile"] and erg["zwillinge"] == 1
    d = pickle.loads((kiste / "v.pkl").read_bytes())
    assert d["parameter"] == ["tiefe", "hoehe"] and d["p"]["tiefe"] == 60
    assert d["farbflaechen"]["Kiste/Korpus"] == [True] * 6 and d["farbflaechen"]["Kiste/Griff"] == [False] * 6
    # Variante tiefe + 0,5: Korpus 0,25 mm tiefer je Seite
    y0 = np.concatenate([f.reshape(-1, 3) for f in d["basis"]["Kiste/Korpus"]])[:, 1]
    y1 = np.concatenate([f.reshape(-1, 3) for f in d["varianten"][0]["Kiste/Korpus"]])[:, 1]
    assert y1.max() - y0.max() == pytest.approx(0.25, abs=1e-6)
    Q, c = d["zwillinge"][0]
    assert np.allclose(Q, np.diag([-1, -1, 1])) and abs(c[1]) < 1e-6  # Mitte des Farbteils, nicht der Hülle
    assert d["messmodell"]["maske"]["gehaeuse"] is True

    fehl = varianten.baue({"modell": str(kiste / "model.py"), "params": {}, "frei": ["laenge"],
                           "ausgabe": str(kiste / "w.pkl"), "catalog": {}})
    assert fehl["ok"] is False and "laenge" in fehl["error"]


# ----------------------------------------------------------------------------------------------- Laufzeit

FAKE_CAPTURE = r'''
import json, sys, time
from pathlib import Path
a = sys.argv[1:]
aus = Path(a[a.index("--aus") + 1])
(aus / "bilder").mkdir(parents=True, exist_ok=True)
def e(**k):
    print(json.dumps(k), flush=True)
e(event="start", command="lauf")
for f in (0.2, 0.6, 1.0):
    e(event="progress", phase="reconstruction", fraction=f, stage="mesh_generation")
    time.sleep(0.05)
b, t, h = 100, 60, 40
v = [(x, y, z) for z in (0, h) for y in (-t / 2, t / 2) for x in (-b / 2, b / 2)]
q = [(1, 3, 4, 2), (5, 6, 8, 7), (1, 2, 6, 5), (3, 7, 8, 4), (1, 5, 7, 3), (2, 4, 8, 6)]
# Capture-System: um 180 Grad gedreht gegenüber dem Modell
(aus / "netz_mm.obj").write_text("".join(f"v {-x} {-y} {z}\n" for x, y, z in v) + "".join("f %d %d %d %d\n" % f for f in q))
kams = json.loads(Path(sys.argv[0]).with_name("kameras.json").read_text())
cams = []
for i, k in enumerate(kams):
    (aus / "bilder" / f"bild_{i:04d}.jpg").write_bytes(b"jpg")
    cams.append({"image": f"bild_{i:04d}.jpg", "path": str(aus / "bilder" / f"bild_{i:04d}.jpg"), "width": k["w"],
                 "height": k["h"], "time_s": k["zeit"], "aligned": {"opencv": {"R": k["R"], "t": k["t"]},
                 "fx": k["f"], "fy": k["f"], "cx": k["cx"], "cy": k["cy"]}})
(aus / "poses.json").write_text(json.dumps({"format": "kevcad-capture/poses", "cameras": cams}))
summary = {"huellmass_mm": {"laenge": 100, "breite": 60, "hoehe": 40}, "grundkoerper_mm": {"laenge": 99, "breite": 59},
           "rekonstruktion": {"images": len(cams), "posed": len(cams)}, "massstab_bekannt": True}
(aus / "bericht.json").write_text(json.dumps(summary))
e(event="done", report=str(aus / "bericht.json"), summary=summary)
'''

FAKE_FOTOMESS = r'''
import json, sys
from pathlib import Path
auftrag = json.loads(Path(sys.argv[-1]).read_text())
abl = Path(auftrag["ablage"])
(abl / "bilder").mkdir(parents=True, exist_ok=True)
(abl / "masken").mkdir(parents=True, exist_ok=True)
(abl / "kontrolle").mkdir(parents=True, exist_ok=True)
Path(sys.argv[0]).with_name("auftrag_gesehen.json").write_text(json.dumps(auftrag))
def e(**k):
    print(json.dumps(k), flush=True)
for ph in ("bilder", "einpassen", "unsicherheit"):
    e(event="progress", phase=ph, fraction=0.5, text=ph)
kams = json.loads(Path(sys.argv[0]).with_name("kameras.json").read_text())
bilder = []
for i, k in enumerate(kams[::4]):
    n = f"IMG_{k['zeit']:07.3f}"
    for o in ("bilder", "kontrolle"):
        (abl / o / f"{n}.jpg").write_bytes(b"jpg")
    (abl / "masken" / f"{n}.png").write_bytes(b"png")
    kk = dict(k); kk["w"], kk["h"], kk["f"], kk["cx"], kk["cy"] = 3840, 2160, k["f"] * 2, k["cx"] * 2, k["cy"] * 2
    kk["name"] = n; kk["zentrum"] = [0, 0, 0]
    bilder.append({"name": n, "zeit": k["zeit"], "datei": f"bilder/{n}.jpg", "maske": f"masken/{n}.png",
                   "kontrolle": f"kontrolle/{n}.jpg", "kamera": kk, "iou": 0.95})
frei = auftrag["frei"]
m = {"format": "kevcad-fotomess/messung", "stand": "2026-10-22T15:00:00", "frei": frei,
     "start": {k: 60.0 if k == "tiefe" else 40.0 for k in frei}, "fest": {"breite": 100.0, "deckel": -2.0},
     "masse": {k: 57.3 if k == "tiefe" else 41.0 for k in frei}, "sigma": {k: 0.8 for k in frei},
     "brennweite_px": 3100.0, "arbeit": [1920, 1080], "bildgroesse": [3840, 2160], "bilder": bilder,
     "verworfen": [], "nachmessen": [{"mass": "hoehe", "varianz_vorher": 1.0, "varianz_nachher": 0.4, "anteil": 0.4}],
     "aufnahme": [{"azimut": 270.0, "hoehe": 5.0, "varianz_nachher": 0.95, "anteil": 0.95, "text": "von vorne, flach"}],
     "huelle": {"min": [-50, -40, 0], "max": [50, 30, 41], "groesse": [100, 70, 41]},
     "teile": {"Kiste/Korpus": {"min": [-50, -30, 0], "max": [50, 30, 41], "groesse": [100, 60, 41]},
               "Kiste/Griff": {"min": [-10, -40, 15], "max": [10, -30, 25], "groesse": [20, 10, 10]}},
     "zeiten": {"bilder": 1.0}, "dauer_s": 2.0, "warnungen": []}
(abl / "messung.json").write_text(json.dumps(m))
e(event="done", ergebnis=str(abl / "messung.json"))
'''


@pytest.fixture
def umgebung(kiste, monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="kcr", dir=tempfile.gettempdir())).resolve()
    werkzeuge = tmp / "w"
    (werkzeuge / "fm" / ".venv" / "bin").mkdir(parents=True)
    (werkzeuge / "fm" / "src" / "fotomess").mkdir(parents=True)
    kams = []
    for i, t in enumerate(np.linspace(0, 20, 21)):
        w = t / 20 * 2 * math.pi
        C = np.array([400 * math.cos(w), 400 * math.sin(w), 300.0])
        kams.append({**_kamera(C, [0, 0, 20]), "zeit": round(float(t), 3)})
    # fotomess-Kameras im Modellsystem, Capture-Kameras im um 180° gedrehten System
    (werkzeuge / "fm" / ".venv" / "bin" / "kameras.json").write_text(json.dumps(kams))
    A = np.diag([-1.0, -1.0, 1.0])
    cap = []
    for k in kams:
        R = np.asarray(k["R"]) @ A.T  # X_m = A X_c -> R_c = R_m A
        cap.append({**k, "R": R.tolist()})
    (werkzeuge / "kameras.json").write_text(json.dumps(cap))
    stub = werkzeuge / "fm" / ".venv" / "bin" / "stub.py"
    stub.write_text(FAKE_FOTOMESS)
    py = werkzeuge / "fm" / ".venv" / "bin" / "python"
    py.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{stub}' \"$@\"\n")
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    cap_py = werkzeuge / "capture.py"
    cap_py.write_text(FAKE_CAPTURE)
    cap_prog = werkzeuge / "kevcad-capture"
    cap_prog.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{cap_py}' \"$@\"\n")
    cap_prog.chmod(0o755)
    monkeypatch.setenv("KEVCAD_CAPTURE", str(cap_prog))
    monkeypatch.setenv("KEVCAD_FOTOMESS", str(werkzeuge / "fm"))
    monkeypatch.setattr(vermessen, "speicher_frei", lambda: 99)
    projekt = tmp / "Kiste"
    shutil.copytree(kiste, projekt, ignore=shutil.ignore_patterns("*.pkl"))
    video = tmp / "IMG_TEST.MOV"
    video.write_bytes(b"video")
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, own=tmp / "eigen", start_worker=False)
    assert rt.project_open(str(projekt))["ok"]
    yield rt, sock, projekt, video, werkzeuge
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_ablauf_video_vermessen_anlegen_uebernehmen(umgebung):
    rt, sock, projekt, video, werkzeuge = umgebung
    app = FakeApp(sock, answer=False)
    app.wait_for(lambda h: h["type"] == "REF_LIST")
    assert rt.referenzen()["referenzen"] == []

    # Vermessen direkt am Video (legt die Referenz an), freie Maße aus messmodell()
    start = app.mark()
    res = rt.referenz_vermessen(str(video))
    assert res["ok"], res
    assert res["referenz"] == "IMG_TEST" and [m["name"] for m in res["masse"]] == ["tiefe", "hoehe"]
    assert res["masse"][0] == {"name": "tiefe", "wert": 57.3, "sigma": 0.8, "start": 60.0, "aenderung": -2.7}
    assert res["bekannt"] == {"breite": 100.0}  # nur das bekannte Maß, nicht alle festen
    assert res["grundkoerper"]["teil"] == "Kiste/Korpus" and res["huelle"]["groesse"] == [100, 70, 41]
    texte = [e["text"] for e in res["empfehlungen"]]
    assert any("Von Hand nachmessen: hoehe" in t for t in texte) and any("bringen wenig" in t for t in texte)
    gesehen = json.loads((werkzeuge / "fm" / ".venv" / "bin" / "auftrag_gesehen.json").read_text())
    assert gesehen["video"] == str(video) and gesehen["frei"] == ["tiefe", "hoehe"]
    assert gesehen["farbe_hsv"] == [[168, 4], 70, 25] and gesehen["gehaeuse"] is True  # Maske aus messmodell()
    assert gesehen["vorgaben"] == {"tiefe": [60, 20]}
    _, _, fotos, _ = app.wait_for(lambda h: h["type"] == "REF_PHOTOS" and h["satz"] == "messung", start=start)
    assert check_ref_message(fotos) == []
    k = fotos["fotos"][0]["kamera"]
    assert k["w"] == 1920 and k["h"] == 1080 and k["f"] == pytest.approx(1500)  # auf Arbeitsgröße umgerechnet
    assert Path(fotos["fotos"][0]["bild"]).is_file() and fotos["fotos"][0]["maske"].endswith(".png")
    _, _, erg, _ = app.wait_for(lambda h: h["type"] == "REF_RESULT", start=start)
    assert check_ref_message(erg) == [] and erg["masse"][1]["wert"] == 41.0
    meta = json.loads((projekt / "referenzen" / "IMG_TEST" / "referenz.json").read_text())
    assert meta["messung"]["frei"] == ["tiefe", "hoehe"]

    # Object Capture (Ersatzprogramm) für dieselbe Referenz: Netz, Kameras, Lage
    start = app.mark()
    r = rt.referenz_video(str(video), masz={"laenge": 100}, auflage=True)
    assert r["ok"] and r["name"] == "IMG_TEST", r
    assert "--auflage" in r["befehl"] and "laenge=100" in r["befehl"]
    fertig = rt.referenzen("IMG_TEST", warten_s=30)["referenzen"][0]
    assert fertig["zustand"] == "fertig" and fertig["netz"] and fertig["messung"], fertig
    assert fertig["capture"]["huelle"] == {"laenge": 100, "breite": 60, "hoehe": 40}
    assert abs(abs(fertig["lage"]["drehung_z"]) - 180) < 1 and fertig["lage"]["rest_mm"] < 2
    _, _, laeuft, _ = app.wait_for(lambda h: h["type"] == "REF_LIST" and h["referenzen"]
                                   and h["referenzen"][0]["zustand"] == "rechnet", start=start)
    assert laeuft["referenzen"][0]["laeuft"] == "capture"
    _, _, kopf, nutz = app.wait_for(lambda h: h["type"] == "REF_UPSERT", start=start)
    assert check_ref_message(kopf) == [] and kopf["lage"]["paare"] >= 2
    pos = unpack_ref_netz(kopf, nutz)["positions"]
    # Ersatznetz war um 180° gedreht: angelegt liegt es wieder wie das Modell
    assert np.allclose(sorted(pos[:, 0]), sorted(np.repeat([-50, 50], 4)), atol=1.5)
    _, _, cfotos, _ = app.wait_for(lambda h: h["type"] == "REF_PHOTOS" and h["satz"] == "capture", start=start)
    assert len(cfotos["fotos"]) == 21 and cfotos["fotos"][0]["maske"] is None

    # Kevins Klick „Maße übernehmen“
    start = app.mark()
    app.send({"type": "REF_APPLY", "id": "a-1", "referenz": "IMG_TEST", "werte": {"tiefe": 57.3, "hoehe": 41.0}})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-1", start=start)
    assert ack["ok"] and "tiefe 60.0 → 57.3" in ack["message"], ack
    code = (projekt / "model.py").read_text()
    assert 'param("tiefe", 57.3)' in code and 'param("hoehe", 41)' in code
    app.close()


def test_fotos_und_fehler(umgebung, tmp_path):
    rt, sock, projekt, video, _ = umgebung
    assert "gibt es nicht" in rt.referenz_video(str(tmp_path / "fehlt.mov"))["error"]
    assert "kein Video" in rt.referenz_video(str(projekt / "model.py"))["error"]
    assert rt.referenz_fotos([str(tmp_path / "x.jpg")])["ok"] is False
    # Foto (sips wandelt in die Arbeitsgröße)
    import zlib
    import struct

    def png(w, h):
        def chunk(k, d):
            return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
        raw = b"".join(b"\x00" + b"\x80\x20\x20" * w for _ in range(h))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    for i in range(2):
        (tmp_path / f"foto{i}.png").write_bytes(png(40, 30))
    r = rt.referenz_fotos([str(tmp_path / "foto0.png"), str(tmp_path / "foto1.png")], name="Probe")
    assert r["ok"] and len(r["fotos"]) == 2 and all(Path(f).is_file() for f in r["fotos"])
    liste = rt.referenzen()["referenzen"]
    probe = next(e for e in liste if e["name"] == "Probe")
    assert probe["art"] == "fotos" and probe["zustand"] == "leer" and probe["quelle"] == "2 Fotos"
    assert rt.referenz_vermessen("Unbekannt")["ok"] is False


def test_versionen_ohne_bilder_der_referenzen(tmp_path):
    """Berichte, Kameras und Netz kommen in die Versionen, Bilder, Masken und Rohdaten nicht."""
    from kevcad_kernel.versionen.git import GitRepo, git_verfuegbar

    if not git_verfuegbar()[0]:
        pytest.skip("kein git")
    (tmp_path / "model.py").write_text("x = 1\n")
    r = tmp_path / "referenzen" / "IMG_1"
    for rel in ("referenz.json", "capture/poses.json", "capture/netz_mm.obj", "capture/bericht.json",
                "capture/bilder/bild_0001.jpg", "capture/baked_mesh_tex0.png", "capture/roh/obj/x.obj",
                "capture/punktwolke_mm.ply", "messung/messung.json", "messung/bilder/a.jpg", "messung/masken/a.png",
                "messung/kontrolle/a.jpg", "messung/varianten.pkl", "messung/cache/netz-1.pkl", "fotos/f.jpg"):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text("x")
    g = GitRepo(tmp_path)
    g.init()
    neu = sorted(g.unversionierte())
    assert neu == ["model.py", "referenzen/IMG_1/capture/bericht.json", "referenzen/IMG_1/capture/netz_mm.obj",
                   "referenzen/IMG_1/capture/poses.json", "referenzen/IMG_1/messung/messung.json",
                   "referenzen/IMG_1/referenz.json"]
