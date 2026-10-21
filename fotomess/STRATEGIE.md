# fotomess · Ein parametrisches Modell aus wenigen Bildern vermessen

Stand: 21.10.2026. Prototyp für Kev CAD, Phase 4 (Foto und Video als Referenz). Ergebnisse und Laufzeiten stehen in
[BENCHMARK.md](BENCHMARK.md), dort auch die Rollwagen-Maße.

## Kurzfassung

Kevins bisheriges Verfahren (`fotocad`, an der Beelonia-Küche erprobt) vergleicht gerenderte Silhouetten mit dem
Foto und sucht mit Powell, also ohne Ableitungen: jede Auswertung ist ein ganzes GPU-Bild, ein Foto braucht einige
tausend Auswertungen. fotomess behält Kevins Modellanbindung (`fotocad.cad_netz`: Netz linear in den Maßen) und
ersetzt das Einpassen:

1. **Kanten statt Flächen.** Je Bild und Stufe wird einmal vorberechnet, wo die nächste Bildkante liegt
   (Distanztransformation mit Marken, getrennt nach Kantenrichtung, dazu der Maskenrand). Ein projizierter
   Modellkantenpunkt findet seinen Partner dann ohne Suche.
2. **Glattes Ausgleichsproblem.** Abstand Punkt zu Linie entlang der Modellnormale, robust (Cauchy), Zuordnung bei jeder
   Auswertung neu (ICP). Levenberg-Marquardt mit analytischen Ableitungen: Projektion, Kameralage, Maße (über die
   Netzableitungen), Gelenkwinkel (Haube, Lenkrollen). Unter 300 Unbekannte, direkt gelöst.
3. **GPU nur dort, wo sie messbar hilft:** Tiefenbild für die Sichtbarkeit der Kantenpunkte (alle 3 bis 4
   LM-Schritte, nicht bei jeder Auswertung) und ein Silhouetten-Atlas für die Grobsuche (bis 600 Kandidatenkameras
   in einem Zeichenpuffer). Das Lösen der Normalgleichungen braucht unter 1 % der Zeit; MLX oder Metal brächten dort
   nichts.
4. **Wenige Unbekannte, viel Vorwissen:** bekannte Maße fest (Maßstab), weiche Vorgaben für übliche Maße,
   Brennweite aus EXIF/QuickTime als Vorgabe, gemeinsame Brennweite aller Videobilder, Hauptpunkt in der Mitte, kleine
   Rollwinkel als Vorgabe, Gelenke je Bild.

Ergebnis an der Küche (Einzelheiten BENCHMARK.md): 1 Foto in rund 1,3 s, 22 Fotos in rund 22 s, etwa linear. Das
bisherige Verfahren braucht für ein Foto rund 60 s bei gleichem Start. Die Maße liegen im Mittel 12 bis 14 mm neben
der fotocad-Referenz, das ist die Größenordnung, mit der die Referenz selbst angegeben ist (Kameras tragen dort etwa
1 cm bei). Gemessen an Fotos, die nicht eingepasst wurden, erklären die Maße aus 5 Fotos die übrigen 17 Fotos so gut
wie die Referenzmaße (Abstand 0,1 Punkte Überdeckung).

Am Rollwagen (Handyvideo, echte Umgebung, Masken aus Apple Vision und Farbe): 2 Bilder in 2,2 s, 9 Bilder in 13 s.
Rollenhöhe 120,6 ± 3,2 mm (Annahme 128), Seitenhöhe Rahmen plus Rand 44 mm (Annahme 54), Steg 56,6 ± 0,9 mm
(Annahme 45); die Prüfmaße Breite und Raddurchmesser kommen innerhalb einer Sigma heraus, die Kameras stimmen mit
Apple Object Capture auf 0,8° und 14 mm überein.

## Ablauf

