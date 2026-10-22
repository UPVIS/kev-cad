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
   (15 mm, 1,5°), Tiefe als zusätzliche Bedingung (Tiefe des Modells gegen gemessene Tiefe, Cauchy, Gewicht nach
   Konfidenz), zweiter Durchgang nach Nachführen der Lage. Das Netz liegt danach am Modell (`lage`).

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

## Gemessen (MacBook M2 Pro, 16 GB)

Synthetische Probe (`kevscan synth`): Quader 200 × 100 × 50 mm auf dem Boden, 10 Fotos und 30 Videobilder 1920 × 1440,
LiDAR-Ersatz 256 × 192 mit Rauschen (2 mm + 0,4 %, langwelliger Versatz, Mischpixel an Kanten).

| Schritt | Large | Small |
|---|---|---|
| PromptDA je Bild (1008 × 756, MPS) | 1,9 s | 0,28 s |
| Modell laden | 3 bis 7 s | 0,5 s |
| TSDF je Bild (2 mm) | 0,07 s | 0,07 s |
| Auswertung gesamt (40 bzw. 22 Bilder) | 95 s | 17 s |
| Hüllmaß des Netzes (wahr 200 × 100 × 50) | Grundriss 200,4 × 101,3, Hülle mit Krempe | 202,4 × 103,1 × 50,9 |

Maße nach `referenz_vermessen` über den Kernel (`scan_importieren`, dann `referenz_vermessen`; alle drei Maße frei,
Startwerte 214 × 108 × 54 mm, kein bekanntes Maß). Die Lagen im Scan sind wie bei ARKit verfälscht (je Bild 3 mm und
0,3° je Achse, dazu Drift bis 9 mm und 0,9°), gerendert wurde mit den echten. Fehler in mm (laenge / breite / hoehe):

| Tiefe aus | Bilder | mit Tiefenbedingung | ohne Tiefenbedingung (nur Kanten, ARKit-Kameras) |
|---|---|---|---|
| Small | 10 (8 genutzt) | +0,10 / +0,30 / +0,07 (Sigma 0,6 / 0,7 / 0,1) | +0,07 / +0,07 / +0,15 (Sigma 14 / 7 / 3,5) |
| Large | 10 (8 genutzt) | −0,48 / −0,07 / +0,75 (Sigma 1,3 / 0,8 / 0,5) | −0,04 / −0,03 / +0,02 (Sigma 14 / 7 / 3,5) |
| Large | 3 | −0,42 / −0,51 / +0,45 | +4,27 / +1,95 / +0,98 |

Lesart: Mit bekannten Kameras sind die Kanten der synthetischen Bilder (scharf, kontrastreich) schon allein auf
Zehntelmillimeter genau; die Tiefe bringt dort nichts und zieht mit der verzerrten Large-Tiefe leicht weg. Mit wenigen
Bildern trägt die Tiefe (3 Bilder: 4,3 statt 0,5 mm), und die Unsicherheit wird ehrlich klein angegeben (Sigma
0,1 bis 1,3 statt 3,5 bis 14 mm). Echte Kanten sind weicher, Masken ungenauer; dort ist der Gewinn der Tiefe größer zu
erwarten, nachgewiesen ist er noch nicht. Laufzeit `referenz_vermessen` 25 s (8 Bilder, zwei Durchgänge), ohne Tiefe
11 s; `scan_importieren` 15 s (Small, 22 Bilder) bzw. 78 s (Large, 40 Bilder).

Echter Scan (Kevins iPhone 15 Pro, 22.10.2026 21:38, 78 s, 779 Videobilder 1920 × 1440 HEVC, 61 Fotos 4032 × 3024 mit
eigener Tiefe, Box 306 × 402 × 341 mm gesetzt). Gegenstand: oben offener, rechteckiger Behälter.

| | Large (101 Bilder: 61 Fotos, 40 Videobilder) | Small (73 Bilder: 61 Fotos, 12 Videobilder) |
|---|---|---|
| Bilder wählen (Schärfe von 779 Videobildern) | 4,7 s | 10,4 s |
| Bilder holen (Fotos verkleinern) | 11,4 s | 15,2 s |
| PromptDA je Bild | 1,84 s (203 s) | 0,26 s (25 s) |
| TSDF (7,7 Mio. Voxel, 2 mm) je Bild | 0,90 s numpy | 0,58 s numpy; mit MPS gemessen 0,24 s |
| Masken | 117 s (vierfach) | 48 s (dreifach); jetzt zweifach und vier Fäden |
| gesamt | 437 s | 148 s |
| Grundriss des Netzes | 206,3 × 155,6 mm | 207,1 × 158,0 mm |
| Oberkante | 303,7 mm (mit Bodenresten im Netz) | 294,4 mm (Bodenreste entfernt) |
| Streuung Tiefe gegen Netz (Median / 90 %) | 3,4 / 9,6 mm | 3,8 / 10,9 mm |
| PromptDA gegen LiDAR (Median) | 4,4 mm | 4,1 mm |
| Maßstab PromptDA an LiDAR (Median, Spanne) | 0,982 (0,950 bis 1,004) | 0,979 (0,953 bis 0,998) |
| Netzpunkte von mindestens 2 Bildern gesehen | 79 % | 79 % |

Auch am echten Scan liegt PromptDA rund 2 % zu weit; ohne Angleichen an LiDAR rückte bei 0,5 m Abstand jede Fläche
um etwa 1 cm nach innen (an der Probe ohne Angleichen: 192 × 92 × 47 statt 200 × 100 × 50 mm). Die ARKit-Lagen passen untereinander auf wenige Millimeter (Streuung der Tiefe aller 101 Bilder gegen das
gemeinsame Netz im Median 3,4 mm).

## Grenzen und offene Punkte

- PromptDA Large lag auf den synthetischen Bildern ungenauer als Small (Neigung der Deckfläche um 10 bis 15 mm,
  Seiten 10 mm zu weit); an echten Aufnahmen steht der Vergleich aus.
- Netz ohne Unterseite; dünne Teile unter etwa zwei Voxeln fehlen. Glas, Spiegel, Schwarz: LiDAR-Lücken.
- Die App zeigt die laufende Auswertung als „Object Capture läuft“ (Feld `laeuft` = `capture`); ein eigener Text wäre
  eine kleine Änderung in `ReferenzPanels.swift`.
- macOS-Firewall: Ist sie an, fragt macOS beim ersten Empfang, ob Python eingehende Verbindungen annehmen darf.
- Bonjour-Name ist der Rechnername; bei zwei Macs mit Kev CAD sieht das iPhone beide.
