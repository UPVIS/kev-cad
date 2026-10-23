# Kev CAD · Umsetzungsplan MVP

Stand: 21.10.2026. Grundlage ist die Recherche in [RECHERCHE.md](RECHERCHE.md). Die Annahmen über fremden Code
(build123d-mcp, OCCTSwiftViewport, ocp-tessellate) sind am Quellcode geprüft. **AP0 bis AP7 sind erledigt**: AP0 im
Abschnitt 12, die Abnahme und die offenen Punkte im Abschnitt 17.

## 1. Was das MVP kann

Das MVP ist fertig, wenn dieser Ablauf ohne Handarbeit funktioniert:

1. Kevin startet Kev CAD und legt das Projekt „Wandhalter“ an.
2. Er sagt Claude: „Bau mir einen Wandhalter für ein 42,4er-Rohr aus 5-mm-Alublech mit zwei M6-Löchern.“
3. Im Viewer erscheinen Grundplatte, Lasche und Bohrungen **nacheinander**, jedes Teil mit Namen und Farbe.
4. Kevin klickt eine Bohrung an und fragt „Wie weit ist die vom Rand weg?“. Claude liest die Auswahl, misst exakt und
   blendet das Maß im Viewer ein.
5. „Zoom auf die Lasche und zeig sie mir von der Seite.“ Die Kamera fährt hin, Claude bekommt ein Bild davon.
6. Export als STEP, STL und 3MF in den Projektordner.
7. Die Outdoorküche eines Kunden (75 Bauteile, rund 134.000 Dreiecke) öffnet, dreht sich flüssig, ein Teil lässt sich
   isolieren und aufschneiden.

Dazu kann Kevin auch ohne Claude: Projekte öffnen, Teile ein- und ausblenden, Flächen und Kanten anklicken und messen,
Ansichten wechseln, schneiden, exportieren.

## 2. Was bewusst noch nicht drin ist

Diese Punkte kommen nach dem MVP (Abschnitt 15), sind aber in der Architektur schon vorgesehen:

- Lagerteile-Katalog mit Stückliste, Zuschnitt, Gewicht und Kosten (im MVP nur Material mit Dichte und Farbe)
- Datenblätter und Zeichnungen als PDF mit Druck
- Renderings
- Bambu-Druck
- Versionsvergleich, Parameter-Schieberegler, STEP-Import

