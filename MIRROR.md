# Kev CAD · Spiegel-Protokoll

Version 1 vom 21.10.2026, mit VoiceBridge abgestimmt; Version 1.1 vom 22.10.2026 (rein additiv: Freigabe vom iPhone,
siehe [unten](#freigabe-vom-iphone-version-11)). Gehört zu [PLAN-IPHONE-LIVE.md](PLAN-IPHONE-LIVE.md). Änderungen
nur gemeinsam mit VoiceBridge: Vertrag, Testdateien und beide Seiten im selben Schritt.

Drei Strecken, ein Inhalt:

```
Kev CAD (Mac, Spiegel-Dienst)  ──Unix-Socket──>  VoiceBridge-Mac-App  ──WLAN direkt / CloudKit──>  VoiceBridge-iPhone
```

Kev CAD spricht nur die erste Strecke. VoiceBridge reicht Kopf und Nutzlast unverändert weiter, in der Hülle `cad`
(siehe „Weiterreichen“). Einheiten mm und Grad, rechtshändig, Z nach oben, wie im Kernel-Protokoll
([PROTOCOL.md](PROTOCOL.md)). Alle Koordinaten sind Weltkoordinaten.

## Verbindung und Vertrauen

- **Kev CAD lauscht**, VoiceBridge verbindet sich. Pfad: `~/Library/Application Support/<bundle-id>/mirror.sock`.
  Die installierte VoiceBridge sucht nur genau `de.upvis.kevcad/mirror.sock`; Testvarianten (`de.upvis.kevcad.test…`)
  und der Simulator nur, wenn VoiceBridge mit ihrem Debug-Schalter läuft.
- macOS begrenzt Socket-Pfade auf 104 Byte (`sun_path`). Der Pfad der installierten App hat 73 Byte; Namen von
  Testvarianten kurz halten.
- Ordner 0700, Socket 0600. Kev CAD prüft die Gegenstelle mit `getpeereid` auf dieselbe UID und trennt sonst sofort.
  Eine Prüfung der Codesignatur ist in Version 1 nicht vorgesehen (Kev CAD ist ad hoc signiert, VoiceBridge mit Team-ID;
  eine einseitige Prüfung wäre später möglich). Seit Version 1.1 prüft Kev CAD die Signatur der Gegenstelle für die
  Freigabe (Abschnitt „Freigabe vom iPhone“): Nur die VoiceBridge-App bekommt `FREIGABE` und darf `freigabe` schicken.
- **Vertrauensgrenze ist VoiceBridge.** VoiceBridge reicht ein `CMD` nur weiter, wenn es von einem gekoppelten iPhone
  kommt: über den direkten Kanal (TLS-PSK plus Handschlag) oder über CloudKit mit Geräte-Unterschrift wie beim
  `AgentCommand`. Kev CAD nimmt `CMD` ausschließlich über diesen Socket an und vertraut ihm. Kev CAD öffnet keinen
  zweiten Eingang für Befehle (kein Netzwerkport, kein HTTP).
- **Der volle Projektpfad verlässt den Mac nicht.** `project.path` steht nur in `HELLO`; VoiceBridge reicht davon nur
  `name` weiter, weder aufs iPhone noch in die iCloud. `SCENE` trägt nur `project.name`.
- Mehrere gleichzeitige Verbindungen sind erlaubt, jede bekommt den vollen Stand.
- Kev CAD kann jederzeit neu starten (Update, Absturz). VoiceBridge verbindet sich neu, sobald der Socket wieder da ist:
  Ordner beobachten oder alle 3 s nachsehen, aber nur, solange laut AgentDesk eine Sitzung Kev CAD nutzt.

## Rahmen

Wie im Kernel-Protokoll: `u32 LE` Länge des JSON-Kopfes, JSON (UTF-8, ein Objekt), `u32 LE` Länge der Nutzlast,
Nutzlast. Obergrenzen: Kopf 16 KB, Nutzlast **64 KB**. Kev CAD teilt Netze selbst in Blöcke, VoiceBridge muss nie
umpacken.

Jeder Kopf hat `type`, `seq` (je Absender und Verbindung ab 1) und `prio`:

| prio | Inhalt | Regel beim Weiterreichen |
|---|---|---|
| `zustand` | Auswahl, Sichtbarkeit, Isolieren, Hervorhebung, Laufstand, Befehle und Antworten | nie verwerfen, Reihenfolge halten, immer vor allem anderen |
| `kamera` | Kamerastand | nur der neueste zählt („latest-only“), höchstens 40 je Sekunde |
| `szene` | Teileliste, Teil dazu oder weg | nie verwerfen, vor Netzen |
| `netz` | Netzblöcke | zuletzt; höchstens zwei Blöcke gleichzeitig unterwegs |

Pflicht für jede Strecke: eine Warteschlange mit diesem Vorrang, damit Netze Kamera und Auswahl nicht ausbremsen. Eine
zweite Verbindung nur für Netze ist eine spätere Option, falls das gemessen nicht reicht.

Unbekannte Felder werden ignoriert; neue optionale Felder sind ohne Versionswechsel erlaubt. Unbekannte `type` werden
verworfen und protokolliert, nicht beantwortet.

## Handschlag, Versionen und Hinsehen

| type | Richtung | Felder |
|---|---|---|
| `HELLO` | VB → KC | `protocol: "kevcad-mirror"`, `version: 1`, `client` (`voicebridge-mac`), `features` (Liste) |
| `HELLO` | KC → VB | `version`, `epoche`, `app_build`, `bundle_id`, `features`, `project` (`path`, `name` oder null), `agents` |
| `AGENTS` | KC → VB | `epoche`, `agents`, bei jeder Änderung, auch ohne Hinsehen |
| `WATCH` | VB → KC | `dauer_s` (Miete, Vorschlag 300), `geraet` (Kennung des iPhones, nur zur Anzeige) |
| `UNWATCH` | VB → KC | – |

- **Versionen:** Kev CAD antwortet immer mit seiner `version`. Kann VoiceBridge sie nicht, trennt VoiceBridge, schreibt
  einen Hinweis ins Protokoll und zeigt auf dem iPhone „Kev CAD zu neu“ bzw. „zu alt“.
- **Epoche:** `epoche` ist eine zufällige Kennung je Programmstart von Kev CAD (16 Hex-Zeichen). Wechselt sie, gilt
  alles Bisherige als überholt (Zustand, `rev`, offene Befehle); der volle Stand kommt neu. Netze nach Hash bleiben
  gültig.
- **Sitzungen:** `agents` ist eine Liste
  `{"session_id": "…", "aktiv": true, "seit": "2026-10-21T21:50:00Z", "taetigkeit": "baut Rollwagen"}`, optional
  `zuletzt` (ISO-Zeitpunkt des letzten verändernden Aufrufs). Kev CAD ist
  **eine** Szene; mehrere Claude-Sitzungen können sie bedienen. `aktiv` hat genau die Sitzung mit dem letzten
  verändernden Werkzeugaufruf (run, view, focus …) der letzten 10 Minuten, alle anderen stehen mit `aktiv: false` in
  der Liste. VoiceBridge zeigt die CAD-Ansicht im Chat jeder gelisteten Sitzung, die aktive zuerst. `session_id` ist
  die aktuelle `CLAUDE_CODE_SESSION_ID` aus der Umgebung des MCP-Brückenprozesses `kevcad`; alte Kennungen nach einem
  Kontowechsel löst VoiceBridge über seine Abstammung selbst auf.
- **Miete:** Ohne gültige Miete schickt Kev CAD nur `HELLO` und `AGENTS`. Nach `WATCH` folgen `SCENE` und `STATE` als
  voller Stand, danach nur Änderungen, bis die Miete abläuft oder `UNWATCH` kommt. Erneuern = `WATCH` noch einmal.
  Die Miete gilt nur für die Verbindung, auf der sie kam: Trennt sich die Verbindung, endet sie. Nach jedem
  Neuverbinden schickt VoiceBridge `WATCH` neu, solange ein iPhone hinsieht.

## Szene

| type | prio | Felder | Nutzlast |
|---|---|---|---|
| `SCENE` | szene | `epoche`, `project` (nur `name`), `run`, `bbox`, `seite` (ab 0), `seiten`, `parts` (Liste Teil dieser Seite, siehe unten) | – |
| `PART` | szene | `epoche`, `op`: `upsert` \| `remove`, `run`, Teil bzw. `name` | – |
| `MESH_REQ` | zustand | `hashes` (Liste) | – |
| `MESH` | netz | `hash`, `format`, `block` (ab 0), `blocks`, `bytes` (Länge gepackt), `roh_bytes` (Länge ungepackt) | Block |

Teil: `{"name": "Rollwagen/Lenkrolle 1/Rad", "hash": "9f3c…", "color": [r,g,b,a], "material": "gummi",
"bbox": {"min": […], "max": […]}, "counts": {"vert": …, "tri": …, "face": …, "edge": …, "epts": …}}`. `color` ist sRGB
wie in `PART_UPSERT`. Während eines Laufs kommen `PART`-Nachrichten in der Reihenfolge, in der der Kernel die Teile
zeigt: Die Szene baut sich auf dem iPhone genauso auf wie am Mac.

Die Teileliste passt bei großen Baugruppen nicht in einen Kopf (Kugelschieber: 112 Teile, 34 KB). `SCENE` kommt deshalb
in Seiten, jede höchstens 16 KB Kopf; `run`, `bbox` und `epoche` stehen in jeder Seite gleich. Der Empfänger ersetzt
seine Teileliste erst, wenn alle Seiten `0 … seiten − 1` da sind.

**Netzformat `kcad-mesh-1`:** die Arrays aus `PART_UPSERT` in dieser Reihenfolge, little-endian, direkt hintereinander:
positions (f32, vert × 3), normals (f32, vert × 3), triangles (u32, tri × 3), tri_face (i32, tri), edge_points
(f32, epts × 3), edge_offsets (u32, edge + 1). Ohne B-Rep-Punkte. Das Ganze als **ein** LZFSE-Strom gepackt und dann in
Blöcke zu höchstens 64 KB geteilt. Der Empfänger hängt die Blöcke in der Reihenfolge von `block` aneinander und
entpackt sie in einem Zug in einen Puffer der Größe `roh_bytes`.

**Wiederholen:** Bleibt ein `MESH_REQ` etwa 10 s unbeantwortet, darf der Empfänger es wiederholen. Kev CAD bedient
doppelte Anfragen still (schickt die Blöcke erneut, ohne Fehler); der Empfänger verwirft Blöcke eines Netzes, das er
schon vollständig hat.

**Hash:** SHA-256 über die ungepackten Arrays genau in der Reihenfolge von `kcad-mesh-1`, die ersten 16 Hex-Zeichen.
Der Empfänger prüft ihn nach dem Entpacken und verwirft das Netz bei Abweichung. Das iPhone behält Netze nach Hash und
fragt mit `MESH_REQ` nur fehlende an.

**Nicht vorab teilen:** Die Teilung großer Teile über 16.000 Dreiecke oder Kantensegmente (Grenze der Pick-ID im
Viewport) macht jede Darstellung selbst, auch das iPhone. Netze gehen immer ungeteilt über die Leitung, sonst stimmen
die Hashes nicht mehr.

Eine kompaktere Form (Positionen 16 Bit, Normalen 8 Bit) ist als `kcad-mesh-q1` vorgesehen, falls Messungen es
verlangen; sie würde über `features` ausgehandelt.

Größen zur Abschätzung (Beelonia-Outdoorküche, 75 Teile, 134.000 Dreiecke): roh 4,8 MB, mit LZFSE 0,82 MB; mit
Innenleben roh 5,7 MB, gepackt 1,0 MB. Das sind 13 bzw. 16 Blöcke. Kevins Kugelschieber mit 63 Teilen ist kleiner.

## Zustand

| type | prio | Felder |
|---|---|---|
| `STATE` | zustand | `epoche`, `rev`, voller Stand mit allen Feldern unten |
| `STATE_DELTA` | zustand | `epoche`, `rev`, nur geänderte Felder, `quelle`: `mac` \| `iphone` \| `agent` |
| `CAMERA` | kamera | `epoche`, `rev`, `kamera`, `quelle` |

| Feld | Inhalt |
|---|---|
| `kamera` | `rotation` (Quaternion x, y, z, w; Kamera → Welt, Blick −Z der Kamera), `pivot` [x,y,z], `distance`, `fov` (Grad), `ortho` (bool), `ortho_scale`, optional `aspect` (Breite / Höhe der Ansicht am Mac; damit zeigt das iPhone beim Mitfolgen auch im Hochformat genau denselben Ausschnitt) |
| `auswahl` | `{"run": 3, "refs": […]}` mit Referenzen wie im Kernel-Protokoll (`Teil`, `Teil#f12`) |
| `verborgen` | Liste Teilnamen |
| `isoliert` | Liste Teilnamen oder null |
| `hervorgehoben` | Liste `{refs, color, label}`, `color` RGBA 0…1 in **sRGB** wie bei den Teilen |
| `darstellung` | `shaded_edges` \| `shaded` \| `wireframe` \| `xray` |
| `schnitt` | null oder `{axis` bzw. `normal`, `offset}` |
| `masse` | Liste `{id, kind, points, text}`, `points` in Weltkoordinaten (mm) |
| `befunde` | Liste Prüfbefunde `{art, teile, schwere, ort, text}` (aus der Prüfung, sobald es sie gibt) |
| `lauf` | `{run, laeuft, schritt, fehler}` |

- `rev` zählt je Epoche hoch. Ein Delta derselben Epoche mit kleinerem `rev` als dem bekannten wird verworfen; ein
  Delta mit fremder Epoche ebenfalls, bis der volle Stand der neuen Epoche da ist.
- Flächen- und Kantenreferenzen in `auswahl` gelten nur für den genannten `run`. Nach einem neuen Lauf schickt Kev CAD
  die gültige Auswahl neu (Teilreferenzen bleiben, wenn das Teil noch existiert) oder leert sie.

## Befehle vom iPhone

| type | prio | Felder |
|---|---|---|
| `CMD` | zustand (Kamera: kamera) | `id`, `op`, `args` |
| `CMD_RES` | zustand | `reply_to`, `ok`, `fehler` (Text oder null) |

| op | args | Wirkung am Mac |
|---|---|---|
| `kamera` | `kamera` (wie oben) | setzt die Kamera am Mac (nur im Modus „Mitfolgen“); **latest-only und ohne `CMD_RES`** |
| `auswahl` | `refs`, `run`, `modus`: `setzen` \| `dazu` \| `weg` | wie ein Klick im Viewer, die Auswahl geht auch an den Kernel |
| `sichtbarkeit` | `mode`: `show` \| `hide` \| `isolate` \| `show_all`, `refs` | wie `VIEW_CMD visibility` |
| `fokus` | `refs` | Zoom auf die Teile |
| `ansicht` | `standard`, `projection` | Standardansicht |
| `darstellung` | `display` | Darstellungsart |
| `einpassen` | optional `refs` (ohne: alles) | Kev CAD passt die Kamera selbst ein, mit eigenen Rändern und eigener Projektion (wie Pos1 bzw. „.“ am Mac) |

Alle Befehle außer `kamera` bekommen ein `CMD_RES`. Die Wirkung kommt als `STATE_DELTA` bzw. `CAMERA` mit
`quelle: "iphone"` an alle zurück. Im Modus „Frei“ schickt das iPhone keine Kamera, alles andere schon.

## Freigabe vom iPhone (Version 1.1)

Kevin am 22.10.2026: Lagerkatalog-Freigaben auch vom iPhone, nicht nur per Klick am Mac. Rein additiv; `version` im
HELLO bleibt 1, Kev CAD nennt im HELLO zusätzlich das Merkmal `freigabe-1`.

**Grundsatz:** Freigeben darf nur Kevin selbst. Eine Antwort im Agenten-Chat oder eine von einem Agenten weitergegebene
Nachricht zählt nie. Die Freigabe vom iPhone läuft deshalb **am Agenten vorbei**, direkt zwischen der VoiceBridge-App
und Kev CAD über diesen Socket. MCP hat keinen Weg, eine Freigabe zu setzen: `freigabe_anfragen` öffnet nur den Dialog
und wartet.

| type | Richtung | prio | Felder |
|---|---|---|---|
| `FREIGABE` | KC → VB | zustand | `epoche`, `anfrage_id`, `nonce`, `ablauf`, `eintraege` |
| `FREIGABE_ENDE` | KC → VB | zustand | `epoche`, `anfrage_id`, optional `id`, `grund`, mit `id` auch `ergebnis` |
| `CMD` mit `op: "freigabe"` | VB → KC | zustand | `id` (des Befehls), `args`: `anfrage_id`, `nonce`, `id` (Katalog-ID), `entscheidung` |
| `CMD_RES` | KC → VB | zustand | wie bisher plus `status` (nur bei `freigabe`) |

**FREIGABE:** geht hinaus, sobald ein Agent `freigabe_anfragen` aufruft und der Dialog „Vorschläge freigeben“ im
Projektfenster aufgeht (kurz danach, sobald der Katalog nachgeladen ist).

- **Ohne Miete:** an jede verbundene Gegenstelle, die die Prüfung unten besteht und ihr HELLO geschickt hat, wie `HELLO`
  und `AGENTS`, auch ohne `WATCH`. Direkt nach dem HELLO von Kev CAD kommen alle noch offenen Anfragen.
- `anfrage_id`: eindeutig je Programmstart („F-0001-5c1e9a27“). `ablauf`: ISO 8601 in UTC, 24 h nach der Anfrage.
- `nonce`: 128 Bit Zufall als 32 Hex-Zeichen, einmalig je Anfrage. Kev CAD hält sie nur im Speicher, nie auf Platte und
  nie im Protokoll; VoiceBridge ebenso (kein Log, kein CloudKit-Feld im Klartext, das länger lebt als die Anfrage).
- `eintraege`: die noch offenen Vorschläge, je `{id, kind, name, art, kurz, link, grund, projekt}`. `kind` `teil` oder
  `material`; `art` wie im Katalog (`rohr`, `zukaufteil` …, bei Materialien `material`); `kurz` die Kurzdaten in einer
  Zeile (Maße, Preis, Händler, z. B. „d 16 · s 1 mm · 4,20 €/m · ALFER“). `link` **nur `https`**, sonst fehlt das Feld.
  `grund` (Text oder null) wie in `freigabe_anfragen`; `projekt` nur der Projektname (oder null), **nie ein Pfad**.
- Eine neue Anfrage ersetzt eine offene (die alte endet mit `grund: "zurueckgezogen"`). Eine neue Epoche beendet alle.

**FREIGABE_ENDE:** Die Karte auf dem iPhone verschwindet sofort. Mit `id` ist nur dieser Eintrag erledigt (`ergebnis`
`frei` oder `abgelehnt`), ohne `id` die ganze Anfrage. `grund`:

| grund | wann |
|---|---|
| `mac` | Kevin hat am Mac entschieden (Dialog, Lagerkatalog) oder den Dialog geschlossen |
| `iphone` | per `CMD freigabe` entschieden (auch: der letzte offene Eintrag) |
| `abgelaufen` | 24 h ohne Entscheidung |
| `zurueckgezogen` | eine neue Anfrage hat diese ersetzt |

**CMD freigabe:** eine Entscheidung je Eintrag, `entscheidung` `frei` oder `abgelehnt`. Kev CAD führt sie aus wie
Kevins Klick: Freigeben über dieselbe Freigabe wie der Dialog im Projektfenster (`CATALOG_SAVE` mit `status: "frei"`,
erst nach der Bestätigung im neu geladenen Katalog), mit dem Vermerk `freigegeben_von: "Kevin (iPhone)"` und
`freigegeben_am` (ISO 8601, UTC) im Katalogeintrag; Ablehnen löscht den Vorschlag (`CATALOG_DELETE`, ebenfalls
bestätigt). Der Dialog am Mac aktualisiert sich, `freigabe_anfragen` meldet dem Agenten das Ergebnis wie bisher.
`CMD_RES` kommt erst nach der Bestätigung (Zeitlimit 45 s), danach `FREIGABE_ENDE` mit `id` an alle.

| status | ok | Bedeutung |
|---|---|---|
| `frei` | true | freigegeben und im Katalog bestätigt |
| `abgelehnt` | true | gelöscht und bestätigt |
| `schon_frei` | false | war schon freigegeben |
| `fehlt` | false | steht nicht mehr im Katalog |
| `ungueltig` | false | `anfrage_id`, `nonce`, `id` oder `entscheidung` passen nicht |
| `verbraucht` | false | dieser Eintrag ist mit dieser Nonce schon entschieden oder wird gerade ausgeführt |
| `abgelaufen` | false | die Anfrage ist abgelaufen |
| `beendet` | false | die Anfrage ist erledigt (am Mac geschlossen, ersetzt, alles entschieden) |
| `nicht_erlaubt` | false | die Gegenstelle ist nicht die VoiceBridge-App |
| `katalogfehler` | false | Kernel oder Katalog hat abgelehnt, ist nicht verbunden oder hat nicht bestätigt; `fehler` nennt den Grund |

Die Nonce gilt für die ganze Anfrage, jede Entscheidung aber nur einmal: Ein entschiedener Eintrag ist mit ihr
verbraucht, die Anfrage endet mit dem letzten Eintrag, mit dem Schließen am Mac oder nach 24 h, und mit ihr die Nonce.
Scheitert eine Entscheidung am Katalog (`katalogfehler`), darf das iPhone sie wiederholen.

**Prüfung der Gegenstelle** (`KevCADCore/Mirror/MirrorGegenstelle.swift`): Kev CAD liest beim Verbinden das Audit-Token
des Sockets (`getsockopt(LOCAL_PEERTOKEN)`) und prüft daraus, ohne PID-Umweg:

1. Code der Gegenstelle aus dem Audit-Token: `SecCodeCopyGuestWithAttributes` mit `kSecGuestAttributeAudit` (gleichwertig
   zu `SecCodeCreateWithAuditToken`, das im öffentlichen macOS-SDK nicht deklariert ist).
2. Argumente des Prozesses (`sysctl KERN_PROCARGS2`, PID aus dem Audit-Token) enthalten kein `--mcp`: Die MCP-Prozesse
   der Agenten sind dieselbe Datei wie die VoiceBridge-App und dürfen sich nie als Freigabe-Gegenstelle ausgeben.
3. `SecCodeCheckValidity` gegen das Requirement (Konstante `MirrorGegenstelle.voiceBridgeRequirement`):
   `anchor apple generic and identifier "de.upvis.voicebridge.mac" and certificate leaf[subject.OU] = "2GX7UC98J6"`.
   Gilt für Apple Development und später Developer ID; Testinstanzen von VoiceBridge (Bundle-ID mit „test“) fallen
   gewollt heraus. Die Prüfung kommt nach dem Lesen der Argumente, so passt sie zum selben Prozess (Audit-Token mit
   PID-Version). Geprüft wird mit Standard-Flags, also auch gegen die Datei auf der Platte: Nach einem Update von
   VoiceBridge scheitert der noch laufende alte Prozess (`errSecCSStaticCodeChanged`, Antwort `nicht_erlaubt` mit
   „VoiceBridge neu starten“), bis VoiceBridge neu startet. Die Prüfung im Kernel
   (`kSecCSMatchGuestRequirementInKernel`) kann Zertifikatsfelder nicht auswerten und kommt deshalb nicht in Frage.

Kev CAD prüft beim Verbinden (entscheidet, wer `FREIGABE` bekommt) und vor jedem `CMD freigabe` noch einmal mit dem
Audit-Token vom Verbinden. Alle anderen Gegenstellen bekommen kein `FREIGABE` und auf `freigabe` die Antwort
`nicht_erlaubt`; der übrige Spiegel bleibt für sie wie in Version 1. **Testmodus:** Nur eine Testvariante (Bundle-ID mit
`.test`) mit der Umgebungsvariable `KEVCAD_FREIGABE_TESTMODUS=1` lässt jede Gegenstelle derselben UID zu (etwa
`mirror_sim.py --client`); die installierte App kennt keinen Testmodus.

**VoiceBridge** reicht `FREIGABE` und `FREIGABE_ENDE` wie Zustand weiter (nie verwerfen, auch ohne CAD-Ansicht und
ohne `WATCH`), zeigt je Eintrag eine Karte mit Name, Kurzdaten, Grund, Projekt und Link und schickt `CMD freigabe` nur
aus einer Entscheidung von Kevin auf dem gekoppelten iPhone (gleiche Vertrauensgrenze wie bei allen `CMD`). Keine
automatische Antwort, keine Weitergabe an einen Agenten. Abgelaufene Anfragen (`ablauf`) zeigt sie nicht mehr an, auch
wenn `FREIGABE_ENDE` unterwegs verloren ging; nach einer neuen Epoche verwirft sie alle Karten.

## Kontext für den Agenten

Nicht Teil dieses Sockets, aber hier festgehalten: Ein Diktat oder Text aus der CAD-Ansicht trägt im `AgentCommand` das
optionale, **nicht unterschriebene** Feld `context`:
`{"kind": "cad.selection", "project": "…", "parts": ["Rollwagen/Lenkrolle 1"]}` (`project` = Name, nicht Pfad). Die
VoiceBridge-Mac-App stellt der Nachricht eine abgegrenzte Zeile voran, `[Kev CAD · Auswahl: Rollwagen/Lenkrolle 1]`;
das iPhone zeigt dafür einen Chip. Der Agent sieht die Auswahl zusätzlich in `status`, die Zeile hält den Stand zum
Zeitpunkt des Diktats fest.

## Weiterreichen (VoiceBridge)

- **Direkter Kanal:** eine neue Hülle `cad` mit Kopf und Nutzlast aus Kev CAD, ausgehandelt über `HelloBody.features`
  `cad.mirror.v1`. Ohne dieses Merkmal auf beiden Seiten wird nichts geschickt. Eigenes Eingangskontingent für
  `cad`-Kamerastände (bis 40 je Sekunde, latest-only), sonst gelten die bestehenden Grenzen.
- **Unterwegs (CloudKit):** eigener Bereich (nicht `AgentsLive`), Miete wie beim Live-Verlauf. VoiceBridge setzt Netze
  zu einem CKAsset je Hash zusammen (gepackt, ohne Blockteilung) und bündelt Zustandsdeltas. `kamera` läuft auf diesem
  Weg **nicht in Echtzeit**: höchstens etwa ein Stand je Sekunde, dazu der letzte Stand nach dem Loslassen.

## Testdateien

Liegen in `mirror-fixtures/` im Kev-CAD-Repo, je Datei ein Rahmen, erzeugt aus einem echten Lauf:
`hello_kc.bin`, `agents.bin`, `scene.bin`, `part_upsert.bin`, `mesh_block_1.bin` und `mesh_block_last.bin` (ein Teil
über zwei Blöcke), `state.bin`, `state_delta_auswahl.bin`, `state_delta_sichtbarkeit.bin`, `camera.bin`,
`cmd_kamera.bin`, `cmd_auswahl.bin`, `cmd_res.bin`; dazu `hello_vb.bin`, `watch.bin`, `unwatch.bin`,
`part_remove.bin`, `mesh_req.bin`, `state_delta_alle_zeigen.bin` (isoliert ausdrücklich null), `cmd_sichtbarkeit.bin`,
`cmd_res_fehler.bin` und `fixtures.json` mit den erwarteten Werten. Version 1.1 dazu: `freigabe.bin` (drei Einträge,
einer ohne Link), `cmd_freigabe.bin`, `cmd_freigabe_ablehnen.bin`, `cmd_res_freigabe.bin`,
`cmd_res_freigabe_fehler.bin` (`ungueltig`), `freigabe_ende_eintrag.bin` (mit `id`) und `freigabe_ende.bin` (ganze
Anfrage, `abgelaufen`); die Nonce darin ist ein festes Beispiel. Erzeugt byte-gleich von
`kernel/tools/make_mirror_fixtures.py`; Szene, Zustand und Befehle aus `gestell.kcadrec`, das Netz über zwei Blöcke aus
`samples/drehknopf` (6.680 Dreiecke, gepackt 86 KB).

Weil `STATE_DELTA` Vorrang vor `PART` hat, kann das Delta zum Laufende vor dem letzten `PART` ankommen. Das ist
vertragsgemäß; Empfänger dürfen sich nicht auf die Reihenfolge zwischen den Vorrangklassen verlassen.

Aufgezeichnete Kernel-Läufe in den Rahmen des Kernel-Protokolls liegen in `samples/mirror-recordings/` (siehe dortige
README).

## Ohne laufende Kev-CAD-App testen

`kernel/tools/mirror_sim.py` (Teil von M1): bietet einen Spiegel-Socket an, spielt eine aufgezeichnete Szene ab (Aufbau
Teil für Teil wie bei einem Lauf), beantwortet Befehle wie die App und kann Kamerafahrten, Auswahlwechsel und einen
Neustart mit neuer Epoche simulieren. Aufruf mit eigenem, kurzem Socket-Pfad, damit er neben der echten App läuft.
Seit Version 1.1 auch die Freigabe: `freigabe` (Anfrage mit drei Einträgen), `freigabe-mac`, `freigabe-zurueck` auf
stdin, `--freigabe-ablauf S` zum Testen des Ablaufs; ohne Prüfung der Gegenstelle. Mit `--client PFAD` spielt er
umgekehrt die Gegenstelle gegen eine Testvariante im Testmodus (wartet auf `FREIGABE`, entscheidet jeden Eintrag,
`--pruefen` auch falsche Nonce und Wiederholung).

## Offen

- Ob eine Codesignatur-Prüfung nötig wird, falls Kevin Kev CAD später mit Team-ID signiert.
- Messwerte des Vorrangs auf dem echten iPhone (VoiceBridge-Rollmesser, gleichartig für Gesten in der CAD-Ansicht).
