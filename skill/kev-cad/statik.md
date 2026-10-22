# Statik in Kev CAD (Stufe 1)

Kev CAD rechnet nach jedem Lauf, ob die Konstruktion hält, kippt oder rutscht, und ob sie unnötig schwer ist
(PLAN-STATIK.md, Strang „Statik Stufe 1“). Das Ergebnis steht im Laufergebnis (eine Zeile „Statik: …“), ausführlich
über `statik` und im Inspektor der App (Abschnitt „Statik“, Farbverlauf grün → gelb → rot, Verformung als Geist).

## Was gerechnet wird

| Stufe | Was | Wofür |
|---|---|---|
| S0, jeder Lauf | Schwerpunkt, Kippen je Kante der Standfläche (Reserve = Standmoment / Kippmoment) und je Richtung (Kippwinkel, Beschleunigung, bei der es kippt), Rutschen über den Reibwert gegen den Boden, lose aufliegende Teile, Schraubenlast grob | Standsicherheit in jedem Szenario |
| S0, jeder Lauf | Bauteil mit Last als Kragträger: Schnitte durch das echte Teil zwischen Einspannung und Lastpunkt, Biegung, Längskraft, Torsion | Halter, Konsolen, Druckteile |
| S1, jeder Lauf | Stabwerk mit PyNite: Rohre und Profile aus dem Lager als Stäbe (Querschnitt aus dem Katalog), Verbinder starr, Gelenke aus den Zwangsbedingungen; Spannung, Durchbiegung, Knicken (Eigenwerte), Auflagerkräfte | Rahmen, Gestelle, Tische, Rigs |
| später | S2 MuJoCo (Dynamik, Ball springt, Rig kippt im Ablauf), S3 Volumen-FEM (Gmsh, scikit-fem) | nicht in Stufe 1 |

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
