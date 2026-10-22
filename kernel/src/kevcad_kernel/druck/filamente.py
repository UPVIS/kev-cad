"""Kevins Filamente mit ihren Bambu-Studio-Presets (Strang „Druckexport 2“, 22.10.2026; DRUCKVORSCHAU.md „Filamente
und Presets“).

Kevin, 22.10.2026: „Wenn ich etwas zum Drucken anweise oder abfrage, fragst du mich nach dem Filament, und die
Projektdatei liefert die passenden Custom Presets zum Filament mit.“

- **Liste** (nicht im freigabepflichtigen Katalog): ``~/Library/Application Support/de.upvis.kevcad/filamente.json``
  (``KEVCAD_FILAMENTE`` übersteuert, Tests). Je Filament Hersteller, Produkt, Material (Katalog-id), Farbe,
  Durchmesser und ein **Preset**: das Bambu-Studio-Profil, von dem es erbt (``basis``, System- oder Kevins
  Benutzerprofil, nur gelesen), ein sprechender Name („Polymaker PolyLite PETG gelb (Kev CAD)“) und Abweichungen, je
  mit Quelle (Herstellerprofil für den P1P oder Kevins getestete Werte). Fehlt die Datei, legt der Kernel sie mit
  dem Startbestand ``START`` an. Erweiterbar per MCP (``filament_liste``, ``filament_define``).
- **Zuletzt gewählt** je Material und Projekt (``druck.json`` → ``filament``, ``vorgaben.py``): nur Vorschlag und
  Grundlage der Schätzung in der Druckvorschau, nie stillschweigend für den Export (dort muss das Filament genannt
  werden, ``druck_export(filament=…)``).
- **Spulen** im Bestand verweisen mit ``filament`` auf einen Eintrag; ältere Spulen ohne Verweis werden über Hersteller
  und Name zugeordnet (``fuer_spule``).

Ein Preset geht vollständig (aufgelöst) als Filamentprofil ins Bambu-Projekt; Name und ``filament_settings_id`` sind
der sprechende Name, ``inherits`` das Systemprofil, von dem es abstammt (Bambu Studio führt es dann als
Projekt-Preset mit diesem Elternteil, ``inherits_group``). Geprüft am 22.10.2026 mit Bambu Studio 2.07.01.62: die
Werte des Presets kommen mit ``--slice 0`` im G-Code an (``M109 S…``).
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from kevcad_kernel.druck import slicer as sl

VERSION = 1
_LOCK = threading.RLock()

# Startbestand (Kevin, 22.10.2026): zwei PETG und sein PLA; für PETG gibt es keine feste Vorgabe (Kevin wird gefragt).
# Ohne Abweichungen: Das Systemprofil „PolyLite PETG @BBL
# P1P“ ist auf die Geschwindigkeiten des P1P abgestimmt (Düse 255 °C); Polymakers 230–240 °C gelten für 30–50 mm/s und
# sind keine belegte Abweichung für diesen Drucker. „Amazon Basics PLA“ ist Kevins Benutzerprofil (nur gelesen).
START: list[dict[str, Any]] = [
    {"id": "polymaker-polylite-petg-gelb", "hersteller": "Polymaker", "produkt": "PolyLite PETG", "material": "petg",
     "farbe": "gelb", "farbe_hex": "#F5C518", "durchmesser_mm": 1.75,
     "preset": {"name": "Polymaker PolyLite PETG gelb (Kev CAD)", "basis": "PolyLite PETG @BBL P1P",
                "abweichungen": []},
     "quelle": "Kevin, 22.10.2026 (Spule Polymaker PolyLite PETG gelb 1,75 mm); Basis: Systemprofil von Bambu Studio "
               "für den P1P; Polymaker bietet im Wiki (Printer Profiles, PET/PETG) ein eigenes Bambu-Studio-Profil "
               "für A1, A1 mini, P1P, P1S und X1C zum Laden an"},
    {"id": "bambu-petg-basic", "hersteller": "Bambu Lab", "produkt": "PETG Basic", "material": "petg",
     "farbe": None, "farbe_hex": None, "durchmesser_mm": 1.75, "offen": ["farbe"],
     "preset": {"name": "Bambu Lab PETG Basic (Kev CAD)", "basis": "Bambu PETG Basic @BBL X1C", "abweichungen": []},
     "quelle": "Kevin, 22.10.2026 (Bambu Lab nennt 230–260 °C; Farbe offen); Basis „Bambu PETG Basic @BBL X1C“, das "
               "Bambu Studio für den P1P 0.4 freigibt (eine P1P-Fassung gibt es nicht)"},
    {"id": "amazon-basics-pla", "hersteller": "Amazon Basics", "produkt": "PLA", "material": "pla", "farbe": None,
     "farbe_hex": None, "durchmesser_mm": 1.75,
     "preset": {"name": "Amazon Basics PLA (Kev CAD)", "basis": "Amazon Basics PLA", "abweichungen": []},
     "quelle": "Kevins Bambu-Studio-Benutzerprofil „Amazon Basics PLA“ (erbt Bambu PLA Basic @BBL P1P; Düse 205 °C, "
               "Bett 47 °C)"},
]

# Abweichungen: Schlüssel → (Bambu-Schlüssel, Einheit, Text). Andere Schlüssel gehen, wenn das Basisprofil sie kennt.
ABWEICHUNGEN: dict[str, tuple[tuple[str, ...], str, str]] = {
    "duese": (("nozzle_temperature",), "°C", "Düse"),
    "duese_erste_schicht": (("nozzle_temperature_initial_layer",), "°C", "Düse erste Schicht"),
    "bett": (tuple(sl.PLATTEN.values()), "°C", "Bett"),
    "bett_erste_schicht": (tuple(f"{v}_initial_layer" for v in sl.PLATTEN.values()), "°C", "Bett erste Schicht"),
    "luefter_min": (("fan_min_speed",), "%", "Lüfter min."),
    "luefter_max": (("fan_max_speed",), "%", "Lüfter max."),
    "max_volumen": (("filament_max_volumetric_speed",), "mm³/s", "Tempo (max. Volumenstrom)"),
    "fluss": (("filament_flow_ratio",), "", "Flussrate"),
}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class FilamentFehler(ValueError):
    pass


# ---------------------------------------------------------------------------------------------------------------------
# Datei


def pfad() -> Path:
    p = os.environ.get("KEVCAD_FILAMENTE")
    if p:
        return Path(p).expanduser()
    return Path.home() / "Library/Application Support/de.upvis.kevcad/filamente.json"


def _schreibe(d: dict[str, Any]) -> None:
    p = pfad()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def lies(anlegen: bool = True) -> dict[str, Any]:
    """Die Liste; fehlt die Datei, der Startbestand (und die Datei wird angelegt)."""
    with _LOCK:
        p = pfad()
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            d = {"version": VERSION, "filamente": copy.deepcopy(START)}
            if anlegen:
                try:
                    _schreibe(d)
                except OSError:
                    pass
            return d
        except (OSError, ValueError) as exc:
            raise FilamentFehler(f"{p.name} ist nicht lesbar: {exc}") from None
        if not isinstance(d, dict) or not isinstance(d.get("filamente"), list):
            raise FilamentFehler(f"{p.name} muss {{\"version\": 1, \"filamente\": [...]}} sein")
        return d


def liste(material: str | None = None) -> list[dict[str, Any]]:
    try:
        alle = [f for f in lies()["filamente"] if isinstance(f, dict)]
    except FilamentFehler:
        return []
    m = str(material or "").lower()
    return [f for f in alle if not m or str(f.get("material") or "").lower() == m]


# Anzeigefarbe im Viewer für häufige Farbnamen (Druckteil mit farbe=…); sonst die Farbe des Materials
FARBEN_HEX = {"gelb": "#F2C200", "schwarz": "#222222", "weiß": "#F2F2F2", "weiss": "#F2F2F2", "rot": "#C8102E",
              "blau": "#1F4E9C", "grün": "#2E8B3D", "gruen": "#2E8B3D", "grau": "#8A8D91", "orange": "#F07D00",
              "silber": "#B8BCC2", "braun": "#7B4A2A", "lila": "#6A3D9A", "violett": "#6A3D9A", "pink": "#E85A9B",
              "natur": "#E8E0C8", "transparent": "#DDEEF2", "beige": "#D8C8A8"}


def farbe_hex(farbe: Any, filament: dict[str, Any] | None = None) -> str | None:
    """Hex-Farbe zur Anzeige: aus dem Filament (``farbe_hex``) oder aus ``FARBEN_HEX``."""
    if filament and filament.get("farbe_hex"):
        return str(filament["farbe_hex"])
    return FARBEN_HEX.get(farbe_schluessel(farbe) or "")


def farbe_schluessel(text: Any) -> str | None:
    """Farbe zum Vergleichen (Druckteil, Spule, Filament): klein, Leerzeichen zusammengefasst; leer → None."""
    t = " ".join(str(text or "").split()).lower()
    return t or None


def _woerter(text: Any) -> frozenset[str]:
    return frozenset(re.findall(r"[0-9a-zäöüß]+", str(text or "").lower()))


def anzeige(f: dict[str, Any]) -> str:
    """„Polymaker PolyLite PETG gelb (1,75 mm)“."""
    teile = [f.get("hersteller"), f.get("produkt"), f.get("farbe")]
    d = f.get("durchmesser_mm")
    return " ".join(str(t) for t in teile if t) + (f" ({str(d).replace('.', ',')} mm)" if d else "")


def finde(eintrag: Any) -> dict[str, Any] | None:
    """Filament zur id oder zu einem Namen („Polymaker PolyLite PETG gelb“, Preset-Name)."""
    if isinstance(eintrag, dict):
        return eintrag
    e = str(eintrag or "").strip()
    if not e:
        return None
    alle = liste()
    for f in alle:
        if f.get("id") == e or (f.get("preset") or {}).get("name") == e:
            return f
    w = _woerter(e)
    treffer = [f for f in alle if w and w <= _woerter(anzeige(f)) | _woerter(f.get("id"))]
    return treffer[0] if len(treffer) == 1 else None


def vorschlaege_ids(eintrag: str, material: str | None = None, n: int = 4) -> list[str]:
    import difflib

    ids = [str(f.get("id")) for f in liste(material)]
    return difflib.get_close_matches(str(eintrag), ids, n=n, cutoff=0.4) or ids[:n]


# ---------------------------------------------------------------------------------------------------------------------
# Preset


def preset_name(f: dict[str, Any]) -> str:
    p = f.get("preset") or {}
    if p.get("name"):
        return str(p["name"])
    return " ".join(str(t) for t in (f.get("hersteller"), f.get("produkt"), f.get("farbe")) if t) + " (Kev CAD)"


def _system_vorfahr(name: str) -> str | None:
    """Das Systemprofil, von dem ein Profil abstammt (bei Kevins Benutzerprofilen über ``inherits``)."""
    system = str(sl.system_ordner())
    for _ in range(12):
        p = sl._index().get(("filament", name)) or sl._index_voll("filament", name)
        if p is None:
            return None
        if str(p).startswith(system):
            return name
        try:
            eltern = json.loads(Path(p).read_text(encoding="utf-8")).get("inherits")
        except (OSError, ValueError):
            return None
        if not eltern:
            return None
        name = str(eltern)
    return None


def _wert_wie(basis_wert: Any, wert: Any) -> Any:
    """Wert im Format des Basisprofils (Listen von Texten, je Extruder-Variante gleich)."""
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        text = f"{wert:g}"
    else:
        text = str(wert)
    if isinstance(basis_wert, list):
        return [text] * max(1, len(basis_wert))
    return text


def bambu_werte(f: dict[str, Any], basis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Die Abweichungen als Bambu-Werte (``bett`` nur für Platten, die das Basisprofil kennt, also nicht 0 °C)."""
    out: dict[str, Any] = {}
    for a in (f.get("preset") or {}).get("abweichungen") or []:
        k = str(a.get("schluessel") or "")
        ziele = ABWEICHUNGEN.get(k, ((k,), "", k))[0]
        for z in ziele:
            alt = (basis or {}).get(z)
            if basis is not None and z not in basis:
                continue
            if k.startswith("bett") and basis is not None:
                v = alt[0] if isinstance(alt, list) and alt else alt
                try:
                    if float(str(v)) <= 0:
                        continue  # Platte, auf der das Filament nicht druckt
                except (TypeError, ValueError):
                    pass
            out[z] = _wert_wie(alt, a.get("wert"))
    return out


