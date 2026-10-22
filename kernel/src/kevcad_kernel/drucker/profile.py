"""Profile von Bambu Studio für das Slicen auflösen (nur lesen, Kevins Einstellungen bleiben unverändert).

Die Systemprofile liegen in der App (``Contents/Resources/profiles/BBL``, Verzeichnis ``BBL.json`` mit ``sub_path`` je
Name), Kevins eigene unter ``~/Library/Application Support/BambuStudio/user/<id>/{filament,process,machine}``. Fast alle
erben (``inherits``) von Basisprofilen; die CLI löst die Kette nicht vollständig auf (lokal geprüft am 22.10.2026:
ohne Auflösung fehlen Dichte und Gewicht). Deshalb lösen wir die Kette selbst auf und schreiben flache JSON-Dateien in
den Zwischenspeicher.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BAMBU_APP = Path("/Applications/BambuStudio.app")
BENUTZER_WURZEL = Path.home() / "Library/Application Support/BambuStudio/user"
MASCHINE_P1P_04 = "Bambu Lab P1P 0.4 nozzle"
MODELL_ID_P1P = "C11"

# Systemprofil je Material, wenn weder Druckvorschau noch kevcad.json ein Filament nennen
FILAMENT_STANDARD: dict[str, str] = {
    "pla": "Bambu PLA Basic @BBL P1P",
    "petg": "Generic PETG @BBL P1P",
    "asa": "Generic ASA @BBL P1P",
    "abs": "Generic ABS @BBL P1P",
    "tpu": "Generic TPU @BBL P1P",
    "tpu-95a": "Generic TPU @BBL P1P",
    "pa": "Generic PA @BBL P1P",
    "pc": "Generic PC @BBL P1P",
    "pla-cf": "Generic PLA-CF @BBL P1P",
    "petg-cf": "Generic PETG-CF @BBL P1P",
}
PROZESS_STANDARD = "0.20mm Standard @BBL P1P"


class ProfilFehler(Exception):
    pass


def material_schluessel(material: str | None) -> str:
    m = (material or "").strip().lower()
    if m in FILAMENT_STANDARD:
        return m
    for k in sorted(FILAMENT_STANDARD, key=len, reverse=True):
        if m.startswith(k):
            return k
    return "pla"


class Profile:
    def __init__(self, app: Path = BAMBU_APP, benutzer_wurzel: Path | None = BENUTZER_WURZEL) -> None:
        self.app = Path(app)
        self.basis = self.app / "Contents/Resources/profiles/BBL"
        self._pfade: dict[str, Path] = {}
        self._prozesse: list[str] = []
        idx = self.basis.parent / "BBL.json"
        if not idx.exists():
            raise ProfilFehler(f"Profile von Bambu Studio nicht gefunden ({idx})")
        daten = json.loads(idx.read_text(encoding="utf-8"))
        for liste in ("machine_model_list", "machine_list", "process_list", "filament_list"):
            for e in daten.get(liste) or []:
                if isinstance(e, dict) and e.get("name") and e.get("sub_path"):
                    self._pfade[e["name"]] = self.basis / e["sub_path"]
                    if liste == "process_list":
                        self._prozesse.append(e["name"])
        # Kevins eigene Profile (nur lesen); bei gleichem Namen gelten sie vor den Systemprofilen
        self.benutzer: dict[str, Path] = {}
        if benutzer_wurzel is not None and benutzer_wurzel.is_dir():
            for f in sorted(benutzer_wurzel.glob("*/*/*.json")):
                if f.parent.name in ("filament", "process", "machine"):
                    try:
                        name = json.loads(f.read_text(encoding="utf-8")).get("name") or f.stem
                    except (OSError, ValueError):
                        continue
                    self.benutzer[str(name)] = f

    def kennt(self, name: str) -> bool:
        return name in self.benutzer or name in self._pfade

    def laden(self, name: str, _tiefe: int = 0) -> dict[str, Any]:
        """Profil ``name`` mit aufgelöster Vererbung (``inherits`` entfernt)."""
        if _tiefe > 12:
            raise ProfilFehler(f"Vererbung von {name!r} zu tief")
        pfad = self.benutzer.get(name) or self._pfade.get(name)
        if pfad is None:
            raise ProfilFehler(f"Profil {name!r} kennt Bambu Studio nicht")
        try:
            d = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProfilFehler(f"Profil {name!r} nicht lesbar: {exc}") from None
        eltern = d.get("inherits")
        if eltern:
            basis = self.laden(str(eltern), _tiefe + 1)
            basis.update(d)
            d = basis
        d.pop("inherits", None)
        return d

    def prozess_fuer(self, schicht_mm: float | None) -> str:
        """Prozessprofil des P1P (0,4 mm) mit der nächstliegenden Schichthöhe."""
        if not schicht_mm:
            return PROZESS_STANDARD
        beste, abstand = PROZESS_STANDARD, 9.0
        for n in self._prozesse:
            if not n.endswith("@BBL P1P"):
                continue  # andere Düsen oder Drucker
            m = re.match(r"^(\d+\.\d+)mm ", n)
            if not m:
                continue
            a = abs(float(m.group(1)) - float(schicht_mm))
            if a < abstand - 1e-9 or (abs(a - abstand) < 1e-9 and "Standard" in n):
                beste, abstand = n, a
        return beste

    def filament_fuer(self, material: str | None, wunsch: str | None = None) -> str:
        if wunsch and self.kennt(wunsch):
            return wunsch
        return FILAMENT_STANDARD[material_schluessel(material)]

    def schreiben(self, ordner: Path, prozess: str, filamente: list[str]) -> tuple[list[Path], list[Path]]:
        """Flache Profile für ``--load-settings`` (Maschine, Prozess) und ``--load-filaments`` schreiben."""
        ordner.mkdir(parents=True, exist_ok=True)
        einst = []
        for art, name in (("maschine", MASCHINE_P1P_04), ("prozess", prozess)):
            d = self.laden(name)
            d.setdefault("from", "system")
            p = ordner / f"{art}.json"
            p.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
            einst.append(p)
        fil = []
        for i, name in enumerate(filamente, start=1):
            d = self.laden(name)
            p = ordner / f"filament_{i}.json"
            p.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
            fil.append(p)
        return einst, fil
