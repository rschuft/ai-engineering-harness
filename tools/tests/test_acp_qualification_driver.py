"""Tests for the prepared ACP qualification driver of plan leaf S-03.3, slice 5 (tools/guest.py acp-qualification;
NOT RUN live).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

stdlib unittest; no QEMU, no guest, no ssh, no broker, no network, no provider key. The guest is replaced by fakes:
the dispatcher's sealed API channel (the outer server, the inner server's conversations through the bash route, the
event stream, the containment collector's and the job environment probe's output), the root facts, the broker's
control listener, the forward session, inspect's P5 record and the guest-root vantage. The containment snapshots
are slice 1's own synthetic trees (integrations/dispatch/tests/test_conversation_containment.py). Shown: the
decision rule's PASS, FAIL and UNKNOWN (a lost answer is never PASS); a negative control for each stop condition;
the key search modes (off by default; the real key read only under its act and only inside its step); the record
never holds the attempt token or the key. D-6, the job contract's admission of the attempt token's name, is tested
in test_attempt_token_contract.py.
"""
from pathlib import Path
import base64
import builtins
import contextlib
import http.server
import io
import json
import re
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')
tg = module_code.load('test_guest_fixtures', REPO / 'tools' / 'tests' / 'test_guest.py')
tcc = module_code.load('test_conversation_containment_fixtures',
                       REPO / 'integrations' / 'dispatch' / 'tests' / 'test_conversation_containment.py')
d6 = module_code.load('test_attempt_token_contract_fixtures',
                      REPO / 'tools' / 'tests' / 'test_attempt_token_contract.py')
job_env, TOKEN_SHAPED = d6.job_env, d6.TOKEN_SHAPED
CC = guest.containment()
PROFILE = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
CID = guest.ACP_QUALIFICATION_CONVERSATION_ID
HEX = CID.replace('-', '')
TOKEN = 'aieh-inf-' + 'T' * 43
TOKEN_FP = guest.inference_control().token_fingerprint(TOKEN)
SYNTHETIC = 'aieh-qualification-synthetic-' + 'S' * 32
SYNTHETIC_FP = guest.key_search().fingerprint(SYNTHETIC)
REAL = 'sk-ant-api03-' + 'R' * 40
REAL_FP = guest.key_search().fingerprint(REAL)
MODEL = 'model-main'
FAMILY = guest.ACP_QUALIFICATION_FAMILY
RECORD = {'provisioning': {'image_id': tg.IMAGE_ID}, 'ports': {'ssh': 40022, 'qmp': 40023},
          'inference': {'composition': 'inference'}}
SERVER_USER = {'name': 'openhands', 'uid': 999, 'gid': 989}
CHILD = 'c0000000-0000-4000-8000-0000000000c1'
OTHER = 'b0000000-0000-4000-8000-0000000000b1'
TO_ENDPOINT = tcc.tcp_row('020011AC:C350', '010011AC:1F9A', '01', 6001)
TO_ELSEWHERE = tcc.tcp_row('020011AC:C351', '01010101:01BB', '01', 6003)


def snapshot(processes=None, rows=()):
    fs = tcc.container_fs(processes)
    fs.files['/proc/net/tcp'] = (tcc.TCP + ''.join(rows)).encode()
    return tcc.container_snapshot(fs)


def host_snapshot(processes=None):
    return tcc.host_snapshot(tcc.host_fs(processes))


class FakeGuest:
    """The outer server, the conversation's inner server and its container, as the sealed API channel and the root
    facts see them. Each attribute is one fact a negative control changes."""

    def __init__(self, test):
        self.test = test
        self.created = False
        self.calls = []
        self.bodies = {}
        self.statuses = ['running', 'finished']
        self.during = snapshot(rows=[TO_ENDPOINT])
        self.after = snapshot(rows=[TO_ENDPOINT])
        self.env = job_env(TOKEN_SHAPED)
        self.env_specs = []
        self.events = [[{'id': 'e1', 'kind': 'MessageEvent', 'source': 'user'},
                        {'id': 'e2', 'kind': guest.ACP_TOOL_CALL_KIND, 'title': 'Task'}],
                       [{'id': 'e3', 'kind': 'MessageEvent', 'source': 'agent'}]]
        self.inner_before = [{'id': CID, 'parent_conversation_id': None}]
        self.inner_after = [{'id': CID, 'parent_conversation_id': None}]
        self.outer_extra = []          # outer conversations that appear after the prompt
        self.create_status = 201
        self.create_agent = {'kind': 'ACPAgent', 'acp_server': 'claude-code', 'acp_model': MODEL}
        self.echo_token = False
        self.lose = set()              # paths whose answer is lost
        self.answers = {}              # path: (status, body) answered instead
        self.malformed = set()         # paths answered without a single response
        self.sent = False
        self.rejects = 3
        self.count = None              # the outer count answered instead of the real one
        self.phantom = False           # a container the outer server does not count
        self.extra_when_sent = False   # a second container for the conversation once the prompt is sent
        self.extra_after_create = False
        self.image = None              # another image for the container
        self.keep_container = False    # the container stays after the delete
        self.collector_noise = ''      # a line the collector prints before its result
        self.bash = None               # (status, body) of the bash route instead of the script's output
        self.host_section = None       # the root reporter's containment section (None: a reporter before slice 6)
        self.facts_calls = 0

    def facts(self):
        container = tg.conversation_container(hex_id=HEX)
        container['State']['Pid'] = tcc.HOST_BASE + 1
        if self.image:
            container['Image'] = self.image
        deleted = ('DELETE', f'/api/conversations/{CID}') in self.calls
        containers = [container] if self.created or (self.keep_container and deleted) or self.phantom else []
        if (self.extra_when_sent and self.sent) or (self.extra_after_create and self.created):
            containers.append(tg.conversation_container(cid='f' * 64, hex_id=HEX))
        self.facts_calls += 1
        out = {'containers': containers, 'server_user': dict(SERVER_USER),
               'admission': {'iptables': [{'target': 'REJECT', 'packets': self.rejects}]}}
        if self.host_section is not None:
            out[guest.ACP_HOST_SECTION] = self.host_section() if callable(self.host_section) else self.host_section
        return out

    def answer(self, method, path, body):
        self.calls.append((method, path))
        self.bodies[(method, path)] = body
        if path in self.lose:
            raise OSError('connection lost')
        if path in self.answers:
            return self.answers[path]
        base = f'/api/conversations/{CID}'
        if method == 'GET' and path == '/api/conversations/count':
            return 200, (0 if not self.created else 1) if self.count is None else self.count
        if method == 'POST' and path == '/api/conversations':
            self.test.assertEqual(body['agent_settings']['acp_command'], ['claude-agent-acp'])
            self.test.assertEqual(body['secrets']['ANTHROPIC_API_KEY']['value'], TOKEN)
            self.created = 200 <= self.create_status < 300
            out = {'id': CID, 'agent': self.create_agent}
            if self.echo_token:
                out['secrets'] = {'ANTHROPIC_API_KEY': TOKEN}
            return self.create_status, out
        if method == 'GET' and path == '/api/conversations/search?limit=100':
            ids = ([CID] if self.created else []) + (self.outer_extra if self.sent else [])
            return 200, {'items': [{'id': i} for i in ids], 'next_page_id': None}
        if method == 'POST' and path == base + '/events':
            self.test.assertIn(body['content'][0]['text'], guest.ACP_QUALIFICATION_PROMPTS.values())
            self.test.assertEqual((body['role'], body['content'][0]['type'], body['run']), ('user', 'text', True))
            self.sent = True
            return 200, {'success': True}
        if method == 'GET' and path == base:
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return 200, {'id': CID, 'execution_status': status, 'agent': self.create_agent}
        if method == 'GET' and path.startswith(base + '/events/search?limit=100'):
            index = int(path.split('page_id=p')[1]) if 'page_id=' in path else 0
            nxt = f'p{index + 1}' if index + 1 < len(self.events) else None
            return 200, {'items': self.events[index], 'next_page_id': nxt}
        if method == 'GET' and path == base + '/agent_final_response':
            return 200, {'response': 'ready'}
        if method == 'POST' and path == base + '/bash/execute_bash_command':
            if self.bash is not None:
                return self.bash
            return 200, {'exit_code': 0, 'stdout': self.run_script(body['command'])}
        if method == 'DELETE' and path == base:
            self.created = False
            return 200, {'success': True}
        raise AssertionError(f'unexpected request {method} {path}')

    def run_script(self, command):
        match = re.match(r'echo ([A-Za-z0-9+/=]+) \| base64 -d > /tmp/aieh-job.py && python3 /tmp/aieh-job.py ([^\s;]+)',
                         command)
        script = base64.b64decode(match.group(1)).decode('utf-8')
        if script.startswith('"""The containment observation'):
            snap = self.after if self.test.turn_done else self.during
            return 'noise\n' + self.collector_noise + CC.MARKER + json.dumps(snap) + '\n'
        if script == guest.ACP_INNER_CONVERSATIONS:
            self.test.assertEqual(match.group(2), str(CC.INNER_PORT))
            rows = self.inner_after if self.test.turn_done else self.inner_before
            return guest.JOB_MARKER + json.dumps({'key_present': True, 'status': 200, 'pages': 1,
                                                  'key_occurrences': 0, 'items': rows}) + '\n'
        if script == guest.JOB_ENV_PROBE:
            self.env_specs.append(json.loads(base64.b64decode(match.group(2))))
            return guest.JOB_MARKER + json.dumps(self.env) + '\n'
        raise AssertionError('an unexpected script')

    def api(self, requests, timeout=900, secret=None):
        self.test.assertEqual(secret, TOKEN)            # every call is sealed with the token
        (request,) = requests
        status, body = self.answer(request['method'], request['path'], request.get('json'))
        if request['path'] in self.malformed:
            return {'responses': [], 'session_key_occurrences': 0}
        text = json.dumps(body)
        sealed = text.count(secret)
        body = json.loads(text.replace(secret, '<sealed secret redacted>'))
        return {'responses': [{'status': status, 'body': body}], 'session_key_occurrences': 0,
                'sealed_occurrences': sealed}

