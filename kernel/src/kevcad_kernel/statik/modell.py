"""Statikmodell aus dem Prüfstand eines Laufs (T2): Stäbe, Starrkörper, Anschlüsse und Auflager.

- **Stäbe** sind gezeigte Lagerteile der Stangenware (Rohr, Vierkantrohr, Profil, Holz …) mit Querschnittswerten aus
  dem Katalog. Achse und Länge kommen aus der Geometrie (Hauptachse des Netzes durch den Schwerpunkt), so zählt die
  tatsächliche Lage, nicht die Zeile in model.py. Gedrungene Teile (kürzer als dreimal so lang wie breit) sind keine Stäbe.
- **Starrkörper** sind zusammenhängende Gruppen der übrigen Teile (Druckteile, Platten, Zukaufteile samt ihren
  Schrauben). Zusammen hängen sie über Berührung (bis 0,05 mm), Gewinde, erlaubte Überlappung, ``verbinde`` und Gelenke
  zwischen Nicht-Stäben (die gelten als festgestellt). Spiel zwischen zwei Nicht-Stäben verbindet nicht.
- **Geerdet** ist ein Starrkörper, der auf dem Boden steht (Unterkante am Boden, Kulisse berührt, ``befestigt`` oder
  ``verbinde(…, boden)``): Er trägt die Stäbe wie ein festes Lager (vereinfacht: starr).
- **Anschlüsse** eines Stabs an einen anderen Stab, einen Starrkörper oder den Boden. Art aus den Zwangsbedingungen
  (Gelenk vor ``verbinde`` vor Berührung): fest (Schraube, Klemmung, Kleben, Formschluss,
  Steck, Berührung und Spiel: ein Rohr in einer Bohrung trägt über die Stecklänge auch Momente), gelenkig (Aufliegen),
  Drehgelenk, Schiebegelenk, Zylindergelenk. Gelenke mit ``bereich`` sind Einstellungen (Schlitten mit Klemme,
  Stange im Halter, Kopf): im Betrieb festgestellt, also fest (wie in Stufe 2, T15); frei sind nur Gelenke ohne
  ``bereich`` (Laufrolle auf der Achse).
- Starrkörper mit nur einem Anschluss an einen Stab sind **Anbauteile**: Ihr Gewicht und ihre Lasten gehen an diesen
  Anschluss.

Das Modell ist reine Daten (numpy) und taugt für S0, S1 und später S2/S3 (Naht in ``statik/__init__.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.statik.werkstoff import Querschnitt, Werkstoff, querschnitt, werkstoff, werkstoff_aus_eintrag

STANGEN = ("rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil", "nutprofil",
           "holz")
SCHLANK = 3.0  # Stab erst ab Länge ≥ 3 × größte Querschnittsabmessung
BODEN_TOL = 0.5
ZUSAMMEN_MM = 40.0  # Anschlüsse eines Stabs an denselben Partner näher als das: einer
VERBINDUNGSELEMENTE = ("schraube", "mutter", "scheibe")
# Rangfolge der Anschlussarten, wenn mehrere Quellen dasselbe Paar nennen
FEST_VERBINDE = ("schraube", "klemmung", "kleben", "formschluss", "steck")  # Steck: Rohr in Bohrung trägt Momente
GELENK_ART = {"drehgelenk": "dreh", "schiebegelenk": "schiebe", "zylindergelenk": "zylinder", "kugelgelenk": "gelenkig",
              "fest": "fest"}


@dataclass
class Teil:
    name: str
    masse_kg: float
    schwerpunkt: np.ndarray
    bmin: np.ndarray
    bmax: np.ndarray
    material_id: str | None = None
    werkstoff: Werkstoff | None = None
    art: str | None = None
    stock_id: str | None = None
    druckteil: bool = False
    druck_oben: np.ndarray | None = None  # Aufbaurichtung (Welt), None: unbekannt
    masse_angenommen: bool = False
    verbindungselement: bool = False
    gewinde_d: float | None = None

    @property
    def kurz(self) -> str:
        return self.name.rsplit("/", 1)[-1]


@dataclass
class Stab:
    name: str
    stock_id: str | None
    art: str
    masse: dict[str, Any]
    werkstoff: Werkstoff | None
    q: Querschnitt
    p0: np.ndarray
    p1: np.ndarray
    e_lang: np.ndarray
    masse_kg: float
    item: dict[str, Any] = field(default_factory=dict)
    material_id: str | None = None

    @property
    def achse(self) -> np.ndarray:
        d = self.p1 - self.p0
        return d / float(np.linalg.norm(d))

    @property
    def laenge(self) -> float:
        return float(np.linalg.norm(self.p1 - self.p0))

    def punkt(self, t: float) -> np.ndarray:
        return self.p0 + self.achse * float(t)

    def t_von(self, p: np.ndarray) -> float:
        return float(np.clip(np.dot(np.asarray(p, dtype=float) - self.p0, self.achse), 0.0, self.laenge))


@dataclass
class Starrkoerper:
    id: str
    teile: list[str]
    masse_kg: float
    schwerpunkt: np.ndarray
    geerdet: bool = False
    grund: str = ""


@dataclass
class Anschluss:
    stab: str
    t: float
    art: str  # fest | gelenkig | dreh | schiebe | zylinder
    partner: tuple  # ("stab", name, t) | ("koerper", id) | ("boden",)
    achse: np.ndarray | None = None
    teile: tuple[str, str] = ("", "")
    quelle: str = ""

    def kurz(self) -> dict[str, Any]:
        return {"stab": self.stab, "t": round(self.t, 1), "art": self.art, "partner": list(self.partner[:2]),
                "teile": list(self.teile), "quelle": self.quelle}


@dataclass
class StatikModell:
    teile: dict[str, Teil] = field(default_factory=dict)
    kulisse: set[str] = field(default_factory=set)
    staebe: dict[str, Stab] = field(default_factory=dict)
    koerper: dict[str, Starrkoerper] = field(default_factory=dict)
    teil_koerper: dict[str, str] = field(default_factory=dict)
    anschluesse: list[Anschluss] = field(default_factory=list)
    kanten: dict[frozenset, dict[str, Any]] = field(default_factory=dict)
    verbindungen: list[dict[str, Any]] = field(default_factory=list)  # verbinde(…) aus den Bedingungen
    boden_z: float = 0.0
    untergrund: str = "beton"
    gruppen: list[dict[str, Any]] = field(default_factory=list)  # Standsicherheit (pruefung/stand.py)
    rollend: set[str] = field(default_factory=set)  # Teile, die frei auf dem Boden rollen (Kugel, Walze)
    hinweise: list[str] = field(default_factory=list)
    ms: float = 0.0

    # -- Abfragen ------------------------------------------------------------------------------------------------------

    def koerper_von(self, teil: str) -> Starrkoerper | None:
        k = self.teil_koerper.get(teil)
        return self.koerper.get(k) if k else None

    def anschluesse_von(self, koerper_id: str) -> list[Anschluss]:
        return [a for a in self.anschluesse if a.partner[0] == "koerper" and a.partner[1] == koerper_id]

    def ist_anbau(self, koerper_id: str) -> bool:
        k = self.koerper.get(koerper_id)
        return k is not None and not k.geerdet and len(self.anschluesse_von(koerper_id)) == 1

    def passt(self, name: str, muster: str) -> bool:
        m = muster.strip()
        return name == m.rstrip("/") or name.startswith(m.rstrip("/") + "/")

    def aufloesen(self, muster: str) -> list[str]:
        """Teilnamen zu einem Namen oder einer Gruppe ("Kugelschieber/" oder "Kugelschieber")."""
        if muster in self.teile:
            return [muster]
        return [n for n in self.teile if self.passt(n, muster)]

    def kurz(self) -> dict[str, Any]:
        return {"staebe": len(self.staebe), "starrkoerper": sum(1 for k in self.koerper.values() if not k.geerdet),
                "geerdet": sum(1 for k in self.koerper.values() if k.geerdet),
                "anschluesse": len(self.anschluesse), "ms": round(self.ms, 1)}


# ---------------------------------------------------------------------------------------------------------------------
# Aufbau


class _UF:
    def __init__(self, namen: list[str]) -> None:
        self.p = {n: n for n in namen}

    def find(self, n: str) -> str:
        while self.p[n] != n:
            self.p[n] = self.p[self.p[n]]
            n = self.p[n]
        return n

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _bezug_name(b: Any) -> str | None:
    if b is None or getattr(b, "welt", False):
        return None
    return getattr(b, "teilname", None) or getattr(b, "per_name", None) or getattr(b, "label", None) or None


def _bedingungen(namen: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(verbinde, gelenke) aus den Zwangsbedingungen dieses Laufs; leer, wenn der Stand zu einem anderen Lauf gehört."""
    try:
        from kevcad_kernel.bedingungen import anbindung
        from kevcad_kernel.bedingungen.arten import Gelenk, Verbindung
    except Exception:  # noqa: BLE001
        return [], []
    st = anbindung.STAND
    s = st.sammlung
    if s is None or not getattr(s, "bedingungen", None):
        return [], []
    if namen and not namen <= set(st.formen) | {n for n in namen if n.startswith("Skizze/")}:
        return [], []
    verb, gel = [], []
    aufg = getattr(s, "aufgeloest", None) or {}
    for c in s.bedingungen:
        A, B = aufg.get(getattr(c, "id", None), (getattr(c, "a", None), getattr(c, "b", None)))
        a = _bezug_name(A) or _bezug_name(getattr(c, "a", None))
        b_welt = bool(getattr(B, "welt", False))
        b = None if b_welt else (_bezug_name(B) or _bezug_name(getattr(c, "b", None)))
        if isinstance(c, Verbindung):
            mit = [n for n in (_bezug_name(m) for m in getattr(c, "mit", []) or []) if n]
            verb.append({"a": a, "b": "boden" if b_welt else b, "art": c.verbindungsart, "mit": mit,
                         "zeile": getattr(c, "zeile", None)})
        elif isinstance(c, Gelenk):
            achse = getattr(B, "d", None) if B is not None else None
            if achse is None and A is not None:
                achse = getattr(A, "d", None)
            # für S2 (Dynamik): Punkt der Achse in der gezeigten Lage und Bereich (mit Bereich: Einstellgelenk)
            aw = getattr(c, "achse_welt", None)
            punkt = aw[0] if aw is not None else (getattr(B, "p", None) if B is not None else None)
            if aw is not None and achse is None:
                achse = aw[1]
            gel.append({"a": a, "b": b, "art": GELENK_ART.get(getattr(c, "art", ""), "fest"),
                        "achse": None if achse is None else np.asarray(achse, dtype=float),
                        "mitbewegt": [n for n in (x if isinstance(x, str) else _bezug_name(x)
                                                  for x in getattr(c, "mitbewegt", []) or []) if n],
                        "punkt": None if punkt is None else np.asarray(punkt, dtype=float),
                        "bereich": getattr(c, "bereich", None), "zeile": getattr(c, "zeile", None)})
    return verb, gel


