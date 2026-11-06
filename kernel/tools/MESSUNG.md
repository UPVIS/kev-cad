# Messungen des Kernels

Gemessen wird mit `kernel/tools/messen.py` (Laufzeit mit Rechenprozess und App-Attrappe am Socket, Zeitstempel je
Rahmen, immer auf einer Kopie unter /tmp) und `kernel/tools/gedaechtnis_nachweis.py` (Rechengedächtnis mit und ohne).
Zeiten in Sekunden ab dem Aufruf von `run`.

## Messung V2-1

Stand 05.11.2026, MacBook (M2 Pro, 16 GB), Last durch andere Programme 5 bis 7. Kopie von „Kugelschieber Variante B“
(134 Teile) und Katalog, je Stand ein frischer Rechenprozess, Läufe nacheinander: kalt, gleich, nach einer
Kommentaränderung, mit dem Parameter `laufrolle_l = 90` (ändert die Laufrollen, 28 von 599 Booleans neu).

```
kernel/.venv/bin/python -u kernel/tools/messen.py "<Projekt>" --katalog "<Katalog>" \
    --laeufe kalt,gleich,kommentar,param:laufrolle_l=90 --json messung.json
```

„Vorher“ ist `f136caa` (main vor V2-1) mit demselben Werkzeug, „nachher“ `54080e6` mit `warten_s` 3 (Vorgabe;
`6b2030e` ändert danach nur, wie die Laufzeit Bauplan und Blätter eines Laufs verfolgt).

| Lauf | Teile im Viewer | RUN_END | `run()` kehrt zurück | Prüfung im Endstand |
|---|---|---|---|---|
| kalt | 0,85–7,51 → 0,99–7,11 s | 9,30 → 8,77 s | 29,86 → **11,81 s** | 54,60 → 51,53 s |
| gleich | 0,79–5,42 → 0,21–1,36 s | 7,29 → 1,66 s | 7,93 → **2,29 s** | 8,13 → 2,48 s |
| Kommentar | 0,76–5,20 → 0,18–1,32 s | 7,05 → 1,62 s | 7,72 → **2,25 s** | 8,07 → 2,53 s |
| Parameter | 0,77–5,33 → 0,19–1,70 s | 7,19 → 2,12 s | 15,61 → **5,14 s** | 39,17 → 31,86 s |

Mit `warten_s=0` (run wartet gar nicht auf die Prüfung): kalt 8,70 s, Parameter 2,18 s, gleich 1,67 s.

Zum Vergleich die Zahlen aus dem Auftrag (ältere Messskripte, andere Last): kalt `run()` 34,2 s (Prüfung 22 s), gleich
10,9 s, Kommentar 12,7 s, Teile bis 7,9 bzw. 10,2 s.

### Ziele

| Ziel | Ergebnis |
|---|---|
| gleich und Kommentar: alle Teile im Viewer unter 1,5 s | erreicht: bis 1,36 s bzw. 1,32 s |
| gleich und Kommentar: `run()` unter 1,5 s | **nicht erreicht**: 2,29 s bzw. 2,25 s (Gründe unten) |
| Parameteränderung an wenigen Teilen unter 2,5 s | Teile bis 1,70 s, RUN_END 2,12 s; `run()` 5,14 s, weil es 3 s auf die Prüfung wartet (sie braucht 8,4 s); mit `warten_s=0` 2,18 s |
| kalt: Teile nicht langsamer | erreicht für das letzte Teil (7,11 statt 7,51 s); das erste kommt 0,14 s später (0,99 statt 0,85 s: Schlüssel bilden und Ergebnisse merken) |
| kalt: `run()` unter 13 s statt 34 s | erreicht: 11,81 s (RUN_END 8,77 s plus 3 s Warten auf die Prüfung) |

### Warum der warme Lauf nicht unter 1,5 s kommt

`zeiten_ms` des Laufs „gleich“ (alle 599 Booleans aus dem Gedächtnis, nichts neu gerechnet):

| Phase | ms |
|---|---|
| model.py ausführen (`modell`) | 1347 |
| Bedingungen nach dem Lauf (`bedingungen`) | 232 |
| Serialisieren und Senden der 136 Teile | 36 |
| Module, Animation, Stückliste, Rest | 31 |
| RUN_END | 1656 |
| Rückkehr von `run()` (Prüfung „teilweise“ nach 0,63 s: Statik 0,54 s) | 2289 |

