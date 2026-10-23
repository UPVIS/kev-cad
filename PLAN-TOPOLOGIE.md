# Kev CAD · Topologieoptimierung für Druckteile

Stand: 23.10.2026 (Kevins Wunsch: „so wie in diesem Reel“, gemeint ist implicit.build; Zweig `topologie`).

## Ziel

Aus einem Druckteil wird eine organische Fachwerkform entlang der Lastpfade: „Fix the bolts. Load the pin. … The holes
stay solid. Keep 42 %. Remove the rest.“ Wie im Reel in vier Schritten, nur dass Kev CAD Lager und Lasten schon kennt:

1. **Lager und Lasten** aus dem Statikmodell bzw. einem Szenario (wie der Festkörper, Stufe 3): Kontaktflächen zu den
   tragenden Nachbarn, `st.last` am Teil, Kraftpaare, Lagerkräfte der Stäbe, Kräfte der Stäbe auf Verbinder.
2. **Simulieren:** Festkörper-FEM des Ausgangsteils (von Mises, Verschiebung, Sicherheit gegen das Ziel).
3. **Schutzzonen:** Bohrungen mit Wandring über die ganze Tiefe, Gewindeeinsätze mit Mindestwand, Last- und
   Klemmflächen, auf Wunsch die Bettfläche, dazu Formen und Flächen aus model.py.
4. **Material optimieren:** SIMP auf einem Voxelgitter in Drucklage, „behalten“ (Standard 0,4), auf Wunsch ohne neue
   Überhänge über 45°; daraus eine glatte Oberfläche und ein druckbarer Körper, nachgerechnet mit Festkörper-FEM und
   Druckprüfung, Kennzahlen vorher und nachher. Hinweis immer dabei: Näherung, kein Festigkeitsnachweis.

