"""Lasten und Lager aus ``simulation.json`` (und ``st.lager`` aus model.py) dem aktuellen Modell zuordnen, im
Rechenprozess nach jedem Lauf (``statik/anbindung.py``) und nach jeder Änderung in der App.

Bezug ist der **Teilname** aus ``show()`` und die **Fläche** (Nummer wie im Viewer, ``signatur`` wie
``PART_UPSERT.faces[i]``: Typ, Inhalt, Normale bzw. Achse, Mittelpunkt, Radius). Nach einer Modelländerung:

1. Passt die Fläche mit derselben Nummer noch (gleicher Typ, Normale bis 2°, Mitte bis 1 % der Teilgröße, Inhalt bis
   3 %), bleibt alles, wie es war (``ok``).
2. Sonst wird unter den Flächen desselben Typs die ähnlichste gesucht (Normale bzw. Achse bis 12°, Radius bis ±40 %,
   Mitte höchstens 30 % der Teilgröße bzw. 15 mm entfernt): ``neu`` mit Text „Fläche 12 → 15“. Der Angriffspunkt
   wandert mit der Fläche, eine Kraft „entlang der Normale“ dreht mit.
3. Findet sich nichts, ist die Last bzw. das Lager **nicht mehr zuordenbar** (``fehlt``): sie zählt nicht mit, bleibt
   aber in der Datei und in der App sichtbar (rot), bis Kevin sie neu setzt oder löscht.

Ein Teil, das es nicht mehr gibt, wird über den letzten Namensteil gesucht (Teil in eine Gruppe verschoben), sonst
``fehlt``. Ergebnis: ``Vorbereitet`` mit den Szenarien der App (Wörterbücher für ``szenario.szenario_aus``), den
aufgelösten Lagern (Punkt, Normale, Netz der Lagerfläche in Weltlage für Festkörper und Topologie), den ausgeschalteten
abgeleiteten Lagern und dem Zustand je Last, Lager und Schutzfläche für die App (``SIM``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.simulation import kraft as kr

WINKEL_GLEICH = 2.0
WINKEL_SUCHE = 12.0
MITTE_GLEICH = 0.01
FLAECHE_GLEICH = 0.03
MITTE_SUCHE = 0.30
MITTE_SUCHE_MIN = 15.0
PUNKT_TOL = 3.0  # mm: ein Punkt ohne Fläche muss so nah an der Oberfläche liegen
LAGER_RADIUS = (0.05, 3.0, 15.0)  # Punktlager: Anteil der Teilgröße, mindestens, höchstens (mm)


@dataclass
class Lager:
    """Ein Lager im Statikmodell (aus der App oder aus ``st.lager``)."""

    id: str
    teil: str
    art: str  # fest | gelenkig | gleitend
    quelle: str  # app | modell
    punkt: np.ndarray | None = None
    normale: np.ndarray | None = None
    flaeche: int | None = None
    netz: tuple[np.ndarray, np.ndarray] | None = None  # Lagerfläche (Welt): Punkte, Dreiecke
    zeile: int | None = None
    auf: str = "flaeche"  # flaeche | punkt | teil

    @property
    def name(self) -> str:
        """Name als Nachbar im Bauteil-Nachweis und in der FEM."""
        return f"Lager: {self.id}"

    @property
    def komponenten(self) -> list[int] | None:
        """Gehaltene Richtungen (0 = x, 1 = y, 2 = z) eines gleitenden Lagers: nur senkrecht zur Fläche, auf die
        nächste Weltachse gerundet; None = alle (fest, gelenkig)."""
        if self.art != "gleitend" or self.normale is None:
            return None
        return [int(np.argmax(np.abs(self.normale)))]

    def kurz(self) -> dict[str, Any]:
        return {"id": self.id, "teil": self.teil, "art": self.art, "quelle": self.quelle, "flaeche": self.flaeche,
                "punkt": None if self.punkt is None else [round(float(c), 2) for c in self.punkt],
                "normale": None if self.normale is None else [round(float(c), 4) for c in self.normale],
                "zeile": self.zeile, "auf": self.auf}


@dataclass
class Vorbereitet:
    szenarien: list[dict[str, Any]] = field(default_factory=list)  # für szenario_aus (quelle "app")
    lager: list[Lager] = field(default_factory=list)
    aus: set[str] = field(default_factory=set)  # ausgeschaltete abgeleitete Lager (boden:…, kontakt:…)
    zustand: dict[str, Any] = field(default_factory=dict)  # für SIM: lasten, lager, schutz je id
    hinweise: list[str] = field(default_factory=list)
    signaturen: dict[str, dict[str, Any]] = field(default_factory=dict)  # nachgetragen: id → signatur
    topologie: dict[str, Any] = field(default_factory=dict)
    stand: int = 0
    fehler: str | None = None


# ---------------------------------------------------------------------------------------------------------------------
# Flächen


def _winkel(a: Any, b: Any) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b) / (na * nb)))))


def _achswinkel(a: Any, b: Any) -> float:
    w = _winkel(a, b)
    return min(w, 180.0 - w)


def _groesse(k: Any) -> float:
    return float(np.max(np.asarray(k.bmax) - np.asarray(k.bmin))) or 1.0


def _gleich(f: dict[str, Any], sig: dict[str, Any], groesse: float) -> bool:
    if f.get("t") != sig.get("t"):
        return False
    if sig.get("n") is not None and (f.get("n") is None or _winkel(f["n"], sig["n"]) > WINKEL_GLEICH):
        return False
    if sig.get("ax") is not None and (f.get("ax") is None or _achswinkel(f["ax"], sig["ax"]) > WINKEL_GLEICH):
        return False
    if sig.get("c") is not None and f.get("c") is not None:
        if float(np.linalg.norm(np.asarray(f["c"], float) - np.asarray(sig["c"], float))) > max(
                1.0, MITTE_GLEICH * groesse):
            return False
    if sig.get("a") and f.get("a"):
        if abs(float(f["a"]) - float(sig["a"])) > FLAECHE_GLEICH * float(sig["a"]) + 0.5:
            return False
    if sig.get("r") and f.get("r") and abs(float(f["r"]) - float(sig["r"])) > 0.02 * float(sig["r"]) + 0.05:
        return False
    return True


def _abstand(f: dict[str, Any], sig: dict[str, Any], groesse: float) -> float | None:
    """Wie unähnlich (kleiner ist besser), None = kommt nicht in Frage."""
    if f.get("t") != sig.get("t"):
        return None
    w = 0.0
    if sig.get("n") is not None:
        if f.get("n") is None:
            return None
        w = _winkel(f["n"], sig["n"])
    elif sig.get("ax") is not None:
        if f.get("ax") is None:
            return None
        w = _achswinkel(f["ax"], sig["ax"])
    if w > WINKEL_SUCHE:
        return None
    if sig.get("r") and f.get("r"):
        q = float(f["r"]) / float(sig["r"])
        if not 0.6 <= q <= 1.4:
            return None
    d = 0.0
    if sig.get("c") is not None and f.get("c") is not None:
        d = float(np.linalg.norm(np.asarray(f["c"], float) - np.asarray(sig["c"], float)))
        if d > max(MITTE_SUCHE_MIN, MITTE_SUCHE * groesse):
            return None
    fl = 0.0
    if sig.get("a") and f.get("a"):
        fl = abs(math.log(max(float(f["a"]), 1e-9) / max(float(sig["a"]), 1e-9)))
    return d / groesse + w / 90.0 + 0.3 * fl


def flaeche_suchen(k: Any, index: int | None, sig: dict[str, Any] | None) -> tuple[int | None, str, str]:
    """(Nummer, Zustand ``ok`` | ``neu`` | ``fehlt``, Text) der Fläche im aktuellen Teil."""
    faces = list(getattr(k, "flaechen", None) or [])
    if index is None and sig is None:
        return None, "ok", ""
    g = _groesse(k)
    if sig is None:  # ohne Signatur: die Nummer zählt (vom Agenten); Signatur wird nachgetragen
        if index is not None and index < len(faces):
            return index, "ok", ""
        return None, "fehlt", f"Fläche {index} gibt es nicht (das Teil hat {len(faces)} Flächen)"
    if index is not None and index < len(faces) and _gleich(faces[index], sig, g):
        return index, "ok", ""
    beste: tuple[float, int] | None = None
    for i, f in enumerate(faces):
        s = _abstand(f, sig, g)
        if s is not None and (beste is None or s < beste[0]):
            beste = (s, i)
    if beste is None:
        art = {"plane": "Ebene", "cylinder": "Zylinder", "cone": "Kegel", "sphere": "Kugel", "torus": "Torus"}.get(
            str(sig.get("t")), str(sig.get("t")))
        was = f"Fläche {index}" if index is not None else "Die Fläche"
        return None, "fehlt", f"{was} ({art}, {float(sig.get('a') or 0):.0f} mm²) passt zu keiner Fläche des Teils mehr"
    i = beste[1]
    if index is None or i == index:  # dieselbe Fläche, nur verschoben oder größer: der Punkt wandert mit
        return i, "ok", ""
    return i, "neu", f"Fläche {index} → {i}"


def _verschiebe(punkt: Any, alt: dict[str, Any] | None, neu: dict[str, Any] | None) -> np.ndarray | None:
    if punkt is None:
        return None
    p = np.asarray(punkt, float)
    if not alt or not neu or alt.get("c") is None or neu.get("c") is None:
        return p
    q = p + np.asarray(neu["c"], float) - np.asarray(alt["c"], float)
    if neu.get("n") is not None:  # auf die Ebene der neuen Fläche
        n = np.asarray(neu["n"], float)
        n = n / max(float(np.linalg.norm(n)), 1e-12)
        q = q - n * float((q - np.asarray(neu["c"], float)) @ n)
    return q


def _normale(f: dict[str, Any] | None, punkt: np.ndarray | None, alt: Any) -> np.ndarray | None:
    """Normale (nach außen) einer Fläche am Punkt: Ebene aus ``n``; Zylinder radial von der Achse; sonst die alte."""
    if f is not None and f.get("n") is not None:
        return kr.einheit(f["n"])
    if f is not None and f.get("t") == "cylinder" and f.get("ax") is not None and f.get("c") is not None \
            and punkt is not None:
        ax = kr.einheit(f["ax"])
        r = punkt - np.asarray(f["c"], float)
        r = r - ax * float(r @ ax)
        if float(np.linalg.norm(r)) > 1e-9:
            return r / float(np.linalg.norm(r))
    return None if alt is None else kr.einheit(alt)


def _face_shapes(shape: Any) -> list[Any]:
    """Flächen in der Reihenfolge von ``part.faces()`` (build123d: TopExp ohne Doppelte)."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    out: dict[int, Any] = {}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        out.setdefault(hash(ex.Current()), ex.Current())
        ex.Next()
    return list(out.values())


