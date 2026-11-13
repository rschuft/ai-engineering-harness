"""The dispatch-input commands (plan leaf P-04.3, slice 1), on throwaway repositories and a throwaway
integration store.

Run from the repository root, under the tools interpreter (Dulwich is required: without it these tests fail,
never skip):

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

Design acceptances and manifest promotions are recorded under both authorities, the Owner's (a challenge,
then a statement) and the delegated one (decision 0018 points 3.2 and 3.3, on fixture harness repositories
that hold a decision 0018 and a log), and the verifier answers for the manifest that results. Every code of
the recorder table is shown with what it leaves behind: a refusal reserves nothing and leaves the live
manifest and the decision copies as they were; PROMOTION_FAILED and OUTCOME_UNKNOWN leave a failed or an
unknown receipt that ``manifest resolve`` settles by reading. A context built for a test never reaches the
managed data root or its store, and importing the commands loads no Gitea and no credential module. One test
reads the real decision 0018, read-only, at this checkout's HEAD. Every statement, basis and quote is
synthetic.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import input_fixture as fi  # noqa: E402

IR, I, G, D, DI, IS, fx = fi.IR, fi.I, fi.G, fi.D, fi.DI, fi.IS, fi.fx
REPOSITORY, CHANGE, PM, EM = fi.REPOSITORY, fi.CHANGE, fi.PM, fi.EM
ra = IR.ra


def setUpModule():
    fi.start()


def tearDownModule():
    fi.stop()


class Base(fi.Fixture):
    def assertUnchanged(self, code, call, *args, **kw):
        """CALL is refused with CODE and leaves the receipts, the live manifest and the decision copies as they
        were."""
        before = self.snapshot()
        refused = self.assertRefused(code, call, *args, **kw)
        self.assertEqual(self.snapshot(), before)
        return refused

    def design_challenge(self, commit=None, change=CHANGE):
        return IR.design_prepare(self.ctx, self.repos.project, REPOSITORY, change, commit or self.repos.first)


# ---------------------------------------------------------------------------- the outcome under both authorities


class OwnerAuthority(Base):
    """An Owner acceptance and an Owner promotion: prepare shows, record decides, the verifier answers."""

    def test_an_owner_acceptance_and_promotion_load_with_their_records(self):
        challenge = self.design_challenge()
        nonce = challenge['shown']['nonce']
        self.assertEqual(challenge['subject']['commit'], self.repos.first)
        self.assertEqual(challenge['position'], 1)
        self.assertIsNone(challenge['subject']['supersedes'])
        self.assertIn(f'naming the change {CHANGE}', challenge['shown']['summary'])
        self.assertTrue((self.dir / 'state' / 'owner-authorization' / 'dispatch-inputs' / 'challenges'
                         / f'{nonce}.json').is_file())
        self.now = fi.LATER
        accepted = IR.design_record(self.ctx, nonce, fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        decision = accepted['decision']
        self.assertEqual(D.check_record(decision), [])
        self.assertEqual((decision['format'], decision['kind']), (D.FORMAT, 'accept-design'))
        self.assertEqual(accepted['receipt']['state'], 'confirmed')
        self.assertEqual(accepted['receipt']['events'], ['reserved', 'dispatched', 'confirmed'])
        self.assertTrue((self.dir / 'state' / 'owner-authorization' / 'dispatch-inputs' / 'decisions'
                         / f'{decision["decisionId"]}.json').is_file())
        self.assertIsNone(self.live_bytes())  # an acceptance writes no manifest

        path = self.candidate()
        promotion = IR.manifest_prepare(self.ctx, path)
        self.assertEqual(promotion['subject']['designs'], [
            {'repository': REPOSITORY, 'change': CHANGE, 'commit': self.repos.first,
             'acceptance': decision['decisionId'], 'sequence': 1}])
        self.assertIsNone(promotion['subject']['previous'])
        self.assertEqual(promotion['candidate'], path.read_text(encoding='utf-8'))
        self.assertIn('naming approved-inputs-v1', promotion['shown']['summary'])
        result = IR.manifest_record(self.ctx, promotion['shown']['nonce'], fi.statement('approved-inputs-v1'),
                                    recorded_by=fi.RECORDED_BY)
        self.assertEqual(self.live_bytes(), path.read_bytes())
        self.assertEqual(result['receipt']['state'], 'confirmed')
        self.assertEqual(result['authority']['authority'], 'owner')
        verdict = self.verify()
        self.assertIsNone(verdict.code, verdict.detail)
        approval = verdict.approval
        self.assertEqual(approval['format'], I.APPROVAL_FORMAT)
        self.assertEqual((approval['version'], approval['digest']), (1, result['manifest']['digest']))
        self.assertEqual(approval['promotion']['decisionId'], result['decision']['decisionId'])
        self.assertEqual(approval['promotion']['receipt'], 'dispatch-inputs/v1/promotion/1')
        self.assertEqual(approval['promotion']['authority']['authority'], 'owner')
        self.assertEqual([(d['decisionId'], d['receipt'], d['authority']['authority']) for d in approval['designs']],
                         [(decision['decisionId'], f'dispatch-inputs/v1/design/{REPOSITORY}/{CHANGE}/1', 'owner')])

    def test_a_second_acceptance_supersedes_and_a_second_promotion_names_the_first(self):
        first = self.accept()['decision']
        second_challenge = self.design_challenge(self.repos.second)
        self.assertEqual((second_challenge['position'], second_challenge['subject']['supersedes']),
                         (2, first['decisionId']))
        self.assertIn(first['decisionId'], second_challenge['shown']['summary'])
        self.assertNotEqual(second_challenge['subject']['content'], self.design_challenge()['subject']['content'])
        one = self.promote(self.candidate())
        second = IR.design_record(self.ctx, second_challenge['shown']['nonce'], fi.statement(CHANGE),
                                  recorded_by=fi.RECORDED_BY)['decision']
        path = self.candidate(name='v2.json', version=2, designs=((REPOSITORY, CHANGE, self.repos.second),))
        challenge = IR.manifest_prepare(self.ctx, path)
        self.assertEqual(challenge['subject']['previous'], {'version': 1, 'digest': one['manifest']['digest']})
        self.assertIn(f'- designs: {{"change":"{CHANGE}","commit":"{self.repos.first}"', challenge['shown']['summary'])
        self.assertIn(f'+ designs: {{"change":"{CHANGE}","commit":"{self.repos.second}"', challenge['shown']['summary'])
        IR.manifest_record(self.ctx, challenge['shown']['nonce'], fi.statement('approved-inputs-v2'),
                           recorded_by=fi.RECORDED_BY)
        verdict = self.verify()
        self.assertIsNone(verdict.code, verdict.detail)
        self.assertEqual(verdict.approval['designs'][0]['decisionId'], second['decisionId'])
        self.assertEqual(verdict.approval['designs'][0]['sequence'], 2)

    def test_the_content_digest_covers_the_change_folder_in_path_order(self):
        import hashlib
        content, files = IR.read_design(self.repos.project, REPOSITORY, CHANGE, self.repos.first)
        self.assertEqual([path for path, _ in files], ['design.md', 'proposal.md', 'specs/fixture/spec.md'])
        self.assertEqual(files[0][1], hashlib.sha256(b'# Design (SYNTHETIC FIXTURE), first revision\n').hexdigest())
        lines = ''.join(f'{digest}  {path}\n' for path, digest in files).encode('utf-8')
        self.assertEqual(content, 'sha256:' + hashlib.sha256(lines).hexdigest())


class DelegatedAuthority(Base):
    """Decisions delegated by decision 0018 on the fixture harness repository: never Owner records."""

    def test_a_delegated_acceptance_and_promotion_load_naming_the_delegation(self):
        accepted = self.delegate_design()
        decision = accepted['decision']
        self.assertEqual(G.check_record(decision), [])
        self.assertNotEqual(D.check_record(decision), [])
        harness_head = fx.head(self.repos.harness['accepted'])
        self.assertEqual(decision['delegation']['revision'], harness_head)
        self.assertEqual((decision['delegation']['point'], decision['delegation']['basis']), ('3.2', fi.commitment()))
        delegated = self.dir / 'state' / 'delegated-decisions' / 'dispatch-inputs'
        self.assertTrue((delegated / f'{decision["decisionId"]}.json').is_file())
        self.assertFalse((self.dir / 'state' / 'owner-authorization').exists())
        result = self.delegate_promotion(self.candidate())
        self.assertEqual(result['decision']['delegation']['point'], '3.3')
        self.assertEqual(result['decision']['subject']['designs'][0]['acceptance'], decision['decisionId'])
        self.assertFalse((self.dir / 'state' / 'owner-authorization').exists())
        verdict = self.verify()
        self.assertIsNone(verdict.code, verdict.detail)
        promotion = verdict.approval['promotion']
        self.assertEqual(promotion['format'], G.FORMAT)
        self.assertEqual(promotion['authority'], {'authority': 'delegated', 'record': 'decision:0018', 'point': '3.3',
                                                  'revision': harness_head, 'decidedBy': PM, 'basis': fi.envelope()})
        self.assertEqual(verdict.approval['designs'][0]['authority']['point'], '3.2')

    def test_the_record_digest_is_the_committed_blob(self):
        import hashlib
        decision = self.delegate_design()['decision']
        blob = fi.decision_record(fi.ACCEPTED_STATUS)
        self.assertEqual(decision['delegation']['digest'], 'sha256:' + hashlib.sha256(blob).hexdigest())

    def test_an_owner_promotion_may_rest_on_a_delegated_acceptance(self):
        self.delegate_design()
        self.promote(self.candidate())
        verdict = self.verify()
        self.assertEqual((verdict.approval['promotion']['authority']['authority'],
                          verdict.approval['designs'][0]['authority']['authority']), ('owner', 'delegated'))

    def test_the_real_decision_0018_is_accepted_at_head(self):
        """Read-only, through the repository-access module, the committed blob at this checkout's HEAD."""
        with ra.open_repository(fi.REPO, config='repository', ceilings=[str(fi.REPO.parent)]) as repo:
            commit = repo.head().commit
            found = [p for p in repo.files(commit, 'decisions') if p.startswith('decisions/0018-')]
            self.assertEqual(len(found), 1, found)
            text = repo.blob(commit, found[0]).decode('utf-8')
        self.assertTrue(G.accepted_by_owner(text), G.record_status(text))


