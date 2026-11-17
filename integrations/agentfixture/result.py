"""RESULT's answer in the Agent Server fixture (plan leaf E-01.7, slice 9; the engineering manager's ruling 4 of
dispatch 24): the harness's own RESULT script run over D1's base and D1's recorded file changes.

The fixture never executes what it receives. A RESULT request is answered only when every input that determines its
answer is a pinned one, checked before anything runs:

- the command is the dispatcher's RESULT command, its script byte for byte ``integrations/dispatch/attempt_run.py``
  ``RESULT_SCRIPT`` (read from that file's source, never imported), its hex parameters decoded as data;
- the parameters other than the attempt's own (the base, its bundle and ref, the result ref, the identity, the date,
  the message and the frame) equal the production builder's constants (``CONSTANTS`` below, a test binds them to
  ``attempt_run``'s own);
- the conversation was seeded by the core's SEED (the harness's SEED script over the request's payload) and received
  its one message, and it has had no RESULT yet;
- the seeded workspace outside ``openspec/`` and ``backlog/`` holds exactly the files of D1's demo repository, by git
  blob id (``DEMO_BLOBS``: ``integrations/gitea/demo/aieh-d1-demo`` at 1e8d4a9, unchanged since; planning's PB-7: the
  run's project repository is a copy of D1's, whose base outside those two directories equals D1's base tree).

Then D1's three recorded file changes are applied to the seeded workspace (the agent's edits, replayed; read from
the Owner report D1 committed verbatim, checked by its recorded sha256), and the harness's RESULT script runs over it
in the conversation's scratch directory, with no visible window (the shared no-window helper). The script makes the
commit by decision 0024 point 4.4's rule (its base, the edited tree, the identity and date and message the command
carries: the identity is an input), bundles it, and runs the accepted design's fixed test command on an export of the
commit. Its output lines are served as the script printed them (class pinned-rule), except the test output, which is
D1's recorded one (class observation: ``D1_TEST_OUTPUT``, checked by its recorded size and sha256), served only when
the script's own test run passed: the command, the base outside the two directories and the edits are then D1's, the
inputs that determine it. The duration the run printed is not served.

The exchange delivery (the answer's ``delivered``) is not made here: it is E-01.8's seam (the I1 design's R13), so
the whole "finished with a result" path over the listener is proven at E-01.8. Standard library only.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ATTEMPT_RUN = REPO / 'integrations' / 'dispatch' / 'attempt_run.py'
D1_RECORD = REPO / 'evidence' / 'D1-run-2026-11-16.md'

# D1's Owner report, reproduced verbatim in the D1 run record section 12 (its sha256 and size there and in section 2).
REPORT_SHA256 = '4c2e6826c41f81d5b4e20b9344f07d436beb14ec6b694a377498eb893726c338'
REPORT_BYTES = 10096
# D1's test output: the run record section 2, "Tests in RESULT": 114 bytes, this sha256.
TEST_OUTPUT_SHA256 = '432e764160c5b06b41e1864e05386aaf72bcdcdfe2465d19c35fe57144567754'
TEST_OUTPUT_BYTES = 114
# The files of D1's demo repository outside openspec/ and backlog/, by git blob id (git ls-tree 1e8d4a9
# integrations/gitea/demo/aieh-d1-demo; the template is unchanged since that commit).
DEMO_BLOBS = {
    '.gitattributes': '887a183e8f1c96af9f6527fda6b04f3d2fe8df64',
    '.gitignore': '7a60b85e148f80966a550e5ab6a762a907c69ca6',
    'README.md': 'bdb89fd17456144919ad8d084d6d0d9abd9eea6c',
    'aieh_d1_demo/__init__.py': '0e03418b0f851b6d29bc0c4b9d43e8453e5c1cf1',
    'tests/test_package.py': '24c72a28d1cfa96ebbb4f1ae0777a968f24d2944',
}
PROTECTED = ('openspec', 'backlog')
# The RESULT builder's constants (integrations/dispatch/attempt_run.py build_result; a test binds them).
CONSTANTS = {'test_timeout': 300, 'output_limit': 65536, 'part': 'bundle', 'part_begin': 'AIEH-EXCHANGE-PART',
             'part_end': 'AIEH-EXCHANGE-END', 'forbidden': ['.claude', '.mcp.json'],
             'protected': ['openspec', 'backlog'], 'excluded_shown': 100}
PARAMETERS = {'base', 'base_ref', 'bundle', 'ref', 'name', 'email', 'date', 'message', 'frame', *CONSTANTS}
RESULT_TIMEOUT_MAX_S = 540
RESULT_RE = re.compile(r"printf %s '([0-9a-f]+)' \| python -c '(.*)' '/workspace/([A-Za-z0-9][A-Za-z0-9._-]*)'", re.S)
LINE_RE = re.compile(r'AIEH-RESULT (base|tree|commit|excluded|bundle|tests|test-output|done|failed)\b')


class NotAnswered(Exception):
    """The request's answer is not determined by pinned inputs: the core refuses it with the label (the reason)."""


