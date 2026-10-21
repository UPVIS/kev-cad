"""Kommandozeile des Kernels: ``kevcad-kernel check`` prüft die Umgebung, ``kevcad-kernel serve`` startet den Server."""

from __future__ import annotations

import argparse
import sys
import time


def check() -> int:
    t0 = time.perf_counter()
    import build123d
    from ocp_tessellate.tessellator import tessellate

    import kevcad_kernel

    t_import = time.perf_counter() - t0
    box = build123d.Box(10, 20, 30)
    t1 = time.perf_counter()
    result = tessellate(box.wrapped, "check", deviation=0.1, quality=0.02, angular_tolerance=0.2)
    t_tess = time.perf_counter() - t1
    print(f"kevcad-kernel {kevcad_kernel.__version__}")
    print(f"build123d {build123d.__version__}, Python {sys.version.split()[0]}")
    print(f"Import {t_import:.2f} s, Testwürfel: {len(result['triangles']) // 3} Dreiecke, "
          f"{len(result['triangles_per_face'])} Flächen in {t_tess * 1000:.1f} ms")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kevcad-kernel", description="Kernel von Kev CAD")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Umgebung prüfen")
    serve = sub.add_parser("serve", help="Kernel-Server starten (Unix-Socket zur App, MCP über HTTP)")
    serve.add_argument("--socket", required=True, help="Pfad des Unix-Sockets zur App")
    serve.add_argument("--port", type=int, default=47823, help="Port für MCP über HTTP auf 127.0.0.1")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check()
    from kevcad_kernel.server import serve as run_server

    return run_server(socket_path=args.socket, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