# ---------------------------------------------------------------------------- every code and what it leaves


class ChallengeCodes(Base):
    def test_challenge_missing(self):
        for nonce in (None, ''):
            self.assertUnchanged('CHALLENGE_MISSING', IR.design_record, self.ctx, nonce, fi.statement(CHANGE),
                                 recorded_by=fi.RECORDED_BY)
            self.assertUnchanged('CHALLENGE_MISSING', IR.manifest_record, self.ctx, nonce,
                                 fi.statement('approved-inputs-v1'), recorded_by=fi.RECORDED_BY)

    def test_challenge_invalid(self):
        self.assertUnchanged('CHALLENGE_INVALID', IR.design_record, self.ctx, 'not-a-nonce', fi.statement(CHANGE),
                             recorded_by=fi.RECORDED_BY)
        design = self.design_challenge()
        # a design challenge given to the manifest command
        self.assertUnchanged('CHALLENGE_INVALID', IR.manifest_record, self.ctx, design['shown']['nonce'],
                             fi.statement('approved-inputs-v1'), recorded_by=fi.RECORDED_BY)
        # a challenge altered in the recorder's state
        path = self.dir / 'state' / 'owner-authorization' / 'dispatch-inputs' / 'challenges' / \
            f'{design["shown"]["nonce"]}.json'
        altered = json.loads(path.read_text(encoding='utf-8'))
        altered['subject']['commit'] = 'z' * 40
        path.write_text(json.dumps(altered), encoding='utf-8')
        self.assertUnchanged('CHALLENGE_INVALID', IR.design_record, self.ctx, design['shown']['nonce'],
                             fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        self.accept()
        manifest = IR.manifest_prepare(self.ctx, self.candidate())
        path = path.parent / f'{manifest["shown"]["nonce"]}.json'
        altered = json.loads(path.read_text(encoding='utf-8'))
        altered['candidate'] = altered['candidate'].replace('"version": 1', '"version": 1 ')
        path.write_text(json.dumps(altered), encoding='utf-8')
        self.assertUnchanged('CHALLENGE_INVALID', IR.manifest_record, self.ctx, manifest['shown']['nonce'],
                             fi.statement('approved-inputs-v1'), recorded_by=fi.RECORDED_BY)

    def test_challenge_unknown(self):
        self.assertUnchanged('CHALLENGE_UNKNOWN', IR.manifest_record, self.ctx, 'ab' * 16,
                             fi.statement('approved-inputs-v1'), recorded_by=fi.RECORDED_BY)

    def test_challenge_expired(self):
        challenge = IR.design_prepare(self.ctx, self.repos.project, REPOSITORY, CHANGE, self.repos.first,
                                      expires_in_minutes=1)
        self.now = fi.NOW + fi.datetime.timedelta(minutes=1)
        self.assertUnchanged('CHALLENGE_EXPIRED', IR.design_record, self.ctx, challenge['shown']['nonce'],
                             fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)

    def test_challenge_consumed(self):
        """The proof's replay row at the recorder: record twice on one Owner challenge; one receipt."""
        challenge = self.design_challenge()
        IR.design_record(self.ctx, challenge['shown']['nonce'], fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        self.assertUnchanged('CHALLENGE_CONSUMED', IR.design_record, self.ctx, challenge['shown']['nonce'],
                             fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        promotion = IR.manifest_prepare(self.ctx, self.candidate())
        IR.manifest_record(self.ctx, promotion['shown']['nonce'], fi.statement('approved-inputs-v1'),
                           recorded_by=fi.RECORDED_BY)
        live = self.live_bytes()
        self.assertUnchanged('CHALLENGE_CONSUMED', IR.manifest_record, self.ctx, promotion['shown']['nonce'],
                             fi.statement('approved-inputs-v1'), recorded_by=fi.RECORDED_BY)
        self.assertEqual(self.live_bytes(), live)
        self.assertEqual(sorted(self.receipts()), [f'dispatch-inputs/v1/design/{REPOSITORY}/{CHANGE}/1',
                                                   'dispatch-inputs/v1/promotion/1'])

    def test_challenge_stale(self):
        """Two challenges for one position: the second is stale once the first is recorded; and a delegated
        decision that takes the position makes an Owner challenge stale."""
        one, two = self.design_challenge(), self.design_challenge()
        IR.design_record(self.ctx, one['shown']['nonce'], fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        self.assertUnchanged('CHALLENGE_STALE', IR.design_record, self.ctx, two['shown']['nonce'],
                             fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        owner = IR.manifest_prepare(self.ctx, self.candidate())
        self.delegate_promotion(self.candidate(name='same.json'))
        self.assertUnchanged('CHALLENGE_STALE', IR.manifest_record, self.ctx, owner['shown']['nonce'],
                             fi.statement('approved-inputs-v1'), recorded_by=fi.RECORDED_BY)

    def test_challenge_stale_when_anything_else_holds_the_position(self):
        """A position held by a receipt that is no decision of this challenge (here, not a decision at all)."""
        challenge = self.design_challenge()
        intent = {'format': I.RECEIPT_FORMAT, 'recorder': 'by-hand', 'series': 'design'}
        self.store.reserve(I.design_key(REPOSITORY, CHANGE, 1), intent, actor='test')
        self.assertUnchanged('CHALLENGE_STALE', IR.design_record, self.ctx, challenge['shown']['nonce'],
                             fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)


class StatementCodes(Base):
    def setUp(self):
        super().setUp()
        self.nonce = self.design_challenge()['shown']['nonce']

    def refused(self, code, said, recorded_by=fi.RECORDED_BY):
        return self.assertUnchanged(code, IR.design_record, self.ctx, self.nonce, said, recorded_by=recorded_by)

    def test_statement_missing(self):
        for said in (None, fi.statement(CHANGE, text=' '), fi.statement(CHANGE, reference='missing:owner-reply')):
            with self.subTest(said=said):
                self.refused('STATEMENT_MISSING', said)

    def test_statement_model_authored(self):
        for said in (fi.statement(CHANGE, attributedTo=PM), fi.statement(CHANGE, attributedTo=EM),
                     fi.statement(CHANGE, reference='openhands:conversation/1234')):
            with self.subTest(said=said):
                self.refused('STATEMENT_MODEL_AUTHORED', said)

    def test_statement_not_owner(self):
        self.refused('STATEMENT_NOT_OWNER', fi.statement(CHANGE, attributedTo='person:someone'))

    def test_statement_invalid(self):
        self.refused('STATEMENT_INVALID', fi.statement(CHANGE, channel='Main Session'))
        self.refused('STATEMENT_INVALID', {**fi.statement(CHANGE), 'extra': 1})

    def test_channel_not_admitted(self):
        self.refused('CHANNEL_NOT_ADMITTED', fi.statement(CHANGE, channel='email'))

    def test_statement_subject_missing(self):
        self.refused('STATEMENT_SUBJECT_MISSING', fi.statement('another-change'))
        self.refused('STATEMENT_SUBJECT_MISSING', fi.statement(f'{CHANGE}-two'))
        self.accept(change=fi.OTHER_CHANGE, commit=self.repos.second)
        self.accept()
        nonce = IR.manifest_prepare(self.ctx, self.candidate())['shown']['nonce']
        for token in ('approved-inputs-v12', 'approved-inputs-v2', 'approved inputs v1'):
            with self.subTest(token=token):
                self.assertUnchanged('STATEMENT_SUBJECT_MISSING', IR.manifest_record, self.ctx, nonce,
                                     fi.statement(token), recorded_by=fi.RECORDED_BY)

    def test_recorded_by_invalid(self):
        self.refused('RECORDED_BY_INVALID', fi.statement(CHANGE), recorded_by='the overseer')


class ProjectCodes(Base):
    def test_project_unavailable(self):
        directory = self.dir / 'not-a-repository'
        directory.mkdir()
        self.assertUnchanged('PROJECT_UNAVAILABLE', IR.design_prepare, self.ctx, directory, REPOSITORY, CHANGE,
                             self.repos.first)
        self.assertUnchanged('PROJECT_UNAVAILABLE', IR.design_delegate, self.ctx, directory, REPOSITORY, CHANGE,
                             self.repos.first, decided_by=PM, basis=fi.commitment())

    def test_git_failed(self):
        with mock.patch.object(ra.Repository, 'files', side_effect=ra.RepositoryError('GIT_FAILED', 'unreadable')):
            self.assertUnchanged('GIT_FAILED', IR.design_prepare, self.ctx, self.repos.project, REPOSITORY, CHANGE,
                                 self.repos.first)

    def test_change_missing(self):
        self.assertUnchanged('CHANGE_MISSING', IR.design_prepare, self.ctx, self.repos.project, REPOSITORY, CHANGE,
                             self.repos.empty)
        self.assertUnchanged('CHANGE_MISSING', IR.design_prepare, self.ctx, self.repos.project, REPOSITORY,
                             'no-such-change', self.repos.first)
        self.assertUnchanged('CHANGE_MISSING', IR.design_prepare, self.ctx, self.repos.project, REPOSITORY,
                             '../escape', self.repos.first)

    def test_revision_invalid(self):
        for commit in (self.repos.first[:12], self.repos.first.upper(), 'f' * 40, 'f' * 64, 'HEAD'):
            with self.subTest(commit=commit):
                self.assertUnchanged('REVISION_INVALID', IR.design_prepare, self.ctx, self.repos.project, REPOSITORY,
                                     CHANGE, commit)

    def test_a_repository_id_outside_its_grammar_is_a_usage_error(self):
        with self.assertRaises(ValueError):
            IR.design_prepare(self.ctx, self.repos.project, 'Fixture App', CHANGE, self.repos.first)


class CandidateCodes(Base):
    def test_candidate_unreadable(self):
        self.assertUnchanged('CANDIDATE_UNREADABLE', IR.manifest_prepare, self.ctx, self.dir / 'absent.json')
        self.assertUnchanged('CANDIDATE_UNREADABLE', IR.manifest_prepare, self.ctx, 'relative.json')

    def test_candidate_invalid(self):
        for text in ('{', '{"schema": "x"}', fi.manifest(version=0), '﻿' + fi.manifest(),
                     fi.manifest()[:-2] + ', "extra": 1}\n'):
            with self.subTest(text=text[:20]):
                self.assertUnchanged('CANDIDATE_INVALID', IR.manifest_prepare, self.ctx, self.candidate(text))
        path = self.dir / 'candidates' / 'latin1.json'
        path.write_bytes(fi.manifest().replace('fixture-profile', 'fixture-profile').encode('utf-8') + b'\xff')
        self.assertUnchanged('CANDIDATE_INVALID', IR.manifest_prepare, self.ctx, path)

    def test_candidate_inside_checkout(self):
        """Refused before anything is read: the path need not exist."""
        self.assertUnchanged('CANDIDATE_INSIDE_CHECKOUT', IR.manifest_prepare, self.ctx,
                             fi.REPO / 'p043-candidate-never-written.json')
        self.assertUnchanged('CANDIDATE_INSIDE_CHECKOUT', self.delegate_promotion,
                             fi.REPO / 'p043-candidate-never-written.json')

    def test_manifest_location_invalid(self):
        """Inside the checkout (the real one: refused before anything is read or written), and around a
        checkout (a fixture directory standing for one)."""
        stand_in = self.dir / 'checkout'
        stand_in.mkdir()
        for live, checkout in ((fi.REPO / 'p043-never-written' / 'approved-inputs.json', fi.REPO),
                               (self.dir, stand_in)):
            with self.subTest(live=live):
                self.ctx = self.context(manifest_path=live, checkout=checkout)
                self.assertUnchanged('MANIFEST_LOCATION_INVALID', IR.manifest_prepare, self.ctx, self.candidate())
                self.assertUnchanged('MANIFEST_LOCATION_INVALID', self.delegate_promotion, self.candidate())
        self.assertFalse((fi.REPO / 'p043-never-written').exists())

    def test_version_not_next(self):
        self.accept()
        self.assertUnchanged('VERSION_NOT_NEXT', IR.manifest_prepare, self.ctx, self.candidate(version=2))
        self.delegate_promotion(self.candidate())
        self.assertUnchanged('VERSION_NOT_NEXT', self.delegate_promotion, self.candidate(name='again.json'))

    def test_design_acceptance_missing(self):
        """The proof's design row at the recorder: no receipt, the live manifest unchanged."""
        self.assertUnchanged('DESIGN_ACCEPTANCE_MISSING', IR.manifest_prepare, self.ctx, self.candidate())
        self.assertUnchanged('DESIGN_ACCEPTANCE_MISSING', self.delegate_promotion, self.candidate())
        self.accept()
        # accepted at FIRST; a candidate naming SECOND has no acceptance
        path = self.candidate(designs=((REPOSITORY, CHANGE, self.repos.second),))
        self.assertUnchanged('DESIGN_ACCEPTANCE_MISSING', IR.manifest_prepare, self.ctx, path)
        self.assertUnchanged('DESIGN_ACCEPTANCE_MISSING', IR.manifest_prepare, self.ctx, self.candidate(
            designs=((REPOSITORY, CHANGE, None), (REPOSITORY, fi.OTHER_CHANGE, self.repos.second))))

    def test_decision_replayed(self):
        """The proof's row: a change accepted at one commit, then at another; a candidate naming the first."""
        self.accept()
        self.accept(self.repos.second)
        self.assertUnchanged('DECISION_REPLAYED', IR.manifest_prepare, self.ctx, self.candidate())
        self.assertUnchanged('DECISION_REPLAYED', self.delegate_promotion, self.candidate())

    def test_decision_replayed_after_the_challenge_was_shown(self):
        self.accept()
        challenge = IR.manifest_prepare(self.ctx, self.candidate())
        self.accept(self.repos.second)
        self.assertUnchanged('DECISION_REPLAYED', IR.manifest_record, self.ctx, challenge['shown']['nonce'],
                             fi.statement('approved-inputs-v1'), recorded_by=fi.RECORDED_BY)


class DelegationCodes(Base):
    def test_delegation_not_accepted(self):
        self.ctx = self.context(harness=self.repos.harness['proposed'])
        self.assertUnchanged('DELEGATION_NOT_ACCEPTED', self.delegate_design)
        self.accept()
        self.assertUnchanged('DELEGATION_NOT_ACCEPTED', self.delegate_promotion, self.candidate())

    def test_authority_unavailable(self):
        directory = self.dir / 'no-harness'
        directory.mkdir()
        self.ctx = self.context(harness=directory)
        self.assertUnchanged('AUTHORITY_UNAVAILABLE', self.delegate_design)

    def test_delegation_kind_unknown(self):
        for kind in ('authorize-operation', 'accept-objective'):
            with self.subTest(kind=kind):
                self.assertUnchanged('DELEGATION_KIND_UNKNOWN', IR._authority, self.ctx, kind, PM, fi.envelope())

    def test_decider_not_delegated(self):
        """Ruling R6: the engineering manager never accepts a design or promotes a manifest."""
        self.assertUnchanged('DECIDER_NOT_DELEGATED', self.delegate_design, decided_by=EM)
        self.accept()
        for decider in (EM, 'owner', 'agent:program-manager'):
            with self.subTest(decider=decider):
                self.assertUnchanged('DECIDER_NOT_DELEGATED', self.delegate_promotion, self.candidate(),
                                     decided_by=decider)

    def test_delegation_basis_invalid(self):
        for basis in (fi.envelope(), fi.commitment(link='evidence/other.md'), fi.commitment(quote='short'),
                      fi.commitment(quote='a quote of the log naming no commitment entry'), None, []):
            with self.subTest(basis=basis):
                self.assertUnchanged('DELEGATION_BASIS_INVALID', self.delegate_design, basis=basis)
        self.accept()
        self.assertUnchanged('DELEGATION_BASIS_INVALID', self.delegate_promotion, self.candidate(),
                             basis=fi.commitment())

    def test_delegation_basis_not_recorded(self):
        self.assertUnchanged('DELEGATION_BASIS_NOT_RECORDED', self.delegate_design,
                             basis=fi.commitment(quote='2026-11-12: Commitment: NOT IN THE LOG (SYNTHETIC)'))
        self.accept()
        self.assertUnchanged('DELEGATION_BASIS_NOT_RECORDED', self.delegate_promotion, self.candidate(),
                             basis=fi.envelope(quote=fi.ENVELOPE.upper()))

    def test_a_quote_only_in_the_work_tree_is_not_recorded(self):
        harness = self.repos.harness['worktree']
        self.assertIn(fi.COMMITMENT, (harness / G.LOG).read_text(encoding='utf-8'))
        self.ctx = self.context(harness=harness)
        self.assertUnchanged('DELEGATION_BASIS_NOT_RECORDED', self.delegate_design)
        self.accept()
        self.assertUnchanged('DELEGATION_BASIS_NOT_RECORDED', self.delegate_promotion, self.candidate())


class WriteOutcomes(Base):
    """PROMOTION_FAILED and OUTCOME_UNKNOWN leave a failed or unknown receipt; resolve settles by reading."""

    def setUp(self):
        super().setUp()
        self.accept()
        self.promote(self.candidate())
        self.v1 = self.live_bytes()
        self.v2 = self.candidate(name='v2.json', version=2)

    def test_promotion_failed_when_the_replace_fails(self):
        def refuse(source, target):
            raise PermissionError('the live manifest is held open')
        self.replace = refuse
        refused = self.assertRefused('PROMOTION_FAILED', self.delegate_promotion, self.v2, refusal=False)
        self.assertEqual(refused.details['receipt'], 'dispatch-inputs/v1/promotion/2')
        self.assertEqual(self.receipts()['dispatch-inputs/v1/promotion/2'], ('failed', ['reserved', 'dispatched',
                                                                                         'failed']))
        self.assertEqual(self.live_bytes(), self.v1)
        self.assertEqual([p.name for p in self.live.parent.iterdir()], ['approved-inputs.json'])
        self.assertEqual(IR.manifest_resolve(self.ctx, 2)['changed'], False)
        # the position is spent: the same bytes are refused, version 3 is the next
        self.replace = None
        self.assertRefused('VERSION_NOT_NEXT', self.delegate_promotion, self.v2)
        self.delegate_promotion(self.candidate(name='v3.json', version=3))
        self.assertIsNone(self.verify().code)

    def test_promotion_failed_when_the_write_fails(self):
        self.ctx = self.context(manifest_path=self.dir / 'state' / 'no-such-directory' / 'approved-inputs.json')
        self.assertRefused('PROMOTION_FAILED', self.delegate_promotion, self.v2, refusal=False)
        self.assertEqual(self.receipts()['dispatch-inputs/v1/promotion/2'][0], 'failed')

    def test_outcome_unknown_then_resolved_by_reading(self):
        def misplace(source, target):
            os.replace(source, target)
            Path(target).write_bytes(b'{}')  # something else lands
        self.replace = misplace
        refused = self.assertRefused('OUTCOME_UNKNOWN', self.delegate_promotion, self.v2, refusal=False)
        self.assertEqual(refused.details['receipt'], 'dispatch-inputs/v1/promotion/2')
        self.assertEqual(self.receipts()['dispatch-inputs/v1/promotion/2'][0], 'unknown')
        self.assertEqual(self.verify(self.v2).code, 'MANIFEST_PROMOTION_UNCONFIRMED')
        # resolve reads: the decided bytes are there now
        self.live.write_bytes(self.v2.read_bytes())
        result = IR.manifest_resolve(self.ctx, 2)
        self.assertEqual((result['changed'], result['receipt']['state']), (True, 'confirmed'))
        self.assertEqual(result['receipt']['events'], ['reserved', 'dispatched', 'unknown', 'confirmed'])
        self.assertIsNone(self.verify().code)
        self.assertEqual(self.live_bytes(), self.v2.read_bytes())

    def test_outcome_unknown_resolved_failed(self):
        def misplace(source, target):
            os.replace(source, target)
            Path(target).write_bytes(b'{}')
        self.replace = misplace
        self.assertRefused('OUTCOME_UNKNOWN', self.delegate_promotion, self.v2, refusal=False)
        self.replace = None
        result = IR.manifest_resolve(self.ctx, 2)
        self.assertEqual(result['receipt']['state'], 'failed')
        self.assertEqual(self.live_bytes(), b'{}')  # resolve never writes

    def test_a_replace_that_raised_after_landing_is_unknown(self):
        def land_then_raise(source, target):
            os.replace(source, target)
            raise OSError('the answer was lost')
        self.replace = land_then_raise
        self.assertRefused('OUTCOME_UNKNOWN', self.delegate_promotion, self.v2, refusal=False)
        self.assertEqual(IR.manifest_resolve(self.ctx, 2)['receipt']['state'], 'confirmed')

    def test_resolve_settles_reserved_and_dispatched_receipts(self):
        for version, state in ((2, 'reserved'), (3, 'dispatched')):
            self.hand_promotion(version, fi.manifest(version=version), state=state)
        self.assertEqual(IR.manifest_resolve(self.ctx, 2)['receipt']['events'], ['reserved', 'failed'])
        three = IR.manifest_resolve(self.ctx, 3)['receipt']
        self.assertEqual(three['events'], ['reserved', 'dispatched', 'unknown', 'failed'])

    def test_promotion_unresolved(self):
        """Ruling R7 (slice 2, fix-forward of dca60ac): no promotion is prepared, recorded or delegated while an
        earlier promotion receipt is reserved, dispatched or unknown; resolving it first lets the next one through.
        Otherwise resolving it by reading, after a later promotion replaced the live file, would record a decision
        that landed as failed."""
        def land_then_raise(source, target):
            os.replace(source, target)
            raise OSError('the answer was lost')
        self.replace = land_then_raise
        self.assertRefused('OUTCOME_UNKNOWN', self.delegate_promotion, self.v2, refusal=False)
        self.replace = None
        v3 = self.candidate(name='v3.json', version=3)
        refused = self.assertUnchanged('PROMOTION_UNRESOLVED', self.delegate_promotion, v3)
        self.assertIn('version 2 (unknown)', refused.detail)
        self.assertUnchanged('PROMOTION_UNRESOLVED', IR.manifest_prepare, self.ctx, v3)
        for version, state in ((3, 'reserved'), (4, 'dispatched')):
            self.hand_promotion(version, fi.manifest(version=version), state=state)
        refused = self.assertUnchanged('PROMOTION_UNRESOLVED', self.delegate_promotion,
                                       self.candidate(name='v5.json', version=5))
        self.assertIn('version 3 (reserved), version 4 (dispatched)', refused.detail)
        for version in (2, 3, 4):
            IR.manifest_resolve(self.ctx, version)
        # version 2 landed and the live file still holds it: resolved by reading, confirmed
        self.assertEqual(self.receipts()['dispatch-inputs/v1/promotion/2'][0], 'confirmed')
        self.promote(self.candidate(name='v5.json', version=5))
        self.assertIsNone(self.verify().code)

    def test_receipt_missing(self):
        self.assertUnchanged('RECEIPT_MISSING', IR.manifest_resolve, self.ctx, 7)
        with self.assertRaises(ValueError):
            IR.manifest_resolve(self.ctx, 0)


# ---------------------------------------------------------------------------- the verifier


class Verifier(Base):
    """The verifier reads the store's receipts only: what load_manifest will refuse (slice 2)."""

    def setUp(self):
        super().setUp()
        self.accept()
        self.promoted = self.candidate()
        self.promote(self.promoted)

    def hand(self, text, name):
        path = self.dir / 'candidates' / name
        path.write_text(text, encoding='utf-8', newline='\n')
        return path

    def test_not_promoted(self):
        fresh = self.dir / 'empty.sqlite'
        shutil_copy = __import__('shutil').copyfile
        shutil_copy(self.golden, fresh)
        with IS.open_store(fresh) as empty:
            approved = DI.parse_manifest(self.promoted.read_bytes())
            self.assertEqual(I.verify_manifest(empty, 1, approved.sha256, []).code, 'MANIFEST_NOT_PROMOTED')
        raised = self.hand(fi.manifest(version=2, repositories=[{'id': REPOSITORY}, {'id': 'added-by-hand'}]), 'h.json')
        self.assertEqual(self.verify(raised).code, 'MANIFEST_NOT_PROMOTED')

    def test_digest_mismatch(self):
        text = self.promoted.read_text(encoding='utf-8')
        for changed in (text + ' ', text.replace('2' * 64, '7' * 64), text.replace('4' * 64, '8' * 64)):
            with self.subTest(changed=changed[-30:]):
                self.assertEqual(self.verify(self.hand(changed, 'c.json')).code, 'MANIFEST_DIGEST_MISMATCH')

    def test_replayed(self):
        """The proof's row: versions 1 then 2 promoted; version 1's bytes put back."""
        self.promote(self.candidate(name='v2.json', version=2))
        self.assertIsNone(self.verify().code)
        self.live.write_bytes(self.promoted.read_bytes())
        self.assertEqual(self.verify().code, 'DECISION_REPLAYED')

    def test_a_later_unconfirmed_promotion_is_no_replay(self):
        def refuse(source, target):
            raise PermissionError('held open')
        self.replace = refuse
        self.assertRefused('PROMOTION_FAILED', self.promote, self.candidate(name='v2.json', version=2), refusal=False)
        self.assertIsNone(self.verify().code)

    def test_a_hand_written_promotion_without_a_design_acceptance(self):
        """The proof's row: a promotion receipt written into the store by hand for a manifest whose design has
        no acceptance receipt."""
        text = fi.manifest(version=2, designs=((REPOSITORY, fi.OTHER_CHANGE, self.repos.second),))
        path = self.hand(text, 'v2.json')
        self.hand_promotion(2, text, designs=[{'repository': REPOSITORY, 'change': fi.OTHER_CHANGE,
                                               'commit': self.repos.second, 'acceptance': fi.D.new_decision_id(),
                                               'sequence': 1}])
        self.assertEqual(self.verify(path).code, 'DESIGN_ACCEPTANCE_MISSING')

    def test_a_hand_written_decision_is_not_well_formed(self):
        intent = json.loads(self.store.get('dispatch-inputs/v1/promotion/1').intent_json)
        decision = intent['decision']
        text = fi.manifest(version=2)
        path = self.hand(text, 'v2.json')
        digest = f'sha256:{DI.parse_manifest(path.read_bytes()).sha256}'
        decision['subject'].update(version=2, digest=digest, previous={'version': 1, 'digest': intent['digest']})
        decision['statement']['attributedTo'] = PM  # a model's statement in the Owner's format
        hand = {**intent, 'decision': decision, 'version': 2, 'digest': digest,
                'previous': decision['subject']['previous'], 'text': text}
        self.store.reserve(I.promotion_key(2), hand, actor='by-hand')
        self.assertEqual(self.verify(path).code, 'DECISION_RECORD_INVALID')

    def test_a_design_entry_the_promotion_did_not_bind(self):
        approved = DI.parse_manifest(self.promoted.read_bytes())
        answer = I.verify_manifest(self.store, 1, approved.sha256, [
            {'repository': REPOSITORY, 'change': CHANGE, 'commit': self.repos.second}])
        self.assertEqual(answer.code, 'DESIGN_ACCEPTANCE_MISSING')
        with self.assertRaises(ValueError):
            I.verify_manifest(self.store, 0, approved.sha256, [])


# ---------------------------------------------------------------------------- custody and the command line


class Custody(Base):
    def test_a_fixture_context_never_reaches_the_managed_store(self):
        """The authorization recorder's test of the same name is the pattern (OA-11 is the incident it
        prevents): every act with the test's context, the managed root, its store and the managed context
        forbidden."""
        forbid = AssertionError('the managed data root or its integration store')
        with mock.patch.object(IR.paths, 'resolve', side_effect=forbid), \
                mock.patch.object(IR.paths, 'ensure', side_effect=forbid), \
                mock.patch.object(IR.store_module, 'open_store', side_effect=forbid), \
                mock.patch.object(IR, 'managed_context', side_effect=forbid), \
                mock.patch.object(DI, 'manifest_path', side_effect=forbid):
            self.delegate_design()
            self.accept(self.repos.second)  # an Owner acceptance may supersede a delegated one (not the reverse)
            self.promote(self.candidate(designs=((REPOSITORY, CHANGE, self.repos.second),)))
            IR.manifest_resolve(self.ctx, 1)
            IR.status(self.ctx)
            for missing in ({'store': None}, {'state_root': None}, {'harness': None}, {'manifest_path': None},
                            {'manifest_path': Path('relative.json')}):
                with self.subTest(missing=missing), self.assertRaises(ValueError):
                    IR.design_prepare(self.context(**missing), self.repos.project, REPOSITORY, CHANGE,
                                      self.repos.first)
        self.assertTrue(self.store.path.is_relative_to(self.root))
        self.assertIsNone(self.verify().code)

    def test_the_managed_context_is_built_only_from_the_managed_root(self):
        res = mock.Mock(name='resolution')
        made = []

        def ensure(category, given, *parts):
            self.assertIs(given, res)
            made.append((category, *parts))
            return self.dir / 'managed' / category / Path(*parts) if parts else self.dir / 'managed' / category

        @contextlib.contextmanager
        def opened():
            yield self.store

        with mock.patch.object(IR.paths, 'resolve', return_value=res), \
                mock.patch.object(IR.paths, 'ensure', side_effect=ensure), \
                mock.patch.object(IR.store_module, 'open_store', return_value=opened()) as open_store, \
                mock.patch.object(DI, 'manifest_path', return_value=self.dir / 'managed' / 'm.json') as manifest:
            with IR.managed_context() as ctx:
                self.assertEqual((ctx.state_root, ctx.store, ctx.manifest_path, ctx.harness, ctx.checkout),
                                 (self.dir / 'managed' / 'state', self.store, self.dir / 'managed' / 'm.json',
                                  fi.REPO, fi.REPO))
        self.assertEqual(made, [('state',), ('state', 'dispatch'), ('state', 'integration')])
        open_store.assert_called_once_with(self.dir / 'managed' / 'state' / 'integration' / 'integration.sqlite')
        manifest.assert_called_once_with(res)

    def test_importing_the_commands_loads_no_gitea_and_no_credential_module(self):
        code = ('import importlib.util, json, sys\n'
                'spec = importlib.util.spec_from_file_location("input_recorder", sys.argv[1])\n'
                'module = importlib.util.module_from_spec(spec); sys.modules["input_recorder"] = module\n'
                'spec.loader.exec_module(module)\n'
                'print(json.dumps(sorted(getattr(m, "__file__", None) or "" for m in list(sys.modules.values()))))\n')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(fi.OWNER / 'input_recorder.py')],
                                capture_output=True, text=True, encoding='utf-8', timeout=fx.WAIT_CEILING_S,
                                stdin=subprocess.DEVNULL,
                                env={**os.environ, 'AIEH_DATA_ROOT': str(self.dir / 'no-data-root')})
        self.assertEqual(result.returncode, 0, result.stderr)
        files = [Path(f) for f in json.loads(result.stdout) if f]
        loaded = {f.resolve().relative_to(fi.REPO).as_posix() for f in files if f.resolve().is_relative_to(fi.REPO)}
        self.assertIn('integrations/owner/input_recorder.py', loaded)
        self.assertIn('integrations/dispatch/dispatch_inputs.py', loaded)
        forbidden = sorted(f for f in loaded if f.startswith(('integrations/gitea/', 'integrations/credentials/'))
                           or f.endswith('authorization_recorder.py'))
        self.assertEqual(forbidden, [])
        self.assertFalse((self.dir / 'no-data-root').exists())


# ---------------------------------------------------------------------------- slice 2b (the independent review)


def binding(sequence, commit, acceptance):
    return {'repository': REPOSITORY, 'change': CHANGE, 'commit': commit, 'acceptance': acceptance,
            'sequence': sequence}


class BasisAuthority(Base):
    """F1: a basis is an authority of its type, structurally, or the delegated decision is refused (fail
    closed): the anchor names a Decisions entry of the log at HEAD; a commitment's entry is titled
    "Commitment:" and holds the quote; an envelope's is titled "Owner standing authorization:" and holds the
    quote in its verbatim block."""

    def anchored(self, factory, anchor, quote):
        return factory(link=f'{G.LOG}#{anchor}', quote=quote)

    def test_delegation_basis_not_authority(self):
        cases = [  # (what, the basis of a promotion)
            ('an Owner direction', self.anchored(fi.envelope, fi.DIRECTION_ANCHOR, fi.DIRECTION_QUOTE)),
            ('a per-act Owner authorization', self.anchored(fi.envelope, fi.AUTHORIZATION_ANCHOR,
                                                            fi.AUTHORIZATION_QUOTE)),
            ('prose of the standing authorization outside its block',
             self.anchored(fi.envelope, fi.ENVELOPE_ANCHOR, fi.ENVELOPE_PROSE)),
            ('a prepared, not granted, Owner-actions row', self.anchored(fi.envelope, fi.ENVELOPE_ANCHOR, fi.OA_ROW)),
            ('another entry\'s block, anchored at the standing authorization',
             self.anchored(fi.envelope, fi.ENVELOPE_ANCHOR, fi.DIRECTION_QUOTE)),
            ('a commitment', self.anchored(fi.envelope, fi.COMMITMENT_ANCHOR, fi.COMMITMENT)),
        ]
        self.accept()
        for what, basis in cases:
            with self.subTest(what=what):
                self.assertUnchanged('DELEGATION_BASIS_NOT_AUTHORITY', self.delegate_promotion, self.candidate(),
                                     basis=basis)
        for anchor in (fi.ENVELOPE_ANCHOR, fi.DIRECTION_ANCHOR):
            with self.subTest(commitment_at=anchor):
                self.assertUnchanged('DELEGATION_BASIS_NOT_AUTHORITY', self.delegate_design, self.repos.second,
                                     basis=self.anchored(fi.commitment, anchor, fi.COMMITMENT))

    def test_an_absent_anchor_is_not_recorded_and_a_link_without_one_is_invalid(self):
        self.assertUnchanged('DELEGATION_BASIS_NOT_RECORDED', self.delegate_design,
                             basis=self.anchored(fi.commitment, 'no-such-entry', fi.COMMITMENT))
        self.assertUnchanged('DELEGATION_BASIS_INVALID', self.delegate_design, basis=fi.commitment(link=G.LOG))
        self.assertUnchanged('DELEGATION_BASIS_INVALID', self.delegate_design,
                             basis=fi.commitment(link=f'{G.LOG}#Not An Anchor'))

    def test_a_quote_of_the_block_wrapped_differently_is_its_words(self):
        """The block is compared with runs of whitespace collapsed on both sides."""
        self.accept()
        quote = '  '.join(fi.ENVELOPE.split())  # other spacing than the log's wrapped lines
        self.delegate_promotion(self.candidate(), basis=fi.envelope(quote=quote))
        self.assertIsNone(self.verify().code)

    def test_the_real_log_at_head_refuses_the_prepared_d1_envelope(self):
        """R4b, read-only at this checkout's HEAD: OA-22 (j), the D1 manifest envelope, is prepared and not
        granted. Anchored at any Decisions entry of the log, it is no standing authorization: a delegated
        promotion against the real log fails closed."""
        with ra.open_repository(fi.REPO, config='repository', ceilings=[str(fi.REPO.parent)]) as repo:
            commit = repo.head().commit
            text = repo.blob(commit, G.LOG).decode('utf-8')
        start = text.index('(j) the D1 manifest envelope')
        quote = text[start:start + 120]
        anchors = [m.group('anchor') for m in map(G.ENTRY_START.match, text.splitlines()) if m]
        self.assertTrue(anchors)
        view = G.HarnessView(commit, 'decisions/0018.md', '', 'sha256:' + '0' * 64, text)
        for anchor in anchors:
            with self.subTest(anchor=anchor):
                refusal = G.BASIS_TYPES['envelope'].unrecorded(self.anchored(fi.envelope, anchor, quote), view)
                self.assertIn(refusal[0], ('DELEGATION_BASIS_NOT_AUTHORITY', 'DELEGATION_BASIS_NOT_RECORDED'))
        with self.assertRaises(G.DelegationRefused) as caught:
            G.read_authority(fi.REPO, I.PROMOTION, PM, self.anchored(fi.envelope, 'commitment-d1', quote))
        self.assertEqual(caught.exception.code, 'DELEGATION_BASIS_NOT_AUTHORITY')


class OwnerHead(Base):
    """F8: a delegated acceptance never supersedes an Owner acceptance (decision 0018 point 4.8)."""

    def test_owner_acceptance_head(self):
        self.accept()
        refused = self.assertUnchanged('OWNER_ACCEPTANCE_HEAD', self.delegate_design, self.repos.second)
        self.assertIn('is the Owner\'s', refused.detail)

    def test_the_other_successions_are_open(self):
        self.delegate_design()
        self.delegate_design(self.repos.second)  # delegated over delegated
        self.accept()  # Owner over delegated
        self.assertEqual([d['head']['authority']['authority'] for d in IR.status(self.ctx)['designs']], ['owner'])
        # promotions are not gated by authority: a delegated promotion after an Owner one
        self.promote(self.candidate())
        self.delegate_promotion(self.candidate(name='v2.json', version=2))
        self.assertIsNone(self.verify().code)


class CrashPaths(Base):
    """F7: an act that stops after its reservation leaves its receipt failed when it can, and the command line
    answers a code, never a traceback."""

    def test_io_failed_writing_a_challenge_records_nothing(self):
        blocked = self.dir / 'state-is-a-file'
        blocked.write_text('x', encoding='utf-8')
        self.ctx = self.context(state_root=blocked)
        refused = self.assertUnchanged('IO_FAILED', IR.design_prepare, self.ctx, self.repos.project, REPOSITORY,
                                       CHANGE, self.repos.first)
        self.assertNotIn('receipt', refused.details)

    def test_a_design_act_that_stops_after_its_reservation_fails_its_receipt(self):
        challenge = self.design_challenge()
        with mock.patch.object(IR, '_write_copy', side_effect=OSError('disk full')):
            refused = self.assertRefused('IO_FAILED', IR.design_record, self.ctx, challenge['shown']['nonce'],
                                         fi.statement(CHANGE), recorded_by=fi.RECORDED_BY, refusal=False)
        key = I.design_key(REPOSITORY, CHANGE, 1)
        self.assertEqual(refused.details['receipt'], key)
        self.assertEqual(self.receipts()[key], ('failed', ['reserved', 'failed']))
        # the challenge is single-use, and the detail says its decision was not confirmed
        again = self.assertUnchanged('CHALLENGE_CONSUMED', IR.design_record, self.ctx, challenge['shown']['nonce'],
                                     fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        self.assertIn('failed: its decision was not confirmed', again.detail)
        design = IR.status(self.ctx)['designs'][0]
        self.assertEqual((design['head'], design['failed'], design['next']), (None, [1], 2))
        # the position is spent; the next acceptance takes sequence 2 and supersedes nothing
        accepted = self.accept()
        self.assertEqual((accepted['receipt']['operation_key'][-2:], accepted['decision']['subject']['supersedes']),
                         ('/2', None))

    def test_a_delegated_design_act_that_stops_after_its_reservation_fails_its_receipt(self):
        with mock.patch.object(IR, '_write_copy', side_effect=OSError('disk full')):
            self.assertRefused('IO_FAILED', self.delegate_design, refusal=False)
        self.assertEqual(self.receipts()[I.design_key(REPOSITORY, CHANGE, 1)][0], 'failed')

    def test_a_promotion_whose_copy_cannot_be_written_fails_with_the_live_file_as_it_was(self):
        self.accept()
        with mock.patch.object(IR, '_write_copy', side_effect=OSError('disk full')):
            refused = self.assertRefused('PROMOTION_FAILED', self.promote, self.candidate(), refusal=False)
        self.assertIn('copy:', refused.detail)
        self.assertEqual(self.receipts()[I.promotion_key(1)], ('failed', ['reserved', 'failed']))
        self.assertIsNone(self.live_bytes())
        self.assertEqual(IR.status(self.ctx)['promotion']['failed'], [1])

    def test_a_tampered_challenge_and_an_os_error_are_codes_on_the_command_line(self):
        self.accept()
        challenge = IR.manifest_prepare(self.ctx, self.candidate())
        nonce = challenge['shown']['nonce']
        path = self.dir / 'state' / 'owner-authorization' / 'dispatch-inputs' / 'challenges' / f'{nonce}.json'
        altered = json.loads(path.read_text(encoding='utf-8'))
        altered['candidate'] = '{"schema": "tampered"}\n'
        altered['subject']['digest'] = 'sha256:' + hashlib.sha256(altered['candidate'].encode()).hexdigest()
        path.write_text(json.dumps(altered), encoding='utf-8')
        statement = self.dir / 's.json'
        statement.write_text(json.dumps(fi.statement('approved-inputs-v1')), encoding='utf-8')
        out, err = io.StringIO(), io.StringIO()

        @contextlib.contextmanager
        def context():
            yield self.ctx
        code = IR.main(['manifest', 'record', '--challenge', nonce, '--statement', str(statement), '--recorded-by',
                        fi.RECORDED_BY], out, err, context=context)
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith('input-recorder: CHALLENGE_INVALID: '), err.getvalue())

        @contextlib.contextmanager
        def unwritable():
            raise PermissionError('the managed root is not writable')
            yield  # noqa: unreachable
        err = io.StringIO()
        self.assertEqual(IR.main(['status'], io.StringIO(), err, context=unwritable), 2)
        self.assertTrue(err.getvalue().startswith('input-recorder: IO_FAILED: PermissionError'), err.getvalue())
        self.assertNotIn('Traceback', err.getvalue())


class SeriesIntegrity(Base):
    """F2 and F3: the verifier walks positions 1 to N by direct lookups."""

    def setUp(self):
        super().setUp()
        self.accept()
        self.promote(self.candidate())
        self.v1 = json.loads(self.store.get(I.promotion_key(1)).intent_json)['decision']

    def live_at(self, version):
        self.live.write_text(fi.manifest(version=version), encoding='utf-8', newline='\n')

    def refused_with(self, fragment):
        answer = self.verify()
        self.assertEqual(answer.code, 'DECISION_RECORD_INVALID')
        self.assertIn(fragment, answer.detail)

    def test_a_missing_position_below_the_version(self):
        self.hand_promotion(3, fi.manifest(version=3))
        self.live_at(3)
        self.refused_with('no receipt at position 2')

    def test_a_repeated_decision_id_or_challenge(self):
        self.hand_promotion(2, fi.manifest(version=2), decision_id=self.v1['decisionId'])
        self.live_at(2)
        self.refused_with('repeats the decisionId')

    def test_a_repeated_challenge(self):
        self.hand_promotion(2, fi.manifest(version=2), nonce=self.v1['shown']['nonce'])
        self.live_at(2)
        self.refused_with('repeats the challenge')

    def test_a_previous_that_is_not_the_prior_confirmed_promotion(self):
        self.hand_promotion(2, fi.manifest(version=2), previous={'version': 1, 'digest': 'sha256:' + '0' * 64})
        self.live_at(2)
        self.refused_with('not the prior confirmed promotion')

    def test_a_promotion_receipt_not_reserved_by_the_recorder(self):
        self.hand_promotion(2, fi.manifest(version=2), actor='by-hand')
        self.live_at(2)
        self.refused_with("reserved by 'by-hand'")

    def test_a_design_receipt_not_reserved_by_the_recorder(self):
        decision = self.hand_design(2, self.repos.second, actor='by-hand')
        text = fi.manifest(version=2, designs=((REPOSITORY, CHANGE, self.repos.second),))
        self.hand_promotion(2, text, designs=[binding(2, self.repos.second, decision)])
        self.live.write_text(text, encoding='utf-8', newline='\n')
        self.refused_with("reserved by 'by-hand'")

    def test_a_careful_hand_written_series_still_loads(self):
        """What remains outside the threat model (decision 0010 point 1): a store written by hand with the
        recorder's actor, fresh ids and the right previous is accepted; documented, not prevented."""
        self.hand_promotion(2, fi.manifest(version=2))
        self.live_at(2)
        self.assertIsNone(self.verify().code)


class Mutants(Base):
    """F5: tests that kill the review's surviving mutants M4 to M9, M21, M22 and M28."""

    def setUp(self):
        super().setUp()
        self.first = self.accept()['decision']['decisionId']
        self.promote(self.candidate())

    def promoted_by_hand(self, commit, bound):
        text = fi.manifest(version=2, designs=((REPOSITORY, CHANGE, commit),))
        self.hand_promotion(2, text, designs=[bound])
        self.live.write_text(text, encoding='utf-8', newline='\n')
        return self.verify()

    def test_m4_the_bound_acceptance_id(self):
        answer = self.promoted_by_hand(self.repos.first, binding(1, self.repos.first, fi.D.new_decision_id()))
        self.assertEqual(answer.code, 'DESIGN_ACCEPTANCE_MISSING')

    def test_m5_an_unconfirmed_design_receipt(self):
        decision = self.hand_design(2, self.repos.second, state='reserved')
        answer = self.promoted_by_hand(self.repos.second, binding(2, self.repos.second, decision))
        self.assertEqual(answer.code, 'DESIGN_ACCEPTANCE_MISSING')

    def test_m6_the_binding_commit(self):
        answer = self.promoted_by_hand(self.repos.first, binding(1, self.repos.second, self.first))
        self.assertEqual(answer.code, 'DESIGN_ACCEPTANCE_MISSING')

    def test_m7_the_accepted_commit(self):
        second = self.accept(self.repos.second)['decision']['decisionId']
        answer = self.promoted_by_hand(self.repos.first, binding(2, self.repos.first, second))
        self.assertEqual(answer.code, 'DESIGN_ACCEPTANCE_MISSING')

    def test_m8_the_promotion_receipt_binds_its_decision(self):
        text = fi.manifest(version=2)
        self.hand_promotion(2, text, intent_changes={'schema': 'another/v1'})
        self.live.write_text(text, encoding='utf-8', newline='\n')
        self.assertEqual(self.verify().code, 'DECISION_RECORD_INVALID')

    def test_m9_the_design_receipt_binds_its_decision(self):
        decision = self.hand_design(2, self.repos.second, intent_changes={'sequence': 3})
        answer = self.promoted_by_hand(self.repos.second, binding(2, self.repos.second, decision))
        self.assertEqual(answer.code, 'DECISION_RECORD_INVALID')

    def test_m21_the_same_commit_accepted_again_after_the_challenge(self):
        """The review's repro2: the binding (acceptance id and sequence) changed under the challenge."""
        challenge = IR.manifest_prepare(self.ctx, self.candidate(name='v2.json', version=2))
        self.accept()  # the same commit again: sequence 2
        self.assertUnchanged('CHALLENGE_STALE', IR.manifest_record, self.ctx, challenge['shown']['nonce'],
                             fi.statement('approved-inputs-v2'), recorded_by=fi.RECORDED_BY)

    def test_m22_a_design_challenge_whose_series_went_back(self):
        """Not redundant with the position check: after a store restore the challenged position is free but is
        no longer the next one."""
        challenge = self.design_challenge(self.repos.second)
        self.assertEqual(challenge['position'], 2)
        restored = self.dir / 'restored.sqlite'
        __import__('shutil').copyfile(self.golden, restored)
        with IS.open_store(restored) as store:
            self.ctx = self.context(store=store)
            with self.assertRaises(IR.RecorderError) as caught:
                IR.design_record(self.ctx, challenge['shown']['nonce'], fi.statement(CHANGE),
                                 recorded_by=fi.RECORDED_BY)
            self.assertEqual(caught.exception.code, 'CHALLENGE_STALE')
            self.assertEqual(store.attempts(), [])

    def test_m28_the_status_is_read_at_head_not_in_the_work_tree(self):
        harness = self.repos.harness['status-worktree']
        self.assertTrue(G.accepted_by_owner((harness / 'decisions' / '0018-fixture-delegation.md')
                                            .read_text(encoding='utf-8')))
        self.ctx = self.context(harness=harness)
        self.assertUnchanged('DELEGATION_NOT_ACCEPTED', self.delegate_design, self.repos.second)


class EveryCode(unittest.TestCase):
    def test_every_code_of_the_recorder_table_is_shown_by_a_test_of_this_module(self):
        source = Path(__file__).read_text(encoding='utf-8')
        shown = set(re.findall(r"(?:assertUnchanged|assertRefused|self\.refused)\('([A-Z_]+)'", source))
        self.assertEqual(set(IR.REMEDIES) - shown, set())


class CommandLine(Base):
    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()

        @contextlib.contextmanager
        def context():
            yield self.ctx

        code = IR.main(list(argv), out, err, context=context)
        return code, out.getvalue(), err.getvalue()

    def write_json(self, name, value):
        path = self.dir / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def test_the_owner_path_and_the_delegated_path_on_the_command_line(self):
        code, out, err = self.main('design', 'prepare', '--project', str(self.repos.project), '--repository',
                                   REPOSITORY, '--change', CHANGE, '--commit', self.repos.first)
        self.assertEqual((code, err), (0, ''))
        nonce = json.loads(out)['shown']['nonce']
        code, out, err = self.main('design', 'record', '--challenge', nonce, '--statement',
                                   self.write_json('s.json', fi.statement(CHANGE)), '--recorded-by', fi.RECORDED_BY)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['receipt']['state'], 'confirmed')
        code, out, err = self.main('design', 'record', '--challenge', nonce, '--statement',
                                   self.write_json('s.json', fi.statement(CHANGE)), '--recorded-by', fi.RECORDED_BY)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('input-recorder: CHALLENGE_CONSUMED: '), err)
        self.assertIn('Remedy: ', err)
        code, out, err = self.main('manifest', 'delegate', '--candidate', str(self.candidate()), '--decided-by', PM,
                                   '--basis', self.write_json('b.json', fi.envelope()))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['authority']['point'], '3.3')
        code, out, err = self.main('manifest', 'delegate', '--candidate', str(self.candidate(name='v2.json', version=2)),
                                   '--decided-by', EM, '--basis', self.write_json('b.json', fi.envelope()))
        self.assertEqual(code, 2)
        self.assertIn('DECIDER_NOT_DELEGATED', err)
        code, out, err = self.main('status')
        self.assertEqual(code, 0)
        status = json.loads(out)
        self.assertEqual((status['promotion']['head']['version'], status['promotion']['next']), (1, 2))
        self.assertEqual(status['promotion']['head']['authority']['authority'], 'delegated')
        self.assertEqual([(d['change'], d['head']['sequence'], d['head']['authority']['authority'])
                          for d in status['designs']], [(CHANGE, 1, 'owner')])

    def test_exit_one_on_a_failed_or_unknown_promotion_and_resolve(self):
        self.accept()
        self.replace = lambda source, target: (_ for _ in ()).throw(PermissionError('held open'))
        code, _out, err = self.main('manifest', 'delegate', '--candidate', str(self.candidate()), '--decided-by', PM,
                                    '--basis', self.write_json('b.json', fi.envelope()))
        self.assertEqual(code, 1)
        self.assertIn('PROMOTION_FAILED', err)
        code, out, err = self.main('manifest', 'resolve', '--version', '1')
        self.assertEqual((code, json.loads(out)['receipt']['state']), (0, 'failed'))
        code, _out, err = self.main('manifest', 'resolve', '--version', '9')
        self.assertEqual(code, 2)
        self.assertIn('RECEIPT_MISSING', err)

    def test_unreadable_inputs_are_refused_with_their_codes(self):
        bad = self.dir / 'bad.json'
        bad.write_text('{', encoding='utf-8')
        code, _out, err = self.main('design', 'record', '--challenge', 'ab' * 16, '--statement', str(bad),
                                    '--recorded-by', fi.RECORDED_BY)
        self.assertEqual(code, 2)
        self.assertIn('STATEMENT_INVALID', err)
        code, _out, err = self.main('manifest', 'delegate', '--candidate', str(self.candidate()), '--decided-by', PM,
                                    '--basis', str(bad))
        self.assertEqual(code, 2)
        self.assertIn('DELEGATION_BASIS_INVALID', err)
        code, _out, err = self.main('design', 'prepare', '--project', str(self.repos.project), '--repository',
                                    'Bad Id', '--change', CHANGE, '--commit', self.repos.first)
        self.assertEqual(code, 2)
        self.assertIn('manifest repository id', err)


if __name__ == '__main__':
    unittest.main()
