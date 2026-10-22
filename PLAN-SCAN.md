# Kev CAD · Scan mit dem iPhone (Mac-Seite)

Stand: 22.10.2026. Vertrag: [SCAN.md](SCAN.md) (Format, Übertragung, Ergänzungen von App und Mac). Die iPhone-App
„Kev Scan“ (`ios/KevScan/`) nimmt auf; hier steht, was der Mac daraus macht.

## Ziel

Kevin scannt einen Gegenstand mit dem iPhone (LiDAR, ARKit-Lagen, Video, hochaufgelöste Fotos) und schickt den Scan
per WLAN an Kev CAD. Daraus entsteht ohne bekanntes Maß eine Referenz im Projekt: ein metrisches Netz im Viewer
(mm, Z oben, Boden z = 0) und Bilder mit bekannten Kameras. `referenz_vermessen` passt danach die `param()`-Maße von
model.py mit diesen Kameras und der gemessenen Tiefe ein. Gewinn gegenüber Phase 4: die Kameras sind bekannt (laut
BENCHMARK.md 3 bis 4 mm statt 12 bis 14 mm Maßfehler), und die Tiefe macht den Scan metrisch.

## Ablauf

1. **Empfang** (Kernel, `kevcad_kernel/scan/empfang.py`): HTTP auf freiem Port, Bonjour `_kevscan._tcp` über
   `dns-sd`; `POST /scan` schreibt das ZIP in Blöcken auf die Platte, prüft und entpackt es nach
   `~/Documents/Kev CAD/Scans/<datum>_<name>/`. Mitteilung „Scan empfangen“. Läuft, solange der Kernel einer
   App-Variante läuft; Testvarianten als `_kevscan-test._tcp` mit eigenem Namen und eigener Ablage.
2. **MCP:** `scans` listet, `scan_importieren(scan, name, schnell, warten_s)` startet die Auswertung als eigenen
   Prozess und legt die Referenz `<projekt>/referenzen/<name>/` (art `scan`) an; Fortschritt in der Referenzliste der
   App, Netz halbdurchsichtig im Viewer wie bei Object Capture.
3. **Auswertung** (`scan/`, eigene uv-Umgebung, `kevscan auswerten <ordner|zip> [--schnell]`):
   - Bilder: alle Fotos, dazu Videobilder nach Abstand und Blickwinkel (weitester Punkt), Unschärfe aussortiert.
   - Tiefe: PromptDA je Bild, LiDAR als Prompt (Lücken mit dem nächsten Messwert gefüllt, im Ergebnis maskiert),
     lange Kante 1008 px; Maßstab je Bild an LiDAR angeglichen (Median, höchstens ±5 %); Tiefensprünge weg.
   - TSDF über die Box aus `objekt.json` (sonst Boden und Objekt geschätzt), Voxel aus der Boxgröße (2 mm bis 40 cm),
     marching cubes, Bodenreste weg, größte Komponente; Kev-CAD-System wie Object Capture.
   - Ausgabe: Netz (OBJ, PLY), Punktwolke, `poses.json` (Form von kevcad-capture), `kameras.json`, Bilder, Masken
     (Umriss des Netzes), Tiefenbilder, `bericht.json` (Laufzeiten, Abdeckung, Streuung der Tiefe gegen das Netz).
