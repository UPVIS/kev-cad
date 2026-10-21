"""Rechenprozess: führt model.py in einem eigenen Unterprozess aus (``python -m kevcad_kernel.worker``).

Ein OCCT-Absturz oder eine Endlosschleife trifft nur diesen Prozess; die Laufzeit (runtime.py) beendet ihn nach dem
Zeitlimit und startet ihn neu. build123d bleibt zwischen den Läufen geladen.

Verbindung: stdin/stdout mit denselben Rahmen wie zur App (``protocol.encode_frame``/``FrameReader``). Die
ursprüngliche stdout wird nur für Rahmen benutzt; ``print()`` aus model.py wird je Lauf eingefangen, alles andere
(OCCT-Meldungen, Warnungen, faulthandler bei einem Absturz) geht auf stderr.

Nachrichten Eltern → Rechenprozess:

| type | Felder |
|---|---|
| ``RUN`` | ``run``, ``path`` (model.py), ``code``, ``params``, ``slow_ms``, ``deviation``, ``angular``, ``pruefen`` (Standard true: nach ``RUN_DONE`` prüfen, siehe pruefung/lauf.py) |
| ``EXEC`` | ``run``, ``code``, ``project``, ``deviation``, ``angular`` |
| ``PING`` | ``id`` → ``PONG`` |
| ``QUIT`` | – |

Rechenprozess → Eltern:

| type | Felder | Nutzlast |
|---|---|---|
| ``READY`` | ``pid``, ``build123d``, ``python``, ``import_s`` | – |
| ``STEP`` | ``run``, ``index``, ``text`` | – |
| ``PART`` | ``run``, ``name``, ``key`` (Formschlüssel), ``cached``, ``tess_ms``, ``density``, ``app`` (Kopf des PART_UPSERT ohne seq), ``app_len`` | Nutzlast des PART_UPSERT, danach BRep-Binärform |
| ``RUN_DONE`` / ``RUN_FAILED`` | ``run``, ``shown``, ``steps``, ``warnings``, ``params``, ``stdout``, ``duration_ms``, ``error`` (nur FAILED) | – |
| ``CHECK_DONE`` | ``run``, ``app`` (Kopf der Nachricht CHECK ohne seq), ``app_len`` – nach jedem ``RUN_DONE``, wenn ``RUN.pruefen`` nicht false ist | Nutzlast von CHECK |
| ``EXEC_RES`` | ``ok``, ``result``, ``stdout``, ``shown``, ``warnings``, ``error``/``line``/``excerpt``/``hint`` | – |
"""

from __future__ import annotations

import collections
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from kevcad_kernel.protocol import FrameReader, encode_frame

OnMessage = Callable[[int, dict[str, Any], bytes], None]  # (Generation, Kopf, Nutzlast)
OnExit = Callable[[int, int | None], None]  # (Generation, Exitcode)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


# ---------------------------------------------------------------------------------------------------------------------
# Seite des Rechenprozesses
# ---------------------------------------------------------------------------------------------------------------------


def main() -> int:
    import faulthandler

    proto_fd = os.dup(1)
    os.dup2(2, 1)  # alles, was sonst auf stdout ginge (print, OCCT), landet auf stderr
    faulthandler.enable(file=sys.stderr, all_threads=True)
    lock = threading.Lock()

    # Stirbt die Laufzeit (etwa hart beendet), soll ein hängender Lauf nicht verwaist weiterrechnen
    parent = os.getppid()

    def watchdog() -> None:
        while True:
            time.sleep(1.0)
            if os.getppid() != parent:
                os._exit(3)

    threading.Thread(target=watchdog, name="watchdog", daemon=True).start()

    def emit(header: dict[str, Any], payload: bytes = b"") -> None:
        data = encode_frame(header, payload)
        with lock:
            _write_all(proto_fd, data)

    t0 = time.perf_counter()
    import build123d

    from kevcad_kernel.runner import Runner
    from kevcad_kernel.tessellate import CACHE, tessellate_shape

    tessellate_shape(build123d.Box(1, 1, 1), cache=None)  # OCCT-Vernetzung einmal anwärmen
    CACHE.clear()
    runner = Runner(emit)
    emit({"type": "READY", "pid": os.getpid(), "build123d": build123d.__version__,
          "python": sys.version.split()[0], "import_s": round(time.perf_counter() - t0, 2)})

    reader = FrameReader()
    wartend: collections.deque = collections.deque()  # während der Prüfung angekommene Aufträge
    ende = False

    def neuer_auftrag() -> None:
        """Für die Prüfung nach einem Lauf: neue Rahmen einsammeln; ein neuer Lauf (oder QUIT) bricht sie ab."""
        nonlocal ende
        import select

        while select.select([0], [], [], 0)[0]:
            data = os.read(0, 1 << 16)
            if not data:
                ende = True
                break
            wartend.extend(reader.feed(data))
        if ende or any(h.get("type") in ("RUN", "QUIT") for h, _ in wartend):
            from kevcad_kernel.pruefung.pruefer import Abgebrochen

            raise Abgebrochen("neuer Lauf")

    while True:
        if wartend:
            frames = list(wartend)
            wartend.clear()
        elif ende:
            return 0
        else:
            try:
                data = os.read(0, 1 << 16)
            except InterruptedError:
                continue
            if not data:
                return 0
            frames = reader.feed(data)
        for header, _payload in frames:
            kind = header.get("type")
            try:
                if kind == "RUN":
                    result = runner.run(header)
                    emit(result)
                    if result.get("type") == "RUN_DONE" and header.get("pruefen", True):
                        try:
                            check, nutz = runner.pruefe(int(header["run"]), abbrechen=neuer_auftrag)
                        except Exception as exc:  # noqa: BLE001 - der Lauf ist schon gemeldet
                            check, nutz = {"type": "CHECK", "run": header["run"], "state": "failed",
                                           "message": f"Prüfung fehlgeschlagen: {type(exc).__name__}: {exc}",
                                           "befunde": [], "geometrie": []}, b""
                        emit({"type": "CHECK_DONE", "run": header["run"], "app": check, "app_len": len(nutz)}, nutz)
                elif kind == "EXEC":
                    emit(runner.execute(header))
                elif kind == "PING":
                    emit({"type": "PONG", "id": header.get("id")})
                elif kind == "QUIT":
                    return 0
            except Exception as exc:  # noqa: BLE001 - interner Fehler, nicht im Modell
                import traceback

                tb = traceback.format_exc(limit=8)
                print(tb, file=sys.stderr)
                if kind == "RUN":
                    emit({"type": "RUN_FAILED", "run": header.get("run"), "shown": [], "steps": [], "warnings": [],
                          "params": {}, "stdout": "", "duration_ms": 0,
                          "error": {"message": f"Interner Fehler im Rechenprozess: {type(exc).__name__}: {exc}",
                                    "line": None, "excerpt": "", "traceback": tb, "hint": ""}})
                elif kind == "EXEC":
                    emit({"type": "EXEC_RES", "ok": False, "error": f"Interner Fehler: {type(exc).__name__}: {exc}",
                          "stdout": "", "shown": [], "warnings": []})


