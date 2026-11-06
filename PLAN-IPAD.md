# Kev CAD · Plan iPad (Parität Mac und iPad)

Stand 06.11.2026. Gearbeitet wird in kurzen Arbeitskopien, jeder geprüfte Schritt geht sofort nach `main` (CLAUDE.md,
„Immer direkt auf main arbeiten“). Grundlage: [PLAN-V2.md](PLAN-V2.md) (KI-first, Budgets), [OBERFLAECHE.md](OBERFLAECHE.md)
(Graphit, Leisten, Kacheln), [PROTOCOL.md](PROTOCOL.md) (Kernel und App), [MIRROR.md](MIRROR.md) (Spiegel aufs iPhone).

## 1. Ziel

Kevin, 06.11.2026 (diktiert, sinngemäß): Kev CAD soll unbedingt auf dem iPad laufen, mit absoluter Feature-Parität.
Beide Fassungen werden immer zusammen weiterentwickelt: gleiche Engine, gleiche Sprachsteuerung, gleicher Look. Nur
Oberfläche und Bedienung sind je Gerät zugeschnitten, auf dem iPad performant und mit einem Bedienschema für Touch und
Stift, „das richtig Bock macht“. Der Stift beschreibt beim Sprechen Dinge im dreidimensionalen Raum; ein Druck auf den
Stift öffnet ein Menü um die Spitze (Farben, Ansichten, MCP). Projekte liegen lokal und in der iCloud. Mac und iPad sind
live gekoppelt, in beide Richtungen: gleiche Ansicht oder eine eigene, das Modell immer live.

**Fertig, wenn:**

1. Kevin öffnet Kev CAD auf dem iPad; es verbindet sich ohne Zutun mit dem Mac (im WLAN, unterwegs über Tailscale) und
   zeigt das offene Projekt so, wie es sich am Mac aufbaut.
2. Er dreht mit einem Finger, verschiebt mit zwei, zoomt mit zwei, flüssig mit 120 Bildern/s (iPad Pro M2, 134 Teile).
3. Er startet das Sprechen, redet, zeichnet mit dem Stift eine Strebe zwischen zwei Rohre und schickt ab. Der Agent
   bekommt dasselbe Paket wie vom Mac (Sätze mit Bezügen, Striche als 3D-Linien mit Teilbezug), baut die Strebe, beide
   Geräte zeigen das Ergebnis.
4. Doppeltippen auf den Stift öffnet den Werkzeugkranz an der Spitze; ein Wisch wählt.
5. „Gemeinsame Ansicht“: Dreht er am iPad, dreht der Mac mit, und umgekehrt. „Eigene Ansicht“: jedes Gerät für sich, das
   Modell bleibt auf beiden live.
6. Projekte liegen im iCloud-Ordner „Kev CAD“ und sind auf beiden Geräten lokal da.
7. Jede Funktion des Mac ist auf dem iPad erreichbar (Prüfliste in Abschnitt 9). Was das iPad neu kann (Werkzeugkranz,
   Strichfarben, Kopplung), bekommt der Mac ebenso.

## 2. Entscheidungen

