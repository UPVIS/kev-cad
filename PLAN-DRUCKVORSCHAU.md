# Kev CAD · Live-Druckvorschau für 3D-Druckteile

Stand: 21.10.2026 (Kevins Wunsch vom selben Tag). Projekt für später; gehört zu den 3D-Druck-Regeln (Druckprüfung) und
zu Phase 8 (Druck auf dem Bambu-Drucker).

## Ziel

Neben der Stückliste steht immer eine Druckvorschau, die sich nach jedem Lauf von selbst aktualisiert: wie viel
Filament von jeder Sorte (g, m, €), wie lange jeder Druck dauert, wie viele Platten es werden und welche Teile
zusammen auf eine Platte passen, mit empfohlenen Einstellungen (Schichthöhe, Wände, Füllung, Stützen, Ausrichtung) und
allen Hinweisen, die für einen gelungenen Druck zählen. So ist immer klar, was das gerade Konstruierte im Druck
bedeutet und kostet.

**Fertig, wenn:**

1. Nach jedem Lauf zeigt die Vorschau in unter einer Sekunde: je Material Gramm, Meter und Euro, Druckzeit je Platte
   und gesamt, Anzahl Platten, Teile je Platte.
2. Im Hintergrund rechnet der echte Slicer (Bambu Studio mit Kevins Drucker- und Filamentprofilen) nach und ersetzt die
   Schätzung durch genaue Werte; die schnelle Schätzung lernt aus jedem Abgleich.
3. Acht gleiche Halter werden automatisch so viele wie möglich auf eine Platte gelegt; die Vorschau zeigt die
   Anordnung.
4. Je Teil eine Empfehlung mit Begründung, z. B. „tragend: 4 Wände, 25 % Gyroid, liegend drucken, Last längs der
   Schichten“, und Warnungen wie „braucht Stützen unter der Lasche“, „PETG vorher trocknen“, „ABS auf offenem Drucker
   verzieht sich“.
5. Ein Klick exportiert die angeordneten Platten als 3MF für Bambu Studio (Grundlage für Phase 8).

## Was schon da ist (geprüft am 21.10.2026)

- **Bambu Studio 2.07** ist installiert und lässt sich ohne Fenster bedienen: `--slice`, `--arrange` (automatisch
  anordnen, auch mit Drehen), `--orient` (automatisch ausrichten), `--export-slicedata`. Damit kommen Druckzeit und
  Filament aus demselben Slicer, mit dem Kevin druckt.
- **Profile:** In Bambu Studio ist ein **Bambu Lab P1P 0.4** eingerichtet (dazu P1P 0.2 und H2C), eigenes Filament
  „Amazon Basics PLA“. Der Katalog kennt Dichte und Preis je kg der Druckmaterialien.
- **Druckregeln und Druckprüfung** baut der Strang 3D-Druck (`kevcad_kernel/druck/`, `skill/kev-cad/3d-druck.md`).

## Entscheidungen (Vorschlag)

| Nr. | Entscheidung | Begründung |
|---|---|---|
| V1 | **Zwei Stufen:** eine eigene Schätzung live nach jedem Lauf (Volumen, Oberfläche, Wände, Decken und Böden, Füllung, Stützen grob, Schichtzahl), dazu der echte Slicer im Hintergrund mit Zwischenspeicher je Teilstand und Einstellung | Sofort eine Zahl, kurz danach die genaue |
| V2 | **Die Schätzung lernt vom Slicer:** Zeit und Material als einfaches Modell (Extrusionsvolumen, Wege, Schichtwechsel) mit Faktoren je Drucker und Profil, nach jedem Abgleich nachgestellt | Live-Werte werden mit der Zeit fast so genau wie der Slicer |
| V3 | **Anordnen auf der Platte:** schnell über die Grundflächen (konvexe Hülle, Drehen in 90°-Schritten, Abstand und Sperrzonen der Platte), genau über `--arrange` des Slicers; gleiche Teile so oft wie möglich auf eine Platte; Plattenzahl und Gesamtzeit inklusive Plattenwechsel | Das, was Kevin „wie viele passen parallel auf eine Platte“ nennt |
| V4 | **Empfehlungen aus Zweck und Last:** Teile tragen einen Zweck (`zier`, `funktion`, `tragend`, `bewegt`, `aussen`), daraus Wände, Füllung, Muster, Schichthöhe, Material; Ausrichtung nach Festigkeit und Stützenbedarf; später mit Lasten aus der Statik | Füllung und Wände nach Sinn, nicht nach Gefühl |
| V5 | **Weitere Faktoren, die zählen:** Stützen (Material, Zeit, Nacharbeit), Brim bei kleiner Grundfläche oder hohen Teilen, Farbwechsel und Spülmenge beim AMS, Trocknen (PETG, TPU, PA), Verzug offener Drucker bei ABS/ASA, Bauraum, Erfolgsrisiko als Aufschlag, Strom (Leistung × Zeit × Preis je kWh), Düsenverschleiß bei CF-Filamenten | Realistische Einschätzung statt reiner Filamentkosten |
| V6 | **Kosten mit Herkunft:** Filamentpreis aus dem Katalog bzw. aus Kevins Filamentprofil, Strompreis als Einstellung, alles mit Stand-Datum | Wie bei den Lagerteilen |
| V7 | **Anzeige:** Panel „Druck“ neben der Stückliste (je Material, je Platte, je Teil, Hinweise als Ampel), Plattenansicht mit der Anordnung, MCP `druckvorschau`; 3MF-Export der Platten | Immer sichtbar, auch für den Agenten |

## Arbeitspakete

| Paket | Inhalt |
|---|---|
| V-K | Schätzung, Anordnen, Empfehlungen, Bambu-Studio-Anbindung im Hintergrund (Profile, 3MF, Auswertung), Zwischenspeicher, Abgleich, MCP |
| V-A | Panel „Druck“, Plattenansicht, Hinweise, 3MF-Export |

## Offen

- Welcher Drucker: In den Plänen steht bisher P2S, in Bambu Studio ist ein P1P eingerichtet. Bauraum (256 mm³) und
  Düse sind gleich, aber der P1P ist offen (kein Gehäuse), das ändert Empfehlungen für ABS/ASA und die Zeiten. Bitte
  von Kevin bestätigen; beide Profile sollen wählbar sein.
