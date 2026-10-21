# Kev CAD

Nativer CAD-Viewer für den Mac, den ein KI-Agent über MCP bedient. Claude schreibt ein parametrisches `model.py`
mit build123d, Kev CAD zeigt das Modell Teil für Teil live an. Messen, Ansichten, Schnitte und Export gehen per Klick
oder durch den Agenten.

Stand: MVP im Aufbau. Plan und Fortschritt in [PLAN-MVP.md](PLAN-MVP.md).

## Voraussetzungen

- macOS 15 oder neuer, Apple Silicon
- Xcode mit Kommandozeilenwerkzeugen, `xcodegen`, `rsvg-convert` (Homebrew `librsvg`)
- [uv](https://docs.astral.sh/uv/) für die Python-Umgebung des Kernels

## Bauen

```bash
./build.sh
```

Legt `Kev CAD.app` nach `~/Applications/Tools`. Weitere Varianten stehen im Kopf von `build.sh`.

## Aufbau

- `kernel/`: Python-Kernel (build123d, ocp-tessellate, MCP)
- `app/`: SwiftUI-App mit dem Metal-Viewport OCCTSwiftViewport
- [PROTOCOL.md](PROTOCOL.md): Protokoll zwischen Kernel und App
