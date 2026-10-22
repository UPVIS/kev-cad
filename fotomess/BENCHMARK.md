# fotomess · Benchmark

Stand: 21.10.2026 (Scarlett 2i2: 22.10.2026), Mac M2 Pro (16 GB), ein Prozess, GPU über moderngl. Erzeugt mit
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

## Scarlett 2i2 (Video, echte Umgebung, Holzscheibe)

Stand 22.10.2026. Video IMG_5186.MOV (iPhone 15 Pro Max, 4K quer, 30 fps, 39,7 s), Focusrite Scarlett 2i2
(4. Generation): rotes, mattes Aluminiumrohr, vorn und hinten schwarze Blenden, liegt auf einer Holzscheibe auf
Fliesen. Anders als angekündigt wird das Gerät im Video nicht bewegt, nur die Kamera geht herum: 0 bis 21 s
Umlauf mit Rückseite und flachen Ansichten, 21 bis 28 s Nahaufnahmen der Vorderseite, 28 bis 40 s steil von oben
und schräg. Unterseite und Hochkantlage kommen nicht vor; Object Capture kann deshalb das ganze Video nutzen.

Hersteller: 180 × 117 × 47,5 mm (Breite × Tiefe × Höhe); offen, ob Tiefe und Höhe Knöpfe und Füße einschließen.
Fest ist nur die Breite 180 (das Rohr hat seitlich keine Anbauten). Messmodell `modelle/scarlett.py`: Rohr mit
gerundeten Kanten entlang der Tiefe (`kanten_r`; die Kanten an Vorder- und Rückseite sind scharf), Blenden 0,5 mm
vertieft mit 3 mm rotem Rand, vorn zwei Gain-Knöpfe und der Kopfhörerknopf (Überstand `knopf_h`), der Output-Knopf
(`gross_h`), die Kopfhörerbuchse (fest 10 mm); Lage und Durchmesser der Knöpfe aus dem Object-Capture-Netz. Vier Füße
1,5 mm, fest: Die Unterseite ist nie zu sehen, die Füße sind aus den Bildern nicht messbar. Gemessen werden `tiefe`
(Rohr ohne Knöpfe), `hoehe` (Rohr ohne Füße), `kanten_r`, `knopf_h`, `gross_h`.

Masken: Rot über die Farbe (H 168 bis 4, läuft über 0), Blenden und Knöpfe über Apple Vision. Vision zählt die
Holzscheibe mit; deshalb gilt Vision ohne Farbprüfung nur in der konvexen Hülle des roten Rohrs (es fasst die
Blenden ein, in denen sich das Holz spiegelt), außerhalb nur nahe am Rohr, ohne Holzfarbe und nur Teile, die am
Gehäuse hängen (`masken.gehaeuse_optionen`). Brennweite gemeinsam, Vorgabe 2796 px (Metadaten 24 mm, Sigma 15 %).
Bildwahl automatisch (Schärfe, Kameraweg, Gerät ganz im Bild): 1 = 3,7 s; 2 = dazu 38,0 s; 3 = dazu 14,8 s;
5 = 3,7 / 10,5 / 18,5 / 30,2 / 38,0 s; 8 = 3,7 / 9,0 / 14,8 / 18,5 / 25,2 / 30,2 / 32,8 / 38,0 s.

Object Capture zum Vergleich: `kevcad-capture lauf … --auflage --masz laenge=180` (siehe
[tools/capture/README.md](../tools/capture/README.md)). Gesamttiefe = Hüllmaß quer (mit Knöpfen), Gehäusetiefe =
Deckelschicht (dichteste waagrechte Schicht oben, 42 bis 48 mm über der Auflage, dort gibt es keine Knöpfe), Höhe =
obere waagrechte Fläche über der Auflage, also mit Füßen (das robuste Hüllmaß, 99,9 %, steht daneben; es nimmt
Unebenheiten des Netzes am Deckel mit). „ganz“: ganzes Video, 60 × 1920 px, reduced; „genau“: 120 × 2880 px, medium;
„umlauf“: 0 bis 21 s; „nah“: 21 bis 39,7 s.

