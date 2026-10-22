# Kev CAD · Live-Ansicht auf dem iPhone (VoiceBridge)

Stand: 21.10.2026. Gemeinsames Vorhaben von Kev CAD und VoiceBridge (`~/Code Experiments/VoiceBridge`, Repo
`UPVIS/voicebridge`). Kevin hat es am selben Abend gestartet („Es müsste eine 3D-Darstellung sein, kein Videofeed, das
ist wichtig“). Damit ist L1 ausdrücklich bestätigt.

| Paket | Zuständig | Stand |
|---|---|---|
| M0 Vertrag | Kev CAD | [MIRROR.md](MIRROR.md) Version 1, mit VoiceBridge abgestimmt; Aufzeichnungen in `samples/mirror-recordings/` |
| M1 Spiegel-Dienst | Kev CAD | fertig und installiert: KevCADWire (macOS/iOS, Wurzelpaket), Spiegel-Dienst in der App, Sitzungskennung der Agenten, `mirror_sim.py`, `mirror-fixtures/`; Kugelschieber voller Stand in 78 ms |
| M2 Transport | VoiceBridge-Sitzung | WLAN fertig und installiert (21.10.2026, VoiceBridge 0bfcc4a): mirror.sock, Hülle `cad` mit Vorrang an gekoppelte iPhones, WATCH-Miete solange die Ansicht offen ist. Unterwegs über CloudKit (Zone `KevCadLive`, Miete, Netzblöcke, signierte Befehle) gebaut und am Mac geprüft, unterwegs noch nie ausprobiert. Echttest auf Kevins iPhone steht aus (WLAN und unterwegs) |
| M3 iPhone-Ansicht | VoiceBridge-Sitzung | fertig und installiert (KevCADWire, 59 Bilder/s mit 112 Teilen, 0 im Leerlauf). Einstieg: Chat einer Sitzung öffnen, die in Kev CAD arbeitet, Pille „CAD“ neben ihrem Chip (seit 22.10.2026 sichtbar). Noch offen: `kamera.aspect` und `CMD einpassen` (spätere v1-Ergänzungen) |
| M4, M5 | gemeinsam | danach |
| Freigabe vom iPhone | Kev CAD und VoiceBridge-Sitzung „Live Control App Modernisierung“ | Kev-CAD-Seite fertig (MIRROR.md 1.1, 22.10.2026): FREIGABE, CMD `freigabe`, FREIGABE_ENDE, Prüfung der Gegenstelle über Signatur; VoiceBridge-Seite fertig (22.10.2026, gepinnt auf KevCADWire 4e040ef, cadcheck 140 Prüfungen), installiert. **Echttest bestanden am 22.10.2026:** Anfrage 18:10:16 (Kev CAD Build 374), nach 8 s als Mitteilung über iCloud, Kevin gibt auf dem iPhone frei, Entscheidung über WLAN 18:23:55, im Katalog „frei“ 18:23:58 (Testeintrag `voicebridge-test`, danach gelöscht) |

## Ziel

Die 3D-Szene von Kev CAD erscheint live in der VoiceBridge-App auf dem iPhone, so wie sie sich am Mac aufbaut und
ändert. Kevin dreht sie dort selbst, blendet Teile ein und aus, fokussiert, isoliert, wählt aus und arbeitet über den
Chat der Sitzung mit dem Agenten weiter. Beide Seiten bleiben synchron: was am iPhone passiert, sieht der Mac und
umgekehrt. Der Modus steht von selbst bereit, sobald ein Agent in Kev CAD arbeitet.

**Fertig, wenn:**

1. Ein Agent baut am Mac den Kugelschieber; im VoiceBridge-Chat dieser Sitzung erscheint ohne Zutun die Ansicht „CAD“,
   die Teile kommen dort genauso Stück für Stück an wie im Viewer.
2. Kevin dreht mit einem Finger, verschiebt mit zwei, zoomt mit Pinch, flüssig mit 120 Bildern je Sekunde, auch wenn das
   Netz kurz hakt.
3. Langes Drücken auf ein Teil: Auswählen, Ausblenden, Isolieren, Fokussieren. Die Teileliste als Blatt von unten mit
   Schaltern je Baugruppe. Am Mac passiert dasselbe sichtbar mit.
4. Kevin wählt am iPhone die Lenkrolle aus und diktiert „mach die Rolle 20 mm größer“; der Agent weiß, welches Teil
   gemeint ist, und der neue Lauf erscheint auf beiden Geräten.
