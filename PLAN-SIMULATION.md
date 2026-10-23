# Kev CAD · Bereich „Simulation“

Stand: 23.10.2026 (Kevins Freigabe: „Ja, so bauen“; Zweig `simulation`). Baut auf Statik Stufe 1 bis 3
(PLAN-STATIK.md, T1–T35) und der Topologieoptimierung (PLAN-TOPOLOGIE.md) auf.

## Ziel

Bisher legt nur der Agent Lastfälle, Lasten, Kraftpaare und Szenarien im Code an (`kevcad.statik`), und die App zeigt
nur Ergebnisse. Jetzt bekommt Kevin eine eigene Bedienoberfläche: Bereich „Simulation“ (⌘4) im Projektfenster mit
Lastfällen, Kräften und Lagern per Klick, Rechnen per Knopf, einer Ergebnistabelle und der Topologie. Was er anlegt,
liegt in `simulation.json` neben model.py, gehört zu jedem Lauf und zu den Versionen, und der Agent sieht und ändert
dieselben Daten.

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| M1 | **Eigene Projektdatei `simulation.json`** neben model.py, Vorbild `druck.json`: Lastfälle, Kräfte, Lager, ausgeschaltete abgeleitete Lager, Topologie-Einstellungen je Druckteil. Bei jedem Lauf lädt der Prüfer „statik“ sie zusätzlich zu den Szenarien aus model.py (`statik/anbindung.py`). Gleicher Name: **die App gewinnt**, mit Hinweis | Kevins Klicks ändern keinen Code; die Datei gehört zum Projekt und damit zu den Versionen (nicht ausgeschlossen in `versionen/git.py`); der Agent kann sie lesen und ändern, ohne model.py umzuschreiben |
| M2 | **Szenarien aus model.py sind im Bereich nur lesbar**, gekennzeichnet (Zeile, Standard); „Als Kopie bearbeiten“ legt daraus einen Lastfall der App an (Neigung, Beschleunigung, Fahrt, Stoß, Kräfte mit Punkt und Richtung) | Eine Quelle der Wahrheit je Lastfall; eine Kopie gleichen Namens ersetzt das Szenario aus model.py bewusst |
| M3 | **Änderungen als Operationen**, für App (`SIM_EDIT`) und Agent (MCP `simulation_aendern`) dieselben (`simulation/datei.py`): alles oder nichts, mit Zähler `stand`; eine Änderung auf veraltetem Stand wird abgelehnt | Agent und App können gleichzeitig arbeiten, ohne sich still zu überschreiben |
| M4 | **Vom Klick zur Kraft**: Ort aus dem Treffer im Viewer (Teil, Flächennummer, Weltpunkt auf dem Dreieck, Normale aus den Netznormalen), Richtung **entlang der Normale in die Fläche hinein** (umkehren zieht), entlang einer Weltachse oder frei (Azimut und Höhe, oder der **Pfeil-Griff** am Pfeilende im Viewer, gezogen in der Ebene senkrecht zur Blickrichtung), Betrag in N oder kg (× 9,81). Die Kraft rechnet der Kernel (`simulation/kraft.py`), die App spiegelt es für die Vorschau (`SimKraft`) | Normale aus dem Treffer statt aus der Flächenart: gilt auch auf Zylindern und Freiformflächen; der Kernel bleibt maßgebend, die Vorschau ist sofort da |
| M5 | **Robuste Zuordnung** (`simulation/zuordnung.py`): Bezug ist der Teilname und die Fläche (Nummer wie im Viewer plus Signatur wie `PART_UPSERT.faces[i]`). Passt die Fläche gleicher Nummer, bleibt alles (`ok`, der Punkt wandert mit einer verschobenen Fläche mit); sonst die ähnlichste Fläche gleichen Typs (Normale bzw. Achse bis 12°, Radius ±40 %, Mitte bis 30 % der Teilgröße): `neu`, „Fläche 12 → 15“; sonst **„nicht mehr zuordenbar“** (`fehlt`): zählt nicht mit, bleibt in Datei und App sichtbar (rot). Ein umbenanntes Teil wird über den letzten Namensteil gefunden | Modelländerungen dürfen Kevins Kräfte nicht still verschieben oder verlieren |
| M6 | **Lager gelten für alle Lastfälle** und kommen zu den abgeleiteten dazu: `st.lager(teil, flaeche=…, punkt=…, art=…)` in model.py, dieselben per Klick in der App. Arten: **fest**, **gelenkig**, **gleitend** (hält nur senkrecht zur Fläche, auf die nächste Weltachse gerundet); auf Fläche, Punkt (Umkreis 5 % der Teilgröße) oder ganzes Teil. Ein Teil mit ausdrücklichem Lager verliert sein abgeleitetes Bodenlager; abgeleitete Lager (`boden:<teil>`, `kontakt:<teil>|<nachbar>`) stehen in der App und lassen sich ausschalten | Wie Lager in einer Konstruktion; additiv zu den Kontakten, damit bestehende Modelle gleich rechnen |
| M7 | **Lager in allen Stufen**: Stabwerk (S1) bekommt ein Auflager am nächsten Achspunkt (gelenkig und gleitend über ein Gelenkglied, gleitend nur in Richtung der Normale gelagert), andere Teile werden geerdet; S0: gelagerte Gruppen kippen und rutschen nicht; Kragträger, Festkörper (S3) und Topologie halten das Teil an der **Lagerfläche als Nachbarnetz „Lager: A1“** (gleitend nur die Normalkomponente der Freiheitsgrade); nur gleitende Lager ohne Halt in allen Richtungen meldet die FEM als Fehler | Ein Weg für alle Stufen; die FEM kennt Nachbarnetze schon (T25), der Zwischenspeicher bekommt einen eigenen Schlüssel je Lagerfläche |
| M8 | **Nach jeder Änderung S0 und S1 sofort** mit dem Prüfstand des letzten Laufs (`anbindung.neu_mit_simulation`, ohne model.py, das Modell neu, weil Lager es ändern); fertige Abläufe und Festkörper eines unveränderten Szenarios bleiben, solange die Lager gleich sind. FEM und Ablauf rechnen auf Knopf (und nach dem nächsten Lauf wie bisher im Hintergrund) | Antwort in Millisekunden bis einer Sekunde; teure Stufen nur, wenn Kevin sie will |
| M9 | **Rechnen per Knopf** als Aufträge (`SIM_RUN`, MCP `simulation_rechnen`), immer einer zugleich, Stand als `SIM_JOB` mit Fortschritt (FEM und Ablauf aus STATICS) und Abbruch (FEM wie `STATICS_CANCEL`, der Ablauf-Prozess ist jetzt abbrechbar). **Grenze suchen**: Faktor auf die Kräfte bzw. Neigung per Einklammern und Halbieren mit S0/S1 (Ziel, Bruch, Kippen, Rutschen); Geschwindigkeit über den Ablauf mit Rollouts (S2) | Die bestehenden Wege (`szenario_rechnen`, `festigkeit`, `dynamik`, `dynamik_grenze`) bleiben die Rechenkerne |
| M10 | **Ein Viewport**: Der Bereich zeigt denselben 3D-Viewport mit eigener Seitenleiste (Lastfälle, model.py, Lager, abgeleitete Lager), eigenem Inspektor (Reiter Lastfall, Kräfte, Lager, Rechnen, Topologie) und der **Ergebnistabelle** statt der Schnellansichten. Kräfte (blau, Kraftpaar violett, Auswahl und Entwurf orange), Lager (Kegel, fest mit Platte, gleitend mit abgesetzter Platte), Lager- und Schutzflächen liegen als eigene Ebene in der Szene, nur solange der Bereich vorne ist | Klicks auf Flächen brauchen das Modell; Statik-Farbverlauf und Simulation teilen sich die Ansicht |
| M11 | **Ergebnistabelle** aus STATICS (`SimErgebnis.zeilen`): je Teil und Stab Nachweis (S0 Kragträger, S1 Stab, FEM, Ablauf), Kriterium, Sicherheit, Ziel, Ausnutzung, Verformung, Ampel; sortierbar, Filter gelb und rot bzw. nur rot; Klick wählt das Teil, passt ein und schaltet den Farbverlauf an. **Vergleich** mit einem anderen Lastfall oder dem **vorherigen Stand** desselben Lastfalls (die App merkt sich den letzten STATICS-Stand mit anderem Inhalt); Befunde mit Lösungsvorschlag daneben | Eine Datenquelle wie der Statik-Abschnitt; vorher/nachher ohne zweite Rechnung |
| M12 | **Topologie im Bereich**: Druckteil, Lastfall, Behalten, Überhang, Mindeststeg, feines Gitter, Schrauben halten; automatische Schutzzonen **je Art** an und aus (Bohrungen, Gewindeeinsätze, Last- und Klemmflächen, Bettfläche), eigene **Schutzflächen per Klick** (`TOPO_START` additiv: `bohrungen`, `einsaetze`, `kontakt`, `bett`, `steg`, `schutz`); Einstellungen in `simulation.json`. Start, Abbruch, Dichte live, vorher/nachher und „Als Variante übernehmen“ wie bisher; im Inspektor des 3D-Bereichs bleibt ein Verweis | Kevin sieht und wählt, was massiv bleibt; die Optimierung selbst bleibt unverändert |

