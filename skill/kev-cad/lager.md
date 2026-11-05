# Inventar, Lagerteile, Stückliste, Bestand, Zukaufteile

Teil des Skills kev-cad. Gebaut wird nur aus dem Inventar; wie Lagerteile und Zukaufteile verbaut werden, was Stückliste, Bestand und Einkaufsliste zeigen.

## Inventar-Regel

Standard für jedes Projekt: **Gebaut wird nur aus dem Inventar.**

- Jedes Teil in `show()` stammt aus `lager.teil(...).verbauen(...)`, aus einem freigegebenen Zukaufteil
  (`lager.zukauf(...).verbauen(...)`, siehe „Zukaufteile“) oder ist ausdrücklich ein 3D-Druckteil:
  `lager.druckteil(form, "Halter/Schelle", material="petg")`. Druckmaterial muss freigegeben und druckbar sein
  (`katalog(art="material")` zeigt „druckbar“: PLA, PETG, ABS, ASA, TPU 95A, PA, PA-CF, PC-Filament, PLA-CF, Standardharz);
  `verfahren="3d-druck"` (Standard) oder `"harzdruck"`.
- Materialien nur aus dem Katalog (id oder Alias), auch bei `show(material=...)`. Unbekannte oder nur vorgeschlagene
  Materialien brechen den Lauf mit Vorschlägen ab.
- Nichts erfinden. Fehlt ein Teil oder Material: erst `katalog` mit anderen Wörtern, dann Kevin fragen. Nur auf
  seinen Wunsch mit `lager(aktion="teil_vorschlagen")` bzw. `lager(aktion="material_vorschlagen")` vorschlagen. Ein Vorschlag wartet auf Kevins Freigabe und
  lässt sich vorher nicht verbauen. **Freigabe anfragen:** `lager(aktion="freigabe", ids=["id", …], grund="wofür")` öffnet im
  Projektfenster den Dialog „Vorschläge freigeben“ (Daten, Link, „Freigeben“ je Eintrag und für alle), wartet auf
  Kevins Klick (Standard 120 s) und meldet, was freigegeben, abgelehnt oder offen ist. Nie „bitte im Lagerkatalog
  freigeben“ schreiben. Schreibt Kevin im Chat „freigegeben“, ist damit nichts freigegeben: dann ebenfalls
  `lager(aktion="freigabe")` aufrufen, er klickt nur noch. Das Werkzeug gibt nie selbst frei. Freigegebene Einträge ändert
  nur Kevin. Ist VoiceBridge verbunden, kann Kevin die Anfrage auch vom iPhone freigeben (sie geht direkt an ihn, am
  Agenten vorbei); der Agent gibt nie selbst frei und reicht keine Freigabe weiter.
- Verstöße: `run` meldet „Inventar-Regel: 2 Teile sind nicht aus dem Inventar: …“ als isError. Die Geometrie ist zu
  sehen, aber Export (STEP, STL, 3MF, Stückliste) wird verweigert. Passendes Lagerteil verbauen, als Druckteil
  kennzeichnen oder Kevin bitten, das Lagerteil anzulegen.
- **Kulisse** (Kevin, 22.10.2026): Umgebung nur für Bilder und Videos, die weder gekauft noch gebaut wird (gekachelter
  Boden, Wand, Tisch, Straße): `show(form, "Kulisse/Boden", color="#D9D6CF", kulisse=True)` oder
  `show(lager.kulisse(form, "Kulisse/Wand"), "Kulisse/Wand")`. Ausgenommen von Stückliste, Inventar-Regel (Material
  frei), Druckprüfung, Befestigung (`verbinde`) und Einbaubarkeit; weiter erfasst bei der Durchdringung (nichts steckt
  im Boden) und als Auflage: was auf einer Kulisse steht, steht auf dem Boden (Schweben, Standsicherheit). Namen unter
  „Kulisse/“, dann lässt sich die Gruppe im Viewer ausblenden; ohne Farbe kommt sie hellgrau. **Nur für Umgebung, nie
  für echte Teile des Entwurfs.**
