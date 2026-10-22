# Kev CAD · Bestand (Vertrag)

Version 1 (21.10.2026), geändert am selben Abend: **Bestand je Projekt** (Kevin: „Ich brauche das nicht über Projekte
hinweg, sondern individuell nur für das jeweilige Projekt.“). Verbindlich für die Bestandsführung aus [PLAN-BESTAND.md](PLAN-BESTAND.md), erste Stufe:
Stangenware, Platten, Stückgut. Zukaufteile und Filament folgen. Änderungen nur gemeinsam: dieses Dokument,
`protocol.py`, Testdateien und Swift-Decoder im selben Commit (wie PROTOCOL.md).

## Datei

`<projekt>/bestand.json`, **ein Bestand je Projekt**: das Material, das Kevin für genau dieses Projekt hat. Es gibt
keinen projektübergreifenden Bestand und keine Reservierungen zwischen Projekten. Tests setzen `KEVCAD_BESTAND_FILE`.
Schlüssel sind Katalog-ids aus KATALOG.md. Die Datei gehört nicht zu den Versionen des Modells (Wiederherstellen einer
Konstruktion ändert den Bestand nicht).

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

Daneben `<projekt>/.kevcad/bestand-buchungen.jsonl`: eine Zeile je Buchung `{"id", "zeit", "art": "eintrag" | "gebaut" | "korrektur" |
"rueckgaengig", "projekt", "aenderungen": [...], "von": "kevin" | "agent", "grund"}`. Jede Buchung ist umkehrbar
(`rueckgaengig` mit Verweis auf die `id`).

## Zuschnitt mit Bestand

Der Kernel plant nach jedem Lauf je Stangenware und Platte:

1. Stücke absteigend nach Länge (Platten: nach Fläche).
2. Zuerst in den kleinsten passenden Rest, dann in ganze Stangen bzw. Platten aus dem Bestand, dann in neu zu kaufende.
3. Verbessern (scipy `milp` mit Zeitlimit 200 ms, sonst bleibt die Näherung): wenig neue Stangen bzw. Platten, wenig
   Verschnitt, lieber wenige lange Reste.

Platten in `BOM.cuts`: `art: "platte"` am Cut und `platte: {"b", "h"}` statt `stangenlaenge`/`stangen`; `quellen[i]` mit
`b`, `h`, `stuecke: [{"b", "h", "x", "y", "gedreht"}]`, `rest_neu: [{"b", "h", "x", "y"}]` (x, y für die Zeichnung).
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

Neu in `BOM`: `einkaufsliste`, `bestand_stand` (Zeitpunkt der Bestandsdatei), `fehlt` (bool).

```json
"einkaufsliste": [
  {"id": "rohr-alfer-12x1", "benennung": "ALFER-Rundrohr 12 × 1", "menge": 1, "einheit": "Stange 1000 mm",
   "preis_je": 3.9, "preis": 3.9, "link": null, "hinweis": null},
  {"id": "mutter-din315-m4", "benennung": "Flügelmutter DIN 315 M4", "menge": 4, "einheit": "Stück",
   "preis_je": 0.12, "preis": 0.48, "link": null, "hinweis": "Bestand im Projekt: 10, gebraucht: 14"}
]
```

Kaufeinheiten: Stange, Platte, Stück (später Packung). Preis aus dem Katalog mit Stand; `link` aus einer optionalen
`bezugsquelle` am Katalogeintrag (`{"url", "name"}`, additiv in KATALOG.md).

## Buchen

- Der Zuschnitt eines Projekts verplant nur dessen eigenen Bestand; es gibt nichts zu reservieren.
- **„Gebaut“:** bucht ab, was der aktuelle Zuschnitt aus dem Projektbestand verplant: verplante Reste und ganze Stangen
  weg, `neue_reste` (ab Mindestrest) mit neuen Kennungen dazu, Stückgut abziehen. Nur auf Kevins ausdrücklichen Wunsch
  (App-Dialog oder seine Anweisung an Claude).

## Protokoll (additiv)

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `BESTAND_REQ` | App → Kernel | `id` | `BESTAND` |
| `BESTAND` | Kernel → App | `reply_to` (optional), `bestand` (Inhalt der Projektdatei oder null ohne Projekt), `buchungen` (die letzten 50 Buchungen, neueste zuerst, je Zeile wie in der Datei plus `zusammenfassung` als Text und `rueckgaengig_durch` mit der id der Umkehrbuchung oder null), `stand` (ISO-Zeit) | – |
| `BESTAND_SAVE` | App → Kernel | `id`, entweder `posten_id` und `posten` (ganzer Posten wie in der Datei oder null zum Entfernen) oder `einstellungen` (ganzes Objekt), `grund` | `ACK`, danach `BESTAND` und neue `BOM` |
| `GEBAUT_REQ` | App → Kernel | `id`, `run` | `ACK` mit `buchung` (id) und `message` (Kurztext), danach `BESTAND` und `BOM` |
| `BUCHUNG_RUECKGAENGIG` | App → Kernel | `id`, `buchung` | `ACK`, danach `BESTAND` und `BOM` |

