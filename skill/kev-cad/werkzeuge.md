# Werkzeuge von Kev CAD (ab V2-2)

Teil des Skills kev-cad. Erzeugt aus den Werkzeugen selbst mit `kernel/.venv/bin/python kernel/tools/skill_werkzeuge.py`; nicht von Hand ändern (ein Test prüft den Gleichlauf). Beschreibungen englisch wie im MCP-Server.

## Kernsatz

In Claude Code mit einem ToolSearch-Aufruf laden: `select:mcp__kevcad__status,mcp__kevcad__projekt,mcp__kevcad__modell,mcp__kevcad__run,mcp__kevcad__execute,mcp__kevcad__parts,mcp__kevcad__measure,mcp__kevcad__view,mcp__kevcad__pruefen,mcp__kevcad__ansichten,mcp__kevcad__katalog,mcp__kevcad__export,mcp__kevcad__feedback`

### status

Shared picture of the situation, call it first and whenever you lose track: open project and model.py path, kernel and app, last run in one line, open findings, Kevin's selection with values, his camera (named view or direction, target, distance), what is hidden or isolated, mode and open tiles.


### projekt

Open an existing project folder (with model.py), or create one with neu=true (vorlage 'example' writes a small sample model, 'empty' only the imports). A bare name means ~/Documents/Kev CAD/<name>. name=... alone names the open project (a draft moves to ~/Documents/Kev CAD/<name>, the result gives the new path).

- `pfad` (string, optional): Project folder: absolute path, ~/..., or a bare project name
- `neu` (boolean, optional, Vorgabe False): Create a new project instead of opening one
- `vorlage` ('example' | 'empty', optional, Vorgabe 'example'): neu: starting content of model.py
- `name` (string, optional): Name for the open project; not together with pfad

### modell

Read model.py of the open project, or overwrite it with code (complete new content). Prefer your own file tools when you have them; after writing call run.

- `code` (string, optional): Complete new content of model.py; omit to read it

### run

Execute model.py; parts stream live into Kevin's viewer. Returns what you need next: ok or the failing line with excerpt and hint (isError), new and changed parts with the difference to the last run you saw (unchanged ones only counted), new or changed findings first (known ones counted), check state and times. Change dimensions with params (no file edit, about 2 s): run(params={"breite": 140}). detail 'teile' adds every part, 'voll' everything. A run that changed a project file becomes a version; titel names it in Kevin's words.

- `params` (object, optional): Overrides for param() values by name, e.g. {"breite": 140}
- `detail` ('kurz' | 'teile' | 'voll', optional, Vorgabe 'kurz'): kurz = changes only, teile = plus every part, voll = everything
- `titel` (string, optional): Short German description of a larger change in Kevin's words; becomes the title of the new version
- `slow_ms` (integer, optional, Vorgabe 0): Slow motion pause in ms per step, 0 = off
- `timeout_s` (number, optional): Time limit for model.py in seconds (default 120, at most 900); raise only after a time-limit failure
- `warten_s` (number, optional): Wait at most this long for the built-in check (default 0.4 to 3 s, depending on the run time; 0 = not at all); if it still runs, call pruefen() before reporting done

### execute

Run Python in the namespace of the last run (all model.py variables, build123d imported) to inspect geometry, e.g. `print(platte.bounding_box())`. Objects passed to show() appear as a translucent sketch. Returns stdout and the repr of the last expression; does not change model.py.

- `code` (string): Python code; the value of a final expression is returned

### parts

Parts of the last run. Without filter: every part in one line (size, mass, stock/print/material, centre); filter (part name or assembly prefix): those parts with bounding box, volume, area, faces and edges. stueckliste=true: bill of materials with positions, weight, guide prices, cut list per bar and the shopping list (format 'csv' as CSV). Use the names as references.

