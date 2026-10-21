# Kev CAD · Bestand (Vertrag)

Version 1 (21.10.2026). Verbindlich für die Bestandsführung aus [PLAN-BESTAND.md](PLAN-BESTAND.md), erste Stufe:
Stangenware, Platten, Stückgut. Zukaufteile und Filament folgen. Änderungen nur gemeinsam: dieses Dokument,
`protocol.py`, Testdateien und Swift-Decoder im selben Commit (wie PROTOCOL.md).

## Datei

`~/Library/Application Support/<bundle-id>/bestand.json` (Testvarianten haben ihre eigene; Tests setzen
`KEVCAD_BESTAND_FILE`). Ein Bestand für alle Projekte. Schlüssel sind Katalog-ids aus KATALOG.md.

```json
{
  "version": 1,
  "einstellungen": {"mindestrest_mm": 100, "saegeblatt_mm": 3},
  "posten": {
    "rohr-alfer-12x1": {
      "ganze": {"anzahl": 2, "laenge": 1000},
      "reste": [
        {"kennung": "R-0007", "laenge": 430, "ort": "Regal 2", "seit": "2026-10-21"},
        {"kennung": "R-0008", "laenge": 610, "ort": null, "seit": "2026-10-21"}
      ],
      "mindestrest_mm": 80
    },
    "platte-multiplex-birke-18": {
      "ganze": {"anzahl": 1, "b": 2500, "h": 1250},
      "reste": [{"kennung": "P-0003", "b": 600, "h": 400, "ort": null, "seit": "2026-10-20"}]
    },
    "schraube-iso7380-m6": {"stueck": [{"laenge": 16, "anzahl": 40}, {"laenge": 20, "anzahl": 12}]},
    "mutter-din315-m4": {"stueck": [{"anzahl": 30}]}
  }
}
```

| Feld | Bedeutung |
|---|---|
| `ganze` | Stangenware: `anzahl`, `laenge` (Standard: `stangenlaenge` aus dem Katalog). Platten: `anzahl`, `b`, `h` (Standard: `platte` aus dem Katalog) |
| `reste` | einzelne Reste mit eindeutiger `kennung` (`R-` Stangen, `P-` Platten, fortlaufend über den ganzen Bestand), Länge bzw. `b` × `h` in mm, optional `ort`, `seit` (Datum) |
| `stueck` | Stückgut: Liste von `{anzahl}` bzw. bei Schrauben und Gewindestiften `{laenge, anzahl}` |
| `mindestrest_mm` | je Posten, überschreibt die Einstellung; kürzere Reste sind Verschnitt und kommen nicht in den Bestand |
| `einstellungen.saegeblatt_mm` | Schnittbreite für Stangen und Platten (Standard 3) |

Daneben `bestand-buchungen.jsonl`: eine Zeile je Buchung `{"id", "zeit", "art": "eintrag" | "gebaut" | "korrektur" |
"rueckgaengig", "projekt", "aenderungen": [...], "von": "kevin" | "agent", "grund"}`. Jede Buchung ist umkehrbar
(`rueckgaengig` mit Verweis auf die `id`).

## Zuschnitt mit Bestand

Der Kernel plant nach jedem Lauf je Stangenware und Platte:

1. Stücke absteigend nach Länge (Platten: nach Fläche).
2. Zuerst in den kleinsten passenden Rest, dann in ganze Stangen bzw. Platten aus dem Bestand, dann in neu zu kaufende.
3. Verbessern (scipy `milp` mit Zeitlimit 200 ms, sonst bleibt die Näherung): wenig neue Stangen bzw. Platten, wenig
   Verschnitt, lieber wenige lange Reste.
4. Platten mit Guillotine-Schnitten, Sägeblattbreite berücksichtigt.

Erweiterung von `BOM.cuts[i]` (additiv, PROTOCOL.md Phase 2):

```json
{"stock_id": "rohr-alfer-12x1", "...": "bisherige Felder",
 "quellen": [
   {"art": "rest", "kennung": "R-0008", "laenge": 610, "stuecke": [425, 175], "rest_neu": 4, "verschnitt": true},
   {"art": "bestand", "kennung": null, "laenge": 1000, "stuecke": [425, 425], "rest_neu": 144},
   {"art": "kaufen", "kennung": null, "laenge": 1000, "stuecke": [300], "rest_neu": 697}
 ],
 "neue_reste": [144, 697],
 "aus_bestand": {"reste": 1, "ganze": 1}, "kaufen": 1}
```

