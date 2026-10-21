"""Projektordner: öffnen, anlegen (Vorlagen), kevcad.json, Versionen und Laufprotokoll.

```
<Projekt>/
├── model.py
├── kevcad.json        Einheit, Genauigkeit
├── output/            STEP, STL, 3MF, GLB
└── .kevcad/
    ├── log/runs.jsonl Laufprotokoll
    └── versions/      model.py je erfolgreichem Lauf (NNNN-model.py)
```
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODEL = "model.py"
SETTINGS = "kevcad.json"
DEFAULT_SETTINGS: dict[str, Any] = {"version": 1, "unit": "mm", "precision": "normal", "inventar_regel": True}

# Genauigkeitsstufen der Tessellierung: (deviation, angular_tolerance); "normal" wie im AP0-Test
PRECISION_LEVELS: dict[str, tuple[float, float]] = {
    "entwurf": (0.3, 0.5),
    "normal": (0.1, 0.2),
    "fein": (0.03, 0.1),
}

EXAMPLE_MODEL = '''"""Wandhalter für ein Rohr Ø 42,4 mm: Grundplatte und Lasche aus Flachstahl 40 × 5, Schelle als 3D-Druckteil aus
PETG, zwei Löcher für M6.

Alle Teile kommen aus dem Inventar (Inventar-Regel): Lagerteile mit lager.teil(...).verbauen(...), die Schelle mit
lager.druckteil(...). Maße in mm, Z nach oben, die Wand liegt in der Ebene y = 0. Parameter stehen oben; jedes Teil
wird mit show() unter demselben Namen wie in verbauen() gezeigt, "/" im Namen bildet den Baum.
"""

from build123d import *
from kevcad import befestigt, lager, param, show, step

hoehe = param("hoehe", 120)  # Länge der Grundplatte
abstand = param("abstand", 70)  # Wand bis Rohrmitte
loch = param("loch", 6.6)  # Durchgangsloch für M6
lochabstand = param("lochabstand", 80)  # Abstand der beiden Löcher
schelle_h = param("schelle_h", 30)  # Höhe der Schelle
wand = param("wand", 4)  # Wandstärke der Schelle

flach = lager.teil("flach", b=40, s=5, material="stahl-s235")  # Lagerteile: erst stock_search, dann lager.teil
rohr = lager.teil("rohr-en10220-42.4x2.0")
breite, blech = flach.masse["b"], flach.masse["s"]
rohr_d = rohr.masse["d"]

step("Grundplatte")
platte = flach.verbauen(laenge=hoehe, name="Halter/Grundplatte")  # entlang +Z, Breite in X, Dicke in Y
platte = Pos(0, blech / 2, -hoehe / 2) * platte
show(platte, "Halter/Grundplatte")

step("Bohrungen")
for z in (-lochabstand / 2, lochabstand / 2):
    platte -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(loch / 2, 3 * blech)
show(platte, "Halter/Grundplatte")  # gleicher Name: ersetzt das Teil, die Stückliste bleibt beim Lagerteil

step("Lasche")
ring_r = rohr_d / 2 + wand
arm = abstand - ring_r - blech  # von der Platte bis an die Schelle
lasche = flach.verbauen(laenge=arm, name="Halter/Lasche")
show(Pos(0, blech, 0) * Rot(-90, 0, 0) * lasche, "Halter/Lasche")  # waagerecht, von der Wand weg

step("Schelle")
ring = Pos(0, abstand, 0) * (Cylinder(ring_r, schelle_h) - Cylinder(rohr_d / 2, schelle_h + 2))
schelle = lager.druckteil(ring, "Halter/Schelle", material="petg")
show(schelle, "Halter/Schelle")

step("Rohr")
stueck = rohr.verbauen(laenge=300, name="Rohr")
show(Pos(0, abstand, -150) * stueck, "Rohr")

# Der Halter hängt an der Wand: für die Prüfung (Schweben, Standsicherheit) gilt er als befestigt
befestigt("Halter/Grundplatte", grund="an der Wand verschraubt")
'''

EMPTY_MODEL = '''"""Neues Modell. Alle Maße in mm, Z nach oben.