| Nr. | Entscheidung | Grund |
|---|---|---|
| I1 | **Eine Engine.** Der Kernel (Python, build123d, Gedächtnis, Prüfung, Statik, Simulation, Dokumente) bleibt der einzige Rechenkern und läuft auf dem Mac (heute das MacBook mit der Mac-App, später auch der Mac mini als Dauer-Host). Das iPad ist ein zweiter, gleichwertiger Client. | Gleiche Engine heißt gleiche Ergebnisse; jede Änderung am Kernel wirkt sofort auf beiden Geräten. Python mit OpenCascade auf iPadOS wäre ein eigenes Großprojekt (OCP für iOS übersetzen, rund 1 GB Bindungen) und brächte wenig: Der Agent läuft ohnehin auf dem Mac. |
| I2 | **Ein Code.** KevCADCore, KevCADWire und der Viewport übersetzen für macOS und iPadOS. Die Oberfläche in `app/Sources/KevCAD` ist gemeinsamer Code. Je Plattform eigen ist nur die Hülle: Mac in `app/Sources/KevCAD/Mac/` (Menüs, Fenster, Finder, Maus und Tasten), iPad in `app/Sources/KevCADPad/` (Szene, Touch, Stift, Daumenleiste, Kopplung). | Parität durch Bauweise: Was in der gemeinsamen Oberfläche entsteht, ist auf beiden Geräten da. Ein zweites UI-Projekt liefe auseinander. |
| I3 | **Parität wird geprüft, nicht erhofft.** (a) Jeder Befehl steht im Befehlskatalog (heute `ViewerBefehl` und `Tastenbelegung`, erweitert um alle Menübefehle) mit einem Auslöser am Mac und einem am iPad; ein Test schlägt fehl, wenn einer fehlt. (b) Jeder Testbau übersetzt beide Ziele. (c) `tools/paritaet.py` ordnet die Hüllen-Dateien einander zu (`paritaet.json`, Ausnahmen mit Grund) und meldet Änderungen, die nur eine Seite bekommen hat. | Kevin: „dass zwischen beiden Versionen immer Parallelität herrscht und dass beides immer mitentwickelt wird“. Vorbild: Rotation (iPhone und Android, `Tools/paritaet.py`). |
| I4 | **Gleicher Look.** Gestaltungswerte und Bausteine (Graphit, `Gestaltung/`) sind gemeinsam. Abweichungen nur, wo das Gerät sie verlangt: Trefferflächen mindestens 44 pt, Daumenzonen, Hinweisleiste mit Gesten statt Tasten, nichts hängt am Darüberfahren. | Kevin: „Look and Feel soll genau gleich sein“. |
| I5 | **Rollen statt Modi:** Finger bewegen die Kamera, der Stift zeigt, wählt und zeichnet, die Stimme sagt, was passieren soll (Abschnitt 4). Keine Manipulatoren (V7 gilt weiter). | Jede Hand hat eine feste Aufgabe, nichts muss umgeschaltet werden. |
| I6 | **Werkzeugkranz:** ein Kreismenü an der Stiftspitze (Doppeltippen am Pencil 2 und USB-C, Drücken am Pencil Pro, mit dem Finger über die Daumenleiste). Derselbe Kranz kommt an den Mac (Taste Q wie Blenders Schnellfavoriten) und baut auf den Kreismenüs des Viewers auf (`ViewerMenues.swift`). | Kevins Wunsch; Parität in beide Richtungen. |
| I7 | **Zeichnen im Raum:** Striche liegen auf der Fläche unter dem Stift, daneben auf einer Ebene durch den letzten Treffer parallel zum Bild (so rechnet schon der Mac, `StrichPunkt.welt`, `ref`). Sie bleiben im Modell, drehen sich mit, tragen eine Farbe und gehen als 3D-Polylinien mit Teilbezug ins Paket. Der Strich wird im Bildtakt mit Vorhersage gezeichnet, die Zuordnung zum Modell läuft dahinter her. | Kevin: „im dreidimensionalen Raum beschreiben, während man spricht“. |
| I8 | **Verbindung:** Der Kernel nimmt mehrere App-Verbindungen zugleich an (heute ersetzt in `app_link.py` eine neue die alte). Die Mac-App öffnet einen Eingang fürs iPad (Network.framework, TLS mit einem Schlüssel aus der Kopplung, Bonjour `_kevcad._tcp`) und reicht die Rahmen unverändert an den Kernel durch. Für den Kernel ist das iPad eine zweite App-Verbindung. Gekoppelt wird einmal per QR-Code am Mac; unterwegs geht es über Tailscale. | Der Kernel bleibt schlicht (nur mehrere Verbindungen). TLS und Bonjour in Swift sind erprobt (VoiceBridge, Sichtung), und Python braucht keinen offenen Port (keine Firewall-Abfrage). Ersetzt für genau diesen gekoppelten Eingang die Regel aus MIRROR.md „kein Netzwerkport“. |
| I9 | **Live-Kopplung:** Modell, Lauf, Befunde und Agentenspur sind immer auf allen Geräten. Je Gerät wählbar: **Gemeinsame Ansicht** (Kamera, Auswahl, Sichtbarkeit, Isolieren, Darstellung, Leisten und Kacheln folgen dem Gerät, das zuletzt bedient wurde, in beide Richtungen) oder **Eigene Ansicht**. Striche und Zeiger beim Sprechen sieht das andere Gerät live. | Kevin: „Both Ways … live Update“, „die gleiche View … oder eine andere Ansicht“. |
| I10 | **Wen der Agent anspricht:** Ansichtsbefehle des Agenten (`view`, Kacheln, Anmerkungen) gehen an alle Geräte der Gemeinsamen Ansicht, sonst an das aktive Gerät (zuletzt bedient oder gesprochen). `status` liefert das Lagebild des aktiven Geräts und nennt die anderen. | Der Agent zeigt dort, wo Kevin hinschaut. |
| I11 | **iCloud:** Projekte im iCloud-Ordner „Kev CAD“, auf jedem Gerät lokal vorhanden. Zwischenspeicher (Tessellierung, Gedächtnis, Protokolle) bleiben außerhalb der iCloud. Live geht nie über iCloud, sondern über die Kopplung. Bestehende Projekte ziehen erst nach Kevins Ja um. | Sicherung und Projekte auf beiden Geräten; iCloud braucht Sekunden bis Minuten. |
| I12 | **Verteilung:** TestFlight (interne Gruppe „Kevin“), automatisch aus main wie das Mac-Update, höchstens stündlich. Den App-Eintrag in App Store Connect legt Kevin einmal im Browser an (Regel `apple-app-verteilung`, geht nicht über die API). | Kevin bekommt jeden geprüften Stand auf dem iPad wie am Mac. |

