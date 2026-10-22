"""Hilfen für die Drucker-Tests (Phase 8): Ersatz für Bambu Studio (App-Bündel mit CLI-Attrappe und Profilbaum) und
die Drucker-Attrappe aus ``tools/drucker_attrappe.py``."""

from __future__ import annotations

import json
import os
import plistlib
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from drucker_attrappe import TEST_SERIENNUMMER, TEST_ZUGANGSCODE, Attrappe  # noqa: E402,F401

ECHTES_BAMBU = Path("/Applications/BambuStudio.app")

# CLI-Attrappe: schreibt eine .gcode.3mf wie Bambu Studio (slice_info.config, G-Code je Platte, MD5, Einstellungen)
CLI = r'''
import hashlib, json, os, sys, time, zipfile
args = sys.argv[1:]
def wert(name):
    return args[args.index(name) + 1] if name in args else None
aus = wert("--outputdir"); datei = wert("--export-3mf")
with open(os.path.join(aus, "aufruf.json"), "w") as fh:
    json.dump({{"args": args, "home": os.environ.get("HOME")}}, fh)
if os.environ.get("FAKE_BAMBU_SCHLAF"):
    time.sleep(float(os.environ["FAKE_BAMBU_SCHLAF"]))
if os.environ.get("FAKE_BAMBU_FEHLER"):
    with open(os.path.join(aus, "result.json"), "w") as fh:
        json.dump({{"error_string": os.environ["FAKE_BAMBU_FEHLER"], "return_code": -5}}, fh)
    sys.exit(251)
optionen_mit_wert = {{"--slice", "--arrange", "--orient", "--load-settings", "--load-filaments", "--outputdir",
                      "--export-3mf", "--debug"}}
eingaben, i = [], 0
while i < len(args):
    if args[i] in optionen_mit_wert:
        i += 2
    elif args[i].startswith("--"):
        i += 1
    else:
        eingaben.append(args[i]); i += 1
platten = int(os.environ.get("FAKE_BAMBU_PLATTEN", "1"))
fil = wert("--load-filaments")
typ = "PLA"
if fil:
    typ = json.load(open(fil.split(";")[0])).get("filament_type", ["PLA"])[0]
info = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
with zipfile.ZipFile(os.path.join(aus, datei), "w") as z:
    for n in range(1, platten + 1):
        gcode = (f"; Attrappe Platte {{n}} aus {{len(eingaben)}} Eingaben\nG28\n" * 50).encode()
        z.writestr(f"Metadata/plate_{{n}}.gcode", gcode)
        z.writestr(f"Metadata/plate_{{n}}.gcode.md5", hashlib.md5(gcode).hexdigest().upper())
        info += ["  <plate>", f'    <metadata key="index" value="{{n}}"/>',
                 '    <metadata key="printer_model_id" value=""/>',
                 f'    <metadata key="prediction" value="{{1000 * n + 49}}"/>',
                 f'    <metadata key="weight" value="{{7.4 * n:.2f}}"/>',
                 f'    <filament id="1" type="{{typ}}" used_m="{{2.44 * n:.2f}}" used_g="{{7.4 * n:.2f}}"/>',
                 "  </plate>"]
    info.append("</config>")
    z.writestr("Metadata/slice_info.config", "\n".join(info))
    z.writestr("Metadata/project_settings.config", json.dumps({{"printer_model": "Bambu Lab P1P"}}))
    if "--min-save" not in args:
        z.writestr("3D/Objects/object_1.model", "<model/>")
with open(os.path.join(aus, "result.json"), "w") as fh:
    json.dump({{"error_string": "Success.", "return_code": 0,
               "sliced_plates": [{{"id": n, "warning_message": ""}} for n in range(1, platten + 1)]}}, fh)
'''


