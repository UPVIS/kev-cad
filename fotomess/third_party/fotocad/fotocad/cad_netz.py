"""Ein parametrisches CAD-Modell (build123d) mit beliebigen Parametern bauen und als Dreiecksnetz je Bauteil
zurückgeben, dazu die Ableitung der Eckpunkte nach den Parametern (Netz als lineare Funktion der Maße).

Der Bauer ist eine Funktion bauer(p, **argumente) -> build123d.Compound mit benannten Bauteilen (label), angegeben
als "pfad/zur/datei.py:funktion", damit parallele Prozesse sie laden können.

Gebaut wird wie für den Export (export_gltf, gleiche Feinheit), geladen wie in netz_gl.py. Die Flächen eines
Bauteils kommen nach einer Maßänderung nicht immer in derselben Reihenfolge; sie werden deshalb über Dreieckszahl,
Schwerpunkt und Normale einander zugeordnet, die Eckpunkte innerhalb einer Fläche notfalls über den nächsten
Nachbarn. Ändert ein Parameter die Zerlegung einer Fläche, bleibt sie für diesen Parameter starr (Jacobi.unstetig).

    from fotocad.cad_netz import baue, Jacobi
    bauer = "/pfad/modell.py:modell"                         # modell(p, **argumente) -> Compound
    netz = baue(P, bauer, form="winkel")                     # {Bauteil: [Dreiecke (n, 3, 3) je Fläche]} in mm
    jac = Jacobi(P, bauer, {"form": "winkel"}, ["h_fuss", "l_g"])   # Ableitungen, parallel gebaut
    neu = jac.netz({"h_fuss": +2.0})                          # {Bauteil: Dreiecke (n, 3, 3)} bei geänderten Maßen
"""
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

TMP = Path(os.environ.get("FOTOCAD_TMP", tempfile.gettempdir())) / "fotocad_bau"


def p_mit(p, aenderung):
    """Parameter mit Änderungen; Tupel-Einträge als "name.i" (z. B. "motor.0", "glas.2")."""
    q = dict(p)
    for k, v in aenderung.items():
        if "." in k:
            name, i = k.split(".")
            t = list(q[name]); t[int(i)] = t[int(i)] + v; q[name] = tuple(t)
        else:
            q[k] = q[k] + v
    return q


def wert(p, k):
    if "." in k:
        name, i = k.split(".")
        return p[name][int(i)]
    return p[k]


def lade_bauer(bauer):
    """ "datei.py:funktion" -> Funktion (Datei wird als Modul geladen, ihr Ordner kommt in den Suchpfad)."""
    import importlib.util
    datei, funktion = bauer.rsplit(":", 1)
    datei = Path(datei).resolve()
    if str(datei.parent) not in sys.path:
        sys.path.insert(0, str(datei.parent))
    spec = importlib.util.spec_from_file_location(datei.stem, datei)
    modul = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(datei.stem, modul)
    spec.loader.exec_module(modul)
    return getattr(modul, funktion)


def baue(p, bauer, feinheit=(0.25, 0.15), **argumente):
    """Netz je Bauteil in Welt-Millimetern (z oben). feinheit: linear_deflection (mm), angular_deflection (rad)
    wie beim Export, damit Netz und GLB übereinstimmen."""
    import trimesh
    from build123d import export_gltf
    TMP.mkdir(parents=True, exist_ok=True)
    fn = lade_bauer(bauer) if isinstance(bauer, str) else bauer
    k = fn(p, **argumente)
    fd, pfad = tempfile.mkstemp(suffix=".glb", dir=TMP)
    os.close(fd)
    try:
        export_gltf(k, pfad, binary=True, linear_deflection=feinheit[0], angular_deflection=feinheit[1])
        sc = trimesh.load(pfad, force="scene")
    finally:
        os.unlink(pfad)                               # eigene Zwischendatei
    teile = {}
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry[gname]
        v = trimesh.transform_points(g.vertices, T)
        v = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]]) * 1000.0
        teile.setdefault(node.rsplit("_", 1)[0], []).append(v[g.faces].astype(np.float64))
    return dict(sorted(teile.items()))


def zusammen(netz):
    return {n: np.concatenate(f) for n, f in netz.items()}


def _baue_auftrag(args):
    p, bauer, argumente, aenderung = args
    return baue(p_mit(p, aenderung), bauer, **argumente)


def _flaechen_zuordnen(f0, f1, toleranz):
    """Zuordnung der Flächen f0 -> f1 (Index oder None) über Schwerpunkt und Normale; zuerst nur Flächen mit
    gleicher Dreieckszahl, dann die übrigen (dort hat sich die Zerlegung geändert)."""
    def merkmal(f):
        kreuz = np.cross(f[:, 1] - f[:, 0], f[:, 2] - f[:, 0])
        flaeche = np.linalg.norm(kreuz, axis=1)
        c = (f.mean(1) * flaeche[:, None]).sum(0) / max(flaeche.sum(), 1e-12)     # flächengewichtet
        n = kreuz.sum(0)
        laenge = np.linalg.norm(n)
        n = n / laenge if laenge > 1e-3 * np.abs(f).max() else np.zeros(3)     # geschlossene Flächen: ohne Normale
        return c, n
    m0 = [merkmal(f) for f in f0]
    m1 = [merkmal(f) for f in f1]
    frei = set(range(len(f1)))
    out = [None] * len(f0)
    for gleich in (True, False):
        for i, f in enumerate(f0):
            if out[i] is not None:
                continue
            c, n = m0[i]
            beste, bd = None, toleranz
            for j in frei:
                if gleich and f1[j].shape != f.shape:
                    continue
                dist = np.linalg.norm(m1[j][0] - c) + 50 * (float(np.abs(n).sum() > 0) - float(n @ m1[j][1]))
                if dist < bd:
                    beste, bd = j, dist
            if beste is not None:
                frei.discard(beste)
                out[i] = beste
    return out


