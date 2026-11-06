# Kev CAD · Arbeitsregeln

Kevins eigenes Werkzeug (kein Kundenprojekt): ein nativer CAD-Viewer für den Mac, den ein KI-Agent über MCP bedient.
Modelle entstehen als `model.py` mit build123d und bauen sich live im Viewer auf.

Auf anderen Rechnern als Kevins: Einrichtung und Bau nach [EINRICHTUNG.md](EINRICHTUNG.md) mit `./build.sh`. Die
Regeln unten zu Mac mini, `tools/fern.sh`, zweitem Monitor, Sperrdatei und automatischem Update gelten nur auf Kevins
Rechnern; die Verträge und Code-Regeln gelten überall.

Lesen vor der Arbeit: [PLAN-MVP.md](PLAN-MVP.md) (Ziel, Entscheidungen E1–E10, Arbeitspakete, AP0-Ergebnis),
[PROTOCOL.md](PROTOCOL.md) (Kernel ↔ App), [RECHERCHE.md](RECHERCHE.md) (Herkunft der Bausteine). Für den Umbau zu V2
(KI-first, Zweig `v2`): [PLAN-V2.md](PLAN-V2.md) (Ziel, Entscheidungen V1–V12, Budgets, Pakete V2-1 bis V2-8).
Oberfläche: [OBERFLAECHE.md](OBERFLAECHE.md) (Gestaltungswerte, Entwurf, Fokus und Werkstatt, Kacheln, Tasten).

## Aufbau

| Ordner | Inhalt |
|---|---|
| `kernel/` | Python 3.12 mit uv: build123d 0.13, ocp-tessellate, MCP. Paket `kevcad_kernel` (Server, Laufzeit, MCP) und `kevcad` (API für model.py) |
| `app/KevCADCore/` | Swift-Paket ohne Oberfläche: Protokoll, Kernel-Verbindung, Szene, Viewport, Modell, Spiegel-Dienst (`Mirror/`). Mit `swift test` testbar |
| `app/KevCADCore/Sources/KevCADWire/` | plattformneutral (macOS, iOS) für den Spiegel aufs iPhone ([MIRROR.md](MIRROR.md)): Rahmen, Geometrie, Körperteilung, Netzformat, Spiegel-Nachrichten. VoiceBridge bindet es über `Package.swift` im Wurzelordner ein; KevCADCore reicht es weiter |
| `mirror-fixtures/` | Testdateien des Spiegels für Kev CAD und VoiceBridge |
| `app/Sources/KevCAD/` | SwiftUI-App: Hauptfenster (`Arbeitsflaeche/`), Gestaltungswerte und Bausteine (`Gestaltung/`), Menüs, Kachelinhalte |
| `app/project.yml` | XcodeGen; `app/KevCAD.xcodeproj` wird erzeugt und ist nicht im Git |
| `skill/kev-cad/` | Modellierleitfaden für den Agenten |
| `spikes/ap0/` | Viewer- und Kerneltest (abgeschlossen, nur Nachschlagen) |
| `fotomess/` | Phase 4: Modell aus wenigen Fotos oder einem Video vermessen (eigene uv-Umgebung, `STRATEGIE.md`, `BENCHMARK.md`, Tests mit `.venv/bin/python -m pytest`); Einstieg für Kev CAD `fotomess.kevcad` |
| `tools/capture/` | Phase 4: `kevcad-capture` (SwiftPM, Apple Object Capture), Referenznetz aus einem Handyvideo; `build.sh` baut und installiert es mit |
| `kernel/src/kevcad_kernel/referenz/` | Phase 4 im Kernel: Referenzen in `<projekt>/referenzen/<name>/`, Object Capture und fotomess als eigene Prozesse, Bauer aus model.py (`varianten`), Abweichung als Farbkarte (`abweichung`), Maßstab nachträglich (`massstab`), Scans in der App (`laufzeit_rest`), MCP in `mcp_tools/referenz_tools.py` |

## Befehle

Bauen und testen über den Mac mini (`tools/fern.sh`, Kopf der Datei; Mini-Seite `tools/fern/mini.sh`):

```bash
tools/fern.sh tests        # Kern-Tests (swift test und pytest) auf dem Mac mini, Ausgabe live, Ausgang wie dort
tools/fern.sh testbau ui   # Testvariante "Kev CAD Test ui" dort bauen, nach build/ holen; Kernel ist der dieses Worktrees
tools/fern.sh release      # Installationsbau dort, App, Kernel und Skill hier installieren (wie ./build.sh)
tools/fern.sh status       # Plätze, Schlange und Speicher auf dem Mini
tools/fern.sh einrichten   # Mini prüfen bzw. vorbereiten (xcodegen, uv, Metal-Toolchain, Xcode-Fassung)
```

Lokal nur als Rückfall (fern.sh nimmt diesen Weg selbst, wenn der Mini fehlt):

