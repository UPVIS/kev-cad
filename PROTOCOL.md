# Kev CAD · Protokoll zwischen Kernel und App

Version 1 (21.10.2026). Verbindlich für `kernel/src/kevcad_kernel/protocol.py` (Referenz) und
`app/KevCADCore/Sources/KevCADCore/Protocol/`. Testdateien beider Seiten liegen in
`app/KevCADCore/Tests/KevCADCoreTests/Fixtures/` und werden mit `kernel/tools/make_fixtures.py` erzeugt.

Änderungen nur gemeinsam: Protokoll, Referenz-Implementierung, Testdateien und beide Decoder im selben Commit.

## Verbindung

- Unix-Socket. Der **Kernel-Server lauscht**, die App verbindet sich. Pfad: `AppInfo.kernelSocket`
  (`~/Library/Application Support/<bundle-id>/kernel.sock`), dem Kernel als `--socket` übergeben.
- Eine Verbindung, beide Richtungen. Sobald die App sich verbindet (nicht erst nach `HELLO_APP`), schickt der Kernel
  `HELLO`, `PROJECT` (falls offen), `STATUS`, `AGENT` und
  ein `PART_UPSERT` für jedes aktuelle Teil, damit die App den vollen Stand hat.
- Einheiten: Millimeter, Grad für Winkel. Koordinatensystem rechtshändig, **Z nach oben** (wie build123d).

## Rahmen

```
u32 LE  Länge des JSON-Kopfes in Byte
JSON    UTF-8, ein Objekt
u32 LE  Länge der Nutzlast in Byte (0 = keine)
Bytes   Nutzlast
```

Jeder Kopf hat `type` und `seq` (je Absender fortlaufend ab 1). Anfragen haben `id` (je Absender eindeutig, Text),
Antworten `reply_to` mit der `id` der Anfrage. Fehlerantwort auf jede Anfrage:
`{"type": "ERROR", "reply_to": "...", "message": "..."}`.

## Referenzen

| Form | Bedeutung |
|---|---|
| `Halter/Lasche` | Teil (Name aus `show()`, `/` bildet den Baum) |
| `Halter/Lasche#f12` | Fläche 12 in der Reihenfolge von `part.faces()` |
| `Halter/Lasche#e3` | Kante 3 in der Reihenfolge von `part.edges()` (degenerierte Kanten sind nicht mitgezählt) |
| `Halter/Lasche#v2` | Punkt 2 in der Reihenfolge von `part.vertices()` |

Referenzen gelten für einen Lauf. Wo eine Referenz verschickt wird, steht die Laufnummer `run` daneben.

Auto-Lauf: Der Kernel beobachtet `model.py` des offenen Projekts selbst und startet bei `auto_run` nach dem Speichern
(300 ms entprellt) einen Lauf. So gilt dasselbe für Änderungen durch den Agenten und durch Kevin.

## Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `HELLO` | `protocol: 1`, `kernel_version`, `build123d`, `mcp_port` | – |
| `STATUS` | `state`: `ready` \| `busy` \| `error`, `message` | – |
| `PROJECT` | `path`, `name`, `model` (Pfad zu model.py), optional `reply_to` | – |
| `RUN_START` | `run`, `file_hash`, `params` (Objekt), `slow_ms` | – |
| `STEP` | `run`, `index` (ab 1), `text` | – |
| `PART_UPSERT` | siehe unten | Geometrie |
| `PART_REMOVE` | `run`, `name` | – |
| `RUN_END` | `run`, `duration_ms`, `parts` (Anzahl), `triangles`, `warnings` (Liste Text), `params` (alle `param()`-Werte) | – |
| `RUN_ERROR` | `run`, `message`, `line` (oder null), `excerpt` (Codezeilen um den Fehler), `traceback` (gekürzt), `hint` (Reparaturhinweis oder null) | – |
| `AGENT` | `connected` (bool), `activity` (Text oder null, z. B. „misst Abstand Lasche ↔ Grundplatte"), `sessions` (Liste der Claude-Sitzungen, siehe unten) | – |
| `VIEW_CMD` | `id`, `cmd`, `args` – siehe unten; App antwortet `ACK` | – |
| `SCREENSHOT_REQ` | `id`, `width`, `height`, `source`: `current` \| `offscreen`, `view` (nur offscreen: Standardansicht oder null), `hide_overlays` | – |
| `MEASURE_RES` | `reply_to`, `result` (siehe Messen) | – |
| `EXPORT_RES` | `reply_to`, `files` (Liste absoluter Pfade) | – |
| `ACK` | `reply_to`, `ok`, `message` | – |

### AGENT.sessions

Additiv, für den Spiegel aufs iPhone ([MIRROR.md](MIRROR.md), „Sitzungen“): je Claude-Sitzung, die Kev CAD bedient,
`{"session_id", "aktiv", "seit", "taetigkeit", "zuletzt"}` (`zuletzt` optional), die aktive zuerst. `session_id` ist die
`CLAUDE_CODE_SESSION_ID` der MCP-Brücke `kevcad-mcp`; sie schickt sie bei jeder Anfrage im HTTP-Kopf
`x-claude-code-session-id`. Aktiv ist genau die Sitzung mit dem letzten verändernden Werkzeugaufruf (alles außer nur
lesenden Werkzeugen) der letzten 10 Minuten; `taetigkeit` ist die laufende bzw. zuletzt gezeigte Tätigkeit; eine
Sitzung fällt aus der Liste, sobald ihre MCP-Verbindung endet. Der Kernel schickt AGENT bei jeder Änderung neu.

### PART_UPSERT

Kopf:

```json
{
  "type": "PART_UPSERT", "seq": 7, "run": 3,
  "name": "Halter/Lasche",
  "color": [0.72, 0.75, 0.79, 1.0],
  "material": "aluminium",
  "bbox": {"min": [x, y, z], "max": [x, y, z]},
  "props": {"volume": 1234.5, "area": 890.1, "mass": 3.33, "center": [x, y, z]},
  "counts": {"vert": 24, "tri": 12, "face": 6, "edge": 12, "epts": 24, "vtx": 8},
  "faces": [{"t": "plane", "a": 200.0, "n": [0, 0, 1], "c": [0, 0, 15]}],
  "edges": [{"t": "line", "l": 10.0}],
  "transform": null
}
```

- `color` RGBA 0…1 so, wie in model.py angegeben, also **sRGB**; die App rechnet für den Viewport in linear um.
  `material` ist der Name aus model.py (z. B. „aluminium“); `props.mass` nur, wenn das Material bekannt ist (Masse in g).
- `faces[i]`: `t` ∈ `plane`, `cylinder`, `cone`, `sphere`, `torus`, `bspline`, `other`; `a` Flächeninhalt mm².
  Je nach Typ zusätzlich `n` (Normale, Ebene), `c` (Punkt auf der Ebene oder Mittelpunkt), `ax` (Achsrichtung),
  `r` (Radius), `r2` (zweiter Radius bei Torus und Ellipse), `ang` (Halbwinkel beim Kegel).
- `edges[i]`: `t` ∈ `line`, `circle`, `ellipse`, `bspline`, `other`; `l` Länge mm; bei Kreisen `r`, `c`, `ax`.
- `transform`: null (Punkte sind Weltkoordinaten). Reserviert für Instanzen: 16 Zahlen, spaltenweise.

Nutzlast, Arrays in dieser Reihenfolge direkt hintereinander, alle little-endian, alle Längen aus `counts`:

| Array | Typ | Anzahl Werte |
|---|---|---|
| positions | f32 | vert × 3 |
| normals | f32 | vert × 3 |
| triangles | u32 | tri × 3 (Indizes in positions) |
| tri_face | i32 | tri (Flächenindex je Dreieck) |
| edge_points | f32 | epts × 3 |
| edge_offsets | u32 | edge + 1 (Kante k = Punkte `edge_offsets[k] ..< edge_offsets[k+1]`, ein Polygonzug) |
| vertices | f32 | vtx × 3 (B-Rep-Punkte) |

Die App teilt Teile mit mehr als 16.000 Dreiecken oder Kantensegmenten selbst auf (Grenze der Pick-ID im Viewport).

### VIEW_CMD

| cmd | args |
|---|---|
| `view` | `standard` (`top`, `bottom`, `front`, `back`, `left`, `right`, `iso`, `iso_front_left`, `iso_back_right`, `iso_back_left`) oder null, `projection` (`perspective` \| `orthographic` \| null), `display` (`shaded_edges` \| `shaded` \| `wireframe` \| `xray` \| null), `fit` (bool) |
| `focus` | `refs` (Liste), `animate` (bool) |
| `visibility` | `mode`: `show` \| `hide` \| `isolate` \| `show_all`, `refs` (Teile) |
| `highlight` | `refs`, `color` (RGBA oder null für Standard), `label` (Text oder null), `clear` (bool, vorherige entfernen) |
| `section` | `enabled` (bool), `axis` (`x` \| `y` \| `z`) oder `normal` [x,y,z], `offset` (mm) |
| `explode` | `factor` (0 = zusammengebaut … 1 = voll) |
| `annotate` | `kind`: `dimension` \| `label` \| `arrow`, `points` (Liste [x,y,z]), `text`, `id` (zum späteren Entfernen) |
| `clear_annotations` | `ids` (Liste oder null = alle) |

Antwort: `ACK` mit `ok` und optional `message`.

### Messen (MEASURE_RES.result)

```json
{
  "refs": ["Halter/Lasche#f3", "Grundplatte#f0"], "run": 3,
  "kind": "distance",
  "values": {"distance": 12.5, "dx": 0.0, "dy": 0.0, "dz": 12.5, "angle": 0.0, "parallel": true},
  "points": [[x, y, z], [x, y, z]],
  "text": "Abstand 12,500 mm (dz 12,500)"
}
```

`kind` ∈ `distance`, `angle`, `face`, `edge`, `vertex`, `part`. Für ein Element stehen die Eigenschaften in `values`
(z. B. `area`, `radius`, `length`, `volume`, `mass`, `bbox`). `points` sind die Endpunkte für die Anzeige im Viewer.

## App → Kernel

| type | Felder | Antwort |
|---|---|---|
| `HELLO_APP` | `app_version`, `bundle_id` | – (Kernel schickt `HELLO` usw.) |
| `PROJECT_OPEN` | `id`, `path` (Projektordner) | `PROJECT` mit `reply_to` |
| `PROJECT_NEW` | `id`, `path` (neuer Ordner), `template` (`empty` \| `example`) | `PROJECT` mit `reply_to` |
| `RUN_REQ` | `id`, `params` (Objekt oder null), `slow_ms` (0 = normal) | `ACK`, dann `RUN_*` |
| `MEASURE_REQ` | `id`, `refs` (1 oder 2), `run`, `show` (bool) | `MEASURE_RES` |
| `SELECTION` | `run`, `refs` (Liste, kann leer sein) | – (Kernel merkt sich die Auswahl für MCP `selection`) |
| `SETTINGS` | `auto_run` (bool), `slow_ms` (Zeitlupe für Läufe aus der App, 0 = aus) | – |
| `EXPORT_REQ` | `id`, `formats` (`step`, `stl`, `3mf`, `glb`), `parts` (Liste oder null) | `EXPORT_RES` |
| `SCREENSHOT_RES` | `reply_to`, `ok`, `width`, `height`, `camera` (Objekt), `mm_per_px` (nur orthographisch, sonst null) | PNG |
| `ACK` | `reply_to`, `ok`, `message` | – |

## Bestand

Bestand, Zuschnitt mit Resten, Einkaufsliste und die Nachrichten `BESTAND_REQ`, `BESTAND`, `BESTAND_SAVE`,
`GEBAUT_REQ`, `BUCHUNG_RUECKGAENGIG` sind in [BESTAND.md](BESTAND.md) festgelegt.

## Phase 2: Lagerteile und Stückliste

Rein additiv; ältere Gegenseiten ignorieren die neuen Felder und Typen.

### PART_UPSERT.stock

Optionales Feld im Kopf, wenn das Teil aus `lager.teil(...).verbauen(...)` stammt:

```json
"stock": {"id": "vierkantrohr-en10219-40x40x3", "name": "Vierkantrohr 40 × 40 × 3", "laenge": 882.0,
          "gehrung": [0, 45], "material": "stahl-s235", "kg": 2.98, "preis": 7.06}
```

### PART_UPSERT.druckteil

Optionales Feld im Kopf, wenn das Teil aus `lager.druckteil(...)` stammt (statt `stock`; `verfahren` `3d-druck` | `harzdruck`):

```json
"druckteil": {"verfahren": "3d-druck", "material": "petg", "kg": 0.0412, "preis": 1.03}
```

Additiv (Strang „Feinschliff 2“): `"gedruckt": true`, wenn das Teil schon gedruckt ist (`lager.druckteil(…,
gedruckt=True)`); dann trägt auch die Stücklistenzeile `BOM.lines[i].gedruckt: true` (DRUCKVORSCHAU.md, „Gedruckt“).

### PART_UPSERT.kulisse

Optionales Feld im Kopf, `true`, wenn das Teil Kulisse ist (`show(..., kulisse=True)` oder `lager.kulisse(form)`):
Umgebung für Bilder und Videos wie ein gekachelter Boden, weder gekauft noch gebaut. Solche Teile haben kein `stock`,
`druckteil`, `zukauf` und kein `inventar`, stehen nicht in der Stückliste und zählen nicht als Verstoß gegen die
Inventar-Regel. Ohne eigene Farbe kommen sie hellgrau. Die App darf sie zurückhaltend zeigen; per Konvention liegen sie
in einer eigenen Gruppe (`Kulisse/…`), die sich wie jede Gruppe ausblenden lässt. Das Ergebnis des Laufs (`RUN_DONE`
im Kernel, Ergebnis von `run`) nennt sie in `kulisse` (Liste der Namen).

### Inventar-Regel

- `PART_UPSERT.inventar`: `ok` | `fehlt` (nur gesetzt, wenn die Regel im Projekt an ist und kein Skizzenlauf läuft;
  nie bei Kulisse).
- `RUN_END.inventar_regel` (bool): ob die Regel in diesem Lauf galt.
- `RUN_END.inventar_verstoesse`: Liste der Teilnamen, die weder verbaut noch Druckteil sind (leer = alles gut).
- `SETTINGS.inventar_regel` (App → Kernel, bool): Kevins Projekteinstellung, der Kernel schreibt sie in `kevcad.json`.
- Katalogeinträge in `CATALOG` tragen `status` (`frei` | `vorgeschlagen`); Freigabe = `CATALOG_SAVE` mit
  `status: "frei"`, Ablehnen = `CATALOG_DELETE`.

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `BOM` | `run`, `lines`, `cuts`, `totals`, `warnings` – nach jedem `RUN_END` und auf `BOM_REQ` | – |
| `CATALOG` | `reply_to`, `materials` (Liste Material laut KATALOG.md), `items` (Liste Lagerteil laut KATALOG.md, je mit `ebene`: `mitgeliefert` \| `eigen` \| `projekt`), `arten` (Liste der `art`-Werte) | – |

`lines[i]`:

```json
{"pos": 1, "art": "vierkantrohr", "stock_id": "vierkantrohr-en10219-40x40x3", "benennung": "Vierkantrohr 40 × 40 × 3",
 "norm": "DIN EN 10219", "material": "Stahl S235", "laenge": 882.0, "gehrung": [0, 0], "masse_text": "882 mm",
 "anzahl": 4, "kg_je": 2.98, "kg": 11.92, "preis_je": 7.06, "preis": 28.24, "teile": ["Gestell/Bein vorn links", "…"],
 "eigenteil": false}
```

- Platten: `laenge` null, `masse_text` z. B. „800 × 600 mm", Fläche über `flaeche_m2`.
- Schrauben und Kleinteile: `masse_text` z. B. „M8 × 60", Preis je Stück.
- Druckteile (`art: "druckteil"`): aus `lager.druckteil`, `stock_id` null, Material und Masse aus Volumen × Dichte,
  Preis über `preis_je_kg` des Materials.
- Eigenteile (`eigenteil: true`): nur bei abgeschalteter Inventar-Regel; frei modellierte Teile mit Material,
  `stock_id` null, Masse aus Volumen × Dichte.

`cuts[i]` (Zuschnitt je Stangenware):

```json
{"stock_id": "vierkantrohr-en10219-40x40x3", "benennung": "Vierkantrohr 40 × 40 × 3", "stangenlaenge": 6000,
 "saegeschnitt": 3, "stangen": [[882, 882, 882, 882, 800, 800], [800, 800]], "verschnitt_prozent": 12.4}
```

- `zu_lang` (optional): Stücklängen, die länger als die Stange sind (Sonderlänge oder stoßen, steht auch in `warnings`).
- `verschnitt_definition` (additiv, seit 22.10.2026): `"2"` heißt, `verschnitt_prozent` zählt nur Sägeschnitte und
  Reste unter dem Mindestrest (neue Reste nicht), bezogen auf die verplante Länge; genau wie der Bereich „Material“ der
  App. Ohne das Feld (älterer Kernel) war es alles außer den Stücken. Dazu `BOM.verschnitt`
  `{"definition": "2", "stangen", "platten"}` über alle Zuschnitte. Einzelheiten in BESTAND.md, Abschnitt „Verschnitt“.
- `preis_stangen` (optional): Preis der ganzen Stangen in Euro, wenn der Katalog `preis_je_m` kennt.

`totals`: `{"kg": 41.3, "preis": 96.10, "positionen": 7, "teile": 23, "preis_hinweis": "Richtpreise, Stand 2026-10"}`.

### App → Kernel

| type | Felder | Antwort |
|---|---|---|
| `BOM_REQ` | `id` | `BOM` mit `reply_to` |
| `CATALOG_REQ` | `id`, `query` (Text oder null), `art` (oder null) | `CATALOG` |
| `CATALOG_SAVE` | `id`, `kind` (`teil` \| `material`), `entry` (Objekt laut KATALOG.md), `ebene` (`eigen` \| `projekt`) | `ACK` (danach neues `CATALOG` nur auf Anfrage) |
| `CATALOG_DELETE` | `id`, `kind`, `entry_id`, `ebene` | `ACK` |

`EXPORT_REQ.formats` kennt zusätzlich `bom_csv` (Stückliste und Zuschnitt als CSV, Semikolon, deutsche Zahlen, UTF-8
mit BOM für Excel).

### Freigabe im Projektfenster (Strang „Feinschliff 2“, 22.10.2026)

Rein additiv. Vorschläge von Claude gibt Kevin jetzt auch direkt im Projektfenster frei: Band „3 Vorschläge warten auf
Freigabe“ und Dialog „Vorschläge freigeben“ (Vorschau der Daten, Link, „Freigeben“ je Eintrag und für alle). Freigeben
bleibt `CATALOG_SAVE` mit `status: "frei"` wie im Lagerkatalog, einer nach dem anderen und erst nach der Bestätigung im
neu geladenen Katalog; Fehler bleiben im Dialog stehen. MCP `freigabe_anfragen(ids, grund, warten_s)` öffnet den Dialog
und gibt selbst nichts frei; es wartet (Standard 120 s, höchstens 900 s), bis Kevin alles entschieden oder den Dialog
geschlossen hat, und liest das Ergebnis aus dem Katalog (frei, nicht mehr vorhanden = abgelehnt, weiter vorgeschlagen =
offen). Umsetzung: `kernel/src/kevcad_kernel/freigabe.py`, App `Model/Freigabe.swift` und
`Kernel/AppController+Freigabe.swift`; Testdateien `freigabe_*.frame` (`kernel/tools/make_freigabe_fixtures.py`).

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `FREIGABE_ANFRAGE` | Kernel → App | `id`, `anfrage` („F-0001“), `eintraege` (je `id`, `kind` `teil` \| `material`, `name`, `art`, `ebene`), `grund` (Text oder null) | `ACK` (Dialog offen) |
| `FREIGABE_GESCHLOSSEN` | App → Kernel | `anfrage`, `freigegeben`, `abgelehnt`, `offen` (Listen der ids) | – |

Eine neue Anfrage ersetzt eine offene (die App meldet die alte als geschlossen). Ältere Apps antworten nicht mit `ACK`;
`freigabe_anfragen` meldet dann nach 10 s „Dialog nicht geöffnet“.

## Phase 3: Zukaufteile

Rein additiv. Format der Einträge laut KATALOG.md, Abschnitt Zukaufteil.

### PART_UPSERT.zukauf

Optionales Feld im Kopf, wenn das Teil aus `lager.zukauf(...).verbauen(...)` stammt:

```json
"zukauf": {"id": "alutec-05200", "hersteller": "ALUTEC", "mpn": "05200", "cad": "hersteller", "preis": 24.99,
           "url": "https://…"}
```

`cad`: `hersteller` (eingebettetes Modell), `vereinfacht` (Ersatzkörper), `skript` (Geometrie aus einer Funktion). Bei
`vereinfacht` zeichnet die App das Teil halbtransparent.

### BOM.lines bei Zukaufteilen

`art: "zukaufteil"`, zusätzlich `hersteller`, `mpn`, `gtin`, `url`, `bild`, `preis_stand`, `preis_brutto` (bool),
`cad_quelle`, `vereinfacht` (bool).

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `ZUKAUF_STATUS` | `id` (Zukaufteil), `zustand`: `angelegt` \| `wartet_auf_cad` \| `importiert` \| `fehler`, `text`, `cad_links` (Liste `{titel, url}` zum Öffnen im Browser, nur bei `wartet_auf_cad`), `erwartet` (Liste Dateiendungen, z. B. `step`, `stp`, `zip`) | – |

### App → Kernel

| type | Felder | Antwort |
|---|---|---|
| `ZUKAUF_NEU` | `id`, `eingabe` (Link, MPN oder GTIN, wie Kevin sie eingefügt hat), `felder` (Objekt laut KATALOG.md, von Kevin bestätigt), `ebene` (`projekt` \| `eigen`) | `ACK`, danach `ZUKAUF_STATUS` |
| `DOWNLOAD_SEEN` | `pfad`, `groesse`, `zeit` – neue Datei in `~/Downloads` mit passender Endung, solange ein Zukaufteil `wartet_auf_cad` ist | – |
| `ZUKAUF_CAD` | `id` (Anfrage), `teil` (Zukaufteil-id), `pfad` – Kevin hat bestätigt: diese Datei ist das CAD | `ACK`, danach `ZUKAUF_STATUS` |

Festlegungen (21.10.2026):

- `DOWNLOAD_SEEN`: `pfad` absolut, `groesse` in Byte (Ganzzahl), `zeit` ISO 8601 mit Zeitzone
  (`2026-10-21T21:14:03+02:00`). Die App schickt es einmal je neuer, vollständiger Datei (Größe 0,8 s stabil), noch vor
  der Rückfrage an Kevin.
- `ZUKAUF_STATUS` kommt unaufgefordert (ohne `reply_to`). Nach dem Verbinden schickt der Kernel für jedes Zukaufteil,
  das noch `wartet_auf_cad` ist, ein `ZUKAUF_STATUS` (wie `PART_UPSERT`), damit die Downloads-Beobachtung nach einem
  Neustart weiterläuft. Optional `name` (Anzeigename des Teils).
- `ZUKAUF_NEU.felder` ist ein vollständiger Katalogeintrag laut KATALOG.md (`id`, `art: "zukaufteil"`,
  `status: "frei"`, `ersatz` aus den Maßen).
- `BOM.lines[].stock_id` ist bei Zukaufteilen die Zukaufteil-id.

Ergänzt bei der Zusammenführung (21.10.2026, additiv):

- `ZUKAUF_CAD` mit einer Datei, die nicht passt (Maße, kein STEP im ZIP): `ACK` mit `ok: true` (angenommen), dann
  `ZUKAUF_STATUS` `fehler` mit dem Grund. Wartete das Teil auf sein CAD, folgt wieder `wartet_auf_cad` mit den Links und
  dem Grund im `text`, damit die App den Download-Ordner weiter beobachtet. Unbekanntes Teil: `ACK` mit `ok: false`.
- `PART_UPSERT.name` eines Ersatzkörpers endet auf „ (vereinfacht)“ (KATALOG.md, Zukaufteil); `BOM.lines[].teile`
  nennt denselben Namen. Erklärungen in model.py (`erlaubt_ueberlappung` …) finden das Teil auch unter dem Namen aus
  `show()`.

Kev CAD lädt Shop-Seiten nie selbst (PLAN-PHASE3-ZUKAUF.md, Z1): Daten kommen von Claude über MCP oder aus Kevins
Eingabe im Dialog. CAD-Dateien kommen aus `~/Downloads` (Kevin lädt sie über die Links von `cad_suchen` herunter);
eine automatische CAD-Quelle gibt es nicht, die TraceParts-API ist seit dem 22.10.2026 stillgelegt.

## Prüfung

Rein additiv; ältere Apps ignorieren `CHECK`. Nach jedem erfolgreichen Lauf prüft der Kernel den Stand (im
Rechenprozess, direkt nach `RUN_DONE`, siehe `kernel/src/kevcad_kernel/pruefung/`): zuerst Durchdringungen; weitere
Prüfungen (Schweben, Standsicherheit, Einbaubarkeit, Druckregeln, Bedingungen) liefern Befunde im selben Format.

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `CHECK` | `run`, `state` (`running` \| `done` \| `teilweise` \| `cancelled` \| `failed`), `duration_ms`, `message` (Text oder null), `zusammenfassung` (z. B. „2 Durchdringungen · 1 Teil nicht einbaubar“, leer = nichts offen), `zaehler` (`fehler`, `warnung`, `hinweis`), `befunde` (Liste), `geometrie` (Liste `{befund, vert, tri}`), optional `gewinde`, `erlaubt` (nicht gemeldete Überlappungen mit Grund), `montage`, `stand`, `im_hintergrund`, `statik_im_hintergrund`, `statik` (Kurzfassung je Szenario) | Schnittkörper |

- Nach `RUN_END` kommt sofort `CHECK` mit `state: "running"` und leeren Listen, das Ergebnis folgt als zweites `CHECK`.
  `cancelled`: ein neuerer Lauf kam dazwischen (dessen `CHECK` folgt). Beim Verbinden schickt der Kernel das letzte
  fertige `CHECK` mit.
- `teilweise` (additiv, Prüftempo 22.10.2026): Das Ergebnis steht und gilt (Befunde, Schnittkörper, Montage), nur der
  Bewegungsraum hat das Zeitlimit des Laufs erreicht. `im_hintergrund` nennt die offenen Wege (etwa
  `"drehgelenk Kugelschieber/Sterngriffschraube M6x25 Fänger links"`); ihre Befunde sind bis dahin Hinweise
  („… wird im Hintergrund fertig gerechnet“). Der Kernel rechnet sie ohne neuen Lauf fertig und schickt dann ein
  weiteres `CHECK` mit demselben `run` und `state: "done"`, das das teilweise vollständig ersetzt (ohne
  `im_hintergrund`). Kommt vorher ein neuer Lauf, bleibt es beim teilweisen Ergebnis des alten. Ältere Apps lesen
  einen unbekannten `state` als `done` und ersetzen es beim zweiten `CHECK`; die App zeigt im Prüfband und im
  Inspektor „Bewegungsraum: 2 Gelenke werden fertig gerechnet …“.
- `statik_im_hintergrund` (additiv, 22.10.2026, PLAN-STATIK.md T34): Rechnen nach dem Lauf noch ein Ablauf (Stufe 2)
  oder der Festkörper (Stufe 3), ist das `CHECK` ebenfalls `teilweise` und nennt sie hier (etwa
  `"Ablauf „Bremsen aus 1 m/s“"`, `"Festkörper „Haken 2 kg“ (2 Teile)"`). Sind sie fertig (oder abgebrochen), folgt
  dasselbe `run` erneut, ohne neuen Lauf: mit den Befunden `statik_dyn_kippen`, `statik_dyn_ladung`,
  `statik_dyn_rutschen` und `statik_festkoerper` (rot → `warnung`, gelb → `hinweis`, nie `fehler`, T10; ein
  Festkörper-Befund ersetzt `statik_bauteil` desselben Teils), neu nummeriert, und mit `done` (oder weiter
  `teilweise`, solange der Bewegungsraum rechnet). Nur Szenarien des Laufs zählen (model.py und Standard), nicht die
  auf Anfrage gerechneten. Bloßer Fortschritt schickt kein neues `CHECK`. Ältere Apps sehen ein `teilweise` ohne
  `im_hintergrund` und ersetzen es beim nächsten `CHECK`; die App zeigt im Prüfband „Statik: … rechnet noch, Befunde
  folgen …“.
- Befund:

```json
{"id": "du1", "art": "durchdringung", "teile": ["Halter/Block A", "Halter/Block B"], "schwere": "fehler",
 "wert": {"volumen": 200.0, "tiefe": 2.0, "achse": [-1, 0, 0]}, "ort": [4.0, 0.0, 0.0],
 "text": "Halter/Block A und Halter/Block B durchdringen sich: 200 mm³, Tiefe etwa 2 mm bei (4; 0; 0).",
 "loesung": "Halter/Block A um 2,2 mm in −X verschieben (dann 0,2 mm Spiel) …", "geometrie": 0}
```

  `schwere`: `fehler` (Lauf gilt als fehlerhaft, Export gesperrt), `warnung`, `hinweis`. `ort` in mm oder null,
  `geometrie` Index in `geometrie` oder null. Weitere Quellen dürfen eigene Felder ergänzen (etwa `soll`, `ist`).
- Durchdringung zählt ab 0,001 mm³ Schnittvolumen und 0,01 mm Tiefe; Berühren ist kein Befund. Einzige automatische
  Ausnahme ist echter Gewindeeingriff (Schraube in Mutter oder Kernloch, gleiche Achse, nur im Gewindeband); er steht in
  `gewinde` (je Eintrag `teile`, `text`, `volumen`, `achse`). In der Montage sperrt ein Gewindeeingriff quer zur Achse,
  entlang der Achse nicht (herausdrehen). Gewollte Überlappungen erklärt model.py mit `erlaubt_ueberlappung(a, b, grund=…)` (steht in `erlaubt`).
- Nutzlast: je Eintrag von `geometrie` hintereinander positions f32 (`vert` × 3), normals f32 (`vert` × 3), triangles
  u32 (`tri` × 3), Weltkoordinaten. Die App zeigt sie als roten, durchscheinenden Schnittkörper.

Testdateien: `check_done.frame`, `check_running.frame`, `check_teilweise.frame`, `check_statik.frame`, `check.json` (aus
`kernel/tools/make_pruef_fixtures.py`).

Weitere Teile von `CHECK` (Stufe 2):

- `stand`: `{"boden_z", "boden_erklaert", "gruppen": [{"teile", "masse_kg", "schwerpunkt", "stuetzpolygon" (xy),
  "rand_abstand" (mm, negativ = außerhalb), "kippwinkel" (Grad), "kante", "schwebt" | "befestigt"}]}`. Kontakt heißt
  Abstand bis 0,5 mm (Spielpassung zählt als Verbindung), „berührt“ bis 0,05 mm. Befunde `schwebt` gibt es nur bei
  Modellen ohne Zwangsbedingungen; mit Bedingungen prüft die Befestigung (B9, Prüffunktion „bedingungen“) das Schweben,
  damit nichts doppelt gemeldet wird. `kippt` und `standsicherheit` kommen immer aus dieser Prüfung.
- `montage`: `{"vollstaendig", "schritte": [{"nr", "name", "teile", "gruppe", "richtung" (Einführrichtung [x,y,z], null
  beim Grundteil), "richtung_text" („Grundteil“, „von oben“, „von −X her“ …), "werkzeug"}], "offen", "tests",
  "abgebrochen"}` in Einbaureihenfolge.

### SCREENSHOT_REQ.ansicht (Analyse)

Optionales Objekt in `SCREENSHOT_REQ` (mit `source: "offscreen"`) für Bilder zur eigenen Analyse des Agenten (MCP
`ansichten`, `pruefen(bilder=true)`): `name`, `standard` (Standardansicht) oder `richtung` [x,y,z] (Blickrichtung der
Kamera, Z bleibt oben), `ziel` (Teile) oder `punkt` [x,y,z] mit `radius` (mm) zum Einpassen, `darstellung`
(`shaded_edges` \| `shaded` \| `wireframe` \| `xray`), `hervorheben` (Teile, rot getönt), `schnittkoerper` (bool, rote
Schnittkörper der Prüfung). Die App rendert aus einer Kopie der Körper, Kevins Kamera, Darstellung und Auswahl bleiben
unverändert, und setzt in `SCREENSHOT_RES.camera` das Feld `ansicht: true`. Ältere Apps ignorieren das Feld und liefern
die Standardansicht aus `view`.

## Phase 5: Animation

Rein additiv (Strang ANI, PLAN-PHASE5-KAMERA-ANIMATION.md A1–A4); ältere Gegenseiten ignorieren die neuen Typen.
Animationen entstehen in model.py (`animation(...)`, siehe `kernel/src/kevcad/bewegung.py`); der Kernel wertet sie nach
dem Lauf aus (`kevcad_kernel/animation.py`) und schickt sie nach `RUN_END` und `BOM`. Beim Verbinden kommen alle
Animationen des letzten Laufs nach `BOM` mit. `RUN_END`-Ergebnisse für MCP tragen `animationen` (Zusammenfassung).

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `ANIM_DEF` | `run`, `name`, `dauer` (s), `fps`, `bilder` (N = round(dauer · fps) + 1, Bild k bei min(k / fps, dauer)), `teile` (P bewegte Teile), `kamera` (bool, Kamerafahrt dabei), `sichtbar` (Liste `{"teile": [...], "zeiten": [[t, an], ...]}`), `standard` (bool, erste Animation des Laufs), `warnungen`, `spuren` | float32 LE: N × P × 12, dann bei `kamera` N × 7 |
| `ANIM_REMOVE` | `name` | – |
| `ANIM_COLLISIONS` | `name`, `run`, `kollisionen` (siehe unten), `geprueft` (`paare`, `bilder`, `schritt`, `geprueft_bilder`, `exakt`, `symmetrisch`, `ms`, …), optional `reply_to` | – |
| `ANIM_PLAY` | `id`, `name`, `an` (bool), `schleife`, `geschwindigkeit` (1 = Echtzeit), `von_vorn` | App antwortet `ACK` |
| `ANIM_SEEK` | `id`, `name`, `zeit` (s; hält an) | App antwortet `ACK` |
| `ANIM_VIDEO_REQ` | `id`, `name`, `width`, `height`, `fps`, `kamera` (null = Viewer-Kamera bzw. Kamerafahrt, sonst „Kamera/<name>“ aus CAMERA_UPSERT), `format` (`mp4` = H.264 \| `prores` = ProRes 422), `path` (absolute Zieldatei, `<projekt>/output/animationen/<name>.mp4`, mit Kamera `<name>_<kamera>.mp4`) | App antwortet `ANIM_VIDEO_RES` |

Nutzlast von `ANIM_DEF`:

- Matrizen: je Bild, je Teil (Reihenfolge `teile`) 12 Werte = die oberen drei Zeilen der 4 × 4-Lage **spaltenweise**
  (`m00 m10 m20  m01 m11 m21  m02 m12 m22  m03 m13 m23`, wie `transform` an PART_UPSERT). Die Lage bildet die Ruhelage
  aus model.py auf die Lage im Bild ab (Welt = Lage · Punkte des Teils). Teile ohne Eintrag stehen still.
- Kamerafahrt (nur bei `kamera: true`): je Bild `Lage x y z`, `Ziel x y z`, `Bildwinkel` (vertikal, Grad; 0 = unverändert).
- Sichtbarkeit: ein Teil in `sichtbar` gilt zur Zeit t nach dem letzten Eintrag mit Zeit ≤ t; vor dem ersten Eintrag gilt
  das Gegenteil des ersten. Teile ohne Eintrag bleiben, wie sie sind.

`kollisionen[i]` (je Teilpaar und zusammenhängender Zeitspanne der geprüften Bilder):

```json
{"teile": ["Bowlingball", "Pfosten"], "von": 5.1, "bis": 5.6, "zeit": 5.4, "bild": 162, "tiefe": 12.5,
 "volumen": 830.0, "ort": [1500.0, -340.0, 100.0], "bilder": [153, 156, 159, 162, 165, 168]}
```

`zeit`/`bild`: stärkste Durchdringung; `tiefe` (mm): kleinste Ausdehnung des Schnittkörpers (Näherung der
Eindringtiefe); `volumen` mm³; `ort` Mitte des Schnittkörpers in Weltkoordinaten. Berührungen (Volumen unter 0,5 mm³ oder
Dicke unter 0,05 mm), Paare aus `anim.erlaube(...)` und aus `erlaubt_ueberlappung(a, b, grund=…)` der Prüfung zählen
nicht. Die Schnittkörper aus `CHECK` gelten für die Ruhelage; die App zeigt sie nur, solange keine Animation eine Lage
setzt (auch nicht in Kamerabildern und Videos aus einem Bild der Animation).

### App → Kernel

| type | Felder | Antwort |
|---|---|---|
| `ANIM_STATE` | `name`, `zeit`, `bild`, `spielt`, `schleife`, `geschwindigkeit` (bei Abspielen, Anhalten, Springen, nicht je Bild) | – |
| `ANIM_COLLISIONS_REQ` | `id`, `name`, `schritt` (jedes n-te Bild, Vorgabe 3) | `ANIM_COLLISIONS` mit `reply_to` |
| `ANIM_VIDEO_RES` | `reply_to`, `ok`, `path`, `frames`, `ms`, `message`, `kamera` (`Viewer`, `Kamerafahrt` oder der Kameraname) | – |

## Phase 5: Kameras

Rein additiv (Strang KAM); ältere Gegenseiten ignorieren die neuen Typen und Felder. Kameras entstehen in model.py mit
`lager.kamera(...)` (KATALOG.md, „Kameras und Objektive“) und heißen im Protokoll `Kamera/<name>`. Testdateien:
`kernel/tools/make_camera_fixtures.py` schreibt `camera_*.frame`, `view_cmd_camera*.frame`, `screenshot_req_camera.frame`
und `camera_fixtures.json` nach `app/KevCADCore/Tests/KevCADCoreTests/Fixtures/` (getrennt von `stream.bin`).

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `CAMERA_UPSERT` | siehe unten; nach jedem erfolgreichen Lauf für neue und geänderte Kameras (vor `RUN_END`) und beim Verbinden für alle | – |
| `CAMERA_REMOVE` | `run`, `name` – Kamera gibt es im neuen Lauf nicht mehr oder ein anderes Projekt ist offen | – |

```json
{
  "type": "CAMERA_UPSERT", "seq": 21, "run": 4, "name": "Kamera/FX6", "kurzname": "FX6",
  "kamera": {"id": "sony-fx6", "name": "Sony FX6 (ILME-FX6V)", "bajonett": "sony-e", "auflagemass": 18.0},
  "objektiv": {"id": "sigma-ff-hs-35-t1.5-e", "name": "Sigma 35 mm T1,5 FF High Speed Prime (E-Mount)",
               "brennweite": 35, "lichtstaerke": 1.5, "blendenart": "t", "naheinstellgrenze": 300, "bildkreis": 43.3,
               "laenge": 121, "frontdurchmesser": 95},
  "format": {"id": "ff-uhd", "name": "Vollformat UHD 3840 × 2160", "modus": "vollformat"},
  "lage": [0, -1, 0, 0,  0, 0, 1, 0,  -1, 0, 0, 0,  250, 0, 235, 1],
  "sensor_pos": [250, 0, 235], "auge": [285, 0, 235], "blick": [1, 0, 0], "oben": [0, 0, 1], "rechts": [0, -1, 0],
  "sensor_mm": [35.7, 20.081], "aufloesung": [3840, 2160], "seitenverhaeltnis": 1.77778,
  "brennweite": 35.0, "bildwinkel_h": 54.043, "bildwinkel_v": 32.014, "bildwinkel_d": 60.668,
  "blende": 2.8, "blendenart": "t", "fokus": 1500.0, "schaerfe_nah": 1375.628, "schaerfe_fern": 1649.097,
  "hyperfokal": 16238.704, "zerstreuungskreis": 0.027,
  "teil": "Wagen", "folgt": "Wagen", "ausblenden": ["Kamera FX6/Objektiv"], "objektiv_vorne": 139.0,
  "vignettierung": false
}
```

- `lage`: 4 × 4-Matrix spaltenweise; Spalten rechts, oben, hinten (= −`blick`), Sensormitte. Die Kamera blickt entlang
  ihrer lokalen −Z-Achse, oben ist +Y (wie OpenGL und Blender). `sensor_pos`, `blick`, `oben`, `rechts` stehen zusätzlich
  einzeln da.
- `auge`: Projektionszentrum für Ansicht und Kamerabild, Sensormitte plus Brennweite in Blickrichtung.
- Bildwinkel in Grad aus `sensor_mm` (aktive Fläche des Formats; Höhe = Breite × Pixelhöhe / Pixelbreite) und
  `brennweite` bei Fokus unendlich. Die Ansicht durch
  die Kamera und das Kamerabild benutzen `bildwinkel_v` als vertikalen Öffnungswinkel und `seitenverhaeltnis`
  (= `aufloesung`).
- `fokus`, `schaerfe_nah`, `schaerfe_fern`, `hyperfokal` in mm ab Sensorebene; `null` heißt unendlich.
- `teil`: gezeigtes Teil, an dem die Kamera hängt (`an(...)`), sonst `null`.
- `folgt`: gezeigtes Teil, dessen Bewegung die Kamera in der App mitmacht: das Teil aus `an(...)` (bei einer Baugruppe
  ihr erstes gezeigtes Teil), sonst das gezeigte Gehäuse aus `koerper()`, sonst `null` (steht fest). Ohne das Feld
  (ältere Kernel) gilt `teil`. Siehe „Kameras und Animation“.
- `ausblenden`: gezeigte Teile des eigenen Objektivs aus `koerper()`; die App blendet sie (und jedes Teil, dessen
  Hüllquader die Strecke vom Augpunkt bis `objektiv_vorne` vor der Sensorebene schneidet) beim Blick durch die
  Kamera aus.
- `vignettierung`: Bildkreis des Objektivs kleiner als die Diagonale des Formats.

### VIEW_CMD (zusätzlich)

| cmd | args | Antwort |
|---|---|---|
| `camera_view` | `name` (`Kamera/<name>`) oder `null` = zurück zur freien Ansicht | `ACK` |
| `camera_suggest` | `name` | App schickt `CAMERA_SUGGEST`, danach `ACK` |

### SCREENSHOT_REQ (zusätzlich)

`source: "camera"` mit `camera` (Name): Bild genau durch diese Kamera (Augpunkt, Blick, `bildwinkel_v`), `width` und
`height` passend zum Seitenverhältnis des Formats (der Kernel rechnet die Höhe aus). Ausgeblendet wie in der
Kameraansicht. `SCREENSHOT_RES.camera` trägt zusätzlich `name`.

### App → Kernel

| type | Felder | Antwort |
|---|---|---|
| `CAMERA_SUGGEST` | `name`, `sensor_pos`, `auge`, `blick`, `oben`, `rechts`, `roll` (Grad gegenüber Welt-Z) – aktuelle Ansicht als neue Lage der Kamera (Strg+Alt+0 oder auf `camera_suggest`) | – (Kernel merkt sich den Vorschlag; MCP `kamera_info`, `kamera_vorschlag_aus_ansicht`) |

### Kameras und Animation

- Kameras kommen in der Ruhelage aus model.py. Die App bewegt jede Kamera starr mit der Lage ihres Teils `folgt`
  relativ zu dessen Ruhelage (Animation aus `ANIM_DEF`, dazu die Explosion): Pyramide, Blick durch die Kamera (Taste 0;
  er bleibt beim Abspielen aktiv und hat Vorrang vor einer Kamerafahrt), Kamerabild (`SCREENSHOT_REQ` mit `camera`)
  und Video (`ANIM_VIDEO_REQ.kamera`) zeigen die Kamera in der aktuellen bzw. der Lage des Bildes.
- Im Video durch eine Kamera blendet die App wie in der Kameraansicht ihr Objektiv (`ausblenden`) und Teile vor dem
  Augpunkt aus; der Kernel rechnet die Höhe aus dem Seitenverhältnis des Formats (`aufloesung`).
- Der Kernel lässt den gezeigten Körper (`koerper()`) einer Kamera mit `an(teil)` in jeder Animation mit diesem Teil
  fahren (`folge`), außer eine Spur bewegt den Körper dort schon. Rig-Zubehör hängt nicht an der Kamera und braucht
  eine eigene Spur.
- `CAMERA_SUGGEST` (Strg+Alt+0) rechnet die Ansicht in die Ruhelage zurück, wenn die Kamera gerade bewegt steht.
- MCP: `animation_liste` und die Zusammenfassung von `run` nennen je Animation unter `kameras` die Kameras, deren Teil
  sich darin bewegt.

## Zwangsbedingungen (CONSTRAINTS)

Rein additiv (PLAN-BEDINGUNGEN.md); ältere Apps ignorieren den Typ. Der Kernel schickt den Bericht nach jedem
erfolgreichen Lauf direkt nach `RUN_END` und `BOM`, beim Verbinden der App nach `BOM`. Referenz:
`kevcad_kernel/bedingungen` (Bericht aus `pruefen`, Beispiel `protocol.constraints_example()`), Testdatei
`constraints.frame` (eigene Datei, nicht in `stream.bin`).

Zusammenspiel mit der Prüfung: Alle Befunde der Bedingungen gehen zusätzlich als Prüffunktion „bedingungen“ in das
gemeinsame Ergebnis `CHECK` (Arten `bedingung`, `befestigung`, `bewegungsraum`, mit den Zusatzfeldern `soll` und
`ist`); dort sperren Befunde mit Schwere `fehler` den Export. Den Bewegungsraum (Gelenke mit Bereich,
`bewegungen.json`) rechnet nur die Prüfung nach `RUN_END`, weil er Sekunden dauern kann; im Lauf bleibt `bewegungen` in
`CONSTRAINTS` deshalb leer, die Ergebnisse stehen als Befunde in `CHECK`. Was im Zeitlimit des Laufs nicht fertig wird,
rechnet der Kernel im Hintergrund fertig (`CHECK` `teilweise` → `done` mit demselben `run`, siehe „Prüfung“).

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `CONSTRAINTS` | `run`, `items`, `teile`, `bewegungen`, `befunde`, `summe`, `pruef_ms`, `loese_ms` | – |

`items[i]` (eine Bedingung, auch Parametergrenzen und Verbindungen):

```json
{"id": "b3", "art": "auf", "gruppe": "montage", "symbol": "auf",
 "text": "Rollwagen/Rahmen.unten auf Rollwagen/Lenkrolle 1/Gabel.oben",
 "teile": ["Rollwagen/Rahmen", "Rollwagen/Lenkrolle 1/Gabel"], "stand": "verletzt", "schwere": "fehler",
 "soll": "Abstand 0 mm, Flächen gegenüber", "ist": "Abstand 2 mm (Luft 2 mm)", "abweichung": 2.0, "einheit": "mm",
 "punkte": [[255.0, -335.0, 122.0], [255.0, -335.0, 120.0]], "zeile": 57, "datei": "model.py",
 "loesung": "Rollwagen/Rahmen um 2 mm entlang −Z verschieben", "hinweis": null}
```

- `art`: `auf`, `buendig`, `konzentrisch`, `parallel`, `senkrecht`, `abstand`, `winkel`, `tangential`, `mittig`,
  `in_bohrung`, `drehgelenk`, `schiebegelenk`, `zylindergelenk`, `kugelgelenk`, `fest`, `verbinde`, `gleich`, `spiel`,
  `min_abstand`, `min_wand`, `param` (id `p:<name>`). `symbol` wählt das Zeichen in der App (gleich `art`).
- `gruppe`: `montage` | `gelenk` | `mass` | `befestigung`; `stand`: `erfuellt` | `verletzt` | `ungeprueft`;
  `schwere` nur bei `verletzt`: `fehler` | `warnung`.
- `punkte`: bis zu zwei Anzeigepunkte in Weltkoordinaten (mm): der erste am Teil, das sich anpasst (dort sitzt das
  Symbol), der zweite am Gegenstück (bei verletzten Bedingungen zeigt die App die Strecke dazwischen).
- Gelenke zusätzlich: `gelenk` (`revolute` | `linear` | `cylindrical` | `ball` | `rigid`), `wert`, `wert_einheit`
  (`°` | `mm`), `bereich` [min, max] (fehlt ohne Bereich), `achse` {`p`, `d`} in der gezeigten Lage, `anim_art`
  (`dreh` | `schub`, für die Animation). `in_bohrung`: `schraube` {`d`, `laenge`}, `gewinde`. `verbinde`:
  `verbindung` (`schraube` | `klemmung` | `steck` | `formschluss` | `kleben` | `aufliegen`).

`teile[i]` (Teile mit Bedingungen):

```json
{"name": "Rollwagen/Rahmen", "platziert": true, "frei": 0, "stand": "bestimmt", "bedingungen": ["b3", "b4", "b5"],
 "freiheitsgrade": [{"art": "drehung", "richtung": [0, 0, 1], "punkt": [0, -335, 120], "text": "Drehung um Z durch …",
                     "gelenk": false, "unkritisch": false}],
 "gelenke": [], "befestigt": true, "am_boden": true, "verbindungen": ["aufliegen"], "verletzt": 0}
```

`stand`: `bestimmt` | `unterbestimmt` | `widerspruch` | `bezug` (nur Gegenstück); `frei` zählt freie Freiheitsgrade
ohne Gelenke und ohne die unkritische Drehung runder Verbindungen um ihre eigene Achse.

`bewegungen[i]` (Bewegungsraum: Gelenke mit Bereich und `<projekt>/bewegungen.json`):

```json
{"name": "drehgelenk …/Spannhebel", "art": "drehen", "quelle": "gelenk", "bedingung": "b7", "teile": ["…/Spannhebel"],
 "punkt": [0.0, 0.0, 0.0], "richtung": [0.0, 1.0, 0.0], "von": -90, "bis": 90, "ist": 0, "schritte": 18,
 "frei": [[-20, 10]], "frei_um_ist": [-20, 10], "freiraum": 15,
 "kollisionen": [{"gegen": "…/Spannbolzen", "bewegt": "…/Spannhebel", "bereiche": [[-90, -25]], "max_volumen": 12.3,
                  "bei": -40, "ort": [0.0, 0.0, 0.0], "schon_in_ruhe": false}],
 "eng": [{"gegen": "…", "bereiche": [[20, 40]], "min_abstand": 6.2}], "geprueft_ms": 850.0, "teilweise": false}
```

`befunde[i]`: gemeinsames Befundformat der Prüfungen mit `art: "bedingung"`, `pruefung` (`bedingung` | `parameter` |
`widerspruch` | `freiheitsgrade` | `bewegungsraum` | `befestigung`), `teile`, `schwere` (`fehler` | `warnung` |
`hinweis`), `text`, `soll`, `ist`, `wert`, `einheit`, `ort` ([x, y, z] oder null), `loesung`, `bedingung` (id),
`unterart`, `zeile`. Befunde mit `schwere: "fehler"` sperren den Export (über die Prüfung, siehe oben).

`summe`: `gesamt`, `erfuellt`, `verletzt`, `ungeprueft`, `fehler`, `warnungen`, `hinweise`, `bewegungen`.
`pruef_ms`: Dauer der Prüfung im Rechenprozess, `loese_ms`: Summe der Zeit in `platziere`.

## Versionen

Rein additiv (PLAN-VERSIONEN.md); ältere Gegenseiten ignorieren die neuen Typen. Jede Version ist ein Stand aller
Projektdateien in einem eigenen Git-Repo (`<projekt>/.kevcad/git`, ohne `output/`, `.kevcad/`, `bestand.json`), mit
projektweit eindeutiger Nummer `nr` (Anzeige „V12“). Varianten sind Zweige (`haupt` = Hauptstand). Umsetzung:
`kernel/src/kevcad_kernel/versionen/`. Testdateien: `kernel/tools/make_versionen_fixtures.py` schreibt
`versionen.frame`, `version_vergleich.frame`, `version_bild_req.frame` und `versionen_fixtures.json` (getrennt von
`stream.bin`).

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `VERSIONEN` | `projekt`, `verfuegbar` (bool; false = Git fehlt), `meldung` (Text oder null), `variante` (aktueller Zweig), `varianten`, `versionen` (neueste zuerst, höchstens 400 plus alle Meilensteine), `gruppen`, `anzahl`, `meilensteine`, `ungesichert` (Dateien weichen vom aktuellen Stand ab), optional `reply_to` – nach dem Öffnen, nach jeder neuen Version, nach Änderungen an Kennzahlen, Prüfstand, Bild, Meilenstein oder Variante und beim Verbinden | – |
| `VERSION_VERGLEICH` | `a`, `b` (je `nr` (bei b null = aktueller Stand), `titel`, `zeit`, `kennzahlen`), `aktuell`, `zusammenfassung`, `params`, `teile`, `stueckliste`, `pruefung`, `kennzahlen`, `code`, `dokumente` (additiv), `hinweise`, `ms`, `geometrie` (Netzköpfe), optional `reply_to` | Netze |
| `VERSION_BILD_REQ` | `id`, `nr`, `width`, `height`, `view` (Standardansicht), `teile` (Netzköpfe mit `teil`, `farbe` sRGB) – die App rendert offscreen nur diese Netze und antwortet mit `SCREENSHOT_RES` (PNG) | Netze |

`versionen[i]`:

```json
{"nr": 37, "commit": "5905093abc", "zeit": "2026-10-21T23:41:53", "ts": 1792626113, "wer": "agent",
 "wer_text": "Agent · 3f2a9c", "sitzung": "3f2a9c1b77", "quelle": "lauf", "titel": "Halter mit Flügelschrauben",
 "aus": null, "meilenstein": {"titel": "Halter fertig", "notiz": "…", "zeit": "…", "wer": "agent"},
 "kennzahlen": {"teile": 134, "masse_kg": 12.3, "kosten": 85.2, "positionen": 17, "fehler": 0, "warnungen": 1,
                "pruefung": "1 Teil schwebt"},
 "params": {"laenge": 1000}, "pruefung": {"fehler": 0, "warnungen": 1, "pruefung": "…"},
 "bild": "/…/.kevcad/versionen/bilder/37.png", "aktuell": true, "geerbt": false, "zweig": "haupt",
 "dateien": ["model.py"], "gruppe": null, "nachberechnung": null,
 "zusatz": "breite 120 → 140 · + Flügelschraube M4 (4×)", "titel_quelle": "agent",
 "titel_auto": "breite 120 → 140 · + Flügelschraube M4 (4×)"}
```

- `titel`: anzuzeigender Titel (unter einem Meilenstein); Vorrang Titel vom Agenten (`run(titel=…)`), dann der
  automatische aus dem Vergleich mit der Vorgängerversion (PLAN-VERSIONEN.md „Titel“), sonst der Grundtitel beim
  Anlegen („Übernommener Stand“, „Erster Stand“). Wiederhergestellt und gesichert: fester Titel. Additiv seit dem Zweig
  `versionstitel`: `zusatz` (zweite Zeile oder null: der automatische Titel unter dem des Agenten oder unter einem
  festen, „Übernommener Stand“ unter dem automatischen eines übernommenen Stands), `titel_quelle` (`agent`, `auto`,
  `fest`, `offen` = noch nicht berechnet), `titel_auto` (der automatische Titel oder null).

- `wer`: `kevin` (Speichern im Editor, ⌘R oder Aktion in der App), `agent` (MCP; `sitzung` = Claude-Sitzung aus dem Kopf der Brücke, sonst die aktive Sitzung), `kevcad`,
  `unbekannt` (übernommene Stände aus Auto-Läufen). `quelle`: `lauf`, `wiederherstellen` (mit `aus`), `sicherung`
  (ungesicherte Änderungen vor Wiederherstellen oder Variantenwechsel), `meilenstein`, `uebernahme` (alte
  `.kevcad/versions/NNNN-model.py`).
- `kennzahlen` null: noch nicht gerechnet (der Kernel rechnet übernommene Stände im Leerlauf nach); `nachberechnung`
  nennt dann ggf. den Grund, warum das nicht ging.
- `geerbt`: Version stammt aus der Variante, von der die aktuelle abzweigt.
- `gruppe`: Kennung in `gruppen` (`{"id", "anzahl", "neueste", "aelteste", "von", "bis", "text": "12 Läufe in 4
  Minuten"}`), wenn die Version zu einer dichten Folge automatischer Versionen gehört (mindestens 3, je höchstens
  5 Minuten auseinander, ohne Meilenstein); die Leiste fasst sie zu einer Zeile zusammen.
- `varianten[i]`: `{"id" (Zweig), "name", "aktuell", "versionen" (eigene), "letzte", "letzte_nr", "von"}`.

`VERSION_VERGLEICH`: `params` = `[{"name", "alt", "neu", "art": "neu"|"weg"|"geaendert"}]`; `teile` =
`{"neu": [Namen], "weg": [Namen], "geaendert": [{"name", "arten": ["form"|"lage"|"farbe"|"material"|"lagerteil"],
"dvolumen", "dmasse", "verschiebung"}], "gleich": n}`; `stueckliste` = `{"neu", "weg", "geaendert", "totals_alt",
"totals_neu"}` (Zeilen mit `benennung`, `masse_text`, `anzahl`, `preis`; geänderte zusätzlich `alt_anzahl`,
`neu_anzahl`, `alt_masse_text`, `alt_preis`); `pruefung` = `{"alt", "neu"}` (je `zusammenfassung`, `zaehler`,
`befunde` oder null); `kennzahlen` = `{"alt", "neu"}`; `code` = `{"dateien": [{"pfad", "status": "A"|"M"|"D",
"plus", "minus", "binaer"}], "diff" (unified, höchstens 4000 Zeilen), "gekuerzt", "zeilen"}` ohne `dokumente/`;
`dokumente` (additiv, 22.10.2026) = Änderungen an Blättern und Bauplan als eigene Gruppe, je Datei `{"pfad", "art":
"zeichnung"|"bauplan"|"datei", "name", "status", "punkte": [Text], "text"}` (z. B. „Zeichnung Seitenstange: 2 Maße
geändert“); `zusammenfassung` nennt sie am Ende.

Geisterkörper gibt es nur, wenn `b` der aktuelle Stand ist: `geometrie[i]` = `{"teil", "art": "alt"|"weg", "vert",
"tri", "epts", "edge"}` – `alt` ist die frühere Form eines geänderten Teils (Form oder Lage), `weg` ein Teil, das es
nicht mehr gibt. Die App zeigt sie durchscheinend obenauf (alt blau, weg rot), färbt geänderte Teile orange und neue
grün und beendet den Vergleich, sobald ein neuer Lauf den aktuellen Stand ändert.

Netze (Nutzlast von `VERSION_VERGLEICH` und `VERSION_BILD_REQ`): je Kopf hintereinander positions f32 (`vert` × 3),
normals f32 (`vert` × 3), triangles u32 (`tri` × 3), edge_points f32 (`epts` × 3), edge_offsets u32 (`edge` + 1;
Kante k = Punkte `edge_offsets[k] ..< edge_offsets[k+1]`), Weltkoordinaten, little-endian.

### App → Kernel

| type | Felder | Antwort |
|---|---|---|
| `VERSIONEN_REQ` | `id` | `VERSIONEN` mit `reply_to` |
| `VERSION_RESTORE` | `id`, `version` („V12“, „12“ oder Meilensteintitel) | `ACK`; danach `RUN_*` und `VERSIONEN` |
| `VERSION_COMPARE` | `id`, `a`, `b` (null = aktueller Stand) | `VERSION_VERGLEICH` mit `reply_to` oder `ERROR` (kann dauern: alte Stände ohne Zwischenspeicher rechnet der Kernel ohne Live-Aufbau neu) |
| `VERSION_MILESTONE` | `id`, `version` (null = aktueller Stand), `titel`, `notiz`, `entfernen` (bool) | `ACK` |
| `VARIANT` | `id`, `aktion` (`anlegen` \| `wechseln` \| `umbenennen`), `name` (bei wechseln und umbenennen Zweig oder Name), `von` (anlegen: Version oder null), `neuer_name` | `ACK`; danach `VERSIONEN`, bei anlegen und wechseln `RUN_*` |

Wiederherstellen ist nie zerstörend: ungesicherte Änderungen werden vorher eine Version (`sicherung`), der
wiederhergestellte Stand eine neue Version „Wiederhergestellt aus V12“. Läufe, Wiederherstellen, Variantenwechsel und
Meilensteine laufen im Kernel nacheinander (nie während eines Laufs).

## Druckvorschau

Vertrag mit Ergebnisformat und Ablauf: [DRUCKVORSCHAU.md](DRUCKVORSCHAU.md). Nachrichten ohne Nutzlast, Packen und
Prüfen in `protocol.py` (`pack_print_preview`, `print_settings`, `print_export_req`, `print_export_res`,
`check_druck_message`), Testdateien aus `tools/make_druck_fixtures.py`.

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `PRINT_PREVIEW` | Kernel → App | `run`, `stand`, `drucker`, `summe`, `platten`, `teile`, `hinweise`, `slicer` (dazu `einstellungen`, `regler`, `ms`), `reply_to` optional; nach jedem Lauf mit Druckteilen, nach jedem Slicer-Ergebnis und beim Verbinden | – |
| `PRINT_PREVIEW_REQ` | App → Kernel | `id` | `PRINT_PREVIEW` mit `reply_to` |
| `PRINT_SETTINGS` | App → Kernel | `id`, `teil` oder `gruppe`, `einstellungen` (Wert `null` = Vorgabe zurück; additiv auch die Schlüssel „druckfertig je Objekt“: `stuetzen_nur_platte`, `stuetzen_abstand_mm`, `brim_mm`, `naht`, `buegeln`, `oberflaeche`, `loch_kompensation_mm`, `kontur_kompensation_mm`, `elefantenfuss_mm`) und/oder `zweck`, `zuruecksetzen`, `von` | `ACK`, danach `PRINT_PREVIEW` |
| `PRINT_EXPORT_REQ` | App → Kernel | `id`, `platten` (leer = alle), `ziel` (Pfad .3mf oder null); additiv `teile` (nur diese Teile) und `ohne` (diese nicht): Teilname, Baugruppen-Präfix, Gruppe oder Gruppenname, `ohne` gewinnt; additiv `filament` (je Material die id eines Filaments aus Kevins Liste; ohne antwortet der Kernel mit `filament_frage`) | `ACK`, danach `PRINT_EXPORT_RES` |
| `PRINT_EXPORT_RES` | Kernel → App | `reply_to`, `ok`, `pfad`, `platten`, `fehler` (dazu `hinweise`, `ms`, `geprueft`, `pfade`, `dateien` mit `objekte` = Objektnamen im 3MF, `weggelassen` = `[{"name", "grund": "ohne" \| "teile" \| "spaeter", "platte", "anzahl"}]`, `leere_platten`, `filamente`, je Datei `filament_id`, `filament_basis`, `abweichungen`, `temperaturen`, `pruefung`; bei fehlendem Filament `ok: false`, `filament_frage: true`, `vorschlaege`; Paket B: `druckfertig`, `objekte_einstellungen`) | – |

## Phase 4: Referenzen

Rein additiv (PLAN-PHASE4-REFERENZ.md, Strang „Phase 4 in die App“); ältere Gegenseiten ignorieren die neuen Typen.
Eine Referenz ist ein Foto- oder Videobezug des echten Gegenstands, abgelegt in `<projekt>/referenzen/<name>/`
(`referenz.json`, `capture/` aus Object Capture, `messung/` aus fotomess, `fotos/`); sie gehört nicht zum Modell und
nicht zur Stückliste (R4). Umsetzung: `kernel/src/kevcad_kernel/referenz/`, Packen und Prüfen in `protocol.py`
(`pack_ref_netz`, `unpack_ref_netz`, `check_ref_message`, `referenz_beispiele`), Testdateien `ref_*.frame` und
`referenz_fixtures.json` aus `kernel/tools/make_referenz_fixtures.py`. Der Plan nannte die Nachrichten `REF_PHOTO`
(hier gebündelt als `REF_PHOTOS`, ein Satz je Referenz) und `REF_DEVIATION`/`REF_SCALE` (seit 22.10.2026, siehe
„Abweichung, Maßstab, Scans in der App“ unten).

| type | Richtung | Felder | Nutzlast / Antwort |
|---|---|---|---|
| `REF_LIST` | Kernel → App | `referenzen` (Liste, siehe unten); bei jeder Änderung (Fortschritt höchstens alle 0,4 s), nach `PROJECT` und beim Verbinden | – |
| `REF_UPSERT` | Kernel → App | `name` (Referenz), `farbe` (RGBA sRGB, Vorgabe halbdurchsichtig), `counts` {`vert`, `tri`}, `bbox`, `quelle` (`object_capture`), `lage` (oder null) | positions f32 (vert × 3), normals f32 (vert × 3), triangles u32 (tri × 3), Weltkoordinaten des Modells (mm, Z oben) |
| `REF_REMOVE` | Kernel → App | `name` – Netz weg (neue Rekonstruktion läuft) | – |
| `REF_PHOTOS` | Kernel → App | `referenz`, `satz` (`messung` \| `capture`), `fotos` (Liste, ersetzt den Satz) | – |
| `REF_RESULT` | Kernel → App | `referenz`, `stand`, `masse`, `bekannt`, `huelle`, `grundkoerper`, `teile`, `brennweite_px`, `bilder`, `verworfen`, `ueberdeckung`, `empfehlungen`, `zeiten`, `dauer_s`, `warnungen`, `kontrollbilder` | – |
| `REF_ADD` | App → Kernel | `id`, `pfade` (ein Video oder Fotos, absolute Pfade), `name`, `masz` ({`laenge`: mm} o. ä.), `auflage`, `von`, `bis`, `einstellung` (`schnell` \| `genau`) | `ACK`, dann `REF_LIST` … |
| `REF_MEASURE_REQ` | App → Kernel | `id`, `referenz`, `frei` (param-Namen oder null = aus `messmodell()`), `bekannt` ({Name: mm}), `bilder` | `ACK` sofort, dann `REF_LIST`, `REF_PHOTOS`, `REF_RESULT` |
| `REF_APPLY` | App → Kernel | `id`, `referenz`, `werte` ({param-Name: mm}) – Kevins Klick „Maße übernehmen“: der Kernel ersetzt die Vorgabewerte in `param("name", wert)` von model.py (auf 0,1 mm gerundet), der Auto-Lauf rechnet neu | `ACK` mit `message` („tiefe 110 → 103,4; …“) |

`REF_LIST.referenzen[i]`:

```json
{"name": "IMG_5186", "art": "video", "quelle": "/…/IMG_5186.MOV", "zustand": "rechnet", "laeuft": "capture",
 "fortschritt": 0.42, "text": "Rekonstruktion: Netz wird erzeugt", "meldung": null, "netz": false, "fotos": 8,
 "messung": true, "erstellt": "2026-10-22T14:03:11",
 "capture": {"einstellung": "schnell", "zustand": "fertig", "dauer_s": 45.2, "bilder": 60, "ausgerichtet": 42,
             "huelle": {"laenge": 180, "breite": 117.3, "hoehe": 48.4}, "grundkoerper": {"laenge": 174, "breite": 102.1},
             "oberkante": 47.5, "masz": {"laenge": 180}, "auflage": true},
 "lage": {"drehung_z": 180.0, "verschiebung": [0, -1.2, 0], "massstab": 1.012, "rest_mm": 6.3, "paare": 8}}
```

- `art` (additiv, 22.10.2026): `video`, `fotos` oder `scan` (Kev Scan vom iPhone, SCAN.md). Bei `scan` ist `quelle` der
  Scan-Ordner, die Auswertung läuft als `laeuft: "capture"` (Text „Scan: …“), das Netz kommt als `REF_UPSERT` mit
  `quelle: "kevscan"` im System des Scans (Boden z = 0, Mitte x = y = 0), bis `referenz_vermessen` es über `lage` an
  das Modell legt; Satz `capture` in `REF_PHOTOS` sind die Bilder mit den Kameras aus ARKit.
- `zustand`: `leer` (nichts gerechnet), `rechnet` (`laeuft`: `capture` oder `messung`, `fortschritt` 0…1, `text`),
  `fertig`, `fehler` (`meldung`). `fotos`: Zahl der Fotos mit eingepasster Kamera (sonst der abgelegten Fotos).
- `capture.huelle` ist das Hüllmaß mit allen Anbauten, `capture.grundkoerper` die dichteste waagrechte Schicht ohne
  Anbauten (bei der Scarlett das Gehäuse ohne Knöpfe): beide getrennt anzeigen.
- `lage`: Netz aus demselben Video wie die Messung an das Modell angelegt (Drehung um Z und Verschiebung aus
  Kamerapaaren gleicher Videozeit, `rest_mm` = mittlerer Abstand der Kamerazentren danach); null = Netz im System von
  Object Capture (Boden z = 0, Mitte x = y = 0, lange Seite = X). Netz und Kameras im Satz `capture` sind schon bewegt.

`REF_PHOTOS.fotos[i]`: `name`, `bild` (absoluter Pfad, JPEG in Arbeitsgröße, lange Kante 1920), `maske` (PNG gleicher
Größe, 8 bit, Objekt hell; null beim Satz `capture`), `kontrolle` (Kontrollbild von fotomess oder null), `zeit` (s im
Video oder null), `iou` (Überdeckung Modell und Maske beim Einpassen oder null), `kamera` {`R` (3 × 3 zeilenweise,
Welt → Kamera), `t`, `f`, `cx`, `cy` (Pixel), `w`, `h` (Bildgröße, auf die sich f, cx, cy beziehen = Größe von
`bild`)}. Konvention OpenCV: Kamera x rechts, y unten, z Blickrichtung; Pixel = (f·x/z + cx, f·y/z + cy) mit
(x, y, z) = R·X + t, Ursprung links oben, X in mm im System des Modells. Die App zeigt das Foto durch genau diese
Kamera hinter dem Modell (Deckkraft, Differenz rot = nur Foto, blau = nur Modell).

`REF_RESULT.masse[i]`: `name` (param), `wert` (mm), `sigma` (mm; größer von 2,5 × Jackknife und 8 × statistisch),
`start` (Wert in model.py beim Messen), `aenderung`. `bekannt`: feste Maße (Maßstab). `huelle` {`min`, `max`,
`groesse`} des eingepassten Modells mit allen Teilen, `grundkoerper` {`teil`, `min`, `max`, `groesse`} das Teil mit dem
größten Hüllvolumen, `teile` je Teil. `empfehlungen[i]`: `art` (`nachmessen` \| `aufnahme` \| `unsicher` \|
`verworfen`), `text` (deutsch, für den Hinweis in der App), dazu `mass`, `anteil` (Restvarianz), `azimut`, `hoehe`.

### Abweichung, Maßstab, Scans in der App (22.10.2026, additiv)

Rest von Phase 4 (Zweig `rest-referenz`); ältere Gegenseiten ignorieren die neuen Typen und Felder. Umsetzung:
`kernel/src/kevcad_kernel/referenz/{abweichung,massstab,laufzeit_rest}.py`; Packen und Prüfen in `protocol.py`
(`pack_ref_abweichung`, `unpack_ref_abweichung`, `check_ref_abweichung`, `referenz_beispiele_rest`), Testdateien
`ref_deviation_modell.frame`, `ref_deviation_referenz.frame`, `ref_list_abweichung.frame`, `ref_scale_punkte.frame`,
`ref_scale_kante.frame`, `scan_list.frame`, `scan_import.frame` aus `kernel/tools/make_referenz_fixtures.py`.

| type | Richtung | Felder | Nutzlast / Antwort |
|---|---|---|---|
| `REF_DEVIATION` | Kernel → App | `referenz`, `run`, `auf` (`modell` \| `referenz`), `teil` (Teilname bei `modell`, sonst null), `feld` (Schlüssel), `punkte` (n), `dreiecke` (m), `grenze_mm`, `kennzahlen` | n × 3 f32 Punkte (Welt, mm), m × 3 u32 Dreiecke, n f32 Abstand in mm (positiv = die Referenz liegt außerhalb des Modells, negativ = innerhalb, NaN = keine Referenz in der Nähe); little-endian, ohne Lücken |
| `REF_SCALE` | App → Kernel | `id`, `referenz`, `mm` (echtes Maß), dazu `punkte` (zwei Punkte [x, y, z] am Referenznetz, Welt, mm, wie im Viewer) oder `kante` (`laenge`, `breite`, `hoehe`, `grund_laenge`, `grund_breite` der Hülle oder Name eines gemessenen param) | `ACK` mit `message`, dann `REF_LIST`, `REF_UPSERT`, `REF_PHOTOS`, `REF_RESULT`, `REF_DEVIATION` |
| `SCAN_LIST` | Kernel → App | `scans` (höchstens 30, neueste zuerst: `id`, `name`, `empfangen`, `erstellt`, `geraet`, `fotos`, `videobilder`, `objekt`, `groesse_mb`, `vorschau`, `zustand` (`neu` \| `uebernommen`), `referenzen` [{`projekt`, `name`, `stand`, `schnell`}]), `empfaenger` {`laeuft`, `port`, `name`, `dienst`}, `ordner`, `neu` (Kennung des gerade per WLAN empfangenen Scans, sonst null); beim Verbinden, nach jedem Empfang und nach jeder Übernahme | – |
| `SCAN_IMPORT` | App → Kernel | `id`, `scan` (Kennung aus `SCAN_LIST`), `name` (oder null), `schnell` (bool) – Kevins Klick „Scan übernehmen“, wie MCP `scan_importieren` | `ACK`, dann `REF_LIST` mit dem Fortschritt, am Ende `SCAN_LIST` |

- **Abweichung:** Der Kernel rechnet nach jedem Lauf, nach einem neuen Netz, einer neuen Lage und einem neuen Maßstab
  im Hintergrund, je Referenz mit Netz: `auf: "modell"` je Teil (ohne Kulisse) die fein unterteilte Oberfläche des
  Teils (Kanten höchstens etwa 1 bis 3 mm, alle Teile zusammen höchstens 250 000 Dreiecke) mit dem Abstand zum
  Referenznetz, Vorzeichen über die Außennormale des Modells; `auf: "referenz"` das Referenznetz (wie in `REF_UPSERT`)
  mit dem Abstand zum Modell. Ein Punkt ist nicht abgedeckt (NaN), wenn die Referenz weiter als `grenze_mm` weg ist
  (Vorgabe 6 % der Diagonale des Netzes, 10 bis 60 mm) oder ab 1 mm Abstand nur schräg daneben liegt (über 60° zur
  Normale). Ein Feld mit unverändertem Schlüssel `feld` schickt der Kernel nicht noch einmal; beim Verbinden kommen
  alle. Die App zeigt ein Feld nur, wenn die Kurzfassung in `REF_LIST` denselben Schlüssel nennt.
- `kennzahlen` (Feld und Kurzfassung): `mittel_mm` (Mittel des Betrags), `p95_mm`, `max_mm`, `versatz_mm` (Mittel mit
  Vorzeichen), `abgedeckt` (Anteil der Fläche), `punkte`, `ort_max` (Ort der größten Abweichung); Mittel und Anteil
  nach Fläche gewichtet, nur abgedeckte Punkte.
- `REF_LIST.referenzen[i]` additiv: `abweichung` (null ohne Netz) mit `stand` (`done` \| `laeuft` \| `failed`), `run`,
  `grenze_mm`, `skala_mm` (Spanne der Legende ± mm: aufgerundeter 95-%-Wert, oder fest über MCP), `skala_auto`,
  `skala_fest`, `angelegt` (Netz liegt über `lage` am Modell), `ms`, `meldung`, `teile` [{`teil`, `feld`,
  `kennzahlen…`}], `referenz` {`feld`, `kennzahlen…`}; `massstab` (null oder {`faktor` über alle Schritte, `mm`,
  `ist_mm`, `quelle` `punkte` \| `kante` \| `messung`, `kante`, `stand`}); `phase` (laufende Scan-Auswertung: „Einlesen“,
  „Bilder wählen“, „Bilder holen“, „Tiefe (PromptDA)“, „Verschmelzen (TSDF)“, „Netz erzeugen“, „Masken“, „Bericht“).
- `VIEW_CMD referenz_abweichung` {`name`, `auf`, `an`}: der Agent (MCP `referenz_abweichung(zeigen=true)`) schaltet die
  Farbkarte ein bzw. aus.
- **Maßstab:** skaliert um den Ursprung des Referenzsystems (Boden bleibt z = 0): `capture/netz_mm.obj`, PLY-Dateien,
  `poses.json` (`aligned`), `kameras.json`, `bericht.json`, die Maße in `referenz.json`; die Vermessung
  (`messung/messung.json`) nur, wenn `kante` ein gemessenes param ist. Scans (`art: "scan"`) sind metrisch und werden
  abgelehnt. Faktor 0,2 bis 5, Punkte höchstens 3 mm (bzw. 5 % ihres Abstands) neben dem Netz.

## Statik

Rein additiv (PLAN-STATIK.md, Strang „Statik Stufe 1“); ältere Apps ignorieren den Typ. Der Prüfer „statik“ rechnet
nach jedem Lauf im Rechenprozess (zuletzt, nach Stand, Montage und Druck): S0 (Kippen je Richtung, Rutschen, lose
Teile, Schrauben grob, Bauteile mit Last als Kragträger) und S1 (Stabwerk mit PyNite). Das volle Ergebnis kommt im
CHECK-Kopf als Feld `statik` zur Laufzeit; sie nimmt es dort heraus, merkt es und schickt es als `STATICS`. Im `CHECK`
an die App (und im Versionsarchiv) bleibt die Kurzfassung (`statik`: `stand`, `aktiv`, `szenarien` je mit `name`, `art`,
`quelle`, `ampel`, `ziel`, `text`, `kennzahlen`, `beschreibung`, `ms`). Rote und gelbe Urteile sind zusätzlich Befunde
`statik_*` im `CHECK` (Warnung bzw. Hinweis; die Statik sperrt den Export nicht). Packen und Prüfen in `protocol.py`
(`pack_statics`, `statik_kurz`, `check_statics_message`, Beispiel `statik_beispiel`), Testdateien `statics.frame`,
`statics_eigengewicht.frame`, `statics_failed.frame` und `statics.json` aus `tools/make_statik_fixtures.py`.

| type | Richtung | Felder | Nutzlast |
|---|---|---|---|
| `STATICS` | Kernel → App | `run`, `stand` (`done` \| `failed`), `aktiv` (Szenario, das die App anbietet), `zeigen` (bool: der Agent will `aktiv` im Viewer sehen, Farbverlauf und Verformung an), `meldung`, `szenarien`, `ueberdimensioniert`, `grenzen`, `vereinfachungen`, `modell`, `ms`, `reply_to` optional; nach jeder Prüfung, nach `szenario_rechnen`, nach `statik(szenario)` und beim Verbinden | – |

`szenarien[i]`:

```json
{"name": "Aufstützen 30 kg", "art": "statisch", "quelle": "modell", "ampel": "rot", "ziel": 2.0,
 "text": "Aufstützen 30 kg: rot – Rahmen/Rohr hält nicht (Sicherheit 0,2)", "beschreibung": "30 kg vorn auf dem Rohr",
 "kennzahlen": {"sicherheit": 0.2, "knicken": null, "kippreserve": 0.8, "rutschreserve": null, "durchbiegung_mm": 61.0,
                "durchbiegung_grenze_mm": 5.0, "verformung_max_mm": 61.0},
 "urteile": [{"art": "festigkeit", "teil": "Rahmen/Rohr", "ampel": "rot", "text": "…", "loesung": "…",
              "sicherheit": 0.2, "ziel": 2.0, "ausnutzung": 10.0, "ort": [0, 0, 30]}],
 "teile": [{"name": "Rahmen/Rohr", "ausnutzung": 10.0, "ampel": "rot", "verformung_mm": 61.0, "sicherheit": 0.2}],
 "staebe": [{"name": "Rahmen/Rohr", "punkte": [[0, 0, 30], [250, 0, 30], [500, 0, 30]], "ausnutzung": [10.0, 5.0, 0.0],
             "verschiebung": [[0, 0, 0], [0, 0, -22], [0, 0, -61]], "radius": 6.0, "sicherheit": 0.2, "ampel": "rot"}],
 "auflager": [{"stab": "…", "teil": "…", "punkt": [x, y, z], "kraft": [N], "moment": [Nmm], "art": "fest"}],
 "lasten": [{"teile": ["Rahmen/Rohr"], "kraft": [0, 0, -294.3], "punkt": [250, 0, 30], "kg": 30, "zeile": 12},
            {"teile": ["Rahmen/Rohr"], "kraft": [100, 0, 0], "punkt": [500, 0, 30], "kg": null, "zeile": 13,
             "gegen": ["Ball"], "paar": true}],
 "ueberhoehung": 1.0,
 "kippen": [{"name": "Der Aufbau um Rahmen (3 Teile)", "reserve": 9.6, "richtung_text": "+X", "teile": ["…"],
             "je_richtung": {"+X": {"kippwinkel": 31.0, "a_kipp": 5.9}}}]}
```

- `ampel`: `gruen` | `gelb` | `rot` | `grau` (nicht gerechnet). **Ausnutzung** = Zielsicherheit / vorhandene
  Sicherheit: bis 1 grün, bis 2 gelb, darüber rot (T5; Ziel statisch 2, dynamisch 3, Druckteile das Doppelte).
- `urteile[i].art`: `festigkeit`, `knicken`, `durchbiegung`, `kippen`, `rutschen`, `schraube`, `bauteil`,
  `ueberdimensioniert`, `stabwerk`; dazu optional `reserve`, `durchbiegung`, `grenze`, `schichtfaktor`,
  `quer_zur_schicht`, `alternative` (`stock_id`, `name`, `ersparnis_kg`, `ersparnis_eur`, `sicherheit` …).
- `teile`: Ausnutzung je Teil (Stäbe und Bauteile mit Nachweis); die App färbt die Teile damit (grün → gelb → rot).
- `staebe`: je Stab Stationen entlang der Achse (Welt, mm) mit Ausnutzung und Verschiebung (mm); `punkte`,
  `ausnutzung` und `verschiebung` sind gleich lang (mindestens 2). Die App zeichnet daraus den Farbverlauf und die
  Verformung, um `ueberhoehung` vergrößert, als Geist.
- `kippen[i].je_richtung`: Neigung in Grad bzw. waagrechte Beschleunigung in m/s², bei der die Gruppe kippt.
- `lasten` (additiv, Nachbesserung „statik-nach“, T32): die Einzellasten des Szenarios mit Kraft (N, Stoßfaktor
  eingerechnet) und Angriffspunkt (Welt, mm; ohne Angabe in model.py die Mitte der Teile bzw. der Stabachse). Ein
  **Kraftpaar** (innere Kraft, `st.last(…, gegen=…)` oder `st.kraftpaar(a, b, …)`) hat `gegen` (Teile der Gegenseite)
  und `paar: true`: auf `teile` wirkt `kraft`, auf `gegen` am selben Punkt `−kraft`. Die App zeichnet Lasten als Pfeile
  zum Angriffspunkt, ein Kraftpaar als zwei gegeneinander gerichtete Pfeile in eigener Farbe. Ältere Apps ignorieren
  das Feld.

App → Kernel: nur `STATICS_CANCEL` (Stufe 3, siehe „Festkörper“). Die App wählt Szenarien selbst; neue Szenarien rechnet
der Agent mit MCP `szenario_rechnen`, Kevin legt sie im Bereich „Simulation“ an (Abschnitt „Simulation“, `SIM_EDIT`).

### Ablauf (Stufe 2, additiv)

Szenarien mit Geschwindigkeit, Bremsen oder Animation (`st.szenario(…, geschwindigkeit=1, bremsen="abrupt")`, MCP
`dynamik`) rechnet der Kernel zusätzlich als Ablauf mit MuJoCo in einem eigenen Prozess (`statik/dynamik/`). Abläufe aus
model.py kommen nach jedem Lauf im Hintergrund: erst `STATICS` mit `ablauf.stand: "laeuft"`, einige Sekunden später
erneut mit `"done"` (oder `"failed"` mit `meldung`). Das Szenario trägt dann die Urteile des Ablaufs (`dyn_kippen`,
`dyn_ladung`, `dyn_rutschen`; Kippen und Rutschen der Stufe S0 entfallen) und ein Feld `ablauf`:

```json
{"stand": "done", "ampel": "rot", "text": "Bremsen aus 1 m/s: rot – Rollwagen kippt nach vorn (hebt 17 mm ab), …",
 "animation": "Ablauf: Bremsen aus 1 m/s", "dauer": 1.6, "fps": 50.0, "bilder": 81, "meldung": null,
 "antrieb": {"koerper": "Rollwagen mit …", "geschwindigkeit": 1.0, "verzoegerung": 10.0,
             "bremsen": "abrupt (Stillstand in 0,1 s)", "angriff": "boden"},
 "kennzahlen": {"kippreserve": 0.25, "a_abheben": 2.46, "abheben_max_mm": 16.6, "kippwinkel_max": 1.68,
                "a_kipp_hand": 14.1, "a_abheben_ohne_ladung": 13.92, "v_abheben": 0.29, "rutschgrenze": 5.89,
                "rutschreserve": 0.59, "setzt_auf": "Fangrolle",
                "ladung": [{"name": "Bowlingball", "versatz_max_mm": 46.4, "hebt_max_mm": 30.5, "bleibt": true,
                            "v_grenze": 1.12}], "kontaktkraefte": [{"paar": ["…", "…"], "max_n": 97.9}]},
 "handrechnung": {"b_mm": 169.3, "h_mm": 117.8, "a_kipp": 14.1, "text": "a = g · b / h = …"},
 "verlauf": {"zeit": [], "kipp": [], "abheben": [], "weg": [], "fuehrung": [],
             "ladung": {"Bowlingball": {"laengs": [], "hebt": []}}, "kraefte": {"A ↔ B": []}},
 "pfeile": [[{"punkt": [x, y, z], "kraft": [fx, fy, fz], "paar": ["A", "B"]}]],
 "ms": {"ablauf": 97.0, "suche": 1250.0, "varianten": 56, "gesamt": 1470.0}}
```

- `verlauf` und `pfeile` haben je Bild einen Eintrag (`bilder`, Bild k bei k / `fps`); `pfeile` sind die größten
  Kontaktkräfte des Bilds (N, Welt; die Kraft wirkt auf den zweiten Körper des Paars), die App zeichnet sie, solange die
  Zeitleiste die Animation `animation` zeigt. Urteile tragen zusätzlich `kurz` (Kurztext für die Liste).
- `kennzahlen.kippreserve` = Verzögerung, ab der der geschobene Körper hinten abhebt (über 2 mm) / Verzögerung im
  Szenario; `a_kipp_hand` die Handrechnung g · b / h, `a_abheben_ohne_ladung` die Simulation ohne Ladung bei anhaltender
  Verzögerung (Plausibilität); `ladung[i].v_grenze` die Geschwindigkeit, ab der die Ladung bei dieser Bremsart
  herausspringt.
- Den Ablauf spielt die vorhandene Zeitleiste ab: Der Kernel schickt die Lagen als gewöhnliches `ANIM_DEF` mit dem Namen
  `ablauf.animation` (zusätzliches Feld `ablauf: true`, alle Teile der bewegten Körper). Der nächste Lauf entfernt es
  wie jede Animation (`ANIM_REMOVE`). Kurzfassung im `CHECK`: `ablauf` mit `stand`, `ampel`, `text`, `animation` und
  den wichtigsten `kennzahlen`.
- Packen und Prüfen wie oben (`check_statics_message` prüft `ablauf`), Beispiel `statik_beispiel_ablauf`, Testdatei
  `statics_ablauf.frame` aus `tools/make_statik_fixtures.py`.

### Festkörper (Stufe 3, additiv)

Teile mit Last, die das Stabwerk als starr bzw. als Kragträger behandelt (Druckteile, Platten, Verbinder), rechnet der
Kernel zusätzlich als Volumen-FEM in einem eigenen Prozess (`statik/festkoerper/`, Gmsh, scikit-fem, pyamg): nach jedem
Lauf im Hintergrund (nur Szenarien mit Last), nach `szenario_rechnen` und `dynamik` für das neue Szenario und auf
Anfrage (MCP `festigkeit`). Erst kommt `STATICS` mit `festkoerper.stand: "laeuft"` (Fortschritt alle 0,3 s), dann
erneut mit `"done"` (oder `"failed"` mit `meldung`, `"abgebrochen"`). Das Szenario trägt dann je gerechnetem Teil ein
Urteil `festkoerper` statt des Kragträger-Urteils `bauteil`, die Ausnutzung des Teils in `teile` (mit `fem: true`) und
ein Feld `festkoerper`:

```json
{"stand": "done", "fortschritt": 1.0, "text": "1 Teil gerechnet", "meldung": null,
 "teile": [{"teil": "Wandhalter (Druck)", "stand": "done", "ampel": "rot", "sicherheit": 1.87, "ziel": 4.0,
            "ausnutzung": 2.14, "spannung_max": 7.05, "kriterium": "schicht", "ort": [3.7, -2.4, 104.0],
            "sicherheit_lagerrand": 1.52, "verformung_max_mm": 2.43, "kragtraeger": 1.98, "druckteil": true,
            "q": 0.4, "ausrichtungen": {"-z": 4.82, "-y": 4.82, "-x": 1.87}, "ausrichtung_beste": "-z",
            "netz": {"tetraeder": 535, "freiheitsgrade": 3543, "h_mm": 5.33, "fein": false}, "ms": 1960.0,
            "feld": "d0f84561664942f7ae15", "aus_speicher": false, "text": "Wandhalter (Druck) hält nicht …"}]}
```

- `sicherheit`: kleinste örtliche Sicherheit ohne die Knoten der Lagerfläche selbst (dort ist die starre Einspannung
  eine Idealisierung); `sicherheit_lagerrand` mit ihnen. `kriterium`: `mises`, `schicht` (Schichtfuge der Druckteile:
  Normalspannung und Schub quer zur Schicht gegen `quer_zur_schicht` · Festigkeit) oder `quer_unbekannt` (Drucklage
  unbekannt, überall abgemindert). `ausrichtungen`: Sicherheit, wenn das Teil mit `lager.druckteil(…, ausrichtung=…)`
  so gedruckt würde (gleiches Spannungsfeld); `ausrichtung_beste` nur, wenn sie mindestens 20 % mehr bringt.
  `kragtraeger`: die Sicherheit des Kragträger-Nachweises (S0) zum Vergleich.
- Kurzfassung im `CHECK` bzw. in `statik_kurz`: `festkoerper` mit `stand`, `fortschritt`, `text`, `meldung` und je
  Teil `teil`, `stand`, `ampel`, `sicherheit`. Das erste `CHECK` eines Laufs entsteht vor der FEM; das nachgetragene
  (`statik_im_hintergrund`, T34) trägt den Stand und die Befunde `statik_festkoerper`.
- Packen und Prüfen in `protocol.py` (`check_statics_message` prüft `festkoerper`), Beispiel
  `statik_beispiel_festkoerper`, Testdatei `statics_festkoerper.frame` aus `tools/make_statik_fixtures.py`.

| type | Richtung | Felder | Nutzlast |
|---|---|---|---|
| `STATICS_FIELD` | Kernel → App | `run`, `szenario`, `teil`, `feld` (Schlüssel wie `festkoerper.teile[i].feld`), `ziel`, `sicherheit`, `ampel`, `spannung_max`, `verformung_max_mm`, `ueberhoehung`, `werte` (`"ausnutzung"`), `punkte` (n), `dreiecke` (m); nach jeder gerechneten Rechnung je Teil und beim Verbinden (Felder des aktuellen Laufs) | n × 3 float32 Punkte (Welt, mm), m × 3 uint32 Dreiecke (nach außen orientiert), n float32 Ausnutzung (Ziel / örtliche Sicherheit), n float32 von-Mises-Spannung (N/mm²), n × 3 float32 Verschiebung (mm); little-endian, ohne Lücken |
| `STATICS_CANCEL` | App → Kernel | `seq`; beendet eine laufende Festkörper-Rechnung (danach `STATICS` mit `stand: "abgebrochen"`) | – |

- Die App zeigt ein Feld nur, wenn `STATICS` für dasselbe Szenario und Teil denselben Schlüssel `feld` nennt, und nur
  für Felder des laufenden `run` (ein neuer Lauf verwirft sie). Mit dem Farbverlauf zeichnet sie das Netz in Bändern der
  Ausnutzung (Breite 0,1 von 0 bis 2, Farben wie bei den Stäben) und blendet das Teil in der Ruhelage aus; mit der
  Verformung zeichnet sie das Netz um `ueberhoehung` verschoben als Geist.
- Packen und Prüfen: `pack_statics_feld`, `unpack_statics_feld`, `check_statics_feld`, Beispiel `statik_beispiel_feld`,
  Testdatei `statics_feld.frame`.

## Topologie

Rein additiv (PLAN-TOPOLOGIE.md, 23.10.2026); ältere Gegenseiten ignorieren die Typen. Der Kernel optimiert ein
Druckteil in einem eigenen Prozess (`topologie/`) und meldet den Stand als `TOPO` (laufend höchstens alle 0,3 s) und
die Netze dazu als `TOPO_FIELD`. Es gibt immer nur einen Auftrag (`auftrag`, laufende Nummer); ein neuer ersetzt den
alten. Packen und Prüfen in `protocol.py` (`pack_topo`, `check_topo_message`, `pack_topo_feld`, `unpack_topo_feld`,
`check_topo_feld`, `check_topo_app`, Beispiele `topo_beispiel`, `topo_beispiel_feld`), Testdateien `topo.frame`,
`topo_laeuft.frame`, `topo_feld_nachher.frame`, `topo_feld_dichte.frame`, `topo_feld_schutz.frame` und `topo.json` aus
`tools/make_topologie_fixtures.py`.

| type | Richtung | Felder | Nutzlast |
|---|---|---|---|
| `TOPO` | Kernel → App | `run`, `stand` (`laeuft` \| `done` \| `failed` \| `abgebrochen`), `auftrag`, `teil`, `szenario`, `einstellungen` (`behalten`, `ueberhang`, `fein`, `steg`, `bett`, `bohrungen`, `einsaetze`, `kontakt`, `iterationen`), `fortschritt` (0…1), `phase` (`vorbereiten`, `vorher`, `optimieren`, `oberflaeche`, `koerper`, `nachher`, `druck`, `fertig`), `text`, `text_lang`, `iteration`, `max_iter`, `verlauf`, `voxel`, `h_mm`, `kennzahlen`, `schutz`, `netz`, `gitter`, `druckpruefung`, `hinweise`, `grenzen`, `meldung`, `ergebnis`, `quelle` (`modell` \| `agent` \| `app`), `modell_schluessel`, `behalten_wirksam`, `optimierung`, `ms`, `berechnet`; während der Rechnung und am Ende, beim Verbinden der letzte Stand | – |
| `TOPO_FIELD` | Kernel → App | `art` (`dichte` \| `schutz` \| `koerper` \| `vorher` \| `nachher`), `auftrag`, `teil`, `iteration` (bei `dichte`), `werte` (`"ausnutzung"` bei vorher/nachher, sonst null), `sicherheit`, `ziel`, `spannung_max`, `verformung_max_mm`, `ueberhoehung`, `punkte` (n), `dreiecke` (m); Dichte etwa jede Sekunde der Rechnung, die übrigen am Ende und beim Verbinden | n × 3 float32 Punkte (Welt, mm), m × 3 uint32 Dreiecke (nach außen); mit `werte` dazu n float32 Ausnutzung, n float32 von Mises (N/mm²), n × 3 float32 Verschiebung (mm) wie `STATICS_FIELD`; little-endian, ohne Lücken |
| `TOPO_START` | App → Kernel | `seq`, `teil`, `szenario` (fehlt = das mit der größten Ausnutzung), `behalten`, `ueberhang`, `fein` (optional `steg`, `bett`, `lager`: `kontakt` oder `bohrungen`) | – (danach `TOPO`) |
| `TOPO_CANCEL` | App → Kernel | `seq`; beendet den laufenden Auftrag (danach `TOPO` mit `stand: "abgebrochen"`) | – |
| `TOPO_APPLY` | App → Kernel | `seq`; übernimmt das Ergebnis als neue Variante (Versionen) und trägt `topologie.optimieren(…)` in model.py ein | – (danach `VERSIONEN`, `RUN_START` …) |

- `verlauf[i]`: `i` (Iteration ab 1), `c` (Nachgiebigkeit in N·mm), `volumen` (Anteil des Bauraums), `grau` (Anteil der
  Zwischenwerte); die App zeigt `c` relativ zur ersten Iteration.
- `kennzahlen`: `vorher` und `nachher` je mit `volumen_mm3`, `masse_g`, `filament_g`, `druckzeit_min` (Schätzung wie die
  Druckvorschau, Einstellungen „tragend“), `ueberhang_mm2`, `steg_min_mm` (nur nachher), aus der Festkörper-FEM
  `sicherheit`, `ziel`, `ampel`, `ausnutzung`, `spannung_max`, `verformung_max_mm`, `kriterium`, `ort`; `ersparnis` mit
  `volumen_prozent`, `masse_g`, `filament_g`, `druckzeit_min`.
- `schutz`: `anteil` (geschützter Anteil des Bauraums) und `zonen[i]` mit `art` (`Bohrung`, `Gewindeeinsatz M4`,
  `Lastfläche`, `Klemmfläche zu …`, `Bettfläche`, `Schutz aus model.py (…)`), dazu `d`, `ring_mm`, `haut_mm`, `tiefe`,
  `elemente`.
- `ergebnis`: `datei` (relativ zum Projekt, `topologie/<teil>-<schlüssel>.brep`), `schluessel` (Modellschlüssel, wie
  model.py ihn berechnet), `im_modell` (model.py lädt dieses Ergebnis schon), `aus_projekt` (nicht neu gerechnet),
  `variante` (nach `TOPO_APPLY`).
- Die App zeigt während `laeuft` die Dichte (`dichte`) halbdurchsichtig über dem blass gezeigten Teil, danach wahlweise
  „Vorher“ bzw. „Nachher“ als Bänder der Ausnutzung (wie `STATICS_FIELD`, das Teil ist dann ausgeblendet) und auf Wunsch
  die Schutzzonen (`schutz`). Felder eines anderen `auftrag` verwirft sie.

## Simulation

Rein additiv (PLAN-SIMULATION.md, 23.10.2026); ältere Gegenseiten ignorieren die Typen. Bereich „Simulation“ (⌘4) der
App: Lastfälle, Kräfte und Lager, die Kevin per Klick anlegt, liegen in `<projekt>/simulation.json` (Format in
`kernel/src/kevcad_kernel/simulation/datei.py`) und kommen bei jedem Lauf zu den Szenarien aus model.py dazu (gleicher
Name: die App gewinnt). Der Agent sieht und ändert dieselben Daten (MCP `simulation_liste`, `simulation_aendern`,
`simulation_rechnen`). Packen und Prüfen in `protocol.py` (`pack_sim`, `check_sim_message`, `pack_sim_job`,
`check_sim_job`, `check_sim_app`, Beispiele `sim_beispiel`, `sim_job_beispiel`), Testdateien `sim.frame`,
`sim_job.frame`, `sim_job_laeuft.frame` und `sim.json` aus `tools/make_simulation_fixtures.py`.

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `SIM` | Kernel → App | `run`, `stand` (Zähler von simulation.json), `datei`, `vorhanden`, `lastfaelle`, `modell`, `lager`, `modell_lager`, `abgeleitet`, `topologie`, `hinweise`, `fehler`, `job`, `reply_to` optional; nach jedem Lauf (nach STATICS), nach jeder Änderung, beim Verbinden, auf `SIM_REQ` | – |
| `SIM_JOB` | Kernel → App | `auftrag`, `was` (`rechnen` \| `festigkeit` \| `ablauf` \| `grenze`), `lastfall`, `teil`, `grenze` (`last` \| `neigung` \| `geschwindigkeit`), `von` (`app` \| `agent`), `stand` (`laeuft` \| `done` \| `failed` \| `abgebrochen`), `fortschritt` (0…1 oder null), `text`, `ergebnis`, `meldung`, `ms`; beim Start, bei Fortschritt (FEM, Ablauf; höchstens alle 0,4 s) und am Ende | – |
| `SIM_REQ` | App → Kernel | `id` | `SIM` mit `reply_to` |
| `SIM_EDIT` | App → Kernel | `id`, `basis` (erwarteter `stand`, optional), `ops` (Liste von Operationen wie MCP `simulation_aendern`) | `ACK` (`message`: Meldungen bzw. Fehler; alles oder nichts), danach `STATICS` (alles mit dem letzten Modell neu gerechnet) und `SIM` |
| `SIM_RUN` | App → Kernel | `id`, `was`, `lastfall`, `teil`, `fein`, `grenze` | `ACK` (`message`: Nummer des Auftrags), danach `SIM_JOB` |
| `SIM_CANCEL` | App → Kernel | `seq`, `id` optional | `SIM_JOB` mit `stand: "abgebrochen"` |

`lastfaelle[i]` (App): `name`, `art` (`statisch` \| `dynamisch`), `beschreibung`, `kopie_von`, `neigung` (`grad`,
`richtung` `+x` … oder Vektor), `beschleunigung` (m/s²), `fahrt` (`geschwindigkeit`, `bremsen` `abrupt` \| `anprall` \|
m/s², `dauer`, `animation`, `angriff` `boden` \| mm, `fahrtrichtung`, `antrieb`), `stoss`, `untergrund`, `ziel`
(`sicherheit`, `durchbiegung` als x in L/x), `ampel`, `text`, `gerechnet` und `lasten[j]`:

```json
{"id": "L1", "teil": "Halter", "gegen": null,
 "ort": {"flaeche": 5, "punkt": [40, 0, 60], "normale": [0, 0, 1],
         "signatur": {"t": "plane", "a": 800.0, "n": [0, 0, 1], "c": [40, 0, 60]}},
 "richtung": {"art": "normale"}, "betrag": 30, "einheit": "kg", "kraft": [0, 0, -294.3],
 "zustand": "ok", "zustand_text": "", "kraft_wirksam": [0, 0, -294.3], "punkt_wirksam": [40, 0, 60],
 "normale_wirksam": [0, 0, 1], "flaeche_wirksam": 5}
```

- `richtung.art`: `normale` (in die angeklickte Fläche hinein; `umkehren` zieht), `achse` (`achse` `+x` … `-z`) oder
  `frei` (`azimut`, `hoehe` in Grad oder `vektor`). `einheit` `N` oder `kg` (F = m · 9,81). `kraft` rechnet der Kernel
  (`simulation/kraft.py`; die App spiegelt es für die Vorschau in `SimKraft`).
- `zustand` nach der Zuordnung im aktuellen Modell: `ok`, `neu` (andere Fläche bzw. umbenanntes Teil, `zustand_text`
  „Fläche 12 → 15“), `fehlt` (nicht mehr zuordenbar, zählt nicht mit), `offen` (noch kein Lauf). `*_wirksam`: Kraft,
  Punkt, Normale und Fläche, mit denen gerechnet wird.
- `modell[i]`: Szenarien aus model.py bzw. Standard (`name`, `quelle`, `art`, `zeile`, `ampel`, `text`,
  `beschreibung`, `dynamisch`, `ersetzt`: von einem gleichnamigen Lastfall der App ersetzt).
- `lager[i]` (App): `id`, `teil`, `art` (`fest` \| `gelenkig` \| `gleitend`), `auf` (`flaeche` \| `punkt` \| `teil`),
  `ort`, `zustand`, `zustand_text`, `punkt_wirksam`, `normale_wirksam`, `flaeche_wirksam`. `modell_lager[i]`: Lager aus
  `st.lager` (flach: `punkt`, `normale`, `flaeche`, `zeile`). Lager gelten für alle Lastfälle.
- `abgeleitet[i]`: `id` (`boden:<teil>` = steht auf dem Boden bzw. der Kulisse; `kontakt:<teil>|<nachbar>` = Kontakt
  trägt im Bauteil-Nachweis und in der FEM), `art`, `teil`, `nachbar`, `text`, `punkt`, `aktiv`, `ersetzt` (Kennung des
  ausdrücklichen Lagers, das es ersetzt).
- `topologie`: je Druckteil die Einstellungen des Bereichs (`szenario`, `behalten`, `ueberhang`, `fein`, `steg`,
  `bohrungen`, `einsaetze`, `kontakt`, `bett`, `lager`, `schutz` [{`art`: `index`, `index`, `zustand`, `text`}]).
- `SIM_JOB.ergebnis` bei `grenze`: `art`, `lastfall`, `werte` [{`kriterium`, `grenze`, `einheit` (`×` \| `°` \| `m/s`),
  `text`, `massgebend`, `last_n`}], `text`, `hinweis`; bei `festigkeit`: `teile` [{`teil`, `ampel`, `sicherheit`,
  `ziel`, `kriterium`}]; bei `ablauf`: `ampel`, `animation`, `kennzahlen`.

Operationen (`ops`, wie `simulation_aendern`): `lastfall_neu` (`name` und Felder), `lastfall_setzen` (`name`,
`felder`), `lastfall_kopieren` (`von` App oder model.py, `name`), `lastfall_umbenennen` (`name`, `neu`),
`lastfall_loeschen` (`name`), `last_setzen` (`lastfall`, `last` ohne `id` = neu), `last_loeschen` (`lastfall`, `id`),
`lager_setzen` (`lager`), `lager_loeschen` (`id`), `abgeleitet` (`id`, `aktiv`), `topologie` (`teil`, `einstellungen`).

Ergänzungen bestehender Nachrichten (additiv):

- `STATICS.szenarien[i].lasten[j].id`: Kennung einer Last aus der App; `szenarien[i].quelle` ist `app` für Lastfälle aus
  simulation.json.
- `TOPO_START`: `bohrungen`, `einsaetze`, `kontakt`, `bett` (Wahrheitswerte: automatische Schutzzonen je Art), `steg`
  (Linienbreiten), `schutz` [{`art`: `index`, `index`}] (Schutzflächen per Klick); die Zone heißt dann „Schutzfläche n“.

## Phase 7: Renderings

Rein additiv (22.10.2026, PLAN-PHASE7-RENDERINGS.md); ältere Gegenseiten ignorieren die neuen Typen. Der Kernel steuert
jeden Auftrag „R-n“: schnell rendert die App (RealityKit), Foto rendert Blender im Kernel. Testdateien:
`kernel/tools/make_render_fixtures.py` schreibt `render_*.frame` und `render.json` nach
`app/KevCADCore/Tests/KevCADCoreTests/Fixtures/`. Referenz: `protocol.py` (`RENDER_NACHRICHTEN`,
`check_render_message`, `render_beispiele`).

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `RENDER_START` | App → Kernel | `id`, `szene`, `ansicht`, `kamera` (oder null), `breite`, `hoehe`, `qualitaet` (`schnell` \| `foto`), `hintergrund` (oder null = wie die Szene), `ziel` (oder null), `vorschau` (bool) | `ACK` (`message` = Auftrag „R-n“ oder Fehler), danach `RENDER_STATUS` |
| `RENDER_CANCEL` | App → Kernel | `id`, `auftrag` | `ACK` |
| `RENDER_REQ` | Kernel → App | `id`, `auftrag`, `szene` (Objekt, unten), `ansicht`, `kamera`, `width`, `height`, `teile` (Darstellung je Teil, unten), `path` (absolute Zieldatei .png), `vorschau` | `RENDER_RES` |
| `RENDER_RES` | App → Kernel | `reply_to`, `ok`, `path`, `width`, `height`, `ms`, `kamera` (wie bei `RENDER_SCENE`), `message` (oder null), `phasen` (ms je Phase: `netze_ms`, `umgebung_ms`, `szene_ms`, `rendern_ms`, `png_ms`, additiv `schatten_ms` (Schatten auf dem Boden), `wiederholt` (1: das erste Bild kam nicht zurück, zweiter Versuch mit neuem Renderer)) | – |
| `RENDER_SCENE_REQ` | Kernel → App | `id`, `auftrag`, `ansicht`, `kamera`, `width`, `height`, `kulisse` (Namen der Kulisse-Teile) | `RENDER_SCENE` |
| `RENDER_SCENE` | App → Kernel | `reply_to`, `ok`, `kamera` {`projection` (`perspective` \| `orthographic`, additiv 23.10.2026: parallele Viewer-Ansicht), `position`, `target`, `up`, `fov_deg` (vertikal), `ortho_height_mm` (sichtbare Höhe bei `orthographic`, sonst null), `name` (Kamera oder null)} in mm mit Z oben, `teile` (sichtbare Teile `{name, matrix}`; `matrix` 16 Zahlen spaltenweise = Lage gegenüber PART_UPSERT, null = Ruhelage), `message` | – |
| `RENDER_STATUS` | Kernel → App | `auftrag`, `zustand` (`wartet` \| `laeuft` \| `fertig` \| `fehler` \| `abgebrochen`), `qualitaet`, `szene` (Name), `fortschritt` (0…1), `text`, `pfad` (nur bei `fertig`), `width`, `height`, `ms`, `von` (`agent` \| `app`), `vorschau`, `fehler` | – |

`RENDER_REQ.szene`: `name`, `titel`, `licht` (`studio` = eigene Softbox-Umgebung \| `umgebung` = HDRI), `umgebung`
(absoluter Pfad einer Radiance-HDR oder null), `staerke`, `drehung` (Grad um Z), `hintergrund` (`#RRGGBB` \|
`umgebung` \| `transparent`), `transparent` (bool), `boden` (bool: Schatten auf dem Boden unter dem tiefsten Punkt).

`RENDER_REQ.teile[i]` (KATALOG.md „Rendering“, `render/materialien.py`): `name`, `basisfarbe` [r, g, b] sRGB 0…1,
`metallisch`, `rauheit`, `oberflaeche`, `klarlack`, `klarlack_rauheit`, `anisotropie`, `durchsichtig`, optional
`schichthoehe`, `material`, `quelle` (`katalog` \| `abgeleitet` \| `teilfarbe` \| `ohne_material`), `kulisse` (bool), additiv
`druck_oben` (Aufbaurichtung des Druckteils als Einheitsvektor in Weltlage aus der Druckprüfung, nur bei `schichten`;
Schichtlinien liegen quer dazu, ohne das Feld quer zu Z).
Teile ohne Eintrag rendert die App mit ihrer Farbe, matt. Kulisse-Teile (PART_UPSERT.kulisse, Gruppe `Kulisse/`)
sind im Bild, zählen aber nicht für den Ausschnitt von `produkt` und den Standardansichten; bei durchsichtigem
Hintergrund (Freisteller) bleiben sie weg.

Szene wie im Viewer: sichtbare Teile (ausgeblendete und in der Animation verborgene nicht), Lage mit Explosion und
Animation, bei einer Kamera ohne ihr Objektiv und Teile vor dem Augpunkt. Schnitt, Hervorhebungen, Röntgen und Maße
gehen nicht ins Bild. `ansicht`: `aktuell` (Viewer-Kamera; eine parallele Projektion rendert echt orthografisch mit
derselben sichtbaren Höhe, RealityKit `OrthographicCameraComponent`, Blender Kamera `ORTHO` mit `ortho_scale`), `produkt` (3/4-Ansicht vorn rechts, 24° von oben, 22° Bildwinkel, eingepasst) oder eine
Standardansicht (26°, eingepasst); `kamera` (Phase 5) hat Vorrang. Vorschau-Aufträge (`vorschau: true`) schreibt der
Kernel nach `output/renders/.vorschau/` und die App zeigt sie nur im Dialog.
