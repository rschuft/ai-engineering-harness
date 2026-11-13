"""The dispatch-input decision records (plan leaf P-04.3), in the test process only.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

Pure tests of the two new ``owner-decision/v1`` kinds (``accept-design``, ``promote-manifest``), the
sibling format ``delegated-decision/v1`` and its delegation table, the status parser of a delegating
record, and the dispatch-input commands' codes and constants: an Owner record of either new kind with an
agent-attributed statement is refused, a delegated record is never an Owner record, the engineering manager
is never a delegated decider of either kind, a later leaf adds a delegated kind with no change to the
record's fields, and the grammars and the admitted channel list repeated from other modules are equal to
theirs. Every statement and basis here is synthetic.
"""
import copy
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import input_fixture as fi  # noqa: E402

IR, I, G, D, DI = fi.IR, fi.I, fi.G, fi.D, fi.DI
DECISION_ID = '1f0e2d3c-4b5a-4968-8776-0123456789ab'
OTHER_ID = '2a1b0c9d-8e7f-4a6b-9c5d-4e3f2a1b0c9d'
COMMIT = 'a' * 40
SHOWN = {'summary': 'shown', 'nonce': 'ab' * 16, 'expiresAt': '2026-11-13T12:30:00Z'}


def design_subject(**changes):
    return {'repository': fi.REPOSITORY, 'change': fi.CHANGE, 'commit': COMMIT, 'content': 'sha256:' + 'c' * 64,
            'supersedes': None, **changes}


def promotion_subject(**changes):
    return {'schema': DI.MANIFEST_SCHEMA, 'version': 2, 'digest': 'sha256:' + 'd' * 64,
            'previous': {'version': 1, 'digest': 'sha256:' + 'e' * 64},
            'designs': [{'repository': fi.REPOSITORY, 'change': fi.CHANGE, 'commit': COMMIT,
                         'acceptance': DECISION_ID, 'sequence': 1}], **changes}


SUBJECTS = {'accept-design': design_subject, 'promote-manifest': promotion_subject}
BASES = {'accept-design': fi.commitment, 'promote-manifest': fi.envelope}


def owner_record(kind, **changes):
    record = {'format': D.FORMAT, 'decisionId': DECISION_ID, 'kind': kind, 'subject': SUBJECTS[kind](),
              'shown': dict(SHOWN), 'statement': fi.statement(fi.CHANGE), 'recordedBy': fi.RECORDED_BY,
              'recordedAt': '2026-11-13T12:05:00Z'}
    record.update(changes)
    return record


def authority(kind):
    return G.Authority(G.DELEGATIONS[kind], 'b' * 40, 'sha256:' + 'f' * 64, BASES[kind]())


def delegated_record(kind, **changes):
    record = G.decide(authority(kind), SUBJECTS[kind](), recorded_at='2026-11-13T12:05:00Z', decision_id=DECISION_ID)
    record.update(changes)
    return record


