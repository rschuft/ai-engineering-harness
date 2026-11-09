# Repository access

The shared repository-access module for AI Engineering's own Python components (plan leaf F-10.2,
[decision 0014](../../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md),
Proposed): read-only access to git repositories over
[Dulwich](https://www.dulwich.io/) 1.2.21, pinned in the Python tools set
([`composition/lock/python/tools-requirements.txt`](../../composition/lock/python/tools-requirements.txt)),
and the differential contract suite that holds it to git's answers.

- [`repository_access.py`](repository_access.py): the module. It launches **no process**; every
  answer comes from the repository's own files, in the calling process.
- [`tests/`](tests/): the contract suite. The recorded half runs without git; the git-oracle half
  asks git again where git is on `PATH`.

**No caller uses it yet.** F-10.3 makes the planning adapter's `Git` a facade over it and F-10.4
migrates the exchange push, the snapshots and the listing (decision 0014 section 1).

## Use

```python
import repository_access as ra

with ra.open_repository(path, config='repository') as repo:   # config: 'host', 'repository' or 'none'
    repo.commit('HEAD~1')            # full commit id, as git rev-parse --verify 'HEAD~1^{commit}'; None if none
    repo.read('HEAD:docs/a b.md')    # (oid, type, bytes), as git cat-file; None if none
    repo.files(commit, 'openspec/changes')   # git ls-tree -r --name-only <commit> -- <dir>/
    repo.export_tree(commit, 'openspec', empty_directory)
```

| Call | Answers as | Notes |
|---|---|---|
| `open_repository(path, *, config, work_tree=True)` | `git rev-parse --show-toplevel` (acceptance) | The work-tree check: any directory inside a work tree, a linked worktree, a separate git directory's work tree. A bare repository, a `.git` directory or anything inside it, and a non-repository are `CannotRun` `NOT_A_WORK_TREE`. With `work_tree=False` a git directory is accepted (`NOT_A_REPOSITORY` otherwise). `config` is required. |
| `commit(revision)` | `git rev-parse --verify <revision>^{commit}` | Full id or `None`. |
| `object_id(name)`, `object_kind(name)`, `read(name)` | `git cat-file -t` / `cat-file --batch` | `None` when the repository has no such object, or an abbreviation is ambiguous. |
| `blob(commit, path)` | `git cat-file blob <commit>:<path>` | The bytes; `GIT_FAILED` when there is no such blob (as the planning adapter today). |
| `files(commit, directory)` | `git ls-tree -r -z --name-only <commit> -- <directory>/` | Paths in git's order; `[]` when the directory is absent or not a directory. `directory` is a literal repository-relative path. |
| `export_tree(commit, subtree, destination)` | blob bytes (section 4) | See [Export](#export). Returns `{'files', 'links', 'directories', 'bytes'}`. |
| `head()` | `git rev-parse --verify HEAD`, `git symbolic-ref HEAD` | `Head(commit, ref)`: `commit` is `None` on an unborn branch, `ref` `None` when detached. |
| `status(paths=None, untracked='no')` | `git status --porcelain=v1 -z --no-renames --untracked-files=<untracked> -- :(literal)<paths>` | `StatusEntry(xy, path)`: tracked changes, then untracked entries (`??`, a collapsed directory ends with `/`), each sorted. |
| `index_entries()` | `git ls-files -s -z` | `IndexEntry(mode, oid, stage, path)`, one per stage, in index order. |
| `listing(cached=True, others=False, exclude_standard=False)` | `git ls-files -z [--cached] [--others] [--exclude-standard]` | Untracked paths first (sorted; a nested repository as `dir/`), then the index entries. |
| `write_bundle(refs, destination)` | `git bundle create` | A complete bundle (no prerequisites) of full reference names; see [Bundles](#bundles). |
| `parse_bundle_header(path)`, `pack_trailer(path, header)` | the bundle format | Module functions: the checks `tools/guest.py` makes today, here for F-10.4 to switch it over (`BUNDLE_INVALID` where it raises `Refused`). |
| `config_sources` | | The configuration files read, in reading order. |

Paths and names are `str`; the repository's bytes are decoded as UTF-8 (undecodable bytes with
`surrogateescape`).

## The revision grammar (decision 0014 section 2)

Every form git resolves today is implemented over Dulwich, following git's own resolution order
(`object-name.c`): a full id (40 or 64 hex digits, upper case accepted); an abbreviation of at
least 4 digits, unique or made unique by git's own hint (`<abbrev>^{commit}`, `<abbrev>~N` and
`<abbrev>:<path>` prefer the one commit or tree-ish, as git does); `HEAD` and `@`; references by
full or short name in git's order (`<n>`, `refs/<n>`, `refs/tags/<n>`, `refs/heads/<n>`,
`refs/remotes/<n>`, `refs/remotes/<n>/HEAD`); `~N`, `^N`, `^` and their chains; `^{commit}`,
`^{tree}`, `^{blob}`, `^{tag}`, `^{object}` and `^{}`; `<rev>:<path>` (spaces and non-ASCII,
`./` and `../` from the work-tree root, `<rev>:` for the root tree); `:<path>` and `:<n>:<path>`
from the repository's index; `<ref>@{N}`, `@{N}` and `@@{N}` from the reflog.

