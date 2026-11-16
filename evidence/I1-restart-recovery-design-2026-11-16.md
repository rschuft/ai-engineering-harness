# I1 restart-recovery design (E-01.4.2), 2026-11-16

The architect's second I1 consultation (gates A and G), answering the engineering manager's questions after an engineer's restart-matrix probe stopped E-01.4.2: how a restarted dispatcher recovers an interrupted create and turn without a duplicate, and how E-01.4.2's citation clause should read. Read-only; nothing live. The engineering manager's rulings follow the answer. Its numbering continues [the I1 integration design](I1-integration-design-2026-11-16.md): rulings R16 to R22, gates G12 to G16, planning items PB-10 to PB-12, slices 5a to 5c (replacing slice 5).

To the engineering manager. Reading taken: a **consult** that resolves question 1, with the **work design** you asked
for (three bounded slices that replace slice 5 of the I1 design record), a decision draft, and **advice** on question 2
for planning. Advisory throughout: each ruling is a recommendation you accept or not, the decision draft is Proposed,
and question 2 is planning's to decide. Nothing in the repository was edited.

Numbering continues the I1 design record: rulings R16 to R22, STOP gates G12 to G16, planning items PB-10 to PB-12.
Slices 5a, 5b and 5c replace its slice 5.

Contents: 0 basis; 1 question 1, the ruling; 2 work design; 3 decision draft 0027; 4 question 2; 5 planning items;
6 defects named; 7 not verified, and residuals.

## 0. Basis

- **Baseline, observed:** the engineering manager's checkout, branch `main`, HEAD `a34ce77` = `origin/main`; no tracked
  file modified (`git status --untracked-files=no`; untracked files were never listed, so the root `config.yml` was
  neither read nor enumerated).
- **Read in this invocation:**
  - the brief, the I1 design record, the engineer's probe script and the E-01.4.1 verdict entry;
  - `integrations/store`: `integration_store.py` whole, `README.md` whole, migration 0001;
  - `integrations/dispatch`: `reconcile.py` whole; `attempt_end.py` whole; in `dispatch_inputs.py` the ordinal
    resolution, `stored_inputs`, the grant custody, `dispatch`, `end_attempt` and the refusal table; in
    `attempt_run.py` the header, SEED, the turn journal, `run_attempt`, `resume_result` and the result receipts; in
    `result_path.py` `publish_result`; the README's sections on the create, the reconciliation and the attempt run;
    the three fakes and `tests/fixtures/agent-server-1.60.1-exchange.json`;
  - the Owner recorders' `resolve` and `manifest_resolve`; `integrations/ownerhost/service.py` `InstanceLock` and the
    tests that exercise it; `tools/guest.py` `D1_RUN_RULE` and the D1 driver's dispatch and resume branches;
  - decisions 0001, 0004, 0010, 0024 and 0026 whole, 0018 points 1 to 3;
  - evidence: E-01.1.2 whole, E-01.1.1 sections 7 to 9, F-04.2 sections 1, 4 and 10 to 12, the D1 run record
    sections 1 to 6;
  - the plan leaves E-01.4.1, E-01.4.2, E-01.5, E-01.6, E-01.7, E-01.8, U-03.2, U-04.1 and U-06.1;
  - the log entries `commitment-i1-2026-11-16`, `i1-execution-questions-2026-11-16` and
    `i1-blockers-disposed-2026-11-16`, and the Owner's direction of 2026-11-13 on recovery;
  - the blueprint's passages on a lost reply, a process death during dispatch and serialized dispatch, found by
    phrase (`#integration-contracts`, `#dispatch-probe-qualification`, the dispatch contract);
  - the dispatcher-allowed routes of the pinned route allowlist.
- **Pinned upstream, read:** `docker_runtime/routers.py` of `openhands-agent-server` at the lock's commit, the copy
  the first consultation fetched (session scratch). It was not compared byte for byte with the locked wheel. Its five
  handlers stand at exactly the line numbers F-04.2 cites from the wheel (128, 272, 292, 311, 322).
- **Measured in this invocation** (session scratch `i1/arch2-probe/`, the host's CPython 3.12.10, Windows 11; files
  in scratch only): the operating system's file lock, in three respects (R17).
- **The probe was not re-run.** Each of its four "never recovered" findings follows from the code read here (1.1).
- **Not read, by instruction or by boundary:** the root `config.yml`, any credential store, the managed data root, any
  other repository. The Control Plane Knowledge surface was not used: the authorized paths are this repository and
  session scratch.
- **Vocabulary.** "Verified" means read in this invocation at the path named. "Measured" means run here. "Inferred"
  is marked. A defect is `introduced-by`, `exposed-by` or `unrelated-but-detected`.

---

## 1. Question 1: the ruling

### 1.1 What the evidence establishes

**The four findings are structural.** None is a missing transition: every state change the fix needs is already in
`TRANSITIONS`. What is missing is an act.

| Probe case | State left | Why nothing ever moves it (verified at `a34ce77`) |
|---|---|---|
| m2b | attempt `reserved` | `dispatch` resolves the ordinal as the highest claim plus one (`store_next_ordinal`), so a repeat of the same request asks for ordinal 2, which `reserve_attempt` refuses as `LiveClaim`. Only the act that reserved a row ever moves it out of `reserved`. The store's "an identical request returns the existing reservation" (E-01.1.2) is a guarantee a repeated dispatch never reaches. |
| m2c, m3a | attempt `dispatched` | `IntegrationStore.reconcile` moves `dispatched` to `unknown` only while a restore epoch is open, and `create_oracle` is asked only about `unknown` attempts. |
| m4b | turn journal `dispatched` | `run_attempt` refuses an attempt whose turn journal exists, `resume_result` needs it `confirmed`, `reconcile_turn` needs it `unknown`, and only `send_message` itself ever enters `unknown`. |

- **Why the create and the turn, and not the others.** Three other write-ahead receipts of this store already have a
  resume arm, and in each it is a repeat of the same act:
  - the result journal: `publish_result` moves a journal it finds `dispatched` to `unknown`, reason `resumed`, then
    settles by reading Gitea;
  - the end journal: `end_interrupted_attempt` resumes as it began;
  - the Owner recorders: `resolve` and `manifest_resolve` move `reserved` to `failed` (`NOT_SENT`) and `dispatched` to
    `unknown` (`OUTCOME_UNKNOWN`), then settle by a read.

  The create and the turn have none because their act cannot be repeated: a repeated dispatch is a new ordinal, and
  a repeated run is refused.
- **Why the store's sweep cannot simply be widened.** The integration store has several live writers with receipts in
  flight: the credential provider, the inference broker, the three Owner recorders, and from slice 8 the Integration
  process. A sweep of every `dispatched` row is sound inside a restore epoch only because the restore took exclusive
  custody of the file. Outside one it would settle other live processes' receipts.
