"""Tests for the live D1 run's dispatcher side (D1 slice C: ``tests/live_d1_run.py`` ``D1Dispatcher``), offline.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_live_d1_run.py -v

Shown, on E-05.9's native D1 fixture (a throwaway store, manifest and catalog; a fake Agent Server; a synthetic
token): the manifest is loaded for each dispatch, through the loader, never cached, and a hand-built manifest is
refused by dispatch (MANIFEST_NOT_PROMOTED); the native entry is read once per attempt (the dispatcher's read) and the
verifier receives that value as its own in-memory token; a second read, another entry and any write are refused and
counted; the builder bot's entry is the only one the result path may read; the read-only preparation checks the
expected manifest and policy digest; the conversation's delete goes through the route-checked client; a resumed run's
read must hold the attempt's token.
"""
from pathlib import Path
import importlib.util
import hashlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


te = _load('test_attempt_end', HERE / 'test_attempt_end.py')
di, AE, store_mod = te.di, te.AE, te.store_mod
NT = di._native_module()
LD = _load('live_d1_run', HERE / 'live_d1_run.py')
TOKEN = te.NF.TOKEN


class Fixture(te.EndFixture):
    def dispatcher(self, load_manifest=None, provider=None, expected=None):
        resolved = self.resolve_d1(self.manifest)
        return LD.D1Dispatcher(
            request=self.d1_request(), integration_store=self.store, workspaces=self.workspaces,
            work_source=self.d1_sources[self.d1_request()['repository']], project=None,
            load_manifest=load_manifest or (lambda: self.manifest),
            resolve=lambda request: (self.resolve_d1(self.manifest), self.manifest),
            expected=expected or {'manifest_version': self.manifest.version, 'manifest_sha256': self.manifest.sha256,
                                  'policy_digest': resolved.policy_digest},
            provider=provider or self.provider, gitea_port=3000, read_profile=self.read_profile,
            read_artifact=self.read_artifact, catalog_sources=self.catalog.sources)


class Dispatch(Fixture):
    def test_the_manifest_is_loaded_for_each_dispatch_and_the_token_read_once(self):
        loads, held = [], []

        def load():
            loads.append(1)
            return self.manifest
        dispatcher = self.dispatcher(load_manifest=load)
        self.assertEqual(loads, [])                                   # never at construction
        result = dispatcher.dispatch(self.server, held.append)
        self.assertEqual(loads, [1])
        self.assertEqual(result['native_entry_reads'], 1)
        self.assertEqual(self.provider.reads, [NT.ENTRY])
        self.assertEqual([t.fingerprint for t in held], [NT.fingerprint(TOKEN)])
        self.assertTrue(held[0].open)                                 # the verifier's own copy, not dropped
        self.assertEqual(result['native_token']['tokenFingerprint'], NT.fingerprint(TOKEN))
        self.assertTrue(result['manifest']['loaded_for_this_dispatch'])
        self.assertEqual(result['conversation_id'], store_mod.conversation_id_for(result['operation_key']))

    def test_a_hand_built_manifest_is_refused(self):
        raw = self.manifest.data_json.encode('utf-8')
        dispatcher = self.dispatcher(load_manifest=lambda: di.parse_manifest(raw))
        with self.assertRaises(di.DispatchRefused) as caught:
            dispatcher.dispatch(self.server, lambda token: self.fail('no token is read'))
        self.assertEqual(caught.exception.code, 'MANIFEST_NOT_PROMOTED')
        self.assertEqual(self.provider.reads, [])

    def test_the_delete_goes_through_the_route_checked_client(self):
        dispatcher = self.dispatcher()
        result = dispatcher.dispatch(self.server, lambda token: None)
        calls = []

        def transport(method, path, body):
            calls.append((method, path, body))
            return {'status': 200, 'body': {'success': True}}
        self.assertEqual(dispatcher.delete(result['operation_key'], transport), 200)
        self.assertEqual(calls, [('DELETE', f'/api/conversations/{result["conversation_id"]}', None)])

    def base(self, extra=None):
        tar = _load('test_attempt_run', HERE / 'test_attempt_run.py')
        resolved = self.resolve_d1(self.manifest)
        change = LD.AR._design(resolved)['change']
        path = Path(tempfile.mkdtemp(prefix='aieh-d1-base-'))
        self.addCleanup(shutil.rmtree, path, True)
        commits = tar.make_repository(path / 'demo', tar.demo_trees(resolved.work_id, change, extra))
        return LD.AR.read_base(path / 'demo', repository=resolved.repository, design_commit=commits['C2'])

    def test_the_preparation_checks_the_expected_inputs(self):
        dispatcher = self.dispatcher()
        with mock.patch.object(LD.AR, 'read_base', return_value=self.base()) as read_base:
            prepared = dispatcher.prepare()
            self.assertEqual(prepared['verdict'], 'PASS', prepared['checks'])
            self.assertLess(prepared['command_bytes']['result'], LD.ARG_LIMIT)
            dispatcher.expected['policy_digest'] = 'sha256:' + '0' * 64
            self.assertEqual(dispatcher.prepare()['verdict'], 'FAIL')
        # a base whose RESULT command would not fit one argument of /bin/sh -c (its bundle in the command, hex twice)
        noise, block = {}, b'noise'
        for n in range(1536):                                     # about 48 KiB that does not compress
            block = hashlib.sha256(block).digest()
            noise[f'big/{n // 512}.bin'] = noise.get(f'big/{n // 512}.bin', b'') + block
        dispatcher.expected['policy_digest'] = prepared['seen']['policy_digest']
        with mock.patch.object(LD.AR, 'read_base', return_value=self.base(noise)):
            big = dispatcher.prepare()
        self.assertEqual(big['verdict'], 'FAIL')
        self.assertFalse(big['checks']['the SEED and RESULT commands fit one argument'], big['command_bytes'])
        self.assertEqual(read_base.call_args.kwargs['repository'], prepared['repository'])
        self.assertEqual(prepared['conversation_id'], store_mod.conversation_id_for(prepared['operation_key']))
        self.assertEqual(self.store.attempts(), [])                   # read only: nothing reserved
        self.assertEqual(self.provider.reads, [])

    def test_a_resumed_read_must_hold_the_attempt_s_token(self):
        dispatcher = self.dispatcher()
        result = dispatcher.dispatch(self.server, lambda token: None)
        held = []
        dispatcher.read_native(held.append, result['operation_key'])
        self.assertEqual([t.fingerprint for t in held], [NT.fingerprint(TOKEN)])
        other = te.NF.NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, te.NF.OTHER)})
        dispatcher.provider = other
        with self.assertRaises(di.DispatchRefused) as caught:
            dispatcher.read_native(lambda token: self.fail('never handed on'), result['operation_key'])
        self.assertEqual(caught.exception.code, 'OUTBOUND_TOKEN_MISMATCH')