| Verfahren | Bilder (genutzt) | Laufzeit | f (px) | Gesamttiefe mit Knöpfen (Soll 117) | Höhe (Soll 47,5) | Gehäusetiefe ohne Knöpfe | Überstand Knöpfe (Gain / Output) | kanten_r |
|---|---|---|---|---|---|---|---|---|
| fotomess | 1 (1) | 2.1 s | 3432 | 122.1 (+5.1 mm, +4.3 %) | 48.9 ± 1.1 (+1.4 mm, +2.9 %) | 107.8 ± 3.1 | 14.0 ± 1.3 / 14.3 ± 1.5 | 3.2 ± 2.5 |
| fotomess | 2 (2) | 1.2 s | 3379 | 118.7 (+1.7 mm, +1.5 %) | 50.7 ± 0.7 (+3.2 mm, +6.7 %) | 105.4 ± 1.1 | 13.3 ± 1.1 / 13.2 ± 1.0 | 5.8 ± 1.1 |
| fotomess | 3 (3) | 2.5 s | 3597 | 121.5 (+4.5 mm, +3.8 %) | 48.5 ± 0.8 (+1.0 mm, +2.1 %) | 107.3 ± 5.2 | 14.0 ± 4.3 / 14.2 ± 14.9 | 4.4 ± 2.1 |
| fotomess | 5 (5) | 3.5 s | 3260 | 123.3 (+6.3 mm, +5.4 %) | 47.4 ± 1.8 (−0.1 mm, −0.1 %) | 104.5 ± 1.6 | 11.2 ± 1.8 / 18.7 ± 6.2 | 4.0 ± 1.0 |
| fotomess | 8 (8) | 6.0 s | 3123 | 120.8 (+3.8 mm, +3.2 %) | 46.9 ± 0.6 (−0.6 mm, −1.2 %) | 105.2 ± 2.0 | 12.6 ± 1.5 / 15.5 ± 1.7 | 4.0 ± 1.7 |
| Object Capture ganz | 60 (42) | 45 s | 3226 | 117.3 (+0.3 mm, +0.3 %) | 47.5 (±0.0 mm); Hülle 48.4 | 102.1 | 15.2 | – |
| Object Capture genau | 120 (109) | 394 s¹ | 3232 | 118.3 (+1.3 mm, +1.1 %) | 46.7 (−0.8 mm, −1.7 %); Hülle 49.2 | 102.6 | 15.7 | – |
| Object Capture umlauf | 60 (60) | 338 s¹ | 3202 | 116.5 (−0.5 mm, −0.4 %) | 46.9 (−0.6 mm, −1.3 %); Hülle 47.9 | 101.9 | 14.6 | – |
| Object Capture nah | 60 (60) | 239 s¹ | 3260 | 116.7 (−0.3 mm, −0.3 %) | 47.0 (−0.5 mm, −1.1 %); Hülle 48.7 | 102.5 | 14.2 | – |

Höhe: fotomess = Rohr ohne Füße, Object Capture = Auflage bis Deckel (mit Füßen). Überstand bei Object Capture =
Gesamttiefe minus Deckelschicht (der weiteste Knopf). f bei Object Capture: Median der Kameras, auf 3840 px
umgerechnet. ¹ Speicher während dieser Läufe durch andere Agenten auf 13 bis 24 % frei gedrückt: 5- bis
8-mal langsamer als „ganz“ (40 s Rekonstruktion) bzw. als „genau“ am Rollwagen (209 s); nicht vergleichbar.

Laufzeiten fotomess außerdem: Bildbewertung 23 s (238 Bilder, 6 je Sekunde, 640 px), Holen der 4K-Bilder mit Vision
und Masken rund 6 s je Bild (8 Bilder 50 s, unter Last 95 s), Modellaufbau einmalig rund 1 min (6 Varianten,
zwischengespeichert), Unsicherheit mit Jackknife 0,1 bis 3 s.

