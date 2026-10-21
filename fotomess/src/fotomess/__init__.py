"""fotomess: ein parametrisches build123d-Modell aus wenigen Fotos oder einem Video vermessen (Kev CAD, Phase 4).

Module
- kamera: Lochkamera, Lage im Objektsystem, analytische Projektionsableitung, Umrechnung zu fotocad
- modell: Netz linear in den Maßen (fotocad.cad_netz), Kanten-Topologie, Gelenke, Kantenpunkte je Ansicht
- bild: Pyramide, Kanten nach Richtung, Maskenrand, nächste Kante je Pixel (Distanztransformation mit Marken)
- masken: Studio (Weiß), Apple Vision (Swift-Hilfe), Farbe, Kombination
- video: Einzelbilder bewerten, auswählen, holen
- gl: GPU (moderngl): Tiefenbild für die Sichtbarkeit, Silhouetten-Atlas für die Grobsuche
- start: Grobsuche der Kameralage über die Silhouette
- einpassen: Levenberg-Marquardt auf Kantenabständen, Kameras einzeln oder gemeinsam mit den Maßen
- ablauf: Gesamtablauf (Grobsuche, Kandidaten, Kameras, Bündel, Ausreißer)
- unsicherheit: Kovarianz, Jackknife, Empfehlungen (Nachmessen, Zusatzaufnahme), Einrasten
- kontrolle: Kontrollbilder (Modellkanten über dem Foto)
- modelle.rollwagen: Messmodell ALUTEC 05200; benchmark: Küche, Rollwagen, Vergleich mit fotocad
Strategie und Ergebnisse: STRATEGIE.md und BENCHMARK.md im Ordner fotomess/.
"""