def flaechen_netz(k: Any, index: int) -> tuple[np.ndarray, np.ndarray] | None:
    """Dreiecke einer Fläche des Teils in Weltlage (für die Lagerfläche in FEM und Topologie)."""
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopAbs import TopAbs_REVERSED
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS

        faces = _face_shapes(k.shape)
        if not 0 <= index < len(faces):
            return None
        f = TopoDS.Face_s(faces[index]) if hasattr(TopoDS, "Face_s") else TopoDS.Face(faces[index])
        loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is None:
            BRepMesh_IncrementalMesh(f, 0.1, False, 0.3, True)
            t = BRep_Tool.Triangulation_s(f, loc)
        if t is None:
            return None
        trsf = loc.Transformation()
        p = np.array([(lambda q: (q.X(), q.Y(), q.Z()))(t.Node(i).Transformed(trsf)) for i in
                      range(1, t.NbNodes() + 1)], dtype=np.float64)
        d = np.array([t.Triangle(i).Get() for i in range(1, t.NbTriangles() + 1)], dtype=np.int64) - 1
        if f.Orientation() == TopAbs_REVERSED:
            d = d[:, [0, 2, 1]]
        return p, d
    except Exception:  # noqa: BLE001 - ohne Netz bleibt das Lager im Stabwerk und im Bauteil-Nachweis
        return None