5. Im WLAN unter 100 ms von der Änderung am Mac bis zum iPhone (Kamera, Auswahl, Sichtbarkeit); unterwegs über iCloud
   mit einigen Sekunden Verzug, aber dennoch bedienbar.

## Was schon da ist

| Baustein | Wo | Nutzen |
|---|---|---|
| Renderer OCCTSwiftViewport | Kev CAD, Commit `d9984ad` | Läuft auch auf iOS 18 und visionOS, kennt nur `ViewportBody`-Listen, hängt an keinem Kernel. Das iPhone kann **denselben Renderer** benutzen: gleiche Darstellung, keine zweite Grafik |
| Geometrie im Protokoll | Kev CAD `PROTOCOL.md` (`PART_UPSERT`) | Körper je Teil als fertige Vertex- und Indexpuffer mit Flächen- und Kantennummern, genau das Format des Renderers |
| Direkter Kanal im WLAN | VoiceBridge `BridgeServer`/`BridgeClient`, Bonjour `_voicebridge._tcp`, TLS plus eigener Handschlag | Verschlüsselt, gekoppelt; Nachrichten bis 512 KB, Blöcke zu 128 KB, `features` für ältere Gegenstellen |
| iCloud-Weg | VoiceBridge CloudKit, Bereiche `Agents`, `AgentsLive` | Funktioniert in jedem Netz, Verzug 1–3 s |
| Chat je Sitzung, Ansichtswahl | VoiceBridge `AgentPresentation`, `AgentFeedView` („Meldungen / Live / Unteragenten“) | Vierte Ansicht „CAD“ passt in dieses Muster |
| Hinsehen mit Mietzeit, Abgleich in Teilen | VoiceBridge `SessionTranscripts`, `TranscriptPublisher`, `AgentRelay` | Der Mac schickt nur, solange das iPhone hinsieht, und nur Änderungen |
| Rückweg zum Agenten | VoiceBridge `AgentCommand` → `AgentDesk` → `SessionAgent` (Nachricht in die Sitzung) | Diktat und Text vom iPhone kommen schon in der richtigen Sitzung an |
| Sitzungen kennen | VoiceBridge `AgentDesk` (laufende Sitzungen samt Arbeitsordner), Kev CAD Kernel (`agent`-Zustand, offenes Projekt) | Grundlage für „startet von selbst“ |

## Entscheidungen (Vorschlag)

| Nr. | Entscheidung | Begründung |
|---|---|---|
| L1 | **Szene spiegeln, kein Videostrom.** Das iPhone bekommt die Netze einmal je Teilstand und rendert selbst; danach laufen nur kleine Zustände (Kamera, Auswahl, Sichtbarkeit, Hervorhebung, Maße, Befunde) | Drehen bleibt am iPhone flüssig und unabhängig vom Netz; ein Videostrom wäre träge und verbraucht Akku und Datenvolumen |
| L2 | **Kev CAD liefert, VoiceBridge transportiert.** Die Kev-CAD-App bietet einen lokalen Spiegel-Dienst (Unix-Socket im Support-Ordner, gleiches Rahmenformat wie das Kernel-Protokoll); die VoiceBridge-Mac-App verbindet sich, sobald eine Sitzung Kev CAD nutzt, und reicht die Nachrichten über ihren verschlüsselten Kanal weiter | Keine zweite Kopplung, kein zweiter Netzwerkdienst; Sicherheit und Erreichbarkeit bleiben in VoiceBridge |
| L3 | **Netze kompakt und zwischengespeichert:** Positionen quantisiert, Normalen komprimiert, gepackt mit LZFSE, Schlüssel = Inhalts-Hash je Teil. Das iPhone hebt Netze je Projekt auf und fragt nur Fehlendes an | Große Baugruppen (Outdoorküche) gehen beim ersten Mal in Blöcken, danach nur Änderungen |
| L4 | **Zwei Kamera-Arten:** „Mitfolgen“ (iPhone zeigt die Mac-Kamera, eigenes Drehen übernimmt sie) und „Frei“ (eigene Kamera). Auswahl, Sichtbarkeit und Isolieren laufen immer in beide Richtungen | Zwei Leute oder zwei Geräte sollen sich nicht ständig die Ansicht wegdrehen |
| L5 | **Bedienung wie am Mac, für Finger übersetzt:** ein Finger dreht (Drehteller um Z wie in Blender), zwei verschieben, Pinch zoomt, Doppeltipp fokussiert, langes Drücken öffnet das Teilemenü, Ansichtswürfel für vorn, oben, rechts, iso | Gleiches Gefühl wie am Mac, kein Einrasten |
| L6 | **Auswahl als Kontext für den Agenten:** Diktat oder Text aus der CAD-Ansicht trägt die aktuelle Auswahl mit („Auswahl: Rollwagen/Lenkrolle 1“); da die Auswahl auch am Mac ankommt, sieht der Agent sie zusätzlich in `status` | Kevin muss Teile nicht beim Namen nennen |
| L7 | **Unterwegs über iCloud:** Netze als CKAsset, Zustand als kleiner Datensatz in einem eigenen Bereich (wie `AgentsLive`), nur während das iPhone hinsieht | Bedienbar mit einigen Sekunden Verzug, ohne eigenen Server (in VoiceBridge am 29.09.2026 so entschieden) |
| L8 | **Gemeinsamer Vertrag** [MIRROR.md](MIRROR.md) im Kev-CAD-Repo (Nachrichten, Felder, Versionen, Epoche, Vorrang, Vertrauensgrenze); beide Projekte testen gegen dieselben Testdateien | Zwei Repos, zwei Agenten, ein Vertrag |

