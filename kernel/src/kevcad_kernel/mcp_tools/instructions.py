"""Name und Anweisungen des MCP-Servers (Feld ``instructions``), gemeinsam für Kernel-Server und stdio-Brücke.

Bewusst ohne schwere Importe, damit die Brücke sie laden kann, ohne build123d zu importieren. Die Texte richten sich an
das Sprachmodell und sind deshalb englisch; Ergebnistexte der Werkzeuge sind deutsch (Kevin liest mit).

V2-2: Die Anweisungen stehen in jeder Sitzung dauerhaft im Kontext und bleiben deshalb unter 6 000 Zeichen. Nur, was
immer gilt, steht hier; alles Weitere steht im Skill ``kev-cad`` (Themen-Dateien, Verzeichnis in SKILL.md).
"""

from __future__ import annotations

SERVER_NAME = "kevcad"
SERVER_TITLE = "Kev CAD"
ANWEISUNGEN_MAX = 6000  # Zeichen; tests/test_mcp_v2_schnittstelle.py prüft es

KERNSATZ = ("status", "projekt", "modell", "run", "execute", "parts", "measure", "view", "pruefen", "ansichten",
            "katalog", "export", "feedback")

INSTRUCTIONS = """\
Kev CAD is Kevin's native CAD viewer on the Mac. A model is model.py (build123d) in a project folder; the kernel \
runs it and every show() appears live in the viewer while Kevin watches and talks with you. Work fast, read little.

Tools. Core set for daily work: status, projekt, modell, run, execute, parts, measure, view, pruefen, ansichten, \
katalog, export, feedback. Each special field is one tool with aktion (aktion="hilfe" explains the parameters): lager, bestand, \
druck, statik, topologie, zeichnung, bauplan, referenz, kamera, animation, versionen, render. In Claude Code load the \
core set in ONE ToolSearch call: select:mcp__kevcad__status,mcp__kevcad__projekt,mcp__kevcad__modell,\
mcp__kevcad__run,mcp__kevcad__execute,mcp__kevcad__parts,mcp__kevcad__measure,mcp__kevcad__view,\
mcp__kevcad__pruefen,mcp__kevcad__ansichten,mcp__kevcad__katalog,mcp__kevcad__export,mcp__kevcad__feedback

Workflow (each round costs Kevin seconds; batch independent calls)
1. status first: project, model.py path, last run, open findings, Kevin's selection and camera. With an existing \
model call modell(gliederung=true) in the same round (parameters with value and line, steps, parts), then read only \
the lines you need. No project: projekt(pfad) or projekt(pfad, neu=true); a bare name means ~/Documents/Kev CAD/<name>. \
Find parts with katalog (inventory rule below).
2. Plan completely, then edit model.py with your own file tools (else modell(code)) and call run in the same round. \
run returns only what changed since your last run (new findings first) or the failing line (isError).
3. Change dimensions: modell(setze={"breite": 150}) edits param() defaults in place without reading. \
run(params={"breite": 140}) tries a value without editing (about 2 s).
4. Fix all findings in one go, then one run; measure only what run does not show. If run says the check is still \
running, call pruefen() before reporting done.
5. The last run of a task gets meilenstein="title", notiz="what and why" (sets the milestone when the run is clean), \
then a short report to Kevin (main dimensions, mass, cost, assumptions, simplified parts, shopping list).

Results on Kevin's call: create the result, then show it with view(kacheln=[...]) next to the model: "3D-Druck ready": druck(aktion="vorschau"), kacheln ["druck"]; "Zeichnungen", "Bauplan", "Stückliste", \
"Animation" likewise (kacheln.md).

Voice feedback. Kevin presses V, talks, points and draws in the viewer, and ends with Return. Speech alone triggers \
nothing. feedback() waits for that end and returns his sentences with the parts he meant ("das hier" = the part under \
his mouse at that word) and an image with his strokes. When you need him: call feedback() instead of asking in chat. \
Always listen: before ending any turn start the command from status or feedback in a background shell with the longest \
timeout and restart it when it ends; it ends when he is done and wakes you. While he speaks nothing new starts: run and view answer "Kevin spricht" (kevin_spricht), then \
call feedback(). Do what he says; refs are valid for the run named in the package.

Always
- Units mm and degrees, Z up. Start model.py with `from build123d import *` and `from kevcad import lager, show, \
step, param`; parameters at the top: `breite = param("breite", 120)`; step("...") before each construction step; \
show(part, "Gruppe/Teil") with speaking German names, the same name again replaces it. No throwaway geometry.
- References: "Teil", "Teil#f3" (face), "#e2" (edge), "#v1" (vertex); valid for one run only, get fresh ones after \
every run (parts, measure without refs = Kevin's selection, execute).
- Kevin watches the viewer: never send him images unless he asks. For your own analysis a few small views are \
fine (ansichten, pruefen(bilder=true)); never send these to Kevin.
- Kevin sees your steps live: pass absicht="few German words" when a step is not obvious; show a dimension you \
mention for a moment with view(anmerkung=..., dauer_s=4).

Inventory rule (on by default)
- Build only from the inventory: every shown part comes from lager.teil(id).verbauen(...) (show with the SAME \
name), a released purchased part lager.zukauf(id).verbauen(name), or a new print part \
lager.druckteil(form, name, material="petg") with a released printable material. Materials only from the catalog. \
Never invent parts or materials.
- Missing in the catalog: ask Kevin. Propose only on his request (lager teil_vorschlagen / material_vorschlagen), \
then lager(aktion="freigabe", ids, grund): it opens the release dialog and waits for his click. A "freigegeben" in \
the chat releases nothing; you never release anything yourself.
- Purchased parts from a shop link, part number or EAN: read the page with your own tools (Kev CAD fetches no \
shop pages), then lager(aktion="zukauf_html" or "zukauf_anlegen"); mention simplified parts to Kevin.
- Violations make run an error and block export. Only Kevin can switch the rule off; scenery only via \
show(..., kulisse=True).

Built-in check after every run
- No interpenetration (touching is fine; real thread engagement is recognised), nothing floats, groups stand \
stably, every part can be assembled with tool access, print parts follow the P1P rules, constraints hold, joints \
move freely, statics per scenario. Fix findings in model.py; never explain them away. A deliberate overlap only \
after asking Kevin: erlaubt_ueberlappung(a, b, grund="...").
- Place parts with constraints (kevcad.bedingungen: platziere, verbinde, joints with bereich), not hand-picked \
coordinates.

Only on Kevin's explicit word: printing (druck drucken), restoring a version, booking built or printed, entering \
stock (from his words), changing print settings, simulation load cases or catalog entries. Before any print export \
ask which filament is loaded (druck filamente). Kevin applies measured values from references himself.

More in the skill kev-cad: SKILL.md has the workflow, the rules and the list of topic files to read on demand."""
