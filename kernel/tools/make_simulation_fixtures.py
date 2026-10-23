"""Testdateien des Bereichs „Simulation“ (PROTOCOL.md, Abschnitt „Simulation“): SIM, SIM_JOB fertig und laufend, dazu
sim.json mit den erwarteten Werten für den Swift-Decoder.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_simulation_fixtures.py   (``--pruefen``: nur vergleichen)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/sim*.frame und sim.json (eigene Dateien, die übrigen Testdateien
bleiben unverändert).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    check_sim_job,
    check_sim_message,
    encode_frame,
    pack_sim,
    pack_sim_job,
    sim_beispiel,
    sim_job_beispiel,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def dateien() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    erwartet: dict = {}
    head = pack_sim(sim_beispiel(), seq=101)
    fehler = check_sim_message(head)
    assert not fehler, fehler
    out["sim.frame"] = encode_frame(head)
    l0 = head["lastfaelle"][0]
    erwartet["sim"] = {"run": head["run"], "stand": head["stand"], "lastfaelle": len(head["lastfaelle"]),
                       "erster": l0["name"], "lasten": len(l0["lasten"]), "kraft_l1": l0["lasten"][0]["kraft"],
                       "zustand_l2": l0["lasten"][1]["zustand"], "lager": len(head["lager"]),
                       "lager_zustand": head["lager"][0]["zustand"], "modell": len(head["modell"]),
                       "ersetzt": [m["name"] for m in head["modell"] if m.get("ersetzt")],
                       "abgeleitet": len(head["abgeleitet"]),
                       "abgeleitet_aus": [a["id"] for a in head["abgeleitet"] if not a["aktiv"]],
                       "hinweise": len(head["hinweise"]), "neigung": l0["neigung"]["grad"],
                       "ziel": l0["ziel"]["sicherheit"], "untergrund": l0["untergrund"],
                       "fahrt_bremsen": head["lastfaelle"][1]["fahrt"]["bremsen"],
                       "topologie_schutz": head["topologie"]["Halter"]["schutz"][0]["index"],
                       # additiv (simulation2): Lager je Lastfall, Gleitrichtung, Last auf der ganzen Fläche
                       "lager_szenarien": [x.get("szenarien") for x in head["lager"]],
                       "gleiten_richtung": head["lager"][1]["gleiten"]["richtung"],
                       "gleiten_quelle": head["lager"][1]["gleiten"]["quelle"],
                       "gehalten_a2": head["lager"][1]["gehalten_wirksam"],
                       "verteilung_l3": l0["lasten"][2]["verteilung"], "einheit_l3": l0["lasten"][2]["einheit"],
                       "flaeche_mm2_l3": l0["lasten"][2]["flaeche_mm2_wirksam"]}
    for name, stand, seq in (("sim_job", "done", 102), ("sim_job_laeuft", "laeuft", 103)):
        h = pack_sim_job(sim_job_beispiel(stand), seq=seq)
        assert not check_sim_job(h), h
        out[f"{name}.frame"] = encode_frame(h)
        e = h.get("ergebnis") or {}
        erwartet[name] = {"auftrag": h["auftrag"], "was": h["was"], "stand": h["stand"],
                          "fortschritt": h["fortschritt"], "werte": len(e.get("werte") or []),
                          "text": h["text"], "verfahren": e.get("verfahren"),
                          "massgebend_verfahren": e.get("massgebend_verfahren"),
                          "werte_verfahren": [w.get("verfahren") for w in e.get("werte") or []],
                          "probe_ausnutzung": (e.get("probe") or {}).get("ausnutzung")}
    out["sim.json"] = (json.dumps(erwartet, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    return out


def main() -> int:
    pruefen = "--pruefen" in sys.argv[1:]
    alt = []
    for name, daten in dateien().items():
        p = ZIEL / name
        if pruefen:
            if not p.exists() or p.read_bytes() != daten:
                alt.append(name)
            continue
        ZIEL.mkdir(parents=True, exist_ok=True)
        p.write_bytes(daten)
    if pruefen:
        if alt:
            print(f"Veraltet: {', '.join(alt)} (tools/make_simulation_fixtures.py ausführen)")
            return 1
        print("Testdateien der Simulation aktuell")
        return 0
    print(f"Testdateien der Simulation nach {ZIEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