Prüfläufe (Breite frei, dafür ein anderes Maß fest):

- Höhe 47,5 fest (Herstellerhöhe als Rohrhöhe gelesen): Breite **177,6 ± 1,7 mm** (5 Bilder, −1,3 %) bzw.
  **178,4 ± 1,6 mm** (8 Bilder, −0,9 %), innerhalb einer Sigma; mittlere Überdeckung 0,933 bzw. 0,936 gegen 0,940
  ohne Prüfmaß.
- Tiefe 117 fest (Herstellertiefe als Rohr ohne Knöpfe gelesen): Breite 179,9 ± 3,3 bzw. 179,6 ± 4,7 mm, aber die
  Passung wird deutlich schlechter: mittlere Überdeckung 0,908 bzw. 0,926 statt 0,940, in den Draufsichten 0,885 und
  0,913 statt 0,93 und 0,97, der Kantenradius fällt auf 0,6 bis 0,9 mm. Breite und Tiefe sind über diese Bilder schwach gekoppelt (die
  Breite hängt an den Vorderansichten über die Höhe); eine falsche Tiefe zeigt sich hier in der Überdeckung, nicht im
  Prüfmaß Breite.

### Befund: Was steckt in 117 und 47,5?

- **Tiefe 117 schließt die Knöpfe ein.** Beide Verfahren messen das Rohr ohne Knöpfe 102 bis 105 mm tief, die Knöpfe
  stehen 14 bis 16 mm vor (Object Capture 14,2 bis 15,7; fotomess mit 8 Bildern 12,6 Gain, 15,5 Output). Rohr plus
  Knöpfe: Object Capture 116,5 bis 118,3, fotomess 118,7 bis 123,3. Läse man 117 als Rohrtiefe, lägen beide Verfahren
  10 bis 13 % daneben, und der Prüflauf mit 117 fest passt sichtbar schlechter.
- **Höhe 47,5 passt zur Rohrhöhe; ob die Füße mit drin sind, entscheidet das Video nicht.** Object Capture misst
  Auflage bis Deckel 46,7 bis 47,5 mm (mit Füßen), fotomess das Rohr allein 46,9 ± 0,6 mm (8 Bilder). Der Unterschied
  ist 0 ± 1 mm: Entweder sind die Füße höchstens etwa 1 mm hoch, oder 47,5 schließt sie ein und das Rohr ist rund
  46,5 mm hoch. Die Unterseite ist im Video nie zu sehen.
- **Restfehler bei der Lesart „117 mit Knöpfen, 47,5 Rohr“:** Object Capture Gesamttiefe −0,4 bis +1,1 %, Höhe −1,7
  bis 0 %; fotomess mit 8 Bildern Gesamttiefe +3,2 %, Höhe −1,2 %, mit 5 Bildern +5,4 % und −0,1 %. Offen bleibt die
  Rohrtiefe: fotomess 104,5 bis 105,4 (2, 5, 8 Bilder), Object Capture 101,9 bis 102,6 (Deckelschicht; Vorder- und
  Rückfläche liegen im Netz 102 bis 104 mm auseinander). Eins der beiden liegt hier 2 bis 3 % daneben. fotomess ist
  bei 1 bis 3 Bildern unruhig (Höhe 48,5 bis 50,7, Rohrtiefe bis 107,8), ab 5 Bildern stabiler; die Videobilder
  sind fast alle bewegungsunscharf, am schärfsten die Draufsichten.
- **Brennweite:** fotomess 3123 bis 3597 px (8 Bilder 3123), Object Capture 3202 bis 3260 px; die Metadaten (2796 px) sind wie am
  Rollwagen 12 bis 13 % zu kurz. Mit f fest auf 3232 px ändern sich Rohrtiefe und Höhe um weniger als 1 mm
  (Diagnoselauf), die Brennweite erklärt den Unterschied zu Object Capture also nicht.