Forms git resolves that 0014's enumeration does not name are implemented too, because they are not
gaps: `git describe` output (`<anything>-<number>-g<hex>`, git 2.52's rule); `^{object}`; root
references (`ORIG_HEAD`, `FETCH_HEAD`, `MERGE_HEAD`) and `main-worktree/HEAD`; and git's quirks,
such as `HEAD^{commit}x}` (the peel is read by prefix).

**Refused before any repository access, with `REVISION_INVALID`** (`gap_form`, `check_revision`,
`check_object_name`): the gap forms of 0014, recognised in the revision part of a name (the text
before its first `:` outside braces):

| Gap | Recognised as |
|---|---|
| `:/<text>` | a name starting with `:/` and longer than `:/` |
| `<rev>^{/<regex>}` | `^{/` in the revision |
| `<ref>@{<date>}` | an `@{...}` mark that is not a number below 100000000 (git reads larger numbers as a time), including the empty `@{}` |
| `@{upstream}`, `@{u}`, `@{push}` | those marks, in any case |
| `@{-N}` | an `@{-...}` mark |
| ranges | a revision starting with `^`, holding `..`, or ending with `^@`, `^!` or `^-N` |

And, as today, empty text, a leading `-`, whitespace (revisions only: object names keep spaces),
a C0 control or DEL, and text that is not encodable: `REVISION_INVALID` for a revision,
`OBJECT_NAME_INVALID` for an object name. A gap form inside an object name is
`REVISION_INVALID` too.

Local mechanics decided here (0014 leaves them open):

- **The date fallback.** When a name holding a numeric `@{N}` does not resolve otherwise, git
  rereads everything after its last `@{` as a date (`main@{0}:README.md` asked as a commit,
  `main@{3}~1` past the root, `main@{1}x`), so its answer depends on the clock and the time zone.
  The module refuses such a name with `REVISION_INVALID` (the `@{<date>}` gap) at the point git
  would read the date, which is after the failed resolution, not before any access: the shape is
  only known then. The corpus lists these forms (`fallback_commits`, `fallback_names`).
- **References are read from the repository's files** as git's files backend reads them: loose
  before packed, five symbolic levels at most, per-worktree names (`HEAD`, one-level upper-case
  names, `refs/bisect/`, `refs/worktree/`, `refs/rewritten/`) from the worktree's git directory.
  Dulwich's reference container refuses names git reads (`refs/<one component>`, `ORIG_HEAD`,
  `FETCH_HEAD`). Every name is checked by git's `check_refname_format` first, so a path never
  leaves the git directory. A repository with another reference storage (reftable) is
  `GIT_FAILED`.
- **Reflogs are parsed by the module**, skipping the lines git skips; Dulwich 1.2.21's
  `read_reflog` fails on a line without a message (git writes one for `worktree add`).
- **Every object read is checked against its id**: Dulwich 1.2.21's `get_raw` does not check a
  loose object's id, and 0014 section 3 accepts the stricter read (G9).