def punkt_netz(k: Any, punkt: np.ndarray, index: int | None) -> tuple[np.ndarray, np.ndarray] | None:
    """Kleine Lagerfläche um einen Punkt: die Dreiecke der Fläche (sonst des Teils) im Umkreis r."""
    netz = flaechen_netz(k, index) if index is not None else None
    if netz is None:
        netz = (np.asarray(k.pos, float), np.asarray(k.tri, np.int64))
    P, T = netz
    if len(T) == 0:
        return None
    anteil, rmin, rmax = LAGER_RADIUS
    r = min(max(anteil * _groesse(k), rmin), rmax)
    for _ in range(4):
        m = P[T].mean(axis=1)
        sel = np.linalg.norm(m - punkt[None, :], axis=1) <= r
        if sel.sum() >= 2:
            return P, T[sel]
        r *= 2
    j = int(np.argmin(np.linalg.norm(P[T].mean(axis=1) - punkt[None, :], axis=1)))
    return P, T[j:j + 1]


def _teil_suchen(teil: str, koerper: dict[str, Any]) -> tuple[str | None, str, str]:
    if teil in koerper:
        return teil, "ok", ""
    praefix = teil.rstrip("/") + "/"
    if any(n.startswith(praefix) for n in koerper):
        return teil, "ok", ""  # Gruppe
    kurz = teil.rsplit("/", 1)[-1]
    treffer = [n for n in koerper if n.rsplit("/", 1)[-1] == kurz]
    if len(treffer) == 1:
        return treffer[0], "neu", f"Teil heißt jetzt {treffer[0]}"
    import difflib

    tips = difflib.get_close_matches(teil, list(koerper), n=2, cutoff=0.6)
    return None, "fehlt", f"Teil {teil!r} gibt es nicht mehr" + (f" (ähnlich: {', '.join(tips)})" if tips else "")


