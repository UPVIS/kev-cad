"""Messhülle für die Analyse „Prüfung inkrementell“ (nicht Teil des Repos).

Aktiv nur mit KCZ_PROTOKOLL=<datei.jsonl>. Schreibt je Prozess Zeitstempel (time.time()) für:
- Rechenprozess: Runner.run, Runner.pruefe, Runner.fertig_rechnen (auch abgebrochene Abschnitte), Runner.execute
- FEM-Prozess (statik.festkoerper.prozess.rechne_teil): je Teil Dauer und Fälle aus dem Speicher
Mit KCZ_PROFIL=<ordner> zusätzlich cProfile je Aufruf von pruefe, fertig_rechnen und execute.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

_P = os.environ.get("KCZ_PROTOKOLL")
_PROF = os.environ.get("KCZ_PROFIL")
_lock = threading.Lock()
_zaehler = {"n": 0}


def log(ereignis: str, **kw: object) -> None:
    z = {"t": time.time(), "pid": os.getpid(), "e": ereignis, **kw}
    with _lock:
        with open(_P, "a", encoding="utf-8") as f:  # type: ignore[arg-type]
            f.write(json.dumps(z, ensure_ascii=False, default=str) + "\n")


def _profil(label: str):
    if not _PROF:
        return None
    import cProfile

    p = cProfile.Profile()
    p.enable()
    return p


def _profil_ende(p, label: str) -> None:
    if p is None:
        return
    p.disable()
    _zaehler["n"] += 1
    os.makedirs(_PROF, exist_ok=True)
    p.dump_stats(os.path.join(_PROF, f"{os.getpid()}-{_zaehler['n']:03d}-{label}.prof"))


def _patch_runner(mod: object) -> None:
    R = mod.Runner  # type: ignore[attr-defined]

    o_run, o_pruefe, o_fertig, o_exec = R.run, R.pruefe, R.fertig_rechnen, R.execute

    def run(self, header, *a, **kw):
        t0 = time.time()
        log("run_start", run=header.get("run"), schatten=bool(header.get("schatten")), params=header.get("params"))
        try:
            return o_run(self, header, *a, **kw)
        finally:
            log("run_ende", run=header.get("run"), schatten=bool(header.get("schatten")), s=round(time.time() - t0, 3))

    def pruefe(self, run, *a, **kw):
        t0 = time.time()
        log("pruefe_start", run=run)
        uhr_reset()
        zw = kw.get("zwischenstand")
        if zw is not None:
            def zwischenstand(kopf, nutz, _zw=zw):
                log("zwischenstand", run=run, s=round(time.time() - t0, 3), state=kopf.get("state"),
                    offen=kopf.get("im_hintergrund"))
                return _zw(kopf, nutz)
            kw["zwischenstand"] = zwischenstand
        p = _profil("pruefe")
        try:
            erg = o_pruefe(self, run, *a, **kw)
            kopf = erg[0] if isinstance(erg, tuple) else {}
            stat = kopf.get("statistik") or {}
            log("pruefe_ende", run=run, s=round(time.time() - t0, 3), state=kopf.get("state"),
                offen=kopf.get("im_hintergrund"), zeiten=stat.get("zeiten_ms"), paare=stat.get("paare"))
            if os.environ.get("KCZ_KOERPER"):
                pl = getattr(self, "_pruef_lauf", None)
                if pl is not None:
                    import hashlib

                    ks = {}
                    for (name, key), k in pl.koerper.items():
                        lage = getattr(k, "lage", None)
                        ks[name] = {"key": key[:16], "form": str(k.form)[:16],
                                    "lage": None if lage is None else hashlib.sha1(
                                        __import__("numpy").round(lage, 6).tobytes()).hexdigest()[:12]}
                    log("koerper", run=run, teile=ks)
            return erg
        except BaseException as exc:
            log("pruefe_abbruch", run=run, s=round(time.time() - t0, 3), fehler=repr(exc))
            raise
        finally:
            _profil_ende(p, f"pruefe-r{run}")
            if UHR:
                log("uhr", phase="pruefe", run=run, tabelle=uhr_tabelle())

    def fertig_rechnen(self, run, *a, **kw):
        t0 = time.time()
        log("fertig_start", run=run)
        uhr_reset()
        p = _profil("fertig")
        try:
            erg = o_fertig(self, run, *a, **kw)
            log("fertig_ende", run=run, s=round(time.time() - t0, 3), ergebnis=erg is not None)
            return erg
        except BaseException as exc:
            log("fertig_abbruch", run=run, s=round(time.time() - t0, 3), fehler=repr(exc))
            raise
        finally:
            _profil_ende(p, f"fertig-r{run}")
            if UHR:
                log("uhr", phase="fertig", run=run, tabelle=uhr_tabelle())

    def execute(self, header, *a, **kw):
        t0 = time.time()
        code = str(header.get("code") or "")
        kurz = code[:160]
        log("exec_start", run=header.get("run"), code=kurz)
        uhr_reset()
        p = _profil("exec")
        try:
            return o_exec(self, header, *a, **kw)
        finally:
            log("exec_ende", run=header.get("run"), code=kurz, s=round(time.time() - t0, 3))
            if UHR:
                log("uhr", phase="exec", run=header.get("run"), tabelle=uhr_tabelle())
            _profil_ende(p, f"exec-r{header.get('run')}")

    R.run, R.pruefe, R.fertig_rechnen, R.execute = run, pruefe, fertig_rechnen, execute
    log("gepatcht", modul="runner", datei=getattr(mod, "__file__", None))


def _patch_fem(mod: object) -> None:
    o = mod.rechne_teil  # type: ignore[attr-defined]

    def rechne_teil(T, fein, ablage, von, bis, *a, **kw):
        t0 = time.time()
        out = o(T, fein, ablage, von, bis, *a, **kw)
        log("fem_teil", teil=T.get("name"), faelle=len(T.get("faelle") or []), s=round(time.time() - t0, 3),
            aus_speicher=[bool(r.get("aus_speicher")) for r in out],
            ms=[r.get("ms") for r in out if isinstance(r, dict)])
        return out

    mod.rechne_teil = rechne_teil  # type: ignore[attr-defined]


def _patch_auftrag(mod: object) -> None:
    o = mod.schreibe  # type: ignore[attr-defined]

    def schreibe(st, wunsch, *a, **kw):
        t0 = time.time()
        out = o(st, wunsch, *a, **kw)
        log("fem_auftrag", s=round(time.time() - t0, 3),
            faelle=[(f["szenario"], f["teil"], f["schluessel"]) for f in out.get("faelle") or []],
            nicht=out.get("nicht"))
        return out

    mod.schreibe = schreibe  # type: ignore[attr-defined]


def _patch_bewegungsraum(mod: object) -> None:
    o_pb = mod.pruefe_bewegung  # type: ignore[attr-defined]
    o_kf = mod._kollisionsfunktion  # type: ignore[attr-defined]

    def pruefe_bewegung(bew, formen, schluessel, zeitlimit_s, *a, **kw):
        t0 = time.time()
        out = o_pb(bew, formen, schluessel, zeitlimit_s, *a, **kw)
        if out is not None:
            log("weg", name=bew.name, teile=len(bew.teile), schritte=len(bew.werte()) - 1,
                zwischenspeicher=bool(out.get("zwischenspeicher")), teilweise=bool(out.get("teilweise")),
                s=round(time.time() - t0, 3), zeitlimit=zeitlimit_s)
        return out

    def _kollisionsfunktion():
        fn = o_kf()

        def wrap(formen, lagen, zeiten, **kw):
            t0 = time.time()
            befunde, stats = fn(formen, lagen, zeiten, **kw)
            log("kollision", paare=stats.get("paare"), kandidaten=stats.get("kandidaten"), exakt=stats.get("exakt"),
                zwischenspeicher=stats.get("zwischenspeicher"), abgebrochen=stats.get("abgebrochen"),
                s=round(time.time() - t0, 3))
            return befunde, stats

        return wrap

    mod.pruefe_bewegung = pruefe_bewegung  # type: ignore[attr-defined]
    mod._kollisionsfunktion = _kollisionsfunktion  # type: ignore[attr-defined]


# -- Wanduhr je Funktion (inklusive, nur äußerster Aufruf), je pruefe/fertig_rechnen/execute einmal ausgegeben --------

UHR: dict[str, list[float]] = {}
_tiefe: dict[str, int] = {}


_SCHNITT_ZAEHLER: dict[str, int] = {}


def uhr_reset() -> None:
    UHR.clear()
    _SCHNITT_ZAEHLER.clear()


def uhr_tabelle() -> dict[str, list[float]]:
    return {k: [int(v[0]), round(v[1] * 1000, 1)] for k, v in sorted(UHR.items(), key=lambda kv: -kv[1][1])}


def _zeitnehmer(name: str, fn):
    def f(*a, **kw):
        d = _tiefe.get(name, 0)
        _tiefe[name] = d + 1
        t0 = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            _tiefe[name] = d
            if d == 0:
                e = UHR.setdefault(name, [0, 0.0])
                e[0] += 1
                e[1] += time.perf_counter() - t0

    f.__wrapped__ = fn  # type: ignore[attr-defined]
    return f


def _uhr_patch(namen: list[str]):
    """Patcher für ein Modul: Namen „f“ (Modulfunktion) oder „Klasse.methode“."""
    def patch(mod):
        for n in namen:
            try:
                if "." in n:
                    cls, meth = n.split(".", 1)
                    c = getattr(mod, cls)
                    setattr(c, meth, _zeitnehmer(f"{mod.__name__.rsplit('.', 1)[-1]}.{n}", getattr(c, meth)))
                else:
                    setattr(mod, n, _zeitnehmer(f"{mod.__name__.rsplit('.', 1)[-1]}.{n}", getattr(mod, n)))
            except Exception as exc:  # noqa: BLE001
                log("uhr_fehler", modul=mod.__name__, name=n, fehler=repr(exc))
    return patch


UHR_ZIELE = {
    "kevcad_kernel.pruefung.pruefer": ["pruefe_paar"],
    "kevcad_kernel.pruefung.raster": ["rastern", "blockiert", "freier_weg"],
    "kevcad_kernel.pruefung.montage": ["Planer.__init__", "Planer.plane", "Planer.frei", "Planer.kandidaten",
                                       "Planer.sperrt", "Planer.zwei_schritte", "Planer.einheiten", "Planer._loesen",
                                       "werkzeug_befunde", "blockiert"],
    "kevcad_kernel.pruefung.koerper": ["Koerper.projektion", "Koerper.strahl", "koerper_aus_topo"],
    "kevcad_kernel.pruefung.stand": ["pruefe_stand"],
    "kevcad_kernel.statik.anbindung": ["simulation_vorbereiten", "rechne_gruppen", "szenarien_fuer", "modelle_bauen",
                                       "stufe4_aus", "simulation_ergebnis"],
    "kevcad_kernel.statik.modell": ["baue"],
    "kevcad_kernel.statik.merken": ["gemerkt", "fingerabdruck"],
    "kevcad_kernel.statik.rechnen": ["rechne_alles", "_lagerteile", "_verbinderteile", "befunde", "sauber"],
    "kevcad_kernel.statik.feder": ["setze", "drehfeder", "nachgiebigkeit_teil", "bohrungslaenge"],
    "kevcad_kernel.statik.stabwerk": ["rechne", "_knicken", "_auswerten"],
    "kevcad_kernel.statik.s0": ["rechne", "kippen", "rutschen", "lose_teile", "schrauben", "traeger"],
    "kevcad_kernel.statik.bauteil": ["pruefe_last", "schnitte", "_schnitt", "vorschlag_druck", "tragende_nachbarn"],
    "kevcad_kernel.statik.bewertung": ["bewerte", "ueberdimensioniert", "staerker", "alternative"],
    "kevcad_kernel.anim_kollision": ["_common", "_sphere_free"],
    "kevcad_kernel.bedingungen.bewegungsraum": ["_griffraum_pruefen", "_gewinde_in_ruhe", "_dreht_um_sich",
                                                "bewegungen_pruefen", "_gemeinsam"],
    "kevcad_kernel.druck.anbindung": ["_pruefe_form", "_ergebnis_fuer", "_abdruecke_buendeln", "_abdruck_von",
                                      "_teil_info"],
}


PATCHES = {"kevcad_kernel.runner": _patch_runner, "kevcad_kernel.statik.festkoerper.prozess": _patch_fem,
           "kevcad_kernel.statik.festkoerper.auftrag": _patch_auftrag,
           "kevcad_kernel.bedingungen.bewegungsraum": _patch_bewegungsraum}
if os.environ.get("KCZ_UHR"):
    for _m, _n in UHR_ZIELE.items():
        alt = PATCHES.get(_m)
        neu = _uhr_patch(_n)
        if alt is None:
            PATCHES[_m] = neu
        else:
            PATCHES[_m] = (lambda a, b: (lambda mod: (a(mod), b(mod))))(alt, neu)


if _P:
    import importlib.abc

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):  # noqa: D401
            if name not in PATCHES:
                return None
            for f in sys.meta_path:
                if f is self or not hasattr(f, "find_spec"):
                    continue
                spec = f.find_spec(name, path, target)
                if spec is not None:
                    break
            else:
                return None
            loader = spec.loader
            orig = loader.exec_module

            def exec_module(module, _orig=orig, _name=name):
                _orig(module)
                try:
                    PATCHES[_name](module)
                except Exception as exc:  # noqa: BLE001
                    log("patch_fehler", modul=_name, fehler=repr(exc))

            loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _Finder())
    # -m kevcad_kernel.statik.festkoerper.prozess läuft als __main__: dann direkt am Hauptmodul patchen geht nicht;
    # stattdessen protokolliert der Prozessstart selbst
    if len(sys.argv) >= 1:
        log("prozess", argv=sys.argv[:3])


# -- Schattenzähler (KCZ_SCHATTEN=1): was ein Schlüssel aus Form ohne Lage plus relativer Lage gespart hätte ----------

_FORM_JE_WELT: dict[str, tuple[str, object]] = {}
_SCHATTEN_BEW: set = set()
_SCHNITT_LETZT: dict[str, tuple] = {}


def _form_lage(name: str, shape, weltkey: str):
    import numpy as np

    hit = _FORM_JE_WELT.get(weltkey)
    if hit is None:
        from kevcad_kernel.pruefung.koerper import form_schluessel, lage_von

        w = getattr(shape, "wrapped", shape)
        hit = (form_schluessel(w), lage_von(w))
        _FORM_JE_WELT[weltkey] = hit
    return hit


def _patch_bew_schatten(mod) -> None:
    import numpy as np

    o_kf = mod._kollisionsfunktion

    def _kollisionsfunktion():
        fn = o_kf()

        def wrap(formen, lagen, zeiten, **kw):
            from kevcad_kernel.anim_kollision import _box_of, _corners

            paare = list(kw.get("paare") or [])
            sk = kw.get("schluessel") or {}
            cache = kw.get("cache")
            tol = kw.get("toleranz", 0.05)
            n_kand = n_cur = n_alt = n_alt_statt = 0
            neue_alt = []
            zeiten_a = np.asarray(zeiten, float)
            eye = np.repeat(np.eye(4)[None], len(zeiten_a), axis=0)
            boxes = {}
            for a, b in paare:
                for n in (a, b):
                    if n not in boxes:
                        boxes[n] = _box_of(formen[n])
                ta = lagen[a] if a in lagen else eye
                tb = lagen[b] if b in lagen else eye
                rel = np.linalg.solve(ta, tb)
                alo, ahi = boxes[a]
                pc = np.einsum("fij,kj->fki", rel[:, :3, :3], _corners(*boxes[b])) + rel[:, None, :3, 3]
                blo, bhi = pc.min(axis=1), pc.max(axis=1)
                mask = np.all(blo < ahi - tol, axis=1) & np.all(bhi > alo + tol, axis=1)
                if not mask.any():
                    continue
                fa, La = _form_lage(a, formen[a], sk.get(a, a))
                fb, Lb = _form_lage(b, formen[b], sk.get(b, b))
                for i in np.nonzero(mask)[0]:
                    n_kand += 1
                    key = (sk.get(a, a), sk.get(b, b), tuple(np.round(rel[i, :3, :].ravel(), 4)))
                    cur = cache is not None and key in cache
                    relw = np.linalg.solve(La, rel[i] @ Lb)
                    akey = (fa, fb, tuple(np.round(relw[:3, :].ravel(), 4)))
                    alt = akey in _SCHATTEN_BEW
                    n_cur += bool(cur)
                    n_alt += bool(alt)
                    n_alt_statt += bool(alt and not cur)
                    neue_alt.append(akey)
            befunde, stats = fn(formen, lagen, zeiten, **kw)
            _SCHATTEN_BEW.update(neue_alt)
            log("bew_schatten", kandidaten=n_kand, treffer_jetzt=n_cur, treffer_form_rel=n_alt,
                nur_mit_form_rel=n_alt_statt, exakt=stats.get("exakt"), s=stats.get("ms"))
            return befunde, stats

        return wrap

    mod._kollisionsfunktion = _kollisionsfunktion


def _patch_schnitt_schatten(mod) -> None:
    import numpy as np

    o = mod.schnitte

    def schnitte(k, R, P, *a, **kw):
        vorher = UHR.get("bauteil._schnitt", [0, 0.0])[0] if UHR else None
        t0 = time.perf_counter()
        out = o(k, R, P, *a, **kw)
        dt = time.perf_counter() - t0
        jetzt = (k.form, tuple(np.round(np.asarray(k.lage, float).reshape(-1), 4)), tuple(np.round(R, 2)),
                 tuple(np.round(P, 2)))
        idx = _SCHNITT_ZAEHLER.get(k.name, 0)
        _SCHNITT_ZAEHLER[k.name] = idx + 1
        alt = _SCHNITT_LETZT.get((k.name, idx))
        if dt > 0.005:  # gerechnet (kein Treffer)
            grund = "neu" if alt is None else ",".join(n for n, x, y in zip(("form", "lage", "R", "P"), alt, jetzt)
                                                         if x != y) or "gleich?"
            log("schnitt_neu", teil=k.name, idx=idx, grund=grund, s=round(dt, 3),
                dR=None if alt is None else round(float(np.linalg.norm(np.subtract(alt[2], jetzt[2]))), 3),
                dP=None if alt is None else round(float(np.linalg.norm(np.subtract(alt[3], jetzt[3]))), 3))
        _SCHNITT_LETZT[(k.name, idx)] = jetzt
        return out

    mod.schnitte = schnitte


if _P and os.environ.get("KCZ_SCHATTEN"):
    _alt_bew = PATCHES.get("kevcad_kernel.bedingungen.bewegungsraum")
    PATCHES["kevcad_kernel.bedingungen.bewegungsraum"] = (
        lambda mod: ((_alt_bew(mod) if _alt_bew else None), _patch_bew_schatten(mod)))
    _alt_bt = PATCHES.get("kevcad_kernel.statik.bauteil")
    PATCHES["kevcad_kernel.statik.bauteil"] = (
        lambda mod: ((_alt_bt(mod) if _alt_bt else None), _patch_schnitt_schatten(mod)))
