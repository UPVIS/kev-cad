# Kev CAD

Nativer CAD-Viewer für den Mac, den ein KI-Agent über MCP bedient. Claude schreibt ein parametrisches `model.py`
mit build123d, Kev CAD zeigt das Modell Teil für Teil live an. Messen, Ansichten, Schnitte und Export gehen per Klick
oder durch den Agenten.

Stand: MVP fertig (21.10.2026). Plan, Abnahme und offene Punkte in [PLAN-MVP.md](PLAN-MVP.md).

## Voraussetzungen

- macOS 15 oder neuer, Apple Silicon
- Xcode mit Kommandozeilenwerkzeugen, `xcodegen`, `rsvg-convert` (Homebrew `librsvg`)
- [uv](https://docs.astral.sh/uv/) für die Python-Umgebung des Kernels

## Bauen

```bash
./build.sh
```

Legt `Kev CAD.app` nach `~/Applications/Tools`. Weitere Varianten stehen im Kopf von `build.sh`.

## Mit Claude benutzen

```bash
claude mcp add kevcad -s user -e KEVCAD_LAUNCH_ON_START=0 -- "<repo>/kernel/.venv/bin/kevcad-mcp"
ln -sfn "<repo>/skill/kev-cad" ~/.claude/skills/kev-cad
```

Danach in einer neuen Claude-Code-Sitzung zum Beispiel: „Leg in Kev CAD ein Projekt Regalwinkel an und bau einen
Winkel aus 4-mm-Stahlblech mit zwei Bohrungen.“ Kev CAD startet beim ersten Werkzeugaufruf von selbst.

## Aufbau

- `kernel/`: Python-Kernel (build123d, ocp-tessellate, MCP)
- `app/`: SwiftUI-App mit dem Metal-Viewport OCCTSwiftViewport
- [PROTOCOL.md](PROTOCOL.md): Protokoll zwischen Kernel und App
