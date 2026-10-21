# Konstruktionsregeln und Design-Review (Kevin, 21.10.2026, gilt immer)

Zusatz zum Skill `kev-cad`. Gilt für jedes neue Design und jede Änderung, für Gestaltungselemente genauso wie für ganze
Baugruppen. Optimiert wird für **Einzelstücke und kleine Stückzahlen**: der Aufwand für Kevin zählt (Druckzeit,
Fehldruckrisiko, Nacharbeit, Beschaffung, Montage, Reparatur), nicht Werkzeugkosten einer Serie.

Notwendige Funktionen, Schnittstellen und Sicherheitsanforderungen bleiben immer erhalten. Fehlende Angaben und
Annahmen werden ausdrücklich gekennzeichnet. Schätzungen heißen Schätzung. Keine geprüfte Festigkeit, Sicherheit oder
Druckbarkeit behaupten ohne Nachweis (Rechnung, Prüfung in Kev CAD, Probedruck, Versuch).

Keine universellen Grenzwerte für Wandstärken, Überhangwinkel oder Passungsspiel: konkrete Werte immer aus Verfahren,
Material, Maschine und Belastung begründen. Die Zahlen für Kevins Drucker (Bambu Lab P1P, offen) stehen mit Quellen in
[3d-druck.md](3d-druck.md); sie sind Ausgangswerte, keine Nachweise.

## Die 15 Regeln

1. **Anforderungen vor Geometrie.** Funktion, Belastungen, Bauraum, Schnittstellen, Umgebung und Lebensdauer klären.
   Notwendige Anforderungen von Gewohnheiten und optionalen Wünschen trennen. Fehlt etwas Wesentliches, Kevin fragen
   statt raten; was angenommen wird, steht als Annahme im Bericht und als Kommentar in model.py.
2. **Das Wirkprinzip hinterfragen.** Vor Detailverbesserungen prüfen, ob eine einfachere Geometrie, Verbindung oder
   Mechanik dieselbe Aufgabe erfüllt. Standardteile (Lagerkatalog, Zukaufteile) und andere Fertigungsverfahren (Säge und
   Bohrer statt Druck, Rohr statt Druckteil) mit betrachten.
3. **Weglassen vor optimieren.** Unnötige Bauteile, Features, Verbindungen und Bearbeitungsschritte entfernen. Jedes
   Element braucht einen nachvollziehbaren Nutzen. Keine Komplexität für hypothetische spätere Anforderungen.
4. **Den gesamten Aufwand bewerten.** Material, Druckdauer, Support, Fehldruckrisiko, Nacharbeit, Zukaufteile, Montage
   und Reparatur. Weniger Material oder weniger Einzelteile heißt nicht automatisch weniger Aufwand.
5. **Bewusst zusammenfassen oder aufteilen.** Funktionen integrieren, wenn dadurch Aufwand entfällt. Teilen, wenn
   Druckorientierung, Materialwahl, Supportvermeidung oder Austauschbarkeit dadurch deutlich besser werden.
6. **Material nach Einsatz auswählen.** Temperatur, Feuchtigkeit, UV, Chemikalien, Verschleiß, Dauerlast und wechselnde
   Belastungen; Kriechen und Alterung einbeziehen (z. B. PLA kriecht unter Dauerlast und erweicht ab etwa 55 °C).
7. **Kräfte sinnvoll führen.** Unnötige Hebelarme verkürzen, Kerben und abrupte Querschnittswechsel vermeiden. Rippen,
   geeignete Querschnitte, Übergangsradien und größere Auflageflächen vor pauschaler Materialverdickung prüfen.
   Festigkeit und Steifigkeit unterscheiden.
8. **Druckorientierung früh festlegen.** Belastbarkeit, Maßhaltigkeit, Oberflächen, Support und Druckdauer gemeinsam
   abwägen. Bei FDM keine Belastung, die Schichten auseinanderzieht.
9. **Geometrie druckgerecht gestalten.** Problematische Überhänge, lange Brücken und filigrane freistehende Elemente
   reduzieren. Bettkontakt, Verzug und Supportzugänglichkeit prüfen. Fasen und selbsttragende Konturen nutzen, wo
   sinnvoll. Bei Hohlräumen an die Entfernung von Support denken.
10. **Wandstärken gezielt auslegen.** Wände und Details an Belastung, Material und Prozessauflösung anpassen. Bei FDM
    zuerst Wandlinien und lokale Verstärkungen prüfen, dann erst Infill. Druckbare Mindeststärke ist kein
    Tragfähigkeitsnachweis.
11. **Passungen realistisch gestalten.** Benötigtes Spiel und zulässige Abweichung festlegen. Schrumpfung,
    Druckrichtung, Nachbearbeitung und Toleranzketten berücksichtigen. Kritische Passungen mit kleinen Probedrucken
    absichern (Probekörper als eigenes kleines Druckteil vorschlagen).
