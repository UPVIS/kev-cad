# Kev CAD · Phase 4: Foto und Video als Referenz

Stand: 21.10.2026. Läuft parallel zu Phase 3, sobald Phase 2 auf `main` ist. Baut auf dem Verfahren „CAD aus Fotos“
(Repo UPVIS/cad-aus-fotos, Paket `fotocad`) und der Recherche vom 21.10.2026 auf (Abschnitt „Fundstücke“).

## Ziel

Kevin filmt ein Produkt selbst (iPhone, einmal rundherum) oder hat Fotos davon. Kev CAD macht daraus eine **Referenz
im Viewer**, gegen die Claude das parametrische Modell baut und prüft:

- **Video →** Einzelbilder → **Apple Object Capture** auf dem Mac → Referenznetz mit Kamerapositionen und Punktwolke,
  halbtransparent im Viewer. Maßstab über ein gemessenes Maß („diese Kante ist 600 mm“).
- **Fotos →** Foto als Hintergrund hinter dem Modell, gesehen durch die eingepasste Kamera, mit Deckkraft-Regler und
  rot/blauer Differenz (rot nur Foto, blau nur Modell) – live beim Modellieren.
- **Messen und Prüfen an der Referenz:** Punkte und Abstände auf dem Netz, Ebenen und Zylinder finden, Abweichung
  Modell ↔ Referenz als Zahl und als Farbkarte.
- **Inhalt des Videos:** Auf Wunsch beschreibt Gemini das Video (Bauteile, Materialien, sichtbare Maße, Beschriftungen)
  als Ausgangspunkt für Claudes erstes `model.py` – über den bezahlten Gemini-Zugang, Kosten werden ausgewiesen.

**Fertig, wenn:**

1. Kevin legt ein Handyvideo (30–90 s, matter Gegenstand) ins Projekt; nach wenigen Minuten steht die Referenz im
   Viewer, Kevin setzt den Maßstab mit einem bekannten Maß.
2. Claude baut das Modell in build123d, `referenz_abweichung` meldet die mittlere und größte Abweichung je Teil und
   färbt die Referenz danach ein.
3. Mit Studiofotos eines Produkts (Beelonia-Küche) passt Kev CAD die Kameras ein (Verfahren aus `fotocad`) und zeigt
   jedes Foto mit Live-Differenz hinter dem Modell.

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| R1 | **Apple Object Capture** (`PhotogrammetrySession`) als Rekonstruktion, in einem kleinen Swift-Hilfsprogramm `kevcad-capture` im Repo | Läuft nativ auf Apple Silicon, ohne CUDA und ohne Lizenzfragen; liefert Netz, Posen und Punktwolke |
| R2 | **Einzelbilder mit ffmpeg**, nur scharfe (Laplace-Varianz), 2–4 Bilder je Sekunde, Ziel 60–150 Bilder | Object Capture braucht viel Überlappung; unscharfe Bilder verschlechtern das Netz |
| R3 | **Maßstab immer aus einem echten Maß**, nicht aus einem Modell | Ohne LiDAR ist die Rekonstruktion maßstabslos; Tiefenschätzer liegen nur im Prozentbereich |
| R4 | **Referenzen sind eigene Objekte** (`<projekt>/referenzen/`), nicht Teil des Modells und nicht in der Stückliste; im Viewer halbtransparent, eigene Ebene im Teilebaum | Klare Trennung von Vorlage und Konstruktion |
| R5 | **Foto-Einpassung mit `fotocad`** (Silhouetten-Abgleich, Bündelausgleich), als optionale Abhängigkeit des Kernels | Vorhandenes, erprobtes Verfahren (IoU 97,8 % an der Küche) statt Neubau |
| R6 | **Video-Beschreibung über Gemini** (Kevins Regel „Videoinhalte immer über den Google-Stack“), nur auf Wunsch | Kein Raten aus dem Bild; Kosten getrennt ausweisen |
| R7 | **Nicht einbauen:** CAD-Recode, cadrille, CAD-Coder (nichtkommerzielle Lizenzen, nur Einzelteile, CUDA), Hunyuan3D (in der EU nicht lizenziert), SAM 3D / TRELLIS.2 lokal (CUDA bzw. 24 GB+) | Recherche 21.10.2026 |

## Erweiterungen der Verträge (beim Start festschreiben)

- Protokoll: `REF_UPSERT` (Kernel → App: Referenznetz oder Punktwolke mit Lage und Maßstab, Nutzlast wie PART_UPSERT
  ohne Flächenmetadaten), `REF_PHOTO` (Foto mit Kamera: Pfad, Lage, Brennweite), `REF_REMOVE`, `REF_DEVIATION`
  (Abweichung je Punkt als Farbe), App → Kernel `REF_SCALE` (zwei Punkte und ein Maß).
- MCP: `referenz_video(pfad)`, `referenz_fotos(pfade)`, `referenz_massstab(punkt_a, punkt_b, mm)`,
  `referenz_messen(refs)`, `referenz_ebene_finden(bereich)`, `referenz_abweichung(teile=None)`,
  `video_beschreiben(pfad)` (Gemini).