- `filter` (string, optional): Part name or assembly prefix, e.g. 'Gestell'
- `stueckliste` (boolean, optional, Vorgabe False): Bill of materials, cut list and shopping list instead
- `format` ('text' | 'csv', optional, Vorgabe 'text'): stueckliste: text table or CSV

### measure

Exact measurement in the kernel (OCCT). Without refs: what Kevin has selected, with its values (use it when he says 'this', 'here', 'that hole'). One ref: its properties (face area/normal/radius, edge length/radius, vertex position, part bbox/volume/mass). Two refs: minimum distance with dx/dy/dz and both points, angle, distance of parallel faces or axes. show=true also draws it in the viewer.

- `refs` (list[string], optional): One or two references of the current run; omit for Kevin's selection
- `show` (boolean, optional, Vorgabe True): Draw the measurement in the viewer

### view

Control what Kevin sees, several things in one call (applied in this order): visibility (sichtbarkeit with teile), section, standard view, projection, display, fit, explode, camera focus on refs, highlight refs in a color with a label, draw an annotation, remove highlights and annotations. Omitted values stay. dauer_s shows a highlight or annotation only briefly, e.g. a dimension you mention while talking. Result tiles side by side (up to 4, numbered, Kevin says "Kachel 2 groß"): kacheln, kachel_gross, kachel_zu; a tile in Fokus switches to Werkstatt. modus, rand, zeitleiste, zweite_ansicht and blatt arrange the rest.

- `standard` ('top' | 'bottom' | 'front' | 'back' | 'left' | 'right' | 'iso' | 'iso_front_left' | 'iso_back_right' | 'iso_back_left', optional): Standard view direction
- `projection` ('perspective' | 'orthographic', optional): Camera projection
- `display` ('shaded_edges' | 'shaded' | 'wireframe' | 'xray' | 'solid' | 'material' | 'technical', optional): Display style in Kevin's viewer: solid, material (physically based), technical (white parts, outlines), xray, wireframe
- `fit` (boolean, optional, Vorgabe False): Zoom so that all visible parts fit
- `explode` (number, optional): Explosion factor 0 (assembled) .. 1
- `focus` (list[string], optional): Move the camera (animated) to these parts/elements
- `sichtbarkeit` ('zeigen' | 'ausblenden' | 'isolieren' | 'alle', optional): Show, hide or isolate teile (isolieren = only these visible); alle = everything visible
- `teile` (list[string], optional): Parts for sichtbarkeit
- `schnitt` ('x' | 'y' | 'z' | 'aus', optional): Section plane normal to this axis (material on the positive side removed); aus removes it
- `schnitt_mm` (number, optional, Vorgabe 0): Position of the section plane along its normal in mm
- `schnitt_normale` (list[number], optional): Custom section normal [x, y, z]
- `hervorheben` (list[string], optional): Parts, faces, edges or vertices to highlight (earlier highlights are replaced)
- `farbe` (string | list[number], optional): Highlight color: hex like '#FF8800', a name (red, orange, ...) or linear RGB 0..1
- `beschriftung` (string, optional): Short label next to the highlight
- `dazu` (boolean, optional, Vorgabe False): hervorheben: keep earlier highlights instead of replacing them
- `anmerkung` (object, optional): Draw {art: 'dimension'|'arrow'|'label', punkte: [[x,y,z], ...] in mm, text?, id?}; a dimension without text shows the distance
- `entfernen` (boolean | 'hervorhebungen' | 'anmerkungen' | list[string], optional, Vorgabe False): First remove: true = highlights and annotations, 'hervorhebungen' or 'anmerkungen' only those, a list = these annotation ids
- `dauer_s` (number, optional): hervorheben, anmerkung: fade out after this many seconds
- `animate` (boolean, optional, Vorgabe True): Animate the focus move so Kevin can follow
- `kacheln` (list['modell' | 'zeichnung' | 'bauplan' | 'stueckliste' | 'zuschnitt' | 'druck' | 'animation' | 'ansicht' | 'material' | 'simulation' | 'versionen' | 'details' | 'render'], optional): Show these tiles (added to the open ones). zeichnung, bauplan, stueckliste, zuschnitt, druck, animation, ansicht = second view, material, simulation, versionen, details, render, modell = the viewer
- `kacheln_nur` (boolean, optional, Vorgabe False): kacheln: exactly these, numbered in this order
- `kachel_gross` ('modell' | 'zeichnung' | 'bauplan' | 'stueckliste' | 'zuschnitt' | 'druck' | 'animation' | 'ansicht' | 'material' | 'simulation' | 'versionen' | 'details' | 'render' | integer | string, optional): This tile (name or number 1-4) fills the area; aus = all side by side again
- `kachel_zu` (list['modell' | 'zeichnung' | 'bauplan' | 'stueckliste' | 'zuschnitt' | 'druck' | 'animation' | 'ansicht' | 'material' | 'simulation' | 'versionen' | 'details' | 'render' | integer] | string, optional): Close tiles
- `modus` ('fokus' | 'werkstatt', optional): fokus = only the viewer, werkstatt = tiles and properties
- `rand` ('links' | 'rechts' | 'aus', optional): Window narrow at this screen edge next to the chat; aus = back
- `zeitleiste` (boolean, optional): Timeline over the viewer in Fokus
- `zweite_ansicht` ('top' | 'bottom' | 'front' | 'back' | 'left' | 'right' | 'iso' | 'iso_front_left' | 'iso_back_right' | 'iso_back_left', optional): Direction of tile ansicht
- `blatt` (integer | string, optional): Sheet in tile zeichnung: number, id or title

