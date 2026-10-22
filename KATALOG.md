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
| `freigegeben_von`, `freigegeben_am` | `Kevin (iPhone)`, ISO 8601 (UTC) | nur bei einer Freigabe vom iPhone (MIRROR.md 1.1) |

Freigeben heißt: die App speichert den Eintrag mit `status: "frei"`; Ablehnen löscht ihn. Seit dem Strang
„Feinschliff 2“ (22.10.2026) geht das auch direkt im Projektfenster (Band und Dialog „Vorschläge freigeben“); Claude
öffnet den Dialog mit `freigabe_anfragen(ids, grund)` und gibt selbst nie frei (PROTOCOL.md, Abschnitt „Freigabe im
Projektfenster“). Seit dem Strang „Freigabe vom iPhone“ (22.10.2026) geht dieselbe Anfrage auch an die VoiceBridge-App
auf Kevins iPhone, direkt über den Spiegel-Socket und am Agenten vorbei (MIRROR.md, „Freigabe vom iPhone“).

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
| `spule_g` | nein | Druckmaterialien: g Filament je Kaufspule für die Einkaufsliste (BESTAND.md, „Filament“); ohne Angabe 1000 |
| `nachgiebig` | nein | `true` für weiche Werkstoffe (Schaum, Gummi, TPU, Gurtband): Die Prüfung meldet Überlappungen bis zur halben Dicke nur als „verformt“ (Hinweis) und lässt sie bei der Montage nicht als Hindernis zählen |
| `mechanik` | nein | Werkstoffkennwerte für die Statik (Abschnitt „Mechanik“); ohne sie rechnet die Statik das Teil nicht nach und sagt es |
| `hinweis` | nein | Text (z. B. wofür das Material gedacht ist) |

## Mechanik (Statik)

Additiv seit dem Strang „Statik Stufe 1“ (22.10.2026, PLAN-STATIK.md T6). Werte aus Normen oder Datenblättern, nie
erfunden; Schätzungen und Annahmen stehen im Eintrag. Spannungen und Moduln in N/mm² (MPa).

```json
"mechanik": {"e_modul": 70000, "schubmodul": 27000, "querkontraktion": 0.3, "streckgrenze": 160, "zugfestigkeit": 215,
             "quelle": "DIN EN 755-2:2016, EN AW-6060 T66 …; E, G und ν nach DIN EN 1999-1-1, 3.2.5",
             "annahme": "Zustand T66 angenommen …", "stand": "2026-10"}
```

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `e_modul` | ja | E-Modul (Holz: E₀,mean, Druckteile: in der Schicht X-Y) |
| `streckgrenze` / `zugfestigkeit` / `biegefestigkeit` | eine davon | Metall: Streckgrenze (ReH bzw. Rp0,2) und Zugfestigkeit (Mindestwerte); spröde Werkstoffe und Kunststoffe ohne Streckgrenze: Zugfestigkeit; Holz: charakteristische Biegefestigkeit f_m,k, Zug f_t,0,k |
| `druckfestigkeit` | nein | Holz: f_c,0,k |
| `schubmodul`, `querkontraktion` | nein | ohne Schubmodul rechnet die Statik G = E / (2 (1 + ν)), ν sonst 0,3 |
| `e_modul_z`, `zugfestigkeit_z` | nein | Druckteile: Werte quer zur Schicht laut Datenblatt (nur zur Information) |
| `quer_zur_schicht` | nein | Druckteile: Anteil der Festigkeit quer zu den Schichten, mit dem die Statik rechnet (0…1; PLA 0,5, PETG 0,4 wie die Druckregeln in `druck/regeln.py`, offen gedruckt und damit vorsichtiger als die Datenblätter) |
| `quelle` | ja | Norm, Datenblatt mit Version |
| `stand` | nein | Monat `JJJJ-MM` |
| `geschaetzt` | nein | `true` oder Liste der geschätzten Felder (z. B. `["querkontraktion"]`) |
| `annahme` | nein | was angenommen ist (Zustand, Festigkeitsklasse, volle Füllung) |

Mitgeliefert mit Mechanik (Stand 2026-10): Stahl S235, S355 (DIN EN 10025-2), Stahl verzinkt (wie S235 angenommen),
Edelstahl 1.4301 und 1.4404 (DIN EN 10088-2), Aluminium EN AW-6060 T66 (DIN EN 755-2) und EN AW-5754 O/H111
(DIN EN 485-2), Gusseisen EN-GJL-250 (DIN EN 1561), Nadelholz als C24 und Buche/Eiche als D30 (DIN EN 338:2016),
OSB/3 (DIN EN 12369-1), PLA (Bambu Lab PLA Basic TDS V2.0), PETG (Bambu Lab PETG HF TDS V1.0), Schrauben 8.8 (DIN EN
ISO 898-1) und A2-70 (DIN EN ISO 3506-1). Ohne Mechanik bleiben Messing, Kupfer, Multiplex, Siebdruckplatte, MDF,
Spanplatte, die übrigen Druckmaterialien und die Kunststoffe; neu ist das Material `beton` (Boden, Dichte nach DIN EN
1991-1-1) als Untergrund.

