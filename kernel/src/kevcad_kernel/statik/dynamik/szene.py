"""Szene für S2 aus dem Modell des letzten Laufs (läuft im Rechenprozess, auf Anfrage, ohne zu simulieren).

Aus Körpern, Kontakten und Zwangsbedingungen des letzten geprüften Laufs (``statik.anbindung.LETZTER``) entsteht eine
reine Datenbeschreibung, die der eigene Ablauf-Prozess (``prozess.py``) in ein MuJoCo-Modell übersetzt:

- **Starrkörper**: fest verbundene Teile sind ein Körper (``verbinde`` mit Schraube, Klemmung, Kleben, Formschluss,
  Steck samt ``mit``; Gelenke mit ``bereich`` gelten als festgestellt: Einstellungen wie Klemmen und Kopf). Teile ohne
  jede Bedingung hängen wie in Stufe 1 an dem, was sie berühren. ``aufliegen`` verbindet nicht: der Ball liegt frei auf
  dem Boden, ein Karton frei auf dem Regal.
- **Gelenke**: Dreh- und Schiebegelenke ohne ``bereich`` laufen frei (Laufrolle auf der Querstange), ebenso Gelenke mit
  ``frei=True`` (Schublade, Tür ohne Feststeller, T33); deren ``bereich`` wird zum Anschlag (``grenzen`` ab der Lage
  in model.py, Grad bzw. mm). Räder rollen um die
  Achse aus der Animation (``anim.rolle(…, achse=…)``) oder, ohne Animation, um die Achse ihrer größten Zylinderfläche
  (Teile mit Rad/Rolle im Namen auf dem Boden).
- **Masse, Schwerpunkt, Trägheit** je Teil aus der B-Rep (OCC, Dichte aus Masse und Volumen der Stückliste), je Körper
  mit dem Satz von Steiner zusammengefasst.
- **Kollision**: je Teil Kugel, Drehteil, Hülle oder CoACD (``formen.py``); Kontaktpaare nur zwischen Teilen
  verschiedener Körper, die sich nahe kommen können, und gegen den Boden. Reibwerte je Paarung aus ``reibwerte.json``.

Ergebnis: ``(meta, felder)``: ``meta`` JSON-tauglich, ``felder`` numpy-Felder (Hüllen, Netze für CoACD), zusammen als
``.npz`` geschrieben (``schreibe``/``lese``). Einheiten mm, kg; Trägheit kg·mm² um den Schwerpunkt, Weltachsen.
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np

from kevcad_kernel.statik.dynamik import formen as fm

FEST = ("schraube", "klemmung", "kleben", "formschluss", "steck")
BODEN_TOL = 0.5
KLEIN_MM = 3.0  # kleinere Teile bekommen keine Kollisionsform
RAD_WORTE = ("rad", "rolle", "wheel", "caster")
VERSION = 1


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


# ---------------------------------------------------------------------------------------------------------------------
# Masse und Trägheit


def traegheit_teil(k: Any, masse: float) -> tuple[np.ndarray, np.ndarray]:
    """(Schwerpunkt mm, Trägheitstensor kg·mm² um den Schwerpunkt, Weltachsen) eines Teils aus der B-Rep; ohne B-Rep
    aus dem Netz (Divergenzsatz), zur Not als Quader."""
    try:
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(k.shape, g)
        vol = float(g.Mass())
        if vol > 1e-9:
            c = g.CentreOfMass()
            M = g.MatrixOfInertia()
            I = np.array([[M.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)]) * (masse / vol)
            return np.array([c.X(), c.Y(), c.Z()]), 0.5 * (I + I.T)
    except Exception:  # noqa: BLE001 - Netz als Rückfall
        pass
    try:
        return _traegheit_netz(k.pos, k.tri, masse)
    except Exception:  # noqa: BLE001
        ext = np.asarray(k.bmax, float) - np.asarray(k.bmin, float)
        a, b, c = ext
        I = masse / 12 * np.diag([b * b + c * c, a * a + c * c, a * a + b * b])
        return (np.asarray(k.bmin, float) + np.asarray(k.bmax, float)) / 2, I


def _traegheit_netz(pos: np.ndarray, tri: np.ndarray, masse: float) -> tuple[np.ndarray, np.ndarray]:
    """Volumen, Schwerpunkt und Trägheit eines geschlossenen Dreiecksnetzes (Tetraeder zum Ursprung)."""
    P = np.asarray(pos, float)
    T = np.asarray(tri, int)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    v = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    V = float(v.sum())
    if abs(V) < 1e-9:
        raise ValueError("Netz ohne Volumen")
    if V < 0:
        v, V = -v, -V
    cen = ((a + b + c) / 4.0 * v[:, None]).sum(axis=0) / V
    # Kovarianz je Tetraeder (Ursprung, a, b, c): C = v/20 · (Σ x xᵀ + (Σ x)(Σ x)ᵀ)
    s = a + b + c
    C = (np.einsum("i,ij,ik->jk", v, a, a) + np.einsum("i,ij,ik->jk", v, b, b) + np.einsum("i,ij,ik->jk", v, c, c)
         + np.einsum("i,ij,ik->jk", v, s, s)) / 20.0
    C = C - V * np.outer(cen, cen)
    rho = masse / V
    I = rho * (np.trace(C) * np.eye(3) - C)
    return cen, I


def zusammenfassen(teile: list[tuple[float, np.ndarray, np.ndarray]]) -> tuple[float, np.ndarray, np.ndarray]:
    """(Masse, Schwerpunkt, Trägheit um den Schwerpunkt) eines Körpers aus (m, c, I) seiner Teile (Steiner)."""
    m = sum(t[0] for t in teile)
    if m <= 0:
        c = np.mean([t[1] for t in teile], axis=0)
        return 0.0, c, np.zeros((3, 3))
    c = sum(t[0] * t[1] for t in teile) / m
    I = np.zeros((3, 3))
    for mi, ci, Ii in teile:
        d = ci - c
        I += Ii + mi * (float(d @ d) * np.eye(3) - np.outer(d, d))
    return m, c, 0.5 * (I + I.T)


# ---------------------------------------------------------------------------------------------------------------------
# Aufbau


def _bbox_abstand(a_min, a_max, b_min, b_max) -> float:
    lo = np.maximum(a_min, b_min)
    hi = np.minimum(a_max, b_max)
    gap = np.maximum(lo - hi, 0.0)
    return float(np.linalg.norm(gap))


def _anzeige(teile: list[str], masse: dict[str, float]) -> str:
    if len(teile) == 1:
        return teile[0]
    # gemeinsame Baugruppe mit mindestens zwei Ebenen (Rad und Felge: "Rollwagen/Lenkrolle 3")
    pfade = [n.split("/")[:-1] for n in teile]
    gemein = []
    for ebene in zip(*pfade):
        if len(set(ebene)) != 1:
            break
        gemein.append(ebene[0])
    if len(gemein) >= 2:
        return "/".join(gemein)
    gruppen: dict[str, float] = {}
    for n in teile:
        g = n.split("/")[0]
        gruppen[g] = gruppen.get(g, 0.0) + masse.get(n, 0.0)
    reihen = sorted(gruppen, key=lambda g: -gruppen[g])
    name = reihen[0]
    if len(reihen) > 1:
        name += " mit " + ", ".join(reihen[1:3]) + (" …" if len(reihen) > 3 else "")
    return f"{name} ({len(teile)} Teile)"


def baue(letzter: Any, auftrag: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Szene aus ``LETZTER`` (Modell, Körper, Katalog des letzten Laufs). ``auftrag``: ``spins`` (Teil → [Punkt,
    Richtung] rollender Teile aus der Animation), ``antrieb`` (Teil oder Gruppe, die geschoben wird), ``run``,
    ``szenario`` (Lager je Lastfall: dessen feste Lager gelten als befestigt), ``untergruende`` (Untergründe je
    Lastfall: Reibwerte der Bodenpaare zusätzlich je Untergrund, ``boden_mu_je``)."""
    from kevcad_kernel.statik.modell import _bedingungen
    from kevcad_kernel.statik.werkstoff import reibwert

    t0 = time.perf_counter()
    auftrag = auftrag or {}
    m = letzter.modell
    K = letzter.koerper
    katalog = letzter.katalog
    boden_z = float(m.boden_z)
    namen = [n for n in m.teile if n in K]
    hinweise: list[str] = []
    verb, gel = _bedingungen(set(K))
    hat_bedingung = {n: False for n in namen}
    for v in verb:
        for n in [v["a"], v["b"], *v["mit"]]:
            if n in hat_bedingung:
                hat_bedingung[n] = True
    for g in gel:
        for n in (g["a"], g["b"]):
            if n in hat_bedingung:
                hat_bedingung[n] = True

    # Gelenke, die frei laufen (ohne Bereich), und rollende Teile ---------------------------------------------------
    gelenke: list[dict[str, Any]] = []  # {"kind": [Teile], "an": Teil, "art", "punkt", "achse", "quelle"}
    in_gelenk: dict[str, int] = {}
    for g in gel:
        a, b = g["a"], g["b"]
        if a not in hat_bedingung or b not in hat_bedingung or g["art"] not in ("dreh", "schiebe", "zylinder"):
            continue
        if g.get("festgestellt") or g.get("achse") is None or g.get("punkt") is None:
            continue  # mit Bereich festgestellt (T15, T30), außer frei=True (T33)
        if a in in_gelenk:
            hinweise.append(f"{a}: mehrere freie Gelenke, nur das erste gerechnet")
            continue
        kind = [a] + [x for x in g.get("mitbewegt") or [] if x in hat_bedingung and x not in in_gelenk and x != b]
        i = len(gelenke)
        art = "schiebe" if g["art"] == "schiebe" else "dreh"
        name = "Schiebe" if art == "schiebe" else "Dreh"
        # frei mit Bereich (Schublade, Tür): läuft frei bis an die Enden des Bereichs, gezählt ab der Lage in model.py
        grenzen = None
        if g.get("bereich") is not None and g["art"] in ("dreh", "schiebe"):
            w = float(g.get("wert") or 0.0)
            grenzen = [float(g["bereich"][0]) - w, float(g["bereich"][1]) - w]
        gelenke.append({"kind": kind, "an": b, "art": art,
                        "punkt": np.asarray(g["punkt"], float), "achse": np.asarray(g["achse"], float),
                        "grenzen": grenzen,
                        "quelle": (f"{name}gelenk frei mit Bereich {g['bereich'][0]:g} … {g['bereich'][1]:g}"
                                   if g.get("bereich") is not None else f"{name}gelenk ohne Bereich")
                                  + (f" (model.py Zeile {g['zeile']})" if g.get("zeile") else "")})
        for n in kind:
            in_gelenk[n] = i
    # Räder: aus der Animation (rolle mit Achse) oder nach Name und Zylinderachse
    spins = {n: (np.asarray(v[0], float), np.asarray(v[1], float)) for n, v in (auftrag.get("spins") or {}).items()
             if n in hat_bedingung}
    rad_quelle = "Achse aus der Animation (rolle)"
    if not spins:
        rad_quelle = "Achse der größten Zylinderfläche (Rad nach Name)"
        for n in namen:
            k = K[n]
            if not any(w in n.rsplit("/", 1)[-1].lower() for w in RAD_WORTE) or k.bmin[2] > boden_z + BODEN_TOL:
                continue
            achsen = k.zylinder_achsen(1)
            if achsen and abs(float(achsen[0][2])) < 0.3:
                spins[n] = ((np.asarray(k.bmin) + np.asarray(k.bmax)) / 2, achsen[0])
    # nur waagrechte Achsen, deren Achsgruppe auf dem Boden steht (Rad mit Felge)
    linien: list[dict[str, Any]] = []
    for n, (p, d) in spins.items():
        if n in in_gelenk or abs(float(d[2])) > 0.3 * float(np.linalg.norm(d)):
            continue
        d = d / np.linalg.norm(d)
        for li in linien:
            off = p - li["p"]
            if abs(abs(float(d @ li["d"])) - 1) < 1e-4 and np.linalg.norm(off - (off @ li["d"]) * li["d"]) < 0.5:
                li["teile"].append(n)
                break
        else:
            linien.append({"p": p, "d": d, "teile": [n]})
    # je Achslinie die zusammenhängenden Teile (Rad mit Felge): zwei Räder auf derselben Linie bleiben getrennt
    beruehrt: dict[str, set[str]] = {}
    for e in m.kanten.values():
        beruehrt.setdefault(e["a"], set()).add(e["b"])
        beruehrt.setdefault(e["b"], set()).add(e["a"])
    for li in linien:
        uf_l = _UF(li["teile"])
        for a in li["teile"]:
            for b in beruehrt.get(a, ()):
                if b in uf_l.p:
                    uf_l.union(a, b)
        gr: dict[str, list[str]] = {}
        for n in li["teile"]:
            gr.setdefault(uf_l.find(n), []).append(n)
        for teile in gr.values():
            if not any(K[n].bmin[2] <= boden_z + BODEN_TOL for n in teile):
                continue
            if any(fm.kugel(fm.huelle(K[n].pos)[0]) for n in teile):
                continue
            i = len(gelenke)
            gelenke.append({"kind": sorted(teile), "an": None, "art": "dreh", "punkt": li["p"], "achse": li["d"],
                            "quelle": f"Rad: {rad_quelle}", "rad": True})
            for n in teile:
                in_gelenk[n] = i

    # Starrkörper (Union-Find) ----------------------------------------------------------------------------------------
    uf = _UF(namen)
    anhaengen: dict[int, list[str]] = {i: [] for i in range(len(gelenke))}  # Gelenk → Teile, an denen es hängt

    def verbinden(a: str, b: str) -> None:
        if a not in uf.p or b not in uf.p:
            return
        ga, gb = in_gelenk.get(a), in_gelenk.get(b)
        if ga != gb:  # über eine Gelenkgrenze: nicht fest, aber merken, woran das Gelenk hängt
            if ga is not None:
                anhaengen[ga].append(b)
            if gb is not None:
                anhaengen[gb].append(a)
            return
        uf.union(a, b)

    welt: dict[str, str] = {}
    frei_auf: list[str] = []
    kontakt_von: dict[str, set[str]] = {}
    for e in m.kanten.values():
        if e["kontakt"] in ("beruehrt", "durchdringt"):
            kontakt_von.setdefault(e["a"], set()).add(e["b"])
            kontakt_von.setdefault(e["b"], set()).add(e["a"])
    for v in verb:
        a, b, art = v["a"], v["b"], v["art"]
        if a not in uf.p:
            continue
        for f in v["mit"]:
            verbinden(a, f)
        if b == "boden":
            if art in FEST:
                welt[a] = f"verbinde(…, boden, art=\"{art}\")"
            continue
        if b in m.kulisse:
            if art in FEST:
                welt[a] = f"an {b} ({art})"
            continue
        if art in FEST:
            verbinden(a, b)
            for f in v["mit"]:
                verbinden(b, f)
        elif art == "aufliegen" and b in uf.p:
            # liegt frei auf b, außer andere Teile klemmen es ein (Platte unter Muttern): dann fest
            andere = kontakt_von.get(a, set()) - {b} - set(v["mit"])
            if andere:
                verbinden(a, b)
            else:
                frei_auf.append(f"{a} liegt frei auf {b}")
    for g in gel:
        a, b = g["a"], g["b"]
        if a not in uf.p or b not in uf.p:
            continue
        frei = not g.get("festgestellt") and g["art"] in ("dreh", "schiebe", "zylinder") \
            and in_gelenk.get(a) is not None
        if frei:
            continue
        verbinden(a, b)
        for x in g.get("mitbewegt") or []:
            verbinden(a, x)
    for i, gj in enumerate(gelenke):
        for x in gj["kind"][1:]:
            uf.union(gj["kind"][0], x)
        if gj["an"] is not None:
            anhaengen[i].append(gj["an"])
    for e in m.kanten.values():
        a, b = e["a"], e["b"]
        if a not in uf.p or b not in uf.p or e["verbinde"] or e["gelenk"]:
            continue
        if e["kontakt"] not in ("beruehrt", "durchdringt"):
            continue
        if a in m.rollend or b in m.rollend:
            continue
        if not hat_bedingung[a] or not hat_bedingung[b]:
            verbinden(a, b)
    fest_teile = (letzter.befestigt_fuer(auftrag.get("szenario")) if hasattr(letzter, "befestigt_fuer")
                  else getattr(letzter, "befestigt", {}))
    for n in m.teile:
        if n in fest_teile and n not in welt:
            welt[n] = "befestigt"

    gruppen: dict[str, list[str]] = {}
    for n in namen:
        gruppen.setdefault(uf.find(n), []).append(n)
    masse = {n: float(m.teile[n].masse_kg) for n in namen}
    koerper: list[dict[str, Any]] = []
    teil_koerper: dict[str, str] = {}
    traeg: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for n in namen:
        traeg[n] = traegheit_teil(K[n], masse[n])
    for i, (_, teile) in enumerate(sorted(gruppen.items(), key=lambda kv: (-sum(masse[n] for n in kv[1]), kv[1][0])),
                                   1):
        teile = sorted(teile)
        mk, ck, Ik = zusammenfassen([(masse[n], traeg[n][0], traeg[n][1]) for n in teile])
        kid = f"K{i}"
        bmin = np.min([K[n].bmin for n in teile], axis=0)
        bmax = np.max([K[n].bmax for n in teile], axis=0)
        boden = [n for n in teile if K[n].bmin[2] <= boden_z + BODEN_TOL]
        koerper.append({"id": kid, "name": _anzeige(teile, masse), "teile": teile, "masse": mk,
                        "schwerpunkt": ck.tolist(), "traegheit": Ik.tolist(), "bmin": bmin.tolist(),
                        "bmax": bmax.tolist(), "boden": boden, "art": "frei", "eltern": None, "gelenk": None,
                        "welt": next((welt[n] for n in teile if n in welt), None),
                        "masse_angenommen": [n for n in teile if m.teile[n].masse_angenommen]})
        for n in teile:
            teil_koerper[n] = kid
    kmap = {k["id"]: k for k in koerper}
    for i, gj in enumerate(gelenke):
        kid = teil_koerper[gj["kind"][0]]
        k = kmap[kid]
        an = [teil_koerper[x] for x in anhaengen[i] if x in teil_koerper and teil_koerper[x] != kid]
        if not an:
            hinweise.append(f"{gj['kind'][0]}: Gelenk ohne Gegenstück, läuft frei")
            continue
        eltern = max(set(an), key=lambda x: (an.count(x), kmap[x]["masse"]))
        k["art"] = gj["art"]
        k["eltern"] = eltern
        k["gelenk"] = {"art": gj["art"], "punkt": np.asarray(gj["punkt"], float).tolist(),
                       "achse": (np.asarray(gj["achse"], float) / np.linalg.norm(gj["achse"])).tolist(),
                       "quelle": gj["quelle"], "rad": bool(gj.get("rad")), "grenzen": gj.get("grenzen")}
    # Kreise in der Elternkette aufbrechen
    for k in koerper:
        seen = {k["id"]}
        cur = k["eltern"]
        while cur is not None:
            if cur in seen:
                hinweise.append(f"{k['name']}: Gelenke bilden einen Kreis, Gelenk gelöst")
                k["art"], k["eltern"], k["gelenk"] = "frei", None, None
                break
            seen.add(cur)
            cur = kmap[cur]["eltern"]
    for k in koerper:
        if k["eltern"] is None and k["welt"]:
            k["art"] = "welt"

    # Wurzel (Körper ohne Eltern) und Teilbaum
    def wurzel(kid: str) -> str:
        while kmap[kid]["eltern"] is not None:
            kid = kmap[kid]["eltern"]
        return kid

    for k in koerper:
        k["wurzel"] = wurzel(k["id"])
    # Antrieb: geschobener Körper ----------------------------------------------------------------------------------
    antrieb = None
    wunsch = auftrag.get("antrieb")
    if wunsch:
        treffer = m.aufloesen(str(wunsch))
        if not treffer:
            raise ValueError(f"Teil oder Gruppe {wunsch!r} zum Schieben gibt es nicht")
        ks = [wurzel(teil_koerper[n]) for n in treffer if n in teil_koerper]
        antrieb = max(set(ks), key=lambda x: sum(masse[n] for n in treffer if n in teil_koerper
                                                    and wurzel(teil_koerper[n]) == x))
    else:
        def bodenpunkte(kid: str) -> int:
            return sum(len(kmap[c]["boden"]) for c in kmap if kmap[c]["wurzel"] == kid)

        frei = [k for k in koerper if k["eltern"] is None and k["art"] == "frei"]
        steht = [k for k in frei if bodenpunkte(k["id"]) >= 3]
        kand = steht or frei
        if kand:
            antrieb = max(kand, key=lambda k: sum(kmap[c]["masse"] for c in kmap if kmap[c]["wurzel"] == k["id"]))["id"]
    if antrieb is not None:
        kmap[antrieb]["art"] = "antrieb"

    # Kollisionsformen -----------------------------------------------------------------------------------------------
    felder: dict[str, np.ndarray] = {}
    kollision: dict[str, dict[str, Any]] = {}
    for n in namen:
        k = K[n]
        t = m.teile[n]
        groesse = float(np.max(np.asarray(k.bmax) - np.asarray(k.bmin)))
        if t.verbindungselement or groesse < KLEIN_MM or len(k.pos) < 4:
            continue
        kid = teil_koerper[n]
        hv, eb = fm.huelle(k.pos)
        if len(hv) < 4:
            continue
        info: dict[str, Any] = {"art": "huelle", "koerper": kid, "material": t.material_id, "groesse": groesse}
        kg = fm.kugel(hv)
        gj = kmap[kid]["gelenk"]
        if kg is not None:
            info.update(art="kugel", mitte=kg[0].tolist(), radius=kg[1])
        elif gj is not None and gj["art"] == "dreh":
            pr = fm.drehprofil(k.pos, np.asarray(gj["punkt"]), np.asarray(gj["achse"]))
            if pr is not None:
                info.update(art="drehteil", punkt=gj["punkt"], achse=gj["achse"],
                            profil=[pr[0].tolist(), pr[1].tolist()])
                zy = fm.zylinder_aus_profil(pr) if gj.get("rad") else None
                if zy is not None:
                    info["zylinder"] = list(zy)
        felder[f"h:{n}"] = hv.astype(np.float32)
        info["_ebenen"] = eb
        kollision[n] = info
    # Kulisse (außer dem Boden selbst) als feste Formen
    for n in sorted(m.kulisse):
        k = K.get(n)
        if k is None or float(k.bmax[2]) <= boden_z + 1.0:
            continue
        hv, eb = fm.huelle(k.pos)
        if len(hv) >= 4:
            felder[f"h:{n}"] = hv.astype(np.float32)
            kollision[n] = {"art": "huelle", "koerper": "welt", "material": (K[n].info or {}).get("material_id")
                            or (K[n].info or {}).get("material"), "groesse": float(np.max(k.bmax - k.bmin)),
                            "_ebenen": eb, "kulisse": True}

    # Paare zwischen Körpern, die sich nahe kommen können -------------------------------------------------------------
    def verwandt(a: str, b: str) -> bool:
        return kmap.get(a, {}).get("eltern") == b or kmap.get(b, {}).get("eltern") == a

    groesse_k = {k["id"]: float(np.max(np.asarray(k["bmax"]) - np.asarray(k["bmin"]))) for k in koerper}
    kol = list(kollision)
    paare: list[list[str]] = []
    for i, a in enumerate(kol):
        ka = kollision[a]["koerper"]
        for b in kol[i + 1:]:
            kb = kollision[b]["koerper"]
            if ka == kb or (ka == "welt" and kb == "welt") or verwandt(ka, kb):
                continue
            if ka != "welt" and kb != "welt" and kmap[ka]["wurzel"] == kmap[kb]["wurzel"] \
                    and kmap[ka]["art"] in ("dreh", "schiebe") and kmap[kb]["art"] in ("dreh", "schiebe") \
                    and kmap[ka]["eltern"] == kmap[kb]["eltern"]:
                pass  # zwei Räder am selben Wagen: können sich berühren, wenn auch selten
            ga = groesse_k.get(ka, 1e9) if ka != "welt" else 1e9
            gb = groesse_k.get(kb, 1e9) if kb != "welt" else 1e9
            reach = max(30.0, 0.5 * min(ga, gb))
            if _bbox_abstand(np.asarray(K[a].bmin), np.asarray(K[a].bmax), np.asarray(K[b].bmin),
                             np.asarray(K[b].bmax)) <= reach:
                paare.append([a, b])
    hoehe = {k["id"]: float(k["bmax"][2] - k["bmin"][2]) for k in koerper}
    boden_paare = [n for n, c in kollision.items() if c["koerper"] != "welt"
                   and float(K[n].bmin[2]) - boden_z <= max(150.0, 0.6 * hoehe[kmap[c["koerper"]]["wurzel"]])]

    # Mulden: liegen Punkte eines Nachbarn in der Hülle, ohne das Teil zu berühren, braucht es die genaue Form (CoACD)
    nachbarn: dict[str, list[str]] = {}
    for a, b in paare:
        nachbarn.setdefault(a, []).append(b)
        nachbarn.setdefault(b, []).append(a)
    coacd_teile: list[str] = []
    for n, c in kollision.items():
        if c["art"] in ("kugel", "drehteil") or n not in nachbarn:
            continue
        pts = []
        for q in nachbarn[n]:
            P = K[q].pos
            pts.append(P[:: max(1, len(P) // 1500)])
        P = np.vstack(pts)
        innen = fm.abstand_zur_huelle(c["_ebenen"], P) < -0.3
        if not np.any(innen):
            continue
        # berührt der Nachbar das Teil selbst dort? (dann keine Mulde, sondern Kontakt oder Durchdringung)
        from scipy.spatial import cKDTree

        dist, _ = cKDTree(K[n].pos).query(P[innen], k=1)
        if float(np.min(dist)) > 1.0:
            c["art"] = "coacd"
            c["form"] = K[n].form
            lage = np.asarray(K[n].lage, float)
            c["lage"] = lage.tolist()
            if not fm.coacd_im_cache(K[n].form):
                inv = np.linalg.inv(lage)
                felder[f"n:{n}"] = (K[n].pos @ inv[:3, :3].T + inv[:3, 3]).astype(np.float64)
                felder[f"t:{n}"] = np.asarray(K[n].tri, dtype=np.int64)
            coacd_teile.append(n)

    # Reibwerte -------------------------------------------------------------------------------------------------------
    from kevcad_kernel.statik.s0 import MU_ANNAHME

    reib: dict[str, dict[str, Any]] = {}
    angenommen: set[str] = set()

    def mu(a: str | None, b: str | None) -> float:
        key = f"{a}|{b}"
        if key not in reib:
            r = reibwert(katalog, a, b) if a and b else None
            if r is None:
                reib[key] = {"mu": MU_ANNAHME, "angenommen": True}
                angenommen.add(f"{a or 'unbekannt'} auf {b or 'unbekannt'}")
            else:
                reib[key] = {"mu": float(r.get("haft") or MU_ANNAHME), "quelle": r.get("quelle"),
                             "paarung": r.get("paarung")}
        return reib[key]["mu"]

    paar_mu = [mu(kollision[a]["material"], kollision[b]["material"]) for a, b in paare]
    boden_mu = [mu(kollision[n]["material"], m.untergrund) for n in boden_paare]
    # Untergrund je Lastfall (Simulation): dieselben Bodenpaare mit dem Reibwert gegen diesen Boden
    boden_mu_je = {str(u): [mu(kollision[n]["material"], str(u)) for n in boden_paare]
                   for u in dict.fromkeys(auftrag.get("untergruende") or []) if u}

    for c in kollision.values():
        c.pop("_ebenen", None)
    meta = {
        "version": VERSION, "run": auftrag.get("run"), "boden_z": boden_z, "untergrund": m.untergrund,
        "koerper": koerper, "kollision": kollision, "paare": paare, "paar_mu": paar_mu, "boden_paare": boden_paare,
        "boden_mu": boden_mu, "boden_mu_je": boden_mu_je, "antrieb": antrieb, "coacd": coacd_teile,
        "reibung_angenommen": sorted(angenommen), "hinweise": hinweise, "frei_auf": frei_auf,
        "masse_gesamt": float(sum(masse.values())),
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    return _sauber(meta), felder


def _sauber(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _sauber(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_sauber(v) for v in x]
    if isinstance(x, np.ndarray):
        return _sauber(x.tolist())
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def schreibe(meta: dict[str, Any], felder: dict[str, np.ndarray], pfad: str) -> None:
    np.savez(pfad, __meta__=np.frombuffer(json.dumps(meta, ensure_ascii=False).encode("utf-8"), dtype=np.uint8),
             **{f"f{i}": v for i, v in enumerate(felder.values())},
             __namen__=np.frombuffer(json.dumps(list(felder)).encode("utf-8"), dtype=np.uint8))


def lese(pfad: str) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    with np.load(pfad) as z:
        meta = json.loads(bytes(z["__meta__"]).decode("utf-8"))
        namen = json.loads(bytes(z["__namen__"]).decode("utf-8"))
        felder = {n: z[f"f{i}"] for i, n in enumerate(namen)}
    return meta, felder
