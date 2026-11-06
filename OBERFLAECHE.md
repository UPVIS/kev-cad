# Kev CAD V2 · Oberfläche (Paket V2-3)

Stand 05.11.2026, Zweig des Pakets V2-3 (wird auf `v2` zusammengeführt). Grundlage: [PLAN-V2.md](PLAN-V2.md)
(Entscheidungen V3 bis V7 und V10) und der Gestaltungsentwurf in [docs/v2-entwurf/](docs/v2-entwurf/README.md).
Kevins Wahl vom 05.11.2026: Richtung **Graphit**, dazu aus **Sucher** der rote Rahmen beim Sprechen und nummerierte
Kacheln; Zeichnungsblätter im Stil **Reißbrett** (helles Blatt).

## 1. Bestand: die Oberfläche vor V2

Was es in `app/Sources/KevCAD` gab und was in V2 daraus wird. „Bleibt“ heißt: Der Baustein lebt weiter, eingebettet in
die neue Oberfläche. „Wird Kachel“ heißt: Er erscheint auf Zuruf in der Kachelfläche der Werkstatt. „Fliegt aus der
Grundansicht“ heißt: Es gibt ihn noch, aber nicht mehr ständig im Bild, sondern über Menü, Taste oder Werkstatt.

| Baustein (Datei) | Heute | V2 |
|---|---|---|
| `KevCADApp` (App/KevCADApp.swift) | Szenen Willkommen (startet zuerst), Projekt, Protokoll, Lagerkatalog, Zukaufteil | bleibt, umgebaut: Das Hauptfenster startet sofort mit einem leeren Projekt; Protokoll, Lagerkatalog und Zukaufteil bleiben Nebenfenster |
| `AppSession` (App/AppSession.swift) | Projekte öffnen und anlegen, „Zuletzt geöffnet“, Fenster wechseln | bleibt, erweitert um den Entwurf (leeres Projekt ohne Dialog) und Umbenennen |
| `WelcomeView`, `RecentProjectsList`, `ClaudeHint` (Welcome/) | Willkommensfenster: Neues Projekt, Öffnen, Hinweis zu Claude, Liste der letzten Projekte | entfällt; ersetzt durch die Startübersicht im Hauptfenster (Overlay „Zuletzt geöffnet“); der Befehl für Claude Code steht im Hilfe-Menü |
| `NewProjectSheet` (Welcome/) | Blatt „Neues Projekt“ mit Name, Vorlage, Ordner | entfällt: ⌘N öffnet sofort ein leeres Projekt, den Namen gibt man per Doppelklick auf den Titel |
| `ProjectWindow` (Project/ProjectWindow.swift) | NavigationSplitView: Teilebaum, Viewport, Inspektor; Bereiche 3D, Dokumente, Material, Simulation (⌘1 bis ⌘4); Werkzeugleiste | ersetzt durch das Hauptfenster mit **Fokus** und **Werkstatt**; die Bereiche werden Kacheln |
| `ProjectToolbar` | Neu rechnen, Auto-Lauf, Zeitlupe, Standardansichten, Darstellung, Schnitt, Messen, Bedingungen, Explosion, Bild, Export, Stückliste, Inspektor | fliegt aus der Grundansicht: alles im Menü und per Taste; oben rechts bleiben Foto, Video, Messen, Isolieren, An den Rand |
| `ViewportArea` (Project/) | Viewport mit Bändern (Fehler, Zukauf, Scan, Inventar, Freigabe, Prüfung), Laufanzeige, Schnittleiste, Messhinweis, Agentenkapsel, Leerzustand | bleibt als Fläche des Viewers; die Agentenkapsel wird zur Agentenspur, der Leerzustand zu „Was soll entstehen?“ |
| `PartTreeView` (Panels/) | Systemliste mit Suche, Kameras, Kontextmenü | wird **Gliederung**: eigene Zeilen nur mit Gruppen und Objekten, Anzahl, Punkt bei Befund, Doppelklick benennt um; Kameras in der Werkstatt |
| `InspectorView` (Panels/) | Kameras, Auswahl, Eigenschaften, Lagerteil, Zukauf, Bedingungen, Referenzen, Statik, Topologie, Messungen, Projekt | fliegt aus der Grundansicht; die Werkstatt zeigt **Eigenschaften** neu (Name, Werte, Maße mit „vorher“); der ganze Inspektor wird Kachel **Details** |
| `StatusBar` (Panels/) | Kernel, Lauf, Teile, Dreiecke, Agent | wird Baustein **Statuszeile** der Werkstatt; im Fokus steht nur die Agentenspur |
| `SchnellansichtenBereich` (Material/) | Stückliste, Zuschnitt und Druck kompakt unter dem Viewport | wird Kachel (**Stückliste**, **Zuschnitt**, **Druck**) |
| Bereich Material (`MaterialBereich`, `MaterialSeitenleiste`, `MaterialInspektor`, `MaterialToolbar`) | Übersicht, Stückliste, Zuschnitt, Einkauf, Bestand, Zukauf, Druck | wird Kachel **Material** (ganz eingebettet) |
| Bereich Dokumente (`DokumenteBereich`, `DokumenteSeitenleiste`, `BlattInspektor`, `BauplanInspektor`, `BerichteInspektor`, `DokumenteToolbar`) | Zeichnungsblätter, Bauplan, Berichte | wird Kachel **Zeichnung** (Blatt, Bauplan und Berichte über das Menü der Kachel; Seitenleiste und Inspektor in der Kachel) |
| Bereich Simulation (`SimulationSeitenleiste`, `SimulationInspektor`, `SimulationErgebnisAnsicht`, `SimulationToolbar`) | Lastfälle, Kräfte, Lager, Rechnen, Ergebnisse | wird Kachel **Simulation**; die Werkzeugleiste für Kräfte und Lager bleibt im Viewer |
| `VersionenLeiste`, `VariantenMenu`, `VergleichKarte` (Versionen/) | Seitenleiste neben dem Viewport, Variantenmenü in der Titelleiste, Vergleich im Viewport | Leiste wird Kachel **Versionen**; Varianten im Projektmenü; die Vergleichskarte bleibt im Viewer |
| `AnimationTimeline` (Animation/) | Zeitleiste unter dem Viewport, nur mit Animation | Kachel **Animation** (Streifen unten); im Fokus über dem Viewer, auf Zuruf oder beim Abspielen |
| Bänder `ErrorBanner`, `InventoryBanner`, `FreigabeBand`, `PruefBanner`, `ZukaufBanner`, `ScanBand`, `BuchungsBand` | oben im Viewport | bleiben oben im Viewer; Befunde am Teil kommen mit V2-5 |
| Dialoge: Gebaut, Bestand erfassen, Gedruckt, Spule, Freigabe, Referenz hinzufügen, Vermessen, Maßstab, Rendern, Drucken, Drucker-Einstellungen, Dokumente exportieren, Meilenstein, Variante | Blätter und Dialoge | Rendern ist seit V2-7 die Kachel **Rendern**; die übrigen bleiben Blätter und Dialoge (V2-8): kurz und selten, eine Kachel machte sie nur umständlicher. „Dokumente exportieren“ hat drei feste Spalten mit Vorschau und braucht 1000 pt Breite, in einer Kachel wäre es enger als im Blatt |
| `LogWindow`, `CatalogWindow`, `ZukaufDialogWindow` | eigene Fenster | bleiben Nebenfenster |
| `FotoAnsichtOverlay`, `AbweichungLegende`, `MassstabLeiste`, `DurchspielenLeiste`, `SimulationWerkzeugLeiste` | im Viewport | bleiben im Viewer |
| Menüs: `KevCADCommands`, `MaterialCommands`, `DokumenteCommands`, `DokumenteExportCommands`, `AnimationCommands`, `VersionenCommands`, `StockCommands`, `BestandCommands`, `ZukaufCommands`, `RenderCommands`, `SimulationCommands`, `SidebarCommands`, `InspectorCommands` | Ablage, Darstellung (Bereiche ⌘1 bis ⌘4, Schnellansichten ⌃⌘1 bis ⌃⌘3, Blender-Tasten), Modell, Dokumente, Material, Animation, Versionen, Simulation, Hilfe | neu geordnet, siehe Abschnitt 7 |
| `KeyboardGuard`, `WindowHook` (App/) | einbuchstabige Kürzel nicht in Textfeldern; Testfenster auf den zweiten Monitor | bleiben; `WindowHook` kennt zusätzlich das schmale Fenster am Rand |
| `DemoActions`, `DemoViewport` (Demo/) | Demomodus ohne Kernel | bleiben, setzen auch die neuen Aktionen um |
| Selbsttests (`KEVCAD_SELFTEST=…`) | starten aus dem Willkommens- bzw. Projektfenster | bleiben, starten aus dem Hauptfenster; alle nacheinander mit `tools/fern/selbsttests.sh` |

