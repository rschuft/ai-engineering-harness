"""A test-side child: the Integration process's server (``app.serve``) on a port the test chose (plan leaf U-02.2).

``service.py up`` starts the server on the one declared port, 127.0.0.1:13310, which the Owner's own Integration
process may hold. A test that must stop and start a real Integration process therefore runs ``app.serve`` itself, in
this child, on a free loopback port it picked, with a throwaway state and logs directory. Everything else is the
server process as ``service.py`` runs it: the same module, the same ``serve`` (the conversation store opened at
``<state>/conversation.sqlite``, the listener bound to 127.0.0.1 only, the server record, the stop-request file).

    <tools python> -I -B integrations/ownerhost/tests/serve_on_port.py STATE_DIR LOGS_DIR PORT

The test stops it the way ``service.py down`` does: it writes ``<state>/stop-request`` and waits for the process to
exit.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    state_dir, logs_dir, port = Path(argv[0]), Path(argv[1]), int(argv[2])
    spec = importlib.util.spec_from_file_location('aieh_ownerhost_app', PACKAGE / 'app.py')
    app = sys.modules['aieh_ownerhost_app'] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    if port == app.PORT:
        print(f'refused: {app.LOOPBACK}:{app.PORT} is the declared port of the Owner\'s Integration process',
              file=sys.stderr)
        return 2
    try:
        return app.serve(state_dir, logs_dir, port=port)
    except app.ServeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
