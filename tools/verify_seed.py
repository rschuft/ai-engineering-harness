#!/usr/bin/env python3
"""Read-only consistency check for the AI Engineering harness seed (stdlib only).

Default mode checks the working tree against SEED_MANIFEST.json. Every listed
path belongs to one class (CLASSES below):

  contract   strict: a hash mismatch fails. Executable task contracts and this
             verifier.
  authority  strict but updatable: a hash mismatch fails. To change one, edit
             the file and its sha256 in SEED_MANIFEST.json in the same commit.
  ordinary   free to evolve: a mismatch or a missing file is reported as INFO.

A manifest path with no class fails, so new entries are classified deliberately.
Default mode needs no git.

Baseline mode (--baseline REV) verifies the original import: it reads
SEED_MANIFEST.json and every file it lists as of REV from git's object
database, never from the working tree, and checks every file strictly.
'--baseline seed' names the bootstrap revision.

Exit status: 0 PASS, 1 FAIL, 2 the check could not run (usage, git, revision).
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PLAN = 'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json'
BLUEPRINT = 'AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html'
SEED_REVISION = '13197ddf1b4b49924add5dda21c39ac619cbdf3b'  # Bootstrap repository from 2026-11-05 seed archive
REVISION_ALIASES = {'seed': SEED_REVISION}

# Path classes. An entry ending in '/' covers every path below it.
CLASSES = {
    'contract': (
        PLAN,
        'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.html',
        'AI_Engineering_Implementation_Work_Packages_Small_Steps_2026-10-31.csv',
        'task_manifest.json',
        'task_prompts/',
        'tools/verify_seed.py',
    ),
    'authority': (
        BLUEPRINT,
        'OVERSEER_START.md',
    ),
    'ordinary': (
        'README.md',
        'CLAUDE.md',
        '.gitignore',
    ),
}


class CannotRun(Exception):
    """The check could not be carried out (exit status 2)."""


def classify(path):
    for name, patterns in CLASSES.items():
        for pattern in patterns:
            if path == pattern or (pattern.endswith('/') and path.startswith(pattern)):
                return name
    return None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def worktree_reader(root):
    def read(path):
        file = root / path
        return file.read_bytes() if file.is_file() else None
    return read, lambda: None


def git_reader(root, rev):
    """Read blobs as of REV from the object database; return (read, close, commit)."""
    def git(*args):
        try:
            return subprocess.run(['git', '-C', str(root), *args], capture_output=True)
        except OSError as exc:
            raise CannotRun(f'git is unavailable: {exc}') from exc

    probe = git('rev-parse', '--git-dir')
    if probe.returncode:
        raise CannotRun(f'not a git repository: {root}')
    resolved = git('rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}')
    if resolved.returncode:
        raise CannotRun(f'baseline revision not available: {rev}')
    commit = resolved.stdout.decode('ascii').strip()
    proc = subprocess.Popen(['git', '-C', str(root), 'cat-file', '--batch'],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    cache = {}

    def read(path):
        if path not in cache:
            proc.stdin.write(f'{commit}:{path}\n'.encode('utf-8'))
            proc.stdin.flush()
            header = proc.stdout.readline().decode('utf-8').split()
            if header and header[-1] == 'missing':
                cache[path] = None
            elif len(header) == 3 and header[2].isdigit():
                data = proc.stdout.read(int(header[2]) + 1)[:-1]
                cache[path] = data if header[1] == 'blob' else None
            else:
                raise CannotRun(f'unexpected git cat-file output for {path}: {header}')
        return cache[path]

    def close():
        proc.stdin.close()
        proc.stdout.close()
        proc.wait()

    return read, close, commit


def load_json(read, path, errors):
    data = read(path)
    if data is None:
        errors.append(f'missing file: {path}')
        return None
    return json.loads(data.decode('utf-8'))


def verify(read, strict_all):
    """Return (errors, infos, stats) for the seed visible through READ."""
    errors, infos = [], []
    counts = {name: 0 for name in CLASSES}
    ordinary_changed = 0
    manifest = load_json(read, 'SEED_MANIFEST.json', errors)
    if manifest is None:
        return errors, infos, None
    for item in manifest['files']:
        path = item['path']
        cls = classify(path)
        if cls is None:
            errors.append(f'unclassified manifest path: {path}')
            continue
        counts[cls] += 1
        data = read(path)
        relaxed = cls == 'ordinary' and not strict_all
        if data is None:
            if relaxed:
                infos.append(f'ordinary file missing: {path}')
                ordinary_changed += 1
            else:
                errors.append(f'missing {cls} file: {path}')
        elif sha256(data) != item['sha256']:
            if relaxed:
                infos.append(f'ordinary file changed since seed: {path}')
                ordinary_changed += 1
            else:
                errors.append(f'changed {cls} file: {path}')

    plan = load_json(read, PLAN, errors)
    task_manifest = load_json(read, 'task_manifest.json', errors)
    if plan is None or task_manifest is None:
        return errors, infos, None
    tasks = plan['work_packages']
    task_ids = [t['id'] for t in tasks]
    unique_ids = set(task_ids)
    if len(task_ids) != len(unique_ids):
        errors.append('duplicate executable task IDs')
    if any(t.get('size') != 'S' for t in tasks):
        errors.append('a non-Small executable task is present')
    unknown = [(t['id'], dep) for t in tasks for dep in t['deps'] if dep not in unique_ids]
    if unknown:
        errors.append(f'unknown dependency IDs: {unknown[:8]}')
    graph = {t['id']: set(t['deps']) for t in tasks}
    ready = [tid for tid, deps in graph.items() if not deps]
    seen = set()
    while ready:
        task_id = ready.pop()
        if task_id in seen:
            continue
        seen.add(task_id)
        for successor, deps in graph.items():
            if task_id in deps:
                deps.remove(task_id)
                if not deps and successor not in seen:
                    ready.append(successor)
    if len(seen) != len(unique_ids):
        errors.append('dependency graph contains a cycle or unresolved reference')

    rows = task_manifest['tasks']
    if len(rows) != len(tasks) or task_manifest['task_count'] != len(tasks):
        errors.append('task manifest count differs from plan')
    row_ids = {r['id'] for r in rows}
    if row_ids != unique_ids:
        errors.append('task manifest IDs differ from plan')
    tasks_by_id = {t['id']: t for t in tasks}
    for row in rows:
        tid = row['id']
        data = read(row['path'])
        if data is None:
            errors.append(f'missing task prompt: {row["path"]}')
            continue
        if sha256(data) != row['sha256']:
            errors.append(f'prompt content mismatch: {row["path"]}')
        if tid in tasks_by_id and row['deps'] != tasks_by_id[tid]['deps']:
            errors.append(f'prompt dependency mismatch: {tid}')
        if tid in tasks_by_id and not tasks_by_id[tid].get('overseer_prompt'):
            errors.append(f'no Overseer instructions on task: {tid}')

    if plan.get('baseline') != BLUEPRINT:
        errors.append('plan baseline filename differs from bundled architecture')
    if 'LICENSE' in {item['path'] for item in manifest['files']}:
        errors.append('seed would overwrite repository LICENSE')
    stats = {'tasks': len(tasks), 'prompts': len(rows), 'files': len(manifest['files']),
             'counts': counts, 'ordinary_changed': ordinary_changed}
    return errors, infos, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify the AI Engineering harness seed.')
    parser.add_argument('--baseline', metavar='REV',
                        help="verify the seed strictly as of git revision REV, read from the "
                             f"object database ('seed' = {SEED_REVISION})")
    args = parser.parse_args(argv)
    try:
        if args.baseline is None:
            read, close = worktree_reader(ROOT)
            commit = None
        else:
            read, close, commit = git_reader(ROOT, REVISION_ALIASES.get(args.baseline, args.baseline))
        try:
            errors, infos, stats = verify(read, strict_all=commit is not None)
        finally:
            close()
    except CannotRun as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 2
    for info in infos:
        print('INFO:', info)
    if errors:
        for err in errors:
            print('FAIL:', err, file=sys.stderr)
        print(f'{len(errors)} issue(s) found', file=sys.stderr)
        return 1
    c = stats['counts']
    if commit is None:
        files = (f'{stats["files"]} seeded files ({c["contract"]} contract intact, '
                 f'{c["authority"]} authority intact, {c["ordinary"]} ordinary, '
                 f'{stats["ordinary_changed"]} changed since seed)')
        prefix = 'PASS'
    else:
        files = (f'{stats["files"]} intact seeded files, all strict ({c["contract"]} contract, '
                 f'{c["authority"]} authority, {c["ordinary"]} ordinary)')
        prefix = f'PASS (baseline {commit})'
    print(f'{prefix}: {stats["tasks"]} executable Small tasks; {stats["prompts"]} task prompts; '
          f'{files}; dependency graph acyclic')
    print('NOTE: This verifies package integrity, not agent execution or acceptance evidence.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
