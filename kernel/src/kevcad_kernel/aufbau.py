"""Aufbau-Videos: das Modell entsteht Teil für Teil, die Kamera kreist oder wechselt die Blickwinkel.

Kevin, 06.11.2026: „das 3-D Modell baut sich ein Stück für Stück auf … man kann dann ne Zeit bestimmen und parallel wär
halt ein Orbit geil … mehrere Blickwinkel, so dass man da sich verschiedene Sachen zusammenbauen kann“.

Der Agent ruft ``aufbau_video``. Der Kernel rechnet model.py wie sonst und hängt im Rechenprozess danach Animationen an
(``erzeugen``): eine je Blickwinkel, alle mit denselben Zeiten, damit sich die Videos im Schnitt mischen lassen wie bei
mehreren Kameras. Die Teile erscheinen Schritt für Schritt und fliegen dabei ein. Auf Wunsch entsteht vor einem Schritt
ein Strich in Kevins Lichtblau, wie wenn er beim Sprechen zeichnet, und das Teil kommt an dieser Stelle dazu. Die App
rendert die Animationen wie jede andere (``animation_video``). model.py bleibt unberührt; der nächste normale Lauf hat die
Aufbau-Animationen nicht mehr.

Die Rechnung ist rein (``plan``): Teile, Hüllquader und Wunsch rein, Zeitplan und Kamerafahrten raus. ``erzeugen`` setzt
den Plan im Rechenprozess in Striche und Animationen um.
"""

from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

STRICH_PRAEFIX = "Skizze/"
STRICH_FARBE = "#8FC6FF"  # Kevins Lichtblau in der App (GF.kevin)
SEITENVERHAELTNIS = 16 / 9  # Vorgabe; Hochformat über wunsch["seitenverhaeltnis"] (Breite / Höhe, 9:16 = 0,5625)

# Azimut in Grad ab +X gegen den Uhrzeigersinn, Höhe in Grad über dem Horizont. Z oben, „vorne“ blickt wie die
# Standardansicht des Viewers in +Y (Kamera auf der Seite −Y), „iso“ von vorne rechts oben.
RICHTUNGEN: dict[str, tuple[float, float]] = {
    "vorne": (-90.0, 14.0),
    "hinten": (90.0, 14.0),
    "rechts": (0.0, 14.0),
    "links": (180.0, 14.0),
    "oben": (-90.0, 86.0),
    "iso": (-45.0, 35.26),
    "iso_vorne_links": (-135.0, 35.26),
    "iso_hinten_rechts": (45.0, 35.26),
    "iso_hinten_links": (135.0, 35.26),
}
ALIAS = {"front": "vorne", "back": "hinten", "right": "rechts", "left": "links", "top": "oben",
         "iso_front_left": "iso_vorne_links", "iso_back_right": "iso_hinten_rechts", "iso_back_left": "iso_hinten_links"}
BLICKWINKEL = ("orbit", "schnitt", *RICHTUNGEN)
EINFLUG = ("oben", "explosion", "keiner")

MIN_ABSTAND_S = 0.08  # kürzester Abstand zweier Schritte; mehr Schritte werden zusammengelegt
KAMERA_TAKT_S = 0.25  # Schlüsselbilder der Kamerafahrt
STRICH_PAUSE_S = 0.25  # nach dem Strich, bevor das Teil kommt
STRICH_NACHLAUF_S = 0.35  # der Strich bleibt, bis das Teil gelandet ist
MAX_STRICH_STUECKE = 28


class AufbauFehler(ValueError):
    """Wunsch passt nicht zum Modell (unbekannter Schritt, zu kurze Dauer …); die Meldung geht an den Agenten."""


@dataclass
class Strich:
    ziel: str  # Schritt oder Teil, vor dem er entsteht (wie in ``zeichnen``)
    punkte: list[tuple[float, float, float]]
    dauer: float
    radius: float
    wunsch_von: float | None = None
    vor: int = 0  # Index des Schritts, vom Plan gesetzt
    von: float = 0.0  # Zeiten, vom Plan gesetzt
    bis: float = 0.0
    weg: float = 0.0
    namen: list[str] = field(default_factory=list)


@dataclass
class Schritt:
    teile: list[str]
    titel: str
    zeit: float = 0.0
    landet: float = 0.0
    wunsch_landet: float | None = None  # feste Zeit aus dem Wunsch (etwa auf einen Schlag der Musik)


@dataclass
class Kamerafahrt:
    titel: str  # „Orbit“, „Iso“, „Schnitt“ …
    schluessel: list[tuple[float, tuple[float, float, float], tuple[float, float, float]]]  # (zeit, lage, ziel)
    schnitte: list[float] = field(default_factory=list)