## 3. Aufbau

```
Mac (MacBook; später auch Mac mini als Dauer-Host)
  Claude Code ── MCP ──> Kernel (Python: build123d, Gedächtnis, Prüfung, Statik, Simulation, Dokumente)
                            │  Unix-Socket, mehrere Verbindungen (neu)
                            ├──────> Kev CAD für Mac (Viewer, Oberfläche, Sprechen)
                            │            └─ Eingang fürs iPad: TLS mit Schlüssel aus der Kopplung, Bonjour _kevcad._tcp,
                            │               reicht Rahmen unverändert durch
                            └──────────────────────> Kev CAD für iPad (WLAN direkt, unterwegs Tailscale)

iCloud-Ordner „Kev CAD“: model.py, Versionen, Referenzen, Dokumente (auf beiden Geräten lokal)
```

**Code je Plattform**

| Baustein | macOS | iPadOS |
|---|---|---|
| KevCADWire (Rahmen, Netze, Spiegel) | ja | ja (heute schon für VoiceBridge) |
| OCCTSwiftViewport (Metal) | ja | ja (ein Zweig für den Simulator, `KEVCAD-AENDERUNGEN.md`) |
| KevCADCore (Protokoll, Verbindung, Szene, `AppController`, Sprechen) | ja | ja; Mac-Teile (Kernelprozess, Wortlaut über XPC, NSEvent) hinter `#if os(macOS)`, Weichen in `Plattform/` |
| Oberfläche `app/Sources/KevCAD` | ja | ja, ohne `Mac/` |
| Hülle `app/Sources/KevCAD/Mac/` | ja | – |
| Hülle `app/Sources/KevCADPad/` | – | ja |
| Kernel, MCP, Skill | auf dem Mac | über die Verbindung |

Der Vertrag zwischen Kern und Oberfläche bleibt `AppModel`/`AppActions` (CLAUDE.md): Die iPad-Oberfläche liest `AppModel`
und ruft nur `AppActions`, genau wie die Mac-Oberfläche.

**Kernel mit mehreren Verbindungen**

| Nachricht | geht an |
|---|---|
| Zustand (HELLO, PROJECT, STATUS, AGENT, RUN_*, PART_*, Befunde, Stückliste, Statik …) | alle Verbindungen; Delta-Basis je Verbindung (V2-5, `AppConnection` führt sie schon je Verbindung) |
| Antworten (`reply_to`) | nur die fragende Verbindung |
| VIEW_CMD, Kacheln, Anmerkungen des Agenten | alle Geräte der Gemeinsamen Ansicht, sonst das aktive Gerät |
| SCREENSHOT_REQ, Lagebild für `status` | das aktive Gerät |
| SELECTION | je Gerät gemerkt; „Kevins Auswahl“ ist die des aktiven Geräts |
| Feedback-Paket | von jedem Gerät, mit `geraet` |
| neu `ANSICHT` (Kamera, Auswahl, Sichtbarkeit, Leisten, Kacheln, Darstellung) | an die anderen Geräte der Gemeinsamen Ansicht; Kamera nur der neueste Stand, höchstens 60 je Sekunde |

## 4. Bedienung am iPad

### 4.1 Grundsatz

Finger bewegen die Kamera. Der Stift zeigt, wählt und zeichnet. Die Stimme sagt, was passieren soll. Mit Magic Keyboard
und Trackpad gilt die Blender-Belegung des Mac unverändert; `Tastenbelegung.swift` bleibt die einzige Quelle und bekommt
die Touch- und Stiftgriffe dazu (Hinweisleiste und Übersicht lesen dort).

### 4.2 Finger

