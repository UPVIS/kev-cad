---
name: kev-cad
description: Leitfaden für Kev CAD, Kevins nativen CAD-Viewer auf dem Mac (MCP-Server „kevcad“, Werkzeuge wie run, screenshot, measure). Verwenden, sobald Kevin in Kev CAD ein 3D-Modell bauen, ändern, vermessen, ansehen oder exportieren will – Halter, Gehäuse, Bauteile, Möbel, Baugruppen als model.py mit build123d, die sich live im Viewer aufbauen. Auch bei „bau mir …“, „mach die Bohrung größer“, „wie weit ist das vom Rand weg“, „zeig mir die Lasche von der Seite“, „was hab ich angeklickt“, „exportier als STEP/STL/3MF“ in einem Kev-CAD-Projekt, ebenso bei Lagerteilen (Rohre, Profile, Platten, Holz, Schrauben aus dem Katalog), Stückliste, Zuschnitt, Gewicht und Kosten („was kostet das“, „wie viele Stangen“), 3D-Druckteilen und Animationen („lass den Wagen rollen“, „Kollision prüfen“, „mach ein Video davon“).
---

# Kev CAD

Ein Modell ist `model.py` im Projektordner (build123d, Millimeter, Z nach oben). Der Kernel führt die Datei aus, jedes
`show()` erscheint sofort im Viewer, Kevin sieht beim Bauen zu. Die Datei ist die Quelle der Wahrheit: Änderungen immer
dort, nie nur per `execute`.

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

1. `status`: offenes Projekt, Pfad von model.py, letzter Lauf, Kevins Auswahl, Inventar-Regel.
2. Kein Projekt: `project_new("Wandhalter")` oder `project_open("Wandhalter")`. Ein bloßer Name landet in
   `~/Documents/Kev CAD/<Name>`.
3. Teile im Lager suchen: `stock_search("vierkantrohr 40x40x3")`, Materialien mit `material_list` (siehe
   Inventar-Regel).
4. model.py mit den eigenen Dateiwerkzeugen schreiben oder ändern (Pfad aus `status`). `model_write` nur, wenn es keine
   Dateiwerkzeuge gibt.
5. `run`: liefert jedes Teil mit Hüllmaß, Volumen und Masse und kurz die Summen der Stückliste. Ein Fehler kommt als
   isError mit Zeile, Auszug und Hinweis; die letzte gute Geometrie bleibt stehen. Korrigieren, wieder `run`.
6. Prüfen: Zahlen aus `run` mit der Aufgabe vergleichen, wichtige Sollmaße mit `measure` nachmessen, `bom` für
   Stückliste und Zuschnitt. Kein `screenshot`: Kevin sieht den Viewer live und will das Ergebnis schnell (siehe
   „Bilder“).
7. Kevin kurz berichten: was gebaut ist, Hauptmaße, Masse, Kosten (Richtpreise), offene Annahmen. Bei Bedarf `focus`,
   `highlight`, `annotate` nutzen, damit er es im Viewer sieht.

Speichert Kevin model.py selbst und ist Auto-Lauf an, rechnet der Kernel von allein. `run` wartet dann auf diesen Lauf,
statt doppelt zu rechnen.

## Inventar-Regel

Standard für jedes Projekt: **Gebaut wird nur aus dem Inventar.**

- Jedes Teil in `show()` stammt aus `lager.teil(...).verbauen(...)` oder ist ausdrücklich ein 3D-Druckteil:
  `lager.druckteil(form, "Halter/Schelle", material="petg")`. Druckmaterial muss freigegeben und druckbar sein
  (`material_list` zeigt „druckbar“: PLA, PETG, ABS, ASA, TPU 95A, PA, PA-CF, PC-Filament, PLA-CF, Standardharz);
  `verfahren="3d-druck"` (Standard) oder `"harzdruck"`.
- Materialien nur aus dem Katalog (id oder Alias), auch bei `show(material=...)`. Unbekannte oder nur vorgeschlagene
  Materialien brechen den Lauf mit Vorschlägen ab.
- Nichts erfinden. Fehlt ein Teil oder Material: erst `stock_search` mit anderen Wörtern, dann Kevin fragen. Nur auf
  seinen Wunsch mit `stock_define` bzw. `material_define` vorschlagen. Ein Vorschlag „wartet auf Kevins Freigabe im
  Lagerkatalog“ und lässt sich vorher nicht verbauen; Kevin gibt ihn im Lagerkatalog-Fenster frei oder lehnt ab.
  Freigegebene Einträge ändert nur Kevin.
- Verstöße: `run` meldet „Inventar-Regel: 2 Teile sind nicht aus dem Inventar: …“ als isError. Die Geometrie ist zu
  sehen, aber Export (STEP, STL, 3MF, Stückliste) wird verweigert. Passendes Lagerteil verbauen, als Druckteil
  kennzeichnen oder Kevin bitten, das Lagerteil anzulegen.
- Abschalten kann nur Kevin, je Projekt (kevcad.json `"inventar_regel": false`, etwa für Nachbauten aus Fotos). Diese
  Einstellung nie selbst ändern. Ist die Regel aus, gelten auch Materialnamen aus build123d (`aluminum`, `oak`, …) und
  frei modellierte Teile mit Material erscheinen als „Eigenteil“.

