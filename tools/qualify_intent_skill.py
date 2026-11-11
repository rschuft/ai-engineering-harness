"""Run the intent-normalization Skill's behavioural qualification on a model (plan leaf P-01.2).

The corpus (``tools/tests/fixtures/intent_qualification/corpus``) holds requests with
stable message references (``conversation:qual-NN/message-M``), grouped into turns, and
a pre-written expected outcome per item. For one item and turn, this runner:

1. builds a system prompt from the Skill's text (``SKILL.md``, its record grammar and
   its proposal template, verbatim) and a user prompt from the item's messages, and for
   a later turn the proposal of the previous turn;
2. runs a model command from a JSON command template, with the user prompt on stdin
   (or in place of a ``{prompt}`` argument) and the working directory set to an empty
   scratch directory;
3. saves the raw output, extracts ``proposal.md`` from it, checks it with
   ``tools/check_intent_record.py`` against the item's message texts, and appends one
   entry to a JSON Lines run ledger.

It never runs more invocations than ``--max-invocations`` (counted in the ledger,
failures included). It scores form only; whether the record is faithful to the request
is a review against the item's ``expected.md``.

Command template (JSON): ``{"argv": [...], "parser": "claude-stream-json" | "claude-json"
| "text", "drop_env_prefixes": [...], "drop_env": [...], "timeout_s": 900}``. An argv
element that is exactly ``{system_prompt}`` or ``{prompt}`` is replaced by that text;
nothing else is substituted. The first element is resolved on PATH.

Usage (from the repository root):
    python -I -B tools/qualify_intent_skill.py system-prompt
    python -I -B tools/qualify_intent_skill.py prompt --item qual-01 --turn 1
    python -I -B tools/qualify_intent_skill.py run --item qual-01 --turn 1 \\
        --command TEMPLATE.json --cwd EMPTY_DIR --out OUT_DIR --raw-dir RAW_DIR --ledger LEDGER.jsonl
    python -I -B tools/qualify_intent_skill.py check --item qual-01 --turn 1 PROPOSAL

Exit status: 0 done (``run``: the invocation completed, whatever the checker found;
``check``: PASS), 1 ``check`` FAIL or a failed invocation, 2 could not run.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _no_window():
    """integrations/platform/no_window.py, the shared no-window helper, loaded by path once per process:
    ``_no_window().no_window_flags()`` is CREATE_NO_WINDOW only where this process has no console."""
    module = sys.modules.get('aieh_no_window')
    if module is None:
        spec = importlib.util.spec_from_file_location(
            'aieh_no_window', REPO / 'integrations' / 'platform' / 'no_window.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['aieh_no_window'] = module
    return module
DEFAULT_CORPUS = REPO / 'tools' / 'tests' / 'fixtures' / 'intent_qualification' / 'corpus'
DEFAULT_SKILL = REPO / 'catalog' / 'skills' / 'intent-normalization'
SKILL_FILES = ('SKILL.md', 'references/intent-record.md', 'assets/proposal-template.md')
DEFAULT_AGENT_ID = 'intent-qualification'
DEFAULT_MAX_INVOCATIONS = 25

_spec = importlib.util.spec_from_file_location('check_intent_record',
                                               REPO / 'tools' / 'check_intent_record.py')
cir = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cir)


class RunnerError(Exception):
    """A condition that stops the runner before or instead of an invocation."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def skill_version(skill_dir):
    match = re.search(r'^\s*version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?\s*$',
                      (Path(skill_dir) / 'SKILL.md').read_text(encoding='utf-8'), re.M)
    return match.group(1) if match else None


def system_prompt(skill_dir=DEFAULT_SKILL):
    """The Skill as text: its files verbatim, each between named delimiter lines."""
    parts = ['You follow the Agent Skill "intent-normalization", given below in full: '
             'SKILL.md, then the files it links to. Relative links in SKILL.md refer to these '
             'files. Each file is delimited by a line "=== BEGIN FILE <path> ===" and a line '
             '"=== END FILE <path> ===".\n']
    for name in SKILL_FILES:
        text = (Path(skill_dir) / name).read_text(encoding='utf-8')
        if not text.endswith('\n'):
            text += '\n'
        parts.append(f'\n=== BEGIN FILE {name} ===\n{text}=== END FILE {name} ===\n')
    return ''.join(parts)


