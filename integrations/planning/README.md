# Planning adapter

Plan leaf P-02.1, blueprint section
[`#authority`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#authority).
OpenSpec owns the accepted objective and the design. Backlog.md owns tasks,
dependencies and status, and "updates use its commands"
([`#architecture`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#architecture)).
This adapter is the small resolver between them. It turns a task plan for one
OpenSpec change into Backlog.md tasks through Backlog.md's command line, and gives
each task source pointers that resolve the exact design revision (P-02.1). Its
readiness read (P-02.2) reports Backlog.md's own readiness and dependency states per
task, together with those pointers. It is Python standard library only, plus git.

It does not adopt Backlog.md or OpenSpec for this repository. Both run only in a
managed project's repository (in the tests, a throwaway one).

## What it does and does not do

| It does | It never does |
|---|---|
| Run `backlog task create` with `--ref` (one per pointer) and `--dep`, then read each task back with `backlog task view <id> --json` and check its title, references and dependencies | Write or read Backlog.md's markdown files |
| Take the new task's id from Backlog.md's own `task list --json`, before and after | Pass `-s`/`--status`, run `task edit`, or derive, mirror or report a status: Backlog.md assigns its default status and alone changes it |
| Refuse an OpenSpec change that has a `tasks.md`, or whose schema declares `apply.tracks` | Create or edit OpenSpec artifacts |
| Re-resolve every pointer of a task and fail visibly | Compute readiness or the dependency graph: `planning_readiness.py` only reads Backlog.md's |

The `Backlog` wrapper allows only `task create`, `task list` and `task view`, and
refuses a status option before it runs anything.

## Source pointer

```
openspec:changes/<change-id>/<artifact-path>@<commit>#sha256=<digest>
```

| Part | Rule |
|---|---|
| `<change-id>` | An OpenSpec change name, kebab-case (`[a-z0-9]+(-[a-z0-9]+)*`). |
| `<artifact-path>` | Relative to `openspec/changes/<change-id>/`, `/`-separated, no `.` or `..` part, no comma (Backlog.md splits references on commas), no space. |
| `<commit>` | The full commit id of the design revision: 40 hex digits, or 64 in a SHA-256 repository. Never a branch name or an abbreviation. |
| `<digest>` | The sha256 of the artifact's blob bytes in that commit (`git cat-file blob <commit>:<path>`), 64 lowercase hex digits. |

It extends the blueprint's notation `openspec:changes/<name>@<sha>` with the
artifact and its digest. A pointer resolves in the project's own git repository,
the one that holds both `openspec/` and Backlog.md's directory. A design kept in
another repository is not supported.

Resolving a pointer reads only git objects, never the working tree:

| Failure | When |
|---|---|
| `POINTER_MALFORMED` | The text breaks a rule above. |
| `POINTER_REVISION_MISSING` | The repository has no such commit (for example after a history rewrite). |
| `POINTER_ARTIFACT_MISSING` | The commit has no file at that path. |
| `POINTER_DIGEST_MISMATCH` | The file's bytes at that commit do not have the recorded sha256. |
| `POINTER_ABSENT` | A planned task names no artifact, or a Backlog.md task carries no `openspec:` reference (missing provenance). |

A later design revision does not change a task's pointer: the task keeps naming the
revision it was planned from, and a pointer made at the new revision has a
different digest. Revalidation is therefore visible, never silent.

**Git access (plan leaf F-09.4).** `Git` reads objects (`commit`, `object_type`,
`object_kind`, `blob`) through git's own batch protocol: one `git cat-file --batch` process
per read session (`Git.session()`), which one command, one `create`, one `resolve` or one
readiness read opens and closes. Within a session, objects named by a full commit id
(`<id>` or `<id>:<path>`) and file lists of a full commit id are read once, and each
revision is resolved once (a snapshot for the session); nothing is kept after it. A name or
revision holding whitespace or a control character, or starting with `-`, is refused
(`OBJECT_NAME_INVALID`, `REVISION_INVALID`) before it reaches the process. Each request has
the `TOOL_TIMEOUT_S` ceiling: past it the process is killed, `subprocess.TimeoutExpired` is
raised as before, and every later read of the session fails closed (`GIT_FAILED`). The
reader answers as the one-shot commands it replaces (`rev-parse --verify --quiet
<rev>^{commit}`, `cat-file -t`, `cat-file blob`; tested), with the same git and the same
environment; the work-tree check (`rev-parse --show-toplevel`), `ls-tree` and `archive`
still run as single commands.

## Plan

```json
{
  "format": "planning-map/v1",
  "change": "<change-id>",
  "tasks": [
    {"key": "first", "title": "...", "description": "...", "artifacts": ["design.md"]},
    {"key": "second", "title": "...", "artifacts": ["design.md", "specs/x/spec.md"], "depends_on": ["first"]}
  ]
}
```

Tasks are created in order. `depends_on` names earlier keys only, so the plan is
acyclic by construction; the adapter passes Backlog.md the ids it created. Any
other key is refused (`PLAN_INVALID`); a status-like key (`status`, `state`,
`done`, `completed`, `complete`, `checked`, `progress`) is refused as
`STATUS_NOT_OWNED`. The revision comes from the command line and is recorded as a
full commit id.

Before any Backlog.md command, `create` checks the change at that revision:
`CHANGE_MISSING`, `OPENSPEC_CHECKLIST_PRESENT` (a `tasks.md` in the change) and
`OPENSPEC_TRACKING_CONFIGURED` (the schema in `openspec/schemas/<name>/` declares
`apply.tracks`). When the schema is not in the repository, it refuses with
`OPENSPEC_TRACKING_UNKNOWN` unless `--openspec` is given. With `--openspec`, it
exports `openspec/` at the revision into a temporary directory, runs
`openspec instructions apply --change <id> --json` there, and requires
`taskTrackingConfigured: false` and no tasks. A task that maps the same title and
pointers again is refused (`BACKLOG_DUPLICATE`). A Backlog.md failure part way is
reported with the tasks already created; they stay in Backlog.md and are not
rolled back.

## Readiness (P-02.2)

`planning_readiness.py` reads Backlog.md's own readiness and reports it per task. It
never computes readiness: it does not read a status for a verdict, walk the graph or
compare dependencies. It runs only `task list --json` and `task view <id> --json`.

What Backlog.md 1.55.3 reports (observed live, `schemaVersion` 1):

| Field | Where | Meaning as observed |
|---|---|---|
| `isReady` | each task in `task list --json`, and the task in `task view --json` | Backlog.md's verdict. `task list --ready` lists exactly these tasks. |
| `readiness.isReady`, `readiness.isBlocked` | `task view --json` | `isBlocked` is true when a dependency is unfinished or unresolved. A finished or archived task reports `isReady: false`, `isBlocked: false`. |
| `readiness.blockingDependencies` | `task view --json` | Ids of dependencies that exist and are not finished. |
| `readiness.missingDependencies` | `task view --json` | Ids of dependencies that do not resolve: absent, or ambiguous (two tasks share the id). |
| `dependencyGraph.nodes[].state` | `task view --json` | `resolved`, `missing` (title and status `null`) or `ambiguous`. |

Backlog.md does not let a missing reference be created directly. `task create --dep`
refuses an id that does not exist ("The following dependencies do not exist").
`task delete` and `task demote` remove the dependencies other tasks hold on the task. An
archived dependency stays resolved: it blocks while unfinished and counts as done once
finished. A missing reference arises when work from two branches meets. For example,
one branch adds a task that depends on TASK-2, another archives and deletes TASK-2, and
git merges both. Two branches that each create the same id give an `ambiguous` node
reported in `missingDependencies`; `task list --json` then refuses to run (exit 1, a
duplicate-id warning), and the readiness read fails visibly with `BACKLOG_FAILED`.

A task is **eligible** only when Backlog.md reports it ready (`readiness.isReady`), its
readiness fields are present, well-formed and agree with one another and with the task
list, and every OpenSpec source pointer it carries resolves (unless `--no-pointers`).
Each reason names the Backlog.md field or the pointer check it reports:

| Reason | From | Exit 1 |
|---|---|---|
| `BLOCKED_BY_DEPENDENCIES` | `readiness.blockingDependencies` is not empty | no: an ordinary state |
| `NOT_READY` | `isReady` false and neither list set (for example a finished task); Backlog.md says no more | no |
| `MISSING_DEPENDENCIES` | `readiness.missingDependencies` is not empty | yes |
| `READINESS_UNKNOWN` | a readiness field, the task-list `isReady` or the graph is absent or malformed | yes |
| `READINESS_INCONSISTENT` | Backlog.md's own fields disagree (for example `isReady` in the list and the view) | yes |
| `POINTER_*` | a source pointer does not resolve, or the task has none (`POINTER_ABSENT`) | yes |

Output (`planning-readiness/v1`), one entry per task, with no status:

```json
{"format": "planning-readiness/v1", "eligible": ["TASK-2"],
 "tasks": [{"id": "TASK-3", "eligible": false, "reasons": ["MISSING_DEPENDENCIES"],
            "blocking_dependencies": [], "missing_dependencies": ["TASK-2"],
            "graph_unresolved": [{"id": "TASK-2", "state": "missing"}],
            "backlog_readiness": {"isReady": false, "isBlocked": true,
                                  "blockingDependencies": [], "missingDependencies": ["TASK-2"]},
            "pointers": [{"pointer": "openspec:changes/...", "resolved": true}]}]}
```

`backlog_readiness` is Backlog.md's object unchanged, and the lists are `null` when
the readiness is unknown. Each failing task is printed as `FAIL <id>: <reason>` on
stderr. The read takes a task list and then one view per task, so it is not an
atomic snapshot: an edit between them can show as `READINESS_INCONSISTENT`.

## Commands

Run from the repository root (`python3` outside Windows). `CMD` is a Backlog.md or
OpenSpec executable, or its `.js` entry point, which runs with `node`:

```
python -I -B integrations/planning/planning_adapter.py create --project DIR --plan FILE --revision REV --backlog CMD [--openspec CMD]   # task planning:create
python -I -B integrations/planning/planning_adapter.py resolve --project DIR --backlog CMD [--task ID ...]                             # task planning:resolve
python -I -B integrations/planning/planning_adapter.py resolve --project DIR --pointer P [--pointer P ...]
python -I -B integrations/planning/planning_adapter.py pointer --project DIR --change ID --artifact PATH --revision REV
python -I -B integrations/planning/planning_readiness.py --project DIR --backlog CMD [--task ID ...] [--no-pointers]           # task planning:readiness
python -I -B -m unittest discover -s integrations/planning/tests -v                                                                   # task planning:test
```

Exit status: 0 PASS, 1 FAIL (`FAIL <CODE>: ...` on stderr), 2 could not run. The
adapter runs tools with `OPENSPEC_TELEMETRY=0` and `DO_NOT_TRACK=1`.

## Installing the pinned tools

Backlog.md 1.55.3 and OpenSpec 1.16.0 are already in the component lock,
[`composition/lock/npm/`](../../composition/lock/npm/), with their npm integrity
hashes; this leaf adds no lock. Install them in a directory outside the checkout,
with an empty npm configuration and install scripts off:

```
cp composition/lock/npm/package.json composition/lock/npm/package-lock.json <dir>/
cd <dir>
npm ci --ignore-scripts --no-audit --no-fund --registry https://registry.npmjs.org/ \
  --cache <empty dir> --userconfig <empty file> --globalconfig <another empty file>
```

`npm ci` checks every tarball against the lock's integrity. Backlog.md's wrapper
(`node_modules/backlog.md/cli.js`) needs no install script: npm installs the
platform package for the host from `optionalDependencies` (on Windows x64,
`backlog.md-windows-x64`, which holds `backlog.exe`), and the wrapper finds it at
run time. Then:

```
BACKLOG=<dir>/node_modules/backlog.md/cli.js
OPENSPEC=<dir>/node_modules/@fission-ai/openspec/bin/openspec.js
```

## Tests and fixtures

| Path | What |
|---|---|
| `tests/test_planning_adapter.py` | Offline: pointer format and resolution, the visible failures, plan refusals, the checklist and tracking refusals, no status in any Backlog.md command or result, partial failure, the command line. Backlog.md is `tests/fake_backlog.py`, OpenSpec `tests/fake_openspec.py`. It also re-resolves the committed capture against a freshly built design repository. Needs git only. |
| `tests/test_git_batch.py` | Offline, git only: the batch reader's answers equal the one-shot commands' (revisions, object types, blobs, file lists, an ambiguous prefix), names that could break the line protocol are refused and never written, the reader process ends on a normal exit, an exception and a timeout (killed, then failing closed), an out-of-protocol answer or an exited reader fails closed, and no memo outlives its session. Stand-in processes play a git that hangs or answers out of protocol. |
| `tests/test_live_backlog.py` | Live, against the pinned tools; skipped unless `AIEH_BACKLOG` and `AIEH_OPENSPEC` name their entry points. Checks the versions, regenerates the capture and compares it with the committed one, changes a status through Backlog.md and a design revision through git and shows that neither the adapter nor OpenSpec touches the status, refuses a change with a `tasks.md`, and shows each broken pointer edited in through Backlog.md failing visibly. |
| `tests/two_task_fixture.py` | Builds the throwaway design repository and records the capture (`--record`). |
| `tests/test_readiness.py` | Offline: Backlog.md's recorded readiness JSON replayed by the fake (`FAKE_BACKLOG_SNAPSHOT`). The report equals the recorded one, and the eligible tasks equal Backlog.md's own `task list --ready`. A blocked chain stays ineligible and a missing dependency is visible. Absent or malformed fields are unknown, and disagreeing fields are inconsistent. A failing or absent pointer is never eligible. Backlog.md's verdict wins over contrary statuses, and a trap fails the test if any `status` or `completed` field is read. The read issues only `task list` and `task view`. |
| `tests/readiness_fixture.py` | Builds the three readiness stages from the two-task fixture with Backlog.md's CLI and git only, and records them (`--record`). |
| `tests/fixtures/readiness/` | `blocked/` (TASK-2 blocked by TASK-1), `unblocked/` (TASK-1 set to Done through `backlog task edit` by the test acting as the Backlog.md owner; TASK-2 eligible), `missing/` (TASK-3, added on a branch, depends on TASK-2, which was archived and deleted on `main`; merged). Each holds Backlog.md's `task list --json`, `task list --ready --json` and `task view --json` output and `readiness.json`. |
| `tests/fixtures/two-task/` | `plan.json` (two tasks, the second depending on the first), `design.md` (written for this leaf to complete the P-01.2 change `qual-02-search-freshness`), and `recorded/`: Backlog.md's own `task list --json` and `task view --json` output and the adapter's result, with creation times replaced by `<timestamp>`. No machine path. |

The design repository holds the P-01.2 change (proposal and delta spec, from
`tools/tests/fixtures/intent_qualification/openspec/`), the catalog's
`intent-driven` schema and the fixture's `design.md`, committed with a fixed
identity and date. Its commit id is therefore reproducible, and the recorded
pointers name it. If any of those inputs changes, the offline test fails and the
capture must be re-recorded:

```
python -I -B integrations/planning/tests/two_task_fixture.py --backlog BACKLOG --openspec OPENSPEC --record
python -I -B integrations/planning/tests/readiness_fixture.py --backlog BACKLOG --openspec OPENSPEC --record
```

The live tests also regenerate the three readiness stages and compare them with the
recorded ones, and run `planning_readiness.py` on the `missing` stage (exit 1,
`FAIL TASK-3: MISSING_DEPENDENCIES TASK-2`).

## Not yet verified

- Any host but Windows 11 x86_64 (Node 24.19.0, git 2.52.0): the live tests ran
  there only.
- Backlog.md's MCP surface (the CLI is used), concurrent edits by several writers,
  and Backlog.md's cross-branch task lookup (`check_active_branches` was off).
- A design kept in a repository other than the Backlog.md project's.
- The ambiguous (duplicate-id) dependency, the archived dependency and the demoted
  dependency were observed in live probes only; they have no recorded fixture.
- Readiness under concurrent edits (the read is not atomic) and with
  `check_active_branches` on.
