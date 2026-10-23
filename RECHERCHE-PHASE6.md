# Kev CAD · Recherche Phase 6: Zeichnungen, Bauplan, Berichte

Stand: 22.10.2026. Gehört zu [PLAN-PHASE6-DOKUMENTE.md](PLAN-PHASE6-DOKUMENTE.md) und dem Vertrag DOKUMENTE.md (beide auf
dem Zweig `phase6`). Die Recherche bestätigt die Richtung des Plans; Abschnitt 7 nennt, was ergänzt oder geändert
werden sollte.

**Belegart** an jeder Aussage:

- **[N]** Normtext selbst gelesen. Meist über die wortgleichen indischen Übernahmen (BIS) auf law.resource.org, die oft
  der Vorgängerausgabe entsprechen. Ob die heutige Ausgabe gleich lautet, ist offen, weil die Volltexte kostenpflichtig
  sind.
- **[S]** nur aus Sekundärquellen: Hochschulskript, Wikibooks, Hersteller, Forum.
- **[G]** selbst gemessen oder getestet. Apple M2 Pro, build123d 0.13 auf OCCT 8.0.1 (`cadquery-ocp-novtk 8.0.1.1`),
  macOS 26.6, Swift 6.4.
- **[offen]** nicht geprüft.

## Kurzfassung

1. **Normen:** Fast alles, was eine Software braucht, sind feste Zahlen: Linienbreiten, Strichlängen, Schrifthöhen,
   Blattränder, Schriftfeld, Maßstabsreihe und Toleranztabelle. Lücken gibt es nur bei Abstand und Staffelung der
   Maßlinien (10/7 mm ist Lehrbuchpraxis, keine ISO-Zahl) und beim Abstand der Schraffurlinien.
2. **Automatische Bemaßung:** Kein Open-Source-Werkzeug bemaßt sinnvoll aus B-Rep. Fusion und SolidWorks haben eine
   Automatik mit festen Strategien (Bezug, Kette, Koordinaten). Brauchbare Rezepte stehen in der Literatur
   (Kakoulis 2023, Raffaeli 2016 „Drafting Schemes“) und in text-to-cad (MIT). Kev CAD hat einen Vorteil, den keines
   dieser Programme hat: Es weiß, was ein Teil ist (Rohr, Platte, Druckteil, Normteil) und wie es verbunden ist.
3. **Projektion:** Die exakte Verdeckungsrechnung von OCCT (`HLRBRep_Algo`) hat bei genau den achsparallelen Ansichten,
   die Zeichnungen brauchen, Ausreißer über 80 s. Das ist nicht an der Flächenzahl erkennbar [G]. Ein Rost mit
   36 Flächen braucht 81 s, der Netzweg (`HLRBRep_PolyAlgo`) 0,02 s. Auch der Projektionscode auf `phase6-b` läuft in
   diesen Fall. Daher: Verdeckung immer zuerst auf dem Netz, exakt nur mit Zeitbudget.
4. **Bauanleitungen:** Das Verfahren von Agrawala et al. 2003 passt fast eins zu eins auf Kev CAD. Es ist eine gierige
   Demontage über Hauptteile, Verbinder sind Sekundärteile, und die Kostenfunktion ist die Sichtbarkeit der neuen
   Teile. Die Fügerichtungen liefern die vorhandenen Bedingungen (`in_bohrung`, `auf`, `verbinde`), also robuster als
   jede Geometrie-Heuristik.
5. **PDF und Druck:** Eine einzige CoreGraphics-Zeichenfunktion für Bildschirm, PDF und Druck ist der richtige Weg [G]:
   - Linienbreiten, Strichmuster und echter Text mit eingebetteter Teilschrift kommen exakt an.
   - Gedruckt wird nur mit `.pageScaleNone`, sonst skaliert macOS A4 auf 97,18 %.
   - Ein Druckauftrag je Blattformat.
   - Schrift: osifont (ISO 3098, LGPL-3 mit Font-Ausnahme).

## 1. Normen

### 1.1 Übersicht