def preset_spec(f: dict[str, Any]) -> dict[str, Any]:
    """Preset für ``slicer.filament_daten``: {"name", "basis", "werte", "farbe", "inherits"}."""
    p = f.get("preset") or {}
    basis = str(p.get("basis") or "")
    try:
        bdaten = sl.profil("filament", basis) if basis and sl.system_ordner().is_dir() else None
    except sl.SlicerFehler:
        bdaten = None
    return {"name": preset_name(f), "basis": basis, "werte": bambu_werte(f, bdaten),
            "farbe": f.get("farbe_hex") or None,
            "inherits": (_system_vorfahr(basis) if bdaten is not None else None) or ""}


def abweichungen_text(f: dict[str, Any]) -> str:
    ab = (f.get("preset") or {}).get("abweichungen") or []
    if not ab:
        return "keine Abweichungen"
    teile = []
    for a in ab:
        k = str(a.get("schluessel"))
        _, einheit, text = ABWEICHUNGEN.get(k, ((), "", k))
        teile.append(f"{text} {a.get('wert')}{(' ' + einheit) if einheit else ''} ({a.get('quelle')})")
    return "; ".join(teile)


# ---------------------------------------------------------------------------------------------------------------------
# Prüfen, anlegen


def pruefe(f: dict[str, Any], material_ok: Any = None) -> list[str]:
    """Fehler eines Eintrags (leer = gültig). ``material_ok(id)`` prüft das Material (Katalog, druckbar)."""
    err: list[str] = []
    fid = str(f.get("id") or "")
    if not _ID_RE.match(fid):
        err.append(f"id {fid!r}: Kleinbuchstaben, Ziffern und Bindestriche (z. B. \"polymaker-polylite-petg-gelb\")")
    for k in ("hersteller", "produkt", "material"):
        if not str(f.get(k) or "").strip():
            err.append(f"{k} fehlt")
    if material_ok is not None and f.get("material") and not material_ok(str(f["material"])):
        err.append(f"Material {f.get('material')!r} ist kein freigegebenes Druckmaterial im Katalog")
    d = f.get("durchmesser_mm")
    if d is not None and not (isinstance(d, (int, float)) and 1.0 < float(d) < 3.5):
        err.append("durchmesser_mm: 1,75 oder 2,85")
    if f.get("farbe_hex") and not re.match(r"^#[0-9A-Fa-f]{6}$", str(f["farbe_hex"])):
        err.append("farbe_hex als #RRGGBB")
    p = f.get("preset") or {}
    basis = str(p.get("basis") or "")
    if not basis:
        err.append("preset.basis fehlt (Bambu-Studio-Profil, von dem das Preset erbt, z. B. \"PolyLite PETG @BBL P1P\")")
    elif sl.system_ordner().is_dir():
        if not sl.profil_vorhanden("filament", basis) and sl._index_voll("filament", basis) is None:
            err.append(f"preset.basis „{basis}“ gibt es in Bambu Studio nicht")
        elif not sl.kompatibel(basis):
            err.append(f"preset.basis „{basis}“ passt laut Bambu Studio nicht zum {sl.MASCHINE}")
    for i, a in enumerate(p.get("abweichungen") or []):
        if not isinstance(a, dict):
            err.append(f"abweichungen[{i}]: {{\"schluessel\", \"wert\", \"quelle\"}}")
            continue
        k = str(a.get("schluessel") or "")
        if k not in ABWEICHUNGEN and not re.match(r"^[a-z][a-z0-9_]+$", k):
            err.append(f"abweichungen[{i}].schluessel {k!r} unbekannt (z. B. {', '.join(ABWEICHUNGEN)})")
        if not str(a.get("quelle") or "").strip():
            err.append(f"abweichungen[{i}] ({k}): quelle fehlt (Herstellerprofil für den P1P oder Kevins getesteter "
                       "Wert, mit Datum)")
        if k in ABWEICHUNGEN and not isinstance(a.get("wert"), (int, float)):
            err.append(f"abweichungen[{i}] ({k}): wert als Zahl")
    return err