Nach dem Verbinden und nach jedem Projektwechsel schickt der Kernel `BESTAND` von selbst.

## MCP

- `bestand_liste(id=None)` – Bestand und Reste des offenen Projekts.
- `bestand_eintragen(id, ganze=…, reste=…, stueck=…, grund)` – nur nach Kevins Angabe; die Antwort nennt jede Änderung.
- `einkaufsliste()` – die Einkaufsliste genau wie in der App (Abschnitt „Einkaufsliste wie in der App“): Text, CSV-Pfad,
  Gruppen und Summen.
- `gebaut_buchen()` – nur wenn Kevin ausdrücklich sagt, dass das Projekt gebaut ist; nennt, was abgebucht wird und
  welche Reste neu entstehen.
- `buchung_rueckgaengig(id)`.

## App

- Bereich „Bestand“ im **Projektfenster** (neben der Stückliste, nicht im Lagerkatalog): je Lagerteil ganze Stangen
  bzw. Platten, Reste mit Kennung, Länge und Ort, Stückgut; schnelles Erfassen („+1 Stange“, „Rest …“, „−1“),
  Bearbeiten, Entfernen, Einstellungen (Mindestrest, Sägeblatt), Buchungsprotokoll mit „Rückgängig“. Lagerteile zum
  Erfassen kommen aus dem Katalog.
- Stückliste: Zuschnittansicht zeigt je Stange bzw. Platte die Stücke, farbig nach Quelle (Rest, Bestand, kaufen),
  neue Reste markiert, Verschnitt grau; darunter die Einkaufsliste mit Summe, Export als CSV und „Kopieren“ als Text.
- Dialog „Gebaut …“ mit Vorschau der Buchung (was weg, was neu) und Bestätigung.
- Seit dem Strang „Material“ (22.10.2026) zeigt das alles der Bereich **„Material“** im Projektfenster (⌘3):
  Übersicht, Stückliste, Zuschnitt, Bestand, Einkaufsliste (mit Abhaken, Teilen als Text oder CSV), Zukaufteile,
  Druckteile. Unter dem Viewport bleiben Stückliste und Zuschnitt als einzeln aufklappbare Schnellansichten (⌃⌘1, ⌃⌘2,
  ⇧⌘B alle). Eine Datenquelle für Bildschirm und Berichte: `MaterialDaten` im App-Kern
  (`app/KevCADCore/Sources/KevCADCore/Material/`). Seit dem Strang „Material im Kernel“ (22.10.2026) liefert der Kernel
  über MCP und Export genau dieselbe Einkaufsliste und denselben Verschnitt (die beiden folgenden Abschnitte).

## Einkaufsliste wie in der App (22.10.2026)

Was Claude über MCP liest, ist das, was Kevin im Bereich „Material“ sieht und teilt. Kernel: `bestand/einkauf.py`
(`zusammenstellen`, `text`, `csv`), App: `MaterialDaten` und `MaterialText`. Gruppen in fester Reihenfolge:

| Gruppe | Inhalt | in der Summe |
|---|---|---|
| Lagerware | `BOM.einkaufsliste`: Fehlmengen nach Abzug des Projektbestands in Kaufeinheiten, Normteile zum Kaufen eingeschlossen | ja |
| Zukaufteile | je Stücklistenzeile eines Zukaufteils (auch `kamera`, `objektiv`, `kamerazubehoer`) die ganze Anzahl, Preis und Link aus der Zeile (Katalog), Hinweis „Hersteller · Nummer · EAN …“; der Bestand führt sie noch nicht | ja |
| Normteile abzählen | `BOM.stueckgut`: „16 gebraucht, 12 aus Bestand, 4 kaufen“ | nein |
| Filament für Druckteile | je Material aus der Druckvorschau desselben Laufs (`summe.material`, Teile aus `teile[].anzahl`, mit Ersatzteilen), sonst aus den Druckteilen der Stückliste (Volumen × Dichte) | nein |

- **Summe** = Lagerware + Zukaufteile, wie die Kennzahl „Summe“ der App. Gerundet wird wie `KevFormat` (halbe Werte von
  der Null weg, Tausenderpunkt; Nachbau in `kernel/src/kevcad_kernel/appformat.py`).
