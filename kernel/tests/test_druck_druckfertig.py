"""Druckfertig je Objekt (Paket B, druck/druckfertig.py; DRUCKVORSCHAU.md „Druckfertig je Objekt“): vollständiger,
begründeter Satz Einstellungen je Objekt aus Geometrie, Zweck und Material, Kevins Vorgaben gehen vor, die Werte
kommen als Einstellungen je Objekt ins Bambu-Projekt. Typische Teile: Überhang, Klemmbohrung, Gewindeeinsatz, dünner
hoher Steg, optisches Teil. Der Nachweis mit Bambu Studio (3MF und G-Code) steht unten und läuft nur, wenn Bambu Studio
installiert ist."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest
from app_testutil import make_runtime

from kevcad_kernel.druck import druckfertig as df
from kevcad_kernel.druck import empfehlung as em
from kevcad_kernel.druck import slicer as sl

BAMBU = Path("/Applications/BambuStudio.app")


def _geo(**kw):
    g = {"groesse": [40.0, 30.0, 10.0], "auflage": 900.0, "auflage_pruefung": 900.0, "stuetzflaeche": 0.0,
         "ueberhang_hoehe": 0.0, "oben": 100.0, "ausrichtung_text": "−Z-Seite unten"}
    g.update(kw)
    return g


def _bohrung(d, waagrecht=False):
    return {"kennzahlen": {"bohrungen": [{"d": d, "waagrecht": waagrecht}]}}


def test_ueberhang_stuetzen_nur_wo_noetig():
    r = em.empfehle(_geo(stuetzflaeche=180.0, ueberhang_hoehe=20.0), "petg", "funktion")
    e, b = r["einstellungen"], r["begruendung_je"]
    assert (e["stuetzen"], e["stuetzen_nur_platte"], e["stuetzen_abstand_mm"]) == ("baum", True, 0.25)
    assert "180 mm²" in b["stuetzen"] and "nur von der Platte" in b["stuetzen_nur_platte"] and "PETG" in \
        b["stuetzen_abstand_mm"]
    ohne = em.empfehle(_geo(), "petg", "funktion")["einstellungen"]
    assert ohne["stuetzen"] == "keine" and "stuetzen_abstand_mm" not in ohne
    assert sl.prozess_einstellungen(e)["support_on_build_plate_only"] == "1"
    assert sl.prozess_einstellungen(e)["support_top_z_distance"] == "0.25"
    assert sl.prozess_einstellungen(ohne)["enable_support"] == "0"
    assert "support_on_build_plate_only" not in sl.prozess_einstellungen(ohne)


def test_klemmbohrung_und_einsatz_waende():
    """Bohrung mit Passung: mindestens 3 Wände; Einsatz M3 (Ø 4,0, senkrecht): Mindestwand 1,6 mm → 4 Wände, 30 %."""
    r = em.empfehle(_geo(), "petg", "zier", pruefung=_bohrung(12.2, waagrecht=True))
    assert r["einstellungen"]["waende"] == 3 and "Bohrung" in r["begruendung_je"]["waende"]
    assert any("3 Wände" in x for x in r["begruendung"])
    assert r["einstellungen"]["loch_kompensation_mm"] == 0.0 and "Zugabe steckt im Modell" in \
        r["begruendung_je"]["loch_kompensation_mm"]
    r = em.empfehle(_geo(), "petg", "funktion", pruefung=_bohrung(4.0))
    e = r["einstellungen"]
    assert (e["waende"], e["fuellung"]) == (4, 0.3) and "M3" in r["begruendung_je"]["waende"]
    r = em.empfehle(_geo(), "petg", "funktion", pruefung=_bohrung(8.1))  # M6: 3,3 mm Wand → höchstens 6
    assert r["einstellungen"]["waende"] == 6 and "Modifier" in r["begruendung_je"]["waende"]
    r = em.empfehle(_geo(), "petg", "funktion", pruefung=_bohrung(2.5))  # Kernloch M3 für eine Schraube
    assert r["einstellungen"]["waende"] == 4 and "Kernloch" in r["begruendung_je"]["waende"]
    p = sl.prozess_einstellungen(e)
    assert (p["wall_loops"], p["sparse_infill_density"], p["xy_hole_compensation"]) == ("4", "30%", "0")


def test_steg_brim_und_optik():
    r = em.empfehle(_geo(groesse=[20.0, 4.0, 60.0], auflage=80.0, auflage_pruefung=80.0), "petg", "funktion")
    e = r["einstellungen"]
    assert e["brim"] and e["brim_mm"] == 5.0 and "kippt" in r["begruendung_je"]["brim_mm"]
    assert sl.prozess_einstellungen(e)["brim_width"] == "5"
    r = em.empfehle(_geo(oben=1200.0), "pla", "zier")
    e = r["einstellungen"]
    assert (e["naht"], e["buegeln"], e["oberflaeche"]) == ("hinten", True, "monoton_linie")
    p = sl.prozess_einstellungen(e)
    assert (p["seam_position"], p["ironing_type"], p["top_surface_pattern"]) == ("back", "top", "monotonicline")
    f = em.empfehle(_geo(oben=1200.0), "pla", "funktion")["einstellungen"]
    assert (f["naht"], f["buegeln"]) == ("ausgerichtet", False)
    assert sl.prozess_einstellungen(f)["ironing_type"] == "no ironing"
    assert em.empfehle(_geo(), "pla", "zier")["einstellungen"]["buegeln"] is False  # Oberseite zu klein


def test_kevins_vorgaben_gehen_vor():
    r = em.empfehle(_geo(), "petg", "funktion", {"waende": 2, "naht": "zufall", "buegeln": True},
                    pruefung=_bohrung(4.0))
    e = r["einstellungen"]
    assert (e["waende"], e["naht"], e["buegeln"]) == (2, "zufall", True)
    assert set(r["fest"]) == {"waende", "naht", "buegeln"} and "fest vorgegeben" in r["begruendung_je"]["naht"]
    from kevcad_kernel.druck import vorgaben as vg

    assert vg.pruefe_einstellungen({"naht": "hinten", "brim_mm": 8, "buegeln": 1}) == \
        {"naht": "hinten", "brim_mm": 8.0, "buegeln": True}
    with pytest.raises(vg.VorgabeFehler):
        vg.pruefe_einstellungen({"naht": "oben"})
    from kevcad_kernel.protocol import check_druck_message, print_settings

    assert check_druck_message(print_settings("a", gruppe="g1", einstellungen={"naht": "hinten"})) == []


def test_einsatz_erkennung():
    assert df.einsatz_fuer(4.0)[1] == "M3" and df.einsatz_fuer(4.2)[1] == "M3"  # Nennmaß + 0,2 (CK-DS)
    assert df.einsatz_fuer(12.2) is None


# ---------------------------------------------------------------------------------------------------------------------
# Typische Teile in einem Projekt: Laufzeit (ohne Bambu Studio) und Nachweis mit Bambu Studio


PROBE = """from build123d import *
from kevcad import lager, show
t = Box(10, 10, 20, align=(Align.CENTER, Align.CENTER, Align.MIN)) + \\
    Pos(0, 0, 20) * Box(40, 10, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
show(lager.druckteil(t, "Überhang", material="petg", zweck="funktion", ausrichtung="-z"), "Probe/Überhang")
klemme = Box(30, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(6.1, 50)
show(Pos(60, 0, 0) * lager.druckteil(klemme, "Klemme", material="petg", zweck="tragend", ausrichtung="-z"),
     "Probe/Klemme")
einsatz = Box(20, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) - \\
    Pos(0, 0, 3.3) * Cylinder(2.0, 6.7, align=(Align.CENTER, Align.CENTER, Align.MIN))
show(Pos(120, 0, 0) * lager.druckteil(einsatz, "Einsatzhalter", material="petg", zweck="funktion",
                                      ausrichtung="-z"), "Probe/Einsatzhalter")
show(Pos(0, 60, 0) * lager.druckteil(Box(20, 4, 60, align=(Align.CENTER, Align.CENTER, Align.MIN)), "Steg",
                                     material="petg", zweck="funktion", ausrichtung="-z"), "Probe/Steg")
show(Pos(60, 60, 0) * lager.druckteil(Box(60, 60, 4, align=(Align.CENTER, Align.CENTER, Align.MIN)), "Blende",
                                      material="petg", zweck="zier", ausrichtung="-z"), "Probe/Blende")
"""


@pytest.fixture(scope="module")
def env():
    alt = {k: os.environ.get(k) for k in ("KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH", "KEVCAD_BAMBU_APP")}
    tmp = Path(tempfile.mkdtemp(prefix="kcdf", dir=tempfile.gettempdir()))
    mit = (BAMBU / "Contents/MacOS/BambuStudio").exists()
    os.environ.update({"KEVCAD_DRUCK_CACHE": str(tmp / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(tmp / "abgleich.json"),
                       "KEVCAD_BAMBU_APP": str(BAMBU if mit else tmp / "kein-bambu.app")})
    sl.index_leeren()
    rt = make_runtime(str(tmp / "k.sock"))
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    yield {"rt": rt, "tmp": tmp, "bambu": mit}
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)
    for k, v in alt.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    sl.index_leeren()


def test_typische_teile_je_objekt_eingestellt(env):
    """Fünf typische Teile, jedes mit eigenem, begründetem Satz Einstellungen in der Druckvorschau; mit Bambu Studio
    kommen sie je Objekt ins 3MF, sichtbar beim Slicen (Stützen, Brim, Bügeln), und der Export ist druckfertig."""
    rt, tmp = env["rt"], env["tmp"]
    assert rt.project_new(str(tmp / "Probe"), "empty")["ok"]
    assert rt.model_write(PROBE)["ok"]
    res = rt.run()
    assert res["ok"], res
    v = rt.druckvorschau()
    t = {g["name"]: g for g in v["teile"]}
    assert set(t) == {"Überhang", "Klemme", "Einsatzhalter", "Steg", "Blende"}
    e = {n: g["einstellungen"] for n, g in t.items()}
    assert e["Überhang"]["stuetzen"] != "keine" and e["Überhang"]["stuetzen_nur_platte"] is (
        e["Überhang"]["stuetzen"] == "baum")
    assert e["Überhang"]["stuetzen_abstand_mm"] == 0.25
    assert e["Klemme"]["waende"] >= 4 and e["Klemme"]["stuetzen"] == "keine"
    assert (e["Einsatzhalter"]["waende"], e["Einsatzhalter"]["fuellung"]) == (4, 0.3)
    assert "Gewindeeinsatz M3" in t["Einsatzhalter"]["begruendung_je"]["waende"]
    assert e["Steg"]["brim"] and e["Steg"]["brim_mm"] == 5.0
    assert (e["Blende"]["naht"], e["Blende"]["buegeln"]) == ("hinten", True)
    assert all(e[n]["naht"] == "ausgerichtet" and not e[n]["buegeln"] for n in e if n != "Blende")
    assert all(x["loch_kompensation_mm"] == 0.0 for x in e.values())
    for g in t.values():  # jede Einstellung begründet
        assert {"stuetzen", "brim_mm", "naht", "buegeln", "loch_kompensation_mm"} <= set(g["begruendung_je"])
    if not env["bambu"]:
        return
    # Mit Bambu Studio: 3MF, Einstellungen je Objekt in model_settings.config, Prüfung mit --slice 0
    ex = rt.druck_export(str(tmp / "probe.3mf"), filament="polymaker-polylite-petg-gelb")
    assert ex["ok"] and ex["geprueft"], ex
    assert ex["druckfertig"] is True, ex["hinweise"]
    assert any("druckfertig, in Bambu Studio geslict ohne Warnungen" in h for h in ex["hinweise"]), ex["hinweise"]
    assert {o["name"] for o in ex["objekte_einstellungen"]} == set(t)
    assert all("Texturplatte 80 °C" in o["begruendung_je"]["platte"] for o in ex["objekte_einstellungen"])
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(ex["pfad"]) as z:
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
        ps = json.loads(z.read("Metadata/project_settings.config"))
    je: dict[str, dict[str, str]] = {}
    for o in cfg.findall("object"):
        name = next(m.get("value") for m in o.findall("metadata") if m.get("key") == "name")
        werte = {m.get("key"): m.get("value") for m in o.findall("metadata") if m.get("key") != "name"}
        for p in o.findall("part"):
            werte.update({m.get("key"): m.get("value") for m in p.findall("metadata")})
        je[name.split("/")[-1]] = werte
    assert je["Blende"]["seam_position"] == "back" and je["Blende"]["ironing_type"] == "top"
    assert je["Klemme"]["seam_position"] == "aligned" and je["Klemme"]["ironing_type"] == "no ironing"
    assert je["Einsatzhalter"]["wall_loops"] == "4" and je["Einsatzhalter"]["sparse_infill_density"] == "30%"
    assert je["Steg"]["brim_type"] == "outer_only" and je["Steg"]["brim_width"] == "5"
    assert je["Überhang"]["enable_support"] == "1" and je["Überhang"]["support_top_z_distance"] == "0.25"
    assert all(w["xy_hole_compensation"] == "0" for w in je.values())
    assert ps["brim_type"] != "no_brim"  # sonst schaltete Bambu Studio den Brim je Objekt ab
    # Beim Slicen sichtbar: Stützen, Brim und Bügeln
    aus = tmp / "g"
    aus.mkdir()
    r = subprocess.run([str(sl.programm()), "--slice", "0", "--outputdir", str(aus), ex["pfad"]], cwd=str(aus),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0
    merkmale: set[str] = set()
    for g in aus.glob("*.gcode"):
        merkmale |= set(re.findall(r"^; FEATURE: (.*)$", g.read_text(errors="replace"), flags=re.M))
        g.unlink()
    assert {"Ironing", "Brim"} <= merkmale and any(m.startswith("Support") for m in merkmale), merkmale


def test_feste_vorgabe_ohne_widerspruch_in_den_gruenden():
    """Brim fest an, obwohl die Empfehlung keins wäre (KevCup, 22.10.2026): Breite gesetzt, Empfehlung gekennzeichnet."""
    r = em.empfehle(_geo(), "pla", "funktion", vorgaben={"brim": True})
    e, b = r["einstellungen"], r["begruendung_je"]
    assert e["brim"] is True and e["brim_mm"] > 0
    assert b["brim_mm"].startswith("Brim 5 mm, weil Brim fest vorgegeben ist")
    assert "ohne Vorgabe wäre die Empfehlung: kein Brim" in b["brim_mm"]
    assert b["brim"].startswith("fest vorgegeben")
    assert "Bedeutung" not in b.get("stuetzen_nur_platte", "")
