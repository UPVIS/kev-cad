# Kev CAD · Druckvorschau (Vertrag)

Version 1 (22.10.2026). Verbindlich für die Live-Druckvorschau aus [PLAN-DRUCKVORSCHAU.md](PLAN-DRUCKVORSCHAU.md)
(Entscheidungen V1–V7). Änderungen nur gemeinsam: dieses Dokument, `protocol.py`, Testdateien und Swift-Decoder im
selben Commit (wie PROTOCOL.md). Einheiten: mm, g, m, s, €; Platte in Drucker-mm, Ursprung vorn links, Z oben.

## Drucker und Einstellungen

- Drucker: Bambu Lab P1P, 0,4-mm-Düse, Bauraum 256 × 256 × 250 mm, vorn links 18 × 28 mm gesperrt (wie die
  Druckprüfung, `druck/regeln.py`). Weitere Drucker später über `drucker.json` wählbar; bis dahin fest P1P.
- Projekt-Einstellungen in `kevcad.json` unter `"druck"` (alles optional):

```json
{"druck": {"drucker": "p1p-0.4", "strompreis_kwh": 0.32, "leistung_w": 350, "plattenwechsel_s": 120,
           "slicer": true, "filament": {"petg": "Bambu PETG Basic", "pla": "Amazon Basics PLA"}}}
```

- Filamentpreis und Dichte kommen aus dem Materialkatalog (`material_list`, Stand-Datum mitführen). Ein Filament­profil
  aus Bambu Studio gilt für Slicer-Läufe; fehlt es, nimmt der Kernel das mitgelieferte Systemprofil gleichen Materials.

## Zweck eines Druckteils (model.py, additiv)

`lager.druckteil(form, name, material, verfahren="3d-druck", ausrichtung=None, zweck=None, anzahl=None)`

- `zweck`: `"zier"` | `"funktion"` | `"tragend"` | `"bewegt"` | `"aussen"`; ohne Angabe schätzt der Kernel
  (`funktion`), markiert als Schätzung.
- Gleiche Teile erkennt der Kernel über Form und Material (gleicher Formschlüssel); `anzahl` nur, wenn ein Teil
  öfter gedruckt wird, als es im Modell steht (Ersatzteile).

## Ergebnis (`druckvorschau`)

```json
{"run": 12, "stand": "schaetzung" | "slicer" | "gemischt", "drucker": "Bambu Lab P1P 0.4",
 "summe": {"platten": 3, "zeit_s": 61200, "zeit_mit_wechsel_s": 61440, "kosten": 9.85,
           "kosten_teile": {"filament": 8.12, "strom": 1.73},
           "material": [{"material": "petg", "name": "PETG", "g": 812.4, "m": 268.7, "kosten": 8.12,
                         "preis_kg": 10.0, "preis_stand": "2026-10", "stand": "schaetzung"}]},
 "platten": [{"nr": 1, "zeit_s": 22100, "material": [{"material": "petg", "g": 301.0}], "stand": "slicer",
              "teile": [{"name": "Kugelschieber/Stangenhalter vorn links (Druck)", "gruppe": "g3", "x": 40.0, "y": 52.0,
                         "drehung": 90, "umriss": [[x, y], ...]}],
              "auslastung": 0.62}],
 "teile": [{"gruppe": "g3", "name": "Stangenhalter (Druck)", "teile": ["…vorn links (Druck)", "…"], "anzahl": 4,
            "material": "petg", "zweck": "tragend", "zweck_geschaetzt": false,
            "g": 143.4, "m": 47.4, "zeit_s": 5400, "stand": "slicer", "abweichung": 0.06,
            "einstellungen": {"schicht_mm": 0.2, "waende": 4, "decken": 5, "boeden": 4, "fuellung": 0.25,
                              "muster": "gyroid", "stuetzen": "keine" | "baum" | "normal", "brim": false,
                              "ausrichtung": "…aus der Druckprüfung…"},
            "begruendung": ["tragend: 4 Wände, 25 % Gyroid", "Last längs der Schichten"],
            "hinweise": [{"schwere": "hinweis" | "warnung" | "fehler", "text": "PETG vorher trocknen (65 °C, 4 h)",
                          "art": "trocknen"}]}],
 "hinweise": [{"schwere": "warnung", "text": "ABS auf offenem Drucker verzieht sich", "art": "material"}],
 "slicer": {"zustand": "aus" | "wartet" | "rechnet" | "fertig" | "fehler", "fertig": 3, "gesamt": 5,
            "meldung": null}}
```

