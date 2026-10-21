"""Bauplan (Strang P6-B, DOKUMENTE.md „Bauplan“): Gerüst am Gestell mit Bohrungen, Montagefolge mit Unterbaugruppe,
blockierter Einführweg, Reihenfolge nach Verschieben, verdeckter Werkzeugzugang, Erhalten fester Schritte, Protokoll
(BAUPLAN_REQ/BAUPLAN/BAUPLAN_EDIT/BAUPLAN_PRUEFEN/DOCS), MCP und die Testdateien der App.

Eine Laufzeit für das ganze Modul (der Rechenprozess braucht beim ersten Start bis zu einer Minute), je Modell ein
eigenes Projekt im Temp-Ordner, Test-Katalog wie die übrigen Laufzeit-Tests.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import anyio
import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime
from fake_service import FakeService
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.bauplan import datei
from kevcad_kernel.bauplan.wege import WegPruefer, standsicherheit
from kevcad_kernel.protocol import FrameReader, bauplan_beispiel, unpack_bauplan

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[1] / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"

GESTELL = '''"""Gestell aus Vierkantrohr mit Rahmen (Gehrung), Deckel und vier Schrauben M8 durch Rahmen und Deckel."""
from build123d import *
from kevcad import lager, param, show, step

breite = param("breite", 800)
tiefe = param("tiefe", 600)
hoehe = param("hoehe", 900)
rohr = lager.teil("vierkantrohr", a=40, s=3, material="stahl-s235")
platte = lager.teil("platte", s=18, material="multiplex-birke")
schraube = lager.teil("schraube-iso4762-m8")
mutter = lager.teil("mutter-iso4032-m8")
scheibe = lager.teil("scheibe-iso7089-m8")
a = rohr.masse["a"]
s = platte.masse["s"]
z_rahmen = hoehe - s - a
z_mitte = z_rahmen + a / 2
punkte = [(x, y * (tiefe / 2 - a / 2)) for y in (-1, 1) for x in (-breite / 4, breite / 4)]
loch = Cylinder(4.5, 200)
step("Beine")
for lage, x, y in (("vorn links", -1, -1), ("vorn rechts", 1, -1), ("hinten links", -1, 1), ("hinten rechts", 1, 1)):
    name = f"Gestell/Bein {lage}"
    show(Pos(x * (breite / 2 - a / 2), y * (tiefe / 2 - a / 2), 0) * rohr.verbauen(laenge=z_rahmen, name=name), name)
step("Rahmen mit Gehrung")
lagen = {
    "hinten": (breite, Pos(-breite / 2, tiefe / 2 - a / 2, z_mitte) * Rot(0, 90, 0)),
    "vorn": (breite, Pos(-breite / 2, -(tiefe / 2 - a / 2), z_mitte) * Rot(0, 90, 0) * Rot(0, 0, 180)),
    "rechts": (tiefe, Pos(breite / 2 - a / 2, -tiefe / 2, z_mitte) * Rot(-90, 0, 0) * Rot(0, 0, -90)),
    "links": (tiefe, Pos(-(breite / 2 - a / 2), -tiefe / 2, z_mitte) * Rot(-90, 0, 0) * Rot(0, 0, 90)),
}
for seite, (laenge, lage) in lagen.items():
    name = f"Gestell/Rahmen {seite}"
    leiste = lage * rohr.verbauen(laenge=laenge, name=name, gehrung=(45, 45))
    if seite in ("vorn", "hinten"):
        leiste -= [Pos(x, y, z_mitte) * loch for x, y in punkte if (y > 0) == (seite == "hinten")]
    show(leiste, name)
step("Deckel")
deckel = Pos(0, 0, hoehe - s) * platte.verbauen(breite=breite, tiefe=tiefe, name="Deckel")
deckel -= [Pos(x, y, hoehe) * loch for x, y in punkte]
show(deckel, "Deckel")
step("Schrauben")
for i, (x, y) in enumerate(punkte, 1):
    name = f"Schrauben/M8x70 {i}"
    show(Pos(x, y, z_rahmen) * Rot(180, 0, 0) * schraube.verbauen(laenge=70, name=name), name)
    sch = scheibe.verbauen(name=f"Schrauben/Scheibe {i}")
    bb = sch.bounding_box()
    show(Pos(x, y, hoehe - bb.min.Z) * sch, f"Schrauben/Scheibe {i}")
    mu = mutter.verbauen(name=f"Schrauben/Mutter {i}")
    bm = mu.bounding_box()
    show(Pos(x, y, hoehe + bb.size.Z - bm.min.Z) * mu, f"Schrauben/Mutter {i}")
'''

# Kugel in einer geschlossenen Kammer: kommt in keiner Richtung an ihren Platz
KAEFIG = '''from build123d import *
from kevcad import lager, show
unten = (Align.CENTER, Align.CENTER, Align.MIN)
kasten = Box(100, 100, 60, align=unten) - Pos(0, 0, 15) * Box(60, 60, 30, align=unten)
show(lager.druckteil(kasten, "Kasten", material="petg"), "Kasten")
show(lager.druckteil(Pos(0, 0, 25) * Sphere(10), "Kugel", material="petg"), "Kugel")
'''

# Platte, Hülse, Stift in der Hülse, Deckel auf der Hülse: der Stift muss vor dem Deckel hinein
STAPEL = '''from build123d import *
from kevcad import lager, param, show
unten = (Align.CENTER, Align.CENTER, Align.MIN)
h = param("h", 50)
platte = Box(120, 120, 10, align=unten)
huelse = Pos(0, 0, 10) * Cylinder(15, h, align=unten) - Pos(0, 0, 9) * Cylinder(10.25, h + 2, align=unten)
stift = Pos(0, 0, 10) * Cylinder(10, h - 5, align=unten)
deckel = Pos(0, 0, 10 + h) * Box(40, 40, 5, align=unten)
show(lager.druckteil(platte, "Platte", material="petg"), "Platte")
show(lager.druckteil(huelse, "Hülse", material="petg"), "Hülse")
show(lager.druckteil(stift, "Stift", material="petg"), "Stift")
show(lager.druckteil(deckel, "Deckel", material="petg"), "Deckel")
'''

# Mutter in einer engen Tasche: der Schlüssel passt nicht hinein
TASCHE = '''from build123d import *
from kevcad import lager, show
unten = (Align.CENTER, Align.CENTER, Align.MIN)
schraube = lager.teil("schraube-iso4762-m8")
mutter = lager.teil("mutter-iso4032-m8")
sockel = Pos(-20, 0, 0) * Box(60, 100, 40, align=unten)
platte = Pos(0, 0, 40) * Box(100, 100, 20, align=unten)
platte -= Pos(30, 0, 0) * Cylinder(4.5, 200)
platte -= Pos(30, 0, 52) * Cylinder(8.0, 20, align=unten)
show(lager.druckteil(sockel, "Sockel", material="petg"), "Sockel")
show(lager.druckteil(platte, "Platte", material="petg"), "Platte")
show(Pos(30, 0, 40) * Rot(180, 0, 0) * schraube.verbauen(laenge=30, name="Schraube"), "Schraube")
mu = mutter.verbauen(name="Mutter")
show(Pos(30, 0, 52.2 - mu.bounding_box().min.Z) * mu, "Mutter")
'''


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcbp", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def oeffne(env, name: str, code: str, inventar: bool = True) -> dict:
    rt = env["rt"]
    proj = env["tmp"] / name
    assert rt.project_new(str(proj), "empty")["ok"]
    assert rt.model_write(code)["ok"]
    if not inventar:
        assert rt.set_inventory_rule(False)["ok"]
    res = rt.run()
    assert res["ok"], res.get("error")
    rt._pruef.warte(res["run"], 120)
    return res


def schritte(plan: dict, art: str) -> list[dict]:
    return next(a["schritte"] for a in plan["abschnitte"] if a["art"] == art)


def befunde(plan: dict) -> list[dict]:
    return [b for _, s in datei.alle_schritte(plan) for b in s.get("pruefung") or []]


# ---------------------------------------------------------------------------------------------------------------------
# Ohne Laufzeit


def test_wege_stift_in_bohrung_und_deckel():
    from build123d import Box, Cylinder, Pos

    from kevcad_kernel.pruefung.koerper import koerper_aus_form

    block = Box(40, 40, 20) - Cylinder(3.25, 50)
    formen = {"Block": block, "Stift": Pos(0, 0, 5) * Cylinder(3.0, 30), "Deckel": Pos(0, 0, 40) * Box(40, 40, 5)}
    wp = WegPruefer({n: koerper_aus_form(n, f) for n, f in formen.items()})
    assert set(wp.sperrer("Stift", (0, 0, 1))) == {"Deckel"}  # nach oben: Deckel im Weg
    assert not wp.sperrer("Stift", (0, 0, -1))  # nach unten durch die Bohrung frei (0,25 mm Spiel)
    assert set(wp.sperrer("Stift", (1, 0, 0))) == {"Block"}
    assert not wp.sperrer("Stift", (0, 0, 1), weg=3)  # endlicher Weg: Deckel erst nach 5 mm
    assert not wp.sperrer("Stift", (1, 0, 0), versatz=(0, 0, 60))  # zweistufig: erst hoch, dann zur Seite


def test_standsicherheit_kippt_und_steht():
    class T:
        def __init__(self, lo, hi, m):
            from build123d import Box, Pos

            from kevcad_kernel.pruefung.koerper import koerper_aus_form

            lo, hi = np.asarray(lo, float), np.asarray(hi, float)
            self.koerper = koerper_aus_form("t", Pos(*((lo + hi) / 2)) * Box(*(hi - lo)))
            self.bmin, self.bmax = lo, hi
            self.masse_g, self.masse_geschaetzt = m, False
            self.zentrum = (lo + hi) / 2

    fuss = T((0, 0, 0), (40, 40, 10), 100.0)
    arm = T((0, 0, 10), (400, 40, 20), 1000.0)
    assert standsicherheit([fuss], 0.0).sicher
    st = standsicherheit([fuss, arm], 0.0)
    assert st.steht and not st.sicher and st.abstand < 0


# ---------------------------------------------------------------------------------------------------------------------
# Mit Laufzeit


def test_geruest_gestell(env):
    rt = env["rt"]
    oeffne(env, "Gestell", GESTELL)
    res = rt.bauplan()
    assert res["ok"], res.get("error")
    plan = res["bauplan"]
    assert [a["art"] for a in plan["abschnitte"]] == ["material", "zuschnitt", "bearbeiten", "drucken", "montage"]
    assert Path(res["datei"]).is_file() and res["datei"].endswith("dokumente/bauplan.json")
    # Material: Halbzeug und Kleinteile mit Maß
    mat = [m["benennung"] for s in schritte(plan, "material") for m in s.get("material") or []]
    assert any("Vierkantrohr 40 × 40 × 3" in m for m in mat) and any("M8 × 70" in m for m in mat)
    # Zuschnitt: Stangen mit Gehrung
    zs = schritte(plan, "zuschnitt")
    stuecke = [z for s in zs for z in s["zuschnitt"]]
    assert {z["laenge"] for z in stuecke if z["stock_id"] == "vierkantrohr-en10219-40x40x3"} == {842.0, 800.0, 600.0}
    assert any(z["gehrung"] == [45.0, 45.0] for z in stuecke)
    assert any("Gehrung 45°/45°" in h for s in zs for h in s["hinweise"])
    # Bearbeiten: Rahmen vorn und hinten gleich (2× gleich), Bohrungen Ø9 ab Rohrende; Deckel ab den Kanten
    bb = schritte(plan, "bearbeiten")
    rahmen = next(s for s in bb if "Rahmen" in s["titel"])
    assert rahmen["anzahl"] == 2 and "Bohrer Ø 9" in rahmen["werkzeug"]
    lagen = sorted(e["lage_mm"][0] for e in rahmen["bohrbild"] if e["teil"] == rahmen["teile"][0])
    assert lagen == pytest.approx([200.0, 600.0], abs=0.5)
    assert all(e["durchmesser"] == pytest.approx(9.0) and e["tiefe"] is None for e in rahmen["bohrbild"])
    deckel = next(s for s in bb if s["teile"] == ["Deckel"])
    assert len(deckel["bohrbild"]) == 4 and "linker Kante" in deckel["bohrbild"][0]["von"]
    assert sorted(tuple(e["lage_mm"]) for e in deckel["bohrbild"])[0] == pytest.approx((200.0, 20.0), abs=0.5)
    # Montage: Unterbaugruppe Gestell zuerst, dann Deckel mit Schraube, Scheibe, Mutter in dieser Reihenfolge
    mo = schritte(plan, "montage")
    assert mo[0]["baugruppe"] == "Gestell" and any(s["baugruppe"] is None for s in mo)
    haupt = [s for s in mo if s["baugruppe"] is None]
    assert haupt[0]["einbau"][0]["art"] == "gruppe" and haupt[0]["einbau"][0]["grundteil"]
    d = next(s for s in haupt if "Deckel" in s["neu"])
    arten = [e["name"].split("/")[-1].split(" ")[0] for e in d["einbau"]]
    assert arten[0] == "Deckel" and arten.index("M8x70") < arten.index("Scheibe") < arten.index("Mutter")
    assert {"Innensechskant 6 mm", "Maulschlüssel SW 13"} <= set(d["werkzeug"])
    assert {v["anzahl"] for v in d["verbindungsmittel"]} == {4}
    assert d["geschaetzt"] is True  # Modell ohne verbinde
    # Bild: Kamera, Explosion entlang der Einführrichtung, Pfeile, Sichtbarkeit
    bild = d["bild"]
    assert len(bild["kamera"]["rotation"]) == 4 and bild["kamera"]["ortho"] is True
    assert bild["explosion"]["Deckel"][2] > 0 and bild["pfeile"] and bild["sichtbarkeit"]["Deckel"] >= 0.5
    assert not [b for b in befunde(plan) if b["schwere"] == "fehler"]
    # Reihenfolgen „a vor b“ aus der Folge (Wege in der Vormontage)
    assert any(r["quelle"] == "auto" for r in plan["vorher"])


def test_kaefig_einfuehrweg_blockiert(env):
    rt = env["rt"]
    oeffne(env, "Kaefig", KAEFIG)
    plan = rt.bauplan()["bauplan"]
    mo = schritte(plan, "montage")
    kugel = next(s for s in mo if "Kugel" in s["neu"])
    arten = {b["art"] for b in kugel["pruefung"] if b["schwere"] == "fehler"}
    assert "einfuehrweg" in arten, kugel["pruefung"]
    b = next(b for b in kugel["pruefung"] if b["art"] == "einfuehrweg")
    assert "Kasten" in b["text"] and b["loesung"]
    # Drucken: beide Druckteile mit Material und Ausrichtung
    dr = schritte(plan, "drucken")
    assert {s["druck"]["material"] for s in dr} == {"petg"} and all(s["druck"]["seite"] for s in dr)


def test_stapel_reihenfolge_nach_verschieben(env):
    rt = env["rt"]
    oeffne(env, "Stapel", STAPEL)
    plan = rt.bauplan()["bauplan"]
    mo = schritte(plan, "montage")
    namen = [s["neu"][0] for s in mo]
    assert namen.index("Stift") < namen.index("Deckel")
    assert not [b for b in befunde(plan) if b["schwere"] == "fehler"]
    stift = next(s for s in mo if s["neu"] == ["Stift"])
    deckel = next(s for s in mo if s["neu"] == ["Deckel"])
    assert any(r["a"] == stift["id"] and r["b"] == deckel["id"] and "versperrt" in r["grund"] for r in plan["vorher"])
    vorher = mo[namen.index("Stift") - 1]["id"]
    res = rt.bauplan_bearbeiten([{"op": "verschieben", "schritt": deckel["id"], "nach": vorher}], "kevin")
    assert res["ok"], res.get("error")
    stift_bef = [b for b in res["befunde"] if b["schritt"] == stift["id"]]
    assert any(b["art"] == "reihenfolge" and b["schwere"] == "fehler" for b in stift_bef), stift_bef
    assert any("Deckel" in b["text"] for b in stift_bef)
    gespeichert = datei.laden(env["tmp"] / "Stapel")
    assert schritte(gespeichert, "montage")[namen.index("Stift")]["id"] == deckel["id"]


def test_werkzeugzugang_mutter_in_enger_tasche(env):
    rt = env["rt"]
    oeffne(env, "Tasche", TASCHE)
    plan = rt.bauplan()["bauplan"]
    zugang = [b for b in befunde(plan) if b["art"] == "werkzeugzugang"]
    assert any(b["teile"][0] == "Mutter" and "Platte" in b["teile"] for b in zugang), befunde(plan)
    assert all(b["teile"][0] != "Schraube" for b in zugang)  # Innensechskant von unten kommt hin


def test_feste_schritte_und_texte_bleiben(env):
    rt, app = env["rt"], env["app"]
    oeffne(env, "Erhalten", STAPEL)
    plan = rt.bauplan()["bauplan"]
    mo = schritte(plan, "montage")
    stift = next(s for s in mo if s["neu"] == ["Stift"])
    deckel = next(s for s in mo if s["neu"] == ["Deckel"])
    res = rt.bauplan_bearbeiten([
        {"op": "text", "schritt": stift["id"], "titel": "Stift einsetzen",
         "text": "Stift von oben in die Hülse schieben, bis er auf der Platte aufsitzt.",
         "hinweise": ["Hülse innen entgraten"]},
        {"op": "fest", "schritt": deckel["id"], "wert": True},
        {"op": "vorher", "a": "Hülse", "b": "Stift", "grund": "Kevin: Hülse zuerst ausrichten"}], "agent")
    assert res["ok"], res.get("error")
    # neuer Lauf mit anderer Höhe: Bauplan erneuert sich im Hintergrund (Datei existiert), Texte und Feste bleiben
    start = app.mark()
    run = rt.run(params={"h": 60})
    assert run["ok"]
    app.wait_for(lambda h: h["type"] == "DOCS" and (h.get("bauplan") or {}).get("run") == run["run"], timeout=120,
                 start=start)
    plan2 = rt.bauplan()["bauplan"]
    assert plan2["stand"]["run"] == run["run"]
    s2 = next(s for _, s in datei.alle_schritte(plan2) if s["id"] == stift["id"])
    assert s2["titel"] == "Stift einsetzen" and s2["quelle"] == "agent" and s2["hinweise"] == ["Hülse innen entgraten"]
    d2 = next(s for _, s in datei.alle_schritte(plan2) if s["id"] == deckel["id"])
    assert d2["fest"] is True
    assert any(r["quelle"] == "agent" and r["a"] == "Hülse" for r in plan2["vorher"])
    # die Simulation lief für den neuen Stand (Hülse 60 mm: Deckel höher)
    assert d2["einbau"][0]["teile"] == ["Deckel"]


def test_protokoll_rundlauf(env):
    rt, app = env["rt"], env["app"]
    oeffne(env, "Protokoll", STAPEL)
    start = app.mark()
    app.send({"type": "BAUPLAN_REQ", "id": "bp-1"})
    _, _, h, p = app.wait_for(lambda h: h["type"] == "BAUPLAN" and h.get("reply_to") == "bp-1", timeout=120,
                              start=start)
    bilder = unpack_bauplan(h, p)
    assert h["linien_reihenfolge"][-2:] == ["neu", "pfeil"] and h["feld"] == [180.0, 120.0]
    ids = [s["id"] for _, s in datei.alle_schritte(h["bauplan"]) if s.get("bild")]
    assert [b["schritt"] for b in bilder] == ids
    mont = [b for b in bilder if b["schritt"].startswith("m-")]
    assert any(b["linien"]["neu"] for b in mont) and any(b["linien"]["pfeil"] for b in mont)
    for b in bilder:
        for ls in b["linien"].values():
            for pl in ls:
                assert pl.min() >= -1e-3 and pl[:, 0].max() <= 180.001 and pl[:, 1].max() <= 120.001
    stift = next(s for _, s in datei.alle_schritte(h["bauplan"]) if s.get("neu") == ["Stift"])
    start = app.mark()
    app.send({"type": "BAUPLAN_EDIT", "id": "bp-2", "von": "kevin",
              "ops": [{"op": "text", "schritt": stift["id"], "text": "Stift einschieben."}]})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "bp-2", timeout=60, start=start)
    assert ack["ok"], ack
    _, _, h2, _ = app.wait_for(lambda h: h["type"] == "BAUPLAN", timeout=60, start=start)
    s2 = next(s for _, s in datei.alle_schritte(h2["bauplan"]) if s["id"] == stift["id"])
    assert s2["text"] == "Stift einschieben." and s2["quelle"] == "kevin"
    start = app.mark()
    app.send({"type": "BAUPLAN_PRUEFEN", "id": "bp-3", "schritt": None})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "bp-3", timeout=60, start=start)
    assert ack["ok"]
    # DOCS beim Verbinden einer zweiten App
    zweite = FakeApp(str(env["tmp"] / "k.sock"))
    try:
        _, _, docs, _ = zweite.wait_for(lambda h: h["type"] == "DOCS")
        assert docs["bauplan"]["schritte"] > 0 and docs["blaetter"] == []
    finally:
        zweite.close()


def test_bearbeiten_fehler_und_umfang(env):
    rt = env["rt"]
    oeffne(env, "Umfang", STAPEL)
    assert rt.bauplan()["ok"]
    res = rt.bauplan_bearbeiten([{"op": "text", "schritt": "gibt-es-nicht", "text": "x"}])
    assert not res["ok"] and "nicht gefunden" in res["error"]
    res = rt.bauplan_bearbeiten([{"op": "umfang", "ohne": ["Deckel"]}])
    assert res["ok"], res.get("error")
    plan = rt.bauplan()["bauplan"]
    assert "Deckel" not in [t for s in schritte(plan, "montage") for t in s["neu"]]
    assert plan["stand"]["nicht_im_aufbau"]["Deckel"] == "im Bauplan ausgenommen"


# ---------------------------------------------------------------------------------------------------------------------
# MCP und Testdateien


class BauplanFake(FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.plan = bauplan_beispiel()

    def bauplan(self, neu: bool = False):
        self._record("bauplan", neu)
        return {"ok": True, "datei": "/tmp/Halter/dokumente/bauplan.json", "bauplan": self.plan,
                "zusammenfassung": datei.zusammenfassung(self.plan), "zeiten": {"gesamt_ms": 812.5}}

    def bauplan_bearbeiten(self, ops, von="agent"):
        self._record("bauplan_bearbeiten", ops, von)
        meldungen, _ = datei.bearbeiten(self.plan, ops, von)
        return {"ok": True, "meldungen": meldungen, "zusammenfassung": datei.zusammenfassung(self.plan),
                "befunde": [b for _, s in datei.alle_schritte(self.plan) for b in s.get("pruefung") or []]}

    def bauplan_pruefen(self, schritt=None):
        self._record("bauplan_pruefen", schritt)
        return {"ok": True, "befunde": [b for _, s in datei.alle_schritte(self.plan) for b in s.get("pruefung") or []],
                "zusammenfassung": datei.zusammenfassung(self.plan), "ms": 12.0, "schritt": schritt}


def test_mcp_werkzeuge():
    server, fake = start_server(BauplanFake())
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        tools = {t.name: t for t in anyio.run(with_client, server.url, lambda c: c.list_tools()).tools}
        assert {"bauplan", "bauplan_bearbeiten", "bauplan_pruefen"} <= set(tools)
        assert "workshop" in tools["bauplan"].description and "never invent" in tools["bauplan_bearbeiten"].description
        res = call("bauplan")
        text = texts(res)[0]
        assert res.is_error is True  # Beispiel hat einen Fehler (Werkzeugzugang)
        assert "## Montage" in text and "m-2: Deckel einbauen [fest] [agent]" in text and "Werkzeug kommt" in text
        data = json.loads(texts(res)[1])
        assert data["bauplan"]["abschnitte"][4]["schritte"][1]["id"] == "m-2"
        res = call("bauplan_bearbeiten", {"ops": [{"op": "text", "schritt": "m-1g", "text": "Bein hinstellen."}]})
        assert "Text von m-1g gesetzt" in texts(res)[0]
        assert fake.calls_of("bauplan_bearbeiten")[0][0][1] == "agent"
        res = call("bauplan_bearbeiten", {"ops": [{"op": "falsch", "schritt": "m-1g"}]})
        assert res.is_error is True
        res = call("bauplan_pruefen", {"schritt": "m-2", "schwere": "probleme"})
        assert "Simulation von m-2" in texts(res)[0] and "werkzeugzugang" in texts(res)[0]
    finally:
        server.stop_thread()


def test_testdateien_der_app():
    erwartet = json.loads((FIXTURES / "fixtures.json").read_text())["bauplan"]
    rahmen = FrameReader().feed((FIXTURES / "bauplan.frame").read_bytes())
    assert len(rahmen) == 1
    h, p = rahmen[0]
    assert h["type"] == "BAUPLAN" and h["reply_to"] == erwartet["reply_to"] and len(p) == erwartet["payload_bytes"]
    bilder = unpack_bauplan(h, p)
    assert [{"schritt": b["schritt"], "anzahl": b["anzahl"]} for b in bilder] == erwartet["bilder"]
    assert [[round(float(x), 3) for x in q] for q in bilder[1]["linien"]["pfeil"][0]] == erwartet["erster_pfeil"]
    for name in erwartet["frames"]:
        (kopf, _), = FrameReader().feed((FIXTURES / name).read_bytes())
        assert kopf["type"] in ("BAUPLAN", "DOCS", "BAUPLAN_REQ", "BAUPLAN_EDIT", "BAUPLAN_PRUEFEN")
