# Umgebungen (HDRI) für Renderings

Alle drei Bilder stammen unverändert aus Blender 4.5.3 LTS (`/Applications/Blender.app/Contents/Resources/4.5/datafiles/
studiolights/world/`), umgewandelt von EXR (DWAB) nach Radiance-HDR, 1024 × 512, damit macOS (ImageIO) sie lesen kann.
Nichts wurde heruntergeladen.

Lizenz laut `license.txt` dort: **„All HDRIs are licensed as CC0.“** Erstellt von Greg Zaal (Poly Haven,
https://polyhaven.com), 1K-Fassung der Originale.

| Datei | Szene | Blender-Datei | Original (laut license.txt) |
|---|---|---|---|
| `halle.hdr` | `werkstatt` | `studio.exr` | „Probably“ https://polyhaven.com/a/studio_small_01 |
| `garten.hdr` | `draussen` | `forest.exr` | https://polyhaven.com/a/ninomaru_teien |
| `innenraum.hdr` | `wohnraum` | `interior.exr` | https://polyhaven.com/a/hotel_room |

„Werkstatt“ ist damit vorerst eine dunkle Studiohalle mit Lampen und grauem Boden; eine echte Werkstatt-HDRI (etwa von
Poly Haven, ebenfalls CC0) wird erst nach Kevins Freigabe geladen.

Die Studio-Umgebung (`studio`, `freigestellt`) ist selbst erzeugt (Softboxen auf neutralem Grau, im Code der App bzw.
als Flächenlichter in Blender), ohne fremde Lizenz.

Eigene Umgebungen: `render(umgebung="/pfad/bild.hdr")` oder eine `.hdr` in
`~/Library/Application Support/de.upvis.kevcad/umgebungen/` (Name ohne Endung als Szene nutzbar). Nur Bilder mit
freier Lizenz und belegter Quelle.
