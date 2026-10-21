# Kev CAD · Roadmap

Stand: 22.10.2026. Jede Phase entsteht auf einem eigenen Zweig und kommt erst nach der Abnahme auf `main`; von dort
installiert das automatische Update sie in den Tools-Stapel (siehe CLAUDE.md, Abschnitt Installation).

| Phase | Inhalt | Plan | Stand |
|---|---|---|---|
| MVP | Viewer, Kernel, Live-Aufbau, Messen, MCP, Export | [PLAN-MVP.md](PLAN-MVP.md) | fertig, installiert |
| – | Steuerung wie Blender, Neustart nach Update | – | fertig, installiert (Build 24) |
| 2 | Lagerteile, Materialien, Stückliste, Zuschnitt, Inventar-Regel | [PLAN-PHASE2.md](PLAN-PHASE2.md) | fertig, installiert (Build 45); im Kugelschieber ist die Inventar-Regel aus, bis Phase 3 die Zukaufteile bringt |
| 3 | Zukaufteile per Link, Artikelnummer oder EAN, Hersteller-CAD einbetten | [PLAN-PHASE3-ZUKAUF.md](PLAN-PHASE3-ZUKAUF.md) | fertig, installiert (Build 148): Dialog „Zukaufteil hinzufügen“, Hersteller-CAD aus den Downloads, Ersatzkörper, Stückliste mit Preis und Link; TraceParts wartet auf Kevins Schlüssel |
| 4 | Foto und Video als Referenz (Object Capture, Foto mit Live-Differenz, Abweichung) | [PLAN-PHASE4-REFERENZ.md](PLAN-PHASE4-REFERENZ.md) | Vorarbeit läuft; `tools/capture` (Video → Netz, Kameras, Maße) ist auf `main`, noch nicht in der App |
| 5 | Kamerasimulation (Sensor, Objektiv, Blick durch die Kamera, Kamerabild) und Animation (Bewegen, Rollen, Gelenke, Kollision, Video) | [PLAN-PHASE5-KAMERA-ANIMATION.md](PLAN-PHASE5-KAMERA-ANIMATION.md) | fertig, installiert (Build 89): Kameras mit Taste 0 und Kamerabild, Animation mit Zeitleiste, Kollision über den Ablauf, Video, Kamera fährt mit |
| – | 3D-Druck-Konstruktionsregeln und Druckprüfung | `skill/kev-cad/3d-druck.md` | installiert (Build 156): Regelwerk für den P1P, Druckprüfung bei jedem Lauf, MCP `druckpruefung` |
| – | Zwangsbedingungen wie in CAD-Programmen: auf, konzentrisch, bündig, Abstand, Winkel, Gelenke mit Freiheitsgraden, Maß- und Parameterbedingungen, Löser und Prüfung | [PLAN-BEDINGUNGEN.md](PLAN-BEDINGUNGEN.md) | installiert (Build 114): Löser, Gelenke mit Bereich, Bewegungsraum- und Befestigungsprüfung, Symbole im Viewer |
| – | Prüfung jeder Konstruktion: Durchdringung, Schweben, Standsicherheit, Einbaubarkeit (Montagereihenfolge, Werkzeugzugang), Mehrfachansichten zur Bildanalyse | – | Stufe 1 (Durchdringung) installiert in Build 73, Stufe 2 (Schweben, Standsicherheit, Einbaubarkeit, Mehrfachansichten) in Build 178; Nachbesserung am 22.10.2026 installiert: Gewindeeingriff auch für Zollgewinde, Griffraum für Flügelschrauben, Kulisse (`kulisse=True`), Zukaufteile als gelieferte Baugruppe, schneller Bewegungsraum über Läufe hinweg |
| – | Vermessung mit wenigen Bildern, Video-Rekonstruktion (Vorarbeit Phase 4) | PLAN-PHASE4-REFERENZ.md | beide fertig und auf `main`, noch nicht in der App: Video-Rekonstruktion `tools/capture` (gut 1 min, Maße 1–3 %), Vermessung mit wenigen Bildern `fotomess/` (1–3 Bilder unter 5 s, 22 Fotos in 22 s, rund 40- bis 70-mal schneller als fotocad) |
| – | Bestandsführung: ganze Stangen, Reste, Platten, Stückgut, Filament je Lagerteil; Zuschnitt nimmt zuerst Reste; Einkaufsliste mit Preis und Link; „Gebaut“ bucht ab und legt neue Reste an | [PLAN-BESTAND.md](PLAN-BESTAND.md), Vertrag BESTAND.md (Zweig `bestand`) | Stufe 1 installiert (Build 178): Bestand je Projekt für Stangen, Platten, Stückgut, Zuschnitt mit Resten, Einkaufsliste, Gebaut-Buchung; Stufe 2 (Zukaufteile, Filament) offen |
| – | Versionen, Meilensteine und Varianten: Versionsleiste mit Vorschaubild und Kennzahlen, Wiederherstellen mit einem Klick, Vergleichen (Parameter, Stückliste, Geometrie überlagert, Code), Varianten | [PLAN-VERSIONEN.md](PLAN-VERSIONEN.md) | installiert am 22.10.2026: Versionsleiste (⌥⌘V), Meilenstein (⌘S), Vergleich mit Geisterkörper (⌥⌘U), Wiederherstellen, Varianten in der Titelleiste, MCP `versionen`, `meilenstein`, `variante`; alte Stände werden beim ersten Öffnen übernommen |
| 6 | Technische Zeichnungen (automatisch bemaßt, bearbeitbar), Bauplan als Schritt-für-Schritt-Anleitung mit Simulation, Berichte (Stückliste, Einkaufsliste, Zuschnitt) als PDF, Drucken | [PLAN-PHASE6-DOKUMENTE.md](PLAN-PHASE6-DOKUMENTE.md), [DOKUMENTE.md](DOKUMENTE.md) | gestartet am 22.10.2026: Recherche fertig ([RECHERCHE-PHASE6.md](RECHERCHE-PHASE6.md), Zweig `phase6`), Vertrag 1.1, Kernel-Stränge Zeichnung und Bauplan laufen, App folgt |
| 7 | Renderings | PLAN-MVP.md Abschnitt 15 | offen |
| 8 | Druck auf dem Bambu Lab P1P (für den P1P neu zu prüfen: LAN-Modus, Profile) | PLAN-MVP.md Abschnitt 15, RECHERCHE.md | offen |
| später | Live-Druckvorschau: Filament je Sorte, Druckzeit je Platte, Teile je Platte (automatisch angeordnet), empfohlene Einstellungen, Kosten, Hinweise; schnelle Schätzung live, Bambu Studio genau im Hintergrund | [PLAN-DRUCKVORSCHAU.md](PLAN-DRUCKVORSCHAU.md) | geplant |
| später | Statik, Stabilität und Simulation: Belastungsszenarien, Stabwerk aus Lagerteilen (PyNite), Dynamik mit MuJoCo, Festkörper-FEM (Gmsh, scikit-fem), klare Urteile inkl. „überdimensioniert“ | [PLAN-STATIK.md](PLAN-STATIK.md) | geplant, startet nach Prüfungen, Bedingungen und Animation |
| – | Live-Ansicht auf dem iPhone in der VoiceBridge-App: Szene live sehen, drehen, ein- und ausblenden, fokussieren, isolieren, mit dem Agenten weiterarbeiten, zwei Richtungen synchron, startet von selbst, sobald ein Agent in Kev CAD arbeitet | [PLAN-IPHONE-LIVE.md](PLAN-IPHONE-LIVE.md), [MIRROR.md](MIRROR.md) | Spiegel-Dienst in Kev CAD installiert (Build 104), iPhone-Ansicht bei VoiceBridge fertig; die Übertragung (VoiceBridge) fehlt noch |

## Offene Zuarbeit von Kevin

- TraceParts-API-Schlüssel beantragen (für Phase 3, Prüfung dauert einige Tage).
- Ein Probevideo eines matten Gegenstands plus ein nachgemessenes Maß (für Phase 4).
- Zwei, drei echte Produktlinks aus dem Alltag (für Phase 3).