### pruefen

Result of the built-in check of the last run (it runs after every run): every finding with location, values and a fix (interpenetration, floating, tipping, assembly, tool access, print, statics, constraints), stability per group, assembly summary. warten=true (default) waits for work still running in the background, so call it before reporting done. hinweise=true also lists notes; bilder=true adds close-up images of the worst findings for your own analysis (never send them to Kevin). thema 'bedingungen': constraints, degrees of freedom, fastening, range of motion (teil, alle); 'montage': assembly order.

- `thema` ('alles' | 'bedingungen' | 'montage', optional, Vorgabe 'alles'): What to show
- `hinweise` (boolean, optional, Vorgabe False): Also list notes (schwere hinweis)
- `bilder` (boolean, optional, Vorgabe False): Close-up images of up to 3 findings for your own analysis
- `warten` (boolean, optional, Vorgabe True): Wait for the final result (up to 5 minutes)
- `teil` (string, optional): bedingungen: only this part or assembly
- `alle` (boolean, optional, Vorgabe False): bedingungen: list every constraint, also satisfied ones

### ansichten

Images for your own analysis, several in one call (not for Kevin, he watches the viewer): standard views (default iso, front, right, top) and/or free view directions, small (640 × 400), optionally framed on parts or a point, x-ray, parts tinted red, the red overlap volumes of the check; Kevin's camera stays. kevin=true returns instead exactly Kevin's current view (only when he asks for an image).

- `views` (list['top' | 'bottom' | 'front' | 'back' | 'left' | 'right' | 'iso' | 'iso_front_left' | 'iso_back_right' | 'iso_back_left'], optional): Standard views, default iso, front, right, top
- `richtungen` (list[list[number]], optional): Extra free view directions [x, y, z] (camera looks along)
- `ziel` (list[string], optional): Frame these parts (names or groups)
- `punkt` (list[number], optional): Frame this point [x, y, z] (with radius)
- `radius` (number, optional): Radius around punkt in mm
- `darstellung` ('shaded_edges' | 'shaded' | 'wireframe' | 'xray', optional, Vorgabe 'shaded_edges'): Display style for these images
- `hervorheben` (list[string], optional): Parts to tint red
- `schnittkoerper` (boolean, optional, Vorgabe True): Show the red overlap volumes of the check
- `width` (integer, optional): Image width in px (640, kevin: 1280)
- `height` (integer, optional): Image height in px (400, kevin: 800)
- `kevin` (boolean, optional, Vorgabe False): Exactly Kevin's current view instead
- `overlays` (boolean, optional, Vorgabe True): kevin: with highlights, annotations and measurements