- `stand`: Werte der schnellen Schätzung oder des Slicers; je Teil, je Platte und in der Summe getrennt geführt.
- `abweichung`: relative Abweichung der Schätzung vom Slicer beim letzten Abgleich (für Kevin sichtbar als Genauigkeit).
- Hinweise im gemeinsamen Format (`schwere`, `text`, `art`); Fehler der Druckprüfung bleiben dort, hier nur Druckpraxis
  (Trocknen, Verzug, Brim, Stützen-Nacharbeit, AMS-Spülmenge, Düsenverschleiß bei CF, Erfolgsrisiko).

**Präzisierungen und additive Felder (V-K, 22.10.2026; nichts Bestehendes geändert):**

- `teile[]`: `g`, `m`, `zeit_s` und `kosten` gelten für alle `anzahl` Stück der Gruppe; je Stück additiv
  `je_stueck: {"g", "m", "zeit_s"}`. `teile` sind die Namen aus `show()`; `anzahl` ist mindestens ihre Zahl (mehr nur
  mit `druckteil(…, anzahl=)`). Additiv: `fest` (Liste der Einstellungen, die Kevin oder der Agent fest vorgegeben
  hat, dazu `"zweck"`, wenn der Zweck vorgegeben ist), `profil: {"prozess", "filament"}` (Bambu-Studio-Profile),
  `risiko` (0–1, Fehldruck-Wahrscheinlichkeit), `stuetzen_g` (Stützmaterial aller Stück), `kosten`.
- `einstellungen.fuellung` ist ein Anteil 0–1 (0,25 = 25 %); `muster` wie in Bambu Studio (`gyroid`, `grid`,
  `cubic`, `honeycomb`, `rectilinear`, `line`, `concentric`, `triangles`, `zigzag`, `crosshatch`, `lightning`).
- `platten[].teile[]`: `x`, `y` = Mitte des Hüllrechtecks auf der Platte (Drucker-mm, Ursprung vorn links);
  `drehung` in Grad um Z gegenüber der Druckausrichtung; `umriss` = konvexe Hülle in Plattenkoordinaten (absolut,
  gegen den Uhrzeigersinn). Additiv `ersatz` (true für Stück über die gezeigten hinaus, `name` bleibt das gezeigte
  Teil). Additiv je Platte: `anordnung` (`schnell` | `slicer`), `kosten`, `hoehe_mm`, `material[].m` und
  `material[].kosten`. Eine Platte trägt ein Material (P1P ohne AMS).
- `summe.kosten` = Summe von `kosten_teile`; additiv `kosten_teile.risiko` (Aufschlag fürs Erfolgsrisiko, V5).
  `zeit_mit_wechsel_s` = `zeit_s` + (Platten − 1) · `plattenwechsel_s`.
- Additiv oben: `einstellungen` (benutzte Projekt-Einstellungen: `drucker`, `strompreis_kwh`, `leistung_w`,
  `plattenwechsel_s`, `slicer`), `regler` (true: Lauf mit Reglerwerten, nichts gespeichert, kein Slicer), `ms`
  (Rechenzeit der Schätzung); `slicer.version` (Bambu Studio), `slicer.ms`.
- Ohne Druckteile: `platten` und `teile` leer, Summe null, `slicer.zustand: "aus"`.
- `hinweise[].art`: `trocknen`, `verzug`, `material`, `brim`, `stuetzen`, `ams`, `duese`, `risiko`, `bauraum`,
  `auflage`, `festigkeit`, `slicer`, `platte`.

## Ablauf im Kernel

1. Nach jedem erfolgreichen Lauf mit Druckteilen: Schätzung (V1/V2) und schnelles Anordnen (V3), Ziel unter 1 s am
   Kugelschieber; senden als `PRINT_PREVIEW`.
