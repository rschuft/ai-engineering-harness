"""Route and model discovery (inference_qualification.py discover and propose-pin, S-03.3 slice 3 part two), in
this process only.

The reader turns one broker run's audit into a PROPOSED family pin: the exact routes and the exact model names (a
secondary model included) of the requests that presented a grant, with their answers and query parameter names;
flags for what a pin cannot rest on (no top-level model, S-03.5's F7; an unrecorded or withheld value; a query
string the family refuses; requests without a grant); nothing outside the audit's grammars carried, no wildcard;
families.json never written. The discovery mode is the qualification launcher with each keyed family's fake
upstream bound by the same process on its configured loopback upstream, before the key is read; at the stop it
writes the proposal of the run's audit and what the fake upstream received. Every key is synthetic, every listener
is on a 127.0.0.1 port of this process, and the store, logs and proposals are in temporary directories.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import socket
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import broker_support as S

CATEGORY = 'unit'
IB = S.IB
IC = S._load('aieh_inference_control', S.HERE.parent / 'inference_control.py')
IQ = S._load('aieh_inference_qualification', S.HERE.parent / 'inference_qualification.py')
FAMILIES = S.HERE.parent / 'families.json'
PROVIDER_ID = 'qualification'
SYNTHETIC = IQ.SYNTHETIC_PREFIX + 'discovery-' + 'Zq4' * 6
MAIN, SECONDARY = 'syn-main-model', 'syn-small-fast-model'
FP = 'sha256:' + '1' * 16
ATTEMPT, OTHER_ATTEMPT = str(uuid.uuid4()), str(uuid.uuid4())
# the keys of an audit line of a request, as Broker.serve_inference writes them (checked against its source below)
LINE_KEYS = ('event', 'attempt_id', 'conversation_id', 'token_fingerprint', 'family', 'method', 'path',
             'query_names', 'model', 'unrecorded', 'request_bytes', 'response_bytes', 'status', 'upstream_status',
             'latency_ms', 'usage', 'code')


def line(attempt=ATTEMPT, fingerprint=FP, family='anthropic-messages', method='POST', path='/v1/messages',
         query_names=None, model=MAIN, unrecorded=None, code=None, status=200) -> dict:
    record = dict.fromkeys(LINE_KEYS)
    record.update(format=IB.AUDIT_FORMAT, time='2026-11-13T00:00:00Z', event='request', attempt_id=attempt,
                  conversation_id=None if attempt is None else str(uuid.uuid4()), token_fingerprint=fingerprint,
                  family=family, method=method, path=path, query_names=query_names, model=model,
                  unrecorded=unrecorded, code=code, status=status)
    return record


def unattributed(method='GET', path='/v1/models', query_names=None, code='TOKEN_MISSING') -> dict:
    return line(attempt=None, fingerprint=None, family=None, method=method, path=path, query_names=query_names,
                model=None, code=code, status=401)


def flags(proposal, code=None):
    return [f for f in proposal['flags'] if code is None or f['code'] == code]


class Reader(unittest.TestCase):
    """propose_pin over audit records."""

    def setUp(self):
        self.declarations = IB.load_declarations()

    def propose(self, records, **kw):
        proposal = IQ.propose_pin(records, self.declarations, **kw)
        json.dumps(proposal)                                         # JSON throughout
        return proposal

    def test_the_line_keys_are_the_brokers(self):
        source = (S.HERE.parent / 'inference_broker.py').read_text(encoding='utf-8')
        start = source.index("line = {'event': 'request'")
        text = source[start:source.index('}', start)]
        self.assertEqual(tuple(re.findall(r"'(\w+)':", text)), LINE_KEYS)

    def test_exact_routes_and_models_with_their_answers_and_flags(self):
        records = [line(),
                   line(query_names=['beta'], code='QUERY_NOT_ALLOWED', status=400),
                   line(model=SECONDARY, code='MODEL_NOT_ALLOWED', status=403),
                   line(path='/v1/messages/count_tokens', query_names=['beta'], code='ROUTE_NOT_ALLOWED', status=404),
                   line(method='GET', path='/v1/models', model=None, code='ROUTE_NOT_ALLOWED', status=404),
                   unattributed()]
        proposal = self.propose(records, source={'audit_file': 'audit-x.jsonl', 'withheld': 0, 'unreadable': 0})
        self.assertEqual((proposal['format'], proposal['status'], proposal['applied'], proposal['complete']),
                         ('aieh-inference-family-pin-proposal/1', 'proposed', False, False))   # F2: unattributed
        self.assertTrue(self.propose(records[:-1])['complete'])
        self.assertIn('never applied', proposal['statement'])
        self.assertIn('decision 0018 point 3', proposal['statement'])
        self.assertIn("Owner's approval", proposal['statement'])
        (family,) = proposal['families']
        self.assertEqual(family['family'], 'anthropic-messages')
        self.assertEqual(family['proposed'], {
            'routes': [{'method': 'POST', 'path': '/v1/messages'},
                       {'method': 'POST', 'path': '/v1/messages/count_tokens'},
                       {'method': 'GET', 'path': '/v1/models'}],
            'models': [MAIN, SECONDARY]})
        self.assertEqual(family['declared'], {'status': 'provisional', 'query': ['beta=true'],
                                              'routes': [{'method': 'POST', 'path': '/v1/messages'}]})
        self.assertEqual(family['compared'], {'declared_not_observed': [], 'observed_not_declared': [
            {'method': 'POST', 'path': '/v1/messages/count_tokens'}, {'method': 'GET', 'path': '/v1/models'}]})
        messages = family['observed']['routes'][0]
        self.assertEqual(messages, {'method': 'POST', 'path': '/v1/messages', 'requests': 3,
                                    'codes': {'(passed)': 1, 'MODEL_NOT_ALLOWED': 1, 'QUERY_NOT_ALLOWED': 1},
                                    'with_query': 1, 'query_names': ['beta'], 'models': [MAIN, SECONDARY],
                                    'no_top_level_model': 0, 'model_unrecorded': 0, 'declared': True,
                                    'declarable': True})
        self.assertEqual(family['observed']['models'], [
            {'model': MAIN, 'requests': 3, 'routes': ['POST /v1/messages', 'POST /v1/messages/count_tokens'],
             'codes': {'(passed)': 1, 'QUERY_NOT_ALLOWED': 1, 'ROUTE_NOT_ALLOWED': 1}},
            {'model': SECONDARY, 'requests': 1, 'routes': ['POST /v1/messages'], 'codes': {'MODEL_NOT_ALLOWED': 1}}])
        self.assertEqual([(f['code'], f.get('route')) for f in proposal['flags']],
                         [('QUERY_OBSERVED', 'POST /v1/messages'),
                          ('QUERY_OBSERVED', 'POST /v1/messages/count_tokens'),
                          ('MODEL_NOT_TOP_LEVEL', 'GET /v1/models'),
                          ('UNATTRIBUTED_REQUESTS', None)])
        self.assertIn('F7', flags(proposal, 'MODEL_NOT_TOP_LEVEL')[0]['detail'])
        self.assertEqual(proposal['unattributed'], [{'method': 'GET', 'path': '/v1/models', 'requests': 1,
                                                     'query_names': [], 'codes': {'TOKEN_MISSING': 1}}])
        self.assertEqual(proposal['attempts'], [{'attempt_id': ATTEMPT, 'token_fingerprint': FP,
                                                 'family': 'anthropic-messages'}])
        self.assertIn('top-level model only', proposal['not_shown'][0])
        for value in [r['path'] for r in family['proposed']['routes']] + family['proposed']['models']:
            self.assertIsNone(IB.WILDCARD.search(value))

    def test_what_the_audit_did_not_record_makes_it_incomplete(self):
        cases = (
            (line(model=None, unrecorded={'model': 1}, code='MODEL_NOT_ALLOWED', status=403),
             ['MODEL_UNRECORDED', 'BROKER_UNRECORDED']),
            (line(path=None, unrecorded={'path': 1}, code='ROUTE_NOT_ALLOWED', status=404),
             ['PATH_UNRECORDED', 'BROKER_UNRECORDED']),
            (line(query_names=[], unrecorded={'query_names': 2}, code='QUERY_NOT_ALLOWED', status=400),
             ['QUERY_OBSERVED', 'QUERY_NAMES_UNRECORDED', 'BROKER_UNRECORDED']),
            (line(method='other', path='/', model=None, code='ROUTE_NOT_ALLOWED', status=404),
             ['ROUTE_NOT_DECLARABLE', 'MODEL_NOT_TOP_LEVEL']))
        for record, expected in cases:
            with self.subTest(expected=expected):
                proposal = self.propose([line(), record])
                self.assertEqual([f['code'] for f in proposal['flags']], expected)
                self.assertEqual(proposal['complete'], 'BROKER_UNRECORDED' not in expected)
                self.assertEqual(proposal['families'][0]['proposed']['models'], [MAIN])
        for source, code in (({'withheld': 1}, 'AUDIT_LINES_WITHHELD'), ({'unreadable': 2}, 'AUDIT_LINES_UNREADABLE')):
            proposal = self.propose([line()], source=source)
            self.assertEqual(([f['code'] for f in proposal['flags']], proposal['complete']), ([code], False))
        proposal = self.propose([unattributed()])
        self.assertEqual(([f['code'] for f in proposal['flags']], proposal['complete'], proposal['families']),
                         (['UNATTRIBUTED_REQUESTS', 'NO_GRANT_REQUESTS'], False, []))

    def test_nothing_outside_the_audits_grammars_is_carried(self):
        planted = ('claude-*', 'aieh-inf-' + 'A' * 43, 'model with space', 'x' * 129)
        records = [line()] + [line(model=m, code='MODEL_NOT_ALLOWED', status=403) for m in planted] + [
            line(path='/v1/a b'), line(path='/v1/aieh-inf-abc'), line(path='v1/messages'),
            line(path='/' + '/'.join(['s'] * 17)),
            line(query_names=['ok', 'bad name', 'aieh-inf-x', 7]), line(unrecorded=['model']),
            line(unrecorded={'model': True, 'headers': 1}), line(code='lower-case'), line(method='BREW')]
        proposal = self.propose(records)
        text = json.dumps(proposal)
        for value in planted + ('/v1/a b', 'aieh-inf-', 'bad name', '"v1/messages"', 'BREW', 'lower-case'):
            self.assertNotIn(value, text)
        dropped = flags(proposal, 'READER_DROPPED')[0]['detail']
        self.assertIn("'model': 4", dropped)
        self.assertIn("'path': 4", dropped)
        self.assertIn("'query_names': 3", dropped)
        self.assertIn("'unrecorded': 3", dropped)
        self.assertFalse(proposal['complete'])
        (family,) = proposal['families']
        self.assertEqual(family['proposed']['models'], [MAIN])
        self.assertEqual([r['path'] for r in family['proposed']['routes']], ['/v1/messages'])
        routes = {(r['method'], r['path']): r for r in family['observed']['routes']}
        self.assertEqual(routes[('POST', None)]['requests'], 4)
        self.assertEqual(routes[('POST', '/v1/messages')]['codes']['(other)'], 1)
        self.assertIn(('other', '/v1/messages'), routes)
        self.assertEqual(routes[('POST', '/v1/messages')]['query_names'], ['ok'])

    def test_grants_attempts_and_families(self):
        records = [line(), line(attempt=OTHER_ATTEMPT, model=SECONDARY),
                   line(fingerprint='sha256:short'), line(attempt='not-a-uuid'), line(family='unknown-family'),
                   line(family='openai-chat', path='/v1/chat/completions', model=MAIN)]
        proposal = self.propose(records)
        self.assertEqual([f['family'] for f in proposal['families']], ['anthropic-messages', 'openai-chat'])
        self.assertEqual(proposal['families'][0]['proposed']['models'], [MAIN, SECONDARY])
        self.assertEqual(sum(r['requests'] for r in proposal['unattributed']), 3)
        only = self.propose(records, attempt_id=OTHER_ATTEMPT)
        self.assertEqual([(f['family'], f['proposed']['models']) for f in only['families']],
                         [('anthropic-messages', [SECONDARY])])
        self.assertEqual(only['source']['attempt_filter'], OTHER_ATTEMPT)
        self.assertEqual([a['attempt_id'] for a in only['attempts']], [OTHER_ATTEMPT])


class KeyPaths(unittest.TestCase):
    """F7, the engineering manager's option (b): the JSON key paths of an admitted body, names only, and the
    reader's MODEL_KEY_ELSEWHERE, KEY_PATHS_TRUNCATED and KEY_NAMES_UNRECORDED."""

    HIDDEN = 'syn-hidden-secondary-model'

    def test_names_only_arrays_collapsed_bounded(self):
        body = {'model': MAIN, 'max_tokens': 5, 'messages': [{'role': 'user', 'content': [{'type': 'text',
                                                                                            'text': 'hello'}]},
                                                              {'role': 'assistant', 'content': 'x'}],
                'metadata': {'fallback_model': self.HIDDEN, 'user_id': 'u'},
                'extra': {'a.b': 1, 'aieh-inf-k': 2, '': 3, 'k' * 33: 4}, 'tools': []}
        result = IQ.body_key_paths(json.dumps(body).encode())
        self.assertEqual(result, {'body': 'json', 'key_paths_truncated': False, 'key_names_unrecorded': 4,
                                  'key_paths': sorted(['model', 'max_tokens', 'messages', 'messages[].role',
                                                       'messages[].content', 'messages[].content[].type',
                                                       'messages[].content[].text', 'metadata',
                                                       'metadata.fallback_model', 'metadata.<map>', 'extra',
                                                       'extra.<unrecorded>', 'tools'])})
        text = json.dumps(result)
        for value in (MAIN, self.HIDDEN, 'hello', 'a.b', 'aieh-inf-k', 'user_id', 'k' * 33):
            self.assertNotIn(value, text)
        self.assertEqual(IQ.body_key_paths(json.dumps([{'k': 1}]).encode())['key_paths'], ['[].k'])
        for raw, kind in ((b'', 'empty'), (b'not json', 'not a JSON object or array'), (b'"s"', 'not a JSON object '
                                                                                                  'or array')):
            self.assertEqual(IQ.body_key_paths(raw), {'body': kind, 'key_paths': [], 'key_paths_truncated': False,
                                                      'key_names_unrecorded': 0})
        wide = IQ.body_key_paths(json.dumps({f'k{i}': i for i in range(IQ.KEY_PATH_LIMIT + 5)}).encode())
        self.assertEqual((len(wide['key_paths']), wide['key_paths_truncated']), (IQ.KEY_PATH_LIMIT, True))
        deep = {}
        node = deep
        for _ in range(IQ.KEY_PATH_DEPTH + 3):
            node['d'] = {}
            node = node['d']
        self.assertTrue(IQ.body_key_paths(json.dumps(deep).encode())['key_paths_truncated'])
        self.assertFalse(IQ.body_key_paths(json.dumps({'d': {'d': {}}}).encode())['key_paths_truncated'])

    def upstream(self, paths, truncated=False, unnamed=0):
        return {'anthropic-messages': {'requests': 1, 'routes': {}, 'credential_is_the_synthetic_key': True,
                                       'key_paths': {'POST /v1/messages': {
                                           'requests': 1, 'paths': paths, 'truncated': truncated,
                                           'names_unrecorded': unnamed, 'bodies': {'json': 1}}}}}

    def test_the_reader_flags_a_model_key_elsewhere_by_path_only(self):
        declarations = IB.load_declarations()
        only_top = IQ.propose_pin([line()], declarations, upstream=self.upstream(['messages', 'model']))
        self.assertEqual((only_top['flags'], only_top['complete']), ([], True))
        self.assertIn('only admitted requests reach', only_top['not_shown'][0])
        planted = IQ.propose_pin([line()], declarations, upstream=self.upstream(
            ['messages', 'messages[].Model_Hint', 'metadata', 'metadata.fallback_model', 'model', 'modelling.x']))
        (flag,) = planted['flags']
        self.assertEqual((flag['code'], flag['family'], flag['route'], flag['paths']),
                         ('MODEL_KEY_ELSEWHERE', 'anthropic-messages', 'POST /v1/messages',
                          ['messages[].Model_Hint', 'metadata.fallback_model']))
        self.assertIn('F7', flag['detail'])
        self.assertTrue(planted['complete'])
        cut = IQ.propose_pin([line()], declarations, upstream=self.upstream(['model'], truncated=True, unnamed=2))
        self.assertEqual(([f['code'] for f in cut['flags']], cut['complete']),
                         (['KEY_PATHS_TRUNCATED', 'KEY_NAMES_UNRECORDED'], False))
        self.assertIn('top-level model only', IQ.propose_pin([line()], declarations)['not_shown'][0])
        not_shown = ' '.join(only_top['not_shown'])
        self.assertIn('does not contain "model"', not_shown)
        self.assertIn('a key name can itself carry data', not_shown)
        for name in sorted(IQ.OPEN_MAPS) + ['_metadata']:
            self.assertIn(name, not_shown)

    def test_the_reviews_p2_bodies_key_names_that_are_data(self):
        """F3: under the open maps a key name is recorded only when it contains "model"; elsewhere a name longer
        than 32 characters (a token body) is not recorded."""
        email, user = 'jane.doe@example.com', 'user_8f3a2c91d4'
        for body, expected, unnamed in (
                ({'model': 'm', 'metadata': {user: 'x', email: 1, 'fallback_model': 'b'}},
                 ['metadata', 'metadata.<map>', 'metadata.fallback_model', 'model'], 0),
                ({'model': 'm', 'tools': [{'input_schema': {'properties': {'ssn_last4': {}, 'Model': {}}}}]},
                 ['model', 'tools', 'tools[].input_schema', 'tools[].input_schema.<map>',
                  'tools[].input_schema.<map>.<map>', 'tools[].input_schema.<map>.Model'], 0),
                ({'model': 'm', 'x': {'A' * 43: 1}}, ['model', 'x', 'x.<unrecorded>'], 1),
                ({'model': 'm', 'request_metadata': {'tenant-a': {'deep': 1}}, 'parameters': {'p': 1},
                  'definitions': {'d': 1}, '$defs': {'e': 1}},
                 ['$defs', '$defs.<map>', 'definitions', 'definitions.<map>', 'model', 'parameters',
                  'parameters.<map>', 'request_metadata', 'request_metadata.<map>', 'request_metadata.<map>.<map>'],
                 0)):
            with self.subTest(body=sorted(body)):
                result = IQ.body_key_paths(json.dumps(body).encode())
                self.assertEqual((result['key_paths'], result['key_names_unrecorded']), (expected, unnamed))
                for data in (email, user, 'ssn_last4', 'A' * 43, 'tenant-a', 'deep'):
                    self.assertNotIn(data, json.dumps(result))
        summary = {'anthropic-messages': {'key_paths': {'POST /v1/messages': {
            'paths': IQ.body_key_paths(json.dumps({'model': 'm', 'metadata': {'fallback_model': 'b'}}).encode())
            ['key_paths'], 'truncated': False, 'names_unrecorded': 0}}}}
        (flag,) = IQ.propose_pin([line()], IB.load_declarations(), upstream=summary)['flags']
        self.assertEqual((flag['code'], flag['paths']), ('MODEL_KEY_ELSEWHERE', ['metadata.fallback_model']))

    def test_upstream_summary_credentials_and_requests(self):
        """F4: the substitution is shown only when every request carried exactly the provider key's fingerprint."""
        family = IB.load_declarations()['anthropic-messages']
        right, wrong = 'sha256:' + 'a' * 16, 'sha256:' + 'b' * 16

        class Fake:
            def __init__(self, *fingerprints_per_request):
                lines = [{'event': 'start'}] + [
                    {'event': 'request', 'family': family.id, 'method': 'POST', 'path': '/v1/messages',
                     'status': 200, 'credential_fingerprints': fps} for fps in fingerprints_per_request]
                self.out = io.StringIO(''.join(json.dumps(r) + '\n' for r in lines))

        for fake, expected in ((Fake([right]), True), (Fake([right], [right]), True), (Fake([wrong]), False),
                               (Fake([right], [wrong]), False), (Fake([]), False), (Fake([right, right]), False),
                               (Fake(), None)):
            with self.subTest(expected=expected):
                summary = IQ.upstream_summary({'anthropic-messages': fake}, right)['anthropic-messages']
                self.assertIs(summary['credential_is_the_synthetic_key'], expected)
        empty = IQ.upstream_summary({'anthropic-messages': Fake()}, right)['anthropic-messages']
        self.assertEqual((empty['requests'], empty['routes'], empty['key_paths']), (0, {}, {}))