Was in `modell` bleibt, wenn nichts mehr gerechnet wird (Abtastung im Prozess, inklusive, teils verschachtelt):
Gedächtnis selbst 0,39 s (Schlüssel aus der Binärform der Eingaben 0,15 s, Ergebnisse lesen 0,13 s), `moved` und
`__deepcopy__` von build123d 0,16 bis 0,22 s (jede Verschiebung kopiert die B-Rep), `chamfer` und `fillet` 0,15 s,
Zukaufteile 0,15 s, `verbinde` 0,09 s, Hüllquader der neu entstandenen Formen 0,05 s. Schon RUN_END liegt damit über
1,5 s; dazu kommt die Statik der Prüfung, auf die `run()` wartet.

### Rechengedächtnis: Nachweis

`kernel/tools/gedaechtnis_nachweis.py` auf Kopien aller fünf Projekte, je Projekt drei Prozesse (zweimal ohne, einmal
mit Gedächtnis), Läufe kalt, gleich, Kommentar, Prüfung bis zum Endstand. Verglichen mit dem ersten Prozess ohne
Gedächtnis: Schlüssel (`tess.key`), Volumen, Fläche, Hüllquader (relativ 1e-6), Warnungen, Parameter, Stückliste,
Bedingungen, Prüfung. Stand `54080e6`.

| Projekt | Teile | Schlüssel gleich | Geometrie anders | sonst anders | Treffer/neu (gleich) | ohne → mit (gleich) |
|---|---|---|---|---|---|---|
| Kugelschieber Variante B | 134 | 98/134 | 0 | – | 599/0 | 6,65 → 1,65 s |
| Stargate Atlantis | 25 | 10/25 | 0 (4,3e-16) | – | 121/303 | 1,70 → 1,77 s |
| Rollwagen Scanprüfung | 13 | 4/13 | 0 | – | 69/0 | 0,58 → 0,12 s |
| Neues Projekt (ohne Inventar-Regel) | 136 | 89/136 | 0 | – | 475/0 | 3,84 → 0,98 s |
| hhfjdf | 4 | 3/4 | 0 | – | 7/0 | 0,02 → 0,01 s |

- Mit Gedächtnis haben alle Läufe dieselben Schlüssel wie der kalte Lauf (134 von 134 usw.).
- Abweichende Schlüssel gegenüber „ohne“ sind Bitunterschiede der Binärform bei gleicher Geometrie: Das Ergebnis teilt
  keine Teilformen mit den Eingaben, und gelesen ist jede Transformation eine `gp_CompoundTrsf` (−0,0 statt 0,0 möglich).
- Stargate: Zwei Prozesse ohne Gedächtnis stimmen ebenfalls nur in 10 von 25 Schlüsseln überein (Extrusion mit Anzug
  rechnet OCCT nicht in jedem Lauf gleich); deshalb dort auch keine Treffer im warmen Lauf.
- Neues Projekt läuft unter der Inventar-Regel nicht durch (Material `polypropylen` fehlt im Katalog) und wird ohne
  die Regel verglichen.

### Prüfung nach dem Lauf

Teilprüfungen im Prozess (`Runner.pruefe`, Kugelschieber, ms):

| Lauf | Durchdringung | Druck | Bedingungen (Bewegungsraum) | Montage | Statik | gesamt |
|---|---|---|---|---|---|---|
| kalt | 2695 | 893 (+227) | 7370 | 6169 | 2977 | 20 570 |
| Parameter `laufrolle_l = 90` | 455 | 366 (+90) | 3770 | 1264 | 2429 | 8 400 |
| gleich | 7 | 27 (+1) | 11 | 2 | 536 | 600 |

- Durchdringung kalt: 314 Paare mit überlappenden Hüllquadern, 253 gerechnet. 170 berühren sich (1,97 s, brauchen den
  genauen Abstand für Stand, Statik und Montage), 6 durchdringen sich (0,07 s), 77 sind frei (0,77 s). Ein Vorfilter
  über die Netze (BVH) könnte nur die freien sparen, höchstens 0,8 von 20,6 s, und bräuchte eine sichere untere
  Schranke für den Abstand aus genäherten Netzen. Nicht umgesetzt.
- Bedingungen im Lauf (`pruefe_bedingungen`): `_flaeche_daten` lief 1318-mal für 341 verschiedene Flächen. Mit dem
  Flächenspeicher während der Phase 0,23 statt 0,40 s je Lauf, gleicher Bericht in allen fünf Projekten (`3c4fe8c`).