def load_item(corpus, item_id):
    path = Path(corpus) / item_id / 'item.json'
    if not path.is_file():
        raise RunnerError(f'no corpus item {item_id} ({path})')
    item = json.loads(path.read_text(encoding='utf-8'))
    if item.get('id') != item_id:
        raise RunnerError(f'{path}: id is {item.get("id")!r}, expected {item_id!r}')
    item['_dir'] = path.parent
    return item


def _turn(item, number):
    for turn in item['turns']:
        if turn['turn'] == number:
            return turn
    raise RunnerError(f'{item["id"]} has no turn {number}')


def message_text(item, message):
    data = (item['_dir'] / message['file']).read_bytes()
    return data.decode('utf-8')


def _message_block(item, message):
    if message.get('ref'):
        label = f'ref={message["ref"]}'
    else:
        label = f'ref=none ({message.get("note", "no durable reference was given")})'
    text = message_text(item, message)
    if not text.endswith('\n'):
        text += '\n'
    return f'<<<BEGIN MESSAGE {label} from={message["from"]}>>>\n{text}<<<END MESSAGE>>>\n'


CONVERSATION_RULES = (
    'Each message is delimited by a line "<<<BEGIN MESSAGE ref=... from=...>>>", which names '
    "the message's durable reference and its sender, and a line \"<<<END MESSAGE>>>\". The "
    'message text is exactly the characters between the line break that ends the BEGIN line '
    'and the line break that precedes the END line.\n')


def compose_prompt(item, turn_number, previous=None, agent_id=DEFAULT_AGENT_ID):
    """The user prompt for one turn. ``previous`` is the earlier proposal (str) for turn > 1."""
    turn = _turn(item, turn_number)
    reply = (f'- Use `agent:{agent_id}` as normalized_by.\n'
             '- Reply with the complete content of proposal.md and nothing else: no '
             'introduction, no closing remarks, and no code fence around the whole file.\n')
    if turn_number == 1:
        blocks = ''.join(_message_block(item, m) for m in turn['messages'])
        return ('Normalize the request in the conversation below into proposal.md, following '
                'the intent-normalization Skill.\n\n' + reply + '\n' + CONVERSATION_RULES
                + '\n' + blocks)
    if previous is None:
        raise RunnerError(f'turn {turn_number} needs the proposal of the previous turn')
    if not previous.endswith('\n'):
        previous += '\n'
    earlier = ''.join(_message_block(item, m) for t in item['turns']
                      if t['turn'] < turn_number for m in t['messages'])
    new = ''.join(_message_block(item, m) for m in turn['messages'])
    return ('proposal.md was written earlier from the conversation below. A new message has '
            'arrived since. Update proposal.md for the new message, following the '
            'intent-normalization Skill.\n\n' + reply + '\n' + CONVERSATION_RULES
            + '\nEarlier messages:\n\n' + earlier
            + '\nproposal.md as written earlier, between the lines "<<<BEGIN FILE '
            'proposal.md>>>" and "<<<END FILE proposal.md>>>":\n\n'
            '<<<BEGIN FILE proposal.md>>>\n' + previous + '<<<END FILE proposal.md>>>\n'
            + '\nNew message:\n\n' + new)


def sources_for(item, turn_number, proposal):
    """{reference: bytes} for every message up to the turn; an unreferenced message is
    mapped to each ``missing:`` quote source the proposal uses."""
    sources, unreferenced = {}, []
    for turn in item['turns']:
        if turn['turn'] > turn_number:
            continue
        for message in turn['messages']:
            data = (item['_dir'] / message['file']).read_bytes()
            if message.get('ref'):
                sources[message['ref']] = data
            else:
                unreferenced.append(data)
    if len(unreferenced) == 1:
        for line in proposal.decode('utf-8', 'replace').splitlines():
            match = re.match(r'^- source:\s*(missing:\S+)\s*$', line)
            if match:
                sources.setdefault(match.group(1), unreferenced[0])
    return sources


def check_proposal(item, turn_number, proposal):
    problems = cir.check(proposal, sources_for(item, turn_number, proposal))
    return ('FAIL' if problems else 'PASS'), problems


FENCE_LINE = re.compile(r'^(`{3,}|~{3,})(markdown|md)?\s*$')


def extract_proposal(result):
    """Return (proposal text, how it was extracted) from a model's final reply."""
    if result is None:
        return None, 'no-result'
    lines = result.strip('\n').split('\n')
    if len(lines) >= 2:
        first, last = FENCE_LINE.match(lines[0]), lines[-1].strip()
        if first and last == first.group(1):
            return '\n'.join(lines[1:-1]) + '\n', 'unwrapped-outer-fence'
    return result, 'verbatim'


