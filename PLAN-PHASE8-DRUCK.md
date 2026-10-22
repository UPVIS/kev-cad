# Kev CAD · Phase 8: aus Kev CAD drucken (Bambu Lab P1P)

Stand: 22.10.2026 (Kevin am selben Tag: „Direkt hier rausdrucken gerne auch jetzt starten, mit der Druckvorschau
zusammengeführt.“). Zweig `phase8` auf `druckvorschau`. Vertrag: Abschnitt „Drucken (Phase 8)“ in
[DRUCKVORSCHAU.md](DRUCKVORSCHAU.md). Baut auf der Live-Druckvorschau auf ([PLAN-DRUCKVORSCHAU.md](PLAN-DRUCKVORSCHAU.md)):
von den angeordneten Platten bis zum laufenden Druck mit Fortschritt.

**Kevins Entscheidung (22.10.2026):** „Weg A: Handy-App behalten, Kev CAD öffnet die fertigen Platten in Bambu Studio,
Status nur lesend.“ Weg B (LAN-only mit Developer Mode) bleibt als ausgegraute Option mit Anleitung im Code, ohne
weiteren Ausbau.

## Ziel

1. „Drucken …“ in Kev CAD: Kevin sieht im Dialog Platten, Material und Spule, Zeit und Weg und bestätigt.
2. Kev CAD slict die Platten der Druckvorschau mit der Kommandozeile von Bambu Studio fertig (P1P 0.4, Filament je
   Material wie in der Druckvorschau) und öffnet die fertige Datei in Bambu Studio. Dort bleibt für Kevin nur
   „Platte drucken“ und „Senden“.
3. Wenn Kevin IP, Seriennummer und Zugangscode eingetragen hat: Live-Status nur lesend in Kev CAD (Zustand,
   Fortschritt, Schicht, Restzeit, Temperaturen, Fehler).
4. Der Agent kann über MCP den Status lesen und auf Kevins ausdrücklichen Wunsch einen Druck vorbereiten; ausgeführt
   wird nur nach Kevins Klick in der App.

## Recherche (Oktober 2026)

Kennzeichnung: **belegt** (die Quelle sagt es klar), **angenommen** (abgeleitet oder nicht eindeutig belegt).
Quellen am Ende des Abschnitts. Gelesen wurden nur Wiki, Blog, Shop und Quelltexte; kein Kontakt zum echten Drucker.

### Freigaben der Firmware („Authorization Control“)

- Eingeführt für P1P und P1S mit Firmware **01.08.02.00 vom 03.06.2025**; zuerst angekündigt am 16.01.2025 für die X1.
  Die Firmware prüft, ob ein Steuerbefehl von offizieller oder autorisierter Software kommt, und lehnt andere ab.
  **belegt** [W1][B1]
- Autorisiert sein müssen: Druckstart über LAN oder Cloud, Bewegung, Temperaturen, Lüfter, AMS, Kalibrierung, Binden,
  Fernvideo, Firmware-Updates. Frei bleiben die MQTT-Statusmeldungen und der Druck von der SD-Karte. **belegt** [B1]
- Schon seit 01.06.00.00 (11.06.2024) sperrt der lokale MQTT-Broker im Cloud-Modus Druckstart und Heizen; seit
  01.08.02.00 gilt die Sperre für alle Steuerbefehle fremder Software, im Cloud- **und** im LAN-Modus. **belegt**
  [W1][W2][G4]
- Ein unsignierter Steuerbefehl erzeugt den HMS-Fehler **0500-0500-0001-0007** („MQTT command verification failed“),
  der weitere Drucke blockiert, bis er quittiert ist. **belegt** [G7]
- Aktuelle P1-Firmware: **01.10.00.00 (30.03.2026)**; unter 01.09.01.00 erst die Brückenfirmware 01.09.01.00 offline
  aufspielen. **belegt** [W1]
