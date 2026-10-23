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
- Mitgeliefert werden drei davon, als Radiance-HDR umgewandelt (1024 × 512), mit `LIZENZ.md` und Quelle:
  `halle.hdr` (Studio-Halle mit Lampen, studio_small_01) für „Werkstatt“, `garten.hdr` (ninomaru_teien) für
  „Draußen“, `innenraum.hdr` (hotel_room) für „Wohnraum“. „Courtyard“ fiel durch (ein Carport mit Hund im Bild). Das
  Studio ist eine selbst erzeugte Umgebung (Softboxen auf neutralem Grau), ohne fremde Lizenz.
- Die 1K-Bilder sind als Hintergrund grob; beide Wege zeigen den Hintergrund deshalb leicht unscharf (Blender:
  Richtung der Kamerastrahlen verrauscht, RealityKit: verkleinerte, weichgezeichnete Umgebung).
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
| R7 | **Schatten in RealityKit über drei Durchgänge** (siehe Recherche), weichgezeichnet; seit 23.10.2026 ersetzt durch R14 (ein Durchgang, Bodenschatten auf der CPU) | Einziger Weg zu einem Schatten auf einem einheitlichen oder durchsichtigen Hintergrund |
| R8 | **Szenen:** `studio` (heller Hintergrund, weicher Schatten, eigene Softbox-Umgebung), `werkstatt` (Halle mit Lampen, HDRI), `draussen` (Garten, HDRI), `wohnraum` (Innenraum, HDRI), `freigestellt` (Studio-Licht, durchsichtiger Hintergrund, Schatten als halbdurchsichtiges Schwarz, ohne Kulisse) | Kevins Liste; HDRIs CC0 aus Blender |
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
   **erledigt**
3. Kernel: `render/` (Szenen, Größen, Ansichten, Blender-Szene, Blender-Skript, Laufzeit), MCP `render`,
   Protokoll mit Testdateien (`tools/make_render_fixtures.py`), Tests. **erledigt**
4. App-Kern: `Render/` (Nachrichten, RealityKit-Renderer, Umgebungen, Steuerung), Tests gegen die Testdateien.
   **erledigt**
5. Oberfläche: Dialog „Rendern …“ mit Vorschau, Fortschritt, Finder und Teilen; Baustein „Produktbild“.
   **erledigt**, Selbsttest `KEVCAD_SELFTEST=render`
6. Nachweis am Kugelschieber (Kopie): Studio schnell und Foto, Sekunden je Bild und Speicher. **erledigt**

## Abnahme (22.10.2026, Testvariante „Kev CAD Test r7“, MacBook M2 Pro, 16 GB)

Kugelschieber Variante B (Kopie, 134 Teile, 150 464 Dreiecke, davon zwei Kulisse-Böden 21 × 6 m), Studio,
Produktansicht, über MCP `render` gegen die laufende Testvariante:

| Auftrag | Größe | Zeit | Phasen |
|---|---|---|---|
| schnell, erstes Bild nach dem Start | 960 × 540 | 2,2 s | Netze 0,52 s, Umgebung 0,29 s, Rendern 0,15 s, PNG 0,05 s |
| schnell, Studio | 1920 × 1080 | 0,7 s | Netze (Zwischenspeicher) 0,21 s, Rendern 0,17 s, PNG 0,11 s |
| schnell, Studio | 3840 × 2160 | 1,4 s | Rendern 0,32 s, PNG 0,54 s |
| schnell, Freigestellt | 1920 × 1080 | 0,9 s | |
| schnell, Draußen | 1920 × 1080 | 1,1 s | Umgebung (HDR laden) 0,22 s |
| schnell, Werkstatt | 1920 × 1080 | 2,3 s | |
| Foto (Blender Cycles, GPU) | 1920 × 1080 | 32,6 s | Szene schreiben 0,02 s, Blender 32,4 s, 160 Proben mit Rauschgrenze und Entrauschen |

