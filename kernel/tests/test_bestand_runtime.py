"""Bestand über die volle Laufzeit (Rechenprozess, Test-App am Socket) und über den Ersatz-Kernel der App: BESTAND
nach dem Verbinden und Projektwechsel, BESTAND_SAVE, GEBAUT_REQ, BUCHUNG_RUECKGAENGIG, BOM mit Zuschnitt aus dem
Bestand, Einkaufsliste, Protokoll-Rundlauf gegen die Testdateien, MCP über den echten Server."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import texts, wait_for, with_client

from kevcad_kernel.protocol import FrameReader, check_bestand_message, encode_frame
from kevcad_kernel.server import KevcadHTTPServer

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURES = REPO / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"
ALFER = {"id": "rohr-alfer-12x1", "art": "rohr", "name": "ALFER-Rundrohr 12 × 1", "norm": "ALFER 01023",
         "masse": {"d": 12, "s": 1}, "material": "aluminium-6060", "stangenlaenge": 1000,
         "preis": {"je_m": 3.9, "quelle": "Baumarkt", "stand": "2026-10"},
         "bezugsquelle": {"url": "https://www.alfer.com/", "name": "ALFER"}}

# Kugelschieber: 3 × 1000, 2 × 175, 4 × 120, 2 × 60 aus ALFER-Rohr, zwei Platten 800 × 600, vier Muttern M8
MODEL = '''from build123d import *
from kevcad import lager, show, step

step("Rohre")
rohr = lager.teil("rohr-alfer-12x1")
x = 0
for name, laenge, n in (("Führung", 1000, 3), ("Quer", 175, 2), ("Abstand", 120, 4), ("Anschlag", 60, 2)):
    for i in range(n):
        x += 20
        nm = f"Rohre/{name} {i + 1}"
        show(Pos(x, 0, 0) * rohr.verbauen(laenge=laenge, name=nm), nm)
step("Platten")
platte = lager.teil("platte-multiplex-birke-18")
for i in range(2):
    nm = f"Platten/Boden {i + 1}"
    show(Pos(0, 1000 + i * 700, 0) * platte.verbauen(breite=800, tiefe=600, name=nm), nm)
step("Muttern")
mutter = lager.teil("mutter-iso4032-m8")
for i in range(4):
    nm = f"Muttern/M8 {i + 1}"
    show(Pos(-200 - 40 * i, 0, 0) * mutter.verbauen(name=nm), nm)
'''


@pytest.fixture(scope="module")
def rb():
    tmp = Path(tempfile.mkdtemp(prefix="kcb", dir=tempfile.gettempdir())).resolve()
    own = tmp / "eigen"
    own.mkdir()
    sock = str(tmp / "k.sock")
    os.environ.pop("KEVCAD_BESTAND_FILE", None)
    rt = make_runtime(sock, own=own)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp, "sock": sock}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def request(app, header: dict, timeout: float = 30):
    start = app.mark()
    app.send(header)
    i, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == header["id"], start=start, timeout=timeout)
    return reply, i + 1  # BESTAND und BOM kommen nach dem ACK


def after(app, start: int, types: list[str], timeout: float = 30) -> list[dict]:
    """Wartet, bis die Rahmen ``types`` in dieser Reihenfolge (andere dazwischen erlaubt) angekommen sind."""
    got: list[dict] = []
    pos = start
    for t in types:
        i, _, h, _ = app.wait_for(lambda h, t=t: h["type"] == t, start=pos, timeout=timeout)
        got.append(h)
        pos = i + 1
    return got


def fixture_header(name: str) -> dict:
    (header, _), = FrameReader().feed((FIXTURES / name).read_bytes())
    return header


def test_bestand_ueber_die_laufzeit(rb):
    rt, app, tmp = rb["rt"], rb["app"], rb["tmp"]
    # Nach dem Verbinden: BESTAND ohne Projekt
    _, _, first, _ = app.wait_for(lambda h: h["type"] == "BESTAND")
    assert first["bestand"] is None and first["buchungen"] == [] and first["stand"] is None

    # Projekt anlegen: BESTAND nach PROJECT, leer
    proj = tmp / "Kugelschieber"
    start = app.mark()
    assert rt.project_new(str(proj), "empty")["ok"]
    project_msg, bestand_msg = after(app, start, ["PROJECT", "BESTAND"])
    assert bestand_msg["bestand"]["posten"] == {} and bestand_msg["stand"] is None
    assert Path(bestand_msg["datei"]) == (proj / "bestand.json").resolve()
    (proj / "katalog.json").write_text(json.dumps({"version": 1, "teile": [ALFER]}, ensure_ascii=False))
    assert rt.model_write(MODEL)["ok"]

    # Kevins Angabe über MCP: 2 ganze Stangen, Reste 430, 610, 180, Mindestrest 80
    start = app.mark()
    res = rt.bestand_eintragen("rohr-alfer-12x1", ganze=2, reste=[430, 610, 180], mindestrest_mm=80,
                               grund="Kevin: 2 ganze Stangen, Reste 430, 610 und 180 mm")
    assert res["ok"], res
    assert res["buchung"]["id"] == "B-0001" and res["buchung"]["art"] == "eintrag" and res["buchung"]["von"] == "agent"
    assert res["aenderungen_text"] == [
        "ALFER-Rundrohr 12 × 1 (rohr-alfer-12x1): 2 ganze Stangen à 1000 mm dazu",
        "ALFER-Rundrohr 12 × 1 (rohr-alfer-12x1): Rest R-0001 (430 mm) dazu",
        "ALFER-Rundrohr 12 × 1 (rohr-alfer-12x1): Rest R-0002 (610 mm) dazu",
        "ALFER-Rundrohr 12 × 1 (rohr-alfer-12x1): Rest R-0003 (180 mm) dazu",
        "ALFER-Rundrohr 12 × 1 (rohr-alfer-12x1): Mindestrest Standard → 80 mm"]
    (msg,) = after(app, start, ["BESTAND"])
    assert [r["laenge"] for r in msg["bestand"]["posten"]["rohr-alfer-12x1"]["reste"]] == [430, 610, 180]
    assert msg["buchungen"][0]["id"] == "B-0001" and msg["stand"]
    assert rt.bestand_eintragen("gibtsnicht", ganze=1, grund="x")["ok"] is False

    # App: Plattenrest und Muttern (Kennung vergibt der Kernel), Einstellungen ohne Änderung
    reply, start = request(app, {"type": "BESTAND_SAVE", "id": "a-1", "posten_id": "platte-multiplex-birke-18",
                                 "posten": {"ganze": {"anzahl": 1}, "reste": [{"b": 820, "h": 620, "ort": "Keller"}]},
                                 "grund": "Rest 820 × 620"})
    assert reply["type"] == "ACK" and reply["ok"] is True and reply["buchung"] == "B-0002"
    (msg,) = after(app, start, ["BESTAND"])
    rest = msg["bestand"]["posten"]["platte-multiplex-birke-18"]["reste"][0]
    assert rest["kennung"] == "P-0001" and rest["ort"] == "Keller" and rest["seit"]
    reply, _ = request(app, {"type": "BESTAND_SAVE", "id": "a-2", "posten_id": "mutter-iso4032-m8",
                             "posten": {"stueck": [{"anzahl": 3}]}, "grund": ""})
    assert reply["ok"] is True and reply["buchung"] == "B-0003"
    reply, _ = request(app, {"type": "BESTAND_SAVE", "id": "a-3",
                             "einstellungen": {"mindestrest_mm": 100, "saegeblatt_mm": 3}, "grund": ""})
    assert reply["ok"] is True and reply["message"] == "keine Änderung" and "buchung" not in reply
    reply, _ = request(app, {"type": "BESTAND_SAVE", "id": "a-4", "posten_id": "mutter-iso4032-m8",
                             "posten": {"ganze": {"anzahl": 1}}, "grund": ""})
    assert reply["ok"] is False and "Stückgut" in reply["message"]

    # Lauf: BOM mit Zuschnitt aus dem Bestand und Einkaufsliste
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    assert res["bom"]["einkauf"]["positionen"] == 2
    (bom,) = after(app, start, ["BOM"])
    rohr = next(c for c in bom["cuts"] if c["stock_id"] == "rohr-alfer-12x1")
    assert rohr["art"] == "stange" and rohr["aus_bestand"] == {"reste": 3, "ganze": 2} and rohr["kaufen"] == 1
    assert rohr["neue_reste"] == [244]
    assert rohr["quellen"][0] == {"art": "rest", "kennung": "R-0001", "laenge": 430, "stuecke": [120, 60],
                                  "rest_neu": 244, "verschnitt": False}
    platte = next(c for c in bom["cuts"] if c.get("art") == "platte")
    assert platte["platte"] == {"b": 2500, "h": 1250} and platte["aus_bestand"] == {"reste": 1, "ganze": 1}
    assert platte["kaufen"] == 0 and platte["quellen"][0]["kennung"] == "P-0001"
    assert bom["stueckgut"] == [{"stock_id": "mutter-iso4032-m8", "benennung": bom["stueckgut"][0]["benennung"],
                                 "masse_text": "M8", "laenge": None, "anzahl": 4, "aus_bestand": 3, "kaufen": 1}]
    assert [(k["id"], k["menge"], k["einheit"]) for k in bom["einkaufsliste"]] == [
        ("rohr-alfer-12x1", 1, "Stange 1.000 mm"), ("mutter-iso4032-m8", 1, "Stück")]
    assert bom["einkauf_summe"] == 3.95 and bom["fehlt"] is True and bom["bestand_stand"]
    # gleiches Format wie die Testdatei der App
    ref = fixture_header("bom_bestand.frame")
    assert set(ref) - {"seq"} <= set(bom)
    ref_cut = next(c for c in ref["cuts"] if c.get("art") == "stange")
    assert set(ref_cut) <= set(rohr)
    ref_plate = next(c for c in ref["cuts"] if c.get("art") == "platte")
    assert set(ref_plate) <= set(platte)
    assert set(ref["einkaufsliste"][0]) == set(bom["einkaufsliste"][0])

    # Einkaufsliste über die Fassade, CSV in output/
    ek = rt.einkaufsliste()
    assert ek["ok"] and Path(ek["csv"]).name == "Kugelschieber-einkaufsliste.csv"
    roh = Path(ek["csv"]).read_bytes()
    assert roh.startswith(b"\xef\xbb\xbfGruppe;") and not roh.startswith(b"\xef\xbb\xbf\xef\xbb\xbf")
    assert "\n\nSumme: ≈ 3,95 €\n\nNormteile abzählen\n" in ek["text"]
    assert ek["summe"] == 3.95 and ek["positionen"] == 2 and ek["zukauf"] == [] and ek["lagerware"]
    assert ek["normteile"][0]["aus_bestand"] == 3 and ek["filament"] == []
    # Text und CSV wie die App sie teilt (dieselbe Zusammenstellung, Testdatei material für Swift)
    from kevcad_kernel.bestand import einkauf as ek_mod

    e = ek_mod.zusammenstellen(rt.bom())
    assert roh.decode("utf-8") == ek_mod.csv(e)
    assert ek["text"] == ek_mod.text(e, "Kugelschieber", ek_mod.heute_text())
    assert "einkauf_text" in rt.bom() and rt.bom()["verschnitt"]["definition"] == "2"
    exp = rt.export(["einkaufsliste_csv"])
    assert exp["ok"] and exp["files"] == [ek["csv"]]

    # Gebaut: falscher Lauf, dann richtig; ACK mit buchung, danach BESTAND und BOM
    reply, _ = request(app, {"type": "GEBAUT_REQ", "id": "a-5", "run": bom["run"] + 7})
    assert reply["ok"] is False and f"Lauf {bom['run']}" in reply["message"]
    reply, start = request(app, {"type": "GEBAUT_REQ", "id": "a-6", "run": bom["run"]})
    assert reply["type"] == "ACK" and reply["ok"] is True and reply["buchung"] == "B-0004"
    assert reply["message"].startswith("4 Reste weg, 2 ganze Stangen weg, 1 ganze Platte weg, 3 Stück weg")
    msg, bom2 = after(app, start, ["BESTAND", "BOM"])
    best = json.loads((proj / "bestand.json").read_text())
    rohr_p = best["posten"]["rohr-alfer-12x1"]
    assert rohr_p["ganze"]["anzahl"] == 0 and rohr_p["reste"] == [
        {"kennung": "R-0004", "laenge": 244, "ort": None, "seit": rohr_p["reste"][0]["seit"]}]
    assert best["posten"]["platte-multiplex-birke-18"]["ganze"]["anzahl"] == 0
    assert all(r["kennung"].startswith("P-") and r["kennung"] != "P-0001"
               for r in best["posten"]["platte-multiplex-birke-18"]["reste"])
    assert best["posten"]["mutter-iso4032-m8"]["stueck"] == [{"anzahl": 0}]
    assert msg["buchungen"][0]["id"] == "B-0004" and msg["buchungen"][0]["run"] == bom["run"]
    rohr2 = next(c for c in bom2["cuts"] if c["stock_id"] == "rohr-alfer-12x1")
    assert rohr2["aus_bestand"] == {"reste": 1, "ganze": 0}  # nur noch der neue Rest R-0004
    reply, _ = request(app, {"type": "GEBAUT_REQ", "id": "a-7", "run": bom["run"]})
    assert reply["ok"] is False and "schon als gebaut gebucht (B-0004)" in reply["message"]

    # Rückgängig: alter Stand, BESTAND zeigt rueckgaengig_durch
    reply, start = request(app, {"type": "BUCHUNG_RUECKGAENGIG", "id": "a-8", "buchung": "B-0004"})
    assert reply["ok"] is True and reply["buchung"] == "B-0005"
    msg, bom3 = after(app, start, ["BESTAND", "BOM"])
    assert msg["buchungen"][1]["id"] == "B-0004" and msg["buchungen"][1]["rueckgaengig_durch"] == "B-0005"
    assert msg["bestand"]["posten"]["rohr-alfer-12x1"]["ganze"]["anzahl"] == 2
    assert [r["kennung"] for r in msg["bestand"]["posten"]["rohr-alfer-12x1"]["reste"]] == ["R-0001", "R-0002",
                                                                                          "R-0003"]
    assert next(c for c in bom3["cuts"] if c["stock_id"] == "rohr-alfer-12x1")["aus_bestand"] == {"reste": 3,
                                                                                                    "ganze": 2}
    reply, _ = request(app, {"type": "BUCHUNG_RUECKGAENGIG", "id": "a-9", "buchung": "B-0004"})
    assert reply["ok"] is False and "schon rückgängig" in reply["message"]
    reply, _ = request(app, {"type": "BESTAND_REQ", "id": "a-10"})
    assert reply["type"] == "BESTAND" and [b["id"] for b in reply["buchungen"]][:2] == ["B-0005", "B-0004"]
    assert check_bestand_message(reply) == []
    for b in reply["buchungen"]:
        assert {"id", "zeit", "art", "projekt", "aenderungen", "von", "grund", "zusammenfassung",
                "rueckgaengig_durch"} <= set(b)

    # bestand.json von außen geändert: der Kernel meldet sich von selbst
    start = app.mark()
    best = json.loads((proj / "bestand.json").read_text())
    best["posten"]["rohr-alfer-12x1"]["ganze"]["anzahl"] = 5
    (proj / "bestand.json").write_text(json.dumps(best, ensure_ascii=False))
    msg, bom4 = after(app, start, ["BESTAND", "BOM"], timeout=10)
    assert msg["bestand"]["posten"]["rohr-alfer-12x1"]["ganze"]["anzahl"] == 5

    # MCP über den echten Server
    server = KevcadHTTPServer(rt, 0)
    server.start_in_thread()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        r = call("bestand_liste", {"id": "rohr-alfer-12x1"})
        text = texts(r)[0]
        assert r.is_error is False and text.startswith("Bestand im Projekt „Kugelschieber“ (bestand.json, Stand ")
        assert "- ALFER-Rundrohr 12 × 1 (rohr-alfer-12x1): 5 ganze Stangen à 1000 mm; Reste: R-0001 430 mm" in text
        r = call("einkaufsliste")
        assert "Einkaufsliste Kugelschieber" in texts(r)[0] and "CSV: " in texts(r)[0]
        r = call("bom")
        assert "Rest R-0001 (430 mm): 120 + 60; neuer Rest 244 mm" in texts(r)[0]
        r = call("gebaut_buchen", {"grund": "Kevin: Kugelschieber ist gebaut"})
        assert r.is_error is False and texts(r)[0].startswith("Gebaut gebucht (B-0006): ")
        r = call("buchung_rueckgaengig", {"id": "B-0006"})
        assert r.is_error is False and texts(r)[0].startswith("Buchung B-0006 rückgängig gemacht (B-0007)")
        r = call("bestand_eintragen", {"id": "rohr-alfer-12x1", "reste_entfernen": ["R-0099"], "grund": "x"})
        assert r.is_error is True and "R-0099 gibt es bei 'rohr-alfer-12x1' nicht" in texts(r)[0]
    finally:
        server.stop_thread()

    # Bestand je Projekt: ein zweites Projekt sieht davon nichts
    start = app.mark()
    assert rt.project_new(str(tmp / "Regal"), "empty")["ok"]
    _, msg = after(app, start, ["PROJECT", "BESTAND"])
    assert msg["bestand"]["posten"] == {} and msg["buchungen"] == []
    assert rt.bestand_liste()["text"].endswith("Sägeblatt 3 mm")
    assert not (tmp / "Regal" / ".kevcad" / "bestand-buchungen.jsonl").exists()


def test_protokoll_rundlauf_testdateien():
    expected = json.loads((FIXTURES / "fixtures.json").read_text())["bestand"]
    for info in expected["frames"]:
        data = (FIXTURES / info["file"]).read_bytes()
        (header, payload), = FrameReader().feed(data)
        assert header["type"] == info["type"] and len(payload) == info["payload_bytes"]
        assert encode_frame(header, payload) == data  # gleiches JSON beim erneuten Kodieren
        if header["type"] not in ("BOM", "ACK"):
            assert check_bestand_message(header) == [], info["file"]
    bestand = fixture_header("bestand.frame")
    assert sorted(bestand["bestand"]["posten"]) == expected["bestand"]["posten"]
    assert [b["id"] for b in bestand["buchungen"]] == expected["bestand"]["buchungen"]
    assert bestand["buchungen"][0]["zusammenfassung"] == expected["bestand"]["zusammenfassung_erste"]
    leer = fixture_header("bestand_leer.frame")
    assert leer["bestand"] is None and leer["buchungen"] == []
    bom = fixture_header("bom_bestand.frame")
    rohr = next(c for c in bom["cuts"] if c.get("art") == "stange")
    assert rohr["aus_bestand"] == expected["bom"]["rohr"]["aus_bestand"] and "stangen" in rohr
    platte = next(c for c in bom["cuts"] if c.get("art") == "platte")
    assert "stangen" not in platte and "stangenlaenge" not in platte and set(platte["platte"]) == {"b", "h"}
    q = platte["quellen"][0]
    assert set(q) == {"art", "kennung", "b", "h", "stuecke", "rest_neu"}
    assert set(q["stuecke"][0]) == {"b", "h", "x", "y", "gedreht"}
    ack = fixture_header("ack_gebaut.frame")
    assert ack["buchung"] == "B-0003" and ack["ok"] is True
    save = fixture_header("bestand_save_einstellungen.frame")
    assert "posten_id" not in save and set(save["einstellungen"]) == {"mindestrest_mm", "saegeblatt_mm"}


@pytest.mark.timeout(60)
def test_ersatz_kernel_mit_bestand(tmp_path):
    short = Path(tempfile.mkdtemp(prefix="kcf", dir=tempfile.gettempdir()))
    sock = str(short / "f.sock")
    proc = subprocess.Popen([sys.executable, str(REPO / "kernel" / "tools" / "fake_kernel.py"), "--socket", sock,
                             "--bestand", "--pause", "0", "--out", str(tmp_path / "out")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        assert wait_for(lambda: os.path.exists(sock), 20)
        app = FakeApp(sock)
        try:
            _, _, msg, _ = app.wait_for(lambda h: h["type"] == "BESTAND" and h.get("bestand"), timeout=20)
            assert msg["bestand"]["posten"]["rohr-alfer-12x1"]["ganze"]["anzahl"] == 2
            _, _, bom, _ = app.wait_for(lambda h: h["type"] == "BOM" and h.get("einkaufsliste") is not None,
                                        timeout=20)
            assert [c.get("art") for c in bom["cuts"]] == ["stange", "platte"] and bom["einkauf_summe"] == 4.74
            reply, start = request(app, {"type": "GEBAUT_REQ", "id": "a-1", "run": bom["run"]})
            assert reply["ok"] is True and reply["buchung"] == "B-0001"
            msg, bom2 = after(app, start, ["BESTAND", "BOM"])
            assert msg["buchungen"][0]["art"] == "gebaut"
            reply, start = request(app, {"type": "BUCHUNG_RUECKGAENGIG", "id": "a-2", "buchung": "B-0001"})
            assert reply["ok"] is True
            reply, start = request(app, {"type": "BESTAND_SAVE", "id": "a-3",
                                         "einstellungen": {"mindestrest_mm": 80, "saegeblatt_mm": 2.5}, "grund": ""})
            assert reply["ok"] is True and reply["buchung"] == "B-0003"
            msg, bom3 = after(app, start, ["BESTAND", "BOM"])
            assert msg["bestand"]["einstellungen"] == {"mindestrest_mm": 80, "saegeblatt_mm": 2.5}
            assert bom3["cuts"][0]["saegeschnitt"] == 2.5
            reply, _ = request(app, {"type": "EXPORT_REQ", "id": "a-4", "formats": ["einkaufsliste_csv"]})
            assert reply["type"] == "EXPORT_RES" and reply["files"][0].endswith("-einkaufsliste.csv")
        finally:
            app.close()
    finally:
        proc.terminate()
        proc.wait(10)
        shutil.rmtree(short, ignore_errors=True)