| Schritt | Was | Modul |
|---|---|---|
| Bilder | Foto: Arbeitskopie (Viertelgröße bei 24 MP). Video: bewerten (Schärfe, Kameraweg, Objekt ganz im Bild), n Bilder über den Weg verteilt wählen, in voller Größe holen | `video` |
| Masken | Studio: Schwelle 245 (wie fotocad). Umgebung: Apple Vision (`VNGenerateForegroundInstanceMaskRequest`, Neural Engine, rund 40 ms je 4K-Bild, Swift-Hilfe) plus Farbe für genaue Ränder, kleine Löcher zu | `masken` |
| Modell | build123d-Bauer -> Netz mit Ableitungen (einmalig, 1 + k Varianten parallel, zwischengespeichert), Kanten-Topologie, Gelenke | `modell` |
| Grobsuche | Silhouetten-Atlas: Azimut 10°, Höhe 10°, aufrecht und kopfüber; Fläche und Schwerpunkt setzen Abstand und Lage; die besten verschiedenen Lagen werden fein nachgesucht | `start` |
| Kandidaten | jede Startlage mal jeden Startwinkel der Gelenke (Haube 50/75/95°), kurz eingepasst, je Bild gewinnt die beste Überdeckung | `ablauf` |
| Kameras | je Bild einzeln (eigene Dämpfung, Maße fest), Gelenke mit vielen Nebenminima (Lenkrollen) vorher abgetastet | `einpassen` |
| Ausreißer | Bilder mit deutlich schlechterer Überdeckung fallen heraus (nur ab 4 Bildern) | `ablauf` |
| Bündel | Maße, Kameras, Brennweiten, Gelenke gemeinsam, Stufen grob -> fein | `einpassen` |
| Unsicherheit | Kovarianz, Jackknife, Empfehlungen | `unsicherheit` |
| Kontrolle | Modellkanten über dem Foto: grün Umriss gegen Maske, gelb innere Kanten, rot ohne Partner | `kontrolle` |

## Strategien je Fall

### 1 Bild (Worst Case)

- **Messbar:** alle Maße, die in der Bildebene liegen und einen sichtbaren Rand haben, relativ zum Maßstab
  (ein Maß muss bekannt sein). An der Küche: Längen, Höhen, Fußhöhe auf wenige Millimeter bis 2 cm.
- **Schlecht oder nicht messbar:** Tiefen entlang der Blickrichtung (Plattentiefe der Küche: 44 mm daneben, das
  Sigma zeigt es mit 11 mm als schwächstes Maß an), alles Verdeckte, und Brennweite gegen Abstand: beide heben sich
  fast auf. Deshalb ist die Brennweite eine Vorgabe (EXIF, QuickTime, sonst 50 mm KB bei Studiofotos).
- **Was hilft:** Symmetrie und Gruppen (ein Maß für vier gleiche Füße), weiche Vorgaben für Unsichtbares, bekannte
  Maße festhalten, Gelenkzustand angeben (Haube offen/zu). Blick schräg über eine Ecke von 25 bis 40° oben, damit drei
  Seiten sichtbar sind.
- **Am Rollwagen:** Eine Draufsicht allein bestimmt die Rollenhöhe nicht (96 ± 10 mm, die Rollen sind fast verdeckt);
  das große Sigma zeigt das an, und die Empfehlung lautet dann „Rollenhöhe nachmessen“ oder „flach von der Seite“.
- **Grenze:** Eine falsche Grobsuche lässt sich mit einem Bild nicht erkennen; bei symmetrischen Objekten sind die
  gleichwertigen Lagen egal, bei fast symmetrischen nicht (dann Kontrollbild prüfen).

### 2 bis 3 Bilder

- Zwei Ansichten etwa 90° versetzt über Eck, dazu eine deutlich höher oder tiefer: dann sind die Tiefen durch die
  zweite Ansicht bestimmt und die Brennweiten durch die Perspektive.
