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
| Lange drücken | Kontextmenü am Teil (dieselben Einträge wie am Mac: Zentrieren, Ausblenden, Lokale Ansicht, Messen, Maße, Elementmodus); wählt das gedrückte Teil aus | Rechts klicken (wählt nicht aus, wie Blender) |
| 2 Finger tippen | Rückgängig (Ansicht, Auswahl, Sichtbarkeit) | ⌘Z |
| 3 Finger tippen | Wiederholen | ⇧⌘Z |
| vom linken bzw. rechten Rand wischen | Leiste links (Gliederung) bzw. rechts (Eigenschaften); zum Rand hin wischen schließt sie | ⌘1, ⌘2 |
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

Vorbild ist das Kreismenü von Feather 2.0 (Kevin, 06.11.2026, Reel von feather_3d: „die UI für den Stift am Ende,
insbesondere das zirkuläre Menü, finde ich ziemlich geil als Idee“). Dort erscheint an der Stiftspitze eine kleine,
milchig durchscheinende Scheibe; innen liegen weiche Farbpillen um die aktuelle Farbe, am Rand kleine Symbole. Für einen
Wert verwandelt sie sich fließend in ein Ziffernblatt mit Teilstrichen, der Stift kreist am Rand, und die Mitte zeigt
den Wert dunkel hinterlegt („28/32“, „0.1x“). Neben der Scheibe klappt bei Bedarf ein schmales Blatt mit Reglern auf.

```
                         Sprechen / Senden
              Agent         ·  ●  ·        Ansichten
                         ●         ●
          Kacheln      ●   ( Farbe )  ●    Darstellung        innen: Strichfarben als Pillen,
                         ●         ●                         Mitte: aktuelle Farbe bzw. Wert
              Sichtbarkeit  ·  ●  ·        Messen
                              …
```

- **Form:** runde Scheibe, rund 170 pt, an der Stiftspitze (Schwebeposition), sonst am letzten Berührpunkt. Material
  milchig durchscheinend in den Graphit-Farben mit weichem Schatten; kein Rahmen, keine Beschriftungen außer dem Wert in
  der Mitte und einem kurzen Namen beim Darüberfahren.
- **Innen:** die Strichfarben Rot, Gelb, Grün, Blau, Weiß als weiche Pillen um die aktuelle Farbe. Kevin kann sie beim
  Sprechen nennen („die rote Linie“), das Paket trägt sie.
- **Außenring:** acht kleine Symbole. Oben **Sprechen / Senden** (ohne Sitzung startet es, in der Sitzung schickt es ab;
  „Doppeltippen, nach oben“ ist die Hauptschleife), dann **Ansichten** (Vorne, Oben, Rechts, Iso, Gegenseite, Alles
  einrahmen, Zweite Ansicht), **Darstellung** (wie Z am Mac), **Messen**, **Sichtbarkeit** (Isolieren, Ausblenden,
  Alles einblenden, Teil oder Element), **Kacheln** (Druck, Zeichnung, Bauplan, Stückliste, Animation, Statik,
  Versionen, Rendern), **Agent** (Neu rechnen, Prüfen, Bild an den Agenten, Meilenstein) und **mehr** (…). Ein Feld mit
  Unterpunkten öffnet einen zweiten Ring.
- **Drehregler:** Für stufenlose Werte verwandelt sich die Scheibe in ein Ziffernblatt mit Teilstrichen; der Stift
  kreist am Rand, die Mitte zeigt den Wert dunkel hinterlegt. Gilt für Explosion („40 %“), Schnittebene („120 mm“),
  Zeit der Animation („2,4 s“), Strichbreite, Deckkraft beim Röntgen und den Zoom der zweiten Ansicht. Später auch für
  Maße: Teil antippen, Parameter wählen, drehen („Breite 120 → 140 mm“, ein Teilstrich ein Millimeter), der Kernel
  rechnet live über `run(params)`. Das ist ein Feld wie in den Eigenschaften, kein Manipulator (V7 bleibt).
- **Wählen:** Tippen auf das Feld oder in die Richtung wischen, auch ohne hinzusehen (wie Blenders Kreismenüs).
  Abheben übernimmt, Wischen in die Mitte oder ein Tipp daneben bricht ab. Übergänge morphen (Feld → Wert →
  Drehregler) statt hart zu wechseln.
- **Seitenblatt:** Wo es mehr als einen Wert gibt (Darstellung, Licht beim Rendern), klappt neben der Scheibe ein
  schmales Blatt mit Reglern auf, wie Feathers „Adjust“.
- **Pencil Pro:** Drücken öffnet, Rollen dreht den Regler ohne Kreisen, Haptik meldet jeden Teilstrich und jedes Feld.
  Pencil 2 (Kevins iPad): Doppeltippen öffnet, Teilstriche nur sichtbar.
- **Am Mac:** Q öffnet denselben Kranz an der Maus; der Drehregler folgt dem Mausrad oder dem Kreisen der Maus.
- Die Felder kommen aus dem Befehlskatalog; Kevin kann sie später umlegen.

