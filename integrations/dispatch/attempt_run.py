"""The attempt run of a confirmed native D1 attempt (D1 slices A2 and A3; the work design accepted on 2026-11-15,
sections G2 to G6, with the engineering manager's rulings R1 to R5 and the A3 rulings on the review of A1 and A2).

``run_attempt(store, operation_key, transport=, base=, actor=, inspect=, pull=, observe=, reserve_result=)`` runs,
for an attempt ``dispatch_inputs.dispatch`` confirmed, the order the design fixes, every Agent Server call through
the route-checked client (``AgentServerClient``) and its two proxy tails:

0. **build** everything that is sent before anything is sent (review S2): the message, the commit message, the SEED
   and RESULT commands; a slot that cannot be filled refuses with no call;
1. **inspect**: ``GET /api/conversations/count`` is 1, ``GET /api/conversations/{id}`` is the reserved conversation,
   ``GET .../runtime`` is ``running``, and the caller's ``inspect(conversation_id)`` (the container facts, slice C)
   finds no problem. A failure sends no message and ends the attempt (``attempt_end.end_interrupted_attempt``,
   trigger ``attempt-stopped``, a ``containment-stop`` record ``INSPECTION_FAILED``): E-01.3.2's clause;
2. **SEED**: the base's tree (``read_base``: the approved repository's branch head, which must contain the accepted
   design commit; no ``.git``, no history, no link, gitlink or forbidden name, R3) into ``/workspace/<repository>``,
   a gzipped tar in the command's text, hex-encoded (``build_seed``);
3. **MESSAGE**: one versioned frame (``FRAME_VERSION``) whose slots come only from the reserved record and the seeded
   tree (``build_message``); the turn journal ``dispatch/attempt/<attempt id>/turn`` is reserved (base, seed digest
   and count, frame version, the message's sha256) and ``dispatched`` before the POST; a lost answer is ``unknown``
   and is settled by reading the conversation's events, never by sending again (``send_message``). A 429 (the
   message saved, the run not started) is not settled as sent: the attempt is ended as a provider interruption
   (``run-not-started``), so a new attempt is admissible (review S4);
4. **wait**: the conversation's recorded status read to a terminal one, bounded by a ceiling (``wait_for_turn``);
5. **RESULT**, only after a ``finished`` turn: one fixed command (``build_result``) that, in the container, makes a
   fresh git directory from the base bundle it carries, adds the workspace, takes out of the index by an explicit,
   reported rule any path with a ``.claude`` or ``.mcp.json`` component and any change under ``openspec/`` or
   ``backlog/`` (R3 as revised; ``EXCLUSION_RULE``), commits once (parent the base; the builder bot's identity, the
   store's time for the attempt and a message of the reserved record, R5), bundles ``refs/heads/work/<attempt id>``
   completely, hashes the bundle, then runs the accepted design's test command on an export of the committed tree
   (G5) and prints the bundle in the exchange delivery's frame; the API probe writes it into the guest exchange;
6. **intake**: ``pull(name)`` (``tools/guest.py`` ``exchange_pull``: the retained verifier, decision 0014 section 7
   row R6, git the first parser), then ``intake_result``: exactly the one reference, no prerequisite, the digest the
   command printed before the tests and the probe delivered, the commit id the host computes itself over the
   bundle's tree, and the tree policy (regular files only; no link, gitlink, ``.git``, ``.claude`` or ``.mcp.json``
   component, compared case-folded and normalized; ``openspec/`` and ``backlog/`` exactly the base's; bounded depth,
   entries and inflated size);
7. **close**: the runtime stopped and observed ``missing`` (``attempt_end.stop_runtime``, E-05.8's primitive); the
   result path's journal is slice B's (``reserve_result(record, verified)``, called last with the record's digests
   and the in-memory result). ``observe(phase, **facts)`` (slice C's observations) may return dispatcher records at
   ``before-message``, ``after-turn`` and ``after-result``: any record ends the attempt through
   ``end_interrupted_attempt`` and no result is handed on.

``resume_result`` resumes the result step of an attempt whose turn is confirmed (review S3): when the exchange already
holds the named bundle it re-runs RESULT without a delivery and pulls and verifies the bundle there (the commit-id
equality is the integrity check); otherwise it runs RESULT as ``run_attempt`` does. ``run_attempt`` never runs twice
on an attempt: a turn journal already present is TURN_ALREADY_SENT before any call.

What the trusted side accepts from an attempt: one git bundle, whose first parser is git and whose single commit is
byte for byte the commit the dispatcher specified over the tree the container produced; and text (the test output,
the excluded paths, API answers) handled as data and kept in memory only: every record holds its digest and size,
never the text (review S7), until slice B's outbound search has passed over it. The agent's own code runs inside
RESULT (the tests are its tests): it can influence the test status and output, never the commit, whose custody is
the host's commit-id equality and tree policy.

Assumptions stated: one dispatcher process (the builder registry and the held role tokens are its module state; no
second process runs an attempt of the same work item); the workspace's own ``.gitignore`` and ``.gitattributes``
apply to RESULT's ``git add -A`` (an ignored file is not committed; an attribute may convert line endings), which
the agent controls and the report must state as the design's accepted behaviour (review N1).

Standard library only; the base is read through the shared repository-access module (Dulwich, decision 0014), and
nothing here launches git on the host.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import re
import sys
import tarfile
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', HERE / 'dispatch_inputs.py')
AE = di._attempt_end()
store = di.store
DispatchRefused = di.DispatchRefused

TURN_KEY = 'dispatch/attempt/{attempt_id}/turn'
TURN_FORMAT = 'ai-engineering-harness/dispatch/attempt-turn/v1'
RESULT_FORMAT = 'ai-engineering-harness/dispatch/attempt-result/v2'
OUTCOME_FORMAT = 'ai-engineering-harness/dispatch/attempt-run/v2'

PROXY = '/api/conversations/{conversation_id}/{tail}'
COUNT_ROUTE = '/api/conversations/count'
WORKSPACE = '/workspace'
# R3 (revised by the A3 rulings): names compared per path component, Unicode-normalized (NFC), case-folded, with
# trailing dots and spaces stripped (review B1). RESULT excludes the first two from its commit and reports them; the
# host refuses a result tree, and SEED a base tree, holding any of them (.git: review N5).
FORBIDDEN_NAMES = frozenset(('.claude', '.mcp.json'))
TREE_FORBIDDEN = FORBIDDEN_NAMES | {'.git'}
# The directories whose content the result must leave exactly as the base holds it (review N7).
PROTECTED_DIRS = ('openspec', 'backlog')
TREE_MODE, FILE_MODE, EXEC_MODE, LINK_MODE, GITLINK_MODE = 0o040000, 0o100644, 0o100755, 0o120000, 0o160000
REGULAR_MODES = (FILE_MODE, EXEC_MODE)
MAX_HISTORY = 10000            # commits walked to find the design commit in the base's history
MAX_FILES = 5000               # entries of a seeded or a result tree
MAX_DEPTH = 64                 # directory depth of a seeded or a result tree (review S1)
MAX_INFLATED = 64 << 20        # the result tree's blobs, inflated, in all (review N4)
BASE_BRANCH = 'refs/heads/main'
HEX40 = re.compile(r'[0-9a-f]{40}')
ATTEMPT_ID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')   # store.attempt_id_for

# R5: the result commit's identity and message.
BOT_NAME, BOT_EMAIL = 'aieh-bot-builder', 'aieh-bot-builder@localhost.invalid'
TITLE_MAX = 200
# G5: the accepted design's test command (the change add-slugify's acceptance criterion, E-05.1's command), run by
# the RESULT command on an export of the committed tree.
TEST_COMMAND = 'python -m unittest discover -s tests'
TEST_LABEL = ('run by the dispatcher\'s fixed command in the attempt\'s container on an export of the committed '
              'tree; not independent CI. The agent\'s own code runs in it (the tests are its tests), so it can '
              'influence the test status and output; the commit\'s custody is the host\'s commit-id equality and tree '
              'policy, not this run')
EXCLUSION_RULE = ('RESULT takes out of its commit any path with a component that, NFC-normalized, case-folded and '
                  'without trailing dots and spaces, is .claude or .mcp.json, and any change under openspec/ or '
                  'backlog/ (left as the base holds them); each excluded path is reported')
TEST_TIMEOUT_S = 300
TEST_OUTPUT_BYTES = 65536      # the tail of the test run's output the command reports
SEED_TIMEOUT_S = 120
RESULT_TIMEOUT_S = di.COMMAND_MAX_TIMEOUT_S
TURN_CEILING_S = 3600          # a ceiling on the turn, not an expected duration
POLL_S = 10
TERMINAL = ('finished', 'error', 'stuck', 'paused', 'waiting_for_confirmation', 'deleting')
CLOCK = time.monotonic
RUN_NOT_STARTED = 429          # the Agent Server saved the message and did not start the run


def WAIT(seconds):
    """Wait until the next read is due (the poll's deadline): never a guessed sleep."""
    threading.Event().wait(seconds)


# The exchange delivery's frame (tools/guest.py EXCHANGE_PART_BEGIN, EXCHANGE_PART_END, EXCHANGE_PART_DELIVERED; a
# test holds them equal): the dispatch package imports nothing of tools/guest.py.
PART = 'bundle'
PART_BEGIN, PART_END, PART_DELIVERED = 'AIEH-EXCHANGE-PART', 'AIEH-EXCHANGE-END', 'AIEH-EXCHANGE-DELIVERED'


def _refused(code: str, detail: str, **context) -> DispatchRefused:
    return DispatchRefused(code, detail, **context)


def _digest(data: bytes) -> dict:
    """A text of the agent's held as its digest and size only (review S7)."""
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def folded(component: str) -> str:
    """A path component as the R3 names are compared: NFC, case-folded, trailing dots and spaces stripped."""
    return unicodedata.normalize('NFC', component).casefold().rstrip(' .')


def forbidden_component(path: str, names=FORBIDDEN_NAMES) -> bool:
    return any(folded(part) in names for part in path.split('/'))


# ---------------------------------------------------------------------------
# The base: the approved repository's branch head, read through the repository-access module

@dataclass(frozen=True)
class Base:
    """The approved repository at its branch head: the commit, its tree's files (path, mode, bytes, sorted), the
    design commit it was checked to contain, and a complete bundle of the branch (for the RESULT command)."""
    repository: str
    ref: str
    commit: str
    tree: str
    design_commit: str
    files: tuple
    bundle: bytes = field(repr=False)

    @cached_property
    def payload(self) -> bytes:
        """The seeded tree as a deterministic gzipped tar: sorted regular files, 0644 or 0755, owner 0, time 0."""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as tar:
            for path, mode, data in self.files:
                info = tarfile.TarInfo(path)
                info.size, info.mode, info.mtime = len(data), 0o755 if mode == EXEC_MODE else 0o644, 0
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                tar.addfile(info, io.BytesIO(data))
        return gzip.compress(buffer.getvalue(), compresslevel=9, mtime=0)

    @property
    def seed_sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    @cached_property
    def protected(self) -> frozenset:
        """(path, mode, blob id) of every base file under PROTECTED_DIRS."""
        return frozenset((p, m, object_id('blob', d)) for p, m, d in self.files if p.split('/')[0] in PROTECTED_DIRS)

    def summary(self) -> dict:
        return {'repository': self.repository, 'ref': self.ref, 'commit': self.commit,
                'seed': {'sha256': self.seed_sha256, 'files': len(self.files)}}


def _repository_access():
    return di.planning.repository_access


class TreeBound(ValueError):
    """A tree beyond MAX_DEPTH or MAX_FILES; ``reason`` is ``too-deep`` or ``too-many``."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _parse_tree(repository, oid: str):
    found = repository.read(oid)
    if found is None or found[1] != 'tree':
        raise ValueError(f'{oid} is not a tree')
    return _repository_access().dulwich_modules().objects.parse_tree(found[2], len(oid) // 2)


def tree_entries(repository, tree: str) -> list[tuple[str, int, str]]:
    """Every non-tree entry below TREE as (path, mode, oid), walked iteratively (no recursion), at most MAX_DEPTH
    deep and MAX_FILES entries (TreeBound otherwise)."""
    out, pending = [], [(tree, '', 0)]
    while pending:
        oid, prefix, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise TreeBound('too-deep')
        for name, mode, child in _parse_tree(repository, oid):
            name, child = name.decode('utf-8', 'surrogateescape'), child.decode('ascii')
            path = f'{prefix}/{name}' if prefix else name
            if mode == TREE_MODE:
                pending.append((child, path, depth + 1))
            else:
                out.append((path, mode, child))
            if len(out) + len(pending) > MAX_FILES:
                raise TreeBound('too-many')
    return sorted(out)


def tree_problems(entries, names=TREE_FORBIDDEN) -> list[dict]:
    """R3 and the design's tree policy: each entry that is not a regular file (a symbolic link, a gitlink or any
    other mode) or that has a forbidden name (NAMES, compared as ``folded``) as any component of its path."""
    problems = []
    for path, mode, _ in entries:
        if forbidden_component(path, names):
            problems.append({'path': path, 'reason': 'forbidden-name'})
        elif mode == LINK_MODE:
            problems.append({'path': path, 'reason': 'link'})
        elif mode == GITLINK_MODE:
            problems.append({'path': path, 'reason': 'gitlink'})
        elif mode not in REGULAR_MODES:
            problems.append({'path': path, 'reason': f'mode {mode:o}'})
    return problems


def _commit_header(raw: bytes) -> tuple[str, list[str]]:
    """(tree, parents) of a raw commit object."""
    head = raw.split(b'\n\n', 1)[0].decode('utf-8', 'replace').split('\n')
    tree = head[0][len('tree '):] if head and head[0].startswith('tree ') else ''
    return tree, [line[len('parent '):] for line in head[1:] if line.startswith('parent ')]


def contains(repository, head: str, commit: str) -> bool:
    """Whether COMMIT is HEAD or one of its ancestors (at most MAX_HISTORY commits walked)."""
    seen, stack = set(), [head]
    while stack and len(seen) <= MAX_HISTORY:
        current = stack.pop()
        if current in seen:
            continue
        if current == commit:
            return True
        seen.add(current)
        found = repository.read(current)
        if found is None or found[1] != 'commit':
            raise ValueError(f'{current} is not a commit')
        stack.extend(_commit_header(found[2])[1])
    return False


def read_base(project, *, repository: str, design_commit: str, ref: str = BASE_BRANCH) -> Base:
    """The approved REPOSITORY's base from its project clone PROJECT (the work source's own clone), opened under the
    planning adapter's configuration policy: REF's commit, which must contain DESIGN_COMMIT (BASE_LACKS_DESIGN), its
    tree's files, refused when one is not a regular file or has a forbidden name, .git included (SEED_TREE_REFUSED,
    R3, review N5), or the tree is beyond its bounds, and a complete bundle of REF. BASE_UNAVAILABLE when it cannot
    be read."""
    if not isinstance(design_commit, str) or HEX40.fullmatch(design_commit) is None:
        raise _refused('BASE_UNAVAILABLE', 'the design commit is not a full commit id')
    ra = _repository_access()
    try:
        opened = di.planning.open_project(project)
    except di.planning.CannotRun as exc:
        raise _refused('BASE_UNAVAILABLE', f'the project clone cannot be opened ({exc})') from None
    try:
        with tempfile.TemporaryDirectory(prefix='aieh-base-') as scratch:
            commit = opened.commit(ref)
            if commit is None or HEX40.fullmatch(commit) is None:
                raise _refused('BASE_UNAVAILABLE', f'{ref} names no commit of the project clone')
            if not contains(opened, commit, design_commit):
                raise _refused('BASE_LACKS_DESIGN', f'{ref} at {commit} does not contain the accepted design commit '
                               f'{design_commit}', base=commit, design=design_commit)
            tree, _ = _commit_header(opened.read(commit)[2])
            try:
                entries = tree_entries(opened, tree)
            except TreeBound as bound:
                raise _refused('SEED_TREE_REFUSED', f'the base tree is {bound.reason}',
                               problems=[{'path': '', 'reason': bound.reason}]) from None
            problems = tree_problems(entries)
            if problems:
                raise _refused('SEED_TREE_REFUSED', f'the base tree holds {len(problems)} entr(ies) that are not '
                               'regular files or have a forbidden name', problems=problems[:20])
            files = tuple((path, mode, opened.read(oid)[2]) for path, mode, oid in entries)
            header = opened.write_bundle([ref], Path(scratch) / 'base.bundle')
            if header.get('prerequisites') or [r for _, r in header.get('refs') or []] != [ref]:
                raise _refused('BASE_UNAVAILABLE', 'the base bundle is not one complete reference')
            bundle = (Path(scratch) / 'base.bundle').read_bytes()
    except (ra.RepositoryError, ValueError, OSError, TypeError, RecursionError) as exc:
        raise _refused('BASE_UNAVAILABLE', f'the base cannot be read: {type(exc).__name__}: '
                       f'{getattr(exc, "code", exc)}') from None
    finally:
        opened.close()
    return Base(repository=repository, ref=ref, commit=commit, tree=tree, design_commit=design_commit,
                files=tuple(sorted(files)), bundle=bundle)


# ---------------------------------------------------------------------------
# SEED and RESULT: the two builders of the command tail (golden-tested texts; no single quote in either script)

SEED_SCRIPT = r"""import hashlib, io, os, sys, tarfile
data = bytes.fromhex(sys.stdin.read().strip())
if hashlib.sha256(data).hexdigest() != sys.argv[2]:
    print("AIEH-SEED failed digest")
    sys.exit(3)