## 3. Architekturentscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| E1 | **Kernel ist build123d 0.13** (OCCT 8) in Python, als eigener kleiner Kernel-Server `kevcad-kernel` | Modelle schreiben build123d am zuverlässigsten, du nutzt es schon. build123d-mcp wird **nicht** geforkt: sein Live-Stream schickt nur Punkte und Dreiecke (keine Normalen, keine Flächen-IDs, keine Kanten), läuft nur in eine Richtung, seine interne Operationstabelle lässt sich von außen nicht erweitern, und 60 Werkzeuge sind zu viele. Übernommen werden seine Muster (Rechenprozess getrennt, Zeitlimit, Neustart) und bei Bedarf einzelne Dateien unter Apache-2.0 mit Herkunftsvermerk |
| E2 | **`model.py` im Projektordner ist die Quelle der Wahrheit** | Reproduzierbar, speicherbar, versionierbar. Claude ändert die Datei mit seinen normalen Werkzeugen. Ein warm gehaltener Python-Prozess führt sie schnell neu aus |
| E3 | **Live-Aufbau über `show()`** im Modellcode | Jeder `show()`-Aufruf schickt das Teil sofort in den Viewer, noch während das Skript läuft. Ein Teil mit gleichem Namen wird ersetzt, so sieht man es wachsen |
| E4 | **Tessellierung mit [ocp-tessellate](https://pypi.org/project/ocp-tessellate/)** (Apache-2.0, Version 3.6.3) | Der bewährte Tessellierer des OCP CAD Viewers: Dreiecke je Fläche, Kanten je Kante, Flächen- und Kantentypen, Instanzen, Zwischenspeicher. Hängt nicht an einer OCP-Version |
| E5 | **Eigenes Binärprotokoll über Unix-Socket**, in beide Richtungen | Puffer gehen ohne Umweg in Metal, Topologie reist mit. Rückkanal für Messanfragen der App und Viewer-Befehle des Agenten. Wird in `PROTOCOL.md` festgehalten |
| E6 | **Viewer ist [OCCTSwiftViewport](https://github.com/SecondMouseAU/OCCTSwiftViewport)** (Metal, LGPL-2.1, auf einen Commit festgenagelt) | Bringt mit: `ViewportBody` mit Flächen- und Kanten-IDs je Dreieck, Picking über GPU-ID-Puffer, Kanten, Schnittebenen, Messanzeigen, Standardansichten, `focusOn`, Offscreen-Bild als PNG. Ab macOS 15, SwiftPM, ohne OCCT-Abhängigkeit. **Durch AP0 bestätigt**, mit drei Auflagen (Abschnitt 12) |
| E7 | **Exakt messen im Kernel**, anzeigen in der App | OCCT (`BRepExtrema_DistShapeShape`, `GProp`) rechnet, wie bei ocp-viewer-core. Einfache Werte (Kantenlänge, Radius, Flächennormale) liefert der Kernel gleich beim Tessellieren mit, damit die App sie ohne Rückfrage anzeigt |
| E8 | **Referenzen wie `Lasche#f12`, `Lasche#e3`, `Lasche#v2`** | Teilname plus Index von Fläche, Kante oder Punkt. Gültig für einen Lauf (Laufnummer reist mit). Damit sprechen Kevin, App und Claude über dasselbe Element |
| E9 | **MCP sitzt im Kernel-Server** (offizielles Python-SDK `mcp` 2.3, Streamable HTTP auf 127.0.0.1). Die App startet und überwacht den Server. Eine kleine **stdio-Brücke `kevcad-mcp`** startet bei Bedarf die App und leitet weiter | Alle CAD-Werkzeuge leben in Python, wo OCCT ohnehin läuft. Die Brücke sorgt dafür, dass Claude Code die Werkzeuge auch dann hat, wenn die App beim Sitzungsstart noch zu war |
| E10 | **App-Build mit XcodeGen und `build.sh`** wie bei Easy Printer, Installation nach `~/Applications/Tools`, Testvariante mit eigener Bundle-ID | XcodeGen ist installiert und kommt mit Metal-Ressourcen und Signatur sauber klar. Kernel mit `uv` und Lockfile in eigener Umgebung, getrennt von `~/.venvs/cad` |

## 4. Aufbau

```
Claude Code / Claude Desktop
        │ MCP (stdio)
        ▼
  kevcad-mcp (Brücke) ── startet App, falls nötig
        │ HTTP 127.0.0.1
        ▼
┌──────────── Kernel-Server (Python, von der App gestartet) ────────────┐
│  MCP-Werkzeuge · Laufsteuerung · Referenzen · Messen · Export          │
│        │ Pipe                                                          │
│        ▼                                                               │
│  Rechenprozess (build123d, OCCT): führt model.py aus, show() →         │
│  tessellieren → Frame                                                  │
└────────┬───────────────────────────────────────────────────────────────┘
         │ Unix-Socket: Teile live, Messanfragen, Viewer-Befehle, Bilder
         ▼
┌──────────── Kev CAD.app (SwiftUI) ────────────────────────────────────┐
│  Teilebaum │ Viewport (Metal) │ Inspektor │ Statusleiste               │
└────────────────────────────────────────────────────────────────────────┘
```

**Ablauf eines Laufs:**

1. Claude ändert `model.py` und ruft `run` auf, oder die App bemerkt die gespeicherte Datei (Auto-Lauf, 300 ms entprellt).
   Läuft für denselben Dateistand schon ein Lauf, wartet `run` auf dessen Ergebnis statt neu zu starten.
2. Der Server meldet `RUN_START`. Die App dimmt die bisherigen Teile leicht.
3. Der Rechenprozess führt `model.py` aus. Jedes `show()` tesselliert (unveränderte Teile aus dem Zwischenspeicher) und
   schickt `PART_UPSERT`. Die App blendet das Teil ein und hebt es kurz hervor. `step("Bohrungen")` erscheint in der
   Statusleiste.
4. `RUN_END` mit Zusammenfassung. Teile, die nicht erneut gezeigt wurden, verschwinden.
5. Bei einem Fehler bleibt die letzte gute Geometrie stehen. Die App zeigt ein Fehlerband mit Zeile und Auszug,
   Claude bekommt dasselbe als Antwort.

## 5. Repository-Struktur

```
Kev CAD/
├── README.md · RECHERCHE.md · PLAN-MVP.md · PROTOCOL.md · CLAUDE.md
├── build.sh                      App bauen, installieren, Testvariante
├── app/
│   ├── project.yml               XcodeGen
│   ├── Sources/KevCAD/
│   │   ├── App/                  App, Fenster, Menüs, Willkommensfenster
│   │   ├── Kernel/               Supervisor, Socket-Verbindung, Frame-Decoder
│   │   ├── Scene/                Teilebaum, Laufnummer, Referenzen
│   │   ├── Viewer/               Einbindung OCCTSwiftViewport, Picking, Overlays
│   │   ├── Panels/               Teilebaum, Inspektor, Statusleiste, Protokoll
│   │   └── Project/              Projekte, Zuletzt geöffnet, Dateibeobachtung
│   └── Tests/
├── kernel/
│   ├── pyproject.toml · uv.lock
│   ├── src/kevcad_kernel/
│   │   ├── server.py             MCP-Werkzeuge
│   │   ├── app_link.py           Unix-Socket zur App
│   │   ├── worker.py             Rechenprozess mit Zeitlimit und Neustart
│   │   ├── runner.py             model.py ausführen
│   │   ├── api.py                Modul `kevcad` für model.py: show, step, param
│   │   ├── tessellate.py         ocp-tessellate → Frames
│   │   ├── measure.py · refs.py · export.py
│   │   └── bridge.py             stdio-Brücke `kevcad-mcp`
│   └── tests/
├── skill/kev-cad/SKILL.md        Modellierleitfaden für den Agenten
└── samples/wandhalter/model.py
```

Git von Anfang an, Commits je Arbeitspaket.

## 6. Kernel

### API für `model.py`

```python
from build123d import *
from kevcad import show, step, param

breite = param("breite", 120)            # mm, taucht in der Teileliste und später als Regler auf
dicke = param("dicke", 5)

step("Grundplatte")
platte = Box(breite, 80, dicke)
show(platte, "Grundplatte", color="#B8BEC4", material="aluminium")

step("Bohrungen")
platte -= Pos(-40, 0, 0) * Cylinder(3.2, dicke)
show(platte, "Grundplatte")              # gleicher Name: ersetzt, man sieht das Teil wachsen

show(lasche, "Halter/Lasche")            # Schrägstrich ergibt den Baugruppenbaum
```

- `show(obj, name, color=None, material=None)` nimmt Part, Compound, Builder, Sketch und Kanten. Compounds mit
  benannten Kindern werden als Unterbaum gezeigt.
- `material` nutzt die Materialien von build123d 0.13 (Dichte, Farbe). Damit gibt es schon im MVP Masse und Schwerpunkt.
  Den Schwerpunkt über mehrere Materialien rechnet der Kernel selbst (build123d nimmt dort gleiche Dichte an).
- `param(name, wert, min=None, max=None)` liefert den Wert oder eine Vorgabe aus `run(params=…)`.
- Nach dem Lauf bleibt der Namensraum erhalten, damit `execute` darin Fragen stellen kann.

### Rechenprozess

- Eigener Unterprozess, damit ein OCCT-Absturz oder eine Endlosschleife nur ihn trifft. Zeitlimit je Lauf, Standard
  60 s. Danach Neustart, die App behält die letzte Szene.
- build123d bleibt geladen (der Import kostet sonst 1 bis 2 s je Lauf).
- Kein Sandkasten wie bei build123d-mcp. Es ist dein eigener Code auf deinem Rechner.

### Tessellierung

- ocp-tessellate je Teil: Punkte, Normalen, Dreiecke mit Flächenzuordnung, Kantenzüge mit Kantenzuordnung,
  Flächen- und Kantentypen.
- Zusatzwerte je Fläche (Typ, Fläche, Normale oder Achse und Radius) und je Kante (Typ, Länge, Radius, Mittelpunkt).
- Genauigkeit relativ zur Teilgröße, im Projekt umschaltbar (Entwurf, Normal, Fein).
- Zwischenspeicher über die Form, damit unveränderte Teile beim Neu-Rechnen nicht neu tesselliert werden. Gleiche Form
  an anderer Stelle (Schrauben) geht als Instanz mit eigener Lage.
- **Geprüft in AP0:** Die Flächenreihenfolge von ocp-tessellate passt bei allen 76 Teilen der Küche zu
  `part.faces()`, jede Fläche hat Dreiecke. Bei den Kanten liefert ocp-tessellate zusätzlich **degenerierte Kanten**
  (Punktkanten an Kugelpolen), die build123d auslässt. Der Kernel filtert sie mit `BRep_Tool.Degenerated_s` heraus,
  dann stimmt auch die Kantenreihenfolge. Beides bleibt als Test im Kernel.

### Messen

- **Ein Element:**
  - Fläche: Typ, Flächeninhalt, Normale, Radius und Achse
  - Kante: Länge, Radius, Mittelpunkt
  - Punkt: Koordinaten
  - Teil: Hüllmaße, Volumen, Oberfläche, Masse, Schwerpunkt
- **Zwei Elemente:**
  - kleinster Abstand mit beiden Punkten und dx, dy, dz
  - Mittenabstand von Bohrungen und Achsen
  - Winkel zwischen Ebenen, Kanten und Achsen
  - Abstand paralleler Flächen
- Ergebnis in mm mit drei Nachkommastellen. Es geht als Overlay (Endpunkte und Beschriftung) gleich mit an die App.

## 7. Protokoll App ↔ Kernel

- Unix-Socket, Rahmen wie bei build123d-mcp: `[u32 Länge JSON][JSON][u32 Länge Binär][Binär]`.
- **Kernel → App:**
  - `HELLO`
  - `RUN_START`, `STEP`, `PART_UPSERT`, `PART_REMOVE`, `RUN_END`, `RUN_ERROR`
  - `VIEW_CMD` (Kamera, Sichtbarkeit, Hervorheben, Schnitt, Anmerkung)
  - `SCREENSHOT_REQ`
- **App → Kernel:**
  - `RUN_REQ`, `MEASURE_REQ`, `PROJECT_OPEN`
  - `SELECTION` (was Kevin angeklickt hat)
  - `SCREENSHOT_RES` (PNG)
  - Antworten mit Anfrage-Nummer
- `PART_UPSERT`:
  - Kopf: Name, Pfad im Baum, Laufnummer, Farbe, Material, Lage, Hüllquader, Flächen- und Kantenwerte
  - Binär: float32 Punkte und Normalen, uint32 Dreiecke, int32 Fläche je Dreieck, Kantenzüge mit Versatz und Kanten-ID
- Die genaue Byte-Belegung wird in AP2 in `PROTOCOL.md` festgeschrieben und auf beiden Seiten mit denselben Testdateien
  geprüft.

## 8. MCP-Werkzeuge im MVP

| Werkzeug | Zweck | Antwort |
|---|---|---|
| `status` | Projekt, Kernelzustand, letzter Lauf, Auswahl | Text und JSON |
| `project_open` / `project_new` | Projekt öffnen oder anlegen | Pfad, Teileliste |
| `run` | `model.py` ausführen, optional `params` und `slow` (Zeitlupe für den Aufbau) | Teile mit Maßen, Volumen, Masse, Warnungen; bei Fehler Zeile, Auszug, Hinweis |
| `model_read` / `model_write` | für Clients ohne Dateizugriff (Claude Desktop) | Code |
| `execute` | Python im Namensraum des letzten Laufs: Abfragen, Hilfsgeometrie | Ausgabe; Hilfsgeometrie erscheint als halbtransparente Skizze |
| `parts` | Teilebaum mit Hüllmaßen, Volumen, Masse, Material, Sichtbarkeit | JSON |
| `view` | Standardansicht, Perspektive oder parallel, Darstellung, Explosion | Bestätigung |
| `focus` | Kamera auf Teile oder Flächen, animiert | Bestätigung |
| `visibility` | zeigen, ausblenden, isolieren, alles zeigen | Bestätigung |
| `highlight` | Teile, Flächen, Kanten farbig hervorheben, optional mit Text | Bestätigung |
| `section` | Schnittebene setzen oder entfernen | Bestätigung |
| `screenshot` | Bild der aktuellen Ansicht oder einer anderen Ansicht (offscreen) | Bild, dazu Kamera und mm je Pixel |
| `selection` | was Kevin angeklickt hat | Referenzen mit Werten |
| `measure` | exakt messen (ein oder zwei Referenzen), optional im Viewer einblenden | Werte und Punkte |
| `annotate` | Maß, Pfeil oder Text im Viewer zeigen oder löschen | Bestätigung |
| `export` | STEP, STL, 3MF, GLB in den Projektordner | Dateipfade |

- Bilder standardmäßig 1280 px breit, damit sie wenig Kontext kosten.
- Die Server-Anweisungen des MCP (Feld `instructions`) und der Skill `kev-cad` enthalten die Modellierregeln:
  - mm
  - Parameter oben
  - jedes Teil mit `show()` und sprechendem Namen
  - nach größeren Änderungen `screenshot` und `measure` zur Kontrolle
  - Referenzen nur innerhalb eines Laufs verwenden

## 9. App

- **Willkommensfenster:** Neues Projekt, Öffnen, Zuletzt geöffnet.
- **Projektfenster:**

  | Bereich | Inhalt |
  |---|---|
  | links | Teilebaum mit Auge zum Ausblenden, Farbe, Material, Anzahl |
  | Mitte | Viewport |
  | rechts | Inspektor: Werte der Auswahl, Liste der Messungen |
  | unten | Statusleiste |

  - Statusleiste: Kernel bereit, rechnet oder Fehler; aktueller Schritt („3/7 Bohrungen“); Laufzeit; Agent verbunden;
    Teile und Dreiecke.
- **Werkzeugleiste:** Ansichten, Darstellung (schattiert mit Kanten, schattiert, Drahtgitter, Röntgen), Schnitt, Messen,
  Explosion, Bild, Export, Zeitlupe, Auto-Lauf.
- **Agent sichtbar machen:** Kamerafahrten sind animiert, Hervorhebungen pulsieren kurz, eine kurze Zeile meldet, was
  der Agent gerade tut („misst Abstand Lasche ↔ Grundplatte“).
- **Tastenkürzel:**

  | Taste | Wirkung |
  |---|---|
  | 1 bis 7 | Standardansichten |
  | F | Auswahl einpassen |
  | H | ausblenden |
  | I | isolieren |
  | M | messen |
  | S | Schnitt |
  | E | Explosion |
  | ⌘R | neu rechnen |
  | Esc | Auswahl leeren |

- **Kernel-Supervisor:** startet den Server mit festem Socket und Port, zeigt das Protokoll, startet nach einem Absturz
  neu.
- **Szene:** Teile nach Namen, Laufnummer, Umwandlung in `ViewportBody`, nur geänderte Teile neu hochladen.
- **Auflagen aus AP0 für den Viewport:**
  - Picking muss ausdrücklich eingeschaltet werden (`PickingConfiguration(isEnabled: true)`), sonst kommt nichts
    zurück.
  - Die Klick-Kennung hat nur 14 Bit für die Dreiecks- oder Segmentnummer. Teile mit mehr als 16.000 Dreiecken oder
    Kantensegmenten werden deshalb in mehrere `ViewportBody` aufgeteilt. Die App rechnet Treffer auf Teil, Fläche und
    Kante zurück.
  - Die Bildrate ist im Paket fest auf 60 eingestellt. Für den ProMotion-Bildschirm setzt die App
    `preferredFramesPerSecond` am MTKView selbst auf 120.

## 10. Projektordner

```
~/Documents/Kev CAD/Wandhalter/
├── model.py
├── kevcad.json        Einheit, Genauigkeit, Kameraposition, Sichtbarkeit
├── output/            STEP, STL, 3MF, GLB, Bilder
└── .kevcad/
    ├── log/           Laufprotokolle
    └── versions/      model.py und Vorschaubild je erfolgreichem Lauf
```

Speichern heißt: `model.py` und `kevcad.json` liegen immer aktuell auf der Platte. Versionen werden automatisch
abgelegt. Zurückholen und Vergleichen kommen nach dem MVP.

## 11. Build, Installation, Anbindung an Claude

- **App bauen:**
  - `./build.sh` erzeugt das Xcode-Projekt mit XcodeGen, baut mit `xcodebuild`, signiert ad hoc und legt
    `Kev CAD.app` nach `~/Applications/Tools`.
  - `--test` baut „Kev CAD Test“ mit Bundle-ID `de.upvis.kevcad.test`, eigenem Datenordner, eigenem Socket und Port.
  - `--no-install` baut nur.
- **Kernel:** `uv sync` in `kernel/`. Abhängigkeiten sind build123d 0.13, ocp-tessellate, mcp, numpy.
- **Claude Code** (einmalig):

  ```bash
  claude mcp add --scope user kevcad -- "/Users/kevinschwed/Code Experiments/Kev CAD/kernel/.venv/bin/kevcad-mcp"
  ```

- Skill `kev-cad` nach `~/.claude/skills` verlinken.
- **UI-Tests** nach deinen Regeln: Testvariante im Hintergrund (`open -g -n`) auf dem zweiten Monitor (6K extern),
  Mauszeiger und vorheriges Programm danach wiederherstellen.

## 12. Arbeitspakete

| AP | Inhalt | Ergebnis und Prüfung | Größe |
|---|---|---|---|
| **AP0** (erledigt) | **Viewer- und Kerneltest.** Erstens ocp-tessellate mit build123d 0.13 an der Outdoorküche: Zeit, Dreiecke, Flächenreihenfolge. Zweitens Mini-App mit OCCTSwiftViewport lädt das Ergebnis. | Messwerte gegen die Schwellen in Abschnitt 13. **Entscheidung:** OCCTSwiftViewport oder Rückfall RealityKit | S |
| AP1 (erledigt) | Grundgerüst: Git, `project.yml`, `build.sh`, Kernel-Paket mit uv, `CLAUDE.md`, README | Leeres Fenster startet aus `~/Applications/Tools`, Kernel startet von Hand | S |
| AP2 (erledigt) | Kernel: Rechenprozess, `model.py`-API, Tessellierung, Frames, Socket, `PROTOCOL.md` | pytest: Würfel und Zylinder kommen richtig an, Absturz und Zeitlimit führen zu Neustart | M |
| AP3 (erledigt) | App-Kern: Supervisor, Decoder, Szene, Viewport, Live-Aufbau, Teilebaum, Statusleiste, Fehlerband | Beispiel „Wandhalter“ baut sich Teil für Teil auf, ein Syntaxfehler zeigt die Zeile | M |
| AP4 (erledigt) | Projekte: Willkommensfenster, neu, öffnen, zuletzt, Auto-Lauf, Export | Projekt anlegen, speichern, neu öffnen; STEP, STL und 3MF öffnen in Bambu Studio | S |
| AP5 (erledigt) | Auswahl und Messen: Picking zu Referenzen, Inspektor, exakte Messung, Overlays | Bekannte Maße am Testkörper stimmen auf 0,001 mm, Winkel auf 0,01° | M |
| AP6 (erledigt) | MCP: alle Werkzeuge aus Abschnitt 8, Viewer-Befehle, Bild, stdio-Brücke, Skill, Registrierung | Ein Testskript fährt alle Werkzeuge über einen echten MCP-Client ab; Claude Code sieht sie nach Neustart | M |
| AP7 (erledigt) | Abnahme: Ablauf aus Abschnitt 1 mit Claude, Leistungstest Outdoorküche, Fehler beheben, Doku | Ablauf läuft durch, Messwerte erfüllt, README beschreibt Installation und Bedienung | S |

### Ergebnis AP0 (21.10.2026)

**Kernel** (build123d 0.13, ocp-tessellate 3.6.3, Küche mit Pizzaofen):

| Messung | Wert |
|---|---|
| Teile, Dreiecke, Flächen, Kanten | 59 Teile, 101.816 Dreiecke, 2.126 Flächen, 5.181 Kanten |
| Tessellierung gesamt | 0,89 s, Median 3 ms je Teil, größtes Teil 277 ms |
| Erneut aus dem Zwischenspeicher | 0,04 s |
| Modell bauen (`kueche.py`) | 4,0 s |
| build123d importieren | 4–5 s, deshalb bleibt der Rechenprozess warm |
| Flächenreihenfolge gleich build123d | 59 von 59 (Animationsvariante 76 von 76) |
| Kantenreihenfolge gleich build123d | nach Filtern der degenerierten Kanten alle |

**Viewer** (OCCTSwiftViewport, Testfenster auf dem DELL U3223QE mit 60 Hz, Picking eingeschaltet):

| Szene | Teile / Körper | Dreiecke | Bildrate beim Drehen | CPU je Bild | Klick-Latenz Median / Max | Speicher |
|---|---|---|---|---|---|---|
| Küche | 59 / 59 | 102.000 | 60 fps, kein Ausreißer | 0,7 ms | 0,2 / 12 ms | 122 MB |
| Küche, große Teile aufgeteilt | 59 / 61 | 102.000 | 60 fps | 1,0 ms | 0,9 / 7 ms | 116 MB |
| 10-fache Küche | 590 / 610 | 1,0 Mio. | 60 fps, kein Ausreißer | 5,7 ms | 5,8 / 11 ms | 424 MB |
| 30-fache Küche | 1.770 / 1.830 | 3,1 Mio. | 42 fps | 18 ms | 22 / 30 ms | 1,1 GB |

- **Klick-Genauigkeit:** GPU-Picking gegen eigene Strahlberechnung auf der CPU. Treffer und Fehlschläge stimmen
  überein. Die Fläche stimmt in 41 von 41 Fällen, bei der 10-fachen Küche in 62 von 62. Nur dort, wo zwei Teile genau
  aneinanderstoßen (Satteldach und Giebel), gewinnt manchmal das Nachbarteil.
- **14-Bit-Grenze bestätigt:** Am Kühlschrank-Boden (45.948 Dreiecke) stimmen ohne Aufteilung nur 8 von 21 Flächen,
  alle Fehler jenseits von Dreieck 16.384. Mit Aufteilung in Stücke zu 16.000 sind es 77 von 77.
- **Offscreen-Bild** 1600 × 1000 mit Kanten: 26 ms beim ersten Mal, danach 6–7 ms (10-fach: 12 ms).
- **Daten in die App:** 4,8 MB lesen 3 ms, Körper aufbauen 5 ms.
- **Grenze:** Die CPU-Zeit wächst mit der Zahl der Körper (etwa 10 µs je Körper). Bis rund 1.000 Körper bleibt es bei
  60 fps. Für noch größere Baugruppen mit vielen Kleinteilen fassen wir später kleine Teile zu gemeinsamen Körpern
  zusammen und rechnen Treffer über die Flächenzuordnung zurück.
- **Bildqualität:** Kanten, Schattierung und das transparente Kühlschrankglas sehen sauber aus
  (Bildschirmbild aus dem Kundenprojekt, seit 23.10.2026 nicht mehr im Repo).

**Entscheidung:** OCCTSwiftViewport wird die Viewer-Basis, mit den Auflagen aus Abschnitt 9. RealityKit bleibt nur für
spätere Renderings im Plan.

**Reihenfolge:**
- AP0 erledigt.
- AP2 und AP3 können nach festgeschriebenem Protokoll parallel laufen.
- AP5 und AP6 bauen auf beiden auf.

Grob geschätzt sind das sechs bis acht Arbeitssitzungen.

## 13. Tests und Messgrößen

| Größe | Ziel |
|---|---|
| Bildrate beim Drehen der Outdoorküche | mindestens 60 fps, auf dem Hauptbildschirm 120 |
| Picking | unter einer Bildzeit (16 ms) |
| Erstes Teil sichtbar nach `show()` (kleines Teil) | unter 300 ms |
| Neu-Rechnen ohne Änderung an einem Teil | dieses Teil nicht neu tesselliert |
| Kernelstart bis bereit | unter 3 s |
| Messgenauigkeit gegen Sollmaß | 0,001 mm und 0,01° |
| Bild für den Agenten | unter 1 s |

**Tests je Seite:**
- **Kernel:** pytest für Tessellierung, Referenzen, Messen, Zeitlimit und Absturz.
- **App:** XCTest für den Frame-Decoder mit denselben Testdateien wie der Kernel, Offscreen-Bild nicht leer.
- **Gesamt:** ein MCP-Client-Skript fährt den Ablauf aus Abschnitt 1 ab.

## 14. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| OCCTSwiftViewport ist jung, hat einen Entwickler und ändert seine API schnell | auf Commit festnageln, bei Bedarf ins Repo übernehmen (LGPL-Hinweise bleiben). AP0 prüft vorher. Rückfall RealityKit |
| Flächenindizes ändern sich bei jedem Lauf (bekanntes Problem der Topologie-Benennung) | Referenzen tragen die Laufnummer. Veraltete Referenzen lehnt der Kernel mit Hinweis ab. Dauerhafte Namen für Flächen später über Merkmale |
| Große Baugruppen tessellieren langsam | Zwischenspeicher, Instanzen, Genauigkeitsstufen, parallele Vernetzung in OCCT |
| Viele Körper kosten CPU-Zeit je Bild (AP0: ab etwa 1.000 Körpern unter 60 fps) | kleine Teile später zu gemeinsamen Körpern bündeln |
| Klick-Kennung hat nur 14 Bit (AP0 bestätigt) | große Teile in Körper zu höchstens 16.000 Dreiecken aufteilen |
| Absturz oder Hänger im Python-Prozess | getrennter Rechenprozess mit Zeitlimit und Neustart |
| App beim Start von Claude Code zu | stdio-Brücke startet die App im Hintergrund |
| Bilder fressen Kontext | 1280 px als Vorgabe, auf Wunsch kleiner |
| LGPL-Lizenz des Viewports | für ein eigenes Werkzeug unkritisch. Erst bei Weitergabe der App muss der Viewport austauschbar bleiben |
| Plattenplatz (22 GB frei) | Kernel-Umgebung braucht unter 1 GB |

## 15. Danach

1. **Lagerteile und Baugruppen.**
   - Katalog als JSON: Rohr Ø × Wand, Vierkantrohr, Alu-Nutprofil, Holz, Platte, Schraube; jeweils mit Material,
     Dichte, Farbe und Preis je Meter.
   - `lager.rohr(…).verbauen(länge, gehrung)` im Modellcode.
   - Stückliste mit Zuschnitt, Gewicht und Kosten.
   - Startbestand aus bd_warehouse; eigene Tabellen für DIN EN 10220 und für item/Bosch-Profile.
   - Gelenke von build123d für die Platzierung.
2. **Datenblätter.** Ansichten mit verdeckten Kanten, automatische Maße (portiert aus text-to-cad, MIT), Schriftkopf,
   Stücklistentabelle, Schnitt. PDF und Druck über den macOS-Druckdialog. Dein `massblatt.py` der Outdoorküche dient
   als Vorbild.
3. **Renderings.** RealityKit offscreen mit Studiolicht und Materialien. Für Schönes weiter Blender mit `bauteile.py`.
4. **Bambu P2S** (Korrektur 21.10.2026: Kevins Drucker ist ein **P1P**, siehe RECHERCHE.md).
   - Slicen mit der Kommandozeile von Bambu Studio, Übergabe an Bambu Studio.
   - Optional Direktdruck im LAN-Modus mit Fortschritt in der App.
   - Druckstart immer erst nach Bestätigung in der App.
5. **Komfort.** Versionen vergleichen, Parameter-Schieberegler (Vorbild cad-studio), STEP-Import, Kompatibilität mit
   `ocp_vscode.show`.

## 16. Offene Fragen

| Frage | Vorschlag |
|---|---|
| Privates GitHub-Repo `UPVIS/kev-cad` anlegen? | ja, privat |
| Projekte unter `~/Documents/Kev CAD/`? | ja |
| App-Name „Kev CAD“, Bundle-ID `de.upvis.kevcad`? | ja |

## 17. Abnahme (21.10.2026)

Die vier Stränge AP2/AP5 (Kernel-Laufzeit), AP6 (MCP und Brücke), AP3/AP5 (App-Kern) und AP4 (Oberfläche) liefen
parallel in eigenen Arbeitskopien und sind in `main` zusammengeführt.

| Prüfung | Ergebnis |
|---|---|
| Kernel-Tests (pytest, ohne den langsamen Küchentest) | 81 grün |
| KevCADCore-Tests (swift test) | 77 grün |
| Ablauf über MCP gegen die laufende App (Testvariante) | Projekt anlegen, Lauf (Wandhalter, 3 Teile, 140 ms), Ansichten, Fokus, Hervorheben mit Beschriftung, Messen mit Einblendung (50,389 mm), Schnitt, Bilder, Export STEP/STL/3MF – alles ohne Fehler |
| Bilder für den Agenten | 50–120 ms, nach einem Ansichtswechsel ~450 ms (wartet auf das Ende der Kamerafahrt); Vorderansicht parallel mit 0,449 mm je Pixel |
| Küche in der echten App | 59 Teile mit Baugruppenbaum, Lauf 5,5 s (davon 4 s Modellbau in `kueche.py`), erneuter Lauf aus dem Zwischenspeicher |
| Brücke `kevcad-mcp` (stdio) gegen die laufende App | 19 Werkzeuge, status und screenshot gehen durch |
| Bei der Abnahme behoben | Bild direkt nach einem Ansichtswechsel zeigte die Kamera mitten in der Fahrt |

Eingerichtet: `Kev CAD.app` in `~/Applications/Tools`, MCP-Server `kevcad` in Claude Code (Benutzerebene,
`KEVCAD_LAUNCH_ON_START=0`: die App startet erst beim ersten Werkzeugaufruf), Skill `kev-cad` als Verweis in
`~/.claude/skills`.

### Offene Punkte

- **Von Hand prüfen:** echte Mausklicks, Tastenkürzel und Dialoge (Neues Projekt, Öffnen). Eine im Hintergrund gestartete
  Testvariante bekommt keinen Fokus, deshalb nicht automatisch getestet.
- **Bildrate in der echten App** mit der Küche nicht gemessen; der Viewport-Test aus AP0 gilt (60 fps am 60-Hz-Monitor),
  die App setzt 120 Bilder/s.
- **Kaltstart:** In einer frischen Umgebung braucht der erste Start des Kernels wegen der Bytecode-Übersetzung bis zu
  45 s, danach etwa 4 s bis der Rechenprozess bereit ist (Socket sofort).
- **Schnitt ohne Deckfläche:** Geschnittene Körper sind innen hohl dargestellt.
- **Farbwirkung:** Der Viewport kodiert nicht nach sRGB; die App gleicht mit etwas mehr Belichtung aus. Einmal ansehen.
- **Wünsche der Oberfläche an den App-Kern:** Schnittachse und -lage im Modell, Aktion „Projekt schließen“,
  Exportergebnis im Modell (für „Im Finder zeigen“).
- **Nicht gebaut:** Instanzen (`transform`), Vorschaubild je Version.
