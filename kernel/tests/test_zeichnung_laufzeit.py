"""Zeichnungen in der Kernel-Laufzeit: Dateien, DOCS, DRAWING_REQ/DRAWING_EDIT, Neuzuordnung nach einem Lauf, Bild,
und die MCP-Werkzeuge über die Attrappe."""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from fake_service import PNG
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.protocol import unpack_polylinien

MODELL = '''from build123d import *
from kevcad import lager, show, step, param

laenge = param("laenge", 500)
loecher = param("loecher", 3)
rohr = lager.teil("rohr-en10220-42.4x2.0")
r = rohr.verbauen(laenge=laenge, name="Gestell/Rohr")
for z in [40, 250, laenge - 40][:int(loecher)]:
    r -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(4.5, 60)
show(r, "Gestell/Rohr")
platte = lager.teil("platte-multiplex-birke-18")
p = platte.verbauen(breite=200, tiefe=120, name="Gestell/Platte")
p = Pos(0, 0, laenge) * p
p -= [Pos(x, y, laenge) * Cylinder(4.5, 60) for x in (-80, 80) for y in (-40, 40)]
show(p, "Gestell/Platte")
'''


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcz", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    path = tmp / "Gestell"
    assert rt.project_new(str(path), "empty")["ok"]
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    assert rt.model_write(MODELL)["ok"]
    res = rt.run()
    assert res["ok"], res.get("error")
    yield {"rt": rt, "app": app, "path": path}
    app.close()
    rt.close()
    from kevcad_kernel.zeichnung.projektion import EXAKT

    assert EXAKT._proc is None  # Hilfsprozess der exakten Rechnung ist mit der Laufzeit beendet
    shutil.rmtree(tmp, ignore_errors=True)


def test_erstellen_dateien_und_docs(env):
    rt, app, path = env["rt"], env["app"], env["path"]
    start = app.mark()
    res = rt.drawing_create()
    assert res["ok"], res
    ids = {b["id"] for b in res["blaetter"]}
    assert ids == {"rohr", "platte", "zusammenbau"}
    for bid in ids:
        assert (path / "dokumente" / "zeichnungen" / f"{bid}.json").exists()
    rohr = next(b for b in res["blaetter"] if b["id"] == "rohr")
    texte = [m["text"] for m in rohr["masse"]]
    assert "500" in texte and "3× Ø9" in texte and "40" in texte
    _, _, docs, _ = app.wait_for(lambda h: h["type"] == "DOCS", start=start)
    assert {b["id"] for b in docs["blaetter"]} == ids
    assert all(b["verwaiste_masse"] == 0 for b in docs["blaetter"])
    liste = rt.drawings()
    assert liste["ok"] and len(liste["blaetter"]) == 3
    zb = next(b for b in res["blaetter"] if b["id"] == "zusammenbau")
    assert zb["inhalt"]["art"] == "zusammenbau"
    # zweites Erstellen behält die Blätter (nichts neu)
    res2 = rt.drawing_create()
    assert not any(b["neu"] for b in res2["blaetter"])


def test_app_anfrage_und_bearbeitung(env):
    rt, app = env["rt"], env["app"]
    if not rt.drawings()["blaetter"]:
        rt.drawing_create()
    start = app.mark()
    app.send({"type": "DRAWING_REQ", "id": "a-1", "blatt": "rohr"})
    _, _, h, p = app.wait_for(lambda h: h["type"] == "DRAWING" and h.get("reply_to") == "a-1", start=start)
    gruppen = unpack_polylinien(h, p)
    assert len(gruppen) == len(h["geometrie"]) and h["geometrie"][-1]["id"] == "blatt"
    assert h["blatt"]["id"] == "rohr" and h["masse"]
    v1 = next(g for g in h["geometrie"] if g["id"] == "v1")
    x0, y0, x1, y1 = v1["rahmen"]
    laenge_id = next(m["id"] for m in h["blatt"]["masse"] if m.get("schluessel") == "huelle:x")
    start = app.mark()
    app.send({"type": "DRAWING_EDIT", "id": "a-2", "blatt": "rohr", "von": "kevin", "ops": [
        {"op": "mass_verschieben", "id": laenge_id, "versatz": -30.0},
        {"op": "mass_neu", "art": "linear", "richtung": "x", "versatz": 25.0,
         "bezuege": [{"ansicht": "v1", "punkt": [x0, (y0 + y1) / 2]},
                     {"ansicht": "v1", "punkt": [x1, (y0 + y1) / 2]}]}]})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-2", start=start)
    assert ack["ok"], ack
    _, _, neu, _ = app.wait_for(lambda h: h["type"] == "DRAWING" and h.get("reply_to") is None
                                and h["blatt"]["id"] == "rohr", start=start)
    eigen = [m for m in neu["blatt"]["masse"] if m.get("quelle") == "kevin"]
    assert len(eigen) == 1 and eigen[0]["bezuege"][0]["merkmal"] in ("seite:x-", "ende:a")
    assert next(m for m in neu["masse"] if m["id"] == eigen[0]["id"])["text"] == "500"
    datei = json.loads((env["path"] / "dokumente" / "zeichnungen" / "rohr.json").read_text())
    assert any(m.get("quelle") == "kevin" for m in datei["masse"])
    assert next(m for m in datei["masse"] if m["id"] == laenge_id)["fest"] is True
    # unbekanntes Blatt: Fehler an die App
    app.send({"type": "DRAWING_REQ", "id": "a-3", "blatt": "gibt-es-nicht"})
    _, _, err, _ = app.wait_for(lambda h: h.get("reply_to") == "a-3", start=start)
    assert err["type"] == "ERROR" and "gibt es nicht" in err["message"]