@dataclass
class Plan:
    name: str
    dauer: float
    fps: float
    bildwinkel: float
    einflug: str
    einflug_s: float
    schritte: list[Schritt]
    striche: list[Strich]
    fahrten: list[Kamerafahrt]
    mitte: tuple[float, float, float]
    radius: float
    versatz: dict[str, tuple[float, float, float]]  # Einflug je Teil (Abstand zur Ruhelage zu Beginn)

    def zeitplan(self) -> dict[str, Any]:
        """Für den Agenten und den Schnitt danach (Untertitel auf die Schritte legen): wann erscheint was."""
        return {
            "name": self.name, "dauer": self.dauer, "fps": self.fps, "einflug": self.einflug,
            "einflug_s": round(self.einflug_s, 3),
            "schritte": [{"zeit": round(s.zeit, 3), "landet": round(s.landet, 3), "titel": s.titel,
                          "teile": list(s.teile)} for s in self.schritte],
            "striche": [{"vor": st.ziel, "schritt": self.schritte[st.vor].titel, "von": round(st.von, 3), "bis": round(st.bis, 3),
                         "weg": round(st.weg, 3)} for st in self.striche],
            "videos": [{"titel": f.titel, "animation": animationsname(self.name, f.titel),
                        "schnitte": [round(t, 3) for t in f.schnitte]} for f in self.fahrten],
        }


def animationsname(name: str, titel: str) -> str:
    return f"{name} {titel}"


def richtung(name: str) -> str:
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    key = ALIAS.get(key, key)
    if key not in RICHTUNGEN and key not in ("orbit", "schnitt"):
        raise AufbauFehler(f"Blickwinkel {name!r} gibt es nicht ({', '.join(BLICKWINKEL)})")
    return key


# ---------------------------------------------------------------------------------------------------------------------
# Schritte
# ---------------------------------------------------------------------------------------------------------------------


def _trifft(eintrag: str, teil: str) -> bool:
    if any(c in eintrag for c in "*?["):
        return fnmatch.fnmatchcase(teil, eintrag) or fnmatch.fnmatchcase(teil, eintrag + "/*")
    return teil == eintrag or teil.startswith(eintrag + "/")


def _titel(teile: list[str]) -> str:
    if len(teile) == 1:
        return teile[0]
    teile_pfade = [t.split("/") for t in teile]
    gemeinsam: list[str] = []
    for stuecke in zip(*teile_pfade):
        if len(set(stuecke)) != 1:
            break
        gemeinsam.append(stuecke[0])
    return "/".join(gemeinsam) if gemeinsam else f"{teile[0]} und {len(teile) - 1} weitere"


def schritte_aufloesen(eintraege: list[Any] | None, teile: list[str]) -> list[Schritt]:
    """Schritte aus Kevins bzw. des Agenten Liste (Teilname, Baugruppe als Präfix, Muster mit * und ?; oder
    {"auf": …, "landet": s} mit fester Zeit); was keiner nennt, kommt in der Reihenfolge von show() zum Schluss. Ohne
    Liste: in der Reihenfolge von show(), aufeinanderfolgende Teile derselben Baugruppe zusammen, Teile ohne Baugruppe
    einzeln."""
    if not teile:
        raise AufbauFehler("Das Modell zeigt keine Teile, die sich aufbauen ließen")
    if eintraege:
        rest = list(teile)
        out: list[Schritt] = []
        for roh in eintraege:
            landet = None
            if isinstance(roh, dict):
                e = roh.get("auf") or roh.get("teile")
                if roh.get("landet") is not None:
                    landet = _zahl(roh, "landet", 0.0, 0.0, 3600.0)
            else:
                e = roh
            e = str(e or "").strip().strip("/")
            if not e:
                raise AufbauFehler("Ein Schritt ist leer")
            treffer = [t for t in rest if _trifft(e, t)]
            if not treffer:
                schon = [t for t in teile if _trifft(e, t)]
                if schon:
                    raise AufbauFehler(f"Schritt {e!r}: alle Teile darunter kommen schon in früheren Schritten")
                raise AufbauFehler(f"Schritt {e!r}: kein gezeigtes Teil heißt so oder liegt darunter")
            out.append(Schritt(teile=treffer, titel=e, wunsch_landet=landet))
            rest = [t for t in rest if t not in treffer]
        if rest:
            out.append(Schritt(teile=rest, titel=_titel(rest)))
        return out
    # gemeinsamer Pfad aller Teile zählt nicht als Baugruppe (sonst käme alles unter „Drohne/…“ auf einmal)
    pfade = [t.split("/") for t in teile]
    tiefe = 0
    for stuecke in zip(*pfade):
        if len(set(stuecke)) != 1:
            break
        tiefe += 1
    tiefe = min(tiefe, min(len(p) for p in pfade) - 1)
    gruppen: list[tuple[str | None, list[str]]] = []
    for t, p in zip(teile, pfade):
        eltern = "/".join(p[: len(p) - 1]) if len(p) - 1 > tiefe else None
        if gruppen and eltern is not None and gruppen[-1][0] == eltern:
            gruppen[-1][1].append(t)
        else:
            gruppen.append((eltern, [t]))
    return [Schritt(teile=g, titel=e if e is not None else g[0]) for e, g in gruppen]