| Geste | Wirkung | am Mac |
|---|---|---|
| 1 Finger ziehen | Drehen um den Punkt unter dem Finger | Mitte ziehen |
| 2 Finger ziehen | Verschieben | ⇧ Mitte ziehen |
| 2 Finger spreizen | Zoomen zur Mitte der Finger | Rad, Zoomgeste |
| Tippen | Auswählen (Teil; im Elementmodus Fläche, Kante, Punkt) | Links klicken |
| Doppeltippen | Auf das Teil einrahmen, auf leerem Grund alles | `.` und Pos1 |
| Lange drücken | Kontextmenü am Teil (Isolieren, Ausblenden, Messen, Umbenennen, Details …) | Rechts klicken |
| 2 Finger tippen | Rückgängig (Ansicht, Auswahl, Sichtbarkeit) | ⌘Z |
| 3 Finger tippen | Wiederholen | ⇧⌘Z |
| vom linken bzw. rechten Rand wischen | Leiste links (Gliederung) bzw. rechts (Kacheln, Details) | ⌘1, ⌘2 |
| 4 Finger | bleibt dem System | – |

Um die Blickachse wird nicht gedreht (Z bleibt oben wie am Mac). Ein schnell losgelassener Finger dreht kurz nach
(Schwung, abschaltbar).

### 4.3 Stift

Kevins iPad Pro 12,9″ (6. Generation, M2) kann Pencil 2 und Pencil USB-C: Schweben und Doppeltippen. Der Pencil Pro
(Drücken, Rollen, Haptik) braucht ein neueres iPad; der Plan nutzt ihn, wo er da ist, und braucht ihn nicht.

| Stift | ohne Sprechen | beim Sprechen |
|---|---|---|
| Schweben (Spitze über dem Glas) | Teil unter der Spitze leuchtet, beim Messen Vorschau des Maßes | zählt als Zeigen: „das hier“ ist das Teil unter der Spitze |
| Tippen | Auswählen, genauer als der Finger | Bezug setzen (Nadel) |
| Ziehen | startet das Sprechen und zeichnet (Vorgabe, abschaltbar; dann Rahmen aufziehen wie die linke Maustaste) | Zeichnen im Raum |
| Doppeltippen, am Pencil Pro Drücken | Werkzeugkranz an der Spitze | Werkzeugkranz, oben „Senden“ |
| Rollen (Pencil Pro) | dreht die Wahl im Kranz | – |

Die Finger navigieren weiter, während der Stift zeichnet; Handballen zählen nicht, solange der Stift aufliegt. Die
Systemeinstellung „Nur mit Apple Pencil zeichnen“ gilt; ohne Stift zeichnet der Finger, wenn die Daumenleiste auf
„Zeichnen“ steht.

### 4.4 Werkzeugkranz

```
                        Sprechen / Senden
          Agent                                Ansichten
    Kacheln              ( Abbrechen )              Farbe
          Sichtbarkeit                         Darstellung
                             Messen
```

- Er erscheint an der Stiftspitze (Schwebeposition), sonst am letzten Berührpunkt. Erste Ebene acht Felder, die zweite
  als äußerer Ring.
- Gewählt wird durch Tippen auf das Feld oder durch Wischen in die Richtung, auch ohne hinzusehen (wie Blenders
  Kreismenüs). Am Pencil Pro dreht Rollen die Wahl, die Haptik meldet jedes Feld.
- Belegung:
  - **Sprechen / Senden** (oben): ohne Sitzung startet es, in der Sitzung schickt es ab. „Doppeltippen, nach oben“ ist
    die Hauptschleife.
  - **Ansichten:** Vorne, Oben, Rechts, Iso, Gegenseite, Alles einrahmen, Zweite Ansicht, Schnitt.
  - **Farbe:** Strichfarbe Rot, Gelb, Grün, Blau, Weiß. Kevin kann sie beim Sprechen nennen („die rote Linie“), das Paket
    trägt sie.
  - **Darstellung:** wie Z am Mac (Schattiert, mit Kanten, Röntgen, Explosion).
  - **Messen.**
  - **Sichtbarkeit:** Isolieren, Ausblenden, Alles einblenden, Teil oder Element.
  - **Kacheln:** Druck, Zeichnung, Bauplan, Stückliste, Animation, Statik, Versionen, Rendern.
  - **Agent:** Neu rechnen, Prüfen, Bild an den Agenten, Meilenstein.
- Die Felder kommen aus dem Befehlskatalog; Kevin kann sie später umlegen. Am Mac öffnet Q denselben Kranz an der Maus.

### 4.5 Sprechen