def test_neuzuordnung_nach_lauf(env):
    rt, app = env["rt"], env["app"]
    if not any(m.get("quelle") == "kevin" for b in [rt.drawing("rohr")] for m in b["kopf"]["blatt"]["masse"]):
        test_app_anfrage_und_bearbeitung(env)
    start = app.mark()
    lauf = rt.run(params={"laenge": 600})
    assert lauf["ok"]
    _, _, docs, _ = app.wait_for(lambda h: h["type"] == "DOCS" and h.get("run") == lauf["run"], start=start, timeout=60)
    rohr = next(b for b in docs["blaetter"] if b["id"] == "rohr")
    assert rohr["verwaiste_masse"] == 0
    res = rt.drawing("rohr")
    texte = {m["id"]: m["text"] for m in res["kopf"]["masse"]}
    eigen = next(m for m in res["kopf"]["blatt"]["masse"] if m.get("quelle") == "kevin")
    assert texte[eigen["id"]] == "600"  # Kevins Maß hängt an den Stirnseiten und folgt der neuen Länge
    laenge = next(m for m in res["kopf"]["blatt"]["masse"] if m.get("schluessel") == "huelle:x")
    assert texte[laenge["id"]] == "600" and laenge["versatz"] == pytest.approx(-30.0)
    # nur noch eine Bohrung: ein Kevin-Maß auf die dritte Bohrung wird verwaist. Bearbeitet wird am Stand der Dateien;
    # im Reglerstand lehnt der Kernel das ab (die Bezüge gehörten zum Reglerstand)
    op = {"op": "mass_neu", "art": "linear", "richtung": "x", "ansicht": "v1",
          "bezuege": [{"merkmal": "seite:x-"}, {"merkmal": "bohrung:3"}]}
    abgelehnt = rt.drawing_edit("rohr", [op], "kevin")
    assert abgelehnt["ok"] is False and abgelehnt.get("regler") and "Reglerstand" in abgelehnt["error"]
    assert rt.run()["ok"]
    assert rt.drawing_edit("rohr", [op], "kevin")["ok"]
    start = app.mark()
    lauf = rt.run(params={"laenge": 600, "loecher": 1})
    assert lauf["ok"]
    _, _, docs, _ = app.wait_for(lambda h: h["type"] == "DOCS" and h.get("run") == lauf["run"], start=start, timeout=60)
    rohr = next(b for b in docs["blaetter"] if b["id"] == "rohr")
    assert rohr["verwaiste_masse"] == 1
    assert rt.run(params={"laenge": 500, "loecher": 3})["ok"]


@pytest.mark.skipif(shutil.which("rsvg-convert") is None and not Path("/opt/homebrew/bin/rsvg-convert").exists(),
                    reason="rsvg-convert fehlt (z. B. auf dem Mac mini)")
def test_bild_aus_der_laufzeit(env):
    rt = env["rt"]
    if not rt.drawings()["blaetter"]:
        rt.drawing_create()
    res = rt.drawing_image("platte", 800)
    assert res["ok"], res
    assert res["png"][:8] == b"\x89PNG\r\n\x1a\n" and res["breite"] == 800
    assert rt.drawing_image("gibt-es-nicht")["ok"] is False


# ---------------------------------------------------------------------------------------------------------------------
# MCP über die Attrappe
# ---------------------------------------------------------------------------------------------------------------------


def _call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_mcp_zeichnungswerkzeuge():
    server, fake = start_server()
    try:
        res = _call(server.url, "zeichnungen")
        assert res.is_error is False and "seitenstange" in texts(res)[0]
        res = _call(server.url, "zeichnung_erstellen", {"teile": ["Gestell/Seitenstange"]})
        assert res.is_error is False
        text = texts(res)[0]
        assert "3× Ø4,2" in text and "zeichnung_bild" in text
        assert fake.calls_of("drawing_create")[-1] == ((["Gestell/Seitenstange"], "teil", None), {})
        res = _call(server.url, "zeichnung_bearbeiten", {"blatt": "seitenstange", "ops": [
            {"op": "mass_neu", "art": "linear", "ansicht": "v1",
             "bezuege": [{"merkmal": "seite:x-"}, {"merkmal": "bohrung:1"}]}]})
        assert res.is_error is False and "1 von 1 Operationen" in texts(res)[0]
        assert fake.calls_of("drawing_edit")[-1][0][2] == "agent"
        res = _call(server.url, "zeichnung_bearbeiten", {"blatt": "fehlt", "ops": [{"op": "mass_loeschen", "id": "m1"}]})
        assert res.is_error is True
        res = _call(server.url, "zeichnung_bild", {"blatt": "seitenstange", "breite": 900})
        images = [b for b in res.content if b.type == "image"]
        assert len(images) == 1 and base64.b64decode(images[0].data) == PNG
    finally:
        server.stop_thread()
