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

## Stand (22.10.2026, Zweig `versionen`)

Umgesetzt wie oben (V1–V10):

- Kernel `kevcad_kernel/versionen/`: `git.py` (Repo mit abgeschlossener Umgebung), `archiv.py` (Versionen,
  Meilensteine, Wiederherstellen, Varianten, Ausdünnen, Übernahme per fast-import), `schnappschuss.py` (Daten und Netze
  je Version, Netze je Formschlüssel nur einmal), `vergleich.py`, `laufzeit.py` (Einbindung, Lauf ohne Live-Aufbau im
  Rechenprozess der Laufzeit für Vergleiche), `hintergrund.py` (Nachberechnung alter Stände in einem eigenen,
  niedriger priorisierten Prozess).
- Protokoll „Versionen“ in PROTOCOL.md; MCP `versionen`, `version_wiederherstellen`, `versionen_vergleichen`,
  `meilenstein`, `variante`; Skill-Regel „Am Ende jeder Aufgabe ein Meilenstein“.
- App: Leiste rechts neben dem Viewport (⌥⌘V), Vergleichskarte mit Details (Übersicht, Teile, Stückliste, Code),
  Geisterkörper (alt blau, entfernt rot) und Färbung (geändert orange, neu grün), Variantenmenü in der Titelleiste,
  Menü „Versionen“ (⌘S Meilenstein, ⌥⌘U Vergleich mit der vorherigen Version, ⇧⌘U Vergleich beenden, ⌥⌘Z vorherige
  Version wiederherstellen).

Offen: Geisterkörper erscheinen in Bildern aus dem Offscreen-Renderer (MCP `screenshot`) nur, wo sie nicht verdeckt
sind (der Renderer kennt keine Überlagerungsebene); der Vergleich zweier älterer Versionen zeigt nur Unterschiede,
keine Geometrie.

## Titel (22.10.2026, Zweig `versionstitel`)

Befund aus dem Einsatz: Beim Kugelschieber hießen alle 24 Stände „Übernommener Stand“, neue Läufe „Geändert: model.py“.
Kevin will Titel, an denen er sofort sieht, was passiert ist.

**Woher der Titel kommt (Vorrang):**

1. Kevins Meilenstein (App, Dialog „Meilenstein“): steht über allem; die Automatik schreibt ihn nie, ein Agent nur mit
   `meilenstein(…, ersetzen=true)` auf Kevins ausdrücklichen Wunsch. Ohne `ersetzen` bleibt er, und der Titel des
   Agenten wird Titel der Version darunter.
2. Titel vom Agenten: `run(titel="Laufrollen auf Kugellager umgestellt")` (MCP und `KernelService.run`, additiv mit
   Default). Gilt für die Version dieses Laufs; legte schon der Auto-Lauf nach dem Speichern die Version an, für die
   aktuelle, wenn sie jünger als 15 Minuten ist und noch keinen Agententitel hat. Der automatische Titel steht als
   Zusatzzeile darunter.
3. Der automatische Titel aus dem Vergleich mit der Vorgängerversion (`kevcad_kernel/versionen/titel.py`).
4. Bis er berechnet ist, der Grundtitel aus der Commit-Nachricht („Übernommener Stand“, „Erster Stand“).

Wiederhergestellte und gesicherte Stände behalten ihren festen Titel („Wiederhergestellt aus V12“, „Gesichert vor dem
Wiederherstellen“), der automatische steht dann als Zusatz darunter. Bei übernommenen Ständen ist „Übernommener
Stand“ der Zusatz, sobald der automatische Titel da ist.

**Regeln des automatischen Titels** (höchstens etwa 60 Zeichen, Vorrang von oben nach unten; Segmente gleichen Rangs
teilen sich den Platz, ein niedrigerer Rang kommt erst dazu, wenn alles Höhere vollständig dasteht):

