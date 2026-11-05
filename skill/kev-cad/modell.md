# model.py und build123d

Teil des Skills kev-cad. Gerüst von model.py, die API von kevcad, build123d-Kurzreferenz mit Fallen, Lochtabellen, Benennung.

## Gerüst von model.py

```python
from build123d import *
from kevcad import lager, param, show, step

hoehe = param("hoehe", 120)        # Länge der Grundplatte
abstand = param("abstand", 70)     # Wand bis Rohrmitte
loch = param("loch", 6.6)          # Durchgangsbohrung M6, mittel
schelle_h = param("schelle_h", 30)
wand = param("wand", 4)

flach = lager.teil("flach", b=40, s=5, material="stahl-s235")   # vorher mit katalog gefunden
rohr = lager.teil("rohr-en10220-42.4x2.0")
blech, rohr_d = flach.masse["s"], rohr.masse["d"]

step("Grundplatte")
platte = Pos(0, blech / 2, -hoehe / 2) * flach.verbauen(laenge=hoehe, name="Halter/Grundplatte")
show(platte, "Halter/Grundplatte")

step("Bohrungen")
for z in (-40, 40):
    platte -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(loch / 2, 3 * blech)
show(platte, "Halter/Grundplatte")   # gleicher Name: ersetzt, man sieht das Teil wachsen; bleibt Lagerteil

step("Lasche")
ring_r = rohr_d / 2 + wand
lasche = flach.verbauen(laenge=abstand - ring_r - blech, name="Halter/Lasche")
show(Pos(0, blech, 0) * Rot(-90, 0, 0) * lasche, "Halter/Lasche")   # erst drehen, dann schieben

step("Schelle")
ring = Pos(0, abstand, 0) * (Cylinder(ring_r, schelle_h) - Cylinder(rohr_d / 2, schelle_h + 2))
show(lager.druckteil(ring, "Halter/Schelle", material="petg"), "Halter/Schelle")

step("Rohr")
show(Pos(0, abstand, -150) * rohr.verbauen(laenge=300, name="Rohr"), "Rohr")
```

## API von kevcad

| Aufruf | Wirkung |
|---|---|
| `param(name, wert, min=None, max=None)` | benannter Parameter (mm). Liefert den Vorgabewert oder den Wert aus `run(params={"breite": 140})`. Alle Parameter oben in der Datei. |
| `step("Bohrungen")` | Bauschritt, erscheint in Kevins Statusleiste. Vor jedem Schritt aufrufen. |
| `show(obj, name, color=None, material=None, kulisse=False)` | zeigt Part, Compound, Sketch, Kanten oder ein Builder-Ergebnis (`bp.part`) sofort an. Gleicher Name ersetzt. `/` im Namen bildet den Baum. `kulisse=True`: Umgebung (siehe „Inventar-Regel“, Kulisse). |
| `lager.kulisse(form, name=None)` | kennzeichnet eine Form als Kulisse (gleich wie `show(..., kulisse=True)`). |
| `lager.teil(id)` / `lager.teil(art, **maße, material=None)` | Lagerteil aus dem Katalog, genau passend, sonst Fehler mit Vorschlägen. |
| `lager.suche("rohr 42,4")` | Liste von Lagerteilen (zum Ausprobieren in `execute`). |
| `teil.verbauen(...)` | build123d-Teil mit Name, Farbe und Material, dazu eine Stücklistenzeile (siehe unten). |
| `lager.druckteil(form, name, material, verfahren="3d-druck", ausrichtung=None, zweck=None, anzahl=None, gedruckt=False, neu_drucken=False, spaeter=False)` | selbst konstruiertes Druckteil; Material druckbar; Druckprüfung bei jedem Lauf, `ausrichtung` gibt die Lage aufs Bett vor (None = automatisch); `zweck` (zier, funktion, tragend, bewegt, aussen) bestimmt die Empfehlungen der Druckvorschau, `anzahl` nur für zusätzliche Stück; `gedruckt=True` für schon gedruckte Teile (Form in gedruckt.json festgeschrieben, Änderung = Warnung `gedruckt_geaendert`, `neu_drucken=True` einen Lauf lang schreibt die neue Form fest); `spaeter=True` für Teile, die erst später gedruckt werden (in der Druckvorschau gelistet, auf keiner Platte, nicht im 3MF). Vor jedem Druck oder Druckexport Kevin nach dem Filament fragen (`druck(aktion="filamente")`, dann `druck(aktion="export", filament={"petg": "<id>"})`; 3d-druck.md Abschnitt 11a). |
| `topologie.optimieren(teil, szenario=None, behalten=0.4, schutz=None, ueberhang=False, fein=False, steg=6, bett=False, bohrungen=True, einsaetze=True, kontakt=True, iterationen=60, lager="kontakt", automatisch=True)` | topologieoptimiertes Druckteil (`from kevcad import topologie`): das Ergebnis aus `topologie/<teil>-<schlüssel>.brep`, solange es fehlt das Ausgangsteil (Rechnung im Hintergrund, danach neuer Lauf); Stückliste und Masse folgen dem neuen Volumen; `topologie.aus_datei(pfad, name, material)` verbaut eine gespeicherte Form als Druckteil; `lager="bohrungen"` für angeschraubte Halter (die Schrauben halten statt der Auflage). Siehe statik.md, „Topologie optimieren“. |
| `lager.zukauf(id)` → `.verbauen(name)`, `.bezugspunkt(name)` | Zukaufteil mit Hersteller-CAD, Skript oder Ersatzkörper (siehe „Zukaufteile“). |
| `erlaubt_ueberlappung(a, b, grund="…")` | gewollte Überlappung, nur nach Rückfrage bei Kevin (siehe „Prüfen vor dem Fertigmelden“). |
| `montage(teil, richtung=, nach=, werkzeug=, baugruppe=, schnappt=, eingedruckt=)` | Einbau erklären, wo die Prüfung es nicht selbst wissen kann (siehe „Montagegerecht konstruieren“). |
| `befestigt(teil, grund="…")`, `boden(z)` | an Wand/Decke befestigt (nur nach Rückfrage), Bodenebene. |
| `import kevcad.bedingungen as bed` | Bezüge, Bedingungen, Gelenke, Befestigung, `bed.platziere(teil, …)` (Abschnitt „Teile über Bedingungen setzen“). |

