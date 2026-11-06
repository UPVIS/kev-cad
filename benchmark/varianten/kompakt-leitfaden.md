# Kev CAD: Leitfaden in einem Stück

Du arbeitest in Kev CAD, Kevins CAD auf dem Mac. Ein Modell ist `model.py` im Projektordner (build123d, Millimeter,
Z nach oben); der Kernel führt die Datei aus, jedes `show()` erscheint sofort in Kevins Viewer. Kevin will Tempo:
wenige Runden, wenig lesen, keine Bilder an ihn. Alles, was du sonst im Skill kev-cad nachlesen würdest, steht hier;
Einzelheiten bei Bedarf in den Dateien unter `{REFERENZ}` (Liste am Ende), nur lesen, wenn du sie wirklich brauchst.

## Ablauf in wenigen Runden

1. Erste Runde: `status` (Pfad von model.py, Befunde). Bei einer Änderung zusätzlich model.py lesen, beides in
   derselben Runde. Werkzeuge ohne Abhängigkeit immer gemeinsam in einer Runde aufrufen.
2. Erst vollständig planen, dann **model.py schreiben und `run` in derselben Runde** aufrufen. Beim Planen schon die
   Druckregeln unten einbauen (Bettfase, Wände, Bohrungen), damit kein zweiter Durchgang nötig ist.
3. `run` meldet neue und geänderte Teile mit Maßen, Volumen und neue Befunde. Stimmen Maße und gibt es keine Fehler
   und Warnungen, ist das Modell fertig; nur gezielt nachmessen (`execute` oder `measure`), wenn etwas offen ist, was
   der Lauf nicht zeigt (etwa Bohrungsdurchmesser). Alle Befunde in einem Zug beheben, dann einmal `run`. Sagt `run`,
   die Prüfung laufe noch, vor dem Fertigmelden `pruefen()`.
4. Letzte Runde: `versionen(aktion="meilenstein", titel=…, notiz=…)` und im selben Zug der kurze Bericht an Kevin:
   Hauptmaße, Masse, Annahmen, Druckausrichtung neuer Druckteile.
5. Maße ausprobieren ohne Dateiänderung: `run(params={"breite": 140})` überschreibt `param()`-Werte für einen Lauf.
   Was bleiben soll, steht danach in model.py.

## Gerüst

```python
from build123d import *
from kevcad import lager, param, show, step

breite = param("breite", 120)        # alle Maße als param() oben
dicke = param("dicke", 6)

step("Platte")                        # vor jedem Bauschritt
with BuildPart() as bp:
    with BuildSketch():
        RectangleRounded(breite, 80, 5)
    extrude(amount=dicke)
    with Locations(bp.faces().sort_by(Axis.Z)[-1]):
        with GridLocations(100, 60, 2, 2):
            Hole(3.3)                   # Radius; Hole geht von der Fläche ins Material, durch das ganze Teil
show(lager.druckteil(bp.part, "Halter/Platte", material="petg"), "Halter/Platte")
```

- `show(obj, "Gruppe/Teil")`: sprechende deutsche Namen, `/` bildet den Baum, gleicher Name ersetzt das Teil.
- **Inventar-Regel:** jedes gezeigte Teil ist ein Lagerteil (`lager.teil(id).verbauen(laenge, "Name")`, gleicher Name
  in `show`), ein freigegebenes Zukaufteil (`lager.zukauf(id).verbauen("Name")`) oder ein Druckteil
  (`lager.druckteil(form, "Name", material="petg")`). Lagerteile mit `katalog(suche="…")` finden; nichts erfinden.
  Stangenware (Rohre, Profile, Flachstahl) liegt nach `verbauen` entlang +Z ab z = 0, Querschnitt mittig; Platten in
  XY ab z = 0, mittig. Verschieben mit `teil.moved(Location((x, y, z)))` oder `Pos(x, y, z) * teil`.
- `param(name, wert)`, `step(text)`; Lagerteile tragen ihr Material selbst.

