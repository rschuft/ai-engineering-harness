"""Shared fixtures of the provider envelope's tests (plan leaf S-03.5, slice 1).

The envelope receipts are made by the REAL authorization recorder (integrations/owner/authorization_recorder.py)
against the owner suite's fake Gitea (integrations/owner/tests/fake_gitea.py, called in memory: no socket) with
the owner suite's fake protection verifier, a fixture credential provider and a fixed clock, into a throwaway
integration store; the broker reads them with the REAL read side (integrations/owner/envelope_decisions.py).
Hand-written receipts appear only in the tests that say so. The bound origin is a name under ``.test``, never
connected: ``serve`` stops at "started", and a request of a bound family goes to an injected connector that checks
the origin it is given and answers from an in-process fake upstream on 127.0.0.1. Every statement is SYNTHETIC: it
stands in for an Owner statement and is no Owner decision.
"""
from __future__ import annotations

import copy
import datetime
import http.client
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import broker_support as S

sys.path.insert(0, str(S.REPO / 'integrations' / 'owner' / 'tests'))
import authz_support as su  # noqa: E402
import fake_gitea as fg  # noqa: E402

IB = S.IB
E = IB.inference_envelope
AR = su.AR
ED = S._load('envelope_decisions', S.REPO / 'integrations' / 'owner' / 'envelope_decisions.py')

ORIGIN = 'https://api.provider.test'
OTHER_ORIGIN = 'https://api.other-provider.test'
EXPIRES = '2026-12-01T00:00:00Z'
UTC = datetime.timezone.utc
DURING = datetime.datetime(2026, 11, 30, 12, 0, 0, tzinfo=UTC).timestamp()    # twelve hours before the expiry
AT_EXPIRY = datetime.datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC).timestamp()
OPERATION = 'op-envelope-0001'


def limit(**changes) -> dict:
    return {'amount': '25.00', 'currency': 'USD', 'enforced_by': 'provider', **changes}


def block(**changes) -> dict:
    return {'expires_at': EXPIRES, 'limit': limit(), 'selection': 'envelope', **changes}


def component(origin=ORIGIN, models=(S.MODEL_A,), envelope='default', family='anthropic-messages', provider=S.PROVIDER,
              others=None) -> dict:
    """components.inference_broker with one family at ORIGIN (ephemeral ports), OTHERS ({family: settings}) beside
    it, and the envelope block (block() unless given; None leaves it out)."""
    raw = {'control_port': 0, 'inference_port': 0,
           'families': {family: {'provider': provider, 'upstream': origin, 'models': list(models)}}}
    raw['families'].update(copy.deepcopy(others or {}))
    if envelope == 'default':
        envelope = block()
    if envelope is not None:
        raw['envelope'] = copy.deepcopy(envelope)
    return raw


def manifest_bytes(raw: dict, operation: str = OPERATION) -> bytes:
    """The canonical manifest of RAW's live envelope, as the envelope command reports it."""
    report = IB.envelope_report(IB.load_config(raw, allow_ephemeral=True), operation)
    return report['manifest']['text'].encode('utf-8')


class Recorder:
    """The real authorization recorder over one in-memory fake Gitea (one per test), writing its receipts into the
    store at DB."""

    def __init__(self, db: Path, state_dir: Path):
        self.db, self.state_dir = db, state_dir
        self.gitea = fg.FakeGitea()
        self.verifier = su.FakeVerifier()

    def authorize(self, manifest: bytes, operation: str = OPERATION, *, on_merge=None):
        """Propose MANIFEST as operations/<operation>.json, prepare, and record a SYNTHETIC statement. Returns
        record's result, or the RecorderError it raised (a failed or unknown outcome)."""
        number = self.gitea.propose({f'operations/{operation}.json': manifest}, branch=f'work/{operation}')
        store = S.STORE.open_store(self.db)
        try:
            ctx = AR.Context(self.state_dir, store, fg.FixtureProvider(su.owner_entry()), 3000, http=self.gitea,
                             now=lambda: su.NOW, policies=AR.exercise_policies(), verifier=self.verifier)
            challenge = AR.prepare(ctx, fg.REPOSITORY, number)
            self.gitea.on_merge = on_merge
            try:
                return AR.record(ctx, challenge['shown']['nonce'], su.statement(operation),
                                 recorded_by=su.RECORDED_BY)
            except AR.RecorderError as exc:
                return exc
            finally:
                self.gitea.on_merge = None
        finally:
            store.close()


