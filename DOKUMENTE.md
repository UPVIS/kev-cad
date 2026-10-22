# Kev CAD · Dokumente (Vertrag Phase 6)

Version 1.3 (22.10.2026; 1.1: Ergänzungen aus [RECHERCHE-PHASE6.md](RECHERCHE-PHASE6.md) Abschnitt 7; 1.2: `DRAWING_CREATE`, Änderungen des Agenten erreichen die App; 1.3: Schrittbilder beim Bearbeiten mit Bezug, Linienart `kontext`). Verbindlich für Zeichnungen, Bauplan und Berichte aus
[PLAN-PHASE6-DOKUMENTE.md](PLAN-PHASE6-DOKUMENTE.md). Änderungen nur gemeinsam: dieses Dokument, `protocol.py`,
Testdateien und Swift-Decoder im selben Commit (wie PROTOCOL.md). Einheiten auf dem Blatt: mm, Ursprung links unten,
y nach oben. Modellkoordinaten wie überall: mm, Z oben.

## Ablage

```
<projekt>/dokumente/
├── zeichnungen/<blatt-id>.json   je Blatt
├── bauplan.json
├── hausregeln.json               optional, Abweichungen von den Standard-Hausregeln (siehe unten)
└── vorlagen.json                 Export-Vorlagen (gehört der App)
```

Die Dateien gehören zu den Projektdateien (Versionen erfassen sie). Erzeugte Vektoren werden nicht gespeichert,
sondern bei jedem Lauf neu gerechnet.

**Hausregeln** (Version 1.1): Wo die Normen keine Zahl vorgeben, gelten einstellbare Hausregeln. Sie werden nie als
„ISO“ ausgewiesen. Standard, überschreibbar je Projekt in `hausregeln.json`:

```json
{"masslinienabstand": {"erste": 10.0, "weitere": 7.0}, "schraffurabstand": 2.5, "pfeil": {"winkel": 15, "laenge_faktor": 10},
 "schrift": {"familie": "osifont", "hoehe": 3.5}}
```

Schrifthöhe ist die Versalhöhe in mm (ISO 3098 Typ B); 3,5 mm entsprechen 13,46 pt. Die App liefert osifont
(LGPL-Variante mit Font-Ausnahme) im Bundle mit.

**Verdeckungsrechnung** (Version 1.1, gemessen in [RECHERCHE-PHASE6.md](RECHERCHE-PHASE6.md) 3.2): Standard ist die
Rechnung auf dem Netz (`HLRBRep_PolyAlgo`) mit zusammengefassten Segmenten. Die exakte Rechnung (`HLRBRep_Algo`) läuft
nur mit Zeitbudget in einem eigenen Prozess und ersetzt das Netzergebnis, wenn sie rechtzeitig fertig wird. Eine
Flächenzahl ist keine Weiche: Schon 36 Flächen können exakt über 80 s brauchen.

## Bezüge (stabil über Läufe)

Maße, Notizen und Bauplan-Schritte zeigen auf Geometrie über einen **Bezug** mit Signatur, nicht über Nummern:

```json
{"teil": "Kugelschieber/Seitenstange links (Rohr 1)",
 "art": "kante" | "punkt" | "flaeche" | "achse" | "bohrung" | "huelle" | "merkmal",
 "signatur": {"typ": "kreis", "mitte": [12.0, 0.0, 6.0], "richtung": [0, 1, 0], "radius": 3.3, "laenge": null},
 "merkmal": "bohrung:3",
 "ref": "Kugelschieber/Seitenstange links (Rohr 1)#e12"}
```

- `signatur` beschreibt das Element im lokalen System des Teils (Typ, Mitte, Richtung, Radius, Länge).
- `merkmal` ist die Kennung aus der Merkmalerkennung (z. B. `bohrung:3`, `fase:1`, `huelle`), wenn vorhanden.
- `ref` ist nur die Referenz des Laufs, in dem der Bezug entstand (Hinweis, nicht maßgeblich).
- Nach jedem Lauf ordnet der Kernel neu zu (erst `merkmal`, dann `signatur` mit Toleranz). Passt nichts mehr, bekommt
  das Maß `verwaist: true` und bleibt sichtbar markiert, bis es jemand löscht oder neu bezieht.