class OwnerKinds(unittest.TestCase):
    """owner-decision/v1 gains accept-design and promote-manifest; nothing else of it changes."""

    def test_the_shape_is_unchanged_but_for_the_two_kinds(self):
        self.assertEqual(D.FORMAT, 'owner-decision/v1')
        self.assertEqual(D.FIELDS, ('format', 'decisionId', 'kind', 'subject', 'shown', 'statement', 'recordedBy',
                                    'recordedAt'))
        self.assertEqual(D.SHOWN_FIELDS, ('summary', 'nonce', 'expiresAt'))
        self.assertEqual(D.STATEMENT_FIELDS, ('text', 'attributedTo', 'channel', 'reference'))
        self.assertEqual(D.KINDS, ('accept-objective', 'authorize-operation', 'accept-design', 'promote-manifest'))
        self.assertEqual(D.SUBJECT_FIELDS['accept-objective'], ('change', 'item', 'outcome', 'revision', 'proposal'))
        self.assertEqual(D.SUBJECT_FIELDS['authorize-operation'],
                         ('repository', 'pull', 'base', 'head', 'manifest', 'digest', 'operation', 'operationKind',
                          'target', 'expiresAt'))
        self.assertEqual(D.SUBJECT_FIELDS['accept-design'], ('repository', 'change', 'commit', 'content', 'supersedes'))
        self.assertEqual(D.SUBJECT_FIELDS['promote-manifest'], ('schema', 'version', 'digest', 'previous', 'designs'))

    def test_an_owner_record_of_each_new_kind_has_the_shared_shape(self):
        for kind in SUBJECTS:
            with self.subTest(kind=kind):
                self.assertEqual(D.check_record(owner_record(kind)), [])
        first = owner_record('promote-manifest', subject=promotion_subject(version=1, previous=None))
        self.assertEqual(D.check_record(first), [])
        self.assertEqual(D.check_record(owner_record('accept-design', subject=design_subject(
            commit='a' * 64, supersedes=OTHER_ID))), [])

    def test_an_agent_attributed_statement_is_never_an_owner_decision(self):
        """decision 0018 point 3.2 and the P-04 gate: neither new kind is recorded as an Owner decision on a
        statement a model wrote."""
        for kind in SUBJECTS:
            for said in (fi.statement(fi.CHANGE, attributedTo=fi.PM), fi.statement(fi.CHANGE, attributedTo=fi.EM),
                         fi.statement(fi.CHANGE, reference='openhands:conversation/0123')):
                with self.subTest(kind=kind, said=said):
                    problems = D.check_record(owner_record(kind, statement=said))
                    self.assertTrue(any(p.startswith('statement: ') and 'model' in p for p in problems), problems)
                    self.assertEqual(D.statement_verdict(said)[0], D.MODEL)

    def test_each_subject_value_is_checked(self):
        cases = {
            'accept-design': [dict(repository='Fixture'), dict(repository='a' * 65), dict(change='Bad_Change'),
                              dict(change='a' * 129), dict(commit='a' * 39), dict(commit='A' * 40),
                              dict(content='c' * 64), dict(supersedes='not-a-uuid'), dict(supersedes=1)],
            'promote-manifest': [dict(schema='other/v1'), dict(version=0), dict(version=True), dict(digest='d' * 64),
                                 dict(previous={'version': 2, 'digest': 'sha256:' + 'e' * 64}),
                                 dict(previous={'digest': 'sha256:' + 'e' * 64, 'version': 1}),
                                 dict(previous=[]), dict(designs={}),
                                 dict(designs=[{'repository': fi.REPOSITORY}]),
                                 dict(designs=[{**promotion_subject()['designs'][0], 'acceptance': 'x'}]),
                                 dict(designs=[{**promotion_subject()['designs'][0], 'sequence': 0}]),
                                 dict(designs=promotion_subject()['designs'] * 2)],
        }
        for kind, changes in cases.items():
            for change in changes:
                with self.subTest(kind=kind, change=change):
                    self.assertNotEqual(D.subject_problems(kind, SUBJECTS[kind](**change)), [])
        self.assertNotEqual(D.subject_problems('accept-design', {'repository': fi.REPOSITORY}), [])
        self.assertNotEqual(D.subject_problems('no-such-kind', design_subject()), [])

    def test_the_repeated_grammars_equal_their_sources(self):
        planning = DI.planning
        self.assertEqual(D.MANIFEST_SCHEMA, DI.MANIFEST_SCHEMA)
        self.assertEqual(D.MANIFEST_ID.pattern, f'^{DI.ID_RE.pattern}$')
        self.assertEqual(D.MANIFEST_ID_MAX, DI.MAX_ID)
        self.assertEqual(D.DESIGN_CHANGE.pattern, f'^{planning.CHANGE_ID}$')
        self.assertEqual(D.DESIGN_CHANGE_MAX, DI.store.MAX_CHANGE_ID)
        self.assertEqual(D.FULL_COMMIT.pattern, f'^(?:{planning.COMMIT})$')


