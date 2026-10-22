# Kev CAD · Scan-Format und Übertragung (Vertrag, Version 1)

Stand: 22.10.2026 (Kevins Wunsch: eigene iPhone-App für LiDAR plus hochaufgelöste Fotos, Tiefe mit Prompt Depth
Anything, als Grundlage für CAD-Modelle). Zwei Seiten:

- **iPhone-App „Kev Scan“** (`ios/KevScan/`, Bundle-ID `de.upvis.kevscan`): nimmt auf und schickt den Scan an den Mac.
- **Mac-Seite** (`scan/` als eigene uv-Umgebung und `kernel/src/kevcad_kernel/scan/`): nimmt an, rechnet die Tiefe mit
  PromptDA, verschmilzt sie zu einem Netz und legt das Ergebnis als Referenz in Kev CAD an (Phase 4, `referenzen/`).

Änderungen an diesem Vertrag nur additiv (neue Felder und Dateien). Eine Seite ignoriert, was sie nicht kennt.

## Ordner eines Scans

Ein Scan ist ein Ordner `<name>.kevscan/`, unterwegs gepackt als `<name>.kevscan.zip` (ohne Kompression der Bilder
nötig, ZIP mit Deflate genügt). Der Kern ist mit Stray Scanner verträglich, damit die Skripte von PromptDA
(`promptda.scripts.infer_stray_scan`) ihn ohne Umbau lesen:

| Datei | Inhalt |
|---|---|
| `meta.json` | Kopf, siehe unten |
| `rgb.mp4` | Video der Kamerabilder (`ARFrame.capturedImage`), H.264 oder HEVC, 1920 × 1440 (Querformat wie der Sensor), Bild k gehört zu Zeile k der `odometry.csv` |
| `depth/000000.png` … | LiDAR-Tiefe (`ARFrame.sceneDepth`, nicht `smoothedSceneDepth`) je Videobild, 256 × 192, 16 bit, Millimeter, 0 = keine Messung |
| `confidence/000000.png` … | Konfidenz dazu, 8 bit, Werte 0, 1, 2 (`ARConfidenceLevel`) |
| `odometry.csv` | Kopfzeile `timestamp, frame, x, y, z, qx, qy, qz, qw`; je Videobild die Lage der Kamera in der Welt (Kamera → Welt) |
| `camera_matrix.csv` | 3 × 3 Kameramatrix (Komma-getrennt, drei Zeilen) für die Auflösung von `rgb.mp4` |
| `fotos/000.jpg` … | Hochaufgelöste Einzelfotos (`ARSession.captureHighResolutionFrame`), JPEG Qualität 0,95, volle Sensorauflösung des Formats |
| `fotos/000_depth.png`, `fotos/000_confidence.png` | LiDAR-Tiefe und Konfidenz des Fotos (wie oben, 256 × 192) |
| `fotos.json` | je Foto Kameramatrix für die Fotoauflösung, Lage, Zeit, Belichtung (siehe unten) |
| `objekt.json` | optional: Box um das Objekt und Bodenebene, in der App gesetzt |
| `vorschau.jpg` | optional: ein Bild für Listen (etwa 512 px) |

Bildfrequenz von Video, Tiefe und Lage: 10 Hz (jedes sechste ARFrame); die App darf mehr nehmen, `meta.json` nennt es.

### Koordinaten

- Welt wie ARKit: rechtshändig, y oben, Meter, Ursprung am Start der Sitzung.
- Kamera wie ARKit: x rechts, y oben, −z in Blickrichtung, bezogen auf das Bild im Querformat des Sensors
  (`capturedImage` ohne Drehung). Die Kameramatrix gilt für genau dieses Bild (fx, fy, cx, cy in Pixeln).
- Lage als Translation in Metern und Quaternion (x, y, z, w) der Drehung Kamera → Welt (`ARFrame.camera.transform`).
- Umrechnung nach Kev CAD (z oben, Millimeter, Boden bei z = 0) macht die Mac-Seite.

### meta.json

```json
{"format": "kevscan", "version": 1, "name": "Scarlett 2i2", "erstellt": "2026-10-22T21:10:00+02:00",
 "geraet": "iPhone16,2", "ios": "26.1", "app": "1.0 (1)", "hz": 10,
 "video": {"breite": 1920, "hoehe": 1440, "bilder": 412, "codec": "hevc"},
 "tiefe": {"breite": 256, "hoehe": 192, "einheit": "mm", "quelle": "sceneDepth"},
 "fotos": {"anzahl": 24, "breite": 4032, "hoehe": 3024},
 "notiz": "", "objekt": true}
```

