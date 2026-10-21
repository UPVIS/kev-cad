# fotomess · Benchmark

Stand: 21.10.2026, Mac M2 Pro (16 GB), ein Prozess, GPU über moderngl. Erzeugt mit
`.venv/bin/python -m fotomess.benchmark.lauf …` (siehe dort), Rohdaten als JSON unter `build/fotomess/benchmark/`,
Kontrollbilder unter `build/fotomess/kontrolle/` (beides nicht im Git). Laufzeiten ohne den einmaligen Modellaufbau
(Netz mit Ableitungen: Küche rund 2 min für drei Bauformen, Rollwagen rund 30 s, danach zwischengespeichert) und ohne
das Laden der Bilder.

## Küche (Beelonia, Studiofotos auf Weiß)

Start: alle 18 Maße um 3 bis 5 % verfälscht (mittlerer Fehler 25 mm), Kameras unbekannt, Brennweite je Foto frei
(Zoom, kein EXIF; Vorgabe 50 mm KB). Teilmengen: 1 = 0006; 2 = + 0035; 3 = + 0064 (Ofen); 5 = + 0104a (gerade Zeile),
0020; 10 = + 0013, 0043, 0083, 0129, 0140; 22 = alle. Freie Maße: alle der Bauformen, die vorkommen. Referenz: voller
Bündelausgleich mit fotocad über alle 22 Fotos; sie ist selbst etwa ±1 cm unsicher (README der Küche: „Die Kameras
selbst tragen noch etwa 1 cm bei“).

Vergleichsverfahren „fotocad“: Kevins Einpassung (Powell auf der weichen Überdeckung, Kamera 700 px dann 1200 px,
Maße 900 px, Vorgabe zugunsten der Startwerte, wie `messung/netz_buendel.py`), mit denselben Startkameras aus der
fotomess-Grobsuche. Die projektspezifische Grobstufe der Küche (Ersatzkörper) ist nicht nachgebaut.

| Fotos | Verfahren | Laufzeit | Maße: mittl. Abweichung zur Referenz | Kameras: Drehung / Ort / f (Median) | IoU eigenes Modell (eingepasste Fotos) | IoU übrige Fotos (eigene Maße / Referenzmaße) |
|---|---|---|---|---|---|---|
| 1 | fotomess | 1.3 s | 11.8 mm (max 44, 11 Maße) | 0.29° / 306 mm / 5.0 % | 98.29 % | 97.24 / 97.91 % |
| 2 | fotomess | 1.9 s | 13.3 mm (max 55, 11 Maße) | 0.59° / 392 mm / 6.8 % | 98.28 % | 97.16 / 97.90 % |
| 3 | fotomess | 2.5 s | 14.4 mm (max 51, 14 Maße) | 0.54° / 369 mm / 6.9 % | 98.41 % | 97.33 / 97.88 % |
| 5 | fotomess | 4.3 s | 12.3 mm (max 38, 18 Maße) | 0.41° / 188 mm / 4.2 % | 98.19 % | 97.81 / 97.89 % |
| 10 | fotomess | 9.1 s | 13.7 mm (max 44, 18 Maße) | 0.43° / 358 mm / 7.9 % | 98.07 % | 97.78 / 97.84 % |
| 22 | fotomess | 22.3 s | 12.4 mm (max 41, 18 Maße) | 0.67° / 382 mm / 7.0 % | 97.92 % | – |
| 1 | fotocad | 59.7 s | 20.5 mm (max 45, 11 Maße) | 1.22° / 670 mm / 12.2 % | 97.77 % | 97.24 / 97.91 % |
| 2 | fotocad | 76.0 s | 21.5 mm (max 47, 11 Maße) | 0.82° / 617 mm / 10.8 % | 97.48 % | 97.35 / 97.90 % |
| 3 | fotocad | 135.1 s | 20.5 mm (max 49, 14 Maße) | 0.83° / 564 mm / 10.2 % | 97.72 % | 97.35 / 97.88 % |
| 5 | fotocad | 318.3 s | 20.1 mm (max 41, 18 Maße) | 1.11° / 564 mm / 10.2 % | 97.62 % | 97.58 / 97.89 % |

