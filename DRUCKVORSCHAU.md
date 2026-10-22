# Kev CAD · Druckvorschau (Vertrag)

Version 1 (22.10.2026). Verbindlich für die Live-Druckvorschau aus [PLAN-DRUCKVORSCHAU.md](PLAN-DRUCKVORSCHAU.md)
(Entscheidungen V1–V7). Änderungen nur gemeinsam: dieses Dokument, `protocol.py`, Testdateien und Swift-Decoder im
selben Commit (wie PROTOCOL.md). Einheiten: mm, g, m, s, €; Platte in Drucker-mm, Ursprung vorn links, Z oben.

## Drucker und Einstellungen

- Drucker: Bambu Lab P1P, 0,4-mm-Düse, Bauraum 256 × 256 × 250 mm, vorn links 18 × 28 mm gesperrt (wie die
  Druckprüfung, `druck/regeln.py`). Weitere Drucker später über `drucker.json` wählbar; bis dahin fest P1P.
- Projekt-Einstellungen in `kevcad.json` unter `"druck"` (alles optional):

```json
{"druck": {"drucker": "p1p-0.4", "strompreis_kwh": 0.32, "leistung_w": 350, "plattenwechsel_s": 120,
           "slicer": true, "filament": {"petg": "Bambu PETG Basic", "pla": "Amazon Basics PLA"}}}
```

- Filamentpreis und Dichte kommen aus dem Materialkatalog (`material_list`, Stand-Datum mitführen). Ein Filament­profil
  aus Bambu Studio gilt für Slicer-Läufe; fehlt es, nimmt der Kernel das mitgelieferte Systemprofil gleichen Materials.
- Präzisierung (V-K): Filamentprofile nur, wenn ihre `compatible_printers` (mit Vererbung über `inherits`) „Bambu Lab
  P1P 0.4 nozzle“ nennen (Benutzerprofile ohne eigene Liste erben sie); Reihenfolge `druck.filament`, dann Kevins Liste
  (`Amazon Basics PLA`, `Bambu PETG Basic @BBL X1C` …), dann das beste passende Systemprofil gleichen Typs („@BBL P1P“
  zuerst). `Bambu PETG Basic @BBL X1C` ist Bambus PETG-Basic-Profil für P1P und X1 (nennt den P1P 0.4).
  Seit dem Strang „Druckexport 2“ gilt dafür „Filamente und Presets“ (unten): Kevins Filamentliste mit Presets; die
  Liste der Systemprofile ist nur noch der Rückfall für Materialien ohne Filament in der Liste.
- `druck.platte` (additiv): Druckplatte als Bambu-Name (`Textured PEI Plate` Vorgabe, `High Temp Plate`, `Cool Plate`,
  `Engineering Plate`, `Supertack Plate`) oder kurz (`texturiert`, `glatt`, `cool`, `engineering`); geht als
  `curr_bed_type` in jeden Slicer-Lauf und ins 3MF (die Kommandozeile nähme sonst die Cool Plate, PETG bricht dort ab).
  Passt das Filament nicht zur Platte, meldet die Vorschau einen Fehler (`art: "platte"`) und slict nicht.
  `einstellungen.platte` nennt die benutzte Platte.

## Zweck eines Druckteils (model.py, additiv)

`lager.druckteil(form, name, material, verfahren="3d-druck", ausrichtung=None, zweck=None, anzahl=None)` (dazu
`gedruckt`, `neu_drucken` und `spaeter`, siehe „Gedruckt“ und „Auswahl und Objektnamen im Druckexport“)

- `zweck`: `"zier"` | `"funktion"` | `"tragend"` | `"bewegt"` | `"aussen"`; ohne Angabe schätzt der Kernel
  (`funktion`), markiert als Schätzung.
- Gleiche Teile erkennt der Kernel über Form und Material (gleicher Formschlüssel); `anzahl` nur, wenn ein Teil
  öfter gedruckt wird, als es im Modell steht (Ersatzteile).
- Präzisierung (Strang „Feinschliff 2“, 22.10.2026, additiv): Gleiche Form heißt **gleiche Form in Druckausrichtung,
  unabhängig von der Lage im Modell**. Teile, die einzeln in Weltlage gebaut sind (die vier Lenksperren und vier
  Stangenhalter des Kugelschiebers), haben je einen eigenen Formschlüssel und bildeten bisher je eine Gruppe. Der
  Prüfer „druckvorschau“ rechnet je Form eine Signatur (`druck/signatur.py`: Volumen, Oberfläche, Hauptmomente,
  Hüllmaße und Flächenhistogramm der Normalen in Druckausrichtung, dazu dritte und vierte Momente im Hauptachsensystem)
  und vergleicht Formen mit gleicher Signatur genau (Punkte der Oberfläche im Hauptachsensystem aufeinandergelegt, je
  Vorzeichenwechsel der Achsen; höchstens 0,4 % der Punkte weiter als 1,8 mm bzw. 2,5 Punktabstände). Passt nur eine
  Spiegelung, ist das Teil ein Spiegelbild und bildet eine eigene Gruppe „… (gespiegelt)“; symmetrische Teile passen
  auch gedreht und bleiben in einer Gruppe. Drehsymmetrische Formen (Hauptmomente fast gleich) gelten bei gleicher
  Signatur als gleich. Im CHECK additiv `druck.vorschau.formen[fid].signatur` und `.gleichteil: {"fid", "gespiegelt"}`
  (erste Form der Klasse); in der Vorschau additiv `teile[].gespiegelt_von` (Gruppen-id des Originals). Gruppennamen
  ohne gemeinsamen Anfang zählen die Teile auf („Schieberolle und Fangrolle (Druck)“). Ohne Signatur (älterer
  Rechenprozess) gilt der bisherige Schlüssel. Am Kugelschieber (Variante B): 5 Gruppen statt 15, Lenksperre ×4,
  Stangenhalter ×4 (deckungsgleich, nicht gespiegelt).

## Ergebnis (`druckvorschau`)

```json
{"run": 12, "stand": "schaetzung" | "slicer" | "gemischt", "drucker": "Bambu Lab P1P 0.4",
 "summe": {"platten": 3, "zeit_s": 61200, "zeit_mit_wechsel_s": 61440, "kosten": 9.85,
           "kosten_teile": {"filament": 8.12, "strom": 1.73},
           "material": [{"material": "petg", "name": "PETG", "g": 812.4, "m": 268.7, "kosten": 8.12,
                         "preis_kg": 10.0, "preis_stand": "2026-10", "stand": "schaetzung"}]},
 "platten": [{"nr": 1, "zeit_s": 22100, "material": [{"material": "petg", "g": 301.0}], "stand": "slicer",
              "teile": [{"name": "Kugelschieber/Stangenhalter vorn links (Druck)", "gruppe": "g3", "x": 40.0, "y": 52.0,
                         "drehung": 90, "umriss": [[x, y], ...]}],
              "auslastung": 0.62}],
 "teile": [{"gruppe": "g3", "name": "Stangenhalter (Druck)", "teile": ["…vorn links (Druck)", "…"], "anzahl": 4,
            "material": "petg", "zweck": "tragend", "zweck_geschaetzt": false,
            "g": 143.4, "m": 47.4, "zeit_s": 5400, "stand": "slicer", "abweichung": 0.06,
            "einstellungen": {"schicht_mm": 0.2, "waende": 4, "decken": 5, "boeden": 4, "fuellung": 0.25,
                              "muster": "gyroid", "stuetzen": "keine" | "baum" | "normal", "brim": false,
                              "ausrichtung": "…aus der Druckprüfung…"},
            "begruendung": ["tragend: 4 Wände, 25 % Gyroid", "Last längs der Schichten"],
            "hinweise": [{"schwere": "hinweis" | "warnung" | "fehler", "text": "PETG vorher trocknen (65 °C, 4 h)",
                          "art": "trocknen"}]}],
 "hinweise": [{"schwere": "warnung", "text": "ABS auf offenem Drucker verzieht sich", "art": "material"}],
 "slicer": {"zustand": "aus" | "wartet" | "rechnet" | "fertig" | "fehler", "fertig": 3, "gesamt": 5,
            "meldung": null}}
```