## 2. Gestaltungssystem

Alle Werte stehen in `app/Sources/KevCAD/Gestaltung/Gestaltung.swift` (`Gestaltung.Farbe`, `.Schrift`, `.Abstand`,
`.Radius`, `.Bewegung`, kurz `GF`, `GS`, `GA`, `GR`, `GB`). Kein Baustein setzt eigene Farben oder Größen. Eine andere
Richtung tauscht diese Datei und drei eigens gezeichnete Bausteine: `GraphitGrund`, `KachelNummer`, `Sprechrahmen`.

| Baustein | Datei | Zweck |
|---|---|---|
| `KevKnopfStil` (`rund`, `kopf`, `text`, `breit`, `leise`), `SymbolKnopf`, `AufnahmeKnopf` | Gestaltung/Knopf.swift | Knöpfe; echte SwiftUI-Knöpfe, daher Tastatur, Fokusring (Lichtblau) und VoiceOver |
| `ModusUmschalter` | Gestaltung/Knopf.swift | Blickrichtung der zweiten Ansicht (bis V2-9 auch Fokus/Werkstatt) |
| `Tastenkappe`, `TastenHinweis` | Gestaltung/Knopf.swift | Tasten in Hinweisen, mit gesprochenem Namen für VoiceOver |
| `GliederungsZeile` | Gestaltung/Zeilen.swift | Zeile der Gliederung: Pfeil, Name, Anzahl, Punkt bei Befund oder Markierung, Umbenennen im Feld |
| `EigenschaftsFeld` | Gestaltung/Zeilen.swift | Titel, Wert, Einheit oder „vorher …“ in Messing; bearbeitbar mit Zeilenschalter, esc verwirft |
| `AbschnittTitel` | Gestaltung/Zeilen.swift | Überschrift in Spalten und Karten |
| `KachelRahmen`, `KachelNummer` | Gestaltung/Rahmen.swift | Kachel mit Nummer, Titel, Untertitel, „groß“, „schließen“; durchsichtig für den Viewer |
| `OverlayKarte` | Gestaltung/Rahmen.swift | Karte über allem (Startübersicht), mit Unschärfe dahinter |
| `Statuszeile`, `SprechKnopf` | Gestaltung/Rahmen.swift | Zeile mit Sprechen, zuletzt Gesagtem, Agent und Stand; seit V2-9 nur im Gestaltungsmuster, der Sprechknopf im schmalen Fenster |
| `GraphitGrund`, `Sprechrahmen`, `AtmenderPunkt` | Gestaltung/Rahmen.swift | Grund des Fensters, roter Rahmen beim Sprechen, Punkt „läuft gerade“ |