def define(eintrag: dict[str, Any], ersetzen: bool = False, material_ok: Any = None) -> dict[str, Any]:
    """Filament anlegen (oder mit ``ersetzen`` ersetzen); liefert den gespeicherten Eintrag."""
    f = copy.deepcopy(eintrag)
    f.setdefault("durchmesser_mm", 1.75)
    f["material"] = str(f.get("material") or "").lower()
    if not f.get("id"):
        f["id"] = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", " ".join(
            str(t) for t in (f.get("hersteller"), f.get("produkt"), f.get("farbe")) if t).lower()
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))).strip("-")[:64]
    p = f.setdefault("preset", {})
    p.setdefault("abweichungen", [])
    p.setdefault("name", preset_name(f))
    err = pruefe(f, material_ok)
    if err:
        raise FilamentFehler("; ".join(err))
    with _LOCK:
        d = lies()
        alle = [x for x in d["filamente"] if isinstance(x, dict)]
        i = next((k for k, x in enumerate(alle) if x.get("id") == f["id"]), None)
        if i is not None and not ersetzen:
            raise FilamentFehler(f"Filament {f['id']!r} gibt es schon (ersetzen=True zum Ändern)")
        if i is None:
            alle.append(f)
        else:
            alle[i] = f
        d["filamente"] = alle
        _schreibe(d)
    return f


