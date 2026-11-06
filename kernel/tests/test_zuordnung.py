"""V2-2: jede der 95 bisherigen Funktionen bleibt erreichbar (Zuordnung alt → neu) und die Tabelle im Skill stimmt
mit dem Code überein."""

from __future__ import annotations

from pathlib import Path

import anyio
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.mcp_tools import TOOL_NAMES
from kevcad_kernel.mcp_tools.fach import FAECHER, direkt
from kevcad_kernel.mcp_tools.zuordnung import (
    KERN,
    KERN_TEXT,
    alte_namen,
    alter_aufruf,
    tabelle,
    uebersetzen,
    werkzeuge_md,
)

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


# Griffe, die nach V2-1 dazukamen (eigene Aktion eines Fachwerkzeugs, kein Name von früher)
NEU = {"aufbau_video"}


def test_jede_alte_funktion_ist_zugeordnet():
    assert len(ALT) == 95 and set(alte_namen()) == ALT | NEU
    assert set(KERN_TEXT) == set(KERN)
    aktionen = {f.name: {a.name for a in f.aktionen} for f in FAECHER if not direkt(f)}
    for alt in sorted(ALT | NEU):
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
    # 10.000 statt 8.000 seit dem Pipeline-Experiment (PLAN-PIPELINE.md, 06.11.2026): SKILL.md trägt Ablauf, Konstruktions-
    # und Druckregeln selbst, damit 3d-druck.md, modell.md und konstruktion.md (zusammen rund 70.000 Zeichen) für eine
    # gewöhnliche Aufgabe nicht mehr gelesen werden; gemessen 0,76-fache Eingabe bei gleicher Zeit und Qualität.
    assert len(koerper) <= 10000, len(koerper)
    for datei in sorted(p.name for p in SKILL.glob("*.md") if p.name != "SKILL.md"):
        assert f"]({datei})" in skill, f"{datei} fehlt im Verzeichnis von SKILL.md"
    assert "select:mcp__kevcad__status," in skill


def test_alter_aufruf_nennt_den_neuen_aufruf():
    antwort = alter_aufruf("stock_search", {"query": "Alu Ø12"})
    assert "katalog(suche=\"Alu Ø12\")" in antwort and "Nichts wurde ausgeführt" in antwort
    assert "versionen(aktion=\"variante_wechseln\"" in alter_aufruf("variante", {"aktion": "wechseln", "id": "v2"})


def test_alter_aufruf_nur_fuer_alte_namen():
    assert alter_aufruf("gibtsnicht", {}) is None
    for name in TOOL_NAMES:  # Namen, die es weiter gibt, gehen normal durch
        assert alter_aufruf(name, {}) is None


def test_alter_aufruf_fuer_jeden_alten_namen():
    weg = [n for n in alte_namen() if n not in TOOL_NAMES]
    assert len(weg) > 60
    for name in weg:
        antwort = alter_aufruf(name, {"refs": ["A"], "query": "x"})
        neu, _ = uebersetzen(name, {})
        assert f"{neu}(" in antwort, name


def test_alter_aufruf_kuerzt_lange_argumente_und_uebersteht_falsche():
    antwort = alter_aufruf("model_write", {"code": "x = 1\n" * 1000})
    assert len(antwort) < 500 and "modell(code=" in antwort
    assert "view(" in alter_aufruf("highlight", {"refs": 5})  # falscher Typ: Kurzform statt Absturz


def test_server_nennt_den_neuen_aufruf():
    """Eine alte Brücke reicht den Namen an den neuen Kernel durch: Auch der Server antwortet mit dem neuen Aufruf."""
    server, _ = start_server()
    try:
        async def go(c):
            return await c.call_tool("stock_search", {"query": "Alu"}), await c.call_tool("gibtsnicht", {})

        alt, fremd = anyio.run(lambda: with_client(server.url, go, alt=False))
    finally:
        server.stop_thread()
    assert alt.is_error and 'katalog(suche="Alu")' in texts(alt)[0]
    assert fremd.is_error and "Unknown tool" in texts(fremd)[0]