- **Text** wie „Als Text teilen“: Kopf „Einkaufsliste <Projekt> (Stand TT.MM.JJJJ)“, je Kaufzeile
  „- [ ] 1 × Stange 1.000 mm: ALFER-Rundrohr 12 × 1, 3,90 € (Link)“ mit Hinweis darunter, „Summe: ≈ 84,62 €“, dann
  Normteile und Filament („- PETG: 188,8 g für 7 Teile, 3,21 € (Druckvorschau, Teils Bambu Studio)“). Abgehakte Zeilen
  („- [x] “) kennt nur die App.
- **CSV** (`EXPORT_REQ einkaufsliste_csv`, MCP, „Als CSV teilen“ und „in output/ sichern“ der App), Datei
  `<projekt>/output/<Projekt>-einkaufsliste.csv` (Name wie `EinkaufslisteFormat.dateiname`): UTF-8 mit BOM, Semikolon,
  CRLF, Spalten `Gruppe;Menge;Einheit;Benennung;Lagerteil;Preis je (EUR);Preis (EUR);Preisstand;Bezugsquelle;Link;Hinweis`,
  Zahlen mit Komma ohne Tausenderpunkt; nach den Kaufzeilen `;;;Summe;;;<Summe>;;;;`, danach Normteile (Menge =
  gebraucht) und Filament (Menge in g, Lagerteil = Material-id, Kosten im Hinweis) ohne Preis.
- **Entscheidung:** Die App rendert Text und CSV weiter selbst, der Kernel rendert dieselben Bytes; die App nimmt nicht
  den Kernel-Export. Begründung: Teilen braucht den Text sofort (ShareLink, Kopieren, Demo und älterer Kernel ohne
  Rundreise), und nur die App kennt abgehakte Zeilen und das Teilen-Datum. Gleich hält beide Seiten die Testdatei
  `material` in fixtures.json (`kernel/tools/make_bestand_fixtures.py`, Beispiel mit Resten, Normteilen, Zukauf mit und
  ohne Link, Druckteilen und Druckvorschau): `MaterialKernelGleichTests` (Swift) vergleicht Text und CSV Byte für Byte,
  Summen und Verschnitt; `test_material_einkauf.py` prüft, dass die Testdatei zum Kernel passt.
- **MCP** `einkaufsliste()`: `text`, `csv` (Pfad), `lagerware`, `zukauf`, `normteile`, `filament` (je Zeile `werkstoff`,
  `material`, `teile`, `gramm`, `preis`, `quelle` `druckvorschau` | `stueckliste`, `stand`), `positionen`, `summe`,
  `summe_lager`, `summe_zukauf`, `ohne_preis`; die bisherigen Felder der Stückliste bleiben (`einkauf_summe` ist nur
  Lagerware). `bom` zeigt denselben Text (`einkauf_text`), `run` die Kennzeile („5 Positionen, ≈ 84,62 €“).

## Verschnitt (Definition 2, 22.10.2026)

Verschnitt ist, was weder Stück noch verwertbarer Rest ist: **Sägeschnitte und Reste unter dem Mindestrest, bezogen auf
die verplante Länge bzw. Fläche aller Quellen; neue Reste ab Mindestrest zählen nicht** (sie kommen in den Bestand).
Je Stange `Länge − Stücke − (Rest, falls ab Mindestrest)`, je Platte `Fläche − Stücke − neue Restrechtecke`; Prozent =
Summe Verschnitt / Summe verplant · 100, auf 0,1 gerundet wie die App. Kernel `bom.verschnitt_bilanz`, App
`MaterialZuschnitt.bilanz`.

- `BOM.cuts[i].verschnitt_prozent` trägt (additiv) den neuen Wert, dazu `verschnitt_definition: "2"`. Mit Bestand über
  die Quellen gerechnet (`quellen[i].verschnitt` entscheidet über den Rest, sonst der Mindestrest), ohne Quellen über
  `stangen` mit dem Standard-Mindestrest 100 mm. Fehlt `verschnitt_definition` (älterer Kernel), meinte das Feld bei
  Stangen alles außer den Stücken; die App rechnet dann selbst.
- `BOM.verschnitt` (additiv): `{"definition": "2", "stangen": 0.6 | null, "platten": 1.2 | null}`, über alle Zuschnitte
  wie die Kennzahl „Verschnitt“ der App (Summen, nicht Mittelwert der Prozente).
- Gilt für BOM bzw. Zuschnitt im Protokoll, MCP `bom` (Zeile „Verschnitt gesamt“, je Zuschnitt „Verschnitt 0,6 %“),
  die Stücklisten-CSV (`bom_csv`) und die Berichte der App.

