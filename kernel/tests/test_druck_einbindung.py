"""Einbindung der Druckprüfung: Prüfer „druck“ nach jedem Lauf, Schwere im Lauf, Zwischenspeicher, Bezugssystem,
lager.druckteil(ausrichtung=…), Laufergebnis, Laufzeit (KernelService.druckpruefung) und MCP-Werkzeug."""

import json
import shutil
import tempfile
import time
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from build123d import Box, Cylinder, Pos, Rot
from mcp_testutil import start_server, texts, with_client

import kevcad
from kevcad import lager
from kevcad_kernel.catalog import Catalog, builtin_dir
from kevcad_kernel.druck import anbindung
from kevcad_kernel.druck.anbindung import schwere_im_lauf
from kevcad_kernel.druck.bericht import druck_auszug, druck_text
from kevcad_kernel.mcp_tools.format import run_summary
from kevcad_kernel.pruefung.anbindung import fuer_ergebnis
from kevcad_kernel.pruefung.befund import offen
from kevcad_kernel.pruefung.pruefer import PRUEFUNGEN
from kevcad_kernel.runner import Runner

HEAD = "from build123d import *\nfrom kevcad import lager, show, param\n"
WINKEL = """
winkel = Box(40, 20, 4, align=(Align.MIN, Align.MIN, Align.MIN)) + Box(4, 20, 30, align=(Align.MIN, Align.MIN, Align.MIN))
winkel -= Pos(20, 10, 0) * Cylinder(2.5, 10)
"""


