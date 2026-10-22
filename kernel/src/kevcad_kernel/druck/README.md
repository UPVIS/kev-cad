# kevcad_kernel.druck · Druckprüfung für 3D-Druckteile

Prüft eine build123d-Form auf Druckbarkeit mit Kevins Bambu Lab P1P (FDM, offen, Edelstahldüse 0,4 mm, Schicht 0,2 mm)
und schlägt eine Ausrichtung vor. Regeln und Quellen: [skill/kev-cad/3d-druck.md](../../../../skill/kev-cad/3d-druck.md).
Nur numpy, build123d und OCP; keine weiteren Abhängigkeiten.

| Datei | Inhalt |
|---|---|
| `regeln.py` | Druckerprofil `P1P` (aus den installierten Bambu-Studio-Profilen), `MATERIALIEN` (ids wie im Kev-CAD-Katalog), Schwellen, Tabellen (Gewindeeinsätze, Muttern, Kernlöcher, Passungen, Schnapphaken) mit Quellen-Schlüsseln (`QUELLEN`) |
| `netz.py` | vernetzt eine **Kopie** der Form (die Originalform bleibt ohne Dreiecke), Flächeninfos (Ebene, Zylinder mit Achse/Radius/Bogen/hohl), Kanten, Nachbarschaft, Punkt-in-Körper |
| `pruefung.py` | `pruefe_druckteil(...)`, `als_warnungen(...)` |

## API

```python
from kevcad_kernel.druck import pruefe_druckteil, als_warnungen

e = pruefe_druckteil(form, material="petg", ausrichtung=None)   # drucker=P1P
e["ok"]                     # False, sobald ein Fehler dabei ist (z. B. passt nicht in den Bauraum)
e["zusammenfassung"]        # "1 Warnung, 2 Hinweise (PETG, Bambu Lab P1P)"
e["ausrichtung"]            # unten, drehung (Rot(*drehung) * form legt es so aufs Bett), liegt_auf, automatisch,
                            # begruendung (deutscher Satz), kandidaten (die 5 besten Lagen mit Kennzahlen)
e["hinweise"]               # [{art, schwere, text, befund, abhilfe, flaeche, flaechen, punkt, werte}], Fehler zuerst
e["kennzahlen"]             # stuetzflaeche_mm2, auflageflaeche_mm2, hoehe_mm, schichten, abmessungen_mm,
                            # bauraum_ausnutzung_prozent, volumen_cm3, masse_voll_g, dreiecke, laufzeit_ms
e["druckhinweise"]          # Materialeinstellungen (Temperatur, Kammer, Trocknen, AMS), Festigkeit, Profil
als_warnungen(e)            # ["Druck Warnung: … [#f6]", …] nur Fehler und Warnungen, höchstens 8 Zeilen
```

- `ausrichtung`: `None` automatisch; `"-z"` wie modelliert, `"+x"` usw. = diese Seite aufs Bett; Flächennummer (int);
  Richtungsvektor (zeigt im Modell aufs Bett); build123d `Rot(...)`/`Location`.
- `flaeche`/`flaechen` sind Indizes in `form.faces()` (= Kev-CAD-Referenz `Teil#f<n>`), `punkt` liegt in
  Modellkoordinaten – passend zum Viewer, auch wenn die Prüfung das Teil gedreht hat.
- Das Ergebnis ist reines JSON (`json.dumps(e, allow_nan=False)` geht).
- `material`: id oder Alias (`material("nylon")` → `pa`); unbekannt → `ValueError` mit Vorschlägen.
  `harz-standard` ergibt einen Fehler (kein Harzdrucker). ABS, ASA, PC und PA warnen auf dem offenen P1P (nur mit
  Einhausung), CF-Filamente ohne gehärtete Düse (`Drucker(geschlossen=True, duese_gehaertet=True)` nach Umbau).
  Alias `"Amazon Basics PLA"` → `pla` (Kevins Filament, Temperaturen in `druckhinweise`).

## Einbindung (seit 22.10.2026)

