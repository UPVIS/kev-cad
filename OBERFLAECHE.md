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