def ort_aufloesen(ort: dict[str, Any] | None, teil: str, koerper: dict[str, Any]) -> dict[str, Any]:
    """Teil, Fläche, Punkt und Normale im aktuellen Modell: {"teil", "flaeche", "punkt", "normale", "zustand",
    "text", "signatur" (aktuelle Fläche)}."""
    ort = dict(ort or {})
    name, zustand, text = _teil_suchen(teil, koerper)
    out: dict[str, Any] = {"teil": name, "flaeche": None, "punkt": None, "normale": None, "zustand": zustand,
                           "text": text, "signatur": None}
    if name is None:
        return out
    k = koerper.get(name)
    punkt = np.asarray(ort["punkt"], float) if ort.get("punkt") is not None else None
    if k is None:  # Gruppe: kein Flächenbezug
        out["punkt"] = punkt
        return out
    faces = list(getattr(k, "flaechen", None) or [])
    if ort.get("flaeche") is not None or ort.get("signatur"):
        idx, z2, t2 = flaeche_suchen(k, ort.get("flaeche"), ort.get("signatur"))
        if z2 == "fehlt":
            return {**out, "zustand": "fehlt", "text": t2}
        f = faces[idx] if idx is not None and idx < len(faces) else None
        punkt = _verschiebe(punkt, ort.get("signatur"), f)
        if punkt is None and f is not None and f.get("c") is not None:
            punkt = np.asarray(f["c"], float)
            if f.get("t") == "cylinder" and f.get("r") and ort.get("normale") is not None:
                punkt = punkt + kr.einheit(ort["normale"]) * float(f["r"])
        out.update({"flaeche": idx, "punkt": punkt, "normale": _normale(f, punkt, ort.get("normale")),
                    "signatur": f})
        if z2 == "neu":
            out["zustand"] = "neu"
            out["text"] = "; ".join(t for t in (text, t2) if t)
        return out
    if punkt is not None:
        # Punkt ohne Fläche (etwa auf der Achse eines Stabs): im Hüllquader des Teils bzw. dicht an seiner Oberfläche
        innen = bool(np.all(punkt >= np.asarray(k.bmin) - PUNKT_TOL) and np.all(punkt <= np.asarray(k.bmax) + PUNKT_TOL))
        if not innen:
            return {**out, "zustand": "fehlt", "text": "Der Punkt liegt nicht mehr am Teil"}
        out["punkt"] = punkt
        out["normale"] = None if ort.get("normale") is None else kr.einheit(ort["normale"])
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Dokument → Szenarien und Lager