- App: Referenz-Ebene im Teilebaum (sichtbar, Deckkraft), Fotomodus (Foto als Hintergrund durch die Kamera,
  Differenzansicht, Foto wechseln), Werkzeug „Maßstab setzen“ (zwei Punkte klicken, Maß eingeben), Fortschritt der
  Rekonstruktion in der Statusleiste.

## Arbeitspakete (parallel)

| Strang | Inhalt |
|---|---|
| **R-C Rekonstruktion** | `kevcad-capture` (Swift, SwiftPM): Video → Bilder (ffmpeg, Schärfefilter) → PhotogrammetrySession → OBJ/PLY, Posen als JSON, Fortschritt; Tests mit einem kurzen Probevideo |
| **R-K Kernel** | Referenzobjekte, Maßstab, Messen auf Netzen, Ebenen/Zylinder (pyRANSAC-3D, Apache), Abweichung Modell ↔ Referenz, Anbindung `fotocad` für Foto-Kameras, Gemini-Videobeschreibung, MCP-Werkzeuge, Skill |
| **R-A App** | Referenz-Ebene, Fotomodus mit Differenz, Maßstab-Werkzeug, Fortschritt |

### Ergebnis R-C (21.10.2026)

`tools/capture/` (`kevcad-capture`, Details, Zeiten und Maße in [tools/capture/README.md](tools/capture/README.md)).
Entscheidungen beim Bau:

- **AVFoundation statt ffmpeg** (R2 angepasst): Der Hardware-Decoder liefert die Bilder direkt in Zielgröße, die
  Schärfe (Laplace-Varianz, vImage) wird in dieser Größe gemessen; je Zeitfenster gewinnt das schärfste Bild. 1084
  4K-Bilder in 6 s. ffmpeg ist nicht nötig.
- **Posen in zwei Konventionen** (`poses.json`): RealityKit-`camera_to_world` und OpenCV-`R`, `t` mit `K` je Bild
  (ab macOS 26 aus `Pose.intrinsics`), roh und im Kev-CAD-System (mm, Z oben, Boden z = 0). Per Rückprojektion des
  Netzes in die Bilder geprüft.
- **Boden per RANSAC, Objekt am Blickpunkt der Kameras:** Object Capture lässt trotz Maskierung Boden und Umgebung
  im Netz, wenn der Hintergrund unruhig ist; umgekehrt entfernt es den Boden manchmal ganz. Eine waagrechte Ebene
  gilt nur als Boden, wenn fast nichts darunter liegt; sonst Auflage auf den untersten Punkten.
- **Gegenstand nicht bewegen:** Wird er während der Aufnahme umgedreht, rekonstruiert Object Capture die Szene
  (Boden), nicht den Gegenstand; die Bilder vor dem Umdrehen passen nicht zum Netz. Abschnitte mit `--von`/`--bis`
  getrennt rechnen.
- **Standard „schnell“** (60 Bilder, 1920 px, reduced, ~1 min); „genau“ (120, 2880, medium) kostet gut das Dreifache
  und bringt Details, aber keine besseren Hauptmaße.

### Ergebnis „Phase 4 in die App“ (22.10.2026, Zweig `phase4`)

Object Capture und fotomess sind aus Kev CAD heraus nutzbar, für den Agenten über MCP und für Kevin in der App.

- **Kernel** (`kernel/src/kevcad_kernel/referenz/`, Mixin `ReferenzRuntimeMixin`, MCP in
  `mcp_tools/referenz_tools.py`): `referenzen`, `referenz_video`, `referenz_fotos`, `referenz_vermessen`,
  `referenz_fotoansicht`; Ablage in `<projekt>/referenzen/<name>/` (`referenz.json`, `capture/`, `messung/`,
  `fotos/`). Bilder, Masken, Texturen, Rohdaten und Zwischenstände nicht in den Versionen (Ausschluss plus
  Größenregel 20 MB unter `referenzen/`).
- **Zwei eigene Prozesse:** kevcad-capture (Swift) und fotomess (eigene uv-Umgebung). Der Bauer läuft als dritter
  Prozess in der Kernel-Umgebung (`varianten`): model.py mit überschriebenen `param`-Werten, Grundstand und je freiem
  Maß eine Variante, flächenweise. model.py kann `messmodell()` angeben (frei, bekannt, Farbteile je Fläche,
  Zwillingslagen, Maske, Vorgaben, Grenzen).
- **Zusammenspiel:** Liegen Netz und Messung aus demselben Video vor, legt der Kernel das Netz an das Modell an
  (Kamerapaare gleicher Videozeit, dann ICP an der Oberfläche des eingepassten Modells) und erkennt Bilder, in denen
  fotomess die Zwillingslage gewählt hat (Drehung um Z gegen Object Capture); diese rechnet er noch einmal in der
  richtigen Lage. Object Capture rechnet der Kernel bis zu dreimal, wenn die Freistellung misslingt.