Lesart:

- **Tempo:** fotomess braucht rund 1 s je Foto, linear (1 Foto 1,3 s, 22 Fotos 22 s). fotocad braucht bei gleichem
  Start 40- bis 74-mal so lange und kommt mit seinem Auswertungsbudget (5 000 bis 27 000 GPU-Bilder) bei den Maßen
  kaum vom Start weg (25 -> 20 mm). Ein fotocad-Lauf über 10 und 22 Fotos ist deshalb
  nicht gemessen (Hochrechnung aus 1 bis 5 Fotos: je Foto rund 17 s Kamera und 47 s Maße, also rund 11 bzw. 23 min).
- **Passung:** Das eigene Modell deckt die eingepassten Fotos zu 97,9 bis 98,4 % (Referenz mit Referenzkameras:
  97,9 % im Mittel), also gleich gut oder besser als der volle Bündelausgleich.
- **Maße gegen die Referenz:** im Mittel 12 bis 14 mm, unabhängig von der Fotozahl. Mit den Referenzkameras fest
  eingesetzt landen dieselben Maße 3 bis 4 mm neben der Referenz; der Rest ist die Kopplung von Brennweite, Abstand
  und Maßen, die die Umrisse nicht auflösen (Lösungen mit 5 bis 8 % kürzerer Brennweite und näherer Kamera passen
  ebenso gut). Das ist dieselbe Größenordnung, mit der die Referenz selbst angegeben ist.
- **Bester ehrlicher Maßstab:** die rechte Spalte. Maße aus wenigen Fotos, Kameras der übrigen Fotos mit festen Maßen
  eingepasst: Ab 5 Fotos erklären die fotomess-Maße die nicht benutzten Fotos fast so gut wie die Referenzmaße
  (97,81 gegen 97,89 %); aus 1 bis 3 Fotos fehlen 0,6 bis 0,7 Punkte (Tiefen sind schlecht bestimmt).
- **Schwächstes Maß** aus einem Foto: die Plattentiefe (44 mm daneben); die statistische Sigma weist sie mit 11 mm
  als mit Abstand unsicherstes Maß aus.

Laufzeit fotomess je Schritt (s):

| Fotos | Grobsuche | Kandidaten | Kameras | Bündel | gesamt | je Foto | Unsicherheit (mit Jackknife) |
|---|---|---|---|---|---|---|---|
| 1 | 0.4 | 0.4 | 0.2 | 0.3 | 1.3 | 1.28 | 0.0 |
| 2 | 0.4 | 0.5 | 0.4 | 0.6 | 1.9 | 0.95 | 0.1 |
| 3 | 0.3 | 0.6 | 0.6 | 0.9 | 2.5 | 0.84 | 0.9 |
| 5 | 0.5 | 1.4 | 1.0 | 1.4 | 4.3 | 0.86 | 2.2 |
| 10 | 1.0 | 3.0 | 2.1 | 2.9 | 9.1 | 0.91 | 8.5 |
| 22 | 2.1 | 8.8 | 4.6 | 6.7 | 22.3 | 1.01 | 21.0 |

Innerhalb der Schritte (22 Fotos): Sichtbarkeit (GPU-Tiefenbild, Lesen, Kantenauswahl) 5,7 s, Bildstufen
(Kanten, Distanztransformationen) 2,4 s, Auswertung der Residuen und Ableitungen 3,0 s, Lösen der Normalgleichungen
0,02 s. Das Jackknife (bis 8 Läufe ohne je ein Bild) ist optional und kostet etwa so viel wie der Bündelausgleich.

Unsicherheit gegen die Referenz (Abweichung durch Sigma, Median über die Maße): statistische Sigma 5 bis 18
(zu optimistisch, wird mit der Bildzahl kleiner, die Abweichung nicht), Jackknife 1,2 bis 2,7. Daraus die Zuschläge
in `unsicherheit.sigma_gesamt`: Sigma = größer von 2,5 × Jackknife und 8 × statistisch.

## Rollwagen (Video, echte Umgebung)

