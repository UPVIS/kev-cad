# Prüfung inkrementell: Analyse und Plan

Stand 06.11.2026, Analyse ohne Umsetzung (Code-Stand `58a41bd`). Auftrag aus PLAN-PIPELINE.md Abschnitt 8: Kugelschieber
nach einer kleinen Änderung unter 5 statt 26 s bis zum Endstand. Kevins Bedingung: Die Qualität sinkt nicht, das Ergebnis
ist dasselbe wie bei voller Neuberechnung.

Kurzfassung:

- Von den rund 29 s (Lauf 3 s, `pruefen(endstand=True)` 26 s) sind rund 85 % die **Festigkeit (FEM)**: ein Prozess, acht
  Teile nacheinander, alle 20 Fälle neu, 18,5 bis 26,8 s. Sie startet erst nach der ganzen Hauptprüfung.
- Der „Hintergrundblock“ (`zeiten_ms.hintergrund`, 5,0 s bei Kevin, 3,9 bis 4,5 s hier) ist der **Bewegungsraum**, den der
  Rechenprozess nach dem Zeitbudget der Stufen fertig rechnet. Er läuft gleichzeitig mit der FEM und liegt heute nicht auf
  dem kritischen Pfad.
- Ohne geänderte Eingaben wird vor allem eines neu gerechnet: die FEM der vier **unveränderten Stangenhalter** (12 von 20
  Fällen). Nur ihre Lagerkräfte aus dem Stabwerk ändern sich um rund 1 %; Netz, Steifigkeit, Kontaktflächen und
  Zerlegung entstehen trotzdem neu. Dazu im Bewegungsraum 206 von 877 exakten Schnitten (Schlüssel mit Lage statt Form
  plus relativer Lage) und die Planungsschleife der Montage.
- Statik, Durchdringung und Druck rechnen schon nur Geändertes. Das Statik-Gedächtnis über das ganze Modell kostet hier
  nichts Vermeidbares: Die teuren Schnitte unveränderter Teile kommen schon aus dem Speicher, und S1 muss neu, weil sich
  das Stabwerk ändert.
- Mit den FEM-Schritten A1 bis A4 sinkt der Endstand auf etwa 11,5 s, mit allen Schritten auf etwa 6 s unter Last bzw.
  vermutlich unter 5 s auf einem ruhigen Mac. Unter 5 s geht nur mit Parallelarbeit in eigenen Prozessen; reines
  Zwischenspeichern reicht nicht, weil die Änderung 6 Formen und 14 Lagen im beweglichen Teil des Modells trifft.

## 1. Messaufbau

- Kopie von „Kugelschieber Variante B“ (134 gezeigte Teile, model.py 76 KB), Kernel im Prozess wie
  `benchmark/pruefzeit.py`, ohne App und ohne Sprachmodell. Arbeitsordner, Druck- und FEM-Zwischenspeicher und TMPDIR auf
  UPVIS ULTRA (die Systemplatte hatte 2,8 GB frei).
- Schritte: kalt, `laufrolle_l=90` (wie t7), dieselbe Änderung noch einmal, zurück auf die Datei, `laufrolle_l=95`.
- Messhülle ohne Eingriff in den Repo-Code (`sitecustomize` über PYTHONPATH, wirkt in Laufzeit, Rechenprozess und
  FEM-Prozess): Zeitstempel je Ereignis, Wanduhr je Funktion, Schattenzähler für andere Schlüssel, Sicherung der
  FEM-Aufträge für Löserversuche. Skripte unter `benchmark/pruefzeit_analyse/`, Rohdaten unter
  `/Volumes/UPVIS ULTRA/_cache/kevcad-pruefzeit/`.
- cProfile im Rechenprozess lieferte unter Python 3.12 einen zerrissenen Aufrufbaum (Wurzelrahmen fehlen, nur 3,8 von
  5,9 s erfasst) und ist verworfen; gemessen ist mit Wanduhr-Hüllen.
- Fünf Messläufe zwischen 20:54 und 21:13 Uhr, Systemlast 13 bis 40 (andere Agenten: AutoShade, iOS-Simulator). Absolute
  Zeiten schwanken deshalb (Endstand 26,5 s bei Last 17, 34,0 s bei Last 32); Zählungen und Anteile sind stabil.

## 2. Wohin die Zeit nach der Änderung geht

Zeitleiste ab Beginn von `run(params={"laufrolle_l": 90})`, Bereich aus 5 Messungen (Median in Klammern):

| Zeitpunkt | Was | Dauer |
|---|---|---|
| 0 → 1,9–2,0 s | Lauf im Rechenprozess: model.py 1,6–1,7 s, Bedingungen 0,27–0,29 s, Tessellierung 0,27 s | 2,0 s |
| → 2,5 s | Zwischenstand: Durchdringung 0,49–0,52 s (52 von 314 Paaren neu), Stand 0,015 s | 0,5 s |
| → 7,2–8,0 s | Rest der Hauptprüfung: Druck 0,39–0,53, Druckvorschau 0,09–0,13, Montage 1,45–1,67, Statik 2,63–3,39, Bewegungsraum im Budget 0,06 | 4,7–5,4 s |
| 7,3 s | Laufzeit startet die FEM: Auftrag im Rechenprozess (EXEC, 26–38 ms), dann FEM-Prozess | |
| 7,3 → 11,6–12,3 s | Rechenprozess: Bewegungsraum fertig rechnen (`hintergrund`) | 3,9–4,5 s |
| 7,3 → 26,5–34 s | FEM-Prozess: 8 Teile nacheinander, 20 Fälle, alle neu | 18,5–26,8 s (24,8) |
| 26,5–34 s (32,8) | Endstand | |

- `duration_ms` (10,8 s bei Kevin) ist Hauptprüfung plus Hintergrundblock; die FEM steckt nicht darin. Korrektur zu
  PLAN-PIPELINE.md 7.4 F: nicht „Hauptprüfung 10,8 s, danach rund 15 s FEM“, sondern Hauptprüfung rund 5 s nach dem Lauf,
  danach 20 bis 27 s FEM, der Hintergrundblock parallel dazu.
- Sonst läuft nach der Hauptprüfung nichts Nennenswertes: kein Ablauf (S2, das Modell hat kein Szenario mit
  Geschwindigkeit), keine Topologie, kein Schattenlauf der Versionen. STATICS, Versionen, Druckvorschau und Simulation in
  der Laufzeit kosten je Millisekunden.