- Woran der Kernel den Modus erkennt: Der Statusbericht enthält `print.fun` (Hex-Text); Bit `0x20000000` gesetzt =
  „MQTT-Signatur nötig“ (Developer Mode aus). Beispiel aus ha-bambulab: `3EC1AFFF9CFF` aus, `3EC18FFF9CFF` an.
  ha-bambulab sperrt damit alle schreibenden Aktionen. **belegt** [G6c][G6]. SSDP meldet zusätzlich
  `DevConnect.bambu.com: lan|cloud`. **belegt** [G11]

### LAN-only und Developer Mode am P1P

- Developer Mode gibt es ab 01.08.02.00, nur im LAN-Modus. **belegt** [W1][W3]
- Bedienung am Gerät (2,7-Zoll-Schwarzweißanzeige mit Tasten, kein Touch): Einstellungen → WLAN → **LAN Only Mode** →
  Yes; dann nach unten zu **Developer Mode**, Hinweis lesen, ans Ende scrollen → **Enable**. Der Zugangscode steht auf
  derselben Seite unter der IP. **belegt** [W3][W2][S2]
- Was wegfällt: Bambu Handy (Fernüberwachung, Mitteilungen, Kamera in der App), Druckstart außerhalb des LANs,
  Cloud-Druckverlauf; der Drucker ist ganz von der Cloud getrennt. **belegt** [W2][W4]. Firmware-Updates über die
  Cloud fallen weg, offline per microSD geht seit 01.07.00.00. **angenommen** bzw. **belegt** [W1]
- Was bleibt: Bambu Studio im LAN (Drucker per IP und Zugangscode), Druck von der SD-Karte, MQTT, FTPS und
  Livestream offen für Fremdsoftware. **belegt** [W2][W3][W4][B2]
- Status lesen geht in jedem Modus. **belegt** [W4][G4]. ha-bambulab beschreibt ausdrücklich den „hybrid mode“: Der
  Drucker bleibt mit der Bambu-Cloud verbunden, die Integration verbindet sich lokal; lesen geht, steuern nicht
  („All read functionality will continue to work, regardless of firmware version“). **belegt** [G4]
- Dass auch die Leseanfragen `pushall` und `get_version` im Cloud-Modus keinen Fehler auslösen: **angenommen**,
  gestützt darauf, dass ha-bambulab (MIT) sie in jedem Modus schickt und nur schreibende Aktionen sperrt [G5][G6].
- Nicht belegt ist, dass die zusätzliche lokale Verbindung ohne Nebenwirkung bleibt: Für ältere P1-Firmware gibt es
  Berichte über eine kleine Zahl gleichzeitiger lokaler MQTT-Verbindungen (Bambu Studio und Home Assistant verdrängten
  sich), aber keine Herstellerangabe; einen HMS-Fehler oder eine Abmeldung der Handy-App durch reines Lesen meldet keine
  Quelle. **angenommen** [F3][F4]. **Folge:** „Status lesen“ ist in Kev CAD anfangs aus; Kevin schaltet es bewusst
  ein, die Einstellungen sagen warum.

### Ohne Umstellung am Drucker (Weg A)

- **Bambu Studio** nimmt eine fertige `.gcode.3mf` per `open -a BambuStudio datei` an. Enthält sie keine Objekte
  (CLI-Schalter `--min-save`, setzt `SaveStrategy::SkipModel`), lädt Studio nur die G-Code-Platten und springt in die
  Vorschau mit gültigem Slice-Ergebnis („using exported file“); dann ist „Platte drucken“ sofort aktiv und der
  Sendedialog prüft das Druckermodell gegen das Profil der Datei. **belegt** am Quelltext [G9: Plater.cpp
  `load_files` und `on_action_print_plate`, BambuStudio.cpp `minimum_save`, bbs_3mf.cpp `m_skip_model`]. Lokal
  geprüft: Die CLI 02.07.01.62 schreibt mit `--min-save` eine `.gcode.3mf` ohne `3D/Objects`.
