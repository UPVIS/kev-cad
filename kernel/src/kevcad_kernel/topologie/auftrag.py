"""Auftrag für die Topologieoptimierung, im Rechenprozess aus dem Modell des letzten Laufs (``statik.anbindung.LETZTER``).

Lager und Lasten kommen genau wie beim Festkörper (``statik/festkoerper/auftrag.faelle``): Kontaktflächen zu den
tragenden Nachbarn, ``st.last`` am Punkt oder über eine Kontaktfläche, Kraftpaare, Lagerkräfte der Stäbe und Kräfte der
Stäbe auf Verbinder; ein Verbinder ohne äußere Nachbarn hängt am Stab mit der größten Kraft. Dazu für die Schutzzonen:
die Nachbarn, über die eine Last kommt oder die das Teil klemmen (Klemmung, Steck, Formschluss, Kleben, Gelenk mit
Bereich). Geschrieben wird ein Ordner mit ``auftrag.json``, dem Teil als BREP (Weltlage), den Netzen der Nachbarn und
den Schutzformen aus model.py (in Weltlage).

Der Schlüssel ``lastfall`` (Teilstand, Lager, Lasten, Werkstoff, Drucklage) zeigt, ob ein gespeichertes Ergebnis noch
zum Lastfall passt; ``schluessel`` dazu mit allen Einstellungen adressiert den Zwischenspeicher des Prozesses.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
from typing import Any

import numpy as np

from kevcad_kernel.topologie import VERSION

RAND_MM = 3.0
KLEMMEN = ("klemmung", "steck", "formschluss", "kleben")


def _r(x: Any, n: int = 4) -> Any:
    if x is None:
        return None
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_r(v, n) for v in x]
    if isinstance(x, (int, float, np.floating)):
        return round(float(x), n)
    return x


def _json_default(x: Any) -> Any:
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (np.floating, np.integer, np.bool_)):
        return x.item()
    return str(x)


def teil_finden(st: Any, teil: str | None, form: str | None = None) -> tuple[str | None, str | None]:
    """Teilname im letzten Lauf zu ``teil`` (Name, Gruppe mit genau einem Druckteil) oder ``form`` (Formschlüssel aus
    model.py). Rückgabe (Name, Fehlertext)."""
    m = st.modell
    if form and not (teil and teil in m.teile):
        from kevcad_kernel.topologie import form_signatur

        treffer = [n for n, t in m.teile.items() if t.druckteil and n in st.koerper
                   and form_signatur(st.koerper[n].shape) == form]
        if len(treffer) >= 1:
            return sorted(treffer)[0], None
    if not teil:
        druck = [n for n, t in m.teile.items() if t.druckteil]
        if len(druck) == 1:
            return druck[0], None
        return None, ("Welches Teil? " + (", ".join(repr(n) for n in druck[:8]) if druck else
                                          "Im Modell gibt es kein Druckteil"))
    namen = m.aufloesen(teil)
    druck = [n for n in namen if m.teile[n].druckteil]
    if len(druck) == 1:
        return druck[0], None
    if not namen:
        import difflib

        tips = difflib.get_close_matches(teil, list(m.teile), n=3, cutoff=0.4)
        return None, f"Teil {teil!r} gibt es nicht" + (f"; meinten Sie {', '.join(repr(t) for t in tips)}?" if tips
                                                         else "")
    if not druck:
        return None, (f"{teil!r} ist kein Druckteil: optimiert werden nur Teile aus lager.druckteil(…) (Stangen, "
                      "Platten und Zukaufteile kommen fertig aus dem Lager)")
    return None, f"{teil!r} meint mehrere Druckteile: {', '.join(repr(n) for n in druck[:8])}"


def _szenario_waehlen(st: Any, teil: str, szenario: str | None) -> tuple[list[str], str | None]:
    """Szenarien mit Last auf dem Teil (für die Wahl ohne Angabe: das mit der größten Ausnutzung zuerst)."""
    erg = st.ergebnis or {}
    namen = [e.get("name") for e in erg.get("szenarien") or []]
    if szenario is not None:
        if szenario not in namen:
            import difflib

            tips = difflib.get_close_matches(szenario, namen, n=3, cutoff=0.3)
            return [], (f"Szenario {szenario!r} gibt es nicht (vorhanden: {', '.join(repr(n) for n in namen)})"
                        + (f"; meinten Sie {tips[0]!r}?" if tips else ""))
        return [szenario], None
    from kevcad_kernel.statik.festkoerper.auftrag import faelle

    fs = faelle(st, {"teile": [teil]})
    if not fs:
        return [], (f"Auf {teil!r} liegt in keinem Szenario eine Last. Erst ein Szenario mit Last anlegen, etwa "
                    "st.szenario(\"Last 100 N\"); st.last(teil, kraft=(0, 0, -100), punkt=(…))")
    fs.sort(key=lambda f: -(f.get("ausnutzung_s0") or 0.0))
    return [fs[0]["szenario"]], None


def lastfaelle(st: Any, teil: str, szenarien: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Fälle (wie Festkörper) für das Teil in den Szenarien; Verbinder ohne äußere Nachbarn hängen am Stab mit der
    größten Kraft."""
    from kevcad_kernel.statik.festkoerper.auftrag import faelle

    fs = faelle(st, {"teile": [teil], "szenarien": szenarien})
    hinweise: list[str] = []
    out = []
    for f in fs:
        if f["teil"] != teil:
            continue
        if not f.get("lager"):
            mit = [l for l in f["lasten"] if l.get("kontakt_mit")]
            if not mit:
                hinweise.append(f"{f['szenario']}: keine tragenden Nachbarn")
                continue
            gross = max(mit, key=lambda l: float(np.linalg.norm(l["kraft"])))
            f["lager"] = [gross["kontakt_mit"]]
            f["lasten"] = [l for l in f["lasten"] if l is not gross]
            f["lager_aus_last"] = gross["kontakt_mit"]
        out.append(f)
    return out, hinweise


