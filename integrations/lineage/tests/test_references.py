"""Tests for integrations/lineage/lineage.py: the typed references, their canonical text,
the schema, the span anchor, Resolution and the Registry (stdlib unittest, plan leaf P-03.1).

Offline and pure: nothing here runs a tool or opens a store. Run from the repository root:

    python -I -B -m unittest discover -s integrations/lineage/tests -v
"""
import copy
import hashlib
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
LINEAGE_DIR = HERE.parent
REPO = LINEAGE_DIR.parents[1]


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


L = _load('lineage', LINEAGE_DIR / 'lineage.py')
intent_checker = _load('aieh_check_intent_record', REPO / 'tools' / 'check_intent_record.py')

C40 = '6e79b3e42d06146624cde5ffc52ae29a892c5205'
C64 = 'ab' * 32
D = hashlib.sha256(b'digest').hexdigest()
D2 = hashlib.sha256(b'other').hexdigest()
KEY = 'fx1-' + hashlib.sha256(b'key').hexdigest()
UUID = '929f0d8a-f3d8-4da3-8ac3-9d0017709d71'
OUTCOME = '5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a'

# One or more typed values per kind, including native ids that need percent-encoding.
VALUES = [
    L.ConversationRef('thread-42'),
    L.ConversationRef('thread 42/é', through_message='message:8'),
    L.MessageRef('thread-42', 'message-8'),
    L.MessageRef('qual-02', 'message-1', D),
    L.MessageRef('qual-08', 'message-1', D, 0, 1),
    L.MessageRef('t%', 'm#@/?=,', D, 12, 57),
    L.ObjectiveRef(OUTCOME),
    L.ObjectiveRef(OUTCOME, C64),
    L.DesignRef('qual-02-search-freshness', 'design.md', C40, D),
    L.DesignRef('a-b', 'specs/x/spec.md', C64, D),
    L.WorkRef('TASK-2'),
    L.WorkRef('TASK-1.2', C40),
    L.AttemptRef(UUID),
    L.AttemptRef(UUID, event='evt 1/2'),
    L.CommitRef('ai-engineering-harness', C40),
    L.CommitRef('owner/name.git', C64),
    L.ReviewRef('example/project', 7, 31, C40),
    L.CIRef('example/project', 1234, C40),
    L.AuthorizationRef('example/ops', 'authz/main', C40, D),
    L.EffectReceiptRef(KEY),
    L.EffectReceiptRef(KEY, 4, D),
]

