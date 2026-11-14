"""The proof of plan leaf S-03.5, slice 1: the provider envelope and the broker's start precondition, under the
canonical format aieh-provider-envelope/2 of plan leaf S-03.6 (the spending limit retired, decision 0021
amendment 1).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -v

Every row of the slice-1 proof table of the work design (stated before it was run) is shown here: the pure
envelope (its block, document, digest and manifest), the envelope command, every start refusal of serve (in each,
the context's provider, audit directory and wait raise if asked: serve refused before it read the provider key or
opened a listener), the started broker with its authorization, the loopback exemption, and the held authorization
at admission. The envelope receipts are made by the REAL authorization recorder against the owner suite's fake
Gitea and read by the REAL read side (envelope_support.py says how); a hand-written receipt appears only where a
test says so. The bound origin is a name under .test and is never connected.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime
import hashlib
import io
import json
import threading
import unittest

import envelope_support as V

S, IB, E, ED, AR = V.S, V.IB, V.E, V.ED, V.AR
CATEGORY = 'integration'

try:
    import yaml
except ImportError:  # the tools set provides it; the suite runs under the tools interpreter
    yaml = None

# The canonical manifest of envelope_support.component() under V.OPERATION, and its two digests, as constants:
# a change of the canonical form changes them, and is a new format (aieh-provider-envelope/2, S-03.6).
GOLDEN_DIGEST = 'sha256:e5e77a3b0d218e9a139e614ee03ba78e5c62dbc869017d529f6cd07fb52fd184'
GOLDEN_MANIFEST_DIGEST = 'sha256:fc64cada721481cf78fdce071ed6c2df972257611dae2e7a85ddbdb19037c7ed'
GOLDEN_MANIFEST = (
    '{\n  "operation": "op-envelope-0001",\n  "kind": "provider-envelope",\n'
    '  "target": "sha256:e5e77a3b0d218e9a139e614ee03ba78e5c62dbc869017d529f6cd07fb52fd184",\n'
    '  "expiresAt": "2026-12-01T00:00:00Z",\n  "envelope": {\n    "format": "aieh-provider-envelope/2",\n'
    '    "provider": "synthetic-provider",\n    "origin": "https://api.provider.test:443",\n'
    '    "expires_at": "2026-12-01T00:00:00Z",\n    "selection": {\n      "by": "envelope",\n'
    '      "models": {\n        "anthropic-messages": [\n          "syn-model-a"\n        ]\n      }\n    }\n'
    '  }\n}\n')
# The same envelope's canonical digest and manifest digest under S-03.5's aieh-provider-envelope/1 (the golden
# constants S-03.5 recorded): envelope_support.document_v1 reproduces that format exactly.
GOLDEN_V1_DIGEST = 'sha256:e56f90cb18907ce68474b96e93a139845068c6b5083e6281233a43a84215ff61'
GOLDEN_V1_MANIFEST_DIGEST = 'sha256:6a26b733d924fcfa3409089bd0930cd5bb4107604feb1d2b514aee7a297e2cd7'
ORIGIN_TEXT = 'https://api.provider.test:443'


def config(raw):
    return IB.load_config(raw, allow_ephemeral=True)


# ---------------------------------------------------------------- the pure envelope (unit)


class TheBlock(unittest.TestCase):
    category = 'unit'

    def refused(self, envelope):
        with self.assertRaises(IB.InferenceError) as caught:
            config(V.component(envelope=envelope))
        self.assertEqual(caught.exception.code, 'CONFIG_ENVELOPE_INVALID', caught.exception.detail)
        return caught.exception.detail

    def test_the_block_is_checked_and_normalized(self):
        self.assertEqual(config(V.component()).envelope, {'expires_at': V.EXPIRES, 'selection': 'envelope'})
        self.assertEqual(E.BLOCK_FIELDS, ('expires_at', 'selection'))
        self.assertIsNone(config(V.component(envelope=None)).envelope)
        self.assertIsNone(config({'envelope': None}).envelope)

    def test_each_malformed_block_is_refused(self):
        cases = {
            'not a mapping': 'envelope',
            'an unknown key': V.block(extra=1),
            'a missing key': {k: v for k, v in V.block().items() if k != 'selection'},
            'an expiry that is no time': V.block(expires_at='2026-12-01'),
            'an impossible expiry': V.block(expires_at='2026-02-30T00:00:00Z'),
            'an expiry read as a time': V.block(expires_at=datetime.datetime(2026, 12, 1, tzinfo=V.UTC)),
            'an unknown selection': V.block(selection='owner'),
        }
        for name, envelope in cases.items():
            with self.subTest(name):
                self.refused(envelope)
        self.assertIn('quote it', self.refused(cases['an expiry read as a time']))

    def test_the_retired_spending_keys_are_refused_never_ignored(self):
        """S-03.6: the block refuses limit (S-03.5's whole member, or any value) and each of its former members
        amount, currency, enforced_by and cap, beside the designed keys or alone, by name."""
        cases = {
            'the /1 limit': V.block(limit=dict(V.RETIRED_LIMIT)),
            'a broker-enforced /1 limit': V.block(limit=dict(V.RETIRED_LIMIT, enforced_by='broker', cap=1000)),
            'a null limit': V.block(limit=None),
            'an amount': V.block(amount='25.00'),
            'a currency': V.block(currency='USD'),
            'an enforcement': V.block(enforced_by='provider'),
            'a cap': V.block(cap=1000),
            'every one': V.block(limit={}, amount='1', currency='USD', enforced_by='broker', cap=1),
            'a limit without the designed keys': {'limit': dict(V.RETIRED_LIMIT)},
        }
        self.assertEqual(E.RETIRED_FIELDS, ('limit', 'amount', 'currency', 'enforced_by', 'cap'))
        for name, envelope in cases.items():
            with self.subTest(name):
                detail = self.refused(envelope)
                self.assertIn('retired', detail)
                for key in E.RETIRED_FIELDS:
                    self.assertEqual(f"'{key}'" in detail, key in envelope)

    @unittest.skipIf(yaml is None, 'PyYAML is not importable: run task tools:install')
    def test_the_designed_keys_pass_the_secret_rule_and_unquoted_values_are_refused(self):
        """The decision 0009 loader and the broker accept every designed key (none is secret-shaped); YAML reads
        an unquoted timestamp and decimal as a datetime and a float, which are refused, never normalized."""
        text = ('version: 1\ncomponents:\n  inference_broker:\n    envelope:\n      expires_at: {expires}\n'
                '{limit}      selection: delegation\n')
        limit = ('      limit:\n        amount: "25.00"\n        currency: USD\n        enforced_by: broker\n'
                 '        cap: 1000000\n')

        def component(expires, limit=''):
            _, _, components = IB.paths.validate_config(yaml.safe_load(text.format(expires=expires, limit=limit)))
            return components[IB.COMPONENT]
        self.assertEqual(config(component(f'"{V.EXPIRES}"')).envelope,
                         {'expires_at': V.EXPIRES, 'selection': 'delegation'})
        for name, expires, extra, expected in (('an unquoted timestamp', V.EXPIRES, '', 'quote it'),
                                               ('a /1 block with its limit', f'"{V.EXPIRES}"', limit, 'retired')):
            with self.subTest(name):
                with self.assertRaises(IB.InferenceError) as caught:
                    config(component(expires, extra))
                self.assertEqual(caught.exception.code, 'CONFIG_ENVELOPE_INVALID')
                self.assertIn(expected, caught.exception.detail)

    def test_the_loader_never_requires_the_block(self):
        """Trap 7: a non-loopback family loads without an envelope (the launcher's and the dispatcher's callers
        keep their codes); the requirement is serve's. The config report is unchanged."""
        bare = config(V.component(envelope=None))
        self.assertEqual(bare.families['anthropic-messages'].upstream.text(), ORIGIN_TEXT)
        self.assertEqual(config(V.component()).describe(), bare.describe())
        self.assertNotIn('envelope', bare.describe())


class TheDocument(unittest.TestCase):
    category = 'unit'

    def test_the_golden_document_digest_and_manifest(self):
        document, digest = IB.live_envelope(config(V.component()))
        self.assertEqual(tuple(document), E.DOCUMENT_FIELDS)
        self.assertEqual(E.DOCUMENT_FIELDS, ('format', 'provider', 'origin', 'expires_at', 'selection'))
        self.assertEqual(document['format'], 'aieh-provider-envelope/2')
        self.assertFalse(set(json.dumps(document).split('"')) & set(E.RETIRED_FIELDS))   # no spending member
        self.assertEqual(digest, GOLDEN_DIGEST)
        text = E.manifest_text(document, V.OPERATION)
        self.assertEqual(text, GOLDEN_MANIFEST)
        self.assertEqual(tuple(json.loads(text)), E.MANIFEST_FIELDS)
        self.assertEqual(E.manifest_digest(document, V.OPERATION), GOLDEN_MANIFEST_DIGEST)
        self.assertNotIn('\r', text)
        with self.assertRaises(ValueError):
            E.manifest_text(document, 'Not An Id')

    def test_the_canonical_json_is_the_stores_rule(self):
        storecore = S._load('storecore', S.REPO / 'integrations' / 'storecore' / 'storecore.py')
        document, _ = IB.live_envelope(config(V.component(models=(S.MODEL_B, S.MODEL_A))))
        sample = {**document, 'z': [1, None, 'xé'], 'a': {'b': 2}}
        self.assertEqual(E.canonical_json(sample), storecore.canonical_json(sample))

    def test_the_v1_fixture_is_s_03_5s_format_and_its_digest_is_not_the_live_one(self):
        """envelope_support.document_v1 reproduces S-03.5's /1 golden digest and manifest digest exactly (a
        correctly formed /1 document of the same families), and neither is the /2 envelope's."""
        raw = V.component()
        v1 = V.document_v1(raw)
        self.assertEqual(tuple(v1), ('format', 'provider', 'origin', 'limit', 'expires_at', 'selection'))
        self.assertEqual(E.digest(v1), GOLDEN_V1_DIGEST)
        blob = V.manifest_bytes_v1(raw)
        self.assertEqual('sha256:' + hashlib.sha256(blob).hexdigest(), GOLDEN_V1_MANIFEST_DIGEST)
        self.assertNotIn(GOLDEN_V1_DIGEST, (GOLDEN_DIGEST, IB.live_envelope(config(raw))[1]))
        self.assertNotEqual(blob, V.manifest_bytes(raw))

    def test_the_selection_and_the_expiry_are_inside_the_digest(self):
        base = IB.live_envelope(config(V.component(models=(S.MODEL_A, S.MODEL_B))))
        document, digest = base
        self.assertEqual(document['selection'], {'by': 'envelope', 'models': {'anthropic-messages': [S.MODEL_A,
                                                                                                     S.MODEL_B]}})
        reordered = IB.live_envelope(config(V.component(models=(S.MODEL_B, S.MODEL_A))))
        self.assertEqual(reordered[1], digest)          # the identifiers are sorted
        delegated = IB.live_envelope(config(V.component(envelope=V.block(selection='delegation'))))[0]
        self.assertEqual(delegated['selection'], {'by': 'delegation', 'record': 'decision:0018', 'point': '3'})
        others = [V.component(models=(S.MODEL_A,)), V.component(envelope=V.block(selection='delegation')),
                  V.component(envelope=V.block(expires_at='2026-12-02T00:00:00Z')),
                  V.component(origin=V.OTHER_ORIGIN), V.component(provider=S.OTHER_PROVIDER)]
        digests = {IB.live_envelope(config(raw))[1] for raw in others}
        self.assertEqual(len(digests), len(others))
        self.assertNotIn(digest, digests)

    def test_the_repeated_constants_equal_their_sources(self):
        D = AR.D
        self.assertEqual(f'^{E.OPERATION.pattern}$', D.OPERATION.pattern)
        self.assertEqual(IB.AUTHORIZATION_REFUSALS, tuple(ED.REFUSALS))
        self.assertEqual(IB.AUTHORIZATION_VIEW, ED.VIEW_FIELDS)
        self.assertEqual(E.KIND, ED.OPERATION_KIND)
        self.assertEqual(f'^{IB.DECISION_ID.pattern}$', D.UUID4.pattern)
        for code in IB.AUTHORIZATION_REFUSALS:
            self.assertIn(code, IB.CODES)


class TheSelectionGrammars(unittest.TestCase):
    """The select-models subject (integrations/owner/delegated_decision.py, S-03.5 slice 2) repeats the broker's
    family and model grammars, and the broker's provider-envelope kind."""
    category = 'unit'

    def test_they_equal_the_brokers(self):
        G = S._load('delegated_decision', S.REPO / 'integrations' / 'owner' / 'delegated_decision.py')
        for name in ('FAMILY_ID', 'MODEL_NAME', 'WILDCARD'):
            with self.subTest(name):
                self.assertEqual(getattr(G, name).pattern, getattr(IB, name).pattern)
        self.assertEqual(G.ENVELOPE_KIND, E.KIND)


class TheEnvelopeCommand(unittest.TestCase):
    """inference_broker.py envelope: the live envelope and its manifest; it reads no credential, store, log or
    listener."""
    category = 'unit'

    def run_command(self, raw, *argv):
        ctx = IB.Context(component=lambda: raw, provider=V.refuse, store=V.refuse, logs=V.refuse, stdin=None,
                         out=io.StringIO(), err=io.StringIO(), wait=V.refuse, authorization=V.refuse,
                         allow_ephemeral=True)
        return IB.main(['envelope', *argv], ctx), ctx

    def test_it_reports_the_envelope_and_the_manifest_as_a_json_string(self):
        code, ctx = self.run_command(V.component(), '--operation', V.OPERATION)
        self.assertEqual(code, 0, ctx.err.getvalue())
        report = json.loads(ctx.out.getvalue())
        self.assertEqual(report['format'], 'aieh-provider-envelope-report/1')
        self.assertEqual(report['digest'], GOLDEN_DIGEST)
        self.assertEqual(report['manifest'], {'path': f'operations/{V.OPERATION}.json', 'text': GOLDEN_MANIFEST,
                                              'digest': GOLDEN_MANIFEST_DIGEST})
        self.assertNotIn('\\r', ctx.out.getvalue())
        code, ctx = self.run_command(V.component())
        self.assertEqual(code, 0, ctx.err.getvalue())
        report = json.loads(ctx.out.getvalue())
        self.assertEqual((report['operation'], report['manifest']), (None, None))

    def test_its_refusals(self):
        loopback = V.component(origin='http://127.0.0.1:9')
        for raw, code in ((V.component(envelope=None), 'ENVELOPE_NOT_CONFIGURED'),
                          (loopback, 'ENVELOPE_FAMILIES_UNBOUND'),
                          (V.component(envelope=V.block(limit=dict(V.RETIRED_LIMIT))), 'CONFIG_ENVELOPE_INVALID')):
            with self.subTest(code=code):
                exit_code, ctx = self.run_command(raw)
                self.assertEqual(exit_code, 2)
                self.assertIn(f'{code}: ', ctx.err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.run_command(V.component(), '--operation', 'Not/An/Id')
        self.assertEqual(caught.exception.code, 2)


# ---------------------------------------------------------------- serve: the start refusals (integration)


class StartRefusals(V.EnvelopeCase):
    """Proof rows A1 to A11 and the slice-1 refusals of the selection: serve refuses before it reads the provider
    key or opens a listener."""

    def test_a1_a_non_loopback_family_without_an_envelope_block(self):
        self.assertStartRefused(V.component(envelope=None), 'ENVELOPE_NOT_CONFIGURED', decisions=V.refuse)
        self.assertFalse(self.db.exists())   # no store was opened

    def test_a2_missing_an_empty_store_no_decision_source_or_a_failed_receipt_only(self):
        raw = V.component()
        self.assertStartRefused(raw, 'ENVELOPE_NOT_AUTHORIZED')                  # an empty store
        self.db.unlink()                                                         # (serve created it: disclosed)
        self.assertStartRefused(raw, 'ENVELOPE_NOT_AUTHORIZED', decisions=None)  # no decision source
        self.assertFalse(self.db.exists())                                       # no store was opened
        result = self.authorize(raw, on_merge='move-head')                       # the fake Gitea answers 409
        self.assertEqual((result.code, result.refusal), ('HEAD_STALE', False))
        self.assertStartRefused(raw, 'ENVELOPE_NOT_AUTHORIZED')

    def test_a3_an_unsettled_receipt_alone_or_after_the_confirmed_one(self):
        raw = V.component()
        result = self.authorize(raw, on_merge='drop')                            # the merge answer is lost
        self.assertEqual(result.code, 'OUTCOME_UNKNOWN')
        detail = self.assertStartRefused(raw, 'ENVELOPE_AUTHORIZATION_UNRESOLVED').err.getvalue()
        self.assertIn('resolve', detail)

    def test_a3_an_unknown_receipt_after_the_confirmed_one(self):
        raw = V.component()
        self.confirmed(raw, 'op-envelope-0001')
        result = self.authorize(raw, 'op-envelope-0002', on_merge='drop')
        self.assertEqual(result.code, 'OUTCOME_UNKNOWN')
        self.assertStartRefused(raw, 'ENVELOPE_AUTHORIZATION_UNRESOLVED')

    def test_a4_an_expired_authorization(self):
        raw = V.component()
        self.confirmed(raw)
        self.assertStartRefused(raw, 'ENVELOPE_EXPIRED', clock=V.AT_EXPIRY)
        self.assertStartRefused(raw, 'ENVELOPE_EXPIRED', clock=V.AT_EXPIRY + 86400)

    def test_a5_a_superseded_authorization_put_back_is_a_replay(self):
        first = V.component()
        second = V.component(envelope=V.block(expires_at='2026-12-02T00:00:00Z'))
        self.confirmed(first, 'op-envelope-0001')
        self.confirmed(second, 'op-envelope-0002')
        self.assertStartRefused(first, 'ENVELOPE_REPLAYED')

    def test_a6_another_origin(self):
        self.confirmed(V.component())
        self.assertStartRefused(V.component(origin=V.OTHER_ORIGIN), 'ENVELOPE_MISMATCH')

    def test_a7_another_expiry(self):
        self.confirmed(V.component())
        for name, envelope in (('an earlier expires_at', V.block(expires_at='2026-11-30T23:00:00Z')),
                               ('a later expires_at', V.block(expires_at='2026-12-02T00:00:00Z'))):
            with self.subTest(name):
                self.assertStartRefused(V.component(envelope=envelope), 'ENVELOPE_MISMATCH')

    def test_the_model_selection_is_part_of_the_digest(self):
        """C1 within slice 1: selection envelope; a configured model changed, removed or added is a mismatch."""
        self.confirmed(V.component(models=(S.MODEL_A, S.MODEL_B)))
        for models in ((S.MODEL_A, S.MODEL_C), (S.MODEL_A,), (S.MODEL_A, S.MODEL_B, S.MODEL_C)):
            with self.subTest(models=models):
                self.assertStartRefused(V.component(models=models), 'ENVELOPE_MISMATCH')
        self.assertStartRefused(V.component(models=(S.MODEL_A, S.MODEL_B),
                                            envelope=V.block(selection='delegation')), 'ENVELOPE_MISMATCH')

    def test_a_receipt_over_a_v1_document_does_not_authorize_a_start(self):
        """S-03.6: a confirmed receipt of the real recorder over the canonical manifest of a correctly formed /1
        document of the same families (S-03.5's format, with its limit) names a digest no live envelope has: alone
        it is a mismatch; recorded after a /2 authorization it governs, and the /2 digest is then a replay."""
        raw = V.component()
        result = self.recorder.authorize(V.manifest_bytes_v1(raw), V.OPERATION)
        self.assertEqual(result['receipt']['state'], 'confirmed')
        self.assertEqual((result['decision']['subject']['target'], result['decision']['subject']['digest']),
                         (GOLDEN_V1_DIGEST, GOLDEN_V1_MANIFEST_DIGEST))
        self.assertStartRefused(raw, 'ENVELOPE_MISMATCH')
        self.confirmed(raw, 'op-envelope-0002')                                  # the /2 envelope authorized
        code, ctx = self.serve(raw, lambda broker: None)
        self.assertEqual(code, 0, ctx.err.getvalue())
        self.assertEqual(self.recorder.authorize(V.manifest_bytes_v1(raw, 'op-envelope-0003'), 'op-envelope-0003')[
            'receipt']['state'], 'confirmed')                                    # a later /1 receipt governs
        self.assertStartRefused(raw, 'ENVELOPE_REPLAYED')

    def test_a8_the_governing_target_is_another_envelopes(self):
        raw = V.component()
        document, _digest = IB.live_envelope(config(raw))
        other = IB.live_envelope(config(V.component(origin=V.OTHER_ORIGIN)))[1]
        text = json.dumps({'operation': V.OPERATION, 'kind': E.KIND, 'target': other,
                           'expiresAt': V.EXPIRES, 'envelope': document}, indent=2) + '\n'
        self.assertEqual(self.recorder.authorize(text.encode(), V.OPERATION)['receipt']['state'], 'confirmed')
        self.assertStartRefused(raw, 'ENVELOPE_MISMATCH')

    def test_a9_the_target_is_live_but_the_merged_manifest_is_not_canonical(self):
        raw = V.component()
        canonical = V.manifest_bytes(raw)
        data = json.loads(canonical)
        data['envelope']['origin'] = 'https://api.other-provider.test:443'   # the member the Owner read
        altered = (json.dumps(data, indent=2) + '\n').encode()
        cases = (('the envelope member', altered), ('the bytes', canonical.replace(b'\n', b'\r\n')),
                 ('the indentation', (json.dumps(json.loads(canonical), indent=4) + '\n').encode()))
        for number, (name, blob) in enumerate(cases, 1):
            with self.subTest(name):
                operation = f'op-envelope-{number:04d}'
                blob = blob.replace(V.OPERATION.encode(), operation.encode())
                self.assertEqual(self.recorder.authorize(blob, operation)['receipt']['state'], 'confirmed')
                self.assertEqual(json.loads(blob)['target'], IB.live_envelope(config(raw))[1])
                detail = self.assertStartRefused(raw, 'ENVELOPE_MISMATCH').err.getvalue()
                self.assertIn('canonical manifest', detail)

    def hand_written(self, change, actor):
        """A copy of the confirmed receipt under a new nonce, changed by CHANGE and reserved by ACTOR (by hand)."""
        store = self.open_store()
        (source,) = [a for a in store.attempts() if a.operation_key.startswith(AR.RECEIPT_PREFIX)]
        intent = json.loads(source.intent_json)
        nonce = 'ab' * 16
        intent['decision']['shown']['nonce'] = nonce
        intent['decision']['decisionId'] = '0b1c2d3e-4f50-4617-8293-a4b5c6d7e8f9'
        change(intent)
        key = AR.RECEIPT_PREFIX + nonce
        store.reserve(key, intent, actor=actor)
        store.transition(key, 'dispatched', actor=actor, reason='by hand', expected_from='reserved')
        store.transition(key, 'confirmed', actor=actor, reason='by hand', expected_from='dispatched')
        store.close()

    def test_a10_a_receipt_reserved_by_another_actor(self):
        raw = V.component()
        self.confirmed(raw)
        self.hand_written(lambda intent: None, 'someone-else')
        self.assertStartRefused(raw, 'ENVELOPE_RECORD_INVALID')

    def test_a10_a_statement_attributed_to_an_agent(self):
        raw = V.component()
        self.confirmed(raw)
        self.hand_written(lambda intent: intent['decision']['statement'].update(attributedTo='agent:fixture-model'),
                          ED.RECORDER)
        self.assertStartRefused(raw, 'ENVELOPE_RECORD_INVALID')

    def test_a_decision_source_that_raises_or_answers_badly(self):
        raw = V.component()
        self.confirmed(raw)
        view = ED.verifier(self.open_store())(GOLDEN_DIGEST, lambda op: E.manifest_digest(
            IB.live_envelope(config(raw))[0], op), datetime.datetime.fromtimestamp(V.DURING, V.UTC)).view
        self.assertIsNotNone(view)

        def answering(answer):
            return lambda store: (lambda *args: answer)

        def raising(store):
            raise RuntimeError('synthetic decision source failure')
        for name, decisions in (('raises', raising), ('a list', answering([None, '', view])),
                                ('an unknown code', answering(ED.Verdict('SOMETHING_ELSE', '', None))),
                                ('another target', answering(ED.Verdict(None, '', {**view, 'target': 'sha256:' +
                                                                                   '0' * 64}))),
                                ('another manifest', answering(ED.Verdict(None, '', {**view, 'digest': 'sha256:' +
                                                                                     '0' * 64}))),
                                ('another expiry', answering(ED.Verdict(None, '', {**view, 'expiresAt':
                                                                                   '2027-01-01T00:00:00Z'}))),
                                ('a field more', answering(ED.Verdict(None, '', {**view, 'extra': 1})))):
            with self.subTest(name):
                self.assertStartRefused(raw, 'ENVELOPE_RECORD_INVALID', decisions=decisions)

    def test_a11_the_one_upstream_origin_and_provider(self):
        beside = {'provider': S.PROVIDER, 'models': [S.MODEL_A]}
        for name, others in (('two origins', {'openai-chat': {**beside, 'upstream': V.OTHER_ORIGIN}}),
                             ('two providers', {'openai-chat': {**beside, 'provider': S.OTHER_PROVIDER,
                                                                'upstream': V.ORIGIN}}),
                             ('a loopback family naming the provider',
                              {'openai-chat': {**beside, 'upstream': 'http://127.0.0.1:9'}})):
            with self.subTest(name):
                self.assertStartRefused(V.component(others=others), 'ENVELOPE_FAMILIES_UNBOUND',
                                        decisions=V.refuse)

    def test_a_delegated_selection_without_a_record_is_missing(self):
        """Slice 1 refuses selection delegation at start (no selection record can be read yet); slice 2 reads
        the record, and the same configuration with no record stays MODEL_SELECTION_MISSING."""
        raw = V.component(envelope=V.block(selection='delegation'))
        self.confirmed(raw)
        self.assertStartRefused(raw, 'MODEL_SELECTION_MISSING')

    def test_an_envelope_selection_that_names_no_model_is_missing(self):
        raw = V.component(models=())
        self.confirmed(raw)
        self.assertStartRefused(raw, 'MODEL_SELECTION_MISSING')


# ---------------------------------------------------------------- serve: started (integration)


class Started(V.EnvelopeCase):
    def test_b1_a_confirmed_unexpired_receipt_starts_the_broker(self):
        raw = V.component()
        result = self.confirmed(raw)
        order, seen = [], {}
        provider = S.MemoryProvider({IB.ENTRY: (S.PROVIDER, S.KEY)})

        def decisions(store):
            verify = ED.verifier(store)

            def answer(*args):
                order.append('verifier')
                return verify(*args)
            return answer

        def asked():
            order.append('provider')
            return provider

        def wait(broker):
            seen['status'] = broker.status()
        code, ctx = self.serve(raw, wait, decisions=decisions, provider=asked)
        self.assertEqual(code, 0, ctx.err.getvalue())
        self.assertEqual(order, ['verifier', 'provider'])
        expected = {'receipt': result['receipt']['operation_key'], 'operation': V.OPERATION,
                    'decision': result['decision']['decisionId'], 'digest': GOLDEN_DIGEST,
                    'expires_at': V.EXPIRES, 'selection': {'by': 'envelope', 'models': {
                        'anthropic-messages': [S.MODEL_A]}}}
        self.assertEqual(seen['status']['authorization'], expected)
        self.assertEqual(json.loads(ctx.out.getvalue())['authorization'], expected)
        (start,) = self.start_receipts()
        self.assertEqual(start['authorization'], expected)
        events = [json.loads(line)['event'] for path in (self.tmp / 'logs').glob('audit-*.jsonl')
                  for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events, ['broker-start', 'broker-stop'])     # no request was sent

    def test_b2_the_envelope_kind_is_recorded_through_the_recorder(self):
        """The manifest printed by the envelope command, prepared and recorded by the real recorder."""
        raw = V.component()
        ctx = IB.Context(component=lambda: raw, provider=V.refuse, store=V.refuse, logs=V.refuse, stdin=None,
                         out=io.StringIO(), err=io.StringIO(), wait=V.refuse, allow_ephemeral=True)
        self.assertEqual(IB.main(['envelope', '--operation', V.OPERATION], ctx), 0, ctx.err.getvalue())
        manifest = json.loads(ctx.out.getvalue())['manifest']
        blob = manifest['text'].encode('utf-8')
        self.assertEqual(blob, GOLDEN_MANIFEST.encode('utf-8'))
        number = self.recorder.gitea.propose({manifest['path']: blob}, branch='work/envelope')
        store = self.open_store()
        actx = AR.Context(self.tmp / 'authz-state', store, V.fg.FixtureProvider(V.su.owner_entry()), 3000,
                          http=self.recorder.gitea, now=lambda: V.su.NOW, policies=AR.exercise_policies(),
                          verifier=V.su.FakeVerifier())
        challenge = AR.prepare(actx, V.fg.REPOSITORY, number)
        self.assertIn(GOLDEN_MANIFEST.rstrip('\n'), challenge['shown']['summary'])
        self.assertEqual(challenge['subject']['digest'], GOLDEN_MANIFEST_DIGEST)
        result = AR.record(actx, challenge['shown']['nonce'], V.su.statement(V.OPERATION),
                           recorded_by=V.su.RECORDED_BY)
        self.assertEqual(result['receipt']['state'], 'confirmed')
        subject = result['decision']['subject']
        self.assertEqual((subject['operationKind'], subject['target'], subject['digest'], subject['expiresAt']),
                         ('provider-envelope', GOLDEN_DIGEST, GOLDEN_MANIFEST_DIGEST, V.EXPIRES))
        self.assertEqual(result['merge']['digest'], GOLDEN_MANIFEST_DIGEST)   # the fake kept the bytes
        store.close()
        code, ctx = self.serve(raw, lambda broker: None)
        self.assertEqual(code, 0, ctx.err.getvalue())

    def test_g2_the_component_is_read_once(self):
        raw = V.component()
        self.confirmed(raw)
        answers = [raw, V.component(origin=V.OTHER_ORIGIN)]
        reads = []

        def component():
            reads.append(1)
            return answers[len(reads) - 1]
        seen = {}
        code, ctx = self.serve(raw, lambda broker: seen.update(broker.status()), component=component)
        self.assertEqual(code, 0, ctx.err.getvalue())
        self.assertEqual(len(reads), 1)
        upstreams = {f['id']: f['upstream'] for f in seen['families']}
        self.assertEqual(upstreams['anthropic-messages'], ORIGIN_TEXT)


class LoopbackAsToday(V.EnvelopeCase):
    """Proof rows F2 and F3: with only loopback upstreams no line of the precondition runs."""

    START_MEMBERS = {'format', 'service', 'started_at', 'pid', 'listeners', 'audit_file', 'provider_key', 'families'}
    STATUS_MEMBERS = {'format', 'listeners', 'provider_key', 'families', 'grants', 'audit', 'start_receipt'}

    def test_f2_loopback_upstreams_start_issue_and_pass_through_without_a_decision_source(self):
        upstream = S.FakeUpstream('openai-chat')
        self.addCleanup(upstream.close)
        raw = S.component({'openai-chat': upstream.origin})
        seen = {}

        def wait(broker):
            grant = broker.issue({'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': 'openai-chat',
                                  'models': [S.MODEL_A], 'ttl_s': 60})
            seen['answer'] = S.request(broker.listeners['inference']['port'], 'POST', '/v1/chat/completions',
                                       {'model': S.MODEL_A}, [S.auth('openai-chat', grant['token'])])
            seen['status'] = broker.status()
        code, ctx = self.serve(raw, wait, decisions=V.refuse)
        self.assertEqual(code, 0, ctx.err.getvalue())
        self.assertEqual(seen['answer'][0], 200)
        self.assertEqual(set(seen['status']), self.STATUS_MEMBERS)
        (start,) = self.start_receipts()
        self.assertEqual(set(start), self.START_MEMBERS)

    def test_f3_only_an_ip_literal_is_loopback(self):
        for origin in ('http://127.0.0.1:9', 'https://127.0.0.1:9', 'http://[::1]:9', 'http://127.1.2.3:9'):
            with self.subTest(origin=origin):
                code, ctx = self.serve(V.component(origin=origin, envelope=None), lambda broker: None,
                                       decisions=V.refuse)
                self.assertEqual(code, 0, ctx.err.getvalue())
        for origin in ('https://localhost', 'https://localhost:9', 'https://127.0.0.1.example.test'):
            with self.subTest(origin=origin):
                self.assertStartRefused(V.component(origin=origin, envelope=None), 'ENVELOPE_NOT_CONFIGURED',
                                        decisions=V.refuse)


# ---------------------------------------------------------------- the held authorization (integration)


class HeldAuthorization(V.EnvelopeCase):
    """Proof rows E1, G1 and G2 on the Broker itself."""

    def test_g1_a_broker_built_directly_cannot_skip_the_start_check(self):
        raw = V.component()
        self.confirmed(raw)
        authorization = V.minted(raw, self.db)
        for name, held in (('none', None), ('hand-built', dataclasses.replace(authorization))):
            with self.subTest(name):
                rig = V.BoundRig(raw, held, connect=V.refuse)
                self.addCleanup(rig.close)
                with self.assertRaises(IB.InferenceError) as caught:
                    rig.broker.start()
                self.assertEqual(caught.exception.code, 'ENVELOPE_NOT_AUTHORIZED')
                self.assertEqual(rig.broker.listeners, {})
        rig = V.BoundRig(raw, authorization, connect=V.refuse)      # the minted one starts
        self.addCleanup(rig.close)
        rig.start()
        self.assertEqual(rig.broker.status()['authorization']['digest'], GOLDEN_DIGEST)

    def test_g2_a_family_that_is_not_the_held_origin(self):
        raw = V.component()
        self.confirmed(raw)
        authorization = V.minted(raw, self.db)
        rig = V.BoundRig(V.component(origin=V.OTHER_ORIGIN), authorization, connect=V.refuse)
        self.addCleanup(rig.close)
        with self.assertRaises(IB.InferenceError) as caught:
            rig.broker.start()
        self.assertEqual(caught.exception.code, 'ENVELOPE_MISMATCH')
        self.assertEqual(rig.broker.listeners, {})

    def test_g2_at_admission_the_held_origin_and_authorization_are_checked(self):
        upstream = S.FakeUpstream('anthropic-messages')
        self.addCleanup(upstream.close)
        raw = V.component()
        self.confirmed(raw)
        connector = V.Connector({ORIGIN_TEXT: upstream})
        rig = V.BoundRig(raw, V.minted(raw, self.db), connect=connector)
        self.addCleanup(rig.close)
        rig.start()
        token = rig.issue(family='anthropic-messages', ttl=3600)['token']

        def send():
            return S.request(rig.inference, 'POST', '/v1/messages', {'model': S.MODEL_A},
                             [S.auth('anthropic-messages', token)])
        self.assertEqual(send()[0], 200)
        family = rig.broker.config.families['anthropic-messages']
        rig.broker.config.families['anthropic-messages'] = dataclasses.replace(
            family, upstream=IB.parse_origin(V.OTHER_ORIGIN))
        status, _, body = send()
        self.assertEqual((status, json.loads(body)['aieh_refusal']['code']), (503, 'ENVELOPE_MISMATCH'))
        rig.broker.config.families['anthropic-messages'] = family
        held = rig.broker.authorization
        rig.broker.authorization = dataclasses.replace(held)                  # not minted: not held
        status, _, body = send()
        self.assertEqual((status, json.loads(body)['aieh_refusal']['code']), (503, 'ENVELOPE_NOT_AUTHORIZED'))
        rig.broker.authorization = held
        self.assertEqual(send()[0], 200)
        self.assertEqual(connector.seen, [ORIGIN_TEXT, ORIGIN_TEXT])

    def test_e1_the_expiry_while_serving(self):
        bound = S.FakeUpstream('anthropic-messages')
        local = S.FakeUpstream('openai-chat')
        for fake in (bound, local):
            self.addCleanup(fake.close)
        raw = V.component(models=(S.MODEL_A, 'syn-gated'),
                          others={'openai-chat': {'provider': None, 'upstream': local.origin,
                                                  'models': [S.MODEL_A]}})
        self.confirmed(raw)
        connector = V.Connector({ORIGIN_TEXT: bound, IB.parse_origin(local.origin).text(): local})
        rig = V.BoundRig(raw, V.minted(raw, self.db), connect=connector)
        self.addCleanup(rig.close)
        rig.start()
        token = rig.issue(family='anthropic-messages', models=(S.MODEL_A, 'syn-gated'), ttl=86400)['token']
        local_token = rig.issue(family='openai-chat', ttl=86400)['token']

        def bound_request(model, stream=False):
            return S.request(rig.inference, 'POST', '/v1/messages', {'model': model, 'stream': stream},
                             [S.auth('anthropic-messages', token)])

        def local_request():
            return S.request(rig.inference, 'POST', '/v1/chat/completions', {'model': S.MODEL_A},
                             [S.auth('openai-chat', local_token)])
        rig.clock.now = V.AT_EXPIRY - 1                                       # before the expiry: admitted
        self.assertEqual(bound_request(S.MODEL_A)[0], 200)
        self.assertEqual(connector.seen[-1], ORIGIN_TEXT)
        self.assertIn(('x-api-key', S.KEY), bound.requests[-1]['headers'])
        streamed = []
        thread = threading.Thread(target=lambda: streamed.append(bound_request('syn-gated', stream=True)))
        thread.start()
        self.assertTrue(bound.first_sent.wait(30))
        for moment in (V.AT_EXPIRY, V.AT_EXPIRY + 3600):                       # at and after: refused
            rig.clock.now = moment
            status, _, body = bound_request(S.MODEL_A)
            self.assertEqual((status, json.loads(body)['aieh_refusal']['code']), (403, 'ENVELOPE_EXPIRED'))
            self.assertEqual(local_request()[0], 200)                          # the loopback family is served
        bound.release.set()
        thread.join(30)
        self.assertEqual(streamed[0][0], 200)                                  # the answer already streaming
        self.assertIn(S.ANSWER_MARKER.encode(), streamed[0][2])
        self.assertEqual(len(bound.requests), 2)
        codes = [line['code'] for line in rig.audit_lines() if line.get('event') == 'request']
        self.assertEqual(codes.count('ENVELOPE_EXPIRED'), 2)


if __name__ == '__main__':
    unittest.main()