- Läuft Studio schon und ist „nur eine Instanz“ aus, öffnet die Datei ein neues Fenster. **belegt** [G9]
- **Bambu Connect** (v2.5.0-beta.15, Mac arm64 und x64 ab macOS 13) nimmt
  `bambu-connect://import-file?path=<url-kodiert>&name=<url-kodiert>&version=1.0.0` an; danach Platte wählen →
  Drucken → Senden. Auf Kevins Mac nicht installiert. **belegt** [W4][W5]
- Bambu Studio hat auf dem Mac kein URL-Schema für lokale Dateien (registriert ist nur `bambustudioopen://` für
  http(s)). Die CLI kann slicen und exportieren, aber nicht senden. **belegt** [G9][G10]
- **Wenigste Klicks:** fertige `.gcode.3mf` ohne Objekte in Bambu Studio öffnen → „Platte drucken“ (bzw. „Alle
  drucken“) → Drucker steht schon → „Senden“: zwei Klicks. **angenommen** für die Zahl der Klicks (Studio merkt sich
  den zuletzt gewählten Drucker), **belegt** für den Ablauf im Quelltext.

### Kamera

- Der P1P hat die Kamera **ab Werk** (1280 × 720, 0,5 Bilder/s); die „Chamber Camera – P1 Series“ im Shop ist ein
  Ersatzteil. **belegt** [S1]
- Protokoll im LAN: TLS auf Port 6000, 80-Byte-Anmeldung mit `bblp` und Zugangscode, je Bild 16-Byte-Kopf und JPEG.
  **belegt** [G1v][G5]
- „Fernvideo“ steht auf der Liste der freigabepflichtigen Funktionen [B1]; ob Port 6000 im Cloud-Modus für
  Fremdsoftware ohne Fehler offen ist, ist nicht belegt. **Folge (Kevin, 22.10.2026):** kein Kamerabild in Weg A.

### MQTT (Port 8883)

- TLS, Benutzer `bblp`, Passwort = Zugangscode, Themen `device/<SERIAL>/request` und `device/<SERIAL>/report`.
  **belegt** [G1m]
- Der P1P schickt nur geänderte Werte; `pushing.pushall` holt alles, auf dem P1P **höchstens alle 5 Minuten**, sonst
  ruckelt er. **belegt** [G1m]
- Befehle (QoS 1):
  - `{"pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}}` **belegt** [G1m]
  - `{"info": {"sequence_id": "0", "command": "get_version"}}` **belegt** [G6]
  - `{"print": {"sequence_id": "0", "command": "pause"|"resume"|"stop", "param": ""}}` **belegt** [G1m][G6]
  - `{"print": {"sequence_id": "0", "command": "project_file", "param": "Metadata/plate_<n>.gcode",
    "url": "file:///sdcard/cache/<datei>", "md5": "<md5 des Platten-G-Codes>", "subtask_name": "<name>",
    "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0", "timelapse": false,
    "bed_type": "auto", "bed_leveling": true, "flow_cali": true, "vibration_cali": true, "layer_inspect": false,
    "use_ams": false, "ams_mapping": [0]}}` – Schreibweise `bed_leveling` wie in den Projekten, die tatsächlich
    drucken (OpenBambuAPI schreibt `bed_levelling`); `url` mit `cache/` wie bambu-printer-mcp für P1/X1; externe Spule
    ohne AMS: `use_ams: false`. **belegt** [G1m][G6][G7] bzw. **angenommen** für die genaue Schreibweise, die die
    P1P-Firmware erwartet.
