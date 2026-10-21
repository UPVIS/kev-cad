"""Phase 3 über die volle Laufzeit (Rechenprozess, Test-App am Socket, Test-Katalog): Anlegen als Vorschlag, Freigabe,
Ersatzkörper im Lauf, CAD suchen (Links bzw. TraceParts-Attrappe), DOWNLOAD_SEEN und Übernahme aus dem Download-Ordner
(ZIP mit STEP in Zoll), ZUKAUF_NEU und ZUKAUF_CAD aus der App, ZUKAUF_STATUS nach dem Verbinden, MCP über den echten
Server."""

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from build123d import Box, Compound, Cylinder, Pos, export_step
from mcp_testutil import texts, with_client
from test_zukauf_quellen import SCHLUESSEL, Attrappe

from kevcad_kernel.baum import transformieren
from kevcad_kernel.server import KevcadHTTPServer

HEAD = "from build123d import *\nfrom kevcad import lager, show, step, param\n"
FELDER = {"name": "ALUTEC Transportroller 05200", "hersteller": "ALUTEC", "mpn": "05200", "gtin": "4014688052004",
          "masse": "61 x 41 x 12,8 cm", "preis": {"je_stueck": "24,99 €", "brutto": True}, "gewicht": "1,8 kg",
          "bezugspunkte": {"oben": {"pos": [0, 0, 128], "richtung": [0, 0, 1], "hinweis": "Ladefläche"}}}
MODELL = HEAD + """
wagen = lager.zukauf("alutec-05200")
show(wagen.verbauen("Rollwagen"), "Rollwagen")
"""


def step_zoll(path: Path) -> Path:
    platte = Pos(0, 0, 113) * Box(610, 410, 30)
    platte.label = "Platte"
    rolle = Pos(250, 150, 49) * Cylinder(20, 98)
    rolle.label = "Rolle"
    asm = transformieren(Compound(children=[platte, rolle], label="05200").scale(1 / 25.4))
    export_step(asm, str(path))
    return path


@pytest.fixture(scope="module")
def p3():
    tmp = Path(tempfile.mkdtemp(prefix="kc3", dir=tempfile.gettempdir()))
    own = tmp / "eigen"
    own.mkdir()
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, own=own)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp, "sock": sock}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def env(p3, tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setenv("KEVCAD_DOWNLOADS_DIR", str(downloads))
    monkeypatch.setenv("KEVCAD_SECRETS_FILE", str(tmp_path / "keine-secrets.env"))
    p3["rt"].zukauf.traceparts_transport = None
    p3["rt"].zukauf._seen.clear()  # von der App gemeldete Downloads früherer Tests
    p3["downloads"] = downloads
    return p3


_n = iter(range(1, 1000))


def new_project(env, code: str = MODELL) -> Path:
    path = env["tmp"] / f"Z{next(_n)}"
    assert env["rt"].project_new(str(path), "empty")["ok"]
    assert env["rt"].model_write(code)["ok"]
    return path


def request(app, header: dict, timeout: float = 60):
    start = app.mark()
    app.send(header)
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == header["id"], start=start, timeout=timeout)
    return reply, start


def statuses(app, start: int, zid: str) -> list[dict]:
    return [h for h in app.since(start) if h["type"] == "ZUKAUF_STATUS" and h["id"] == zid]


def wait_status(app, start: int, zid: str, zustand: str) -> dict:
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "ZUKAUF_STATUS" and h["id"] == zid and h["zustand"] == zustand,
                              start=start)
    return h


# ---------------------------------------------------------------------------------------------------------------------


