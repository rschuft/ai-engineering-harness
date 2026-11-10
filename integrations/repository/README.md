# Repository access

The shared repository-access module for AI Engineering's own Python components (plan leaf F-10.2,
[decision 0014](../../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md),
Accepted): read-only access to git repositories over
[Dulwich](https://www.dulwich.io/) 1.2.21, pinned in the Python tools set
([`composition/lock/python/tools-requirements.txt`](../../composition/lock/python/tools-requirements.txt)),
and the differential contract suite that holds it to git's answers.

- [`repository_access.py`](repository_access.py): the module. It launches **no process**; every
  answer comes from the repository's own files, in the calling process.
- [`tests/`](tests/): the contract suite. The recorded half runs without git; the git-oracle half
  asks git again where git is on `PATH`.

**Callers.** Since F-10.3 the planning adapter's `Git`
([`integrations/planning/`](../planning/README.md)) is a facade over it, under the `repository`
policy, for the planning, lineage and dispatch components. Since F-10.4 (decision 0014 section 1):
`tools/guest.py`'s exchange push (R5: `full_name`, the `^<n>` parents for the commit count and
`write_bundle`, under `repository`; the header, bounds and pack trailer checked by the caller, the
verifier R6 keeping git), its profile revision and inventory snapshots (R7, R8: `head`, `status`,
`index_entries`, under `host`), `integrations/gitea/gitea_host.py`'s checkout listing (R9:
`listing(cached, others, exclude_standard)`, under `host`) and `tools/test_profile.py`'s revision
stamp (R10, under `host`). Each loads the module by path.

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
| `open_repository(path, *, config, work_tree=True, ceilings=None)` | `git rev-parse --show-toplevel` (acceptance) | The work-tree check: any directory inside a work tree, a linked worktree, a separate git directory's work tree. A bare repository, a `.git` directory or anything inside it, and a non-repository are `CannotRun` `NOT_A_WORK_TREE`. With `work_tree=False` a git directory is accepted (`NOT_A_REPOSITORY` otherwise). `config` is required. `ceilings`: git's ceiling directories (F-10.4); see [Discovery](#discovery). |
| `commit(revision)` | `git rev-parse --verify <revision>^{commit}` | Full id or `None`. |
| `object_id(name)`, `object_kind(name)`, `read(name)` | `git cat-file -t` / `cat-file --batch` | `None` when the repository has no such object, or an abbreviation is ambiguous. |
| `blob(commit, path)` | `git cat-file blob <commit>:<path>` | The bytes; `GIT_FAILED` when there is no such blob (as the planning adapter today). |
| `files(commit, directory)` | `git ls-tree -r -z --name-only <commit> -- <directory>/` | Paths in git's order; `[]` when the directory is absent or not a directory. `directory` is a literal repository-relative path. |
| `export_tree(commit, subtree, destination)` | blob bytes (section 4) | See [Export](#export). Returns `{'files', 'links', 'directories', 'bytes'}`. |
| `head()` | `git rev-parse --verify HEAD`, `git symbolic-ref HEAD` | `Head(commit, ref)`: `commit` is `None` on an unborn branch, `ref` `None` when detached. |
| `full_name(name)` | `git rev-parse --verify --quiet --symbolic-full-name <name>` | F-10.4. The reference NAME resolves to, in git's order (`<name>`, `refs/<name>`, `refs/tags/<name>`, `refs/heads/<name>`, `refs/remotes/<name>`, `refs/remotes/<name>/HEAD`; `@` is HEAD), symbolic references followed to their end (`HEAD` gives `refs/heads/main`). `None` when NAME names no object, is no reference (an id, a navigation, a reflog entry, a path), or is ambiguous (more than one rule resolves, such as a tag shadowing a branch: git prints nothing), unless `core.warnAmbiguousRefs` is false, when the first rule wins. |
| `status(paths=None, untracked='no')` | `git status --porcelain=v1 -z --no-renames --untracked-files=<untracked> -- :(literal)<paths>` | `StatusEntry(xy, path)`: tracked changes, then untracked entries (`??`, a collapsed directory ends with `/`), each sorted. |
| `index_entries()` | `git ls-files -s -z` | `IndexEntry(mode, oid, stage, path)`, one per stage, in index order. |
| `listing(cached=True, others=False, exclude_standard=False)` | `git ls-files -z [--cached] [--others] [--exclude-standard]` | Untracked paths first (sorted; a nested repository as `dir/`), then the index entries. See [Ignore rules](#ignore-rules). |
| `write_bundle(refs, destination)` | `git bundle create` | A complete bundle (no prerequisites) of full reference names; see [Bundles](#bundles). |
| `parse_bundle_header(path)`, `pack_trailer(path, header)` | the bundle format | Module functions: the checks `tools/guest.py` makes today, here for F-10.4 to switch it over (`BUNDLE_INVALID` where it raises `Refused`). |
| `config_sources` | | The configuration files read, in reading order. |

Paths and names are `str`; the repository's bytes are decoded as UTF-8 (undecodable bytes with
`surrogateescape`).

## Discovery

`open_repository` finds the repository as git does, from `path` upwards. **Ceilings** (F-10.4)
have git's `GIT_CEILING_DIRECTORIES` semantics: the search never moves up into a ceiling or above
it, so nothing there is examined (`path` itself always is, even when it is a ceiling); the
longest ceiling that is a proper ancestor of `path` applies. `ceilings=None` (the default, every
product call site) reads them from `GIT_CEILING_DIRECTORIES` (`os.pathsep`-separated; empty and
relative entries skipped), as git does, so that without it the search goes up to the file
system's root. Ceilings are compared as real paths: git's rule that entries after an empty one
are not resolved is not implemented. Every test that opens a corpus repository or a
non-repository passes its temporary root as a ceiling, and the git oracle sets
`GIT_CEILING_DIRECTORIES` likewise, so no test examines its temporary root's parent, the home
directory or the drive root (`Ceilings`, `OracleAgreement.test_ceilings_are_gits`).

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
- **One read per object** (F-10.3 repair): an opened repository keeps the objects it has
  verified in a cache keyed by object id (ids are immutable, so an entry never goes stale), at
  most `OBJECT_CACHE_BYTES` (32 MiB) of content, least recently used out first, an object
  larger than an eighth of that not kept, missing objects never remembered; it is emptied by
  `close()`. A parsed object is parsed from those verified bytes (Dulwich's `from_raw_string`
  with the checked id), not read again, and a commit's parents are taken from it. One
  traversal of the lineage example reads 17 objects through Dulwich, against 180 before. Each
  object Dulwich does not find in a pack still makes it list `objects/pack` once (its
  `get_raw` looks in the packs first and rescans their directory on a miss); no supported
  Dulwich call avoids that, and it costs about 0.5 ms of the example's 3.7 ms.
- **Replace references fail closed.** git applies `refs/replace/` to every object read unless
  `core.useReplaceRefs` is false; the module does not replace objects. In a repository holding
  any replace reference (loose or packed) every object read is refused with
  `REPLACE_REFS_UNSUPPORTED` (at the first read, not at open: HEAD, references, the index and
  the listing are not replaced and answer as git); with `core.useReplaceRefs=false` in the
  applied configuration it reads as git does. `GIT_NO_REPLACE_OBJECTS` is not read (the module
  takes configuration from its policy, not git's environment). Grafts and shallow boundaries
  are applied (Dulwich's `get_parents`).

## Errors (decision 0014 section 3)

| Code | Raised as | Meaning |
|---|---|---|
| `REVISION_INVALID` | `RepositoryError` | Not a usable revision, or a gap form; before any access (the date fallback excepted, above). |
| `OBJECT_NAME_INVALID` | `RepositoryError` | Not an object name, or a path argument outside the repository-relative grammar (`files`, `export_tree`, `status`); before any access. |
| `GIT_FAILED` | `RepositoryError` | The repository could not be read: a damaged object (content not hashing to its id, a corrupt zlib stream, a corrupt pack: `details['object']` names it), any Dulwich or OS error at the module boundary, a tree-ish that does not exist (`files`, `export_tree`), a missing blob (`blob`), an unreadable reference or reflog. |
| `EXPORT_REFUSED` | `RepositoryError` | Local: the export cannot be written safely (below). |
| `BUNDLE_INVALID` | `RepositoryError` | Local: an unparsable bundle header, or refused `write_bundle` input (not a full reference name, no such reference, an existing destination). |
| `FILTER_UNSUPPORTED` | `RepositoryError` | Local: `status` meets a path git would pass through a configured filter driver (a process, such as Git LFS) or a `working-tree-encoding`. |
| `ATTRIBUTES_UNSUPPORTED` | `RepositoryError` | Local: `status` under a policy whose attribute file outside the repository (below) sets an attribute status consults or defines a macro (`details`: `path`, `line`, `attribute`), or cannot be read. |
| `REPLACE_REFS_UNSUPPORTED` | `RepositoryError` | Local: an object read in a repository whose replace references git would apply. |
| `NOT_A_WORK_TREE`, `NOT_A_REPOSITORY` | `CannotRun` | The work-tree check. |
| `REPOSITORY_NEEDS_DULWICH` | `CannotRun` | Dulwich is not importable by the running interpreter; the message names `task tools:install` and the interpreter `tools_install.py --python` prints. |

"No such object" and an ambiguous abbreviation answer `None`. No call raises
`subprocess.TimeoutExpired`: there is no process. `close()` never raises (a pack whose read failed
may hold a buffer Dulwich cannot release at once).

## Configuration policy (decision 0014 section 5)

Every `open_repository` names its policy; `config_sources` lists every configuration file read.

| Policy | Applies | Reads |
|---|---|---|
| `host` | The repository's own configuration, then the user and system files git reads, located **without `PATH`** (`host_config_paths`): `GIT_CONFIG_GLOBAL`, else `~/.gitconfig` and `$XDG_CONFIG_HOME/git/config`; then `GIT_CONFIG_SYSTEM`, else, unless `GIT_CONFIG_NOSYSTEM` is true, the system file (`system_file`): on Windows `<InstallPath>\etc\gitconfig` from Git for Windows' registry entry (`SOFTWARE\GitForWindows`, value `InstallPath`, read only), on POSIX `/etc/gitconfig`, otherwise none. `core.excludesFile` or `$XDG_CONFIG_HOME/git/ignore`. The attribute files: the system one (`<InstallPath>\etc\gitattributes`, `/etc/gitattributes`) unless `GIT_ATTR_NOSYSTEM`, and `core.attributesFile` or `$XDG_CONFIG_HOME/git/attributes`. | All of these that exist. |
| `repository` | The repository's own `config` (and `config.worktree` when `extensions.worktreeConfig` is set), `core.excludesFile` and `core.attributesFile` only if that configuration sets them. | Those files. |
| `none` | Nothing: git's defaults. | The repository's own `config`, read for its format only (`core.repositoryformatversion`, `extensions.*`, `core.bare`, `core.worktree`), as every git must to open a repository; it is listed. |

The configuration a call applies: `core.autocrlf`, `core.symlinks`, `core.fileMode` (POSIX only;
Windows has no executable bit), `core.ignorecase`, `core.excludesFile`, `filter.<driver>`.
No policy's answer depends on `PATH`. Dulwich's own location of the system file does: it
derives Git for Windows' directory from the first `git` on `PATH`, so under Git Bash's `PATH` it
picks `…\mingw64\etc\gitconfig` (absent) where git reads `…\etc\gitconfig`; the module does
not use it. On this host `host` reads exactly the files `git var GIT_CONFIG_SYSTEM`,
`GIT_CONFIG_GLOBAL`, `GIT_ATTR_SYSTEM` and `GIT_ATTR_GLOBAL` name (the oracle checks it).

**Attribute files outside the repository.** Dulwich applies the repository's own
`.gitattributes` files and `info/attributes`, not the user and system ones. `status` reads
those the policy names (`attribute_files`; each read is listed in `config_sources`) and refuses
with `ATTRIBUTES_UNSUPPORTED` when one sets an attribute status consults, a macro included;
attributes status never consults (`diff`, `merge`, `whitespace`, `export-ignore`,
`export-subst`, `delta`, `encoding`, `conflict-marker-size`) cannot change its answer and are
ignored. Git for Windows' own system attributes set only `diff=astextplain`, so `host` status
works on a default installation. No other operation consults attributes: reads, file lists,
exports (blob bytes), the index and listings do not.

## Ignore rules

`listing(..., exclude_standard=True)` and the untracked part of `status` decide which untracked
entries git excludes with the module's own reading of git's rules (`dir.c`), not with Dulwich's
`IgnoreFilterManager`. Dulwich 1.2.21 reports a directory ignored when a pattern only reaches
inside it (`logs/*`), so a directory re-included below it (`!logs/keep/`, gitignore(5)'s
`/*`, `!/foo`, `/foo/*`, `!/foo/bar`) was never entered and its files were missing from the
listing the secret-leak scan reads (F-10.4; introduced at F-10.2). Now:

- an entry is decided by the last pattern that matches the entry itself, level by level from
  the highest precedence: the `.gitignore` of its own directory, then of each directory above
  it, then `info/exclude`, then `core.excludesFile` (a relative path is read from the top of
  the work tree, as git reads it; else, under `host`, `$XDG_CONFIG_HOME/git/ignore`);
- a negated pattern re-includes; a directory is pruned only when the directory itself is
  excluded, and a directory's `.gitignore` is read only when the walk reaches it (an in-tree
  `.gitignore` that is a symbolic link is not followed, as git does not);
- each pattern is matched by Dulwich's `Pattern.matches` (git's wildmatch rules for the path
  relative to the file's directory, and whether it is a directory); a UTF-8 byte-order mark is
  skipped.

The contract suite holds the listing equal to git's and checks the invariant the scan needs:
a listing is never a strict subset of git's.

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
unmerged path is reported by git's two-letter code (`UU`, `AA`, `UD`, ...).

**git's size rule** (F-10.4): a regular file whose index entry records a non-zero size (git
records zero for a size not yet known, or for an entry it smudged as racily clean) that differs
from the file's size is modified, without a content comparison, as git's `ie_match_stat` decides
it. `git status` therefore reports a file whose line endings were swapped as modified even where
the cleaned content is equal (`git diff` then shows nothing); the module answers the same, which
also errs towards dirty. Every other entry's content is compared after the clean conversion (the
module keeps no other stat data, so where git's stat data matches and it compares nothing, the
module compares the content and finds it equal; a file changed without changing its size or any
stat data git records, git's racy case, the module reports modified). Symbolic links are
compared by their target.

**Attributes** (F-10.4): status evaluates the attributes itself, as git's `attr.c` does in the
check-in direction, not with Dulwich's `GitAttributes`, which expands no macro, so that an earlier
`text` won over a later `binary` (the shape of `composition/.gitattributes`, `* text eol=lf`
then `*.gz binary`, which made seven files of this checkout modified; introduced at F-10.2):

- the stack, lowest precedence first: the built-in `binary` macro (`-diff -merge -text`), the
  root `.gitattributes`, each deeper directory's `.gitattributes` down to the path's own, then
  `info/attributes`; an in-tree `.gitattributes` is read from the work tree (a regular file,
  not a symbolic link), else from the index;
- from the highest line down, each matching line determines the attributes not yet determined,
  the last on the line first, and a macro set to true then determines its own attributes the
  same way (`!name` determines a name as unspecified);
- **`[attr]` macros are implemented as git implements them** where git allows them, in the root
  `.gitattributes` and `info/attributes` (the definition of highest precedence wins, and a
  macro may name a macro); a definition in a deeper `.gitattributes` is ignored, as git ignores
  it; an `[attr]` line is never a glob pattern; a macro defined in a user or system attribute
  file is refused with `ATTRIBUTES_UNSUPPORTED` naming the file and the line, like any
  status-relevant attribute there;
- as git drops them: a negative pattern, a line with an invalid attribute name, a line of 2048
  bytes or more; a pattern ending in `/` never matches a file; a quoted pattern is unquoted;
  with `core.ignorecase`, patterns match case-insensitively (ASCII).

Local mechanics: renames are not detected (`--no-renames`), `paths` are literal
(`:(literal)`), a submodule is not inspected (an existing directory for a gitlink is unchanged),
and intent-to-add entries are not distinguished.

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
  change, a conflicted merge, three damaged repositories (an id mismatch, a corrupt zlib
  stream, a corrupt pack), and replace references (loose, packed, and disabled by
  `core.useReplaceRefs=false`). F-10.4 added twelve repositories, answered apart (`cases`, so
  that the F-10.2 answers and test ids stay as they were): ten of ignore rules (directories
  re-included by a negation, gitignore(5)'s examples, nested `.gitignore` files, `**`,
  `info/exclude`, a relative `core.excludesFile` and their precedence), `attributes` (git's
  order, the built-in and `[attr]` macros, the `composition/.gitattributes` shape) and
  `line endings` (git's size rule under `core.autocrlf=true`), and git's
  `rev-parse --symbolic-full-name` answers for 72 names (`full_names`): 962 recorded answers
  over 11 repositories before, 1,109 over 23 after. [`tests/fixtures/repository-corpus-tree.json.gz`](tests/fixtures/)
  holds them byte for byte (git's sample hooks left out) as gzipped JSON, every directory and
  file, plain text as text and git's binary files as base64, so that the publication-safety gate
  can inspect all of it (it refuses an archive it cannot read as text), and
  [`tests/fixtures/repository-corpus.json`](tests/fixtures/repository-corpus.json) git's answers
  to every question the suite asks, with the tree's sha256. The suite extracts the tree
  once per process into a temporary directory.
- **Recorded half** ([`tests/test_repository_access.py`](tests/test_repository_access.py), no
  git): every answer equals the recorded one; every gap form is refused with an access spy
  recording nothing; damaged objects are `GIT_FAILED` naming the object; exports equal the
  recorded blob digests; the policies, `host` identical under Git Bash's `PATH` order,
  PowerShell's and an empty `PATH`; the attribute files; replace references refused; bundles;
  the F-10.4 cases (`RecordedCases`, `AttributeLines`), among them that a listing is never a
  strict subset of git's; and no process is launched (process creation patched to fail).
- **Git-oracle half** ([`tests/test_repository_oracle.py`](tests/test_repository_oracle.py)):
  where git is on `PATH`, git is asked again over the same corpus (the `repository` policy's
  environment: no system, global or XDG configuration or attributes, no optional index writes);
  the module must give git's answer, and git's answer must still be the recorded one. `host`
  reads the files `git var` names (`GIT_CONFIG_SYSTEM`, `GIT_CONFIG_GLOBAL`, `GIT_ATTR_SYSTEM`,
  `GIT_ATTR_GLOBAL`) and every file `git config --system --list --show-origin` shows; git
  applies the replace references the module refuses. Bundles the module writes pass
  `git bundle verify`. Where git is absent the module skips with the reason
  `git is not on PATH: the git-oracle comparison needs it (the recorded half still runs)`.
  Recording asks git one question per launch; the oracle asks many per launch where git
  answers them in one (F-10.4): `cat-file --batch-check` for names and commit forms, one
  `rev-parse --revs-only --symbolic-full-name` for every full name of a repository, one
  `ls-files -t --cached --others --exclude-standard` for the cached and excluding listings, one
  `ls-tree` per commit for the file lists, `rev-parse HEAD --symbolic-full-name HEAD` for HEAD,
  and `--untracked-files=no` read from the `all` status; the recorded answers check every
  batched one.

Every git launch of the suite is the test fixtures' (the recorder and the oracle). Re-record the
corpus (needs git; rewrites both fixture files) when the corpus or git's answers must change,
and review the JSON diff:

```
python -I -B integrations/repository/tests/repository_corpus.py --record
```

The tree is not byte-reproducible (git's index records the build's file times); the
expectations are.

## Not verified

- Platforms other than Windows 11 with Git for Windows 2.52: Linux (F-10.5) and macOS; POSIX
  modes in exports and `core.fileMode` in status; symbolic links on a filesystem without them
  (the refusal is tested by a stand-in).
- The system files on macOS installations with another prefix (Homebrew's
  `$(brew --prefix)/etc/gitconfig`, Xcode's git), and Git for Windows installed without its
  registry entry (portable): the module then reads no system file.
- Reftable repositories, replacing objects (refused), split or sparse indexes, submodule status,
  intent-to-add entries, `working-tree-encoding`, filter drivers (refused), and `status` under
  `host` with user or system attribute files.