4. **Vermessen** (fotomess, `fotomess/src/fotomess/scan.py`): Scan per ICP an das Modell legen (Drehung um Z,
   Verschiebung), ARKit-Kameras als feste Startwerte (Brennweite fest, keine Grobsuche) mit weicher Bindung
   (5 mm, 0,5°), Tiefe als zusätzliche Bedingung (Tiefe des Modells gegen gemessene Tiefe, Cauchy, Gewicht 0,3 nach
   Konfidenz), zweiter Durchgang, nachdem die gemeinsame Bewegung der Kameras in die Lage gewandert ist. Das Netz
   liegt danach am Modell (`lage`).

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| S1 | Auswertung als eigener Prozess in eigener uv-Umgebung `scan/` | torch (rund 800 MB) nie im Kernel; wie fotomess |
| S2 | PromptDA übernommen (Apache-2.0) statt Paket aus Git | Original braucht CUDA, xFormers, torch 2.0.1 und hängt an `torch.hub`; gekürzt läuft es auf MPS, Gewichte passen ohne Umbenennen |
| S3 | torch 2.13.0 | liegt im uv-Zwischenspeicher (kein zweiter Download, Platz ist knapp); fotomess hat kein torch |
| S4 | Eigene TSDF (numpy, auf MPS mit torch) plus marching cubes aus scikit-image statt Open3D | Open3D zieht Dash, Plotly, Pandas und mehr nach; die TSDF hat 150 Zeilen |
| S5 | PromptDA-Tiefe im Maßstab an LiDAR angleichen | an der Probe lag Large 1,5 % zu weit (bei 600 mm 9 mm); LiDAR ist metrisch, PromptDA liefert die Form |
| S6 | Tiefensprünge (Spannweite im 5 × 5-Fenster über 3 % + 2 mm) verwerfen | Mischpixel an Kanten bilden sonst Krempen um das Objekt |
| S7 | Ausgabe im Format von Object Capture (`capture/netz_mm.obj`, `poses.json`) | Viewer, Fotoansicht und Lage aus Phase 4 laufen unverändert |
| S8 | Masken aus dem Umriss des Netzes, Umriss in fotomess gegen Bildkanten | Vision kennt die Szene nicht; der Netzumriss ist um 1 bis 2 Voxel ungenau, dient nur Überdeckung und Ausreißern |
| S9 | Testvarianten als `_kevscan-test._tcp` | das iPhone sieht sie nicht und sendet nie an eine Testvariante |
| S10 | Mitteilung über macOS und Protokollzeile, keine neue Nachricht im Protokoll | „lieber ohne“; die Referenzliste zeigt den Rest |
| S11 | Nach dem ersten Durchgang die gemeinsame Bewegung aller Kameras in die Lage Scan → Modell legen | sonst zieht ein Anlegefehler (an der Probe 6°, 10 mm) jede Kamera gegen ihre Bindung; danach bewegen sich die Kameras nur um das ARKit-Rauschen |
| S12 | Tiefengewicht 0,3, Bindung der Kameras 5 mm und 0,5° | an der Probe mit Lagefehlern abgestimmt (Gewicht 1,0 und 15 mm: Fehler bis 1,2 mm; 0,3 und 5 mm: unter 0,5 mm) |

## Gemessen (MacBook M2 Pro, 16 GB)

Synthetische Probe (`kevscan synth`): Quader 200 × 100 × 50 mm auf dem Boden, 10 Fotos und 30 Videobilder 1920 × 1440,
LiDAR-Ersatz 256 × 192 mit Rauschen (2 mm + 0,4 %, langwelliger Versatz, Mischpixel an Kanten).

| Schritt | Large | Small |
|---|---|---|
| PromptDA je Bild (1008 × 756, MPS; Median) | 1,6 bis 1,9 s | 0,26 bis 0,28 s |
| Modell laden | 3 bis 7 s | 0,5 s |
| TSDF je Bild (2 mm, 2,6 Mio. Voxel) | 0,03 s (MPS) bis 0,07 s (numpy) | 0,07 s |
| Auswertung gesamt (40 bzw. 22 Bilder) | 77 bis 95 s | 15 bis 17 s |
| Grundriss des Netzes, ohne Lagefehler (wahr 200 × 100) | 200,4 × 101,3 | 201,6 × 103,3 |
| Grundriss des Netzes, mit Lagefehlern | 198,1 × 97,8 | 199,5 × 102,3 |
| Höhe (wahr 50) | 51,0 bis 53,0 | 50,3 bis 50,9 |