2. Im Hintergrund, wenn `druck.slicer` an und Bambu Studio vorhanden (`/Applications/BambuStudio.app`): je Gruppe
   (Formschlüssel + Material + Einstellungen) einmal slicen, Zwischenspeicher unter
   `~/Library/Caches/de.upvis.kevcad/druck/<schlüssel>/`; danach die Platten mit `--arrange` genau anordnen. Jedes
   Ergebnis ersetzt die Schätzung und schickt ein neues `PRINT_PREVIEW`. Niedrige Priorität, höchstens ein Slicer-Prozess
   gleichzeitig, Abbruch bei neuem Lauf; nie während eines Laufs mit Reglerwerten speichern.
3. Abgleich: Faktoren der Schätzung je Drucker und Profil in `~/Library/Application Support/de.upvis.kevcad/druck/
   abgleich.json` nachführen (V2).
4. Ohne Bambu Studio (z. B. Mac mini): nur Schätzung, `slicer.zustand: "aus"` mit Meldung; Tests überspringen den
   Slicer-Teil.

## Protokoll (additiv)

| type | Richtung | Felder | Nutzlast |
|---|---|---|---|
| `PRINT_PREVIEW` | Kernel → App | Inhalt von `druckvorschau` (oben), `reply_to` optional | – |
| `PRINT_PREVIEW_REQ` | App → Kernel | `id` | `PRINT_PREVIEW` |
| `PRINT_EXPORT_REQ` | App → Kernel | `id`, `platten` (Liste der Nummern oder leer = alle), `ziel` (Pfad .3mf) | `ACK`, danach `PRINT_EXPORT_RES` |
| `PRINT_EXPORT_RES` | Kernel → App | `reply_to`, `ok`, `pfad`, `platten`, `fehler` | – |
| `PRINT_SETTINGS` | App → Kernel | `id`, `teil` oder `gruppe`, `einstellungen` (Teilmenge wie oben) oder `zweck` | `ACK`, danach `PRINT_PREVIEW` |

`PRINT_SETTINGS` von Kevin gelten als feste Vorgabe je Gruppe und überleben Läufe (gespeichert in
`<projekt>/druck.json`, gehört zu den Projektdateien und damit zu den Versionen).

Präzisierungen (additiv): `PRINT_SETTINGS.von` (`kevin` Vorgabe, `agent` vom MCP); ein Wert `null` in
`einstellungen` nimmt diese Vorgabe zurück; `zuruecksetzen: true` nimmt alle Vorgaben des Teils bzw. der Gruppe
zurück. Gespeichert wird je Teilname (aus `show()`), damit die Vorgabe Formänderungen übersteht; eine Gruppe schreibt
alle ihre Teile. `PRINT_EXPORT_REQ.ziel` `null` = `<projekt>/output/<projekt>-druck.3mf`. `PRINT_EXPORT_RES` additiv
`hinweise`, `ms`, `geprueft` (die Datei wurde zur Kontrolle in Bambu Studio geladen). Testdateien:
`tools/make_druck_fixtures.py` (`print_*.frame`, `ack_print_*.frame`, Abschnitt `druck` in `fixtures.json`);
Beispiel und Prüfung in `protocol.py` (`druckvorschau_beispiel`, `check_druck_message`).

## MCP

- `druckvorschau(detail=False)`: Summe, Platten, Teile mit Empfehlung und Hinweisen; `detail` mit Umrissen.
- `druck_einstellen(teil, einstellungen=None, zweck=None)`: wie `PRINT_SETTINGS` mit `von: "agent"`; nur auf Kevins
  Wunsch oder mit Begründung im Bericht.
- `druck_export(ziel=None, platten=None)`: 3MF der angeordneten Platten für Bambu Studio (Grundlage Phase 8), ohne
  Drucken.

## App

- Panel **„Druck“** neben der Stückliste (Tab in der unteren Leiste): je Material g, m, €; je Platte Zeit und Teile;
  Summe mit Plattenwechseln; je Teil Empfehlung mit Begründung und Hinweise als Ampel; Kennzeichnung „Schätzung“ bzw.
  „Bambu Studio“ und Fortschritt des Slicers.
- **Plattenansicht**: Draufsicht der Platte(n) im Maßstab mit Sperrzone, Teile als Umriss, Auswahl wechselwirkt mit dem
  3D-Bereich und dem Teilebaum.
