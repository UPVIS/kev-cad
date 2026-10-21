"""Startet einen Kernel-Server mit der Attrappe ``FakeService`` als eigenen Prozess (für die Brücken-Tests).

    python fake_kernel.py --port 12345 [--pidfile datei] [--project Name] [--via-serve --marker datei]

``--via-serve`` geht über ``kevcad_kernel.server.serve`` (wie ``kevcad-kernel serve``), mit der Attrappe statt der
echten Laufzeit; ``close()`` schreibt dann ``closed`` in die Markierungsdatei. So lässt sich das Beenden per SIGTERM
prüfen.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_service import FakeService  # noqa: E402


class MarkingFake(FakeService):
    def __init__(self, marker: str | None, project: str) -> None:
        super().__init__(project)
        self.marker = marker

    def close(self) -> None:
        super().close()
        if self.marker:
            Path(self.marker).write_text("closed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--pidfile")
    parser.add_argument("--project", default="Attrappe")
    parser.add_argument("--via-serve", action="store_true")
    parser.add_argument("--marker")
    args = parser.parse_args()
    if args.pidfile:
        Path(args.pidfile).write_text(str(os.getpid()))

    import kevcad_kernel.server as server

    if args.via_serve:
        server.create_service = lambda socket_path, port: MarkingFake(args.marker, args.project)  # type: ignore
        return server.serve("/tmp/kevcad-test-unbenutzt.sock", args.port)

    import anyio

    http = server.KevcadHTTPServer(MarkingFake(args.marker, args.project), args.port)
    anyio.run(http.serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
