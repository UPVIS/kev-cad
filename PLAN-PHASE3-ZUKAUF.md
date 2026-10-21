# Kev CAD · Phase 3: Zukaufteile per Link oder Nummer

Stand: 21.10.2026 (Zusammenführung auf `phase3-int`: Kernel Z-K und App Z-A mit Prüfung Stufe 1 und Phase 5,
Ende-zu-Ende mit echtem Kernel bestanden). Baut auf Phase 2 auf (Katalog, `lager.teil(...).verbauen(...)`, Stückliste). Gestartet am
21.10.2026 abends auf Zweig `phase3`; Verträge in KATALOG.md (Abschnitt Zukaufteil) und PROTOCOL.md (Phase 3). Grundlage ist die Recherche vom 21.10.2026 (Abschnitt „Fundstücke“ unten).

## Ziel

Kevin wirft Claude einen Shop-Link, eine Hersteller-Artikelnummer (MPN) oder eine EAN hin. Kev CAD legt daraus ein
Zukaufteil an:

- **Daten:** Hersteller, Nummer, Preis, Bild, Maße, Link.
- **CAD-Modell:** Gibt es ein Hersteller-Modell, wird es eingebettet. Sonst entsteht ein deutlich als „vereinfacht“
  markierter Ersatzkörper aus den Maßen.
- **Verwendung:** Das Teil lässt sich wie jedes Lagerteil verbauen und steht mit Preis und Link in der Stückliste.

**Fertig, wenn:**

1. „Bau diese Schublade mit dem Vollauszug https://… ein“ → Claude liest die Seite, legt das Zukaufteil an, findet das
   Hersteller-Modell oder zeigt Kevin den Download-Link, übernimmt die STEP-Datei aus `~/Downloads`, baut sie ein.
2. „Nimm ISO 4762 M6×20“ → kein Download, das Teil kommt aus bd_warehouse.
3. Ein Teil ohne CAD-Modell erscheint als Ersatzkörper mit den Shop-Maßen und dem Hinweis „vereinfacht“ im Teilebaum.
4. Die Stückliste zeigt je Zukaufteil Hersteller, Nummer, Stückpreis mit Datum, Link und die CAD-Quelle.

## Ablauf

```
Link / MPN / EAN
   │ 1. Produktdaten: Claude liest die Seite (eigener Browser bzw. WebFetch), Kev CAD wertet JSON-LD, Microdata,
   │    Open Graph aus; Kevin bestätigt Hersteller, Nummer, Preis, Maße
   ▼
Normteil? ── ja ──► bd_warehouse bzw. Katalog (Phase 2), fertig
   │ nein
   ▼
2. CAD suchen: TraceParts-API (Teilenummer + Katalog des Herstellers), sonst Deep-Link ins Herstellerportal
   (CADENAS/PARTcommunity, Misumi, item, igus …)
   ▼
3. STEP holen: über die API automatisch, sonst lädt Kevin mit seinem Konto herunter; Kev CAD beobachtet ~/Downloads
   und übernimmt neue .step/.stp/.zip der letzten Minuten
   ▼
4. Import: build123d import_step (Namen, Farben, Baugruppe), Einheiten und Achsen gegen die Shop-Maße prüfen,
   große Modelle als Instanz und grob tesselliert, BREP zwischengespeichert in <projekt>/zukauf/<hersteller>-<mpn>/
   ▼
5. Katalogeintrag art "zukaufteil" (Projekt-Ebene) und Stücklistenzeile
```

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| Z1 | **Kev CAD lädt Shop-Seiten nicht selbst**, Claude liest sie mit seinen Werkzeugen und übergibt die Felder; Kev CAD wertet mitgeliefertes HTML aus (extruct, BSD-3) | Mehr als die Hälfte der Shops blockt Abrufe vom Server (Amazon, Würth, Hornbach, Conrad …). Bot-Schutz wird nicht umgangen |
| Z2 | **TraceParts-API als einzige automatische CAD-Quelle**, Schlüssel liegt außerhalb des Repos (`~/Library/Application Support/de.upvis.kevcad/secrets.env`, nur für Kevin lesbar) | Einzige Hersteller-CAD-API mit Teilenummersuche. Bedingungen: Name/E-Mail/Firma beim Download, „powered by TraceParts“ anzeigen, keine Massenabrufe |
| Z3 | **Alles andere halbautomatisch:** Deep-Link öffnen, Kevin lädt herunter, Kev CAD übernimmt aus `~/Downloads` | Hersteller-Portale (CADENAS, Misumi, item) haben keine offene API oder verbieten automatische Abrufe |
| Z4 | **Zukauf-Modelle liegen im Projektordner, nie im Git** und nicht im mitgelieferten Katalog | Weitergabe an Dritte ist durch die Bedingungen der Hersteller meist ausgeschlossen |
| Z5 | **Ersatzkörper**, wenn kein Modell da ist: Quader oder Zylinder aus den Shop-Maßen, halbtransparent, Name mit „(vereinfacht)“ | Das Modell bleibt maßlich richtig im Raum, die Lücke ist sichtbar |
| Z6 | **Preise immer mit Datum und Link**, Währung netto/brutto wie im Shop angegeben | Preise veralten |

