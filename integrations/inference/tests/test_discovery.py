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
                         ('aieh-inference-family-pin-proposal/1', 'proposed', False, True))
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
        self.assertEqual(family['declared'], {'status': 'provisional', 'query': 'refuse',
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
                'metadata': {'fallback_model': self.HIDDEN, 'a.b': 1, 'aieh-inf-k': 2, '': 3}, 'tools': []}
        result = IQ.body_key_paths(json.dumps(body).encode())
        self.assertEqual(result, {'body': 'json', 'key_paths_truncated': False, 'key_names_unrecorded': 3,
                                  'key_paths': sorted(['model', 'max_tokens', 'messages', 'messages[].role',
                                                       'messages[].content', 'messages[].content[].type',
                                                       'messages[].content[].text', 'metadata',
                                                       'metadata.fallback_model', 'metadata.<unrecorded>',
                                                       'tools'])})
        text = json.dumps(result)
        for value in (MAIN, self.HIDDEN, 'hello', 'a.b', 'aieh-inf-k'):
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
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


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

    def test_the_discovery_run_proposes_the_routes_and_models_it_saw(self):
        port, seen = free_port(), {}
        families = FAMILIES.read_bytes()

        def wait(broker):
            grant = IC.ControlClient(broker.listeners['control']['port']).issue(
                S.new_id(), S.new_id(), 'anthropic-messages', [MAIN], 10, 1000, 60)
            seen['token'] = token = grant['token']
            inference = broker.listeners['inference']['port']
            key = [('x-api-key', token)]
            for method, target, body in (
                    ('POST', '/v1/messages', {'model': MAIN, 'messages': [S.PROMPT_MARKER]}),
                    ('POST', '/v1/messages?beta=true', {'model': MAIN, 'messages': [S.PROMPT_MARKER]}),
                    ('POST', '/v1/messages', {'model': SECONDARY, 'messages': [S.PROMPT_MARKER]}),
                    ('POST', '/v1/messages/count_tokens?beta=true', {'model': MAIN}),
                    ('GET', '/v1/models', None)):
                seen.setdefault('status', []).append(S.request(inference, method, target, body, key)[0])
            seen['status'].append(S.request(inference, 'GET', '/v1/models?limit=5')[0])
        stdin = Stdin((SYNTHETIC + '\n').encode())
        ctx = self.context(f'http://127.0.0.1:{port}', stdin, wait)
        out = self.tmp / 'proposal.json'
        self.assertEqual(IQ.main(['discover', '--provider', PROVIDER_ID, '--out', str(out)], ctx), 0,
                         ctx.err.getvalue())
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
        self.assertTrue(proposal['complete'])
        fingerprint = IB.contract.fingerprint(SYNTHETIC)
        self.assertEqual(proposal['discovery'], {
            'provider': PROVIDER_ID, 'families': ['anthropic-messages'], 'provider_key_fingerprint': fingerprint,
            'upstream': {'anthropic-messages': {
                'requests': 1, 'routes': {'POST /v1/messages 200': 1}, 'credential_is_the_synthetic_key': True,
                'key_paths': {'POST /v1/messages': {'requests': 1, 'paths': ['messages', 'model'],
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
        port, hidden = free_port(), 'syn-hidden-secondary-model'

        def wait(broker):
            grant = IC.ControlClient(broker.listeners['control']['port']).issue(
                S.new_id(), S.new_id(), 'anthropic-messages', [MAIN], 10, 1000, 60)
            body = {'model': MAIN, 'messages': [{'role': 'user', 'content': S.PROMPT_MARKER}],
                    'metadata': {'fallback_model': hidden}}
            self.assertEqual(S.request(broker.listeners['inference']['port'], 'POST', '/v1/messages', body,
                                       [('x-api-key', grant['token'])])[0], 200)
        ctx = self.context(f'http://127.0.0.1:{port}', Stdin(SYNTHETIC.encode()), wait)
        out = self.tmp / 'proposal.json'
        self.assertEqual(IQ.main(['discover', '--provider', PROVIDER_ID, '--out', str(out)], ctx), 0,
                         ctx.err.getvalue())
        text = out.read_text(encoding='utf-8')
        proposal = json.loads(text)
        self.assertEqual([(f['code'], f.get('paths')) for f in proposal['flags']],
                         [('MODEL_KEY_ELSEWHERE', ['metadata.fallback_model'])])
        self.assertEqual(proposal['families'][0]['proposed']['models'], [MAIN])
        self.assertEqual(proposal['discovery']['upstream']['anthropic-messages']['key_paths']['POST /v1/messages']
                         ['paths'], ['messages', 'messages[].content', 'messages[].role', 'metadata',
                                     'metadata.fallback_model', 'model'])
        for value in (hidden, S.PROMPT_MARKER, SYNTHETIC):
            self.assertNotIn(value, text + ctx.out.getvalue() + ctx.err.getvalue())

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
        port = free_port()
        holder = socket.socket()
        self.addCleanup(holder.close)
        holder.bind(('127.0.0.1', port))
        holder.listen()
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
        free = free_port()
        stdin = Stdin(b'not-a-synthetic-key-0123456789')
        ctx = self.context(f'http://127.0.0.1:{free}', stdin)
        self.assertEqual(IQ.main(['discover', '--provider', PROVIDER_ID, '--out', str(out)], ctx), 2)
        self.assertIn('KEY_NOT_SYNTHETIC', ctx.err.getvalue())
        self.assertFalse(out.exists())
        self.assertEqual(list((self.tmp / 'logs').iterdir()), [])
        with socket.socket() as again:
            again.bind(('127.0.0.1', free))


if __name__ == '__main__':
    unittest.main()