MALFORMED = [
    # no scheme, unknown scheme handled separately, not text
    '', 'conversation', ':x', 'Conversation:t/m',
    # conversation and message
    'conversation:', 'conversation:t/', 'conversation:/m', 'conversation:t/m/x', 'conversation:t m/x',
    'conversation:a%2fb/c',                       # lower-case percent hex
    'conversation:%41/m',                         # an unreserved byte percent-encoded
    'conversation:%FF/m',                         # not UTF-8
    'conversation:t/m#sha256:' + D[:63],          # short digest
    'conversation:t/m#sha256:' + D.upper(),       # upper-case digest
    'conversation:t/m#span:0+5',                  # span without digest
    'conversation:t/m#span:0+0:sha256:' + D,      # empty span
    'conversation:t/m#span:01+5:sha256:' + D,     # non-canonical decimal
    'conversation:t/m#span:-1+5:sha256:' + D,
    'conversation:t/m#sha256:' + D + '#sha256:' + D,
    'conversation:t@',
    # objective
    'outcome:', 'outcome:O-1@main', 'outcome:O-1@' + C40[:7],
    'outcome:O-101', 'outcome:' + OUTCOME.upper(), 'outcome:' + OUTCOME + '@' + C40[:12],
    'outcome:' + OUTCOME[:-1], 'outcome:' + OUTCOME + '@main', 'outcome:{' + OUTCOME + '}',
    # design (P-02.1 form)
    'openspec:changes/editor-shutdown@' + C40,     # the blueprint's change-level notation
    'openspec:changes/x/design.md@' + C40,         # no digest
    'openspec:changes/x/../design.md@' + C40 + '#sha256=' + D,
    'openspec:changes/X/design.md@' + C40 + '#sha256=' + D,
    'openspec:changes/x/design.md@' + C40 + '#sha256:' + D,
    'openspec:changes/x/design.md@HEAD#sha256=' + D,
    # work
    'backlog:', 'backlog:task-2', 'backlog:T204', 'backlog:TASK-2@main', 'backlog:TASK-2@' + C40[:12],
    'backlog:TASK-2@' + C40 + '#sha256:' + D,
    # attempt
    'openhands:conversation/' + UUID.upper(), 'openhands:conversation/123', 'openhands:run/1234',
    'openhands:conversation/' + UUID + '@',
    # commit
    'git:repo', 'git:repo@main', 'git:repo@' + C40[:39], 'git:@' + C40, 'git:../x@' + C40,
    'git:repo@' + C40.upper(),
    # gitea kinds
    'gitea:repo/pulls/7/reviews/31@' + C40,        # repository must be owner/name
    'gitea:o/r/pulls/0/reviews/31@' + C40, 'gitea:o/r/pulls/7/reviews/31',
    'gitea:o/r/actions/runs/1234', 'gitea:o/r/actions/runs/x@' + C40,
    'gitea:o/r/branches/main@' + C40,              # authorization without the manifest digest
    'gitea:o/r/branches/a/b@' + C40 + '#sha256:' + D,  # a / in a branch must be encoded
    # effect receipt
    'effect:fx1-' + 'a' * 63, 'effect:fx2-' + 'a' * 64, 'effect:' + KEY + '@3', 'effect:' + KEY + '#sha256:' + D,
    'effect:' + KEY + '@0#sha256:' + D,
    # unknown kinds have no form
    'catalog:engineer@sha256:' + D, 'release:x',
]


class RoundTrip(unittest.TestCase):
    def test_every_value_round_trips(self):
        kinds = set()
        for value in VALUES:
            with self.subTest(value=value):
                text = L.format_reference(value)
                self.assertEqual(text, value.text)
                parsed = L.parse(text)
                self.assertEqual(parsed, value)
                self.assertIs(type(parsed), type(value))
                self.assertEqual(L.format_reference(parsed), text)
                kinds.add(value.kind)
        self.assertEqual(kinds, set(L.BY_KIND), 'every typed kind is covered')

    def test_every_schema_example_round_trips(self):
        for entry in L.load_schema()['kinds']:
            for text in entry.get('examples') or []:
                with self.subTest(kind=entry['kind'], text=text):
                    ref = L.parse(text)
                    self.assertEqual(ref.kind, entry['kind'])
                    self.assertEqual(ref.text, text)

    def test_native_ids_are_opaque_and_canonically_encoded(self):
        ref = L.MessageRef('thread 42/é', 'm#@/?=,%')
        self.assertEqual(ref.text, 'conversation:thread%2042%2F%C3%A9/m%23%40%2F%3F%3D%2C%25')
        self.assertEqual(L.parse(ref.text), ref)
        self.assertEqual(L.decode_segment('a~b.c_d-e'), 'a~b.c_d-e')
        for text, why in (('%41', 'not canonically encoded'), ('a%2Fb%2f', 'not a segment'),
                          ('%C3', 'not UTF-8'), ('%FF', 'not UTF-8'), ('', 'not a segment')):
            with self.subTest(text=text), self.assertRaises(L.MalformedReference) as caught:
                L.decode_segment(text)
            self.assertIn(why, caught.exception.message)

    def test_design_reuses_the_p021_pointer_unchanged(self):
        planning = L.planning
        text = f'openspec:changes/qual-02-search-freshness/design.md@{C40}#sha256={D}'
        pointer = planning.Pointer.parse(text)
        ref = L.parse(text)
        self.assertEqual(ref.text, pointer.text)
        self.assertEqual(ref.pointer, pointer)
        self.assertIs(L.DesignRef.PATTERN, planning.POINTER_RE)

    def test_identity_drops_the_anchor(self):
        self.assertEqual(L.parse('backlog:TASK-2').identity(), L.parse('backlog:TASK-2@' + C40).identity())
        self.assertEqual(L.parse('effect:' + KEY).identity(), L.EffectReceiptRef(KEY, 4, D).identity())
        self.assertEqual(L.MessageRef('t', 'm').identity(), L.MessageRef('t', 'm', D, 0, 3).identity())
        self.assertFalse(L.parse('backlog:TASK-2').pinned)
        self.assertTrue(L.parse('backlog:TASK-2@' + C40).pinned)