### katalog

Kevin's stock catalog (inventory rule: build only from it). suche finds stock items by text and dimensions ('vierkantrohr 40x40x3', 'multiplex 18', 'm8', 'alutec 05200'); art filters by kind, art='material' lists materials instead (ids and aliases for show(material=...) and print parts). id returns one item with dimensions, kg/m, bar length, price and a usage example for model.py.

- `suche` (string, optional, Vorgabe ''): Words and dimensions, e.g. 'rohr 42,4x2' or 'petg'
- `art` ('rohr' | 'vierkantrohr' | 'rechteckrohr' | 'flach' | 'rund' | 'vierkant' | 'winkel' | 'u_profil' | 'nutprofil' | 'holz' | 'platte' | 'schraube' | 'mutter' | 'scheibe' | 'zukaufteil' | 'material', optional): Only this kind; 'material' for materials
- `id` (string, optional): Details of one stock item by id

### export

Write files into <project>/output/: step, stl, 3mf, glb (parts limits them to these part names), bom_csv (bill of materials with cut list), einkaufsliste_csv (shopping list), pdf (the app builds one PDF from bausteine: deckblatt, produktbild, stueckliste, teileliste, einkaufsliste, zuschnitt, druck, zeichnungen, bauplan; empty = all; drucken=true opens the print dialog, only when Kevin explicitly asks). 3MF for printing with filament settings: druck(aktion="export").

- `formats` (list['step' | 'stl' | '3mf' | 'glb' | 'bom_csv' | 'einkaufsliste_csv' | 'pdf']): File formats to write
- `parts` (list[string], optional): 3D formats: part names to export; omit for all
- `bausteine` (list, optional): pdf: building blocks in order (names or {art, spalten, auswahl}); empty = all
- `ziel` (string, optional): pdf: target path (relative = inside output/)
- `drucken` (boolean, optional, Vorgabe False): pdf: open the print dialog; only on Kevin's explicit wish

### feedback

Wait until Kevin has finished speaking and return his voice feedback: his sentences with what he pointed at (part, face, 3D point) or drew at that moment, plus an image with his strokes. Returns at once if a package is waiting, else waits up to warten_s. Time running out is no error: it says what he is doing. nochmal=true returns the last package again.

- `warten_s` (number, optional, Vorgabe 600.0): Seconds to wait for Kevin; 0 only looks
- `nochmal` (boolean, optional, Vorgabe False): Return the last fetched package again

## Fachwerkzeuge

### lager

Changes to Kevin's stock catalog, releases and purchased parts (search and item details: katalog). Propose only when Kevin asks; a proposal is unusable until Kevin releases it by his click.
aktion and its parameters (pass them next to aktion; ? = optional):
- teil_vorschlagen(entry, ebene?): propose a stock item (entry as in KATALOG.md)
- material_vorschlagen(entry, ebene?): propose a material
- loeschen(kind, id, ebene?): delete a stock item or material, only on Kevin's request
- freigabe(ids, grund?, warten_s?): open the release dialog in the project window and wait for Kevin's click; also when he writes 'freigegeben' in the chat; never releases anything itself
- zukauf_anlegen(url?, mpn?, gtin?, felder?, ebene?): purchased part from a shop link, mpn or gtin and the fields you read from the page
- zukauf_html(url, html, anlegen?, ebene?): purchased part from the HTML of a shop page
- cad_suchen(id): links where Kevin downloads the manufacturer CAD
- cad_uebernehmen(id, pfad?, minuten?, erzwingen?): take over the downloaded STEP or ZIP (newest in ~/Downloads)
- zukauf_liste(query?): purchased parts with release and CAD state
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### bestand

