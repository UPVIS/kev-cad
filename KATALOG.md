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
| `nachgiebig` | nein | `true` für weiche Werkstoffe (Schaum, Gummi, TPU, Gurtband): Die Prüfung meldet Überlappungen bis zur halben Dicke nur als „verformt“ (Hinweis) und lässt sie bei der Montage nicht als Hindernis zählen |

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