class Stops(Fixture):
    """Review of B and C, B1: a stop recorded durably refuses the resume, the recorded result and the result path."""

    def test_a_recorded_stop_refuses_every_later_act(self):
        dispatcher = self.dispatcher()
        result = dispatcher.dispatch(self.server, lambda token: None)
        key = result['operation_key']
        self.assertEqual(dispatcher.stops(key), [])
        record = {'kind': 'credential-stop', 'code': 'TOKEN_ECHOED', 'ref': f'attempt:{result["attempt_id"]}#run'}
        written = dispatcher.record_stop(key, [record])
        self.assertEqual(dispatcher.record_stop(key, [dict(record, ref='attempt:x#later')]), written)   # one receipt
        held = self.store.get(written[0])
        self.assertEqual(held.state, 'confirmed')
        self.assertNotIn('ref', held.intent_json)                     # the intent: attempt, kind and code
        self.assertEqual(dispatcher.stops(key), [{'kind': 'credential-stop', 'code': 'TOKEN_ECHOED'}])
        self.assertEqual(dispatcher.state(key)['stops'], dispatcher.stops(key))
        for call in (lambda: dispatcher.resume(key, self.server, None, None, None), lambda: dispatcher.recorded(key),
                     lambda: dispatcher.publish(key, None, None, None, {}, None)):
            with self.assertRaises(LD.ResumeRefused) as caught:
                call()
            self.assertEqual(caught.exception.code, 'ATTEMPT_STOP_RECORDED')
        with self.assertRaises(di.DispatchRefused):
            dispatcher.record_stop(key, [{'kind': 'not-a-kind', 'code': 'X', 'ref': 'a'}])

    def test_the_run_defers_a_run_that_did_not_start_to_the_driver(self):
        dispatcher = self.dispatcher()
        with mock.patch.object(LD.AR, 'run_attempt', return_value='outcome') as run:
            dispatcher.base = object()
            self.assertEqual(dispatcher.run('k', self.server, None, None, None), 'outcome')
        self.assertTrue(run.call_args.kwargs['defer_interruption_end'])

    def test_the_resumed_read_keeps_one_open_token(self):
        """NIT 2: the wrapper's own copy is dropped; only the token handed on stays open."""
        dispatcher = self.dispatcher()
        result = dispatcher.dispatch(self.server, lambda token: None)
        made = []
        real = NT.NativeToken

        class Counting(real):
            __slots__ = ()

            def __init__(self, token):
                super().__init__(token)
                made.append(self)
        held = []
        with mock.patch.object(NT, 'NativeToken', Counting):
            dispatcher.read_native(held.append, result['operation_key'])
        self.assertEqual(len(held), 1)
        self.assertTrue(held[0].open)
        self.assertEqual([t.open for t in made if t is not held[0]], [False] * (len(made) - 1))