12. **Verbindungen vereinfachen.** Wenige gängige Schraubengrößen und gut verfügbare Normteile. Schrauben, Muttern,
    Gewindeeinsätze, Klebungen oder Rastverbindungen nach Belastung und erforderlicher Demontierbarkeit wählen.
13. **Montage und Wartung mitkonstruieren.** Werkzeugzugang, Einführfasen, eindeutige Positionierung, einfache
    Montagereihenfolge. Verwechslungen, schwer zugängliche Befestigungen und aufwendigen Austausch von Verschleißteilen
    vermeiden.
14. **Fehler und Versagen berücksichtigen.** Wahrscheinliche Druck-, Montage- und Bedienfehler und ihre Folgen prüfen.
    Zugängliche scharfe Kanten und Quetschstellen entschärfen. Sicherheitsrelevante Änderungen anhand geeigneter
    Nachweise bewerten.
15. **Einfach und überprüfbar abschließen.** CAD-Geometrie, Parameter und Abhängigkeiten nachvollziehbar halten.
    Einheiten, geschlossene Volumen, Kollisionen und Slicer-Vorschau prüfen. Kritische Eigenschaften durch passende
    Berechnungen oder reale Versuche validieren.

## So setzt Kev CAD die Regeln um

| Regel | Werkzeug in Kev CAD |
|---|---|
| 1 Anforderungen | Kopfkommentar in model.py mit Anforderungen, Annahmen (markiert) und offenen Fragen; Parameter mit Grenzen |
| 2, 3, 5, 12 Prinzip, Weglassen, Verbindungen | Lagerkatalog (`stock_search`), Normteile, Zukaufteile; Zwangsbedingungen für Verbindungen |
| 4 Gesamtaufwand | Stückliste (`bom`) mit Kosten, Zuschnitt und Verschnitt, Druckteile mit Filament; später Druckvorschau mit Druckzeit |
| 6, 8, 9, 10, 11 Material, Orientierung, Druck, Wände, Passungen | [3d-druck.md](3d-druck.md) und die Druckprüfung: läuft bei jedem `run` für jedes `lager.druckteil` mit (Befunde `druck_*`, Ausrichtung mit Begründung im Laufergebnis); `druckpruefung` liefert die Einzelheiten |
| 7 Kräfte | Prüfung Standsicherheit; später Statik (PLAN-STATIK.md); bis dahin Handrechnung als Schätzung kennzeichnen |
| 13 Montage | Prüfung Einbaubarkeit, `check_motion.py` und `bewegungen.json`, Werkzeugzugang |
| 14 Fehler, Quetschstellen | Bewegungsraum über den ganzen Weg, scharfe Kanten an Griffstellen brechen |
| 15 Überprüfbar | Kollisionsprüfung bei jedem Lauf, `check_interference.py --kontakte`, Meilenstein mit Beschreibung |

## Beim Konstruieren

- Vor der ersten Geometrie Regel 1 abarbeiten. Fehlt Wesentliches (Last, Umgebung, Schnittstelle), erst fragen.
- Bei jedem neuen Bauteil kurz Regeln 2, 3 und 5 durchgehen: Gibt es ein Standardteil? Muss es das Teil geben? Ist
  Zusammenfassen oder Teilen besser?
- Druckteile von Anfang an mit Orientierung, Wandlinien und Passungen nach 3d-druck.md. Die Druckprüfung läuft bei
  jedem `run` mit: Fehler (Bauraum, Harz, CF ohne gehärtete Düse) und Warnungen beheben, Hinweise abwägen; die
  Einzelheiten (Ausrichtung, Kennzahlen, alle Hinweise) mit `druckpruefung`.
- Im Bericht an Kevin: Annahmen, offene Fragen, was nachgewiesen ist und was nur geschätzt.

## Design-Review („prüfe das Design kritisch“)

Auf Kevins Wunsch, am Ende jeder größeren Aufgabe als Kurzfassung (die drei wichtigsten Punkte) und vor einem
Meilenstein „fertig“ als volle Fassung. Das vorliegende Design kritisch prüfen und hinsichtlich Einfachheit,
Zuverlässigkeit, Fertigung, Montage und Gesamtaufwand verbessern; auch das zugrunde liegende Konzept hinterfragen.
Daten zuerst aus Kev CAD holen (`parts`, `bom`, Prüfbefunde, Druckprüfung, Bewegungsprüfung), dann bewerten.

Ausgabe:

1. **Die fünf wichtigsten Verbesserungen**, priorisiert nach Nutzen und Aufwand, jeweils:
   Problem → konkrete Änderung → erwarteter Nutzen → Nachteil oder Zielkonflikt → erforderliche Prüfung.
2. **Fehlende Angaben und Annahmen**, ausdrücklich gekennzeichnet.
3. Falls sinnvoll: eine **minimal veränderte Variante** und ein **vereinfachtes neues Konzept**, mit begründeter
   Empfehlung. Varianten in Kev CAD als Variante anlegen, nicht den Hauptstand überschreiben.

Schätzungen kennzeichnen. Keine geprüfte Festigkeit, Sicherheit oder Druckbarkeit behaupten ohne Nachweis.
