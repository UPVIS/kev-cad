"""Ablauf (S2) im eigenen Prozess: Antrieb, Simulation mit MuJoCo, Aufzeichnung, Varianten über ``mujoco.rollout``.

**Antrieb.** Der geschobene Körper folgt längs einer Sollbahn (Geschwindigkeitsprofil): er fährt von Anfang an mit
``geschwindigkeit`` (alles rollt mit, Räder und Ball drehen passend), nach ``vorlauf`` bremst er mit ``bremsen`` (m/s²;
``"abrupt"`` = Stillstand in 0,1 s, ``"anprall"`` = in 0,02 s) bis zum Stillstand und steht dann. Alternativ die
Sollbahn aus einer Animation (Verschiebung des Teils über der Zeit). Quer, senkrecht und in der Drehung ist er frei: er
kann kippen, abheben und ausweichen. Die Führungskraft greift am Angriffspunkt an (Vorgabe Boden: ungünstigster Fall
fürs Kippen nach vorn, wie blockierte Räder).

**Auswertung** (aus den Lagen je Zeitschritt, auch in Rollouts ohne Kontaktdaten):

- Kippwinkel (Nicken des geschobenen Körpers, + = nach vorn), Abheben der Fußpunkte (Radachsen, tiefste Punkte),
- Versatz und Anheben jeder Ladung (freie Körper wie der Ball) gegenüber dem geschobenen Körper,
- Kontaktkräfte je Körperpaar und als Pfeile je Bild (nur im aufgezeichneten Ablauf),
- Führungskraft und Normalkraft am Boden (Rutschen über blockierte Räder).

Varianten (Suche nach Grenzen) rechnet ``mujoco.rollout`` mit höchstens 4 Fäden.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.statik.dynamik import mjcf

ABRUPT_S = 0.1
ANPRALL_S = 0.02
VORLAUF_S = 0.3
NACHLAUF_S = 1.2
ABHEBEN_MM = 2.0  # Fußpunkt höher als das: abgehoben (darunter federn nur die Kontakte)
LADUNG_ANHEBEN_MM = 3.0
FADEN_MAX = 4


# ---------------------------------------------------------------------------------------------------------------------
# Sollbahn


@dataclass
class Profil:
    """Sollbahn längs der Antriebsrichtung: Zeiten (s), Weg (m), Geschwindigkeit (m/s); ``v0`` Anfangsgeschwindigkeit,
    ``a_brems`` größte Verzögerung (m/s²), ``t_brems`` Beginn des Bremsens."""

    t: np.ndarray
    x: np.ndarray
    v: np.ndarray
    v0: float
    a_brems: float = 0.0
    t_brems: float | None = None
    t_steht: float | None = None
    text: str = ""

    @property
    def dauer(self) -> float:
        return float(self.t[-1])


def bremszeit(bremsen: Any, v: float) -> tuple[float, str]:
    """(Verzögerung m/s², Text) für ``bremsen`` = Zahl (m/s²), "abrupt" (Stillstand in 0,1 s) oder "anprall"."""
    if bremsen is None or bremsen is False:
        return 0.0, "ohne Bremsen"
    if isinstance(bremsen, str):
        b = bremsen.strip().lower()
        if b in ("abrupt", "voll", "vollbremsung", "hart"):
            return v / ABRUPT_S if v > 0 else 0.0, f"abrupt (Stillstand in {ABRUPT_S:g} s)".replace(".", ",")
        if b in ("anprall", "stoss", "stoß", "hindernis"):
            return v / ANPRALL_S if v > 0 else 0.0, f"Anprall (Stillstand in {ANPRALL_S:g} s)".replace(".", ",")
        try:
            bremsen = float(b.replace(",", "."))
        except ValueError:
            raise ValueError(f"bremsen {bremsen!r} unbekannt: Zahl in m/s², \"abrupt\" oder \"anprall\"") from None
    a = abs(float(bremsen))
    return a, f"mit {a:.3g} m/s²".replace(".", ",")


def profil(v: float, a_brems: float, dauer: float | None = None, vorlauf: float = VORLAUF_S,
           dt: float = mjcf.ZEITSCHRITT, text: str = "") -> Profil:
    """Sollbahn: konstant ``v`` bis ``vorlauf``, dann Verzögerung ``a_brems`` bis zum Stillstand (oder weiter mit v)."""
    t_stop = vorlauf + (v / a_brems if a_brems > 0 else math.inf)
    if dauer is None:
        dauer = (t_stop + NACHLAUF_S) if math.isfinite(t_stop) else vorlauf + 2.0
    n = int(round(dauer / dt)) + 1
    t = np.arange(n) * dt
    vv = np.where(t < vorlauf, v, np.maximum(0.0, v - a_brems * (t - vorlauf))) if a_brems > 0 else np.full(n, v)
    x = np.concatenate([[0.0], np.cumsum((vv[1:] + vv[:-1]) / 2 * dt)])
    return Profil(t, x, vv, float(v), float(a_brems), vorlauf if a_brems > 0 else None,
                  t_stop if math.isfinite(t_stop) else None, text)


def profil_aus_bahn(zeiten: np.ndarray, weg_m: np.ndarray, dt: float = mjcf.ZEITSCHRITT, nachlauf: float = 0.5,
                    text: str = "") -> Profil:
    """Sollbahn aus einer Animation (Weg längs der Antriebsrichtung je Bild, m)."""
    from scipy.interpolate import CubicSpline

    zeiten = np.asarray(zeiten, float)
    weg_m = np.asarray(weg_m, float)
    T = float(zeiten[-1]) + nachlauf
    n = int(round(T / dt)) + 1
    t = np.arange(n) * dt
    # Spline durch die Bilder (gleiche Zeiten zusammengefasst): glatte Geschwindigkeit und Beschleunigung
    zt, idx = np.unique(zeiten, return_index=True)
    sp = CubicSpline(zt, weg_m[idx], bc_type="clamped" if abs(weg_m[1] - weg_m[0]) < 1e-9 else "not-a-knot")
    innen = t <= zt[-1]
    x = np.where(innen, sp(np.minimum(t, zt[-1])), weg_m[-1])
    v = np.where(innen, sp(np.minimum(t, zt[-1]), 1), 0.0)
    a = np.where(innen, sp(np.minimum(t, zt[-1]), 2), 0.0)
    return Profil(t, x, v, float(v[0]), float(max(0.0, -a.min())), None, None, text)


# ---------------------------------------------------------------------------------------------------------------------
# Modell und Zustand


@dataclass
class Modell:
    meta: dict[str, Any]
    xml: str
    zuordnung: dict[str, Any]
    model: Any
    richtung: np.ndarray
    angriff: np.ndarray  # mm
    ohne: set[str] = field(default_factory=set)
    fuss: list[dict[str, Any]] = field(default_factory=list)  # Fußpunkte des geschobenen Teilbaums
    ladung: list[str] = field(default_factory=list)  # freie Körper (Wurzeln) außer dem Antrieb
    bauzeit_ms: float = 0.0

    @property
    def K(self) -> dict[str, Any]:
        return {k["id"]: k for k in self.meta["koerper"]}


def teilbaum(meta: dict[str, Any], wurzel: str) -> set[str]:
    K = {k["id"]: k for k in meta["koerper"]}
    out = {wurzel}
    geaendert = True
    while geaendert:
        geaendert = False
        for k in K.values():
            if k["eltern"] in out and k["id"] not in out:
                out.add(k["id"])
                geaendert = True
    return out


def baue_modell(meta: dict[str, Any], formen: dict[str, list[dict[str, Any]]], *, richtung: Any = (1, 0, 0),
                angriff: Any = "boden", neigung: float = 0.0, neigung_richtung: Any = (1, 0, 0),
                ohne_ladung: bool = False) -> Modell:
    import mujoco

    t0 = time.perf_counter()
    K = {k["id"]: k for k in meta["koerper"]}
    an = meta.get("antrieb")
    d = np.asarray(richtung, float)
    d[2] = 0
    d /= np.linalg.norm(d) or 1.0
    ladung = [k["id"] for k in meta["koerper"] if k["eltern"] is None and k["art"] == "frei" and k["id"] != an]
    ohne: set[str] = set()
    if ohne_ladung:
        for x in ladung:
            ohne |= teilbaum(meta, x)
    # Angriffspunkt: Boden unter dem Schwerpunkt des geschobenen Teilbaums, eine Höhe (mm über dem Boden) oder Punkt
    if an is not None:
        tb = teilbaum(meta, an)
        mt = sum(K[x]["masse"] for x in tb)
        c = sum(K[x]["masse"] * np.asarray(K[x]["schwerpunkt"], float) for x in tb) / max(mt, 1e-9)
    else:
        tb, c = set(), np.zeros(3)
    if isinstance(angriff, str) or angriff is None:
        art = (angriff or "boden").lower()
        if art == "schwerpunkt":
            P = c.copy()
        else:
            P = np.array([c[0], c[1], float(meta["boden_z"])])
    elif np.ndim(angriff) == 0:
        P = np.array([c[0], c[1], float(meta["boden_z"]) + float(angriff)])
    else:
        P = np.asarray(angriff, float)
    xml, zu = mjcf.baue_xml(meta, formen, angriff=P, richtung=d,
                            schwerkraft_v=mjcf.schwerkraft(neigung, neigung_richtung), ohne=ohne)
    model = mujoco.MjModel.from_xml_string(xml)
    m = Modell(meta, xml, zu, model, d, P, ohne, ladung=[x for x in ladung if x not in ohne])
    m.fuss = fusspunkte(meta, tb, formen, an)
    m.bauzeit_ms = (time.perf_counter() - t0) * 1000
    return m


def fusspunkte(meta: dict[str, Any], tb: set[str], formen: dict[str, list[dict[str, Any]]] | None = None,
               an: str | None = None) -> list[dict[str, Any]]:
    """Punkte, auf denen der geschobene Teilbaum steht (Weltkoordinaten der Ruhelage, mm): Radachsen (drehende Kinder)
    und je Teil am Boden die Ecken der Aufstandsfläche seiner Kollisionsform (Füße, Kufen), nur am geschobenen
    Körper selbst."""
    K = {k["id"]: k for k in meta["koerper"]}
    out = []
    for kid in sorted(tb):
        k = K[kid]
        if not k["boden"]:
            continue
        if k["art"] == "dreh" and k.get("gelenk"):
            p = np.asarray(k["gelenk"]["punkt"], float)
            # Achse bis zur Mitte des Rads (Punkt auf der Achse nahe dem Schwerpunkt)
            dd = np.asarray(k["gelenk"]["achse"], float)
            c = np.asarray(k["schwerpunkt"], float)
            p = p + dd * float((c - p) @ dd)
            out.append({"koerper": kid, "punkt": p, "art": "achse", "name": k["name"],
                        "boden": p - np.array([0.0, 0.0, float(p[2] - meta["boden_z"])])})
        elif kid == an:
            for n in k["boden"]:
                pts = []
                for f in (formen or {}).get(n, []):
                    if f["typ"] in ("kugel", "zylinder"):
                        pts.append(np.asarray(f["mitte"], float) - np.array([0, 0, f["r"]]))
                    else:
                        pts.extend(np.asarray(f["punkte"], float))
                if not pts:
                    continue
                P = np.asarray(pts)
                unten = P[P[:, 2] <= P[:, 2].min() + 0.5]
                # Ecken der Aufstandsfläche (2D-Hülle), höchstens 8
                if len(unten) > 3:
                    from scipy.spatial import ConvexHull, QhullError

                    try:
                        unten = unten[ConvexHull(unten[:, :2]).vertices]
                    except (QhullError, ValueError):
                        pass
                if len(unten) > 8:
                    from kevcad_kernel.statik.dynamik.formen import fps

                    unten = fps(unten, 8)
                for q in unten:
                    out.append({"koerper": kid, "teil": n, "punkt": q, "art": "tief", "name": n, "boden": q})
    return out


def _quat_mat(q: np.ndarray) -> np.ndarray:
    """Quaternion(en) (…, 4) w x y z → Drehmatrizen (…, 3, 3)."""
    q = np.asarray(q, float)
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], -2)


def anfangszustand(mo: Modell, v0: float) -> tuple[Any, np.ndarray]:
    """MjData in Ruhelage mit Geschwindigkeit ``v0`` längs der Antriebsrichtung für alles, was auf dem Boden steht
    oder mitfährt; Räder und rollende Kugeln drehen passend. Liefert (data, Zustand für rollout)."""
    import mujoco

    model = mo.model
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    d = mo.richtung
    K = mo.K
    vv = v0 * d
    for kid in mo.zuordnung["koerper"]:
        k = K[kid]
        if kid == mo.zuordnung["antrieb"]:
            j = model.joint("an_l")
            data.qvel[j.dofadr[0]] = v0
        elif k["eltern"] is None and k["art"] == "frei":
            j = model.joint(f"f_{kid}")
            a = j.dofadr[0]
            data.qvel[a:a + 3] = vv
            kug = _kugel_am_boden(mo, kid)
            if kug is not None:  # rollt: ω = (z × v) / r, im Körpersystem (= Welt in Ruhelage)
                data.qvel[a + 3:a + 6] = np.cross([0, 0, 1.0], vv) / (kug * mjcf.MM)
        elif k["art"] == "dreh" and k.get("gelenk") and k["gelenk"].get("rad") and k["boden"]:
            j = model.joint(f"j_{kid}")
            r = _radius_rad(mo, kid)
            if r:
                w = np.cross([0, 0, 1.0], vv) / (r * mjcf.MM)
                data.qvel[j.dofadr[0]] = float(w @ np.asarray(k["gelenk"]["achse"], float))
    mujoco.mj_forward(model, data)
    spec = mujoco.mjtState.mjSTATE_FULLPHYSICS
    state = np.empty(mujoco.mj_stateSize(model, spec))
    mujoco.mj_getState(model, data, state, spec)
    return data, state


def _kugel_am_boden(mo: Modell, kid: str) -> float | None:
    k = mo.K[kid]
    for n in k["teile"]:
        c = mo.meta["kollision"].get(n)
        if c and c["art"] == "kugel" and c["mitte"][2] - c["radius"] <= mo.meta["boden_z"] + 1.0:
            return float(c["radius"])
    return None


def _radius_rad(mo: Modell, kid: str) -> float | None:
    k = mo.K[kid]
    gj = k["gelenk"]
    p = np.asarray(gj["punkt"], float)
    r = 0.0
    for n in k["teile"]:
        c = mo.meta["kollision"].get(n)
        if c is None:
            continue
        if c.get("zylinder"):
            r = max(r, float(c["zylinder"][1]))
        elif c["art"] == "drehteil":
            r = max(r, float(max(c["profil"][1])))
    if r <= 0:  # Achshöhe über dem Boden
        r = float(p[2] - mo.meta["boden_z"])
    return r or None


def steuerung(mo: Modell, pr: Profil) -> np.ndarray:
    """Steuerwerte je Zeitschritt (nstep × nu): Sollweg, Sollgeschwindigkeit und Vorsteuerkraft m · a des Antriebs."""
    if mo.model.nu == 0:
        return np.zeros((len(pr.t) - 1, 0))
    dt = float(pr.t[1] - pr.t[0]) if len(pr.t) > 1 else mjcf.ZEITSCHRITT
    a = np.gradient(pr.v, dt)
    f = float(mo.zuordnung.get("masse_antrieb") or 0.0) * a
    return np.stack([pr.x[1:], pr.v[1:], f[1:]], axis=1)


# ---------------------------------------------------------------------------------------------------------------------
# Auswertung aus den Gelenkwerten


@dataclass
class Bewertung:
    """Kennwerte eines Ablaufs (aus den Gelenkwerten, mm und Grad)."""

    kipp_max: float = 0.0  # größter Nickwinkel nach vorn (Grad)
    kipp_min: float = 0.0  # nach hinten
    roll_max: float = 0.0  # seitlich
    abheben_max: float = 0.0  # mm
    abheben_wo: str | None = None
    abheben_t: float | None = None
    ladung: dict[str, dict[str, float]] = field(default_factory=dict)  # Körper → versatz, hebt, ende, t
    weg: float = 0.0  # m
    v_end: float = 0.0


class Auswerter:
    """Rechnet aus qpos-Folgen (Schritte × nq) die Kennwerte ``Bewertung`` und die Zeitreihen."""

    def __init__(self, mo: Modell) -> None:
        self.mo = mo
        m = mo.model
        K = mo.K
        an = mo.zuordnung["antrieb"]
        self.an = an
        if an is not None:
            self.adr_l = m.jnt_qposadr[m.joint("an_l").id]
            self.adr_q = m.jnt_qposadr[m.joint("an_q").id]
            self.adr_z = m.jnt_qposadr[m.joint("an_z").id]
            self.adr_r = m.jnt_qposadr[m.joint("an_r").id]
        self.d = mo.richtung
        self.q = np.cross([0, 0, 1.0], self.d)
        self.P = mo.angriff * mjcf.MM
        self.c_an = np.asarray(K[an]["schwerpunkt"], float) * mjcf.MM if an else np.zeros(3)
        # Fußpunkte als Punkte im System der Ruhelage (m)
        self.fuss = [(f["name"], np.asarray(f["punkt"], float) * mjcf.MM) for f in mo.fuss]
        self.ladung = []
        for kid in mo.ladung:
            j = m.joint(f"f_{kid}")
            self.ladung.append((kid, m.jnt_qposadr[j.id], np.asarray(K[kid]["schwerpunkt"], float) * mjcf.MM,
                                float(np.max(np.asarray(K[kid]["bmax"]) - np.asarray(K[kid]["bmin"])))))

    def lage_antrieb(self, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(s (N, 3) Verschiebung, R (N, 3, 3) Drehung um P) des Antriebs je Zeile von Q."""
        s = (Q[:, self.adr_l, None] * self.d + Q[:, self.adr_q, None] * self.q
             + Q[:, self.adr_z, None] * np.array([0, 0, 1.0]))
        R = _quat_mat(Q[:, self.adr_r:self.adr_r + 4])
        return s, R

    def reihen(self, Q: np.ndarray) -> dict[str, np.ndarray]:
        """Zeitreihen: kipp (Grad, + = nach vorn), roll (Grad), abheben (mm), je Ladung versatz und hebt (mm)."""
        out: dict[str, np.ndarray] = {}
        if self.an is None:
            return out
        s, R = self.lage_antrieb(Q)
        oben = R[:, :, 2]
        out["kipp"] = np.degrees(np.arctan2(oben @ self.d, oben[:, 2]))
        out["roll"] = np.degrees(np.arctan2(oben @ self.q, oben[:, 2]))
        hebt = np.zeros(len(Q))
        wo = np.full(len(Q), -1)
        for i, (_, p) in enumerate(self.fuss):
            w = s + self.P + np.einsum("nij,j->ni", R, p - self.P)
            dz = (w[:, 2] - p[2]) / mjcf.MM
            besser = dz > hebt
            hebt = np.where(besser, dz, hebt)
            wo = np.where(besser, i, wo)
        out["abheben"] = hebt
        out["abheben_wo"] = wo
        out["weg"] = Q[:, self.adr_l]
        for kid, adr, c0, _ in self.ladung:
            c = Q[:, adr:adr + 3]
            rel = np.einsum("nji,nj->ni", R, c - s - self.P) + self.P - c0
            out[f"versatz:{kid}"] = np.linalg.norm(rel[:, :2], axis=1) / mjcf.MM
            out[f"laengs:{kid}"] = (rel @ self.d) / mjcf.MM
            out[f"hebt:{kid}"] = (c[:, 2] - c0[2]) / mjcf.MM
        return out

    def bewerte(self, Q: np.ndarray, t: np.ndarray) -> Bewertung:
        r = self.reihen(Q)
        b = Bewertung()
        if not r:
            return b
        b.kipp_max = float(max(0.0, r["kipp"].max()))
        b.kipp_min = float(min(0.0, r["kipp"].min()))
        b.roll_max = float(np.abs(r["roll"]).max())
        i = int(np.argmax(r["abheben"]))
        b.abheben_max = float(max(0.0, r["abheben"][i]))
        if r["abheben_wo"][i] >= 0 and b.abheben_max > 0:
            b.abheben_wo = self.fuss[int(r["abheben_wo"][i])][0]
            b.abheben_t = float(t[i])
        b.weg = float(r["weg"][-1])
        for kid, _, _, groesse in self.ladung:
            vs = r[f"versatz:{kid}"]
            hb = r[f"hebt:{kid}"]
            j = int(np.argmax(vs))
            b.ladung[kid] = {"versatz": float(vs[j]), "versatz_t": float(t[j]), "hebt": float(max(0.0, hb.max())),
                             "hebt_t": float(t[int(np.argmax(hb))]), "ende": float(vs[-1]),
                             "laengs_max": float(r[f"laengs:{kid}"].max()), "groesse": groesse}
        return b