| Datei | Rolle |
|---|---|
| `anbindung.py` | Prüfer „druck“ (`registriere("druck", pruefe, nach="durchdringung")`, aktiv über `pruefung/lauf.py`): prüft nach jedem Lauf im Rechenprozess jedes gezeigte `lager.druckteil`, Befunde `druck_<art>` (ids `dr1` …), `ergebnis["druck"]` mit Ausrichtung, Begründung und Kennzahlen je Teil; Zwischenspeicher |
| `bericht.py` | Texte und Auszüge: Laufergebnis (`druck_kurz`, Druck-Hinweise nur im Werkzeug), Zeilen für `run`, `druck_auszug`/`druck_text` für das Werkzeug |
| `laufzeit.py` | `DruckRuntime.druckpruefung(teil)` (Mixin der `KernelRuntime`, Vertrag in `service.py`): liest das letzte CHECK, rechnet nichts |
| `mcp_tools/druck_tools.py` | MCP-Werkzeug `druckpruefung(teil=None)` |

- **Weg der Daten:** `lager.druckteil(..., ausrichtung=None)` legt Material, Verfahren und Ausrichtung an die
  Stücklistenzeile (`Piece.ausrichtung`); `pruefung/erfassung.py` übernimmt sie samt der Lage der Form, wie sie an
  `druckteil` ging (`druck_rahmen`). Geprüft wird diese Form ohne Verschiebung; Flächennummern bleiben gleich, Punkte
  rechnet die Anbindung in Weltkoordinaten um. CHECK trägt zusätzlich das Feld `druck` (die App ignoriert es).
- **Schwere im Lauf:** Fehler (Export gesperrt) nur aus harten Gründen – Bauraum samt Sperrfläche, Harzdruck (Material
  oder `verfahren="harzdruck"`), CF-Material ohne gehärtete Düse (`werte.grund`). Andere Fehler der Prüfung werden
  zur Warnung (`wert.schwere_druckpruefung` nennt die ursprüngliche Schwere).
- **Zwischenspeicher:** Schlüssel Form ohne Lage (`Koerper.form`) + Drehung der Druckteil-Form + Material +
  Ausrichtung, höchstens 512 Einträge. Verschieben der Baugruppe und gleiche Teile kosten nichts. Kugelschieber (20
  Druckteile PETG): kalt ca. 1,6 s (16 gerechnet, 4 gleiche Stellringe aus dem Speicher), warm ca. 1 ms.
- **Abdrücke:** Schichtraster-Hinweise an Flächen, deren Ecken alle ≤ 1,5 mm an einem gezeigten Lager- oder
  Zukaufteil liegen (Aussparung), bündelt `_abdruecke_buendeln` je fremdem Teil zu `druck_schichtraster_abdruck`.

## Druckvorschau (DRUCKVORSCHAU.md, seit 22.10.2026)

| Datei | Rolle |
|---|---|
| `vorschau_geo.py` | Prüfer „druckvorschau“ nach „druck“ (Rechenprozess): Grundriss (konvexe Hülle), Flächen nach Richtung, Überhanghöhe, Seitenfläche je Höhenband je Druckteil in Druckausrichtung; `check["druck"]["vorschau"]` |
| `empfehlung.py` | Einstellungen je Zweck und Material mit Begründung, Hinweise der Druckpraxis, Erfolgsrisiko |
| `schaetzung.py` | Filament und Zeit je Stück (Bahnlängen, Volumenstrom, Kühlung), Abgleich `abgleich.json` |
| `anordnen.py` | schnelles Anordnen (Skyline, 90°, Abstand, Sperrzone), ein Material je Platte |
| `vorschau.py` | Gruppen gleicher Teile, Summen, Kosten; ersetzt Schätzungen durch Slicer-Ergebnisse (`SlicerStand`) |
| `slicer.py` | Bambu Studio: Profile, STL in Druckausrichtung, Slicen, `--arrange`, Platten, 3MF je Material |
| `dreimf.py` | 3MF ohne Bambu Studio (je Platte eine Datei) |
| `vorgaben.py` | `<projekt>/druck.json` (feste Vorgaben je Teil mit `von`) |
| `vorschau_laufzeit.py` | Mixin der Laufzeit: PRINT_PREVIEW, Slicer im Hintergrund, PRINT_SETTINGS, PRINT_EXPORT_REQ, MCP-Dienste |
| `vorschau_text.py` | Kurzfassung für das MCP-Werkzeug `druckvorschau` |

Messung am Kugelschieber (15 Druckteile PETG, 22.10.2026): Geometrie im Rechenprozess 32 ms kalt / 2 ms warm, Bau der
Vorschau 10–13 ms, PRINT_PREVIEW 33–77 ms nach CHECK; Bambu Studio je Gruppe 0,5–2,7 s, alles samt Anordnen und
Platten 44 s; Schätzung gegen Slicer −8 bis +5 % Zeit, −2 bis +3 % Filament.

