"""Geometrie der Zukaufteile: Hersteller-STEP laden und prüfen, Einheiten und Achsen korrigieren, BREP-Zwischenspeicher,
Ersatzkörper, Skript-Geometrie und bd_warehouse.

Prüfung gegen die Hüllmaße aus dem Katalog (``masse`` bzw. ``ersatz``):

1. Einheit: Das Modell wird mit 1, 25,4 (Zoll), 10 (cm) und 1000 (m) skaliert verglichen (sortierte Kantenlängen); der
   Faktor mit der kleinsten Abweichung gilt. Ist er nicht 1, wird skaliert und das gemeldet.
2. Achsen: Liegt die Höhe ``h`` nicht in Z, aber in Y (oder X), war das Modell „Y oben“ gespeichert; es wird auf Z oben
   gedreht. Länge und Breite dürfen vertauscht sein (Hinweis, keine Drehung).
3. Abweichung: bis 12 % je Maß gilt als passend, bis 35 % mit Hinweis, darüber wird abgelehnt (mit ``erzwingen`` doch
   übernommen).

Der Zwischenspeicher ``<projekt>/zukauf/<id>/<datei>.brep`` mit ``.json`` (Baum mit Namen und Farben, Korrektur,
Prüfsumme der Quelle) spart das Einlesen großer STEP-Dateien bei jedem Lauf.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kevcad_kernel.zukauf.eintrag import ersatz_aus_masse, ersatz_huelle

CACHE_VERSION = 1
TOL_OK = 0.12
TOL_WARN = 0.35
GROB_FLAECHEN = 3000  # ab so vielen Flächen grob tessellieren
FAKTOREN = ((1.0, None), (25.4, "Zoll"), (10.0, "Zentimeter"), (1000.0, "Meter"))
ERSATZ_FARBE = "#AEB4BA"

_memo: dict[tuple[str, int, int], tuple[Any, dict[str, Any]]] = {}


class CadFehler(ValueError):
    """CAD-Datei passt nicht oder ist nicht lesbar (Meldung für Agent und Kevin)."""


@dataclass
class Pruefung:
    skala: float = 1.0
    drehung: str | None = None  # None | "y_oben" | "x_oben"
    abweichung: float = 0.0  # größte relative Abweichung nach der Korrektur
    modell: tuple[float, float, float] = (0.0, 0.0, 0.0)  # Hüllmaß wie gelesen
    korrigiert: tuple[float, float, float] = (0.0, 0.0, 0.0)  # Hüllmaß nach Korrektur
    soll: tuple[float, float, float] | None = None
    hinweise: list[str] = field(default_factory=list)
    ok: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"skala": self.skala, "drehung": self.drehung, "abweichung": round(self.abweichung, 4),
                "modell": [round(v, 3) for v in self.modell], "korrigiert": [round(v, 3) for v in self.korrigiert],
                "soll": [round(v, 3) for v in self.soll] if self.soll else None, "hinweise": list(self.hinweise),
                "ok": self.ok}


def _de(x: float) -> str:
    from kevcad_kernel.bom import de_num

    return de_num(x, 1)


def _dims(t: tuple[float, float, float]) -> str:
    return " × ".join(_de(v) for v in t) + " mm"


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-9)


def pruefen(modell: tuple[float, float, float], soll: tuple[float, float, float] | None,
            achsen_pruefen: bool = True) -> Pruefung:
    """Einheit, Achsen und Abweichung des Hüllmaßes ``modell`` (x, y, z) gegen ``soll`` (siehe Moduldoku)."""
    p = Pruefung(modell=tuple(modell), korrigiert=tuple(modell), soll=tuple(soll) if soll else None)
    if not soll or min(soll) <= 0 or min(modell) <= 0:
        if not soll:
            p.hinweise.append("Keine Maße im Katalog: Hüllmaß nicht geprüft")
        return p
    s_sorted = sorted(soll)
    best = None
    for f, name in FAKTOREN:
        m_sorted = sorted(v * f for v in modell)
        err = max(_rel(a, b) for a, b in zip(m_sorted, s_sorted))
        if best is None or err < best[0] - 1e-9:
            best = (err, f, name)
    assert best is not None
    err, f, name = best
    p.skala = f
    scaled = tuple(v * f for v in modell)
    if name:
        p.hinweise.append(f"Modell war in {name} gespeichert (Hüllmaß {_dims(tuple(modell))} gelesen): mit Faktor "
                          f"{_de(f)} auf mm umgerechnet")
    korr = scaled
    if achsen_pruefen:
        def score(d: tuple[float, float, float]) -> float:
            ez = _rel(d[2], soll[2])
            exy = min(max(_rel(d[0], soll[0]), _rel(d[1], soll[1])), max(_rel(d[0], soll[1]), _rel(d[1], soll[0])))
            return max(ez, exy)

        options = [(None, scaled), ("y_oben", (scaled[0], scaled[2], scaled[1])),
                   ("x_oben", (scaled[2], scaled[1], scaled[0]))]
        base = score(scaled)
        alt = min(options[1:], key=lambda o: score(o[1]))
        if base > TOL_OK and score(alt[1]) < base - 0.05:
            p.drehung, korr = alt
            achse = "Y" if alt[0] == "y_oben" else "X"
            p.hinweise.append(f"Modell war mit {achse} nach oben gespeichert: auf Z nach oben gedreht (Höhe "
                              f"{_de(soll[2])} mm liegt jetzt in Z)")
        same = max(_rel(korr[0], soll[0]), _rel(korr[1], soll[1]))
        swapped = max(_rel(korr[0], soll[1]), _rel(korr[1], soll[0]))
        if swapped + 0.05 < same and abs(soll[0] - soll[1]) > 1e-6:
            p.hinweise.append("Länge liegt entlang Y, Breite entlang X (anders als im Katalog l × b); beim Einbauen "
                              "drehen oder einbaupunkt mit x_richtung setzen")
        p.abweichung = score(korr)
    else:
        p.abweichung = err
    p.korrigiert = korr
    if p.abweichung > TOL_WARN:
        p.ok = False
    elif p.abweichung > TOL_OK:
        p.hinweise.append(f"Hüllmaß {_dims(korr)} weicht bis {round(p.abweichung * 100):d} % von den Katalogmaßen "
                          f"{_dims(soll)} ab: Maße im Katalog prüfen")
    return p


def ablehnung(p: Pruefung, name: str) -> str:
    soll = p.soll or (0, 0, 0)
    return (f"CAD für {name} passt nicht: Hüllmaß {_dims(p.modell)} gegen {_dims(soll)} laut Katalog (Abweichung "
            f"{round(p.abweichung * 100):d} %, auch nicht in Zoll, cm oder m). Falsche Datei, falsches Teil der "
            "Baugruppe oder falsche Maße im Katalog? Maße korrigieren oder mit erzwingen=True übernehmen.")


# ---------------------------------------------------------------------------------------------------------------------
# Laden, korrigieren, zwischenspeichern


def _bbox(shape: Any) -> tuple[float, float, float]:
    bb = shape.bounding_box()
    return (float(bb.size.X), float(bb.size.Y), float(bb.size.Z))


def sha1_datei(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def step_lesen(path: Path):
    """STEP mit Namen, Farben und Baugruppe (build123d ``import_step``)."""
    from build123d import import_step

    if not path.is_file():
        raise CadFehler(f"CAD-Datei {path} fehlt")
    try:
        shape = import_step(str(path))
    except Exception as exc:  # noqa: BLE001
        raise CadFehler(f"{path.name} ist keine lesbare STEP-Datei ({type(exc).__name__}: {exc})") from exc
    if shape is None or getattr(shape, "wrapped", None) is None or shape.wrapped.IsNull():
        raise CadFehler(f"{path.name} enthält keine Geometrie")
    if not shape.solids() and not shape.faces():
        raise CadFehler(f"{path.name} enthält keine Körper oder Flächen")
    return shape


def korrigieren(shape: Any, p: Pruefung):
    """Skalieren und auf Z oben drehen, Baum mit Namen und Farben bleibt erhalten."""
    from build123d import Rot
    from OCP.gp import gp_Pnt, gp_Trsf

    from kevcad_kernel.baum import transformieren

    if abs(p.skala - 1.0) > 1e-12:
        trsf = gp_Trsf()
        trsf.SetScale(gp_Pnt(0, 0, 0), p.skala)
        shape = transformieren(shape, trsf=trsf)
    if p.drehung == "y_oben":
        shape = transformieren(shape, location=Rot(90, 0, 0))
    elif p.drehung == "x_oben":
        shape = transformieren(shape, location=Rot(0, -90, 0))
    return shape


def _flaechen(shape: Any) -> int:
    try:
        return len(shape.faces())
    except Exception:  # noqa: BLE001
        return 0


def cache_pfade(cache_dir: Path, quelle: Path) -> tuple[Path, Path]:
    stem = quelle.stem
    return cache_dir / f"{stem}.brep", cache_dir / f"{stem}.json"


def importieren(quelle: Path, cache_dir: Path, soll: tuple[float, float, float] | None, *, name: str = "",
                erzwingen: bool = False, achsen_pruefen: bool = True) -> tuple[Any, dict[str, Any]]:
    """Hersteller-CAD laden (Zwischenspeicher, sonst STEP), prüfen und korrigieren. Rückgabe (Form, Info) mit Info
    ``{"pruefung", "flaechen", "grob", "cache": bool, "brep", "hinweise"}``. Passt das Modell nicht: CadFehler."""
    from build123d import import_brep

    from kevcad_kernel.baum import baum_bauen, baum_meta

    quelle = Path(quelle)
    if not quelle.is_file():
        raise CadFehler(f"CAD-Datei {quelle} fehlt")
    brep, meta_path = cache_pfade(Path(cache_dir), quelle)
    st = quelle.stat()
    key = (str(quelle.resolve()), st.st_mtime_ns, st.st_size)
    soll_key = [round(v, 3) for v in soll] if soll else None
    if key in _memo:
        wrapped, meta = _memo[key]
        if meta.get("soll") == soll_key and (meta["pruefung"]["ok"] or meta.get("erzwungen") or erzwingen):
            shape = baum_bauen(wrapped, meta.get("baum"))
            return shape, {**_info(meta), "cache": True}
    meta = None
    if brep.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = None
        if meta is not None and (meta.get("version") != CACHE_VERSION or meta.get("groesse") != st.st_size
                                 or meta.get("soll") != soll_key or meta.get("sha1") != sha1_datei(quelle)):
            meta = None
    if meta is not None and (meta["pruefung"]["ok"] or meta.get("erzwungen") or erzwingen):
        try:
            raw = import_brep(str(brep))
            _memo[key] = (raw.wrapped, meta)
            return baum_bauen(raw.wrapped, meta.get("baum")), {**_info(meta), "cache": True}
        except Exception:  # noqa: BLE001 - Zwischenspeicher kaputt: neu einlesen
            meta = None
    shape = step_lesen(quelle)
    p = pruefen(_bbox(shape), soll, achsen_pruefen=achsen_pruefen)
    if not p.ok and not erzwingen:
        raise CadFehler(ablehnung(p, name or quelle.name))
    if not p.ok:
        p.hinweise.append(f"Trotz {round(p.abweichung * 100):d} % Abweichung übernommen (erzwingen)")
    shape = korrigieren(shape, p)
    n = _flaechen(shape)
    meta = {"version": CACHE_VERSION, "quelle": quelle.name, "sha1": sha1_datei(quelle), "groesse": st.st_size,
            "soll": soll_key, "pruefung": p.as_dict(), "erzwungen": bool(erzwingen and not p.ok), "flaechen": n,
            "grob": n > GROB_FLAECHEN, "baum": baum_meta(shape)}
    try:
        from build123d import export_brep

        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        export_brep(shape, str(brep))
        tmp = meta_path.with_name(f".{meta_path.name}.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(meta_path)
        meta["brep"] = str(brep)
    except Exception as exc:  # noqa: BLE001 - ohne Zwischenspeicher geht es auch
        meta["hinweise_cache"] = f"Zwischenspeicher nicht geschrieben: {exc}"
    _memo[key] = (shape.wrapped, meta)
    return shape, {**_info(meta), "cache": False}


def _info(meta: dict[str, Any]) -> dict[str, Any]:
    out = {"pruefung": meta.get("pruefung"), "flaechen": meta.get("flaechen"), "grob": bool(meta.get("grob")),
           "hinweise": list((meta.get("pruefung") or {}).get("hinweise") or [])}
    if meta.get("hinweise_cache"):
        out["hinweise"].append(meta["hinweise_cache"])
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Ersatzkörper, Skript, bd_warehouse


def ersatzkoerper(entry: dict[str, Any]):
    """Quader oder Zylinder aus ``ersatz`` (sonst aus ``masse``): Unterseite mittig auf dem Ursprung, Z oben;
    Zylinder mit ``achse`` x oder y liegen auf z = 0."""
    from build123d import Align, Box, Cylinder, Rot

    ers = entry.get("ersatz") if isinstance(entry.get("ersatz"), dict) else ersatz_aus_masse(entry.get("masse") or {})
    if not ers:
        raise CadFehler(f"Zukaufteil {entry.get('id')!r}: weder ersatz noch masse im Katalog, kein Ersatzkörper möglich")
    dims = ersatz_huelle(ers)
    if dims is None:
        raise CadFehler(f"Zukaufteil {entry.get('id')!r}: ersatz.masse unvollständig")
    boden = (Align.CENTER, Align.CENTER, Align.MIN)
    if ers.get("form") == "quader":
        return Box(*dims, align=boden)
    m = ers.get("masse") or {}
    d = float(m.get("d"))
    hoehe = float(m.get("l") or m.get("h") or d)
    achse = ers.get("achse") or "z"
    if achse == "z":
        return Cylinder(d / 2, hoehe, align=boden)
    zyl = Cylinder(d / 2, hoehe)
    lage = Rot(0, 90, 0) if achse == "x" else Rot(90, 0, 0)
    from build123d import Pos

    return Pos(0, 0, d / 2) * (lage * zyl)


def _modul_aus_datei(path: Path):
    """Python-Datei als Modul laden (gleiches Objekt, wenn sie schon unter ihrem Namen importiert ist)."""
    name = path.stem
    mod = sys.modules.get(name)
    if mod is not None and getattr(mod, "__file__", None) and Path(mod.__file__).resolve() == path.resolve():
        return mod
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise CadFehler(f"{path} lässt sich nicht als Python-Modul laden")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def skript_form(entry: dict[str, Any], base_dir: Path, kwargs: dict[str, Any] | None = None):
    """Form aus ``cad.funktion`` in ``cad.modul`` (importierbar) bzw. ``cad.datei`` (relativ zur Katalogdatei). Die
    Funktion darf eine Form oder (Form, Bezugspunkte) liefern; Bezugspunkte werden zurückgegeben."""
    cad = entry.get("cad") or {}
    fname = str(cad.get("funktion") or "").strip()
    if cad.get("datei"):
        path = (Path(base_dir) / str(cad["datei"])).resolve()
        if not path.is_file():
            raise CadFehler(f"Zukaufteil {entry.get('id')!r}: Skript {path} fehlt")
        mod = _modul_aus_datei(path)
    else:
        try:
            mod = importlib.import_module(str(cad.get("modul")))
        except ImportError as exc:
            raise CadFehler(f"Zukaufteil {entry.get('id')!r}: Modul {cad.get('modul')!r} nicht gefunden ({exc}); "
                            "Datei in den Projektordner legen oder cad.datei angeben") from exc
    fn = getattr(mod, fname, None)
    if not callable(fn):
        names = [n for n in dir(mod) if callable(getattr(mod, n)) and not n.startswith("_")]
        import difflib

        close = difflib.get_close_matches(fname, names, n=3, cutoff=0.5)
        raise CadFehler(f"Zukaufteil {entry.get('id')!r}: Funktion {fname!r} gibt es in {mod.__name__} nicht"
                        + (f"; meinten Sie {', '.join(close)}?" if close else ""))
    res = fn(**(kwargs or {}))
    punkte = None
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict):
        res, punkte = res
    from build123d import BuildPart, Shape

    if isinstance(res, BuildPart):
        res = res.part
    if not isinstance(res, Shape):
        raise CadFehler(f"Zukaufteil {entry.get('id')!r}: {fname}() muss eine build123d-Form liefern, nicht "
                        f"{type(res).__name__}")
    return res, punkte


def bd_warehouse_form(entry: dict[str, Any]):
    """Teil aus bd_warehouse, z. B. ``{"quelle": "bd_warehouse", "klasse": "bearing.SingleRowDeepGrooveBallBearing",
    "parameter": {"size": "M8-22-7", "bearing_type": "SKT"}}``."""
    cad = entry.get("cad") or {}
    klasse = str(cad.get("klasse"))
    modul, _, cls_name = klasse.rpartition(".")
    candidates = [f"bd_warehouse.{modul}"] if modul else ["bd_warehouse.fastener", "bd_warehouse.bearing",
                                                          "bd_warehouse.flange", "bd_warehouse.pipe"]
    for name in candidates:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        cls = getattr(mod, cls_name, None)
        if cls is not None:
            try:
                return cls(**dict(cad.get("parameter") or {}))
            except Exception as exc:  # noqa: BLE001
                raise CadFehler(f"Zukaufteil {entry.get('id')!r}: {klasse}({cad.get('parameter')}) geht nicht: "
                                f"{exc}") from exc
    raise CadFehler(f"Zukaufteil {entry.get('id')!r}: Klasse {klasse!r} gibt es in bd_warehouse nicht")


def huellmass(shape: Any) -> tuple[float, float, float]:
    return _bbox(shape)



def einbau_lage(shape: Any, entry: dict[str, Any]):
    """Location, die den Einbaupunkt (Standard: Mitte der Unterseite des Hüllquaders) auf den Ursprung legt."""
    from build123d import Pos

    from kevcad_kernel.bezugspunkte import einbau

    if isinstance(entry.get("einbaupunkt"), dict):
        return einbau(entry["einbaupunkt"])
    bb = shape.bounding_box()
    c = bb.center()
    return Pos(-float(c.X), -float(c.Y), -float(bb.min.Z))

