#!/usr/bin/env python3
"""Read-only consistency check for the AI Engineering harness seed (stdlib only)."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
PLAN = 'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json'
BLUEPRINT = 'AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    errors = []
    manifest = json.loads((ROOT/'SEED_MANIFEST.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path = ROOT / item['path']
        if not path.is_file():
            errors.append(f'missing file: {item["path"]}')
        elif sha256(path) != item['sha256']:
            errors.append(f'changed file: {item["path"]}')

    plan = json.loads((ROOT/PLAN).read_text(encoding='utf-8'))
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

    task_manifest = json.loads((ROOT/'task_manifest.json').read_text(encoding='utf-8'))
    rows = task_manifest['tasks']
    if len(rows) != len(tasks) or task_manifest['task_count'] != len(tasks):
        errors.append('task manifest count differs from plan')
    row_ids = {r['id'] for r in rows}
    if row_ids != unique_ids:
        errors.append('task manifest IDs differ from plan')
    tasks_by_id = {t['id']: t for t in tasks}
    for row in rows:
        tid = row['id']
        path = ROOT / row['path']
        if not path.is_file():
            errors.append(f'missing task prompt: {row["path"]}')
            continue
        if sha256(path) != row['sha256']:
            errors.append(f'prompt content mismatch: {row["path"]}')
        if tid in tasks_by_id and row['deps'] != tasks_by_id[tid]['deps']:
            errors.append(f'prompt dependency mismatch: {tid}')
        if tid in tasks_by_id and not tasks_by_id[tid].get('overseer_prompt'):
            errors.append(f'no Overseer instructions on task: {tid}')

    if plan.get('baseline') != BLUEPRINT:
        errors.append('plan baseline filename differs from bundled architecture')
    if 'LICENSE' in {item['path'] for item in manifest['files']}:
        errors.append('seed would overwrite repository LICENSE')
    if errors:
        for err in errors:
            print('FAIL:', err, file=sys.stderr)
        print(f'{len(errors)} issue(s) found', file=sys.stderr)
        return 1
    print(f'PASS: {len(tasks)} executable Small tasks; {len(rows)} task prompts; '
          f'{len(manifest["files"])} intact seeded files; dependency graph acyclic')
    print('NOTE: This verifies package integrity, not agent execution or acceptance evidence.')
    return 0


if __name__ == '__main__':
    sys.exit(verify())
