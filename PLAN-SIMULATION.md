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
  Pfeil steht sofort; Verteilung am Punkt oder auf der ganzen Fläche; Richtung Normale, Achse oder frei (Winkel oder
  der Griff am Pfeilende: weiße Kugel frei drehen, blauer Ring nur Azimut, grüner Ring nur Höhe, rastet auf Achsen und
  die Normale ein, ⌘ beim Ziehen ohne), Betrag N, kg oder (ganze Fläche) N/mm², Kraftpaar mit einem anderen Teil;
  „Übernehmen“. Liste mit Auswählen, Ändern (Stift), Löschen, Zustand nach der Zuordnung. Schalter „Pfeile
  bildschirmfest“.
- **Lager**: Art, auf Fläche oder Punkt, gleitend „in der Fläche“, „entlang X/Y/Z“, „entlang einer Kante“ (anklicken)
  oder „frei“, „Gilt für“ alle Lastfälle, nur den gewählten oder eine Auswahl; „Lager setzen“ (⌃⌘L) und anklicken;
  Liste mit Lastfällen je Lager (Menü), Löschen und Art im Kontextmenü. Lager, die im gewählten Lastfall nicht gelten,
  stehen blass im Viewer.
- **Rechnen**: Rechnen (S0, S1; ⌃⌘R), Festigkeit (FEM) für ein Teil oder alle mit Last, Ablauf, Grenze suchen (wie
  viel Last, wie steil, wie schnell; Verfahren S0 und S1 oder mit FEM); Fortschritt mit Abbrechen, Ergebnis der Grenze
  darunter mit dem Verfahren je Wert, dem maßgebenden und der Probe.
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

## Ausbau: offene Grenzen geschlossen (Zweig `simulation2`, 23.10.2026)

Kevin: „auch die offenen Grenzen bauen“. Alle zehn Punkte aus dem Bericht des ersten Strangs sind umgesetzt, additiv in
simulation.json, SIM, SIM_RUN, SIM_JOB und STATICS (PROTOCOL.md „Simulation“), `st.lager`, `st.szenario` und MCP.

