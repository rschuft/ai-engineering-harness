"""A stand-in for ``openspec instructions apply --change ID --json`` (OpenSpec 1.16.0).

It answers with the fields the adapter reads, shaped like the real output recorded in
``fixtures/two-task/recorded/openspec-apply.json``. It reports task tracking when the
exported tree it runs in holds the change's ``tasks.md``, or when
``FAKE_OPENSPEC_TRACKED=1``. Test scaffolding only.
"""
import json
import os
import sys
from pathlib import Path


def main(argv):
    if argv[:2] != ['instructions', 'apply'] or '--json' not in argv or '--change' not in argv:
        print(f'fake: unsupported command {argv}', file=sys.stderr)
        return 1
    change = argv[argv.index('--change') + 1]
    tracked = os.environ.get('FAKE_OPENSPEC_TRACKED') == '1' or \
        Path('openspec', 'changes', change, 'tasks.md').exists()
    print(json.dumps({'changeName': change, 'schemaName': 'intent-driven',
                      'progress': {'total': 1 if tracked else 0, 'complete': 0,
                                   'remaining': 1 if tracked else 0},
                      'tasks': [{'id': '1', 'description': 'x', 'done': False}] if tracked else [],
                      'taskTrackingConfigured': tracked, 'state': 'ready'}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
