"""Rest von Phase 4 (22.10.2026): Abweichung als Farbkarte (Rechnung, Protokoll, Laufzeit), Maßstab nachträglich
(Dateien, Laufzeit, App), Scans in der App (SCAN_LIST, SCAN_IMPORT, Phase der Auswertung).

Ersatzprogramme für kevcad-capture, fotomess und kevscan (gleiche Schnittstellen, rechnen aber nichts) wie in
test_referenz.py; die Laufzeit hier mit Rechenprozess, damit das Modell Teile hat.
"""

from __future__ import annotations

import io
import json
import math
import shutil
import stat
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime
from test_referenz import FAKE_CAPTURE, FAKE_FOTOMESS, MODELL, _kamera

from kevcad_kernel.protocol import (
    check_ref_abweichung,
    check_ref_message,
    pack_ref_abweichung,
    referenz_beispiele,
    unpack_ref_abweichung,
    unpack_ref_netz,
)
from kevcad_kernel.referenz import massstab, netz, vermessen
from kevcad_kernel.referenz import abweichung as ab
from kevcad_kernel.referenz.ablage import ReferenzFehler


def quader(b, t, h, z0=0.0):
    v = np.array([(x, y, z) for z in (z0, z0 + h) for y in (-t / 2, t / 2) for x in (-b / 2, b / 2)], float)
    q = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    T = []
    for a, b_, c, d in q:
        T += [(a, b_, c), (a, c, d)]
    return v, np.array(T)


# ----------------------------------------------------------------------------------------------- Rechnung

def test_naechster_punkt_gegen_proben():
    rng = np.random.default_rng(3)
    a, b, c = rng.normal(size=(3, 800, 3))
    p = rng.normal(size=(800, 3)) * 2
    q = ab.naechster_punkt(p, a, b, c)
    uv = rng.random((3000, 2))
    m = uv.sum(1) > 1
    uv[m] = 1 - uv[m]
    P = a[:, None] + (b - a)[:, None] * uv[None, :, :1] + (c - a)[:, None] * uv[None, :, 1:]
    proben = np.linalg.norm(P - p[:, None], axis=2).min(1)
    d = np.linalg.norm(q - p, axis=1)
    assert (d <= proben + 1e-9).all()  # nie weiter weg als die beste Probe
    assert float((proben - d).max()) < 0.15  # und nah an ihr


def test_abweichung_vorzeichen_und_abdeckung():
    V, T = quader(100, 60, 40)
    teil = [{"name": "Kiste", "positions": V, "triangles": T, "normals": None}]
    # Referenz 2 mm breiter: an den Seiten x = ±50 liegt sie 1 mm außerhalb (+1), oben und unten 0
    erg = ab.rechnen(teil, *quader(102, 60, 40))
    f = erg["modell"][0]
    P, w = f["punkte"], f["werte"]
    seite = (np.abs(np.abs(P[:, 0]) - 50) < 1e-3) & (np.abs(P[:, 1]) < 25) & (P[:, 2] > 5) & (P[:, 2] < 35)
    assert np.allclose(w[seite], 1.0, atol=1e-4)
    deckel = (np.abs(P[:, 2] - 40) < 1e-3) & (np.abs(P[:, 0]) < 45)
    assert np.allclose(w[deckel], 0.0, atol=1e-4)
    assert f["kennzahlen"]["max_mm"] == pytest.approx(1.0, abs=1e-3) and f["kennzahlen"]["abgedeckt"] == 1.0
    assert erg["referenz"]["kennzahlen"]["mittel_mm"] == pytest.approx(1.0, abs=1e-3)  # Ecken 1 mm außen
    assert erg["skala_mm"] == 1.0 and erg["grenze_mm"] == 10.0
    # Referenz 4 mm schmaler: Modell zu groß, negativ
    f2 = ab.rechnen(teil, *quader(96, 60, 40))["modell"][0]
    s2 = (np.abs(np.abs(f2["punkte"][:, 0]) - 50) < 1e-3) & (np.abs(f2["punkte"][:, 1]) < 25)
    assert np.nanmax(f2["werte"][s2]) == pytest.approx(-2.0, abs=1e-4)
    assert f2["kennzahlen"]["versatz_mm"] < 0
    # Referenz ohne Boden (wie ein Scan): die Unterseite des Modells ist nicht abgedeckt
    OV, OT = quader(100, 60, 40)
    f3 = ab.rechnen(teil, OV, OT[2:])["modell"][0]
    boden = (np.abs(f3["punkte"][:, 2]) < 1e-3) & (np.abs(f3["punkte"][:, 0]) < 40) & (np.abs(f3["punkte"][:, 1]) < 20)
    assert np.isnan(f3["werte"][boden]).all()
    assert 0.7 < f3["kennzahlen"]["abgedeckt"] < 0.85  # Boden 6000 von 24800 mm²
    # Weit weg: nichts abgedeckt
    f4 = ab.rechnen(teil, *quader(100, 60, 40, z0=500))["modell"][0]
    assert f4["kennzahlen"]["abgedeckt"] == 0.0 and f4["kennzahlen"]["mittel_mm"] is None