| Nr. | Entscheidung | Begründung |
|---|---|---|
| M13 | **Lager je Lastfall:** `szenarien` am Lager (null = alle, Namen = nur diese, `[]` = in keinem); in model.py `st.lager(…, szenario="A")` bzw. Liste. Die Statik baut **je Menge gültiger Lager ein eigenes Statikmodell** (`anbindung.modelle_bauen`) und rechnet je Gruppe (`rechne_gruppen`), zusammengeführt zu einem Ergebnis; ohne Lager je Lastfall genau ein Modell wie bisher. `LETZTER.modell_fuer(name)` gibt Festkörper, Topologie, Grenze und Ablauf das Modell des Szenarios; STATICS trägt je Szenario `lager`. Umbenennen eines Lastfalls folgt, Löschen lässt das Lager „in keinem Lastfall“ (sichtbar, mit Hinweis) | Stabwerk und Bodenlager hängen am ganzen Modell (ein Gleichungssystem für alle Lastfälle), deshalb Modelle statt Filter; die Kosten sind ein Aufbau je Gruppe (Millisekunden) |
| M14 | **Gleitend in beliebiger Richtung:** `gleiten` fehlt = gleitet in der Fläche und hält **genau entlang der Normale** (nicht mehr gerundet); `{art: "richtung", richtung}` = Schiene, frei nur entlang der Richtung, quer dazu in beide Richtungen gehalten; in der App „in der Fläche“, „entlang X, Y, Z“, „entlang einer Kante“ (anklicken) oder „frei“ (Winkel); in model.py `gleiten="+x"`, Vektor, `Axis` oder Kante. Stabwerk: je gehaltene Richtung ein Pendelstab (nur Längskraft) zu einem festen Punkt, der Lagerknoten nur gegen Drehen gehalten; FEM: jeder Ort der Lagerfläche nur in den gehaltenen Richtungen (schräge Bedingungen) | Eine Bedingung u · h = 0 je Richtung ist das Lager selbst; der Pendelstab macht sie in PyNite exakt, ohne schiefe Lager zu brauchen |
| M15 | **Gelenkig auf einer Fläche in der FEM wie ein RBE3** mit festem Bezugspunkt: mittlere Verschiebung der Fläche null (∫ u dA = 0) und mittlere Drehung um die gehaltenen Achsen null (∫ (b × r) · u dA = 0, b = J⁻¹ t); die Fläche dreht frei um die übrigen Achsen und verformt sich selbst frei. Ebene (und Punkt mit Normale): Drehung um die Normale gehalten (wie im Stabwerk die Verdrehung um die Stabachse); Zylinder (Bolzen in einer Bohrung): nur um die Achse frei. Gelöst über u = T q (`loeser.Zwang`: schräge Bedingungen je Ort durch Drehung der drei Freiheitsgrade, Kopplungen über Haupt- und Nebenfreiheitsgrade mit QR und Pivotsuche), die Matrix bleibt symmetrisch positiv definit (SuperLU und pyamg wie bisher). Vorher prüft die FEM, ob alle sechs Starrkörperbewegungen gehalten sind, und nennt sonst, was frei ist | Ein Volumenmodell hat keine Drehfreiheitsgrade; ein Punktlager wäre singulär, weiche Randbedingungen hängen an einer frei gewählten Steifigkeit. Die Kopplung ist genau und stört die Spannung nur an der Lagerfläche selbst (gewertet wird dort wie bisher ab dem ersten Knoten daneben) |
| M16 | **Last auf der ganzen Fläche:** `verteilung: "flaeche"`, Betrag als Gesamtkraft (N, kg) oder Druck (`einheit: "N/mm2"`, nur senkrecht). S0, S1 und Kragträger nehmen sie im Schwerpunkt der Fläche (aus ihrem Netz), die FEM verteilt sie gleichmäßig (Kraft / Fläche) bzw. als Druck senkrecht auf jedes Randdreieck; die Randdreiecke findet sie über das Netz der B-Rep-Fläche (Abstand und Normale). Ein Druck auf einer gekrümmten Fläche hat als Resultierende die Summe über ihr Netz | Gleichmäßige Last ist der Normalfall bei Auflagen, Druck bei Flüssigkeit und Luft; im Viewer getönte Fläche mit kleinen Pfeilen |
| M17 | **Untergrund je Lastfall überall, wo er zählt:** S0 (Rutschen), Grenze „wie steil“, Ablauf (S2): die Szene bringt die Reibwerte der Bodenpaare zusätzlich je Untergrund der Lastfälle (`boden_mu_je`), der Ablauf nimmt die seines Lastfalls (Reibung am Boden, Rutschgrenze μ · g). Stabwerk und FEM kennen keine Reibung. In model.py `st.szenario(…, untergrund=)` | Eine Szene, viele Lastfälle; die Reibwerte kommen aus dem Katalog im Rechenprozess |
| M18 | **Grenze suchen mit der FEM** (`verfahren: "fem"` an SIM_RUN und MCP): Die FEM ist linear-elastisch, die Lasten aus S0 und S1 sind linear im Lastfaktor (bei der Neigung linear in 1, sin θ, cos θ). Gerechnet werden nur Grundfälle (λ = 1 und 2 bzw. θ = 0°, 30°, 60°), im Zwischenspeicher je Fall; der FEM-Prozess halbiert je Teil über ihre Überlagerung (Spannung je Knoten), eine **Probe** rechnet die FEM bei der gefundenen Grenze noch einmal richtig. Kippen, Rutschen, Stäbe und Teile ohne FEM sucht S0/S1 weiter; den Kragträger der FEM-Teile zeigt das Ergebnis zum Vergleich (`ersetzt`). Jeder Wert trägt sein Verfahren, das Ergebnis das maßgebende; Fortschritt und Abbruch wie bei der Festigkeit | Eine echte Halbierung mit je einer FEM-Rechnung bräuchte 15 bis 30 Prozessläufe; die Überlagerung ist für das lineare Modell genau dieselbe Halbierung, die Probe belegt es |
| M19 | **Pfeil-Griff frei im Raum** wie ein Rotations-Gizmo: weiße Kugel am Pfeilende als Trackball (Shoemake, schrittweise, über den Rand hinaus dreht sie auf die Rückseite), blauer Breitenkreis durch das Pfeilende (nur Azimut), grüner Meridian (nur Höhe); beide Ringe am Blickstrahl, stetig auch bei Blick von der Seite. **Einrasten** unter 6° auf ±X, ±Y, ±Z und ± Flächennormale (die Richtung wird dann „Achse“ bzw. „Normale“), ⌘ beim Ziehen schaltet es ab (`SimGriff`) | Freie Richtung in 3D ohne Winkelfelder; die Ringe für genaue Änderungen einer Komponente |
| M20 | **Vergleich nur gleicher Verfahren:** je Zeile die Werte je Verfahren (FEM-Teile tragen ihren Kragträger S0 mit); verglichen wird dasselbe Verfahren wie gezeigt, sonst ein gemeinsames (FEM vor S1 vor S0), sonst „nicht vergleichbar (FEM ↔ S0)“ ohne Prozentänderung; Spalte „Verfahren“ in der Vergleichstabelle | Sonst sah eine FEM-Sicherheit gegen einen Kragträger wie eine Verbesserung oder Verschlechterung aus |
| M21 | **Pfeile wahlweise bildschirmfest** (Schalter in Kräften und Ergebnissen, gemerkt): Pfeile, Lagersymbole, Griff und Ringe etwa 80 Punkte lang in der Tiefe ihres Angriffspunkts; bei Kamerabewegung neu gebaut, gedrosselt und nur bei merklicher Änderung | Beim Heranzoomen bleiben sie lesbar und verdecken das Teil nicht |
| M22 | **Untertitel der Fensterleiste** folgt der Lastfallwahl sofort: das Fenster beobachtet nur `simulation.$auswahl` (nicht den ganzen Store, sonst zeichnete jeder Griff-Zug das Fenster neu) | Der Untertitel blieb stehen, bis sich am AppModel etwas anderes änderte |

