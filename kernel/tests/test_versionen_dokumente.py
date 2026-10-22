"""Dokumente in den Versionen ohne Rechenprozess (versionen/dokumente.py, archiv.py): was sich an Blättern und Bauplan
geändert hat, Titel aus Dokumentänderungen, Vergleich mit eigener Gruppe statt Code und das Nachtragen der
Hintergrundrechnung in die Version des Laufs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from kevcad_kernel.versionen.archiv import Versionsarchiv
from kevcad_kernel.versionen.dokumente import bauplan_punkte, blatt_punkte, vergleiche_dokumente
from kevcad_kernel.versionen.git import git_verfuegbar
from kevcad_kernel.versionen.titel import auto_titel
from kevcad_kernel.versionen.vergleich import text, vergleiche, zusammenfassung

BLATT_PFAD = "dokumente/zeichnungen/seitenstange.json"


def bezug(x: float) -> dict:
    return {"teil": "Gestell/Seitenstange", "art": "flaeche",
            "signatur": {"typ": "ebene", "mitte": [x, 0.0, 0.0], "richtung": [1.0, 0.0, 0.0]}, "merkmal": None}


def blatt(laenge: float = 500.0) -> dict:
    return {"version": 1, "id": "seitenstange", "titel": "Seitenstange", "format": "A4", "ausrichtung": "quer",
            "massstab": "1:5", "inhalt": {"art": "teil", "teile": ["Gestell/Seitenstange"]},
            "schriftfeld": {"benennung": "Seitenstange", "werkstoff": "EN AW-6060", "version": None},
            "ansichten": [{"id": "v1", "art": "vorn", "lage": [100, 120]}, {"id": "v2", "art": "oben", "lage": [100, 60]}],
            "masse": [{"id": "m1", "art": "linear", "ansicht": "v1", "bezuege": [bezug(0), bezug(laenge)],
                       "quelle": "auto", "verwaist": False},
                      {"id": "m2", "art": "durchmesser", "ansicht": "v2", "bezuege": [bezug(laenge / 2)],
                       "quelle": "auto", "verwaist": False},
                      {"id": "m3", "art": "linear", "ansicht": "v1", "bezuege": [bezug(10), bezug(laenge - 10)],
                       "quelle": "kevin", "verwaist": False}],
            "notizen": [], "tabellen": [], "unterdrueckt": [], "auto": {"ansichten": True, "masse": True}}


def schritt(sid: str, titel: str, text_: str = "…", **kw) -> dict:
    return {"id": sid, "titel": titel, "text": text_, "quelle": "auto", "fest": False, "teile": [sid], "neu": [sid],
            "bild": {"kamera": {"distance": 100}}, "pruefung": [], **kw}


def bauplan(texte: dict[str, str] | None = None) -> dict:
    texte = texte or {}
    montage = [schritt(f"m-{i}", f"Teil {i} montieren", texte.get(f"m-{i}", "…")) for i in range(1, 8)]
    return {"version": 1, "titel": "Gestell", "abschnitte": [
        {"art": "material", "titel": "Material", "schritte": []},
        {"art": "montage", "titel": "Montage", "schritte": montage}], "vorher": []}


def aenderung(pfad: str, alt: dict | str | None, neu: dict | str | None) -> dict:
    def t(x):
        return x if isinstance(x, str) or x is None else json.dumps(x, indent=1, ensure_ascii=False)
    status = "A" if alt is None else "D" if neu is None else "M"
    return {"pfad": pfad, "status": status, "alt": t(alt), "neu": t(neu), "binaer": False}


# ---------------------------------------------------------------------------------------------------------------------
# Was sich an Blättern und Bauplan geändert hat


def test_blatt_punkte():
    alt, neu = blatt(500), blatt(600)
    assert blatt_punkte(alt, neu) == ["3 Maße geändert"]
    neu["masse"][2]["verwaist"] = True
    neu["masse"].append({"id": "m4", "art": "radius", "ansicht": "v1", "bezuege": [], "quelle": "agent"})
    neu["ansichten"][1]["lage"] = [120, 60]
    neu["massstab"] = "1:2"
    assert blatt_punkte(alt, neu) == ["Maß neu", "2 Maße geändert", "Maß verwaist", "Maßstab 1:5 → 1:2",
                                      "Ansicht verschoben"]
    assert blatt_punkte(alt, copy.deepcopy(alt)) == []


def test_bauplan_punkte():
    alt = bauplan()
    neu = bauplan({"m-6": "Teil 6 mit zwei Schrauben M6 befestigen."})
    assert bauplan_punkte(alt, neu) == ["Schritt 6 umformuliert"]  # Nummer im Plan (Material hat keine Schritte)
    neu["abschnitte"][1]["schritte"].append(schritt("m-8", "Deckel aufsetzen"))
    neu["abschnitte"][1]["schritte"][2]["fest"] = True
    del neu["abschnitte"][1]["schritte"][0]
    punkte = bauplan_punkte(alt, neu)
    assert punkte[:4] == ["Schritt 7 neu", "Schritt „Teil 1 montieren“ entfernt", "Schritt 5 umformuliert",
                          "Schritt 2 festgehalten"]


def test_vergleiche_dokumente_ohne_formatierung():
    a = blatt(500)
    eintraege = vergleiche_dokumente([
        aenderung(BLATT_PFAD, a, blatt(600)),
        aenderung("dokumente/zeichnungen/platte.json", None, {**blatt(), "id": "platte", "titel": "Platte"}),
        {"pfad": "dokumente/zeichnungen/wange.json", "status": "M", "alt": json.dumps(a),
         "neu": json.dumps(a, indent=4), "binaer": False},  # nur umformatiert: fällt weg
        aenderung("dokumente/bauplan.json", bauplan(), bauplan({"m-7": "neu"})),
        aenderung("model.py", "x = 1\n", "x = 2\n"),  # kein Dokument
    ])
    assert [e["text"] for e in eintraege] == ["Zeichnung Platte neu", "Zeichnung Seitenstange: 3 Maße geändert",
                                              "Bauplan: Schritt 7 umformuliert"]


# ---------------------------------------------------------------------------------------------------------------------
# Titel


def test_titel_nur_dokumente():
    res = auto_titel([aenderung(BLATT_PFAD, blatt(500), blatt(600))], None, None)
    assert res["titel"] == "Zeichnung Seitenstange: 3 Maße geändert" and res["regeln"] == ["dokumente"]
    res = auto_titel([aenderung("dokumente/bauplan.json", bauplan(), bauplan({"m-7": "anders"}))], None, None)
    assert res["titel"] == "Bauplan: Schritt 7 umformuliert"
    neu = [aenderung(f"dokumente/zeichnungen/{n.lower()}.json", None, {**blatt(), "id": n.lower(), "titel": n})
           for n in ("Platte", "Wange")]
    assert auto_titel(neu, None, None)["titel"] == "Zeichnungen Platte, Wange neu"
    # nie „Code in seitenstange.json geändert“
    assert "Code" not in auto_titel([aenderung(BLATT_PFAD, blatt(500), blatt(600))], None, None)["titel"]


def test_titel_modellaenderung_vor_dokumenten():
    aend = [aenderung("model.py", 'b = param("b", 60)\n', 'b = param("b", 80)\n'),
            aenderung(BLATT_PFAD, blatt(500), blatt(600))]
    assert auto_titel(aend, None, None)["titel"] == "b 60 → 80"  # neu zugeordnete Maße sind die Folge
    aend = [aenderung("model.py", "x = 1\n", "x = 1  # Kommentar\n"), aenderung(BLATT_PFAD, blatt(500), blatt(600))]
    assert auto_titel(aend, None, None)["titel"] == "Zeichnung Seitenstange: 3 Maße geändert · Code aufgeräumt"


def test_vergleich_text_und_zusammenfassung_nennen_dokumente():
    leer = {"teile": [], "params": {}, "stueckliste": None, "pruefung": None, "kennzahlen": {}}
    v = vergleiche(leer, leer)
    v["dokumente"] = vergleiche_dokumente([aenderung(BLATT_PFAD, blatt(500), blatt(600))])
    assert zusammenfassung(v).endswith("Zeichnung Seitenstange: 3 Maße geändert")
    assert "- Dokument: Zeichnung Seitenstange: 3 Maße geändert" in text(v)


# ---------------------------------------------------------------------------------------------------------------------
# Archiv: Nachtragen und Vergleich

git = pytest.mark.skipif(not git_verfuegbar()[0], reason="git fehlt")


def projekt(tmp_path: Path) -> tuple[Path, Versionsarchiv]:
    p = tmp_path / "P"
    (p / "dokumente" / "zeichnungen").mkdir(parents=True)
    (p / "model.py").write_text('b = param("b", 60)\n')
    (p / BLATT_PFAD).write_text(json.dumps(blatt(500)))
    a = Versionsarchiv(p)
    a.oeffnen()
    return p, a


@git
def test_nachtragen_in_die_version_des_laufs(tmp_path):
    p, a = projekt(tmp_path)
    v1, neu = a.nach_lauf(wer="kevin", lauf=1)
    assert neu
    (p / "model.py").write_text('b = param("b", 80)\n')
    v2, neu = a.nach_lauf(wer="kevin", lauf=2)
    assert neu and v2.nr == 2
    # Hintergrundrechnung: Blatt neu zugeordnet; Kevin tippt schon weiter an model.py
    (p / BLATT_PFAD).write_text(json.dumps(blatt(600)))
    (p / "model.py").write_text('b = param("b", 90)\n')
    nach = a.dokumente_nachtragen(v2.nr, v2.commit)
    assert nach is not None and nach.nr == 2 and nach.commit != v2.commit
    assert nach.eltern == v1.commit and nach.ts == v2.ts and a.git.nachricht(nach.commit) == a.git.nachricht(v2.commit)
    assert json.loads(a.git.datei(nach.commit, BLATT_PFAD)) == blatt(600)
    assert a.git.datei(nach.commit, "model.py") == b'b = param("b", 80)\n'  # model.py bleibt für den nächsten Lauf
    assert [v.nr for v in a.versionen()] == [2, 1]
    v3, neu = a.nach_lauf(wer="kevin", lauf=3)
    assert neu and v3.dateien == ["model.py"]
    assert a.dokumente_nachtragen(v3.nr, v3.commit) is None  # nichts nachzutragen


@git
def test_nachtragen_nur_an_der_spitze_ohne_meilenstein(tmp_path):
    p, a = projekt(tmp_path)
    v1, _ = a.nach_lauf(wer="kevin", lauf=1)
    (p / BLATT_PFAD).write_text(json.dumps(blatt(600)))
    a.meilenstein(v1.nr, "Prototyp", wer="kevin")
    assert a.nachtrag_moeglich(v1.nr, v1.commit) is None
    assert a.dokumente_nachtragen(v1.nr, v1.commit) is None
    a.meilenstein_entfernen(v1.nr)
    a.variante_anlegen("Flach", wer="kevin")  # zweigt an V1 ab: V1 gehört jetzt auch der Variante
    assert a.dokumente_nachtragen(v1.nr, v1.commit) is None
    a.variante_wechseln("Hauptstand", wer="kevin")
    (p / "model.py").write_text('b = param("b", 70)\n')
    v2, _ = a.nach_lauf(wer="kevin", lauf=2)
    assert a.dokumente_nachtragen(v1.nr, v1.commit) is None  # nicht mehr die Spitze


@git
def test_nur_dokumente_geaendert_legt_mit_nachtrag_keine_version_an(tmp_path):
    p, a = projekt(tmp_path)
    v1, _ = a.nach_lauf(wer="kevin", lauf=1)
    (p / BLATT_PFAD).write_text(json.dumps(blatt(600)))
    v, neu = a.nach_lauf(wer="kevin", lauf=2, nachtrag=(v1.nr, v1.commit))
    assert not neu and v.nr == 1
    v, neu = a.nach_lauf(wer="kevin", lauf=3)  # ohne Nachtrag: eine Änderung wie jede andere
    assert neu and v.nr == 2
    (p / BLATT_PFAD).write_text(json.dumps(blatt(700)))
    (p / "model.py").write_text('b = param("b", 70)\n')
    v, neu = a.nach_lauf(wer="kevin", lauf=4, nachtrag=(2, a.aktuelle().commit))
    assert neu and v.nr == 3  # auch model.py geändert: neue Version


@git
def test_vergleich_dokumente_eigene_gruppe(tmp_path):
    p, a = projekt(tmp_path)
    v1, _ = a.nach_lauf(wer="kevin", lauf=1)
    (p / BLATT_PFAD).write_text(json.dumps(blatt(600)))
    (p / "model.py").write_text('b = param("b", 80)\n')
    code = a.code_diff(v1, None)
    assert [d["pfad"] for d in code["dateien"]] == ["model.py"] and "seitenstange" not in code["diff"]
    assert [e["text"] for e in a.dokumente_vergleich(v1, None)] == ["Zeichnung Seitenstange: 3 Maße geändert"]
    v2, _ = a.nach_lauf(wer="kevin", lauf=2)
    assert [e["text"] for e in a.dokumente_vergleich(v1, v2)] == ["Zeichnung Seitenstange: 3 Maße geändert"]
    assert a.dokumente_vergleich(v2, None) == []