### fotos.json

```json
{"fotos": [{"datei": "000.jpg", "zeit": 12.345, "breite": 4032, "hoehe": 3024,
            "k": [[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
            "lage": {"t": [x, y, z], "q": [qx, qy, qz, qw]},
            "tiefe": "000_depth.png", "konfidenz": "000_confidence.png",
            "belichtung_s": 0.008, "iso": 125, "tracking": "normal"}]}
```

### objekt.json

```json
{"box": {"mitte": [x, y, z], "groesse": [b, h, t], "drehung_y_grad": 0},
 "boden": {"punkt": [x, y, z], "normale": [0, 1, 0]}}
```

Box in Weltkoordinaten (Meter, achsparallel bis auf die Drehung um y). Ohne `objekt.json` schätzt die Mac-Seite
Objekt und Boden selbst (Ebene am Boden, größte Gruppe darüber).

### Ergänzungen der App (22.10.2026, additiv)

So schreibt Kev Scan 1.0 die Dateien; alles hier ist Präzisierung oder Zusatz, nichts davon ist für den Empfänger Pflicht.

- **ZIP:** oberste Ebene im ZIP ist der Ordner `<name>.kevscan/` (gepackt mit `NSFileCoordinator`, Deflate). Der
  Empfänger nimmt am besten beides an, mit und ohne diesen Ordner.
- **Zeitbezug:** `timestamp` in `odometry.csv` und `zeit` in `fotos.json` sind Sekunden seit dem ersten Videobild
  (Bild 0 hat 0,0), dieselbe Uhr wie `ARFrame.timestamp`. `meta.json` nennt das als `"zeit_bezug": "erstes_videobild"`.
  Die Zeitstempel im Video (`rgb.mp4`) sind dieselben Werte; die Bildfolge ist also nicht streng gleichmäßig.
- **Bildauswahl:** ein Videobild wird genommen, wenn seit dem letzten mindestens 0,095 s vergangen sind und es eine
  `sceneDepth` hat; nur dann entstehen Videobild, Tiefe, Konfidenz und Zeile in `odometry.csv` (gleiche Nummer k).
- **`odometry.csv`:** Quaternion normiert, `qw >= 0`; Zahlen mit sechs Nachkommastellen, getrennt durch Komma und
  Leerzeichen (wie Stray Scanner).
- **`camera_matrix.csv`:** Kameramatrix des ersten Videobilds, `fx,0,cx` / `0,fy,cy` / `0,0,1`, ohne Leerzeichen.
  ARKit nutzt Autofokus, die Brennweite schwankt dadurch leicht; je Foto steht die eigene Matrix in `fotos.json`.
- **`rgb.mp4`:** HEVC (Rückfall H.264), Bitrate etwa 16 Mbit/s, ein Schlüsselbild je zehn Bilder, ohne Drehung.
- **`meta.json`, zusätzliche Felder:**
  `id` (UUID des Scans, bleibt beim Umbenennen gleich), `dauer_s` (Zeit des letzten Videobilds), `zeit_bezug`,
  `videoformat` (`breite`, `hoehe`, `fps`, `kamera` als AVCaptureDevice-Typ, `hochaufloesend_empfohlen`) und
  `auto_foto` (`aktiv`, `winkel_grad`, `abstand_m`). `video.codec` ist `hevc` oder `h264`. `fotos.breite/hoehe` sind die
  des ersten Fotos (0 ohne Fotos). Die App schreibt `meta.json` als letzte Datei; ein Ordner ohne `meta.json` ist eine
  abgebrochene Aufnahme.
- **`fotos.json`, zusätzliche Felder je Foto:** `tiefe_quelle` = `"foto"` (Tiefe gehört zum hochaufgelösten Bild
  selbst) oder `"videobild"` (das Foto kam ohne `sceneDepth`, genommen ist die Tiefe des letzten Videobilds, Lage dann
  leicht verschieden); `ausloeser` = `"hand"` oder `"auto"`. `tracking` ist `normal`, `nicht_verfuegbar` oder
  `eingeschraenkt_start|_bewegung|_merkmale|_neuortung`. `belichtung_s` und `iso` stammen aus den EXIF-Daten des Bilds
  (`ARFrame.exifData`), ohne EXIF aus `ARCamera.exposureDuration`; fehlen beide, fehlt das Feld. `tiefe` und
  `konfidenz` fehlen, wenn es gar keine Tiefe gab. Die Kameramatrix `k` ist auf die tatsächliche Pixelgröße des Fotos
  umgerechnet.
