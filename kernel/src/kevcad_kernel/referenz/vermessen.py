"""Ablauf von ``referenz_vermessen``: Varianten von model.py bauen (Kernel-Umgebung, eigener Prozess), dann fotomess
(eigene uv-Umgebung, eigener Prozess) und das Ergebnis für Agent und App aufbereiten.

Warum zwei Prozesse: fotomess bringt OpenCV, moderngl, scipy und die Swift-Hilfe für Apple Vision mit und hat seine
eigene Umgebung (``fotomess/.venv``); model.py dagegen braucht die API ``kevcad`` mit Lager und Katalog aus der
Kernel-Umgebung. Der Kernel baut deshalb die Netze (``varianten``), fotomess rechnet daraus Ableitungen, Kameras, Maße
und Unsicherheit. Beide Prozesse melden ihren Fortschritt als JSON-Zeilen.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kevcad_kernel.referenz import ablage, netz
from kevcad_kernel.referenz.ablage import ReferenzFehler

Melde = Callable[[float, str], None]
# Gewichte für den Gesamtbalken: Varianten bauen, Bilder, Einpassen, Unsicherheit, Kontrollbilder
PHASEN = {"varianten": (0.0, 0.12), "modell": (0.12, 0.06), "bilder": (0.18, 0.37), "einpassen": (0.55, 0.3),
          "unsicherheit": (0.85, 0.1), "kontrolle": (0.95, 0.05)}
MASKEN_OPTIONEN = ("maske", "farbe_hsv", "ausschluss_hsv", "gehaeuse", "umkreis")


def fotomess_cache() -> Path:
    return Path.home() / "Library" / "Caches" / "de.upvis.kevcad" / "fotomess"


def _zeilen(cmd: list[str], *, env: dict[str, str] | None = None, cwd: str | None = None,
            bei_zeile: Callable[[dict[str, Any]], None] | None = None, timeout_s: float = 1800) -> tuple[int, list, str]:
    """Prozess starten, stdout zeilenweise als JSON lesen. Rückgabe (Exitcode, Ereignisse, stderr-Ende)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=env,
                            cwd=cwd)
    fehler: list[str] = []

    def lies_err() -> None:
        assert proc.stderr is not None
        for z in proc.stderr:
            fehler.append(z.rstrip())
            del fehler[:-60]

    t = threading.Thread(target=lies_err, daemon=True)
    t.start()
    ereignisse = []
    tot = threading.Timer(timeout_s, proc.kill)
    tot.start()
    try:
        assert proc.stdout is not None
        for z in proc.stdout:
            z = z.strip()
            if not z.startswith("{"):
                continue
            try:
                e = json.loads(z)
            except json.JSONDecodeError:
                continue
            ereignisse.append(e)
            if bei_zeile is not None:
                bei_zeile(e)
        code = proc.wait()
    finally:
        tot.cancel()
    t.join(2)
    return code, ereignisse, "\n".join(fehler[-12:])


def varianten_bauen(*, modell: Path, frei: list[str], bekannt: dict[str, float], ausgabe: Path,
                    katalog: dict[str, Any], inventar_regel: bool) -> dict[str, Any]:
    auftrag = {"modell": str(modell), "params": dict(bekannt), "frei": list(frei), "ausgabe": str(ausgabe),
               "catalog": katalog, "inventar_regel": inventar_regel}
    datei = ausgabe.with_name("varianten-auftrag.json")
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(json.dumps(auftrag, ensure_ascii=False), encoding="utf-8")
    code, ereignisse, err = _zeilen([sys.executable, "-m", "kevcad_kernel.referenz.varianten", str(datei)],
                                    cwd=str(modell.parent), timeout_s=900)
    erg = ereignisse[-1] if ereignisse else None
    if not erg:
        raise ReferenzFehler(f"Modellvarianten nicht gebaut (Code {code}): {err[-600:]}")
    return erg


def speicher_frei() -> int | None:
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=20).stdout
        m = re.search(r"free percentage:\s*(\d+)%", out)
        return int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def warte_auf_speicher(melde: Melde | None, anteil: float, min_prozent: int = 25, hoechstens_s: float = 600) -> None:
    """Rücksicht auf den 16-GB-Mac: speicherhungrige Läufe erst ab 25 % freiem Speicher (höchstens 10 min warten)."""
    t0 = time.monotonic()
    while True:
        frei = speicher_frei()
        if frei is None or frei >= min_prozent or time.monotonic() - t0 > hoechstens_s:
            return
        if melde:
            melde(anteil, f"wartet auf freien Arbeitsspeicher ({frei} % frei)")
        time.sleep(10)