- **Protokoll** (additiv): `REF_LIST`, `REF_UPSERT`, `REF_REMOVE`, `REF_PHOTOS`, `REF_RESULT`, `REF_ADD`,
  `REF_MEASURE_REQ`, `REF_APPLY`, dazu `VIEW_CMD referenz_foto` und `SCREENSHOT_REQ` mit `source: "referenz_foto"`.
- **App:** Abschnitt „Referenzen“ im Inspektor, Drag and Drop auf den Viewport bzw. +, Netz halbdurchsichtig mit
  Deckkraft, Fotoansicht (Foto durch die eingepasste Kamera hinter dem Modell, Deckkraft, Differenz rot/blau,
  Überdeckung, live nach jedem Lauf, rund 0,1 s je Foto), Messergebnis mit Sigma neben den Werten aus model.py,
  Hinweise, „Maße übernehmen“ (schreibt die Vorgabewerte der `param`-Aufrufe, nur auf Kevins Klick).
- **Bauen:** `build.sh` baut kevcad-capture und die fotomess-Umgebung; Paket und Installation bringen
  `bin/kevcad-capture` und `fotomess/` mit (Probe-Installation geprüft), `tools/auto-update.sh` baut bei Änderungen
  an beiden neu.

Nachweis an der Scarlett 2i2 (IMG_5186.MOV, Testvariante, alles über MCP; Messmodell `samples/scarlett/model.py`):

| Schritt | Zeit | Ergebnis |
|---|---|---|
| Object Capture „schnell“ (`masz laenge=180`, `auflage`) | 37 s | Hülle 180 × 118,3 × 49,2 mm, Grundkörper 173,4 × 102,5 mm, Deckel 48,0 mm über der Auflage, 41 von 60 Bildern |
| Vermessen, 8 Bilder, zwei Durchgänge (ein Bild lag gedreht) | 57 s | tiefe 104,8 ± 4,2 · hoehe 46,4 ± 1,3 · kanten_r 3,6 ± 3,3 · knopf_h 11,0 ± 3,9 · gross_h 16,4 ± 1,1 mm; Überdeckung 93,5 % |
| Netz angelegt | – | −0,3° um Z, 2,4 mm verschoben, mittlerer Abstand Netz zu Modell 0,5 mm |
| Fotoansicht | 0,1 s je Foto | Foto 1: Überdeckung 91,6 %, Knöpfe und Buchse decken sich |

Gegen den Benchmark (fotomess 8 Bilder: tiefe 105,2 ± 2,0, hoehe 46,9 ± 0,6, Gesamttiefe 120,8) und den Hersteller
(117 mit Knöpfen, 47,5): Gesamttiefe 121,4 mm (+3,8 %), Höhe mit Füßen 48,0 mm (+1,0 %), Rohrtiefe 104,8 mm (Object
Capture 102,5). Object Capture war in zwei von vier gleichen Läufen unbrauchbar (Splitter, falsche Auflage); die
Wiederholung fängt das ab.

Offen: Zwillingslage in Bildern ohne Object-Capture-Kamera (dort 14,8 s gedreht, der Kernel nennt sie),
`REF_DEVIATION`/`referenz_abweichung` und `referenz_massstab`, Punktwolke, Gemini-Videobeschreibung, Fotos ohne
Video als Quelle von Startkameras, Versionstitel für geänderte Referenzdateien („Code in bericht.json“).

## Was Kevin beitragen muss

- **Ein Probevideo:** ein matter Gegenstand (Holzkiste, Werkzeug, Kunststoffgehäuse), langsam einmal rundherum und
  einmal von schräg oben, gleichmäßiges Licht, 30–90 s. Dazu ein Maß, das er nachgemessen hat.
- Optional ein zweites Video eines Edelstahlteils, um zu sehen, wie weit Object Capture bei spiegelnden Flächen kommt.

## Fundstücke (Recherche 21.10.2026)

- Object Capture: nativ auf dem Mac, Netz + Posen (`.poses`) + Punktwolke (`.pointCloud`); 20–200 Bilder mit ~70 %
  Überlappung; spiegelnde Flächen schließt Apple selbst aus; echter Maßstab nur mit Tiefendaten/LiDAR.
- Kamera-Startwerte aus wenigen Fotos: VGGT (nur `VGGT-1B-Commercial` kommerziell, Antrag), Mac-Port vggt-mps; Ersatz
  MapAnything (Apache-Variante). Später als Option für `fotocad`.
- Brennweite und grobe Tiefe aus einem Bild: Apple Depth Pro (MPS offiziell), nur als Plausibilitätsprüfung.
- Größter Genauigkeitshebel für das Foto-Verfahren: Kanten und Bauteilmasken zusätzlich zur Silhouette abgleichen.
- Mac M2 Pro mit 16 GB: TRELLIS.2 (24 GB+) und SAM 3D (NVIDIA 32 GB) fallen lokal aus.