os.makedirs(sys.argv[1])
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
    count = sum(1 for member in tar.getmembers() if member.isfile())
    tar.extractall(sys.argv[1], filter="data")
print("AIEH-SEED ok", sys.argv[2], count)
"""

RESULT_SCRIPT = r"""import hashlib, json, os, shutil, subprocess, sys, tempfile, unicodedata
p = json.loads(bytes.fromhex(sys.stdin.read().strip()).decode("utf-8"))
work = os.path.abspath(sys.argv[1])
root = tempfile.mkdtemp(prefix="aieh-result-")
gd = os.path.join(root, "git")
keep = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ}
ident = {"GIT_AUTHOR_NAME": p["name"], "GIT_AUTHOR_EMAIL": p["email"], "GIT_AUTHOR_DATE": p["date"],
         "GIT_COMMITTER_NAME": p["name"], "GIT_COMMITTER_EMAIL": p["email"], "GIT_COMMITTER_DATE": p["date"]}
env = dict(keep, HOME=root, LC_ALL="C", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
           GIT_TERMINAL_PROMPT="0", GIT_DIR=gd, GIT_WORK_TREE=work, **ident)


def say(*words):
    print("AIEH-RESULT", *words, flush=True)


def stop(step, err=b""):
    say("failed", step, (err or b"")[-2000:].hex())
    sys.exit(3)