def test_verfeinern_und_kantenlaenge():
    V, T = quader(100, 60, 40)
    n, fl = ab.flaechennormalen(V, T)
    P, T2, N2, W = ab.verfeinern(V, T, n, 5.0)
    assert W.sum() == pytest.approx(fl.sum(), rel=1e-9)  # Fläche bleibt
    kanten = np.linalg.norm(P[T2[:, 1]] - P[T2[:, 0]], axis=1)
    assert kanten.max() <= 5.0 + 1e-9 and len(N2) == len(P)
    L, je = ab.kantenlaenge([1e6, 10.0])
    assert L > 1.0 and je[1] >= L


def test_protokoll_abweichung():
    beispiele = {n: (k, p) for n, k, p in referenz_beispiele()}
    for name in ("ref_deviation_modell", "ref_deviation_referenz"):
        kopf, nutz = beispiele[name]
        assert check_ref_abweichung(kopf, nutz) == [], name
    kopf, nutz = beispiele["ref_deviation_modell"]
    arr = unpack_ref_abweichung(kopf, nutz)
    assert arr["punkte"].shape == (8, 3) and arr["dreiecke"].shape == (12, 3) and np.isnan(arr["werte"][:4]).all()
    for name in ("ref_list_abweichung", "ref_scale_punkte", "ref_scale_kante", "scan_list", "scan_import"):
        assert check_ref_message(beispiele[name][0]) == [], name
    assert check_ref_message({"type": "REF_SCALE", "id": "x", "referenz": "r", "mm": 1, "punkte": None, "kante": None})
    with pytest.raises(ValueError, match="Werte"):
        pack_ref_abweichung(referenz="r", run=1, auf="modell", teil="t", feld="f", punkte=np.zeros((3, 3)),
                            dreiecke=[[0, 1, 2]], werte=[0.0])


# ----------------------------------------------------------------------------------------------- Maßstab (Dateien)

