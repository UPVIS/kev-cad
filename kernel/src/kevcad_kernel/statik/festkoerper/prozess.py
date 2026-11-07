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

from kevcad_kernel.statik.festkoerper import GRENZEN_S3, RECHENSTAND, VERSION

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
    if _STILL:
        return
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


def _netz_schluessel(T: dict[str, Any], fein: bool) -> str:
    """Schlüssel des Netzes eines Teils (Teilstand, Netzeinstellung, Grenzen von Gmsh)."""
    from kevcad_kernel.statik.festkoerper import netz

    schl = {"v": VERSION, "teil": T["schluessel_teil"], "fein": fein, "h": T.get("h_mm"),
            "max": [netz.MAX_TET, netz.MAX_TET_FEIN, netz.WAND_ANTEIL, netz.KRUEMMUNG]}
    if T.get("verfeinern"):  # Stufe 4 (additiv): örtliche Verfeinerung, etwa am Punktkontakt
        schl["verfeinern"] = T["verfeinern"]
    return hashlib.sha1(json.dumps(schl, sort_keys=True).encode()).hexdigest()[:20]


def _netz(T: dict[str, Any], fein: bool, ablage: Path) -> tuple[dict[str, Any], bool]:
    from kevcad_kernel.statik.festkoerper import netz

    pfad = ablage / "netze" / f"{_netz_schluessel(T, fein)}.npz"
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


# -- Einheitslastfälle (A4, PLAN-PRUEFUNG-INKREMENTELL.md) -----------------------------------------------------------
# Teile, die SuperLU löst, rechnet der Prozess über Einheitslastfälle statt Fall für Fall: je Lastfläche Kraft 1 N in
# x, y, z am Schwerpunkt der Fläche und Moment 1 Nmm um x, y, z (dieselbe RBE3-Verteilung wie ``Netz.last_flaeche``),
# je Fläche unter Druck der Einheitsdruck, für Volumenlasten (Eigengewicht, Last ohne Punkt) b in x, y, z, für Momente
# am Schwerpunkt die ganze Oberfläche, alle mit einer Zerlegung. Ein Fall ist die Summe der Einheitsfälle mal ihrer
# Beiwerte (Kraft, Moment um den Schwerpunkt der Fläche M + (P − c) × F, Druck, b). Die Einheitsfälle (Verschiebungen,
# Reaktionen an den Lagern, Summen der Lastvektoren) liegen je Teilzustand auf der Platte (``einheiten/``); ändern sich
# nur die Lasten, setzt der nächste Lauf die Fälle daraus zusammen, ohne Steifigkeit, Kontaktflächen und Zerlegung. Der
# Schlüssel enthält alles, wovon die Einheitsfälle abhängen: Netz, Werkstoff und Schicht (Steifigkeit), Lager (Netz des
# Nachbarn bzw. der Lagerfläche, Toleranz, Art), Lastflächen. Gerechnet wird so auch beim ersten Mal: Ein Fall aus
# gemerkten Einheitsfällen ist Bit für Bit derselbe wie frisch gerechnet; gegen die Lösung je Fall weicht er nur in der
# Rundung ab. Teile, die AMG löst, und Lastflächen ohne Treffer auf dem Netz (Ersatzfläche um den Punkt) rechnen weiter
# Fall für Fall.

EINHEIT_ORDNER = "einheiten"
EINHEIT_FORMAT = 1
EINHEIT_MAX_MB = 1024.0  # Platz für Einheitszustände; zuerst weg, was am längsten nicht benutzt wurde
UEBERLAGERN_ENV = "KEVCAD_FEM_UEBERLAGERN"  # "0": Fall für Fall wie vor A4 (Tests, Vergleiche)
VOL = '["volumen"]'
ALLE = '["alle"]'


def _ueberlagern_an() -> bool:
    """Einheitslastfälle an? Aus mit ``KEVCAD_FEM_UEBERLAGERN=0`` und wenn AMG erzwungen ist (``KEVCAD_FEM_LOESER``)."""
    from kevcad_kernel.statik.festkoerper.loeser import LOESER_ENV

    if (os.environ.get(LOESER_ENV) or "").strip().lower() == "amg":
        return False
    return (os.environ.get(UEBERLAGERN_ENV) or "1").strip().lower() not in ("0", "aus", "false", "nein", "no")


def _datei_schluessel(datei: str) -> str | None:
    """Inhalt eines Netzes (alle Felder der Datei) als Schlüssel."""
    try:
        with np.load(datei) as z:
            h = hashlib.sha1()
            for k in sorted(z.files):
                a = np.ascontiguousarray(z[k])
                h.update(f"{k}|{a.dtype}|{a.shape}|".encode())
                h.update(a.tobytes())
        return h.hexdigest()[:20]
    except Exception:  # noqa: BLE001
        return None


class _Nachbarn:
    """Schlüssel der Nachbarnetze eines Teils (Inhalt der Datei), je Nachbar einmal gelesen."""

    def __init__(self, T: dict[str, Any]) -> None:
        self.T = T
        self._h: dict[str, str | None] = {}

    def __call__(self, x: str) -> str | None:
        if x not in self._h:
            nb = self.T["nachbarn"].get(x) or {}
            self._h[x] = _datei_schluessel(nb["datei"]) if nb.get("datei") else None
        return self._h[x]


def _lager_daten(nb: dict[str, Any]) -> dict[str, Any]:
    return {k: nb.get(k) for k in ("art", "gelenkig", "gehalten", "komponenten", "drehachsen", "normale")}


def _last_schluessel(last: dict[str, Any], T: dict[str, Any], nachbarn: _Nachbarn) -> list[str]:
    """Lastflächen einer Last, ohne Netz: Fläche einer Datei (gleichmäßig oder Druck), Kontaktfläche zum Nachbarn,
    Fläche um den Punkt; Last am Schwerpunkt: Volumen und mit Moment die ganze Oberfläche."""
    if last.get("flaeche_datei"):
        druck = (last.get("flaeche") or {}).get("druck")
        return [json.dumps(["druck" if druck else "flaeche", _datei_schluessel(last["flaeche_datei"])])]
    if last.get("kontakt_mit"):
        x = last["kontakt_mit"]
        return [json.dumps(["kontakt", x, nachbarn(x), (T["nachbarn"].get(x) or {}).get("tol")])]
    if last.get("punkt") is not None:
        return [json.dumps(["punkt", [repr(float(c)) for c in last["punkt"]]])]
    M = last.get("moment")
    return [VOL, ALLE] if M is not None and np.any(np.asarray(M, float) != 0) else [VOL]


