#!/usr/bin/env python3
"""Report a commitment's committed set and its readiness, read-only.

A commitment names a milestone's terminal leaf (decision 0018, point 6). Its committed set is the
terminal leaf's transitive dependency closure in the plan, the leaf itself included. This tool
computes that set from the plan's ``work_packages``, and each leaf's status from exactly one
source (plan leaf P-05.1); it keeps no copy of either and writes nothing.

Status of a leaf, from exactly one source:

1. its row in the Leaves table of ``evidence/bootstrap-log.md``, if it has one: the first bold
   token of the row's verdict cell, reduced to its leading upper-case words (``**PASS
   (2026-11-12)**`` is PASS, ``**IN PROGRESS (...)**`` is IN PROGRESS, ``**BLOCKED on one clause
   ...**`` is BLOCKED; a cell without a bold token is read the same way from its start); passed
   when PASS;
2. else its Backlog.md task's status, in ``backlog/tasks/``: passed when ``Done``, open with the
   task's status otherwise;
3. else "not started".

A leaf with both a row and a task is refused (``STATUS_TWO_SOURCES``). The Leaves table is closed
(P-05.1): the log records the row count at closure, and a table with another count is refused.

A leaf is *passed* or *open*. An open leaf is *ready* when every plan dependency is passed and its
task depends on no open Owner-act task; otherwise it is *blocked*, and the Owner acts it waits on
are named. Its own status (for example BLOCKED or In Progress) is reported beside it.

The repository's Backlog.md tasks are checked on every run, and any mismatch refuses the report:

- a leaf task's title is ``<leaf id>: <plan title>`` and it references ``<plan file>#<leaf id>``;
  an Owner-act task's title is ``OA-<n>: <what>``, for an act in the log's Owner actions; one task
  per leaf and per act;
- a leaf task's milestone is the plan milestone of the leaf's phase;
- a leaf task's acceptance criteria, joined by one space, equal the leaf's plan proof after
  whitespace normalization;
- a leaf task's dependencies are exactly the tasks of its plan dependencies, plus any Owner-act
  tasks; a plan dependency with no Leaves-table row has a task;
- an Owner-act task is Done only when it references ``evidence/bootstrap-log.md#owner-...``, an
  anchor in the log's Decisions (the Owner's recorded act).

The Backlog.md files are read by a strict reader of the subset Backlog.md 1.55.3 writes (YAML front
matter of plain, quoted and folded scalars and lists; the acceptance-criteria block). Anything
outside that subset, and any file in ``backlog/`` other than ``config.yml``, ``tasks/*.md`` and
``milestones/*.md``, is refused, never skipped.

Usage: python -I -B tools/plan_commitment.py LEAF [--json] [--plan FILE] [--log FILE] [--backlog-dir DIR]

Exit codes: 0 reported; 2 refused, with a stable code:

- UNKNOWN_LEAF: the id is not a plan leaf;
- DEPENDENCY_CYCLE: the closure has a cycle;
- UNREADABLE_FILE: a file is missing or cannot be parsed, or the log has no Leaves table;
- LEAVES_CLOSURE_MISSING: the Leaves section has no single closure record;
- LEAVES_TABLE_REOPENED: the Leaves table's row count differs from the count at closure;
- BACKLOG_UNREADABLE: a Backlog.md file outside the reader's subset, an unsupported file, a
  duplicate task id, an unknown status or milestone;
- BACKLOG_CONFIG_REFUSED: the Backlog.md configuration enables auto-commit, remote operations or
  cross-branch checks;
- TASK_UNMAPPED: a task's title names neither a plan leaf nor an Owner act of the log;
- TASK_DUPLICATE: two tasks for one leaf or one Owner act;
- TASK_LINK_MISMATCH: a leaf task's title or plan reference differs from its plan contract;
- TASK_MILESTONE_MISMATCH: a leaf task's milestone is not its leaf's plan milestone;
- TASK_CRITERIA_MISMATCH: a leaf task's acceptance criteria differ from its leaf's proof;
- TASK_DEPENDENCIES_MISMATCH: a leaf task's dependencies differ from its plan dependencies' tasks,
  or name a task that does not exist;
- TASK_MISSING: a leaf task's plan dependency has neither a Leaves-table row nor a task;
- STATUS_TWO_SOURCES: a leaf has both a Leaves-table row and a task;
- OWNER_ACT_UNKNOWN: an Owner-act task names an act that the log's Owner actions do not list;
- OWNER_ACT_UNRECORDED: an Owner-act task is Done without a reference to an Owner's recorded act
  in the log's Decisions.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = 'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json'
LOG = 'evidence/bootstrap-log.md'
BACKLOG = 'backlog'
SCHEMA = 'ai-engineering-harness/plan-commitment/v2'
NOT_STARTED = 'not started'
PASS = 'PASS'
DONE = 'Done'
OWNER_ANCHOR_PREFIX = 'owner-'
# Backlog.md settings that would let it commit, reach a remote or read other branches.
CONFIG_OFF = ('auto_commit', 'remote_operations', 'check_active_branches')

BOLD = re.compile(r'\*\*(.+?)\*\*')
UPPER_WORD = re.compile(r"[A-Z][A-Z'-]+")
CLOSURE = re.compile(r'\*\*Closed on (\d{4}-\d{2}-\d{2}) at (\d+) rows\b')
ANCHOR = re.compile(r'<a id="([^"]+)"></a>')
ACT_ID = re.compile(r'OA-\d+')
ACT_ROW = re.compile(r'\| (OA-\d+) \|')
TITLE = re.compile(r'(\S+?): (\S.*)')


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
    """Return the plan's leaves as {id: leaf}, in plan order, its group aliases, and the
    milestone code of each phase."""
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
        milestones = {m['id']: m['code'] for m in plan.get('milestones', [])}
    except Refusal:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise Refusal('UNREADABLE_FILE', f'cannot parse the plan {path}: {exc}') from None
    return leaves, aliases, milestones


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


def section(lines, heading):
    """The lines under ``heading`` up to the next level-2 heading, or None."""
    try:
        start = lines.index(heading)
    except ValueError:
        return None
    out = []
    for line in lines[start + 1:]:
        if line.startswith('## '):
            break
        out.append(line)
    return out


class Log:
    """What the tool reads from the log: Leaves-table statuses, the closure check, the Owner-act
    ids of the Owner-actions queue and the anchors of the Decisions."""

    def __init__(self, path):
        lines = read_text(path, 'log').replace('\r\n', '\n').split('\n')
        leaves = section(lines, '## Leaves')
        if leaves is None:
            raise Refusal('UNREADABLE_FILE', f'no "## Leaves" section in {path}')
        self.statuses, rows = self._table(leaves, path)
        closures = CLOSURE.findall('\n'.join(leaves))
        if len(closures) != 1:
            raise Refusal('LEAVES_CLOSURE_MISSING',
                          f'the Leaves section of {path} has {len(closures)} closure records '
                          '("**Closed on <date> at <n> rows"), not exactly one')
        (date, count), = closures
        if rows != int(count):
            raise Refusal('LEAVES_TABLE_REOPENED',
                          f'the Leaves table has {rows} rows; it was closed on {date} at {count} rows')
        self.closed = {'date': date, 'rows': int(count)}
        self.acts = set(ACT_ROW.findall('\n'.join(section(lines, '## Owner actions') or [])))
        self.decision_anchors = set(ANCHOR.findall('\n'.join(section(lines, '## Decisions') or [])))

    @staticmethod
    def _table(lines, path):
        """{leaf id: status} and the row count of the first table under the heading."""
        statuses = {}
        rows = 0
        in_table = False
        for line in lines:
            if not line.startswith('|'):
                if in_table:
                    break
                continue
            if not in_table:
                in_table = True  # the header row
                continue
            if line.startswith('|---'):
                continue
            rows += 1
            cells = line.strip().strip('|').split(' | ')
            if len(cells) < 2:
                continue
            task = cells[0].strip().split(' ', 1)[0]
            statuses.setdefault(task, status_of(cells[1]))
        if not in_table:
            raise Refusal('UNREADABLE_FILE', f'no Leaves table in {path}')
        return statuses, rows


def load_statuses(path):
    """Return {leaf id: status} from the first table under the log's "## Leaves" heading."""
    return Log(path).statuses


