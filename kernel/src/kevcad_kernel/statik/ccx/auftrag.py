"""Aufträge für Stufe 4 (CalculiX), im Rechenprozess aus dem Modell des letzten Laufs.

Grundlage ist der Auftrag der Stufe 3 (``festkoerper.auftrag.schreibe``: Fälle, Teil als BREP, Nachbarnetze, Lasten,
Lager). Dazu kommt je Teil:

- **Verbindungsart** zu jedem Nachbarn: fest (``verbinde`` mit Schraube, Kleben, Formschluss: wie in Stufe 3 fest
  eingespannt) oder **Kontakt** (Klemmung, Steck, Aufliegen, Gelenke, bloße Berührung oder Spiel; dazu jedes Paar aus
  ``st.kontakt`` in model.py). Kontaktpaare heben ab und gleiten mit dem Reibwert aus ``reibwerte.json`` (Haftreibung
  der Werkstoffpaarung).
- **Kontaktkörper** als BREP, auf den Hüllquader des Teils plus Rand zugeschnitten: Stäbe, die Last einleiten (Rohr in
  der Klemmung), sind elastisch und bekommen an ihren Schnittflächen die Kräfte beider Seiten aus dem Stabwerk
  (``seiten``, S1); Lager-Nachbarn sind starr (alle Knoten fest), das Teil liegt mit Kontakt auf ihnen.
- **Klemmschrauben** (``verbinde(…, art="schraube")`` innerhalb des Teils samt eingeschmolzener Einsätze, etwa die
  Sterngriffklemme): Kopfseite (Scheibe, Schraube) und Mutterseite (Einsatz, Mutter) mit der Klemmkraft. Ohne Angabe
  „handfest“ angenommen: 120 N je mm Gewindedurchmesser (M6 rund 720 N, etwa 1 Nm am Sterngriff).
- **Fließkurve** des Werkstoffs (Plastizität): Metalle von Rp0,2 auf Rm bei der Gleichmaßdehnung (je Werkstoffgruppe
  angenommen), danach ideal plastisch; Druckteile ideal plastisch ab der Zugfestigkeit (Drucklage bekannt) bzw. ab
  ``quer_zur_schicht`` · Zugfestigkeit (Drucklage unbekannt), dazu bleibt die Schichtfuge spröde (Kriterium wie S3).
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import numpy as np

VERSION = 1
FEST_ARTEN = ("schraube", "kleben", "formschluss")  # bleiben fest eingespannt (Vorspannung der Schrauben nicht einzeln)
RAND_STARR = 3.0  # mm Rand um das Teil für starre Lager-Körper
KLEMM_N_JE_MM = 120.0  # handfest: N je mm Gewindedurchmesser
# Gleichmaßdehnung (plastisch) je Werkstoffgruppe, angenommen (Normwerte A_g; Bruchdehnung A deutlich größer)
GLEICHMASS = {"Stahl": 0.15, "Edelstahl": 0.30, "Aluminium": 0.06, "Buntmetall": 0.20, "Guss": 0.01}
GRENZDEHNUNG_METALL = 0.05  # plastische Grenzdehnung für die Traglast (DIN EN 1993-1-5, Anhang C: 5 %)
GRENZDEHNUNG_DRUCK = 0.02  # Druckteile (PLA, PETG: Bruchdehnung in der Schicht wenige Prozent), Näherung


def fliesskurve(w: dict[str, Any], gruppe: str, druckteil: bool, schicht_bekannt: bool,
                verfestigung: bool = True) -> dict[str, Any] | None:
    """Fließkurve [(Spannung, plastische Dehnung)] und Grenzdehnung; None für spröde Werkstoffe (Holz, Beton)."""
    E = float(w["E"])
    if druckteil:
        rm = float(w.get("zug") or w["f"])
        q = float(w.get("q") or 0.5)
        fy = rm if schicht_bekannt else q * rm
        return {"kurve": [(fy, 0.0), (fy, 1.0)], "fy": fy, "rm": rm, "grenzdehnung": GRENZDEHNUNG_DRUCK,
                "modell": ("Druckteil: ideal plastisch ab der Zugfestigkeit, Schichtfuge spröde (Näherung)"
                           if schicht_bekannt else "Druckteil, Drucklage unbekannt: ideal plastisch ab "
                                                   f"{round(q * 100)} % der Zugfestigkeit (Näherung)")}
    rp = w.get("streckgrenze")
    if not rp:
        return None
    rp = float(rp)
    rm = float(w.get("zug") or rp)
    eu = GLEICHMASS.get(gruppe, 0.10)
    if not verfestigung or rm <= rp * 1.001:
        kurve = [(rp, 0.0), (rp, 1.0)]
        modell = "ideal plastisch ab Rp0,2"
    else:
        e_pl = max(eu - rm / E, 0.01)
        kurve = [(rp, 0.0), (rm, e_pl), (rm, 1.0)]
        modell = (f"Rp0,2 {rp:g} → Rm {rm:g} N/mm² bei {e_pl * 100:.0f} % plastischer Dehnung (Gleichmaßdehnung "
                  f"{gruppe or 'Metall'} angenommen), danach ideal plastisch")
    return {"kurve": kurve, "fy": rp, "rm": rm, "grenzdehnung": min(GRENZDEHNUNG_METALL, eu), "modell": modell}


def _werkstoff_s4(m: Any, katalog: Any, name: str) -> dict[str, Any] | None:
    """Werkstoff wie in S3 (``festkoerper.auftrag._werkstoff``) plus Gruppe, Streckgrenze, Zugfestigkeit."""
    from kevcad_kernel.statik.festkoerper.auftrag import _werkstoff

    w = _werkstoff(m, katalog, name)
    if w is None:
        return None
    t = m.teile[name]
    ws = t.werkstoff
    w.update({"gruppe": _gruppe(ws), "streckgrenze": ws.streckgrenze, "zug": ws.zug})
    return w


def _werkstoff_stab(m: Any, name: str) -> dict[str, Any] | None:
    s = m.staebe.get(name)
    ws = s.werkstoff if s is not None else (m.teile[name].werkstoff if name in m.teile else None)
    if ws is None or not ws.E:
        return None
    return {"id": ws.id, "name": ws.name, "E": float(ws.E), "nu": float(ws.nu if ws.nu is not None else 0.3),
            "E_z": None, "f": float(ws.grenze or 0.0) or None, "q": None, "gruppe": _gruppe(ws),
            "streckgrenze": ws.streckgrenze, "zug": ws.zug}


def _gruppe(ws: Any) -> str:
    g = str(getattr(ws, "gruppe", "") or "")
    n = f"{getattr(ws, 'id', '')} {getattr(ws, 'name', '')}".lower()
    if "edelstahl" in n or g == "Edelstahl":
        return "Edelstahl"
    if "alu" in n or g == "Aluminium":
        return "Aluminium"
    if "messing" in n or "kupfer" in n or g == "Buntmetall":
        return "Buntmetall"
    if "guss" in n:
        return "Guss"
    if "stahl" in n or g == "Stahl":
        return "Stahl"
    return g


def verbindungsart(m: Any, a: str, b: str, deklariert: list[dict[str, Any]],
                   befestigt: dict[str, str] | None = None) -> tuple[str, str]:
    """("fest" | "kontakt", Quelle) für das Paar a, b. An der Umgebung befestigte Teile (``befestigt(…)``, etwa an die
    Wand geschraubt) bleiben an der Kulisse fest."""
    for d in deklariert:
        if (a in d["a"] and b in d["b"]) or (a in d["b"] and b in d["a"]):
            return "kontakt", "st.kontakt in model.py"
    for x, y in ((a, b), (b, a)):
        if befestigt and x in befestigt and (y in m.kulisse or y not in m.teile):
            return "fest", f"befestigt: {befestigt[x]}"
    e = m.kanten.get(frozenset((a, b))) or {}
    if e.get("verbinde") in FEST_ARTEN:
        return "fest", f"verbinde {e['verbinde']}"
    if e.get("gelenk"):
        return "kontakt", f"Gelenk ({e['gelenk']})" + (" mit Bereich" if e.get("festgestellt") else "")
    if e.get("verbinde"):
        return "kontakt", f"verbinde {e['verbinde']}"
    return "kontakt", f"Berührung ({e.get('kontakt') or 'Kontakt'})"


def _deklariert(st: Any) -> list[dict[str, Any]]:
    out = []
    m = st.modell
    for d in (getattr(st, "s4", None) or {}).get("kontakte") or []:
        a = {n for t in d.get("teile") or [] for n in m.aufloesen(str(t))}
        b = {n for t in d.get("gegen") or [] for n in m.aufloesen(str(t))}
        if a and b:
            out.append({**d, "a": a, "b": b})
    return out


def _zuschneiden(k: Any, lo: np.ndarray, hi: np.ndarray, pfad: str) -> bool:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt

    from kevcad_kernel.pruefung.kollision import schnittmenge

    box = BRepPrimAPI_MakeBox(gp_Pnt(*map(float, lo)), gp_Pnt(*map(float, hi))).Shape()
    s = schnittmenge(k.shape, box)
    if s is None:
        return False
    BRepTools.Write_s(s, pfad)
    return True


def _netz_npz(st: Any, name: str, lo: np.ndarray, hi: np.ndarray, pfad: str) -> bool:
    o = st.koerper.get(name)
    if o is None:
        return False
    pos = np.asarray(o.pos, dtype=float)
    tri = np.asarray(o.tri, dtype=np.int64)
    if len(tri):
        P = pos[tri]
        keep = np.all((P.max(axis=1) >= lo) & (P.min(axis=1) <= hi), axis=1)
        tri = tri[keep]
    if not len(tri):
        return False
    used = np.unique(tri)
    remap = np.full(len(pos), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    np.savez(pfad, pos=pos[used], tri=remap[tri])
    return True


def _klemmungen(st: Any, teil: str, opt: dict[str, Any], deklariert: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Schrauben, die das Teil in sich zusammenziehen (Klemmschlitz) oder an einen Kontaktpartner pressen."""
    m = st.modell
    einheit = {teil}
    for e in m.kanten.values():  # eingeschmolzene oder geklebte Teile (Einsatz) gehören zum Teil
        if e.get("verbinde") in ("formschluss", "kleben") and teil in (e["a"], e["b"]):
            einheit.add(e["b"] if e["a"] == teil else e["a"])
    out = []
    for v in m.verbindungen:
        if v.get("art") != "schraube":
            continue
        a, b, mit = v.get("a"), v.get("b"), [x for x in v.get("mit") or [] if x in m.teile]
        if a not in einheit or b not in einheit:
            continue
        schrauben = [x for x in mit if "schraube" in x.lower()]
        kopf = [x for x in mit if "scheibe" in x.lower()] or schrauben
        mutter = [x for x in (a, b, *mit) if x != teil and x in einheit or "mutter" in x.lower()]
        mutter = [x for x in dict.fromkeys(mutter) if x not in kopf and x not in schrauben]
        if not kopf or not mutter:
            continue
        d = next((m.teile[x].gewinde_d for x in schrauben if m.teile[x].gewinde_d), None) or 6.0
        kraft, quelle = KLEMM_N_JE_MM * float(d), f"handfest angenommen ({KLEMM_N_JE_MM:g} N je mm, M{d:g})"
        for dk in deklariert:
            if teil in dk["a"] | dk["b"] and dk.get("klemmkraft") is not None:
                kraft, quelle = float(dk["klemmkraft"]), "st.kontakt(…, klemmkraft=) in model.py"
        if opt.get("klemmkraft") is not None:
            kraft, quelle = float(opt["klemmkraft"]), "festigkeit(…, klemmkraft=)"
        out.append({"schraube": schrauben[0] if schrauben else None, "kopf": kopf, "mutter": mutter,
                    "kraft": kraft, "d": d, "quelle": quelle})
    return out