def _zusammenlegen(schritte: list[Schritt], hoechstens: int) -> list[Schritt]:
    if len(schritte) <= hoechstens:
        return schritte
    out: list[Schritt] = []
    for k in range(hoechstens):
        a, b = round(k * len(schritte) / hoechstens), round((k + 1) * len(schritte) / hoechstens)
        teil = schritte[a:b]
        teile = [t for s in teil for t in s.teile]
        out.append(Schritt(teile=teile, titel=teil[0].titel if len(teil) == 1 else _titel(teile)))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Kamera
# ---------------------------------------------------------------------------------------------------------------------


def _richtung_vektor(azimut: float, hoehe: float) -> np.ndarray:
    a, h = math.radians(azimut), math.radians(hoehe)
    return np.array([math.cos(h) * math.cos(a), math.cos(h) * math.sin(a), math.sin(h)])


def _abstand(ecken: np.ndarray, mitte: np.ndarray, u: np.ndarray, bildwinkel: float,
             seiten: float = SEITENVERHAELTNIS) -> float:
    """Abstand, aus dem alle Ecken des Hüllquaders ins Bild passen (Kamera auf mitte + d·u, Blick auf mitte)."""
    f = -u
    rechts = np.cross(f, [0.0, 0.0, 1.0])
    if np.linalg.norm(rechts) < 1e-6:
        rechts = np.cross(f, [0.0, 1.0, 0.0])
    rechts /= np.linalg.norm(rechts)
    oben = np.cross(rechts, f)
    tv = math.tan(math.radians(bildwinkel) / 2)
    th = tv * seiten
    v = ecken - mitte
    x, y, z = v @ rechts, v @ oben, v @ u
    return float(max(np.max(z + np.abs(x) / th), np.max(z + np.abs(y) / tv)))


def _fahrt(titel: str, art: str, zeiten: np.ndarray, mitte: np.ndarray, ecken: np.ndarray, bildwinkel: float, seiten: float,
           umdrehungen: float, hoehe: float, start: float, drift: float, rand: float) -> list[tuple[float, Any, Any]]:
    del titel
    if art == "orbit":
        dauer = float(zeiten[-1]) if len(zeiten) else 1.0
        azimute = start + 360.0 * umdrehungen * (zeiten / max(dauer, 1e-9))
        d = max(_abstand(ecken, mitte, _richtung_vektor(a, hoehe), bildwinkel, seiten) for a in np.arange(0, 360, 10))
        return [(float(t), tuple(mitte + rand * d * _richtung_vektor(float(a), hoehe)), tuple(mitte))
                for t, a in zip(zeiten, azimute)]
    az, h = RICHTUNGEN[art]
    dauer = float(zeiten[-1]) if len(zeiten) else 1.0
    if art == "oben":  # von oben nicht drehen: das Bild würde nur kreiseln
        azimute = np.full(len(zeiten), az)
    else:
        azimute = az - drift / 2 + drift * (zeiten / max(dauer, 1e-9))
    d = max(_abstand(ecken, mitte, _richtung_vektor(float(a), h), bildwinkel, seiten) for a in (azimute[0], azimute[-1]))
    return [(float(t), tuple(mitte + rand * d * _richtung_vektor(float(a), h)), tuple(mitte))
            for t, a in zip(zeiten, azimute)]


# ---------------------------------------------------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------------------------------------------------


def _zahl(wunsch: dict[str, Any], key: str, vorgabe: float, lo: float, hi: float) -> float:
    v = wunsch.get(key)
    if v is None:
        return vorgabe
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise AufbauFehler(f"{key} muss eine Zahl sein, nicht {v!r}") from None
    if not lo <= x <= hi:
        raise AufbauFehler(f"{key}={x:g} liegt außerhalb von {lo:g} bis {hi:g}")
    return x