| Rang | Regel | Beispiel |
|---|---|---|
| 1 | geänderte Parameter (aus den Daten, sonst aus `param()` im Code) | `breite 120 → 140`, `hub = 30 neu`, `27 Parameter entfernt` |
| 2 | neue und entfernte Teile; eine ganz neue Baugruppe steht für ihre Teile | `+ Flügelschraube M4 (4×)`, `− Klotz`, `+ Lenkrolle 1–4` |
| 3 | geänderte Teile (entfällt neben geänderten Parametern), nur verschoben, nur umgefärbt; ohne Teileänderung die Stückliste | `Rahmen, Schlitten geändert`, `Einsatz verschoben`, `Stückliste + Rillenkugellager 61801-2RS (4×)` |
| 4 | neue (dann entfernte) `step()`-Abschnitte | `neuer Schritt „Bohrungen“` |
| 5 | ohne Wirkung auf Parameter, Teile, Stückliste: nur Kommentar, Docstring, Formatierung (Syntaxbaum bzw. JSON gleich) | `Code aufgeräumt (ohne Wirkung)` |
| 5 | sonst Thema (Aufrufe von Kev CAD: Bedingungen, Montage, Druckausrichtung, Animation, Kamera, erlaubte Überlappung) und Stelle (Funktion, Abschnitt ab dem letzten `step()`, Konstante, Hilfsdatei) | `Bedingungen in klemme() geändert, Teile gleich`, `Code in „Kamera: Kameraträger“ geändert, Teile gleich` |
| 6 | zuletzt die Dateien, deren Inhalt sich nicht lesen lässt | `Geändert: teil.step` |

Teilnamen: nach dem letzten `/`, ohne Klammerzusatz (`(Druck)`) und Lagewörter (vorn, links …); Gleiches mit Anzahl
(`Gewindestift M4x35 (4×)`) oder als Nummernbereich (`Lenkrolle 1–4`); zu lang, dann gröber (`Flügelschraube M4
(12×)`, dann nur das erste Wort), dann `…` bzw. `und 3 weitere`, zuletzt nur die Zahl (`+ 16 Teile`).

**Speicher:** Titel stehen nur in `.kevcad/versionen/index.json` je Version (`titel_auto`, `titel_regel`,
`titel_basis` = `daten` oder `code`, `titel_gegen` = Nummer der Vorgängerversion, `titel_agent`). Die Git-Geschichte
wird nie umgeschrieben; ihre erste Zeile bleibt der Grundtitel beim Anlegen. Bestehende Archive zieht der Kernel beim
Öffnen nach (`_titel_nachziehen`: fehlender Titel, ältere `titel.REGEL`, anderer Vorgänger nach dem Ausdünnen, bisher
nur aus dem Code), danach nach jeder Nachberechnung (dann aus den Daten). Neue Versionen bekommen ihren Titel gleich
nach dem Lauf (etwa 40–80 ms bei 70 KB model.py). Läufe mit überschriebenen Parametern (`run(params=…)`, Regler der
App) zeigen nicht den Stand der Dateien und ändern Kennzahlen und Daten der Version nicht mehr.

**Für die App (additiv in `VERSIONEN`):** `titel` ist weiter der anzuzeigende Titel; neu sind `zusatz` (zweite Zeile
oder null), `titel_quelle` (`agent`, `auto`, `fest`, `offen`) und `titel_auto`. Die Leiste zeigt `zusatz` noch nicht.

Beispiele aus einer Kopie des Kugelschiebers: V2 `neigung 6 → 6,5`, V6 `Code aufgeräumt (ohne Wirkung)`, V10
`Druckausrichtung in DRUCKLAGE … geändert, Teile gleich`, V12 `+ Gewindestift M4x35 (4×) · − Gewindestift M4x30 (4×)`,
V15 `+ Flügelschraube M4 (12×) … · − Gewindestift M4 (12×) …`, V18 `Stückliste − Rillenkugellager 61801-2RS (4×)`,
V22 `Montage in „Rollwagen: Lenkrollen“ geändert, Teile gleich`, V24 `Schieberschlitten, Fängerschlitten geändert`
(alle 24 nach dem Öffnen in 2,5 s nachgezogen). Neuer Lauf mit `run(titel="Lücke zwischen den Teilen auf 12 mm")`:
V25 mit diesem Titel und dem Zusatz `luecke 10 → 12`; danach nur ein Kommentar: V26 `Code aufgeräumt (ohne Wirkung)`.