- **Not applied:** replace references (`refs/replace/`), which git applies to every object read
  by default. Grafts and shallow boundaries are applied (Dulwich's `get_parents`). A
  repository using replace references gets the unreplaced objects.

## Errors (decision 0014 section 3)

| Code | Raised as | Meaning |
|---|---|---|
| `REVISION_INVALID` | `RepositoryError` | Not a usable revision, or a gap form; before any access (the date fallback excepted, above). |
| `OBJECT_NAME_INVALID` | `RepositoryError` | Not an object name, or a path argument outside the repository-relative grammar (`files`, `export_tree`, `status`); before any access. |
| `GIT_FAILED` | `RepositoryError` | The repository could not be read: a damaged object (content not hashing to its id, a corrupt zlib stream, a corrupt pack: `details['object']` names it), any Dulwich or OS error at the module boundary, a tree-ish that does not exist (`files`, `export_tree`), a missing blob (`blob`), an unreadable reference or reflog. |
| `EXPORT_REFUSED` | `RepositoryError` | Local: the export cannot be written safely (below). |
| `BUNDLE_INVALID` | `RepositoryError` | Local: an unparsable bundle header, or refused `write_bundle` input (not a full reference name, no such reference, an existing destination). |
| `FILTER_UNSUPPORTED` | `RepositoryError` | Local: `status` meets a path git would pass through a configured filter driver (a process, such as Git LFS) or a `working-tree-encoding`. |
| `NOT_A_WORK_TREE`, `NOT_A_REPOSITORY` | `CannotRun` | The work-tree check. |
| `REPOSITORY_NEEDS_DULWICH` | `CannotRun` | Dulwich is not importable by the running interpreter; the message names `task tools:install` and the interpreter `tools_install.py --python` prints. |

"No such object" and an ambiguous abbreviation answer `None`. No call raises
`subprocess.TimeoutExpired`: there is no process. `close()` never raises (a pack whose read failed
may hold a buffer Dulwich cannot release at once).

## Configuration policy (decision 0014 section 5)

Every `open_repository` names its policy; `config_sources` lists every configuration file read.

| Policy | Applies | Reads |
|---|---|---|
| `host` | The repository's own configuration, then the user and system files located as Dulwich's `StackedConfig.default_backends` locates them (`GIT_CONFIG_GLOBAL`, `~/.gitconfig`, `$XDG_CONFIG_HOME/git/config`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_NOSYSTEM`, `/etc/gitconfig`, and on Windows Git for Windows' `etc/gitconfig`, found through `PATH` or the registry); `core.excludesFile` or `$XDG_CONFIG_HOME/git/ignore`. | All of these that exist. |
| `repository` | The repository's own `config` (and `config.worktree` when `extensions.worktreeConfig` is set), `core.excludesFile` only if that configuration sets it. | Those files. Never `PATH`. |
| `none` | Nothing: git's defaults. | The repository's own `config`, read for its format only (`core.repositoryformatversion`, `extensions.*`, `core.bare`, `core.worktree`), as every git must to open a repository; it is listed. |

The configuration a call applies: `core.autocrlf`, `core.symlinks`, `core.fileMode` (POSIX only;
Windows has no executable bit), `core.ignorecase`, `core.excludesFile`, `filter.<driver>`.
Neither Dulwich nor the module reads git's user or system attribute files
(`core.attributesFile`, `$XDG_CONFIG_HOME/git/attributes`, the system attributes): under `host`,
a path those files would convert can differ from git's status. Observed on this host: under Git
Bash's `PATH`, Dulwich locates `C:\Program Files\Git\mingw64\etc\gitconfig` (absent), so `host`
reads no system configuration there, while git reads `C:\Program Files\Git\etc\gitconfig`
(`core.autocrlf=true`); under PowerShell's `PATH` both read the latter.

## Export (decision 0014 section 4)

`export_tree(commit, subtree, destination)` writes the blob bytes of `subtree` (`'.'` for the
whole tree) into `destination`, an existing empty directory, each entry at its
repository-relative path, as an extracted `git archive <commit> -- <subtree>` would place it:
no end-of-line conversion, no attributes (`export-ignore` and `export-subst` included as stored),
no pax header. Regular files are written 0644 and executables 0755 where the OS has modes (not on
Windows); a gitlink is an empty directory; a symbolic link is written as a link (on Windows with
`\` separators, as Windows resolves relative links only through them) when its target stays
inside `destination`.

Refused with `EXPORT_REFUSED`, before anything is written: a destination that is not an empty
directory; a link whose target is absolute, holds `\` or NUL, is not UTF-8, climbs above the
export, or climbs (`..`) out of another link; an entry name that is empty, `.`, `..`, `.git` in
any case, and on Windows names Windows would change or refuse (`git~1`, device names such as
`aux.txt`, a trailing dot or space, `<>:"|?*\`). A write the OS refuses, a link it cannot
create included, is `EXPORT_REFUSED` with the OS's reason; the destination may then hold part of
the export. A missing subtree or tree-ish is `GIT_FAILED`.

## Status

`status` compares, for every path, HEAD's tree against the index (`X`: `A`, `D`, `M`, `T`) and
the index against the work tree (`Y`: `D`, `M`, `T`), with git's clean conversion of the work
tree's bytes (`text`, `eol`, `crlf` and `binary` attributes, `core.autocrlf`, git's binary
detection and its rule of not converting a path whose index blob holds CRLF; `ident`). An
unmerged path is reported by git's two-letter code (`UU`, `AA`, `UD`, ...). Local mechanics:
content is always compared (no stat shortcut, so no racy-git case), renames are not detected
(`--no-renames`), `paths` are literal (`:(literal)`), a submodule is not inspected (an existing
directory for a gitlink is unchanged), and intent-to-add entries are not distinguished.

## Bundles

`write_bundle(refs, destination)` writes a complete bundle (version 2, or 3 with
`object-format=sha256` in a SHA-256 repository) of the full reference names `refs`, with the
references' own values (an annotated tag keeps its tag object; Dulwich's
`create_bundle_from_repo` would record the peeled commit), packs every object they reach with
Dulwich, and never overwrites a file. It returns the parsed header with its recomputed pack
trailer. The verifier of bundles pulled from the guest stays git (decision 0014 section 7).

