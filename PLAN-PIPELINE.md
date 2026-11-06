# Kev CAD · Experiment KI-CAD-Pipeline

Stand 06.11.2026. Ergebnisoffenes Experiment, keine vorweggenommene Architekturentscheidung. Die bestehende Pipeline
bleibt als unveränderte Baseline erhalten (Tag `pipeline-baseline` = main `28788c7`). Übernommen wird nur, was die
Messung als überlegen zeigt.

## 1. Auftrag

Kevin, 06.11.2026, vier Nachrichten (sinngemäß, Kernsätze wörtlich):

- **Hauptmaß:** „Gesamtlatenz vom Prompt-Input bis zum vollständig generierten, korrekten 3D-Modell“, nicht einzelne
  Schritte. „Keine Geschwindigkeitsoptimierung zulasten der Ergebnisqualität“, universelle CAD-Funktion bleibt.
- **Zu untersuchen:** kompakte CAD-Befehlssprache, kompakte Modelldarstellung (Feature-Graph mit stabilen IDs,
  Abhängigkeiten, Constraints), deterministische CAD-Engine für Wiederkehrendes, MCP gegen andere Schnittstellen,
  build123d gegen OCP oder andere Kerne, Streaming und Batching.
- **Minimale Modelldarstellung:** welche Informationen ein LLM wirklich braucht, DSL gegen JSON gegen Feature-Graph,
  persistenter Modellkontext mit Deltas, Details auf Abruf, ausdrücklich das Qualitätsrisiko: „Informationskompression
  darf nicht mit Informationsverlust verwechselt werden.“ Kombinationen testen; „bei welchem Kompaktheitsgrad das optimale
  Verhältnis … erreicht wird.“
- **Kontextstrategie als Achse:** Anweisung erst prüfen (betrifft sie das ganze Modell oder ein Unterteil?) und nur die
  nötigen 3D-Daten mitschicken, gegen ein persistentes „mentales Modell“, das sich weiterentwickelt und nur das Minimum
  nachlädt. „Alles ist offen … aus diesen Möglichkeiten die beste Kombination finden.“
- **Token-Minimalismus allgemein:** „bei jedem Aufruf wird ohne Ende Skill und MCP-Kontext mit geladen, der vielleicht
  gar nicht notwendig ist.“

Gilt für Mac und iPad gleich (Entscheidung 06.11.2026, PLAN-IPAD.md): Alles, was übernommen wird, läuft über Kernel,
Protokoll und MCP und bleibt plattformneutral.

## 2. Messgrößen

| Größe | Quelle |
|---|---|
| Gesamtzeit Auftrag → Ende des Agenten | eigene Uhr um `claude -p` (`benchmark/lauf.py`) |
| Zeit bis zur ersten Geometrie | Beobachter am Kernel: erstes neues Teil in der Szene |
| Modellaufrufe: Zahl, Zeit bis zum ersten Zeichen, Dauer | Ereignisstrom (`--include-partial-messages`), eigene Zeitstempel |
| Werkzeugaufrufe: Zahl, Dauer, Ein- und Ausgabegröße | Ereignisstrom (tool_use bis tool_result) |
| Tokens: Eingabe neu, aus dem Zwischenspeicher, geschrieben; Ausgabe, davon Denken | `result.usage` der CLI (Denken als `thinking_tokens`) |
| Kosten laut CLI, Verbrauch des Wochenlimits | `total_cost_usd`, `rate_limit_event` (seven_day utilization) |
| Korrektheit | Orakel je Aufgabe (`benchmark/orakel.py`): misst die B-Rep-Formen der Szene selbst |
| Erfolgsquote, Korrekturschleifen | Orakel bestanden; `run`-Aufrufe mit Fehler |
| Kernelzeit | `run` kalt und warm (Stufe A), Läufe während des Agenten |

## 3. Wo die Zeit hingeht: erste Messungen

