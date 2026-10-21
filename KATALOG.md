# Kev CAD · Katalog für Materialien und Lagerteile

Version 1 (21.10.2026). Verbindlich für die Dateien unter `kernel/src/kevcad/katalog/`, für Kevins eigenen Katalog
(`~/Library/Application Support/de.upvis.kevcad/katalog/*.json`) und für `<projekt>/katalog.json`.

## Ebenen und Zusammenführen

1. mitgeliefert: `kernel/src/kevcad/katalog/*.json`
2. eigener Katalog: `~/Library/Application Support/de.upvis.kevcad/katalog/*.json` (Claude schreibt neue Einträge nach
   `eigene.json`)
3. Projekt: `<projekt>/katalog.json`

Jede Datei ist ein Objekt `{"version": 1, "materialien": [...], "teile": [...]}` (beide Listen optional). Gleiche `id`
in einer späteren Ebene ersetzt den Eintrag ganz; `"entfernt": true` blendet einen Eintrag aus.

## Inventar-Regel und Freigabe

Gebaut wird nur aus dem Inventar (PLAN-PHASE2.md, P6): Jedes Teil im Modell stammt aus `verbauen()` eines
freigegebenen Lagerteils oder ist ein ausdrücklich gekennzeichnetes 3D-Druckteil (`lager.druckteil`) aus einem
freigegebenen Material mit `druckbar: true`. Jeder Eintrag (Material oder Teil) hat dafür optional

| Feld | Werte | Bedeutung |
|---|---|---|
| `status` | `frei` (Standard, wenn das Feld fehlt) \| `vorgeschlagen` | Vorschläge von Claude (`stock_define`, `material_define`) sind erst nach Kevins Freigabe im Lagerkatalog verbaubar |
| `vorgeschlagen_am`, `vorgeschlagen_von` | Datum, `agent` | nur bei Vorschlägen |

Freigeben heißt: die App speichert den Eintrag mit `status: "frei"`; Ablehnen löscht ihn.

Der mitgelieferte Normkatalog (Rohre, Profile, Schrauben, Platten …) zählt als Inventar (Kevin, 21.10.2026): seine
Einträge haben kein `status`-Feld und sind damit freigegeben.

## Material

```json
{
  "id": "stahl-s235",
  "name": "Stahl S235",
  "gruppe": "Stahl",
  "dichte": 7.85,
  "farbe": "#8A9099",
  "metallisch": 0.8,
  "rauheit": 0.45,
  "preis_je_kg": 2.4,
  "preis_quelle": "Richtwert Stahlhandel",
  "preis_stand": "2026-10",
  "aliase": ["stahl", "baustahl", "s235jr", "steel"]
}
```

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `id` | ja | eindeutig, Kleinbuchstaben, Bindestriche |
| `name`, `gruppe` | ja | Anzeige; `gruppe` z. B. Stahl, Edelstahl, Aluminium, Buntmetall, Holz, Holzwerkstoff, Kunststoff |
| `dichte` | ja | g/cm³ |
| `farbe` | ja | sRGB-Hex für den Viewer |
| `metallisch`, `rauheit` | nein | 0…1 für spätere Renderings |
| `preis_je_kg` | nein | € netto, Richtwert |
| `preis_quelle`, `preis_stand` | wenn Preis | Herkunft, Monat |
| `aliase` | nein | weitere Namen für `material=` in `show()` und für die Suche (klein geschrieben) |
| `druckbar` | nein | `true` für Materialien, aus denen 3D-Druckteile entstehen dürfen (PLA, PETG, ABS, ASA, TPU, PA, Harz …) |

## Lagerteil

```json
{
  "id": "rohr-en10220-42.4x2.0",
  "art": "rohr",
  "name": "Rohr 42,4 × 2,0",
  "norm": "DIN EN 10220",
  "masse": {"d": 42.4, "s": 2.0},
  "material": "stahl-s235",
  "kg_je_m": 1.99,
  "stangenlaenge": 6000,
  "preis": {"je_m": 4.8, "quelle": "Richtwert", "stand": "2026-10"},
  "tags": ["rund", "gewinderohr"]
}
```

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `id` | ja | eindeutig |
| `art` | ja | siehe Tabelle unten |
| `name` | ja | Anzeige mit deutschem Komma und „×" |
| `norm` | nein | Norm oder Hersteller (z. B. „DIN EN 10219", „Raster 40 Nut 8, item-ähnlich") |
| `masse` | ja | Maße in mm je `art` |
| `material` | ja | `id` eines Materials |
| `kg_je_m` | nein | Tabellenwert; sonst aus Querschnitt × Dichte berechnet |
| `stangenlaenge` | nein | Standardlänge für den Zuschnitt (mm); Platten: `platte: [b, h]` statt dessen |
| `preis` | nein | `je_m` (Stangenware), `je_m2` (Platten), `je_stueck` (Schrauben, Kleinteile) plus `quelle`, `stand` |
| `tags` | nein | Suchbegriffe |