## The contract suite

```
<tools python> -I -B -m unittest discover -s integrations/repository/tests -v      # task repository:test
```

`<tools python>` is what `python -I -B integrations/paths/tools_install.py --python` prints. Under
an interpreter without Dulwich the suite **fails** with `REPOSITORY_NEEDS_DULWICH` (decision 0014
section 9); it never skips.

- **The corpus** ([`tests/repository_corpus.py`](tests/repository_corpus.py)): the Dulwich
  probe's repositories, built by git with a fixed identity and dates under a root named `a b ü`:
  loose and packed copies, a bare mirror, a linked worktree (relative paths), a separate git
  directory, a SHA-256 repository, a 295-character path, `eol=crlf`, binary, CRLF and executable
  files, `export-ignore`, annotated, lightweight, nested, tree and blob tags, a merge, ambiguous
  abbreviations, symbolic links and a gitlink, unsafe names, a work tree with every kind of
  change, a conflicted merge, and three damaged repositories (an id mismatch, a corrupt zlib
  stream, a corrupt pack). [`tests/fixtures/repository-corpus.tar.gz`](tests/fixtures/) holds
  them byte for byte (git's sample hooks left out) and
  [`tests/fixtures/repository-corpus.json`](tests/fixtures/repository-corpus.json) git's answers
  to every question the suite asks, with the archive's sha256. The suite extracts the archive
  once per process into a temporary directory.
- **Recorded half** ([`tests/test_repository_access.py`](tests/test_repository_access.py), no
  git): every answer equals the recorded one; every gap form is refused with an access spy
  recording nothing; damaged objects are `GIT_FAILED` naming the object; exports equal the
  recorded blob digests; the policies; bundles; and no process is launched (process creation
  patched to fail).
- **Git-oracle half** ([`tests/test_repository_oracle.py`](tests/test_repository_oracle.py)):
  where git is on `PATH`, git is asked again over the same corpus (the `repository` policy's
  environment: no system, global or XDG configuration or attributes, no optional index writes);
  the module must give git's answer, and git's answer must still be the recorded one. Bundles the
  module writes pass `git bundle verify`. Where git is absent the module skips with the reason
  `git is not on PATH: the git-oracle comparison needs it (the recorded half still runs)`.

Every git launch of the suite is the test fixtures' (the recorder and the oracle). Re-record the
corpus (needs git; rewrites both fixture files) when the corpus or git's answers must change,
and review the JSON diff:

```
python -I -B integrations/repository/tests/repository_corpus.py --record
```

The archive is not byte-reproducible (git's index records the build's file times); the
expectations are.

## Not verified

- Platforms other than Windows 11 with Git for Windows 2.52: Linux (F-10.5) and macOS; POSIX
  modes in exports and `core.fileMode` in status; symbolic links on a filesystem without them
  (the refusal is tested by a stand-in).
- Reftable repositories, replace references, split or sparse indexes, submodule status,
  intent-to-add entries, `working-tree-encoding`, filter drivers (refused), and `status` under
  `host` with user or system attribute files.
