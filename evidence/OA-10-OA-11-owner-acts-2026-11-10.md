# Owner acts OA-10 and OA-11, performed 2026-11-10

Both acts were performed by the Overseer under the Owner's decisions of 2026-11-10 (verbatim in
[`bootstrap-log.md`](bootstrap-log.md), Decisions). Each was performed once and exactly as prepared.
Paths under the managed data root are written `<managed root>`.

## OA-10: the F-06.3 real-store cross-read (one run)

**Authorization (Owner, 2026-11-10):** "Authorize exactly one execution of the prepared F-06.3 Windows
Credential Manager cross-process test. Use the described random, synthetic credential only. Verify
cross-process retrieval, deletion and absence. Do not enumerate or modify any other credential. Record the
outcome and cleanup evidence. If the operation differs from the prepared plan, stop."

**Pre-check.** `integrations/credentials/tests/test_crossread.py` and `crossread_support.py` were unchanged
since `437a578` (the F-06.3 commit; `git log` on both files). The Overseer re-read both before the run: one
entry named `AIEH test cross-read ` plus 32 random hex digits, the user `aieh-test-cross-read`, a random
value that protects nothing; absent-check, write, a separate process reads it back by name and prints the
user and the value's fingerprint only, delete, a separate process checks absence, the test checks absence;
cleanup deletes the entry if it is still present; the child refuses any name without the throwaway prefix;
no `CredEnumerate`; an I7 no-exposure scan of every child output follows. The operation matched the plan.

**Run** (one, at `867381b`, 2026-11-10 15:30:51Z to 15:30:52Z):

```
AIEH_CREDENTIALS_REAL_STORE=1 <tools python> -I -B -m unittest discover -s integrations/credentials/tests -p test_crossread.py -v
test_a_separate_process_reads_the_entry_by_its_name_then_finds_it_gone (TestCrossReadKeyringFile) ... ok
test_the_child_refuses_a_name_that_is_not_a_throwaway_one (TestCrossReadKeyringFile) ... ok
test_credential_manager_cross_read_with_one_throwaway_entry (TestCrossReadRealStore) ... ok
Ran 3 tests in 0.749s
OK
```

**Outcome:** PASS. The real-store test's assertions are the evidence of each step: the fresh name was absent
before the write; the separate process read `{"present": true, "user": "aieh-test-cross-read",
"fingerprint": <the value's fingerprint>}`; the delete returned true; a second separate process read
`{"present": false}`; the test's own read returned nothing; the I7 scan of both child outputs was clean.
The two file-keyring tests ran beside it as the module's default mode and touch no host store.

**Cleanup evidence:** the entry's absence was asserted from a separate process and from the test process
after the delete. The random name is never printed, so no independent absence check by name is possible
without listing the store, which the authorization excludes; none was made. No other entry was read,
written, deleted or enumerated.

## OA-11: the stray integration store (verify, then remove)

**Authorization (Owner, 2026-11-10):** "Authorize removal of the exact stray integration.sqlite file and its
associated SQLite sidecars only after the specified read-only verification establishes that the database
contains only the five synthetic receipts. If anything unexpected is present, leave it unchanged. Delete the
integration directory only if empty. Record the result."

**Existence, by exact path** (no listing): `<managed root>\persistent\state\integration\integration.sqlite`
present, 131,072 bytes; `-wal`, `-shm` and `-journal` absent.

**Read-only verification** (SQLite URI `mode=ro&immutable=1`, so nothing was created beside the file;
sha256 of the file `4fcc5516d72acbd642879f9ca41043dee04f8d6c590608b3cd8118fa34536737`):

- `attempt`: 5 rows, all written by one run within 50 ms at 2026-11-10T08:01:14Z, every intent
  `aieh-credential-act/1` with `provider` `MemoryProvider` (the test fake) and entry `AIEH Gitea bot
  builder`: four `confirmed` (one `rotate`, three `retire`) and one `failed` (`retire`,
  `REVOCATION_FAILED`). This is finding 1 of [the F-06.3 evidence](F-06.3-credential-provider.md) exactly.
- `attempt_event`: 15 rows, three per attempt (reserved, dispatched, terminal), actors `gitea_roles rotate`
  and `gitea_roles retire`.
- The schema's own reference rows only: `attempt_stage` 2, `attempt_state` 5, `attempt_transition` 7,
  `reconciliation_status` 3, `schema_migration` 3 (migrations 0001 to 0003 applied at 08:01:14Z).
- Empty: `attempt_identity`, `proj_cursor`, `restore_epoch`, `restore_epoch_closure`.

Nothing unexpected was present: no other receipt, no real provider, no token (fingerprints of the fake's
tokens only).

**Removal:** the file's sha256 was re-checked equal to the verified value and the sidecars re-checked
absent, then the file was removed; the `integration` directory was then removed with a plain directory
removal, which succeeds only on an empty directory (so its contents were never listed). Both are gone.

**Effect on F-07.2:** its copy of the integration store into `<state>/integration/` no longer meets an
existing store.
