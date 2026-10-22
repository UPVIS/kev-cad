"""Durchdringung und Kontakt zweier Teile in ihrer Lage.

Vorfilter über die Hüllquader, dann exakt mit OCCT: Schnittmenge (BRepAlgoAPI_Common) mit Volumen, Schwerpunkt als
Ort und Eindringtiefe (kleinste Ausdehnung der Schnittmenge über ihre Hauptachsen und die Weltachsen); ohne
Durchdringung der kleinste Abstand (BRepExtrema). Berühren mit Toleranz ist kein Befund.

Ergebnisse werden je Teilepaar zwischengespeichert, und zwar nach der Form ohne Lage und der **relativen** Lage beider
Teile: Wandert eine ganze Baugruppe, bleiben ihre Paare gültig. Für die Animation (Kollision je Zeitschritt) gibt es
``durchdringung(a, b, lage_a, lage_b)`` mit beliebigen Lagen.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np

from kevcad_kernel import gewinde as _gw
from kevcad_kernel.pruefung.befund import BERUEHR_TOL, BERUEHRT_TOL, TIEFE_MIN, VOLUMEN_MIN
from kevcad_kernel.pruefung.koerper import Koerper, form_schluessel, lage_von


@dataclass
class Paar:
    """Ergebnis für ein Teilepaar (a, b) in Weltkoordinaten."""

    a: str
    b: str
    abstand: float | None  # kleinster Abstand (0 bei Berührung oder Durchdringung); None: weiter weg als die Toleranz
    volumen: float = 0.0  # mm³ der Schnittmenge
    tiefe: float = 0.0  # mm Eindringtiefe (Schätzung)
    ort: np.ndarray | None = None  # Schwerpunkt der Schnittmenge
    achse: np.ndarray | None = None  # Richtung, in die a aus b heraus muss (Einheitsvektor)
    netz: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None  # Schnittkörper: Punkte, Normalen, Dreiecke (Welt)
    rechenzeit_ms: float = 0.0

    @property
    def kontakt(self) -> bool:
        return self.abstand is not None and self.abstand <= BERUEHR_TOL

    @property
    def art(self) -> str | None:
        """„durchdringt“, „beruehrt“ (bis 0,05 mm), „spiel“ (Spielpassung bis 0,5 mm) oder None (weiter weg)."""
        if self.durchdringt:
            return "durchdringt"
        if not self.kontakt:
            return None
        return "beruehrt" if (self.abstand or 0.0) <= BERUEHRT_TOL else "spiel"

    @property
    def durchdringt(self) -> bool:
        return self.volumen > VOLUMEN_MIN and self.tiefe > TIEFE_MIN


@dataclass
class Durchdringung:
    """Ergebnis von ``durchdringung`` (für die Animation und andere Aufrufer)."""

    volumen: float
    tiefe: float
    ort: tuple[float, float, float]
    achse: tuple[float, float, float]  # a muss entlang dieser Richtung um ``tiefe`` heraus
    form: Any = None  # TopoDS_Shape der Schnittmenge (nur mit mit_form=True)


# ---------------------------------------------------------------------------------------------------------------------
# OCCT


def schnittmenge(a: Any, b: Any) -> Any | None:
    """Schnittmenge zweier TopoDS_Shapes oder None (leer oder fehlgeschlagen)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.collections import List_TopoDS_Shape

    for fuzzy in (0.0, 1e-4):
        op = BRepAlgoAPI_Common()
        args, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
        args.Append(a)
        tools.Append(b)
        op.SetArguments(args)
        op.SetTools(tools)
        op.SetRunParallel(True)
        if fuzzy:
            op.SetFuzzyValue(fuzzy)
        try:
            op.Build()
        except Exception:  # noqa: BLE001 - OCCT meldet Fehler als Ausnahme oder über HasErrors
            continue
        if op.IsDone():
            return op.Shape()
    return None


def volumen_und_achsen(shape: Any) -> tuple[float, np.ndarray, list[np.ndarray]]:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    gp = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, gp)
    vol = float(gp.Mass())
    c = gp.CentreOfMass()
    achsen = []
    try:
        pp = gp.PrincipalProperties()
        for v in (pp.FirstAxisOfInertia(), pp.SecondAxisOfInertia(), pp.ThirdAxisOfInertia()):
            a = np.array([v.X(), v.Y(), v.Z()], dtype=np.float64)
            n = np.linalg.norm(a)
            if n > 1e-9:
                achsen.append(a / n)
    except Exception:  # noqa: BLE001
        pass
    return vol, np.array([c.X(), c.Y(), c.Z()]), achsen


