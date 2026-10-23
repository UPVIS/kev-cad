# Kev CAD · Recherche und Architekturvorschlag

Stand: 21.10.2026. Sterne und letzte Aktivität per `gh api` am selben Tag geprüft.

## Ziel

Ein nativer, schneller CAD-**Viewer** für den Mac, den ein KI-Agent über MCP bedient. Das Modell entsteht
per Code und baut sich live Stück für Stück auf. Kein vollwertiges CAD mit eigenen Werkzeugen, sondern:

- Baugruppen und Einzelteile, Zoomen auf ein Teil, Hervorheben, Ausblenden, Explosion
- **Messen** (Abstand, Winkel, Radius, Hüllquader, Volumen, Masse, Schwerpunkt)
- **Datenblätter und Zeichnungen** als PDF, direkt druckbar
- **Materialien und Lagerteile** definieren (Rohre, Profile, Platten, Schrauben) und verbauen, mit Stückliste
- einfache Renderings
- Druck auf dem **Bambu Lab P2S** mit einem Klick
- einfache Dateiverwaltung (Speichern, Laden, Versionen)

## Was schon auf dem Mac liegt

- `~/.venvs/cad`: Python 3.12, **build123d 0.13** auf OCCT 8.0.1 (aus „CAD aus Fotos“)
- Bambu Studio 02.07.01.62 mit P2S-Profilen, Blender, FreeCAD
- Swift 6.4, Xcode, `uv`, `rsvg-convert`
- Testmodell mit vielen Teilen: Outdoorküche eines Kunden in build123d (bei Kevin lokal, nicht im Repo)

## Fundstücke

### Native Mac-Apps und Viewer