Dazu Foto freigestellt 960 × 540: 15 s (132 Teile, ohne Kulisse). Die Zeiten oben stammen aus einem Lauf bei
mäßiger Last. Unter Volllast (Lastmittel um 70 durch parallele Stränge mit Xcode und iOS-Simulator) lief eine Reihe
von zehn schnellen Aufträgen (Kamera aus model.py, Produkt, iso, vorn, aktuell, Wohnraum, Freigestellt, oben, 4K)
vollständig durch, brauchte aber 7 bis 36 s je Bild; der größte Teil war Warten auf den Hauptfaden (Phase `start`).
Deshalb hält die App den Viewport während eines Bildes an, jedes RealityKit-Bild hat eine Frist von 12 s (danach
neuer Renderer und ein zweiter Versuch), und der Kernel wartet bei „schnell“ 60 s plus 10 s je Megapixel.

Selbsttest des Dialogs (`KEVCAD_SELFTEST=render`, ohne Maus und Tastatur): Vorschau Studio, Wechsel auf Freigestellt
und Instagram hochkant, Rendern, PNG 1080 × 1350 mit Alpha, „letztes Bild“ im Dialog – bestanden.

Speicher (höchste RSS während aller Aufträge): App 568 MB, Blender 1 748 MB. Bei den Probeszenen meldete
`/usr/bin/time` für Blender rund 5 GB „peak memory footprint“ (einschließlich GPU-Speicher und Shader-Übersetzung);
deshalb läuft nur ein Foto-Auftrag zur Zeit, und unter 20 % freiem Speicher wartet er bis zu 2 min.

Tests: Kernel 889 grün, 1 übersprungen (echter Blender-Lauf, mit `KEVCAD_BLENDER_TEST=1` grün); `test_render.py`
16 Fälle. KevCADCore: `RenderTests` (8) und die Export-Tests grün.

### Offene Punkte (Stand 22.10.2026, erledigt bis auf zwei, siehe unten)

- ~~Schatten im Schnellbild weicher und schwächer als im Foto~~ (R14)
- **Werkstatt** ist vorerst eine dunkle Studiohalle; eine echte Werkstatt-HDRI braucht Kevins Freigabe zum Laden.
- ~~Schichtlinien quer zur Welt-Z-Achse statt zur Druckausrichtung~~ (R16)
- ~~Parallele Projektion wird perspektivisch~~ (R15)
- **Von Hand prüfen:** Dialog mit echten Klicks (Teilen-Menü, Finder), Fokus und Tastenkürzel ⌥⌘R.
- ~~RealityKit meldet selten ein Bild nicht fertig~~ (R17)

## Restpunkte (Zweig `rest-statik-render`, 23.10.2026)

