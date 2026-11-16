"""The Owner UI session credential and its check (plan leaf U-01.3; Proposed decision 0025, points 3 and 5).

- The credential's shape is its own: ``aieh-oui-`` and 52 lower-case base32 characters, not an Agent Server key
  (43 URL-safe characters) or any other credential shape of security/inventory.json; every one of those is refused
  (``SESSION_CREDENTIAL_FOREIGN``).
- Missing, foreign, expired and revoked are each refused with their stable code, and change nothing: the store's
  canonical dump is equal before and after.
- The store keeps the verifier only: the credential's bytes are nowhere in the database files.

Every credential here is minted in process for one test, in a temporary store.
"""
from __future__ import annotations

import datetime
import re
import unittest

import ownerhost_support as T

CATEGORY = 'unit'
S, E, CS = T.S, T.E, T.CS
NOW = T.utc(2026, 11, 16, 12, 0, 0)


class Shape(unittest.TestCase):
    def test_a_minted_credential_has_the_shape_and_differs_each_time(self):
        minted = {E.mint() for _ in range(20)}
        self.assertEqual(len(minted), 20)
        for value in minted:
            self.assertRegex(value, r'\Aaieh-oui-[a-z2-7]{52}\Z')
            self.assertTrue(S.shaped(value))
            self.assertEqual(len(value), 61)

    def test_the_shape_is_exactly_32_bytes_of_base32(self):
        self.assertEqual(E.mint(lambda n: bytes(n)), 'aieh-oui-' + 'a' * 52)
        self.assertEqual(E.mint(lambda n: b'\xff' * n), 'aieh-oui-' + '7' * 51 + 'q')
        for bad in (lambda n: bytes(n - 1), lambda n: bytes(n + 1), lambda n: 'x' * n):
            with self.assertRaises(ValueError):
                E.mint(bad)

    def test_it_is_not_shaped_like_an_agent_server_key_or_any_harness_token(self):
        value = E.mint()
        broker_token = re.compile(r'aieh-inf-[A-Za-z0-9_-]{43}')         # inference_broker.TOKEN_SHAPE
        agent_server_key = re.compile(r'[A-Za-z0-9_-]{43}')                 # secrets.token_urlsafe(32)
        gitea_token = re.compile(r'[0-9a-f]{40}')
        for other in (broker_token, agent_server_key, gitea_token, re.compile(r'sk-[a-z]+-.*')):
            with self.subTest(shape=other.pattern):
                self.assertIsNone(other.fullmatch(value))
        self.assertNotRegex(value, r'(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])')   # the exposure guard's

    def test_values_off_the_shape_are_not_shaped(self):
        good = E.mint()
        for bad in ('', good.upper(), good[:-1], good + 'a', good.replace('aieh-oui-', 'aieh-inf-'),
                    good[:-1] + '1', good[:-1] + '=', ' ' + good, good + '\n', None, 42, good.encode()):
            with self.subTest(value=repr(bad)[:20]):
                self.assertFalse(S.shaped(bad))
                if isinstance(bad, str):
                    with self.assertRaises(ValueError):
                        S.verifier(bad)

    def test_the_verifier_is_the_domain_separated_sha256(self):
        import hashlib
        value = E.mint()
        self.assertEqual(S.verifier(value), hashlib.sha256(b'ai-engineering-harness/owner-ui-session/v1\n'
                                                           + value.encode()).hexdigest())
        self.assertNotEqual(S.verifier(value), hashlib.sha256(value.encode()).hexdigest())


