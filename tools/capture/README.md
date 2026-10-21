# kevcad-capture · Referenz aus einem Handyvideo

Strang R-C aus [PLAN-PHASE4-REFERENZ.md](../../PLAN-PHASE4-REFERENZ.md) (Entscheidungen R1–R4). Kommandozeilenprogramm
in Swift (SwiftPM, nur Apple-Frameworks): Handyvideo → scharfe Einzelbilder → Apple Object Capture
(`PhotogrammetrySession`) → Netz, Kameraposen, Punktwolke → Boden abschneiden, Z nach oben, Maßstab aus einem
bekannten Maß → Bericht in mm. Fortschritt als JSON-Zeilen auf stdout, damit Kev CAD ihn anzeigen kann.

```
Video ──AVAssetReader (Hardware-Decoder, direkt auf Zielgröße)──► Laplace-Varianz je Bild (vImage)
      ──je Zeitfenster das schärfste──► bilder/*.jpg (Hochformat, sRGB)
      ──PhotogrammetrySession (sequential, Maske an)──► roh/obj, roh/punktwolke.ply, poses.json
      ──Nachbearbeitung──► netz_mm.obj/.usdz, punktwolke_mm.ply, poses.json (aligned), bericht.json/.md
      ──Blender (optional)──► Kontrollbilder vorne/Seite/oben/schräg
```

## Bauen und testen

```bash
swift build -c release --package-path tools/capture     # → tools/capture/.build/release/kevcad-capture
swift test --package-path tools/capture                 # Auswahl, Schärfe, RANSAC, Rechteck, Kreis, Schicht
```

macOS 15 oder neuer, Apple Silicon. Brennweiten je Kamera (`Pose.intrinsics`) und Verzeichnung gibt die API erst ab
macOS 26 her; auf macOS 15 fehlen in `poses.json` dann `K` und `lens_distortion`.

## Aufruf

```bash
# alles in einem Lauf (Empfehlung „schnell“, siehe unten)
kevcad-capture lauf IMG_5182.MOV --aus ~/Projekte/x/referenzen/rollwagen \
    --bilder 60 --kante 1920 --detail reduced \
    --masz laenge=610 --pruef breite=410 --pruef rad=100 \
    --kontrollbilder build/capture/kontrolle

# Teilschritte
kevcad-capture bilder IMG_5182.MOV --aus <ordner> --bilder 120 --kante 2880
kevcad-capture rekonstruktion <ordner> --detail medium
kevcad-capture nachbearbeitung <ordner> --masz grund_breite=410     # ~1 s, z. B. nach neuem Maß
```

| Option | Wirkung |
|---|---|
| `--bilder N` | Anzahl Bilder (Standard 80). Das Video wird in N gleich lange Fenster geteilt, je Fenster gewinnt das schärfste Bild |
| `--kante PX` | lange Kante der Bilder (Standard 1920, `0` = Original 3840). Der Decoder skaliert selbst, die Schärfe wird in Zielgröße gemessen |
| `--von S`, `--bis S` | nur diesen Abschnitt des Videos (Sekunden), z. B. ohne das Umdrehen am Anfang |
| `--brennweite35 MM` | 35-mm-Brennweite in die EXIF-Daten (nur wenn sicher bekannt; Object Capture schätzt sie sonst selbst) |
| `--detail D` | `preview`, `reduced` (Standard), `medium`, `full`, `raw` |
| `--ohne-maske` | `isObjectMaskingEnabled = false` |
| `--hohe-empfindlichkeit` | `featureSensitivity = .high` (texturarme Gegenstände, langsamer) |
| `--ungeordnet` | `sampleOrdering = .unordered` statt `.sequential` (lose Fotos statt Video) |
| `--posen-zuerst` | Posen in eigener erster Anfrage: `poses.json` nach rund der Hälfte der Zeit, der Lauf dauert dafür ~40 % länger |
| `--roh-usdz` | zusätzlich `roh/modell.usdz` von Object Capture (ohne Maßstab; kostet 5 s bei reduced, 17 s bei medium) |
| `--ohne-usdz` | kein `netz_mm.usdz` (das schreibt sonst die Nachbearbeitung aus dem OBJ, ModelIO + `usdzip`) |
| `--masz NAME=MM` | bekanntes Maß, setzt den Maßstab: `laenge` (längste waagrechte Ausdehnung), `breite`, `hoehe`, `grund_laenge`, `grund_breite` |
| `--pruef NAME=MM` | Prüfmaß, wird mit Abweichung in mm und % berichtet (Namen wie `--masz`, dazu `rad`) |
| `--ohne-boden-schnitt` | Boden finden und ausrichten, aber nicht abschneiden |
| `--kontrollbilder ORDNER` | Kontrollbilder mit Blender (`/Applications/Blender.app` oder `$KEVCAD_BLENDER`) |
| `--kopie ORDNER` | `poses.json` mit Bildern sofort nach der Ausrichtung, alle Ergebnisse am Ende zusätzlich dorthin |
| `--behalte-checkpoint` | Zwischenstände von Object Capture behalten (sonst gelöscht, ~300 MB je Lauf) |
| `--leise` | keine Hinweise auf stderr |