1. **Starten:** Daumenleiste „Sprechen“, Kranz oben, ein Stiftstrich oder V auf der Tastatur. Der rote Rahmen zeigt, dass
   zugehört wird (wie am Mac).
2. **Währenddessen:** reden, mit dem Stift zeigen und zeichnen, mit den Fingern drehen. Alles läuft auf einer Uhr, die
   Wörter erscheinen live als Text.
3. **Abschicken:** Kranz oben, Daumenleiste „Senden“ oder ↩. **Verwerfen:** X am Rahmen oder Esc.
4. **Erkennung** auf dem Gerät mit Apples SpeechAnalyzer (am Mac der Rückfall hinter Wortlaut). Wortlaut mit Parakeet
   läuft nur am Mac; ob Parakeet über Core ML aufs iPad kommt, prüft I-5.
5. **Ohne Verbindung** wird die Sitzung lokal fertig und geht los, sobald der Mac wieder da ist (Postausgang wie in
   Sichtung).

### 4.6 Bildschirm

```
┌────────────────────────────────────────────────────────────────────┐
│ Projekt ▾          Darstellung ◐ ◑ ◒        Kopplung ⇄       ⋯     │  Kopfleiste schwebend, ohne Grund
│                                                                    │
│ ◉ Sprechen                                                 ┌─────┐ │
│ ↶                                                          │  1  │ │  Kacheln in der rechten Leiste
│ ↷                    3D über den ganzen Bildschirm         ├─────┤ │
│ ✎ Zeichnen                                                 │  2  │ │
│ ◎ Kranz                                                    └─────┘ │
│                 Agentenspur · Hinweise (Gesten)                    │
└────────────────────────────────────────────────────────────────────┘
```

- **Daumenleiste** am linken Rand (Stift in der rechten Hand; für Linkshänder rechts): Sprechen (groß), Rückgängig,
  Wiederholen, Zeichnen mit dem Finger, Werkzeugkranz.
- **Leisten** links (Gliederung) und rechts (Kacheln, Details) wie am Mac, als Schublade über dem Viewer. Im Hochformat
  kommen die Kacheln als Blatt von unten.
- **Kopfleiste** wie am Mac ohne Hintergrund. Stage Manager und geteilter Bildschirm: Schmale Fenster verhalten sich wie
  „An den Rand“ am Mac.
- **Hinweisleiste** zeigt Gesten statt Tasten (gleiche Quelle wie am Mac).

### 4.7 Tastatur und Trackpad

Am Magic Keyboard gelten alle Kürzel aus `Tastenbelegung.swift` (die Tastencodes des Mac werden den HID-Codes von `UIKey`
zugeordnet). Trackpad: zwei Finger drehen, mit ⇧ verschieben, Zoomgeste wie am Mac; der Zeiger zeigt wie die Maus.

## 5. Live-Kopplung

- **Geräte:** Die Kopfleiste zeigt, welches Gerät noch verbunden ist und in welcher Art („Gemeinsame Ansicht mit dem
  MacBook“). Umschalten mit einem Tipp; die Wahl merkt sich jedes Gerät.
- **Gemeinsame Ansicht:** Führung hat, wer zuletzt bedient wird; das andere Gerät folgt weich. Nach einer Pause von 1 s
  darf das andere Gerät die Führung übernehmen, gleichzeitige Bedienung entscheidet der spätere Griff. Gespiegelt werden
  Kamera (Augpunkt, Ziel, oben, senkrechter Öffnungswinkel bzw. Maßstab bei Parallelprojektion), Auswahl, Sichtbarkeit,
  Isolieren, Darstellung, Schnitt, Leisten und Kacheln. Andere Seitenverhältnisse zeigen an den Rändern etwas mehr oder
  weniger.
- **Eigene Ansicht:** Nur Modell, Lauf, Befunde und Agentenspur sind gemeinsam. Auf Wunsch zeigt jedes Gerät den Blick des
  anderen als dünnen Rahmen im Modell („wo schaut das iPad hin“).
- **Beim Sprechen** sieht das andere Gerät Zeiger, Striche und Text live. So kann der Mac als großer Schirm laufen, während
  Kevin auf dem iPad zeichnet.
- **Agent:** Abschnitt 2, I10. Das Feedback-Paket nennt das Gerät; Bilder für den Agenten rechnet das aktive Gerät.
- **Abbrüche:** Startet die Mac-App neu (jedes Update auf main), verbindet sich das iPad selbst neu und behält Ansicht und
  offene Sitzung.

