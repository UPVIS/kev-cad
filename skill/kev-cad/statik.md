# Statik in Kev CAD (Stufe 1 bis 3)

Kev CAD rechnet nach jedem Lauf, ob die Konstruktion hält, kippt oder rutscht, und ob sie unnötig schwer ist
(PLAN-STATIK.md, Strang „Statik Stufe 1“). Das Ergebnis steht im Laufergebnis (eine Zeile „Statik: …“), ausführlich
über `statik` und im Inspektor der App (Abschnitt „Statik“, Farbverlauf grün → gelb → rot, Verformung als Geist).

## Was gerechnet wird

| Stufe | Was | Wofür |
|---|---|---|
| S0, jeder Lauf | Schwerpunkt, Kippen je Kante der Standfläche (Reserve = Standmoment / Kippmoment) und je Richtung (Kippwinkel, Beschleunigung, bei der es kippt), Rutschen über den Reibwert gegen den Boden, lose aufliegende Teile, Schraubenlast grob | Standsicherheit in jedem Szenario |
| S0, jeder Lauf | Bauteil mit Last als Kragträger: Schnitte durch das echte Teil zwischen Einspannung und Lastpunkt, Biegung, Längskraft, Torsion | Halter, Konsolen, Druckteile |
| S1, jeder Lauf | Stabwerk mit PyNite: Rohre und Profile aus dem Lager als Stäbe (Querschnitt aus dem Katalog), Verbinder starr, Gelenke aus den Zwangsbedingungen; Spannung, Durchbiegung, Knicken (Eigenwerte), Auflagerkräfte | Rahmen, Gestelle, Tische, Rigs |
| S2, auf Anfrage und für Abläufe aus model.py nach jedem Lauf | Ablauf mit MuJoCo (Starrkörper, Gelenke, Kontakt, Reibung) im eigenen Prozess: Kippen und Abheben, Ladung (Ball) bleibt oder springt heraus, Grenzgeschwindigkeit, Rutschgrenze, Kontaktkräfte | Schieben, Bremsen, Anprall, Fahrt einer Animation |
| S3, nach jedem Lauf im Hintergrund (Teile mit Last) und auf Anfrage | Festkörper-FEM im eigenen Prozess (Gmsh, Tetraeder zweiter Ordnung, scikit-fem, pyamg): Spannung (von Mises, bei Druckteilen die Schichtfuge), Sicherheit, Verformung, Sicherheit in den anderen Drucklagen; Farbverlauf auf dem Netz im Viewer | Druckteile, Halter, Platten, Verbinder statt Kragträger |

## Szenarien in model.py

```python
import kevcad.statik as st   # als Modul: kollidiert nicht mit anderen Namen

st.szenario("Aufstützen 30 kg", beschreibung="Kevin stützt sich vorn auf den Rahmen")
st.last("Kugelschieber/Querstange vorn (Rohr 3)", kg=30)                # senkrecht nach unten, Mitte des Teils
st.last(halter, kraft=(0, 0, -50), punkt=(120, 0, 40))                  # Kraft in N an einem Punkt (mm, Welt)
st.last(["Tisch/Zarge vorn", "Tisch/Zarge hinten"], kg=20)              # auf mehrere Teile verteilt

st.szenario("Bremsen", beschleunigung=(-3, 0, 0))                        # m/s² des ganzen Gegenstands
st.szenario("Schräge", neigung=10, richtung="+y")                        # Boden 10° geneigt, abwärts nach +Y
st.szenario("Anstoßen", stoss=2)                                         # Stoßfaktor auf die Lasten
st.stoss("Regal/Fach 2", masse=5, geschwindigkeit=1, weg=10)             # F = m·v² / (2·s), nach unten

st.untergrund("eiche")                                                   # Boden zum Rutschen (Standard Beton)
st.ziel(sicherheit=2.5, durchbiegung="L/300")                            # eigene Ziele
```

- `last`, `stoss`, `neigung` ohne `szenario=` gehören zum zuletzt angelegten Szenario; Lasten ganz ohne Szenario landen
  in „Nutzlast“. Teile als Name aus `show()`, als Gruppe ("Kugelschieber/") oder als Form.