- Gleiche Kamera, gleicher Zoom: eine gemeinsame Brennweite (bei Fotos mit Zoom je Bild eine, wie bei der Küche).
- Jackknife ab 3 Bildern: Weglassen je eines Bildes zeigt, welche Maße an einem einzigen Bild hängen.

### 4 bis 10 Bilder

- Gemeinsamer Ausgleich, Ausreißer-Bilder fallen automatisch heraus (falsche Grobsuche, angeschnittenes Objekt).
- Ab hier lohnen sich Maße, die nur einzelne Ansichten zeigen (Ofen, Rückseite), sonst bleiben sie bei der Vorgabe.
- Die Laufzeit wächst linear (je Bild rund 1 s, an der Küche wie am Rollwagen).

### Video

- **Bildwahl:** ein Durchlauf mit 6 Bildern je Sekunde in kleiner Größe (Hardware-Dekoder, 36 s Video in rund 15 s),
  Schärfe (Laplace-Varianz) und Kameraweg (Phasenkorrelation). Der Weg wird gleichmäßig aufgeteilt, je Abschnitt
  das schärfste Bild mit ganz sichtbarem Objekt. Nahaufnahmen, bei denen das Objekt am Rand abgeschnitten ist,
  bleiben draußen: an ihnen scheitert die Grobsuche.
- **Brennweite:** aus den QuickTime-Metadaten (`camera.focal_length.35mm_equivalent`, hier 24 mm) als Vorgabe.
  Das 4K-Video schneidet für die Stabilisierung aber deutlich vom Sensor ab: eingepasst wurden 2990 bis 3075 px statt
  2796 px aus den Metadaten, Apple Object Capture kommt unabhängig auf 3182 px (rund 29 mm statt 24 mm KB). Deshalb
  gilt die Metadaten-Brennweite nur als weiche Vorgabe (Sigma 15 %), gemeinsam für alle Bilder; mit Sigma 30 % oder
  ganz ohne Vorgabe ändert sich das Ergebnis kaum (geprüft). Eine Gerätetabelle (Modell, Objektiv, Videoformat ->
  gemessene Brennweite) wäre der nächste Schritt.
- **Objekt darf bewegt werden:** Die Kameras stehen im Objektsystem; dass Kevin den Wagen nach 12 s umdreht, stört
  nicht (Object Capture dagegen kann nur einen der beiden Teile nutzen). Bewegliche Teile (Lenkrollen) bekommen je
  Bild eigene Winkel.
- **Grenze:** Bewegungsunschärfe (der zweite Teil des Videos ist weitgehend unscharf) und Nahaufnahmen. Für das
  Messen genügen 5 bis 8 gute Bilder; mehr Bilder senken die Streuung kaum, wenn sie aus derselben Richtung kommen.

## Unsicherheit

- **Statistisch:** Kovarianz aus J^T W J am Ergebnis, Streuung der zugeordneten Kantenpunkte geschätzt, benachbarte
  Punkte als abhängig gezählt. Das ergibt Zehntelmillimeter und ist viel zu optimistisch: An der Küche liegen die
  Abweichungen zur Referenz beim 5- bis 15-Fachen dieser Sigma. Ursache sind Modellfehler (das Modell ist nicht das
  Produkt) und gleichwertige Lösungen von Kamera und Maß, nicht Pixelrauschen.
- **Jackknife (ab 3 Bildern):** je ein Bild weg, warm gestartet nur die feinste Stufe. Erfasst, was an einzelnen
  Bildern hängt; an der Küche liegen die Abweichungen beim 1- bis 3-Fachen davon (die Referenz selbst ist rund 1 cm
  unsicher, das steckt in diesem Faktor mit drin).
- **Ausgabe:** Sigma = größer von 2,5 × Jackknife und 8 × statistischer Sigma (`unsicherheit.sigma_gesamt`, an der
  Küche abgeglichen). Für die Rangfolge der Empfehlungen genügt die statistische Kovarianz.
- **Nachmessen:** für jedes freie Maß die bedingte Kovarianz, wenn es von Hand gemessen würde; empfohlen wird das Maß
  mit der größten Senkung der Gesamtvarianz.