def _json(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")


def bambu_attrappe(ordner: Path, version: str = "02.07.01.62") -> Path:
    """App-Bündel ``BambuStudio.app`` mit CLI-Attrappe und kleinem Profilbaum (mit Vererbung wie im Original)."""
    app = ordner / "BambuStudio.app"
    exe = app / "Contents/MacOS/BambuStudio"
    exe.parent.mkdir(parents=True, exist_ok=True)
    skript = app / "Contents/Resources/cli_attrappe.py"
    skript.parent.mkdir(parents=True, exist_ok=True)
    skript.write_text(CLI.format(), encoding="utf-8")
    # Shell-Hülle statt Shebang: Pfade mit Leerzeichen („Code Experiments“) gehen im Shebang nicht
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{skript}" "$@"\n', encoding="utf-8")
    os.chmod(exe, 0o755)
    with (app / "Contents/Info.plist").open("wb") as fh:
        plistlib.dump({"CFBundleShortVersionString": version, "CFBundleIdentifier": "com.bambulab.bambu-studio"}, fh)
    prof = app / "Contents/Resources/profiles"
    bbl = prof / "BBL"
    _json(bbl / "machine/fdm_machine_common.json", {"name": "fdm_machine_common", "nozzle_diameter": ["0.4"],
                                                    "printable_height": "250"})
    _json(bbl / "machine/Bambu Lab P1P 0.4 nozzle.json", {"name": "Bambu Lab P1P 0.4 nozzle",
                                                          "inherits": "fdm_machine_common",
                                                          "printer_model": "Bambu Lab P1P", "from": "system"})
    _json(bbl / "process/fdm_process_common.json", {"name": "fdm_process_common", "wall_loops": "2",
                                                    "sparse_infill_density": "15%"})
    for schicht, art in (("0.20", "Standard"), ("0.16", "Optimal"), ("0.12", "Fine"), ("0.28", "Extra Draft")):
        n = f"{schicht}mm {art} @BBL P1P"
        _json(bbl / f"process/{n}.json", {"name": n, "inherits": "fdm_process_common", "layer_height": schicht})
    _json(bbl / "process/0.20mm Standard @BBL P1P 0.6 nozzle.json", {"name": "0.20mm Standard @BBL P1P 0.6 nozzle",
                                                                     "layer_height": "0.2"})
    _json(bbl / "filament/fdm_filament_common.json", {"name": "fdm_filament_common", "filament_diameter": ["1.75"]})
    _json(bbl / "filament/fdm_filament_pla.json", {"name": "fdm_filament_pla", "inherits": "fdm_filament_common",
                                                   "filament_type": ["PLA"], "filament_density": ["1.24"]})
    _json(bbl / "filament/fdm_filament_pet.json", {"name": "fdm_filament_pet", "inherits": "fdm_filament_common",
                                                   "filament_type": ["PETG"], "filament_density": ["1.27"]})
    _json(bbl / "filament/P1P/Bambu PLA Basic @BBL P1P.json", {"name": "Bambu PLA Basic @BBL P1P",
                                                               "inherits": "fdm_filament_pla"})
    _json(bbl / "filament/P1P/Generic PETG @BBL P1P.json", {"name": "Generic PETG @BBL P1P",
                                                            "inherits": "fdm_filament_pet"})
    namen = {
        "machine_model_list": [],
        "machine_list": [{"name": "fdm_machine_common", "sub_path": "machine/fdm_machine_common.json"},
                         {"name": "Bambu Lab P1P 0.4 nozzle", "sub_path": "machine/Bambu Lab P1P 0.4 nozzle.json"}],
        "process_list": [{"name": "fdm_process_common", "sub_path": "process/fdm_process_common.json"}]
        + [{"name": f"{s}mm {a} @BBL P1P", "sub_path": f"process/{s}mm {a} @BBL P1P.json"}
           for s, a in (("0.20", "Standard"), ("0.16", "Optimal"), ("0.12", "Fine"), ("0.28", "Extra Draft"))]
        + [{"name": "0.20mm Standard @BBL P1P 0.6 nozzle",
            "sub_path": "process/0.20mm Standard @BBL P1P 0.6 nozzle.json"}],
        "filament_list": [{"name": n, "sub_path": p} for n, p in (
            ("fdm_filament_common", "filament/fdm_filament_common.json"),
            ("fdm_filament_pla", "filament/fdm_filament_pla.json"),
            ("fdm_filament_pet", "filament/fdm_filament_pet.json"),
            ("Bambu PLA Basic @BBL P1P", "filament/P1P/Bambu PLA Basic @BBL P1P.json"),
            ("Generic PETG @BBL P1P", "filament/P1P/Generic PETG @BBL P1P.json"))],
    }
    _json(prof / "BBL.json", {"name": "Bambu Lab", "version": "02.07.00.00", **namen})
    return app


def benutzer_profile(ordner: Path) -> Path:
    """Benutzerprofile wie in Bambu Studio (ein eigenes PLA, erbt vom Systemprofil)."""
    _json(ordner / "1234567890/filament/Kevins PLA.json", {"name": "Kevins PLA", "from": "User",
                                                           "inherits": "Bambu PLA Basic @BBL P1P",
                                                           "nozzle_temperature": ["205"]})
    return ordner


def wuerfel_stl(pfad: Path, kante: float = 20.0) -> Path:
    import struct

    v = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6),
         (3, 0, 4), (3, 4, 7)]
    with pfad.open("wb") as fh:
        fh.write(b"\0" * 80 + struct.pack("<I", len(f)))
        for a, b, c in f:
            fh.write(struct.pack("<3f", 0, 0, 0))
            for i in (a, b, c):
                fh.write(struct.pack("<3f", *(x * kante for x in v[i])))
            fh.write(b"\0\0")
    return pfad