class Delegated(unittest.TestCase):
    """delegated-decision/v1: a sibling format, never an Owner record."""

    def test_a_delegated_record_has_its_shape_and_names_its_delegation(self):
        for kind, (point, basis) in {'accept-design': ('3.2', 'commitment'),
                                     'promote-manifest': ('3.3', 'envelope')}.items():
            with self.subTest(kind=kind):
                record = delegated_record(kind)
                self.assertEqual(list(record), list(G.FIELDS))
                self.assertEqual(G.check_record(record), [])
                self.assertEqual(record['delegation']['record'], 'decision:0018')
                self.assertEqual((record['delegation']['point'], record['delegation']['basis']['type']), (point, basis))
                self.assertEqual(record['decidedBy'], fi.PM)
                self.assertEqual(record['recordedBy'], fi.PM)

    def test_a_delegated_record_fails_the_owner_check_and_an_owner_record_the_delegated_check(self):
        for kind in SUBJECTS:
            with self.subTest(kind=kind):
                problems = D.check_record(delegated_record(kind))
                self.assertIn('format must be owner-decision/v1', problems)
                self.assertTrue(any(p.startswith('the fields must be exactly') for p in problems), problems)
                self.assertNotEqual(G.check_record(owner_record(kind)), [])
                # the format alone does not make one the other
                self.assertNotEqual(D.check_record({**delegated_record(kind), 'format': D.FORMAT}), [])
                self.assertNotEqual(G.check_record({**owner_record(kind), 'format': G.FORMAT}), [])

    def test_the_engineering_manager_never_decides_either_kind(self):
        """Ruling R6: the delegated decider of both P-04.3 kinds is the product manager only."""
        for kind in SUBJECTS:
            with self.subTest(kind=kind):
                self.assertEqual(G.DELEGATIONS[kind].decider, fi.PM)
                with self.assertRaises(G.DelegationRefused) as caught:
                    G.check_delegation(kind, fi.EM, BASES[kind]())
                self.assertEqual(caught.exception.code, 'DECIDER_NOT_DELEGATED')
                for changes in ({'decidedBy': fi.EM, 'recordedBy': fi.EM}, {'recordedBy': fi.EM}):
                    self.assertNotEqual(G.check_record(delegated_record(kind, **changes)), [])

    def test_each_part_of_a_delegated_record_is_checked(self):
        record = delegated_record('promote-manifest')
        variants = []
        for key, value in (('format', D.FORMAT), ('decisionId', 'x'), ('kind', 'authorize-operation'),
                           ('subject', design_subject()), ('recordedAt', 'today')):
            variants.append({**record, key: value})
        for key, value in (('record', 'decision:0012'), ('point', '3.2'), ('revision', 'b' * 39),
                           ('digest', 'f' * 64), ('basis', fi.commitment()), ('basis', fi.envelope(link='x'))):
            changed = copy.deepcopy(record)
            changed['delegation'][key] = value
            variants.append(changed)
        changed = copy.deepcopy(record)
        changed['delegation'] = {'record': 'decision:0018'}
        variants.append(changed)
        variants.append({k: record[k] for k in reversed(G.FIELDS)})
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertNotEqual(G.check_record(variant), [])
        self.assertEqual(G.check_record('record'), ['the record must be an object'])

    def test_each_basis_shape_is_checked(self):
        for kind, good in BASES.items():
            row = G.DELEGATIONS[kind]
            G.check_delegation(kind, fi.PM, good())
            other = BASES['promote-manifest' if kind == 'accept-design' else 'accept-design']
            for basis in (None, 'quote', {}, good(link='evidence/other.md'), good(quote='too short'),
                          {'type': row.basis_type, 'quote': good()['quote'], 'link': G.LOG}, other()):
                with self.subTest(kind=kind, basis=basis), self.assertRaises(G.DelegationRefused) as caught:
                    G.check_delegation(kind, fi.PM, basis)
                self.assertEqual(caught.exception.code, 'DELEGATION_BASIS_INVALID')
        with self.assertRaises(G.DelegationRefused) as caught:
            G.check_delegation('accept-design', fi.PM, fi.commitment(quote='a quote that names no commitment entry'))
        self.assertIn('Commitment: ', caught.exception.detail)

    def test_a_kind_without_a_row_is_never_delegated(self):
        for kind in ('authorize-operation', 'accept-objective', 'select-model', None):
            with self.subTest(kind=kind), self.assertRaises(G.DelegationRefused) as caught:
                G.check_delegation(kind, fi.PM, fi.envelope())
            self.assertEqual(caught.exception.code, 'DELEGATION_KIND_UNKNOWN')

    def test_a_later_leaf_adds_a_kind_with_a_row_and_no_change_to_the_fields(self):
        """Ruling R5 (S-03.5's model selection, as section 6 of the work design describes it): a row (kind,
        delegating record and point, decider, basis type), a subject check and a basis type of its own; the
        record's fields, check_record and decide are unchanged."""
        fields = G.FIELDS
        receipt = G.BasisType('recorder-receipt',
                              lambda basis: [] if isinstance(basis, dict) and list(basis) == ['type', 'receipt']
                              and basis['type'] == 'recorder-receipt' else ['not a receipt basis'],
                              lambda basis, view: None)
        row = G.Delegation('select-model', 'decision:0018', '3', fi.EM, 'recorder-receipt',
                           lambda subject: [] if isinstance(subject, dict) and list(subject) == ['models']
                           else ['subject must be {models}'])
        basis = {'type': 'recorder-receipt', 'receipt': 'owner-authorization/v1/' + 'ab' * 16}
        with mock.patch.dict(G.DELEGATIONS, {'select-model': row}), \
                mock.patch.dict(G.BASIS_TYPES, {'recorder-receipt': receipt}):
            self.assertIs(G.check_delegation('select-model', fi.EM, basis), row)
            record = G.decide(G.Authority(row, 'b' * 40, 'sha256:' + 'f' * 64, basis), {'models': ['m-1']},
                              recorded_at='2026-11-13T12:05:00Z')
            self.assertEqual(G.check_record(record), [])
            self.assertEqual(record['decidedBy'], fi.EM)
            # the P-04.3 kinds still refuse the engineering manager
            with self.assertRaises(G.DelegationRefused):
                G.check_delegation('promote-manifest', fi.EM, fi.envelope())
        self.assertEqual(G.FIELDS, fields)
        self.assertNotIn('select-model', G.DELEGATIONS)
        self.assertEqual(G.check_record(record)[0], 'kind must be a delegated kind: accept-design, promote-manifest')