class Command(unittest.TestCase):
    """propose-pin: the audit file read, the proposal written to a new file outside the checkout, never
    families.json."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-pin-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.audit = self.tmp / 'audit-20261113T000000Z-abcd1234.jsonl'
        lines = [line(), line(model=SECONDARY, code='MODEL_NOT_ALLOWED', status=403),
                 {'format': IB.AUDIT_FORMAT, 'time': 't', 'event': 'broker-start', 'receipt': 'r'},
                 {'format': IB.AUDIT_FORMAT, 'time': 't', 'withheld': 'EXPOSURE_FOUND'}]
        self.audit.write_text(''.join(json.dumps(r) + '\n' for r in lines) + 'not json\n\n{"format": "x"}\n',
                              encoding='utf-8')

    def main(self, *argv):
        ctx = type('Ctx', (), {})()
        ctx.out, ctx.err = io.StringIO(), io.StringIO()
        return IQ.main(['propose-pin', *argv], ctx), ctx

    def test_the_proposal_is_written_to_a_new_file_and_nothing_else(self):
        families = FAMILIES.read_bytes()
        out = self.tmp / 'proposal.json'
        code, ctx = self.main('--audit', str(self.audit), '--out', str(out))
        self.assertEqual(code, 0, ctx.err.getvalue())
        proposal = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(proposal['source'], {
            'audit_file': self.audit.name, 'bytes': self.audit.stat().st_size,
            'sha256': hashlib.sha256(self.audit.read_bytes()).hexdigest(), 'lines': 6, 'requests': 2,
            'unreadable': 2, 'withheld': 1, 'attempt_filter': None})
        self.assertEqual(proposal['families'][0]['proposed']['models'], [MAIN, SECONDARY])
        self.assertFalse(proposal['complete'])
        summary = json.loads(ctx.out.getvalue())
        self.assertEqual(summary, {'format': IQ.PROPOSAL_FORMAT, 'out': str(out.resolve()), 'complete': False,
                                   'families': {'anthropic-messages': {'routes': 1, 'models': [MAIN, SECONDARY]}},
                                   'flags': ['AUDIT_LINES_UNREADABLE', 'AUDIT_LINES_WITHHELD']})
        self.assertEqual(FAMILIES.read_bytes(), families)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), sorted([self.audit.name, 'proposal.json']))
        code, ctx = self.main('--audit', str(self.audit), '--out', str(self.tmp / 'one.json'), '--attempt-id',
                              OTHER_ATTEMPT)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((self.tmp / 'one.json').read_text(encoding='utf-8'))['families'], [])

    def test_refusals(self):
        families = FAMILIES.read_bytes()
        missing = str(self.tmp / 'absent.jsonl')
        existing = self.tmp / 'exists.json'
        existing.write_text('{}', encoding='utf-8')
        for argv, code in (
                (['--audit', missing, '--out', str(existing)], 'PROPOSAL_OUT_REFUSED'),
                (['--audit', missing, '--out', str(FAMILIES)], 'PROPOSAL_OUT_REFUSED'),
                (['--audit', missing, '--out', str(S.REPO / 'new-proposal.json')], 'PROPOSAL_OUT_REFUSED'),
                (['--audit', missing, '--out', str(S.HERE / 'new-proposal.json')], 'PROPOSAL_OUT_REFUSED'),
                (['--audit', missing, '--out', str(self.tmp / 'no' / 'dir.json')], 'PROPOSAL_OUT_REFUSED'),
                (['--audit', missing, '--out', ' '], 'PROPOSAL_OUT_REFUSED'),
                (['--audit', missing, '--out', str(self.tmp / 'a.json'), '--attempt-id', 'X'], 'ATTEMPT_ID_INVALID'),
                (['--audit', missing, '--out', str(self.tmp / 'b.json')], 'AUDIT_UNREADABLE'),
                (['--audit', str(self.tmp), '--out', str(self.tmp / 'c.json')], 'AUDIT_UNREADABLE')):
            with self.subTest(code=code, argv=argv[-1]):
                status, ctx = self.main(*argv)
                self.assertEqual((status, ctx.out.getvalue()), (2, ''))
                self.assertIn(code, ctx.err.getvalue())
        with mock.patch.object(IQ, 'AUDIT_LIMIT', 10):
            status, ctx = self.main('--audit', str(self.audit), '--out', str(self.tmp / 'd.json'))
        self.assertEqual(status, 2)
        self.assertIn('AUDIT_UNREADABLE', ctx.err.getvalue())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), sorted([self.audit.name, 'exists.json']))
        self.assertFalse((S.REPO / 'new-proposal.json').exists())
        self.assertEqual(FAMILIES.read_bytes(), families)
        with self.assertRaises(IQ.QualificationError) as caught:
            IQ.write_proposal(self.tmp / 'e.json', {'model': SYNTHETIC})
        self.assertEqual(caught.exception.code, 'PROPOSAL_EXPOSURE')
        self.assertFalse((self.tmp / 'e.json').exists())

    def test_a_write_failure_is_a_coded_failure(self):
        """F6: PROPOSAL_WRITE_FAILED, exit 1, no traceback."""
        with mock.patch.object(IQ, 'open', side_effect=PermissionError('denied'), create=True):
            status, ctx = self.main('--audit', str(self.audit), '--out', str(self.tmp / 'w.json'))
        self.assertEqual((status, ctx.out.getvalue()), (1, ''))
        self.assertIn('PROPOSAL_WRITE_FAILED', ctx.err.getvalue())
        self.assertIn('PermissionError', ctx.err.getvalue())
        self.assertNotIn('Traceback', ctx.err.getvalue())
        self.assertFalse((self.tmp / 'w.json').exists())

    @unittest.skipUnless(os.name == 'nt', 'alternate data streams are a Windows form')
    def test_an_alternate_data_stream_of_the_checkout_is_refused(self):
        """N-A: --out <checkout>:ads.json (a stream of the checkout directory) is refused PROPOSAL_OUT_REFUSED."""
        repo = os.path.realpath(S.REPO)
        for value in (repo + ':ads.json', repo + ' :ads.json', repo + '\\x-na.json:ads'):
            with self.subTest(value=value):
                status, ctx = self.main('--audit', str(self.tmp / 'absent.jsonl'), '--out', value)
                self.assertEqual(status, 2)
                self.assertIn('PROPOSAL_OUT_REFUSED', ctx.err.getvalue())

    @unittest.skipUnless(os.name == 'nt', 'a directory junction')
    def test_a_junction_is_seen_through_by_both_halves(self):
        """N-B: with a throwaway checkout, --out through a junction outside it pointing in is refused by the resolved
        half, and --out through a junction inside it pointing out by the given-path half (the review's N4, N5)."""
        import _winapi
        checkout, outside = self.tmp / 'checkout', self.tmp / 'outside'
        checkout.mkdir()
        outside.mkdir()
        into, out = self.tmp / 'into-checkout', checkout / 'out-of-checkout'
        for link, target in ((into, checkout), (out, outside)):
            _winapi.CreateJunction(str(target), str(link))
            self.addCleanup(os.rmdir, link)              # the junction only, never its target (runs first)
        with mock.patch.object(IQ.broker, 'REPO', checkout):
            self.assertEqual(IQ.proposal_target(str(outside / 'p.json')), (outside / 'p.json').resolve())
            for value in (into / 'p.json', out / 'p.json'):
                with self.subTest(value=value):
                    with self.assertRaises(IQ.QualificationError) as caught:
                        IQ.proposal_target(str(value))
                    self.assertEqual(caught.exception.code, 'PROPOSAL_OUT_REFUSED')
        self.assertEqual(sorted(p.name for p in outside.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'the Windows forms of a path')
    def test_every_windows_form_of_the_checkout_is_refused(self):
        """F1: --out in the checkout under another form Windows resolves to it (\\\\?\\, trailing spaces or dots,
        case, '/')."""
        repo = os.path.realpath(S.REPO)
        for value in ('\\\\?\\' + repo + '\\x-proposal.json', repo + ' \\x-proposal.json',
                      repo + '.\\x-proposal.json', repo + '. .\\x-proposal.json', '\\\\?\\' + repo.upper() + '\\x.json',
                      repo.replace('\\', '/') + '/integrations/x.json', '\\\\?\\' + repo + ' \\x-proposal.json'):
            with self.subTest(value=value):
                status, ctx = self.main('--audit', str(self.tmp / 'absent.jsonl'), '--out', value)
                self.assertEqual(status, 2)
                self.assertIn('PROPOSAL_OUT_REFUSED', ctx.err.getvalue())
        self.assertFalse((S.REPO / 'x-proposal.json').exists())


# ---------------------------------------------------------------- discovery, end to end


class Stdin:
    def __init__(self, data: bytes = b''):
        self._data, self.reads = io.BytesIO(data), 0

    def isatty(self):
        return False

    @property
    def buffer(self):
        self.reads += 1
        return self._data


def free_port() -> int:
    """A port that was free a moment ago: used only where nothing binds it (a refusal comes first), or through
    Discovery.discover, which retries when another socket took it in between (F7: no bind-close-rebind race)."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


PORT_TRIES = 5


class Discovery(unittest.TestCase):
    category = 'integration'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-discover-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / 'logs').mkdir()

    def context(self, upstream, stdin, wait=None):
        raw = {'control_port': 0, 'inference_port': 0, 'families': {
            'anthropic-messages': {'provider': PROVIDER_ID, 'upstream': upstream, 'models': [MAIN]}}}

        def refuse(*args):
            raise AssertionError('reached past a refusal')
        return IB.Context(component=lambda: raw, provider=refuse,
                          store=lambda: S.STORE.open_store(self.tmp / 'i.sqlite'), logs=lambda: self.tmp / 'logs',
                          stdin=stdin, out=io.StringIO(), err=io.StringIO(), wait=wait or refuse,
                          allow_ephemeral=True)

    def discover(self, make_context, out, provider=PROVIDER_ID):
        """(exit code, context, port) of a discover run on a fresh port; a run refused DISCOVERY_PORT_TAKEN (before
        the key is read) is retried on another port, at most PORT_TRIES times."""
        for _ in range(PORT_TRIES):
            port = free_port()
            ctx = make_context(port)
            code = IQ.main(['discover', '--provider', provider, '--out', str(out)], ctx)
            if 'DISCOVERY_PORT_TAKEN' not in ctx.err.getvalue():
                return code, ctx, port
        self.fail(f'no free port in {PORT_TRIES} tries')

    def test_the_discovery_run_proposes_the_routes_and_models_it_saw(self):
        seen = {}
        families = FAMILIES.read_bytes()

        def wait(broker):
            grant = IC.ControlClient(broker.listeners['control']['port']).issue(
                S.new_id(), S.new_id(), 'anthropic-messages', [MAIN], 60)
            seen['token'] = token = grant['token']
            inference = broker.listeners['inference']['port']
            key = [('x-api-key', token)]
            for method, target, body in (
                    ('POST', '/v1/messages', {'model': MAIN, 'messages': [{'role': 'user', 'content': S.PROMPT_MARKER}]}),
                    ('POST', '/v1/messages?beta=TRUE', {'model': MAIN, 'messages': [{'role': 'user', 'content': S.PROMPT_MARKER}]}),
                    ('POST', '/v1/messages', {'model': SECONDARY, 'messages': [{'role': 'user', 'content': S.PROMPT_MARKER}]}),
                    ('POST', '/v1/messages/count_tokens?beta=true', {'model': MAIN}),
                    ('GET', '/v1/models', None)):
                seen.setdefault('status', []).append(S.request(inference, method, target, body, key)[0])
            seen['status'].append(S.request(inference, 'GET', '/v1/models?limit=5')[0])
        out = self.tmp / 'proposal.json'
        code, ctx, port = self.discover(lambda p: self.context(f'http://127.0.0.1:{p}',
                                                               Stdin((SYNTHETIC + '\n').encode()), wait), out)
        self.assertEqual(code, 0, ctx.err.getvalue())
        self.assertEqual(seen['status'], [200, 400, 403, 404, 404, 401])
        proposal = json.loads(out.read_text(encoding='utf-8'))
        (family,) = proposal['families']
        self.assertEqual(family['proposed'], {'routes': [{'method': 'POST', 'path': '/v1/messages'},
                                                         {'method': 'POST', 'path': '/v1/messages/count_tokens'},
                                                         {'method': 'GET', 'path': '/v1/models'}],
                                              'models': [MAIN, SECONDARY]})
        self.assertEqual([(f['code'], f.get('route')) for f in proposal['flags']],
                         [('QUERY_OBSERVED', 'POST /v1/messages'),
                          ('QUERY_OBSERVED', 'POST /v1/messages/count_tokens'),
                          ('MODEL_NOT_TOP_LEVEL', 'GET /v1/models'), ('UNATTRIBUTED_REQUESTS', None)])
        self.assertEqual(proposal['unattributed'], [{'method': 'GET', 'path': '/v1/models', 'requests': 1,
                                                     'query_names': ['limit'], 'codes': {'TOKEN_MISSING': 1}}])
        self.assertFalse(proposal['complete'])          # F2: an unattributed request was seen
        fingerprint = IB.contract.fingerprint(SYNTHETIC)
        self.assertEqual(proposal['discovery'], {
            'provider': PROVIDER_ID, 'families': ['anthropic-messages'], 'provider_key_fingerprint': fingerprint,
            'upstream': {'anthropic-messages': {
                'requests': 1, 'routes': {'POST /v1/messages 200': 1}, 'credential_is_the_synthetic_key': True,
                'key_paths': {'POST /v1/messages': {'requests': 1, 'paths': ['messages', 'messages[].content', 'messages[].role', 'model'],
                                                    'truncated': False, 'names_unrecorded': 0,
                                                    'bodies': {'json': 1}}}}}})
        self.assertIn('only admitted requests reach', proposal['not_shown'][0])
        (audit,) = (self.tmp / 'logs').glob('audit-*.jsonl')
        self.assertEqual(proposal['source']['audit_file'], audit.name)
        self.assertEqual(proposal['source']['sha256'], hashlib.sha256(audit.read_bytes()).hexdigest())
        self.assertEqual(json.loads(ctx.out.getvalue())['grants']['live'], 1)     # serve's own report
        self.assertIn('inference-discovery: {', ctx.err.getvalue())
        everything = (ctx.out.getvalue() + ctx.err.getvalue() + out.read_text(encoding='utf-8')
                      + audit.read_text(encoding='utf-8'))
        for secret in (SYNTHETIC, seen['token'], S.PROMPT_MARKER):
            self.assertNotIn(secret, everything)
        self.assertEqual(FAMILIES.read_bytes(), families)
        with socket.socket() as again:                              # the fake upstream's port is free again
            again.bind(('127.0.0.1', port))

    def test_a_secondary_model_in_a_nested_field_is_flagged_by_its_path(self):
        hidden = 'syn-hidden-secondary-model'

        def wait(broker):
            grant = IC.ControlClient(broker.listeners['control']['port']).issue(
                S.new_id(), S.new_id(), 'anthropic-messages', [MAIN], 60)
            body = {'model': MAIN, 'messages': [{'role': 'user', 'content': S.PROMPT_MARKER}],
                    'metadata': {'fallback_model': hidden}}
            self.assertEqual(S.request(broker.listeners['inference']['port'], 'POST', '/v1/messages', body,
                                       [('x-api-key', grant['token'])])[0], 200)
        out = self.tmp / 'proposal.json'
        code, ctx, _ = self.discover(lambda p: self.context(f'http://127.0.0.1:{p}', Stdin(SYNTHETIC.encode()), wait),
                                     out)
        self.assertEqual(code, 0, ctx.err.getvalue())
        text = out.read_text(encoding='utf-8')
        proposal = json.loads(text)
        self.assertEqual([(f['code'], f.get('paths')) for f in proposal['flags']],
                         [('MODEL_KEY_ELSEWHERE', ['metadata.fallback_model'])])
        self.assertEqual(proposal['families'][0]['proposed']['models'], [MAIN])
        self.assertTrue(proposal['complete'])           # MODEL_KEY_ELSEWHERE is a suitability flag only
        self.assertEqual(proposal['discovery']['upstream']['anthropic-messages']['key_paths']['POST /v1/messages']
                         ['paths'], ['messages', 'messages[].content', 'messages[].role', 'metadata',
                                     'metadata.fallback_model', 'model'])
        for value in (hidden, S.PROMPT_MARKER, SYNTHETIC):
            self.assertNotIn(value, text + ctx.out.getvalue() + ctx.err.getvalue())

    def test_a_write_failure_after_the_run_is_a_coded_failure(self):
        """F6: the run happened; the proposal could not be written: exit 1, PROPOSAL_WRITE_FAILED, no traceback."""
        def wait(broker):
            pass
        out = self.tmp / 'proposal.json'
        with mock.patch.object(IQ, 'open', side_effect=OSError('disk full'), create=True):
            code, ctx, _ = self.discover(lambda p: self.context(f'http://127.0.0.1:{p}', Stdin(SYNTHETIC.encode()),
                                                                wait), out)
        self.assertEqual(code, 1)
        self.assertIn('FAILED after the run: PROPOSAL_WRITE_FAILED', ctx.err.getvalue())
        self.assertNotIn('Traceback', ctx.err.getvalue())
        self.assertFalse(out.exists())

    def test_the_fake_upstream_command_records_no_key_paths(self):
        family = IB.load_declarations()['anthropic-messages']
        sink = io.StringIO()
        fake = IQ.FakeUpstream(family, '127.0.0.1', 0, sink)
        fake.start()
        try:
            S.request(fake.port, 'POST', '/v1/messages', {'model': MAIN, 'metadata': {'fallback_model': MAIN}})
        finally:
            fake.stop()
        (record,) = [json.loads(r) for r in sink.getvalue().splitlines() if '"request"' in r]
        self.assertEqual(sorted(record), ['credential_fingerprints', 'event', 'family', 'format', 'header_names',
                                          'method', 'path', 'status'])

    def test_refusals_come_before_the_key_is_read(self):
        out = self.tmp / 'proposal.json'
        existing = self.tmp / 'exists.json'
        existing.write_text('{}', encoding='utf-8')
        holder = socket.socket()
        self.addCleanup(holder.close)
        holder.bind(('127.0.0.1', 0))                   # held: its port is taken for the whole test
        holder.listen()
        port = holder.getsockname()[1]
        for upstream, target, code in (
                (f'http://127.0.0.1:{free_port()}', existing, 'PROPOSAL_OUT_REFUSED'),
                (f'http://127.0.0.1:{port}', out, 'DISCOVERY_PORT_TAKEN'),
                (f'http://[::1]:{free_port()}', out, 'FAKE_ADDRESS_REFUSED'),
                ('https://api.example.invalid', out, 'QUALIFICATION_UPSTREAM_REFUSED')):
            with self.subTest(code=code):
                stdin = Stdin(SYNTHETIC.encode())
                ctx = self.context(upstream, stdin)
                self.assertEqual(IQ.main(['discover', '--provider', PROVIDER_ID, '--out', str(target)], ctx), 2)
                self.assertIn(code, ctx.err.getvalue())
                self.assertEqual((stdin.reads, ctx.out.getvalue()), (0, ''))
        stdin = Stdin(SYNTHETIC.encode())
        ctx = self.context(f'http://127.0.0.1:{port}', stdin)
        self.assertEqual(IQ.main(['discover', '--provider', 'Not An Id', '--out', str(out)], ctx), 2)
        self.assertIn('PROVIDER_ID_INVALID', ctx.err.getvalue())
        # a key refused after the fake upstream was bound: nothing proposed, the port freed
        code, ctx, free = self.discover(lambda p: self.context(f'http://127.0.0.1:{p}',
                                                               Stdin(b'not-a-synthetic-key-0123456789')), out)
        self.assertEqual(code, 2)
        self.assertIn('KEY_NOT_SYNTHETIC', ctx.err.getvalue())
        self.assertFalse(out.exists())
        self.assertEqual(list((self.tmp / 'logs').iterdir()), [])
        with socket.socket() as again:
            again.bind(('127.0.0.1', free))


if __name__ == '__main__':
    unittest.main()
