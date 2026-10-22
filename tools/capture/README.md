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
swift test --package-path tools/capture                 # Auswahl, Schärfe, RANSAC, Rechteck, Kreis, Schicht, Auflage
```

macOS 15 oder neuer, Apple Silicon. Brennweiten je Kamera (`Pose.intrinsics`) und Verzeichnung gibt die API erst ab
macOS 26 her; auf macOS 15 fehlen in `poses.json` dann `K` und `lens_distortion`.

## Aufruf

```bash
# alles in einem Lauf; Standard = Empfehlung „schnell“ (60 Bilder, 1920 px, reduced)
kevcad-capture lauf IMG_5182.MOV --aus ~/Projekte/x/referenzen/rollwagen --von 12.4 \
    --masz laenge=610 --pruef grund_breite=410 --pruef rad=100 \
    --kontrollbilder build/capture/kontrolle

# „genau“
kevcad-capture lauf IMG_5182.MOV --aus <ordner> --bilder 120 --kante 2880 --detail medium --masz laenge=610

# Teilschritte
kevcad-capture bilder IMG_5182.MOV --aus <ordner> --bilder 120 --kante 2880
kevcad-capture rekonstruktion <ordner> --detail medium
kevcad-capture nachbearbeitung <ordner> --masz grund_breite=410     # ~1 s, z. B. nach neuem Maß
```

| Option | Wirkung |
|---|---|
| `--bilder N` | Anzahl Bilder (Standard 60). Das Video wird in N gleich lange Fenster geteilt, je Fenster gewinnt das schärfste Bild |
| `--kante PX` | lange Kante der Bilder (Standard 1920, `0` = Original 3840). Der Decoder skaliert selbst, die Schärfe wird in Zielgröße gemessen |
| `--von S`, `--bis S` | nur diesen Abschnitt des Videos (Sekunden), z. B. ohne das Umdrehen am Anfang |
| `--brennweite35 MM` | 35-mm-Brennweite in die EXIF-Daten (nur wenn sicher bekannt; Object Capture schätzt sie sonst selbst) |
| `--detail D` | `preview`, `reduced` (Standard), `medium`, `full`, `raw` |
| `--ohne-maske` | `isObjectMaskingEnabled = false` |
| `--hohe-empfindlichkeit` | `featureSensitivity = .high` (texturarme Gegenstände, langsamer) |
| `--ungeordnet` | `sampleOrdering = .unordered` statt `.sequential` (lose Fotos statt Video) |
| `--posen-zuerst` | Posen in eigener erster Anfrage: `poses.json` nach rund der Hälfte der Zeit, der Lauf dauert dafür ~40 % länger |
| `--roh-usdz` | zusätzlich `roh/modell.usdz` von Object Capture (ohne Maßstab; kostet 5 s bei reduced, 17 s bei medium) |
| `--ohne-usdz` | kein `netz_mm.usdz` (sonst schreibt die Nachbearbeitung es selbst: eigenes USDA mit Farbtextur, `metersPerUnit = 0.001`, `upAxis = Z`, mit `usdcat`/`usdzip` gepackt, `usdchecker` ohne Befund) |
| `--masz NAME=MM` | bekanntes Maß, setzt den Maßstab: `laenge` (längste waagrechte Ausdehnung), `breite`, `hoehe`, `grund_laenge`, `grund_breite` |
| `--pruef NAME=MM` | Prüfmaß, wird mit Abweichung in mm und % berichtet (Namen wie `--masz`, dazu `rad`) |
| `--ohne-boden-schnitt` | Boden finden und ausrichten, aber nicht abschneiden |
| `--auflage` | Gegenstand liegt auf einer Unterlage, die mit im Netz ist (Holzscheibe, Tisch, Kiste): oberste große waagrechte Ebene unter ihm wird Auflage (z = 0), alles darunter fällt weg, Höhen zählen ab dort. Bericht unter `auflage`; mit `KEVCAD_CAPTURE_DEBUG=1` stehen die geprüften Ebenen im Protokoll |
| `--kontrollbilder ORDNER` | Kontrollbilder mit Blender (`/Applications/Blender.app` oder `$KEVCAD_BLENDER`) |
| `--kopie ORDNER` | `poses.json` mit Bildern sofort nach der Ausrichtung, alle Ergebnisse am Ende zusätzlich dorthin |
| `--behalte-checkpoint` | Zwischenstände von Object Capture behalten (sonst gelöscht, ~300 MB je Lauf) |
| `--leise` | keine Hinweise auf stderr |

Maße im Bericht:

- **Hüllmaß** L × B × H: alle Punkte des Objekts, robust (0,1–99,9 %); waagrecht ohne den Bodenrand (unterste 6 %
  der Höhe), an dem sonst Bodenreste hängen. Enthält abstehende Teile (ausgeschwenkte Lenkrollen).
- **Grundkörper** L × B: die dichteste waagrechte Schicht (beim Rollwagen der Rahmen), 0,5–99,5 % der Punkte
  dieser Schicht über dem Bodenrand. Seine Achsen und seine Mitte legen das Koordinatensystem fest (lange Seite = X).
- **Gesamthöhe** H (höchster Punkt über dem Boden, 99,9 %) und **obere Fläche** (stärkste waagrechte Ebene im
  oberen Viertel). Liegt der Gegenstand kopfüber (Räder oben erkannt), gilt H gespiegelt für den aufrechten Stand;
  die obere Fläche zeigt dann zum Boden, ist unsichtbar und wird nicht angegeben.
- **Räder**: je Ecke Kreisausgleich (RANSAC + Kåsa) auf dem Umriss in der senkrechten Radebene, Mittelwert und Streuung.

## Ausgabe

```
<aus>/bilder/bild_0001.jpg …     ausgewählte Bilder (bleiben, alles andere Zwischenmaterial wird gelöscht)
<aus>/bilder.json                Auswahl: Videobild, Zeit, Schärfe, Fenster-Median
<aus>/poses.json                 Kameras je Bild, roh und ausgerichtet (siehe unten)
<aus>/roh/obj/ roh/punktwolke.ply roh/posen_roh.json roh/rekonstruktion.json   Object Capture, ohne Maßstab, Y oben
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

