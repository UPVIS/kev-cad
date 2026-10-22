"""Welches Filament die Druckvorschau annimmt (Strang „Druckexport 2“, 22.10.2026; DRUCKVORSCHAU.md „Filamente und
Presets“).

Für den **Druckexport** wählt Kevin das Filament selbst (``druck_export(filament=…)``, sonst Rückfrage). Die
**Druckvorschau** schätzt vorher mit einem angenommenen Filament und zeigt an, welches sie nimmt. Reihenfolge je
Material (die erste Stufe mit einem Filament, dessen Preset sich auflösen lässt, gewinnt; verworfene Angaben stehen
als Hinweis im Ergebnis):

1. ``projekt``: ``kevcad.json`` → ``druck.filament.<material>``: id eines Filaments der Liste (``druck/filamente.py``)
   oder, wie bisher, ein Bambu-Studio-Profilname.
2. ``zuletzt``: das zuletzt für dieses Projekt exportierte Filament des Materials (``druck.json`` → ``filament``).
3. ``spule``: eine Spule dieses Materials im Bestand des Projekts (``bestand.json``, Verweis ``filament`` oder
   Hersteller und Name), in der Reihenfolge, in der sie verbraucht werden.
4. ``standard``: das erste Filament der Liste mit diesem Material.
5. ``system``: ein Systemprofil, das zum Drucker passt (``slicer.filament_name``), wenn die Liste keins hat.

Ohne Bambu Studio (Mac mini) lässt sich nichts prüfen; die Angaben gelten dann so, wie sie sind.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from kevcad_kernel.druck import filamente as fl
from kevcad_kernel.druck import slicer as sl

QUELLEN = ("projekt", "zuletzt", "spule", "standard", "system", "kevin")


@dataclass
class FilamentWahl:
    material: str
    profil: str | None                   # Name im 3MF: Preset-Name oder Bambu-Profil
    quelle: str                          # projekt | zuletzt | spule | standard | system | kevin | keins
    detail: str = ""
    filament: str | None = None          # id in der Filamentliste
    basis: str | None = None             # Bambu-Studio-Profil, von dem das Preset erbt
    preset: dict[str, Any] | None = None  # für slicer.filament_daten
    abweichungen: list[dict[str, Any]] = field(default_factory=list)
    temperaturen: dict[str, Any] | None = None
    verworfen: list[str] = field(default_factory=list)

    @property
    def slicer_filament(self) -> str | dict[str, Any] | None:
        """Was die Slicer-Funktionen bekommen: das Preset, sonst der Profilname."""
        return self.preset or self.profil

    def als_dict(self) -> dict[str, Any]:
        return {"material": self.material, "profil": self.profil, "quelle": self.quelle, "detail": self.detail,
                "filament": self.filament, "basis": self.basis, "preset": self.preset,
                "abweichungen": list(self.abweichungen), "temperaturen": self.temperaturen,
                "verworfen": list(self.verworfen)}


# ---------------------------------------------------------------------------------------------------------------------
# Temperaturen


def _erster(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def _zahl(v: Any) -> float | None:
    try:
        return float(str(_erster(v)).rstrip("%"))
    except (TypeError, ValueError):
        return None


def temperaturen(filament: str | dict[str, Any] | None, platte: str | None = None) -> dict[str, Any] | None:
    """Düse, Platte, Lüfter und Tempo aus dem aufgelösten Profil bzw. Preset: {"duese", "duese_erste_schicht",
    "duese_bereich", "platte", "platte_erste_schicht", "platte_name", "luefter", "max_volumen", "hersteller"}."""
    if not filament:
        return None
    try:
        d = sl.filament_daten(filament)
    except (sl.SlicerFehler, OSError, ValueError):
        return None
    try:
        pname = sl.platte_name(platte)
    except sl.SlicerFehler:
        pname = sl.PLATTE_STANDARD
    key = sl.PLATTEN.get(pname, "textured_plate_temp")
    out = {"duese": _zahl(d.get("nozzle_temperature")),
           "duese_erste_schicht": _zahl(d.get("nozzle_temperature_initial_layer")),
           "duese_bereich": [_zahl(d.get("nozzle_temperature_range_low")),
                             _zahl(d.get("nozzle_temperature_range_high"))],
           "platte": _zahl(d.get(key)), "platte_erste_schicht": _zahl(d.get(key + "_initial_layer")),
           "platte_name": pname,
           "luefter": [_zahl(d.get("fan_min_speed")), _zahl(d.get("fan_max_speed"))],
           "max_volumen": _zahl(d.get("filament_max_volumetric_speed"))}
    vendor = _erster(d.get("filament_vendor"))
    if vendor:
        out["hersteller"] = str(vendor)
    return out


def temperaturen_text(t: dict[str, Any] | None) -> str:
    """„Düse 255 °C, Texturplatte 80 °C“ (erste Schicht, wenn anders)."""
    if not t:
        return ""

    def g(x: Any) -> str:
        return f"{x:g}" if isinstance(x, (int, float)) else "?"

    platte = {"Textured PEI Plate": "Texturplatte", "High Temp Plate": "glatte Platte", "Cool Plate": "Cool Plate",
              "Engineering Plate": "Engineering-Platte", "Supertack Plate": "Supertack-Platte"}
    s = f"Düse {g(t.get('duese'))} °C"
    if t.get("duese_erste_schicht") not in (None, t.get("duese")):
        s += f" (erste Schicht {g(t.get('duese_erste_schicht'))})"
    s += f", {platte.get(str(t.get('platte_name')), t.get('platte_name'))} {g(t.get('platte'))} °C"
    if t.get("platte_erste_schicht") not in (None, t.get("platte")):
        s += f" (erste Schicht {g(t.get('platte_erste_schicht'))})"
    return s


# ---------------------------------------------------------------------------------------------------------------------
# Bambu-Profil zu Hersteller und Produkt (Vorschlag für filament_define)


_KAND: dict[tuple[str, str, str], list[tuple[str, frozenset[str], str, bool]]] = {}  # je Profilstand
_KAND_LOCK = threading.Lock()


def _woerter(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[0-9a-zäöüß]+(?:[+\-][0-9a-zäöüß]+)*", str(text or "").lower()))


def _kandidaten(material: str, drucker: str) -> list[tuple[str, frozenset[str], str, bool]]:
    """Alle Filamentprofile (System und Kevins) des Materialtyps, die zum Drucker passen: (Name, Wörter des Namens vor
    „ @“, Hersteller klein, Benutzerprofil)."""
    key = (material, drucker, str(sl.system_ordner()) + "|" + "|".join(str(o) for o in sl.benutzer_ordner()))
    with _KAND_LOCK:
        if key in _KAND:
            return _KAND[key]
    benutzer = [str(o) for o in sl.benutzer_ordner()]
    out = []
    for name in sl._filament_suche(material, drucker):
        try:
            d = sl.profil("filament", name)
        except (sl.SlicerFehler, OSError, ValueError):
            continue
        pfad = sl._index().get(("filament", name))
        user = pfad is not None and any(str(pfad).startswith(b) for b in benutzer)
        out.append((name, _woerter(name.split(" @")[0]), str(_erster(d.get("filament_vendor")) or "").lower(), user))
    with _KAND_LOCK:
        _KAND[key] = out
    return out


def cache_leeren() -> None:
    with _KAND_LOCK:
        _KAND.clear()


def basis_vorschlag(hersteller: str | None, produkt: str | None, material: str,
                    drucker: str = "p1p-0.4") -> str | None:
    """Bambu-Studio-Profil zu Hersteller und Produkt: alle Wörter des Profilnamens vor „ @“ stehen in Hersteller und
    Produkt; das genauere gewinnt, dann das des Herstellers (``filament_vendor``), dann ein Systemprofil vor einer
    Kopie Kevins. Nennt nur der Hersteller eine eindeutige Profilreihe, gilt die."""
    if not sl.system_ordner().is_dir():
        return None
    h = str(hersteller or "").strip()
    w = _woerter(f"{h} {produkt or ''}")
    if not w:
        return None
    kand = _kandidaten(str(material).lower(), drucker)
    beste: tuple | None = None
    for name, bw, vendor, user in kand:
        if not bw or not bw <= w:
            continue
        rang = (len(bw), bool(h) and vendor == h.lower(), not user, "@BBL P1P" in name and "nozzle" not in name,
                -len(name))
        if beste is None or rang > beste[0]:
            beste = (rang, name)
    if beste is not None:
        return beste[1]
    if h:
        eigene = [(name, bw) for name, bw, vendor, user in kand if vendor == h.lower() and not user]
        if len({bw for _, bw in eigene}) == 1:
            return sorted(eigene, key=lambda x: ("@BBL P1P" not in x[0] or "nozzle" in x[0], x[0]))[0][0]
    return None


# ---------------------------------------------------------------------------------------------------------------------
# Wahl


def wahl_fuer(f: dict[str, Any], quelle: str, detail: str, platte: str | None = None,
              drucker: str = "p1p-0.4") -> FilamentWahl:
    """Wahl eines Filaments der Liste (Preset aufgelöst); ``verworfen`` sagt, wenn das Preset nicht geht."""
    spec = fl.preset_spec(f)
    w = FilamentWahl(str(f.get("material") or "").lower(), spec["name"], quelle, detail, filament=f.get("id"),
                     basis=spec["basis"], preset=spec,
                     abweichungen=list((f.get("preset") or {}).get("abweichungen") or []))
    if sl.system_ordner().is_dir():
        basis = spec["basis"]
        if not (sl.profil_vorhanden("filament", basis) or sl._index_voll("filament", basis)):
            w.verworfen.append(f"Filament „{fl.anzeige(f)}“: Basisprofil „{basis}“ gibt es in Bambu Studio nicht.")
        elif not sl.kompatibel(basis, drucker):
            w.verworfen.append(f"Filament „{fl.anzeige(f)}“: Basisprofil „{basis}“ passt laut Bambu Studio nicht zum "
                               f"{sl.maschinen_name(drucker)}.")
        else:
            w.temperaturen = temperaturen(spec, platte)
    return w


def _spulen_reihenfolge(spulen: list[dict[str, Any]], material: str) -> list[dict[str, Any]]:
    def key(s: dict[str, Any]) -> tuple:
        g = _zahl(s.get("gramm")) or 0.0
        voll = _zahl(s.get("gramm_voll"))
        angebrochen = voll is None or g < voll - 0.05
        return (not angebrochen, g, str(s.get("kennung")))

    eigene = [s for s in spulen or [] if isinstance(s, dict) and str(s.get("material") or "").lower() == material
              and (_zahl(s.get("gramm")) or 0.0) > 0]
    return sorted(eigene, key=key)


def spule_text(s: dict[str, Any]) -> str:
    t = "Spule " + " ".join(x for x in (str(s.get("kennung") or ""), str(s.get("name") or "").strip()) if x)
    if s.get("hersteller"):
        t += f" ({s['hersteller']})"
    return t


def vorschlaege(material: str, zuletzt: str | None, spulen: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Für die Rückfrage: {"zuletzt": id | None, "spulen": [{"kennung", "name", "gramm", "filament"}],
    "liste": [{"id", "name", "preset", "basis"}]} (``liste`` = alle Filamente des Materials)."""
    mat = str(material).lower()
    sp = []
    for s in _spulen_reihenfolge(spulen or [], mat):
        f = fl.fuer_spule(s)
        sp.append({"kennung": s.get("kennung"), "name": s.get("name"), "gramm": s.get("gramm"),
                   "filament": f.get("id") if f else None})
    z = fl.finde(zuletzt) if zuletzt else None
    return {"zuletzt": z.get("id") if z and str(z.get("material") or "").lower() == mat else None, "spulen": sp,
            "liste": [{"id": f.get("id"), "name": fl.anzeige(f), "preset": fl.preset_name(f),
                       "basis": (f.get("preset") or {}).get("basis")} for f in fl.liste(mat)]}