- Einstellungen je Teil bzw. Gruppe ändern (Zweck, Wände, Füllung, Muster, Stützen, Brim) → `PRINT_SETTINGS`.
- **„Platten als 3MF …“** → `PRINT_EXPORT_REQ`; danach „In Bambu Studio öffnen“.
- Bericht „Druck“ im Export-Dialog von Phase 6 (Baustein `druck`): Tabelle je Platte und Teil mit Einstellungen.

## Drucken (Phase 8)

Version 1 (22.10.2026), additiv. Plan, Recherche und Entscheidungen P1–P7: [PLAN-PHASE8-DRUCK.md](PLAN-PHASE8-DRUCK.md).
Kevins Entscheidung: **Weg A**. Änderungen nur gemeinsam: dieser Abschnitt, `protocol.py` (Abschnitt Drucker),
`tools/make_drucker_fixtures.py` mit den Testdateien und die Swift-Decoder im selben Commit.

### Wege

- **`a`** (Standard): Drucker bleibt im Cloud-Modus. Der Kernel slict die gewählten Platten mit der CLI von Bambu Studio
  fertig (`.gcode.3mf` ohne Objekte, `--min-save`) und öffnet die Datei in Bambu Studio; dort „Platte drucken“ →
  „Senden“. Status nur lesend, wenn IP, Seriennummer und Zugangscode eingetragen sind.
- **`b`** (gesperrt, nicht ausgebaut): LAN-only + Developer Mode. Upload per FTPS nach `cache/`, Start per MQTT
  (`project_file`) mit genau einer Platte, Pause, Fortsetzen, Abbruch.

**Sperre (verbindlich, `drucker/sperre.py`):** Außer den Leseanfragen `pushing.pushall` (höchstens alle 300 s) und
`info.get_version` schickt der Kernel nur dann etwas an den Drucker, wenn alles gilt: Weg `b` eingestellt;
MQTT-Verbindung in dieser Sitzung; `print.fun` in dieser Verbindung empfangen und Bit `0x20000000` gelöscht (Developer
Mode an); SSDP meldet nicht `cloud` (falls gesehen); kein HMS `0500-0500-0001-0007` offen; für den Start ein von Kevin
bestätigter Auftrag. Sonst sendet er nichts und antwortet mit dem Grund. Die Kamera wird nicht benutzt (`kamera: false`).

### Einstellungen

Gehören der App, eine Datei je Variante: `~/Library/Application Support/<Bundle-ID>/drucker.json`, nie mit Geheimnissen:

```json
{"version": 1, "aktiv": "p1p",
 "drucker": [{"id": "p1p", "name": "P1P", "modell": "C11", "ip": "192.168.178.40", "weg": "a", "status_lesen": false,
              "schluesselbund": {"dienst": "de.upvis.kevcad.drucker", "konto": "p1p"}}]}
```

- `id`: `[a-z0-9][a-z0-9-]{0,31}`, zugleich das Konto im Schlüsselbund. `status_lesen` ist anfangs **aus**: Dass die lokale
  MQTT-Verbindung im Cloud-Modus ohne Nebenwirkung bleibt, ist nur für das Lesen belegt (ha-bambulab „hybrid mode“), nicht
  für die Zahl gleichzeitiger Verbindungen; Kevin schaltet es bewusst ein (Hinweis in den Einstellungen).
- Seriennummer und Zugangscode stehen nur im Schlüsselbund: ein Eintrag (generisches Passwort) je Drucker, Dienst fest
  `de.upvis.kevcad.drucker`, Konto = `id`, Inhalt `{"seriennummer": "…", "zugangscode": "…"}` als JSON. Die App legt
  ihn an (Zugriff erlaubt für Kev CAD und `/usr/bin/security`; damit kann jedes Programm unter Kevins Benutzer ihn ohne
  Rückfrage lesen, die Einstellungen sagen das und bieten „Zugangsdaten löschen“). Der Kernel liest ihn nur beim
  Verbinden mit `/usr/bin/security find-generic-password -s de.upvis.kevcad.drucker -a <id> -w` (feste Namen, `id`
  geprüft), hält ihn nur im Speicher, solange die Verbindung besteht, und gibt Ausgabe und Fehlertext von `security`
  nie weiter. Niemand gibt ihn aus: nicht in Nachrichten, Protokollen, Tracebacks, MCP-Ergebnissen, Dateien oder
  Commits. Das Feld `schluesselbund` in `drucker.json` ist nur ein Hinweis für Menschen.
