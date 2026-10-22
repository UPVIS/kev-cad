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
