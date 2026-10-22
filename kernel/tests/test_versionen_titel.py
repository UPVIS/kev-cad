"""Automatische Titel der Versionen ohne Rechenprozess (versionen/titel.py, PLAN-VERSIONEN.md „Titel“): Regeln mit
Vorrang, Kürzen und Zusammenfassen der Teilnamen, Code ohne Wirkung, Stellen und Themen im Code, Übernahme alter
Stände mit Nachberechnung (nur Metadaten, Git bleibt), Titel vom Agenten und Kevins Meilensteine."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kevcad_kernel.versionen.archiv import KevinsMeilenstein, Versionsarchiv
from kevcad_kernel.versionen.git import git_verfuegbar
from kevcad_kernel.versionen.schnappschuss import Zwischenspeicher, daten_aus_teilen
from kevcad_kernel.versionen.titel import (
    MAX_LAENGE,
    OHNE_WIRKUNG,
    Segment,
    auto_titel,
    code_befund,
    gruppen,
    neue_einheiten,
    stamm,
    zusammensetzen,
)


def teil(name: str, key: str | None = None, vol: float = 1000.0, x: float = 0.0, farbe=(0.5, 0.5, 0.5, 1.0)):
    """Kopf wie aus PART_UPSERT: Würfel mit Kante 10 an der Stelle x (Formschlüssel aus Name und Maßen)."""
    h = {"props": {"volume": vol, "area": vol / 2, "mass": vol * 0.0027, "center": [x + 5, 5, 5]},
         "bbox": {"min": [x, 0, 0], "max": [x + 10, 10, 10]}, "color": list(farbe), "material": "aluminium",
         "counts": {"tri": 12}}
    return (name, key or f"{name}|{vol}|{x}", h)


def daten(teile, params=None, bom=None, schritte=None):
    return daten_aus_teilen(teile, bom=bom, params=params or {}, schritte=schritte)


def aenderung(alt: str, neu: str, pfad: str = "model.py") -> list[dict]:
    return [{"pfad": pfad, "status": "M", "alt": alt, "neu": neu, "binaer": False}]


CODE = '''from build123d import *
from kevcad import lager, show, step, param

breite = param("breite", 120)
KERN_M4 = 3.3


def klemme(name):
    """Klemme mit Flügelschraube."""
    return Box(10, 10, 10)


step("Rahmen")
rahmen = Box(breite, 40, 20)
show(rahmen, "Rahmen")

step("Schlitten")
show(Pos(0, 0, 20) * klemme("a"), "Schlitten")
'''


# ---------------------------------------------------------------------------------------------------------------------
# Regeln und Vorrang


def test_parameter_vor_teilen_und_folgen_entfallen():
    alt = daten([teil("Rahmen"), teil("Schlitten")], params={"breite": 120, "hoehe": 20})
    neu = daten([teil("Rahmen", vol=1400), teil("Schlitten", x=10), teil("Deckel")],
                params={"breite": 140, "hoehe": 20})
    res = auto_titel(aenderung(CODE, CODE.replace("120", "140")), alt, neu)
    assert res["titel"] == "breite 120 → 140 · + Deckel"
    assert res["regeln"] == ["parameter", "teile_neu"] and res["basis"] == "daten"
    # mehrere Parameter, neue und entfernte
    neu2 = daten([teil("Rahmen")], params={"breite": 140, "tiefe": 30})
    t = auto_titel(aenderung(CODE, CODE + "\n"), alt, neu2)["titel"]
    assert t.startswith("breite 120 → 140, tiefe = 30 neu, hoehe entfernt")


def test_neue_und_entfernte_teile_zusammengefasst():
    alt = daten([teil("Rahmen"), teil("Klotz")] + [teil(f"Klemme {s}/Gewindestift M4x30") for s in ("vorn links",
                                                                                                  "vorn rechts")])
    neu = daten([teil("Rahmen")] + [teil(f"Klemme {s}/Flügelschraube M4x{l}") for s, l in
                                    (("vorn links", 20), ("vorn rechts", 20), ("hinten links", 25),
                                     ("hinten rechts", 25))]
                + [teil(f"Rollwagen/Lenkrolle {i}/{t}") for i in range(1, 5) for t in ("Gabel", "Rad")])
    res = auto_titel(aenderung(CODE, CODE.replace("Klotz", "x")), alt, neu)
    # „Klemme hinten …“ ist als ganze Baugruppe neu, vorn kommen nur die Schrauben dazu; Entferntes bleibt erkennbar
    assert res["titel"] == "+ Flügelschraube M4 (2×), Klemme (2×), Rollwagen · − Klotz …"
    assert res["regeln"] == ["teile_neu", "teile_weg"]
    # ganze Baugruppen stehen für ihre Teile, Nummern als Bereich
    einheiten = neue_einheiten([f"Rollwagen/Lenkrolle {i}/Rad" for i in range(1, 5)], ["Rollwagen/Rahmen"])
    assert einheiten == [f"Rollwagen/Lenkrolle {i}" for i in range(1, 5)]
    assert gruppen(einheiten) == ["Lenkrolle 1–4"]
    assert auto_titel(aenderung(CODE, CODE + "x = 1\n"), daten([teil("Rollwagen/Rahmen")]),
                      daten([teil("Rollwagen/Rahmen")] + [teil(f"Rollwagen/Lenkrolle {i}/Rad")
                                                         for i in range(1, 5)]))["titel"] == "+ Lenkrolle 1–4"
    assert auto_titel(aenderung(CODE, CODE + "x = 1\n"), alt, daten([teil("Rahmen"), teil("Klemme vorn links/"
                                                                                          "Gewindestift M4x30")]))[
        "titel"] == "− Klotz, Klemme vorn rechts"  # die Baugruppe ist ganz weg


def test_kurznamen_und_stufen():
    assert stamm("Stellring hinten links (Druck)") == ("Stellring", None)
    assert stamm("Seitenstange links (Rohr 1)") == ("Seitenstange", None)
    assert stamm("Lenkrolle 3") == ("Lenkrolle", 3)
    assert stamm("Gewindestift M4x35 vorn links") == ("Gewindestift M4x35", None)
    namen = [f"KS/Flügelschraube M4x{l} {s}" for l in (12, 25) for s in ("links", "rechts")]
    assert gruppen(namen) == ["Flügelschraube M4x12 (2×)", "Flügelschraube M4x25 (2×)"]
    assert gruppen(namen, 1) == ["Flügelschraube M4 (4×)"]
    assert gruppen(["A/Lenkrolle 1", "A/Lenkrolle 3"]) == ["Lenkrolle (2×)"]  # nicht zusammenhängend
    assert gruppen(["Stellring hinten links (Druck)"]) == ["Stellring hinten links"]


def test_geaenderte_verschobene_umgefaerbte_teile():
    alt = daten([teil("Rahmen"), teil("Schlitten links (Druck)"), teil("Schlitten rechts (Druck)"), teil("Einsatz"),
                 teil("Deckel")])
    neu = daten([teil("Rahmen", vol=1200), teil("Schlitten links (Druck)", vol=900),
                 teil("Schlitten rechts (Druck)", vol=900), teil("Einsatz", x=4),
                 teil("Deckel", farbe=(1, 0, 0, 1))])
    res = auto_titel(aenderung(CODE, CODE.replace("40, 20", "40, 24")), alt, neu)
    assert res["titel"] == "Rahmen … geändert · Einsatz verschoben · Deckel umgefärbt"  # gleicher Rang teilt sich
    assert res["regeln"] == ["teile_geaendert", "teile_verschoben", "teile_umgefaerbt"]
    neu_kurz = daten([teil("Rahmen", vol=1200), teil("Schlitten links (Druck)", vol=900),
                      teil("Schlitten rechts (Druck)", vol=900), teil("Einsatz", x=4), teil("Deckel")])
    assert auto_titel(aenderung(CODE, CODE + "w = 1\n"), alt, neu_kurz)["titel"] == \
        "Rahmen, Schlitten geändert · Einsatz verschoben"
    # alle Teile einer Baugruppe geändert: die Baugruppe steht für sie
    alt = daten([teil("Halter/Lasche"), teil("Halter/Platte"), teil("Fuß")])
    neu = daten([teil("Halter/Lasche", vol=2), teil("Halter/Platte", vol=3), teil("Fuß")])
    assert auto_titel(aenderung(CODE, CODE + "y = 2\n"), alt, neu)["titel"] == "Halter geändert"


def test_stueckliste_ohne_teileaenderung():
    zeile = {"pos": 1, "art": "zukauf", "stock_id": "lager-61801", "benennung": "Rillenkugellager 61801-2RS "
             "(12 × 21 × 5 mm)", "masse_text": "", "anzahl": 4, "preis": 8.0, "teile": ["Rolle"]}
    alt = daten([teil("Rolle")], bom={"lines": [], "totals": {}})
    neu = daten([teil("Rolle")], bom={"lines": [zeile], "totals": {"preis": 8.0}})
    t = auto_titel(aenderung(CODE, CODE.replace('"Rahmen")', '"Rahmen")  ')), alt, neu)["titel"]
    assert t == "Stückliste + Rillenkugellager 61801-2RS (4×)"
    assert auto_titel(aenderung(CODE, CODE + "z = 3\n"), neu, alt)["titel"] == \
        "Stückliste − Rillenkugellager 61801-2RS (4×)"


def test_neue_schritte_und_dateien():
    alt = daten([teil("Rahmen")], schritte=["Rahmen"])
    neu = daten([teil("Rahmen"), teil("Bohrung")], schritte=["Rahmen", "Bohrungen"])
    assert auto_titel(aenderung(CODE, CODE + 'step("Bohrungen")\n'), alt, neu)["titel"] == \
        "+ Bohrung · neuer Schritt „Bohrungen“"
    # ohne Daten: Schritte und Parameter aus dem Code
    neu_code = CODE.replace('param("breite", 120)', 'param("breite", 150)') + 'step("Bohrungen")\n'
    res = auto_titel(aenderung(CODE, neu_code), None, None)
    assert res["titel"] == "breite 120 → 150 · neuer Schritt „Bohrungen“" and res["basis"] == "code"
    # nur eine binäre Datei: zuletzt die Dateien
    binaer = [{"pfad": "zukauf/igus/teil.step", "status": "M", "alt": None, "neu": None, "binaer": True}]
    assert auto_titel(binaer, alt, alt)["titel"] == "Geändert: zukauf/igus/teil.step"


def test_code_ohne_wirkung_und_stellen():
    alt = daten([teil("Rahmen"), teil("Schlitten")])
    gleich = daten([teil("Rahmen"), teil("Schlitten")])
    kommentar = CODE.replace("KERN_M4 = 3.3", "KERN_M4 = 3.3  # Kernloch").replace(
        '"""Klemme mit Flügelschraube."""', '"""Klemme mit Flügelschraube DIN 316,\n    von Hand."""')
    umbruch = CODE.replace("rahmen = Box(breite, 40, 20)", "rahmen = Box(breite,\n             40, 20)")
    for code in (kommentar, umbruch):
        assert auto_titel(aenderung(CODE, code), alt, gleich)["titel"] == OHNE_WIRKUNG
        assert auto_titel(aenderung(CODE, code), None, None)["titel"] == OHNE_WIRKUNG  # auch ohne Daten sicher
    assert auto_titel(aenderung('{"a": 1}', '{\n  "a": 1\n}\n', "bewegungen.json"), alt, gleich)["titel"] == \
        OHNE_WIRKUNG
    # mit Wirkung im Code, aber gleichen Teilen: wo
    in_funktion = CODE.replace("return Box(10, 10, 10)", "return Box(10, 10, 10).moved(Location())")
    assert auto_titel(aenderung(CODE, in_funktion), alt, gleich)["titel"] == "Code in klemme() geändert, Teile gleich"
    im_abschnitt = CODE.replace('show(rahmen, "Rahmen")', 'rahmen = rahmen.moved(Location())\nshow(rahmen, "Rahmen")')
    assert auto_titel(aenderung(CODE, im_abschnitt), alt, gleich)["titel"] == \
        "Code in „Rahmen“ geändert, Teile gleich"
    konstante = CODE.replace("KERN_M4 = 3.3", "KERN_M4 = 3.4")
    assert auto_titel(aenderung(CODE, konstante), alt, gleich)["titel"] == "Code in KERN_M4 geändert, Teile gleich"
    # Thema aus Aufrufen von Kev CAD
    bed = CODE + 'import kevcad.bedingungen as bed\nbed.verbinde("Schlitten", "Rahmen", art="schraube")\n'
    res = auto_titel(aenderung(CODE, bed), alt, gleich)
    assert res["titel"] == "Bedingungen in „Schlitten“ geändert, Teile gleich"
    b = code_befund(aenderung(CODE, bed))
    assert not b.ohne_wirkung and list(b.themen) == ["Bedingungen"]


def test_laenge_und_zusammensetzen():
    s1 = Segment("a", ["eins zwei drei vier fünf sechs sieben acht neun zehn elf", "eins …"], "1 Sache")
    s2 = Segment("b", ["zweites Segment ausführlich", "zweites"], "2 Sachen")
    text = zusammensetzen([s1, s2])
    assert len(text) <= MAX_LAENGE and text.startswith("eins") and "zweites" in text
    lang = Segment("x", ["x" * 90], None)
    assert len(zusammensetzen([lang])) == MAX_LAENGE and zusammensetzen([lang]).endswith("…")
    viele = daten([teil(f"Teil{i} Name{i}") for i in range(30)])
    t = auto_titel(aenderung(CODE, CODE + "q = 1\n"), daten([]), viele)["titel"]
    assert len(t) <= MAX_LAENGE and t.startswith("+ ")


# ---------------------------------------------------------------------------------------------------------------------
# Archiv: Metadaten, Übernahme mit Nachberechnung, Agent, Kevins Meilensteine

pytestmark_git = pytest.mark.skipif(not git_verfuegbar()[0], reason="git fehlt")


def projekt(tmp_path: Path, code: str = CODE) -> Path:
    p = tmp_path / "P"
    p.mkdir()
    (p / "model.py").write_text(code)
    (p / "kevcad.json").write_text('{"version": 1}\n')
    return p


@pytestmark_git
def test_uebernommene_staende_bekommen_titel_ohne_git_zu_aendern(tmp_path):
    p = projekt(tmp_path, CODE.replace("120", "160"))
    alt = p / ".kevcad" / "versions"
    alt.mkdir(parents=True)
    staende = [CODE, CODE.replace("120", "140"), CODE.replace("120", "160")]
    for i, code in enumerate(staende, 1):
        (alt / f"{i:04d}-model.py").write_text(code)
    a = Versionsarchiv(p)
    assert a.oeffnen()["uebernommen"] == 3
    log_vorher = a.git.text("log", "--all", "--format=%H %s")
    # vor jeder Berechnung: „Übernommener Stand“ als Titel (offen)
    v = a.liste()["versionen"][0]
    assert (v["titel"], v["zusatz"], v["titel_quelle"]) == ("Übernommener Stand", None, "offen")
    alle = a.alle_versionen()
    nach_commit = {x.commit: x for x in alle.values()}
    # erst aus dem Code (Kennzahlen fehlen noch)
    for x in sorted(alle.values(), key=lambda x: x.nr):
        vor = nach_commit.get(x.eltern)
        assert a.titel_veraltet(x, vor, daten_da=False)
        a.titel_berechnen(x, vor, None, None)
        assert not a.titel_veraltet(x, vor, daten_da=False)
    vs = {x["nr"]: x for x in a.liste()["versionen"]}
    assert vs[1]["titel"] == "Erster Stand"
    assert vs[3]["titel"] == "breite 140 → 160" and vs[3]["zusatz"] == "Übernommener Stand"
    assert vs[3]["titel_quelle"] == "auto"
    # die Nachberechnung liefert Daten: der Titel wird aus den Daten neu berechnet (mit Teilen)
    sp = Zwischenspeicher(a.ordner)
    for nr, b in ((2, 140), (3, 160)):
        sp.speichere_daten(nr, daten([teil("Rahmen", vol=b * 800), teil("Schlitten")] +
                                     ([teil("Deckel")] if nr == 3 else []), params={"breite": b}))
    v3 = alle[3]
    assert a.titel_veraltet(v3, alle[2], daten_da=True)
    a.titel_berechnen(v3, alle[2], sp.lade_daten(2), sp.lade_daten(3))
    v = a.liste()["versionen"][0]
    assert v["titel"] == "breite 140 → 160 · + Deckel" and v["zusatz"] == "Übernommener Stand"
    # ein neues Archiv-Objekt (Kernel neu gestartet) liest die Titel aus den Metadaten; Git ist unverändert
    b = Versionsarchiv(p)
    b.oeffnen()
    assert b.liste()["versionen"][0]["titel"] == "breite 140 → 160 · + Deckel"
    assert b.git.text("log", "--all", "--format=%H %s") == log_vorher
    meta = json.loads((p / ".kevcad" / "versionen" / "index.json").read_text())
    assert meta["versionen"]["3"]["titel_basis"] == "daten" and meta["versionen"]["3"]["titel_gegen"] == 2


@pytestmark_git
def test_agent_titel_vorrang_und_kevins_meilenstein_bleibt(tmp_path):
    p = projekt(tmp_path)
    a = Versionsarchiv(p)
    a.oeffnen()
    v1, _ = a.nach_lauf(wer="kevin")
    (p / "model.py").write_text(CODE.replace("120", "140"))
    v2, neu = a.nach_lauf(wer="agent")
    assert neu and v2.eltern == v1.commit
    a.titel_berechnen(v2, v1, None, None)
    a.titel_agent(v2.nr, "  Rahmen   breiter  ")
    v = a.liste()["versionen"][0]
    assert (v["titel"], v["zusatz"], v["titel_quelle"]) == ("Rahmen breiter", "breite 120 → 140", "agent")
    assert v["titel_auto"] == "breite 120 → 140"
    # Kevins Meilenstein: der Agent überschreibt ihn nicht, die Automatik auch nicht
    a.meilenstein("V2", "Kevins Name", wer="kevin")
    with pytest.raises(KevinsMeilenstein) as exc:
        a.meilenstein("V2", "Agent will umbenennen", wer="agent")
    assert exc.value.meilenstein["titel"] == "Kevins Name"
    a.titel_berechnen(v2, v1, None, None)
    v = a.liste()["versionen"][0]
    assert v["meilenstein"]["titel"] == "Kevins Name" and v["titel"] == "Rahmen breiter"
    # auf Kevins ausdrücklichen Wunsch
    a.meilenstein("V2", "Neu benannt", wer="agent", ersetzen=True)
    assert a.liste()["versionen"][0]["meilenstein"]["titel"] == "Neu benannt"
    # Meilensteine des Agenten darf der Agent ändern, Kevin ohnehin
    a.meilenstein("V2", "Wieder anders", wer="agent")
    a.meilenstein("V2", "Kevin zuletzt", wer="kevin")
    assert a.liste()["versionen"][0]["meilenstein"]["titel"] == "Kevin zuletzt"


@pytestmark_git
def test_sicherung_und_wiederherstellen_mit_zusatz(tmp_path):
    p = projekt(tmp_path)
    a = Versionsarchiv(p)
    a.oeffnen()
    v1, _ = a.nach_lauf(wer="kevin")
    (p / "model.py").write_text(CODE.replace("120", "140"))
    v2, _ = a.nach_lauf(wer="kevin")
    (p / "model.py").write_text(CODE.replace("120", "180"))  # ungesichert
    res = a.wiederherstellen("V1", wer="kevin")
    alle = a.alle_versionen()
    nach_commit = {x.commit: x for x in alle.values()}
    for x in alle.values():
        a.titel_berechnen(x, nach_commit.get(x.eltern), None, None)
    vs = {x["nr"]: x for x in a.liste()["versionen"]}
    s = vs[res["gesichert"].nr]
    assert s["titel"] == "Gesichert vor dem Wiederherstellen" and s["zusatz"] == "breite 140 → 180"
    w = vs[res["version"].nr]
    assert w["titel"] == "Wiederhergestellt aus V1" and w["zusatz"] == "breite 180 → 120"
    assert time.time() - w["ts"] < 60