## Zeichnungsblatt (`zeichnungen/<id>.json`)

```json
{"version": 1, "id": "seitenstange-links", "titel": "Seitenstange links",
 "format": "A4", "ausrichtung": "quer", "massstab": "1:2",
 "inhalt": {"art": "teil" | "baugruppe" | "zusammenbau", "teile": ["Kugelschieber/Seitenstange links (Rohr 1)"]},
 "schriftfeld": {"benennung": "Seitenstange links", "zeichnungsnummer": "KS-B-003", "werkstoff": "EN AW-6060",
                 "halbzeug": "Rohr 12 × 1,0", "masse_g": 94.0, "allgemeintoleranz": "ISO 2768-m",
                 "projekt": "Kugelschieber Variante B", "version": "Meilenstein 12", "datum": "2026-10-22",
                 "gezeichnet": "Kev CAD", "notiz": null,
                 "dokumentart": "Fertigungszeichnung", "blatt_nr": 1, "blatt_anzahl": 1,
                 "eigentuemer": "Kevin Schwed", "freigegeben": null},
 "ansichten": [
   {"id": "v1", "art": "vorn", "lage": [80, 120], "massstab": null, "verdeckt": true, "mittellinien": true},
   {"id": "v2", "art": "oben", "lage": [80, 60]},
   {"id": "v3", "art": "schnitt", "lage": [200, 120], "schnitt": {"von": "v1", "ebene": {"punkt": [0, 0, 0], "normale": [1, 0, 0]}, "name": "A"}},
   {"id": "v4", "art": "einzelheit", "lage": [220, 50], "einzelheit": {"von": "v1", "mitte": [500, 0], "radius": 15, "faktor": 4, "name": "B"}},
   {"id": "v5", "art": "iso", "lage": [230, 160], "massstab": "1:5"}
 ],
 "masse": [
   {"id": "m1", "art": "linear" | "durchmesser" | "radius" | "winkel" | "fase" | "bohrung" | "gewinde" | "bezugskette" | "koordinaten",
    "ansicht": "v1", "bezuege": [<Bezug>, <Bezug>], "richtung": "x" | "y" | "frei", "versatz": 12.0,
    "text": null, "toleranz": null, "quelle": "auto" | "kevin" | "agent", "fest": false, "verwaist": false}
 ],
 "notizen": [{"id": "n1", "text": "Grat entfernen", "lage": [30, 30], "zeiger": <Bezug> | null, "quelle": "kevin"}],
 "tabellen": [{"art": "bohrungen" | "stueckliste", "lage": [150, 20]}],
 "unterdrueckt": [{"art": "durchmesser", "ansicht": "v1", "bezuege": [<Bezug>]}],
 "auto": {"ansichten": true, "masse": true}}
```

- **Schriftfeld nach ISO 7200** (Version 1.1): `dokumentart` („Fertigungszeichnung“, „Zusammenbauzeichnung“,
  „Bohrbild“), `blatt_nr` und `blatt_anzahl` (der Kernel zählt je Inhalt), `eigentuemer`, `freigegeben` (Name oder
  null). Neben dem Maßstab steht das Symbol der Projektionsmethode 1. Allgemeintoleranz als „ISO 2768-m“ (ISO 2768-2
  ist zurückgezogen, kein „-mK“).
- **Version im Schriftfeld:** `schriftfeld.version` bleibt in der Datei null, außer Kevin trägt selbst etwas ein. Das
  gezeichnete Schriftfeld (Texte in `DRAWING`) zeigt die Version, zu der der Lauf gehört: `V12`, in einer Variante
  `V12 (Flacher Rand)`, mit Meilenstein `V12 „Prototyp“` (PLAN-VERSIONEN.md, „Dokumente“).
- **Unterdrückung** (Version 1.1): `mass_loeschen` auf ein Maß mit `quelle: "auto"` entfernt es und trägt Art und Bezüge
  in `unterdrueckt` ein. Die automatische Bemaßung legt für unterdrückte Bezüge kein Maß gleicher Art neu an.
  Aufheben mit `{"op": "unterdrueckung_aufheben", "index"}` oder `{"op": "auto", "masse": true, "zuruecksetzen": true}`.

