"""The result path of a native D1 attempt (plan leaf E-05.4; D1 slice B of the work design accepted on 2026-11-15,
sections G6 to G8, with the engineering manager's rulings R1, R3 and R5 and the A3 ruling S7).

From a result the host verified (``attempt_run.VerifiedResult``: the bundle the retained verifier accepted, whose
one commit is byte for byte the commit the dispatcher specified), the dispatcher, as the stage's bot, pushes
``work/<attempt id>`` to the host Gitea and opens one draft pull request into ``main``, reconciled against Gitea's
actual state before any write, journaled, with a lineage receipt and an Owner report.

1. **The result journal** ``dispatch/attempt/<attempt id>/result`` (``RESULT_KEY``, shared with ``attempt_end``):
   reserved at the intake by ``attempt_run``'s hook (``result_hook``; the intent is the verified result's record,
   digests only, so a resumed intake reserves the same journal and a different result is RESULT_JOURNAL_CONFLICT),
   ``dispatched`` immediately before the first write, ``confirmed`` with the receipt after the read-back,
   ``unknown`` when a write was refused or its answer lost (RESULT_WRITE_UNSETTLED), which only the next run's
   reading of Gitea settles. Once dispatched, ``attempt_end.end_interrupted_attempt`` refuses the attempt
   (ATTEMPT_RESULT_HANDED_ON); the result path refuses an attempt with an end journal in any state (ATTEMPT_ENDED).
   A result whose tree is the base's (an attempt that changed nothing) fails the journal with RESULT_EMPTY_CHANGE
   and writes nothing: the open decision of the design's section 7 is planning's.
2. **The outbound search** (decision 0023 section 5; ``native_token_search``, E-05.9's search reused): before
   anything is written beyond digests or sent, the result bundle (its bytes and every pack object, inflated) and
   every text to be written or sent (the test output, the excluded paths, the commit message, the pull request's
   title and body, the diff, the report's draft, the receipt's draft, the caller's extra texts) are searched for
   the native token, held in memory as the dispatcher holds it (``native_token.NativeToken``; its fingerprint must
   be the one the attempt's dispatch recorded, OUTBOUND_TOKEN_MISMATCH). The journal's dispatch and every write
   require a ``not-found`` report with valid controls whose subject names the bundle's sha256 and each text's
   sha256 (``require_not_found``: OUTBOUND_SEARCH_REQUIRED, OUTBOUND_TOKEN_FOUND, OUTBOUND_SEARCH_NOT_PASSED). The
   final report and receipt, which name the pull request, are searched again before they are recorded or written.
3. **Reconciliation** before any write, by reading Gitea as the bot (``attempt_tokens.ResultSession``, a closed
   route list with no merge route): the attempt's branch already at the exact commit and its pull request are
   reused (nothing written); a branch at another commit is RESULT_BRANCH_CONFLICT; a pull request of the branch
   that is not the one opened here is RESULT_PR_CONFLICT; and when a write is needed, the protected branch must
   still be at the result's base (RESULT_BASE_MOVED) and no pull request from another attempt of the task (the
   store's attempts of the work item and their ``work/<attempt id>`` branches, never the pull requests' text) may
   be open (RESULT_EARLIER_PR_OPEN).
4. **The push** of ``work/<attempt id>`` at the verified commit, from the verified repository, as the stage's bot
   (``attempt_tokens.attempt_role_token``: the builder's standing token in the attempt context; the repository
   module's Dulwich push, fast-forward only, never forced), then **one pull request** to ``main`` whose title is
   ``WIP: `` and the commit's subject (R5) and whose body names the repository, the base, the exact SHA, the task,
   the attempt, the conversation, the outcome and the design, and carries the test output labelled not independent
   CI (R1: a failing run is marked FAILED and the path proceeds) and R3's excluded paths. Gitea 28.3.0 has no
   draft field in its create option (modules/structs/pull.go ``CreatePullRequestOption``); a pull request is a
   draft when its title begins with one of ``[repository.pull-request] WORK_IN_PROGRESS_PREFIXES``, by default
   ``WIP:`` and ``[WIP]`` (modules/setting/repository.go; ``models/issues/pull.go`` ``IsWorkInProgress``), its view
   says ``draft`` (services/convert/pull.go), and a work-in-progress pull request is not mergeable
   (``PullRequest.Mergeable``). The harness's app.ini sets no prefixes (``gitea_host.render_app_ini``).
5. **Read-back**: the branch at the exact commit, and the pull request open, unmerged, by the bot, from the branch
   at that commit into ``main``, with the title and body sent and ``draft`` true (RESULT_READBACK otherwise).
6. **Lineage** (G7): the confirmed journal's receipt (``result-receipt/v1``) holds ``workRef`` (``backlog:``),
   ``outcomeRef``, ``executionRef`` (``openhands:conversation/``), the design revision and the base and result as
   ``git:<repository>@<commit>``, each in the lineage reader's grammar, beside the branch, the pull request's
   number and URL and the bundle's sha256; the commit's trailers (Task, Attempt, Outcome, Design) and the pull
   request's body mirror it on Gitea.
7. **The Owner report** (E-05.5: "with the diff and the test output, without a Gitea sign-in"), JSON and Markdown,
   built by host code from the verified objects: the diff base..result computed here from the verified
   repository's objects (no git launch; bounded; control characters removed), the test output, R3's exclusions,
   the attempt and conversation identities, the pull request's URL and number, and the run's observations (a slot
   the run driver fills). After a result step resumed from its intake receipt, the test output and the excluded
   paths exist only as digests (receipts never hold agent text): the pull request and the report say so and give
   the digests, and invent nothing.

``publish_result(store, key, verified=, native=, provider=, target=, actor=)`` runs 2 to 7; ``result_hook`` is
``attempt_run``'s ``reserve_result``. A confirmed journal is returned as it is, with no call. Assumptions stated: one
dispatcher process (as ``attempt_run``); the demo repository is the only admitted repository
(``ADMITTED_REPOSITORIES``). Standard library and the repository-access module only; nothing here launches git.
"""
from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


AR = _load('attempt_run', HERE / 'attempt_run.py')
di, AE = AR.di, AR.AE
store = di.store
DispatchRefused = di.DispatchRefused
AT = _load('attempt_tokens', HERE / 'attempt_tokens.py')
roles = AT.roles
NT = di._native_module()
NTS = _load('aieh_native_token_search', HERE / 'native_token_search.py')

