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
DEFAULT_SETTINGS: dict[str, Any] = {"version": 1, "unit": "mm", "precision": "normal"}

# Genauigkeitsstufen der Tessellierung: (deviation, angular_tolerance); "normal" wie im AP0-Test
PRECISION_LEVELS: dict[str, tuple[float, float]] = {
    "entwurf": (0.3, 0.5),
    "normal": (0.1, 0.2),
    "fein": (0.03, 0.1),
}

EXAMPLE_MODEL = '''"""Wandhalter für ein Rohr Ø 42,4 mm aus 5-mm-Alublech mit zwei M6-Löchern.

Alle Maße in mm, Z nach oben, die Wand liegt in der Ebene y = 0. Parameter stehen oben, jedes Teil wird mit show()
und sprechendem Namen gezeigt; "/" im Namen bildet den Baum.
"""

from build123d import *
from kevcad import param, show, step

rohr_d = param("rohr_d", 42.4)  # Außendurchmesser des Rohrs
blech = param("blech", 5)  # Blechdicke
breite = param("breite", 60)  # Breite der Grundplatte
hoehe = param("hoehe", 120)  # Höhe der Grundplatte
abstand = param("abstand", 70)  # Wand bis Rohrmitte
loch = param("loch", 6.6)  # Durchgangsloch für M6
lochabstand = param("lochabstand", 80)  # Abstand der beiden Löcher
schelle = param("schelle", 30)  # Höhe der Rohrschelle

step("Grundplatte")
platte = Box(breite, blech, hoehe, align=(Align.CENTER, Align.MIN, Align.CENTER))
show(platte, "Halter/Grundplatte", color="#B8BEC4", material="aluminium")

step("Bohrungen")
for z in (-lochabstand / 2, lochabstand / 2):
    platte -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(loch / 2, 3 * blech)
show(platte, "Halter/Grundplatte", color="#B8BEC4", material="aluminium")  # gleicher Name: ersetzt das Teil

step("Lasche mit Schelle")
ring_r = rohr_d / 2 + blech
arm = abstand - ring_r + blech
lasche = Pos(0, blech + arm / 2, 0) * Box(breite * 0.6, arm, blech)
lasche += Pos(0, abstand, 0) * Cylinder(ring_r, schelle)
lasche -= Pos(0, abstand, 0) * Cylinder(rohr_d / 2, schelle + 2)
show(lasche, "Halter/Lasche", color="#9FB4C7", material="aluminium")

step("Rohr")
rohr = Pos(0, abstand, 0) * (Cylinder(rohr_d / 2, 300) - Cylinder(rohr_d / 2 - 2.6, 300))
show(rohr, "Rohr", color="#8A949C", material="edelstahl")
'''

EMPTY_MODEL = '''"""Neues Modell. Alle Maße in mm, Z nach oben.

Parameter oben mit param(), Bauschritte mit step(), jedes Teil mit show(objekt, "Name").
"""

from build123d import *
from kevcad import param, show, step

# breite = param("breite", 50)
# step("Grundkörper")
# koerper = Box(breite, 30, 10)
# show(koerper, "Grundkörper", color="#B8BEC4", material="aluminium")
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

    def info(self) -> dict[str, str]:
        return {"path": str(self.path), "name": self.name, "model": str(self.model)}

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
