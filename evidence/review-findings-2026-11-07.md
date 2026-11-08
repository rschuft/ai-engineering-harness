# Review findings of 2026-11-07: dispositions and fixes

- **Date:** 2026-11-08.
- **Source:** three findings of an independent read-only review, evaluated at the Owner's
  direction ("the smallest coherent changes, no broad refactor, isolated unit tests with mocks
  rather than live services"). The Overseer verified the findings against the code and gave the
  dispositions; the Builder re-read the code at the base commit before changing it.
- **Base commit:** `b0f7ca9`. Line numbers below are at that commit.
- **Commit:** the commit that adds this record also holds the fixes of findings 2 and 3, their
  tests, `integrations/gitea/README.md` and the paragraph of finding 1 in
  `integrations/store/README.md`. The `AGENTS.md` test-list correction is a separate commit.
- **Not claimed:**
  - No live Gitea, credential provider, network or managed root was used. Every test runs on
    fakes (`FakeAccounts`, `MemoryProvider`) in throwaway directories under the default TEMP;
    TEMP, HOME, USERPROFILE, APPDATA and LOCALAPPDATA were not redirected by the Builder.
  - `finalize-credentials` and `verify` were not rerun against the live instance. Whether the
    live checkout or managed root holds a file or directory the scans cannot read is not
    established here.
  - Execution-level non-overlap (finding 1) is not implemented; it is documented and carried as
    an acceptance requirement.

## Finding 1: `confirmed` is not execution completion (a responsibility gap, intentional)

**Disposition:** confirmed as a gap in responsibility, not a store defect. Schema unchanged.

**Evidence at `b0f7ca9`:**

- `integrations/store/README.md:279`: `confirmed` is entered "on an observed successful create"
  and permits "the next ordinal on the triple (rework, a fresh review) if policy calls for one".
- `integrations/store/README.md:234-242` (claim rule) and
  `integrations/store/migrations/0003_typed_attempt_identity.sql:128` (the partial unique index
  `WHERE live = 1`) and `:146` (the admission trigger): the store holds at most one live
  reservation per (`work_id`, `design_revision`, `stage`); a confirmed attempt is not live.
- So nothing prevents reserving ordinal N+1 while ordinal N's conversation is still executing.
  Under the Overseer's E-01.1.1 ruling (the blueprint's rework loop and "Prevent concurrent
  claims"), that is the intended scope of the store: the dispatcher and coordinator that must
  enforce execution-level non-overlap are not built yet (E-01.3 onward, E-04.2.x).

**Change:** one paragraph in `integrations/store/README.md`'s lifecycle contract: `confirmed`
is not execution completion; the store's claim rule covers reservation and creation only; the
coordinator must not reserve the next ordinal of a triple while the earlier attempt's
conversation is still executing, as the Agent Server reports it; that rule is required, with
acceptance tests, at E-01.5 and E-04.2.x. No code, schema or migration change. The Overseer
carries the acceptance requirement on E-01.5 and E-04.2.1/E-04.2.2 in the bootstrap log.

## Finding 2: the token-revocation postcondition was reported, not enforced

**Disposition:** confirmed; fixed.

**Evidence at `b0f7ca9`:**

- `integrations/gitea/gitea_host.py:1124-1126`: after the deletions, `revoke_all_tokens()`
  lists again and returns `remaining`, either the names still listed or the string
  `'HTTP <status>'`. Nothing required it to be empty.
- `:1144` (the "already final" path) and `:1165` (the change path): `finalize_account()` stored
  the result in its report and never checked it. A token that survived revocation (a 204 that
  did not delete, a token minted meanwhile) or an unverifiable listing still finished with
  exit 0.

**Fix** (`revoke_all_tokens()`, so both paths are covered):

- the listing after the deletions not 200 with a JSON list raises `TOKEN_REVOCATION_UNVERIFIED`
  (exit 1). A distinct code, not `TOKEN_LIST_FAILED`: that one is raised by the first listing,
  before anything was deleted; this one says deletions may have happened and the postcondition
  is unknown, which is a different operator situation;
- any token still listed raises `TOKENS_REMAIN` (exit 1), naming the token names and the names
  deleted with 204, never a value or a fragment of one. A deletion that answered 204 but whose
  token is still listed is caught by this check;
- on success `remaining` is always `[]`;
- rerun semantics unchanged and now stated in `finalize_account()`'s docstring: a raise after the
  password change and before the temporary entry is deleted leaves both entries and the final
  password set in Gitea; a rerun finds the final entry, sees the change already applied, revokes
  again and completes.

**Tests** (`integrations/gitea/tests/test_gitea_host.py`; `RevocationFake` extends the existing
`FakeAccounts` with a delete that answers 204 without deleting and an overridable listing after
the deletions):

| Test | What it shows | On the base code |
|---|---|---|
| `TestRevokeAllTokens.test_an_empty_listing_after_revocation_passes` | happy path, `remaining == []` | passes (regression guard) |
| `TestRevokeAllTokens.test_a_remaining_token_raises_with_its_name_only` | a token minted during revocation: `TOKENS_REMAIN`, name only, no password | fails |
| `TestRevokeAllTokens.test_a_204_delete_whose_token_is_still_listed_raises` | 204 but still listed: `TOKENS_REMAIN` | fails |
| `TestRevokeAllTokens.test_an_unverifiable_listing_after_revocation_raises` | 500, 401, a JSON object, non-JSON: `TOKEN_REVOCATION_UNVERIFIED` | fails (4 subtests) |
| `TestRevokeAllTokens.test_the_first_listing_failing_is_still_token_list_failed` | the first listing keeps `TOKEN_LIST_FAILED`, nothing deleted | passes (regression guard) |
| `TestFinalizeCredentials.test_a_token_still_listed_after_a_204_delete_fails_the_change_path_and_a_rerun_resumes` | change path raises, no report; both entries kept, Gitea holds the final password; the rerun resumes ("already applied") and deletes the temporary entry | fails |
| `TestFinalizeCredentials.test_an_unverifiable_listing_fails_the_change_path_and_a_rerun_resumes` | the same for `TOKEN_REVOCATION_UNVERIFIED` (non-200 and non-list) | fails (2 subtests) |
| `TestFinalizeCredentials.test_the_already_final_path_also_fails_closed` | the "already final" path raises both codes, then completes when clean | fails |

## Finding 3: unreadable files and directories were skipped silently

**Disposition:** confirmed; fixed. The unreadable-directory case of the managed-root scan was
exposed by the same review and is the same class; fixed in the same way.

**Evidence at `b0f7ca9`:**

- `integrations/gitea/gitea_host.py:993-996`: `files_containing()` did `except OSError: continue`.
  So `finalize_credentials()`'s `found_in_checkout` (`:1200`) could be empty with incomplete
  coverage and finalization succeeded (`:1205`), and `verify()`'s `no_gitea_secret_in_checkout`
  (`:1267`) could pass.
- `:958`: `contains_secret()` (the managed-root scan) called `os.walk(root)` with no `onerror`,
  so a directory it could not list was skipped silently. Its unreadable non-empty files were
  already counted (`:972-978`), as a password hit.

**Fix:**

- `files_containing()` returns `{'found', 'unreadable', 'absent'}`: any `OSError` but
  `FileNotFoundError` is `unreadable`; a listed path absent from the working tree (a tracked file
  deleted from it, `FileNotFoundError`) holds no content and is reported as `absent`, not as a
  failure (stated in the docstring).
- `contains_secret()` returns `{'found', 'unreadable'}`: `os.walk(..., onerror=...)` records every
  directory it cannot list (the root included); an unreadable non-empty file is `unreadable`
  rather than a `found` hit; the existing rule that an unreadable **empty** file (a held LevelDB
  `LOCK`) is not reported is kept.
- `finalize_credentials()`: a hit still refuses with `PASSWORD_FOUND` (its detail now also carries
  `scan_incomplete`); with no hit but anything unreadable it refuses with the new
  `SECRET_SCAN_INCOMPLETE` (exit 1), listing the paths, not `PASSWORD_FOUND`, which would misstate
  what happened. The report carries `scan_incomplete` and `absent_from_checkout`.
- `verify()`: `no_gitea_secret_in_checkout` is false when the checkout scan found a secret **or**
  could not read a file; the new `checkout_scan` output names the unreadable and absent paths.
- Names and the exception class only in every message, never content.

The classification change of an unreadable non-empty managed-root file, from a `PASSWORD_FOUND`
hit to `SECRET_SCAN_INCOMPLETE`, still fails closed; it follows the dispatch's rule that an
incomplete scan must not be reported as a found password.

**Tests** (unreadability is simulated, never with Windows ACLs: a fake path whose `read_bytes`
raises `PermissionError`, a patched `Path.read_bytes`, a patched `os.scandir` that the real
`os.walk` reaches, a patched `open`):

| Test | What it shows | On the base code |
|---|---|---|
| `TestSecretScans.test_files_containing_reports_an_unreadable_file` | an unreadable checkout file is `unreadable` | fails |
| `TestSecretScans.test_files_containing_through_a_patched_read` | the same through `Path.read_bytes` | errors (old result is a list) |
| `TestSecretScans.test_files_containing_reports_a_missing_tracked_file_as_absent` | a missing tracked file is `absent`, not a failure | fails |
| `TestSecretScans.test_contains_secret_reports_an_unlisted_directory` | an unlistable directory under the root is `unreadable`; its file is not reported as found | fails (old: silently `[]`) |
| `TestSecretScans.test_contains_secret_reports_an_unreadable_file_but_not_an_unreadable_empty_one` | a held empty `LOCK` is not reported; a held non-empty file is `unreadable`; a UTF-16 leak is `found` | fails (old result is a list) |
| `TestFinalizeCredentials.test_an_unreadable_checkout_file_refuses_as_an_incomplete_scan` | `SECRET_SCAN_INCOMPLETE` with the path; the absent file is not a failure | fails (old: no refusal) |
| `TestFinalizeCredentials.test_an_unlisted_managed_root_directory_refuses_as_an_incomplete_scan` | `SECRET_SCAN_INCOMPLETE` naming the unlistable directory | fails (old: no refusal) |
| `TestFinalizeCredentials.test_a_missing_tracked_file_is_reported_as_absent_not_as_a_failure` | finalization completes; `absent_from_checkout` names it | errors (old report has no such key) |
| `TestVerifyCheckoutScan.test_an_unreadable_checkout_file_fails_the_check_with_its_path` | only `no_gitea_secret_in_checkout` fails, `passed` is false, `checkout_scan` names the path, no secret in the output | fails |
| `TestVerifyCheckoutScan.test_a_complete_clean_scan_passes` | control: with every other `verify` collaborator faked, a complete clean scan passes | errors (old output has no `checkout_scan`) |
| `TestFinalizeCredentials.test_checkout_search` (updated) | the new result shape | fails (old result is a list) |

"On the base code" was observed by running the new test module against the `b0f7ca9` sources
(a `git archive` copy in a scratch directory): 18 failures and 4 errors, all in the tests named
above as failing or erroring, plus `TestCheckoutFiles` erroring only because the copy is not a
git repository.

## Validation

On the working tree committed with this record, on Windows 11, CPython 3.12, default TEMP:

- `python -I tools/verify_seed.py`: PASS (156 executable Small tasks; 166 seeded files: 161 contract intact, 2 authority intact, 3 ordinary, 3 changed since seed; graph acyclic), exit 0
- `python -I tools/verify_seed.py --baseline seed`: PASS (baseline `13197ddf`; 146 intact seeded files, all strict), exit 0
- `python -I -B -m unittest discover -s integrations/gitea/tests -v`: 90 tests, OK (6 skipped: the opt-in live lifecycle and authorization tests, and the not-applicable executor test)
- `python -I -B -m unittest discover -s integrations/store/tests -v`: 84 tests, OK
- `python -I -B -m unittest discover -s tools/tests -v`: 926 tests, OK
- `python -I -B -m unittest discover -s integrations/dispatch/tests`: 47 tests, OK (named in the corrected `AGENTS.md` list)