# --------------------------------------------------------------------------- Backlog.md reader

def _unreadable(where, why):
    return Refusal('BACKLOG_UNREADABLE', f'{where}: {why}')


def _scalar(text, where):
    """One YAML scalar on one line, of the forms Backlog.md writes: plain, single- or
    double-quoted (without escapes), or an empty flow list ``[]``."""
    if text == '[]':
        return []
    if text.startswith('['):
        return _flow_list(text, where)
    if text.startswith("'"):
        inner = text[1:-1] if len(text) >= 2 and text.endswith("'") else None
        if inner is None or "'" in inner.replace("''", ''):
            raise _unreadable(where, f'unsupported single-quoted scalar {text!r}')
        return inner.replace("''", "'")
    if text.startswith('"'):
        inner = text[1:-1] if len(text) >= 2 and text.endswith('"') else None
        if inner is None or '"' in inner or '\\' in inner:
            raise _unreadable(where, f'unsupported double-quoted scalar {text!r}')
        return inner
    if (not text or text[0] in '>|&*!{%@`#,?-]' and not re.fullmatch(r'-?[\w.-]+', text)
            or ': ' in text or ' #' in text or text.endswith(':') or text != text.strip()):
        raise _unreadable(where, f'unsupported scalar {text!r}')
    return text


