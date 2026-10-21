"""Name und Anweisungen des MCP-Servers (Feld ``instructions``), gemeinsam für Kernel-Server und stdio-Brücke.

Bewusst ohne schwere Importe, damit die Brücke sie laden kann, ohne build123d zu importieren. Die Texte richten sich an
das Sprachmodell und sind deshalb englisch; Ergebnistexte der Werkzeuge sind deutsch (Kevin liest mit).
"""

from __future__ import annotations

SERVER_NAME = "kevcad"
SERVER_TITLE = "Kev CAD"

INSTRUCTIONS = """\
Kev CAD is Kevin's native CAD viewer on the Mac. A model is a Python file `model.py` (build123d) in a project folder; \
the kernel executes it and every show() appears live in the viewer while Kevin watches.

Workflow
1. `status` first. No project open: `project_open(path)` or `project_new(path)` (a bare name means \
~/Documents/Kev CAD/<name>).
2. Edit model.py with your own file tools (path from status); use `model_write` only if you have none. Then `run`: \
it returns every part with size, volume and mass, or the failing line with an excerpt (isError).
3. Check the numbers from `run` against the task; verify key dimensions with `measure` where they matter. Fix, run \
again. Kevin watches the viewer live and wants results fast: no `screenshot` unless he asks for an image.

model.py rules
- Units mm and degrees, Z up. Start with `from build123d import *` and `from kevcad import show, step, param`.
- Parameters at the top: `breite = param("breite", 120)`; `run(params={...})` overrides them for one run.
- Call `step("Bohrungen")` before each construction step so Kevin sees the build progress live.
- Show every physical part once it exists, with a speaking German name: \
`show(platte, "Grundplatte", color="#B8BEC4", material="aluminum")`. Showing the same name again replaces it \
(the part visibly grows). "/" in names builds assemblies: "Halter/Lasche". Do not show throwaway helper geometry.
- material gives mass: a build123d material name such as aluminum, stainless, mild_steel, brass, pla, petg, oak.

References
- "Halter/Lasche" (part), "Halter/Lasche#f3" (face), "#e2" (edge), "#v1" (vertex); indices follow \
part.faces()/edges()/vertices(). They are valid for one run only: after every run get fresh ones from \
parts, selection or execute.
- `selection` returns what Kevin clicked in the viewer. Use it when he says "this", "here", "that hole".

Showing Kevin things
- `focus` moves the camera, `highlight` colors and labels elements, `annotate` draws dimensions, arrows and labels \
(world mm), `visibility` isolates or hides parts, `section` cuts, `view` switches standard views and display style. \
`measure(show=true)` also draws the measurement.
- `export` writes STEP, STL, 3MF or GLB into <project>/output/.
"""