Text, der direkt im Bild steht, bekommt `textImBild()` (weicher Schatten). Die Musterseite aller Bausteine zeigt die App
mit `KEVCAD_MUSTER=1`.

Abweichung vom Entwurf: Die Kopfleiste ist 32 pt hoch und an der Ampel ausgerichtet. macOS 26 setzt die Ampel bei
versteckter Titelleiste auf 16 pt Höhe; ein Verschieben der Ampel (wie Electron es tut) bricht bei jeder
Größenänderung und verdeckt Klicks. Runde Knöpfe sind deshalb 30 statt 34 pt groß.

## 3. Start ohne Dialog: der Entwurf

- Beim Start zeigt das Hauptfenster sofort das leere Projekt („Neues Projekt · noch nicht gesichert“, „Was soll
  entstehen?“) und darüber die Startübersicht „Zuletzt geöffnet“, sofern es Projekte gibt.
- Ist der Kernel bereit und hat 0,35 s danach niemand ein Projekt geöffnet, legt die App einen **Entwurf** an
  (`PROJECT_NEW` mit der leeren Vorlage). Der Agent sieht ihn in `status` als Projekt „Neues Projekt“ und kann sofort
  darin bauen; `project_new` und `project_open` funktionieren unverändert.
- Ort: `~/Library/Application Support/<Bundle-ID>/Entwürfe/<JJJJ-MM-TT HH.MM.SS>/Neues Projekt/`, je Variante getrennt.
  Nichts davon liegt in ~/Documents/Kev CAD.