- **Lastpunkt angeben**, wo er nicht die Mitte des Teils ist (Haken, Konsole): `punkt=(x, y, z)`. Bei Halter-Teilen
  rechnet Kev CAD den Hebel von der Einspannung (Berührung mit dem Gegenstück) bis zu diesem Punkt.
- Von selbst rechnet Kev CAD: „Eigengewicht“; auf Rollen „Bremsen“ (−3 m/s² in X, dynamisch); eine Nutzlast aus einem
  Parameter in kg (`param("nutzlast", 30)`, auch `zuladung`, `traglast`, `fachlast`, `sitzlast`), verteilt auf die
  obersten Teile, wenn model.py keine eigenen Lasten hat.

## Urteile (T5)

- **Ziel**: statisch Sicherheit 2, dynamisch (Beschleunigung, Stoß) 3, Druckteile das Doppelte (4 bzw. 6).
  Durchbiegung: Feld / 200, Kragarm 2 · Länge / 200. Kippen und Rutschen: Reserve 1,5.
- **Ampel**: grün = Ziel erreicht; gelb = Sicherheit zwischen halbem Ziel und Ziel (Kippen/Rutschen 1 bis 1,5;
  Durchbiegung bis doppelt so groß wie zulässig); rot = darunter (bei Ziel 2: hält rechnerisch nicht).
- **Rot und gelb** werden Befunde `statik_*` (Warnung bzw. Hinweis). Sie sperren den Export nicht. Rote Befunde trotzdem
  beheben oder mit Kevin besprechen: stärkeres Profil (Kev CAD schlägt das leichteste ausreichende **aus dem Lager**
  vor), kürzer auskragen, abstützen, Standfläche verbreitern.
- **Druckteile** quer zur Schicht tragen nur `quer_zur_schicht` der Festigkeit (PLA 0,5, PETG 0,4). Der Befund nennt
  „drehen oder verstärken“ mit konkreter `ausrichtung=` für `lager.druckteil` und wie viel höher der Querschnitt werden
  müsste. Lieber drehen (Druckregel: Hauptlast in der Schichtebene, 3d-druck.md) als Material häufen.
- **Überdimensioniert** (Sicherheit ab 10 in allen Lastszenarien, nicht beim reinen Eigengewicht): Hinweis mit dem
  leichtesten Lagerteil desselben Werkstoffs, das reicht, und der Ersparnis in kg und €. Nur ein Vorschlag: Kevin
  entscheidet (Optik, Steifigkeit beim Anfassen, vorhandenes Material).

## Werkzeuge

- `statik()` – alle Szenarien mit Ampel und Kennzahlen; `statik(szenario="…")` – Stäbe, Lager, Kippen je Richtung,
  Rutschen, Schrauben; die App zeigt dann dieses Szenario.
- `szenario_rechnen(name, lasten=[{"teil": "…", "kg": 30}], beschleunigung=…, neigung=…, richtung=…, stoss=…)` – „Hält
  das, wenn …?“ ohne neuen Lauf, in unter einer Sekunde, im Viewer gezeigt. Soll das Szenario bleiben, in model.py
  eintragen.
- Antwort an Kevin immer mit Ampel, Sicherheit, Spannung oder Durchbiegung, Kippreserve und **den Grenzen**: vereinfacht
  (Balken, linear-elastisch, Verbinder starr, Schrauben ohne Vorspannung, Werkstoffwerte Richtwerte), kein Ersatz für
  einen Statiker bei sicherheitsrelevanten Dingen (Personen, Lasten über Kopf, Fahrzeuge).

## Ablauf (Stufe 2, Dynamik)

„Was passiert, wenn ich mit 1 m/s schiebe und abrupt bremse?“ rechnet Kev CAD als Ablauf über der Zeit: MuJoCo mit
Starrkörpern, in einem eigenen Prozess (nie im Rechenprozess von model.py), in ein bis wenigen Sekunden samt Suche nach
den Grenzen.

```python
st.szenario("Bremsen aus 1 m/s", geschwindigkeit=1, bremsen="abrupt")      # rechnet nach jedem Lauf im Hintergrund
st.szenario("Vollbremsung", geschwindigkeit=1.5, bremsen=6)                # Verzögerung in m/s²
st.szenario("Kante", geschwindigkeit=0.5, bremsen="anprall")               # Stillstand in 0,02 s (gegen ein Hindernis)
st.szenario("Fahrt", animation="Fahrt")                                    # Sollbahn aus der Animation „Fahrt“
st.szenario("Rampe", geschwindigkeit=0.5, neigung=5, richtung="+x")        # auf geneigtem Boden
```