def _hauptachse(pos: np.ndarray, zentrum: np.ndarray) -> tuple[np.ndarray, float, float, np.ndarray]:
    """(Richtung, t_min, t_max, Querrichtung der größten Ausdehnung) der Punkte um den Schwerpunkt."""
    P = np.asarray(pos, dtype=float)
    c = P.mean(axis=0)
    w, v = np.linalg.eigh(np.cov((P - c).T))
    d = v[:, int(np.argmax(w))]
    i = int(np.argmax(np.abs(d)))
    if d[i] < 0:
        d = -d
    t = (P - zentrum) @ d
    Q = (P - zentrum) - np.outer(t, d)
    w2, v2 = np.linalg.eigh(np.cov(Q.T))
    e = v2[:, int(np.argmax(w2))]
    e = e - d * float(np.dot(e, d))
    n = float(np.linalg.norm(e))
    if n < 1e-9:
        e = np.cross(d, [0, 0, 1.0]) if abs(d[2]) < 0.9 else np.cross(d, [1.0, 0, 0])
        n = float(np.linalg.norm(e))
    return d, float(t.min()), float(t.max()), e / n


def _segment_naechste(p0: np.ndarray, p1: np.ndarray, q0: np.ndarray, q1: np.ndarray) -> tuple[float, float, float]:
    """Nächste Punkte zweier Strecken: (s in [0, 1] auf p, t in [0, 1] auf q, Abstand)."""
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = float(d1 @ d1), float(d2 @ d2), float(d2 @ r)
    c, b = float(d1 @ r), float(d1 @ d2)
    den = a * e - b * b
    s = float(np.clip((b * f - c * e) / den, 0, 1)) if den > 1e-12 else 0.0
    t = (b * s + f) / e if e > 1e-12 else 0.0
    if t < 0:
        t, s = 0.0, float(np.clip(-c / a, 0, 1))
    elif t > 1:
        t, s = 1.0, float(np.clip((b - c) / a, 0, 1))
    dist = float(np.linalg.norm((p0 + d1 * s) - (q0 + d2 * t)))
    return s, t, dist


