"""Dokument-Export (Strang P6-A2, DOKUMENTE.md, Anhang „Export“): Bausteine prüfen, Rundlauf DOC_EXPORT_REQ →
DOC_EXPORT_RES mit einer Test-App am Socket, MCP-Werkzeug ``dokument_export`` und die Testdateien der App."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import start_server, texts, wait_for, with_client

from kevcad_kernel.dokument_export import BAUSTEINE, BausteinFehler, normalisiere
from kevcad_kernel.protocol import FrameReader, check_doc_export_res, doc_export_req

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[1] / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"


def test_bausteine_normalisieren():
    alle, opt = normalisiere(None)
    assert [b["art"] for b in alle] == list(BAUSTEINE) and opt == {"format": None, "ausrichtung": None, "vorlage": None}
    assert [b["art"] for b in normalisiere("alle")[0]] == list(BAUSTEINE)
    liste, _ = normalisiere(["Bauplan", "BOM", {"art": "zeichnungen", "auswahl": ["a", "b"]}, "titelblatt"])
    assert liste == [{"art": "bauplan"}, {"art": "stueckliste"}, {"art": "zeichnungen", "auswahl": ["a", "b"]},
                     {"art": "deckblatt"}]
    liste, opt = normalisiere(["vorlage:Werkstatt", {"format": "a3", "ausrichtung": "Quer"}])
    assert liste == [] and opt == {"format": "A3", "ausrichtung": "quer", "vorlage": "Werkstatt"}
    liste, _ = normalisiere([{"art": "stueckliste", "spalten": ["pos", "benennung"]}])
    assert liste[0]["spalten"] == ["pos", "benennung"]
    for falsch, text in ((["gibtsnicht"], "unbekannt"), (["bauplan", "anleitung"], "doppelt"),
                         ([{"art": "bauplan", "auswahl": ["x"]}], "nur für zeichnungen"),
                         ([{"format": "A5"}], "A4 oder A3"), ([{"art": "stueckliste", "spalten": "pos"}], "spalten"),
                         (42, "Liste")):
        with pytest.raises(BausteinFehler, match=text):
            normalisiere(falsch)


class ExportApp(FakeApp):
    """Test-App, die DOC_EXPORT_REQ wie die echte App beantwortet (schreibt eine kleine PDF-Datei)."""

    def __init__(self, path: str, fehler: str | None = None) -> None:
        self.fehler = fehler
        self.anfragen: list[dict] = []
        super().__init__(path)
        threading.Thread(target=self._antworten, daemon=True).start()

    def _antworten(self) -> None:
        seen = 0
        while not self.closed:
            try:
                i, _, h, _ = self.wait_for(lambda h: h["type"] == "DOC_EXPORT_REQ", start=seen, timeout=0.5)
            except AssertionError:
                continue
            seen = i + 1
            self.anfragen.append(h)
            if self.fehler:
                self.send({"type": "DOC_EXPORT_RES", "reply_to": h["id"], "ok": False, "pfad": None, "seiten": 0,
                           "fehler": self.fehler})
                continue
            if h.get("ziel"):
                Path(h["ziel"]).write_bytes(b"%PDF-1.4\n%%EOF\n")
            seiten = [{"art": b["art"], "seiten": 2} for b in h["bausteine"]]
            self.send({"type": "DOC_EXPORT_RES", "reply_to": h["id"], "ok": True, "pfad": h.get("ziel"),
                       "seiten": 2 * len(seiten), "fehler": None, "bausteine": seiten,
                       "formate": {"A4 hoch": 2 * len(seiten)},
                       "gedruckt": "Druckdialog geöffnet" if h.get("drucken") else None, "hinweise": [], "ms": 50})


def verbunden(rt, app) -> None:
    app.wait_for(lambda h: h["type"] == "AGENT")
    assert wait_for(lambda: rt.status()["app_connected"], timeout=10)


@pytest.fixture
def laufzeit():
    tmp = Path(tempfile.mkdtemp(prefix="kcx", dir="/tmp"))  # Socket-Pfade sind auf 103 Zeichen begrenzt
    rt = make_runtime(str(tmp / "k.sock"), start_worker=False)
    try:
        yield rt, tmp.resolve()
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_ohne_projekt_und_ohne_app(laufzeit):
    rt, tmp = laufzeit
    assert "Kein Projekt" in rt.dokument_export()["error"]
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    assert rt.dokument_export()["error"] == "App nicht verbunden"
    assert "unbekannt" in rt.dokument_export(["gibtsnicht"])["error"]


def test_rundlauf_mit_test_app(laufzeit):
    rt, tmp = laufzeit
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = ExportApp(str(tmp / "k.sock"))
    try:
        verbunden(rt, app)
        res = rt.dokument_export(["deckblatt", "stückliste", {"art": "zeichnungen", "auswahl": ["blatt-1"]}],
                                 timeout_s=20)
        assert res["ok"], res
        ziel = (tmp / "Halter" / "output" / "Halter-dokumente.pdf").resolve()
        assert res["pfad"] == str(ziel) and ziel.read_bytes().startswith(b"%PDF")
        assert res["seiten"] == 6 and [b["art"] for b in res["bausteine"]] == ["deckblatt", "stueckliste",
                                                                                 "zeichnungen"]
        req = app.anfragen[-1]
        assert req["bausteine"][2] == {"art": "zeichnungen", "auswahl": ["blatt-1"]} and req["drucken"] is False
        assert req["id"].startswith("k-") and req["format"] is None
        # relativer Zielpfad landet in output/, Endung .pdf wird ergänzt
        res = rt.dokument_export(["bauplan"], ziel="anleitung/werkstatt", timeout_s=20)
        assert res["pfad"] == str((tmp / "Halter" / "output" / "anleitung" / "werkstatt.pdf").resolve())
        # nur drucken: kein Pfad, Druckdialog
        res = rt.dokument_export(["bauplan"], drucken=True, timeout_s=20)
        assert res["ok"] and res["pfad"] is None and res["gedruckt"] == "Druckdialog geöffnet"
        assert app.anfragen[-1]["ziel"] is None and app.anfragen[-1]["drucken"] is True
        # Vorlage und Format gehen mit
        rt.dokument_export(["vorlage:Werkstatt", {"format": "A3", "ausrichtung": "quer"}], timeout_s=20)
        assert app.anfragen[-1]["vorlage"] == "Werkstatt" and app.anfragen[-1]["format"] == "A3"
        assert app.anfragen[-1]["bausteine"] == []
    finally:
        app.close()


def test_fehler_der_app(laufzeit):
    rt, tmp = laufzeit
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = ExportApp(str(tmp / "k.sock"), fehler="Kein Bauplan: erst bauplan() rechnen")
    try:
        verbunden(rt, app)
        res = rt.dokument_export(["bauplan"], timeout_s=20)
        assert res == {"ok": False, "error": "Kein Bauplan: erst bauplan() rechnen", "bausteine": None}
    finally:
        app.close()


def test_mcp_werkzeug():
    server, fake = start_server()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        tools = {t.name: t for t in anyio.run(with_client, server.url, lambda c: c.list_tools()).tools}
        beschreibung = tools["dokument_export"].description
        assert "only when Kevin explicitly asks to print" in beschreibung and "never on your own" in beschreibung
        res = call("dokument_export", {"bausteine": ["deckblatt", "stueckliste", "bauplan"]})
        assert res.is_error is not True
        text = texts(res)[0]
        assert "PDF mit 9 Seiten: /tmp/p/output/Halter-dokumente.pdf" in text and "Stückliste 2 Seiten" in text
        assert fake.calls_of("dokument_export")[-1][0] == (["deckblatt", "stueckliste", "bauplan"], None, False)
        res = call("dokument_export", {"drucken": True})
        assert "Druckdialog geöffnet" in texts(res)[0]
        assert call("dokument_export", {"bausteine": ["gibtsnicht"]}).is_error is True
    finally:
        server.stop_thread()


def test_testdateien_der_app():
    erwartet = json.loads((FIXTURES / "fixtures.json").read_text())["export"]
    (req, _), = FrameReader().feed((FIXTURES / "doc_export_req.frame").read_bytes())
    (res, _), = FrameReader().feed((FIXTURES / "doc_export_res.frame").read_bytes())
    assert req == erwartet["req"] and res == erwartet["res"]
    assert req["type"] == "DOC_EXPORT_REQ" and req["bausteine"][2]["auswahl"] == ["seitenstange-links", "zusammenbau"]
    assert check_doc_export_res(res) == [] and res["reply_to"] == req["id"]
    assert erwartet["bausteine"] == list(BAUSTEINE)
    assert doc_export_req([], ziel=None)["drucken"] is False