- **Szene aus dem Modell**: Teile, die fest verbunden sind (`verbinde` mit Schraube, Klemmung, Steck, Formschluss,
  Kleben; Gelenke mit `bereich` gelten als festgestellt), sind ein Körper. Frei laufen Gelenke ohne `bereich`
  (Laufrolle auf der Querstange) und Räder (Achse aus `anim.rolle(…, achse=…)`, sonst Teile mit Rad/Rolle im Namen
  auf dem Boden). `verbinde(ball, boden, art="aufliegen")` lässt den Ball frei liegen; liegt ein Teil frei auf einem
  anderen und klemmt nichts es ein, ist es Ladung. Masse und Trägheit aus der Geometrie, Reibung aus `reibwerte.json`.
- **Antrieb**: Der schwerste Körper auf Rädern (oder `antrieb=`) folgt der Sollbahn: fährt mit `geschwindigkeit`,
  bremst nach 0,3 s mit `bremsen` (Zahl in m/s², `"abrupt"` = Stillstand in 0,1 s, `"anprall"` = in 0,02 s). Die
  Führung greift am Boden an (wie blockierte Räder, ungünstigster Fall fürs Kippen nach vorn), sonst ist er frei:
  er kann kippen, abheben, ausweichen.
- **Urteile** (Befunde `statik_dyn_*`): `dyn_kippen` mit Kippreserve = Verzögerung, ab der er hinten abhebt (über 2 mm)
  / Verzögerung im Szenario (rot unter 1, gelb unter 1,5), „fällt zurück“ oder „kippt um“ und was aufsetzt;
  `dyn_ladung` (der Ball bleibt, bleibt knapp oder springt heraus, mit der Geschwindigkeit, ab der er herausspringt);
  `dyn_rutschen` (mit blockierten Rädern rutscht er ab μ · g). Dazu die **Handrechnung** a = g · b / h gegen die
  Simulation ohne Ladung bei anhaltender Verzögerung (Plausibilität, typisch innerhalb weniger Prozent).
- **Werkzeuge**: `dynamik(name, geschwindigkeit, bremsen, …)` und `dynamik_grenze(ohne="ball"|"kippen"|"beides",
  bremsen="abrupt")`; `szenario_rechnen(…, dynamik=True)` ist dasselbe. Kevin sieht den Ablauf im Statik-Abschnitt
  („Ablauf zeigen“) und als Animation „Ablauf: <Name>“ in der Zeitleiste (`animation_abspielen`), mit Kontaktkräften als
  Pfeilen.
- **Grenzen, immer dazusagen**: Starrkörper (keine Verformung, kein Federn der Rohre), Stöße ohne Rückprall, Reibung
  nach Coulomb mit einem Wert je Paarung (fehlt die Paarung im Katalog: 0,3 angenommen), Räder ohne Lagerreibung,
  angenommene Massen (Teile ohne Material: 1 g/cm³). Die Grenzgeschwindigkeit hängt stark an Reibwert und Masse der
  Ladung; „abrupt“ ist eine Annahme (0,1 s).

## Festkörper (Stufe 3, FEM)

Teile mit Last, die das Stabwerk als starr nimmt oder S0 als Kragträger nachweist (gedruckte Halter, Konsolen,
Platten, Verbinder zwischen Rohren), rechnet Kev CAD zusätzlich als Volumen: nach jedem Lauf im Hintergrund (nur
Szenarien mit Last, die am stärksten ausgelasteten acht Teile), nach `szenario_rechnen` und `dynamik` für das neue
Szenario, und mit `festigkeit` auf Anfrage. Einige Sekunden je Teil; gleiche Teile und Lasten kommen aus dem
Zwischenspeicher (Bruchteil einer Sekunde). Der Lauf wartet nie darauf.

