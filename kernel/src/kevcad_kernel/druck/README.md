# kevcad_kernel.druck · Druckprüfung für 3D-Druckteile

Prüft eine build123d-Form auf Druckbarkeit mit dem Bambu Lab P2S (FDM, Düse 0,4 mm, Schicht 0,2 mm) und schlägt eine
Ausrichtung vor. Regeln und Quellen: [skill/kev-cad/3d-druck.md](../../../../skill/kev-cad/3d-druck.md).
Nur numpy, build123d und OCP; keine weiteren Abhängigkeiten.

| Datei | Inhalt |
|---|---|
| `regeln.py` | Druckerprofil `P2S`, `MATERIALIEN` (ids wie im Kev-CAD-Katalog), Schwellen, Tabellen (Gewindeeinsätze, Muttern, Kernlöcher, Passungen, Schnapphaken) mit Quellen-Schlüsseln (`QUELLEN`) |
| `netz.py` | vernetzt eine **Kopie** der Form (die Originalform bleibt ohne Dreiecke), Flächeninfos (Ebene, Zylinder mit Achse/Radius/Bogen/hohl), Kanten, Nachbarschaft, Punkt-in-Körper |
| `pruefung.py` | `pruefe_druckteil(...)`, `als_warnungen(...)` |

## API

```python
from kevcad_kernel.druck import pruefe_druckteil, als_warnungen

e = pruefe_druckteil(form, material="petg", ausrichtung=None)   # drucker=P2S
e["ok"]                     # False, sobald ein Fehler dabei ist (z. B. passt nicht in den Bauraum)
e["zusammenfassung"]        # "1 Warnung, 2 Hinweise (PETG, Bambu Lab P2S)"
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
  `harz-standard` wird nur grob geprüft (kein Harzdrucker im Profil).

## Einbindung (macht Kevin bzw. der Kernel-Strang)

### 1. `lager.druckteil(form, name, material, verfahren="3d-druck")`

Nach der Material- und Freigabeprüfung (KATALOG.md) die Prüfung anstoßen und das Ergebnis am Stücklisteneintrag
ablegen:

```python
from kevcad_kernel.druck import als_warnungen, pruefe_druckteil

def druckteil(form, name, material, verfahren="3d-druck", ausrichtung=None, pruefen=True):
    ...                                                   # Katalog: Material frei und druckbar?
    if pruefen:
        try:
            erg = pruefe_druckteil(form, material=mat.id, ausrichtung=ausrichtung)
        except ValueError as exc:                         # z. B. neues druckbares Material ohne Regeln
            _warnung(f"{name}: keine Druckregeln für {mat.id} ({exc})")
        else:
            eintrag["druckpruefung"] = {k: erg[k] for k in ("ok", "zusammenfassung", "ausrichtung", "hinweise",
                                                           "kennzahlen")}
            for zeile in als_warnungen(erg):
                _warnung(f"{name}: {zeile}")              # landet in RUN_END.warnings (Punkt 2)
    ...
```

- Die ids der druckbaren Katalogmaterialien sind identisch mit `MATERIALIEN` (pla, pla-cf, petg, abs, asa,
  pc-filament, pa, pa-cf, tpu-95a, harz-standard). Kommt eins dazu, in `regeln.py` einen Eintrag ergänzen.
- Laufzeit typisch 30–200 ms je Teil, große Teile mit viel Text bis ca. 0,6 s. Bei Auto-Lauf nach jedem Speichern
  zwischenspeichern: Schlüssel = Formschlüssel aus `tessellate.shape_key` (BRep ohne Dreiecke) + Material +
  Ausrichtung. Unveränderte Teile nicht neu prüfen.
- Die Stücklistenzeile kann `kennzahlen.masse_voll_g` nicht als Druckgewicht nehmen (Füllung fehlt); Filamentkosten
  weiter aus Volumen × Dichte × Füllfaktor des K2-Strangs.

### 2. Warnungen in `RUN_END`

`RUN_END.warnings` ist eine Liste von Texten (PROTOCOL.md) – keine Protokolländerung nötig. Je Druckteil die Zeilen aus
`als_warnungen(erg)` mit vorangestelltem Teilnamen anhängen (Fehler und Warnungen, Hinweise nur im Werkzeug);
`MAX_WARNINGS = 30` in `runner.py` beachten (ggf. je Teil auf 3 Zeilen kürzen: `als_warnungen(erg, max_anzahl=3)`).
Der Export sollte durch Druckfehler **nicht** gesperrt werden (das macht nur die Inventar-Regel); ein Fehler wie
„passt nicht in den Bauraum“ ist eine Information für Kevin.

### 3. MCP-Werkzeug `druckpruefung(teil, material=None, ausrichtung=None, zeigen=True)`

Läuft im Elternprozess auf der schon vorhandenen Form: `Scene`-Eintrag (`refs.PartRecord.shape`, deserialisierte BRep,
gleiche Flächennummern wie die Referenzen). Vorschlag für `mcp_tools/tools.py` plus eine `KernelService`-Methode:

```python
@tool("druckpruefung", "Druckprüfung",
      "Prüft ein Teil auf 3D-Druckbarkeit (Bambu P2S): Ausrichtung, Überhänge, Brücken, Wände, Bohrungen, Bauraum …",
      ToolAnnotations(readOnlyHint=True))
async def druckpruefung(teil: str, material: str | None = None, ausrichtung: str | int | None = None,
                        zeigen: bool = True) -> CallToolResult:
    rec = service.part(teil)                                      # PartRecord des letzten Laufs
    mat = material or rec.druckmaterial or rec.material or "petg"  # druckteil-Material bevorzugen
    erg = await tools.work("Druckprüfung", pruefe_druckteil, rec.shape, mat, ausrichtung)
    if zeigen:   # vorhandene Werkzeuge wiederverwenden
        farbe = {"fehler": "red", "warnung": "orange", "hinweis": "yellow"}
        for h in erg["hinweise"]:
            refs = [f"{teil}#f{f}" for f in h["flaechen"][:6]]
            if refs:
                service.highlight(refs, color=farbe[h["schwere"]], label=h["art"])
    return ok_json(kompakt(erg))    # zusammenfassung, ausrichtung (drehung, begruendung), hinweise (text, refs,
                                    # punkt), kennzahlen, druckhinweise
```

- Für Claude die Hinweise mit Referenzen `Teil#f<n>` zurückgeben, damit `focus`, `highlight` und `annotate`
  (Beschriftung am `punkt`) direkt weiterarbeiten können.
- Der Skill sollte darauf verweisen: nach jedem neuen oder geänderten Druckteil `druckpruefung` aufrufen, Fehler und
  Warnungen beheben, Hinweise abwägen, Ausrichtung und Begründung Kevin nennen. SKILL.md bitte um einen Verweis auf
  `3d-druck.md` ergänzen (Abschnitt „Inventar-Regel“ bzw. ein eigener Abschnitt „3D-Druckteile“).

## Wie die Prüfung arbeitet

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