class Malformed(unittest.TestCase):
    def test_malformed_text_is_refused(self):
        for text in MALFORMED:
            with self.subTest(text=text):
                with self.assertRaises(L.MalformedReference) as caught:
                    L.parse(text)
                self.assertIn(caught.exception.code, ('REFERENCE_MALFORMED', 'REFERENCE_UNSUPPORTED_SCHEME'))

    def test_unknown_scheme_is_named(self):
        with self.assertRaises(L.MalformedReference) as caught:
            L.parse('catalog:engineer@x')
        self.assertEqual(caught.exception.code, 'REFERENCE_UNSUPPORTED_SCHEME')

    def test_non_text_is_refused(self):
        for value in (None, 5, b'backlog:TASK-1', ['backlog:TASK-1']):
            with self.subTest(value=value), self.assertRaises(L.MalformedReference):
                L.parse(value)

    def test_invalid_values_cannot_be_constructed(self):
        cases = [
            lambda: L.ConversationRef(''), lambda: L.ConversationRef('t', ''),
            lambda: L.ConversationRef('\ud800'),
            lambda: L.MessageRef('t', 'm', 'x'), lambda: L.MessageRef('t', 'm', None, 0, 3),
            lambda: L.MessageRef('t', 'm', D, 0, 0), lambda: L.MessageRef('t', 'm', D, -1, 3),
            lambda: L.MessageRef('t', 'm', D, 0, None), lambda: L.MessageRef('t', 'm', D, True, 3),
            lambda: L.MessageRef('t', 'm', D, None, 3),
            lambda: L.ReviewRef('o/r', 7, 31, 'x'), lambda: L.CIRef('r', 1, C40),
            lambda: L.AuthorizationRef('r', 'main', C40, D), lambda: L.AuthorizationRef('o/r', 'main', 'x', D),
            lambda: L.EffectReceiptRef(KEY, 3, 'x'),
            lambda: L.ObjectiveRef('O', 'main'), lambda: L.ObjectiveRef('O-101'),
            lambda: L.ObjectiveRef(OUTCOME.upper()), lambda: L.ObjectiveRef(OUTCOME, 'main'),
            lambda: L.DesignRef('X', 'design.md', C40, D), lambda: L.DesignRef('x', '../d.md', C40, D),
            lambda: L.DesignRef('x', 'd.md', C40[:7], D), lambda: L.DesignRef('x', 'd.md', C40, 'x'),
            lambda: L.WorkRef('task-2'), lambda: L.WorkRef('TASK-2', 'HEAD'),
            lambda: L.AttemptRef('not-a-uuid'), lambda: L.AttemptRef(UUID, ''),
            lambda: L.CommitRef('', C40), lambda: L.CommitRef('r', 'HEAD'),
            lambda: L.ReviewRef('r', 7, 31, C40), lambda: L.ReviewRef('o/r', 0, 31, C40),
            lambda: L.ReviewRef('o/r', '7', 31, C40),
            lambda: L.CIRef('o/r', 0, C40), lambda: L.CIRef('o/r', 1, 'x'),
            lambda: L.AuthorizationRef('o/r', 'main', C40, 'x'), lambda: L.AuthorizationRef('o/r', '', C40, D),
            lambda: L.EffectReceiptRef('fx1-x'), lambda: L.EffectReceiptRef(KEY, 3, None),
            lambda: L.EffectReceiptRef(KEY, None, D), lambda: L.EffectReceiptRef(KEY, 0, D),
        ]
        for number, make in enumerate(cases):
            with self.subTest(case=number), self.assertRaises(L.MalformedReference):
                make()

    def test_format_refuses_what_is_not_a_typed_reference(self):
        for value in ('backlog:TASK-1', None, L.Reference()):
            with self.subTest(value=value), self.assertRaises(L.MalformedReference):
                L.format_reference(value)


