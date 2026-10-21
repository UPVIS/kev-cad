# Kev CAD · Versionen, Meilensteine und Varianten

Stand: 21.10.2026 (Kevins Wunsch vom selben Tag: „Versionierung wie in anderen CAD-Programmen, zu der man mit einem
Klick zurückkehren kann … extrem Premium“).

## Was schon da ist

Der Kernel legt nach jedem erfolgreichen Lauf `model.py` in `<projekt>/.kevcad/versions/NNNN-model.py` ab (Kevins
Kugelschieber hat 63 Stände). Es fehlen: die übrigen Projektdateien (Hilfsmodule, `geometrie/`, `bewegungen.json`,
`katalog.json`, `kevcad.json`), eine Oberfläche, Wiederherstellen, Vergleichen, Namen und Varianten.

## Ziel

Wie in Onshape oder Fusion: eine Versionsleiste im Projekt, jede Version mit Vorschaubild, Zeit, wer sie erzeugt hat
(Kevin oder Agent), Teilezahl, Masse, Kosten und Prüfstand. Benannte Meilensteine. Ein Klick stellt jede Version wieder
her, ohne etwas zu verlieren. Zwei Versionen lassen sich vergleichen (Parameter, Stückliste, Geometrie überlagert, Code).
Varianten (Zweige) erlauben, eine Idee auszuprobieren, ohne den Hauptstand anzufassen.

**Fertig, wenn:**

1. Die Leiste „Versionen“ zeigt alle Stände des Kugelschiebers (auch die 63 vorhandenen) mit Vorschaubild und Kennzahlen.
2. „Wiederherstellen“ setzt Projektdateien und Ansicht auf den Stand zurück, rechnet neu und legt dabei selbst eine
   neue Version an; die Rückkehr nach vorn ist wieder ein Klick.
3. „Vergleichen“ zeigt geänderte Parameter, Stücklistenzeilen (neu, weg, geändert), überlagert die alte Geometrie
   halbtransparent und färbt geänderte Teile; dazu der Code-Unterschied.
4. Der Agent setzt am Ende jeder Aufgabe einen Meilenstein mit kurzer Beschreibung; Kevin kann jeden Stand benennen.
5. „Variante anlegen“ von jedem Stand aus, Wechsel zwischen Varianten mit einem Klick, jede mit eigener Versionsleiste.

## Entscheidungen (Vorschlag)

| Nr. | Entscheidung | Begründung |
|---|---|---|
| V1 | **Git als Speicher, unsichtbar:** eigenes Repo in `<projekt>/.kevcad/git` (eigenes `GIT_DIR`, Arbeitskopie = Projektordner), erfasst alle Quelldateien, nicht `output/`, nicht `.kevcad/`; große CAD-Dateien aus Zukaufteilen werden nur einmal gespeichert | Bewährt, platzsparend, Unterschiede und Zweige gibt es geschenkt; Kevin sieht kein Git |
| V2 | **Eine Version je erfolgreichem Lauf mit Änderung**, egal ob Kevin oder ein Agent gespeichert hat; die Leiste fasst dichte Folgen zusammen („12 Läufe in 4 Minuten“) | Nichts geht verloren, die Leiste bleibt lesbar |
| V3 | **Meilensteine:** benannte Versionen mit Notiz; der Agent setzt einen am Ende jeder Aufgabe (Skill-Regel), Kevin per Klick oder ⌘S-ähnlichem Befehl | Wichtige Stände finden sich sofort |
| V4 | **Kennzahlen je Version:** Teilezahl, Masse, Kosten, Prüfbefunde, Parameter, Vorschaubild (offscreen, klein; für Meilensteine immer, sonst höchstens alle paar Minuten) | Versionen unterscheiden, ohne sie zu öffnen |
| V5 | **Wiederherstellen ist nie zerstörend:** stellt Dateien her, rechnet neu, legt eine neue Version „wiederhergestellt aus …“ an | Zurück und wieder nach vorn mit einem Klick |
| V6 | **Vergleichen:** Parameter, Stückliste, Prüfstand, Code und Geometrie (alte Version als Geisterkörper, geänderte Teile farbig, neue und entfernte Teile markiert) | Sehen, was sich geändert hat, nicht nur lesen |
| V7 | **Varianten = Zweige** mit Namen; Wechseln setzt die Arbeitskopie auf die Variante; ein Zusammenführen gibt es vorerst nicht (Kevin wählt eine Variante und macht dort weiter) | Ausprobieren ohne Risiko, ohne Git-Begriffe |
| V8 | **MCP:** `versionen`, `version_wiederherstellen`, `versionen_vergleichen`, `meilenstein`, `variante` | Der Agent kann zurückgehen und vergleichen wie Kevin |
| V9 | **Aufräumen:** Meilensteine bleiben immer; automatische Versionen älter als 30 Tage werden auf eine je Stunde ausgedünnt | Platz bleibt im Rahmen |
| V10 | **Übernahme der alten Stände:** die vorhandenen `versions/NNNN-model.py` werden beim ersten Öffnen als Vorgeschichte übernommen | Kevins 63 Stände gehen nicht verloren |

## Umsetzung

Ein Strang (Kernel und App). Kernel: `kevcad_kernel/versionen/` (Git-Anbindung, Kennzahlen, Vergleich, Aufräumen,
Übernahme), Protokoll (additiv: Versionsliste, Wiederherstellen, Vergleich mit Geisterkörpern), MCP, Skill-Regel.
App: Leiste „Versionen“ (Seitenleiste oder unten), Vergleichsansicht, Meilenstein-Dialog, Varianten-Menü.
