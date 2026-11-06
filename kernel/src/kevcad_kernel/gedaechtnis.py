"""Rechengedächtnis des Rechenprozesses (V2-1 „Tempo im Kernel“): teure OCCT-Operationen über Läufe hinweg merken.

Ein unveränderter oder kaum veränderter Modellstand soll fast nichts mehr rechnen, ohne dass model.py anders
geschrieben werden muss. Gemerkt werden zuerst die booleschen Operationen von build123d (``Shape._bool_op`` für
Schnitt, Vereinigung, Schnittmenge, samt dem Aufräumen mit ``ShapeUpgrade_UnifySameDomain``): rund 40 % eines Laufs.

Schlüssel ist der Inhalt der Eingaben: die BRep-Binärform aller Argumente und Werkzeuge in einem Compound (mit Lage,
Orientierung, Toleranzen und gemeinsam benutzten Teilformen), dazu Art und Einstellungen der Operation (Fuzzy-Wert,
Glue, …) und ob aufgeräumt wird. Der Wert ist die BRep-Binärform des Ergebnisses.

Gleiche Ergebnisse, ob gemerkt oder nicht, und in jedem Lauf dieselben:

- Gerechnet wird immer auf einer Kopie der Eingaben (aus derselben Binärform, die den Schlüssel bildet, mit Free-Flag
  und Lage der Originale). OCCT ändert bei Booleans die Eingaben sonst selbst (Kurven auf fremden Flächen, Toleranzen,
  Free-Flag; bei rund der Hälfte der Booleans im Kugelschieber); so bleiben die Eingaben, wie sie sind, und ein später
  gleicher Aufruf hat denselben Schlüssel.
- Zurück kommt immer das Ergebnis aus seiner Binärform gelesen, beim ersten Mal wie bei jedem Treffer: eine frische
  Kopie, nie dasselbe Objekt an zwei Stellen, und eine reine Funktion der Eingaben. Ein Lauf aus dem Gedächtnis
  rechnet deshalb Bit für Bit wie der erste (auch was danach ohne Gedächtnis gerechnet wird, etwa eine Verrundung).
  Typ, Attribute (Name, Farbe, Material) und ``_history`` entstehen wie in build123d.
- Gegenüber OCCT direkt bleibt die Geometrie gleich. Zwei Unterschiede sind möglich, nie an Maßen: Das Ergebnis teilt
  keine Teilformen mit den Eingaben (Identität einer Fläche der Eingabe im Ergebnis), und die Binärform kennt die Art
  einer Transformation nicht (gelesen ist sie gp_CompoundTrsf), sodass eine Koordinate als -0,0 statt 0,0 herauskommen
  kann; außerdem behalten die Eingaben ihren Stand, wo OCCT ihnen Kurven anhängen würde. Gemessen an Kopien aller fünf
  Projekte (05.11.2026, tools/gedaechtnis_nachweis.py): siehe kernel/tools/MESSUNG.md.
- ``_history`` (Select.LAST/NEW, Builder) ist eine ``ErinnerteHistorie``: erst beim ersten Zugriff wird sie auf die
  Teilformen der Eingaben (Stand beim Aufruf) übersetzt; bei einem Treffer wird dafür einmal nachgerechnet. Eine
  Teilform, die unverändert ins Ergebnis ging, gilt dort als „modified“ (für LAST und NEW dasselbe wie „untouched“).
- Ausnahmen von OCCT kommen unverändert durch (nichts wird für einen Fehlschlag gemerkt). Konnte nicht aufgeräumt
  werden (Warnung von build123d), wird das Ergebnis nicht gemerkt.
- Andere Operationen (Section, Splitter) und die Abkürzungen von build123d (leere Werkzeugliste) laufen wie bisher.

Dazu Zahlen je Inhalt einer Form (``inhalt``: Binärform ohne Netz, im Lauf je Form und Lage gemerkt): Volumen
(``compute_volume``), Hüllquader (``bounding_box`` im Standardaufruf; ``AddOptimal`` kostet auf Torus- und
Freiformflächen Millisekunden, beim Kugelschieber 0,2 s je Lauf) und kleinste Abstände (``abstand``, Bedingungen).

V2-1b: Fasen und Verrundungen (``Mixin3D.chamfer``, ``Mixin3D.fillet``) wie die Booleans: Schlüssel aus der Binärform
des Körpers, den Maßen und den Kanten als Nummern in der Reihenfolge von ``TopExp``, gerechnet auf einer Kopie, zurück
kommt das Ergebnis aus seiner Binärform, die Historie entsteht erst bei Bedarf. Scheitert die Operation, wird nichts
gemerkt, die Ausnahme kommt unverändert durch. Kanten, die nicht zum Körper gehören, laufen wie bisher.

``Shape.moved`` macht dasselbe wie build123d, ohne die B-Rep zu kopieren: Das Original kopiert erst die ganze Form
(``__deepcopy__``) und ersetzt die Kopie im nächsten Schritt durch ``self.wrapped.Moved(loc)``; die Kopie sah nie
jemand. Alle übrigen Attribute werden kopiert wie dort (rund 1000 Verschiebungen je Lauf beim Kugelschieber).

Ein: ``installieren()`` im Rechenprozess (worker.py). Aus mit ``KEVCAD_GEDAECHTNIS=0``; Größe mit
``KEVCAD_GEDAECHTNIS_MB`` (Vorgabe 256, LRU nach Bytes). Läuft eine andere Fassung von build123d als die, nach der
``_bool_op`` hier nachgebaut ist, bleibt es aus (Prüfsumme der Quelle).
"""

from __future__ import annotations

import hashlib
import inspect
import io
import os
import sys
import threading
import time
import warnings
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

FORMAT = "kc-gd-1"  # geht in jeden Schlüssel ein
# sha1 von inspect.getsource(...) der nachgebauten build123d-Methoden, Fassung 0.13.0
BOOL_OP_QUELLE = "595079df155b1b475922505d80983a633c2e2d1e"  # Shape._bool_op
QUELLEN = {
    "Shape._bool_op": BOOL_OP_QUELLE,
    "Shape.clean": "b53920bf0d2c902c39887ea733f9c3c6a867830d",
    "Shape.intersect": "d969d374d3228e2a38456a32632acc0c4fc7f9dc",
    "Compound._intersect": "1dc196d4929a9d4182aa5c6dfa1dc4894db88c55",
    "Shape.compute_volume": None,  # nur Vorspann nachgebaut, gerechnet wird mit dem Original
    "Shape.bounding_box": "59a4e73fc96dcf3aadedce4b9a5adcdc50b3cc8a",  # gerechnet wird mit dem Original
    "Shape.moved": "e1a17b2350cb8825d0862022fba7673bc201e378",
    "Mixin3D.chamfer": "5fe2d07935e09241dbb7b20870a44cae4c0b760b",  # gerechnet wird mit dem Original, auf einer Kopie
    "Mixin3D.fillet": "4836e4c7da0b8eb6020ef84526c4a9c1f771e04a",
}
# Nicht ersetzt, aber vorausgesetzt: BoundBox(shape) entfernt das Netz und nimmt AddOptimal ohne Formtoleranz;
# Shape.__deepcopy__ ist in ``_moved`` nachgebaut (ohne die Kopie der B-Rep), _make_3d_result gibt die Art des Ergebnisses
# von chamfer und fillet vor
ABHAENGIG = {"BoundBox.__init__": "ef03fb7a09c9523f31e115ff3a08263ad58547e0",
             "Shape.__deepcopy__": "6eebfb00c3795a574d9aa3bc937e41784f2aa5f2", "Mixin3D._make_3d_result": "93aec1536b872cc5c2293fa405267aa25a06ee51"}


