# Kev CAD · Roadmap

Stand: 21.10.2026. Jede Phase entsteht auf einem eigenen Zweig und kommt erst nach der Abnahme auf `main`; von dort
installiert das automatische Update sie in den Tools-Stapel (siehe CLAUDE.md, Abschnitt Installation).

| Phase | Inhalt | Plan | Stand |
|---|---|---|---|
| MVP | Viewer, Kernel, Live-Aufbau, Messen, MCP, Export | [PLAN-MVP.md](PLAN-MVP.md) | fertig, installiert |
| – | Steuerung wie Blender, Neustart nach Update | – | fertig, installiert (Build 24) |
| 2 | Lagerteile, Materialien, Stückliste, Zuschnitt, Inventar-Regel | [PLAN-PHASE2.md](PLAN-PHASE2.md) | fertig, installiert (Build 45); im Kugelschieber ist die Inventar-Regel aus, bis Phase 3 die Zukaufteile bringt |
| 3 | Zukaufteile per Link, Artikelnummer oder EAN, Hersteller-CAD einbetten | [PLAN-PHASE3-ZUKAUF.md](PLAN-PHASE3-ZUKAUF.md) | in Arbeit seit 21.10.2026 abends (Kernel und App parallel, Zweig `phase3`, Verträge stehen) |
| 4 | Foto und Video als Referenz (Object Capture, Foto mit Live-Differenz, Abweichung) | [PLAN-PHASE4-REFERENZ.md](PLAN-PHASE4-REFERENZ.md) | Vorarbeit läuft; `tools/capture` (Video → Netz, Kameras, Maße) ist auf `main`, noch nicht in der App |
| 5 | Kamerasimulation (Sensor, Objektiv, Blick durch die Kamera, Kamerabild) und Animation (Bewegen, Rollen, Gelenke, Kollision, Video) | [PLAN-PHASE5-KAMERA-ANIMATION.md](PLAN-PHASE5-KAMERA-ANIMATION.md) | in Arbeit (zwei Stränge parallel, auf Basis von `phase2`) |
| – | 3D-Druck-Konstruktionsregeln und Druckprüfung | – | in Arbeit (eigener Strang) |
| – | Zwangsbedingungen wie in CAD-Programmen: auf, konzentrisch, bündig, Abstand, Winkel, Gelenke mit Freiheitsgraden, Maß- und Parameterbedingungen, Löser und Prüfung | [PLAN-BEDINGUNGEN.md](PLAN-BEDINGUNGEN.md) | in Arbeit (eigener Strang) |
| – | Prüfung jeder Konstruktion: Durchdringung, Schweben, Standsicherheit, Einbaubarkeit (Montagereihenfolge, Werkzeugzugang), Mehrfachansichten zur Bildanalyse | – | in Arbeit (eigener Strang auf Basis von `phase2`) |
| – | Vermessung mit wenigen Bildern, Video-Rekonstruktion (Vorarbeit Phase 4) | PLAN-PHASE4-REFERENZ.md | Video-Rekonstruktion fertig (`tools/capture`, schnell gut 1 min, Maße 1–3 %), Vermessung mit wenigen Bildern in Arbeit |
| 6 | Datenblätter und Zeichnungen als PDF, Drucken | PLAN-MVP.md Abschnitt 15 | offen |
| 7 | Renderings | PLAN-MVP.md Abschnitt 15 | offen |
| 8 | Druck auf dem Bambu Lab P2S | PLAN-MVP.md Abschnitt 15, RECHERCHE.md | offen |
| später | Live-Druckvorschau: Filament je Sorte, Druckzeit je Platte, Teile je Platte (automatisch angeordnet), empfohlene Einstellungen, Kosten, Hinweise; schnelle Schätzung live, Bambu Studio genau im Hintergrund | [PLAN-DRUCKVORSCHAU.md](PLAN-DRUCKVORSCHAU.md) | geplant |
| später | Statik, Stabilität und Simulation: Belastungsszenarien, Stabwerk aus Lagerteilen (PyNite), Dynamik mit MuJoCo, Festkörper-FEM (Gmsh, scikit-fem), klare Urteile inkl. „überdimensioniert“ | [PLAN-STATIK.md](PLAN-STATIK.md) | geplant, startet nach Prüfungen, Bedingungen und Animation |
| – | Live-Ansicht auf dem iPhone in der VoiceBridge-App: Szene live sehen, drehen, ein- und ausblenden, fokussieren, isolieren, mit dem Agenten weiterarbeiten, zwei Richtungen synchron, startet von selbst, sobald ein Agent in Kev CAD arbeitet | [PLAN-IPHONE-LIVE.md](PLAN-IPHONE-LIVE.md), [MIRROR.md](MIRROR.md) | gestartet: Vertrag v1 steht, VoiceBridge baut die iPhone-Ansicht, Kev CAD den Spiegel-Dienst |

## Offene Zuarbeit von Kevin

- TraceParts-API-Schlüssel beantragen (für Phase 3, Prüfung dauert einige Tage).
- Ein Probevideo eines matten Gegenstands plus ein nachgemessenes Maß (für Phase 4).
- Zwei, drei echte Produktlinks aus dem Alltag (für Phase 3).