- **Why no case produced a duplicate, and none can.** A create is sent only by the act whose `reserved` to
  `dispatched` transition of that attempt committed, and a message only by the act whose turn journal's did. Each
  transition is one compare-and-swap in one `BEGIN IMMEDIATE` transaction (E-01.1.2: of competing transitions one
  wins). Nothing sends from `dispatched`, `unknown`, `confirmed` or `failed`. So the no-duplicate property is the
  store's, and it holds whatever recovery does, provided recovery itself sends nothing (R19).
- **Three restart points the probe's matrix does not have.** Each is between the create and the message's receipt:
  - G: SEED has run and no turn journal exists yet (the dispatcher dies during the `before-message` observations);
  - H: the turn journal is `reserved`;
  - I: the turn journal is `dispatched` and the message never reached the server.

  They matter for the proof's reading (R21, PB-11).
- **The design authority already states the rule.** Blueprint `#integration-contracts`, "Failure and recovery at the
  connections", row "Process dies during dispatch":
  - what must happen: "Read the dispatch receipt, query OpenHands, then attach to existing run or report unknown
    state";
  - what must never happen: "Blindly launch a second implementation against the same checkout".

  The same section says "A single-user initial mode may serialize dispatch, but the durable operation key still
  protects crash/restart and webhook replay".

### 1.2 Rulings

**R16. Recovery is an explicit dispatcher act, `recover`, that keeps two questions apart.** Your option (c), with
(a) as its evidence at a narrower scope than a dispatcher instance; (b) is rejected.

- *Is the act that wrote this row still going to record its outcome?* Only a lock answers that (R17).
- *What happened at the Agent Server?* Only the Agent Server answers that: E-01.4.1's lookup for a create, and
  decision 0024 point 6.1's event read for a message.

Recovery never infers the second from the first, and never from the store alone. Decision 0004 point 7 is the reason
for the last clause: after a restore, "the absence of a receipt ... is not evidence that an effect did not happen".

**R17. The dispatcher lock: one OS lock per integration store, held across each write-ahead window.**

1. **What it is.** A file beside the store, `<store file name>.dispatcher.lock`, in the store's own directory and
   custody. It is locked exclusively and without blocking, by the technique `InstanceLock` already uses in
   `integrations/ownerhost/service.py` (accepted at U-01.3). The operating system releases it when the holder's handle
   closes or its process ends. It is never deleted and holds no data.
2. **Who holds it, and for how long.**
   - `dispatch`: from before `reserve_attempt` until the create's outcome transition has committed or the call is
     left by an exception.
   - The attempt run: from before its first call until the message's outcome is recorded. `send_message` takes it
     itself, re-entrantly, because tests call it directly. It is not held while the turn is waited for.
   - `recover`: throughout.
   - Busy is one stable refusal, `DISPATCHER_BUSY`, raised before anything is reserved or sent. The lock is
     re-entrant in the holding thread; a second thread is refused like a second process.
3. **The invariant** (the thing the falsifiers of slice 5a test):
   - **I-1.** A typed attempt or a turn journal is moved into `dispatched` only by a thread that holds the lock, and
     that thread holds it until it has recorded that row's outcome, or its act has ended without one.
   - **I-2.** A typed attempt is reserved, and leaves `reserved`, inside one held region.
4. **What it proves.** A process that holds the lock and finds a typed attempt `reserved` or `dispatched`, or a turn
   journal `dispatched`, has established that the act which wrote that row has ended without recording its outcome.
   That covers a process that died and an act interrupted in a process that lives on. It proves nothing about the
   Agent Server.
5. **Who does not take it.**
   - Must not: `end_attempt`, `end_interrupted_attempt` and the cause commands. `end_attempt` is designed to run
     while a dispatch is in flight (E-05.6: ending an attempt in flight revokes its grant), and the engineering
     manager must be able to stop an attempt whose dispatcher hangs.
   - Do not, in this unit: `publish_result`, `reconcile_creates`, the recorders and the store. They have their own
     resolvers and none of their rows is settled by `recover`. Whether the result journal's own resume arm, which
     makes the same declaration on decision 0024's one-process assumption, should take the lock is left open in
     draft 0027.
6. **Measured on this host** (session scratch `i1/arch2-probe/`):
   - a second handle in the same process is refused while the first holds the lock;
   - after the holder is killed and its exit observed, the first attempt to take the lock succeeds (about 0.1 ms
     later, twice);
   - a child the holder started, still alive after the holder was killed, does not keep the lock, including with the
     handle marked inheritable and `close_fds=False`.

   The first is also asserted by `integrations/ownerhost/tests/test_service.py`. Not measured: Linux and macOS, where
   `flock` belongs to the open file description and a child that inherited the descriptor would keep it.
7. **What it is not.** A coordination control between cooperating dispatcher code, not a security boundary. A process
   of the Owner's account that does not take it is not stopped (decision 0010 point 1). It turns decision 0024's
   residual 5 ("One dispatcher process ... assumed, not enforced across processes") into a mechanism at the two
   write-ahead points and nowhere else; the builder registry and the held role tokens stay as assumed.

Why window scope and not a dispatcher-instance lock: there is no dispatcher process with a lifetime, only library acts
run by a command. The window is exactly what I-1 needs. And a lock held for a whole turn would refuse every other
dispatcher act on the store for up to the turn's ceiling.

**R18. Which states may be settled, how, and on what evidence.** `recover` holds the lock, then:

| Found | The lock establishes | What is read | Then |
|---|---|---|---|
| Typed attempt `reserved` | its dispatch ended before the `dispatched` transition committed, so no continuation will send its create | `GET /api/conversations/{reserved id}`, on the attempt's pinned allowlist | `404`: `reserved` to `failed`, code `NOT_SENT`. `200` with that id: no change, held as `RESERVED_CONVERSATION_FOUND`. Anything else: no change, asked again at the next `recover` |
| Typed attempt `dispatched` | the act that sent, or was about to send, the create will never record its outcome | nothing yet | `dispatched` to `unknown`, code `OUTCOME_UNKNOWN`; then the next row |
| Typed attempt `unknown` | nothing is needed | E-01.4.1's lookup, unchanged (`reconcile_creates`) | `200`: `confirmed`, reattached. `404`: `failed`. Anything else: stays `unknown` |
| Turn journal `dispatched` | the act that sent, or was about to send, the message will never record its outcome | nothing yet | `dispatched` to `unknown`; then the next row |
| Turn journal `unknown`, its attempt `confirmed` with no end record | nothing is needed | the conversation's events (`reconcile_turn`, unchanged) | the message is there: `confirmed`, reason `reconciled-from-events`. Not there, or the conversation cannot be read: stays `unknown`, held |
| Turn journal `reserved` | its message was never sent | nothing | no change; reported as held, not sent (R21) |
| Any other key | nothing | nothing | not read, not asked, not changed |

