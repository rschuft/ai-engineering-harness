"""A test-side child: the Integration process's server (``app.serve``) on a free port, with its capture replaced by a
probe that tries to open a transport (decision 0025 point 2; the outbound guard of app.py).

    <tools python> -I -B integrations/ownerhost/tests/serve_outbound_probe.py STATE_DIR LOGS_DIR PORT TARGET_PORT

Everything but the capture is the server process as service.py runs it (serve_on_port.py): the same ``serve``,
whose lifespan arms the outbound guard. The probe's capture, asked for message ``connect``, ``connect-ex`` or
``getaddrinfo``, opens a TCP connection to 127.0.0.1:TARGET_PORT, calls ``connect_ex`` on it, or looks
``localhost`` up. The guard refuses each before the call (the route answers OUTBOUND_REFUSED); were it not armed,
the call would go through and the probe would answer ``reached`` (the test's listener on TARGET_PORT also sees the
connection). The test stops it with ``<state>/stop-request``.
"""
from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    state_dir, logs_dir, port, target = Path(argv[0]), Path(argv[1]), int(argv[2]), int(argv[3])
    spec = importlib.util.spec_from_file_location('aieh_ownerhost_app', PACKAGE / 'app.py')
    app = sys.modules['aieh_ownerhost_app'] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    if port == app.PORT:
        print(f'refused: {app.LOOPBACK}:{app.PORT} is the declared port of the Owner\'s Integration process',
              file=sys.stderr)
        return 2

    def probe(_capturer, _store, _thread_id, message_id, _sha256, _session):
        if message_id == 'connect':
            socket.create_connection((app.LOOPBACK, target), timeout=5).close()
        elif message_id == 'connect-ex':
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                return {'reached': sock.connect_ex((app.LOOPBACK, target)) == 0}
        elif message_id == 'getaddrinfo':
            socket.getaddrinfo('localhost', target)
        return {'reached': True}

    app.capture.Capture.capture = probe
    try:
        return app.serve(state_dir, logs_dir, port=port)
    except app.ServeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