def _an() -> bool:
    return os.environ.get("KEVCAD_GEDAECHTNIS", "1").strip().lower() not in ("0", "aus", "false", "nein", "no")


def _max_bytes() -> int:
    try:
        mb = float(os.environ.get("KEVCAD_GEDAECHTNIS_MB", "256"))
    except ValueError:
        mb = 256.0
    return int(max(1.0, mb) * 1024 * 1024)


# ---------------------------------------------------------------------------------------------------------------------
# Speicher und Statistik
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Eintrag:
    blob: bytes  # BRep-Binärform des Ergebnisses (nach dem Aufräumen)
    rechnen_ms: float  # so lange hat die Operation beim ersten Mal gerechnet
    art: type  # Klasse der Operation (für das Nachrechnen der Historie)
    einstellungen: dict[str, Any]
    n_args: int  # Anzahl Argumente (der Rest sind Werkzeuge)
    aufraeumen: bool


class Speicher:
    """LRU-Speicher Schlüssel → Eintrag, begrenzt über die Größe der Binärformen."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[bytes, Eintrag] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: bytes) -> Eintrag | None:
        with self._lock:
            e = self._items.get(key)
            if e is not None:
                self._items.move_to_end(key)
            return e

    def put(self, key: bytes, eintrag: Eintrag) -> None:
        with self._lock:
            alt = self._items.pop(key, None)
            if alt is not None:
                self._bytes -= len(alt.blob)
            self._items[key] = eintrag
            self._bytes += len(eintrag.blob)
            while self._bytes > self.max_bytes and len(self._items) > 1:
                _, weg = self._items.popitem(last=False)
                self._bytes -= len(weg.blob)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    @property
    def nbytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._items)


SPEICHER = Speicher(_max_bytes())
_installiert = False
_original: dict[str, Any] = {}
_stat_lock = threading.Lock()
_ZAEHLER = ("treffer", "neu", "nicht_gemerkt", "umgangen", "werte_treffer", "werte_neu")
_stat: dict[str, float] = {}


def _stat_reset() -> None:
    with _stat_lock:
        _stat.clear()
        _stat.update({k: 0 for k in _ZAEHLER})
        _stat.update({"gespart_ms": 0.0, "aufwand_ms": 0.0, "rechnen_ms": 0.0})


_stat_reset()


def _zaehle(**werte: float) -> None:
    with _stat_lock:
        for k, v in werte.items():
            _stat[k] = _stat.get(k, 0) + v


def lauf_beginn() -> None:
    """Zähler für den nächsten Lauf zurücksetzen und die Inhaltsschlüssel je Form vergessen (Runner.run)."""
    _stat_reset()
    with _inhalt_lock:
        _INHALT.clear()


def statistik() -> dict[str, Any] | None:
    """Zähler seit ``lauf_beginn`` (für zeiten_ms.gedaechtnis) oder None, wenn das Gedächtnis aus ist.
    ``treffer``: aus dem Speicher, ``neu``: gerechnet und gemerkt, ``nicht_gemerkt``: gerechnet, aber nicht gemerkt
    (Aufräumen gescheitert), ``umgangen``: nicht merkbar (Section, Splitter, Abkürzungen von build123d).
    ``gespart_ms``: Rechenzeit der Treffer beim ersten Mal, ``aufwand_ms``: Schlüssel, Kopien, Lesen und Schreiben der
    Binärformen, ``rechnen_ms``: gerechnete Operationen."""
    if not _installiert:
        return None
    with _stat_lock:
        out = {k: (round(v, 1) if isinstance(v, float) else int(v)) for k, v in _stat.items()}
    out["eintraege"] = len(SPEICHER)
    out["mb"] = round(SPEICHER.nbytes / 1e6, 1)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Binärform
# ---------------------------------------------------------------------------------------------------------------------


def _bin() -> tuple[Any, Any]:
    from OCP.BinTools import BinTools, BinTools_FormatVersion

    return BinTools, BinTools_FormatVersion.BinTools_FormatVersion_CURRENT


def schreiben(topods: Any) -> bytes:
    """BRep-Binärform ohne Dreiecke (wie tessellate.serialize_shape)."""
    bintools, fmt = _bin()
    bio = io.BytesIO()
    bintools.Write_s(topods, bio, False, False, fmt)
    return bio.getvalue()


def lesen(data: bytes) -> Any:
    from OCP.TopoDS import TopoDS_Shape

    bintools, _ = _bin()
    shape = TopoDS_Shape()
    bintools.Read_s(shape, io.BytesIO(data))
    return shape


def _compound(shapes: Iterable[Any]) -> Any:
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    c = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(c)
    for s in shapes:
        b.Add(c, s)
    return c


def _kinder(shape: Any) -> list[Any]:
    from OCP.TopoDS import TopoDS_Iterator

    out = []
    it = TopoDS_Iterator(shape)
    while it.More():
        out.append(it.Value())
        it.Next()
    return out


def _binaerform(eingaben: list[Any]) -> tuple[bytes, list[bool]]:
    """Binärform aller Eingaben in einem Compound (mit gemeinsam benutzten Teilformen) und ihre Free-Flags.

    ``BRep_Builder.Add`` sperrt das TShape der Eingabe (Free wird False, das ändert auch ihre Binärform); die Flags
    kommen danach zurück, die Eingaben bleiben, wie sie waren. Die Kopien bekommen sie in ``_kopien``."""
    frei = [bool(s.Free()) for s in eingaben]
    try:
        return schreiben(_compound(eingaben)), frei
    finally:
        for s, f in zip(eingaben, frei):
            s.Free(f)


def _kopien(vorher: bytes, frei: list[bool], lagen: list[Any] | None = None) -> list[Any]:
    """Die Eingaben als frische Kopie aus ihrer Binärform, mit den Free-Flags der Originale und, wenn gegeben, ihren
    Lagen. Die Binärform kennt die Art einer Transformation nicht (gelesen ist jede gp_CompoundTrsf, eine reine
    Verschiebung rechnet OCCT sonst als gp_Translation): mit den Original-Lagen rechnet OCCT auf der Kopie Bit für Bit
    wie auf den Eingaben (sonst kann eine Koordinate als -0,0 statt 0,0 herauskommen)."""
    kinder = _kinder(lesen(vorher))
    for i, (k, f) in enumerate(zip(kinder, frei)):
        k.Free(f)
        if lagen is not None:
            k.Location(lagen[i])
    return kinder


def _schnappschuss(shapes: Iterable[Any]) -> list[Any]:
    """Kopien der TopoDS-Werte (gleiches TShape, gleiche Lage): spätere move/locate an den Originalen ändern sie nicht."""
    return [s.Located(s.Location()) for s in shapes]


# ---------------------------------------------------------------------------------------------------------------------
# Inhalt je Form (innerhalb eines Laufs) und gemerkte Werte (Volumen, Abstände)
# ---------------------------------------------------------------------------------------------------------------------

_INHALT: dict[int, list[tuple[Any, bytes]]] = {}  # hash(TopoDS) → [(Zeuge, Inhaltsschlüssel)]
_inhalt_lock = threading.Lock()


def _digest(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=20).digest()


def inhalt(topods: Any) -> bytes:
    """Schlüssel aus dem Inhalt einer Form (Binärform), je Form und Lage bis zum nächsten Lauf gemerkt.

    Gleich heißt gleiches TShape, gleiche Lage und Orientierung (``IsEqual``; ``move``/``locate`` ändern die Lage und
    damit den Treffer). Nur für Werte, die an der Geometrie hängen (Volumen, Abstände): Was OCCT einer Form im selben
    Lauf noch anhängt (Kurven auf fremden Flächen, Toleranzen), ändert sie nicht."""
    h = hash(topods)
    with _inhalt_lock:
        for zeuge, schluessel in _INHALT.get(h, ()):
            if zeuge.IsEqual(topods):
                return schluessel
    schluessel = _digest(schreiben(topods))
    _inhalt_merken(topods, schluessel)
    return schluessel


def _inhalt_merken(topods: Any, schluessel: bytes) -> None:
    with _inhalt_lock:
        _INHALT.setdefault(hash(topods), []).append((topods.Located(topods.Location()), schluessel))


class Werte:
    """Gemerkte Zahlen je Inhaltsschlüssel (LRU nach Anzahl)."""

    def __init__(self, maximum: int = 200_000) -> None:
        self.maximum = maximum
        self._items: OrderedDict[tuple, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Any:
        with self._lock:
            v = self._items.get(key)
            if v is not None:
                self._items.move_to_end(key)
            return v

    def put(self, key: tuple, wert: Any) -> None:
        with self._lock:
            self._items[key] = wert
            self._items.move_to_end(key)
            while len(self._items) > self.maximum:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


WERTE = Werte()


def _compute_volume(self: Any) -> float:
    """``Shape.compute_volume`` mit Gedächtnis (Volumen hängt nur an der Geometrie). Wie build123d 0.13.0."""
    from build123d.topology import shape_core as sc
    from OCP.TopAbs import TopAbs_ShapeEnum

    if not self or sc.shapetype(self.wrapped) == TopAbs_ShapeEnum.TopAbs_VERTEX:
        return 0.0
    t0 = time.perf_counter()
    key = ("volumen", inhalt(self.wrapped))
    wert = WERTE.get(key)
    if wert is not None:
        _zaehle(werte_treffer=1, aufwand_ms=(time.perf_counter() - t0) * 1000)
        return wert
    wert = _original["compute_volume"](self)
    WERTE.put(key, wert)
    _zaehle(werte_neu=1)
    return wert


def _bounding_box(self: Any, tolerance: float | None = None, optimal: bool = True) -> Any:
    """``Shape.bounding_box`` mit Gedächtnis für den Standardaufruf (ohne Toleranz, ``optimal=True``), wie build123d
    0.13.0. Der Hüllquader hängt dann nur an Geometrie und Lage: build123d entfernt vorher jedes Netz
    (``BRepTools.Clean``) und rechnet ``AddOptimal`` ohne Formtoleranz. Wie ``huellen.py`` (im Lauf je Form und Lage),
    hier über die Läufe hinweg je Inhalt; der Treffer ist eine genaue Kopie des ``Bnd_Box`` (Ecken, Lücke) und behält den
    Nebeneffekt (Netz entfernen). Auf Torus- und Freiformflächen kostet ``AddOptimal`` Millisekunden, der Schlüssel
    einen Bruchteil davon."""
    topo = getattr(self, "wrapped", None)
    if tolerance is not None or not optimal or topo is None:
        return _original["bounding_box"](self, tolerance, optimal)
    from build123d.geometry import BoundBox
    from OCP.Bnd import Bnd_Box
    from OCP.BRepTools import BRepTools

    t0 = time.perf_counter()
    key = ("huelle", inhalt(topo))
    wert = WERTE.get(key)
    if wert is not None:
        BRepTools.Clean_s(topo)  # wie build123d: ein vorhandenes Netz entfernen
        box = Bnd_Box()
        if wert[0] is not None:
            box.Add(wert[0])  # in einen leeren Bnd_Box: genaue Kopie
        _zaehle(werte_treffer=1, aufwand_ms=(time.perf_counter() - t0) * 1000)
        return BoundBox(box)
    bb = _original["bounding_box"](self, tolerance, optimal)
    kopie = None
    if bb.wrapped is not None:
        kopie = Bnd_Box()
        kopie.Add(bb.wrapped)
    WERTE.put(key, (kopie,))
    _zaehle(werte_neu=1)
    return bb


def abstand(a: Any, b: Any) -> tuple[float, tuple[float, float, float]] | None:
    """Kleinster Abstand zweier TopoDS-Formen (``BRepExtrema_DistShapeShape``): (Wert, Punkt auf ``a``) oder None
    ohne Lösung. Gemerkt je Inhalt beider Formen, wenn das Gedächtnis an ist."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    key = ("abstand", inhalt(a), inhalt(b)) if _installiert else None
    if key is not None:
        wert = WERTE.get(key)
        if wert is not None:
            _zaehle(werte_treffer=1)
            return wert[0]
    d = BRepExtrema_DistShapeShape(a, b)
    if not d.IsDone() or d.NbSolution() == 0:
        wert = (None,)
    else:
        p = d.PointOnShape1(1)
        wert = ((float(d.Value()), (p.X(), p.Y(), p.Z())),)
    if key is not None:
        WERTE.put(key, wert)
        _zaehle(werte_neu=1)
    return wert[0]