**Fertig, wenn:** klassischer Kragträger und MBB-Balken ergeben die bekannte Fachwerkform mit genauem Volumenanteil;
ein Winkelhalter wie im Reel spart etwa die Hälfte bei grüner Sicherheit; ein Stangenhalter des Kugelschiebers lässt
sich im Szenario „Ball drückt 100 N“ optimieren; 50 000 bis 200 000 Voxel in unter einer Minute; ein normaler Lauf
wartet nie darauf.

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| O1 | **Eigener Prozess** (`python -m kevcad_kernel.topologie.prozess`), wie der Festkörper: Der Rechenprozess schreibt nur den Auftrag (Teil als BREP, Nachbarnetze, Lastfall aus `festkoerper.auftrag.faelle`), die Laufzeit startet den Prozess, liest den Fortschritt (JSON-Zeilen) und beendet ihn auf Abbruch. Immer nur einer zugleich; ein neuer Lauf bricht ihn nicht ab (das Ergebnis gilt je Modellschlüssel, nicht je Lauf) | model.py und die Prüfung bleiben ungestört, Gmsh (GPL) nur im eigenen Prozess, der Lauf wartet nie |
| O2 | **SIMP auf Voxeln in Drucklage:** Gitter über dem Hüllquader in Druckkoordinaten (z = Aufbaurichtung aus der Druckprüfung, unten bündig mit dem Bett), Kante aus der Voxelzahl (60 000, `fein` 180 000 im Teil, dünne Wände feiner bis dreimal so viele), Element im Bauraum, wenn seine Mitte im Teil liegt (Strahlparität). Ziel kleinste Nachgiebigkeit, p = 3, E_min = 1e-6, OC-Schritt 0,2 mit Bisektion auf das linearisierte Volumen, Dichtefilter als Kegel mit r = max(1,5 h, Steg), Ende bei < 0,01 Änderung über drei oder < 0,2 % Nachgiebigkeit über fünf Schritte (mindestens 20–25, höchstens 60) | Das Standardverfahren der Literatur, robust und schnell; Drucklage, damit Schichtrichtung und Überhangfilter am Gitter ausgerichtet sind |
| O3 | **Löser:** H8-Elemente mit 6×6-Steifigkeit der Statik (quer zur Schicht weicher wie S3), geometrisches Mehrgitter mit **elementweiser Galerkin-Vergröberung** (je grobem Element Σ P_cᵀ K_kind P_c mit acht festen Matrizen, auf Ebene 1 ein Matrixprodukt), Lager als Masken (grober Knoten fest, sobald ein feiner in seinem Einfluss fest ist: dann ist die maskierte Galerkin-Rechnung genau), **Chebyshev-Glätter vom Grad 2 auf l1-Jacobi**, gröbste Ebene SuperLU, CG mit Warmstart, Toleranz 1e-2 in den ersten fünf, danach 3e-3. Feinste Ebene matrixfrei über die aktiven Elemente, Produkte in einfacher Genauigkeit | pyamg müsste die Matrix jeden Schritt neu aufbauen; gedämpftes Jacobi divergiert bei 1e-6 neben 1 (λ_max(D⁻¹A) = 4,2), l1-Jacobi nicht; Chebyshev halbiert die CG-Schritte; 3e-3 ändert die Dichte am Kragträger um < 1e-4 bei 40 % weniger CG |
| O4 | **Überhangfilter** (Langelaar 2017) Schicht für Schicht: gedruckt = smin(Entwurf, smax des Kreuzes aus fünf Elementen darunter), P = 40; die unterste Schicht liegt auf dem Bett; Elemente, die schon im Ausgangsteil frei hängen, gelten als gestützt; Ableitungen adjungiert (gegen Differenzenquotient geprüft) | 45° entlang der Achsen, diagonal strenger (sicher für den P1P); keine neuen Überhänge, alte bleiben, wie sie waren |
| O5 | **Schutzzonen von selbst:** zylindrische Bohrungen (Wand außen, zusammen ≥ 300° Umfang, sonst Rundung) mit Ring max(Steg, 0,6 r); Sacklöcher mit Einsatzmaß (Tabelle der Druckregeln) mit 1,5 × Mindestwand; Lastflächen und Klemmflächen (Klemmung, Steck, Formschluss, Kleben, Gelenk mit Bereich) mit einer Haut max(Steg, 1,5 h); Bettfläche nur auf Wunsch (`bett=True`, Haut in Stegdicke). Mindeststeg 6 × 0,42 mm | „The holes stay solid“; eine geschlossene Bodenhaut verhinderte die Fenster durch die Grundplatte (Reel) und war dünner als ein Steg; die Unterseite bleibt ohnehin eben auf dem Bett |
| O6 | **Oberfläche:** Schwelle so, dass das Volumen auf dem feinen Gitter genau „behalten“ trifft; **ein Körper aus einem Stück**: es bleibt, was mit der Last zusammenhängt, abseits liegende Schutzzonen (Schraubenauge, das die Optimierung nicht braucht, weil die Auflage trägt) bekommen auf kürzestem Weg einen Steg in Stegdicke, lose Inseln ohne Schutz fallen weg; Feld max(Abstand zum Teil, (Schwelle − Dichte) · 2 r) auf einem halb so großen Gitter; **Marching Cubes** mit aus den Würfelflächen erzeugten Fällen (mehrdeutige Fläche trennt die inneren Ecken; Nachbarn entscheiden gleich, das Netz ist geschlossen und mannigfaltig, geprüft an Rauschen); Taubin-Glättung nur der neuen Schnittflächen; Quadrik-Ausdünnung auf 6 000 (fein 12 000) Dreiecke mit **fast-simplification** (0,4 MB, MIT), nur wenn mannigfaltig | Flächen des Ausgangsteils bleiben eben und Bohrungen rund (Abstandsfeld), nur die Schnitte werden organisch; wenige Dreiecke halten Viewer, Prüfung und Export schnell |
| O7 | **Körper als B-Rep aus dem Netz** (`BRepBuilderAPI_MakeShapeOnMesh`, eine ebene Fläche je Dreieck, geschlossene Schale, Volumenkörper; Millisekunden, gültig, Volumen genau) in Teilkoordinaten, **Bohrungen danach genau nachgeschnitten** (Boolesche Differenz mit den Zylindern des Ausgangsteils, 2 mm über die Enden), damit Schrauben und Gewindeeinsätze wieder passen (sonst Durchdringung und „Befestigung fehlt“ an den Facetten), binär gespeichert unter `topologie/<teil>-<schlüssel>.brep` mit `.json` (Kennzahlen, Lastfall). Kein eigenes „Netzteil“ | Stückliste, Prüfung, Druckvorschau, Export und Festkörper verstehen ihn ohne Sonderweg |
| O8 | **Druckprüfung schnell halten:** waagrechte Unterseiten über dem Bett werden in flache Pyramiden geteilt (3°, Versatz ≈ 5 % des Inkreises ins Material), Punkte am Bett genau aufs Bett gesetzt | Die Druckprüfung klassifiziert Decken mit OCCT-Punkten; bei Tausenden Dreiecksflächen dauerte das 156 s für vier Decken, Überhänge rechnet sie am Netz in Millisekunden. Ohne Bett-Punkt hielt sie die ganze Unterseite für schwebend |
| O9 | **Nachrechnen** mit den Bausteinen des Festkörpers (Netz, Steifigkeit P2, Werkstoff, Bewertung): vorher aus der BREP, nachher aus dem Oberflächennetz (Gmsh vernetzt das Volumen mit genau diesen Dreiecken als Rand), Lager wie dort, Lastflächen nachher auf den Dreiecken über der Lastfläche des Ausgangsteils; SuperLU direkt. Dazu Druckprüfung des Ergebnisses, Filament und Zeit vorher und nachher (Schätzung der Druckvorschau, Einstellungen „tragend“), dünnster Steg | Gleiche Lager und Lasten wie die Statik, damit vorher und nachher vergleichbar sind; Fachwerke aus Stegen lassen AMG nicht konvergieren |
| O10 | **model.py:** `topologie.optimieren(teil, szenario, behalten, …)` gibt das Ergebnis zurück, sobald es zum **Modellschlüssel** (Form ohne Lage, Szenario, Einstellungen, Schutzformen) im Projekt liegt, sonst das Teil; der Aufruf wird in `.kevcad/topologie/aufrufe/` vermerkt (mit der Form des Ausgangsteils), die Laufzeit rechnet fehlende Ergebnisse nach dem Lauf im Hintergrund und startet danach den Lauf neu. Das Stück der Stückliste folgt dem neuen Körper (Masse, Preis, Zuordnung) | Kein minutenlanger Lauf; Ergebnisse gehören zu den Versionen; Optimieren von einem schon optimierten Stand nimmt immer das Ausgangsteil als Bauraum |
| O11 | **Übernehmen als Variante:** neue Variante (Versionen), in model.py hinter `x = lager.druckteil(…, "Name", …)` die Zeile `x = topologie.optimieren(x, …)` (AST, mit Import), Lauf. Ohne einfache Zuweisung meldet Kev CAD die Zeile zum Eintragen | Kevin entscheidet, welche Variante bleibt |
| O12 | **App:** Inspektor, Abschnitt „Optimieren“ beim ausgewählten Druckteil (Schieber „Behalten“, Lastfall, Überhänge, fein, Start/Abbruch, Fortschritt, Kennzahlen vorher → nachher, Ansicht Dichte/Vorher/Nachher/Aus, Schutzzonen, „Als Variante übernehmen“); Viewer: Dichte halbdurchsichtig über dem blassen Teil, Vorher/Nachher als Bänder der Ausnutzung (wie STATICS_FIELD), Teil darunter ausgeblendet | Wie im Reel: man sieht das Material schwinden; eine Farbsprache mit der Statik |
| O13 | **Lager wählbar** (`lager`): `"kontakt"` (Vorgabe) wie die Statik, die Kontaktflächen zu den tragenden Nachbarn; `"bohrungen"`: die Wände der Bohrungen ohne Last sind fest („Fix the bolts“), sonst nichts. Nachgerechnet wird immer mit den Lagern der Statik | Liegt ein angeschraubter Halter auf einer Platte, trägt die Auflage alles und die Optimierung lässt die Schraubenaugen liegen; mit den Schrauben als Lager entstehen die Arme zu den Schrauben wie im Reel |

