"""MQTT-Befehle an den Drucker (Thema ``device/<SERIAL>/request``), Aufbau nach OpenBambuAPI und ha-bambulab (MIT).

Zwei Arten: ``LESEN`` (nur ``pushing.pushall`` und ``info.get_version``, in jedem Modus erlaubt, ``pushall`` höchstens
alle 300 s) und ``STEUERN`` (alles andere; geht nur durch ``sperre.pruefe_steuern``). Welche Art ein Befehl ist,
bestimmt ``art(befehl)`` aus dem Inhalt, nicht der Aufrufer.
"""

from __future__ import annotations

from typing import Any

LESEN = "lesen"
STEUERN = "steuern"
PUSHALL_ABSTAND_S = 300.0  # OpenBambuAPI: auf dem P1P nicht öfter als alle 5 Minuten

DRUCKER_ABLAGE = "cache"  # FTPS-Ordner auf der SD-Karte (bambu-printer-mcp: P1/X1 „cache/“)


def pushall(seq: int = 0) -> dict[str, Any]:
    return {"pushing": {"sequence_id": str(seq), "command": "pushall", "version": 1, "push_target": 1}}


def get_version(seq: int = 0) -> dict[str, Any]:
    return {"info": {"sequence_id": str(seq), "command": "get_version"}}


def pause(seq: int = 0) -> dict[str, Any]:
    return {"print": {"sequence_id": str(seq), "command": "pause", "param": ""}}


def fortsetzen(seq: int = 0) -> dict[str, Any]:
    return {"print": {"sequence_id": str(seq), "command": "resume", "param": ""}}


def abbrechen(seq: int = 0) -> dict[str, Any]:
    return {"print": {"sequence_id": str(seq), "command": "stop", "param": ""}}


def project_file(datei: str, platte: int, md5: str, name: str, *, bett_nivellieren: bool = True,
                 flussrate: bool = True, zeitraffer: bool = False, seq: int = 0) -> dict[str, Any]:
    """Druckstart einer hochgeladenen ``.gcode.3mf`` (Ablage ``cache/<datei>``), eine Platte, externe Spule (P1P ohne
    AMS: ``use_ams`` false, ``ams_mapping`` [0] wie ha-bambulab)."""
    return {"print": {
        "sequence_id": str(seq), "command": "project_file",
        "param": f"Metadata/plate_{int(platte)}.gcode",
        "url": f"file:///sdcard/{DRUCKER_ABLAGE}/{datei}",
        "md5": md5, "subtask_name": name,
        "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
        "timelapse": bool(zeitraffer), "bed_type": "auto", "bed_leveling": bool(bett_nivellieren),
        "flow_cali": bool(flussrate), "vibration_cali": True, "layer_inspect": False,
        "use_ams": False, "ams_mapping": [0],
    }}


def art(befehl: dict[str, Any]) -> str:
    """``LESEN`` nur für genau ``pushing.pushall`` und ``info.get_version``; alles andere ist ``STEUERN``."""
    if not isinstance(befehl, dict) or len(befehl) != 1:
        return STEUERN
    (thema, inhalt), = befehl.items()
    if not isinstance(inhalt, dict):
        return STEUERN
    if thema == "pushing" and inhalt.get("command") == "pushall":
        return LESEN
    if thema == "info" and inhalt.get("command") == "get_version":
        return LESEN
    return STEUERN


def name(befehl: dict[str, Any]) -> str:
    try:
        (thema, inhalt), = befehl.items()
        return f"{thema}.{inhalt.get('command')}"
    except (ValueError, AttributeError):
        return "?"
