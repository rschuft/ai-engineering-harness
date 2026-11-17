"""The projection's transport-free authority reader (``bound_authority.py``) pinned to the dispatcher's own
(``dispatch_inputs.attempt_authority`` and ``bound_label``), case by case (plan leaf U-04.1; the I1 integration design,
R11; the engineering manager's ruling on U-04.1's STOP, option B).

Each case is a reservation the dispatcher's own constructors made (``ResolvedInputs.intent()`` reserved through the
store's API, or a whole dispatch through ``dispatch_inputs.dispatch`` on the checked-in profiles), read by both
readers. The two answer the same authority, or both refuse, with codes that map one to one (``CODE_MAP``); and
``bound_label`` labels exactly what the reader binds. The one known divergence (``Divergence``): the dispatcher
validates the whole admission policy, the reader only the pin it reads. The per-record labels of a real run are
compared in ``test_projection.EndToEnd``.

The dispatch modules are loaded on the test side only: the reader itself names none (test_structure.NewModules).
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import ownerhost_support as T

CATEGORY = 'integration'
DISPATCH_TESTS = T.REPO / 'integrations' / 'dispatch' / 'tests'
TA = T._load('test_authority', DISPATCH_TESTS / 'test_authority.py')
FA = T._load('fixture_attempts', T.REPO / 'integrations' / 'lineage' / 'tests' / 'fixture_attempts.py')
B = T._load('aieh_ownerhost_bound_authority', T.PACKAGE / 'bound_authority.py')
di, ci, store_mod = TA.di, TA.ci, TA.store_mod
ACTOR = 'u-04.1-test'
ABSENT = object()
OUTCOME = 'outcome:3f6a2c1d-9b4e-4f7a-8c2d-5e1b0a9f7d63'
# The dispatcher's refusal codes on this path and the reader's own, one to one.
ADMISSION_CODES = ('PROFILE_ADMISSION_INVALID', 'RUNTIME_NOT_DOCKER', 'ROUTE_NOT_ALLOWLISTED', 'WORKING_DIR_NOT_ALLOWED',
                   'CAPS_ABOVE_CEILING', 'MOUNT_POLICY_INVALID')
CODE_MAP = {'RESERVATION_INVALID': 'BINDING_RECORD_INVALID', 'ADMISSION_MISMATCH': 'BINDING_POLICY_MISMATCH',
            **{code: 'BINDING_ADMISSION_INVALID' for code in ADMISSION_CODES},
            'PROFILE_ARTIFACT_MISSING': 'BINDING_ALLOWLIST_MISSING',
            'PROFILE_ARTIFACT_DRIFTED': 'BINDING_ALLOWLIST_DRIFTED',
            'PROFILE_ARTIFACT_INVALID': 'BINDING_ALLOWLIST_INVALID',
            'TRANSPORT_DECLARATION_MISMATCH': 'BINDING_DECLARATION_INVALID'}


class Profile(FA.FixtureAttempts):
    """``fixture_attempts.FixtureAttempts`` (the dispatcher's constructors over a throwaway profile directory), its
    allowlist's top-level ``transport`` set to TRANSPORT (ABSENT: none) and its admission policy changed by ADMISSION
    (a function of a copy), so that every case is a record the dispatcher's own constructors made."""

    def __init__(self, root, transport=ABSENT, admission=None):
        self.root, self.live = Path(root), transport is ABSENT
        directory = self.root / 'profiles' / FA.PROFILE / 'agent-server'
        directory.mkdir(parents=True, exist_ok=True)
        routes = json.loads((FA.CHECKED_IN / 'agent-server' / 'routes.json').read_text(encoding='utf-8'))
        if transport is not ABSENT:
            routes['transport'] = copy.deepcopy(transport)
        routes_raw = (json.dumps(routes, indent=2) + '\n').encode('utf-8')
        template_raw = (FA.CHECKED_IN / 'agent-server' / 'conversation-create.json').read_bytes()
        (directory / 'routes.json').write_bytes(routes_raw)
        (directory / 'conversation-create.json').write_bytes(template_raw)
        declared = json.loads((FA.CHECKED_IN / 'profile.json').read_text(encoding='utf-8'))
        server = declared['provisioning']['agent_server']
        server.pop(di.STAGE_TEMPLATE_KEY, None)
        server['admission']['routes'] = {**server['admission']['routes'],
                                         'path': f'profiles/{FA.PROFILE}/agent-server/routes.json',
                                         'sha256': hashlib.sha256(routes_raw).hexdigest()}
        server['fixture'] = {**server['fixture'], 'path': f'profiles/{FA.PROFILE}/agent-server/conversation-create.json',
                             'sha256': hashlib.sha256(template_raw).hexdigest()}
        self.declared = declared
        self.profile_raw = (json.dumps(declared, indent=2) + '\n').encode('utf-8')
        (self.root / 'profiles' / FA.PROFILE / 'profile.json').write_bytes(self.profile_raw)
        self.admission = di.admission_policy(declared, FA.PROFILE)
        if admission is not None:
            self.admission = admission(copy.deepcopy(self.admission))

    @property
    def routes(self) -> Path:
        return self.root / 'profiles' / FA.PROFILE / 'agent-server' / 'routes.json'


class Store:
    """A stand-in store answering one reservation by key (``bound_label`` reads ``get``)."""

    def __init__(self, reservation):
        self.reservation = reservation

    def get(self, key):
        return self.reservation if key == self.reservation.operation_key else None


def dispatcher(reservation, read_artifact):
    """The dispatcher's answer: (authority, None) or (None, its refusal code), by ``bound_label``'s own steps."""
    if reservation is None or di._sha256(reservation.intent_json) != reservation.intent_digest:
        return None, 'RESERVATION_INVALID'
    try:
        intent = di._strict_loads(reservation.intent_json)
    except ValueError:
        return None, 'RESERVATION_INVALID'
    try:
        resolved = di.ResolvedInputs.from_json(intent.get(di.INTENT_KEY) if isinstance(intent, dict) else None)
        return di.attempt_authority(resolved, read_artifact), None
    except di.DispatchRefused as refusal:
        return None, refusal.code


def reader(reservation, read_artifact):
    try:
        return B.bound_authority(reservation, read_artifact), None
    except B.Unbound as unbound:
        return None, unbound.code


class Equivalence(TA.Bound):
    """Each case: the same authority, or both refused with mapped codes; bound_label labels what the reader binds."""

    def setUp(self):
        super().setUp()
        self.work = Path(tempfile.mkdtemp(prefix='u41-bind-'))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.cases = []

    def agree(self, name, store, key, read_artifact, expected):
        """Both readers on STORE's reservation KEY; EXPECTED is the authority or the reader's code."""
        reservation = store.get(key)
        theirs, ours = dispatcher(reservation, read_artifact), reader(reservation, read_artifact)
        with self.subTest(case=name):
            self.assertEqual(ours[0], theirs[0], (theirs, ours))
            self.assertEqual(ours[1], CODE_MAP.get(theirs[1]) if theirs[1] else None, (theirs, ours))
            self.assertEqual(ours[0] if ours[0] else ours[1], expected)
            label = di.bound_label(store, key, read_artifact)
            self.assertEqual(label, {} if ours[0] in (None, 'live') else {'authority': ours[0]})
        self.cases.append(name)

    def reserved(self, profile, n):
        """One attempt of its own work item (TASK-<N>) reserved with PROFILE's records."""
        resolved = profile.resolved(f'TASK-{n}', change='qual-02', design_commit='a' * 40, outcome_ref=OUTCOME)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor=ACTOR)
        return resolved.attempt_identity().operation_key, resolved

    def test_the_checked_in_live_profile(self):
        live = self.dispatch(self.core, TA.provider(), profile=ci.REAL, manifest=self.approve_real())
        self.agree('checked-in live (strong-windows-qemu-whpx)', self.store, live.operation_key, self.read_artifact,
                   'live')

    def test_the_checked_in_fixture_profile(self):
        fixture = self.fixture_attempt()
        self.agree('checked-in fixture (fixture-d1-replay)', self.store, fixture.operation_key, self.read_artifact,
                   'fixture')
        self.assertEqual(B.bound_authority(self.store.get(fixture.operation_key), self.read_artifact), 'fixture')

    def test_declarations(self):
        cases = [('no transport', ABSENT, 'live'), ('transport null', None, 'live'),
                 ('the fixture declaration', {'authority': 'fixture', 'kind': 'loopback-fixture'}, 'fixture'),
                 ('authority without kind', {'authority': 'fixture'}, 'BINDING_DECLARATION_INVALID'),
                 ('live with the fixture kind', {'authority': 'live', 'kind': 'loopback-fixture'},
                  'BINDING_DECLARATION_INVALID'),
                 ('an extra key', {'authority': 'fixture', 'kind': 'loopback-fixture', 'port': 13320},
                  'BINDING_DECLARATION_INVALID'),
                 ('a string', 'fixture', 'BINDING_DECLARATION_INVALID'),
                 ('a list', [], 'BINDING_DECLARATION_INVALID')]
        for n, (name, transport, expected) in enumerate(cases):
            profile = Profile(self.work / f'decl-{n}', transport)
            key, _ = self.reserved(profile, n + 1)
            self.agree(f'declaration: {name}', self.store, key, profile.read_artifact, expected)

    def test_a_drifted_a_missing_and_an_invalid_allowlist(self):
        for n, (name, change, expected) in enumerate((
                ('drifted', lambda p: p.write_bytes(p.read_bytes() + b' '), 'BINDING_ALLOWLIST_DRIFTED'),
                ('missing', lambda p: p.unlink(), 'BINDING_ALLOWLIST_MISSING'))):
            profile = Profile(self.work / f'file-{n}', {'authority': 'fixture', 'kind': 'loopback-fixture'})
            key, _ = self.reserved(profile, n + 1)
            change(profile.routes)
            self.agree(f'allowlist {name}', self.store, key, profile.read_artifact, expected)
        # pinned bytes that are not a JSON object: the pin re-pointed at a file of its own
        profile = Profile(self.work / 'file-invalid', {'authority': 'fixture', 'kind': 'loopback-fixture'})
        raw = b'[1, 2]\n'
        bad = profile.root / 'profiles' / FA.PROFILE / 'agent-server' / 'list.json'
        bad.write_bytes(raw)
        profile.admission['routes'] = {'path': f'profiles/{FA.PROFILE}/agent-server/list.json',
                                       'sha256': hashlib.sha256(raw).hexdigest()}
        key, _ = self.reserved(profile, 3)
        self.agree('allowlist not an object', self.store, key, profile.read_artifact, 'BINDING_ALLOWLIST_INVALID')

    def test_a_policy_digest_mismatch_and_a_policy_of_another_profile(self):
        profile = Profile(self.work / 'policy', {'authority': 'fixture', 'kind': 'loopback-fixture'})
        resolved = profile.resolved('TASK-1', change='qual-02', design_commit='a' * 40, outcome_ref=OUTCOME)
        for n, (name, edit) in enumerate((
                ('policy digest mismatch', lambda r: r['policy_inputs'].update(extra=1)),
                ('policy of another profile', lambda r: r.update(
                    policy_inputs={**r['policy_inputs'], 'profile': {'id': 'other', 'sha256': '0' * 64}},
                    policy_digest=hashlib.sha256(di._canonical({**r['policy_inputs'], 'profile': {
                        'id': 'other', 'sha256': '0' * 64}}).encode()).hexdigest())))):
            intent = resolved.intent()
            edit(intent[di.INTENT_KEY])
            key = f'u41/policy/{n}'
            self.store.reserve(key, intent, actor=ACTOR)
            self.agree(name, self.store, key, profile.read_artifact, 'BINDING_POLICY_MISMATCH')

    def test_a_record_that_is_not_the_dispatcher_s(self):
        profile = Profile(self.work / 'other', {'authority': 'fixture', 'kind': 'loopback-fixture'})
        self.store.reserve('work-TASK-1/implement/revision-1', {'workRef': 'backlog:TASK-1', 'outcomeRef': OUTCOME},
                           actor=ACTOR)
        self.agree('a lineage-style reservation', self.store, 'work-TASK-1/implement/revision-1',
                   profile.read_artifact, 'BINDING_RECORD_INVALID')
        resolved = profile.resolved('TASK-1', change='qual-02', design_commit='a' * 40, outcome_ref=OUTCOME)
        good = resolved.intent()
        for n, (name, text) in enumerate((
                ('an intent that is not its digest', None),
                ('a duplicate key', '{"dispatchInputs": {}, "dispatchInputs": {}}'),
                ('a NaN', '{"x": NaN}'),
                ('a record of another format', di._canonical({**good, di.INTENT_KEY: {
                    **good[di.INTENT_KEY], 'format': 'ai-engineering-harness/dispatch/resolved-inputs/v1'}})),
                ('a record with an extra key', di._canonical({**good, di.INTENT_KEY: {
                    **good[di.INTENT_KEY], 'extra': 1}})))):
            intent_json = text if text is not None else di._canonical(good)
            digest = '0' * 64 if text is None else di._sha256(intent_json)
            reservation = store_mod.Reservation(f'u41/not/{n}', digest, intent_json, 'c', 'reserved', 'none', 0,
                                                'x', 'x')
            self.agree(name, Store(reservation), reservation.operation_key, profile.read_artifact,
                       'BINDING_RECORD_INVALID')


