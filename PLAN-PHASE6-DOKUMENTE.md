# Kev CAD · Phase 6: Zeichnungen, Bauplan, Berichte als PDF

Stand: 22.10.2026 (Kevins Auftrag vom selben Abend: „einfach mal sinnvoll implementieren, so wie du es als sinnvoll
erachtest“). Vertrag: [DOKUMENTE.md](DOKUMENTE.md). Recherche: RECHERCHE-PHASE6.md (läuft).

## Ziel

Drei Dokumentarten, alle in der App ansehen, bearbeiten, als PDF exportieren und drucken, alle auch über MCP:

1. **Technische Zeichnungen** von jedem Einzelteil, jeder Baugruppe und vom Zusammenbau: normgerechte Ansichten
   (Projektionsmethode 1), Schnitte und Einzelheiten, verdeckte Kanten und Mittellinien, Schriftfeld, Maßstab,
   Allgemeintoleranz, Werkstoff, Masse. Die Maße wählt Kev CAD selbst nach Funktion (Hüllmaße, Bohrungen mit Ø und
   Lage ab Bezugskante, Lochbilder, Fasen, Radien, Gewinde, Stangenlänge und Gehrung); Kevin und der Agent können Maße
   verschieben, löschen und hinzufügen, eigene Notizen setzen. Bemaßungen bleiben an der Geometrie hängen, wenn sich
   das Modell ändert.
2. **Bauplan** als Schritt-für-Schritt-Anleitung: Material besorgen, Zuschneiden (je Stange mit Gehrung),
   Bearbeiten (alle Bohrungen mit Ø, Lage, Senkung, Gewinde), Drucken (Druckteile mit Ausrichtung und Einstellungen),
   Montieren (Reihenfolge, Teile, Verbindungsmittel, Werkzeug, Hinweise), jeder Schritt mit Bild (Strichzeichnung,
   neue Teile hervorgehoben, Explosion und Einführpfeile). In der App Schritt für Schritt durchspielen; die Simulation
   prüft jeden Schritt (Einführweg frei, Werkzeug kommt hin, Teilbaugruppe steht) und zeigt Probleme am Schritt.
3. **Berichte** (Stückliste, Teileliste, Einkaufsliste, Zuschnitt, Druckteile, Gewicht und Kosten, Prüfstand,
   Bedingungen, Bestand) als übersichtliche PDF-Tabellen mit Vorschaubildern; in einem Export-Dialog zusammenstellbar
   („Bausteine“), als Vorlage speicherbar, zusammen mit Zeichnungen und Bauplan in einem Dokument.

**Fertig, wenn (am Kugelschieber Variante B):**

1. „Zeichnungen erstellen“ legt für jedes gefertigte Teil (Rohre, Platten, Druckteile) ein Blatt und für den
   Zusammenbau ein Blatt mit Positionsnummern und Stückliste an; die Rohre zeigen Länge, Bohrungen und deren Lage ab
   dem Rohrende, die Druckteile Hüllmaße, Bohrungen, Einsatztaschen, Fasen.
2. Kevin verschiebt in der App ein Maß, löscht eins, setzt ein neues zwischen zwei Kanten; nach einem neuen Lauf
   mit geänderter Rohrlänge stimmen alle Maße und seine Änderungen sind noch da.
3. Der Bauplan hat Abschnitte Material, Zuschnitt, Bohren, Drucken, Montage; jeder Montageschritt zeigt die neuen
   Teile hervorgehoben mit Pfeilen; Durchspielen in der App zeigt Schritt für Schritt den Aufbau, ein absichtlich
   blockierter Schritt wird als Problem gemeldet.
