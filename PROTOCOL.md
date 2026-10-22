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
Eingabe im Dialog. CAD-Dateien kommen über die TraceParts-API (mit Kevins Schlüssel) oder aus `~/Downloads`.

## Prüfung

Rein additiv; ältere Apps ignorieren `CHECK`. Nach jedem erfolgreichen Lauf prüft der Kernel den Stand (im
Rechenprozess, direkt nach `RUN_DONE`, siehe `kernel/src/kevcad_kernel/pruefung/`): zuerst Durchdringungen; weitere
Prüfungen (Schweben, Standsicherheit, Einbaubarkeit, Druckregeln, Bedingungen) liefern Befunde im selben Format.

### Kernel → App

| type | Felder | Nutzlast |
|---|---|---|
| `CHECK` | `run`, `state` (`running` \| `done` \| `teilweise` \| `cancelled` \| `failed`), `duration_ms`, `message` (Text oder null), `zusammenfassung` (z. B. „2 Durchdringungen · 1 Teil nicht einbaubar“, leer = nichts offen), `zaehler` (`fehler`, `warnung`, `hinweis`), `befunde` (Liste), `geometrie` (Liste `{befund, vert, tri}`), optional `gewinde`, `erlaubt` (nicht gemeldete Überlappungen mit Grund), `montage`, `stand`, `im_hintergrund` | Schnittkörper |

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

Testdateien: `check_done.frame`, `check_running.frame`, `check_teilweise.frame`, `check.json` (aus
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
| `PRINT_SETTINGS` | App → Kernel | `id`, `teil` oder `gruppe`, `einstellungen` (Wert `null` = Vorgabe zurück) und/oder `zweck`, `zuruecksetzen`, `von` | `ACK`, danach `PRINT_PREVIEW` |
| `PRINT_EXPORT_REQ` | App → Kernel | `id`, `platten` (leer = alle), `ziel` (Pfad .3mf oder null) | `ACK`, danach `PRINT_EXPORT_RES` |
| `PRINT_EXPORT_RES` | Kernel → App | `reply_to`, `ok`, `pfad`, `platten`, `fehler` (dazu `hinweise`, `ms`, `geprueft`) | – |