- Profile für das Slicen wie in der Druckvorschau (`kevcad.json` → `druck.filament`, Drucker `p1p-0.4`); additiv
  `druck.platte` (Druckplatte mit dem Namen aus Bambu Studio, Vorgabe die des P1P: „Textured PEI Plate“). Die CLI setzt
  die Platte nicht selbst; ohne sie nimmt sie die Cool Plate, und PETG scheitert.

### Nachrichten (ohne Nutzlast)

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `PRINTER_CONFIG` | App → Kernel | `id`, `drucker` (Eintrag wie oben oder `null` = keiner) | `ACK`, danach `PRINTER_STATUS` |
| `PRINTER_STATUS_REQ` | App → Kernel | `id` | `PRINTER_STATUS` mit `reply_to` |
| `PRINTER_STATUS` | Kernel → App | siehe unten; beim Verbinden, bei jeder Änderung (höchstens 2 je s) und auf Anfrage | – |
| `PRINT_JOB_REQ` | App → Kernel | `id`, `platten` (leer = alle), `weg`, `bestaetigt` (false = nur vorbereiten, true = Kevin hat bestätigt), `optionen` (nur Weg B), `auftrag` (optional, aus `PRINT_JOB_ASK`) | `ACK`, danach `PRINT_JOB_RES` |
| `PRINT_JOB_RES` | Kernel → App | `reply_to`, `ok`, `auftrag`, `weg`, `schritt` (`vorbereitet`, `geoeffnet`, `gestartet`), `datei`, `platten`, `fehler`, `hinweise`, `ms` | – |
| `PRINT_JOB_ASK` | Kernel → App | `id`, `auftrag`, `platten`, `weg`, `von` (`agent`), `grund` | `ACK` (Dialog offen); Kevins Antwort als `PRINT_JOB_REQ` mit `auftrag` oder `PRINT_CONTROL` `verwerfen` |
| `PRINT_CONTROL` | App → Kernel | `id`, `aktion` (`aktualisieren`, `pause`, `fortsetzen`, `abbrechen`, `verwerfen`), `auftrag` (bei `verwerfen`) | `ACK` (`ok: false` mit Grund, wenn gesperrt) |

`optionen` (Weg B): `{"bett_nivellieren": true, "flussrate": true, "zeitraffer": false, "spule": "extern"}`.

`PRINTER_STATUS`:

```json
{"konfiguriert": true, "verbindung": "aus" | "verbindet" | "verbunden" | "getrennt" | "fehler", "meldung": "…",
 "drucker": {"id": "p1p", "name": "P1P", "modell": "P1P", "ip": "192.168.178.40", "firmware": "01.10.00.00",
             "modus": "cloud" | "lan" | "unbekannt", "entwicklermodus": false, "signal": "-45dBm"},
 "weg": "a",
 "wege": {"a": {"moeglich": true, "grund": null},
          "b": {"moeglich": false, "grund": "Developer Mode ist aus.", "anleitung": ["Einstellungen → WLAN …"]}},
 "steuern": false,
 "druck": {"zustand": "unbekannt" | "bereit" | "vorbereiten" | "druckt" | "pausiert" | "fertig" | "fehlgeschlagen",
           "gcode_state": "RUNNING", "fortschritt": 0.42, "schicht": 41, "schichten": 98, "restzeit_s": 3720,
           "aufgabe": "Kugelschieber Platte 1", "datei": "…gcode.3mf", "stufe": "druckt", "geschwindigkeit": "standard"},
 "temperaturen": {"duese": 219.5, "duese_ziel": 220.0, "bett": 55.0, "bett_ziel": 55.0},
 "fehler": [{"code": "0300-0100-0001-0001", "text": "…", "schwere": "fehler", "art": "hms"}],
 "kamera": false,
 "gefunden": [{"name": "P1P", "modell": "P1P", "ip": "192.168.178.40", "verbindung": "cloud", "kennung": "3fa2c1d09e7b"}],
 "auftrag": {"auftrag": "j-3", "zustand": "wartet" | "slict" | "bereit" | "oeffnet" | "geoeffnet" | "laedt_hoch" |
             "startet" | "gestartet" | "fehler" | "verworfen",
             "weg": "a", "platten": [1, 2], "fortschritt": 0.5, "meldung": "…", "datei": "…", "von": "kevin" | "agent"},
 "aktualisiert": 1792656000.0}
```