4. Der Export-Dialog erzeugt ein PDF mit Deckblatt, Stückliste mit Bildern, Zuschnitt, Einkaufsliste, allen Zeichnungen
   und dem Bauplan; „Drucken“ öffnet den macOS-Druckdialog.

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| D1 | **Dokumente sind Daten im Projekt** (`<projekt>/dokumente/`, JSON), versioniert mit dem Projekt; der Kernel erzeugt und aktualisiert sie, die App zeigt und bearbeitet sie über Nachrichten, beide arbeiten auf demselben Modell | Bearbeitbar, nachvollziehbar, über MCP steuerbar |
| D2 | **Geometrie im Kernel, Darstellung in der App:** der Kernel projiziert (OCCT Hidden Line Removal), erkennt Merkmale, bemaßt und platziert; er schickt fertige Vektoren je Linienart und semantische Maße in Blattkoordinaten (mm); die App zeichnet mit CoreGraphics, identisch auf Bildschirm, PDF und Drucker | Ein Rechenweg, eine Darstellung, echte Vektoren |
| D3 | **Stabile Bezüge:** Maße hängen an Merkmalen mit Signatur (Art, Lage, Richtung, Radius) statt an Kanten-Nummern; nach jedem Lauf ordnet der Kernel neu zu; was nicht mehr passt, wird als „verwaist“ markiert statt still falsch | Maße überleben Konstruktionsänderungen |
| D4 | **Automatische Bemaßung nach ISO 129-1:** jedes Maß einmal, funktionsbezogen, Bezug von einer Kante bzw. Achse, Lochbilder zusammengefasst, Ø und R normgerecht, Gewinde nach ISO 6410; minimale Ansichtenzahl, Schnitt nur bei Innenmerkmalen; Platzierung ohne Überlappung; Kevins und Agent-Maße (`fest`) werden nie automatisch verschoben oder gelöscht | Lesbare Werkstattzeichnungen statt Maßwust |
| D5 | **Blatt nach ISO 5457/7200:** A4/A3, Rahmen, Schriftfeld (Benennung, Zeichnungsnummer, Werkstoff, Masse, Maßstab nach ISO 5455, Allgemeintoleranz ISO 2768-m, Projekt, Version/Meilenstein, Datum, „gezeichnet: Kev CAD“) | Druckbar und vollständig |
| D6 | **Bauplan aus den Daten, Text vom Agenten:** Kev CAD baut das Gerüst (Abschnitte, Schritte, Teile, Bohrbilder, Verbindungsmittel und Werkzeuge aus `verbinde`, Reihenfolge aus der Einbaubarkeit), der Agent formuliert Texte und Hinweise per MCP, Kevin ändert in der App; feste Schritte bleiben bei neuem Lauf erhalten | Realistisch, nicht nur generisch |
| D7 | **Durchspielen = Simulation:** je Schritt nur die bis dahin montierten Teile, neue Teile fahren entlang ihrer Einführrichtung ein (Animations-Engine), dabei Prüfung Einführweg, Werkzeugzugang, Standsicherheit der Teilbaugruppe | Fehler im Ablauf fallen vor dem Bauen auf |
| D8 | **Bilder:** Strichzeichnungen für Bauplan und Zusammenbau aus derselben Projektion wie die Zeichnungen (vektor, IKEA-Stil, neue Teile farbig); Vorschaubilder der Teile für Berichte über den vorhandenen Offscreen-Renderer | Scharf im PDF, einheitlicher Stil |
| D9 | **Export-Dialog mit Bausteinen:** Deckblatt, Teileliste mit Bildern, Stückliste, Zuschnitt, Einkaufsliste, Druckteile, Gewicht/Kosten, Prüfstand, Bedingungen, Bestand, Zeichnungen (Auswahl), Bauplan; Vorlagen speichern; PDF oder Drucken; Spalten der Tabellen wählbar | Kevin stellt zusammen, was er braucht |
| D10 | **Eigener Bereich „Dokumente“** im Projektfenster (Seitenleiste mit Blättern, Bauplan, Berichten; Werkzeugleiste zum Bearbeiten); Wechsel zwischen 3D und Blatt mit einem Klick | Integriert statt angeflanscht |

## Stränge

| Strang | Inhalt | Start |
|---|---|---|
| **P6-Z** Kernel Zeichnungen | Projektion (HLR schnell und exakt), Ansichten, Schnitte, Einzelheiten, Merkmalerkennung, automatische Bemaßung, Platzierung, Signaturen und Neuzuordnung, Schriftfeld, Nachrichten, MCP | sofort |
| **P6-B** Kernel Bauplan | Gerüst aus BOM, Zuschnitt, Merkmalen, Druckteilen, `verbinde`, Einbaubarkeit; Bohrbilder; Explosion und Pfeile je Schritt; Prüfung je Schritt; Strichbilder über P6-Z; Nachrichten, MCP | sofort |
| **P6-A1** App Zeichnungen und PDF | Bereich „Dokumente“, Blatt-Renderer, Bearbeiten (Maße, Ansichten, Notizen), PDF-Engine und Druck | sobald die laufenden App-Stränge (Bestand, Versionen) fertig sind |
| **P6-A2** App Bauplan und Berichte | Bauplan-Ansicht mit Durchspielen, Export-Dialog mit Bausteinen und Vorlagen, Berichtstabellen | wie P6-A1 |
