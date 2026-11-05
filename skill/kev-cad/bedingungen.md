# Teile über Bedingungen setzen

Teil des Skills kev-cad. Bezüge, Montagebedingungen, Gelenke, Befestigung und Maßbedingungen in model.py.

## Teile über Bedingungen setzen (Kevin, 21.10.2026, gilt immer)

Wie in CAD-Programmen hängt jedes Teil über Bedingungen an seinem Gegenstück, nicht an frei gewählten Koordinaten.
Feste Regel neben Prüfungen, Druckregeln und Inventar-Regel: **Teile werden mit `platziere` gesetzt, jedes Teil ist mit
`verbinde` befestigt, Bewegliches ist ein Gelenk mit Bereich.** Kev CAD prüft alle Bedingungen nach jedem Lauf gegen
die echte Geometrie; verletzte sind Befunde wie eine Durchdringung (`run` isError, rot im Viewer, Export gesperrt).

```python
import kevcad.bedingungen as bed   # als Modul: kollidiert nicht mit eigenen Namen wie spiel, winkel, boden

platte = Box(200, 120, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Pos(60, 0, 5) * Cylinder(4.5, 20)
show(platte, "Halter/Platte")
klotz = Box(40, 30, 20)                                    # im eigenen System bauen, dann setzen
klotz = bed.platziere(klotz,
                      bed.auf((klotz, "unten"), (platte, "oben")),            # Fläche auf Fläche
                      bed.mittig((klotz, "mitte"), (platte, "mitte"), "xy"),   # mittig in X und Y
                      bed.parallel((klotz, "vorn"), (platte, "vorn")))        # nicht verdreht
show(klotz, "Halter/Klotz")
schraube = lager.teil("schraube-iso4762-m8").verbauen(laenge=25, name="Halter/Schraube")
schraube = bed.platziere(schraube, bed.in_bohrung(schraube, bed.bezug(platte, "bohrung", nahe=(60, 0, 0))))
show(schraube, "Halter/Schraube")
bed.verbinde(klotz, platte, art="kleben")                 # Befestigung (Pflicht für jedes Teil)
bed.verbinde(platte, bed.boden, art="aufliegen")
wand = param("wand", 2.0, min=1.2)                        # Grenzen: 0,8 ist ein Befund mit Soll, Ist und Lösung
```

- **Bezüge** über Namen, nie über Flächennummern: als Tupel `(teil, "unten")` oder `bed.bezug(teil, …)` mit
  `oben`/`unten` (±Z), `rechts`/`links` (±X), `hinten`/`vorn` (±Y, vorn = −Y), `mitte`, `schwerpunkt`, `achse`
  (größter Zylinder), `achse_x/y/z`, `bohrung` (mit `nahe=(x, y, z)`), `teil`; **Richtung einer Bohrung:** aus dem
  Loch heraus durch seine Öffnung (Sackloch), bei Durchgangsbohrungen in die positive Hauptrichtung (+Z, +X, +Y);
  `richtung="-x"` oder `(dx, dy, dz)` legt sie bei jedem Bezug mit Achse oder Normale fest, z. B.
  `bed.bezug(halter, "bohrung", nahe=p, richtung="+x")`. Gelenke zählen `bereich` und `weg` entlang der Richtung des
  **festen** (zweiten) Bezugs, also dort `richtung=` setzen, wenn + in eine bestimmte Richtung zeigen soll; eigene Auswahl
  `bed.bezug(teil, "Auflage", teil.faces().sort_by(Axis.Z)[0])` oder `lambda t: …`, dazu `Plane`, `Axis`, `Location`
  und Bezugspunkte aus dem Katalog; Teile auch über ihren Namen aus `show()` (`bed.verbinde("Gestell/Bein 1", …)`).
  `bed.boden` ist die Ebene z = 0. **Der erste Bezug gehört zum Teil, das sich anpasst** (bei `platziere` das bewegte).
- **Montage:** `auf` (Flächen gegenüber, `abstand=` für Luft), `buendig`, `konzentrisch`, `parallel`, `senkrecht`,
  `abstand(a, b, wert)`, `winkel(a, b, grad)`, `tangential` (Zylinder/Kugel an Ebene oder Zylinder), `mittig(…, "xy")`,
  `in_bohrung(schraube, bohrung, gewinde=False)` (konzentrisch, Kopf liegt auf, Durchmesser ISO 273 bzw. Kernloch und
  Länge geprüft). Teile im eigenen System bauen, mit `bed.platziere(teil, …)` setzen, danach erst bohren ist erlaubt
  (die Prüfung findet das Teil wieder); was danach noch verschoben wird, verschiebt seine Bezüge mit.