class StatusLine(unittest.TestCase):
    """The delegating record's status: its first Status: line begins "Status: Accepted (Owner)"."""

    def test_the_status_parser(self):
        self.assertTrue(G.accepted_by_owner(fi.decision_record(fi.ACCEPTED_STATUS).decode()))
        for text in (fi.decision_record(fi.PROPOSED_STATUS).decode(), '# 0018\n\nno status\n',
                     '# 0018\n\nStatus: Accepted (Overseer) - 2026-11-12\n',
                     '# 0018\n\nStatus: Proposed\n\nStatus: Accepted (Owner)\n',
                     '# 0018\n\n Status: Accepted (Owner)\n'):
            with self.subTest(text=text):
                self.assertFalse(G.accepted_by_owner(text))
        self.assertTrue(G.accepted_by_owner('# 0018\r\n\r\nStatus: Accepted (Owner) - 2026-11-12\r\n'))
        self.assertEqual(G.record_status('x\nStatus: Proposed - 1\n'), 'Status: Proposed - 1')
        self.assertIsNone(G.record_status('x\n'))

    def test_only_the_exact_accepted_form_passes(self):
        """F11 (slice 2b): "Status: Accepted (Owner) -" exactly; a qualified variant is not accepted."""
        for line in ('Status: Accepted (Owner), superseded by decision 0021', 'Status: Accepted (Owner)',
                     'Status: Accepted (Owner) superseded', 'Status: Accepted (Owner)- 2026-11-12',
                     'Status: Accepted (Owner, in part) - 2026-11-12'):
            with self.subTest(line=line):
                self.assertFalse(G.accepted_by_owner(f'# 0018\n\n{line}\n'))
        self.assertTrue(G.accepted_by_owner('# 0018\n\nStatus: Accepted (Owner) - 2026-11-12, revision 4\n'))


