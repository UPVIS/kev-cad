# Messen, zeigen, Bilder, Renderings

Teil des Skills kev-cad. Referenzen und Kevins Auswahl, exakt messen, Kevin etwas im Viewer zeigen, Bilder zur eigenen Analyse, Renderings für Kevin.

## Referenzen und Auswahl

- `Halter/Lasche` ist das Teil, `Halter/Lasche#f3` Fläche 3, `#e2` Kante 2, `#v1` Punkt 1. Die Nummer folgt
  `teil.faces()`, `teil.edges()` und `teil.vertices()` des zuletzt gezeigten Objekts.
- Referenzen gelten **nur für einen Lauf**. Nach jedem `run` neu holen, nie alte Nummern wiederverwenden.
- Flächennummer finden: `execute("[(i, f.geom_type.name, round(f.area, 1), f.center()) for i, f in
  enumerate(platte.faces())]")` mit der Variablen des gezeigten Teils.
- Sagt Kevin „diese Bohrung“, „hier“ oder „das da“: zuerst `measure()` ohne refs. Sie liefert seine angeklickten Referenzen samt
  Werten (Typ, Fläche, Radius).

## Messen

- `measure(refs=["Grundplatte#f3"])`: Eigenschaften eines Elements (Fläche, Normale, Radius, Länge, Lage, beim Teil Hüllmaß,
  Volumen, Masse).
- `measure(refs=["Lasche#f2", "Grundplatte#f0"])`: kleinster Abstand mit dx, dy, dz und beiden Punkten, Winkel, Abstand
  paralleler Flächen. Zwei Bohrungswände (Zylinderflächen) ergeben den Achsabstand.
- `show=True` (Standard) blendet das Maß im Viewer ein. Werte stimmen exakt (OCCT), nicht aus dem Bild schätzen.
- Rechnungen und Abfragen im Modell mit `execute` (z. B. `platte.volume`, `schelle.bounding_box()`), ohne model.py zu
  ändern.

## Kevin etwas zeigen

| Werkzeug | Zweck |
|---|---|
| `view(focus=["Halter/Lasche"])` | Kamera fährt hin (animiert) |
| `view(hervorheben=refs, farbe="orange", beschriftung="M6")` | einfärben, beschriften; ersetzt alte, `dazu=true` ergänzt |
| `view(anmerkung={"art": "dimension", "punkte": [[x,y,z],[x,y,z]]})` | Maßlinie (Text = Abstand, wenn leer); auch `arrow`, `label` |
| `view(entfernen="anmerkungen")` | alle Anmerkungen weg (oder `entfernen=[ids]`) |
| `view(sichtbarkeit="isolieren", teile=["Halter/Lasche"])` | nur diese Teile; `sichtbarkeit="alle"` stellt alles wieder her |
| `view(schnitt="y", schnitt_mm=0)` | Schnitt; `view(schnitt="aus")` hebt ihn auf |
| `view(standard="front", projection="orthographic", fit=True)` | Standardansicht, Darstellung (`xray`, `wireframe`), `explode=0.6` |

„Zoom auf die Lasche und zeig sie von der Seite“: `view(standard="right", projection="orthographic")`, dann
`view(focus=["Halter/Lasche"])`. Kevin sieht das Ergebnis selbst im Viewer.

## Bilder

Kevin keine Screenshots schicken, außer er will ausdrücklich ein Bild: Er sieht den Viewer beim Arbeiten selbst, und
jedes Bild hält die Generierung auf.

Zur eigenen Analyse sind Bilder aus mehreren Blickwinkeln ausdrücklich erlaubt, wenn sie zu einer besseren Entscheidung
führen (Kevin, 21.10.2026): Durchdringungen und Einbaubarkeit beurteilen, Proportionen und Lage prüfen, mit
Referenzfotos vergleichen. Dann gezielt: wenige Offscreen-Ansichten in kleiner Auflösung in einem Zug (etwa iso, vorn,
rechts, oben), nicht nach jedem Schritt. Erste Quelle bleiben die Zahlen aus `run`, `parts`, `measure` und der Prüfung.