## Messung am Rollwagen (21.10.2026)

Testvideo `IMG_5182.MOV`: iPhone 15 Pro Max, 4K Hochformat, 30 fps, 36 s, blauer Kunststoff-Rollwagen ALUTEC 05200
(Außenmaß 610 × 410 mm, vier Lenkrollen Ø 100 mm) auf Fliesen, Umgebung im Bild. Kevin dreht den Wagen nach 10 s
um; ab 12,4 s liegt er kopfüber (Räder oben). Mac M2 Pro, 16 GB, macOS 26.6. Maßstab immer `--masz laenge=610`.

### Zeiten

| Einstellung | Abschnitt | Bilder (ausgerichtet) | Auswahl | Object Capture | Nachbearb. | gesamt | Dreiecke Objekt | Zwischenstände |
|---|---|---|---|---|---|---|---|---|
| **schnell**: 60 × 1920 px, reduced | kopfüber 12,4–36,1 s | 60 (57) | 2,7 s | 57,5 s | 0,5 s | **64 s** | 11 751 | 286 MB |
| **genau**: 120 × 2880 px, medium | kopfüber 12,4–36,1 s | 120 (112) | 4,8 s | 198,9 s² | 1,2 s | **209 s** | 21 398 | 933 MB |
| genau, Wiederholung unter Last³ | kopfüber 12,4–36,1 s | 120 (112) | 4,6 s | 234,8 s | 1,3 s | 245 s | 20 735 | 764 MB |
| schnell | aufrecht 0–10,3 s | 60 (59) | 1,3 s | 28,5 s | 0,3 s | 33 s | 9 844 | 142 MB |
| schnell | ganzes Video | 60 (56) | 6,4 s | 54,5–72,9 s | 0,5 s | 61–80 s | 7 687 | 271 MB |

² davon 17 s für die zusätzliche USDZ von Object Capture, die inzwischen abgeschaltet ist (ohne also rund 190 s).
³ Rechner parallel mit anderen Agenten ausgelastet (Last 17); zeigt die Streuung von Zeit und Ergebnis.

Der Lauf „schnell“ kopfüber enthielt noch rund 5 s für diese USDZ. Hinzu kommen 2–3 s für die Kontrollbilder
(Blender). Von der Object-Capture-Zeit entfallen bei „schnell“ etwa 35 % auf die Netzerzeugung, je 17 % auf
Punktwolke, Texturen und Optimierung, 10 % auf die Bildausrichtung. Die Posen kommen mit dem Netz kurz vor Schluss
(`--posen-zuerst`: nach 27 statt 49 s, gesamt dafür 75 statt 55 s).

### Maße (mm)

