# Kev CAD · Arbeitsregeln

Kevins eigenes Werkzeug (kein Kundenprojekt): ein nativer CAD-Viewer für den Mac, den ein KI-Agent über MCP bedient.
Modelle entstehen als `model.py` mit build123d und bauen sich live im Viewer auf.

Lesen vor der Arbeit: [PLAN-MVP.md](PLAN-MVP.md) (Ziel, Entscheidungen E1–E10, Arbeitspakete, AP0-Ergebnis),
[PROTOCOL.md](PROTOCOL.md) (Kernel ↔ App), [RECHERCHE.md](RECHERCHE.md) (Herkunft der Bausteine).

## Aufbau

| Ordner | Inhalt |
|---|---|
| `kernel/` | Python 3.12 mit uv: build123d 0.13, ocp-tessellate, MCP. Paket `kevcad_kernel` (Server, Laufzeit, MCP) und `kevcad` (API für model.py) |
| `app/KevCADCore/` | Swift-Paket ohne Oberfläche: Protokoll, Kernel-Verbindung, Szene, Viewport, Modell. Mit `swift test` testbar |
| `app/Sources/KevCAD/` | SwiftUI-App: Fenster, Leisten, Projekte, Menüs |
| `app/project.yml` | XcodeGen; `app/KevCAD.xcodeproj` wird erzeugt und ist nicht im Git |
| `skill/kev-cad/` | Modellierleitfaden für den Agenten |
| `spikes/ap0/` | Viewer- und Kerneltest (abgeschlossen, nur Nachschlagen) |

## Befehle

```bash
./build.sh                 # bauen und nach ~/Applications/Tools installieren
./build.sh --test          # Testvariante "Kev CAD Test", nicht installiert
./build.sh --test ui       # weitere Testvariante mit eigenem Namen, Bundle-ID und Port
./build.sh --core-tests    # swift test (KevCADCore) und pytest (Kernel)
cd kernel && uv sync       # Kernel-Umgebung
cd kernel && .venv/bin/python tools/make_fixtures.py   # Protokoll-Testdateien neu erzeugen
```

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

Wer eine Vertragsdatei ändern muss, beschreibt die Änderung im Abschlussbericht, statt sie still zu machen.

## Regeln

- Oberflächentexte, Kommentare und Doku auf Deutsch; Bezeichner im Code englisch. Keine Emojis.
- Einheiten mm und Grad, Z nach oben.
- **Tests mit Oberfläche:** nur die Testvariante, im Hintergrund starten (`open -g -n "build/Kev CAD Test.app"`), ihr
  Fenster liegt auf dem zweiten Monitor. Danach beenden (`pkill -x "Kev CAD Test"`). Keine simulierten Maus- oder
  Tastatureingaben auf dem Hauptbildschirm; falls doch nötig, Mauszeiger und vorderes Programm wiederherstellen.
  Fensterbilder mit `screencapture -l <Fensternummer> -o -x datei.png`.
- Kernel-Tests nutzen eigene Sockets im Temp-Ordner und eigene Ports (nicht 47823/47824).
- Der Viewport ist OCCTSwiftViewport, festgenagelt auf Commit `d9984ad`. Auflagen aus AP0: Picking einschalten,
  Körper über 16.000 Dreiecke oder Kantensegmente aufteilen, `preferredFramesPerSecond` selbst auf 120 setzen.
- ocp-tessellate liefert degenerierte Kanten mit; vor dem Nummerieren herausfiltern (`BRep_Tool.Degenerated_s`).
- Commit-Nachrichten auf Deutsch, je Arbeitspaket mindestens ein Commit.