def test_anlegen_freigeben_bauen_cad_aus_downloads(env):
    rt, app = env["rt"], env["app"]
    proj = new_project(env)
    start = app.mark()
    res = rt.zukauf_anlegen(url="https://www.beispiel-shop.de/p/05200", felder=FELDER)
    assert res["ok"] and res["angelegt"], res
    item = res["item"]
    assert item["id"] == "alutec-05200" and item["status"] == "vorgeschlagen" and item["ebene"] == "projekt"
    assert item["masse"] == {"l": 610, "b": 410, "h": 128} and item["gewicht"] == 1800
    assert item["preis"] == {"je_stueck": 24.99, "brutto": True, "waehrung": "EUR", "stand": item["preis"]["stand"],
                             "quelle": "https://www.beispiel-shop.de/p/05200"}
    st = wait_status(app, start, "alutec-05200", "angelegt")
    assert st["name"] == "ALUTEC Transportroller 05200" and "reply_to" not in st
    # nur vorgeschlagen: der Lauf bricht ab
    run = rt.run()
    assert not run["ok"] and "wartet auf Kevins Freigabe" in run["error"]["message"]
    # Kevin gibt frei (Lagerkatalog der App)
    reply, _ = request(app, {"type": "CATALOG_SAVE", "id": "a-1", "kind": "teil", "ebene": "projekt",
                             "entry": {**{k: v for k, v in item.items() if k != "ebene"}, "status": "frei"}})
    assert reply["ok"], reply
    start = app.mark()
    run = rt.run()
    assert run["ok"] and run["inventar_verstoesse"] == []
    part = next(h for h in app.since(start) if h["type"] == "PART_UPSERT")
    assert part["name"] == "Rollwagen (vereinfacht)" and part["zukauf"]["cad"] == "vereinfacht"
    _, _, bom, _ = app.wait_for(lambda h: h["type"] == "BOM" and h.get("run") == run["run"], start=start)
    line, = bom["lines"]
    assert line["art"] == "zukaufteil" and line["stock_id"] == "alutec-05200" and line["vereinfacht"] is True
    # CAD suchen ohne Schlüssel: Links, wartet_auf_cad
    start = app.mark()
    found = rt.cad_suchen("alutec-05200")
    assert found["zustand"] == "wartet_auf_cad" and found["cad_links"][0]["url"].endswith("/p/05200")
    assert any("TRACEPARTS_API_KEY" in h for h in found["hinweise"])
    st = wait_status(app, start, "alutec-05200", "wartet_auf_cad")
    assert st["erwartet"] == ["step", "stp", "zip"] and st["cad_links"]
    assert json.loads((proj / ".kevcad" / "zukauf-status.json").read_text())["alutec-05200"]["zustand"] == \
        "wartet_auf_cad"
    # App neu verbunden (eine Verbindung zugleich): der Kernel meldet das wartende Teil wieder
    app.close()
    app = env["app"] = FakeApp(env["sock"])
    _, _, again, _ = app.wait_for(lambda h: h["type"] == "ZUKAUF_STATUS")
    assert again["id"] == "alutec-05200" and again["zustand"] == "wartet_auf_cad"
    kinds = [h["type"] for h in app.since(0)]
    assert kinds.index("ZUKAUF_STATUS") > kinds.index("AGENT")
    # Kevin lädt ein ZIP herunter; die App meldet es, Claude übernimmt ohne Pfad
    step = step_zoll(env["tmp"] / "05200.step")
    archiv = env["downloads"] / "ALUTEC_05200_CAD.zip"
    with zipfile.ZipFile(archiv, "w") as zf:
        zf.write(step, "CAD/ALUTEC_05200.stp")
    app.send({"type": "DOWNLOAD_SEEN", "pfad": str(archiv), "groesse": archiv.stat().st_size,
              "zeit": "2026-10-21T21:14:03+02:00"})
    start = app.mark()
    got = rt.cad_uebernehmen("alutec-05200")
    assert got["ok"], got
    assert got["pruefung"]["skala"] == 25.4 and any("Zoll" in h for h in got["hinweise"])
    assert got["item"]["cad"]["quelle"] == "download" and got["item"]["cad"]["datei"] == \
        "zukauf/alutec-05200/ALUTEC_05200.stp"
    assert got["item"]["status"] == "frei"  # das CAD ändert nichts an der Freigabe
    assert (proj / "zukauf" / "alutec-05200" / "ALUTEC_05200.stp").is_file()
    assert (proj / "zukauf" / "alutec-05200" / "ALUTEC_05200.brep").is_file()
    st = wait_status(app, start, "alutec-05200", "importiert")
    assert st["cad_links"] == []
    start = app.mark()
    run = rt.run()
    assert run["ok"] and run["inventar_verstoesse"] == []
    names = sorted(h["name"] for h in app.since(start) if h["type"] == "PART_UPSERT")
    assert names == ["Rollwagen/Platte", "Rollwagen/Rolle"]
    part = next(h for h in app.since(start) if h["type"] == "PART_UPSERT")
    assert part["zukauf"]["cad"] == "hersteller" and part["bbox"]["max"][2] == pytest.approx(128, abs=0.01)
    assert rt.zukauf.offene_status() == []
    liste = rt.zukauf_liste("alutec")
    assert liste["items"][0]["cad_art"] == "hersteller" and liste["items"][0]["zustand"] == "importiert"


