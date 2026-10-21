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
| `AGENT` | `connected` (bool), `activity` (Text oder null, z. B. „misst Abstand Lasche ↔ Grundplatte") | – |
| `VIEW_CMD` | `id`, `cmd`, `args` – siehe unten; App antwortet `ACK` | – |
| `SCREENSHOT_REQ` | `id`, `width`, `height`, `source`: `current` \| `offscreen`, `view` (nur offscreen: Standardansicht oder null), `hide_overlays` | – |
| `MEASURE_RES` | `reply_to`, `result` (siehe Messen) | – |
| `EXPORT_RES` | `reply_to`, `files` (Liste absoluter Pfade) | – |
| `ACK` | `reply_to`, `ok`, `message` | – |

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

### Inventar-Regel

- `PART_UPSERT.inventar`: `ok` | `fehlt` (nur gesetzt, wenn die Regel im Projekt an ist und kein Skizzenlauf läuft).
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
| `ANIM_VIDEO_REQ` | `id`, `name`, `width`, `height`, `fps`, `kamera` (null = Viewer-Kamera bzw. Kamerafahrt; reserviert für „Kamera/<name>“), `format` (`mp4` = H.264 \| `prores` = ProRes 422), `path` (absolute Zieldatei, `<projekt>/output/animationen/<name>.mp4`) | App antwortet `ANIM_VIDEO_RES` |

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
Dicke unter 0,05 mm) und Paare aus `anim.erlaube(...)` zählen nicht.

### App → Kernel

| type | Felder | Antwort |
|---|---|---|
| `ANIM_STATE` | `name`, `zeit`, `bild`, `spielt`, `schleife`, `geschwindigkeit` (bei Abspielen, Anhalten, Springen, nicht je Bild) | – |
| `ANIM_COLLISIONS_REQ` | `id`, `name`, `schritt` (jedes n-te Bild, Vorgabe 3) | `ANIM_COLLISIONS` mit `reply_to` |
| `ANIM_VIDEO_RES` | `reply_to`, `ok`, `path`, `frames`, `ms`, `message`, `kamera` | – |
