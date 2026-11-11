"""Tests for the prepared custody probe of plan leaf E-01.3.3 (tools/guest.py custody_probe; NOT RUN live).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

stdlib unittest; no QEMU, no guest, no ssh, no Gitea. The guest is replaced by fakes: the dispatcher's API channel
(create, mint, delete), the root facts (one conversation container with its published port), inspect's and
job-access-probe's records, and a fake ssh that runs the real RUNTIME_CREDENTIAL_SWEEP locally under the base
interpreter against a loopback fake that is both the outer server and the conversation's inner server. Shown: the
decision rule's PASS; every step's FAIL and UNKNOWN (a lost answer is never PASS); each stop condition; the assumed
shape of the runtime-credentials answer; the record never holds the runtime credential.
"""
from pathlib import Path
import ast
import copy
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

CATEGORY = 'integration'

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')
tg = module_code.load('test_guest_fixtures', REPO / 'tools' / 'tests' / 'test_guest.py')
PROFILE = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
KEY = PROFILE['provisioning']['agent_server']['session_key']
BASE_PYTHON = getattr(sys, '_base_executable', sys.executable)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CREDENTIAL = 'runtime-credential-' + 'R' * 24
CID = guest.CUSTODY_CONVERSATION_ID
FP = {'builder': 'sha256:' + '1' * 16, 'reviewer': 'sha256:' + '2' * 16}
RECORD = {'provisioning': {'image_id': tg.IMAGE_ID}, 'ports': {'ssh': 40022, 'qmp': 40023}}


class Listener(http.server.ThreadingHTTPServer):
    """A loopback listener standing for the outer server (every route refuses the runtime credential with 401,
    unless ``admit`` names a path answered 200, or holds '*': a broken outer server) or, with ``inner``, the conversation's
    inner server (/api/conversations/count answers 200 with the runtime credential and 401 without)."""

    def __init__(self, inner=False):
        server = self
        self.admit, self.seen = set(), []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self):
                key = self.headers.get('X-Session-API-Key')
                server.seen.append((self.command, self.path, key))
                if self.headers.get('Upgrade'):
                    status = 403
                elif self.path in server.admit or '*' in server.admit:
                    status = 200
                elif inner and self.path == '/api/conversations/count':
                    status = 200 if key == CREDENTIAL else 401
                else:
                    status = 401
                data = json.dumps({'ok': True} if status == 200 else {'detail': 'Unauthorized'}).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(data)
            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = answer

        super().__init__(('127.0.0.1', 0), Handler)


class FakeSweepSsh:
    """guest.Ssh's run(): the sweep runs locally; the outer listener and the inner endpoint are mapped to the
    loopback fake. Every script is kept."""

    def __init__(self, port, inner_port, lose=False):
        self.port, self.inner_port, self.lose, self.scripts = port, inner_port, lose, []

    def run(self, command, user='agent', input_text=None, timeout=300):
        self.scripts.append((list(command), user, input_text))
        if self.lose:
            return subprocess.CompletedProcess(command, 255, '', 'Connection reset')
        head, _, body = input_text.partition('\n')
        sealed = ast.literal_eval(head.split('=', 1)[1].strip())  # (base64 spec, credential), as the script reads it
        spec = json.loads(guest.base64.b64decode(sealed[0]))
        spec['outer'] = ['127.0.0.1', self.port]
        spec['inner'][:2] = ['127.0.0.1', self.inner_port]
        text = 'SEALED = ' + repr((guest.base64.b64encode(json.dumps(spec).encode()).decode(), sealed[1])) + '\n' + body
        done = subprocess.run([BASE_PYTHON, '-I', '-'], input=text.encode(), capture_output=True, timeout=timeout,
                              creationflags=NO_WINDOW)
        return subprocess.CompletedProcess(command, done.returncode, done.stdout.decode().replace('\r\n', '\n'),
                                           done.stderr.decode())