Maße nach `referenz_vermessen` über den Kernel (`scan_importieren`, dann `referenz_vermessen`; alle drei Maße frei,
Startwerte 214 × 108 × 54 mm, kein bekanntes Maß). Die Lagen im Scan sind wie bei ARKit verfälscht (je Bild 3 mm und
0,3° je Achse, dazu Drift bis 9 mm und 0,9°), gerendert wurde mit den echten. Fehler in mm (laenge / breite / hoehe):

| Tiefe aus | Bilder | mit Tiefenbedingung | ohne Tiefenbedingung (nur Kanten, ARKit-Kameras) |
|---|---|---|---|
| Small | 10 (8 genutzt) | +0,13 / +0,29 / +0,03 (Sigma 0,6 / 0,7 / 0,2) | −0,56 / −0,29 / −0,14 (Sigma 4,7 / 2,3 / 1,2) |
| Small | 3 | +0,35 / +0,05 / −0,01 (Sigma 2,1 / 0,3 / 0,2) | −0,28 / −0,37 / −0,28 (Sigma 7,8 / 3,9 / 1,9) |
| Large | 10 (8 genutzt) | −0,48 / −0,17 / −0,03 (Sigma 0,8 / 0,5 / 0,2) | −1,09 / −0,56 / −0,30 (Sigma 4,7 / 2,3 / 1,2) |
| Large | 3 | −0,43 / −0,42 / +0,04 (Sigma 2,5 / 0,4 / 0,3) | −1,70 / −0,41 / −0,39 (Sigma 7,2 / 3,6 / 1,8) |

Die eingepassten Kameras liegen 5 bis 9 mm und 0,15 bis 0,6° neben den (verrauschten) ARKit-Lagen, also im Bereich
des eingebauten Fehlers (3 mm je Achse plus Drift bis 9 mm). Der Boden des Scans liegt bei der Probe mit Lagefehlern
5 mm neben dem echten (geschätzt aus den verrauschten LiDAR-Punkten).

Lesart: Mit bekannten Kameras sind die Kanten der synthetischen Bilder (scharf, kontrastreich) schon allein auf
0,3 bis 1,7 mm genau. Mit der Tiefe bleibt jeder Fehler unter 0,5 mm, auch mit drei Bildern, und die angegebene
Unsicherheit ist klein und ehrlich (Sigma 0,2 bis 2,5 statt 1,2 bis 7,8 mm). Die an dieser Szene verzerrte
Large-Tiefe zieht die Länge um knapp 0,5 mm. Echte Kanten sind weicher, Masken ungenauer; dort ist der Gewinn der
Tiefe größer zu erwarten, nachgewiesen ist er noch nicht. Die erste Fassung (Tiefengewicht 1,0, Bindung 15 mm, Lage
nur über die Oberfläche, Höhe frei) lag bei drei Bildern ohne Tiefe 4,3 mm daneben, mit Tiefe 0,5 mm, die Kameras
wanderten dabei gemeinsam bis 6° (siehe S11, S12).

Laufzeit `referenz_vermessen` 18 bis 34 s (8 Bilder, zwei Durchgänge, je nach Last), ohne Tiefe 12 s, mit drei
Bildern 8 bzw. 5 s; `scan_importieren` 15 s (Small, 22 Bilder) bzw. 78 s (Large, 40 Bilder).

Echter Scan (Kevins iPhone 15 Pro, 22.10.2026 21:38, 78 s, 779 Videobilder 1920 × 1440 HEVC, 61 Fotos 4032 × 3024 mit
eigener Tiefe, Box 306 × 402 × 341 mm gesetzt). Gegenstand laut Fotos: eine geöffnete Frühstücksflocken-Packung mit
aufgeklappten Laschen, stehend auf einem Sofapolster.

