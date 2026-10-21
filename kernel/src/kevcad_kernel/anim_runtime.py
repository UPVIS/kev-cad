"""Animation in der Kernel-Laufzeit (Phase 5, Strang ANI): Ablage der ausgewerteten Animationen, Nachrichten an die
App (ANIM_DEF, ANIM_REMOVE, ANIM_COLLISIONS, ANIM_PLAY, ANIM_SEEK, ANIM_VIDEO_REQ) und die Dienstmethoden für MCP.

``AnimationRuntimeMixin`` wird in ``KernelRuntime`` eingemischt und nutzt dessen Bausteine (``_send_app``,
``_request``, ``_app_lock``, ``_occ_lock``, ``_pool``, ``scene``, ``_project``, ``_link``). So bleibt runtime.py bis
auf wenige Aufrufstellen unverändert.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.animation import unpack_matrices

APP_NOT_CONNECTED = "App nicht verbunden"
NO_ANIMATION = ("Keine Animation im Projekt: in model.py `anim = animation(dauer=8, fps=30)` anlegen, Spuren setzen "
                "(anim.bewege, anim.rolle, …) und run aufrufen.")
VIDEO_FORMATS = ("mp4", "prores")


@dataclass
class StoredAnimation:
    name: str
    run: int
    header: dict[str, Any]  # Kopf von ANIM_DEF ohne type/seq
    payload: bytes  # Nutzlast von ANIM_DEF
    matrices: np.ndarray  # (N, P, 4, 4)
    times: np.ndarray  # (N,)
    nospin: dict[str, np.ndarray] = field(default_factory=dict)
    spins: dict[str, tuple[list[float], list[float]]] = field(default_factory=dict)
    erlaubt: list[tuple[list[str], list[str]]] = field(default_factory=list)
    eval_ms: float = 0.0
    kollisionen: dict[str, Any] | None = None  # letztes ANIM_COLLISIONS (ohne type/seq)

    @property
    def teile(self) -> list[str]:
        return list(self.header.get("teile") or [])

    @property
    def frames(self) -> int:
        return int(self.header.get("bilder") or len(self.times))

    @property
    def dauer(self) -> float:
        return float(self.header.get("dauer") or 0.0)

    @property
    def fps(self) -> float:
        return float(self.header.get("fps") or 30.0)

    def summary(self) -> dict[str, Any]:
        out = {"name": self.name, "dauer": self.dauer, "fps": self.fps, "bilder": self.frames,
               "teile": len(self.teile), "kamerafahrt": bool(self.header.get("kamera")),
               "spuren": self.header.get("spuren", 0), "standard": bool(self.header.get("standard")),
               "auswertung_ms": round(self.eval_ms, 1)}
        if self.header.get("warnungen"):
            out["warnungen"] = list(self.header["warnungen"])
        if self.kollisionen is not None:
            out["kollisionen"] = len(self.kollisionen.get("kollisionen") or [])
        return out


def stored_from_worker(header: dict[str, Any], payload: bytes) -> StoredAnimation:
    """Nachricht ``ANIM`` des Rechenprozesses (animation.worker_message) → Ablage."""
    d = dict(header["def"])
    n, p = int(d["bilder"]), len(d["teile"])
    app_len = int(header.get("app_len", len(payload)))
    app_payload = payload[:app_len]
    mats = unpack_matrices(app_payload[: n * p * 48], n, p)
    nospin_names = list(header.get("nospin") or [])
    nospin: dict[str, np.ndarray] = {}
    if nospin_names:
        extra = unpack_matrices(payload[app_len:], n, len(nospin_names))
        nospin = {name: extra[:, i] for i, name in enumerate(nospin_names)}
    dauer, fps = float(d["dauer"]), float(d["fps"])
    times = np.minimum(np.arange(n, dtype=float) / fps, dauer)
    spins = {k: (list(v[0]), list(v[1])) for k, v in (header.get("spins") or {}).items()}
    erlaubt = [(list(a), list(b)) for a, b in (header.get("erlaubt") or [])]
    return StoredAnimation(name=str(d["name"]), run=int(d.get("run") or header.get("run") or 0), header=d,
                           payload=app_payload, matrices=mats, times=times, nospin=nospin, spins=spins,
                           erlaubt=erlaubt, eval_ms=float(header.get("eval_ms") or 0.0))


def visibility_at(header: dict[str, Any], part: str, t: float) -> bool:
    """Sichtbarkeit eines Teils zur Zeit ``t`` nach ``sichtbar`` aus ANIM_DEF (ohne Eintrag: sichtbar)."""
    for entry in header.get("sichtbar") or []:
        if part in entry.get("teile", []):
            events = entry.get("zeiten") or []
            if not events:
                return True
            state = not bool(events[0][1])
            for et, an in events:
                if t + 1e-9 >= et:
                    state = bool(an)
            return state
    return True


class AnimationHub:
    """Animationen des letzten erfolgreichen Laufs und der Abspielstand, den die App meldet. Threadsicher."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.anims: dict[str, StoredAnimation] = {}
        self.app_state: dict[str, Any] = {}
        self.symmetry: dict[tuple, bool] = {}

    def replace(self, new: list[StoredAnimation]) -> list[str]:
        with self.lock:
            old = self.anims
            self.anims = {a.name: a for a in new}
            for a in new:  # Kollisionen bleiben nur, wenn die Bewegung gleich geblieben ist
                prev = old.get(a.name)
                if prev is not None and prev.payload == a.payload and prev.header.get("teile") == a.header.get("teile"):
                    a.kollisionen = prev.kollisionen
            return [n for n in old if n not in self.anims]

    def clear(self) -> list[str]:
        with self.lock:
            names = list(self.anims)
            self.anims = {}
            self.app_state = {}
            return names

    def get(self, name: str | None) -> StoredAnimation | None:
        with self.lock:
            if not self.anims:
                return None
            if name is None:
                current = self.app_state.get("name")
                if current in self.anims:
                    return self.anims[current]
                return next(iter(self.anims.values()))
            return self.anims.get(name)

    def all(self) -> list[StoredAnimation]:
        with self.lock:
            return list(self.anims.values())

    def unknown(self, name: str) -> str:
        names = [a.name for a in self.all()]
        if not names:
            return NO_ANIMATION
        return f"Animation {name!r} gibt es nicht. Vorhanden: {', '.join(repr(n) for n in names)}"