### 4.5 Sprechen

1. **Starten:** Daumenleiste „Sprechen“, Kranz oben, ein Stiftstrich oder V auf der Tastatur. Der rote Rahmen zeigt, dass
   zugehört wird (wie am Mac).
2. **Währenddessen:** reden, mit dem Stift zeigen und zeichnen, mit den Fingern drehen. Alles läuft auf einer Uhr, die
   Wörter erscheinen live als Text.
3. **Abschicken:** Kranz oben, Daumenleiste „Senden“ oder ↩. **Verwerfen:** X am Rahmen oder Esc.
4. **Erkennung** auf dem Gerät mit Apples SpeechAnalyzer (am Mac der Rückfall hinter Wortlaut). Wortlaut mit Parakeet
   läuft nur am Mac. **Geprüft am 07.11.2026 (I-7):** Parakeet ginge aufs iPad, der Einbau ist aber kein kleiner Tausch.
   - Wortlaut (`~/Code Experiments/VoiceRecorder`, `Sources/WortlautSprache/Speech/ParakeetEngine.swift`) nutzt FluidAudio
     0.17.4 (Apache-2.0, läuft ab iOS 17) mit Parakeet Ultra (603 MB) und TDT v3 (461 MB) als Core ML auf der Neural
     Engine; Modell CC-BY-4.0, kommerziell erlaubt mit Namensnennung. Apps mit Parakeet über FluidAudio gibt es im App Store.
   - Deutsch (FLEURS, Wortfehler): Ultra 3,6 %, v3 4,1 bis 5,9 %, Apple 6,3 %. Echtes Streaming auf Deutsch gibt es nur
     mit einem schwächeren Modell (rund 10 %); Wortlaut erkennt stattdessen alle 0,4 s den ganzen Satz neu.
   - Versuch am MacBook M2 Pro (ähnlicher Chip wie Kevins iPad), drei deutsche Befehlssätze und 20 s Ton: v3 83 bis 107 ms
     je Satz, Ultra 79 bis 101 ms, Apple 159 bis 201 ms; je ein bis drei falsche Wörter bei allen dreien (STEP wurde „Deck“
     bzw. „Stepp“). Speicher alle drei geladen: 116 MB Footprint. Erstes Laden unter Last 72 s (v3) bzw. 121 s (Ultra), auf
     dem iPhone 16 Pro Max laut FluidAudio 3,4 s.
   - Einbau hieße: FluidAudio in KevCADCore (verlangt Swift-Tools 6.2), Mikrofonaufnahme fürs iPad, Wortlauts
     `Dauerhoerer` und `Satzschneider` portieren (rund 39 KB Code), 460 bis 600 MB Modell mitliefern oder nachladen.
   - **Empfehlung:** SpeechAnalyzer behalten. Parakeet als eigenes Paket vormerken (Klasse `ParakeetErkennung` hinter
     dem bestehenden Erkenner), erst wenn die Erkennung am iPad im Alltag stört; vorher am echten iPad messen (erster Start,
     Wartezeit, Speicher).
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

Stand nach dem Spike vom 07.11.2026 (I-7). Gemessen an diesem MacBook (macOS 26) mit einem kleinen Testordner in iCloud
Drive; das echte iPad und ein zweiter Mac fehlten im Versuch, was dort gilt, ist als „nicht gemessen“ markiert.

**Ergebnis des Spikes**

| Frage | Ergebnis |
|---|---|
| Fragt macOS nach, wenn Kernel oder Agent in iCloud Drive lesen und schreiben? | Nein. Prozesse ohne Sandbox (Kernel, Shell der Agenten; geprüft ohne Festplattenvollzugriff) lesen und schreiben `~/Library/Mobile Documents/com~apple~CloudDocs` ohne Abfrage. |
| Tempo beim Lauf | Wie lokal: 200 × model.py atomar ersetzen 99 gegen 84 ms, 300 Dateien je 4 KB 44 gegen 46 ms, Git mit 20 Commits 1,9 gegen 2,0 s. Der Lauf selbst rechnet ohnehin im Speicher. |
| Dateiwächter des Kernels (mtime alle 250 ms) | Geht: Schreiben ändert mtime wie lokal. Auslagern und erneutes Laden ändern mtime nicht, lösen also keinen Lauf aus. |
| Ausgelagerte Dateien („Mac-Speicher optimieren“) | `brctl evict` macht model.py „dataless“ (`SF_DATALESS`, Größe bleibt sichtbar). Lesen lädt sie still nach: 2,5 s unter Last, Python merkt nichts. Ohne Netz scheitert dieses Lesen (nicht gemessen); Abhilfe: Ordner „Kev CAD“ im Finder und in der Dateien-App auf „Immer behalten“ (Heruntergeladen lassen) stellen. |
| Hochladen | Unter Last 1 bis 3 min, bis alle Dateien `isUploaded` sind; danach keine Konfliktkopien. Ein Git-Repo mit 80 kleinen Dateien wird Datei für Datei hochgeladen, ohne Zusammenhang. |
| Ausschlüsse | Namen mit `.nosync` und `.tmp` lässt iCloud aus (`isExcludedFromSync`, Fehler „Excluded From Sync Due To Filename“). Versteckte Ordner (`.kevcad`) werden übertragen. Ein symbolischer Link wird als Link übertragen (`public.symlink`), sein Ziel nicht. |
| Konflikte und Versionen | iCloud legt bei gleichzeitigen Änderungen Konfliktkopien an („model 2.py“) und führt ältere Fassungen über `NSFileVersion`. Mit einem einzigen Schreiber (Kernel am Mac) entstehen keine; ein zweiter Mac oder Schreiben vom iPad in dieselbe Datei würde sie erzeugen (nicht gemessen). |
| Ohne Netz | Nicht gemessen. Lokal vorhandene Dateien gehen am Mac weiter, Änderungen laden später hoch; ausgelagerte Dateien fehlen. |