Video IMG_5182.MOV (iPhone 15 Pro Max, 4K, 36 s), Bilder automatisch gewählt (Schärfe, Objekt ganz im Bild, über den
Kameraweg verteilt). Masken: Apple Vision plus Blau. Bekannt und fest: 610 × 410 mm, Räder Ø 100 mm. Brennweite
gemeinsam für alle Bilder, Vorgabe aus den Metadaten 2796 px (24 mm KB, Sigma 15 %). Gelenke: je Bild vier
Schwenkwinkel der Lenkrollen. Sigma wie oben (größer von 2,5 × Jackknife und 8 × statistisch).

| Bilder (genutzt) | Laufzeit | f (px) | rolle_h | rahmen_h | rand_h | rahmen_h + rand_h | steg | oeff_fase | schraube_rand |
|---|---|---|---|---|---|---|---|---|---|
| 1 (1) | 1.7 s | 2972 | 96.2 ± 10.1 | 49.9 ± 2.9 | 18.3 ± 2.3 | 68.2 | 54.3 ± 1.2 | 93.3 ± 2.8 | 56.1 ± 3.2 |
| 2 (2) | 2.2 s | 2917 | 115.6 ± 3.1 | 25.4 ± 1.9 | 18.5 ± 2.5 | 44.0 | 57.7 ± 0.8 | 100.2 ± 1.9 | 61.6 ± 1.4 |
| 3 (3) | 3.6 s | 3010 | 117.5 ± 3.0 | 23.4 ± 4.3 | 18.8 ± 15.9 | 42.1 | 56.9 ± 2.4 | 103.2 ± 3.3 | 64.0 ± 1.4 |
| 5 (5) | 5.8 s | 3048 | 120.3 ± 7.0 | 29.0 ± 10.8 | 17.8 ± 3.5 | 46.8 | 55.9 ± 1.6 | 98.0 ± 6.7 | 64.3 ± 1.6 |
| 8 (6) | 8.9 s | 2996 | 119.0 ± 5.2 | 28.5 ± 6.0 | 16.4 ± 2.9 | 44.9 | 55.9 ± 0.9 | 97.2 ± 6.5 | 64.0 ± 0.8 |
| 12 (9) | 13.0 s | 3007 | 120.6 ± 3.2 | 23.3 ± 3.2 | 20.7 ± 2.9 | 44.0 | 56.6 ± 0.9 | 100.8 ± 2.2 | 63.7 ± 1.2 |

Nicht genutzt (automatisch verworfen, Überdeckung deutlich unter den anderen): bei 8 Bildern 12,8 s und 34,0 s,
bei 12 Bildern 1,7 s, 32,5 s und 34,0 s. Ein einzelnes Bild (Draufsicht von oben) bestimmt die Rollenhöhe nicht
(96 ± 10 mm, die Rollen sind kaum zu sehen); ab 2 Bildern liegen alle Läufe in einem engen Band.

### Gemessene Maße gegen die Annahmen

Ergebnis: Lauf mit 12 gewählten, 9 genutzten Bildern; Spanne über die Läufe mit 2 bis 12 Bildern.

| Maß (mm) | Annahme im Auftrag | model.py jetzt (andere Sitzung) | fotomess | Spanne 2–12 Bilder | Befund |
|---|---|---|---|---|---|
| rolle_h (Boden bis Unterkante Rahmen) | 128 | 120 ± 6 | **120.6 ± 3.2** | 115.6 – 120.6 | 128 ist 7 bis 12 mm zu hoch; 120 bestätigt |
| rahmen_h (Unterkante Schürze bis Plattenoberseite) | 35 | 31 ± 7 | **23.3 ± 3.2** | 23.3 – 29.0 | niedriger als angenommen; Trennung zum Rand nur über die Randenden bestimmt |
| rand_h (Rand über der Platte) | – | 19 ± 2 | **20.7 ± 2.9** | 16.4 – 20.7 | bestätigt |
| rahmen_h + rand_h (Seitenhöhe) | 35 + 19 | 50 | **44.0** | 42.1 – 46.8 | robust; 6 mm unter model.py |
| steg (Außenkante bis Öffnung) | 45 | 58.5 / 57.5 (Öffnung 493 × 295) | **56.6 ± 0.9** | 55.9 – 57.7 | 45 ist deutlich zu klein; 57 bis 58 bestätigt |
| oeff_fase (Eckschräge der Öffnung) | – | 103 / 101.5 | **100.8 ± 2.2** | 97.2 – 103.2 | bestätigt |
| schraube_rand (Rollenachse von den Kanten) | – | 63 ± 3 | **63.7 ± 1.2** | 61.6 – 64.3 | bestätigt |
| Gesamthöhe Rad unten bis Randoberkante | 182 | 170 | **164.6** | 159.6 – 167.1 | Object Capture (andere Sitzung): 161.6 |

