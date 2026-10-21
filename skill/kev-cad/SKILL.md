---
name: kev-cad
description: Leitfaden für Kev CAD, Kevins nativen CAD-Viewer auf dem Mac (MCP-Server „kevcad“, Werkzeuge wie run, screenshot, measure). Verwenden, sobald Kevin in Kev CAD ein 3D-Modell bauen, ändern, vermessen, ansehen oder exportieren will – Halter, Gehäuse, Bauteile, Möbel, Baugruppen als model.py mit build123d, die sich live im Viewer aufbauen. Auch bei „bau mir …“, „mach die Bohrung größer“, „wie weit ist das vom Rand weg“, „zeig mir die Lasche von der Seite“, „was hab ich angeklickt“, „exportier als STEP/STL/3MF“ in einem Kev-CAD-Projekt.
---

# Kev CAD

Ein Modell ist `model.py` im Projektordner (build123d, Millimeter, Z nach oben). Der Kernel führt die Datei aus, jedes
`show()` erscheint sofort im Viewer, Kevin sieht beim Bauen zu. Die Datei ist die Quelle der Wahrheit: Änderungen immer
dort, nie nur per `execute`.

## Inventar-Regel (Kevin, 21.10.2026, gilt immer)

Gebaut wird nur aus dem Inventar. Jedes Teil im Modell ist ein Lagerteil bzw. Halbzeug, das Kevin definiert hat
(Rohr, Profil, Platte, Holz, Schraube, später Zukaufteile), oder ausdrücklich ein **neues 3D-Druckteil** aus einem
druckbaren Material (PLA, PETG, ABS …). Es kommt kein Material neu dazu, das nicht vorher ausdrücklich definiert ist.

- Fehlt ein Teil oder Material: **nicht erfinden**, sondern Kevin fragen und es erst nach seiner Freigabe verwenden.
  Was du anlegst, ist nur ein Vorschlag, bis Kevin ihn freigibt.
- Eigene Konstruktionen nur als Druckteil kennzeichnen, nie als freies Teil mit beliebigem Material.
- Mit Phase 2 prüft Kev CAD das selbst (Lagerkatalog, `lager.teil(...).verbauen(...)`, `lager.druckteil(...)`); bis
  dahin hältst du dich von Hand daran und nennst in `show()` nur Materialien, die Kevin vorgegeben hat.
- Ausnahme: Projekte, in denen Kevin die Regel ausdrücklich abschaltet (Nachbauten aus Fotos, Skizzen).

## Prüfen vor dem Fertigmelden (Kevin, 21.10.2026, gilt immer)

Nichts darf physikalisch unmöglich sein. Nach jedem Lauf und vor jeder Fertigmeldung prüfen und Fehler beheben, nicht
nur melden:

- **Keine Durchdringungen:** Zwei Teile dürfen sich berühren, aber nicht ineinander stecken. Prüfen mit `execute`:

  ```python
  from itertools import combinations
  teile = {n: o for n, o in shown.items()} if "shown" in dir() else {}
  for (a, fa), (b, fb) in combinations(teile.items(), 2):
      if fa.bounding_box().overlaps(fb.bounding_box()):  # nur Paare mit sich überschneidenden Hüllquadern
          v = (fa & fb).volume
          if v > 0.001:
              print(f"Durchdringung {a} ↔ {b}: {v:.3f} mm³")
  ```

  (Die Namen und Formen kommen aus dem Namensraum von model.py; dort die gezeigten Teile in einem dict sammeln, falls
  es noch keines gibt.) Gefundene Durchdringungen beheben: Spiel oder Bohrung vorsehen, Teil verschieben, Maß
  korrigieren. Gewollte Überlappungen (Gewinde in einem Kernloch, Presspassung, nachgiebiger Schaum) nur nach Rückfrage
  und mit Begründung im Code.
- **Nichts schwebt:** Jedes Teil berührt ein anderes Teil oder steht auf dem Boden (z = 0). Mit `measure` den Abstand
  zum Nachbarteil prüfen (0,000 mm = Kontakt).
- **Steht sicher:** Der Schwerpunkt der Baugruppe liegt über der Aufstandsfläche (`parts` liefert Masse und Lage).
- **Bewegliches** (Klappen, Räder, Schieber) über den ganzen Weg ohne Kollision.
- Kev CAD bekommt diese Prüfungen fest eingebaut (Fehler im Lauf, rote Markierung); bis dahin hältst du dich von Hand
  daran.

