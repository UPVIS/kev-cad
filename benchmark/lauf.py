"""Benchmark der KI-CAD-Pipeline (PLAN-PIPELINE.md): Auftrag rein, fertiges Modell raus, alles gemessen.

Je Variante ein Lauf dieses Skripts. Der Kernel läuft hier im Prozess (Stand aus ``--kernel-src`` oder diesem
Checkout), MCP über HTTP; die Testvariante der App verbindet sich mit ihm (``KEVCAD_KERNEL_EXTERNAL=1``, Fenster
versteckt), damit Bilder, Ansichten und Lagebild echt sind. Für jede Aufgabe entsteht ein frisches Projekt, dann läuft
ein Agent als ``claude -p`` mit der Konfiguration der Variante. Gemessen werden aus seinem Ereignisstrom (eigene
Zeitstempel) und aus dem Kernel:

- Gesamtzeit Auftrag → Ende, Zeit bis zur ersten Geometrie, Zeit je Modellaufruf (bis zum ersten Zeichen, Erzeugung)
  und je Werkzeugaufruf,
- Tokens: Eingabe (neu, aus dem Zwischenspeicher, geschrieben), Ausgabe, davon Denken; Kosten laut CLI,
- Läufe des Kernels, gescheiterte Läufe (Korrekturschleifen),
- das Ergebnis mit dem Orakel der Aufgabe (orakel.py), unabhängig von Agent und eingebauter Prüfung.

Aufruf (aus dem Repo, mit der Umgebung des Kernels):

    tools/fern.sh testbau bench
    kernel/.venv/bin/python -u benchmark/lauf.py --variante baseline --aufgaben t1,t2 \
        --app "build/Kev CAD Test bench.app" --ablage "$HOME/Library/Caches/de.upvis.kevcad-bench"
    kernel/.venv/bin/python -u benchmark/lauf.py --referenz --aufgaben alle      # Stufe A: Musterlösungen, ohne LLM

Budgetwächter: Jeder Agentenlauf meldet die Auslastung des Wochenlimits (``rate_limit_event``). Liegt sie bei oder über
``--budget`` (Vorgabe 0,75), startet kein weiterer Lauf.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
REPO = HIER.parent
MCP_HELLO_PORT = 47997  # nur die Zahl in HELLO; nie 47823/47824 (Kevins App)


def stand_pfad(wert: str) -> str:
    """``@<git-ref>:<pfad>`` aus einem festen Stand des Repos (Tag, Commit) in einen Ordner auflösen: einmal per
    ``git archive`` nach ``~/Library/Caches/de.upvis.kevcad-bench/staende/<ref>`` entpackt, danach wiederverwendet.
    So bleibt etwa die Baseline (Tag ``pipeline-baseline``) messbar, wenn main längst weiter ist. Andere Werte bleiben."""
    if not wert.startswith("@"):
        return wert
    ref, _, pfad = wert[1:].partition(":")
    ziel = Path.home() / "Library/Caches/de.upvis.kevcad-bench/staende" / ref.replace("/", "_")
    if not (ziel / ".fertig").is_file():
        tmp = ziel.with_name(ziel.name + f".tmp{os.getpid()}")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        archiv = subprocess.run(["git", "-C", str(REPO), "archive", ref, "kernel/src", "skill"], capture_output=True,
                                check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(tmp)], input=archiv, check=True)
        (tmp / ".fertig").write_text(ref, encoding="utf-8")
        shutil.rmtree(ziel, ignore_errors=True)
        os.replace(tmp, ziel)
    return str(ziel / pfad)


def _kernel_src_einsetzen(src: str | None) -> None:
    """Fremden Kernel-Stand (Baseline-Kopie, Experiment) vor das installierte Paket legen; der Rechenprozess erbt
    PYTHONPATH."""
    if not src:
        return
    src = str(Path(src).expanduser().resolve())
    if os.environ.get("BENCH_KERNEL_SRC") == src:
        return
    env = dict(os.environ, BENCH_KERNEL_SRC=src, PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
    os.execve(sys.executable, [sys.executable, "-u", *sys.argv], env)


# ---------------------------------------------------------------------------------------------------------------------
# Umgebung


def arbeitsordner(ablage: Path, name: str) -> tuple[Path, Path]:
    """Arbeitsordner mit Katalogkopie und umgelenkten Ablagen (nichts von Kevin wird geschrieben)."""
    sys.path.insert(0, str(REPO / "kernel" / "tools"))
    from messen import KATALOG  # noqa: PLC0415

    arbeit = Path(tempfile.mkdtemp(prefix=f"kcbench-{name}-", dir="/tmp"))
    katalog = arbeit / "katalog"
    if KATALOG.is_dir():
        shutil.copytree(KATALOG, katalog)
    else:
        katalog.mkdir()
    projekte = arbeit / "projekte"
    projekte.mkdir()
    druck = arbeit / "druck"
    os.environ.update({
        "KEVCAD_CATALOG_DIR": str(katalog), "KEVCAD_PROJECTS_DIR": str(projekte),
        "KEVCAD_DRUCK_CACHE": str(druck / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(druck / "abgleich.json"),
        "KEVCAD_BAMBU_APP": str(druck / "kein-bambu-studio.app"), "KEVCAD_FESTKOERPER_CACHE": str(druck / "festkoerper"),
        "KEVCAD_FILAMENTE": str(druck / "filamente.json"), "KEVCAD_DRUCKER_SSDP": "0",
    })
    ablage.mkdir(parents=True, exist_ok=True)
    return arbeit, projekte


def claude_umgebung() -> dict[str, str]:
    """Umgebung für ``claude -p`` ohne die Variablen dieser Sitzung (sonst hängt der Lauf an ihr)."""
    return {k: v for k, v in os.environ.items()
            if not (k.startswith("CLAUDE_CODE_") or k == "CLAUDECODE" or k.startswith("ANTHROPIC_"))}


class App:
    """Testvariante der App mit diesem Kernel, Fenster versteckt hinter dem Schreibtischbild."""

    def __init__(self, pfad: Path, projekte: Path, log: Path) -> None:
        info = plistlib.loads((pfad / "Contents/Info.plist").read_bytes())
        self.bundle_id = info["CFBundleIdentifier"]
        self.name = info.get("CFBundleExecutable") or pfad.stem
        if ".test" not in self.bundle_id:
            raise SystemExit(f"{self.bundle_id}: nur Testvarianten")
        self.pfad, self.projekte, self.log = pfad, projekte, log
        self.socket = Path.home() / "Library/Application Support" / self.bundle_id / "kernel.sock"
        self.socket.parent.mkdir(parents=True, exist_ok=True)

    def starten(self) -> None:
        env = ["KEVCAD_KERNEL_EXTERNAL=1", f"KEVCAD_PROJECTS_DIR={self.projekte}", "KEVCAD_TEST_VERSTECKT=1",
               f"KEVCAD_CATALOG_DIR={os.environ['KEVCAD_CATALOG_DIR']}"]
        argv = ["open", "-g", "-n"]
        for e in env:
            argv += ["--env", e]
        subprocess.run([*argv, "--stderr", str(self.log), str(self.pfad)], check=True)

    def beenden(self) -> None:
        subprocess.run(["pkill", "-x", self.name], check=False)


# ---------------------------------------------------------------------------------------------------------------------
# Ein Agentenlauf


class Strom:
    """Ereignisse von ``claude -p --output-format stream-json`` mit eigenen Zeitstempeln."""

    def __init__(self, t0: float) -> None:
        self.t0 = t0
        self.ereignisse: list[tuple[float, dict[str, Any]]] = []
        self.auslastung: float | None = None
        self.ergebnis: dict[str, Any] | None = None

    def nimm(self, zeile: str) -> None:
        t = time.monotonic() - self.t0
        try:
            e = json.loads(zeile)
        except json.JSONDecodeError:
            return
        self.ereignisse.append((t, e))
        if e.get("type") == "rate_limit_event":
            info = e.get("rate_limit_info") or {}
            u = (info.get("unifiedWindows") or {}).get("seven_day", {}).get("utilization", info.get("utilization"))
            if isinstance(u, (int, float)):
                self.auslastung = float(u)
        elif e.get("type") == "result":
            self.ergebnis = e

    def auswerten(self) -> dict[str, Any]:
        """Modellaufrufe (Beginn, erstes Zeichen, Ende), Werkzeugaufrufe (Dauer bis zum Ergebnis), Zeitachse."""
        aufrufe: list[dict[str, Any]] = []
        offen: dict[str, Any] | None = None
        werkzeuge: dict[str, dict[str, Any]] = {}
        start = None
        for t, e in self.ereignisse:
            art = e.get("type")
            if art == "system" and e.get("subtype") == "init" and start is None:
                start = t
            if art == "stream_event":
                ev = e.get("event") or {}
                et = ev.get("type")
                if et == "message_start":
                    offen = {"beginn": t, "erstes": None, "ende": None, "usage": (ev.get("message") or {}).get("usage")}
                    aufrufe.append(offen)
                elif et == "content_block_delta" and offen is not None and offen["erstes"] is None:
                    offen["erstes"] = t
                elif et == "message_delta" and offen is not None:
                    offen["usage_ende"] = ev.get("usage")
                elif et == "message_stop" and offen is not None:
                    offen["ende"] = t
                    offen = None
            elif art == "assistant":
                for b in (e.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use":
                        werkzeuge[b["id"]] = {"name": b.get("name"), "start": t,
                                              "eingabe_zeichen": len(json.dumps(b.get("input"), ensure_ascii=False))}
            elif art == "user":
                inhalt = (e.get("message") or {}).get("content")
                for b in inhalt if isinstance(inhalt, list) else []:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in werkzeuge:
                        w = werkzeuge[b["tool_use_id"]]
                        w["ende"] = t
                        w["fehler"] = bool(b.get("is_error"))
                        c = b.get("content")
                        w["ergebnis_zeichen"] = len(c) if isinstance(c, str) else len(json.dumps(c, ensure_ascii=False))
        for a in aufrufe:
            a["bis_erstes_s"] = round(a["erstes"] - a["beginn"], 3) if a["erstes"] is not None else None
            a["dauer_s"] = round(a["ende"] - a["beginn"], 3) if a["ende"] is not None else None
        wl = []
        for w in werkzeuge.values():
            w["dauer_s"] = round(w["ende"] - w["start"], 3) if "ende" in w else None
            wl.append(w)
        r = self.ergebnis or {}
        usage = r.get("usage") or {}
        modell_s = sum(a["dauer_s"] or 0 for a in aufrufe)
        werkzeug_s = sum(w["dauer_s"] or 0 for w in wl)
        return {
            "cli_start_s": round(start, 3) if start is not None else None,
            "dauer_ms_cli": r.get("duration_ms"), "api_ms_cli": r.get("duration_api_ms"), "turns": r.get("num_turns"),
            "kosten_usd": r.get("total_cost_usd"), "fehler": r.get("is_error"), "text": (r.get("result") or "")[:4000],
            "tokens": {
                "eingabe": usage.get("input_tokens"), "cache_lesen": usage.get("cache_read_input_tokens"),
                "cache_schreiben": usage.get("cache_creation_input_tokens"), "ausgabe": usage.get("output_tokens"),
                "denken": (usage.get("output_tokens_details") or {}).get("thinking_tokens"),
            },
            "modellaufrufe": len(aufrufe), "modell_s": round(modell_s, 2), "werkzeug_s": round(werkzeug_s, 2),
            "bis_erstes_summe_s": round(sum(a["bis_erstes_s"] or 0 for a in aufrufe), 2),
            "aufrufe": [{k: a.get(k) for k in ("beginn", "bis_erstes_s", "dauer_s", "usage_ende")} for a in aufrufe],
            "werkzeuge": wl,
        }


class Beobachter(threading.Thread):
    """Kernel während des Agentenlaufs: erste neue Geometrie, Läufe mit Dauer und Ausgang."""

    def __init__(self, rt: Any, t0: float, lauf_vorher: int | None) -> None:
        super().__init__(daemon=True)
        self.rt, self.t0, self.vorher = rt, t0, lauf_vorher
        self.erste_geometrie: float | None = None
        self.laeufe: dict[int, dict[str, Any]] = {}
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.wait(0.1):
            t = time.monotonic() - self.t0
            try:
                st = self.rt.status()
            except Exception:  # noqa: BLE001
                continue
            last = st.get("last_run") or {}
            nr = last.get("run")
            if isinstance(nr, int) and (self.vorher is None or nr > self.vorher):
                eintrag = self.laeufe.setdefault(nr, {"gesehen_s": round(t, 2)})
                eintrag.update({k: last.get(k) for k in ("ok", "duration_ms", "error") if k in last})
                if self.erste_geometrie is None and (last.get("parts") or last.get("part_count")):
                    self.erste_geometrie = t
            if self.erste_geometrie is None:
                try:
                    recs = [r for r in self.rt.scene.records() if self.vorher is None or r.run > self.vorher]
                except Exception:  # noqa: BLE001
                    recs = []
                if recs:
                    self.erste_geometrie = t


def befundstand(rt: Any) -> dict[str, Any]:
    """Offene Befunde der fertigen Prüfung (Qualität neben dem Orakel): Zähler je Schwere, Arten, Meilensteine."""
    out: dict[str, Any] = {}
    try:
        p = rt.pruefen(warten_s=120, endstand=True)
        befunde = p.get("befunde") or []
        zaehler: dict[str, int] = {}
        for b in befunde:
            zaehler[str(b.get("schwere"))] = zaehler.get(str(b.get("schwere")), 0) + 1
        je_art: dict[str, int] = {}
        for b in befunde:
            je_art[f"{b.get('schwere')}:{b.get('art')}"] = je_art.get(f"{b.get('schwere')}:{b.get('art')}", 0) + 1
        out.update({"run": p.get("run"), "state": p.get("state"), "zaehler": zaehler,
                    "arten": sorted(je_art), "je_art": je_art})
    except Exception as exc:  # noqa: BLE001
        out["fehler"] = f"{type(exc).__name__}: {exc}"
    try:
        v = rt.versionen(limit=50) or {}
        m = v.get("meilensteine")
        out["meilensteine"] = len(m) if isinstance(m, (list, dict)) else m
        if not v.get("ok", True):
            out["versionen_fehler"] = str(v.get("error") or v.get("meldung"))[:200]
    except Exception as exc:  # noqa: BLE001
        out["meilensteine"] = None
        out["versionen_fehler"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def mcp_text(url: str, aufrufe: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Werkzeuge des Kernels über MCP aufrufen wie ein Hook beim Absenden des Auftrags (Lagebild in den Auftrag)."""
    import asyncio  # noqa: PLC0415

    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client import streamable_http  # noqa: PLC0415

    verbinden = getattr(streamable_http, "streamable_http_client", None) or streamable_http.streamablehttp_client

    async def holen() -> list[str]:
        out = []
        async with verbinden(url) as stroeme:
            async with ClientSession(stroeme[0], stroeme[1]) as s:
                await s.initialize()
                for name, eingabe in aufrufe:
                    r = await s.call_tool(name, eingabe)
                    out.append("\n".join(getattr(c, "text", "") for c in r.content if getattr(c, "type", "") == "text"))
        return out

    return asyncio.run(holen())


