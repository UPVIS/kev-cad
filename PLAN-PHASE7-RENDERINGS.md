# Kev CAD · Phase 7: Renderings

Stand: 22.10.2026 (Kevin am selben Tag: „Bitte mit allem weitermachen, was geht.“). Zweig `phase7` auf `main`.
Grundlage: PLAN-MVP.md Abschnitt 15, Punkt 3 („RealityKit offscreen mit Studiolicht und Materialien. Für Schönes weiter
Blender mit `bauteile.py`.“). Vertrag: PROTOCOL.md Abschnitt „Phase 7: Renderings“, KATALOG.md Abschnitt
„Material“ (Feld `render`).

## Ziel

Kevin bekommt aus Kev CAD schöne Bilder seiner Konstruktionen: Produktbild, Bild für den Bauplan bzw. das
Deckblatt, Bild für Kunden und Social Media. Schnell und gut am Mac, auf Wunsch fotorealistisch.

1. Menü „Rendern …“ (⌥⌘R): Szene, Größe, Qualität, Hintergrund, Ansicht; Vorschau im Dialog; Ergebnis im Finder
   zeigen oder teilen.
2. MCP `render(szene, ansicht, kamera, groesse, qualitaet, hintergrund, ziel)` für den Agenten; Ergebnis unter
   `<projekt>/output/renders/`.
3. Baustein „Produktbild“ im Export-Dialog von Phase 6 (eigene Seite nach dem Deckblatt).

## Recherche (Oktober 2026)

Kennzeichnung: **belegt** (am SDK, am Quelltext oder durch eigene Messung auf diesem MacBook, M2 Pro, 16 GB, macOS
26.6), **angenommen** (abgeleitet, nicht gemessen).

### RealityKit offscreen (`RealityRenderer`)

- `RealityRenderer` gibt es ab macOS 15 (`@available(macOS 15.0)` in RealityFoundation.swiftinterface des SDK):
  Entitäten, `activeCamera`, `cameraSettings.colorBackground` (`.color(CGColor)` oder `.outputTexture()`),
  `cameraSettings.antialiasing = .multisample4X`, `lighting` (Bildbeleuchtung aus einer `EnvironmentResource`),
  `updateAndRender(deltaTime:cameraOutput:)` in eine eigene `MTLTexture`. **belegt** (SDK)
- `EnvironmentResource(equirectangular: CGImage)` ab macOS 15; `PhysicallyBasedMaterial` mit Basisfarbe, metallisch,
  Rauheit, Klarlack, Anisotropie, Normalen- und Farbtextur; `DirectionalLightComponent.Shadow` mit
  `shadowProjection: .fixed/.automatic`; `PerspectiveCameraComponent`, `OrthographicCameraComponent` (macOS 15).
  **belegt** (SDK)
- Probe (`scratchpad/rk/spike.swift`): drei PBR-Körper, Bildbeleuchtung aus einer 1K-HDR, gerichtetes Licht mit
  Schatten, 1600 × 1000 px. Einrichten 0,79 s (davon der Großteil die Umgebung), drei Bilder 0,46 s, Prozess
  höchstens 91 MB. Metall spiegelt die Umgebung richtig, Schatten fallen auf einen beleuchteten Boden. **belegt**
- Transparenter Hintergrund: `colorBackground = .color(rgba 0,0,0,0)` liefert Alpha 0 im Hintergrund und 1 am Körper.
  **belegt**
- **Kein Schattenfänger auf dem Mac:** `OcclusionMaterial(receivesDynamicLighting: true)` zeigt im Offscreen-Bild
  keinen Schatten (gemessen; der Parameter ist nur für visionOS dokumentiert). Ein sichtbarer Boden passt farblich nie
  genau zum Hintergrund. Lösung: drei Durchgänge (Körper mit Boden, nur Boden, nur Körper freigestellt); das
  Verhältnis der beiden Bodenbilder ist die Schattenmaske, weichgezeichnet und über den Hintergrund gelegt. **belegt**
  (Probe), Aufwand etwa dreimal ein Bild.
- `ImageIO` liest die DWAB-komprimierten EXR von Blender nicht (`CGImageSourceCreateImageAtIndex` = nil), wohl aber
  Radiance-HDR (16 bit je Kanal, erweitert-linear). Die mitgelieferten Umgebungen liegen deshalb als `.hdr` vor.
  **belegt**
- Keine Umgebungsverdeckung (Ambient Occlusion) und keine weichen Flächenlichter in `RealityRenderer`; die
  Kontaktschatten kommen aus `GroundingShadowComponent` (ab macOS 15) und dem weichgezeichneten Schatten. **belegt**
  (SDK), Wirkung **angenommen**.