class FakeBroker:
    def __init__(self, source=guest.ACP_SYNTHETIC_SOURCE, fingerprint=SYNTHETIC_FP):
        self.grant = {'state': 'live', 'family': FAMILY, 'models': [MODEL, 'model-small'], 'conversation_id': CID,
                      'attempt_id': 'a' * 8, 'budget': {'requests': 20, 'tokens': 20000}, 'requests': 2,
                      'refused': 0, 'usage': {'input': 10}}
        self.family = {'id': FAMILY, 'status': 'provisional', 'ready': True, 'upstream': 'http://127.0.0.1:9',
                       'models': [MODEL, 'model-small']}
        self.key = {'fingerprint': fingerprint, 'source': source, 'provider': 'anthropic'}
        self.calls = []

    def call(self, method, *args):
        self.calls.append((method,) + args)
        if method == 'status':
            return {'families': [self.family], 'provider_key': self.key}
        if method == 'grant':
            assert args == (TOKEN_FP,)
            return dict(self.grant)
        if method == 'revoke':
            self.grant['state'] = 'revoked'
            self.grant['revocation'] = {'trigger': args[1], 'revoker': args[2]}
            return dict(self.grant)
        raise AssertionError(method)


def inspect_record(verdict='PASS'):
    return {'properties': [{'property': 'profiles P5', 'checks': [
        {'check': guest.INFERENCE_KEY_SEARCH_CHECK, 'observed': {'verdict': 'not-found'}, 'verdict': verdict}]}]}