def pinned_script(name: str, path: Path = ATTEMPT_RUN) -> str:
    """The value of the module-level string NAME in PATH's source, read as data (``ast``), never imported."""
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and [getattr(t, 'id', None) for t in node.targets] == [name]:
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise LookupError(f'{name} is not a module-level string of {path.name}')


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b'blob %d\x00' % len(data) + data, usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# D1's recorded observations: the Owner report, its diff and its test output

def report_text(path: Path = D1_RECORD) -> str:
    """D1's Owner report as the run record reproduces it (section 12), checked against its recorded sha256."""
    text = path.read_bytes().decode('utf-8').replace('\r\n', '\n')
    start = text.index('````markdown\n') + len('````markdown\n')
    report = text[start:text.index('\n````\n', start)] + '\n'
    data = report.encode('utf-8')
    if len(data) != REPORT_BYTES or hashlib.sha256(data).hexdigest() != REPORT_SHA256:
        raise ValueError('the D1 run record no longer reproduces the Owner report it recorded')
    return report


def _block(report: str, heading: str) -> str:
    """The first ```text fenced block after HEADING."""
    at = report.index(heading)
    start = report.index('```text\n', at) + len('```text\n')
    return report[start:report.index('\n```\n', start) + 1]


def d1_test_output(report: str | None = None) -> bytes:
    """D1's test output (the report's Tests section), checked against the run record's size and sha256."""
    data = _block(report or report_text(), '## Tests (not independent CI)').encode('utf-8')
    if len(data) != TEST_OUTPUT_BYTES or hashlib.sha256(data).hexdigest() != TEST_OUTPUT_SHA256:
        raise ValueError('the recorded test output is not the one D1 recorded')
    return data


def d1_changes(report: str | None = None) -> list[dict]:
    """D1's recorded file changes (the report's Diff section, difflib's unified diff, three lines of context):
    [{path, status, hunks: [(old_start, old_lines, new_lines)]}], the line lists with their newlines."""
    lines = _block(report or report_text(), '## Diff (').splitlines(keepends=True)
    changes, at = [], 0
    while at < len(lines):
        head = re.fullmatch(r'diff -- (\S+) \((modified|added)\)\n', lines[at])
        if head is None:
            raise ValueError(f'the diff\'s line {at + 1} is not a file header')
        change = {'path': head.group(1), 'status': head.group(2), 'hunks': []}
        at += 3                                   # the --- and +++ lines
        while at < len(lines) and lines[at].startswith('@@ '):
            hunk = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\n', lines[at])
            old_start, old_count = int(hunk.group(1)), int(hunk.group(2) or 1)
            new_count = int(hunk.group(4) or 1)
            at += 1
            old, new = [], []
            while at < len(lines) and (len(old) < old_count or len(new) < new_count):
                line = lines[at]
                if line.startswith(' '):
                    old.append(line[1:])
                    new.append(line[1:])
                elif line.startswith('-'):
                    old.append(line[1:])
                elif line.startswith('+'):
                    new.append(line[1:])
                else:
                    raise ValueError(f'the diff\'s line {at + 1} is not a hunk line')
                at += 1
            change['hunks'].append((old_start, old, new))
        changes.append(change)
    return changes


def apply_changes(workspace: Path, changes: list[dict]) -> None:
    """Apply CHANGES to WORKSPACE: an added file must not exist; a modified file's hunks must match it exactly."""
    for change in changes:
        target = workspace / change['path']
        if change['status'] == 'added':
            if target.exists() or len(change['hunks']) != 1:
                raise NotAnswered(f'{change["path"]}: the recorded added file cannot be added here')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(''.join(change['hunks'][0][2]).encode('utf-8'))
            continue
        if not target.is_file():
            raise NotAnswered(f'{change["path"]}: the recorded modified file is not in the base')
        current = target.read_bytes().decode('utf-8').splitlines(keepends=True)
        out, done = [], 0
        for start, old, new in change['hunks']:
            begin = start - 1 if old else start
            if current[begin:begin + len(old)] != old:
                raise NotAnswered(f'{change["path"]}: the base is not the one D1\'s change was made on')
            out += current[done:begin] + new
            done = begin + len(old)
        target.write_bytes(''.join(out + current[done:]).encode('utf-8'))


# ---------------------------------------------------------------------------
# The request's determining inputs