RESULT_KEY = AE.RESULT_KEY
JOURNAL_FORMAT = 'ai-engineering-harness/dispatch/attempt-result-journal/v1'
RECEIPT_FORMAT = 'ai-engineering-harness/dispatch/result-receipt/v1'
REPORT_FORMAT = 'ai-engineering-harness/dispatch/owner-report/v1'
SEARCH_SUMMARY_FORMAT = 'ai-engineering-harness/dispatch/outbound-search-summary/v1'

# The approved repositories the result path pushes to, and their Gitea repository: the D1 demo only.
ADMITTED_REPOSITORIES = {'aieh-d1-demo': roles.DEMO_REPOSITORY}
BASE_BRANCH = AT.BASE_BRANCH
DRAFT_PREFIX = 'WIP: '              # Gitea 28.3.0's default WORK_IN_PROGRESS_PREFIXES: WIP:, [WIP]
WIP_PREFIXES = ('WIP:', '[WIP]')
MAX_PULL_PAGES = 20                 # open pull requests read page by page, at most this many pages
DIFF_LIMIT = 256 * 1024             # characters of the rendered diff the report carries
BUNDLE_LABEL = 'result-bundle'
TRAILERS = ('Task', 'Attempt', 'Outcome', 'Design')
HEX40 = AR.HEX40


def _refused(code: str, detail: str, **context) -> DispatchRefused:
    return DispatchRefused(code, detail, **context)


def _sha256(data) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8', 'surrogatepass')
    return hashlib.sha256(data).hexdigest()


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


# ---------------------------------------------------------------------------
# The Gitea target

@dataclass(frozen=True)
class GiteaTarget:
    """Where the result goes: the approved repository's id, its Gitea repository (OWNER/NAME), the managed Gitea's
    port, its smart-HTTP URL (the push) and HTTP (None: gitea_host.http_get to 127.0.0.1:PORT; tests: a fake with
    its signature)."""
    repository_id: str
    full_name: str
    port: int
    git_url: str
    http: Callable | None = None
    authority: str = di.LIVE        # E-01.8 (R8 point 5): the target's declared authority, the managed Gitea's live

    @property
    def web_root(self) -> str:
        return f'http://{roles.host.LOOPBACK}:{self.port}/{self.full_name}'

    def pull_url(self, number: int) -> str:
        return f'{self.web_root}/pulls/{number}'


def gitea_target(repository_id: str, port: int, http=None) -> GiteaTarget:
    """The managed Gitea's target for the approved REPOSITORY_ID (ADMITTED_REPOSITORIES)."""
    if repository_id not in ADMITTED_REPOSITORIES:
        raise _refused('RESULT_REPOSITORY_NOT_ADMITTED', f'{repository_id!r} is not an admitted repository '
                       f'({sorted(ADMITTED_REPOSITORIES)})')
    return GiteaTarget(repository_id=repository_id, full_name=ADMITTED_REPOSITORIES[repository_id], port=port,
                       git_url=roles.demo_url(port), http=http)


# ---------------------------------------------------------------------------
# The result journal (reserved at the intake: attempt_run's hook)

def journal_intent(operation_key: str, verified) -> dict:
    """The journal's intent: the verified result's record (digests and sizes only, S7) without ``resumed``, so that
    the same result reserves the same journal whether its intake ran now or is resumed from its receipt."""
    record = verified.to_json()
    record.pop('resumed', None)
    return {'format': JOURNAL_FORMAT, 'operationKey': operation_key,
            'attemptId': store.attempt_id_for(operation_key), 'result': record}


def _attempt_checks(integration_store, operation_key: str, verified):
    resolved = di.stored_inputs(integration_store, operation_key, state='confirmed')
    attempt_id = store.attempt_id_for(operation_key)
    if integration_store.get(AE.END_KEY.format(attempt_id=attempt_id)) is not None:
        raise _refused('ATTEMPT_ENDED', f'attempt {attempt_id} has an end journal: no result is taken from it')
    if not isinstance(verified, AR.VerifiedResult) or verified.attempt_id != attempt_id \
            or verified.conversation_id != store.conversation_id_for(operation_key) \
            or verified.repository != resolved.repository or verified.ref != AR.result_ref(attempt_id):
        raise _refused('RESULT_NOT_RESERVED', f'the verified result is not attempt {attempt_id}\'s')
    return resolved, attempt_id


def reserve_result(integration_store, operation_key: str, verified, *, actor: str) -> dict:
    """Reserve the attempt's result journal for VERIFIED (repeat-safe: the same result returns the reservation as it
    is). RESULT_JOURNAL_CONFLICT for another result; ATTEMPT_ENDED for an attempt with an end journal."""
    _attempt_checks(integration_store, operation_key, verified)
    key = RESULT_KEY.format(attempt_id=verified.attempt_id)
    try:
        held = integration_store.reserve(key, journal_intent(operation_key, verified), actor=actor).reservation
    except store.ConflictingReservation:
        raise _refused('RESULT_JOURNAL_CONFLICT', f'{key} holds another verified result') from None
    return {'key': key, 'state': held.state}


def result_hook(integration_store, operation_key: str, *, actor: str) -> Callable:
    """``attempt_run``'s ``reserve_result(record, verified)`` for this attempt: RECORD must be VERIFIED's own."""
    def reserve(record, verified):
        if not isinstance(verified, AR.VerifiedResult) or record != verified.to_json():
            raise _refused('RESULT_NOT_RESERVED', 'the hook\'s record is not the verified result\'s')
        return reserve_result(integration_store, operation_key, verified, actor=actor)
    return reserve


def _journal(integration_store, operation_key: str, verified):
    key = RESULT_KEY.format(attempt_id=verified.attempt_id)
    held = integration_store.get(key)
    if held is None:
        raise _refused('RESULT_NOT_RESERVED', f'{key} is not reserved: the intake reserves it')
    if held.intent_digest != _sha256(store.canonical_intent(journal_intent(operation_key, verified))):
        raise _refused('RESULT_JOURNAL_CONFLICT', f'{key} holds another verified result')
    return key, held


def _detail(integration_store, key: str, to_state: str):
    for event in reversed(integration_store.events(key)):
        if event.to_state == to_state:
            return json.loads(event.detail_json) if event.detail_json else None
    return None


def receipt(integration_store, attempt_id: str) -> dict | None:
    """The attempt's confirmed result receipt, or None."""
    key = RESULT_KEY.format(attempt_id=attempt_id)
    held = integration_store.get(key)
    if held is None or held.state != 'confirmed':
        return None
    found = _detail(integration_store, key, 'confirmed')
    return found if isinstance(found, dict) and found.get('format') == RECEIPT_FORMAT else None