## Arbeitspakete

| Paket | Repo | Inhalt |
|---|---|---|
| M0 Vertrag | Kev CAD | `MIRROR.md`: Szene (Teilebaum, Netze, Farben, Materialien), Zustand (Kamera, Auswahl, Sichtbarkeit, Isolieren, Hervorhebung, Maße, Prüfbefunde, Laufstand), Befehle vom iPhone, Testdateien |
| M1 Spiegel-Dienst | Kev CAD | KevCADCore: plattformneutrales Teilziel für Protokoll und Szene (damit das iPhone dieselben Typen nutzt), Spiegel-Dienst in der App, Befehle über `AppActions`, Tests |
| M2 Transport | VoiceBridge | Mac: Verbindung zum Spiegel-Dienst, neue Nachrichtentypen mit eigener Drossel (Kamera bis 30 je Sekunde, Netze in Blöcken), iCloud-Weg für unterwegs |
| M3 CAD-Ansicht | VoiceBridge | iPhone: Ansicht „CAD“ im Sitzungschat mit OCCTSwiftViewport, Gesten, Teileblatt, Teilemenü, Mitfolgen/Frei, Netz-Speicher |
| M4 Agent | beide | Auswahl als Kontext in Diktat und Text, MCP-Werkzeug zum Öffnen der Ansicht, Hinweis im Kev-CAD-Skill |
| M5 Von selbst | beide | Kev CAD meldet „Agent aktiv“, VoiceBridge blendet die Ansicht im Chat dieser Sitzung ein, Mitteilung auf Wunsch |

Reihenfolge: M0 zuerst, danach M1 und M2/M3 parallel; M4 und M5 zum Schluss. Abstimmung mit der VoiceBridge-Sitzung über
den Vertrag; Änderungen am Vertrag nur gemeinsam.

## Zu beachten

- Auf dem iPhone nur bei Bedarf rendern (Gesten, Kamerafahrten, Zustandswechsel), im Leerlauf keine Rechenzeit, Pause
  im Hintergrund und bei „Bewegung reduzieren“. Die CAD-Ansicht hat einen eigenen Zustand und löst keine Neuberechnung
  des Chat-Feeds aus. Netze außerhalb des Bildes bei Speicherwarnung verwerfen, Plattenspeicher mit Obergrenze und LRU
  (etwa 200–300 MB). Eine Messung wie der Rollmesser von VoiceBridge für Gesten (Vorgaben von VoiceBridge).
- VoiceBridge hat strenge Regeln für Kopplung und Verschlüsselung; der Spiegel-Dienst nimmt nur lokale Verbindungen an
  (Socket mit Dateirechten nur für Kevin), nichts lauscht im Netz.
- Auf dem MacBook mit 16 GB nur ein `xcodebuild` gleichzeitig (Notiz aus VoiceBridge vom 20.10.2026).
- iOS-Mindestversion der VoiceBridge-App ist 26, OCCTSwiftViewport verlangt iOS 18: passt.

## Offene Fragen an Kevin (wenn es losgeht)

1. Nur iPhone oder auch iPad (größere Fläche, Stift)?
2. Muss es unterwegs flüssig sein (dann doch ein Relay-Dienst) oder reichen dort einige Sekunden Verzug?
3. Kamera beim Öffnen: „Mitfolgen“ oder „Frei“? Vorschlag: Mitfolgen, bis Kevin selbst dreht.
