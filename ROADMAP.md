# Kev CAD · Roadmap

Stand: 21.10.2026. Jede Phase entsteht auf einem eigenen Zweig und kommt erst nach der Abnahme auf `main`; von dort
installiert das automatische Update sie in den Tools-Stapel (siehe CLAUDE.md, Abschnitt Installation).

| Phase | Inhalt | Plan | Stand |
|---|---|---|---|
| MVP | Viewer, Kernel, Live-Aufbau, Messen, MCP, Export | [PLAN-MVP.md](PLAN-MVP.md) | fertig, installiert |
| – | Steuerung wie Blender, Neustart nach Update | – | fertig, installiert (Build 24) |
| 2 | Lagerteile, Materialien, Stückliste, Zuschnitt, Inventar-Regel | [PLAN-PHASE2.md](PLAN-PHASE2.md) | gebaut und abgenommen auf Zweig `phase2`, wartet auf Übernahme nach `main` |
| 3 | Zukaufteile per Link, Artikelnummer oder EAN, Hersteller-CAD einbetten | [PLAN-PHASE3-ZUKAUF.md](PLAN-PHASE3-ZUKAUF.md) | geplant, startet nach Phase 2 parallel zu Phase 4 |
| 4 | Foto und Video als Referenz (Object Capture, Foto mit Live-Differenz, Abweichung) | [PLAN-PHASE4-REFERENZ.md](PLAN-PHASE4-REFERENZ.md) | geplant, startet nach Phase 2 parallel zu Phase 3 |
| 5 | Kamerasimulation (Sensor, Objektiv, Blick durch die Kamera, Kamerabild) und Animation (Bewegen, Rollen, Gelenke, Kollision, Video) | [PLAN-PHASE5-KAMERA-ANIMATION.md](PLAN-PHASE5-KAMERA-ANIMATION.md) | in Arbeit (zwei Stränge parallel, auf Basis von `phase2`) |
| – | 3D-Druck-Konstruktionsregeln und Druckprüfung | – | in Arbeit (eigener Strang) |
| – | Prüfung jeder Konstruktion: Durchdringung, Schweben, Standsicherheit, Einbaubarkeit (Montagereihenfolge, Werkzeugzugang), Mehrfachansichten zur Bildanalyse | – | in Arbeit (eigener Strang auf Basis von `phase2`) |
| – | Vermessung mit wenigen Bildern, Video-Rekonstruktion (Vorarbeit Phase 4) | PLAN-PHASE4-REFERENZ.md | in Arbeit (zwei Stränge) |
| 6 | Datenblätter und Zeichnungen als PDF, Drucken | PLAN-MVP.md Abschnitt 15 | offen |
| 7 | Renderings | PLAN-MVP.md Abschnitt 15 | offen |
| 8 | Druck auf dem Bambu Lab P2S | PLAN-MVP.md Abschnitt 15, RECHERCHE.md | offen |

## Offene Zuarbeit von Kevin

- TraceParts-API-Schlüssel beantragen (für Phase 3, Prüfung dauert einige Tage).
- Ein Probevideo eines matten Gegenstands plus ein nachgemessenes Maß (für Phase 4).
- Zwei, drei echte Produktlinks aus dem Alltag (für Phase 3).
