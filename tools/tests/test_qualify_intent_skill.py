"""Tests for tools/qualify_intent_skill.py and the P-01.2 qualification corpus.

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The runner is exercised with a fake model command (a Python script written to a
temporary directory); no test runs a live model. The committed corpus is only read.
"""
from pathlib import Path
from unittest import mock
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / 'tools' / 'qualify_intent_skill.py'
FIXTURES = Path(__file__).resolve().parent / 'fixtures'
QUAL = FIXTURES / 'intent_qualification'
CORPUS = QUAL / 'corpus'
SKILL = REPO / 'catalog' / 'skills' / 'intent-normalization'

_spec = importlib.util.spec_from_file_location('qualify_intent_skill', RUNNER)
qis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qis)

P011_PROPOSAL = (FIXTURES / 'intent_record' / 'proposal.md').read_bytes()
P011_REQUEST = (FIXTURES / 'intent_record' / 'request.txt').read_bytes()
P011_REF = 'conversation:thread-17/message-4'

FAKE_MODEL = r'''
import json, os, sys
mode, canned, marker_dir = sys.argv[1], sys.argv[2], sys.argv[3]
system = sys.argv[4] if len(sys.argv) > 4 else ''
prompt = sys.stdin.buffer.read().decode('utf-8')
os.makedirs(marker_dir, exist_ok=True)
with open(os.path.join(marker_dir, 'calls.txt'), 'a', encoding='utf-8') as handle:
    handle.write(f'{len(system)} {len(prompt)}\n')
with open(os.path.join(marker_dir, 'last-prompt.txt'), 'w', encoding='utf-8', newline='') as h:
    h.write(prompt)
if any(name.upper().startswith('CLAUDE') for name in os.environ):
    sys.exit(7)
if mode == 'fail':
    sys.stderr.write('boom\n')
    sys.exit(3)
text = open(canned, encoding='utf-8', newline='').read()
if mode == 'fenced':
    text = '```markdown\n' + text + '```\n'
if mode == 'text':
    sys.stdout.buffer.write(text.encode('utf-8'))
    sys.exit(0)
out = sys.stdout
out.write(json.dumps({'type': 'system', 'subtype': 'init', 'tools': [], 'mcp_servers': [],
                      'skills': [], 'slash_commands': [], 'model': 'fake-model'}) + '\n')
out.write(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False,
                      'num_turns': 1, 'result': text, 'total_cost_usd': 0.0,
                      'usage': {'input_tokens': 10, 'output_tokens': 20,
                                'output_tokens_details': {'thinking_tokens': 5}},
                      'modelUsage': {'fake-model': {}}, 'permission_denials': []}) + '\n')
'''


def _between_markers(prompt, begin_prefix):
    lines = prompt.split('\n')
    start = next(i for i, line in enumerate(lines) if line.startswith(begin_prefix))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == '<<<END MESSAGE>>>')
    return '\n'.join(lines[start + 1:end])


class Prompts(unittest.TestCase):
    def test_system_prompt_carries_the_skill_files_verbatim(self):
        system = qis.system_prompt(SKILL)
        for name in qis.SKILL_FILES:
            text = (SKILL / name).read_text(encoding='utf-8')
            self.assertIn(f'=== BEGIN FILE {name} ===\n{text}=== END FILE {name} ===\n', system)

    def test_turn_one_prompt_carries_each_message_exactly(self):
        for item_dir in sorted(CORPUS.iterdir()):
            item = qis.load_item(CORPUS, item_dir.name)
            prompt = qis.compose_prompt(item, 1, agent_id='x')
            self.assertIn('agent:x', prompt)
            for message in item['turns'][0]['messages']:
                text = (item_dir / message['file']).read_bytes().decode('utf-8')
                label = (f'ref={message["ref"]} ' if message['ref'] else 'ref=none (')
                found = _between_markers(prompt, f'<<<BEGIN MESSAGE {label}')
                self.assertEqual(found + '\n', text, item_dir.name)

    def test_subtle_bytes_survive_into_the_prompt(self):
        item = qis.load_item(CORPUS, 'qual-08')
        prompt = qis.compose_prompt(item, 1)
        for marker in (' €', '\U0001F615 \n', '\tDanke!  Gilt', '„Summe“'):
            self.assertIn(marker, prompt)

    def test_later_turn_prompt_has_earlier_messages_previous_proposal_and_new_message(self):
        item = qis.load_item(CORPUS, 'qual-01')
        prompt = qis.compose_prompt(item, 2, previous='PREVIOUS PROPOSAL')
        first = prompt.index('ref=conversation:qual-01/message-1')
        previous = prompt.index('<<<BEGIN FILE proposal.md>>>\nPREVIOUS PROPOSAL\n'
                                '<<<END FILE proposal.md>>>')
        second = prompt.index('ref=conversation:qual-01/message-2')
        self.assertLess(first, previous)
        self.assertLess(previous, second)
        with self.assertRaises(qis.RunnerError):
            qis.compose_prompt(item, 2)

    def test_unreferenced_message_maps_to_a_missing_source(self):
        item = qis.load_item(CORPUS, 'qual-13')
        self.assertIn('ref=none (relayed from a phone call', qis.compose_prompt(item, 1))
        proposal = b'- source: missing:phone-relay\n'
        sources = qis.sources_for(item, 1, proposal)
        self.assertEqual(list(sources), ['missing:phone-relay'])

    def test_extract_proposal(self):
        self.assertEqual(qis.extract_proposal('# P\n'), ('# P\n', 'verbatim'))
        self.assertEqual(qis.extract_proposal('```markdown\n# P\n```\n'),
                         ('# P\n', 'unwrapped-outer-fence'))
        self.assertEqual(qis.extract_proposal(None), (None, 'no-result'))
        inner = '# P\n\n```text\nq\n```\n'
        self.assertEqual(qis.extract_proposal(inner), (inner, 'verbatim'))