- `stand`: Werte der schnellen Schätzung oder des Slicers; je Teil, je Platte und in der Summe getrennt geführt.
- `abweichung`: relative Abweichung der Schätzung vom Slicer beim letzten Abgleich (für Kevin sichtbar als Genauigkeit).
- Hinweise im gemeinsamen Format (`schwere`, `text`, `art`); Fehler der Druckprüfung bleiben dort, hier nur Druckpraxis
  (Trocknen, Verzug, Brim, Stützen-Nacharbeit, AMS-Spülmenge, Düsenverschleiß bei CF, Erfolgsrisiko).

**Präzisierungen und additive Felder (V-K, 22.10.2026; nichts Bestehendes geändert):**

- `teile[]`: `g`, `m`, `zeit_s` und `kosten` gelten für alle `anzahl` Stück der Gruppe; je Stück additiv
  `je_stueck: {"g", "m", "zeit_s"}`. `teile` sind die Namen aus `show()`; `anzahl` ist mindestens ihre Zahl (mehr nur
  mit `druckteil(…, anzahl=)`). Additiv: `fest` (Liste der Einstellungen, die Kevin oder der Agent fest vorgegeben
  hat, dazu `"zweck"`, wenn der Zweck vorgegeben ist), `fest_von: {schlüssel: "kevin" | "agent"}` (wer jede feste
  Vorgabe gesetzt hat; aus `PRINT_SETTINGS.von` bzw. dem MCP), `profil: {"prozess", "filament"}`
  (Bambu-Studio-Profile), `risiko` (0–1, Fehldruck-Wahrscheinlichkeit), `stuetzen_g` (Stützmaterial aller Stück),
  `kosten`, `abweichung_material` (wie `abweichung`, für das Filament). `abweichung` = Schätzung der Zeit / Slicer − 1.
- `einstellungen.fuellung` ist ein Anteil 0–1 (0,25 = 25 %); `muster` wie in Bambu Studio (`gyroid`, `grid`,
  `cubic`, `honeycomb`, `rectilinear`, `line`, `concentric`, `triangles`, `zigzag`, `crosshatch`, `lightning`).
- `platten[].teile[]`: `x`, `y` = Mitte des Hüllrechtecks auf der Platte (Drucker-mm, Ursprung vorn links);
  `drehung` in Grad um Z gegenüber der Druckausrichtung; `umriss` = konvexe Hülle in Plattenkoordinaten (absolut,
  gegen den Uhrzeigersinn). Additiv `ersatz` (true für Stück über die gezeigten hinaus, `name` bleibt das gezeigte
  Teil). Additiv je Platte: `anordnung` (`schnell` | `slicer`), `kosten`, `hoehe_mm`, `material[].m` und
  `material[].kosten`. Eine Platte trägt ein Material (P1P ohne AMS).
- `summe.kosten` = Summe von `kosten_teile`; additiv `kosten_teile.risiko` (Aufschlag fürs Erfolgsrisiko, V5).
  `zeit_mit_wechsel_s` = `zeit_s` + (Platten − 1) · `plattenwechsel_s`.
- Additiv oben: `einstellungen` (benutzte Projekt-Einstellungen: `drucker`, `strompreis_kwh`, `leistung_w`,
  `plattenwechsel_s`, `slicer`), `regler` (true: Lauf mit Reglerwerten, nichts gespeichert, kein Slicer), `ms`
  (Rechenzeit der Schätzung); `slicer.version` (Bambu Studio), `slicer.ms`.
- Ohne Druckteile: `platten` und `teile` leer, Summe null, `slicer.zustand: "aus"`.
- `hinweise[].art`: `trocknen`, `verzug`, `material`, `brim`, `stuetzen`, `ams`, `duese`, `risiko`, `bauraum`,
  `auflage`, `festigkeit`, `slicer`, `platte`.

## Gedruckt (Strang „Feinschliff 2“, 22.10.2026, additiv)

`lager.druckteil(…, gedruckt=True)` kennzeichnet ein Teil, das Kevin schon gedruckt hat (Vorbild: das eigene
`GEDRUCKT`-Dict mit Formprüfung in Variante B des Kugelschiebers, das damit ersetzt werden kann).

- **Ausgeschlossen:** nicht in `teile`, `platten`, `summe` der Druckvorschau, nicht im Druckexport (3MF), keine
  Befunde der Druckprüfung mehr (`druck.teile[name].gedruckt: true`), kein Filament in der Einkaufsliste (auch nicht
  aus der Stückliste), kein Bauplanschritt „Drucken“. Stattdessen additiv `druckvorschau.gedruckt: [{"name",
  "material", "form": "gleich" | "geaendert" | "neu" | "neu_drucken", "unterschiede": [...], "seit"}]`; sind alle
  Druckteile gedruckt, ist die Vorschau leer mit `slicer.meldung` „Alle Druckteile sind schon gedruckt.“.
- **Stückliste:** eigene Zeile mit `gedruckt: true` (gedruckte und zu druckende gleiche Teile getrennt),
  `PART_UPSERT.druckteil.gedruckt: true`. Die App zeigt das Kennzeichen „Gedruckt“ in Stückliste und Material und ein
  Häkchen am Druck-Symbol im Teilebaum; die Druckansicht nennt sie als „Gedruckt, vorhanden“.
- **Form festschreiben:** Beim ersten Lauf mit `gedruckt=True` schreibt der Kernel die Signatur der Form
  (`druck/signatur.py`) mit Hüllmaßen, Volumen, Material und Datum nach `<projekt>/gedruckt.json` (Projektdatei, damit
  in den Versionen). Der Prüfer `gedruckt` (nach „druckvorschau“) vergleicht bei jedem Lauf: Volumen ±0,2 %,
  Oberfläche ±0,3 %, Hauptmomente, Maße ±0,1 mm, Spiegelbild. Weicht die Form ab: Befund `gedruckt_geaendert`
  (Warnung, kein Fehler), z. B. „Fangrolle ist als gedruckt markiert, die Form hat sich geändert (Volumen +3,0 %).“,
  Lösung „Neu drucken … oder die Änderung zurücknehmen“. Heraus: einen Lauf lang `gedruckt=True, neu_drucken=True`
  (schreibt die neue Form fest) oder den Eintrag in gedruckt.json löschen. `neu_drucken` ohne `gedruckt` bricht den
  Lauf ab. Umsetzung `kernel/src/kevcad_kernel/druck/gedruckt.py`; CHECK additiv `druck.gedruckt` (Stand je Teil).

