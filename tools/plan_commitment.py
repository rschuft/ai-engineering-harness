#!/usr/bin/env python3
"""Report a commitment's committed set and its readiness, read-only.

A commitment names a milestone's terminal leaf (decision 0018, point 6). Its committed set is the
terminal leaf's transitive dependency closure in the plan, the leaf itself included. This tool
computes that set from the plan's ``work_packages`` and each leaf's status from the Leaves table
of ``evidence/bootstrap-log.md``; it keeps no copy of either and writes nothing.

Status of a leaf: the first bold token of its row's verdict cell, reduced to its leading
upper-case words (``**PASS (2026-11-12)**`` is PASS, ``**IN PROGRESS (...)**`` is IN PROGRESS,
``**BLOCKED on one clause ...**`` is BLOCKED). A row without a bold token is read the same way
from the start of the cell; a leaf without a row is "not started".

A leaf is *passed* when its status is PASS, *open* otherwise. An open leaf is *ready* when every
dependency is passed, and *blocked* when at least one dependency is not; its own status (for
example BLOCKED) is reported beside it.

Usage: python -I -B tools/plan_commitment.py LEAF [--json] [--plan FILE] [--log FILE]

Exit codes: 0 reported; 2 refused, with a stable code: UNKNOWN_LEAF (the id is not a plan leaf),
DEPENDENCY_CYCLE (the closure has a cycle), UNREADABLE_FILE (a file is missing or cannot be
parsed, or the log has no Leaves table).
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = 'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json'
LOG = 'evidence/bootstrap-log.md'
SCHEMA = 'ai-engineering-harness/plan-commitment/v1'
NOT_STARTED = 'not started'
PASS = 'PASS'

BOLD = re.compile(r'\*\*(.+?)\*\*')
UPPER_WORD = re.compile(r"[A-Z][A-Z'-]+")


class Refusal(Exception):
    """A refusal with a stable code."""

    def __init__(self, code, detail):
        super().__init__(f'{code}: {detail}')
        self.code = code
        self.detail = detail


def read_text(path, what):
    try:
        return Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal('UNREADABLE_FILE', f'cannot read the {what} {path}: {exc}') from None


def load_plan(path):
    """Return the plan's leaves as {id: leaf}, in plan order."""
    try:
        plan = json.loads(read_text(path, 'plan'))
        leaves = {}
        for leaf in plan['work_packages']:
            ident = leaf['id']
            deps = leaf['deps']
            if not isinstance(ident, str) or not isinstance(deps, list):
                raise TypeError(f'malformed leaf {ident!r}')
            leaves[ident] = leaf
        aliases = dict(plan.get('decomposition', {}).get('legacy_parent_aliases', {}))
        aliases.update(plan.get('decomposition', {}).get('medium_parent_aliases', {}))
    except Refusal:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise Refusal('UNREADABLE_FILE', f'cannot parse the plan {path}: {exc}') from None
    return leaves, aliases


def status_of(cell):
    """Reduce a Leaves-table verdict cell to its status token."""
    match = BOLD.search(cell)
    text = (match.group(1) if match else cell).strip()
    words = []
    for word in text.split():
        token = word.rstrip(':;,.')
        if not UPPER_WORD.fullmatch(token):
            break
        words.append(token)
        if token != word:
            break
    if words:
        return ' '.join(words)
    head = re.split(r'[(:;,.]', text, maxsplit=1)[0].strip().lower()
    return head or NOT_STARTED


def load_statuses(path):
    """Return {leaf id: status} from the first table under the log's "## Leaves" heading."""
    lines = read_text(path, 'log').splitlines()
    try:
        start = lines.index('## Leaves')
    except ValueError:
        raise Refusal('UNREADABLE_FILE', f'no "## Leaves" section in {path}') from None
    statuses = {}
    in_table = False
    for line in lines[start + 1:]:
        if line.startswith('## '):
            break
        if not line.startswith('|'):
            if in_table:
                break
            continue
        if not in_table:
            in_table = True  # the header row
            continue
        if line.startswith('|---'):
            continue
        cells = line.strip().strip('|').split(' | ')
        if len(cells) < 2:
            continue
        task = cells[0].strip().split(' ', 1)[0]
        statuses.setdefault(task, status_of(cells[1]))
    if not in_table:
        raise Refusal('UNREADABLE_FILE', f'no Leaves table in {path}')
    return statuses