| | Large, letzter Stand (101 Bilder: 61 Fotos, 40 Videobilder) | Large, erster Stand | Small, erster Stand (73 Bilder) |
|---|---|---|---|
| Bilder wählen (Schärfe von 779 Videobildern) | 3,3 s | 4,7 s | 10,4 s |
| Bilder holen (Fotos verkleinern, vier Fäden) | 5,2 s | 11,4 s | 15,2 s |
| PromptDA je Bild (Median) | 1,61 s (172 s) | 1,84 s (203 s) | 0,26 s (25 s) |
| TSDF (7,7 Mio. Voxel, 2 mm) je Bild | 0,11 s (MPS) | 0,90 s (numpy) | 0,58 s (numpy) |
| Masken | 16 s (zweifach, vier Fäden) | 117 s | 48 s |
| gesamt | 216 s (`scan_importieren`, 218 s) | 437 s | 148 s |
| Grundriss des Netzes | 206,3 × 155,6 mm | 206,3 × 155,6 mm | 207,1 × 158,0 mm |
| Oberkante (99,9 %) | 303,7 mm | 303,7 mm | 294,4 mm |
| Streuung Tiefe gegen Netz (Median / 90 %) | 3,4 / 9,6 mm | 3,4 / 9,6 mm | 3,8 / 10,9 mm |
| PromptDA gegen LiDAR (Median) | 4,4 mm | 4,4 mm | 4,1 mm |
| Maßstab PromptDA an LiDAR (Median, Spanne) | 0,982 (0,950 bis 1,004) | 0,982 | 0,979 (0,953 bis 0,998) |
| Netzpunkte von mindestens 2 Bildern gesehen | 79 % | 79 % | 79 % |

Auch am echten Scan liegt PromptDA rund 2 % zu weit; ohne Angleichen an LiDAR rückte bei 0,5 m Abstand jede Fläche
um etwa 1 cm nach innen (an der Probe ohne Angleichen: 192 × 92 × 47 statt 200 × 100 × 50 mm). Die ARKit-Lagen passen
untereinander auf wenige Millimeter (Streuung der Tiefe aller 101 Bilder gegen das gemeinsame Netz im Median 3,4 mm).
Die Hülle enthält die aufgeklappten Laschen; die Oberkante hängt an ihnen (Large 304, Small 294 mm).

`referenz_vermessen` mit einem geratenen Messmodell (Quader oben offen, frei Länge, Breite, Höhe, Wand; 12 Bilder,
33 s): 190,6 ± 1,9 × 123,1 ± 13,4 × 288,5 ± 3,8 mm, Wand an der unteren Grenze 1 mm, 2 Bilder verworfen. Das Modell
kennt weder die Laschen noch den weichen Untergrund; die Kameras werden dabei um 17 mm einzeln verschoben (Maß dafür,
dass Modell und Gegenstand nicht zusammenpassen). Als Genauigkeitsnachweis taugt der Lauf deshalb nicht, als
Durchstich der ganzen Kette am echten Scan schon.

## Grenzen und offene Punkte

- PromptDA Large lag auf den synthetischen Bildern ungenauer als Small (Neigung der Deckfläche um 10 bis 15 mm,
  Seiten 10 mm zu weit); an echten Aufnahmen steht der Vergleich aus.
- Netz ohne Unterseite; dünne Teile unter etwa zwei Voxeln fehlen. Glas, Spiegel, Schwarz: LiDAR-Lücken.
- Der Boden gilt als eben und waagrecht (Ebene aus ARKit bzw. geschätzt); ein weicher Untergrund (Sofa) oder ein
  schräger Tisch verschiebt Höhe und Lage. Vermessen nimmt an, dass das Modell auf z = 0 steht.
- Die Gewichte der Tiefenbedingung sind nur an der synthetischen Probe abgestimmt; an einem echten Gegenstand mit
  bekannten Maßen (Messschieber) steht der Nachweis aus.
- Die App zeigt die laufende Auswertung als „Object Capture läuft“ (Feld `laeuft` = `capture`); ein eigener Text wäre
  eine kleine Änderung in `ReferenzPanels.swift`.
- macOS-Firewall: Ist sie an, fragt macOS beim ersten Empfang, ob Python eingehende Verbindungen annehmen darf.
- Bonjour-Name ist der Rechnername; bei zwei Macs mit Kev CAD sieht das iPhone beide.
