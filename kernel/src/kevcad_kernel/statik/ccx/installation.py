"""CalculiX (ccx) für Statik Stufe 4: finden, einrichten, prüfen.

CalculiX ist GPL und läuft nur als eigenes Programm (nie eingebunden). Es kommt von conda-forge (Paket ``calculix``,
osx-arm64, mit ARPACK, OpenBLAS, libgfortran, llvm-openmp) über ``micromamba`` (statisches Programm von conda-forge)
in eine eigene Umgebung. Kevins Vorgabe (23.10.2026): alles, auch der Paket-Zwischenspeicher, auf der externen Platte
UPVIS ULTRA, nicht auf der Systemplatte:

    /Volumes/UPVIS ULTRA/#PROGRAMME_DO-NOT-DELETE#/Kev CAD/calculix/
        LIESMICH.txt        wofür, wer, wie neu einrichten, Quelle, Lizenz
        bin/micromamba      Paketverwalter (conda-forge, BSD-3)
        env/bin/ccx         CalculiX
        mamba/pkgs          Paket-Zwischenspeicher
        stand.json          Version, Datum, Größe

Übersteuern: Umgebungsvariable ``KEVCAD_CALCULIX_DIR`` (Ordner wie oben) oder ``KEVCAD_CCX`` (direkt das Programm),
sonst die Einstellung ``calculix.json`` (``{"ordner": "…"}``) in ``~/Library/Application Support/de.upvis.kevcad/``.
Ist die Platte nicht angeschlossen, meldet ``finde`` das klar; S0 bis S3 laufen weiter, nur S4 fehlt.

Einrichten von Hand: ``python -m kevcad_kernel.statik.ccx.installation`` (``--wenn-fehlt`` still, wenn schon da;
``--pruefen`` nur prüfen). Kev CAD richtet es beim ersten Gebrauch selbst ein, ``build.sh`` bei jeder Installation
(nie fatal, auch nicht ohne Platte).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

PLATTE = "/Volumes/UPVIS ULTRA"
STANDARD = Path(PLATTE) / "#PROGRAMME_DO-NOT-DELETE#" / "Kev CAD" / "calculix"
EINSTELLUNG = Path.home() / "Library" / "Application Support" / "de.upvis.kevcad" / "calculix.json"
MICROMAMBA_URL = "https://micro.mamba.pm/api/micromamba/osx-arm64/latest"
PAKETE = ("calculix",)
KANAL = "conda-forge"

LIESMICH = """CalculiX für Kev CAD (Statik Stufe 4) - BITTE NICHT LÖSCHEN
====================================================================

Wofür: CalculiX (Programm ccx) rechnet in Kev CAD die Statik Stufe 4: Kontakt mit Abheben und Gleiten
(Klemmungen, aufliegende Teile, Bolzen in Bohrungen), Plastizität (Fließen, bleibende Verformung, Traglast)
und Beulen. Kev CAD ruft es nur als eigenes Programm auf (MCP-Werkzeug festigkeit mit verfahren="ccx").

Wer nutzt es: Kev CAD (Kevins CAD-Viewer, ~/Applications/Tools/Kev CAD.app) und seine Testvarianten.
Fehlt der Ordner oder die Platte, laufen S0 bis S3 weiter; Stufe 4 meldet dann "CalculiX nicht verfügbar".