def _flow_list(text, where):
    """A flow list of double-quoted (no escapes) or plain items: ``["To Do", "Done"]``."""
    if not text.endswith(']'):
        raise _unreadable(where, f'unsupported flow list {text!r}')
    items = []
    for part in text[1:-1].split(','):
        part = part.strip()
        if re.fullmatch(r'"[^"\\]*"', part):
            items.append(part[1:-1])
        elif re.fullmatch(r'[A-Za-z0-9_.-][A-Za-z0-9_. -]*', part) and part == part.strip():
            items.append(part)
        else:
            raise _unreadable(where, f'unsupported flow list {text!r}')
    return items


def _folded(lines, i, indent, where):
    """A ``>-`` block's lines at exactly ``indent`` spaces, joined by one space."""
    parts = []
    prefix = ' ' * indent
    while i < len(lines) and lines[i].startswith(prefix) and lines[i][indent:indent + 1] not in ('', ' '):
        parts.append(lines[i][indent:])
        i += 1
    if not parts:
        raise _unreadable(where, 'an empty or more-indented folded scalar')
    if i < len(lines) and lines[i].startswith(prefix):
        raise _unreadable(where, 'a more-indented or blank line in a folded scalar')
    return ' '.join(parts), i


def parse_yaml(lines, where, blank_lines=False):
    """The YAML subset Backlog.md writes in front matter and ``config.yml``: ``key: scalar``,
    ``key: >-`` with folded lines, and ``key:`` with a block list of scalars or ``>-`` items."""
    out = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if blank_lines and not line:
            i += 1
            continue
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*):(?: (.+))?', line)
        if not match:
            raise _unreadable(where, f'unsupported line {line!r}')
        key, rest = match.groups()
        if key in out:
            raise _unreadable(where, f'duplicate key {key!r}')
        i += 1
        if rest == '>-':
            out[key], i = _folded(lines, i, 2, where)
        elif rest is not None:
            out[key] = _scalar(rest, where)
        else:
            items = []
            while i < len(lines) and lines[i].startswith('  - '):
                item = lines[i][4:]
                i += 1
                if item == '>-':
                    value, i = _folded(lines, i, 4, where)
                    items.append(value)
                else:
                    value = _scalar(item, where)
                    if not isinstance(value, str):
                        raise _unreadable(where, f'unsupported list item {item!r}')
                    items.append(value)
            if not items:
                raise _unreadable(where, f'key {key!r} has no value')
            out[key] = items
    return out


def front_matter(path):
    """(front matter, body lines) of a Backlog.md markdown file."""
    lines = read_text(path, 'Backlog.md file').replace('\r\n', '\n').split('\n')
    if not lines or lines[0] != '---' or '---' not in lines[1:]:
        raise _unreadable(path, 'no front matter')
    end = lines.index('---', 1)
    return parse_yaml(lines[1:end], str(path)), lines[end + 1:]