Stock on hand of the open project, shopping list and bookings. Enter only what Kevin told you (quote him in grund); book built or printed only on his explicit word; every booking can be undone.
aktion and its parameters (pass them next to aktion; ? = optional):
- liste(id?): stock on hand: bars, sheets, offcuts, pieces, filament spools
- eintragen(grund, id?, ganze?, reste?, reste_entfernen?, stueck?, mindestrest_mm?, reste_ersetzen?, material?, gramm?, spule?, gramm_voll?, farbe?, hersteller?, ort?, anzahl?, kennung?, spulen_entfernen?, filament?): enter or change stock from Kevin's words
- einkaufsliste(): shopping list exactly as Kevin sees it in the app
- gebaut(grund): book the project as built
- gedruckt(grund, platten?, spule?): book printed plates (filament) off
- rueckgaengig(id): undo a booking
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### druck

3D printing on Kevin's Bambu Lab P1P. Before any export or print question ask Kevin which filament is loaded (filamente lists his); the last choice is only a suggestion.
aktion and its parameters (pass them next to aktion; ? = optional):
- pruefung(teil?): print check: orientation with reason, key figures, findings, settings
- vorschau(detail?): filament, time, plates, cost, recommended settings
- einstellen(teil, einstellungen?, zweck?, zuruecksetzen?): fix print settings of a part, only on Kevin's request
- export(ziel?, platten?, teile?, ohne?, filament?): print-ready 3MF plates for Bambu Studio; filament from Kevin required
- filamente(material?): Kevin's filaments, last choice of this project, spools in stock
- filament_neu(hersteller, produkt, material, farbe?, durchmesser_mm?, basis?, abweichungen?, farbe_hex?, id?, preset_name?, quelle?, ersetzen?): define a filament, only on Kevin's request
- drucker(): printer state and last job, read-only
- drucken(platten?, weg?, grund?): open the print dialog; ONLY when Kevin explicitly asks to print
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### statik

Statics computed after every run: load scenarios, motion (MuJoCo), solid FEM, contact and plasticity (CalculiX), the load cases of the app's Simulation area. Always state the simplifications; no substitute for a structural engineer on safety-relevant things.
aktion and its parameters (pass them next to aktion; ? = optional):
- ergebnis(szenario?): all scenarios with traffic light, or one in detail
- szenario(name, lasten?, beschleunigung?, neigung?, richtung?, stoss?, ziel?, beschreibung?, zeigen?, dynamik?, geschwindigkeit?, bremsen?, dauer?): answer 'does it hold if ...' in under a second without a new run, shown in the viewer
- dynamik(name, geschwindigkeit?, bremsen?, dauer?, neigung?, richtung?, stoss?, animation?, antrieb?, angriff?, fahrtrichtung?, suche?, zeigen?, beschreibung?): motion over time, e.g. push at 1 m/s and brake abruptly
- grenze(ohne?, bremsen?, geschwindigkeit?, name?): speed limit until a loose body jumps out or the group tips
- festigkeit(teil?, szenario?, fein?, ablauf?, zeigen?, abbrechen?, verfahren?, kontakt?, plastisch?, traglast?, beulen?, klemmkraft?, reibwert?): solid FEM of a part; verfahren='ccx' for contact, plasticity, load capacity, buckling
- simulation(): load cases, forces and supports from the app
- simulation_aendern(ops, basis?): change them like Kevin's clicks, only on his request
- simulation_rechnen(was, lastfall?, teil?, fein?, grenze?, verfahren?): run the buttons of the Simulation area
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### topologie

