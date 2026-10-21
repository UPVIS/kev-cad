# Kev CAD · Bestandsführung mit Resten und Einkaufsliste

Stand: 21.10.2026 (Kevins Wunsch vom selben Tag). Baut auf Phase 2 (Lagerkatalog, Stückliste, Zuschnitt) und Phase 3
(Zukaufteile) auf. Gestartet am selben Abend auf Zweig `bestand`, erste Stufe Stangen, Platten, Stückgut; Vertrag in
[BESTAND.md](BESTAND.md).

## Ziel

Kev CAD weiß je Projekt, was Kevin für dieses Projekt tatsächlich da hat (Kevin: individuell nur für das jeweilige
Projekt, nicht projektübergreifend): ganze Stangen, Reste mit ihrer Länge, Platten und Plattenreste,
Schrauben und Kleinteile, Zukaufteile, Filament. Der Zuschnitt nimmt zuerst passende Reste, dann ganze Stangen, und
Kev CAD sagt klar, was für das aktuelle Projekt nachgekauft werden muss, mit Menge, Preis und Bezugsquelle. Nach dem
Bauen bucht Kevin mit einem Klick ab; die neuen Reste kommen von selbst in den Bestand.

**Fertig, wenn:**

1. Kevin trägt ein: „ALFER-Rohr 12 × 1: 2 ganze Stangen, Reste 430, 610 und 180 mm“. Der Bestand zeigt das je Lagerteil.
2. Die Stückliste des Kugelschiebers zeigt im Zuschnitt, welche Stücke aus welchem Rest und welcher Stange kommen,
   welche neuen Reste entstehen und wie viel Verschnitt bleibt.
3. Darunter steht die Einkaufsliste: „1 Stange ALFER-Rohr 12 × 1 (1 m), 4 Flügelmuttern M4, 120 g PETG“, mit Preis,
   Link und Gesamtsumme; exportierbar als CSV oder Text zum Weiterleiten.
4. „Gebaut“ bucht alles ab, legt die neuen Reste an und lässt sich rückgängig machen.

## Entscheidungen (Vorschlag)

| Nr. | Entscheidung | Begründung |
|---|---|---|
| S1 | **Bestand getrennt vom Katalog:** eigene Datei `~/Library/Application Support/de.upvis.kevcad/bestand.json`, je Lagerteil-, Zukaufteil- bzw. Material-id; der Katalog bleibt die Beschreibung, der Bestand die Menge | Katalog und Bestand ändern sich unterschiedlich oft; mitgelieferte Einträge bleiben unberührt |
| S2 | **Mengen je Art:** Stangenware = ganze Stangen (Anzahl, Länge) plus Reste (Liste von Längen mit Kennung, optional Lagerort); Platten = ganze Platten plus Reste (Rechtecke); Stückgut = Anzahl; Filament = Gramm je Spule, Material und Farbe | Deckt Kevins Werkstatt ab, ohne Lagerverwaltung zu spielen |
| S3 | **Zuschnitt mit Resten zuerst:** Stücke absteigend, zuerst in den kleinsten passenden Rest, dann in ganze Stangen; danach Verbesserung über ein kleines Optimierungsproblem (scipy `milp`, für Werkstattgrößen in Millisekunden); Ziel: wenig neue Stangen, wenig Verschnitt, brauchbare Reste lieber lang als viele kurze | Das klassische Zuschnittproblem, mit Resten als erstem Lager |
| S4 | **Mindestrestlänge:** Reste unter einer einstellbaren Länge (Standard 100 mm, je Lagerteil änderbar) gelten als Verschnitt und kommen nicht in den Bestand | Sonst füllt sich der Bestand mit Abfall |
| S5 | **Platten 2D:** Zuschnitt aus Plattenresten und ganzen Platten mit Guillotine-Schnitten (Kreissäge), Sägeblattbreite berücksichtigt | Wie Kevin tatsächlich schneidet |
| S6 | **Einkaufsliste:** Fehlmenge je Position, aufgerundet auf Kaufeinheiten (Stange, Platte, Packung, Spule), Preis mit Stand aus dem Katalog, Link aus dem Zukaufteil bzw. einer `bezugsquelle` am Lagerteil; Summe; Export als CSV und als Text | „Was muss ich nachkaufen“ ohne Rechnen |
| S7 | **Reservieren und Abbuchen:** Ein Projekt reserviert, was sein Zuschnitt verplant; „Gebaut“ bucht ab und legt neue Reste an; jede Buchung im Protokoll und rückgängig machbar | Bestand bleibt ehrlich, auch bei mehreren Projekten |
| S8 | **Eingabe:** Fenster „Bestand“ (im Lagerkatalog) mit schnellem Erfassen („+1 Stange“, „Rest 430 mm“); über MCP darf Claude Bestand nur nach Kevins Angabe eintragen und nennt jede Änderung; später Erfassen per EAN-Scan auf dem iPhone | Schnell, nachvollziehbar, nichts wird erfunden |
| S9 | **Optional streng:** je Projekt „nur aus Bestand bauen“, dann ist eine Fehlmenge ein Hinweis bzw. Befund statt nur eine Zeile auf der Einkaufsliste | Für Projekte, bei denen nichts gekauft werden soll |

## Arbeitspakete

| Paket | Inhalt |
|---|---|
| S-K | `bestand.json` mit Format und Prüfung, Zuschnitt mit Resten (1D und Platten), Einkaufsliste, Reservierung, Buchungen mit Protokoll und Rückgängig, Erweiterung von BOM und Protokoll (additiv), MCP `bestand_liste`, `bestand_eintragen`, `einkaufsliste`, `gebaut_buchen` |
| S-A | Fenster „Bestand“ mit schnellem Erfassen, Zuschnittansicht (Rest und Stange farbig, neue Reste markiert), Einkaufsliste mit Export und Teilen, Dialog „Gebaut“ mit Vorschau der Buchung |

## Zu beachten

- Startet nach Phase 3 (Zukaufteile gehören in den Bestand) oder parallel dazu mit Stangen, Platten und Stückgut.
- Filamentbestand passt zur Live-Druckvorschau ([PLAN-DRUCKVORSCHAU.md](PLAN-DRUCKVORSCHAU.md)): Verbrauch je Druckteil
  kommt von dort.
- Etiketten für Reste (Kennung, Länge, Material) gehören zu Phase 6 (Drucken).