def _punkte(roh: Any, wo: str) -> list[tuple[float, float, float]]:
    try:
        pts = [tuple(float(c) for c in p) for p in roh]
    except (TypeError, ValueError):
        raise AufbauFehler(f"{wo}: punkte muss eine Liste von Punkten [x, y, z] sein") from None
    if len(pts) < 2 or any(len(p) != 3 for p in pts):
        raise AufbauFehler(f"{wo}: mindestens zwei Punkte [x, y, z]")
    return pts  # type: ignore[return-value]


def _nachbilden(punkte: list[tuple[float, float, float]], stuecke: int) -> list[np.ndarray]:
    """Polylinie gleichmäßig nach Bogenlänge in ``stuecke`` Abschnitte (Punkte = stuecke + 1)."""
    p = np.asarray(punkte, dtype=float)
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] < 1e-6:
        raise AufbauFehler("Strich ohne Länge: alle Punkte liegen aufeinander")
    ziel = np.linspace(0.0, s[-1], stuecke + 1)
    return [np.array([np.interp(z, s, p[:, k]) for k in range(3)]) for z in ziel]


def plan(wunsch: dict[str, Any], teile: list[str], huellen: dict[str, tuple[list[float], list[float]]],
         ausgenommen: set[str] | None = None) -> Plan:
    """Zeitplan und Kamerafahrten für ``teile`` (Reihenfolge von show()). ``huellen``: Hüllquader je Teil (min, max) in
    mm, ``ausgenommen``: Kulisse und Striche, die von Anfang an stehen bzw. eigene Zeiten haben."""
    ausgenommen = set(ausgenommen or ())
    name = str(wunsch.get("name") or "Aufbau").strip() or "Aufbau"
    dauer = _zahl(wunsch, "dauer", 20.0, 3.0, 600.0)
    fps = _zahl(wunsch, "fps", 30.0, 10.0, 60.0)
    bildwinkel = _zahl(wunsch, "bildwinkel", 30.0, 10.0, 90.0)
    einflug = str(wunsch.get("einflug") or "oben")
    if einflug not in EINFLUG:
        raise AufbauFehler(f"einflug {einflug!r} gibt es nicht ({', '.join(EINFLUG)})")
    bau = [t for t in teile if t not in ausgenommen and not t.startswith(STRICH_PRAEFIX)]
    schritte = schritte_aufloesen(wunsch.get("schritte"), bau)
    if not any(t in huellen for t in bau):
        raise AufbauFehler("Keine Hüllquader zu den Teilen: das Modell erst mit run bauen")
    lo = np.min([huellen[t][0] for t in bau if t in huellen], axis=0).astype(float)
    hi = np.max([huellen[t][1] for t in bau if t in huellen], axis=0).astype(float)
    mitte = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo) / 2) or 1.0
    ecken = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])

    # Striche vor Schritten (welcher Schritt, steht erst nach dem Zusammenlegen fest)
    striche: list[Strich] = []
    for i, z in enumerate(wunsch.get("zeichnen") or []):
        if not isinstance(z, dict):
            raise AufbauFehler(f"zeichnen[{i}] muss ein Objekt mit vor und punkte sein")
        vor = str(z.get("vor") or "").strip().strip("/")
        if not vor or not any(_trifft(vor, t) or vor == s.titel for s in schritte for t in s.teile):
            raise AufbauFehler(f"zeichnen[{i}]: vor={vor!r} passt zu keinem Schritt")
        ds = _zahl(z, "dauer_s", 1.4, 0.3, 10.0)
        r = _zahl(z, "radius", max(0.8, radius * 0.006), 0.2, 20.0)
        von = _zahl(z, "von", 0.0, 0.0, 3600.0) if z.get("von") is not None else None
        striche.append(Strich(ziel=vor, punkte=_punkte(z.get("punkte"), f"zeichnen[{i}]"), dauer=ds, radius=r,
                              wunsch_von=von))

    start_s = _zahl(wunsch, "start_s", 0.4, 0.0, 30.0)
    halten_s = _zahl(wunsch, "halten_s", max(1.5, 0.12 * dauer), 0.0, 120.0)
    strichzeit = sum(s.dauer + STRICH_PAUSE_S for s in striche)
    fest = any(s.wunsch_landet is not None for s in schritte)
    e = 0.6
    for _ in range(0 if fest else 2):  # Einflug hängt vom Abstand der Schritte ab und umgekehrt
        frei = dauer - halten_s - e - start_s - strichzeit
        if frei < 0:
            raise AufbauFehler(f"dauer {dauer:g} s reicht nicht: Vorlauf {start_s:g} s, Halten {halten_s:g} s und "
                               f"Striche {strichzeit:.1f} s brauchen schon mehr. Länger machen oder halten_s kürzen.")
        if len(schritte) > 1 and frei / (len(schritte) - 1) < MIN_ABSTAND_S:
            schritte = _zusammenlegen(schritte, int(frei / MIN_ABSTAND_S) + 1)
        abstand = frei / (len(schritte) - 1) if len(schritte) > 1 else 0.0
        e = _zahl(wunsch, "einflug_s", min(0.75, max(0.3, 1.5 * abstand)), 0.0, 5.0) if einflug != "keiner" else 0.0
    for st in striche:
        st.vor = next(k for k, s in enumerate(schritte) if s.titel == st.ziel or any(_trifft(st.ziel, t) for t in s.teile))
    striche.sort(key=lambda s: s.vor)
    for a_, b_ in zip(striche, striche[1:]):
        if a_.vor == b_.vor:
            raise AufbauFehler(f"zeichnen: vor {b_.ziel!r} steht schon ein Strich (Schritt {schritte[a_.vor].titel!r})")
    nach_strich = {s.vor: s for s in striche}
    if fest:
        e = _zahl(wunsch, "einflug_s", 0.5, 0.0, 5.0) if einflug != "keiner" else 0.0
        _feste_zeiten(schritte, nach_strich, e, dauer)
    else:
        t = start_s
        for k, s in enumerate(schritte):
            st = nach_strich.get(k)
            if st is not None:
                st.von, st.bis = t, t + st.dauer
                t = st.bis + STRICH_PAUSE_S
            s.zeit, s.landet = t, t + e
            if st is not None:
                st.weg = min(dauer, s.landet + STRICH_NACHLAUF_S)
            t += abstand

    # Einflug: Abstand zur Ruhelage zu Beginn (das Teil landet in seiner Ruhelage)
    versatz: dict[str, tuple[float, float, float]] = {}
    if einflug != "keiner":
        kinder = {t for t in bau if any(m.startswith(t + "/") for m in bau)}  # Eltern bewegten ihre Kinder mit
        hub = 0.6 * radius
        for s in schritte:
            for teil in s.teile:
                if teil in kinder:
                    continue
                if einflug == "oben":
                    versatz[teil] = (0.0, 0.0, hub)
                else:
                    if teil in huellen:
                        c = (np.asarray(huellen[teil][0], float) + np.asarray(huellen[teil][1], float)) / 2
                    else:
                        c = mitte
                    r = c - mitte
                    n = np.linalg.norm(r)
                    r = r / n if n > 1e-6 else np.array([0.0, 0.0, 1.0])
                    versatz[teil] = tuple(float(v) for v in r * hub)  # type: ignore[assignment]

    # Kamerafahrten, eine je Blickwinkel
    winkel = [richtung(w) for w in (wunsch.get("blickwinkel") or ["orbit"])]
    if len(set(winkel)) != len(winkel):
        raise AufbauFehler("Ein Blickwinkel steht doppelt in der Liste")
    umdrehungen = _zahl(wunsch, "umdrehungen", 1.0, -10.0, 10.0)
    hoehe = _zahl(wunsch, "hoehe_grad", 24.0, -60.0, 89.0)
    start = _zahl(wunsch, "start_grad", -60.0, -360.0, 360.0)
    drift = _zahl(wunsch, "drift_grad", 16.0, 0.0, 90.0)
    rand = _zahl(wunsch, "rand", 1.1, 0.6, 3.0)
    wechsel_s = _zahl(wunsch, "wechsel_s", 3.0, 0.8, 60.0)
    # Schlüsselbilder dicht genug, dass der Orbit auf der Sehne nicht sichtbar näher kommt (höchstens 5° je Schritt)
    takt = max(1.0 / fps, min(KAMERA_TAKT_S, 5.0 / max(1e-6, abs(360.0 * umdrehungen / dauer))))
    zeiten = np.unique(np.concatenate([np.arange(0.0, dauer, takt), [dauer]]))
    seiten = _zahl(wunsch, "seitenverhaeltnis", SEITENVERHAELTNIS, 0.2, 5.0)
    args = dict(mitte=mitte, ecken=ecken, bildwinkel=bildwinkel, seiten=seiten, umdrehungen=umdrehungen, hoehe=hoehe,
                start=start,
                drift=drift, rand=rand)
    fahrten: list[Kamerafahrt] = []
    for w in winkel:
        if w != "schnitt":
            fahrten.append(Kamerafahrt(titel=_fahrt_titel(w), schluessel=_fahrt(w, w, zeiten, **args)))
    # Nahaufnahmen: Kamera auf eine Baugruppe gerichtet (etwa dorthin, wo gezeichnet wird), gleiche Zeiten
    titel_vergeben = {f.titel for f in fahrten}
    for i, d in enumerate(wunsch.get("details") or []):
        if not isinstance(d, dict):
            raise AufbauFehler(f"details[{i}] muss ein Objekt mit auf sein")
        auf = str(d.get("auf") or "").strip().strip("/")
        teile_d = [t for t in bau if auf and _trifft(auf, t) and t in huellen]
        if not teile_d:
            raise AufbauFehler(f"details[{i}]: auf={auf!r} passt zu keinem gezeigten Teil")
        w_d = richtung(d.get("richtung") or "iso")
        if w_d == "schnitt":
            raise AufbauFehler(f"details[{i}]: richtung schnitt geht nur für das ganze Modell")
        lo_d = np.min([huellen[t][0] for t in teile_d], axis=0).astype(float)
        hi_d = np.max([huellen[t][1] for t in teile_d], axis=0).astype(float)
        ecken_d = np.array([[x, y, z] for x in (lo_d[0], hi_d[0]) for y in (lo_d[1], hi_d[1])
                            for z in (lo_d[2], hi_d[2])])
        titel_d = str(d.get("titel") or f"Detail {auf.rsplit('/', 1)[-1].rstrip('*').strip()}").strip()
        if titel_d in titel_vergeben:
            raise AufbauFehler(f"details[{i}]: Titel {titel_d!r} gibt es schon")
        titel_vergeben.add(titel_d)
        args_d = {**args, "mitte": (lo_d + hi_d) / 2, "ecken": ecken_d, "rand": _zahl(d, "rand", 1.3, 0.6, 6.0)}
        fahrten.append(Kamerafahrt(titel=titel_d, schluessel=_fahrt(w_d, w_d, zeiten, **args_d)))
    if "schnitt" in winkel:
        folge = [w for w in winkel if w != "schnitt"] or ["iso", "orbit", "vorne", "iso_hinten_links"]
        if len(folge) == 1:
            folge = [folge[0], "orbit" if folge[0] != "orbit" else "iso"]
        fahrten.append(_schnittfahrt(folge, zeiten, dauer, fps, wechsel_s, [s.zeit for s in schritte], args))
    return Plan(name=name, dauer=dauer, fps=fps, bildwinkel=bildwinkel, einflug=einflug, einflug_s=e,
                schritte=schritte, striche=striche, fahrten=fahrten, mitte=tuple(float(v) for v in mitte),  # type: ignore[arg-type]
                radius=radius, versatz=versatz)