def refuse(*args, **kwargs):
    raise AssertionError('serve went past its start precondition')


class EnvelopeCase(unittest.TestCase):
    """A throwaway directory per test: the integration store, the recorder's state and the audit directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-envelope-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / 'logs').mkdir()
        self.db = self.tmp / 'integration.sqlite'
        self.recorder = Recorder(self.db, self.tmp / 'authz-state')

    def authorize(self, raw: dict, operation: str = OPERATION, **kw):
        return self.recorder.authorize(manifest_bytes(raw, operation), operation, **kw)

    def confirmed(self, raw: dict, operation: str = OPERATION) -> dict:
        result = self.authorize(raw, operation)
        self.assertIsInstance(result, dict, getattr(result, 'detail', result))
        self.assertEqual(result['receipt']['state'], 'confirmed')
        return result

    def open_store(self):
        store = S.STORE.open_store(self.db)
        self.addCleanup(store.close)
        return store

    def keys(self) -> list:
        store = S.STORE.open_store(self.db)
        try:
            return sorted(a.operation_key for a in store.attempts())
        finally:
            store.close()

    def context(self, raw, *, provider=refuse, logs=refuse, wait=refuse, decisions=ED.verifier, clock=DURING,
                component=None):
        return IB.Context(component=component or (lambda: raw), provider=provider,
                          store=lambda: S.STORE.open_store(self.db), logs=logs, stdin=None, out=io.StringIO(),
                          err=io.StringIO(), wait=wait, allow_ephemeral=True, authorization=decisions,
                          clock=lambda: clock)

    def assertStartRefused(self, raw, code, **kw):
        """serve exits 2 with CODE before it asks for the provider, the audit directory or the wait (each raises if
        called), and writes nothing to the store."""
        before = self.keys() if self.db.exists() else None
        ctx = self.context(raw, **kw)
        self.assertEqual(IB.main(['serve'], ctx), 2, ctx.err.getvalue())
        self.assertIn(f'inference-broker: {code}: ', ctx.err.getvalue())
        self.assertEqual(ctx.out.getvalue(), '')
        if before is not None:
            self.assertEqual(self.keys(), before)
        return ctx

    def serve(self, raw, wait, **kw):
        """serve with the in-memory provider holding the synthetic key, the audit directory, and WAIT."""
        provider = S.MemoryProvider({IB.ENTRY: (S.PROVIDER, S.KEY)})
        kw.setdefault('provider', lambda: provider)
        ctx = self.context(raw, logs=lambda: self.tmp / 'logs', wait=wait, **kw)
        return IB.main(['serve'], ctx), ctx

    def start_receipts(self) -> list:
        store = S.STORE.open_store(self.db)
        try:
            return [json.loads(a.intent_json) for a in store.attempts()
                    if a.operation_key.startswith('inference/broker-start/')]
        finally:
            store.close()


def minted(raw: dict, db: Path, clock: float = DURING):
    """The Authorization authorize() mints for RAW over the store at DB (the real read side)."""
    return IB.authorize(IB.load_config(raw, allow_ephemeral=True), ED.verifier, lambda: S.STORE.open_store(db),
                        lambda: clock)


class BoundRig(S.Rig):
    """broker_support.Rig with the authorization the broker holds, and its clock at DURING."""

    def __init__(self, raw: dict, authorization, *, connect, db: Path | None = None, store_factory=None):
        super().__init__(raw, connect=connect, db=db, store_factory=store_factory)
        self.clock.now = DURING
        self.broker = IB.Broker(self.config, provider_key=self.broker.provider_key, journal=self.journal,
                                audit=self.audit, guard=self.guard, clock=self.clock, connect=connect,
                                authorization=authorization)


class Connector:
    """An injected connector: it records the origin it is given and connects to the in-process fake upstream that
    plays it (ROUTES: {origin text: FakeUpstream}); any other origin is refused as connect_upstream would."""

    def __init__(self, routes: dict):
        self.routes, self.seen = routes, []

    def __call__(self, origin, timeout):
        self.seen.append(origin.text())
        fake = self.routes.get(origin.text())
        if fake is None:
            raise IB.InferenceError('UPSTREAM_NOT_CONFIGURED', f'{origin.text()} is not a test route')
        return http.client.HTTPConnection('127.0.0.1', fake.port, timeout=timeout)