**Zwei Wege verglichen**

| | Ordner in iCloud Drive („Kev CAD“) | Eigener Container `iCloud.de.upvis.kevcad` |
|---|---|---|
| Mac | `~/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD`, ohne Berechtigung, ohne Änderung an der Signatur | `~/Library/Mobile Documents/iCloud~de~upvis~kevcad/Documents`; die Mac-App (Developer ID, ohne Profil) bräuchte ein Developer-ID-Profil mit iCloud, sonst legt erst das iPad den Ordner an (Container von iOS-Apps wie Procreate erscheinen am Mac ohne die App) |
| iPad | Kevin wählt den Ordner einmal in der Dateien-App, die App merkt sich ein Lesezeichen (`PadOrdner`) | voller Zugriff ohne Wahl, `NSMetadataQuery` für Änderungen |
| Signatur | nichts | Container im Entwicklerkonto anlegen (die App Store Connect API kennt keine iCloud-Container), Fähigkeit iCloud an der App-ID, Berechtigungen in `app/project.yml`; ob `-allowProvisioningUpdates` mit dem Schlüssel (Rolle App-Manager) den Container selbst anlegt, ist ungeprüft |
| Risiko | Lesezeichen kann veralten (Ordner umbenannt): die App erneuert es oder fragt neu | Fehler in der Signatur stoppen TestFlight-Takt und Mac-Update |

**Empfehlung: Ordner in iCloud Drive.** Er trägt ohne Änderung an Signatur und Profilen, der Kernel arbeitet dort wie in
`~/Documents`, und das iPad braucht nur eine einmalige Ordnerwahl. Der Container bringt erst etwas, wenn das iPad ohne Mac
selbst schreibt; dann neu bewerten.

**Was in die iCloud gehört**

- **Mit:** `model.py`, `kevcad.json`, Hilfsdateien neben model.py, `bestand.json`, `druck.json`, `dokumente/`, `output/`,
  `referenzen/` ohne große Rohdaten, `feedback/`, Notizen.
- **Ohne:** `.kevcad/` (Git der Versionen, Versionsbilder, Laufprotokoll, Topologie). Liegt ein Projekt in der iCloud, wird
  `.kevcad` ein Link auf `.kevcad.nosync` daneben (`kernel/src/kevcad_kernel/ablage.py`, beim Öffnen und Anlegen); der Kernel
  arbeitet unverändert über `.kevcad/`. Ein zweiter Mac bekommt nur den Link, der Kernel legt das Ziel dann an. Übersetzte
  Hilfsdateien (`__pycache__`) gehen nach `~/Library/Caches/de.upvis.kevcad/pycache`. Zwischenspeicher des Kernels lagen
  schon vorher unter `~/Library/Caches/de.upvis.kevcad/`.
- **Versionen sichern** (offen): Git in der iCloud ist unzuverlässig (Datei für Datei, halbe Stände auf dem zweiten Gerät).
  Vorschlag: Beim Meilenstein schreibt der Kernel ein `git bundle` als eine Datei ins Projekt (`versionen.bundle`); ein
  anderer Mac stellt die Versionen daraus wieder her. Ebenso ein kleines `vorschau.png` für die Projektliste am iPad
  (die Liste zeigt es schon, wenn es da ist).
- **Schreiben** tut nur der Kernel. Das iPad schreibt in Projektordner nur Eigenes (Feedback, Fotos) in eigene
  Unterordner mit eindeutigen Namen; Konfliktkopien zeigt die Projektliste (`ProjektListe.konfliktKopien`, `NSFileVersion`).
- **iPad ohne Mac:** Projektliste aus dem Ordner (Name, letzte Änderung, „noch in der iCloud“, Konflikte, später Vorschau),
  das letzte Modell aus dem eigenen Zwischenspeicher, Sprechen und Zeichnen im Postausgang. Rechnen und Öffnen gehen nur
  mit dem Mac.

**Prototyp (Schalter, Vorgabe aus)**

