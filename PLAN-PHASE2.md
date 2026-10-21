# Kev CAD · Phase 2: Lagerteile, Materialien, Stückliste

Stand: 21.10.2026. Baut auf dem MVP auf ([PLAN-MVP.md](PLAN-MVP.md)). Entwickelt auf dem Zweig `phase2`, erst nach der
Abnahme auf `main` (dann installiert das automatische Update die neue Version in den Tools-Stapel).

## Ziel

Kevin legt Materialien und Lagerteile an (Rohre, Profile, Platten, Holz, Schrauben) und lässt Claude sie verbauen.
Kev CAD zeigt dazu eine Stückliste mit Zuschnitt, Gewicht und Kosten.

**Fertig, wenn dieser Ablauf ohne Handarbeit geht:**

1. Kevin: „Bau mir ein Gestell 800 × 600 × 900 aus Vierkantrohr 40 × 40 × 3, oben eine 18-mm-Multiplexplatte,
   mit M8-Schrauben verschraubt.“
2. Claude sucht die Lagerteile im Katalog (`stock_search`), schreibt `model.py` mit `lager.teil(...).verbauen(...)`,
   rechnet; das Gestell baut sich Teil für Teil auf, jedes Teil in der Farbe seines Materials.
3. Die Stückliste in der App zeigt: 4 × Rohr 40×40×3 à 882 mm, 2 × à 800 mm …, Platte 800 × 600 × 18, 8 × ISO 4762
   M8×60, je Zeile Material, Gewicht und Preis, darunter den Zuschnitt (2 Stangen à 6 m, Verschnitt 12 %) und die
   Summen (Gewicht, Materialkosten, als Richtpreis gekennzeichnet).
4. Kevin: „Leg mir Edelstahlrohr 33,7 × 2 an, 14,50 € pro Meter.“ Claude legt es per `stock_define` im eigenen
   Katalog an; es erscheint im Lagerkatalog-Fenster und lässt sich dort auch von Hand bearbeiten.
5. Stückliste als CSV exportieren (öffnet in Numbers/Excel).

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| P1 | **Katalog als JSON-Dateien** in drei Ebenen: mitgeliefert (`kernel/src/kevcad/katalog/`), Kevins eigener (`~/Library/Application Support/de.upvis.kevcad/katalog/`), je Projekt (`<projekt>/katalog.json`). Spätere Ebene überschreibt frühere bei gleicher `id` | Lesbar, versionierbar, von Claude und Kevin gleichermaßen pflegbar. Eigene Preise überleben Updates |
| P2 | **Querschnitte werden berechnet**, nicht als CAD-Dateien gespeichert: je Art eine Generatorfunktion aus den Maßen | Ein Generator deckt eine ganze Normreihe ab; neue Größen sind eine Zeile JSON |
| P3 | **`lager.teil(...).verbauen(laenge, name, gehrung)`** liefert ein build123d-Teil entlang +Z ab z = 0 (Querschnitt mittig auf der Achse) und meldet eine Stücklistenzeile an. Verknüpfung mit dem gezeigten Teil über den Namen (gleicher Name in `show`), sonst über die Form (`IsPartner`) | Lagerteil-Angaben überleben Verschieben/Drehen; Bohrungen danach ändern Gewicht, aber nicht die Zuschnittlänge |
| P4 | **Länge = Zuschnittmaß an der längsten Kante**, Gehrung als Winkel der Schnittfläche an Anfang und Ende (0° = gerade) | So steht es auf Sägelisten |
| P5 | **Stückliste im Kernel** nach jedem Lauf: gleiche Lagerteile mit gleicher Länge und Gehrung werden zusammengefasst; Zuschnitt je Stangenlänge mit First-Fit-Decreasing und 3 mm Sägeschnitt | Einfach, gut genug, nachvollziehbar |
| P6 | **Teile ohne Lagerteil** (frei modelliert mit `material=`) erscheinen als „Eigenteil" mit Masse aus Volumen × Dichte und Preis über €/kg des Materials | Auch frei Gebautes landet auf der Liste |
| P7 | **Preise sind Richtwerte** mit Quelle und Stand; die Summen sagen das dazu | Keine erfundene Genauigkeit |

## Arbeitspakete (parallel)

| Strang | Inhalt | Dateien |
|---|---|---|
| **K1 Katalogdaten** | Materialien und Normreihen als JSON nach [KATALOG.md](KATALOG.md): Rohre (DIN EN 10220, ISO 1127 Edelstahl), Quadrat- und Rechteckrohre (EN 10219), Flach-, Rund-, Vierkantstahl, Winkel (EN 10056), Alu-Nutprofile (Raster 20/30/40/45, Nut 5/6/8/10), Holz (KVH, Latten, Bretter), Platten und Bleche, Schrauben/Muttern/Scheiben (Verweis auf bd_warehouse) | `kernel/src/kevcad/katalog/`, `kernel/tests/test_katalog_daten.py` |
| **K2 Kernel** | `kevcad.lager` (laden, suchen, verbauen), Querschnitt-Generatoren, Stückliste und Zuschnitt, Protokoll (BOM, CATALOG, stock an PART_UPSERT), Fassade und MCP-Werkzeuge, Skill | `kernel/src/kevcad/lager*.py`, `kernel/src/kevcad_kernel/{bom,catalog,profiles}.py`, Laufzeit, MCP, `skill/` |
| **A1 App** | Stückliste (Tabelle, Zuschnitt, Summen, Klick hebt Teile hervor, CSV-Export), Lagerkatalog-Fenster (suchen, ansehen, eigene Einträge anlegen/ändern/löschen), Lagerteil im Inspektor, Hinweis „neue Version installiert – neu starten" | `app/` |

Verträge: [PROTOCOL.md](PROTOCOL.md) (Abschnitt „Phase 2"), [KATALOG.md](KATALOG.md), `service.py` (Phase-2-Methoden),
`AppModel.swift` (Phase-2-Typen und -Aktionen).

## Abnahme

- Ablauf oben über MCP gegen die Testvariante, Bilder und Stückliste geprüft.
- Kernel-Tests: Querschnittsflächen gegen Tabellenwerte (kg/m auf ±2 %), Gehrungslängen, Zusammenfassen, Zuschnitt.
- App-Tests: Dekodieren von BOM/CATALOG, Tabelle im Demomodus, Fensterbilder.
