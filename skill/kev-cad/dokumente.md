# Zeichnungen, Bauplan, Dokumente, Export

Teil des Skills kev-cad. Werkstattzeichnungen, Bauanleitung, PDF aus Bausteinen und Dateiexport.

## Technische Zeichnungen

Werkstattzeichnungen nach ISO 128/129-1 (Projektionsmethode 1, Schriftfeld ISO 7200, Allgemeintoleranz ISO 2768-m)
entstehen aus dem Modell; die Maße hängen an erkannten Merkmalen (Bohrung, Lochbild, Langloch, Tasche, Fase, Radius,
Stange mit Gehrung, Einsatz- und Muttertasche) und überleben Änderungen am Modell. Blätter liegen unter
`<Projekt>/dokumente/zeichnungen/<id>.json`, Kevin sieht und bearbeitet sie in der App (Bereich „Dokumente“).

Ablauf:

1. `zeichnung(aktion="erstellen")` nach einem fehlerfreien `run`: je Stücklistenposition eines gefertigten Teils (Rohre und
   Profile, Platten, Druckteile) ein Blatt, dazu der Zusammenbau mit Positionsnummern und Stückliste. Einzelne Teile
   mit `teile=["Gestell/Bein vorn links"]`, eine Baugruppe mit `art="baugruppe"`. Normteile und Zukaufteile bekommen
   keine Zeichnung. Vorhandene Blätter behalten Kevins Änderungen und werden nur neu gerechnet.
2. Jedes Blatt selbst prüfen: `zeichnung(aktion="bild", blatt=…)` (nur zur eigenen Prüfung, **Kevin keine Bilder schicken**) und
   die Prüfung im Ergebnis lesen (fehlendes Größen- oder Lagemaß, Überbemaßung, Überlappung, verwaiste Maße). Frage:
   Kann eine Werkstatt das Teil allein mit diesem Blatt fertigen?
3. Fehlende oder falsche Maße mit `zeichnung(aktion="bearbeiten", blatt=…, ops=…)` korrigieren, Bezüge über Merkmal-Kennungen aus
   dem Ergebnis von `zeichnung(aktion="erstellen")`:
   - `{"op": "mass_neu", "art": "linear", "ansicht": "v1", "bezuege": [{"merkmal": "seite:x-"}, {"merkmal": "bohrung:2"}], "richtung": "x"}`
   - `{"op": "mass_loeschen", "id": "m7"}` (automatische Maße bleiben dann weg), `{"op": "mass_aendern", "id": "m3", "toleranz": "H7"}`
   - `{"op": "ansicht_neu", "art": "schnitt", "schnitt": {"von": "v1", "ebene": {"punkt": [x, y, z], "normale": [0, 1, 0]}}}`
     für Innenmerkmale; `{"op": "massstab", "wert": "1:2"}`, `{"op": "format", "wert": "A3"}`, `{"op": "notiz", "text": "Grat entfernen", "lage": [30, 30]}`.
4. Kevin kurz berichten: welche Blätter, Format und Maßstab, was von Hand ergänzt wurde, offene Punkte.

Regeln der automatischen Bemaßung: Vorlage je Teiletyp (Rohr: eine Ansicht längs, Länge, Gehrung, Bohrungen ab dem
Rohrende; Platte: eine Ansicht, Dicke als Angabe, Lagen ab der Ecke unten links; Druckteil: Hüll- und Funktionsmaße,
sonst „nach 3D-Modell“), jedes Maß einmal, Lochbilder als „n× Ø“, symmetrische Lagen zur Mittellinie, ab vier Lagen
steigende Bemaßung, Hüllmaße außen. Gewinde und Einsatztaschen erkennt Kev CAD nur mit Gegenstück im Modell (Schraube,
Gewindestift, Gewindeeinsatz auf derselben Achse); fehlt es, steht nur der Durchmesser da. Abweichende Hausregeln
(Maßlinienabstand, Schraffur, Pfeil, Schrift) in `dokumente/hausregeln.json`.

## Bauplan

Kev CAD erzeugt aus dem Modell eine Bauanleitung zum Ausdrucken (Kevin, 22.10.2026: „was muss wann gemacht werden,
was muss wie montiert werden … alle Löcher, die gebohrt werden“). Datei `<projekt>/dokumente/bauplan.json`, in der
App im Bereich „Dokumente“ mit Strichbild je Schritt; Vertrag in DOKUMENTE.md.

- **Erzeugen:** `bauplan(aktion="zeigen")` (bei neuem Lauf rechnet Kev CAD einen vorhandenen Bauplan selbst nach). Fünf Abschnitte:
  Material (Einkauf, Bestand), Zuschnitt (je Stange mit Gehrung), Bearbeiten (Bohrbild je Teil mit Ø und Lage ab
  Rohrende bzw. Außenkante, Gewinde, Senkungen; Gewindeeinsätze einschmelzen, Gewindestifte einkleben), Drucken
  (Material, Ausrichtung als Schätzung, Temperaturen), Montage (Unterbaugruppen aus dem Namensbaum zuerst, dann die
  Hauptmontage; je Schritt ein Hauptteil mit seinen Verbindungsmitteln, gleiche Schritte als „4×“).
