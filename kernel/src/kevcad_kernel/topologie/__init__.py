"""Topologieoptimierung für Druckteile (PLAN-TOPOLOGIE.md): „Behalte 40 %, entferne den Rest“, entlang der Lastpfade.

Vorbild ist implicit.build: Lager und Lasten setzen, simulieren, Schutzzonen (Bohrungen bleiben massiv), Material
optimieren. Kev CAD nimmt Lager und Lasten aus dem Statikmodell (wie der Festkörper, Stufe 3), rechnet SIMP auf einem
Voxelgitter in Drucklage, macht daraus eine glatte Oberfläche und einen druckbaren Körper und rechnet ihn mit der
Festkörper-FEM und der Druckprüfung nach. Näherung, kein Festigkeitsnachweis.

| Modul | Läuft in | Inhalt |
|---|---|---|
| ``mehrgitter`` | Topo-Prozess | H8-Elemente auf dem Gitter, Galerkin-Mehrgitter elementweise, l1-Jacobi, CG |
| ``simp`` | Topo-Prozess | Dichtefilter, Überhangfilter (Langelaar), OC-Schritt, Iterationen |
| ``raster`` | Topo-Prozess | Druckrahmen, innen/außen über Strahlen, Abstandsfeld, nächste Fläche, Bohrungen |
| ``oberflaeche`` | Topo-Prozess | Marching Cubes (Fälle aus den Würfelflächen erzeugt), Taubin-Glättung, Netzwerte |
| ``nachrechnen`` | Topo-Prozess | Festkörper-FEM vorher und nachher (Bausteine aus ``statik/festkoerper``) |
| ``ergebnis`` | überall | Körper aus dem Netz (B-Rep mit Dreiecksflächen), Dateien im Projekt, Aufrufe aus model.py |
| ``auftrag`` | Rechenprozess | Lastfall wie der Festkörper aus dem Modell des letzten Laufs, Teil als BREP, Nachbarnetze |
| ``dienst`` | Rechenprozess | EXEC-Einstieg der Laufzeit (``auftrag(json)``) |
| ``prozess`` | eigener Prozess | ``python -m kevcad_kernel.topologie.prozess auftrag.json ergebnis.json``: alles oben |
| ``laufzeit`` | Laufzeit | MCP ``topologie_*``, Hintergrund, Fortschritt, Abbruch, TOPO und TOPO_FIELD, Übernehmen als Variante |

Einheiten: mm, N, N/mm². Gmsh (GPL) läuft wie beim Festkörper nur im eigenen Prozess.
"""

from __future__ import annotations

VERSION = 1  # Rechenstand: ändert er sich, gelten gespeicherte Ergebnisse als veraltet

STANDARD = {
    "behalten": 0.4,      # Volumenanteil, der bleibt (geschützte Zonen zählen mit)
    "ueberhang": False,   # Überhangfilter in Druckrichtung (45°, Bambu Lab P1P)
    "fein": False,        # feineres Gitter (etwa 180 000 statt 60 000 Voxel)
    "steg": 6,            # Mindeststegdicke in Linienbreiten (0,42 mm): 6 → 2,52 mm
    "bett": False,        # Bettfläche: geschlossene Bodenhaut in Stegdicke (Standard aus, sonst keine Fenster durch die Grundplatte)
    "bohrungen": True,    # Bohrungen mit Wandring schützen
    "einsaetze": True,    # Gewindeeinsätze mit Mindestwand schützen
    "kontakt": True,      # Last- und Klemmflächen schützen
    "iterationen": 60,    # höchstens so viele SIMP-Schritte
    "lager": "kontakt",   # Lager beim Optimieren: Kontaktflächen zu tragenden Nachbarn (wie die Statik) oder nur die
                          # Bohrungen ("bohrungen": die Schrauben halten, wie im Reel „Fix the bolts“)
}
LINIENBREITE = 0.42