### Metal über OCCTSwiftViewport (Commit `d9984ad`)

- Der `OffscreenRenderer` des Viewports kann Schattenkarten (`lighting.shadowsEnabled`) und `PBRMaterial` je Körper
  (metallisch, Rauheit, Klarlack). SSAO, Bildbeleuchtung (`EnvironmentMapManager`) und TAA gibt es nur im
  Live-Renderer des Fensters, nicht im Offscreen-Pfad. **belegt** (Quelltext `OffscreenRenderer.swift`,
  `ViewportRenderer.swift`)
- Ohne Umgebungsbild wirken metallische Flächen fast schwarz (deshalb rendert der Viewer heute alles matt,
  `SceneStore.metallic`). **belegt** (Kommentar und Verhalten im Viewer)
- Für ein Produktbild müsste man SSAO und Bildbeleuchtung in den Offscreen-Pfad des festgenagelten Pakets einbauen
  (Fork). **angenommen**: deutlich mehr Aufwand als RealityKit, ohne Gewinn an Bildqualität.

### Blender Cycles im Hintergrund

- Blender 4.5.3 LTS liegt unter `/Applications/Blender.app`; Cycles rendert auf dem M2 Pro über Metal
  (`compute_device_type = "METAL"`). **belegt** (Version, Beelonia-Renderer `render_blender.py`)
- Erfahrungswert aus „CAD aus Fotos“: Standbild 2400 × 1600 mit 160 Proben rund 2 min auf dem M2 Pro, Glas und
  Spiegelungen richtig. **belegt** (README dort)
- Messung dieser Phase (Kugelschieber, Studio): siehe Abschnitt „Nachweis“.
- Schattenfänger (`is_shadow_catcher`) und durchsichtiger Film (`film_transparent`) gibt es in Cycles; Flächenlichter
  ohne Kamerasichtbarkeit für weiches Studiolicht. **belegt** (Beelonia-Renderer)

### Umgebungen (HDRI) und Lizenz

- Blender liefert acht HDRIs in `datafiles/studiolights/world/` mit: **„All HDRIs are licensed as CC0.“**, erstellt
  von Greg Zaal (Poly Haven), Quellen je Bild in `license.txt` (z. B. Courtyard: polyhaven.com/a/courtyard, Interior:
  polyhaven.com/a/hotel_room). **belegt** (Datei auf diesem Mac, nichts heruntergeladen)
- Mitgeliefert werden zwei davon, als Radiance-HDR umgewandelt (1024 × 512): `innenraum.hdr` (Interior) für
  „Werkstatt“ und `hof.hdr` (Courtyard) für „Draußen“, mit `LIZENZ.md` und Quelle. Das Studio ist eine selbst
  erzeugte Umgebung (Softboxen auf neutralem Grau), ohne fremde Lizenz.