# ---------------------------------------------------------------------------------------------------------------------
# Historie (Select.LAST/NEW, Builder)
# ---------------------------------------------------------------------------------------------------------------------


def _historie_klasse() -> type:
    from build123d.topology.history import ShapeHistory

    class ErinnerteHistorie(ShapeHistory):
        """ShapeHistory, deren BRepTools_History erst beim ersten Zugriff auf ``wrapped`` entsteht (Modulbeschreibung).
        ``before``, ``brought`` und ``with_inputs`` verhalten sich wie in build123d. Auch ``merge`` wartet: Der Stand
        der späteren Historie wird beim Aufruf festgehalten (Kopie bzw. ihre noch offenen Schritte) und erst beim
        ersten Zugriff angehängt, in derselben Reihenfolge wie bei build123d. So kostet ``clean()`` (``&``,
        Builder) nichts, solange niemand Select.LAST/NEW fragt."""

        def __init__(self, before: Iterable[Any], brought: Iterable[Any], quelle: Callable[[], Any]) -> None:
            # bewusst ohne ShapeHistory.__init__: das legte gleich ein (leeres) wrapped an
            self._echt = None
            self._quelle = quelle
            self._basis_h = None
            self._spaeter: list[Any] = []  # festgehaltene spätere Historien (merge)
            self.before = list(before)
            self.brought = list(brought)
            self._traces = None

        def _basis(self) -> Any:
            if self._basis_h is None:
                quelle, self._quelle = self._quelle, None
                self._basis_h = quelle() if quelle is not None else _leere_historie()
            return self._basis_h

        def _stand(self, spaeter: list[Any]) -> Any:
            """Neue BRepTools_History: Basis, dann die festgehaltenen späteren Historien."""
            h = _leere_historie()
            h.Merge(self._basis())  # in eine leere: Kopie
            for teil in spaeter:
                h.Merge(_aufloesen(teil))
            return h

        @property
        def wrapped(self) -> Any:  # type: ignore[override]
            if self._echt is None:
                self._echt = self._stand(self._spaeter) if self._spaeter else self._basis()
                self._spaeter = []
            return self._echt

        @wrapped.setter
        def wrapped(self, value: Any) -> None:
            self._echt = value
            self._quelle = None
            self._spaeter = []

        def merge(self, later: Any) -> Any:
            if later is None:
                return self
            if self._echt is not None or later is self:
                return super().merge(later)
            if isinstance(later, ErinnerteHistorie) and later._echt is None:
                self._spaeter.append(("offen", later, list(later._spaeter)))
            else:
                kopie = _leere_historie()
                kopie.Merge(later.wrapped)  # Stand jetzt, wie Merge in build123d
                self._spaeter.append(kopie)
            self._traces = None
            return self

    def _aufloesen(teil: Any) -> Any:
        if isinstance(teil, tuple):
            _, spaeter_h, liste = teil
            return spaeter_h._stand(liste)
        return teil

    return ErinnerteHistorie


