"""The child process of test_provider_tunnel.py's lifecycle tests: the tunnel's own serve
(provider_tunnel.main(['serve', ...])) with its real wait in a process of its own, over a test context, so that the
stop command, the operating system's tables and the run record see a real process.

Never the managed context: its run directory and log directory are the ones its spec names (a temporary directory of
the test), its profile is the spec's, its port an ephemeral one on 127.0.0.1, and no connection is made through it
(its outbound seam is never reached).

  <tools python> -I -B integrations/inference/tests/tunnel_child.py <spec.json>

The spec: {"run_dir", "logs", "profile"}. Standard error carries the tunnel's "serving" line.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import provider_tunnel as T  # noqa: E402 - after the path above


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    ctx = T.Context(run_dir=lambda: Path(spec['run_dir']), logs=lambda: Path(spec['logs']), out=sys.stdout,
                    err=sys.stderr, allow_ephemeral=True)
    return T.main(['serve', '--profile', spec['profile'], '--port', '0'], ctx)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
