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
| `SchnellansichtenBereich` (Material/) | Stückliste, Zuschnitt und Druck kompakt unter dem Viewport | wird Kachel (**Stückliste**, **Zuschnitt**) |
| Bereich Material (`MaterialBereich`, `MaterialSeitenleiste`, `MaterialInspektor`, `MaterialToolbar`) | Übersicht, Stückliste, Zuschnitt, Einkauf, Bestand, Zukauf, Druck | wird Kachel **Material** (ganz eingebettet) |
| Bereich Dokumente (`DokumenteBereich`, `DokumenteSeitenleiste`, `BlattInspektor`, `BauplanInspektor`, `BerichteInspektor`, `DokumenteToolbar`) | Zeichnungsblätter, Bauplan, Berichte | wird Kachel **Zeichnung** (Blatt, Bauplan und Berichte über das Menü der Kachel; Seitenleiste und Inspektor in der Kachel) |
| Bereich Simulation (`SimulationSeitenleiste`, `SimulationInspektor`, `SimulationErgebnisAnsicht`, `SimulationToolbar`) | Lastfälle, Kräfte, Lager, Rechnen, Ergebnisse | wird Kachel **Simulation**; die Werkzeugleiste für Kräfte und Lager bleibt im Viewer |
| `VersionenLeiste`, `VariantenMenu`, `VergleichKarte` (Versionen/) | Seitenleiste neben dem Viewport, Variantenmenü in der Titelleiste, Vergleich im Viewport | Leiste wird Kachel **Versionen**; Varianten im Projektmenü; die Vergleichskarte bleibt im Viewer |
| `AnimationTimeline` (Animation/) | Zeitleiste unter dem Viewport, nur mit Animation | bleibt unter dem Viewer (Kachel in V2-7) |
| Bänder `ErrorBanner`, `InventoryBanner`, `FreigabeBand`, `PruefBanner`, `ZukaufBanner`, `ScanBand`, `BuchungsBand` | oben im Viewport | bleiben oben im Viewer; Befunde am Teil kommen mit V2-5 |
| Dialoge: Gebaut, Bestand erfassen, Gedruckt, Spule, Freigabe, Referenz hinzufügen, Vermessen, Maßstab, Rendern, Drucken, Drucker-Einstellungen, Dokumente exportieren, Meilenstein, Variante | Blätter und Dialoge | bleiben vorerst (V2-7 macht daraus Kacheln) |
| `LogWindow`, `CatalogWindow`, `ZukaufDialogWindow` | eigene Fenster | bleiben Nebenfenster |
| `FotoAnsichtOverlay`, `AbweichungLegende`, `MassstabLeiste`, `DurchspielenLeiste`, `SimulationWerkzeugLeiste` | im Viewport | bleiben im Viewer |
| Menüs: `KevCADCommands`, `MaterialCommands`, `DokumenteCommands`, `DokumenteExportCommands`, `AnimationCommands`, `VersionenCommands`, `StockCommands`, `BestandCommands`, `ZukaufCommands`, `RenderCommands`, `SimulationCommands`, `SidebarCommands`, `InspectorCommands` | Ablage, Darstellung (Bereiche ⌘1 bis ⌘4, Schnellansichten ⌃⌘1 bis ⌃⌘3, Blender-Tasten), Modell, Dokumente, Material, Animation, Versionen, Simulation, Hilfe | neu geordnet, siehe Abschnitt 7 |
| `KeyboardGuard`, `WindowHook` (App/) | einbuchstabige Kürzel nicht in Textfeldern; Testfenster auf den zweiten Monitor | bleiben; `WindowHook` kennt zusätzlich das schmale Fenster am Rand |
| `DemoActions`, `DemoViewport` (Demo/) | Demomodus ohne Kernel | bleiben, setzen auch die neuen Aktionen um |
| Selbsttests (`KEVCAD_SELFTEST=…`) | starten aus dem Willkommens- bzw. Projektfenster | bleiben, starten aus dem Hauptfenster |

## 2. Gestaltungssystem

Alle Werte stehen in `app/Sources/KevCAD/Gestaltung/Gestaltung.swift` (`Gestaltung.Farbe`, `.Schrift`, `.Abstand`,
`.Radius`, `.Bewegung`, kurz `GF`, `GS`, `GA`, `GR`, `GB`). Kein Baustein setzt eigene Farben oder Größen. Eine andere
Richtung tauscht diese Datei und drei eigens gezeichnete Bausteine: `GraphitGrund`, `KachelNummer`, `Sprechrahmen`.