def test_app_neu_und_cad(env):
    rt, app = env["rt"], env["app"]
    proj = new_project(env, HEAD + 'show(lager.zukauf("happy-people-77805").verbauen("Nudel"), "Nudel")\n')
    felder = {"id": "happy-people-77805", "art": "zukaufteil", "name": "Schwimmnudel", "hersteller": "Happy People",
              "mpn": "77805", "gtin": "4008332778051", "status": "frei", "masse": {"d": 70, "l": 1600},
              "ersatz": {"form": "zylinder", "masse": {"d": 70, "l": 1600}}}
    reply, start = request(app, {"type": "ZUKAUF_NEU", "id": "a-2", "eingabe": "4008332778051", "felder": felder,
                                 "ebene": "projekt"})
    assert reply["type"] == "ACK" and reply["ok"], reply
    app.wait_for(lambda h: h["type"] == "ZUKAUF_STATUS" and h["zustand"] == "wartet_auf_cad", start=start)
    seq = [h["zustand"] for h in statuses(app, start, "happy-people-77805")]
    kinds = [h["type"] for h in app.since(start)]
    assert seq[:2] == ["angelegt", "wartet_auf_cad"] and kinds.index("ACK") < kinds.index("ZUKAUF_STATUS")
    entry = rt.catalog.item("happy-people-77805")
    assert entry["status"] == "frei" and entry["ebene"] == "projekt"
    assert json.loads((proj / "katalog.json").read_text())["teile"][0]["status"] == "frei"
    assert rt.run()["ok"]
    # ZUKAUF_CAD: Kevin bestätigt eine Datei, die nicht passt (falsche Maße) → fehler
    falsch = step_zoll(env["tmp"] / "falsch.step")
    reply, start = request(app, {"type": "ZUKAUF_CAD", "id": "a-3", "teil": "happy-people-77805",
                                 "pfad": str(falsch)})
    assert reply["ok"]
    _, _, st, _ = app.wait_for(lambda h: h["type"] == "ZUKAUF_STATUS" and h["zustand"] in ("fehler", "importiert"),
                               start=start)
    assert st["zustand"] == "fehler" and "passt nicht" in st["text"]
    # Das Teil wartete auf sein CAD: danach wieder wartet_auf_cad (mit Links), damit die App weiter beobachtet
    _, _, st2, _ = app.wait_for(lambda h: h["type"] == "ZUKAUF_STATUS" and h["zustand"] == "wartet_auf_cad",
                                start=start)
    assert st2["text"].startswith("falsch.step nicht übernommen:") and st2["cad_links"]
    assert [s["zustand"] for s in rt.zukauf.offene_status()] == ["wartet_auf_cad"]
    assert not (proj / "zukauf" / "happy-people-77805" / "falsch.step").exists()
    reply, _ = request(app, {"type": "ZUKAUF_CAD", "id": "a-4", "teil": "gibtsnicht", "pfad": str(falsch)})
    assert reply["ok"] is False
    # ungültige EAN (falsche Prüfziffer) wird abgelehnt, wie in der App
    reply, _ = request(app, {"type": "ZUKAUF_NEU", "id": "a-6", "eingabe": "4005187052009",
                             "felder": {**felder, "id": "alutec-05200", "mpn": "05200", "gtin": "4005187052009"},
                             "ebene": "projekt"})
    assert reply["ok"] is False and "Prüfziffer stimmt nicht" in reply["message"]
    res = rt.zukauf_anlegen(gtin="4005187052009", felder={"name": "X", "hersteller": "ALUTEC", "mpn": "05200",
                                                          "masse": {"l": 1, "b": 1, "h": 1}})
    assert res["ok"] is False and "Prüfziffer" in res["error"]
    # Normteil statt Zukaufteil
    res = rt.zukauf_anlegen(mpn="ISO 4762 M8x40")
    assert res["ok"] and not res["angelegt"] and res["stock_id"] == "schraube-iso4762-m8"
    reply, _ = request(app, {"type": "ZUKAUF_NEU", "id": "a-5", "eingabe": "DIN 912 M8x40",
                             "felder": {"name": "DIN 912 M8x40", "mpn": "DIN 912 M8x40", "masse": {"d": 13, "l": 48}},
                             "ebene": "projekt"})
    assert reply["ok"] is False and "Normteil" in reply["message"]