def test_massstab_dateien(tmp_path):
    cap = tmp_path / "capture"
    cap.mkdir()
    V, T = quader(100, 60, 40)
    (cap / "netz_mm.obj").write_text("# x\nmtllib n.mtl\n" + "".join(f"v {x} {y} {z} 0.5 0.5 0.5\n" for x, y, z in V)
                                     + "vt 0 0\n" + "".join(f"f {a + 1}/1 {b + 1}/1 {c + 1}/1\n" for a, b, c in T))
    kopf = ("ply\nformat binary_little_endian 1.0\nelement vertex 2\nproperty float x\nproperty float y\n"
            "property float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
    daten = b"".join(np.array(p, "<f4").tobytes() + bytes([1, 2, 3]) for p in ([1, 2, 3], [-4, 5, 6]))
    (cap / "punkte_mm.ply").write_bytes(kopf.encode() + daten)
    k = _kamera([400, 0, 300], [0, 0, 20])
    (cap / "poses.json").write_text(json.dumps({"cameras": [
        {"image": "a.jpg", "aligned": {"opencv": {"R": k["R"], "t": k["t"]}, "position": [400, 0, 300],
                                       "camera_to_world": [[1, 0, 0, 400], [0, 1, 0, 0], [0, 0, 1, 300],
                                                           [0, 0, 0, 1]]},
         "raw": {"position": [0.4, 0, 0.3]}}]}))
    (cap / "bericht.json").write_text(json.dumps({"huellmass_mm": {"laenge": 100, "breite": 60, "hoehe": 40},
                                                  "oberkante_mm": 40.0, "rekonstruktion": {"images": 60}}))
    erg = massstab.ordner_skalieren(tmp_path, 1.5, mit_messung=False)
    assert set(erg["geaendert"]) == {"capture/netz_mm.obj", "capture/punkte_mm.ply", "capture/poses.json",
                                     "capture/bericht.json"}
    m = netz.lies_obj(cap / "netz_mm.obj")
    assert np.allclose(m["positions"].max(0), [75, 45, 60]) and m["triangles"].shape == (12, 3)
    assert "0.5 0.5 0.5" in (cap / "netz_mm.obj").read_text() and "mtllib n.mtl" in (cap / "netz_mm.obj").read_text()
    roh = (cap / "punkte_mm.ply").read_bytes()
    p = np.frombuffer(roh[len(kopf):], dtype=[("xyz", "<f4", 3), ("rgb", "u1", 3)])
    assert np.allclose(p["xyz"], [[1.5, 3, 4.5], [-6, 7.5, 9]]) and (p["rgb"] == [1, 2, 3]).all()
    posen = json.loads((cap / "poses.json").read_text())["cameras"][0]
    assert posen["aligned"]["position"] == [600, 0, 450] and posen["aligned"]["camera_to_world"][0][3] == 600
    assert posen["raw"]["position"] == [0.4, 0, 0.3]  # Rohdaten bleiben
    # Projektion bleibt gleich: skalierter Punkt durch die skalierte Kamera
    R, t = np.asarray(k["R"]), np.asarray(k["t"])
    t2 = np.asarray(posen["aligned"]["opencv"]["t"])
    X = np.array([20.0, -10.0, 30.0])
    x1, x2 = R @ X + t, R @ (1.5 * X) + t2
    assert np.allclose(x1[:2] / x1[2], x2[:2] / x2[2])
    b = json.loads((cap / "bericht.json").read_text())
    assert b["huellmass_mm"] == {"laenge": 150, "breite": 90, "hoehe": 60} and b["oberkante_mm"] == 60
    assert b["rekonstruktion"] == {"images": 60} and b["massstab_bekannt"] is True
    assert massstab.faktor_pruefen(180, 120) == 1.5
    with pytest.raises(ReferenzFehler, match="unplausibel"):
        massstab.faktor_pruefen(1000, 10)
    meta = {"capture": {"huelle": {"laenge": 100}, "grundkoerper": {"laenge": 99, "breite": 59}}}
    assert massstab.kante_ist(meta, None, "grund_breite") == (59.0, "huelle")
    assert massstab.kante_ist(meta, {"masse": {"tiefe": 57.3}}, "tiefe") == (57.3, "messung")
    with pytest.raises(ReferenzFehler, match="unbekannt"):
        massstab.kante_ist(meta, None, "diagonale")
    neu = massstab.meta_skalieren(meta, 2.0, {"mm": 200, "ist_mm": 100, "quelle": "kante", "kante": "laenge"})
    neu = massstab.meta_skalieren(neu, 1.1, {"mm": 220, "ist_mm": 200, "quelle": "kante", "kante": "laenge"})
    assert neu["capture"]["huelle"]["laenge"] == pytest.approx(220) and neu["massstab"]["faktor"] == pytest.approx(2.2)
    assert len(neu["massstab"]["verlauf"]) == 2


# ----------------------------------------------------------------------------------------------- Laufzeit

FAKE_KEVSCAN = r'''
import json, sys, time
from pathlib import Path
a = sys.argv[1:]
aus = Path(a[a.index("--aus") + 1])
aus.mkdir(parents=True, exist_ok=True)
def e(**k):
    print(json.dumps(k), flush=True)
for ph, g in (("einlesen", 0.01), ("tiefe", 0.4), ("tsdf", 0.8), ("bericht", 0.97)):
    e(event="progress", phase=ph, fraction=0.5, gesamt=g, text=ph + " läuft")
    time.sleep(0.05)
b, t, h = 100, 60, 40
v = [(x, y, z) for z in (0, h) for y in (-t / 2, t / 2) for x in (-b / 2, b / 2)]
q = [(1, 3, 4, 2), (5, 6, 8, 7), (1, 2, 6, 5), (3, 7, 8, 4), (1, 5, 7, 3), (2, 4, 8, 6)]
(aus / "netz_mm.obj").write_text("".join(f"v {x} {y} {z}\n" for x, y, z in v) + "".join("f %d %d %d %d\n" % f for f in q))
(aus / "poses.json").write_text(json.dumps({"cameras": []}))
(aus / "kameras.json").write_text(json.dumps({"bilder": []}))
(aus / "bericht.json").write_text(json.dumps({"huellmass_mm": {"laenge": 100, "breite": 60, "hoehe": 40},
                                              "bilder": {"gesamt": 3, "fotos": 1, "video": 2}}))
e(event="done", bericht=str(aus / "bericht.json"))
'''


@pytest.fixture
def lauf(tmp_path_factory, monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="kcrr", dir=tempfile.gettempdir())).resolve()
    w = tmp / "w"
    (w / "fm" / ".venv" / "bin").mkdir(parents=True)
    (w / "fm" / "src" / "fotomess").mkdir(parents=True)
    kams = []
    for i, t in enumerate(np.linspace(0, 20, 21)):
        a = t / 20 * 2 * math.pi
        kams.append({**_kamera([400 * math.cos(a), 400 * math.sin(a), 300.0], [0, 0, 20]), "zeit": round(float(t), 3)})
    (w / "fm" / ".venv" / "bin" / "kameras.json").write_text(json.dumps(kams))
    A = np.diag([-1.0, -1.0, 1.0])
    (w / "kameras.json").write_text(json.dumps([{**k, "R": (np.asarray(k["R"]) @ A.T).tolist()} for k in kams]))
    for name, code, ziel in (("stub.py", FAKE_FOTOMESS, w / "fm" / ".venv" / "bin" / "python"),):
        (w / "fm" / ".venv" / "bin" / name).write_text(code)
        ziel.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{w / 'fm' / '.venv' / 'bin' / name}' \"$@\"\n")
        ziel.chmod(ziel.stat().st_mode | stat.S_IEXEC)
    (w / "capture.py").write_text(FAKE_CAPTURE)
    cap_prog = w / "kevcad-capture"
    cap_prog.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{w / 'capture.py'}' \"$@\"\n")
    cap_prog.chmod(0o755)
    ks = w / "ks"
    (ks / ".venv" / "bin").mkdir(parents=True)
    (ks / "src" / "kevscan").mkdir(parents=True)
    (ks / "stub.py").write_text(FAKE_KEVSCAN)
    py = ks / ".venv" / "bin" / "python"
    py.write_text(f"#!/bin/sh\nshift; shift\nexec '{sys.executable}' '{ks / 'stub.py'}' \"$@\"\n")  # ohne -m kevscan
    py.chmod(0o755)
    monkeypatch.setenv("KEVCAD_CAPTURE", str(cap_prog))
    monkeypatch.setenv("KEVCAD_FOTOMESS", str(w / "fm"))
    monkeypatch.setenv("KEVCAD_SCAN", str(ks))
    monkeypatch.setenv("KEVCAD_SCANS_DIR", str(tmp / "Scans"))
    monkeypatch.setattr(vermessen, "speicher_frei", lambda: 99)
    projekt = tmp / "Kiste"
    projekt.mkdir()
    (projekt / "model.py").write_text(MODELL)
    (projekt / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": False}))
    video = tmp / "IMG_TEST.MOV"
    video.write_bytes(b"video")
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, own=tmp / "eigen")
    assert rt.project_open(str(projekt))["ok"]
    yield rt, sock, projekt, video, tmp
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _warte(pred, s=30.0):
    ende = time.monotonic() + s
    while time.monotonic() < ende:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_abweichung_und_massstab_in_der_laufzeit(lauf):
    rt, sock, projekt, video, _ = lauf
    app = FakeApp(sock)
    assert rt.run()["ok"]
    assert rt.referenz_abweichung()["ok"] is False  # noch keine Referenz
    start = app.mark()
    r = rt.referenz_video(str(video), masz={"laenge": 100})
    assert r["ok"], r
    assert rt.referenzen("IMG_TEST", warten_s=30)["referenzen"][0]["zustand"] == "fertig"
    res = rt.referenz_abweichung("IMG_TEST", zeigen=True)
    assert res["ok"], res
    teile = {t["teil"]: t for t in res["teile"]}
    assert set(teile) == {"Kiste/Korpus", "Kiste/Griff"}  # Kulisse „Boden“ nicht
    # Ersatznetz von Object Capture: derselbe Quader wie der Korpus (um 180° gedreht, ohne Lage: hier gleich)
    assert teile["Kiste/Korpus"]["mittel_mm"] < 0.05 and teile["Kiste/Korpus"]["abgedeckt"] > 0.95
    assert teile["Kiste/Griff"]["versatz_mm"] < -2  # den Griff hat die Referenz nicht: Modell zu groß
    assert res["referenz_netz"]["abgedeckt"] > 0.9 and res["gezeigt"] is True and res["angelegt"] is False
    assert any("nicht am Modell angelegt" in h for h in res["hinweise"])
    _, _, abw, nutz = app.wait_for(lambda h: h["type"] == "REF_DEVIATION" and h.get("teil") == "Kiste/Korpus",
                                   start=start)
    assert check_ref_abweichung(abw, nutz) == [] and abw["auf"] == "modell"
    app.wait_for(lambda h: h["type"] == "REF_DEVIATION" and h["auf"] == "referenz", start=start)
    _, _, liste, _ = app.wait_for(lambda h: h["type"] == "REF_LIST" and h["referenzen"]
                                  and (h["referenzen"][0].get("abweichung") or {}).get("stand") == "done",
                                  start=start)
    kurz = liste["referenzen"][0]["abweichung"]
    assert {t["teil"] for t in kurz["teile"]} == set(teile) and kurz["referenz"]["abgedeckt"] > 0.9
    assert any(t["feld"] == abw["feld"] for t in kurz["teile"])
    app.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "referenz_abweichung", start=start)
    # Ein neuer Lauf mit unverändertem Modell schickt keine Felder noch einmal
    start = app.mark()
    assert rt.run()["ok"]
    assert rt.referenz_abweichung("IMG_TEST")["ok"]
    time.sleep(0.3)
    assert not [h for h in app.since(start) if h["type"] == "REF_DEVIATION"]
    # Legende fest auf 2 mm, Grenze 5 mm
    res = rt.referenz_abweichung("IMG_TEST", skala_mm=2, grenze_mm=5)
    assert res["skala_mm"] == 2 and res["skala_fest"] and res["grenze_mm"] == 5
    assert rt.referenz_abweichung("IMG_TEST", skala_mm=0)["skala_fest"] is False

    # Maßstab: Länge der Hülle 100 mm ist in Wahrheit 110 mm
    start = app.mark()
    m = rt.referenz_massstab("IMG_TEST", mm=110, kante="laenge")
    assert m["ok"], m
    assert m["faktor"] == pytest.approx(1.1) and "capture/netz_mm.obj" in m["geaendert"] and not m["messung_skaliert"]
    _, _, kopf, nutz = app.wait_for(lambda h: h["type"] == "REF_UPSERT", start=start)
    pos = unpack_ref_netz(kopf, nutz)["positions"]
    assert np.ptp(pos[:, 0]) == pytest.approx(110, abs=0.01) and np.ptp(pos[:, 2]) == pytest.approx(44, abs=0.01)
    e = rt.referenzen("IMG_TEST")["referenzen"][0]
    assert e["capture"]["huelle"]["laenge"] == pytest.approx(110) and e["massstab"]["faktor"] == pytest.approx(1.1)
    # Abweichung danach: Referenz größer als das Modell, positiv
    res = rt.referenz_abweichung("IMG_TEST")
    korpus = next(t for t in res["teile"] if t["teil"] == "Kiste/Korpus")
    assert korpus["versatz_mm"] > 1
    # Zwei Punkte am Netz (App-Weg): Ecken der Unterkante, 110 mm auseinander, sind 100 mm
    lo, hi = pos.min(0), pos.max(0)
    start = app.mark()
    app.send({"type": "REF_SCALE", "id": "s-1", "referenz": "IMG_TEST",
              "punkte": [[float(lo[0]), float(lo[1]), 0.0], [float(hi[0]), float(lo[1]), 0.0]], "kante": None,
              "mm": 100.0})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "s-1", start=start)
    assert ack["ok"] and "Faktor 0,9091" in ack["message"], ack
    e = rt.referenzen("IMG_TEST")["referenzen"][0]
    assert e["capture"]["huelle"]["laenge"] == pytest.approx(100, abs=0.01)
    assert e["massstab"]["faktor"] == pytest.approx(1.0, abs=1e-4)
    # Fehler: Punkt neben dem Netz, beides oder nichts, Scan
    assert "neben dem Netz" in rt.referenz_massstab("IMG_TEST", mm=50, punkte=[[0, 0, 500], [10, 0, 0]])["error"]
    assert "Entweder" in rt.referenz_massstab("IMG_TEST", mm=50)["error"]
    app.close()


