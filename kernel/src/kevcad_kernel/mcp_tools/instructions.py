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
2. Find the parts in Kevin's stock catalog with `stock_search` (see Inventory rule).
3. Edit model.py with your own file tools (path from status); use `model_write` only if you have none. Then `run`: \
it returns every part with size, volume and mass, or the failing line with an excerpt (isError).
4. Check the numbers from `run` (and `bom`) against the task; verify key dimensions with `measure` where they \
matter. Fix, run again. Kevin watches the viewer live and wants results fast: no `screenshot` unless he asks for an \
image.

Inventory rule (Inventar-Regel, on by default)
- Build only from the inventory. Every part passed to show() must come from `lager.teil(...).verbauen(...)`, from \
a released purchased part `lager.zukauf(...).verbauen(...)` or be marked as a new 3D printed part with `lager.druckteil(form, name, material="petg")`; the material of a print must be \
released and printable ("druckbar" in `material_list`, e.g. pla, petg, asa, tpu-95a; verfahren "3d-druck" or \
"harzdruck"). Materials in show(material=...) only from the catalog (id or alias). Never invent parts or materials.
- If something is missing in the catalog: ask Kevin. Only on his request propose it with `stock_define` / \
`material_define`; a proposal waits for Kevin's release in the stock catalog window and cannot be used before that.
- `run` reports parts outside the inventory as isError ("Inventar-Regel: …"); the geometry is still shown, but export \
is refused. Fix the model: search a matching stock item and verbauen it, or make it a druckteil.
- Only Kevin can switch the rule off for a project (kevcad.json "inventar_regel": false, e.g. for reconstructions \
from photos). There is no tool for it and you must not change it yourself.
- 3D printed parts follow the design rules for Kevin's Bambu Lab P1P (open frame, no enclosure: PLA or PETG by default) (see the skill kev-cad, file 3d-druck.md): \
walls in multiples of the 0.42 mm line width, overhangs up to 45°, teardrop horizontal holes, bed-side chamfer, \
clearances, inserts and nut traps, layer direction for strength, build volume 256 × 256 × 250 mm.

Built-in check (Prüfung, after every run)
- Every run is checked automatically; `run` waits for the result. Parts that interpenetrate (overlap volume above \
0.001 mm³ and 0.01 mm depth; touching is fine) are findings with a concrete fix each. Fasteners are no exception \
(washer ↔ washer, head ↔ washer, screw in a through hole). The only automatic exception is real thread engagement \
(screw in a nut or in a core/tapped hole, same axis, overlap only within the thread depth).
- Open findings make `run` an error (isError) and export is refused. Fix them in model.py (clearance, hole, move, \
correct a dimension); never explain them away. A deliberate overlap (press fit, foam) only after asking Kevin, with \
`erlaubt_ueberlappung(a, b, grund="...")` from kevcad in model.py; without a reason it does not count.
- Kevin sees the affected parts in red and the overlap volume as a red ghost in the viewer.

model.py rules
- Units mm and degrees, Z up. Start with `from build123d import *` and `from kevcad import lager, show, step, param`.
- Parameters at the top: `breite = param("breite", 120)`; `run(params={...})` overrides them for one run.
- Call `step("Bohrungen")` before each construction step so Kevin sees the build progress live.
- Show every physical part once it exists, with a speaking German name: `show(bein, "Gestell/Bein vorn links")`. \
Showing the same name again replaces it (the part visibly grows). "/" in names builds assemblies: "Halter/Lasche". \
Do not show throwaway helper geometry. Stock parts carry their material, color and mass.

Stock parts (Lagerteile) and bill of materials
- `stock_search("vierkantrohr 40x40x3")`, then in model.py `rohr = lager.teil("<id>")` (or \
`lager.teil("vierkantrohr", a=40, s=3, material="stahl-s235")`), \
`bein = rohr.verbauen(laenge=842, name="Gestell/Bein vorn links", gehrung=(0, 0))` and \
`show(Pos(...) * bein, "Gestell/Bein vorn links")` with the SAME name as in verbauen, so the bill of materials links \
the shown part (moving, rotating, drilling keep the link). Bars lie along +Z from z=0 with the section centered; \
laenge is the cut length at the longest edge; gehrung=(start, end) in degrees about the local X axis (positive keeps \
the +Y edge long); drehung=90 turns the section first. Sheets: `platte.verbauen(breite=800, tiefe=600, \
name="Deckel")` (XY plane from z=0, centered) or form=<Sketch>. Screws: `schraube.verbauen(laenge=60, \
name="Schrauben/M8x60 1")` (bd_warehouse, head on z=0, shaft along -Z); nuts and washers without laenge.
- Every verbauen and druckteil call is one line in the bill of materials, even if the part is drilled later.
- `bom` shows positions, weight, guide prices and the cut list (3 mm saw kerf); `run` mentions the totals. \
`export(["bom_csv"])` writes the CSV.

Purchased parts (Zukaufteile)
- Bought parts with manufacturer and number (drawer slides, hinges, castors, trolleys, camera accessories) come from \
the catalog as `lager.zukauf("<id>")`: `rw = wagen.verbauen("Rollwagen")`, `show(Pos(...) * rw, "Rollwagen")` with the \
SAME name; `wagen.bezugspunkt("oben")` is a Location in the part's own system for placing other parts. Without a \
manufacturer model the part is a simplified box or cylinder ("(vereinfacht)" in its name): always mention simplified \
parts in your report to Kevin.
- Kevin gives a shop link, part number or EAN: read the page with YOUR tools (Kev CAD never fetches shop pages), then \
`zukauf_html(url, html)` or `zukauf_anlegen(url, felder={...})`; let Kevin confirm manufacturer, number, price and \
dimensions. The entry is a proposal until Kevin releases it. Standard parts ("ISO 4762 M6x20") are redirected to the \
stock catalog. Then `cad_suchen(id)`: with TraceParts the STEP comes automatically, otherwise ask Kevin to download it \
from the returned links and call `cad_uebernehmen(id)` (newest file in ~/Downloads, ZIP too). `zukauf_liste` shows \
all purchased parts.

References
- "Halter/Lasche" (part), "Halter/Lasche#f3" (face), "#e2" (edge), "#v1" (vertex); indices follow \
part.faces()/edges()/vertices(). They are valid for one run only: after every run get fresh ones from \
parts, selection or execute.
- `selection` returns what Kevin clicked in the viewer. Use it when he says "this", "here", "that hole".

Showing Kevin things
- `focus` moves the camera, `highlight` colors and labels elements, `annotate` draws dimensions, arrows and labels \
(world mm), `visibility` isolates or hides parts, `section` cuts, `view` switches standard views and display style. \
`measure(show=true)` also draws the measurement.
- `export` writes STEP, STL, 3MF, GLB or the bill of materials (bom_csv) into <project>/output/.
"""