## build123d: das Wichtigste und die Fallen

- `Box`, `Cylinder`, `Sphere` sind um den Ursprung **zentriert**; auf XY stellen mit
  `align=(Align.CENTER, Align.CENTER, Align.MIN)`.
- `Pos(x, y, z) * teil` verschiebt, `Rot(x, y, z) * teil` dreht (Grad, um den Ursprung); von rechts nach links lesen.
- Boolesch: `a + b`, `a - b`, `a & b`; Werkzeugkörper für Durchbrüche überstehen lassen (nie bündig).
- Im Builder: `Cylinder`, `Box` mit `mode=Mode.SUBTRACT` ziehen ab; `Locations(...)`, `GridLocations(dx, dy, nx, ny)`,
  `PolarLocations(radius, anzahl)` setzen Lagen; `Hole(r, depth=t)` für Sacklöcher; `Hole`, `CounterBoreHole`,
  `CounterSinkHole(…, counter_sink_angle=90)` (metrisch 90°, Vorgabe 82°) nur im Builder.
- Kanten: `edges().filter_by(Axis.Z)` senkrecht, `group_by(Axis.Z)[-1]` oben, `[0]` unten,
  `filter_by(GeomType.CIRCLE)` Kreise; `fillet(kanten, radius=r)`, `chamfer(kanten, length=l)` (Ergebnis neu
  zuweisen). Ecken vor dem Bohren runden, sonst greift `filter_by(Axis.Z)` auch Bohrungskanten. Radius kleiner als die
  halbe Wand.
- Skizzen: `extrude(Plane.XY.offset(z) * (Rectangle(a, b) - Circle(r)), amount=h)`, `revolve(...)`, `mirror(...)`,
  `offset(teil, amount=-wand, openings=fläche)` für Schalen.
- Bohrungen für Schrauben: M3 Durchgang 3,4, M4 4,5, M5 5,5, M6 6,6; Kernloch zum Schneiden ≈ 0,8 × d.

## Druckteile (Kevins Bambu Lab P1P, offen; PLA oder PETG)

- Bauraum 256 × 256 × 250 mm (vorne links 18 × 28 mm gesperrt); Düse 0,4, Schicht 0,2.
- Wände als Vielfache von ~0,42 mm, mindestens 1,2 mm, tragend 2–3 mm; Merkmale nicht unter 0,8 mm.
- Überhänge bis 45° ohne Stütze, Unterseiten fasen statt runden, Brücken höchstens ~15 mm.
- **Bettseite mit Fase 0,4–0,6 mm** gegen Elefantenfuß; große ebene Auflage einplanen.
- Waagrechte Bohrungen als Tropfen (Spitze oben); Bohrungen drucken 0,1–0,2 mm zu klein.
- Spiel je Seite: Presspassung 0,1, Spielpassung 0,2, beweglich 0,3–0,5 mm.
- Gewinde: Gewindeeinsätze (Tasche nach Herstellermaß) oder eingeschlossene Muttern; Kernloch für Schrauben 0,8 × d.
- Last längs der Schichten führen; Innenkanten verrunden. Die Druckprüfung läuft nach jedem `run` von selbst
  (Befunde `druck_*`); Ausrichtung wählt sie selbst, vorgeben mit `ausrichtung="-z"` usw.

## Prüfung

Nach jedem Lauf prüft der Kernel: keine Durchdringung, nichts schwebt, alles steht und lässt sich einbauen. Fehler
beheben, Warnungen beheben oder begründen, nicht wegerklären.

## Nachschlagen (nur bei Bedarf, unter `{REFERENZ}`)

`modell.md` (API und Rezepte), `3d-druck.md` (Druckregeln mit Rezepten: Tropfenbohrung, Passungen, Einsätze,
Schnapphaken), `lager.md` (Lager und Zukaufteile), `pruefung.md`, `bedingungen.md`, `konstruktion.md`
(15 Konstruktionsregeln), `werkzeuge.md` (alle Parameter), `ablauf.md`.
