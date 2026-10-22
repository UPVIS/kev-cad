"""Bewegungsraum (Range of Motion, PLAN-BEDINGUNGEN.md B8): jedes Gelenk mit Bereich über den ganzen Weg prüfen.

Je Gelenk (``drehgelenk``, ``schiebegelenk``, ``zylindergelenk`` mit ``bereich``) und je Eintrag in
``<projekt>/bewegungen.json`` (Format wie ``kernel/tools/check_motion.py``) wird das bewegte Teil samt mitbewegten
Teilen in Schritten über den Bereich gefahren und gegen alle übrigen Teile geprüft: Hüllquader-Vorfilter, dann exaktes
Schnittvolumen. Berühren ist erlaubt (unter ``min_volumen`` mm³ oder dünner als ``toleranz`` mm). Bedienteile prüfen
zusätzlich den Freiraum am Griff (Finger, Hand, Werkzeug): Hebel und Klappen an ihrem Griffpunkt über den ganzen Weg,
Teile, die um ihre eigene Achse gedreht werden (Flügelmutter, Drehknopf, ``bedienung="fluegel"``), im Griffraum: ein
Zylinderring um die Drehachse über der Auflage, so weit wie die Flügelspitze plus Freiraum.

Paare, die schon in der Ausgangslage im Gewinde greifen (Schraube in Mutter, Einsatz oder Kernloch), blockieren eine
Bewegung entlang bzw. um ihre Gewindeachse nicht: die Schraube wird heraus- oder hineingedreht (Helfer
``pruefung.kollision.im_gewinde`` und ``entlang_gewinde``). Quer zur Achse sperrt das Gewinde weiter.

Die Kollisionsfunktion ist dieselbe wie bei der Animation: ``kevcad_kernel.anim_kollision.pruefe_kollisionen``, sobald
der Strang Animation zusammengeführt ist; bis dahin eine Fassung mit gleicher Schnittstelle (``_pruefe_kollisionen``).
Zwischenspeicher auf zwei Ebenen, beide über Läufe hinweg im Rechenprozess:

- je Weg (Gelenk): Schlüssel aus Geometrieschlüssel und Lage aller beteiligten Teile, Achse, Bereich, Schritte,
  Freiraum und Bedienung. Ein unveränderter Stand kostet nur das Nachschlagen; ändert sich ein Teil, rechnet nur der
  Weg neu, an dem es beteiligt ist.
- je Teilepaar und relativer Lage (``_PAAR_CACHE``): auch was ein abgebrochener (Zeitlimit) oder geänderter Weg schon
  gerechnet hat, bleibt erhalten; der nächste Lauf setzt dort fort.
"""

from __future__ import annotations

import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .arten import Drehgelenk, Gelenk, Schiebegelenk, Zylindergelenk
from .geometrie import Bezug, drehung_um_gerade, einheit, verschiebung
from .text import grad, mm, vektor

TOLERANZ = 0.05  # mm: dünnere Schnittkörper gelten als Berührung (wie Animation)
MIN_VOLUMEN = 0.5  # mm³: kleinere Schnittvolumen gelten als Berührung (wie Animation)
GRIFF_INNEN = 0.5  # Griffraum beginnt bei diesem Anteil des Spitzenradius (innen: Nabe, Bolzen, Gewindestift)
AUFLAGE_TOL = 0.3  # mm: so nah gilt ein festes Teil als Auflage des bedienten Teils

try:  # gemeinsame Kollisionsfunktion mit der Animation (Strang ANI)
    from kevcad_kernel.anim_kollision import pruefe_kollisionen  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - bis zum Zusammenführen
    pruefe_kollisionen = None  # type: ignore[assignment]


class _LRU(OrderedDict):
    """Kleiner LRU-Speicher mit ``get``/``[]=`` (für die Kollisionsfunktion)."""

    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum

    def get(self, key: Any, default: Any = None) -> Any:
        if key in self:
            self.move_to_end(key)
            return self[key]
        return default

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.maximum:
            self.popitem(last=False)


_CACHE: _LRU = _LRU(200)  # je Weg: fertiges Ergebnis
_PAAR_CACHE: _LRU = _LRU(100_000)  # je Teilepaar und relativer Lage: (Volumen, min, max) oder None
_GEWINDE_CACHE: _LRU = _LRU(2000)  # je Geometriestand: Gewindeeingriff eines Paars in Ruhelage, Drehgriff ja/nein


@dataclass
class _Kollision:
    zeit: float
    bild: int
    teile: tuple[str, str]
    volumen: float
    tiefe: float
    ort: tuple[float, float, float]


_BOXEN: dict[int, tuple[np.ndarray, np.ndarray]] = {}  # Hüllquader der gezeigten Formen (aus der Vernetzung)


def _box(form: Any) -> tuple[np.ndarray, np.ndarray]:
    hit = _BOXEN.get(id(form))
    if hit is not None:
        return hit
    bb = form.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