- Hüllquader: Im warmen Lauf blieben 702 Fehltreffer im Hüllquader-Speicher des Laufs (`huellen.py`), 214 ms
  `AddOptimal`, davon 200 ms auf 70 Formen mit Torus- und Freiformflächen; der Inhaltsschlüssel kostet 51 ms. Jetzt im
  Gedächtnis je Inhalt (`54080e6`): `modell` 1362 → 1223 ms.
- Warm bleibt die Statik (S1 mit Pynite, Suche nach stärkeren Lagerteilen) mit 0,54 s der größte Teil der Prüfung.
  Sie ließe sich je Statikmodell merken; dafür bräuchte es einen vollständigen Fingerabdruck von `StatikModell`,
  Szenarien und Katalog (Strang Statik). Nicht umgesetzt.

### Was jeder Lauf zur App schickt

Auch ohne Änderung: `PART_UPSERT` 136-mal (6,95 MB), `STATICS_FIELD` 20-mal (1,63 MB), `ANIM_DEF` (1,53 MB), bei
einer neuen Version `VERSION_BILD_REQ` (5,90 MB). Unveränderte Teile nicht erneut zu schicken, bräuchte eine Änderung
des Protokolls und war nicht Teil von V2-1.

### Tests

Volle Testsuite (`kernel/tests`) auf `6b2030e`: 1107 bestanden, 16 fehlgeschlagen, 1 übersprungen (18 min). Dieselben 16
schlagen auf der Basis `f136caa` fehl: CalculiX-Tests (Simulation, Statik Stufe 3 und 4) mit `UnicodeDecodeError`
(ASCII-Codec im Testprozess). An `LANG=C.UTF-8` allein liegt es nicht: Python meldet darunter UTF-8, und
`test_statik4.py::test_hertz_kugel_auf_platte` läuft einzeln auch mit `LANG=C.UTF-8` grün (nachgeprüft 05.11.2026).
Vermutlich stellt im vollen Lauf etwas die Locale des Testprozesses um; offen (PLAN-V2.md, Abschnitt 7). Auf der Basis
kamen 8 Druck-Tests dazu, in denen Bambu Studio nicht antwortete; im Lauf auf `6b2030e` liefen sie durch. Neu sind
`test_gedaechtnis.py` (15 Tests) und `test_tempo.py` (7 Tests).

### Werkzeuge zum Messen

- cProfile sieht die Zeit in OCP-Methoden nicht (C++-Erweiterung ohne Python-Rahmen) und verfälscht durch den eigenen
  Aufwand: Ein Lauf mit Millionen Aufrufen wirkt deutlich langsamer, die OCCT-Zeit verschwindet in den Aufrufern. Für
  OCCT-Arbeit die Abtastung des Hauptfadens nehmen (`messen.py --profil`, alle 1 ms) oder Wanduhr-Hüllen um die
  verdächtigen Aufrufe.

## Messung V2-5a (Delta-Übertragung)

Stand 05.11.2026 spätabends, Kopie von „Kugelschieber Variante B“ und Katalog, ein frischer Rechenprozess. `messen.py`
zählt seit V2-5a ganze Rahmen (Kopf und Nutzlast), die App-Attrappe meldet die Fähigkeiten aus PROTOCOL.md, Abschnitt
„V2-5 Live“:

```
kernel/.venv/bin/python -u kernel/tools/messen.py "<Projekt>" --katalog "<Katalog>" \
    --laeufe kalt,gleich,kommentar,param:laufrolle_l=90,gleich,param:laufrolle_l=90 \
    --faehigkeiten delta-1,in-arbeit-1,spur-1,lage-1,live-masse-1 --json messung.json
```

Die Zeiten taugen hier nicht zum Vergleich: Der Rechner stand unter Last anderer Agenten. Die Bytes schon.

| Lauf | vorher | mit `delta-1` | was bleibt |
|---|---|---|---|
| kalt | 18,71 MB | 11,14 MB | alles einmal; das Versionsbild schrumpft von 5,9 MB auf 19 KB (Netze aus der Szene) |
| gleich | 11,33 MB | **44 KB** (Budget 50 KB) | `WIE_ZUVOR` 18 KB, `PART_SAME` 17 KB, `RUN_END` 6 KB |
| Kommentar | 17,25 MB | 53 KB | dazu das Versionsbild (19 KB) |
| Parameter `laufrolle_l = 90` | 12,61 MB | 4,47 MB | 20 Teile 1,0 MB, Statikfelder 1,6 MB, Animation 1,5 MB |
| zurück auf „gleich“ | 11,38 MB | 1,76 MB | fast nur `ANIM_DEF` (1,5 MB); Teile und Felder kommen aus den letzten 4 Inhalten |
| wieder Parameter | – | 1,72 MB | ebenso |