def test_traceparts_automatisch(env, tmp_path, monkeypatch):
    rt, app = env["rt"], env["app"]
    new_project(env)
    secrets = tmp_path / "secrets.env"
    secrets.write_text(f"TRACEPARTS_API_KEY={SCHLUESSEL}\nTRACEPARTS_TENANT_UID=11111111-2222-3333-4444-555555555555\n"
                       "TRACEPARTS_USER_EMAIL=kevin@example.com\n", encoding="utf-8")
    monkeypatch.setenv("KEVCAD_SECRETS_FILE", str(secrets))
    step = step_zoll(tmp_path / "tp.step")
    zbytes = tmp_path / "tp.zip"
    with zipfile.ZipFile(zbytes, "w") as zf:
        zf.write(step, "05200.stp")
    rt.zukauf.traceparts_transport = Attrappe(warten=1, datei=zbytes.read_bytes())
    rt.zukauf.traceparts_sleep = lambda s: None
    res = rt.zukauf_anlegen(felder=FELDER)
    assert res["ok"] and res["angelegt"]
    start = app.mark()
    found = rt.cad_suchen("alutec-05200")
    assert found["ok"] and found["zustand"] == "importiert", found
    assert found["powered_by"] == "powered by TraceParts" and found["item"]["cad"]["quelle"] == "traceparts"
    assert found["item"]["cad"]["traceparts_id"] == "FAM-1" and "TraceParts" in found["item"]["cad"]["lizenz"]
    assert found["item"]["status"] == "vorgeschlagen"
    assert SCHLUESSEL not in json.dumps(found) and SCHLUESSEL not in json.dumps(app.since(start))
    wait_status(app, start, "alutec-05200", "importiert")


def test_mcp_ueber_echten_server(env):
    rt = env["rt"]
    new_project(env)
    html = (Path(__file__).resolve().parent / "zukauf_testdaten" / "obi_muster.html").read_text(encoding="utf-8")
    server = KevcadHTTPServer(rt, 0)
    server.start_in_thread()
    try:
        async def go(c):
            return {
                "html": await c.call_tool("zukauf_html", {"url": "https://www.baumarkt-muster.example/p/7654321",
                                                          "html": html, "anlegen": True}),
                "liste": await c.call_tool("zukauf_liste", {}),
                "suchen": await c.call_tool("cad_suchen", {"id": "alutec-05200"}),
                "leer": await c.call_tool("cad_uebernehmen", {"id": "alutec-05200", "minuten": 5}),
                "norm": await c.call_tool("zukauf_anlegen", {"mpn": "ISO 4762 M8x40"}),
            }

        r = anyio.run(with_client, server.url, go)
    finally:
        server.stop_thread()
    text = texts(r["html"])[0]
    assert "Gelesen aus json-ld:" in text and "- Herstellernummer: 05200" in text
    assert "- Maße: 610 × 410 × 128 mm" in text and "24,99 € brutto" in text
    assert "Angelegt als alutec-05200 (Vorschlag, wartet auf Kevins Freigabe)" in text
    assert "alutec-05200" in texts(r["liste"])[0] and "wartet auf Freigabe" in texts(r["liste"])[0]
    assert "Links zum Herunterladen" in texts(r["suchen"])[0] and "cad_uebernehmen" in texts(r["suchen"])[0]
    assert r["leer"].is_error and "Keine neue STEP- oder ZIP-Datei der letzten 5 Minuten" in texts(r["leer"])[0]
    assert "Normteil" in texts(r["norm"])[0] and "lager.teil('schraube-iso4762-m8')" in texts(r["norm"])[0]