- Ansichten nach Projektionsmethode 1 (ISO 128-30); `art` vorn/hinten/oben/unten/links/rechts beziehen sich auf die
  Modellachsen (vorn = Blick in +Y, oben = Blick in −Z), iso = isometrisch.
- `auto.masse`: Der Kernel ergänzt und aktualisiert automatische Maße (`quelle: "auto"`); Maße mit `fest: true` oder
  `quelle` kevin/agent fasst er nie an (nur Neuzuordnung der Bezüge).
- Zusammenbau-Blätter tragen Positionsnummern (je Stücklistenposition) und eine Stücklisten-Tabelle.

## Bauplan (`bauplan.json`)

```json
{"version": 1, "titel": "Kugelschieber Variante B",
 "abschnitte": [
   {"art": "material" | "zuschnitt" | "bearbeiten" | "drucken" | "montage", "titel": "Zuschnitt",
    "schritte": [
      {"id": "s7", "titel": "Seitenstangen ablängen", "text": "…", "quelle": "auto" | "agent" | "kevin", "fest": false,
       "teile": ["…"], "neu": ["…"], "baugruppe": null,
       "verbindungsmittel": [{"id": "schraube-iso7380-m6", "laenge": 16, "anzahl": 4}],
       "werkzeug": ["Innensechskant 4 mm", "Bohrer Ø 6,6"],
       "bohrbild": [{"teil": "…", "bezug": <Bezug>, "durchmesser": 6.6, "tiefe": null, "lage_mm": [25.0], "von": "Rohrende links", "senkung": null, "gewinde": null}],
       "zuschnitt": [{"stock_id": "rohr-alu-12x1.0", "laenge": 1000, "gehrung": [0, 0], "anzahl": 2}],
       "druck": {"teil": "…", "material": "petg", "ausrichtung": [0, 0, 0], "hinweise": ["Brim"]},
       "bild": {"kamera": {"rotation": [x,y,z,w], "pivot": [x,y,z], "distance": 900, "ortho": true},
                "explosion": {"<teil>": [0, 0, 80]}, "pfeile": [{"teil": "…", "richtung": [0, 0, -1]}],
                "hervorheben": ["…"], "sichtbarkeit": {"<teil>": 0.82}},
       "pruefung": [<Befund>]}
    ]}
 ],
 "vorher": [{"a": "<schritt-id oder teil>", "b": "<schritt-id oder teil>", "grund": "…", "quelle": "auto" | "agent" | "kevin"}]}
```

- `bild.sichtbarkeit` (Version 1.1): gemessener sichtbarer Anteil jedes neuen Teils im Schrittbild (0 bis 1). Unter
  der Hausregel-Schwelle meldet die Prüfung einen Befund `verdeckt` mit Vorschlag für eine andere Blickrichtung.
- **Bearbeiten mit Bezug** (Version 1.3): Schritte, die Teile in ein anderes bringen (Gewindeeinsätze einschmelzen,
  Lager einpressen, Stifte einkleben), zeigen das aufnehmende Teil als Bezug: `bild.kontext` (das erste aufnehmende
  Teil, bei Stiften dazu seine schon eingebrachten Einsätze), `bild.kontext_linie: "kontext"` (diese Teile im
  Strichbild als Linienart `kontext`, dünn und grau), `bild.vertreter` (bei „4 ×“ steht dieses Teil für alle),
  `bild.hervorheben` (nur seine neuen Teile), `bild.explosion` und `bild.pfeile` entlang der Einführrichtung (aus der
  Tasche bzw. dem Sitz heraus; Pfeile mit `luecke: true` stehen zwischen abgerücktem Teil und Sitz), Blick auf die
  Eintrittsseite. Das Strichbild hebt `bild.hervorheben` hervor (sonst `neu`).
- `vorher` (Version 1.1): Reihenfolgen „a vor b“. Der Kernel leitet sie aus Bedingungen und Demontage ab
  (`quelle: "auto"`); eingetragene von Agent oder Kevin bleiben erhalten. Ein Verstoß ist ein Befund `reihenfolge`.

- Der Kernel erzeugt das Gerüst bei jedem Lauf neu und übernimmt dabei alle Schritte mit `fest: true` sowie Texte mit
  `quelle` agent/kevin, zugeordnet über `id` und Bezüge.