## 6. iCloud

- **Ort:** iCloud Drive › „Kev CAD“ (Ordner der App, `iCloud.de.upvis.kevcad`, in der Dateien-App sichtbar). Auf dem Mac
  liegt er unter `~/Library/Mobile Documents/iCloud~de~upvis~kevcad/Documents/`; der Kernel liest dort wie heute in
  `~/Documents/Kev CAD` (Umgebungsvariable `KEVCAD_PROJECTS_DIR`).
- **Mit:** `model.py`, `referenzen/`, Versionen, Dokumente und Exporte.
- **Ohne:** `.kevcad/log` und alle Zwischenspeicher des Kernels; sie ziehen nach `~/Library/Caches/de.upvis.kevcad/` oder
  bekommen die Endung `.nosync`.
- **Schreiben** tut nur der Kernel. Das iPad schreibt in Projektordner nur Eigenes (Feedback, Fotos) in eigene
  Unterordner; Konfliktkopien meldet die App.
- **iPad ohne Mac:** Projektliste aus dem iCloud-Ordner, das letzte Modell aus dem eigenen Zwischenspeicher, Sprechen und
  Zeichnen im Postausgang.
- **Erst prüfen (Spike in I-7):** ob macOS beim Zugriff des Kernels (Kindprozess der App) und der Agenten (Claude Code,
  T3) auf den iCloud-Ordner nachfragt; ob die Versionen in `.kevcad/git` die iCloud vertragen; was „Mac-Speicher
  optimieren“ mit ausgelagerten Dateien macht. Die Mac-App braucht dafür ein Profil mit iCloud-Berechtigung
  (`tools/signatur.sh`, Schlüssel über `asc-mit-schluessel`).
- **Umzug** von `~/Documents/Kev CAD` (rund 1,1 GB, davon 1 GB Scans) erst nach Kevins Ja.

## 7. Budgets

| Was | Ziel |
|---|---|
| Drehen am iPad (134 Teile, iPad Pro M2) | 120 Bilder/s, keine Pause über 50 ms |
| Stift bis Strich im Bild | unter 20 ms (Vorhersage, ProMotion 120 Hz) |
| Werkzeugkranz nach Doppeltippen | unter 50 ms |
| Kopplung: Kamera folgt am anderen Gerät | unter 50 ms im WLAN (Median), unter 150 ms über Tailscale |
| Geändertes Teil am iPad | höchstens 100 ms nach dem Mac |
| Start bis bedienbar | App unter 1 s, Verbindung zum Mac unter 1 s im WLAN |
| Wort erscheint als Text | unter 0,6 s (SpeechAnalyzer auf dem Gerät) |
| Feedback-Paket beim Agenten | unter 1 s nach dem Senden (wie am Mac) |
| Übertragung je unverändertem Lauf | unter 50 KB je Gerät (`delta-1` wie am Mac) |

Gemessen wird mit Selbsttests im iPad-Simulator; Bildrate, Stift und Latenz misst erst das echte Gerät (I-10).

## 8. Pakete

