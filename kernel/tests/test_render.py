"""Phase 7: Renderings (PLAN-PHASE7-RENDERINGS.md): Materialien, Szenen und Größen, Blender-Szene und -Lauf (mit einem
Ersatz-Blender), Rundlauf schnell und Foto mit einer Test-App am Socket, MCP ``render`` und die Testdateien der App."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import wait_for

from kevcad_kernel.catalog import Catalog, builtin_dir, validate_material
from kevcad_kernel.protocol import FrameReader, PART_ARRAYS, check_render_message, render_beispiele
from kevcad_kernel.render import blender as bl
from kevcad_kernel.render import szenen as sz
from kevcad_kernel.render.materialien import OBERFLAECHEN, hex_rgb, material_pbr, part_pbr, schluessel, validate_render

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[1] / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"


# -- Materialien ---------------------------------------------------------------------------------------------------------

def test_alle_mitgelieferten_materialien_haben_render():
    daten = json.loads((builtin_dir() / "materialien.json").read_text(encoding="utf-8"))
    for m in daten["materialien"]:
        assert isinstance(m.get("render"), dict), m["id"]
        assert validate_material(m) == [], m["id"]
        assert m["render"]["oberflaeche"] in OBERFLAECHEN
    ids = {m["id"]: m["render"]["oberflaeche"] for m in daten["materialien"]}
    # Kevins Liste: Alu eloxiert/gebürstet, Stahl verzinkt, Edelstahl, PETG/PLA mit Schichten, Gummi, Holz
    assert ids["alu-6060"] == "eloxiert" and ids["alu-5754"] == "gebuerstet"
    assert ids["stahl-verzinkt"] == "verzinkt" and ids["edelstahl-1.4301"] == "gebuerstet"
    assert ids["pla"] == ids["petg"] == "schichten" and ids["epdm"] == "gummi" and ids["buche"] == "holz"


def test_render_pruefen():
    assert validate_render({"basisfarbe": "#C8CCD0", "metallisch": 1, "rauheit": 0.3, "oberflaeche": "gebuerstet"}) == []
    fehler = validate_render({"basisfarbe": "grau", "rauheit": 1.4, "oberflaeche": "chrom", "schichthoehe": 3})
    assert len(fehler) == 4 and any("basisfarbe" in f for f in fehler) and any("chrom" in f for f in fehler)
    assert validate_render("matt") == ["Material: render muss ein Objekt sein"]
    m = {"id": "x", "name": "X", "gruppe": "Stahl", "dichte": 7.85, "farbe": "#808080", "render": {"rauheit": 2}}
    assert any("render.rauheit" in f for f in validate_material(m))


def test_pbr_aus_katalog_ableitung_und_teilfarbe():
    kat = Catalog(builtin=builtin_dir(), own=Path(tempfile.mkdtemp()))
    alu = kat.find_material("alu-6060")
    pbr = material_pbr(alu)
    assert pbr["quelle"] == "katalog" and pbr["oberflaeche"] == "eloxiert" and pbr["metallisch"] == 1.0
    assert pbr["basisfarbe"] == hex_rgb("#D3D6D9") and pbr["klarlack"] == 0.35
    # Teilfarbe = Katalogfarbe: Katalog-Basisfarbe bleibt
    farbe = hex_rgb(alu["farbe"]) + [1.0]
    assert part_pbr({"color": farbe}, alu)["basisfarbe"] == hex_rgb("#D3D6D9")
    # eigene Farbe aus model.py hat Vorrang (schwarz eloxiert), Glanz bleibt
    schwarz = part_pbr({"color": [0.1, 0.1, 0.12, 1.0]}, alu)
    assert schwarz["basisfarbe"] == [0.1, 0.1, 0.12] and schwarz["quelle"] == "teilfarbe"
    assert schwarz["metallisch"] == 1.0 and schwarz["material"] == "alu-6060"
    # ohne render: aus Gruppe, farbe, metallisch, rauheit abgeleitet; druckbar → Schichten
    eigen = {"id": "e", "gruppe": "Kunststoff", "farbe": "#336699", "druckbar": True, "rauheit": 0.4}
    p = material_pbr(eigen)
    assert p["quelle"] == "abgeleitet" and p["oberflaeche"] == "schichten" and p["rauheit"] == 0.4
    assert p["schichthoehe"] == 0.2
    # ohne Material: Teilfarbe, matt; Druckteil bekommt Schichten; halbdurchsichtige Farbe
    ohne = part_pbr({"color": [0.2, 0.4, 0.6, 0.5], "druckteil": {"material": "pla"}}, None)
    assert ohne["basisfarbe"] == [0.2, 0.4, 0.6] and ohne["oberflaeche"] == "schichten" and ohne["durchsichtig"] == 0.5
    assert schluessel(pbr) == schluessel(dict(pbr)) and schluessel(pbr) != schluessel(schwarz)


# -- Szenen, Größen, Pfade ------------------------------------------------------------------------------------------------

def test_groessen_und_szenen(tmp_path):
    assert sz.groesse(None) == (1920, 1080) and sz.groesse("4K") == (3840, 2160)
    assert sz.groesse("2400x1600") == (2400, 1600) and sz.groesse([800, 600]) == (800, 600)
    assert sz.groesse({"breite": 1000, "hoehe": 500}) == (1000, 500)
    for falsch in ("riesig", "9000x10", [1, 2]):
        with pytest.raises(sz.RenderFehler):
            sz.groesse(falsch)
    s = sz.szene(None)
    assert s["name"] == "studio" and s["hintergrund"] == "#F1F2F4" and not s["transparent"] and s["umgebung"] is None
    d = sz.szene("Draußen")
    assert d["name"] == "draussen" and Path(d["umgebung"]).is_file() and d["hintergrund"] == "umgebung"
    for name in ("werkstatt", "wohnraum"):
        assert Path(sz.szene(name)["umgebung"]).is_file()
    f = sz.szene("freigestellt")
    assert f["transparent"] and f["hintergrund"] == "transparent"
    assert sz.szene("studio", hintergrund="grau")["hintergrund"] == "#D9DBDE"
    assert sz.szene("studio", hintergrund="#abcdef")["hintergrund"] == "#ABCDEF"
    assert sz.szene("draussen", hintergrund="transparent")["transparent"]
    with pytest.raises(sz.RenderFehler, match="keine Umgebung"):
        sz.szene("studio", hintergrund="umgebung")
    with pytest.raises(sz.RenderFehler, match="unbekannt"):
        sz.szene("mond")
    # eigene Umgebung im Datenordner
    (tmp_path / "umgebungen").mkdir()
    eigen = tmp_path / "umgebungen" / "Halle2.hdr"
    eigen.write_bytes(b"#?RADIANCE\n")
    e = sz.szene("halle2", datenordner=tmp_path)
    assert e["umgebung"] == str(eigen) and e["licht"] == "umgebung"
    assert sz.szene("studio", umgebung=str(eigen))["hintergrund"] == "umgebung"
    with pytest.raises(sz.RenderFehler, match=".hdr"):
        sz.szene("studio", umgebung=str(tmp_path / "x.exr"))
    assert sz.ansicht(None) == "aktuell" and sz.ansicht("Produkt") == "produkt" and sz.ansicht("oben") == "top"
    assert sz.qualitaet("Fotorealistisch") == "foto" and sz.qualitaet(None) == "schnell"


def test_zielpfade(tmp_path):
    s = sz.szene("studio")
    p = sz.zielpfad(tmp_path, "Halter / Test", s, "schnell")
    assert p.parent == tmp_path / "renders" and p.name.startswith("Halter-Test_studio_schnell_") and p.suffix == ".png"
    assert sz.zielpfad(tmp_path, "H", s, "foto", kamera="Kamera/FX6").name.startswith("H_studio_FX6_foto_")
    assert sz.zielpfad(tmp_path, "H", s, "foto", ziel="titel") == tmp_path / "renders" / "titel.png"
    assert sz.zielpfad(tmp_path, "H", s, "foto", ziel="/tmp/x.png") == Path("/tmp/x.png")
    assert sz.zielpfad(tmp_path, "H", s, "schnell", vorschau=True) == tmp_path / "renders" / ".vorschau" / \
        "vorschau-schnell.png"


# -- Blender-Szene und -Lauf ------------------------------------------------------------------------------------------------

def teil(name: str, z0: float = 0.0, color=(0.8, 0.2, 0.1, 1.0), material: str | None = "petg") -> tuple[dict, bytes]:
    """Kleines Teil (ein Rechteck aus zwei Dreiecken) als PART_UPSERT-Kopf und Nutzlast."""
    pos = np.array([[0, 0, z0], [100, 0, z0], [100, 50, z0], [0, 50, z0]], dtype="<f4")
    nor = np.array([[0, 0, 1]] * 4, dtype="<f4")
    tri = np.array([[0, 1, 2], [0, 2, 3]], dtype="<u4")
    counts = {"vert": 4, "tri": 2, "face": 1, "edge": 0, "epts": 0, "vtx": 0}
    arrays = {"positions": pos, "normals": nor, "triangles": tri, "tri_face": np.zeros(2, "<i4"),
              "edge_points": np.zeros((0, 3), "<f4"), "edge_offsets": np.zeros(1, "<u4"),
              "vertices": np.zeros((0, 3), "<f4")}
    payload = b"".join(arrays[n].tobytes() for n, _, _, _ in PART_ARRAYS)
    header = {"type": "PART_UPSERT", "run": 1, "name": name, "color": list(color), "material": material,
              "bbox": {"min": [0, 0, z0], "max": [100, 50, z0]}, "props": {"volume": 1.0}, "counts": counts,
              "faces": [{"t": "plane", "a": 5000.0}], "edges": [], "transform": None}
    return header, payload


def test_szene_schreiben(tmp_path):
    h1, p1 = teil("A")
    h2, p2 = teil("B", z0=10)
    pbr = part_pbr(h1, None)
    verschoben = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 40.0, 1]  # spaltenweise: z + 40
    pfad, info = bl.szene_schreiben(
        tmp_path, teile=[{"name": "A", "header": h1, "payload": p1, "matrix": None, "pbr": pbr},
                         {"name": "B", "header": h2, "payload": p2, "matrix": verschoben, "pbr": pbr}],
        kamera={"projection": "perspective", "position": [300, -300, 200], "target": [50, 25, 0], "up": [0, 0, 1],
                "fov_deg": 30, "ortho_height_mm": None},
        szene=sz.szene("studio"), breite=640, hoehe=400, samples=16, ausgabe=tmp_path / "out.png")
    d = json.loads(pfad.read_text())
    assert info == {"teile": 2, "dreiecke": 4, "materialien": 1}
    assert d["grenzen"] == {"min": [0.0, 0.0, 0.0], "max": [100.0, 50.0, 50.0]}  # B mit Verschiebung
    assert [t["netz"] for t in d["teile"]] == [0, 1] and len(d["materialien"]) == 1
    netze = np.load(d["netze"])
    assert netze["p1"].shape == (4, 3) and netze["t0"].shape == (2, 3)
    with pytest.raises(ValueError, match="Keine sichtbaren"):
        bl.szene_schreiben(tmp_path / "leer", teile=[], kamera={}, szene={}, breite=1, hoehe=1, samples=1,
                           ausgabe=tmp_path / "x.png")


def ersatz_blender(tmp_path: Path, *, schlafen: float = 0.0, fehler: bool = False) -> Path:
    """Shell-Skript, das sich wie Blender verhält: Probenzeilen und KEVCAD-Meldungen, schreibt das PNG aus der JSON."""
    skript = tmp_path / "blender"
    ausgabe = ('python3 -c "import json,sys; d=json.load(open(sys.argv[1])); open(d[\'ausgabe\'],\'wb\').write('
               'b\'\\x89PNG\\r\\n\\x1a\\n\')" "$J"')
    skript.write_text(
        "#!/bin/bash\n"
        'J="${@: -1}"\n'
        'echo "KEVCAD teile 2 dreiecke 4 materialien 1 in 0.0 s"\n'
        'echo "KEVCAD rendert 640x400 samples 16 auf GPU Test"\n'
        "for i in 4 8 12 16; do echo \"Fra:1 Mem:1M | Sample $i/16\"; sleep %s; done\n" % schlafen
        + ("echo 'Error: kaputt'; exit 3\n" if fehler else f"{ausgabe}\necho \"KEVCAD fertig x rendern 0.1 s\"\n"))
    skript.chmod(skript.stat().st_mode | stat.S_IEXEC)
    return skript


def test_blender_lauf_mit_ersatz(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"ausgabe": str(tmp_path / "o.png")}))
    meldungen: list[tuple[float, str]] = []
    lauf = bl.BlenderLauf(tmp_path / "s.json", zeitlimit=30, fortschritt=lambda a, t: meldungen.append((a, t)),
                          blender=ersatz_blender(tmp_path), prioritaet=0)
    lauf._letzte = -1e9
    res = lauf.laufen()
    assert res["ok"], res
    assert res["samples"] == 16 and res["geraet"] == "GPU Test" and (tmp_path / "o.png").is_file()
    assert meldungen[0] == (0.02, "Blender startet") and any(t == "Cycles rendert" for _, t in meldungen)
    # Fehler wird gemeldet
    lauf = bl.BlenderLauf(tmp_path / "s.json", zeitlimit=30, blender=ersatz_blender(tmp_path, fehler=True))
    res = lauf.laufen()
    assert not res["ok"] and "kaputt" in res["fehler"]
    # Zeitlimit bricht ab
    lauf = bl.BlenderLauf(tmp_path / "s.json", zeitlimit=0.5, blender=ersatz_blender(tmp_path, schlafen=1.0))
    res = lauf.laufen()
    assert not res["ok"] and "Zeitlimit" in res["fehler"]
    assert bl.samples_fuer(1920, 1080) == 160 and bl.samples_fuer(3840, 2160) == 128 and bl.samples_fuer(1, 1, 999) == 999


# -- Rundlauf mit einer Test-App -----------------------------------------------------------------------------------------

class RenderApp(FakeApp):
    """Test-App: beantwortet RENDER_REQ (schreibt ein PNG) und RENDER_SCENE_REQ (Kamera, Lagen)."""

    def __init__(self, path: str, fehler: str | None = None) -> None:
        self.fehler = fehler
        self.anfragen: list[dict] = []
        super().__init__(path)
        threading.Thread(target=self._antworten, daemon=True).start()

    def _antworten(self) -> None:
        seen = 0
        while not self.closed:
            try:
                i, _, h, _ = self.wait_for(lambda h: h["type"] in ("RENDER_REQ", "RENDER_SCENE_REQ"), start=seen,
                                           timeout=0.5)
            except AssertionError:
                continue
            seen = i + 1
            self.anfragen.append(h)
            kamera = {"projection": "perspective", "position": [300.0, -300.0, 200.0], "target": [50.0, 25.0, 0.0],
                      "up": [0.0, 0.0, 1.0], "fov_deg": 26.0, "ortho_height_mm": None, "name": h.get("kamera")}
            if h["type"] == "RENDER_REQ":
                if self.fehler:
                    self.send({"type": "RENDER_RES", "reply_to": h["id"], "ok": False, "path": None, "width": 0,
                               "height": 0, "ms": 0, "kamera": None, "message": self.fehler})
                    continue
                Path(h["path"]).parent.mkdir(parents=True, exist_ok=True)
                Path(h["path"]).write_bytes(b"\x89PNG\r\n\x1a\n")
                self.send({"type": "RENDER_RES", "reply_to": h["id"], "ok": True, "path": h["path"],
                           "width": h["width"], "height": h["height"], "ms": 640, "kamera": kamera, "message": None,
                           "phasen": {"rendern_ms": 300}})
            else:
                self.send({"type": "RENDER_SCENE", "reply_to": h["id"], "ok": True, "kamera": kamera,
                           "teile": [{"name": "Platte", "matrix": None}], "message": None})


@pytest.fixture
def laufzeit():
    tmp = Path(tempfile.mkdtemp(prefix="kcr", dir="/tmp"))  # Socket-Pfade sind auf 103 Zeichen begrenzt
    rt = make_runtime(str(tmp / "k.sock"), start_worker=False)
    try:
        yield rt, tmp.resolve()
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)


def verbunden(rt, app) -> None:
    app.wait_for(lambda h: h["type"] == "AGENT")
    assert wait_for(lambda: rt.status()["app_connected"], timeout=10)


def mit_teil(rt) -> None:
    h, p = teil("Platte")
    rt.scene.upsert(name="Platte", run=1, key="k1", header=h, payload=p, brep=b"", density=None)


def test_render_ohne_projekt_app_teile(laufzeit):
    rt, tmp = laufzeit
    assert "Kein Projekt" in rt.render()["error"]
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    assert rt.render()["error"] == "App nicht verbunden"


def test_render_schnell_rundlauf(laufzeit):
    rt, tmp = laufzeit
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = RenderApp(str(tmp / "k.sock"))
    try:
        verbunden(rt, app)
        assert rt.render()["error"] == "Keine Teile: erst run aufrufen"
        mit_teil(rt)
        assert "unbekannt" in rt.render(szene="mond")["error"]
        start = app.mark()
        res = rt.render(szene="studio", groesse="quadrat")
        assert res["ok"] and res["zustand"] == "fertig", res
        assert res["auftrag"] == "R-1" and res["width"] == res["height"] == 2048
        assert Path(res["pfad"]).is_file() and Path(res["pfad"]).parent == tmp / "Halter" / "output" / "renders"
        req = app.anfragen[-1]
        assert check_render_message(req) == [] and req["szene"]["name"] == "studio" and req["ansicht"] == "aktuell"
        assert [t["name"] for t in req["teile"]] == ["Platte"] and req["teile"][0]["oberflaeche"] == "schichten"
        app.wait_for(lambda h: h["type"] == "RENDER_STATUS" and h["zustand"] == "fertig", start=start)
        status = [h for h in app.since(start) if h["type"] == "RENDER_STATUS"]
        assert [s["zustand"] for s in status] == ["laeuft", "fertig"] and all(not check_render_message(s)
                                                                                for s in status)
        assert status[-1]["pfad"] == res["pfad"]
        # Abfrage mit Bild
        q = rt.render(auftrag="R-1", bild=True)
        assert q["zustand"] == "fertig" and q["png"].startswith(b"\x89PNG")
        assert "unbekannt" in rt.render(auftrag="R-99")["error"]
    finally:
        app.close()


def test_render_schichtlinien_nach_druckrichtung(laufzeit):
    """Druckteile bekommen die Aufbaurichtung aus der Druckprüfung des letzten Laufs (CHECK.druck, ``oben_welt``) als
    ``druck_oben``; Blender legt dafür ein eigenes Material an (Schichtlinien quer dazu statt quer zu Z)."""
    rt, tmp = laufzeit
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = RenderApp(str(tmp / "k.sock"))
    try:
        verbunden(rt, app)
        mit_teil(rt)
        rt._pruef.fertig({"type": "CHECK", "run": 1, "state": "done", "befunde": [],
                          "druck": {"teile": {"Platte": {"ausrichtung": {"text": "liegt auf -x",
                                                                        "oben_welt": [1.0, 0.0, 0.0]}}}}}, b"")
        res = rt.render(szene="studio", groesse="vorschau")
        assert res["ok"], res
        t = app.anfragen[-1]["teile"][0]
        assert t["oberflaeche"] == "schichten" and t["druck_oben"] == [1.0, 0.0, 0.0]
        assert check_render_message(app.anfragen[-1]) == []
        ohne = {k: v for k, v in t.items() if k != "druck_oben"}
        assert schluessel(t) != schluessel(ohne)
    finally:
        app.close()


def test_render_fehler_der_app(laufzeit):
    rt, tmp = laufzeit
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = RenderApp(str(tmp / "k.sock"), fehler="Metal fehlt")
    try:
        verbunden(rt, app)
        mit_teil(rt)
        res = rt.render()
        assert not res["ok"] and res["zustand"] == "fehler" and res["error"] == "Metal fehlt"
    finally:
        app.close()


def test_render_start_aus_der_app(laufzeit):
    rt, tmp = laufzeit
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = RenderApp(str(tmp / "k.sock"))
    try:
        verbunden(rt, app)
        mit_teil(rt)
        start = app.mark()
        app.send({"type": "RENDER_START", "id": "a-1", "szene": "freigestellt", "ansicht": "produkt", "kamera": None,
                  "breite": 960, "hoehe": 540, "qualitaet": "schnell", "hintergrund": None, "ziel": None,
                  "vorschau": True})
        _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-1", start=start)
        assert ack["ok"] and ack["message"].startswith("R-")
        _, _, fertig, _ = app.wait_for(lambda h: h["type"] == "RENDER_STATUS" and h["zustand"] == "fertig",
                                       start=start)
        assert fertig["von"] == "app" and fertig["vorschau"] and fertig["pfad"].endswith("vorschau-schnell.png")
        assert app.anfragen[-1]["szene"]["transparent"] and app.anfragen[-1]["ansicht"] == "produkt"
        # ungültige Anfrage: ACK mit Fehler
        app.send({"type": "RENDER_START", "id": "a-2", "szene": "studio", "qualitaet": "kino"})
        _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "a-2", start=start)
        assert not ack["ok"] and "kino" in ack["message"]
    finally:
        app.close()


def _frisch_mit_szene(p: Path) -> bool:
    """Arbeitsordner der letzten 5 s mit szene.json; ein Ordner, der zwischen glob und stat aufgeräumt wird, zählt nicht."""
    try:
        return p.stat().st_mtime > time.time() - 5 and (p / "szene.json").exists()
    except FileNotFoundError:
        return False


def test_render_foto_mit_ersatz_blender(laufzeit, monkeypatch):
    rt, tmp = laufzeit
    monkeypatch.setenv("KEVCAD_BLENDER", str(ersatz_blender(tmp, schlafen=0.25)))
    monkeypatch.setattr(bl, "freier_speicher_prozent", lambda: 50)
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = RenderApp(str(tmp / "k.sock"))
    try:
        verbunden(rt, app)
        mit_teil(rt)
        start = app.mark()
        res = rt.render(szene="draussen", qualitaet="foto", groesse="640x400")
        assert res["ok"] and res["zustand"] in ("wartet", "laeuft") and res["qualitaet"] == "foto"
        fertig = rt.render(auftrag=res["auftrag"], warten_s=30)
        assert fertig["zustand"] == "fertig", fertig
        assert Path(fertig["pfad"]).is_file() and fertig["samples"] == 16 and fertig["teile"] == 1
        req = [a for a in app.anfragen if a["type"] == "RENDER_SCENE_REQ"][-1]
        assert check_render_message(req) == [] and req["width"] == 640
        # die Meldung „fertig“ an die App kann unter Last kurz nach der Antwort des Auftrags ankommen
        app.wait_for(lambda h: h["type"] == "RENDER_STATUS" and h["zustand"] == "fertig", start=start, timeout=10)
        status = [h for h in app.since(start) if h["type"] == "RENDER_STATUS"]
        assert status[-1]["zustand"] == "fertig" and any(s["text"].startswith("Probe") for s in status)
        # Arbeitsordner aufgeräumt
        assert not [p for p in Path(tempfile.gettempdir()).glob("kevcad-render-*") if _frisch_mit_szene(p)]
    finally:
        app.close()


def test_render_foto_abbrechen(laufzeit, monkeypatch):
    rt, tmp = laufzeit
    monkeypatch.setenv("KEVCAD_BLENDER", str(ersatz_blender(tmp, schlafen=2.0)))
    monkeypatch.setattr(bl, "freier_speicher_prozent", lambda: 50)
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = RenderApp(str(tmp / "k.sock"))
    try:
        verbunden(rt, app)
        mit_teil(rt)
        res = rt.render(qualitaet="foto", groesse="vorschau")
        assert wait_for(lambda: rt.render(auftrag=res["auftrag"])["zustand"] == "laeuft", timeout=10)
        time.sleep(0.3)
        out = rt.render(auftrag=res["auftrag"], abbrechen=True, warten_s=15)
        assert out["zustand"] == "abgebrochen" and not out["ok"]
    finally:
        app.close()


def test_render_foto_ohne_blender(laufzeit, monkeypatch):
    rt, tmp = laufzeit
    monkeypatch.setattr(bl, "blender_pfad", lambda: None)
    assert rt.project_new(str(tmp / "Halter"), "empty")["ok"]
    app = RenderApp(str(tmp / "k.sock"))
    try:
        verbunden(rt, app)
        mit_teil(rt)
        assert "Blender fehlt" in rt.render(qualitaet="foto")["error"]
    finally:
        app.close()


# -- Testdateien der App ---------------------------------------------------------------------------------------------------

def test_testdateien_aktuell():
    erwartet = json.loads((FIXTURES / "render.json").read_text(encoding="utf-8"))
    namen = [n for n, _ in render_beispiele()]
    assert sorted(erwartet) == sorted(namen)
    for name, head in render_beispiele():
        reader = FrameReader()
        frames = list(reader.feed((FIXTURES / f"{name}.frame").read_bytes()))
        assert len(frames) == 1
        h, _ = frames[0]
        assert {k: v for k, v in h.items() if k != "seq"} == erwartet[name] == {k: v for k, v in head.items()
                                                                                if k != "seq"}


def test_umgebungen_lizenz():
    lizenz = (sz.UMGEBUNGEN_DIR / "LIZENZ.md").read_text(encoding="utf-8")
    for s in sz.SZENEN.values():
        if s["umgebung"]:
            assert (sz.UMGEBUNGEN_DIR / s["umgebung"]).read_bytes().startswith(b"#?RADIANCE"), s["umgebung"]
            assert s["umgebung"] in lizenz
    assert "CC0" in lizenz and "polyhaven.com" in lizenz


@pytest.mark.skipif(os.environ.get("KEVCAD_BLENDER_TEST") != "1" or bl.blender_pfad() is None,
                    reason="echter Blender-Lauf nur mit KEVCAD_BLENDER_TEST=1")
def test_echter_blender(tmp_path):
    h, p = teil("A")
    pfad, _ = bl.szene_schreiben(
        tmp_path, teile=[{"name": "A", "header": h, "payload": p, "matrix": None, "pbr": part_pbr(h, None)}],
        kamera={"projection": "perspective", "position": [300, -300, 200], "target": [50, 25, 0], "up": [0, 0, 1],
                "fov_deg": 30, "ortho_height_mm": None},
        szene=sz.szene("studio"), breite=160, hoehe=100, samples=4, ausgabe=tmp_path / "o.png")
    res = bl.BlenderLauf(pfad, zeitlimit=300).laufen()
    assert res["ok"], res
    assert (tmp_path / "o.png").read_bytes().startswith(b"\x89PNG")