### 2.1 FEM je Teil (Messung m3, Last 19)

| Teil | Fälle | Netz | Steifigkeit | Lösen | gesamt | Geometrie |
|---|---|---|---|---|---|---|
| Stangenhalter vorn links | 3 | 127 ms | 167 ms | 4.131 ms (AMG) | 4,9 s | unverändert |
| Stangenhalter vorn rechts | 3 | 2 ms | 279 ms | 829 ms (LU) | 1,4 s | unverändert |
| Stangenhalter hinten links | 3 | 1 ms | 148 ms | 904 ms (LU) | 1,3 s | unverändert |
| Stangenhalter hinten rechts | 3 | 2 ms | 212 ms | 1.060 ms (LU) | 1,6 s | unverändert |
| Fangrolle | 1 | 1.847 ms | 256 ms | 450 ms (LU) | 2,9 s | Form neu |
| Schieberolle | 1 | 118 ms | 273 ms | 554 ms (LU) | 1,3 s | Form neu |
| Schieberschlitten rechts | 3 | 205 ms | 374 ms | 4.516 ms (AMG) | 5,7 s | Form neu |
| Schieberschlitten links | 3 | 169 ms | 318 ms | 4.438 ms (AMG) | 5,5 s | Form neu |

Zerlegung eines unveränderten Teils (Stangenhalter vorn links, 25.794 Freiheitsgrade, davon 24.990 frei, 2,09 s):
SuperLU-Zerlegung 1,37 s, Steifigkeit 0,24 s, Kontaktflächen 0,24 s, Netzaufbau 0,09 s, Lastvektoren 0,04 s, drei
Lösungen 0,04 s, Auswertung 0,03 s. Was von den Lasten abhängt, kostet unter 0,15 s.

### 2.2 Hauptprüfung je Funktion (Wanduhr, Messung m3)

| Stufe | Zeit | Inhalt |
|---|---|---|
| Statik | 2,8–3,4 s | 84 OCCT-Schnitte durch geänderte Teile (`bauteil._schnitt`, je 25–31 ms) 2,1–2,6 s; Stabwerk S1 0,35 s; Inventar-Vorschläge (`staerker`, zweites Stabwerk) 0,24 s; S0 0,11 s; Modellaufbau 0,02 s |
| Montage | 1,46–1,67 s | 256–258 neue Sperrtests (`raster.blockiert`) 0,69–0,71 s; Planung (Kandidaten, `frei`, Zwei-Schritt-Wege) 0,75–0,85 s |
| Druck | 0,39–0,40 s | 6 Druckteile neu (`_pruefe_form` 0,36–0,37 s), 10 aus dem Speicher |
| Bewegungsraum (Hintergrund) | 3,9–4,5 s | 8 von 18 Wegen neu, 877–884 exakte Schnittmengen (3,4 s), Griffraum der vier Sterngriffschrauben (je 0,17–0,2 s) |

Wege nach der Änderung: Fängerschlitten links 1,51 s, die vier Sterngriffschrauben der Schlitten je 0,48–0,63 s,
Schieberschlitten links 0,32 s, Seitenstangen 0,10 und 0,15 s; die übrigen 10 Wege (Lenkrollen, vordere und hintere
Sterngriffschrauben, Fluidkopf) aus dem Speicher.

## 3. Was neu gerechnet wird, nötig oder nicht

`laufrolle_l` 100 → 90 ändert 20 von 134 Teilen (gemessen über Formschlüssel und Lage je Körper), auf beiden Seiten, weil
die Rollenlänge die Höhe beider Querstangen (`quer_z`) und die Lage der Schlitten bestimmt:

- 6 mit neuer Form: Fangrolle, Schieberolle, Fängerschlitten links und rechts, Schieberschlitten links und rechts.
- 14 nur verschoben: Querstange vorn und hinten, je vier Gewindeeinsätze, Scheiben und Sterngriffschrauben an den
  Schlitten.

| Stufe | neu gerechnet | zwangsläufig | vermeidbar |
|---|---|---|---|
| Durchdringung | 52 von 314 Paaren | alle 52: Form oder relative Lage geändert; der Schlüssel ist schon Form ohne Lage plus relative Lage (`kollision._rel_schluessel`) | nichts |
| Druck | 6 von 16 Druckteilen | alle 6 (Form neu) | nichts |
| Montage | 256 Sperrtests, Planung ganz | die Sperrtests (gleicher Schlüssel wie Durchdringung) | Planungsschleife 0,75–0,85 s, wenn alle Antworten gleich bleiben |
| Statik S0/S1 | alle 4 Szenarien | ja: Querstangen sind Stäbe und verschieben sich, Massen ändern sich, S1 koppelt alle Szenarien | nichts nennenswert: 32 von 46 Schnittaufrufen kommen aus dem Speicher; alle 14 neuen gehören zu den 6 formgeänderten Teilen |
| FEM | 20 von 20 Fällen | 8 Fälle: Schieberschlitten links und rechts (je 3), Fangrolle, Schieberolle | 12 Fälle der vier Stangenhalter: Geometrie, Lager, Werkstoff gleich, nur die Lagerkraft aus S1 ändert sich (etwa −4,77 → −4,72 N); 6 bis 9 s |
| Bewegungsraum | 8 von 18 Wegen, 877 exakte Schnitte | Wege ja (Teile darin geändert oder verschoben) | 206 Schnitte von Paaren, die gemeinsam verschoben wurden (Schraube, Einsatz, Scheibe); rund 1 s |

Je Szenario (FEM): „Bremsen“ 6 Fälle (4 Stangenhalter vermeidbar, 2 Schieberschlitten nötig); „Ball drückt 100 N auf
den Schieber“ 7 Fälle (4 vermeidbar, Schieberschlitten und Schieberolle nötig); „Ball drückt 100 N auf den Fänger“ 7
Fälle (4 vermeidbar, Schieberschlitten und Fangrolle nötig); „Eigengewicht“ ohne FEM (keine Last). Die Fängerschlitten
sind nicht unter den 8 FEM-Teilen (`MAX_TEILE_AUTO`, Auswahl nach Auslastung in S0).

