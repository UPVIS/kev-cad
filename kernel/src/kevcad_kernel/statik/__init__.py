"""Statik Stufe 1 (PLAN-STATIK.md, Pakete T-A und T-B): hält es, kippt es, rutscht es, ist es zu schwer?

Aufbau:

| Modul | Inhalt |
|---|---|
| ``werkstoff`` | Werkstoffkennwerte aus dem Katalog (``mechanik``), Reibwerte, Querschnittswerte der Stangenware |
| ``szenario`` | Szenarien aus model.py (``kevcad.statik``) und Standardszenarien je Gegenstand (T3) |
| ``modell`` | Statikmodell aus der Prüfung: Stäbe (Lagerteile), Starrkörper, Verbindungen, Auflager |
| ``s0`` | Stufe S0 bei jedem Lauf: Schwerpunkt, Kippen je Richtung, Rutschen, Schraubenlast grob, Träger |
| ``bauteil`` | Bauteil als Kragträger (Druckteile mit Schichtrichtung): Spannung an Schnitten durch das Teil |
| ``stabwerk`` | Stufe S1: Stabwerk mit PyNite, Lastfälle, Verformung, Spannung, Knicken über Eigenwerte, leichtere Lagerteile |
| ``bewertung`` | Ampel (T5), Texte, ehrliche Grenzen (T7), Befunde im Format der Prüfung |
| ``anbindung`` | Prüfer „statik“ nach jedem Lauf (Rechenprozess) |
| ``dienst`` | Rechenprozess: Szenario auf Anfrage (MCP ``szenario_rechnen``) |
| ``laufzeit`` | Laufzeit: ``KernelService.statik``/``szenario_rechnen``, Nachricht STATICS an die App |
| ``dynamik`` | Stufe 2 (T-C): Ablauf mit MuJoCo im eigenen Prozess, Szene aus dem Modell, Urteile, Animation „Ablauf: …“ |

Einheiten: mm, N, N/mm² (MPa), kg, m/s². Naht für später: S2 (Dynamik mit MuJoCo) und S3 (Festkörper-FEM) setzen auf
``modell.StatikModell`` und ``szenario.Szenario`` auf (siehe ``NAHT`` unten).
"""

from __future__ import annotations

# Naht für S2/S3 (nicht in diesem Strang): Stufen, die ein Szenario rechnen können. Jede Stufe bekommt das Statikmodell
# und die Szenarien und liefert je Szenario Urteile im Format von ``bewertung.urteil``.
NAHT = {
    "S0": "kevcad_kernel.statik.s0",
    "S1": "kevcad_kernel.statik.stabwerk",
    "S2": "kevcad_kernel.statik.dynamik",  # MuJoCo im eigenen Prozess: Ablauf als Animation (Stufe 2)
    "S3": None,  # Gmsh + scikit-fem: Volumen-FEM für Bauteile, von Mises als Farbverlauf
}