Inhalt:
  bin/micromamba   Paketverwalter (conda-forge, https://github.com/mamba-org/mamba, BSD-3-Clause)
  env/             eigene Umgebung mit CalculiX und seinen Bibliotheken (ARPACK, OpenBLAS, libgfortran, llvm-openmp)
  env/bin/ccx      CalculiX CrunchiX
  mamba/pkgs       Paket-Zwischenspeicher
  stand.json       eingerichtete Version, Datum, Größe

Neu einrichten (etwa nach Löschen oder auf einer anderen Platte):
  cd ~/Library/Application\\ Support/de.upvis.kevcad/install/kernel
  .venv/bin/python -m kevcad_kernel.statik.ccx.installation
Anderer Ort: Umgebungsvariable KEVCAD_CALCULIX_DIR oder Datei
  ~/Library/Application Support/de.upvis.kevcad/calculix.json mit {"ordner": "/pfad/zum/ordner"}

Quelle: conda-forge, Paket "calculix" (https://anaconda.org/conda-forge/calculix,
        Feedstock https://github.com/conda-forge/calculix-feedstock), Original http://www.calculix.de
        (Guido Dhondt, Klaus Wittig).
Lizenz: CalculiX ist freie Software unter der GNU General Public License (GPL-2.0-or-later). Kev CAD bindet
        es nicht ein, sondern startet es als eigenen Prozess.
"""


def _einstellung() -> dict[str, Any]:
    try:
        return json.loads(EINSTELLUNG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ordner() -> Path:
    """Ordner der Einrichtung (Umgebungsvariable, Einstellung, sonst die externe Platte)."""
    p = os.environ.get("KEVCAD_CALCULIX_DIR") or _einstellung().get("ordner")
    return Path(p).expanduser() if p else STANDARD


def _platte(o: Path) -> str | None:
    """Mount-Punkt unter /Volumes, auf dem der Ordner liegt (sonst None)."""
    teile = o.parts
    if len(teile) >= 3 and teile[0] == "/" and teile[1] == "Volumes":
        return str(Path("/Volumes") / teile[2])
    return None


def _platte_da(o: Path) -> bool:
    m = _platte(o)
    return m is None or os.path.ismount(m)


def finde() -> dict[str, Any]:
    """{"ok", "ccx", "ordner", "meldung", "einrichtbar"}: wo ccx liegt bzw. warum nicht."""
    direkt = os.environ.get("KEVCAD_CCX")
    if direkt:
        ok = os.access(direkt, os.X_OK)
        return {"ok": ok, "ccx": direkt if ok else None, "ordner": str(Path(direkt).parent), "einrichtbar": False,
                "meldung": None if ok else f"CalculiX nicht verfügbar: KEVCAD_CCX={direkt} ist kein Programm"}
    o = ordner()
    if not _platte_da(o):
        name = Path(_platte(o) or "").name
        return {"ok": False, "ccx": None, "ordner": str(o), "einrichtbar": False,
                "meldung": f"CalculiX nicht verfügbar (externe Platte {name} nicht angeschlossen)"}
    ccx = o / "env" / "bin" / "ccx"
    if os.access(ccx, os.X_OK):
        return {"ok": True, "ccx": str(ccx), "ordner": str(o), "einrichtbar": True, "meldung": None}
    return {"ok": False, "ccx": None, "ordner": str(o), "einrichtbar": True,
            "meldung": f"CalculiX ist noch nicht eingerichtet (Ordner {o}); Kev CAD richtet es beim ersten Gebrauch "
                       "ein, von Hand: python -m kevcad_kernel.statik.ccx.installation"}


def umgebung(ccx: str, faeden: int = 4) -> dict[str, str]:
    """Umgebung für einen ccx-Lauf: Fäden für Löser und Aufbau begrenzen, Bibliotheken der eigenen Umgebung."""
    return dict(os.environ, OMP_NUM_THREADS=str(faeden), CCX_NPROC_EQUATION_SOLVER=str(faeden),
                CCX_NPROC_STIFFNESS=str(faeden), CCX_NPROC_RESULTS=str(faeden), OPENBLAS_NUM_THREADS="1",
                PATH=str(Path(ccx).parent) + os.pathsep + os.environ.get("PATH", ""))


def version(ccx: str) -> str | None:
    try:
        r = subprocess.run([ccx, "-v"], capture_output=True, text=True, timeout=30, env=umgebung(ccx, 1))
    except (OSError, subprocess.TimeoutExpired):
        return None
    for zeile in (r.stdout + r.stderr).splitlines():
        if "Version" in zeile:
            return zeile.strip().split("Version", 1)[1].strip(" :")
    return None


PROBE_INP = """*NODE
1, 0, 0, 0
2, 10, 0, 0
3, 0, 10, 0
4, 0, 0, 10
*ELEMENT, TYPE=C3D4, ELSET=EALL
1, 1, 2, 3, 4
*MATERIAL, NAME=STAHL
*ELASTIC
210000, 0.3
*SOLID SECTION, ELSET=EALL, MATERIAL=STAHL
*BOUNDARY
1, 1, 3
2, 2, 3
3, 3, 3
*STEP
*STATIC
*CLOAD
4, 3, 100.
*NODE FILE
U
*END STEP
"""


def probe(ccx: str) -> dict[str, Any]:
    """Ein Tetraeder unter Zug: läuft ccx und schreibt eine Ergebnisdatei?"""
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="kevcad-ccx-probe-") as d:
        (Path(d) / "probe.inp").write_text(PROBE_INP, encoding="utf-8")
        try:
            r = subprocess.run([ccx, "-i", "probe"], cwd=d, capture_output=True, text=True, timeout=60,
                               env=umgebung(ccx, 1))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "meldung": f"ccx startet nicht: {exc}"}
        ok = r.returncode == 0 and (Path(d) / "probe.frd").exists()
        return {"ok": ok, "ms": round((time.perf_counter() - t0) * 1000, 1),
                "meldung": None if ok else f"ccx-Probe fehlgeschlagen (Code {r.returncode}): {(r.stdout + r.stderr)[-500:]}"}


def _groesse(p: Path) -> int:
    """Belegter Platz in Byte; harte Links (Umgebung und Zwischenspeicher teilen Dateien) zählen einmal."""
    n = 0
    gesehen: set[tuple[int, int]] = set()
    for wurzel, _, dateien in os.walk(p):
        for f in dateien:
            try:
                st = os.lstat(os.path.join(wurzel, f))
            except OSError:
                continue
            if (st.st_dev, st.st_ino) in gesehen:
                continue
            gesehen.add((st.st_dev, st.st_ino))
            n += st.st_size
    return n


def _micromamba(o: Path, melde: Callable[[str], None]) -> Path:
    mm = o / "bin" / "micromamba"
    if os.access(mm, os.X_OK):
        return mm
    melde(f"micromamba laden ({MICROMAMBA_URL})")
    req = urllib.request.Request(MICROMAMBA_URL, headers={"User-Agent": "kevcad/1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        daten = r.read()
    with tarfile.open(fileobj=io.BytesIO(daten), mode="r:bz2") as tar:
        mitglied = next((m for m in tar.getmembers() if m.name.endswith("bin/micromamba") and m.isfile()), None)
        if mitglied is None:
            raise RuntimeError("micromamba nicht im Archiv")
        f = tar.extractfile(mitglied)
        assert f is not None
        mm.parent.mkdir(parents=True, exist_ok=True)
        tmp = mm.with_suffix(".tmp")
        tmp.write_bytes(f.read())
    tmp.chmod(0o755)
    os.replace(tmp, mm)
    return mm


def einrichten(melde: Callable[[str], None] | None = None) -> dict[str, Any]:
    """micromamba laden und die Umgebung mit CalculiX anlegen (etwa 30 bis 60 s, rund 25 MB Download). Nur, wenn die
    Platte angeschlossen ist; legt nie einen Ordner unter /Volumes an."""
    melde = melde or (lambda s: None)
    t0 = time.perf_counter()
    if os.environ.get("KEVCAD_CCX"):
        return finde()
    o = ordner()
    if not _platte_da(o):
        return finde()
    o.mkdir(parents=True, exist_ok=True)
    (o / "LIESMICH.txt").write_text(LIESMICH, encoding="utf-8")
    mm = _micromamba(o, melde)
    wurzel = o / "mamba"
    env = dict(os.environ, MAMBA_ROOT_PREFIX=str(wurzel), CONDA_PKGS_DIRS=str(wurzel / "pkgs"),
               MAMBA_NO_BANNER="1")
    melde("CalculiX von conda-forge einrichten")
    befehl = [str(mm), "create", "-y", "-q", "--no-rc", "-r", str(wurzel), "-p", str(o / "env"), "-c", KANAL,
              "--override-channels", *PAKETE]
    r = subprocess.run(befehl, capture_output=True, text=True, timeout=900, env=env)
    if r.returncode != 0:
        return {"ok": False, "ccx": None, "ordner": str(o), "einrichtbar": True,
                "meldung": f"CalculiX nicht eingerichtet (micromamba Code {r.returncode}): {(r.stderr or r.stdout)[-800:]}"}
    subprocess.run([str(mm), "clean", "-y", "-q", "--tarballs", "-r", str(wurzel)], capture_output=True, text=True,
                   timeout=120, env=env)
    f = finde()
    if not f["ok"]:
        return f
    p = probe(f["ccx"])
    if not p["ok"]:
        return {**f, "ok": False, "meldung": p["meldung"]}
    stand = {"version": version(f["ccx"]), "eingerichtet": time.strftime("%Y-%m-%d %H:%M"), "quelle":
             f"{KANAL}::{' '.join(PAKETE)} über micromamba", "lizenz": "GPL-2.0-or-later",
             "groesse_mb": round(_groesse(o) / 1e6, 1), "dauer_s": round(time.perf_counter() - t0, 1)}
    (o / "stand.json").write_text(json.dumps(stand, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**f, **stand, "probe_ms": p["ms"]}


def sicherstellen(melde: Callable[[str], None] | None = None) -> dict[str, Any]:
    """ccx finden, sonst (Platte da, Ordner einrichtbar) einmalig einrichten."""
    f = finde()
    if f["ok"] or not f.get("einrichtbar"):
        return f
    try:
        return einrichten(melde)
    except Exception as exc:  # noqa: BLE001 - Netz weg, Platte voll …: als Meldung
        return {**f, "ok": False, "meldung": f"CalculiX nicht eingerichtet: {type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--pruefen" in argv:
        f = finde()
        if f["ok"]:
            f["version"] = version(f["ccx"])
            f["probe"] = probe(f["ccx"])
        print(json.dumps(f, ensure_ascii=False, indent=2))
        return 0 if f["ok"] else 1
    f = finde()
    if f["ok"] and "--wenn-fehlt" in argv:
        print(f"CalculiX vorhanden: {f['ccx']}")
        return 0
    if not f.get("einrichtbar") and not f["ok"]:
        print(f["meldung"])
        return 0 if "--wenn-fehlt" in argv else 1
    f = einrichten(lambda s: print(f"==> {s}", flush=True))
    print(json.dumps(f, ensure_ascii=False, indent=2))
    return 0 if f["ok"] or "--wenn-fehlt" in argv else 1


if __name__ == "__main__":
    raise SystemExit(main())