### Arten und ihre Maße

| `art` | `masse` | Querschnitt |
|---|---|---|
| `rohr` | `d` Außendurchmesser, `s` Wand | Kreisring |
| `vierkantrohr` | `a`, `s`, optional `r` Außenradius (Standard 2·s für s ≤ 6, sonst 2,5·s) | Quadrat mit Ecken­radius, hohl |
| `rechteckrohr` | `b`, `h`, `s`, optional `r` | Rechteck, hohl |
| `flach` | `b`, `s` | Rechteck |
| `rund` | `d` | Kreis |
| `vierkant` | `a` | Quadrat |
| `winkel` | `a`, `b`, `s`, optional `r` Innenradius | L-Profil |
| `u_profil` | `h`, `b`, `s` (Steg), `t` (Flansch) | U-Profil, vereinfacht ohne Neigung |
| `nutprofil` | `raster` (20/30/40/45/…), `nut` (5/6/8/10), `variante` (`leicht`/`schwer`), optional `a`, `b` für 2er/4er (z. B. 40×80) | vereinfachte Kontur mit T-Nuten und Kernbohrung; Gewicht aus `kg_je_m` |
| `holz` | `b`, `h` | Rechteck (Kantholz, Latte, Brett) |
| `platte` | `s` Dicke; optional `platte: [b, h]` Standardformat | Zuschnitt aus Fläche (siehe verbauen) |
| `schraube` | `typ` (bd_warehouse-Klasse, z. B. `SocketHeadCapScrew`), `norm` (z. B. `iso4762`), `groesse` (z. B. `M8-1.25`), Länge bei `verbauen` | aus bd_warehouse |
| `mutter`, `scheibe` | `typ`, `norm`, `groesse` | aus bd_warehouse |

## API in model.py (Vertrag für K2)

```python
from kevcad import lager, show, step

rohr = lager.teil("vierkantrohr", a=40, s=3)        # nach Art und Maßen (genau, sonst Fehler mit Vorschlägen)
rohr = lager.teil("rohr-en10220-42.4x2.0")          # nach id
treffer = lager.suche("vierkantrohr 40")            # Liste von Lagerteilen (für Claude und zum Ausprobieren)

bein = rohr.verbauen(laenge=882, name="Gestell/Bein vorn links", gehrung=(0, 0))
show(Pos(0, 0, 0) * bein, "Gestell/Bein vorn links")

platte = lager.teil("platte", s=18, material="multiplex-birke")
deckel = platte.verbauen(breite=800, tiefe=600, name="Deckel")       # Rechteck; oder form=<Sketch/Face>
schraube = lager.teil("schraube", norm="iso4762", groesse="M8-1.25")
s1 = schraube.verbauen(laenge=60, name="Schrauben/M8x60 1")
```

- `verbauen` gibt ein build123d-`Part` zurück (Stangenware entlang +Z ab z = 0, Querschnitt mittig; Platten in der
  XY-Ebene ab z = 0; Schrauben wie in bd_warehouse) mit Name, Farbe und Material des Lagerteils.
- `gehrung=(w_anfang, w_ende)` in Grad um die lokale X-Achse; `laenge` ist das Maß an der längsten Kante.
- Jede `verbauen`-Zeile erscheint in der Stückliste, auch wenn das Teil später gebohrt oder gekürzt wird.
- Neue 3D-Druckteile: `lager.druckteil(form, name="Halter/Clip", material="petg", verfahren="3d-druck")` – `form` ist
  die selbst konstruierte build123d-Form, `material` ein freigegebenes Material mit `druckbar: true`, `verfahren`
  `3d-druck` oder `harzdruck`. Stücklistenzeile `art: "druckteil"` mit Masse und Filamentkosten.
- Ist die Inventar-Regel an, ist jedes gezeigte Teil ohne `verbauen`/`druckteil` ein Verstoß (Skizzen aus `execute`
  ausgenommen).

