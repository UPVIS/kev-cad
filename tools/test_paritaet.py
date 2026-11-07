"""Tests der Paritätsprüfung (tools/paritaet.py) an einem kleinen Baum im Temp-Ordner.

    python3 -m unittest tools/test_paritaet.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HIER = Path(__file__).resolve().parent

KARTE = {
    "mac_huelle": ["app/Sources/KevCAD/Mac/**/*.swift"],
    "ipad_huelle": ["app/Sources/KevCADPad/**/*.swift"],
    "paare": {"app/Sources/KevCAD/Mac/KevCADApp.swift": "app/Sources/KevCADPad/KevCADPadApp.swift"},
    "nur_mac": {"app/Sources/KevCAD/Mac/Commands.swift": "Menüleiste"},
    "nur_ipad": {},
    "gemeinsam": ["app/Sources/KevCAD/**/*.swift"],
    "gemeinsam_ohne": ["app/Sources/KevCAD/Mac/"],
    "begruendung_muster": "nur am Mac|iPad:",
    "marken_quellen": ["app/Sources/**/*.swift"],
    "befehlskatalog": {"datei": "app/Tasten.swift", "eintrag": "Belegung\\(befehl:\\s*\\.(\\w+)",
                       "ipad_felder": ["ipad:"], "nur_mac": {}},
}


class ParitaetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wurzel = Path(self.tmp.name)
        self.schreiben("paritaet.json", json.dumps(KARTE))
        self.schreiben("app/Sources/KevCAD/Mac/KevCADApp.swift", "// Mac\n")
        self.schreiben("app/Sources/KevCAD/Mac/Commands.swift", "// Menüs\n")
        self.schreiben("app/Sources/KevCADPad/KevCADPadApp.swift", "// iPad\n")
        self.schreiben("app/Sources/KevCAD/Ansicht.swift", "import SwiftUI\n#if os(macOS)\nimport AppKit\n#endif\n")
        self.schreiben("PLAN-IPAD.md", "| Paket | Inhalt | hängt ab | Stand |\n|---|---|---|---|\n"
                                       "| I-2b Eingang | x | – | fertig: alles |\n| I-8 Volle Parität | y | – | offen |\n")
        os.environ["KEVCAD_PARITAET_WURZEL"] = str(self.wurzel)
        spec = importlib.util.spec_from_file_location("paritaet_test_modul", HIER / "paritaet.py")
        self.p = importlib.util.module_from_spec(spec)
        # dataclasses sucht das Modul unter seinem Namen (Python 3.12), also vor dem Ausführen eintragen
        sys.modules[spec.name] = self.p
        spec.loader.exec_module(self.p)

    def tearDown(self):
        sys.modules.pop("paritaet_test_modul", None)
        os.environ.pop("KEVCAD_PARITAET_WURZEL", None)
        self.tmp.cleanup()

    def schreiben(self, pfad: str, text: str):
        p = self.wurzel / pfad
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def lauf(self, *args) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            if args[:1] == ("abgleichen",):
                rc = self.p.abgleichen([a for a in args[1:] if a != "--alle"], "--alle" in args)
            else:
                rc = self.p.bericht(kurz="--kurz" in args, alle="--alle" in args)
        return rc, out.getvalue()

    def test_nach_abgleich_alles_gut(self):
        self.lauf("abgleichen", "--alle")
        rc, text = self.lauf("--kurz")
        self.assertEqual(rc, 0, text)
        self.assertIn("abgeglichen", text)

    def test_nur_mac_geaendert_wird_gemeldet(self):
        self.lauf("abgleichen", "--alle")
        self.schreiben("app/Sources/KevCAD/Mac/KevCADApp.swift", "// Mac neu\n")
        rc, text = self.lauf()
        self.assertEqual(rc, 1)
        self.assertIn("Nur eine Seite geändert", text)
        self.assertIn("KevCADPadApp.swift", text)
        # Nachgezogen und abgeglichen: wieder gut
        self.schreiben("app/Sources/KevCADPad/KevCADPadApp.swift", "// iPad neu\n")
        self.lauf("abgleichen", "app/Sources/KevCADPad/KevCADPadApp.swift")
        self.assertEqual(self.lauf("--kurz")[0], 0)

    def test_neue_huellen_datei_ohne_zuordnung(self):
        self.lauf("abgleichen", "--alle")
        self.schreiben("app/Sources/KevCAD/Mac/Neu.swift", "// neu\n")
        rc, text = self.lauf()
        self.assertEqual(rc, 1)
        self.assertIn("ohne Zuordnung", text)

    def test_ausnahme_geaendert(self):
        self.lauf("abgleichen", "--alle")
        self.schreiben("app/Sources/KevCAD/Mac/Commands.swift", "// Menüs mit neuem Befehl\n")
        rc, text = self.lauf()
        self.assertEqual(rc, 1)
        self.assertIn("Ausnahme geändert", text)

    def test_mac_stelle_ohne_grund_und_mit_grund(self):
        self.lauf("abgleichen", "--alle")
        self.schreiben("app/Sources/KevCAD/Ansicht.swift",
                       "#if os(macOS)\nfunc nurHier() {}\n#endif\n"
                       "// Druckdialog gibt es nur am Mac\n#if os(macOS)\nfunc drucken() {}\n#endif\n"
                       "#if os(macOS)\nfunc a() {}\n#else\nfunc a() {}\n#endif\n"
                       "#if os(macOS)  // iPad: folgt in I-8\nfunc b() {}\n#endif\n")
        rc, text = self.lauf()
        self.assertEqual(rc, 1)
        self.assertIn("Ansicht.swift:1", text)
        self.assertNotIn("Ansicht.swift:5", text)  # begründet
        self.assertIn("Marken „iPad: folgt in I-x“: 1 (I-8: 1)", text)
        self.lauf("abgleichen", "app/Sources/KevCAD/Ansicht.swift")
        self.assertEqual(self.lauf("--kurz")[0], 0)

    def test_veraltete_marke(self):
        self.lauf("abgleichen", "--alle")
        self.schreiben("app/Sources/KevCAD/Netz.swift", "// iPad: folgt in I-2b\n")
        rc, text = self.lauf()
        self.assertEqual(rc, 1)
        self.assertIn("veraltet", text)

    def test_befehlskatalog_erst_aktiv_mit_ipad_feld(self):
        katalog = ("static let alle = [\n    Belegung(befehl: .vorne, tasten: [.z(\"1\")]),\n"
                   "    Belegung(befehl: .oben, tasten: [.z(\"7\")]),\n]\nlet gesten = [ipad: 1]\n")
        self.schreiben("app/Tasten.swift", katalog)
        self.lauf("abgleichen", "--alle")
        self.assertEqual(self.lauf("--kurz")[0], 0)  # das ipad: hinter der Liste zählt nicht
        self.schreiben("app/Tasten.swift", katalog.replace(".z(\"1\")]", ".z(\"1\")], ipad: .tippen"))
        rc, text = self.lauf()
        self.assertEqual(rc, 1)
        self.assertIn("Befehle ohne Auslöser am iPad (1)", text)
        self.assertIn("  oben", text)

    def test_befehlskatalog_mit_weiteren_ausloesern(self):
        # I-4: Ein Feld des Werkzeugkranzes zählt als Auslöser am iPad
        karte = json.loads(json.dumps(KARTE))
        karte["befehlskatalog"]["weitere"] = ["\\.befehl\\(\\.(\\w+)"]
        self.schreiben("paritaet.json", json.dumps(karte))
        katalog = ("static let alle = [\n    Belegung(befehl: .vorne, tasten: [.z(\"1\")], ipad: [.tippen]),\n"
                   "    Belegung(befehl: .oben, tasten: [.z(\"7\")]),\n]\nlet kranz = [.befehl(.oben, \"x\")]\n")
        self.schreiben("app/Tasten.swift", katalog)
        self.lauf("abgleichen", "--alle")
        self.assertEqual(self.lauf("--kurz")[0], 0)
        self.schreiben("app/Tasten.swift", katalog.replace(".befehl(.oben", ".befehl(.unten"))
        rc, text = self.lauf()
        self.assertEqual(rc, 1)
        self.assertIn("  oben", text)


if __name__ == "__main__":
    unittest.main()