## Auswahl und Objektnamen im Druckexport (Strang „Druckexport 2“, 22.10.2026, additiv)

Anlass: Am Kugelschieber (Build 362) lagen alle Teile auf einer Platte, Kevin wollte sie ohne die Lenksperren drucken
(die kommen erst nach dem Nachmessen), und Bambu Studio zeigte die Objekte als „assemble_1“ bis „assemble_8“.

**Auswahl** (`druck/auswahl.py`): `druck_export(…, teile=[…], ohne=[…])`, ebenso `PRINT_EXPORT_REQ.teile` und
`.ohne` (Listen, nur gesendet, wenn nicht leer).

- Ein Eintrag ist ein Teilname aus `show()` (genau), eine Baugruppe als Präfix (`"Kugelschieber/Lenksperren"` trifft
  alles darunter), eine Gruppe der Vorschau (`"g3"`) oder ihr Name (`"Lenksperre (Druck)"`). `teile` = nur diese,
  `ohne` = diese nicht; beides zusammen geht, `ohne` gewinnt; `platten` filtert vorher. Ersatzteile gehen mit ihrem
  Namen. Unbekannte Einträge sind ein Fehler mit Vorschlägen („Meintest du …?“); bleibt nichts übrig, ebenso.
- **Lage:** Die übrigen Teile bleiben, wo die Vorschau sie hingelegt hat (Lücken sind in Ordnung). Bambu Studio lädt und
  slict Platten mit festen Lagen und Lücken (`need_arrange: false`), geprüft am 22.10.2026 mit 2.07.01.62
  (`pruefe_3mf` und `--slice 0`); die Lagen waren überschneidungsfrei, im Bauraum und außerhalb der Sperrzone und
  bleiben es. Neu anordnen hieße andere Platten als die, die Kevin in der Vorschau gesehen hat. Leere Platten fallen
  weg; passen die übrigen Teile auf weniger Platten, nennt das ein Hinweis (schnelles Anordnen als Probe).
- Platten behalten im 3MF ihre Nummer aus der Vorschau als Namen („Platte 2“), auch wenn davor eine wegfällt.
- Ergebnis additiv: `teile` (exportierte Teilnamen), `weggelassen: [{"name", "grund": "ohne" | "teile" | "spaeter",
  "platte" (Nummer oder null), "anzahl"}]`, `leere_platten`, je Datei `objekte` (Objektnamen im 3MF); der erste
  Hinweis lautet „Weggelassen: … (ohne), … (später).“. `PRINT_EXPORT_RES` trägt `weggelassen` und `leere_platten` mit
  (`dateien` wie bisher, mit `objekte`).

**Objektnamen im 3MF:** Bambu Studio nennt die Objekte einer Montageliste `assemble_<n>` (n = `assemble_index`, die
laufende Nummer über alle Platten) und die Teile darin nach der STL-Datei; einen Namen nimmt die Montageliste nicht an.
Den Namen der Objektliste liest Bambu Studio aus `Metadata/model_settings.config` (`<object>` und `<part>`, je
`<metadata key="name">`); ein `name` an den Objekten in `3D/3dmodel.model` übergeht es bei eigenen Projekten
(nachgeprüft: nur dort gesetzt, meldet der Slicer weiter „assemble_…“). Der Kernel setzt nach dem Export in dieser
Datei die Teilnamen (`slicer.objekte_benennen`, Zuordnung über die Nummer, denn die `<object>`-Blöcke stehen nicht
immer in der Reihenfolge der Liste); alles andere im Archiv bleibt unverändert. Name = Teilname aus `show()`, über 60
Zeichen ohne die mittleren Baugruppen („Kugelschieber/…/Stangenhalter vorn links (Druck)“), sonst nur der letzte Teil,
zuletzt gekürzt mit „…“; kommt ein Name mehrfach vor (Ersatzteile), zählen die weiteren mit „(2)“, „(3)“
(`slicer.objekt_namen`). Das 3MF lädt danach (`pruefe_3mf`) und slict; der Slicer meldet die Objekte unter diesen
Namen. Ohne Bambu Studio trägt `dreimf.py` dieselben Namen (im Kern und in `model_settings.config`).

**Später drucken** (`lager.druckteil(…, spaeter=True)`): Das Teil wird noch gedruckt, nur nicht jetzt (etwa nach dem
Nachmessen). Es steht weiter in `teile` (eigene Gruppe „… (später)“, `spaeter: true`, mit Filament, Zeit und
Einstellungen; der Slicer rechnet es nach), liegt aber auf keiner Platte, zählt nicht in `summe` (auch nicht im
Risikoaufschlag) und kommt nicht in den Druckexport (dort immer unter `weggelassen`, `grund: "spaeter"`; über `teile`
nicht holbar). Additiv oben `spaeter: [{"name", "gruppe", "material"}]`. Druckprüfung, Stückliste, Filament in der
Einkaufsliste und der Bauplanschritt „Drucken“ bleiben. Abgrenzung: `gedruckt=True` heißt schon gedruckt (fällt aus
Vorschau, Export, Filament und Bauplan, Form festgeschrieben), `neu_drucken=True` schreibt die Form eines gedruckten
Teils neu fest; `spaeter=True` zusammen mit `gedruckt=True` bricht den Lauf ab. Zum Drucken `spaeter` weglassen. Die
App braucht nichts Neues: sie zeigt die Gruppe in der Liste mit dem Namen „(später)“, im Bericht unter „Ohne Platte“.

## Filamente und Presets (Strang „Druckexport 2“, 22.10.2026, additiv)

Kevin: „Wenn ich etwas zum Drucken anweise oder abfrage, fragst du mich nach dem Filament, und die Projektdatei liefert
die passenden Custom Presets zum Filament mit.“ Umsetzung `druck/filamente.py` (Liste), `druck/filamentwahl.py`
(Annahme der Vorschau, Vorschläge), `slicer.filament_daten` (Preset → Bambu-Profil).

- **Filamentliste** (nicht im freigabepflichtigen Katalog): `~/Library/Application Support/de.upvis.kevcad/
  filamente.json` (`KEVCAD_FILAMENTE` übersteuert), `{"version": 1, "filamente": [{"id", "hersteller", "produkt",
  "material", "farbe", "farbe_hex", "durchmesser_mm", "offen", "quelle", "preset": {"name", "basis",
  "abweichungen": [{"schluessel", "wert", "quelle"}]}}]}`. Fehlt die Datei, legt der Kernel den Startbestand an:
  `polymaker-polylite-petg-gelb` (Basis „PolyLite PETG @BBL P1P“), `bambu-petg-basic` (Basis „Bambu PETG Basic @BBL
  X1C“, für den P1P 0.4 freigegeben, Farbe offen), `amazon-basics-pla` (Basis Kevins Benutzerprofil „Amazon Basics
  PLA“, nur gelesen). Startwerte ohne Abweichungen; Abweichungen nur belegt (offizielles Herstellerprofil für den P1P
  oder Kevins getestete Werte), je mit Quelle. Schlüssel `duese`, `duese_erste_schicht`, `bett` (alle Platten, auf
  denen das Basisprofil druckt), `bett_erste_schicht`, `luefter_min`, `luefter_max`, `max_volumen`, `fluss` oder ein
  Schlüssel des Basisprofils. Erweiterbar per MCP `filament_define`.