| Nr. | Entscheidung | Begründung |
|---|---|---|
| R14 | **Bodenschatten im Schnellbild auf der CPU** (`KevCADCore/Render/BodenSchatten.swift`) statt der Schattenmaske aus zwei weiteren RealityKit-Durchgängen (R7): je Licht des Fotos (Studio: Hauptlicht 18°, Kante 13°, Aufheller 18°, Decke 27°, Himmel 60°; mit HDRI Sonne 4° und Himmel) die Dreiecke des Produkts längs des Lichts auf den Boden projizieren und rastern (höchstens 768 Zellen je Seite), daraus weiche Schatten wie bei einer Flächenleuchte (PCSS: mittlerer Verdecker im Suchfenster, Halbschatten t · tan Winkel, Deckung über Summentabellen in O(1) je Zelle); seitliche Lichter mit der tiefsten Fläche (am Fuß hart), Decke und Himmel mit der höchsten (wie Umgebungsverdeckung), dazu ein Kontaktschatten aus allem bis 4 % der Modellgröße über dem Boden. Die Teile werfen in RealityKit weiter Schatten aufeinander. Gewichte und Stärke an Fotos derselben Szene abgeglichen (weißes und dunkles PLA, siehe Abnahme): Kante deutlich schwächer, als ihre Leistung erwarten ließe; helle Teile werfen Licht zurück und heben bis zu 70 % der Verdeckung von oben (Decke, Himmel, Kontakt) auf, nach ihrer mittleren Helligkeit | RealityKit hat keine Flächenlichter, keine Umgebungsverdeckung und auf dem Mac keinen Schattenfänger; die Schattenkarte eines Richtungslichts gibt weder den Kontaktschatten noch den mit dem Abstand weicher werdenden Halbschatten. Die CPU-Rechnung ist in 50 ms fertig (1600 × 1000, Release) und spart zwei RealityKit-Bilder je Aufnahme |
| R15 | **Parallele Ansicht echt orthografisch:** `ansicht="aktuell"` bei paralleler Projektion im Viewer: RealityKit `OrthographicCameraComponent` (`scale` ist die halbe sichtbare Höhe, gemessen), Blender Kamera `ORTHO` mit `ortho_scale` (vertikal); die Kamera meldet `projection: orthographic` und `ortho_height_mm`; das Auge rückt hinter die Hüllkugel, der Hintergrund aus einer HDRI ist dann einfarbig in Blickrichtung (wie in Blender) | Zeichnungsähnliche Bilder (Schnitt, Ansicht von vorn) brauchen parallele Kanten; gleiche sichtbare Höhe wie im Viewer |
| R16 | **Schichtlinien quer zur Druckrichtung:** Die Druckprüfung legt die Aufbaurichtung in Weltlage ab (`CHECK.druck.teile[n].ausrichtung.oben_welt`), der Kernel gibt sie als `druck_oben` je Teil mit (`RENDER_REQ.teile`, Blender-Material); RealityKit projiziert v längs dieser Richtung (`schichtUV`, Deck- und Bettflächen ohne Linien), Blender nimmt sin(2π (p · oben) / h) | Dieselbe Ausrichtung wie Druckvorschau und Druckprüfung (vorgegeben mit `lager.druckteil(…, ausrichtung=…)` oder automatisch) |
| R17 | **Bild fertig, auch wenn RealityKit es nicht meldet:** Jedes Bild setzt nach dem Rendern ein GPU-Ereignis (`MTLSharedEvent`, `actionsAfterRender`); fertig ist es mit dem Ereignis oder der Meldung `onComplete`, was zuerst kommt. Kommt keins binnen 12 s, steht ein Befund im Protokoll (geplant, GPU fertig, gemeldet, auf welchem Faden, ob der Hauptfaden frei war), der Renderer wird verworfen und die App versucht es einmal neu (`phasen.wiederholt`); scheitert auch das, geht der Fehler mit Befund an den Kernel. Statt drei Durchgängen mit je zwei Bildern ist es nur noch einer (R14), höchstens 24 s je Versuch, zwei Versuche bleiben unter der Frist des Kernels (60 s) | Ursache nicht gefunden: In allen Läufen kam die Meldung abseits des Hauptfadens (`gemeldet ja (abseits des Hauptfadens)`), ein blockierter Hauptfaden scheidet als Ursache also aus; der Fehler ließ sich nicht nachstellen. Das Ereignis macht den Weg unabhängig von der Meldung, der Befund zeigt beim nächsten Auftreten, woran es lag |

Nachweise (Tests in `RenderTests`: `testRealityKitOrthografisch`, `testBodenSchattenKontaktUndSchlagschatten`,
`testKameraStrahlenPerspektiveUndParallel`, `testSchichtUVNachDruckrichtung`; Kernel `test_render.py`
`test_render_schichtlinien_nach_druckrichtung`):

- Orthografisch: zwei 100-mm-Würfel, einer 500 mm tiefer, bei 200 mm sichtbarer Höhe auf 200 px: beide 100 × 100 px,
  der vordere an der erwarteten Stelle (x = −150 mm bei Pixel 50).
- Testvariante „Kev CAD Test sr“ (über MCP, Probe im Scratchpad): parallele Iso-Ansicht im Viewer, `render(ansicht=
  "aktuell")` schnell und als Foto: beide mit parallelen Kanten und gleichem Ausschnitt.
- Schichtlinien: zwei gleiche Blöcke, einer `ausrichtung="-z"`, einer `"-x"`: im Schnellbild und im Foto liegen die
  Linien beim ersten waagrecht, beim zweiten senkrecht (quer zu x), auf seiner Bettseite (Normale x) keine.