Zur Annahme im Auftrag („das Statik-Gedächtnis schlüsselt über das ganze Modell“): stimmt, kostet hier aber nur rund
0,7 s über die nötigen Schnitte hinaus, und auch die wären nötig, weil das geänderte Stabwerk alle Szenarien betrifft. Ein
Gedächtnis je Szenario brächte bei dieser Änderung nichts.

## 4. Weitere Befunde

1. **Gmsh-Netze sind nicht reproduzierbar** (HXT, `General.NumThreads` 4): Derselbe Stangenhalter mit demselben Schlüssel
   bekam in vier frischen Sitzungen 4457, 4459, 4478 und 4471 Tetraeder; die Sicherheit desselben Falls lag bei 0,367 bis
   0,374. Innerhalb einer Sitzung hält der Netzspeicher sie fest. „Gleich wie volle Neuberechnung“ heißt für die FEM
   deshalb: gleich bei denselben Netzen.
2. **Netzspeicher nach Weltschlüssel** (`prozess._netz`, Schlüssel `schluessel_teil` = Weltschlüssel): Ein nur
   verschobenes Teil wird neu vernetzt (0,1 bis 1,8 s) und bekommt ein anderes Zufallsnetz, sein Ergebnis springt um bis
   zu 1 %, ohne dass sich die Geometrie geändert hat.
3. **Lösergrenze mitten in den Teilen:** `LU_KLEIN` = 25.000 freie Freiheitsgrade; die Stangenhalter haben 25.464 bis
   25.800 Freiheitsgrade, ohne die gelagerten rund 25.000 (gemessen 24.990). Je nach Zufallsnetz löst SuperLU (0,7–1,0 s)
   oder AMG (3,9–4,1 s) denselben Halter.
4. **Schnittspeicher der Statik** (`bauteil._SPEICHER`) wird bei 256 Einträgen ganz geleert; kalt 22 Einträge, je
   Änderung 14 dazu: Nach etwa 17 Änderungen rechnet die nächste wieder alle Schnitte (rund 2,3 s mehr).
5. **OCP gibt die GIL nicht frei** (40 Schnittmengen in 4 Threads: Faktor 0,99), OCCT `SetRunParallel` bringt bei kleinen
   Schnitten 5 %. Parallele exakte Geometrie braucht eigene Prozesse.
6. Der Rechenprozess nimmt EXEC nur zwischen zwei Aufträgen an; während `pruefe` unterbrechen nur RUN und QUIT. Ein
   FEM-Auftrag mitten in der Hauptprüfung würde bis zu ihrem Ende warten.

## 5. Grundsätze für alle Schritte

- Jeder Zwischenspeicher hat einen Schlüssel aus allen Eingaben seines Ergebnisses; Invalidierung heißt neuer Schlüssel,
  nie ausdrückliches Löschen. Vorbild ist `kollision.PaarCache`: Form ohne Lage plus relative Lage, Ergebnis im System
  des ersten Teils.
- Jeder Schritt bekommt einen A/B-Test: inkrementell (warme Speicher) gegen volle Neuberechnung (frischer Prozess,
  dieselben FEM-Netze). Bitgleich, wo dieselben Rechnungen laufen; wo nur die Rundung abweicht (Überlagerung), eine feste
  Schranke (1e-10 relativ) und gleiche gerundete Ausgaben.
- Parallel nur in Prozessen und nach Speicher begrenzt (16 GB; gemessen 0,8 bis 1,5 GB Spitze je FEM-Prozess mit LU).
- Die Bedeutung des Endstands bleibt: `pruefen(endstand=True)` wartet weiter auf alles.
- Nur Kernel (Python); keine Änderung an App, PROTOCOL.md oder Spiegel. Mac und iPad sind gleich betroffen, weil beide
  den Kernel am Mac nutzen.

## 6. Plan

Reihenfolge nach Wirkung je Aufwand. Zeiten unter Last um 20; auf einem ruhigen Mac vermutlich 20 bis 30 % weniger
(nicht gemessen).

### A0 Messwerkzeug (0,5 Tage)

`benchmark/pruefzeit.py` um die Zeitleiste (Ereignisse aus Laufzeit, Rechenprozess, FEM-Prozess) und eine
**Gleichheitsprobe** erweitern: nach jedem Schritt das Endstand-Ergebnis (Befunde, Statik je Szenario samt Festkörper je
Teil, Montage, Bewegungen) gegen einen frischen Rechenprozess mit leeren Speichern, aber demselben FEM-Netzspeicher
vergleichen. Grundlage für jeden folgenden Schritt.

### A1 FEM direkt nach der Statik starten (1 Tag)

- **Was:** Prüfreihenfolge `erklaerungen, durchdringung, bedingungen, stand, druck, statik, druckvorschau, gedruckt,
  montage, bewegungsraum`. Direkt nach der Statik schreibt der Rechenprozess den FEM-Auftrag selbst
  (`statik/dienst.festkoerper_schreiben`, Auswahl wie `festkoerper/laufzeit._kandidaten`, dafür in ein gemeinsames Modul)
  und schickt einen zweiten Zwischenstand (`teilweise`, offen „Montage“, „Bewegungsraum“) mit Statik und Auftragspfad; die
  Laufzeit startet den FEM-Prozess sofort, ohne EXEC.
- **Ersparnis:** FEM-Start 1,6 bis 1,9 s früher (Montage, Druckvorschau, gedruckt, Bewegungsraum im Budget), am Endstand
  ebenso viel, solange die FEM den Endstand bestimmt.
- **Schlüssel:** keine neuen. Abhängigkeiten geprüft: Die Statik liest aus der Prüfung nur `stand`, `druck` und die
  Paare (`statik/anbindung.py` Zeile 279 und 300); die Montage liest nichts aus der Statik.
- **Risiken:** doppelter FEM-Start (der erste CHECK mit Statik startet, `_statik_check` gibt beim zweiten CHECK desselben
  Laufs schon heute `None`); Versionen und `gedruckt` reagieren auf jedes CHECK_DONE und müssen das vertragen.
- **Tests:** Befunde, Montage und Statik in alter und neuer Reihenfolge gleich (Kugelschieber, Testmodelle aus
  `test_pruefung_stand_montage.py`, `test_statik.py`); genau ein FEM-Auftrag je Lauf; ein neuer Lauf während der Montage
  bricht die FEM ab wie heute.

### A2 FEM-Teile parallel (1 bis 1,5 Tage)