def parse_output(parser, stdout):
    """Pick the final reply and run metadata out of the command's stdout."""
    meta = {'result': None}
    text = stdout.decode('utf-8', 'replace')
    if parser == 'text':
        meta['result'] = text
        return meta
    if parser == 'claude-json':
        objects = [json.loads(text)] if text.strip() else []
    elif parser == 'claude-stream-json':
        objects = []
        for line in text.splitlines():
            if line.strip():
                try:
                    objects.append(json.loads(line))
                except ValueError:
                    meta.setdefault('non_json_lines', 0)
                    meta['non_json_lines'] += 1
    else:
        raise RunnerError(f'unknown parser {parser!r}')
    for obj in objects:
        if obj.get('type') == 'system' and obj.get('subtype') == 'init':
            for key in ('tools', 'mcp_servers', 'skills', 'slash_commands', 'agents',
                        'plugins', 'model', 'permissionMode', 'claude_code_version',
                        'apiKeySource'):
                if key in obj:
                    meta[f'init_{key}'] = obj[key]
        if obj.get('type') == 'result':
            meta['result'] = obj.get('result')
            meta['is_error'] = obj.get('is_error')
            meta['subtype'] = obj.get('subtype')
            meta['num_turns'] = obj.get('num_turns')
            meta['cost_usd'] = obj.get('total_cost_usd')
            meta['permission_denials'] = obj.get('permission_denials')
            meta['stop_reason'] = obj.get('stop_reason')
            usage = obj.get('usage') or {}
            for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens',
                        'cache_read_input_tokens'):
                if key in usage:
                    meta[key] = usage[key]
            thinking = (usage.get('output_tokens_details') or {}).get('thinking_tokens')
            if thinking is not None:
                meta['thinking_tokens'] = thinking
            meta['models'] = sorted((obj.get('modelUsage') or {}).keys())
    return meta