# ---------------------------------------------------------------------------------------------------------------------
# Seite der Laufzeit
# ---------------------------------------------------------------------------------------------------------------------


class WorkerClient:
    """Startet und überwacht den Rechenprozess. Rückrufe kommen aus eigenen Lesefäden; ``generation`` zählt die
    Neustarts, damit Nachrichten eines beendeten Prozesses erkannt werden."""

    def __init__(self, on_message: OnMessage, on_exit: OnExit, python: str | None = None,
                 env: dict[str, str] | None = None, log: Callable[[str], None] | None = None) -> None:
        self._on_message = on_message
        self._on_exit = on_exit
        self._python = python or sys.executable
        self._env = env
        self._log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._ready = threading.Event()
        self.generation = 0
        self.info: dict[str, Any] = {}
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=60)
        self._err_threads: dict[int, threading.Thread] = {}

    # -- Zustand -------------------------------------------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def ready(self) -> bool:
        return self.alive and self._ready.is_set()

    def stderr_tail(self, lines: int = 20) -> str:
        return "\n".join(list(self._stderr_tail)[-lines:])

    # -- Steuerung -----------------------------------------------------------------------------------------------------

    def start(self) -> int:
        """Startet einen neuen Prozess (ein laufender wird vorher beendet). Gibt die Generation zurück."""
        with self._lock:
            self._kill_locked()
            self.generation += 1
            gen = self.generation
            self._ready = threading.Event()
            self.info = {}
            env = dict(os.environ if self._env is None else self._env)
            env.setdefault("PYTHONUNBUFFERED", "1")
            env.pop("PYTHONSTARTUP", None)
            self._proc = subprocess.Popen(
                [self._python, "-m", "kevcad_kernel.worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, env=env, close_fds=True,
            )
            proc = self._proc
        err = threading.Thread(target=self._read_stderr, args=(proc, gen), name=f"worker-err-{gen}", daemon=True)
        self._err_threads = {gen: err}
        err.start()
        threading.Thread(target=self._read_stdout, args=(proc, gen), name=f"worker-out-{gen}", daemon=True).start()
        return gen

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ev = self._ready
            if ev.wait(0.1):
                return self.alive
            if not self.alive:
                return False
        return False

    def send(self, header: dict[str, Any], payload: bytes = b"") -> bool:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False
        try:
            _write_all(proc.stdin.fileno(), encode_frame(header, payload))
            return True
        except (OSError, ValueError):
            return False

    def kill(self) -> None:
        with self._lock:
            self._kill_locked()

    def stop(self, timeout: float = 2.0) -> None:
        """Höflich beenden (QUIT), sonst hart."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            if proc.poll() is None:
                self.send({"type": "QUIT"})
                try:
                    proc.wait(timeout)
                except subprocess.TimeoutExpired:
                    pass
            self._kill_locked()

    def _kill_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    # -- Lesefäden -----------------------------------------------------------------------------------------------------

    def _read_stdout(self, proc: subprocess.Popen, gen: int) -> None:
        reader = FrameReader()
        fd = proc.stdout.fileno() if proc.stdout else -1
        try:
            while True:
                try:
                    data = os.read(fd, 1 << 20)
                except OSError:
                    break
                if not data:
                    break
                for header, payload in reader.feed(data):
                    if header.get("type") == "READY" and gen == self.generation:
                        self.info = header
                        self._ready.set()
                    try:
                        self._on_message(gen, header, payload)
                    except Exception as exc:  # noqa: BLE001
                        self._log(f"[kernel] Fehler beim Verarbeiten von {header.get('type')}: {exc!r}")
        finally:
            code = None
            try:
                code = proc.wait(5)
            except Exception:  # noqa: BLE001
                code = proc.poll()
            err = self._err_threads.get(gen)
            if err is not None:
                err.join(1.0)  # letzte stderr-Zeilen (faulthandler) vor der Meldung einsammeln
            try:
                self._on_exit(gen, code)
            except Exception as exc:  # noqa: BLE001
                self._log(f"[kernel] Fehler nach Prozessende: {exc!r}")

    def _read_stderr(self, proc: subprocess.Popen, gen: int) -> None:
        stream = proc.stderr
        if stream is None:
            return
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self._stderr_tail.append(line)
                    self._log(f"[rechenprozess {gen}] {line}")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    sys.exit(main())