Maße im Bericht:

- **Hüllmaß** L × B × H: alle Punkte des Objekts, robust (0,1–99,9 %); waagrecht ohne den Bodenrand (unterste 6 %
  der Höhe), an dem sonst Bodenreste hängen. Enthält abstehende Teile (ausgeschwenkte Lenkrollen).
- **Grundkörper** L × B: die dichteste waagrechte Schicht (beim Rollwagen der Rahmen), 0,5–99,5 % der Punkte
  dieser Schicht über dem Bodenrand. Seine Achsen und seine Mitte legen das Koordinatensystem fest (lange Seite = X).
- **Oberkante im aufrechten Stand**: liegt der Gegenstand kopfüber (Anbauten oben), ist das die Gesamthöhe, sonst die
  obere waagrechte Ebene.
- **Räder**: je Ecke Kreisausgleich (RANSAC + Kåsa) auf dem Umriss in der senkrechten Radebene, Mittelwert und Streuung.

## Ausgabe

```
<aus>/bilder/bild_0001.jpg …     ausgewählte Bilder (bleiben, alles andere Zwischenmaterial wird gelöscht)
<aus>/bilder.json                Auswahl: Videobild, Zeit, Schärfe, Fenster-Median
<aus>/poses.json                 Kameras je Bild, roh und ausgerichtet (siehe unten)
<aus>/roh/obj/ roh/punktwolke.ply roh/rekonstruktion.json   Object Capture, ohne Maßstab, Y oben
<aus>/netz_mm.obj, netz_mm.mtl, *.png, netz_mm.usdz    Objekt ohne Boden, mm, Z oben, Boden z = 0, Mitte x = y = 0
<aus>/punktwolke_mm.ply          Punktwolke im selben System, nur Objektbereich
<aus>/bericht.json, bericht.md   Maße, Prüfmaße, Zeiten, Transformation roh → mm
```

`poses.json` (`format: kevcad-capture/poses`): je Kamera `image`, `path`, `width`, `height`, `time_s`, `video_frame`
und zwei Formen `raw` (Object-Capture-Welt) und `aligned` (Kev-CAD-System, mm). Jede Form hat `camera_to_world`
(4×4 zeilenweise, RealityKit-Kamera: X rechts, Y oben, Blick −Z), `position`, `view_dir`, `up`, `K`, `fx`, `fy`,
`cx`, `cy`, `focal_35mm`, `hfov_deg` und `opencv` mit `R`, `t` (Welt → Kamera, X rechts, Y unten, Z Blick; Pixel =
K · (R·X + t)). Die Verzeichnung steht einmal oben (`lens_distortion`, Apple-Format). Geprüft: das Netz mit
`aligned.opencv` und `K` in die Bilder projiziert deckt sich mit dem Rollwagen.