| Paket | Inhalt | hängt ab von | Stand |
|---|---|---|---|
| I-0 Plan und Regel | dieser Plan, Paritätsregel in CLAUDE.md, Hinweis an den Thread „KEV Cad Optimize“ | – | fertig |
| I-1 Kern für iPadOS | KevCADCore, KevCADWire und Viewport übersetzen für iPadOS (Simulator und Gerät), Plattform-Schicht `KevCADCore/Plattform/`, Mac unverändert | – | fertig: iPad-Simulator und -Gerät bauen, 474 Kern-Tests im iPad-Simulator grün; am Mac 479 Swift-Tests und 1267 Kernel-Tests grün, Testbau gut |
| I-2a Kernel mit mehreren Geräten | Kernel nimmt mehrere Verbindungen an (Regeln in Abschnitt 3), Antworten an die fragende Verbindung, gezielte Anfragen an das aktive Gerät, `HELLO_APP.geraet`, `AKTIV`, `SETTINGS.anlass`; PROTOCOL.md „I-2 Mehrere Geräte“, `kernel/tests/test_mehrere_geraete.py` | – | fertig (Tests grün) |
| I-2b Eingang und Kopplung | Eingang fürs iPad in der Mac-App (Network.framework, TLS mit Schlüssel je Gerät wie in VoiceBridge, Bonjour `_kevcad._tcp`), reicht Rahmen an den Kernel durch; Kopplung per QR mit Geräteliste und Widerruf; Verbindung im Kern über Unix-Socket oder TLS; Mac-App meldet `geraet` und `SETTINGS.anlass` | I-1, I-2a | offen |
| I-3 iPad-App | Ziel `KevCADPad` in `app/project.yml` (iPadOS 26, `de.upvis.kevcad.ipad`), gemeinsame Oberfläche übersetzt, Mac-Hülle nach `Mac/`, Verbindung (Suche, QR), Viewer mit Fingergriffen, Gliederung, Kacheln, Laufanzeige, Befunde, Demo ohne Kernel, Testvariante im Simulator, Selbsttest | I-1, I-2b | offen |
| I-4 Stift und Werkzeugkranz | Schweben, Auswahl, Zeichnen im Raum mit Vorhersage, Strichfarben, Werkzeugkranz (auch am Mac mit Q), Befehlskatalog mit Auslöser je Gerät und Paritätstest | I-3 | offen |
| I-5 Sprechen am iPad | SpeechAnalyzer, eine Uhr, Paket wie am Mac (mit `geraet` und Farbe), Postausgang, Daumenleiste | I-3, I-4 | offen |
| I-6 Live-Kopplung | Gemeinsame und Eigene Ansicht, Führung, Live-Striche, Agent spricht das aktive Gerät an, Lagebild je Gerät | I-2b, I-3 | offen |
| I-7 iCloud | Spike (Zugriff, Versionen, Auslagern), Ordner der App, Zwischenspeicher draußen, Projektliste am iPad, Umzug nach Kevins Ja | I-3 | offen |
| I-8 Volle Parität | Prüfliste in Abschnitt 9 abarbeiten | I-3 | offen |
| I-9 Verteilung und Prüfung | TestFlight automatisch aus main (höchstens stündlich), Selbsttests im iPad-Simulator über `tools/fern.sh`, Paritätsprüfung in jedem Testbau | I-3 | offen |
| I-10 Abnahme | Kevin am echten iPad: Gesten, Stift, Latenz, Kopplung; Learnings in Plan, Skill und Regeln | alle | offen |

### Offene Stellen auf dem iPad nach I-1

Im Code mit „iPad: folgt in I-x“ markiert; jedes Paket arbeitet seine Zeilen ab.

| Paket | Stelle |
|---|---|
| I-2b | `KernelProcess.start` meldet auf dem iPad einen Fehler, `AppController.start()` endet dort; die Verbindung braucht den Weg über TLS (der Socket-Pfad im iPad-Container wäre ohnehin zu lang, 165 statt 104 Byte) |
| I-3 | iPad-Eingabeebene in `BlenderNavigation.swift` meldet nur die Größe (bis dahin gelten die Gesten der Viewport-Kopie, mit Rollen und Auswahl im Paket statt über `onClick`); kein Kontextmenü, kein Ziffernblock; `Tastenbelegung.befehl(keyCode:)` kennt nur Mac-Tastencodes; `beiEsc` ohne Wirkung. Punkte der Eingabeebene zählen wie am Mac von unten links |
| I-4 | Stift (Schweben, Zeichnen, Doppeltippen) |
| I-5 | `SprachSteuerung`: Mikrofon, Bedienung, ↩ einer Hardware-Tastatur; auf dem iPad hört gleich Apples Erkennung zu, Wortlaut gibt es nur am Mac |
| I-7 | `AppInfo.projectsDirectory` ist der Dokumente-Ordner der App; Ordnernamen unterscheiden auf dem iPad Groß- und Kleinschreibung (`ProjectLocator.uniqueFolder`) |
| I-8 | Video (`AnimationVideo`, ffmpeg nur am Mac), Drucken (`exportDrucken`, `BlattDruck`, `ExportDrucker`), Bambu Studio, `DruckerSchluesselbund.speichern`, „Im Finder zeigen“ (wird Teilen), Zukauf (Downloads-Ordner) |
| I-9 | Selbsttests: `SprachSelbsttest`, Treffertest in `AppController+SelfTest`, Fensterbild in `AppController+Flaeche` |

Bewusst ohne Gegenstück: Die Signaturprüfung der Spiegel-Gegenstelle und der Spiegel-Socket (MIRROR.md) gibt es nur am Mac.
Tests, die auf dem iPad nicht laufen können (Prozesse, ffmpeg, NSPrintInfo, Unix-Socket des Kernels), sind dort mit
`#if os(macOS)` ausgenommen; `tools/ipad-bau.sh test` fährt die übrigen im iPad-Simulator.