def ladung_verloren(b: Bewertung, kid: str) -> bool:
    """Hat die Ladung ihren Platz verlassen? Versatz über die halbe Größe (Ball: über den Radius) oder am Ende mehr als
    ein Fünftel ihrer Größe weg."""
    L = b.ladung.get(kid)
    if not L:
        return False
    return L["versatz"] > 0.5 * L["groesse"] or L["ende"] > 0.2 * L["groesse"]


# ---------------------------------------------------------------------------------------------------------------------
# Rechnen


@dataclass
class Aufzeichnung:
    zeiten: np.ndarray  # Bilder (s)
    lagen: np.ndarray  # (Bilder, Körper, 4, 4) Welt = Lage · Ruhelage (mm)
    koerper: list[str]
    reihen: dict[str, np.ndarray]  # je Bild
    kontakte: list[list[dict[str, Any]]]  # je Bild: Pfeile {"punkt", "kraft", "paar"}
    paar_kraft: dict[str, np.ndarray]  # "K1|K2" → Betrag je Bild (N)
    fuehrung: np.ndarray  # Führungskraft längs (N) je Bild
    boden_normal: np.ndarray  # Normalkraft des Bodens auf den geschobenen Teilbaum (N) je Bild
    bewertung: Bewertung
    ms: float
    schritte: int