Befund am Kontrollbild: Die Stirnseiten haben keinen aufgestellten Rand (nur die Längsseiten). Mit Rand an allen vier
Seiten (wie im Modell der Sitzung) drückte die Suche den Rand auf null und schob ihn in den Rahmen (Seitenhöhe dann
50 bis 54 mm); nach der Korrektur des Messmodells sind die Läufe stabil.

Prüfmaße: Lauf mit 8 Bildern, nur die Länge 610 mm fest, Breite und Raddurchmesser mitgemessen: Breite
**402.9 ± 18.5 mm** (Soll 410), Rad **Ø 94.9 ± 5.4 mm** (Soll 100). Beide innerhalb einer Sigma; das Rad liegt
systematisch etwas klein (abgerundete Lauffläche, im Modell ein scharfkantiger Zylinder).

Empfehlungen (`unsicherheit`): Von Hand nachmessen sollte man die **Rollenhöhe** (senkt die Gesamtvarianz am stärksten,
in allen Läufen ab 2 Bildern an erster Stelle). Als Zusatzaufnahme bringt eine **flache Ansicht von der Stirnseite**
(10° Höhe, bzw. 20° bei liegendem Wagen) am meisten.

### Kameras gegen Apple Object Capture

Gleiche Videobilder wie Object Capture (aus deren 112 Bildern mit derselben Auswahlregel gewählt), Kameras nach
Ähnlichkeitstransformation verglichen (Drehung aus den Blickrichtungen, Maßstab und Verschiebung aus den
Kamerazentren; der Wagen ist um 180° symmetrisch, je Bild zählt die passende Lage). Object Capture brauchte für seine
120 Bilder rund 200 s.

| Bilder | Laufzeit fotomess | f fotomess / Object Capture | Maßstab | Drehung (Median) | Ort (Median, Abstand 0,8 bis 1,2 m) |
|---|---|---|---|---|---|
| 3 | 3.7 s | 3075 / 3182 px | 1.032 | 1.93° | 35 mm |
| 4 | 5.1 s | 2986 / 3182 px | 1.032 | 4.54° | 77 mm |
| 7 | 7.1 s | 2989 / 3182 px | 1.079 | 0.84° | 14 mm |

Die Brennweite aus den Metadaten (2796 px) ist für dieses Video 12 % zu kurz: Das 4K-Video schneidet für die
Stabilisierung vom Sensor ab. fotomess schätzt sie selbst auf 2990 bis 3075 px, Object Capture auf 3182 px; die
verbleibenden 3 bis 6 % zeigen sich als Maßstab 1,03 bis 1,08 der Kamerazentren (fotomess-Kameras etwas näher, dazu
kommt, dass Object Capture seinen Maßstab aus einer Hüllkante von 610 mm nimmt). Mit 7 Bildern stimmen Drehung
(0,8°) und Ort (14 mm) gut überein.

## Kontrollbilder

`build/fotomess/kontrolle/`: `kueche_<n>_<foto>.jpg` (erste drei Fotos je Teilmenge), `rollwagen_<n>_<bild>.jpg`
(alle genutzten Bilder je Lauf), `rollwagen_pruef_8_*.jpg`, `objectcapture_<n>_*.jpg`. Grün: Umriss gegen die Maske,
gelb: innere Kanten gegen Bildkanten, rot: ohne Partner im Bild, blau: Rand der Bildmaske.