def projekt_vorbereiten(aufgabe: Any, rt: Any, projekt: Path) -> int | None:
    """Projekt der Aufgabe anlegen (Vorlage-Ordner, Vorlage-Datei oder leer), öffnen, rechnen; Nummer des Laufs."""
    ordner = getattr(aufgabe, "vorlage_ordner", None)
    if ordner:
        shutil.copytree(ordner, projekt, ignore=shutil.ignore_patterns(
            ".kevcad", "versionen", "output", "export*", "*.3mf", "*.step", "*.stp", "*.stl", "__pycache__",
            ".DS_Store", "dokumente"))
        rt.project_open(str(projekt))
        res = rt.run(timeout_s=900)
        rt.wait_idle(300)
        return res.get("run")
    projekt.mkdir(parents=True)
    if aufgabe.vorlage:
        (projekt / "model.py").write_text(aufgabe.vorlage, encoding="utf-8")
        rt.project_open(str(projekt))
        res = rt.run(timeout_s=600)
        rt.wait_idle(120)
        return res.get("run")
    rt.project_new(str(projekt), template="empty")
    rt.wait_idle(30)
    return (rt.status().get("last_run") or {}).get("run")


def agentenlauf(aufgabe: Any, variante: dict[str, Any], rt: Any, url: str, arbeit: Path, ablage: Path, wdh: int,
                args: argparse.Namespace, *, kennung: str | None = None, projekt: Path | None = None,
                agent: Path | None = None, fortsetzen: str | None = None, auftrag: str | None = None,
                zusatz: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ein Agentenlauf. Ohne ``projekt`` entsteht das Projekt der Aufgabe frisch; mit ``projekt`` arbeitet der Agent im
    schon offenen Projekt weiter (Kette), mit ``fortsetzen`` in derselben Sitzung (``--resume``)."""
    from orakel import Bogen  # noqa: PLC0415

    kennung = kennung or f"{aufgabe.id}-{wdh}"
    if projekt is None:
        projekt = Path(os.environ["KEVCAD_PROJECTS_DIR"]) / f"{variante['name']}-{kennung}"
        vorher = projekt_vorbereiten(aufgabe, rt, projekt)
    else:
        vorher = (rt.status().get("last_run") or {}).get("run")
    time.sleep(1.0)
    # Die App legt beim Start einen Entwurf an, wenn sie 0,35 s nach „Kernel bereit“ kein Projekt sieht; unter Last kam
    # das einmal nach dem Öffnen der Aufgabe an (06.11.2026, schlank-k t5). Vor dem Agenten also prüfen und notfalls
    # das Projekt der Aufgabe wieder öffnen.
    gewechselt = None
    offen = (rt.status().get("project") or {}).get("path")
    if not offen or Path(offen).resolve() != projekt.resolve():
        gewechselt = offen
        print(f"   offen war {offen}, öffne die Aufgabe wieder", flush=True)
        rt.project_open(str(projekt))
        vorher = rt.run(timeout_s=900).get("run")
        rt.wait_idle(300)
        time.sleep(1.0)
    befunde_vorher = befundstand(rt)

    # Arbeitsordner des Agenten: Skill der Variante als Projekt-Skill, nichts von Kevins globalen Regeln
    agent = agent or arbeit / f"agent-{variante['name']}-{kennung}"
    nachschlagen = agent / "kev-cad-referenz"  # Skill-Dateien zum Lesen auf Abruf, nicht als Skill angemeldet
    if not agent.exists():
        skills = agent / ".claude" / "skills"
        skills.mkdir(parents=True)
        if variante.get("skill"):
            shutil.copytree(Path(variante["skill"]).expanduser(), skills / "kev-cad")
        if variante.get("referenz"):
            shutil.copytree(Path(variante["referenz"]).expanduser(), nachschlagen)
    mcp = agent / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"kevcad": {"type": "http", "url": url}}}), encoding="utf-8")
    einstellungen = {"claudeMdExcludes": ["**"], "disableAllHooks": True, **(variante.get("einstellungen") or {})}

    t0 = time.monotonic()  # ab hier zählt alles, auch das Lagebild im Auftrag (wie ein Hook beim Absenden)
    prompt = auftrag or aufgabe.prompt
    lagebild_s = None
    if variante.get("lagebild_im_auftrag"):
        aufrufe: list[tuple[str, dict[str, Any]]] = [("status", {})]
        if aufgabe.art != "neu" or fortsetzen or auftrag:
            aufrufe.append(("modell", {"gliederung": True}))
        texte = mcp_text(url, aufrufe)
        lagebild_s = round(time.monotonic() - t0, 3)
        kopf = ("Beim Absenden abgefragt (status, bei vorhandenem Modell die Gliederung von model.py); nicht noch einmal "
                "abfragen, gleich loslegen.\n\n" if variante.get("lagebild_kopf") else "")
        prompt += "\n\n<lagebild>\n" + kopf + "\n\n".join(texte) + "\n</lagebild>"
    argv = ["claude", "-p", prompt, "--model", variante.get("modell") or args.modell,
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--setting-sources", variante.get("setting_sources") or "project,local", "--settings", json.dumps(einstellungen),
            "--mcp-config", str(mcp), "--strict-mcp-config", "--permission-mode", "bypassPermissions",
            "--disallowedTools", ",".join(variante.get("verboten") or
                                          ["Bash", "WebFetch", "WebSearch", "Task", "Agent", "mcp__kevcad__feedback"])]
    if variante.get("effort") or args.effort:
        argv += ["--effort", variante.get("effort") or args.effort]
    if variante.get("system_prompt"):
        argv += ["--system-prompt", Path(variante["system_prompt"]).read_text(encoding="utf-8")]
    if variante.get("append_system_prompt"):
        text = Path(variante["append_system_prompt"]).read_text(encoding="utf-8").replace("{REFERENZ}", str(nachschlagen))
        argv += ["--append-system-prompt", text]
    argv += list(variante.get("claude_args") or [])
    if fortsetzen:
        argv += ["--resume", fortsetzen]

    roh = ablage / f"{variante['name']}-{kennung}.jsonl"
    strom = Strom(t0)
    beob = Beobachter(rt, t0, vorher)
    beob.start()
    proc = subprocess.Popen(argv, cwd=agent, env=claude_umgebung(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    zeitgeber = threading.Timer(args.frist, lambda: os.killpg(proc.pid, signal.SIGTERM))
    zeitgeber.start()
    with roh.open("w", encoding="utf-8") as f:
        for zeile in proc.stdout:  # type: ignore[union-attr]
            f.write(f"{time.monotonic() - t0:.3f}\t{zeile}")
            strom.nimm(zeile)
    proc.wait()
    zeitgeber.cancel()
    gesamt = time.monotonic() - t0
    abgebrochen = proc.returncode not in (0, None) and strom.ergebnis is None
    beob.halt.set()
    rt.wait_idle(180)
    time.sleep(1.0)
    befunde_nachher = befundstand(rt)

    try:
        bogen = aufgabe.pruefen(rt)
    except Exception as exc:  # noqa: BLE001 - ein kaputtes Modell ist ein Ergebnis, kein Absturz des Benchmarks
        bogen = Bogen()
        bogen.pruefe(f"Orakel lief nicht: {type(exc).__name__}: {exc}", False)
    modell = projekt / "model.py"
    werte = strom.auswerten()
    runs = [w for w in werte["werkzeuge"] if str(w.get("name", "")).endswith("__run")]
    ergebnis = {
        "variante": variante["name"], "aufgabe": aufgabe.id, "titel": aufgabe.titel, "art": aufgabe.art, "wdh": wdh,
        "modell": variante.get("modell") or args.modell, "effort": variante.get("effort") or args.effort,
        "gesamt_s": round(gesamt, 2), "abgebrochen": abgebrochen, "rueckgabe": proc.returncode,
        "erste_geometrie_s": round(beob.erste_geometrie, 2) if beob.erste_geometrie is not None else None,
        "kernel_laeufe": beob.laeufe, "run_aufrufe": len(runs), "run_fehler": sum(bool(w.get("fehler")) for w in runs),
        "auslastung_nachher": strom.auslastung, "orakel": bogen.als_dict(),
        "befunde_vorher": befunde_vorher, "befunde_nachher": befunde_nachher, "lagebild_s": lagebild_s,
        "fortgesetzt": bool(fortsetzen), "sitzung": (strom.ergebnis or {}).get("session_id"),
        "projekt_gewechselt": gewechselt,
        "model_py_zeichen": len(modell.read_text(encoding="utf-8")) if modell.is_file() else None,
        "stderr": (proc.stderr.read() if proc.stderr else "")[-2000:], **werte, **(zusatz or {}),
    }
    if modell.is_file():
        shutil.copy2(modell, ablage / f"{variante['name']}-{kennung}.model.py")
    (ablage / f"{variante['name']}-{kennung}.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")
    return ergebnis


def kettenlauf(kette: Any, variante: dict[str, Any], rt: Any, url: str, arbeit: Path, ablage: Path, wdh: int,
               args: argparse.Namespace) -> list[dict[str, Any]]:
    """Stufe D: Neubau, dann dieselbe Änderung fortgesetzt (gleiche Sitzung) und frisch (Kopie des Stands, neue
    Sitzung). Ergebnisse als Aufgabe ``k1:erst``, ``k1:fort``, ``k1:frisch``."""
    basis = f"{kette.id}-{wdh}"
    a = agentenlauf(kette.erste, variante, rt, url, arbeit, ablage, wdh, args, kennung=f"{basis}-erst",
                    zusatz={"aufgabe": f"{kette.id}:erst", "kette": kette.id, "rolle": "erst"})
    projekt = Path(os.environ["KEVCAD_PROJECTS_DIR"]) / f"{variante['name']}-{basis}-erst"
    kopie = projekt.with_name(projekt.name + "-kopie")
    shutil.copytree(projekt, kopie, ignore=shutil.ignore_patterns(".kevcad", "versionen", "__pycache__", "output"))
    out = [a]
    if not a.get("sitzung"):
        print("   erste Sitzung ohne Kennung, Kette abgebrochen", flush=True)
        return out
    out.append(agentenlauf(kette.zweite, variante, rt, url, arbeit, ablage, wdh, args, kennung=f"{basis}-fort",
                           projekt=projekt, agent=arbeit / f"agent-{variante['name']}-{basis}-erst",
                           fortsetzen=a["sitzung"],
                           zusatz={"aufgabe": f"{kette.id}:fort", "kette": kette.id, "rolle": "fort"}))
    rt.project_open(str(kopie))
    rt.run(timeout_s=600)
    rt.wait_idle(120)
    out.append(agentenlauf(kette.zweite, variante, rt, url, arbeit, ablage, wdh, args, kennung=f"{basis}-frisch",
                           projekt=kopie, zusatz={"aufgabe": f"{kette.id}:frisch", "kette": kette.id,
                                                  "rolle": "frisch"}))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Stufe A: Musterlösungen ohne Sprachmodell


def referenzlauf(aufgabe: Any, rt: Any, ablage: Path) -> dict[str, Any]:
    from aufgaben import REFERENZ_PARAMS  # noqa: PLC0415

    projekt = Path(os.environ["KEVCAD_PROJECTS_DIR"]) / f"referenz-{aufgabe.id}"
    ordner = getattr(aufgabe, "vorlage_ordner", None)
    if ordner:
        shutil.copytree(ordner, projekt, ignore=shutil.ignore_patterns(
            ".kevcad", "versionen", "output", "export*", "*.3mf", "*.step", "*.stp", "*.stl", "__pycache__",
            ".DS_Store", "dokumente"))
    else:
        projekt.mkdir(parents=True)
        (projekt / "model.py").write_text(aufgabe.referenz, encoding="utf-8")
    rt.project_open(str(projekt))
    t0 = time.monotonic()
    res = rt.run(params=REFERENZ_PARAMS.get(aufgabe.id), timeout_s=600)
    kalt = time.monotonic() - t0
    rt.wait_idle(120)
    t1 = time.monotonic()
    res2 = rt.run(params=REFERENZ_PARAMS.get(aufgabe.id), timeout_s=600)
    warm = time.monotonic() - t1
    rt.wait_idle(120)
    if ordner:  # großes Modell: Fingerabdruck der Referenz für das Orakel
        from aufgaben import REFERENZEN, fingerabdruck  # noqa: PLC0415

        REFERENZEN.mkdir(exist_ok=True)
        (REFERENZEN / f"{aufgabe.id}.json").write_text(json.dumps(fingerabdruck(rt), ensure_ascii=False, indent=0),
                                                        encoding="utf-8")
    bogen = aufgabe.pruefen(rt)
    out = {"aufgabe": aufgabe.id, "ok_lauf": bool(res.get("ok", True)) and bool(res2.get("ok", True)),
           "run_kalt_s": round(kalt, 3), "run_warm_s": round(warm, 3), "orakel": bogen.als_dict(),
           "referenz_zeichen": len(aufgabe.referenz), "fehler": res.get("error")}
    print(f"{aufgabe.id} {aufgabe.titel}: Orakel {'bestanden' if bogen.bestanden else 'NICHT bestanden'} "
          f"({bogen.anteil:.0%}), run kalt {kalt:.2f} s, warm {warm:.2f} s", flush=True)
    for p in bogen.punkte:
        if not p.ok:
            print(f"   - {p.was}: ist {p.ist}, soll {p.soll}", flush=True)
    return out


def letzte_auslastung(wurzel: Path) -> float | None:
    """Zuletzt gemeldete Auslastung des Wochenlimits aus früheren Läufen (für den Wächter vor dem ersten Lauf)."""
    beste: tuple[float, float] | None = None
    for p in wurzel.glob("*/*.json"):
        if p.name == "zusammenfassung.json":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        u = d.get("auslastung_nachher") if isinstance(d, dict) else None  # pruefzeit.json ist eine Liste
        if isinstance(u, (int, float)) and (beste is None or p.stat().st_mtime > beste[0]):
            beste = (p.stat().st_mtime, float(u))
    return beste[1] if beste else None


def nachpruefen(ordner: Path, rt: Any) -> None:
    """Gespeicherte model.py früherer Läufe mit dem heutigen Orakel bewerten (ohne Sprachmodell), Ergebnis als
    ``orakel_nachgeprueft`` in die JSON des Laufs."""
    from aufgaben import ALLE  # noqa: PLC0415

    for modell in sorted(ordner.glob("*.model.py")):
        stamm = modell.name[: -len(".model.py")]
        lauf = ordner / f"{stamm}.json"
        if not lauf.is_file():
            continue
        d = json.loads(lauf.read_text(encoding="utf-8"))
        aufgabe = ALLE[d["aufgabe"]]
        projekt = Path(os.environ["KEVCAD_PROJECTS_DIR"]) / f"nach-{stamm}"
        projekt.mkdir(parents=True)
        shutil.copy2(modell, projekt / "model.py")
        rt.project_open(str(projekt))
        rt.run(timeout_s=600)
        rt.wait_idle(120)
        bogen = aufgabe.pruefen(rt)
        d["orakel_nachgeprueft"] = bogen.als_dict()
        lauf.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        fehlt = [f"{p.was}: {p.ist} statt {p.soll}" for p in bogen.punkte if not p.ok]
        print(f"{stamm}: {'bestanden' if bogen.bestanden else 'NICHT bestanden'} {bogen.anteil:.0%} {fehlt}", flush=True)


# ---------------------------------------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--variante", default="baseline", help="Name einer Datei in benchmark/varianten/ (ohne .json)")
    ap.add_argument("--aufgaben", default="alle")
    ap.add_argument("--wdh", type=int, default=1, help="Wiederholungen je Aufgabe")
    ap.add_argument("--app", default=str(REPO / "build" / "Kev CAD Test bench.app"))
    ap.add_argument("--ohne-app", action="store_true", help="ohne App (nur für --referenz)")
    ap.add_argument("--ablage", default=str(Path.home() / "Library/Caches/de.upvis.kevcad-bench"))
    ap.add_argument("--modell", default="opus")
    ap.add_argument("--effort", default=None)
    ap.add_argument("--frist", type=float, default=1500.0, help="Sekunden je Agentenlauf")
    ap.add_argument("--budget", type=float, default=0.75, help="höchste Auslastung des Wochenlimits")
    ap.add_argument("--kernel-src", default=None, help="kernel/src eines anderen Stands (sonst dieser Checkout)")
    ap.add_argument("--referenz", action="store_true", help="Stufe A: Musterlösungen ohne Sprachmodell")
    ap.add_argument("--nachpruefen", default=None, help="Ablage eines früheren Laufs mit dem heutigen Orakel bewerten")
    args = ap.parse_args()
    if args.nachpruefen:
        args.referenz, args.ohne_app = True, True
    # Grenze des Wochenlimits für laufende Runden ändern: benchmark/BUDGET mit einer Zahl (Kevin, 06.11.2026: „Die
    # Benchmark kann gerne ohne Limit voll weiterlaufen“ → 1.01, also keine Grenze)
    budget_datei = HIER / "BUDGET"
    if budget_datei.is_file():
        try:
            args.budget = float(budget_datei.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    # Laufende Runde umplanen, ohne sie abzubrechen: benchmark/STOP mit Aufgaben (Komma) überspringt genau diese, leer alle
    stopp = HIER / "STOP"
    if stopp.is_file() and not args.referenz:
        liste = {a.strip() for a in stopp.read_text(encoding="utf-8").replace("\n", ",").split(",") if a.strip()}
        if not liste or set(args.aufgaben.split(",")) <= liste:
            print(f"STOP-Datei: {args.aufgaben} übersprungen", flush=True)
            return 0

    variante: dict[str, Any] = {"name": "referenz"}
    if not args.referenz:
        variante = json.loads((HIER / "varianten" / f"{args.variante}.json").read_text(encoding="utf-8"))
        variante["name"] = args.variante
        for schluessel in ("skill", "referenz", "append_system_prompt", "system_prompt", "kernel_src"):
            if variante.get(schluessel):
                variante[schluessel] = stand_pfad(variante[schluessel])
                if not Path(variante[schluessel]).is_absolute():
                    variante[schluessel] = str((REPO / variante[schluessel]).resolve())
        args.kernel_src = args.kernel_src or variante.get("kernel_src")
    _kernel_src_einsetzen(args.kernel_src)
    sys.path.insert(0, str(HIER))
    from aufgaben import ALLE, KETTEN  # noqa: PLC0415

    ids = list(ALLE) if args.aufgaben == "alle" else [a.strip() for a in args.aufgaben.split(",") if a.strip()]
    stamm = time.strftime("%Y%m%d-%H%M%S")
    ablage = Path(args.ablage).expanduser() / f"{stamm}-{variante['name']}"
    arbeit, projekte = arbeitsordner(ablage, variante["name"])

    from kevcad_kernel.runtime import KernelRuntime  # noqa: PLC0415
    from kevcad_kernel.server import KevcadHTTPServer  # noqa: PLC0415

    import kevcad_kernel  # noqa: PLC0415

    print(f"Kernel aus {Path(kevcad_kernel.__file__).parent}", flush=True)
    app = None if (args.referenz and args.ohne_app) else App(Path(args.app).resolve(), projekte, arbeit / "app.log")
    socket = app.socket if app else arbeit / "k.sock"
    if socket.exists():
        socket.unlink()
    rt = KernelRuntime(str(socket), MCP_HELLO_PORT, auto_run=False, run_timeout_s=900, log=lambda line: None)
    server = None
    ergebnisse: list[dict[str, Any]] = []
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        server = KevcadHTTPServer(rt, 0).start_in_thread()
        if app:
            app.starten()
            # Öffentlicher Stand statt rt._link: app_link.py bekommt mehrere Verbindungen (iPad, 06.11.2026)
            ende = time.monotonic() + 40
            while time.monotonic() < ende and not rt.status().get("app_connected"):
                time.sleep(0.1)
            if not rt.status().get("app_connected"):
                raise SystemExit("App meldet sich nicht")
            time.sleep(2.0)  # HELLO_APP und Einstellungen der App ankommen lassen
            # Den Start-Entwurf der App abwarten, damit er nicht später das Projekt der Aufgabe verdrängt
            ende = time.monotonic() + 10
            while time.monotonic() < ende and not (rt.status().get("project") or {}).get("path"):
                time.sleep(0.1)
            time.sleep(0.5)
            print("App verbunden", flush=True)
        if args.nachpruefen:
            nachpruefen(Path(args.nachpruefen).expanduser(), rt)
            ids = []
        auslastung = letzte_auslastung(Path(args.ablage).expanduser())
        if auslastung is not None:
            print(f"Wochenlimit zuletzt bei {auslastung:.0%} (Grenze {args.budget:.0%})", flush=True)
        for aid in ids:
            aufgabe = KETTEN.get(aid) or ALLE[aid]
            for wdh in range(1, args.wdh + 1):
                if args.referenz:
                    ergebnisse.append(referenzlauf(aufgabe, rt, ablage))
                    continue
                if auslastung is not None and auslastung >= args.budget:
                    print(f"Budget erreicht ({auslastung:.0%} ≥ {args.budget:.0%}): keine weiteren Läufe", flush=True)
                    raise StopIteration
                print(f"{variante['name']} {aid} #{wdh}: läuft …", flush=True)
                if aid in KETTEN:
                    neu = kettenlauf(aufgabe, variante, rt, server.url, arbeit, ablage, wdh, args)
                else:
                    neu = [agentenlauf(aufgabe, variante, rt, server.url, arbeit, ablage, wdh, args)]
                for e in neu:
                    ergebnisse.append(e)
                    auslastung = e.get("auslastung_nachher", auslastung)
                    o = e["orakel"]
                    z = (e.get("befunde_nachher") or {}).get("zaehler")
                    print(f"   {e['aufgabe']}: {e['gesamt_s']:.0f} s, erste Geometrie {e['erste_geometrie_s']} s, "
                          f"{e['turns']} Turns, Ausgabe {e['tokens']['ausgabe']} (Denken {e['tokens']['denken']}), "
                          f"Orakel {'OK' if o['bestanden'] else 'FEHLER'} {o['anteil']:.0%}, Befunde {z}, "
                          f"Auslastung {e.get('auslastung_nachher')}", flush=True)
    except StopIteration:
        pass
    finally:
        if app:
            app.beenden()
        rt.close()
        pool = getattr(rt, "_pool", None)
        if pool is not None:
            pool.shutdown(wait=True)
        (ablage / "zusammenfassung.json").write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
        print(f"Ergebnisse: {ablage}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