- **Mac:** Datei `~/Library/Application Support/de.upvis.kevcad/projektablage.json` mit `{"ort": "icloud"}` (oder
  `{"ordner": "…"}`). Dann legen App und MCP neue Projekte in iCloud Drive › Kev CAD an, ein bloßer Projektname meint diesen
  Ordner. Ohne Datei bleibt alles wie bisher. Öffnen geht wie immer über „Öffnen …“.
- **iPad:** Einstellungen › Kev CAD › „Projekte aus iCloud“. Dann zeigt die Statusleiste „Projekte“; die Liste fragt beim
  ersten Mal nach dem Ordner. Ein Tipp öffnet das Projekt am Mac: Das iPad schickt den Pfad mit `~`
  (`Projektablage.kernelPfad`), der Kernel löst ihn am Mac auf.

**Umzug** (erst nach Kevins Ja; die Scans bleiben lokal):

1. Am Mac den Ordner „Kev CAD“ in iCloud Drive anlegen und im Finder auf „Heruntergeladen lassen“ stellen.
2. Je Projekt kopieren (nicht verschieben) ohne `.kevcad`; dann `.kevcad` nach `.kevcad.nosync` kopieren und den Link
   setzen (oder das Projekt einmal öffnen, der Kernel macht das selbst). `Scans/` bleibt in `~/Documents/Kev CAD`.
3. Prüfen: Prüfsummen aller kopierten Dateien gleich, jedes Projekt öffnet und rechnet, Versionen sind da, nach dem
   Hochladen keine Konfliktkopien.
