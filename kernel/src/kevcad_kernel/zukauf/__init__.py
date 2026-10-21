"""Zukaufteile (Phase 3, PLAN-PHASE3-ZUKAUF.md): fertig gekaufte Teile per Shop-Link, Herstellernummer oder EAN.

| Modul | Inhalt | schwer? |
|---|---|---|
| ``eintrag`` | Katalogeinträge ``art: "zukaufteil"`` prüfen und aus Feldern zusammensetzen, Maße/Preise aus Text | nein |
| ``normteile`` | „ISO 4762 M6×20“ erkennen und auf Katalog bzw. bd_warehouse umleiten | nein |
| ``shopdaten`` | mitgeliefertes HTML auswerten (extruct: JSON-LD, Microdata, Open Graph) | lxml |
| ``traceparts`` | TraceParts-API (Schlüssel aus secrets.env) und Deep-Links zu Herstellerportalen | nein |
| ``downloads`` | neueste CAD-Datei im Download-Ordner, ZIP sicher entpacken | nein |
| ``cad`` | STEP laden, Einheiten und Achsen prüfen, BREP-Zwischenspeicher, Ersatzkörper, Skript | build123d |
| ``dienst`` | Laufzeit-Teil: MCP-Werkzeuge und App-Nachrichten (ZUKAUF_NEU, DOWNLOAD_SEEN, ZUKAUF_CAD) | nein |

Kev CAD lädt Shop-Seiten nie selbst (Z1): Daten kommen von Claude oder aus Kevins Eingabe in der App.
"""