class Schema(unittest.TestCase):
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.schema = L.load_schema()
        cls.kinds = L.schema_kinds(cls.schema)

    def test_schema_is_consistent_with_the_code(self):
        self.assertEqual(L.check_schema(self.schema), [])

    def test_every_kind_has_authority_identity_and_revision_option(self):
        for kind, entry in self.kinds.items():
            with self.subTest(kind=kind):
                self.assertTrue(entry['authority']['name'])
                self.assertTrue(entry['authority']['system_of_record'])
                self.assertTrue(entry['authority']['blueprint'])
                self.assertTrue(entry['validation_rule'])
                self.assertTrue(entry['citations'])
                if entry['status'] == 'unknown':
                    self.assertFalse(entry['identity']['settled'])
                    self.assertTrue(entry['identity']['unsettled'])
                    self.assertTrue(entry['open'])
                    continue
                self.assertTrue(entry['identity']['native_id'])
                self.assertIn(entry['revision']['pinning'], ('required', 'optional'))
                self.assertTrue(entry['revision']['anchor'])
                cls = L.BY_KIND[kind]
                self.assertEqual(cls.PINNING, entry['revision']['pinning'])

    def test_required_pinning_is_enforced_by_the_grammar(self):
        unpinned = {'design': 'openspec:changes/x/design.md', 'commit': 'git:repo',
                    'review': 'gitea:o/r/pulls/7/reviews/31', 'ci': 'gitea:o/r/actions/runs/1',
                    'authorization': 'gitea:o/r/branches/main@' + C40}
        required = {k for k, e in self.kinds.items() if e['revision']['pinning'] == 'required'}
        self.assertEqual(required, set(unpinned))
        for kind, text in unpinned.items():
            with self.subTest(kind=kind), self.assertRaises(L.MalformedReference):
                L.parse(text)
        for value in VALUES:
            if value.kind in required:
                self.assertTrue(value.pinned, value)

    def test_the_overseer_kinds_and_statuses(self):
        expected = {
            'conversation': 'authority-unavailable', 'message': 'authority-unavailable', 'objective': 'implemented',
            'design': 'implemented', 'work': 'implemented', 'attempt': 'authority-unavailable',
            'commit': 'implemented', 'review': 'authority-unavailable', 'ci': 'authority-unavailable',
            'authorization': 'authority-unavailable', 'effect-receipt': 'implemented', 'release': 'unknown',
            'catalog': 'unknown'}
        self.assertEqual({k: e['status'] for k, e in self.kinds.items()}, expected)
        for kind, entry in self.kinds.items():
            if entry['status'] != 'implemented':
                self.assertEqual(entry['verified'], L.NOT_YET_VERIFIED)
            if entry['status'] == 'authority-unavailable':
                self.assertTrue(all(re.match(r'^[A-Z]-\d{2}(\.\d+)*$', leaf) for leaf in entry['supplied_by']))

    def test_outcomes_are_defined(self):
        self.assertEqual(set(self.schema['outcomes']), set(L.OUTCOMES))

    def test_canonical_forms_except_design_are_intent_record_references(self):
        """Every kind but design can be cited as an intent-record/v1 source or acceptance."""
        self.assertEqual(intent_checker.REFERENCE.pattern, r'^[a-z][a-z0-9+.-]*:[^\s=,]+$')
        for value in VALUES:
            with self.subTest(value=value):
                matches = bool(intent_checker.REFERENCE.match(value.text))
                self.assertEqual(matches, value.kind != 'design')

    def test_schema_check_catches_each_defect(self):
        def broken(mutate):
            schema = copy.deepcopy(self.schema)
            mutate(schema, L.schema_kinds(schema))
            return L.check_schema(schema)

        # Each defect, and the problem that must name it (so one rule cannot mask another).
        mutations = {
            'format': (lambda s, k: s.update(format='x'), 'format must be'),
            'version': (lambda s, k: s.update(schema_version=2), 'schema_version must be'),
            'outcomes': (lambda s, k: s['outcomes'].pop('ambiguous'), 'outcomes must define exactly'),
            'no kinds': (lambda s, k: s.update(kinds=[]), 'kinds must be a non-empty list'),
            'entry not an object': (lambda s, k: s['kinds'].append(5), 'every kind entry must be an object'),
            'duplicate kind': (lambda s, k: s['kinds'].append(copy.deepcopy(k['work'])), 'kinds must be unique'),
            'status': (lambda s, k: k['attempt'].update(status='pending'), 'status must be one of'),
            'authority name': (lambda s, k: k['commit']['authority'].update(name=''), 'authority.name is required'),
            'authority': (lambda s, k: k['commit']['authority'].pop('system_of_record'),
                          'authority.system_of_record is required'),
            'authority passage': (lambda s, k: k['commit']['authority'].update(blueprint=' '),
                                  'authority.blueprint'),
            'identity settled': (lambda s, k: k['commit']['identity'].pop('settled'),
                                 'identity.settled must be true or false'),
            'native id': (lambda s, k: k['commit']['identity'].update(native_id=''), 'identity.native_id is required'),
            'pinning': (lambda s, k: k['work']['revision'].update(pinning='never'),
                        'revision.pinning must be required or optional'),
            'pinning differs': (lambda s, k: k['work']['revision'].update(pinning='required'),
                                "revision.pinning must be 'optional'"),
            'anchor': (lambda s, k: k['work']['revision'].update(anchor=None), 'revision.anchor is required'),
            'validation rule': (lambda s, k: k['design'].pop('validation_rule'), 'validation_rule is required'),
            'citations': (lambda s, k: k['design'].update(citations=[]), 'citations are required'),
            'unknown but settled': (lambda s, k: k['release']['identity'].update(settled=True),
                                    'status unknown exactly when'),
            'settled but unknown': (lambda s, k: k['commit'].update(status='unknown'), 'status unknown exactly when'),
            'unknown without open': (lambda s, k: k['release'].update(open=[]), 'lists what is open'),
            'unavailable without leaf': (lambda s, k: k['attempt'].update(supplied_by=[]),
                                         'names the leaves that supply it'),
            'unverified claim': (lambda s, k: k['attempt'].update(verified='verified'), 'verified must be'),
            'resolver on unavailable': (lambda s, k: k['attempt'].update(resolver='x'),
                                        'only an implemented kind names a resolver'),
            'implemented without resolver': (lambda s, k: k['design'].update(resolver=None), 'resolver is required'),
            'outcomes without resolved': (lambda s, k: k['design'].update(outcomes=['missing', 'authority-unavailable']),
                                          "outcomes must list the resolver's outcomes"),
            'unsupported as an outcome': (lambda s, k: k['design']['outcomes'].append('unsupported-kind'),
                                          "outcomes must list the resolver's outcomes"),
            'scheme': (lambda s, k: k['work'].update(scheme='task'), "scheme must be 'backlog'"),
            'no form for a typed kind': (lambda s, k: k['work'].update(canonical_form=None),
                                         'a typed reference exists, so canonical_form is required'),
            'no form for a known kind': (lambda s, k: k['release'].update(status='authority-unavailable',
                                                                          supplied_by=['R-05.4.2']),
                                         'only an unknown kind may lack a canonical form'),
            'form for an untyped kind': (lambda s, k: k['release'].update(canonical_form='release:<x>',
                                                                          examples=['backlog:TASK-1']),
                                         'no typed reference implements it'),
            'no examples': (lambda s, k: k['work'].update(examples=[]), 'examples are required'),
            'example of another kind': (lambda s, k: k['work']['examples'].append('git:r@' + C40), 'parses as commit'),
            'malformed example': (lambda s, k: k['work']['examples'].append('backlog:task-2'), 'does not parse'),
            'kind without entry': (lambda s, k: s['kinds'].remove(k['ci']), "typed reference 'ci' has no schema entry"),
        }
        for name, (mutate, expected) in mutations.items():
            with self.subTest(defect=name):
                problems = broken(mutate)
                self.assertTrue(any(expected in p for p in problems), f'{name}: {problems}')


