# 0020 - Dispatch-input decisions: design acceptance, manifest promotion, the delegated-decision record and load_manifest's enforcement

Status: Accepted (engineering manager) - 2026-11-13, at the completion of plan leaf P-04.3, under decision 0018 points 1 and 3.1 (an architectural decision inside committed scope that changes no acceptance criterion, no other leaf's contract and no Owner-approved policy). It authorizes no reserved act. Previously: Proposed - 2026-11-13, for plan leaf P-04.3 (architect, gates B and G; engineering manager's rulings)

**Authority:** plan leaf P-04.3, "Promote approved dispatch inputs through recorded decisions" (its action,
artifact and proof unchanged); decision 0008 points 2 and 5 (acceptance "delegated by an accepted decision
record"; the exact revision); decision 0012 points 4 to 6 and 9 (the recorder's own state, its challenge, run
only in the main session on an Owner decision); decision 0018 points 3.2, 3.3, 4.3, 4.8, 5 and 7 (the two
delegations, the reserved recorder decisions, weakening an Owner-accepted decision, standing authorizations,
presence-checked log quotes); within decisions 0009 (the managed data root), 0010 point 1 (the same-account
limit) and 0014 (every repository read through the repository-access module).

**Gate:** architecture consultation at gates B (durable decisions no record settled: the record shape of a
delegated decision, where the records live and what `load_manifest` trusts, the definition of replay) and G
(a security control: the only writer of the live manifest and the refusal at load). The architect's work design
was accepted by the engineering manager with rulings R1 to R8 and, after the independent review and its
re-review, the fix-forward rulings F1 to F8 and F11 and N-A to N-D; this record states the design **as built**.

**Supersedes:** none. It refines decision 0012 points 4 and 5 (two more kinds in the recorder's state and the
store), applies decision 0018 points 3.2, 3.3, 4.8, 5 and 7 and decision 0008 points 2 and 5, and changes no
accepted record's text.

## Context

The approved-input manifest (`ai-engineering-harness/dispatch/approved-inputs/v1`) is the dispatcher's approval
source: the repositories, the accepted design revisions, the profiles with their sha256, the catalog pins and the
bindings (`integrations/dispatch/dispatch_inputs.py`). Until P-04.3 nothing recorded who approved it:
`load_manifest` schema-checked whatever file it found under the managed data root, and the custody section of
the dispatch README said that a change was "visible afterwards, not impossible".

P-04.3 requires the manifest and each accepted-design entry to be written only through recorded decisions in
the shared Owner decision-record shape of P-04.1 and P-04.2, and `load_manifest` to detect and refuse, each with
a stable code, an entry without a recorded decision, a digest other than the decided one, a design entry without
a design-acceptance record and a replayed decision. Decision 0018, accepted after the plan was written, delegates
two of these decisions (design acceptance inside a recorded commitment, point 3.2; manifest promotion inside an
Owner-granted envelope, point 3.3) to the product manager, and requires that a delegated acceptance is "never
recorded as an Owner decision".

## Considered options

