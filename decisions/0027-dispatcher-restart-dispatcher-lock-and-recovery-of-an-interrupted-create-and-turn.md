# 0027 - Dispatcher restart: the dispatcher lock, and the recovery of an interrupted create and turn

Status: Proposed - 2026-11-16, for plan leaf E-01.4.2 (architect, gates A and G). It authorizes no reserved act.

**Authority:** plan leaf E-01.4.2 and its group E-01.4 (actions, artifacts and proofs unchanged by this record); the I1
commitment ([`evidence/bootstrap-log.md`](../evidence/bootstrap-log.md), commitment-i1-2026-11-16); blueprint
`#integration-contracts` ("Failure and recovery at the connections", the row "Process dies during dispatch"; "A
single-user initial mode may serialize dispatch") and the dispatch contract ("A lost HTTP reply is not permission to
start a new conversation"); decision 0001 (the reserved conversation id); decision 0004 points 7 and 9; decision 0010
point 1; decision 0018 points 1 and 3.1; decision 0024 points 6.1 and 6.2 and residual 5; the Owner's direction of
2026-11-13 on recovery, which this record keeps to; E-01.4.1's verdict (e-01-4-1-verdict-2026-11-16).

**Gate:** architecture consultation at gates A (a relied-on premise failed: nothing recovers a create or a turn that a
dispatcher left in flight outside a restore epoch) and G (execution custody: no duplicate execution); the architect's
answer with the engineering manager's rulings
([`evidence/I1-restart-recovery-design-2026-11-16.md`](../evidence/I1-restart-recovery-design-2026-11-16.md), section 3).

**Supersedes:** none. It applies decisions 0001, 0004 and 0024 and changes no accepted record's text. It enforces, at
two points, the one-dispatcher assumption that decision 0024 records as its residual 5.

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
4. Recovery. recover, run under the lock before its first act by every dispatcher composition root except the native
   driver (d1_run does not call it; that goes to the leaf that next runs it live):
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
Linux and macOS, where the lock belongs to the open file description and a child that inherited it keeps it; there, a
fork without exec inherits the lock's open file description, so a forked child alive after its holder ended keeps the
lock held (the handle's being non-inheritable closes it only at exec); the lock and the recovery on the live
transport; how long a create stays invisible to the lookup on a live server.
