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
- Präzisierung (V-K): Filamentprofile nur, wenn ihre `compatible_printers` (mit Vererbung über `inherits`) „Bambu Lab
  P1P 0.4 nozzle“ nennen (Benutzerprofile ohne eigene Liste erben sie); Reihenfolge `druck.filament`, dann Kevins Liste
  (`Amazon Basics PLA`, `Bambu PETG Basic @BBL X1C` …), dann das beste passende Systemprofil gleichen Typs („@BBL P1P“
  zuerst). `Bambu PETG Basic @BBL X1C` ist Bambus PETG-Basic-Profil für P1P und X1 (nennt den P1P 0.4).
- `druck.platte` (additiv): Druckplatte als Bambu-Name (`Textured PEI Plate` Vorgabe, `High Temp Plate`, `Cool Plate`,
  `Engineering Plate`, `Supertack Plate`) oder kurz (`texturiert`, `glatt`, `cool`, `engineering`); geht als
  `curr_bed_type` in jeden Slicer-Lauf und ins 3MF (die Kommandozeile nähme sonst die Cool Plate, PETG bricht dort ab).
  Passt das Filament nicht zur Platte, meldet die Vorschau einen Fehler (`art: "platte"`) und slict nicht.
  `einstellungen.platte` nennt die benutzte Platte.

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
  hat, dazu `"zweck"`, wenn der Zweck vorgegeben ist), `fest_von: {schlüssel: "kevin" | "agent"}` (wer jede feste
  Vorgabe gesetzt hat; aus `PRINT_SETTINGS.von` bzw. dem MCP), `profil: {"prozess", "filament"}`
  (Bambu-Studio-Profile), `risiko` (0–1, Fehldruck-Wahrscheinlichkeit), `stuetzen_g` (Stützmaterial aller Stück),
  `kosten`, `abweichung_material` (wie `abweichung`, für das Filament). `abweichung` = Schätzung der Zeit / Slicer − 1.
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

Präzisierungen (additiv): `PRINT_SETTINGS.von` (`kevin` Vorgabe, `agent` vom MCP), in `druck.json` je Vorgabe
gespeichert (`"von": {"waende": "kevin", "zweck": "agent"}`) und als `teile[].fest_von` ausgegeben; ein Wert `null` in
`einstellungen` nimmt diese Vorgabe zurück; `zuruecksetzen: true` nimmt alle Vorgaben des Teils bzw. der Gruppe
zurück. Gespeichert wird je Teilname (aus `show()`), damit die Vorgabe Formänderungen übersteht; eine Gruppe schreibt
alle ihre Teile. `PRINT_EXPORT_REQ.ziel` `null` = `<projekt>/output/<projekt>-druck.3mf`. `PRINT_EXPORT_RES` additiv
`hinweise`, `ms`, `geprueft` (die Datei wurde zur Kontrolle in Bambu Studio geladen), `pfade` und `dateien`
(`[{"pfad", "material", "filament", "platten"}]`).

**3MF (Eingang von Phase 8):** je Material ein Bambu-Studio-Projekt (`pfad` ist das erste, bei mehreren Materialien
heißen sie `<ziel>-<material>.3mf`): Platten mit den Lagen der Vorschau, Drucker-, Prozess- und Filamentprofil in
`Metadata/project_settings.config`, Einstellungen je Teil (Schicht, Wände, Decken, Böden, Füllung, Muster, Stützen,
Brim) in `Metadata/model_settings.config`. `BambuStudio --slice 0 <datei>` übernimmt sie; geprüft am 22.10.2026:
Zeit und Filament nachgeslict wie in der Vorschau (±0,3 %). Ein Filament je Datei, weil Bambu Studio 2.07 Projekte mit
mehreren Filamenten aus der Kommandozeile nicht wieder slicen kann (Teile landen auf Filament 1); der P1P ohne AMS
druckt ohnehin ein Material je Platte. Ohne Bambu Studio schreibt der Kernel die 3MF selbst: je Platte eine Datei
(`<ziel>[-<material>]-platte<n>.3mf`, Teile in ihrer Lage, ohne Profile), weil Bambu Studio Platten nur aus eigenen
Projekten liest. Laufzeit: `druck_export(ziel=None, platten=None) -> {"ok", "pfad", "platten", "fehler", "pfade", "dateien",
"hinweise", "geprueft", "ms"}`.

**Druckprüfung, Abdrücke (V-K, 22.10.2026):** Schichtraster-Hinweise an Flächen, deren Eckpunkte alle näher als
1,5 mm an einem gezeigten Lager- oder Zukaufteil liegen (Aussparung um ein fremdes Teil), fasst die Prüfung je Teil
und fremdem Teil zu einem Hinweis `druck_schichtraster_abdruck` zusammen („6 Flächen aus der Aussparung für
ALUTEC-Rahmen liegen nicht im Schichtraster (unkritisch, Passung prüfen)“, `wert.abdruck_von`).

Testdateien:
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