- Statusfelder (`print`): `gcode_state` (IDLE, PREPARE, RUNNING, PAUSE, FINISH, FAILED, INIT, SLICING), `mc_percent`,
  `mc_remaining_time` (Minuten), `layer_num`, `total_layer_num`, `nozzle_temper`, `nozzle_target_temper`,
  `bed_temper`, `bed_target_temper`, `print_error`, `hms` (Liste `attr`, `code`), `subtask_name`, `gcode_file`,
  `mc_print_stage`, `stg_cur`, `spd_lvl` (1 leise, 2 Standard, 3 Sport, 4 Ludicrous), `wifi_signal`, `fun`,
  `vt_tray` (externe Spule, `id` 254). Version in `info.module[name=ota].sw_ver`. **belegt** [G1m][G6c][G6m]

### FTPS (Port 990)

- Implizites TLS, Benutzer `bblp`, Zugangscode; passive Ports 50000–50100; Wurzel = SD-Karte mit `cache/` und
  `timelapse/`. **belegt** [G1f][W6][G8]
- Der Datenkanal braucht die TLS-Sitzung des Steuerkanals (`ntransfercmd` mit `session=self.sock.session`); beim
  Hochladen kein `unwrap()`, sonst hängt der Server. **belegt** [G5][G8]
- Ohne Developer Mode ist FTP für Fremdsoftware gesperrt: **angenommen** [B2]. Der P1P braucht eine SD-Karte für den
  Druck über LAN: **angenommen** (belegt nur für den X1) [W2].

### TLS

- Zertifikat des Druckers: CN = Seriennummer, ausgestellt von „BBL CA“; Hostname-Prüfung aus, CN selbst prüfen; die
  CA-Datei aus ha-bambulab (`pybambu/certs/bambu.cert`, MIT) enthält BBL CA, BBL CA2 RSA und BBL CA2 ECC.
  **belegt** [G1t][G5]. ha-bambulab begrenzt auf TLS 1.2 (wegen einer P2S-Firmware); für den P1P nicht nötig,
  schadet nicht. **belegt** bzw. **angenommen**.

### SSDP (passives Erkennen)

- Der Drucker schickt etwa alle 5 s `NOTIFY * HTTP/1.1` als Broadcast an Port 2021 (dazu 1990) mit `Location` (IPv4),
  `USN` (Seriennummer), `NT: urn:bambulab-com:device:3dprinter:1`, `DevModel.bambu.com` (P1P = `C11`),
  `DevName.bambu.com`, `DevConnect.bambu.com` (`lan`/`cloud`), `DevBind.bambu.com`, `DevSignal.bambu.com`,
  `DevVersion.bambu.com`. **belegt** [G11][F1][G12]
- Kev CAD reicht die Seriennummer aus `USN` nie weiter; nach außen geht nur eine Kennung (Hash).

### Lizenzen der Vorlagen

| Projekt | Lizenz | Verwendung |
|---|---|---|
| OpenBambuAPI | GFDL-1.3 (Doku) | nur Fakten |
| ha-bambulab (mit pybambu) | MIT | Vorlage; CA-Zertifikate übernommen mit Herkunftsangabe |
| bambulabs_api | MIT | Vorlage (FTPS) |
| bambu-printer-mcp | GPL-2.0 | nur gelesen, nichts übernommen |
| paho-mqtt | EPL-2.0 oder EDL-1.0 (BSD-artig) | Abhängigkeit des Kernels |

### Quellen

- [W1] https://wiki.bambulab.com/en/p1/manual/p1p-firmware-release-history
- [W2] https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
- [W3] https://wiki.bambulab.com/en/knowledge-sharing/enable-developer-mode
- [W4] https://wiki.bambulab.com/en/software/third-party-integration
- [W5] https://wiki.bambulab.com/en/software/bambu-connect
- [W6] https://wiki.bambulab.com/en/general/printer-network-ports
- [B1] https://blog.bambulab.com/firmware-update-introducing-new-authorization-control-system-2
- [B2] https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect
- [S1] https://us.store.bambulab.com/products/chamber-camera-p1-series
- [S2] https://eu.store.bambulab.com/en/products/p1p-screen
- [G1m/f/v/t] https://github.com/Doridian/OpenBambuAPI (`mqtt.md`, `ftp.md`, `video.md`, `tls.md`)
- [G4] https://github.com/greghesp/ha-bambulab/blob/main/docs/index.mdx
- [G5] https://github.com/greghesp/ha-bambulab/blob/main/custom_components/bambu_lab/pybambu/bambu_client.py
- [G6] https://github.com/greghesp/ha-bambulab/blob/main/custom_components/bambu_lab/pybambu/commands.py,
  `coordinator.py`; [G6c] `const.py`; [G6m] `models.py`
