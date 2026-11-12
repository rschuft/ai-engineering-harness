"""Tests for tools/check_control_catalog.py and policy/control-catalog.json (plan leaf G-01.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The committed catalog must pass against the committed inventory, lineage schema and README.
Each negative case mutates an in-memory copy of the catalog (or of the inventory or the README)
and must fail with the expected code. Everything runs in process against inputs loaded once;
nothing is launched, no temporary directory is made and the checkout is only read.
"""
from pathlib import Path
import contextlib
import importlib.util
import io
import json
import unittest

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / 'tools' / 'check_control_catalog.py'

_spec = importlib.util.spec_from_file_location('check_control_catalog', CHECKER)
ccc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccc)

CATALOG_TEXT = (REPO / 'policy' / 'control-catalog.json').read_text(encoding='utf-8')
INVENTORY_TEXT = (REPO / 'security' / 'inventory.json').read_text(encoding='utf-8')
INVENTORY = json.loads(INVENTORY_TEXT)
README = (REPO / 'policy' / 'control-catalog.md').read_text(encoding='utf-8')
INPUTS = ccc.load_inputs(REPO)
REQUIRED = {'isolation', 'credentials', 'ci', 'code-review', 'authorization', 'evidence',
            'recovery'}


def fresh():
    return json.loads(CATALOG_TEXT)


def control(c, ident):
    for item in c['controls']:
        if item['id'] == ident:
            return item
    raise AssertionError(f'fixture has no control {ident!r}')


def problems(c, inv=None, readme=None, inputs=None):
    return ccc.evaluate(c, INVENTORY if inv is None else inv, INPUTS if inputs is None else inputs,
                        readme)


def codes(c, inv=None, readme=None, inputs=None):
    return {p.code for p in problems(c, inv, readme, inputs)}