- `color`: Hex wie `"#B8BEC4"`; Lager- und Druckteile haben schon die Farbe ihres Materials.
- `material`: id oder Alias aus dem Katalog (`katalog(art="material")`), z. B. `stahl-s235`, `edelstahl`, `alu`,
  `multiplex-birke`, `petg`. Lagerteile tragen ihr Material selbst, `material=` ist dort nicht nötig.
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

Zollgewinde (ASME B1.1; Kernloch 75 % und Durchgang „free fit“ der üblichen Bohrtabelle), Größe im Lagerteil z. B.
`"1/4-20"`, `"3/8-16 UNC"`, `"#10-24"`:

| Gewinde | Nenn-Ø | Steigung | Kernloch | Durchgang |
|---|---|---|---|---|
| #10-24 UNC | 4,83 | 1,06 | 3,8 | 5,1 |
| 1/4"-20 UNC (Kamera, Stativ) | 6,35 | 1,27 | 5,1 | 6,8 |
| 5/16"-18 UNC | 7,94 | 1,41 | 6,5 | 8,4 |
| 3/8"-16 UNC (Stativkopf) | 9,53 | 1,59 | 7,9 | 10,1 |
| 1/2"-13 UNC | 12,7 | 1,95 | 10,7 | 13,5 |

Für den 3D-Druck Löcher 0,2 bis 0,3 mm größer und Passungen mit Spiel. Rohrmaße sind Außendurchmesser (42,4 mm =
DN 32, 1¼ Zoll).

## Benennung und Baugruppen

- Jedes echte Teil bekommt einen sprechenden deutschen Namen: „Grundplatte“, „Lasche“, „Schelle“.
- Baugruppen über `/`: „Halter/Grundplatte“, „Halter/Schelle“. Gleiche Teile nummerieren: „Schrauben/M6x20 1“.
- Ein Teil nach jedem Bauschritt mit demselben Namen erneut zeigen. So sieht Kevin es wachsen.
- Hilfsgeometrie (Werkzeugkörper, Schnittkörper) nicht zeigen.
- Lagerteile und Druckteile tragen Material, Farbe und Masse; die Masse steht in `run`, `parts` und `measure`.