## Bedienung

- **⌘4** oder der vierte Knopf oben links öffnet den Bereich. Links die Lastfälle der App (+ statisch bzw. dynamisch,
  Kopieren, Umbenennen, Löschen im Kontextmenü), darunter die Szenarien aus model.py (Schloss, Zeile; „Als Kopie
  bearbeiten“), die Lager und die abgeleiteten Lager mit Häkchen.
- **Lastfall**: Art (statisch, dynamisch), Beschreibung, Neigung mit Richtung, Beschleunigung, Untergrund, bei
  dynamischen die Fahrt (Geschwindigkeit, Bremsen abrupt, Anprall oder Verzögerung, Dauer, Animation als Antrieb,
  Angriffshöhe, Fahrtrichtung), Stoßfaktor, Ziel-Sicherheit und Durchbiegung; „Übernehmen“ (⌘↩) speichert und rechnet.
- **Kräfte**: „Kraft setzen“ (Werkzeugleiste, ⌃⌘K, Esc beendet), im Viewer eine Fläche oder einen Punkt anklicken, der
  Pfeil steht sofort; Richtung Normale, Achse oder frei (Winkel oder weißer Griff am Pfeilende), Betrag N oder kg,
  Kraftpaar mit einem anderen Teil; „Übernehmen“. Liste mit Auswählen, Ändern (Stift), Löschen, Zustand nach der
  Zuordnung.