- Unverändert heißt: alle 136 Teile als `PART_SAME`, keine Nutzlast. Die Weiche prüft vor jedem `WIE_ZUVOR`, dass der
  Aufbau genau den neuen Kopf ergibt, sonst geht die Nachricht vollständig.
- Eine Animation merkt sich die Weiche nur einmal je Name, deshalb kostet ein Maß, das hin und her wechselt, jedes Mal
  1,5 MB. Lohnt sich erst, wenn es im Alltag stört.
- Eine App ohne `faehigkeiten` bekommt alles wie bisher; `test_live.py` prüft das mit der alten Attrappe.

## Messung V2-5b (echte App)

Stand 06.11.2026 nachts, MacBook mit vielen parallelen Agenten (Last 40 bis 120, zwischendurch über 500). Kernel im Prozess,
Testvariante der App verbunden, Kopie von „Kugelschieber Variante B“ und Katalog; gezählt wird, was auf den Draht geht
(ganze Rahmen), was die Szene der App getan hat, meldet ihr LAGE in Testvarianten:

```
tools/fern.sh testbau live
kernel/.venv/bin/python -u kernel/tools/live_selbsttest.py "build/Kev CAD Test live.app" "<Projekt>" \
    --param laufrolle_l=90 --json live.json
```

| Lauf | vorher (V2-5a, App ohne Fähigkeiten) | jetzt, echte App | was bleibt |
|---|---|---|---|
| unverändert | 11,33 MB | **32 KB** (Budget 50 KB) | `PART_SAME` 17 KB, `WIE_ZUVOR` 7 KB, `RUN_END` 6 KB, `STEP` 2 KB |
| Kommentar (neue Version mit Bild) | 17,25 MB | 54 KB | dazu das Versionsbild 19 KB: alle 134 Netze aus der Szene |
| Parameter `laufrolle_l = 90` | 12,61 MB | 4,47 MB | 20 von 134 Teilen 1,0 MB, Statikfelder 1,6 MB, `ANIM_DEF` 1,5 MB |
| zurück auf den alten Wert | 11,38 MB | 1,76 MB | fast nur `ANIM_DEF`; die 20 Teile kommen ohne Netz aus dem Speicher der App |

| Was die App im unveränderten Lauf tut | vorher (aus dem Code hergeleitet) | jetzt (gemessen) |
|---|---|---|
| Körper neu gebaut | 3 (Zwischenstände eines Teils, das model.py dreimal zeigt) | 0 |
| Teile leuchten auf | 3 | 0 |
| Weitergaben an den Viewport | rund 140 (eine je Teil, dazu Beginn und Ende des Laufs) und die Schritte des Aufleuchtens | **0** |

Bei einer Parameteränderung baut die App genau die 20 geänderten Teile neu, beim Rückweg tauscht sie genau diese 20 aus
dem Speicher. `run()` kehrt im unveränderten Lauf nach 2,5 s zurück, das letzte Teil steht nach 1,5 s (Last um 60).

**Lagebild** (100 Abfragen in Ruhe, 40 während eines Laufs, gemessen im Kernel vom Senden bis zur Antwort):

| | Median | 95 % | Größtwert | davon die App selbst |
|---|---|---|---|---|
| in Ruhe | 9,0 ms | 19,0 ms | 21,2 ms | unter 1 ms |
| während eines Laufs | 13,1 ms | 38,8 ms | 40,2 ms | unter 1 ms |

Das Budget von 50 ms hält bei normaler Last. Unter schwerer Last (über 100) kamen einzelne Antworten erst nach 100 bis
970 ms: Dann ist der Hauptfaden der App kurz belegt. Über 200 ms nimmt der Kernel seinen eigenen Stand.

**Viewer** (`KEVCAD_SELFTEST=viewer`, Stand `v2` und V2-5b je zweimal im Wechsel, gleiche Kopie, Last 25 bis 65, 0 Fehler in
allen vier Läufen):

| | Bilder/s über die sieben Darstellungen | Hauptfaden je Bild, Median | GPU je Bild, Median (Darstellung „wie bisher“) |
|---|---|---|---|
| `v2` | 37 bis 41, 38 bis 41 | 1,17 und 1,23 ms | 8,0 und 3,5 ms |
| V2-5b | 35 bis 38, 38 bis 42 | 1,21 und 1,09 ms | 7,6 und 3,4 ms |

Kein Unterschied über die Streuung hinaus; V2-5b ändert am Zeichnen je Bild nichts. Beide liegen unter den 58 bis 60
Bildern/s aus V2-4. Ob das an der Last oder an V2-3 liegt, ist hier nicht geklärt.

