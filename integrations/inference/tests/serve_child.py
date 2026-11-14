"""The child process of test_stop.py's and test_census.py's subprocess tests: the broker's own serve
(inference_broker.main(['serve']) with its real wait, _wait_for_interrupt) in a process of its own, over a test
context, so that a real console control event or the control listener's stop can be sent to it, and so that the
live census (S-03.2) sees the broker's sockets in a process of their own.

Never the managed context: no config.yml, no credential provider and no managed root are read. Its configuration is
loopback only: one family (anthropic-messages) whose upstream is broker_support's in-process fake upstream on an
ephemeral 127.0.0.1 port, with the synthetic key of an in-memory credential provider; its integration store and
audit directory are in the directory the spec names (a temporary directory of the test).

  <tools python> -I -B integrations/inference/tests/serve_child.py <spec.json>

The spec: {"dir": <a temporary directory, with logs/ in it>, "drain_ceiling_s": <the broker's drain ceiling>},
and optionally "upstream": <the origin of a fake upstream the test runs> (then the child runs none, so that every
socket of the child is the broker's) and "sockets": true (test_census.py: the child then reads commands on standard
input, each opening one more socket in the broker's process, kept until the child ends: "listen" a TCP listener on
127.0.0.1, "connect <port>" a TCP connection to 127.0.0.1:<port>, "udp" a UDP socket on 127.0.0.1; each answers
"serve-child: <command> <port>" on standard error).
Standard error carries the broker's "serving" line, then "serve-child: stop asked" once its wait has returned.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))      # -I leaves the script's directory off the path

import broker_support as S  # noqa: E402 - after the path above

IB = S.IB
STOP_ASKED = 'serve-child: stop asked'
KEPT = []          # the sockets the commands opened: held until the child ends


def commands() -> None:
    """Each line of standard input opens one more socket in this (the broker's) process and names its port."""
    for line in sys.stdin:
        words = line.split()
        if words == ['listen']:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('127.0.0.1', 0))
            sock.listen(1)
        elif len(words) == 2 and words[0] == 'connect':
            sock = socket.create_connection(('127.0.0.1', int(words[1])), timeout=30)
        elif words == ['udp']:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1', 0))
        else:
            continue
        KEPT.append(sock)
        port = sock.getpeername()[1] if words[0] == 'connect' else sock.getsockname()[1]
        sys.stderr.write(f'serve-child: {words[0]} {port}\n')
        sys.stderr.flush()


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    tmp = Path(spec['dir'])
    origin = spec.get('upstream')
    if origin is None:
        upstream = S.FakeUpstream('anthropic-messages')
        upstream.server.handle_error = lambda request, client_address: None   # a cut stream's reset: expected
        origin = upstream.origin
    if spec.get('sockets'):
        threading.Thread(target=commands, name='serve-child-commands', daemon=True).start()
    raw = S.component({'anthropic-messages': origin})
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