- `pruefung` füllt die Simulation (D7) mit Befunden im gemeinsamen Format (`art`, `teile`, `schwere`, `text`, `ort`,
  `loesung`); Arten `einfuehrweg`, `werkzeugzugang`, `standsicherheit`, `reihenfolge`, `verdeckt`.

## Protokoll (additiv)

| type | Richtung | Felder | Nutzlast |
|---|---|---|---|
| `DOCS` | Kernel → App | `run`, `blaetter` (Liste `{id, titel, inhalt, format, verwaiste_masse}`), `bauplan` (Zusammenfassung `{abschnitte, schritte, probleme}`) – nach jedem Lauf und nach dem Verbinden | – |
| `DRAWING_REQ` | App → Kernel | `id`, `blatt` | `DRAWING` |
| `DRAWING` | Kernel → App | `reply_to` (optional), `blatt` (Inhalt der Datei), `geometrie` (je Ansicht `{id, rahmen: [x0,y0,x1,y1], linien: {sichtbar, verdeckt, mitte, schnitt, schraffur, duenn}}` mit Polylinien in Blatt-mm), `masse` (je Maß die fertige Darstellung `{id, linien, pfeile, text, text_lage, text_winkel, wert}`), `stand` | Polylinien als f32-Arrays (siehe unten) |
| `DRAWING_EDIT` | App → Kernel | `id`, `blatt`, `ops` (Liste, siehe unten), `von`: `kevin` | `ACK`, danach `DRAWING` |
| `DRAWING_CREATE` | App → Kernel | `id`, `teile` (optional; ohne: alle gefertigten Teile und Zusammenbau), `art` (`teil` \| `baugruppe` \| `zusammenbau`), `format` (optional) – Version 1.2 | `ACK`, danach `DOCS` mit `reply_to` |
| `BAUPLAN_REQ` | App → Kernel | `id` | `BAUPLAN` |
| `BAUPLAN` | Kernel → App | `reply_to` (optional), `bauplan` (Inhalt der Datei mit Prüfung), `bilder` (je Schritt Strichbild wie `geometrie` einer Ansicht, Blatt-mm in einem Feld 180 × 120) | Polylinien |
| `BAUPLAN_EDIT` | App → Kernel | `id`, `ops`, `von` | `ACK`, danach `BAUPLAN` |
| `BAUPLAN_PRUEFEN` | App → Kernel | `id`, `schritt` (oder null für alle) | `ACK`, danach `BAUPLAN` |
| `DOC_EXPORT_REQ` | Kernel → App | `id`, `bausteine` (Liste wie im Export-Dialog), `ziel` (Pfad .pdf) oder `drucken: true` | App antwortet `DOC_EXPORT_RES` |
| `DOC_EXPORT_RES` | App → Kernel | `reply_to`, `ok`, `pfad`, `seiten`, `fehler` | – |

Änderungen über MCP (`zeichnung_erstellen`, `zeichnung_bearbeiten`, `bauplan_bearbeiten`) schickt der Kernel der App
sofort: `DOCS` und für jedes geänderte Blatt `DRAWING` bzw. `BAUPLAN` (Version 1.2), nicht erst nach dem nächsten Lauf.

**Reglerstand:** Zeigt die Szene einen Lauf mit überschriebenen Parametern (Regler, `run(params=…)`), rechnet der
Kernel Blätter und Bauplan dazu und zeigt sie, speichert sie aber nicht. Bearbeiten, Anlegen und Neurechnen
(`DRAWING_EDIT`, `DRAWING_CREATE`, `BAUPLAN_EDIT`, die MCP-Werkzeuge dazu) lehnt er dann mit `ACK` `ok: false` und
einer Meldung ab („Das Modell zeigt gerade einen Reglerstand (breite = 280) …“); nach einem Lauf ohne überschriebene
Parameter geht es wieder.