- **Leer** heißt: `model.py` unverändert seit dem Anlegen (Prüfsumme in `.kevcad/entwurf.json`), keine weiteren
  Dateien außer dem, was der Kernel selbst anlegt. Leere Entwürfe räumt die App weg: beim Start, beim Wechsel in ein
  anderes Projekt (nach 1,5 s, wenn der Kernel umgezogen ist) und beim Beenden. Ohne Marke gilt ein Entwurf nie als leer.
- **Mit Inhalt** bleibt ein Entwurf liegen und steht in der Startübersicht („Entwurf · ohne Namen“). Pfade ändern sich
  nie von selbst, damit der Agent seinen Pfad aus `status` nicht verliert.
- **Namen** gibt Kevin per Doppelklick auf den Titel oder mit ⇧⌘S („Sichern unter …“). Ein Entwurf zieht dabei nach
  ~/Documents/Kev CAD/<Name> (ohne Namenskollision), ein benanntes Projekt wird im selben Ordner umbenannt; danach
  öffnet der Kernel es am neuen Ort. Während eines Laufs wartet das Benennen.
- ⌘N legt sofort einen neuen Entwurf an (kein Formular). Ist das offene Projekt schon ein leerer Entwurf, bleibt es.
- Wiederherstellen nach einem automatischen Update, Selbsttests mit eigenem Projekt und der Demomodus legen keinen
  Entwurf an.
- `KEVCAD_PROJECTS_DIR` setzt den Projektordner für App und Kernel (Testvarianten schreiben so nicht in Kevins Ordner).

## 4. Viewer, Leisten und Kopfleiste

Seit V2-9 (Kevin, 06.11.2026: „den Unterschied zwischen Fokus und Werkstatt müssen wir nicht machen … Es gibt ja eine
linke und eine rechte Seitebar“) gibt es keine Modi mehr. `OberflaechenZustand` führt `leisteLinks`, `leisteRechts` und die
Kacheln; ob Kacheln nebeneinander stehen (`kachelflaeche`), folgt daraus: andere Kacheln als das Modell offen und das Modell
nicht groß. `modus` ist nur noch abgeleitet (für ältere Agenten und LAGE), `.modus(.fokus)` bzw. `.modus(.werkstatt)` gehen
weiter.

- **Viewer allein**: Er reicht bis an die Oberkante, die Kopfleiste schwebt ohne eigenen Grund darüber. Links die
  Gliederung leise im Bild (linke Leiste an), unten Kevins Live-Text (sobald er spricht), rechts unten die Agentenspur. Keine
  Tafeln. Die Zeitleiste steht nur auf Zuruf (⌃⌘T, `view(zeitleiste=true)`) oder beim Abspielen über dem Viewer; sie liegt
  darüber, damit der Viewer seine Größe behält. Der Achsenwürfel rückt unter die Kopfleiste (`ViewerStore.obenFrei`).