4. Schalter setzen (`projektablage.json`), „Zuletzt geöffnet“ zeigt danach auf die neuen Orte.
5. Rückweg: Die alten Ordner bleiben zwei Wochen unverändert liegen; Schalter löschen heißt zurück zu `~/Documents/Kev CAD`.
6. Am iPad einmal den Ordner wählen und dort „Heruntergeladen lassen“ setzen.

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
| I-2b Eingang und Kopplung | Eingang fürs iPad in der Mac-App (Network.framework, TLS mit Schlüssel je Gerät wie in VoiceBridge, Bonjour `_kevcad._tcp`), reicht Rahmen an den Kernel durch; Kopplung per QR mit Geräteliste und Widerruf; Verbindung im Kern über Unix-Socket oder TLS; Mac-App meldet `geraet` und `SETTINGS.anlass` | I-1, I-2a | fertig: Kern (`KevCADCore/Netz/`, `KernelConnection.open(netz:)`, `AppController+Kopplung`), Oberfläche (Ablage › iPad koppeln … mit QR-Code, Code kopieren und Geräteliste; auf dem iPad Blatt mit Scanner, Einsetzen und Beispiel, Anzeige oben), Tests `NetzTests` und Kettentest `tools/ipad-kette.sh` |
| I-3a iPad-App-Gerüst | Ziel `KevCADPad` in `app/project.yml` (iPadOS 26, `de.upvis.kevcad.ipad`), gemeinsame Oberfläche übersetzt, Mac-Hülle nach `app/Sources/KevCAD/Mac/`, Beispielmodell ohne Kopplung (`KEVCAD_DEMO_VIEWPORT=kern`), `tools/ipad-bau.sh app`, `starten`, `stoppen` | I-1 | fertig: baut für den iPad-Simulator, startet dort im Graphit-Look mit echtem Metal-Viewer; Mac-Testbau und Swift-Tests grün |
| I-3b Bedienung am iPad | Eingabeebene mit Fingern, Stift, Trackpad und Magic Keyboard (`TouchNavigation.swift`), Kopplung in der Oberfläche, Hinweisleiste und Übersicht mit Gesten (`Tastenbelegung.gesten`), Leertext ohne „Drück V“, Kontextmenü am Teil aus einer Quelle (`Kontextmenue.swift`: NSMenu am Mac, UIContextMenuInteraction am iPad), Rückgängig und Wiederholen für Ansicht, Auswahl und Sichtbarkeit (`AnsichtsVerlauf.swift`; ⌘Z, ⇧⌘Z, 2 und 3 Finger tippen, ↶ ↷ in der Daumenleiste), vom Rand wischen öffnet und zum Rand hin wischen schließt die Leisten (`RandWischen.swift`, `zumRandSchliessen`), Viewer bis unter die Statusleiste (`viewerUeberstand`), „Verwerfen“ am roten Rahmen, Gesten-Tests (XCUITest `KevCADPadUITests`, `tools/ipad-bau.sh gesten`); offen: Bonjour über die Kennung des Mac (I-6) | I-2b, I-3a | Eingabe, Kopplung und Gesten fertig (07.11.2026), Gesten-Tests und Kettentest im Simulator grün; Abnahme am Gerät offen |
| I-4 Stift und Werkzeugkranz | Schweben, Auswahl, Zeichnen im Raum mit Vorhersage, Strichfarben, Werkzeugkranz (auch am Mac mit Q), Befehlskatalog mit Auslöser je Gerät und Paritätstest | I-3 | offen |
| I-5 Sprechen am iPad | SpeechAnalyzer, eine Uhr, Paket wie am Mac (mit `geraet` und Farbe), Postausgang, Daumenleiste | I-3, I-4 | erster Schritt (07.11.2026): Daumenleiste links unten (Sprechen, Pause, Weiter, Senden), Live-Zeile mit Wörtern statt Tasten, Audio-Sitzung fürs Mikrofon, Paket als Nutzlast über die Kopplung (`FEEDBACK_PAKET.nutzlast`, der Kernel legt es ab), Postausgang ohne Mac; offen: Abnahme am Gerät, `geraet` und Strichfarben im Paket (mit I-4), X am Rahmen; Parakeet geprüft (4.5: geht, Einbau groß, vorerst SpeechAnalyzer) |
| I-6 Live-Kopplung | Gemeinsame und Eigene Ansicht, Führung, Live-Striche, Agent spricht das aktive Gerät an, Lagebild je Gerät | I-2b, I-3 | offen |
| I-7 iCloud | Spike (Zugriff, Versionen, Auslagern), Ordner der App, Zwischenspeicher draußen, Projektliste am iPad, Umzug nach Kevins Ja | I-3 | Spike fertig (07.11.2026, Abschnitt 6): Empfehlung Ordner in iCloud Drive statt eigenem Container. Prototyp hinter Schaltern (aus): `projektablage.json` am Mac (App und MCP), `.kevcad` bleibt lokal (`ablage.py`), Projektliste am iPad mit Ordnerwahl, Öffnen über den Mac mit `~`-Pfad; Tests `test_ablage.py`, `ProjektablageTests`. Offen: Kevins Ja zum Umzug, Versionen als `git bundle`, `vorschau.png`, Neu anlegen vom iPad, Test am echten iPad |
| I-8 Volle Parität | Prüfliste in Abschnitt 9 abarbeiten | I-3 | begonnen (07.11.2026): Datei ans Gerät (PROTOCOL.md „I-8 Datei ans Gerät“, `DATEI_REQ`/`DATEI` in Stücken, Fähigkeit `datei-1`, nur Dateien unter den Wurzeln des Kernels); am iPad „Teilen“ statt „Im Finder zeigen“ (`DateiKnopf`, `DateiTeilenKnopf`, `AppSession.dateienTeilen`): Bestand, 3MF statt Bambu Studio, Dokument-Export, Rendern, Drucken-Dialog, model.py in Kopfleiste und Fehlerband; was der Kern nach einer Aktion im Finder zeigen würde (Export, CSV, Video, Referenz), öffnet am iPad das Teilen-Blatt mit Drucken, Dateien, AirDrop. Video aus Animationen am iPad mit AVAssetWriter statt ffmpeg (H.264 bzw. ProRes, im Zwischenspeicher, dann Teilen). Offen: Zeilen I-8 in der Tabelle unten |
| I-9 Verteilung und Prüfung | TestFlight automatisch aus main (höchstens stündlich), Selbsttests im iPad-Simulator über `tools/fern.sh`, Paritätsprüfung in jedem Testbau | I-3 | `tools/ipad-testflight.sh` fertig; Build 1 seit 07.11.2026 in TestFlight (App 6831891464, interne Gruppe „Kevin“); Takt fertig (`tools/ipad-testflight-takt.sh` aus `tools/auto-update.sh`, eigene Arbeitskopie, höchstens stündlich, Testhinweise mit den Änderungen an der App); Paritätsprüfung fertig (07.11.2026: `tools/paritaet.py`, `paritaet.json`, Kurzfassung in `tools/fern.sh testbau` und `tools/ipad-bau.sh`, Tests `tools/test_paritaet.py` in `tools/fern.sh tests`; Befehle ohne iPad-Auslöser vorbereitet, aktiv sobald I-4 sie im Katalog führt); Kern-Tests im iPad-Simulator über `tools/fern.sh ipadtests` (der Mini hat noch keine iOS-Laufzeit, bis dahin hier); offen: iOS-Laufzeit auf dem Mini (Kevins Ja), Selbsttests der Oberfläche im iPad-Simulator |
| I-10 Abnahme | Kevin am echten iPad: Gesten, Stift, Latenz, Kopplung; Learnings in Plan, Skill und Regeln | alle | offen |

### Offene Stellen auf dem iPad nach I-1

Im Code mit „iPad: folgt in I-x“ markiert; jedes Paket arbeitet seine Zeilen ab.

