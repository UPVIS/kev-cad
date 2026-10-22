"""Versionen ohne Rechenprozess: Git-Anbindung, Ausschluss, Übernahme, Wiederherstellen, Meilensteine, Varianten,
Ausdünnen, Vergleich, Zwischenspeicher und Netze im Protokoll (PLAN-VERSIONEN.md)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.protocol import pack_netze, pack_part, unpack_netze, PartGeometry
from kevcad_kernel.versionen.archiv import (
    HAUPT,
    Versionsarchiv,
    VersionsFehler,
    gruppiere,
    lies_nachricht,
    nachricht,
)
from kevcad_kernel.versionen.git import MAX_DATEI_BYTES, git_verfuegbar
from kevcad_kernel.versionen.schnappschuss import (
    Zwischenspeicher,
    daten_aus_teilen,
    entpacke_netz,
    packe_netz,
)
from kevcad_kernel.versionen.vergleich import geister_auswahl, text, vergleiche, zusammenfassung

pytestmark = pytest.mark.skipif(not git_verfuegbar()[0], reason="git fehlt")


def projekt(tmp_path: Path, name: str = "P", code: str = "x = 1\n") -> Path:
    p = tmp_path / name
    p.mkdir()
    (p / "model.py").write_text(code)
    (p / "kevcad.json").write_text('{"version": 1}\n')
    return p


def archiv(p: Path) -> Versionsarchiv:
    a = Versionsarchiv(p)
    a.oeffnen()
    return a


def git_dateien(a: Versionsarchiv, ref: str = "HEAD") -> list[str]:
    return sorted(a.git.dateien(ref))


# ---------------------------------------------------------------------------------------------------------------------
# Git-Anbindung und Ausschluss


def test_eigenes_repo_ohne_fremde_konfiguration(tmp_path, monkeypatch):
    fremd = tmp_path / "fremd.gitconfig"
    fremd.write_text("[user]\n\tname = Fremder\n\temail = fremd@example.com\n[commit]\n\tgpgsign = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(fremd))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "falsch"))  # darf nicht durchschlagen
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Falsch")
    p = projekt(tmp_path)
    a = archiv(p)
    hook = a.git.git_dir / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    v, neu = a.nach_lauf(wer="kevin")
    assert neu and v.nr == 1 and v.titel == "Erster Stand"
    assert (p / ".kevcad" / "git" / "HEAD").is_file()
    autor = a.git.text("log", "-1", "--format=%an <%ae>|%cn").strip()
    assert autor == "Kev CAD <kevcad@localhost>|Kev CAD"
    assert not (tmp_path / "falsch").exists()
    assert not (p / ".git").exists()


def test_ausschluss_und_erfasste_dateien(tmp_path):
    p = projekt(tmp_path)
    for rel, inhalt in {
        "hilfe.py": "y = 2\n", "geometrie/kamera.py": "z = 3\n", "bewegungen.json": "[]\n",
        "katalog.json": "{}\n", "zukauf/igus-123/teil.step": "ISO-10303\n", "output/bild.png": "png",
        "bestand.json": "{}\n", "__pycache__/x.pyc": "pyc", ".DS_Store": "x", ".model.py.tmp": "tmp",
    }.items():
        f = p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(inhalt)
    a = archiv(p)
    a.nach_lauf(wer="kevin")
    assert git_dateien(a) == ["bewegungen.json", "geometrie/kamera.py", "hilfe.py", "katalog.json", "kevcad.json",
                              "model.py", "zukauf/igus-123/teil.step"]
    # Änderungen nur in ausgeschlossenen Dateien: keine neue Version
    (p / "output" / "bild.png").write_text("neu")
    (p / "bestand.json").write_text('{"a": 1}\n')
    (p / ".kevcad" / "log").mkdir(parents=True, exist_ok=True)
    (p / ".kevcad" / "log" / "runs.jsonl").write_text("{}\n")
    v, neu = a.nach_lauf(wer="kevin")
    assert not neu and v.nr == 1
    assert not a.ungesichert()


def test_grosse_datei_bleibt_draussen(tmp_path, monkeypatch):
    import kevcad_kernel.versionen.git as gitmod

    monkeypatch.setattr(gitmod, "MAX_DATEI_BYTES", 1000)
    p = projekt(tmp_path)
    (p / "scans").mkdir()
    (p / "scans" / "scan.ply").write_bytes(b"0" * 5000)
    a = archiv(p)
    a.nach_lauf(wer="kevin")
    assert "scans/scan.ply" not in git_dateien(a)
    assert a.git.grosse_dateien() == ["scans/scan.ply"]
    assert MAX_DATEI_BYTES > 1000


def test_version_nur_bei_aenderung_und_fortlaufende_nummern(tmp_path):
    p = projekt(tmp_path)
    a = archiv(p)
    v1, n1 = a.nach_lauf(wer="kevin", lauf=1)
    v1b, n1b = a.nach_lauf(wer="kevin", lauf=2)
    assert n1 and not n1b and v1b.nr == v1.nr
    (p / "model.py").write_text("x = 2\n")
    v2, n2 = a.nach_lauf(wer="agent", sitzung="abcdef123456", lauf=3)
    assert n2 and v2.nr == 2 and v2.titel == "Geändert: model.py"
    (p / "teil.py").write_text("t = 1\n")
    v3, _ = a.nach_lauf(wer="kevin")
    assert v3.nr == 3 and v3.titel == "Geändert: teil.py"
    liste = a.liste()
    assert [v["nr"] for v in liste["versionen"]] == [3, 2, 1]
    assert liste["versionen"][0]["aktuell"] and not liste["versionen"][1]["aktuell"]
    assert liste["versionen"][1]["wer_text"] == "Agent · abcdef" and liste["versionen"][1]["dateien"] == ["model.py"]
    # neues Archiv-Objekt (Kernel neu gestartet): Nummern laufen weiter
    b = archiv(p)
    (p / "model.py").write_text("x = 3\n")
    v4, _ = b.nach_lauf(wer="kevin")
    assert v4.nr == 4


def test_nachricht_und_felder():
    text = nachricht("Wiederhergestellt aus V3", nr=7, wer="agent", sitzung="s1", quelle="wiederherstellen",
                     zweig=HAUPT, aus=3, lauf=None)
    titel, f = lies_nachricht(text)
    assert titel == "Wiederhergestellt aus V3"
    assert f == {"nr": "7", "wer": "agent", "sitzung": "s1", "quelle": "wiederherstellen", "zweig": HAUPT, "aus": "3"}


# ---------------------------------------------------------------------------------------------------------------------
# Übernahme der alten Stände


def test_uebernahme_alter_staende(tmp_path):
    p = projekt(tmp_path, code="x = 3\n")
    (p / "geometrie").mkdir()
    (p / "geometrie" / "kamera.py").write_text("k = 1\n")
    alt = p / ".kevcad" / "versions"
    alt.mkdir(parents=True)
    import hashlib

    zeilen = []
    for i, code in enumerate(["x = 1\n", "x = 2\n", "x = 3\n"], 1):
        f = alt / f"{i:04d}-model.py"
        f.write_text(code)
        os.utime(f, (1_700_000_000 + i * 1000, 1_700_000_000 + i * 1000))
        h = hashlib.sha1(code.encode()).hexdigest()[:12]
        zeit = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(1_760_000_000 + i * 60))
        zeilen.append(json.dumps({"time": zeit, "run": i, "ok": True, "source": ["agent", "app", "auto"][i - 1],
                                  "file_hash": h}))
    (p / ".kevcad" / "log").mkdir()
    (p / ".kevcad" / "log" / "runs.jsonl").write_text("\n".join(zeilen) + "\n")
    a = Versionsarchiv(p)
    t0 = time.perf_counter()
    res = a.oeffnen()
    assert res == {"neu": True, "uebernommen": 3}
    assert time.perf_counter() - t0 < 5
    liste = a.liste()
    vs = liste["versionen"]
    assert [v["nr"] for v in vs] == [3, 2, 1]
    assert [v["quelle"] for v in vs] == ["uebernahme"] * 3
    assert [v["ts"] for v in vs] == [1_760_000_180, 1_760_000_120, 1_760_000_060]  # Zeit aus dem Laufprotokoll
    assert [v["wer"] for v in vs] == ["unbekannt", "kevin", "agent"]
    assert a.git.datei("V1" if False else vs[2]["commit"], "model.py") == b"x = 1\n"
    # Hilfsdateien des heutigen Stands stecken in jedem übernommenen Stand (nichts geht beim Wiederherstellen verloren)
    assert "geometrie/kamera.py" in a.git.dateien(vs[2]["commit"])
    assert not a.ungesichert()  # heutiges model.py = letzter alter Stand
    (p / "model.py").write_text("x = 4\n")
    v, neu = a.nach_lauf(wer="kevin")
    assert neu and v.nr == 4
    # zweites Öffnen übernimmt nichts doppelt
    assert Versionsarchiv(p).oeffnen() == {"neu": False, "uebernommen": 0}


# ---------------------------------------------------------------------------------------------------------------------
# Wiederherstellen, Meilensteine


def test_wiederherstellen_ist_nicht_zerstoerend(tmp_path):
    p = projekt(tmp_path, code="breite = 100\n")
    (p / "hilfe.py").write_text("h = 1\n")
    a = archiv(p)
    v1, _ = a.nach_lauf(wer="kevin")
    (p / "model.py").write_text("breite = 140\n")
    (p / "hilfe.py").unlink()
    (p / "neu.py").write_text("n = 1\n")
    v2, _ = a.nach_lauf(wer="agent")
    (p / "output").mkdir()
    (p / "output" / "x.step").write_text("step")
    (p / "model.py").write_text("breite = 180  # ungesichert\n")  # ohne Lauf
    res = a.wiederherstellen("V1", wer="kevin")
    assert res["gesichert"] is not None and res["gesichert"].quelle == "sicherung"
    assert res["aus"].nr == v1.nr and res["version"].nr == res["gesichert"].nr + 1
    assert (p / "model.py").read_text() == "breite = 100\n"
    assert (p / "hilfe.py").read_text() == "h = 1\n"
    assert not (p / "neu.py").exists()
    assert (p / "output" / "x.step").read_text() == "step"  # Ausgeschlossenes bleibt
    liste = a.liste()["versionen"]
    assert liste[0]["titel"] == "Wiederhergestellt aus V1" and liste[0]["aus"] == 1
    assert liste[1]["quelle"] == "sicherung"
    # die gesicherte Version enthält den ungesicherten Stand: wieder nach vorn mit einem Klick
    res2 = a.wiederherstellen(res["gesichert"].nr, wer="kevin")
    assert res2["gesichert"] is None
    assert (p / "model.py").read_text() == "breite = 180  # ungesichert\n"
    assert (p / "neu.py").exists() and not (p / "hilfe.py").exists()
    # gleicher Stand: nichts Neues
    res3 = a.wiederherstellen(res2["version"].nr, wer="kevin")
    assert res3["unveraendert"]
    with pytest.raises(VersionsFehler):
        a.wiederherstellen("V99", wer="kevin")


def test_meilenstein_und_suche(tmp_path):
    p = projekt(tmp_path)
    a = archiv(p)
    a.nach_lauf(wer="kevin")
    (p / "model.py").write_text("x = 5\n")  # ungesichert
    v = a.meilenstein(None, "Prototyp fertig", "Bohrungen geprüft", wer="agent", sitzung="s9")
    assert v.nr == 2 and v.quelle == "meilenstein"
    assert a.finde("Prototyp fertig").nr == 2
    assert a.finde("v2").nr == 2 and a.finde(" 2 ").nr == 2
    assert a.finde(v.commit[:8]).nr == 2
    m = a.liste()["versionen"][0]["meilenstein"]
    assert m["titel"] == "Prototyp fertig" and m["notiz"] == "Bohrungen geprüft" and m["wer"] == "agent"
    a.meilenstein("V1", "Start", wer="kevin")
    assert a.liste()["meilensteine"] == 2
    a.meilenstein_entfernen("Start")
    assert a.liste()["meilensteine"] == 1
    with pytest.raises(VersionsFehler):
        a.meilenstein(None, "  ", wer="kevin")


# ---------------------------------------------------------------------------------------------------------------------
# Varianten


def test_varianten_anlegen_wechseln_eigene_leiste(tmp_path):
    p = projekt(tmp_path, code="a = 1\n")
    a = archiv(p)
    a.nach_lauf(wer="kevin")
    (p / "model.py").write_text("a = 2\n")
    v2, _ = a.nach_lauf(wer="kevin")
    res = a.variante_anlegen("Leichtbau Ä", von="V1", wer="kevin")
    assert res["zweig"] == "v-leichtbau-ae" and res["von"].nr == 1
    assert (p / "model.py").read_text() == "a = 1\n"
    assert a.git.zweig() == "v-leichtbau-ae"
    (p / "model.py").write_text("a = 10\n")
    v3, _ = a.nach_lauf(wer="agent")
    liste = a.liste()
    assert liste["variante"] == "v-leichtbau-ae"
    assert [v["nr"] for v in liste["versionen"]] == [3, 1]
    assert [v["geerbt"] for v in liste["versionen"]] == [False, True]
    namen = {v["id"]: v for v in liste["varianten"]}
    assert namen["haupt"]["name"] == "Hauptstand" and namen["v-leichtbau-ae"]["name"] == "Leichtbau Ä"
    assert namen["v-leichtbau-ae"]["aktuell"] and namen["v-leichtbau-ae"]["versionen"] == 1
    # Wechsel mit einem Klick, ungesicherte Änderungen werden vorher Version der Variante
    (p / "model.py").write_text("a = 11\n")
    w = a.variante_wechseln("Hauptstand", wer="kevin")
    assert w["gesichert"].nr == 4 and w["gesichert"].zweig == "v-leichtbau-ae"
    assert (p / "model.py").read_text() == "a = 2\n"
    assert [v["nr"] for v in a.liste()["versionen"]] == [2, 1]
    a.variante_wechseln("leichtbau ä", wer="kevin")
    assert (p / "model.py").read_text() == "a = 11\n"
    with pytest.raises(VersionsFehler):
        a.variante_anlegen("Leichtbau Ä", wer="kevin")
    a.variante_umbenennen("Leichtbau Ä", "Alu")
    assert a.zweig_von("Alu") == "v-leichtbau-ae"
    with pytest.raises(VersionsFehler):
        a.variante_wechseln("gibt es nicht", wer="kevin")


# ---------------------------------------------------------------------------------------------------------------------
# Ausdünnen


def test_aufraeumen_duennt_alte_automatische_versionen_aus(tmp_path):
    p = projekt(tmp_path)
    a = archiv(p)
    basis = 1_700_000_000 - 1_700_000_000 % 3600  # volle Stunde, 2023
    nrs = {}
    for i in range(12):  # 12 Läufe in zwei Stunden, alle sehr alt
        (p / "model.py").write_text(f"x = {i}\n")
        a._vormerken()
        v = a._neue_version(f"Lauf {i}", wer="kevin", sitzung=None, quelle="lauf", datum=basis + i * 600)
        nrs[i] = v.nr
    a.aktualisiere(nrs[2], meilenstein={"titel": "Wichtig"}, kennzahlen={"teile": 1})
    a.aktualisiere(nrs[3], kennzahlen={"teile": 3})
    a.variante_anlegen("Abzweig", von=nrs[4], wer="kevin")  # Abzweigpunkt bleibt
    a.variante_wechseln("Hauptstand", wer="kevin")
    (p / "model.py").write_text("x = 99\n")
    jung, _ = a.nach_lauf(wer="kevin")  # jung: bleibt
    vorher = a.liste()["anzahl"]
    res = a.aufraeumen(jetzt=time.time())
    behalten = [v["nr"] for v in a.liste()["versionen"]]
    # Stunde 0: Läufe 0..5 → Meilenstein 2, Abzweig 4, letzte 5; Stunde 1: Läufe 6..11 → letzte 11
    assert sorted(behalten) == sorted([nrs[2], nrs[4], nrs[5], nrs[11], jung.nr])
    assert sorted(res["entfernt"]) == sorted([nrs[i] for i in (0, 1, 3, 6, 7, 8, 9, 10)])
    assert vorher == 13
    assert str(nrs[3]) not in a.meta["versionen"] and a.meta["versionen"][str(nrs[2])]["meilenstein"]
    # Inhalte bleiben: jede behaltene Version hat ihren Stand, die Arbeitskopie ist unverändert
    assert a.git.datei(a.finde(nrs[5]).commit, "model.py") == b"x = 5\n"
    assert (p / "model.py").read_text() == "x = 99\n" and not a.ungesichert()
    # Variante hängt weiter am (neu geschriebenen) Abzweigpunkt
    a.variante_wechseln("Abzweig", wer="kevin")
    assert [v["nr"] for v in a.liste()["versionen"]] == [nrs[4], nrs[2]]
    # zweites Aufräumen ändert nichts
    assert a.aufraeumen(jetzt=time.time())["entfernt"] == []


# ---------------------------------------------------------------------------------------------------------------------
# Leiste: dichte Folgen


def test_gruppen_dichter_folgen():
    t = 1_760_000_000
    vs = [{"nr": n, "ts": t - (10 - n) * 60, "quelle": "lauf"} for n in range(10, 0, -1)]
    vs[3]["meilenstein"] = {"titel": "M"}  # Nr. 7
    gruppen = gruppiere(vs)
    assert [g["text"] for g in gruppen] == ["6 Läufe in 5 Minuten"]
    assert [v["gruppe"] for v in vs] == [None, None, None, None, "g1", "g1", "g1", "g1", "g1", "g1"]
    # Lücke über fünf Minuten trennt
    vs = [{"nr": n, "ts": t + n * 600, "quelle": "lauf"} for n in range(6, 0, -1)]
    assert gruppiere(vs) == []


# ---------------------------------------------------------------------------------------------------------------------
# Code-Unterschied und Auspacken


def test_code_diff_und_materialisieren(tmp_path):
    p = projekt(tmp_path, code="breite = 100\nhoehe = 50\n")
    a = archiv(p)
    v1, _ = a.nach_lauf(wer="kevin")
    (p / "model.py").write_text("breite = 140\nhoehe = 50\n")
    (p / "teil.py").write_text("t = 1\n")
    d = a.code_diff(v1, None)
    assert {f["pfad"]: (f["status"], f["plus"], f["minus"]) for f in d["dateien"]} == {
        "model.py": ("M", 1, 1), "teil.py": ("A", 1, 0)}
    assert "-breite = 100" in d["diff"] and "+breite = 140" in d["diff"]
    v2, _ = a.nach_lauf(wer="kevin")
    assert "+t = 1" in a.code_diff(v1, v2)["diff"]
    ziel = a.materialisiere(v1, tmp_path / "aus")
    assert (ziel / "model.py").read_text() == "breite = 100\nhoehe = 50\n" and not (ziel / "teil.py").exists()


# ---------------------------------------------------------------------------------------------------------------------
# Vergleich


def _teil(name, key, vol, mn, mx, farbe=(0.5, 0.5, 0.5, 1.0), lager=None):
    h = {"props": {"volume": vol, "area": vol / 2, "mass": vol * 0.0027, "center": [(a + b) / 2 for a, b in zip(mn, mx)]},
         "bbox": {"min": list(mn), "max": list(mx)}, "color": list(farbe), "material": "aluminium",
         "counts": {"tri": 12}}
    if lager:
        h["stock"] = {"id": lager, "name": lager, "laenge": 100}
    return (name, key, h)


def test_vergleich_parameter_teile_stueckliste():
    bom_a = {"lines": [
        {"pos": 1, "art": "rohr", "stock_id": "rohr-12", "benennung": "Rohr 12", "masse_text": "882 mm", "anzahl": 4,
         "preis": 10.0, "teile": ["Bein 1", "Bein 2", "Bein 3", "Bein 4"]},
        {"pos": 2, "art": "flach", "stock_id": "flach-40", "benennung": "Flach 40", "masse_text": "120 mm",
         "anzahl": 1, "preis": 2.0, "teile": ["Platte"]},
        {"pos": 3, "art": "schraube", "stock_id": "m6", "benennung": "M6", "masse_text": "M6 × 16", "anzahl": 8,
         "preis": 1.0, "teile": ["S1"]}],
        "totals": {"kg": 3.0, "preis": 13.0}}
    bom_b = {"lines": [
        {"pos": 1, "art": "rohr", "stock_id": "rohr-12", "benennung": "Rohr 12", "masse_text": "882 mm", "anzahl": 2,
         "preis": 5.0, "teile": ["Bein 1", "Bein 2"]},
        {"pos": 2, "art": "flach", "stock_id": "flach-40", "benennung": "Flach 40", "masse_text": "140 mm",
         "anzahl": 1, "preis": 2.3, "teile": ["Platte"]},
        {"pos": 3, "art": "platte", "stock_id": "alu-3", "benennung": "Alu 3", "masse_text": "200 × 100 mm",
         "anzahl": 1, "preis": 4.0, "teile": ["Deckel"]}],
        "totals": {"kg": 3.5, "preis": 11.3}}
    alt = daten_aus_teilen([
        _teil("Platte", "k1", 1000, (0, 0, 0), (10, 10, 10)),
        _teil("Halter/Lasche", "k2", 500, (0, 0, 10), (5, 5, 20)),
        _teil("Weg", "k3", 100, (0, 0, 0), (1, 1, 1)),
        _teil("Gleich", "k4", 100, (0, 0, 0), (1, 1, 1)),
        _teil("Bunt", "k5", 100, (0, 0, 0), (1, 1, 1)),
    ], bom=bom_a, params={"breite": 120, "alt": 1}, pruefung={"state": "done", "zaehler": {"fehler": 0}})
    neu = daten_aus_teilen([
        _teil("Platte", "k1b", 1400, (0, 0, 0), (14, 10, 10)),  # Form
        _teil("Halter/Lasche", "k2b", 500, (5, 0, 10), (10, 5, 20)),  # Lage
        _teil("Gleich", "k4", 100, (0, 0, 0), (1, 1, 1)),
        _teil("Bunt", "k5", 100, (0, 0, 0), (1, 1, 1), farbe=(1, 0, 0, 1)),  # Farbe
        _teil("Deckel", "k6", 300, (0, 0, 30), (20, 10, 31)),  # neu
    ], bom=bom_b, params={"breite": 140, "neu": 2},
        pruefung={"state": "done", "zaehler": {"fehler": 2}, "zusammenfassung": "2 Durchdringungen",
                  "befunde": [{"id": "du1", "art": "durchdringung", "teile": ["A", "B"], "schwere": "fehler",
                               "text": "…"}]})
    v = vergleiche(alt, neu)
    assert v["params"] == [{"name": "breite", "alt": 120, "neu": 140, "art": "geaendert"},
                           {"name": "neu", "alt": None, "neu": 2, "art": "neu"},
                           {"name": "alt", "alt": 1, "neu": None, "art": "weg"}]
    t = v["teile"]
    assert t["neu"] == ["Deckel"] and t["weg"] == ["Weg"] and t["gleich"] == 1
    arten = {g["name"]: g["arten"] for g in t["geaendert"]}
    assert arten == {"Platte": ["form"], "Halter/Lasche": ["lage"], "Bunt": ["farbe"]}
    lasche = next(g for g in t["geaendert"] if g["name"] == "Halter/Lasche")
    assert lasche["verschiebung"] == [5.0, 0.0, 0.0]
    s = v["stueckliste"]
    assert [ln["benennung"] for ln in s["neu"]] == ["Alu 3"]
    assert [ln["benennung"] for ln in s["weg"]] == ["M6"]
    ge = {ln["benennung"]: (ln["alt_anzahl"], ln["neu_anzahl"], ln.get("alt_masse_text"), ln["masse_text"])
          for ln in s["geaendert"]}
    assert ge == {"Rohr 12": (4, 2, "882 mm", "882 mm"), "Flach 40": (1, 1, "120 mm", "140 mm")}
    z = zusammenfassung(v)
    assert "Teile: 3 geändert, 1 neu, 1 weg" in z and "3 Parameter geändert" in z and "Prüfung 0 → 2 Fehler" in z
    assert "Kosten 13 → 11,3 €" in z
    langtext = text(v)
    assert "Parameter breite: 120 → 140" in langtext and "Stückliste geändert: Flach 40 120 mm → 140 mm" in langtext
    geister = geister_auswahl(v, alt)
    assert sorted(geister) == [("Halter/Lasche", "k2", "alt"), ("Platte", "k1", "alt"), ("Weg", "k3", "weg")]


# ---------------------------------------------------------------------------------------------------------------------
# Zwischenspeicher und Protokoll


def _netz(n: int = 4):
    pos = np.arange(n * 3, dtype=np.float32).reshape(-1, 3)
    return {"positions": pos, "normals": np.ones_like(pos), "triangles": np.array([[0, 1, 2], [1, 2, 3]], np.uint32),
            "edge_points": pos[:2].copy(), "edge_offsets": np.array([0, 2], np.uint32)}


def test_netz_packen_und_speicher(tmp_path):
    n = _netz()
    zurueck = entpacke_netz(packe_netz(n))
    for k in n:
        assert np.array_equal(np.asarray(zurueck[k]).reshape(np.asarray(n[k]).shape), n[k]), k
    geo = PartGeometry(positions=n["positions"], normals=n["normals"], triangles=n["triangles"],
                       tri_face=np.zeros(2, np.int32), edge_points=n["edge_points"], edge_offsets=n["edge_offsets"],
                       vertices=np.zeros((0, 3), np.float32), faces=[{"t": "plane"}], edges=[{"t": "line"}])
    head, payload = pack_part(run=1, name="A", geometry=geo, color=(1, 0, 0, 1),
                              bbox={"min": [0, 0, 0], "max": [1, 1, 1]}, props={"volume": 1.0})
    sp = Zwischenspeicher(tmp_path / "v", max_bytes=10 ** 9)
    assert sp.speichere_netz("k:0.1:0.2", head, payload) is True
    assert sp.speichere_netz("k:0.1:0.2", head, payload) is False  # nur einmal
    assert sp.hat_netz("k:0.1:0.2")
    assert np.array_equal(sp.lade_netz("k:0.1:0.2")["triangles"], n["triangles"])
    sp.speichere_daten(5, {"teile": [{"name": "A", "key": "k:0.1:0.2"}]})
    assert sp.hat_alle_netze(sp.lade_daten(5))
    sp.speichere_netz("verwaist", head, payload)
    assert sp.entferne_verwaiste() == 1 and sp.hat_netz("k:0.1:0.2")
    sp.max_bytes = 1
    assert sp.begrenze() == 1 and not sp.hat_netz("k:0.1:0.2")


def test_netze_im_protokoll():
    koepfe, nutzlast = pack_netze([({"teil": "A", "art": "alt"}, _netz()), ({"teil": "B", "art": "weg"}, _netz(3))])
    assert koepfe[0] == {"teil": "A", "art": "alt", "vert": 4, "tri": 2, "epts": 2, "edge": 1}
    netze = unpack_netze(koepfe, nutzlast)
    assert np.array_equal(netze[1]["triangles"], _netz(3)["triangles"])
    with pytest.raises(ValueError):
        unpack_netze(koepfe, nutzlast + b"\0\0\0\0")


def test_git_fehlt_klare_meldung(tmp_path, monkeypatch):
    import kevcad_kernel.versionen.archiv as archivmod

    monkeypatch.setattr(archivmod, "git_verfuegbar", lambda: (False, "Git fehlt auf diesem Mac: Versionen sind aus."))
    p = projekt(tmp_path)
    a = Versionsarchiv(p)
    assert a.oeffnen()["fehler"].startswith("Git fehlt")
    assert a.nach_lauf(wer="kevin") == (None, False)
    liste = a.liste()
    assert liste["verfuegbar"] is False and liste["meldung"].startswith("Git fehlt")
    with pytest.raises(VersionsFehler, match="Git fehlt"):
        a.finde("V1")
    assert not (p / ".kevcad" / "git").exists()


def test_projektordner_in_fremdem_git_repo(tmp_path):
    """Liegt das Projekt in einem anderen Repo, bleibt dieses unberührt."""
    aussen = tmp_path / "aussen"
    aussen.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=aussen, check=True, capture_output=True)
    p = projekt(aussen)
    a = archiv(p)
    a.nach_lauf(wer="kevin")
    st = subprocess.run(["git", "status", "--porcelain"], cwd=aussen, capture_output=True, text=True).stdout
    assert "P/" in st  # für das äußere Repo ist der Ordner nur unversioniert
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=aussen,
                          capture_output=True).returncode != 0