## Umsetzung

- Kernel `kevcad_kernel/topologie/` (Übersicht im Docstring von `__init__.py`): `mehrgitter`, `simp`, `raster`,
  `oberflaeche`, `nachrechnen`, `ergebnis`, `auftrag`, `dienst`, `prozess`, `laufzeit`; API `kevcad.topologie`
  (`optimieren`, `aus_datei`); MCP `topologie_optimieren` (mit `abbrechen`), `topologie_ergebnis`,
  `topologie_uebernehmen` (`mcp_tools/topologie_tools.py`).
- Protokoll additiv: `TOPO`, `TOPO_FIELD`, `TOPO_START`, `TOPO_CANCEL`, `TOPO_APPLY` (PROTOCOL.md „Topologie“),
  Testdateien aus `kernel/tools/make_topologie_fixtures.py`.
- App: `KevCADCore/Topologie/` (Nachrichten, Store, Viewer), Ebene `topologie` im `SceneStore`,
  `Sources/KevCAD/Topologie/TopologieAbschnitt.swift`.
- Skill: `skill/kev-cad/statik.md`, Abschnitt „Topologie optimieren“; SKILL.md Überblick und API-Zeile.

## Nachweise

Gemessen am 23.10.2026 auf dem MacBook (M2 Pro, 16 GB), PETG aus dem Katalog, Mindeststeg 2,5 mm.