Topology optimisation of a print part (saves material, runs about a minute in the background). Report before/after figures; approximation, no strength proof.
aktion and its parameters (pass them next to aktion; ? = optional):
- optimieren(teil?, szenario?, behalten?, schutz?, ueberhang?, fein?, steg?, lager?, neu?, warten?, abbrechen?): start or check an optimisation
- ergebnis(warten_s?): result with figures before and after
- uebernehmen(variante?): take it over as a variant, only on Kevin's request
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### zeichnung

Workshop drawings (ISO 128/129-1) from the model, sheets in dokumente/zeichnungen/. Check every sheet yourself with bild; never send these images to Kevin.
aktion and its parameters (pass them next to aktion; ? = optional):
- liste(): sheets with their checks
- erstellen(teile?, art?, format?): drawings for manufactured parts plus the assembly sheet
- bearbeiten(blatt, ops): edit dimensions, views, scale, format, notes (ops)
- bild(blatt, breite?): image of a sheet for your own check
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### bauplan

Step-by-step build instructions from the model (material, cutting, drilling, printing, assembly), every assembly step simulated. Numbers come from the kernel; fix problems in model.py, not in the text.
aktion and its parameters (pass them next to aktion; ? = optional):
- zeigen(neu?, kurz?): generate or show the build plan
- bearbeiten(ops): rewrite step texts, order, scope (ops)
- pruefen(schritt?, schwere?): re-run the simulation of the assembly steps
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### referenz

Reference meshes from phone videos, photos and Kev Scan; measure param() values from them. Never edit model.py with measured values yourself (Kevin applies them); never send check images to Kevin.
aktion and its parameters (pass them next to aktion; ? = optional):
- liste(name?, warten_s?): references and their state; waits with warten_s
- video(pfad, masz?, auflage?, von?, bis?, name?, einstellung?, warten_s?): scaled reference mesh from a video (Object Capture, about 1 min)
- fotos(pfade, name?): reference from photos
- vermessen(quelle?, freie_masse?, bekannte_masse?, bilder?, vorgaben?, grenzen?, maske?, von?, bis?, kb_brennweite?): measure free param() values from video, photos or scan
- fotoansicht(name?, foto?, modus?, deckkraft?, satz?, aus?, bild_zeigen?): a photo through its fitted camera behind the model
- abweichung(name?, teile?, zeigen?, auf?, skala_mm?, grenze_mm?): deviation model to mesh per part, color map for Kevin
- massstab(mm, name?, punkte?, kante?): fix the scale of a reference afterwards
- scans(): scans received from Kev Scan on the iPhone
- scan_importieren(scan?, name?, schnell?, warten_s?): evaluate a scan in the background and add it
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### kamera

Film cameras from model.py (lager.kamera): angle of view, depth of field, view through the camera, images.
aktion and its parameters (pass them next to aktion; ? = optional):
- liste(): cameras with angle of view and depth of field
- info(name?): all values of one camera
- ansicht(name?): Kevin's viewer looks through the camera; name 'aus' or none = back
- bild(name?, breite?, speichern?, bild_zeigen?, rahmen?): PNG through the camera into output/kameras/, returns the path
- katalog(suche?, art?): cameras, lenses and rig accessories in the inventory
- vorschlag(name?): Kevin's current view as a setzen(...) line
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### animation

Animations from model.py (animation(...)): play, jump, render video, check collisions over time.
aktion and its parameters (pass them next to aktion; ? = optional):
- liste(): animations with duration, moving parts and cameras
- abspielen(name?, an?, schleife?, geschwindigkeit?, von_vorn?): play or stop in the app
- springen(zeit, name?): jump to a time
- video(name?, breite?, fps?, kamera?, format?): MP4 into output/animationen/, optionally through a camera
- kollision(name?, schritt?): exact collision check every 3rd frame; solve every penetration
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### versionen