def inspect_record(**changes):
    files = {KEY['guest_path']: [KEY['owner'], KEY['group'], KEY['mode'], 'regular file'],
             KEY['guest_path'].rsplit('/', 1)[0]: [KEY['guest_dir_owner'], KEY['guest_dir_group'],
                                                   KEY['guest_dir_mode'], 'directory']}
    observed = {'files': files, 'agent_open': {KEY['guest_path']: 'READABLE'},
                'host_copy': {'present': True, 'equal': True}, 'session_key_matches': True}
    observed.update(changes)
    return {'properties': [{'property': 'profiles P5', 'checks': [
        {'check': 'Agent Server secrets (custody)', 'observed': observed, 'verdict': 'PASS'}]}]}


def job_record(hits=None, result='PASS', gitea=None, ok=True):
    containers = {c: {'hits': (hits or {}).get(c, []), 'credential_files': [], 'ok': ok} for c in ('c1', 'c2')}
    return {'result': result, 'steps': [{'step': guest.JOB_CREDENTIALS_STEP, 'ok': ok, 'detail': {
        'searched': {'outer (aieh v1)': ['OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0'],
                     'gitea (sha256 prefix)': sorted(gitea if gitea is not None else FP.values())},
        'containers': containers}}]}


def delivery(stage, role, bot, fp):
    return {'format': 'ai-engineering-harness/dispatch/role-token-delivery/v1',
            'operationKey': f'attempt/v1/TASK-2/{"a" * 40}/{stage}/1', 'attemptId': 'x', 'stage': stage,
            'role': role, 'bot': bot, 'entry': f'AIEH Gitea bot {role}', 'credential': f'cred-gitea-bot-{role}',
            'scopes': ['write:repository'], 'fingerprint': fp}


def deliveries(**change):
    out = {'records': [delivery('implement', 'builder', 'aieh-bot-builder', FP['builder']),
                       delivery('review', 'reviewer', 'aieh-bot-reviewer', FP['reviewer'])],
           'fingerprints': dict(FP), 'refused': [], 'provider_writes': 0}
    out.update(change)
    return out