- **Preset im 3MF:** aufgelöst (Basis mit `inherits` und `include`, darüber die Abweichungen), Name und
  `filament_settings_id` = Preset-Name („Polymaker PolyLite PETG gelb (Kev CAD)“), `from: "User"`, `inherits` = das
  Systemprofil, von dem es abstammt (bei Kevins Benutzerprofilen über deren `inherits`), Farbe aus `farbe_hex`. Bambu
  Studio schreibt es als Projekt-Preset (`project_settings.config`: `filament_settings_id`, `inherits_group` mit dem
  Elternteil); die Kommandozeile löst `inherits` nicht selbst auf, deshalb aufgelöst. Geprüft am 22.10.2026 mit
  2.07.01.62: mit `--slice 0` steht die Temperatur des Presets im G-Code (`M109 S255` PolyLite PETG, `M109 S238` ein
  Testfilament mit Abweichung). Die Anzeige in der Oberfläche von Bambu Studio ist nicht maschinell geprüft.
- **Rückfrage erzwungen:** `druck_export(…, filament=…)`: je Material ein Filament der Liste (`{"petg": "<id>"}`, eine
  id oder eine Liste von ids); `PRINT_EXPORT_REQ.filament` ebenso. Fehlt es, schreibt der Kernel nichts und antwortet
  `{"ok": false, "filament_frage": true, "vorschlaege": {material: {"zuletzt", "spulen": [{"kennung", "name", "gramm",
  "filament"}], "liste": [{"id", "name", "preset", "basis"}]}}, "fehler": "Frag Kevin nach dem Filament …"}` (MCP:
  isError). `"vorschau"` (nur intern, Phase 8) nimmt das angenommene Filament, das der Dialog „Drucken …“ anzeigt;
  über MCP und App gilt es nicht. Falsches Material oder unbekannte id: Fehler mit den vorhandenen ids.
- **Ergebnis** additiv: `filamente: {material: {"id", "preset", "basis", "quelle", "detail", "abweichungen",
  "temperaturen"}}`, je Datei `filament_id`, `filament_basis`, `abweichungen`, `filament_quelle` (`kevin`),
  `temperaturen` (`duese`, `duese_erste_schicht`, `duese_bereich`, `platte`, `platte_erste_schicht`, `platte_name`,
  `luefter`, `max_volumen`, `hersteller`); Hinweis „PETG: Filament …, Preset „…“ (Basis „…“; keine Abweichungen);
  Düse 255 °C, Texturplatte 80 °C.“ Das gewählte Filament merkt sich das Projekt: `druck.json` → `filament:
  {material: {"id", "stand"}}`.
- **Druckvorschau:** schätzt mit einem angenommenen Filament und zeigt es an: `kevcad.json` `druck.filament.<material>`
  (id der Liste oder Bambu-Profil), zuletzt für das Projekt gewählt (`druck.json`), Spule im Bestand (Verweis
  `filament` oder Hersteller und Name), erstes Filament der Liste, sonst Systemprofil. Additiv `summe.material[]`:
  `filament` (Preset-Name), `filament_id`, `filament_quelle` (`projekt` | `zuletzt` | `spule` | `standard` |
  `system`), `filament_detail`, `filament_basis`, `temperaturen`; `teile[].profil.filament_id`, `.quelle`, `.detail`;
  oben `filamente` (die Filamente der Liste zu den Materialien der Vorschau: `id`, `name`, `material`, `farbe`,
  `farbe_hex`, `preset`, `basis`, `abweichungen` (Anzahl), `offen`). Das Preset gehört zum Schlüssel der Gruppe (anderes
  Filament = neu slicen).
- **Spulen** im Bestand verweisen mit `filament` auf einen Eintrag (BESTAND.md); `bestand_eintragen(filament=…)` füllt
  Material, Name, Hersteller und Farbe.
- **App:** Der Sichern-Dialog des 3MF-Exports zeigt je Material eine Auswahl aus `druckvorschau.filamente`,
  vorausgewählt das angenommene Filament; `PRINT_EXPORT_REQ.filament` (`DruckExportNachricht.filament`,
  `DruckActions.druckExportieren(platten:nach:filament:)`).
- **Profil-Vorlagen (`include`):** Bambu Studio 2.x lagert Teile der Profile in Vorlagen aus, beim „Bambu Lab P1P 0.4
  nozzle“ Start-, End-, Filamentwechsel- und Schichtwechsel-G-Code. Kev CAD löste bis 22.10.2026 nur `inherits` auf;
  alle geslicten G-Codes und die Projekt-Einstellungen aller exportierten 3MF trugen deshalb den allgemeinen
  Start-G-Code aus „fdm_machine_common“ (Düse fest `M109 S205`, ohne das P1P-Vorprogramm). Jetzt in `slicer.profil`
  und `drucker/profile.Profile.laden` aufgelöst (Eltern, Vorlagen, eigene Werte); Schlüssel der Zwischenspeicher `v2`.

## Druckfertig je Objekt (Strang „Druckexport 2“, Paket B, 22.10.2026, additiv)

Kevin: „Grundsätzlich alle Drucksettings immer automatisch einstellen, auch für die einzelnen Objekte, auch wenn sie
sich unterscheiden, so dass alles komplett druckfertig voreingestellt ist.“ Umsetzung `druck/druckfertig.py`
(`ergaenze`, aufgerufen von `empfehlung.empfehle`), Bambu-Schlüssel in `slicer.prozess_einstellungen`.

`teile[].einstellungen` additiv (optional, `protocol.DRUCK_EINSTELLUNGEN_ERWEITERT`, auch in `PRINT_SETTINGS`):

| Schlüssel | Bambu Studio | Regel |
|---|---|---|
| `stuetzen_nur_platte` | `support_on_build_plate_only` | Baumstützen nur von der Platte, normale überall; ohne Stützen ohne Bedeutung |
| `stuetzen_abstand_mm` | `support_top_z_distance` | PETG 0,25 mm (haftet an Stützen, EW), sonst Profil |
| `brim_mm` | `brim_width` | 3 mm kleine Auflage, 5 mm schlank (Höhe > 10 · √Auflage) oder schmaler hoher Steg (Höhe > 8 × kleinste Breite, setzt auch `brim`), 8 mm verziehendes Material |
| `naht` | `seam_position` | `hinten` bei Zier- und Außenteilen, sonst `ausgerichtet` |
| `buegeln` | `ironing_type` | nur Zierteile mit ebener Oberseite ab 300 mm² |
| `oberflaeche` | `top_surface_pattern` | `monoton_linie` |
| `loch_kompensation_mm`, `kontur_kompensation_mm` | `xy_hole_compensation`, `xy_contour_compensation` | 0: die Zugabe steckt im Modell |
| `elefantenfuss_mm` | `elefant_foot_compensation` | 0,15 mm wie das P1P-Profil |

