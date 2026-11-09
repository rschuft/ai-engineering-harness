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
task, together with those pointers. It is Python standard library only, plus the shared
repository-access module (Dulwich, from the Python tools set): it starts no git.

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

**Repository access (plan leaves F-09.4 and F-10.3).** `Git` is a facade over the shared
repository-access module, [`integrations/repository/`](../repository/README.md) ([decision
0014](../../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md)): every
answer is read in this process from the repository's own files, over Dulwich 1.2.21, and the
adapter starts no git process. Making a `Git` is the work-tree check (`CannotRun` when the
project is not inside a git work tree, or when Dulwich is not importable:
`REPOSITORY_NEEDS_DULWICH`, naming `task tools:install`; run the adapter with the tools
interpreter, `python -I -B integrations/paths/tools_install.py --python`). Reads (`commit`,
`object_type`, `object_kind`, `blob`, `files`, `export_tree`) go through one opened repository
per read session (`Git.session()`), which one command, one `create`, one `resolve` or one
readiness read opens and closes. Within a session, objects named by a full commit id (`<id>` or
`<id>:<path>`) and file lists of a full commit id are read once, and each revision is resolved
once (a snapshot for the session); nothing is kept after it, and a read after the session's end
fails closed (`GIT_FAILED`). Every repository is opened under the `repository` configuration
policy (decision 0014 section 5: its own `config` only; `Git.config_sources` lists the files
read): no answer the adapter gives depends on a user or system setting.

The calls and codes are those of the git commands they replace, held to git's answers by tests:
`commit` answers as `rev-parse --verify <rev>^{commit}`, `object_type` and `object_kind` as
`cat-file -t`, `blob` as `cat-file blob`, `files` as `ls-tree -r --name-only`. A revision or
object name is checked before anything is opened: empty text, a leading `-`, a C0 control
character or DEL (and, for a revision, any whitespace) is `REVISION_INVALID` or
`OBJECT_NAME_INVALID`, as before, and so is every form decision 0014 lists as a documented
gap (`:/<text>`, `<rev>^{/<regex>}`, `@{<date>}`, `@{upstream}`, `@{push}`, `@{-N}`, ranges),
`REVISION_INVALID`. "No such object" and an ambiguous abbreviation answer `None`. A repository
that cannot be read (a damaged object, content that does not hash to its id, an unreadable
file) is `GIT_FAILED`, naming the object, at once: reads raise no `subprocess.TimeoutExpired`.
The module's local codes (`REPLACE_REFS_UNSUPPORTED`, `EXPORT_REFUSED`, and the others its
README lists) pass through unchanged.

`export_tree` writes an export of the exact revision (decision 0014 section 4): each file's
blob bytes, with no end-of-line conversion and no attributes (`export-ignore` files included);
it replaces `git archive`, whose output followed the host's `core.autocrlf` (CRLF on a Windows
host configured so, LF elsewhere). OpenSpec (`instructions apply`) and Backlog.md (`task view`,
for a pinned lineage reference) read such exports.

**Process trees.** The adapter still starts the upstream command-line tools, Backlog.md and
OpenSpec, and each runs as one process tree (`ProcessTree`, `run_tree`), with the
`TOOL_TIMEOUT_S` ceiling: a command on `PATH` may be a launcher that runs the real program as
its child (an npm shim such as `backlog.CMD`, which runs node through `cmd.exe`; Git for
Windows' `cmd\git.exe`), and a kill, a timeout, an exception or the close ends that child too
and waits for it. On Windows the process joins a job object (kill on close) before its first
instruction runs; on POSIX it leads a new session whose process group is killed.

**Operations.** One top-level adapter operation (`operation()`) is one lineage traversal, one
readiness evaluation (`planning_readiness.read_readiness`, and so one dispatch read), or one
resolution from the command line (`resolve`, `pointer`) or a lineage resolver entry point.
Within it, each project's repository access is one `Git` (`project_git`: one work-tree check)
with one read session (one opened repository), and Backlog.md's reads are a snapshot: the same `task
list` or `task view` in the same directory is run once, and a `task create` ends that
snapshot. Everything is dropped when the operation ends, normally or by an exception; nothing
is kept at module level or for the next operation.

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
| `tests/test_planning_adapter.py` | Offline: pointer format and resolution, the visible failures, plan refusals, the checklist and tracking refusals, no status in any Backlog.md command or result, partial failure, the command line. Backlog.md is `tests/fake_backlog.py`, OpenSpec `tests/fake_openspec.py`. It also re-resolves the committed capture against a freshly built design repository. Needs the tools interpreter (Dulwich); git builds the fixture repositories. |
| `tests/test_git_batch.py` | Offline, under the tools interpreter, with git as the oracle (F-09.4's test ids, retargeted at F-10.3): the facade's answers equal the one-shot git commands' (revisions, object types, blobs, file lists, an ambiguous prefix, names with spaces); refused names and revisions open and read nothing; the session's repository is closed on a normal exit and on an exception, and a read after it fails closed; a damaged repository (an object file that is a directory, a corrupt zlib stream, another object's content) and one that went away are `GIT_FAILED` at once, naming the object; no memo outlives its session; one operation shares one `Git` and one opened repository, its Backlog.md reads are made once, and all of it ends with the operation. The upstream CLIs run on `run_tree`, and through a stand-in launcher, and Git for Windows' own where it is installed, a kill, a timeout, an exception and a normal close end the launcher's child. |
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
  there only. Since F-10.3 they read blob-bytes exports (LF where the repository stores LF) on a host
  whose git converts to CRLF; repository access and process trees on Linux and macOS are
  not yet verified (F-10.5).
- Backlog.md's MCP surface (the CLI is used), concurrent edits by several writers,
  and Backlog.md's cross-branch task lookup (`check_active_branches` was off).
- A design kept in a repository other than the Backlog.md project's.
- The ambiguous (duplicate-id) dependency, the archived dependency and the demoted
  dependency were observed in live probes only; they have no recorded fixture.
- Readiness under concurrent edits (the read is not atomic) and with
  `check_active_branches` on.