- **Was Kev CAD weiß, was du schreibst:** Reihenfolge, Einführrichtung, Teile, Verbindungsmittel, Werkzeug, Maße und
  Lagen kommen aus dem Kernel. Du formulierst danach die Texte mit `bauplan(aktion="bearbeiten")` (`{"op": "text", "schritt",
  "titel", "text", "hinweise"}`), knapp wie für eine Werkstatt: Schritt, Handgriff, Werkzeug, worauf achten, dazu
  Sicherheit (Quetschstellen an beweglichen Teilen, scharfe Kanten nach Sägen und Bohren, heißer Lötkolben,
  Schutzbrille). Zahlen nur aus den Schrittdaten übernehmen, nie schätzen oder anders runden; fehlt eine, schreiben,
  was zu messen ist.
- **Prüfen:** Jeder Montageschritt wird simuliert (`bauplan(aktion="pruefen")`): Einführweg frei (`einfuehrweg`), Reihenfolge
  (`reihenfolge`, auch die Regeln „a vor b“), Werkzeugzugang (`werkzeugzugang`: Innensechskant gerade über dem Kopf,
  Schlüssel um die Mutter, Finger um die Flügelmutter), Standsicherheit der Teilbaugruppe (`standsicherheit`), neue
  Teile im Bild sichtbar (`verdeckt`, Agrawala: mindestens 50 %). Hinweis „unter die Aufstandsfläche“ heißt: Baugruppe
  aufbocken oder umdrehen.
- **Probleme im Modell beheben, nicht im Text verstecken:** Passt ein Teil nicht hinein oder kommt das Werkzeug nicht
  hin, wird model.py geändert (Spiel, Einführschräge, Schlitz, Teilung, Muttertasche statt Schlüssel, Zugangsbohrung),
  dann `run`; der Bauplan folgt. Reihenfolge nur ändern (`verschieben`, `{"op": "vorher", "a", "b", "grund"}`), wenn
  mehrere Folgen gleich gut sind, und dann Kevin fragen.
- **Erhalten:** Texte von Agent und Kevin und Schritte mit `fest` bleiben bei jedem neuen Lauf (Zuordnung über die id
  und die Teile). Teile, die nicht zum Aufbau gehören (Umgebung, lose daneben), nimmt Kev CAD selbst heraus; weitere mit
  `{"op": "umfang", "ohne": ["Umgebung"]}`.
- **Grenzen:** Montage nur durch Schieben (ein- oder zweistufig), kein Drehen; Eigenteile einer Gruppe, die
  zusammenhängen (Rollwagen, Fluidkopf, Kamera), gelten als vorhanden und vormontiert; ohne `verbinde` sind Verbindungen
  und Werkzeug aus Kontakt und Normteilen geschätzt (steht am Schritt). Kevin keine Bilder schicken, die App zeigt sie.
- **Durchspielen:** Kevin spielt den Aufbau in der App Schritt für Schritt im 3D-Bereich durch (nur montierte Teile,
  neue fahren entlang der Einführrichtung ein). Das ist seine Ansicht; du prüfst mit `bauplan(aktion="pruefen")`.

## Dokumente als PDF

`export(formats=["pdf"], bausteine=…, ziel=None, drucken=False)` lässt die App ein PDF bauen, dieselben Seiten wie im Dialog
„Dokumente exportieren …“ (⇧⌘E): `deckblatt`, `produktbild` (Rendering auf eigener Seite: das jüngste aus
`output/renders/`, wenn es nach dem letzten Lauf entstand, sonst ein schnelles Studio-Bild), `stueckliste`,
`teileliste`, `einkaufsliste`, `zuschnitt`, `zeichnungen`, `bauplan`, in der angegebenen Reihenfolge; leer oder
`"alle"` = alles. Objekte wie
`{"art": "stueckliste", "spalten": ["pos", "bild", "benennung", "masse", "anzahl"]}` oder
`{"art": "zeichnungen", "auswahl": ["<blatt-id>", …]}` wählen Spalten bzw. Blätter; `"vorlage:<Name>"` nimmt eine
Vorlage, die Kevin im Dialog gesichert hat; `{"format": "A3", "ausrichtung": "quer"}` setzt das Papier der Listen und
des Bauplans (Zeichnungen behalten ihr Blattformat). Ohne `ziel` landet das PDF in `<projekt>/output/<Projekt>-dokumente.pdf`.
`drucken=true` öffnet den Druckdialog in der App, **nur wenn Kevin ausdrücklich drucken will**. Vorher `bauplan(aktion="zeigen")` und
`zeichnung(aktion="erstellen")`, damit die Bausteine Inhalt haben; die Antwort nennt Seiten je Baustein, Formate und Hinweise.

## Export

`export(formats=["step", "stl", "3mf"])` schreibt nach `<Projekt>/output/`, `export(formats=["bom_csv"])` die Stückliste als CSV. STEP für CAD und Fertigung, STL oder 3MF für den
Bambu-Drucker, GLB für Ansichten. `parts=["Halter/Schelle"]` exportiert nur diese Teile.