```bash
./build.sh                 # bauen und nach ~/Applications/Tools installieren
./build.sh --test          # Testvariante "Kev CAD Test", nicht installiert
./build.sh --test ui       # weitere Testvariante mit eigenem Namen, Bundle-ID und Port
./build.sh --core-tests    # swift test (KevCADCore) und pytest (Kernel)
./build.sh --bundle        # Installationspaket build/bundle ohne Installation (so baut der Mini für release)
cd kernel && uv sync       # Kernel-Umgebung
cd kernel && .venv/bin/python tools/make_fixtures.py   # Protokoll-Testdateien neu erzeugen
cd kernel && .venv/bin/python tools/make_mirror_fixtures.py   # Testdateien des Spiegels neu erzeugen
cd kernel && .venv/bin/python tools/mirror_sim.py --socket /tmp/kcsim.sock   # Spiegel-Socket ohne App
```

## Installation und automatische Updates

- `main` ist der stabile Stand, den Kevin benutzt. Jeder neue Stand auf `main` (Commit, Merge, Pull) startet über
  `.githooks/post-commit` bzw. `post-merge` im Hintergrund `tools/auto-update.sh`: Es baut aus einer sauberen
  Arbeitskopie von main (`~/Library/Application Support/de.upvis.kevcad/build-src`) über `tools/fern.sh release` auf
  dem Mac mini (fehlt er, hier unter der Sperre) und installiert hier `Kev CAD.app` nach `~/Applications/Tools`
  (Tools-Stapel im Dock), Kernel und Skill nach `~/Library/Application Support/de.upvis.kevcad/install`. Protokoll:
  `~/Library/Logs/Kev CAD/update.log`. Probe ohne Kevins App: `KEVCAD_UPDATE_PROBE=<Ordner> KEVCAD_UPDATE_REF=<Zweig>`.
- Die installierte App, der MCP-Server `kevcad` und der Skill `kev-cad` nutzen nur diese installierte Kopie, nie den
  Arbeitsstand des Repos. Entwicklung daher auf Zweigen bzw. in Arbeitskopien und erst fertig nach `main`.
- Hooks sind aktiv über `git config core.hooksPath .githooks` (nach einem frischen Klon einmal setzen).
- Eine Instanz je Variante: ein zweiter Start holt die laufende App nach vorn und beendet sich.

## Schnittstellen (Verträge)

- `PROTOCOL.md` + `kernel/src/kevcad_kernel/protocol.py` + Testdateien in
  `app/KevCADCore/Tests/KevCADCoreTests/Fixtures/`: nur gemeinsam ändern, beide Seiten im selben Commit.
- `kernel/src/kevcad_kernel/service.py` (`KernelService`): Vertrag zwischen MCP-Werkzeugen und Kernel-Laufzeit.
- `app/KevCADCore/Sources/KevCADCore/Model/AppModel.swift` (`AppModel`, `AppActions`): Vertrag zwischen App-Kern und
  Oberfläche. Die Oberfläche liest `AppModel` und ruft nur `AppActions`; sie setzt keine `@Published`-Werte selbst.
- Öffentliche Signaturen von `AppController(model:)`, `start()`, `KevViewport(controller:)` bleiben stabil.

## Zuständigkeiten (für parallele Arbeit)

| Strang | Dateien |
|---|---|
| Kernel-Laufzeit | `kernel/src/kevcad_kernel/{runtime,worker,runner,tessellate,app_link,refs,measure,export,project}.py`, `kernel/src/kevcad/`, Tests dazu |
| MCP und Brücke | `kernel/src/kevcad_kernel/{server,bridge,tools}*.py`, `skill/kev-cad/`, Tests dazu |
| App-Kern | `app/KevCADCore/Sources/KevCADCore/{Protocol,Kernel,Scene,Viewer}/`, Tests dazu |
| Oberfläche | `app/Sources/KevCAD/`, `app/KevCADCore/Sources/KevCADCore/Project/`, Tests dazu |
| Statik | `kernel/src/kevcad_kernel/statik/`, `kernel/src/kevcad/statik.py`, `mcp_tools/statik_tools.py`, `app/KevCADCore/Sources/KevCADCore/Statik/`, `app/Sources/KevCAD/Statik/`, `test_statik.py`, `StatikTests.swift` (PLAN-STATIK.md) |
| Sprach-Feedback | `kernel/src/kevcad_kernel/feedback*.py`, `mcp_tools/feedback_tools.py`, `app/KevCADCore/Sources/KevCADCore/Sprache/`, `test_feedback.py`, `FeedbackTests.swift` (PROTOCOL.md, „V2-6 Sprach-Feedback“) |
| Simulation | `kernel/src/kevcad_kernel/simulation/`, `mcp_tools/simulation_tools.py`, `app/KevCADCore/Sources/KevCADCore/Simulation/`, `app/Sources/KevCAD/Simulation/`, `test_simulation.py`, `SimulationTests.swift` (PLAN-SIMULATION.md) |