- **Lager**: Art, auf Fläche oder Punkt, „Lager setzen“ (⌃⌘L) und anklicken; Liste mit Löschen und Art im Kontextmenü.
- **Rechnen**: Rechnen (S0, S1; ⌃⌘R), Festigkeit (FEM) für ein Teil oder alle mit Last, Ablauf, Grenze suchen (wie
  viel Last, wie steil, wie schnell); Fortschritt mit Abbrechen, Ergebnis der Grenze darunter.
- **Ergebnisse** unter dem Viewport: Tabelle, Filter, Vergleich, Farbverlauf und Verformung, Befunde.
- **Topologie**: Druckteil wählen, Einstellungen, Schutzzonen, „per Klick“ eigene Schutzflächen, Optimieren.

## Umsetzung

- Kernel `kevcad_kernel/simulation/`: `datei.py` (Format, Operationen), `kraft.py` (Klick → Kraft), `zuordnung.py`
  (Modelländerungen, Lager mit Lagerfläche), `grenze.py` (Last, Neigung), `laufzeit.py` (SIM, SIM_JOB, SIM_EDIT,
  SIM_RUN, SIM_CANCEL, MCP). API `kevcad.statik.lager`. Statik: `modell.baue(…, lager, aus)`, gleitende Auflager im
  Stabwerk, Lagerflächen in Kragträger, Festkörper (`feste_dofs(…, komponenten)`) und Topologie, Untergrund je
  Szenario in S0, Kennung je Last in STATICS.
- Protokoll additiv: `SIM`, `SIM_JOB`, `SIM_REQ`, `SIM_EDIT`, `SIM_RUN`, `SIM_CANCEL`; `TOPO_START` um Schutzzonen;
  `STATICS.lasten[].id`. Testdateien aus `tools/make_simulation_fixtures.py`.
- MCP: `simulation_liste`, `simulation_aendern`, `simulation_rechnen` (`mcp_tools/simulation_tools.py`).
- App: `KevCADCore/Simulation/` (Nachrichten, Store, Controller mit Klick, Griff, Körpern), Ebene `simulation` im
  `SceneStore`, Griff-Haken im Viewport; Oberfläche `Sources/KevCAD/Simulation/` (Seitenleiste, Inspektor, Kräfte,
  Rechnen, Topologie, Ergebnisse, Menü, Selbsttest `KEVCAD_SELFTEST=simulation`).

## Nachweise

Kernel (`kernel/tests/test_simulation.py`, 14 Tests):

| Probe | Handrechnung | Kev CAD |
|---|---|---|
| Rohr 21,3 × 2, 1000 mm frei im Raum, `st.lager` gelenkig links, gleitend rechts (Normale +z), 200 N in der Mitte: w = F L³ / (48 E I) + 5 q L⁴ / (384 E I) | 3,578 mm, je Lager 104,67 N | 3,578 mm, 104,67 N |
| dasselbe, 50 N längs des Rohrs: das gleitende Lager hält nicht längs | links −50 N, rechts 0 | −50,0 / 0,0 N |
| Lager aus der App (simulation.json), beidseitig fest: w = F L³ / (192 E I) + q L⁴ / (384 E I) | | unter 2 % |
| nur links fest (Kragarm), 20 N an der Spitze: w = F L³ / (3 E I) + q L⁴ / (8 E I) | 6,54 mm | 6,54 mm |
| Wandhalter PETG 80 × 20 × 8 ohne Wand, `st.lager` an der Stirnfläche, 20 N bei 78 mm, Schichtfuge q f / (M / W) | 1,86 | S0 1,98, FEM 1,84 bis 1,87 (Lagerfläche 160 mm²) |
| derselbe nur gleitend gelagert | – | FEM: „nur gleitende Lager“ |
| Grenze „wie viel Last“ am Rohr: Probe bei λ | Ausnutzung 1 | 1,00 ± 0,01 |
| Grenze „wie steil“: Klotz 40 × 40 × 200 kippt bei atan(20 / 100) | 11,31° | ± 0,3° |

