"""MuJoCo-Modell (MJCF) aus der Szene (``szene.py``), im Ablauf-Prozess.

- Einheiten SI (m, kg, s); jeder Körper liegt mit seinem Rahmen im Schwerpunkt der Ruhelage, Achsen wie die Welt. So
  ist die Lage eines Körpers im Bild (``xpos``, ``xmat``) direkt die Matrix für die Zeitleiste: Welt = Lage · Ruhelage.
- Der geschobene Körper (``antrieb``) hängt an drei Schiebegelenken (längs, quer, senkrecht) und einem Kugelgelenk im
  Angriffspunkt; längs zieht ein Regler (Position und Geschwindigkeit) ihn auf die Sollbahn. Er kann also kippen,
  abheben und seitlich ausweichen; die Führungskraft greift im Angriffspunkt an (Vorgabe: am Boden unter dem
  Schwerpunkt, wie gebremste Räder).
- Räder und Laufrollen sind Kinder mit Drehgelenk; freie Körper (Ball) haben ein freies Gelenk.
- Kontakte nur über ausdrückliche Paare (``<pair>``) mit dem Reibwert der Paarung; alle Formen haben contype 0.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import quoteattr

import numpy as np

from kevcad_kernel.statik.dynamik import formen as fm

MM = 1e-3
G = 9.81
ZEITSCHRITT = 0.0005
SOLREF = "0.004 1"
SOLIMP = "0.95 0.99 0.001"


def _f(x: float) -> str:
    return f"{float(x):.7g}"


def _v(v: Any) -> str:
    return " ".join(_f(c) for c in np.asarray(v, float).ravel())


def schwerkraft(neigung_grad: float = 0.0, richtung: Any = (1.0, 0.0, 0.0)) -> np.ndarray:
    """Schwerkraft im System des Bodens: bei Neigung zeigt sie schräg in die Abwärtsrichtung (Boden bleibt waagrecht)."""
    t = np.radians(float(neigung_grad or 0.0))
    h = np.asarray(richtung, float).copy()
    h[2] = 0.0
    n = float(np.linalg.norm(h))
    h = h / n if n > 1e-9 else np.array([1.0, 0, 0])
    return G * (np.sin(t) * h - np.cos(t) * np.array([0, 0, 1.0]))


def formen_je_teil(meta: dict[str, Any], felder: dict[str, np.ndarray], coacd: dict[str, list[np.ndarray]]
                   ) -> dict[str, list[dict[str, Any]]]:
    """Je Teil die Kollisionsformen in Weltkoordinaten der Ruhelage (mm): {"typ": "kugel"|"zylinder"|"netz", …}."""
    out: dict[str, list[dict[str, Any]]] = {}
    for n, c in meta["kollision"].items():
        art = c["art"]
        if art == "kugel":
            out[n] = [{"typ": "kugel", "mitte": np.asarray(c["mitte"]), "r": float(c["radius"])}]
        elif art == "drehteil":
            p, d = np.asarray(c["punkt"], float), np.asarray(c["achse"], float)
            if c.get("zylinder"):
                tm, r, hl = c["zylinder"]
                out[n] = [{"typ": "zylinder", "mitte": p + d * tm, "achse": d, "r": r, "hl": hl}]
            else:
                pr = (np.asarray(c["profil"][0]), np.asarray(c["profil"][1]))
                out[n] = [{"typ": "netz", "punkte": s} for s in fm.drehteil_stuecke(pr, p, d)]
        elif art == "coacd" and coacd.get(n):
            lage = np.asarray(c["lage"], float)
            out[n] = [{"typ": "netz", "punkte": s @ lage[:3, :3].T + lage[:3, 3]} for s in coacd[n]]
        else:
            out[n] = [{"typ": "netz", "punkte": np.asarray(felder[f"h:{n}"], float)}]
    return out


def baue_xml(meta: dict[str, Any], formen: dict[str, list[dict[str, Any]]], *, angriff: np.ndarray | None,
             richtung: np.ndarray, schwerkraft_v: np.ndarray, kp: float | None = None,
             ohne: set[str] | None = None) -> tuple[str, dict[str, Any]]:
    """MJCF-Text und Zuordnung (Körper → Name, Formen je Teil, Fußpunkte). ``ohne``: Körper, die weggelassen werden
    (Szenario ohne Ladung)."""
    ohne = ohne or set()
    K = {k["id"]: k for k in meta["koerper"] if k["id"] not in ohne}
    kinder: dict[str | None, list[str]] = {}
    for k in K.values():
        el = k["eltern"] if k["eltern"] in K else None
        kinder.setdefault(el, []).append(k["id"])
    an = meta.get("antrieb") if meta.get("antrieb") in K else None
    d = np.asarray(richtung, float)
    d[2] = 0
    d = d / (np.linalg.norm(d) or 1.0)
    q = np.cross([0, 0, 1.0], d)
    assets: list[str] = []
    geoms_je_koerper: dict[str, list[str]] = {}
    geom_teil: dict[str, str] = {}
    teil_geoms: dict[str, list[str]] = {}
    gi = 0
    for n, liste in formen.items():
        kid = meta["kollision"][n]["koerper"]
        if kid != "welt" and kid not in K:
            continue
        for f in liste:
            name = f"g{gi}"
            gi += 1
            geom_teil[name] = n
            teil_geoms.setdefault(n, []).append(name)
            geoms_je_koerper.setdefault(kid, []).append(name)
            f["_name"] = name
            if f["typ"] == "netz":
                assets.append(f"m{name}")

    def schwerpunkt(kid: str) -> np.ndarray:
        return np.asarray(K[kid]["schwerpunkt"], float) * MM

    def geom_xml(kid: str, ursprung: np.ndarray) -> list[str]:
        zeilen = []
        for n, liste in formen.items():
            if meta["kollision"][n]["koerper"] != kid:
                continue
            for f in liste:
                nm = f["_name"]
                if f["typ"] == "kugel":
                    zeilen.append(f'<geom name="{nm}" type="sphere" size="{_f(f["r"] * MM)}" '
                                  f'pos="{_v(f["mitte"] * MM - ursprung)}"/>')
                elif f["typ"] == "zylinder":
                    zeilen.append(f'<geom name="{nm}" type="cylinder" size="{_f(f["r"] * MM)} {_f(f["hl"] * MM)}" '
                                  f'pos="{_v(f["mitte"] * MM - ursprung)}" zaxis="{_v(f["achse"])}"/>')
                else:
                    zeilen.append(f'<geom name="{nm}" type="mesh" mesh="m{nm}" pos="{_v(-ursprung)}"/>')
        return zeilen

    mesh_xml = []
    for n, liste in formen.items():
        kid = meta["kollision"][n]["koerper"]
        if kid != "welt" and kid not in K:
            continue
        for f in liste:
            if f["typ"] == "netz":
                P = np.asarray(f["punkte"], float) * MM
                mesh_xml.append(f'<mesh name="m{f["_name"]}" vertex="{_v(P)}" maxhullvert="96"/>')

    def koerper_xml(kid: str, eltern_ursprung: np.ndarray, tiefe: int) -> list[str]:
        k = K[kid]
        c = schwerpunkt(kid)
        ein = "  " * tiefe
        z = [f'{ein}<body name="{kid}" pos="{_v(c - eltern_ursprung)}">']
        if kid == an:
            P = np.asarray(angriff, float) * MM if angriff is not None else c
            z += [f'{ein}  <joint name="an_l" type="slide" axis="{_v(d)}"/>',
                  f'{ein}  <joint name="an_q" type="slide" axis="{_v(q)}"/>',
                  f'{ein}  <joint name="an_z" type="slide" axis="0 0 1"/>',
                  f'{ein}  <joint name="an_r" type="ball" pos="{_v(P - c)}"/>']
        elif k["art"] in ("dreh", "schiebe") and k.get("gelenk"):
            gj = k["gelenk"]
            typ = "hinge" if gj["art"] == "dreh" else "slide"
            z.append(f'{ein}  <joint name="j_{kid}" type="{typ}" pos="{_v(np.asarray(gj["punkt"]) * MM - c)}" '
                     f'axis="{_v(gj["achse"])}" damping="1e-5"/>')
        elif k["art"] == "frei" or (k["art"] == "antrieb"):
            z.append(f'{ein}  <freejoint name="f_{kid}"/>')
        I = np.asarray(k["traegheit"], float) * 1e-6  # kg·mm² → kg·m²
        m = max(float(k["masse"]), 1e-4)
        ev = np.linalg.eigvalsh(I)
        if ev.min() <= 1e-12:  # entartet (Scheibe ohne Dicke): kleine Kugel um den Schwerpunkt
            I = I + np.eye(3) * max(1e-9, 1e-3 * m * 1e-4)
        z.append(f'{ein}  <inertial pos="0 0 0" mass="{_f(m)}" fullinertia="{_f(I[0, 0])} {_f(I[1, 1])} '
                 f'{_f(I[2, 2])} {_f(I[0, 1])} {_f(I[0, 2])} {_f(I[1, 2])}"/>')
        z += [ein + "  " + g for g in geom_xml(kid, c)]
        for ch in kinder.get(kid, []):
            z += koerper_xml(ch, c, tiefe + 1)
        z.append(f"{ein}</body>")
        return z

    welt = []
    for kid in kinder.get(None, []):
        welt += koerper_xml(kid, np.zeros(3), 2)
    welt_geoms = geom_xml("welt", np.zeros(3))
    boden_z = float(meta["boden_z"]) * MM
    # Kontaktpaare
    paare = []
    for (a, b), mu in zip(meta["paare"], meta["paar_mu"]):
        for ga in teil_geoms.get(a, []):
            for gb in teil_geoms.get(b, []):
                paare.append(f'<pair geom1="{ga}" geom2="{gb}" friction="{_f(mu)} {_f(mu)} 0.001 0.0001 0.0001"/>')
    for n, mu in zip(meta["boden_paare"], meta["boden_mu"]):
        for g in teil_geoms.get(n, []):
            paare.append(f'<pair geom1="boden" geom2="{g}" friction="{_f(mu)} {_f(mu)} 0.001 0.0001 0.0001"/>')
    # Regler des Antriebs
    akt = []
    if an is not None:
        m_an = sum(float(K[x]["masse"]) for x in K if _wurzel(K, x) == an)
        w = 2 * np.pi * 20.0
        kp_ = kp if kp is not None else m_an * w * w
        kv_ = 2 * m_an * w
        f_max = max(200.0, 60.0 * m_an * G)
        # Regler (Weg, Geschwindigkeit) plus Vorsteuerung der Kraft m · a: folgt der Sollbahn ohne Überschwingen
        akt = [f'<position name="soll_l" joint="an_l" kp="{_f(kp_)}" ctrlrange="-1e4 1e4" '
               f'forcerange="{_f(-f_max)} {_f(f_max)}" forcelimited="true"/>',
               f'<velocity name="soll_v" joint="an_l" kv="{_f(kv_)}" ctrlrange="-1e3 1e3" '
               f'forcerange="{_f(-f_max)} {_f(f_max)}" forcelimited="true"/>',
               f'<motor name="soll_f" joint="an_l" gear="1" ctrlrange="{_f(-f_max)} {_f(f_max)}" '
               f'ctrllimited="true"/>']
    xml = "\n".join([
        '<mujoco model="kevcad-ablauf">',
        '  <compiler angle="radian" boundmass="1e-5" boundinertia="1e-10"/>',
        f'  <option timestep="{ZEITSCHRITT}" gravity="{_v(schwerkraft_v)}" integrator="implicitfast" '
        'cone="elliptic" iterations="60" ls_iterations="30" tolerance="1e-9"/>',
        f'  <default><geom contype="0" conaffinity="0" condim="3" solref="{SOLREF}" solimp="{SOLIMP}" '
        'rgba="0.6 0.6 0.6 1"/></default>',
        "  <asset>", *["    " + x for x in mesh_xml], "  </asset>",
        "  <worldbody>",
        f'    <geom name="boden" type="plane" size="0 0 1" pos="0 0 {_f(boden_z)}"/>',
        *["    " + g for g in welt_geoms],
        *welt,
        "  </worldbody>",
        "  <contact>", *["    " + p for p in paare], "  </contact>",
        "  <actuator>", *["    " + a for a in akt], "  </actuator>",
        "</mujoco>",
    ])
    zuordnung = {"geom_teil": geom_teil, "teil_geoms": teil_geoms, "koerper": list(K), "antrieb": an,
                 "masse_antrieb": sum(float(K[x]["masse"]) for x in K if an is not None and _wurzel(K, x) == an),
                 "richtung": d.tolist(), "quer": q.tolist(), "paare": len(paare)}
    return xml, zuordnung


def _wurzel(K: dict[str, Any], kid: str) -> str:
    while K[kid]["eltern"] is not None and K[kid]["eltern"] in K:
        kid = K[kid]["eltern"]
    return kid


def namen_quote(s: str) -> str:
    return quoteattr(s)