def _ecken(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return np.array([[(lo, hi)[i & 1][0], (lo, hi)[(i >> 1) & 1][1], (lo, hi)[(i >> 2) & 1][2]] for i in range(8)])


def _gemeinsam(a: Any, b_moved: Any) -> tuple[float, np.ndarray, np.ndarray] | None:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps

    op = BRepAlgoAPI_Common(a.wrapped if hasattr(a, "wrapped") else a, b_moved)
    if not op.IsDone():
        return None
    res = op.Shape()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(res, props)
    vol = abs(props.Mass())
    if vol <= 0:
        return 0.0, np.zeros(3), np.zeros(3)
    box = Bnd_Box()
    BRepBndLib.Add_s(res, box)
    if box.IsVoid():
        return vol, np.zeros(3), np.zeros(3)
    lo, hi = box.CornerMin(), box.CornerMax()
    return vol, np.array([lo.X(), lo.Y(), lo.Z()]), np.array([hi.X(), hi.Y(), hi.Z()])


def _pruefe_kollisionen(formen, lagen, zeiten, *, bilder=None, paare=None, huellen=None, kugeln=None,  # noqa: ANN001
                        toleranz=TOLERANZ, min_volumen=MIN_VOLUMEN, sichtbar=None, zeitlimit_s=None, cache=None,
                        schluessel=None, abbrechen=None):
    """Gleiche Schnittstelle wie ``anim_kollision.pruefe_kollisionen`` (nur die hier gebrauchten Teile)."""
    from OCP.TopLoc import TopLoc_Location

    from .geometrie import matrix_trsf

    t0 = time.perf_counter()
    zeiten = np.asarray(zeiten, dtype=float)
    frames = list(range(len(zeiten))) if bilder is None else sorted(set(bilder))
    stats = {"paare": 0, "bilder": len(frames), "kandidaten": 0, "exakt": 0, "abgebrochen": False}
    befunde: list[_Kollision] = []
    boxes = {n: _box(f) for n, f in formen.items()}
    eye = np.repeat(np.eye(4)[None], len(zeiten), axis=0)
    for a, b in list(paare or []):
        stats["paare"] += 1
        ta = lagen[a] if a in lagen else eye
        tb = lagen[b] if b in lagen else eye
        for k in frames:
            if zeitlimit_s is not None and time.perf_counter() - t0 > zeitlimit_s:
                stats["abgebrochen"] = True
                break
            rel = np.linalg.solve(ta[k], tb[k])  # Lage von b im Ruhesystem von a
            pc = _ecken(*boxes[b]) @ rel[:3, :3].T + rel[:3, 3]
            lo, hi = boxes[a]
            if np.any(pc.max(axis=0) <= lo + toleranz) or np.any(pc.min(axis=0) >= hi - toleranz):
                continue
            stats["kandidaten"] += 1
            sk = schluessel or {}
            key = (sk.get(a, a), sk.get(b, b), tuple(np.round(rel[:3, :].ravel(), 4)))
            if cache is not None and key in cache:
                res = cache.get(key)
            else:
                if abbrechen is not None:
                    abbrechen()
                stats["exakt"] += 1
                wb = formen[b].wrapped.Moved(TopLoc_Location(matrix_trsf(rel)))
                res = _gemeinsam(formen[a], wb)
                if cache is not None:
                    cache[key] = res
            if res is None:
                continue
            vol, clo, chi = res
            if vol < min_volumen or float(np.min(chi - clo)) < toleranz:
                continue
            mitte = ta[k][:3, :3] @ ((clo + chi) / 2) + ta[k][:3, 3]
            befunde.append(_Kollision(float(zeiten[k]), k, (a, b), float(vol), float(np.min(chi - clo)),
                                      tuple(float(c) for c in mitte)))
        if stats["abgebrochen"]:
            break
    stats["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return befunde, stats


def _kollisionsfunktion():  # noqa: ANN202
    return pruefe_kollisionen or _pruefe_kollisionen


@dataclass
class Bewegung:
    """Ein Weg, der geprüft wird (aus einem Gelenk oder aus bewegungen.json)."""

    name: str
    art: str  # drehen | schieben
    teile: list[str]
    punkt: np.ndarray
    richtung: np.ndarray
    von: float
    bis: float
    ist: float = 0.0
    schritte: int = 0
    ignorieren: list[str] = field(default_factory=list)
    freiraum: float | None = None
    bedienung: str | None = None
    griff: np.ndarray | None = None
    quelle: str = ""
    zeile: int | None = None
    bedingung: str | None = None
    achse_teil: str | None = None  # Teil des festen Bezugs (Welle, Gewindestift, Gehäuse)

    def lage(self, wert: float) -> np.ndarray:
        if self.art == "drehen":
            return drehung_um_gerade(self.punkt, self.richtung, wert - self.ist)
        return verschiebung(self.richtung * (wert - self.ist))

    def werte(self) -> list[float]:
        n = self.schritte or (max(4, min(36, math.ceil(abs(self.bis - self.von) / 10)))
                              if self.art == "drehen" else 20)
        lo, hi = min(self.von, self.bis), max(self.von, self.bis)  # bewegungen.json erlaubt auch von > bis
        vals = [lo + (hi - lo) * k / n for k in range(n + 1)]
        if lo <= self.ist <= hi and not any(abs(v - self.ist) < 1e-9 for v in vals):
            vals.append(self.ist)
            vals.sort()
        return vals


def _mitglied(name: str, praefixe: list[str]) -> bool:
    return any(name == p or name.startswith(p.rstrip("/") + "/") for p in praefixe)


def _name_von(obj: Any, formen: dict[str, Any], index: Any = None) -> str | None:
    if isinstance(obj, str):
        return obj
    from .geometrie import als_bezug

    try:
        b = als_bezug(obj)
    except Exception:  # noqa: BLE001
        return None
    if b.quelle is None:
        return None
    for name, form in formen.items():
        w = getattr(form, "wrapped", None)
        if w is not None and w.IsPartner(b.quelle):
            return name
    return None


def aus_gelenk(g: Gelenk, A: Bezug, B: Bezug, formen: dict[str, Any]) -> Bewegung | None:
    if g.bereich is None or not g.weg_pruefen or not A.teilname or B.d is None:
        return None
    if isinstance(g, (Drehgelenk, Zylindergelenk)):
        art, ist = "drehen", g.winkel
    elif isinstance(g, Schiebegelenk):
        art, ist = "schieben", g.weg
    else:
        return None
    teile = [A.teilname] + [n for n in (_name_von(m, formen) for m in g.mitbewegt) if n]
    ignorieren = [n for n in (_name_von(m, formen) for m in g.ignorieren) if n]
    griff = None
    if g.griff is not None:
        from .geometrie import als_bezug, v3

        try:
            griff = v3(g.griff) if isinstance(g.griff, (tuple, list, np.ndarray)) else als_bezug(g.griff).p
        except Exception:  # noqa: BLE001
            griff = None
    return Bewegung(name=f"{g.art} {A.teilname}", art=art, teile=teile, punkt=B.p.copy(), richtung=B.d.copy(),
                    von=g.bereich[0], bis=g.bereich[1], ist=ist, schritte=g.schritte or 0, ignorieren=ignorieren,
                    freiraum=g.freiraum, bedienung=g.bedienung, griff=griff, quelle="gelenk", zeile=g.zeile,
                    bedingung=g.id, achse_teil=B.teilname)


def aus_json(projekt: Path, formen: dict[str, Any]) -> tuple[list[Bewegung], list[str]]:
    """Einträge aus ``<projekt>/bewegungen.json`` (Format von check_motion.py)."""
    datei = projekt / "bewegungen.json"
    if not datei.is_file():
        return [], []
    try:
        specs = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], [f"bewegungen.json nicht lesbar: {exc}"]
    out, warn = [], []
    for spec in specs if isinstance(specs, list) else []:
        teile = spec.get("teile") or []
        teile = teile if isinstance(teile, list) else [teile]
        bewegt = [n for n in formen if _mitglied(n, teile)]
        if not bewegt:
            warn.append(f"bewegungen.json: keine Teile zu {teile}")
            continue
        art = spec.get("art", "drehen")
        richtung = einheit(np.array([float(v) for v in (spec.get("richtung") or [0, 0, 1])]))
        if spec.get("punkt") is not None:
            punkt = np.array([float(v) for v in spec["punkt"]])
        elif spec.get("achse_von") in formen:
            lo, hi = _box(formen[spec["achse_von"]])
            punkt = (lo + hi) / 2
            k = int(np.argmax(hi - lo))
            richtung = np.eye(3)[k]
        elif spec.get("punkt_von") in formen:
            lo, hi = _box(formen[spec["punkt_von"]])
            punkt = (lo + hi) / 2
        else:
            los = [_box(formen[n]) for n in bewegt]
            punkt = (np.min([b[0] for b in los], axis=0) + np.max([b[1] for b in los], axis=0)) / 2
        von = float(spec.get("von", 0))
        bis = float(spec.get("bis", 360 if art == "drehen" else 100))
        out.append(Bewegung(name=spec.get("name") or ", ".join(teile), art=art, teile=bewegt, punkt=punkt,
                            richtung=richtung, von=von, bis=bis, ist=0.0, schritte=int(spec.get("schritte") or 0),
                            ignorieren=[n for n in formen if _mitglied(n, spec.get("ignorieren") or [])],
                            freiraum=spec.get("freiraum"), quelle="bewegungen.json"))
    return out, warn


def _griff(bew: Bewegung, formen: dict[str, Any]) -> np.ndarray:
    if bew.griff is not None:
        return bew.griff
    form = formen[bew.teile[0]]
    pts = np.array([[v.X, v.Y, v.Z] for v in form.vertices()]) if form.vertices() else np.array([_box(form)[0]])
    if bew.art == "drehen":
        off = pts - bew.punkt
        radial = off - np.outer(off @ bew.richtung, bew.richtung)
        return pts[int(np.argmax(np.linalg.norm(radial, axis=1)))]
    lo, hi = _box(form)
    return (lo + hi) / 2


def _bereiche(werte: list[float], getroffen: set[float]) -> list[list[float]]:
    out: list[list[float]] = []
    vorher = False
    for w in werte:
        if w in getroffen:
            if vorher:
                out[-1][1] = w
            else:
                out.append([w, w])
            vorher = True
        else:
            vorher = False
    return out


def _frei(werte: list[float], blockiert: set[float]) -> list[list[float]]:
    out: list[list[float]] = []
    offen = False
    for w in werte:
        if w not in blockiert:
            if offen:
                out[-1][1] = w
            else:
                out.append([w, w])
            offen = True
        else:
            offen = False
    return out


def pruefe_bewegung(bew: Bewegung, formen: dict[str, Any], schluessel: dict[str, str],
                    zeitlimit_s: float | None, abbrechen: Any = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    werte = bew.werte()
    lagen_liste = np.array([bew.lage(w) for w in werte])
    bewegt = {n: formen[n] for n in bew.teile if n in formen}
    # Hüllquader des ganzen Wegs: nur Teile darin prüfen
    ecken = np.concatenate([_ecken(*_box(f)) for f in bewegt.values()])
    weg = np.einsum("kij,pj->kpi", lagen_liste[:, :3, :3], ecken) + lagen_liste[:, None, :3, 3]
    wlo, whi = weg.reshape(-1, 3).min(axis=0), weg.reshape(-1, 3).max(axis=0)
    rand = (bew.freiraum or 0.0)
    statisch = {}
    for n, f in formen.items():
        if n in bewegt or n in bew.ignorieren:
            continue
        lo, hi = _box(f)
        if np.all(lo < whi + rand) and np.all(hi > wlo - rand):
            statisch[n] = f
    griffraum = bool(bew.freiraum) and _dreht_um_sich(bew, formen, schluessel)
    griff_kand: dict[str, Any] = {}
    if griffraum:  # Griffraum um die Drehachse: Teile im Umkreis des bedienten Teils plus Freiraum
        g_lo, g_hi = _box(formen[bew.teile[0]])
        for n, f in formen.items():
            if n in bewegt or n in bew.ignorieren:
                continue
            lo, hi = _box(f)
            if np.all(lo < g_hi + 2 * rand) and np.all(hi > g_lo - 2 * rand):
                griff_kand[n] = f
    def stand(teile: dict[str, Any]) -> tuple:
        return tuple(sorted((n, schluessel.get(n) or str(id(f))) for n, f in teile.items()))

    # Schlüssel: alles, was das Ergebnis beeinflusst. Bewegte, feste und ignorierte Teile getrennt: Wandert ein Teil
    # nur von „fest“ nach „mitbewegt“, ist es ein anderer Weg (KevCup, 22.10.2026: sonst veraltete Kollisionen
    # zwischen Teilen derselben Gruppe)
    key = (bew.name, bew.art, tuple(np.round(bew.punkt, 4)), tuple(np.round(bew.richtung, 6)), bew.von, bew.bis,
           bew.ist, tuple(round(float(w), 6) for w in werte), bew.freiraum, bew.bedienung, griffraum,
           None if bew.griff is None else tuple(np.round(bew.griff, 3)), bew.achse_teil, TOLERANZ, MIN_VOLUMEN,
           GRIFF_INNEN, AUFLAGE_TOL, stand(bewegt), stand(statisch), tuple(sorted(bew.ignorieren)), stand(griff_kand))
    hit = _CACHE.get(key)
    if hit is not None:
        return {**hit, "zwischenspeicher": True}
    lagen = {n: lagen_liste for n in bewegt}
    paare = [(m, s) for m in bewegt for s in statisch]
    fn = _kollisionsfunktion()
    sk = {n: schluessel[n] for n in {**bewegt, **statisch} if schluessel.get(n)}
    befunde, stats = fn({**bewegt, **statisch}, lagen, werte, paare=paare, toleranz=TOLERANZ, min_volumen=MIN_VOLUMEN,
                        zeitlimit_s=zeitlimit_s, cache=_PAAR_CACHE if sk else None, schluessel=sk,
                        abbrechen=abbrechen)
    kollisionen: dict[tuple[str, str], list[Any]] = {}
    for b in befunde:
        m, s = b.teile if b.teile[0] in bewegt else (b.teile[1], b.teile[0])
        kollisionen.setdefault((m, s), []).append(b)
    # Paare, die schon in der Ausgangslage im Gewinde greifen: entlang bzw. um die Gewindeachse kein Hindernis
    gewinde: list[dict[str, Any]] = []
    i_ist = next((k for k, w in enumerate(werte) if abs(w - bew.ist) < 1e-9), None)
    for (m, s), bs in list(kollisionen.items()):
        if i_ist is None or not any(b.bild == i_ist for b in bs):
            continue
        eingriff = _gewinde_in_ruhe(m, s, formen, schluessel)
        if eingriff is not None and eingriff.entlang(bew.richtung, bew.punkt, drehen=bew.art == "drehen"):
            del kollisionen[(m, s)]
            gewinde.append({"teile": [m, s], "text": eingriff.text})
    blockiert = {werte[b.bild] for bs in kollisionen.values() for b in bs}
    # Freiraum am Griff
    eng: dict[str, list[tuple[float, float]]] = {}
    raum: dict[str, Any] | None = None
    if griffraum and not stats.get("abgebrochen"):
        raum = _griffraum_pruefen(bew, formen, griff_kand)
        for n, platz in raum.pop("eng").items():
            eng[n] = [(w, platz) for w in werte]  # der Griffraum dreht mit: gilt für den ganzen Weg
    elif bew.freiraum and not stats.get("abgebrochen"):
        from build123d import Vertex

        g0 = _griff(bew, formen)
        for k, w in enumerate(werte):
            if zeitlimit_s is not None and time.perf_counter() - t0 > zeitlimit_s:
                stats["abgebrochen"] = True
                break
            if abbrechen is not None:
                abbrechen()
            M = lagen_liste[k]
            g = M[:3, :3] @ g0 + M[:3, 3]
            for n, f in statisch.items():
                lo, hi = _box(f)
                if np.any(g < lo - bew.freiraum) or np.any(g > hi + bew.freiraum):
                    continue
                d = f.distance_to(Vertex(*map(float, g)))
                if d < bew.freiraum - 1e-6:  # eigener Befund; der freie Bereich zählt nur Kollisionen
                    eng.setdefault(n, []).append((w, d))
    frei = _frei(werte, blockiert)
    um_ist = next((f for f in frei if f[0] - 1e-9 <= bew.ist <= f[1] + 1e-9), None)
    ergebnis = {
        "name": bew.name, "art": bew.art, "quelle": bew.quelle, "bedingung": bew.bedingung, "teile": bew.teile,
        "punkt": [round(float(c), 3) for c in bew.punkt], "richtung": [round(float(c), 6) for c in bew.richtung],
        "von": bew.von, "bis": bew.bis, "ist": bew.ist, "schritte": len(werte) - 1, "frei": frei,
        "frei_um_ist": um_ist, "freiraum": bew.freiraum,
        "kollisionen": [{"gegen": s, "bewegt": m, "bereiche": _bereiche(werte, {werte[b.bild] for b in bs}),
                         "max_volumen": round(max(b.volumen for b in bs), 3),
                         "bei": werte[max(bs, key=lambda b: b.volumen).bild],
                         "ort": [round(c, 2) for c in max(bs, key=lambda b: b.volumen).ort],
                         "schon_in_ruhe": any(abs(werte[b.bild] - bew.ist) < 1e-9 for b in bs)}
                        for (m, s), bs in sorted(kollisionen.items())],
        "eng": [{"gegen": n, "bereiche": _bereiche(werte, {w for w, _ in v}), "min_abstand": round(min(d for _, d in v), 2),
                 **({"griffraum": True} if raum is not None else {})}
                for n, v in sorted(eng.items())],
        "geprueft_ms": round((time.perf_counter() - t0) * 1000, 1), "teilweise": bool(stats.get("abgebrochen")),
        "zwischenspeicher": False, "zeile": bew.zeile,
    }
    if bew.bedienung:
        ergebnis["bedienung"] = bew.bedienung
    if raum is not None:
        ergebnis["griffraum"] = raum
    if gewinde:
        ergebnis["gewinde"] = gewinde
    if not ergebnis["teilweise"]:
        _CACHE[key] = ergebnis
    return ergebnis


# ---------------------------------------------------------------------------------------------------------------------
# Gewinde in der Ausgangslage


def _gewinde_in_ruhe(m: str, s: str, formen: dict[str, Any], schluessel: dict[str, str]) -> Any:
    """Gewindeeingriff von m und s in der gezeigten Lage (``pruefung.kollision.im_gewinde``), je Geometriestand
    zwischengespeichert."""
    from kevcad_kernel.pruefung.kollision import im_gewinde

    key = (schluessel.get(m) or str(id(formen[m])), schluessel.get(s) or str(id(formen[s])))
    if key in _GEWINDE_CACHE:
        return _GEWINDE_CACHE.get(key)
    try:
        g = im_gewinde(formen[m], formen[s], name_a=m, name_b=s)
    except Exception:  # noqa: BLE001 - ohne Erkennung bleibt die Kollision ein Befund
        g = None
    _GEWINDE_CACHE[key] = g
    return g


# ---------------------------------------------------------------------------------------------------------------------
# Griffraum für Teile, die um ihre eigene Achse gedreht werden (Flügelmutter, Drehknopf)


def _punkte(form: Any) -> np.ndarray:
    """Punkte auf der Oberfläche (Netz, 0,2 mm genau), für Radien und Höhen entlang einer Achse."""
    try:
        verts, _ = form.tessellate(0.2)
        pts = np.array([[v.X, v.Y, v.Z] for v in verts], dtype=float)
        if len(pts):
            return pts
    except Exception:  # noqa: BLE001
        pass
    return np.array([[v.X, v.Y, v.Z] for v in form.vertices()], dtype=float)


def _dreht_um_sich(bew: Bewegung, formen: dict[str, Any], schluessel: dict[str, str] | None = None) -> bool:
    """Wird das Teil um seine eigene Achse gedreht (Flügelmutter, Knopf), statt wie ein Hebel um eine Achse am Rand?
    ``bedienung="fluegel"`` immer; Finger und Hand, wenn der Schwerpunkt nahe der Drehachse liegt (je Geometriestand
    zwischengespeichert, damit ein unveränderter Lauf nichts rechnet)."""
    if bew.art != "drehen" or bew.bedienung not in ("fluegel", "finger", "hand") or bew.griff is not None:
        return False
    if bew.bedienung == "fluegel":
        return True
    form = formen.get(bew.teile[0])
    if form is None:
        return False
    sk = (schluessel or {}).get(bew.teile[0])
    key = ("um_sich", sk, tuple(np.round(bew.punkt, 4)), tuple(np.round(bew.richtung, 6))) if sk else None
    if key is not None and key in _GEWINDE_CACHE:
        return bool(_GEWINDE_CACHE.get(key))
    out = _schwerpunkt_auf_achse(bew, form)
    if key is not None:
        _GEWINDE_CACHE[key] = out
    return out


def _schwerpunkt_auf_achse(bew: Bewegung, form: Any) -> bool:
    """Liegt der Schwerpunkt näher an der Drehachse als ein Viertel des größten Radius?"""
    try:
        from build123d import CenterOf

        c = np.array(list(form.center(CenterOf.MASS)), dtype=float)
    except Exception:  # noqa: BLE001
        lo, hi = _box(form)
        c = (lo + hi) / 2
    pts = _punkte(form)
    d = einheit(bew.richtung)
    off = pts - bew.punkt
    r = np.linalg.norm(off - np.outer(off @ d, d), axis=1)
    oc = c - bew.punkt
    rc = float(np.linalg.norm(oc - d * float(np.dot(oc, d))))
    return len(r) > 0 and rc <= 0.25 * float(r.max())


def _griffraum_pruefen(bew: Bewegung, formen: dict[str, Any], kandidaten: dict[str, Any]) -> dict[str, Any]:
    """Griffraum: Zylinderring um die Drehachse, innen ab dem halben Spitzenradius (Nabe, Bolzen), außen bis
    Flügelspitze plus Freiraum; axial über dem Griff (dem Bereich, in dem das Teil über die Nabe hinausragt: Flügel,
    Kopf), von der Auflage (0,5 mm darüber) bis Oberkante plus Freiraum, also nur auf der Griffseite. Die Auflage ist
    die Seite des Griffs, an der ein festes Teil anliegt (Scheibe, Platte, Backe); liegt auf beiden Seiten etwas an, nur
    die Höhe des Griffs, ebenso wenn nichts anliegt. Liefert die Maße und je eindringendem Teil den Platz neben der
    Spitze (``eng``: Name → mm)."""
    from build123d import Align, Cylinder, Edge, Location, Plane, Pos

    from kevcad_kernel.pruefung.kollision import abstand, schnittmenge, volumen_und_achsen

    form = formen[bew.teile[0]]
    d = einheit(bew.richtung)
    p = np.asarray(bew.punkt, dtype=float)
    pts = _punkte(form)
    off = pts - p
    t = off @ d
    r = np.linalg.norm(off - np.outer(t, d), axis=1)
    r_spitze = float(r.max())
    r_in, r_out = GRIFF_INNEN * r_spitze, r_spitze + float(bew.freiraum or 0.0)
    # Griff: der Bereich entlang der Achse, in dem das Teil über die Nabe hinausragt (Flügel, Kopf); der Schaft einer
    # Flügelschraube steckt in Backe und Einsatz und gehört nicht dazu
    kopf = t[r >= r_in - 1e-6]
    t0, t1 = (float(kopf.min()), float(kopf.max())) if len(kopf) else (float(t.min()), float(t.max()))
    frei = float(bew.freiraum or 0.0)
    g_lo, g_hi = _box(form)
    seiten: set[int] = set()
    for n, f in kandidaten.items():
        lo, hi = _box(f)
        if np.any(lo > g_hi + AUFLAGE_TOL) or np.any(hi < g_lo - AUFLAGE_TOL):
            continue
        try:
            spalt = float(form.distance_to(f))
        except Exception:  # noqa: BLE001
            continue
        if spalt > AUFLAGE_TOL:
            continue
        s = (_ecken(lo, hi) - p) @ d
        if float(s.max()) <= t0 + AUFLAGE_TOL:
            seiten.add(-1)  # liegt unter dem Griff (Scheibe, Platte, Backe): Griff zur anderen Seite
        elif float(s.min()) >= t1 - AUFLAGE_TOL:
            seiten.add(1)
    if seiten == {-1}:
        a0, a1, auflage = t0 + 0.5, t1 + frei, "unten"
    elif seiten == {1}:
        a0, a1, auflage = t0 - frei, t1 - 0.5, "oben"
    elif seiten == {-1, 1}:
        a0, a1, auflage = t0 + 0.5, t1 - 0.5, "beidseitig"
    else:
        a0, a1, auflage = t0, t1, "keine"
    hoehe = max(a1 - a0, 0.1)
    unten = (Align.CENTER, Align.CENTER, Align.MIN)
    ring = Cylinder(r_out, hoehe, align=unten) - Pos(0, 0, -1) * Cylinder(r_in, hoehe + 2, align=unten)
    ring = Location(Plane(origin=tuple(map(float, p + d * a0)), z_dir=tuple(map(float, d)))) * ring
    achse = Edge.make_line(tuple(map(float, p + d * (a0 - 1))), tuple(map(float, p + d * (a1 + 1))))
    rb = ring.bounding_box()
    rlo, rhi = np.array([rb.min.X, rb.min.Y, rb.min.Z]), np.array([rb.max.X, rb.max.Y, rb.max.Z])
    eng: dict[str, float] = {}
    for n, f in kandidaten.items():
        lo, hi = _box(f)
        if np.any(lo > rhi) or np.any(hi < rlo):
            continue
        common = schnittmenge(ring.wrapped, f.wrapped)
        if common is None:
            continue
        vol, _, _ = volumen_und_achsen(common)
        if vol < MIN_VOLUMEN:
            continue
        r_min = abstand(achse.wrapped, common)  # kleinster Abstand des eindringenden Teils von der Drehachse
        if r_min is None:
            r_min = r_in
        eng[n] = round(max(0.0, float(r_min) - r_spitze), 2)
    return {"r_spitze": round(r_spitze, 2), "r_innen": round(r_in, 2), "r_aussen": round(r_out, 2),
            "von": round(a0, 2), "bis": round(a1, 2), "auflage": auflage, "eng": eng}


def _befunde(erg: dict[str, Any], hintergrund: bool = False) -> list[dict[str, Any]]:
    from .pruefung import _befund

    e = "°" if erg["art"] == "drehen" else " mm"
    fmt = (lambda v: grad(v)) if erg["art"] == "drehen" else (lambda v: mm(v))

    def ber(liste: list[list[float]]) -> str:
        return ", ".join(f"{fmt(a)} … {fmt(b)}" if a != b else fmt(a) for a, b in liste) or "nirgends"

    frei_text = ber(erg["frei"])
    out = []
    soll = f"frei von {fmt(erg['von'])} bis {fmt(erg['bis'])}"
    for k in erg["kollisionen"]:
        ruhe = " (schon in Ruhelage)" if k["schon_in_ruhe"] else ""
        out.append(_befund(
            pruefung="bewegungsraum", teile=[k["bewegt"], k["gegen"]], schwere="fehler",
            text=f"{erg['name']}: stößt bei {ber(k['bereiche'])} an {k['gegen']}{ruhe}; frei {frei_text}",
            soll=soll, ist=f"Kollision bei {ber(k['bereiche'])}, frei {frei_text}", wert=k["max_volumen"],
            einheit="mm³", ort=k["ort"], art=erg["art"], bedingung=erg.get("bedingung"), zeile=erg.get("zeile"),
            loesung=(f"Platz schaffen: {k['gegen']} versetzen, aussparen oder kürzen, oder {k['bewegt']} so umbauen, "
                     f"dass es den Weg schafft; den Bereich nur kleiner machen, wenn die Bedienung das erlaubt")))
    raum = erg.get("griffraum")
    for k in erg.get("eng") or []:
        if k.get("griffraum") and raum:
            seite = {"unten": "über der Auflage", "oben": "unter der Auflage", "beidseitig": "zwischen den Auflagen",
                     "keine": "neben dem Griff"}.get(raum["auflage"], "")
            out.append(_befund(
                pruefung="bewegungsraum", teile=[erg["teile"][0], k["gegen"]], schwere="fehler",
                text=f"{erg['name']}: kein Griffraum, {k['gegen']} ragt in den Raum um die Drehachse {seite} "
                     f"(nur {mm(k['min_abstand'], 1)} neben der Spitze frei, nötig {mm(erg['freiraum'], 0)})",
                soll=f"Griffraum frei: Ring Ø {mm(2 * raum['r_innen'], 0)} bis Ø {mm(2 * raum['r_aussen'], 0)} um die "
                     f"Drehachse {seite}", ist=f"{k['gegen']} im Griffraum",
                wert=k["min_abstand"] - float(erg["freiraum"]), ort=None, art=erg["art"],
                bedingung=erg.get("bedingung"), zeile=erg.get("zeile"),
                loesung=f"{k['gegen']} vom Bedienteil wegrücken oder aussparen, das Bedienteil höher setzen "
                        f"(längerer Stift, Distanzscheibe) oder eine kleinere Flügelmutter bzw. einen Knopf wählen, "
                        f"damit Daumen und Zeigefinger es fassen können"))
            continue
        out.append(_befund(
            pruefung="bewegungsraum", teile=[erg["teile"][0], k["gegen"]], schwere="fehler",
            text=f"{erg['name']}: am Griff nur {mm(k['min_abstand'], 1)} Platz zu {k['gegen']} bei {ber(k['bereiche'])}"
                 f" (Freiraum {mm(erg['freiraum'], 0)})",
            soll=f"Freiraum ≥ {mm(erg['freiraum'], 0)} über den ganzen Weg", ist=f"{mm(k['min_abstand'], 1)}",
            wert=k["min_abstand"] - float(erg["freiraum"]), ort=None, art=erg["art"], bedingung=erg.get("bedingung"),
            zeile=erg.get("zeile"),
            loesung=f"Griff verlängern oder {k['gegen']} vom Griff wegrücken, damit Finger oder Werkzeug Platz haben"))
    if erg["teilweise"]:
        if hintergrund:
            out.append(_befund(pruefung="bewegungsraum", teile=erg["teile"][:1], schwere="hinweis",
                               text=f"{erg['name']}: Weg erst teilweise geprüft (Zeitlimit des Laufs), wird im "
                                    "Hintergrund fertig gerechnet", art=erg["art"], bedingung=erg.get("bedingung"),
                               loesung="pruefen(warten=true) bzw. bedingungen() zeigt den Endstand"))
        else:
            out.append(_befund(pruefung="bewegungsraum", teile=erg["teile"][:1], schwere="hinweis",
                               text=f"{erg['name']}: Weg nur teilweise geprüft (Zeitlimit)", art=erg["art"],
                               bedingung=erg.get("bedingung"),
                               loesung="schritte=… verkleinern oder einzeln mit tools/check_motion.py prüfen"))
    _ = e, vektor
    return out


def bewegungen_pruefen(sammlung: Any, aufgeloest: dict[str, tuple[Bezug, Bezug]], formen: dict[str, Any], *,
                       schluessel: dict[str, str], projekt: str | Path | None, zeitlimit_s: float | None,
                       boxen: dict[str, tuple[np.ndarray, np.ndarray]] | None = None, abbrechen: Any = None,
                       offen: list[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Alle Wege prüfen: (Ergebnisse je Weg, Befunde). ``zeitlimit_s`` None: ohne Zeitlimit (Fertigrechnen im
    Hintergrund). ``abbrechen`` wird vor jeder exakten Rechnung aufgerufen und darf mit einer Ausnahme unterbrechen
    (was gerechnet ist, bleibt im Zwischenspeicher). ``offen``: Liste, in die die Namen der Wege kommen, die das
    Zeitlimit nicht ganz geschafft haben; mit ihr sagen die Hinweise „wird im Hintergrund fertig gerechnet“."""
    _BOXEN.clear()
    for n, f in formen.items():
        if boxen and n in boxen:
            _BOXEN[id(f)] = boxen[n]
    try:
        return _bewegungen_pruefen(sammlung, aufgeloest, formen, schluessel=schluessel, projekt=projekt,
                                   zeitlimit_s=zeitlimit_s, abbrechen=abbrechen, offen=offen)
    finally:
        _BOXEN.clear()


def _bewegungen_pruefen(sammlung: Any, aufgeloest: dict[str, tuple[Bezug, Bezug]], formen: dict[str, Any], *,
                        schluessel: dict[str, str], projekt: str | Path | None, zeitlimit_s: float | None,
                        abbrechen: Any = None, offen: list[str] | None = None
                        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    t0 = time.perf_counter()
    liste: list[Bewegung] = []
    for c in sammlung.bedingungen:
        if isinstance(c, Gelenk) and c.id in aufgeloest:
            A, B = aufgeloest[c.id]
            bew = aus_gelenk(c, A, B, formen)
            if bew is not None:
                liste.append(bew)
    hinweise: list[str] = []
    if projekt is not None:
        aus, hinweise = aus_json(Path(projekt), formen)
        # Gelenke in model.py sind die Quelle (Kevin, 22.10.2026); bewegungen.json gilt nur für Teile ohne Gelenk
        mit_gelenk = {t for b in liste for t in b.teile}
        doppelt = [b.name for b in aus if any(t in mit_gelenk for t in b.teile)]
        liste.extend(b for b in aus if not any(t in mit_gelenk for t in b.teile))
        if doppelt:
            hinweise.append(f"bewegungen.json: {len(doppelt)} Einträge übergangen, weil die Teile ein Gelenk in model.py "
                            f"haben ({', '.join(doppelt[:3])}{' …' if len(doppelt) > 3 else ''})")
    ergebnisse, befunde = [], []
    hintergrund = offen is not None
    for bew in liste:
        rest = None if zeitlimit_s is None else zeitlimit_s - (time.perf_counter() - t0)
        if rest is not None and rest <= 0:
            from .pruefung import _befund

            if hintergrund:
                offen.append(bew.name)  # type: ignore[union-attr]
                befunde.append(_befund(pruefung="bewegungsraum", teile=bew.teile[:1], schwere="hinweis",
                                       text=f"{bew.name}: noch nicht geprüft (Zeitlimit des Laufs), wird im "
                                            "Hintergrund fertig gerechnet",
                                       loesung="pruefen(warten=true) bzw. bedingungen() zeigt den Endstand",
                                       bedingung=bew.bedingung))
            else:
                befunde.append(_befund(pruefung="bewegungsraum", teile=bew.teile[:1], schwere="hinweis",
                                       text=f"{bew.name}: nicht geprüft (Zeitlimit des Laufs erreicht)",
                                       loesung="einzeln mit tools/check_motion.py prüfen", bedingung=bew.bedingung))
            continue
        erg = pruefe_bewegung(bew, formen, schluessel, rest, abbrechen)
        ergebnisse.append(erg)
        if erg["teilweise"] and hintergrund:
            offen.append(bew.name)  # type: ignore[union-attr]
        befunde.extend(_befunde(erg, hintergrund))
    for h in hinweise:
        from .pruefung import _befund

        befunde.append(_befund(pruefung="bewegungsraum", teile=[], schwere="hinweis", text=h))
    return ergebnisse, befunde