def _szenario_dict(l: dict[str, Any], lasten: list[dict[str, Any]], ziel_global: dict[str, Any]) -> dict[str, Any]:
    sz: dict[str, Any] = {"name": l["name"], "beschreibung": l.get("beschreibung") or "",
                          "dynamisch": l.get("art") == "dynamisch", "lasten": lasten}
    if l.get("beschleunigung"):
        sz["beschleunigung"] = list(l["beschleunigung"])
    if l.get("neigung"):
        sz["neigung"] = {"grad": float(l["neigung"]["grad"]), "richtung": l["neigung"].get("richtung") or "+x"}
    if l.get("stoss"):
        sz["stoss"] = {"faktor": float(l["stoss"])}
    z = dict(l.get("ziel") or {})
    if z.get("sicherheit"):
        sz["ziel"] = float(z["sicherheit"])
    elif ziel_global.get("sicherheit"):
        from kevcad_kernel.statik.szenario import ZIEL_DYNAMISCH, ZIEL_STATISCH

        sz["ziel"] = float(ziel_global["sicherheit"]) * (ZIEL_DYNAMISCH / ZIEL_STATISCH
                                                          if l.get("art") == "dynamisch" else 1.0)
    db = z.get("durchbiegung") or ziel_global.get("durchbiegung")
    if db:
        sz["durchbiegung"] = f"L/{str(db).replace('L/', '')}"
    if l.get("untergrund"):
        sz["untergrund"] = str(l["untergrund"])
    f = l.get("fahrt")
    if f:
        sz["ablauf"] = {k: f.get(k) for k in ("geschwindigkeit", "bremsen", "dauer", "animation", "antrieb",
                                              "angriff", "fahrtrichtung") if f.get(k) is not None}
        sz["dynamisch"] = True
    return sz