def read_ledger(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def _drop_env(template):
    prefixes = tuple(p.upper() for p in template.get('drop_env_prefixes', []))
    names = {n.upper() for n in template.get('drop_env', [])}
    env = {k: v for k, v in os.environ.items()
           if not (k.upper().startswith(prefixes) if prefixes else False)
           and k.upper() not in names}
    return env, sorted(set(os.environ) - set(env))


def run_turn(item, turn_number, template, cwd, out_dir, raw_dir, ledger, *,
             skill_dir=DEFAULT_SKILL, agent_id=DEFAULT_AGENT_ID, previous=None,
             max_invocations=DEFAULT_MAX_INVOCATIONS):
    entries = read_ledger(ledger)
    if len(entries) >= max_invocations:
        raise RunnerError(f'the ledger already records {len(entries)} invocation(s); the cap '
                          f'is {max_invocations}')
    cwd = Path(cwd)
    if not cwd.is_dir() or any(cwd.iterdir()):
        raise RunnerError(f'the working directory must be an existing empty directory: {cwd}')
    out_dir, raw_dir = Path(out_dir), Path(raw_dir)
    if turn_number > 1 and previous is None:
        prev_path = out_dir / item['id'] / f'turn-{turn_number - 1}.proposal.md'
        if not prev_path.is_file():
            raise RunnerError(f'turn {turn_number} needs {prev_path}')
        previous = prev_path.read_text(encoding='utf-8')
    system = system_prompt(skill_dir)
    prompt = compose_prompt(item, turn_number, previous, agent_id)
    argv, stdin, redacted = [], prompt.encode('utf-8'), []
    for index, element in enumerate(template['argv']):
        if element == '{system_prompt}':
            argv.append(system)
            redacted.append(f'<system prompt, sha256 {sha256(system.encode("utf-8"))}>')
        elif element == '{prompt}':
            argv.append(prompt)
            stdin = b''
            redacted.append(f'<prompt, sha256 {sha256(prompt.encode("utf-8"))}>')
        elif index == 0:
            resolved = shutil.which(element)
            if resolved is None:
                raise RunnerError(f'command not found on PATH: {element}')
            argv.append(resolved)
            redacted.append(Path(element).name)
        else:
            argv.append(element)
            redacted.append(element)
    env, dropped = _drop_env(template)
    number = len(entries) + 1
    tag = f'inv-{number:02d}-{item["id"]}-t{turn_number}'
    raw_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    clock = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, env=env,
                              timeout=template.get('timeout_s', 900), creationflags=_no_window().no_window_flags())
        exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code, stdout, stderr = 'timeout', exc.stdout or b'', exc.stderr or b''
    duration = round(time.monotonic() - clock, 1)
    (raw_dir / f'{tag}.out').write_bytes(stdout)
    (raw_dir / f'{tag}.err').write_bytes(stderr)
    meta = parse_output(template.get('parser', 'text'), stdout)
    proposal_text, extraction = extract_proposal(meta.pop('result'))
    entry = {
        'n': number, 'item': item['id'], 'turn': turn_number, 'started_utc': started,
        'duration_s': duration, 'argv': redacted, 'env_dropped': dropped,
        'skill_version': skill_version(skill_dir),
        'system_prompt_sha256': sha256(system.encode('utf-8')),
        'prompt_sha256': sha256(prompt.encode('utf-8')),
        'expected_sha256': sha256((item['_dir'] / 'expected.md').read_bytes())
        if (item['_dir'] / 'expected.md').is_file() else None,
        'exit_code': exit_code, 'stdout_sha256': sha256(stdout), 'stdout_bytes': len(stdout),
        'stderr_bytes': len(stderr), 'extraction': extraction,
    }
    entry.update(meta)
    entry['cwd_empty_after'] = not any(cwd.iterdir())
    if proposal_text is not None:
        data = proposal_text.encode('utf-8')
        target = out_dir / item['id'] / f'turn-{turn_number}.proposal.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        verdict, problems = check_proposal(item, turn_number, data)
        entry.update({'proposal': f'{item["id"]}/turn-{turn_number}.proposal.md',
                      'proposal_sha256': sha256(data), 'checker': verdict,
                      'checker_codes': sorted({p.code for p in problems}),
                      'checker_problems': [str(p) for p in problems]})
    else:
        entry.update({'proposal': None, 'checker': None})
    with Path(ledger).open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + '\n')
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--corpus', type=Path, default=DEFAULT_CORPUS)
    parser.add_argument('--skill', type=Path, default=DEFAULT_SKILL)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('system-prompt', help='print the system prompt')
    p_prompt = sub.add_parser('prompt', help='print the user prompt of an item and turn')
    p_run = sub.add_parser('run', help='run one item and turn through the model command')
    p_check = sub.add_parser('check', help="check a proposal against an item's messages")
    for p in (p_prompt, p_run, p_check):
        p.add_argument('--item', required=True)
        p.add_argument('--turn', type=int, default=1)
    for p in (p_prompt, p_run):
        p.add_argument('--agent-id', default=DEFAULT_AGENT_ID)
        p.add_argument('--previous', type=Path, help='the earlier proposal (turn > 1)')
    p_run.add_argument('--command', type=Path, required=True, help='JSON command template')
    p_run.add_argument('--cwd', type=Path, required=True, help='an existing empty directory')
    p_run.add_argument('--out', type=Path, required=True)
    p_run.add_argument('--raw-dir', type=Path, required=True)
    p_run.add_argument('--ledger', type=Path, required=True)
    p_run.add_argument('--max-invocations', type=int, default=DEFAULT_MAX_INVOCATIONS)
    p_check.add_argument('proposal', type=Path)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if args.command == 'system-prompt':
            sys.stdout.write(system_prompt(args.skill))
            return 0
        item = load_item(args.corpus, args.item)
        if args.command == 'check':
            verdict, problems = check_proposal(item, args.turn, args.proposal.read_bytes())
            print(f'{verdict} {args.proposal}')
            for problem in problems:
                print(f'  {problem}')
            return 0 if verdict == 'PASS' else 1
        previous = args.previous.read_text(encoding='utf-8') if args.previous else None
        if args.command == 'prompt':
            sys.stdout.write(compose_prompt(item, args.turn, previous, args.agent_id))
            return 0
        template = json.loads(args.command.read_text(encoding='utf-8'))
        entry = run_turn(item, args.turn, template, args.cwd, args.out, args.raw_dir,
                         args.ledger, skill_dir=args.skill, agent_id=args.agent_id,
                         previous=previous, max_invocations=args.max_invocations)
    except (RunnerError, OSError, ValueError) as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2
    print(json.dumps({k: entry.get(k) for k in ('n', 'item', 'turn', 'exit_code', 'models',
                                                 'cost_usd', 'extraction', 'checker',
                                                 'checker_codes')}, ensure_ascii=False))
    return 0 if entry['exit_code'] == 0 and entry.get('proposal') else 1


if __name__ == '__main__':
    sys.exit(main())