def _feste_zeiten(schritte: list[Schritt], nach_strich: dict[int, Strich], e: float, dauer: float) -> None:
    """Schritte mit ``landet`` aus dem Wunsch landen genau dann (etwa auf einem Schlag der Musik); Schritte ohne Zeit
    liegen gleichmäßig zwischen ihren Nachbarn, am Rand im Abstand der nächsten festen Schritte. Striche enden vor ihrem
    Teil, ohne ``von`` gerade rechtzeitig."""
    fix = [(k, s.wunsch_landet) for k, s in enumerate(schritte) if s.wunsch_landet is not None]
    for (k0, t0), (k1, t1) in zip(fix, fix[1:]):
        if t1 <= t0:
            raise AufbauFehler(f"landet {t1:g} s für {schritte[k1].titel!r} liegt nicht nach {t0:g} s")
    luecke = (fix[-1][1] - fix[0][1]) / (fix[-1][0] - fix[0][0]) if len(fix) > 1 else 1.0
    for k, s in enumerate(schritte):
        if s.wunsch_landet is not None:
            s.landet = s.wunsch_landet
            continue
        vor = [f for f in fix if f[0] < k]
        nach = [f for f in fix if f[0] > k]
        if vor and nach:
            (ka, ta), (kb, tb) = vor[-1], nach[0]
            s.landet = ta + (tb - ta) * (k - ka) / (kb - ka)
        elif vor:
            s.landet = vor[-1][1] + luecke * (k - vor[-1][0])
        else:
            s.landet = nach[0][1] - luecke * (nach[0][0] - k)
    for k, s in enumerate(schritte):
        s.zeit = s.landet - e
        if s.zeit < -1e-9 or s.landet > dauer + 1e-9:
            raise AufbauFehler(f"Schritt {s.titel!r} landet bei {s.landet:.2f} s, außerhalb von {e:g} bis {dauer:g} s")
        if k and s.landet <= schritte[k - 1].landet:
            raise AufbauFehler(f"Schritt {s.titel!r} landet nicht nach {schritte[k - 1].titel!r}")
        st = nach_strich.get(k)
        if st is not None:
            st.von = st.wunsch_von if st.wunsch_von is not None else s.zeit - STRICH_PAUSE_S - st.dauer
            st.bis = st.von + st.dauer
            if st.von < -1e-9 or st.bis > s.zeit + 1e-9:
                raise AufbauFehler(f"Strich vor {s.titel!r} ({st.von:.2f} bis {st.bis:.2f} s) passt nicht vor das "
                                   f"Erscheinen bei {s.zeit:.2f} s")
            st.weg = min(dauer, s.landet + STRICH_NACHLAUF_S)