- **One record format with an `authority` field.** Rejected: an Owner record and a model-decided record would be
  one token apart, and opening `statement_verdict` to an agent attribution would make the P-04 gate ("never
  minted, approved or merged by a model") false.
- **A sidecar decision file beside the manifest, or a record in the project repository's OpenSpec tree.**
  Rejected: a file pair is self-consistent forever, so replay cannot be detected from files; whoever writes the
  manifest writes the sidecar; `load_manifest` would have to read repositories, and the acceptance recorder
  validates every file of a change's `owner-decisions/` as an Owner record.
- **Schema v2 with a per-entry decision field.** Rejected: it needs a plan amendment and breaks every stored
  reservation (`ResolvedInputs.from_json` pins the v1 schema). The approval is carried on the loaded manifest
  instead.
- **The adopted design:** two formats, receipts in the integration store, one writer, one enforcement point
  (below).

## Decision

### 1. Two decision kinds and their subjects

`owner-decision/v1` gains two kinds, nothing else of it changing (`integrations/owner/owner_decision.py`):

- `accept-design`: `repository` (a manifest repository id; a label, which nothing ties to a project repository),
  `change` (an OpenSpec change id), `commit` (the exact revision, 40 or 64 hex digits), `content` (`sha256:` over
  the change's folder at that commit: for each blob under `openspec/changes/<change>/`, in ascending path order,
  the line `<sha256>  <path>\n`; `commit` and `content` bind what was accepted) and `supersedes` (the
  acceptance it replaces in its series, or `null`).
- `promote-manifest`: `schema`, `version` (the manifest's version: its position in the promotion series),
  `digest` (`sha256:` of the manifest's bytes), `previous` (`{version, digest}` of the promotion it replaces, or
  `null`) and `designs` (for each `designs` entry, in manifest order, `{repository, change, commit, acceptance,
  sequence}`).

### 2. Two authorities, two formats

A decision of the Owner is an `owner-decision/v1` record, taken through the recorder's single-use challenge
(`prepare`, then `record` with the Owner's statement, which must name the change or the token
`approved-inputs-v<version>` and come through an admitted channel). A decision delegated by decision 0018 is a
`delegated-decision/v1` record (`integrations/owner/delegated_decision.py`): the same `kind` and `subject`
(validated by the same function), and a `delegation` block (`record`, `point`, the harness `revision` and the
record's blob `digest` at which it was read, and the `basis`) where the Owner's record has `shown` and
`statement`; `decidedBy` the role the delegation names and `recordedBy` equal to it. A delegated decision is never
an `owner-decision/v1` record, is never kept among the Owner's records and is never shown as the Owner's.

The delegation table is data, one row per kind: `accept-design` under point 3.2 and `promote-manifest` under
point 3.3, both decided by `agent:product-manager` only; the engineering manager is refused
(`DECIDER_NOT_DELEGATED`). A kind without a row is never delegated (`DELEGATION_KIND_UNKNOWN`). A later leaf
(S-03.5) adds its kind as a row, with its own subject check and basis type, through the same `read_authority` and
`decide`; the record's fields do not change.

A delegated acceptance never supersedes an Owner acceptance of the same change (`OWNER_ACCEPTANCE_HEAD`):
weakening an Owner-accepted decision stays reserved (decision 0018 point 4.8). Promotions are not gated so: a new
manifest version does not weaken an earlier one.

### 3. The two series, positions and replay

Promotions form one series whose position is the manifest's `version`; the acceptances of one (repository,
change) form one series by `sequence`. Each decision is a write-ahead receipt in the integration store at its
position (`dispatch-inputs/v1/promotion/<version>`, `dispatch-inputs/v1/design/<repository>/<change>/<sequence>`,
intent format `aieh-dispatch-input-decision/1`, actor `dispatch-input-recorder/1`). Positions start at 1 and are
contiguous; a decision's link names the last **confirmed** decision of its series and it takes the next free
position; a failed or unconfirmed position is spent and never reused. The store's unique key makes a position
single-use.

Replay, and where it is refused: a second `record` on a consumed challenge (`CHALLENGE_CONSUMED`); a challenge
whose position another decision took, or whose series or design binding changed after it was shown
(`CHALLENGE_STALE`); a candidate naming a design revision whose acceptance a later one superseded
(`DECISION_REPLAYED`, at the promotion act); an older manifest put back after a later promotion was confirmed
(`DECISION_REPLAYED`, at load). No promotion is prepared, recorded or delegated while an earlier promotion
receipt is reserved, dispatched or unknown (`PROMOTION_UNRESOLVED`): once a later promotion replaced the live
file, resolving the earlier one by reading would record a decision that landed as failed.

### 4. Where the records live and what is trusted

The store's confirmed receipts are what the verifier reads (`integrations/owner/input_decisions.py`). The
Owner's challenges and decision copies are in the recorder's own state,
`<state>/owner-authorization/dispatch-inputs/`; delegated copies in `<state>/delegated-decisions/dispatch-inputs/`.
The copies are for people and backups; nothing reads them to decide, and no file beside the manifest is read. No
receipt holds a filesystem path. The verifier also walks the promotion series from position 1 to the manifest's
version by direct lookups and refuses (`DECISION_RECORD_INVALID`, naming the position) a missing position, a
receipt not reserved by the recorder's actor, a repeated `decisionId` or Owner challenge, or a confirmed
promotion whose `previous` is not the confirmed promotion before it; it checks the bound design receipt's actor
too. A gap **above** the manifest's version cannot be seen without listing the store, which the verifier does not
do: that limit is documented, not closed.

### 5. The promotion act: the only writer of the live manifest

The dispatch-input commands (`integrations/owner/input_recorder.py`; `task owner:design`, `task owner:promote`) are
the only writer of `<state>/dispatch/approved-inputs.json` (decision 0009). `manifest record` and `manifest
delegate` reserve the receipt, write the decision copy, mark the receipt dispatched, write the candidate's exact
bytes to a temporary file in the live file's own directory, replace the live file atomically, read its digest back
and confirm. A write that did not land (the copy, the temporary file or the replace) leaves the receipt failed and
the live file as it was (`PROMOTION_FAILED`); an outcome that does not read back as decided leaves it unknown
(`OUTCOME_UNKNOWN`), which `manifest resolve --version N` settles **by reading**, never by writing. A design act
that stops after its reservation marks its receipt failed when the store lets it (`IO_FAILED`), and so does no
other harm: a design acceptance has no external effect. Every refusal reserves nothing and leaves the live file
untouched. The module imports no Gitea and no credential module and reads no credential.

### 6. The enforcement at load

`load_manifest(path, *, decisions=None, repo_root=...)` keeps its path refusals first (`MANIFEST_PATH_INVALID`,
`MANIFEST_INSIDE_CHECKOUT`, before anything is read), then the read and the schema; without a decision verifier it
refuses `MANIFEST_NOT_PROMOTED`; otherwise it asks the verifier `(version, sha256, designs)` and passes on its
refusal in this order: `MANIFEST_NOT_PROMOTED`, `DECISION_RECORD_INVALID`, `MANIFEST_PROMOTION_UNCONFIRMED`,
`MANIFEST_DIGEST_MISMATCH`, `DECISION_REPLAYED`, `DESIGN_ACCEPTANCE_MISSING`; a verifier that raises or answers
anything but a well-formed view of this manifest approves nothing (`DECISION_RECORD_INVALID`). The loaded
`ApprovedInputs` carries the approval view (`ai-engineering-harness/dispatch/manifest-approval/v1`), and
`approving_record(section, key)` names each entry's approving record: a design entry its design acceptance, every
other entry the promotion. The manifest stays schema v1; `parse_manifest`, `RESOLVED_FORMAT`, `POLICY_FORMAT` and
the golden policy digest do not change.

`resolve`, `admit` and `dispatch` accept only an `ApprovedInputs` object that `load_manifest` returned in this
process (held by identity: a replace, a copy or a hand-built equal object is refused), re-checking its approval
view, and refuse anything else with `MANIFEST_NOT_PROMOTED` before anything is read or reserved. That guard is
against convenience and accident, not against code of the same account in the same process. `load_manifest` does
not know which verifier it was given: the live driver (E-01.3.2) must pass
`input_decisions.verifier(<the managed integration store>)`, load the manifest for each dispatch and never cache
an `ApprovedInputs`. Design acceptances are not re-checked for currency at load: a later acceptance takes effect
when a manifest naming it is promoted.

### 7. What is checked about a delegated decision, and what is disclosed

Checked at the act: the delegation row, the decider and the basis's shape; the delegating record read from the
harness repository's `HEAD` commit through the repository-access module (the committed blob, never the work
tree), whose first `Status:` line must begin exactly `Status: Accepted (Owner) -`; and the basis as an authority
of its type, structurally. The basis link is `evidence/bootstrap-log.md#<anchor>`, and the anchor must open a
dated entry of the log's Decisions at `HEAD` (the entry runs to the next top-level list item or heading). A
`commitment`'s entry title begins, after its `<date>: `, with `Commitment:`, and the quote lies inside the entry;
an `envelope`'s entry title begins with `Owner standing authorization:`, and the quote lies inside its verbatim
block (its `>` lines, prefixes stripped, whitespace collapsed on both sides). An absent anchor or quote is
`DELEGATION_BASIS_NOT_RECORDED`; an undated entry, an entry of another title (an `Owner direction:`, a per-act
`Owner authorization:`), a quote outside the entry or its block, or a prepared-not-granted Owner-actions row is
`DELEGATION_BASIS_NOT_AUTHORITY`. Then everything the Owner path checks about the subject.

This needs a convention of the records: the session in which the Owner grants a standing authorization records
it in the log's Decisions as an entry titled `<date>: Owner standing authorization: <what it covers>`, with an
anchor and the Owner's words verbatim as a `>` block (decision 0018 points 5 and 7). Until such an entry exists,
every delegated promotion fails closed and a promotion is the Owner's.

Not checked, and disclosed (decision 0018 point 7; decision 0010 point 1): who actually ran the command; that the
change lies inside the commitment's scope, that the Owner gave its intent and that it is not a change to the
harness's own governance; that every entry lies inside the envelope and that the envelope has not expired or
stopped; and who wrote a log entry ("a log quote is checked for presence, not authorship"). At load, the verifier
checks the decision's form and its receipt, not the delegation again: no accepted record says what a later change
to the delegation does to earlier decisions.

### 8. The threat model

Decision 0010 point 1 places a process with the Owner's account privileges out of scope, and decision 0009 point
11 keeps agents in the execution guest from the managed data root and the store. Within that, unapproved content
is **detected and refused at load**, not prevented from being written: a file beside the manifest has no effect,
and a manifest loads only when the store holds a confirmed receipt at its version with its digest, which running
the recorder leaves as an append-only receipt naming the authority it claimed. A same-account write of the store
that imitates the recorder (its actor, fresh ids, the right `previous`) is outside the threat model; the series
checks of point 4 catch only a careless one.

### 9. Not decided here

1. **E-05.1's clause "The OpenSpec change has a design-acceptance record (decision 0008)".** The record is held by
   the recorder and names the change at its exact revision; no file is added to the change folder. If the change
   folder must carry a pointer to the decision, that is E-05.1's or a later leaf's.
2. **OA-22 item (j).** As realized, a delegated promotion rests on an anchored `Owner standing authorization:`
   entry whose verbatim block holds the quoted grant; containment of the entries in the envelope stays the product
   manager's recorded judgment. Presenting item (j) as a typed list would make containment mechanical; granting it
   through the recorder would make the grant itself enforced. The Owner grants whichever form planning presents.
3. **"Recorded through the authorization recorder" (decision 0018 point 3.2)**, realized as commands of that
   recorder in a module of their own (`integrations/owner/input_recorder.py`), importing none of its Gitea or
   credential code. Whether another recorder was meant is not decided here.
4. **The target carrier.** A promotion decision binds a digest, so the same decision can later ride a protected
   Gitea policy merge (G-03); that is the Owner's and planning's at that gate.
5. **A class-E path category for authorization records** (E-01.2.1 finding F3), carried unchanged.

## Consequences

- The live manifest has one writer and loads only through a recorded decision; `parse_manifest` stays for
  checking only.
- The resolution and admission tests load their fixtures through `load_manifest` with a test-only verifier; the
  proof (`integrations/dispatch/tests/test_manifest_promotion.py`) uses the real recorder, a throwaway store and
  the real verifier.
- A delegated promotion needs an `Owner standing authorization:` entry in the log; none exists when this record is
  written.
- The integration store carries the recorders' decision receipts, which `load_manifest` reads as evidence; the
  authority stays with the decider.

## Evidence

`evidence/P-04.3-dispatch-input-decisions.md`: the proof table, the independent review and re-review, the mutation
checks and what is not verified. The code: `integrations/owner/owner_decision.py`,
`integrations/owner/delegated_decision.py`, `integrations/owner/input_decisions.py`,
`integrations/owner/input_recorder.py`, `integrations/dispatch/dispatch_inputs.py` and their tests.

## Not verified

Anything live: the managed data root and its integration store, a real Owner decision, a real standing
authorization, the live driver (E-01.3.2) and Task. Linux and macOS.

## Current facts (2026-11-13)

Recorded by the engineering manager at S-03.5's completion ([decision 0021](0021-provider-envelope-model-selection-and-broker-enforced-cap.md), Accepted). The numbered points are unchanged.

1. The delegation table has a third row: `select-models`, decision 0018 point 3, decided by `agent:engineering-manager`
   only, with the basis type `envelope-receipt` (the governing provider-envelope receipt of the authorization recorder).
   `delegated-decision/v1`'s fields did not change, as point 2 foresaw.
2. `read_authority` takes the integration store (`store=`) for a basis type that needs it; without a store such a type
   refuses (`AUTHORITY_UNAVAILABLE`), never passes.