def fotomess_lauf(auftrag: dict[str, Any], ablage_ordner: Path, melde: Melde) -> Path:
    fm = ablage.fotomess_ordner()
    if fm is None:
        raise ReferenzFehler("fotomess fehlt: im Repo `cd fotomess && uv sync` ausführen (das installierte Kev CAD "
                             "bringt es unter install/fotomess mit).")
    datei = ablage_ordner / "fotomess-auftrag.json"
    datei.write_text(json.dumps(auftrag, ensure_ascii=False, indent=1), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"))}
    env.setdefault("FOTOMESS_CACHE", str(fotomess_cache()))
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")  # ffmpeg, ffprobe

    def zeile(e: dict[str, Any]) -> None:
        if e.get("event") == "progress":
            start, breite = PHASEN.get(str(e.get("phase")), (0.2, 0.0))
            melde(start + breite * float(e.get("fraction") or 0), str(e.get("text") or ""))

    code, ereignisse, err = _zeilen([str(fm / ".venv" / "bin" / "python"), "-m", "fotomess.kevcad", str(datei)],
                                    env=env, cwd=str(fm), bei_zeile=zeile, timeout_s=1800)
    fertig = next((e for e in reversed(ereignisse) if e.get("event") in ("done", "error")), None)
    if fertig is None or fertig.get("event") == "error" or code != 0:
        msg = (fertig or {}).get("message") or f"fotomess endete mit Code {code}"
        raise ReferenzFehler(f"Vermessen fehlgeschlagen: {msg}" + (f"\n{err[-800:]}" if err and not fertig else ""))
    return Path(str(fertig["ergebnis"]))


def _num(x: Any, nd: int = 2) -> Any:
    if isinstance(x, float):
        return round(x, nd) if math.isfinite(x) else None
    return x


def sauber(v: Any) -> Any:
    """NaN und Unendlich zu None (JSON für die App)."""
    if isinstance(v, dict):
        return {k: sauber(x) for k, x in v.items()}
    if isinstance(v, list):
        return [sauber(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def de(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def ergebnis_aus(messung: dict[str, Any], referenz: str, varianten: dict[str, Any] | None = None,
                 ordner: Path | None = None) -> dict[str, Any]:
    """REF_RESULT (ohne type/seq) aus messung.json: Maße mit Sigma, Hülle, Grundkörper, Empfehlungen."""
    masse = []
    for k in messung.get("frei") or []:
        w = float(messung["masse"][k])
        s = float((messung.get("sigma") or {}).get(k) or 0)
        st = (messung.get("start") or {}).get(k)
        masse.append({"name": k, "wert": round(w, 2), "sigma": round(s, 2), "start": _num(st),
                      "aenderung": round(w - float(st), 2) if st is not None else None})
    teile = messung.get("teile") or {}
    grund = None
    if teile:
        # Grundkörper: das Teil mit dem größten Hüllvolumen (bei der Scarlett das Gehäuse ohne Knöpfe und Füße)
        name = max(teile, key=lambda n: math.prod(max(g, 1e-3) for g in teile[n]["groesse"]))
        grund = {"teil": name, **teile[name]}
    empf = []
    nm = messung.get("nachmessen") or []
    if nm and nm[0].get("anteil") is not None:
        a = nm[0]
        empf.append({"art": "nachmessen", "mass": a["mass"], "anteil": _num(a["anteil"], 3),
                     "text": f"Von Hand nachmessen: {a['mass']} (die Unsicherheit aller Maße sinkt auf "
                             f"{a['anteil'] * 100:.0f} %)"})
    au = messung.get("aufnahme") or []
    if au and au[0].get("anteil") is not None:
        a = au[0]
        gewinn = (1 - a["anteil"]) * 100
        text = (f"Zusatzaufnahme {a['text']}: senkt die Unsicherheit auf {a['anteil'] * 100:.0f} %" if gewinn >= 15
                else f"Weitere Aufnahmen bringen wenig (am meisten {a['text']}: {gewinn:.0f} %)")
        empf.append({"art": "aufnahme", "azimut": a.get("azimut"), "hoehe": a.get("hoehe"),
                     "anteil": _num(a["anteil"], 3), "text": text})
    for m in masse:
        if m["sigma"] > max(2.0, 0.05 * abs(m["wert"])):
            empf.append({"art": "unsicher", "mass": m["name"],
                         "text": f"{m['name']} ist unsicher (± {de(m['sigma'])} mm): nachmessen oder mehr Ansichten"})
    if messung.get("verworfen"):
        empf.append({"art": "verworfen", "text": f"{len(messung['verworfen'])} Bild(er) passten nicht und sind "
                                                 f"verworfen: {', '.join(messung['verworfen'])}"})
    bilder = [b for b in messung.get("bilder") or [] if not b.get("verworfen")]
    iou = [b["iou"] for b in bilder if b.get("iou") is not None]
    out = {"referenz": referenz, "stand": messung.get("stand"), "masse": masse,
           "bekannt": {k: _num(v) for k, v in (messung.get("fest") or {}).items()
                       if varianten is None or k in (varianten.get("bekannt") or {})},
           "huelle": messung.get("huelle"), "grundkoerper": grund, "teile": teile,
           "brennweite_px": _num(messung.get("brennweite_px"), 1), "bilder": len(bilder),
           "verworfen": list(messung.get("verworfen") or []), "ueberdeckung": _num(sum(iou) / len(iou), 4) if iou
           else None, "empfehlungen": empf, "zeiten": messung.get("zeiten"), "dauer_s": messung.get("dauer_s"),
           "warnungen": list(messung.get("warnungen") or []) + list((varianten or {}).get("warnungen") or []),
           "kontrollbilder": [str(ordner / b["kontrolle"]) if ordner is not None else b["kontrolle"]
                              for b in bilder if b.get("kontrolle")]}
    return sauber(out)


def fotos_aus_messung(messung: dict[str, Any], ordner: Path) -> list[dict[str, Any]]:
    """REF_PHOTOS.fotos (Satz ``messung``): Bilder in Arbeitsgröße, Kamera auf diese Größe umgerechnet."""
    aw, ah = (messung.get("arbeit") or [None, None])[:2]
    out = []
    for b in messung.get("bilder") or []:
        if b.get("verworfen") or not b.get("kamera"):
            continue
        k = b["kamera"]
        kam = {"R": k["R"], "t": k["t"], "f": float(k["f"]), "cx": float(k["cx"]), "cy": float(k["cy"]),
               "w": int(k["w"]), "h": int(k["h"])}
        if aw and ah:
            kam = netz.skaliert(kam, int(aw), int(ah))
        out.append({"name": b["name"], "bild": str(ordner / b["datei"]),
                    "maske": str(ordner / b["maske"]) if b.get("maske") else None,
                    "kontrolle": str(ordner / b["kontrolle"]) if b.get("kontrolle") else None,
                    "zeit": b.get("zeit"), "iou": _num(b.get("iou"), 4),
                    "kamera": {k2: kam[k2] for k2 in ("R", "t", "f", "cx", "cy", "w", "h")}})
    return out


def fotos_aus_capture(posen: list[dict[str, Any]], lage: dict[str, Any] | None) -> list[dict[str, Any]]:
    """REF_PHOTOS.fotos (Satz ``capture``) aus poses.json, mit der Lage des Netzes bewegt."""
    import numpy as np

    out = []
    for p in posen:
        k = p["kamera"]
        if lage is not None:
            k = netz.bewegt(k, np.asarray(lage["A"], float), np.asarray(lage["b"], float))
        out.append({"name": p["name"], "bild": p["bild"], "maske": None, "kontrolle": None, "zeit": p.get("zeit"),
                    "iou": None, "kamera": {k2: k[k2] for k2 in ("R", "t", "f", "cx", "cy", "w", "h")}})
    return out


def auftrag_fotomess(*, varianten: dict[str, Any], quelle: dict[str, Any], ablage_ordner: Path, bilder: int,
                     optionen: dict[str, Any]) -> dict[str, Any]:
    """Auftrag für fotomess.kevcad aus Quelle, Messmodell (Vorgaben aus model.py) und Werkzeugangaben."""
    mm = dict(varianten.get("messmodell") or {})
    maske = dict(mm.get("maske") or {})
    auftrag: dict[str, Any] = {"varianten": varianten["datei"], "ablage": str(ablage_ordner), "bilder": int(bilder),
                               "arbeit": 1920, "frei": varianten.get("frei"), "vorgaben": mm.get("vorgaben") or {},
                               "grenzen": mm.get("grenzen") or {}, "hoehen": mm.get("hoehen"),
                               "kopfueber": mm.get("kopfueber", False), "kb_brennweite": mm.get("kb_brennweite"),
                               "kanten_gewicht": mm.get("kanten_gewicht"), "jackknife": True}
    for k in MASKEN_OPTIONEN:
        if k in maske:
            auftrag[k] = maske[k]
    auftrag.update(quelle)
    for k, v in (optionen or {}).items():
        if v is not None:
            if k in ("vorgaben", "grenzen"):
                auftrag[k] = {**auftrag.get(k, {}), **v}
            else:
                auftrag[k] = v
    return auftrag
