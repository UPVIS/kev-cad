"""Aufträge für den Festkörper (S3), im Rechenprozess aus dem Modell des letzten Laufs (``anbindung.LETZTER``).

Ein **Fall** ist ein Teil in einem Szenario. Quelle sind die Bauteil-Nachweise der Stufe S0 (``bauteil.pruefe_last``):

- **direkte Lasten** (``st.last(teil, …)``): Kraft am angegebenen Punkt (sonst gleichmäßig über das Volumen, wie die
  Last „am Schwerpunkt“ des Kragträgers), Lager an den tragenden Nachbarn;
- **Lager eines Stabs** (das Stabwerk liegt im Teil auf): alle Lagerkräfte und -momente der Stäbe auf dieses Teil aus
  S1, eingeleitet über die Kontaktfläche zum jeweiligen Stab, Lager an den übrigen Nachbarn. Hängt das Teil nur an
  Stäben, ist der Stab mit der größten Kraft das Lager (Gleichgewicht);
- **Verbinder zwischen Stäben** (im Stabwerk starr, ohne eigene Last): Kraft und Moment jedes Stabs am Anschluss aus
  S1 (Endkräfte des starren Glieds), über die Kontaktfläche zum Stab; Lager wie oben;
- **Kontaktkräfte eines Ablaufs** (S2) auf Wunsch: die größte Kontaktkraft auf das Teil, am Kontaktpunkt, allein
  (statt der ruhenden Ersatzlasten des Szenarios).

Dazu immer das Eigengewicht im Beschleunigungsfeld des Szenarios. Der Ordner enthält ``auftrag.json``, je Teil die
Form als BREP (Welt) und die Netze der Nachbarn, auf den Hüllquader des Teils zugeschnitten. Der Schlüssel je Fall
(Teilstand, Lager, Lasten, Werkstoff, Netzeinstellung) adressiert den Zwischenspeicher des FEM-Prozesses.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from typing import Any

import numpy as np

from kevcad_kernel.statik.festkoerper import VERSION

MAX_TEILE_AUTO = 8
MAX_TEILE = 24
RAND_MM = 3.0  # Nachbarnetze: Hüllquader des Teils plus so viel
TOL_BERUEHRT = 0.3  # mm, Lagerfläche: Abstand zum Nachbarnetz (Netzabweichung eingerechnet)
TOL_SPIEL = 0.75
NICHT_RECHNEN = ("zukaufteil",)


def _r(x: Any, n: int = 4) -> Any:
    if x is None:
        return None
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_r(v, n) for v in x]
    return round(float(x), n)


def _ausrichtungen(k: Any) -> dict[str, list[float]]:
    """Schichtnormale (Welt) je möglicher Drucklage, wie ``modell._druck_oben`` für unten = −x, −y, −z der Form."""
    lage = np.asarray(k.lage, dtype=float).reshape(4, 4)
    rahmen = k.info.get("druck_rahmen")
    R = np.asarray(rahmen, dtype=float).reshape(4, 4)[:3, :3] if rahmen is not None else lage[:3, :3]
    out = {}
    for name, unten in (("-z", (0, 0, -1.0)), ("-y", (0, -1.0, 0)), ("-x", (-1.0, 0, 0))):
        d = lage[:3, :3] @ (R.T @ np.asarray(unten))
        n = float(np.linalg.norm(d))
        if n > 1e-9:
            out[name] = [float(c) for c in -d / n]
    return out


def _werkstoff(m: Any, katalog: Any, name: str) -> dict[str, Any] | None:
    t = m.teile[name]
    w = t.werkstoff
    if w is None or not w.grenze or not w.E:
        return None
    ez = None
    if t.druckteil and katalog is not None and t.material_id:
        try:
            mat = katalog.material(t.material_id) or {}
            ez = (mat.get("mechanik") or {}).get("e_modul_z")
            ez = float(ez) if ez else None
        except Exception:  # noqa: BLE001
            ez = None
    return {"id": w.id, "name": w.name, "E": float(w.E), "nu": float(w.nu if w.nu is not None else 0.3),
            "E_z": ez, "f": float(w.grenze), "q": (float(w.quer) if w.quer else 0.5) if t.druckteil else None,
            "nu_angenommen": w.nu is None}


def _toleranz(m: Any, a: str, b: str) -> float:
    e = m.kanten.get(frozenset((a, b))) or {}
    return TOL_SPIEL if e.get("kontakt") == "spiel" else TOL_BERUEHRT


def faelle(st: Any, wunsch: dict[str, Any]) -> list[dict[str, Any]]:
    """Fälle aus dem Ergebnis des letzten Laufs: je (Szenario, Teil) Lasten und Lager. ``wunsch``: ``teile`` (Namen
    oder Gruppen), ``szenarien`` (Namen), ``lasten`` (zusätzliche Lasten, etwa aus einem Ablauf: je ``szenario``,
    ``teil``, ``kraft``, ``punkt``, ``quelle``), ``auto`` (nur Szenarien mit Lasten, höchstens ``MAX_TEILE_AUTO``
    Teile, die am stärksten ausgelasteten zuerst)."""
    from kevcad_kernel.statik.bauteil import tragende_nachbarn

    m = st.modell
    erg = st.ergebnis or {}
    szen_obj = {s.name: s for s in st.szenarien}
    teile_filter: set[str] | None = None
    if wunsch.get("teile"):
        teile_filter = {n for t in wunsch["teile"] for n in m.aufloesen(str(t))}
    sz_filter = set(wunsch["szenarien"]) if wunsch.get("szenarien") else None
    out: dict[tuple[str, str], dict[str, Any]] = {}

    def fall(sz_name: str, teil: str, ziel: float, s0: dict[str, Any] | None) -> dict[str, Any] | None:
        key = (sz_name, teil)
        if key not in out:
            t = m.teile.get(teil)
            if t is None or teil in m.staebe or t.verbindungselement or (t.art in NICHT_RECHNEN):
                return None
            out[key] = {"szenario": sz_name, "teil": teil, "ziel": ziel, "lasten": [], "lager": None,
                        "s0": s0, "druckteil": bool(t.druckteil)}
        return out[key]

    for e in erg.get("szenarien") or []:
        name = e.get("name")
        sz = szen_obj.get(name)
        if sz is None or (sz_filter is not None and name not in sz_filter):
            continue
        if wunsch.get("auto") and not sz.hat_lasten:
            continue
        if wunsch.get("lasten"):  # Kontaktkräfte eines Ablaufs: allein (sie sind die Last des Ablaufs)
            continue
        bauteile = [b for b in e.get("bauteile") or [] if b.get("sicherheit") is not None]
        for b in bauteile:
            teil = b["teil"]
            if teile_filter is not None and teil not in teile_filter:
                continue
            s0 = {k: b.get(k) for k in ("sicherheit", "spannung", "ziel", "schichtfaktor", "quer_zur_schicht",
                                        "hebel_mm", "aus_lager")}
            f = fall(name, teil, float(b["ziel"]), s0)
            if f is None:
                continue
            if f["s0"] and b["sicherheit"] < (f["s0"].get("sicherheit") or np.inf):
                f["s0"] = s0
            if b.get("aus_lager"):
                if f.get("aus_lager_fertig"):
                    continue
                f["aus_lager_fertig"] = True
                stabs = []
                for a in e.get("auflager") or []:
                    if a.get("teil") != teil:
                        continue
                    stabs.append(a["stab"])
                    f["lasten"].append({"kraft": [-float(c) for c in a["kraft"]],
                                        "moment": [-float(c) for c in a.get("moment") or (0, 0, 0)],
                                        "punkt": [float(c) for c in a["punkt"]], "kontakt_mit": a["stab"],
                                        "quelle": f"Lager von {a['stab']}"})
                _, nach = tragende_nachbarn(m, teil, st.koerper, set(stabs))
                f["lager"] = nach or None
            else:
                f["lasten"].append({"kraft": list(b["kraft"]), "moment": b.get("moment"),
                                    "punkt": list(b["lastpunkt"]) if b.get("punkt_gegeben") else None,
                                    "quelle": "Last aus dem Szenario"})
                f["lager"] = sorted(set(f["lager"] or []) | set(b.get("nachbarn") or []))
        # Verbinder zwischen Stäben (S1, im Stabwerk starr): Kraft und Moment jedes Stabs am Anschluss; gehalten von
        # Nachbarn außerhalb der Stäbe (ohne Schrauben), sonst vom Stab mit der größten Kraft (``schreibe``)
        schon = {b["teil"] for b in bauteile}
        je_teil: dict[str, list[dict[str, Any]]] = {}
        for v in e.get("verbinder") or []:
            if v["teil"] in schon or (teile_filter is not None and v["teil"] not in teile_filter):
                continue
            je_teil.setdefault(v["teil"], []).append(v)
        for teil, vs in je_teil.items():
            kraft = max(float(np.linalg.norm(v["kraft"])) for v in vs)
            t = m.teile.get(teil)
            if t is None or kraft < 0.5:
                continue
            f = fall(name, teil, sz.ziel_fuer(t.druckteil), None)
            if f is None:
                continue
            for v in vs:
                f["lasten"].append({"kraft": list(v["kraft"]), "moment": list(v["moment"]), "punkt": list(v["punkt"]),
                                    "kontakt_mit": v["stab"], "quelle": f"Verbinder: Kraft von {v['stab']}"})
            # Ein Verbinder hängt nur an Stäben (sonst wäre er geerdet): Lager ist der Stab mit der größten Kraft;
            # Nachbarn derselben Gruppe (Rolle, Schrauben) tragen nichts von außen
            f["lager"] = None
            f["verbinder_n"] = kraft
            rest = np.sum([v["kraft"] for v in vs], axis=0) + np.asarray(sz.feld) * t.masse_kg
            if float(np.linalg.norm(rest)) > 0.1 * kraft + 0.5:
                f.setdefault("hinweise", []).append(
                    f"Verbinder aus mehreren Teilen: {_r(float(np.linalg.norm(rest)), 1)} N gehen über die übrigen "
                    "Teile der Gruppe und landen hier im Lager")
    # zusätzliche Lasten (Kontaktkräfte aus einem Ablauf)
    for l in wunsch.get("lasten") or []:
        teil = l["teil"]
        sz = szen_obj.get(l["szenario"])
        if sz is None or teil not in m.teile:
            continue
        mit = l.get("kontakt_mit") if l.get("kontakt_mit") in m.teile else None
        f = fall(l["szenario"], teil, sz.ziel_fuer(m.teile[teil].druckteil), None)
        if f is None:
            continue
        f["lasten"].append({"kraft": list(l["kraft"]), "moment": None, "punkt": list(l["punkt"]),
                            "quelle": l.get("quelle") or "Kontaktkraft aus dem Ablauf"})
        _, nach = tragende_nachbarn(m, teil, st.koerper, {mit} if mit else set())
        f["lager"] = sorted(set(f["lager"] or []) | set(nach))
    liste = [f for f in out.values() if f["lasten"]]
    for f in liste:
        f.pop("aus_lager_fertig", None)
        s0 = f.get("s0") or {}
        f["ausnutzung_s0"] = (f["ziel"] / s0["sicherheit"]) if s0.get("sicherheit") else 0.0
    # Reihenfolge: am stärksten ausgelastete Teile zuerst; Grenze je Auftrag
    # (Verbinder ohne Kragträger-Nachweis nach der Kraft, die durch sie geht, hinter den nachgewiesenen Teilen)
    beste: dict[str, tuple[float, float]] = {}
    for f in liste:
        alt = beste.get(f["teil"], (0.0, 0.0))
        beste[f["teil"]] = (max(alt[0], f["ausnutzung_s0"]), max(alt[1], f.get("verbinder_n") or 0.0))
    reihenfolge = sorted(beste, key=lambda n: (-beste[n][0], -beste[n][1]))
    grenze = MAX_TEILE_AUTO if wunsch.get("auto") else MAX_TEILE
    erlaubt = set(reihenfolge[:grenze])
    return sorted((f for f in liste if f["teil"] in erlaubt),
                  key=lambda f: (reihenfolge.index(f["teil"]), f["szenario"]))


def schreibe(st: Any, wunsch: dict[str, Any]) -> dict[str, Any]:
    """Ordner mit ``auftrag.json``, BREP je Teil und Nachbarnetzen; Rückgabe: Pfade, Fälle (mit Schlüssel)."""
    from OCP.BRepTools import BRepTools

    t0 = time.perf_counter()
    if st.modell is None:
        raise ValueError("Noch kein Statikmodell: erst run aufrufen.")
    m = st.modell
    liste = faelle(st, wunsch)
    ordner = tempfile.mkdtemp(prefix="kevcad-fem-")
    szen_obj = {s.name: s for s in st.szenarien}
    teile: dict[str, dict[str, Any]] = {}
    nicht: list[dict[str, Any]] = []
    for f in liste:
        name = f["teil"]
        k = st.koerper.get(name)
        w = _werkstoff(m, st.katalog, name)
        if k is None or w is None:
            nicht.append({"szenario": f["szenario"], "teil": name, "meldung": "Material ohne Festigkeitswerte im "
                                                                          "Katalog"})
            continue
        if not f.get("lager"):
            # Verbinder nur zwischen Stäben: der Stab mit der größten Kraft hält
            mit = [l for l in f["lasten"] if l.get("kontakt_mit")]
            if not mit:
                nicht.append({"szenario": f["szenario"], "teil": name, "meldung": "keine tragenden Nachbarn"})
                continue
            gross = max(mit, key=lambda l: float(np.linalg.norm(l["kraft"])))
            f["lager"] = [gross["kontakt_mit"]]
            f["lasten"] = [l for l in f["lasten"] if l is not gross]
            f["lager_aus_last"] = gross["kontakt_mit"]
        if name not in teile:
            i = len(teile)
            brep = os.path.join(ordner, f"teil_{i}.brep")
            BRepTools.Write_s(k.shape, brep)
            t = m.teile[name]
            teile[name] = {"id": i, "name": name, "brep": brep, "schluessel_teil": k.key, "volumen": float(k.volumen),
                           "masse_kg": float(t.masse_kg), "werkstoff": w, "druckteil": bool(t.druckteil),
                           "schicht": None if t.druck_oben is None else [float(c) for c in t.druck_oben],
                           "ausrichtungen": _ausrichtungen(k) if t.druckteil else {},
                           "bmin": [float(c) for c in k.bmin], "bmax": [float(c) for c in k.bmax],
                           "nachbarn": {}, "faelle": []}
        T = teile[name]
        lo, hi = np.asarray(k.bmin) - RAND_MM, np.asarray(k.bmax) + RAND_MM
        brauche = set(f["lager"]) | {l["kontakt_mit"] for l in f["lasten"] if l.get("kontakt_mit")}
        for x in sorted(brauche):
            if x in T["nachbarn"] or x not in st.koerper:
                continue
            o = st.koerper[x]
            pos = np.asarray(o.pos, dtype=float)
            tri = np.asarray(o.tri, dtype=np.int64)
            if len(tri):
                P = pos[tri]
                tlo, thi = P.min(axis=1), P.max(axis=1)
                keep = np.all((thi >= lo) & (tlo <= hi), axis=1)
                tri = tri[keep]
            used = np.unique(tri) if len(tri) else np.zeros(0, dtype=np.int64)
            remap = np.full(len(pos), -1, dtype=np.int64)
            remap[used] = np.arange(len(used))
            datei = os.path.join(ordner, f"nachbar_{T['id']}_{len(T['nachbarn'])}.npz")
            np.savez(datei, pos=pos[used].astype(np.float64), tri=remap[tri].astype(np.int64))
            T["nachbarn"][x] = {"datei": datei, "tol": _toleranz(m, name, x), "schluessel": o.key,
                                "dreiecke": int(len(tri))}
        sz = szen_obj[f["szenario"]]
        f["feld"] = [float(c) for c in sz.feld]
        schl = {"v": VERSION, "teil": k.key, "fein": bool(wunsch.get("fein")), "w": w, "schicht": T["schicht"],
                "masse": round(T["masse_kg"], 6), "feld": _r(f["feld"]),
                "lager": [(x, T["nachbarn"].get(x, {}).get("schluessel"), T["nachbarn"].get(x, {}).get("tol"))
                          for x in sorted(f["lager"])],
                "lasten": [{kk: _r(v) if kk != "kontakt_mit" else v for kk, v in l.items() if kk != "quelle"}
                           for l in f["lasten"]],
                "kontakte": [(l.get("kontakt_mit"), T["nachbarn"].get(l.get("kontakt_mit"), {}).get("schluessel"))
                             for l in f["lasten"] if l.get("kontakt_mit")],
                "ausrichtungen": {a: _r(v) for a, v in T["ausrichtungen"].items()}}
        f["schluessel"] = hashlib.sha1(json.dumps(schl, sort_keys=True, default=str).encode()).hexdigest()[:20]
        f["id"] = f"{T['id']}.{len(T['faelle'])}"
        T["faelle"].append(f)
    auftrag = {"version": VERSION, "fein": bool(wunsch.get("fein")), "teile": list(teile.values()),
               "run": st.run}
    pfad = os.path.join(ordner, "auftrag.json")
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(auftrag, fh, ensure_ascii=False)
    return {"ordner": ordner, "auftrag": pfad, "run": st.run,
            "faelle": [{"id": f["id"], "szenario": f["szenario"], "teil": f["teil"], "schluessel": f["schluessel"],
                        "ziel": f["ziel"], "s0": f.get("s0")} for T in teile.values() for f in T["faelle"]],
            "nicht": nicht, "ms": round((time.perf_counter() - t0) * 1000, 1)}
