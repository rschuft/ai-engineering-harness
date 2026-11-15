"""Tests for the prepared native qualification driver of plan leaf E-05.11 (tools/guest.py native-qualification;
NOT RUN live).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

stdlib unittest; no QEMU, no guest, no ssh, no tunnel, no network, no credential. The guest is replaced by fakes:
the dispatcher's sealed API channel (the outer server, the inner server's conversations, the event stream, the
containment collector's, the job environment probe's and the native attempt probe's output), the root facts, the
forward session, the tunnel's census and log, the guest-root vantage and the credential provider (an in-memory one
holding a synthetic native token built at run time). Shown: the decision rule's PASS (with the Owner's values) and
UNKNOWN (without them, the reason recorded); each judgement's FAIL or UNKNOWN on its own fact; each stop with the
run going on to the persisted-token search, the Owner-credential steps, the teardown and the outbound search; the
record never holds the token or an Owner value; the native attempt probe itself, run in this process over a
synthetic /proc and file tree, reports counts and never the token; the command line's refusals.
"""
from pathlib import Path
import base64
import contextlib
import copy
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
import tempfile
import types
import unittest
import zlib
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')
aq = module_code.load('test_acp_qualification_driver_fixtures', REPO / 'tools' / 'tests' / 'test_acp_qualification_driver.py')
NS = module_code.load('native_support_fixtures', REPO / 'integrations' / 'dispatch' / 'tests' / 'native_support.py')
tg, tcc = aq.tg, aq.tcc
CC = guest.containment()
NT = guest.native_token_module()
PROFILE = aq.PROFILE
RECORD = aq.RECORD
CID = guest.NATIVE_QUALIFICATION_CONVERSATION_ID
HEX = CID.replace('-', '')
TOKEN = NS.token('E-05.11 driver synthetic native token')
FP = NT.fingerprint(TOKEN)
OTHER = NS.token('another native token')
GITHUB = 'ghp_' + 'G' * 36                       # synthetic Owner values (never real)
LOGIN = 'sk-ant-' + 'oat01-' + 'L' * 60
CFG = '/workspace/conversations/' + HEX + '/acp/claude-code'
ORIGIN = 'api.anthropic.com:443'
NAMES = sorted(['CLAUDE_CODE_OAUTH_TOKEN', 'HTTPS_PROXY', 'CLAUDE_CODE_PROXY_RESOLVES_HOSTS',
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', 'CLAUDE_CONFIG_DIR', 'OH_SECRET_KEY', 'PATH'])
DNS = '2026-11-15T05:24:05+0000 guest kernel: aieh-container-guard: IN=docker0 OUT= SRC=172.17.0.2 DST=172.17.0.1 LEN=60 PROTO=UDP SPT=40001 DPT=53 LEN=40'
NATIVE_SHAPED = {'CLAUDE_CODE_OAUTH_TOKEN': {'token': True, 'provider_key': False}}


def process(pid, role, argv, started=1005.0, names=NAMES, **kw):
    return dict({'pid': pid, 'role': role, 'exe': '/x/' + role, 'started': started, 'argv': argv, 'names': names,
                 'config_dir': CFG, 'proxy_is_endpoint': True, 'switches_declared': True}, **kw)


def start_data():
    return {'mode': 'start', 'container_started': 1000.0, 'config_dirs': [CFG], 'config_exists': True,
            'processes': [process(20, 'adapter', ['node', '/acp-node/bin/claude-agent-acp']),
                          process(21, 'cli', ['/x/claude', '--output-format', 'stream-json', '--model', 'sonnet'],
                                  started=1006.0)],
            'config_listing': [{'path': '.claude.json', 'dir': False, 'size': 10, 'mtime': 1007.0, 'ctime': 1007.0}]}


def after_data():
    return dict(start_data(), mode='after', owner_files_found=[CFG + '/.claude.json'], changed_files=12,
                token_found_in_environment=True, token_fingerprint=FP,
                search={'verdict': 'not-found', 'bytes_searched': 1000, 'controls': {'valid': True, 'cases': 40},
                        'surfaces': [{'label': 'configuration directory', 'complete': True, 'found': 0}]},
                transcript={'files': 1, 'records': 6, 'models': {'claude-sonnet-5': 2}, 'sidechain_records': 0,
                            'subagent_files': 0, 'occurrences': {'token': 0, 'endpoint': 0, 'switch': 0, 'marker': 0}})


def capture(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    data = buf.getvalue()
    return {'b64': base64.b64encode(data).decode('ascii'), 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'truncated': False}


def log_line(**entry):
    return json.dumps(entry)


class FakeGuest:
    """The outer server, the conversation's inner server and its container, as the sealed channel and the facts see
    them; each attribute one fact a test changes."""

    def __init__(self, test):
        self.test = test
        self.created = self.sent = False
        self.calls, self.bodies = [], {}
        self.statuses = ['running', 'finished']
        self.during = aq.snapshot(rows=[aq.TO_ENDPOINT])
        self.after = aq.snapshot(rows=[aq.TO_ENDPOINT])
        self.env = aq.job_env(NATIVE_SHAPED, names=('CLAUDE_CODE_OAUTH_TOKEN',))
        self.env_specs = []
        self.events = [[{'id': 'e1', 'kind': 'MessageEvent', 'source': 'user'},
                        {'id': 'e2', 'kind': guest.ACP_TOOL_CALL_KIND, 'title': 'Task'}],
                       [{'id': 'e3', 'kind': 'MessageEvent', 'source': 'agent'}]]
        self.inner = [{'id': CID, 'parent_conversation_id': None}]
        self.create_status = 201
        self.agent = {'kind': 'ACPAgent', 'acp_server': 'claude-code', 'acp_model': 'claude-sonnet-5'}
        self.echo_token = False
        self.probe = {'start': start_data(), 'after': after_data(),
                      'capture': {'mode': 'capture', 'capture': capture({'proc/20/environ': b'PATH=/usr/bin\0'})}}
        self.probe_specs = []
        self.rejects = 3
        self.guard_log = ['2026-11-15T05:00:00+0000 guest kernel: aieh-container-guard: IN=docker0 SRC=172.17.0.2 '
                          'DST=172.17.0.1 PROTO=UDP SPT=1 DPT=53'] * 3
        self.egress = self.egress6 = 0
        self.lazy = True                 # the provider starts at the first prompt (live run 2)
        self.seals, self.nonces = [], []

    def facts(self):
        container = tg.conversation_container(hex_id=HEX)
        container['State']['Pid'] = tcc.HOST_BASE + 1
        return {'containers': [container] if self.created else [], 'server_user': dict(aq.SERVER_USER),
                'admission': {'iptables': [{'target': 'REJECT', 'packets': self.rejects}],
                              'log': {'count': len(self.guard_log), 'tail': list(self.guard_log[-20:])},
                              'egress': {'iptables': [{'target': 'REJECT', 'packets': self.egress}],
                                         'ip6tables': [{'target': 'REJECT', 'packets': self.egress6}]}}}

    def refuse(self, *lines):
        """The container guard refuses one packet per kernel log line (and counts it)."""
        self.guard_log += list(lines)
        self.rejects += len(lines)

    def answer(self, method, path, body):
        self.calls.append((method, path))
        self.bodies[(method, path)] = body
        base = f'/api/conversations/{CID}'
        if method == 'GET' and path == '/api/conversations/count':
            return 200, 1 if self.created else 0
        if method == 'POST' and path == '/api/conversations':
            self.test.assertEqual(body['secrets']['CLAUDE_CODE_OAUTH_TOKEN']['value'], TOKEN)
            self.test.assertEqual(sorted(body['secrets']), sorted(guest.native_qualification().secrets_check.NATIVE_NAMES))
            self.created = 200 <= self.create_status < 300
            out = {'id': CID, 'agent': self.agent}
            if self.echo_token:
                out['echo'] = TOKEN
            return self.create_status, out
        if method == 'GET' and path == '/api/conversations/search?limit=100':
            return 200, {'items': [{'id': CID}] if self.created else [], 'next_page_id': None}
        if method == 'POST' and path == base + '/events':
            self.test.assertIn(body['content'][0]['text'], guest.NATIVE_QUALIFICATION_PROMPTS.values())
            self.sent = True
            return 200, {'success': True}
        if method == 'GET' and path == base:
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return 200, {'id': CID, 'execution_status': status, 'agent': self.agent}
        if method == 'GET' and path.startswith(base + '/events/search?limit=100'):
            index = int(path.split('page_id=p')[1]) if 'page_id=' in path else 0
            nxt = f'p{index + 1}' if index + 1 < len(self.events) else None
            return 200, {'items': self.events[index], 'next_page_id': nxt}
        if method == 'POST' and path == base + '/bash/execute_bash_command':
            return 200, {'exit_code': 0, 'stdout': self.run_script(body['command'])}
        if method == 'DELETE' and path == base:
            self.created = False
            return 200, {'success': True}
        raise AssertionError(f'unexpected request {method} {path}')

    def run_script(self, command):
        z = re.match(r'echo ([A-Za-z0-9+/=]+) \| base64 -d \| python3 -c .*? > /tmp/aieh-job.py && '
                     r'python3 /tmp/aieh-job.py ([A-Za-z0-9+/=]+);', command)
        if z:
            script = zlib.decompress(base64.b64decode(z.group(1))).decode('utf-8')
            spec = json.loads(zlib.decompress(base64.b64decode(z.group(2))))
            self.test.assertEqual(script, guest.NATIVE_ATTEMPT_PROBE)
            self.probe_specs.append(spec)
            self.test.assertEqual('search_source' in spec, spec['mode'] == 'after')
            data = self.probe[spec['mode']]
            if spec['mode'] == 'start' and self.lazy and not self.sent:
                data = dict(data, processes=[], config_dirs=[], config_listing=[], config_exists=False)
            return guest.JOB_MARKER + json.dumps(data) + '\n'
        match = re.match(r'echo ([A-Za-z0-9+/=]+) \| base64 -d > /tmp/aieh-job.py && python3 /tmp/aieh-job.py '
                         r'([^\s;]+)', command)
        script = base64.b64decode(match.group(1)).decode('utf-8')
        if script.startswith('"""The containment observation'):
            snap = self.after if self.test.turn_done else self.during
            return CC.MARKER + json.dumps(snap) + '\n'
        if script == guest.ACP_INNER_CONVERSATIONS:
            return guest.JOB_MARKER + json.dumps({'key_present': True, 'status': 200, 'pages': 1,
                                                  'key_occurrences': 0, 'items': self.inner}) + '\n'
        if script == guest.JOB_ENV_PROBE:
            self.env_specs.append(json.loads(base64.b64decode(match.group(2))))
            return guest.JOB_MARKER + json.dumps(self.env) + '\n'
        raise AssertionError('an unexpected script')

    def api(self, requests, timeout=900, secret=None):
        # every call is sealed: with the native token once it is held, before that with a fresh nonce (review S1)
        self.test.assertRegex(secret, r'^[A-Za-z0-9_-]{16,512}$')
        (request,) = requests
        self.seals.append((request['method'], request['path'], secret == TOKEN))
        if secret != TOKEN:
            self.nonces.append(secret)
        if request['method'] == 'POST' and request['path'] == '/api/conversations':
            self.test.assertEqual(secret, TOKEN)
        status, body = self.answer(request['method'], request['path'], request.get('json'))
        text = json.dumps(body)
        sealed = text.count(secret)
        body = json.loads(text.replace(secret, '<sealed secret redacted>'))
        return {'responses': [{'status': status, 'body': body}], 'session_key_occurrences': 0,
                'sealed_occurrences': sealed}


class FakeTunnel:
    def __init__(self, guest_):
        self.guest = guest_
        self.census_verdicts = ['PASS', 'PASS']
        self.name, self.name_after = 'tunnel-20261115T000000Z-0123abcd.jsonl', None
        self.base = [log_line(event='tunnel-start')]
        self.run_lines = [log_line(event='upstream-connect', conn=7, target=ORIGIN, peer={'address': '160.79.104.10',
                                                                                           'port': 443}),
                          log_line(event='connection', conn=7, target=ORIGIN, decision='admitted', reason=None,
                                   end='client-closed', bytes_up=5000, bytes_down=9000)]
        self.census_calls = []
        self.late_lines = []          # lines the tunnel logs after step (10)'s read, seen by (12a)

    def census(self):
        verdict = self.census_verdicts.pop(0)
        self.census_calls.append((list(self.guest.calls), verdict))
        return {'format': 'aieh-provider-tunnel-census/1', 'verdict': verdict, 'violations': []}

    def log_lines(self):
        torn_down = ('DELETE', f'/api/conversations/{CID}') in self.guest.calls
        lines = self.base + (self.run_lines if self.guest.sent else []) + (self.late_lines if torn_down else [])
        return (self.name_after or self.name) if self.guest.sent else self.name, lines


class DriverRun(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix='aieh-nq-'))
        self.addCleanup(tg.remove_tree, self.state)
        self.guest = FakeGuest(self)
        self.tunnel = FakeTunnel(self.guest)
        self.provider = NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, TOKEN)})
        self.session = {'ports': {'tunnel': '127.0.0.1:18433'}}
        self.turn_done = False

    def wait(self, fetch, done, ceiling):
        value = fetch()
        for _ in range(20):
            if done(value):
                break
            value = fetch()
        self.turn_done = done(value)
        return value, done(value)

    def run_driver(self, owner=True, profile=PROFILE, **kw):
        written = {}
        ctx = types.SimpleNamespace(profile=profile, repo=REPO, instance_dir=lambda n: self.state / n)
        args = dict(channels=lambda rec: (self.guest.api, self.guest.facts), provider=self.provider,
                    forward=types.SimpleNamespace(status=lambda: {'held': True, 'session': self.session}),
                    tunnel=self.tunnel, host_vantage=lambda rec, pid: aq.host_snapshot(), wait=self.wait)
        if owner:
            args.update(owner_values={'cred-owner-github': GITHUB, 'cred-owner-provider-login': LOGIN},
                        owner_value_act='OA-test owner values')
        args.update(kw)

        def no_wait(seconds):
            raise AssertionError('the facts limiter waited')
        with mock.patch.object(guest, 'running_instance', side_effect=lambda c, n: (None, RECORD)), \
                mock.patch.object(guest, 'write_record', side_effect=lambda i, op, out: written.update({op: out})), \
                mock.patch.object(guest, 'FACTS_WAIT', no_wait), mock.patch.object(guest, 'log'):
            out = guest.native_qualification_run(ctx, 'g1', 'single', 'OA-31 (b) (f)', **args)
        text = json.dumps(written, default=str)
        for secret in (TOKEN, TOKEN[len(NS.PREFIX):], GITHUB, LOGIN):
            self.assertNotIn(secret, text)
        if written:
            self.assertEqual(written['native-qualification']['result'], out['result'])
        return out

    def step(self, out, number):
        found = [s for s in out['steps'] if s['step'].startswith(f'({number})')]
        self.assertEqual(len(found), 1, number)
        return found[0]

    def verdicts(self, out):
        return {s['step'].split(' ', 1)[0]: s['verdict'] for s in out['steps']}

    def stops(self, out):
        return [s['stop'] for s in out['stop_conditions']]

    def test_the_rule_passes_on_a_guest_that_holds_it(self):
        out = self.run_driver()
        self.assertEqual(out['result'], 'PASS', [(s['step'], s['verdict'], s.get('detail')) for s in out['steps']])
        self.assertFalse(self.step(out, 3)['detail']['provider_running'])      # the lazy start (live run 2)
        self.assertEqual(self.step(out, 1)['detail']['guards']['log_lines'][0],          # pre-create attribution
                         {'proto': 'UDP', 'dst': '172.17.0.1', 'dport': 53})
        self.assertEqual(list(self.verdicts(out)), ['(1)', '(1a)', '(1b)', '(2)', '(3)', '(4)', '(4a)', '(5)', '(6)', '(7)',
                                                    '(8)', '(9)', '(10)', '(10a)', '(11)', '(11a)', '(11b)', '(11c)',
                                                    '(11d)', '(12)', '(12a)', '(12b)', '(13)'])
        (before, _), (after, _) = self.tunnel.census_calls
        self.assertNotIn(('POST', '/api/conversations'), before)            # before the create: no model call
        self.assertIn(('POST', f'/api/conversations/{CID}/events'), after)
        self.assertEqual(self.provider.reads, [NT.ENTRY])                     # the dispatcher's read, once
        create = self.guest.seals.index(('POST', '/api/conversations', True))
        self.assertEqual(self.guest.seals[0], ('GET', '/api/conversations/count', False))    # a nonce before (1b)
        self.assertTrue(all(sealed for _, _, sealed in self.guest.seals[create:]))
        self.assertEqual(self.step(out, '12a')['verdict'], 'PASS')
        [entry] = [c for c in out['transport_calls'] if c['path'] == '/api/conversations']
        self.assertIsNone(entry['body_sha256'])                                # review N4: no digest of the body
        self.assertEqual(self.step(out, 2)['detail']['fixture_sha256'], guest.native_qualification().FIXTURE_SHA256)
        self.assertEqual(out['native_token']['fingerprint'], FP)
        self.assertEqual(self.step(out, 10)['detail']['admitted_to_origin'], 1)
        self.assertEqual(self.step(out, 13)['detail']['verdict'], 'not-found')
        self.assertEqual(self.guest.env_specs[0]['attempt_token']['names'], ['CLAUDE_CODE_OAUTH_TOKEN'])
        self.assertEqual([s['mode'] for s in self.guest.probe_specs], ['start', 'start', 'after', 'capture'])      # (3) and (4a)
        self.assertEqual(self.step(out, 11)['detail']['transcript']['sidechain_records'], 0)

    def test_a_fresh_nonce_seals_every_call_before_the_token(self):
        self.run_driver()
        first = list(self.guest.nonces)
        self.setUp()
        self.run_driver()
        self.assertEqual((len(first), len(self.guest.nonces)), (1, 1))
        self.assertNotEqual(first, self.guest.nonces)

    def test_without_the_owners_values_that_part_is_unknown_with_its_reason(self):
        out = self.run_driver(owner=False)
        self.assertEqual(out['result'], 'UNKNOWN')
        unknown = [k for k, v in self.verdicts(out).items() if v != 'PASS']
        self.assertEqual(unknown, ['(11d)'])
        self.assertIn('credential access the Owner has not granted', self.step(out, '11d')['detail']['by_value']['reason'])
        self.assertNotIn('capture', [s['mode'] for s in self.guest.probe_specs])

    def test_preconditions(self):
        """Review S1 (P3): a precondition that fails reads no entry, makes no census and seals no call with a token."""
        for change, check in (
                (lambda: self.session.update(ports={'broker': '127.0.0.1:18432'}), 'the forward targets the provider tunnel'),
                (lambda: setattr(self, 'session', None), 'the forward targets the provider tunnel'),
                (lambda: setattr(self.guest, 'created', True), 'the outer server holds no conversation')):
            with self.subTest(check=check):
                self.setUp()
                change()
                out = self.run_driver(owner=False)
                self.assertEqual(self.step(out, 1)['verdict'], 'FAIL')
                self.assertFalse(self.step(out, 1)['detail']['checks'][check])
                self.assertNotIn(('POST', '/api/conversations'), self.guest.calls)
                self.assertEqual(self.tunnel.census_calls, [])
                self.assertEqual(self.provider.reads, [])
                self.assertFalse(any(sealed for _, _, sealed in self.guest.seals))
        self.setUp()
        out = self.run_driver(owner=False, forward=types.SimpleNamespace(status=lambda: {'held': False, 'session': None}))
        self.assertEqual((self.provider.reads, self.guest.seals), ([], []))   # P3: not even the count is asked

    def test_the_token_is_read_after_the_census_and_only_then(self):
        for provider, code in ((NS.ObservedProvider({}), 'NATIVE_TOKEN_MISSING'),
                               (NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, 'sk-ant-api03-' + 'k' * 50)}),
                                'NATIVE_TOKEN_NOT_SHAPED')):
            with self.subTest(code=code):
                self.setUp()
                self.provider = provider
                out = self.run_driver(owner=False)
                self.assertEqual((self.step(out, '1b')['verdict'], self.step(out, '1b')['detail']['refused']),
                                 ('FAIL', code))
                self.assertEqual(len(self.tunnel.census_calls), 1)            # the census came first
                self.assertNotIn(('POST', '/api/conversations'), self.guest.calls)
        self.setUp()
        self.tunnel.census_verdicts = ['FAIL']
        self.run_driver(owner=False)
        self.assertEqual(self.provider.reads, [])                             # no read after a failed census

    def test_the_census_before_the_create_is_a_stop_and_no_model_call(self):
        self.tunnel.census_verdicts = ['UNKNOWN']
        out = self.run_driver()
        self.assertEqual(out['result'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['census-before'], self.stops(out))
        self.assertNotIn(('POST', '/api/conversations'), self.guest.calls)
        self.assertEqual(self.provider.reads, [])                          # no token read (review S1)
        self.assertEqual(self.step(out, 13)['skipped'], 'no token was read')

    def test_an_unreadable_tunnel_log_before_the_create_creates_nothing(self):
        def unreadable():
            raise OSError('the log is not readable')
        self.tunnel.log_lines = unreadable
        out = self.run_driver()
        self.assertEqual(self.step(out, '1a')['verdict'], 'UNKNOWN')
        self.assertNotIn(('POST', '/api/conversations'), self.guest.calls)
        self.assertEqual(self.provider.reads, [])                 # no token without the census and its log mark

    def test_an_admission_refusal_sends_nothing(self):
        with mock.patch.object(guest.native_qualification(), 'FIXTURE_SHA256', '0' * 64):
            out = self.run_driver()
        self.assertEqual(self.step(out, 2)['verdict'], 'FAIL')
        self.assertEqual(self.step(out, 2)['detail']['admission']['code'], 'FIXTURE_DRIFTED')
        self.assertNotIn(('POST', '/api/conversations'), self.guest.calls)

    def test_the_answers_model_and_server(self):
        self.guest.agent = dict(self.guest.agent, acp_model='claude-opus-5')
        self.assertEqual(self.step(self.run_driver(), 2)['verdict'], 'FAIL')

    def test_the_providers_start(self):
        cases = {
            'an entry older than the provider': lambda d: d['config_listing'].append(
                {'path': 'settings.json', 'dir': False, 'size': 5, 'mtime': 990.0, 'ctime': 990.0}),
            'bare mode': lambda d: d['processes'][1]['argv'].append('--bare'),
            'an MCP configuration': lambda d: d['processes'][1]['argv'].append('--mcp-config={}'),
            'a second authentication method': lambda d: d['processes'][0].update(
                names=NAMES + ['ANTHROPIC_API_KEY']),
            'CLAUDE_CODE_SIMPLE': lambda d: d['processes'][1].update(names=NAMES + ['CLAUDE_CODE_SIMPLE']),
            'two configuration directories': lambda d: (d['processes'][1].update(config_dir='/tmp/x'),
                                                        d.update(config_dirs=[CFG, '/tmp/x'])),
            'another directory': lambda d: (d['processes'][0].update(config_dir='/var/lib/other/.claude'),
                                            d['processes'][1].update(config_dir='/var/lib/other/.claude'),
                                            d.update(config_dirs=['/var/lib/other/.claude'])),
            'the proxy': lambda d: d['processes'][0].update(proxy_is_endpoint=False),
            'the CLI\'s proxy (review N8)': lambda d: d['processes'][1].update(proxy_is_endpoint=False),
            'a CLI switch (review N8)': lambda d: d['processes'][1].update(switches_declared=False),
            'a switch': lambda d: d['processes'][0].update(switches_declared=False),
            'a missing name': lambda d: d['processes'][0].update(names=[n for n in NAMES if n != 'HTTPS_PROXY']),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                data = start_data()
                change(data)
                self.assertEqual(guest.native_start_verdict(data, guest.native_qualification().secrets_check.NATIVE_NAMES)[0],
                                 'FAIL')
        self.assertEqual(guest.native_start_verdict(start_data(), guest.native_qualification().secrets_check.NATIVE_NAMES)[0],
                         'PASS')
        tool = start_data()      # a tool's process (git --bare) is not the provider's command line
        tool['processes'].append(process(40, 'descendant', ['git', 'init', '--bare'], started=1009.0))
        self.assertEqual(guest.native_start_verdict(tool, guest.native_qualification().secrets_check.NATIVE_NAMES)[0],
                         'PASS')
        no_adapter = start_data()
        no_adapter['processes'] = no_adapter['processes'][1:]
        self.assertEqual(guest.native_start_verdict(no_adapter, ())[0], 'UNKNOWN')
        self.guest.probe['start']['processes'][1]['argv'].append('--bare')
        out = self.run_driver()
        self.assertEqual((self.step(out, 3)['verdict'], self.step(out, '4a')['verdict']), ('PASS', 'FAIL'))
        self.assertEqual(self.step(out, '4a')['detail']['forbidden_flags'], ['--bare'])

    def test_the_start_is_judged_at_the_lazy_start(self):
        """Live run 2 (F2): no provider before the prompt is recorded at (3); (4a) judges it once it runs; a provider
        never seen is UNKNOWN with the probe's output kept."""
        out = self.run_driver()
        self.assertEqual((self.step(out, 3)['verdict'], self.step(out, '4a')['verdict']), ('PASS', 'PASS'))
        self.assertTrue(self.step(out, '4a')['detail']['seen_within_ceiling'])
        self.setUp()
        self.guest.probe['start'] = dict(start_data(), processes=[])
        seen = []

        def never(fetch, done, ceiling):
            value = fetch()
            seen.append(ceiling)
            return value, done(value)
        out = self.run_driver(start_wait=never)
        self.assertEqual(self.step(out, '4a')['verdict'], 'UNKNOWN')
        self.assertEqual(self.step(out, '4a')['detail']['processes'], [])
        self.assertEqual(seen, [guest.NATIVE_START_CEILING_S])

    def test_another_credential_in_an_environment_is_a_stop(self):
        self.guest.env = aq.job_env({'CLAUDE_CODE_OAUTH_TOKEN': {'token': False, 'provider_key': True}},
                                    names=('CLAUDE_CODE_OAUTH_TOKEN',))
        out = self.run_driver()
        self.assertIn(guest.NATIVE_STOPS['other-credential'], self.stops(out))
        self.assertEqual(self.step(out, 12)['verdict'], 'PASS')            # teardown still runs

    def test_an_owner_credential_name_is_a_stop(self):
        self.guest.env = aq.job_env(NATIVE_SHAPED, names=('CLAUDE_CODE_OAUTH_TOKEN', 'GITHUB_TOKEN'))
        out = self.run_driver()
        self.assertEqual(self.step(out, '11c')['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['owner'], self.stops(out))

    def test_a_direct_connection_attempt_is_a_stop(self):
        """Live run 2 (F1 a), superseding B1: the egress guard's refusal counters rising during the turn, and a
        SYN_SENT row to any destination but the tunnel endpoint, are each a stop."""
        orig = self.guest.facts

        def facts():
            if self.guest.sent:
                self.guest.egress = 2
            return orig()
        self.guest.facts = facts
        out = self.run_driver()
        self.assertEqual((out['result'], self.step(out, 10)['verdict'], self.step(out, '12b')['verdict']),
                         ('FAIL', 'FAIL', 'FAIL'))
        self.assertIn(guest.NATIVE_STOPS['direct'], self.stops(out))
        self.assertEqual(sorted(s.get('window') for s in out['stop_conditions'] if s['stop'] == guest.NATIVE_STOPS['direct']),
                         ['preconditions to teardown', 'the turn'])           # (10)'s view and (12b)'s
        self.setUp()
        syn = tcc.tcp_row('020011AC:C352', '01010101:01BB', '02', 6004)       # SYN_SENT to 1.1.1.1:443
        self.guest.during = aq.snapshot(rows=[aq.TO_ENDPOINT, syn])
        out = self.run_driver()
        self.assertEqual(self.step(out, 5)['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['direct'], self.stops(out))
        self.setUp()
        self.guest.rejects = 3          # unchanged counters: PASS (the control)
        self.assertEqual(self.step(self.run_driver(), 10)['verdict'], 'PASS')

    def test_the_guard_window_spans_start_up_to_teardown(self):
        """Live run 2 (F1): the container guard's refusals during the container's start-up attributed from its log:
        19 name lookups to 172.17.0.1:53 (run 2's shape) are counted, not a stop; a refusal to another port of the
        guest is the stop 'guest'; refusals beyond the logged lines are UNKNOWN; the egress guard of both families
        judges a direct connection leaving the container."""
        orig, done = self.guest.facts, {'start-up': False}

        def facts(*lines):
            def call():
                if self.guest.created and not done['start-up']:
                    done['start-up'] = True
                    self.guest.refuse(*lines)
                return orig()
            return call
        self.guest.facts = facts(*[DNS] * 19)
        out = self.run_driver()
        window = self.step(out, '12b')
        self.assertEqual((window['verdict'], window['detail']['name_lookups'], window['detail']['container_rise']),
                         ('PASS', 19, 19))
        self.assertNotIn('a refused', ' '.join(self.stops(out)))
        self.assertEqual(out['result'], 'PASS')
        for line, verdict, stop in ((DNS.replace('DPT=53', 'DPT=22').replace('UDP', 'TCP'), 'FAIL', 'guest'),
                                    (DNS.replace('DST=172.17.0.1', 'DST=172.17.0.3'), 'FAIL', 'guest')):
            with self.subTest(line=line[-40:]):
                self.setUp()
                orig, done = self.guest.facts, {'start-up': False}
                self.guest.facts = facts(DNS, line)
                out = self.run_driver()
                self.assertEqual(self.step(out, '12b')['verdict'], verdict)
                self.assertIn(guest.NATIVE_STOPS[stop], self.stops(out))
                self.assertNotIn('SPT', json.dumps(self.step(out, '12b')['detail']))   # proto, dst, port only
        self.setUp()
        orig, done = self.guest.facts, {'start-up': False}

        def unlogged():
            if self.guest.created and not done['start-up']:
                done['start-up'] = True
                self.guest.rejects += 5                          # beyond the LOG rule's rate limit: no lines
            return orig()
        self.guest.facts = unlogged
        out = self.run_driver()
        self.assertEqual((self.step(out, '12b')['verdict'], self.step(out, '12b')['detail']['unattributed']),
                         ('UNKNOWN', 5))
        self.setUp()
        orig = self.guest.facts

        def egress6():
            if self.guest.created:
                self.guest.egress6 = 1                           # N-a: the ip6tables rows count too
            return orig()
        self.guest.facts = egress6
        out = self.run_driver()
        self.assertEqual(self.step(out, '12b')['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['direct'], self.stops(out))

    def test_the_guard_window_in_isolation(self):
        snap = lambda c, log, e=0: {'container_rejects': c, 'log_count': len(log),
                                    'log_lines': [guest.guard_log_line(l) for l in log], 'egress_rejects': e}
        lookup = ('172.17.0.1', 53)
        self.assertEqual(guest.native_guard_window(snap(1, [DNS]), snap(20, [DNS] * 20), lookup)[0], 'PASS')
        self.assertEqual(guest.native_guard_window(snap(1, [DNS]), snap(1, [DNS], e=1), lookup)[2], ['direct'])
        self.assertEqual(guest.native_guard_window(snap(None, []), snap(1, []), lookup)[0], 'UNKNOWN')
        self.assertEqual(guest.native_guard_window(snap(1, []), snap(1, [], e=None), lookup)[0], 'UNKNOWN')
        many = [DNS] * 30                                        # more new lines than the tail of 20 keeps
        v, detail, _ = guest.native_guard_window(snap(0, []), dict(snap(30, many), log_lines=snap(30, many)['log_lines'][-20:]),
                                                 lookup)
        self.assertEqual((v, detail['unattributed'], detail['name_lookups']), ('UNKNOWN', 10, 20))
        self.assertEqual(guest.guard_log_line(DNS), {'proto': 'UDP', 'dst': '172.17.0.1', 'dport': 53})
        self.assertEqual(guest.guard_log_line('PROTO=ICMP DST=172.17.0.1 TYPE=8'),
                         {'proto': 'ICMP', 'dst': '172.17.0.1', 'dport': None})
        self.assertEqual(guest.native_egress_rejects({'admission': {'egress': {
            'iptables': [{'target': 'REJECT', 'packets': 2}], 'ip6tables': [{'target': 'REJECT', 'packets': 1}]}}}), 3)
        self.assertIsNone(guest.native_egress_rejects({'admission': {}}))

    def test_the_guard_counters_of_both_families(self):
        rows = lambda *packets: [{'target': 'REJECT', 'packets': n} for n in packets]
        self.assertEqual(guest.native_guard_rejects({'admission': {'iptables': rows(3, 4)}}), 7)
        self.assertEqual(guest.native_guard_rejects({'admission': {'iptables': rows(3), 'ip6tables': rows(2)}}), 5)
        self.assertEqual(guest.native_guard_rejects({'admission': {'iptables': rows(3) + [
            {'target': 'ACCEPT', 'packets': 9}]}}), 3)
        for report in ({'admission': {}}, {'admission': {'iptables': rows(1), 'ip6tables': 'x'}}, {}, None):
            self.assertIsNone(guest.native_guard_rejects(report))

    def test_no_sent_turn_leaves_the_whole_run_log_unknown(self):
        """Review N-b (D7): with no prompt sent, (12a) is not reached (UNKNOWN), never a FAIL for no connection."""
        answer = self.guest.answer

        def refused(method, path, body):
            if method == 'POST' and path == f'/api/conversations/{CID}/events':
                self.guest.calls.append((method, path))
                return 500, {'detail': 'refused'}
            return answer(method, path, body)
        self.guest.answer = refused
        out = self.run_driver(owner=False)
        self.assertEqual((self.step(out, 4)['verdict'], self.step(out, '12a')['verdict']), ('FAIL', 'UNKNOWN'))
        self.assertIn('not reached', self.step(out, '12a')['skipped'])
        self.assertEqual(self.step(out, 12)['verdict'], 'PASS')

    def test_a_lost_or_refused_create_answer_still_tears_down_and_searches(self):
        """Review S2 (P4): the create marked sent before the call; a 504 after the conversation was made, or a lost
        answer, still leads to the teardown and the persisted-token search."""
        answer = self.guest.answer

        def lossy(method, path, body):
            if method == 'POST' and path == '/api/conversations':
                answer(method, path, body)
                self.guest.created = True
                return 504, {'detail': 'gateway timeout'}
            return answer(method, path, body)
        self.guest.answer = lossy
        out = self.run_driver()
        self.assertEqual(self.step(out, 2)['verdict'], 'FAIL')
        self.assertTrue(self.step(out, 2)['detail']['present'])
        self.assertIn(('DELETE', f'/api/conversations/{CID}'), self.guest.calls)
        self.assertFalse(self.guest.created)
        self.assertNotIn('skipped', self.step(out, 11))                         # the search ran
        self.setUp()

        def lost(method, path, body):
            if method == 'POST' and path == '/api/conversations':
                raise OSError('the answer was lost')
            return self.guest.__class__.answer(self.guest, method, path, body)
        self.guest.answer = lost
        out = self.run_driver()
        self.assertEqual(self.step(out, 2)['detail']['error'], 'OSError')
        self.assertFalse(self.step(out, 2)['detail']['present'])
        self.assertIn(('DELETE', f'/api/conversations/{CID}'), self.guest.calls)  # torn down all the same
        self.assertEqual(self.step(out, 12)['verdict'], 'PASS')                   # 404 and nothing left
        self.assertIn('skipped', self.step(out, 11))                              # nothing to search

    def test_an_interrupt_still_tears_down_and_drops_the_token(self):
        def interrupted(fetch, done, ceiling):
            raise KeyboardInterrupt
        with mock.patch.object(NT.NativeToken, 'drop', autospec=True, side_effect=NT.NativeToken.drop) as drop:
            with self.assertRaises(KeyboardInterrupt):
                self.run_driver(wait=interrupted)
        self.assertIn(('DELETE', f'/api/conversations/{CID}'), self.guest.calls)
        self.assertGreaterEqual(drop.call_count, 1)

    def test_a_token_in_the_runs_own_text_is_redacted_and_a_stop(self):
        """Review S3 (P10): the record is redacted once and written; the redaction is a stop."""
        lines = self.tunnel.log_lines

        def log_lines():
            if self.guest.sent:
                raise guest.Refused('TUNNEL', 'host-side text that happens to hold ' + TOKEN)
            return lines()
        self.tunnel.log_lines = log_lines
        out = self.run_driver()                    # run_driver asserts the written record holds no token
        self.assertEqual(out['result'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['redacted'], self.stops(out))
        self.assertGreaterEqual(out['native_token']['redacted_from_record'], 1)
        self.assertEqual(self.step(out, 12)['verdict'], 'PASS')                   # the teardown's status survives

    def test_the_tunnel_carrying_another_target_is_a_stop(self):
        """Review S6 (P2): PASS needs an admitted connection to the origin and no other target carried; the whole
        run's log is read again after the teardown."""
        self.tunnel.run_lines = [log_line(event='upstream-connect', conn=7, target='evil.example:443',
                                          peer={'address': '203.0.113.9', 'port': 443})]
        out = self.run_driver()
        self.assertEqual(self.step(out, 10)['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['other-target'], self.stops(out))
        self.setUp()
        self.tunnel.late_lines = [log_line(event='connection', conn=9, target=ORIGIN, decision='refused',
                                           reason='TUNNEL_ECH_REFUSED')]
        out = self.run_driver()
        self.assertEqual((self.step(out, 10)['verdict'], self.step(out, '12a')['verdict']), ('PASS', 'FAIL'))
        self.assertIn(guest.NATIVE_STOPS['hello'], self.stops(out))

    def test_an_unreadable_environment_in_the_lineage_is_unknown(self):
        """Review S4 (P7): unreadable in the provider's lineage, or a process the snapshot did not see: UNKNOWN; a
        process outside the lineage: recorded, not judged."""
        self.guest.env['process_environments']['99'] = {'unreadable': 'PermissionError'}
        out = self.run_driver()
        self.assertEqual(self.step(out, 6)['verdict'], 'UNKNOWN')
        self.assertEqual(self.step(out, 6)['detail']['unreadable_in_the_lineage'], ['99'])
        self.setUp()
        self.guest.env['process_environments']['1'] = {'unreadable': 'PermissionError'}
        out = self.run_driver()
        self.assertEqual((self.step(out, 6)['verdict'], self.step(out, 6)['detail']['unreadable']), ('PASS', ['1']))

    def test_another_credentials_value_under_any_name_is_a_stop(self):
        """Review S5: the probe's shape report of any value (never the value)."""
        self.guest.env['process_environments']['1']['other_value_shape'] = True
        out = self.run_driver()
        self.assertEqual(self.step(out, 6)['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['other-credential'], self.stops(out))
        self.assertIn('other_value_shape', self.guest.env_specs[0])

    def test_a_connection_elsewhere_is_a_stop(self):
        self.guest.during = aq.snapshot(rows=[aq.TO_ENDPOINT, aq.TO_ELSEWHERE])
        out = self.run_driver()
        self.assertEqual(out['result'], 'FAIL')
        self.assertTrue(any('the tunnel endpoint' in s for s in self.stops(out)))
        self.assertEqual(self.step(out, 11)['verdict'], 'PASS')            # the persisted-token search still runs

    def test_the_tunnels_log(self):
        def verdict(*extra, run=None):
            return guest.native_tunnel_verdict((self.tunnel.run_lines if run is None else run) + list(extra), ORIGIN)
        self.assertEqual(verdict()[0], 'PASS')
        refused = log_line(event='connection', conn=8, target='statsig.anthropic.com:443', decision='refused',
                           reason='TUNNEL_TARGET_REFUSED', end=None, bytes_up=0, bytes_down=0)
        v, detail, hello = verdict(refused)
        self.assertEqual((v, hello, detail['refused']), ('PASS', False, [{'target': 'statsig.anthropic.com:443',
                                                                          'reason': 'TUNNEL_TARGET_REFUSED'}]))
        for reason in guest.NATIVE_HELLO_REFUSALS:
            ech = log_line(event='connection', conn=9, target=ORIGIN, decision='refused', reason=reason)
            self.assertEqual(verdict(ech)[0::2], ('FAIL', True))
        self.assertEqual(verdict(run=[])[0], 'FAIL')                        # never through the tunnel
        carried = log_line(event='upstream-connect', conn=10, target='evil.example:443',
                           peer={'address': '203.0.113.9', 'port': 443})
        v, detail, _ = verdict(carried)                             # review S6: the origin admitted, and another
        self.assertEqual((v, detail['other_targets']), ('FAIL', ['evil.example:443']))
        admitted_other = log_line(event='connection', conn=11, target='evil.example:443', decision='admitted')
        self.assertEqual(verdict(admitted_other)[0], 'FAIL')
        self.assertEqual(verdict(log_line(event='refusals-suppressed', reason='x', count=4))[0], 'UNKNOWN')
        self.assertEqual(verdict('not json')[0], 'UNKNOWN')
        self.tunnel.run_lines.append(log_line(event='connection', conn=9, target=ORIGIN, decision='refused',
                                              reason='TUNNEL_ECH_REFUSED'))
        out = self.run_driver()
        self.assertIn(guest.NATIVE_STOPS['hello'], self.stops(out))

    def test_a_tunnel_restart_or_unread_counters_are_unknown(self):
        self.tunnel.name_after = 'tunnel-20261115T010000Z-89abcdef.jsonl'
        self.assertEqual(self.step(self.run_driver(), 10)['verdict'], 'UNKNOWN')
        self.setUp()
        self.guest.facts_orig = self.guest.facts
        self.guest.facts = lambda: dict(self.guest.facts_orig(), admission={})
        self.assertEqual(self.step(self.run_driver(), 10)['verdict'], 'UNKNOWN')

    def test_the_census_after_the_turn(self):
        self.tunnel.census_verdicts = ['PASS', 'FAIL']
        out = self.run_driver()
        self.assertIn(guest.NATIVE_STOPS['census-after'], self.stops(out))

    def test_the_persisted_token_search(self):
        self.guest.probe['after']['search'] = dict(self.guest.probe['after']['search'], verdict='found')
        out = self.run_driver()
        self.assertEqual(self.step(out, 11)['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['persisted'], self.stops(out))
        for change, want in ((lambda d: d.update(token_fingerprint=NT.fingerprint(OTHER)), 'FAIL'),
                             (lambda d: d['search'].update(controls={'valid': False}), 'UNKNOWN'),
                             (lambda d: d['search'].update(verdict='incomplete'), 'UNKNOWN'),
                             (lambda d: d.update(search={'withheld': True}), 'FAIL'),
                             (lambda d: d.update(owner_files_found=['/var/lib/other/.claude']), 'FAIL')):
            with self.subTest(want=want):
                self.setUp()
                change(self.guest.probe['after'])
                self.assertEqual(self.step(self.run_driver(), 11)['verdict'], want)

    def test_the_models(self):
        self.assertEqual(guest.native_model_verdict({'models': {'claude-sonnet-5': 3,
                                                                'claude-haiku-4-5-20251001': 1}})[0], 'PASS')
        self.assertEqual(guest.native_model_verdict({'models': {'claude-opus-5': 1}})[0], 'FAIL')     # no main loop
        self.assertEqual(guest.native_model_verdict({'models': {}})[0], 'UNKNOWN')
        self.assertEqual(guest.native_model_verdict(None)[0], 'UNKNOWN')
        self.assertEqual(guest.native_model_verdict({'models': {'claude-sonnet-5': 2, '<synthetic>': 1}})[0],
                         'FAIL')                  # review N1: kept, fails closed; attributed after a run
        self.guest.probe['after']['transcript']['models'] = {'claude-sonnet-5': 1, 'claude-sonnet-5-5': 1}
        out = self.run_driver()
        self.assertEqual(self.step(out, '11a')['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['model'], self.stops(out))
        record = (REPO / 'evidence' / 'D1-native-model-record.md').read_text(encoding='utf-8')
        for model in guest.NATIVE_MODELS_RECORDED:
            self.assertIn(f'`{model}`', record)

    def test_the_masking_check(self):
        occ = lambda **o: {'occurrences': dict({'token': 0, 'endpoint': 0, 'switch': 0, 'marker': 0}, **o)}
        self.assertEqual(guest.native_mask_verdict(0, occ())[0], 'PASS')
        self.assertEqual(guest.native_mask_verdict(2, occ(token=2))[0], 'PASS')
        self.assertEqual(guest.native_mask_verdict(5, occ(token=1))[0], 'UNKNOWN')        # review N3 (P9)
        self.assertEqual(guest.native_mask_verdict(1, occ(marker=1))[0], 'PASS')          # live run 2 (F3)
        self.assertEqual(guest.native_mask_verdict(2, occ(marker=1))[0], 'UNKNOWN')
        self.assertEqual(guest.native_mask_verdict(2, occ(marker=1, token=1))[0], 'PASS')
        self.assertEqual(guest.native_mask_verdict(1, occ(marker=1, switch=1))[0], 'FAIL')
        self.assertEqual(guest.native_mask_verdict(1, occ(endpoint=1))[0], 'FAIL')
        self.assertEqual(guest.native_mask_verdict(1, occ(switch=1, token=1))[0], 'FAIL')
        self.assertEqual(guest.native_mask_verdict(1, occ())[0], 'UNKNOWN')
        self.assertEqual(guest.native_mask_verdict(1, None)[0], 'UNKNOWN')
        self.assertEqual(guest.native_mask_verdict(None, occ())[0], 'UNKNOWN')
        self.guest.events[1].append({'id': 'e4', 'kind': 'MessageEvent', 'text': 'proxy ' + guest.NATIVE_MASK_MARKER})
        out = self.run_driver()
        self.assertEqual((self.step(out, 9)['detail']['mask_markers'], self.step(out, '11b')['verdict']), (1, 'UNKNOWN'))

    def test_the_delegation_mechanisms(self):
        self.guest.events[1].append({'id': 'e5', 'kind': 'ActionEvent', 'tool_name': 'start_child_conversation'})
        self.assertEqual(self.step(self.run_driver(), 9)['verdict'], 'FAIL')
        self.assertIn('isSidechain', guest.NATIVE_DELEGATION_SOURCE)

    def test_the_owner_value_search(self):
        self.guest.probe['capture']['capture'] = capture({'proc/20/environ': b'GITHUB_TOKEN=' + GITHUB.encode() + b'\0'})
        out = self.run_driver()
        self.assertEqual(self.step(out, '11d')['verdict'], 'FAIL')
        self.assertIn(guest.NATIVE_STOPS['owner'], self.stops(out))
        self.setUp()
        broken = capture({'proc/20/environ': b'PATH=/usr/bin\0'})
        broken['sha256'] = '0' * 64
        self.guest.probe['capture']['capture'] = broken
        self.assertEqual(self.step(self.run_driver(), '11d')['verdict'], 'UNKNOWN')

    def test_a_token_echoed_by_the_server_is_a_stop_and_never_recorded(self):
        self.guest.echo_token = True
        out = self.run_driver()
        self.assertTrue(any('echoed' in s for s in self.stops(out)))
        self.assertEqual(out['token_echoes'][0]['occurrences'], 1)

    def test_refusals_before_anything_runs(self):
        for kw, message in (({'prompt': 'free text'}, '--prompt'), ({'owner_act': ''}, '--owner-act'),
                            ({'owner_values': {'cred-owner-github': GITHUB}}, 'go together')):
            with self.subTest(message=message):
                args = dict(prompt='single', owner_act='OA-31 (b) (f)')
                args.update(kw)
                ctx = types.SimpleNamespace(profile=PROFILE, repo=REPO, instance_dir=lambda n: self.state / n)
                with self.assertRaises(guest.Refused) as caught:
                    guest.native_qualification_run(ctx, 'g1', args.pop('prompt'), args.pop('owner_act'), **args)
                self.assertIn(message, str(caught.exception))
        self.assertEqual(self.provider.reads, [])


class NativeTokenContract(unittest.TestCase):
    """The native token's name in the job contract (the profile's native_token_environment, declared as D-6 is)."""

    def test_the_name_only_for_an_opted_in_guest(self):
        self.assertEqual(guest.native_token_environment(PROFILE, RECORD), ('CLAUDE_CODE_OAUTH_TOKEN',))
        self.assertEqual(guest.native_token_environment(PROFILE, {'provisioning': {}}), ())
        bare = copy.deepcopy(PROFILE)
        del bare['network']['inference_composition']['native_token_environment']
        self.assertEqual(guest.native_token_environment(bare, RECORD), ())

    def test_the_spec_is_the_profiles_and_the_codes(self):
        spec = guest.native_token_spec(PROFILE, ('CLAUDE_CODE_OAUTH_TOKEN',))
        self.assertEqual((spec['token_shape'], spec['provider_key_shape']),
                         (NT.TOKEN_SHAPE.pattern, NT.OTHER_CREDENTIAL_SHAPE.pattern))

    def test_the_probe_reports_another_credentials_shape_never_the_value(self):
        d6 = aq.d6
        key = 'sk-ant-' + 'api03-' + hashlib.sha256(b'review S5').hexdigest() * 2      # built at run time
        spec = guest.native_token_spec(PROFILE, ('CLAUDE_CODE_OAUTH_TOKEN',))
        environs = {'20': b'CLAUDE_CODE_OAUTH_TOKEN=' + TOKEN.encode() + b'\0PATH=/bin\0',
                    '21': b'FOO=' + key.encode() + b'\0'}
        real = d6.run_env_probe.__globals__['json']
        original_dumps = real.dumps

        def with_shape(value, *args, **kwargs):
            if isinstance(value, dict) and value.get('attempt_token') == spec:
                value = dict(value, other_value_shape=NT.OTHER_CREDENTIAL_SHAPE.pattern)
            return original_dumps(value, *args, **kwargs)
        with mock.patch.object(real, 'dumps', with_shape):
            out = d6.run_env_probe(environs, spec)
        envs = out['process_environments']
        self.assertEqual((envs['20'].get('other_value_shape'), envs['21'].get('other_value_shape')), (False, True))
        self.assertNotIn(key, json.dumps(out))
        self.assertNotIn(TOKEN, json.dumps(out))

    def test_the_probe_and_the_verdict(self):
        d6 = aq.d6
        names = ('CLAUDE_CODE_OAUTH_TOKEN',)
        out = d6.run_env_probe({'1': b'OH_SECRET_KEY=x\0PATH=/bin\0',
                                '20': b'CLAUDE_CODE_OAUTH_TOKEN=' + TOKEN.encode() + b'\0',
                                '21': b'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-api03-' + b'k' * 60 + b'\0',
                                '22': b'CLAUDE_CODE_OAUTH_TOKEN=short\0'},
                               guest.native_token_spec(PROFILE, names))
        envs = out['process_environments']
        self.assertEqual(envs['20']['shapes'], {'CLAUDE_CODE_OAUTH_TOKEN': {'token': True, 'provider_key': False}})
        self.assertEqual(envs['21']['shapes'], {'CLAUDE_CODE_OAUTH_TOKEN': {'token': False, 'provider_key': True}})
        self.assertEqual(envs['22']['shapes'], {'CLAUDE_CODE_OAUTH_TOKEN': {'token': False, 'provider_key': False}})
        self.assertNotIn(TOKEN, json.dumps(out))
        admission = guest.attempt_token_admission(out, names)
        self.assertEqual((sorted(admission['admitted']), sorted(admission['provider_key']),
                          sorted(admission['not_token'])), (['20'], ['21'], ['22']))
        ok, problems, _ = guest.job_env_verdict(PROFILE, aq.SERVER_USER, aq.job_env(NATIVE_SHAPED, names=names), names)
        self.assertEqual((ok, problems), (True, []))
        ok, _, _ = guest.job_env_verdict(PROFILE, aq.SERVER_USER, aq.job_env(NATIVE_SHAPED, names=names), ())
        self.assertFalse(ok)                                                  # never admitted without the names


class TunnelView(unittest.TestCase):
    def test_a_tunnel_that_is_not_running_is_a_refusal_never_an_escape(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-nqt-'))
        self.addCleanup(tg.remove_tree, tmp)
        pt = guest.provider_tunnel()
        ctx = pt.Context(run_dir=lambda: tmp, logs=lambda: tmp, out=io.StringIO(), err=io.StringIO())
        with mock.patch.object(pt, 'managed_context', return_value=ctx):
            with self.assertRaises(guest.Refused) as caught:
                guest.NativeTunnelView().log_lines()
        self.assertEqual(caught.exception.code, 'TUNNEL')


class OwnerValues(unittest.TestCase):
    def stream(self, text):
        s = io.StringIO(text)
        s.isatty = lambda: False
        return s

    def test_read_from_standard_input_only_under_the_act(self):
        values = guest.read_owner_values(self.stream(f'cred-owner-github={GITHUB}\ncred-owner-provider-login={LOGIN}\n'),
                                         'OA-test act')
        self.assertEqual(values, {'cred-owner-github': GITHUB, 'cred-owner-provider-login': LOGIN})
        for text, act in ((f'cred-owner-github={GITHUB}\n', 'OA-test act'),
                          (f'cred-owner-github={GITHUB}\ncred-owner-github={GITHUB}\n', 'OA-test act'),
                          (f'other={GITHUB}\ncred-owner-provider-login={LOGIN}\n', 'OA-test act'),
                          (f'cred-owner-github=short\ncred-owner-provider-login={LOGIN}\n', 'OA-test act'),
                          (f'cred-owner-github={GITHUB}\ncred-owner-provider-login={LOGIN}\n', '')):
            with self.subTest(act=act):
                with self.assertRaises(guest.Refused) as caught:
                    guest.read_owner_values(self.stream(text), act)
                self.assertNotIn(GITHUB, str(caught.exception))
                self.assertNotIn(LOGIN, str(caught.exception))
        tty = self.stream('x')
        tty.isatty = lambda: True
        with self.assertRaises(guest.Refused):
            guest.read_owner_values(tty, 'OA-test act')

    def test_the_command_line_needs_both_or_neither(self):
        with mock.patch.object(guest, 'Context'), mock.patch.object(guest, 'native_qualification_run') as run:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = guest.main(['native-qualification', '--profile', 'p', '--state-dir', 's', '--name', 'n',
                                 '--prompt', 'single', '--owner-act', 'OA-31', '--owner-credential-stdin'])
        self.assertEqual(rc, 1)
        run.assert_not_called()


class AttemptProbe(unittest.TestCase):
    """NATIVE_ATTEMPT_PROBE itself, run in this process over a synthetic /proc and file tree."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-nqp-'))
        self.addCleanup(tg.remove_tree, self.tmp)
        proc, self.root, self.cfg = self.tmp / 'proc', self.tmp / 'root', self.tmp / 'cfg'
        for d in (proc / '1', proc / '20', proc / '21', proc / '30', self.root / 'workspace', self.cfg / 'projects' / 'p'):
            d.mkdir(parents=True)
        (proc / 'stat').write_text('cpu 1 2 3\nbtime 1000\n')
        env = {'PATH': '/usr/bin', 'CLAUDE_CODE_OAUTH_TOKEN': TOKEN, 'HTTPS_PROXY': 'http://172.17.0.1:8090',
               'CLAUDE_CODE_PROXY_RESOLVES_HOSTS': 'tRuE', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': 'tRuE',
               'CLAUDE_CONFIG_DIR': str(self.cfg)}
        environ = b''.join(f'{k}={v}'.encode() + b'\0' for k, v in env.items())
        for pid, argv in (('1', ['tini', '--', 'openhands-agent-server']), ('20', ['node', '/acp-node/bin/claude-agent-acp']),
                          ('21', ['/x/claude', '--model', 'sonnet', TOKEN]), ('30', ['bash'])):
            (proc / pid / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv) + b'\0')
            (proc / pid / 'environ').write_bytes(environ if pid in ('20', '21') else b'PATH=/usr/bin\0')
            (proc / pid / 'stat').write_text(f'{pid} (x) S ' + ' '.join(['0'] * 30))
        (self.cfg / '.claude.json').write_text('{}')
        records = [{'type': 'assistant', 'message': {'model': 'claude-sonnet-5'}},
                   {'type': 'assistant', 'isSidechain': True, 'message': {'model': 'claude-haiku-4-5-20251001'}},
                   {'type': 'user', 'message': {'content': 'http://172.17.0.1:8090'}}]
        (self.cfg / 'projects' / 'p' / 's.jsonl').write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        (self.root / 'workspace' / 'notes.txt').write_text('nothing here')
        self.proc = proc

    def run_probe(self, mode):
        spec = {'mode': mode, 'token_name': 'CLAUDE_CODE_OAUTH_TOKEN', 'proxy_name': 'HTTPS_PROXY',
                'endpoint': 'http://172.17.0.1:8090', 'switch': 'tRuE',
                'switches': ['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', 'CLAUDE_CODE_PROXY_RESOLVES_HOSTS'],
                'owner_files': list(guest.NATIVE_OWNER_FILE_NAMES), 'marker': guest.NATIVE_MASK_MARKER,
                'file_limit': guest.NATIVE_FILE_LIMIT, 'total_limit': guest.NATIVE_TOTAL_LIMIT,
                'capture_limit': guest.NATIVE_CAPTURE_LIMIT, 'proc': str(self.proc), 'root': str(self.root)}
        if mode == 'after':
            spec['search_source'] = (REPO / 'integrations' / 'inference' / 'inference_key_search.py').read_text('utf-8')
        arg = base64.b64encode(zlib.compress(json.dumps(spec).encode('utf-8'))).decode('ascii')
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['aieh-job.py', arg]), contextlib.redirect_stdout(out):
            exec(compile(guest.NATIVE_ATTEMPT_PROBE, 'aieh-job.py', 'exec'), {'__name__': '__main__'})
        text = out.getvalue()
        for secret in (TOKEN, TOKEN[len(NS.PREFIX):]):
            self.assertNotIn(secret, text)
        return guest._job_json(text)

    def test_start(self):
        data = self.run_probe('start')
        roles = {p['pid']: p['role'] for p in data['processes']}
        self.assertEqual(roles, {20: 'adapter', 21: 'cli'})
        self.assertEqual(data['config_dirs'], [str(self.cfg)])
        self.assertIn('<token>', data['processes'][1]['argv'])
        self.assertTrue(all(p['proxy_is_endpoint'] and p['switches_declared'] for p in data['processes']))
        self.assertIn('.claude.json', [e['path'] for e in data['config_listing']])
        self.assertTrue(data['config_exists'])

    def test_after_not_found_and_found(self):
        data = self.run_probe('after')
        self.assertEqual(data['token_fingerprint'], FP)
        self.assertEqual(data['search']['verdict'], 'not-found', data['search'])
        self.assertTrue(data['search']['controls']['valid'])
        self.assertEqual(data['transcript']['models'], {'claude-sonnet-5': 1, 'claude-haiku-4-5-20251001': 1})
        self.assertEqual(data['transcript']['sidechain_records'], 1)
        self.assertEqual(data['transcript']['occurrences'], {'token': 0, 'endpoint': 1, 'switch': 0, 'marker': 0})
        (self.root / 'workspace' / 'leak.txt').write_text('x' + base64.b64encode(TOKEN.encode()).decode())
        (self.cfg / 'projects' / 'p' / 's.jsonl').write_text(json.dumps({'text': TOKEN}) + '\n')
        (self.root / 'workspace' / '.git-credentials').write_text('none')
        data = self.run_probe('after')
        self.assertEqual(data['search']['verdict'], 'found')
        self.assertEqual(data['transcript']['occurrences']['token'], 1)
        self.assertTrue(any(p.endswith('.git-credentials') for p in data['owner_files_found']))

    def test_capture(self):
        data = self.run_probe('capture')
        raw = base64.b64decode(data['capture']['b64'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), data['capture']['sha256'])
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
            names = tar.getnames()
        self.assertIn('proc/20/environ', names)


if __name__ == '__main__':
    unittest.main()
