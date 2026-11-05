---
name: kev-cad
description: Leitfaden für Kev CAD, Kevins nativen CAD-Viewer auf dem Mac (MCP-Server „kevcad“, Werkzeuge wie status, run, measure, view). Verwenden, sobald Kevin in Kev CAD ein 3D-Modell bauen, ändern, vermessen, ansehen oder exportieren will – Halter, Gehäuse, Bauteile, Möbel, Baugruppen als model.py mit build123d, die sich live im Viewer aufbauen. Auch bei „bau mir …“, „mach die Bohrung größer“, „wie weit ist das vom Rand weg“, „zeig mir die Lasche von der Seite“, „was hab ich angeklickt“, „exportier als STEP/STL/3MF“ in einem Kev-CAD-Projekt, ebenso bei Lagerteilen (Rohre, Profile, Platten, Holz, Schrauben aus dem Katalog), Stückliste, Zuschnitt, Gewicht und Kosten („was kostet das“, „wie viele Stangen“), 3D-Druckteilen, Zukaufteilen per Shop-Link, Herstellernummer oder EAN („bau diesen Auszug ein: https://…“, Hersteller-CAD, STEP aus den Downloads übernehmen), Kameras („setz die FX6 mit 35 mm auf den Wagen“, „zeig mir ihr Bild“, „rendere das Kamerabild in 4K“) und Animationen („lass den Wagen rollen“, „Kollision prüfen“, „mach ein Video aus Sicht der FX6“), technischen Zeichnungen („mach mir Zeichnungen“, „Werkstattzeichnung vom Rohr“, „bemaß die Platte“, „Maß fehlt auf dem Blatt“) sowie Bauplan und Bauanleitung („mach mir einen Bauplan“, „was muss ich bohren und in welcher Reihenfolge montieren“) und Referenzen aus Handyvideo oder Fotos („hier ist ein Video vom Gerät, bau es nach“, „miss die Maße aus den Fotos“, „leg das Video als Referenz an“, „passt das Modell zum Foto?“) sowie Scans vom iPhone mit Kev Scan („ich hab das gescannt“, „übernimm den Scan“, „miss das am Scan“).

description: Leitfaden für Kev CAD, Kevins nativen CAD-Viewer auf dem Mac (MCP-Server „kevcad“, Werkzeuge wie status, run, measure, view). Verwenden, sobald Kevin in Kev CAD ein 3D-Modell bauen, ändern, vermessen, ansehen oder exportieren will – Halter, Gehäuse, Bauteile, Möbel, Baugruppen als model.py mit build123d, die sich live im Viewer aufbauen. Auch bei „bau mir …“, „mach die Bohrung größer“, „wie weit ist das vom Rand weg“, „zeig mir die Lasche von der Seite“, „was hab ich angeklickt“, „exportier als STEP/STL/3MF“ in einem Kev-CAD-Projekt, ebenso bei Lagerteilen (Rohre, Profile, Platten, Holz, Schrauben aus dem Katalog), Stückliste, Zuschnitt, Gewicht und Kosten („was kostet das“, „wie viele Stangen“), 3D-Druckteilen, Zukaufteilen per Shop-Link, Herstellernummer oder EAN („bau diesen Auszug ein: https://…“, Hersteller-CAD, STEP aus den Downloads übernehmen), Kameras („setz die FX6 mit 35 mm auf den Wagen“, „zeig mir ihr Bild“, „rendere das Kamerabild in 4K“) und Animationen („lass den Wagen rollen“, „Kollision prüfen“, „mach ein Video aus Sicht der FX6“), technischen Zeichnungen („mach mir Zeichnungen“, „Werkstattzeichnung vom Rohr“, „bemaß die Platte“, „Maß fehlt auf dem Blatt“) sowie Bauplan und Bauanleitung („mach mir einen Bauplan“, „was muss ich bohren und in welcher Reihenfolge montieren“) und Statik („hält das, wenn ich mich mit 30 kg draufstütze“, „trägt der Rahmen das“, „kippt das beim Bremsen“, „ist das überdimensioniert“).
---

# Kev CAD

Ein Modell ist `model.py` im Projektordner (build123d, Millimeter, Z nach oben). Der Kernel führt die Datei aus, jedes
`show()` erscheint sofort im Viewer; Kevin sieht zu und spricht mit dir. Die Datei ist die Quelle der Wahrheit:
Änderungen immer dort, nie nur per `execute`. Kevin will Tempo: wenig lesen, wenige Runden, keine Bilder an ihn.

## Werkzeuge

Kernsatz für die tägliche Arbeit. In Claude Code alle dreizehn mit EINEM ToolSearch-Aufruf laden:
`select:mcp__kevcad__status,mcp__kevcad__projekt,mcp__kevcad__modell,mcp__kevcad__run,mcp__kevcad__execute,mcp__kevcad__parts,mcp__kevcad__measure,mcp__kevcad__view,mcp__kevcad__pruefen,mcp__kevcad__ansichten,mcp__kevcad__katalog,mcp__kevcad__export,mcp__kevcad__feedback`

| Werkzeug | Wofür |
|---|---|
| `status()` | Lagebild: Projekt, letzter Lauf, offene Befunde, Kevins Auswahl mit Werten, seine Kamera, Ausgeblendetes |
| `projekt(pfad, neu=false)` | Projekt öffnen oder anlegen (bloßer Name: `~/Documents/Kev CAD/<Name>`) |
| `modell(code=None)` | model.py lesen oder ganz schreiben (nur ohne eigene Dateiwerkzeuge) |
| `run(params, detail, titel)` | ausführen; antwortet nur mit dem, was sich seit deinem letzten Lauf geändert hat |
| `execute(code)` | Python im Namensraum des letzten Laufs (Geometrie untersuchen, ohne model.py zu ändern) |
| `parts(filter, stueckliste)` | Teile kurz oder je Baugruppe ausführlich; Stückliste mit Zuschnitt und Einkauf |
| `measure(refs, show)` | exakt messen; ohne refs Kevins Auswahl („das hier“, „diese Bohrung“) |
| `view(…)` | Kamera, Darstellung, Fokus, Sichtbarkeit, Schnitt, Hervorheben, Anmerkungen in einem Aufruf |
| `pruefen(thema)` | Prüfergebnis im Endstand; `thema="bedingungen"` oder `"montage"` |
| `ansichten(…)` | Bilder zur eigenen Analyse; `kevin=true` genau Kevins Ansicht (nur auf seinen Wunsch) |
| `katalog(suche, art, id)` | Lagerteile suchen, ein Teil im Detail, `art="material"` für Materialien |
| `export(formats)` | STEP, STL, 3MF, GLB, Stückliste, Einkaufsliste, PDF aus Bausteinen |
| `feedback(warten_s)` | wartet, bis Kevin fertig gesprochen hat; seine Sätze mit dem, worauf er gezeigt hat, und ein Bild ([feedback.md](feedback.md)) |

Je Fachbereich ein Werkzeug mit `aktion`: `lager`, `bestand`, `druck`, `statik`, `topologie`, `zeichnung`,
`bauplan`, `referenz`, `kamera`, `animation`, `versionen`, dazu `render` (ohne aktion). `aktion="hilfe"` erklärt jeden
Parameter, `daten=true` hängt die Rohdaten als JSON an. Einzelheiten und die Zuordnung der bisherigen 95 Namen:
[werkzeuge.md](werkzeuge.md).

## Ablauf

1. `status`. Kein Projekt: `projekt(pfad)` bzw. `projekt(pfad, neu=true)`.
2. Teile im Lager suchen: `katalog(suche="vierkantrohr 40x40x3")`, Materialien `katalog(art="material")`.
3. model.py mit den eigenen Dateiwerkzeugen schreiben (Pfad aus `status`), dann `run`. Die Antwort nennt neue und
   geänderte Teile mit dem Unterschied, unveränderte nur als Zahl, neue Befunde zuerst; bekannte nur gezählt. Ein
   Fehler kommt vollständig (Zeile, Auszug, Hinweis) als isError; die letzte gute Geometrie bleibt stehen.
4. **Maße ändern als Operation:** `run(params={"breite": 140})` überschreibt `param()`-Werte für diesen Lauf, ohne
   die Datei anzufassen (mit Rechengedächtnis rund 2 s). So Maße ausprobieren und vergleichen; den Wert erst in
   model.py schreiben, wenn Kevin ihn will. Ein `param`, den es nicht gibt, meldet `run` ausdrücklich.
5. Befunde beheben, wichtige Maße mit `measure` prüfen. Sagt `run`, die Prüfung laufe noch, vor dem Fertigmelden
   `pruefen()` (wartet auf den Endstand). Ausführlich: [pruefung.md](pruefung.md).
6. Am Ende jeder Aufgabe `versionen(aktion="meilenstein", titel=…, notiz=…)`, dann Kevin kurz berichten: Hauptmaße,
   Masse, Kosten (Richtpreise), Annahmen, vereinfachte Zukaufteile, Einkaufsliste.

## Was immer gilt

- **Konstruktionsregeln:** die 15 Regeln in [konstruktion.md](konstruktion.md) vor der ersten Zeile Geometrie lesen;
  auf „prüfe das Design kritisch“ folgt das Design-Review im festen Format.
- **Inventar-Regel:** nur Lagerteile (`lager.teil(id).verbauen(…)`, gleicher Name in `show`), freigegebene
  Zukaufteile (`lager.zukauf(id)`) und Druckteile (`lager.druckteil(form, name, material="petg")`). Nichts erfinden;
  fehlt etwas, Kevin fragen, vorschlagen nur auf seinen Wunsch, freigeben nur durch seinen Klick
  (`lager(aktion="freigabe", ids=[…], grund=…)`). Einzelheiten: [lager.md](lager.md).
- **Prüfung:** keine Durchdringung, nichts schwebt, alles steht und lässt sich einbauen; Befunde beheben, nicht
  wegerklären ([pruefung.md](pruefung.md)). Teile über Bedingungen setzen und befestigen
  ([bedingungen.md](bedingungen.md)).
- **3D-Druck:** Regeln für Kevins Bambu Lab P1P beim Konstruieren ([3d-druck.md](3d-druck.md)); vor jedem Druck oder
  Druckexport nach dem Filament fragen.
- **Bilder:** Kevin keine schicken, außer er will eins. Zur eigenen Analyse wenige kleine Ansichten, wenn sie zu
  einer besseren Entscheidung führen.
- **Nur auf Kevins ausdrückliches Wort:** drucken, Version wiederherstellen, gebaut oder gedruckt buchen, Bestand
  eintragen (seine Worte), Druckeinstellungen, Lastfälle der Simulation und Katalogeinträge ändern. Gemessene Maße aus
  Referenzen übernimmt Kevin selbst.

## Verzeichnis

| Datei | Lesen, wenn … |
|---|---|
| [werkzeuge.md](werkzeuge.md) | du Parameter eines Werkzeugs brauchst oder einen alten Werkzeugnamen kennst |
| [ablauf.md](ablauf.md) | du eine Aufgabe beginnst: Ablauf, Versionen, Meilenstein, typische Meldungen |
| [modell.md](modell.md) | du model.py schreibst: Gerüst, API von kevcad, build123d und seine Fallen, Lochtabellen |
| [bedingungen.md](bedingungen.md) | du Teile platzierst, befestigst oder bewegliche Teile (Gelenke) baust |
| [pruefung.md](pruefung.md) | `run` Befunde meldet oder du fertig melden willst; montagegerecht konstruieren |
| [lager.md](lager.md) | es um Lagerteile, Stückliste, Bestand, Einkaufsliste oder Zukaufteile geht |
| [3d-druck.md](3d-druck.md) | du ein Druckteil konstruierst, exportierst oder drucken sollst |
| [statik.md](statik.md) | Kevin fragt, ob etwas hält, kippt, sich biegt; Dynamik, FEM, Topologie |
| [feedback.md](feedback.md) | Kevin per Sprache mit dir arbeitet: auf ihn warten, sein Feedback lesen, was gilt, während er spricht |
| [ansicht.md](ansicht.md) | du messen, Kevin etwas zeigen, Bilder zur Analyse oder ein Rendering brauchst |
| [kamera-animation.md](kamera-animation.md) | Kameras (FX6 & Co.) oder Animationen und Videos im Spiel sind |
| [referenz.md](referenz.md) | Kevin ein Video, Fotos oder einen Scan des echten Gegenstands gibt |
| [dokumente.md](dokumente.md) | Zeichnungen, Bauplan, PDF oder Dateiexport gefragt sind |
| [konstruktion.md](konstruktion.md) | vor jedem Design und beim Design-Review |