AC_ITEM = re.compile(r'- \[([ x])\] #(\d+) (\S.*)')


def criteria(body, where):
    """The acceptance-criteria items' texts, in order; [] when the task has none."""
    begins = [n for n, line in enumerate(body) if line == '<!-- AC:BEGIN -->']
    ends = [n for n, line in enumerate(body) if line == '<!-- AC:END -->']
    if not begins and not ends:
        return []
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise _unreadable(where, 'not exactly one acceptance-criteria block')
    items = []
    for line in body[begins[0] + 1:ends[0]]:
        match = AC_ITEM.fullmatch(line)
        if not match or int(match.group(2)) != len(items) + 1:
            raise _unreadable(where, f'unsupported acceptance-criteria line {line!r}')
        items.append(match.group(3))
    return items


def _text(meta, key, where, required=True):
    value = meta.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise _unreadable(where, f'{key!r} is missing or not text')
    return value


def _list(meta, key, where):
    value = meta.get(key, [])
    if not isinstance(value, list):
        raise _unreadable(where, f'{key!r} is not a list')
    return value


class Backlog:
    """The repository's Backlog.md tasks, milestones and statuses, read strictly."""

    def __init__(self, directory):
        directory = Path(directory)
        if not directory.is_dir():
            raise Refusal('UNREADABLE_FILE', f'no Backlog.md directory {directory}')
        for path in sorted(p for p in directory.rglob('*') if not p.is_dir()):
            rel = path.relative_to(directory).as_posix()
            if not (rel == 'config.yml' or re.fullmatch(r'(tasks|milestones)/[^/]+\.md', rel)):
                raise _unreadable(path, 'unsupported file (the reader reads config.yml, tasks/*.md and '
                                        'milestones/*.md only)')
        config_path = directory / 'config.yml'
        config = parse_yaml(read_text(config_path, 'Backlog.md configuration')
                            .replace('\r\n', '\n').split('\n'), str(config_path), blank_lines=True)
        self.statuses = config.get('statuses')
        if not isinstance(self.statuses, list) or not self.statuses:
            raise _unreadable(config_path, 'no statuses')
        for key in CONFIG_OFF:
            if config.get(key) != 'false':
                raise Refusal('BACKLOG_CONFIG_REFUSED', f'{config_path}: {key} must be false')
        self.milestones = {}
        for path in sorted((directory / 'milestones').glob('*.md')):
            meta, _ = front_matter(path)
            ident = _text(meta, 'id', path)
            if ident in self.milestones:
                raise _unreadable(path, f'duplicate milestone id {ident}')
            self.milestones[ident] = _text(meta, 'title', path)
        self.tasks = {}
        for path in sorted((directory / 'tasks').glob('*.md')):
            meta, body = front_matter(path)
            ident = _text(meta, 'id', path)
            if ident in self.tasks:
                raise _unreadable(path, f'duplicate task id {ident}')
            status = _text(meta, 'status', path)
            if status not in self.statuses:
                raise _unreadable(path, f'status {status!r} is not one of {self.statuses}')
            milestone = _text(meta, 'milestone', path, required=False)
            if milestone is not None and milestone not in self.milestones:
                raise _unreadable(path, f'milestone {milestone!r} has no milestone file')
            self.tasks[ident] = {
                'id': ident, 'path': path, 'title': _text(meta, 'title', path), 'status': status,
                'milestone': self.milestones.get(milestone), 'dependencies': _list(meta, 'dependencies', path),
                'references': _list(meta, 'references', path), 'criteria': criteria(body, path)}


def normalize(text):
    return ' '.join(text.split())


