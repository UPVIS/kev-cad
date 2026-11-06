---
name: kev-cad
description: Leitfaden für Kev CAD, Kevins nativen CAD-Viewer auf dem Mac (MCP-Server „kevcad“, Werkzeuge wie status, run, measure, view). Verwenden, sobald Kevin in Kev CAD ein 3D-Modell bauen, ändern, vermessen, ansehen oder exportieren will – Halter, Gehäuse, Bauteile, Möbel, Baugruppen als model.py mit build123d, die sich live im Viewer aufbauen. Auch bei „bau mir …“, „mach die Bohrung größer“, „wie weit ist das vom Rand weg“, „zeig mir die Lasche von der Seite“, „was hab ich angeklickt“, „exportier als STEP/STL/3MF“ in einem Kev-CAD-Projekt, ebenso bei Lagerteilen (Rohre, Profile, Platten, Holz, Schrauben aus dem Katalog), Stückliste, Zuschnitt, Gewicht und Kosten („was kostet das“, „wie viele Stangen“), 3D-Druckteilen, Zukaufteilen per Shop-Link, Herstellernummer oder EAN („bau diesen Auszug ein: https://…“, Hersteller-CAD, STEP aus den Downloads übernehmen), Kameras („setz die FX6 mit 35 mm auf den Wagen“, „zeig mir ihr Bild“, „rendere das Kamerabild in 4K“) und Animationen („lass den Wagen rollen“, „Kollision prüfen“, „mach ein Video aus Sicht der FX6“), technischen Zeichnungen („mach mir Zeichnungen“, „Werkstattzeichnung vom Rohr“, „bemaß die Platte“, „Maß fehlt auf dem Blatt“), Bauplan und Bauanleitung („mach mir einen Bauplan“, „was muss ich bohren und in welcher Reihenfolge montieren“), Statik („hält das, wenn ich mich mit 30 kg draufstütze“, „trägt der Rahmen das“, „kippt das beim Bremsen“, „ist das überdimensioniert“) und Referenzen aus Handyvideo, Fotos oder Scans vom iPhone mit Kev Scan („hier ist ein Video vom Gerät, bau es nach“, „miss die Maße aus den Fotos“, „passt das Modell zum Foto?“, „ich hab das gescannt“, „übernimm den Scan“).
---

# Kev CAD

Ein Modell ist `model.py` im Projektordner (build123d, Millimeter, Z nach oben). Der Kernel führt die Datei aus, jedes
`show()` erscheint sofort im Viewer; Kevin sieht zu und spricht mit dir. Die Datei ist die Quelle der Wahrheit:
Änderungen immer dort, nie nur per `execute`. **Kevin will Tempo: jede Runde (Modellaufruf) kostet ihn Sekunden.** Was
du für eine gewöhnliche Aufgabe brauchst, steht auf dieser Seite; die Dateien im Verzeichnis unten nur bei Bedarf.

## Ablauf in wenigen Runden

1. **Erste Runde:** `status` (Pfad von model.py, Befunde, Kevins Auswahl). Bei einem vorhandenen Modell im selben Zug
   `modell(gliederung=true)`: Parameter mit Wert und Zeile, Schritte, gezeigte Teile. Danach aus model.py nur die
   Zeilen lesen, die du brauchst (Read mit offset und limit), nicht die ganze Datei. Kein Projekt: `projekt(pfad)` bzw.
   `projekt(pfad, neu=true)`. Werkzeuge ohne Abhängigkeit immer gemeinsam in einer Runde aufrufen; Lagerteile
   (`katalog(suche=…)`) gleich mit, wenn der Auftrag sie nennt.
2. **Erst vollständig planen, dann model.py schreiben und `run` in derselben Runde.** Druckregeln, Bettfase, Wände,
   Bohrungen schon beim Planen einbauen, damit kein zweiter Durchgang nötig ist.
3. `run` meldet neue und geänderte Teile mit Maßen, Volumen und neue Befunde zuerst (bekannte gezählt); ein Fehler kommt
   vollständig als isError, die letzte gute Geometrie bleibt stehen. Stimmen die Maße und gibt es keine Fehler und
   Warnungen, ist das Modell fertig. Nur gezielt nachmessen (`measure`, `execute`), was der Lauf nicht zeigt. Alle
   Befunde in einem Zug beheben, dann ein `run`. Sagt `run`, die Prüfung laufe noch, vor dem Fertigmelden `pruefen()`.
4. **Der letzte `run` einer Aufgabe bekommt `meilenstein="Kurzer Titel"` und `notiz="was und warum"`:** Er setzt den
   Meilenstein mit, wenn der Lauf fehlerfrei ist (gilt immer, kein eigener Aufruf nötig). Danach der kurze Bericht an
   Kevin: Hauptmaße, Masse, Kosten (Richtpreise), Annahmen, vereinfachte Zukaufteile, Einkaufsliste, Druckausrichtung
   neuer Druckteile.
5. **Maße ändern:** `modell(setze={"breite": 150, "dicke": 8})` ändert die Vorgabewerte der `param()` in model.py genau
   an diesen Stellen, ohne Lesen; im selben Zug `run(meilenstein=…)`. Was kein `param` ist, änderst du von Hand.
   Ausprobieren ohne Dateiänderung: `run(params={"breite": 140})` (rund 2 s); den Wert erst übernehmen, wenn Kevin ihn
   will.

## Werkzeuge

Kernsatz, in Claude Code mit EINEM ToolSearch-Aufruf laden:
`select:mcp__kevcad__status,mcp__kevcad__projekt,mcp__kevcad__modell,mcp__kevcad__run,mcp__kevcad__execute,mcp__kevcad__parts,mcp__kevcad__measure,mcp__kevcad__view,mcp__kevcad__pruefen,mcp__kevcad__ansichten,mcp__kevcad__katalog,mcp__kevcad__export,mcp__kevcad__feedback`

`status` Lagebild · `projekt` öffnen, anlegen, benennen · `modell` lesen, schreiben, `setze`, `gliederung` · `run`
ausführen (`params`, `meilenstein`, `titel`, `detail`) · `execute` Python im Namensraum des letzten Laufs · `parts`
Teile, Stückliste · `measure` exakt messen, ohne refs Kevins Auswahl · `view` Kamera, Fokus, Schnitt, Anmerkungen,
Kacheln · `pruefen` Endstand der Prüfung · `ansichten` Bilder zur eigenen Analyse · `katalog` Lagerteile, Materialien ·
`export` STEP, STL, 3MF, Listen, PDF · `feedback` wartet auf Kevins Sprache ([feedback.md](feedback.md)).
Je Fachbereich ein Werkzeug mit `aktion` (`aktion="hilfe"` erklärt die Parameter): `lager`, `bestand`, `druck`,
`statik`, `topologie`, `zeichnung`, `bauplan`, `referenz`, `kamera`, `animation`, `versionen`, dazu `render`.

## Gerüst

```python
from build123d import *
from kevcad import lager, param, show, step

# Anforderungen und Annahmen (markiert) als Kopfkommentar
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
- `Box`, `Cylinder`, `Sphere` sind um den Ursprung **zentriert**; auf XY stellen mit
  `align=(Align.CENTER, Align.CENTER, Align.MIN)`. `Pos(x, y, z) * teil` verschiebt, `Rot(x, y, z) * teil` dreht.
- Boolesch `a + b`, `a - b`, `a & b`; Werkzeugkörper für Durchbrüche überstehen lassen (nie bündig). Im Builder
  `mode=Mode.SUBTRACT`, `Locations`, `GridLocations(dx, dy, nx, ny)`, `PolarLocations(radius, anzahl)`;
  `Hole(r, depth=t)` für Sacklöcher; `CounterSinkHole(…, counter_sink_angle=90)` (metrisch 90°).
- Kanten: `edges().filter_by(Axis.Z)` senkrecht, `group_by(Axis.Z)[-1]` oben, `[0]` unten; `fillet`, `chamfer`
  (Ergebnis neu zuweisen). Ecken vor dem Bohren runden. Schalen mit `offset(teil, amount=-wand, openings=fläche)`.
- Schrauben: Durchgang M3 3,4, M4 4,5, M5 5,5, M6 6,6; Kernloch ≈ 0,8 × d. Mehr API: [modell.md](modell.md).

## Was immer gilt

- **Inventar-Regel:** jedes gezeigte Teil ist ein Lagerteil (`lager.teil(id).verbauen(laenge, "Name")`, gleicher Name in
  `show`), ein freigegebenes Zukaufteil (`lager.zukauf(id).verbauen("Name")`) oder ein Druckteil
  (`lager.druckteil(form, "Name", material="petg")`). Nichts erfinden; fehlt etwas, Kevin fragen, vorschlagen nur auf
  seinen Wunsch, freigeben nur durch seinen Klick ([lager.md](lager.md)). Stangenware liegt nach `verbauen` entlang +Z
  ab z = 0, Querschnitt mittig; Platten in XY ab z = 0, mittig.
- **Prüfung nach jedem Lauf:** keine Durchdringung, nichts schwebt, alles steht und lässt sich einbauen, Druckregeln.
  Fehler beheben, Warnungen beheben oder begründen, nicht wegerklären ([pruefung.md](pruefung.md)). Teile über
  Bedingungen setzen und befestigen ([bedingungen.md](bedingungen.md)).
- **Bilder:** Kevin keine schicken, außer er will eins; zur eigenen Analyse wenige kleine Ansichten.
- **Nur auf Kevins ausdrückliches Wort:** drucken, Version wiederherstellen, gebaut oder gedruckt buchen, Bestand
  eintragen, Druckeinstellungen, Lastfälle und Katalogeinträge ändern. Vor jedem Druck oder Druckexport nach dem
  Filament fragen. Gemessene Maße aus Referenzen übernimmt Kevin selbst.

## Konstruktionsregeln (Kevin, gelten für jedes Design)

1 Anforderungen vor Geometrie, Annahmen markieren · 2 Wirkprinzip hinterfragen, Standardteile mitdenken · 3 Weglassen
vor Optimieren · 4 Gesamtaufwand bewerten (Druckzeit, Fehldruck, Nacharbeit, Montage, Reparatur) · 5 bewusst
zusammenfassen oder teilen · 6 Material nach Einsatz (PLA kriecht, erweicht ab ~55 °C) · 7 Kräfte führen, Kerben
meiden, Rippen vor Verdickung · 8 Druckorientierung früh · 9 druckgerechte Geometrie · 10 Wände gezielt · 11 Passungen
realistisch, Probedruck vorschlagen · 12 wenige gängige Normteile · 13 Montage und Wartung mitkonstruieren · 14 Fehler,
Quetschstellen, scharfe Kanten · 15 einfach und überprüfbar abschließen. Optimiert für Einzelstücke. Keine universellen
Grenzwerte, Werte begründen; Schätzungen heißen Schätzung. „Prüfe das Design kritisch“: Design-Review im festen Format
aus [konstruktion.md](konstruktion.md).

## Druckteile (Kevins Bambu Lab P1P, offen; PLA oder PETG)

- Bauraum 256 × 256 × 250 mm (vorne links 18 × 28 mm gesperrt); Düse 0,4, Schicht 0,2.
- Wände als Vielfache von ~0,42 mm, mindestens 1,2 mm, tragend 2–3 mm; Merkmale nicht unter 0,8 mm.
- Überhänge bis 45° ohne Stütze, Unterseiten fasen statt runden, Brücken höchstens ~15 mm.
- **Bettseite mit Fase 0,4–0,6 mm** gegen Elefantenfuß; große ebene Auflage einplanen.
- Waagrechte Bohrungen als Tropfen (Spitze oben); Bohrungen drucken 0,1–0,2 mm zu klein.
- Spiel je Seite: Presspassung 0,1, Spielpassung 0,2, beweglich 0,3–0,5 mm. Gewinde über Gewindeeinsätze (Tasche nach
  Herstellermaß, in Sacklöchern Entlastung vorsehen) oder eingeschlossene Muttern.
- Last längs der Schichten führen; Innenkanten verrunden. Die Druckprüfung läuft bei jedem `run` (Befunde `druck_*`,
  Ausrichtung mit Begründung); vorgeben mit `ausrichtung="-z"` usw. Rezepte (Tropfenbohrung, Passungen, Einsätze,
  Schnapphaken) und Quellen: [3d-druck.md](3d-druck.md).

## Verzeichnis (nur lesen, wenn die Aufgabe es braucht)

| Datei | Lesen, wenn … |
|---|---|
| [modell.md](modell.md) | du API von kevcad oder build123d brauchst, die oben fehlt (Rezepte, Lochtabellen) |
| [3d-druck.md](3d-druck.md) | Passungen, Einsätze, Schnapphaken, Tropfenbohrung, ein Druckbefund unklar ist oder ein Druckexport ansteht |
| [lager.md](lager.md) | Lagerteile, Stückliste, Bestand, Einkaufsliste oder Zukaufteile (Shop-Link, EAN) |
| [bedingungen.md](bedingungen.md) | du Teile platzierst, befestigst oder Gelenke baust |
| [pruefung.md](pruefung.md) | ein Befund unklar ist; montagegerecht konstruieren |
| [ablauf.md](ablauf.md) | Versionen, Varianten, typische Meldungen |
| [werkzeuge.md](werkzeuge.md) | du Parameter eines Werkzeugs brauchst oder einen alten Werkzeugnamen kennst |
| [statik.md](statik.md) | Kevin fragt, ob etwas hält, kippt, sich biegt; Dynamik, FEM, Topologie |
| [feedback.md](feedback.md) | Kevin per Sprache mit dir arbeitet |
| [ansicht.md](ansicht.md) | du messen, Kevin etwas zeigen oder ein Rendering brauchst |
| [kacheln.md](kacheln.md) | Kevin ein Ergebnis auf Zuruf sehen will: „3D-Druck ready“, „Zeichnungen“, „Animation“, „Stückliste“ |
| [kamera-animation.md](kamera-animation.md) | Kameras (FX6 & Co.), Animationen, Videos |
| [referenz.md](referenz.md) | Kevin ein Video, Fotos oder einen Scan des echten Gegenstands gibt |
| [dokumente.md](dokumente.md) | Zeichnungen, Bauplan, PDF oder Dateiexport |
| [konstruktion.md](konstruktion.md) | Design-Review oder die 15 Regeln ausführlich |