**Kernel (Stufe A, Musterlösungen ohne Sprachmodell, MacBook unter Last, 06.11.2026):** Alle sechs Musterlösungen
bestehen ihr Orakel. `run` kalt 0,08 bis 2,4 s, warm 0,02 bis 0,08 s. Für Aufgaben dieser Größe ist die Geometrie-Engine
damit kaum ein Faktor; beim Kugelschieber (134 Teile) sind es 11,6 s kalt, 1,4 bis 2,3 s warm (PLAN-V2.md).

**Kontext (statisch, 06.11.2026):** Was eine CAD-Sitzung in Kevins normaler Umgebung vor dem ersten Wort lädt:

| Schicht | Zeichen | Tokens (≈ /4) |
|---|---:|---:|
| Kevins globale Regeln (38 Dateien, größte: HyperFrames 90.904, Videoschnitt 32.282, Android 22.987) | 273.198 | 68.300 |
| Beschreibungen aller Skills (76) | 48.020 | 12.000 |
| Anweisungen und Werkzeugnamen der übrigen MCP-Server | geschätzt 40.000 bis 60.000 | 10.000 bis 15.000 |
| Systemprompt von Claude Code ohne Werkzeuge (gemessen) | – | 3.700 |
| Anweisungen des MCP-Servers kevcad | 5.989 | 1.500 |
| Skill kev-cad: SKILL.md (beim Auslösen) / alle 16 Dateien | 10.108 / 221.057 | 2.500 / 55.000 |

Für CAD braucht davon fast nichts außer kevcad und dem Skill. Der Benchmark läuft deshalb schlank (ohne Kevins Regeln,
ohne Hooks, nur kevcad); die Variante „voller Kontext“ misst, was die übrigen Schichten kosten.

**Agent:** folgt aus Stufe C (Abschnitt 7).

## 4. Achsen und Varianten

| Achse | Varianten | Erwartung vorab (Hypothese) | Risiko |
|---|---|---|---|
| A Kontextumfang | A0 voller Kevin-Kontext · A1 schlank (nur kevcad, Skill) · A2 minimal (eigener Systemprompt, nur nötige Werkzeuge) | weniger Zeit bis zum ersten Zeichen je Aufruf, viel weniger Limit-Verbrauch, spätere Verdichtung | Regeln, die für CAD doch gelten (Kevins Konstruktionsregeln stehen schon im Skill bzw. Gedächtnis) |
| B Schreibsprache | B0 Python/build123d · B1 kompakte typisierte DSL (zeilenweise) · B2 JSON-Operationen · B3 Patches auf einen Feature-Graphen; jeweils mit Ausweg in Python | weniger Ausgabetokens beim Erzeugen; deterministische Übersetzung | ungewohnte Sprache, mehr Fehlerschleifen; Ausdrucksstärke |
| C Lesedarstellung | C0 model.py lesen · C1 Feature-Graph-Übersicht mit stabilen IDs · C2 nur Deltas, Details auf Abfrage | weniger Eingabe bei Änderungen | Verständnis geht verloren, wenn die Übersicht zu knapp ist |
| D Kontextstrategie | D0 persistente Sitzung (nur Deltas) · D1 zustandslos mit Router (erst Bezug klären, dann nur betroffene Teile) · D2 gemischt | D1 bei großen Modellen und Einzeländerungen, D0 bei Gesprächen | D1: ein zusätzlicher Aufruf, Fehlgriff des Routers |
| E Schnittstelle | E0 Claude Code + MCP · E1 MCP mit Bündelwerkzeugen (schreiben, rechnen, prüfen, messen in einem Aufruf) · E2 eigene Orchestrierung (eigener Systemprompt, strukturierte Aufrufe) · E3 Streaming | jede gesparte Runde spart Zeit bis zum ersten Zeichen plus Kontext | weniger Kontrolle des Agenten zwischen den Schritten |
| F Engine | F0 build123d · F1 OCP direkt · F2 deterministische Bausteine (Muster, Symmetrie, Bohrbilder, Kantenwahl nach Bedeutung) | F1 bringt fast nichts (Abschnitt 3); F2 spart Code und Fehler | F2 deckt nicht alles ab |
| G Modell und Denktiefe | Opus · Sonnet; effort niedrig bis hoch | Denken kann einen großen Teil der Ausgabe sein | weniger Qualität bei schwierigen Aufgaben |