class LogEntries(unittest.TestCase):
    """F1 (slice 2b): the anchored Decisions entries of the log, as the basis types read them."""

    LOG = fi.log().decode('utf-8')

    def test_each_anchored_entry_its_title_and_its_block(self):
        entry = G.decisions_entry(self.LOG, fi.ENVELOPE_ANCHOR)
        self.assertEqual(entry.title, 'Owner standing authorization: the fixture-app envelope.')
        self.assertEqual(' '.join(entry.verbatim.split()), fi.ENVELOPE)
        self.assertNotIn(fi.DIRECTION_QUOTE.split()[0] + ' direction', entry.text)  # ends at the next entry
        self.assertTrue(G.decisions_entry(self.LOG, fi.COMMITMENT_ANCHOR).title.startswith('Commitment: '))
        self.assertEqual(G.decisions_entry(self.LOG, fi.COMMITMENT_ANCHOR).verbatim, '')
        self.assertIsNone(G.decisions_entry(self.LOG, 'no-such-anchor'))
        self.assertIsNone(G.decisions_entry(self.LOG.replace('## Decisions', '## Something else'), fi.ENVELOPE_ANCHOR))

    def test_an_anchor_outside_the_decisions_section_is_no_entry(self):
        moved = self.LOG.replace('## Decisions\n', '## Decisions\n\n## Later\n', 1)
        self.assertIsNone(G.decisions_entry(moved, fi.ENVELOPE_ANCHOR))

    def test_a_link_names_an_anchor(self):
        for link in (G.LOG, f'{G.LOG}#', f'{G.LOG}#Upper', f'{G.LOG}#a b', f'other.md#{fi.ENVELOPE_ANCHOR}'):
            with self.subTest(link=link), self.assertRaises(G.DelegationRefused) as caught:
                G.check_delegation('promote-manifest', fi.PM, fi.envelope(link=link))
            self.assertEqual(caught.exception.code, 'DELEGATION_BASIS_INVALID')