| | schnell kopfüber | genau kopfüber (1. / 2. Lauf) | schnell aufrecht | schnell ganzes Video |
|---|---|---|---|---|
| Hüllmaß L × B × H | 610 × 456,3 × 160,5 | 610 × 456,7 × 161,6 / 610 × 458,8 × 161,3 | 610 × 422,1 × 156,4 | 610 × 455,0 × 170,4 |
| Grundkörper (Rahmen) L × B | 609,4 × 423,3 | 608,7 × 422,8 / 608,6 × 430,8 | 598,0 × 410,0 | 609,4 × 432,2 |
| **Prüfmaß Rahmenbreite** (soll 410) | 423,3 (+3,3 %) | 422,8 (+3,1 %) / 430,8 (+5,1 %) | 410,0 (±0) bzw. 418,2 (+2,0 %)¹ | 432,2 (+5,4 %) |
| Raddurchmesser (soll 100), Mittel ± halbe Spanne | 97,3 ± 6,9 | 97,1 ± 2,5 / 99,2 ± 2,2 | – (unter dem Rahmen verdeckt) | 95,2 ± 9,1 |
| Gesamthöhe im aufrechten Stand (Stapelrand oben) | 160,5 | 161,6 / 161,3 | 156,4 bzw. 159,5¹ | (170,4, unbrauchbar) |
| Obere Rahmenfläche über Boden | – (zeigt zum Boden) | – | 132,6 bzw. 135,3¹ | – |

¹ Im aufrechten Abschnitt ist das Hüllmaß durch einen „Vorhang“ unter dem Rahmen 2 % länger als der Rahmen selbst;
mit `--masz grund_laenge=610` skaliert gelten die zweiten Werte.

Lesart:

- **Länge/Breite-Verhältnis:** Die kopfüber-Läufe messen den Rahmen 3–5 % zu breit gegenüber der Länge („genau“
  nicht besser als „schnell“), der aufrechte 0–2 %. Teils ist das Bodenrest an einer Längsseite (dunkle Schürze in
  der Draufsicht), teils eine leichte Verzerrung der Rekonstruktion. Mit einem Maß lässt
  sich nur ein gleichmäßiger Maßstab setzen; für Abweichungen um 1 % braucht es zwei Maße (offen).
- **Hüllbreite 456 statt 410:** zwei ausgeschwenkte Lenkrollen stehen über eine Längsseite hinaus (sichtbar in der
  Draufsicht). Für Nennmaße das Grundkörpermaß nehmen.
- **Räder:** 97–99 mm statt 100 (−1 bis −3 %), bei „genau“ deutlich gleichmäßiger (Spanne 4–5 statt 14 mm).
- **Streuung:** Derselbe Lauf „genau“ zweimal gerechnet ergab 422,8 und 430,8 mm Rahmenbreite; Object Capture ist
  nicht deterministisch, die Hauptmaße streuen um 1–2 %.
- **Ganzes Video:** wegen des Umdrehens unbrauchbar (Mischung aus zwei Lagen, Boden und Umgebung im Netz).

### Empfehlung

**„schnell“ (60 Bilder, 1920 px, reduced) als Standard:** rund eine Minute, Hauptmaße so gut wie „genau“ (beide
+3 bis +5 % in der Breite bei Maßstab über die Länge, Höhe und Räder auf 1–3 %). **„genau“ (120 Bilder, 2880 px,
medium)** nur, wenn Details zählen (Radform, Rippen, kleine Bohrungen): gut dreimal so lang, doppelte Dreieckszahl,
gleichmäßigere Räder. Größter Hebel für bessere Maße ist nicht die
Einstellung, sondern die Aufnahme (siehe Tipps): ruhiger Hintergrund, Gegenstand nicht bewegen, ein zweites Maß.

Kontrollbilder der Läufe: `build/capture/kontrolle/<lauf>_{vorne,seite,oben,schraeg}.png` (nicht im Git).
Ergebnisse für den Vergleich durch andere Agenten: `~/Library/Caches/de.upvis.kevcad.testdaten/rollwagen/`
(Lauf „genau“, kopfüber; `poses.json` mit Bildpfaden dorthin).

## Messung an der Scarlett 2i2 (22.10.2026)

Testvideo `IMG_5186.MOV`: iPhone 15 Pro Max, 4K quer, 30 fps, 39,7 s. Focusrite Scarlett 2i2 (4. Gen.), rotes mattes
Aluminium, schwarze Blenden, liegt auf einer Holzscheibe auf Fliesen und wird nicht bewegt (die Kamera geht herum,
21 bis 28 s Nahaufnahmen der Vorderseite). Hersteller 180 × 117 × 47,5 mm. Aufruf jeweils
`--auflage --masz laenge=180 --pruef breite=117 --pruef hoehe=47.5`. Vergleich mit fotomess in
[fotomess/BENCHMARK.md](../../fotomess/BENCHMARK.md), Abschnitt „Scarlett 2i2“.