def _einheit_pfad(ablage: Path, T: dict[str, Any], fein: bool, lager: tuple, fs: list[dict[str, Any]],
                  nachbarn: _Nachbarn) -> Path:
    """Datei der Einheitsfälle einer Lagergruppe: Schlüssel aus Netz, Steifigkeit, Lagern und Lastflächen."""
    w = T["werkstoff"]
    druckteil = bool(T.get("druckteil"))
    flaechen = {VOL} | {k for f in fs for last in f["lasten"] for k in _last_schluessel(last, T, nachbarn)}
    schl = {"f": EINHEIT_FORMAT, "v": VERSION, "r": RECHENSTAND, "netz": _netz_schluessel(T, fein),
            "w": [w.get("E"), w.get("nu"), w.get("E_z") if druckteil else None],
            "schicht": T.get("schicht") if druckteil else None,
            "lager": [[x, nachbarn(x), (T["nachbarn"].get(x) or {}).get("tol"),
                       _lager_daten(T["nachbarn"].get(x) or {})] for x in lager],
            "flaechen": sorted(flaechen)}
    key = hashlib.sha1(json.dumps(schl, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return ablage / EINHEIT_ORDNER / f"{key}.npz"


def _einheit_laden(pfad: Path) -> dict[str, Any] | None:
    try:
        with np.load(pfad) as z:
            info = json.loads(bytes(z["info"]).decode("utf-8"))
            d = {"U": z["U"], "R": z["R"], "S": z["S"], "ldofs": z["ldofs"], "fest": z["fest"], **info}
            d["lager_facetten"] = {x: z[f"lager_{i}"] for i, x in enumerate(info["lager"])}
        if info.get("f") != EINHEIT_FORMAT:
            return None
        os.utime(pfad)  # zuletzt benutzt (Aufräumen)
        return d
    except Exception:  # noqa: BLE001 - fehlt oder kaputt: neu rechnen
        return None


def _einheit_speichern(pfad: Path, d: dict[str, Any]) -> None:
    info = {"f": EINHEIT_FORMAT, **{k: d[k] for k in ("einheiten", "flaechen", "residuen", "lose", "zwang", "lager")}}
    felder = {"U": d["U"], "R": d["R"], "S": d["S"], "ldofs": d["ldofs"], "fest": d["fest"],
              **{f"lager_{i}": d["lager_facetten"][x] for i, x in enumerate(d["lager"])}}
    try:
        _schreibe_npz(pfad, info=np.frombuffer(json.dumps(info).encode("utf-8"), dtype=np.uint8), **felder)
    except OSError:
        return
    _einheiten_aufraeumen(pfad.parent)


def _einheiten_aufraeumen(ordner: Path, max_mb: float = EINHEIT_MAX_MB) -> None:
    """Höchstens ``max_mb`` Einheitszustände: die am längsten nicht benutzten zuerst weg (bis 80 % davon)."""
    try:
        dateien = sorted((p.stat().st_mtime, p.stat().st_size, p) for p in ordner.glob("*.npz"))
    except OSError:
        return
    summe = sum(s for _, s, _ in dateien) / (1 << 20)
    if summe <= max_mb:
        return
    for _, groesse, p in dateien:  # die am längsten nicht benutzten zuerst
        if summe <= 0.8 * max_mb:
            break
        try:
            p.unlink()
        except OSError:
            continue
        summe -= groesse / (1 << 20)


def _flaechen_waehlen(N: Any, T: dict[str, Any], fs: list[dict[str, Any]], beruehrt: dict[str, np.ndarray],
                      groesse: float, h: float, nachbarn: _Nachbarn) -> dict[str, np.ndarray | None] | None:
    """Randdreiecke je Lastfläche der Fälle (Volumen ohne). None, wenn eine Fläche einer Datei oder eine Kontaktfläche
    auf dem Netz leer bleibt: dann Fall für Fall wie bisher (Ersatzfläche um den Punkt)."""
    sel: dict[str, np.ndarray | None] = {VOL: None}
    for f in fs:
        for last in f["lasten"]:
            for k in _last_schluessel(last, T, nachbarn):
                if k in sel:
                    continue
                art = json.loads(k)[0]
                if art in ("flaeche", "druck"):
                    s = _flaechen_facetten(N, last["flaeche_datei"])
                elif art == "kontakt":
                    s = beruehrt.get(last["kontakt_mit"], np.zeros(0, dtype=np.int64))
                elif art == "punkt":
                    s = _lastflaeche(N, np.asarray(last["punkt"], float), groesse, h)
                else:  # die ganze Oberfläche (Moment einer Last am Schwerpunkt)
                    s = np.arange(len(N.rand))
                if len(s) == 0:
                    return None
                sel[k] = np.asarray(s, dtype=np.int64)
    return sel


def _einheiten_rechnen(N: Any, K: Any, fest_dofs: np.ndarray, zw: Any, duenn: bool,
                       flaechen: dict[str, np.ndarray | None], ldofs: np.ndarray) -> dict[str, Any]:
    """Einheitslastfälle der Flächen mit einer Zerlegung (SuperLU): Verschiebungen ``U`` (m × N), Reaktionen an den
    Lagern ``R`` (m × Lagerfreiheitsgrade ``ldofs``), Summen der Lastvektoren ``S`` (m × 3), dazu je Fläche A, c bzw.
    die Resultierende des Einheitsdrucks und die Residuen."""
    vektoren: list[np.ndarray] = []
    einheiten: list[list[str]] = []
    meta: dict[str, Any] = {}
    for k in sorted(flaechen):
        sel = flaechen[k]
        art = json.loads(k)[0]
        if art == "volumen":
            for c in range(3):
                e = np.zeros(3)
                e[c] = 1.0
                vektoren.append(N.last_volumen(e))
                einheiten.append([k, f"b{c}"])
            continue
        A = float(N.rand_flaeche_mm2[sel].sum())
        if art == "druck":
            vektoren.append(N.last_druck(sel, 1.0))
            einheiten.append([k, "p"])
            Fp = -(N.rand_normale[sel] * N.rand_flaeche_mm2[sel, None]).sum(axis=0)
            meta[k] = {"A": A, "Fp": [float(c) for c in Fp]}
            continue
        vs, geo = N.last_flaeche_einheiten(sel, kraefte=art != "alle", momente=art != "flaeche")
        for name, v in vs:
            vektoren.append(np.asarray(v, dtype=float).reshape(-1))
            einheiten.append([k, name])
        meta[k] = {"A": A, "c": [float(c) for c in geo["c"]]}
    us, info = N.loese(K, fest_dofs, vektoren, duenn=duenn, zwang=zw, verfahren="lu")
    U = np.stack(us)
    R = np.stack([(np.asarray(K @ u).reshape(-1) - f)[ldofs] for u, f in zip(us, vektoren)])
    S = np.array([[float(f[N.basis.nodal_dofs[c]].sum() + f[N.basis.edge_dofs[c]].sum()) for c in range(3)]
                  for f in vektoren])
    return {"U": U, "R": R, "S": S, "ldofs": ldofs, "einheiten": einheiten, "flaechen": meta,
            "residuen": [float(r) for r in info["residuum"]]}


def _koeffizienten(f: dict[str, Any], T: dict[str, Any], d: dict[str, Any], V: float, nachbarn: _Nachbarn
                   ) -> tuple[np.ndarray, np.ndarray, list[Any], np.ndarray]:
    """Beiwerte der Einheitsfälle für einen Fall, dazu Resultierende, Lastflächen und Eigengewichtsfeld (wie
    ``_lastvektor``)."""
    idx = {(k, name): i for i, (k, name) in enumerate(d["einheiten"])}
    koef = np.zeros(len(d["einheiten"]))
    summe = np.zeros(3)
    b = np.zeros(3)
    lastflaechen: list[Any] = []
    for last in f["lasten"]:
        F = np.asarray(last["kraft"], float)
        M = np.asarray(last["moment"], float) if last.get("moment") is not None else None
        P = np.asarray(last["punkt"], float) if last.get("punkt") is not None else None
        summe += F
        k = _last_schluessel(last, T, nachbarn)
        art = json.loads(k[0])[0]
        if art in ("flaeche", "druck"):
            m = d["flaechen"][k[0]]
            druck = (last.get("flaeche") or {}).get("druck")
            if druck:
                koef[idx[(k[0], "p")]] += float(druck)
                summe += float(druck) * np.asarray(m["Fp"], float) - F
            else:
                for c in range(3):
                    koef[idx[(k[0], f"F{c}")]] += F[c]
            lastflaechen.append(round(float(m["A"]), 1))
        elif art in ("kontakt", "punkt"):
            m = d["flaechen"][k[0]]
            Mc = (np.zeros(3) if M is None else M) + (np.cross(P - np.asarray(m["c"], float), F)
                                                     if P is not None else 0.0)
            for c in range(3):
                koef[idx[(k[0], f"F{c}")]] += F[c]
                koef[idx[(k[0], f"M{c}")]] += Mc[c]
            lastflaechen.append(round(float(m["A"]), 1))
        else:  # am Schwerpunkt: gleichmäßig über das Volumen, ein Moment über die ganze Oberfläche
            b += F / V
            if ALLE in k:
                for c in range(3):
                    koef[idx[(ALLE, f"M{c}")]] += M[c]  # type: ignore[index]
            lastflaechen.append(None)
    g = np.asarray(f.get("feld") or (0, 0, 0), float) * (T["masse_kg"] / max(T["volumen"], 1e-9))
    b += g
    summe += g * V
    for c in range(3):
        koef[idx[(VOL, f"b{c}")]] += b[c]
    return koef, summe, lastflaechen, g


def _ueberlagern(d: dict[str, Any], koef: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Verschiebung, Reaktionen an den Lagern und Summe des Lastvektors eines Falls aus den Einheitsfällen (in fester
    Reihenfolge, damit gemerkt und frisch Bit für Bit gleich rechnen)."""
    U, R, S = d["U"], d["R"], d["S"]
    u = np.zeros(U.shape[1])
    r = np.zeros(R.shape[1])
    kontrolle = np.zeros(3)
    genutzt = np.flatnonzero(koef)
    for k in genutzt:
        u += koef[k] * U[k]
        r += koef[k] * R[k]
        kontrolle += koef[k] * S[k]
    return u, r, kontrolle, genutzt


def _lastvektor(N: Any, T: dict[str, Any], f: dict[str, Any], beruehrt: dict[str, np.ndarray], groesse: float,
                h: float, V: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Lastvektor eines Falls, Fall für Fall (Teile mit AMG, Ersatzflächen), und seine Angaben."""
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
                sel = _lastflaeche(N, P, groesse, h) if P is not None else np.arange(len(N.rand))
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
                sel = _lastflaeche(N, P, groesse, h)
            lv += N.last_flaeche(sel, F, M, P)
            lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
        elif P is not None:
            sel = _lastflaeche(N, P, groesse, h)
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
    return lv, {"lastflaechen_mm2": lastflaechen, "kraft_n": [round(float(c), 3) for c in summe],
                "gleichgewicht_n": round(float(np.linalg.norm(kontrolle - summe)), 6),
                "eigengewicht_n": [round(float(c), 4) for c in g * V]}


def _fall_auswerten(N: Any, C: np.ndarray, T: dict[str, Any], f: dict[str, Any], u: np.ndarray, r_voll: np.ndarray,
                    det: dict[str, Any], lager: tuple, arten: dict[str, str], fest: np.ndarray,
                    fest_knoten: np.ndarray, lager_dofs: dict[str, np.ndarray], zwang_info: dict[str, Any] | None,
                    mit_sigma: bool, netz_info: dict[str, Any], loeser_info: dict[str, Any], ms: dict[str, float],
                    t0: float, ablage: Path, einheiten: dict[str, Any] | None) -> dict[str, Any]:
    """Ein gelöster Fall: Bewertung, Lagerkräfte, Angaben, Zwischenspeicher (gleich für Fall für Fall und überlagert)."""
    t3 = time.perf_counter()
    kurzinfo, felder = _bewerten(N, u, C, T, f, fest_knoten)
    kurzinfo.update(det)
    kurzinfo["lagerkraefte"] = lagerkraefte_aus_r(N, r_voll, lager_dofs, arten, T["nachbarn"])
    kurzinfo["lagerarten"] = dict(arten)
    if zwang_info is not None:
        kurzinfo["zwang"] = dict(zwang_info)
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
        "netz": dict(netz_info),
        "loeser": loeser_info,
        "ms": {**{k: round(v, 1) for k, v in ms.items()},
               "auswerten": round((time.perf_counter() - t3) * 1000, 1),
               "teil": round((time.perf_counter() - t0) * 1000, 1)},
    })
    if einheiten is not None:
        kurzinfo["einheiten"] = einheiten
    _schreibe_npz(ablage / "faelle" / f"{f['schluessel']}.npz",
                  info=np.frombuffer(json.dumps(kurzinfo, ensure_ascii=False).encode("utf-8"), dtype=np.uint8),
                  **felder)
    return {**kurzinfo, "id": f["id"], "aus_speicher": False, "_felder": felder}


def _faelle_ueberlagert(N: Any, C: np.ndarray, T: dict[str, Any], fs: list[dict[str, Any]], d: dict[str, Any],
                        lager: tuple, arten: dict[str, str], V: float, nachbarn: _Nachbarn, mit_sigma: bool,
                        netz_info: dict[str, Any], ablage: Path, t0: float, ms: dict[str, float], gemerkt: bool
                        ) -> list[dict[str, Any]]:
    """Alle Fälle einer Lagergruppe aus ihren Einheitsfällen."""
    out = []
    fest = np.asarray(d["fest"], dtype=np.int64)
    fest_knoten = np.unique(N.rand[fest])
    lager_dofs = {x: (N.facetten_dofs(d["lager_facetten"][x]) if len(d["lager_facetten"][x])
                      else np.zeros(0, dtype=np.int64)) for x in lager}
    ldofs = np.asarray(d["ldofs"], dtype=np.int64)
    for f in fs:
        t2 = time.perf_counter()
        if d.get("lose"):
            f.setdefault("hinweise", []).append(f"{int(d['lose'])} Tetraeder ohne Verbindung zum Lager weggelassen")
        koef, summe, lastflaechen, g = _koeffizienten(f, T, d, V, nachbarn)
        u, r, kontrolle, genutzt = _ueberlagern(d, koef)
        r_voll = np.zeros(N.N)
        r_voll[ldofs] = r
        det = {"lastflaechen_mm2": lastflaechen, "kraft_n": [round(float(c), 3) for c in summe],
               "gleichgewicht_n": round(float(np.linalg.norm(kontrolle - summe)), 6),
               "eigengewicht_n": [round(float(c), 4) for c in g * V]}
        if len(genutzt):
            loeser_info = {"verfahren": "superlu", "iterationen": 0,
                           "residuum": max(float(d["residuen"][k]) for k in genutzt)}
        else:
            loeser_info = {"verfahren": "null", "iterationen": 0, "residuum": 0.0}
        out.append(_fall_auswerten(N, C, T, f, u, r_voll, det, lager, arten, fest, fest_knoten, lager_dofs,
                                   d.get("zwang"), mit_sigma, netz_info, loeser_info,
                                   {**ms, "loesen": ms.get("loesen", 0.0) + (time.perf_counter() - t2) * 1000},
                                   t0, ablage, {"zahl": len(d["einheiten"]), "aus_speicher": gemerkt}))
    return out


def rechne_teil(T: dict[str, Any], fein: bool, ablage: Path, von: float, bis: float) -> list[dict[str, Any]]:
    """Alle Fälle eines Teils; Ergebnisse aus dem Zwischenspeicher, wo vorhanden, sonst aus Einheitslastfällen (A4:
    gemerkt oder mit einer Zerlegung frisch gerechnet) bzw. Fall für Fall (AMG, Ersatzflächen)."""
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

    gruppen: dict[tuple, list[dict[str, Any]]] = {}
    for f in offen:
        gruppen.setdefault(tuple(sorted(f["lager"])), []).append(f)
    nachbarn = _Nachbarn(T)
    ueberlagern = _ueberlagern_an()
    einheit: dict[tuple, tuple[Path, dict[str, Any] | None]] = {}
    if ueberlagern:
        for lager, fs in gruppen.items():
            pfad = _einheit_pfad(ablage, T, fein, lager, fs, nachbarn)
            einheit[lager] = (pfad, _einheit_laden(pfad) if pfad.exists() else None)
    schritt(0.02, "vernetzen")
    n, netz_gemerkt = _netz(T, fein, ablage)
    t_netz = (time.perf_counter() - t0) * 1000
    N = loeser.Netz(n["p"], n["t"], n["rand"], n["flaeche"])
    schritt(0.3, f"{len(N.t)} Tetraeder, {N.N} Freiheitsgrade")
    w = T["werkstoff"]
    C = wk.steifigkeit(w["E"], w["nu"], w.get("E_z") if T["druckteil"] else None,
                       T.get("schicht") if T["druckteil"] else None)
    groesse = float(np.max(np.asarray(T["bmax"]) - np.asarray(T["bmin"])))
    duenn = groesse / max(2.0 * T["volumen"] / max(float(N.rand_flaeche_mm2.sum()), 1e-9), 1e-9) > 25
    h = float(n["h"])
    netz_info = {"knoten": int(N.n), "tetraeder": int(len(N.t)), "freiheitsgrade": int(N.N), "h_mm": round(h, 2),
                 "fein": fein, "aus_speicher": netz_gemerkt, "duenn": bool(duenn)}
    K = None
    t_k = 0.0
    beruehrt: dict[str, np.ndarray] = {}
    if any((einheit.get(lager) or (None, None))[1] is None for lager in gruppen):
        t1 = time.perf_counter()
        K = N.steifigkeit(C)
        t_k = (time.perf_counter() - t1) * 1000
        schritt(0.45, "Steifigkeit aufgebaut")
        # Kontaktflächen je Nachbar (Lager und Lasteinleitung)
        for x, nb in T["nachbarn"].items():
            with np.load(nb["datei"]) as z:
                dist = kontakt.abstand(N.rand_mitte, z["pos"], z["tri"], float(nb["tol"]))
            beruehrt[x] = np.where(np.isfinite(dist))[0]
    erledigt = 0
    V = float(N.vol.sum())
    for lager, fs in gruppen.items():
        pfad, d = einheit.get(lager) or (None, None)
        arten = {x: _lager_art(T["nachbarn"].get(x, {})) for x in lager}
        if d is not None:  # A4: aus gemerkten Einheitsfällen, ohne Steifigkeit, Kontakte und Zerlegung
            schritt(0.5 + 0.4 * erledigt / max(len(offen), 1), f"aus Einheitslastfällen ({len(fs)} Lastfälle)")
            out += _faelle_ueberlagert(N, C, T, fs, d, lager, arten, V, nachbarn, mit_sigma, netz_info, ablage, t0,
                                       {"netz": t_netz, "steifigkeit": t_k, "loesen": 0.0}, True)
            erledigt += len(fs)
            schritt(0.5 + 0.45 * erledigt / max(len(offen), 1), f"{erledigt} von {len(offen)} Lastfällen fertig")
            continue
        assert K is not None
        fest = np.unique(np.concatenate([beruehrt.get(x, np.zeros(0, dtype=np.int64)) for x in lager])) \
            if lager else np.zeros(0, dtype=np.int64)
        if len(fest) == 0:
            for f in fs:
                out.append({"id": f["id"], "stand": "failed", "meldung": f"keine Lagerfläche zu {', '.join(lager)} "
                                                                        "gefunden (berühren sie sich?)"})
            continue
        # Lagerarten (simulation2): fest, gleitend (gehaltene Richtungen), gelenkig (RBE3-artig gekoppelt)
        mit_zwang = any(a != "fest" for a in arten.values())
        voll = [x for x in lager if arten[x] == "fest"]
        # Teile des Netzes ohne Lager (lose Stücke) würden das System singulär machen: weglassen
        komp = loeser.komponenten(N.t, N.n)
        mit_lager = np.unique(komp[np.unique(N.rand[fest])])
        lose = ~np.isin(komp[N.t[:, 0]], mit_lager)
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
        fest_knoten = np.unique(N.rand[fest])
        lager_dofs = {x: N.facetten_dofs(beruehrt[x]) if len(beruehrt.get(x, ())) else np.zeros(0, dtype=np.int64)
                      for x in lager}
        frei_zahl = int(zw.T.shape[1]) if zw is not None else int(N.N - len(fest_dofs))
        flaechen = None
        if ueberlagern and loeser.lu_erlaubt(frei_zahl, duenn)[0]:
            flaechen = _flaechen_waehlen(N, T, fs, beruehrt, groesse, h, nachbarn)
        if flaechen is not None:  # A4: Einheitslastfälle mit einer Zerlegung, dann überlagert
            schritt(0.5 + 0.4 * erledigt / max(len(offen), 1), f"lösen ({len(fs)} Lastfälle, Einheitslastfälle)")
            t2 = time.perf_counter()
            ldofs = np.unique(np.concatenate([lager_dofs[x] for x in lager]
                                             + [np.zeros(0, dtype=np.int64)])).astype(np.int64)
            d = _einheiten_rechnen(N, K, fest_dofs, zw, duenn, flaechen, ldofs)
            d.update({"fest": np.asarray(fest, dtype=np.int64), "lager": list(lager),
                      "lager_facetten": {x: np.asarray(beruehrt.get(x, np.zeros(0)), dtype=np.int64) for x in lager},
                      "lose": int(lose.sum()), "zwang": dict(zw.info) if zw is not None else None})
            t_loesen = (time.perf_counter() - t2) * 1000
            if pfad is not None:
                _einheit_speichern(pfad, d)
            out += _faelle_ueberlagert(N, C, T, fs, d, lager, arten, V, nachbarn, mit_sigma, netz_info, ablage, t0,
                                       {"netz": t_netz, "steifigkeit": t_k, "loesen": t_loesen}, False)
            erledigt += len(fs)
            schritt(0.5 + 0.45 * erledigt / max(len(offen), 1), f"{erledigt} von {len(offen)} Lastfällen fertig")
            continue
        if lose.any():
            for f in fs:
                f.setdefault("hinweise", []).append(f"{int(lose.sum())} Tetraeder ohne Verbindung zum Lager "
                                                    "weggelassen")
        vektoren, details = [], []
        for f in fs:
            lv, det = _lastvektor(N, T, f, beruehrt, groesse, h, V)
            vektoren.append(lv)
            details.append(det)
        schritt(0.5 + 0.4 * erledigt / max(len(offen), 1), f"lösen ({len(fs)} Lastfälle)")
        t2 = time.perf_counter()
        us, info = N.loese(K, fest_dofs, vektoren, duenn=duenn, zwang=zw)
        t_loesen = (time.perf_counter() - t2) * 1000
        for i, (f, u, det) in enumerate(zip(fs, us, details)):
            r_voll = np.asarray(K @ u).reshape(-1) - vektoren[i]
            loeser_info = {"verfahren": info["verfahren"][i], "iterationen": info["iterationen"][i],
                           "residuum": info["residuum"][i]}
            out.append(_fall_auswerten(N, C, T, f, u, r_voll, det, lager, arten, fest, fest_knoten, lager_dofs,
                                       dict(zw.info) if zw is not None else None, mit_sigma, netz_info, loeser_info,
                                       {"netz": t_netz, "steifigkeit": t_k, "loesen": t_loesen}, t0, ablage, None))
            erledigt += 1
        schritt(0.5 + 0.45 * erledigt / max(len(offen), 1), f"{erledigt} von {len(offen)} Lastfällen fertig")
    return out


def lagerkraefte(N: Any, K: Any, u: np.ndarray, f: np.ndarray, lager_dofs: dict[str, np.ndarray],
                 arten: dict[str, str], nachbarn: dict[str, Any]) -> dict[str, list[float]]:
    """Resultierende Lagerkraft je Lager (N, auf das Teil) aus der Reaktion r = K u − f (``lagerkraefte_aus_r``)."""
    return lagerkraefte_aus_r(N, np.asarray(K @ u).reshape(-1) - f, lager_dofs, arten, nachbarn)


def lagerkraefte_aus_r(N: Any, r: np.ndarray, lager_dofs: dict[str, np.ndarray], arten: dict[str, str],
                       nachbarn: dict[str, Any]) -> dict[str, list[float]]:
    """Resultierende Lagerkraft je Lager (N, auf das Teil): Reaktion r an den Orten seiner Fläche. Teilen sich Lager
    einen Ort (Kante zwischen zwei Lagerflächen), wird r dort nach ihren gehaltenen Richtungen aufgeteilt (kleinste
    Quadrate; gleitend nur in seinen Richtungen); ein festes oder gelenkiges Lager an diesem Ort nimmt, was übrig
    bleibt. A4: r kommt bei überlagerten Fällen aus den Reaktionen der Einheitsfälle (nur an den Lagern)."""
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


def _speicher_spitze_mb() -> float | None:
    """Größter belegter Speicher dieses Prozesses bisher (MB; macOS zählt ru_maxrss in Byte, Linux in kB)."""
    try:
        import resource

        r = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:  # noqa: BLE001 - nur eine Angabe
        return None
    return round(r / (1 << 20) if sys.platform == "darwin" else r / 1024, 1)


# -- Mehrere Prozesse (A2, PLAN-PRUEFUNG-INKREMENTELL.md) ------------------------------------------------------------
# Die Teile eines Auftrags sind voneinander unabhängig: Je Teil rechnet ein Teilprozess (Pool, spawn), dieselbe Funktion
# ``rechne_teil`` wie nacheinander, also dasselbe Ergebnis (die Zahl der Fäden ändert es nicht, gemessen 1, 2 und 4
# Fäden: bitgleich). Längste Teile zuerst (Zeit des letzten Laufs je Teilstand bzw. Teilname, sonst Größe), ein neues
# Teil nur, wenn sein geschätzter Speicher frei ist. Die Teilprozesse sind in der Prozessgruppe des FEM-Prozesses: Der
# Abbruch der Laufzeit (killpg) beendet alle, und stirbt der FEM-Prozess, beenden sie sich selbst.

PROZESSE_MAX = 3  # Kevin 07.11.2026: bis zu 3 FEM-Prozesse, bei Speicherdruck 2 bzw. 1
PROZESSE_ENV = "KEVCAD_FEM_PROZESSE"  # Zahl erzwingen, ohne Speicherprüfung (Tests, Messungen); 1: nacheinander hier
KIND_FAEDEN = 2  # Fäden (OMP, BLAS) je Teilprozess
FAEDEN_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")
MB_JE_FG = 0.032  # Speicherspitze eines Teilprozesses je Freiheitsgrad (A3: 25.600 → 0,80 GB, 48.500 → 1,45 GB)
MB_GRUND = 150.0
FG_ANNAHME = 40_000  # ohne Erfahrung mit dem Teil
RESERVE_MB = 1536.0  # so viel Arbeitsspeicher bleibt beim Verteilen frei
FREI_STUFEN = ((25.0, 3), (12.0, 2))  # freier Anteil (kern.memorystatus_level, %) → höchstens so viele Prozesse
ZEITEN_DATEI = "zeiten.json"  # Rechenzeit und Freiheitsgrade je Teilstand und Teilname (Reihenfolge, Speicher)
ZEITEN_MAX = 400
_STILL = False  # in Teilprozessen: keine Fortschrittszeilen (der FEM-Prozess meldet je fertigem Teil)


def speicher_lage() -> tuple[float | None, int | None]:
    """(freier Anteil in Prozent, Druckstufe 1 normal, 2 Warnung, 4 kritisch): macOS kern.memorystatus_level und
    kern.memorystatus_vm_pressure_level, sonst psutil ohne Druckstufe."""
    frei: float | None = None
    druck: int | None = None
    if sys.platform == "darwin":
        import subprocess

        try:
            w = subprocess.run(["sysctl", "-n", "kern.memorystatus_level", "kern.memorystatus_vm_pressure_level"],
                               capture_output=True, text=True, encoding="utf-8", timeout=3).stdout.split()
            frei, druck = float(w[0]), int(w[1])
        except Exception:  # noqa: BLE001
            frei, druck = None, None
    if frei is None:
        try:
            import psutil

            frei = 100.0 - float(psutil.virtual_memory().percent)
        except Exception:  # noqa: BLE001
            frei = None
    return frei, druck


def prozesse_zahl(teile: int, frei_prozent: float | None, druck: int | None) -> int:
    """Wie viele Teilprozesse für ``teile`` zu rechnende Teile: bis ``PROZESSE_MAX``, bei Speicherdruck (Warnung,
    weniger als 25 % frei) 2, kritisch oder unter 12 % frei 1 (dann nacheinander in diesem Prozess)."""
    erzwungen = (os.environ.get(PROZESSE_ENV) or "").strip()
    if erzwungen:
        try:
            return max(1, min(int(erzwungen), max(teile, 1)))
        except ValueError:
            pass
    if teile < 2:
        return 1
    n = PROZESSE_MAX
    if druck is not None and druck >= 4:
        n = 1
    elif druck is not None and druck >= 2:
        n = min(n, 2)
    if frei_prozent is not None:
        n = min(n, next((k for grenze, k in FREI_STUFEN if frei_prozent >= grenze), 1))
    return max(1, min(n, teile))


def _zeiten_lesen(ablage: Path) -> dict[str, Any]:
    try:
        z = json.loads((ablage / ZEITEN_DATEI).read_text(encoding="utf-8"))
        return z if isinstance(z, dict) else {}
    except Exception:  # noqa: BLE001 - fehlt oder kaputt: ohne Erfahrung
        return {}


def _zeiten_schreiben(ablage: Path, neu: dict[str, Any]) -> None:
    if not neu:
        return
    z = _zeiten_lesen(ablage)
    z.update(neu)
    if len(z) > ZEITEN_MAX:
        z = dict(sorted(z.items(), key=lambda kv: -float((kv[1] or {}).get("t") or 0.0))[:ZEITEN_MAX])
    try:
        ablage.mkdir(parents=True, exist_ok=True)
        tmp = ablage / f"{ZEITEN_DATEI}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(z, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ablage / ZEITEN_DATEI)
    except OSError:
        pass


def schaetzung(T: dict[str, Any], zeiten: dict[str, Any]) -> tuple[float, float]:
    """(Sekunden, Speicherspitze MB) eines Teils: aus dem letzten Lauf desselben Teilstands, sonst desselben Teils,
    sonst aus dem Volumen (nur für die Reihenfolge) und ``FG_ANNAHME``."""
    e = zeiten.get(f"teil:{T.get('schluessel_teil')}") or zeiten.get(f"name:{T.get('name')}")
    if isinstance(e, dict) and e.get("s") is not None:
        s, fg = float(e["s"]), float(e.get("fg") or FG_ANNAHME)
    else:
        s, fg = 0.5 + float(T.get("volumen") or 0.0) / 30000.0, float(FG_ANNAHME)
    return s, MB_GRUND + MB_JE_FG * fg


def _kinder_rss_mb() -> float:
    try:
        import psutil

        return sum(c.memory_info().rss for c in psutil.Process().children(recursive=True)) / (1 << 20)
    except Exception:  # noqa: BLE001
        return 0.0


def frei_system_mb() -> float | None:
    """Freier Arbeitsspeicher nach dem System (MB): macOS ``kern.memorystatus_level`` (Anteil frei, wie ihn das System
    für seinen Speicherdruck rechnet) mal Gesamtspeicher, sonst psutil (verfügbar)."""
    frei_prozent, _ = speicher_lage()
    try:
        import psutil

        vm = psutil.virtual_memory()
    except Exception:  # noqa: BLE001
        return None
    if sys.platform == "darwin" and frei_prozent is not None:
        return frei_prozent / 100.0 * float(vm.total) / (1 << 20)
    return float(vm.available) / (1 << 20)


def platz(bedarf_mb: float, laufend_mb: list[float], frei_mb: float | None = None,
          kinder_mb: float | None = None) -> bool:
    """Darf ein weiteres Teil starten? Frei ist, was das System frei meldet (``frei_system_mb``), abzüglich dessen, was
    die laufenden Teile nach ihrer Schätzung noch belegen werden; danach bleiben ``RESERVE_MB``."""
    frei = frei_system_mb() if frei_mb is None else frei_mb
    if frei is None:
        return True
    noch = max(0.0, sum(laufend_mb) - (_kinder_rss_mb() if kinder_mb is None else kinder_mb))
    return frei - noch >= bedarf_mb + RESERVE_MB


def _gescheitert(T: dict[str, Any], exc: BaseException) -> list[dict[str, Any]]:
    return [{"id": f["id"], "stand": "failed", "szenario": f["szenario"], "teil": T["name"],
             "meldung": f"nicht gerechnet: {type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=6)}
            for f in T["faelle"]]


def _teil(T: dict[str, Any], fein: bool, ablage: Path, beginn: float, von: float, bis: float) -> dict[str, Any]:
    """Ein Teil rechnen (hier oder im Teilprozess): Fälle (Felder als Pfad), Prozess, Beginn und Ende ab ``beginn``."""
    t0 = time.time()
    faelle: list[dict[str, Any]] = []
    try:
        for r in rechne_teil(T, fein, ablage, von, bis):
            felder = r.pop("_felder", None)
            if felder is not None and r.get("stand") == "done":
                r["feld"] = str(ablage / "faelle" / f"{r['schluessel']}.npz")
            faelle.append(r)
    except Exception as exc:  # noqa: BLE001 - ein Teil darf die anderen nicht verhindern
        faelle = _gescheitert(T, exc)
    return {"faelle": faelle, "pid": os.getpid(), "start": round(t0 - beginn, 3), "ende": round(time.time() - beginn, 3),
            "speicher_mb": _speicher_spitze_mb(), "faeden": os.environ.get("OMP_NUM_THREADS")}


def _kind_start() -> None:
    """Teilprozess: still, und beenden, sobald der FEM-Prozess nicht mehr lebt."""
    import threading

    global _STILL
    _STILL = True
    eltern = os.getppid()

    def wache() -> None:
        while True:
            time.sleep(1.0)
            if os.getppid() != eltern:
                os._exit(3)

    threading.Thread(target=wache, name="fem-wache", daemon=True).start()


def _kind_teil(T: dict[str, Any], fein: bool, ablage: str, beginn: float) -> dict[str, Any]:
    return _teil(T, fein, Path(ablage), beginn, 0.0, 1.0)


def _gespeichert(T: dict[str, Any], f: dict[str, Any], ablage: Path) -> bool:
    return (ablage / "faelle" / f"{f['schluessel']}.npz").exists() and (
        not T.get("grenze") or (ablage / "faelle" / f"{f['schluessel']}.sig.npz").exists())


def _aus_speicher(T: dict[str, Any], ablage: Path) -> bool:
    """Liegen alle Fälle des Teils im Zwischenspeicher?"""
    return all(_gespeichert(T, f, ablage) for f in T["faelle"])


def _leicht(T: dict[str, Any], fein: bool, ablage: Path) -> bool:
    """Braucht das Teil keine Zerlegung (alle Fälle im Zwischenspeicher oder je Lagergruppe gemerkte Einheitsfälle, A4)?
    Dann rechnet es der FEM-Prozess selbst, ohne Teilprozess."""
    offen = [f for f in T["faelle"] if not _gespeichert(T, f, ablage)]
    if not offen:
        return True
    if not _ueberlagern_an():
        return False
    gruppen: dict[tuple, list[dict[str, Any]]] = {}
    for f in offen:
        gruppen.setdefault(tuple(sorted(f["lager"])), []).append(f)
    nachbarn = _Nachbarn(T)
    try:
        return all(_einheit_pfad(ablage, T, fein, lager, fs, nachbarn).exists() for lager, fs in gruppen.items())
    except Exception:  # noqa: BLE001
        return False


def _parallel(teile: list[dict[str, Any]], offen: list[int], fein: bool, ablage: Path, n: int, beginn: float,
              je_teil: dict[int, dict[str, Any]], fertig: Any, hier: list[int] | None = None) -> list[int]:
    """Teile ``offen`` (Indizes) auf bis zu n Teilprozesse verteilen, Ergebnis je Index in ``je_teil``; ``fertig(i)``
    nach jedem Teil. ``hier``: leichte Teile, die dieser Prozess rechnet, während die Teilprozesse arbeiten. Rückgabe:
    Indizes, die kein Teilprozess fertig bekam (Pool abgestürzt), die rechnet der Aufrufer."""
    # Fäden je Teilprozess: Die Umgebung gilt, solange der Pool besteht, denn mit spawn entstehen die Teilprozesse erst
    # beim submit (zuvor nur um den Bau des Pools gesetzt, kam die Grenze nie an: drei Prozesse mit allen Kernen). Auf
    # diesen Prozess wirkt sie nicht mehr, numpy und scipy sind hier schon geladen.
    alt = {k: os.environ.get(k) for k in FAEDEN_VARS}
    os.environ.update({k: str(KIND_FAEDEN) for k in FAEDEN_VARS})
    try:
        return _parallel_pool(teile, offen, fein, ablage, n, beginn, je_teil, fertig, hier)
    finally:
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _parallel_pool(teile: list[dict[str, Any]], offen: list[int], fein: bool, ablage: Path, n: int, beginn: float,
                   je_teil: dict[int, dict[str, Any]], fertig: Any, hier: list[int] | None) -> list[int]:
    global _STILL
    import concurrent.futures as cf
    import multiprocessing as mp

    from kevcad_kernel.statik.festkoerper import prozess as modul  # über den Modulnamen, auch wenn dies __main__ ist

    zeiten = _zeiten_lesen(ablage)
    sch = {i: schaetzung(teile[i], zeiten) for i in offen}
    warte = sorted(offen, key=lambda i: (-sch[i][0], i))
    ex = cf.ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("spawn"), initializer=modul._kind_start)
    laufend: dict[Any, int] = {}
    rest: list[int] = []
    kaputt = False
    erzwungen = bool((os.environ.get(PROZESSE_ENV) or "").strip())  # Tests, Messungen: ohne Speicherprüfung
    try:
        while (warte or laufend) and not kaputt:
            while warte and len(laufend) < n and (not laufend or erzwungen or platz(
                    sch[warte[0]][1], [sch[j][1] for j in laufend.values()])):
                i = warte.pop(0)
                laufend[ex.submit(modul._kind_teil, teile[i], fein, str(ablage), beginn)] = i
            while hier:  # leichte Teile hier, während die Teilprozesse rechnen
                i = hier.pop(0)
                _STILL = True
                try:
                    je_teil[i] = _teil(teile[i], fein, ablage, beginn, 0.0, 1.0)
                finally:
                    _STILL = False
                fertig(i)
            erledigt, _ = cf.wait(list(laufend), timeout=1.0, return_when=cf.FIRST_COMPLETED)
            for fut in erledigt:
                i = laufend.pop(fut)
                try:
                    je_teil[i] = fut.result()
                except cf.process.BrokenProcessPool:
                    kaputt = True
                    rest.append(i)
                    continue
                except Exception as exc:  # noqa: BLE001 - Übergabe gescheitert: dieses Teil als Fehler
                    je_teil[i] = {"faelle": _gescheitert(teile[i], exc), "pid": None, "start": None, "ende": None}
                fertig(i)
        rest += list(laufend.values()) + warte + list(hier or [])
    finally:
        ex.shutdown(wait=not kaputt, cancel_futures=True)
    return rest


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("Aufruf: python -m kevcad_kernel.statik.festkoerper.prozess auftrag.json ergebnis.json",
              file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    beginn = time.time()
    auftrag = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    ablage = speicher()
    # beginn und zeiten_teile (Wanduhr, s ab beginn) für Zeitleisten (benchmark/pruefzeit.py), speicher_mb: Spitze
    out: dict[str, Any] = {"stand": "done", "faelle": [], "pid": os.getpid(), "grenzen": list(GRENZEN_S3),
                           "beginn": beginn, "zeiten_teile": []}
    teile = auftrag.get("teile") or []
    fein = bool(auftrag.get("fein"))
    offen = [i for i, T in enumerate(teile) if not _leicht(T, fein, ablage)]
    n = prozesse_zahl(len(offen), *speicher_lage()) if len(offen) >= 2 else 1
    out["prozesse_zahl"] = n
    melde(0.0, f"{len(teile)} Teile" + (f", {n} Prozesse" if n >= 2 else ""))
    je_teil: dict[int, dict[str, Any]] = {}
    gezaehlt = {"n": 0}

    def fertig(i: int) -> None:
        gezaehlt["n"] += 1
        melde(gezaehlt["n"] / max(len(teile), 1), f"{teile[i]['name'].rsplit('/', 1)[-1]}: fertig "
                                                  f"({gezaehlt['n']} von {len(teile)} Teilen)")

    rest = list(range(len(teile)))
    if n >= 2:  # leichte Teile (Zwischenspeicher, gemerkte Einheitsfälle) hier, während die Teilprozesse rechnen
        rest = _parallel(teile, offen, fein, ablage, n, beginn, je_teil, fertig, [i for i in rest if i not in offen])
    for i in rest:  # nacheinander in diesem Prozess (wie bisher; auch, was ein abgestürzter Pool übrig ließ)
        je_teil[i] = _teil(teile[i], fein, ablage, beginn, i / max(len(teile), 1), (i + 1) / max(len(teile), 1))
    neu_zeiten: dict[str, Any] = {}
    prozesse: dict[Any, float | None] = {os.getpid(): None}
    for i, T in enumerate(teile):
        e = je_teil[i]
        out["faelle"] += e["faelle"]
        out["zeiten_teile"].append({"teil": T["name"], "pid": e.get("pid"), "start": e.get("start"),
                                    "ende": e.get("ende"), "faeden": e.get("faeden")})
        if e.get("pid") is not None:
            prozesse[e["pid"]] = max(prozesse.get(e["pid"]) or 0.0, e.get("speicher_mb") or 0.0) or None
        gerechnet = [r for r in e["faelle"] if r.get("stand") == "done" and not r.get("aus_speicher")]
        if gerechnet and e.get("start") is not None:
            fg = (gerechnet[0].get("netz") or {}).get("freiheitsgrade")
            eintrag = {"s": round(float(e["ende"]) - float(e["start"]), 3), "fg": fg, "t": round(time.time(), 1)}
            neu_zeiten[f"teil:{T.get('schluessel_teil')}"] = eintrag
            neu_zeiten[f"name:{T.get('name')}"] = eintrag
    _zeiten_schreiben(ablage, neu_zeiten)
    if any(T.get("grenze") for T in teile):
        melde(0.97, "Grenze suchen (Halbieren über die überlagerten Spannungen)")
        out["grenze"] = grenzen_suchen(teile, out["faelle"], ablage)
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["speicher_mb"] = _speicher_spitze_mb()
    prozesse[os.getpid()] = out["speicher_mb"]
    out["prozesse"] = [{"pid": pid, "speicher_mb": mb} for pid, mb in prozesse.items()]
    melde(1.0, "fertig")
    tmp = argv[1] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    os.replace(tmp, argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