def _netz_npz(k: Any, lo: np.ndarray, hi: np.ndarray, datei: str) -> int:
    pos = np.asarray(k.pos, dtype=float)
    tri = np.asarray(k.tri, dtype=np.int64)
    if len(tri):
        P = pos[tri]
        tlo, thi = P.min(axis=1), P.max(axis=1)
        tri = tri[np.all((thi >= lo) & (tlo <= hi), axis=1)]
    used = np.unique(tri) if len(tri) else np.zeros(0, dtype=np.int64)
    remap = np.full(len(pos), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    np.savez(datei, pos=pos[used].astype(np.float64), tri=remap[tri].astype(np.int64))
    return int(len(tri))


def _form_in_welt(b64: str, lage: np.ndarray) -> Any:
    """Form aus model.py (BREP-Text, Koordinaten der Form ohne Lage) in die Weltlage des gezeigten Teils."""
    import io

    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS_Shape

    form = TopoDS_Shape()
    BRepTools.Read_s(form, io.BytesIO(base64.b64decode(b64)), BRep_Builder())
    tr = gp_Trsf()
    tr.SetValues(*[float(lage[i, j]) for i in range(3) for j in range(4)])
    return form.Moved(TopLoc_Location(tr))


def _masse(shape: Any) -> tuple[float, np.ndarray, np.ndarray]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p)
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    lo, hi = b.CornerMin(), b.CornerMax()
    return abs(float(p.Mass())), np.array([lo.X(), lo.Y(), lo.Z()]), np.array([hi.X(), hi.Y(), hi.Z()])