def laufe(tmp_path: Path, code: str, runner: Runner | None = None, run: int = 1, params: dict | None = None):
    """model.py ausführen und wie im Rechenprozess nach RUN_DONE prüfen: (Laufergebnis, CHECK-Kopf, Runner)."""
    (tmp_path / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": True}))
    model = tmp_path / "model.py"
    model.write_text(code, encoding="utf-8")
    runner = runner or Runner(lambda h, p=b"": None)
    res = runner.run({"run": run, "path": str(model), "code": code, "params": params or {}, "inventar_regel": True,
                      "catalog": {"builtin": str(builtin_dir()), "own": str(tmp_path / "eigen")}})
    assert res["type"] == "RUN_DONE", res.get("error")
    check, _ = runner.pruefe(run)
    assert check["state"] == "done", check
    return res, check, runner


def druck(check: dict, teil: str | None = None) -> list[dict]:
    return [b for b in check["befunde"] if (b.get("wert") or {}).get("pruefung") == "druck"
            and (teil is None or b["teile"][0] == teil)]


@pytest.fixture(autouse=True)
def frischer_speicher():
    anbindung.leeren()
    yield
    anbindung.leeren()


# ---------------------------------------------------------------------------------------------------------------------
# Schwere


@pytest.mark.parametrize("art, schwere, werte, erwartet", [
    ("bauraum", "fehler", {}, "fehler"),
    ("bauraum", "warnung", {}, "warnung"),
    ("bauraum", "hinweis", {}, "hinweis"),
    ("material", "fehler", {"grund": "harzdruck"}, "fehler"),
    ("material", "warnung", {"grund": "gehaertete_duese"}, "fehler"),
    ("material", "warnung", {"grund": "einhausung"}, "warnung"),
    ("bohrung_klein", "fehler", {}, "warnung"),
    ("ueberhang", "warnung", {}, "warnung"),
    ("elefantenfuss", "hinweis", {}, "hinweis"),
])
def test_schwere_nur_harte_gruende_sind_fehler(art, schwere, werte, erwartet):
    assert schwere_im_lauf({"art": art, "schwere": schwere, "werte": werte}) == erwartet


def test_registriert_nach_durchdringung():
    namen = [n for n, _ in PRUEFUNGEN]
    assert "druck" in namen and namen.index("druck") > namen.index("durchdringung")
    from kevcad_kernel.pruefung import lauf

    assert lauf.AKTIV is None or "druck" in lauf.AKTIV  # None: alle registrierten Prüfer laufen


# ---------------------------------------------------------------------------------------------------------------------
# Prüfer im Rechenprozess


def test_befunde_ausrichtung_und_laufergebnis(tmp_path):
    code = HEAD + WINKEL + """
show(Pos(1000, 0, 0) * lager.druckteil(winkel, "Halter/Winkel", material="petg"), "Halter/Winkel")
quer = lager.druckteil(Rot(0, 90, 0) * winkel, "Halter/Quer", material="petg", ausrichtung="-z")
show(Pos(0, 200, 0) * quer, "Halter/Quer")
show(lager.teil("platte", s=18, material="multiplex-birke").verbauen(breite=100, tiefe=100, name="Platte"), "Platte")
"""
    res, check, _ = laufe(tmp_path, code)
    teile = check["druck"]["teile"]
    assert set(teile) == {"Halter/Winkel", "Halter/Quer"}  # Platte ist kein Druckteil
    w = teile["Halter/Winkel"]
    assert w["material"] == "petg" and w["ausrichtung"]["automatisch"] is True and w["ausrichtung"]["vorgabe"] is None
    assert w["ausrichtung"]["text"] == "−Z-Seite unten" and w["ausrichtung"]["liegt_auf"].startswith("Halter/Winkel#f")
    assert "Stützfläche" in w["ausrichtung"]["begruendung"] and "Festigkeit" not in w["ausrichtung"]["begruendung"]
    assert w["ausrichtung"]["bezug"] == "druckteil" and w["kennzahlen"]["schichten"] == 150
    q = teile["Halter/Quer"]
    assert q["ausrichtung"]["automatisch"] is False and q["ausrichtung"]["vorgabe"] == "-z"
    # Jeder Befund nennt Teil, Fläche oder Ort und die Abhilfe; Arten druck_*, ids dr1 …
    alle = druck(check)
    assert alle and all(b["id"].startswith("dr") and b["art"].startswith("druck_") for b in alle)
    for b in alle:
        assert b["text"].startswith(b["teile"][0] + ": ") and b["loesung"] and b["loesung"][0].isupper()
        assert "#f" in b["text"] or " bei (" in b["text"], b["text"]
    # wie modelliert quer gelegt: waagrechte Bohrung und Auskragung sind Warnungen, kein Fehler
    arten_quer = {b["art"]: b["schwere"] for b in druck(check, "Halter/Quer")}
    assert arten_quer.get("druck_waagrechte_bohrung") == "warnung" and arten_quer.get("druck_kragarm") == "warnung"
    # nur die Druckprüfung zählt hier; Schweben und Kippen des frei stehenden Testmodells meldet die Prüfung Stufe 2
    assert not offen([b for b in check["befunde"] if b["art"].startswith("druck_")])
    # Punkte in Weltkoordinaten (Pos(1000, …) im Modell)
    orte = [b["ort"] for b in druck(check, "Halter/Winkel") if b["ort"]]
    assert orte and all(990 <= o[0] <= 1045 for o in orte)
    # Laufergebnis: Ausrichtung mit Begründung je Teil, Druck-Hinweise nur über druckpruefung
    pr = fuer_ergebnis(check)
    assert pr["druck"]["teile"]["Halter/Quer"]["ausrichtung"]["begruendung"]
    assert pr["druck"]["festigkeit"]["petg"].startswith("Festigkeit:")
    assert all(b["schwere"] != "hinweis" for b in pr["befunde"] if b["wert"].get("pruefung") == "druck")
    assert pr["druck"]["hinweise_nur_in_druckpruefung"] == sum(1 for b in alle if b["schwere"] == "hinweis") > 0
    nur_druck = {**pr, "befunde": [b for b in pr["befunde"] if b["art"].startswith("druck_")]}  # Stufe 2 ausblenden
    text, _, failed = run_summary({"ok": True, "run": 1, "parts": [], "pruefung": nur_druck})
    assert not failed and "Druckprüfung (Bambu Lab P1P): 2 Druckteile, 0 Fehler" in text
    assert "- Ausrichtung Halter/Quer: −Z-Seite unten (vorgegeben: -z)." in text
    json.dumps(check, allow_nan=False)


def test_harte_gruende_sperren_den_export(tmp_path):
    code = HEAD + """
show(lager.druckteil(Box(300, 300, 10), "Platte gross", material="petg"), "Platte gross")
show(Pos(400, 0, 0) * lager.druckteil(Box(20, 20, 5), "Clip CF", material="pa-cf"), "Clip CF")
show(Pos(500, 0, 0) * lager.druckteil(Box(20, 20, 5), "Clip Harz", material="petg", verfahren="harzdruck"),
     "Clip Harz")
show(Pos(600, 0, 0) * lager.druckteil(Box(20, 20, 5) - Cylinder(0.4, 10), "Clip Loch", material="petg"), "Clip Loch")
show(Pos(700, 0, 0) * lager.druckteil(Box(20, 20, 5), "Clip ASA", material="asa"), "Clip ASA")
"""
    _, check, _ = laufe(tmp_path, code)
    fehler = {(b["teile"][0], b["art"]) for b in offen(check["befunde"]) if b["art"].startswith("druck_")}
    assert fehler == {("Platte gross", "druck_bauraum"), ("Clip CF", "druck_material"), ("Clip Harz", "druck_material")}
    bau = next(b for b in druck(check, "Platte gross") if b["art"] == "druck_bauraum")
    assert "passt nicht in den Bauraum" in bau["text"] and bau["loesung"].startswith("Teilen")
    loch = next(b for b in druck(check, "Clip Loch") if b["art"] == "druck_bohrung_klein")
    assert loch["schwere"] == "warnung" and loch["wert"]["schwere_druckpruefung"] == "fehler"
    asa = next(b for b in druck(check, "Clip ASA") if b["art"] == "druck_material")
    assert asa["schwere"] == "warnung" and asa["wert"]["grund"] == "einhausung"
    assert "Druckteil passt nicht in den Bauraum" in check["zusammenfassung"]
    assert check["druck"]["teile"]["Platte gross"]["ok"] is False and check["druck"]["teile"]["Clip ASA"]["ok"]
    from kevcad_kernel.pruefung.text import export_sperre

    assert export_sperre(offen(check["befunde"])).startswith("Export verweigert. Prüfung: ")


def test_zwischenspeicher_ueber_laeufe_und_kopien(tmp_path):
    code = HEAD + WINKEL + """
x = param("x", 0)
for i in range(4):  # vier gleiche Teile: einmal gerechnet
    show(Pos(x + 60 * i, 0, 0) * lager.druckteil(winkel, f"Winkel {i}", material="petg"), f"Winkel {i}")
"""
    _, c1, runner = laufe(tmp_path, code)
    assert c1["druck"]["neu_geprueft"] == 1 and c1["druck"]["aus_zwischenspeicher"] == 3
    t0 = time.perf_counter()
    _, c2, _ = laufe(tmp_path, code, runner, run=2, params={"x": 25})  # ganze Gruppe verschoben
    warm_ms = (time.perf_counter() - t0) * 1000
    assert c2["druck"]["neu_geprueft"] == 0 and c2["druck"]["aus_zwischenspeicher"] == 4
    assert c2["druck"]["dauer_ms"] < 20 and warm_ms < 5000
    # gleiche Befunde, Orte mitverschoben
    o1 = [b["ort"] for b in druck(c1, "Winkel 0") if b["ort"]]
    o2 = [b["ort"] for b in druck(c2, "Winkel 0") if b["ort"]]
    assert [b["text"].split(" bei ")[0] for b in druck(c1)] == [b["text"].split(" bei ")[0] for b in druck(c2)]
    assert o1 and all(abs(b[0] - a[0] - 25) < 1e-6 for a, b in zip(o1, o2))
    # anderes Material: neu
    _, c3, _ = laufe(tmp_path, code.replace('material="petg"', 'material="pla"'), runner, run=3)
    assert c3["druck"]["neu_geprueft"] == 1


def test_bezug_ist_die_druckteil_form(tmp_path):
    """Gedreht in die Baugruppe gesetzt: Ausrichtung und „wie modelliert“ gelten für die Form aus druckteil."""
    code = HEAD + WINKEL + """
show(lager.druckteil(winkel, "Gerade", material="petg", ausrichtung="-z"), "Gerade")
show(Pos(200, 0, 0) * Rot(90, 0, 30) * lager.druckteil(winkel, "Gedreht", material="petg", ausrichtung="-z"),
     "Gedreht")
"""
    _, check, _ = laufe(tmp_path, code)
    g, d = check["druck"]["teile"]["Gerade"], check["druck"]["teile"]["Gedreht"]
    assert d["ausrichtung"]["unten"] == g["ausrichtung"]["unten"] == [0.0, 0.0, -1.0]
    assert d["kennzahlen"] == g["kennzahlen"]
    assert check["druck"]["aus_zwischenspeicher"] == 1  # gleiche Form, gleiche Drehung der druckteil-Form
    assert [b["art"] for b in druck(check, "Gerade")] == [b["art"] for b in druck(check, "Gedreht")]


def test_druckteile_als_kinder_einer_baugruppe(tmp_path):
    """Baugruppe aus Druckteilen, verschoben und gedreht gezeigt (Kinder über baum.kinder, Phase 3)."""
    code = HEAD + WINKEL + """
a = lager.druckteil(winkel, "Links", material="petg", ausrichtung="-z")
b = lager.druckteil(Pos(60, 0, 0) * winkel, "Rechts", material="petg")
gruppe = Compound(children=[a, b])
show(Pos(0, 300, 0) * Rot(0, 0, 90) * gruppe, "Halter")
"""
    _, check, _ = laufe(tmp_path, code)
    teile = check["druck"]["teile"]
    assert set(teile) == {"Halter/Links", "Halter/Rechts"}
    li, re = teile["Halter/Links"], teile["Halter/Rechts"]
    assert li["ausrichtung"]["vorgabe"] == "-z" and li["ausrichtung"]["bezug"] == "druckteil"
    assert re["ausrichtung"]["automatisch"] and re["kennzahlen"]["schichten"] == li["kennzahlen"]["schichten"] == 150
    orte = [b["ort"] for b in druck(check) if b["ort"]]
    assert orte and all(240 <= o[1] <= 420 and -25 <= o[0] <= 1 for o in orte), orte  # in der Welt: gedreht, verschoben


def test_ausrichtung_als_vektor(tmp_path):
    code = HEAD + WINKEL + """
show(lager.druckteil(winkel, "Winkel", material="petg", ausrichtung=(1, 0, 0)), "Winkel")
"""
    _, check, _ = laufe(tmp_path, code)
    a = check["druck"]["teile"]["Winkel"]["ausrichtung"]
    assert a["automatisch"] is False and a["text"] == "+X-Seite unten" and a["vorgabe"].startswith("Richtung (1;")


def test_ungueltige_vorgabe_und_unbekanntes_material():
    """Ohne lager (etwa ältere Erfassung): ungültige Fläche → automatisch mit Warnung; Material ohne Regeln → Warnung."""
    from kevcad_kernel.pruefung.koerper import koerper_aus_form
    from kevcad_kernel.pruefung.pruefer import pruefe

    form = Box(20, 10, 5) - Cylinder(2, 10)
    rund = next(i for i, f in enumerate(form.faces()) if f.geom_type.name != "PLANE")
    ks = [koerper_aus_form("A", form, {"druckteil": True, "druck_material": "petg", "druck_ausrichtung": rund}),
          koerper_aus_form("B", Pos(50, 0, 0) * form, {"druckteil": True, "druck_material": "holz"})]
    erg, _ = pruefe(ks, {}, {"pruefungen": ("druck",)})
    arten = {(b["teile"][0], b["art"], b["schwere"]) for b in erg["befunde"]}
    assert ("A", "druck_ausrichtung", "warnung") in arten and ("B", "druck_material", "warnung") in arten
    assert erg["druck"]["teile"]["A"]["ausrichtung"]["automatisch"] is True and "B" not in erg["druck"]["teile"]
    assert "keine Druckregeln" in next(b["text"] for b in erg["befunde"] if b["teile"] == ["B"])
    assert erg["druck"]["teile"]["A"]["ausrichtung"]["bezug"] == "welt"


# ---------------------------------------------------------------------------------------------------------------------
# lager.druckteil(ausrichtung=…)


@pytest.fixture
def cat(tmp_path):
    c = Catalog(builtin_dir(), tmp_path / "eigen", tmp_path)
    kevcad._hooks["catalog"] = lambda: c
    yield c
    kevcad._hooks.clear()


def test_druckteil_ausrichtung_wird_geprueft(cat):
    stuecke = []
    kevcad._hooks["lager"] = lambda piece, shape: stuecke.append(piece)
    form = Box(20, 10, 5) - Cylinder(2, 10)
    for gut in (None, "-z", "+X", "−y", 0, (0, 1, 0), Rot(90, 0, 0)):
        lager.druckteil(form, "Clip", material="petg", ausrichtung=gut)
    assert [p.ausrichtung for p in stuecke[:6]] == [None, "-z", "+X", "−y", 0, (0.0, 1.0, 0.0)]
    rund = next(i for i, f in enumerate(form.faces()) if f.geom_type.name != "PLANE")
    for schlecht, text in (("oben", "unbekannt"), (99, "gibt es nicht"), (rund, "nicht eben"), ((0, 0, 0), "keine Richtung"),
                           (True, "keine Ausrichtung"), ("x y", "unbekannt")):
        with pytest.raises(lager.LagerError, match=text):
            lager.druckteil(form, "Clip", material="petg", ausrichtung=schlecht)


# ---------------------------------------------------------------------------------------------------------------------
# Werkzeug: Auszug, Text, Laufzeit, MCP


def test_auszug_und_text(tmp_path):
    code = HEAD + WINKEL + """
show(lager.druckteil(winkel, "Halter/Winkel", material="petg"), "Halter/Winkel")
show(Pos(100, 0, 0) * lager.druckteil(Box(20, 20, 5), "Halter/Clip", material="pla"), "Halter/Clip")
klotz = lager.teil("platte", s=18, material="multiplex-birke").verbauen(breite=10, tiefe=10, name="Halter/Klotz")
show(Pos(0, 100, 0) * klotz, "Halter/Klotz")
"""
    _, check, _ = laufe(tmp_path, code)
    namen = ["Halter/Winkel", "Halter/Clip", "Halter/Klotz"]
    alle = druck_auszug(check, None, namen)
    assert alle["ok"] and [t["name"] for t in alle["teile"]] == ["Halter/Winkel", "Halter/Clip"]
    assert set(alle["materialien"]) == {"petg", "pla"}
    eins = druck_auszug(check, "Halter/Winkel", namen)
    assert [t["name"] for t in eins["teile"]] == ["Halter/Winkel"] and set(eins["materialien"]) == {"petg"}
    b = eins["teile"][0]["befunde"][0]
    assert b["refs"] and all(r.startswith("Halter/Winkel#f") for r in b["refs"])
    assert len(druck_auszug(check, "Halter", namen)["teile"]) == 2  # Gruppe
    kein = druck_auszug(check, "Halter/Klotz", namen)
    assert not kein["ok"] and "kein Druckteil" in kein["error"]
    tipp = druck_auszug(check, "Halter/Winkl", namen)
    assert not tipp["ok"] and "Halter/Winkel" in tipp["error"]
    assert not druck_auszug(None)["ok"] and not druck_auszug({"state": "failed", "message": "x"})["ok"]
    text = druck_text(alle)
    for stueck in ("Druckprüfung Lauf 1 (Bambu Lab P1P): 2 Druckteile", "Halter/Winkel – PETG:", "  Ausrichtung: ",
                   "  Begründung: ", "  Kennzahlen: ", "Abhilfe: ", "Materialeinstellungen PETG:", "Festigkeit:"):
        assert stueck in text, stueck
    leer = druck_auszug({"run": 2, "state": "done", "befunde": []})
    assert leer["ok"] and leer["teile"] == [] and "keine Druckteile" in druck_text(leer)


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcdr", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_laufzeit_run_und_druckpruefung(env):
    rt, app = env["rt"], env["app"]
    path = env["tmp"] / "Druck"
    assert rt.project_new(str(path), "empty")["ok"]
    groesse = 'g = param("g", 40)\n'
    code = HEAD + groesse + WINKEL.replace("Box(40, 20, 4", "Box(g, 20, 4") + """
show(lager.druckteil(winkel, "Halter/Winkel", material="petg"), "Halter/Winkel")
"""
    assert rt.model_write(code)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    pr = res["pruefung"]
    assert pr["state"] == "done" and pr["druck"]["teile"]["Halter/Winkel"]["ausrichtung"]["text"] == "−Z-Seite unten"
    _, _, fertig, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h["state"] == "done", start=start)
    assert fertig["druck"]["teile"]["Halter/Winkel"]["kennzahlen"]["schichten"] == 150  # App bekommt es mit
    d = rt.druckpruefung()
    assert d["ok"] and d["run"] == res["run"] and [t["name"] for t in d["teile"]] == ["Halter/Winkel"]
    assert d["teile"][0]["befunde"] and d["materialien"]["petg"]["druckhinweise"]
    assert not rt.druckpruefung("Gibtsnicht")["ok"]
    assert rt.export(["stl"])["ok"]  # nur Hinweise: Export geht
    # zu groß für den P1P: Fehler, Export gesperrt
    res2 = rt.run(params={"g": 400})
    assert res2["ok"] and "Druckteil passt nicht in den Bauraum" in res2["pruefung"]["zusammenfassung"]
    assert run_summary(res2)[2] is True
    ex = rt.export(["stl"])
    assert not ex["ok"] and "Export verweigert" in ex["error"]
    assert rt.druckpruefung("Halter/Winkel")["teile"][0]["ok"] is False


def call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_mcp_werkzeug_druckpruefung():
    server, fake = start_server()
    try:
        res = call(server.url, "druckpruefung")
        assert res.is_error is True and "erst run aufrufen" in texts(res)[0]
        call(server.url, "run")
        res = call(server.url, "druckpruefung")
        assert res.is_error is False
        text = texts(res)[0]
        assert text.startswith("Druckprüfung Lauf 3 (Bambu Lab P1P): 1 Druckteil, 0 Fehler, 1 Warnung, 0 Hinweise")
        assert "Ausrichtung: −Z-Seite unten (automatisch, liegt auf Halter/Clip (Druck)#f0)." in text
        assert "[Warnung] Halter/Clip (Druck): Überhang 70° an Fläche #f4" in text and "Abhilfe: Fase 45°" in text
        assert res.structured_content["teile"][0]["befunde"][0]["refs"] == ["Halter/Clip (Druck)#f4"]
        res = call(server.url, "druckpruefung", {"teil": "Halter/Platte"})
        assert res.is_error is True and "kein Druckteil" in texts(res)[0]
        assert fake.calls_of("druckpruefung")[-1] == (("Halter/Platte",), {})
    finally:
        server.stop_thread()
