"""V2-6 Sprach-Feedback (PROTOCOL.md, „V2-6 Sprach-Feedback“): Format, Stand, Sperre während des Sprechens, Warten,
Abholen, Abbrechen, Text für den Agenten, Hintergrundbefehl."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from kevcad_kernel import feedback_cli
from kevcad_kernel.mcp_tools.feedback_tools import feedback_text, hintergrund_befehl, stand_text
from kevcad_kernel.protocol import (
    FEEDBACK_WARTEN_MAX_S, check_feedback_message, check_feedback_paket, feedback_beispiel, feedback_beispiele,
)
from kevcad_kernel.server import KevcadHTTPServer, build_server
from mcp import Client

CODE = """from build123d import *
from kevcad import show
show(Box(20, 10, 5), "Klotz")
"""
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
NAME = "fb-20261105-223011"


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcfb", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240)
    e = {"rt": rt, "tmp": tmp, "sock": sock, "app": FakeApp(sock), "n": 0}
    e["app"].wait_for(lambda h: h["type"] == "HELLO")
    yield e
    e["app"].close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def projekt(env) -> Path:
    env["n"] += 1
    path = env["tmp"] / f"P{env['n']}"
    assert env["rt"].project_new(str(path), "empty")["ok"]
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    (path / "model.py").write_text(CODE)
    assert env["rt"].project_open(str(path))["ok"]
    assert env["rt"].run()["ok"]
    yield path
    stand(env, "aus")


def stand(env, wert: str, sitzung: str = "s-1", grund: str | None = None) -> None:
    grund = grund or ("fertig" if wert == "aus" else None)
    env["app"].send({"type": "FEEDBACK_STAND", "sitzung": sitzung, "stand": wert, "seit": time.time(), "grund": grund})
    ende = time.monotonic() + 5
    while env["rt"].feedback_stand()["stand"] != wert:
        assert time.monotonic() < ende
        time.sleep(0.005)


def paket_schreiben(projekt: Path, name: str = NAME, **anders: Any) -> dict[str, Any]:
    p = feedback_beispiel()
    p.update({"name": name, "bild": {"datei": f"{name}.jpg", "breite": 4, "hoehe": 2}, **anders})
    ordner = projekt / "feedback"
    ordner.mkdir(exist_ok=True)
    (ordner / f"{name}.jpg").write_bytes(JPEG)
    (ordner / f"{name}.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return p


def melden(env, projekt: Path, name: str = NAME) -> None:
    env["app"].send({"type": "FEEDBACK_PAKET", "sitzung": "s-1", "name": name,
                     "datei": str(projekt / "feedback" / f"{name}.json"), "saetze": 2, "striche": 2, "dauer_s": 9.5})


# -- Format ------------------------------------------------------------------------------------------------------------


def test_beispiel_und_rahmen_sind_gueltig():
    assert check_feedback_paket(feedback_beispiel()) == []
    for _, kopf, nutz, _ in feedback_beispiele():
        assert check_feedback_message(kopf, nutz) == []


@pytest.mark.parametrize("aendern, teil", [
    (lambda p: p.update(format="x"), "format"),
    (lambda p: p.update(name="anders"), "name"),
    (lambda p: p.update(wortzeiten="genau"), "wortzeiten"),
    (lambda p: p["worte"][0].update(satz=9), "satz"),
    (lambda p: p["saetze"][0]["bezuege"][1].update(strich=9), "Strich"),
    (lambda p: p["saetze"][0]["bezuege"].extend([p["saetze"][0]["bezuege"][0]] * 6), "Zeiger"),
    (lambda p: p["mausweg"][1].update(t=0.1), "mausweg"),
    (lambda p: p["striche"][0].update(punkte=[]), "Punkte"),
    (lambda p: p["abschnitte"].append({"von": 2.0, "bis": 99.0}), "abschnitt"),
])
def test_ungueltige_pakete_fallen_auf(aendern, teil):
    p = copy.deepcopy(feedback_beispiel())
    aendern(p)
    assert any(teil in zeile for zeile in check_feedback_paket(p))


def test_stand_ohne_grund_und_grund_ohne_aus_fallen_auf():
    kopf = {"type": "FEEDBACK_STAND", "sitzung": "s", "stand": "aus", "seit": 1.0, "grund": None}
    assert check_feedback_message(kopf)
    assert check_feedback_message({**kopf, "stand": "pause", "grund": "fertig"})
    assert check_feedback_message({**kopf, "stand": "laut"})


# -- Text --------------------------------------------------------------------------------------------------------------


def test_text_nennt_satz_zeiger_strich_und_bleibt_knapp():
    text = feedback_text(feedback_beispiel(), aktueller_lauf=7)
    assert "Kevin ist fertig: 2 Sätze, 2 Striche, 0:09" in text
    assert "„Mach das hier höher.“" in text
    assert "„hier“ = Halter/Lasche#f3 bei (120; 4; 62)" in text or "„hier“ = Halter/Lasche#f3 bei (120; 4; 63)" in text
    assert "Strich 1 auf Halter/Lasche, 84 mm" in text or "Strich 1 auf Halter/Lasche, 85 mm" in text
    assert "ausgewählt: Halter/Lasche" in text
    assert "Ohne Satz: Strich 2 in der Bildebene" in text
    assert "Im Bild: 2 Teile, 1 ausgeblendet" in text
    assert "Refs gelten" not in text
    assert len(text) < 700


def test_text_warnt_bei_neuem_lauf():
    assert "Refs gelten für Lauf 7, aktuell ist Lauf 9" in feedback_text(feedback_beispiel(), aktueller_lauf=9)


def test_stand_text():
    assert stand_text({"stand": "aus", "offen": 0}) == ""
    assert "spricht gerade (seit 12 s)" in stand_text({"stand": "spricht", "seit_s": 12.0, "offen": 0})
    assert "Pause" in stand_text({"stand": "pause", "offen": 0})
    assert "2 Feedbacks wartet" in stand_text({"stand": "aus", "offen": 2})


# -- Stand und Sperre --------------------------------------------------------------------------------------------------


def test_sperre_solange_kevin_spricht(env, projekt):
    rt = env["rt"]
    stand(env, "spricht")
    assert rt.status()["feedback"]["stand"] == "spricht"
    t0 = time.monotonic()
    res = rt.run()
    assert res["kevin_spricht"] and not res["ok"] and time.monotonic() - t0 < 0.2
    assert rt.view_command("view", {"standard": "top"})["kevin_spricht"]
    assert rt.view_command("focus", {"refs": ["Klotz"]})["kevin_spricht"]
    assert rt.project_open(str(projekt))["kevin_spricht"]
    assert rt.project_open(str(projekt), reply_to="a-1")["ok"], "Kevins eigene Aktionen gehen weiter"
    assert rt.view_command("annotate", {"kind": "label", "points": [[0, 0, 0]], "text": "x", "id": "a"})["ok"]
    stand(env, "pause")
    assert rt.view_command("view", {"standard": "top"})["ok"], "in der Pause arbeitet der Agent weiter"


def test_auto_lauf_wartet_bis_kevin_fertig_ist(env, projekt):
    rt = env["rt"]
    rt.configure(auto_run=True)
    try:
        vorher = rt.status()["last_run"]["run"]
        stand(env, "spricht")
        (projekt / "model.py").write_text(CODE.replace("Box(20", "Box(30"))
        time.sleep(0.9)  # Entprellen und Prüfen des Auto-Laufs sind vorbei
        assert rt.status()["last_run"]["run"] == vorher, "kein Lauf, solange er spricht"
        stand(env, "aus")
        ende = time.monotonic() + 30
        while rt.status()["last_run"]["run"] == vorher or rt.status()["kernel"] != "ready":
            assert time.monotonic() < ende, "der Auto-Lauf kommt nach dem Sprechen"
            time.sleep(0.05)
    finally:
        rt.configure(auto_run=False)


def test_ohne_app_spricht_niemand_mehr(env, projekt):
    stand(env, "spricht")
    env["rt"]._feedback_verbindung_weg()
    assert env["rt"].feedback_stand()["stand"] == "aus"
    assert env["rt"].run()["ok"]


def test_ungueltiger_stand_aendert_nichts(env, projekt):
    env["app"].send({"type": "FEEDBACK_STAND", "sitzung": "s-1", "stand": "laut", "seit": 1.0, "grund": None})
    env["app"].send({"type": "FEEDBACK_PAKET", "sitzung": "s-1", "name": "kaputt"})
    time.sleep(0.1)
    assert env["rt"].feedback_stand()["stand"] == "aus"


# -- Warten und Abholen ------------------------------------------------------------------------------------------------


def test_warten_wacht_sofort_auf(env, projekt):
    rt = env["rt"]
    ergebnis: dict[str, Any] = {}

    def warten() -> None:
        ergebnis.update(rt.feedback_warten(30))
        ergebnis["wach"] = time.monotonic()

    faden = threading.Thread(target=warten)
    faden.start()
    time.sleep(0.2)
    paket_schreiben(projekt)
    t0 = time.monotonic()
    melden(env, projekt)
    faden.join(5)
    assert ergebnis["da"] and ergebnis["name"] == NAME
    assert ergebnis["wach"] - t0 < 0.2, "wacht auf die Meldung hin auf, nicht im Takt"


def test_zeitablauf_ist_kein_fehler_und_nennt_den_stand(env, projekt):
    rt = env["rt"]
    t0 = time.monotonic()
    assert rt.feedback_warten(0.2)["da"] is False
    assert 0.15 < time.monotonic() - t0 < 1.0
    stand(env, "spricht")
    assert rt.feedback_warten(0)["stand"] == "spricht"


def test_abbruch_beendet_das_warten_und_holt_nichts(env, projekt):
    abbruch = threading.Event()
    ergebnis: dict[str, Any] = {}
    faden = threading.Thread(target=lambda: ergebnis.update(env["rt"].feedback_warten(30, abbruch)))
    faden.start()
    time.sleep(0.1)
    abbruch.set()
    faden.join(2)
    assert not faden.is_alive() and ergebnis["da"] is False


def test_zuerst_das_aelteste_und_abgeholt_bleibt_abgeholt(env, projekt):
    rt = env["rt"]
    paket_schreiben(projekt, "fb-20261105-223012")
    paket_schreiben(projekt, "fb-20261105-223011-10")
    paket_schreiben(projekt, "fb-20261105-223011-2")
    paket_schreiben(projekt, "fb-20261105-223011")
    namen = [rt.feedback_holen()["name"] for _ in range(4)]
    assert namen == ["fb-20261105-223011", "fb-20261105-223011-2", "fb-20261105-223011-10", "fb-20261105-223012"]
    assert rt.feedback_holen()["leer"]
    daten = json.loads((projekt / "feedback" / "abgeholt.json").read_text())
    assert daten["format"] == "kevcad-feedback-abgeholt/1" and len(daten["pakete"]) == 4
    assert sorted(p.name for p in (projekt / "feedback").iterdir() if p.name.endswith(".tmp")) == []


def test_holen_liefert_bild_und_nochmal_dasselbe(env, projekt):
    rt = env["rt"]
    paket_schreiben(projekt)
    res = rt.feedback_holen()
    assert res["bild"] == JPEG and res["paket"]["name"] == NAME and res["offen"] == 0
    assert rt.feedback_holen(nochmal=True)["name"] == NAME
    assert rt.feedback_holen()["leer"]
    assert rt.feedback_stand()["offen"] == 0


def test_offene_pakete_ueberleben_einen_neustart(env, projekt):
    """Sitzung ohne wartenden Agenten: Das Paket liegt im Ordner, ein neuer Kernel findet es."""
    paket_schreiben(projekt)
    env["rt"]._fb_zuletzt.clear()
    assert env["rt"].feedback_stand() | {"seit_s": None} == {"stand": "aus", "sitzung": None, "seit_s": None, "offen": 1,
                                                             "name": NAME}
    assert env["rt"].feedback_holen()["name"] == NAME
    env["rt"]._fb_zuletzt.clear()
    assert env["rt"].feedback_holen(nochmal=True)["name"] == NAME, "auch nach einem Neustart"


def test_halbe_dateien_gelten_nicht_und_kaputte_halten_nichts_auf(env, projekt):
    rt = env["rt"]
    ordner = projekt / "feedback"
    ordner.mkdir()
    (ordner / f".{NAME}.json.tmp").write_text("{")
    (ordner / "notizen.json").write_text("{}")
    assert rt.feedback_stand()["offen"] == 0
    (ordner / f"{NAME}.json").write_text("{")
    paket_schreiben(projekt, "fb-20261105-223012")
    res = rt.feedback_holen()
    assert res["ok"] is False and NAME in res["error"]
    assert rt.feedback_holen()["name"] == "fb-20261105-223012"


# -- MCP und Hintergrundbefehl -----------------------------------------------------------------------------------------


def aufruf(env, name: str, **argumente: Any):
    async def go():
        async with Client(build_server(env["rt"]), raise_exceptions=True) as c:
            return await c.call_tool(name, argumente)

    return anyio.run(go)


def text(res) -> str:
    return "\n".join(b.text for b in res.content if getattr(b, "type", None) == "text")


def test_werkzeug_gibt_text_und_bild(env, projekt):
    paket_schreiben(projekt)
    res = aufruf(env, "feedback", warten_s=0)
    assert not res.is_error
    assert "Kevin ist fertig: 2 Sätze" in text(res) and str(projekt / "feedback" / f"{NAME}.json") in text(res)
    assert [b.mime_type for b in res.content if getattr(b, "type", None) == "image"] == ["image/jpeg"]
    assert res.structured_content["saetze"] == 2


def test_werkzeug_bei_zeitablauf_nennt_stand_und_befehl(env, projekt):
    stand(env, "pause")
    res = aufruf(env, "feedback", warten_s=0)
    assert not res.is_error
    assert "Noch kein Feedback" in text(res) and "Pause" in text(res) and "kevcad-feedback" in text(res)


def test_werkzeug_und_status_waehrend_kevin_spricht(env, projekt):
    stand(env, "spricht")
    res = aufruf(env, "run")
    assert res.is_error and "Kevin spricht gerade" in text(res)
    res = aufruf(env, "view", standard="top")
    assert res.is_error and "Kevin spricht gerade" in text(res)
    status = text(aufruf(env, "status"))
    assert "Kevin spricht gerade" in status and "kevcad-feedback" in status


def test_abgebrochenes_warten_laesst_das_paket_offen(env, projekt):
    async def go():
        async with Client(build_server(env["rt"]), raise_exceptions=True) as c:
            with anyio.move_on_after(0.3):
                await c.call_tool("feedback", {"warten_s": 30})

    anyio.run(go)
    paket_schreiben(projekt)
    melden(env, projekt)
    time.sleep(0.3)
    assert env["rt"].feedback_stand()["offen"] == 1


def test_grenze_der_wartezeit_liegt_unter_der_lesezeit_der_bruecke():
    from kevcad_kernel.bridge import LESEZEIT_S

    assert FEEDBACK_WARTEN_MAX_S < LESEZEIT_S


def test_hintergrundbefehl_endet_mit_dem_paket(env, projekt):
    server = KevcadHTTPServer(env["rt"], port=0).start_in_thread()
    try:
        ergebnis: dict[str, Any] = {}
        faden = threading.Thread(target=lambda: ergebnis.update(feedback_cli.warten(server.port, 20) or {}))
        faden.start()
        time.sleep(0.3)
        paket_schreiben(projekt)
        melden(env, projekt)
        faden.join(5)
        assert ergebnis["da"] and ergebnis["name"] == NAME and ergebnis["saetze"] == 2 and ergebnis["striche"] == 2
        assert env["rt"].feedback_stand()["offen"] == 1, "der Befehl holt nichts ab"
        assert feedback_cli.main(["--port", str(server.port), "--warten-s", "5"]) == 0
        env["rt"].feedback_holen()
        assert feedback_cli.main(["--port", str(server.port), "--warten-s", "0.2"]) == 2
    finally:
        server.stop_thread()


def test_hintergrundbefehl_uebersteht_einen_neustart(env, projekt):
    """Kev CAD läuft beim Start noch nicht: Der Befehl fragt weiter, bis der Port da ist."""
    from kevcad_kernel.server import bind_socket

    sock = bind_socket("127.0.0.1", 0)
    port = sock.getsockname()[1]
    sock.close()
    paket_schreiben(projekt)
    ergebnis: dict[str, Any] = {}

    def warten() -> None:
        ergebnis.update(feedback_cli.warten(port, 20, erneut_s=0.05) or {})

    faden = threading.Thread(target=warten)
    faden.start()
    time.sleep(0.2)
    server = KevcadHTTPServer(env["rt"], port=port).start_in_thread()
    try:
        faden.join(5)
        assert ergebnis.get("da")
    finally:
        server.stop_thread()


def test_befehl_nennt_den_port():
    assert hintergrund_befehl(47824).endswith('kevcad-feedback" --port 47824')