- Schatten (Studio, Produktansicht, 1600 × 1000, gleiche Kamera, Helligkeit des Bodens linear relativ zum
  Hintergrund): siehe Tabelle; Schnellbild 0,9 bis 1,1 s, davon Schatten 0,05 s.

## Abnahme der Restpunkte (Testvariante „Kev CAD Test sr“, 23.10.2026)

Probe im Scratchpad: zwei Blöcke 60 × 40 × 40 mm (`ausrichtung="-z"` und `"-x"`) und ein Turm 30 × 30 × 120 mm,
PLA, Studio, Produktansicht, 1600 × 1000, Schnellbild und Foto mit derselben Kamera. Bodenhelligkeit linear
(sRGB entzerrt), bezogen auf den Hintergrund; gemessen an Weltpunkten, die in beide Bilder projiziert werden.

Schatten des Turms längs des Hauptlichts (Abstand vom Fuß):

| Abstand | 22 mm | 30 mm | 45 mm | 70 mm | 100 mm | 130 mm | 160 mm |
|---|---|---|---|---|---|---|---|
| weiß, Schnellbild | 0,66 | 0,67 | 0,68 | 0,72 | 0,78 | 0,87 | 0,94 |
| weiß, Foto | 0,72 | 0,71 | 0,72 | 0,78 | 0,84 | 0,88 | 0,94 |
| dunkel, Schnellbild | 0,64 | 0,67 | 0,67 | 0,72 | 0,78 | 0,87 | 0,94 |
| dunkel, Foto | 0,59 | 0,62 | 0,65 | 0,74 | 0,82 | 0,87 | 0,93 |

Boden vor der Vorderkante des flachen Blocks (Kontaktschatten):

| Abstand | 0,5 mm | 1 mm | 2 mm | 4 mm | 7 mm | 10 mm | 15 mm | 25 mm |
|---|---|---|---|---|---|---|---|---|
| weiß, Schnellbild | 0,76 | 0,79 | 0,85 | 0,90 | 0,93 | 0,94 | 0,95 | 0,96 |
| weiß, Foto | 0,99 | 1,00 | 0,99 | 0,99 | 0,98 | 0,97 | 0,96 | 0,92 |
| dunkel, Schnellbild | 0,71 | 0,74 | 0,80 | 0,86 | 0,89 | 0,91 | 0,93 | 0,95 |
| dunkel, Foto | 0,73 | 0,74 | 0,73 | 0,75 | 0,76 | 0,77 | 0,79 | 0,81 |

| Punkt | Ergebnis |
|---|---|
| Schatten (R14) | Der Schlagschatten des Turms liegt in Lage, Länge und Verlauf beim Foto, bei weißem und dunklem PLA höchstens 0,07 daneben; vorher war er im Schnellbild deutlich schwächer und weicher. Grenze: Vor hellen Teilen hellt das Foto den Boden durch Rückstrahlung bis an die Kante auf (0,99), das Schnellbild bleibt mit Kontaktschatten dunkler (0,76); die Rückstrahlung heller Teile mildert das nur. Vor dunklen Teilen ist das Foto weiter draußen dunkler (0,81 gegen 0,95 bei 25 mm), weil dort nichts zurückstrahlt |
| Zeit | Schnellbild 0,8 bis 1,1 s (Schatten 0,05 s), Foto 23 bis 28 s |
| Parallel (R15) | Viewer auf parallele Projektion (`view(projection="orthographic")`), `render(ansicht="aktuell")` schnell und als Foto: beide mit parallelen Kanten, gleichem Ausschnitt, Kamera mit `projection: orthographic` |
| Schichtlinien (R16) | Block `-z` waagrechte Linien, Block `-x` senkrechte, Turm waagrecht; Bettseite des seitlichen Blocks ohne Linien; im Foto ebenso |
| Bildmeldung (R17) | In allen Aufnahmen kam `onComplete` abseits des Hauptfadens, kein Befund, keine Wiederholung nötig |