| Paket | Stelle |
|---|---|
| I-2b | `KernelProcess.start` meldet auf dem iPad einen Fehler, `AppController.start()` endet dort; die Verbindung braucht den Weg über TLS (der Socket-Pfad im iPad-Container wäre ohnehin zu lang, 165 statt 104 Byte) |
| I-3 | iPad-Eingabeebene in `BlenderNavigation.swift` meldet nur die Größe (bis dahin gelten die Gesten der Viewport-Kopie, mit Rollen und Auswahl im Paket statt über `onClick`); kein Kontextmenü, kein Ziffernblock; `Tastenbelegung.befehl(keyCode:)` kennt nur Mac-Tastencodes; `beiEsc` ohne Wirkung. Punkte der Eingabeebene zählen wie am Mac von unten links |
| I-4 | Stift (Schweben, Zeichnen, Doppeltippen) |
| I-5 | `SprachSteuerung`: Mikrofon und Bedienung da (Daumenleiste, Audio-Sitzung, Paket als Nutzlast); auf dem iPad hört gleich Apples Erkennung zu, Wortlaut gibt es nur am Mac; Selbsttest Sprache nur am Mac |
| I-7 | `AppInfo.projectsDirectory` ist der Dokumente-Ordner der App, mit dem Schalter „Projekte aus iCloud“ der gewählte Ordner (Prototyp); Ordnernamen unterscheiden auf dem iPad Groß- und Kleinschreibung (`ProjectLocator.uniqueFolder`) |
| I-8 | Video auf Wunsch des Agenten (ANIM_VIDEO_REQ geht ans aktive Gerät; ist das das iPad, sagt die Antwort, dass die Mac-App es rechnet; besser: der Kernel gibt solche Aufträge an den Mac), Drucken mit eigenem Dialog (`exportDrucken`, `BlattDruck`, `ExportDrucker`; bis dahin Drucken im Teilen-Blatt), `DruckerSchluesselbund.speichern`, Zukauf (Downloads-Ordner des Mac; am iPad per Link). Erledigt 07.11.2026: „Im Finder zeigen“ wird Teilen, Bambu Studio wird „3MF teilen“, Video aus der Animationskachel mit AVAssetWriter |
| I-9 | Selbsttests: `SprachSelbsttest`, Treffertest in `AppController+SelfTest`, Fensterbild in `AppController+Flaeche` |
| I-3b (aus I-3a) | Pfeiltasten in der Gliederung, Zoomen mit zwei Fingern in Zoomflächen, Tippen in den Viewer macht ihn nicht zur aktiven Kachel (`viewerKlickBeobachten`), Auswahl erweitern mit Umschalt oder Befehl (Viewer bis unter die Statusleiste: erledigt, nur ohne Kacheln; neben Kacheln bleibt der Streifen) |
| I-7 (aus I-3a) | „Ordner öffnen“ ist ausgeblendet (`presentOpenPanel`; mit dem Schalter wählt die Projektliste den Ordner), ein fehlendes Projekt in der Liste meldet sich nur statt „Entfernen?“ zu fragen |
| I-8 (aus I-3a) | Berichte und Dokument-Export (`ExportSteuerung` nur am Mac, am iPad weder Drucken noch PDF), Referenz- und CAD-Dateien wählen (braucht den Weg vom Gerät zum Mac), Blätter bearbeiten, Protokoll, Lagerkatalog und Zukauf (keine eigene Szene). Erledigt 07.11.2026: Finder und Editor (`AppSession`, `ErrorBanner`, `Kopfleiste`: model.py teilen), Teilen in `BestandAnsicht`, `DruckAnsicht`, `ExportDialog`, `RenderDialog`, `DruckenDialog`; `ZukaufBanner` bleibt am Mac (Datei in dessen Downloads) |
| I-9 (aus I-3a) | alle Selbsttests der Oberfläche; Menüs liegen nur in `Mac/`, iPadOS 26 hätte eine Menüleiste (Rückweg über den Befehlskatalog in I-4) |

Bewusst ohne Gegenstück: Die Signaturprüfung der Spiegel-Gegenstelle und der Spiegel-Socket (MIRROR.md) gibt es nur am Mac.
Tests, die auf dem iPad nicht laufen können (Prozesse, ffmpeg, NSPrintInfo, Unix-Socket des Kernels), sind dort mit
`#if os(macOS)` ausgenommen; `tools/ipad-bau.sh test` fährt die übrigen im iPad-Simulator.

Reihenfolge: I-1 und I-2a, dann I-2b und I-3 nebeneinander (Mac-Eingang gegen iPad-Hülle), dann I-4 bis I-7; I-8 läuft
mit jedem Paket mit. Build 1 steht seit 07.11.2026 in TestFlight (I-9); seitdem kommt jede Änderung an der App von selbst nach, höchstens stündlich (Takt). Höchstens zwei Agenten zugleich mit voller Denktiefe (Wochenlimit, siehe Gedächtnis).

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
| Kameras, Bildschirmfoto, Video, Navigation aufnehmen | ja | Video aus der Animation am iPad (AVAssetWriter, 07.11.2026); Bildschirmfoto und Aufnahme I-8 |
| Gliederung mit Umbenennen | ja | I-3 |
| Startübersicht, Projekt neu, öffnen, umbenennen | ja | I-3, iCloud I-7 |
| Kacheln: Druck, Zeichnung, Bauplan, Stückliste, Zuschnitt, Material, Animation, Statik, Simulation, Rendern, Versionen, Details, zweite Ansicht | ja | I-3 (Fläche), I-8 (Inhalte) |
| Sprechen mit Zeigen und Zeichnen | ja | I-5 |
| Werkzeugkranz, Strichfarben | I-4 | I-4 |
| Kopplung mit dem anderen Gerät | I-6 | I-6 |
| Export STEP, STL, 3MF, GLB; Dokumente als PDF | ja | Teilen-Blatt mit Datei vom Mac (seit 07.11.2026); Dokument-Export und Berichte als PDF I-8 |
| Drucker (Bambu) | ja | I-8 (über den Kernel am Mac) |
| Bestand, Lager, Katalog, Zukaufteil per Link | ja | I-8 (Link per Teilen-Blatt aus Safari) |
| Referenzen und Scans | ja | I-8 (Kamera und LiDAR des iPad, Vorbild `ios/KevScan`) |
| Freigaben, Protokoll, Selbsttests | ja | I-8, I-9 |

