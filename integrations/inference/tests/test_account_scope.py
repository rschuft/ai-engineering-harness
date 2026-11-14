"""Account-scope headers are never forwarded (plan leaf S-03.3, fix-forward before the first paid call; the OA-12
package section 3 point 5 and section 5 item 2).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_account_scope.py -v

NOT_FORWARDED is a deny list, so a client's anthropic-workspace-id reached the upstream. Shown here: every request
header whose lower-cased name starts with anthropic-workspace or anthropic-organization is stripped (not refused)
for each declared family, in the streamed and the non-streamed path, against the in-process fake upstreams; the
request is admitted and answered; its audit line names the stripped headers (names only, in the bounded name
grammar), never a value; a request without them carries no such member; declared headers still pass. Since the
security review's S1 a family forwards only the headers it declares (test_headers.py); the account-scope rule is now
implied by it, and still shown here. Everything is synthetic.
"""
from __future__ import annotations

import io
import json
import unittest

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
SCOPE_VALUE = 'SYNTHETIC-SCOPE-VALUE-51c7'
SCOPED = (('anthropic-workspace-id', 'wrkspc_' + SCOPE_VALUE),
          ('Anthropic-Organization-Id', 'org_' + SCOPE_VALUE),
          ('ANTHROPIC-WORKSPACE', SCOPE_VALUE),
          ('anthropic-organization-x-' + 'y' * 40, SCOPE_VALUE))       # a name outside the audit's grammar
KEPT = (('User-Agent', 'synthetic-agent/1'), ('Accept', 'application/json'), ('X-Stainless-Lang', 'js'))


class Stripped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstreams = {family: S.FakeUpstream(family) for family in S.FAMILIES}
        cls.rig = S.Rig(S.component({family: fake.origin for family, fake in cls.upstreams.items()})).start()

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()
        for fake in cls.upstreams.values():
            fake.close()

    def test_each_family_streamed_and_not_receives_none_of_them(self):
        for family in S.FAMILIES:
            grant = self.rig.issue(family=family)
            for stream in (False, True):
                with self.subTest(family=family, stream=stream):
                    upstream = self.upstreams[family]
                    before = len(upstream.requests)
                    status, headers, data = S.request(
                        self.rig.inference, 'POST', S.ROUTE[family], {'model': S.MODEL_A, 'stream': stream},
                        [S.auth(family, grant['token']), *SCOPED, *KEPT])
                    self.assertEqual(status, 200)
                    if stream:
                        self.assertEqual(headers.get('content-type'), 'text/event-stream')
                    (received,) = upstream.requests[before:]
                    names = [name.lower() for name, _ in received['headers']]
                    self.assertFalse([n for n in names if n.startswith(IB.ACCOUNT_SCOPE_PREFIXES)], names)
                    self.assertNotIn(SCOPE_VALUE, json.dumps(received['headers']))
                    for name, value in KEPT:
                        self.assertIn((name.lower(), value), [(n.lower(), v) for n, v in received['headers']])
            lines = [line for line in self.rig.audit_lines()
                     if line.get('token_fingerprint') == grant['token_fingerprint']]
            self.assertEqual(len(lines), 2)
            for line in lines:
                self.assertEqual((line['code'], line['status']), (None, 200))
                self.assertEqual(line['stripped_headers'], {
                    'names': ['anthropic-organization-id', 'anthropic-workspace', 'anthropic-workspace-id'],
                    'unrecorded': 1})
        for family in IB.load_declarations().values():          # implied by every declaration, and asserted
            self.assertFalse([name for name, _ in SCOPED if family.forwards(name.lower())], family.id)
        self.assertNotIn(SCOPE_VALUE, self.rig.audit.path.read_text(encoding='utf-8'))

    def test_a_request_without_them_records_no_member(self):
        grant = self.rig.issue(family='anthropic-messages')
        status, _, _ = S.request(self.rig.inference, 'POST', '/v1/messages', {'model': S.MODEL_A},
                                 [S.auth('anthropic-messages', grant['token']), *KEPT])
        self.assertEqual(status, 200)
        (line,) = [line for line in self.rig.audit_lines()
                   if line.get('token_fingerprint') == grant['token_fingerprint']]
        self.assertNotIn('stripped_headers', line)


class Admission(unittest.TestCase):
    """Socket-free: the admission's forwarded headers and its stripped names."""

    def test_stripped_not_refused_and_named(self):
        rig = S.Rig(S.component({'anthropic-messages': 'http://127.0.0.1:9'}), connect=None)
        self.addCleanup(rig.close)
        grant = rig.issue(family='anthropic-messages')
        data = json.dumps({'model': S.MODEL_A}).encode()
        headers = S.headers(S.auth('anthropic-messages', grant['token']), ('Content-Type', 'application/json'),
                            ('Content-Length', str(len(data))), *SCOPED, *KEPT)
        admission = rig.broker.admit('POST', '/v1/messages', headers, io.BytesIO(data).read)
        self.assertEqual(admission.stripped, ('anthropic-organization-id', 'anthropic-organization-x-' + 'y' * 40,
                                              'anthropic-workspace', 'anthropic-workspace-id'))
        self.assertEqual([name for name, _ in admission.headers], ['Content-Type'] + [name for name, _ in KEPT])
        self.assertEqual(IB.ACCOUNT_SCOPE_PREFIXES, ('anthropic-workspace', 'anthropic-organization'))


if __name__ == '__main__':
    unittest.main()