Gefunden hat der Selbsttest, was die App-Attrappe nicht sehen konnte:

- Das stille Nachladen des Katalogs nach jeder Stückliste kostete 250 KB je Lauf (`CATALOG_REQ` nimmt jetzt `stand`).
- Teile, die model.py in einem Lauf mehrmals zeigt, sprangen hin und her (3 Körper je Lauf).
- Die Schnittkörper der Prüfung gingen bei jedem Lauf neu an den Viewport, auch ohne Änderung.

Selbstheilung am echten Paar: Ein `PART_SAME` mit unbekanntem Inhalt holt das Teil über `PARTS_REQ` neu, ein `WIE_ZUVOR`
mit unbekannter Basis die Nachricht über `NOCHMAL`.

## Messung V2-1b (Tempo nachziehen)

Stand 06.11.2026, MacBook (M2 Pro, 16 GB) mit anderen Agenten daneben. Vorher und nachher deshalb im Wechsel: je Runde erst
die Basis `45fe2c5`, dann dieser Stand, zwei Runden, Last 10 bis 57 (Runde 2 beim neuen Stand 20). Beide Spalten zeigen
Runde 1 / Runde 2. Kopie von „Kugelschieber Variante B“ und Katalog, je Stand ein frischer Rechenprozess:

```
kernel/.venv/bin/python -u kernel/tools/messen.py "<Projekt>" --laeufe kalt,gleich,kommentar,gleich,param:laufrolle_l=90,gleich,param:laufrolle_l=95 \
    --faehigkeiten delta-1,in-arbeit-1,spur-1,lage-1,live-masse-1 --pruef-max-s 45 --json messung.json
PYTHONPATH=<Basis>/kernel/src kernel/.venv/bin/python -u <Basis>/kernel/tools/messen.py …   # dieselben Läufe mit der Basis
```

| Lauf | Teile im Viewer | RUN_END | `run()` zurück | erstes Prüfergebnis |
|---|---|---|---|---|
| kalt | 7,40 / 9,40 → 7,73 / 7,26 s | 9,07 / 11,21 → 9,44 / 8,85 s | 12,13 / 14,39 → 12,35 / 11,56 s | 30,40 / 34,58 → **13,26 / 11,89 s** |
| gleich | 1,30 / 1,29 → 1,11 / 0,96 s | 1,61 / 1,63 → 1,34 / 1,18 s | 2,25 / 2,29 → **1,44 / 1,37 s** | wie `run()` |
| Kommentar | 1,30 / 1,34 → 1,02 / 0,89 s | 1,61 / 1,64 → 1,25 / 1,10 s | 2,29 / 2,30 → **1,55 / 1,19 s** | 2,29 / 2,30 → 1,58 / 1,31 s |
| `laufrolle_l = 90` | 1,82 / 1,79 → 1,64 / 1,47 s | 2,25 / 2,22 → 1,99 / 1,79 s | 5,38 / 5,24 → **2,43 / 2,30 s** | 11,31 / 11,60 → 2,51 / 2,30 s |
| `laufrolle_l = 95` | 1,92 / 4,86 → 2,05 / 1,53 s | 2,36 / 5,29 → 2,42 / 1,85 s | 5,44 / 8,34 → **2,86 / 2,35 s** | 12,12 / 14,78 → 2,97 / 2,36 s |

Budgets: unveränderter Lauf unter 1,5 s und Maßänderung unter 2,5 s sind bei einer Last um 20 erreicht. Unter stärkerer Last
reißt die Maßänderung: Mit Last 30 bis 50 steht RUN_END bei 2,4 s, `run` kehrt nach 2,8 s zurück. Der Zwischenstand ist dann
noch unterwegs, `run` sagt das (`running`) und nennt vorläufig die Befunde der Bedingungen.

Was nach einer Maßänderung in welcher Stufe kommt (`laufrolle_l = 90`, Last 28, ab dem Start des Laufs):

| Zeit | Zustand | was da ist |
|---|---|---|
| 2,1 s | `running` | RUN_END |
| 2,7 s | `teilweise` | Durchdringung, Bedingungen, Stand; offen: Druck, Montage, Statik, Bewegungsraum |
| 7,2 s | `teilweise` | dazu Druck, Montage, Statik; offen: 8 Wege des Bewegungsraums, Ablauf und Festkörper |
| 11,8 s | `teilweise` | dazu der Bewegungsraum; offen: Ablauf und Festkörper |
| 32 s | `done` | Endstand |