### Reibwerte

Eine Katalogdatei darf außer `materialien` und `teile` die Listen `reibwerte` und `reibgruppen` haben (mitgeliefert:
`reibwerte.json`):

```json
{"version": 1,
 "reibgruppen": {"Edelstahl": "Stahl", "Holzwerkstoff": "Holz"},
 "reibwerte": [{"a": "Elastomer", "b": "Mineralisch", "haft": 0.6, "bereich": [0.6, 0.85],
                "quelle": "Engineering ToolBox, Friction Coefficients (rubber on dry concrete)", "stand": "2026-10"}]}
```

`a`, `b` sind Material-ids oder Gruppen (`gruppe` des Materials); gesucht wird id/id, id/Gruppe, Gruppe/Gruppe und
zuletzt über die Reibgruppen. `haft` ist die Haftreibungszahl, mit der die Statik rechnet (bei einer Spanne der untere
Wert, trocken und sauber), `gleit` und `bereich` informativ, `geschaetzt` kennzeichnet Stellvertreterwerte (Kunststoff
auf Metall). Eine spätere Ebene ersetzt dieselbe Paarung.

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
| `bezugsquelle` | nein | `{"url", "name"}`: wo Kevin das Teil nachkauft; erscheint als Link in der Einkaufsliste (BESTAND.md) |

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

## Zukaufteil (Phase 3)

Fertig gekaufte Teile mit Hersteller und Nummer (Beispielwerte unten erfunden, EAN mit gültiger Prüfziffer):
Schubladenauszug, Scharnier, Rolle, Rollwagen (Kameras, Objektive und Kamera-Zubehör: Abschnitt „Kameras und
Objektive“). Sie
liegen in der Projekt-Ebene (`<projekt>/katalog.json`) oder, wenn Kevin sie in mehreren Projekten nutzt, im eigenen
Katalog; nie im mitgelieferten Katalog und nie im Git (Hersteller-CAD darf meist nicht weitergegeben werden).

```json
{
  "id": "alutec-05200",
  "art": "zukaufteil",
  "name": "ALUTEC Transportroller 05200",
  "hersteller": "ALUTEC",
  "mpn": "05200",
  "gtin": "4005187052008",
  "url": "https://www.beispiel-shop.de/p/alutec-05200",
  "bild": "https://www.beispiel-shop.de/bilder/05200.jpg",
  "preis": {"je_stueck": 24.99, "waehrung": "EUR", "brutto": true, "stand": "2026-10-21",
            "quelle": "https://www.beispiel-shop.de/p/alutec-05200"},
  "masse": {"l": 610, "b": 410, "h": 128},
  "gewicht": 1800,
  "material": "polypropylen",
  "cad": {"quelle": "download", "datei": "zukauf/alutec-05200/05200.step", "lizenz": "Herstellerbedingungen",
          "stand": "2026-10-21"},
  "ersatz": {"form": "quader", "masse": {"l": 610, "b": 410, "h": 128}},
  "einbaupunkt": {"pos": [0, 0, 0], "richtung": [0, 0, 1], "hinweis": "Mitte der Aufstandsfläche, Z nach oben"},
  "bezugspunkte": {"oben": {"pos": [0, 0, 128], "richtung": [0, 0, 1], "hinweis": "Ladefläche"}},
  "status": "vorgeschlagen",
  "hinweis": "Maße aus dem Shop, Höhe gemessen"
}
```

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `hersteller`, `mpn` | ja (außer bei reinen Shop-Artikeln ohne MPN, dann `shop_nr`) | Hersteller und Herstellernummer |
| `gtin` | nein | EAN/GTIN, 8 bis 14 Ziffern |
| `url`, `bild` | nein | Produktseite und Bild |
| `preis` | nein | `je_stueck`, `waehrung`, `brutto` (bool, wie im Shop angegeben), `stand` (Datum), `quelle` |
| `masse` | ja | Hüllmaße in mm: `l`, `b`, `h` (Quader) bzw. `d` mit `l` oder `h` (rund); nur `d` steht für eine Kugel (Hüllmaß d × d × d). Grundlage für den Ersatzkörper und die Prüfung des Imports |
| `gewicht` | nein | g; sonst aus Volumen × Dichte des Materials |
| `material` | nein | `id` eines Materials, für Farbe und Masse |
| `cad` | nein | `quelle` (`traceparts` \| `hersteller` \| `download` \| `bd_warehouse` \| `skript` \| `keins`), `datei` (relativ zum Ordner der Katalogdatei) oder bei `skript` `modul`/`datei` plus `funktion` wie bei den Kameras, bei `bd_warehouse` `klasse` (Modul.Klasse, z. B. `bearing.SingleRowDeepGrooveBallBearing`) und `parameter` (Objekt mit den Argumenten, z. B. `{"size": "M8-22-7", "bearing_type": "SKT"}`), `lizenz`, `stand`, optional `traceparts_id` |
| `ersatz` | nein | `form` (`quader` \| `zylinder`) und `masse`, beim Zylinder optional `achse` (`x` \| `y` \| `z`, Standard `z`; liegende Zylinder liegen auf z = 0); gilt, solange kein CAD da ist. Im Viewer halbtransparent, im Namen „(vereinfacht)“ |
| `einbaupunkt` | nein | Punkt (siehe unten) **im System der Quelle** (Hersteller-CAD, Skript, Ersatzkörper): wird beim Verbauen zum Ursprung, seine `richtung` zur +Z-Achse. Ohne Angabe: Mitte der Unterseite des Hüllquaders, Z oben |
| `bezugspunkte` | nein | benannte Punkte (siehe unten) **im System des verbauten Teils**, also nach dem Einbaupunkt, damit `Pos(...) * teil.bezugspunkt("oben")` zum gezeigten Teil passt; `pos` wie bei Kameras und Kamera-Zubehör (deren Bezugspunkte gelten im System der Kamera, Achsen wie die Kamera) |

