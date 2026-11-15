#!/usr/bin/env python3
"""Talk to a program running in developer mode (python app.py --dev).

    python tools/devctl.py state
    python tools/devctl.py checks
    python tools/devctl.py people
    python tools/devctl.py select "Ivo"
    python tools/devctl.py action add_child          (on whoever is selected)
    python tools/devctl.py screenshot /tmp/now.png
    python tools/devctl.py overlay on
    python tools/devctl.py log 20
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket

from devtools.devmode import server_name


def send(command, arg=None, timeout_ms=600000):
    QCoreApplication.instance() or QCoreApplication([])
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(2000):
        raise SystemExit("No program in developer mode is running (start it with: python app.py --dev)")
    socket.write(json.dumps({"cmd": command, "arg": arg}).encode() + b"\n")
    socket.flush()
    data = b""
    while not data.endswith(b"\n"):
        if not socket.waitForReadyRead(timeout_ms):
            raise SystemExit("The program did not answer")
        data += bytes(socket.readAll())
    return json.loads(data)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    reply = send(sys.argv[1], " ".join(sys.argv[2:]) or None)
    if not reply["ok"]:
        print(reply["error"], file=sys.stderr)
        return 1
    result = reply["result"]
    print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
