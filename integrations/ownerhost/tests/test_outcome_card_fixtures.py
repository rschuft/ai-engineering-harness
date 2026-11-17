"""The outcome card's projection fixtures pinned to the projection (plan leaf U-04.2): the answers of
``GET /outcomes/{outcome_id}`` committed for the Owner host's card tests (``apps/owner-host/src/areas/fixtures/
outcome-projection/``, exported by ``outcome_card_fixtures.py``) are what projection.py answers now.

- ``Committed``: every scenario is committed and nothing else; ``schema.json`` is the projection's own constants; each
  fixture names its source and holds only the projection's statuses, codes, verdicts and coverage, and no local path;
  together they cover what the card must show (each status, an ``_UNPROVEN`` code, ``disclosed``, the lineage
  verdicts ``failed`` and ``incomplete``, an unreadable store, fixture, live and unknown authority, the refusals, and
  the reconnect pair from running to succeeded).
- ``Regenerated``: each scenario is made again by the dispatcher's own writers and the route, and its answers have the
  committed ones' shape (every key at every depth with its value's type) and decisive values. A change of the
  projection's schema fails here until the fixtures are exported again (``outcome_card_fixtures.py``), and the card's
  tests then run against the new answers.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import outcome_card_fixtures as F

CATEGORY = 'integration'
P, TP = F.P, F.TP


def committed(name: str) -> dict:
    return json.loads((F.OUT / f'{name}.json').read_text(encoding='utf-8'))


def bodies():
    for name in F.SCENARIOS:
        for answer in committed(name)['answers']:
            yield name, answer


class Committed(unittest.TestCase):

    def test_every_scenario_is_committed_and_nothing_else(self):
        self.assertEqual(sorted(p.name for p in F.OUT.iterdir()),
                         sorted([f'{name}.json' for name in F.SCENARIOS] + ['schema.json']))

    def test_the_schema_is_the_projection_s_constants(self):
        self.assertEqual(json.loads((F.OUT / 'schema.json').read_text(encoding='utf-8')),
                         {'generatedBy': F.GENERATOR, **F.schema()})

    def test_each_fixture_names_its_source_and_holds_only_the_projection_s_values(self):
        codes = set(P.CODES) | {code + P.UNPROVEN for code in P.CODES} | {'NO_ATTEMPT' + P.UNPROVEN}
        home = str(Path.home()).lower()
        for name in F.SCENARIOS:
            document = committed(name)
            with self.subTest(scenario=name):
                self.assertEqual((document['scenario'], document['source'], document['generatedBy']),
                                 (name, F.SCENARIOS[name][1], F.GENERATOR))
                self.assertFalse([s for s in TP.strings(document) if home in s.lower()], 'a local path')
        for name, answer in bodies():
            body = answer['body']
            with self.subTest(scenario=name, status=answer['status']):
                if answer['status'] != 200:
                    self.assertEqual(P.STATUS[body['code']], answer['status'])
                    self.assertEqual(body['remedy'], P.REMEDIES[body['code']])
                    continue
                self.assertEqual(body['format'], P.FORMAT)
                self.assertIn(body['lineageVerdict'], ('complete', 'incomplete', 'failed'))
                self.assertEqual(body['coverage'], P.COVERAGE)
                for attempt in body['attempts']:
                    self.assertIn(attempt['executionStatus'], P.STATUSES)
                    self.assertIn(attempt['executionCode'], codes)
                    self.assertIn(attempt['authority']['shown'], (P.LIVE, P.FIXTURE, P.UNKNOWN))
                for task in body['tasks']:
                    self.assertIn(task['execution']['status'], P.STATUSES)
                    self.assertIn(task['execution']['code'], codes)

    def test_together_they_cover_what_the_card_must_show(self):
        statuses, codes, verdicts, authorities, refusals, stores = set(), set(), set(), set(), set(), set()
        authority_codes = set()
        restored = disclosed = False
        for _name, answer in bodies():
            body = answer['body']
            if answer['status'] != 200:
                refusals.add((answer['status'], body['code']))
                continue
            verdicts.add(body['lineageVerdict'])
            stores.add(body['sources']['integrationStore'] == 'read')
            for attempt in body['attempts']:
                statuses.add(attempt['executionStatus'])
                codes.add(attempt['executionCode'])
                authorities.add(attempt['authority']['shown'])
                authority_codes.add(attempt['authority']['code'])
                restored |= 'restoredRow' in attempt and attempt['executionCode'].endswith(P.UNPROVEN)
                disclosed |= bool(attempt.get('disclosed'))
            for task in body['tasks']:
                statuses.add(task['execution']['status'])
                codes.add(task['execution']['code'])
        self.assertEqual(statuses, set(P.STATUSES))
        self.assertTrue(restored and disclosed)
        self.assertLessEqual({'NO_ATTEMPT_UNPROVEN', 'STORE_UNAVAILABLE', 'ATTEMPT_LABEL_MISSING'}, codes)
        self.assertIn('ATTEMPT_AUTHORITY_UNBOUND', authority_codes)
        self.assertTrue({'failed', 'incomplete'} <= verdicts)
        self.assertEqual(authorities, {P.LIVE, P.FIXTURE, P.UNKNOWN})
        self.assertEqual(stores, {True, False})
        self.assertEqual({status for status, _ in refusals}, {400, 503})
        running, published = committed('reconnect')['answers']
        self.assertEqual([(a['executionStatus'], a['executionCode']) for a in
                          (running['body']['attempts'][0], published['body']['attempts'][0])],
                         [('running', 'RESULT_VERIFIED'), ('succeeded', 'RESULT_PUBLISHED')])
        self.assertEqual(running['body']['attempts'][0]['operationKey'], published['body']['attempts'][0]['operationKey'])

    def test_the_shape_comparison_sees_a_key_added_removed_or_retyped(self):
        [answer] = committed('pending-created')['answers']
        for change in (lambda b: b['attempts'][0].__setitem__('stageName', 'implement'),
                       lambda b: b['attempts'][0].pop('shownBy'),
                       lambda b: b['tasks'][0]['execution'].__setitem__('status', 1),
                       lambda b: b.__setitem__('coverage', None)):
            changed = json.loads(json.dumps(answer))
            change(changed['body'])
            self.assertNotEqual(F.shape(changed), F.shape(answer))



@unittest.skipIf(TP.tar.BASH is None, 'no Git Bash (Windows) or bash: RESULT runs the harness\'s script')
class Regenerated(unittest.TestCase):
    """Each scenario made again now: the committed answers' shape and decisive values."""

    @classmethod
    def setUpClass(cls):
        F.Exporter.setUpClass()

    @classmethod
    def tearDownClass(cls):
        F.Exporter.tearDownClass()

    def test_each_fixture_is_what_the_projection_answers_now(self):
        for name in F.SCENARIOS:
            with self.subTest(scenario=name):
                made = F.generate(name)
                kept = committed(name)['answers']
                self.assertEqual([a['status'] for a in made], [a['status'] for a in kept])
                self.assertEqual([F.shape(a) for a in made], [F.shape(a) for a in kept],
                                 f'{name}: the projection\'s schema changed; export the fixtures again '
                                 f'({F.GENERATOR}) and check the card against them')
                self.assertEqual([F.decisive(a) for a in made], [F.decisive(a) for a in kept])


if __name__ == '__main__':
    unittest.main()
