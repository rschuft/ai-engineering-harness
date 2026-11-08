"""Tests for tools/check_intent_record.py and the catalog it checks (plan leaf P-01.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The fixture under fixtures/intent_record/ is builder-produced (see its README): the
checker must pass it, and must fail each mutation of it that breaks an invariant.
Mutations are made in memory or in a temporary directory; the checkout is only read.
"""
from pathlib import Path
import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / 'tools' / 'check_intent_record.py'
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'intent_record'
SOURCE_REF = 'conversation:thread-17/message-4'
SCHEMA_DIR = REPO / 'catalog' / 'openspec' / 'schemas' / 'intent-driven'
SKILL_DIR = REPO / 'catalog' / 'skills' / 'intent-normalization'

_spec = importlib.util.spec_from_file_location('check_intent_record', CHECKER)
cir = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cir)

PROPOSAL = (FIXTURES / 'proposal.md').read_bytes()
REQUEST = (FIXTURES / 'request.txt').read_bytes()


def codes(proposal, sources=None):
    problems = cir.check(proposal, {SOURCE_REF: REQUEST} if sources is None else sources)
    return sorted({p.code for p in problems}), problems


def edit(old, new, data=PROPOSAL):
    old, new = old.encode('utf-8'), new.encode('utf-8')
    assert data.count(old) == 1, f'fixture edit is ambiguous or stale: {old!r}'
    return data.replace(old, new)