- **Was:** Die Teile eines Auftrags auf N Prozesse verteilen (Vorgabe 3, bei Speicherdruck 2 bzw. 1), längste zuerst
  (Schätzung aus den Zeiten des letzten Laufs, sonst Freiheitsgrade). Jeder Prozess bekommt `OMP_NUM_THREADS` 1 bis 2.
  Fortschritt je Prozess zusammenführen; Abbruch beendet alle Prozessgruppen.
- **Ersparnis gemessen:** 8 Teile 18,5 s → 9,2 s mit 4 Prozessen (gleiche Netze, Last 20); einzelne Teile werden dabei
  bis zu doppelt so langsam (Speicherbandbreite, Fremdlast).
- **Ergebnis:** bitgleich (jedes Teil unabhängig, derselbe Code).
- **Risiken:** Speicher: Spitze 0,8 GB (25.000 Freiheitsgrade, LU) bis 1,5 GB (35.000) je Prozess, mit 3 Prozessen bis
  4,5 GB. Der Verteiler reserviert nach Schätzung (gemessen rund 42 kB je Freiheitsgrad) und liest den Speicherdruck
  (`kern.memorystatus_level`).
- **Tests:** nacheinander gegen parallel bitgleich; `test_abbruch_beendet_den_prozess` für mehrere Prozesse;
  Verteiler mit gespieltem Speicher.

### A3 Direkte Zerlegung bis rund 45.000 Freiheitsgrade (0,5 Tage, Entscheidung Kevin)

- **Was:** `LU_KLEIN` von 25.000 auf etwa 45.000 (genauer Wert nach Messung von Zeit und Speicher bei 45.000 bis
  60.000); darüber AMG wie heute.
- **Ersparnis gemessen:** Schieberschlitten 5,1–5,3 s (AMG, 3 Lastfälle) → 2,3–2,5 s (SuperLU 1,5 s, die 3 Lösungen
  zusammen 0,04–0,06 s); 8 Teile nacheinander 18,5 → 12,5 s. Das zufällige Umschalten der Stangenhalter (0,7 gegen 4,1 s)
  entfällt.
- **Ergebnis:** In allen 20 Fällen gleiche Sicherheit (so gerundet, wie sie ausgegeben wird) und gleiche größte
  Verschiebung auf 5 Nachkommastellen; der Unterschied ist durch die CG-Toleranz 1e-7 begrenzt. Gegenüber heute ändert
  sich das Ergebnis innerhalb der Lösertoleranz; inkrementell und voll bleiben gleich. Die direkte Zerlegung ist genauer
  als AMG.
- **Risiko:** Speicher (Zerlegung 35.000 Freiheitsgrade 264 MB, Spitze 1,5 GB): Grenze nach Speicher statt nur nach
  Freiheitsgraden.
- **Tests:** vorhandene FEM-Tests (Kragbalken gegen Handrechnung, Lochplatte gegen Kerbfaktor) mit beiden Lösern; AMG
  gegen LU an einem Teil mit 30.000 Freiheitsgraden innerhalb 1e-6 relativ.

### A4 Einheitslastfälle je Teil, überlagert (2 Tage, Entscheidung Kevin)

- **Was:** Der FEM-Prozess speichert je Teilzustand die Lösungen für Einheitslasten auf der Platte und setzt neue Fälle
  daraus zusammen. Schlüssel: Netzschlüssel, Werkstoff und Schichtrichtung (Steifigkeit C), Lager (Nachbarformen, relative
  Lage, Toleranz, Art), Behandlung loser Stücke, Löser. Je Lastfläche 6 Einheitsfälle (Kraft in x, y, z am Schwerpunkt der
  Fläche, Moment um x, y, z; dieselbe RBE3-Verteilung wie `loeser.last_flaeche`, linear in Kraft und Moment, ein anderer
  Angriffspunkt P geht als Moment (P − c) × F ein), 3 für Volumenlasten (Eigengewicht, Last ohne Punkt), dazu die
  Einheits-Lagerkräfte. Spannung, Sicherheit und Lagerkräfte entstehen aus den überlagerten Feldern wie heute
  (`_bewerten`, `lagerkraefte`). Der bisherige Speicher je Fall (gleiche Last) bleibt die erste Stufe.
- **Anwendbar**, wenn die Lastflächen fest sind: Lasten über `kontakt_mit` (Lager eines Stabs, Verbinder; hier alle 12
  Fälle der Stangenhalter), Eigengewicht, Flächenlasten der Simulation. Eine Last mit freiem Punkt (`_lastflaeche(P)`) nur,
  wenn P gleich bleibt (P im Schlüssel).
- **Ersparnis gemessen:** unverändertes Teil 1,2 bis 2,1 s → rund 0,15 s (Kombination, Auswertung, Netz laden). Hier 4
  Stangenhalter: 6 bis 9 s nacheinander → etwa 0,6 s.
- **Ergebnis:** gleich bis auf Rundung (relativ etwa 1e-15 bei LU). Teile, die AMG löst, überlagern nur mit enger
  Toleranz der Einheitsfälle oder gar nicht (dann wie heute).
- **Speicher:** 9 × Freiheitsgrade × 8 Byte, rund 2 MB je Teilzustand auf der Platte.
- **Alternative:** ein dauerhafter FEM-Prozess, der die Zerlegung im Speicher hält: bitgleich, aber 144 MB (25.000
  Freiheitsgrade) bis 264 MB (35.000) je Teil im Speicher, und der Abbruch darf den Prozess nicht mehr beenden. Auf dem
  16-GB-MacBook nicht empfohlen.
- **Tests:** Überlagerung gegen direkte Lösung für jede Lastart (Kontaktlast mit Moment, anderer Angriffspunkt,
  Eigengewicht in drei Richtungen, Flächenlast, Druck) innerhalb 1e-10 relativ, gerundete Ausgaben gleich; Fehltreffer bei
  geändertem Lager, Werkstoff, Schicht, Netz, Kontaktfläche (parametrisiert wie `test_tempo_pruefung.py`).

### A5 Netz nach Form, reproduzierbar (1 Tag, Entscheidung Kevin)

- **Was:** Netzschlüssel aus Formschlüssel (ohne Lage), `h`, `fein`, Verfeinerung; Netz in Teilkoordinaten gespeichert
  und mit der Lage des Teils verschoben. Dazu, nach Messung von Zeit und Netzqualität: reproduzierbare Vernetzung (Gmsh mit
  einem Faden oder Algorithmus 1).