def waehle(material: str, projekt: dict[str, Any] | None = None, spulen: list[dict[str, Any]] | None = None,
           drucker: str | None = None, platte: str | None = None) -> FilamentWahl:
    """Angenommenes Filament der Druckvorschau nach der Reihenfolge oben. ``projekt``:
    ``vorschau.projekt_einstellungen`` (``filament``, ``filament_zuletzt``, ``drucker``, ``platte``, ``spulen``)."""
    material = str(material or "pla").lower()
    projekt = projekt or {}
    if spulen is None:
        spulen = projekt.get("spulen") or []
    drucker = str(drucker or projekt.get("drucker") or "p1p-0.4")
    platte = platte or projekt.get("platte")
    mit_profilen = sl.system_ordner().is_dir()
    verworfen: list[str] = []

    def nimm(w: FilamentWahl) -> FilamentWahl | None:
        if w.verworfen:
            verworfen.extend(w.verworfen)
            return None
        w.verworfen = verworfen
        return w

    # 1. Projekt: Filament der Liste oder Bambu-Profil
    f_proj = projekt.get("filament")
    wunsch = str(f_proj.get(material)) if isinstance(f_proj, dict) and f_proj.get(material) else None
    if wunsch:
        eintrag = fl.finde(wunsch)
        if eintrag is not None and str(eintrag.get("material") or "").lower() == material:
            w = nimm(wahl_fuer(eintrag, "projekt", f"kevcad.json druck.filament.{material}", platte, drucker))
            if w:
                return w
        else:
            p = _profil_pruefen(wunsch, f"kevcad.json druck.filament.{material}", drucker, verworfen, mit_profilen)
            if p:
                return FilamentWahl(material, p, "projekt", f"kevcad.json druck.filament.{material}", basis=p,
                                    temperaturen=temperaturen(p, platte) if mit_profilen else None,
                                    verworfen=verworfen)
    # 2. zuletzt für dieses Projekt exportiert
    z = (projekt.get("filament_zuletzt") or {}).get(material)
    eintrag = fl.finde(z) if z else None
    if eintrag is not None and str(eintrag.get("material") or "").lower() == material:
        w = nimm(wahl_fuer(eintrag, "zuletzt", f"zuletzt gewählt: {fl.anzeige(eintrag)}", platte, drucker))
        if w:
            return w
    # 3. Spule im Bestand
    for s in _spulen_reihenfolge(spulen, material):
        eintrag = fl.fuer_spule(s)
        if eintrag is not None:
            w = nimm(wahl_fuer(eintrag, "spule", spule_text(s), platte, drucker))
            if w:
                return w
    # 4. erstes Filament der Liste
    for eintrag in fl.liste(material):
        w = nimm(wahl_fuer(eintrag, "standard", f"angenommen: {fl.anzeige(eintrag)} (erstes der Liste)", platte,
                           drucker))
        if w:
            return w
    # 5. Systemprofil
    if not mit_profilen:
        kand = sl.FILAMENTE.get(material) or ()
        return FilamentWahl(material, kand[0] if kand else None, "system" if kand else "keins", "Liste des Kernels",
                            basis=kand[0] if kand else None, verworfen=verworfen)
    try:
        p = sl.filament_name(material, None, drucker)
    except sl.SlicerFehler as exc:
        verworfen.append(str(exc))
        return FilamentWahl(material, None, "keins", "", verworfen=verworfen)
    return FilamentWahl(material, p, "system", f"Systemprofil für den {sl.maschinen_name(drucker)} (kein Filament "
                                               "dieses Materials in der Liste)", basis=p,
                        temperaturen=temperaturen(p, platte), verworfen=verworfen)


def _profil_pruefen(name: str, wo: str, drucker: str, verworfen: list[str], mit_profilen: bool) -> str | None:
    """Bambu-Profilname (genau, mit „ @BBL P1P“/„ @BBL X1C“ oder als Anfang) → passendes Profil oder None."""
    if not mit_profilen:
        return name
    kand = [name, f"{name} @BBL P1P", f"{name} @BBL X1C"]
    kand += sorted(n for (a, n) in sl._index() if a == "filament" and n.startswith(name) and "nozzle" not in n)
    da = [k for k in kand if sl.profil_vorhanden("filament", k)]
    for k in da:
        if sl.kompatibel(k, drucker):
            return k
    verworfen.append(f"{wo}: „{name}“ " + (f"passt laut Bambu Studio nicht zum {sl.maschinen_name(drucker)}" if da
                                            else "gibt es weder in der Filamentliste noch in Bambu Studio") + ".")
    return None
