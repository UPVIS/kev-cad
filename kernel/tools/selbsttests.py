"""Alle Selbsttests der App (``KEVCAD_SELFTEST=…``) nacheinander, in einer Testvariante, je Test an einer frischen Kopie.

    tools/fern.sh testbau st
    tools/fern/selbsttests.sh "build/Kev CAD Test st.app" "$HOME/Documents/Kev CAD/Kugelschieber Variante B" [Tests …]

Das Skript fährt den Lauf auf dem Mac mini: Etliche Tests öffnen Dialoge und Nebenfenster, die nicht auf Kevins
Hauptbildschirm gehören. ``viewer`` braucht ein gezeichnetes Bild und läuft deshalb mit ``--hier`` direkt am MacBook, das
Fenster hinter dem Schreibtischbild (``KEVCAD_TEST_VERSTECKT=1``). Zu jedem Test steht unten, womit er läuft: mit dem
echten Kernel, dem Ersatz-Kernel (``fake_kernel.py``) oder dem Demomodus.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from messen import KATALOG, kopieren  # noqa: E402

KERNEL = Path(__file__).resolve().parents[1]
ECHT = shlex.quote(str(KERNEL / ".venv/bin/kevcad-kernel"))


def ersatz(*schalter: str) -> str:
    teile = [str(KERNEL / ".venv/bin/python"), str(KERNEL / "tools/fake_kernel.py"), *schalter]
    return " ".join(shlex.quote(t) for t in teile)


# Test → (Kernel, Ergebnisdatei, Frist in s, weitere Umgebung). Kernel None heißt Demomodus; ohne Ergebnisdatei steht das
# Ergebnis nur im Protokoll der App. Nicht dabei, weil sie mehr brauchen als ein Projekt: drucker (Attrappe und echter
# Schlüsselbund), restdruck (Projekt mit Spulen und Resten), massstab (Referenznetz), sprache
# (kernel/tools/feedback_selbsttest.py), wortlaut (Kevins Dienst, ohne Fenster).
TESTS: dict[str, tuple[str | None, str, int, dict[str, str]]] = {
    "keys": (None, "selftest-keys.txt", 40, {"KEVCAD_DEMO": "1", "KEVCAD_DEMO_STATE": "bom"}),
    "oberflaeche": (ECHT, "selftest-oberflaeche.txt", 300, {}),
    "material": (ECHT, "selftest-material.txt", 300, {}),
    "bestand": (ersatz("--bestand"), "selftest-bestand.txt", 120, {}),
    "filament": (ersatz("--bestand", "--filament"), "selftest-filament.txt", 120, {}),
    "catalog": (ersatz("--lager"), "selftest-catalog.txt", 120, {}),
    "freigabe": (ersatz("--lager"), "selftest-freigabe.txt", 120, {"KEVCAD_SELFTEST_PROJEKT": ""}),
    "zukauf": (ersatz("--zukauf"), "selftest-zukauf.txt", 180, {}),
    "dokumente": (ECHT, "selftest-dokumente.txt", 420, {}),
    "bauplan-export": (ECHT, "selftest-dokumente.txt", 420, {}),
    # Ohne Bambu Studio kommt kein Slicer-Ergebnis: nicht warten, die Schätzung genügt
    "druck": (ECHT, "selftest-druck.txt", 300, {"KEVCAD_SELFTEST_SLICER_WARTEN": "5",
                                                "KEVCAD_SELFTEST_EXPORT_WARTEN": "30"}),
    "render": (ECHT, "selftest-render.txt", 300, {}),
    "simulation": (ECHT, "selftest-simulation.txt", 420, {"PROJEKT": str(KERNEL.parent / "samples/winkelhalter")}),
    "viewer": (ECHT, "selftest-viewer.txt", 480, {}),  # nur mit --hier
    "core": (ECHT, "", 90, {}),  # nur mit --hier: Klick und Treffer brauchen ein gezeichnetes Bild
}
HIER = {"viewer", "core"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("app")
    ap.add_argument("projekt")
    ap.add_argument("tests", nargs="*", help="Vorgabe: alle")
    ap.add_argument("--katalog", default=None)
    ap.add_argument("--ausgabe", default="selbsttests")
    ap.add_argument("--hier", action="store_true", help="auf diesem Rechner, Fenster hinter dem Schreibtischbild")
    ap.add_argument("--sichtbar", action="store_true", help="auf diesem Rechner, Fenster sichtbar: misst die Bilder je "
                                                            "Sekunde am Monitor (zweiter Monitor oder Kevins Abnahme)")
    args = ap.parse_args()

    app = Path(args.app).resolve()
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    bundle_id, name = info["CFBundleIdentifier"], info.get("CFBundleExecutable") or app.stem
    if ".test" not in bundle_id:
        raise SystemExit(f"{bundle_id}: nur Testvarianten")
    daten = Path.home() / "Library/Application Support" / bundle_id
    ausgabe = Path(args.ausgabe).resolve()
    ausgabe.mkdir(parents=True, exist_ok=True)
    projekt = Path(args.projekt).expanduser().resolve()
    katalog = Path(args.katalog).expanduser() if args.katalog else KATALOG

    ergebnisse: dict[str, str] = {}
    for test in args.tests or [t for t in TESTS if t not in HIER]:
        kernel, datei, frist, mehr = TESTS[test]
        ziel = ausgabe / test
        shutil.rmtree(ziel, ignore_errors=True)
        ziel.mkdir()
        arbeit, kopie = kopieren(Path(mehr.get("PROJEKT", projekt)), katalog)
        if datei:
            (daten / datei).unlink(missing_ok=True)
        umgebung = {
            "KEVCAD_SELFTEST": test, "KEVCAD_SELFTEST_AUSGABE": str(ziel), "KEVCAD_SELFTEST_QUIT": "1",
            "KEVCAD_SELFTEST_PROJEKT": str(kopie), "KEVCAD_PROJECTS_DIR": str(arbeit),
            "KEVCAD_DOWNLOADS_DIR": str(arbeit / "downloads"),
            **{k: v for k, v in os.environ.items() if k.startswith(("KEVCAD_DRUCK", "KEVCAD_BAMBU", "KEVCAD_FESTKOERPER",
                                                                    "KEVCAD_FILAMENTE", "KEVCAD_CATALOG"))},
            **{k: v for k, v in mehr.items() if k != "PROJEKT"},
        }
        if args.hier:
            umgebung["KEVCAD_TEST_VERSTECKT"] = "1"
        (arbeit / "downloads").mkdir(exist_ok=True)
        # Die Testvariante kennt den Ordner dieses Kernels nicht (gebaut auf einem Bauplatz): Er läuft hier neben ihr
        prozess = None
        if kernel:
            umgebung["KEVCAD_KERNEL_EXTERNAL"] = "1"
            socket = daten / "kernel.sock"
            socket.unlink(missing_ok=True)
            prozess = subprocess.Popen([*shlex.split(kernel), "serve", "--socket", str(socket), "--port", "47921"],
                                       env={**os.environ, **umgebung, "KEVCAD_APP_BUNDLE_ID": bundle_id},
                                       stdout=open(ziel / "kernel.log", "wb"), stderr=subprocess.STDOUT)
        log = ziel / "app.log"
        befehl = ["open", "-g", "-n", "--stderr", str(log), "--stdout", str(log)]
        for k, v in umgebung.items():
            befehl += ["--env", f"{k}={v}"]
        t0 = time.monotonic()
        print(f"== {test}", flush=True)
        subprocess.run([*befehl, str(app)], check=True)
        bericht = None
        while time.monotonic() - t0 < frist:
            for ort in (ziel / datei, daten / datei) if datei else ():
                if ort.exists() and ort.stat().st_size > 0:
                    bericht = ort
            if bericht:
                break
            time.sleep(1)
        time.sleep(2)  # die App schreibt zu Ende und beendet sich
        subprocess.run(["pkill", "-x", name], check=False)
        time.sleep(1)
        if prozess is not None:
            prozess.terminate()
            try:
                prozess.wait(10)
            except subprocess.TimeoutExpired:
                prozess.kill()
        dauer = time.monotonic() - t0
        if not datei:
            zeilen = [z for z in log.read_text(encoding="utf-8", errors="replace").splitlines() if "Selbsttest" in z]
            ergebnisse[test] = f"{len(zeilen)} Zeilen im Protokoll"
            for z in zeilen[-30:]:
                print("   ", z[:220], flush=True)
        elif bericht is None:
            ergebnisse[test] = f"kein Bericht nach {dauer:.0f} s"
        else:
            text = bericht.read_text(encoding="utf-8")
            if bericht.parent != ziel:
                shutil.copy(bericht, ziel / datei)
            fehler = [z for z in text.splitlines() if z.startswith("FEHLER")]
            kopf = text.splitlines()[0] if text else ""
            ergebnisse[test] = f"{len(fehler)} Fehler, {dauer:.0f} s: {kopf}"
            for z in fehler[:30]:
                print("   ", z[:220], flush=True)
        print(f"   {ergebnisse[test]}", flush=True)
        shutil.rmtree(arbeit, ignore_errors=True)
    (ausgabe / "ergebnis.json").write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
