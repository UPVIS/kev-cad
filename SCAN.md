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