## Fortschritt (stdout, eine JSON-Zeile je Ereignis)

Jede Zeile hat `event` und `t` (Sekunden seit Start).

| event | Felder |
|---|---|
| `start` | `command`, `input`, `out`, `images`, `long_edge`, `detail` |
| `video` | `width`, `height`, `duration`, `start`, `end`, `fps`, `frames`, `decode_width`, `decode_height`, `orientation` |
| `progress` | `phase` (`frames`, `reconstruction`, `post`), `fraction` 0…1; dazu `frame`/`selected`, `request`/`stage` oder `step` |
| `frames_done` | `count`, `decoded`, `seconds`, `dir` |
| `reconstruction_start` | `detail`, `object_masking`, `sequential`, `high_sensitivity`, `max_images`, `max_dimension` |
| `stage` | `stage` (`pre_processing`, `image_alignment`, `point_cloud_generation`, `mesh_generation`, `texture_mapping`, `optimization`), `request`, `remaining_s` |
| `file` | `kind` (`poses`, `poses_copy`, `point_cloud_raw`, `obj_raw`, `usdz_raw`, `mesh_mm`, `usdz_mm`, `point_cloud_mm`, `preview`, `report`), `path` |
| `skipped_sample` | `sample` (Bild ließ sich nicht ausrichten) |
| `warning`, `error` | `message` |
| `reconstruction_done` | Zahlen und Zeiten wie `roh/rekonstruktion.json` |
| `copied` | `dest`, `items` |
| `done` | `report` (Pfad), `summary` (Inhalt von `bericht.json`) |

Exit-Code 0 = fertig, 1 = Fehler (letzte Zeile `error`), 2 = falscher Aufruf.

MESSUNG_PLATZHALTER

## Grenzen

- **Spiegelnde, transparente und texturlose Flächen** (Edelstahl, Glas, glatter einfarbiger Kunststoff): Object
  Capture findet dort keine Merkmale; Flächen fehlen, wellen sich oder werden aus der Umgebung gespiegelt
  rekonstruiert. Matter Gegenstand mit etwas Struktur ist Voraussetzung, notfalls mattieren (Kreidespray).
- **Kein Maßstab ohne LiDAR:** Aus einem normalen Video ist das Netz maßstabslos (im Test lag die Rohgröße um den
  Faktor 2,8 daneben). Der Maßstab kommt immer aus einem echten Maß (R3); ohne `--masz` schreibt das Programm die
  Rohwerte × 1000 und vermerkt `massstab_bekannt: false`.
- **Gegenstand nicht bewegen:** Object Capture rekonstruiert die starre Szene. Im Testvideo wird der Rollwagen nach
  10 s umgedreht; die Objektmaskierung hat ihn nicht von der Umgebung getrennt, sondern Boden und Hintergrund
  mitgenommen und die Bilder vor dem Umdrehen gegen den Boden ausgerichtet. Ergebnis: Netz zeigt nur die
  kopfüber liegende Lage, die Posen der ersten Bilder passen nicht zum Wagen. Abhilfe: Abschnitte getrennt mit
  `--von`/`--bis` rekonstruieren.
- **Bodenrand:** Wo der Gegenstand den Boden berührt, verschmilzt das Netz mit Bodenresten („Schürze“, einige mm
  hoch und bis 20 mm breit). Das Programm schneidet bei 1,5 × RANSAC-Toleranz und misst waagrecht erst über 6 % der
  Höhe; für die Außenkante eines Kastens ist das Grundkörpermaß verlässlicher als das Hüllmaß.
- **Hüllmaß enthält Anbauten:** Ausgeschwenkte Lenkrollen stehen über den Rahmen hinaus und vergrößern Breite oder
  Länge. Für Nennmaße das Grundkörpermaß nehmen.