Wer eine Vertragsdatei ändern muss, beschreibt die Änderung im Abschlussbericht, statt sie still zu machen.

## Regeln

- Oberflächentexte, Kommentare und Doku auf Deutsch; Bezeichner im Code englisch. Keine Emojis.
- Einheiten mm und Grad, Z nach oben.
- **Tests mit Oberfläche:** nur die Testvariante, im Hintergrund starten (`open -g -n "build/Kev CAD Test.app"`), ihr
  Fenster liegt auf dem zweiten Monitor. Danach beenden (`pkill -x "Kev CAD Test"`). Keine simulierten Maus- oder
  Tastatureingaben auf dem Hauptbildschirm; falls doch nötig, Mauszeiger und vorderes Programm wiederherstellen.
  Fensterbilder mit `screencapture -l <Fensternummer> -o -x datei.png`. Ohne zweiten Monitor `open -g -n --env
  KEVCAD_TEST_VERSTECKT=1 …`: Das Fenster liegt hinter dem Schreibtischbild, zeichnet und trifft weiter, ohne Dock-Symbol.
- Kernel-Tests nutzen eigene Sockets im Temp-Ordner und eigene Ports (nicht 47823/47824).
- **Bauen und Testen auf dem Mac mini:** Agenten bauen und testen nur über `tools/fern.sh` (Kevin, 22.10.2026: der Mini
  entlastet das MacBook). Dort gibt es zwei Bauplätze mit warmen Bauordnern und einen Testplatz, gewartet wird in einer
  Schlange; mehrere Agenten können also gleichzeitig aufrufen. Die Test-App kommt nach `build/` und läuft hier wie
  gewohnt. `./build.sh` direkt nur als Rückfall, wenn `tools/fern.sh` es nicht selbst tut.
  **Seit 05.11.2026 bauen Mini und MacBook wieder beide** (Kevin: „Mini und MacBook können gerne beide bauen, das würde
  ich mich nicht einschränken auf eins“; vom 22.10. bis 05.11.2026 lief alles auf dem MacBook). `~/.kevcad-nur-macbook`
  ist entfernt. `tools/fern.sh testbau` nimmt einen freien Bauplatz des Mini und baut hier, wenn dort beide belegt sind
  und die Sperre frei ist. Kernel-Tests über `tools/fern.sh tests` (Testplatz auf dem Mini); einige Tests nutzen feste
  Ports, lokal deshalb nie zwei volle Testläufe gleichzeitig. Bis zu drei Agenten mit Builds.
- **Lokal nur einzeln:** Der Mac hat 16 GB. Jedes lokale `xcodebuild` (also jedes `./build.sh`) läuft unter der mit
  VoiceBridge gemeinsamen Sperre: `lockf -k /tmp/vb-xcodebuild.lock ./build.sh --test …`, vorher
  `memory_pressure | tail -1` prüfen und unter 25 % freiem Speicher warten. `tools/fern.sh` und das automatische Update
  halten sich im Rückfall selbst daran.
- **Mac mini:** ssh-Name `mac-mini` (Benutzer core), alles für Kev CAD unter `~/KevCAD-Bau`, nie in fremden Ordnern
  (Tessera, VoiceBridge). Die Metal-Toolchain ist dort installiert (Shader übersetzt der Mini selbst); fehlt sie nach einem
  Xcode-Update, meldet fern.sh das, baut lokal und `tools/fern.sh einrichten` holt sie ohne Passwort nach.
- Der Viewport ist OCCTSwiftViewport, Stand `d9984ad`, als lokale Kopie in `app/Packages/OCCTSwiftViewport` mit
  kleinen, markierten Änderungen (Liste in `KEVCAD-AENDERUNGEN.md` dort; nur ergänzen, nie still ändern). Auflagen aus
  AP0: Picking einschalten, Körper über 16.000 Dreiecke oder Kantensegmente aufteilen, `preferredFramesPerSecond` selbst
  auf 120 setzen.
- Viewer V2: Die Belegung von Tasten, Maus und Trackpad steht nur in `Viewer/Tastenbelegung.swift` (Menüs, Viewport,
  Hinweisleiste und Tastenübersicht lesen dort); Gestaltungswerte der Überlagerungen in `Viewer/ViewerStil.swift`.
  Selbsttest: `KEVCAD_SELFTEST=viewer` (Zustände mit Fotos, Bildzeiten beim Drehen).
- ocp-tessellate liefert degenerierte Kanten mit; vor dem Nummerieren herausfiltern (`BRep_Tool.Degenerated_s`).
- Commit-Nachrichten auf Deutsch, je Arbeitspaket mindestens ein Commit.
