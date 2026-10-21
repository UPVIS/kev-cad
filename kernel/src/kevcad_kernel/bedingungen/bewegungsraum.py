"""Bewegungsraum (Range of Motion, PLAN-BEDINGUNGEN.md B8): jedes Gelenk mit Bereich über den ganzen Weg prüfen.

Je Gelenk (``drehgelenk``, ``schiebegelenk``, ``zylindergelenk`` mit ``bereich``) und je Eintrag in
``<projekt>/bewegungen.json`` (Format wie ``kernel/tools/check_motion.py``) wird das bewegte Teil samt mitbewegten
Teilen in Schritten über den Bereich gefahren und gegen alle übrigen Teile geprüft: Hüllquader-Vorfilter, dann exaktes
Schnittvolumen. Berühren ist erlaubt (unter ``min_volumen`` mm³ oder dünner als ``toleranz`` mm). Bedienteile prüfen
zusätzlich den Freiraum am Griff (Finger, Hand, Werkzeug).

Die Kollisionsfunktion ist dieselbe wie bei der Animation: ``kevcad_kernel.anim_kollision.pruefe_kollisionen``, sobald
der Strang Animation zusammengeführt ist; bis dahin eine Fassung mit gleicher Schnittstelle (``_pruefe_kollisionen``).
Ergebnisse werden je Geometriestand zwischengespeichert, damit ein neuer Lauf ohne Änderung am Gelenk nichts kostet.
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

try:  # gemeinsame Kollisionsfunktion mit der Animation (Strang ANI)
    from kevcad_kernel.anim_kollision import pruefe_kollisionen  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - bis zum Zusammenführen
    pruefe_kollisionen = None  # type: ignore[assignment]

_CACHE: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
_CACHE_MAX = 200


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
                        toleranz=TOLERANZ, min_volumen=MIN_VOLUMEN, sichtbar=None, zeitlimit_s=None):
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
            stats["exakt"] += 1
            wb = formen[b].wrapped.Moved(TopLoc_Location(matrix_trsf(rel)))
            res = _gemeinsam(formen[a], wb)
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
                    bedingung=g.id)


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
                    zeitlimit_s: float | None) -> dict[str, Any]:
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
    key = (bew.name, bew.art, tuple(np.round(bew.punkt, 4)), tuple(np.round(bew.richtung, 6)), bew.von, bew.bis,
           bew.ist, len(werte), bew.freiraum, None if bew.griff is None else tuple(np.round(bew.griff, 3)),
           tuple(sorted((n, schluessel.get(n, str(id(f)))) for n, f in {**bewegt, **statisch}.items())))
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return {**_CACHE[key], "zwischenspeicher": True}
    lagen = {n: lagen_liste for n in bewegt}
    paare = [(m, s) for m in bewegt for s in statisch]
    fn = _kollisionsfunktion()
    befunde, stats = fn({**bewegt, **statisch}, lagen, werte, paare=paare, toleranz=TOLERANZ, min_volumen=MIN_VOLUMEN,
                        zeitlimit_s=zeitlimit_s)
    kollisionen: dict[tuple[str, str], list[Any]] = {}
    for b in befunde:
        m, s = b.teile if b.teile[0] in bewegt else (b.teile[1], b.teile[0])
        kollisionen.setdefault((m, s), []).append(b)
    blockiert = {werte[b.bild] for b in befunde}
    # Freiraum am Griff
    eng: dict[str, list[tuple[float, float]]] = {}
    if bew.freiraum and not stats.get("abgebrochen"):
        from build123d import Vertex

        g0 = _griff(bew, formen)
        for k, w in enumerate(werte):
            if zeitlimit_s is not None and time.perf_counter() - t0 > zeitlimit_s:
                stats["abgebrochen"] = True
                break
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
        "eng": [{"gegen": n, "bereiche": _bereiche(werte, {w for w, _ in v}), "min_abstand": round(min(d for _, d in v), 2)}
                for n, v in sorted(eng.items())],
        "geprueft_ms": round((time.perf_counter() - t0) * 1000, 1), "teilweise": bool(stats.get("abgebrochen")),
        "zwischenspeicher": False, "zeile": bew.zeile,
    }
    if not ergebnis["teilweise"]:
        _CACHE[key] = ergebnis
        if len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return ergebnis


def _befunde(erg: dict[str, Any]) -> list[dict[str, Any]]:
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
    for k in erg.get("eng") or []:
        out.append(_befund(
            pruefung="bewegungsraum", teile=[erg["teile"][0], k["gegen"]], schwere="fehler",
            text=f"{erg['name']}: am Griff nur {mm(k['min_abstand'], 1)} Platz zu {k['gegen']} bei {ber(k['bereiche'])}"
                 f" (Freiraum {mm(erg['freiraum'], 0)})",
            soll=f"Freiraum ≥ {mm(erg['freiraum'], 0)} über den ganzen Weg", ist=f"{mm(k['min_abstand'], 1)}",
            wert=k["min_abstand"] - float(erg["freiraum"]), ort=None, art=erg["art"], bedingung=erg.get("bedingung"),
            zeile=erg.get("zeile"),
            loesung=f"Griff verlängern oder {k['gegen']} vom Griff wegrücken, damit Finger oder Werkzeug Platz haben"))
    if erg["teilweise"]:
        out.append(_befund(pruefung="bewegungsraum", teile=erg["teile"][:1], schwere="hinweis",
                           text=f"{erg['name']}: Weg nur teilweise geprüft (Zeitlimit)", art=erg["art"],
                           bedingung=erg.get("bedingung"),
                           loesung="schritte=… verkleinern oder einzeln mit tools/check_motion.py prüfen"))
    _ = e, vektor
    return out


def bewegungen_pruefen(sammlung: Any, aufgeloest: dict[str, tuple[Bezug, Bezug]], formen: dict[str, Any], *,
                       schluessel: dict[str, str], projekt: str | Path | None, zeitlimit_s: float,
                       boxen: dict[str, tuple[np.ndarray, np.ndarray]] | None = None
                       ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _BOXEN.clear()
    for n, f in formen.items():
        if boxen and n in boxen:
            _BOXEN[id(f)] = boxen[n]
    try:
        return _bewegungen_pruefen(sammlung, aufgeloest, formen, schluessel=schluessel, projekt=projekt,
                                   zeitlimit_s=zeitlimit_s)
    finally:
        _BOXEN.clear()


def _bewegungen_pruefen(sammlung: Any, aufgeloest: dict[str, tuple[Bezug, Bezug]], formen: dict[str, Any], *,
                        schluessel: dict[str, str], projekt: str | Path | None,
                        zeitlimit_s: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
    for bew in liste:
        rest = zeitlimit_s - (time.perf_counter() - t0)
        if rest <= 0:
            from .pruefung import _befund

            befunde.append(_befund(pruefung="bewegungsraum", teile=bew.teile[:1], schwere="hinweis",
                                   text=f"{bew.name}: nicht geprüft (Zeitlimit des Laufs erreicht)",
                                   loesung="einzeln mit tools/check_motion.py prüfen", bedingung=bew.bedingung))
            continue
        erg = pruefe_bewegung(bew, formen, schluessel, rest)
        ergebnisse.append(erg)
        befunde.extend(_befunde(erg))
    for h in hinweise:
        from .pruefung import _befund

        befunde.append(_befund(pruefung="bewegungsraum", teile=[], schwere="hinweis", text=h))
    return ergebnisse, befunde