- **Kacheln nebeneinander**: links die Objekte als Spalte (linke Leiste an, Suche ab 13 Teilen), daneben die Kachelfläche.
  Live-Text und Agentenspur stehen über der Kachel „Modell“, fehlt sie, über der Kachelfläche. Keine Statuszeile mehr.
- **Rechte Leiste** (in beiden Fällen): Eigenschaften der Auswahl und Maße des Modells als Insel rechts; der Viewer endet
  davor, damit Einpassen und Achsenwürfel frei bleiben. Leisten brauchen ein Fenster ab 760 pt.
- **Kopfleiste**: neben der Ampel Schalter der linken Leiste und Projektname, rechts die Darstellung wie in Blender
  (Röntgen als Schalter, Drahtgitter, Solid, Material, Technisch, Optionen im Pfeil; ab 900 pt), Foto, Video, Messen,
  Isolieren, An den Rand, ganz außen „Kacheln nebeneinander“ (nur mit weiteren Kacheln) und der Schalter der rechten
  Leiste. Jede Gruppe liegt in einer Kapsel (`GF.insel`), damit sie auch über dem weißen Grund von Technisch lesbar ist. Die
  Knöpfe darin sind 26 pt (`KnopfForm.kopf`). Leere Stellen ziehen das Fenster (`FensterZiehen`), ein Doppelklick zoomt.
- **Text im Bild bei Technisch**: Gliederung, Startzeile, Live-Text und Agentenspur stehen auf dem weißen Grund auf einer
  dunklen Insel wie die Kopfleiste (`InselImHellen` in `FokusEbenen.swift`), der dunkle Verlauf unten entfällt dann.
- **Unten im schmalen Viewer** (Kachel unter 640 pt): links der Sprechknopf (unter 480 pt nur das Mikrofon), die Kapseln
  des Viewers (Prüfung, Messen) rücken nach rechts (`ViewportArea.schmal`); mittig lagen sie über dem Sprechknopf.
- **Gliederung**: nur Gruppen und Objekte. Klick wählt, ⇧ oder ⌘ nimmt dazu, Doppelklick oder Zeilenschalter benennt
  um, ↑ ↓ wandern, ← → klappen. Gruppen mit gewählten Teilen öffnen sich von selbst. Umbenennen ändert die Namen in
  model.py (`ModellQuelle.benenneUm`): genau die Zeichenketten in `show()`, `verbauen(name=…)`, `befestigt(…)`; entsteht
  ein Name im Code, sagt die Kopfleiste, dass der Agent das übernimmt.
- **Eigenschaften**: Lagerteil, Länge, Maße, Werkstoff, Masse; Isolieren und Zeigen; darunter „Maße des Modells“: alle
  `param()`-Werte als Felder. Ein geänderter Wert landet in model.py (`ModellQuelle.setzeParameter`, nur bei genau
  einem `param("name", Zahl)`). „vorher …“ zeigt, was sich im letzten Lauf geändert hat, egal ob durch Kevin oder den
  Agenten.
- **Agentenspur**: die Schritte des Agenten aus `AppModel.agentenspur` (V2-5, `spur-1`): Absicht vor der Beschreibung,
  fertige mit Dauer, der laufende zählt mit. Dazu das Ende jedes Laufs, den kein Schritt nennt, und die Befunde der
  Prüfung; ältere Kernel liefern nur die Tätigkeitszeile (`agentActivity`). Höchstens sechs Einträge. Das Hauptfenster
  hält `AgentenSpur` mit `@State`, nur die Spur-Ansichten beobachten sie.
