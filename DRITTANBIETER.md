# Fremde Bausteine und Lizenzen

Kev CAD selbst steht unter der [MIT-Lizenz](LICENSE). Die Bausteine unten gehören anderen und stehen unter ihren
eigenen Lizenzen. Stand: 23.10.2026, geprüft an den Sperrdateien (`Package.resolved`, `uv.lock`) und den installierten
Umgebungen.

## Im Repo enthalten

| Baustein | Ort | Lizenz | Hinweis |
|---|---|---|---|
| osifont | `app/Resources/Fonts/` | LGPL-3.0 mit Font-Ausnahme | Lizenztexte liegen bei; Schrift der technischen Zeichnungen |
| HDRI-Umgebungen (Poly Haven, über Blender) | `kernel/src/kevcad_kernel/render/umgebungen/` | CC0 | Herkunft in `LIZENZ.md` dort |
| Prompt Depth Anything (PromptDA) und DINOv2, Code | `scan/src/kevscan/promptda/` | Apache-2.0 | übernommen von https://github.com/DepthAnything/PromptDA (Haotong Lin u. a., CVPR 2025) und für Apple Silicon angepasst; Herkunft und Änderungen in `__init__.py` dort |
| fotocad (Auszug) | `fotomess/third_party/fotocad/` | MIT wie Kev CAD | Kevins eigenes Paket aus UPVIS/cad-aus-fotos |

## Beim Bau geladen

| Baustein | Lizenz | Hinweis |
|---|---|---|
| [OCCTSwiftViewport](https://github.com/SecondMouseAU/OCCTSwiftViewport) @ `d9984ad` (Swift-Paket, Metal-Viewport) | LGPL-2.1 mit OCCT-Ausnahme | wird in die App gelinkt. Wer die fertige App weitergibt, erfüllt die LGPL: Hinweis und Lizenztext beilegen, Neulinken ermöglichen (der Quellcode hier genügt dafür) |
| build123d, cadquery-ocp (OpenCASCADE) | Apache-2.0, LGPL-2.1 mit OCCT-Ausnahme | Kernel, fotomess |
| gmsh | GPL-2.0-or-later | Netze für die Festkörper-FEM und die Topologie. Kev CAD lädt es über uv, liefert es aber nicht mit. Wer Kev CAD mit gmsh als fertiges Paket weitergibt, muss die GPL beachten |
| torch, numpy, scipy, opencv-python-headless, scikit-fem, PyNite, MuJoCo, trimesh, moderngl, MCP-SDK und die übrigen Python-Pakete | MIT, BSD, Apache-2.0, PSF | rund 220 Pakete in den Umgebungen `kernel`, `fotomess` und `scan` |
| certifi, tqdm | MPL-2.0 | schwaches Copyleft, nur bei Änderung dieser Dateien relevant |
| paho-mqtt | EPL-2.0 oder BSD-3-Clause | BSD wählbar |

Keiner dieser Bausteine steht unter AGPL oder einer Lizenz ohne kommerzielle Nutzung.

## Zur Laufzeit geladen oder aufgerufen (nicht im Repo)

| Baustein | Lizenz | Wie Kev CAD ihn nutzt |
|---|---|---|
| PromptDA-Gewichte (Large, Small) | Apache-2.0 laut Rechteinhabern | laden beim ersten Scan von Hugging Face nach `~/Library/Caches/de.upvis.kevcad/promptda` |
| CalculiX (über micromamba von conda-forge) | GPL-2.0-or-later, micromamba BSD-3-Clause | eigenes Programm, nur als Prozess gestartet |
| Blender | GPL-2.0-or-later | eigenes Programm für Renderings in Fotoqualität. Die Skripte `kernel/src/kevcad_kernel/render/blender_skript.py` und `tools/capture/scripts/kontrollbilder.py` laufen in Blender; nach Lesart der Blender Foundation gelten solche Skripte bei Weitergabe als Teil von Blender (GPL). Die MIT-Lizenz ist mit der GPL verträglich |
| Bambu Studio | AGPL-3.0 | nur als Kommandozeilenprogramm aufgerufen (Slicen, Drucker-Profile aus dem installierten Programm); kein Profil liegt im Repo |
| Apple-Frameworks (Object Capture, RealityKit, ARKit, Vision) | Apple SDK-Bedingungen | Teil von macOS bzw. iOS |