class SpanAnchor(unittest.TestCase):
    """The D2 case: a U+00A0 in the durable source that a model channel turned into U+0020."""
    DURABLE = 'Please keep it fast: under 200 ms. Thanks…'.encode('utf-8')
    MODEL = DURABLE.replace(' '.encode('utf-8'), b' ')

    def test_span_resolves_and_re_extracts_byte_exactly(self):
        start = self.DURABLE.index(b'under')
        length = len('under 200 ms'.encode('utf-8'))
        ref = L.span_reference('qual-08', 'message-1', self.DURABLE, start, length)
        parsed = L.parse(ref.text)
        self.assertEqual(parsed, ref)
        result = L.check_message_content(parsed, self.DURABLE)
        self.assertEqual(result.outcome, L.RESOLVED)
        self.assertEqual(result.observed_digest, hashlib.sha256('under 200 ms'.encode('utf-8')).hexdigest())
        self.assertEqual(L.span_bytes(parsed, self.DURABLE), 'under 200 ms'.encode('utf-8'))

    def test_a_normalised_source_is_a_digest_mismatch(self):
        start = self.DURABLE.index(b'under')
        ref = L.span_reference('qual-08', 'message-1', self.DURABLE, start, len('under 200'.encode('utf-8')))
        result = L.check_message_content(ref, self.MODEL)
        self.assertEqual((result.outcome, result.code), (L.DIGEST_MISMATCH, 'SPAN_DIGEST_MISMATCH'))
        with self.assertRaises(L.MalformedReference):
            L.span_bytes(ref, self.MODEL)

    def test_span_outside_content_or_inside_a_character(self):
        ref = L.span_reference('t', 'm', self.DURABLE, 0, len(self.DURABLE))
        self.assertEqual(L.check_message_content(ref, self.DURABLE[:-1]).code, 'SPAN_OUT_OF_RANGE')
        nbsp = self.DURABLE.index(' '.encode('utf-8'))
        inside = L.MessageRef('t', 'm', hashlib.sha256(self.DURABLE[nbsp + 1:nbsp + 3]).hexdigest(), nbsp + 1, 2)
        self.assertEqual(L.check_message_content(inside, self.DURABLE).code, 'SPAN_NOT_ON_CHARACTER_BOUNDARY')
        with self.assertRaises(L.MalformedReference):
            L.span_reference('t', 'm', self.DURABLE, nbsp + 1, 2)
        with self.assertRaises(L.MalformedReference):
            L.span_reference('t', 'm', self.DURABLE, 0, len(self.DURABLE) + 1)

    def test_whole_message_digest(self):
        ref = L.message_reference('t', 'm', self.DURABLE)
        self.assertEqual(L.check_message_content(ref, self.DURABLE).outcome, L.RESOLVED)
        mismatch = L.check_message_content(ref, self.MODEL)
        self.assertEqual((mismatch.outcome, mismatch.code), (L.DIGEST_MISMATCH, 'MESSAGE_DIGEST_MISMATCH'))
        unpinned = L.check_message_content(L.MessageRef('t', 'm'), self.MODEL)
        self.assertEqual(unpinned.outcome, L.RESOLVED)
        self.assertEqual(unpinned.observed_digest, hashlib.sha256(self.MODEL).hexdigest())
        with self.assertRaises(L.MalformedReference):
            L.span_bytes(ref, self.DURABLE)  # no span: there is no quote to extract