- `ansichten()` liefert mehrere Offscreen-Ansichten in einem Aufruf (Standard iso, vorn, rechts, oben, 640 × 400),
  frei wählbare Blickrichtungen (`richtungen=[[1, 1, -1]]`), auf Teile (`ziel`) oder einen Punkt (`punkt`, `radius`)
  eingepasst, mit Röntgen (`darstellung="xray"`) für verdeckte Teile, rot hervorgehobenen Teilen und den roten
  Schnittkörpern der Prüfung. Kevins Kamera und Darstellung bleiben unverändert.
- `pruefen(bilder=True)` zeigt die schlimmsten Befunde aus zwei, drei Richtungen von nah, mit Schnittvolumen.
- `ansichten(kevin=true)` zeigt genau Kevins Ansicht, 1280 × 800 px. Größer nur, wenn Details fehlen.
- `mm_per_px` gibt es nur in paralleler Projektion. Maße trotzdem mit `measure` bestätigen.

## Renderings (Phase 7)

Schöne Bilder für Kevin (Produktbild, Deckblatt, Kunden, Social Media) macht `render`, nicht `ansichten(kevin=true)`. Nur auf
Kevins Wunsch, und das Bild ist für ihn: die Antwort nennt den Pfad; selbst ansehen nur mit `bild_zeigen=true`, wenn
Kevin danach fragt oder du etwas prüfen musst.

- `render(szene="studio", ansicht=None, kamera=None, groesse="hd", qualitaet="schnell", hintergrund=None, ziel=None)`
  schreibt ein PNG nach `<projekt>/output/renders/`. Es zeigt, was der Viewer zeigt: sichtbare Teile, Explosion und
  Animationslage; ohne Schnitt, Hervorhebungen und Maße.
- Szenen: `studio` (heller Hintergrund, weicher Schatten), `werkstatt` (Werkstatt mit Werkbank und Regalen), `draussen` (Garten
  bei Tageslicht), `wohnraum`, `freigestellt` (PNG mit Alpha und halbdurchsichtigem Schatten). `hintergrund` ersetzt den
  Hintergrund (`weiss`, `hell`, `grau`, `dunkel`, `schwarz`, `transparent`, `#RRGGBB`).
- `ansicht`: `aktuell` (Kevins Ansicht, Vorgabe; steht der Viewer auf paralleler Projektion, wird das Bild in beiden
  Qualitäten echt orthografisch mit derselben sichtbaren Höhe), `produkt` (3/4 von vorn rechts, leicht von oben,
  eingepasst) oder eine Standardansicht (perspektivisch); `kamera="FX6"` rendert durch eine Kamera aus model.py
  (Seitenverhältnis ihres Formats).
- `groesse`: `hd`, `4k`, `quadrat`, `hochkant` (Instagram 4:5), `story`, `deckblatt` (3:2), `a4`, `vorschau` oder
  `"2400x1600"`.
- `qualitaet="schnell"`: RealityKit in der App, ein bis wenige Sekunden, wartet. `qualitaet="foto"`: Blender Cycles im
  Hintergrund, eine bis wenige Minuten; die Antwort kommt sofort mit Auftrag `R-n`. Stand mit
  `render(auftrag="R-3", warten_s=120)`, Abbruch mit `abbrechen=true`. Kevin sieht den Fortschritt in der App.
- Materialien kommen aus dem Katalog (`render`: eloxiert, gebürstet, verzinkt, Schichtlinien bei Druckteilen, Holz,
  Gummi). Die Schichtlinien liegen quer zur Druckrichtung des Teils (Ausrichtung aus der Druckprüfung, wie in der
  Druckvorschau). Den Schatten auf dem Boden rechnet das Schnellbild wie die Flächenlichter des Fotos (Kontaktschatten
  unter dem Objekt, weicher Schlagschatten). Eine Farbe in `show(..., color=...)` hat Vorrang vor der Katalogfarbe, Glanz und Metall bleiben.
- Kevin selbst: Ablage → „Rendern …“ (⌥⌘R) mit Vorschau, Finder und Teilen; im Export-Dialog der Baustein
  „Produktbild“.