## Gerüst von model.py

```python
from build123d import *
from kevcad import lager, param, show, step

hoehe = param("hoehe", 120)        # Länge der Grundplatte
abstand = param("abstand", 70)     # Wand bis Rohrmitte
loch = param("loch", 6.6)          # Durchgangsbohrung M6, mittel
schelle_h = param("schelle_h", 30)
wand = param("wand", 4)

flach = lager.teil("flach", b=40, s=5, material="stahl-s235")   # vorher mit stock_search gefunden
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
| `show(obj, name, color=None, material=None)` | zeigt Part, Compound, Sketch, Kanten oder ein Builder-Ergebnis (`bp.part`) sofort an. Gleicher Name ersetzt. `/` im Namen bildet den Baum. |
| `lager.teil(id)` / `lager.teil(art, **maße, material=None)` | Lagerteil aus dem Katalog, genau passend, sonst Fehler mit Vorschlägen. |
| `lager.suche("rohr 42,4")` | Liste von Lagerteilen (zum Ausprobieren in `execute`). |
| `teil.verbauen(...)` | build123d-Teil mit Name, Farbe und Material, dazu eine Stücklistenzeile (siehe unten). |
| `lager.druckteil(form, name, material, verfahren="3d-druck")` | selbst konstruiertes Druckteil; Material druckbar. |

- `color`: Hex wie `"#B8BEC4"`; Lager- und Druckteile haben schon die Farbe ihres Materials.
- `material`: id oder Alias aus dem Katalog (`material_list`), z. B. `stahl-s235`, `edelstahl`, `alu`,
  `multiplex-birke`, `petg`. Lagerteile tragen ihr Material selbst, `material=` ist dort nicht nötig.
- Langsam aufbauen, wenn Kevin zuschauen soll: `run(slow_ms=400)`.

## Lagerteile verbauen

- Stangenware (Rohr, Vierkant-/Rechteckrohr, Flach-, Rund-, Vierkantstahl, Winkel, U-Profil, Nutprofil, Holz):
  `teil.verbauen(laenge=842, name="Gestell/Bein vorn links", gehrung=(0, 0))`. Das Teil liegt entlang +Z ab z = 0,
  der Querschnitt mittig. `laenge` ist das **Zuschnittmaß an der längsten Kante**. `gehrung=(anfang, ende)` in Grad um
  die lokale X-Achse: positiv lässt die Kante bei +Y lang (Rahmenleiste mit Außenkante bei +Y), negativ die bei -Y.
  `drehung=90` dreht den Querschnitt vorher um Z (Gehrung über die andere Seite). Querschnitte: Breite b in X,
  Höhe h bzw. Dicke s in Y; Winkel mit Schenkel a nach +Y und b nach +X; U-Profil nach +X offen.
- Platten: `platte.verbauen(breite=800, tiefe=600, name="Deckel")` in der XY-Ebene ab z = 0, mittig; oder
  `form=Rectangle(800, 600) - Circle(40)` (Skizze in XY).
- Schrauben: `schraube.verbauen(laenge=60, name="Schrauben/M8x60 1")` (bd_warehouse, Kopf auf z = 0, Schaft nach -Z,
  ohne Gewinde); Muttern und Scheiben ohne `laenge`.
- **Name in `show()` gleich wie in `verbauen()`.** Dann kennt die Stückliste das gezeigte Teil, auch nach Verschieben,
  Drehen oder Bohren. Gleiche Teile durchnummerieren: „Schrauben/M8x60 1“ … „8“.
- Rahmen mit Gehrung: Leiste mit `gehrung=(45, 45)` verbauen, erst um die eigene Achse drehen (lange Kante nach außen),
  dann hinlegen, dann schieben. Beispiel: `samples/gestell/model.py`.
- Jede `verbauen`-Zeile steht in der Stückliste, auch wenn das Teil später gebohrt wird. Gleiche Lagerteile mit
  gleicher Länge und Gehrung werden zusammengefasst.

## Stückliste

- `bom`: Positionen (Anzahl, Maße, Gehrung, Material, kg, €), Zuschnitt je Stangenware („Stange 1: 882 + 882 + … =
  5.394 mm, Rest 606 mm“, Sägeschnitt 3 mm, Verschnitt in %), Summen mit Richtpreis-Hinweis, Hinweise (etwa nicht
  zugeordnete Lagerteile). `bom(format="csv")` liefert CSV, `export(["bom_csv"])` schreibt die Datei.
- Preise sind Richtwerte mit Stand; so auch an Kevin weitergeben.

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
- Lagerteile und Druckteile tragen Material, Farbe und Masse; die Masse steht in `run`, `parts` und `measure`.

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

## Animation

Bewegungen gehören wie die Geometrie in `model.py`: `from kevcad import animation`, am Ende nach allen `show()`.
Ziele sind Teilnamen oder Baugruppenpräfixe („Rollwagen“ bewegt alle „Rollwagen/…“). Zeiten in s, Längen in mm,
Winkel in Grad. Der Kernel rechnet daraus je Bild die Lage jedes Teils, die App spielt flüssig ab (Zeitleiste unter dem
Viewport, Leertaste, Pfeiltasten, Umschalt+Pfeil für Anfang und Ende).

```python
fahrt = animation(dauer=8, fps=30, name="Fahrt")          # mehrere Animationen je Projekt mit eigenem Namen
fahrt.bewege("Rollwagen", nach=(2000, 0, 0), von=1, bis=7, kurve="weich")
for i in range(1, 5):                                     # Räder drehen mit: Winkel = Strecke / Radius
    fahrt.rolle(f"Rollwagen/Lenkrolle {i}/Rad", auf="Rollwagen", radius=50, achse="y")
