# Messung V2-2: Wie viel die Schnittstelle dem Agenten zu lesen gibt

Werkzeug: `kernel/tools/schnittstelle_messen.py` (Aufruf im Kopf der Datei). Gezählt wird in Zeichen; Tokens grob als
Zeichen / 4. „Text“ ist, was das Modell in Claude Code liest (die Textblöcke eines Ergebnisses), „strukturiert“ das
Feld `structuredContent`, das zusätzlich über die Leitung geht.

Messobjekt: Kopie von „Kugelschieber Variante B“ (134 Teile, 33 Parameter) samt Kevins Katalog in einem Temp-Ordner,
echte Laufzeit mit Rechenprozess und Rechengedächtnis (V2-1), App-Attrappe am Socket (antwortet auf Ansichten und
Bilder, mit Kameradaten wie die App). Parameteränderung: `laufrolle_l` 100 → 90 (20 Teile ändern sich). Nach jedem
Lauf wartet das Werkzeug, bis die Prüfung im Hintergrund fertig ist, damit sich die Messungen nicht überlagern; `run`
selbst wartet wie im Betrieb höchstens 3 s auf die Prüfung.

## Vorher (main f136caa mit v2-tempo, Stand 6b2030e)

Gemessen am 05.11.2026 abends aus einer unveränderten Kopie des Basis-Codes (`git archive 6b2030e`, per `PYTHONPATH`),
Rechner unter Last anderer Agenten (Load 13 bis 16), Zeiten deshalb nur als Anhalt.

| Was | Zeichen | Tokens (≈ Zeichen/4) |
|---|---:|---:|
| Anweisungen des Servers | 29.809 | 7.452 |
| tools/list (95 Werkzeuge, JSON kompakt) | 131.021 | 32.755 |
| tools/list über HTTP (Antwortkörper) | 130.998 | 32.750 |
| initialize über HTTP (mit Anweisungen) | 30.458 | 7.614 |
| Skill SKILL.md | 83.629 | 20.907 |
| Skill gesamt (4 Dateien) | 167.862 | 41.966 |

Größte Werkzeuge (Zeichen): festigkeit 5.151, bestand_eintragen 5.056, druck_export 4.119, topologie_optimieren 3.884,
render 3.760, dynamik 3.649, szenario_rechnen 3.401, simulation_aendern 3.182.

| Antwort | Werkzeug | Text (liest das Modell) | Tokens | strukturiert | gesamt | Dauer |
|---|---|---:|---:|---:|---:|---:|
| status ohne Projekt | `status` | 514 | 128 | 379 | 1.179 | 0,06 s |
| Projekt öffnen | `project_open` | 431 | 108 | 207 | 883 | 0,08 s |
| run kalt | `run` | 67.447 | 16.862 | 52.758 | 126.850 | 12,68 s |
| run unverändert | `run` | 120.670 | 30.168 | 95.038 | 225.298 | 2,63 s |
| run Parameter laufrolle_l=90 | `run` | 67.398 | 16.850 | 52.734 | 126.774 | 6,71 s |
| status nach den Läufen | `status` | 54.396 | 13.599 | 53.895 | 114.896 | 0,01 s |
| Teile (alle) | `parts` | 73.713 | 18.428 | 60.373 | 141.443 | 0,01 s |
| Messen, ein Teil | `measure` | 489 | 122 | 401 | 1.155 | 0,0 s |
| Messen, zwei Teile | `measure` | 380 | 95 | 292 | 929 | 0,0 s |
| Prüfen | `pruefen` | 160.339 | 40.085 | 137.860 | 308.717 | 0,01 s |
| Stückliste | `bom` | 28.465 | 7.116 | 21.049 | 51.937 | 0,0 s |

Beobachtungen:

- Jede Antwort steht doppelt da: als deutsche Zusammenfassung und als JSON-Block mit denselben Daten (für Clients ohne
  `structuredContent`). Beim kalten `run` sind 52.758 der 67.447 Zeichen der JSON-Block, bei `pruefen` 137.860 von
  160.339.