class Divergence(TA.Bound):
    """The known divergence, stated in bound_authority.py and the README: the dispatcher validates the whole admission
    policy before it reads the pin, the reader only the pin. A record whose other admission values are invalid while
    its digests hold is bound by the reader and refused by the dispatcher. The dispatcher cannot reserve such a record
    (its admission runs before the reservation), so this is built by its constructors for the test only."""

    def test_caps_above_the_ceilings_are_the_dispatcher_s_refusal_and_not_the_reader_s(self):
        work = Path(tempfile.mkdtemp(prefix='u41-div-'))
        self.addCleanup(shutil.rmtree, work, True)

        def above(admission):
            admission['caps']['memory'] = '999g'
            return admission
        profile = Profile(work, {'authority': 'fixture', 'kind': 'loopback-fixture'}, admission=above)
        resolved = profile.resolved('TASK-1', change='qual-02', design_commit='a' * 40, outcome_ref=OUTCOME)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor=ACTOR)
        reservation = self.store.get(resolved.attempt_identity().operation_key)
        self.assertEqual(dispatcher(reservation, profile.read_artifact), (None, 'CAPS_ABOVE_CEILING'))
        self.assertEqual(di.bound_label(self.store, reservation.operation_key, profile.read_artifact), {})
        self.assertEqual(reader(reservation, profile.read_artifact), ('fixture', None))