GRENZEN = [
    "Topologieoptimierung ist eine Näherung, kein Festigkeitsnachweis: Voxel-FEM mit linearer Elastizität und kleinen "
    "Verformungen, Eigengewicht beim Optimieren vernachlässigt, Lager fest eingespannt (wie verklebt).",
    "Das Ergebnis wird mit der Festkörper-FEM nachgerechnet (Tetraeder zweiter Ordnung, volle Füllung); gedruckt mit "
    "Wänden und Füllung trägt es weniger, Schichtfugen quer zur Last bleiben die Schwachstelle.",
    "Die Form gilt für die Lastfälle, für die optimiert wurde: andere Lastrichtungen kann sie deutlich schlechter "
    "tragen als das Ausgangsteil.",
]


def einstellungen(**kw) -> dict:
    """Einstellungen mit Vorgaben und festen Typen (gleicher Schlüssel für gleiche Wünsche)."""
    out = dict(STANDARD)
    for k, v in kw.items():
        if v is None or k not in STANDARD:
            continue
        out[k] = v
    out["behalten"] = round(min(0.95, max(0.05, float(out["behalten"]))), 4)
    for k in ("ueberhang", "fein", "bett", "bohrungen", "einsaetze", "kontakt"):
        out[k] = bool(out[k])
    out["steg"] = round(max(2.0, min(40.0, float(out["steg"]))), 2)
    out["iterationen"] = int(max(10, min(200, int(out["iterationen"]))))
    out["lager"] = "bohrungen" if str(out["lager"]).strip().lower() in ("bohrungen", "bohrung", "schrauben") \
        else "kontakt"
    return out


def modell_schluessel(form: str | None, teil: str, szenario: str | None, einst: dict, schutz: list | None = None
                      ) -> str:
    """Schlüssel eines Ergebnisses, wie model.py ihn sieht: Form des Teils (ohne Lage), Szenario, Einstellungen,
    Schutzformen. Der Lastfall selbst steht im Ergebnis (``lastfall``), die Laufzeit vergleicht ihn nach dem Lauf."""
    import hashlib
    import json

    d = {"v": VERSION, "form": form, "teil": teil if not form else None, "szenario": szenario,
         "einst": einstellungen(**einst), "schutz": sorted(schutz or [])}
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:20]


def form_signatur(shape) -> str:
    """Schlüssel einer Form unabhängig von ihrer Lage und davon, ob sie schon vernetzt ist: Volumen, Fläche,
    Schwerpunkt, Trägheit und Anzahl der Flächen und Kanten in den Koordinaten der Form, auf sieben Stellen gerundet.
    (Die Binärform und die Toleranzen ändern sich beim Vernetzen; model.py sieht die Form vorher, die Prüfung danach.)"""
    import hashlib

    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location

    s = getattr(shape, "wrapped", shape).Located(TopLoc_Location())
    v = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, v)
    a = GProp_GProps()
    BRepGProp.SurfaceProperties_s(s, a)
    c = v.CentreOfMass()
    m = v.MatrixOfInertia()

    def zahl(ex_typ) -> int:
        n = 0
        ex = TopExp_Explorer(s, ex_typ)
        while ex.More():
            n += 1
            ex.Next()
        return n

    V = abs(v.Mass())
    L = max(V ** (1.0 / 3.0), 1e-9)
    # auf die Größe bezogen gerundet: Werte nahe null (Schwerpunkt auf der Achse) dürfen nicht am Vorzeichen hängen
    werte = [V / L ** 3, a.Mass() / L ** 2, c.X() / L, c.Y() / L, c.Z() / L,
             *[m.Value(i, j) / (V * L * L) for i in (1, 2, 3) for j in (1, 2, 3)]]
    text = f"{V:.6e};" + ";".join(f"{round(x, 6) + 0.0:.6f}" for x in werte) + \
        f";{zahl(TopAbs_FACE)};{zahl(TopAbs_EDGE)}"
    return hashlib.sha1(text.encode()).hexdigest()[:24]