- **Zusatzaufnahme:** virtuelle Kameras rundherum (Abstand und Brennweite wie die vorhandenen), je Richtung die
  Information der dort sichtbaren Kanten über die Maße, die eigene Lage herausgerechnet (Schur-Komplement); unter
  10 ms je Richtung. Am Rollwagen: nachmessen die Rollenhöhe, zusätzlich flach von der Stirnseite filmen.
- **Einrasten:** `unsicherheit.einrasten` setzt ein Maß auf ein Raster (5 mm) oder auf übliche Werte (Lagermaße,
  Rollenhöhen 100/125 mm), wenn es innerhalb einer Sigma liegt.

## Empfehlungen für die Aufnahme

- Ein Maß von Hand messen und eintragen (Maßstab), am besten ein langes, gut sichtbares (Länge des Wagens, Arbeitshöhe).
- Mattes Objekt, ruhig filmen: lieber 10 s langsam als 30 s mit Schwenks; das Objekt ganz im Bild halten.
- Ansichten: schräg über jede zweite Ecke von 30° oben, einmal flach von der Seite (Höhen: Rollen, Rahmen, Rand), einmal
  steil von oben (Öffnungen, Stege). Liegt ein Objekt kopfüber, zeigt es seine Unterseite (Rollen, Rippen) besser.
- Gelenke vorher in eine definierte Stellung bringen (Lenkrollen alle in eine Richtung, Haube ganz zu) oder als
  Gelenk modellieren; sonst kosten sie je Bild Unbekannte.
- Fotos auf Weiß sind am genauesten (Maske pixelgenau); mit Umgebung trägt die Farbe (einfarbiger Kunststoff) oder
  Vision die Maske, die Kanten der Umgebung (Fliesenfugen) filtert die Richtungstrennung weitgehend heraus.

## Einbindung in Kev CAD (Phase 4)

- **MCP-Werkzeug `referenz_vermessen`** (Strang R-K): Eingaben Quelle (Video oder Fotos), freie Maße, bekannte Maße,
  Vorgaben, Bildzahl; Ablauf wie `fotomess vermessen auftrag.json` (`cli.py`). Rückgabe: Maße mit Sigma, je Bild Kamera
  (R, t, f, Bildgröße), verworfene Bilder, Empfehlungen, Kontrollbilder. Laufzeit Sekunden, also synchron möglich; der
  einmalige Modellaufbau (1 + k Varianten von model.py) läuft wie bei fotocad parallel und wird zwischengespeichert.
- **Bauer aus model.py:** Kev-CAD-Modelle lesen Maße mit `param("name", wert)`. Der Kernel braucht dafür einen
  Bauer `p -> Compound`, der model.py mit überschriebenen `param`-Werten ausführt und die mit `show()` gezeigten Teile
  mit ihren Namen sammelt; Gelenke über eine optionale Funktion im Modell oder eine Angabe im Werkzeug. Das ist die
  eine Schnittstelle, die im Kernel neu entsteht (Vertrag `KernelService`).
- **Viewer:** `REF_PHOTO` (Phase-4-Protokoll) bekommt die eingepasste Kamera direkt aus fotomess (`Kamera.als_dict`:
  R, t, f, cx, cy, Bildgröße; Konvention OpenCV, mm, z oben). Das Foto liegt hinter dem Modell, durch diese Kamera
  gesehen, mit Deckkraft-Regler; die Differenz rot/blau kommt gratis, weil Modell und Kamera dieselben sind. Sigma je
  Parameter neben dem Wert in der Parameterliste, Empfehlungen als Hinweis („Rahmenhöhe von Hand messen senkt die
  Unsicherheit am stärksten“, „eine Aufnahme flach von der Stirnseite fehlt“).