class Work:
    """The leaf-to-task and act-to-task mappings, validated against the plan and the log."""

    def __init__(self, leaves, milestones, log, backlog):
        self.leaf_task = {}
        self.act_task = {}
        tasks = backlog.tasks
        for task in tasks.values():
            match = TITLE.fullmatch(task['title'])
            head = match.group(1) if match else None
            if head and ACT_ID.fullmatch(head):
                if head not in log.acts:
                    raise Refusal('OWNER_ACT_UNKNOWN', f'{task["id"]} names {head}, which the log\'s '
                                                       'Owner actions do not list')
                target = self.act_task
            elif head in leaves:
                target = self.leaf_task
            else:
                raise Refusal('TASK_UNMAPPED', f'{task["id"]} ({task["title"]!r}) names neither a plan leaf '
                                               'nor an Owner act: its title must be "<leaf id>: <plan title>" '
                                               'or "OA-<n>: <what>"')
            if head in target:
                raise Refusal('TASK_DUPLICATE', f'{head} has two tasks: {target[head]["id"]} and {task["id"]}')
            target[head] = task
        self.act_of = {task['id']: act for act, task in self.act_task.items()}
        self.leaf_of = {task['id']: leaf for leaf, task in self.leaf_task.items()}
        for ident, task in self.leaf_task.items():
            if ident in log.statuses:
                raise Refusal('STATUS_TWO_SOURCES', f'{ident} has both a Leaves-table row and the task {task["id"]}')
        for act, task in self.act_task.items():
            self._check_act(act, task, log)
        for ident, task in self.leaf_task.items():
            self._check_leaf(ident, task, leaves, milestones, log, tasks)

    @staticmethod
    def _check_act(act, task, log):
        if task['status'] != DONE:
            return
        prefix = LOG + '#'
        recorded = [ref[len(prefix):] for ref in task['references'] if ref.startswith(prefix)]
        if not any(anchor.startswith(OWNER_ANCHOR_PREFIX) and anchor in log.decision_anchors
                   for anchor in recorded):
            raise Refusal('OWNER_ACT_UNRECORDED',
                          f'{task["id"]} ({act}) is {DONE} without a reference {prefix}{OWNER_ANCHOR_PREFIX}... '
                          'to an anchor in the log\'s Decisions (the Owner\'s recorded act)')

    def _check_leaf(self, ident, task, leaves, milestones, log, tasks):
        leaf = leaves[ident]
        tid = task['id']
        if task['title'] != f'{ident}: {leaf.get("title", "")}' or f'{PLAN}#{ident}' not in task['references']:
            raise Refusal('TASK_LINK_MISMATCH', f'{tid} for {ident}: its title must be "{ident}: <plan title>" '
                                                f'and it must reference {PLAN}#{ident}')
        expected_milestone = milestones.get(leaf.get('phase'))
        if not task['milestone'] or task['milestone'] != expected_milestone:
            raise Refusal('TASK_MILESTONE_MISMATCH', f'{tid} for {ident}: milestone {task["milestone"]!r}, '
                                                     f'the plan milestone is {expected_milestone!r}')
        if normalize(' '.join(task['criteria'])) != normalize(leaf.get('proof', '')):
            raise Refusal('TASK_CRITERIA_MISMATCH', f'{tid} for {ident}: its acceptance criteria, joined, '
                                                    f'differ from the plan proof of {ident}')
        for dep in leaf['deps']:
            if dep not in log.statuses and dep not in self.leaf_task:
                raise Refusal('TASK_MISSING', f'{ident} ({tid}) depends on {dep}, which has neither a '
                                              'Leaves-table row nor a task')
        actual = task['dependencies']
        unknown = [d for d in actual if d not in tasks]
        expected = {self.leaf_task[d]['id'] for d in leaf['deps'] if d in self.leaf_task}
        leaf_deps = {d for d in actual if d not in self.act_of}
        if unknown or len(set(actual)) != len(actual) or leaf_deps != expected:
            raise Refusal('TASK_DEPENDENCIES_MISMATCH',
                          f'{tid} for {ident}: dependencies {sorted(actual)}, expected the tasks of its plan '
                          f'dependencies {sorted(expected)} plus Owner-act tasks'
                          + (f'; {", ".join(unknown)} do not exist' if unknown else ''))

    def open_acts(self, ident, backlog):
        """The open Owner acts the leaf's task depends on, in act order."""
        task = self.leaf_task.get(ident)
        if task is None:
            return []
        acts = [self.act_of[d] for d in task['dependencies']
                if d in self.act_of and backlog.tasks[d]['status'] != DONE]
        return sorted(acts, key=lambda a: int(a.split('-')[1]))


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