def _ueberlapp_mitte(a_min: np.ndarray, a_max: np.ndarray, b_min: np.ndarray, b_max: np.ndarray) -> np.ndarray:
    lo, hi = np.maximum(a_min, b_min), np.minimum(a_max, b_max)
    m = (lo + hi) / 2
    # trennen sich die Hüllquader (Berührung mit Spiel), liegt die Mitte zwischen ihnen
    return m


def _druck_oben(name: str, k: Any, druck: dict[str, Any]) -> np.ndarray | None:
    t = (druck.get("teile") or {}).get(name)
    if not t:
        return None
    unten = (t.get("ausrichtung") or {}).get("unten")
    if unten is None:
        return None
    lage = np.asarray(k.lage, dtype=float).reshape(4, 4)
    rahmen = k.info.get("druck_rahmen")
    R = np.asarray(rahmen, dtype=float).reshape(4, 4)[:3, :3] if rahmen is not None else lage[:3, :3]
    d = lage[:3, :3] @ (R.T @ np.asarray(unten, dtype=float))
    n = float(np.linalg.norm(d))
    return -d / n if n > 1e-9 else None


def baue(koerper: dict[str, Any], paare: dict[frozenset, Any], erklaerungen: dict[str, Any], stand: dict[str, Any],
         druck: dict[str, Any] | None, katalog: Any, befestigt: dict[str, str] | None = None,
         untergrund: str | None = None) -> StatikModell:
    """Statikmodell aus den Körpern und Kontakten der Prüfung (``PruefKontext``)."""
    import time

    from kevcad_kernel.pruefung.befund import DICHTE_ANNAHME

    t0 = time.perf_counter()
    m = StatikModell()
    m.boden_z = float((stand or {}).get("boden_z") or 0.0)
    m.gruppen = list((stand or {}).get("gruppen") or [])
    m.untergrund = untergrund or "beton"
    druck = druck or {}
    befestigt = befestigt or {}

    # Teile -----------------------------------------------------------------------------------------------------------
    for name, k in koerper.items():
        if k.kulisse:
            m.kulisse.add(name)
            continue
        if k.masse_g is not None:
            masse, ann = float(k.masse_g) / 1000.0, False
        else:
            masse, ann = k.volumen * DICHTE_ANNAHME * 1e-6, True
        mid = k.info.get("material_id") or k.info.get("druck_material")
        w = werkstoff(katalog, mid) if mid else None
        if w is None and k.info.get("material"):
            w = werkstoff(katalog, k.info.get("material"))
        d = k.info.get("d")
        if d is None and k.art in ("zukaufteil", None):
            from kevcad_kernel import gewinde as gw

            g = gw.aus_text(name.rsplit("/", 1)[-1])
            d = g.d if g is not None else None
        m.teile[name] = Teil(name, masse, np.asarray(k.zentrum, dtype=float), np.asarray(k.bmin, dtype=float),
                             np.asarray(k.bmax, dtype=float), mid, w, k.art, k.info.get("stock_id"),
                             bool(k.info.get("druckteil")),
                             _druck_oben(name, k, druck) if k.info.get("druckteil") else None, ann,
                             k.ist_verbindungselement or "gewindeeinsatz" in name.lower()
                             or "schraube" in name.lower(), float(d) if d else None)

    # Stäbe -----------------------------------------------------------------------------------------------------------
    for name, k in koerper.items():
        if name in m.kulisse or k.art not in STANGEN or len(k.pos) < 4:
            continue
        item = katalog.item(k.info.get("stock_id")) if katalog is not None and k.info.get("stock_id") else None
        if not item:
            continue
        try:
            q = querschnitt(item["art"], item.get("masse") or {})
        except Exception as exc:  # noqa: BLE001
            m.hinweise.append(f"{name}: Querschnitt nicht berechnet ({type(exc).__name__}: {exc})")
            continue
        d, tmin, tmax, e_lang = _hauptachse(k.pos, np.asarray(k.zentrum, dtype=float))
        L = tmax - tmin
        if L < SCHLANK * 2 * q.radius:
            continue
        mat = None
        if katalog is not None and item.get("material"):
            mat = katalog.material(item["material"])
        w = werkstoff_aus_eintrag(mat) or m.teile[name].werkstoff
        if w is None:
            m.hinweise.append(f"{name}: Material {item.get('material')!r} ohne Mechanikdaten im Katalog, als Stab nicht "
                              "gerechnet")
            continue
        z = np.asarray(k.zentrum, dtype=float)
        m.staebe[name] = Stab(name, k.info.get("stock_id"), item["art"], dict(item.get("masse") or {}), w, q,
                              z + d * tmin, z + d * tmax, e_lang, m.teile[name].masse_kg, item, item.get("material"))

    # Kanten aus Kontakten und Bedingungen ----------------------------------------------------------------------------
    alle = set(m.teile) | m.kulisse

    def kante(a: str, b: str) -> dict[str, Any]:
        key = frozenset((a, b))
        e = m.kanten.get(key)
        if e is None:
            e = m.kanten[key] = {"a": a, "b": b, "kontakt": None, "verbinde": None, "gelenk": None, "achse": None}
        return e

    for key, p in (paare or {}).items():
        if not (p.kontakt or p.durchdringt):
            continue
        if p.a in alle and p.b in alle:
            kante(p.a, p.b)["kontakt"] = p.art
    verb, gel = _bedingungen(set(koerper))
    boden_teile = set()
    for v in verb:
        a, b = v["a"], v["b"]
        if a not in alle:
            continue
        m.verbindungen.append(v)
        if b == "boden":
            boden_teile.add(a)
            continue
        if b in alle:
            kante(a, b)["verbinde"] = v["art"]
        for f in v["mit"]:
            if f in alle:
                kante(f, a)["verbinde"] = kante(f, a)["verbinde"] or v["art"]
                if b in alle:
                    kante(f, b)["verbinde"] = kante(f, b)["verbinde"] or v["art"]
    for g in gel:
        a, b = g["a"], g["b"]
        if a in alle and b in alle:
            e = kante(a, b)
            e["gelenk"], e["achse"] = g["art"], g["achse"]
            e["festgestellt"] = g.get("bereich") is not None  # Einstellgelenk: im Betrieb geklemmt (T15, T30)

    # Starrkörper -----------------------------------------------------------------------------------------------------
    nicht = [n for n in m.teile if n not in m.staebe]
    uf = _UF(nicht)
    for e in m.kanten.values():
        a, b = e["a"], e["b"]
        if a in uf.p and b in uf.p:
            if e["verbinde"] or e["gelenk"] or e["kontakt"] in ("beruehrt", "durchdringt"):
                uf.union(a, b)
    gruppen: dict[str, list[str]] = {}
    for n in nicht:
        gruppen.setdefault(uf.find(n), []).append(n)
    am_kulisse = {e["a"] if e["b"] in m.kulisse else e["b"] for e in m.kanten.values()
                  if (e["a"] in m.kulisse) != (e["b"] in m.kulisse)}
    for i, (_, teile) in enumerate(sorted(gruppen.items(), key=lambda kv: (-len(kv[1]), kv[1][0])), 1):
        masse = sum(m.teile[n].masse_kg for n in teile)
        sp = (sum(m.teile[n].masse_kg * m.teile[n].schwerpunkt for n in teile) / masse if masse > 0
              else np.mean([m.teile[n].schwerpunkt for n in teile], axis=0))
        grund = ""
        for n in teile:
            if n in am_kulisse:
                grund = f"{n} steht auf der Kulisse"
            elif n in boden_teile:
                grund = f"{n}: verbinde(…, boden)"
            elif n in befestigt:
                grund = f"{n} befestigt: {befestigt[n]}"
            elif m.teile[n].bmin[2] <= m.boden_z + BODEN_TOL:
                grund = f"{n} steht auf dem Boden"
            if grund:
                break
        kid = f"K{i}"
        m.koerper[kid] = Starrkoerper(kid, sorted(teile), masse, np.asarray(sp, dtype=float), bool(grund), grund)
        for n in teile:
            m.teil_koerper[n] = kid

    # Anschlüsse der Stäbe --------------------------------------------------------------------------------------------
    roh: list[Anschluss] = []
    for e in m.kanten.values():
        a, b = e["a"], e["b"]
        for s_name, x in ((a, b), (b, a)):
            s = m.staebe.get(s_name)
            if s is None:
                continue
            art, quelle = _art(e)
            if x in m.staebe:
                if s_name > x:  # Stab-Stab nur einmal
                    continue
                o = m.staebe[x]
                u, v, _ = _segment_naechste(s.p0, s.p1, o.p0, o.p1)
                roh.append(Anschluss(s_name, u * s.laenge, art, ("stab", x, v * o.laenge), e["achse"], (s_name, x),
                                     quelle))
                continue
            if x in m.kulisse:
                mitte = _ueberlapp_mitte(np.asarray(koerper[s_name].bmin), np.asarray(koerper[s_name].bmax),
                                         np.asarray(koerper[x].bmin), np.asarray(koerper[x].bmax))
                roh.append(Anschluss(s_name, s.t_von(mitte), "gelenkig" if art == "fest" else art, ("boden",),
                                     e["achse"], (s_name, x), "steht auf der Kulisse"))
                continue
            kid = m.teil_koerper.get(x)
            if kid is None:
                continue
            mitte = _ueberlapp_mitte(np.asarray(koerper[s_name].bmin), np.asarray(koerper[s_name].bmax),
                                     np.asarray(koerper[x].bmin), np.asarray(koerper[x].bmax))
            roh.append(Anschluss(s_name, s.t_von(mitte), art, ("koerper", kid), e["achse"], (s_name, x), quelle))
    # Stäbe, die selbst befestigt sind (befestigt(…) oder verbinde(…, boden)): fest eingespannt an beiden Enden
    for s in m.staebe.values():
        grund = befestigt.get(s.name) or ("verbinde(…, boden)" if s.name in boden_teile else None)
        if grund:
            for t in (0.0, s.laenge):
                roh.append(Anschluss(s.name, t, "fest", ("boden",), None, (s.name, "Umgebung"),
                                     f"befestigt: {grund}"))
    # Stäbe direkt auf dem Boden (ohne Kulisse)
    for s in m.staebe.values():
        if any(a.stab == s.name and a.partner[0] == "boden" for a in roh):
            continue
        if m.teile[s.name].bmin[2] <= m.boden_z + BODEN_TOL:
            if abs(float(s.p0[2]) - float(s.p1[2])) < 2 * s.q.radius:  # liegt: an beiden Enden
                for t in (0.0, s.laenge):
                    roh.append(Anschluss(s.name, t, "gelenkig", ("boden",), None, (s.name, "Boden"), "liegt auf"))
            else:
                t = 0.0 if float(s.p0[2]) <= float(s.p1[2]) else s.laenge
                roh.append(Anschluss(s.name, t, "gelenkig", ("boden",), None, (s.name, "Boden"), "steht auf"))
    m.anschluesse = _zusammenfassen(roh)
    m.rollend = {n for n in m.teile if rollend(m, koerper, n)}
    # Anschlüsse an geerdete Starrkörper sind Auflager
    for a in m.anschluesse:
        if a.partner[0] == "koerper" and m.koerper[a.partner[1]].geerdet:
            a.quelle = (a.quelle + "; " if a.quelle else "") + "Lager (steht auf dem Boden, starr angenommen)"
    m.ms = (time.perf_counter() - t0) * 1000
    return m