Nachweise (Kernel `kernel/tests/test_simulation2.py`, 11 Tests; Werkstoffe aus dem Katalog):

| Probe | Handrechnung | Kev CAD |
|---|---|---|
| Rohr 21,3 × 2, 1000 mm, links gelenkig, rechts gleitend auf einer um 30° geneigten Ebene, 200 N in der Mitte: R = (F + q L) / (2 cos α) senkrecht auf der Ebene, waagrecht R sin α links | rechts (−60,43; 0; 104,67) N, links (60,43; 0; 104,67) N | dieselben Werte (±0,05 N); bisher gerundet: 0 N waagrecht |
| dasselbe als Schiene entlang der Ebene (`gleiten` = Tangente) | wie oben | wie oben |
| Lager je Lastfall: Rohr links fest (alle), rechts gleitend nur in „Gestützt“, 20 N an der Spitze: Kragarm F L³ / (3 E I) + q L⁴ / (8 E I); gestützt R_B = F + 3 q L / 8 | 6,54 mm; 23,50 N | 6,54 mm; 23,50 N |
| FEM: Balken 200 × 20 × 20 PLA auf zwei gelenkigen Stirnflächen, 100 N gleichmäßig auf der ganzen Oberseite: w = 5 F L³ / (384 E I) + F L / (8 κ G A), θ = F L² / (24 E I), je Lager F / 2 | | unter 4 % bzw. 6 %, Lager 50 N; beidseitig fest etwa ein Fünftel |
| FEM: Würfel 40 mm, 30° gekippt, in einer Ecke aus drei gleitenden Lagern, Eigengewicht W: Kraft je Fläche nur senkrecht zu ihr, R_unten = W cos α, R_vorn = W sin α | 84,96 / 49,05 N | (42,48; 0; 73,58) und (−42,48; 0; 24,53) N, also genau; mit nur zwei Flächen: „verschiebbar in (0; 1; 0)“ |
| FEM: Würfel 20 mm, oben Druck 0,5 N/mm² | p · A = 200 N | Lagerkraft 200,0 N, Lastfläche 400 mm² |
| Modell bis FEM: Balken PETG mit `st.lager(…, art="gelenkig")` an beiden Stirnflächen, Druck 0,025 N/mm² auf der Oberseite aus der App | 100 N, je Lager 50 N | Last im Schwerpunkt, Fläche 4000 mm², Lager 50,5 N (mit Eigengewicht) |
| Untergrund je Lastfall: Wagen bremst auf Beton bzw. Eiche, Rutschgrenze μ · g | 6,08 / 2,45 m/s² | 6,08 / 2,45 m/s² |
| Grenze mit der FEM: Wandhalter PETG, 20 N; linear λ = S(1) / Ziel | 0,460 | 0,457 (Eigengewicht), Probe Ausnutzung 0,999; aus dem Zwischenspeicher 0,4 s statt 1,6 s |

KevCADCore (`Simulation2Tests.swift`, 8 Tests): neue Felder aus den Testdateien (Lager je Lastfall, Gleitrichtung,
Druck, Verfahren der Grenze), Druck und SIM_EDIT, Kante setzt Gleitrichtung und Lager je Lastfall im Entwurf,
Trackball folgt der Maus, Ringe und Einrasten, Griff mit Kugel, Ring und bildschirmfester Länge, Vergleich nur gleicher
Verfahren.

## Grenzen und offen

- Gleitende Lager halten bilateral (kein Abheben) und reibungsfrei; die Topologie rundet sie weiter auf die nächste
  Gitterachse und spannt gelenkige Lager ein (Hinweis dort).
- Das gelenkige Lager in der FEM hält die Fläche im Mittel (RBE3); Kontakt und Pressung eines echten Bolzens rechnet es
  nicht (das wäre CalculiX, Strang Statik Stufe 4). Zwei gelenkige Lager halten auch längs gegeneinander (wie zwei
  Bolzen); eine Querdehnung der Fläche erzeugt dann eine kleine Längskraft.
- Lager je Lastfall gelten im Stabwerk, in S0, im Bauteil-Nachweis, in der FEM, in der Grenze und im Ablauf (dort nur
  feste Lager, als befestigt); Szenarien auf Anfrage des Agenten (`szenario_rechnen`) rechnen mit den Lagern für alle.
- Grenze mit der FEM: für Last und Neigung; „wie schnell“ bleibt beim Ablauf (S2). Teile, die bei einem der Grundwerte
  keine Last tragen (etwa reine Neigung ohne Einzellast auf einem Druckteil), rechnet nur S0/S1.
- Last auf der ganzen Fläche: Druck nur senkrecht; die Lastfläche kommt aus dem Netz der B-Rep-Fläche (Toleranz
  0,35 mm), bei sehr feinen Flächen an Kanten kann ein Randdreieck fehlen.