Reihenfolge: I-1 und I-2a, dann I-2b und I-3 nebeneinander (Mac-Eingang gegen iPad-Hülle), dann I-4 bis I-7; I-8 läuft
mit jedem Paket mit. Höchstens zwei Agenten zugleich mit voller Denktiefe (Wochenlimit, siehe Gedächtnis).

## 9. Parität im Alltag

**Regel für jede Änderung** (steht auch in CLAUDE.md): Funktion, Fehlerbehebung, Text, Gestaltung und Tests gelten für Mac
und iPad im selben Schritt. Gemeinsamer Code macht das meist von selbst. Wer eine Hüllen-Datei ändert (`Mac/` oder
`KevCADPad/`), zieht das Gegenstück im selben Commit nach oder trägt eine Ausnahme mit Grund in `paritaet.json` ein und
nennt sie Kevin. Geht etwas auf einem Gerät grundsätzlich nicht (Wortlaut-XPC, Finder), steht das im Code und in
`paritaet.json`.

**Prüfliste der Funktionen** (Stand iPad; wird mit jedem Paket nachgezogen):

| Bereich | Mac | iPad |
|---|---|---|
| Viewer: drehen, verschieben, zoomen, Standardansichten, Projektion, Isolieren, Ausblenden | ja | I-3 |
| Auswahl, Elementmodus, Rahmen, Kontextmenü | ja | I-3, Stift I-4 |
| Messen mit Vorschau | ja | I-3, Schweben I-4 |
| Darstellung, Schnitt, Explosion, Röntgen | ja | I-3 |
| Kameras, Bildschirmfoto, Video, Navigation aufnehmen | ja | I-8 |
| Gliederung mit Umbenennen | ja | I-3 |
| Startübersicht, Projekt neu, öffnen, umbenennen | ja | I-3, iCloud I-7 |
| Kacheln: Druck, Zeichnung, Bauplan, Stückliste, Zuschnitt, Material, Animation, Statik, Simulation, Rendern, Versionen, Details, zweite Ansicht | ja | I-3 (Fläche), I-8 (Inhalte) |
| Sprechen mit Zeigen und Zeichnen | ja | I-5 |
| Werkzeugkranz, Strichfarben | I-4 | I-4 |
| Kopplung mit dem anderen Gerät | I-6 | I-6 |
| Export STEP, STL, 3MF, GLB; Dokumente als PDF | ja | I-8 (Teilen-Blatt) |
| Drucker (Bambu) | ja | I-8 (über den Kernel am Mac) |
| Bestand, Lager, Katalog, Zukaufteil per Link | ja | I-8 (Link per Teilen-Blatt aus Safari) |
| Referenzen und Scans | ja | I-8 (Kamera und LiDAR des iPad, Vorbild `ios/KevScan`) |
| Freigaben, Protokoll, Selbsttests | ja | I-8, I-9 |

## 10. Offene Fragen und Risiken

**Entschieden** (Kevin, 06.11.2026: „Zu allem sage ich ja“):

1. Die Projekte ziehen in den iCloud-Ordner um, nach dem Spike in I-7; die Scans bleiben zuerst lokal.
2. TestFlight: Kevin legt den App-Eintrag in App Store Connect an (Anleitung im Chat vom 06.11.2026). Die App-ID
   `de.upvis.kevcad.ipad` („Kev CAD iPad“, Kennung `TL3W2GRCH3`) ist per API angelegt.
3. Der Mac mini wird später Dauer-Host mit Kernel und Agent, damit das iPad auch ohne MacBook arbeitet.

**Risiken**

- Ohne laufende Mac-App kein Kernel: Das iPad zeigt dann den letzten Stand und sammelt Sprechen im Postausgang. Ein
  Dauer-Host (Mac mini, LaunchAgent mit Socket-Aktivierung) behebt das später.
- Jedes Update auf main startet die Mac-App neu: Das iPad muss sich in unter 2 s neu verbinden und den Stand behalten.
- iCloud-Zugriff aus Python und aus den Agenten (Abfragen von macOS) ist ungeprüft, darum der Spike vor dem Umzug.
- Die geteilte Oberfläche ist für Maus gebaut: Trefferflächen, Hover-Hilfen und Kontextmenüs müssen für Touch durchgesehen
  werden (I-3, mit dem Skill `apple-design`).
- Wortlaut (Parakeet) gibt es auf dem iPad vorerst nicht; die Erkennung kann sich anders anfühlen.
- Kein Gerät zum Testen im Simulator für Stift und Schweben: Latenz, Handballen und Doppeltippen prüft erst Kevin am
  echten iPad.