- **Ersparnis:** Nur verschobene Teile werden nicht neu vernetzt (0,1 bis 1,8 s je Teil), ihre Ergebnisse springen nicht
  mehr um bis zu 1 %. Voraussetzung dafür, dass A4 bei verschobenen Teilen trifft.
- **Tests:** verschobenes Teil gleiche Sicherheit, Felder verschoben; dieselbe BREP zweimal vernetzt gleich (falls
  reproduzierbar gewählt).

### A6 Geänderte FEM-Teile vorziehen (1,5 Tage, nach A4)

- **Was:** Direkt nach dem Zwischenstand (Kontakte bekannt) rechnet der FEM-Prozess für Teile mit neuer Form, die im
  letzten FEM-Auftrag waren, schon Netz, Steifigkeit, Kontaktflächen und Einheitsfälle (A4) mit den Lagern des letzten
  Laufs. Das hängt nicht von den Lasten ab. Nach der Statik bleibt die Überlagerung.
- **Ersparnis:** Die FEM der geänderten Schlitten (2,4 bis 2,7 s mit LU) läuft parallel zu Druck und Statik; der
  Endstand liegt dann rund 0,3 s hinter der Statik.
- **Ergebnis:** unverändert; Vorziehen füllt nur Speicher mit vollständigen Schlüsseln. Brauchen die echten Fälle andere
  Lager oder Teile, wird normal gerechnet.
- **Tests:** Endstand mit und ohne Vorziehen gleich, auch wenn sich die Auswahl der FEM-Teile ändert.

### B1 Bewegungsraum: Schlüssel aus Form und relativer Lage (1 Tag)

- **Was:** Paarschlüssel in `anim_kollision.pruefe_kollisionen` (Bewegungsraum) aus Formschlüssel von a und b, Drehung
  von a und relativer Lage (Ruhelage mal Weg), Ergebnis relativ zur Lage von a (Hüllquader um die Verschiebung von a
  versetzt). Der Wegschlüssel nimmt ebenfalls Formen und relative Lagen statt Weltschlüssel; den Griffraum ebenso merken.
  Die Drehung von a gehört in den Schlüssel, weil Tiefe und Ort aus dem achsparallelen Hüllquader der Schnittmenge in
  Weltachsen kommen.
- **Ersparnis gemessen (Schattenzähler):** 877 → 671 exakte Schnitte nach dieser Änderung (−23 %, rund 1 s); kalt
  1603 → 1333 (−17 %), weil gleiche Unterbaugruppen (vier Lenkrollen, vier Sterngriffschrauben) nur einmal rechnen; beim
  Verschieben ganzer Baugruppen fast alles.
- **Tests:** Bewegungen und Befunde mit altem und neuem Schlüssel gleich (Kugelschieber, `test_bedingungen*.py`);
  verschobene Baugruppe ohne neue Schnitte; gedrehte Baugruppe ohne falsche Treffer.

### B2 Prozesse für exakte Geometrie (3 Tage)

- **Was:** 2 bis 3 Rechenprozesse mit eigenem Formspeicher (BREP je Formschlüssel einmal übertragen), die auf Anfrage
  Schnittmengen (Bewegungsraum, Durchdringung) und Statik-Schnitte rechnen. Die Ergebnisspeicher bleiben im Rechenprozess,
  die Schlüssel ändern sich nicht. Bei Absturz eines Helfers rechnet der Rechenprozess selbst.
- **Ersparnis:** Bewegungsraum 3,4 s exakte Schnitte → rund 1,2 s (3 Prozesse), Statik-Schnitte 2,1–2,6 s → rund 0,9 s,
  Durchdringung 0,5 → 0,2 s.
- **Risiken:** Lebenszyklus, Abbruch, Speicher je Helfer (Formen klein); Übertragung einige Millisekunden je Form.
- **Tests:** Helfer gegen Rechenprozess bitgleich, Abbruch, Absturz mit Rückfall.

### B3 Bewegungsraum gleichzeitig mit Statik und Montage (1 Tag, nach B2)

- **Was:** Den Bewegungsraum direkt nach dem Zwischenstand in den Helfern starten; er hängt nur am Stand der Bedingungen
  und an den Formen, nicht an Druck, Statik oder Montage. Sein Ergebnis kommt in den Endstand wie heute.
- **Ersparnis:** 3,9 bis 4,5 s (nach B1 und B2 rund 1,5 s) fallen aus der Kette des Rechenprozesses.

### B4 Montageplanung beschleunigen (1,5 Tage)

- **Was:** Die Planungsschleife (0,75–0,85 s, je Änderung ganz) beschleunigen: Vorfilter in `Planer.kandidaten`,
  `frei` und `sperrt` über alle Partner auf einmal (numpy) statt Teil für Teil. Wiederverwenden des alten Plans nur mit
  einem Schlüssel über alle Eingaben des Planers außer den Sperrantworten (Hüllquader, Projektionen, Prioritäten, Kontakte,
  Boden); das ist fehleranfällig und kommt erst nach der Beschleunigung in Frage.
- **Ersparnis:** geschätzt 0,4 bis 0,6 s.
- **Tests:** Plan gleich wie bisher für Kugelschieber und Testmodelle.

### B5 Statik, kleine Punkte (0,5 Tage)

- `bauteil._SPEICHER` als LRU statt Leeren bei 256 Einträgen.
- Schnittschlüssel relativ zur Teillage (Form, R und P im Teilsystem): Treffer für verschobene Teile (bei dieser Änderung
  ohne Wirkung, bei Verschiebungen ganzer Baugruppen groß). Dafür Schnitte immer im Teilsystem rechnen, damit voll und
  inkrementell gleich bleiben.
- Inventar-Vorschläge (0,24 s) erst nach dem Absenden des FEM-Auftrags (A1).
- Kein Statik-Gedächtnis je Szenario (gemessen ohne Nutzen).

## 7. Erwartete Zeit bis zum Endstand

Aus den gemessenen Teilzeiten zusammengesetzt, Last um 20:

| Ausbau | Endstand | kritischer Pfad |
|---|---|---|
| heute | 26,5–34 s (Median 32,8) | FEM, 8 Teile nacheinander, Start nach der Hauptprüfung |
| A1–A4 | etwa 11,5 s | Bewegungsraum im Rechenprozess (Montage endet bei 7,4 s, dann 4,2 s Bewegungsraum); FEM endet bei etwa 9,5 s |
| + B1–B3 | etwa 9,5 s | Statik (bis 5,7 s), dann FEM der geänderten Schlitten (3,3 s mit Gegenlast) |
| + B2 für Statik-Schnitte, B4 | etwa 8 s | FEM der geänderten Schlitten nach der Statik |
| + A6 | etwa 6 s (ruhig vermutlich 4,5 s) | Lauf 2 s, Zwischenstand, Druck, Statik, Montage |

Unter 5 s also nur mit allen Schritten und ohne Fremdlast. A1 bis A4 allein bringen den Faktor 3 bei geringem Risiko.
Der Lauf selbst (model.py 1,6–2,0 s) bleibt der Sockel. Eine schnellere Zerlegung (CHOLMOD aus SuiteSparse oder Apple
Accelerate über ein kleines Hilfsmodul) könnte die FEM geänderter Teile weiter senken; das ist eine neue Abhängigkeit und
nicht gemessen.

## 8. Entscheidungen für Kevin

1. **A3:** direkte Zerlegung statt AMG bis etwa 45.000 Freiheitsgrade. Ergebnisse ändern sich gegenüber heute innerhalb
   der Lösertoleranz (gemessen: in allen 20 Fällen dieselbe ausgegebene Sicherheit).
2. **A4:** Überlagerung von Einheitslastfällen (gleich bis auf Rundung, rund 2 MB je Teil auf der Platte) statt gehaltener
   Zerlegung (bitgleich, 150 bis 260 MB Speicher je Teil).
3. **A5:** reproduzierbare Netze. Heute schwanken FEM-Ergebnisse desselben Modells zwischen Sitzungen um etwa 1 %.
4. **Parallelität:** bis zu 3 FEM-Prozesse und 3 Geometrie-Prozesse auf dem MacBook (Spitze 4 bis 5 GB), nach Speicher
   gedrosselt.
5. **Schnellere Zerlegung** mit neuer Abhängigkeit (optional, nach A1 bis A4).

**Kevins Entscheidungen (07.11.2026):** A3 und A5 ja („Beides“), A4 als Überlagerung, Parallelität bis 3 FEM- und 3
Geometrie-Prozesse nach Speicher gedrosselt, Umfang zuerst A0 bis A4, danach messen und über den Rest entscheiden. A5 ist
freigegeben, kommt aber erst nach A0 bis A4. Die schnellere Zerlegung mit neuer Abhängigkeit (Punkt 5) ist offen.

## 9. Umsetzungsreihenfolge

A0 → A3 → A1 → A2 → A4 → B1 → A5 → B2 → B3 → A6 → B4 → B5. Je Schritt ein Commit nach Gleichheitsprobe und Tests, auf
`main` wie üblich nur Geprüftes.

## 10. Umsetzung

Messungen am Kugelschieber (Kopie, `benchmark/pruefzeit.py`), Schritte kalt, `laufrolle_l=90`, dieselbe Änderung, zurück
auf die Datei, `laufrolle_l=95`. „Endstand“ ist die Zeit ab Beginn von `run(params=…)` bis `pruefen(endstand=True)`
zurückkommt. Rohdaten unter `/Volumes/UPVIS ULTRA/_cache/kevcad-pruefzeit/` (Ordner je Messung).

### A0 Messwerkzeug (07.11.2026)

- `benchmark/pruefzeit.py`: Zeitleiste je Schritt (Ankunft jedes CHECK aus dem Rechenprozess mit Zustand und offenen
  Prüfungen, FEM-Auftrag, FEM-Prozess und je Teil Beginn und Ende, Endstand), Systemlast und freier Speicher vorher und
  nachher, Speicherspitze des FEM-Prozesses. Dafür meldet der FEM-Prozess `beginn`, `zeiten_teile` und `speicher_mb` im
  Ergebnis (sonst unverändert). Alle Ablagen samt TMPDIR auf UPVIS ULTRA.
- Gleichheitsprobe `--probe` (`benchmark/pruefzeit_analyse/gleichheit.py`): Nach jedem Schritt rechnet ein frischer Kernel
  in eigenem Prozess (leere Speicher) denselben Stand (Kopie des Projekts vor dem Schritt) mit denselben Parametern bis zum
  Endstand und teilt nur die FEM-Netze. Verglichen werden Befunde, Schnittkörper (SHA-1 der Nutzlast), Montage, Stand,
  Druck, Gewinde, Bedingungen, die volle Statik je Szenario samt Festkörper je Teil (genau) und die FEM-Felder (float32,
  relativ zum größten Betrag 1e-6). Ungleich: Ausgang 1. `--netze-von` und `--vergleich` vergleichen zwei Stände des
  Kernels mit denselben Netzen, `--nachvergleich` wertet eine Ablage neu.
- Basis (Stand `12d6294`, Ablage `20261107-063751-a0-basis`, Last 9 bis 22, 52 bis 72 % Speicher frei):

| Schritt | Endstand | FEM-Prozess | FEM-Spitze |
|---|---|---|---|
| kalt | 48,6 s | 22,7 → 48,5 s | 1,3 GB |
| `laufrolle_l=90` | 33,2 s | 7,0 → 33,1 s (8 Teile nacheinander) | 1,5 GB |
| dieselbe Änderung | 2,7 s | aus dem Zwischenspeicher | – |
| zurück auf die Datei | 1,9 s | aus dem Zwischenspeicher | – |
| `laufrolle_l=95` | 32,4 s | 7,4 → 32,3 s | 1,8 GB |

- Probe der Basis: in allen Schritten gleich bis auf drei Schwankungen, die schon zwischen zwei frischen Prozessen
  auftreten, also nichts mit Zwischenspeichern zu tun haben. Sie stehen im Ergebnis getrennt unter `bekannt` und lassen
  die Probe nicht scheitern:
  1. **Knicken (S1)**: `statik/stabwerk.py` `_knicken` ruft `eigsh` ohne festen Startvektor, mit sigma 1e-3 weit unter
     den Eigenwerten (alle transformierten Eigenwerte liegen dicht bei 1). Die kleinste Knicklast schwankt von Prozess zu
     Prozess: 2.594,9 gegen 2.637,4, nach der Änderung 1.191 gegen 846, dazu der Stab, dem sie zugeordnet wird. Nicht Teil
     von A0 bis A4; Frage an Kevin.
  2. **Rutschen (S0)**: `statik/s0.py` `rutschen` entscheidet einen Gleichstand gleicher Räder nach der Reihenfolge einer
     Menge (Hash-Zufall je Prozess): „Lenkrolle 3“ gegen „Lenkrolle 1“, gleiche Werte. Nicht Teil von A0 bis A4.
  3. **AMG**: pyamg schätzt den Spektralradius mit einem Zufallsvektor (`np.random`); Residuen und Felder der AMG-Teile
     weichen bis 9e-8 relativ ab, die gerundeten Ausgaben nicht. In A3 behoben (fester Startwert).