Dazu: Klick → Kraft (Normale, Achse, frei, kg), Operationen und Datei (alles oder nichts, Stand), Kopie eines
Szenarios aus model.py, Laden und Zusammenführen (App gewinnt, Hinweis, Neu-Rechnen ohne Lauf), Zuordnung nach
Modelländerungen (Fläche verschoben: ok, Punkt wandert mit; Bohrung und Fase: neu zugeordnet; Kugel statt Quader:
nicht mehr zuordenbar; Teil in eine Gruppe verschoben: über den Namen gefunden), abgeleitetes Lager ausschalten,
Laufzeit (SIM_EDIT mit ACK, STATICS, SIM; veralteter Stand abgelehnt; SIM_RUN Grenze mit SIM_JOB; MCP-Sicht),
Testdateien aktuell, MCP-Werkzeuge. Die bisherigen Tests der Statik, des Festkörpers, der Topologie, der Dynamik, des
Protokolls und des MCP-Servers laufen unverändert durch.

KevCADCore (`SimulationTests.swift`, 7 Tests): SIM und SIM_JOB aus den Testdateien, Kraft wie im Kernel, Operationen und
Anfragen (SIM_EDIT, SIM_RUN, SIM_CANCEL, TOPO_START mit Schutzzonen), Ergebnistabelle und Vergleich, Controller (Klick
aus dem Pick-Puffer → Entwurf mit Normale am Treffer, Körper im Viewer, Griff, Lager- und Schutzfläche per Klick,
Bereich verlassen), freie Richtung, vorheriger Stand.

Selbsttest der Testvariante (`KEVCAD_SELFTEST=simulation`, 40 Prüfungen, ohne Maus): Winkelhalter PETG auf einem Tisch.
Lastfall anlegen, Kraft per Klick auf die Oberseite des Stegs (2 kg in die Fläche, 19,6 N), Richtung über den
Pfeil-Griff, Lager fest auf der Unterseite (ersetzt das abgeleitete Bodenlager), Rechnen, Tabelle mit Filter, Klick
zeigt das Teil, Grenze „wie viel Last“ (im letzten Lauf 3,97-fach, 78 N statt 20 N, begrenzt durch die
Ziel-Sicherheit; Bruch erst beim 7,9-fachen), Festigkeit (FEM in rund 3 s, Nachweis „FEM“ in der Tabelle), Vergleich
mit dem vorherigen Stand (doppelte Last: Sicherheit 20,2 → 7,93, −61 %), dynamischer Lastfall im Editor, Kopie von
„Bolzen 50 N“ aus model.py, Topologie mit einer Schutzfläche per Klick (Volumen −55 %, Ziel 4, „Schutzfläche 8“ unter
den Schutzzonen). Die Zahlen hängen von der gezogenen Richtung ab (der Griff dreht die Kraft in der Bildebene), sie
schwanken deshalb von Lauf zu Lauf; der Selbsttest prüft Plausibilität, nicht feste Werte.

## Grenzen und offen

- Lager gelten für alle Lastfälle; Lager nur in einem Lastfall gibt es nicht.
- Gleitende Lager halten nur in Richtung der nächsten Weltachse (schräge Flächen mit Hinweis); gelenkige Lager auf
  einer Fläche wirken in der FEM wie feste (ein Volumenmodell hat keine Drehfreiheitsgrade).
- Eine Kraft auf einer Fläche greift am angeklickten Punkt an und wird in der FEM wie bisher im Umkreis auf der Fläche
  verteilt (10 % der Teilgröße), nicht über die ganze Fläche.
- Der Untergrund je Lastfall gilt für S0 (Rutschen); der Ablauf nimmt den Untergrund des Modells.
- „Grenze suchen“ für Last und Neigung rechnet mit S0/S1, nicht mit der Festkörper-FEM.
- Der Pfeil-Griff dreht die Kraft in der Ebene senkrecht zur Blickrichtung; für genaue Winkel die Felder nehmen.