def git(step, *args, data=None, over=None, raw=False):
    done = subprocess.run(["git", "-c", "safe.directory=*", *args], input=data, capture_output=True,
                          env=over or env)
    if done.returncode != 0:
        stop(step, done.stderr)
    return done.stdout if raw else done.stdout.decode("ascii", "replace").strip()


def entries(text, at):
    out = {}
    for item in text.split(b"\0"):
        if item:
            meta, _, path = item.partition(b"\t")
            words = meta.split()
            out[path] = (words[0].decode(), words[at].decode())
    return out


def folded(part):
    return unicodedata.normalize("NFC", part.decode("utf-8", "surrogateescape")).casefold().rstrip(" .")


bundle = os.path.join(root, "base.bundle")
with open(bundle, "wb") as handle:
    handle.write(bytes.fromhex(p["bundle"]))
git("init", "init", "-q")
for key, value in (("core.bare", "false"), ("core.autocrlf", "false"), ("core.fileMode", "false"),
                   ("core.symlinks", "true"), ("gc.auto", "0"), ("commit.gpgSign", "false")):
    git("config", "config", key, value)
git("fetch", "fetch", "-q", "--no-tags", bundle, p["base_ref"] + ":refs/aieh/base")
if git("base", "rev-parse", "--verify", "refs/aieh/base^{commit}") != p["base"]:
    stop("base")
git("read-tree", "read-tree", p["base"])
git("add", "add", "-A")
index = entries(git("exclude", "ls-files", "-s", "-z", raw=True), 1)
based = entries(git("exclude", "ls-tree", "-r", "-z", "--full-tree", p["base"], raw=True), 2)
drop, put, excluded = [], [], []
for path in sorted(set(index) | set(based)):
    parts = path.split(b"/")
    if any(folded(part) in p["forbidden"] for part in parts):
        if path in index:
            drop.append(path)
            excluded.append({"path": path.decode("utf-8", "replace"), "reason": "forbidden-name"})
    elif parts[0].decode("utf-8", "replace") in p["protected"] and index.get(path) != based.get(path):
        if path in index:
            drop.append(path)
        if path in based:
            put.append(path)
        excluded.append({"path": path.decode("utf-8", "replace"), "reason": "protected-dir"})
if drop or put:
    lines = [b"0 " + b"0" * 40 + b"\t" + path for path in drop]
    lines += [(based[path][0] + " " + based[path][1]).encode() + b"\t" + path for path in put]
    git("exclude", "update-index", "-z", "--index-info", data=b"\0".join(lines) + b"\0")
tree = git("write-tree", "write-tree")
commit = git("commit", "commit-tree", tree, "-p", p["base"], data=p["message"].encode("utf-8"))
git("ref", "update-ref", p["ref"], commit)
out = os.path.join(root, "result.bundle")
git("bundle", "bundle", "create", "-q", out, p["ref"])
with open(out, "rb") as handle:
    data = handle.read()
digest = hashlib.sha256(data).hexdigest()
export = os.path.join(root, "export")
os.mkdir(export)
xenv = dict(env, GIT_WORK_TREE=export, GIT_INDEX_FILE=os.path.join(root, "export.index"))
git("export", "read-tree", commit, over=xenv)
git("export", "checkout-index", "-a", "-f", over=xenv)
say("base", p["base"])
say("tree", tree)
say("commit", commit)
say("excluded", json.dumps(excluded, sort_keys=True).encode("utf-8").hex())
say("bundle", digest, len(data))
try:
    run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=export,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=p["test_timeout"], env=dict(keep, HOME=export, PYTHONDONTWRITEBYTECODE="1"))
    status, output = str(run.returncode), run.stdout
except subprocess.TimeoutExpired as exc:
    status, output = "timeout", exc.output or b""
say("tests", status)
say("test-output", output[-p["output_limit"]:].hex())
if p["frame"]:
    print(p["part_begin"], p["part"], digest, len(data))
    hexed = data.hex()
    for start in range(0, len(hexed), 76):
        print(hexed[start:start + 76])
    print(p["part_end"], p["part"])
