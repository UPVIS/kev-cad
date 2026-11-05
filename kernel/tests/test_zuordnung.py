"""V2-2: jede der 95 bisherigen Funktionen bleibt erreichbar (Zuordnung alt → neu) und die Tabelle im Skill stimmt
mit dem Code überein."""

from __future__ import annotations

from pathlib import Path

from kevcad_kernel.mcp_tools import TOOL_NAMES
from kevcad_kernel.mcp_tools.fach import FAECHER, direkt
from kevcad_kernel.mcp_tools.zuordnung import KERN, KERN_TEXT, alte_namen, tabelle, uebersetzen, werkzeuge_md

SKILL = Path(__file__).resolve().parents[2] / "skill" / "kev-cad"

# Werkzeuge bis V2-1 (tests/mcp_testutil.py, EXPECTED_TOOLS auf 6b2030e)
ALT = {
    "status", "project_open", "project_new", "run", "model_read", "model_write", "execute", "parts", "view", "focus",
    "visibility", "highlight", "section", "screenshot", "selection", "measure", "annotate", "clear_annotations",
    "export", "stock_search", "stock_get", "stock_define", "material_list", "material_define", "catalog_delete", "bom",
    "bestand_liste", "bestand_eintragen", "einkaufsliste", "gebaut_buchen", "gedruckt_buchen", "buchung_rueckgaengig",
    "zukauf_anlegen", "zukauf_html", "cad_suchen", "cad_uebernehmen", "zukauf_liste", "pruefen", "montage_reihenfolge",
    "ansichten", "bedingungen", "animation_liste", "animation_abspielen", "animation_springen", "animation_video",
    "kollision_pruefen", "kamera_liste", "kamera_info", "kamera_ansicht", "kamera_bild", "kamera_katalog",
    "kamera_vorschlag_aus_ansicht", "bauplan", "bauplan_bearbeiten", "bauplan_pruefen", "druckpruefung",
    "druckvorschau", "druck_einstellen", "druck_export", "filament_liste", "filament_define", "zeichnungen",
    "zeichnung_erstellen", "zeichnung_bearbeiten", "zeichnung_bild", "versionen", "version_wiederherstellen",
    "versionen_vergleichen", "meilenstein", "variante", "dokument_export", "drucker_status", "drucken",
    "freigabe_anfragen", "referenzen", "referenz_video", "referenz_fotos", "referenz_vermessen", "referenz_fotoansicht",
    "referenz_abweichung", "referenz_massstab", "statik", "szenario_rechnen", "dynamik", "dynamik_grenze", "render",
    "festigkeit", "scans", "scan_importieren", "topologie_optimieren", "topologie_ergebnis", "topologie_uebernehmen",
    "simulation_liste", "simulation_aendern", "simulation_rechnen",
}


def test_jede_alte_funktion_ist_zugeordnet():
    assert len(ALT) == 95 and set(alte_namen()) == ALT
    assert set(KERN_TEXT) == set(KERN)
    aktionen = {f.name: {a.name for a in f.aktionen} for f in FAECHER if not direkt(f)}
    for alt in sorted(ALT):
        neu, args = uebersetzen(alt, {})
        assert neu in TOOL_NAMES, (alt, neu)
        if neu in aktionen:
            aktion = args.get("aktion")
            assert aktion in aktionen[neu], (alt, neu, aktion)


def test_uebersetzung_der_argumente():
    assert uebersetzen("project_new", {"path": "X", "template": "empty"}) == (
        "projekt", {"neu": True, "pfad": "X", "vorlage": "empty"})
    assert uebersetzen("visibility", {"mode": "show_all"}) == ("view", {"sichtbarkeit": "alle"})
    assert uebersetzen("highlight", {"refs": [], "clear": True}) == ("view", {"entfernen": "hervorhebungen"})
    assert uebersetzen("section", {"enabled": True, "normal": [0, 1, 0], "offset": 5}) == (
        "view", {"schnitt_mm": 5, "schnitt_normale": [0, 1, 0]})
    assert uebersetzen("screenshot", {"view": "front"}) == ("ansichten", {"views": ["front"]})
    assert uebersetzen("bedingungen", {"part": "A", "alle": True}) == (
        "pruefen", {"thema": "bedingungen", "teil": "A", "alle": True})
    assert uebersetzen("druck_export", {"filament": {"petg": "x"}}) == (
        "druck", {"aktion": "export", "filament": {"petg": "x"}})
    assert uebersetzen("variante", {"aktion": "wechseln", "name": "Hauptstand"}) == (
        "versionen", {"aktion": "variante_wechseln", "name": "Hauptstand"})
    assert uebersetzen("render", {"szene": "studio"}) == ("render", {"szene": "studio"})
    assert uebersetzen("projekt", {"pfad": "X"}) == ("projekt", {"pfad": "X"})  # neue Namen gehen durch


def test_werkzeuge_md_im_skill_stimmt():
    """skill/kev-cad/werkzeuge.md entsteht aus den Werkzeugen (kernel/tools/skill_werkzeuge.py) und ist aktuell."""
    werkzeuge = (SKILL / "werkzeuge.md").read_text(encoding="utf-8")
    assert tabelle() in werkzeuge
    assert werkzeuge == werkzeuge_md(), "skill/kev-cad/werkzeuge.md veraltet: kernel/tools/skill_werkzeuge.py ausführen"


def test_skill_schlank_mit_verzeichnis():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    koerper = skill.split("\n---\n", 1)[1]
    assert len(koerper) <= 8000, len(koerper)
    for datei in sorted(p.name for p in SKILL.glob("*.md") if p.name != "SKILL.md"):
        assert f"]({datei})" in skill, f"{datei} fehlt im Verzeichnis von SKILL.md"
    assert "select:mcp__kevcad__status," in skill