# ---------------------------------------------------------------------------------------------------------------------
# Spulen und Vorschläge


def fuer_spule(spule: dict[str, Any]) -> dict[str, Any] | None:
    """Filament einer Spule: ihr Verweis ``filament``, sonst der Eintrag gleichen Materials, dessen Hersteller- und
    Produktwörter im Namen oder Hersteller der Spule stehen (bei mehreren der mit passender Farbe)."""
    if spule.get("filament"):
        return finde(spule["filament"])
    w = _woerter(f"{spule.get('hersteller') or ''} {spule.get('name') or ''}")
    if not w:
        return None
    mat = str(spule.get("material") or "").lower()
    sh = str(spule.get("hersteller") or "").strip().lower()

    def passt(f: dict[str, Any]) -> bool:
        pw, hw = _woerter(f.get("produkt")), _woerter(f.get("hersteller"))
        return bool(pw) and pw <= w and (hw <= w or (bool(sh) and sh == str(f.get("hersteller") or "").lower()))

    kand = [f for f in liste(mat) if passt(f)]
    if not kand:
        return None
    farbe = _woerter(spule.get("farbe")) | w
    kand.sort(key=lambda f: not (_woerter(f.get("farbe")) and _woerter(f.get("farbe")) <= farbe))
    return kand[0]


def kurz(f: dict[str, Any]) -> dict[str, Any]:
    """Für die Druckvorschau und die App: id, Anzeige, Material, Farbe, Preset."""
    return {"id": f.get("id"), "name": anzeige(f), "material": f.get("material"), "farbe": f.get("farbe"),
            "farbe_hex": f.get("farbe_hex"), "preset": preset_name(f), "basis": (f.get("preset") or {}).get("basis"),
            "abweichungen": len((f.get("preset") or {}).get("abweichungen") or []),
            **({"offen": list(f["offen"])} if f.get("offen") else {})}