Ein Punkt (Einbau- und Bezugspunkte) ist
`{"pos": [x, y, z], "richtung": [x, y, z], "x_richtung": [x, y, z], "hinweis": "…"}` in mm: `pos` ist der Ursprung, `richtung` die lokale Z-Achse (Standard `[0, 0, 1]`, etwa Blickrichtung eines Bajonetts oder
Normale einer Auflagefläche), `x_richtung` (optional, nicht parallel zu `richtung`) legt die Verdrehung um `richtung`
fest; ohne sie gilt die X-Achse, die build123d für `Plane(z_dir=richtung)` wählt (bei `richtung` = Z ist das +X).
Andere Felder sind bei Zukaufteilen nicht erlaubt (Prüfung und Location: `kevcad_kernel/bezugspunkte.py`).

Inventar-Regel: Ein Zukaufteil aus dem Dialog „Zukaufteil hinzufügen …“ in der App legt Kevin selbst an, es ist sofort
`frei`. Legt Claude es über MCP an, ist es `vorgeschlagen`, bis Kevin es im Lagerkatalog freigibt. Kameras, Objektive und
Kamera-Zubehör (`art` `kamera`, `objektiv`, `kamerazubehoer`) sind Sonderformen von Zukaufteilen mit eigenen Feldern
und folgen denselben Regeln.

In model.py:

```python
wagen = lager.zukauf("alutec-05200")                       # nach id, sonst lager.zukauf(mpn="05200", hersteller="ALUTEC")
rw = wagen.verbauen("Rollwagen")                           # Part am Einbaupunkt; Hersteller-CAD oder Ersatzkörper
show(Pos(0, 0, 0) * rw, "Rollwagen")
oben = wagen.bezugspunkt("oben")                           # Location für das Platzieren anderer Teile
```

Stücklistenzeile `art: "zukaufteil"` mit Hersteller, Nummer, Stückpreis mit Datum, Link und CAD-Quelle.

- `CATALOG.arten` (PROTOCOL.md) enthält `zukaufteil`; `stock_search` findet freigegebene Zukaufteile (art `zukaufteil`),
  verbaut werden sie mit `lager.zukauf(id)`, nicht mit `lager.teil`.
- Preise: Zukaufteile gehen mit dem Shoppreis in die Summe. Ist einer davon brutto, ergänzt `totals.preis_hinweis`
  „Zukaufteile zum Shoppreis brutto“ (z. B. „Richtpreise, Stand 2026-10; Zukaufteile zum Shoppreis brutto“).
- CSV (`bom_csv`): Zeilen von Zukaufteilen haben die Art „Zukaufteil“ bzw. „Zukaufteil (vereinfacht)“ und die
  Zusatzspalten Hersteller, Herstellernummer, EAN, Link, Preisstand (Datum mit „brutto“ bzw. „netto“) und CAD
  (Quelle bzw. „vereinfacht“); bei anderen Zeilen bleiben sie leer.

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