def bild_fps(fps: float, dt: float = mjcf.ZEITSCHRITT) -> tuple[int, float]:
    """(Schritte je Bild, tatsächliche Bildrate): Bilder liegen genau auf Vielfachen des Zeitschritts, damit Bild k
    bei k / fps liegt (wie ANIM_DEF verlangt)."""
    k = max(1, int(round(1.0 / (fps * dt))))
    return k, 1.0 / (k * dt)


def rechne(mo: Modell, pr: Profil, fps: float = 50.0, pfeile_je_bild: int = 12) -> Aufzeichnung:
    """Ein Ablauf mit Aufzeichnung (Lagen, Kontaktkräfte) in ``fps`` Bildern je Sekunde (auf den Zeitschritt
    gerundet); die Dauer wird auf ein ganzes Bild verlängert."""
    import mujoco

    t0 = time.perf_counter()
    model = mo.model
    data, _ = anfangszustand(mo, pr.v0)
    ctrl = steuerung(mo, pr)
    schritt_bild, _ = bild_fps(fps, model.opt.timestep)
    n = len(pr.t) - 1
    n_voll = int(math.ceil(n / schritt_bild)) * schritt_bild
    if n_voll > n and len(ctrl):
        ctrl = np.vstack([ctrl, np.repeat(ctrl[-1:], n_voll - n, axis=0)])
        if model.nu >= 3:
            ctrl[n:, 2] = 0.0
    n = n_voll
    ids = [model.body(k).id for k in mo.zuordnung["koerper"]]
    body_kid = {model.body(k).id: k for k in mo.zuordnung["koerper"]}
    an = mo.zuordnung["antrieb"]
    tb = teilbaum(mo.meta, an) if an else set()
    geom_body = model.geom_bodyid
    boden_geom = model.geom("boden").id
    x0 = data.xpos[ids].copy()
    R0 = data.xmat[ids].reshape(-1, 3, 3).copy()
    Q, T, lagen, kontakte = [], [], [], []
    paar: dict[str, list[float]] = {}
    fuehr, bodn = [], []
    f6 = np.zeros(6)
    nq = model.nq
    bild = 0

    def aufnehmen() -> None:
        nonlocal bild
        T.append(float(data.time))
        Q.append(data.qpos[:nq].copy())
        L = np.zeros((len(ids), 4, 4))
        R = data.xmat[ids].reshape(-1, 3, 3)
        for i in range(len(ids)):
            Ri = R[i] @ R0[i].T
            L[i, :3, :3] = Ri
            L[i, :3, 3] = (data.xpos[ids[i]] - Ri @ x0[i]) / mjcf.MM
            L[i, 3, 3] = 1.0
        lagen.append(L)
        pfeile = []
        summen: dict[str, float] = {}
        fn_boden = 0.0
        for ci in range(data.ncon):
            c = data.contact[ci]
            mujoco.mj_contactForce(model, data, ci, f6)
            fr = np.asarray(c.frame).reshape(3, 3)
            F = fr.T @ f6[:3]  # Kraft auf geom2 (Normale von geom1 nach geom2)
            b1, b2 = body_kid.get(int(geom_body[c.geom1]), "welt"), body_kid.get(int(geom_body[c.geom2]), "welt")
            if c.geom1 == boden_geom:
                b1 = "boden"
                if b2 in tb:
                    fn_boden += float(f6[0])
            key = "|".join(sorted((b1, b2)))
            betrag = float(np.linalg.norm(F))
            summen[key] = summen.get(key, 0.0) + betrag
            pfeile.append({"punkt": (c.pos / mjcf.MM).tolist(), "kraft": F.tolist(), "paar": [b1, b2], "n": betrag})
        pfeile.sort(key=lambda p: -p["n"])
        kontakte.append([{k: v for k, v in p.items() if k != "n"} for p in pfeile[:pfeile_je_bild]])
        for k, v in summen.items():
            paar.setdefault(k, [0.0] * bild).append(v)
        for k in paar:
            if len(paar[k]) < bild + 1:
                paar[k].append(0.0)
        fuehr.append(float(np.sum(data.actuator_force)) if model.nu else 0.0)
        bodn.append(fn_boden)
        bild += 1

    if model.nu and len(ctrl):
        data.ctrl[:] = ctrl[0]
        mujoco.mj_forward(model, data)
    aufnehmen()
    for i in range(n):
        if model.nu:
            data.ctrl[:] = ctrl[i]
        mujoco.mj_step(model, data)
        if (i + 1) % schritt_bild == 0:
            aufnehmen()
    Qa = np.array(Q)
    Ta = np.array(T)
    aus = Auswerter(mo)
    reihen = aus.reihen(Qa)
    bew = aus.bewerte(Qa, Ta)
    bew.v_end = float(data.qvel[model.jnt_dofadr[model.joint("an_l").id]]) if an else 0.0
    return Aufzeichnung(Ta, np.array(lagen), list(mo.zuordnung["koerper"]), reihen, kontakte,
                        {k: np.array(v) for k, v in paar.items()}, np.array(fuehr), np.array(bodn), bew,
                        (time.perf_counter() - t0) * 1000, n)