def _fahrt_titel(w: str) -> str:
    return {"orbit": "Orbit", "schnitt": "Schnitt", "iso": "Iso", "vorne": "Vorne", "hinten": "Hinten", "rechts": "Rechts",
            "links": "Links", "oben": "Oben", "iso_vorne_links": "Iso vorne links", "iso_hinten_rechts": "Iso hinten rechts",
            "iso_hinten_links": "Iso hinten links"}[w]


def _schnittfahrt(folge: list[str], zeiten: np.ndarray, dauer: float, fps: float, wechsel_s: float,
                  schrittzeiten: list[float], args: dict[str, Any]) -> Kamerafahrt:
    """Ein Video mit harten Schnitten zwischen den Blickwinkeln; ein Schnitt rückt auf das nächste Teil, das erscheint
    (bis 0,6 s), dann hat er einen Grund im Bild."""
    schnitte: list[float] = []
    t = wechsel_s
    while t < dauer - 1.0:
        nah = [s for s in schrittzeiten if abs(s - t) <= 0.6 and (not schnitte or s > schnitte[-1] + 0.8)]
        c = min(nah, key=lambda s: abs(s - t)) if nah else t
        c = round(c * fps) / fps  # auf ein Bild
        if c > 0 and (not schnitte or c > schnitte[-1] + 0.5):
            schnitte.append(c)
        t = c + wechsel_s
    grenzen = [0.0, *schnitte, dauer]
    fahrten = {w: dict((k[0], k) for k in _fahrt(w, w, zeiten, **args)) for w in set(folge)}
    schluessel: list[tuple[float, Any, Any]] = []
    halb = 0.5 / fps
    for k, (a, b) in enumerate(zip(grenzen, grenzen[1:])):
        w = folge[k % len(folge)]
        z = [float(x) for x in zeiten if a <= x < b] or [a]
        if z[0] > a:
            z.insert(0, a)
        ende = b - halb if k < len(grenzen) - 2 else b
        if z[-1] < ende - 1e-9:
            z.append(ende)
        for x in z:
            schluessel.append(_an(fahrten[w], x))
    return Kamerafahrt(titel="Schnitt", schluessel=schluessel, schnitte=schnitte)