- Ohne Einstellungen: `konfiguriert: false`, `verbindung: "aus"`, `drucker: null`; Weg A geht trotzdem (slicen und
  öffnen), nur ohne Status.
- `druck` und `temperaturen` sind `null`, solange kein Bericht da ist; `fortschritt` 0–1, `restzeit_s` aus
  `mc_remaining_time` · 60.
- `steuern`: true nur, wenn die Sperre Steuerbefehle erlaubt (Weg B nachgewiesen); die App zeigt Pause, Fortsetzen und
  Abbruch nur dann.
- `gefunden`: passiv per SSDP gehörte Bambu-Drucker; `kennung` = die ersten 12 Hex-Zeichen von SHA-256 der
  Seriennummer (die App vergleicht mit dem eigenen Eintrag), nie die Seriennummer selbst.

### Ablauf

1. Kevin klickt „Drucken …“ (oder MCP `drucken` schickt `PRINT_JOB_ASK`, die App öffnet denselben Dialog). Beim
   Öffnen schickt die App `PRINT_JOB_REQ` mit `bestaetigt: false`: Der Kernel slict schon (Zwischenspeicher je Eingang
   und Profilen) und meldet `schritt: "vorbereitet"`.
2. Kevin bestätigt → `PRINT_JOB_REQ` mit `bestaetigt: true` (und `auftrag`, falls vorhanden). Weg A: Datei nach
   `<projekt>/output/<projekt>-platten.gcode.3mf` kopieren und mit `open -a BambuStudio` öffnen →
   `schritt: "geoeffnet"`. Weg B: Sperre prüfen, hochladen, starten → `schritt: "gestartet"`.
3. Eingang des Slicens ist das 3MF der Druckvorschau (`druck_export(ziel, platten)` von V-K). Enthält es keine
   Bambu-Projekteinstellungen, lädt der Kernel die aufgelösten Systemprofile (P1P 0.4, Prozess nach Schichthöhe,
   Filament je Material). Ohne Druckvorschau: Ersatzweg je Material aus den Druckteilen (Bambu Studio richtet aus und
   ordnet an), mit Hinweis.

### MCP

- `drucker_status()`: Verbindung, Modus, Wege mit Grund, laufender Druck, Temperaturen, Fehler, gefundene Drucker,
  letzter Auftrag. Nur lesen; ohne Seriennummer und Zugangscode.
- `drucken(platten=None, weg="a", grund=None)`: **nur auf Kevins ausdrücklichen Wunsch.** Schickt `PRINT_JOB_ASK`; es
  geschieht nichts, bis Kevin im Dialog bestätigt. Antwort: Auftrag und „wartet auf Kevins Bestätigung“.

### App

- `DruckerLeiste(model:)` in der Druckvorschau-Ansicht (Platz stimmt der Koordinator mit V-A ab): Zustand, Fortschritt,
  Schicht, Restzeit, Temperaturen, Fehler, Knopf „Drucken …“; Pause, Fortsetzen, Abbruch nur bei `steuern`.
- `DruckenDialog`: Platten (Auswahl), Material und Spule je Platte, Zeit, Weg (B ausgegraut mit Grund und Anleitung),
  „In Bambu Studio öffnen“ bzw. „Drucken“.
- `DruckerEinstellungen`: Name, IP, Seriennummer, Zugangscode (in den Schlüsselbund), Weg, „Status lesen“, gefundene
  Drucker zum Übernehmen von Name und IP.
- Selbsttest `KEVCAD_SELFTEST=drucker` gegen die Attrappe.

Testdateien: `tools/make_drucker_fixtures.py` (`printer_*.frame`, `print_job_*.frame`, `print_control*.frame`,
`ack_printer_*.frame`, Abschnitt `drucker` in `fixtures.json`); Beispiel und Prüfung in `protocol.py`
(`drucker_status_beispiel`, `check_drucker_message`).