## Kameras und Objektive

Phase 5 (Strang KAM), additiv: drei weitere Arten in `teile`, geprüft in `kernel/src/kevcad_kernel/optik.py`. Sie haben
eigene Felder statt `masse`/`material` (beide freiwillig), werden nicht mit `verbauen`, sondern mit `lager.kamera(...)`
und `lager.kamerazubehoer(...)` eingesetzt und stehen dann als Inventar in der Stückliste (Gewicht aus `gewicht`, Preis
aus `preis.je_stueck`). Mitgeliefert: `kernel/src/kevcad/katalog/kameras.json`. Kevins eigene Objektive (per EAN)
kommen wie andere Zukaufteile in den eigenen Katalog (über MCP `stock_define` als Vorschlag).

Lokale Koordinaten aller Einträge: x Blickrichtung bzw. nach vorn, y links, z oben, mm. Ursprung bei Kameras die
Sensormitte, bei Objektiven die Bajonett-Auflage, bei Zubehör laut `ursprung`.

### Kamera (`art: "kamera"`)

```json
{
  "id": "sony-fx6", "art": "kamera", "name": "Sony FX6 (ILME-FX6V)", "kurzname": "FX6",
  "hersteller": "Sony", "modell": "ILME-FX6V", "bajonett": "sony-e", "auflagemass": 18.0,
  "standard_format": "ff-uhd",
  "formate": [{"id": "ff-uhd", "name": "Vollformat UHD 3840 × 2160", "modus": "vollformat",
               "sensor_mm": [35.7, 20.1], "aufloesung": [3840, 2160], "fps_max": 60, "zerstreuungskreis": 0.027}],
  "gehaeuse": {"b": 114, "h": 116, "t": 153, "achse_hoehe": 74, "achse_seitlich": 5.8, "bajonett_vorstand": 0,
               "ring_vorstand": 4},
  "gewicht": 890,
  "bezugspunkte": {"stativ_1_4": {"pos": [-33, 0, -74], "von": "front", "richtung": [0, 0, -1], "hinweis": "…"}},
  "geometrie": {"modul": "kevcad.geometrie.kamerasystem", "funktion": "sony_fx6"},
  "hinweis": "…", "quellen": ["…"], "tags": ["fx6"]
}
```

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `hersteller`, `modell`, `bajonett` | ja | `bajonett` als Kennung (`sony-e`, `pl`, `ef` …); Objektive brauchen dasselbe |
| `kurzname` | nein | Standardname der Kamera in model.py („FX6“) |
| `auflagemass` | ja | Bajonett-Auflage bis Sensorebene in mm (E-Mount 18) |
| `formate` | ja | Aufnahmeformate: `id`, `name`, `modus`, `sensor_mm` (aktive Fläche [b, h]), `aufloesung` [px, px], optional `fps_max`, `zerstreuungskreis` (mm, sonst Diagonale / 1500), `hinweis`. Die aktive Höhe rechnet der Kernel aus der Breite und dem Seitenverhältnis der Auflösung (quadratische Pixel); weicht die Angabe mehr als 3 % ab, ist der Eintrag ungültig |
| `standard_format` | nein | `id` des Formats ohne Angabe in model.py |
| `gehaeuse` | ja | `b`, `h`, `t` (Breite, Höhe, Tiefe ohne Anbauten), `achse_hoehe` (Bildachse über der Unterseite), `achse_seitlich` (Bildachse rechts der Gehäusemitte, von hinten gesehen), `bajonett_vorstand` (Auflage vor der Gehäusefront), `ring_vorstand` (nur Darstellung; der Ring endet an der Auflage, sichtbar ist davon nur der Teil vor der Front, sonst stäke das Objektiv im Ring) |
| `gewicht` | nein | g, für Stückliste und Schwerpunkt |
| `schwerpunkt` | nein | [x, y, z] lokal |

### Objektiv (`art: "objektiv"`)

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `hersteller`, `bajonett` | ja | wie bei der Kamera |
| `brennweite` | ja | mm; Festbrennweite als Zahl, Zoom als [kurz, lang] |
| `lichtstaerke` | ja | kleinste Blendenzahl bzw. T-Wert |
| `blendenart` | nein | `f` (Standard) oder `t` (Cine) |
| `blende_max` | nein | größte Blendenzahl (z. B. 22) |
| `naheinstellgrenze` | ja | mm ab Sensorebene |
| `bildkreis` | ja | mm; kleiner als die Formatdiagonale → Warnung „vignettiert“ |
| `laenge`, `frontdurchmesser` | ja | mm, Länge ab Bajonett-Auflage |
| `filter`, `gewicht`, `bildstabilisator` | nein | mm, g, bool |