- **Sprechen** (V2-6, Vertrag in PROTOCOL.md, „V2-6 Sprach-Feedback“, Steuerung `Sprache/SprachSteuerung.swift`): V beginnt
  eine Sitzung, der Rahmen wird rot, der Text läuft unten mit (`AppModel.sprache`, eigener Speicher, damit nicht jedes Wort
  das Hauptfenster auswertet). Solange Kevin spricht, zeichnet Ziehen mit der linken Maustaste einen Strich aufs Modell;
  Klicken wählt weiter aus, Drehen bleibt bei der mittleren Taste und ⌥ links. V hält an und lässt die Sitzung offen, ↩
  schickt alles an den Agenten, esc verwirft es. ↩ wirkt im ganzen Fenster, nur Textfelder und Dialoge gehen vor. Während
  Kevin spricht, passt ein Lauf die Ansicht nicht ein. Erkannt wird mit Wortlaut, Rückfall ist Apples Erkennung.
- Der Viewer wird nie neu angelegt: Er steht an fester Stelle im Ansichtsbaum, nur sein Rahmen wechselt (ohne
  Animation). Er kommt erst nach dem ersten Bild dazu, damit Metal das Fenster nicht aufhält. Verdeckt (Kacheln ohne
  Kachel „Modell“, andere Kachel groß) ruht er (`isPaused`). Seine runden Ecken neben Kacheln setzt die Metal-Ebene
  selbst (`cornerRadius`), kein `.clipShape`: Eine Formmaske zwingt das Fenstersystem, jedes Bild abseits zusammenzusetzen.
- Die Kachelfläche bleibt nach dem ersten Öffnen eingehängt und wird ohne Kacheln nur ausgeblendet, mit den Maßen von
  zuletzt.
  So baut das Umschalten keine Tabellen ab und auf, und beim Schieben an den Rand wird nichts neu vermessen.

## 5. Kacheln

- Arten: Modell, Zeichnung, Bauplan, Stückliste, Zuschnitt, Druck, Animation, zweite Ansicht, Material, Simulation,
  Versionen, Details, Rendern. Höchstens vier zugleich, nummeriert 1 bis 4; eine fünfte verdrängt die älteste außer dem
  Modell. Die Animation bringt das Modell mit, denn die Bewegung sieht man dort.
- Anordnung: eine füllt alles; zwei nebeneinander (im Hochformat übereinander); drei mit der ersten links groß und zwei
  rechts übereinander; vier im Raster. Eine große Kachel füllt die Fläche allein. Die Animation ist ein Streifen unten
  über die ganze Breite, darüber der Rest; groß bleibt sie mit dem Modell zusammen, und auch ein großes Modell behält sie.
  Unter 760 pt Breite steht die Zeitleiste in zwei Zeilen, im Fenster am Rand fehlt nichts.
- Eingebettet statt neu geschrieben: Zeichnung = `DokumenteBereich` (breit mit Seitenleiste und Inspektor; Blätter
  wechseln im Kopf der Kachel, das Blatt bleibt hell und liegt auf Planquadraten wie auf einem Zeichenbrett), Bauplan =
  `BauplanBereich` (breit mit Inspektor), Stückliste = `StuecklisteKompaktTabelle` bzw. groß `MaterialStuecklisteAnsicht`,
  Zuschnitt = `MaterialZuschnittAnsicht`, Druck = `DruckAnsicht` (Platten ab 640 pt Breite, „Drucken …“ öffnet nur den
  Dialog), Animation = `AnimationTimeline`, Material = `MaterialBereich` mit Seitenleiste und Inspektor, Simulation =
  Seitenleiste, Ergebnisse, Inspektor, Versionen = `VersionenLeiste`, Details = `InspectorView`, Rendern = `RenderDialog`.
- Zweite Ansicht: ein Bild einer Standardansicht, gerechnet auf einer eigenen Warteschlange (`ZweiteAnsichtRechner`,
  `OffscreenRenderer` ist dafür nicht mehr an den Hauptfaden gebunden). Es entsteht nach jedem Lauf, bei neuer Größe oder
  Richtung und nach jedem Kamerabefehl des Agenten: `view(focus=…)` zeigt dasselbe Ziel aus ihrer Richtung,
  `view(standard=…)` oder `fit` wieder alles. Ein zweiter echter Viewport hätte auf dem Hauptfaden gezeichnet und alle
  Körper ein zweites Mal hochgeladen; dafür bleibt die Ansicht ein Bild ohne Maus.