Dazu: Bohrungen mindestens 3 Wände; Gewindeeinsätze (Bohrung wie `GEWINDEEINSAETZE`) und Kernlöcher für Schrauben
seit dem Strang „Rest Druck“ je ein Modifier (unten); nur ohne Lage der Bohrung wie bisher Wände nach der Mindestwand des
Herstellers (4 bis 6) und Füllung mindestens 30 %, Kernlöcher 4 Wände. Die Druckprüfung liefert dazu je
Teil `kennzahlen.bohrungen` (`d`, `waagrecht`). `teile[].begruendung_je` (additiv): je Schlüssel ein Satz; die
Abweichungen vom Zweck stehen zusätzlich in `teile[].begruendung`. Kevins feste Vorgaben gehen vor.

**Modifier um Gewindeeinsätze und Kernlöcher (Strang „Rest Druck“, 22.10.2026, additiv):** Statt die Wände des ganzen
Objekts zu erhöhen, bekommt jede erkannte Einsatzbohrung (Ø wie `GEWINDEEINSAETZE`, bis M6) und jedes Kernloch für
selbstschneidende Schrauben (`druckfertig.KERNLOCH`) im Bambu-Projekt einen Modifier: ein Zylinder koaxial zur Bohrung,
Radius = Bohrung/2 + Mindestwand des Herstellers (Kernloch: Tubus 2 · d) + eine Bahn, längs der Achse die Bohrung und je
Ende die Mindestwand (Material unter dem Einsatz), begrenzt auf 0 ≤ z ≤ Teilhöhe; darin Wände nach der Mindestwand
(`ceil(Wand / 0,42)`, **ohne** die frühere Obergrenze von 6) und 100 % Füllung. Das übrige Objekt behält Wände und Füllung
seines Zwecks (Bohrungen weiter mindestens 3 Wände). Waagrechte Bohrungen und Passungen (Rohre, Wellen) bekommen keinen
Modifier.

- Lage: Die Druckprüfung liefert je Bohrung additiv `kennzahlen.bohrungen[].achse`, `.mitte`, `.laenge` (Koordinaten der
  geprüften Form); der Prüfer „druckvorschau“ rechnet sie in Druckkoordinaten um (`vorschau_geo.bohrungen_druck`, im
  CHECK additiv `druck.vorschau.formen[fid].bohrungen`). Ohne Lage (ältere Prüfergebnisse) gilt die bisherige Regel
  (Wände des ganzen Objekts, höchstens 6, Füllung ≥ 30 %), die Begründung sagt „ohne Modifier“.
- Vorschau und Export additiv: `teile[].modifier` und `objekte_einstellungen[].modifier` je `{"art": "einsatz" |
  "kernloch", "groesse", "hersteller", "name", "d", "radius", "laenge", "wand_mm", "einstellungen": {"waende",
  "fuellung"}}`; `teile[].begruendung_je.modifier` nennt sie („Modifier um die Bohrungen statt mehr Wände für das ganze
  Objekt: 1 × Gewindeeinsatz M3 (ruthex, Bohrung Ø 4,0, Mindestwand 1,6 mm): Zylinder Ø 11 × 10 mm mit 4 Wänden und
  100 % Füllung. Das übrige Teil behält 3 Wände und 20 % Füllung.“), ebenso `teile[].begruendung`; je Datei additiv
  `dateien[].modifier` (Anzahl). Der Schlüssel der Gruppe enthält die Modifier (Zwischenspeicher `v3`).
- Im 3MF: Montageliste mit einem Eintrag `"subtype": "modifier_part"` und demselben `assemble_index` wie das Teil
  (Bambu Studio 2.07 liest `normal_part`, `modifier_part`, `negative_part`, `support_enforcer`, `support_blocker`; ein
  unbekannter Wert macht stillschweigend ein Volumenteil daraus), `print_params` `wall_loops` und
  `sparse_infill_density`; gedreht wie das Teil. In `Metadata/model_settings.config` steht er als `<part
  subtype="modifier_part">` mit dem Namen „Gewindeeinsatz M3 (Modifier)“ (`slicer.objekte_benennen`). Auch die
  Slicer-Läufe der Vorschau (`slice_teil`, Platten) rechnen mit den Modifiern; diese Gruppen führen den Abgleich der
  Schätzung nicht nach. Ohne Bambu Studio (`dreimf.py`, ohne Einstellungen je Teil) keine Modifier.
- Geprüft am 22.10.2026 mit Bambu Studio 2.07.01.62 (`test_druck_modifier.py`): Block 30 × 30 × 12 mm mit M3-Sackloch,
  `--slice 0`: im Ring 3,4 bis 3,95 mm um die Bohrung (außerhalb der 3 Wände des Objekts) in den Schichten 6,2 bis
  10,6 mm 41,4 mm Filament mit Modifier gegen 4,5 mm ohne (20 % Gyroid); Bambu Studio legt im G-Code auch um den
  Rand des Modifiers Wände. Im G-Code steht das Objekt 2 mm in Y neben der Matrix des 3MF (beide Fälle gleich).

Prüfung vor der Ausgabe: `druck_export` slict jedes geschriebene Bambu-Projekt mit `--slice 0` (`slicer.pruefe_slicen`)
und wertet die Warnungen aus. Ergebnis und `PRINT_EXPORT_RES` additiv: `druckfertig` (true nur, wenn Bambu Studio jede
Datei ohne Warnung und Fehler geslict hat; ohne Bambu Studio false), je Datei `pruefung` ({"ok", "warnungen":
[{"platte", "text", "art"}], "platten": [{"platte", "zeit_s", "g", "merkmale"}], "fehler"}) und
`objekte_einstellungen` ([{"gruppe", "name", "teile", "einstellungen", "fest", "begruendung_je"}], dazu `platte` und
`tempo` aus dem Preset des Filaments). Die Hinweise sagen „PETG: druckfertig, in Bambu Studio geslict ohne
Warnungen (…)“ oder „PETG: NICHT druckfertig, Bambu Studio warnt: …“.

Geprüft am 22.10.2026 mit Bambu Studio 2.07.01.62 (`test_druck_druckfertig.py`): Die Werte stehen je Objekt in
`Metadata/model_settings.config` und wirken beim Slicen (Merkmale „Support“, „Brim“, „Ironing“ im G-Code). Global
„kein Brim“ schaltet den Brim je Objekt ab; das Prozessprofil einer Platte behält deshalb den Profilwert
(`slicer.global_einstellungen`). Bambu Studio meldet zum Beispiel „It seems object … has floating cantilever“, wenn
ein Überhang ohne Stützen bleibt; das ist dann `NICHT druckfertig`.

## Ablauf im Kernel

1. Nach jedem erfolgreichen Lauf mit Druckteilen: Schätzung (V1/V2) und schnelles Anordnen (V3), Ziel unter 1 s am
   Kugelschieber; senden als `PRINT_PREVIEW`.
