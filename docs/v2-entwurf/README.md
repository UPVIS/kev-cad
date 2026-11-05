# Kev CAD V2: Gestaltungsentwurf

Drei Richtungen für die neue Oberfläche, jede in denselben fünf Zuständen. Zum Ansehen
[entwurf.html](entwurf.html) im Browser öffnen: Oben wählst du Richtung und Zustand, die Tasten 1 bis 3 und a bis e
schalten ebenfalls um, ← und → blättern durch die Zustände.

| Zustand | Was zu sehen ist |
|---|---|
| a | Fokus, während Kevin spricht und zeigt: Live-Text, Zeigespur und Striche, markierte Teile, Live-Maß, Agentenspur und ein Befund direkt am Teil |
| b | Werkstatt mit Kacheln für Modell, Zeichnung und Stückliste, daneben Objekte, Eigenschaften und Maße zum Nachjustieren |
| c | Fokus schmal am rechten Bildschirmrand neben dem Chat, während der Agent den Schiebebügel baut |
| d | Start im leeren Projekt, die letzten Projekte liegen darüber und lassen sich mit einem Klick wegschieben |
| e | Hinweisleiste und Tastenübersicht (Steuerung wie in Blender, dazu Sprechen und Zeichnen) |

Das Modell im Bild ist echte Geometrie, die die Seite selbst mit WebGL 2 rendert: Nutprofile 30 × 30, eine
Multiplexplatte, vier Lenkrollen Ø 100, Winkel und Schrauben. Die Zeichnungen sind Parallelansichten desselben
Modells. Ohne WebGL 2 bleibt die Bildfläche leer und die Seite sagt das.

## Graphit

Der Viewer wird zum Fotostudio: Das Modell steht in weichem Licht, und im Fokus gibt es keine Tafeln, nur Text
direkt im Bild, Kevins Stimme in Lichtblau und den Agenten in Messing. Stark ist, wie viel Raum das Modell bekommt
und wie ruhig alles bleibt; der Live-Text steht groß wie ein Untertitel in der Mitte, und das schmale Fenster am
Rand verliert dabei kaum etwas. Das Risiko liegt in der Lesbarkeit von Text über hellen Teilen, und von den drei
Richtungen ist sie die unauffälligste, sie könnte gewohnten dunklen Profi-Apps zu nahe kommen.

## Reißbrett

Gearbeitet wird wie am Zeichenbrett: helles Blatt mit Planquadraten und Schriftfeld, Kevin markiert mit dem
Rotstift, der Agent antwortet in Blau und trägt jede Änderung mit einem Index ein, Befunde sind gelb schraffiert.
Stark ist, dass Modell, Zeichnung und Stückliste dieselbe Sprache sprechen und auf einen Blick klar ist, wer was
gesagt oder geändert hat, bis zur Änderungsmarke in der Zeichnung. Ein heller Bildschirm ermüdet über Stunden, die
technische Darstellung nimmt dem Modell den Glanz, und Rahmen, Schriftfeld und Änderungsliste bringen mehr Linien
ins Bild, als ein leerer Fokus verträgt.

## Sucher

Der Viewer verhält sich wie ein Kameramonitor: Sobald Kevin spricht, geht das Bild mit rotem Rahmen auf Sendung,
der Agent schreibt mit Timecode mit, Befunde zeigen Zebra, und die Werkstatt ist ein Multiviewer mit nummerierten
Kacheln. Der Zustand ist nie unklar, Kacheln lassen sich per Sprache eindeutig ansteuern („Kachel 3 groß“), und die
Bildsprache passt zu Kevins Arbeit als Filmer und zur App Sichtung. Die vielen Monospace-Anzeigen wirken technisch
und kühl, vier Signalfarben brauchen Disziplin, und der rote Rahmen kann bei langen Ansagen unruhig werden.

## Empfehlung

Ich empfehle Graphit als Grundlage, weil diese Richtung den Kern von Kevins Wunsch am besten trifft: Das Modell
steht im Mittelpunkt, der Fokus ist wirklich leer, und die Oberfläche fühlt sich nach Mac an, ohne macOS-Bausteine
zu benutzen. Aus Sucher würde ich zwei Dinge übernehmen, weil sie Graphit an seinen schwächsten Stellen helfen:
einen schmalen Rahmen in Kevins Farbe, solange er spricht, und nummerierte Kacheln, damit Anweisungen wie „Kachel 2
und 3 nebeneinander“ eindeutig sind. Reißbrett taugt als Stil für die Zeichnungen selbst, etwa mit den
Änderungsindizes.

## Dateien

- [entwurf.html](entwurf.html): alles in einer Datei, ohne externe Abhängigkeiten
- [graphit-a-fokus.jpg](graphit-a-fokus.jpg), [graphit-b-werkstatt.jpg](graphit-b-werkstatt.jpg)
- [reissbrett-a-fokus.jpg](reissbrett-a-fokus.jpg), [reissbrett-b-werkstatt.jpg](reissbrett-b-werkstatt.jpg)
- [sucher-a-fokus.jpg](sucher-a-fokus.jpg), [sucher-b-werkstatt.jpg](sucher-b-werkstatt.jpg)
- [uebersicht-a.jpg](uebersicht-a.jpg): alle drei Richtungen im Zustand a nebeneinander

Die Bilder sind 1440 × 900 in doppelter Auflösung, gerendert mit headless Chromium (`entwurf.html?bild#graphit/a`,
Übersicht mit `?uebersicht=a`). Chromium kennt SF Mono nicht und zeigt dort Menlo; Safari zeigt SF Mono.