- **Lager** sind die Kontaktflächen zu den tragenden Nachbarn (dieselben wie beim Kragträger: Wand, Platte, Rohr;
  Schrauben nur, wenn sonst nichts trägt), fest eingespannt. **Lasten**: `st.last` am Teil (mit `punkt=` auf einer
  Fläche um den Punkt verteilt, ohne Punkt gleichmäßig über das Volumen), die Lagerkräfte der Stäbe (über die Bohrung
  bzw. Kontaktfläche zum Stab), bei **Verbindern zwischen Stäben** (im Stabwerk starr, etwa Schlitten oder
  Eckverbinder) Kraft und Moment jedes Stabs am Anschluss, gehalten vom Stab mit der größten Kraft; immer das
  Eigengewicht; mit `festigkeit(…, ablauf=True)` alle Kontaktkräfte auf das Teil im Bild mit der größten Summe aus dem
  Ablauf des Szenarios (Ball an der Fangrolle, Boden), zurückgerechnet in die Ruhelage.
- **Druckteile**: steifer und fester in der Schicht; quer dazu `e_modul_z` und `quer_zur_schicht` aus dem Katalog. Das
  Schichtkriterium (Zug und Schub in der Schichtfuge gegen q · Festigkeit) gilt neben von Mises, Ziel 4 statisch. Das
  Urteil `festkoerper` ersetzt den Kragträger und nennt die **Sicherheit in jeder Drucklage** (`ausrichtung="-z"`,
  `"-y"`, `"-x"`) als FEM-Beleg für „drehen oder verstärken“. Unbekannte Drucklage: überall abgemindert.
- `festigkeit(teil="…", szenario="…")` – Ergebnis je Teil: Ampel, Sicherheit gegen das Ziel, maßgebendes Kriterium,
  Ort der größten Ausnutzung (Welt), Spannung, größte Verschiebung, Kragträger S0 zum Vergleich, Netz und Zeit. Die App
  zeigt das Teil mit **Farbverlauf auf dem Netz** (Bänder der Ausnutzung, grün bis 1, gelb bis 2, darüber rot) und die
  Verformung überhöht als Geist. `fein=True` für Spannungsspitzen an Löchern und Rundungen (langsamer),
  `abbrechen=True` beendet eine laufende Rechnung (in der App: Knopf am Fortschritt).
- **Grenzen, immer dazusagen**: linear-elastisch, kleine Verformungen, Lagerflächen fest eingespannt (wie verklebt;
  am Rand der Einspannung rechnerische Spitzen, sie werden nicht gewertet und stehen als `sicherheit_lagerrand`
  daneben), Schrauben und Gewinde nicht einzeln, Druckteile mit voller Füllung. Kein Ersatz für einen Statiker bei
  sicherheitsrelevanten Dingen.

## Was die Statik braucht

- Materialien mit `mechanik` im Katalog (KATALOG.md, Abschnitt „Mechanik“). Ohne Werte: „nicht nachgewiesen“, nie
  Werte erfinden; fehlt etwas, Kevin fragen und ggf. mit `material_define` vorschlagen (Quelle angeben). Seit
  22.10.2026 haben auch Multiplex, MDF, Spanplatte, Messing, Kupfer und alle Druckmaterialien außer Harz Werte (PA
  vorsichtig nass); Stahl auf Beton haftet mit 0,2.
- Gewindeeinsätze in Druckteilen: den Einsatz als Teil zeigen (Name mit „Gewindeeinsatz“, z. B. „Halter/Gewindeeinsatz
  M3 1“) und in `verbinde(…, art="schraube", mit=[Schraube, Einsatz])` nennen. Dann stellt S0 die Zugkraft je Schraube
  gegen die Auszugkraft aus dem Katalog (`einsatz_auszug`: M3 und M6 in PLA und PETG belegt, M4 und M5 nicht), Ziel 4.
- Verbindungen über `verbinde` und Gelenke (Teile über Bedingungen setzen): Schraube, Klemmung, Steck, Formschluss,
  Kleben gelten als fest, Aufliegen als gelenkig; Dreh- und Schiebegelenke geben die Freiheit frei. Ohne Bedingung
  zählen Berührung (fest) und Spiel (gesteckt, fest).
- Stäbe nur aus `lager.teil(…).verbauen(…)` (Stangenware). Selbst gezeichnete Rohre sind Bauteile, keine Stäbe.
