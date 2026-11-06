"""V2-7: Der Agent stellt die Oberfläche über ``view``, benennt das Projekt mit ``projekt(name=…)`` und merkt, wenn Kevin
während der Arbeit umbenennt. Kernel und MCP gegen die Test-App."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import get_args

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from kevcad_kernel import protocol as p
from kevcad_kernel.mcp_tools.tools import Kachel
from kevcad_kernel.server import build_server
from mcp import Client

ALLE = list(p.KERNEL_FAEHIGKEITEN)
FLAECHE = {"modus": "werkstatt", "kacheln": ["modell", "zeichnung", "druck"], "gross": "druck", "aktiv": "druck",
           "rand": "rechts", "zeitleiste": False, "ansicht": "top", "blatt": {"id": "b-2", "titel": "Rohr", "nr": 2, "von": 5}}
KOPF = {"zeit": 1.0, "ms": 1.0, "kamera": {}, "viewport": {"breite": 10, "hoehe": 10}, "sichtbar": [], "verborgen": [],
        "isoliert": None, "auswahl": {"run": None, "refs": []}, "maus": None, "darstellung": "shaded_edges",
        "schnitt": None, "explosion": 0.0, "animation": None}


class App(FakeApp):
    """Wie die echte App: `projekt_name` zieht den Ordner um und öffnet das Projekt am neuen Ort."""

    def __init__(self, sock: str, **kwargs) -> None:
        self.ziel: Path | None = None
        super().__init__(sock, answer=False, **kwargs)

    def _read(self) -> None:  # noqa: D102 (Lesefaden der Test-App mit eigener Antwort auf VIEW_CMD)
        from kevcad_kernel.protocol import FrameReader

        leser = FrameReader()
        while True:
            try:
                data = self.sock.recv(1 << 16)
            except OSError:
                return
            if not data:
                return
            for h, pl in leser.feed(data):
                with self.cond:
                    self.frames.append((0.0, h, pl))
                    self.cond.notify_all()
                if h["type"] == "VIEW_CMD":
                    self.antworten(h)
                elif h["type"] == "LAGE_REQ" and self.lage is not None:
                    self.send({"type": "LAGE", "reply_to": h["id"], **self.lage})

    def antworten(self, h: dict) -> None:
        if h["cmd"] == "projekt_name":
            alt = self.ziel
            neu = alt.with_name(h["args"]["name"])
            alt.rename(neu)
            self.ziel = neu
            self.send({"type": "ACK", "reply_to": h["id"], "ok": True, "message": str(neu)})
            self.send({"type": "PROJECT_OPEN", "id": "a-1", "path": str(neu)})
        else:
            self.send({"type": "ACK", "reply_to": h["id"], "ok": True, "message": "Werkstatt: 1 Modell, 2 Druck"})


@pytest.fixture()
def tmp():
    t = Path(tempfile.mkdtemp(prefix="kcfl", dir=tempfile.gettempdir())).resolve()
    yield t
    shutil.rmtree(t, ignore_errors=True)


def aufrufe(mcp, *schritte):
    async def go():
        out = []
        async with Client(mcp, raise_exceptions=True) as c:
            for name, args in schritte:
                out.append(await c.call_tool(name, args))
        return out

    return anyio.run(go)


def text(res) -> str:
    return "\n".join(b.text for b in res.content if b.type == "text")


def flaeche_befehle(app) -> list[dict]:
    return [h["args"] for _t, h, _p in app.frames if h["type"] == "VIEW_CMD" and h["cmd"] == "flaeche"]


def test_kacheln_gleich_auf_beiden_seiten():
    assert get_args(Kachel) == p.KACHELN
    swift = Path(__file__).resolve().parents[2] / "app/KevCADCore/Sources/KevCADCore/Model/Oberflaeche.swift"
    zeile = next(z for z in swift.read_text(encoding="utf-8").splitlines() if z.strip().startswith("case modell,"))
    assert tuple(n.strip() for n in zeile.strip()[len("case "):].split(",")) == p.KACHELN


def test_befehle_sind_gueltig_und_falsche_werden_gemeldet():
    gut = {"type": "VIEW_CMD", "id": "k", "cmd": "flaeche", "args": {"zeigen": ["druck"], "gross": 2, "rand": "aus"}}
    assert p.check_live_message(gut) == []
    for falsch in ({"zeigen": ["kaffee"]}, {"gross": 5}, {"modus": "ruhe"}, {"rand": "oben"}, {"schliessen": "einige"},
                   {"zeitleiste": "ja"}):
        assert p.check_live_message({**gut, "args": falsch}), falsch


def test_view_stellt_die_flaeche_und_status_nennt_sie(tmp):
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    app = App(sock, faehigkeiten=ALLE, lage={**KOPF, "flaeche": FLAECHE})
    try:
        app.wait_for(lambda h: h["type"] == "HELLO")
        assert rt.wait_worker_ready(240)
        app.ziel = tmp / "Klein"
        assert rt.project_new(str(app.ziel), "empty")["ok"]
        mcp = build_server(rt)
        gezeigt, nur, gross, ordnen, alles, status = aufrufe(
            mcp,
            ("view", {"kacheln": ["druck"]}),
            ("view", {"kacheln": ["modell", "stueckliste"], "kacheln_nur": True}),
            ("view", {"kachel_gross": 2}),
            ("view", {"kachel_gross": "aus", "kachel_zu": [2], "rand": "aus"}),
            ("view", {"modus": "fokus", "rand": "rechts", "zeitleiste": True, "zweite_ansicht": "front", "blatt": "Rohr"}),
            ("status", {}))
        assert not gezeigt.is_error and "Werkstatt: 1 Modell, 2 Druck" in text(gezeigt), text(gezeigt)
        befehle = flaeche_befehle(app)
        assert befehle[0] == {"zeigen": ["druck"]}
        assert befehle[1] == {"ordnen": ["modell", "stueckliste"]}
        assert befehle[2] == {"gross": 2}
        assert befehle[3] == {"gross": "aus", "schliessen": [2], "rand": "aus"}
        assert befehle[4] == {"modus": "fokus", "rand": "rechts", "zeitleiste": True, "ansicht": "front", "blatt": "Rohr"}
        for b in befehle:
            assert p.check_live_message({"type": "VIEW_CMD", "id": "k", "cmd": "flaeche", "args": b}) == []
        t = text(status)
        assert "Fläche: Werkstatt, 1 Modell, 2 Zeichnung, 3 Druck (groß), Blatt 2 von 5, Fenster am rechten Rand" in t, t
        assert status.structured_content["flaeche"]["gross"] == "druck"

        falsch, = aufrufe(mcp, ("view", {"kacheln_nur": True}))
        assert falsch.is_error and "kacheln_nur" in text(falsch)
        unbekannt, = aufrufe(mcp, ("view", {"kacheln": ["kaffee"]}))
        assert unbekannt.is_error, text(unbekannt)
    finally:
        app.close()
        rt.close()


def test_fokus_steht_knapp_im_status():
    from kevcad_kernel.mcp_tools.kern import flaeche_zeile

    assert flaeche_zeile({"modus": "fokus", "kacheln": ["modell"], "zeitleiste": False}) == "Fläche: Fokus"
    assert flaeche_zeile({"modus": "fokus", "kacheln": ["modell", "druck"], "zeitleiste": True, "rand": "links"}) \
        == "Fläche: Fokus, Zeitleiste an, Fenster am linken Rand"
    assert flaeche_zeile({"modus": "werkstatt", "kacheln": []}) == "Fläche: Werkstatt, keine Kachel"
    assert flaeche_zeile(None) is None


def test_aeltere_app_bekommt_klaren_fehler_und_keinen_befehl(tmp):
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    app = FakeApp(sock, faehigkeiten=[f for f in ALLE if f != p.FAEHIGKEIT_FLAECHE])
    ohne = None
    try:
        app.wait_for(lambda h: h["type"] == "HELLO")
        assert rt.wait_worker_ready(240)
        assert rt.project_new(str(tmp / "Klein"), "empty")["ok"]
        mcp = build_server(rt)
        res, benannt = aufrufe(mcp, ("view", {"kacheln": ["druck"]}), ("projekt", {"name": "Neu"}))
        assert res.is_error and "aktualisieren" in text(res), text(res)
        assert benannt.is_error and "aktualisieren" in text(benannt), text(benannt)
        assert not [h for _t, h, _p in app.frames if h["type"] == "VIEW_CMD"]
    finally:
        app.close()
        if ohne:
            ohne.close()
        rt.close()


def test_projekt_benennen_und_kevin_benennt_um(tmp):
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    app = App(sock, faehigkeiten=ALLE)
    try:
        app.wait_for(lambda h: h["type"] == "HELLO")
        assert rt.wait_worker_ready(240)
        app.ziel = tmp / "Neues Projekt"
        assert rt.project_new(str(app.ziel), "empty")["ok"]
        mcp = build_server(rt)

        erst, benannt, danach = aufrufe(mcp, ("status", {}), ("projekt", {"name": "Kugelschieber"}), ("status", {}))
        assert "Neues Projekt" in text(erst)
        neu = tmp / "Kugelschieber"
        assert not benannt.is_error, text(benannt)
        assert f"Projekt heißt jetzt Kugelschieber: {neu}" in text(benannt) and str(neu / "model.py") in text(benannt)
        assert "Achtung" not in text(danach), "die eigene Änderung ist kein Hinweis"
        assert rt.wait_idle(60) and rt.status()["last_run"], "nach dem Umzug steht das Modell gleich wieder da, auch ohne Auto-Lauf"

        # Kevin benennt im Fenster um: Die App zieht den Ordner um und öffnet das Projekt am neuen Ort
        um = tmp / "Kugelbahn"
        neu.rename(um)
        app.ziel = um
        app.send({"type": "PROJECT_OPEN", "id": "a-2", "path": str(um)})
        app.wait_for(lambda h: h["type"] == "PROJECT" and h.get("path") == str(um))
        teile, wieder = aufrufe(mcp, ("parts", {}), ("parts", {}))
        assert text(teile).startswith(f"Achtung, das offene Projekt ist jetzt „Kugelbahn“: model.py liegt unter {um / 'model.py'}"), text(teile)
        assert "Achtung" not in text(wieder), "nur das nächste Ergebnis"

        falsch, leer = aufrufe(mcp, ("projekt", {"name": "X", "pfad": "Y"}), ("projekt", {}))
        assert falsch.is_error and leer.is_error and "pfad fehlt" in text(leer)
    finally:
        app.close()
        rt.close()