def abstand(a: Any, b: Any) -> float | None:
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.Extrema import Extrema_ExtFlag_MIN

    d = BRepExtrema_DistShapeShape()
    d.SetMultiThread(True)
    d.SetFlag(Extrema_ExtFlag_MIN)
    d.LoadS1(a)
    d.LoadS2(b)
    try:
        d.Perform()
    except Exception:  # noqa: BLE001
        return None
    return float(d.Value()) if d.IsDone() else None


def vernetzen(shape: Any, deviation: float = 0.1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Punkte, Normalen, Dreiecke (wie PART_UPSERT) einer TopoDS_Shape."""
    from build123d import Shape

    from kevcad_kernel.tessellate import tessellate_shape

    t = tessellate_shape(Shape.cast(shape), deviation, 0.3, cache=None)
    g = t.geometry
    return (np.asarray(g.positions, dtype=np.float32).reshape(-1, 3),
            np.asarray(g.normals, dtype=np.float32).reshape(-1, 3),
            np.asarray(g.triangles, dtype=np.uint32).reshape(-1, 3))


def _tiefe(punkte: np.ndarray, achsen: list[np.ndarray]) -> tuple[float, np.ndarray]:
    """Kleinste Ausdehnung der Punktwolke über die Kandidatenachsen: (Tiefe, Achse)."""
    kandidaten = list(achsen) + [np.eye(3)[i] for i in range(3)]
    best, best_ax = np.inf, np.array([0.0, 0.0, 1.0])
    for ax in kandidaten:
        w = punkte @ ax
        ext = float(w.max() - w.min())
        if ext < best:
            best, best_ax = ext, ax
    return best, best_ax


# ---------------------------------------------------------------------------------------------------------------------
# Zwischenspeicher


def _rel_schluessel(la: np.ndarray, lb: np.ndarray) -> tuple:
    rel = np.linalg.inv(la) @ lb
    return tuple(np.round(rel[:3, :4].ravel(), 5).tolist())


class PaarCache:
    """LRU-Speicher für Paarergebnisse; Werte liegen im lokalen System von a (Form ohne Lage)."""

    def __init__(self, max_eintraege: int = 50_000) -> None:
        self._items: OrderedDict[tuple, Any] = OrderedDict()
        self._max = max_eintraege
        self._lock = threading.Lock()
        self.treffer = 0
        self.neu = 0

    def get(self, key: tuple) -> Any:
        with self._lock:
            v = self._items.get(key)
            if v is not None:
                self._items.move_to_end(key)
                self.treffer += 1
            return v

    def put(self, key: tuple, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            self.neu += 1
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


def _transform(m: np.ndarray, p: np.ndarray) -> np.ndarray:
    return p @ m[:3, :3].T + m[:3, 3]


def _hull_ueberlappung(a: Koerper, b: Koerper) -> np.ndarray:
    """Ausdehnung der Überlappung der Hüllquader je Achse (negativ: Lücke)."""
    return np.minimum(a.bmax, b.bmax) - np.maximum(a.bmin, b.bmin)


def pruefe_paar(a: Koerper, b: Koerper, cache: PaarCache | None = None, mit_netz: bool = True) -> Paar | None:
    """Durchdringung oder Kontakt von a und b; None, wenn sie weiter als die Berührtoleranz auseinander liegen."""
    import time

    ext = _hull_ueberlappung(a, b)
    if np.any(ext < -BERUEHR_TOL):
        return None
    # Schlüssel: Form a, Form b, Lage von b relativ zu a (Reihenfolge nach Formschlüssel)
    swap = (a.form, a.name) > (b.form, b.name)
    p, q = (b, a) if swap else (a, b)
    key = ("paar", p.form, q.form, _rel_schluessel(p.lage, q.lage))
    hit = cache.get(key) if cache is not None else None
    if hit is None:
        t0 = time.perf_counter()
        hit = _rechne_paar(p, q, ext, mit_netz)
        hit["ms"] = (time.perf_counter() - t0) * 1000
        if cache is not None:
            cache.put(key, hit)
    # zurück in Weltlage (Werte liegen im System von p)
    m = p.lage
    ort = _transform(m, hit["ort"][None, :])[0] if hit.get("ort") is not None else None
    achse = None
    if hit.get("achse") is not None:
        achse = hit["achse"] @ m[:3, :3].T
        if swap:
            achse = -achse
    netz = None
    if hit.get("netz") is not None:
        pts, nrm, tri = hit["netz"]
        netz = (_transform(m, pts.astype(np.float64)).astype(np.float32),
                (nrm.astype(np.float64) @ m[:3, :3].T).astype(np.float32), tri)
    return Paar(a=a.name, b=b.name, abstand=hit["abstand"], volumen=hit["volumen"], tiefe=hit["tiefe"], ort=ort,
                achse=achse, netz=netz, rechenzeit_ms=hit.get("ms", 0.0))


def _nahe_form(k: Koerper, anderer: Koerper) -> Any | None:
    """Form von k für die Paarrechnung mit ``anderer``. Kulisse aus vielen Körpern (Bodenkacheln, Prüftempo
    22.10.2026): nur die Körper, deren Hüllquader dem anderen Teil bis auf die Berührtoleranz nahekommen. Weiter
    entfernte tragen weder zum Schnittvolumen bei noch zu einem Abstand unter der Toleranz; das Ergebnis bleibt
    gleich, die Boolesche Operation wird kleiner. None: kein Körper ist nah genug."""
    if not k.kulisse:
        return k.shape
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Builder
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound

    if k._solids is None:
        ex, liste = TopExp_Explorer(k.shape, TopAbs_SOLID), []
        while ex.More():
            liste.append(ex.Current())
            ex.Next()
        k._solids = liste
    if len(k._solids) < 2:
        return k.shape
    lo, hi = anderer.bmin - 2 * BERUEHR_TOL, anderer.bmax + 2 * BERUEHR_TOL
    nah = []
    for solid in k._solids:
        box = Bnd_Box()
        BRepBndLib.Add_s(solid, box)
        a, b = box.CornerMin(), box.CornerMax()
        if np.all(np.array([a.X(), a.Y(), a.Z()]) <= hi) and np.all(np.array([b.X(), b.Y(), b.Z()]) >= lo):
            nah.append(solid)
    if not nah:
        return None
    if len(nah) == len(k._solids):
        return k.shape
    comp, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(comp)
    for solid in nah:
        builder.Add(comp, solid)
    return comp


def _rechne_paar(p: Koerper, q: Koerper, ext: np.ndarray, mit_netz: bool) -> dict[str, Any]:
    """Rechnet in Weltlage und legt Ort, Achse und Netz im lokalen System von p ab."""
    out: dict[str, Any] = {"abstand": None, "volumen": 0.0, "tiefe": 0.0, "ort": None, "achse": None, "netz": None}
    inv = np.linalg.inv(p.lage)
    p_form, q_form = _nahe_form(p, q), _nahe_form(q, p)
    if p_form is None or q_form is None:
        return out  # Kulisse: kein Teilkörper in Berührweite
    if np.all(ext > TIEFE_MIN):
        common = schnittmenge(p_form, q_form)
        if common is not None:
            vol, zentrum, achsen = volumen_und_achsen(common)
            if vol > VOLUMEN_MIN:
                pts, nrm, tri = vernetzen(common)
                punkte = pts.astype(np.float64) if len(pts) else zentrum[None, :]
                tiefe, ax = _tiefe(punkte, achsen)
                # p muss entlang ax aus q heraus: weg vom Schwerpunkt der Schnittmenge, hin zum eigenen Schwerpunkt
                if float(np.dot(p.zentrum - zentrum, ax)) < 0:
                    ax = -ax
                if tiefe > TIEFE_MIN:
                    out.update(abstand=0.0, volumen=vol, tiefe=tiefe, ort=_transform(inv, zentrum[None, :])[0],
                               achse=ax @ inv[:3, :3].T)
                    if mit_netz and len(pts):
                        out["netz"] = (_transform(inv, pts.astype(np.float64)).astype(np.float32),
                                       (nrm.astype(np.float64) @ inv[:3, :3].T).astype(np.float32), tri)
                    return out
    d = abstand(p_form, q_form)
    out["abstand"] = d if d is not None and d <= BERUEHR_TOL else None
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Gewindeeingriff: die einzige Überlappung, die ohne Erklärung erlaubt ist
#
# Gewindemaße (metrisch und UNC/UNF) stehen in kevcad_kernel/gewinde.py.

STEIGUNG = {d: g.steigung for d, g in _gw.METRISCH.items()}  # Regelgewinde ISO 261 (für ältere Aufrufer)


def gewindetiefe(d: float, steigung: float | None = None) -> float:
    """Radiale Tiefe des Gewindes (Außendurchmesser bis Kerndurchmesser), ISO 68: (d − d3)/2 ≈ 0,6134·P."""
    if steigung:
        return _gw.TIEFE_FAKTOR * steigung
    g = _gw.naechstes(d, float("inf"))
    return g.tiefe if g is not None else _gw.TIEFE_FAKTOR * 0.15 * d


@dataclass
class Gewindeeingriff:
    """Ein erkannter Gewindeeingriff: welches Gewinde, wo die Achse liegt und wer Außen- bzw. Innengewinde hat."""

    text: str
    gewinde: _gw.Gewinde
    achse: np.ndarray  # Einheitsvektor der Gewindeachse (Welt)
    punkt: np.ndarray  # Punkt auf der Achse (Welt)
    aussen: str  # Teil mit dem Außengewinde (Schraube, Gewindestift, Gewindestange)
    innen: str  # Gegenstück (Mutter, Einsatz, Kern- oder Gewindeloch)
    radial: float  # radiale Überdeckung in mm

    def entlang(self, richtung: Any, punkt: Any = None, drehen: bool = False, winkel_grad: float = 1.0,
                versatz: float = 0.1) -> bool:
        """Folgt eine Bewegung dem Gewinde (herein- oder herausdrehen)? Schieben: Richtung parallel zur Achse.
        Drehen: Drehachse (``punkt``, ``richtung``) fällt mit der Gewindeachse zusammen."""
        d = np.asarray(richtung, dtype=np.float64).reshape(3)
        n = float(np.linalg.norm(d))
        if n < 1e-12:
            return False
        d = d / n
        if abs(float(np.dot(d, self.achse))) < np.cos(np.radians(winkel_grad)):
            return False
        if not drehen:
            return True
        if punkt is None:
            return False
        off = np.asarray(punkt, dtype=np.float64).reshape(3) - self.punkt
        quer = off - self.achse * float(np.dot(off, self.achse))
        return float(np.linalg.norm(quer)) <= versatz

    def kurz(self) -> dict[str, Any]:
        return {"gewinde": self.gewinde.name, "achse": [round(float(c), 6) for c in self.achse],
                "punkt": [round(float(c), 4) for c in self.punkt], "aussen": self.aussen, "innen": self.innen}


def _zylinder_mit_gewinde(flaechen: list[dict[str, Any]], groesse: Any) -> list[tuple[dict[str, Any], _gw.Gewinde]]:
    """Zylinderflächen, deren Durchmesser ein Gewinde-Nenndurchmesser ist (± 0,3 mm), mit dem Gewinde dazu. Eine
    Größe aus dem Lagerteil (``groesse``, z. B. "M8-1.25" oder "3/8-16") geht vor."""
    vorgabe = _gw.aus_text(groesse) if groesse else None
    out = []
    for f in flaechen:
        if f.get("t") != "cylinder" or not f.get("r") or not f.get("ax") or f.get("c") is None:
            continue
        d = 2 * float(f["r"])
        g = vorgabe if vorgabe is not None and abs(vorgabe.d - d) <= 0.3 else _gw.naechstes(d)
        if g is not None:
            out.append((f, g))
    return out


def _eingriff(seiten: tuple[tuple[list, Any, str], tuple[list, Any, str]],
              netz_punkte: np.ndarray) -> Gewindeeingriff | None:
    """Kern der Erkennung. ``seiten``: je Teil (Flächen wie in PART_UPSERT, Größe aus dem Lagerteil, Name)."""
    if netz_punkte is None or not len(netz_punkte):
        return None
    pts = np.asarray(netz_punkte, dtype=np.float64).reshape(-1, 3)
    for (flaechen, groesse, name), (_, _, anderer) in (seiten, seiten[::-1]):
        for f, g in _zylinder_mit_gewinde(flaechen, groesse):
            r_aussen = float(f["r"])
            tiefe = g.tiefe
            ax = np.asarray(f["ax"], dtype=np.float64)
            ax = ax / np.linalg.norm(ax)
            c = np.asarray(f["c"], dtype=np.float64)
            rel = pts - c
            t = rel @ ax
            r = np.linalg.norm(rel - np.outer(t, ax), axis=1)
            # ganz im Gewindeband und mindestens die halbe Gewindetiefe tief (Kernloch bzw. Muttergewinde, keine
            # bloße Presspassung eines Rohrs oder Bolzens mit Gewinde-Nenndurchmesser)
            if r.max() <= r_aussen + 0.02 and r_aussen - tiefe - 0.02 <= r.min() <= r_aussen - 0.5 * tiefe:
                kurz_s, kurz_a = name.rsplit("/", 1)[-1], anderer.rsplit("/", 1)[-1]
                text = (f"Gewindeeingriff {g.name}: {kurz_s} in {kurz_a} (radial "
                        f"{r_aussen - r.min():.2f} von {tiefe:.2f} mm Gewindetiefe)")
                return Gewindeeingriff(text, g, ax, c, name, anderer, float(r_aussen - r.min()))
    return None


def gewinde_daten(a: Koerper, b: Koerper, netz_punkte: np.ndarray) -> Gewindeeingriff | None:
    """Ist die Überlappung von a und b ein Gewindeeingriff? Eins der Teile hat einen Zylinder mit Gewinde-
    Nenndurchmesser (metrisch, UNC oder UNF: Schraube, Gewindestift, Gewindestange, Bolzen), und die Schnittmenge
    (``netz_punkte``) liegt ringsum diese Achse ganz im Band zwischen Kern- und Außendurchmesser (nur im
    Gewindebereich, radial nicht tiefer als die Gewindetiefe). Das trifft Schraube in Mutter und Schraube im Kern- oder
    Gewindeloch."""
    return _eingriff(((a.flaechen, a.info.get("groesse"), a.name), (b.flaechen, b.info.get("groesse"), b.name)),
                     netz_punkte)


def gewinde(a: Koerper, b: Koerper, netz_punkte: np.ndarray) -> tuple[str, np.ndarray] | None:
    """Wie ``gewinde_daten``, nur (Beschreibung, Gewindeachse) oder None."""
    g = gewinde_daten(a, b, netz_punkte)
    return (g.text, g.achse) if g else None


def gewindeeingriff(a: Koerper, b: Koerper, netz_punkte: np.ndarray) -> str | None:
    """Wie ``gewinde_daten``, nur die Beschreibung oder None."""
    g = gewinde_daten(a, b, netz_punkte)
    return g.text if g else None


def _form_seite(form: Any, name: str | None, groesse: Any) -> tuple[list[dict[str, Any]], Any, str]:
    """(Zylinderflächen, Größe, Name) einer build123d-Form für die Gewindeerkennung."""
    from build123d import GeomType, Shape

    from kevcad_kernel.tessellate import face_info

    shape = form if isinstance(form, Shape) else Shape.cast(form)
    flaechen = [face_info(f) for f in shape.faces() if f.geom_type == GeomType.CYLINDER]
    if groesse is None:
        lt = getattr(form, "lagerteil", None)
        groesse = (getattr(lt, "masse", None) or {}).get("groesse") if lt is not None else None
    return flaechen, groesse, name or str(getattr(form, "label", "") or "Teil")


def im_gewinde(a: Any, b: Any, *, name_a: str | None = None, name_b: str | None = None, groesse_a: Any = None,
               groesse_b: Any = None) -> Gewindeeingriff | None:
    """Greifen die Formen a und b in ihrer jetzigen Lage im Gewinde ineinander (Schraube in Mutter, Einsatz oder
    Kernloch)? Für Prüfungen, die nur build123d-Formen haben (Bewegungsraum, Montage): rechnet die Schnittmenge
    selbst. Die Größe kommt aus ``groesse_*`` oder dem Lagerteil der Form (``form.lagerteil``). None, wenn sich die
    Formen nicht überlappen oder die Überlappung kein Gewindeeingriff ist."""
    ta, tb = getattr(a, "wrapped", a), getattr(b, "wrapped", b)
    common = schnittmenge(ta, tb)
    if common is None:
        return None
    vol, _, _ = volumen_und_achsen(common)
    if vol <= VOLUMEN_MIN:
        return None
    pts, _, _ = vernetzen(common, 0.05)
    if not len(pts):
        return None
    return _eingriff((_form_seite(a, name_a, groesse_a), _form_seite(b, name_b, groesse_b)), pts)


def entlang_gewinde(eingriff: Gewindeeingriff | None, richtung: Any, punkt: Any = None, drehen: bool = False) -> bool:
    """Hilfe für Bewegungs- und Montageprüfungen: Ein Paar, das schon in der Ausgangslage im Gewinde greift, blockiert
    eine Bewegung entlang bzw. um seine Gewindeachse nicht (die Schraube wird heraus- oder hineingedreht). Quer dazu
    sperrt es weiter. False ohne Eingriff."""
    return eingriff is not None and eingriff.entlang(richtung, punkt, drehen)


# ---------------------------------------------------------------------------------------------------------------------
# Für andere Aufrufer (Animation, Werkzeuge): zwei Formen in beliebiger Lage

_CACHE = PaarCache(20_000)


def _als_topods(shape: Any, lage: Any) -> Any:
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    topo = getattr(shape, "wrapped", shape)
    if lage is None:
        return topo
    if hasattr(lage, "wrapped"):  # build123d Location
        return topo.Moved(lage.wrapped)
    m = np.asarray(lage, dtype=np.float64)
    tr = gp_Trsf()
    tr.SetValues(*[float(x) for x in m[:3, :4].ravel()])
    return topo.Moved(TopLoc_Location(tr))


def durchdringung(a: Any, b: Any, lage_a: Any = None, lage_b: Any = None, *, schluessel_a: str | None = None,
                  schluessel_b: str | None = None, mit_form: bool = False) -> Durchdringung | None:
    """Durchdringen sich a und b in den Lagen ``lage_a``/``lage_b`` (build123d-Location, 4×4-Matrix oder None)?

    ``a``/``b``: build123d-Formen oder TopoDS_Shapes. ``schluessel_*``: feste Schlüssel der Formen (etwa der
    Formschlüssel aus dem Lauf), sonst wird die Form gehasht. Ergebnisse werden nach Form und relativer Lage
    zwischengespeichert, sodass wiederkehrende Stellungen (Zeitschritte einer Animation) nichts kosten. Berühren ist
    keine Durchdringung. None, wenn sie sich nicht durchdringen."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    ta, tb = _als_topods(a, lage_a), _als_topods(b, lage_b)

    def box(t: Any) -> tuple[np.ndarray, np.ndarray]:
        bb = Bnd_Box()
        BRepBndLib.Add_s(t, bb)
        lo, hi = bb.CornerMin(), bb.CornerMax()
        return np.array([lo.X(), lo.Y(), lo.Z()]), np.array([hi.X(), hi.Y(), hi.Z()])

    amin, amax = box(ta)
    bmin, bmax = box(tb)
    ext = np.minimum(amax, bmax) - np.maximum(amin, bmin)
    if np.any(ext <= TIEFE_MIN):
        return None
    la, lb = lage_von(ta), lage_von(tb)
    fa = schluessel_a or form_schluessel(ta)
    fb = schluessel_b or form_schluessel(tb)
    key = ("durch", fa, fb, _rel_schluessel(la, lb))
    hit = None if mit_form else _CACHE.get(key)
    if hit is None:
        hit = {"leer": True}
        common = schnittmenge(ta, tb)
        if common is not None:
            vol, zentrum, achsen = volumen_und_achsen(common)
            if vol > VOLUMEN_MIN:
                pts, _, _ = vernetzen(common, 0.2)
                tiefe, ax = _tiefe(pts.astype(np.float64) if len(pts) else zentrum[None, :], achsen)
                if float(np.dot((amin + amax) / 2 - zentrum, ax)) < 0:
                    ax = -ax
                if tiefe > TIEFE_MIN:
                    inv = np.linalg.inv(la)
                    hit = {"leer": False, "vol": vol, "tiefe": tiefe, "ort": _transform(inv, zentrum[None, :])[0],
                           "achse": ax @ inv[:3, :3].T, "form": common if mit_form else None}
        _CACHE.put(key, {k: v for k, v in hit.items() if k != "form"})
    if hit.get("leer"):
        return None
    ort = _transform(la, hit["ort"][None, :])[0]
    achse = hit["achse"] @ la[:3, :3].T
    return Durchdringung(volumen=float(hit["vol"]), tiefe=float(hit["tiefe"]), ort=tuple(float(x) for x in ort),
                         achse=tuple(float(x) for x in achse), form=hit.get("form"))
