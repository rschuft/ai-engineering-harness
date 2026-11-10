"""Shared fixtures of the Owner authorization recorder's tests (plan leaf P-04.2).

``Fixture`` gives each test a fake Gitea (fake_gitea.py), a fixture credential provider holding the fake
aieh-owner's synthetic password, the recorder's own state directory and an integration store of its own
(a copy of one migrated store per class) under one temporary directory per class, and a fixed clock.
Nothing here reads the platform's credential store, the managed data root or a real Gitea. Every
statement is SYNTHETIC: it stands in for an Owner statement and is no Owner decision.
"""
from __future__ import annotations

import datetime
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWNER_DIR = HERE.parent
REPO = OWNER_DIR.parents[1]
sys.path.insert(0, str(HERE))
import fake_gitea as fg  # noqa: E402


def _load(name, path):
    import importlib.util
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


AR = _load('authorization_recorder', OWNER_DIR / 'authorization_recorder.py')
D = AR.D
IS = AR.host._load_integration_store()

NOW = datetime.datetime(2026, 11, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
LATER = NOW + datetime.timedelta(minutes=5)
EXPIRES = '2026-11-11T12:00:00Z'
OPERATION = 'op-0001'
RECORDED_BY = 'agent:fixture-transcriber'


def manifest(operation=OPERATION, **changes):
    data = {'operation': operation, 'kind': 'example-effect', 'target': 'example-target (synthetic)',
            'expiresAt': EXPIRES, **changes}
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


def statement(operation=OPERATION, **changes):
    """A SYNTHETIC statement standing in for the Owner's authorization (no Owner decision)."""
    return {'text': f'SYNTHETIC FIXTURE, not an Owner decision: I authorize operation {operation}.',
            'attributedTo': 'owner', 'channel': 'main-session', 'reference': 'conversation:fixture-owner/message-9',
            **changes}


def owner_entry():
    return {AR.OWNER_ENTRY: (AR.OWNER, fg.PASSWORD)}


# A fake protection verifier's answers (the seam of decision 0012 point 6; no real check stands behind them).
VERIFIED = AR.ProtectionVerdict('verified', 'fake verifier: every rule as declared', 'sha256:' + 'c' * 64)
DRIFT = AR.ProtectionVerdict('drift', 'fake verifier: main.enable_bypass_allowlist is true', 'sha256:' + 'd' * 64)
UNVERIFIED = AR.ProtectionVerdict('unverified', 'fake verifier: the rules could not be read')


class FakeVerifier:
    """A fake protection verifier: answers ANSWERS in turn, then DEFAULT; an exception in the list is raised.
    ``calls`` lists (repository, base, phase); ``on_call`` (when set) runs first, with the phase."""

    def __init__(self, *answers, default=VERIFIED):
        self.answers, self.default, self.calls, self.on_call = list(answers), default, [], None

    def __call__(self, repository, base, phase):
        self.calls.append((repository, base, phase))
        if self.on_call is not None:
            self.on_call(phase)
        answer = self.answers.pop(0) if self.answers else self.default
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def phases(self):
        return [phase for _repository, _base, phase in self.calls]


_SHARED = []


def start():
    """setUpModule of a test module: one temporary directory and one migrated integration store for the
    module."""
    tmp = tempfile.TemporaryDirectory(prefix='aieh-authz-')
    golden = Path(tmp.name) / 'golden.sqlite'
    IS.open_store(golden).close()
    _SHARED.append((tmp, golden))


def stop():
    """tearDownModule of a test module."""
    _SHARED.pop()[0].cleanup()


class Fixture(unittest.TestCase):
    """A directory per class in the module's temporary directory (start); a copy of the module's migrated
    integration store, a state directory and a fixture provider per test. Subclasses give the fake Gitea
    (gitea_for_test)."""

    @classmethod
    def setUpClass(cls):
        tmp, cls.golden = _SHARED[-1]
        cls.root = Path(tmp.name) / cls.__name__
        cls.root.mkdir()
        cls.serial = 0

    def gitea_for_test(self):
        """(http callable, port, FakeGitea) of this test."""
        raise NotImplementedError

    def setUp(self):
        type(self).serial += 1
        self.dir = self.root / f't{self.serial}'
        self.dir.mkdir()
        shutil.copyfile(self.golden, self.dir / 'integration.sqlite')
        self.store = IS.open_store(self.dir / 'integration.sqlite')
        self.addCleanup(self.store.close)
        self.http, self.port, self.gitea = self.gitea_for_test()
        self.provider = fg.FixtureProvider(owner_entry())
        self.now = NOW
        self.verifier = FakeVerifier()
        self.ctx = self.context()

    def context(self, **changes):
        """The test's context; its protection verifier is the fake (``verified`` unless the test scripts it)."""
        fields = dict(state_dir=self.dir / 'state', store=self.store, provider=self.provider, port=self.port,
                      http=self.http, now=lambda: self.now, verifier=self.verifier)
        fields.update(changes)
        return AR.Context(**fields)

    def propose(self, operation=OPERATION, files=None, **kw):
        return self.gitea.propose(files or {f'operations/{operation}.json': manifest(operation)}, **kw)

    def prepare(self, number, **kw):
        return AR.prepare(self.ctx, fg.REPOSITORY, number, **kw)

    def record(self, nonce, said=None, **kw):
        return AR.record(self.ctx, nonce, statement() if said is None else said,
                         recorded_by=kw.pop('recorded_by', RECORDED_BY), **kw)

    def assertRefused(self, code, call, *args, refusal=True, **kw):
        with self.assertRaises(AR.RecorderError) as caught:
            call(*args, **kw)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertEqual(caught.exception.refusal, refusal, caught.exception.detail)
        self.assertIn(code, AR.REMEDIES)
        return caught.exception

    def receipts(self):
        return {k: (r.state, [e.to_state for e in self.store.events(r.operation_key)])
                for k, (r, _intent) in AR._receipts(self.store).items()}

    def secrets_absent(self, *texts):
        """The fake password and every fake bot token appear in none of TEXTS or the recorder's files."""
        needles = [fg.PASSWORD, *fg.BOT_TOKENS.values()]
        files = [p for p in (self.dir / 'state').rglob('*') if p.is_file()] if (self.dir / 'state').exists() else []
        blobs = [p.read_bytes().decode('utf-8', 'replace') for p in files]
        blobs.append(self.store.canonical_dump().decode('utf-8', 'replace'))
        for text in (*texts, *blobs):
            for needle in needles:
                self.assertNotIn(needle, text)
