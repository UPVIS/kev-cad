"""Maßstab einer Referenz nachträglich setzen (Phase 4): ein bekanntes Maß, alles skaliert mit.

Object Capture rechnet ohne LiDAR maßstabslos (R3); hatte ``referenz_video`` kein Maß oder ein falsches, gibt Kevin
später eines an: zwei Punkte am Referenznetz mit ihrem echten Abstand (App: zwei Klicks, MCP ``punkte``) oder ein
Maß der Hülle (``kante``: ``laenge``, ``breite``, ``hoehe``, ``grund_laenge``, ``grund_breite``) bzw. ein gemessenes
Maß der Vermessung (``kante`` = Name eines ``param``).

Skaliert wird um den Ursprung des Referenzsystems (Mitte des Grundrisses, Boden z = 0), so bleibt der Boden auf
z = 0 und die Mitte an ihrem Platz; die Lage am Modell (``lage``) gilt danach weiter und wird beim nächsten
Vermessen neu bestimmt:

- ``capture/netz_mm.obj`` (Punkte), ``netz_mm.ply`` und ``punkte_mm.ply`` bzw. ``punktwolke_mm.ply`` (binär
  little-endian oder ASCII, die ersten drei Eigenschaften x, y, z als float),
- ``capture/poses.json`` (``aligned``: ``opencv.t``, ``position``, Verschiebung von ``camera_to_world``),
- ``capture/kameras.json`` (Scan), ``capture/bericht.json`` (Hülle, Grundkörper, Oberkante, Prüfmaße),
- ``referenz.json`` (``capture`` mit Hülle, Grundkörper, Oberkante; ``massstab`` mit Faktor und Verlauf),
- ``messung/messung.json``, wenn ihr Maßstab von der Referenz kommt (``mit_messung``): Maße, Sigma, Hülle, Teile,
  Kameras (``t``, ``zentrum``), Lage eines Scans. Sie bleibt, wenn sie ihren Maßstab aus einem bekannten Maß hat.

Ein Scan (Kev Scan, LiDAR) ist metrisch und wird nicht skaliert (die Tiefenbilder gehörten sonst mit dazu).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from kevcad_kernel.referenz.ablage import CAPTURE, MESSUNG, ReferenzFehler

FAKTOR_MIN, FAKTOR_MAX = 0.2, 5.0
HUELLE = {"laenge": ("huelle", "laenge"), "breite": ("huelle", "breite"), "hoehe": ("huelle", "hoehe"),
          "grund_laenge": ("grundkoerper", "laenge"), "grund_breite": ("grundkoerper", "breite")}
PLY_DATEIEN = ("netz_mm.ply", "punkte_mm.ply", "punktwolke_mm.ply")


def faktor_pruefen(mm: float, ist: float) -> float:
    if not (mm and mm > 0):
        raise ReferenzFehler("Das echte Maß in mm angeben (größer als 0)")
    if not (ist and ist > 1e-6):
        raise ReferenzFehler("Das Maß an der Referenz ist 0: zwei verschiedene Punkte wählen")
    f = float(mm) / float(ist)
    if not FAKTOR_MIN <= f <= FAKTOR_MAX:
        def de(x: float, nd: int) -> str:
            return f"{x:.{nd}f}".replace(".", ",")

        raise ReferenzFehler(f"Faktor {de(f, 3)} (an der Referenz {de(ist, 1)} mm, echt {de(mm, 1)} mm) ist "
                             f"unplausibel; erlaubt {de(FAKTOR_MIN, 1)} bis {de(FAKTOR_MAX, 1)}. Punkte oder Maß prüfen")
    return f


def kante_ist(meta: dict[str, Any], messung: dict[str, Any] | None, kante: str) -> tuple[float, str]:
    """Aktueller Wert eines benannten Maßes: Hülle bzw. Grundkörper (aus referenz.json) oder ein gemessenes Maß
    (messung.json). Rückgabe (mm, Art „huelle“ | „messung“)."""
    cap = meta.get("capture") or {}
    if kante in HUELLE:
        gruppe, feld = HUELLE[kante]
        v = (cap.get(gruppe) or {}).get(feld)
        if v is None:
            raise ReferenzFehler(f"Die Referenz hat kein Maß {kante} (kein Netz mit Bericht)")
        return float(v), "huelle"
    if messung and kante in (messung.get("masse") or {}):
        return float(messung["masse"][kante]), "messung"
    bekannt = sorted(HUELLE) + sorted((messung or {}).get("masse") or {})
    raise ReferenzFehler(f"Maß {kante!r} unbekannt; möglich: {', '.join(bekannt)}")


def _zahl(v: Any, f: float) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v) * f, 4)
    if isinstance(v, list):
        return [_zahl(x, f) for x in v]
    if isinstance(v, dict):
        return {k: _zahl(x, f) for k, x in v.items()}
    return v


def _json_lesen(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _json_schreiben(p: Path, d: Any) -> None:
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def obj_skalieren(pfad: Path, f: float) -> int:
    """Zeilen ``v x y z [r g b]`` skalieren (Texturkoordinaten und Normalen bleiben). Rückgabe: Zahl der Punkte."""
    tmp = pfad.with_name(f".{pfad.name}.tmp")
    n = 0
    with open(pfad, encoding="utf-8", errors="replace") as quelle, open(tmp, "w", encoding="utf-8") as ziel:
        for zeile in quelle:
            if zeile.startswith("v "):
                t = zeile.split()
                xyz = [float(t[1]) * f, float(t[2]) * f, float(t[3]) * f]
                ziel.write("v " + " ".join(f"{x:.5f}" for x in xyz) + ("" if len(t) <= 4 else " " + " ".join(t[4:]))
                           + "\n")
                n += 1
            else:
                ziel.write(zeile)
    os.replace(tmp, pfad)
    return n


_PLY_TYPEN = {"char": 1, "int8": 1, "uchar": 1, "uint8": 1, "short": 2, "int16": 2, "ushort": 2, "uint16": 2,
              "int": 4, "int32": 4, "uint": 4, "uint32": 4, "float": 4, "float32": 4, "double": 8, "float64": 8}


def ply_skalieren(pfad: Path, f: float) -> int:
    """Punkte einer PLY-Datei skalieren (Element ``vertex`` zuerst, Eigenschaften x, y, z als erste drei float). Andere
    Aufbauten bleiben unverändert (Rückgabe 0)."""
    import numpy as np

    roh = pfad.read_bytes()
    ende = roh.find(b"end_header")
    if not roh.startswith(b"ply") or ende < 0:
        return 0
    kopf_ende = roh.index(b"\n", ende) + 1
    kopf = roh[:kopf_ende].decode("ascii", errors="replace").splitlines()
    fmt = next((z.split()[1] for z in kopf if z.startswith("format ")), "")
    elemente: list[tuple[str, int, list[tuple[str, str]]]] = []
    for z in kopf:
        t = z.split()
        if not t:
            continue
        if t[0] == "element":
            elemente.append((t[1], int(t[2]), []))
        elif t[0] == "property" and elemente:
            if t[1] == "list":
                elemente[-1][2].append(("list", t[-1]))
            else:
                elemente[-1][2].append((t[1], t[2]))
    if not elemente or elemente[0][0] != "vertex":
        return 0
    _, n, props = elemente[0]
    if [p[1] for p in props[:3]] != ["x", "y", "z"] or any(p[0] not in ("float", "float32") for p in props[:3]):
        return 0
    if fmt == "binary_little_endian":
        if any(p[0] == "list" for p in props):
            return 0
        breite = sum(_PLY_TYPEN[p[0]] for p in props)
        daten = bytearray(roh)
        dt = np.dtype([("xyz", "<f4", 3), ("rest", f"V{breite - 12}")] if breite > 12 else [("xyz", "<f4", 3)])
        feld = np.frombuffer(daten, dtype=dt, count=n, offset=kopf_ende).copy()
        feld["xyz"] *= f
        daten[kopf_ende:kopf_ende + n * breite] = feld.tobytes()
        tmp = pfad.with_name(f".{pfad.name}.tmp")
        tmp.write_bytes(bytes(daten))
        os.replace(tmp, pfad)
        return n
    if fmt == "ascii":
        zeilen = roh[kopf_ende:].decode("ascii", errors="replace").splitlines()
        for i in range(min(n, len(zeilen))):
            t = zeilen[i].split()
            t[:3] = [f"{float(x) * f:.5f}" for x in t[:3]]
            zeilen[i] = " ".join(t)
        tmp = pfad.with_name(f".{pfad.name}.tmp")
        tmp.write_bytes(roh[:kopf_ende] + ("\n".join(zeilen) + "\n").encode("ascii"))
        os.replace(tmp, pfad)
        return n
    return 0


def _pose_skalieren(form: dict[str, Any], f: float) -> None:
    cv = form.get("opencv")
    if isinstance(cv, dict) and isinstance(cv.get("t"), list):
        cv["t"] = [float(x) * f for x in cv["t"]]
    if isinstance(form.get("position"), list):
        form["position"] = [float(x) * f for x in form["position"]]
    m = form.get("camera_to_world")
    if isinstance(m, list) and len(m) == 4 and all(isinstance(r, list) and len(r) == 4 for r in m):
        for r in range(3):  # zeilenweise 4 × 4: Verschiebung in der letzten Spalte
            m[r][3] = float(m[r][3]) * f


def capture_skalieren(cap: Path, f: float) -> list[str]:
    """Alle Dateien in ``capture/`` (siehe Modulkopf). Rückgabe: geänderte Dateien (Namen)."""
    geaendert: list[str] = []
    obj = cap / "netz_mm.obj"
    if obj.is_file():
        obj_skalieren(obj, f)
        geaendert.append(obj.name)
    for name in PLY_DATEIEN:
        p = cap / name
        if p.is_file() and ply_skalieren(p, f):
            geaendert.append(name)
    p = cap / "poses.json"
    if p.is_file():
        d = _json_lesen(p)
        for c in d.get("cameras") or []:
            if isinstance(c.get("aligned"), dict):
                _pose_skalieren(c["aligned"], f)
        d["massstab_faktor"] = round(float(d.get("massstab_faktor") or 1.0) * f, 6)
        _json_schreiben(p, d)
        geaendert.append(p.name)
    p = cap / "kameras.json"
    if p.is_file():
        d = _json_lesen(p)
        for b in d.get("bilder") or []:
            k = b.get("kamera") or {}
            if isinstance(k.get("t"), list):
                k["t"] = [float(x) * f for x in k["t"]]
            if isinstance(k.get("zentrum"), list):
                k["zentrum"] = [float(x) * f for x in k["zentrum"]]
        _json_schreiben(p, d)
        geaendert.append(p.name)
    p = cap / "bericht.json"
    if p.is_file():
        d = _json_lesen(p)
        for k in list(d):
            if re.search(r"_mm$", k) or k in ("pruefmasse",):
                d[k] = _zahl(d[k], f)
        d["massstab_faktor"] = round(float(d.get("massstab_faktor") or 1.0) * f, 6)
        d["massstab_bekannt"] = True
        _json_schreiben(p, d)
        geaendert.append(p.name)
    return geaendert


def messung_skalieren(mess: Path, f: float) -> bool:
    """``messung/messung.json``: gemessene Längen und Kameras mit; Werte aus model.py (``start``, ``fest``),
    Brennweite und Bildgrößen bleiben. Dazu das eingepasste Modell (``modell_eingepasst.npz``) für das Anlegen."""
    p = mess / "messung.json"
    if not p.is_file():
        return False
    d = _json_lesen(p)
    for k in ("masse", "sigma", "huelle", "teile"):
        if k in d:
            d[k] = _zahl(d[k], f)
    for b in d.get("bilder") or []:
        k = b.get("kamera") or {}
        for feld in ("t", "zentrum"):
            if isinstance(k.get(feld), list):
                k[feld] = [float(x) * f for x in k[feld]]
    for k in d.get("startkameras") or {}:
        sk = d["startkameras"][k]
        if isinstance(sk, dict) and isinstance(sk.get("t"), list):
            sk["t"] = [float(x) * f for x in sk["t"]]
    lage = (d.get("scan") or {}).get("lage")
    if isinstance(lage, dict) and isinstance(lage.get("b"), list):
        lage["b"] = [float(x) * f for x in lage["b"]]
    d["massstab_faktor"] = round(float(d.get("massstab_faktor") or 1.0) * f, 6)
    _json_schreiben(p, d)
    npz = mess / "modell_eingepasst.npz"
    if npz.is_file():
        import numpy as np

        try:
            with np.load(npz) as z:
                inhalt = {k: z[k] for k in z.files}
            if "V" in inhalt:
                inhalt["V"] = inhalt["V"] * f
                tmp = npz.with_name(".modell_eingepasst.tmp.npz")
                np.savez(tmp, **inhalt)
                os.replace(tmp, npz)
        except (OSError, ValueError):
            pass
    return True


def meta_skalieren(meta: dict[str, Any], f: float, eintrag: dict[str, Any]) -> dict[str, Any]:
    """``referenz.json``: Maße unter ``capture`` mit, ``massstab`` mit Faktor (über alle Schritte) und Verlauf."""
    cap = meta.get("capture")
    if isinstance(cap, dict):
        for k in ("huelle", "grundkoerper", "oberkante", "pruefmasse"):
            if k in cap:
                cap[k] = _zahl(cap[k], f)
        cap["massstab_bekannt"] = True
    m = dict(meta.get("massstab") or {})
    verlauf = list(m.get("verlauf") or [])
    verlauf.append({k: v for k, v in eintrag.items() if k != "verlauf"})
    m.update(eintrag)
    m["faktor"] = round(float((meta.get("massstab") or {}).get("faktor") or 1.0) * f, 6)
    m["verlauf"] = verlauf[-10:]
    meta["massstab"] = m
    lage = meta.get("lage")
    if isinstance(lage, dict) and meta.get("art") != "video":
        # Scan: Lage aus der (skalierten) Messung; Video: die Lage wird aus den Kameras neu bestimmt
        if isinstance(lage.get("b"), list):
            lage["b"] = [float(x) * f for x in lage["b"]]
    return meta


def ordner_skalieren(ordner: Path, f: float, *, mit_messung: bool) -> dict[str, Any]:
    geaendert = [f"{CAPTURE}/{n}" for n in capture_skalieren(ordner / CAPTURE, f)] if (ordner / CAPTURE).is_dir() \
        else []
    messung = mit_messung and messung_skalieren(ordner / MESSUNG, f)
    if messung:
        geaendert.append(f"{MESSUNG}/messung.json")
    return {"geaendert": geaendert, "messung": bool(messung)}