class Check(unittest.TestCase):
    def setUp(self):
        self.scratch = T.Scratch()
        self.addCleanup(self.scratch.close)

    def refused(self, presented, code, now=NOW):
        before = self.scratch.dump()
        with self.assertRaises(S.SessionRefused) as caught:
            S.check(self.scratch.store, presented, T.stamp(now))
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(self.scratch.dump(), before, 'a refusal changed the store')
        for value in presented:
            text = value.decode('latin-1') if isinstance(value, bytes) else value
            if len(text) > 8:
                self.assertNotIn(text, str(caught.exception))
        return caught.exception

    def test_an_enrolled_current_session_passes_until_its_expiry(self):
        credential, record = self.scratch.enroll(at=NOW, hours=12)
        for presented in ([credential], [credential.encode()]):
            session = S.check(self.scratch.store, presented, T.stamp(NOW + datetime.timedelta(hours=11, minutes=59)))
            self.assertEqual(session.session_id, record.session_id)
        self.refused([credential], 'SESSION_CREDENTIAL_EXPIRED', NOW + datetime.timedelta(hours=12))

    def test_missing(self):
        self.scratch.enroll(at=NOW)
        self.refused([], 'SESSION_CREDENTIAL_MISSING')

    def test_foreign_shape_unknown_verifier_and_duplicate_headers(self):
        credential, _ = self.scratch.enroll(at=NOW)
        self.refused([E.mint()], 'SESSION_CREDENTIAL_FOREIGN')                 # shaped, never enrolled
        self.refused([credential.upper()], 'SESSION_CREDENTIAL_FOREIGN')
        self.refused([credential, credential], 'SESSION_CREDENTIAL_FOREIGN')
        self.refused([b'aieh-oui-\xff' + b'a' * 51], 'SESSION_CREDENTIAL_FOREIGN')
        self.refused([credential + ' '], 'SESSION_CREDENTIAL_FOREIGN')

    def test_every_other_credential_shape_of_the_inventory_is_refused_as_foreign(self):
        self.scratch.enroll(at=NOW)
        for cid, value in T.samples().items():
            with self.subTest(credential=cid):
                self.assertFalse(S.shaped(value))
                self.refused([value], 'SESSION_CREDENTIAL_FOREIGN')

    def test_the_shape_catalogue_covers_every_inventory_credential(self):
        self.assertEqual(set(T.SHAPES) | {T.OWN}, T.inventory_credential_ids())
        self.assertNotIn(T.OWN, T.SHAPES)

    def test_a_superseded_session_is_revoked_and_the_new_one_passes(self):
        first, one = self.scratch.enroll(at=NOW)
        second, two = self.scratch.enroll(at=NOW + datetime.timedelta(minutes=1))
        self.assertEqual(two.supersedes, one.session_id)
        refusal = self.refused([first], 'SESSION_CREDENTIAL_REVOKED')
        self.assertIn(two.session_id, refusal.detail)
        self.assertEqual(S.check(self.scratch.store, [second], T.stamp(NOW)).session_id, two.session_id)

    def test_revoked_is_decided_before_expired(self):
        first, _ = self.scratch.enroll(at=NOW, hours=1)
        self.scratch.enroll(at=NOW)
        self.refused([first], 'SESSION_CREDENTIAL_REVOKED', NOW + datetime.timedelta(days=3))

    def test_expired_and_foreign_stay_distinguishable(self):
        credential, _ = self.scratch.enroll(at=NOW - datetime.timedelta(days=2), hours=1)
        self.refused([credential], 'SESSION_CREDENTIAL_EXPIRED')
        self.refused([E.mint()], 'SESSION_CREDENTIAL_FOREIGN')

    def test_a_session_issued_more_than_five_minutes_ahead_is_foreign(self):
        credential, _ = self.scratch.enroll(at=NOW + datetime.timedelta(minutes=5, seconds=1))
        refusal = self.refused([credential], 'SESSION_CREDENTIAL_FOREIGN')
        self.assertIn('after now', refusal.detail)
        within, _ = self.scratch.enroll(at=NOW + datetime.timedelta(minutes=5))
        self.assertEqual(S.check(self.scratch.store, [within], T.stamp(NOW)).issued_at, '2026-11-16T12:05:00Z')

    def test_with_no_enrollment_every_credential_is_foreign(self):
        self.refused([E.mint()], 'SESSION_CREDENTIAL_FOREIGN')

    def test_each_refusal_names_its_remedy(self):
        self.assertEqual(set(S.REMEDIES), {'SESSION_CREDENTIAL_MISSING', 'SESSION_CREDENTIAL_FOREIGN',
                                           'SESSION_CREDENTIAL_EXPIRED', 'SESSION_CREDENTIAL_REVOKED'})
        for code in S.REMEDIES:
            exc = S.SessionRefused(code, 'detail')
            self.assertEqual(exc.body(), {'code': code, 'detail': 'detail', 'remedy': S.REMEDIES[code]})
        with self.assertRaises(ValueError):
            S.SessionRefused('SESSION_UNKNOWN', 'x')


class Enrollment(unittest.TestCase):
    def setUp(self):
        self.scratch = T.Scratch()
        self.addCleanup(self.scratch.close)

    def test_the_store_keeps_the_verifier_never_the_credential(self):
        credential, record = self.scratch.enroll(at=NOW, hours=7 * 24)
        self.assertEqual((record.issued_at, record.expires_at), ('2026-11-16T12:00:00Z', '2026-11-23T12:00:00Z'))
        self.assertEqual(record.verifier, S.verifier(credential))
        self.assertNotIn(credential.encode(), self.scratch.dump())
        self.scratch.store.conn.execute('PRAGMA wal_checkpoint(FULL)')
        for path in self.scratch.dir.iterdir():
            data = path.read_bytes()
            self.assertNotIn(credential.encode(), data, path.name)
            self.assertNotIn(credential[len(S.PREFIX):].encode(), data, path.name)
        self.assertNotIn('verifier', record.public())

    def test_one_session_is_current_and_each_enrollment_supersedes_it(self):
        records = [self.scratch.enroll(at=NOW + datetime.timedelta(minutes=i))[1] for i in range(3)]
        self.assertEqual([r.supersedes for r in records], [None, records[0].session_id, records[1].session_id])
        sessions = self.scratch.store.sessions()
        self.assertEqual([s.current for s in sessions], [False, False, True])
        self.assertEqual(self.scratch.store.current_session().session_id, records[2].session_id)

    def test_the_validity_is_one_hour_to_seven_days(self):
        for hours in (0, -1, 169, 1.5, '12', True):
            with self.subTest(hours=hours), self.assertRaises(E.EnrollRefused) as caught:
                self.scratch.enroll(at=NOW, hours=hours)
            self.assertEqual(caught.exception.code, 'ENROLL_HOURS_INVALID')
        self.assertEqual(self.scratch.store.sessions(), [])
        self.scratch.enroll(at=NOW, hours=1)
        self.scratch.enroll(at=NOW, hours=168)

    def test_the_announcement_shows_the_credential_once_with_the_session(self):
        import io
        credential, record = self.scratch.enroll(at=NOW)
        out = io.StringIO()
        E.announce(credential, record, out)
        self.assertEqual(out.getvalue().count(credential), 1)
        self.assertIn(record.session_id, out.getvalue())
        self.assertIn(record.expires_at, out.getvalue())


if __name__ == '__main__':
    unittest.main()