def parameters(body, workspace_name: str | None) -> tuple[dict, str, str]:
    """The RESULT request's (parameters, payload hex, script) when BODY is the dispatcher's RESULT command on the
    workspace WORKSPACE_NAME was seeded into; NotAnswered otherwise."""
    if not isinstance(body, dict) or set(body) != {'command', 'cwd', 'timeout'} or body['cwd'] != '/workspace' \
            or type(body['timeout']) is not int or not 0 < body['timeout'] <= RESULT_TIMEOUT_MAX_S \
            or not isinstance(body['command'], str):
        raise NotAnswered('a command that is not the harness\'s SEED or RESULT command')
    match = RESULT_RE.fullmatch(body['command'])
    if match is None or match.group(2) != pinned_script('RESULT_SCRIPT'):
        raise NotAnswered('a command that is not the harness\'s SEED or RESULT command')
    if match.group(3) != workspace_name:
        raise NotAnswered('a RESULT on a workspace the conversation was not seeded into: no observation')
    try:
        params = json.loads(bytes.fromhex(match.group(1)).decode('utf-8'))
    except ValueError:
        raise NotAnswered('a RESULT whose parameters are not hex-encoded JSON') from None
    if not isinstance(params, dict) or set(params) != PARAMETERS \
            or any(params[k] != v for k, v in CONSTANTS.items()) \
            or not all(isinstance(params[k], str) for k in ('base', 'base_ref', 'bundle', 'ref', 'name', 'email',
                                                            'date', 'message')) \
            or type(params['frame']) is not bool or re.fullmatch(r'[0-9a-f]{40}', params['base']) is None:
        raise NotAnswered('a RESULT whose parameters are not the production builder\'s: no observation')
    return params, match.group(1), match.group(2)


def check_base(workspace: Path) -> None:
    """The seeded workspace outside openspec/ and backlog/ is D1's demo repository, file for file by blob id."""
    found = {}
    for path in sorted(workspace.rglob('*')):
        rel = path.relative_to(workspace).as_posix()
        if path.is_file() and rel.split('/')[0] not in PROTECTED:
            found[rel] = blob_id(path.read_bytes())
    if found != DEMO_BLOBS:
        raise NotAnswered('a RESULT whose base is not D1\'s outside openspec/ and backlog/: no observation')


def served_stdout(stdout: str, report: str | None = None) -> str:
    """The script's output with its test-output line D1's recorded one; NotAnswered unless the script's own run
    printed each marker once, exited at ``done``, and its tests passed (status 0)."""
    lines = stdout.split('\n')
    marks = [LINE_RE.match(line) for line in lines]
    names = [m.group(1) for m in marks if m]
    if 'failed' in names or sorted(names) != sorted(['base', 'tree', 'commit', 'excluded', 'bundle', 'tests',
                                                    'test-output', 'done']):
        raise NotAnswered('a RESULT whose script did not complete: no observation')
    if 'AIEH-RESULT tests 0' not in lines:
        raise NotAnswered('a RESULT whose tests did not pass over D1\'s base and changes: no observation')
    recorded = d1_test_output(report).hex()
    return '\n'.join(f'AIEH-RESULT test-output {recorded}' if m and m.group(1) == 'test-output' else line
                     for line, m in zip(lines, marks))


def _load_no_window():
    """integrations/platform/no_window.py, the shared no-window helper, loaded by path once per process."""
    import importlib.util
    module = sys.modules.get('aieh_no_window')
    if module is None:
        spec = importlib.util.spec_from_file_location('aieh_no_window',
                                                      REPO / 'integrations' / 'platform' / 'no_window.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['aieh_no_window'] = module
    return module


def run(script: str, payload: str, workspace: Path, cwd: Path, timeout: int, python: str) -> tuple:
    """The harness's RESULT script over WORKSPACE, its parameters on standard input as the command pipes them,
    with no visible window (the shared no-window helper)."""
    done = subprocess.run([python, '-I', '-c', script, str(workspace)], input=payload.encode('ascii'),
                          capture_output=True, timeout=timeout, cwd=cwd,
                          creationflags=_load_no_window().no_window_flags())
    return done.returncode, done.stdout.decode('utf-8', 'replace').replace('\r\n', '\n')


def answer(scratch: Path, held: dict, body, *, python: str) -> str:
    """The RESULT answer's stdout for the held conversation (``held``: the core's state, with the seeded workspace),
    or NotAnswered. The workspace is edited and the script run in a copy, so the seeded workspace stays the base."""
    seeded = held.get('seeded')
    if not seeded:
        raise NotAnswered('a RESULT before SEED: no observation')
    if held.get('execution_status') != 'finished':
        raise NotAnswered('a RESULT before the turn finished: no observation')
    if held.get('result'):
        raise NotAnswered('a second RESULT on the conversation: no observation')
    params, payload, script = parameters(body, seeded['repository'])
    source = Path(seeded['path'])
    check_base(source)
    report = report_text()
    work = scratch / 'result'
    if work.exists():
        shutil.rmtree(work)
    workspace = work / seeded['repository']
    shutil.copytree(source, workspace)
    apply_changes(workspace, d1_changes(report))
    held['result'] = True
    code, stdout = run(script, payload, workspace, work, body['timeout'], python)
    if code != 0:
        raise NotAnswered(f'a RESULT whose script exits {code}: no record observes its answer')
    return served_stdout(stdout, report)
