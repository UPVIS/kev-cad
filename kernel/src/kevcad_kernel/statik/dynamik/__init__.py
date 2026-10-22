"""Statik Stufe 2 (PLAN-STATIK.md, Paket T-C): Dynamik mit MuJoCo. „Was passiert, wenn ich mit 1 m/s schiebe und
abrupt bremse?“

| Modul | Läuft in | Inhalt |
|---|---|---|
| ``szene`` | Rechenprozess (auf Anfrage) | Starrkörper, Masse, Trägheit, Gelenke, Kollisionsformen, Kontaktpaare, Reibwerte aus dem Modell des letzten Laufs → Datei |
| ``formen`` | beide | Kugel, Drehteil, Hülle, CoACD mit Zwischenspeicher je Formschlüssel |
| ``mjcf`` | Ablauf-Prozess | MuJoCo-Modell (MJCF) aus der Szene |
| ``ablauf`` | Ablauf-Prozess | Sollbahn, Anfangszustand, Simulation mit Aufzeichnung, Varianten (``mujoco.rollout``), Grenzen suchen |
| ``urteil`` | Ablauf-Prozess | Kennzahlen, Handrechnung, Urteile im Format von ``bewertung.urteil``, Texte |
| ``prozess`` | eigener Prozess | ``python -m kevcad_kernel.statik.dynamik.prozess auftrag.json``: alles oben, Ergebnis als Datei |
| ``laufzeit`` | Laufzeit | MCP ``dynamik``, ``dynamik_grenze``, Hintergrundrechnung nach dem Lauf, STATICS und ANIM_DEF an die App |

Der Ablauf wird nie im Rechenprozess von model.py gerechnet: dort entsteht nur die Szene (Millisekunden), MuJoCo und
CoACD laufen in einem eigenen Prozess (Varianten mit höchstens 4 Fäden). Ehrliche Grenzen (T7): Starrkörper, Reibung nach
Coulomb mit einem Wert je Paarung, keine Verformung, Stöße ohne Rückprall.
"""

GRENZEN_S2 = [
    "Ablauf (S2) mit Starrkörpern: keine Verformung, kein Federn der Rohre, Stöße ohne Rückprall.",
    "Reibung vereinfacht nach Coulomb, ein Wert je Paarung aus dem Katalog (Haftreibung); Räder und Laufrollen ohne "
    "Lagerreibung, kein Rollwiderstand.",
    "Kev CAD führt den Wagen ideal auf der Sollbahn (Angriff am Boden, wie gebremste Räder); schiebt Kevin am Griff, "
    "kippt es später.",
]