### Kamerazubehör (`art: "kamerazubehoer"`)

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `typ` | ja | `kaefig`, `baseplate`, `rod`, `rosette`, `akkuplatte`, `akku`, `griff`, `monitor`, `sonstiges` |
| `masse` | nein | `b`, `h`, `t` oder `d`, `l` in mm (vereinfachte Form, wenn `geometrie` fehlt) |
| `gewicht`, `schwerpunkt` | nein | g, [x, y, z] lokal |
| `ursprung` | nein | Text: wo der lokale Ursprung liegt und wohin x zeigt |

### Gemeinsame Felder

| Feld | Bedeutung |
|---|---|
| `bezugspunkte` | {name: {`pos` [x, y, z], `richtung` [x, y, z] (nur Information), `von`: `"front"` (nur Kameras: x ab der Gehäusefront, wandert mit `bajonett_vorstand`), `hinweis`}}. Namen aus Kleinbuchstaben, Ziffern und `_`. Kameras haben dazu immer `sensor`, `bajonett`, `auge` (Projektionszentrum) und `front` (Frontlinse) |
| `geometrie` | {`modul`: importierbares Modul, z. B. `kevcad.geometrie.kamerasystem`, oder `datei`: `.py` relativ zur Katalogdatei, `funktion`}. Die Funktion `f(eintrag: dict) -> Shape \| dict[str, Shape]` liefert die Form in lokalen Koordinaten, ein dict ergibt Unterteile. Ohne `geometrie` zeichnet Kev CAD Quader bzw. Zylinder aus den Maßen |
| `hinweis` | Text: was belegt, was angenommen ist, was Kevin besitzt |
| `quellen` | Liste von Texten (Hersteller, Händler, Messung) |

### API in model.py

```python
from kevcad import lager, show

fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", blende=2.8, fokus=1500, name="FX6")
fx6.setzen((0, -400, 180), blick_auf=(800, 0, 108))               # Sensormitte, Blick auf einen Punkt
fx6.setzen(platte.bezugspunkt("kamera_1_4"), bezug="stativ_1_4")    # eine Location gibt auch die Ausrichtung vor
fx6.an("Rollwagen/Deckel", punkt=(150, 0, 40), richtung=(1, 0, 0), bezug="stativ_1_4", lokal=True)  # folgt dem Teil
fx6.einstellen(brennweite=50, blende=4, fokus="unendlich", format="dci")
show(fx6.koerper(), "Kamera FX6")       # Gehäuse und Objektiv, Inventar
fx6.bildwinkel_h, fx6.bildwinkel_v, fx6.schaerfe_nah, fx6.schaerfe_fern, fx6.hyperfokal, fx6.bezugspunkt("bajonett")

platte = lager.kamerazubehoer("tilta-es-t20-qrbp")
show(platte.verbauen("Rig/Baseplate", an=fx6.bezugspunkt("stativ_1_4"), bezug="kamera_1_4"), "Rig/Baseplate")
```

- `setzen`/`an`: `bezug` ist ein Bezugspunkt der Kamera, der an `position`/`punkt` liegt; Blick über `blick_auf` oder
  `richtung`, oben ist Welt-Z, `roll` in Grad (positiv im Uhrzeigersinn aus Sicht des Kameramanns).
- `an(teil, …, lokal=True)`: Angaben in den Koordinaten des gezeigten Teils (seiner Location); `an` nach dem `show` des
  Teils aufrufen. Die Kamera trägt das Teil als Eltern-Teil (`teil` in CAMERA_UPSERT) und folgt ihm.
- `verbauen(name, an=Location, bezug="punkt", drehung=(rx, ry, rz))`: setzt den eigenen Bezugspunkt auf `an` (gleiche
  Achsen) und meldet die Stücklistenzeile; `bezugspunkt(name)` liefert danach die Weltlage.
- Bildwinkel `2 · atan(Seite / (2 f))` (Fokus unendlich), Schärfentiefe mit `H = f² / (N c) + f`, Nahpunkt
  `s (H − f) / (H + s − 2 f)`, Fernpunkt `s (H − f) / (H − s)`; `s` ab Sensorebene, bei Cine-Objektiven der T-Wert als `N`.