**Klassische Formen** (`kernel/tests/test_topologie.py`): Kragträger 48 × 12 × 16 Voxel, links eingespannt, 30 %
behalten: Ober- und Untergurt an der Einspannung, Mitte und erstes Feld leer (Fachwerk), Volumen 30,0 %, Nachgiebigkeit
unter 25 % der ersten Iteration. Halber MBB-Balken 60 × 20 (eben), 50 %: Druckgurt oben, Zuggurt unten, Diagonalen mit
Löchern dazwischen. Tempo am Kragträger 2 : 1 : 1 (alle konvergiert, Volumen genau 30,00 %):

| Voxel | Zeit | Iterationen | je Iteration | CG-Schritte gesamt | Ebenen |
|---|---|---|---|---|---|
| 49 152 | 9,6 s | 40 | 0,24 s | 148 | 3 |
| 102 400 | 20,1 s | 40 | 0,50 s | 192 | 4 |
| 199 680 | 37,6 s | 38 | 0,99 s | 177 | 4 |

**Winkelhalter wie im Reel** (Grundplatte 80 × 50 × 8 mit vier Schraubenlöchern Ø 5,5, Steg 40 × 10 × 60 mit
Bolzenloch Ø 12; vier Schrauben halten, Bolzen zieht mit (0, 15, 50) N; behalten 42 %, 60 000 Voxel, h = 0,95 mm):

| | vorher | nachher |
|---|---|---|
| Volumen | 50,9 cm³ | 21,3 cm³ (−58 %) |
| Masse | 64,7 g | 27,1 g |
| Filament (tragend) | 34,1 g | 20,6 g |
| Druckzeit | 83 min | 70 min |
| größte Spannung | 2,45 N/mm² | 3,64 N/mm² |
| Sicherheit (Ziel 4) | 10,8 grün | 4,6 grün |
| Verformung | 0,20 mm | 0,26 mm |

34 s gesamt: Aufbau 0,4 s, Ausgangsteil nachrechnen 1,8 s, Optimieren 22,8 s (25 Iterationen, konvergiert, 0,91 s
je Iteration), Oberfläche 2,2 s, Körper 1,3 s, Ergebnis nachrechnen 2,1 s, Druckprüfung und Schätzung 3,3 s. Fünf
Schutzzonen an den Bohrungen, alle fünf genau nachgeschnitten, Netz geschlossen (6 000 Dreiecke). Rest der
Druckprüfung: kleine Überhänge (3–6 mm²) und die waagrechte Bolzenbohrung (Tropfenform empfohlen).

**Derselbe Halter auf einer Platte** (Lager in der Statik = Kontakt zur Platte):

| | `lager="kontakt"` | `lager="bohrungen"` |
|---|---|---|
| Volumen | −58,6 % | −58,1 % |
| Sicherheit vorher → nachher | 27,9 → 22,2 grün | 27,8 → 8,9 grün |
| Form | Steg auf der Platte, die zwei hinteren Schraubenaugen über Streben angebunden (Weg im Bauraum) | Arme vom Steg zu allen vier Schrauben (wie im Reel) |
| Zeit | 26 s | 36 s |