- **Object Capture und fotomess ergänzen sich:** Object Capture liefert das Referenznetz für den Viewer (100+ Bilder,
  rund 3 min, ein starres Objekt), fotomess die parametrischen Maße in Sekunden aus 3 bis 8 Bildern, auch bei
  bewegtem Objekt. Liegen Object-Capture-Kameras vor, können sie fotomess als Startwerte dienen (Grobsuche entfällt).

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| F1 | Kantenabstand mit Distanztransformation statt Flächenvergleich | glatt, ableitbar, O(1) je Punkt; die Fläche braucht je Auswertung ein ganzes Bild |
| F2 | LM mit analytischen Ableitungen statt Powell | 20 bis 40 Schritte statt tausender Auswertungen |
| F3 | Netzableitungen aus `fotocad.cad_netz` wiederverwendet | erprobt, Flächenzuordnung bei Neuvernetzung gelöst |
| F4 | Kantenrichtung in 6 überlappenden Fächern | Fliesenfugen und Spiegelungen quer zur Modellkante stören nicht |
| F5 | Sichtbarkeit per GPU-Tiefenbild alle 3 bis 4 Schritte | Sichtbarkeit ändert sich langsam; CPU-Strahltest wäre teurer |
| F6 | Grobsuche als GPU-Atlas mit Flächen- und Schwerpunktausgleich | 300 bis 600 Kandidaten in unter 1 s, kein Vorwissen über die Lage nötig |
| F7 | Erst Kameras je Bild, dann gemeinsam | gemeinsam von schlechten Kameras aus fiel die Suche in Nebenminima (Probe mit dem Tisch) |
| F8 | Maskenrand mit Unterpixel-Lage aus der weichen Maske | halber Pixel Versatz am Rand entfernt (gemessen 0,24 px -> 0,03 px Restfehler) |
| F9 | Apple Vision über Swift-Hilfe, kein Modell mit Fremdlizenz | Neural Engine, keine Gewichte, keine Lizenzfragen |
| F10 | Keine MLX/Metal-Rechnung | gemessen: Lösen unter 1 %, Zeit liegt in Sichtbarkeit und Bildstufen |

## Grenzen und offene Punkte

- Die Grobsuche nimmt Flächen und Schwerpunkt der Maske; bei angeschnittenen Objekten (Nahaufnahme) liegt sie daneben.
  Für Videos wäre Verfolgen von Bild zu Bild der nächste Schritt (Start aus dem Nachbarbild).
- Fluchtpunkte (LSD) als Startwert für Kastenformen sind nicht eingebaut; die Silhouetten-Grobsuche hat bei Küche und
  Rollwagen genügt.
- Das Messmodell bestimmt, was gemessen wird. Beim Rollwagen hatte das Modell der Sitzung auch an den Stirnseiten einen
  Rand; das Kontrollbild zeigte, dass es dort keinen gibt. Mit dem falschen Rand drückte die Suche den Rand auf null
  (Seitenhöhe 50 bis 54 statt 44 mm). Deshalb: Kontrollbilder ansehen, rote Kanten ohne Partner sind Modellfehler.
  Rand und Rahmen trennt nur die Unterbrechung des Randes vor den Ecken; die Summe (Seitenhöhe) ist robust, die
  Aufteilung auf ±3 bis 6 mm. Ein feineres Modell (Rippen, Dome, Lenkrollen nach Datenblatt) macht die Maße sicherer.
- Gegen den Kurzschluss „Merkmal verschwindet in einer starken Kante“ (Kantenabstand nur vom Modell zum Bild) helfen
  harte Grenzen für Maße, die sichtbar nicht null sind (`grenzen`, z. B. Rand ≥ 8 mm).
- Linearisierung: Das Netz ist an den Startmaßen linearisiert; bei Startfehlern über 5 % lohnt ein zweiter Durchgang
  mit neu gebauten Ableitungen am Ergebnis.
- Verzeichnung wird nicht modelliert (iPhone-Video ist entzerrt, die Studiofotos laut fotocad auch).