| Lauf | Bilder (ausgerichtet) | Object Capture | gesamt | Hülle L × B × H | obere Fläche über Auflage | Deckelschicht L × B (ohne Knöpfe) |
|---|---|---|---|---|---|---|
| schnell, ganzes Video | 60 (42) | 40 s | 45 s | 180 × 117,3 × 48,4 | 47,5 | 174,0 × 102,1 |
| genau (120 × 2880, medium) | 120 (109) | 375 s¹ | 394 s¹ | 180 × 118,3 × 49,2 | 46,7 | 174,7 × 102,6 |
| schnell, 0–21 s | 60 (60) | 332 s¹ | 338 s¹ | 180 × 116,5 × 47,9 | 46,9 | 174,2 × 101,9 |
| schnell, 21–39,7 s | 60 (60) | 234 s¹ | 239 s¹ | 180 × 116,7 × 48,7 | 47,0 | 174,2 × 102,5 |

¹ Speicher während dieser Läufe durch andere Agenten auf 13 bis 24 % frei gedrückt, 5- bis 8-mal langsamer als
sonst; nicht vergleichbar.

Lesart:

- **Ohne `--auflage` unbrauchbar:** Die Objektmaskierung nimmt die Holzscheibe mit und entfernt den Boden; der
  Maßstab kam dann aus der Scheibe (Hülle 180 × 149 × 58). Mit `--auflage` ist das Gerät sauber freigestellt.
- **Prüfmaße:** Tiefe mit Knöpfen 116,5 bis 118,3 (Soll 117: −0,4 bis +1,1 %), Höhe Auflage bis Deckel 46,7 bis
  47,5 (Soll 47,5: −1,7 bis 0 %; das robuste Hüllmaß 47,9 bis 49,2 nimmt Unebenheiten am Deckel mit). Die
  Deckelschicht (dichteste Schicht oben, dort gibt es keine Knöpfe) misst das Gehäuse ohne Knöpfe: 101,9 bis
  102,6 mm, die Knöpfe stehen also 14 bis 16 mm vor. Die Länge der Deckelschicht (174) ist um die gerundeten
  Längskanten kürzer als die Breite.
- **Ausrichtung:** Im ganzen Video fallen 18 von 60 Bildern heraus (Rückseite und flache Ansichten bei 5,7 bis
  20,9 s, viel Bewegungsunschärfe); getrennt gerechnet richtet Object Capture alle 60 Bilder jedes Abschnitts aus.
  Die Maße sind trotzdem gleich gut.
- **Brennweite:** 3202 bis 3260 px auf 3840 px (Metadaten 2796 px, wie am Rollwagen 12 bis 13 % zu kurz).
- **Erste Fassung der Auflagesuche:** Sie nahm die oberste gültige Ebene und verlangte die Ebene unter dem Blickpunkt
  der Kameras. In den Abschnitten gewann dann eine kleine schräge Scheinebene durch Netzreste (12° gekippt, 452
  Punkte) bzw. die Scheibe fiel heraus, weil der Blickpunkt bei Draufsichten und Nahaufnahmen unter ihr lag.
  Jetzt zählen nur Ebenen mit mindestens 30 % des größten Randes außerhalb des Gegenstands, und der Blickpunkt wird
  nur waagrecht geprüft (über dem, was auf der Ebene steht).
- **Schnitthöhe:** Die Toleranz kommt weiter aus der Größe des ganzen Netzes (mit Scheibe), geschnitten wird 2,6 bis
  5,7 mm über der Auflage. Die Maße stört das nicht (Höhen zählen ab der Ebene, waagrechte Maße erst über dem
  Bodenrand), das Netz verliert aber den untersten Streifen. Eine Toleranz aus der Streuung der Auflagepunkte wäre
  der nächste Schritt.
- Die Rad-Heuristik meldet bei Gegenständen ohne Räder Unsinnskreise mit `plausibel: false` und `gefunden: false`.

Kontrollbilder: `build/capture/kontrolle/scarlett_{ganz,genau,umlauf,nah}_{vorne,seite,oben,schraeg}.png`
(nicht im Git). Netze und Bilder der Läufe sind wegen der vollen Systemplatte gelöscht, Berichte und `poses.json`
liegen unter `build/capture/scarlett_*/`.

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
- **Verdeckte Bereiche** schließt Object Capture mit glatten „Vorhängen“: Beim aufrechten Wagen ist der Raum
  unter dem Rahmen bis zu den Rädern zugezogen, die Räder sind dort nicht messbar. Umgekehrt entfernt die
  Maskierung manchmal den Boden ganz; dann nimmt die Nachbearbeitung die untersten Punkte als Auflage und richtet
  nach der stärksten waagrechten Ebene aus (Hinweis im Bericht unter `boden`).
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