## 3D-Druckteile konstruieren (Kevin, 21.10.2026, immer beachten)

Drucker: Bambu Lab P2S, Bauraum 256 × 256 × 256 mm, Düse 0,4 mm, Schicht 0,2 mm. Die Druckausrichtung beim Konstruieren
mitdenken und im Bericht nennen. Kurzfassung (ausführlich folgt in `3d-druck.md`):

- **Wände** als Vielfache der Linienbreite (~0,42 mm): mindestens 1,2 mm, tragend 2–3 mm; Merkmale nicht unter 0,8 mm.
- **Überhänge** bis 45° ohne Stütze; Unterseiten fasen statt runden; Brücken höchstens ~15 mm.
- **Waagrechte Bohrungen** als Tropfenform (Spitze nach oben); Bohrungen drucken etwa 0,1–0,2 mm zu klein, Ø vorhalten.
- **Bettseite** mit Fase 0,4–0,6 mm gegen Elefantenfuß; eine ebene, große Auflagefläche einplanen.
- **Spiel** je Seite: Presspassung 0,1, Spielpassung 0,2, beweglich/Print-in-Place 0,3–0,5 mm.
- **Gewinde**: Gewindeeinsätze (Tasche nach Herstellermaß, z. B. M3 Ø 4,0–4,2 mm) oder eingeschlossene Muttern
  (Sechskant +0,2–0,3 mm, Einführschräge); Kernlöcher für Schrauben direkt ins Teil etwa 0,8 × d.
- **Gegenbohrungen und Senkungen**, die nach unten zeigen, mit Opferschicht (0,2 mm) drucken, sonst Stütze nötig.
- **Festigkeit**: Last längs der Schichten führen, nicht quer (Schichtfugen sind die Schwachstelle); Innenkanten
  verrunden; Schnapphaken in Schichtrichtung legen.
- **Verzug** bei ABS/ASA/PA: große ebene Flächen und spitze Ecken vermeiden, Ecken verrunden.
- **Z-Maße** möglichst als Vielfache von 0,2 mm; Schrift mindestens 0,6 mm erhaben, Strich ab 0,8 mm.
- **Größer als der Bauraum**: teilen, mit Passstiften oder Schwalbenschwanz und ebenen Fügeflächen.

## Arbeitsablauf

1. `status`: offenes Projekt, Pfad von model.py, letzter Lauf, Kevins Auswahl.
2. Kein Projekt: `project_new("Wandhalter")` oder `project_open("Wandhalter")`. Ein bloßer Name landet in
   `~/Documents/Kev CAD/<Name>`.
3. model.py mit den eigenen Dateiwerkzeugen schreiben oder ändern (Pfad aus `status`). `model_write` nur, wenn es keine
   Dateiwerkzeuge gibt.
4. `run`: liefert jedes Teil mit Hüllmaß, Volumen und Masse. Ein Fehler kommt als isError mit Zeile, Auszug und
   Hinweis; die letzte gute Geometrie bleibt stehen. Korrigieren, wieder `run`.
5. Prüfen: Zahlen aus `run` mit der Aufgabe vergleichen, wichtige Sollmaße mit `measure` nachmessen. Kein
   `screenshot`: Kevin sieht den Viewer live und will das Ergebnis schnell (siehe „Bilder“).
6. Kevin kurz berichten: was gebaut ist, Hauptmaße, Masse, offene Annahmen. Bei Bedarf `focus`, `highlight`,
   `annotate` nutzen, damit er es im Viewer sieht.

Speichert Kevin model.py selbst und ist Auto-Lauf an, rechnet der Kernel von allein. `run` wartet dann auf diesen Lauf,
statt doppelt zu rechnen.

## Gerüst von model.py