def _an(fahrt: dict[float, tuple[float, Any, Any]], t: float) -> tuple[float, Any, Any]:
    """Kamera einer Fahrt zur Zeit ``t`` (zwischen zwei Schlüsselbildern linear)."""
    zs = sorted(fahrt)
    if t <= zs[0]:
        return (t, fahrt[zs[0]][1], fahrt[zs[0]][2])
    for a, b in zip(zs, zs[1:]):
        if a <= t <= b:
            u = (t - a) / (b - a) if b > a else 0.0
            la, lb = np.asarray(fahrt[a][1]), np.asarray(fahrt[b][1])
            return (t, tuple(float(v) for v in la + (lb - la) * u), fahrt[a][2])
    return (t, fahrt[zs[-1]][1], fahrt[zs[-1]][2])


# ---------------------------------------------------------------------------------------------------------------------
# Im Rechenprozess
# ---------------------------------------------------------------------------------------------------------------------


def anheben(p: np.ndarray, kaesten: list[tuple[np.ndarray, np.ndarray]], abstand: float) -> np.ndarray:
    """Punkt eines Strichs aus allen Hüllquadern herausschieben, die eine Kugel mit ``abstand`` um ihn berührt, jeweils
    durch die nächste Fläche (auf einer Platte gezeichnet: nach oben). Sonst meldet die Prüfung eine Durchdringung mit
    der Fläche, auf der Kevin gezeichnet hat."""
    q = np.asarray(p, float).copy()
    for _ in range(4):
        bewegt = False
        for lo, hi in kaesten:
            if np.linalg.norm(q - np.clip(q, lo, hi)) >= abstand:
                continue
            wege = [(q[k] - (lo[k] - abstand), k, lo[k] - abstand) for k in range(3)]
            wege += [((hi[k] + abstand) - q[k], k, hi[k] + abstand) for k in range(3)]
            _, k, ziel = min(wege)
            q[k] = ziel
            bewegt = True
        if not bewegt:
            break
    return q