- Der Agent stellt die Fläche über `view` (PROTOCOL.md, „Fläche“, `VIEW_CMD flaeche`), Skill `kacheln.md`. Eine Kachel holt
  die Kachelfläche dazu; am Rand bleibt das Fenster schmal und die Kacheln stehen übereinander.
- Wer `ProjectWindowState.bereich` setzt (Sprünge aus Stückliste, Teilebaum, Menüs, Selbsttests), holt die passende
  Kachel nach vorn; umgekehrt folgt `bereich` der aktiven Kachel, damit die Kürzel der Bereiche passen.
- Alles über `OberflaechenActions` (Befehle `Oberflaechenbefehl`), damit Sprache (V2-6) und Agent (V2-7) es auslösen.
- Ist eine Kachel groß, bleiben die übrigen in ihrer letzten Größe eingehängt und nur ausgeblendet: „alle einordnen“ baut
  nichts neu auf (gemessen 107 statt 53 ms). Seitenleisten und Inspektoren breiter Kacheln (`NebenSpalte`) bauen sich eine
  Sekunde nach dem Öffnen unsichtbar auf, „groß“ gibt ihnen nur noch Platz.
- Drei Regeln gegen lange Pausen (gemessen bis 15 s, wenn eine davon fehlt): Das Hauptfenster beobachtet das Modell
  nicht, sonst wertet jede Protokollzeile alles neu aus. Rahmen von Kacheln werden nie animiert, sonst vermisst SwiftUI
  Tabellen in jedem Animationsschritt neu. `KachelInhalt` ist `Equatable` (nur Art und Breite zählen), denn seine
  Closures sind bei jeder Auswertung neu. Änderungen an Größe oder Modell gehören in Teilansichten, nie in `@State` des
  Hauptfensters.
- Eingebettete Ansichten nehmen `SuchFeld` statt `.searchable` (das setzt sein Feld in die Fensterleiste) und keine
  `.toolbar`-Einträge.

## 6. An den Rand

⌃⌥→ bzw. ⌃⌥← (oder der Knopf oben rechts): Das Fenster wird 460 pt breit, so hoch wie der sichtbare Bildschirm, am
rechten bzw. linken Rand, und zeigt den Viewer allein ohne rechte Leiste (unter 640 pt rückt er zusammen: ohne Gliederung,
Agent und Sprechknopf unten). Noch einmal stellt Größe, Lage, rechte Leiste und Kacheln von vorher wieder her. Die Bewegung läuft 0,3 s über die
Fensteranimation von AppKit. Beim Beenden geht das Fenster ohne Animation zurück.

## 7. Menüs und Tasten

Menüleiste: Ablage, Bearbeiten, Darstellung, Modell, Kacheln, Agent, Fenster, Hilfe (vorher 15 Menüs). Versionen,
Animation, Simulation, Material, Dokumente und Bauplan sind Untermenüs von Modell (`ModellUntermenues`); ihre Kürzel
gelten weiter.

| Taste | Wirkung |
|---|---|
| ⌘1, ⌘2 | Objekte links, Eigenschaften rechts ein und aus |
| ⌘3 | nur das Modell bzw. Kacheln wieder nebeneinander (nur mit weiteren Kacheln) |
| ⌃⌥→, ⌃⌥← | schmal an den rechten bzw. linken Rand, noch einmal zurück |
| ⌘N, ⌘O, ⇧⌘O | neues leeres Projekt, Öffnen, letzte Projekte zeigen |
| ⇧⌘S | Entwurf sichern bzw. Projekt umbenennen |
| ⌃⌘1 bis ⌃⌘0 | Kachel Stückliste, Zuschnitt, Zeichnung, zweite Ansicht, Material, Simulation, Versionen, Details, Druck, Animation; Bauplan und Rendern im Menü (⌥⌘R) |
| ⌃⌘T | Zeitleiste über dem Viewer zeigen und ausblenden |
| ⌥⌘1 bis ⌥⌘4 | Kachel 1 bis 4 groß und zurück |
| ⇧⌘W | aktive Kachel schließen |
| V | Sprechen an und aus; aus hält an, die Sitzung bleibt offen (im Zeichnungsblatt bleibt V das Auswahlwerkzeug) |
| ↩ | Sitzung offen: fertig, an den Agenten schicken; sonst wie bisher |
| esc | Startübersicht wegschieben, Sitzung verwerfen, sonst wie bisher |