# ---------------------------------------------------------------------------
# The verified objects: the commit, its message and the diff, read on the host

@dataclass(frozen=True)
class Verified:
    """What the host reads of the verified repository for the path: the commit's message (subject, trailers), the
    base tree, and the diff base..result."""
    message: str
    subject: str
    trailers: dict
    base_tree: str
    diff: dict


def _open(verified):
    ra = AR._repository_access()
    try:
        return ra.open_repository(verified.verify_repo, config='repository', work_tree=False)
    except (ra.CannotRun, ra.RepositoryError, OSError, ValueError) as exc:
        raise _refused('RESULT_STAGED_UNVERIFIED', f'the verify repository cannot be opened ({type(exc).__name__})') \
            from None


def read_verified(verified, resolved) -> Verified:
    """The verified commit re-read from the verified repository (its id, tree and parent the result's), its message
    (the dispatcher's, R5) with the trailers the reserved record names, and the diff (``tree_diff``)."""
    ra = AR._repository_access()
    opened = _open(verified)
    try:
        found = opened.read(verified.commit)
        base = opened.read(verified.base)
        if found is None or found[1] != 'commit' or AR.object_id('commit', found[2]) != verified.commit \
                or AR._commit_header(found[2]) != (verified.tree, [verified.base]) \
                or base is None or base[1] != 'commit':
            raise _refused('RESULT_STAGED_UNVERIFIED', 'the verify repository does not hold the verified commit on '
                           'its base')
        base_tree = AR._commit_header(base[2])[0]
        message = found[2].split(b'\n\n', 1)[1].decode('utf-8')
        diff = tree_diff(opened, base_tree, verified.tree)
    except DispatchRefused:
        raise
    except (ra.RepositoryError, ValueError, OSError, IndexError, UnicodeDecodeError, AR.TreeBound) as exc:
        raise _refused('RESULT_STAGED_UNVERIFIED', f'the verified objects cannot be read ({type(exc).__name__})') \
            from None
    finally:
        opened.close()
    subject, _, rest = message.partition('\n')
    trailers = {}
    for line in rest.strip('\n').split('\n'):
        name, sep, value = line.partition(': ')
        if sep and name in TRAILERS:
            trailers[name] = value
    want = {'Task': resolved.work_id, 'Attempt': verified.attempt_id, 'Outcome': resolved.outcome_ref,
            'Design': resolved.design_revision}
    if trailers != want or not subject.startswith(f'{resolved.work_id}: '):
        raise _refused('RESULT_STAGED_UNVERIFIED', 'the verified commit\'s message is not the reserved record\'s')
    return Verified(message=message, subject=subject, trailers=trailers, base_tree=base_tree, diff=diff)


def _text_of(data: bytes) -> str | None:
    if b'\x00' in data:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def tree_diff(opened, base_tree: str, tree: str) -> dict:
    """The diff base..result of two trees of OPENED (the verified repository), computed here from its objects (no
    git launch): a unified diff per changed text file (difflib, three lines of context), a line for a binary or
    mode change; paths and text rendered as data (control characters but newline and tab removed); the rendered text
    at most DIFF_LIMIT characters, the whole one's sha256 and size kept."""
    before = {p: (m, o) for p, m, o in AR.tree_entries(opened, base_tree)}
    after = {p: (m, o) for p, m, o in AR.tree_entries(opened, tree)}
    parts, files, added_lines, removed_lines = [], [], 0, 0
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        shown = AR._data_text(path)
        status = 'added' if old is None else 'removed' if new is None else 'modified'
        files.append({'path': shown, 'status': status,
                      'mode': f'{(new or old)[0]:o}', **({'oldMode': f'{old[0]:o}'} if old and new and old[0] != new[0]
                                                         else {})})
        old_data = opened.read(old[1])[2] if old else b''
        new_data = opened.read(new[1])[2] if new else b''
        header = f'diff -- {shown} ({status})\n'
        if old and new and old[0] != new[0]:
            header += f'mode {old[0]:o} -> {new[0]:o}\n'
        if old and new and old[1] == new[1]:
            parts.append(header)
            continue
        old_text, new_text = _text_of(old_data), _text_of(new_data)
        if old_text is None or new_text is None:
            parts.append(header + f'binary: {len(old_data)} bytes sha256 {_sha256(old_data)[:16]} -> '
                                  f'{len(new_data)} bytes sha256 {_sha256(new_data)[:16]}\n')
            continue
        body = []
        for line in difflib.unified_diff(_lines(old_text), _lines(new_text),
                                         fromfile=f'a/{shown}' if old else '/dev/null',
                                         tofile=f'b/{shown}' if new else '/dev/null', n=3):
            if line.startswith('+') and not line.startswith('+++'):
                added_lines += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed_lines += 1
            body.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
        parts.append(header + AR._data_text(''.join(body)))
    whole = ''.join(parts)
    return {'text': whole[:DIFF_LIMIT], 'truncated': len(whole) > DIFF_LIMIT, 'sha256': _sha256(whole),
            'characters': len(whole), 'files': files,
            'stats': {'files': len(files), 'added': added_lines, 'removed': removed_lines}}


# ---------------------------------------------------------------------------
# What is written and sent: the pull request's title and body, the report, the receipt

def test_outcome(tests: Mapping) -> str:
    """R1: PASSED for exit 0, FAILED otherwise (the exit status or the timeout named)."""
    status = tests.get('status')
    if status == '0':
        return 'PASSED'
    return 'FAILED (timeout)' if status == 'timeout' else f'FAILED (exit {status})'


