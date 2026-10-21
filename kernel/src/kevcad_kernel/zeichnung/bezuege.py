"""Bezüge (DOKUMENTE.md, „Bezüge“): Maße und Notizen zeigen auf Geometrie über Merkmal-Kennung und Signatur.

```json
{"teil": "…", "art": "kante" | "punkt" | "flaeche" | "achse" | "bohrung" | "huelle" | "merkmal",
 "signatur": {"typ": "kreis", "mitte": [x, y, z], "richtung": [x, y, z], "radius": 3.3, "laenge": null},
 "merkmal": "bohrung:3", "ref": "Teil#e12"}
```

Neuzuordnung nach jedem Lauf (Regel aus D3, begründet):

1. ``merkmal`` gibt es noch, von derselben Art, und die Signatur ist ähnlich (gleicher Typ, Radius bis 30 % bzw.
   0,5 mm, Lage bis 25 % der Teilgröße bzw. 5 mm): Treffer. So überlebt ein Maß eine geänderte Rohrlänge oder einen
   verschobenen Lochabstand, ohne an eine fremde Bohrung zu springen, wenn sich die Nummerierung verschiebt.
2. Sonst das Merkmal derselben Art mit der nächsten Signatur innerhalb der engen Toleranz (0,5 mm + 1 % der Größe,
   Radius 0,05 mm): Treffer, die Kennung wird nachgeführt.
3. Kanten und Punkte ohne Merkmal: nächste Kante bzw. nächster Punkt gleicher Art innerhalb der engen Toleranz.
4. Sonst: verwaist (das Maß bleibt sichtbar markiert, bis jemand es löscht oder neu bezieht).

Signaturen liegen im lokalen System des Teils (teilsystem.py); ``Element`` liefert sie für die Darstellung in
Weltkoordinaten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.merkmale import Kante, Merkmal, Merkmale

ARTEN = ("kante", "punkt", "flaeche", "achse", "bohrung", "huelle", "merkmal")
GRUPPEN = {  # Merkmal-Arten, die sich gegenseitig ersetzen dürfen
    "bohrung": ("bohrung", "einsatztasche"),
    "einsatztasche": ("bohrung", "einsatztasche"),
    "tasche": ("tasche", "absatz"),
    "absatz": ("tasche", "absatz"),
}


def _arr(v: Any) -> np.ndarray | None:
    return None if v is None else np.asarray(v, dtype=float)


def _r(v: Any) -> Any:
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_r(x) for x in v]
    x = round(float(v), 4)
    return 0.0 if x == 0 else x


@dataclass
class Element:
    """Aufgelöster Bezug in Weltkoordinaten."""

    typ: str  # punkt | linie | ebene | kreis | bogen | box
    teil: str
    p: np.ndarray
    d: np.ndarray | None = None
    r: float | None = None
    ecken: np.ndarray | None = None  # Ebene/Linie/Box: Eckpunkte (Ausdehnung, für Ansatzpunkte von Hilfslinien)
    merkmal: Merkmal | None = None
    kante: Kante | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def art_von(m: Merkmal) -> str:
    """Bezugsart eines Merkmals (Vertrag: kante, punkt, flaeche, achse, bohrung, huelle, merkmal)."""
    if m.art in ("bohrung", "einsatztasche"):
        return "bohrung"
    if m.art == "huelle":
        return "huelle"
    if m.art in ("seite", "tasche", "absatz", "fase", "stirnseite"):
        return "flaeche"
    if m.art in ("stange", "radius"):
        return "achse"
    return "merkmal"


def aus_merkmal(teil: str, m: Merkmal, ref: str | None = None) -> dict[str, Any]:
    sig = {k: _r(v) for k, v in m.signatur.items()}
    return {"teil": teil, "art": art_von(m), "signatur": sig, "merkmal": m.id, "ref": ref}


def aus_kante(teil: str, k: Kante, run: int | None = None) -> dict[str, Any]:
    sig = {"typ": k.typ if k.typ != "andere" else "kurve", "mitte": _r(k.mitte), "richtung": _r(k.richtung),
           "radius": _r(k.radius), "laenge": _r(k.laenge)}
    return {"teil": teil, "art": "kante", "signatur": sig, "merkmal": None, "ref": f"{teil}#e{k.index}"}


def aus_punkt(teil: str, p: np.ndarray, index: int | None = None) -> dict[str, Any]:
    sig = {"typ": "punkt", "mitte": _r(p), "richtung": None, "radius": None, "laenge": None}
    return {"teil": teil, "art": "punkt", "signatur": sig, "merkmal": None,
            "ref": f"{teil}#v{index}" if index is not None else None}


# ---------------------------------------------------------------------------------------------------------------------
# Vergleich von Signaturen
# ---------------------------------------------------------------------------------------------------------------------


def abstand(a: dict[str, Any], b: dict[str, Any], groesse: float) -> float | None:
    """Maß der Abweichung zweier Signaturen (0 = gleich); None, wenn der Typ nicht passt."""
    if (a.get("typ") or "") != (b.get("typ") or ""):
        return None
    pa, pb = _arr(a.get("mitte")), _arr(b.get("mitte"))
    d = 0.0
    if pa is not None and pb is not None and pa.shape == pb.shape:
        d += float(np.linalg.norm(pa - pb))
    ra, rb = a.get("radius"), b.get("radius")
    if ra is not None and rb is not None:
        d += 10.0 * abs(float(ra) - float(rb))
    da, db = _arr(a.get("richtung")), _arr(b.get("richtung"))
    if da is not None and db is not None and da.shape == db.shape and np.linalg.norm(da) > 0 and np.linalg.norm(db) > 0:
        cos = abs(float(np.dot(da, db)) / (np.linalg.norm(da) * np.linalg.norm(db)))
        if cos < 0.999:
            d += groesse  # andere Richtung: deutlich schlechter
    return d


def aehnlich(a: dict[str, Any], b: dict[str, Any], groesse: float) -> bool:
    """Lockere Prüfung für Treffer über die Merkmal-Kennung (Regel 1)."""
    if (a.get("typ") or "") != (b.get("typ") or ""):
        return False
    ra, rb = a.get("radius"), b.get("radius")
    if ra is not None and rb is not None and abs(float(ra) - float(rb)) > max(0.5, 0.3 * abs(float(ra))):
        return False
    pa, pb = _arr(a.get("mitte")), _arr(b.get("mitte"))
    if pa is not None and pb is not None and pa.shape == pb.shape:
        if float(np.linalg.norm(pa - pb)) > max(5.0, 0.25 * groesse):
            return False
    da, db = _arr(a.get("richtung")), _arr(b.get("richtung"))
    if da is not None and db is not None and da.shape == db.shape and np.linalg.norm(da) > 0 and np.linalg.norm(db) > 0:
        if abs(float(np.dot(da, db)) / (np.linalg.norm(da) * np.linalg.norm(db))) < 0.99:
            return False
    return True


def eng(groesse: float) -> float:
    return 0.5 + 0.01 * groesse


# ---------------------------------------------------------------------------------------------------------------------
# Neuzuordnung
# ---------------------------------------------------------------------------------------------------------------------


def zuordnen(bezug: dict[str, Any], merkmale: Merkmale | None) -> tuple[dict[str, Any] | None, Merkmal | Kante | np.ndarray | None]:
    """Bezug gegen die Merkmale des neuen Laufs: (nachgeführter Bezug, Treffer) oder (None, None) = verwaist."""
    if merkmale is None:
        return None, None
    sig = bezug.get("signatur") or {}
    groesse = float(np.max(merkmale.groesse)) if len(merkmale.groesse) else 100.0
    mid = bezug.get("merkmal")
    if mid:
        alt_art = str(mid).split(":", 1)[0]
        arten = GRUPPEN.get(alt_art, (alt_art,))
        m = merkmale.get(mid)
        if m is not None and m.art in arten and (not sig or aehnlich(sig, m.signatur, groesse)):
            return _nachgefuehrt(bezug, m), m
        # Regel 2: nächstes Merkmal derselben Art innerhalb der engen Toleranz
        best = None
        for m in merkmale.von_art(*arten):
            dd = abstand(sig, m.signatur, groesse) if sig else None
            if dd is not None and dd <= eng(groesse) and (best is None or dd < best[0]):
                best = (dd, m)
        if best is not None:
            return _nachgefuehrt(bezug, best[1]), best[1]
        return None, None
    art = bezug.get("art")
    if art == "punkt":
        p = _arr(sig.get("mitte"))
        if p is None or not merkmale.punkte:
            return None, None
        ds = [float(np.linalg.norm(q - p)) for q in merkmale.punkte]
        i = int(np.argmin(ds))
        if ds[i] <= eng(groesse):
            return {**bezug, "signatur": {**sig, "mitte": _r(merkmale.punkte[i])}}, merkmale.punkte[i]
        return None, None
    # Kante ohne Merkmal
    best = None
    for k in merkmale.kanten:
        ksig = {"typ": k.typ if k.typ != "andere" else "kurve", "mitte": k.mitte, "richtung": k.richtung,
                "radius": k.radius}
        dd = abstand(sig, ksig, groesse)
        if dd is not None and (sig.get("laenge") is None or abs(float(sig["laenge"]) - k.laenge) <= eng(groesse) * 4):
            if dd <= eng(groesse) and (best is None or dd < best[0]):
                best = (dd, k)
    if best is None:
        return None, None
    k = best[1]
    neu = aus_kante(bezug.get("teil") or merkmale.teil, k)
    return {**bezug, "signatur": neu["signatur"], "ref": neu["ref"]}, k


def _nachgefuehrt(bezug: dict[str, Any], m: Merkmal) -> dict[str, Any]:
    return {**bezug, "merkmal": m.id, "signatur": {k: _r(v) for k, v in m.signatur.items()}}


# ---------------------------------------------------------------------------------------------------------------------
# Elemente für die Darstellung
# ---------------------------------------------------------------------------------------------------------------------


def element(treffer: Any, merkmale: Merkmale, teil: str) -> Element | None:
    """Treffer (Merkmal, Kante oder Punkt, lokal) → Element in Weltkoordinaten."""
    sysw = merkmale.system
    g = merkmale.groesse
    if isinstance(treffer, np.ndarray):
        return Element("punkt", teil, sysw.welt(treffer))
    if isinstance(treffer, Kante):
        k = treffer
        pts = sysw.welt(k.punkte)
        if k.typ == "linie":
            return Element("linie", teil, sysw.welt(k.mitte), sysw.richtung_welt(k.richtung) if k.richtung is not None
                           else None, None, np.array([sysw.welt(k.a), sysw.welt(k.b)]), kante=k)
        if k.typ == "kreis":
            return Element("kreis", teil, sysw.welt(k.mitte), sysw.richtung_welt(k.richtung), k.radius, pts, kante=k)
        return Element("linie", teil, sysw.welt(k.mitte), None, None, pts, kante=k)
    m: Merkmal = treffer
    sig = m.signatur
    mitte = np.asarray(sig.get("mitte"), dtype=float)
    richtung = _arr(sig.get("richtung"))
    w = m.werte
    if m.art == "seite":
        i, s = int(w["achse"]), int(w["seite"])
        ecken = []
        a, b = [j for j in range(3) if j != i]
        for ua in (0.0, g[a]):
            for ub in (0.0, g[b]):
                p = np.zeros(3)
                p[i] = 0.0 if s < 0 else g[i]
                p[a], p[b] = ua, ub
                ecken.append(p)
        return Element("ebene", teil, sysw.welt(mitte), sysw.richtung_welt(richtung), None, sysw.welt(np.array(ecken)),
                       m)
    if m.art in ("bohrung", "einsatztasche"):
        d = sysw.richtung_welt(np.asarray(w["achse"], dtype=float))
        p = sysw.welt(mitte)
        laenge = float(w.get("laenge") or 0.0)
        return Element("kreis", teil, p, d, float(w["d"]) / 2, np.array([p, p + d * laenge]), m,
                       extra={"laenge": laenge})
    if m.art == "lochbild":
        return Element("punkt", teil, sysw.welt(mitte), sysw.richtung_welt(richtung) if richtung is not None else None,
                       float(w.get("d") or 0) / 2, merkmal=m)
    if m.art in ("tasche", "absatz"):
        lo, hi = np.asarray(w["lo"], dtype=float), np.asarray(w["hi"], dtype=float)
        i = int(w["achse"])
        a, b = [j for j in range(3) if j != i]
        ecken = []
        for ua in (lo[a], hi[a]):
            for ub in (lo[b], hi[b]):
                p = mitte.copy()
                p[a], p[b] = ua, ub
                ecken.append(p)
        return Element("ebene", teil, sysw.welt(mitte), sysw.richtung_welt(richtung), None, sysw.welt(np.array(ecken)),
                       m)
    if m.art in ("fase", "stirnseite"):
        return Element("ebene", teil, sysw.welt(mitte), sysw.richtung_welt(richtung), None, None, m)
    if m.art == "radius":
        zentren = w.get("zentren") or []
        achsen = w.get("achsen") or []
        if zentren and achsen:
            return Element("bogen", teil, sysw.welt(np.asarray(zentren[0])), sysw.richtung_welt(np.asarray(achsen[0])),
                           float(w["r"]), sysw.welt(np.asarray(w["lagen"][:1])) if w.get("lagen") else None, m)
        return Element("punkt", teil, sysw.welt(mitte), None, float(w["r"]), merkmal=m)
    if m.art == "stange":
        a = np.array([0.0, g[1] / 2, g[2] / 2])
        b = np.array([g[0], g[1] / 2, g[2] / 2])
        return Element("linie", teil, sysw.welt(mitte), sysw.richtung_welt(np.array([1.0, 0, 0])), None,
                       sysw.welt(np.array([a, b])), m)
    if m.art == "huelle":
        ecken = np.array([[x, y, z] for x in (0, g[0]) for y in (0, g[1]) for z in (0, g[2])], dtype=float)
        return Element("box", teil, sysw.welt(mitte), None, None, sysw.welt(ecken), m)
    if m.art == "langloch":
        mitten = [sysw.welt(np.asarray(p)) for p in w.get("mitten") or []]
        return Element("punkt", teil, sysw.welt(mitte), sysw.richtung_welt(np.asarray(w["achse"])), float(w["breite"]) / 2,
                       np.array(mitten) if mitten else None, m)
    if m.art == "muttertasche":
        return Element("kreis", teil, sysw.welt(mitte), sysw.richtung_welt(richtung), float(w["sw"]) / 2, None, m)
    return Element("punkt", teil, sysw.welt(mitte), None, None, merkmal=m)