say("done")
shutil.rmtree(root, ignore_errors=True)
"""
if "'" in SEED_SCRIPT or "'" in RESULT_SCRIPT:   # each travels in single quotes in the command's text
    raise AssertionError('a builder script holds a single quote')


def workspace_of(repository: str) -> str:
    if not isinstance(repository, str) or di.ID_RE.fullmatch(repository) is None:
        raise _refused('MESSAGE_SLOT_UNRESOLVED', f'not a repository id: {repository!r}')
    return f'{WORKSPACE}/{repository}'


@di.command_builder('d1-seed')
def build_seed(base: Base) -> dict:
    """SEED: the base's tree into ``/workspace/<repository>``, a new directory (an existing one fails the command),
    from a gzipped tar in the command's text, hex-encoded, its sha256 checked in the container; tarfile's data filter
    (no absolute path, no path out of the directory, no link out of it, no device). Prints ``AIEH-SEED ok <sha256>
    <files>``."""
    return {'command': f"printf %s '{base.payload.hex()}' | python -c '{SEED_SCRIPT}' "
                       f"'{workspace_of(base.repository)}' '{base.seed_sha256}'",
            'timeout': SEED_TIMEOUT_S}


def result_name(attempt_id: str) -> str:
    return f'work-{attempt_id}.bundle'


def result_ref(attempt_id: str) -> str:
    return f'refs/heads/work/{attempt_id}'


@di.command_builder('d1-result')
def build_result(base: Base, *, attempt_id: str, message: str, when: int, deliver: bool = True) -> dict:
    """RESULT: one commit of ``/workspace/<repository>`` on a fresh git directory the command brings (from the base
    bundle in its text), under EXCLUSION_RULE, bundled and, with DELIVER, delivered into the guest exchange as
    ``work-<attempt id>.bundle``; the accepted design's test command on an export of the committed tree. Without
    DELIVER (a resumed result step whose bundle is already in the exchange) no frame is printed. Every value in the
    command's text is hex-encoded JSON, from the base, the reserved record (``commit_message``) and the store's time
    (``attempt_time``)."""
    if not isinstance(attempt_id, str) or ATTEMPT_ID_RE.fullmatch(attempt_id) is None:
        raise _refused('TAIL_BODY_INVALID', 'not an attempt id')
    if type(when) is not int or when <= 0:
        raise _refused('TAIL_BODY_INVALID', 'the commit time is not a positive integer of seconds')
    if type(deliver) is not bool:
        raise _refused('TAIL_BODY_INVALID', 'deliver is a bool')
    params = {'base': base.commit, 'base_ref': base.ref, 'bundle': base.bundle.hex(), 'ref': result_ref(attempt_id),
              'name': BOT_NAME, 'email': BOT_EMAIL, 'date': f'{when} +0000', 'message': message,
              'test_timeout': TEST_TIMEOUT_S, 'output_limit': TEST_OUTPUT_BYTES, 'part': PART,
              'part_begin': PART_BEGIN, 'part_end': PART_END, 'frame': deliver,
              'forbidden': sorted(FORBIDDEN_NAMES), 'protected': list(PROTECTED_DIRS)}
    payload = json.dumps(params, sort_keys=True, separators=(',', ':')).encode('utf-8').hex()
    made = {'command': f"printf %s '{payload}' | python -c '{RESULT_SCRIPT}' '{workspace_of(base.repository)}'",
            'timeout': RESULT_TIMEOUT_S}
    if deliver:
        made['deliver'] = {'part': PART, 'name': result_name(attempt_id)}
    return made


# ---------------------------------------------------------------------------
# The message: one frame in dispatcher code (G4)

FRAME_VERSION = 'aieh-d1-message/v2'
FRAME = """You are the implementing agent for one task of the repository in {workdir}.

Task: {work_id}. Its Backlog.md file is {workdir}/{task_file}.
Design: the accepted OpenSpec change {change}, in {workdir}/openspec/changes/{change}/.

1. Read the task file and the change's files, then implement the change as designed, in {workdir}.
2. Run the accepted design's test command there, offline, with what this container holds: {test_command}
3. Do not change anything under backlog/ or openspec/: Backlog.md alone owns the task's status, and the accepted \
design is bound by its acceptance. Changes there are left out of the result.
4. Do not create .claude or .mcp.json files or directories anywhere in {workdir}: they are left out of the result.
5. Do not commit and do not push: the dispatcher records the result from the files you leave in {workdir}.
"""
WORK_ID_RE = re.compile(r'[A-Za-z][A-Za-z0-9]*-[0-9]{1,9}')
SLOT_PATH_RE = re.compile(r'[A-Za-z0-9 ()._,+-]+(?:/[A-Za-z0-9 ()._,+-]+)*')


def _design(resolved) -> dict:
    design = resolved.policy_inputs.get('design') if isinstance(resolved.policy_inputs, dict) else None
    if not isinstance(design, dict) or not isinstance(design.get('change'), str) \
            or di.CHANGE_RE.fullmatch(design['change']) is None or not isinstance(design.get('commit'), str):
        raise _refused('MESSAGE_SLOT_UNRESOLVED', 'the reserved record names no accepted design')
    return design


def task_file(base: Base, work_id: str) -> str:
    """The one Backlog.md task file of WORK_ID in the seeded tree: ``backlog/tasks/<work id, lower case> - <title>.md``."""
    prefix = f'backlog/tasks/{work_id.lower()} - '
    found = [p for p, _, _ in base.files if p.lower().startswith(prefix) and p.endswith('.md') and p.count('/') == 2]
    if len(found) != 1 or SLOT_PATH_RE.fullmatch(found[0]) is None:
        raise _refused('MESSAGE_SLOT_UNRESOLVED', f'the seeded tree holds {len(found)} task file(s) of {work_id} in '
                       'its grammar, not one')
    return found[0]


def task_title(base: Base, path: str) -> str:
    """The ``title:`` of the task file's front matter: one line of printable text, at most TITLE_MAX characters."""
    data = next(d for p, _, d in base.files if p == path).decode('utf-8', 'replace')
    lines = data.split('\n')
    front = lines[1:lines.index('---', 1)] if lines and lines[0] == '---' and '---' in lines[1:] else []
    titles = [line[len('title:'):].strip() for line in front if line.startswith('title:')]
    title = titles[0] if len(titles) == 1 else ''
    if len(title) >= 2 and title[0] == title[-1] and title[0] in '\'"':
        title = title[1:-1].replace("''", "'") if title[0] == "'" else title[1:-1]
    if not title or len(title) > TITLE_MAX or not title.isprintable():
        raise _refused('MESSAGE_SLOT_UNRESOLVED', f'the task file {path} holds no one-line title of at most '
                       f'{TITLE_MAX} printable characters')
    return title


def build_message(resolved, base: Base) -> str:
    """The frame with its slots filled: the repository, the work id and the change from the reserved record, the
    task file and the change folder from the seeded tree (each must be there); nothing the conversation wrote."""
    if WORK_ID_RE.fullmatch(resolved.work_id or '') is None:
        raise _refused('MESSAGE_SLOT_UNRESOLVED', f'not a work id: {resolved.work_id!r}')
    change = _design(resolved)['change']
    if not any(p.startswith(f'openspec/changes/{change}/') for p, _, _ in base.files):
        raise _refused('MESSAGE_SLOT_UNRESOLVED', f'the seeded tree holds no openspec/changes/{change}/')
    return FRAME.format(workdir=workspace_of(resolved.repository), work_id=resolved.work_id,
                        task_file=task_file(base, resolved.work_id), change=change, test_command=TEST_COMMAND)


def message_body(text: str) -> dict:
    return {'role': 'user', 'content': [{'type': 'text', 'text': text}], 'run': True}


def commit_message(resolved, base: Base, attempt_id: str) -> str:
    """R5: ``<task id>: <task title>``, then the trailers Task, Attempt, Outcome and Design, from the reserved record
    and the base's task file."""
    title = task_title(base, task_file(base, resolved.work_id))
    return (f'{resolved.work_id}: {title}\n\nTask: {resolved.work_id}\nAttempt: {attempt_id}\n'
            f'Outcome: {resolved.outcome_ref}\nDesign: {resolved.design_revision}\n')


def attempt_time(integration_store, operation_key: str) -> int:
    """The store's time for the attempt (R5, the dispatcher's time): its ``confirmed`` transition's, in whole seconds
    since the epoch, so a resumed RESULT makes the same commit."""
    for event in reversed(integration_store.events(operation_key)):
        if event.to_state == 'confirmed':
            moment = datetime.fromisoformat(event.recorded_at.replace('Z', '+00:00'))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return int(moment.timestamp())
    raise _refused('ATTEMPT_NOT_CONFIRMED', f'{operation_key} has no confirmed transition')


@dataclass(frozen=True)
class Prepared:
    """Everything the run sends, built before anything is sent (review S2)."""
    text: str
    message: str
    when: int
    seed: object
    result: object


def prepare(resolved, base: Base, attempt_id: str, when: int, *, deliver: bool = True) -> Prepared:
    text = build_message(resolved, base)
    message = commit_message(resolved, base, attempt_id)
    return Prepared(text=text, message=message, when=when, seed=build_seed(base),
                    result=build_result(base, attempt_id=attempt_id, message=message, when=when, deliver=deliver))