### Start des Kernels

`kernel/tools/messen_start.py` startet den Kernel wie die App, wartet auf „bereit“, legt nach 0,35 s den Entwurf an und fragt
über MCP, bis `status` ihn nennt. Sekunden ab dem Start des Prozesses, je 5 Läufe im Wechsel, Last 16 bis 19:

| | Basis | jetzt |
|---|---|---|
| Socket offen | 2,3 bis 8,0 s | 0,4 bis 1,2 s |
| „bereit“ | 4,4 bis 10,7 s | 0,4 bis 1,3 s |
| `status` nennt das Projekt | **4,7 bis 11,2 s** | **0,8 bis 1,7 s** |
| erster Lauf im leeren Projekt fertig | 4,9 bis 11,4 s | 2,2 bis 5,3 s |

Woran es lag: Der Elternprozess lud build123d über `kevcad_kernel.druck` (2,0 s) und startete den Rechenprozess erst danach,
der es noch einmal lud; „bereit“ kam erst mit dem Rechenprozess. Jetzt lädt der Elternprozess beim Start weder build123d noch
OCP, scipy oder pandas (0,4 statt 2,8 s Importe; ein Test hält das fest), meldet „bereit“ sofort (ein Lauf wartet selbst auf den
Rechenprozess) und lädt build123d erst, wenn der Rechenprozess bereit ist: Der Import hält die GIL, App und MCP kämen sonst
nicht dran (Projekt nach 3,6 statt 1,4 s). `import build123d` braucht ohne `sklearn` 1,2 statt 2,0 s; sklearn nutzt build123d
nur für `DBSCAN` beim Netz-zu-B-Rep, der Stellvertreter in `schnellstart.py` lädt es beim ersten Aufruf.

### Was der warme Lauf jetzt kostet

Wanduhr-Hüllen im Prozess, Last um 30, ms (die Abtastung täuscht hier: OCP-Aufrufe halten die GIL, sie sieht vor allem, wo
die GIL frei wird):

| | V2-1 | jetzt |
|---|---|---|
| `modell` | 1380 | 1100 |
| davon `Shape.moved` (1065 Aufrufe) | 181 | 31 |
| `chamfer` / `fillet` | 112 / 48 | 14 / 4 |
| Booleans (489 Aufrufe; 174 Schlüssel, Rest Ergebnisse lesen) | 385 | 385 |
| Bedingungen nach dem Lauf | 240 | 150 |
| Statik in der Prüfung | 540 bis 680 | 7 bis 12 |
| Prüfung gesamt | 600 | 90 |

`Shape.moved` kopierte die ganze B-Rep und ersetzte die Kopie im nächsten Schritt. Der Garbage Collector zählt nicht:
abgeschaltet, mit hoher Schwelle oder `gc.freeze()` gemessen im Wechsel kein Unterschied über 2 %.

### Bauplan im Hintergrund

Ab der zweiten Maßänderung kostete jeder Lauf 2,6 bis 3,1 s mehr (`senden` statt 15 ms; der Rechenprozess wartete auf den
Lesefaden der Laufzeit). Ursache war der Bauplan des vorigen Laufs im Elternprozess (13 s Python und OCCT): Er hielt die GIL.
Sein Ergebnis hätte er nicht mehr speichern dürfen (`_lauf_aktuell`). Jetzt endet er, sobald ein neuer Lauf beginnt
(`bauplan/wege.py`: `halt`, `Ueberholt`). Ohne Wirkung war `sys.setswitchinterval(0.0005)`: lange OCP-Aufrufe geben die GIL
nicht ab.

### Gleichheit

`kernel/tools/gedaechtnis_nachweis.py` auf Kopien aller fünf Projekte, jetzt mit vier Läufen (dazu ein Lauf mit Parameter),
der Prüfung in Stufen im Prozess mit Gedächtnis und am Stück ohne, und verglichen werden zusätzlich die Montagefolge und die
Ampeln der Statik. Bestanden: keine Abweichung an Geometrie (außer 4,3e-16 bei Stargate wie in V2-1), Warnungen, Parametern,
Stückliste, Bedingungen, Befunden, Montage und Statik. Der vorgegebene Parameter ändert in drei Projekten keine Form, deshalb
zusätzlich für den Kugelschieber mit `--parameter laufrolle_l=90` (34 Operationen neu): ebenfalls bestanden, Lauf 7,24 → 1,82 s.