Eine direkte Anbindung an die Anthropic-API (ohne Claude Code) bräuchte einen API-Schlüssel und kostet je Token: nur mit
Kevins Ja. Bis dahin steht E2 für sie (eigener Systemprompt über `claude -p`); den festen Aufschlag der CLI misst der
Benchmark mit (Start bis `init`).

## 5. Benchmark

Code in `benchmark/` (README dort). Aufgaben (`benchmark/aufgaben.py`), jede mit Musterlösung und Orakel:

| Id | Aufgabe | Art | Prüft unter anderem |
|---|---|---|---|
| t1 | Montageplatte 120 × 80 × 6, vier Bohrungen Ø 6,6 im Raster 100 × 60, Ecken R 5 | neu, einfach | Maße, Bohrungen und Lage, Radien, Volumen, Material |
| t2 | Flansch Ø 90 mit Ansatz Ø 40, Bohrung Ø 30, sechs Bohrungen Ø 5,5 auf Ø 70, Fase | neu, mittel | Lochkreis, Teilung, Fase, Volumen |
| t3 | Gehäuse 100 × 60 × 40 mit Wand 2, vier Domen mit Sacklöchern, Deckel mit Löchern darüber | neu, komplex, zwei Teile | Lage der Teile zueinander, Durchdringung, Wanddicke über das Volumen |
| t4 | Gestell aus vier Alurohren 12 × 1 (Lager) und zwei gedruckten Platten mit Sacklöchern | neu, Baugruppe | Lagerteile in der Stückliste, Einstecktiefe, Durchdringung, Gesamthöhe |
| t5 | Flansch ändern: acht Bohrungen Ø 6,6 auf Ø 72, Scheibe 10 dick | Änderung | gezielte Änderung, Rest bleibt |
| t6 | Platte ändern: 150 breit, 8 dick, Lochabstand 130 | Änderung | Parameterweg |
| t7 | Kugelschieber (Kopie von Kevins Projekt, 132 Teile, model.py 78.000 Zeichen): Laufrollen 90 statt 100 mm | Änderung am großen Modell | alle 132 Teile gegen die Musterlösung (Hüllquader, Volumen) |
| k1, k2 | Ketten: t1 dann t6, t2 dann t5; die Änderung in derselben Sitzung (`--resume`) und frisch an einer Kopie | Kontextstrategie | Orakel der Änderung |

Stufen:

1. **A ohne Sprachmodell:** Musterlösungen prüfen das Orakel, Kernelzeiten, Größe jeder Darstellung derselben
   Konstruktion (Python, DSL, JSON, Graph), Engine-Vergleich.
2. **B Einzelaufrufe:** ein Aufruf erzeugt bzw. ändert ein Modell in einer Darstellung (ohne Werkzeuge), das Ergebnis
   läuft durch Übersetzer, Kernel und Orakel. Misst Erzeugungszeit, Ausgabetokens, Fehlerquote und Verständnis je
   Darstellung, billig genug für viele Vergleiche.
3. **C volle Agentenläufe:** Baseline und die besten Kombinationen aus B an allen Aufgaben, mit Wiederholungen, wo die
   Unterschiede knapp sind.
4. **D Übernahme:** nur, was in C bei mindestens gleicher Qualität schneller ist, mit Tests, Doku und Skill.

Reproduzierbar: feste Aufträge, fester Kernel-Stand je Variante (`--kernel-src`), festes Modell, Ereignisstrom und
model.py jedes Laufs in der Ablage, Zusammenfassung als JSON. Budgetwächter: kein neuer Lauf, sobald das Wochenlimit bei
75 % steht (Vorgabe `--budget`); am 06.11.2026 abends stand es schon bei 60 %. Kevin hob die Grenze um 19.45 Uhr auf
(„Die Benchmark kann gerne ohne Limit voll weiterlaufen“); am Ende stand das Wochenlimit bei 81 %.

## 6. Varianten-Dateien

