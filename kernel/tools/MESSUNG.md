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