Platten: `quellen[i]` mit `b`, `h` statt `laenge`, `stuecke` als Liste `{"b", "h", "x", "y", "gedreht"}`, `rest_neu` als
Liste von Rechtecken.

Neu in `BOM`: `einkaufsliste`, `bestand_stand` (Zeitpunkt der Bestandsdatei), `fehlt` (bool).

```json
"einkaufsliste": [
  {"id": "rohr-alfer-12x1", "benennung": "ALFER-Rundrohr 12 × 1", "menge": 1, "einheit": "Stange 1000 mm",
   "preis_je": 3.9, "preis": 3.9, "link": null, "hinweis": null},
  {"id": "mutter-din315-m4", "benennung": "Flügelmutter DIN 315 M4", "menge": 4, "einheit": "Stück",
   "preis_je": 0.12, "preis": 0.48, "link": null, "hinweis": "Bestand 30, davon 26 in Projekt „Regal“ verplant"}
]
```

Kaufeinheiten: Stange, Platte, Stück (später Packung). Preis aus dem Katalog mit Stand; `link` aus einer optionalen
`bezugsquelle` am Katalogeintrag (`{"url", "name"}`, additiv in KATALOG.md).

## Reservieren und Buchen

- **Reservierung:** Jedes Projekt reserviert, was sein letzter Zuschnitt aus dem Bestand verplant (Reste nach
  Kennung, ganze Stangen und Stückgut nach Menge), gespeichert in `<projekt>/.kevcad/reservierung.json`. Die
  Planung eines Projekts zieht die Reservierungen anderer Projekte ab und nennt sie im `hinweis`.
- **„Gebaut“:** bucht die Reservierung des aktuellen Projekts ab: verplante Reste und ganze Stangen weg, `neue_reste`
  (ab Mindestrest) mit neuen Kennungen dazu, Stückgut abziehen. Nur auf Kevins ausdrücklichen Wunsch (App-Dialog oder
  seine Anweisung an Claude).

## Protokoll (additiv)

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `BESTAND_REQ` | App → Kernel | `id` | `BESTAND` |
| `BESTAND` | Kernel → App | `reply_to` (optional), `bestand` (Inhalt der Datei), `reserviert` (je id: Projekt und Menge), `stand` | – |
| `BESTAND_SAVE` | App → Kernel | `id`, `posten_id`, `posten` (ganzer Posten wie in der Datei oder null zum Entfernen), `grund` | `ACK`, danach `BESTAND` und neue `BOM` |
| `GEBAUT_REQ` | App → Kernel | `id`, `run` | `ACK` mit Buchungs-id, danach `BESTAND` und `BOM` |
| `BUCHUNG_RUECKGAENGIG` | App → Kernel | `id`, `buchung` | `ACK`, danach `BESTAND` und `BOM` |

Nach dem Verbinden schickt der Kernel `BESTAND` von selbst (wie `CATALOG` auf Anfrage, hier immer).

## MCP

- `bestand_liste(id=None)` – Bestand, Reste, Reservierungen.
- `bestand_eintragen(id, ganze=…, reste=…, stueck=…, grund)` – nur nach Kevins Angabe; die Antwort nennt jede Änderung.
- `einkaufsliste()` – Fehlmengen des aktuellen Projekts mit Preis und Summe, als Text und CSV-Pfad.
- `gebaut_buchen()` – nur wenn Kevin ausdrücklich sagt, dass das Projekt gebaut ist; nennt, was abgebucht wird und
  welche Reste neu entstehen.
- `buchung_rueckgaengig(id)`.

## App

- Fenster „Bestand“ als eigener Bereich im Lagerkatalog (⇧⌘K): je Lagerteil ganze Stangen bzw. Platten, Reste mit
  Kennung, Länge und Ort, Stückgut; schnelles Erfassen („+1 Stange“, „Rest …“, „−1“), Bearbeiten, Entfernen,
  Reservierungen je Projekt sichtbar, Buchungsprotokoll mit „Rückgängig“.
- Stückliste: Zuschnittansicht zeigt je Stange bzw. Platte die Stücke, farbig nach Quelle (Rest, Bestand, kaufen),
  neue Reste markiert, Verschnitt grau; darunter die Einkaufsliste mit Summe, Export als CSV und „Kopieren“ als Text.
- Dialog „Gebaut …“ mit Vorschau der Buchung (was weg, was neu) und Bestätigung.
