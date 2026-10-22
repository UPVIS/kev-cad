"""Drucken (Phase 8) über die volle Laufzeit (Rechenprozess, Test-App am Socket) und über den MCP-Server: PRINTER_STATUS
beim Verbinden, PRINTER_CONFIG, PRINT_JOB_REQ mit dem Ersatzweg je Material (Bambu-Studio-Attrappe), PRINT_JOB_ASK aus
MCP ``drucken``, PRINT_CONTROL gesperrt. Kein echter Drucker, kein echtes Bambu Studio (nichts wird geöffnet)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from drucker_testutil import bambu_attrappe
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.protocol import check_drucker_message

MODELL = '''from build123d import *
from kevcad import lager, show
show(lager.druckteil(Pos(0, 0, 3) * Box(30, 20, 6), "Halter/Clip (Druck)", material="petg"), "Halter/Clip (Druck)")
show(lager.druckteil(Pos(60, 0, 2) * Box(20, 20, 4), "Halter/Kappe (Druck)", material="petg"), "Halter/Kappe (Druck)")
'''


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcdk", dir=tempfile.gettempdir())).resolve()
    app_bambu = bambu_attrappe(tmp)
    alt = {k: os.environ.get(k) for k in ("KEVCAD_BAMBU_STUDIO", "KEVCAD_DRUCKER_CACHE", "KEVCAD_DRUCKER_SSDP")}
    os.environ.update(KEVCAD_BAMBU_STUDIO=str(app_bambu), KEVCAD_DRUCKER_CACHE=str(tmp / "cache"),
                      KEVCAD_DRUCKER_SSDP="0")
    sock = str(tmp / "k.sock")
    try:
        rt = make_runtime(sock)
    finally:
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    geoeffnet: list[Path] = []
    rt._drucker._oeffnen = geoeffnet.append  # nie das echte Bambu Studio öffnen
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp, "geoeffnet": geoeffnet}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def anfrage(app, header: dict, typ: str = "ACK", timeout: float = 30):
    start = app.mark()
    app.send(header)
    _, _, h, _ = app.wait_for(lambda h: h.get("reply_to") == header["id"] and h["type"] == typ, start=start,
                              timeout=timeout)
    return h


def test_drucken_ueber_die_laufzeit(env):
    rt, app = env["rt"], env["app"]
    _, _, st, _ = app.wait_for(lambda h: h["type"] == "PRINTER_STATUS")
    assert st["konfiguriert"] is False and check_drucker_message(st) == []
    ack = anfrage(app, {"type": "PRINTER_CONFIG", "id": "a-1", "drucker": {
        "id": "p1p", "name": "P1P", "modell": "C11", "ip": "192.0.2.10", "weg": "a", "status_lesen": False}})
    assert ack["ok"] and "Weg A" in ack["message"]
    st = anfrage(app, {"type": "PRINTER_STATUS_REQ", "id": "a-2"}, "PRINTER_STATUS")
    assert st["konfiguriert"] and st["verbindung"] == "aus" and st["drucker"]["ip"] == "192.0.2.10"

    # ohne Projekt: abgelehnt
    ack = anfrage(app, {"type": "PRINT_JOB_REQ", "id": "a-3", "platten": [], "weg": "a", "bestaetigt": False})
    assert not ack["ok"] and "Kein Projekt" in ack["message"]

    assert rt.project_new(str(env["tmp"] / "Halter"), "empty")["ok"]
    assert rt.model_write(MODELL)["ok"]
    res = rt.run()
    assert res["ok"], str({k: v for k, v in res.items() if k not in ("parts", "steps")})
    # ohne Druckvorschau gibt es je Material eine Platte (hier nur PETG)
    ack = anfrage(app, {"type": "PRINT_JOB_REQ", "id": "a-4", "platten": [2], "weg": "a", "bestaetigt": False})
    assert ack["ok"]
    _, _, r, _ = app.wait_for(lambda h: h["type"] == "PRINT_JOB_RES" and h["reply_to"] == "a-4", start=0)
    start = app.mark()
    assert not r["ok"] and "1 bis 1" in r["fehler"] and check_drucker_message(r) == []
    # alle Platten vorbereiten, dann bestätigen
    anfrage(app, {"type": "PRINT_JOB_REQ", "id": "a-5", "platten": [], "weg": "a", "bestaetigt": False})
    _, _, r, _ = app.wait_for(lambda h: h["type"] == "PRINT_JOB_RES" and h["reply_to"] == "a-5", start=start)
    assert r["ok"] and r["schritt"] == "vorbereitet" and r["platten"] == []
    if not callable(getattr(rt, "druck_export", None)):  # Ersatzweg ohne Druckvorschau
        assert any("Bambu Studio richtet" in x and "2 Teile, PETG" in x for x in r["hinweise"])
    anfrage(app, {"type": "PRINT_JOB_REQ", "id": "a-6", "platten": [], "weg": "a", "bestaetigt": True, "filament": {"petg": "bambu-petg-basic"},
                  "auftrag": r["auftrag"]})
    _, _, r2, _ = app.wait_for(lambda h: h["type"] == "PRINT_JOB_RES" and h["reply_to"] == "a-6", start=start)
    assert r2["ok"] and r2["schritt"] == "geoeffnet", r2
    ziel = Path(r2["datei"])
    assert ziel == env["tmp"] / "Halter" / "output" / "Halter-platten.gcode.3mf" and ziel.exists()
    assert env["geoeffnet"] == [ziel]
    st = rt.drucker_status()
    assert st["ok"] and st["auftrag"]["zustand"] == "geoeffnet"

    # Steuern bei Weg A: gesperrt, nichts gesendet
    ack = anfrage(app, {"type": "PRINT_CONTROL", "id": "a-7", "aktion": "pause"})
    assert not ack["ok"] and "Weg A" in ack["message"]

    # MCP drucken: öffnet nur den Dialog (PRINT_JOB_ASK), die App bestätigt das Öffnen
    def antworte():
        _, _, frage, _ = app.wait_for(lambda h: h["type"] == "PRINT_JOB_ASK", start=start, timeout=20)
        assert check_drucker_message(frage) == []
        app.send({"type": "ACK", "reply_to": frage["id"], "ok": True, "message": "Dialog offen"})

    t = threading.Thread(target=antworte)
    t.start()
    res = rt.drucken([2], "a", "Kevin will die Kappe drucken")
    t.join()
    assert res["ok"] and res["zustand"] == "wartet" and "Kevin" in res["meldung"]
    assert rt.drucker_status()["auftrag"]["von"] == "agent"
    assert env["geoeffnet"] == [ziel]  # nichts Neues geöffnet
    assert not rt.drucken([1], "b")["ok"]
    ack = anfrage(app, {"type": "PRINT_CONTROL", "id": "a-8", "aktion": "verwerfen", "auftrag": res["auftrag"]})
    assert ack["ok"] and rt.drucker_status()["auftrag"]["zustand"] == "verworfen"


def test_quelle_aus_der_druckvorschau(env, tmp_path):
    """Naht zu V-K: ``druck_export`` liefert ein Bambu-Projekt je Material; mehrere Materialien → Fehler mit Wahl."""
    import zipfile

    rt = env["rt"]
    if rt._project is None:
        assert rt.project_new(str(env["tmp"] / "Halter"), "empty")["ok"]
    projekt = tmp_path / "p.3mf"
    with zipfile.ZipFile(projekt, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({"printer_model": "Bambu Lab P1P",
                                                                   "printer_settings_id": "Bambu Lab P1P 0.4 nozzle"}))
    aufrufe = []

    def export_ein(ziel=None, platten=None, filament=None):
        aufrufe.append((ziel, platten, filament))
        return {"ok": True, "pfad": str(projekt), "pfade": [str(projekt)], "platten": [1, 2], "fehler": None,
                "dateien": [{"pfad": str(projekt), "material": "petg", "filament": "Generic PETG @BBL P1P",
                             "platten": [1, 2]}], "hinweise": ["PETG: in Bambu Studio geprüft"]}

    def export_zwei(ziel=None, platten=None, **_):
        return {"ok": True, "pfad": "a.3mf", "platten": [1, 2], "fehler": None,
                "dateien": [{"pfad": "a.3mf", "material": "petg", "platten": [1]},
                            {"pfad": "b.3mf", "material": "pla", "platten": [2]}]}

    try:
        rt.druck_export = export_ein
        q = rt._drucker_quelle([], tmp_path / "q")
        assert q.eingaben == [projekt] and q.mit_einstellungen and not q.anordnen and q.platten == [1, 2]
        assert q.hinweise == ["PETG: in Bambu Studio geprüft"] and aufrufe[0][1] == []
        assert aufrufe[0][0].endswith("Halter-platten.3mf") and aufrufe[0][2] == "vorschau"
        rt.druck_export = export_zwei
        from kevcad_kernel.drucker.dienst import QuelleFehler

        with pytest.raises(QuelleFehler, match=r"PETG: Platte 1; PLA: Platte 2"):
            rt._drucker_quelle([], tmp_path / "q")
        rt.druck_export = lambda ziel=None, platten=None, **_: {  # V-K ohne Bambu Studio: je Platte eine Datei
            "ok": True, "pfad": "a.3mf", "platten": [1, 2], "fehler": None,
            "dateien": [{"pfad": "a.3mf", "material": "petg", "platten": [1]},
                        {"pfad": "b.3mf", "material": "petg", "platten": [2]}]}
        with pytest.raises(QuelleFehler, match="je Platte eine eigene Datei"):
            rt._drucker_quelle([], tmp_path / "q")
        rt.druck_export = lambda ziel=None, platten=None, **_: {"ok": False,
                                                                "fehler": "Keine Druckteile im Modell."}
        with pytest.raises(QuelleFehler, match="Keine Druckteile"):
            rt._drucker_quelle([1], tmp_path / "q")
    finally:
        del rt.druck_export


def call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_mcp_drucker_status_und_drucken():
    server, fake = start_server()
    try:
        res = call(server.url, "drucker_status")
        assert res.is_error is False
        text = texts(res)[0]
        assert text.startswith("Drucker: P1P Werkstatt (P1P) unter 192.168.178.40, Cloud-Modus, Firmware 01.10.00.00.")
        assert "Druck: druckt, 42 %, Schicht 41/98, noch 1 h 2 min" in text and "Kamera: nicht genutzt" in text
        assert "B = direkt, gesperrt" in text
        assert res.structured_content["druck"]["zustand"] == "druckt"
        res = call(server.url, "drucken", {"platten": [1], "grund": "Kevin will drucken"})
        assert res.is_error is False and "Dialog „Drucken …“" in texts(res)[0] and "j-1" in texts(res)[0]
        assert fake.calls_of("drucken")[-1] == (([1], "a", "Kevin will drucken"), {})
        res = call(server.url, "drucken", {"weg": "b"})
        assert res.is_error is True and "Weg B" in texts(res)[0]
    finally:
        server.stop_thread()