```python
from build123d import *
from kevcad import param, show, step

# Parameter in mm
rohr_d = param("rohr_d", 42.4)   # Außendurchmesser des Rohrs
dicke = param("dicke", 5)        # Blechdicke
breite = param("breite", 40)
laenge = param("laenge", 120)
loch_d = param("loch_d", 6.6)    # Durchgangsbohrung M6, mittel
spiel = 0.5

step("Grundplatte")
platte = Box(laenge, breite, dicke, align=(Align.CENTER, Align.CENTER, Align.MIN))
platte = fillet(platte.edges().filter_by(Axis.Z), radius=4)   # Ecken runden, bevor gebohrt wird
show(platte, "Halter/Grundplatte", color="#B8BEC4", material="aluminum")

step("Bohrungen")
for x in (-laenge / 2 + 15, laenge / 2 - 15):
    platte -= Pos(x, 0, -1) * Cylinder(loch_d / 2, dicke + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
show(platte, "Halter/Grundplatte")   # gleicher Name: ersetzt, man sieht das Teil wachsen

step("Schelle")
r_i = rohr_d / 2 + spiel
mitte_z = 2 * dicke + r_i
ring = Cylinder(r_i + dicke, breite) - Cylinder(r_i, breite + 2)
schelle = Pos(0, 0, mitte_z) * Rot(90, 0, 0) * ring              # erst drehen, dann schieben
schelle -= Pos(0, 0, mitte_z + r_i) * Box(4, breite + 2, 2 * dicke + 2)   # Schlitz oben
show(schelle, "Halter/Schelle", color="#8FA3B8", material="aluminum")
```

## API von kevcad

| Aufruf | Wirkung |
|---|---|
| `param(name, wert, min=None, max=None)` | benannter Parameter (mm). Liefert den Vorgabewert oder den Wert aus `run(params={"breite": 140})`. Alle Parameter oben in der Datei. |
| `step("Bohrungen")` | Bauschritt, erscheint in Kevins Statusleiste. Vor jedem Schritt aufrufen. |
| `show(obj, name, color=None, material=None)` | zeigt Part, Compound, Sketch, Kanten oder ein Builder-Ergebnis (`bp.part`) sofort an. Gleicher Name ersetzt. `/` im Namen bildet den Baum. |

- `color`: Hex wie `"#B8BEC4"`.
- `material`: Name aus dem Katalog von build123d, damit gibt es Masse in g. Gängige Namen: `aluminum` (nicht
  „aluminium“), `stainless`, `mild_steel`, `tool_steel`, `brass`, `copper`, `titanium`, `pla`, `petg`, `abs`, `asa`,
  `nylon`, `pmma`, `pom`, `oak`, `beech`, `birch`, `pine`, `mdf`, `rubber`. Unbekannte Namen meldet der Lauf mit
  Vorschlägen.
- Langsam aufbauen, wenn Kevin zuschauen soll: `run(slow_ms=400)`.

## build123d: Kurzreferenz und Fallen

**Algebra-Modus bevorzugen** (Objekte und Operatoren). Builder (`with BuildPart() as bp:`) nur, wo er klar hilft, etwa
für Bohrungen auf einer Fläche. Ergebnis eines Builders ist `bp.part`, nicht `bp`.

- **Ausrichtung:** `Box`, `Cylinder` und `Sphere` sind standardmäßig um den Ursprung **zentriert** (eine Box der Höhe 10
  reicht von z = −5 bis +5). Auf die XY-Ebene stellen: `align=(Align.CENTER, Align.CENTER, Align.MIN)`.
- **Lage:** `Pos(x, y, z) * teil` verschiebt, `Rot(x, y, z) * teil` dreht in Grad um den Ursprung. Gelesen wird von
  rechts nach links: `Pos(100, 0, 0) * Rot(0, 0, 90) * teil` dreht erst und schiebt dann. Andersherum kreist das Teil um
  den Ursprung. `Rot(90, 0, 0)` legt die Z-Achse eines Zylinders auf −Y.
- **Boolesch:** `a + b` vereinigen, `a - b` abziehen, `a & b` Schnittmenge. Listen gehen auch: `platte -= [Pos(x, 0, 0)
  * zyl for x in xs]` oder `platte -= GridLocations(40, 20, 2, 2) * Cylinder(3, 10)`.
- **Werkzeugkörper überstehen lassen:** Durchgangsbohrungen und Schlitze länger als das Material machen (z. B.
  `dicke + 2`, um 1 nach unten versetzt). Genau bündige Flächen hinterlassen sonst Häute oder kaputte Flächen.
  Beim Vereinigen gilt dasselbe: Teile leicht überlappen lassen, nicht nur berühren.