2. Im Hintergrund, wenn `druck.slicer` an und Bambu Studio vorhanden (`/Applications/BambuStudio.app`): je Gruppe
   (Formschlüssel + Material + Einstellungen) einmal slicen, Zwischenspeicher unter
   `~/Library/Caches/de.upvis.kevcad/druck/<schlüssel>/`; danach die Platten mit `--arrange` genau anordnen. Jedes
   Ergebnis ersetzt die Schätzung und schickt ein neues `PRINT_PREVIEW`. Niedrige Priorität, höchstens ein Slicer-Prozess
   gleichzeitig, Abbruch bei neuem Lauf; nie während eines Laufs mit Reglerwerten speichern.
3. Abgleich: Faktoren der Schätzung je Drucker und Profil in `~/Library/Application Support/de.upvis.kevcad/druck/
   abgleich.json` nachführen (V2).
4. Ohne Bambu Studio (z. B. Mac mini): nur Schätzung, `slicer.zustand: "aus"` mit Meldung; Tests überspringen den
   Slicer-Teil.
5. Löcher und Bohrungen (Strang „Feinschliff 2“, additiv): Der Prüfer „druckvorschau“ zählt je Höhenband die Umrisse
   im waagrechten Schnitt (Außenkontur und jedes Loch, CHECK `druck.vorschau.formen[fid].schleifen_baender`); die
   Schätzung rechnet je Schicht und weiterer Wandschleife 0,40 s für Naht, Rückzug und Leerweg (`Modell.s_loch`). Am
   Abgleich von V-K (88 Slicer-Läufe): Lochscheibe mit 12 Löchern vorher 17 bis 26 % zu tief, jetzt −8,5 bis +1,0 %;
   Zeit im Mittel aller Teile 4,9 % statt 6,3 %, Material unverändert 3,3 %.

## Protokoll (additiv)

| type | Richtung | Felder | Nutzlast |
|---|---|---|---|
| `PRINT_PREVIEW` | Kernel → App | Inhalt von `druckvorschau` (oben), `reply_to` optional | – |
| `PRINT_PREVIEW_REQ` | App → Kernel | `id` | `PRINT_PREVIEW` |
| `PRINT_EXPORT_REQ` | App → Kernel | `id`, `platten` (Liste der Nummern oder leer = alle), `ziel` (Pfad .3mf); additiv `teile`, `ohne`, `filament` | `ACK`, danach `PRINT_EXPORT_RES` |
| `PRINT_EXPORT_RES` | Kernel → App | `reply_to`, `ok`, `pfad`, `platten`, `fehler` | – |
| `PRINT_SETTINGS` | App → Kernel | `id`, `teil` oder `gruppe`, `einstellungen` (Teilmenge wie oben) oder `zweck` | `ACK`, danach `PRINT_PREVIEW` |

`PRINT_SETTINGS` von Kevin gelten als feste Vorgabe je Gruppe und überleben Läufe (gespeichert in
`<projekt>/druck.json`, gehört zu den Projektdateien und damit zu den Versionen).

Präzisierungen (additiv): `PRINT_SETTINGS.von` (`kevin` Vorgabe, `agent` vom MCP), in `druck.json` je Vorgabe
gespeichert (`"von": {"waende": "kevin", "zweck": "agent"}`) und als `teile[].fest_von` ausgegeben; ein Wert `null` in
`einstellungen` nimmt diese Vorgabe zurück; `zuruecksetzen: true` nimmt alle Vorgaben des Teils bzw. der Gruppe
zurück. Gespeichert wird je Teilname (aus `show()`), damit die Vorgabe Formänderungen übersteht; eine Gruppe schreibt
alle ihre Teile. `PRINT_EXPORT_REQ.ziel` `null` = `<projekt>/output/<projekt>-druck.3mf`. `PRINT_EXPORT_RES` additiv
`hinweise`, `ms`, `geprueft` (die Datei wurde zur Kontrolle in Bambu Studio geladen), `pfade` und `dateien`
(`[{"pfad", "material", "filament", "platten"}]`).

**3MF (Eingang von Phase 8):** je Material ein Bambu-Studio-Projekt (`pfad` ist das erste, bei mehreren Materialien
heißen sie `<ziel>-<material>.3mf`): Platten mit den Lagen der Vorschau, Drucker-, Prozess- und Filamentprofil in
`Metadata/project_settings.config`, Einstellungen je Teil (Schicht, Wände, Decken, Böden, Füllung, Muster, Stützen,
Brim) in `Metadata/model_settings.config`. `BambuStudio --slice 0 <datei>` übernimmt sie; geprüft am 22.10.2026:
Zeit und Filament nachgeslict wie in der Vorschau (±0,3 %). Ein Filament je Datei, weil Bambu Studio 2.07 Projekte mit
mehreren Filamenten aus der Kommandozeile nicht wieder slicen kann (Teile landen auf Filament 1); der P1P ohne AMS
druckt ohnehin ein Material je Platte. Ohne Bambu Studio schreibt der Kernel die 3MF selbst: je Platte eine Datei
(`<ziel>[-<material>]-platte<n>.3mf`, Teile in ihrer Lage, ohne Profile), weil Bambu Studio Platten nur aus eigenen
Projekten liest. Laufzeit: `druck_export(ziel=None, platten=None, teile=None, ohne=None) -> {"ok", "pfad", "platten",
"fehler", "pfade", "dateien", "hinweise", "geprueft", "ms"}` (dazu additiv `teile`, `weggelassen`, `leere_platten`,
`dateien[].objekte`, siehe „Auswahl und Objektnamen im Druckexport“).

**Druckprüfung, Abdrücke (V-K, 22.10.2026):** Schichtraster-Hinweise an Flächen, deren Eckpunkte alle näher als
1,5 mm an einem gezeigten Lager- oder Zukaufteil liegen (Aussparung um ein fremdes Teil), fasst die Prüfung je Teil
und fremdem Teil zu einem Hinweis `druck_schichtraster_abdruck` zusammen („6 Flächen aus der Aussparung für
ALUTEC-Rahmen liegen nicht im Schichtraster (unkritisch, Passung prüfen)“, `wert.abdruck_von`).

Testdateien:
`tools/make_druck_fixtures.py` (`print_*.frame`, `ack_print_*.frame`, Abschnitt `druck` in `fixtures.json`);
Beispiel und Prüfung in `protocol.py` (`druckvorschau_beispiel`, `check_druck_message`).

## MCP

- `druckvorschau(detail=False)`: Summe, Platten, Teile mit Empfehlung und Hinweisen; `detail` mit Umrissen.
- `druck_einstellen(teil, einstellungen=None, zweck=None)`: wie `PRINT_SETTINGS` mit `von: "agent"`; nur auf Kevins
  Wunsch oder mit Begründung im Bericht.
- `druck_export(ziel=None, platten=None, teile=None, ohne=None, filament=None)`: 3MF der angeordneten Platten für
  Bambu Studio (Grundlage Phase 8), ohne Drucken; `teile`/`ohne` wählen Teile aus, `filament` ist Pflicht (sonst
  Rückfrage, „Filamente und Presets“).
- `filament_liste(material=None)`, `filament_define(hersteller, produkt, material, farbe, durchmesser_mm, basis,
  abweichungen, farbe_hex, id, preset_name, quelle, ersetzen)`: Kevins Filamentliste lesen bzw. erweitern.

## App