fahrt.folge("Kugelschieber", "Rollwagen")                 # fährt starr mit
fahrt.rolle("Bowlingball", auf="Rollwagen", radius=108.5) # rollt frei vor dem Schieber
fahrt.ansicht(0, lage=(-900, -1800, 700), ziel=(300, -340, 150), mit="Rollwagen/Rahmen")  # Kamerafahrt
```

| Spur | Wirkung |
|---|---|
| `bewege(name, nach=(dx,dy,dz), von, bis, kurve)` | verschieben; `kurve` `"linear"`, `"weich"`, `"ein"`, `"aus"` |
| `drehe(name, achse, winkel, von, bis, kurve)` | drehen; `achse=((x,y,z),(dx,dy,dz))`, `Axis`, Richtung oder `"x"/"y"/"z"` durch die Teilmitte |
| `pfad(name, punkte, von, bis, ausrichten=False, spline=False)` | entlang Polylinie oder Spline, gleichmäßig nach Bogenlänge |
| `rolle(name, auf, radius, achse=None)` | Rollbedingung; mit Achse wie ein Rad, ohne frei wie eine Kugel |
| `folge(name, eltern)` | Kind folgt allen Bewegungen des Elternteils |
| `gelenk(name, art="dreh"/"schub", achse, werte={t: wert}, grenzen=(min, max), eltern)` | Gelenkwinkel/-weg über die Zeit, an den Grenzen begrenzt (Warnung) |
| `sichtbar(name, an, zeit)` / `ansicht(zeit, lage, ziel, bildwinkel, mit)` / `erlaube(a, b)` | ein-/ausblenden, Kamerafahrt, gewollte Berührung |

Drehachsen gelten in der Ruhelage (Koordinaten wie in model.py); Drehungen wirken vor Verschiebungen, beides vor der
Bewegung des Elternteils. Ein unbekanntes Teil oder eine Zeit außerhalb der Dauer bricht den Lauf mit Zeile ab.

- `kollision_pruefen(name)` prüft jedes 3. Bild exakt (OCCT-Schnittvolumen, Berühren ist erlaubt) und meldet Zeit,
  Teilpaar, Eindringtiefe und Volumen; die App markiert sie auf der Zeitleiste und färbt das Paar rot. **Jede
  Durchdringung muss gelöst werden**, gewollte Anlage mit `erlaube` oder Luft im Modell.
- `animation_abspielen(name, an=True, schleife=False)`, `animation_springen(zeit)`, `animation_liste()`.
- `animation_video(name, breite=1920)` schreibt ein H.264-MP4 (oder `format="prores"`) nach
  `<Projekt>/output/animationen/` aus der Viewer-Sicht bzw. der Kamerafahrt.

## Export

`export(["step", "stl", "3mf"])` schreibt nach `<Projekt>/output/`, `export(["bom_csv"])` die Stückliste als CSV. STEP für CAD und Fertigung, STL oder 3MF für den
Bambu-Drucker, GLB für Ansichten. `parts=["Halter/Schelle"]` exportiert nur diese Teile.

## Wenn etwas hakt

| Meldung | Bedeutung |
|---|---|
| Lauf fehlgeschlagen in Zeile N | Fehler in model.py; Auszug lesen, korrigieren, `run` |
| Unbekannte oder veraltete Referenz | nach dem letzten Lauf neu holen (`parts`, `selection`, `execute`) |
| App nicht verbunden | der Kernel läuft, die App hängt (noch) nicht an ihm; kurz warten, sonst Kevin bitten, Kev CAD zu öffnen |
| Kev CAD läuft nicht – bitte starten | die Brücke erreicht die App nicht; Kevin bitten, Kev CAD zu starten |
| Inventar-Regel: … nicht aus dem Inventar | Teil ohne `verbauen`/`druckteil` gezeigt; Lagerteil suchen, Druckteil kennzeichnen oder Kevin fragen |
| … wartet auf Kevins Freigabe im Lagerkatalog | Vorschlag aus `stock_define`/`material_define`; Kevin gibt ihn im Lagerkatalog frei |
| Material '…' gibt es im Katalog nicht | nur Katalogmaterialien (`material_list`); fehlt eins, Kevin fragen |
| Lagerteil „…“ ist keinem gezeigten Teil zugeordnet | Name in `show()` anders als in `verbauen()`; gleich benennen |
| Export verweigert | erst die Verstöße gegen die Inventar-Regel beheben |