## 10. Erfahrungen

- **Simulator unter Last (06.11.2026):** Beim ersten Booten standen rund 30 Prozesse des Simulators im Zustand „U“, die
  Last stieg über 700 und `simctl launch` kam nicht zurück. Herunterfahren und neu booten half; danach dauerte der erste
  Start einer App bis zu drei Minuten. Vor GUI-Tests `uptime` und `ps -Ao stat,comm | awk '$1 ~ /U/'` ansehen.
- **Bonjour hängt ohne Fehler:** Eine Verbindung zu `.service(name:…)` blieb im Aufbau stehen, ohne `.waiting` oder
  `.failed`, als es keinen Dienst unter genau diesem Namen gab. Jeder Weg hat deshalb eine Frist (Bonjour 3 s, Adresse
  5 s); dauerhaft besser ist die Suche über die Kennung des Mac im TXT-Eintrag (offen, I-6).
- **Eingang neu öffnen:** Ein Listener auf demselben Port lässt sich erst öffnen, wenn der alte ganz geschlossen ist
  (`.cancelled`). `IPadEingang` wartet darauf und versucht es sonst kurz erneut (`testNeueKopplungWaehrendDerEingangLaeuft`).
- **Einsetzen statt Einfügen:** Der Knopf des Systems zum Einfügen heißt auf Deutsch „Einsetzen“ (`PasteButton`, ohne
  Abfrage der Zwischenablage); die Anleitung am Mac nennt ihn so. Der Scanner (VisionKit) fehlt im Simulator, das Blatt
  blendet „Code scannen“ dort aus.
- **Kettentest ohne Kamera:** Testvarianten am Mac schreiben mit `KEVCAD_TEST_KOPPLUNG_DATEI` einen Kopplungscode, die
  iPad-App übernimmt ihn in Debug-Bauten über `KEVCAD_PAD_KOPPLUNG`. `tools/ipad-kette.sh` fährt die ganze Strecke und
  baut über MCP ein Modell.
- **TestFlight-Tester je App** (07.11.2026): Apple führt interne Tester je App als eigenen Eintrag; einen Eintrag aus
  Akquise Mobil oder VoiceBridge nimmt die Gruppe von Kev CAD nicht an (409). `tools/ipad-testflight.sh` legt Tester
  deshalb über die Mail-Adresse in der Gruppe an und schickt die Einladung (Regel `apple-app-verteilung.md`).
- **Takt aus eigener Arbeitskopie** (07.11.2026): Die Arbeitskopie des Mac-Updates springt bei jedem neuen Stand auf main
  um; ein iPad-Build darin hätte halb alte, halb neue Dateien. Der Takt baut deshalb in `_cache/kevcad-ipad/takt/src`, und
  das Update startet eine Kopie des Takt-Skripts, damit ein wartender Takt nicht mitten im Lauf umgeschrieben wird.
- **Erzeugte Dateien in frischen Arbeitskopien** (07.11.2026): Das App-Symbol erzeugt `tools/ipad-bau.sh` aus
  `app/icon.svg`, es steht nicht im Git. Build 1 kam aus einer Arbeitskopie, in der es schon lag; der erste Build des
  Takts aus der frischen Kopie scheiterte bei App Store Connect (90023 kein 152-px-Symbol, 90713 kein
  `CFBundleIconName`). `tools/ipad-testflight.sh` ruft seitdem `tools/ipad-bau.sh symbol` vor dem Archiv auf.
- **iCloud am Mac ohne Abfrage** (07.11.2026, I-7): Prozesse ohne Sandbox lesen und schreiben iCloud Drive ohne
  Nachfrage von macOS, auch ohne Festplattenvollzugriff. Container von iOS-Apps (Procreate, Goodnotes) liegen am Mac unter
  `~/Library/Mobile Documents/`, obwohl die App dort fehlt.