**Format und Maßstab automatisch:** das kleinste Format, auf dem Ansichten, Maße und Tabellen mit Abstand passen (A4
vor A3 vor A2), dort der größte Normmaßstab; eine Größe mehr nur, wenn das Teil sonst klein würde und dort ein größerer
Maßstab passt. Feste Ansichten (`fest: true`) wandern beim Formatwechsel anteilig mit und bleiben im Zeichenfeld;
überdeckten sie dort Schriftfeld oder Tabellen, bleibt ein größeres Format, und das Blatt bekommt einen Hinweis.

Polylinien-Nutzlast: je Linienart nacheinander `u32 Anzahl Polylinien`, je Polylinie `u32 Punktzahl` und `f32 x, y`
paarweise; Reihenfolge der Linienarten wie im Kopf `linien_reihenfolge`. Maße und Texte im JSON-Kopf.

Linienarten (Version 1.1, additiv): zusätzlich `nachbar` (Strich-Zweipunkt dünn, ISO 128 05.1: Nachbarteile,
Endlagen von Gelenken) und `bruch` (Freihand dünn: Bruchkanten verkürzter Ansichten langer Rohre). Die App zeichnet
unbekannte Linienarten dünn durchgezogen, statt abzubrechen. Strichbilder des Bauplans (Version 1.3): nach `neu` und
`pfeil` zusätzlich `kontext` (aufnehmendes Teil beim Bearbeiten, dünn und grau).

`DRAWING_EDIT.ops`: `{"op": "mass_verschieben", "id", "versatz" | "text_lage"}`, `{"op": "mass_loeschen", "id"}`,
`{"op": "mass_neu", "art", "ansicht", "bezuege": [{ "ansicht", "punkt": [x, y] (Blatt-mm, der Kernel sucht das nächste
Element) } …], "versatz"}`, `{"op": "ansicht_neu", "art", "lage"}`, `{"op": "ansicht_verschieben", "id", "lage"}`,
`{"op": "ansicht_loeschen", "id"}`, `{"op": "massstab", "wert"}`, `{"op": "notiz", "text", "lage", "zeiger"}`,
`{"op": "notiz_loeschen", "id"}`, `{"op": "schriftfeld", "feld", "wert"}`, `{"op": "auto", "ansichten": bool, "masse": bool, "zuruecksetzen": bool}`,
`{"op": "unterdrueckung_aufheben", "index"}`.

**Schnitt und Einzelheit aus der App** (Version 1.3): `ansicht_neu` mit `art: "schnitt"` nimmt statt `schnitt.ebene`
die gezogene Linie `schnitt.linie: [[x, y], [x, y]]` (Blatt-mm) und optional `schnitt.von`; der Kernel nimmt die
Ansicht unter der Mitte der Linie und legt die Ebene durch Linie und Blickrichtung, Blick zur größeren Hälfte der
Ansicht (geht die Linie durch die Mitte: links der Zeichenrichtung). Mit `art: "einzelheit"` statt `mitte`/`radius`
der aufgezogene Kreis `einzelheit.kreis: {"mitte": [x, y], "radius": r}` (Blatt-mm); ohne `faktor` wählt der Kernel 2,
4, 5 oder 10 (Einzelheit etwa 60 mm). Nur in Vorder-, Seiten- und Draufsichten. `schnitt.umkehren: true` nimmt die andere Seite als
die vorgeschlagene (in der App ⌥ beim Ziehen). `{"op": "schnitt_umkehren", "id"}` dreht die Blickrichtung eines
bestehenden Schnitts um (Normale umgekehrt, eine feste `schnitt.blick` entfällt); zweimal angewandt ist es wie vorher.

`BAUPLAN_EDIT.ops`: `{"op": "text", "schritt", "titel", "text"}`, `{"op": "fest", "schritt", "wert"}`,
`{"op": "verschieben", "schritt", "nach"}`, `{"op": "zusammenfassen" | "teilen", …}`, `{"op": "bild", "schritt", "kamera" | "explosion" | "pfeile"}`.

## MCP

- `zeichnungen()` – Blätter mit Stand, verwaisten Maßen.
- `zeichnung_erstellen(teile=None, art="teil", format=None)` – ohne `teile`: Blätter für alle gefertigten Teile und den
  Zusammenbau; legt Ansichten und automatische Maße an.
