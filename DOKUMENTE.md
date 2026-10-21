# Kev CAD · Dokumente (Vertrag Phase 6)

Version 1 (22.10.2026). Verbindlich für Zeichnungen, Bauplan und Berichte aus
[PLAN-PHASE6-DOKUMENTE.md](PLAN-PHASE6-DOKUMENTE.md). Änderungen nur gemeinsam: dieses Dokument, `protocol.py`,
Testdateien und Swift-Decoder im selben Commit (wie PROTOCOL.md). Einheiten auf dem Blatt: mm, Ursprung links unten,
y nach oben. Modellkoordinaten wie überall: mm, Z oben.

## Ablage

```
<projekt>/dokumente/
├── zeichnungen/<blatt-id>.json   je Blatt
├── bauplan.json
└── vorlagen.json                 Export-Vorlagen (gehört der App)
```

Die Dateien gehören zu den Projektdateien (Versionen erfassen sie). Erzeugte Vektoren werden nicht gespeichert,
sondern bei jedem Lauf neu gerechnet.

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
                 "gezeichnet": "Kev CAD", "notiz": null},
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
 "auto": {"ansichten": true, "masse": true}}
```

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
                "hervorheben": ["…"]},
       "pruefung": [<Befund>]}
    ]}
 ]}
```

- Der Kernel erzeugt das Gerüst bei jedem Lauf neu und übernimmt dabei alle Schritte mit `fest: true` sowie Texte mit
  `quelle` agent/kevin, zugeordnet über `id` und Bezüge.
- `pruefung` füllt die Simulation (D7) mit Befunden im gemeinsamen Format (`art`, `teile`, `schwere`, `text`, `ort`,
  `loesung`); Arten `einfuehrweg`, `werkzeugzugang`, `standsicherheit`, `reihenfolge`.

## Protokoll (additiv)

| type | Richtung | Felder | Nutzlast |
|---|---|---|---|
| `DOCS` | Kernel → App | `run`, `blaetter` (Liste `{id, titel, inhalt, format, verwaiste_masse}`), `bauplan` (Zusammenfassung `{abschnitte, schritte, probleme}`) – nach jedem Lauf und nach dem Verbinden | – |
| `DRAWING_REQ` | App → Kernel | `id`, `blatt` | `DRAWING` |
| `DRAWING` | Kernel → App | `reply_to` (optional), `blatt` (Inhalt der Datei), `geometrie` (je Ansicht `{id, rahmen: [x0,y0,x1,y1], linien: {sichtbar, verdeckt, mitte, schnitt, schraffur, duenn}}` mit Polylinien in Blatt-mm), `masse` (je Maß die fertige Darstellung `{id, linien, pfeile, text, text_lage, text_winkel, wert}`), `stand` | Polylinien als f32-Arrays (siehe unten) |
| `DRAWING_EDIT` | App → Kernel | `id`, `blatt`, `ops` (Liste, siehe unten), `von`: `kevin` | `ACK`, danach `DRAWING` |
| `BAUPLAN_REQ` | App → Kernel | `id` | `BAUPLAN` |
| `BAUPLAN` | Kernel → App | `reply_to` (optional), `bauplan` (Inhalt der Datei mit Prüfung), `bilder` (je Schritt Strichbild wie `geometrie` einer Ansicht, Blatt-mm in einem Feld 180 × 120) | Polylinien |
| `BAUPLAN_EDIT` | App → Kernel | `id`, `ops`, `von` | `ACK`, danach `BAUPLAN` |
| `BAUPLAN_PRUEFEN` | App → Kernel | `id`, `schritt` (oder null für alle) | `ACK`, danach `BAUPLAN` |
| `DOC_EXPORT_REQ` | Kernel → App | `id`, `bausteine` (Liste wie im Export-Dialog), `ziel` (Pfad .pdf) oder `drucken: true` | App antwortet `DOC_EXPORT_RES` |
| `DOC_EXPORT_RES` | App → Kernel | `reply_to`, `ok`, `pfad`, `seiten`, `fehler` | – |

Polylinien-Nutzlast: je Linienart nacheinander `u32 Anzahl Polylinien`, je Polylinie `u32 Punktzahl` und `f32 x, y`
paarweise; Reihenfolge der Linienarten wie im Kopf `linien_reihenfolge`. Maße und Texte im JSON-Kopf.

`DRAWING_EDIT.ops`: `{"op": "mass_verschieben", "id", "versatz" | "text_lage"}`, `{"op": "mass_loeschen", "id"}`,
`{"op": "mass_neu", "art", "ansicht", "bezuege": [{ "ansicht", "punkt": [x, y] (Blatt-mm, der Kernel sucht das nächste
Element) } …], "versatz"}`, `{"op": "ansicht_neu", "art", "lage"}`, `{"op": "ansicht_verschieben", "id", "lage"}`,
`{"op": "ansicht_loeschen", "id"}`, `{"op": "massstab", "wert"}`, `{"op": "notiz", "text", "lage", "zeiger"}`,
`{"op": "notiz_loeschen", "id"}`, `{"op": "schriftfeld", "feld", "wert"}`, `{"op": "auto", "ansichten": bool, "masse": bool}`.

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
