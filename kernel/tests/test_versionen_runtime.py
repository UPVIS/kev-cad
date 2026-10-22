"""Versionen in der Laufzeit mit echtem Rechenprozess und Test-App: Version je Lauf, Vorschaubild, Wiederherstellen
mit Neurechnen, Vergleich mit Lauf ohne Live-Aufbau und Geisterkörpern, Meilensteine, Varianten, App-Nachrichten."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.protocol import unpack_netze
from kevcad_kernel.versionen.git import git_verfuegbar

pytestmark = pytest.mark.skipif(not git_verfuegbar()[0], reason="git fehlt")

# Testmodelle stehen physikalisch korrekt (Prüfung Stufe 2: nichts schwebt, nichts kippt)
HEAD = "from build123d import *\nfrom kevcad import show, step, param\n"
CODE1 = HEAD + 'b = param("b", 20)\nshow(Box(b, 10, 5), "Platte")\nshow(Pos(0, 0, 5) * Box(5, 5, 5), "Klotz")\n'
CODE2 = HEAD + ('b = param("b", 40)\nshow(Box(b, 10, 5), "Platte")\nshow(Pos(0, 0, 5) * Box(5, 5, 5), "Klotz")\n'
                'show(Pos(30, 0, 1.5) * Cylinder(3, 8), "Stift")\n')


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kv", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


_n = iter(range(1, 1000))


def projekt(env, code: str) -> Path:
    path = env["tmp"] / f"V{next(_n)}"
    start = env["app"].mark()
    res = env["rt"].project_new(str(path), "empty")
    assert res["ok"], res
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    env["app"].wait_for(lambda h: h["type"] == "PROJECT" and h["name"] == path.name, start=start)
    env["app"].wait_for(lambda h: h["type"] == "VERSIONEN" and Path(h["projekt"]).name == path.name, start=start)
    assert env["rt"].model_write(code)["ok"]
    return path


def warte(cond, timeout: float = 30.0) -> bool:
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        if cond():
            return True
        time.sleep(0.05)
    return False


def versionen_nachricht(env, start: int, pred) -> dict:
    return env["app"].wait_for(lambda h: h["type"] == "VERSIONEN" and pred(h), start=start)[2]


def test_lauf_legt_version_an_mit_kennzahlen_und_bild(env):
    rt, app = env["rt"], env["app"]
    p = projekt(env, CODE1)
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    assert res["version"]["nr"] == 1 and res["version"]["neu"] is True
    assert res["version"]["ms"] < 1000
    msg = versionen_nachricht(env, start, lambda h: h["versionen"] and h["versionen"][0].get("bild"))
    v = msg["versionen"][0]
    assert v["nr"] == 1 and v["aktuell"] and v["wer"] == "agent" and v["titel"] == "Erster Stand"
    assert v["kennzahlen"]["teile"] == 2 and v["params"] == {"b": 20}
    assert v["kennzahlen"]["fehler"] == 0  # Prüfstand kommt nach dem Lauf dazu
    assert Path(v["bild"]).is_file() and v["bild"].endswith("bilder/1.png")
    _, _, bild_req, bild_nutzlast = app.wait_for(lambda h: h["type"] == "VERSION_BILD_REQ", start=start)
    assert bild_req["nr"] == 1 and {t["teil"] for t in bild_req["teile"]} == {"Platte", "Klotz"}
    netze = unpack_netze(bild_req["teile"], bild_nutzlast)  # die Netze reisen mit
    assert all(len(n["triangles"]) > 0 for n in netze)
    assert msg["varianten"][0]["name"] == "Hauptstand" and msg["ungesichert"] is False
    assert warte(lambda: (p / ".kevcad" / "versionen" / "daten" / "1.json").is_file())
    assert len(list((p / ".kevcad" / "versionen" / "geometrie").glob("*.kvg"))) == 2
    # gleicher Stand: keine neue Version
    res = rt.run()
    assert res["version"] == {**res["version"], "nr": 1, "neu": False}
    # Auto-Lauf ohne Agent: Kevin
    rt._agent["connected"] = False
    (p / "model.py").write_text(CODE2)
    job = rt._submit_run(None, 0, 60, source="auto")
    job.done.wait(60)
    assert job.result["version"]["nr"] == 2
    vs = rt.versionen()["versionen"]
    assert [x["nr"] for x in vs] == [2, 1] and vs[0]["wer"] == "kevin" and vs[0]["kennzahlen"]["teile"] == 3
    assert not list((p / ".kevcad" / "versions").glob("*"))  # alte Ablage nicht mehr beschrieben


def test_wiederherstellen_rechnet_neu_und_ist_nicht_zerstoerend(env):
    rt, app = env["rt"], env["app"]
    p = projekt(env, CODE1)
    assert rt.run()["ok"]
    (p / "model.py").write_text(CODE2)
    assert rt.run()["version"]["nr"] == 2
    start = app.mark()
    t0 = time.perf_counter()
    res = rt.version_wiederherstellen("V1")
    dauer = time.perf_counter() - t0
    assert res["ok"], res
    assert res["aus"] == 1 and res["version"] == 3 and res["gesichert"] is None
    assert res["lauf"]["ok"] and res["lauf"]["teile"] == 2
    assert (p / "model.py").read_text() == CODE1
    assert sorted(x["name"] for x in rt.parts()) == ["Klotz", "Platte"]
    assert any(h["type"] == "PART_REMOVE" and h["name"] == "Stift" for h in app.since(start))
    assert dauer < 60
    vs = rt.versionen()["versionen"]
    assert vs[0]["titel"] == "Wiederhergestellt aus V1" and vs[0]["kennzahlen"]["teile"] == 2
    # zurück nach vorn: ein Klick
    res = rt.version_wiederherstellen("2")
    assert res["ok"] and (p / "model.py").read_text() == CODE2 and len(rt.parts()) == 3


def test_vergleich_mit_lauf_ohne_live_aufbau(env):
    rt, app = env["rt"], env["app"]
    p = projekt(env, CODE1)
    assert rt.run()["ok"]
    assert warte(lambda: (p / ".kevcad" / "versionen" / "daten" / "1.json").is_file())
    shutil.rmtree(p / ".kevcad" / "versionen" / "daten")  # Zwischenspeicher weg: alte Version muss neu rechnen
    shutil.rmtree(p / ".kevcad" / "versionen" / "geometrie")
    (p / "model.py").write_text(CODE2)
    assert rt.run()["ok"]
    assert rt.execute("b")["result"] == "40"
    start = app.mark()
    parts_vorher = app.mark()
    res = rt.versionen_vergleichen("V1")
    assert res["ok"], res
    assert res["params"] == [{"name": "b", "alt": 20, "neu": 40, "art": "geaendert"}]
    assert res["teile"]["neu"] == ["Stift"] and res["teile"]["weg"] == []
    assert [(g["name"], g["arten"]) for g in res["teile"]["geaendert"]] == [("Platte", ["form"])]
    assert res["geister"] == [{"teil": "Platte", "art": "alt"}]
    assert "-b = param(\"b\", 20)" in res["code"]["diff"]
    assert rt.execute("b")["result"] == "40"  # Namensraum des echten Laufs bleibt
    # nichts vom Schattenlauf ging an die App, nur der Vergleich
    neu = app.since(parts_vorher)
    assert not any(h["type"] in ("PART_UPSERT", "RUN_START", "STEP") for h in neu)
    _, _, kopf, nutzlast = app.wait_for(lambda h: h["type"] == "VERSION_VERGLEICH", start=start)
    netze = unpack_netze(kopf["geometrie"], nutzlast)
    assert kopf["geometrie"][0]["teil"] == "Platte" and kopf["geometrie"][0]["art"] == "alt"
    xs = netze[0]["positions"][:, 0]
    assert xs.max() - xs.min() == pytest.approx(20, abs=0.01)  # alte Breite
    assert kopf["teile"]["neu"] == ["Stift"] and kopf["a"]["nr"] == 1
    # jetzt liegt die alte Version im Zwischenspeicher: zweiter Vergleich ohne neuen Lauf
    t0 = time.perf_counter()
    res2 = rt.versionen_vergleichen("V1", zeigen=False)
    assert res2["ok"] and res2["geister"] == res["geister"] and time.perf_counter() - t0 < 5
    # zwei alte Versionen: ohne Geisterkörper
    (p / "model.py").write_text(CODE2.replace("Cylinder(3, 8)", "Cylinder(4, 8)"))
    assert rt.run()["ok"]
    res3 = rt.versionen_vergleichen("V1", "V2", zeigen=False)
    assert res3["ok"] and res3["geister"] == [] and res3["teile"]["neu"] == ["Stift"]


def test_meilenstein_varianten_und_app_nachrichten(env):
    rt, app = env["rt"], env["app"]
    p = projekt(env, CODE1)
    assert rt.run()["ok"]
    res = rt.meilenstein("Grundform", "zwei Teile")
    assert res == {"ok": True, "version": 1, "titel": "Grundform", "notiz": "zwei Teile", "entfernt": False}
    # Kevin aus der App: Variante von V1 anlegen, dort ändern, zurück zum Hauptstand
    start = app.mark()
    app.send({"type": "VARIANT", "id": "a-1", "aktion": "anlegen", "name": "Breit", "von": "V1"})
    ack = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-1", start=start)[2]
    assert ack["ok"], ack
    msg = versionen_nachricht(env, start, lambda h: h["variante"] == "v-breit")
    assert {v["name"]: v["aktuell"] for v in msg["varianten"]} == {"Hauptstand": False, "Breit": True}
    assert rt.wait_idle(60)
    (p / "model.py").write_text(CODE1.replace("20)", "60)"))
    assert rt.run()["version"]["nr"] == 2
    start = app.mark()
    app.send({"type": "VARIANT", "id": "a-2", "aktion": "wechseln", "name": "Hauptstand"})
    assert app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-2", start=start)[2]["ok"]
    assert (p / "model.py").read_text() == CODE1
    msg = versionen_nachricht(env, start, lambda h: h["variante"] == "haupt")
    assert [v["nr"] for v in msg["versionen"]] == [1]
    assert msg["versionen"][0]["meilenstein"]["titel"] == "Grundform"
    # Vergleich und Liste auf Anfrage
    start = app.mark()
    app.send({"type": "VERSIONEN_REQ", "id": "a-3"})
    msg = app.wait_for(lambda h: h["type"] == "VERSIONEN" and h.get("reply_to") == "a-3", start=start)[2]
    assert msg["anzahl"] == 1
    app.send({"type": "VERSION_COMPARE", "id": "a-4", "a": "V2", "b": None})
    vg = app.wait_for(lambda h: h.get("reply_to") == "a-4", start=start, timeout=120)[2]
    assert vg["type"] == "VERSION_VERGLEICH" and vg["params"][0]["alt"] == 60
    app.send({"type": "VERSION_MILESTONE", "id": "a-5", "version": "V2", "titel": "Breit probiert", "notiz": ""})
    assert app.wait_for(lambda h: h.get("reply_to") == "a-5", start=start)[2]["ok"]
    app.send({"type": "VERSION_RESTORE", "id": "a-6", "version": "V99"})
    nein = app.wait_for(lambda h: h.get("reply_to") == "a-6", start=start)[2]
    assert nein["ok"] is False and "V99" in nein["message"]


def test_uebernahme_und_nachberechnung_im_hintergrund(env):
    """Alte Stände kommen beim Öffnen ins Archiv; Kennzahlen und Vorschaubild rechnet ein eigener Prozess nach."""
    rt, app = env["rt"], env["app"]
    path = env["tmp"] / "Alt"
    path.mkdir()
    (path / "model.py").write_text(CODE2)
    (path / "kevcad.json").write_text('{"inventar_regel": false}\n')
    alt = path / ".kevcad" / "versions"
    alt.mkdir(parents=True)
    (alt / "0001-model.py").write_text(CODE1)
    (alt / "0002-model.py").write_text(CODE2)
    start = app.mark()
    assert rt.project_open(str(path))["ok"]
    vs = rt.versionen()["versionen"]
    assert [(v["nr"], v["quelle"]) for v in vs] == [(2, "uebernahme"), (1, "uebernahme")]
    res = rt.run()
    assert res["ok"] and res["version"]["nr"] == 2 and res["version"]["neu"] is False

    def nachgerechnet():
        v1 = next(v for v in rt.versionen()["versionen"] if v["nr"] == 1)
        return v1["kennzahlen"] is not None and v1["bild"] is not None

    assert warte(nachgerechnet, 180)
    v1 = next(v for v in rt.versionen()["versionen"] if v["nr"] == 1)
    assert v1["kennzahlen"]["teile"] == 2 and v1["params"] == {"b": 20}
    assert any(h["type"] == "VERSION_BILD_REQ" and h["nr"] == 1 for h in app.since(start))
    assert rt.execute("b")["result"] == "40"  # der Rechenprozess der Laufzeit blieb unberührt
    assert warte(lambda: rt._ver_rechner is None, 30)  # Hintergrundprozess wieder beendet
    # Titel: sobald beide Stände Kennzahlen haben, aus dem Inhalt (vorher aus dem Code), „Übernommener Stand“ als
    # Zusatz; die Git-Geschichte bleibt, wie sie ist
    assert warte(lambda: rt.versionen()["versionen"][0]["titel"] == "b 20 → 40 · + Stift", 30)
    vs = rt.versionen()["versionen"]
    assert vs[0]["zusatz"] == "Übernommener Stand" and vs[0]["titel_quelle"] == "auto"
    assert vs[1]["titel"] == "Erster Stand"
    assert rt._archiv.git.text("log", "--all", "--format=%s").split() == ["Übernommener", "Stand"] * 2
    msg = versionen_nachricht(env, start, lambda h: h["versionen"][0]["titel"] == "b 20 → 40 · + Stift")
    assert msg["versionen"][0]["zusatz"] == "Übernommener Stand"


def test_titel_automatisch_vom_agenten_und_kevins_meilenstein(env):
    """Automatischer Titel aus dem Inhalt, run(titel=…) mit Vorrang (der automatische als Zusatz), Läufe mit
    überschriebenen Parametern ändern die Version nicht, Kevins Meilenstein überschreibt der Agent nicht."""
    rt, app = env["rt"], env["app"]
    p = projekt(env, CODE1)
    res = rt.run()
    assert res["version"]["titel"] == "Erster Stand"
    (p / "model.py").write_text(CODE2)
    res = rt.run(titel="  Stift ergänzt,   Platte breiter ")
    assert res["ok"] and res["version"]["neu"] and res["version"]["nr"] == 2
    assert res["version"]["titel"] == "Stift ergänzt, Platte breiter"
    assert res["version"]["titel_auto"] == "b 20 → 40 · + Stift"
    v = rt.versionen()["versionen"][0]
    assert (v["titel"], v["zusatz"], v["titel_quelle"]) == ("Stift ergänzt, Platte breiter", "b 20 → 40 · + Stift",
                                                            "agent")
    # ohne Änderung: kein neuer Titel für einen Stand, der schon einen hat
    res = rt.run(titel="Noch einmal")
    assert not res["version"]["neu"] and "Titel nicht vergeben" in res["version"]["hinweis"]
    assert rt.versionen()["versionen"][0]["titel"] == "Stift ergänzt, Platte breiter"
    # Kevin speichert, der Auto-Lauf legt die Version an; danach beschreibt der Agent sie
    rt._agent["connected"] = False
    (p / "model.py").write_text(CODE2.replace("Cylinder(3, 8)", "Cylinder(4, 8)"))
    job = rt._submit_run(None, 0, 60, source="auto")
    job.done.wait(60)
    assert job.result["version"]["nr"] == 3 and job.result["version"]["titel"] == "Stift geändert"
    res = rt.run(titel="Stift dicker")
    assert res["version"]["nr"] == 3 and not res["version"]["neu"] and "hinweis" not in res["version"]
    v = rt.versionen()["versionen"][0]
    assert (v["titel"], v["zusatz"]) == ("Stift dicker", "Stift geändert")
    # nur ein Kommentar: ohne Wirkung
    (p / "model.py").write_text(CODE2.replace("Cylinder(3, 8)", "Cylinder(4, 8)") + "# Stift aus Messing\n")
    assert rt.run()["version"]["titel"] == "Code aufgeräumt (ohne Wirkung)"
    # überschriebene Parameter: die Version behält die Kennzahlen und Parameter ihrer Dateien
    res = rt.run(params={"b": 30})
    assert res["ok"] and res["version"] == {**res["version"], "nr": 4, "neu": False}
    assert rt.versionen()["versionen"][0]["params"] == {"b": 40}
    assert rt.run()["ok"]  # zurück auf den Dateistand
    # Kevin benennt die Version in der App; der Meilenstein des Agenten am Ende der Aufgabe überschreibt das nicht
    start = app.mark()
    app.send({"type": "VERSION_MILESTONE", "id": "t-1", "version": None, "titel": "Kevins Prototyp", "notiz": ""})
    assert app.wait_for(lambda h: h.get("reply_to") == "t-1", start=start)[2]["ok"]
    res = rt.meilenstein("Messingstift dokumentiert", "Kommentar ergänzt")
    assert res["ok"] and res["geschuetzt"] and res["version"] == 4 and res["titel"] == "Kevins Prototyp"
    assert "Kevins Meilenstein" in res["hinweis"]
    v = rt.versionen()["versionen"][0]
    assert v["meilenstein"]["titel"] == "Kevins Prototyp" and v["meilenstein"]["wer"] == "kevin"
    assert v["titel"] == "Messingstift dokumentiert"  # die Beschreibung des Agenten steht darunter
    # die Automatik ändert daran nichts, auch nicht beim Nachziehen
    rt._titel_nachziehen(rt._archiv)
    assert rt.versionen()["versionen"][0]["meilenstein"]["titel"] == "Kevins Prototyp"
    # nur auf Kevins ausdrücklichen Wunsch
    res = rt.meilenstein("Prototyp mit Messingstift", ersetzen=True)
    assert res["ok"] and not res.get("geschuetzt")
    assert rt.versionen()["versionen"][0]["meilenstein"]["titel"] == "Prototyp mit Messingstift"