- [G7] https://github.com/DMontgomery40/bambu-printer-mcp/blob/main/src/printers/bambu.ts (GPL, nur gelesen)
- [G8] https://github.com/BambuTools/bambulabs_api (`ftp_client.py`, `mqtt_client.py`)
- [G9] https://github.com/bambulab/BambuStudio: `src/slic3r/GUI/Plater.cpp`, `src/slic3r/GUI/SelectMachine.cpp`,
  `src/BambuStudio.cpp`, `src/libslic3r/Format/bbs_3mf.cpp`, `src/platform/osx/Info.plist.in`
- [G10] https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/PrintConfig.cpp
- [G11] https://github.com/ClusterM/open-bamboo-networking/blob/master/research/06.01-ssdp.md
- [G12] https://github.com/bambulab/BambuStudio/blob/master/resources/profiles/BBL/machine/Bambu%20Lab%20P1P.json
- [F1] https://forum.bambulab.com/t/use-ssdp-standards/7173
- [F3] https://forum.bambulab.com/t/p1p-and-mqtt/5582 (Berichte zu lokalen MQTT-Verbindungen am P1P)
- [F4] https://community.home-assistant.io/t/bambu-lab-x1-x1c-mqtt/489510 (Berichte zu gleichzeitigen Verbindungen)

## Gegenüberstellung für Kevin (vorgelegt am 22.10.2026)

| | Weg A: ohne Umstellung (Cloud-Modus) | Weg B: LAN-only + Developer Mode |
|---|---|---|
| Druck starten | Kev CAD slict und öffnet in Bambu Studio, Kevin klickt „Platte drucken“ und „Senden“ | ein Klick in Kev CAD nach Bestätigung (FTPS-Upload, MQTT-Start) |
| Optionen | in Bambu Studio | Bettnivellierung, Flussratenkalibrierung, Zeitraffer, externe Spule im Dialog |
| Live-Status in Kev CAD | nur lesend (Zustand, Fortschritt, Schicht, Restzeit, Temperaturen, Fehler) | lesend plus Pause, Fortsetzen, Abbruch |
| Kamera | nein (nicht belegt, dass es ohne Fehler geht) | Einzelbild im LAN möglich |
| Bambu Handy | bleibt: Fernüberwachung, Mitteilungen, Kamera, Verlauf | fällt ganz weg |
| Firmware-Updates | über die Cloud | nur offline per microSD |
| Sicherheit | Steuern nur über Bambu | jeder im LAN mit Zugangscode kann steuern |