def report(terminal, plan_path=None, log_path=None, backlog_dir=None):
    plan_path = plan_path or ROOT / PLAN
    log_path = log_path or ROOT / LOG
    backlog_dir = backlog_dir or ROOT / BACKLOG
    leaves, aliases, milestones = load_plan(plan_path)
    if terminal not in leaves:
        hint = f'; {terminal} is an acceptance group, its terminal leaf is {aliases[terminal]}' \
            if terminal in aliases else ''
        raise Refusal('UNKNOWN_LEAF', f'{terminal!r} is not a leaf of the plan{hint}')
    log = Log(log_path)
    backlog = Backlog(backlog_dir)
    work = Work(leaves, milestones, log, backlog)
    members = closure(leaves, terminal)

    def state(ident):
        """(status, passed, source, task id)."""
        if ident in log.statuses:
            status = log.statuses[ident]
            return status, status == PASS, 'leaves-table', None
        task = work.leaf_task.get(ident)
        if task is not None:
            return task['status'], task['status'] == DONE, 'backlog', task['id']
        return NOT_STARTED, False, 'none', None

    states = {ident: state(ident) for ident in members}
    rows = []
    for ident in members:
        leaf = leaves[ident]
        status, passed, source, task = states[ident]
        deps = list(leaf['deps'])
        waits_on = [] if passed else work.open_acts(ident, backlog)
        ready = not passed and not waits_on and all(states[d][1] for d in deps)
        rows.append({'id': ident, 'title': leaf.get('title', ''), 'status': status, 'source': source,
                     'task': task, 'deps': deps, 'waits_on': waits_on, 'passed': passed, 'ready': ready})
    passed = sum(r['passed'] for r in rows)
    ready = [r['id'] for r in rows if r['ready']]
    summary = {'total': len(rows), 'passed': passed, 'open': len(rows) - passed, 'ready': len(ready),
               'blocked': len(rows) - passed - len(ready)}
    return {'schema': SCHEMA, 'terminal': terminal, 'leaves': rows, 'summary': summary, 'ready': ready,
            'leaves_table': log.closed}


def render(result):
    out = [f"Committed set of {result['terminal']} (the terminal leaf and its transitive dependencies)", '']
    width = max(len(r['id']) for r in result['leaves'])
    swidth = max(len(r['status']) for r in result['leaves'])
    for r in result['leaves']:
        mark = 'ready' if r['ready'] else ('passed' if r['passed'] else 'blocked')
        deps = ', '.join(r['deps']) or '-'
        line = f"{r['id']:<{width}}  {r['status']:<{swidth}}  {mark:<7}  {r['title']}  [deps: {deps}]"
        if r['task']:
            line += f"  [task: {r['task']}]"
        if r['waits_on']:
            line += f"  [waits on Owner act: {', '.join(r['waits_on'])}]"
        out.append(line)
    s = result['summary']
    closed = result['leaves_table']
    out += ['', f"Summary: total {s['total']}, passed {s['passed']}, open {s['open']}, "
                f"ready {s['ready']}, blocked {s['blocked']}",
            f"Ready: {', '.join(result['ready']) or 'none'}",
            f"Status sources: the Leaves table (closed on {closed['date']} at {closed['rows']} rows), "
            f"else the Backlog.md task, else not started"]
    return '\n'.join(out)


def main(argv=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = argparse.ArgumentParser(description="Report a commitment's committed set and readiness (read-only).")
    parser.add_argument('leaf', help="the commitment's terminal leaf id")
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    parser.add_argument('--plan', help=f'the plan JSON (default: {PLAN})')
    parser.add_argument('--log', help=f'the log with the Leaves table (default: {LOG})')
    parser.add_argument('--backlog-dir', help=f'the Backlog.md directory (default: {BACKLOG})')
    args = parser.parse_args(argv)
    try:
        result = report(args.leaf, args.plan, args.log, args.backlog_dir)
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