| Baustein | Datei | Zweck |
|---|---|---|
| `KevKnopfStil` (`rund`, `text`, `breit`, `leise`), `SymbolKnopf`, `AufnahmeKnopf` | Gestaltung/Knopf.swift | Knöpfe; echte SwiftUI-Knöpfe, daher Tastatur, Fokusring (Lichtblau) und VoiceOver |
| `ModusUmschalter` | Gestaltung/Knopf.swift | Fokus/Werkstatt, auch Blickrichtung der zweiten Ansicht |
| `Tastenkappe`, `TastenHinweis` | Gestaltung/Knopf.swift | Tasten in Hinweisen, mit gesprochenem Namen für VoiceOver |
| `GliederungsZeile` | Gestaltung/Zeilen.swift | Zeile der Gliederung: Pfeil, Name, Anzahl, Punkt bei Befund oder Markierung, Umbenennen im Feld |
| `EigenschaftsFeld` | Gestaltung/Zeilen.swift | Titel, Wert, Einheit oder „vorher …“ in Messing; bearbeitbar mit Zeilenschalter, esc verwirft |
| `AbschnittTitel` | Gestaltung/Zeilen.swift | Überschrift in Spalten und Karten |
| `KachelRahmen`, `KachelNummer` | Gestaltung/Rahmen.swift | Kachel mit Nummer, Titel, Untertitel, „groß“, „schließen“; durchsichtig für den Viewer |
| `OverlayKarte` | Gestaltung/Rahmen.swift | Karte über allem (Startübersicht), mit Unschärfe dahinter |
| `Statuszeile`, `SprechKnopf` | Gestaltung/Rahmen.swift | Zeile unten in der Werkstatt: Sprechen, zuletzt Gesagtes, Agent, Stand |
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

## 4. Fokus und Werkstatt

- **Fokus** (⌘1): Viewer über die ganze Fläche unter der Kopfleiste. Links die Gliederung leise im Bild, unten Kevins
  Live-Text (sobald er spricht), rechts unten die Agentenspur. Keine Tafeln.
- **Werkstatt** (⌘2): links eine Spalte mit Objekten (Suche ab 13 Teilen) und Eigenschaften der Auswahl, rechts die
  Kachelfläche, unten die Statuszeile.
- **Gliederung**: nur Gruppen und Objekte. Klick wählt, ⇧ oder ⌘ nimmt dazu, Doppelklick oder Zeilenschalter benennt
  um, ↑ ↓ wandern, ← → klappen. Gruppen mit gewählten Teilen öffnen sich von selbst. Umbenennen ändert die Namen in
  model.py (`ModellQuelle.benenneUm`): genau die Zeichenketten in `show()`, `verbauen(name=…)`, `befestigt(…)`; entsteht
  ein Name im Code, sagt die Kopfleiste, dass der Agent das übernimmt.
- **Eigenschaften**: Lagerteil, Länge, Maße, Werkstoff, Masse; Isolieren und Zeigen; darunter „Maße des Modells“: alle
  `param()`-Werte als Felder. Ein geänderter Wert landet in model.py (`ModellQuelle.setzeParameter`, nur bei genau
  einem `param("name", Zahl)`). „vorher …“ zeigt, was sich im letzten Lauf geändert hat, egal ob durch Kevin oder den
  Agenten.
- **Agentenspur**: bis V2-5 aus der Tätigkeitszeile (`agentActivity`), dem Ende jedes Laufs und den Befunden der
  Prüfung. Höchstens sechs Einträge.
- Der Viewer wird nie neu angelegt: Er steht an fester Stelle im Ansichtsbaum, nur sein Rahmen wechselt (ohne
  Animation). Verdeckt (Werkstatt ohne Kachel „Modell“, andere Kachel groß) ruht er (`isPaused`).

## 5. Kacheln

- Arten: Modell, Zeichnung, Stückliste, Zuschnitt, zweite Ansicht, Material, Simulation, Versionen, Details. Höchstens
  vier zugleich, nummeriert 1 bis 4; eine fünfte verdrängt die älteste außer dem Modell.
- Anordnung: eine füllt alles; zwei nebeneinander (im Hochformat übereinander); drei mit der ersten links groß und zwei
  rechts übereinander; vier im Raster. Eine große Kachel füllt die Fläche allein.
- Eingebettet statt neu geschrieben: Zeichnung = `DokumenteBereich` (breit mit Seitenleiste und Inspektor),
  Stückliste = `StuecklisteKompaktTabelle` bzw. groß `MaterialStuecklisteAnsicht`, Zuschnitt = `MaterialZuschnittAnsicht`,
  Material = `MaterialBereich` mit Seitenleiste und Inspektor, Simulation = Seitenleiste, Ergebnisse, Inspektor,
  Versionen = `VersionenLeiste`, Details = `InspectorView`. Die zweite Ansicht ist bis V2-4 ein Bild einer
  Standardansicht (`AppController.zweiteAnsicht`), neu gerechnet nach jedem Lauf.
- Wer `ProjectWindowState.bereich` setzt (Sprünge aus Stückliste, Teilebaum, Menüs, Selbsttests), holt die passende
  Kachel nach vorn; umgekehrt folgt `bereich` der aktiven Kachel, damit die Kürzel der Bereiche passen.
- Alles über `OberflaechenActions` (Befehle `Oberflaechenbefehl`), damit Sprache (V2-6) und Agent (V2-7) es auslösen.

## 6. An den Rand

⌃⌥→ bzw. ⌃⌥← (oder der Knopf oben rechts): Das Fenster wird 460 pt breit, so hoch wie der sichtbare Bildschirm, am
rechten bzw. linken Rand, und zeigt den Fokus (unter 640 pt rückt er zusammen: ohne Gliederung, Agent und Sprechknopf
unten). Noch einmal stellt Größe, Lage und Modus von vorher wieder her. Die Bewegung läuft 0,3 s über die
Fensteranimation von AppKit. Beim Beenden geht das Fenster ohne Animation zurück.