| Norm | Gültige Ausgabe | Was die Software daraus umsetzt |
|---|---|---|
| ISO 128-1/-2/-3 | 128-1:2020, **128-2:2022, 128-3:2022** ([SIS 128-2](https://www.sis.se/en/produkter/standardization/technical-drawings/general/iso-128-22022/), [ISO 128-3](https://www.iso.org/standard/83356.html)). Die alten Teile -20 bis -25 sind in 128-2 aufgegangen, die Teile -30 bis -50 in 128-3 ([Wikipedia](https://en.wikipedia.org/wiki/ISO_128)) | Linienarten und -breiten, Ansichten, Schnitte, Einzelheiten |
| ISO 129-1 | 2018 + Amd 1:2020 ([ISO](https://www.iso.org/standard/64007.html)) | Bemaßungsregeln |
| ISO 6410-1 | 1993 ([DIN Media](https://www.dinmedia.de/en/standard/iso-6410-1/1308829)) | Gewindedarstellung |
| ISO 5455 | 1979 | Maßstabsreihe |
| ISO 5457 | 1999 + Amd 1:2010 | Blatt, Rand, Rahmen |
| ISO 7200 | 2004 | Schriftfeld |
| ISO 2768-1 | 1989. Teil 2 ist zurückgezogen und durch ISO 22081:2021 ersetzt ([SIS](https://www.sis.se/en/produkter/metrology-and-measurement-physical-phenomena/linear-and-angular-measurements/limits-and-fits/ssiso27682/)) | Allgemeintoleranz **„ISO 2768-m“** (nicht mehr „-mK“) |
| ISO 13715 | 2017 | Kantenangabe |
| ISO 3098-0 | 1997 | Schrift |
| ISO 6433 / ISO 7573 | 2012 / 2008 ([6433](https://www.iso.org/standard/51527.html), [7573](https://www.iso.org/standard/43883.html)) | Positionsnummern, Stückliste |

### 1.2 Linien (ISO 128)

- **Breiten** [N] ([ISO 128-20 als IS 10714-20](https://law.resource.org/pub/in/bis/S01/is.10714.20.2001.pdf)):
  - Reihe d = 0,13 · 0,18 · 0,25 · 0,35 · 0,5 · 0,7 · 1 · 1,4 · 2 mm.
  - Sehr breit, breit und schmal stehen im Verhältnis 4:2:1.
  - Paralleler Mindestabstand 0,7 mm.
- **Liniengruppe 0,5 für A4 bis A2** [S], 0,7 für A1/A0 ([FreeCAD LineGroup.csv](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/TechDraw/LineGroup/LineGroup.csv)):
  - breit 0,5 mm, schmal 0,25 mm, Schrift 0,35 mm
- **Strichlängen** [N] (128-20, Tabelle 3):
  - Punkt ≤ 0,5d, Lücke 3d, Strich 12d, langer Strich 24d.
  - Strich- und Strichpunktlinien sollen sich im Strich treffen, nicht in der Lücke.
  - FreeCAD rechnet den Punkt als 1d ([ElementDef.csv](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/TechDraw/LineGroup/ISO.128.20.1996.ElementDef.csv)).
- **Linienarten für Maschinenbauzeichnungen** [N] ([128-34](https://law.resource.org/pub/in/bis/S01/is.10714.34.2006.pdf), [128-40](https://law.resource.org/pub/in/bis/S01/is.10714.40.2006.pdf)):

  | Nr. | Linie | Wofür | Kev-CAD-Linienart (Vertrag) |
  |---|---|---|---|
  | 01.2 | Volllinie breit | sichtbare Kanten und Umrisse | `sichtbar` |
  | 01.1 | Volllinie schmal | Maß-, Hilfs- und Hinweislinien, Schraffur, Lichtkanten an Rundungen | `duenn`, `schraffur` |
  | 02.1 | Strichlinie schmal | verdeckte Kanten | `verdeckt` |
  | 04.1 | Strichpunktlinie schmal | Mittellinien, Lochkreise | `mitte` |
  | 04.2 | Strichpunktlinie breit | Enden und Knicke des Schnittverlaufs | `schnitt` |
  | 05.1 | Strich-Zweipunktlinie schmal | Nachbarteile, Endlagen beweglicher Teile | fehlt, nützlich für Gelenke |
  | 01.1.18/19 | Freihand-/Zickzacklinie | Bruchkante, Teilschnitt | fehlt, für lange Rohre |

### 1.3 Ansichten, Schnitte, Einzelheiten (ISO 128-3, früher -30/-34/-40/-44)

- **Ansichten** [N] ([128-30](https://law.resource.org/pub/in/bis/S01/is.10714.30.2006.pdf)):
  - Hauptansicht ist die aussagekräftigste Seite.
  - So wenige Ansichten wie nötig, verdeckte Kanten möglichst vermeiden.
  - Symmetrische Teile dürfen halb gezeichnet werden, mit zwei kurzen Querstrichen an der Symmetrielinie.
- **Projektionsmethode 1** (Europa, Draufsicht unter der Vorderansicht) mit ihrem Symbol auf dem Blatt [S] ([TUM-Skript](https://www.epe.ed.tum.de/fileadmin/w00bzo/ewt/Werkstatt/Zeichnungserstellung.pdf)).
  - Die Symbolmaße stehen in ISO 5456-2 nur als Bild [offen].
- **Schnitte** [N] ([128-40](https://law.resource.org/pub/in/bis/S01/is.10714.40.2006.pdf), [128-44](https://law.resource.org/pub/in/bis/S01/is.10714.44.2006.pdf)):
  - Schnittverlauf als 04.2 nur an Enden und Knicken, Pfeile für die Blickrichtung, gleiche Großbuchstaben an beiden Enden.
  - Über dem Schnitt „A–A“.
  - Halb- und Teilschnitt sind zulässig.
  - **Rippen, Wellen, Speichen und Verbindungselemente werden im Längsschnitt nicht geschnitten** [N]. Schrauben, Muttern und Scheiben auch nicht [S].
- **Schraffur** [S] (TUM):
  - schmale Volllinien unter 45°
  - benachbarte Teile gegensinnig oder mit anderem Abstand
  - Einen Zahlenwert für den Abstand nennt keine gelesene Quelle; Untergrenze sind die 0,7 mm aus 128-20 [offen].
- **Einzelheit** [N] (128-34 §11): schmaler Kreis mit Großbuchstabe, vergrößert als „Z (5:1)“.
- **Gleiche Elemente** wie Lochreihen dürfen einmal gezeichnet und sonst nur angedeutet werden [N] (128-34).

### 1.4 Bemaßung (ISO 129-1) und Gewinde (ISO 6410-1)

Der Volltext von 2018 ist nicht gelesen. Die Regeln stammen aus ISO 129:1985 ([IS 11669](https://law.resource.org/pub/in/bis/S01/is.11669.1986.pdf)) [N] und aus Lehrunterlagen [S].

- **Jedes Formelement nur einmal bemaßen, Funktionsmaße direkt eintragen** [N].
- **Kettenmaße nur dort, wo sich Toleranzen summieren dürfen**, sonst Parallel- oder steigende Bemaßung (vom Ursprungskreis aus) [N].
- **Maßzahl** parallel zur Maßlinie, mittig darüber, lesbar von unten oder von rechts [N]. Mindestens 3,5 mm hoch [S].
- **Maßlinienbegrenzung** [N]:
  - Pfeil 15° bis 90°, auf einem Blatt nur eine Pfeilform.
  - Alternativen: Schrägstrich 45° oder Punkt.
  - Praxis [S]: Pfeil 15°, Länge 10d.
- **Symbole vor der Zahl** [N]: Ø, R, □, SØ, SR. Ein Radius hat nur einen Pfeil.
- **Hilfsmaße** stehen in Klammern, **nicht maßstäbliche Maße** werden unterstrichen [N].
- **Maßhilfslinie** ragt etwa 2 mm über die Maßlinie hinaus [S]. Ein kleiner Spalt zur Körperkante ist erlaubt, ohne festen Wert [offen].
- **Abstand der Maßlinien: keine ISO-Zahl gefunden** [S]:
  - Wikibooks nennt 10 mm zur Kante und 7 mm untereinander, mit Verweis auf DIN 406 ([Wikibooks](https://de.wikibooks.org/wiki/Technisches_Zeichnen/_Ma%C3%9Feintragung)).
  - Andere Unterlagen nennen 10/5 oder 10/8 mm.
  - **Als einstellbare Hausregel 10/7 mm.**
- **Fasen** als „2 × 45°“; Fasen am Gewindeende werden nicht bemaßt [S].
- Für „4× Ø6“, Lochkreise und das Verbot, an verdeckte Kanten zu bemaßen, fehlt ein Normbeleg [offen]. Alle drei sind übliche Praxis.
- **Gewinde nach ISO 6410-1** [S] (TUM):
  - **Außengewinde:** Außendurchmesser breit, Kerndurchmesser schmal, in der Stirnansicht als schmaler ¾-Kreis.
  - **Innengewinde im Schnitt:** Kerndurchmesser breit, Außendurchmesser als ¾-Kreis.
  - Das Kernloch wird tiefer gezeichnet als das Gewinde. Bei verschraubten Teilen verdeckt das Außengewinde das Innengewinde.
  - Wie Gewindetiefe und Kernlochtiefe genau anzugeben sind, ist [offen].

### 1.5 Blatt, Maßstab, Schriftfeld, Toleranzen, Kanten, Schrift

- **Maßstäbe** [N] ([IS 10713](https://law.resource.org/pub/in/bis/S01/is.10713.1983.pdf)):
  - Vergrößerung: 50:1, 20:1, 10:1, 5:1, 2:1.
  - Verkleinerung: 1:2, 1:5, 1:10, 1:20, 1:50, 1:100 und weiter.
  - Erweiterung nur über Zehnerpotenzen.
- **Blatt** [N] ([IS 10711](https://law.resource.org/pub/in/bis/S01/is.10711.2001.pdf)):
  - Rand links 20 mm, sonst 10 mm, Rahmen 0,7 mm.
  - Mittenmarken; Feldeinteilung in 50-mm-Feldern, Buchstaben ohne I und O.
  - Schriftfeld unten rechts.
  - A0 bis A3 quer, A4 hoch; seit Amd 1:2010 ist A4 auch quer erlaubt ([DIN Media](https://www.dinmedia.de/de/norm/din-en-iso-5457/278410251)).
- **Schriftfeld nach ISO 7200** [N] ([IS 11665](https://law.resource.org/pub/in/bis/S01/is.11665.2010.pdf)):
  - **180 mm breit** für alle Formate.
  - **Acht Pflichtfelder:** Eigentümer, Sachnummer, Ausgabedatum, Blattnummer, Titel, Freigebender, Ersteller, Dokumentart.
  - Maßstab und Projektionssymbol sind keine ISO-7200-Felder; sie stehen üblicherweise daneben im Kopf.
- **ISO 2768-1, Klasse m** [S], Werte von Wevolver mit TUM abgeglichen ([TUM-Blatt](https://www.epe.ed.tum.de/fileadmin/w00bzo/ewt/Werkstatt/Allgemeintoleranzen_nach_DIN_ISO_2768.pdf), [Wevolver](https://www.wevolver.com/article/iso-2768-general-tolerances-tables-classes-current-status)):
  - Längenmaße: ±0,1 (0,5 bis 6 mm), ±0,2 (bis 30), ±0,3 (bis 120), ±0,5 (bis 400), ±0,8 (bis 1000), ±1,2 (bis 2000), ±2 (bis 4000).
  - Radien und Fasen: ±0,2 / ±0,5 / ±1.
  - Winkel nach kürzerem Schenkel: ±1° (bis 10 mm), 30′, 20′, 10′, 5′.
  - Eine zweite Ausgabe von ISO 2768 ist laut ISO in Vorbereitung ([ISO 85741](https://www.iso.org/standard/85741.html)) [S].
- **Kanten nach ISO 13715** [N] ([Vorschau](https://qualityforum.zeiss.com/migration/images/1125_cad718ab03258942de4de01b28242c05.pdf)):
  - „+“ bedeutet Grat bzw. Übergang erlaubt, „−“ bedeutet Abtrag gefordert.
  - „−0,3“ heißt gratfrei, Abtrag bis 0,3 mm.
  - Es gibt eine Sammelangabe für alle Kanten. Definierte Fasen werden nach ISO 129 bemaßt.
- **Schrift nach ISO 3098-0, Typ B** [N] ([IS 9609-0](https://law.resource.org/pub/in/bis/S01/is.9609.0.2001.pdf)):
  - Höhen 1,8 · 2,5 · 3,5 · 5 · 7 · 10 mm.
  - Linienbreite h/10, Kleinbuchstaben 0,7h, Zeichenabstand 0,2h, Zeilenabstand mindestens 1,5h.
  - senkrecht oder 75° geneigt
- **Hinweislinien** [N] ([128-22](https://law.resource.org/pub/in/bis/S01/is.10714.22.2006.pdf)):
  - Endet die Linie in einer Fläche: Punkt mit Ø 5d.
  - An einer Kante: Pfeil.
  - An einer Linie: kein Abschluss.
  - Kreis und Spalten der Positionsnummern nach ISO 6433/7573: Inhalt [offen].
- **Oberflächen:** ISO 1302 ist zurückgezogen und durch ISO 21920-1:2021 ersetzt ([SIS](https://www.sis.se/en/produkter/standardization/technical-drawings/mechanical-engineering-drawings/iso13022002)).

### 1.6 Was für Werkstattzeichnungen eines Makers zählt

**Fest einbauen:**

- Projektionsmethode 1 mit Symbol.
- Liniengruppe 0,5, Strichlängen nach Tabelle (rein rechnerisch).
- Schrift Typ B senkrecht: 3,5 mm für Maße, 5 mm für Titel.
- A4 hoch oder quer, A3 quer. Rand 20/10 mm, Rahmen 0,7 mm. Feldeinteilung erst ab A3.
- Maßstab automatisch der größte aus der Vorzugsreihe, der passt.
- Schriftfeld 180 mm mit den acht Pflichtfeldern plus Maßstab, Werkstoff/Halbzeug, Masse und Allgemeintoleranz. Eigentümer und Freigebender sind Kevin.
- „ISO 2768-m“ als Vorgabe, Einzeltoleranzen nur bei Passungen.
- Kanten-Sammelangabe „−0,3“ (entgratet) für Zuschnitte aus Metall.
- Jedes Maß einmal. Bezug an der Anschlag- oder Funktionskante, bei Rohren am Rohrende.
- Lochbilder als „n× Ø“, Gewinde als „M8“ mit Tiefe.
- Zusammenbau mit Positionsnummern und Stückliste. Normteile im Schnitt nicht schneiden, Schraffur gegensinnig.

**Ballast** für Einzelstücke:

- Form- und Lagetoleranzen (ISO 1101), Rauheitsangaben (ISO 21920-1). Ohne Messtechnik prüft das niemand. Bei 3D-Druck höchstens ein Freitext.
- Änderungsindex-Verwaltung, Sprachcode, Schneid- und Mittenmarken, Klassifikationsfelder. Die Version steht schon über den Meilenstein im Schriftfeld.
- Koordinatentabellen. Erst sinnvoll ab etwa einem Dutzend Bohrungen, etwa bei Lochplatten.

## 2. Automatische Bemaßung

### 2.1 Verfahren aus der Literatur

| Quelle | Kern | Brauchbar für Kev CAD |
|---|---|---|
| Chen, Feng, Lu 2001, CAD 33(13) ([DOI](https://doi.org/10.1016/S0010-4485(00)00132-9)) | Redundanz erkennen, Features erkennen, Schema wählen, Maße Ansichten zuordnen, regelbasiert platzieren. Jedes Maß reserviert eine Region | Ablaufmodell. Schwäche ist die strikte Reihenfolge; Volltext nicht gelesen, Inhalt laut Kakoulis 2023 |
| Raffaeli, Cicconi, Germani 2016, CAD&A 13(4) ([DOI](https://doi.org/10.1080/16864360.2015.1131538)) | „Drafting Schemes“: Vorlage je Teilefamilie mit festem Ansichtenlayout und fester Bemaßungsstrategie, Bezüge per Feature-Suche | **Kernidee:** Vorlagen je Teiletyp (Rohr, Platte, Druckteil …) |
| Kakoulis et al. 2023, IJMMT 15(3) ([DOI](https://doi.org/10.54684/ijmmt.2023.15.3.67)), gelesen | Seite je Segment über die Lage zum Schwerpunkt der Ansicht. Endpunkte auf die Seiten projizieren, Doppelte streichen, dann Kreise und Bögen; O(n log n). Kein Maß in zwei Ansichten. Kosten: wenige Maße je Seite, kurze Maß- und Hilfslinien | **Platzierung Stufe 1.** Die Arbeit kritisiert SolidWorks Autodimension: Überlappungen, Bögen dreifach bemaßt |
| Yu, Tan, Yuen 1994, Übersicht ([DOI](https://doi.org/10.1007/BF01200178)) | Überblick über die frühen Verfahren | nur Hintergrund, nicht gelesen |
| Autodesk-Patent [US11954820B2](https://patents.google.com/patent/US11954820B2/en) (2024) | Maße per Graphabgleich (GNN, Hungarian-Algorithmus) von ähnlichen bemaßten Zeichnungen übertragen | nicht nachbauen; ob Fusion es nutzt, ist offen |
| ML direkt von 3D zu Maßen | keine belastbare Arbeit 2020–2026 gefunden; die Forschung läuft meist umgekehrt (Zeichnung zu CAD) | – |
| Ansichtenwahl | kein spezielles Paper gefunden; maßgeblich ist die Normregel „aussagekräftigste Seite, so wenige Ansichten wie nötig“ | eigene Heuristik (2.5) |

**Überbemaßung als Graph** (Übertragung aus Constraint-Solvern, kein Bemaßungspaper):

- Je Achse sind die Koordinatenebenen der Anker die Knoten, die Maße die Kanten.
- Bezugsbemaßung ist ein Stern, Kettenbemaßung ein Pfad.
- **Jeder Kreis im Graphen ist eine Überbemaßung**, jeder nicht erreichbare Knoten ein fehlendes Maß.
- Das passt zur Unter-/Überbestimmungsmeldung, die Kev CAD für Bedingungen schon hat (PLAN-BEDINGUNGEN B5).

### 2.2 Platzierung ohne Überlappung

- **Christensen, Marks, Shieber 1995** ([DOI](https://doi.org/10.1145/212332.212334), [TR94-12](https://www.merl.com/publications/docs/TR94-12.pdf)):
  - Beschriftungsplatzierung ist NP-schwer.
  - Simulated Annealing über diskrete Kandidatenlagen ist die erste Wahl, wenn Qualität zählt, und ist schnell genug.
- **Boundary Labeling** (Bekos et al. 2007, [DOI](https://doi.org/10.1016/j.comgeo.2006.05.003)): Beschriftungen am Rand mit Führungslinien. Passt zu Bohrungs- und Gewindeangaben (Volltext nicht gelesen).
- **Regeln für Maße** [S] (Kakoulis 2023, TUM):
  - nah am Element, nicht durch das Teil
  - Maßlinien kreuzen sich nicht und kreuzen keine Maßhilfslinien; Maßhilfslinien dürfen sich kreuzen
  - Text mittig zwischen den Pfeilen und von keiner Linie gekreuzt
  - kurze Maße innen, lange außen, Gesamtmaß ganz außen
- **build123d `DimensionLine`** (Code gelesen):
  - drei Fälle: Text und Pfeile innen, Pfeile außen, alles außen
  - Textlage bewertet nach Überlappung mit der Skizze
  - Gute Regel für zu kurze Maße.

### 2.3 Bestehende Programme

| Programm | Automatik | Bindung an die Geometrie | Übernehmbar |
|---|---|---|---|
| **FreeCAD TechDraw** (LGPL-2.1+) | Keine Vollautomatik; Erweiterungen arbeiten auf gewählten Punkten oder Maßen: Kette, Koordinaten, Staffeln, Lochkreis, Fase, Präfixe Ø/□/n× ([CommandExtensionDims.cpp](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/TechDraw/Gui/CommandExtensionDims.cpp)) | `References2D` (Projektion) plus `References3D` (Modell), `SavedGeometry`. Bei Änderung: exakt gleiche Geometrie unter neuem Index suchen; der „ähnlich“-Abgleich ist im aktuellen main leer ([DimensionAutoCorrect.cpp](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/TechDraw/App/DimensionAutoCorrect.cpp), [GeometryMatcher.cpp](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/TechDraw/App/GeometryMatcher.cpp)) | **Verfahren nachbauen**, nicht den Code kopieren: Kopierter oder 1:1 übertragener Code bliebe LGPL |
| **Fusion** ([Hilfe](https://help.autodesk.com/cloudhelp/ENU/Fusion-Drawing/files/DWG-AUTO-DRAWING.htm)) | Ansichten automatisch. Auto Dimension mit Baseline, Chain, Ordinate, Overall, Symmetric, Symmetric with baseline; Bezug wählbar, Regler „Density“, danach „Tidy Up“; Standardstrategie je Blatttyp | proprietär | Bedienkonzept: Strategie, Dichte, Aufräumen |
| **SolidWorks** ([Autodimension](https://help.solidworks.com/2022/English/SolidWorks/Sldworks/t_Autodimensioning_a_Drawing.htm), [Auto Arrange](https://help.solidworks.com/2018/english/SolidWorks/sldworks/t_auto_arrange_dimensions.htm)) | Baseline, Chain, Ordinate je Ansicht; DimXpert-Schema; Modellmaße einfügen | proprietär | Kritik bei Kakoulis beachten: jede Ansicht unabhängig bemaßt |
| **Inventor** ([Retrieve Model Annotations](https://help.autodesk.com/cloudhelp/2026/ENU/Inventor-Help/files/GUID-675E2605-5E63-40C6-9DCB-E2862CCB3D71.htm)) | Skizzen- und Feature-Maße übernehmen, jedes nur einmal je Blatt | proprietär | Regel „einmal je Blatt“ |
| **Onshape** | keine Auto-Bemaßung gefunden [offen] | – | – |
| **CadQuery** | nur SVG/DXF mit verdeckten Kanten; [cq_warehouse/drafting.py](https://github.com/gumyr/cq_warehouse/blob/HEAD/src/cq_warehouse/drafting.py) ist der Vorläufer von build123d `drafting` | – | – |
| **build123d 0.13** `drafting.py` (Apache-2.0, Code gelesen) | **Keine Automatik.** Klassen `Draft`, `DimensionLine`, `ExtensionLine`, `TechnicalDrawing`, `Arrow(Head)`; keine Radius-, Durchmesser- oder Winkelklasse; Toleranz nur ±x bzw. +a/−b | keine; Maße und **Text sind gefüllte Flächen** (Glyphen-Umrisse), im DXF als LINE/SPLINE, nicht bearbeitbar | **nicht als Datenmodell nutzen** |
| **text-to-cad / cadgen** (MIT, [eng_drawing.py](https://github.com/earthtojake/text-to-cad/blob/main/packages/cadgen/src/cadgen/eng_drawing.py)) | Keine Feature-Erkennung: Maße werden in Modellkoordinaten angegeben, `overall()` setzt Gesamtmaße, Mittelkreuze automatisch, Reihen alle 12 mm, Bohrungsangaben per Hinweislinie gestapelt | **Anker in 3D, gleicher Projektor wie die Geometrie**; echte ezdxf-DIMENSION | Reihen-, Hinweislinien- und Maßstabslogik; Prüfungen in [drawing_checks.py](https://github.com/earthtojake/text-to-cad/blob/main/packages/cadgen/src/cadgen/drawing_checks.py) |
| **cad-studio** (MIT) | keine Engine: Der Agent zeichnet je Lauf mit matplotlib, Vorgaben im [Prompt](https://github.com/filippofinke/cad-studio/blob/main/CADStudio/Resources/CADSystemPrompt.md) | – | nur die Prompt-Vorgaben |
| [freecad-automation](https://github.com/dooosp/freecad-automation) (MIT, klein) | einfache Regeln: Bohrung → Schnitt, Fase → Einzelheit; Lochbild → Koordinaten, sonst Kette; Lochkreis ab 3 gleichen Bohrungen | – | Ideen, Regeln teils grob |
| OCCT `PrsDim_*`, [ezdxf](https://ezdxf.readthedocs.io/en/stable/dxfentities/dimension.html) (MIT) | 3D-Maße im OCCT-Viewer; DXF-Maße aller Arten | – | ezdxf für einen DXF-Export der Blätter |

### 2.4 Fallen in build123d beim Projizieren (getestet)

- **`look_at` ist standardmäßig der Schwerpunkt** [G]. Die Blickrichtung wird aus `viewport_origin − look_at` gebildet. Bei einer Platte mit außermittiger Bohrung kippt die Ansicht dadurch leicht: Kreise kommen als Ellipsen zurück, und es entstehen Mini-Segmente. Abhilfe: die Richtung explizit vorgeben, wie `exporters.Drawing(look_from=…)` oder ein eigener `gp_Ax2`.
- **Glatte Übergangskanten zählen als sichtbar.** `project_to_viewport` legt `Rg1Line` (Kanten zwischen tangential stetigen Flächen, also Rundungsränder) in die sichtbaren Kanten (`topology/one_d.py`, ab Zeile 1479). Nach ISO sind das schmale Linien (01.1) oder sie entfallen. Der Code auf `phase6-b` trennt sie bereits als `duenn`.
- **Keine Verbindung zum Modell.** Die projizierten Kanten verlieren jede Verbindung zu den 3D-Kanten, und ihre Reihenfolge ist nicht stabil. Maße deshalb nie an Projektionskanten hängen.

### 2.5 Heuristiken, die die eigene Engine umsetzen sollte

1. **Vorlage je Teiletyp** (Drafting Scheme). Kev CAD kennt den Typ aus Lager, Druckteil und Zukauf:

   | Teiletyp | Inhalt der Zeichnung |
   |---|---|
   | Rohr/Profil | eine Ansicht längs, Profil als Text („Rohr 20 × 2“), Länge, Gehrungen, Bohrungen als Bezugsmaß ab dem Rohrende, Lochbild |
   | Platte/Laserteil | eine Ansicht, „t = 4“, Koordinatenmaße ab Ecke unten links |
   | Holz | Länge × Breite × Dicke, Bohrungen, Faserrichtung als Pfeil |
   | Drehteil | eine Ansicht mit Mittellinie, Ø-Maße, Schnitt bei Innenbohrung |
   | 3D-Druckteil | Hüll- und Funktionsmaße (Bohrungen, Einsatztaschen, Passflächen), sonst „nach CAD-Modell“ |
   | Normteil | keine Zeichnung, nur Stücklistenzeile |
   | Baugruppe | Hüll- und Anschlussmaße, Positionsnummern, Stückliste |

2. **Feature-Erkennung auf B-Rep.** Läuft auf `phase6-b` (`zeichnung/merkmale.py`):
   - Zylinder nach innen bzw. außen unterscheiden: Bohrung oder Zapfen.
   - Koaxiale Stufen ergeben Senkungen. Langloch: zwei Halbzylinder mit parallelen Ebenen.
   - Fasen und Rundungen.
   - Lochbilder als Reihe, Raster oder Kreis, mit CAD-Toleranz statt Prozent.
   - Gewinde nur mit Gegenstück aus der Baugruppe.
3. **Ansichtenwahl als Mengenüberdeckung:**
   - Hauptachsen aus dem Teilsystem.
   - Hauptansicht ist die Richtung mit der besten Wertung: projizierte Fläche, Kreise in Draufsicht, Feature-Kanten, abzüglich verdeckter Kanten.
   - Weitere Ansichten nur, wenn sie ein Maß sichtbar und in wahrer Länge ermöglichen, das sonst fehlt.
   - Ein Schnitt, wenn ein Innenmerkmal sonst nur verdeckt bemaßbar wäre.
4. **Bezug:** Anschlag- oder Auflagefläche, bei Stangen das Schnittende, bei Symmetrie die Achse. Lochbilder als Ganzes verorten (Mitte des Musters zum Bezug), innen „n× Ø“ plus Teilung bzw. Lochkreis.
5. **Je Achse ein Bemaßungsgraph** (2.1) als Spannbaum ab dem Bezug. Kreise und Lücken sind Befunde im gemeinsamen Format der Prüfung.
6. **Platzierung in zwei Stufen:**
   - Stufe 1: Seite nach Kakoulis; Reihen 10/7 mm, kurz innen, lang außen; Drei-Fälle-Regel für Text und Pfeile; Bohrungsangaben als Hinweislinie zur freien Seite.
   - Stufe 2: Simulated Annealing über Kandidatenlagen. Hohe Kosten für Text auf Text, Text auf Geometrie und Maßlinie über Maßhilfslinie.
7. **Prüfungen wie in text-to-cad, ergänzt um Vollständigkeit:**
   - Maß zeigt ins Leere, ragt aus dem Rahmen, überlappt oder ist doppelt.
   - Jedes Merkmal hat ein Größen- und ein Lagemaß.

## 3. Projektion

### 3.1 Exakt gegen Netz

Laut [OCCT-Benutzerhandbuch, Abschnitt Hidden Line Removal](https://occt3d.com/dev/doc/overview/html/occt_user_guides__modeling_algos.html):

- **`HLRBRep_Algo`** arbeitet auf der B-Rep und liefert ein exaktes Ergebnis. Linien und Kreise bleiben Linien und Kreise.
- **`HLRBRep_PolyAlgo`** arbeitet auf dem Netz. Es spart Rechenzeit und liefert nur Polygonzüge.
- Beide vergleichen jede Kante mit jeder Fläche.
- **Ausgabe:** sichtbare und verdeckte Kanten getrennt nach Art: scharfe (`V/HCompound`), glatte (`Rg1Line`), genähte (`RgNLine`) und Umrisslinien (`OutLine`). Isolinien gibt es nur beim exakten Verfahren.
- **Nicht verarbeitet:** Punkte und unendliche Flächen.
- Weder Mehrkern-Nutzung noch Leistungsschalter sind dokumentiert [offen].

### 3.2 Messungen [G]

Die Zeiten gelten je Ansicht und Lauf. Die Szene ist die Outdoorküche eines Kunden (STEP, 112 Körper, 2.126 Flächen, 10.356 Kanten).

| Fall | exakt (`HLRBRep_Algo`) | Netz (`PolyAlgo`, inklusive Vernetzung 0,5 mm) |
|---|---|---|
| Einzelteil: Platte mit Rundungen, Senkungen, Fase (32 Flächen), drei Ansichten | je 0,01 s | je unter 0,01 s |
| Küche iso | 0,5 s | 0,24 s |
| Küche vorn / oben / rechts | **9 s / 23 s / 44 s** | 0,25 s |
| einzelne Körper der Küche (Roste aus Runddraht, 105–111 Flächen), Ansicht rechts | **54–145 s** (gekippt um 10⁻⁴ rad: 1 s) | 0,01 s |
| nachgebauter Rost: 10 Drähte Ø3 auf 2 Querstäben, verschmolzen (36 Flächen), rechts | **82 s** | 0,02 s |
| derselbe mit 20 Drähten (66 Flächen), rechts | **311 s** | 0,03 s |
| 20 getrennte Rohre in einer Reihe, Blick entlang der Reihe | 0,02 s | 0,01 s |
| Schnitt durch die Küche (`split` an einer Ebene, 5–19 geschnittene Körper) | 0,06–0,36 s | – |

**Erkenntnisse:**

- **Die exakte Rechnung bricht bei achsparallelen Ansichten ein.** Betroffen sind verschmolzene Körper mit
  sich durchdringenden Zylindern (Roste, Rohrknoten, gedruckte Teile mit Querbohrungen), wenn ihre Schnittkurven
  streifend gesehen werden. Die Laufzeit wächst stärker als linear und ist **nicht an der Flächenzahl ablesbar**.
- **Getrennte Teile blieben im Test schnell**, auch viele gleiche hintereinander.
- **Auch der Code auf `phase6-b` läuft in diesen Fall.** `projiziere(rost, "rechts")` braucht dort 81 s. Er rechnet
  unter `POLY_AB_FLAECHEN = 60000` immer exakt.
- **Das Netz liefert praktisch dasselbe Bild.** Am Rost-Körper ist die sichtbare Umrisslänge identisch (520,2 mm). Die
  sichtbaren scharfen Kanten weichen um rund 20 % ab (43,7 gegen 55,7 mm), die verdeckten um 2 % (594 gegen 582 mm).
  - Dafür gibt es viele kurze Segmente: 7.442 verdeckte Stücke statt 582. Sie müssen zusammengefasst werden.
  - Kreise werden Polygone. Für die Bemaßung ist das gleichgültig, weil Maße an 3D-Ankern hängen (2.5).
- **Kippen ist keine Lösung.** Eine um 10⁻⁴ rad gekippte Blickrichtung macht die exakte Rechnung schnell (1 s),
  verfälscht aber die Sichtbarkeit streifend gesehener Flächen. Am Rost wurden aus 520 mm Umriss 4.162 mm.
- **Vorhandene Vernetzung beschleunigt die exakte Rechnung nicht** (gemessen: gleiche Zeiten mit und ohne Netz).

Nachstellbarer Fall für Tests (build123d):

```python
with BuildPart() as p:
    with GridLocations(44.5, 0, 10, 1):
        Cylinder(1.5, 265, rotation=(90, 0, 0))
    with Locations((0, 100, -2.0), (0, -100, -2.0)):
        Cylinder(2.0, 445, rotation=(0, 90, 0))
# HLRBRep_Algo, Blick entlang +X: rund 80 s; HLRBRep_PolyAlgo: 0,02 s
```

### 3.3 Schnittansichten mit Schraffur

- **Schnittfläche:**
  - Je geschnittenem Körper mit `split(Ebene, keep=…)` schneiden.
  - Die Flächen in der Ebene sind die Schnittflächen, ihre Ränder die Schraffurgrenzen.
  - Der Rest wird normal projiziert.
- **Ausnahmen:** Normteile, Wellen und Rippen nicht schneiden. Kev CAD erkennt sie aus Lager und Katalog (Art
  „schraube“, „mutter“ …).
- **Schraffur je Teil:** Winkel und Abstand wechseln, damit benachbarte Teile unterscheidbar sind, etwa 45° und 135°,
  dann versetzt mit anderem Abstand.
- **Schraffur in der App zeichnen:** Clip-Pfad plus Linien (Abschnitt 5) statt `CGPattern`. Der Kernel schickt nur die
  Grenzpolygone mit Teil-ID.
- **Halbschnitt:** Schnitt nur in einem Viertel des Körpers (Quader-Subtraktion), Trennlinie als Mittellinie.
- **Teilschnitt:** wie der Halbschnitt mit Freihand-Begrenzung. Das ist eine reine Darstellungsaufgabe.

### 3.4 Leistung bei Baugruppen mit 100+ Teilen

1. **Verdeckung standardmäßig auf dem Netz** (0,1–0,25 s für 112 Teile).
   - Die exakte Rechnung nur für Einzelteilblätter, in einem eigenen Prozess mit Zeitbudget, etwa 2 s.
   - Läuft sie zu lang, wird sie abgebrochen und das Netzergebnis bleibt; Abbrechen nur über einen eigenen Prozess, weil OCP keinen Abbruch bietet [offen].
   - Optional nachträglich Kreisbögen in die Polygone einpassen, für DXF und für schönere PDF-Kreise.
2. **Zwischenspeicher je Formschlüssel, Ansicht und Optionen.** Steht auf `phase6-b`.
3. **Zusammenbau ohne verdeckte Kanten.** Das ist übliche Praxis [S], und die Netzrechnung liefert dort zehntausende
   verdeckte Segmente, die nur stören.
4. **Ansichten parallel in getrennten Prozessen.** Der Rechenprozess von Kev CAD ist ohnehin ein eigener Prozess;
   M2 Pro mit vielen Kernen.
5. **Bauplanbilder** (30 Schritte und mehr) ebenfalls auf dem Netz: zusammen wenige Sekunden.

## 4. Bauanleitungen

### 4.1 Forschung

**Agrawala, Phan, Heiser et al., SIGGRAPH 2003** ([DOI](https://doi.org/10.1145/882262.882352), [Projekt](https://graphics.stanford.edu/papers/assembly_instructions/)), Volltext gelesen.

- **Gestaltungsprinzipien:**
  - Hierarchie aus Hauptteilen und Verbindern.
  - Je Bild ein Hauptteil, aber mehrere Verbinder.
  - Gleiche oder symmetrische Teile zusammen bzw. direkt nacheinander.
  - Wiederholte Abläufe nur zweimal ausführlich zeigen.
  - Aktionsbilder (neue Teile abgerückt, mit Hilfslinien) sind besser als reine Strukturbilder, sobald nicht alles gleich gefügt wird.
  - Ansicht schräg von oben, in natürlicher Lage.
  - **Alle neuen Teile sichtbar, dazu etwas vom bisherigen Stand.**
- **Planer:**
  - gierig über Teilmengen der noch fehlenden Hauptteile; Verbinder werden danach eingesetzt
  - Harte Bedingungen: keine Kollision, Befestigung (ein Teil erst, wenn sein Gegenstück verbaut ist), vorgegebene Reihenfolgen, Gruppen.
  - Die einzige Kostenfunktion ist die Sichtbarkeit über einen Farbpuffer: neue Teile mindestens 50 %, bisherige 10 %, künftige 25 %.
  - Unter 35 % wird die Kamera umgestellt.
- **Blockierung:** Bewegungsrichtungen diskretisiert, oft reichen die 6 Hauptachsen.
- **Explosion:**
  - kürzester Weg aus der Hülle der Kontaktteile
  - Schraube, Scheibe und Mutter als Stapel mit wachsendem Abstand
  - Hilfslinien ab der Mitte der Kontaktflächen
- **Grenzen:** nur Verschiebungen; Gruppen werden von Hand vergeben.
- **Nutzertest** (Heiser et al., AVI 2004, [DOI](https://doi.org/10.1145/989863.989917)): Montage rund 35 % schneller,
  50 % weniger Fehler als mit der Fabrikanleitung. Getestet wurde nur ein TV-Ständer mit wenigen Teilnehmenden.

**Weitere Arbeiten zur Darstellung:**

- **Li, Agrawala, Curless, Salesin, SIGGRAPH 2008** ([DOI](https://doi.org/10.1145/1360612.1360700), [Projekt](https://grail.cs.washington.edu/projects/exview3D/)):
  - Explosionsgraph, indem iterativ das Teil mit dem kürzesten Fluchtweg entfernt wird.
  - Unterbaugruppen explodieren für sich, nur entlang der Hauptachsen.
  - Setzt Teile ohne Überlappung voraus. Schrauben mit Gewindeüberlappung müssen ausgenommen werden; Kev CAD erlaubt Gewindeeingriff bereits in der Prüfung.
- **Mitra et al., SIGGRAPH 2010** ([DOI](https://doi.org/10.1145/1778765.1778795)): Bewegungspfeile und Bildfolgen aus der Bewegungsanalyse. Passt zu den Gelenken (nur Kurzfassung gelesen).

**Montagefolge als umgekehrte Demontage:**

- AND/OR-Graphen nach Homem de Mello & Sanderson 1990 ([DOI](https://doi.org/10.1109/70.54734)).
- Richtungsunabhängiger Blockiergraph (NDBG) nach Wilson & Latombe 1994 ([DOI](https://doi.org/10.1016/0004-3702(94)90048-5)). Beide nicht gelesen.
- **Sandia „Archimedes“** ([US5980084](https://patents.google.com/patent/US5980084A/en)): Verbinder sind „Sekundärteile“, direkt nach dem Fügen eingesetzt und direkt vor dem Lösen entfernt.
- **Tian et al., „Assemble Them All“, SIGGRAPH Asia 2022** ([DOI](https://doi.org/10.1145/3550454.3555525)): physikbasierte Demontage auch mit Drehungen.
- **Tian et al., „ASAP“, ICRA 2024** ([arXiv](https://arxiv.org/abs/2309.16909)): Demontage unter Schwerkraft, jede Zwischenbaugruppe steht stabil. Ob es Code gibt, ist [offen].

**Werkzeugzugang** (Wilson, ICRA 1996, [OSTI 204109](https://www.osti.gov/biblio/204109)):

- Jedes Werkzeug hat ein **Nutzvolumen**, den nötigen Freiraum, plus Lagebedingungen zum Zielteil.
- Die Prüfung ist ein Platzierungsproblem.
- Schwenkwinkel laut Archimedes-Patent: Ringschlüssel etwa 60°, Innensechskantschlüssel 360°.

**ML und Vision:** IKEA-Manual (NeurIPS 2022), MEPNet (ECCV 2022), LegoGPT (2025) braucht Kev CAD nicht. Brauchbar ist
ein Befund aus „IKEA Manuals at Work“ (NeurIPS 2024): Rund 25 % der Möbel haben mehr als eine gültige Folge
(laut Folien). Mehrdeutigkeit ist also normal und eine Rückfrage an Kevin wert.

### 4.2 Stil von IKEA und LEGO

**Belegt:**

- **IKEA** (Interview in *Works That Work*, [Zhuang](https://justinzhuang.com/posts/wordless-instructions/)):
  - Aufbau: Bild des fertigen Produkts, Comic mit Hinweisen (Unterlage, zweite Person), Werkzeugliste, nummerierte Schritte.
  - Schwarz-weiße Strichbilder, Grau zum Hervorheben, kein Text.
  - Zuerst Rahmen und große Teile, damit man früh Fortschritt sieht.
  - Teile und Werkzeuge mit Nummern.
- **LEGO** ([lego.com](https://www.lego.com/en-si/service/help-topics/article/how-we-design-our-building-instructions)): eigene 3D-Software; je Schritt Teile und Blickwinkel festlegen; das Modell wird auf mehreren Wegen gebaut, um die beste Folge zu finden.

**Verbreitet, aber nicht offiziell belegt:**

- **LEGO:** Teilekasten mit „2x“ je Schritt, Unterbaugruppen im eigenen Kasten, Drehsymbol (so umgesetzt in [LPub3D](https://sourceforge.net/projects/lpub3d/)).
- **IKEA:** 1:1-Schraubenbild, Lupenkreise, Richtig/Falsch-Bilder; Zwei-Personen-Symbol (nur in einer Händler-Symbollegende).
- **Nicht eingesehen:** die wohl beste Einzelquelle, Schumacher, „A Pattern Language for Pictorial Assembly Instructions“ 2013 ([DOI](https://doi.org/10.1075/idj.20.2.03sch)), und die Norm IEC/IEEE 82079-1:2019 für Gebrauchsanleitungen.

### 4.3 Werkstattschritte

- **Kernlöcher für Regelgewinde** [S] ([Hartner, DIN 336](https://www.hartner.de/wp-content/uploads/2025/07/HAR_Plakat_Kernlochdurchmesser_Bohren_2025_DE.pdf)):
  - M3 → 2,5 · M4 → 3,3 · M5 → 4,2 · M6 → 5,0 · M8 → 6,8 mm.
  - Gleich mit `skill/kev-cad/SKILL.md` und `merkmale.py` auf `phase6-b`.
  - DIN 336 selbst nicht gelesen.
- **Senkungen:**
  - ISO 15065 gilt laut Anwendungsbereich für Senkköpfe nach ISO 7721 (ISO 2009, 7046, 14586) ([Nimonik](https://standards.nimonik.com/products/bsi/bs-iso-15065/)).
  - **ISO 10642 steht nicht darin.** Die passende Senkung zu ISO 10642 und den 90°-Winkel im Normtext konnte ich nicht belegen [offen].
  - Senkmaße daher aus dem Normteil-Katalog nehmen, nicht aus einer pauschalen Regel.
- **Zuschnitt:**
  - MaxCut ([Funktionen](https://maxcutsoftware.com/features/cutting-optimization/)) führt Sägeschnitt und Randbeschnitt je Material, Etiketten und Bohrungen im Schnittplan.
  - OpenCutList (GPL-3) bietet Zuschnittliste, Schnittpläne, Etiketten und Explosionsbilder.
  - Kev CAD hat das meiste schon (`bom.py`: Zuschnitt mit Sägeschnitt und Gehrung, Bestand mit Resten).
- **Arbeitsplan:** Es gibt kein Normformular.
  - Ausbildungsordnungen verlangen Arbeitsschritt, Werkzeug und Maschine, technologische Daten, Prüfmittel und Arbeitsschutz ([Beispiel Metallbau](https://www.gesetze-im-internet.de/metallbausbvo/__14.html)).
  - Die Folge Anreißen, Körnen, Vorbohren, Bohren, Entgraten, Senken, Gewindeschneiden ist Fachwissen ohne Beleg.
- **Bohrbild je Teil:** Koordinaten ab Bezugskante bzw. Rohrende, Bohrer-Ø, Senkung, Gewinde mit Kernloch.
  - Optional eine **3D-gedruckte Bohrschablone** aus genau diesen Daten, mit den vorhandenen Druckregeln.

### 4.4 Was der Algorithmus kann, was die KI ergänzt

**Zuverlässig im Kernel:**

- **Montagefolge per Demontage** mit Kollisionsprüfung entlang endlich vieler Richtungen.
  - Die Fügerichtung kommt aus den Bedingungen: `in_bohrung` und `konzentrisch` liefern die Achse, `auf` die Normale, `verbinde(mit=…)` die Verbinder.
- **Verbinder als Sekundärteile**, Stapel aus Schraube, Scheibe und Mutter.
- **Gruppen:** gleiche Lagerteile, Symmetrie, Hierarchie aus „/“ in den Namen.
- **Kamera mit Sichtbarkeitsmaß** über den vorhandenen ID-Puffer des Viewports.
- **Hervorhebung, Teilezähler, Werkzeug** aus dem Normteiltyp (Schlüsselweite, Innensechskant aus dem Katalog).
- **Bohrbilder** aus den erkannten Merkmalen, **Zuschnittliste** aus der Stückliste.
- **Werkzeugzugang** als Nutzvolumen-Körper gegen den Stand des Schritts.
- **Einführweg** über die vorhandene Animation und `kollision_pruefen`.

**Begrenzt zuverlässig:**

- Standsicherheit von Zwischenständen. Die Prüfung Stufe 2 hat Standsicherheit für die Ruhelage; für jeden Zwischenstand muss sie erweitert werden.
- Drehfügen, Presspassungen, biegsame Teile.
- „Natürliche“ Lage und Umdrehen der Baugruppe.
- Zwei Personen nötig: nur über Schwellen für Masse und Länge, die noch zu eichen sind.

**KI als Text:**

- Hinweise und Warnungen, etwa in Holz vorbohren, PLA-Gewinde nicht überdrehen, entgraten.
- Begründungen für die Reihenfolge.
- Bei gleichwertigen Folgen die Wahl mit Rückfrage an Kevin.
- Namen für Unterbaugruppen und Bildkritik anhand von Mehrfachansichten.

**Maße, Anzahlen und Durchmesser kommen immer aus dem Kernel, nie aus dem Text der KI.**

## 5. PDF und Druck auf macOS

### 5.1 CoreGraphics und PDFKit [G]

Getestet im Scratchpad mit Swift 6.4 und geprüft mit `pdffonts`/`pdfinfo`.

- **CoreGraphics-PDF-Kontext** (`CGContext(url:mediaBox:_:)` mit `beginPDFPage`/`endPDFPage`):
  - Linienbreite, `setLineDash` und `setLineCap` landen exakt als PDF-Befehle: 0,7 mm wird `1.984252 w`, 0,13 mm wird `0.3685 w`.
  - **Linienbreite 0 nie benutzen**: Sie bedeutet laut PDF-Spezifikation „dünnste Gerätelinie“.
  - Text über CoreText bleibt echter Text; die Schrift wird als Teilmenge eingebettet.
  - ⌀ und andere Zeichen außerhalb von MacRoman kommen in eine zweite Teilmenge mit ToUnicode und sind durchsuchbar.
  - **Gemischte Formate in einer Datei** (A4 hoch, dann A3 quer) über `kCGPDFContextMediaBox` je Seite.
  - Titel, Autor und Ersteller kommen an.
  - Inhaltsverzeichnis: dokumentiert über PDFKit `PDFOutline` nachträglich, im Test ohne Verlust. `CGPDFContextSetOutline` funktioniert ebenfalls, aber ohne dokumentierte Schlüssel.
- **Schraffur:**
  - **Clip-Pfad plus Linien** ist reiner Vektor und in jedem Viewer gleich.
  - `CGPattern` wird ein PDF-Kachelmuster, das am Grund-Koordinatensystem hängt; Quartz darf die Zelle je Gerät anpassen ([Quartz-2D-Leitfaden](https://developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/drawingwithquartz2d/dq_patterns/dq_patterns.html)). Nicht verwenden.
- **SwiftUI `ImageRenderer`** ([Doku](https://developer.apple.com/documentation/swiftui/imagerenderer/render(rasterizationscale:renderer:)), ab macOS 13):
  - `Text`, `Path` und `Canvas` werden Vektor und echter Text; AppKit-gestützte Ansichten werden gerastert.
  - **Falle:** `.font(.custom(name, size: 13.46))` landet als 13 pt. Exakte Größen gibt es nur mit `.custom(_:fixedSize:)`.
  - Seitenaufteilung macht man selbst.
  - Gut für Berichte und Bauplanseiten mit Layout, unnötig für Zeichnungsblätter.

### 5.2 Druck [G]

- **`PDFDocument.printOperation(for:scalingMode:autoRotate:)`** ([Doku](https://developer.apple.com/documentation/pdfkit/pdfdocument/printoperation(for:scalingmode:autorotate:))), getestet mit Ausgabe in eine Datei:
  - **`.pageScaleNone`** druckt A4 exakt 1:1.
  - **`.pageScaleToFit`** verkleinert selbst A4 auf A4 auf 97,18 %, weil der bedruckbare Bereich rund 3 mm Rand hat. Damit stimmt kein Maßstab mehr.
  - Den Rahmen nach ISO 5457 (20/10 mm) erhält der 1:1-Druck. Ränder echter Drucker sind nicht gemessen.
- **Ein Druckauftrag hat genau eine Papiergröße.**
  - A3 auf einem A4-Auftrag kam gedreht und abgeschnitten.
  - Gemischte Formate bietet macOS erst ab 15 mit AirPrint-Druckern, die PDF verstehen ([Apple Support](https://support.apple.com/en-gb/126267)).
  - Daher **je Blattformat ein Auftrag**.
- **`NSPrintOperation` mit eigener NSView** (`knowsPageRange`, `rectForPage`) bringt keinen Vorteil gegenüber dem PDF-Weg (nicht getestet).
- **Aus SwiftUI:** PDF erzeugen, dann die PDFKit-Druckoperation ([Apple-Forum](https://developer.apple.com/forums/thread/763719)).
  - Menüpunkt über `CommandGroup(replacing: .printItem)`.
  - Skalierungsfeld im Dialog ausblenden.
  - Die Sandbox-Berechtigung `com.apple.security.print` ist unnötig, weil Kev CAD ohne Sandbox läuft (`app/project.yml`).

### 5.3 Schriften für ISO 3098

| Schrift | Lizenz | Urteil |
|---|---|---|
| **osifont** ([GitHub](https://github.com/hikikomori82/osifont)) | Varianten GPL-3, GPL-2 oder **LGPL-3, jeweils mit Font-Ausnahme**; `fsType 0` (Einbetten erlaubt) | **Erste Wahl.** FreeCAD liefert `osifont-lgpl3fe.ttf` mit (lokal in `/Applications/FreeCAD.app/…/TechDraw/Resources/fonts/`) |
| ISOCPEUR | „Copyright Autodesk, All rights reserved“ | proprietär, nicht verwenden |
| D-DIN (Datto) | SIL OFL 1.1 | DIN 1451, nicht ISO 3098; für Bauplan und Berichte denkbar |
| Alte DIN 1451 Mittelschrift (Wiegel) | Angaben widersprüchlich (OFL, CC BY-SA, „Freeware“) | ungeklärt |
| LibreCAD-Schriften (`iso.lff`) | gemischt GPL/OFL | Einstrich-Format, von CoreText nicht nutzbar |

**osifont im Einsatz** [G]:

- **Versalhöhe** ist 0,737 des Schriftgrads. Für h = 3,5 mm also **13,46 pt**, für 2,5 mm 9,61 pt, für 5 mm 19,23 pt.
- **Zeichenvorrat** der FreeCAD-Fassung: Ø, ±, °, ⌀ und weitere CAD-Symbole sowie ÄÖÜß. Es fehlen ∥, ⟂ und →; ob die GitHub-Fassung vom Januar 2026 sie hat, ist [offen].
- **Registrieren:** `CTFontManagerRegisterFontsForURL(…, .process, …)` funktioniert. Alternativ `ATSApplicationFontsPath` in der Info.plist (nicht getestet).

### 5.4 Umweg über SVG im Kernel

- **`rsvg-convert -f pdf`** [G]:
  - Erzeugt echte Strichmuster und Clips, mehrere Seiten mit eigenem Format, etwa 75 ms je Seite.
  - **Ersetzt aber eine nicht installierte Schrift stillschweigend durch Helvetica.** Erst mit `PANGOCAIRO_BACKEND=fc` und eigener Fontconfig kommt osifont an.
  - Braucht Homebrew-Bibliotheken (LGPL).
- **build123d `ExportSVG`** [G]:
  - Hat ISO-Linientypen.
  - Text wird zu Umrissen (nicht durchsuchbar), die SVG-Größe ist der Begrenzungsrahmen statt des Blatts.
  - Box mit Bohrung samt Schriftfeld: 4,6 s.
- **CairoSVG** (LGPL-3) scheitert an der Schrift wie rsvg. svglib ist LGPL-3, nicht BSD.
- **Nicht getestet:** reportlab (BSD) und fpdf2 (LGPL-3).
- **Urteil:** Ein zweiter Renderer neben der App liefert nie dasselbe Bild, ist schlecht bearbeitbar und hat Schriftfallen. Höchstens als Zusatzexport (SVG/DXF) für andere Programme.

## 6. Empfehlung für Kev CAD

**Grundsatz:** Der Kernel rechnet Geometrie und Bedeutung, die App zeichnet und bearbeitet. Es gibt genau eine
Zeichenfunktion für Bildschirm, PDF und Druck. Maße hängen an 3D-Merkmalen, nie an projizierten Kanten. Das deckt sich
mit D1 bis D10 im Plan.

1. **Dokumente als JSON im Projekt** (wie DOKUMENTE.md). Erzeugte Vektoren werden nicht gespeichert, nur Absicht und
   Nutzeränderungen. Damit wirken Versionen und Varianten automatisch auch auf Zeichnungen.
2. **Projektion im Kernel, Netz als Standard:**
   - `HLRBRep_PolyAlgo` mit feiner Vernetzung, etwa 0,05 mm oder relativ zur Blattgröße.
   - Segmente zusammenfassen, Doppelte zwischen sichtbar und verdeckt streichen, degenerierte Kanten filtern.
   - Exakt nur für Einzelteilblätter, in einem eigenen Prozess mit Zeitbudget; danach optional Kreisbögen einpassen.
   - Zwischenspeicher je Formschlüssel und Ansicht.
   - **Schätzung 3–5 PT**, ein Teil steht auf `phase6-b`.
3. **Linienarten nach ISO 128 als feste Tabelle:** sichtbar, verdeckt, mitte, dünn (Lichtkanten), schnitt, schraffur,
   dazu ergänzend Nachbarteil (05.1) und Bruchlinie. Liniengruppe 0,5, Strichlängen als Vielfache von d.
   **0,5 PT.**
4. **Merkmalerkennung je Teil** (Bohrung, Senkung, Gewinde mit Gegenstück, Langloch, Tasche, Fase, Radius, Lochbild,
   Stange mit Gehrung). Jedes Merkmal bekommt eine Signatur im lokalen Teilsystem. **5–8 PT**, weit fortgeschritten auf
   `phase6-b`.
5. **Zeichnungsvorlagen je Teiletyp** (Tabelle in 2.5 Punkt 1). Sie bestimmen Ansichten, Bezug und Bemaßungsstrategie.
   Das wiegt mehr als jede generische Automatik. **3–4 PT.**
6. **Ansichtenwahl und Blattaufbau:**
   - Hauptansicht nach Wertung, weitere Ansichten über Mengenüberdeckung, Schnitt bei Innenmerkmalen, Einzelheit bei
     kleinen Merkmalen unter einer Mindestgröße auf dem Blatt.
   - Maßstab aus der ISO-Reihe, Format A4/A3, Anordnung nach Projektionsmethode 1.
   - **4–6 PT.**
7. **Bemaßungsplaner:**
   - Je Achse ein Graph mit Spannbaum ab dem Bezug.
   - Lochbilder zusammenfassen, Ø/R/□/Fase/Gewinde nach ISO 129-1 und 6410.
   - Jedes Maß einmal je Blatt.
   - Kreise im Graphen und fehlende Lagemaße werden Befunde.
   - **8–12 PT.**
8. **Platzierung in zwei Stufen** (Reihen 10/7 mm, dann Annealing) und Prüfungen auf Überlappung, Rahmen und
   Vollständigkeit. **4–6 PT.**
9. **Bezüge, die Modelländerungen überleben:**
   - Teilname, dann Merkmalskennung, dann Signatur mit Toleranz.
   - Ist die Zuordnung mehrdeutig, wird das Maß „verwaist“ und rot, nie still falsch.
   - Nutzer-Maße sind fest; **ihr Versatz ist relativ zum Anker gespeichert**.
   - **Gelöschte Auto-Maße werden als Unterdrückung gespeichert** (Merkmal plus Maßart), damit sie beim nächsten Lauf nicht wiederkommen.
   - **4–6 PT.**
10. **Schnitte, Einzelheiten, Zusammenbau:**
    - Schnittflächen per `split`, Normteile ungeschnitten, Schraffur je Teil wechselnd.
    - Positionsnummern mit Hinweislinie und Punkt, Stücklistentabelle aus `bom`, Zusammenbau ohne verdeckte Kanten.
    - **6–9 PT.**
11. **Blatt-Renderer in der App:**
    - Eine CoreGraphics-Funktion `zeichne(blatt, in: CGContext)`; Text über CoreText mit osifont in exakter Punktgröße.
    - Schraffur als Clip plus Linien; Rahmen, Schriftfeld (ISO 7200 plus Projektionssymbol), Feldeinteilung ab A3.
    - Am Bildschirm in einer NSView bzw. `Canvas` mit `withCGContext`, optional mit 1-px-Mindestbreite nur fürs Display.
    - **4–6 PT.**
12. **Bearbeiten in der App:**
    - Maß ziehen, Text verschieben, löschen, neu (zwei Elemente anklicken, der Kernel findet das nächste Merkmal).
    - Notiz mit Zeiger, Ansicht verschieben oder neu, Maßstab, Schriftfeld.
    - Jede Änderung geht als `DRAWING_EDIT` an den Kernel, die Antwort kommt als neues `DRAWING`, Rückgängig über die Versionen.
    - **6–10 PT.**
13. **PDF, Druck und Berichte:**
    - Dieselbe Zeichenfunktion in einen PDF-Kontext, Formate je Seite gemischt, Outline über `PDFOutline`.
    - Berichte (Stückliste, Teileliste, Einkaufsliste, Zuschnitt, Druckteile) als Tabellen mit eigener Seitenaufteilung, per CoreText oder `ImageRenderer` mit `fixedSize`-Schriften.
    - Drucken nur mit `.pageScaleNone`, je Format ein Auftrag.
    - Export-Dialog mit Bausteinen und Vorlagen.
    - **6–9 PT.**
14. **Bauplan im Kernel:**
    - **Gerüst:** Material und Einkauf aus `bom` und Bestand, Zuschnitt aus dem Zuschnittplan, Bohren aus den Merkmalen (Bohrbild ab Bezugskante, Bohrer-Ø, Kernloch, Senkung), Drucken aus `druckteil` mit Ausrichtung.
    - **Montage nach Agrawala:**
      - Demontage über Hauptteile mit Fügerichtungen aus den Bedingungen; Verbinder aus `verbinde(mit=…)` als Sekundärteile.
      - Symmetriegruppen zusammen, Wiederholungen als „×n“.
      - Kamera mit Sichtbarkeitsschwellen 50/10/25/35 % über den ID-Puffer.
      - Strichbilder auf dem Netz.
    - **Reihenfolgen speichern:** „a vor b“ wird gespeichert, damit Entscheidungen von Kevin oder dem Agenten bei Mehrdeutigkeit stabil bleiben.
    - **10–15 PT.**
15. **Durchspielen und Prüfung je Schritt:**
    - Neue Teile fahren über die Animation ein; `kollision_pruefen` prüft den Weg.
    - Werkzeug-Nutzvolumen je Werkzeugtyp gegen den Stand des Schritts; Standsicherheit je Zwischenstand.
    - Befunde am Schritt.
    - Dazu MCP-Werkzeuge nach DOKUMENTE.md und ein Skill-Abschnitt.
    - **8–12 PT.**

**Gesamt grob 75–115 Personentage** eines erfahrenen Entwicklers ohne KI. Das ist eine **Schätzung**, nicht belastbar.
Mit parallelen Agenten-Strängen schrumpft die Kalenderzeit stark. Der Prüf- und Abstimmungsaufwand bei Kevin bleibt,
vor allem für Bemaßung und Bauplan, und ein echter Probeaufbau gehört dazu (wie bei Heiser et al.).

**Wiederverwendung:**

| Baustein | Herkunft | Lizenz |
|---|---|---|
| Projektion | OCCT über OCP | LGPL-2.1 mit Ausnahme, als Bibliothek |
| Linientypen und Schriftfeld-Ideen | build123d | Apache-2.0 |
| Reihen, Hinweislinien, Prüfungen | text-to-cad | MIT |
| Bezugs-Neuzuordnung | FreeCAD | LGPL; nur das Verfahren neu geschrieben |
| Schrift | osifont | LGPL-3 mit Font-Ausnahme |
| DXF-Zusatzexport | ezdxf | MIT |
| Explosion, Sichtbarkeit, Werkzeug-Nutzvolumen | Agrawala, Li, Wilson | Verfahren aus den Veröffentlichungen |
| Kollision, Animation, Bedingungen, Stückliste, Bestand, Offscreen-Renderer | Kev CAD | vorhanden |

## 7. Abgleich mit Plan und Vertrag auf `phase6`

1. **HLR-Weiche ändern.** `POLY_AB_FLAECHEN = 60000` in `zeichnung/projektion.py` fängt die gemessenen Ausreißer nicht
   ab: 36 Flächen brauchen 81 s. Daher Netz als Standard und exakt nur mit Zeitbudget im eigenen Prozess (3.4).
   Den Rost aus 3.2 als Testfall aufnehmen.
2. **Unterdrückung gelöschter Auto-Maße** in DOKUMENTE.md aufnehmen. Etwa `unterdrueckt: [{merkmal, art}]` je Blatt;
   `mass_loeschen` auf ein Auto-Maß schreibt dorthin. Sonst erzeugt der nächste Lauf das Maß neu.
3. **Schriftfeld nach ISO 7200 vervollständigen.** Es fehlen Blattnummer und Blattanzahl, Dokumentart (etwa
   „Fertigungszeichnung“, „Zusammenbauzeichnung“), Eigentümer und Freigebender. Dazu das Projektionssymbol neben dem
   Maßstab.
4. **Linienarten ergänzen** um `nachbar` (05.1, etwa für Endlagen von Gelenken) und `bruch` (Freihand, für lange
   Rohre in kurzer Ansicht).
5. **Druck:** Vertrag und App mit `.pageScaleNone`, je Blattformat ein Druckauftrag. Ein Hinweis im Dialog, falls
   Formate gemischt sind.
6. **Schrift festlegen:** osifont (LGPL-Variante) im App-Bundle, Schriftgrößen aus der Versalhöhe (3,5 mm = 13,46 pt).
7. **Bauplan:**
   - `bild` um die gemessene Sichtbarkeit der neuen Teile ergänzen, damit die Prüfung „Teil verdeckt“ melden kann.
   - Reihenfolgen „a vor b“ als eigene Liste aufnehmen.
   - Werkzeuge mit Nutzvolumen im Katalog führen.
8. **Normlücken als einstellbare Hausregeln führen:** Maßlinienabstand 10/7 mm, Schraffurabstand, Pfeil 15° mit
   Länge 10d. Nicht als „ISO“ ausweisen.

## Nicht geprüft

- **Normvolltexte:** die heutigen Ausgaben von ISO 128-2/-3:2022, ISO 129-1:2018, ISO 6433, ISO 7573, ISO 15065,
  DIN 336 und IEC/IEEE 82079-1, sowie die Symbolmaße der Projektionsmethode.
- **Volltexte der Literatur:** Chen 2001, Yu 1994, Bekos 2007, Wilson 1994, Homem de Mello 1990, Schumacher 2013.
- **Andere Programme:** Ergebnisqualität von Fusion, SolidWorks und Onshape im eigenen Test; eine wissenschaftliche
  Arbeit zur Ansichtenwahl (keine gefunden).
- **OCCT:** ob `HLRBRep_Algo` mehrere Kerne nutzt oder sich abbrechen lässt; die Ursache der Ausreißer im OCCT-Code
  (beobachtet ist nur, wann sie auftreten).
- **Sonstiges:** Ränder echter Drucker; Code-Verfügbarkeit von ASAP und Assemble Them All; die Rechtslage der
  LEGO- und Autodesk-Patente.