- `run` nennt jedes der 134 Teile mit Maßen, Volumen und Masse, in jedem Lauf, auch wenn sich nichts geändert hat.
  Der unveränderte Lauf ist am längsten, weil seine Prüfung binnen 3 s fertig ist und alle 54 Befunde mit Lösung und
  Werten mitkommen.
- `status` nach einem Lauf trägt im JSON-Block das ganze letzte Laufergebnis samt aller Teile.
- In Claude Code kostet jedes der 95 Werkzeuge eine eigene ToolSearch-Runde, bevor es benutzt werden kann.

## Nachher (V2-2, Stand 4a2ef93)

Gemessen am 05.11.2026 spätabends mit derselben Kopie und Parameteränderung, Rechner wieder unter Last eines anderen
Agenten (Zeiten deshalb nicht vergleichbar, die Zeichen schon). Die neue Abfolge folgt dem empfohlenen Ablauf: nach dem
ersten Lauf mit fertiger Prüfung einmal `pruefen`, danach gelten die Befunde als bekannt.

| Was | vorher | nachher | Budget |
|---|---:|---:|---:|
| Anweisungen des Servers | 29.809 | 4.784 | 6.000 |
| tools/list (Werkzeuge) | 131.021 (95) | 31.784 (24) | – |
| initialize über HTTP | 30.458 | 5.129 | – |
| Skill SKILL.md (wird beim Auslösen geladen) | 83.629 | 9.558 | – |
| Skill gesamt (Themen-Dateien nur bei Bedarf) | 167.862 (4 Dateien) | 206.467 (14 Dateien) | – |

| Antwort (Text, den das Modell liest) | vorher | nachher | Budget |
|---|---:|---:|---:|
| status ohne Projekt | 514 | 130 | – |
| Projekt öffnen | 431 | 224 | – |
| run kalt (134 Teile) | 67.447 | 1.449 | 8.000 |
| run unverändert, Befunde zum ersten Mal | 120.670 | 2.683 | – |
| pruefen | 160.339 | 14.120 | – |
| run unverändert, alles bekannt | – | 490 | 1.500 |
| run Parameter `laufrolle_l` 100 → 90 (20 Teile geändert) | 67.398 | 2.389 | 4.000 |
| dieselbe mit `detail="teile"` (auf Abruf) | – | 15.355 | – |
| status nach den Läufen | 54.396 | 352 | – |
| parts, alle 134 Teile | 73.713 | 15.349 | – |
| parts, eine Baugruppe (29 Teile) | – | 5.405 | – |
| measure, ein Teil | 489 | 88 | – |
| measure, zwei Teile | 380 | 144 | – |
| Stückliste | 28.465 | 7.416 | – |

Strukturierte Daten (`structuredContent`, gehen mit über die Leitung): run kalt 52.758 → 3.051, pruefen 137.860 →
8.471, status 53.895 → 548, parts 60.373 → 13.

Was die Zahlen ausmacht:

- Kein JSON-Block mehr neben dem Text (Kernsatz immer, Fachwerkzeuge auf Wunsch mit `daten=true`).
- `run` vergleicht mit dem letzten Lauf, den der Agent gesehen hat: unveränderte Teile nur als Zahl, bekannte
  Befunde gezählt, gleichartige Befunde zusammengefasst (beim Kugelschieber 12 gleiche Gewindeeinsatz-Warnungen in
  einer Zeile mit „Ebenso 11× bei …“), der erste Lauf mit Baugruppen und Parametern statt 134 Teilezeilen.
- Werkzeugliste: 12 Werkzeuge im Kernsatz, je Fachbereich eines mit `aktion`, Schemas ohne pydantic-Ballast (`title`
  je Feld, `default: null`, `anyOf` mit `null`, zusammen gut 10 % der Liste).
- In Claude Code lädt ein einziger ToolSearch-Aufruf den Kernsatz (Zeile in den Anweisungen und in SKILL.md).

Zum Vergleich der Zeiten: Eine Parameteränderung (`run(params=…)`) ändert model.py nicht und braucht mit dem
Rechengedächtnis rund 2 s Rechenzeit im Modell (V2-1); die Antwort nennt genau die geänderten Teile mit Unterschied.