def run_main(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = ccc.main(['--root', str(REPO), *args])
    return rc, out.getvalue()


class CommittedCatalog(unittest.TestCase):
    category = 'contract'

    def test_catalog_passes(self):
        found = problems(fresh(), readme=README)
        self.assertEqual(found, [], '\n'.join(map(str, found)))

    def test_every_required_control_has_an_objective_subject_boundary_and_applicability(self):
        """The leaf's acceptance, read straight from the data, independently of the checker."""
        lineage = json.loads((REPO / 'integrations' / 'lineage' / 'lineage_schema.json')
                             .read_text(encoding='utf-8'))
        settled = {k['kind'] for k in lineage['kinds'] if k['identity']['settled'] is True}
        principals = {p['id']: p for p in INVENTORY['principals']}
        catalog = fresh()
        profiles = {p['id'] for p in catalog['profiles']}
        self.assertEqual({c['category'] for c in catalog['controls']}, REQUIRED)
        for c in catalog['controls']:
            self.assertTrue(c['purpose'].strip(), c['id'])
            self.assertTrue(c['subject']['scope'].strip(), c['id'])
            self.assertTrue(c['subject']['kinds'] and set(c['subject']['kinds']) <= settled, c['id'])
            self.assertTrue(c['applicability']['events'], c['id'])
            self.assertTrue(set(c['applicability']['profiles']) <= profiles, c['id'])
            self.assertTrue(c['enforcement'], c['id'])
            for e in c['enforcement']:
                self.assertIn(e['boundary'], ('execution', 'git-ci', 'effect', 'evidence'), c['id'])
                self.assertIs(principals[e['principal']]['agent_controlled'], False, c['id'])
        # admitted by the Owner's sign-off of 2026-11-12, quoted verbatim from the bootstrap log
        self.assertEqual(catalog['admission']['status'], 'admitted')
        self.assertEqual(catalog['admission']['approval']['link'], 'evidence/bootstrap-log.md')
        self.assertIn(catalog['admission']['approval']['quote'],
                      (REPO / 'evidence' / 'bootstrap-log.md').read_text(encoding='utf-8'))
        self.assertNotEqual(catalog['admission']['performer'], 'authorization-recorder')

    def test_cli_lists_and_renders_the_readme_block(self):
        rc, out = run_main('--list')
        self.assertEqual(rc, 0, out)
        self.assertIn('policy/control-catalog.json: 8 controls in 7 categories', out)
        self.assertIn('EXEC-01 (isolation): attempt; baseline; execution:management-dispatcher', out)
        rc, out = run_main('--render')
        self.assertEqual(rc, 0)
        self.assertEqual(ccc.generated_block(README).strip(), out.strip())
        rc, _ = run_main('--catalog', str(REPO / 'policy' / 'no-such-catalog.json'))
        self.assertEqual(rc, 2)


class Mutations(unittest.TestCase):
    """Each rule fails its own mutation (in memory, against the shared inputs)."""

    def expect(self, code, c, inv=None, readme=None, inputs=None):
        found = codes(c, inv, readme, inputs)
        self.assertIn(code, found)
        return found

    def test_each_required_category_needs_a_control(self):
        c = fresh()
        c['controls'] = [r for r in c['controls'] if r['category'] != 'recovery']
        self.expect('CATEGORY_UNCOVERED', c)
        c = fresh()
        del c['categories']['recovery']
        self.expect('SCHEMA', c)
        c = fresh()
        c['categories']['recovery'] = ''
        self.expect('SCHEMA', c)

    def test_objective_and_subject(self):
        cases = [('purpose', ' ', 'OBJECTIVE_MISSING'),
                 ('subject', {'kinds': ['release'], 'scope': 'a release'}, 'SUBJECT_UNSETTLED'),
                 ('subject', {'kinds': ['ticket'], 'scope': 'a ticket'}, 'SUBJECT_INVALID'),
                 ('subject', {'kinds': ['commit']}, 'SUBJECT_INVALID'),
                 ('subject', {'kinds': ['commit'], 'scope': 'x', 'by': 'me'}, 'SUBJECT_INVALID'),
                 ('subject', {'kinds': ['commit'], 'scope': ''}, 'SUBJECT_INVALID'),
                 ('subject', {'kinds': [], 'scope': 'x'}, 'SUBJECT_INVALID'),
                 ('title', '', 'SCHEMA'),
                 ('category', 'quality', 'SCHEMA')]
        for key, value, code in cases:
            with self.subTest(key=key, code=code):
                c = fresh()
                control(c, 'SDLC-01')[key] = value
                self.expect(code, c)
        found = self.expect('SUBJECT_INVALID', fresh(), inputs=ccc.Inputs(REPO, {}, INPUTS.files))
        self.assertIn('SCHEMA', found)
        odd = {'kinds': [5, {'kind': 7}, {'kind': 'commit', 'identity': {'settled': True}}]}
        found = codes(fresh(), inputs=ccc.Inputs(REPO, odd, INPUTS.files))
        self.assertIn('SUBJECT_INVALID', found)

    def test_applicability(self):
        cases = [('SDLC-01', {}, 'APPLICABILITY_MISSING'),
                 ('SDLC-01', {'profiles': ['baseline'], 'events': []}, 'APPLICABILITY_MISSING'),
                 ('SDLC-01', {'profiles': ['baseline'], 'events': ['']}, 'APPLICABILITY_MISSING'),
                 ('SDLC-01', {'profiles': [], 'events': ['x']}, 'APPLICABILITY_MISSING'),
                 ('SDLC-01', {'profiles': ['baseline'], 'events': ['x'], 'when': 'x'},
                  'APPLICABILITY_MISSING'),
                 ('SDLC-01', {'profiles': ['nightly'], 'events': ['x']}, 'DANGLING_REF'),
                 ('EXEC-01', {'profiles': ['elevated'], 'events': ['x']}, 'APPLICABILITY_NARROW')]
        for ident, value, code in cases:
            with self.subTest(ident=ident, code=code):
                c = fresh()
                control(c, ident)['applicability'] = value
                self.expect(code, c)

    def test_enforcement(self):
        c = fresh()
        control(c, 'SDLC-01')['enforcement'] = []
        self.expect('ENFORCEMENT_MISSING', c)
        cases = [('boundary', 'agent-planning', 'ENFORCEMENT_INVALID'),
                 ('mechanism', '', 'ENFORCEMENT_INVALID'),
                 ('assets', [], 'ENFORCEMENT_INVALID'),
                 ('assets', ['nowhere'], 'DANGLING_REF'),
                 ('builds_at', ['Z-99.1'], 'DANGLING_REF'),
                 ('builds_at', [], 'DANGLING_REF'),
                 ('principal', 'nobody', 'DANGLING_REF'),
                 ('principal', 'engineering-agent', 'ENFORCER_UNTRUSTED'),
                 ('principal', 'bootstrap-host-agents', 'ENFORCER_UNTRUSTED'),
                 ('principal', 'release-job-environment', 'ENFORCER_UNTRUSTED')]
        for key, value, code in cases:
            with self.subTest(key=key, value=value):
                c = fresh()
                control(c, 'SDLC-01')['enforcement'][0][key] = value
                self.expect(code, c)
        # an untrusted domain alone disqualifies, even for a principal not flagged agent-controlled
        inv = json.loads(INVENTORY_TEXT)
        for p in inv['principals']:
            if p['id'] == 'engineering-agent':
                p['agent_controlled'] = False
        c = fresh()
        control(c, 'SDLC-01')['enforcement'][0]['principal'] = 'engineering-agent'
        self.expect('ENFORCER_UNTRUSTED', c, inv=inv)

    def test_exceptions(self):
        cases = [('EXEC-01', {'exception': 'scoped'}, 'EXCEPTION_FORBIDDEN'),
                 ('SEC-EXEC-01', {'exception': 'unsettled', 'exception_settled_at': 'G-06.3.1'},
                  'EXCEPTION_FORBIDDEN'),
                 ('SDLC-01', {'exception_settled_at': None}, 'EXCEPTION_UNSETTLED'),
                 ('SEC-PR-01', {'exception_settled_at': 'G-06.3.1'}, 'SCHEMA'),
                 ('SEC-PR-01', {'exception': 'waived'}, 'SCHEMA'),
                 ('SEC-PR-01', {'failure_effect': ''}, 'SCHEMA')]
        for ident, change, code in cases:
            with self.subTest(ident=ident, change=change):
                c = fresh()
                control(c, ident).update(change)
                self.expect(code, c)

    def test_profiles(self):
        def change(fn):
            c = fresh()
            fn(c)
            return c
        cases = [(lambda c: c['profiles'][0].update(applies={'input': 'risk', 'any_of': ['x']}),
                  'PROFILE_INVALID'),
                 (lambda c: c['profiles'][1].update(applies='always'), 'PROFILE_INVALID'),
                 (lambda c: c['profiles'][1]['applies'].update(input='mood'), 'PROFILE_INVALID'),
                 (lambda c: c['profiles'][1]['applies'].update(any_of=[]), 'PROFILE_INVALID'),
                 (lambda c: c['profiles'][1].update(obligations=''), 'PROFILE_INVALID'),
                 (lambda c: c['profiles'][1].update(id='Elevated Risk'), 'PROFILE_INVALID'),
                 (lambda c: c['profiles'][1]['applies'].update(note='x'), 'PROFILE_INVALID'),
                 (lambda c: c['resolution'].update(sources=[]), 'SCHEMA'),
                 (lambda c: c['profiles'].append(dict(c['profiles'][1])), 'PROFILE_INVALID'),
                 (lambda c: c['resolution'].update(unknown=''), 'SCHEMA'),
                 (lambda c: [control(c, i)['applicability'].update(profiles=['elevated'])
                             for i in ('AUTH-01', 'RECOVER-01')], 'PROFILE_EMPTY')]
        for n, (fn, code) in enumerate(cases):
            with self.subTest(case=n, code=code):
                self.expect(code, change(fn))

    def test_authority_and_admission(self):
        cases = [(lambda c: c['authority'].update(principal='owner-os-account'), 'AUTHORITY'),
                 (lambda c: c['exception_contract'].update(authority='engineering-agent'),
                  'AUTHORITY'),
                 (lambda c: c['exception_contract'].update(fields=['control']), 'SCHEMA'),
                 (lambda c: c['exception_contract'].update(rule=''), 'SCHEMA'),
                 (lambda c: c['exception_contract'].update(sources=[]), 'SCHEMA'),
                 (lambda c: c['authority'].update(operation='op-protected-merge'), 'AUTHORITY'),
                 (lambda c: c['admission'].update(operation='op-protected-merge'),
                  'ADMISSION_AUTHORITY'),
                 (lambda c: c['admission'].update(performer='owner-os-account'),
                  'ADMISSION_AUTHORITY'),
                 (lambda c: c['admission'].update(realization=''), 'SCHEMA'),
                 (lambda c: c['admission'].update(performer='authorization-recorder'),
                  'ADMISSION_AUTHORITY'),
                 (lambda c: c['admission'].update(repository='gitea-server'), 'DANGLING_REF'),
                 (lambda c: (c['admission'].update(status='admitted'), c['admission'].pop('approval', None)),
                  'OWNER_APPROVAL'),
                 (lambda c: c['admission'].update(status='admitted', approval={
                     'link': 'evidence/bootstrap-log.md', 'quote': 'The Owner signs off G-01.1 '
                     'at no revision at all'}), 'OWNER_APPROVAL'),
                 (lambda c: c['admission'].update(status='proposed', approval={'link': 'x', 'quote': 'y'}),
                  'SCHEMA'),
                 (lambda c: c['admission'].update(status='draft'), 'SCHEMA')]
        for n, (fn, code) in enumerate(cases):
            with self.subTest(case=n, code=code):
                c = fresh()
                fn(c)
                self.expect(code, c)
        # positive control: an approval quoted verbatim from the log is accepted; each part of
        # its shape is required, and an unreadable log accepts nothing
        log, quote = 'evidence/bootstrap-log.md', 'OA-18 \u2014 APPROVED: M-5 BLUEPRINT RECONCILIATION'
        c = fresh()
        c['admission'].update(status='admitted', approval={'link': log, 'quote': quote})
        self.assertEqual(problems(c), [])
        for approval in ({'link': log, 'quote': quote, 'by': 'x'}, {'link': 'README.md', 'quote': quote},
                         {'link': log, 'quote': 5}, {'link': log, 'quote': 'OA-18'}):
            with self.subTest(approval=approval):
                c['admission']['approval'] = approval
                self.expect('OWNER_APPROVAL', c)
        c['admission']['approval'] = {'link': log, 'quote': quote}
        files = ccc.csi.RepoFiles(REPO)
        files._text[log] = None
        self.expect('OWNER_APPROVAL', c, inputs=ccc.Inputs(REPO, INPUTS.lineage, files))
        # the inventory's Owner-only policy change is the only rule authority
        inv = json.loads(INVENTORY_TEXT)
        ops = {o['id']: o for o in inv['operations']}
        ops['op-policy-change']['owner_only'] = False
        self.expect('AUTHORITY', fresh(), inv=inv)
        # even an inventory that gave the recorder the policy change gives it no admission
        ops['op-policy-change'].update(owner_only=True, principal='authorization-recorder')
        c = fresh()
        c['authority']['principal'] = c['admission']['performer'] = 'authorization-recorder'
        c['exception_contract']['authority'] = 'authorization-recorder'
        self.assertEqual(codes(c, inv=inv), {'ADMISSION_AUTHORITY'})

    def test_ids_keys_links_and_paths(self):
        cases = [(lambda c: c['controls'].append(dict(c['controls'][0])), 'ID_DUPLICATE'),
                 (lambda c: c['deferred_controls'][0].update(id='EXEC-01'), 'ID_DUPLICATE'),
                 (lambda c: c['controls'][0].update(id='exec-1'), 'ID_INVALID'),
                 (lambda c: c['controls'][0].update(owner='me'), 'SCHEMA'),
                 (lambda c: c.update(extra=1), 'SCHEMA'),
                 (lambda c: c['controls'][0]['enforcement'][0].update(where='host'), 'SCHEMA'),
                 (lambda c: c['controls'][0].update(sources=[]), 'SCHEMA'),
                 (lambda c: c['controls'][0]['sources'].append(
                     'AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html'
                     '#nowhere'), 'ANCHOR_MISSING'),
                 (lambda c: c['controls'][0]['enforcement'][0].update(
                     mechanism='reads Z:\\scratch\\x'), 'MACHINE_PATH'),
                 (lambda c: c['deferred_controls'][0].update(leaves=[]), 'DANGLING_REF'),
                 (lambda c: c['deferred_controls'][0].update(reason=''), 'SCHEMA'),
                 (lambda c: c['oscal'].update(claim='OSCAL 1.1 catalog'), 'SCHEMA'),
                 (lambda c: c['oscal']['fields'].pop('purpose'), 'SCHEMA'),
                 (lambda c: c['oscal']['fields'].update(severity='x'), 'SCHEMA'),
                 (lambda c: c.update(readme='policy/no-such-page.md'), 'LINK_MISSING'),
                 (lambda c: c['controls'][0]['sources'].append('../outside.md'), 'LINK_INVALID'),
                 (lambda c: c.update(controls=[]), 'SCHEMA'),
                 (lambda c: c.update(schema='v0'), 'SCHEMA')]
        for n, (fn, code) in enumerate(cases):
            with self.subTest(case=n, code=code):
                c = fresh()
                fn(c)
                self.expect(code, c)

    def test_readme(self):
        cases = [(README.replace('`REL-01`', 'REL-01'), 'README_MISSING'),
                 (README.replace('| `AUTH-01` | effect | `privileged-executor`',
                                 '| `AUTH-01` | effect | `owner`'), 'README_STALE'),
                 (README.replace(ccc.GENERATED_BEGIN, ''), 'README_STALE'),
                 (ccc.GENERATED_BEGIN + ccc.render(fresh()) + '.', 'README_STALE'),  # no end marker
                 (README + '\nSee Z:\\scratch\\x.\n', 'MACHINE_PATH')]
        for n, (text, code) in enumerate(cases):
            with self.subTest(case=n, code=code):
                self.assertNotEqual(text, README)
                self.expect(code, fresh(), readme=text)

    def test_malformed_values_fail_by_name_never_crash(self):
        values = (None, 5, 'x', [None], {'a': 1})
        targets = [lambda c: c, lambda c: control(c, 'AUTH-01'),
                   lambda c: control(c, 'AUTH-01')['enforcement'][0],
                   lambda c: c['profiles'][1], lambda c: c['admission'],
                   lambda c: c['deferred_controls'][0]]
        for n, target in enumerate(targets):
            for key in list(target(fresh())):
                for value in values:
                    c = fresh()
                    target(c)[key] = value
                    try:
                        problems(c)
                    except Exception as exc:  # a crash where a named FAIL belongs
                        self.fail(f'target {n} key {key!r} = {value!r}: {exc!r}')
        c = fresh()
        c['profiles'].append(5)
        c['controls'][0]['enforcement'].append(None)
        c['deferred_controls'].append('x')
        self.expect('PROFILE_INVALID', c, readme=README)  # the render skips them, never crashes
        for bad in (None, [], 'x'):
            self.assertEqual({p.code for p in problems(bad)}, {'SCHEMA'})


if __name__ == '__main__':
    unittest.main()