- Eine echte Werkstatt-HDRI (z. B. Poly Haven, CC0) wäre schöner. Laden erst nach Kevins Freigabe; Kevin kann jede
  eigene `.hdr` über `umgebung=` oder den Ordner `~/Library/Application Support/de.upvis.kevcad/umgebungen/` nutzen.

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| R1 | **Zwei Stufen.** „Schnell“ mit RealityKit in der App (eine bis wenige Sekunden), „Foto“ mit Blender Cycles im Hintergrund (eine bis wenige Minuten) | RealityKit liefert PBR, Bildbeleuchtung, Schatten und Freisteller ohne eigenen Renderer; Cycles bringt Flächenlicht, Umgebungsverdeckung, weiche Schatten und echte Spiegelungen. Metal über den Viewport bräuchte einen Fork für SSAO und Bildbeleuchtung (siehe Recherche) |
| R2 | **Der Kernel steuert jeden Auftrag**, die App ist Bildgeber | Materialien kommen aus dem Katalog (Kernel), Ansicht, Lage (Explosion, Animation) und Sichtbarkeit aus der App. Ein Weg für MCP und Dialog: `RENDER_START` (App) bzw. `render` (MCP) → Kernel → `RENDER_REQ` an die App (schnell) oder `RENDER_SCENE_REQ` plus Blender (Foto) → `RENDER_STATUS` |
| R3 | **Szene wie im Viewer:** sichtbare Teile, Explosion und Animationslage aus der App; Schnitt, Hervorhebungen, Röntgen und Maße bleiben draußen | Ein Rendering zeigt das Produkt, nicht den Arbeitszustand |
| R4 | **Materialien additiv im Katalog** (`render`: Basisfarbe, metallisch, Rauheit, Oberfläche, Klarlack, Anisotropie, Durchsicht); ohne `render` leitet der Kernel aus `farbe`, `metallisch`, `rauheit` und `gruppe` ab | Bestehende eigene Materialien rendern ohne Pflege; neue Oberflächen (gebürstet, eloxiert, verzinkt, Schichten, Holz, Gummi) als Name, nicht als Textur-Datei |
| R5 | **Farbe aus model.py hat Vorrang**, wenn sie von der Katalogfarbe des Materials abweicht (farbiges PLA, eloxiert schwarz) | So bleibt das Bild bei Kevins Farbwahl; Glanz und Metall kommen weiter aus dem Material |
| R6 | **Oberflächen prozedural:** Blender mit Knoten (Rauschen, Wellen, Voronoi), RealityKit mit kleinen erzeugten Texturen über Quaderprojektion (Normalen für Schichten und Bürstung, Farbe für Holz) | Keine Texturdateien, keine Lizenzfragen, Netze ohne UV reichen |
| R7 | **Schatten in RealityKit über drei Durchgänge** (siehe Recherche), weichgezeichnet | Einziger Weg zu einem Schatten auf einem einheitlichen oder durchsichtigen Hintergrund |
| R8 | **Szenen:** `studio` (heller Hintergrund, weicher Schatten, eigene Softbox-Umgebung), `werkstatt` (Innenraum-HDRI), `draussen` (Hof-HDRI), `freigestellt` (Studio-Licht, durchsichtiger Hintergrund, Schatten als halbdurchsichtiges Schwarz) | Kevins Liste; HDRIs CC0 aus Blender |
| R9 | **Kamera:** aktuelle Ansicht (Vorgabe), Standardansicht, `produkt` (3/4-Ansicht leicht von oben, perspektivisch, eingepasst) oder eine Kamera aus Phase 5 (posiert wie im Viewer) | Kevin bestimmt den Ausschnitt im Viewer, der Agent kann ohne Viewer eine gute Ansicht wählen |
| R10 | **Blender nur einzeln, mit `nice` und Zeitlimit**, Fortschritt aus der Ausgabe von Cycles (`Sample n/m`), Arbeitsdateien werden nach dem Lauf gelöscht | 16 GB, zwei weitere Stränge, Platte knapp |
| R11 | **MCP `render` wartet bei „schnell“, bei „foto“ nicht** (Auftrag läuft im Hintergrund, `render(auftrag="R-3")` fragt den Stand ab, `warten_s` wartet höchstens so lange) | Ein Foto dauert Minuten; der Agent soll weiterarbeiten können |
| R12 | **Bilder sind für Kevin**: der Agent bekommt Pfad und Kennzahlen, das Bild nur mit `bild=True` | Kevins Regel: keine Bilder ungefragt |
| R13 | **Produktbild im Export** rendert schnell im Studio aus der Produktansicht, außer es gibt in `output/renders/` ein Rendering, das jünger ist als der letzte Lauf (dann das) | Ein Foto-Rendering, das Kevin vorher bestellt hat, kommt ins PDF; sonst passt das Bild immer zum Modell |

## Ablauf

```
Dialog „Rendern …“ ──RENDER_START──▶ Kernel ◀── MCP render(...)
                                        │ Materialien aus dem Katalog, Pfad, Auftrag R-n
              ┌─────────────────────────┴──────────────────────────┐
         schnell                                                  foto
   RENDER_REQ ▶ App (RealityKit, drei Durchgänge)     RENDER_SCENE_REQ ▶ App: Kamera, Lagen, Sichtbarkeit
   RENDER_RES ◀ App (PNG geschrieben)                 Kernel schreibt Netze und szene.json, startet Blender
                                                       (nice, Zeitlimit), liest „Sample n/m“
              └─────────────── RENDER_STATUS (läuft, fertig, Fehler) ▶ App ───────────────┘
```

## Arbeitspakete

1. Plan (diese Datei), Recherche mit Probe. **erledigt**
2. Katalog: `render` für alle mitgelieferten Materialien, KATALOG.md, Ableitung im Kernel (`render/materialien.py`).
3. Kernel: `render/` (Szenen, Größen, Ansichten, Blender-Szene, Blender-Skript, Laufzeit), MCP `render`,
   Protokoll mit Testdateien (`tools/make_render_fixtures.py`), Tests.
4. App-Kern: `Render/` (Nachrichten, RealityKit-Renderer, Umgebungen, Steuerung), Tests gegen die Testdateien.
5. Oberfläche: Dialog „Rendern …“ mit Vorschau, Fortschritt, Finder und Teilen; Baustein „Produktbild“.
6. Nachweis am Kugelschieber (Kopie): Studio schnell und Foto, Sekunden je Bild und Speicher.

## Nachweis

Siehe Abschnitt „Abnahme“ unten (wird mit den Messwerten gefüllt).
