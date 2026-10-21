"""Bauplan (Phase 6, Strang P6-B): Schritt-für-Schritt-Bauanleitung aus dem Modell, mit Simulation je Schritt.

Vertrag: DOKUMENTE.md, Abschnitt „Bauplan“. Ablage ``<projekt>/dokumente/bauplan.json``.

Module:

| Modul | Inhalt |
|---|---|
| ``eingang`` | Daten des letzten Laufs: Teile mit Rolle (gefertigt, Druck, Verbindungsmittel, Zukauf …), Verbindungen |
| ``raster`` | Netze in einer Blickrichtung rastern (Tiefe je Bildpunkt): Grundlage für Wege, Sicht und Strichbild |
| ``wege`` | Einführwege (frei oder versperrt), Werkzeugzugang, Standsicherheit |
| ``montagefolge`` | eigene Montagefolge (Montage durch Demontage), bis die Einbaubarkeit der Prüfung auf main ist |
| ``merkmale`` | Bohrungen erkennen (Platzhalter, bis die Merkmalerkennung von P6-Z steht) |
| ``geruest`` | die fünf Abschnitte Material, Zuschnitt, Bearbeiten, Drucken, Montage |
| ``bild`` / ``projektion`` | Kamera, Explosion, Pfeile je Schritt; Strichbild (Platzhalter für die Projektion von P6-Z) |
| ``simulation`` | Prüfung je Schritt: Einführweg, Werkzeugzugang, Standsicherheit, Reihenfolge |
| ``datei`` | Laden, Speichern, Bestehendes erhalten (fest, Texte von Agent und Kevin), Bearbeiten |
| ``dienst`` | Teil der Kernel-Laufzeit: MCP-Methoden, Nachrichten BAUPLAN*, DOCS |
"""