**Im Kev-CAD-Projekt** (Halter mit Platte und Schrauben als Kulisse, `topologie.optimieren(halter, szenario="Bolzen
50 N", behalten=0.42)` in model.py): Lauf 1 in 1,6 s mit dem Ausgangsteil und der Meldung „wird im Hintergrund
optimiert“, Optimierung 24 s im eigenen Prozess (Dichte als TOPO_FIELD live), danach Lauf 2 von selbst mit dem neuen
Körper: Volumen −60 % (50,9 → 20,4 cm³), Filament 34,1 → 18,5 g, Druckzeit 83 → 68 min, Sicherheit 13,4 → 7,2 grün;
Stückliste und Masse folgen dem neuen Körper. In der Testvariante „Kev CAD Test to“ über MCP gestartet: die Dichte
erscheint halbdurchsichtig über dem blassen Teil, danach die Bänder der Ausnutzung am Ergebnis (Fensterbilder mit
`screencapture -l`).

**Kugelschieber, Kopie** (Stangenhalter vorn links, Szenario „Ball drückt 100 N auf den Fänger“, behalten 40 %, aus
model.py): Lauf 1 32,6 s, Optimierung im Hintergrund etwa 2 min (dünnwandig, h aus der Wandstärke, 62 CG-Schritte je
Lösung), Lauf 2 35,4 s. Volumen −60 % (70,6 → 28,5 cm³), Filament 46,9 → 28,4 g, Druckzeit 104 → 91 min. Nach dem
Nachschneiden der Bohrungen keine Durchdringung mit den Gewindeeinsätzen und keine fehlende Befestigung mehr (vorher 2
und 2; Durchdringungsprüfung 2,4 s statt 18,7 s). Ehrlich: Schon das Ausgangsteil ist in der Festkörper-FEM rot
(Sicherheit 0,30 gegen Ziel 4, Spannungsspitze 75 N/mm² an der Klemmkante), nachher 0,44 (Spitze 37 N/mm², weil die
Steifigkeit umverteilt), und Stufe 2 (Kragträger aus dem Querschnitt) meldet das optimierte Teil als „hält nicht“
(0,6, vorher „hält knapp“ 2,1). Das Teil ist in diesem Lastfall kein Kandidat zum Sparen; das Ergebnis sagt das jetzt
selbst („Schon das Ausgangsteil erreicht das Ziel nicht …“). Rest der Druckprüfung: elf Überhänge (ohne
`ueberhang=True` gerechnet) und eine 1 mm² kleine freie Unterseite.

## Grenzen und offen

- Optimiert wird die Steifigkeit, nicht die Spannung: An scharfen Innenecken steigt die Spannung oft stärker, als das
  Volumen sinkt (Winkelhalter: Sicherheit −46 % bei Volumen −60 %). Abhilfe heute: mehr behalten oder ausrunden;
  später eine Spannungsnebenbedingung (p-Norm) oder ein Rundungsfilter an den Lagern.
- Eigengewicht beim Optimieren vernachlässigt (im Nachrechnen enthalten); Lasten ohne Angriffspunkt landen auf den
  Schutzzonen.
- Der Körper besteht aus ebenen Dreiecksflächen: Bohrungen sind genau nachgeschnitten, die übrigen Flächen des
  Ausgangsteils so genau wie das Netz (halbe Voxelkante); der Viewer glättet die Normalen und zeichnet nur scharfe
  Kanten. Echte Freiformflächen (NURBS) fehlen.
- Druckteile werden mit voller Füllung gerechnet; gedruckt mit Wänden und Füllung trägt das Ergebnis weniger.
- Überhangfilter nur entlang der Achsen streng 45°; die Druckprüfung nennt die Rest-Überhänge. Brücken und Decken
  erkennt die Optimierung nicht als druckbar.
- Ein geänderter Lastfall unter gleichem Szenarionamen bleibt beim gespeicherten Ergebnis, bis `neu=True` oder ein
  neuer Name; die Laufzeit meldet die Änderung nur, wenn sie aus model.py neu rechnet.
- Mehrere Szenarien zugleich (Summe der Nachgiebigkeiten) sind im Prozess vorbereitet, aber über model.py und MCP
  nur ein Szenario wählbar.