Parameter oben mit param(), Bauschritte mit step(), jedes Teil mit show(objekt, "Name"). Inventar-Regel: Teile kommen
aus dem Lager (stock_search, dann lager.teil(...).verbauen(...)) oder sind 3D-Druckteile (lager.druckteil(...)).
"""

from build123d import *
from kevcad import lager, param, show, step

# laenge = param("laenge", 300)
# step("Rohr")
# rohr = lager.teil("rohr-en10220-42.4x2.0")
# stueck = rohr.verbauen(laenge=laenge, name="Rohr")
# show(stueck, "Rohr")
'''

TEMPLATES = {"example": EXAMPLE_MODEL, "empty": EMPTY_MODEL}


class ProjectError(ValueError):
    """Projekt lässt sich nicht öffnen oder anlegen (Meldung für Agent und App)."""


@dataclass
class Project:
    path: Path
    settings: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def model(self) -> Path:
        return self.path / MODEL

    @property
    def output_dir(self) -> Path:
        return self.path / "output"

    @property
    def versions_dir(self) -> Path:
        return self.path / ".kevcad" / "versions"

    @property
    def log_dir(self) -> Path:
        return self.path / ".kevcad" / "log"

    def info(self) -> dict[str, Any]:
        return {"path": str(self.path), "name": self.name, "model": str(self.model),
                "inventar_regel": self.inventar_regel}

    @property
    def inventar_regel(self) -> bool:
        """Inventar-Regel (Phase 2): an, solange kevcad.json nicht ausdrücklich "inventar_regel": false sagt."""
        return self.settings.get("inventar_regel", True) is not False

    def reload_settings(self) -> None:
        """kevcad.json neu lesen (Kevin oder die App können sie ändern)."""
        self.settings, warnings = _read_settings(self.path)
        if warnings:
            self.warnings = warnings

    def set_setting(self, key: str, value: Any) -> None:
        """Einen Wert in kevcad.json schreiben; andere Einträge bleiben, wie sie sind."""
        file = self.path / SETTINGS
        data: dict[str, Any] = dict(DEFAULT_SETTINGS)
        if file.exists():
            try:
                loaded = json.loads(file.read_text(encoding="utf-8"))
                data = loaded if isinstance(loaded, dict) else dict(self.settings)
            except (OSError, json.JSONDecodeError):
                data = dict(self.settings)
        data[key] = value
        tmp = file.with_name(f".{file.name}.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(file)
        self.settings[key] = value

    @property
    def precision(self) -> tuple[float, float]:
        """(deviation, angular) aus der Genauigkeit in kevcad.json."""
        level = str(self.settings.get("precision", "normal")).lower()
        return PRECISION_LEVELS.get(level, PRECISION_LEVELS["normal"])

    # -- Versionen und Protokoll ---------------------------------------------------------------------------------------

    def save_version(self, code: str) -> Path | None:
        """model.py eines erfolgreichen Laufs ablegen; gleicher Inhalt wie die letzte Version wird nicht doppelt
        gespeichert."""
        d = self.versions_dir
        d.mkdir(parents=True, exist_ok=True)
        existing = sorted(d.glob("[0-9][0-9][0-9][0-9]-model.py"))
        if existing:
            try:
                if existing[-1].read_text(encoding="utf-8") == code:
                    return None
            except OSError:
                pass
            number = int(existing[-1].name[:4]) + 1
        else:
            number = 1
        target = d / f"{number:04d}-model.py"
        target.write_text(code, encoding="utf-8")
        return target

    def log_run(self, entry: dict[str, Any]) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            line = json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}, ensure_ascii=False)
            with open(self.log_dir / "runs.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _read_settings(path: Path) -> tuple[dict[str, Any], list[str]]:
    settings = dict(DEFAULT_SETTINGS)
    file = path / SETTINGS
    if not file.exists():
        return settings, []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            settings.update(data)
            return settings, []
        return settings, [f"{SETTINGS} ist kein JSON-Objekt, Vorgaben benutzt"]
    except (OSError, json.JSONDecodeError) as exc:
        return settings, [f"{SETTINGS} nicht lesbar ({exc}), Vorgaben benutzt"]


def open_project(path: str | Path) -> Project:
    p = Path(path).expanduser()
    if not p.exists():
        raise ProjectError(f"Projektordner {str(p)!r} gibt es nicht.")
    if not p.is_dir():
        raise ProjectError(f"{str(p)!r} ist kein Ordner.")
    if not (p / MODEL).is_file():
        raise ProjectError(f"Im Ordner {str(p)!r} fehlt {MODEL}. Neues Projekt mit project_new anlegen.")
    p = p.resolve()
    settings, warnings = _read_settings(p)
    return Project(path=p, settings=settings, warnings=warnings)


def new_project(path: str | Path, template: str = "example") -> Project:
    if template not in TEMPLATES:
        raise ProjectError(f"Vorlage {template!r} unbekannt (erlaubt: {', '.join(TEMPLATES)}).")
    p = Path(path).expanduser()
    if p.exists() and not p.is_dir():
        raise ProjectError(f"{str(p)!r} gibt es schon und ist kein Ordner.")
    if (p / MODEL).exists():
        raise ProjectError(f"In {str(p)!r} liegt schon ein {MODEL}; zum Öffnen project_open benutzen.")
    if p.exists() and any(c for c in p.iterdir() if c.name not in (".DS_Store",)):
        raise ProjectError(f"Der Ordner {str(p)!r} ist nicht leer. Bitte einen neuen oder leeren Ordner angeben.")
    try:
        p.mkdir(parents=True, exist_ok=True)
        (p / MODEL).write_text(TEMPLATES[template], encoding="utf-8")
        (p / SETTINGS).write_text(json.dumps(DEFAULT_SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (p / "output").mkdir(exist_ok=True)
        (p / ".kevcad" / "versions").mkdir(parents=True, exist_ok=True)
        (p / ".kevcad" / "log").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectError(f"Projekt {str(p)!r} ließ sich nicht anlegen: {exc}") from exc
    return open_project(p)