def _strich_formen(st: Strich, kaesten: list[tuple[np.ndarray, np.ndarray]]) -> list[Any]:
    """Röhre aus Zylinderstücken mit Kugeln an den Knicken, knapp über den Flächen (``anheben``)."""
    from build123d import Plane, Pos, Solid, Vector

    pts = [np.asarray(p, float) for p in st.punkte]
    laenge = sum(float(np.linalg.norm(b - a)) for a, b in zip(pts, pts[1:]))
    stuecke = max(2, min(MAX_STRICH_STUECKE, int(laenge / max(st.radius * 4, 1e-6))))
    pts = _nachbilden(st.punkte, stuecke)
    gehoben = [anheben(p, kaesten, st.radius + 0.8) for p in pts]
    formen = []
    for i, (a, b) in enumerate(zip(gehoben, gehoben[1:])):
        d = b - a
        lang = float(np.linalg.norm(d))
        if lang < 1e-6:
            continue
        zyl = Solid.make_cylinder(st.radius, lang, Plane(origin=Vector(*a), z_dir=Vector(*d)))
        form = zyl.fuse(Pos(*a) * Solid.make_sphere(st.radius))
        if i == len(gehoben) - 2:
            form = form.fuse(Pos(*b) * Solid.make_sphere(st.radius))
        formen.append(form)
    return formen


def erzeugen(wunsch: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Im Rechenprozess nach model.py: Striche zeigen, je Blickwinkel eine Animation anlegen. Gibt den Zeitplan zurück
    (geht mit RUN_DONE an den Kernel)."""
    from kevcad import show
    from kevcad.bewegung import animation
    from kevcad.pruefung import erlaubt_ueberlappung

    kulisse = set(state.get("kulisse") or ())
    gezeigt = list(state["shown"])
    huellen = dict(state.get("bboxes", {}))
    p = plan(wunsch, gezeigt, huellen, ausgenommen=kulisse)
    for k, st in enumerate(p.striche, start=1):
        ziel = set(p.schritte[st.vor].teile)  # dort entsteht das Teil: der Strich darf es berühren
        kaesten = [(np.asarray(lo, float), np.asarray(hi, float)) for n, (lo, hi) in huellen.items()
                   if n not in ziel and not n.startswith(STRICH_PRAEFIX)]
        for i, form in enumerate(_strich_formen(st, kaesten), start=1):
            n = f"{STRICH_PRAEFIX}Strich {k}/{i:02d}"
            show(form, n, color=STRICH_FARBE, kulisse=True)
            st.namen.append(n)
        erlaubt_ueberlappung(st.namen, sorted(ziel), grund="Strich im Aufbau-Video zeigt, wo das Teil hinkommt")
        erlaubt_ueberlappung(st.namen, st.namen, grund="Stücke eines Strichs greifen an den Knicken ineinander")
    vorhanden = {a.name for a in state.get("animations", [])}
    for f in p.fahrten:
        name = animationsname(p.name, f.titel)
        if name in vorhanden:
            raise AufbauFehler(f"Animation {name!r} gibt es schon in model.py; einen anderen name wählen")
        a = animation(dauer=p.dauer, fps=p.fps, name=name)
        for s in p.schritte:
            for teil in s.teile:
                a.sichtbar(teil, an=False, zeit=0)
                a.sichtbar(teil, an=True, zeit=s.zeit)
                v = p.versatz.get(teil)
                if v is not None and p.einflug_s > 0:
                    a.bewege(teil, nach=v, von=0, bis=0)
                    a.bewege(teil, nach=tuple(-x for x in v), von=s.zeit, bis=min(p.dauer, s.landet), kurve="aus")
        for st in p.striche:
            n_st = len(st.namen)
            for i, n in enumerate(st.namen):
                a.sichtbar(n, an=False, zeit=0)
                a.sichtbar(n, an=True, zeit=st.von + st.dauer * i / max(1, n_st))
                a.sichtbar(n, an=False, zeit=st.weg)
        for t, lage, ziel in f.schluessel:
            a.ansicht(min(p.dauer, max(0.0, t)), lage=lage, ziel=ziel, bildwinkel=p.bildwinkel, kurve="linear")
    return p.zeitplan()