- Abschalten kann nur Kevin, je Projekt (kevcad.json `"inventar_regel": false`, etwa für Nachbauten aus Fotos). Diese
  Einstellung nie selbst ändern. Ist die Regel aus, gelten auch Materialnamen aus build123d (`aluminum`, `oak`, …) und
  frei modellierte Teile mit Material erscheinen als „Eigenteil“.

## Lagerteile verbauen

- Stangenware (Rohr, Vierkant-/Rechteckrohr, Flach-, Rund-, Vierkantstahl, Winkel, U-Profil, Nutprofil, Holz):
  `teil.verbauen(laenge=842, name="Gestell/Bein vorn links", gehrung=(0, 0))`. Das Teil liegt entlang +Z ab z = 0,
  der Querschnitt mittig. `laenge` ist das **Zuschnittmaß an der längsten Kante**. `gehrung=(anfang, ende)` in Grad um
  die lokale X-Achse: positiv lässt die Kante bei +Y lang (Rahmenleiste mit Außenkante bei +Y), negativ die bei -Y.
  `drehung=90` dreht den Querschnitt vorher um Z (Gehrung über die andere Seite). Querschnitte: Breite b in X,
  Höhe h bzw. Dicke s in Y; Winkel mit Schenkel a nach +Y und b nach +X; U-Profil nach +X offen.
- Platten: `platte.verbauen(breite=800, tiefe=600, name="Deckel")` in der XY-Ebene ab z = 0, mittig; oder
  `form=Rectangle(800, 600) - Circle(40)` (Skizze in XY).
- Schrauben: `schraube.verbauen(laenge=60, name="Schrauben/M8x60 1")` (bd_warehouse, Kopf auf z = 0, Schaft nach -Z,
  ohne Gewinde); Muttern und Scheiben ohne `laenge`.
- **Name in `show()` gleich wie in `verbauen()`.** Dann kennt die Stückliste das gezeigte Teil, auch nach Verschieben,
  Drehen oder Bohren. Gleiche Teile durchnummerieren: „Schrauben/M8x60 1“ … „8“.
- Rahmen mit Gehrung: Leiste mit `gehrung=(45, 45)` verbauen, erst um die eigene Achse drehen (lange Kante nach außen),
  dann hinlegen, dann schieben. Beispiel: `samples/gestell/model.py`.
- Jede `verbauen`-Zeile steht in der Stückliste, auch wenn das Teil später gebohrt wird. Gleiche Lagerteile mit
  gleicher Länge und Gehrung werden zusammengefasst.

## Stückliste

- `parts(stueckliste=true)`: Positionen (Anzahl, Maße, Gehrung, Material, kg, €), Zuschnitt je Stangenware („Stange 1: 882 + 882 + … =
  5.394 mm, Rest 606 mm“, Sägeschnitt 3 mm, Verschnitt in %), Summen mit Richtpreis-Hinweis, Hinweise (etwa nicht
  zugeordnete Lagerteile). Verschnitt heißt wie in der App: Sägeschnitte und Reste unter dem Mindestrest, bezogen auf
  die verplante Länge bzw. Fläche; neue Reste zählen nicht (`verschnitt_definition: "2"`). `parts(stueckliste=true, format="csv")` liefert CSV, `export(formats=["bom_csv"])` schreibt die Datei.
- Preise sind Richtwerte mit Stand; so auch an Kevin weitergeben.

## Bestand und Einkauf (Kevin, 21.10.2026)

Jedes Projekt hat seinen eigenen Bestand (`bestand.json` im Projektordner): ganze Stangen und Platten, Reste mit
Kennung (R-0001, P-0001) und Länge bzw. Maß, Stückgut wie Schrauben je Länge. Nichts gilt projektübergreifend.

- Der Zuschnitt nimmt nach jedem Lauf zuerst passende Reste, dann ganze Stangen bzw. Platten aus dem Bestand, dann
  zu kaufende (optimiert, mit Mindestrest und Sägeblatt). `parts(stueckliste=true)` zeigt je Rest, Stange und Platte die Stücke und die
  neuen Reste, `bestand(aktion="liste")` den Bestand.