class Codes(unittest.TestCase):
    """The commands' codes: every one raised has a remedy, and they are the work design's Q7 recorder table."""

    SOURCE = (fi.OWNER / 'input_recorder.py').read_text(encoding='utf-8')
    DELEGATED = (fi.OWNER / 'delegated_decision.py').read_text(encoding='utf-8')
    # answer.md section Q7: the codes shared with the existing recorders, then the new ones (with the engineering
    # manager's ruling R7 of slice 2: PROMOTION_UNRESOLVED).
    SHARED = {'CHALLENGE_MISSING', 'CHALLENGE_INVALID', 'CHALLENGE_UNKNOWN', 'CHALLENGE_EXPIRED',
              'CHALLENGE_CONSUMED', 'CHALLENGE_STALE', 'STATEMENT_MISSING', 'STATEMENT_MODEL_AUTHORED',
              'STATEMENT_NOT_OWNER', 'STATEMENT_INVALID', 'CHANNEL_NOT_ADMITTED', 'RECORDED_BY_INVALID',
              'PROJECT_UNAVAILABLE', 'GIT_FAILED', 'CHANGE_MISSING', 'OUTCOME_UNKNOWN', 'RECEIPT_MISSING'}
    NEW = {'STATEMENT_SUBJECT_MISSING', 'REVISION_INVALID', 'CANDIDATE_UNREADABLE', 'CANDIDATE_INVALID',
           'CANDIDATE_INSIDE_CHECKOUT', 'MANIFEST_LOCATION_INVALID', 'VERSION_NOT_NEXT', 'DESIGN_ACCEPTANCE_MISSING',
           'DECISION_REPLAYED', 'PROMOTION_FAILED', 'PROMOTION_UNRESOLVED', 'DELEGATION_NOT_ACCEPTED',
           'AUTHORITY_UNAVAILABLE', 'DELEGATION_KIND_UNKNOWN', 'DECIDER_NOT_DELEGATED', 'DELEGATION_BASIS_INVALID',
           'DELEGATION_BASIS_NOT_RECORDED', 'DELEGATION_BASIS_NOT_AUTHORITY', 'OWNER_ACCEPTANCE_HEAD', 'IO_FAILED'}

    def test_the_codes_are_the_recorder_table(self):
        self.assertEqual(set(IR.REMEDIES), self.SHARED | self.NEW)

    def test_every_code_raised_has_a_remedy_and_every_remedy_a_code(self):
        """Every code the commands raise (directly, through a mapping of the statement verdicts or of
        load_manifest's path refusals, from delegated_decision's DelegationRefused or input_decisions'
        DesignAnswer) has a remedy, and every remedy is raised somewhere: the remedy table itself is left
        out of the scan."""
        start = self.SOURCE.index('REMEDIES = {')
        body = self.SOURCE[:start] + self.SOURCE[self.SOURCE.index('\n}\n', start):]
        decisions = (fi.OWNER / 'input_decisions.py').read_text(encoding='utf-8')
        raised = set(re.findall(r"RecorderError\('([A-Z_]+)'", body))
        raised |= {code for code in re.findall(r"'([A-Z_]+)'", body) if code in IR.REMEDIES}
        raised |= {code for code in re.findall(r"'([A-Z_]+)'", self.DELEGATED) if code in IR.REMEDIES}
        raised |= set(re.findall(r"DesignAnswer\('([A-Z_]+)'", decisions)) - {'DECISION_RECORD_INVALID'}
        self.assertEqual(raised - set(IR.REMEDIES), set())
        self.assertEqual(set(IR.REMEDIES) - raised, set())

    def test_the_shared_codes_mean_what_they_mean_in_the_authorization_recorder(self):
        AR = fi._load('authorization_recorder', fi.OWNER / 'authorization_recorder.py')
        self.assertLessEqual(self.SHARED - {'PROJECT_UNAVAILABLE', 'GIT_FAILED', 'CHANGE_MISSING', 'CHALLENGE_STALE'},
                             set(AR.REMEDIES))
        A = fi._load('acceptance_recorder', fi.OWNER / 'acceptance_recorder.py')
        self.assertLessEqual({'PROJECT_UNAVAILABLE', 'GIT_FAILED', 'CHANGE_MISSING', 'CHALLENGE_STALE'},
                             set(A.REMEDIES))

    def test_the_admitted_channels_are_the_authorization_recorders(self):
        """The list is repeated (input_recorder imports no Gitea module, so not the authorization recorder);
        the two are equal."""
        AR = fi._load('authorization_recorder', fi.OWNER / 'authorization_recorder.py')
        self.assertEqual(IR.ADMITTED_CHANNELS, AR.ADMITTED_CHANNELS)

    def test_the_verifier_codes_are_load_manifests_and_the_receipts_are_their_own(self):
        self.assertEqual(list(I.REFUSALS), ['MANIFEST_NOT_PROMOTED', 'DECISION_RECORD_INVALID',
                                            'MANIFEST_PROMOTION_UNCONFIRMED', 'MANIFEST_DIGEST_MISMATCH',
                                            'DECISION_REPLAYED', 'DESIGN_ACCEPTANCE_MISSING'])
        AR = fi._load('authorization_recorder', fi.OWNER / 'authorization_recorder.py')
        self.assertFalse(I.KEY_PREFIX.startswith(AR.RECEIPT_PREFIX) or AR.RECEIPT_PREFIX.startswith(I.KEY_PREFIX))
        self.assertEqual(I.promotion_key(3), 'dispatch-inputs/v1/promotion/3')
        self.assertEqual(I.design_key('r', 'c', 2), 'dispatch-inputs/v1/design/r/c/2')
        self.assertEqual(IR.OWNER_STATE[0], AR.STATE_COMPONENT)
        self.assertNotEqual(IR.DELEGATED_STATE[0], AR.STATE_COMPONENT)

    def test_the_commands_name_no_gitea_or_credential_module(self):
        for name in ('input_recorder.py', 'input_decisions.py', 'delegated_decision.py'):
            source = (fi.OWNER / name).read_text(encoding='utf-8')
            with self.subTest(name=name):
                self.assertNotIn("'gitea'", source)
                self.assertNotIn("'credentials'", source)
                self.assertNotIn('gitea_host', source)
                self.assertNotIn('authorization_recorder.py', source)


if __name__ == '__main__':
    unittest.main()