| Projekt | Lizenz | Sterne / letzte Aktivität | Was es ist | Urteil |
|---|---|---|---|---|
| [filippofinke/cad-studio](https://github.com/filippofinke/cad-studio) | MIT | 29 / 10.10.2026 (seit 06.10.) | Native macOS-App: Claude Code schreibt build123d, RealityKit-Viewer, Messen, Schnitt, Explosion, ISO-Zeichnung als PDF, Versionen, Druckplatte als 3MF | Konzept fast identisch. Aber: Agent läuft *in* der App (`claude -p`), kein MCP für deine Sitzung, Neuladen über Dateibeobachtung statt Live-Stream, Zeichnungen per matplotlib. **UX und Code übernehmen** |
| [SecondMouseAU/OCCTSwift](https://github.com/SecondMouseAU/OCCTSwift) | LGPL-2.1 | 15 / heute | OCCT 8.0.1 als Swift-Paket (fertiges arm64-xcframework), STEP/IGES/glTF, Baugruppen, exakte Messung, Verdeckte-Kanten-Zeichnungen | Starker Baustein, aber ein Entwickler und sehr schnelle API-Wechsel. **Optional für exakte Messung in Swift** |
| [SecondMouseAU/OCCTSwiftViewport](https://github.com/SecondMouseAU/OCCTSwiftViewport) | LGPL-2.1 | 2 / heute | Metal-Viewport für SwiftUI: Picking per ID-Puffer (Körper und Fläche), Kanten, Schnittebenen, Mess-Overlays, ViewCube, SSAO | **Kandidat als Viewer-Basis** (forken, Version festnageln) |
| [tomasf/CadovaViewer](https://github.com/tomasf/CadovaViewer) | MIT | 38 / gestern | 3MF-Viewer mit Live-Reload, Schnitten, Messung, Teileliste | SceneKit (ab macOS 26 abgekündigt), nur Netze. **UX-Ideen** |
| [tomasf/ThreeMF](https://github.com/tomasf/ThreeMF), [manifold-swift](https://github.com/tomasf/manifold-swift) | MIT | 16 / 27 | 3MF lesen und schreiben, Netz-Booleans | **Direkt nutzbar** |
| [warrenm/GLTFKit2](https://github.com/warrenm/GLTFKit2) | MIT | 235 | glTF-Lader, behält `extras` | **Direkt nutzbar** |

### Kernel, MCP und Live-Übertragung

| Projekt | Lizenz | Sterne / letzte Aktivität | Was es ist | Urteil |
|---|---|---|---|---|
| [gumyr/build123d](https://github.com/gumyr/build123d) | Apache-2.0 | 3.489 / heute | Python-Code-CAD auf OCCT. Gelenke für Baugruppen, Materialien (`bd_materials`), Messfunktionen, Verdeckte-Kanten-Projektion, Zeichnungsmodul mit Schriftkopf | **Kernel.** Kennen die Modelle am besten, du nutzt es schon |
| [pzfreo/build123d-mcp](https://github.com/pzfreo/build123d-mcp) | Apache-2.0 | 125 / 15.10. | 51 Werkzeuge: dauerhafte Sitzung in einem abbrechbaren Prozess, Messen, Prüfen, Kollision, Schnitte, Bilder, Export, Snapshots mit Rückrollen. **Live-Stream** über Unix-Socket: je geändertem Teil ein GLB (`HELLO`/`UPSERT`/`REMOVE`/`RESET`) | **Kernel-Seite übernehmen.** Der Stream passt direkt zu einer nativen App |
| [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) | MIT | 22.196 / gestern | Plugin für Claude Code: build123d-Skills, Viewer im Browser, Zeichnungs-PDF mit automatischen Maßen, DFM-Prüfung, Slicen, Bambu-Druck | Größtes Projekt. Nicht nativ, Telemetrie standardmäßig an, auf build123d < 0.12 festgelegt. **Zeichnungsmodul (`eng_drawing.py`) und Auswahl-Referenzen übernehmen** |
| [KittyCAD/mcp](https://github.com/KittyCAD/mcp) (Zoo) | MIT | 10 / 19.10. | KCL-Modellierung mit Auswahl, Hervorheben, Kamera auf Auswahl, Ansichten | Rechenkern läuft in Zoos Cloud. **Nur das Werkzeug-Design übernehmen** |
| [bernhard-42/vscode-ocp-cad-viewer](https://github.com/bernhard-42/vscode-ocp-cad-viewer) + three-cad-viewer + ocp-viewer-core | Apache-2.0 / MIT | 418 / 395 | Standard-Viewer für build123d. WebSocket auf Port 3939, `show()` schickt Teile live. Messen: Viewer liefert Flächen-ID, Python rechnet exakt | **Protokoll übernehmen**, damit jedes `show()` in der App landet |
| [yeicor-3d/yet-another-cad-viewer](https://github.com/yeicor-3d/yet-another-cad-viewer) | MIT | 143 / heute | Viewer über Server-Sent Events + GLB mit Flächenzuordnung | Einfachstes Protokoll, Alternative |
| [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) | MIT | 2.989 | FreeCAD fernsteuern | Bedient FreeCADs Oberfläche, nicht unsere. Nicht geeignet |
| [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) | MIT | 31.873 | Blender fernsteuern | Nur für schöne Renderings |

### Teile, Materialien, Zeichnungen

- **[bd_warehouse](https://github.com/gumyr/bd_warehouse)** (Apache-2.0): Schrauben, Muttern, Scheiben nach ISO/DIN, Lager, Gewinde,
  Zahnräder, Sicherungsringe, O-Ringe, OpenBuilds-V-Slot 2020 bis 4040. Rohre nur in US-Maßen.
- **[FrameForge](https://github.com/lukh/frameforge)** (LGPL-3.0): beste offene Stahlprofiltabellen mit kg/m (EN 10210/10219
  Vierkant- und Rechteckrohre, Winkel, IPE/HEA/HEB, Flach, Rund, Holz) und Zuschnittliste mit Gehrungswinkeln.
- **Lücken**: keine offene Tabelle für Rohre nach DIN EN 10220/10255 oder ISO 1127 und keine für Nutprofile von item/Bosch.
  Die müssen wir selbst anlegen.
- **Zeichnungen**: build123d liefert verdeckte Kanten und einen Schriftkopf, aber keine automatischen Maße. cadgen aus
  text-to-cad hat brauchbare automatische Maße (Außenmaße, Bohrungen, Radien), ohne Schnittansichten und ohne Stückliste.
  FreeCAD TechDraw ist am vollständigsten, braucht für PDF aber die Oberfläche.
- **Stolperfalle**: build123d 0.13 braucht OCP 8, CadQuery und cadgen brauchen OCP < 8. Nicht in einer Umgebung mischen.
- **Stolperfalle**: Eigene Attribute an build123d-Teilen gehen bei Booleans verloren. Metadaten (Lagerteil, Länge, Preis)
  deshalb in einem eigenen Register halten.

### Bambu Lab P2S

> **Korrektur 21.10.2026:** Kevins Drucker ist ein **Bambu Lab P1P** (offen, ohne Gehäuse), nicht der P2S. Bauraum
> und Düse sind gleich; Ansteuerung (LAN-Modus, MQTT, FTP, Freigaben) und Profile sind für Phase 8 neu zu prüfen.

- Einen „P2P“ gibt es nicht. Gemeint ist der **P2S** (seit Herbst 2025, 256 mm Bauraum).
- **Ohne Umstellung am Drucker**: Slicen per Kommandozeile von Bambu Studio (P2S-Profile sind installiert) und das fertige
  `.gcode.3mf` an Bambu Studio oder Bambu Connect übergeben. Dort ein Klick auf Drucken. Cloud und Handy-App bleiben.
- **Ganz direkt aus der App**: nur mit **LAN-Only und Developer Mode** am Drucker. Dann Upload per FTPS (Port 990) und Start
  per MQTT (Port 8883), Fortschritt und Temperaturen live in der App. Cloud und Handy-App fallen in diesem Modus weg.
- P2S-Eigenheiten: TLS auf 1.2 begrenzen, `ams_mapping2` mitschicken, externe Spule heißt `vir_slot`.
- Referenzen: [OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI), [ha-bambulab](https://github.com/greghesp/ha-bambulab),
  [bambu-printer-mcp](https://github.com/DMontgomery40/bambu-printer-mcp) (GPL, nur als Vorlage).

### Technik von Apple

- SceneKit ist ab macOS 26 abgekündigt. Nicht mehr darauf bauen.
- RealityKit kann offscreen rendern (`RealityRenderer`) und ist gut für PBR-Renderings, bietet aber keinen ID-Puffer für
  Picking und keine dicken Linien. Für den eigentlichen CAD-Viewport ist reines Metal besser.

## Architekturvorschlag

Eigene schlanke App, zusammengesetzt aus den Bausteinen oben. Nichts von Grund auf, aber auch kein Fork einer Komplettlösung,
weil keine davon die MCP-Steuerung von außen und den Live-Aufbau mitbringt.

```
Claude Code / Claude Desktop
        │  MCP (eine Verbindung)
        ▼
┌───────────────────────────── Kev CAD.app (SwiftUI) ─────────────────────────────┐
│  MCP-Server: Code, Kamera, Auswahl, Messen, Schnitt, Bild, Zeichnung, Druck      │
│  Viewer (Metal): Teilebaum, Kanten, Picking, Schnitt, Maße, Explosion            │
│  Projekte: Ordner mit model.py, Versionen, Exporte                               │
│  Renderings (RealityKit offscreen) · Datenblatt-PDF (PDFKit) · Druckdialog       │
└───────────────┬───────────────────────────────────────────────┬─────────────────┘
                │ Socket: GLB je Teil live, Mess-Anfragen        │ CLI / FTPS / MQTT
                ▼                                               ▼
   Kernel-Prozess (Python, build123d 0.13)              Bambu Studio CLI → P2S
   Sitzung, Messen, Lagerteile, Stückliste, Zeichnung
```

- **Live-Aufbau**: Jeder Schritt des Agenten (und jedes `show()`) schickt die geänderten Teile sofort als GLB in den Viewer.
- **Messen**: Der Viewer kennt Teil und Fläche unter dem Mauszeiger, der Kernel rechnet exakt (OCCT), die App zeichnet das Maß.
- **Agent sieht, was du siehst**: Auswahl im Viewer wird zur Referenz („diese Fläche“), Screenshot der aktuellen Ansicht.
- **Lagerteile**: eigener Katalog (Rohr Ø × Wand, Vierkantrohr, Alu-Profil, Holz, Platte, Schraube) mit Dichte, Farbe und
  Preis je Meter. `verbauen(teil, länge, gehrung)` legt das Bauteil an, die Stückliste fasst Zuschnitte, Gewicht und Kosten zusammen.

## Phasen

1. **Viewer-Test**: OCCTSwiftViewport und cad-studio bauen und mit der Outdoorküche vergleichen (Bildrate, Picking, Kanten).
   Danach steht die Viewer-Basis fest.
2. **MVP**: App mit Viewer, Kernel-Prozess, Live-Stream und MCP (Code ausführen, Kamera, Zoom auf Teil, Messen, Screenshot).
3. **Baugruppen und Lagerteile**: Teilebaum, Gelenke, Katalog, Stückliste.
4. **Datenblätter**: Ansichten mit verdeckten Kanten, Maße, Schriftkopf, Stückliste, PDF, Drucken.
5. **Renderings und Bambu**: RealityKit-Rendering, Slicen und Übergabe an Bambu Studio, optional Direktdruck im LAN.