- **Räder** sind eine Heuristik für Gegenstände mit vier Rollen an den Ecken (Rollwagen, Möbel); sie melden
  `plausibel: false`, wenn kein Kreis passt.
- **Zeiten schwanken** mit der Last des Rechners (gleicher Lauf 55–73 s). Object Capture belegt während des Laufs
  rund 300 MB (reduced) bis 1 GB (medium) Zwischenstände; sie werden danach gelöscht.

## Aufnahmetipps für Kevin

1. **Matter Gegenstand, gleichmäßiges Licht**, keine harten Schatten, kein Gegenlicht. Hintergrund ruhig, wenig
   anderes im Bild (im Test landeten Kiste, Schale und Tasche im Netz).
2. **Nicht anfassen und nicht umdrehen** während der Aufnahme. Unterseite braucht ein zweites Video; dann beide
   getrennt rekonstruieren.
3. **Langsam gehen:** zwei Runden, eine auf Hüfthöhe schräg von oben (30–45°), eine tiefer (10–20°), dazu ein paar
   Bilder von fast senkrecht oben. 30–60 s reichen; lieber langsam als lang (Bewegungsunschärfe ist der größte
   Feind, das Programm nimmt je Fenster nur das schärfste Bild).
4. **Gegenstand füllt etwa die Hälfte des Bildes**, immer ganz im Bild, keine Nahaufnahmen mit Schwenk.
5. **Ein Maß nachmessen** (die längste Kante, möglichst groß) und dazu ein zweites als Prüfmaß.
6. Hauptkamera (1×), 4K 30 fps, keine Zoomwechsel während der Aufnahme.

## Einbindung in Kev CAD (Phase 4)

- **MCP `referenz_video(pfad, masz=None, einstellung="schnell", von=None, bis=None)`** (Strang R-K): Der Kernel
  legt `<projekt>/referenzen/<name>/` an (R4) und startet
  `kevcad-capture lauf <pfad> --aus <ordner> --bilder 60 --kante 1920 --detail reduced [--masz …]` als
  Unterprozess („genau“: `--bilder 120 --kante 2880 --detail medium`). Er liest stdout zeilenweise.
- **Fortschritt:** `progress` mit `phase`/`fraction` und `stage` geht als `STATUS busy` mit Text in die
  Statusleiste der App („Rekonstruktion: Netz wird erzeugt, 63 %“). Grobe Gewichtung für einen Gesamtbalken:
  Bilder 5 %, Rekonstruktion 93 %, Nachbearbeitung 2 %.
- **Anzeige:** Bei `file` mit `kind: mesh_mm` schickt der Kernel `REF_UPSERT` mit `netz_mm.obj` (mm, Z oben, wie
  das Modell), halbtransparent auf der Referenz-Ebene; `punktwolke_mm.ply` als zweite Referenz; Kameras aus
  `poses.json` → `aligned` für den Fotomodus (`REF_PHOTO`: Bildpfad, `camera_to_world`, `K`).
- **Maßstab nachträglich:** `referenz_massstab(punkt_a, punkt_b, mm)` skaliert im Kernel direkt (Faktor =
  mm / Abstand); alternativ `kevcad-capture nachbearbeitung <ordner> --masz …` (rund 1 s), das auch Bericht und
  `poses.json` neu schreibt.
- **Bericht:** `done.summary` (= `bericht.json`) gibt der Kernel dem Agenten als Antwort von `referenz_video`
  zurück; Kontrollbilder (`--kontrollbilder`) kann der Agent direkt ansehen.
- **Installation (offen):** `build.sh` bzw. `tools/auto-update.sh` bauen das Programm noch nicht. Vorschlag:
  `swift build -c release --package-path tools/capture` und Programm plus `scripts/` nach
  `~/Library/Application Support/de.upvis.kevcad/install/bin/` kopieren; das Programm sucht seine Skripte neben
  sich, in `scripts/` darüber oder unter `$KEVCAD_CAPTURE_SCRIPTS`.