`benchmark/varianten/<name>.json`: Skill, Kernel-Stand, Modell, Denktiefe, Systemprompt, verbotene Werkzeuge, weitere
CLI-Schalter. `baseline` ist die bestehende Pipeline.

## 7. Ergebnisse (06.11.2026, 108 gültige Agentenläufe, 104 bestanden)

Auswertung: `kernel/.venv/bin/python benchmark/auswertung.py ~/Library/Caches/de.upvis.kevcad-bench` (mit `--seit` und
`--varianten` für einen Ausschnitt). Kosten laut CLI zusammen 30,39 USD (Abo, nicht abgerechnet). Sieben Läufe sind als
ungültig markiert (Fehler des Benchmarks, Grund in der JSON) und zählen nicht.

### 7.1 Die Wartezeit schwankt stark, deshalb nur verschränkt vergleichen

Dieselbe Baseline brauchte für t1 am Nachmittag 83 s, am Abend 29 s; vor dem ersten Zeichen lagen bei Opus 2 bis 24 s.
Gültig sind deshalb nur Vergleiche aus derselben Runde (je Aufgabe alle Varianten nacheinander, Reihenfolge gedreht).

### 7.2 Realistischer Aufbau (Skill und ToolSearch wie in Kevins Sitzungen), verschränkt ab Runde 5

Median der Gesamtzeit in s, in Klammern Zahl der Läufe, wenn mehr als einer:

| Aufgabe | Baseline (Opus) | Skill neu + K1–K4 (Opus) | dasselbe, Sonnet | dazu Lagebild im Auftrag | Leitfaden im Systemprompt, Werkzeuge sofort |
|---|---:|---:|---:|---:|---:|
| t1 Platte | 29 | 30 | 19 | | |
| t2 Flansch | 38 (2) | 34 (2) | 32 (2) | 27 | 16 |
| t3 Gehäuse | 40 (2) | 36 | 31 (2) | 24 | 18 |
| t4 Gestell | 35 (2) | 38 (2) | 38 (2) | 32 | 44 |
| t5 Flansch ändern | 23 (2) | 17 (2) | 20 (2) | 12 | 13 |
| t6 Platte ändern | 20 (2) | 15 (2) | 19 (2) | 11 | 8 |
| t7 Kugelschieber ändern | 64 (2) | 58 (2) | 57 (2) | 47 | 67 |
| **Verhältnis zur Baseline** (geom. Mittel) | 1,0 | 0,93 | 0,88 | 0,66 | 0,61 |
| Eingabe-Tokens | 1,0 | 0,76 | 0,55 | 0,33 | 0,24 |
| Kosten | 1,0 | 0,76 | 0,34 | 0,27 | 0,22 |
| Annahmen vor dem ersten Bauschritt (Neubauten) | 2/9 | 8/8 | 10/10 | 3/3 | 3/3 |

Kein Lauf erzeugte neue Fehler oder Warnungen der Prüfung (gemessen: Endstand minus Stand vor dem Agenten, ohne die
erwartete Warnung „gedruckt geändert“ beim Kugelschieber).

### 7.3 Laborvarianten (eigener Systemprompt, nur nötige Werkzeuge), verschränkt in Runde 4

| Variante | t7 Kugelschieber ändern | t5 Flansch ändern |
|---|---:|---:|
| Baseline (Opus) | 83 | 27 |
| Kevins voller Kontext (globale Regeln, alle Skills) | 74 | 22 |
| schlank (Kompaktleitfaden im Systemprompt) | 66 | 25 |
| schlank + Kernel K1–K3 | 62 | ungültig |
| schlank + K1–K3 + Lagebild im Auftrag | 49 | 12 |
| schlank, Sonnet | 76 | 26 |
| schlank + K1–K3, Sonnet | 55 | 11 |
| schlank + K1–K3 + Lagebild, Sonnet | 48 | 13 |

### 7.4 Ergebnisse je Achse