- **Automatische Fotos:** während der Aufnahme, sobald sich das iPhone seit dem letzten Foto um `winkel_grad` gedreht
  (Vorgabe 15°) oder um `abstand_m` bewegt hat (Vorgabe 0,25 m), höchstens eins je 0,8 s und nur bei Tracking `normal`.
  Das erste Foto entsteht gleich zu Beginn.
- **`objekt.json`:** `groesse` = [Breite entlang der gedrehten x-Achse, Höhe entlang y, Tiefe entlang der gedrehten
  z-Achse]; `drehung_y_grad` dreht um +y (rechtshändig, von oben gesehen gegen den Uhrzeigersinn). Die Grundfläche der
  Box liegt auf `boden.punkt`, `mitte` ist eine halbe Höhe darüber. `boden.normale` ist die Normale der getroffenen
  ARKit-Ebene (horizontal, also nahe [0, 1, 0]).
- **`vorschau.jpg`:** anders als alle anderen Bilder aufrecht (Hochformat, um 90° gedreht), 512 px lange Seite, aus
  dem Videobild bei etwa 0,5 s. Nur zur Anzeige.
- **Auf dem iPhone:** Scans liegen in den Dokumenten der App (in der Dateien-App unter „Auf meinem iPhone > Kev Scan“
  sichtbar, auch im Finder per Kabel). Der Sendestatus steht nur in der App, nicht im Scan.

## Übertragung iPhone → Mac

- Der Kernel von Kev CAD bietet, solange die App läuft, einen Empfänger an: HTTP auf einem freien Port, angemeldet per
  Bonjour als `_kevscan._tcp` (Name: Rechnername), TXT `version=1`.
- `GET /` → `{"dienst": "kevscan", "version": 1, "rechner": "…", "projekt": "<offenes Projekt oder null>"}`.
- `POST /scan` mit dem ZIP als Körper, Kopfzeilen `X-KevScan-Name` (Name, URL-kodiert) und `Content-Length`;
  Antwort `{"ok": true, "id": "<ordnername>", "ordner": "…"}` oder `{"ok": false, "fehler": "…"}`.
- Empfangene Scans landen unter `~/Documents/Kev CAD/Scans/<datum>_<name>/` (entpackt, ZIP-Pfade geprüft, höchstens
  4 GB). Importiert wird nicht automatisch ins Projekt, sondern auf Anfrage (MCP `scan_importieren`, oder „Scan
  übernehmen“ in der App, wenn es sie gibt). Kev CAD zeigt eine Mitteilung „Scan empfangen“.
- Rückfall ohne WLAN: Die App teilt das ZIP über das Teilen-Menü (AirDrop); `scan_importieren(pfad)` nimmt dann den
  Pfad (etwa im Ordner Downloads).

## Auswertung auf dem Mac (Überblick)

1. Bilder auswählen: alle Fotos, dazu Videobilder nach Abstand und Blickwinkel (Schärfe als Filter).
2. PromptDA (Modell Large, Rückfall Small) je ausgewähltem Bild: Tiefe in Bildauflösung, metrisch.
3. Verschmelzen mit den ARKit-Lagen (TSDF), Beschnitt auf Box bzw. über dem Boden, Netz und Punktwolke.
4. Umrechnen in Kev-CAD-Koordinaten und als Referenz anlegen: Netz, Kameras (bekannt aus ARKit) und Tiefenbilder für
   fotomess, das damit die Maße des Modells einpasst (Tiefe als zusätzliche Bedingung).

## App bauen und installieren

Quellen in `ios/KevScan/` (XcodeGen `project.yml`, SwiftUI, ARKit, RealityKit, iOS 18 oder neuer, nur iPhone,
Hochformat). Gebaut wird nur für das Gerät; ein Simulator-Build ist für ARKit wertlos.

```bash
tools/kevscan.sh bauen          # Release für iOS, signiert (Team 2GX7UC98J6), Ergebnis build/KevScan.app
tools/kevscan.sh installieren   # per devicectl auf das iPhone (entsperrt, gleiches WLAN oder Kabel)
tools/kevscan.sh alles          # beides
tools/kevscan.sh starten        # App auf dem iPhone starten
tools/kevscan.sh geraet         # geraet.json der App holen: Videoformate laut ARKit, gemessene Fotogröße
```

Das Skript baut unter der mit VoiceBridge gemeinsamen Sperre `/tmp/vb-xcodebuild.lock`, wartet auf 25 % freien
Speicher und löscht die DerivedData in `/tmp/kevscan-build` nach dem Bau.