- `bestand(aktion="einkaufsliste")` liefert genau die Liste, die Kevin unter „Material › Einkaufsliste“ sieht und teilt (gleicher Text,
  gleiche CSV): Lagerware (was nach Resten und Bestand fehlt, Normteile zum Kaufen eingeschlossen), Zukaufteile (Link
  und Preis aus dem Katalog), Summe dieser beiden, dann „Normteile abzählen“ (gebraucht, aus Bestand, kaufen) und
  „Filament für Druckteile“ (aus der Druckvorschau, sonst Volumen × Dichte; nicht in der Summe).
- **Bestand nur nach Kevins Angabe eintragen** (`bestand(aktion="eintragen")`, seine Worte in `grund`), nie schätzen oder
  erfinden; jede Änderung aus der Antwort an Kevin nennen. Zukaufteile, Kameras, Objektive und Kamerazubehör sind
  Stückgut: `bestand(aktion="eintragen", id="blackmagic-pocket-6k-pro", stueck=1, grund=…)`; was Kevin hat, fällt aus der
  Einkaufsliste („Zukaufteile aus dem Bestand“).
- **Filament** (Strang „Bestand Stufe 2“): Spulen je Material und Farbe mit Kennung S-0001, Gramm übrig, Gramm voll,
  Name, Hersteller, Ort: `bestand(aktion="eintragen", material="petg", gramm=640, spule="Bambu PETG Basic schwarz",
  grund=…)`; mehrere volle Spulen mit `anzahl`, ändern mit `kennung="S-0002", gramm=310`, entfernen mit
  `spulen_entfernen`; „kein Filament da“ mit `anzahl=0`. Sobald das Projekt Filament führt, stehen unter Lagerware die
  Spulen, die der Druckvorschau desselben Laufs fehlen (Fehlmenge auf ganze Spulen aufgerundet, Spulengröße aus dem
  Katalog `spule_g`, sonst 1 kg), mit Preis in der Summe. Farben kennt die Druckvorschau nicht: Bedarf und Bestand
  gelten je Material.
- **„Gedruckt“ nur auf Kevins ausdrücklichen Wunsch** (`bestand(aktion="gedruckt", grund=…, platten=…, spule=…)`): bucht das
  Filament der Druckvorschau ab, angebrochene Spulen zuerst bzw. die Spule, die Kevin nennt; was der Bestand nicht
  deckt, gilt als von gekauften Spulen gedruckt, deren Rest als neue Spule dazukommt. Jede Platte nur einmal je Lauf.
- **„Gebaut“ nur auf Kevins ausdrücklichen Wunsch** (`bestand(aktion="gebaut")`): bucht verplante Reste, ganze Stangen und
  Stückgut ab, legt die neuen Reste an und bucht das Filament der noch nicht als gedruckt gebuchten Platten ab. Jede
  Buchung lässt sich mit `bestand(aktion="rueckgaengig")` umkehren.
- **Einkaufsliste im Bericht nennen:** nach dem Bauen eines Modells die Positionen mit Summe aus `bestand(aktion="einkaufsliste")`
  aufführen, oder ausdrücklich sagen, dass alles aus dem Bestand kommt.

## Zukaufteile

Fertig gekaufte Teile mit Hersteller und Nummer (Schubladenauszug, Scharnier, Rolle, Rollwagen). Sie zählen zum
Inventar, sobald Kevin sie freigegeben hat. Kameras, Objektive und Kamera-Zubehör: siehe „Kameras“.

```python
wagen = lager.zukauf("alutec-05200")          # nach id; sonst lager.zukauf(mpn="05200", hersteller="ALUTEC") oder gtin=
rw = wagen.verbauen("Rollwagen")              # Hersteller-CAD, Skript-Geometrie oder Ersatzkörper
show(Pos(0, y, 0) * rw, "Rollwagen")          # gleicher Name wie in verbauen
oben = wagen.bezugspunkt("oben")              # Location im System des verbauten Teils
show(Pos(0, y, 0) * oben * ball, "Ball")      # auf die Ladefläche gesetzt
```

- Das verbaute Teil liegt mit seinem **Einbaupunkt** im Ursprung (Standard: Mitte der Unterseite, Z oben).
  Bezugspunkte (`bezugspunkte` im Katalog) gelten im selben System; Lage daraus ableiten statt Zahlen abzuschreiben.
