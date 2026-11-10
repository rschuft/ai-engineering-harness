"""Live: the acceptance recorder's output under the pinned OpenSpec 1.16.0 (plan leaf P-04.1).

Skipped unless AIEH_OPENSPEC names OpenSpec's entry point (install it outside the checkout as
integrations/planning/README.md describes). On a throwaway copy of the recorder's fixture project,
with the intent-driven schema added, the recorder records a (synthetic) acceptance of qual-02's O1;
then ``openspec validate --strict`` accepts the change holding ``owner-decisions/<id>.json`` and
``x-outcomes``, and ``openspec archive --yes`` moves the whole change, the decision record
included, byte for byte. The lineage objective resolver then resolves the outcome at its archived
path, and still at its active path when pinned at the recording.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'e2e'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import owner_fixture as of  # noqa: E402

A, fx = of.A, of.fx
L, R = A.L, A.R
OPENSPEC = os.environ.get('AIEH_OPENSPEC')
CHANGE = of.HAND_ACCEPTED  # qual-02: the fixture change with a delta spec, which validate --strict needs


def digests(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).rglob('*')) if p.is_file()}


@unittest.skipUnless(OPENSPEC, 'set AIEH_OPENSPEC to run the live OpenSpec tests')
class LiveOpenSpec(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fx.require_repository_access()
        cls.openspec = fx.adapter.tool_argv(OPENSPEC)
        cls.work = Path(tempfile.mkdtemp(prefix='lo-'))  # short: the archived paths are deep
        (cls.work / 'home').mkdir()
        cls.env = fx.isolated_env(cls.work / 'home')
        cls.repo = cls.work / 'p'
        with mock.patch.dict(os.environ, cls.env), fx.ceiling(cls.work):
            if fx.tool_version(cls.openspec, cls.work) != fx.OPENSPEC_VERSION:
                raise unittest.SkipTest('not the pinned OpenSpec')
            of.build_project(cls.repo)
            fx.write(cls.repo, {f'openspec/schemas/intent-driven/{p.relative_to(fx.SCHEMA).as_posix()}':
                                p.read_bytes() for p in sorted(fx.SCHEMA.rglob('*')) if p.is_file()})
            fx.commit_all(cls.repo, 'the intent-driven schema')
            cls.result = A.record(cls.repo, A.prepare(cls.repo, CHANGE, 'O1'),
                                  of.statement(reference='conversation:qual-02/message-2'),
                                  recorded_by=of.RECORDED_BY, identity=of.IDENTITY)

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.work)

    def openspec_run(self, *args):
        with mock.patch.dict(os.environ, self.env):
            return subprocess.run([*self.openspec, *args], cwd=self.repo, capture_output=True, text=True,
                                  encoding='utf-8', stdin=subprocess.DEVNULL, timeout=fx.WAIT_CEILING_S)

    def test_validate_strict_then_archive_moves_the_decision_record_unchanged(self):
        base = self.repo / 'openspec' / 'changes' / CHANGE
        before = digests(base)
        self.assertIn(self.result['path'].removeprefix(f'openspec/changes/{CHANGE}/'), before)
        valid = self.openspec_run('validate', CHANGE, '--strict')
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        report = json.loads(self.openspec_run('validate', CHANGE, '--strict', '--json').stdout)
        self.assertEqual(report['summary']['totals'], {'items': 1, 'passed': 1, 'failed': 0})

        archived = self.openspec_run('archive', CHANGE, '--yes')
        self.assertEqual(archived.returncode, 0, archived.stdout + archived.stderr)
        self.assertFalse(base.exists())
        moved = sorted((self.repo / 'openspec' / 'changes' / 'archive').glob(f'*-{CHANGE}'))
        self.assertEqual(len(moved), 1)
        self.assertEqual(digests(moved[0]), before)  # the record and .openspec.yaml included

        with mock.patch.dict(os.environ, self.env), fx.ceiling(self.work):
            archived_commit = fx.commit_all(self.repo, 'openspec archive')
            resolver = R.ObjectiveResolver(self.repo)
            current = resolver.current(L.parse(f'outcome:{self.result["outcome"]}'))
            pinned = resolver.resolve(L.parse(self.result['reference']))
        self.assertEqual((current.outcome, current.observed_revision), (L.RESOLVED, archived_commit))
        self.assertEqual(current.facts['change'], f'openspec/changes/archive/{moved[0].name}')
        self.assertEqual(current.facts['acceptance'], 'conversation:qual-02/message-2')
        self.assertEqual((pinned.outcome, pinned.facts['change']), (L.RESOLVED, f'openspec/changes/{CHANGE}'))
        self.assertEqual(current.observed_digest, pinned.observed_digest)


if __name__ == '__main__':
    unittest.main()