### A3 Direkte Zerlegung bis 45.000 Freiheitsgrade (07.11.2026)

- `statik/festkoerper/loeser.py`: SuperLU bis 25.000 freie Freiheitsgrade immer, bis 45.000, wenn nach der geschätzten
  Zerlegung noch 1 GB Arbeitsspeicher frei bleibt (`lu_erlaubt`, `lu_bedarf_mb`: obere Hülle der gemessenen Einträge von
  L und U, n · (700 + 0,01 n) zu je 12 Byte, mal 1,5), dünne Teile wie bisher bis 150.000; sonst AMG wie heute.
  `KEVCAD_FEM_LOESER=lu|amg` erzwingt einen Löser (Tests, Messungen). AMG bekommt einen festen Startwert der
  Zufallszahlen (pyamg schätzt den Spektralradius mit `np.random`): AMG-Teile sind damit von Prozess zu Prozess gleich.
- Messung der Grenze (`benchmark/pruefzeit_analyse/lu_grenze.py`, Stangenhalter und Schieberschlitten mit verkleinerter
  Netzgröße, je Löser ein frischer Prozess, 3 Lastfälle, Last 13 bis 22):

| Freiheitsgrade | SuperLU gesamt (Zerlegung) | AMG gesamt | Spitze SuperLU / AMG | Einträge L+U |
|---|---|---|---|---|
| 25.600 | 1,8 s (1,0) | 4,2 s | 0,80 / 0,65 GB | 17,7 Mio. |
| 39.700 (Schlitten) | 2,6 s (1,5) | 5,1 s | 1,06 / 0,89 GB | 26,0 Mio. |
| 43.000 | 3,2 s (2,1) | 6,2 s | 1,27 / 1,05 GB | 33,8 Mio. |
| 48.500 | 4,4 s (3,3) | 7,1 s | 1,45 / 1,16 GB | 44,1 Mio. |
| 54.900 | 10,5 s (8,9) | 7,3 s | 1,37 / 1,30 GB | 66,8 Mio. |
| 55.100 (Schlitten) | 7,2 s (5,6) | 7,0 s | 1,61 / 1,26 GB | 55,7 Mio. |
| 68.100 | 10,4 s (8,8) | 13,4 s | 1,98 / 1,33 GB | 81,2 Mio. |

  Bis rund 50.000 ist SuperLU immer schneller, darüber schwankt die Zerlegung mit der Ordnung stark. Jeder weitere
  Lastfall kostet SuperLU 0,01 bis 0,03 s, AMG 0,7 bis 1,3 s (70 bis 120 Iterationen). In allen Größen dieselbe
  Sicherheit (gerundet); Verschiebungen AMG gegen SuperLU höchstens 8,6e-8 relativ.
- Kugelschieber (Ablage `20261107-065637-a3`, mit den Netzen der Basis, Last 12 bis 26): Endstand nach
  `laufrolle_l=90` **20,0 s** (Basis 33,2 s), nach `laufrolle_l=95` **19,4 s** (32,4 s); FEM-Prozess 7,3 → 19,9 s
  (12,6 statt 26 s), alle 8 Teile mit SuperLU (Stangenhalter 1,0 bis 2,0 s, Schieberschlitten 2,0 bis 2,4 s statt 4,1 bis
  6,4 s). Speicherspitze des FEM-Prozesses 2,1 GB (Basis 1,5 bis 1,8 GB). Kalt 36,8 s (ohne Vernetzen, Netze der Basis).
- Gleichheitsprobe: in allen Schritten gleich, FEM-Felder genau gleich (vorher bis 9e-8). Gegen die Basis mit denselben
  Netzen: in allen 20 Fällen gleiche Sicherheit, Spannung, Verformung und Orte; anders sind nur Verfahren, Iterationen und
  Residuum des Lösers, die Felder um höchstens 9,8e-8 relativ (Toleranz von AMG).
- Tests: Kragbalken und Lochplatte mit beiden Lösern, AMG gegen SuperLU an einem Klotz mit rund 30.000
  Freiheitsgraden innerhalb 1e-6, Löserwahl nach Größe und Speicher, AMG Bit für Bit reproduzierbar. Mac mini: 1278
  bestanden, 23 übersprungen.

### A1 FEM direkt nach der Statik (07.11.2026)

- Reihenfolge der Prüfungen jetzt `erklaerungen, durchdringung, bedingungen, stand, druck, statik, druckvorschau,
  gedruckt, montage, bewegungsraum` (`pruefung/lauf.py` `REIHENFOLGE`). Direkt nach der Statik schreibt der Rechenprozess
  den FEM-Auftrag selbst (`statik/festkoerper/auftrag.nach_statik`: dieselbe Auswahl `kandidaten`, die bisher in der
  Laufzeit stand und jetzt von beiden benutzt wird, derselbe Wunsch wie über EXEC) und schickt einen zweiten
  Zwischenstand (`teilweise`, offen Montage und Bewegungsraum, mit Druck und Statik). Das Feld `festkoerper_auftrag` geht
  nur vom Rechenprozess zur Laufzeit; die Laufzeit nimmt es heraus, startet den FEM-Prozess sofort, ohne EXEC
  (`runtime._nach_statik`), und schickt das CHECK wie jedes andere `teilweise` an die App.
- Nur mit Stufen (`KEVCAD_PRUEF_STUFEN`), nicht für Läufe der Versionen. Passt die Auswahl der Laufzeit nicht zum
  Auftrag oder scheitert das Schreiben, gilt der bisherige Weg (EXEC nach dem Endstand). Genau ein FEM-Auftrag je Lauf;
  ein neuer Lauf bricht die FEM ab wie bisher (mit seiner Statik). Abläufe (S2) werden mit dem Zwischenstand markiert
  (zählen als offen), starten aber wie die Topologie erst mit dem CHECK nach der Montage: Beide schicken EXEC, das der
  Rechenprozess erst nach der Prüfung annimmt und das bis dahin einen neuen Lauf aufhielte. Ein abgebrochener oder
  gescheiterter Lauf startet sie nicht; ein CHECK eines Schattenlaufs der Versionen dazwischen ändert nichts.