Every successful run that changed a project file is a version V<n>. At the end of every task set a milestone; restore only when Kevin asks.
aktion and its parameters (pass them next to aktion; ? = optional):
- liste(limit?, variante?): history of versions and milestones
- meilenstein(titel, notiz?, version?, ersetzen?): name the current version: short German title and a note
- vergleichen(a, b?, zeigen?, code_zeilen?): parameters, parts, BOM, check and code diff, ghost in the viewer
- wiederherstellen(version): go back to a version, only on Kevin's request
- variante_liste(): variants of the project
- variante_anlegen(name, von?): create a variant (from a version) and switch to it
- variante_wechseln(name): switch to a variant ('Hauptstand' = main state)
- variante_umbenennen(name, neuer_name): rename a variant
aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as JSON.

### render

Beautiful images for Kevin (product image, cover, social media), only on his wish: the answer names the PNG in output/renders/. qualitaet 'schnell' in the app (seconds), 'foto' Blender Cycles in the background.

Parameter: szene?, ansicht?, kamera?, groesse?, qualitaet?, hintergrund?, umgebung?, ziel?, auftrag?, abbrechen?, warten_s?, bild_zeigen? (`?` = optional); Einzelheiten: render mit falschen Argumenten oder [ansicht.md](ansicht.md).

## Zuordnung der bisherigen Werkzeuge (bis V2-1)

Die 95 Werkzeuge bis V2-1 sind seit V2-2 Aktionen der Fachwerkzeuge oder Teil des Kernsatzes; alle Funktionen sind erhalten.