## Erweiterungen der Verträge (beim Start festschreiben)

- KATALOG.md: `art: "zukaufteil"` mit `hersteller`, `mpn`, `gtin`, `url`, `bild`, `preis.je_stueck`, `preis.stand`,
  `cad: {quelle, datei, lizenz, stand}`, `ersatz: {form, masse}`, `einbaupunkt` (Ursprung und Ausrichtung).
- MCP: `zukauf_anlegen(url|mpn|gtin, felder…)`, `zukauf_html(url, html)` (Auswertung von mitgeliefertem HTML),
  `cad_suchen(id)` (TraceParts bzw. Deep-Links), `cad_uebernehmen(id, pfad=None)` (ohne Pfad: neueste passende Datei
  aus `~/Downloads`), `zukauf_liste()`.
- Protokoll: `ZUKAUF_STATUS` (Kernel → App: Teil angelegt, wartet auf Download, importiert), `DOWNLOAD_SEEN`
  (App → Kernel: neue CAD-Datei in `~/Downloads`).
- App: Dialog „Zukaufteil hinzufügen …“ (Link oder Nummer einfügen, Felder bestätigen, „CAD suchen“ öffnet den Link im
  Standardbrowser), Beobachtung von `~/Downloads` mit Rückfrage „Diese Datei als CAD für … übernehmen?“, Zukaufteile im
  Teilebaum mit Symbol (Hersteller-CAD bzw. vereinfacht), in der Stückliste mit Link und Bild.

## Arbeitspakete (parallel)

| Strang | Inhalt |
|---|---|
| **Z-K Kernel** | Datenauswertung (extruct), Zukauf-Katalogeinträge, TraceParts-Client (mit Attrappe testbar, echter Test sobald der Schlüssel da ist), STEP-Import mit Prüfung und Zwischenspeicher, Ersatzkörper, Stückliste, MCP-Werkzeuge, Skill-Abschnitt |
| **Z-A App** | Dialog, Downloads-Beobachtung (FSEvents), Anzeige im Teilebaum und in der Stückliste, Rückfragen |

## Was Kevin beitragen muss

- **TraceParts-API-Schlüssel beantragen** (Formular, Prüfung dauert einige Tage):
  https://developers.traceparts.com/docs/requesting-apikey.md. Ohne Schlüssel läuft alles halbautomatisch.
- Zwei, drei echte Beispiel-Links aus dem Alltag (Schublade, Scharnier, Rolle, Profilverbinder) für die Abnahme.

## Fundstücke (Recherche 21.10.2026)

- Shop-Daten: OBI liefert vollständiges JSON-LD (GTIN, Maße, Preis), igus teilweise, Misumi nur im eingebetteten
  Seitenzustand, McMaster nur Open Graph. Amazon, Würth, Hornbach, Bauhaus, Häfele, Conrad, Digi-Key, RS, item24,
  Norelem und Ganter blocken Abrufe vom Server.
- Elektronik: Mouser- und Digi-Key-API (kostenlos mit Schlüssel), Nexar/Octopart (Evaluation mit 100 Teilen,
  CAD-Modelle nur dort und in Enterprise).
- CAD: TraceParts-API (`Search/PartNumber/Availability`, `CADDataAvailability`, `CadRequest`, `CadFileUrl`);
  CADENAS ohne offene API, aber mit eingebettetem Portal (Vorbild: offizielles 3Dfindit-Addon für FreeCAD, LGPL-3.0);
  Misumi/item/igus nur über Login; GrabCAD für Kundenprojekte ungeeignet (kommerziell nur mit Erlaubnis).
- Kein vorhandener MCP-Server holt Hersteller-STEP per Teilenummer – echte Lücke.
- build123d `import_step` behält Namen, Farben und Baugruppen (`STEPCAFControl_Reader`).