Dabei fiel auf: Der Parameterlauf wich schon auf der Basis ab, und zwar im Kontaktgraph. Bowlingball und Schieberolle haben
nominal genau 0,5 mm Abstand, also die Grenze `BERUEHR_TOL`. OCCT misst das je nach Reihenfolge der Formen als knapp
darüber oder darunter, und die Reihenfolge hängt am Formschlüssel. `BERUEHR_GRENZE` nimmt das Rundungsrauschen (1e-9 mm) mit
hinein. Am Kugelschieber ändert das gegenüber der Basis nur die Reihenfolge der Teile in einem Hinweis: Der Ball gehört jetzt
in allen Läufen zur großen Gruppe, die Menge der 51 bzw. 54 Befunde bleibt gleich.

Offen: Ein Durchlauf für den Kugelschieber meldete bei einer Last von rund 600 (fremde Prozesse) „nicht bestanden“. Der Lauf
mit Parameter war sauber, welcher der drei anderen abwich und worin, ist nicht festgehalten (Ausgabe gefiltert). Derselbe Stand
bestand davor und danach. Vermutung, nicht belegt: ein Zeitlimit (die Montage bricht nach 60 s ab).

Die Statik gerechnet streut für sich: Die Knicklast kommt aus ARPACK mit einem Zufallsvektor (2525 und 2416 in zwei Läufen).
Ein Treffer im Gedächtnis macht sie stabiler, nicht ungenauer.

### Tests

Volle Suite über `tools/fern.sh tests` auf dem Mac mini, nach dem Zusammenführen mit V2-8: 465 Swift-Tests (einer übersprungen)
und 1246 Kernel-Tests (23 übersprungen), alle grün, 6:25 min. Neu sind `test_tempo_pruefung.py` (Statik-Gedächtnis, Stufen, Start,
Bauplan) und in `test_gedaechtnis.py` die Fasen, Verrundungen, `moved` und Innenzylinder. Die Testsuite rechnet die Prüfung am
Stück (`KEVCAD_PRUEF_STUFEN=0` in `conftest.py`, Stufen hängen an der Uhr); `test_tempo_pruefung.py` schaltet sie ein. Die
Laufzeit-Tests von Bauplan, Statik, Druck, Bedingungen, Live und Prüftempo laufen auch mit `KEVCAD_PRUEF_STUFEN=1` grün.
## Messung V2-8 (Oberfläche, Tests, Installation)

Stand 06.11.2026. Kugelschieber Variante B (134 Teile) als Kopie.

**Drehen im Viewer** (`kernel/tools/selbsttests.py … viewer --hier`, Fenster hinter dem Schreibtischbild, MacBook unter Last
130 bis 190). Neu im Bericht: Arbeitsstücke des Hauptfadens über 30 ms mit dem, was darin lief (`HauptfadenProtokoll`, ein
Beobachter der Hauptschleife, ohne `sample`).

| Darstellung | Bilder in 3 s | Hauptfaden je Bild | GPU je Bild | längster Takt | Stücke über 30 ms |
|---|---|---|---|---|---|
| wie bisher | 357 | 1,16 ms | 6,01 ms | 26 ms | keins |
| Solid ohne Verdeckung, ohne Kanten | 370 | 0,95 ms | 5,56 ms | 21 ms | keins |
| Solid ohne Verdeckung | 359 | 1,18 ms | 5,28 ms | 26 ms | 39 ms |
| Solid mit Verdeckung und Kantenbetonung | 362 | 1,19 ms | 5,63 ms | 29 ms | 39 ms |
| Solid mit allem und Schatten | 343 | 1,47 ms | 6,97 ms | 21 ms | 65 und 37 ms |
| Material mit Verdeckung | 357 | 1,18 ms | 5,54 ms | 17 ms | 56 ms |
| Technisch | 361 | 1,17 ms | 5,72 ms | 20 ms | keins |

Nach dem Entfernen der Formmaske, Last 20 bis 30: 376 bis 387 Bilder in 3 s, Hauptfaden 0,83 bis 1,32 ms, GPU 3,7 bis 5,3 ms, längstes
Stück 48 ms (eine Nachricht CHECK), sonst höchstens 34 ms.

Die 850 ms in „Technisch“ aus V2-4 kamen nicht wieder, auch nicht unter deutlich höherer Last; was damals lief, lässt sich nicht
mehr feststellen. Kein Stück enthält eine Kernel-Nachricht, alle sind Oberfläche und liegen unter 65 ms. Hauptfaden und GPU kommen
zusammen auf gut 7 ms je Bild, die 35 bis 42 Bilder/s von V2-5b entstanden also nach dem Zeichnen.
V2-3 hatte über den Viewer eine `.clipShape` gelegt: eine Formmaske, für die das Fenstersystem jedes Bild erst abseits
zusammensetzen muss. Die Ecken setzt jetzt die Metal-Ebene selbst. Ob das die Ursache war, zeigt nur ein Monitor: Hinter dem
Schreibtischbild und auf dem Mini kommt kein Bild an.