def test_katalogaenderung_waehrend_eines_laufs(env):
    """Zweites übernommenes CAD, während der Lauf nach dem ersten noch rechnet: Der laufende Lauf hat den alten Katalog
    gelesen, also muss ein neuer folgen (vorher wurde die Anfrage mit dem laufenden Lauf gleichen Stands zusammengelegt
    und das zweite CAD erschien erst beim nächsten Speichern)."""
    import hashlib

    from kevcad_kernel.runtime import Job

    rt = env["rt"]
    proj = new_project(env)
    code = (proj / "model.py").read_text(encoding="utf-8")
    laufend = Job(kind="run", code=code, source="auto", timeout_s=60, path=str(rt._project.model),
                  file_hash=hashlib.sha1(code.encode("utf-8")).hexdigest()[:12])
    with rt._jobs_cond:
        alt, rt._current = rt._current, laufend
    try:
        assert rt._submit_run(None, 0, 60, source="auto") is laufend  # gleicher Stand: zusammengelegt
        neu = rt._submit_run(None, 0, 60, source="auto", katalog_neu=True)
        assert neu is not laufend and neu.key == laufend.key
    finally:
        with rt._jobs_cond:
            if rt._current is laufend:
                rt._current = alt
    assert neu.done.wait(60)


def test_pruefung_mit_zukaufteil(env):
    """Zusammenführung mit der Kollisionsprüfung: Ersatzkörper werden wie alle Teile geprüft; erlaubt_ueberlappung
    findet das Teil auch unter dem Namen aus show() (ohne „(vereinfacht)“)."""
    rt = env["rt"]
    code = ("from build123d import *\nfrom kevcad import lager, show, erlaubt_ueberlappung\n"
            "nudel = lager.zukauf(\"happy-people-77805\")\n"
            "show(nudel.verbauen(\"Nudel\"), \"Nudel\")\n"
            "klemme = lager.druckteil(Pos(0, 30, 50) * Box(20, 20, 20), \"Klemme\", material=\"petg\")\n"
            "show(klemme, \"Klemme\")\n")
    new_project(env, code)
    felder = {"id": "happy-people-77805", "art": "zukaufteil", "name": "Schwimmnudel", "hersteller": "Happy People",
              "mpn": "77805", "status": "frei", "masse": {"d": 70, "l": 1600},
              "ersatz": {"form": "zylinder", "masse": {"d": 70, "l": 1600}}}
    assert rt.zukauf.anlegen(felder=felder, proposal=False, status_senden=False)["ok"]
    res = rt.run()
    assert res["ok"], res
    assert res["inventar_verstoesse"] == []
    (b,) = [b for b in res["pruefung"]["befunde"] if b["art"] == "durchdringung"]
    assert sorted(b["teile"]) == ["Klemme", "Nudel (vereinfacht)"]
    erlaubt = 'erlaubt_ueberlappung("Nudel", "Klemme", grund="Test: Klemme sitzt auf Schaum")\n'
    assert rt.model_write(code + erlaubt)["ok"]
    res2 = rt.run()
    assert res2["ok"] and res2["pruefung"]["befunde"] == [], res2["pruefung"]["befunde"]
    assert len(res2["pruefung"]["erlaubt"]) == 1
