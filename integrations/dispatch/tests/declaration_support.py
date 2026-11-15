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
``implement`` stage keeps E-01.2.2's admission with the F-04.2 fixture. Nothing else is changed: the removal is
textual, so every byte outside the removed member is the checked-in declaration's (since the review of
2026-11-15, S1), and a declaration the dispatcher's strict reader refuses (a duplicate key, a non-standard constant)
or one without that pin is refused rather than passed through. ``test_d1_checked_in_template.TheProbeDerivation``
asserts both.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
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


def _strict_loads(text: str):
    """The dispatcher's own strict reader of a profile (duplicate keys and non-standard constants refused)."""
    dispatch = sys.modules.get('dispatch_inputs')
    if dispatch is None:
        spec = importlib.util.spec_from_file_location('dispatch_inputs', HERE.parent / 'dispatch_inputs.py')
        dispatch = importlib.util.module_from_spec(spec)
        sys.modules['dispatch_inputs'] = dispatch
        spec.loader.exec_module(dispatch)
    return dispatch._strict_loads(text)


def removed_span(text: str) -> tuple[int, int]:
    """The [start, end) span of TEXT that holds exactly the agent server's stage_create_template member: from the
    start of its line to the end of its value, with the comma that separates it from its neighbour (the following
    one's, or, when it is the last member, the preceding one's) and the following line break. ValueError unless
    the member's key occurs exactly once in TEXT."""
    token = json.dumps(STAGE_TEMPLATE_KEY)
    if text.count(token) != 1:
        raise ValueError(f'{token} must occur exactly once in the declaration, found {text.count(token)}')
    at = text.index(token)
    colon = text.index(':', at + len(token))
    value_start = colon + 1
    while text[value_start] in ' \t\r\n':
        value_start += 1
    _, value_end = json.JSONDecoder().raw_decode(text, value_start)
    start = text.rfind('\n', 0, at) + 1
    if text[start:at].strip():
        raise ValueError(f'{token} does not begin its own line')
    after = value_end
    while after < len(text) and text[after] in ' \t':
        after += 1
    if after < len(text) and text[after] == ',':                     # a following member: take this comma
        end = after + 1
        while end < len(text) and text[end] in ' \t':
            end += 1
        if text.startswith('\r\n', end):
            end += 2
        elif text.startswith('\n', end):
            end += 1
        return start, end
    before = start - 1                                             # the last member: take the preceding comma
    while before >= 0 and text[before] in ' \t\r\n':
        before -= 1
    if before < 0 or text[before] != ',':
        raise ValueError(f'{token} is the only member of its object')
    return before, value_end


def derived_declaration_bytes(raw: bytes | None = None) -> bytes:
    """The bytes the probe and the drill write as the throwaway profile: RAW (the checked-in declaration by
    default) with DERIVATION applied as a textual removal of exactly the stage_create_template member
    (``removed_span``), so every other byte is copied unchanged. RAW must parse with the dispatcher's strict reader
    (a duplicate key or a non-standard constant is a ValueError here, as the dispatcher refuses it: PROFILE_INVALID),
    and the result must parse with it to exactly RAW's declaration less that one member (``without_d1_stage_pin``).
    """
    raw = checked_in_bytes() if raw is None else raw
    text = raw.decode('utf-8')
    declared = _strict_loads(text)
    expected = without_d1_stage_pin(declared)
    start, end = removed_span(text)
    derived = text[:start] + text[end:]
    if json.dumps(_strict_loads(derived), sort_keys=True) != json.dumps(expected, sort_keys=True):   # type-strict
        raise ValueError('the textual removal is not exactly the stage_create_template member')
    return derived.encode('utf-8')