# ---------------------------------------------------------------------------
# The turn journal and the message

def _message_texts(event) -> list[str]:
    message = event.get('llm_message') if isinstance(event, Mapping) else None
    content = message.get('content') if isinstance(message, Mapping) else None
    return [part['text'] for part in content or () if isinstance(part, Mapping) and isinstance(part.get('text'), str)]


def message_received(client, conversation_id: str, message_sha256: str) -> bool:
    """Whether the conversation's recorded events hold the user message whose text has MESSAGE_SHA256."""
    _, events = AE.observe(client, conversation_id)
    return any(isinstance(e, Mapping) and e.get('kind') == 'MessageEvent' and e.get('source') == 'user'
               and any(hashlib.sha256(t.encode('utf-8')).hexdigest() == message_sha256 for t in _message_texts(e))
               for e in events)


def turn_intent(operation_key: str, base: Base, text: str) -> dict:
    return {'format': TURN_FORMAT, 'operationKey': operation_key, 'attemptId': store.attempt_id_for(operation_key),
            'conversationId': store.conversation_id_for(operation_key),
            'base': {'repository': base.repository, 'ref': base.ref, 'commit': base.commit},
            'seed': {'sha256': base.seed_sha256, 'files': len(base.files)}, 'frame': FRAME_VERSION,
            'messageSha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def send_message(integration_store, operation_key: str, client, base: Base, text: str, *, actor: str) -> dict:
    """The one message of the attempt: the turn journal reserved with its intent (TURN_CONFLICT for another one),
    ``dispatched`` immediately before the one POST, ``confirmed`` with the answer's status. A journal already past
    ``reserved`` is TURN_ALREADY_SENT with zero calls: the message is never sent twice. A lost answer (no answer or a
    5xx) is ``unknown`` and is settled only by reading the conversation's events (``reconcile_turn``). A 429 (the
    message saved, the run not started) is ``failed`` and TURN_RUN_NOT_STARTED: never settled as sent (review S4)."""
    body = message_body(text)
    di.TAIL_GRAMMARS[di.MESSAGE_TAIL](body)                 # the client's own grammar, before anything is recorded
    intent = turn_intent(operation_key, base, text)
    key = TURN_KEY.format(attempt_id=intent['attemptId'])
    try:
        held = integration_store.reserve(key, intent, actor=actor).reservation
    except store.ConflictingReservation:
        raise _refused('TURN_CONFLICT', f'the turn journal of {intent["attemptId"]} holds another base, seed, frame '
                       'or message') from None
    if held.state != 'reserved':
        raise _refused('TURN_ALREADY_SENT', f'the turn journal is {held.state}: the message is never sent again',
                       state=held.state)
    di._mark(integration_store, key, 'reserved', 'dispatched', actor, 'send-message', None)
    params = {'conversation_id': intent['conversationId'], 'tail': di.MESSAGE_TAIL}
    try:
        answer = client.call('POST', PROXY, params=params, body=body)
    except DispatchRefused as refusal:          # refused before the transport: nothing was sent
        di._mark(integration_store, key, 'dispatched', 'failed', actor, refusal.code, {'code': refusal.code})
        raise
    except Exception as exc:  # noqa: BLE001 - no answer: it may have been received
        di._mark(integration_store, key, 'dispatched', 'unknown', actor, 'no-answer', {'error': type(exc).__name__})
        return reconcile_turn(integration_store, operation_key, client, actor=actor)
    status = answer.get('status') if isinstance(answer, Mapping) else None
    if type(status) is int and 200 <= status < 300:
        di._mark(integration_store, key, 'dispatched', 'confirmed', actor, 'sent', {'status': status})
    elif status == RUN_NOT_STARTED:
        di._mark(integration_store, key, 'dispatched', 'failed', actor, 'run-not-started', {'status': status})
        raise _refused('TURN_RUN_NOT_STARTED', 'the Agent Server answered 429: the message is saved and the run did '
                       'not start; it is not settled as sent', status=status)
    elif type(status) is int and 400 <= status < 500:
        di._mark(integration_store, key, 'dispatched', 'failed', actor, 'refused', {'status': status})
        raise _refused('TURN_REFUSED', f'the message was answered {status}', status=status)
    else:
        di._mark(integration_store, key, 'dispatched', 'unknown', actor, 'unsettled', {'status': status})
        return reconcile_turn(integration_store, operation_key, client, actor=actor)
    return turn_record(integration_store, operation_key)


def reconcile_turn(integration_store, operation_key: str, client, *, actor: str) -> dict:
    """Settle an ``unknown`` turn journal by reading the conversation's events: the message is there (``confirmed``,
    reconciled) or TURN_UNRECONCILED, the journal left ``unknown``. Nothing is ever sent again."""
    attempt_id = store.attempt_id_for(operation_key)
    key = TURN_KEY.format(attempt_id=attempt_id)
    held = integration_store.get(key)
    if held is None or held.state != 'unknown':
        raise _refused('TURN_ALREADY_SENT', f'the turn journal is {getattr(held, "state", None)}, not unknown')
    intent = json.loads(held.intent_json)
    if message_received(client, intent['conversationId'], intent['messageSha256']):
        di._mark(integration_store, key, 'unknown', 'confirmed', actor, 'reconciled-from-events', {'status': None})
        return turn_record(integration_store, operation_key)
    raise _refused('TURN_UNRECONCILED', 'the message\'s answer was lost and the conversation\'s events do not hold '
                   'it: nothing is sent again')


def turn_record(integration_store, operation_key: str) -> dict:
    held = integration_store.get(TURN_KEY.format(attempt_id=store.attempt_id_for(operation_key)))
    return {'state': held.state, 'intent': json.loads(held.intent_json)} if held else None


def wait_for_turn(client, conversation_id: str, *, ceiling_s: float = TURN_CEILING_S, poll_s: float = POLL_S,
                  clock: Callable[[], float] = None, wait: Callable[[float], None] = None) -> str:
    """The conversation's recorded execution status once it is no longer idle or running (TERMINAL), read through
    the client (``GET /api/conversations/{id}``, the persisted catalog) until the ceiling: TURN_CEILING then. The
    wait between reads is bounded by the next read's due time and the ceiling."""
    clock, wait = clock or CLOCK, wait or WAIT
    deadline = clock() + ceiling_s
    while True:
        status, execution = conversation_status(client, conversation_id)
        if execution in TERMINAL:
            return execution
        remaining = deadline - clock()
        if remaining <= 0:
            raise _refused('TURN_CEILING', f'the turn is still {execution} after {ceiling_s} s', status=execution)
        wait(min(poll_s, remaining))


def conversation_status(client, conversation_id: str) -> tuple[int, str]:
    status, body = AE._answer(client, 'GET', AE.CONVERSATION_ROUTE, conversation_id, 'CONVERSATION_UNOBSERVED',
                              'the conversation')
    execution = body.get('execution_status') if isinstance(body, Mapping) else None
    if status != 200 or execution not in AE.EXECUTION_STATUSES:
        raise _refused('CONVERSATION_UNOBSERVED', f'the conversation answered {status} without its status',
                       status=status)
    return status, execution


# ---------------------------------------------------------------------------
# The inspection (E-01.3.2's API half; the container facts are slice C's hook)

def inspect_conversation(client, conversation_id: str) -> list[str]:
    """The API half of the inspection before any work: exactly one conversation on the server, the reserved one, and
    its runtime running. Each problem as a sentence; [] when it holds."""
    problems = []
    status, body = _plain(client, 'GET', COUNT_ROUTE)
    if status != 200 or type(body) is not int or body != 1:
        problems.append(f'the server holds {body!r} conversations (HTTP {status}), not exactly one')
    status, body = AE._answer(client, 'GET', AE.CONVERSATION_ROUTE, conversation_id, 'INSPECTION_FAILED',
                              'the conversation')
    if status != 200 or not isinstance(body, Mapping) or body.get('id') != conversation_id:
        problems.append(f'the conversation answered {status} without the reserved id')
    runtime = AE.runtime_status(client, conversation_id, 'INSPECTION_FAILED')
    if runtime != 'running':
        problems.append(f'the runtime is {runtime!r}, not running')
    return problems


def _plain(client, method: str, route: str):
    """A route without parameters, through the client: (status, body), INSPECTION_FAILED with no answer."""
    try:
        answer = client.call(method, route)
    except DispatchRefused:
        raise
    except Exception as exc:  # noqa: BLE001 - no answer: nothing is inferred
        raise _refused('INSPECTION_FAILED', f'{method} {route}: no answer ({type(exc).__name__})') from None
    status = answer.get('status') if isinstance(answer, Mapping) else None
    return status, answer.get('body') if isinstance(answer, Mapping) else None


def _command(client, conversation_id: str, command, code: str) -> Mapping:
    """One built command through the client; no answer (a raw OSError or a transport error) is CODE (review S3)."""
    try:
        answer = client.call('POST', PROXY, params={'conversation_id': conversation_id, 'tail': di.COMMAND_TAIL},
                             body=command)
    except DispatchRefused:
        raise
    except Exception as exc:  # noqa: BLE001 - no answer: the command may or may not have run
        raise _refused(code, f'the {command.builder} command was not answered ({type(exc).__name__}); its step is '
                       'resumed, never assumed', error=type(exc).__name__) from None
    return answer if isinstance(answer, Mapping) else {}


# ---------------------------------------------------------------------------
# The result: the command's answer, then the host's intake of the pulled bundle

LINE_RE = re.compile(r'AIEH-RESULT (base|tree|commit) ([0-9a-f]{40})|AIEH-RESULT tests (-?[0-9]{1,5}|timeout)'
                     r'|AIEH-RESULT (test-output|excluded) ([0-9a-f]*)|AIEH-RESULT (done)'
                     r'|AIEH-RESULT failed ([a-z-]{1,32}) ([0-9a-f]*)|AIEH-RESULT bundle ([0-9a-f]{64}) ([0-9]{1,12})'
                     r'|AIEH-EXCHANGE-DELIVERED bundle ([0-9a-f]{64}) ([0-9]{1,12})')
RESULT_MARKERS = ('base', 'tree', 'commit', 'excluded', 'bundle', 'tests', 'test-output', 'done')


def parse_result(answer, *, delivered_expected: bool = True) -> dict:
    """The RESULT command's answer: its printed base, tree, commit, excluded paths, bundle digest, test status and
    output, and the probe's ``delivered``. The command exits 0 (review S8); each marker line once; a ``failed`` line,
    a missing or repeated marker, a delivery error, or a delivery that is not the printed bundle digest, is
    RESULT_COMMAND_FAILED. Agent-controlled text (the test output, the excluded paths, a failed step's stderr) is
    returned in memory; a refusal carries only its digest (review S7)."""
    body = answer.get('body') if isinstance(answer, Mapping) else None
    stdout = body.get('stdout') if isinstance(body, Mapping) else None
    delivered = answer.get('delivered') if isinstance(answer, Mapping) else None
    if answer.get('status') != 200 or not isinstance(stdout, str):
        raise _refused('RESULT_COMMAND_FAILED', f'the result command answered {answer.get("status")} without its '
                       'output', delivered=di._json_value(delivered))
    found: dict = {}
    for line in stdout.splitlines():
        match = LINE_RE.fullmatch(line.strip())
        if match is None:
            continue
        if match.group(7):
            raise _refused('RESULT_COMMAND_FAILED', f'the result command failed at {match.group(7)}',
                           step=match.group(7), stderr=_digest(bytes.fromhex(match.group(8))))
        if match.group(1):
            name, value = match.group(1), match.group(2)
        elif match.group(3):
            name, value = 'tests', match.group(3)
        elif match.group(4):
            name, value = match.group(4), match.group(5)
        elif match.group(6):
            name, value = 'done', 'done'
        elif match.group(9):
            name, value = 'bundle', (match.group(9), int(match.group(10)))
        else:
            name, value = 'delivered', (match.group(11), int(match.group(12)))
        if name in found:
            raise _refused('RESULT_COMMAND_FAILED', f'the result output repeats {name}')
        found[name] = value
    missing = [n for n in RESULT_MARKERS + (('delivered',) if delivered_expected else ()) if n not in found]
    if missing:
        raise _refused('RESULT_COMMAND_FAILED', f'the result output lacks {missing}',
                       delivered=di._json_value(delivered))
    if body.get('exit_code') != 0:
        raise _refused('RESULT_COMMAND_FAILED', 'the result command did not exit 0',
                       exit_code=di._json_value(body.get('exit_code')))
    if delivered_expected and (not isinstance(delivered, Mapping) or 'error' in delivered
                               or (delivered.get('sha256'), delivered.get('size')) != found['delivered']
                               or found['delivered'] != found['bundle']):
        raise _refused('RESULT_COMMAND_FAILED', 'the bundle was not delivered into the exchange as printed before '
                       'the tests ran', delivered=di._json_value(delivered))
    output = bytes.fromhex(found['test-output'])
    excluded_raw = bytes.fromhex(found['excluded'])
    try:
        excluded = json.loads(excluded_raw.decode('utf-8'))
        if not isinstance(excluded, list) or not all(isinstance(e, dict) and set(e) == {'path', 'reason'}
                                                     and e['reason'] in ('forbidden-name', 'protected-dir')
                                                     and isinstance(e['path'], str) for e in excluded):
            raise ValueError
    except ValueError:
        raise _refused('RESULT_COMMAND_FAILED', 'the excluded paths are not the command\'s list') from None
    printed = {'base': found['base'], 'tree': found['tree'], 'commit': found['commit'],
               'bundle': {'sha256': found['bundle'][0], 'size': found['bundle'][1]},
               'tests': {'status': found['tests'], 'output': _data_text(output.decode('utf-8', 'replace')),
                         'output_digest': _digest(output), 'command': TEST_COMMAND, 'label': TEST_LABEL},
               'excluded': excluded, 'excluded_digest': _digest(excluded_raw)}
    if delivered_expected:
        printed['delivered'] = {'name': delivered.get('name'), 'sha256': delivered['sha256'],
                                'size': delivered['size']}
    return printed


def _data_text(text: str) -> str:
    """Text kept as data: control characters but newline and tab removed."""
    return ''.join(c for c in text if c in '\n\t' or c.isprintable())


def expected_commit(tree: str, base: str, message: str, when: int) -> bytes:
    """The raw commit object the dispatcher specifies over TREE: parent the base, the builder bot as author and
    committer at the store's time, the message; nothing else."""
    identity = f'{BOT_NAME} <{BOT_EMAIL}> {when} +0000'
    return (f'tree {tree}\nparent {base}\nauthor {identity}\ncommitter {identity}\n\n{message}').encode('utf-8')


def object_id(kind: str, raw: bytes) -> str:
    return hashlib.sha1(b'%s %d\x00' % (kind.encode('ascii'), len(raw)) + raw, usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class VerifiedResult:
    """A result the host accepted: the bundle's one commit, equal to the specified one, over a tree of regular
    files. ``tests`` (with its output) and ``excluded`` (the paths RESULT left out) are agent-controlled text, held
    in memory only: ``to_json`` (every record) holds their digests and sizes (review S7)."""
    attempt_id: str
    conversation_id: str
    repository: str
    base: str
    commit: str
    tree: str
    ref: str
    bundle_sha256: str
    bundle_bytes: int
    staged: str
    verify_repo: str
    files: int
    inflated_bytes: int
    tests: dict = field(repr=False)
    excluded: tuple = field(repr=False)
    excluded_digest: dict = field(default_factory=dict)
    resumed: bool = False

    def to_json(self) -> dict:
        return {'format': RESULT_FORMAT, 'attemptId': self.attempt_id, 'conversationId': self.conversation_id,
                'repository': self.repository, 'base': self.base, 'commit': self.commit, 'tree': self.tree,
                'ref': self.ref, 'bundle': {'sha256': self.bundle_sha256, 'bytes': self.bundle_bytes},
                'files': self.files, 'inflatedBytes': self.inflated_bytes, 'resumed': self.resumed,
                'tests': {'status': self.tests.get('status'), 'command': self.tests.get('command'),
                          'label': self.tests.get('label'), 'output': dict(self.tests.get('output_digest') or {})},
                'excluded': {'count': len(self.excluded), **dict(self.excluded_digest)},
                'exclusionRule': EXCLUSION_RULE}


def _check_attempt(integration_store, operation_key: str):
    resolved = di.stored_inputs(integration_store, operation_key, state='confirmed')
    if AE.end_record(integration_store, store.attempt_id_for(operation_key)) is not None:
        raise _refused('ATTEMPT_ENDED', f'attempt {store.attempt_id_for(operation_key)} has an end record: no '
                       'result is taken from it')
    return resolved


def _tree_refused(problems: list[dict], what: str) -> DispatchRefused:
    """RESULT_TREE_REFUSED with each problem's reason and the digest of its path (agent-controlled text, S7)."""
    return _refused('RESULT_TREE_REFUSED', f'the result tree {what}',
                    problems=[{'reason': p['reason'], 'path': _digest(p['path'].encode('utf-8', 'surrogateescape'))}
                              for p in problems[:20]])


def intake_result(integration_store, operation_key: str, *, base: Base, printed: dict, pulled: Mapping,
                  message: str, when: int, resumed: bool = False) -> VerifiedResult:
    """The host's intake of the pulled bundle: the attempt confirmed with no end record (ATTEMPT_ENDED) and its turn
    confirmed; the pull verified by the retained verifier (RESULT_NOT_VERIFIED) at the bundle digest the command
    printed before the tests and the probe delivered (a resumed intake: the pulled bundle's own digest, the
    commit-id equality its integrity check); exactly the reference ``refs/heads/work/<attempt id>``, no prerequisite
    (RESULT_REFS_INVALID); its commit the printed one and byte for byte ``expected_commit`` over its own tree
    (RESULT_COMMIT_MISMATCH); the tree within its bounds, regular files only, no link, gitlink or forbidden name,
    ``openspec/`` and ``backlog/`` exactly the base's, the blobs at most MAX_INFLATED inflated (RESULT_TREE_REFUSED
    with a reason). Any repository error is RESULT_NOT_VERIFIED."""
    resolved = _check_attempt(integration_store, operation_key)
    attempt_id = store.attempt_id_for(operation_key)
    turn = integration_store.get(TURN_KEY.format(attempt_id=attempt_id))
    if turn is None or turn.state != 'confirmed':
        raise _refused('TURN_NOT_CONFIRMED', f'the turn journal is {getattr(turn, "state", None)}, not confirmed')
    staged = pulled.get('staged') if isinstance(pulled, Mapping) else None
    verified = pulled.get('bundle') if isinstance(pulled, Mapping) else None
    want = (printed['bundle']['sha256'], printed['bundle']['size']) if not resumed else None
    if not isinstance(staged, Mapping) or not isinstance(verified, Mapping) or pulled.get('result') != 'pulled' \
            or verified.get('verified') is not True \
            or (want is not None and ((staged.get('sha256'), staged.get('bytes')) != want
                                      or (printed['delivered']['sha256'], printed['delivered']['size']) != want)):
        raise _refused('RESULT_NOT_VERIFIED', 'the pulled bundle did not pass the retained verifier at the digest '
                       'printed before the tests and delivered')
    header = verified.get('header') if isinstance(verified.get('header'), Mapping) else {}
    refs = [list(r) for r in header.get('refs') or ()]
    if header.get('prerequisites') or len(refs) != 1 or refs[0][1] != result_ref(attempt_id):
        raise _refused('RESULT_REFS_INVALID', f'the bundle holds {len(refs)} reference(s) with prerequisites '
                       f'{bool(header.get("prerequisites"))}, not exactly {result_ref(attempt_id)}')
    commit = refs[0][0]
    if commit != printed['commit'] or printed['base'] != base.commit:
        raise _refused('RESULT_COMMIT_MISMATCH', 'the bundle\'s commit is not the one the command printed')
    ra = _repository_access()
    try:
        opened = ra.open_repository(verified['verify_repo'], config='repository', work_tree=False)
    except (ra.CannotRun, ra.RepositoryError, KeyError, TypeError, OSError) as exc:
        raise _refused('RESULT_NOT_VERIFIED', f'the verified repository cannot be read ({type(exc).__name__})') \
            from None
    try:
        found = opened.read(commit)
        if found is None or found[1] != 'commit':
            raise _refused('RESULT_NOT_VERIFIED', f'the verified repository lacks the commit {commit}')
        tree, _ = _commit_header(found[2])
        if HEX40.fullmatch(tree) is None or found[2] != expected_commit(tree, base.commit, message, when) \
                or object_id('commit', found[2]) != commit or tree != printed['tree']:
            raise _refused('RESULT_COMMIT_MISMATCH', f'{commit} is not the commit the dispatcher specified over its '
                           'tree (parent, identity, time, message or header)', commit=commit)
        try:
            entries = tree_entries(opened, tree)
        except TreeBound as bound:
            raise _tree_refused([{'path': '', 'reason': bound.reason}], f'is {bound.reason}') from None
        problems = tree_problems(entries)
        protected = frozenset((p, m, o) for p, m, o in entries if p.split('/')[0] in PROTECTED_DIRS)
        if protected != base.protected:
            problems += [{'path': p, 'reason': 'protected-changed'} for p in
                         sorted({e[0] for e in protected ^ base.protected})]
        if problems:
            raise _tree_refused(problems, f'holds {len(problems)} entr(ies) outside its policy')
        inflated = 0
        for _, _, oid in entries:
            blob = opened.read(oid)
            if blob is None or blob[1] != 'blob':
                raise _refused('RESULT_NOT_VERIFIED', f'the result tree names {oid}, not a blob of the repository')
            inflated += len(blob[2])
            if inflated > MAX_INFLATED:
                raise _tree_refused([{'path': '', 'reason': 'too-large'}], f'inflates beyond {MAX_INFLATED} bytes')
    except DispatchRefused:
        raise
    except (ra.RepositoryError, ValueError, OSError, TypeError, RecursionError) as exc:
        raise _refused('RESULT_NOT_VERIFIED', f'the verified repository cannot be read ({type(exc).__name__}: '
                       f'{getattr(exc, "code", "")})') from None
    finally:
        opened.close()
    return VerifiedResult(attempt_id=attempt_id, conversation_id=store.conversation_id_for(operation_key),
                          repository=resolved.repository, base=base.commit, commit=commit, tree=tree,
                          ref=result_ref(attempt_id), bundle_sha256=str(staged.get('sha256')),
                          bundle_bytes=int(staged.get('bytes')), staged=str(staged.get('path')),
                          verify_repo=str(verified['verify_repo']), files=len(entries), inflated_bytes=inflated,
                          tests=printed['tests'], excluded=tuple(printed['excluded']),
                          excluded_digest=printed['excluded_digest'], resumed=resumed)


# ---------------------------------------------------------------------------
# The run

@dataclass(frozen=True)
class RunOutcome:
    outcome: str      # verified, stopped, inspection-failed, run-not-started, turn-not-finished
    attempt_id: str
    conversation_id: str
    turn_status: str | None = None
    problems: tuple = ()
    end: dict | None = None
    result: VerifiedResult | None = None
    runtime: str | None = None

    def to_json(self) -> dict:
        return {'format': OUTCOME_FORMAT, 'outcome': self.outcome, 'attemptId': self.attempt_id,
                'conversationId': self.conversation_id, 'turnStatus': self.turn_status,
                'problems': list(self.problems), 'end': self.end,
                'result': self.result.to_json() if self.result else None, 'runtime': self.runtime}


def _stop(integration_store, operation_key, transport, actor, records, read_artifact):
    return AE.end_interrupted_attempt(integration_store, operation_key, transport=transport, actor=actor,
                                      trigger=AE.ATTEMPT_STOPPED, dispatcher_records=list(records),
                                      read_artifact=read_artifact)


def _start(integration_store, operation_key, base, transport, read_artifact):
    resolved = _check_attempt(integration_store, operation_key)
    design = _design(resolved)
    if base.repository != resolved.repository or base.design_commit != design['commit']:
        raise _refused('BASE_LACKS_DESIGN', 'the base is not the approved repository checked against the attempt\'s '
                       'accepted design commit')
    client = AE._client(resolved, transport)(read_artifact)
    return resolved, client, store.attempt_id_for(operation_key), store.conversation_id_for(operation_key)


def _result_step(integration_store, operation_key, client, *, base, prepared, pull, observe, reserve_result,
                 stopped, resumed, status):
    """RESULT, the intake, the after-result observation, the runtime stop and the result hook."""
    attempt_id, conversation_id = store.attempt_id_for(operation_key), store.conversation_id_for(operation_key)
    answer = _command(client, conversation_id, prepared.result, 'RESULT_UNANSWERED')
    printed = parse_result(answer, delivered_expected=not resumed)
    verified = intake_result(integration_store, operation_key, base=base, printed=printed,
                             pulled=pull(result_name(attempt_id)), message=prepared.message, when=prepared.when,
                             resumed=resumed)
    records = AE.check_records(list(observe('after-result', result=verified) or ()))
    if records:
        return stopped(records, status=status)
    runtime = AE.stop_runtime(client, conversation_id)
    if reserve_result is not None:
        reserve_result(verified.to_json(), verified)
    return RunOutcome('verified', attempt_id, conversation_id, turn_status=status, result=verified, runtime=runtime)


def run_attempt(integration_store, operation_key: str, *, transport, base: Base, actor: str,
                inspect: Callable[[str], Sequence[str]], pull: Callable[[str], Mapping],
                observe: Callable[..., Sequence[Mapping]] | None = None,
                reserve_result: Callable[[dict, VerifiedResult], object] | None = None,
                ceiling_s: float = TURN_CEILING_S, clock=None, wait=None,
                read_artifact: Callable[[str], bytes] = di.read_profile_artifact) -> RunOutcome:
    """The attempt run (the module docstring's steps 0 to 7) of a confirmed attempt on BASE (``read_base`` of the
    approved repository). An attempt whose turn journal exists is TURN_ALREADY_SENT before any call (its result step
    is ``resume_result``'s). Refusals (DispatchRefused) leave the conversation as it is, for a resumed step; only an
    inspection failure, a run that did not start, or an observer's record ends the attempt."""
    resolved, client, attempt_id, conversation_id = _start(integration_store, operation_key, base, transport,
                                                           read_artifact)
    held = integration_store.get(TURN_KEY.format(attempt_id=attempt_id))
    if held is not None:
        raise _refused('TURN_ALREADY_SENT', f'the turn journal is {held.state}: the run is not repeated; a result step '
                       'is resumed with resume_result', state=held.state)
    prepared = prepare(resolved, base, attempt_id, attempt_time(integration_store, operation_key))   # S2: first
    observe = observe or (lambda phase, **facts: ())

    def stopped(records, outcome='stopped', problems=(), status=None):
        end = _stop(integration_store, operation_key, transport, actor, records, read_artifact)
        return RunOutcome(outcome, attempt_id, conversation_id, turn_status=status, problems=tuple(problems), end=end)

    # 1. inspect before any work
    try:
        problems = inspect_conversation(client, conversation_id)
    except DispatchRefused as refusal:
        problems = [f'{refusal.code}: {refusal.detail}']
    try:
        problems += [str(p) for p in inspect(conversation_id) or ()]
    except Exception as exc:  # noqa: BLE001 - a hook that cannot answer is a failed inspection
        problems.append(f'the container inspection did not answer ({type(exc).__name__})')
    if problems:
        return stopped([{'kind': 'containment-stop', 'code': 'INSPECTION_FAILED',
                         'ref': f'attempt:{attempt_id}#inspection'}], 'inspection-failed', problems)
    # 2. SEED
    answer = _command(client, conversation_id, prepared.seed, 'SEED_FAILED')
    body = answer.get('body') if isinstance(answer.get('body'), Mapping) else {}
    stdout = body.get('stdout')
    want = f'AIEH-SEED ok {base.seed_sha256} {len(base.files)}'
    if answer.get('status') != 200 or body.get('exit_code') != 0 or not isinstance(stdout, str) \
            or want not in [line.strip() for line in stdout.splitlines()]:
        raise _refused('SEED_FAILED', f'the seed answered {answer.get("status")} without its success line; nothing '
                       'was sent to the agent', exit_code=di._json_value(body.get('exit_code')))
    records = AE.check_records(list(observe('before-message') or ()))
    if records:
        return stopped(records)
    # 3. the message, 4. the turn
    try:
        send_message(integration_store, operation_key, client, base, prepared.text, actor=actor)
    except DispatchRefused as refusal:
        if refusal.code != 'TURN_RUN_NOT_STARTED':
            raise
        return stopped([{'kind': 'run-not-started', 'code': 'TURN_RUN_NOT_STARTED',
                         'ref': f'attempt:{attempt_id}#turn'}], 'run-not-started')
    status = wait_for_turn(client, conversation_id, ceiling_s=ceiling_s, clock=clock, wait=wait)
    records = AE.check_records(list(observe('after-turn', status=status) or ()))
    if records:
        return stopped(records, status=status)
    if status != 'finished':
        return RunOutcome('turn-not-finished', attempt_id, conversation_id, turn_status=status)
    # 5. RESULT, 6. the intake, 7. close
    return _result_step(integration_store, operation_key, client, base=base, prepared=prepared, pull=pull,
                        observe=observe, reserve_result=reserve_result, stopped=stopped, resumed=False,
                        status=status)


def resume_result(integration_store, operation_key: str, *, transport, base: Base, actor: str,
                  pull: Callable[[str], Mapping], exists: Callable[[str], bool],
                  observe: Callable[..., Sequence[Mapping]] | None = None,
                  reserve_result: Callable[[dict, VerifiedResult], object] | None = None,
                  read_artifact: Callable[[str], bytes] = di.read_profile_artifact) -> RunOutcome:
    """Resume the result step of an attempt whose turn journal is confirmed, which has no end record and whose result
    journal is not dispatched, and whose conversation finished (review S3). When ``exists(name)`` says the exchange
    already holds the attempt's bundle, RESULT is re-run without a delivery (the same inputs: the same commit) and
    the bundle there is pulled and verified, the commit-id equality its integrity check; otherwise RESULT runs with
    its delivery, as in ``run_attempt``."""
    resolved, client, attempt_id, conversation_id = _start(integration_store, operation_key, base, transport,
                                                           read_artifact)
    turn = integration_store.get(TURN_KEY.format(attempt_id=attempt_id))
    if turn is None or turn.state != 'confirmed':
        raise _refused('TURN_NOT_CONFIRMED', f'the turn journal is {getattr(turn, "state", None)}, not confirmed')
    result = integration_store.get(AE.RESULT_KEY.format(attempt_id=attempt_id))
    if result is not None and result.state in AE.HANDED_ON:
        raise _refused('ATTEMPT_RESULT_HANDED_ON', f'the result journal is {result.state}: the result step is the '
                       'result path\'s now', result_state=result.state)
    _, status = conversation_status(client, conversation_id)
    if status != 'finished':
        raise _refused('TURN_NOT_FINISHED', f'the conversation is {status}, not finished: no result is taken',
                       status=status)
    resumed = bool(exists(result_name(attempt_id)))
    prepared = prepare(resolved, base, attempt_id, attempt_time(integration_store, operation_key),
                       deliver=not resumed)
    observe = observe or (lambda phase, **facts: ())

    def stopped(records, outcome='stopped', problems=(), status=None):
        end = _stop(integration_store, operation_key, transport, actor, records, read_artifact)
        return RunOutcome(outcome, attempt_id, conversation_id, turn_status=status, problems=tuple(problems), end=end)
    return _result_step(integration_store, operation_key, client, base=base, prepared=prepared, pull=pull,
                        observe=observe, reserve_result=reserve_result, stopped=stopped, resumed=resumed,
                        status=status)