def schreibe(st: Any, wunsch: dict[str, Any]) -> dict[str, Any]:
    """S3-Auftrag schreiben und um Stufe 4 ergänzen (``auftrag.json`` im selben Ordner)."""
    from kevcad_kernel.statik.festkoerper import auftrag as fa
    from kevcad_kernel.statik.werkstoff import reibwert

    job = fa.schreibe(st, wunsch)
    pfad = job["auftrag"]
    with open(pfad, encoding="utf-8") as fh:
        a = json.load(fh)
    m = st.modell
    opt = {k: wunsch.get(k) for k in ("kontakt", "plastisch", "traglast", "beulen", "klemmkraft", "reibwert",
                                      "verfestigung", "lastfaktor_max")}
    opt["kontakt"] = bool(opt.get("kontakt"))
    opt["plastisch"] = bool(opt.get("plastisch"))
    opt["traglast"] = bool(opt["plastisch"] if opt.get("traglast") is None else opt["traglast"])
    opt["beulen"] = bool(opt.get("beulen"))
    deklariert = _deklariert(st)
    erg = st.ergebnis or {}
    szen = {e.get("name"): e for e in erg.get("szenarien") or []}
    ordner = job["ordner"]
    for T in a["teile"]:
        name = T["name"]
        k = st.koerper[name]
        t = m.teile[name]
        w = _werkstoff_s4(m, st.katalog, name) or T["werkstoff"]
        T["werkstoff"] = w
        T["fliess"] = fliesskurve(w, w.get("gruppe") or "", bool(t.druckteil), T.get("schicht") is not None,
                                  verfestigung=wunsch.get("verfestigung", True)) if opt["plastisch"] else None
        T["verbindungen"] = {}
        T["koerper"] = {}
        bmin, bmax = np.asarray(k.bmin, float), np.asarray(k.bmax, float)
        nachbarn = set(T["nachbarn"])
        for f in T["faelle"]:
            # Kräfte beider Seiten je Stab (S1) an die Lasten hängen
            e = szen.get(f["szenario"]) or {}
            for last in f["lasten"]:
                x = last.get("kontakt_mit")
                if not x:
                    continue
                for quelle in (e.get("auflager") or []) + (e.get("verbinder") or []):
                    if quelle.get("stab") == x and quelle.get("teil") == name and quelle.get("seiten"):
                        last["seiten"] = quelle["seiten"]
                        break
            nachbarn |= set(f.get("lager") or []) | {l["kontakt_mit"] for l in f["lasten"] if l.get("kontakt_mit")}
        if opt["kontakt"]:
            for x in sorted(nachbarn):
                if x not in st.koerper:
                    continue
                art, quelle = verbindungsart(m, name, x, deklariert, getattr(st, "befestigt", None))
                rw = reibwert(st.katalog, t.material_id, (m.teile[x].material_id if x in m.teile else None))
                mu = float(rw.get("haft")) if rw and rw.get("haft") is not None else 0.3
                mu_quelle = (rw.get("quelle") if rw else "angenommen 0,3")
                for dk in deklariert:
                    if (name in dk["a"] and x in dk["b"]) or (name in dk["b"] and x in dk["a"]):
                        if dk.get("reibwert") is not None:
                            mu, mu_quelle = float(dk["reibwert"]), "st.kontakt in model.py"
                if opt.get("reibwert") is not None:
                    mu, mu_quelle = float(opt["reibwert"]), "festigkeit(…, reibwert=)"
                T["verbindungen"][x] = {"art": art, "quelle": quelle, "reibwert": mu, "reibwert_quelle": mu_quelle,
                                        "spiel": next((dk.get("spiel") for dk in deklariert if dk.get("spiel")
                                                       is not None and ((name in dk["a"] and x in dk["b"]) or
                                                                        (name in dk["b"] and x in dk["a"]))), None)}
                if art != "kontakt":
                    continue
                last_von = any(l.get("kontakt_mit") == x for f in T["faelle"] for l in f["lasten"])
                o = st.koerper[x]
                if last_von:  # elastisch, Schnitt quer zum Stab weit genug vom Teil
                    ext = np.sort(np.asarray(o.bmax, float) - np.asarray(o.bmin, float))
                    rand = max(15.0, 1.5 * float(ext[1]))
                    rolle = "last"
                    wx = _werkstoff_stab(m, x)
                else:
                    rand, rolle, wx = RAND_STARR, "lager", None
                lo, hi = bmin - rand, bmax + rand
                datei = os.path.join(ordner, f"koerper_{T['id']}_{len(T['koerper'])}.brep")
                if rolle == "last" and wx is None:
                    continue
                if not _zuschneiden(o, lo, hi, datei):
                    continue
                if x not in T["nachbarn"]:
                    npz = os.path.join(ordner, f"nachbar_{T['id']}_k{len(T['koerper'])}.npz")
                    if _netz_npz(st, x, bmin - fa.RAND_MM, bmax + fa.RAND_MM, npz):
                        T["nachbarn"][x] = {"datei": npz, "tol": fa._toleranz(m, name, x), "schluessel": o.key}
                gr = None
                if rolle == "last" and wx is not None:
                    gr = fliesskurve(wx, wx.get("gruppe") or "", False, True,
                                     verfestigung=wunsch.get("verfestigung", True)) if opt["plastisch"] else None
                T["koerper"][x] = {"brep": datei, "rolle": rolle, "werkstoff": wx, "fliess": gr,
                                   "box": [lo.tolist(), hi.tolist()], "schluessel": o.key,
                                   "groesse": float(np.max(np.asarray(o.bmax) - np.asarray(o.bmin)))}
            T["klemmungen"] = _klemmungen(st, name, opt, deklariert)
            for kl in T["klemmungen"]:
                for x in kl["kopf"] + kl["mutter"]:
                    if x in T["nachbarn"] or x not in st.koerper:
                        continue
                    npz = os.path.join(ordner, f"nachbar_{T['id']}_s{len(T['nachbarn'])}.npz")
                    if _netz_npz(st, x, bmin - fa.RAND_MM, bmax + fa.RAND_MM, npz):
                        T["nachbarn"][x] = {"datei": npz, "tol": 0.75, "schluessel": st.koerper[x].key}
        else:
            T["klemmungen"] = []
        # Schlüssel je Fall: Stufe 3 plus Optionen, Verbindungen, Körper, Klemmungen
        for f in T["faelle"]:
            schl = {"s3": f["schluessel"], "v": VERSION, "opt": opt, "fliess": T.get("fliess"),
                    "verb": T["verbindungen"], "koerper": {x: (v["schluessel"], v["rolle"], v["box"])
                                                           for x, v in T["koerper"].items()},
                    "klemm": T["klemmungen"], "seiten": [l.get("seiten") for l in f["lasten"]]}
            f["schluessel"] = "s4" + hashlib.sha1(json.dumps(schl, sort_keys=True, default=str).encode()
                                                   ).hexdigest()[:18]
    a["verfahren"] = "ccx"
    a["optionen"] = opt
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(a, fh, ensure_ascii=False)
    job["verfahren"] = "ccx"
    job["optionen"] = opt
    job["faelle"] = [{"id": f["id"], "szenario": f["szenario"], "teil": f["teil"], "schluessel": f["schluessel"],
                      "ziel": f["ziel"], "s0": f.get("s0")} for T in a["teile"] for f in T["faelle"]]
    return job