- Panel **„Druck“** neben der Stückliste (Tab in der unteren Leiste): je Material g, m, €; je Platte Zeit und Teile;
  Summe mit Plattenwechseln; je Teil Empfehlung mit Begründung und Hinweise als Ampel; Kennzeichnung „Schätzung“ bzw.
  „Bambu Studio“ und Fortschritt des Slicers.
- **Plattenansicht**: Draufsicht der Platte(n) im Maßstab mit Sperrzone, Teile als Umriss, Auswahl wechselwirkt mit dem
  3D-Bereich und dem Teilebaum.
- Einstellungen je Teil bzw. Gruppe ändern (Zweck, Wände, Füllung, Muster, Stützen, Brim) → `PRINT_SETTINGS`.
- **„Platten als 3MF …“** → `PRINT_EXPORT_REQ`; danach „In Bambu Studio öffnen“.
- Bericht „Druck“ im Export-Dialog von Phase 6 (Baustein `druck`): Tabelle je Platte und Teil mit Einstellungen.
- **Filament statt Vollkörper** (Strang „Feinschliff 2“, 22.10.2026): Stückliste, Material und Inspektor nannten bei
  Druckteilen „Gewicht“ den Vollkörper (Lenksperre 104,7 g), die Druckvorschau das Filament (39 g bei 20 % Füllung).
  Jetzt einheitlich: Liegt die Vorschau desselben Laufs vor, gelten für Druckteile Filament und Filamentkosten (je
  Teil das Stück seiner Gruppe, `je_stueck.g`, Kosten anteilig), bezeichnet als „Filament 39,1 g (gedruckt,
  Schätzung | Bambu Studio) · Vollkörper 104,7 g“ (Inspektor im 3D-Bereich und im Material, Tooltip in der
  Stückliste, Gruppenkopf „Filament, Bambu Studio“); Summen von Gewicht und Kosten folgen. Ohne Vorschau desselben
  Laufs bleibt Vollkörper × Dichte. App `DruckFilamentWert` (Material/MaterialDaten.swift); Kernel MCP `bom` additiv
  `druck_filament` je Position (`druck/vorschau.filament_je_zeile`) und im Text eine Zeile je Druckteil.

## Drucken (Phase 8)

Version 1 (22.10.2026), additiv. Plan, Recherche und Entscheidungen P1–P7: [PLAN-PHASE8-DRUCK.md](PLAN-PHASE8-DRUCK.md).
Kevins Entscheidung: **Weg A**. Änderungen nur gemeinsam: dieser Abschnitt, `protocol.py` (Abschnitt Drucker),
`tools/make_drucker_fixtures.py` mit den Testdateien und die Swift-Decoder im selben Commit.

### Wege

- **`a`** (Standard): Drucker bleibt im Cloud-Modus. Der Kernel slict die gewählten Platten mit der CLI von Bambu Studio
  fertig (`.gcode.3mf` ohne Objekte, `--min-save`) und öffnet die Datei in Bambu Studio; dort „Platte drucken“ →
  „Senden“. Status nur lesend, wenn IP, Seriennummer und Zugangscode eingetragen sind.
- **`b`** (gesperrt, nicht ausgebaut): LAN-only + Developer Mode. Upload per FTPS nach `cache/`, Start per MQTT
  (`project_file`) mit genau einer Platte, Pause, Fortsetzen, Abbruch.

**Sperre (verbindlich, `drucker/sperre.py`):** Außer den Leseanfragen `pushing.pushall` (höchstens alle 300 s) und
`info.get_version` schickt der Kernel nur dann etwas an den Drucker, wenn alles gilt: Weg `b` eingestellt;
MQTT-Verbindung in dieser Sitzung; `print.fun` in dieser Verbindung empfangen und Bit `0x20000000` gelöscht (Developer
Mode an); SSDP meldet nicht `cloud` (falls gesehen); kein HMS `0500-0500-0001-0007` offen; für den Start ein von Kevin
bestätigter Auftrag. Sonst sendet er nichts und antwortet mit dem Grund. Die Kamera wird nicht benutzt (`kamera: false`).

### Einstellungen

Gehören der App, eine Datei je Variante: `~/Library/Application Support/<Bundle-ID>/drucker.json`, nie mit Geheimnissen:

```json
{"version": 1, "aktiv": "p1p",
 "drucker": [{"id": "p1p", "name": "P1P", "modell": "C11", "ip": "192.168.178.40", "weg": "a", "status_lesen": false,
              "schluesselbund": {"dienst": "de.upvis.kevcad.drucker", "konto": "p1p"}}]}
```

- `id`: `[a-z0-9][a-z0-9-]{0,31}`, zugleich das Konto im Schlüsselbund. `status_lesen` ist anfangs **aus**: Dass die lokale
  MQTT-Verbindung im Cloud-Modus ohne Nebenwirkung bleibt, ist nur für das Lesen belegt (ha-bambulab „hybrid mode“), nicht
  für die Zahl gleichzeitiger Verbindungen; Kevin schaltet es bewusst ein (Hinweis in den Einstellungen).
- Seriennummer und Zugangscode stehen nur im Schlüsselbund: ein Eintrag (generisches Passwort) je Drucker, Dienst fest
  `de.upvis.kevcad.drucker`, Konto = `id`, Inhalt `{"seriennummer": "…", "zugangscode": "…"}` als JSON. Die App legt
  ihn an (Zugriff erlaubt für Kev CAD und `/usr/bin/security`; damit kann jedes Programm unter Kevins Benutzer ihn ohne
  Rückfrage lesen, die Einstellungen sagen das und bieten „Zugangsdaten löschen“). Der Kernel liest ihn nur beim
  Verbinden mit `/usr/bin/security find-generic-password -s de.upvis.kevcad.drucker -a <id> -w` (feste Namen, `id`
  geprüft), hält ihn nur im Speicher, solange die Verbindung besteht, und gibt Ausgabe und Fehlertext von `security`
  nie weiter. Niemand gibt ihn aus: nicht in Nachrichten, Protokollen, Tracebacks, MCP-Ergebnissen, Dateien oder
  Commits. Das Feld `schluesselbund` in `drucker.json` ist nur ein Hinweis für Menschen.
- Profile für das Slicen wie in der Druckvorschau (`kevcad.json` → `druck.filament`, Drucker `p1p-0.4`); additiv
  `druck.platte` (Druckplatte mit dem Namen aus Bambu Studio, Vorgabe die des P1P: „Textured PEI Plate“). Die CLI setzt
  die Platte nicht selbst; ohne sie nimmt sie die Cool Plate, und PETG scheitert.

### Nachrichten (ohne Nutzlast)