- **iCloud überträgt Datei für Datei** (07.11.2026): Ein Git-Repo kommt so als lose Dateien an, Hochladen dauerte unter
  Last 1 bis 3 min. `.nosync` und `.tmp` schließt iCloud aus, ein symbolischer Link geht als Link hinüber. Daraus der Link
  `.kevcad` → `.kevcad.nosync` für Projekte in der iCloud. Prüfen lässt sich das je Datei mit
  `fileproviderctl evaluate <pfad>` (`isExcludedFromSync`, `isUploaded`); `brctl evict` lagert zum Testen aus.
- **Git-Ausschluss für Links** (07.11.2026): Das Muster `/.kevcad/` mit Schrägstrich trifft nur Ordner; ein Link `.kevcad`
  wäre als neue Datei in die Versionen gerutscht. Der Ausschluss nennt deshalb auch `/.kevcad` und `/.kevcad.nosync/`.
- **Paritätsprüfung mit Bestand** (07.11.2026): Im gemeinsamen Code standen 82 Blöcke `#if os(macOS)` ohne `#else`, die
  nicht nur Importe enthalten; 20 davon nannten schon einen Grund. Statt alle nachträglich zu begründen, hält
  `paritaet.lock.json` den Bestand (Prüfsumme je Block) fest; gemeldet werden neue und geänderte Blöcke ohne Grund im
  Kommentar. Eine Marke „iPad: folgt in I-2b“ stand noch nach dem fertigen Paket im Code; solche meldet die Prüfung jetzt
  als veraltet.
- **Mini ohne iOS-Laufzeit** (07.11.2026): Der Mac mini hat Xcode 27, aber keine iOS-Laufzeit für den Simulator (rund
  8 GB; frei waren 17 GB). `tools/fern.sh ipadtests` rechnet deshalb vorerst hier; `tools/fern.sh einrichten ipad` lädt sie
  nach Kevins Ja.
- **Skripte nicht ändern, während sie laufen** (07.11.2026): bash liest ein Skript stückweise. Eine Änderung an
  `tools/fern.sh` während eines Testlaufs ließ ihn nach grünen Tests mit „syntax error“ enden.
- **Dateien des Mac auf dem iPad** (07.11.2026): Pfade, die der Kernel nennt, gibt es nur am Mac; ein `ShareLink` darauf
  (Rendern) ging auf dem iPad ins Leere. Jede Datei, die die Oberfläche weitergibt, geht über `DateiActions`: am Mac die
  Datei selbst, am iPad eine Kopie vom Mac im Zwischenspeicher (Stücke zu 4 MiB, damit Live-Nachrichten dazwischen laufen).

- **Rückgängig über Ruhe statt über Befehle** (I-3b, 07.11.2026): Der Verlauf merkt sich Kamera, Auswahl und Sichtbarkeit,
  sobald der Viewer 0,4 s ruhig ist, statt jeden Befehl einzeln einzutragen. Ein Drehen ist so ein Schritt, und auch
  Ansichten des Agenten lassen sich zurücknehmen. Kameras vergleicht er mit Toleranz (q und −q, Fahrten enden nicht
  bitgleich), sonst wäre jedes angewandte Rückgängig selbst ein neuer Schritt. ⌘Z direkt nach einer Änderung schreibt die
  wartende Änderung erst fest, sonst nähme es den Schritt davor zurück.
- **⌘Z am Mac über die Responder-Kette:** Der Viewer antwortet auf `undo:` und `redo:` (mit `validateMenuItem` für den Titel
  im Menü Bearbeiten). So bleibt das Rückgängig von Textfeldern und Zeichnungsblatt unberührt, ohne das Menü zu ersetzen.
- **Kontextmenü mit nachgeladenen Einträgen:** `UIContextMenuInteraction` fragt die Einträge synchron, der Treffertest ist
  asynchron. Ein `UIDeferredMenuElement.uncached` lädt sie nach dem Treffer; die Vorschau ist ein kleiner Ring am Finger
  (`highlightPreviewForItemWithIdentifier`), nicht der ganze Viewer. Das langes Drücken der Interaktion ersetzt den
  eigenen Recognizer; den Sekundärklick mit Trackpad oder Maus bringt sie gleich mit.
- **UIView hat ein eigenes `gestureRecognizerShouldBegin`:** Eine UIView als Delegate eigener Gesten lässt sich deshalb
  nicht übersetzen („overriding declaration requires an override keyword“); die Regeln der Randgesten sind ein eigenes
  Objekt (`RandRegeln`).
- **XCUITest und das Fenster:** `twoFingerTap()` auf `app.windows.firstMatch` scheitert („unable to compute coordinates
  for gesture“). Der Viewer ist deshalb ein eigenes Element (`viewer`, mit `.allowsDirectInteraction` auch für
  VoiceOver richtig). Zustand für die Tests liefert ein unsichtbarer Text `test.zustand` (`KEVCAD_PAD_UITEST=1`, nur Debug).
- **Schemata fest im Projekt:** Mit einem Testziel legt Xcode die Schemata nicht mehr von selbst an; `project.yml` nennt
  sie (`scheme:` bei KevCAD und KevCADPad, das iPad-Schema mit `KevCADPadUITests` als Test).

## 11. Offene Fragen und Risiken

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