## Ergänzungen des Kernels (S-K, additiv und optional)

Was der Kernel über den Vertrag hinaus liefert; ältere Gegenseiten ignorieren es. Umsetzung in
`kernel/src/kevcad_kernel/bestand/`, Testdateien aus `kernel/tools/make_bestand_fixtures.py` (Abschnitt `bestand` in
`fixtures.json`), Ersatz-Kernel mit `fake_kernel.py --bestand`.

- **BESTAND:** `datei` (Pfad der Projektdatei oder null), `fehler` (Text, wenn bestand.json kaputt ist; `bestand` ist
  dann null). Ohne Bestandsdatei, aber mit Projekt: leerer Bestand mit Standard-Einstellungen, `stand` null.
- **Buchungen:** `aenderungen[i]` mit `op` (`posten` mit `vorher`/`nachher`, `einstellungen`, `ganze` mit `delta`,
  `rest_weg`, `rest_neu` mit `rest`, `stueck` mit `laenge` und `delta`); Umkehrbuchungen tragen `bezug` (id der
  umgekehrten Buchung), Gebaut-Buchungen `run` und `sitzung` (Kernelstart; derselbe Lauf wird nur einmal als gebaut
  gebucht). Ids `B-0001` fortlaufend je Projekt.
- **BESTAND_SAVE:** Reste ohne `kennung` bekommen eine neue, `seit` ist sonst heute. Ohne Änderung: `ACK` mit `ok` und
  `message` „keine Änderung“, ohne `buchung`, danach nichts. ACK auf BESTAND_SAVE und BUCHUNG_RUECKGAENGIG trägt wie
  bei GEBAUT_REQ `buchung`, wenn gebucht wurde.
- **BOM.lines** (Platten): `breite`, `tiefe` (Zuschnittmaß, bei `form=` das Hüllrechteck).
- **BOM.cuts:** Stangen tragen `art: "stange"`; jeder Cut mit Bestand trägt `mindestrest`. `quellen[i].verschnitt` ist
  immer da: true nur bei 0 < `rest_neu` < Mindestrest. Weicht `einstellungen.saegeblatt_mm` von 3 ab, sind auch die
  bisherigen Felder (`saegeschnitt`, `stangen`, `preis_stangen`) mit dieser Schnittbreite gerechnet;
  `verschnitt_prozent` siehe „Verschnitt (Definition 2)“. Platten: `platte` ist null ohne Standardformat im Katalog (dann wird je Stück ein Zuschnitt gekauft),
  `neue_reste` als Liste `{b, h}`, `verschnitt_prozent` nach Definition 2, optional `zu_gross` (Liste `{b, h}`).
  In `stuecke` sind `b` und `h` die Lage auf der Platte (b entlang x); `gedreht` heißt: gegenüber `breite` × `tiefe`
  der Zeile um 90° gedreht. Platten haben ihren Ursprung links unten, Stücke liegen ohne Randschnitt an der Kante.
- **BOM.stueckgut:** je Schraube (nach Länge), Mutter, Scheibe `{stock_id, benennung, masse_text, laenge, anzahl,
  aus_bestand, kaufen}`. Bestandszeilen ohne `laenge` passen zu jeder Schraubenlänge.
- **BOM:** `einkauf_summe` (€ oder null), `einkauf_hinweis` (Richtpreise mit Stand, Positionen ohne Preis).
  `einkaufsliste[i]` zusätzlich `link_text` (Name der Bezugsquelle) und `preis_stand`; `einheit` auch
  „Sonderlänge 1.200 mm“ (Stück länger als die Stange) und „Zuschnitt 800 × 600 mm“.
- **EXPORT_REQ:** Format `einkaufsliste_csv` nach `<projekt>/output/<Projekt>-einkaufsliste.csv`, ohne Export-Sperre;
  seit 22.10.2026 die ganze Liste wie in der App (Abschnitt „Einkaufsliste wie in der App“).
- **MCP:** `bestand_eintragen` zusätzlich mit `reste_entfernen`, `reste_ersetzen` und `mindestrest_mm`; `grund` ist
  Pflicht (Kevins Worte), ebenso bei `gebaut_buchen`. `run` nennt die Einkaufsliste in einer Zeile.
- **Zuschnitt:** 1D-Näherung wie oben, danach `scipy.optimize.milp` (200 ms, nur wenn besser nach derselben Bewertung:
  wenig kaufen, wenig Verschnitt, wenige Reste danach, Reste vor ganzen Stangen). Platten: Guillotine mit freien
  Rechtecken, 27 Varianten (Sortierung, Wahl, Schnittrichtung) im Zeitlimit, die beste gilt.