def _scan_ordner(basis: Path) -> Path:
    from kevcad_kernel.scan import ablage as sa

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("Packung.kevscan/meta.json", json.dumps({"format": "kevscan", "version": 1, "name": "Packung",
                                                            "geraet": "iPhone16,1"}))
        z.writestr("Packung.kevscan/odometry.csv", "timestamp, frame, x, y, z, qx, qy, qz, qw\n0, 0, 0, 0, 0, 0, 0, 0, 1\n")
        z.writestr("Packung.kevscan/fotos.json", json.dumps({"fotos": [{"datei": "000.jpg"}]}))
    zp = basis / "p.zip"
    zp.write_bytes(puffer.getvalue())
    return sa.aufnehmen(zp, basis / "Scans", None)


def test_scans_in_der_app(lauf):
    rt, sock, projekt, _, tmp = lauf
    ordner = _scan_ordner(tmp)
    app = FakeApp(sock)
    _, _, liste, _ = app.wait_for(lambda h: h["type"] == "SCAN_LIST")
    assert check_ref_message(liste) == []
    assert [s["name"] for s in liste["scans"]] == ["Packung"] and liste["scans"][0]["zustand"] == "neu"
    assert liste["neu"] is None
    start = app.mark()
    rt._scan_empfangen({"id": ordner.name, "name": "Packung", "fotos": 1, "videobilder": 1, "groesse_mb": 0.1,
                        "ordner": str(ordner)})
    _, _, liste, _ = app.wait_for(lambda h: h["type"] == "SCAN_LIST", start=start)
    assert liste["neu"] == ordner.name
    # „Scan übernehmen“ in der App (schnell)
    start = app.mark()
    app.send({"type": "SCAN_IMPORT", "id": "i-1", "scan": ordner.name, "name": None, "schnell": True})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "i-1", start=start)
    assert ack["ok"] and "ausgewertet (schnell)" in ack["message"], ack
    _, _, laeuft, _ = app.wait_for(lambda h: h["type"] == "REF_LIST" and h["referenzen"]
                                   and h["referenzen"][0].get("phase"), start=start)
    r = laeuft["referenzen"][0]
    assert r["art"] == "scan" and r["laeuft"] == "capture" and r["phase"] in (
        "Einlesen", "Tiefe (PromptDA)", "Verschmelzen (TSDF)", "Bericht")
    _, _, fertig, _ = app.wait_for(lambda h: h["type"] == "SCAN_LIST" and h["scans"]
                                   and h["scans"][0]["zustand"] == "uebernommen", start=start)
    assert fertig["scans"][0]["referenzen"][0]["name"] == "Packung"
    assert rt.referenzen("Packung")["referenzen"][0]["zustand"] == "fertig"
    # Scan ist metrisch: kein Maßstab
    assert "metrisch" in rt.referenz_massstab("Packung", mm=100, kante="laenge")["error"]
    # unbekannter Scan
    start = app.mark()
    app.send({"type": "SCAN_IMPORT", "id": "i-2", "scan": "gibt-es-nicht", "schnell": False})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "i-2", start=start)
    assert not ack["ok"] and "nicht gefunden" in ack["message"]
    app.close()


def test_scanliste_ohne_projekt(tmp_path, monkeypatch):
    """Beim Verbinden kommt SCAN_LIST auch ohne offenes Projekt (das Band zeigt den Scan, bevor ein Projekt offen ist)."""
    monkeypatch.setenv("KEVCAD_SCANS_DIR", str(tmp_path / "Scans"))
    ordner = _scan_ordner(tmp_path)
    sock = str(Path(tempfile.mkdtemp(prefix="kcso", dir=tempfile.gettempdir())) / "k.sock")
    rt = make_runtime(sock, own=tmp_path / "eigen", start_worker=False)
    try:
        app = FakeApp(sock)
        _, _, liste, _ = app.wait_for(lambda h: h["type"] == "SCAN_LIST")
        assert [s["id"] for s in liste["scans"]] == [ordner.name]
        app.close()
    finally:
        rt.close()