def _fence(text: str) -> str:
    """TEXT as a fenced block whose fence no run of backticks in TEXT can close (CommonMark)."""
    longest = max((len(run) for run in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}text\n{text}{"" if text.endswith(chr(10)) or not text else chr(10)}{fence}\n'


def test_section(tests: Mapping) -> tuple[str, dict]:
    """The test output as the pull request and the report show it, and its JSON; when only its digest exists (a
    result step resumed from its intake receipt), a statement and the digest, never invented text."""
    output, digest = tests.get('output'), dict(tests.get('output_digest') or {})
    available = isinstance(output, str)
    data = {'status': tests.get('status'), 'outcome': test_outcome(tests), 'command': tests.get('command'),
            'label': tests.get('label'), 'outputAvailable': available, 'outputDigest': digest,
            'output': AR._data_text(output) if available else None}
    lines = [f'Command: `{tests.get("command")}`', f'Outcome: **{data["outcome"]}**',
             f'Label: {tests.get("label")}.']
    if available:
        text = '\n'.join(lines) + '\n\n' + _fence(data['output'])
    else:
        text = '\n'.join(lines) + ('\n\nThe output is not available in this run: the result step was resumed from its '
                                   'intake receipt, and receipts hold only its digest (sha256 '
                                   f'{digest.get("sha256")}, {digest.get("bytes")} bytes).\n')
    return text, data


def exclusion_section(verified) -> tuple[str, dict]:
    """R3's excluded paths: the rule, the count, the whole list's sha256 and the first entries RESULT listed; after
    a resumed intake only the count and digests exist."""
    digest = dict(verified.excluded_digest)
    count = digest.get('count')
    shown = [{'path': AR._data_text(e['path']), 'reason': e['reason']} for e in verified.excluded]
    available = bool(shown) or count == 0
    data = {'rule': AR.EXCLUSION_RULE, 'count': count, 'sha256': digest.get('sha256'), 'shown': len(shown),
            'available': available, 'paths': shown if available else None}
    text = (f'Rule: {AR.EXCLUSION_RULE}.\n\nExcluded: {count} path(s) (sha256 of the whole list '
            f'{digest.get("sha256")}).\n')
    if count and available:
        text += (f'The first {len(shown)}:\n\n' if len(shown) < count else '\n') \
            + _fence(''.join(f'{e["reason"]}: {e["path"]}\n' for e in shown))
    elif count:
        text += ('\nThe list is not available in this run: the result step was resumed from its intake receipt, and '
                 'receipts hold only its count and digest.\n')
    return text, data


def lineage_refs(resolved, verified) -> dict:
    """The receipt's references, each in the lineage reader's grammar (parsed and canonical, or a refusal)."""
    refs = {'workRef': resolved.work_ref, 'outcomeRef': resolved.outcome_ref,
            'executionRef': f'{di.EXECUTION_REF_PREFIX}{verified.conversation_id}',
            'designRevision': resolved.design_revision,
            'baseRef': f'git:{resolved.repository}@{verified.base}',
            'resultRef': f'git:{resolved.repository}@{verified.commit}'}
    for name, text in refs.items():
        if name == 'designRevision':      # the store's design revision (openspec:changes/<change>@<commit>)
            if not store.valid_design_revision(text):
                raise _refused('RESULT_STAGED_UNVERIFIED', f'{name} {text!r} is not a design revision')
            continue
        try:
            if di.lineage.parse(text).text != text:
                raise ValueError(text)
        except (di.lineage.MalformedReference, ValueError):
            raise _refused('RESULT_STAGED_UNVERIFIED', f'{name} {text!r} is not a lineage reference') from None
    return refs


def pull_title(read: Verified) -> str:
    return DRAFT_PREFIX + read.subject


def pull_body(resolved, verified, target: GiteaTarget, refs: dict, tests_text: str, excluded_text: str) -> str:
    """The pull request's body: built from the reserved record and the verified result only (values of their
    grammars), then the test output and R3's exclusions as data."""
    branch = verified.ref[len('refs/heads/'):]
    labelled = [('Authority', verified.authority)] if verified.authority != di.LIVE else []   # E-01.8, R11
    rows = [*labelled,
            ('Repository', f'{target.full_name} (approved repository {resolved.repository})'),
            ('Base', f'{BASE_BRANCH} at {verified.base}'), ('Exact SHA', verified.commit), ('Branch', branch),
            ('Task', f'{resolved.work_id} ({refs["workRef"]})'), ('Attempt', verified.attempt_id),
            ('Conversation', refs['executionRef']), ('Outcome', refs['outcomeRef']),
            ('Design', refs['designRevision']),
            ('Result bundle', f'sha256 {verified.bundle_sha256}, {verified.bundle_bytes} bytes')]
    table = '| | |\n|---|---|\n' + ''.join(f'| {k} | `{v}` |\n' for k, v in rows)
    bot = roles.ROLES[AT.STAGE_ROLES[resolved.stage]]['user']
    return (f'Draft pull request opened by the dispatcher as {bot} (plan leaf E-05.4) '
            f'from attempt {verified.attempt_id} of {resolved.work_id}. It is marked draft ({DRAFT_PREFIX.strip()} '
            'title) and is not mergeable except by the Owner-authorized protected merge; no bot merges.\n\n'
            f'{table}\n## Tests (not independent CI)\n\n{tests_text}\n## Paths left out of the commit (R3)\n\n'
            f'{excluded_text}')


def owner_report(resolved, verified, target: GiteaTarget, read: Verified, refs: dict, *, tests: dict,
                 excluded: dict, tests_text: str, excluded_text: str, pull: dict | None, search: dict | None,
                 observations: Mapping | None) -> dict:
    """The Owner report as JSON and Markdown (``{'json': ..., 'markdown': ...}``): host code, from the verified
    objects, readable without a Gitea sign-in. PULL is None in the draft the first search covers."""
    if observations is not None:
        try:
            observations = json.loads(json.dumps(observations, sort_keys=True))
        except (TypeError, ValueError):
            raise ValueError('the run\'s observations are JSON data') from None
    pull_view = pull or {'number': None, 'url': None, 'state': 'pending: not opened yet'}
    data = {'format': REPORT_FORMAT,
            'builtBy': 'integrations/dispatch/result_path.py, host code, from the verified objects; no Gitea sign-in '
                       'is needed to read it',
            'task': resolved.work_id, 'attemptId': verified.attempt_id, 'conversationId': verified.conversation_id,
            'repository': {'id': resolved.repository, 'gitea': target.full_name}, 'base': verified.base,
            'commit': verified.commit, 'branch': verified.ref[len('refs/heads/'):],
            'bundle': {'sha256': verified.bundle_sha256, 'bytes': verified.bundle_bytes},
            'pullRequest': {**pull_view, 'title': pull_title(read), 'draft': True}, 'lineage': refs,
            'commitMessage': read.message, 'diff': read.diff, 'tests': tests, 'exclusions': excluded,
            'search': search, 'observations': observations,
            'observationsStatement': 'supplied by the run driver' if observations is not None else
            'not supplied: the run driver (slice C) fills this slot', **di.authority_label(verified.authority)}
    pr = f'#{pull_view["number"]} {pull_view["url"]}' if pull else 'pending'
    diff = read.diff
    md = [f'# D1 result: {resolved.work_id}, attempt {verified.attempt_id}\n',
          f'Built by host code from the verified objects; readable without a Gitea sign-in.\n',
          *([f'- Authority: `{verified.authority}` (the attempt\'s bound authority, not a live run)']
            if verified.authority != di.LIVE else []),
          f'- Repository: `{target.full_name}` (approved repository `{resolved.repository}`)',
          f'- Base: `{BASE_BRANCH}` at `{verified.base}`', f'- Commit (exact SHA): `{verified.commit}`',
          f'- Branch: `{data["branch"]}`', f'- Pull request: {pr} (draft, title `{pull_title(read)}`)',
          f'- Conversation: `{refs["executionRef"]}`', f'- Task: `{refs["workRef"]}`',
          f'- Outcome: `{refs["outcomeRef"]}`', f'- Design: `{refs["designRevision"]}`',
          f'- Result bundle: sha256 `{verified.bundle_sha256}`, {verified.bundle_bytes} bytes\n',
          f'## Diff ({diff["stats"]["files"]} file(s), +{diff["stats"]["added"]} -{diff["stats"]["removed"]})\n',
          _fence(diff['text']) + (f'\nThe diff is cut at {DIFF_LIMIT} characters of {diff["characters"]} (sha256 of '
                                  f'the whole {diff["sha256"]}).\n' if diff['truncated'] else ''),
          f'## Tests (not independent CI)\n\n{tests_text}', f'## Paths left out of the commit (R3)\n\n{excluded_text}',
          '## Run observations\n',
          (_fence(json.dumps(observations, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
           if observations is not None else data['observationsStatement'] + '.\n')]
    if search is not None:
        md.append(f'## Outbound token search\n\nVerdict `{search.get("verdict")}` over {search.get("bytesSearched")} '
                  f'bytes, controls valid: {search.get("controlsValid")}, key {search.get("fingerprint")}.\n')
    return {'json': data, 'markdown': '\n'.join(md)}


def report_texts(report: dict) -> tuple[str, str]:
    return json.dumps(report['json'], indent=2, sort_keys=True, ensure_ascii=False) + '\n', report['markdown']


# ---------------------------------------------------------------------------
# The outbound search (decision 0023 section 5)

def search_summary(report: dict) -> dict:
    """What a record carries of a search report: the verdict, the key's fingerprint, the counts, the controls'
    validity, the subject's digests and the report's sha256; never a byte of a searched text."""
    return {'format': SEARCH_SUMMARY_FORMAT, 'verdict': report.get('verdict'),
            'fingerprint': (report.get('key') or {}).get('fingerprint'), 'bytesSearched': report.get('bytes_searched'),
            'controlsValid': bool((report.get('controls') or {}).get('valid'))
            and bool((report.get('bundle_control') or {}).get('valid')),
            'surfaces': [{'label': s.get('label'), 'kind': s.get('kind'), 'bytes': s.get('bytes_total'),
                          'complete': s.get('complete'), 'found': s.get('found')}
                         for s in report.get('surfaces') or ()],
            'subject': report.get('subject'), 'reportSha256': _sha256(_canonical(report))}


def outbound_search(native, *, expected_fingerprint: str, texts: Mapping[str, str], bundle_path=None,
                    bundle_sha256: str | None = None) -> dict:
    """E-05.9's search (``native_token_search``) for NATIVE (the dispatcher's held ``NativeToken``; its fingerprint
    must be EXPECTED_FINGERPRINT, the attempt's dispatch record's) over the bundle at BUNDLE_PATH (its sha256 must
    be BUNDLE_SHA256) and TEXTS ({label: text}), with its positive controls. The report gains ``subject``: the
    bundle's and each text's sha256. The token is used in memory only and dropped from this frame at the end."""
    if not isinstance(native, NT.NativeToken) or not native.open:
        raise _refused('OUTBOUND_SEARCH_REQUIRED', 'no native token is held for the outbound search')
    if not isinstance(expected_fingerprint, str) or native.fingerprint != expected_fingerprint:
        raise _refused('OUTBOUND_TOKEN_MISMATCH', f'the held token is {native.fingerprint}, the attempt\'s dispatch '
                       f'recorded {expected_fingerprint}')
    if any(not NTS.ks.LABEL.fullmatch(label) or label == BUNDLE_LABEL for label in texts):
        raise ValueError('a text label is not of the search\'s grammar')
    subject = {'texts': {label: _sha256(text) for label, text in sorted(texts.items())}}
    token = native.token()
    try:
        search = NTS.new_search(token)
        if bundle_path is not None:
            try:
                data = Path(bundle_path).read_bytes()
            except OSError as exc:
                raise _refused('RESULT_STAGED_UNVERIFIED', f'the staged bundle cannot be read '
                               f'({type(exc).__name__})') from None
            if _sha256(data) != bundle_sha256:
                raise _refused('RESULT_STAGED_UNVERIFIED', 'the staged bundle is not the verified result\'s')
            subject['bundle'] = {'sha256': bundle_sha256, 'bytes': len(data)}
            NTS.search_bundle(search, BUNDLE_LABEL, data)
            del data
        for label, text in sorted(texts.items()):
            search.capture(label, text.encode('utf-8', 'surrogatepass'))
        try:
            report = NTS.report(search, token)
        except NTS.SearchRefused:
            # the report itself would have held the token: it is a finding, never printed or recorded
            report = {'verdict': 'found', 'key': {'fingerprint': native.fingerprint}, 'surfaces': [],
                      'withheld': True}
    finally:
        del token
        search = None
    report['subject'] = subject
    return report


def require_not_found(report, *, bundle_sha256: str | None, texts: Mapping[str, str]) -> dict:
    """The gate: REPORT is a ``not-found`` report with valid controls (the shared ones and the bundle's) whose
    subject names BUNDLE_SHA256 (when given) and the sha256 of each of TEXTS, each searched completely; its summary,
    or OUTBOUND_TOKEN_FOUND, OUTBOUND_SEARCH_NOT_PASSED, OUTBOUND_SEARCH_REQUIRED."""
    if not isinstance(report, Mapping) or not isinstance(report.get('subject'), Mapping):
        raise _refused('OUTBOUND_SEARCH_REQUIRED', 'no outbound search report was given')
    if report.get('verdict') == 'found':
        raise _refused('OUTBOUND_TOKEN_FOUND', 'the outbound search found the native token: nothing is written or '
                       'sent', where=[s.get('label') for s in report.get('surfaces') or () if s.get('found')])
    controls_valid = bool((report.get('controls') or {}).get('valid')) \
        and bool((report.get('bundle_control') or {}).get('valid'))
    if report.get('verdict') != 'not-found' or not controls_valid or report.get('format') != NTS.FORMAT:
        raise _refused('OUTBOUND_SEARCH_NOT_PASSED', f'the outbound search is {report.get("verdict")!r} (controls '
                       f'valid: {controls_valid})')
    subject = report['subject']
    surfaces = {s.get('label'): s for s in report.get('surfaces') or ()}
    want = {label: _sha256(text) for label, text in texts.items()}
    named = subject.get('texts') == want and all(
        surfaces.get(label, {}).get('complete') and surfaces[label].get('found') == 0 for label in want)
    if bundle_sha256 is not None:
        bundle = surfaces.get(BUNDLE_LABEL, {})
        named = named and (subject.get('bundle') or {}).get('sha256') == bundle_sha256 \
            and bundle.get('kind') == 'bundle' and bundle.get('complete') and bundle.get('found') == 0
    if not named:
        raise _refused('OUTBOUND_SEARCH_REQUIRED', 'the outbound search report does not name this result bundle and '
                       'every text to be written or sent')
    return search_summary(report)


# ---------------------------------------------------------------------------
# Reading Gitea's actual state

def _read(session, path: str, what: str):
    try:
        return session.call('GET', path)
    except DispatchRefused:
        raise
    except Exception as exc:  # noqa: BLE001 - a lost answer to a read: nothing is inferred, nothing written
        raise _refused('RESULT_GITEA_UNAVAILABLE', f'GET {what}: no answer ({type(exc).__name__})') from None


def branch_head(session, repository: str, branch: str) -> str | None:
    """The commit Gitea's BRANCH is at, or None (404)."""
    status, view = _read(session, f'/repos/{repository}/branches/{branch}', f'the branch {branch}')
    if status == 404:
        return None
    head = ((view or {}).get('commit') or {}).get('id') if isinstance(view, dict) else None
    if status != 200 or not isinstance(head, str) or HEX40.fullmatch(head) is None:
        raise _refused('RESULT_GITEA_UNAVAILABLE', f'GET the branch {branch} answered {status} without its commit',
                       status=status if type(status) is int else None)
    return head


def pull_of(session, repository: str, branch: str) -> dict | None:
    """The pull request of BRANCH into the protected branch (Gitea's GetPullRequestByBaseHead, any state), or None."""
    status, view = _read(session, f'/repos/{repository}/pulls/{BASE_BRANCH}/{branch}', f'the pull request of {branch}')
    if status == 404:
        return None
    if status != 200 or not isinstance(view, dict) or type(view.get('number')) is not int:
        raise _refused('RESULT_GITEA_UNAVAILABLE', f'GET the pull request of {branch} answered {status}',
                       status=status if type(status) is int else None)
    return view


def open_pulls(session, repository: str) -> list[dict]:
    """Every open pull request, page by page (a page shorter than the limit is the last)."""
    out = []
    for page in range(1, MAX_PULL_PAGES + 1):
        status, listed = _read(session, f'/repos/{repository}/pulls?state=open&page={page}&limit={AT.PULL_PAGE_LIMIT}',
                               'the open pull requests')
        if status != 200 or not isinstance(listed, list) or not all(isinstance(p, dict) for p in listed):
            raise _refused('RESULT_GITEA_UNAVAILABLE', f'GET the open pull requests answered {status} without a list')
        out.extend(listed)
        if len(listed) < AT.PULL_PAGE_LIMIT:
            return out
    raise _refused('RESULT_GITEA_UNAVAILABLE', f'more than {MAX_PULL_PAGES} pages of open pull requests: not read '
                   'whole')


def task_attempts(integration_store, work_id: str) -> set[str]:
    """The attempt ids of every typed attempt of WORK_ID in the store (any design revision and stage)."""
    out = set()
    for held in integration_store.attempts():
        record = integration_store.attempt_identity(held.operation_key) \
            if held.operation_key.startswith('attempt/') else None
        if record is not None and record.identity.work_id == work_id:
            out.add(store.attempt_id_for(held.operation_key))
    return out


def _side(view: dict, name: str) -> dict:
    side = view.get(name)
    return side if isinstance(side, dict) else {}


def pull_problems(view: dict, *, repository: str, branch: str, commit: str, user: str, title: str,
                  body: str | None) -> list[str]:
    """How a pull request VIEW differs from the one the result path opens (open, unmerged, by USER, from BRANCH of
    REPOSITORY at COMMIT into the protected branch, TITLE, a draft, BODY when given)."""
    full = lambda side: (_side(view, side).get('repo') or {}).get('full_name')  # noqa: E731
    seen = {'state': view.get('state'), 'merged': view.get('merged'),
            'author': (view.get('user') or {}).get('login') if isinstance(view.get('user'), dict) else None,
            'base': (full('base'), _side(view, 'base').get('ref')),
            'head': (full('head'), _side(view, 'head').get('ref'), _side(view, 'head').get('sha')),
            'title': view.get('title'), 'draft': view.get('draft')}
    want = {'state': 'open', 'merged': False, 'author': user, 'base': (repository, BASE_BRANCH),
            'head': (repository, branch, commit), 'title': title, 'draft': True}
    problems = [f'{k} is {seen[k]!r}, not {v!r}' for k, v in want.items() if seen[k] != v]
    if body is not None and _normal(view.get('body')) != _normal(body):
        problems.append('the body is not the one sent')
    return problems


def _normal(text) -> str | None:
    return text.replace('\r\n', '\n').rstrip() if isinstance(text, str) else None


@dataclass(frozen=True)
class Reconciled:
    """Gitea's actual state for the attempt: the protected branch's head, the attempt's branch head (None: absent),
    its pull request (None: absent), and the open pull requests of other attempts of the task."""
    base_head: str
    branch_head: str | None
    pull: dict | None
    earlier: tuple

    @property
    def push(self) -> bool:
        return self.branch_head is None

    @property
    def open(self) -> bool:
        return self.pull is None


def reconcile(session, integration_store, resolved, verified, *, title: str, body: str) -> Reconciled:
    """Read Gitea before any write (the module docstring's point 3): RESULT_BRANCH_CONFLICT, RESULT_PR_CONFLICT,
    and, when anything is to be written, RESULT_BASE_MOVED and RESULT_EARLIER_PR_OPEN."""
    repository, branch = session.repository, verified.ref[len('refs/heads/'):]
    base_head = branch_head(session, repository, BASE_BRANCH)
    if base_head is None:
        raise _refused('RESULT_GITEA_UNAVAILABLE', f'the protected branch {BASE_BRANCH} does not exist')
    head = branch_head(session, repository, branch)
    if head is not None and head != verified.commit:
        raise _refused('RESULT_BRANCH_CONFLICT', f'{branch} is at {head}, not the verified {verified.commit}',
                       branch_head=head)
    pull = pull_of(session, repository, branch)
    if pull is not None:
        # its body is the one an earlier run of this attempt sent (searched then); after a resumed intake this
        # run's body may differ in what it can show of the test output, so the body is not compared here
        problems = pull_problems(pull, repository=repository, branch=branch, commit=verified.commit,
                                 user=session.user, title=title, body=None)
        if problems:
            raise _refused('RESULT_PR_CONFLICT', f'pull request #{pull.get("number")} of {branch}: '
                           + '; '.join(problems)[:500], number=pull.get('number'))
    others = task_attempts(integration_store, resolved.work_id) - {verified.attempt_id}
    earlier = []
    for listed in open_pulls(session, repository):
        head_side = _side(listed, 'head')
        ref = head_side.get('ref')
        if isinstance(ref, str) and ref.startswith('work/') and ref[len('work/'):] in others:
            earlier.append({'number': listed.get('number'), 'attemptId': ref[len('work/'):]})
    state = Reconciled(base_head=base_head, branch_head=head, pull=pull, earlier=tuple(earlier))
    if state.push or state.open:
        if base_head != verified.base:
            raise _refused('RESULT_BASE_MOVED', f'{BASE_BRANCH} is at {base_head}, not the result\'s base '
                           f'{verified.base}', base_head=base_head)
        if earlier:
            raise _refused('RESULT_EARLIER_PR_OPEN', f'pull request(s) {[e["number"] for e in earlier]} of earlier '
                           f'attempt(s) of {resolved.work_id} are open', earlier=earlier)
    return state


# ---------------------------------------------------------------------------
# The writes

@dataclass(frozen=True)
class ResultOutcome:
    """What a run of the path did: ``confirmed`` (this run), or ``already-confirmed`` (no call made)."""
    outcome: str
    attempt_id: str
    receipt: dict
    report: dict | None = None
    pushed: bool = False
    opened: bool = False


def _unsettled(integration_store, key: str, actor: str, step: str, cause: str, **context):
    held = integration_store.get(key)
    if held is not None and held.state == 'dispatched':
        di._mark(integration_store, key, 'dispatched', 'unknown', actor, f'{step}-unsettled',
                 {'step': step, 'cause': cause})
    return _refused('RESULT_WRITE_UNSETTLED', f'the {step} was not settled ({cause}): the result journal is unknown; '
                    'the next run reads Gitea\'s actual state', step=step, cause=cause, **context)


def push_branch(verified, target: GiteaTarget, delivery) -> None:
    """``work/<attempt id>`` at the verified commit, pushed from the verified repository as the bot (fast-forward
    only: the branch is new)."""
    opened = _open(verified)
    try:
        update = opened.push(target.git_url, f'{verified.commit}:{verified.ref}', credential=delivery.credential())
    finally:
        opened.close()
    if update.new != verified.commit or update.old not in (None, verified.commit):
        raise AR._repository_access().RepositoryError('PUSH_REJECTED', f'the push answered {update!r}')


def publish_result(integration_store, operation_key: str, *, verified, native, provider, target: GiteaTarget,
                   actor: str, observations: Mapping | None = None, extra_texts: Mapping[str, str] | None = None,
                   report_dir: Path | None = None,
                   read_artifact: Callable[[str], bytes] | None = None) -> ResultOutcome:
    """The result path of a verified, reserved result (the module docstring's points 1 to 7). NATIVE is the
    dispatcher's held native token (searched with, never sent); PROVIDER the credential provider of the stage bot's
    entry; OBSERVATIONS the run driver's (JSON data, in the report); EXTRA_TEXTS more texts the caller writes or sends
    with the result (searched too); REPORT_DIR, when given, receives report.json and report.md (exclusive create)
    after the final search.

    E-01.8 (the I1 integration design, R8 point 5, R11): the attempt's bound authority is the one the verified result
    carries (the attempt run's client established it from the pinned route allowlist); given READ_ARTIFACT it is
    also read from that allowlist here and must agree (RESULT_NOT_RESERVED). TARGET and PROVIDER must declare it
    (RESULT_TARGET_AUTHORITY_MISMATCH, CREDENTIAL_AUTHORITY_MISMATCH) before anything is read or written; the
    receipt, the Owner report and the pull request body carry it when it is not live."""
    resolved, attempt_id = _attempt_checks(integration_store, operation_key, verified)
    bound = verified.authority
    if read_artifact is not None and di.attempt_authority(resolved, read_artifact) != bound:
        raise _refused('RESULT_NOT_RESERVED', f'the verified result carries authority {bound!r}, not the one attempt '
                       f'{attempt_id}\'s pinned route allowlist declares')
    di.require_authority(target, bound, 'RESULT_TARGET_AUTHORITY_MISMATCH', 'the Gitea target')
    di.require_authority(provider, bound, 'CREDENTIAL_AUTHORITY_MISMATCH', 'the credential provider')
    key, held = _journal(integration_store, operation_key, verified)
    if held.state == 'confirmed':
        return ResultOutcome('already-confirmed', attempt_id, receipt(integration_store, attempt_id))
    if held.state == 'failed':
        raise _refused('RESULT_JOURNAL_FAILED', f'{key} is failed',
                       failed=_detail(integration_store, key, 'failed'))
    if target.repository_id != resolved.repository \
            or ADMITTED_REPOSITORIES.get(resolved.repository) != target.full_name:
        raise _refused('RESULT_REPOSITORY_NOT_ADMITTED', f'{target.full_name!r} is not the admitted Gitea repository '
                       f'of {resolved.repository!r}')
    read = read_verified(verified, resolved)
    if read.base_tree == verified.tree:
        if held.state == 'reserved':
            di._mark(integration_store, key, 'reserved', 'failed', actor, 'RESULT_EMPTY_CHANGE',
                     {'code': 'RESULT_EMPTY_CHANGE', 'tree': verified.tree})
        raise _refused('RESULT_EMPTY_CHANGE', f'the result tree {verified.tree} is the base\'s: nothing is written')
    refs = lineage_refs(resolved, verified)
    tests_text, tests = test_section(verified.tests)
    excluded_text, excluded = exclusion_section(verified)
    title = pull_title(read)
    body = pull_body(resolved, verified, target, refs, tests_text, excluded_text)
    draft = owner_report(resolved, verified, target, read, refs, tests=tests, excluded=excluded,
                         tests_text=tests_text, excluded_text=excluded_text, pull=None, search=None,
                         observations=observations)
    draft_json, draft_md = report_texts(draft)
    texts = {'pr-title': title, 'pr-body': body, 'commit-message': read.message, 'diff': read.diff['text'],
             'report-json-draft': draft_json, 'report-md-draft': draft_md,
             'journal-intent': _canonical(journal_intent(operation_key, verified))}
    if isinstance(verified.tests.get('output'), str):
        texts['test-output'] = verified.tests['output']
    if verified.excluded:
        texts['excluded-paths'] = _canonical(list(verified.excluded))
    for label, text in (extra_texts or {}).items():
        if label in texts or not isinstance(text, str):
            raise ValueError(f'an extra text {label!r} is not a new label with text')
        texts[label] = text
    expected = AE.native_fingerprint(integration_store, operation_key)
    before = require_not_found(outbound_search(native, expected_fingerprint=expected, texts=texts,
                                               bundle_path=verified.staged, bundle_sha256=verified.bundle_sha256),
                               bundle_sha256=verified.bundle_sha256, texts=texts)
    branch = verified.ref[len('refs/heads/'):]
    with AT.attempt_role_token(integration_store, operation_key, provider=provider, port=target.port,
                               http=target.http) as delivery:
        session = AT.ResultSession(delivery, repository=target.full_name, port=target.port, http=target.http)
        state = reconcile(session, integration_store, resolved, verified, title=title, body=body)
        if integration_store.get(AE.END_KEY.format(attempt_id=attempt_id)) is not None:
            raise _refused('ATTEMPT_ENDED', f'attempt {attempt_id} was ended meanwhile: nothing is written')
        current = integration_store.get(key).state
        if current == 'reserved':
            di._mark(integration_store, key, 'reserved', 'dispatched', actor, 'push',
                     {'search': before, 'push': state.push, 'open': state.open, 'baseHead': state.base_head})
        elif current == 'dispatched':            # a run that stopped after the dispatch: settled by this reading
            di._mark(integration_store, key, 'dispatched', 'unknown', actor, 'resumed',
                     {'step': 'resumed', 'cause': 'a run stopped after the dispatch'})
        pushed = opened = False
        if state.push:
            try:
                push_branch(verified, target, delivery)
            except Exception as exc:  # noqa: BLE001 - refused or lost: settled by the next run's reading
                raise _unsettled(integration_store, key, actor, 'push',
                                 str(getattr(exc, 'code', type(exc).__name__))[:64]) from None
            pushed = True
        pull = state.pull
        if state.open:
            try:
                status, pull = session.call('POST', f'/repos/{target.full_name}/pulls',
                                            {'head': branch, 'base': BASE_BRANCH, 'title': title, 'body': body})
            except DispatchRefused:
                raise
            except Exception as exc:  # noqa: BLE001 - the answer was lost: it may have been opened
                raise _unsettled(integration_store, key, actor, 'pull-request', type(exc).__name__) from None
            if status != 201 or not isinstance(pull, dict) or type(pull.get('number')) is not int:
                raise _unsettled(integration_store, key, actor, 'pull-request', f'HTTP {status}')
            opened = True
        # the read-back (a read that is not answered leaves the journal to the next run's reading)
        try:
            head = branch_head(session, target.full_name, branch)
            seen = pull_of(session, target.full_name, branch)
        except DispatchRefused as refusal:
            raise _unsettled(integration_store, key, actor, 'readback', refusal.code) from None
        problems = [] if head == verified.commit else [f'{branch} is at {head}']
        if seen is None or seen.get('number') != pull.get('number'):
            problems.append('the pull request does not read back by its base and head')
        else:
            problems += pull_problems(seen, repository=target.full_name, branch=branch, commit=verified.commit,
                                      user=session.user, title=title, body=body if opened else None)
        if problems:
            if integration_store.get(key).state == 'dispatched':
                di._mark(integration_store, key, 'dispatched', 'unknown', actor, 'readback',
                         {'step': 'readback', 'cause': 'RESULT_READBACK'})
            raise _refused('RESULT_READBACK', '; '.join(problems)[:500])
        number = seen['number']
        bot = session.user
    pull_record = {'number': number, 'url': target.pull_url(number), 'state': 'open', 'draft': True}
    report = owner_report(resolved, verified, target, read, refs, tests=tests, excluded=excluded,
                          tests_text=tests_text, excluded_text=excluded_text, pull=pull_record, search=before,
                          observations=observations)
    report_json, report_md = report_texts(report)
    made = {'format': RECEIPT_FORMAT, 'operationKey': operation_key, 'attemptId': attempt_id, **refs,
            'repository': resolved.repository, 'giteaRepository': target.full_name, 'branch': branch,
            'ref': verified.ref, 'base': verified.base, 'commit': verified.commit,
            'pullRequest': {**pull_record, 'title': title, 'author': bot,
                            'bodySha256': _sha256(_normal(seen.get('body')) or '')},
            'bundle': {'sha256': verified.bundle_sha256, 'bytes': verified.bundle_bytes},
            'trailers': read.trailers, 'wrote': {'push': pushed, 'pullRequest': opened},
            'tests': {'status': tests['status'], 'outcome': tests['outcome'], 'outputDigest': tests['outputDigest']},
            'report': {'jsonSha256': _sha256(report_json), 'markdownSha256': _sha256(report_md)},
            'search': {'before': before}, **di.authority_label(bound)}
    final_texts = {'report-json': report_json, 'report-md': report_md, 'receipt': _canonical(made)}
    after = require_not_found(outbound_search(native, expected_fingerprint=expected, texts=final_texts),
                              bundle_sha256=None, texts=final_texts)
    made['search']['after'] = after
    from_state = integration_store.get(key).state
    di._mark(integration_store, key, from_state, 'confirmed', actor, 'read-back', made)
    if report_dir is not None:
        write_report(report_dir, report_json, report_md)
    return ResultOutcome('confirmed', attempt_id, receipt(integration_store, attempt_id), report=report,
                         pushed=pushed, opened=opened)


def write_report(directory, report_json: str, report_md: str) -> dict:
    """report.json and report.md in DIRECTORY, each created exclusively (an existing file with the same bytes is
    kept; another is never overwritten: ValueError)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, text in (('report.json', report_json), ('report.md', report_md)):
        data = text.encode('utf-8')
        path = directory / name
        try:
            with open(path, 'xb') as handle:
                handle.write(data)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f'{path} exists with other bytes: a report is never overwritten') from None
        written[name] = {'path': str(path), 'sha256': _sha256(data)}
    return written