- **Kanten und Flächen wählen:**
  - `teil.edges().filter_by(Axis.Z)`: Kanten parallel zu Z (senkrechte Ecken)
  - `teil.edges().group_by(Axis.Z)[-1]`: oberste Kanten, `[0]` unterste
  - `teil.faces().sort_by(Axis.Z)[-1]`: oberste Fläche
  - `teil.edges().filter_by(GeomType.CIRCLE)`: Kreiskanten (Bohrungsränder)
  - `teil.edges().filter_by(Axis.Z).group_by(SortBy.DISTANCE)[-1]`: nur die äußersten senkrechten Kanten
  - Kurzformen: `|` = filter_by, `>` = sort_by, `>>` = group_by(...)[-1], `<<` = group_by(...)[0]
- **Fillet und Fase:** `teil = fillet(kanten, radius=4)` und `teil = chamfer(kanten, length=1)`. Das Ergebnis neu
  zuweisen. Der Radius muss kleiner sein als die halbe Wandstärke dort. `filter_by(Axis.Z)` erfasst nach dem Bohren
  auch die Nahtkanten der Bohrungen; deshalb Ecken vor dem Bohren runden oder die Auswahl eingrenzen. Scheitert ein
  Fillet („command not done“), ist meist der Radius zu groß oder die Auswahl zu breit.
- **Skizzen:** `extrude(Plane.XY.offset(10) * (Rectangle(40, 20) - Circle(5)), amount=5)`,
  `revolve(Plane.XZ * Pos(20, 0) * Rectangle(4, 10), Axis.Z)`, `mirror(teil, about=Plane.YZ)`,
  `Text("KEV", font_size=10)`.
- **Bohrungen im Builder** (Bohrung geht von der gewählten Fläche ins Material):

  ```python
  with BuildPart() as bp:
      Box(60, 40, 10)
      with Locations(bp.faces().sort_by(Axis.Z)[-1]):
          with GridLocations(40, 20, 2, 2):
              CounterBoreHole(radius=3.3, counter_bore_radius=5.5, counter_bore_depth=6.4)
  show(bp.part, "Deckel")
  ```

  `Hole(radius)`, `CounterBoreHole(...)` und `CounterSinkHole(radius, counter_sink_radius, counter_sink_angle=90)` gehen
  nur im Builder. **Falle:** `CounterSinkHole` nimmt standardmäßig 82° (Zoll-Norm). Metrische Senkschrauben brauchen
  `counter_sink_angle=90`.

### Löcher für Schrauben (Durchmesser in mm)

| Gewinde | Durchgang mittel (ISO 273) | Kernloch für Gewinde | Senkung Zylinderkopf ISO 4762 (Ø × Tiefe) | Senkung 90° ISO 10642 (Ø) |
|---|---|---|---|---|
| M3 | 3,4 | 2,5 | 6,5 × 3,4 | 6,7 |
| M4 | 4,5 | 3,3 | 8 × 4,4 | 9,0 |
| M5 | 5,5 | 4,2 | 10 × 5,4 | 11,2 |
| M6 | 6,6 | 5,0 | 11 × 6,4 | 13,4 |
| M8 | 9,0 | 6,8 | 15 × 8,6 | 17,9 |
| M10 | 11,0 | 8,5 | 18 × 10,6 | 22,4 |

Für den 3D-Druck Löcher 0,2 bis 0,3 mm größer und Passungen mit Spiel. Rohrmaße sind Außendurchmesser (42,4 mm =
DN 32, 1¼ Zoll).

## Benennung und Baugruppen

- Jedes echte Teil bekommt einen sprechenden deutschen Namen: „Grundplatte“, „Lasche“, „Schelle“.
- Baugruppen über `/`: „Halter/Grundplatte“, „Halter/Schelle“. Gleiche Teile nummerieren: „Schrauben/M6x20 1“.
- Ein Teil nach jedem Bauschritt mit demselben Namen erneut zeigen. So sieht Kevin es wachsen.
- Hilfsgeometrie (Werkzeugkörper, Schnittkörper) nicht zeigen.
- Material setzen, wo es bekannt ist; die Masse steht dann in `run`, `parts` und `measure`.

## Referenzen und Auswahl

