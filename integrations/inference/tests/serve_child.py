"""The child process of test_stop.py's subprocess tests: the broker's own serve (inference_broker.main(['serve'])
with its real wait, _wait_for_interrupt) in a process of its own, over a test context, so that a real console
control event or the control listener's stop can be sent to it.

Never the managed context: no config.yml, no credential provider and no managed root are read. Its configuration is
loopback only: one family (anthropic-messages) whose upstream is broker_support's in-process fake upstream on an
ephemeral 127.0.0.1 port, with the synthetic key of an in-memory credential provider; its integration store and
audit directory are in the directory the spec names (a temporary directory of the test).

  <tools python> -I -B integrations/inference/tests/serve_child.py <spec.json>

The spec: {"dir": <a temporary directory, with logs/ in it>, "drain_ceiling_s": <the broker's drain ceiling>}.
Standard error carries the broker's "serving" line, then "serve-child: stop asked" once its wait has returned.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))      # -I leaves the script's directory off the path

import broker_support as S  # noqa: E402 - after the path above

IB = S.IB
STOP_ASKED = 'serve-child: stop asked'


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    tmp = Path(spec['dir'])
    upstream = S.FakeUpstream('anthropic-messages')
    upstream.server.handle_error = lambda request, client_address: None   # a cut stream's reset: expected
    raw = S.component({'anthropic-messages': upstream.origin})
    provider = S.MemoryProvider({IB.ENTRY: (S.PROVIDER, S.KEY)})

    def wait(broker):
        broker.drain_ceiling_s = spec['drain_ceiling_s']
        IB._wait_for_interrupt(broker)
        sys.stderr.write(STOP_ASKED + '\n')
        sys.stderr.flush()
    ctx = IB.Context(component=lambda: raw, provider=lambda: provider,
                     store=lambda: S.STORE.open_store(tmp / 'integration.sqlite'), logs=lambda: tmp / 'logs',
                     stdin=None, out=sys.stdout, err=sys.stderr, wait=wait, allow_ephemeral=True)
    return IB.main(['serve'], ctx)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
