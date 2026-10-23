"""Stufe S0 (bei jedem Lauf, Millisekunden): Kippen je Richtung, Rutschen, lose aufliegende Teile, Schraubenlast grob.

Baut auf der Standsicherheit der Prüfung auf (``pruefung/stand.py``: Gruppen, Schwerpunkt, Standfläche) und rechnet
für jedes Szenario mit dessen Beschleunigungsfeld und Lasten weiter:

- **Kippen**: je Kante der Standfläche das Moment aller Kräfte um die Kante; Kippreserve = Standmoment / Kippmoment
  (≥ 1 steht). Dazu je Richtung der Kippwinkel (Neigung, bei der es kippt) und die Beschleunigung, bei der es kippt.
- **Rutschen**: waagrechte Kraft / senkrechte Kraft am Boden gegen den Reibwert aus dem Katalog (Material der
  Bodenteile gegen den Untergrund, Standard Beton). Auf Rollen gilt das nur gebremst.
- **Kraftpaare** (innere Kräfte zwischen zwei Teilen, ``st.last(…, gegen=…)``, T32) zählen beim Kippen, Rutschen und
  Abheben des Ganzen nicht (Kraft und Gegenkraft heben sich auf); bei losen Teilen und Schrauben wirkt jede Seite auf
  ihre Teile.
- **Lose Teile** (``verbinde(…, art="aufliegen")`` ohne weitere feste Verbindung): rutschen sie auf ihrer Auflage?
- **Schrauben** (``verbinde(…, art="schraube", mit=[…])``): Kraft je Schraube aus allem, was an der Verbindung hängt
  (grob, ohne Vorspannung), gegen Streckgrenze × Spannungsquerschnitt.
- **Gewindeeinsätze** (Strang „Bestand Stufe 2“): Steckt in ``mit`` ein Gewindeeinsatz (Name mit „Gewindeeinsatz“,
  „Einschmelz…“ oder „Heat-Set“) und ist eine Seite ein Druckteil, trägt der Einsatz die Zugkraft der Schraube. Sie
  wird gegen die Auszugkraft aus dem Katalog (``einsatz_auszug``, Größe und Druckmaterial) gestellt; ohne belegten Wert
  bleibt der Einsatz unbewertet und die Statik sagt es.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from kevcad_kernel.statik.modell import BODEN_TOL, StatikModell
from kevcad_kernel.statik.szenario import Szenario, angriffe
from kevcad_kernel.statik.werkstoff import G, reibwert, spannungsquerschnitt

RICHTUNGEN = {"+X": (1, 0), "−X": (-1, 0), "+Y": (0, 1), "−Y": (0, -1)}
MU_ANNAHME = 0.3
RP_ANNAHME = 240.0  # Schraube ohne Werkstoff: Festigkeitsklasse 4.6 (DIN EN ISO 898-1) angenommen
EINSATZ_WORTE = re.compile(r"(gewindeeinsatz|einschmelz|heat.?set)", re.IGNORECASE)  # wie bauplan/eingang.py


def einsatz_nachweis(m: StatikModell, katalog: Any, mit: list[str], druck: list[str], d: float,
                     kraft_axial: float) -> dict[str, Any] | None:
    """Gewindeeinsatz einer Schraubverbindung mit Druckteil: Auszugkraft aus dem Katalog gegen die Zugkraft je Schraube.
    None ohne Einsatz in ``mit`` oder ohne Druckteil; sonst ``{"teil", "druckteil", "groesse", "material",
    "auszug_n", "sicherheit", "quelle", "einsatz", "bedingungen", "geschaetzt"}`` (``auszug_n`` None: nicht belegt)."""
    einsatz = next((n for n in mit if n in m.teile and EINSATZ_WORTE.search(n.rsplit("/", 1)[-1])), None)
    if einsatz is None or not druck:
        return None
    teil = m.teile[druck[0]]  # Druckteil, in dem der Einsatz sitzt
    groesse = f"M{d:g}"
    mat = teil.material_id or (teil.werkstoff.id if teil.werkstoff is not None else None)
    eintrag = None
    if katalog is not None and mat and hasattr(katalog, "einsatz_auszug"):
        try:
            eintrag = katalog.einsatz_auszug(groesse, mat)
        except Exception:  # noqa: BLE001 - ohne Katalog kein Nachweis
            eintrag = None
    auszug = float(eintrag["kraft_n"]) if eintrag else None
    sf = None
    if auszug is not None and kraft_axial > 1e-9:
        sf = round(auszug / kraft_axial, 2)
    return {"teil": einsatz, "druckteil": druck[0], "groesse": groesse, "material": mat, "auszug_n": auszug,
            "sicherheit": sf, "quelle": (eintrag or {}).get("quelle"), "einsatz": (eintrag or {}).get("einsatz"),
            "bedingungen": (eintrag or {}).get("bedingungen"), "geschaetzt": bool((eintrag or {}).get("geschaetzt"))}


def _kraefte_auf(m: StatikModell, sz: Szenario, teile: set[str], innere: bool = True
                 ) -> list[tuple[np.ndarray, np.ndarray]]:
    """(Kraft N, Angriffspunkt mm) für Gewicht und Trägheit der Teile und die Lasten auf ihnen. ``innere=False``:
    ohne Kraftpaare (Kippen, Rutschen und Abheben des Ganzen: innere Kräfte heben sich auf, T32); sonst wirkt jede
    Seite eines Paars auf ihre Teile (lose Teile, Schrauben)."""
    f = sz.feld
    out = [(m.teile[n].masse_kg * f, m.teile[n].schwerpunkt) for n in teile if n in m.teile]
    for last in sz.kraefte():
        for n, F, p, _ in angriffe(m, last, innere):
            if n in teile:
                p = p if p is not None else m.teile[n].schwerpunkt
                out.append((F, np.asarray(p, dtype=float)))
    return out


def _strahl(c: np.ndarray, d: np.ndarray, poly: np.ndarray) -> float:
    """Abstand von c in Richtung d bis zum Rand des Polygons (c innen), sonst 0."""
    best = math.inf
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        e = b - a
        den = d[0] * e[1] - d[1] * e[0]
        if abs(den) < 1e-12:
            continue
        w = a - c
        t = (w[0] * e[1] - w[1] * e[0]) / den
        u = (w[0] * d[1] - w[1] * d[0]) / den
        if t >= -1e-9 and -1e-9 <= u <= 1 + 1e-9:
            best = min(best, t)
    return 0.0 if best is math.inf else float(best)


def kippen(m: StatikModell, sz: Szenario) -> list[dict[str, Any]]:
    out = []
    z0 = m.boden_z
    for g in m.gruppen:
        poly = np.asarray(g.get("stuetzpolygon") or [], dtype=float)
        if g.get("befestigt") or g.get("schwebt") or len(poly) < 3:
            continue
        teile = set(g.get("teile") or [])
        if teile and teile <= m.rollend:
            continue  # rollt frei (Kugel): Kippen und Rutschen gelten nicht, das Rollen zeigt erst S2
        kr = _kraefte_auf(m, sz, teile, innere=False)
        if not kr:
            continue
        F_ges = sum(F for F, _ in kr)
        if F_ges[2] >= 0:  # hebt ab
            out.append({"teile": sorted(teile)[:3], "gruppe": len(teile), "reserve": 0.0, "kante": None,
                        "text": "Lasten heben die Gruppe ab"})
            continue
        n = len(poly)
        area = 0.5 * sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
        if area < 0:
            poly = poly[::-1]
        best = None
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            e = b - a
            le = float(np.linalg.norm(e))
            if le < 1e-6:
                continue
            nout = np.array([e[1], -e[0]]) / le  # außen (rechts der Kante bei Umlauf gegen den Uhrzeigersinn)
            stand = kipp = 0.0
            for F, P in kr:
                d_in = float(np.dot(P[:2] - a, -nout))
                term = (-float(F[2])) * d_in - float(np.dot(F[:2], nout)) * (float(P[2]) - z0)
                if term >= 0:
                    stand += term
                else:
                    kipp -= term
            reserve = math.inf if kipp < 1e-9 else stand / kipp
            if best is None or reserve < best[0]:
                best = (reserve, [a.tolist(), b.tolist()], nout)
        if best is None:
            continue
        sp = np.asarray(g.get("schwerpunkt") or [0, 0, 0], dtype=float)
        h = max(float(sp[2]) - z0, 1e-6)
        je_richtung = {}
        for k, (dx, dy) in RICHTUNGEN.items():
            d = _strahl(sp[:2], np.array([dx, dy], dtype=float), poly)
            je_richtung[k] = {"kippwinkel": round(math.degrees(math.atan2(d, h)), 1),
                              "a_kipp": round(G * d / h, 2)}
        richtung = best[2]
        schwer = max(teile, key=lambda n: m.teile[n].masse_kg if n in m.teile else 0.0)
        je_gruppe: dict[str, float] = {}
        for n in teile:
            je_gruppe[n.split("/")[0]] = je_gruppe.get(n.split("/")[0], 0.0) + (m.teile[n].masse_kg if n in m.teile
                                                                                else 0.0)
        haupt = max(je_gruppe, key=lambda k: je_gruppe[k])
        name = schwer if len(teile) == 1 else f"Der Aufbau um {haupt} ({len(teile)} Teile)"
        i = int(np.argmax(np.abs(richtung)))
        rtext = ("+" if richtung[i] > 0 else "−") + "XY"[i] if abs(richtung[i]) > 0.9 else (
            "(" + "; ".join(f"{c:.2f}".replace(".", ",") for c in richtung) + ")")
        out.append({"name": name, "richtung_text": rtext,
                    "teile": [schwer] + sorted(teile - {schwer})[:2], "gruppe": len(teile), "masse_kg": g.get("masse_kg"),
                    "reserve": None if best[0] is math.inf else round(best[0], 3),
                    "kante": [[round(c, 1) for c in p] for p in best[1]],
                    "richtung": [round(float(richtung[0]), 3), round(float(richtung[1]), 3)],
                    "je_richtung": je_richtung})
    return out


def _material(m: StatikModell, n: str) -> str | None:
    t = m.teile.get(n)
    return t.material_id if t else None


def rutschen(m: StatikModell, sz: Szenario, katalog: Any, rollen: bool) -> list[dict[str, Any]]:
    out = []
    z0 = m.boden_z
    for g in m.gruppen:
        teile = set(g.get("teile") or [])
        if g.get("befestigt") or g.get("schwebt") or not teile or teile <= m.rollend:
            continue
        kr = _kraefte_auf(m, sz, teile, innere=False)
        R = sum((F for F, _ in kr), np.zeros(3))
        N = -float(R[2])
        H = float(np.linalg.norm(R[:2]))
        if N <= 1e-9:
            continue
        mu_erf = H / N
        unten = [n for n in teile if n in m.teile and m.teile[n].bmin[2] <= z0 + BODEN_TOL and n not in m.rollend]
        werte = []
        for n in unten:
            r = reibwert(katalog, _material(m, n), sz.untergrund or m.untergrund)
            werte.append((r["haft"] if r else MU_ANNAHME, n, r))
        if not werte:
            continue
        mu, teil, r = min(werte, key=lambda w: w[0])
        e = {"teile": sorted(teile)[:3], "gruppe": len(teile), "mu_erf": round(mu_erf, 3), "mu_vorh": round(mu, 3),
             "reserve": None if mu_erf < 1e-9 else round(mu / mu_erf, 3), "teil": teil,
             "untergrund": sz.untergrund or m.untergrund,
             "paarung": (r or {}).get("paarung"), "quelle": (r or {}).get("quelle"), "angenommen": r is None,
             "auf_rollen": rollen}
        out.append(e)
    return out


def lose_teile(m: StatikModell, sz: Szenario, katalog: Any) -> list[dict[str, Any]]:
    """Teile, die nur aufliegen: ``verbinde(a, b, art="aufliegen")`` und sonst keine feste Verbindung, kein Gelenk
    und keine Berührung mit anderen Teilen als ihren Auflagen."""
    out = []
    auflagen: dict[str, set[str]] = {}
    for v in m.verbindungen:
        if v["art"] == "aufliegen" and v["b"] not in (None, "boden"):
            auflagen.setdefault(v["a"], set()).add(v["b"])
    for v in m.verbindungen:
        a, b = v["a"], v["b"]
        if v["art"] != "aufliegen" or b in (None, "boden") or a not in m.teile or m.teile[a].verbindungselement:
            continue
        halt = False
        for e in m.kanten.values():
            if a not in (e["a"], e["b"]):
                continue
            x = e["b"] if e["a"] == a else e["a"]
            if x in auflagen.get(a, set()):
                continue
            if (e["verbinde"] and e["verbinde"] != "aufliegen") or e["gelenk"] or \
                    e["kontakt"] in ("beruehrt", "durchdringt"):
                halt = True
                break
        if halt:
            continue
        kr = _kraefte_auf(m, sz, {a})
        R = sum((F for F, _ in kr), np.zeros(3))
        N = -float(R[2])
        if N <= 1e-9:
            out.append({"teil": a, "auf": b, "mu_erf": None, "mu_vorh": None, "reserve": 0.0, "hebt_ab": True})
            continue
        mu_erf = float(np.linalg.norm(R[:2])) / N
        r = reibwert(katalog, _material(m, a), _material(m, b) or b)
        mu = r["haft"] if r else MU_ANNAHME
        out.append({"teil": a, "auf": b, "mu_erf": round(mu_erf, 3), "mu_vorh": round(mu, 3),
                    "reserve": None if mu_erf < 1e-9 else round(mu / mu_erf, 3), "angenommen": r is None,
                    "zeile": v.get("zeile")})
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Schrauben


def _graph(m: StatikModell, ohne: set[str], ohne_kante: set[frozenset]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {n: set() for n in m.teile if n not in ohne}
    for key, e in m.kanten.items():
        a, b = e["a"], e["b"]
        if key in ohne_kante or a in ohne or b in ohne or a not in adj or b not in adj:
            continue
        if e["verbinde"] or e["gelenk"] or e["kontakt"]:
            adj[a].add(b)
            adj[b].add(a)
    return adj


def _komponente(adj: dict[str, set[str]], start: str) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        n = stack.pop()
        for x in adj.get(n, ()):
            if x not in seen:
                seen.add(x)
                stack.append(x)
    return seen


def _geerdet(m: StatikModell, teile: set[str]) -> bool:
    an_kulisse = {e["a"] if e["b"] in m.kulisse else e["b"] for e in m.kanten.values()
                  if (e["a"] in m.kulisse) != (e["b"] in m.kulisse)}
    for n in teile:
        k = m.koerper_von(n)
        if k is not None and k.geerdet:
            return True
        t = m.teile.get(n)
        if t is not None and t.bmin[2] <= m.boden_z + BODEN_TOL:
            return True
        if n in an_kulisse:
            return True
    return False


def schrauben(m: StatikModell, sz: Szenario, koerper: dict[str, Any] | None = None,
              katalog: Any = None) -> list[dict[str, Any]]:
    out = []
    for v in m.verbindungen:
        if v["art"] != "schraube" or v["b"] in (None, "boden"):
            continue
        a, b = v["a"], v["b"]
        if a not in m.teile or b not in m.teile:
            continue
        schr = [n for n in v["mit"] if n in m.teile and "schraube" in n.lower()]
        if not schr:
            continue
        mit = set(v["mit"])
        adj = _graph(m, mit, {frozenset((a, b))})
        haengt, traeger = None, None
        for x, y in ((a, b), (b, a)):
            comp = _komponente(adj, x)
            if y in comp:
                break  # über andere Wege verbunden: Kraftfluss nicht eindeutig
            if not _geerdet(m, comp):
                haengt, traeger = comp, y
                break
        if haengt is None:
            continue
        kr = _kraefte_auf(m, sz, haengt)
        F = sum((k for k, _ in kr), np.zeros(3))
        pos = np.array([m.teile[n].schwerpunkt for n in schr])
        C = pos.mean(axis=0)
        M = sum((np.cross(P - C, k) for k, P in kr), np.zeros(3))
        ach = []
        for n in schr:
            info = (koerper or {}).get(n)
            ax = (info.info.get("achse") if info is not None else None)
            if ax is not None:
                ach.append(np.asarray(ax, dtype=float))
        achse = (np.mean(ach, axis=0) if ach else np.array([0.0, 0.0, 1.0]))
        achse = achse / max(float(np.linalg.norm(achse)), 1e-9)
        n_s = len(schr)
        d = next((m.teile[n].gewinde_d for n in schr if m.teile[n].gewinde_d), None) or 6.0
        r_eff = max(float(np.mean(np.linalg.norm(pos - C, axis=1))) if n_s > 1 else 0.0, 0.85 * d)
        M_quer = M - achse * float(np.dot(M, achse))
        F_ax = abs(float(np.dot(F, achse))) / n_s + float(np.linalg.norm(M_quer)) / (n_s * r_eff)
        F_q = float(np.linalg.norm(F - achse * float(np.dot(F, achse)))) / n_s + abs(float(np.dot(M, achse))) / (
            n_s * r_eff)
        As = spannungsquerschnitt(d) or 20.1
        w = m.teile[schr[0]].werkstoff
        rp = float(w.streckgrenze) if w is not None and w.streckgrenze else RP_ANNAHME
        u = math.sqrt((F_ax / (rp * As)) ** 2 + (F_q / (0.6 * rp * As)) ** 2)
        druck = [n for n in (a, b) if m.teile[n].druckteil]
        zeile = {"verbindung": f"{a} an {b}", "teile": [a, b] + schr[:2], "schrauben": n_s,
                 "gewinde": f"M{d:g}", "kraft_axial": round(F_ax, 1), "kraft_quer": round(F_q, 1),
                 "ausnutzung": round(u, 4), "sicherheit": None if u < 1e-12 else round(1 / u, 2),
                 "rp": rp, "rp_angenommen": w is None or not w.streckgrenze, "traegt": traeger,
                 "haengt": sorted(haengt)[:4], "haengt_masse_kg": round(sum(m.teile[n].masse_kg for n in haengt), 3),
                 "druckteil": druck, "zeile": v.get("zeile")}
        e = einsatz_nachweis(m, katalog, list(v["mit"]), druck, d, F_ax)
        if e is not None:
            zeile["einsatz"] = e
        out.append(zeile)
    return out


def traeger(m: StatikModell, sz: Szenario) -> list[dict[str, Any]]:
    """Einfache Träger (S0, ohne Stabwerk): jeder Stab für sich als Einfeldträger zwischen seinem ersten und letzten
    Lager, Überstände als Kragarme, mit Eigengewicht und seinen Einzellasten (quer zur Achse). Ersatz, wenn das
    Stabwerk nicht rechnen kann (beweglich, kein Lager); bewusst grob."""
    out = []
    f = sz.feld
    for s in m.staebe.values():
        ts = sorted({a.t for a in m.anschluesse if a.stab == s.name}
                    | {a.partner[2] for a in m.anschluesse if a.partner[0] == "stab" and a.partner[1] == s.name})
        if not ts:
            continue
        L, ax = s.laenge, s.achse
        q_vec = s.masse_kg / L * f
        q = float(np.linalg.norm(q_vec - ax * float(np.dot(q_vec, ax))))  # N/mm quer
        lasten = []
        for last in sz.kraefte():
            for n, F, p, _ in angriffe(m, last):
                if n != s.name:
                    continue
                Fq = float(np.linalg.norm(F - ax * float(np.dot(F, ax))))
                lasten.append((s.t_von(p) if p is not None else L / 2, Fq))
        a, b = ts[0], ts[-1]
        E, I = float(s.werkstoff.E), min(s.q.I_lang, s.q.I_quer)
        W = min(s.q.W_lang, s.q.W_quer)
        M = 0.0
        w = 0.0
        if b - a > 1.0:  # Feld
            l = b - a
            M = q * l * l / 8
            w = 5 * q * l ** 4 / (384 * E * I)
            for t, F in lasten:
                if a <= t <= b:
                    x, y = t - a, b - t
                    M += F * x * y / l
                    w += F * x * y * (l * l - x * x - y * y) / (6 * E * I * l) if l > 0 else 0.0
        for k_l, seite in ((a, "Anfang"), (L - b, "Ende")):  # Kragarme
            if k_l < 1.0:
                continue
            Mk = q * k_l * k_l / 2
            wk = q * k_l ** 4 / (8 * E * I)
            for t, F in lasten:
                abst = (a - t) if seite == "Anfang" else (t - b)
                if abst > 0:
                    Mk += F * abst
                    wk += F * abst * abst * (3 * k_l - abst) / (6 * E * I)
            M = max(M, Mk)
            w = max(w, wk)
        sigma = M / W if W > 0 else math.inf
        grenze = float(s.werkstoff.grenze or 0)
        sf = grenze / sigma if sigma > 1e-9 else math.inf
        out.append({"stab": s.name, "moment_nmm": round(M, 1), "spannung": round(sigma, 2),
                    "sicherheit": round(sf, 3) if math.isfinite(sf) else None, "durchbiegung_mm": round(w, 3),
                    "grenze_durchbiegung_mm": round(max(b - a, 2 * max(a, L - b)) / sz.durchbiegung, 3)})
    return out


def rechne(m: StatikModell, sz: Szenario, katalog: Any, rollen: bool, koerper: dict[str, Any] | None = None,
           traeger_auch: bool = False) -> dict[str, Any]:
    out = {"kippen": kippen(m, sz), "rutschen": rutschen(m, sz, katalog, rollen),
           "lose": lose_teile(m, sz, katalog), "schrauben": schrauben(m, sz, koerper, katalog)}
    if traeger_auch:
        out["traeger"] = traeger(m, sz)
    return out