class ProbeRun(unittest.TestCase):
    """custody_probe against the fakes."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.inner = Listener(), Listener(inner=True)
        cls.threads = [threading.Thread(target=s.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
                       for s in (cls.server, cls.inner)]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls):
        for server, thread in zip((cls.server, cls.inner), cls.threads):
            server.shutdown()
            server.server_close()
            thread.join(10)

    def sweep_ssh(self, lose=False):
        return FakeSweepSsh(self.server.server_address[1], self.inner.server_address[1], lose)

    def setUp(self):
        self.server.admit.clear()
        self.state = Path(tempfile.mkdtemp(prefix='aieh-custody-'))
        self.addCleanup(tg.remove_tree, self.state)
        self.api_calls = []
        self.mint_body = {'session_api_key': CREDENTIAL}

    def api(self, requests, timeout=900, secret=None):
        (request,) = requests
        self.api_calls.append((request['method'], request['path']))
        if request['path'].endswith('/runtime/credentials'):
            return {'responses': [{'status': 200, 'body': self.mint_body}], 'session_key_occurrences': 0}
        if request['method'] == 'POST':
            return {'responses': [{'status': 201, 'body': {'id': CID}}], 'session_key_occurrences': 0}
        return {'responses': [{'status': 200, 'body': {}}], 'session_key_occurrences': 0}

    def facts(self):
        container = tg.conversation_container(hex_id=CID.replace('-', ''), port=str(self.inner.server_address[1]))
        return {'containers': [container]}

    def run_probe(self, attempts=None, inspected=None, job=None, ssh=None, profile=PROFILE, ports_after=None):
        """One probe run; its sweep takes the first three key-gated HTTP routes and one WebSocket (each is a
        loopback request; the spec's coverage of every route is tested apart)."""
        written = {}
        full = guest.runtime_credential_spec

        def trimmed(routes, outer, inner):
            spec = full(routes, outer, inner)
            return dict(spec, http=spec['http'][:3], ws=spec['ws'][:1])
        ctx = types.SimpleNamespace(profile=profile, repo=REPO, instance_dir=lambda n: self.state / n)
        records = iter([RECORD, dict(RECORD, ports=ports_after or RECORD['ports'])])
        self.ssh = ssh or self.sweep_ssh()
        self.job_calls = []

        def job_access(fps):
            self.job_calls.append(fps)
            return job if job is not None else job_record(gitea=sorted(fps.values()))
        with mock.patch.object(guest, 'running_instance', side_effect=lambda c, n: (None, next(records))),                 mock.patch.object(guest, 'runtime_credential_spec', trimmed), \
                mock.patch.object(guest, 'write_record', side_effect=lambda i, op, out: written.update({op: out})):
            out = guest.custody_probe(
                ctx, 'g1', attempts_fn=lambda transport: (self.transports.append(transport) or
                                                          (deliveries() if attempts is None else attempts)),
                channels=lambda rec: (self.api, self.facts), ssh_fn=lambda rec: self.ssh,
                inspect_fn=lambda: inspected or inspect_record(), job_access_fn=job_access)
        self.assertEqual(written['custody-probe']['result'], out['result'])
        self.assertNotIn(CREDENTIAL, json.dumps(written, default=str))
        return out

    transports = []

    def verdicts(self, out):
        return [s['verdict'] for s in out['steps']]

    def test_the_rule_passes_on_a_guest_that_holds_it(self):
        out = self.run_probe()
        self.assertEqual(out['result'], 'PASS', [(s['step'], s['verdict'], s.get('detail')) for s in out['steps']])
        self.assertEqual(self.verdicts(out), ['PASS'] * 5)
        self.assertEqual(out['rule'], guest.CUSTODY_PROBE_RULE)
        self.assertIsInstance(self.transports[-1], guest.dispatch_transport().GuestTransport)
        self.assertEqual(self.job_calls, [FP])
        detail = out['steps'][4]['detail']
        self.assertEqual(detail['inner'], {'with_credential': 200, 'without': 401})
        self.assertEqual((detail['outer_http_routes'], detail['outer_ws_routes']), (3, 1))
        self.assertIn('ASSUMED', detail['assumed'])
        # the sweep was sealed: the credential in the script's text only, never an argument; no outer key read
        (argv, user, script), = self.ssh.scripts
        self.assertEqual((argv, user), (['python3', '-'], 'agent'))
        self.assertIn(CREDENTIAL, script)
        self.assertNotIn(KEY['guest_path'], script)
        self.assertEqual(self.api_calls, [('POST', '/api/conversations'),
                                          ('POST', f'/api/conversations/{CID}/runtime/credentials'),
                                          ('DELETE', f'/api/conversations/{CID}')])
        self.assertEqual(out['conversation_deleted'], 200)

    def test_without_the_dispatch_chain_it_is_refused(self):
        ctx = types.SimpleNamespace(profile=PROFILE, repo=REPO, instance_dir=lambda n: self.state / n)
        with self.assertRaisesRegex(guest.Refused, 'live_custody_probe'):
            guest.custody_probe(ctx, 'g1')

    def test_a_2xx_on_an_outer_route_is_a_stop(self):
        self.server.admit.add('*')  # every outer route answers 2xx
        out = self.run_probe()
        self.assertEqual(out['result'], 'FAIL')
        self.assertEqual(out['stop_conditions'][0]['stop'], 'the runtime credential got 2xx on an outer route')
        self.assertEqual(out['steps'][4]['verdict'], 'FAIL')

    def test_an_inner_server_open_without_the_credential_fails(self):
        verdict, detail, stops = guest.runtime_credential_verdict(
            {'http': [], 'ws': [], 'inner': {'with_credential': {'status': 200}, 'without': {'status': 200}},
             'credential_occurrences': 0}, {'http': [], 'ws': []})
        self.assertEqual((verdict, stops), ('FAIL', []))
        verdict, _, _ = guest.runtime_credential_verdict(
            {'http': [], 'ws': [], 'inner': {'with_credential': {'status': 401}, 'without': {'status': 401}},
             'credential_occurrences': 0}, {'http': [], 'ws': []})
        self.assertEqual(verdict, 'FAIL')

    def test_a_websocket_that_admits_the_credential_is_a_stop(self):
        spec = {'http': [], 'ws': ['/sockets/x']}
        inner = {'with_credential': {'status': 200}, 'without': {'status': 401}}
        for observed, want in (({'handshake': 101, 'opcode': 1}, 'FAIL'), ({'handshake': 403}, 'PASS'),
                               ({'handshake': 101, 'close_code': 4001}, 'PASS'), ({'error': 'x'}, 'UNKNOWN'),
                               ({}, 'UNKNOWN')):
            with self.subTest(observed=observed):
                verdict, _, stops = guest.runtime_credential_verdict(
                    {'http': [], 'ws': [{'path': '/sockets/x', 'first_message_credential': observed}],
                     'inner': inner, 'credential_occurrences': 0}, spec)
                self.assertEqual(verdict, want)
                self.assertEqual(bool(stops), want == 'FAIL')

    def test_lost_answers_are_unknown_never_pass(self):
        out = self.run_probe(ssh=self.sweep_ssh(lose=True))
        self.assertEqual((out['result'], out['steps'][4]['verdict']), ('UNKNOWN', 'UNKNOWN'))
        self.mint_body = {'credential': CREDENTIAL}  # not the assumed shape
        out = self.run_probe()
        self.assertEqual((out['result'], out['steps'][4]['verdict']), ('UNKNOWN', 'UNKNOWN'))
        self.assertIn('ASSUMED', out['steps'][4]['detail']['assumed'])
        self.mint_body = {'session_api_key': CREDENTIAL}
        out = self.run_probe(inspected={'properties': []})
        self.assertEqual(self.verdicts(out)[1:3], ['UNKNOWN', 'UNKNOWN'])
        self.assertEqual(out['result'], 'UNKNOWN')
        out = self.run_probe(attempts={'records': None})
        self.assertEqual((self.verdicts(out)[0], self.verdicts(out)[3]), ('UNKNOWN', 'UNKNOWN'))
        verdict, _, _ = guest.runtime_credential_verdict(
            {'http': [{'method': 'GET', 'path': '/a', 'with_credential': {'error': 'TimeoutError'}}], 'ws': [],
             'inner': {'with_credential': {'status': 200}, 'without': {'status': 401}}, 'credential_occurrences': 0},
            {'http': [['GET', '/a']], 'ws': []})
        self.assertEqual(verdict, 'UNKNOWN')

    def test_key_custody_and_positive_control_failures(self):
        files = copy.deepcopy(inspect_record()['properties'][0]['checks'][0]['observed']['files'])
        files[KEY['guest_path']][2] = '444'
        out = self.run_probe(inspected=inspect_record(files=files))
        self.assertEqual(self.verdicts(out)[1:3], ['FAIL', 'PASS'])
        for change in ({'agent_open': {KEY['guest_path']: 'EACCES'}}, {'host_copy': {'equal': False}},
                       {'session_key_matches': False}):
            with self.subTest(change=change):
                out = self.run_probe(inspected=inspect_record(**change))
                self.assertEqual((self.verdicts(out)[2], out['result']), ('FAIL', 'FAIL'))

    def test_a_fingerprint_hit_or_an_incomplete_search_in_a_container(self):
        out = self.run_probe(job=job_record(hits={'c2': [['/proc/1/environ', 'gitea:builder']]}))
        self.assertEqual((self.verdicts(out)[3], out['result']), ('FAIL', 'FAIL'))
        out = self.run_probe(job=job_record(gitea=['sha256:' + '9' * 16]))
        self.assertEqual(self.verdicts(out)[3], 'UNKNOWN')
        out = self.run_probe(job=job_record(result='FAIL'))
        self.assertEqual(self.verdicts(out)[3], 'FAIL')
        out = self.run_probe(attempts=deliveries(fingerprints={'builder': FP['builder']}))
        self.assertEqual(self.verdicts(out)[3], 'UNKNOWN')

    def test_deliveries_must_be_exactly_the_mapped_bots_with_fingerprints_only(self):
        wrong = deliveries()
        wrong['records'][1]['bot'] = 'aieh-bot-builder'
        token_shaped = deliveries()
        token_shaped['records'][0]['fingerprint'] = 'b' * 40
        extra = deliveries()
        extra['records'][0]['token'] = 'x'
        for name, attempts in (('another bot', wrong), ('a token-shaped value', token_shaped),
                               ('an extra field', extra), ('a refusal', deliveries(refused=[{'code': 'X'}])),
                               ('one stage only', deliveries(records=deliveries()['records'][:1]))):
            with self.subTest(name):
                out = self.run_probe(attempts=attempts)
                self.assertEqual((self.verdicts(out)[0], out['result']), ('FAIL', 'FAIL'))

    def test_stop_conditions(self):
        out = self.run_probe(attempts=deliveries(provider_writes=1))
        self.assertEqual(out['stop_conditions'][0]['stop'], 'a credential-provider write')
        self.assertEqual(out['result'], 'FAIL')
        self.assertTrue(all(out['steps'][i].get('skipped') for i in (1, 3, 4)))
        out = self.run_probe(ports_after={'ssh': 40022, 'qmp': 40023, 'ui': 40100})
        self.assertEqual((out['stop_conditions'][-1]['stop'], out['result']), ('a new host port', 'FAIL'))
        changed = copy.deepcopy(PROFILE)
        changed['provisioning']['agent_server']['session_key']['group'] = 'dispatch'
        out = self.run_probe(profile=changed)
        self.assertEqual(out['stop_conditions'][0]['stop'], 'a change of the seed or the profile would be needed')
        self.assertEqual(out['result'], 'FAIL')

    def test_the_sweep_covers_every_key_gated_route_of_the_inventory(self):
        ctx = types.SimpleNamespace(profile=PROFILE, repo=REPO)
        routes, problems = guest.load_routes(ctx)
        self.assertEqual(problems, [])
        spec = guest.runtime_credential_spec(routes, ('127.0.0.1', 8000), ('127.0.0.1', 32768))
        gated = [r for r in routes['routes'] if r['admission'] == 'session-key' and r['method'] != 'WEBSOCKET']
        self.assertEqual(len(spec['http']), len(gated))
        self.assertGreater(len(gated), 100)
        self.assertEqual(len(spec['ws']), len([r for r in routes['routes'] if r['method'] == 'WEBSOCKET']))
        self.assertNotIn(('GET', '/server_info'), [tuple(x) for x in spec['http']])  # public routes are not swept
        self.assertEqual(spec['inner'], ['127.0.0.1', 32768, '/api/conversations/count'])

    def test_the_verdict_function(self):
        self.assertEqual(guest.custody_verdict([], []), 'UNKNOWN')
        self.assertEqual(guest.custody_verdict([{'verdict': 'PASS'}], [{'stop': 'x'}]), 'FAIL')
        self.assertEqual(guest.custody_verdict([{'verdict': 'PASS'}, {'verdict': 'UNKNOWN'}], []), 'UNKNOWN')
        self.assertEqual(guest.custody_verdict([{'verdict': 'UNKNOWN'}, {'verdict': 'FAIL'}], []), 'FAIL')
        self.assertIsNone(guest.runtime_credential_of({'session_api_key': 'short'}))
        self.assertIsNone(guest.runtime_credential_of({'session_api_key': 'has space ' + 'x' * 20}))
        self.assertIsNone(guest.runtime_credential_of([CREDENTIAL]))
        self.assertEqual(guest.runtime_credential_of({'session_api_key': CREDENTIAL}), CREDENTIAL)
        self.assertIsNone(guest.inner_endpoint(PROFILE, {'containers': []}, CID))


if __name__ == '__main__':
    unittest.main()