class Constants(unittest.TestCase):
    category = 'unit'

    def test_the_reader_s_formats_and_grammars_are_the_dispatcher_s(self):
        self.assertEqual((B.INTENT_KEY, B.RESOLVED_FORMAT, B.POLICY_FORMAT, B.MANIFEST_SCHEMA, B.TRANSPORT_KEY),
                         (di.INTENT_KEY, di.RESOLVED_FORMAT, di.POLICY_FORMAT, di.MANIFEST_SCHEMA, di.TRANSPORT_KEY))
        self.assertEqual((B.LIVE, B.FIXTURE, B.AUTHORITIES, B.DECLARATIONS),
                         (di.LIVE, di.FIXTURE, di.AUTHORITIES, di.TRANSPORT_DECLARATIONS))
        self.assertEqual((B.ARTIFACT_PATH_RE.pattern, B.RESERVED_NAMES, B.SHA256_RE.pattern),
                         (di.ARTIFACT_PATH_RE.pattern, di.RESERVED_NAMES, di.SHA256_RE.pattern))
        for path in ('profiles/x/a.json', 'profiles/x/CON', 'profiles/x/nul.json', 'profiles/X/a', 'other/x/a',
                     'profiles/x/../a', 'profiles/x/com1.txt', None, 'profiles/x'):
            with self.subTest(path=path):
                self.assertEqual(B.is_artifact_path(path), di.is_artifact_path(path))

    def test_the_reader_s_record_keys_are_the_resolved_record_s(self):
        record = TA.ci.di.ResolvedInputs(
            work_id='TASK-1', repository='r', stage='implement', ordinal=1, design_revision='d', profile='p',
            profile_digest='0' * 64, catalog_pin='c', agent_manifest_digest='0' * 64, planned_workspace='w',
            policy_digest='0' * 64, policy_inputs_json='{}', manifest_version=1, manifest_sha256='0' * 64,
            outcome_ref='o').to_json()
        self.assertEqual(set(record), B.RECORD_KEYS)
        self.assertEqual(set(record['approval']), B.APPROVAL_KEYS)


if __name__ == '__main__':
    unittest.main()