class RunWithFakeModel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.corpus = self.tmp / 'corpus'
        item_dir = self.corpus / 'qual-90'
        item_dir.mkdir(parents=True)
        (item_dir / 'message-1.txt').write_bytes(P011_REQUEST)
        (item_dir / 'message-2.txt').write_bytes(b'A follow-up.\n')
        (item_dir / 'expected.md').write_bytes(b'# qual-90 expected outcome\n')
        (item_dir / 'item.json').write_text(json.dumps({
            'id': 'qual-90', 'title': 't', 'covers': [],
            'turns': [{'turn': 1, 'messages': [{'ref': P011_REF, 'from': 'owner',
                                                'file': 'message-1.txt'}]},
                      {'turn': 2, 'messages': [{'ref': 'conversation:thread-17/message-5',
                                                'from': 'owner', 'file': 'message-2.txt'}]}]}),
            encoding='utf-8')
        self.item = qis.load_item(self.corpus, 'qual-90')
        self.fake = self.tmp / 'fake_model.py'
        self.fake.write_text(FAKE_MODEL, encoding='utf-8')
        self.canned = self.tmp / 'canned.md'
        self.canned.write_bytes(P011_PROPOSAL)
        self.marker = self.tmp / 'marker'
        self.cwd = self.tmp / 'cwd'
        self.cwd.mkdir()
        self.out, self.raw, self.ledger = self.tmp / 'out', self.tmp / 'raw', self.tmp / 'l.jsonl'

    def tearDown(self):
        self._tmp.cleanup()

    def template(self, mode='ok', parser='claude-stream-json', drop=True):
        return {'argv': [sys.executable, '-I', str(self.fake), mode, str(self.canned),
                         str(self.marker), '{system_prompt}'],
                'parser': parser, 'drop_env_prefixes': ['CLAUDE'] if drop else [],
                'timeout_s': 60}

    def run_turn(self, template, turn=1, **kwargs):
        return qis.run_turn(self.item, turn, template, self.cwd, self.out, self.raw,
                            self.ledger, **kwargs)

    def calls(self):
        path = self.marker / 'calls.txt'
        return path.read_text(encoding='utf-8').splitlines() if path.exists() else []

    @mock.patch.dict(os.environ, {'CLAUDE_FAKE_SESSION': 'x'})
    def test_stream_json_run_is_checked_and_ledgered(self):
        entry = self.run_turn(self.template())
        self.assertEqual(entry['exit_code'], 0)
        self.assertIn('CLAUDE_FAKE_SESSION', entry['env_dropped'])
        self.assertEqual(entry['checker'], 'PASS', entry.get('checker_problems'))
        self.assertEqual(entry['extraction'], 'verbatim')
        self.assertEqual(entry['init_tools'], [])
        self.assertEqual(entry['models'], ['fake-model'])
        self.assertEqual(entry['thinking_tokens'], 5)
        self.assertTrue(entry['cwd_empty_after'])
        self.assertEqual(entry['skill_version'], qis.skill_version(SKILL))
        self.assertTrue(entry['argv'][-1].startswith('<system prompt, sha256 '))
        written = self.out / 'qual-90' / 'turn-1.proposal.md'
        self.assertEqual(written.read_bytes(), P011_PROPOSAL)
        self.assertEqual(entry['proposal_sha256'], qis.sha256(P011_PROPOSAL))
        ledger = qis.read_ledger(self.ledger)
        self.assertEqual([e['n'] for e in ledger], [1])
        self.assertEqual(self.calls(), [f'{len(qis.system_prompt())} '
                                        f'{len(qis.compose_prompt(self.item, 1))}'])

    @mock.patch.dict(os.environ, {'CLAUDE_FAKE_SESSION': 'x'})
    def test_env_is_inherited_without_a_drop_rule(self):
        entry = self.run_turn(self.template(drop=False))
        self.assertEqual(entry['exit_code'], 7)

    def test_outer_fence_is_unwrapped_and_text_parser(self):
        entry = self.run_turn(self.template('fenced'))
        self.assertEqual(entry['extraction'], 'unwrapped-outer-fence')
        self.assertEqual(entry['checker'], 'PASS')
        entry = self.run_turn(self.template('text', parser='text'), turn=2)
        self.assertEqual(entry['checker'], 'PASS')
        self.assertEqual(entry['n'], 2)

    def test_second_turn_reads_the_first_turn_output(self):
        self.run_turn(self.template())
        self.run_turn(self.template(), turn=2)
        prompt = (self.marker / 'last-prompt.txt').read_text(encoding='utf-8')
        self.assertIn(P011_PROPOSAL.decode('utf-8'), prompt)
        self.assertIn('ref=conversation:thread-17/message-5', prompt)

    def test_second_turn_without_a_first_turn_output_refuses(self):
        with self.assertRaises(qis.RunnerError):
            self.run_turn(self.template(), turn=2)
        self.assertEqual(self.calls(), [])

    def test_failed_invocation_counts(self):
        entry = self.run_turn(self.template('fail'))
        self.assertEqual(entry['exit_code'], 3)
        self.assertIsNone(entry['proposal'])
        self.assertEqual(len(qis.read_ledger(self.ledger)), 1)

    def test_cap_refuses_without_running(self):
        self.run_turn(self.template(), max_invocations=1)
        with self.assertRaises(qis.RunnerError):
            self.run_turn(self.template(), max_invocations=1)
        self.assertEqual(len(self.calls()), 1)

    def test_non_empty_working_directory_refuses(self):
        (self.cwd / 'CLAUDE.md').write_text('x', encoding='utf-8')
        with self.assertRaises(qis.RunnerError):
            self.run_turn(self.template())
        self.assertEqual(self.calls(), [])

    def test_checker_failure_is_recorded(self):
        self.canned.write_bytes(P011_PROPOSAL.replace('that’ll'.encode(), b"that'll"))
        entry = self.run_turn(self.template())
        self.assertEqual(entry['checker'], 'FAIL')
        self.assertEqual(entry['checker_codes'], ['quote-not-in-source'])

    def test_cli_check(self):
        import subprocess
        proposal = self.tmp / 'p.md'
        proposal.write_bytes(P011_PROPOSAL)
        run = subprocess.run([sys.executable, '-I', '-B', str(RUNNER), '--corpus',
                              str(self.corpus), 'check', '--item', 'qual-90', str(proposal)],
                             capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(run.stdout.startswith('PASS'))


class Corpus(unittest.TestCase):
    def test_items_are_complete_and_references_stable(self):
        ids = sorted(p.name for p in CORPUS.iterdir())
        self.assertGreaterEqual(len(ids), 10)
        self.assertLessEqual(len(ids), 14)
        refs = set()
        for item_id in ids:
            self.assertRegex(item_id, r'^qual-[0-9]{2}$')
            item = qis.load_item(CORPUS, item_id)
            expected = (CORPUS / item_id / 'expected.md').read_text(encoding='utf-8')
            self.assertTrue(expected.startswith(f'# {item_id} expected outcome'))
            self.assertEqual([t['turn'] for t in item['turns']],
                             list(range(1, len(item['turns']) + 1)))
            for turn in item['turns']:
                for message in turn['messages']:
                    self.assertTrue((CORPUS / item_id / message['file']).is_file())
                    if message['ref'] is None:
                        self.assertIn('note', message)
                        continue
                    self.assertRegex(message['ref'],
                                     rf'^conversation:{item_id}/message-[0-9]+$')
                    self.assertNotIn(message['ref'], refs)
                    refs.add(message['ref'])

    def test_corpus_covers_the_required_cases(self):
        covers = set()
        for item_dir in CORPUS.iterdir():
            covers.update(qis.load_item(CORPUS, item_dir.name)['covers'])
        for case in ('ambiguous-goal', 'misleading-method', 'insistence', 'injection',
                     'separate-acceptance', 'no-method', 'non-ascii', 'whitespace',
                     'clarification-trace'):
            self.assertIn(case, covers)
        traced = [d.name for d in CORPUS.iterdir()
                  if len(qis.load_item(CORPUS, d.name)['turns']) > 1]
        self.assertGreaterEqual(len(traced), 3)


if __name__ == '__main__':
    unittest.main()