def varianten(mo: Modell, profile: list[Profil], nthread: int | None = None, abtast: int = 4
              ) -> list[Bewertung]:
    """Mehrere Abläufe parallel (``mujoco.rollout``, höchstens 4 Fäden); je Ablauf die Bewertung. Abläufe mit
    verschiedener Länge werden auf die längste aufgefüllt (Stillstand)."""
    import mujoco
    from mujoco import rollout

    if not profile:
        return []
    model = mo.model
    nstep = max(len(p.t) for p in profile) - 1
    nb = len(profile)
    nth = max(1, min(FADEN_MAX, nthread or FADEN_MAX, nb))
    zust = []
    ctrl = np.zeros((nb, nstep, model.nu))
    for i, p in enumerate(profile):
        _, s = anfangszustand(mo, p.v0)
        zust.append(s)
        c = steuerung(mo, p)
        if model.nu:
            ctrl[i, :len(c)] = c
            ctrl[i, len(c):] = c[-1] if len(c) else 0
    datas = [mujoco.MjData(model) for _ in range(nth)]
    with rollout.Rollout(nthread=nth) as ro:
        state, _ = ro.rollout(model, datas, np.array(zust), ctrl, nstep=nstep)
    nq = model.nq
    aus = Auswerter(mo)
    out = []
    for i, p in enumerate(profile):
        Q = state[i, ::abtast, 1:1 + nq]
        t = state[i, ::abtast, 0]
        out.append(aus.bewerte(Q, t))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Grenzen suchen (k-fache Teilung mit Rollouts, mehrere Kriterien auf denselben Varianten)