- A `reserved` attempt is failed only on a `404`, not on the store's word, because of decision 0004 point 7: a restore
  can return a row to `reserved` whose create the lost history sent. The lookup costs nothing in liveness. With no
  reachable Agent Server no dispatch is possible anyway.
- The `200` under a `reserved` row is deliberately a hold and not a reattachment. The row has no `dispatched` detail,
  which is where the token's fingerprint is recorded, so it could not be run, ended or published as a confirmed
  attempt. It can arise only after a restore; no resolver exists and none is designed here.
- A client that cannot be built, or a call the client refuses, is indeterminate: never a settlement. After slice 11
  that includes a transport whose authority is not the attempt's (R8).
- The reasons and detail codes take the recorders' vocabulary (`NOT_SENT`, `OUTCOME_UNKNOWN`). The exact strings are
  the engineer's.
- Inside a restore epoch the store's own sweep still runs, unchanged. `recover` then adds one thing: it reconciles the
  turn journals the sweep made `unknown`, which nothing does today, so an epoch can close.

**R19. What recovery never does.** It sends no create and no message, ends no attempt, reserves nothing, deletes
nothing, and calls no broker. Every call it makes is a `GET`. Its namespace is the typed attempts and the turn
journals; every other key has its own resolver and is byte for byte what it was.

**R20. The store contract does not change.**

- No schema, state, transition pair, trigger, migration or API changes. `IntegrationStore.reconcile` stays as it is,
  and so does `reconcile.py`. `recover` uses `transition(..., expected_from=)` as any caller does.
- What changes is two cells of the lifecycle contract in `integrations/store/README.md`, which the engineer edits in
  slice 5b:
  - `unknown` is already "entered by ... the dispatcher on ... an interrupted create". It gains the evidence: an
    interruption is established under the dispatcher lock.
  - `failed` gains "or a reservation the dispatcher abandoned, when the Agent Server does not know its reserved
    conversation".
  - The `reserved` row's "after a restart, dispatching it again" is a permission no dispatcher code uses. Say what
    the dispatcher does instead.
- **No E-01.1.x guarantee changes.** Concurrent identical requests still resolve to one reserved key. A restart still
  finds the same key, attempt id, conversation id and revision. A crash still leaves a call whole or absent. Races
  still give typed outcomes only. The claim rule is untouched: E-01.1.2's "next ordinal: `LiveClaim`" for a live row
  stays true until that row is settled, which is what the rule says.
- Whether the lifecycle table is a contract between leaves, and so the product manager's, is your judgement as with
  PB-9. My reading: it is inside committed scope, because both additions are causes the table's existing text already
  admits in kind, and no reader of `failed` or `unknown` changes.

**R21. Where the effect cannot be observed or repeated, recovery holds; it does not resume.**

| Point | What recovery finds | Outcome |
|---|---|---|
| G: SEED ran, no turn journal | a `confirmed` attempt; nothing to settle | The next `run_attempt` sends SEED again and stops at `SEED_FAILED`: the pinned script creates the directory and "an existing one fails the command". No message is sent. Held |
| H: turn journal `reserved` | not sent | `run_attempt` refuses with zero calls. Held |
| I: turn journal `dispatched`, message not in the events | `unknown` after `recover` | `TURN_UNRECONCILED`. Held. If the events later hold the message, the next `recover` confirms the turn and the result step resumes on the same conversation |

- This is the blueprint's "attach to existing run or report unknown state", decision 0024 point 6.1 ("The message is
  never sent twice"), and `D1_RUN_RULE`, the rule D1 ran under ("a dispatcher refusal before the message, a lost
  create answer, an undecided inspection or a turn past its ceiling is held for the engineering manager").
- It also keeps to the Owner's direction of 2026-11-13 on recovery: "Do not design or implement a new general-purpose
  resumption framework for D1", and "preserve durable Work and attempt state and permit a new attempt ... with
  appropriate idempotency and reconciliation safeguards".
- The exit from a hold exists and is fenced: `end_interrupted_attempt`, trigger `attempt-stopped`, stops the runtime
  and observes it stopped before any new ordinal is admissible. Which dispatcher record the end carries is yours or
  the driver's, not recovery's. `run-not-started` is the existing kind that fits and classifies as an interruption;
  with no record the end is unclassified and waits for your `record-end-cause`.
- Making G and H continue on the same conversation needs a seed receipt and a turn resume. That is new durable
  semantics under decision 0024 and a step toward what the Owner's direction rules out, so it is its own leaf or a
  deferral, never a clause of E-01.4.2 (PB-11).

**R22. What other leaves inherit.**

1. **E-01.5, the 404 race, now load-bearing.** The restart path reaches `404` to `failed` routinely, and soon after a
   crash.
   - Source-read: the pinned handler creates the provisioning identity, starts the container, forwards the create to
     the inner server, and only then refreshes the outer catalog. F-04.2 observed the create answering in 24.8 s and
     D1 in 10.64 s. Inferred: for about that long a lookup answers `404` for a create that will complete.
   - The worst case is not a second execution. Nothing sends a message to a `failed` attempt (`run_attempt` requires
     `confirmed`), and the next attempt's inspection fails when the server's count is not 1. The worst case is an
     idle conversation, holding the create's secrets, that nobody tracks.
   - It is costly all the same. That failed inspection ends the next attempt with a `containment-stop` record, which
     is non-retryable and refuses every later attempt of the work item (`PRIOR_END_SECURITY_STOP`). So the rule has
     to refuse the next ordinal before it is reserved, not rely on the inspection.
   - So E-01.5's non-overlap rule must ask the Agent Server about every earlier ordinal whose history holds a
     `dispatched` event, whatever its final state. That is the E-01.4.1 verdict's carried note, and it makes the
     README's sentence "An earlier attempt that failed before or at its create created no conversation and needs no
     end" true where it is not today.
   - Two facts for that design, not designed here. At the pinned source the runtime read and the runtime stop answer
     `404` until the conversation's `meta.json` exists, so E-05.8's stop cannot reach a create in flight. And
     `DELETE /api/conversations/{id}` is dispatcher-allowed in the pinned allowlist and, at the source, is keyed on
     the provisioning identity.
   - Its refusal tests should include a conversation that appears after the lookup answered `404`. That behaviour
     of the fake is derived from the pinned handler's order, so it is a test knob there, not a catalog answer.
   - Nothing live runs between E-01.4.2 and E-01.5, so no exposure arises before E-01.5 lands.
2. **E-01.6** observes `recover` and the lock on the live transport, and the user message event (section 4).
3. **Slice 11 (E-01.8).** The fixture's composition root runs `recover` before its first dispatcher act, and stops on
   `DISPATCHER_BUSY` or on a held row of the triple it is about to dispatch. Add one row to its proof: a transport of
   the other authority never settles an attempt.