def schreibe(st: Any, wunsch: dict[str, Any]) -> dict[str, Any]:
    """Ordner mit ``auftrag.json``; ``wunsch``: ``teil``, ``form`` (Formschlüssel aus model.py), ``szenario``,
    ``einstellungen`` (behalten, ueberhang, fein, steg, bett, schutz_auto …), ``schutz`` (Liste von Formen als
    BREP-Text in Teilkoordinaten, Base64, mit ``art`` "form" oder "flaeche")."""
    from OCP.BRepTools import BRepTools

    from kevcad_kernel.statik.festkoerper.auftrag import _toleranz, _werkstoff

    t0 = time.perf_counter()
    if st.modell is None:
        raise ValueError("Noch kein Statikmodell: erst run aufrufen.")
    m = st.modell
    name, fehler = teil_finden(st, wunsch.get("teil"), wunsch.get("form"))
    if fehler:
        raise ValueError(fehler)
    t = m.teile[name]
    if not t.druckteil:
        raise ValueError(f"{name!r} ist kein Druckteil")
    k = st.koerper.get(name)
    if k is None:
        raise ValueError(f"{name!r} fehlt im letzten Lauf")
    szen, fehler = _szenario_waehlen(st, name, wunsch.get("szenario"))
    if fehler:
        raise ValueError(fehler)
    fs, hinweise = lastfaelle(st, name, szen)
    if not fs:
        raise ValueError(f"Im Szenario {szen[0]!r} liegt keine Last auf {name!r}"
                         + (f" ({'; '.join(hinweise)})" if hinweise else "")
                         + ". Optimiert wird für die Lasten eines Szenarios (st.last auf dem Teil, Lagerkräfte von "
                           "Stäben, Kräfte auf Verbinder).")
    w = _werkstoff(m, st.katalog, name)
    if w is None:
        raise ValueError(f"Material von {name!r} hat keine Festigkeitswerte im Katalog")
    ordner = tempfile.mkdtemp(prefix="kevcad-topo-")
    brep = os.path.join(ordner, "teil.brep")
    lage = np.asarray(k.lage, dtype=float).reshape(4, 4)
    volumen, bmin, bmax = float(k.volumen), np.asarray(k.bmin, float), np.asarray(k.bmax, float)
    from kevcad_kernel.topologie import form_signatur

    if wunsch.get("form_brep"):
        # Bauraum ist das Ausgangsteil aus model.py (der Lauf zeigt vielleicht schon ein optimiertes Ergebnis)
        welt = _form_in_welt(wunsch["form_brep"], lage)
        volumen, bmin, bmax = _masse(welt)
        BRepTools.Write_s(welt, brep)
        form = form_signatur(welt)
    else:
        BRepTools.Write_s(k.shape, brep)
        form = form_signatur(k.shape)
    lo, hi = bmin - RAND_MM, bmax + RAND_MM
    nachbarn: dict[str, dict[str, Any]] = {}
    brauche: set[str] = set()
    for f in fs:
        brauche |= set(f["lager"]) | {l["kontakt_mit"] for l in f["lasten"] if l.get("kontakt_mit")}
    # Klemmende Nachbarn (Schutz der Klemmfläche)
    klemmen = []
    for key, e in m.kanten.items():
        if name not in key:
            continue
        anderer = next(iter(key - {name}), None)
        if anderer is None or anderer not in st.koerper:
            continue
        if (e.get("verbinde") in KLEMMEN) or (e.get("gelenk") and e.get("festgestellt")):
            klemmen.append(anderer)
            brauche.add(anderer)
    from kevcad_kernel.statik.festkoerper.auftrag import lager_nachbar, lager_npz, lager_schluessel

    for x in sorted(brauche):
        L = lager_nachbar(m, x)
        if L is not None:  # ausdrücklich gesetztes Lager (Simulation): seine Fläche ist das „Nachbarnetz“
            datei = os.path.join(ordner, f"nachbar_{len(nachbarn)}.npz")
            n = lager_npz(L, datei)
            nachbarn[x] = {"datei": datei, "tol": 0.3, "schluessel": lager_schluessel(L), "dreiecke": n,
                           "normale": None if L.normale is None else [float(c) for c in L.normale],
                           "komponenten": L.komponenten}
            continue
        if x not in st.koerper:
            continue
        datei = os.path.join(ordner, f"nachbar_{len(nachbarn)}.npz")
        n = _netz_npz(st.koerper[x], lo, hi, datei)
        nachbarn[x] = {"datei": datei, "tol": _toleranz(m, name, x), "schluessel": st.koerper[x].key, "dreiecke": n}
    # Schutzformen aus model.py: Teilkoordinaten → Welt (Lage des gezeigten Teils)
    schutz = []
    for i, s in enumerate(wunsch.get("schutz") or []):
        if s.get("brep"):  # aus model.py: Form oder Fläche in Teilkoordinaten
            datei = os.path.join(ordner, f"schutz_{i}.brep")
            with open(datei, "wb") as fh:
                fh.write(base64.b64decode(s["brep"]))
            schutz.append({"datei": datei, "art": s.get("art") or "form", "lage": lage.tolist(),
                           "dicke": s.get("dicke"), "schluessel": hashlib.sha1(s["brep"].encode()).hexdigest()[:16]})
        else:  # aus MCP oder App: Quader, Kugel (Welt) oder Fläche des Teils nach Nummer
            schutz.append({**s, "schluessel": hashlib.sha1(json.dumps(s, sort_keys=True).encode()).hexdigest()[:16]})
    sz_obj = {s.name: s for s in st.szenarien}
    faelle_out = []
    for f in fs:
        sz = sz_obj.get(f["szenario"])
        faelle_out.append({"szenario": f["szenario"], "ziel": f["ziel"], "lager": sorted(f["lager"]),
                           "lager_aus_last": f.get("lager_aus_last"),
                           "lasten": [{kk: v for kk, v in l.items()} for l in f["lasten"]],
                           "feld": [float(c) for c in (sz.feld if sz is not None else (0, 0, 0))],
                           "s0": f.get("s0"), "hinweise": f.get("hinweise") or []})
    einst = dict(wunsch.get("einstellungen") or {})
    oben = None if t.druck_oben is None else [float(c) for c in t.druck_oben]
    lastfall = {"v": VERSION, "teil": None if wunsch.get("form_brep") else k.key,
                "form": form, "w": w, "oben": _r(oben),
                "masse": round(float(t.masse_kg), 6),
                "faelle": [{"szenario": f["szenario"], "lager": [(x, nachbarn.get(x, {}).get("schluessel"),
                                                                  nachbarn.get(x, {}).get("tol")) for x in f["lager"]],
                            "lasten": [{kk: _r(v) for kk, v in l.items() if kk != "quelle"} for l in f["lasten"]],
                            "feld": _r(f["feld"])} for f in faelle_out],
                "klemmen": [(x, nachbarn.get(x, {}).get("schluessel")) for x in sorted(klemmen)]}
    lastfall_key = hashlib.sha1(json.dumps(lastfall, sort_keys=True, default=_json_default).encode()).hexdigest()[:20]
    schluessel = hashlib.sha1(json.dumps({"lastfall": lastfall_key, "einst": einst,
                                          "schutz": [s["schluessel"] for s in schutz]},
                                         sort_keys=True, default=str).encode()).hexdigest()[:20]
    masse = float(t.masse_kg) * volumen / max(float(k.volumen), 1e-9)
    auftrag = {"version": VERSION, "teil": name, "form": form, "brep": brep,
               "lage": lage.tolist(), "druck_rahmen": None if k.info.get("druck_rahmen") is None else
               np.asarray(k.info["druck_rahmen"], dtype=float).tolist(), "oben": oben,
               "volumen": volumen, "masse_kg": masse, "werkstoff": w,
               "material_id": t.material_id, "bmin": [float(c) for c in bmin], "bmax": [float(c) for c in bmax],
               "nachbarn": nachbarn, "klemmen": sorted(klemmen), "faelle": faelle_out, "schutz": schutz,
               "einstellungen": einst, "lastfall": lastfall_key, "schluessel": schluessel, "run": st.run,
               "hinweise": hinweise}
    pfad = os.path.join(ordner, "auftrag.json")
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(auftrag, fh, ensure_ascii=False, default=_json_default)
    return {"ordner": ordner, "auftrag": pfad, "teil": name, "szenarien": [f["szenario"] for f in faelle_out],
            "lastfall": lastfall_key, "schluessel": schluessel, "run": st.run, "hinweise": hinweise,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}