- Messung (Ablage `20261107-070509-a1`, Netze der Basis, Last 5 bis 16): Endstand nach `laufrolle_l=90` **16,0 s**,
  nach `laufrolle_l=95` 16,8 s (A3: 20,0 und 19,4 s, aber bei Last 12 bis 26). Lastunabhängig an der Zeitleiste: Der
  FEM-Prozess startet bei 5,2 s, 1,6 s vor dem Ende der Hauptprüfung (6,8 s); in A3 startete er erst nach ihr (7,3 s).
  Kalt 32,1 s; dort ist die FEM jetzt vor dem Bewegungsraum fertig (29,6 gegen 32,1 s).
- Gleichheitsprobe in allen Schritten gleich; Vergleich mit A3 (alte Reihenfolge, Auftrag über EXEC) mit denselben
  Netzen in allen Schritten genau gleich (Befunde, Montage, Statik samt Festkörper, Felder).
- Tests: `test_pruefung_inkrementell.py` (alte gegen neue Reihenfolge an HALTER, STANGE, ECKE, TURM und drei kleinen
  Stand- und Montagefällen; Zwischenstand mit Auftrag im Rechenprozess, keiner ohne Last oder ohne Stufen; Laufzeit:
  FEM aus dem Auftrag genau einmal ohne EXEC, Abbruch durch den nächsten Lauf, Ablauf erst mit dem CHECK nach der
  Montage, nicht nach Abbruch, Schattenlauf dazwischen, Auftrag eines überholten Laufs verworfen). In
  `test_tempo_pruefung.py` die Reihenfolge der offenen Prüfungen nachgezogen (Druck, Statik, Montage). Mac mini, dritter
  Lauf: 1288 bestanden, 23 übersprungen. In den ersten beiden Läufen je ein einzelner Ausreißer, beide nicht wieder
  aufgetreten und lokal (auch fünfmal einzeln) nicht nachstellbar: `test_simulation2::test_gleitendes_lager_schraeg_im_
  stabwerk` (Statikmodell eines früheren Tests noch in `LETZTER`) und `test_festkoerper::test_laufzeit_hintergrund_
  festigkeit_und_feld` (Festkörper binnen 120 s nicht fertig, passt zum schon bekannten sporadischen Absturz des
  FEM-Prozesses). Der zweite Test nennt bei einem Zeitlimit jetzt den Stand und die Meldung des FEM-Prozesses.

### A2 FEM-Teile parallel (07.11.2026)

- `statik/festkoerper/prozess.py`: Der FEM-Prozess verteilt die Teile eines Auftrags, die nicht ganz aus dem
  Zwischenspeicher kommen, auf bis zu 3 Teilprozesse (Pool mit `spawn`, je 2 Fäden), längste zuerst (Zeit des letzten
  Laufs je Teilstand bzw. Teilname aus `zeiten.json` im FEM-Zwischenspeicher, sonst nach Volumen). Zahl nach
  Speicherdruck (`kern.memorystatus_vm_pressure_level` Warnung oder unter 25 % frei: 2, kritisch oder unter 12 %: 1, dann
  nacheinander im FEM-Prozess wie bisher), ein weiteres Teil nur, wenn nach `kern.memorystatus_level` frei ist, was es
  nach Schätzung braucht (150 MB plus 32 kB je Freiheitsgrad), plus 1,5 GB Reserve, abzüglich dessen, was die laufenden
  noch belegen werden. `KEVCAD_FEM_PROZESSE` erzwingt eine Zahl (Tests, Messungen). Fortschritt meldet der FEM-Prozess je
  fertigem Teil; die Teilprozesse sind in seiner Prozessgruppe (der Abbruch der Laufzeit beendet alle) und beenden sich
  selbst, wenn er stirbt. Stürzt der Pool ab, rechnet der FEM-Prozess den Rest selbst.
- Ergebnis gleich: Jedes Teil rechnet dieselbe Funktion. Gemessen ist das Ergebnis eines Teils mit 1, 2 und 4 Fäden Bit
  für Bit gleich (Schieberschlitten, 39.700 Freiheitsgrade, SuperLU, je 2,1 bis 2,6 s), und der gesicherte
  Kugelschieber-Auftrag (8 Teile) nacheinander und mit 3 Prozessen: gleiche Fälle in gleicher Reihenfolge, Ergebnisse und
  Felder bitgleich.
- Dazu behoben: Die Laufzeit setzt die Befunde nach dem Festkörper neu zusammen (`_statik_in_check`) und kannte die Texte
  der Arten von Druck und Bedingungen nur, wenn deren Module zufällig schon geladen waren; je nach Zeitfolge stand dann
  „12 druck_einsatz_sackloch“ statt „12 Gewindeeinsätze im Sackloch (Druck)“ in der Zusammenfassung. Jetzt lädt sie die
  Texte immer.
- Messung (Ablage `20261107-073958-a2`, Netze der Basis, Last 11 bis 21, 32 bis 53 % frei): Endstand nach
  `laufrolle_l=90` **12,8 s** (A1: 16,0 s): FEM-Prozess 5,6 → 12,8 s mit 3 Prozessen (A1: 10,8 s nacheinander); die Teile
  selbst brauchen parallel länger (Schieberschlitten 3,3 bis 3,8 s statt 1,8 bis 2,1 s), Speicher je Teilprozess höchstens
  0,84 GB. Nach `laufrolle_l=95` 16,7 s bei Last 17 bis 21 (Hauptprüfung und jedes Teil 1,5- bis 2-mal so lang wie in
  Schritt 1). Gleichheitsprobe in allen Schritten gleich; gegen A1 mit denselben Netzen gleich bis auf den Text der
  Zusammenfassung (siehe oben).
- Tests: nacheinander gegen 3 Prozesse bitgleich (drei Klötze, gleiche Netze), Verteiler mit gespieltem Speicher,
  Abbruch beendet alle Teilprozesse. Mac mini: 1291 bestanden, 23 übersprungen.