RANG = {"dreh": 5, "schiebe": 5, "zylinder": 5, "fest": 3, "gelenkig": 1}


def _art(e: dict[str, Any]) -> tuple[str, str]:
    if e.get("gelenk"):
        if e.get("festgestellt") and e["gelenk"] != "fest":
            # Gelenk mit Bereich: Einstellung, die im Betrieb geklemmt ist (Schlitten, Stange im Halter). Frei
            # gerechnet liefe die ganze Kraft längs der Führung über das andere Gegenstück (T30).
            return "fest", f"Gelenk ({e['gelenk']}) mit Bereich: festgestellt"
        return e["gelenk"], f"Gelenk ({e['gelenk']})"
    v = e.get("verbinde")
    if v:
        return ("fest" if v in FEST_VERBINDE else "gelenkig"), f"verbinde {v}"
    k = e.get("kontakt")
    if k in ("beruehrt", "durchdringt"):
        return "fest", f"Kontakt ({k})"
    return "fest", "Kontakt mit Spiel (gesteckt)"


def _zusammenfassen(roh: list[Anschluss]) -> list[Anschluss]:
    """Anschlüsse desselben Stabs an denselben Partner, die nah beieinander liegen, zu einem (stärkste Art)."""
    out: list[Anschluss] = []
    gruppiert: dict[tuple, list[Anschluss]] = {}
    for a in roh:
        key = (a.stab, a.partner[0], a.partner[1] if len(a.partner) > 1 else None)
        gruppiert.setdefault(key, []).append(a)
    for liste in gruppiert.values():
        liste.sort(key=lambda a: a.t)
        cluster: list[list[Anschluss]] = []
        for a in liste:
            if cluster and a.t - cluster[-1][-1].t <= ZUSAMMEN_MM:
                cluster[-1].append(a)
            else:
                cluster.append([a])
        for c in cluster:
            best = max(c, key=lambda a: (RANG.get(a.art, 0), a.quelle.startswith("Gelenk")))
            t = float(np.mean([a.t for a in c]))
            partner = best.partner
            if partner[0] == "stab":
                partner = ("stab", partner[1], float(np.mean([a.partner[2] for a in c if a.partner[0] == "stab"])))
            out.append(Anschluss(best.stab, t, best.art, partner, best.achse, best.teile,
                                 best.quelle + (f" ({len(c)} Berührungen)" if len(c) > 1 else "")))
    out.sort(key=lambda a: (a.stab, a.t))
    return out