- `Halter/Lasche` ist das Teil, `Halter/Lasche#f3` Fläche 3, `#e2` Kante 2, `#v1` Punkt 1. Die Nummer folgt
  `teil.faces()`, `teil.edges()` und `teil.vertices()` des zuletzt gezeigten Objekts.
- Referenzen gelten **nur für einen Lauf**. Nach jedem `run` neu holen, nie alte Nummern wiederverwenden.
- Flächennummer finden: `execute("[(i, f.geom_type.name, round(f.area, 1), f.center()) for i, f in
  enumerate(platte.faces())]")` mit der Variablen des gezeigten Teils.
- Sagt Kevin „diese Bohrung“, „hier“ oder „das da“: zuerst `selection`. Sie liefert seine angeklickten Referenzen samt
  Werten (Typ, Fläche, Radius).

## Messen

- `measure(["Grundplatte#f3"])`: Eigenschaften eines Elements (Fläche, Normale, Radius, Länge, Lage, beim Teil Hüllmaß,
  Volumen, Masse).
- `measure(["Lasche#f2", "Grundplatte#f0"])`: kleinster Abstand mit dx, dy, dz und beiden Punkten, Winkel, Abstand
  paralleler Flächen. Zwei Bohrungswände (Zylinderflächen) ergeben den Achsabstand.
- `show=True` (Standard) blendet das Maß im Viewer ein. Werte stimmen exakt (OCCT), nicht aus dem Bild schätzen.
- Rechnungen und Abfragen im Modell mit `execute` (z. B. `platte.volume`, `schelle.bounding_box()`), ohne model.py zu
  ändern.

## Kevin etwas zeigen

| Werkzeug | Zweck |
|---|---|
| `focus(["Halter/Lasche"])` | Kamera fährt hin (animiert) |
| `highlight(refs, color="orange", label="M6")` | einfärben, beschriften; `clear=True` entfernt alte |
| `annotate("dimension", [[x,y,z],[x,y,z]])` | Maßlinie (Text = Abstand, wenn leer); auch `arrow`, `label` |
| `clear_annotations()` | alle Anmerkungen weg (oder `ids=[...]`) |
| `visibility("isolate", ["Halter/Lasche"])` | nur diese Teile; `show_all` stellt alles wieder her |
| `section(True, axis="y", offset=0)` | Schnitt; `section(False)` hebt ihn auf |
| `view(standard="front", projection="orthographic", fit=True)` | Standardansicht, Darstellung (`xray`, `wireframe`), `explode=0.6` |

„Zoom auf die Lasche und zeig sie von der Seite“: `view(standard="right", projection="orthographic")`, dann
`focus(["Halter/Lasche"])`. Kevin sieht das Ergebnis selbst im Viewer.

## Bilder

Screenshots nur, wenn Kevin ausdrücklich ein Bild will. Er sieht den Viewer beim Arbeiten selbst, und jedes Bild hält
die Generierung auf. Geprüft wird mit den Zahlen aus `run`, `parts` und `measure`.

- `screenshot()` zeigt genau Kevins Ansicht, 1280 × 800 px. Größer nur, wenn Details fehlen.
- `screenshot(view="iso")` rendert offscreen eine andere Ansicht, ohne Kevins Kamera zu bewegen.
- `mm_per_px` gibt es nur in paralleler Projektion. Maße trotzdem mit `measure` bestätigen.

## Export

`export(["step", "stl", "3mf"])` schreibt nach `<Projekt>/output/`. STEP für CAD und Fertigung, STL oder 3MF für den
Bambu-Drucker, GLB für Ansichten. `parts=["Halter/Schelle"]` exportiert nur diese Teile.

## Wenn etwas hakt

| Meldung | Bedeutung |
|---|---|
| Lauf fehlgeschlagen in Zeile N | Fehler in model.py; Auszug lesen, korrigieren, `run` |
| Unbekannte oder veraltete Referenz | nach dem letzten Lauf neu holen (`parts`, `selection`, `execute`) |
| App nicht verbunden | der Kernel läuft, die App hängt (noch) nicht an ihm; kurz warten, sonst Kevin bitten, Kev CAD zu öffnen |
| Kev CAD läuft nicht – bitte starten | die Brücke erreicht die App nicht; Kevin bitten, Kev CAD zu starten |