class AnimationRuntimeMixin:
    """Animationsteil von ``KernelRuntime`` (siehe Moduldoku)."""

    @property
    def anim_hub(self) -> AnimationHub:
        hub = self.__dict__.get("_anim_hub")
        if hub is None:
            hub = self.__dict__.setdefault("_anim_hub", AnimationHub())
        return hub

    # -- Aufrufstellen in runtime.py -----------------------------------------------------------------------------------

    def _anim_publish(self, job: Any, result: dict[str, Any]) -> None:
        """Nach RUN_END und BOM eines erfolgreichen Laufs: neue Animationen ablegen und an die App schicken."""
        new = []
        for header, payload in getattr(job, "animations", []) or []:
            try:
                new.append(stored_from_worker(header, payload))
            except Exception as exc:  # noqa: BLE001
                result.setdefault("warnings", []).append(f"Animation nicht gelesen: {type(exc).__name__}: {exc}")
        removed = self.anim_hub.replace(new)
        with self._app_lock:  # type: ignore[attr-defined]
            for name in removed:
                self._send_app({"type": "ANIM_REMOVE", "name": name})  # type: ignore[attr-defined]
            for a in new:
                self._send_app({"type": "ANIM_DEF", **a.header}, a.payload)  # type: ignore[attr-defined]
                if a.kollisionen is not None:
                    self._send_app({"type": "ANIM_COLLISIONS", **a.kollisionen})  # type: ignore[attr-defined]
        if new:
            result["animationen"] = [a.summary() for a in new]

    def _anim_project_changed(self) -> None:
        for name in self.anim_hub.clear():
            self._send_app({"type": "ANIM_REMOVE", "name": name})  # type: ignore[attr-defined]

    def _anim_on_connect(self, conn: Any) -> None:
        for a in self.anim_hub.all():
            conn.send({"type": "ANIM_DEF", **a.header}, a.payload)
            if a.kollisionen is not None:
                conn.send({"type": "ANIM_COLLISIONS", **a.kollisionen})

    def _anim_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        """Nachrichten der App zur Animation; True = erledigt."""
        if kind == "ANIM_STATE":
            with self.anim_hub.lock:
                self.anim_hub.app_state = {k: header.get(k) for k in
                                           ("name", "zeit", "bild", "spielt", "schleife", "geschwindigkeit")}
            return True
        if kind == "ANIM_COLLISIONS_REQ":
            def job() -> None:
                rid = header.get("id")
                res = self.collision_check(header.get("name"), int(header.get("schritt") or 3), reply_to=rid)
                if not res.get("ok"):
                    self._send_app({"type": "ERROR", "reply_to": rid, "message": res.get("error", "")})  # type: ignore[attr-defined]

            self._pool.submit(job)  # type: ignore[attr-defined]
            return True
        return False

    # -- KernelService (Phase 5) ---------------------------------------------------------------------------------------

    def animation_list(self) -> dict[str, Any]:
        anims = self.anim_hub.all()
        with self.anim_hub.lock:
            state = dict(self.anim_hub.app_state)
        out: dict[str, Any] = {"ok": True, "animationen": [a.summary() for a in anims], "stand": state or None}
        if not anims:
            out["hinweis"] = NO_ANIMATION
        return out

    def _anim_target(self, name: str | None) -> tuple[StoredAnimation | None, str | None]:
        a = self.anim_hub.get(name)
        if a is None:
            return None, (self.anim_hub.unknown(name) if name else NO_ANIMATION)
        return a, None

    def animation_play(self, name: str | None = None, an: bool = True, schleife: bool = False,
                       geschwindigkeit: float = 1.0, von_vorn: bool = False) -> dict[str, Any]:
        a, err = self._anim_target(name)
        if err:
            return {"ok": False, "error": err}
        if not self._link.connected:  # type: ignore[attr-defined]
            return {"ok": False, "error": APP_NOT_CONNECTED}
        req = {"type": "ANIM_PLAY", "name": a.name, "an": bool(an), "schleife": bool(schleife),
               "geschwindigkeit": float(geschwindigkeit), "von_vorn": bool(von_vorn)}
        reply, _, error = self._request(req, 10)  # type: ignore[attr-defined]
        if error:
            return {"ok": False, "error": error}
        if not reply.get("ok", True):
            return {"ok": False, "error": reply.get("message") or "App hat abgelehnt"}
        return {"ok": True, "name": a.name, "an": bool(an), "schleife": bool(schleife),
                "geschwindigkeit": float(geschwindigkeit), "dauer": a.dauer, "message": reply.get("message")}

    def animation_seek(self, zeit: float, name: str | None = None) -> dict[str, Any]:
        a, err = self._anim_target(name)
        if err:
            return {"ok": False, "error": err}
        if not 0 <= float(zeit) <= a.dauer + 1e-9:
            return {"ok": False, "error": f"zeit {zeit:g} s liegt außerhalb der Animation {a.name!r} (0 bis "
                                          f"{a.dauer:g} s)"}
        if not self._link.connected:  # type: ignore[attr-defined]
            return {"ok": False, "error": APP_NOT_CONNECTED}
        reply, _, error = self._request({"type": "ANIM_SEEK", "name": a.name, "zeit": float(zeit)}, 10)  # type: ignore[attr-defined]
        if error:
            return {"ok": False, "error": error}
        if not reply.get("ok", True):
            return {"ok": False, "error": reply.get("message") or "App hat abgelehnt"}
        frame = int(round(float(zeit) * a.fps))
        return {"ok": True, "name": a.name, "zeit": float(zeit), "bild": min(frame, a.frames - 1), "dauer": a.dauer}

    def animation_video(self, name: str | None = None, breite: int = 1920, hoehe: int | None = None,
                        fps: float | None = None, kamera: str | None = None, format: str = "mp4") -> dict[str, Any]:  # noqa: A002
        a, err = self._anim_target(name)
        if err:
            return {"ok": False, "error": err}
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen"}
        fmt = str(format or "mp4").lower()
        if fmt not in VIDEO_FORMATS:
            return {"ok": False, "error": f"format {format!r} unbekannt (mp4 = H.264, prores = ProRes 422)"}
        if not self._link.connected:  # type: ignore[attr-defined]
            return {"ok": False, "error": APP_NOT_CONNECTED}
        w = max(64, min(int(breite), 7680)) // 2 * 2
        h = (int(hoehe) if hoehe else round(w * 9 / 16)) // 2 * 2
        rate = float(fps) if fps else a.fps
        if not 1 <= rate <= 120:
            return {"ok": False, "error": f"fps {rate:g} liegt außerhalb von 1 bis 120"}
        from kevcad_kernel.export import safe_name

        out_dir = proj.output_dir / "animationen"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Ordner {out_dir} nicht anlegbar: {exc}"}
        path = (out_dir / f"{safe_name(a.name)}.{'mov' if fmt == 'prores' else 'mp4'}").resolve()
        frames = int(round(a.dauer * rate)) + 1
        timeout = 60.0 + frames * max(0.4, w * h / 1920 / 1080 * 0.6)
        req = {"type": "ANIM_VIDEO_REQ", "name": a.name, "width": w, "height": h, "fps": rate, "kamera": kamera,
               "format": fmt, "path": str(path)}
        t0 = time.perf_counter()
        reply, _, error = self._request(req, timeout)  # type: ignore[attr-defined]
        if error:
            return {"ok": False, "error": error}
        if not reply.get("ok", False):
            return {"ok": False, "error": reply.get("message") or "Video nicht erstellt"}
        out = {"ok": True, "name": a.name, "path": reply.get("path") or str(path), "width": w, "height": h,
               "fps": rate, "bilder": reply.get("frames", frames), "format": fmt,
               "ms": reply.get("ms") or int((time.perf_counter() - t0) * 1000), "kamera": reply.get("kamera")}
        if reply.get("message"):
            out["message"] = reply["message"]
        return out

    def collision_check(self, name: str | None = None, schritt: int = 3, toleranz: float = 0.05,
                        reply_to: str | None = None) -> dict[str, Any]:
        """Kollisionsprüfung der Animation an jedem ``schritt``-ten Bild (und dem letzten); Ergebnis geht als
        ANIM_COLLISIONS an die App."""
        from kevcad_kernel.anim_kollision import (
            bewegte_paare,
            huellkugel,
            pruefe_kollisionen,
            rotationssymmetrisch,
            zusammenfassen,
        )
        from kevcad_kernel.protocol import unpack_part

        a, err = self._anim_target(name)
        if err:
            return {"ok": False, "error": err}
        step = max(1, int(schritt or 3))
        frames = list(range(0, a.frames, step))
        if frames[-1] != a.frames - 1:
            frames.append(a.frames - 1)
        records = {r.name: r for r in self.scene.records() if not r.name.startswith("Skizze/")}  # type: ignore[attr-defined]
        missing = [p for p in a.teile if p not in records]
        if missing:
            return {"ok": False, "error": f"Teile der Animation fehlen in der Szene: {', '.join(missing[:5])} "
                                          "(erst neu rechnen)"}
        t0 = time.perf_counter()
        lagen: dict[str, np.ndarray] = {}
        reduced: list[str] = []
        with self._occ_lock:  # type: ignore[attr-defined]
            formen = {n: r.shape for n, r in records.items()}
            for i, part in enumerate(a.teile):
                m = a.matrices[:, i]
                if part in a.spins and part in a.nospin:
                    rec = records[part]
                    p, d = a.spins[part]
                    key = (rec.key, tuple(np.round(p, 4)), tuple(np.round(d, 6)))
                    sym = self.anim_hub.symmetry.get(key)
                    if sym is None:
                        sym = rotationssymmetrisch(formen[part], p, d)
                        self.anim_hub.symmetry[key] = sym
                    if sym:
                        m = a.nospin[part]
                        reduced.append(part)
                lagen[part] = m

            def allowed(x: str, y: str) -> bool:
                return any((x in pa and y in pb) or (x in pb and y in pa) for pa, pb in a.erlaubt)

            def visible(part: str, k: int) -> bool:
                return visibility_at(a.header, part, float(a.times[k]))

            names = list(records)
            pairs = bewegte_paare(names, lagen, frames, allowed)
            boxes = {n: (r.bbox.get("min", [0, 0, 0]), r.bbox.get("max", [0, 0, 0])) for n, r in records.items()}
            kugeln = {}
            for part in a.teile:  # Hüllkugeln der bewegten Teile um die Mitte ihres Hüllquaders (rollende Kugel)
                lo, hi = boxes[part]
                try:
                    pts = unpack_part(records[part].header, records[part].payload)["positions"]
                except Exception:  # noqa: BLE001
                    continue
                kugeln[part] = huellkugel(pts, (np.asarray(lo, float) + np.asarray(hi, float)) / 2.0)
            befunde, stats = pruefe_kollisionen(formen, lagen, a.times, bilder=frames, paare=pairs, huellen=boxes,
                                                kugeln=kugeln, toleranz=float(toleranz), sichtbar=visible,
                                                zeitlimit_s=120)
        spans = zusammenfassen(befunde, frames)
        stats.update({"schritt": step, "geprueft_bilder": len(frames), "symmetrisch": reduced,
                      "ms": round((time.perf_counter() - t0) * 1000.0, 1)})
        payload = {"name": a.name, "run": a.run, "kollisionen": spans, "geprueft": stats}
        a.kollisionen = payload
        msg = {"type": "ANIM_COLLISIONS", **payload}
        if reply_to:
            msg["reply_to"] = reply_to
        self._send_app(msg)  # type: ignore[attr-defined]
        return {"ok": True, **payload}