| type | Richtung | Felder | Antwort |
|---|---|---|---|
| `PRINTER_CONFIG` | App → Kernel | `id`, `drucker` (Eintrag wie oben oder `null` = keiner) | `ACK`, danach `PRINTER_STATUS` |
| `PRINTER_STATUS_REQ` | App → Kernel | `id` | `PRINTER_STATUS` mit `reply_to` |
| `PRINTER_STATUS` | Kernel → App | siehe unten; beim Verbinden, bei jeder Änderung (höchstens 2 je s) und auf Anfrage | – |
| `PRINT_JOB_REQ` | App → Kernel | `id`, `platten` (leer = alle), `weg`, `bestaetigt` (false = nur vorbereiten, true = Kevin hat bestätigt), `optionen` (nur Weg B), `auftrag` (optional, aus `PRINT_JOB_ASK`) | `ACK`, danach `PRINT_JOB_RES` |
| `PRINT_JOB_RES` | Kernel → App | `reply_to`, `ok`, `auftrag`, `weg`, `schritt` (`vorbereitet`, `geoeffnet`, `gestartet`), `datei`, `platten`, `fehler`, `hinweise`, `ms` | – |
| `PRINT_JOB_ASK` | Kernel → App | `id`, `auftrag`, `platten`, `weg`, `von` (`agent`), `grund` | `ACK` (Dialog offen); Kevins Antwort als `PRINT_JOB_REQ` mit `auftrag` oder `PRINT_CONTROL` `verwerfen` |
| `PRINT_CONTROL` | App → Kernel | `id`, `aktion` (`aktualisieren`, `pause`, `fortsetzen`, `abbrechen`, `verwerfen`), `auftrag` (bei `verwerfen`) | `ACK` (`ok: false` mit Grund, wenn gesperrt) |

`optionen` (Weg B): `{"bett_nivellieren": true, "flussrate": true, "zeitraffer": false, "spule": "extern"}`.

`PRINTER_STATUS`:

```json
{"konfiguriert": true, "verbindung": "aus" | "verbindet" | "verbunden" | "getrennt" | "fehler", "meldung": "…",
 "drucker": {"id": "p1p", "name": "P1P", "modell": "P1P", "ip": "192.168.178.40", "firmware": "01.10.00.00",
             "modus": "cloud" | "lan" | "unbekannt", "entwicklermodus": false, "signal": "-45dBm"},
 "weg": "a",
 "wege": {"a": {"moeglich": true, "grund": null},
          "b": {"moeglich": false, "grund": "Developer Mode ist aus.", "anleitung": ["Einstellungen → WLAN …"]}},
 "steuern": false,
 "druck": {"zustand": "unbekannt" | "bereit" | "vorbereiten" | "druckt" | "pausiert" | "fertig" | "fehlgeschlagen",
           "gcode_state": "RUNNING", "fortschritt": 0.42, "schicht": 41, "schichten": 98, "restzeit_s": 3720,
           "aufgabe": "Kugelschieber Platte 1", "datei": "…gcode.3mf", "stufe": "druckt", "geschwindigkeit": "standard"},
 "temperaturen": {"duese": 219.5, "duese_ziel": 220.0, "bett": 55.0, "bett_ziel": 55.0},
 "fehler": [{"code": "0300-0100-0001-0001", "text": "…", "schwere": "fehler", "art": "hms"}],
 "kamera": false,
 "gefunden": [{"name": "P1P", "modell": "P1P", "ip": "192.168.178.40", "verbindung": "cloud", "kennung": "3fa2c1d09e7b"}],
 "auftrag": {"auftrag": "j-3", "zustand": "wartet" | "slict" | "bereit" | "oeffnet" | "geoeffnet" | "laedt_hoch" |
             "startet" | "gestartet" | "fehler" | "verworfen",
             "weg": "a", "platten": [1, 2], "fortschritt": 0.5, "meldung": "…", "datei": "…", "von": "kevin" | "agent"},
 "aktualisiert": 1792656000.0}
```

- Ohne Einstellungen: `konfiguriert: false`, `verbindung: "aus"`, `drucker: null`; Weg A geht trotzdem (slicen und
  öffnen), nur ohne Status.
- `druck` und `temperaturen` sind `null`, solange kein Bericht da ist; `fortschritt` 0–1, `restzeit_s` aus
  `mc_remaining_time` · 60.
- `steuern`: true nur, wenn die Sperre Steuerbefehle erlaubt (Weg B nachgewiesen); die App zeigt Pause, Fortsetzen und
  Abbruch nur dann.
- `gefunden`: passiv per SSDP gehörte Bambu-Drucker; `kennung` = die ersten 12 Hex-Zeichen von SHA-256 der
  Seriennummer (die App vergleicht mit dem eigenen Eintrag), nie die Seriennummer selbst.

### Ablauf

1. Kevin klickt „Drucken …“ (oder MCP `drucken` schickt `PRINT_JOB_ASK`, die App öffnet denselben Dialog). Beim
   Öffnen schickt die App `PRINT_JOB_REQ` mit `bestaetigt: false`: Der Kernel slict schon (Zwischenspeicher je Eingang
   und Profilen) und meldet `schritt: "vorbereitet"`.
2. Kevin bestätigt → `PRINT_JOB_REQ` mit `bestaetigt: true` (und `auftrag`, falls vorhanden). Weg A: Datei nach
   `<projekt>/output/<projekt>-platten.gcode.3mf` kopieren und mit `open -a BambuStudio` öffnen →
   `schritt: "geoeffnet"`. Weg B: Sperre prüfen, hochladen, starten → `schritt: "gestartet"`.
3. Eingang des Slicens ist das 3MF der Druckvorschau (`druck_export(ziel, platten)` von V-K). Enthält es keine
   Bambu-Projekteinstellungen, lädt der Kernel die aufgelösten Systemprofile (P1P 0.4, Prozess nach Schichthöhe,
   Filament je Material). Ohne Druckvorschau: Ersatzweg je Material aus den Druckteilen (Bambu Studio richtet aus und
   ordnet an), mit Hinweis.

### MCP

- `drucker_status()`: Verbindung, Modus, Wege mit Grund, laufender Druck, Temperaturen, Fehler, gefundene Drucker,
  letzter Auftrag. Nur lesen; ohne Seriennummer und Zugangscode.
- `drucken(platten=None, weg="a", grund=None)`: **nur auf Kevins ausdrücklichen Wunsch.** Schickt `PRINT_JOB_ASK`; es
  geschieht nichts, bis Kevin im Dialog bestätigt. Antwort: Auftrag und „wartet auf Kevins Bestätigung“.

### App

- `DruckerLeiste(model:)` in der Druckvorschau-Ansicht (Platz stimmt der Koordinator mit V-A ab): Zustand, Fortschritt,
  Schicht, Restzeit, Temperaturen, Fehler, Knopf „Drucken …“; Pause, Fortsetzen, Abbruch nur bei `steuern`.
- `DruckenDialog`: Platten (Auswahl), Material und Spule je Platte, Zeit, Weg (B ausgegraut mit Grund und Anleitung),
  „In Bambu Studio öffnen“ bzw. „Drucken“.
- `DruckerEinstellungen`: Name, IP, Seriennummer, Zugangscode (in den Schlüsselbund), Weg, „Status lesen“, gefundene
  Drucker zum Übernehmen von Name und IP.
- Selbsttest `KEVCAD_SELFTEST=drucker` gegen die Attrappe.

Testdateien: `tools/make_drucker_fixtures.py` (`printer_*.frame`, `print_job_*.frame`, `print_control*.frame`,
`ack_printer_*.frame`, Abschnitt `drucker` in `fixtures.json`); Beispiel und Prüfung in `protocol.py`
(`drucker_status_beispiel`, `check_drucker_message`).