| bis V2-1 | ab V2-2 |
|---|---|
| `animation_abspielen` | `animation(aktion="abspielen")` |
| `animation_liste` | `animation(aktion="liste")` |
| `animation_springen` | `animation(aktion="springen")` |
| `animation_video` | `animation(aktion="video")` |
| `annotate` | `view(anmerkung={art, punkte, text, id})` |
| `ansichten` | `ansichten(…)` |
| `bauplan` | `bauplan(aktion="zeigen")` |
| `bauplan_bearbeiten` | `bauplan(aktion="bearbeiten")` |
| `bauplan_pruefen` | `bauplan(aktion="pruefen")` |
| `bedingungen` | `pruefen(thema="bedingungen", teil, alle)` |
| `bestand_eintragen` | `bestand(aktion="eintragen")` |
| `bestand_liste` | `bestand(aktion="liste")` |
| `bom` | `parts(stueckliste=true, format)` |
| `buchung_rueckgaengig` | `bestand(aktion="rueckgaengig")` |
| `cad_suchen` | `lager(aktion="cad_suchen")` |
| `cad_uebernehmen` | `lager(aktion="cad_uebernehmen")` |
| `catalog_delete` | `lager(aktion="loeschen")` |
| `clear_annotations` | `view(entfernen=…)` |
| `dokument_export` | `export(formats=["pdf"], bausteine, ziel, drucken)` |
| `druck_einstellen` | `druck(aktion="einstellen")` |
| `druck_export` | `druck(aktion="export")` |
| `drucken` | `druck(aktion="drucken")` |
| `drucker_status` | `druck(aktion="drucker")` |
| `druckpruefung` | `druck(aktion="pruefung")` |
| `druckvorschau` | `druck(aktion="vorschau")` |
| `dynamik` | `statik(aktion="dynamik")` |
| `dynamik_grenze` | `statik(aktion="grenze")` |
| `einkaufsliste` | `bestand(aktion="einkaufsliste")` |
| `execute` | `execute(code)` |
| `export` | `export(formats, parts)` |
| `festigkeit` | `statik(aktion="festigkeit")` |
| `filament_define` | `druck(aktion="filament_neu")` |
| `filament_liste` | `druck(aktion="filamente")` |
| `focus` | `view(focus=[…])` |
| `freigabe_anfragen` | `lager(aktion="freigabe")` |
| `gebaut_buchen` | `bestand(aktion="gebaut")` |
| `gedruckt_buchen` | `bestand(aktion="gedruckt")` |
| `highlight` | `view(hervorheben, farbe, beschriftung, dazu)` |
| `kamera_ansicht` | `kamera(aktion="ansicht")` |
| `kamera_bild` | `kamera(aktion="bild")` |
| `kamera_info` | `kamera(aktion="info")` |
| `kamera_katalog` | `kamera(aktion="katalog")` |
| `kamera_liste` | `kamera(aktion="liste")` |
| `kamera_vorschlag_aus_ansicht` | `kamera(aktion="vorschlag")` |
| `kollision_pruefen` | `animation(aktion="kollision")` |
| `material_define` | `lager(aktion="material_vorschlagen")` |
| `material_list` | `katalog(art="material", suche)` |
| `measure` | `measure(refs, show)` |
| `meilenstein` | `versionen(aktion="meilenstein")` |
| `model_read` | `modell()` |
| `model_write` | `modell(code)` |
| `montage_reihenfolge` | `pruefen(thema="montage")` |
| `parts` | `parts(filter)` |
| `project_new` | `projekt(pfad, neu=true, vorlage)` |
| `project_open` | `projekt(pfad)` |
| `pruefen` | `pruefen(hinweise, bilder, warten)` |
| `referenz_abweichung` | `referenz(aktion="abweichung")` |
| `referenz_fotoansicht` | `referenz(aktion="fotoansicht")` |
| `referenz_fotos` | `referenz(aktion="fotos")` |
| `referenz_massstab` | `referenz(aktion="massstab")` |
| `referenz_vermessen` | `referenz(aktion="vermessen")` |
| `referenz_video` | `referenz(aktion="video")` |
| `referenzen` | `referenz(aktion="liste")` |
| `render` | `render(…)` |
| `run` | `run(params, detail, titel, …)` |
| `scan_importieren` | `referenz(aktion="scan_importieren")` |
| `scans` | `referenz(aktion="scans")` |
| `screenshot` | `ansichten(kevin=true) bzw. ansichten(views=[…])` |
| `section` | `view(schnitt, schnitt_mm, schnitt_normale)` |
| `selection` | `measure() ohne refs` |
| `simulation_aendern` | `statik(aktion="simulation_aendern")` |
| `simulation_liste` | `statik(aktion="simulation")` |
| `simulation_rechnen` | `statik(aktion="simulation_rechnen")` |
| `statik` | `statik(aktion="ergebnis")` |
| `status` | `status()` |
| `stock_define` | `lager(aktion="teil_vorschlagen")` |
| `stock_get` | `katalog(id)` |
| `stock_search` | `katalog(suche, art)` |
| `szenario_rechnen` | `statik(aktion="szenario")` |
| `topologie_ergebnis` | `topologie(aktion="ergebnis")` |
| `topologie_optimieren` | `topologie(aktion="optimieren")` |
| `topologie_uebernehmen` | `topologie(aktion="uebernehmen")` |
| `variante` | `versionen(aktion="variante_liste|_anlegen|_wechseln|_umbenennen")` |
| `version_wiederherstellen` | `versionen(aktion="wiederherstellen")` |
| `versionen` | `versionen(aktion="liste")` |
| `versionen_vergleichen` | `versionen(aktion="vergleichen")` |
| `view` | `view(standard, projection, display, fit, explode)` |
| `visibility` | `view(sichtbarkeit, teile)` |
| `zeichnung_bearbeiten` | `zeichnung(aktion="bearbeiten")` |
| `zeichnung_bild` | `zeichnung(aktion="bild")` |
| `zeichnung_erstellen` | `zeichnung(aktion="erstellen")` |
| `zeichnungen` | `zeichnung(aktion="liste")` |
| `zukauf_anlegen` | `lager(aktion="zukauf_anlegen")` |
| `zukauf_html` | `lager(aktion="zukauf_html")` |
| `zukauf_liste` | `lager(aktion="zukauf_liste")` |