def vorbereiten(doc: dict[str, Any], koerper: dict[str, Any], modell_lager: list[dict[str, Any]] | None = None,
                ziel_global: dict[str, Any] | None = None) -> Vorbereitet:
    """Szenarien und Lager der App (und Lager aus model.py) für den aktuellen Stand des Modells."""
    v = Vorbereitet(aus=set(str(x) for x in doc.get("abgeleitet_aus") or []), stand=int(doc.get("stand") or 0),
                    fehler=doc.get("fehler"), topologie=dict(doc.get("topologie") or {}))
    zl: dict[str, Any] = {}
    zg = dict(ziel_global or {})
    for l in doc.get("lastfaelle") or []:
        lasten = []
        for x in l.get("lasten") or []:
            lid = str(x.get("id") or "")
            o = ort_aufloesen(x.get("ort"), str(x.get("teil")), koerper)
            eintrag: dict[str, Any] = {"lastfall": l["name"], "zustand": o["zustand"], "text": o["text"],
                                       "teil": o["teil"], "flaeche": o["flaeche"]}
            gegen = x.get("gegen")
            if gegen:
                g, gz, gt = _teil_suchen(str(gegen), koerper)
                if g is None:
                    o["zustand"], o["text"] = "fehlt", f"Gegenstück: {gt}"
                    eintrag.update(zustand="fehlt", text=o["text"])
                gegen = g
            if o["zustand"] == "fehlt":
                zl[lid] = eintrag
                continue
            try:
                F = kr.kraft_aus(x.get("richtung"), x.get("betrag"), str(x.get("einheit") or "N"), o["normale"])
            except kr.KraftFehler as exc:
                zl[lid] = {**eintrag, "zustand": "fehlt", "text": str(exc)}
                continue
            if x.get("ort", {}).get("signatur") is None and o.get("signatur") is not None:
                v.signaturen[lid] = dict(o["signatur"])
            unten = abs(float(F[0])) < 1e-9 and abs(float(F[1])) < 1e-9 and float(F[2]) < 0
            last = {"teile": [o["teil"]], "kraft": [float(c) for c in F],
                    "punkt": None if o["punkt"] is None else [float(c) for c in o["punkt"]],
                    "kg": float(x["betrag"]) if x.get("einheit") == "kg" and unten else None,
                    "text": f"Last {lid} (App)", "id": lid}
            if gegen:
                last["gegen"] = [gegen]
            lasten.append(last)
            zl[lid] = {**eintrag, "kraft": kr.kurz(F), "punkt": last["punkt"],
                       "normale": None if o["normale"] is None else kr.kurz(o["normale"])}
        v.szenarien.append(_szenario_dict(l, lasten, zg))
    za: dict[str, Any] = {}
    quellen = [(x, "app") for x in doc.get("lager") or []] + [(x, "modell") for x in modell_lager or []]
    for i, (x, quelle) in enumerate(quellen):
        lid = str(x.get("id") or f"M{i + 1}")
        o = ort_aufloesen(x.get("ort"), str(x.get("teil")), koerper)
        za[lid] = {"zustand": o["zustand"], "text": o["text"], "teil": o["teil"], "flaeche": o["flaeche"],
                   "quelle": quelle}
        if o["zustand"] == "fehlt" or o["teil"] is None:
            continue
        k = koerper.get(o["teil"])
        if k is None:  # Gruppe: jedes Teil der Gruppe ganz gelagert
            for n in [n for n in koerper if n.startswith(o["teil"].rstrip("/") + "/")]:
                v.lager.append(Lager(f"{lid}.{n.rsplit('/', 1)[-1]}", n, str(x.get("art") or "fest"), quelle,
                                     zeile=x.get("zeile")))
            continue
        netz = None
        auf = str(x.get("auf") or ("flaeche" if o["flaeche"] is not None else "punkt"))
        if auf == "flaeche" and o["flaeche"] is not None:
            netz = flaechen_netz(k, int(o["flaeche"]))
        elif auf != "teil" and o["punkt"] is not None:
            netz = punkt_netz(k, np.asarray(o["punkt"], float), o["flaeche"])
        L = Lager(lid, o["teil"], str(x.get("art") or "fest"), quelle,
                  None if o["punkt"] is None else np.asarray(o["punkt"], float),
                  None if o["normale"] is None else np.asarray(o["normale"], float), o["flaeche"], netz,
                  x.get("zeile"), auf)
        if L.art == "gleitend" and L.normale is None:
            za[lid].update(zustand="fehlt", text="gleitendes Lager ohne Normale (Fläche anklicken)")
            continue
        if x.get("ort", {}).get("signatur") is None and o.get("signatur") is not None and quelle == "app":
            v.signaturen[lid] = dict(o["signatur"])
        v.lager.append(L)
        za[lid].update(L.kurz())
    zs: dict[str, Any] = {}
    for teil, e in v.topologie.items():
        k = koerper.get(teil)
        for z in e.get("schutz") or []:
            key = f"{teil}#{z.get('index')}"
            if k is None:
                zs[key] = {"zustand": "fehlt", "text": f"Teil {teil!r} gibt es nicht mehr"}
                continue
            idx, zz, tt = flaeche_suchen(k, z.get("index"), z.get("signatur"))
            zs[key] = {"zustand": zz, "text": tt, "index": idx}
    v.zustand = {"lasten": zl, "lager": za, "schutz": zs}
    fehlen = [i for i, z in {**zl, **za}.items() if z.get("zustand") == "fehlt"]
    if fehlen:
        v.hinweise.append(f"{len(fehlen)} Lasten bzw. Lager aus der App sind nicht mehr zuordenbar und zählen nicht "
                          f"mit ({', '.join(fehlen[:6])}{' …' if len(fehlen) > 6 else ''})")
    return v