## Wie die Prüfung arbeitet

- **Bauraum:** 256 × 256 × 250 mm aus dem P1P-Maschinenprofil, Sperrbereich 18 × 28 mm vorne links muss frei
  bleiben (Teil rechts daneben oder dahinter), 5 mm Rand für Brim; Drehungen um Z in 1°-Schritten.
- **Netz:** BRepMesh auf einer Kopie, Ablenkung diag/1000 (0,01–0,1 mm), 0,3 rad. Auflage zählt nur auf ebenen Flächen.
- **Ausrichtung:** sechs Achsrichtungen und die Normalen der acht größten ebenen Flächen. Bewertet (kleiner ist besser):
  Stützfläche (projiziert, kurze Brücken ≤ 10 mm ausgenommen) + 0,6 · fehlende Auflage + 0,25 · Höhe
  + 0,3 · Anteil waagrechter Bohrungen + Strafen für Auflage < 25 mm², nicht passend (10) oder ohne Rand (1);
  „wie modelliert“ hat 0,05 Bonus. Die Lastrichtung kennt die Prüfung nicht – das sagt die Begründung dazu.
- **Überhang:** Dreiecke steiler als die Materialgrenze (+0,5° Toleranz), über der ersten Schicht, nicht auf dem Bett;
  je Fläche zusammengefasst, schmale Streifen (Grundriss ≤ 1 mm) ausgenommen.
- **Waagrechte Unterseiten:** Halt hat eine Randkante, unter der Material liegt (OCCT-Klassifikation 0,3 mm seitlich,
  eine halbe Schicht tiefer). Wie im Slicer eine Brückenrichtung je Fläche (12 Richtungen), der Weg zum Halt muss in
  der Fläche liegen; Punkte ohne beidseitigen Halt kragen aus. Ringfläche mit nach oben weiterlaufender Bohrung =
  Gegenbohrung zur Bettseite; eine Schicht dicke Haut darüber = erkannte Opferschicht.
- **Wandstärke:** ca. 4000 flächengewichtete Stichproben, Strahl gegen die Normale ins Material, vektorisiert auf dem
  Netz (Möller–Trumbore, räumlich gruppiert, Reichweite ≈ 1,3 mm). Gezählt wird nur eine fast parallele Gegenfläche
  (≤ 20°), damit Fasen und Keilspitzen nicht als dünne Wand gelten. Steile Wände messen in Bahnbreiten, flache in
  Schichten.
- **Bohrungen/Stifte:** Zylinderflächen gleicher Achse zusammengefasst (Bogen ≥ 180° = Bohrung, ≥ 300° = voll).

## Laufzeit (MacBook, Kernel-venv)

| Teil | Dreiecke | Zeit |
|---|---|---|
| Winkel, Kasten, Block mit Bohrung | 20–200 | 30–50 ms |
| gutes Teil mit Rundungen und Fasen | 1 600 | 100–200 ms |
| Gehäuse 120 × 80 mit Rippen, Domen | 3 200 | 90–125 ms |
| Gehäuse 220 × 160 mit 70 Löchern und Schrift | 15 800 | 500–600 ms |

## Grenzen und offene Punkte

- Lasten und Funktion kennt die Prüfung nicht: Festigkeit (Schichtrichtung), Schnapphaken, Filmscharniere, Passungen
  zwischen Teilen und Gewindeeinsätze werden nicht als solche erkannt (Regeln und Rezepte stehen im Skill).
- Wandstärke unter 1,3 mm wird erkannt; Mindestwand um Gewindeeinsätze (1,6–6 mm) nicht.
- Text als Prägung wird nicht gesondert geprüft (zu feine Striche fallen als dünne Wand auf).
- Brücken über gekreuzte Kanäle (eine Fläche, die in keiner Richtung ganz gehalten ist) werden als Auskragung gemeldet.
- Mehrere Körper in einer Form werden gemeinsam gelegt (wie ein Druckauftrag).
- Werte mit „EW“ in `regeln.py` sind Erfahrungswerte; mit Kevins Drucken kalibrieren (Überhang- und Brückentürme,
  Lochkompensation) und dann in `regeln.py` nachtragen.
