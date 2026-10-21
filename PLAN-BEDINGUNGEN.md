# Kev CAD · Zwangsbedingungen (Constraints)

Stand: 21.10.2026 (Kevins Wunsch vom selben Tag). Eigener Strang auf Basis von `main`, gehört zu den Prüfungen
(Durchdringung, Schweben, Kippen, Einbaubarkeit) und zur Animation (Gelenke).

## Ziel

Wie in klassischen CAD-Programmen hängen Teile über **Bedingungen** zusammen statt über frei gewählte Koordinaten:
Fläche auf Fläche, konzentrisch, bündig, Abstand, Winkel, Gelenk. Dazu Maß- und Parameterbedingungen: Grenzen, abgeleitete
Maße, Mindestspiel, Mindestwand. Kev CAD prüft sie nach jedem Lauf; verletzte Bedingungen sind Befunde wie eine
Durchdringung. So fallen Fehler auf, bevor sie entstehen: Ändert sich die Rollenhöhe, wandert der Rahmen mit, statt in
der Luft zu hängen oder in die Rolle zu stecken.

Kevin, 21.10.2026: „Das hilft ja gewisse Fehler schon vorab zu vermeiden … und das muss der Agent noch bei der
Erstellung alles berücksichtigen.“

**Fertig, wenn:**

1. Im Kugelschieber sitzt der Rahmen über `auf(rahmen.unten, rolle.oben)` auf den Rollen; ändert Kevin die Rollenhöhe,
   folgt der Rahmen, und die Prüfung bleibt grün.
2. Eine Schraube über `in_bohrung(schraube, bohrung)` steckt konzentrisch und liegt mit dem Kopf auf; ist die Bohrung zu
   klein oder versetzt, meldet der Lauf den Befund mit Soll, Ist und Lösung.
3. `param("wand", 2.0, min=1.2)` lehnt 0,8 ab; `spiel(deckel, gehaeuse, min=0.2)` meldet 0,1 mm als Befund.
4. Gelenke (`drehgelenk`, `schiebegelenk`) tragen ihre Freiheitsgrade; die Animation bewegt Teile nur entlang dieser
   Freiheitsgrade, die Prüfung testet den ganzen Weg.
5. Im Viewer: Bedingungen als Symbole an den Teilen (wie in CAD-Programmen), verletzte rot, Liste im Inspektor; über MCP
   `bedingungen` mit Stand je Bedingung.

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| B1 | **Grundlage sind die Joints von build123d** (`RigidJoint`, `RevoluteJoint`, `LinearJoint`, `CylindricalJoint`, `BallJoint`) für Verbindungsstellen und Freiheitsgrade; Kev CAD legt eine deutsche, schlanke API darüber | Vorhandene, getestete Mechanik; Gelenke und Animation sprechen dieselbe Sprache |
| B2 | **Bezüge über Namen, nicht über Flächennummern:** Bezugsflächen, -achsen und -punkte werden benannt (`bezug(teil, "oben", flaeche)`, Bezugspunkte aus dem Katalog, Auswahl über Selektoren wie `faces().sort_by(Axis.Z)[-1]`) | Flächennummern ändern sich bei jeder Konstruktionsänderung |
| B3 | **Zwei Arten:** Montagebedingungen zwischen Teilen (`auf`, `buendig`, `konzentrisch`, `parallel`, `senkrecht`, `abstand`, `winkel`, `tangential`, `mittig`, `in_bohrung`) und Maßbedingungen (`param(…, min, max)`, `gleich`, `spiel`, `min_abstand`, `min_wand`) | Deckt ab, was CAD-Programme als Mates und Bemaßungsbedingungen kennen |
| B4 | **Platzieren durch Lösen, Prüfen nach dem Lauf:** `platziere(teil, auf(…), konzentrisch(…))` berechnet die Lage aus den Bedingungen (geschlossen für die häufigen Fälle, sonst kleinste Quadrate mit scipy); nach jedem Lauf prüft der Kernel alle Bedingungen gegen die tatsächliche Geometrie mit Toleranz | Der Agent setzt Teile so, wie man sie montiert; Abweichungen fallen sofort auf |
| B5 | **Unter- und Überbestimmung melden:** freie Freiheitsgrade eines Teils, das kein Gelenk ist, sind ein Hinweis; widersprüchliche Bedingungen ein Fehler mit den beteiligten Bedingungen | Wie die Statusanzeige „unterbestimmt / überbestimmt“ in CAD-Programmen |
| B6 | **Befunde im gemeinsamen Format der Prüfung** (`art: "bedingung"`, `teile`, `schwere`, `soll`, `ist`, `ort`, `loesung`); verletzte Bedingungen sperren den Export wie Durchdringungen | Eine Stelle für alle Befunde, eine Regel für den Agenten |
| B8 | **Bewegungsraum (Range of Motion) bei jedem Lauf:** jedes Gelenk mit Bereich wird über den ganzen Weg geprüft (Schritte, Hüllquader-Vorfilter, exaktes Schnittvolumen, gemeinsame Kollisionsfunktion mit der Animation); Bedienteile zusätzlich mit Freiraum für Finger bzw. Werkzeug; Befund mit freiem Bereich und blockierendem Teil. Vorbild: `kernel/tools/check_motion.py` und `<projekt>/bewegungen.json` | Kevin, 21.10.2026: Bedienteile, die an Teile stoßen, die man nicht wegschieben kann, sind ein Konstruktionsfehler |
| B9 | **Befestigung ist Pflicht:** jedes Teil hat mindestens eine Verbindung zu seinem Gegenstück (`verbinde(a, b, art="schraube" \| "klemmung" \| "steck" \| "formschluss" \| "kleben" \| "aufliegen", mit=[Schraube, Mutter …])`); die Prüfung kontrolliert, dass die Verbindung physisch da ist (Kontakt oder Spielpassung, Schraube durch fluchtende Bohrungen beider Teile, Kopf und Mutter liegen auf) und dass alle Teile über Verbindungen am Boden hängen | Kevin, 21.10.2026: Generierte Teile stehen oft einfach im Raum, ohne dass bedacht ist, wie sie montiert und befestigt werden |
| B7 | **Skizzen bleiben Code:** 2D-Skizzen sind in build123d schon parametrisch; ein Skizzen-Löser (z. B. planegcs aus FreeCAD) kommt nur, wenn sich das als nötig zeigt | Erst messen, dann einbauen |

## Umsetzung (eigener Strang)

- Kernel: `kevcad/bedingungen.py` (API für model.py), `kevcad_kernel/bedingungen/` (Löser, Prüfung, Freiheitsgrade),
  Einhängen in den Lauf nach RUN_END, Befunde zur Prüfung.
- Protokoll: Bedingungen je Teil mit Stand und Anzeigepunkten (additiv, PROTOCOL.md).
- App: Symbole am Teil, verletzte rot, Liste im Inspektor.
- MCP: `bedingungen` (Liste, Stand, Freiheitsgrade), Beschreibung in den Server-Anweisungen.
- Skill: „Teile über Bedingungen setzen“ als feste Regel neben Prüfungen, Druckregeln und Inventar-Regel.
- Abstimmung: Befundformat mit dem Strang Prüfungen, Gelenke und Freiheitsgrade mit dem Strang Animation.