def rollend(m: StatikModell, koerper: dict[str, Any], name: str) -> bool:
    """Rollt das Teil frei auf dem Boden (Kugel, Walze): Bodenberührung winzig gegen seine Grundfläche, kein Rad mit
    Namen (Räder gelten als gebremst)."""
    from kevcad_kernel.statik.szenario import RAD_WORTE

    t = m.teile.get(name)
    k = koerper.get(name)
    if t is None or k is None or t.bmin[2] > m.boden_z + BODEN_TOL:
        return False
    if any(w in name.lower() for w in RAD_WORTE):
        return False
    P = np.asarray(k.pos, dtype=float)
    unten = P[P[:, 2] <= m.boden_z + BODEN_TOL + 1.0]
    breite = float(np.min((t.bmax - t.bmin)[:2]))
    if len(unten) == 0:
        return True
    ausdehnung = float(np.max(np.ptp(unten[:, :2], axis=0)))
    return ausdehnung < 0.15 * breite


def auf_rollen(m: StatikModell) -> bool:
    """Steht das Modell auf Rädern oder Rollen (Teile am Boden mit Rad/Rolle im Namen)?"""
    from kevcad_kernel.statik.szenario import RAD_WORTE

    an_kulisse = _am_kulisse(m)
    for n, t in m.teile.items():
        if t.bmin[2] <= m.boden_z + BODEN_TOL or n in an_kulisse:
            kurz = n.lower()
            if any(w in kurz for w in RAD_WORTE):
                return True
    return False


def _am_kulisse(m: StatikModell) -> set[str]:
    return {e["a"] if e["b"] in m.kulisse else e["b"] for e in m.kanten.values()
            if (e["a"] in m.kulisse) != (e["b"] in m.kulisse)}


def oberste_teile(m: StatikModell, toleranz: float = 5.0) -> list[tuple[str, np.ndarray]]:
    """Teile, deren Oberkante höchstens ``toleranz`` unter der höchsten liegt (ohne Verbindungselemente): Ort der
    Nutzlast im Standardszenario, je Teil die Mitte der Oberseite."""
    kand = [t for t in m.teile.values() if not t.verbindungselement]
    if not kand:
        return []
    top = max(float(t.bmax[2]) for t in kand)
    out = []
    for t in kand:
        if float(t.bmax[2]) >= top - toleranz:
            out.append((t.name, np.array([(t.bmin[0] + t.bmax[0]) / 2, (t.bmin[1] + t.bmax[1]) / 2, t.bmax[2]])))
    return out

