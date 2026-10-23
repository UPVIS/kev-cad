"""FEM-Prozess (S3): ``python -m kevcad_kernel.statik.festkoerper.prozess <auftrag.json> <ergebnis.json>``.

Läuft getrennt vom Rechenprozess von model.py und von der Laufzeit; Gmsh, scikit-fem und pyamg werden nur hier
geladen (und nur, wenn etwas zu rechnen ist). Fortschritt als JSON-Zeilen auf stdout (``{"fortschritt": 0.4,
"text": "…"}``), Ergebnis als Datei; die Laufzeit bricht durch Beenden des Prozesses ab.

Je Teil: Netz (Zwischenspeicher je Teilstand und Netzeinstellung), Steifigkeit einmal, Lagerflächen je Nachbar, dann
je Lagerung alle Lastfälle mit einer Zerlegung bzw. einem AMG-Aufbau. Ergebnis je Fall (Zwischenspeicher je Schlüssel,
siehe ``auftrag``): Sicherheit, maßgebendes Kriterium, Ort, Verformung, Sicherheit in den anderen Drucklagen und das
Oberflächennetz mit Ausnutzung, von-Mises-Spannung und Verschiebung je Punkt (für STATICS_FIELD).

Lager (simulation2): fest (Fläche eingespannt), gleitend (an jedem Ort der Fläche nur die gehaltenen Richtungen, genau
auch schräg) und gelenkig (Fläche wie ein RBE3 an einem festen Bezugspunkt: mittlere Verschiebung null, mittlere Drehung
nur um die gehaltenen Achsen null, sonst frei). Sobald ein gleitendes oder gelenkiges Lager dabei ist, rechnet der Löser
mit Zwangsbedingungen (``loeser.Zwang``) und prüft vorher, ob die Lager das Teil in allen sechs Richtungen halten. Je
Lager steht die Lagerkraft im Ergebnis (``lagerkraefte``). Lasten auf der ganzen Fläche (``flaeche_datei``): gleichmäßig
(Kraft / Fläche) oder als Druck senkrecht auf jedes Dreieck. Für „Grenze suchen“ mit der FEM schreibt der Prozess die
Spannungen je Knoten mit (``<schluessel>.sig.npz``) und sucht die Grenze je Teil durch Halbieren über die Überlagerung
der gerechneten Fälle (``grenzen_suchen``).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.statik.festkoerper import GRENZEN_S3, VERSION

LAST_RADIUS = (0.1, 3.0, 25.0)  # Lastfläche um einen Punkt: Anteil der Teilgröße, mindestens, höchstens (mm)
FLAECHE_TOL = 0.35  # mm: Randdreiecke einer Lastfläche (Netz der B-Rep-Fläche)
GRENZE_MAX = 1000.0  # Lastfaktor höchstens
GRENZE_SCHRITTE = 16


def _lager_art(nb: dict[str, Any]) -> str:
    """Art eines Lagers (Nachbar): gelenkig, gleitend oder fest (Kontakt mit einem Nachbarn ist fest)."""
    if nb.get("art") == "gelenkig" or nb.get("gelenkig"):
        return "gelenkig"
    if nb.get("gehalten") or nb.get("komponenten"):
        return "gleitend"
    return "fest"


def _gehalten(nb: dict[str, Any]) -> list[list[float]]:
    if nb.get("gehalten"):
        return [list(map(float, h)) for h in nb["gehalten"]]
    return [[1.0 if i == int(c) else 0.0 for i in range(3)] for c in nb.get("komponenten") or []]


def _flaechen_facetten(N: Any, datei: str, tol: float = FLAECHE_TOL) -> np.ndarray:
    """Randdreiecke des FEM-Netzes auf einer B-Rep-Fläche (Netz der Fläche): Schwerpunkt nah an ihr und Normale wie
    das nächste Dreieck der Fläche (keine Nachbarflächen an den Kanten)."""
    from scipy.spatial import cKDTree

    from kevcad_kernel.statik.festkoerper import kontakt

    with np.load(datei) as z:
        P, T = np.asarray(z["pos"], float), np.asarray(z["tri"], np.int64)
    if len(T) == 0:
        return np.zeros(0, dtype=np.int64)
    d = kontakt.abstand(N.rand_mitte, P, T, tol)
    sel = np.flatnonzero(np.isfinite(d))
    if len(sel) == 0:
        return sel
    X = P[T]
    n = np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
    _, j = cKDTree(X.mean(axis=1)).query(N.rand_mitte[sel])
    return sel[np.einsum("ij,ij->i", N.rand_normale[sel], n[j]) > 0.5]


def speicher() -> Path:
    p = os.environ.get("KEVCAD_FESTKOERPER_CACHE")
    if p:
        return Path(p)
    bundle = os.environ.get("KEVCAD_APP_BUNDLE_ID") or "de.upvis.kevcad"
    return Path.home() / "Library" / "Caches" / bundle / "festkoerper"


def melde(fortschritt: float, text: str) -> None:
    print(json.dumps({"fortschritt": round(max(0.0, min(1.0, fortschritt)), 3), "text": text}, ensure_ascii=False),
          flush=True)


def _schreibe_npz(pfad: Path, **felder: Any) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + f".{os.getpid()}.tmp.npz")
    np.savez(tmp, **felder)
    os.replace(tmp, pfad)


def lies_fall(pfad: Path) -> dict[str, Any] | None:
    """Fall aus dem Zwischenspeicher: Kurzfassung (``info``) und Felder."""
    try:
        with np.load(pfad) as z:
            info = json.loads(bytes(z["info"]).decode("utf-8"))
            info["_felder"] = {k: z[k] for k in z.files if k != "info"}
        return info
    except Exception:  # noqa: BLE001 - kaputter Eintrag: neu rechnen
        return None


def _netz(T: dict[str, Any], fein: bool, ablage: Path) -> tuple[dict[str, Any], bool]:
    from kevcad_kernel.statik.festkoerper import netz

    schl = {"v": VERSION, "teil": T["schluessel_teil"], "fein": fein, "h": T.get("h_mm"),
            "max": [netz.MAX_TET, netz.MAX_TET_FEIN, netz.WAND_ANTEIL, netz.KRUEMMUNG]}
    if T.get("verfeinern"):  # Stufe 4 (additiv): örtliche Verfeinerung, etwa am Punktkontakt
        schl["verfeinern"] = T["verfeinern"]
    key = hashlib.sha1(json.dumps(schl, sort_keys=True).encode()).hexdigest()[:20]
    pfad = ablage / "netze" / f"{key}.npz"
    if pfad.exists():
        try:
            with np.load(pfad) as z:
                return {k: z[k] for k in z.files} | {"h": float(z["h"]), "ms": 0.0}, True
        except Exception:  # noqa: BLE001
            pass
    n = netz.vernetze(T["brep"], fein=fein, h_vorgabe=T.get("h_mm"), verfeinern=T.get("verfeinern"))
    _schreibe_npz(pfad, p=n["p"], t=n["t"], rand=n["rand"], flaeche=n["flaeche"], h=np.float64(n["h"]))
    return n, False


def _lastflaeche(N: Any, punkt: np.ndarray, groesse: float, h: float) -> np.ndarray:
    """Randdreiecke um den Punkt: auf derselben B-Rep-Fläche wie das nächste Randdreieck, im Umkreis r."""
    d = np.linalg.norm(N.rand_mitte - punkt[None, :], axis=1)
    j0 = int(np.argmin(d))
    anteil, rmin, rmax = LAST_RADIUS
    r = min(max(anteil * groesse, rmin, 2 * h), rmax)
    for _ in range(4):
        nah = d <= d[j0] + r
        if N.rand_brep[j0] >= 0:
            sel = np.where(nah & (N.rand_brep == N.rand_brep[j0]))[0]
        else:
            sel = np.where(nah & (N.rand_normale @ N.rand_normale[j0] > 0.7))[0]
        if N.rand_flaeche_mm2[sel].sum() >= 1.0:
            return sel
        r *= 2
    return np.array([j0])


def _bewerten(N: Any, u: np.ndarray, C: np.ndarray, T: dict[str, Any], fall: dict[str, Any], fest_knoten: np.ndarray
              ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    from kevcad_kernel.statik.festkoerper import werkstoff as wk

    w = T["werkstoff"]
    s = N.spannung(u, C)
    vm = wk.mises(s)
    i_m, i_s = wk.index(s, w["f"], w.get("q"), T.get("schicht") if T["druckteil"] else None)
    if T["druckteil"] and i_s is None:  # Drucklage unbekannt: überall wie quer zur Schicht (wie S0)
        idx = i_m / float(w.get("q") or 0.5)
        krit = np.full(len(idx), 2)
    elif i_s is not None:
        idx = np.maximum(i_m, i_s)
        krit = np.where(i_s > i_m, 1, 0)
    else:
        idx = i_m
        krit = np.zeros(len(idx), dtype=np.int64)
    # Auf der Lagerfläche selbst ist die Spannung eine Folge der starren Einspannung (Querdehnung behindert, Kante
    # singulär): gewertet wird ab dem ersten Knoten neben der Lagerfläche, die Spitze am Lagerrand steht daneben.
    frei = np.ones(N.n, dtype=bool)
    frei[fest_knoten] = False
    if not frei.any():
        frei[:] = True
    kandidaten = np.where(frei)[0]
    k = int(kandidaten[np.argmax(idx[kandidaten])])
    k_rand = int(np.argmax(idx))
    sicherheit = 1.0 / float(idx[k]) if idx[k] > 0 else math.inf
    v = N.verschiebung(u)
    vb = np.linalg.norm(v, axis=1)
    ziel = float(fall["ziel"])
    alt = {}
    if T["druckteil"]:
        for name, n in (T.get("ausrichtungen") or {}).items():
            a_m, a_s = wk.index(s, w["f"], w.get("q"), np.asarray(n))
            alt[name] = round(1.0 / float(np.max(np.maximum(a_m, a_s)[kandidaten])), 3)
    sv = np.unique(N.rand)
    remap = np.full(N.n, -1, dtype=np.int64)
    remap[sv] = np.arange(len(sv))
    info = {
        "sicherheit": round(sicherheit, 3) if math.isfinite(sicherheit) else None, "ziel": ziel,
        "ausnutzung": round(ziel / sicherheit, 4) if sicherheit > 0 else None,
        "spannung_max": round(float(vm[kandidaten].max()), 3), "spannung_ort": round(float(vm[k]), 3),
        "index_mises": round(float(i_m[k]), 4), "index_schicht": None if i_s is None else round(float(i_s[k]), 4),
        "kriterium": ("schicht" if krit[k] == 1 else ("quer_unbekannt" if krit[k] == 2 else "mises")),
        "ort": [round(float(c), 2) for c in N.p[k]],
        "sicherheit_lagerrand": round(1.0 / float(idx[k_rand]), 3) if idx[k_rand] > 0 else None,
        "ort_lagerrand": [round(float(c), 2) for c in N.p[k_rand]],
        "verformung_max_mm": round(float(vb.max()), 5),
        "verformung_ort": [round(float(c), 2) for c in N.p[int(np.argmax(vb))]],
        "festigkeit": w["f"], "q": w.get("q"), "werkstoff": w.get("name"),
        "ausrichtungen": alt,
    }
    felder = {"punkte": N.p[sv].astype(np.float32), "dreiecke": remap[N.rand].astype(np.uint32),
              "ausnutzung": (ziel * idx[sv]).astype(np.float32), "spannung": vm[sv].astype(np.float32),
              "verschiebung": v[sv].astype(np.float32)}
    return info, felder


def rechne_teil(T: dict[str, Any], fein: bool, ablage: Path, von: float, bis: float) -> list[dict[str, Any]]:
    """Alle Fälle eines Teils; Ergebnisse aus dem Zwischenspeicher, wo vorhanden."""
    t0 = time.perf_counter()
    kurz = T["name"].rsplit("/", 1)[-1]
    out: list[dict[str, Any]] = []
    offen = []
    mit_sigma = bool(T.get("grenze"))
    for f in T["faelle"]:
        alt = lies_fall(ablage / "faelle" / f"{f['schluessel']}.npz")
        if alt is not None and mit_sigma and not (ablage / "faelle" / f"{f['schluessel']}.sig.npz").exists():
            alt = None  # Grenze suchen braucht die Spannungen je Knoten
        if alt is not None:
            out.append({**alt, "id": f["id"], "aus_speicher": True})
        else:
            offen.append(f)
    if not offen:
        melde(bis, f"{kurz}: aus dem Zwischenspeicher")
        return out
    from kevcad_kernel.statik.festkoerper import kontakt, loeser
    from kevcad_kernel.statik.festkoerper import werkstoff as wk

    def schritt(anteil: float, text: str) -> None:
        melde(von + (bis - von) * anteil, f"{kurz}: {text}")

    schritt(0.02, "vernetzen")
    n, netz_gemerkt = _netz(T, fein, ablage)
    t_netz = (time.perf_counter() - t0) * 1000
    N = loeser.Netz(n["p"], n["t"], n["rand"], n["flaeche"])
    schritt(0.3, f"{len(N.t)} Tetraeder, {N.N} Freiheitsgrade")
    w = T["werkstoff"]
    C = wk.steifigkeit(w["E"], w["nu"], w.get("E_z") if T["druckteil"] else None,
                       T.get("schicht") if T["druckteil"] else None)
    t1 = time.perf_counter()
    K = N.steifigkeit(C)
    t_k = (time.perf_counter() - t1) * 1000
    schritt(0.45, "Steifigkeit aufgebaut")
    groesse = float(np.max(np.asarray(T["bmax"]) - np.asarray(T["bmin"])))
    duenn = groesse / max(2.0 * T["volumen"] / max(float(N.rand_flaeche_mm2.sum()), 1e-9), 1e-9) > 25
    # Kontaktflächen je Nachbar (Lager und Lasteinleitung)
    beruehrt: dict[str, np.ndarray] = {}
    for x, nb in T["nachbarn"].items():
        with np.load(nb["datei"]) as z:
            d = kontakt.abstand(N.rand_mitte, z["pos"], z["tri"], float(nb["tol"]))
        beruehrt[x] = np.where(np.isfinite(d))[0]
    gruppen: dict[tuple, list[dict[str, Any]]] = {}
    for f in offen:
        gruppen.setdefault(tuple(sorted(f["lager"])), []).append(f)
    erledigt = 0
    V = float(N.vol.sum())
    for lager, fs in gruppen.items():
        fest = np.unique(np.concatenate([beruehrt.get(x, np.zeros(0, dtype=np.int64)) for x in lager])) \
            if lager else np.zeros(0, dtype=np.int64)
        if len(fest) == 0:
            for f in fs:
                out.append({"id": f["id"], "stand": "failed", "meldung": f"keine Lagerfläche zu {', '.join(lager)} "
                                                                        "gefunden (berühren sie sich?)"})
            continue
        # Lagerarten (simulation2): fest, gleitend (gehaltene Richtungen), gelenkig (RBE3-artig gekoppelt)
        arten = {x: _lager_art(T["nachbarn"].get(x, {})) for x in lager}
        mit_zwang = any(a != "fest" for a in arten.values())
        voll = [x for x in lager if arten[x] == "fest"]
        # Teile des Netzes ohne Lager (lose Stücke) würden das System singulär machen: weglassen
        komp = loeser.komponenten(N.t, N.n)
        mit_lager = np.unique(komp[np.unique(N.rand[fest])])
        lose = ~np.isin(komp[N.t[:, 0]], mit_lager)
        if lose.any():
            for f in fs:
                f.setdefault("hinweise", []).append(f"{int(lose.sum())} Tetraeder ohne Verbindung zum Lager "
                                                    "weggelassen")
        if mit_zwang:
            voll_f = np.unique(np.concatenate([beruehrt.get(x, np.zeros(0, dtype=np.int64)) for x in voll])) \
                if voll else np.zeros(0, dtype=np.int64)
            fest_dofs = N.feste_dofs(voll_f) if len(voll_f) else np.zeros(0, dtype=np.int64)
        else:
            fest_dofs = N.feste_dofs(fest)
        if lose.any():
            weg_knoten = np.unique(N.t[lose])
            weg_knoten = weg_knoten[~np.isin(weg_knoten, np.unique(N.t[~lose]))]
            fest_dofs = np.union1d(fest_dofs, N.basis.nodal_dofs[:, weg_knoten].reshape(-1))
            weg_kanten = np.unique(N.kante[:, lose])
            weg_kanten = weg_kanten[~np.isin(weg_kanten, np.unique(N.kante[:, ~lose]))]
            fest_dofs = np.union1d(fest_dofs, N.basis.edge_dofs[:, weg_kanten].reshape(-1))
        zw = None
        if mit_zwang:
            schief, kopplung = [], []
            for x in lager:
                sel = beruehrt.get(x, np.zeros(0, dtype=np.int64))
                if len(sel) == 0:
                    continue
                nb = T["nachbarn"].get(x, {})
                if arten[x] == "gleitend":
                    schief.append((N.facetten_dofs(sel), _gehalten(nb)))
                elif arten[x] == "gelenkig":
                    kopplung += N.gelenk_zeilen(sel, nb.get("drehachsen") or [])
            zw = N.zwang(fest_dofs, schief, kopplung)
            n_frei, frei_text = N.starr_frei(zw)
            if n_frei:
                nur_gleitend = all(a == "gleitend" for a in arten.values())
                text = ("nur gleitende Lager: " if nur_gleitend else "") + \
                    "das Teil ist mit diesen Lagern nicht in allen Richtungen gehalten (" + "; ".join(frei_text) + \
                    ("); ein festes Lager dazu setzen" if nur_gleitend else "); ein Lager dazu setzen oder eines fest "
                                                                           "machen")
                for f in fs:
                    out.append({"id": f["id"], "stand": "failed", "meldung": text})
                continue
        vektoren, details = [], []
        for f in fs:
            lv = np.zeros(N.N)
            summe = np.zeros(3)
            lastflaechen = []
            for last in f["lasten"]:
                F = np.asarray(last["kraft"], float)
                M = np.asarray(last["moment"], float) if last.get("moment") is not None else None
                P = np.asarray(last["punkt"], float) if last.get("punkt") is not None else None
                summe += F
                if last.get("flaeche_datei"):  # Last auf der ganzen Fläche (simulation2)
                    sel = _flaechen_facetten(N, last["flaeche_datei"])
                    if len(sel) == 0:
                        sel = _lastflaeche(N, P, groesse, n["h"]) if P is not None else np.arange(len(N.rand))
                    druck = (last.get("flaeche") or {}).get("druck")
                    if druck:
                        lv += N.last_druck(sel, float(druck))
                        F_ist = -float(druck) * (N.rand_normale[sel] * N.rand_flaeche_mm2[sel, None]).sum(axis=0)
                        summe += F_ist - F  # Resultierende auf dem FEM-Netz (gleich F bis auf die Vernetzung)
                    else:
                        lv += N.last_flaeche(sel, F, None, None)  # gleichmäßig: F / A auf jedem Dreieck
                    lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
                elif last.get("kontakt_mit"):
                    sel = beruehrt.get(last["kontakt_mit"], np.zeros(0, dtype=np.int64))
                    if len(sel) == 0 and P is not None:
                        sel = _lastflaeche(N, P, groesse, n["h"])
                    lv += N.last_flaeche(sel, F, M, P)
                    lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
                elif P is not None:
                    sel = _lastflaeche(N, P, groesse, n["h"])
                    lv += N.last_flaeche(sel, F, M, P)
                    lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
                else:  # am Schwerpunkt: gleichmäßig über das Volumen
                    lv += N.last_volumen(F / V)
                    if M is not None and np.any(M):
                        lv += N.last_flaeche(np.arange(len(N.rand)), np.zeros(3), M, None)
                    lastflaechen.append(None)
            g = np.asarray(f.get("feld") or (0, 0, 0), float) * (T["masse_kg"] / max(T["volumen"], 1e-9))
            lv += N.last_volumen(g)
            summe += g * V
            kontrolle = np.array([lv[N.basis.nodal_dofs[c]].sum() + lv[N.basis.edge_dofs[c]].sum() for c in range(3)])
            vektoren.append(lv)
            details.append({"lastflaechen_mm2": lastflaechen, "kraft_n": [round(float(c), 3) for c in summe],
                            "gleichgewicht_n": round(float(np.linalg.norm(kontrolle - summe)), 6),
                            "eigengewicht_n": [round(float(c), 4) for c in g * V]})
        schritt(0.5 + 0.4 * erledigt / max(len(offen), 1), f"lösen ({len(fs)} Lastfälle)")
        t2 = time.perf_counter()
        us, info = N.loese(K, fest_dofs, vektoren, duenn=duenn, zwang=zw)
        t_loesen = (time.perf_counter() - t2) * 1000
        fest_knoten = np.unique(N.rand[fest])
        lager_dofs = {x: N.facetten_dofs(beruehrt[x]) if len(beruehrt.get(x, ())) else np.zeros(0, dtype=np.int64)
                      for x in lager}
        for i, (f, u, det) in enumerate(zip(fs, us, details)):
            t3 = time.perf_counter()
            kurzinfo, felder = _bewerten(N, u, C, T, f, fest_knoten)
            kurzinfo.update(det)
            kurzinfo["lagerkraefte"] = lagerkraefte(N, K, u, vektoren[i], lager_dofs, arten, T["nachbarn"])
            kurzinfo["lagerarten"] = dict(arten)
            if zw is not None:
                kurzinfo["zwang"] = dict(zw.info)
            if mit_sigma:
                frei = np.ones(N.n, dtype=bool)
                frei[fest_knoten] = False
                _schreibe_npz(ablage / "faelle" / f"{f['schluessel']}.sig.npz",
                              sigma=N.spannung(u, C).astype(np.float64), frei=frei,
                              punkte=N.p.astype(np.float32))
            kurzinfo.update({
                "stand": "done", "szenario": f["szenario"], "teil": T["name"], "schluessel": f["schluessel"],
                "lager": list(lager), "lager_aus_last": f.get("lager_aus_last"),
                "lagerflaeche_mm2": round(float(N.rand_flaeche_mm2[fest].sum()), 1),
                "lasten": [{k: v for k, v in l.items()} for l in f["lasten"]], "s0": f.get("s0"),
                "hinweise": f.get("hinweise") or [],
                "netz": {"knoten": int(N.n), "tetraeder": int(len(N.t)), "freiheitsgrade": int(N.N),
                         "h_mm": round(float(n["h"]), 2), "fein": fein, "aus_speicher": netz_gemerkt,
                         "duenn": bool(duenn)},
                "loeser": {"verfahren": info["verfahren"][i], "iterationen": info["iterationen"][i],
                           "residuum": info["residuum"][i]},
                "ms": {"netz": round(t_netz, 1), "steifigkeit": round(t_k, 1), "loesen": round(t_loesen, 1),
                       "auswerten": round((time.perf_counter() - t3) * 1000, 1),
                       "teil": round((time.perf_counter() - t0) * 1000, 1)},
            })
            _schreibe_npz(ablage / "faelle" / f"{f['schluessel']}.npz",
                          info=np.frombuffer(json.dumps(kurzinfo, ensure_ascii=False).encode("utf-8"), dtype=np.uint8),
                          **felder)
            out.append({**kurzinfo, "id": f["id"], "aus_speicher": False, "_felder": felder})
            erledigt += 1
        schritt(0.5 + 0.45 * erledigt / max(len(offen), 1), f"{erledigt} von {len(offen)} Lastfällen fertig")
    return out


def lagerkraefte(N: Any, K: Any, u: np.ndarray, f: np.ndarray, lager_dofs: dict[str, np.ndarray],
                 arten: dict[str, str], nachbarn: dict[str, Any]) -> dict[str, list[float]]:
    """Resultierende Lagerkraft je Lager (N, auf das Teil): Reaktion r = K u − f an den Orten seiner Fläche. Teilen
    sich Lager einen Ort (Kante zwischen zwei Lagerflächen), wird r dort nach ihren gehaltenen Richtungen aufgeteilt
    (kleinste Quadrate; gleitend nur in seinen Richtungen); ein festes oder gelenkiges Lager an diesem Ort nimmt, was
    übrig bleibt."""
    r = np.asarray(K @ u).reshape(-1) - f
    trip, ort = N.orte()
    je_ort: dict[int, list[str]] = {}
    for x, d_ in lager_dofs.items():
        for o in np.unique(ort[d_]):
            je_ort.setdefault(int(o), []).append(x)
    out = {x: np.zeros(3) for x in lager_dofs}
    for o, xs in je_ort.items():
        ro = r[trip[o]]
        if len(xs) == 1:
            out[xs[0]] += ro
            continue
        gl = [x for x in xs if arten.get(x) == "gleitend"]
        rest = [x for x in xs if x not in gl]
        if gl:
            spalten = [(x, np.asarray(h, float)) for x in gl for h in _gehalten(nachbarn.get(x, {}))]
            A = np.stack([h / max(float(np.linalg.norm(h)), 1e-300) for _, h in spalten], axis=1)
            lam = np.linalg.lstsq(A, ro, rcond=None)[0] if not rest else np.zeros(A.shape[1])
            for (x, _), lk, a in zip(spalten, lam, A.T):
                out[x] += lk * a
            ro = ro - A @ lam
        if rest:
            out[rest[0]] += ro
    return {x: [round(float(c), 3) + 0.0 for c in v] for x, v in out.items()}


def _index(s: np.ndarray, T: dict[str, Any]) -> np.ndarray:
    """Ausnutzungsindex je Knoten (1 = Festigkeit erreicht) wie in ``_bewerten``."""
    from kevcad_kernel.statik.festkoerper import werkstoff as wk

    w = T["werkstoff"]
    i_m, i_s = wk.index(s, w["f"], w.get("q"), T.get("schicht") if T["druckteil"] else None)
    if T["druckteil"] and i_s is None:
        return i_m / float(w.get("q") or 0.5)
    if i_s is not None:
        return np.maximum(i_m, i_s)
    return i_m


def halbieren(ok: Any, lo: float, hi: float, schritte: int = GRENZE_SCHRITTE) -> float | None:
    """Größtes x in [lo, hi] mit ok(x) (wie ``simulation.grenze._halbieren``): einklammern, dann halbieren."""
    if not ok(lo):
        return None
    b = min(max(lo * 2, 1.0), hi)
    while b < hi and ok(b):
        lo, b = b, min(b * 2, hi)
    if b >= hi and ok(hi):
        return hi
    hi = b
    for _ in range(schritte):
        mitte = (lo + hi) / 2
        if ok(mitte):
            lo = mitte
        else:
            hi = mitte
    return lo


def grenzen_suchen(teile: list[dict[str, Any]], faelle: list[dict[str, Any]], ablage: Path) -> list[dict[str, Any]]:
    """„Grenze suchen“ mit der FEM: je Teil und Gruppe die gerechneten Grundfälle überlagern (linear-elastisch:
    Spannung = Σ Gewicht · Spannung des Grundfalls) und den Faktor halbieren, bis die Ausnutzung das Ziel bzw. die
    Festigkeit erreicht. ``last``: Grundfälle bei λ₁ und λ₂ (Spannung linear in λ); ``neigung``: drei Neigungen θₖ
    (Spannung = A + B sin θ + C cos θ)."""
    nach_id = {r.get("id"): r for r in faelle}
    out = []
    for T in teile:
        for gruppe, g in (T.get("grenze") or {}).items():
            basis = {}
            for f in T["faelle"]:
                if (f.get("grenze") or {}).get("gruppe") == gruppe:
                    r = nach_id.get(f["id"]) or {}
                    if r.get("stand") != "done":
                        continue
                    pfad = ablage / "faelle" / f"{f['schluessel']}.sig.npz"
                    if pfad.exists():
                        with np.load(pfad) as z:
                            basis[float(f["grenze"]["wert"])] = (np.asarray(z["sigma"], float),
                                                                 np.asarray(z["frei"], bool),
                                                                 np.asarray(z["punkte"], float), f, r)
            werte = sorted(basis)
            art = g.get("art") or "last"
            if (art == "last" and len(werte) < 2) or (art == "neigung" and len(werte) < 3):
                out.append({"teil": T["name"], "gruppe": gruppe, "stand": "failed",
                            "meldung": "Grundfälle nicht gerechnet"})
                continue
            frei = basis[werte[0]][1]
            if not frei.any():
                frei = np.ones_like(frei)
            punkte = basis[werte[0]][2]
            if art == "last":
                (l1, (s1, *_)), (l2, (s2, *_)) = (werte[0], basis[werte[0]]), (werte[1], basis[werte[1]])
                d = (s2 - s1) / (l2 - l1)

                def sigma(x: float, s1=s1, l1=l1, d=d) -> np.ndarray:
                    return s1 + (x - l1) * d
                hi = GRENZE_MAX
            else:
                th = np.radians(werte[:3])
                A = np.stack([np.ones(3), np.sin(th), np.cos(th)], axis=1)
                S = np.stack([basis[w][0] for w in werte[:3]])  # (3, n, 6)
                koef = np.einsum("ij,jkl->ikl", np.linalg.inv(A), S)

                def sigma(x: float, koef=koef) -> np.ndarray:
                    t = math.radians(x)
                    return koef[0] + math.sin(t) * koef[1] + math.cos(t) * koef[2]
                hi = float(g.get("max") or 60.0)
            ziel = float(basis[werte[0]][3].get("ziel") or 2.0)
            zaehler = {"n": 0}

            def ausnutzung(x: float) -> tuple[float, int]:
                zaehler["n"] += 1
                idx = _index(sigma(x), T)
                k = int(np.flatnonzero(frei)[np.argmax(idx[frei])])
                return float(idx[k]), k

            ziel_g = halbieren(lambda x: ausnutzung(x)[0] * ziel <= 1.0, 0.0, hi)
            bruch_g = halbieren(lambda x: ausnutzung(x)[0] <= 1.0, 0.0, hi)
            e: dict[str, Any] = {"teil": T["name"], "gruppe": gruppe, "art": art, "stand": "done", "ziel": ziel,
                                 "ziel_grenze": ziel_g, "bruch_grenze": bruch_g, "auswertungen": zaehler["n"]}
            if ziel_g is not None and ziel_g < hi:
                _, k = ausnutzung(ziel_g * 1.0001)
                e["ort"] = [round(float(c), 2) for c in punkte[k]]
            out.append(e)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("Aufruf: python -m kevcad_kernel.statik.festkoerper.prozess auftrag.json ergebnis.json",
              file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    auftrag = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    ablage = speicher()
    out: dict[str, Any] = {"stand": "done", "faelle": [], "pid": os.getpid(), "grenzen": list(GRENZEN_S3)}
    teile = auftrag.get("teile") or []
    melde(0.0, f"{len(teile)} Teile")
    for i, T in enumerate(teile):
        von, bis = i / max(len(teile), 1), (i + 1) / max(len(teile), 1)
        try:
            for r in rechne_teil(T, bool(auftrag.get("fein")), ablage, von, bis):
                felder = r.pop("_felder", None)
                if felder is not None and r.get("stand") == "done":
                    r["feld"] = str(ablage / "faelle" / f"{r['schluessel']}.npz")
                out["faelle"].append(r)
        except Exception as exc:  # noqa: BLE001 - ein Teil darf die anderen nicht verhindern
            for f in T["faelle"]:
                out["faelle"].append({"id": f["id"], "stand": "failed", "szenario": f["szenario"], "teil": T["name"],
                                      "meldung": f"nicht gerechnet: {type(exc).__name__}: {exc}",
                                      "traceback": traceback.format_exc(limit=6)})
    if any(T.get("grenze") for T in teile):
        melde(0.97, "Grenze suchen (Halbieren über die überlagerten Spannungen)")
        out["grenze"] = grenzen_suchen(teile, out["faelle"], ablage)
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    melde(1.0, "fertig")
    tmp = argv[1] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    os.replace(tmp, argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