def closure(leaves, terminal):
    """The terminal leaf's transitive dependency closure, in dependency order (plan order on ties)."""
    order = {ident: n for n, ident in enumerate(leaves)}
    members = set()
    stack = [terminal]
    while stack:
        ident = stack.pop()
        if ident in members:
            continue
        if ident not in leaves:
            raise Refusal('UNREADABLE_FILE', f'the plan names an unknown dependency {ident!r}')
        members.add(ident)
        stack.extend(leaves[ident]['deps'])
    remaining = {ident: set(leaves[ident]['deps']) for ident in members}
    result = []
    while remaining:
        free = sorted((i for i, deps in remaining.items() if not deps), key=order.get)
        if not free:
            cycle = ', '.join(sorted(remaining, key=order.get))
            raise Refusal('DEPENDENCY_CYCLE', f'the closure of {terminal} has a cycle among: {cycle}')
        for ident in free:
            result.append(ident)
            del remaining[ident]
        for deps in remaining.values():
            deps.difference_update(free)
    return result


def report(terminal, plan_path=None, log_path=None):
    plan_path = plan_path or ROOT / PLAN
    log_path = log_path or ROOT / LOG
    leaves, aliases = load_plan(plan_path)
    if terminal not in leaves:
        hint = f'; {terminal} is an acceptance group, its terminal leaf is {aliases[terminal]}' \
            if terminal in aliases else ''
        raise Refusal('UNKNOWN_LEAF', f'{terminal!r} is not a leaf of the plan{hint}')
    statuses = load_statuses(log_path)
    rows = []
    for ident in closure(leaves, terminal):
        leaf = leaves[ident]
        status = statuses.get(ident, NOT_STARTED)
        passed = status == PASS
        deps = list(leaf['deps'])
        ready = not passed and all(statuses.get(d, NOT_STARTED) == PASS for d in deps)
        rows.append({'id': ident, 'title': leaf.get('title', ''), 'status': status, 'deps': deps,
                     'passed': passed, 'ready': ready})
    passed = sum(r['passed'] for r in rows)
    ready = [r['id'] for r in rows if r['ready']]
    summary = {'total': len(rows), 'passed': passed, 'open': len(rows) - passed, 'ready': len(ready),
               'blocked': len(rows) - passed - len(ready)}
    return {'schema': SCHEMA, 'terminal': terminal, 'leaves': rows, 'summary': summary, 'ready': ready}


def render(result):
    out = [f"Committed set of {result['terminal']} (the terminal leaf and its transitive dependencies)", '']
    width = max(len(r['id']) for r in result['leaves'])
    swidth = max(len(r['status']) for r in result['leaves'])
    for r in result['leaves']:
        mark = 'ready' if r['ready'] else ('passed' if r['passed'] else 'blocked')
        deps = ', '.join(r['deps']) or '-'
        out.append(f"{r['id']:<{width}}  {r['status']:<{swidth}}  {mark:<7}  {r['title']}  [deps: {deps}]")
    s = result['summary']
    out += ['', f"Summary: total {s['total']}, passed {s['passed']}, open {s['open']}, "
                f"ready {s['ready']}, blocked {s['blocked']}",
            f"Ready: {', '.join(result['ready']) or 'none'}"]
    return '\n'.join(out)


def main(argv=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = argparse.ArgumentParser(description="Report a commitment's committed set and readiness (read-only).")
    parser.add_argument('leaf', help="the commitment's terminal leaf id")
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    parser.add_argument('--plan', help=f'the plan JSON (default: {PLAN})')
    parser.add_argument('--log', help=f'the log with the Leaves table (default: {LOG})')
    args = parser.parse_args(argv)
    try:
        result = report(args.leaf, args.plan, args.log)
    except Refusal as exc:
        if args.json:
            print(json.dumps({'schema': SCHEMA, 'error': {'code': exc.code, 'detail': exc.detail}}, indent=2),
                  file=stdout)
        print(f'REFUSED {exc.code}: {exc.detail}', file=stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False), file=stdout)
    else:
        print(render(result), file=stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