trp = _load('test_result_path', HERE / 'test_result_path.py')


class Regenerate(trp.Fixture):
    """NIT 6: a resume with a confirmed result journal and no report regenerates the report from the receipt and
    the verified objects (searched before it is written), saying which texts are digests only."""

    def test_the_report_is_regenerated_from_the_receipt(self):
        verified = self.reserved(resumed=True)       # as recorded_result makes it from the intake: digests only
        self.assertEqual(self.publish(verified).outcome, 'confirmed')            # no report directory then
        dispatcher = LD.D1Dispatcher(
            request={}, integration_store=self.store, workspaces=None, work_source=None, project=None,
            load_manifest=None, resolve=None, expected={}, provider=self.bot_provider, gitea_port=trp.PORT,
            http=self.gitea, read_artifact=self.read_artifact)
        recorded = verified
        report_dir = self.scratch / 'report'
        with mock.patch.object(LD.RP, 'gitea_target', return_value=self.target):
            out = dispatcher.publish(self.key, recorded, self.native, {'run': 'resumed'}, {}, report_dir)
        self.assertEqual(out['outcome'], 'already-confirmed')
        self.assertTrue(out['report_regenerated']['digest_only_texts'])
        text = (report_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn(str(out['receipt']['pullRequest']['number']), text)
        self.assertNotIn(trp.te.TOKEN, text + (report_dir / 'report.json').read_text(encoding='utf-8'))
        with mock.patch.object(LD.RP, 'gitea_target', return_value=self.target):   # a report there is kept
            again = dispatcher.publish(self.key, recorded, self.native, {'run': 'resumed'}, {}, report_dir)
        self.assertIsNone(again['report_regenerated'])


class Providers(unittest.TestCase):
    def test_one_native_read(self):
        held = []
        source = te.NF.NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, TOKEN), 'other': ('u', 'v')})
        provider = LD.OneNativeRead(source, held.append)
        self.assertEqual(provider.get(NT.ENTRY), (NT.ENTRY_USER, TOKEN))
        for call in (lambda: provider.get(NT.ENTRY), lambda: provider.get('other'),
                     lambda: provider.set(NT.ENTRY, 'u', 'v'), lambda: provider.delete(NT.ENTRY)):
            with self.assertRaises(LD.EntryRefused):
                call()
        self.assertEqual(source.reads, [NT.ENTRY])
        self.assertEqual([r[0] for r in provider.refused], ['get', 'get', 'set', 'delete'])
        self.assertEqual(len(held), 1)

    def test_a_value_without_the_token_s_shape_is_never_handed_on(self):
        held = []
        source = te.NF.NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, 'sk-ant-api03-' + 'k' * 50)})
        LD.OneNativeRead(source, held.append).get(NT.ENTRY)
        self.assertEqual(held, [])

    def test_only_the_builder_entry_for_the_result_path(self):
        builder = LD.RP.roles.target(LD.RP.AT.STAGE_ROLES['implement'])
        self.assertEqual(builder, 'AIEH Gitea bot builder')
        source = te.NF.NS.ObservedProvider({builder: ('aieh-bot-builder', 'x'), NT.ENTRY: (NT.ENTRY_USER, TOKEN)})
        provider = LD.AllowedEntries(source, [builder])
        self.assertEqual(provider.get(builder), ('aieh-bot-builder', 'x'))
        with self.assertRaises(LD.EntryRefused):
            provider.get(NT.ENTRY)
        with self.assertRaises(LD.EntryRefused):
            provider.set(builder, 'u', 'v')
        self.assertEqual(source.reads, [builder])


if __name__ == '__main__':
    unittest.main()