### Empfehlung: von Hand nachmessen

- `unsicherheit.nachmessen` (8 Bilder): zuerst der Überstand des Output-Knopfs (`gross_h`, Gesamtvarianz auf 59 %),
  dann Kantenradius und Rohrtiefe; bei 1 bis 3 Bildern steht die Rohrtiefe vorn. Zusatzaufnahme: schräg über die
  vordere rechte Ecke (Azimut 315°, 30° hoch), bei 8 Bildern nur noch 4 % Gewinn.
- Für die offene Frage mit dem Messschieber: (1) **Rohrtiefe ohne Knöpfe** an der Oberkante des roten Rohrs,
  Vorderkante bis Hinterkante (gemessen 102 bis 105; entscheidet zwischen den Verfahren), (2) **Gesamttiefe**
  Rückseite bis Vorderfläche des Output-Knopfs (prüft 117), (3) **Rohrhöhe** an der Seite und **Gesamthöhe** auf
  einer ebenen Platte (Differenz = Füße, prüft 47,5).

### Was an fotomess dafür ergänzt wurde

- **Farbteile** (`Ausgleich.iou_farbe`, `netz.farb_tris`, `bild.farbmaske`): Die sichtbaren roten Flächen des Modells
  werden mit der Rotmaske verglichen und gehen in die Wahl der Startlage ein. Ohne sie fiel in der flachen Ansicht
  (18,5 s) die um 90° gedrehte Lage hinein (rote Stirnseite und schwarze Vorderseite vertauscht, gleiche Silhouette).
- **Zwillingslagen** (`Eingabe.zwillinge`): Vorn und hinten sehen gleich aus, nur die Knöpfe unterscheiden sie. Zu
  jeder Startlage wird die um 180° gedrehte gleich eingepasst; fast gleich gute Kandidaten vergleicht die feinere
  Stufe. Ohne sie lagen in einem von fünf Bildern die Knöpfe hinten (38,0 s); eine zuerst versuchte Entscheidung
  über die mittleren Kantenkosten war schlechter (zwei von fünf falsch) und ist verworfen. Ohne Zwillinge bleibt die
  Wahl wie bisher (Küche und Rollwagen unverändert).
- **Masken mit Unterlage** (`masken.farbbereich`, `kombiniert(ausschluss, umkreis, innen, aussen_oeffnen,
  schliessen, loch_anteil)`, `gehaeuse_optionen`), dazu dieselben Optionen in der Kommandozeile (`farbe_hsv` über 0,
  `ausschluss_hsv`, `gehaeuse`, `farbteile`, `zwillinge`). Probe über `fotomess vermessen` mit 5 Bildern: Rohrtiefe
  103,9 ± 0,9, Höhe 47,6 ± 1,4 mm in 5,4 s.
- Grenzen: Die Knöpfe fehlen in Seitenansichten teils in der Maske (dunkel vor dunklem Boden außerhalb der Hülle, teils
  als Holzfarbe ausgeschlossen); nur 33 bis 90 % der Kantenpunkte finden einen Partner (Unschärfe, Blendenkanten);
  Bildholen und Masken in 4K kosten rund 6 s je Bild und sollten auf der Arbeitsgröße laufen.

## Kontrollbilder

`build/fotomess/kontrolle/`: `kueche_<n>_<foto>.jpg` (erste drei Fotos je Teilmenge), `rollwagen_<n>_<bild>.jpg`
(alle genutzten Bilder je Lauf), `rollwagen_pruef_8_*.jpg`, `objectcapture_<n>_*.jpg`, `scarlett_<n>_<bild>.jpg`,
`scarlett_pruef_<maß>_<n>_<bild>.jpg`; Object Capture der Scarlett unter `build/capture/kontrolle/`. Grün: Umriss gegen die Maske,
gelb: innere Kanten gegen Bildkanten, rot: ohne Partner im Bild, blau: Rand der Bildmaske.