- `zeichnung_bearbeiten(blatt, ops)` – dieselben Operationen wie `DRAWING_EDIT`, `von: "agent"`.
- `zeichnung_bild(blatt)` – das Blatt als PNG zur eigenen Prüfung (nicht an Kevin schicken, siehe Skill „Bilder“).
- `bauplan()`, `bauplan_bearbeiten(ops)`, `bauplan_pruefen(schritt=None)`.
- `dokument_export(bausteine, ziel=None, drucken=False)` – lässt die App das PDF bauen; `drucken` öffnet den
  Druckdialog nur, wenn Kevin es ausdrücklich will.

## App

- Bereich **„Dokumente“** im Projektfenster (umschaltbar mit dem 3D-Bereich), Seitenleiste: Zusammenbau, Baugruppen,
  Einzelteile, Bauplan, Berichte; Blattansicht mit Zoom und Verschieben.
- **Bearbeiten:** Maß auswählen, ziehen (Versatz, Textlage), löschen; neues Maß durch Anklicken zweier Elemente in einer
  Ansicht (Art je nach Auswahl); Ansicht hinzufügen und verschieben; Maßstab; Notiz mit Zeiger; Schriftfeld bearbeiten;
  verwaiste Maße rot markiert. Jede Änderung geht als `DRAWING_EDIT` an den Kernel.
- **Bauplan:** Liste der Abschnitte und Schritte, Schrittansicht mit Strichbild, Teile- und Werkzeugliste; „Durchspielen“
  im 3D-Bereich (nur montierte Teile, neue fahren ein); Probleme am Schritt.
- **Export-Dialog** „Dokumente exportieren …“: Bausteine ankreuzen, Reihenfolge, Spalten der Tabellen, Format,
  Vorlage speichern; PDF speichern oder Drucken (macOS-Druckdialog). PDF vektoriell über CoreGraphics; Bilder über den
  Offscreen-Renderer.
- **Eine Zeichenfunktion** für Bildschirm, PDF und Druck (Version 1.1, getestet in RECHERCHE-PHASE6.md 5): Schrift
  eingebettet, Schraffur als Clip-Pfad mit Linien (kein Muster), A4 und A3 gemischt in einer PDF-Datei.
- **Drucken** immer mit `.pageScaleNone` (sonst verkleinert macOS ein A4-Blatt auf 97,18 % und der Maßstab stimmt
  nicht mehr), je Blattformat ein eigener Druckauftrag; bei gemischten Formaten ein Hinweis im Dialog.


## Anhang: Zeichnungsnachrichten im Einzelnen (P6-Z, rein additiv)

Umsetzung im Kernel: `kevcad_kernel/zeichnung/` (Referenz `protocol.pack_drawing`, `pack_polylinien`,
`unpack_polylinien`, `docs_message`). Testdateien: `drawing.frame`, `drawing_tube.frame`, `docs.frame`,
`drawing_req.frame`, `drawing_edit.frame` und Abschnitt `dokumente` in `fixtures.json` (`kernel/tools/make_doc_fixtures.py`).

**DRAWING** (Kopf), zusätzlich zu den Feldern oben:

| Feld | Inhalt |
|---|---|
| `blattgroesse` | [Breite, Höhe] in mm |
| `geometrie[i]` | `{id, art, rahmen, massstab, titel, linien}`; `linien` = Anzahl Polylinien je Linienart; der letzte Eintrag `id: "blatt"` trägt Rahmen, Mittenmarken, Schriftfeld, Tabellen und Positionsnummern (`sichtbar` breit, `duenn` schmal) |
| `masse[i]` | wie oben, dazu `text_hoehe` (Versalhöhe), `einheit` (`mm` bzw. `°`), `box` [x0, y0, x1, y1] des Textes, `texte` (steigende Bemaßung: je Lage `{text, lage, hoehe, winkel, anker, wert}`), `ansicht`, `art`, `quelle`, `fest`, `verwaist`. `text_lage` ist die Mitte der Textgrundlinie, `text_winkel` in Grad gegen den Uhrzeigersinn. `pfeile[i]`: `{spitze, richtung, art (voll, punkt, ursprung), laenge, breite, polygon}` |
| `texte` | Texte des Blatts (Schriftfeld, Tabellen, Ansichtstitel, Positionsnummern, Notizen, allgemeine Angaben): `{text, lage, hoehe, winkel, anker (links, mitte, rechts), art}`, `lage` auf der Grundlinie |
| `gefuellt` | gefüllte Polygone (Pfeile am Schnittverlauf) |
| `pruefung` | Befunde der Blattprüfung `{art: "bemassung", pruefung (fehlend, ueberbemasst, ausserhalb, ueberlappung, doppelt, verwaist), schwere, text, masse, merkmal}` |
| `hinweise`, `stand`, `run` | Hinweise zur Anordnung; Stand (Hash aus Blatt und Formschlüsseln, ändert sich mit jeder Änderung); Lauf |