Entscheidung: **Weg A** (Kevin, 22.10.2026).

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| P1 | **Weg A ist Standard und der einzige ausgebaute Weg.** Weg B ist im Kernel vorhanden (Upload, Start, Pause, Fortsetzen, Abbruch), getestet nur gegen Attrappen, in der App ausgegraut mit Erklärung und Umschalt-Anleitung | Kevins Entscheidung |
| P2 | **Sperre vor jedem Steuerbefehl** im Kernel (`drucker/sperre.py`): nur Weg B gewählt, Verbindung in dieser Sitzung, `print.fun` empfangen und Bit `0x20000000` gelöscht, SSDP nicht `cloud`, kein HMS 0500-0500-0001-0007 offen, beim Start Kevins Bestätigung. Sonst wird nichts gesendet. Erlaubt sind in jedem Modus nur die Leseanfragen `pushall` (höchstens alle 5 min) und `get_version` | HMS 0500-0500-0001-0007 blockiert sonst den Drucker |
| P3 | **Fertig slicen mit der CLI:** Eingang ist das 3MF der Druckvorschau (V-K, `druck_export`); ohne sie ein Ersatzweg je Material aus den Druckteilen (STL, Bambu Studio richtet aus und ordnet an). Profile: Systemprofile aus Bambu Studio, Vererbung (`inherits`) aufgelöst, Kevins Filamentprofile nur gelesen; `--min-save`, damit Studio direkt in der Vorschau öffnet; Zwischenspeicher je Eingang und Profilen unter `~/Library/Caches/de.upvis.kevcad/drucker/` | Ein Slicer, Kevins Profile, zwei Klicks bis zum Druck |
| P4 | **Zugangsdaten:** Seriennummer und Zugangscode nur im macOS-Schlüsselbund (ein Eintrag je Drucker, Dienst `de.upvis.kevcad.drucker`, Konto = Drucker-ID). Die App schreibt ihn mit Zugriff für Kev CAD und `/usr/bin/security`: Das bedeutet, dass jedes Programm unter Kevins Benutzer den Zugangscode ohne Rückfrage lesen kann; die Einstellungen sagen das und haben „Zugangsdaten löschen“. Der Kernel ruft `security` nur mit festem Dienst- und Kontonamen auf, gibt Ausgabe und Fehlertext nie weiter und hält den Code nur im Speicher, solange die Verbindung besteht. Nie in Datei, Protokoll, Nachricht an den Agenten oder Commit | Kevins Regel; ohne Zugriff für `security` fragte macOS nach jedem Ad-hoc-Build neu nach dem Kennwort; bei Weg A erlaubt der Code ohnehin nur das Lesen |
| P5 | **Bestätigung in der App:** Jeder Auftrag (auch Weg A) braucht Kevins Klick im Dialog „Drucken …“; MCP `drucken` öffnet nur den Dialog | Nichts geschieht ohne Kevin |
| P6 | **Status nur lesend in Weg A** über MQTT, wenn IP, Seriennummer und Zugangscode eingetragen sind und Kevin „Status lesen“ bewusst eingeschaltet hat (anfangs aus, weil die Nebenwirkungsfreiheit der zusätzlichen lokalen Verbindung nicht belegt ist); ohne das zeigt Kev CAD nur, was es selbst tut (slicen, öffnen) | Kevins Entscheidung, Auflage des Koordinators |
| P7 | **Erkennen nur passiv** (SSDP mithören auf UDP 2021), keine Portscans; Erreichbarkeit höchstens per TCP-Verbindungsaufbau ohne Anmeldung | Sicherheitsregel |

## Arbeitspakete

| Paket | Inhalt |
|---|---|
| P8-K | Kernel: Paket `kevcad_kernel/drucker/` (Erkennen, Profile, Slicen, Weg A, Weg B, Sperre, Status, Zwischenspeicher), Laufzeit-Mixin, MCP `drucker_status`, `drucken`, Nachrichten und Testdateien |
| P8-A | App: `DruckerStore`, `DruckerLeiste(model:)`, `DruckenDialog`, `DruckerEinstellungen` (Schlüsselbund), Selbsttest `KEVCAD_SELFTEST=drucker` |
| P8-I | Einbindung der `DruckerLeiste` in die Druckvorschau-Ansicht von V-A (Platz stimmt der Koordinator ab) |

## Was Kevin am Drucker tun muss

- Weg A: nichts. Für den lesenden Status in Kev CAD die IP, die Seriennummer und den Zugangscode eintragen (am
  Drucker unter Einstellungen → WLAN; Seriennummer auch in Bambu Studio unter „Gerät“).
- Weg B (nur falls er später umstellen will): Firmware mindestens 01.08.02.00, LAN Only Mode und Developer Mode
  einschalten (Anleitung oben), SD-Karte im Drucker.
