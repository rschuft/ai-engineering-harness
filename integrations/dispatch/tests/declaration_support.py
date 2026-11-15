"""The checked-in strong-windows-qemu-whpx declaration as E-01.3.3's custody probe and E-01.2.2's live drill
use it (TEST ONLY; not a unittest module).

Both build their requests from the checked-in declaration, in a throwaway copy, and dispatch an ``implement``
attempt on it. Since E-05.2 that declaration pins the D1 stage's create template for ``implement``
(``provisioning.agent_server.stage_create_template``, the native execution profile): an ``implement`` attempt on it
is the native D1 stage, whose create is E-05.11's qualified agent block and carries the Owner's native token. Neither
leaf is about the agent's create template: the custody probe proves bot-token custody per stage, the key file and
the runtime credential; the drill compares the container the Agent Server created with the admitted request. The
native D1 stage is E-05.2's and E-05.11's. So, by the engineering manager's ruling of 2026-11-15 on E-05.2's STOP,
both use the checked-in declaration with exactly one derivation (DERIVATION): that pin removed, so that their
``implement`` stage keeps E-01.2.2's admission with the F-04.2 fixture. Nothing else is changed; a declaration
without that pin is refused rather than passed through, and ``test_d1_checked_in_template.TheProbeDerivation``
asserts that the derived declaration differs from the checked-in one by that key only.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REAL_PROFILE = 'strong-windows-qemu-whpx'
STAGE_TEMPLATE_KEY = 'stage_create_template'   # dispatch_inputs.STAGE_TEMPLATE_KEY
D1_STAGE = 'implement'
DERIVED_PATH = ('provisioning', 'agent_server', STAGE_TEMPLATE_KEY)
DERIVATION = ('the checked-in strong-windows-qemu-whpx declaration with exactly one change: '
              'provisioning.agent_server.stage_create_template (the implement stage\'s D1 create template pin, '
              'E-05.2) removed, so the implement stage keeps E-01.2.2\'s admission with the F-04.2 fixture '
              '(the engineering manager\'s ruling of 2026-11-15)')


def without_d1_stage_pin(declared: dict) -> dict:
    """DECLARED with its implement stage_create_template pin removed, and nothing else changed. ValueError when it
    declares no such pin (the derivation is exactly one removal, never a pass-through)."""
    derived = copy.deepcopy(declared)
    server = ((derived.get('provisioning') or {}).get('agent_server') if isinstance(derived, dict) else None)
    pin = server.get(STAGE_TEMPLATE_KEY) if isinstance(server, dict) else None
    if not isinstance(pin, dict) or pin.get('stage') != D1_STAGE:
        raise ValueError(f'the declaration has no {D1_STAGE} {STAGE_TEMPLATE_KEY} pin to remove')
    del server[STAGE_TEMPLATE_KEY]
    return derived


def checked_in_bytes(repo: Path = REPO) -> bytes:
    """The checked-in declaration's bytes."""
    return (Path(repo) / 'profiles' / REAL_PROFILE / 'profile.json').read_bytes()


def derived_declaration_bytes(raw: bytes | None = None) -> bytes:
    """The bytes the probe and the drill write as the throwaway profile: RAW (the checked-in declaration by
    default) with DERIVATION applied, serialized as JSON with two-space indentation and a final newline."""
    declared = json.loads(checked_in_bytes() if raw is None else raw)
    return (json.dumps(without_d1_stage_pin(declared), indent=2) + '\n').encode('utf-8')