class ResolutionContract(unittest.TestCase):
    def test_no_truth_value(self):
        result = L.Resolution('backlog:TASK-1', 'work', L.RESOLVED, 'Backlog.md')
        with self.assertRaises(TypeError):
            bool(result)
        with self.assertRaises(TypeError):
            if result:  # noqa: SIM102 - the point is that this raises
                pass
        self.assertTrue(result.resolved)

    def test_code_iff_not_resolved(self):
        with self.assertRaises(ValueError):
            L.Resolution('r', 'work', L.RESOLVED, 'a', 'CODE')
        with self.assertRaises(ValueError):
            L.Resolution('r', 'work', L.MISSING, 'a')
        for code in ('', 5):
            with self.subTest(code=code), self.assertRaises(ValueError):
                L.Resolution('r', 'work', L.MISSING, 'a', code)
        with self.assertRaises(ValueError):
            L.Resolution('r', 'work', 'done', 'a', 'CODE')
        with self.assertRaises(ValueError):
            L.Resolution('r', 'work', L.MISSING, 'a', 'CODE', query='latest')
        with self.assertRaises(ValueError):
            L.Resolution('r', 'work', L.MISSING, 'a', 'CODE', supplied_by=['U-02.1'])
        for facts in ([1], 'x'):
            with self.subTest(facts=facts), self.assertRaises(ValueError):
                L.Resolution('r', 'objective', L.RESOLVED, 'a', facts=facts)
        self.assertEqual(L.Resolution('r', 'objective', L.RESOLVED, 'a', facts={'item': 'O1'}).to_json()['facts'],
                         {'item': 'O1'})
        result = L.Resolution('r', 'work', L.MISSING, 'a', 'CODE', supplied_by=('U-02.1',))
        self.assertEqual(json.loads(json.dumps(result.to_json()))['supplied_by'], ['U-02.1'])