_ErinnerteHistorie: type | None = None


def _leere_historie() -> Any:
    from OCP.BRepTools import BRepTools_History

    return BRepTools_History()


def _uebersetzen(h_kopie: Any, kopien: list[Any], eingaben: list[Any], erg_quelle: Any,
                 erg_ziel: Any | None) -> Any:
    """BRepTools_History über ``kopien`` → ``erg_quelle`` in eine über ``eingaben`` → ``erg_ziel`` übersetzen (gleiche
    Struktur, Zuordnung über die Reihenfolge der Teilformen). ``erg_ziel`` None: das Ergebnis bleibt dasselbe."""
    from build123d.topology.history import TRACKED_TYPES, tracked_subshapes
    from build123d.topology.kernel import list_shapes
    from OCP.BRepTools import BRepTools_History
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as IMap
    from OCP.TopExp import TopExp

    alt = tracked_subshapes(kopien)
    neu = tracked_subshapes(eingaben)
    h = BRepTools_History()
    if len(alt) != len(neu):
        return h
    quelle = IMap()
    for t in TRACKED_TYPES:
        TopExp.MapShapes_s(erg_quelle, t, quelle)
    ziel: list[Any] | None = None
    if erg_ziel is not None:
        zm = IMap()
        for t in TRACKED_TYPES:
            TopExp.MapShapes_s(erg_ziel, t, zm)
        if zm.Extent() != quelle.Extent():
            return h
        ziel = [zm.FindKey(i) for i in range(1, zm.Extent() + 1)]

    def abbild(s: Any) -> Any | None:
        if ziel is None:
            return s
        i = quelle.FindIndex(s)
        return ziel[i - 1] if i > 0 else None

    for k, e in zip(alt, neu):
        if not BRepTools_History.IsSupportedType_s(e):
            continue
        if quelle.Contains(k):  # unverändert ins Ergebnis übernommen
            z = abbild(k)
            if z is not None:
                h.AddModified(e, z)
        for m in list_shapes(h_kopie.Modified(k)):
            z = abbild(m)
            if z is not None:
                h.AddModified(e, z)
        for g in list_shapes(h_kopie.Generated(k)):
            z = abbild(g)
            if z is not None and BRepTools_History.IsSupportedType_s(g):
                h.AddGenerated(e, z)
        if h_kopie.IsRemoved(k):
            h.Remove(e)
    return h


# ---------------------------------------------------------------------------------------------------------------------
# Boolesche Operationen
# ---------------------------------------------------------------------------------------------------------------------