Die Tasten des Viewers stehen in `Commands.swift` und gehören zu V2-4.

## 8. Messwerte

Selbsttest `KEVCAD_SELFTEST=oberflaeche`, Kugelschieber Variante B (134 Teile), Release. „Vorher“ ist der erste Lauf,
„jetzt“ der letzte (05.11.2026). Der Rechner war in allen Läufen stark ausgelastet (Last 50 bis 176).

| Was | vorher | jetzt |
|---|---|---|
| Fenster da (Wanduhr) | 6,65 s | 1,74 s |
| Rechenzeit des Hauptfadens bis zum Fenster | nicht gemessen | 0,90 s |
| leeres Projekt offen (Kernel bereit plus 0,35 s) | 13,5 s | 6,8 s |
| Fokus → Werkstatt, Werkstatt → Fokus mit drei Kacheln | 1651 ms in eine Richtung | 52 ms, 75 ms |
| an den Rand, zurück | 11994 ms, 123 ms | 81 ms, 84 ms |
| Kachel Stückliste öffnen, zweites Mal | 10087 ms | 244 ms, 114 ms |
| Kachel Material groß, zweites Mal | 15555 ms | 391 ms, 293 ms |

Gemessen wird die längste Pause des Hauptfadens. Ohne fremde Last ist der Start nicht gemessen; die Zeit bis zum Fenster
liegt dann nahe der Rechenzeit.

### V2-7: Kacheln vom Agenten

Selbsttest `kernel/tools/kachel_selbsttest.py` (`tools/fern/kachel-selbsttest.sh`): echter Kernel, echte Testvariante,
Kugelschieber Variante B, die Befehle kommen als `view` über MCP; gemessen wird die längste Pause des Hauptfadens im
Lagebild der Testvariante. Mac mini (M4), ohne fremde Last. Der Viewer zeichnet dort nicht auf den Bildschirm, die Pausen
enthalten also den Aufbau der Oberfläche, nicht das Zeichnen des Modells.

| Was | längste Pause |
|---|---|
| Kachel öffnen, zweites Mal: Stückliste, Zuschnitt, Zeichnung, Bauplan, Druck | 103, 50, 29, 89, 60 ms |
| Kachel öffnen, zweites Mal: Animation, zweite Ansicht, Material, Simulation | 35, 30, 65, 132 ms |
| Kachel öffnen, zweites Mal: Versionen, Details, Rendern | 34, 80, 146 ms |
| Werkstatt zum ersten Mal über eine Kachel im Fokus | 155 ms |
| Fokus → Werkstatt, Werkstatt → Fokus | 38 bis 66 ms |
| Kachel 2 groß, alle einordnen | 142, 66 ms |
| an den Rand, zurück | 59, 88 ms |
| zweite Ansicht: andere Richtung, Kamerabefehl, ganzer Lauf | 40, 38, 39 ms |

V2-8: Kachel 2 groß 50 bis 60 ms, alle einordnen 35 bis 42 ms (Nebenspalten vorgebaut), Zahlen in `kernel/tools/MESSUNG.md`.

Bilder der Fenster liefert im Test `VIEW_CMD test_foto` (ohne Viewer): `screencapture` geht über ssh nicht. Fallen beim Bau:
`EmptyView()` in `ViewThatFits` ist kein Kandidat, die letzte echte Ansicht wird dann erzwungen und macht die Kachel breiter
als das Fenster (Kopf der Druckvorschau am Rand).