4. **U-06.1.** Its run rule requires `recover`'s report to be empty before the dispatch. Its item (7) restarts the
   Integration process, not the dispatcher, and needs nothing from this design.
5. **The native driver** (`tools/guest.py` `d1_run`) inherits the lock with no change, because the lock is taken
   inside the acts. It does not call `recover`; that goes to the leaf that next runs it live.

### 1.3 Options ruled out

| Option | Why not |
|---|---|
| (b) A sweep keyed on the process identity recorded at dispatch | It adds a key to every `create-dispatched/v1` detail, so native records stop being byte for byte what they are, against R11 and E-01.8's "suites unchanged". It needs a per-platform liveness probe with its own races. And a recorded process id is knowledge a restore brings back stale. The OS lock gives the same fact atomically with no record change |
| A store-level sweep outside an epoch | Settles other live writers' receipts (1.1) |
| A lease with a timeout or heartbeat | Liveness by a guessed duration: a holder that is slow or suspended is declared dead while it lives |
| A lock for the dispatcher process's whole life | There is no such process; it would refuse other acts for a whole turn |
| The lock only in `recover` and in the composition roots, by convention | Then "the lock is free" proves nothing about `dispatch` and `send_message`: decision 0024's residual 5 again |
| Recovery inside `dispatch` (a `LiveClaim` settled in passing) | Changes `dispatch`'s behaviour and E-01.2.x and E-01.3.x tests, and hides a settlement inside another act. An explicit act returns a report that is evidence |
| Resending the create under the same id after a `404` (decision 0001's retry rule) | Against E-01.4.1's accepted table (`failed` is terminal; the reserved id is never sent again). It would deliver the native token a second time, against E-05.8 and decision 0023. And the pinned server's behaviour for two creates of one id at once is not established. The blueprint's probe re-posts only "after confirming it exists" |
| One lock per attempt | More precise, and the form E-04.2.x would need for parallel creates. Not needed while "a single-user initial mode may serialize dispatch". The invariant does not depend on the granularity |
| The recorders' pattern alone: an operator-run settle per key, no lock | Sound for a one-shot command the Owner runs himself. Here the settle is automatic at every start, so its evidence must be mechanical. It is the fallback if G12 fails |

---

## 2. Work design

Three slices, one per engineer dispatch, in this order. 5a and 5b do not wait for planning. 5c waits for PB-10 and
PB-11. **Send PB-10 and PB-11 to planning now:** E-01.4.2 is on the critical path and E-01.5 cannot start before its
verdict.

**Fresh review recommended for 5a and 5b together.** They change the two write-ahead points of the dispatch path, and
gate G's property rests on them.

### Slice 5a: the dispatcher lock

- **Purpose.** Make "no create and no message is in flight on this store" a fact a process can establish.
- **Governing authority.** R17; draft 0027 points 2 and 3; blueprint `#integration-contracts`.
- **Entry state.** `a34ce77` or later, tree clean.
- **Files.**
  - New: `integrations/dispatch/dispatcher_lock.py` (standard library only); its tests; a worker script for a holder
    in another process, on the pattern of `integrations/store/tests/store_worker.py`.
  - Changed: `integrations/dispatch/dispatch_inputs.py` (the refusal `DISPATCHER_BUSY`; the held region of
    `dispatch`); `integrations/dispatch/attempt_run.py` (the held regions of `run_attempt` and `send_message`);
    `integrations/dispatch/README.md` (a section, the refusal table, and the "One process" paragraph).
  - Records: `decisions/0027-...md`, Proposed, in the slice's records commit.
- **Non-goals.** No lock in any act R17 point 5 names. No change to the store, to `reconcile.py`, to a transition's
  detail or reason on an existing path, or to `integrations/ownerhost`. The lock primitive is written again here
  rather than moved: a move would add a module to the Integration process's supervisor, whose module set
  `integrations/ownerhost/tests/test_structure.py` pins. Two copies of about thirty lines are a recorded residual
  (section 7).
- **Falsifiable completion conditions.**
  1. With the lock held elsewhere, by a second handle and by a real second process:
     - `dispatch` raises `DISPATCHER_BUSY` with nothing reserved, the store's canonical dump unchanged and zero
       transport calls;
     - `run_attempt` raises it before any call;
     - `send_message` raises it with no journal reserved.
  2. A holder process killed after its `dispatched` transition leaves the lock free once its exit is observed. The
     test waits on the process, never on a duration.
  3. A `BaseException` raised in the transport during the create, and during the message, leaves the lock free and
     the row `dispatched`.
  4. I-1 and I-2, as a property of production code. In `integrations/dispatch/*.py` the only call of
     `reserve_attempt`, and the only transitions of a typed attempt or a turn journal into `dispatched`, are inside
     the held regions of `dispatch` and `send_message`. Shown twice: by the call sites, and by a recording wrapper
     around the store under the dispatch suite, in which every such call made by production code finds the lock held
     by the calling thread. At `a34ce77` the sites are one `reserve_attempt` and one transition in `dispatch`, and one
     transition in `send_message` (verified by search).
  5. The lock file is beside the store, never in the checkout, 0 bytes, never deleted. The store's backup and restore
     tests pass with it present.
  6. Fail closed: a lock file that cannot be opened or created is a refusal of its own with a stable code, never a
     pass and never reported as busy.
- **STOP gates.**
  - **G12.** On the test host, by test: a second handle in the same process is refused; a killed holder's lock is
    free once its exit is observed; an orphaned child does not keep it. STOP when any fails: the evidence base is
    gone. Report it; the fallback is the operator-run settle of 1.3's last row.
  - **G13.** The whole test set (`tools/run_tests.py`) passes with no changed assertion and no removed test id. STOP
    when an existing test needs a change, and report which and why.
  - **G14.** STOP when the census of condition 4 finds another site.
- **Compatibility.** No format, schema or record changes. New refusal codes only.
- **Trap.** `integrations/ownerhost/tests/test_structure.py` globs `integrations/*/<name>` for every `.py` name that
  occurs as a string in the Integration process's modules. Do not name a new dispatch module after one of them.

### Slice 5b: `recover`

- **Purpose.** The restart procedure: R18's table, and nothing else.
- **Governing authority.** R16, R18 to R21; draft 0027 points 4 to 7; E-01.4.1's decision table; decision 0024
  point 6.1.
- **Entry state.** Slice 5a accepted.
- **Files.**
  - New: one module in `integrations/dispatch/` holding
    `recover(integration_store, *, transport, actor, read_artifact=...) -> dict`; its tests, on the existing fakes
    unchanged, as slice 3 used them.
  - Changed: `integrations/dispatch/README.md` (a section "Recovering after a dispatcher restart", with the decision
    table and the restart procedure); `integrations/store/README.md` (R20's three cells).
- **Non-goals.** No change to `integration_store.py`, a migration, `reconcile.py`, `dispatch`, `run_attempt`,
  `resume_result`, `attempt_end.py` or `result_path.py`. No command-line command: the composition root calls the
  function (slice 11). No end, no send, no broker call.
- **The report** (returned, in memory, as E-01.4.1's observations are). For each key touched or asked about: its
  class, the state found, the basis, the verdict and the HTTP status of a lookup. A `held` list, each entry with its
  code and the act that resolves it. For an attempt that has a grant journal, that journal's state and `end_attempt`
  as its resolver. The durable trace is the transitions' reasons and details.
- **Falsifiable completion conditions.**
  1. Each row of R18's table, asserting the store's event history (states, reasons, details) and the transport's
     calls.
  2. With the lock held elsewhere: `DISPATCHER_BUSY`, the canonical dump unchanged, zero calls. This is the control
     for "never settles another live process's in-flight attempt".
  3. The namespace. Outside an epoch, with each of these left `reserved`, `dispatched` and `unknown`, their rows and
     events are identical after `recover` and no call is made for them:
     - a P-04.2 receipt and a P-04.3 receipt, built with their own key builders;
     - a credential receipt and a broker journal;
     - the dispatcher's own end, result, grant, revocation, delivery, pull and intake receipts.

     Inside an epoch, state exactly what the store's own sweep did and that `recover` added only the turn arm.
  4. No send. `recover`'s module calls no `send_create`, `send_message` or `dispatch` and no client method but `GET`.
     Across every test the fake's log holds no `POST` made during `recover`.
  5. Idempotent and crash-safe. A second `recover` changes nothing and asks only about what is still unknown. A
     `BaseException` at each of its transitions, then a re-run, converges on the same store.
  6. Refused clients settle nothing: an unreadable or drifted allowlist, a call the client refuses.
  7. A row that changes state between `recover`'s read and its transition (the store's `IllegalTransition`: a writer
     that did not take the lock) is reported and left as it now is. `recover` goes on with the other rows and never
     retries the transition.
  8. A mutation check, as E-01.4.1's: at least the lock dropped; a `reserved` row failed without its lookup; a `200`
     under a `reserved` row settled; a key outside the namespace touched; a not-found turn marked `failed`.
- **STOP gates.**
  - **G15.** Before coding the table, list every (class, state) pair that a death at each statement boundary of
    `dispatch` and `send_message` can leave (E-01.1.2's method). STOP when a pair is not in R18's table: report it,
    and do not invent a rule.
  - STOP on any need to change the store, a transition pair, a record format or `reconcile.py`, or to end an attempt
    or send anything.

### Slice 5c: the cited core and the restart matrix. **After PB-10 and PB-11.**

- **Purpose.** E-01.4.2's proof.
- **Files.**
  - `integrations/agentfixture/` (`observations.json`, `core.py`, `README.md` with the provenance table).
  - The three test modules that hold the fakes now import them, keeping their test-only knobs as subclasses.
  - The matrix test, in `integrations/dispatch/tests/` so that no new suite is registered in this leaf.
- **Written before the matrix runs** (the rule precedes the observation): the table below, with planning's reading of
  PB-11 in the three held rows, and the provenance table.

| Row | The dispatcher dies | Store after the death | After `recover` | Then | Creates the fake received | Messages it received |
|---|---|---|---|---|---|---|
| A | before the reservation | nothing | nothing | dispatch, ordinal 1; run | 1 | 1 |
| B | `reserved` | attempt 1 `reserved` | lookup `404`: `failed` | dispatch, ordinal 2; run | 1 | 1 |
| C | `dispatched`, create not received | `dispatched` | `unknown`; `404`: `failed` | dispatch, ordinal 2; run | 1 | 1 |
| D | `dispatched`, create received | `dispatched` | `unknown`; `200`: `confirmed` | a repeat of the dispatch is refused before any reservation; run | 1 | 1 |
| E | no death: the create's answer is lost | `unknown` | `200`: `confirmed` | run | 1 | 1 |
| F | `confirmed`, before the run | `confirmed` | nothing | run | 1 | 1 |
| G | after SEED, before the turn journal | `confirmed`, no journal | nothing | run: a second SEED is refused, `SEED_FAILED`; held | 1 | 0 |
| H | turn journal `reserved` | turn `reserved` | reported, not sent | run refused with zero calls; held | 1 | 0 |
| I | turn `dispatched`, message not received | turn `dispatched` | `unknown`; not in the events: stays; held | result step refused | 1 | 0 |
| J | turn `dispatched`, message received | turn `dispatched` | `unknown`; in the events: `confirmed` | result step resumes when finished | 1 | 1 |
| K | the message's answer is lost, then a death | turn `unknown` or `confirmed` | in the events: `confirmed` | result step | 1 | 1 |
| L | turn `confirmed`, during the wait | turn `confirmed` | nothing | result step | 1 | 1 |
| C', D', J' | as C, D, J, then a restore | an epoch open | the store's sweep, then as C, D, J | the epoch closes; then as the row | 1 | as the row |
| Z | nobody: another holder has the lock | rows in flight | `DISPATCHER_BUSY`, nothing changed, zero calls | | 0 or 1 | 0 |

- **In every row:** at most one `POST /api/conversations` per operation key; at most one conversation holds a message;
  `recover` made `GET`s only; a second `recover` changes nothing.
- **The call log records what the fake received.** A request a transport event drops before the fake leaves no entry;
  it is a wrapper outside the core. E-01.4.1's `lost(performed=False)` counts such a request as a create received.
  That is harmless there and would falsify row C here.
- **What the matrix's restart is.** A simulated death: the act's continuation is dropped, the lock released and the
  store reopened. The real-process facts it rests on are E-01.1.2's crash matrix and slice 5a's condition 2. The live
  restart is E-01.6's. Say so in the evidence; do not call it a process restart.
- **Completion.** E-01.4.2's clauses as planning words them; no changed assertion and the same test ids in the three
  modules that held the fakes; no row decided by an injected answer.
- **STOP gate G16.** STOP when a row's expected value cannot be stated before the run; when a field of an answer the
  matrix uses has no class under planning's answer to PB-10; or when a row's verdict would rest on an injected answer.

---

## 3. Decision draft (Proposed)

A new record, not a point of 0026. 0026 is about transport authority and the fixture; this is custody of an in-flight
dispatcher act, and it should not wait on, or be accepted with, a fixture record.

Accepted by: the engineering manager under decision 0018 points 1 and 3.1. It is an architectural decision inside
committed scope that changes no criterion, no Owner-approved policy and, on my reading of R20, no other leaf's
contract. It authorizes no reserved act. Suggested handling, as for 0025 and 0026: committed as Proposed with slice
5a's records, accepted at E-01.4.2's verdict.

```
## 0027 - Dispatcher restart: the dispatcher lock, and the recovery of an interrupted create and turn

Status: Proposed - 2026-11-16, for plan leaf E-01.4.2 (architect, gates A and G). It authorizes no reserved act.

Authority: plan leaf E-01.4.2 and its group E-01.4 (actions, artifacts and proofs unchanged by this record); the I1
commitment (evidence/bootstrap-log.md, commitment-i1-2026-11-16); blueprint #integration-contracts ("Failure and
recovery at the connections", the row "Process dies during dispatch"; "A single-user initial mode may serialize
dispatch") and the dispatch contract ("A lost HTTP reply is not permission to start a new conversation"); decision
0001 (the reserved conversation id); decision 0004 points 7 and 9; decision 0010 point 1; decision 0018 points 1 and
3.1; decision 0024 points 6.1 and 6.2 and residual 5; the Owner's direction of 2026-11-13 on recovery, which this
record keeps to; E-01.4.1's verdict (e-01-4-1-verdict-2026-11-16).

Gate: architecture consultation at gates A (a relied-on premise failed: nothing recovers a create or a turn that a
dispatcher left in flight outside a restore epoch) and G (execution custody: no duplicate execution).

Supersedes: none. It applies decisions 0001, 0004 and 0024 and changes no accepted record's text. It enforces, at two
points, the one-dispatcher assumption that decision 0024 records as its residual 5.

## Context
- A dispatcher that stops between a write-ahead transition and its outcome leaves a typed attempt reserved or
  dispatched, or a turn journal dispatched. Outside a restore epoch nothing moves such a row: the attempt is a live
  claim for ever, and its Work can never be dispatched again.
- No case duplicates a create or a message. That is the store's compare-and-swap, not recovery's doing.
- The integration store has other live writers. A sweep of every dispatched row is sound only under a restore's
  exclusive custody.

## Considered options
1. An explicit recovery act whose evidence is an OS lock held across each write-ahead window: chosen.
2. The process identity recorded at dispatch and probed later: rejected. It changes every native record, needs a
   per-platform probe, and a restore brings a recorded identity back stale.
3. A store-level sweep outside an epoch: rejected. It settles other writers' receipts.
4. A lease with a timeout: rejected. Liveness by a guessed duration.
5. Recovery inside dispatch: rejected. It hides a settlement inside another act.
6. Resending the create under the reserved id after a not-found lookup: rejected. E-01.4.1's table makes failed
   terminal, and it would deliver a stage's secret twice.
7. One lock per attempt: not now. It is the refinement parallel dispatch would need.

## Decision
1. Safety is the store's. A create is sent only by the act whose reserved-to-dispatched transition of that attempt
   committed, and a message only by the act whose turn journal's did. Nothing is sent from any other state.
2. The dispatcher lock. One exclusive, non-blocking OS lock per integration store, a file beside the store in its
   custody, released by the operating system when its holder's handle closes or its process ends. dispatch holds it
   from before the reservation until the create's outcome is recorded; the attempt run holds it from before its first
   call until the message's outcome is recorded. Busy is DISPATCHER_BUSY, before anything is reserved or sent.
3. What the lock is evidence of. A holder that finds a typed attempt reserved or dispatched, or a turn journal
   dispatched, has established that the act which wrote it ended without recording its outcome. It is evidence of
   nothing at the Agent Server.
4. Recovery. recover, run under the lock by every dispatcher composition root before its first act:
   - a dispatched typed attempt becomes unknown, and is then settled as E-01.4.1 settles any unknown attempt;
   - a reserved typed attempt is failed when the Agent Server does not know its reserved conversation, and is held
     when it does;
   - a dispatched turn journal becomes unknown, and is confirmed when the conversation's events hold the message;
   - anything else is left as it is.
5. Outcomes come only from the Agent Server: found is confirmed, not found is failed for a create and stays unknown
   for a message, and an answer that decides nothing leaves the row as it is.
6. Recovery sends nothing, ends nothing, reserves nothing and deletes nothing. Where an effect cannot be observed or
   repeated, the attempt is held on its conversation, and E-05.8's end is its exit.
7. Namespace. Only typed attempts and turn journals. Every other key keeps its own resolver. The store's reconcile
   and its restore-epoch rule are unchanged.
8. Limits. The lock coordinates cooperating dispatcher code and is not a security boundary (decision 0010 point 1).
   It does not close the window in which a create still completing at the server is not yet visible to the lookup.

## Consequences
- The store's schema, states, transitions and API are unchanged; its lifecycle contract names the two recovery
  causes. No E-01.1.x guarantee changes.
- Decision 0024's residual 5 is enforced at the create and at the message, and stays an assumption elsewhere.
- E-01.5's non-overlap rule asks the Agent Server about every earlier ordinal whose history holds a dispatched event,
  whatever its final state.
- E-01.6 observes the recovery and the lock on the live transport.

## Not decided here
A resumable seed or turn; closing the not-yet-visible window, or stopping a conversation that appears under a failed
attempt (E-01.5); the lock's granularity for parallel dispatch (E-04.2.x); whether the result journal's and the end
journal's own resume arms take the lock; a resolver for a reserved attempt whose conversation exists after a restore
(decision 0004 point 7).

## Not verified
Linux and macOS, where the lock belongs to the open file description and a child that inherited it keeps it; the lock
and the recovery on the live transport; how long a create stays invisible to the lookup on a live server.
```

---

## 4. Question 2: advice for planning

### 4.1 What the committed evidence observes

"Each fake answer cites its F-04.2 observation" cannot be met as written, and your proposed wording would not be
meetable either, for three reasons.

1. **The unit is the field, not the route.** E-01.7's classes are per field. One answer mixes them.
2. **More records than two hold the observations.** The complete `/server_info` answer is F-04.1c section 3, which is
   what the existing fixture file cites. A refused create is S-01.3.1's. E-01.7's action does not name F-04.1c;
   its proof does not restrict the source.
3. **Three kinds of field have no class on the dispatcher's face under E-01.7's proof as amended.** The table shows
   which; the third kind is not in your list and is the one that matters.

| Answer on the dispatcher's face | Field | Does the dispatch path read it | Standing |
|---|---|---|---|
| `GET /server_info` 200 | `version`, `capabilities`, `conversation_runtime`, `available_conversation_runtimes` | yes | observed: F-04.1c section 3, F-04.2 4.1 |
| | `uptime`, `idle_time` | no | observed, clock-valued |
| `POST /api/conversations` 201 | status; `id` | yes | observed (F-04.2 4.2; D1 step (2)); `id` is the request's echo |
| | every other field, for the D1-shaped create | no | **not observed for that request**: F-04.2's body answers F-04.2's own fixture request, and D1's record keeps the status and the id only |
| | `created_at` | no | clock-valued |
| `POST /api/conversations` 200 | status; `id` | yes | observed: F-04.2 4.5 |
| `GET /api/conversations/count` 200 | the integer | yes | observed: D1 steps (3) and (10) |
| `GET /api/conversations/{id}` 200 | `id`; `execution_status` | yes | `idle` F-04.2 4.3; `finished` D1 step (6); `running` is for the engineer to cite or refuse |
| `GET /api/conversations/{id}` 404 | status | yes | observed: F-04.2 4.9 |
| | `detail` | no | not observed |
| `GET .../runtime` 200 | `runtime_status`, `can_resume` | yes | observed: F-04.2 4.3 and 4.6; D1 steps (3) and (9) |
| `DELETE .../runtime` 204 | status | yes | observed: F-04.2 4.6; D1 |
| `POST .../bash/execute_bash_command` (SEED) 200 | `stdout`'s success line, `exit_code` | yes | the pinned SEED script's rule (harness code the production path runs), with D1 step (4) |
| | `stderr` | no | not observed |
| | a second SEED on one conversation | | no observation: refused |
| `POST .../events` 200 | status | yes | observed: D1's call list |
| | the body | no | not observed |
| `GET .../events/search` 200 | `items`, `next_page_id` | yes | observed: F-04.2 4.4, on an empty log |
| | **the event that records the dispatcher's own message:** its `kind` | yes | the kind is observed at D1 step (7b), as a count |
| | its text | yes | the request's echo |
| | **its `source` and its message structure** | **yes** | **not observed in any committed record** (searched: no evidence file holds one) |

- D1 confirmed its turn by a 2xx. No committed live run has ever settled a turn from the events, which is what
  decision 0024's "Not verified" already says of "a lost answer".
- So rows J and K of the matrix, the proof's "after the initial message", can be shown offline only with an event
  whose two dispatcher-read fields come from the pinned source.

### 4.2 Your ruling on test knobs

I agree, with one distinction that E-01.7's proof makes and "transport events or test knobs" blurs.

- A **transport event** is a non-answer: a response withheld, a connection closed. E-01.7 lists it with its scenario in
  the provenance table. The matrix needs only these: a death, a lost answer, a request that never arrives.
- A **fabricated answer** (a 422, 500 or 202 create, an overridden body) is not a transport event. It is a test knob:
  a subclass in the test module, unreachable from the promoted core, never served. No row of the matrix may be
  decided by one.

### 4.3 Recommended proof wording for E-01.4.2

The first two sentences stay as they are, with one addition, "which records what the fake received". The last clause
is replaced. Whole text:

> Same conversation is recovered without repeated effects; original E-01.4 proof satisfied. Offline, against the fake,
> across a lost create response and a dispatcher restart at each step (before the create, after it, after the initial
> message): no second create and no second initial message, shown by the fake's call log, which records what the fake
> received. Each answer the fake gives is an entry of the fixture catalog E-01.7 serves, and each field of it is, in
> the provenance table, of one of the provenance classes of E-01.7's proof: an observation is cited to the committed
> record of the live run that observed it (F-04.2's lifecycle; where F-04.2 did not observe it, F-04.1c, the E-01.3.x
> or S-01.3.1 evidence, or the D1 run record of 2026-11-16) and only for an equivalent request. A clock-valued field
> reproduces its cited observation's recorded value unchanged and is marked clock-valued. A field the committed
> evidence does not observe is not served, and a request whose answer the dispatch path would read from such a field
> is refused with the fixture's label; the one exception is the event that records the dispatcher's own initial
> message, whose source and message structure are derived from the pinned upstream source, marked source-derived, not
> observed. A transport event a test injects (a response withheld, a connection closed, a request that never arrives)
> is not a catalog answer and is listed with its row; an answer no cited run gave is a test knob outside the catalog,
> and no row of the restart matrix is decided by one.

The action's "whose answers are traced to F-04.2's live observations" should follow: "traced to recorded live
observations".

### 4.4 How the three kinds of field should be classed

So that one catalog serves both leaves: E-01.4.2's proof carries the rules (4.3), and E-01.7 carries the first two as
readings in its notes, so that its own provenance table is judged the same way.

1. **Clock-valued fields** (`created_at`, `updated_at`, `uptime`, `idle_time`, an event's `timestamp`): class
   *observation*, marked clock-valued.
   - The value is the cited record's, unchanged, in every scenario. The fixture has no clock, and its scenarios
     advance by call count.
   - E-01.7's "cited only when the inputs that determine it equal the observed request's" is read as not applying to
     the clock. What it protects is that no observation is passed off as the result of a different request, and a
     timestamp nothing reads is not a result.
   - The condition that keeps it honest: no dispatch-path code reads a clock-valued field.
   - Rejected: generating a current value (the fixture's own code, a failure by E-01.7, and not deterministic);
     leaving it out (where the response model requires the field, the answer no longer validates); pinning the rule
     in decision 0026 (the pinned-rule class would admit it, but execution would then be defining an acceptance class
     for a proof planning wrote).
2. **Fields no committed record observes and the dispatch path does not read** (the `404`'s `detail`, the message
   answer's body, `stderr`, the D1-shaped create's other fields): **not served.**
   - The provenance table lists them per answer as "not served: no committed observation".
   - This fails closed: a later change that starts reading such a field finds nothing, where a filled value would be
     consumed silently.
   - It needs one reading of E-01.7's validation clause for the dispatcher's face (PB-12): each served field
     validates against its property, and a required property that is not served and is listed so is not a failure.
     Only the dispatcher calls that face.
3. **Fields no committed record observes and the dispatch path does read:** the request is refused with the fixture's
   label. That is E-01.7's rule as written, and it is right: a repeated SEED and a failed turn stay unservable.
   - One exception is needed, and only for E-01.4.2: the event that records the dispatcher's own message.
   - **Recommended form: the exception lives in E-01.4.2's proof, as 4.3 words it, and E-01.7's proof text is not
     touched a third time.** The catalog holds the entry, marked source-derived. A note on E-01.7 says its served
     fixture refuses the request that would need it until E-01.6 re-cites it. So "only on the UI face" stays true of
     everything the listener serves. I1's run injects no fault, so it never asks.
   - Its observed counterpart has a home. E-01.6 sends a message and reads the event log live. Give E-01.6 the
     sentence U-03.2 was given: each dispatcher-face field marked source-derived is compared with the live answer
     observed there, corrected where they diverge, and re-cited; a field left uncompared is a failure of E-01.6.
   - Say in that sentence that the compared fields do not depend on `run`. E-01.6's message is sent with
     `run: false` and the dispatcher's with `run: true`; without the sentence the "equivalent request" rule would
     refuse the citation.
   - Broader alternative: amend E-01.7's proof to admit this one dispatcher-face answer as source-derived, so that
     the listener can serve it. Nothing in I1 needs that.

### 4.5 What this means for the catalog

- Each field's row carries: its class; its citation; the inputs that determine it; whether the dispatch path reads it,
  and where; whether it is served; and its marks (clock-valued, source-derived).
- The "read" column is bound to the code by a test, not by inspection. The robust form is a recording wrapper around
  the answers during the matrix and the dispatch suites: the keys the dispatch code reads are exactly the rows marked
  read, and none is clock-valued or unserved.
- The core answers by state, not only by route. The SEED success line is the answer to the first SEED of a
  conversation; no observation covers a second.

---

## 5. Planning items

Decision 0018 point 1: what changes a criterion is planning's. None is designed around.

| Id | Leaf | What | Class | Needed from planning |
|---|---|---|---|---|
| **PB-10** | E-01.4.2; E-01.6 | "Each fake answer cites its F-04.2 observation" cannot be met. F-04.2 sent no message (its finding 2). The message route, `count`, `finished` and the SEED answer are observed only at D1, and the complete `/server_info` at F-04.1c. Three kinds of field have no class on the dispatcher's face (4.1). | A mis-specified proof clause, `introduced-by` the plan amendment of 2026-11-16 (I1), `exposed-by` E-01.4.2's preparation. **Blocker for E-01.4.2's verdict, and so for E-01.5's start.** | The wording of 4.3, the readings of 4.4, and E-01.6's added sentence. |
| **PB-11** | E-01.4.2 | "Same conversation is recovered" at the three points where the effect is not observed or cannot be repeated (R21: G, H, I). There recovery holds the attempt on its conversation and sends nothing. | A reading to fix before the matrix's decision rule is written. It blocks slice 5c only. | Confirm: "recovered" reads as the blueprint's "attach to existing run or report unknown state". If planning wants continuation at G and H, that is a seed receipt and a turn resume: its own leaf or a deferral, with the Owner's direction of 2026-11-13 in view. |
| **PB-12** | E-01.7; E-01.4.2 | On the dispatcher's face, the D1-shaped create's answer and the conversation read may have properties the response model requires and no committed record observes for that request. "Not served, listed" then conflicts with "each response validates against ... the schema". | Conditional: it is a blocker only if gate G4 finds such a property. Raised now to save a round trip. If it holds: `introduced-by` the plan amendment of 2026-11-16 (I1 blockers), `exposed-by` this consultation. | The reading of 4.4 item 2 for the dispatcher's face. |

For your report, not a planning matter: draft 0027; new refusal codes; a lock file beside the integration store (no
new asset, edge, credential or listener).

---

## 6. Defects named

1. **Slice 5 of the I1 design record assumed that E-01.4.2 needs no dispatch change** (its file list is the fixture
   package and three test modules). `introduced-by` the architect's I1 answer; `exposed-by` the engineer's probe. This
   answer replaces it with slices 5a to 5c.
2. **The same answer repeated "cites its F-04.2 observation" in slice 5's proof and in R13 without testing it against
   F-04.2's finding 2**, which it had read. `introduced-by` the plan amendment of 2026-11-16 (I1) as to the clause;
   the missed check is the architect's. PB-10.
3. **`attempt_run._receipt` does not complete a receipt left `dispatched`.** It marks `dispatched` and `confirmed` in
   two transactions and, found again, completes only a `reserved` one (`attempt_end._write_cause` completes both).
   - Effect, inferred from the code and not run: a delivery, pull or intake receipt interrupted between the two is
     never `confirmed`. For the intake, `recorded_result` then answers `RESULT_STAGED_UNVERIFIED` although the intake
     was taken.
   - `unrelated-but-detected`. It is the same family as this unit's finding, and `recover` deliberately leaves these
     receipts alone. Its own leaf or a fix-forward, at your judgement; not a clause of E-01.4.2.

Not a defect: that the restart was unbuilt. `integrations/dispatch/README.md` records it as E-01.4.2's.

---

## 7. Not verified, and residuals

### Not verified

1. The probe's run; I read the code it exercises.
2. The pinned upstream copy against the locked wheel, beyond the five matching line numbers. The registry's code
   (`get_or_create`, the provisioning identity) was not read, so R22 item 1's window is an inference from the
   handler's order and two observed create times.
3. The locked release `openapi.json`: which properties the create's and the conversation's answers require (PB-12).
4. The lock on Linux and macOS, and on the live transport path.
5. Whether a committed record observes `execution_status` `running` on the conversation read (4.1).
6. That no existing test asserts the list of files in a store's directory. Slice 5a's G13 would show it.

### Residuals, stated

- **The lock is cooperative.** A same-account process that does not take it is not stopped (decision 0010 point 1).
- **The not-yet-visible window stays open** until E-01.5: an untracked idle conversation, never a second execution.
- **A hold needs the engineering manager.** After a death between the create and the message's receipt, the Work
  waits for an end and a new attempt.
- **A lookup's authority is the transport the caller supplies.** The store does not know which server instance
  received a create. A fresh guest's server answers `404` for everything; that is right only because a destroyed
  guest's conversations are gone with it.
- **A row whose pinned route allowlist can no longer be read stays held.** That is E-01.4.1's indeterminate case, and
  it now applies to a `reserved` row too. It arises when the profile's allowlist has changed since the reservation;
  the artifact reader is injectable.
- **Two copies of the lock primitive** (`integrations/ownerhost/service.py` and the new dispatch module). Unify them
  when either next changes. `integrations/storecore/storecore.py` is already in both packages' module sets, so that
  home would not move the set the Integration process's test pins.
- **Store-wide serialization of creates and message sends.** Harmless with one dispatcher; the granularity is
  E-04.2.x's question.
- **A `reserved` attempt whose conversation exists** has no resolver. It can arise only after a restore of the
  integration store.


## The engineering manager's rulings on this answer (2026-11-16)

- Question 1: ACCEPTED as ruled (option (c), with the dispatcher lock as its evidence at the write-ahead windows; option (b) rejected), with R16 to R22, slices 5a, 5b and 5c, and STOP gates G12 to G16. No store contract change; no E-01.1.x guarantee changes.
- Draft 0027 is committed Proposed with slice 5a and accepted, or not, at E-01.4.2's verdict (decision 0018 points 1 and 3.1).
- One fresh review covers slices 5a and 5b together.
- Defect 3 (an interrupted intake receipt left dispatched by attempt_run._receipt, inferred from the code): unrelated-but-detected; reproduced by a test and fixed forward in slice 5b if the test confirms it.
- Question 2: the test-knob distinction is accepted (a transport event is a listed non-answer; a fabricated answer is a test knob unreachable from the promoted core). PB-10, PB-11 and PB-12 go to planning; PB-10 blocks E-01.4.2's verdict on the critical path; slices 5a and 5b proceed meanwhile.