class DriverRun(unittest.TestCase):
    """acp_qualification_run against the fakes."""

    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix='aieh-acpq-'))
        self.addCleanup(tg.remove_tree, self.state)
        self.guest = FakeGuest(self)
        self.broker = FakeBroker()
        self.turn_done = False
        self.inspected = []
        self.real_reads = []

    def wait(self, fetch, done, ceiling):
        value = fetch()
        for _ in range(20):              # twenty more reads stand for the ceiling
            if done(value):
                break
            value = fetch()
        self.turn_done = done(value)
        return value, done(value)

    def run_driver(self, key_mode='synthetic', host=True, inspected='PASS', profile=PROFILE, record=RECORD,
                   real_key_act=None, real_reader=None, **kw):
        written = {}
        ctx = types.SimpleNamespace(profile=profile, repo=REPO, instance_dir=lambda n: self.state / n)

        def inspect_fn(fp, key):
            self.inspected.append((fp, key))
            return inspect_record(inspected)

        def reader(fp):
            self.real_reads.append(fp)
            return REAL

        args = dict(key_mode=key_mode, channels=lambda rec: (self.guest.api, self.guest.facts),
                    broker=self.broker, forward=types.SimpleNamespace(status=lambda: {'held': True}),
                    inspect_fn=inspect_fn, wait=self.wait, real_key_act=real_key_act,
                    real_key_reader=real_reader or reader,
                    host_vantage=(lambda rec, pid: host_snapshot()) if host is True else host)
        if key_mode == 'synthetic':
            args.update(provider_key=SYNTHETIC, provider_key_fingerprint=SYNTHETIC_FP)
        args.update(kw)
        with mock.patch.object(guest, 'running_instance', side_effect=lambda c, n: (None, record)), \
                mock.patch.object(guest, 'write_record', side_effect=lambda i, op, out: written.update({op: out})), \
                mock.patch.object(guest, 'log'):
            out = guest.acp_qualification_run(ctx, 'g1', TOKEN, 'single', MODEL, **args)
        self.assertEqual(written['acp-qualification']['result'], out['result'])
        text = json.dumps(written, default=str)
        for secret in (TOKEN, SYNTHETIC, REAL, TOKEN[len('aieh-inf-'):]):
            self.assertNotIn(secret, text)
        self.assertIn(TOKEN_FP, text)
        return out

    @staticmethod
    def verdicts(out):
        return [s['verdict'] for s in out['steps']]

    def step(self, out, number):
        found = [s for s in out['steps'] if s['step'].startswith(f'({number})')]
        self.assertEqual(len(found), 1, number)
        return found[0]

    def stops(self, out):
        return [s['stop'] for s in out['stop_conditions']]

    def test_the_rule_passes_on_a_guest_that_holds_it(self):
        out = self.run_driver()
        self.assertEqual(out['result'], 'PASS', [(s['step'], s['verdict'], s.get('detail')) for s in out['steps']])
        self.assertEqual(self.verdicts(out), ['PASS'] * 13)
        self.assertEqual(out['rule'], guest.ACP_QUALIFICATION_RULE)
        self.assertEqual((out['schema'], out['operation'], out['plan_leaf']),
                         (guest.ACP_QUALIFICATION_SCHEMA, 'acp-qualification', 'S-03.3'))
        self.assertEqual(out['stop_conditions'], [])
        self.assertEqual(out['attempt_token'], {'fingerprint': TOKEN_FP, 'redacted_from_record': 0})
        # the create went through the dispatcher's transport, admitted: only its body's sha256 is recorded
        create = [c for c in out['transport_calls'] if c['method'] == 'POST' and c['path'] == '/api/conversations']
        self.assertEqual(len(create), 1)
        self.assertRegex(create[0]['body_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(self.step(out, 2)['detail']['admission'], 'admitted (acp_qualification.check_create)')
        # the order of the live acts: nothing but these calls, the turn between the prompt and the teardown
        paths = [p for _, p in self.guest.calls]
        self.assertLess(paths.index('/api/conversations'), paths.index(f'/api/conversations/{CID}/events'))
        self.assertEqual(self.guest.calls[-2:], [('DELETE', f'/api/conversations/{CID}'),
                                                 ('GET', '/api/conversations/count')])
        self.assertFalse(any(p.endswith(guest.ACP_FORK_PATHS) for p in paths))
        # the token revoked at attempt end, by the driver, after the search
        self.assertEqual(self.broker.calls[-2:], [('grant', TOKEN_FP),
                                                  ('revoke', TOKEN_FP, 'attempt end', guest.ACP_REVOKER)])
        self.assertEqual(self.step(out, 12)['detail']['state'], 'revoked')
        # the mechanisms are distinguished
        mech = self.step(out, 9)['detail']['mechanisms']
        self.assertEqual(mech["(a) the provider's own tools and sub-agents"]['acp_tool_call_events'], 1)
        self.assertEqual(mech["(a) the provider's own tools and sub-agents"]['tool_call_titles'], ['Task'])
        self.assertTrue(mech["(a) the provider's own tools and sub-agents"]['observed'])
        self.assertEqual(mech["(b) an ACP session fork (ask_agent)"]['driver_called'], [])
        self.assertEqual(mech["(c) the inner server's children route"], {'children': [], 'observed': False})
        self.assertFalse(mech["(d) OpenHands' start_child_conversation tool"]['observed'])
        self.assertEqual(self.step(out, 9)['detail']['events'], 3)
        self.assertEqual(self.step(out, 9)['detail']['pages'], 2)
        # D-6: the token's name admitted in the adapter's environment, by shape
        self.assertEqual(self.step(out, 6)['detail']['admission']['admitted'], {'20': ['ANTHROPIC_API_KEY']})
        # the synthetic key: inspect's P5 search and this run's answers in memory
        self.assertEqual(self.inspected, [(SYNTHETIC_FP, SYNTHETIC)])
        self.assertEqual(self.step(out, 11)['detail']['this_run_in_memory']['verdict'], 'not-found')
        self.assertEqual(self.real_reads, [])
        # the network view classified the endpoint connection
        kinds = [c['kind'] for c in self.step(out, 5)['detail']['network']['connections']]
        self.assertIn('the inference endpoint', kinds)

    def test_children_route_is_classified_not_failed(self):
        self.guest.inner_after = self.guest.inner_after + [{'id': CHILD, 'parent_conversation_id': CID}]
        out = self.run_driver()
        self.assertEqual(out['result'], 'PASS')
        mech = self.step(out, 9)['detail']['mechanisms']["(c) the inner server's children route"]
        self.assertEqual(mech, {'children': [CHILD.replace('-', '')], 'observed': True})

    def test_with_an_older_reporter_and_the_search_off_the_run_is_unknown(self):
        # the default vantage on a guest whose root reporter predates slice 6 (no containment section)
        out = self.run_driver(key_mode='off', host=None)
        self.assertEqual(out['result'], 'UNKNOWN')
        self.assertEqual((self.step(out, 5)['verdict'], self.step(out, 8)['verdict'], self.step(out, 11)['verdict']),
                         ('UNKNOWN', 'UNKNOWN', 'UNKNOWN'))
        self.assertIn("no 'containment' section", self.step(out, 5)['detail']['host_vantage'])
        self.assertIsNone(self.step(out, 5)['detail']['host'])
        self.assertEqual(self.step(out, 11)['detail']['mode'], 'off')
        self.assertEqual(self.inspected, [])
        self.assertEqual(self.real_reads, [])
        self.assertEqual(self.step(out, 12)['verdict'], 'PASS')

    def test_the_real_key_is_read_only_inside_its_step_under_its_act(self):
        broker = FakeBroker(source='windows-credential-manager', fingerprint=REAL_FP)
        self.broker = broker
        out = self.run_driver(key_mode='real', real_key_act='OA-12 A1 and D-5')
        self.assertEqual(out['result'], 'PASS', [(s['step'], s['verdict']) for s in out['steps']])
        self.assertEqual(self.real_reads, [REAL_FP])
        self.assertEqual(self.inspected, [(REAL_FP, REAL)])
        self.assertEqual(self.step(out, 11)['detail']['real_key_act'], 'OA-12 A1 and D-5')
        # a run that never got ready reads no key
        self.setUp()
        self.broker = FakeBroker(source='windows-credential-manager', fingerprint=REAL_FP)
        self.broker.grant['conversation_id'] = OTHER
        out = self.run_driver(key_mode='real', real_key_act='OA-12 A1')
        self.assertEqual((out['result'], self.real_reads), ('FAIL', []))
        self.assertEqual(self.step(out, 11)['skipped'], 'not reached (ready)')
        self.assertEqual(self.step(out, 12)['verdict'], 'PASS')     # revoked all the same

    def test_a_real_key_found_is_a_stop(self):
        for leak in ('leak ' + REAL, base64.b64encode(REAL.encode()).decode()):
            with self.subTest(leak=leak[:8]):
                self.setUp()
                self.broker = FakeBroker(source='windows-credential-manager', fingerprint=REAL_FP)
                self.guest.events[1].append({'id': 'e9', 'kind': 'MessageEvent', 'text': leak})
                out = self.run_driver(key_mode='real', real_key_act='OA-12 A1')
                self.assertEqual((self.step(out, 11)['verdict'], out['result']), ('FAIL', 'FAIL'))
                self.assertIn('a credential found in a recorded surface (the provider key)', self.stops(out))
                self.assertEqual(self.step(out, 11)['detail']['this_run_in_memory']['verdict'], 'found')

    def test_a_record_that_would_hold_the_key_is_not_written(self):
        self.broker = FakeBroker(source='windows-credential-manager', fingerprint=REAL_FP)
        self.guest.events[1].append({'id': 'e9', 'kind': guest.ACP_TOOL_CALL_KIND, 'title': REAL})
        written = {}
        with mock.patch.object(guest, 'running_instance', side_effect=lambda c, n: (None, RECORD)), \
                mock.patch.object(guest, 'write_record', side_effect=lambda i, op, out: written.update({op: out})), \
                mock.patch.object(guest, 'log'), self.assertRaisesRegex(guest.Refused, 'would hold the provider key'):
            guest.acp_qualification_run(
                types.SimpleNamespace(profile=PROFILE, repo=REPO, instance_dir=lambda n: self.state / n), 'g1',
                TOKEN, 'single', MODEL, key_mode='real', real_key_act='A1',
                channels=lambda rec: (self.guest.api, self.guest.facts), broker=self.broker,
                forward=types.SimpleNamespace(status=lambda: {'held': True}),
                inspect_fn=lambda fp, key: inspect_record(), wait=self.wait, real_key_reader=lambda fp: REAL,
                host_vantage=lambda rec, pid: host_snapshot())
        self.assertEqual(written, {})

    def test_stop_a_process_outside_the_lineage(self):
        entered = {**tcc.CONTAINER, 40: (0, '/usr/bin/bash', ['bash'])}
        orphan = {**tcc.CONTAINER, 41: (1, '/usr/bin/sleep', ['sleep'])}
        for name, processes in (('entered', entered), ('orphan', orphan)):
            with self.subTest(name):
                self.setUp()
                self.guest.during = snapshot(processes, rows=[TO_ENDPOINT])
                out = self.run_driver()
                self.assertEqual(out['result'], 'FAIL')
                self.assertTrue(any('outside the container\'s lineage' in s for s in self.stops(out)),
                                self.stops(out))
                self.assertEqual(self.step(out, 5)['verdict'], 'FAIL')
                # the later steps are skipped; the search, the revocation and the teardown still run
                self.assertEqual(self.step(out, 7).get('skipped'), 'a stop condition')
                self.assertEqual([self.step(out, n)['verdict'] for n in (11, 12, 13)], ['PASS'] * 3)
        self.setUp()
        out = self.run_driver(host=lambda rec, pid: dict(host_snapshot(), outside_children=[
            {'pid': 9999, 'ppid': tcc.HOST_BASE + 8, 'exe': '/x', 'argv0': 'x', 'script': None}]))
        self.assertIn("a process outside the container's lineage (an escaped child)", self.stops(out))

    def test_stop_an_unexpected_outer_conversation(self):
        self.guest.outer_extra = [OTHER]
        out = self.run_driver()
        self.assertEqual(out['result'], 'FAIL')
        self.assertIn('an outer-server conversation that was not expected', self.stops(out))
        self.assertEqual(self.step(out, 8)['verdict'], 'FAIL')
        # at create: the outer server lists more than the qualification conversation
        self.setUp()
        self.guest.sent = True
        self.guest.outer_extra = [OTHER]
        out = self.run_driver()
        self.assertEqual(self.step(out, 2)['verdict'], 'FAIL')
        self.assertIn('an outer-server conversation that was not expected', self.stops(out))

    def test_stop_npx_or_npm(self):
        for argv in (['npx', '-y', 'x'], ['node', '/usr/lib/node_modules/npm/bin/npm-cli.js']):
            with self.subTest(argv=argv):
                self.setUp()
                self.guest.during = snapshot({**tcc.CONTAINER, 23: (20, '/usr/bin/node', argv)},
                                             rows=[TO_ENDPOINT])
                out = self.run_driver()
                self.assertIn('an npx or npm process', self.stops(out))
                self.assertEqual(out['result'], 'FAIL')

    def test_stop_a_credential_in_a_recorded_surface(self):
        # the attempt token echoed by the Agent Server
        self.guest.echo_token = True
        out = self.run_driver()
        self.assertEqual(out['result'], 'FAIL')
        self.assertTrue(any('the attempt token echoed' in s for s in self.stops(out)))
        self.assertEqual(out['token_echoes'][0]['occurrences'], 1)
        # a provider-key shaped value in a process environment
        self.setUp()
        self.guest.env = job_env({'ANTHROPIC_API_KEY': {'token': False, 'provider_key': True}})
        out = self.run_driver()
        self.assertTrue(any('provider-key shaped value' in s for s in self.stops(out)))
        self.assertEqual(self.step(out, 6)['verdict'], 'FAIL')
        # the synthetic key found by inspect's P5 search, or in this run's answers
        self.setUp()
        out = self.run_driver(inspected='FAIL')
        self.assertIn('a credential found in a recorded surface (the provider key)', self.stops(out))
        self.assertEqual(self.step(out, 11)['verdict'], 'FAIL')
        self.setUp()
        self.guest.events[0].append({'id': 'e8', 'kind': 'MessageEvent', 'text': SYNTHETIC.encode().hex()})
        out = self.run_driver()
        self.assertEqual(self.step(out, 11)['detail']['this_run_in_memory']['verdict'], 'found')
        self.assertEqual(out['result'], 'FAIL')
        # the management key in an answer
        self.setUp()
        original = self.guest.api

        def leaky(requests, timeout=900, secret=None):
            data = original(requests, timeout, secret)
            if requests[0]['path'].endswith('/agent_final_response'):
                data['session_key_occurrences'] = 1
            return data
        self.guest.api = leaky
        out = self.run_driver()
        self.assertTrue(any('the management key' in s for s in self.stops(out)))
        self.assertEqual(self.step(out, 9)['verdict'], 'UNKNOWN')

    def test_stop_another_network_destination(self):
        self.guest.after = snapshot(rows=[TO_ENDPOINT, TO_ELSEWHERE])
        out = self.run_driver()
        self.assertEqual(out['result'], 'FAIL')
        self.assertIn("a connection reached a destination other than the broker's inference endpoint",
                      self.stops(out))
        self.assertEqual(self.step(out, 8)['verdict'], 'FAIL')
        # an attempt that never connected is recorded, not a stop
        self.setUp()
        self.guest.during = snapshot(rows=[tcc.tcp_row('020011AC:C351', '01010101:01BB', '02', 6003)])
        out = self.run_driver()
        self.assertEqual(out['result'], 'PASS')
        self.assertEqual(len(self.step(out, 5)['detail']['network']['attempted']), 1)

    def test_fail_outcomes(self):
        cases = {
            'the turn ends in error': (lambda: setattr(self.guest, 'statuses', ['running', 'error']), 7),
            'the create is refused by the server': (lambda: setattr(self.guest, 'create_status', 409), 2),
            'another acp_server answers': (lambda: self.guest.create_agent.update(acp_server='codex'), 2),
            'the broker admitted no request': (lambda: self.broker.grant.update(requests=0), 10),
            'the native child tool appears': (lambda: self.guest.events[1].append(
                {'id': 'e7', 'kind': 'ActionEvent', 'tool_name': 'start_child_conversation'}), 9),
            'an inner conversation of another parent': (lambda: setattr(
                self.guest, 'inner_after', self.guest.inner_before + [{'id': OTHER, 'parent_conversation_id': None}]),
                8),
            'the adapter is missing while the turn runs': (lambda: setattr(
                self.guest, 'during', snapshot({k: v for k, v in tcc.CONTAINER.items() if k not in (20, 21, 22)},
                                               rows=[TO_ENDPOINT])), 5),
            'root is obtainable in the job': (lambda: self.guest.env.update(sudo={'rc': 0, 'out': ''}), 6),
            'the token name holds another shape': (lambda: setattr(self.guest, 'env', job_env(
                {'ANTHROPIC_API_KEY': {'token': False, 'provider_key': False}})), 6),
            'a limit differs': (lambda: self.guest.during['limits'].update({'pids.max': 'max'}), 5),
        }
        for name, (change, number) in cases.items():
            with self.subTest(name):
                self.setUp()
                change()
                out = self.run_driver()
                self.assertEqual(out['result'], 'FAIL', name)
                self.assertEqual(self.step(out, number)['verdict'], 'FAIL', name)

    def test_preconditions(self):
        changes = {
            'the forward is not held': lambda: None,
            'the grant is revoked': lambda: self.broker.grant.update(state='revoked'),
            'another conversation': lambda: self.broker.grant.update(conversation_id=OTHER),
            'another family': lambda: self.broker.grant.update(family='openai-responses'),
            'the family is not ready': lambda: self.broker.family.update(ready=False),
            'the model is not in the grant': lambda: self.broker.grant.update(models=['model-small']),
            'the model is not allowlisted': lambda: self.broker.family.update(models=['model-small']),
            'the broker holds another key': lambda: self.broker.key.update(fingerprint='sha256:' + '0' * 16),
            'the broker holds a real key': lambda: self.broker.key.update(source='windows-credential-manager'),
            'a conversation exists': lambda: setattr(self.guest, 'created', True),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.setUp()
                change()
                held = name != 'the forward is not held'
                out = self.run_driver(forward=types.SimpleNamespace(status=lambda: {'held': held}))
                self.assertEqual((out['result'], self.step(out, 1)['verdict']), ('FAIL', 'FAIL'), name)
                self.assertNotIn(('POST', '/api/conversations'), self.guest.calls)
                self.assertEqual(self.step(out, 2)['skipped'], 'not reached (ready)')
                self.assertEqual(self.step(out, 12)['verdict'], 'PASS')
                self.assertEqual(self.step(out, 13)['skipped'], 'not reached (created)')
        # a real-key run needs a broker key from a credential provider
        self.setUp()
        out = self.run_driver(key_mode='real', real_key_act='A1')
        self.assertEqual(self.step(out, 1)['verdict'], 'FAIL')

    def test_admission_refuses_and_nothing_is_sent(self):
        acp = guest.acp_qualification()
        with mock.patch.object(acp, 'approved_model', side_effect=acp.QualificationRefused('MODEL_NOT_APPROVED', 'x')):
            out = self.run_driver()
        self.assertEqual(self.step(out, 2)['verdict'], 'FAIL')
        self.assertEqual(self.step(out, 2)['detail']['admission']['code'], 'MODEL_NOT_APPROVED')
        self.assertNotIn(('POST', '/api/conversations'), self.guest.calls)
        self.assertEqual(self.step(out, 13)['skipped'], 'not reached (created)')

    def test_lost_answers_are_unknown_never_pass(self):
        base = f'/api/conversations/{CID}'
        for path, number in ((base + '/events/search?limit=100', 9), ('/api/conversations/search?limit=100', 3),
                             (base + '/agent_final_response', 9)):
            with self.subTest(path=path):
                self.setUp()
                self.guest.lose = {path}
                out = self.run_driver()
                self.assertEqual(self.step(out, number)['verdict'], 'UNKNOWN')
                self.assertNotEqual(out['result'], 'PASS')
        # the turn never ends within the ceiling
        self.setUp()
        self.guest.statuses = ['running']
        out = self.run_driver()
        self.assertEqual((self.step(out, 7)['verdict'], out['result']), ('UNKNOWN', 'UNKNOWN'))
        # an events page of another shape, or no event at all
        self.setUp()
        self.guest.events = [[]]
        out = self.run_driver()
        self.assertEqual(self.step(out, 9)['verdict'], 'UNKNOWN')
        # the broker's counters unreadable
        self.setUp()
        self.broker.grant['requests'] = None
        out = self.run_driver()
        self.assertEqual(self.step(out, 10)['verdict'], 'UNKNOWN')
        # inspect gave no key-search check
        self.setUp()
        out = self.run_driver(inspect_fn=lambda fp, key: {'properties': []})
        self.assertEqual(self.step(out, 11)['verdict'], 'UNKNOWN')
        # the token's name not observed: the gate was not exercised
        self.setUp()
        self.guest.env = job_env(names=())
        out = self.run_driver()
        self.assertEqual(self.step(out, 6)['verdict'], 'UNKNOWN')
        # the inner server's list unread
        self.setUp()
        self.guest.inner_before = None
        out = self.run_driver()
        self.assertEqual(self.step(out, 3)['verdict'], 'UNKNOWN')
        self.assertEqual(self.step(out, 4)['skipped'], 'not reached (before)')

    def test_an_adapter_missed_after_the_turn_ended_is_unknown(self):
        self.guest.statuses = ['finished']
        gone = {k: v for k, v in tcc.CONTAINER.items() if k not in (20, 21, 22)}
        self.guest.during = snapshot(gone, rows=[TO_ENDPOINT])
        out = self.run_driver(host=lambda rec, pid: host_snapshot(gone))
        self.assertEqual(self.step(out, 5)['verdict'], 'UNKNOWN')
        self.assertEqual(self.step(out, 5)['detail']['execution_status_after_the_snapshot'], 'finished')

    def test_an_events_stream_longer_than_the_bound(self):
        self.guest.events = [[{'id': f'e{i}', 'kind': 'MessageEvent'}] for i in range(guest.ACP_EVENT_PAGES + 1)]
        out = self.run_driver()
        self.assertEqual(self.step(out, 9)['verdict'], 'UNKNOWN')

    def test_refusals_before_anything_runs(self):
        ctx = types.SimpleNamespace(profile=PROFILE, repo=REPO, instance_dir=lambda n: self.state / n)
        cases = [
            (dict(prompt='other'), '--prompt'),
            (dict(key_mode='maybe'), '--key-search'),
            (dict(key_mode='synthetic'), 'needs the synthetic key'),
            (dict(key_mode='synthetic', provider_key=SYNTHETIC, provider_key_fingerprint='x'), 'needs the synthetic'),
            (dict(key_mode='off', provider_key=SYNTHETIC), 'synthetic only'),
            (dict(key_mode='real'), 'needs --real-key-act'),
            (dict(key_mode='real', real_key_act=' bad'), 'needs --real-key-act'),
            (dict(key_mode='off', real_key_act='A1'), 'real only'),
            (dict(token='not-a-token'), "broker's shape"),
        ]
        touched = mock.Mock(side_effect=AssertionError('the guest was reached'))
        for kw, message in cases:
            with self.subTest(kw=kw), mock.patch.object(guest, 'running_instance', touched), \
                    self.assertRaisesRegex(guest.Refused, re.escape(message)):
                args = dict(key_mode='off')
                args.update(kw)
                guest.acp_qualification_run(ctx, 'g1', args.pop('token', TOKEN), args.pop('prompt', 'single'),
                                            MODEL, **args)
        for record, message in (({'ports': {}}, 'was not created with --provision'),
                                ({'provisioning': {}, 'ports': {}}, 'was not created with --provision'),
                                ({'provisioning': {'x': 1}, 'ports': {}}, '--inference')):
            with self.subTest(record=record), \
                    mock.patch.object(guest, 'running_instance', return_value=(None, record)), \
                    self.assertRaisesRegex(guest.Refused, re.escape(message)):
                guest.acp_qualification_run(ctx, 'g1', TOKEN, 'single', MODEL)
        for out_path in (str(REPO / 'x.json'), str(self.state / 'missing' / 'x.json'), str(self.state / 'g1' / 'x')):
            with self.subTest(out_path=out_path), \
                    mock.patch.object(guest, 'running_instance', return_value=(None, RECORD)), \
                    self.assertRaisesRegex(guest.Refused, '--out'):
                (self.state / 'g1').mkdir(exist_ok=True)
                guest.acp_qualification_run(ctx, 'g1', TOKEN, 'single', MODEL, out_path=out_path)

    def test_out_file_and_the_record_redaction(self):
        target = self.state / 'record.json'
        self.guest.echo_token = True
        out = self.run_driver(out_path=str(target))
        self.assertEqual(out['out'], str(target.resolve()))
        data = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(data['result'], 'FAIL')
        self.assertNotIn(TOKEN, target.read_text(encoding='utf-8'))
        self.assertEqual(data['attempt_token']['fingerprint'], TOKEN_FP)

    def test_default_seams_never_read_a_key_or_reach_a_root_channel(self):
        """With no seam given: the host vantage is the root facts report read through the facts channel (a gap,
        UNKNOWN, without its section), the real key reader is the gated one, the provider factory is never called
        in a synthetic or off run."""
        with self.assertRaisesRegex(guest.Refused, 'no guest-root view'):
            guest.facts_host_vantage(lambda: {'containers': []})(RECORD, 1)
        factory = mock.Mock(side_effect=AssertionError('the credential provider was read'))
        with mock.patch.object(guest.inference_control().broker.credentials, 'select_provider', factory):
            out = self.run_driver(key_mode='off', host=None, real_key_reader=None)
            self.run_driver(real_key_reader=None)
        factory.assert_not_called()
        self.assertEqual(out['result'], 'UNKNOWN')

    def test_the_prompts_and_the_reserved_ids_are_fixed(self):
        self.assertEqual(sorted(guest.ACP_QUALIFICATION_PROMPTS), ['delegated', 'single'])
        self.assertEqual(guest.ACP_QUALIFICATION_PROMPTS['single'], 'Reply with exactly one word: ready')
        self.assertRegex(CID, r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$')
        self.assertNotIn(CID, (guest.CUSTODY_CONVERSATION_ID, guest.JOB_PEER_CONVERSATION_ID, guest.PROBE_UUID))
        for word in ('STOP', 'UNKNOWN', 'npx', 'outer-server conversation', 'recorded surface',
                     'inference endpoint', 'lineage'):
            self.assertIn(word, guest.ACP_QUALIFICATION_RULE)


    # ---- tests from the mutation check: each fact of a check on its own

    def test_the_record_details(self):
        out = self.run_driver()
        create = self.guest.bodies[('POST', '/api/conversations')]
        self.assertEqual(self.step(out, 2)['detail']['sent_body_sha256'],
                         guest.dispatch_transport().body_sha256(create))
        self.assertEqual(self.step(out, 2)['detail']['agent'],
                         {'kind': 'ACPAgent', 'acp_server': 'claude-code', 'acp_model': MODEL})
        self.assertEqual(self.step(out, 2)['detail']['containers'], 1)
        self.assertEqual(self.step(out, 9)['detail']['kinds'], {'MessageEvent': 2, guest.ACP_TOOL_CALL_KIND: 1})
        mech = self.step(out, 9)['detail']['mechanisms']["(a) the provider's own tools and sub-agents"]
        self.assertEqual(mech['provider_processes'], {'during': ['node', 'claude', 'bash'],
                                                      'after': ['node', 'claude', 'bash']})
        spec, = self.guest.env_specs
        self.assertEqual(spec['attempt_token'], guest.attempt_token_spec(('ANTHROPIC_API_KEY',)))
        self.assertEqual(spec['pattern'],
                         PROFILE['provisioning']['agent_server']['jobs']['environment']['credential_name_pattern'])
        self.assertIn('/run/docker.sock', spec['sockets'])

    def test_each_precondition_fact_alone(self):
        for name, change in (('the count is not answered', lambda: self.guest.answers.update(
                {'/api/conversations/count': (500, {})})),
                             ('the outer server counts one', lambda: setattr(self.guest, 'count', 1)),
                             ('a container the outer server does not count',
                              lambda: setattr(self.guest, 'phantom', True))):
            with self.subTest(name):
                self.setUp()
                change()
                out = self.run_driver()
                self.assertEqual(self.step(out, 1)['verdict'], 'FAIL')
                self.assertEqual([k for k, v in self.step(out, 1)['detail']['checks'].items() if not v],
                                 ['no conversation container' if 'container' in name else
                                  'the outer server holds no conversation'])
        self.setUp()
        self.broker = FakeBroker(source='windows-credential-manager', fingerprint=None)
        out = self.run_driver(key_mode='real', real_key_act='A1')
        self.assertEqual((self.step(out, 1)['verdict'], self.real_reads), ('FAIL', []))

    def test_each_create_fact_alone(self):
        for name, change in (('a second container', lambda: setattr(self.guest, 'extra_after_create', True)),
                             ('another image', lambda: setattr(self.guest, 'image', 'sha256:' + '0' * 64))):
            with self.subTest(name):
                self.setUp()
                change()
                out = self.run_driver()
                self.assertEqual(self.step(out, 2)['verdict'], 'FAIL')
        self.setUp()
        self.guest.create_agent = {'kind': 'ACPAgent'}           # an answer that names no acp_server
        self.assertEqual(self.step(self.run_driver(), 2)['verdict'], 'PASS')

    def test_teardown_failures(self):
        base = f'/api/conversations/{CID}'
        cases = {'the delete is refused': lambda: setattr(self.guest, 'delete_refused', True),
                 'the container stays': lambda: setattr(self.guest, 'keep_container', True),
                 'the outer server still counts one': lambda: setattr(self.guest, 'count_after', 1)}
        for name, change in cases.items():
            with self.subTest(name):
                self.setUp()
                change()
                original = self.guest.answer

                def answer(method, path, body, original=original):
                    if method == 'DELETE' and getattr(self.guest, 'delete_refused', False):
                        self.guest.calls.append((method, path))
                        return 500, {}
                    if path == '/api/conversations/count' and method == 'GET' and \
                            getattr(self.guest, 'count_after', None) is not None and \
                            ('DELETE', base) in self.guest.calls:
                        self.guest.calls.append((method, path))
                        return 200, self.guest.count_after
                    return original(method, path, body)
                self.guest.answer = answer
                out = self.run_driver()
                self.assertEqual((self.step(out, 13)['verdict'], out['result']), ('FAIL', 'FAIL'), name)

    def test_container_and_list_errors_are_unknown(self):
        for name, change, number in (
                ('the bash route refuses', lambda: setattr(self.guest, 'bash', (500, {})), 3),
                ('the command gives no exit code', lambda: setattr(self.guest, 'bash', (200, {'stdout': ''})), 3),
                ('the outer list is refused', lambda: self.guest.answers.update(
                    {'/api/conversations/search?limit=100': (500, {'items': []})}), 3),
                ('the outer list is not a list', lambda: self.guest.answers.update(
                    {'/api/conversations/search?limit=100': (200, {'items': {}})}), 3),
                ('the outer list has another page', lambda: self.guest.answers.update(
                    {'/api/conversations/search?limit=100': (200, {'items': [], 'next_page_id': 'x'})}), 3),
                ('an outer id that is not a uuid', lambda: self.guest.answers.update(
                    {'/api/conversations/search?limit=100': (200, {'items': [{'id': 'conversation-1'}]})}), 3),
                ('an events page refused', lambda: self.guest.answers.update(
                    {f'/api/conversations/{CID}/events/search?limit=100': (500, {'items': []})}), 9),
                ('an events page of another shape', lambda: self.guest.answers.update(
                    {f'/api/conversations/{CID}/events/search?limit=100': (200, {'items': 'x'})}), 9),
                ('a second container once the turn runs', lambda: setattr(self.guest, 'extra_when_sent', True), 5)):
            with self.subTest(name):
                self.setUp()
                change()
                out = self.run_driver()
                self.assertEqual(self.step(out, number)['verdict'], 'UNKNOWN', name)
                self.assertNotEqual(out['result'], 'PASS')

    def test_a_lost_answer_is_not_a_stop(self):
        self.guest.malformed = {f'/api/conversations/{CID}/agent_final_response'}
        out = self.run_driver()
        self.assertEqual((self.step(out, 9)['verdict'], out['stop_conditions'], out['result']),
                         ('UNKNOWN', [], 'UNKNOWN'))
        self.assertEqual(self.step(out, 9)['detail']['error'], 'NO_ANSWER')

    def test_during_the_turn_a_stop_or_another_failure_is_never_excused(self):
        gone = {k: v for k, v in tcc.CONTAINER.items() if k not in (20, 21, 22)}
        for name, processes, change in (
                ('npx with the adapter gone', {**gone, 23: (8, '/usr/bin/node', ['npx', '-y', 'x'])}, None),
                ('a limit with the adapter gone', gone, lambda snap: snap['limits'].update({'pids.max': 'max'}))):
            with self.subTest(name):
                self.setUp()
                self.guest.statuses = ['finished']
                self.guest.during = snapshot(processes, rows=[TO_ENDPOINT])
                if change:
                    change(self.guest.during)
                out = self.run_driver(host=lambda rec, pid: host_snapshot(gone))
                self.assertEqual(self.step(out, 5)['verdict'], 'FAIL', name)

    def test_after_the_turn_each_view_fails_on_its_own(self):
        bad_host = host_snapshot()
        bad_host['limits'] = dict(bad_host['limits'], **{'pids.max': 'max'})

        def host_after(rec, pid):
            return bad_host if self.turn_done else host_snapshot()
        cases = {
            'the container view': (lambda: self.guest.after['limits'].update({'pids.max': 'max'}), {}),
            'the guest-root view': (lambda: None, {'host': host_after}),
            'the connections (ambiguous, no stop)': (lambda: setattr(self.guest, 'after', snapshot(
                rows=[TO_ENDPOINT, tcc.tcp_row('020011AC:C351', '01010101:01BB', '07', 6003)])), {}),
        }
        for name, (change, kw) in cases.items():
            with self.subTest(name):
                self.setUp()
                change()
                out = self.run_driver(**kw)
                self.assertEqual((self.step(out, 8)['verdict'], out['stop_conditions']), ('FAIL', []), name)

    def test_the_job_contract_needs_the_admitted_names(self):
        bare = json.loads(json.dumps(PROFILE))
        del bare['network']['inference_composition']['attempt_token_environment']
        out = self.run_driver(profile=bare)
        self.assertEqual(self.step(out, 6)['verdict'], 'FAIL')
        self.assertNotIn('attempt_token', self.guest.env_specs[0])

    def test_the_native_tool_in_an_acp_tool_call_fails(self):
        self.guest.events[1].append({'id': 'e7', 'kind': guest.ACP_TOOL_CALL_KIND,
                                     'title': 'start_child_conversation(task)'})
        out = self.run_driver()
        self.assertEqual(self.step(out, 9)['verdict'], 'FAIL')
        self.assertEqual(self.step(out, 9)['detail']['mechanisms']["(d) OpenHands' start_child_conversation tool"]
                         ['events_naming_it'], ['e7'])

    def test_the_key_search_is_unknown_unless_both_searches_are_clean(self):
        ks = guest.key_search()
        real_report = ks.Search.report
        for verdict in ('incomplete', 'invalid'):
            with self.subTest(verdict=verdict):
                self.setUp()
                with mock.patch.object(ks.Search, 'report',
                                       lambda self_, real=real_report, v=verdict: dict(real(self_), verdict=v)):
                    out = self.run_driver()
                self.assertEqual((self.step(out, 11)['verdict'], out['result']), ('UNKNOWN', 'UNKNOWN'))
        self.setUp()
        out = self.run_driver(inspected='UNKNOWN')
        self.assertEqual(self.step(out, 11)['verdict'], 'UNKNOWN')

    def test_the_key_in_a_container_output_is_found(self):
        self.guest.collector_noise = base64.b64encode(SYNTHETIC.encode()).decode() + '\n'
        out = self.run_driver()
        self.assertEqual((self.step(out, 11)['verdict'], out['result']), ('FAIL', 'FAIL'))

    def test_an_already_revoked_grant_is_not_revoked_again(self):
        self.broker.grant['state'] = 'revoked'
        out = self.run_driver()
        self.assertEqual(self.step(out, 12)['verdict'], 'PASS')
        self.assertNotIn('revoke', [c[0] for c in self.broker.calls])
        self.setUp()
        self.broker.grant['state'] = 'expired'
        original = self.broker.call
        self.broker.call = lambda method, *a: dict(original(method, *a), state='expired') \
            if method in ('grant', 'revoke') else original(method, *a)
        out = self.run_driver()
        self.assertEqual(self.step(out, 12)['verdict'], 'FAIL')

    def test_the_stop_names_its_cause(self):
        self.guest.during = snapshot({**tcc.CONTAINER, 40: (0, '/usr/bin/bash', ['bash'])}, rows=[TO_ENDPOINT])
        out = self.run_driver()
        self.assertEqual(sorted(self.stops(out)), [
            "a process outside the container's lineage (entered from outside)",
            "a process outside the container's lineage (not a descendant of the inner server)"])
        # with the inner server not identified (no listener owner), its ancestry is a failure, not a stop
        self.setUp()
        fs = tcc.container_fs(socket_owner=None)
        fs.files['/proc/net/tcp'] = (tcc.TCP + TO_ENDPOINT).encode()
        self.guest.during = tcc.container_snapshot(fs)
        out = self.run_driver()
        self.assertEqual((self.step(out, 5)['verdict'], out['stop_conditions']), ('FAIL', []))

    def test_more_refusals(self):
        ctx = types.SimpleNamespace(profile=PROFILE, repo=REPO, instance_dir=lambda n: self.state / n)
        with mock.patch.object(guest, 'running_instance', side_effect=AssertionError('reached')), \
                self.assertRaisesRegex(guest.Refused, 'needs the synthetic key'):
            guest.acp_qualification_run(ctx, 'g1', TOKEN, 'single', MODEL, key_mode='synthetic',
                                        provider_key_fingerprint=SYNTHETIC_FP)
        existing = self.state / 'exists.json'
        existing.write_text('{}', encoding='utf-8')
        with mock.patch.object(guest, 'running_instance', return_value=(None, RECORD)), \
                self.assertRaisesRegex(guest.Refused, '--out'):
            guest.acp_qualification_run(ctx, 'g1', TOKEN, 'single', MODEL, out_path=str(existing))

    def test_the_synthetic_source_is_the_launchers(self):
        source = (REPO / 'integrations' / 'inference' / 'inference_qualification.py').read_text(encoding='utf-8')
        self.assertIn(repr(guest.ACP_SYNTHETIC_SOURCE), source)
        self.assertEqual((guest.ACP_QUALIFICATION_FAMILY, guest.ACP_QUALIFICATION_PROVIDER, guest.ACP_EVENT_PAGES),
                         ('anthropic-messages', 'claude-code', 50))
        self.assertEqual(guest.ACP_TURN_CEILING_S, 1920)
        self.assertEqual(guest.ACP_TURN_END, ('finished', 'error', 'stuck', 'paused', 'waiting_for_confirmation'))
        # F-8: the enum and the SDK's terminal set as the pinned image defines them (the D-1 record, section 7)
        self.assertEqual(guest.ACP_STATUS_VALUES, ('idle', 'running', 'paused', 'waiting_for_confirmation',
                                                   'finished', 'error', 'stuck', 'deleting'))
        self.assertEqual((guest.ACP_TURN_TERMINAL, guest.ACP_TURN_HALTED, guest.ACP_TURN_RUNNING),
                         (('finished', 'error', 'stuck'), ('paused', 'waiting_for_confirmation'),
                          ('idle', 'running')))
        for key, text in guest.ACP_ASSUMED.items():
            self.assertIn('evidence/S-03.3-D-1-image-source-read.md section 7', text, key)
        self.assertIn('429', guest.ACP_ASSUMED['message'])
        self.assertIn('retries nothing', guest.ACP_ASSUMED['message'])

    # F-8: (verdict of step 7, its outcome, whether it is a stop) of each value the turn's last status can take
    STATUS_OUTCOMES = {
        'finished': ('PASS', 'terminal', False),
        'error': ('FAIL', 'terminal', False),
        'stuck': ('FAIL', 'terminal', False),
        'paused': ('FAIL', 'halted', False),
        'waiting_for_confirmation': ('FAIL', 'halted', True),
        'deleting': ('FAIL', 'deleting', False),
        'FINISHED': ('FAIL', 'outside the status enum', False),
        'archived': ('FAIL', 'outside the status enum', False),
        7: ('FAIL', 'outside the status enum', False),
        'idle': ('UNKNOWN', 'not ended within the ceiling', False),
        'running': ('UNKNOWN', 'not ended within the ceiling', False),
        None: ('UNKNOWN', 'not ended within the ceiling', False),
    }

    def test_each_status_value_has_its_outcome(self):
        for status, (verdict, outcome, is_stop) in self.STATUS_OUTCOMES.items():
            with self.subTest(status=status):
                self.setUp()
                self.guest.statuses = ['running', status]
                out = self.run_driver()
                step = self.step(out, 7)
                self.assertEqual((step['verdict'], step['detail']['outcome'], step['detail']['execution_status']),
                                 (verdict, outcome, status))
                self.assertEqual(step['detail']['within_ceiling'], verdict != 'UNKNOWN')
                self.assertEqual(out['result'], 'PASS' if verdict == 'PASS' else verdict)
                self.assertEqual(guest.ACP_CONFIRMATION_STOP in self.stops(out), is_stop)
                if is_stop:      # the later steps are skipped; the search, the revocation and the teardown run
                    self.assertEqual([self.step(out, n).get('skipped') for n in (8, 9, 10)],
                                     ['a stop condition'] * 3)
                    self.assertEqual([self.step(out, n)['verdict'] for n in (11, 12, 13)], ['PASS'] * 3)
                else:
                    self.assertEqual(self.stops(out), [])
        # the wait ends on every value but idle, running and none, at the first such read
        for status in guest.ACP_STATUS_VALUES + ('archived', 7, None):
            self.assertEqual(guest.acp_turn_over(status), status not in ('idle', 'running', None), status)
            self.assertEqual(guest.acp_turn_outcome(status)[0] == 'PASS', status == 'finished', status)
        self.assertEqual(guest.acp_turn_outcome('running'), ('UNKNOWN', 'not ended'))

    def test_the_default_vantage_reads_the_reporters_section(self):
        self.guest.host_section = host_section
        out = self.run_driver(host=None)
        self.assertEqual(out['result'], 'PASS', [(s['step'], s['verdict'], s.get('detail')) for s in out['steps']])
        self.assertEqual(self.verdicts(out), ['PASS'] * 13)
        for number in (5, 8):
            detail = self.step(out, number)['detail']
            self.assertEqual(detail['host_vantage'], 'guest root')
            self.assertEqual([c['ok'] for c in detail['host']['checks']], [True] * len(detail['host']['checks']))
        with_default = self.guest.facts_calls
        self.setUp()
        self.run_driver()
        self.assertEqual(with_default - self.guest.facts_calls, 2)     # one new report per observation

    def test_a_gap_in_the_reporters_section_is_unknown_never_pass(self):
        for name, (section, fragment) in section_gaps().items():
            with self.subTest(name):
                self.setUp()
                self.guest.host_section = section
                out = self.run_driver(host=None)
                self.assertEqual(out['result'], 'UNKNOWN', name)
                self.assertEqual(out['stop_conditions'], [])
                for number in (5, 8):
                    self.assertEqual(self.step(out, number)['verdict'], 'UNKNOWN', (name, number))
                    self.assertIn(fragment, self.step(out, number)['detail']['host_vantage'])

    def test_the_reporters_view_is_judged_by_slice_1(self):
        escaped = host_snapshot()
        escaped['outside_children'] = [dict(escaped['processes'][3], pid=9999, pidns='pid:[1]',
                                            ppid=tcc.HOST_BASE + 8)]
        self.guest.host_section = host_section(escaped)
        out = self.run_driver(host=None)
        self.assertEqual(out['result'], 'FAIL')
        self.assertIn("a process outside the container's lineage (an escaped child)", self.stops(out))
        self.assertEqual(self.step(out, 5)['verdict'], 'FAIL')
        self.setUp()
        unreadable = host_snapshot()
        unreadable['processes'].append({'pid': 5000, 'ppid': None, 'error': 'stat: PermissionError'})
        self.guest.host_section = host_section(unreadable)
        out = self.run_driver(host=None)
        self.assertEqual((self.step(out, 5)['verdict'], self.step(out, 8)['verdict'], out['result']),
                         ('FAIL', 'FAIL', 'FAIL'))


def host_section(snap=None, *, cid='0123abcd' * 8, truncated=None):
    """The root reporter's containment section (S-03.3 slice 6, the seed's containment_host) holding one container's
    slice 1 host snapshot."""
    entry = dict(snap or host_snapshot(), truncated=truncated or {'processes': 0, 'outside_children': 0})
    return {'format': CC.SNAPSHOT_FORMAT, 'containers': {cid: entry}, 'skipped': 0,
            'caps': {'containers': 16, 'processes': 1024, 'outside_children': 64}}


def section_gaps():
    """{name: (section, the gap message's fragment)}: each a field slice 1 needs that the reporter left out."""
    pid = tcc.HOST_BASE + 1

    def entry_change(change):
        section = host_section()
        change(section['containers']['0123abcd' * 8])
        return section

    def first_process(change):
        return entry_change(lambda e: change(e['processes'][0]))
    second = host_section(cid='f' * 64)['containers']
    return {
        'the reporter recorded an error': ({'error': 'OSError: x'}, 'not of its shape'),
        'another format': (dict(host_section(), format='other/v1'), 'not of its shape'),
        'no container map': (dict(host_section(), containers=[]), 'not of its shape'),
        'no entry for the init': (dict(host_section(), containers={}, skipped=3), '0 entries'),
        'two entries for the init': (dict(host_section(), containers=dict(host_section()['containers'], **second)),
                                     '2 entries'),
        'the entry is an error': (dict(host_section(), containers={'x': {'error': 'TARGET_INVALID: pid 1: '
                                                                         'PermissionError', 'target_pid': pid}}),
                                  'TARGET_INVALID'),
        'members truncated': (host_section(truncated={'processes': 1, 'outside_children': 0}), 'truncated'),
        'outside children truncated': (host_section(truncated={'processes': 0, 'outside_children': 2}), 'truncated'),
        'no truncation count': (entry_change(lambda e: e.update(truncated=None)), 'truncated'),
        'no limits key': (entry_change(lambda e: e.pop('limits')), "missing ['limits']"),
        'a container snapshot': (entry_change(lambda e: e.update(mode='container')), 'not slice 1'),
        'a process without its executable': (first_process(lambda p: p.pop('exe')), "lacks ['exe']"),
        'a process without its namespace link': (first_process(lambda p: p.pop('pidns')), "lacks ['pidns']"),
        'a status without Seccomp': (first_process(lambda p: p['status'].pop('Seccomp')), 'status Seccomp'),
        'a process without its parent': (first_process(lambda p: p.pop('ppid')), 'without pid or ppid'),
    }


class HostVantage(unittest.TestCase):
    """host_snapshot_from_report on its own: slice 1's host snapshot out of the root reporter's section, or a gap."""

    def test_the_snapshot_is_slice_1s_own(self):
        pid = tcc.HOST_BASE + 1
        section = host_section()
        other = host_section(host_snapshot(), cid='e' * 64)['containers']['e' * 64]
        other['target_pid'] = 777
        section['containers']['e' * 64] = other
        snap = guest.host_snapshot_from_report({'containers': [], guest.ACP_HOST_SECTION: section}, pid)
        self.assertEqual(snap, host_snapshot())
        self.assertIn('truncated', section['containers']['0123abcd' * 8])     # the report is not changed
        verdict = CC.host_verdict(snap, inspect=tcc.INSPECT, container=tcc.container_snapshot(),
                                  expected=tcc.expected())
        self.assertTrue(verdict['ok'], verdict['checks'])

    def test_each_gap_is_refused(self):
        for name, (section, fragment) in section_gaps().items():
            with self.subTest(name):
                with self.assertRaises(guest.Refused) as raised:
                    guest.host_snapshot_from_report({guest.ACP_HOST_SECTION: section}, tcc.HOST_BASE + 1)
                self.assertEqual(raised.exception.code, 'HOST_VANTAGE')
                self.assertIn(fragment, str(raised.exception))
        for report in ({}, None, [], {'containers': []}):
            with self.subTest(report=report), self.assertRaisesRegex(guest.Refused, "no 'containment' section"):
                guest.host_snapshot_from_report(report, tcc.HOST_BASE + 1)

    def test_slice_1s_own_failed_reads_pass_through(self):
        # an unreadable stat (slice 1's error record) and an unreadable status are judged by slice 1, not refused
        snap = host_snapshot()
        snap['processes'].append({'pid': 5000, 'ppid': None, 'error': 'stat: PermissionError'})
        snap['processes'][1]['status'] = {'error': 'PermissionError'}
        got = guest.host_snapshot_from_report({guest.ACP_HOST_SECTION: host_section(snap)}, tcc.HOST_BASE + 1)
        self.assertEqual(got, snap)
        verdict = CC.host_verdict(got, inspect=tcc.INSPECT, container=tcc.container_snapshot(),
                                  expected=tcc.expected())
        self.assertFalse(verdict['ok'])


class Delegation(unittest.TestCase):
    """acp_delegation on its own: what each mechanism is classified from."""

    def test_processes_alone_or_tool_calls_alone_show_mechanism_a(self):
        a = "(a) the provider's own tools and sub-agents"
        self.assertTrue(guest.acp_delegation([], ['node', 'claude', 'bash'], None, [], [])[a]['observed'])
        self.assertTrue(guest.acp_delegation([], None, ['node', 'claude', 'bash'], [], [])[a]['observed'])
        self.assertFalse(guest.acp_delegation([], ['node', 'claude'], ['node'], [], [])[a]['observed'])
        self.assertFalse(guest.acp_delegation([{'kind': 'MessageEvent'}], None, None, [], [])[a]['observed'])
        out = guest.acp_delegation([{'kind': guest.ACP_TOOL_CALL_KIND}], None, None, [], [])[a]
        self.assertEqual((out['observed'], out['tool_call_titles']), (True, ['None']))

    def test_the_drivers_own_fork_calls_are_named(self):
        calls = [{'path': '/api/conversations/x/ask_agent'}, {'path': '/api/conversations/x/fork?y=1'},
                 {'path': '/api/conversations/x/children'}, {'path': '/api/conversations/x/events'},
                 {'path': '/api/conversations/x/forked'}]
        b = guest.acp_delegation([], None, None, [], calls)['(b) an ACP session fork (ask_agent)']
        self.assertEqual(b['driver_called'], ['/api/conversations/x/ask_agent', '/api/conversations/x/fork?y=1',
                                              '/api/conversations/x/children'])

    def test_the_native_tool_by_name_only(self):
        d = "(d) OpenHands' start_child_conversation tool"
        for events, want in (([{'id': 1, 'tool_name': 'start_child_conversation'}], [1]),
                             ([{'id': 2, 'kind': 'MessageEvent', 'title': 'start_child_conversation'}], []),
                             ([{'id': 3, 'kind': guest.ACP_TOOL_CALL_KIND, 'title': None}], []),
                             ([{'id': 4, 'kind': guest.ACP_TOOL_CALL_KIND, 'title': 'x start_child_conversation'}],
                              [4])):
            with self.subTest(events=events):
                self.assertEqual(guest.acp_delegation(events, None, None, [], [])[d]['events_naming_it'], want)


INNER_KEY = 'inner-session-key-' + 'K' * 32


class InnerServer(http.server.ThreadingHTTPServer):
    """A loopback stand-in for the conversation's inner server: GET /api/conversations/search pages, key-gated."""

    def __init__(self):
        server = self
        self.pages, self.seen, self.status, self.echo, self.body = [], [], 200, False, None

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                server.seen.append((self.path, self.headers.get('X-Session-API-Key')))
                index = int(self.path.split('page_id=p')[1]) if 'page_id=' in self.path else 0
                if self.headers.get('X-Session-API-Key') != INNER_KEY:
                    status, body = 401, {'detail': 'Unauthorized'}
                else:
                    nxt = f'p{index + 1}' if index + 1 < len(server.pages) else None
                    status, body = server.status, {'items': server.pages[index], 'next_page_id': nxt}
                    if server.body is not None:
                        body = server.body
                    if server.echo:
                        body['key'] = INNER_KEY
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        super().__init__(('127.0.0.1', 0), Handler)


class InnerConversationsScript(unittest.TestCase):
    """ACP_INNER_CONVERSATIONS itself, in this process: the key from an in-memory /proc/1/environ, the inner server a
    loopback fake. Ids and parents only; the key never printed, its echoes counted."""
    category = 'integration'  # its class fixture serves a loopback HTTP socket: not unit (docs/development.md)

    @classmethod
    def setUpClass(cls):
        cls.server = InnerServer()
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)

    def setUp(self):
        self.server.pages = [[{'id': CID, 'parent_conversation_id': None, 'title': 'x'}],
                             [{'id': CHILD, 'parent_conversation_id': CID}, 'not an object']]
        self.server.seen.clear()
        self.server.status, self.server.echo, self.server.body = 200, False, None

    def run_script(self, environ=b'OH_SESSION_API_KEYS_0=' + INNER_KEY.encode() + b'\0PATH=/bin\0'):
        real_open = builtins.open

        def fake_open(path, mode='r', *args, **kwargs):
            if path == '/proc/1/environ':
                if environ is None:
                    raise PermissionError(path)
                return io.BytesIO(environ)
            return real_open(path, mode, *args, **kwargs)
        printed = io.StringIO()
        argv = ['probe', str(self.server.server_address[1])]
        with mock.patch('builtins.open', fake_open), mock.patch.object(sys, 'argv', argv), \
                contextlib.redirect_stdout(printed):
            exec(compile(guest.ACP_INNER_CONVERSATIONS, 'ACP_INNER_CONVERSATIONS', 'exec'), {'__name__': '__probe__'})
        self.assertNotIn(INNER_KEY, printed.getvalue())
        return guest._job_json(printed.getvalue())

    def test_pages_are_followed_and_only_ids_and_parents_kept(self):
        out = self.run_script()
        self.assertEqual(out, {'key_present': True, 'status': 200, 'pages': 2, 'key_occurrences': 0,
                               'items': [{'id': CID, 'parent_conversation_id': None},
                                         {'id': CHILD, 'parent_conversation_id': CID}]})
        self.assertEqual([p for p, _ in self.server.seen],
                         ['/api/conversations/search?limit=100', '/api/conversations/search?limit=100&page_id=p1'])
        self.assertEqual({k for _, k in self.server.seen}, {INNER_KEY})

    def test_no_key_no_request_and_failures_leave_items_unset(self):
        out = self.run_script(environ=None)
        self.assertEqual((out['key_present'], out['items'], out['error'], self.server.seen),
                         (False, None, 'PermissionError', []))
        out = self.run_script(environ=b'PATH=/bin\0')
        self.assertEqual((out['key_present'], out['items'], out['pages']), (False, None, 0))
        self.server.status = 500
        out = self.run_script()
        self.assertEqual((out['items'], out['status'], out['pages']), (None, 500, 1))
        self.server.status, self.server.echo = 200, True
        out = self.run_script()
        self.assertEqual((out['key_occurrences'], out['pages']), (2, 2))
        self.assertEqual(len(out['items']), 2)
        # a refused connection (mocked: a closed loopback port costs seconds on Windows): named, nothing listed
        with mock.patch('socket.create_connection', side_effect=ConnectionRefusedError()):
            out = self.run_script()
        self.assertEqual((out['items'], out['error'], out['pages']), (None, 'ConnectionRefusedError', 0))

    def test_an_answer_of_another_shape_leaves_items_unset(self):
        for body in ([], {'items': {}}, {'next_page_id': None}):
            with self.subTest(body=body):
                self.server.body = body
                out = self.run_script()
                self.assertEqual((out['items'], out['status'], out['pages']), (None, 200, 1))

    def test_twenty_pages_at_most(self):
        self.server.pages = [[{'id': CID}]] * 25
        out = self.run_script()
        self.assertEqual((out['pages'], out['items']), (20, None))


class RealKeyReader(unittest.TestCase):
    """read_real_provider_key: the entry the broker reads, checked against the running broker's fingerprint."""

    def provider(self, entry=None, error=None):
        provider = mock.Mock()
        provider.get.side_effect = error or (lambda name: entry)
        return lambda: provider

    def test_reads_the_brokers_entry_and_checks_its_fingerprint(self):
        factory = self.provider(('anthropic', REAL))
        self.assertEqual(guest.read_real_provider_key(REAL_FP, factory), REAL)
        factory().get.assert_called_once_with(guest.inference_control().broker.ENTRY)

    def test_refusals_never_repeat_what_was_read(self):
        for factory, code in ((self.provider(None), 'holds no provider key'),
                              (self.provider(('anthropic', 7)), 'holds no provider key'),
                              (self.provider(('anthropic', REAL)), 'FINGERPRINT_MISMATCH'),
                              (self.provider(error=RuntimeError(REAL)), 'did not answer (RuntimeError)')):
            with self.subTest(code=code), self.assertRaises(guest.Refused) as cm:
                guest.read_real_provider_key('sha256:' + '0' * 16 if 'MISMATCH' in code else REAL_FP, factory)
            self.assertIn(code, str(cm.exception))
            self.assertNotIn(REAL, str(cm.exception))
            self.assertEqual(cm.exception.code, 'REAL_KEY')


class CommandLine(unittest.TestCase):
    """guest.py acp-qualification: the token and the synthetic key from standard input, never argv."""

    def run_main(self, argv, stdin_text):
        seen = {}

        def fake_run(ctx, name, token, prompt, model, key_mode, **kw):
            seen.update(token=token, prompt=prompt, model=model, key_mode=key_mode, **kw)
            return {'operation': 'acp-qualification', 'result': 'PASS'}
        stdin = io.StringIO(stdin_text)
        stdin.isatty = lambda: False
        with mock.patch.object(guest, 'Context', return_value=types.SimpleNamespace()), \
                mock.patch.object(guest, 'acp_qualification_run', side_effect=fake_run), \
                mock.patch('sys.stdin', stdin), mock.patch('sys.stdout', io.StringIO()) as out, \
                mock.patch('sys.stderr', io.StringIO()):
            rc = guest.main(['acp-qualification', '--profile', 'p', '--state-dir', 's', '--name', 'g1'] + argv)
        return rc, seen, out.getvalue()

    def test_token_and_synthetic_key_from_stdin(self):
        rc, seen, _ = self.run_main(['--attempt-token-stdin', '--prompt', 'single', '--acp-model', MODEL],
                                    TOKEN + '\n')
        self.assertEqual((rc, seen['token'], seen['key_mode'], seen['provider_key']), (0, TOKEN, 'off', None))
        rc, seen, _ = self.run_main(['--attempt-token-stdin', '--prompt', 'delegated', '--acp-model', MODEL,
                                     '--key-search', 'synthetic', f'--provider-key-fingerprint={SYNTHETIC_FP}'],
                                    TOKEN + '\n' + SYNTHETIC + '\n')
        self.assertEqual((rc, seen['provider_key'], seen['prompt']), (0, SYNTHETIC, 'delegated'))
        rc, seen, _ = self.run_main(['--attempt-token-stdin', '--prompt', 'single', '--acp-model', MODEL,
                                     '--key-search', 'real', '--real-key-act', 'OA-12 A1'], TOKEN + '\n')
        self.assertEqual((rc, seen['provider_key'], seen['real_key_act']), (0, None, 'OA-12 A1'))

    def test_refusals(self):
        rc, seen, out = self.run_main(['--prompt', 'single', '--acp-model', MODEL], TOKEN + '\n')
        self.assertEqual((rc, seen), (1, {}))
        self.assertIn('needs --attempt-token-stdin', out)
        rc, seen, out = self.run_main(['--attempt-token-stdin', '--prompt', 'single', '--acp-model', MODEL],
                                      'sk-ant-api03-' + 'x' * 40 + '\n')
        self.assertEqual((rc, seen), (1, {}))
        self.assertNotIn('sk-ant', out)
        rc, seen, out = self.run_main(['--attempt-token-stdin', '--prompt', 'single', '--acp-model', MODEL,
                                       '--key-search', 'synthetic', f'--provider-key-fingerprint={SYNTHETIC_FP}'],
                                      TOKEN + '\n' + REAL + '\n')
        self.assertEqual((rc, seen), (1, {}))
        self.assertNotIn(REAL, out)
        for argv in (['--attempt-token-stdin', '--acp-model', MODEL],
                     ['--attempt-token-stdin', '--prompt', 'any', '--acp-model', MODEL],
                     ['--attempt-token-stdin', '--prompt', 'single'],
                     ['--attempt-token-stdin', '--prompt', 'single', '--acp-model', MODEL, '--key-search', 'x']):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as cm:
                self.run_main(argv, TOKEN + '\n')
            self.assertEqual(cm.exception.code, 2)

    def test_exit_code_follows_the_result(self):
        with mock.patch.object(guest, 'Context', return_value=types.SimpleNamespace()), \
                mock.patch.object(guest, 'acp_qualification_run',
                                  return_value={'operation': 'acp-qualification', 'result': 'UNKNOWN'}), \
                mock.patch('sys.stdin', io.StringIO(TOKEN + '\n')), mock.patch('sys.stdout', io.StringIO()):
            self.assertEqual(guest.main(['acp-qualification', '--profile', 'p', '--state-dir', 's', '--name', 'g',
                                         '--attempt-token-stdin', '--prompt', 'single', '--acp-model', MODEL]), 1)


if __name__ == '__main__':
    unittest.main()