**Kacheln** (`tools/fern/kachel-selbsttest.sh`, Mac mini, längste Pause des Hauptfadens, zwei Läufe, je 54 von 54 Prüfungen):

| Was | V2-7 | V2-8 |
|---|---|---|
| Kachel 2 groß (Zeichnung) | 118 bis 142 ms | 50, 60 ms |
| alle einordnen | 66 ms | 35, 42 ms |
| Kachel zweites Mal: Stückliste, Zeichnung, Material | 103, 29, 65 ms | 83 bis 117, 85 bis 90, 83 bis 91 ms |
| Kachel zweites Mal: Rendern, Simulation | 146, 132 ms | 141, 105 bis 119 ms |
| an den Rand, zurück | 59, 88 ms | 107 bis 137, 65 bis 86 ms |

Die Nebenspalten bauen sich jetzt eine Sekunde nach dem Öffnen auf, das liegt im Messfenster und erklärt die Zeichnung; das Öffnen
bleibt unter der Grenze von 300 ms. „An den Rand“ ist langsamer als in V2-7, der Grund ist offen; eine Grenze gibt es dafür nicht.

**Start** (`KEVCAD_SELFTEST=oberflaeche`, Mac mini ohne fremde Last): Fenster nach 0,19 s, bedienbar nach 0,20 s, Rechenzeit
des Hauptfadens 0,14 s. Der Kernel brauchte dort beim ersten Start einer neuen Umgebung 46 s, gut 50 s am MacBook unter Last:
Das ist der erste Import ohne Bytecode. Seit V2-8 übersetzt `uv sync --compile-bytecode` beim Installieren, und `build.sh` lädt den
Kernel einmal; danach dauert der Import in der frischen Installation 3,8 s statt 53 s.

**Tests** (`tools/fern.sh tests`, Mac mini): fünf volle Läufe, 465 Swift-Tests und rund 1200 Kernel-Tests. Der erste scheiterte an
einer Zeitgrenze unter Last (`test_bewegungsraum_zwischenspeicher_ueber_laeufe`, die Grenze ist entfernt, die Prüfung auf den
Zwischenspeicher bleibt), die vier übrigen waren grün, in 7 Minuten je Lauf.

- **Locale:** `lib3mf` setzt beim Schreiben `setlocale(LC_ALL, "C")` (nachgestellt: `locale.getencoding()` wird `US-ASCII`). Der alte
  Stand scheitert danach an `test_hertz_kugel_auf_platte` mit `UnicodeDecodeError`. Mit Rücksetzen nach jedem Test laufen 3MF und
  CalculiX im selben Prozess ohne `PYTHONUTF8` durch.
- **test_unveraendert_wird_nichts_neu_gerechnet:** Auch der Bauplan schickt ein DOCS, mit den Blättern von zuletzt. Mit künstlich
  verzögertem Nachtrag schlägt der alte Test in zwei von drei Läufen fehl (`blatt.kopf["run"]` noch vom Lauf davor). Der Test wartet
  jetzt auf das Future `job.dokumente`.
- **test_gleitende_lager_schraeg_in_der_fem:** Gmsh rechnet mit vier Fäden, jeder Lauf hat ein anderes Netz (12.003 bis 12.138
  Freiheitsgrade). In 50 Läufen waren die Lagerkräfte exakt und die Meldung gleich. Der Fehler trat in fünf vollen Läufen nicht auf.

**Installation** (`KEVCAD_UPDATE_PROBE`, `KEVCAD_UPDATE_REF`, Zweig dieses Pakets): gesamt 130 s, davon 65 s auf dem Mini. App mit
„Developer ID Application: KEVIN SCHWED (2GX7UC98J6)“, `codesign --verify --deep --strict` in Ordnung, Skill mit allen 16 Dateien
gleich dem Repo, `kevcad-kernel check` läuft, `kevcad-mcp`, `kevcad-feedback`, fotomess und scan vorhanden. Über die installierte
Brücke: 25 Werkzeuge, 5.989 Zeichen Anweisungen, `stock_search` antwortet mit `katalog(suche=…)`. KevCADWire baut wie in VoiceBridge über
das `Package.swift` im Wurzelordner für macOS und iOS.