**Blattdatei**, zusätzliche Felder: `allgemein` (allgemeine Angaben, von Kev CAD gepflegt), `schriftfeld_fest`
(Felder, die Kevin gesetzt hat), `auto.massstab` und `auto.format` (Kev CAD wählt selbst, bis Kevin setzt),
`ansichten[i].fest` (verschoben, bleibt stehen), `.optional` (darf bei Platzmangel entfallen, Isometrie), `.titel`;
`masse[i].schluessel` (automatische Maße: wiedererkennen über Läufe), `.seite` (unten, oben, links, rechts),
`.text_versatz` (Lage der Zahl nach `mass_verschieben`), `.anker` (letzte Ansatzpunkte relativ zur Ansicht, damit ein
verwaistes Maß an seiner Stelle bleibt); Bezüge mit `element` (`lo0`, `hi0` … Grenze einer Tasche je Achse).
`unterdrueckt[i]` trägt zusätzlich `schluessel`. Merkmal-Kennungen: `huelle`, `seite:x-` … `seite:z+`, `stange`,
`ende:a`, `ende:b`, `bohrung:n`, `einsatztasche:n`, `muttertasche:n`, `langloch:n`, `lochbild:n`, `tasche:n`,
`absatz:n`, `fase:n`, `radius:n`.

**DRAWING_EDIT**, zusätzliche Operationen: `{"op": "format", "wert": "A3", "ausrichtung"}` (schaltet die
Formatwahl ab), `{"op": "mass_aendern", "id", "text", "toleranz", "fest"}` (Text mit `<>` für den Messwert).
`mass_neu.bezuege` nimmt neben Klicks auch Merkmal-Bezüge `{"merkmal": "bohrung:2", "teil"?}` (MCP).
`ACK` auf `DRAWING_EDIT` trägt `ergebnisse` (je Operation `{op, ok, id?, fehler?}`); danach folgt `DRAWING` ohne
`reply_to`. **DOCS_REQ** (App → Kernel, `id`): rechnet alle Blätter und antwortet mit `DOCS` (`reply_to`). `DOCS.blaetter[i]`
trägt zusätzlich `ausrichtung`, `massstab`, `masse`, `stand`, `hinweise`, `pruefung` (Anzahl).

Einzelteilblätter rechnen die Verdeckung exakt im Hilfsprozess mit 1,5 s Budget je Ansicht, sonst auf dem Netz.

## Anhang: Export und Bauplan in der App (P6-A2, rein additiv)

Umsetzung: Kernel `kevcad_kernel/dokument_export.py` (Laufzeit), `mcp_tools/dokument_tools.py` (MCP), Referenz
`protocol.doc_export_req` und `check_doc_export_res`; App `KevCADCore/Dokumente/Export*.swift` (Seiten, PDF, Druck),
`Bauplan*.swift` (Decoder, Durchspielen) und die Oberfläche unter `app/Sources/KevCAD/Dokumente/`. Testdateien:
`doc_export_req.frame`, `doc_export_res.frame` und Abschnitt `export` in `fixtures.json`
(`kernel/tools/make_export_fixtures.py`).

**DOC_EXPORT_REQ** (Kernel → App), Felder im Einzelnen:

| Feld | Inhalt |
|---|---|
| `id` | Anfrage; die App antwortet mit `DOC_EXPORT_RES` und `reply_to` |
| `bausteine` | Liste in der gewünschten Reihenfolge, je `{art, spalten?, auswahl?}`; `art` aus `deckblatt`, `produktbild` (Phase 7: Rendering auf eigener Seite), `stueckliste`, `teileliste`, `einkaufsliste`, `zuschnitt`, `zeichnungen`, `bauplan`; `spalten` (Spalten-ids der Tabelle in dieser Reihenfolge, sonst die der Vorlage bzw. die Vorgabe); `auswahl` nur bei `zeichnungen` (Blatt-ids, sonst alle). Leer mit `vorlage`: die Bausteine der Vorlage |
| `ziel` | absoluter Pfad der .pdf (der Kernel legt den Ordner an) oder null, wenn nur gedruckt wird |
| `drucken` | true: zusätzlich der macOS-Druckdialog, je Blattformat ein Auftrag mit `.pageScaleNone` |
| `format`, `ausrichtung` | Papier der Berichts- und Bauplanseiten (`A4`/`A3`, `hoch`/`quer`), null = Vorlage bzw. A4 hoch; Zeichnungsblätter behalten immer ihr eigenes Format |
| `vorlage` | Name einer Vorlage aus `vorlagen.json` oder null |

Spalten-ids: Stückliste `pos`, `bild`, `benennung`, `norm`, `material`, `masse`, `anzahl`, `gewicht`, `preis_je`,
`preis`, `herkunft`; Teileliste `nr`, `bild`, `name`, `baugruppe`, `herkunft`, `material`, `abmessungen`, `gewicht`;
Einkaufsliste `abhaken`, `menge`, `einheit`, `benennung`, `preis_je`, `preis`, `bezugsquelle`, `hinweis`; Zuschnitt
`stange`, `herkunft`, `stuecke`, `rest`, `verschnitt`.

**DOC_EXPORT_RES** (App → Kernel): `reply_to`, `ok`, `pfad` (geschriebene Datei oder null), `seiten`, `fehler` (Text
oder null), additiv `bausteine` (je `{art, seiten}`), `formate` (z. B. `{"A4 hoch": 13, "A3 quer": 1}`), `gedruckt`
(Text, wenn der Druckdialog offen ist, sonst null), `hinweise` (z. B. „Bauplan noch nicht gerechnet“), `ms`, `phasen`
(Dauer je Phase in ms: `bauplan_ms`, `blaetter_ms`, `bilder_ms`, `seiten_ms`, `pdf_ms`).

**MCP** `dokument_export(bausteine=None, ziel=None, drucken=False)`: `bausteine` wie oben, Einträge auch als Namen
(Groß- und Kleinschreibung egal, gängige Synonyme), `"alle"`, `"vorlage:<Name>"` oder `{format, ausrichtung}`.
Ohne `ziel`: `<projekt>/output/<Projekt>-dokumente.pdf`; ein relativer Pfad liegt in `output/`.

**`vorlagen.json`** (gehört der App):

```json
{"version": 1, "zuletzt": "Werkstatt",
 "vorlagen": [{"name": "Werkstatt", "format": "A4", "ausrichtung": "hoch",
               "bausteine": [{"art": "deckblatt", "an": true},
                             {"art": "stueckliste", "an": true, "spalten": ["pos", "bild", "benennung", "masse", "anzahl"]},
                             {"art": "zeichnungen", "an": true, "auswahl": null}, {"art": "bauplan", "an": true}]}]}
```

**PDF:** Kopf- und Fußzeile auf jeder Seite außer dem Deckblatt (Projekt, Baustein, Version und Datum, Seite x/y),
Tabellen brechen nur zwischen Zeilen und wiederholen ihren Kopf, Gruppenüberschriften bleiben bei ihrer ersten Zeile,
Inhaltsverzeichnis als PDF-Outline je Baustein. Berichtsschrift Helvetica Neue (Teilmenge eingebettet), Zeichnungen
wie die Blätter selbst.

**Durchspielen** (App): je Montageschritt sind nur die bis dahin montierten Teile zu sehen (Hauptmontage: alle
früheren Hauptschritte; Vormontage: nur Schritte derselben `baugruppe`), die neuen fahren aus `bild.explosion` (sonst
`−einbau.richtung × einbau.weg`) in ihre Lage, Kamera aus `bild.kamera`, eingepasst auf `bild.ausschnitt`. Schritte
der übrigen Abschnitte zeigen ihre `teile` hervorgehoben im fertigen Stand.