class _Stub:
    def __init__(self, kind, authority, outcomes, answer_with):
        self.kind, self.authority, self.outcomes, self._answer = kind, authority, frozenset(outcomes), answer_with

    def resolve(self, reference):
        return self._answer(reference, 'reference')

    def current(self, reference):
        return self._answer(reference, 'current')


class RegistryContract(unittest.TestCase):
    def test_declared_but_unavailable_kinds_name_their_leaves(self):
        registry = L.Registry()
        for text, leaves in (('conversation:thread-42', ('U-02.1', 'U-02.2')),
                             ('conversation:thread-42/message-8', ('U-02.1', 'U-02.2')),
                             ('openhands:conversation/' + UUID, ('E-01.3.1', 'E-01.4.1')),
                             (f'gitea:o/r/pulls/7/reviews/31@{C40}', ('E-03.3.1', 'E-03.3.2', 'D-01.1')),
                             (f'gitea:o/r/actions/runs/9@{C40}', ('Q-03.1', 'Q-03.2')),
                             (f'gitea:o/r/branches/main@{C40}#sha256:{D}', ('G-03.1', 'G-04.3.1'))):
            for method in (registry.resolve, registry.current):
                with self.subTest(text=text, method=method.__name__):
                    result = method(text)
                    self.assertEqual(result.outcome, L.AUTHORITY_UNAVAILABLE)
                    self.assertEqual(result.code, 'AUTHORITY_NOT_YET_AVAILABLE')
                    self.assertEqual(result.supplied_by, leaves)
                    self.assertIn(L.NOT_YET_VERIFIED, result.detail)

    def test_unsettled_and_unknown_kinds_are_unsupported(self):
        schema = L.load_schema()
        objective = L.schema_kinds(schema)['objective']  # as it stood before decision 0008
        objective.update(status='unknown', resolver=None, verified=L.NOT_YET_VERIFIED,
                         open=['the outcomeId is not settled'])
        objective['identity']['settled'] = False
        result = L.Registry(schema=schema).resolve(f'outcome:{OUTCOME}')
        self.assertEqual((result.outcome, result.code), (L.UNSUPPORTED_KIND, 'KIND_NOT_SETTLED'))
        self.assertIn('the outcomeId is not settled', result.detail)
        registry = L.Registry()
        with self.assertRaises(L.MalformedReference):
            registry.resolve('outcome:O-101')  # the illustrative notation no longer parses (decision 0008)
        result = registry.resolve('catalog:engineer@x')
        self.assertEqual((result.outcome, result.code, result.kind),
                         (L.UNSUPPORTED_KIND, 'REFERENCE_UNSUPPORTED_SCHEME', 'unknown'))
        with self.assertRaises(L.MalformedReference):
            registry.resolve('backlog:task-2')
        for value in (5, None, L.Reference()):
            with self.subTest(value=value), self.assertRaises(L.MalformedReference):
                registry.resolve(value)

    def test_a_kind_the_schema_does_not_declare(self):
        schema = L.load_schema()
        schema['kinds'] = [e for e in schema['kinds'] if e['kind'] != 'ci']
        result = L.Registry(schema=schema).resolve(f'gitea:o/r/actions/runs/9@{C40}')
        self.assertEqual((result.outcome, result.code, result.authority),
                         (L.UNSUPPORTED_KIND, 'KIND_NOT_DECLARED', 'none'))

    def test_implemented_kinds_without_configuration(self):
        registry = L.Registry()
        for text in ('backlog:TASK-1', f'git:r@{C40}', 'effect:' + KEY, f'outcome:{OUTCOME}',
                     f'openspec:changes/x/design.md@{C40}#sha256={D}'):
            with self.subTest(text=text):
                result = registry.resolve(text)
                self.assertEqual((result.outcome, result.code), (L.AUTHORITY_UNAVAILABLE, 'RESOLVER_NOT_CONFIGURED'))

    def test_registry_holds_resolvers_to_the_schema(self):
        good = lambda ref, query: L.answer(ref, L.RESOLVED, 'Git', query=query)  # noqa: E731
        outcomes = L.schema_kinds(L.load_schema())['commit']['outcomes']
        registry = L.Registry([_Stub('commit', 'Git', outcomes, good)])
        self.assertEqual(registry.resolve(f'git:r@{C40}').outcome, L.RESOLVED)
        self.assertEqual(registry.current(f'git:r@{C40}').query, 'current')
        with self.assertRaises(ValueError):
            L.Registry([_Stub('attempt', 'OpenHands Agent Server', outcomes, good)])  # not implemented
        with self.assertRaises(ValueError):
            L.Registry([_Stub('commit', 'Git', {'resolved'}, good)])            # outcomes differ
        with self.assertRaises(ValueError):
            L.Registry([_Stub('commit', 'GitHub', outcomes, good)])             # authority differs
        with self.assertRaises(ValueError):
            L.Registry([_Stub('commit', 'Git', outcomes, good)] * 2)
        bad_answers = {
            'other kind': lambda ref, q: L.Resolution(ref.text, 'design', L.RESOLVED, 'Git', query=q),
            'other reference': lambda ref, q: L.Resolution('git:x@' + C40, 'commit', L.RESOLVED, 'Git', query=q),
            'undeclared outcome': lambda ref, q: L.answer(ref, L.AMBIGUOUS, 'Git', 'X', query=q),
            'wrong query': lambda ref, q: L.answer(ref, L.RESOLVED, 'Git', query='reference'),
            'other authority': lambda ref, q: L.answer(ref, L.RESOLVED, 'Gitea', query=q),
            'not a resolution': lambda ref, q: True,
        }
        for name, answer_with in bad_answers.items():
            with self.subTest(answer=name), self.assertRaises(RuntimeError):
                L.Registry([_Stub('commit', 'Git', outcomes, answer_with)]).current(f'git:r@{C40}')


if __name__ == '__main__':
    unittest.main()