def grenzen(mo: Modell, erzeuge: Any, kriterien: dict[str, Any], lo: float, hi: float, runden: int = 3,
            erste: int = 8, weitere: int = 4) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Je Kriterium der kleinste Wert in [lo, hi], bei dem ``kriterium(Bewertung)`` zutrifft (monoton angenommen).
    ``erzeuge(wert)`` liefert das Profil. Runde 1: ``erste`` Werte (geometrisch verteilt) für alle Kriterien zugleich;
    danach je Kriterium ``weitere`` Werte im eingegrenzten Bereich, alle in einem Rollout-Stapel.

    Ergebnis je Kriterium: {"wert": Grenze (Mitte des letzten Bereichs) oder None, "ab": untere Schranke, "bis": obere,
    "schon_bei_lo": bool, "nie_bis_hi": bool}."""
    t0 = time.perf_counter()
    gerechnet = 0
    bereich: dict[str, tuple[float, float] | None] = {}
    out: dict[str, dict[str, Any]] = {}
    werte = list(np.geomspace(lo, hi, erste)) if lo > 0 else list(np.linspace(lo, hi, erste))
    bew = varianten(mo, [erzeuge(w) for w in werte])
    gerechnet += len(werte)
    for name, krit in kriterien.items():
        treffer = [bool(krit(b)) for b in bew]
        if treffer[0]:
            out[name] = {"wert": lo, "ab": None, "bis": lo, "schon_bei_lo": True, "nie_bis_hi": False}
            bereich[name] = None
        elif not any(treffer):
            out[name] = {"wert": None, "ab": hi, "bis": None, "schon_bei_lo": False, "nie_bis_hi": True}
            bereich[name] = None
        else:
            k = treffer.index(True)
            bereich[name] = (werte[k - 1], werte[k])
    for _ in range(runden - 1):
        offen = [n for n, b in bereich.items() if b is not None]
        if not offen:
            break
        plan: list[tuple[str, float]] = []
        for n in offen:
            a, b = bereich[n]
            for w in np.linspace(a, b, weitere + 2)[1:-1]:
                plan.append((n, float(w)))
        bew = varianten(mo, [erzeuge(w) for _, w in plan])
        gerechnet += len(plan)
        for n in offen:
            a, b = bereich[n]
            neu_a, neu_b = a, b
            for (m_, w), x in zip(plan, bew):
                if m_ != n:
                    continue
                if kriterien[n](x):
                    neu_b = min(neu_b, w)
                else:
                    neu_a = max(neu_a, w) if w < neu_b else neu_a
            bereich[n] = (neu_a, neu_b)
    for n, b in bereich.items():
        if b is not None:
            out[n] = {"wert": (b[0] + b[1]) / 2, "ab": b[0], "bis": b[1], "schon_bei_lo": False, "nie_bis_hi": False}
    return out, {"varianten": gerechnet, "ms": round((time.perf_counter() - t0) * 1000, 1)}