- **A Kontextumfang:** Kevins voller Kontext (Regeln 273.000 Zeichen, 110 Skills) kostet das 4,5- bis 5-Fache an
  Eingabe-Tokens, aber keine messbare Zeit (Verhältnis 0,89 bei 3 Läufen). Er belastet das Wochenlimit, nicht die
  Latenz. Ein verdichteter Leitfaden verlor anfangs Information: Die schlanken Varianten schrieben in 0 von 8 Neubauten
  Annahmen in den Kopf; der neue Skill mit den 15 Regeln in Kurzform schreibt sie immer.
- **B Schreibsprache (DSL, JSON, Feature-Graph):** Der Modellcode ist im Median 19 % der Ausgabe, rund 2,5 s je
  Aufgabe (0,9 bis 5,4 s). Eine Sprache, die ihn halbiert, spart etwa 1 s; der Schlussbericht an Kevin ist im Median mit
  1.170 Zeichen länger als der Code. Nicht weiter verfolgt.
- **C Lesedarstellung:** Die Gliederung (Parameter mit Zeile, Schritte, gezeigte Teile; Kugelschieber 3.066 statt
  77.437 Zeichen) und `modell(setze=…)` ersetzen das Lesen großer Dateien. Mit dem Lagebild zusammen halbieren sie kleine
  Änderungen.
- **D Kontextstrategie:** In derselben Sitzung war die Änderung in 7 von 7 Fällen richtig, frisch nur in 3 von 7, und
  meist schneller (Median etwa 16 gegen 23 s; 3 bis 8 statt 9 bis 13 Runden). Alle vier Fehler sind derselbe Fall: Der
  Agent hatte beim Bauen die 80-mm-Seite `breite` genannt; frisch folgt er dem Namen in der Datei, fortgesetzt legt er
  „150 mm breit“ wie gemeint auf die lange Seite. Die Datei allein trägt die Absicht nicht vollständig.
- **E Schnittstelle:** MCP selbst kostet fast nichts (Werkzeugaufrufe 0,01 bis 0,5 s, Start der CLI 1 bis 3 s). Es
  zählt die Zahl der Runden: Jede kostet 3 bis 5 s Wartezeit. Im realistischen Aufbau kosten `Skill` und `ToolSearch`
  zwei Runden, bevor der Agent arbeitet; ohne sie (Leitfaden im Systemprompt, Werkzeuge sofort) und mit Lagebild im
  Auftrag 0,61 der Baseline. Opus prüft nach dem Lauf gern noch zweimal nach (`parts`, `execute`), Sonnet nicht.
- **F Engine:** build123d ist kein Engpass (Lauf 0,02 bis 2,5 s, Kugelschieber nach einer Änderung 2,5 bis 3 s). Bei
  großen Modellen bremst die **Prüfung**: Kugelschieber nach der Änderung 26 bis 34 s bis zum Endstand. Die
  Hauptprüfung endet rund 5 s nach dem Lauf (Statik 3,3, Montage 1,5, Durchdringung 0,5, Druck 0,4); danach rechnet die
  Festigkeit (FEM) 20 bis 27 s, acht Teile nacheinander und alle 20 Fälle neu, auch die der unveränderten Stangenhalter.
  Der Hintergrundblock (5 s, der Bewegungsraum) läuft gleichzeitig mit der FEM; `duration_ms` (10,8 s) ist Hauptprüfung
  plus Hintergrundblock, ohne FEM (berichtigt nach der Analyse in
  [PLAN-PRUEFUNG-INKREMENTELL.md](PLAN-PRUEFUNG-INKREMENTELL.md)). Die Durchdringung rechnet schon nur Geänderte (52 von
  314 Paaren); unverändert kommt alles in 0,1 bis 0,5 s aus dem Gedächtnis. Ein Umstieg auf OCP brächte nichts.
- **G Modell und Denktiefe:** Sonnet ist bei Neubauten deutlich schneller (Platte 19 statt 29 s) und besteht dieselben
  Prüfungen; mit wenigen Runden und Lagebild verschwindet der Unterschied fast (t7: 49 s Opus, 48 s Sonnet). `effort low`
  bei Opus brachte keine Zeit (gleich), nur weniger Ausgabe.

### 7.5 Benchmark-Fehler, die auffielen und behoben sind

