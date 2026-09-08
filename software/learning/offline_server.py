#!/usr/bin/env python3
"""Run the existing MuJoCo lab with physical-device requests disabled."""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
for component in ("sim", "shared", "jetson", "pi"):
    sys.path.insert(0, str(ROOT / "software" / component))

from lab_server import Lab, make_handler


class OfflineLab(Lab):
    @staticmethod
    def _request_json(*args, **kwargs):
        raise OSError("Offline learning mode: physical-device requests are disabled")

    def camera_frame(self):
        raise OSError("Offline learning mode: no physical camera")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    handler = make_handler(OfflineLab("http://127.0.0.1:1", "http://127.0.0.1:1"))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    url = f"http://127.0.0.1:{server.server_port}/?view=sim"
    print(f"Offline MuJoCo lab: {url}\nControl-C stops this server.", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