- Hersteller-CAD mit Baugruppe erscheint als Baum („Rollwagen/Platte“, „Rollwagen/Rolle_1“). Ohne Modell ist es ein
  **Ersatzkörper** (Quader oder Zylinder aus den Shop-Maßen), halbtransparent und mit „(vereinfacht)“ im Namen.
  **Vereinfachte Teile im Bericht an Kevin immer nennen.**
- Die Prüfung behandelt Zukaufteile wie alle Teile: Hersteller-CAD und Ersatzkörper dürfen nichts durchdringen.
  Überlappt ein Zukaufteil sein Gegenstück nur, weil das Modell vereinfacht ist (Gewinde als Vollzylinder,
  Ersatzquader), ist das trotzdem ein Befund: im Modell lösen oder `erlaubt_ueberlappung(…, grund=…)` erst nach
  Rückfrage bei Kevin.
- Skript-Geometrie (`cad.quelle: "skript"` mit `datei`/`modul` und `funktion`): `verbauen(name, **kwargs)` reicht
  Schlüsselwörter an die Funktion weiter.

Ablauf, wenn Kevin einen Link, eine Herstellernummer oder eine EAN nennt:

1. **Seite selbst lesen** (Browser oder WebFetch). Kev CAD lädt keine Shop-Seiten und umgeht keinen Bot-Schutz. Bei
   einer EAN erst den Artikel suchen.
2. **Normteil?** „ISO 4762 M6×20“, „DIN 934 M8“: kein Zukaufteil, sondern `katalog` und `lager.teil(...)`
   (`lager(aktion="zukauf_anlegen")` leitet selbst um).
3. **Anlegen:** HTML an `lager(aktion="zukauf_html", url=…, html=…)` (wertet JSON-LD, Microdata und Open Graph aus) oder die gelesenen
   Felder an `lager(aktion="zukauf_anlegen", url=…, felder={name, hersteller, mpn, gtin, preis {je_stueck, waehrung, brutto}, masse {l,
   b, h} bzw. {d, l}, gewicht, bild})`. Preis immer mit brutto/netto wie im Shop. Kevin Hersteller, Nummer, Preis und
   Maße bestätigen lassen (`zu_pruefen` in der Antwort). Das Teil ist ein **Vorschlag**, bis Kevin es freigibt
   (`lager(aktion="freigabe", ids=[id], grund)` öffnet den Dialog im Projektfenster); vorher lässt es sich nicht verbauen.
4. **CAD suchen:** `lager(aktion="cad_suchen", id=…)` liefert Links (Produktseite, Herstellerportal, 3Dfindit, Websuche); eine
   automatische CAD-Quelle gibt es nicht (TraceParts ist seit dem 22.10.2026 stillgelegt, Kevins Entscheidung):
   **Kevin bitten, das STEP (oder ein ZIP mit STEP) mit seinem Konto herunterzuladen.** Die App beobachtet derweil
   `~/Downloads` und fragt ihn selbst.
5. **Übernehmen:** `lager(aktion="cad_uebernehmen", id=…)` ohne Pfad nimmt die neueste passende Datei aus `~/Downloads` (auch aus ZIP).
   Zoll, Zentimeter und „Y oben“ werden erkannt und korrigiert (steht im Ergebnis); passt das Hüllmaß nicht zu den
   Katalogmaßen, wird abgelehnt (falsche Datei? Maße prüfen; `erzwingen=True` nur nach Rückfrage). Die Datei liegt
   danach in `<projekt>/zukauf/<id>/` (nie im Git, Herstellerbedingungen).
6. `run`, prüfen wie immer, `parts(stueckliste=true)` zeigt das Teil mit Hersteller, Nummer, Stückpreis mit Datum, Link und CAD-Quelle.

`lager(aktion="zukauf_liste")` zeigt alle Zukaufteile mit Freigabe und CAD-Stand. Die Summe der Stückliste mischt Richtpreise (netto)
und Shoppreise (oft brutto); die Stückliste sagt das dazu, so auch an Kevin weitergeben.