def _randpunkte(t):
    """Eckpunkte auf dem Rand einer Flächenzerlegung (Kanten, die nur zu einem Dreieck gehören)."""
    v = t.reshape(-1, 3)
    schl = np.round(v, 4)
    _, ids = np.unique(schl, axis=0, return_inverse=True)
    ids = ids.reshape(-1, 3)
    kanten = np.sort(np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]]), axis=1)
    k, n = np.unique(kanten, axis=0, return_counts=True)
    rand = np.unique(k[n == 1])
    return np.isin(ids.ravel(), rand)


def _ableitung_flaeche(t0, t1, schritt, grenze, grenze_nachbar):
    """Ableitung der Eckpunkte einer Fläche. Gleiche Zerlegung: direkt oder über den nächsten Nachbarn. Andere
    Zerlegung: die Randpunkte beider Zerlegungen über den nächsten Nachbarn zuordnen, alle übrigen Punkte aus
    ihnen mitnehmen (nach Abstand gewichtet), damit innere Hilfspunkte nicht über den Rand wandern."""
    from scipy.spatial import cKDTree
    v0 = t0.reshape(-1, 3)
    v1 = t1.reshape(-1, 3)
    if t1.shape == t0.shape:
        d = t1 - t0
        if np.abs(d).max() <= grenze:
            return d / schritt
        dist, idx = cKDTree(v1).query(v0)
        if dist.max() <= grenze_nachbar:
            return (v1[idx].reshape(t0.shape) - t0) / schritt
    r0, r1 = _randpunkte(t0), _randpunkte(t1)
    if r0.sum() < 3 or r1.sum() < 3:
        return None
    dist, idx = cKDTree(v1[r1]).query(v0[r0])
    treffer = dist <= grenze_nachbar
    if treffer.mean() < 0.6:
        return None
    quelle = v0[r0][treffer]
    d_quelle = v1[r1][idx[treffer]] - quelle
    k = min(4, len(quelle))
    dd, ii = cKDTree(quelle).query(v0, k=k)
    dd, ii = dd.reshape(len(v0), k), ii.reshape(len(v0), k)
    gew = 1.0 / np.maximum(dd, 1e-4) ** 2
    d = (gew[:, :, None] * d_quelle[ii]).sum(1) / gew.sum(1, keepdims=True)
    return d.reshape(t0.shape) / schritt


class Jacobi:
    def __init__(self, p, bauer, argumente, parameter, schritt=0.1, prozesse=4, basis=None):
        self.p, self.bauer, self.argumente = dict(p), bauer, dict(argumente)
        self.parameter = list(parameter)
        self.schritt = schritt
        auftraege = ([] if basis else [(self.p, bauer, self.argumente, {})]) + \
            [(self.p, bauer, self.argumente, {k: schritt}) for k in self.parameter]
        with ProcessPoolExecutor(max_workers=prozesse) as ex:
            netze = list(ex.map(_baue_auftrag, auftraege))
        self.basis = basis or netze.pop(0)
        self.ableitung = {}          # (Parameter, Bauteil) -> d Dreiecke / d Parameter, Flächen aneinandergereiht
        self.unstetig = []           # (Parameter, Bauteil, Zahl der starren Flächen)
        for k, n in zip(self.parameter, netze):
            for teil, f0 in self.basis.items():
                f1 = n.get(teil, [])
                zu = _flaechen_zuordnen(f0, f1, toleranz=1.5)
                teile, starr = [], 0
                for i, j in enumerate(zu):
                    d = None if j is None else _ableitung_flaeche(f0[i], f1[j], schritt, 4 * schritt, 4 * schritt)
                    if d is None:
                        starr += 1
                        d = np.zeros_like(f0[i])
                    teile.append(d)
                if starr:
                    self.unstetig.append((k, teil, starr))
                d = np.concatenate(teile)
                if np.abs(d).max() > 1e-6:
                    self.ableitung[(k, teil)] = d.astype(np.float32)

    def speichere(self, pfad):
        import pickle
        tmp = Path(str(pfad) + ".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(dict(p=self.p, bauer=self.bauer, argumente=self.argumente, parameter=self.parameter,
                             schritt=self.schritt, basis=self.basis, ableitung=self.ableitung, unstetig=self.unstetig), f,
                        protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(pfad)

    @classmethod
    def lade(cls, pfad):
        import pickle
        with open(pfad, "rb") as f:
            z = pickle.load(f)
        j = cls.__new__(cls)
        j.__dict__.update(z)
        return j

    def netz(self, aenderung):
        out = {}
        for teil, f0 in self.basis.items():
            t = np.concatenate(f0)
            for k, v in aenderung.items():
                d = self.ableitung.get((k, teil))
                if d is not None and v:
                    t = t + v * d
            out[teil] = t.astype(np.float32)
        return out
