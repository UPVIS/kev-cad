"""Zeichnungen und Bauplan mit der App (DOKUMENTE.md 1.2): DRAWING_CREATE, Änderungen über MCP erreichen die App
sofort (DOCS, DRAWING, BAUPLAN), Notizen mit Zeiger auf Geometrie zeichnen ihre Hinweislinie und folgen dem Modell."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.protocol import drawing_create_message
from kevcad_kernel.zeichnung.zeichner import lies_nutzlast

MODELL = '''from build123d import *
from kevcad import lager, show, step, param

breite = param("breite", 200)
platte = lager.teil("platte-multiplex-birke-18")
p = platte.verbauen(breite=breite, tiefe=120, name="Gestell/Platte")
p -= [Pos(x, y, 0) * Cylinder(4.5, 60) for x in (-breite / 2 + 20, breite / 2 - 20) for y in (-40, 40)]
show(p, "Gestell/Platte")
'''


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcza", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    path = tmp / "Tisch"
    assert rt.project_new(str(path), "empty")["ok"]
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    assert rt.model_write(MODELL)["ok"]
    res = rt.run()
    assert res["ok"], res.get("error")
    yield {"rt": rt, "app": app, "path": path}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _blatt(rt, bid: str = "platte") -> tuple[dict, list[dict]]:
    res = rt.drawing(bid)
    assert res["ok"], res
    return res["kopf"], lies_nutzlast(res["kopf"], res["nutzlast"])


def _gruppe(kopf: dict, gruppen: list[dict], gid: str) -> dict:
    return next(g for geo, g in zip(kopf["geometrie"], gruppen) if geo["id"] == gid)


def _abstand(p: np.ndarray, pl: np.ndarray) -> float:
    a, b = pl[:-1], pl[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
    return float(np.min(np.linalg.norm(a + ab * t[:, None] - p, axis=1)))


def test_drawing_create_von_der_app(env):
    rt, app, path = env["rt"], env["app"], env["path"]
    start = app.mark()
    app.send(drawing_create_message("c-1", "teil", ["Gestell/Platte"]))
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "c-1", start=start, timeout=60)
    assert ack["ok"], ack
    assert ack["blaetter"] == ["platte"]
    _, _, docs, _ = app.wait_for(lambda h: h["type"] == "DOCS" and h.get("reply_to") == "c-1", start=start)
    assert [b["id"] for b in docs["blaetter"]] == ["platte"]
    assert (path / "dokumente" / "zeichnungen" / "platte.json").is_file()
    # Fehler: unbekanntes Teil, ACK mit ok false und ohne DOCS
    start = app.mark()
    app.send(drawing_create_message("c-2", "teil", ["Gibt/Es nicht"]))
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "c-2", start=start)
    assert ack["ok"] is False and ack["message"]
    assert rt.drawings()["ok"]


def test_mcp_aenderungen_erreichen_die_app(env):
    rt, app = env["rt"], env["app"]
    if not rt.drawings()["blaetter"]:
        assert rt.drawing_create(["Gestell/Platte"])["ok"]
    start = app.mark()
    res = rt.drawing_create(art="zusammenbau")
    assert res["ok"], res
    app.wait_for(lambda h: h["type"] == "DOCS" and not h.get("reply_to")
                 and "zusammenbau" in [b["id"] for b in h["blaetter"]], start=start)
    app.wait_for(lambda h: h["type"] == "DRAWING" and h["blatt"]["id"] == "zusammenbau", start=start)
    start = app.mark()
    res = rt.drawing_edit("platte", [{"op": "notiz", "text": "Vom Agenten", "lage": [30.0, 30.0]}], "agent")
    assert res["ok"], res
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "DRAWING" and h["blatt"]["id"] == "platte", start=start)
    assert any(n["text"] == "Vom Agenten" and n["quelle"] == "agent" for n in h["blatt"]["notizen"])
    app.wait_for(lambda h: h["type"] == "DOCS" and not h.get("reply_to"), start=start)
    plan = rt.bauplan()
    assert plan["ok"], plan
    schritt = next(s for a in plan["bauplan"]["abschnitte"] for s in a["schritte"])
    start = app.mark()
    res = rt.bauplan_bearbeiten([{"op": "text", "schritt": schritt["id"], "text": "Platte auflegen."}], "agent")
    assert res["ok"], res
    _, _, bp, _ = app.wait_for(lambda h: h["type"] == "BAUPLAN", start=start, timeout=60)
    assert any(s["text"] == "Platte auflegen." for a in bp["bauplan"]["abschnitte"] for s in a["schritte"])
    _, _, docs, _ = app.wait_for(lambda h: h["type"] == "DOCS" and h.get("bauplan"), start=start, timeout=60)
    assert docs["bauplan"]["schritte"] > 0


def test_notiz_mit_zeiger_auf_kante(env):
    rt, path = env["rt"], env["path"]
    if not (path / "dokumente" / "zeichnungen" / "platte.json").exists():
        assert rt.drawing_create(["Gestell/Platte"])["ok"]
    kopf, gruppen = _blatt(rt)
    v1 = _gruppe(kopf, gruppen, "v1")
    # längstes sichtbares Stück der ersten Ansicht: eine Außenkante; geklickt wird in ihre Mitte
    _, a, b = max(((float(np.linalg.norm(pl[i + 1] - pl[i])), pl[i], pl[i + 1]) for pl in v1["sichtbar"]
                   for i in range(len(pl) - 1)), key=lambda x: x[0])
    klick = [float(x) for x in (np.asarray(a) + np.asarray(b)) / 2]
    lage = [40.0, 45.0]
    res = rt.drawing_edit("platte", [{"op": "notiz", "text": "Kante entgraten", "lage": lage,
                                      "zeiger": {"ansicht": "v1", "punkt": klick}}], "kevin")
    assert res["ok"] and all(e["ok"] for e in res["ergebnisse"]), res
    datei = json.loads((path / "dokumente" / "zeichnungen" / "platte.json").read_text())
    notiz = next(n for n in datei["notizen"] if n["text"] == "Kante entgraten")
    assert notiz["zeiger"].get("teil") == "Gestell/Platte"  # Zeiger auf Geometrie, nicht auf einen Blattpunkt

    def hinweislinie(kopf, gruppen) -> np.ndarray:
        rahmen = _gruppe(kopf, gruppen, "blatt")
        linien = [pl for pl in rahmen["duenn"] if np.linalg.norm(np.asarray(pl[0]) - lage) < 1e-3]
        assert linien, "Hinweislinie fehlt"
        return np.asarray(linien[0][-1], dtype=float)

    kopf, gruppen = _blatt(rt)
    assert float(np.linalg.norm(hinweislinie(kopf, gruppen) - klick)) < 0.5
    # breitere Platte (Regler): die Notiz bleibt zugeordnet, ihre Spitze sitzt wieder auf einer Kante
    assert rt.run(params={"breite": 260})["ok"]
    kopf, gruppen = _blatt(rt)
    notiz = next(n for n in kopf["blatt"]["notizen"] if n["text"] == "Kante entgraten")
    assert not notiz.get("verwaist")
    spitze = hinweislinie(kopf, gruppen)
    v1 = _gruppe(kopf, gruppen, "v1")
    assert min(_abstand(spitze, np.asarray(pl, dtype=float)) for pl in v1["sichtbar"]) < 0.5
    assert rt.run()["ok"]