- Die App legt beim Start einen leeren Entwurf an, wenn sie 0,35 s nach „Kernel bereit“ kein Projekt sieht; unter
  Last kam das einmal nach dem Öffnen der Aufgabe an und verdrängte sie (`AppSession+Entwurf.swift`). Der Benchmark wartet
  seitdem auf den Entwurf und prüft das offene Projekt vor jedem Agenten. In Kevins App bleibt der Wettlauf möglich, wenn
  ein Agent in den ersten Sekunden nach dem Start ein Projekt öffnet.
- Gleichnamige Skills: Kevins installierter Skill (`~/.claude/skills/kev-cad`) gewinnt gegen den des Projekts; der volle
  Kontext mit neuem Skill ließ sich deshalb nicht messen.
- Zwei versehentlich parallele Warteschlangen teilten sich Test-App und Socket (20.03 bis 20.08 Uhr); diese Läufe sind
  ungültig.

## 8. Entscheidungen

Kevin, 06.11.2026 abends: „Sofort“ übernehmen, Lagebild „im Feedback-Paket“, als Nächstes „Prüfung inkrementell“.

**Übernommen (main):**

| Was | Wo | Beleg |
|---|---|---|
| K1 `run(meilenstein=…, notiz=…)`: Meilenstein am letzten Lauf, eine Runde weniger | `mcp_tools/kern.py` | 7.3 |
| K2 `modell(setze={…})`: `param()`-Vorgaben ändern ohne Lesen | `mcp_tools/kern.py`, `mcp_tools/modell_quelle.py` | 7.3, t5 11 statt 26 s (Sonnet) |
| K3 `modell(gliederung=true)`: Gliederung statt ganzer Datei | ebenda | 7.3, t7 55 statt 76 s (Sonnet) |
| K4 MCP-Anweisungen mit Ablauf in wenigen Runden, Werkzeugliste wieder unter 36.000 Zeichen | `mcp_tools/instructions.py`, `kern.py` | 7.2 |
| K5 Lagebild im Feedback-Paket (Lauf, Prüfstand, Gliederung) | `mcp_tools/feedback_tools.py` | 7.2 Spalte „Lagebild“: 0,66 statt 0,88 |
| Skill kev-cad als Kompaktleitfaden (Ablauf, 15 Regeln kurz, Druckregeln), Rest auf Abruf; Wache 10.000 Zeichen | `skill/kev-cad/SKILL.md`, `ablauf.md`, `feedback.md` | 7.2: 0,76 Eingabe, Annahmen 8/8 statt 2/9 |
| Benchmark | `benchmark/` | |

**Nicht übernommen, weil gemessen ohne Nutzen:** eigene CAD-Sprache, JSON- oder Graph-Schreibweise (7.4 B), OCP statt
build123d (7.4 F), niedrige Denktiefe (7.4 G).

**Empfehlungen ohne Code:** Für Neubauten und Routineänderungen Sonnet. Eine CAD-Sitzung je Projekt offen lassen statt
neu zu starten (7.4 D).

**Offen:**

1. **Prüfung inkrementell (Kevins Wahl als nächstes Paket):** analysiert in
   [PLAN-PRUEFUNG-INKREMENTELL.md](PLAN-PRUEFUNG-INKREMENTELL.md). Rund 85 % der Zeit bis zum Endstand sind die FEM;
   Schritte A1 bis A4 (FEM früher starten, parallel, direkte Zerlegung, Einheitslastfälle) bringen etwa Faktor 3, alle
   Schritte unter Last etwa 6 s.
2. **Startrunden in Kevins Umgebung:** Skill und ToolSearch kosten zwei Runden (7.4 E). Ein eigener CAD-Start
   (Leitfaden im Systemprompt, kevcad-Werkzeuge sofort geladen) brachte 0,61; dafür bräuchte es einen Startweg für
   CAD-Sitzungen in T3 Code. Lagebild bei getippten Aufträgen (Hook) hat Kevin vorerst nicht gewollt.
3. **Kürzerer Schlussbericht** (7.4 B): Kevins Entscheidung, nicht gewählt.
4. **Start-Entwurf der App** (7.5): kleiner Fehler, nicht gewählt.