- **Gelenke** (Grundlage build123d-Joints, Freiheitsgrade für Animation und Prüfung): `drehgelenk(achse_bewegt,
  achse_fest, winkel=0, bereich=(min, max))`, `schiebegelenk(…, weg=0, bereich=…)`, `zylindergelenk`, `kugelgelenk`,
  `fest`. Mit `bereich` prüft jeder Lauf den ganzen Weg auf Kollision (`mitbewegt=[…]` für Teile, die mitfahren,
  `ignorieren=[…]`); Bedienteile mit `bedienung="finger" | "hand" | "werkzeug" | "fluegel"` oder `freiraum=mm` am
  `griff`. Hebel und Klappen prüfen den Freiraum am Griffpunkt über den Weg (finger 15, hand 25, werkzeug 10 mm). Teile,
  die um ihre eigene Achse gedreht werden (Flügelmutter, Flügelschraube, Drehknopf: `bedienung="fluegel"`, 10 mm; bei
  `"finger"`/`"hand"` ohne `griff` automatisch, wenn der Schwerpunkt auf der Drehachse liegt), prüfen den **Griffraum**:
  einen Ring um die Drehachse über der Auflage, bis Flügelspitze plus Freiraum, also nur auf der Griffseite. Beispiel:
  `bed.drehgelenk(achse("Flügelmutter M4"), achse("Gewindestift M4x30"), bereich=(0, 180), bedienung="fluegel")`.
  `gelenk.fuer_animation()` liefert Art, Achse und Grenzen für `animation.gelenk`.
- **Befestigung (B9):** jedes Teil `bed.verbinde(a, b, art="schraube" | "klemmung" | "steck" | "formschluss" |
  "kleben" | "aufliegen", mit=[schraube, mutter, scheibe])`. Geprüft wird, dass es die Verbindung wirklich gibt
  (Kontakt bzw. Spielpassung bis 0,5 mm; bei Schrauben fluchtende Bohrungen in beiden Teilen, Kopf und Mutter liegen
  auf) und dass alle Teile über Verbindungen am Boden hängen. Gelenke, `in_bohrung` und `auf` von oben zählen mit.
  In `mit=[…]` ordnet die Prüfung Schraube, Mutter, Scheibe und Gewindeeinsatz nach dem Lagerteil (`art`, `typ`) zu,
  sonst nach der Form: ein Ring mit Innenbohrung ist nie eine Schraube. Selbst gebaute Normteile deshalb mit
  `form.lagerteil = lager.teil("…")` kennzeichnen, wenn es sie im Katalog gibt. Zollgewinde (`1/4-20`, `3/8"-16 UNC`)
  gelten wie metrische.
  Kevin, 22.10.2026: Solange ein Modell kein `verbinde` nutzt, ist fehlende Befestigung nur ein Hinweis; sobald es
  `verbinde` nutzt, ist jede fehlende Angabe ein Fehler mit Exportsperre. Bei neuen Modellen gleich alles verbinden.
- **Bewegungen:** Die Gelenke in model.py sind die Quelle dafür, was sich wie bewegt (Bereich, Bedienung,
  mitbewegte Teile). `<projekt>/bewegungen.json` gilt nur noch für Teile ohne Gelenk; Einträge für Teile mit Gelenk
  werden übergangen (Kevin, 22.10.2026).
- **Maße:** `param(name, wert, min=, max=)`, `bed.gleich(a, b)`, `bed.spiel(deckel, gehaeuse, min=0.2)`,
  `bed.min_abstand(a, b, wert)`, `bed.min_wand(teil, 1.2)`.
- **Prüfen:** `run` meldet Befunde mit Soll, Ist, Zeile und Lösung; `pruefen(thema="bedingungen")` zeigt alle Bedingungen, Freiheitsgrade
  je Teil (unterbestimmt = Hinweis), Widersprüche (Fehler mit den beteiligten Bedingungen), Befestigung und
  Bewegungsraum (`pruefen(thema="bedingungen", teil="…", alle=true)` für ein Teil). Jeden Fehler beheben, bevor du fertig meldest; die
  Lösung steht im Befund. Beispiel mit Kevins Kugelschieber: `samples/kugelschieber-bedingungen/model.py`.