def run_cli(*args):
    return subprocess.run([sys.executable, '-I', '-B', str(CHECKER), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8')


M1 = '''#### M1
- statement: Raise the gateway timeout to 10 minutes.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1
'''


class FixturePasses(unittest.TestCase):
    category = 'contract'

    def test_fixture_passes(self):
        found, problems = codes(PROPOSAL)
        self.assertEqual(problems, [])

    def test_quote_is_the_whole_request_byte_for_byte(self):
        record, _ = cir._Parser(PROPOSAL).parse()
        quote = record.items['Q1'].quote
        self.assertEqual(quote + b'\n', REQUEST)
        for marker in ('’'.encode(), '—'.encode(), b'`invoices`', b'be  fast'):
            self.assertIn(marker, quote)

    def test_owner_methods_are_hypotheses(self):
        record, _ = cir._Parser(PROPOSAL).parse()
        methods = record.sections['Proposed Methods']
        self.assertEqual([m.id for m in methods], ['M1', 'M2'])
        for method in methods:
            self.assertEqual(method.fields['attributed_to'], 'owner')
            self.assertEqual(method.fields['claim_type'], 'hypothesis')
            self.assertNotIn('acceptance', method.fields)
            self.assertEqual(record.items[method.fields['hypothesis']].section, 'Hypotheses')
        self.assertEqual(record.sections['Binding Constraints'], [])
        self.assertEqual(len(record.sections['Open Clarifications']), 3)

    def test_crlf_copies_still_pass(self):
        crlf = lambda data: data.replace(b'\n', b'\r\n')
        self.assertEqual(cir.check(crlf(PROPOSAL), {SOURCE_REF: crlf(REQUEST)}), [])

    def test_cli_pass(self):
        result = run_cli(FIXTURES / 'proposal.md', '--source',
                         f'{SOURCE_REF}={FIXTURES / "request.txt"}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith('PASS '), result.stdout)
        self.assertIn('(1 Q, 1 O, 0 C, 2 M, 2 H, 2 AC, 3 CL)', result.stdout)


class QuoteMutations(unittest.TestCase):
    def assertFailsWith(self, proposal, expected, sources=None):
        found, problems = codes(proposal, sources)
        self.assertIn(expected, found, [str(p) for p in problems])

    def test_straightened_apostrophe(self):
        found, problems = codes(edit('that’ll fix it', "that'll fix it"))
        self.assertEqual(found, ['quote-not-in-source'], [str(p) for p in problems])

    def test_collapsed_double_space(self):
        self.assertFailsWith(edit('needs to be  fast', 'needs to be fast'),
                             'quote-not-in-source')

    def test_corrected_word(self):
        self.assertFailsWith(edit('Just bump the gateway', 'Just raise the gateway'),
                             'quote-not-in-source')

    def test_source_differs_from_quote(self):
        self.assertFailsWith(PROPOSAL, 'quote-not-in-source',
                             {SOURCE_REF: REQUEST.replace(b'10 minutes', b'ten minutes')})

    def test_a_shorter_span_passes(self):
        # A quote may be a part of the source, as long as it is byte-identical.
        data = edit(' It has to work for the big accounts too, and it needs to be  fast.\n```',
                    '\n```')
        self.assertEqual(codes(data)[1], [])

    def test_source_text_not_given(self):
        self.assertFailsWith(PROPOSAL, 'source-unavailable', {})

    def test_fence_not_longer_than_backtick_run(self):
        source = b'Please run ``` before the export.'
        quote_start = PROPOSAL.index(b'```text\n') + len(b'```text\n')
        quote_end = PROPOSAL.index(b'\n```\n', quote_start)
        bad = PROPOSAL[:quote_start] + source + PROPOSAL[quote_end:]
        self.assertFailsWith(bad, 'quote-fence', {SOURCE_REF: source})
        good = bad.replace(b'```text\n', b'````text\n', 1).replace(
            source + b'\n```\n', source + b'\n````\n', 1)
        self.assertEqual(codes(good, {SOURCE_REF: source})[1], [])


class MethodMutations(unittest.TestCase):
    def assertFailsWith(self, proposal, *expected):
        found, problems = codes(proposal)
        for code in expected:
            self.assertIn(code, found, [str(p) for p in problems])

    def test_owner_method_promoted_to_constraint_without_acceptance(self):
        promoted = M1.replace('claim_type: hypothesis', 'claim_type: constraint').replace(
            'authority: proposed', 'authority: accepted')
        found, problems = codes(edit(M1, promoted))
        self.assertEqual(found, ['missing-acceptance', 'owner-method-not-hypothesis'],
                         [str(p) for p in problems])

    def test_owner_method_reclassified_but_left_proposed(self):
        self.assertFailsWith(edit(M1, M1.replace('claim_type: hypothesis',
                                                 'claim_type: constraint')),
                             'owner-method-not-hypothesis', 'missing-acceptance',
                             'bad-authority')

    def test_owner_method_copied_into_binding_constraints_without_acceptance(self):
        constraint = ('#### C1\n- statement: Raise the gateway timeout to 10 minutes.\n'
                      '- claim_type: constraint\n- attributed_to: owner\n- source: M1\n'
                      '- authority: accepted\n')
        data = edit('### Binding Constraints\n\nNone.\n',
                    f'### Binding Constraints\n\n{constraint}')
        self.assertFailsWith(data, 'missing-field', 'missing-acceptance')

    def test_request_cannot_accept_its_own_method(self):
        promoted = M1.replace('claim_type: hypothesis', 'claim_type: constraint').replace(
            'authority: proposed', f'authority: accepted\n- acceptance: {SOURCE_REF}')
        self.assertFailsWith(edit(M1, promoted), 'acceptance-not-separate')

    def test_promotion_with_a_separate_acceptance_passes(self):
        # Positive control: a recorded, separate acceptance is how a method becomes binding.
        acceptance = 'conversation:thread-17/message-9'
        promoted = M1.replace('claim_type: hypothesis', 'claim_type: constraint').replace(
            'authority: proposed', f'authority: accepted\n- acceptance: {acceptance}')
        constraint = ('#### C1\n- statement: Raise the gateway timeout to 10 minutes.\n'
                      '- claim_type: constraint\n- attributed_to: owner\n- source: M1\n'
                      f'- authority: accepted\n- acceptance: {acceptance}\n')
        data = edit(M1, promoted)
        data = edit('### Binding Constraints\n\nNone.\n',
                    f'### Binding Constraints\n\n{constraint}', data)
        self.assertEqual(codes(data)[1], [])

    def test_owner_method_reattributed_to_an_agent(self):
        self.assertFailsWith(edit(M1, M1.replace('attributed_to: owner',
                                                 'attributed_to: agent:normalizer')),
                             'method-attribution')

    def test_attribution_outside_the_vocabulary(self):
        self.assertFailsWith(edit(M1, M1.replace('attributed_to: owner',
                                                 'attributed_to: Owner')),
                             'bad-attribution')

    def test_method_without_its_hypothesis_link(self):
        self.assertFailsWith(edit(M1, M1.replace('- hypothesis: H1\n', '')), 'missing-field')

    def test_hypothesis_link_to_a_missing_item(self):
        self.assertFailsWith(edit(M1, M1.replace('hypothesis: H1', 'hypothesis: H9')),
                             'unknown-reference')

    def test_hypothesis_cannot_be_accepted(self):
        self.assertFailsWith(edit('- source: M1, O1\n- authority: proposed',
                                  '- source: M1, O1\n- authority: accepted\n'
                                  '- acceptance: decision:0099'), 'bad-authority')


class StructureMutations(unittest.TestCase):
    category = 'contract'

    def assertFailsWith(self, proposal, *expected):
        found, problems = codes(proposal)
        for code in expected:
            self.assertIn(code, found, [str(p) for p in problems])

    def test_missing_attribution_field(self):
        found, problems = codes(edit('- attributed_to: owner\n- source: Q1\n- authority: proposed'
                                     '\n\n### Binding', '- source: Q1\n- authority: proposed'
                                     '\n\n### Binding'))
        self.assertEqual([str(p) for p in problems],
                         ['missing-field O1: "attributed_to" is required'])

    def test_missing_quote_source(self):
        self.assertFailsWith(edit(f'- source: {SOURCE_REF}\n', ''), 'missing-field')

    def test_missing_quote_block(self):
        start = PROPOSAL.index(b'```text\n')
        end = PROPOSAL.index(b'\n```\n', start) + len(b'\n```\n')
        self.assertFailsWith(PROPOSAL[:start] + PROPOSAL[end:], 'missing-field')

    def test_missing_section(self):
        start = PROPOSAL.index(b'### Open Clarifications')
        end = PROPOSAL.index(b'## Why')
        self.assertFailsWith(PROPOSAL[:start] + PROPOSAL[end:], 'missing-section')

    def test_empty_objective(self):
        start = PROPOSAL.index(b'#### O1')
        end = PROPOSAL.index(b'### Binding Constraints')
        self.assertFailsWith(PROPOSAL[:start] + PROPOSAL[end:], 'empty-section')
        self.assertFailsWith(PROPOSAL[:start] + b'None.\n\n' + PROPOSAL[end:], 'missing-item')

    def test_empty_section_without_none(self):
        self.assertFailsWith(edit('### Binding Constraints\n\nNone.\n',
                                  '### Binding Constraints\n'), 'empty-section')

    def test_missing_openspec_heading(self):
        self.assertFailsWith(edit('## Why\n', '## Motivation\n'), 'missing-section')

    def test_missing_record(self):
        self.assertFailsWith(edit('## Intent Record\n', '## Intent\n'), 'missing-section')

    def test_missing_record_format(self):
        self.assertFailsWith(edit('- record_format: intent-record/v1\n', ''), 'missing-field')

    def test_wrong_record_format(self):
        self.assertFailsWith(edit('intent-record/v1', 'intent-record/v2'), 'record-format')

    def test_misspelt_field(self):
        self.assertFailsWith(edit('- consequence: It bounds', '- consquence: It bounds'),
                             'unknown-field', 'missing-field')

    def test_wrong_claim_type(self):
        self.assertFailsWith(PROPOSAL.replace(b'- claim_type: unknown',
                                              b'- claim_type: requirement', 1), 'bad-claim-type')

    def test_unknown_reference(self):
        self.assertFailsWith(edit('- source: Q1, O1, CL2', '- source: Q1, O1, CL9'),
                             'unknown-reference')

    def test_resolved_clarification_needs_resolution(self):
        self.assertFailsWith(edit('- blocks: AC2\n- status: open', '- blocks: AC2\n- status: resolved'),
                             'missing-field')

    def test_stray_prose_line(self):
        self.assertFailsWith(edit('### Hypotheses\n', '### Hypotheses\n\nSome notes.\n'),
                             'malformed-line')

    def test_unfilled_template_fails(self):
        template = (SCHEMA_DIR / 'templates' / 'proposal.md').read_bytes()
        found, _ = codes(template, {})
        self.assertIn('bad-attribution', found)
        self.assertIn('bad-reference', found)

    def test_cli_fail_and_error_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'proposal.md'
            bad.write_bytes(edit('that’ll', "that'll"))
            result = run_cli(bad, '--source', f'{SOURCE_REF}={FIXTURES / "request.txt"}')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('quote-not-in-source Q1', result.stdout)
            missing = run_cli(Path(tmp) / 'absent.md')
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)


def frontmatter(text):
    """The SKILL.md frontmatter: top-level scalars and one level of nested mapping."""
    lines = text.split('\n')
    assert lines[0] == '---'
    end = lines.index('---', 1)
    data, parent = {}, None
    for line in lines[1:end]:
        if line.startswith('  '):
            key, _, value = line.strip().partition(':')
            data[parent][key] = value.strip()
        else:
            key, _, value = line.partition(':')
            parent = key
            data[key] = value.strip() or {}
    return data


class Catalog(unittest.TestCase):
    category = 'contract'

    def test_skill_frontmatter_follows_agent_skills_spec(self):
        # https://agentskills.io/specification: name 1-64 chars of a-z, 0-9 and single
        # inner hyphens, equal to the directory name; description 1-1024 characters;
        # metadata maps string keys to string values.
        meta = frontmatter((SKILL_DIR / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertRegex(meta['name'], r'^[a-z0-9]+(-[a-z0-9]+)*$')
        self.assertLessEqual(len(meta['name']), 64)
        self.assertEqual(meta['name'], SKILL_DIR.name)
        self.assertTrue(1 <= len(meta['description']) <= 1024)
        self.assertEqual(set(meta) - {'name', 'description', 'license', 'compatibility',
                                      'metadata', 'allowed-tools'}, set())
        for value in meta['metadata'].values():
            self.assertRegex(value, r'^"[^"]*"$', 'metadata values are quoted strings')
        version = meta['metadata']['version'].strip('"')
        self.assertRegex(version, r'^[0-9]+\.[0-9]+\.[0-9]+$')
        self.assertEqual(meta['metadata']['record-format'], f'"{cir.RECORD_FORMAT}"')
        changelog = (SKILL_DIR / 'CHANGELOG.md').read_text(encoding='utf-8')
        self.assertRegex(changelog, rf'(?m)^## {re.escape(version)} ')
        body = (SKILL_DIR / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn(f'skill: intent-normalization@{version}', body)
        self.assertLess(body.count('\n'), 500)

    def test_skill_template_is_the_schema_template(self):
        self.assertEqual((SKILL_DIR / 'assets' / 'proposal-template.md').read_bytes(),
                         (SCHEMA_DIR / 'templates' / 'proposal.md').read_bytes())

    def test_skill_references_resolve(self):
        body = (SKILL_DIR / 'SKILL.md').read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)#]+)\)', body):
            self.assertTrue((SKILL_DIR / target).is_file(), target)

    def test_schema_artifacts_and_apply(self):
        text = (SCHEMA_DIR / 'schema.yaml').read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^name: intent-driven$')
        self.assertRegex(text, r'(?m)^version: 1$')
        self.assertEqual(re.findall(r'(?m)^  - id: (\S+)$', text), ['proposal', 'specs', 'design'])
        for template in re.findall(r'(?m)^    template: (\S+)$', text):
            self.assertTrue((SCHEMA_DIR / 'templates' / template).is_file(), template)
        apply = text[text.index('\napply:\n'):]
        self.assertEqual(re.findall(r'(?m)^    - (\S+)$', apply), ['proposal', 'specs', 'design'])
        self.assertNotRegex(text, r'(?m)^\s*tracks:', 'apply.tracks is omitted (Backlog.md tracks)')


if __name__ == '__main__':
    unittest.main()