def _einstellungen(op: Any) -> dict[str, Any] | None:
    """Einstellungen einer merkbaren Operation (Schnitt, Vereinigung, Schnittmenge), sonst None."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    if type(op) not in (BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Common):
        return None
    try:
        return {"fuzzy": float(op.FuzzyValue()), "glue": str(op.Glue()), "nondestructive": bool(op.NonDestructive()),
                "checkinverted": bool(op.CheckInverted()), "history": bool(op.HasHistory())}
    except Exception:  # noqa: BLE001 - unbekannte Fassung: lieber nicht merken
        return None


def _neue_operation(art: type, einstellungen: dict[str, Any]) -> Any:
    from OCP.BOPAlgo import BOPAlgo_GlueEnum

    op = art()
    if einstellungen["fuzzy"]:
        op.SetFuzzyValue(einstellungen["fuzzy"])
    glue = {str(g): g for g in (BOPAlgo_GlueEnum.BOPAlgo_GlueOff, BOPAlgo_GlueEnum.BOPAlgo_GlueShift,
                                 BOPAlgo_GlueEnum.BOPAlgo_GlueFull)}.get(einstellungen["glue"])
    if glue is not None:
        op.SetGlue(glue)
    op.SetNonDestructive(einstellungen["nondestructive"])
    op.SetCheckInverted(einstellungen["checkinverted"])
    op.SetToFillHistory(einstellungen["history"])
    return op


def _schluessel(einstellungen: dict[str, Any], n_args: int, n_tools: int, aufraeumen: bool, frei: list[bool],
                vorher: bytes) -> bytes:
    kopf = (f"{FORMAT}|bool|{einstellungen}|{n_args}|{n_tools}|{int(aufraeumen)}|"
            f"{''.join('1' if f else '0' for f in frei)}|").encode()
    h = hashlib.blake2b(kopf, digest_size=24)
    h.update(vorher)
    return h.digest()


def _rechnen(op: Any, args: list[Any], tools: list[Any], aufraeumen: bool, stacklevel: int) -> tuple[Any, Any, bool]:
    """Wie build123d: Operation bauen und aufräumen. (Ergebnis, ShapeHistory, aufgeräumt ohne Fehler)."""
    from build123d.topology.history import ShapeHistory
    from build123d.topology.shape_core import downcast
    from OCP.collections import List_TopoDS_Shape
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    arg = List_TopoDS_Shape()
    for s in args:
        arg.Append(s)
    tool = List_TopoDS_Shape()
    for s in tools:
        tool.Append(s)
    op.SetArguments(arg)
    op.SetTools(tool)
    op.SetRunParallel(True)
    op.Build()
    ergebnis = downcast(op.Shape())
    history = ShapeHistory.from_boolean(op, args, tools)
    sauber = True
    if aufraeumen:
        upgrader = ShapeUpgrade_UnifySameDomain(ergebnis, True, True, True)
        upgrader.AllowInternalEdges(False)
        try:  # wie Shape._bool_op: OCP gibt OCCT-Fehlern keine gemeinsame Basisklasse
            upgrader.Build()
            ergebnis = downcast(upgrader.Shape())
            history.merge(ShapeHistory.from_unify(upgrader))
        except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            warnings.warn("Boolean operation unable to clean", stacklevel=stacklevel)
            sauber = False
    return ergebnis, history, sauber


def _boolesch(op: Any, einstellungen: dict[str, Any], before: list[Any], brought: list[Any],
              aufraeumen: bool) -> tuple[Any, Any]:
    """Kern von ``_bool_op`` mit Gedächtnis: (aufgeräumtes Ergebnis, Historie).

    Gerechnet wird auf einer Kopie der Eingaben, zurück kommt immer das Ergebnis aus seiner Binärform gelesen, beim
    ersten Mal wie bei jedem Treffer: So ist das Ergebnis eine reine Funktion der Binärform der Eingaben, und ein Lauf
    rechnet mit gemerkten Ergebnissen Bit für Bit wie beim ersten Mal (auch folgende Operationen, die nicht gemerkt
    werden, etwa Verrundungen)."""
    global _ErinnerteHistorie
    if _ErinnerteHistorie is None:
        _ErinnerteHistorie = _historie_klasse()
    from build123d.topology.shape_core import downcast

    t0 = time.perf_counter()
    eingaben = before + brought
    vorher, frei = _binaerform(eingaben)
    key = _schluessel(einstellungen, len(before), len(brought), aufraeumen, frei, vorher)
    schnapp = _schnappschuss(eingaben)
    eintrag = SPEICHER.get(key)
    if eintrag is not None:
        ergebnis = downcast(lesen(eintrag.blob))  # wie downcast(op.Shape()): Compound, Solid, … statt TopoDS_Shape
        _inhalt_merken(ergebnis, _digest(eintrag.blob))  # Binärform bekannt: Volumen und Abstände ohne Schreiben
        ziel = ergebnis.Located(ergebnis.Location())

        def nachrechnen() -> Any:
            return _historie_nachrechnen(eintrag, vorher, frei, schnapp, ziel)

        _zaehle(treffer=1, gespart_ms=eintrag.rechnen_ms, aufwand_ms=(time.perf_counter() - t0) * 1000)
        return ergebnis, _ErinnerteHistorie(before, brought, nachrechnen)
    kopien = _kopien(vorher, frei, [e.Location() for e in eingaben])
    t1 = time.perf_counter()
    roh, h_kopie, sauber = _rechnen(op, kopien[:len(before)], kopien[len(before):], aufraeumen, stacklevel=4)
    rechnen_ms = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    blob = schreiben(roh)
    if sauber:
        SPEICHER.put(key, Eintrag(blob=blob, rechnen_ms=rechnen_ms, art=type(op), einstellungen=einstellungen,
                                  n_args=len(before), aufraeumen=aufraeumen))
        _zaehle(neu=1)
    else:
        _zaehle(nicht_gemerkt=1)
    ergebnis = downcast(lesen(blob))
    _inhalt_merken(ergebnis, _digest(blob))
    ziel = ergebnis.Located(ergebnis.Location())
    _zaehle(rechnen_ms=rechnen_ms, aufwand_ms=(t1 - t0 + time.perf_counter() - t2) * 1000)

    def uebersetzen() -> Any:
        return _uebersetzen(h_kopie.wrapped, kopien, schnapp, roh, ziel)

    return ergebnis, _ErinnerteHistorie(before, brought, uebersetzen)


def _historie_nachrechnen(eintrag: Eintrag, vorher: bytes, frei: list[bool], schnapp: list[Any], ziel: Any) -> Any:
    """Treffer: die Historie entsteht erst, wenn jemand sie braucht; dafür einmal auf einer Kopie nachrechnen."""
    kopien = _kopien(vorher, frei, [s.Location() for s in schnapp])
    op = _neue_operation(eintrag.art, eintrag.einstellungen)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ergebnis, h_kopie, _ = _rechnen(op, kopien[:eintrag.n_args], kopien[eintrag.n_args:], eintrag.aufraeumen,
                                        stacklevel=2)
    if schreiben(ergebnis) != eintrag.blob:  # sollte nie sein: dann lieber keine Zuordnung als eine falsche
        _zaehle(historie_abweichend=1)
        return _leere_historie()
    return _uebersetzen(h_kopie.wrapped, kopien, schnapp, ergebnis, ziel)


def _bool_op(self: Any, args: Iterable[Any], tools: Iterable[Any], operation: Any) -> Any:
    """Nachbau von build123d 0.13.0 ``Shape._bool_op`` (Prüfsumme BOOL_OP_QUELLE); Unterschied nur im Kern: Rechnen und
    Aufräumen laufen über ``_boolesch``, wenn die Operation merkbar ist."""
    from build123d.topology import shape_core as sc
    from build123d.topology.history import ShapeHistory
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.collections import List_TopoDS_Shape
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopoDS import TopoDS_Compound

    args = list(args)
    tools = list(tools)
    # Find the highest order class from all the inputs Solid > Vertex
    order_dict = {
        type(s): type(s).order
        for s in [self] + args + tools
        if hasattr(type(s), "order")
    }
    highest_order = sorted(order_dict.items(), key=lambda item: item[1])[-1]

    # The base of the operation
    base = args[0] if isinstance(args, (list, tuple)) else args

    arg = List_TopoDS_Shape()
    for obj in args:
        if obj._wrapped is not None:
            arg.Append(obj._wrapped)

    tool = List_TopoDS_Shape()
    for obj in tools:
        if obj._wrapped is not None:
            tool.Append(obj._wrapped)

    # Handle operations with "zero" shapes
    topo_result = None
    if isinstance(operation, BRepAlgoAPI_Cut):
        if tool.IsEmpty():
            if arg.Extent() == 1:
                topo_result = arg.First()
            else:
                topo_result = sc._make_topods_compound_from_shapes(arg)
    elif isinstance(operation, BRepAlgoAPI_Fuse):
        if tool.IsEmpty():
            if arg.Extent() == 1:
                topo_result = arg.First()
            else:
                topo_result = sc._make_topods_compound_from_shapes(arg)
        elif arg.IsEmpty():
            if tool.Extent() == 1:
                topo_result = tool.First()
            else:
                topo_result = sc._make_topods_compound_from_shapes(tool)
    elif isinstance(operation, BRepAlgoAPI_Common):
        if tool.IsEmpty() or arg.IsEmpty():
            return self.__class__()

    before = [o._wrapped for o in args if o._wrapped is not None]
    brought = [o._wrapped for o in tools if o._wrapped is not None]
    history = ShapeHistory(before=before, brought=brought)
    gemerkt = False
    if topo_result is None:
        einstellungen = _einstellungen(operation)
        if einstellungen is not None:
            topo_result, history = _boolesch(operation, einstellungen, before, brought, bool(sc.SkipClean.clean))
            gemerkt = True
        else:
            _zaehle(umgangen=1)
            operation.SetArguments(arg)
            operation.SetTools(tool)

            operation.SetRunParallel(True)
            operation.Build()

            topo_result = sc.downcast(operation.Shape())
            history = ShapeHistory.from_boolean(operation, before, brought)
    else:
        _zaehle(umgangen=1)

    # Clean (beim Gedächtnis schon in _boolesch)
    if sc.SkipClean.clean and not gemerkt:
        upgrader = ShapeUpgrade_UnifySameDomain(topo_result, True, True, True)
        upgrader.AllowInternalEdges(False)
        # see Shape.clean: OCP gives OCCT failures no common base class
        try:
            upgrader.Build()
            topo_result = sc.downcast(upgrader.Shape())
            history.merge(ShapeHistory.from_unify(upgrader))
        except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            warnings.warn("Boolean operation unable to clean", stacklevel=2)

    # Remove unnecessary TopoDS_Compound around single shape
    if isinstance(topo_result, TopoDS_Compound):
        topo_result = sc.unwrap_topods_compound(topo_result, True)

    if isinstance(topo_result, TopoDS_Compound) and highest_order[1] != 4:
        results = sc.ShapeList(
            highest_order[0].cast(s)
            for s in sc.get_top_level_topods_shapes(topo_result)
        )
        for result in results:
            base.copy_attributes_to(result, ["wrapped", "_NodeMixin__children"])
            result._made_by(history)
        result = sc.Shape.make_composite(results, highest_order[1])
        base.copy_attributes_to(result, ["wrapped", "_NodeMixin__children"])
        return result._made_by(history)

    result = highest_order[0].cast(topo_result)
    base.copy_attributes_to(result, ["wrapped", "_NodeMixin__children"])
    return result._made_by(history)


# ---------------------------------------------------------------------------------------------------------------------
# clean (ShapeUpgrade_UnifySameDomain) und Schnittmengen in fester Reihenfolge
# ---------------------------------------------------------------------------------------------------------------------


def _clean(self: Any) -> Any:
    """Nachbau von build123d 0.13.0 ``Shape.clean`` mit Gedächtnis: Schlüssel ist die Binärform der Form, gerechnet
    wird auf einer Kopie, das Ergebnis kommt aus seiner Binärform (wie bei den Booleans); die Historie des Aufräumens
    entsteht erst bei Bedarf. Kann OCCT nicht aufräumen, läuft das Original (Warnung, Form bleibt)."""
    global _ErinnerteHistorie
    if self._wrapped is None:
        return self
    if _ErinnerteHistorie is None:
        _ErinnerteHistorie = _historie_klasse()
    from build123d.topology.shape_core import downcast
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    t0 = time.perf_counter()
    alt = self.wrapped
    vorher = schreiben(alt)
    key = hashlib.blake2b(f"{FORMAT}|clean|".encode(), digest_size=24)
    key.update(vorher)
    key = key.digest()
    schnapp = alt.Located(alt.Location())
    eintrag = SPEICHER.get(key)
    if eintrag is not None:
        ergebnis = downcast(lesen(eintrag.blob))
        _inhalt_merken(ergebnis, _digest(eintrag.blob))
        ziel = ergebnis.Located(ergebnis.Location())

        def nachrechnen() -> Any:
            kopie = _kopien_einzeln(vorher, alt)
            up = ShapeUpgrade_UnifySameDomain(kopie, True, True, True)
            up.AllowInternalEdges(False)
            up.Build()
            roh = downcast(up.Shape())
            if schreiben(roh) != eintrag.blob:
                _zaehle(historie_abweichend=1)
                return _leere_historie()
            return _uebersetzen(up.History(), [kopie], [schnapp], roh, ziel)

        self.wrapped = ergebnis
        unified = _ErinnerteHistorie([], [], nachrechnen)
        self._history = unified if self._history is None else self._history.merge(unified)
        _zaehle(treffer=1, gespart_ms=eintrag.rechnen_ms, aufwand_ms=(time.perf_counter() - t0) * 1000)
        return self
    kopie = _kopien_einzeln(vorher, alt)
    t1 = time.perf_counter()
    up = ShapeUpgrade_UnifySameDomain(kopie, True, True, True)
    up.AllowInternalEdges(False)
    try:
        up.Build()
        roh = downcast(up.Shape())
    except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001 - wie build123d: Original warnt
        _zaehle(nicht_gemerkt=1)
        return _original["clean"](self)
    rechnen_ms = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    blob = schreiben(roh)
    SPEICHER.put(key, Eintrag(blob=blob, rechnen_ms=rechnen_ms, art=ShapeUpgrade_UnifySameDomain, einstellungen={},
                              n_args=1, aufraeumen=True))
    ergebnis = downcast(lesen(blob))
    _inhalt_merken(ergebnis, _digest(blob))
    ziel = ergebnis.Located(ergebnis.Location())
    h_kopie = up.History()

    def uebersetzen() -> Any:
        return _uebersetzen(h_kopie, [kopie], [schnapp], roh, ziel)

    self.wrapped = ergebnis
    unified = _ErinnerteHistorie([], [], uebersetzen)
    self._history = unified if self._history is None else self._history.merge(unified)
    _zaehle(neu=1, rechnen_ms=rechnen_ms, aufwand_ms=(t1 - t0 + time.perf_counter() - t2) * 1000)
    return self


def _kopien_einzeln(vorher: bytes, original: Any) -> Any:
    """Eine Form als frische Kopie aus ihrer Binärform, mit der Lage des Originals (siehe ``_kopien``)."""
    kopie = lesen(vorher)
    kopie.Location(original.Location())
    return kopie


def _intersect(self: Any, *to_intersect: Any, tolerance: float = 1e-6, include_touched: bool = False) -> Any:
    """Nachbau von build123d 0.13.0 ``Shape.intersect``; einziger Unterschied: Doppelte fallen in fester Reihenfolge
    heraus (``dict.fromkeys`` statt ``set``, gleiche Gleichheit). Mit ``set`` hing die Reihenfolge der Teile von
    Speicheradressen ab, jeder Lauf baute ein anders sortiertes Compound, und folgende Booleans hatten jedes Mal einen
    neuen Schlüssel."""
    from build123d.geometry import Axis, Location, Plane, Vector
    from build123d.topology.shape_core import Shape, ShapeList

    if not to_intersect:
        return None

    # Validate input types
    for obj in to_intersect:
        if not isinstance(obj, (Shape, Vector, Location, Axis, Plane)):
            raise ValueError(f"Unsupported type for intersect: {type(obj)}")

    # Chained iteration for AND semantics: c.intersect(s1, s2) = c ∩ s1 ∩ s2
    # Geometry objects (Vector, Location, Axis, Plane) are converted in _intersect
    common_set = ShapeList([self])
    for other in to_intersect:
        next_set: ShapeList = ShapeList()
        for obj in common_set:
            result = obj._intersect(other, tolerance, include_touched)
            if result:
                next_set.extend(result.expand())
        if not next_set:
            return None  # AND semantics: if any step fails, no intersection
        common_set = ShapeList(dict.fromkeys(next_set))  # deduplicate (feste Reihenfolge)
    return common_set if common_set else None


def _compound_intersect(self: Any, other: Any, tolerance: float = 1e-6, include_touched: bool = False) -> Any:
    """Nachbau von build123d 0.13.0 ``Compound._intersect``; Doppelte fallen in fester Reihenfolge heraus (siehe
    ``_intersect``)."""
    from build123d.topology.composite import Compound
    from build123d.topology.shape_core import Shape, ShapeList

    # Convert geometry objects
    other = Shape.as_shape(other)

    # Get self elements: assembly children or OCCT direct children
    if self.children:
        self_elements = [
            c.moved(c.location.inverse() * c.global_location) for c in self.children
        ]
    else:
        self_elements = list(self)
    if not self_elements:
        return None

    results: ShapeList = ShapeList()

    # Distribute over elements (OR semantics for Compound arguments)
    if isinstance(other, Compound):
        if other.children:
            other_elements = [
                c.moved(c.location.inverse() * c.global_location)
                for c in other.children
            ]
        else:
            other_elements = list(other)
    else:
        other_elements = [other]

    for self_elem in self_elements:
        for other_elem in other_elements:
            intersection = self_elem._intersect(
                other_elem, tolerance, include_touched
            )
            if intersection:
                results.extend(intersection)

    # Remove duplicates using Shape's __hash__ (feste Reihenfolge)
    unique = ShapeList(dict.fromkeys(results))

    return unique if unique else None


# ---------------------------------------------------------------------------------------------------------------------
# Verschieben ohne Kopie der B-Rep
# ---------------------------------------------------------------------------------------------------------------------


def _moved(self: Any, loc: Any) -> Any:
    """Nachbau von build123d 0.13.0 ``Shape.moved`` samt ``Shape.__deepcopy__``; einziger Unterschied: keine Kopie der
    B-Rep, die das Original im nächsten Schritt ohnehin durch ``self.wrapped.Moved(loc)`` ersetzt (Modulbeschreibung).
    Alle anderen Attribute (Kinder, Gelenke, Farbe, ...) werden kopiert wie dort."""
    import copy

    from build123d.geometry import Plane
    from build123d.topology.shape_core import downcast

    if isinstance(loc, Plane):
        loc = loc.location
    if self._wrapped is None:
        raise ValueError("Cannot move an empty shape")
    cls = self.__class__
    ergebnis = cls.__new__(cls)
    original = self.wrapped
    memo: dict[int, Any] = {id(self): ergebnis, id(original): original}  # wird unten ersetzt
    for key, value in self.__dict__.items():
        if key in ("topo_path", "_history"):
            setattr(ergebnis, key, value)
        else:
            setattr(ergebnis, key, copy.deepcopy(value, memo))
        if key == "joints":
            for joint in ergebnis.joints.values():
                joint.parent = ergebnis
    ergebnis.wrapped = downcast(original.Moved(loc.wrapped))
    return ergebnis


# ---------------------------------------------------------------------------------------------------------------------
# Fasen und Verrundungen
# ---------------------------------------------------------------------------------------------------------------------


class _Koerper3D:
    """Das, was ``Mixin3D.chamfer`` und ``fillet`` an ``self`` benutzen; ``self`` selbst kann eine Klasse sein, die sich
    nicht aus einer Form bauen lässt (``Box``)."""

    def __init__(self, wrapped: Any, make_3d_result: Callable[[Any], Any]) -> None:
        self.wrapped = wrapped
        self._make_3d_result = make_3d_result


def _nummern(wrapped: Any, art: Any, formen: list[Any]) -> tuple[Any, list[tuple[int, int]]] | None:
    """Teilformen als (Nummer in der Reihenfolge von ``TopExp``, Orientierung) und die Karte dazu; None, wenn eine nicht
    zu ``wrapped`` gehört."""
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as IMap
    from OCP.TopExp import TopExp

    karte = IMap()
    TopExp.MapShapes_s(wrapped, art, karte)
    out = []
    for f in formen:
        i = karte.FindIndex(f)
        if i <= 0:
            return None
        out.append((i, int(f.Orientation())))
    return karte, out


def _kopie_teilform(wrapped: Any, art: Any, nummer: tuple[int, int]) -> Any:
    """Teilform ``nummer`` von ``wrapped`` (wie ``_nummern``), als build123d-Form mit ihrer Orientierung."""
    from build123d.topology.shape_core import Shape, downcast
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as IMap
    from OCP.TopAbs import TopAbs_Orientation
    from OCP.TopExp import TopExp

    karte = IMap()
    TopExp.MapShapes_s(wrapped, art, karte)
    t = karte.FindKey(nummer[0])
    return Shape.cast(downcast(t.Oriented(TopAbs_Orientation(nummer[1]))))


def _kanten_operation(name: str, self: Any, zahlen: tuple, edge_list: Iterable[Any], face: Any,
                      rechnen: Callable[[Any, list[Any], Any], Any]) -> Any:
    """Kern von ``_chamfer`` und ``_fillet``: Schlüssel, Treffer, sonst ``rechnen(körper, kanten, fläche)`` auf einer
    Kopie, Ergebnis aus der Binärform und Historie auf Abruf (wie ``_boolesch``)."""
    global _ErinnerteHistorie
    if _ErinnerteHistorie is None:
        _ErinnerteHistorie = _historie_klasse()
    from build123d.topology.three_d import Mixin3D
    from OCP.TopAbs import TopAbs_ShapeEnum

    t0 = time.perf_counter()
    kanten = list(edge_list)
    alt = self.wrapped
    kanten_art, flaechen_art = TopAbs_ShapeEnum.TopAbs_EDGE, TopAbs_ShapeEnum.TopAbs_FACE
    k = _nummern(alt, kanten_art, [e.wrapped for e in kanten])
    f = _nummern(alt, flaechen_art, [face.wrapped]) if face else (None, [])
    if k is None or f is None:  # gehört nicht zum Körper: so soll es build123d selbst melden
        _zaehle(umgangen=1)
        return rechnen(self, kanten, face)
    nummern, flaeche = k[1], f[1]
    vorher = schreiben(alt)
    frei = bool(alt.Free())
    kopf = f"{FORMAT}|{name}|{zahlen!r}|{nummern!r}|{flaeche!r}|{int(frei)}|".encode()
    h = hashlib.blake2b(kopf, digest_size=24)
    h.update(vorher)
    key = h.digest()
    schnapp = alt.Located(alt.Location())

    def auf_kopie() -> tuple[Any, Any]:
        kopie = _kopien_einzeln(vorher, alt)
        kopie.Free(frei)
        koerper = _Koerper3D(kopie, Mixin3D._make_3d_result)
        return kopie, rechnen(koerper, [_kopie_teilform(kopie, kanten_art, n) for n in nummern],
                              _kopie_teilform(kopie, flaechen_art, flaeche[0]) if flaeche else None)

    eintrag = SPEICHER.get(key)
    if eintrag is not None:
        ergebnis = Mixin3D._make_3d_result(lesen(eintrag.blob))
        _inhalt_merken(ergebnis.wrapped, _digest(eintrag.blob))
        ziel = ergebnis.wrapped.Located(ergebnis.wrapped.Location())

        def nachrechnen() -> Any:
            kopie, roh = auf_kopie()
            if schreiben(roh.wrapped) != eintrag.blob:  # sollte nie sein: dann lieber keine Zuordnung als eine falsche
                _zaehle(historie_abweichend=1)
                return _leere_historie()
            return _uebersetzen(roh._history.wrapped, [kopie], [schnapp], roh.wrapped, ziel)

        _zaehle(treffer=1, gespart_ms=eintrag.rechnen_ms, aufwand_ms=(time.perf_counter() - t0) * 1000)
        return ergebnis._made_by(_ErinnerteHistorie([alt], [], nachrechnen))
    t1 = time.perf_counter()
    kopie, roh = auf_kopie()  # Ausnahmen kommen unverändert durch, gemerkt wird nichts
    rechnen_ms = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    blob = schreiben(roh.wrapped)
    SPEICHER.put(key, Eintrag(blob=blob, rechnen_ms=rechnen_ms, art=type(None), einstellungen={}, n_args=1,
                              aufraeumen=False))
    ergebnis = Mixin3D._make_3d_result(lesen(blob))
    _inhalt_merken(ergebnis.wrapped, _digest(blob))
    ziel = ergebnis.wrapped.Located(ergebnis.wrapped.Location())

    def uebersetzen() -> Any:
        return _uebersetzen(roh._history.wrapped, [kopie], [schnapp], roh.wrapped, ziel)

    _zaehle(neu=1, rechnen_ms=rechnen_ms, aufwand_ms=(t1 - t0 + time.perf_counter() - t2) * 1000)
    return ergebnis._made_by(_ErinnerteHistorie([alt], [], uebersetzen))


def _chamfer(self: Any, length: float, length2: float | None, edge_list: Iterable[Any], face: Any = None) -> Any:
    """``Mixin3D.chamfer`` mit Gedächtnis (Modulbeschreibung)."""

    def rechnen(koerper: Any, kanten: list[Any], flaeche: Any) -> Any:
        return _original["Mixin3D.chamfer"](koerper, length, length2, kanten, flaeche)

    return _kanten_operation("chamfer", self, (float(length), None if length2 is None else float(length2)), edge_list,
                             face, rechnen)


def _fillet(self: Any, radius: float, edge_list: Iterable[Any]) -> Any:
    """``Mixin3D.fillet`` mit Gedächtnis (Modulbeschreibung)."""

    def rechnen(koerper: Any, kanten: list[Any], _flaeche: Any) -> Any:
        return _original["Mixin3D.fillet"](koerper, radius, kanten)

    return _kanten_operation("fillet", self, (float(radius),), edge_list, None, rechnen)


# ---------------------------------------------------------------------------------------------------------------------
# Ein und aus
# ---------------------------------------------------------------------------------------------------------------------


def installieren(log: Callable[[str], None] | None = None) -> bool:
    """Gedächtnis einschalten (im Rechenprozess, einmal beim Start). False, wenn es aus ist oder build123d nicht passt."""
    global _installiert
    if _installiert:
        return True
    if not _an():
        return False
    melden = log or (lambda text: print(text, file=sys.stderr, flush=True))
    try:
        ziele = _ziele()
        for name, (_, _, attr, _) in ziele.items():
            soll = QUELLEN.get(name)
            if soll is None:
                continue
            ist = hashlib.sha1(inspect.getsource(attr).encode()).hexdigest()
            if ist != soll:
                melden(f"[gedaechtnis] aus: {name} dieser build123d-Fassung ist nicht die nachgebaute (Prüfsumme "
                       f"{ist[:12]} statt {soll[:12]})")
                return False
        from build123d.geometry import BoundBox
        from build123d.topology.shape_core import Shape
        from build123d.topology.three_d import Mixin3D

        for name, attr in (("BoundBox.__init__", BoundBox.__init__), ("Shape.__deepcopy__", Shape.__deepcopy__),
                           ("Mixin3D._make_3d_result", Mixin3D._make_3d_result)):
            ist = hashlib.sha1(inspect.getsource(attr).encode()).hexdigest()
            if ist != ABHAENGIG[name]:
                melden(f"[gedaechtnis] aus: {name} dieser build123d-Fassung ist nicht die vorausgesetzte (Prüfsumme "
                       f"{ist[:12]} statt {ABHAENGIG[name][:12]})")
                return False
    except Exception as exc:  # noqa: BLE001
        melden(f"[gedaechtnis] aus: build123d nicht lesbar ({exc!r})")
        return False
    for name, (klasse, attr_name, attr, ersatz) in ziele.items():
        _original[name] = attr
        setattr(klasse, attr_name, ersatz)
    _original["compute_volume"] = _original["Shape.compute_volume"]
    _original["bounding_box"] = _original["Shape.bounding_box"]
    _original["clean"] = _original["Shape.clean"]
    _installiert = True
    _stat_reset()
    return True


def _ziele() -> dict[str, tuple[type, str, Any, Any]]:
    """Name → (Klasse, Attribut, Original, Ersatz) aller Stellen, die das Gedächtnis ersetzt."""
    from build123d.topology import composite, shape_core, three_d

    return {
        "Shape.moved": (shape_core.Shape, "moved", shape_core.Shape.moved, _moved),
        "Mixin3D.chamfer": (three_d.Mixin3D, "chamfer", three_d.Mixin3D.chamfer, _chamfer),
        "Mixin3D.fillet": (three_d.Mixin3D, "fillet", three_d.Mixin3D.fillet, _fillet),
        "Shape._bool_op": (shape_core.Shape, "_bool_op", shape_core.Shape._bool_op, _bool_op),
        "Shape.clean": (shape_core.Shape, "clean", shape_core.Shape.clean, _clean),
        "Shape.intersect": (shape_core.Shape, "intersect", shape_core.Shape.intersect, _intersect),
        "Compound._intersect": (composite.Compound, "_intersect", composite.Compound._intersect, _compound_intersect),
        "Shape.compute_volume": (shape_core.Shape, "compute_volume", shape_core.Shape.compute_volume,
                                 _compute_volume),
        "Shape.bounding_box": (shape_core.Shape, "bounding_box", shape_core.Shape.bounding_box, _bounding_box),
    }


def entfernen() -> None:
    """Wieder ausschalten und leeren (für Tests)."""
    global _installiert
    if not _installiert:
        return
    from build123d.topology import composite, shape_core, three_d

    klassen = {"Shape": shape_core.Shape, "Compound": composite.Compound, "Mixin3D": three_d.Mixin3D}
    for name in [n for n in _original if "." in n]:
        klasse, attr = name.split(".", 1)
        setattr(klassen[klasse], attr, _original.pop(name))
    _original.clear()
    _installiert = False
    SPEICHER.clear()
    WERTE.clear()
    with _inhalt_lock:
        _INHALT.clear()


def aktiv() -> bool:
    return _installiert
