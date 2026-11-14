# 0021 - The provider envelope: the broker's start precondition, the model selection and the broker-enforced cap (the cap retired by amendment 1)

Status: Accepted (engineering manager) - 2026-11-13, at the completion of plan leaf S-03.5, under decision 0018 points 1 and 3.1 (an architectural decision inside committed scope that changes no acceptance criterion, no other leaf's contract and no Owner-approved policy; it narrows the broker's start). It authorizes no reserved act: no provider key, envelope, spending cap, egress or model call. Amended 2026-11-13 (amendment 1, product manager, on the Owner's direction of 2026-11-13): the spending limit and the broker-enforced cap are retired. Amendment 2 (2026-11-14, effective with decision 0023's acceptance) scopes this record to the brokered execution profile. Previously: Proposed - 2026-11-13, for plan leaf S-03.5 (architect, gates C and G; engineering manager's rulings)

**Authority:** plan leaf S-03.5, "Bind the broker's real-provider start to a recorded provider-envelope
authorization" (its action, artifact and proof unchanged); decision 0012 (the authorization recorder's receipts,
points 7 to 9); decision 0015 as amended (the broker, sections 2, 5.1 and 6.3: counts and token budgets, not
prices); decision 0018 points 3, 4.1, 4.2 and 7 (technical model selection delegated to the engineering manager
inside an authorized model-access envelope; the Owner's per-act decisions; presence-checked records); decision 0020
(the delegated-decision record and its table); within decisions 0009 (the managed data root and `config.yml`) and
0010 point 1 (the same-account limit).

**Gate:** architecture consultation at gates C (durable decisions no record settled: the envelope's canonical form,
which authorization governs a start, the two selection authorities, the cap's units and ledger) and G (a security
control: the start precondition before the provider key and the listeners, and the fail-closed cap). The
architect's work design was accepted by the engineering manager with rulings R1 to R11 (R6 qualified), the slice
rulings, and, after the independent review and its re-review, the fix-forward rulings F1 to F7; this record states
the design **as built**.

**Supersedes:** none. It applies decision 0018 point 3 and decision 0015 section 6.3, adds a third row to decision
0020's delegation table, adds a first consumer of decision 0012's `authorize-operation` receipts outside the
recorder, and changes no accepted record's text.

## Context

The inference broker of S-03.2 (`integrations/inference/inference_broker.py`) reads the provider key and opens its
listeners for any configured family; nothing tied a start toward a real provider to an Owner decision. The
classification of instruction-only consequential boundaries (the log's Decisions, 2026-11-12) found that spend,
external egress and the provider key all pass through that start. S-03.5 requires that `serve`, for any family
whose upstream is not loopback, refuses before it opens a listener or reads the key unless the integration store
holds a confirmed, unexpired authorization recorder receipt whose operation is the provider envelope and whose
target is the canonical digest of the live envelope; that the model selection is either part of that digest or a
delegated record under decision 0018 point 3 naming the envelope's receipt; that a request for a model outside the
selection is refused; and that, where the provider does not enforce the Owner's limit on the dedicated key, the
envelope carries a cumulative cap that fails closed when reached or when usage is unknown.

## Considered options

- **A pointer in `config.yml` to the receipt, or a lookup "any confirmed receipt whose target is my digest".**
  Rejected: a pointer is a second thing to keep right and cannot see that the Owner has since authorized something
  else; a lookup by digest alone makes an old authorization valid for ever.
- **An envelope file under the managed root, written by an install step.** Rejected: the Owner's act is a merge by
  the authorization recorder, which writes no file; a second copy would have to be kept equal to the families.
- **A per-request write-ahead ledger for the cap** (reserve and dispatch before forwarding; confirm with usage).
  Not taken (ruling R7; section 6): three transactions on every paid request and a receipt per request for ever.
- **The adopted design:** the live envelope is a projection of the one configuration snapshot `serve` serves, bound
  by its digest to the last-decided provider-envelope receipt, with the manifest regenerated and compared, and a
  per-run ledger in the integration store (below).

## Decision

### 1. The provider-envelope operation and its canonical form

- **Operation kind** `provider-envelope`: the manifest's `kind`, so the receipt's `subject.operationKind`. It is
  authorized through the authorization recorder exactly as any operation (`integrations/owner/
  authorization_recorder.py`, unchanged; it learns nothing of the kind).
- **The live envelope** is projected from the one snapshot `serve` reads (once) and serves: the provider id, the one
  upstream origin and, when the envelope selects them, the models come from the families whose upstream is not
  loopback (the bound families); only what has no home there is the block `components.inference_broker.envelope`
  of `config.yml`: `expires_at` (a quoted UTC timestamp), `limit` (`amount`, a quoted decimal; `currency`;
  `enforced_by`, `provider` or `broker`; `cap`, an integer, with `broker` only) and `selection` (`envelope` or
  `delegation`). An unquoted timestamp or decimal is refused (`CONFIG_ENVELOPE_INVALID`), never normalized; every
  designed key passes the secret-shaped rule of decision 0009.
- **The canonical document** `aieh-provider-envelope/1`: exactly `format`, `provider`, `origin`
  (`https://<host>:<port>`), `limit` (`amount`, `currency`, `enforced_by`, `cap`), `expires_at` and `selection`
  (`{"by": "envelope", "models": {<family>: [<ids, sorted>]}}` or `{"by": "delegation", "record": "decision:0018",
  "point": "3"}`) (`integrations/inference/inference_envelope.py`).
- **The digest** (the receipt's `target`): `sha256:` and the sha256 of the document as canonical JSON by the
  integration store's own rule (sorted keys, no whitespace, UTF-8, no NaN; repeated and asserted equal by a test).
- **The canonical manifest** `operations/<operation>.json`: `operation`, `kind`, `target`, `expiresAt` and
  `envelope` (the document, so the Owner reads it in the recorder's challenge summary), JSON with a two-space
  indent and one final LF. **The manifest binding:** at start the broker regenerates the canonical manifest from
  the live envelope and the governing receipt's operation id and requires its sha256 to be the receipt's manifest
  digest, so what the Owner was shown is exactly what is enforced. `inference_broker.py envelope [--operation ID]`
  prints the document, its digest and the manifest as a JSON string (no console changes its line endings); it
  reads no credential or store.
- A change of the canonical form is a new format (`/2`): receipts recorded under `/1` then stop verifying.

### 2. Which authorization governs a start

The read side (`integrations/owner/envelope_decisions.py`) lists the recorder's receipts and keeps the
**candidates**: those under `owner-authorization/v1/` whose decision is a well-formed `owner-decision/v1` of kind
`authorize-operation` with `operationKind` `provider-envelope`, reserved by `authorization-recorder/1`, in
reservation order. **The last confirmed candidate governs** (the last decided). In this order:

- a receipt under the recorder's prefix that cannot be read, or a provider-envelope receipt that is not the
  recorder's (another actor or receipt format, a decision that fails `check_record` or does not bind its receipt's
  key, operation and digest, a repeated `decisionId`): `ENVELOPE_RECORD_INVALID`;
- none confirmed and none unsettled, or no decision source: `ENVELOPE_NOT_AUTHORIZED`;
- a later candidate `reserved`, `dispatched` or `unknown` (the Owner's later decision may be in force):
  `ENVELOPE_AUTHORIZATION_UNRESOLVED`, remedied by `authorization_recorder.py resolve`;
- the live digest is an earlier, superseded candidate's target: `ENVELOPE_REPLAYED`;
- the live digest is no confirmed candidate's target, or the merged manifest is not the canonical one:
  `ENVELOPE_MISMATCH`;
- the governing `expiresAt` reached: `ENVELOPE_EXPIRED`.

A later provider-envelope authorization ends an earlier one at the next start, whatever its expiry. No revocation
record exists: an authorization ends by its expiry, by a later one, or, outside the harness, by the key's
revocation at the provider.

### 3. The start precondition and the loopback rule

- **Order in `serve`:** the configuration is read once; the existing refusals and the port check come first; then,
  only when a family's upstream is not loopback: the envelope block (`ENVELOPE_NOT_CONFIGURED`) and the binding rule
  (`ENVELOPE_FAMILIES_UNBOUND`: the bound families share exactly one provider and one origin, and no loopback
  family names that provider); the governing receipt (section 2); the model selection (section 5); and, for a
  broker-enforced cap, the ledger (section 6). Only then are the provider key read and the listeners opened. A
  refused start exits 2 and writes no receipt and no audit line.
- **The exemption is `Origin.loopback` exactly:** an IP literal the interpreter calls loopback, on the one snapshot;
  a host name (`localhost` included) is never loopback and no name resolution takes part. With only loopback
  upstreams no line of the precondition runs and `serve` starts as before.
- `load_config` only shape-checks the block and never requires it: its other callers (the qualification launcher,
  the dispatcher's side) keep their codes.

### 4. What the broker holds: the minted object, expiry and supersession

- `authorize` returns one frozen `Authorization` (the receipt, operation and decision ids, the digest and manifest
  digest, the expiry, the provider and origin, the selected models, the limit's enforcement and, for a
  broker-enforced cap, the carried usage and the run). `Broker.start()` refuses a bound family unless it holds an
  object `authorize` returned in this process (`ENVELOPE_NOT_AUTHORIZED`; a copy or a hand-built one is not) whose
  provider and origin the family has (`ENVELOPE_MISMATCH`). This guard is against convenience and accident, not
  against code of the same account in the process (decision 0010 point 1).
- **At admission**, where the attempt budget is checked, a request of a bound family is refused when the held
  authorization is not one `authorize` minted (`ENVELOPE_NOT_AUTHORIZED`, 503), when the family's provider or
  upstream is not the held one (`ENVELOPE_MISMATCH`, 503), and from the expiry on (`ENVELOPE_EXPIRED`, 403). An
  answer already streaming completes; loopback families and the control listener keep working; nothing is written
  at the moment of expiry. Supersession takes effect at the next start.
- The start receipt and the status answer carry an `authorization` member only when an envelope is bound; it never
  carries a commit id (the I7 scan refuses a 40-hex run).

### 5. The model selection: two authorities

- **`selection: envelope`:** the bound families' configured models are inside the digest; changing, adding or
  removing one is `ENVELOPE_MISMATCH`.
- **`selection: delegation`:** a `delegated-decision/v1` record of kind **`select-models`**, the third row of
  decision 0020's delegation table (`integrations/owner/delegated_decision.py`): `decision:0018` point `3`, decided
  by **`agent:engineering-manager` only** (the product manager is refused `DECIDER_NOT_DELEGATED`), on an
  **`envelope-receipt`** basis `{type, receipt}` that is an authority when the integration store holds that receipt,
  reserved by the authorization recorder, of kind `provider-envelope`, confirmed. This basis type needs the store:
  `read_authority` takes it as a keyword and, without one, refuses `AUTHORITY_UNAVAILABLE`. Its subject: `leaf`,
  `models` (`{<family>: [{id, use, cost}]}`: exact identifiers, no wildcard, no duplicate, no family empty),
  `verified` (`{source, at}`) and `supersedes`. The act (`integrations/owner/selection_recorder.py delegate`;
  `task owner:select-models`) also requires the basis to be the governing, unexpired authorization and writes a
  write-ahead receipt at the next position of **one series `model-selection/v1/<n>`**, with a copy under
  `<state>/delegated-decisions/model-selections/`; it imports no Gitea or credential module.
- **At start**, the governing selection is the series' **last confirmed position** (an unsettled position is never
  in force and has no file effect, so it is harmless): none is `MODEL_SELECTION_MISSING`; a head that is not a
  well-formed `select-models` record of the selection recorder (another actor, another decider, an Owner record,
  another kind) is `MODEL_SELECTION_NOT_AUTHORIZED`; a head resting on another receipt is
  `MODEL_SELECTION_RECEIPT_MISMATCH` (a selection does not carry to a new envelope). Under either authority a
  configured model of a bound family the selection does not select is `MODEL_NOT_SELECTED` (the configuration may
  not widen it), and none left is `MODEL_SELECTION_MISSING`.
- **Per request**, `issue` and admission refuse any other model of a bound family (`MODEL_NOT_SELECTED`, 403),
  after the existing checks. The check reads the request body's top-level `model`, where the three declared
  families name it.

### 6. The cumulative cap (`limit.enforced_by: broker`)

- **Units: usage tokens, never money** (decision 0015 section 6.3): the usage the provider reports (input including
  cache, plus output) over every bound family, for the life of the **governing receipt**. How the cap follows from
  the money limit and the prices is OA-12's presentation and the selection's cost text; the broker does no price
  arithmetic.
- **The ledger, per run** (ruling R7): `inference/envelope/<nonce>/run/<k>` (`aieh-inference-envelope-run/1`),
  written and read back as the last fallible step before the listeners serve, and `.../run/<k>/close`
  (`aieh-inference-envelope-close/1`), written at the broker's own stop with the run's usage, requests, unknown
  answers and requests in flight. At start the runs are walked from 1 by direct lookups: a run receipt that is not
  confirmed never served and counts zero; a confirmed one needs the broker's confirmed close with no unknown answer
  and nothing in flight; the closed runs' usage is carried. `<nonce>` is the governing receipt's, so a new
  authorization starts at zero.
- **What one admitted request adds:** a usage report's total; zero when nothing of it was written upstream (the
  connection was never made); **zero for a complete answer outside 2xx (ruling R6: an assumption about the
  provider's billing, to verify at OA-12's presentation)**; **unknown** for a 2xx answer without readable usage,
  any answer cut off by the upstream or by the client leaving mid-stream, a request written and never answered, a
  connection made and the request cut while sending, and a broker error after admission. "Was anything written" is
  recorded before the answer is read, and on a failure before the connection is closed.
- **Fail closed, and stay closed:** the cap reached is `ENVELOPE_CAP_REACHED` and an unknown answer is
  `ENVELOPE_USAGE_UNKNOWN`, for every further request of a bound family in that run (429) and at every later start;
  a run without its close, or a close with unknown answers or requests in flight, is `ENVELOPE_USAGE_UNKNOWN` at the
  next start. **The stop:** the broker's own stop sets a stopping state under its lock before it reads the close's
  counts; from then on a request of a metered family is refused **`BROKER_STOPPING`** (503) before anything of it is
  written upstream, so the close's counts are the run's whole usage.
- **A closed envelope reopens only with a new provider-envelope authorization** (ruling R8; raising a cap is the
  Owner's per act, decision 0018 point 4.2); there is no reconciliation command.
- With `enforced_by: provider` nothing is metered and no ledger receipt is written; loopback families are never
  metered.
- **The alternative not taken** (R7), a per-request write-ahead ledger, survives a hard stop while idle; reconsider
  it when a hard stop closing the envelope proves operationally costly: at the first live use of a broker-enforced
  cap, or when the broker becomes a supervised service whose stop is a kill (decision 0011 point 2).

### 7. What is checked, and what is disclosed

**Checked** at start: the envelope's shape and binding, the governing receipt and its manifest, the expiry, the
selection and its authority, the ledger. At the act: the row, the decider, the basis's shape and that it governs,
decision 0018 at the harness repository's `HEAD` with `Status: Accepted (Owner) -`, the selection's shape.

**Disclosed, not checked:**

- Who ran the selection act; that its identifiers were verified against current provider information; that its
  costs are right; that it was presented to the Owner before the first paid operation (S-03.3's proof).
  Containment of the selection in the Owner's envelope is the engineering manager's recorded judgment.
- Only the top-level `model` of the request body is checked, for the three declared families; a family naming its
  model elsewhere needs a check of its own before it is declared.
- A refused start may create an empty integration store where none exists.
- One transient TLS or certificate failure closes a broker-enforced envelope until a new authorization: a TLS
  handshake that fails after the TCP connection counts as unknown (observed on CPython 3.12 on Windows).
- Requests admitted together can overshoot the cap by their own usage; charges that are not tokens are not
  counted; a stop that is not the broker's own closes the envelope; a store restored to an earlier backup loses
  recorded usage (decision 0004). After the broker's stop a `BROKER_STOPPING` refusal is not answered (the audit
  is closed): the connection is closed instead.

### 8. The threat model

The precondition turns the one instruction-only consequential boundary of the broker's start into a check at the
moment of the act: a start toward a real provider needs a decision the recorder wrote, for exactly the origin,
limit, expiry and identifiers the snapshot holds. It is a control against accident, convenience and a stale or
edited `config.yml`: unapproved settings are detected and refused at start, not prevented from being written. It is
not a control against a process of the Owner's account, which can write the store as the recorder does, read the
credential entry or forward from loopback (decision 0010 point 1), and it does not authenticate the Owner (decision
0012 point 9). The egress control stays a code-path control in the broker, evidenced by its connection census,
not an OS-enforced boundary.

### 9. Not decided here

1. **The expiry is a timestamp.** OA-22 item (g) "expires at D1's acceptance" cannot be the manifest's
   `expiresAt`; OA-12's preparation presents a date, and an earlier end is a superseding envelope, a stopped broker
   or a revoked key.
2. **Which repository carries the first real envelope manifest.** The recorder admits only the S-01.2.2 fixture
   repository; the authorization repository of G-03.1 is not built.
3. **"What may be sent"** to the provider, part of the envelope in decision 0018 point 3, is not a member of the
   envelope here; the broker cannot check content.
4. **Decision 0015 section 2.2's spend cap at the provider versus `enforced_by: broker`:** an envelope with
   `enforced_by: broker` is the Owner choosing the fallback in the act he already gives; the Owner's to choose.
5. **The envelope does not bind which key:** the precondition runs before the key is read, so the key's
   fingerprint is not part of it.

## Consequences

- A start toward a real provider needs the Owner's recorded provider-envelope authorization; a loopback start (the
  S-03.2 qualification) is unchanged.
- The integration store carries the envelope ledger (`inference/envelope/...`) and the selection series
  (`model-selection/v1/...`) beside the recorders' receipts; the authority stays with the decider.
- The delegation table has a third row and a store-reading basis type; the record's fields and the P-04.3 rows are
  unchanged.
- A broker-enforced cap closes the envelope on any unknown outcome, including one transient TLS failure, until a new
  authorization.

## Amendment 1 (2026-11-13): the envelope without a spending limit

By the product manager (a change to the contract between leaves and to S-03.5's criteria; decision 0018 point 1),
applying the Owner's direction of 2026-11-13 ("Owner direction: reconcile the D1 provider-access requirements before live execution", verbatim in `evidence/bootstrap-log.md`, Decisions) and decision 0018 revision 5. The text above stays as written; where it and this amendment
disagree, this amendment governs.

1. **The canonical form is `aieh-provider-envelope/2`** (section 1): exactly `format`, `provider`, `origin`,
   `expires_at` and `selection`. `limit` is removed from the document, from the `config.yml` block and from the
   digest. A block that still carries `limit` is refused (`CONFIG_ENVELOPE_INVALID`), never ignored. As section 1
   states, receipts under `/1` stop verifying; none was recorded for a real provider.
2. **Section 6 is retired.** No cumulative cap, no `enforced_by`, no per-run ledger (`inference/envelope/...`), and
   no `ENVELOPE_CAP_REACHED` or `ENVELOPE_USAGE_UNKNOWN`, at a request or at a start. Section 3's start order loses
   its ledger step. Section 4's minted object loses the limit's enforcement, the carried usage and the run. Section
   7's disclosures about the cap, and the Consequences item on a closed envelope, lapse with it. Spending is bounded
   by the provider account's own limits.
3. **Kept unchanged:** the operation kind, the canonical JSON and digest rule, the manifest binding and
   `inference_broker.py envelope`; which authorization governs a start (section 2); the start precondition before
   the key and the listeners, and the loopback rule (section 3); the minted object, the expiry and supersession
   (section 4); the two selection authorities and the per-request model check (section 5); the threat model
   (section 8), less the limit; and `expires_at` as a security validity window (decision 0012 point 7), not a
   spending term.
4. **Section 9:** item 1 stands (the package of 2026-11-13 presents `2027-01-31T23:59:59Z`); item 4 lapses (there is
   no `enforced_by`); items 3 and 5 stand as disclosures.
5. **`BROKER_STOPPING`** was introduced so that a run's close counted its whole usage. Whether the broker keeps it as
   part of its clean stop is the engineering manager's decision inside S-03.6.

The code change is plan leaf S-03.6's. Until it passes, the built `/1` form stays in the code, and the Owner is
shown no envelope manifest (OA-12 act 3 waits on it).

## Amendment 2 (2026-11-14, effective with decision 0023's acceptance the same day): the brokered execution profile

Drafted by the program manager for the product manager (a change to the contract between leaves; decision 0018
point 1), applying the Owner's direction of 2026-11-14 ("Owner direction: reconcile D1 for isolated, native Claude
Code execution", verbatim in `evidence/bootstrap-log.md`, Decisions), which reads in part "Reconcile ... Decisions
0015 and 0021." and "Preserve the existing broker implementation and its qualifications without making them
prerequisites for native execution.". It takes effect when [decision
0023](0023-native-claude-code-execution-profile-native-authentication-and-provider-tunnel.md) is accepted; until
then the text above governs unchanged. The text above, amendment 1 and the Current facts stay as written; where
they and this amendment disagree, this amendment governs.

1. **Scope.** This record governs the broker's start toward a real provider, that is, the brokered execution
   profile. The native profile of decision 0023 starts no broker, so no provider-envelope receipt governs it, and
   its model calls are not admitted by a selection the broker checks: on the native profile the model identifiers
   are approved by the Owner (decision 0023 section 7; OA-31 (c)).
2. **Unchanged:** every section above and amendment 1, for the brokered profile; the recorded authorization of
   2026-11-14 (operation `d1-provider-envelope`, OA-12 act 3) and its receipt, which stand and which the native
   profile does not use.

## Evidence

`evidence/S-03.5-provider-envelope-authorization.md`: the proof clause by clause, the independent review and
re-review, the mutation checks and what is not verified. The code: `integrations/inference/inference_envelope.py`,
`integrations/inference/inference_broker.py`, `integrations/owner/envelope_decisions.py`,
`integrations/owner/delegated_decision.py`, `integrations/owner/selection_recorder.py` and their tests.

## Not verified

Anything live: a real envelope manifest and its authorization by the Owner against a real Gitea, `serve` on the
managed root, a request through `serve` to a non-loopback origin (S-03.3's live step), a real model selection, a
real provider's billing of answers outside 2xx and its enforcement of a limit on a dedicated key, http.client's
socket state after a partial send, Task, Linux and macOS.

## Current facts (2026-11-13)

1. (Planning, 2026-11-13) Section 9 item 2 is settled by [decision 0022](0022-authorization-repository-the-one-ledger-provisioned-for-d1.md) (Accepted, product manager): the first real envelope manifest is carried by the dedicated authorization repository, provisioned for D1 by plan leaf E-05.7 under Owner act OA-30, and never by the S-01.2.2 fixture. The managed recorder admits it alone. Until a second non-fixture repository is admitted, `envelope_decisions` needs no repository predicate. Items 1 and 3 to 5 are carried into OA-12's presentation (`evidence/bootstrap-log.md`, anchor `planning-pass-2026-11-13`). The numbered points are unchanged.
2. (Engineering manager, 2026-11-13) Plan leaf S-03.6 is PASS ([evidence](../evidence/S-03.6-spending-enforcement-retired.md); `ef82b76`, `1144776`, `9acfc66`): the `/2` form of amendment 1 is now in the code (`inference_envelope.py`: exactly `format`, `provider`, `origin`, `expires_at` and `selection`; a block naming `limit`, `amount`, `currency`, `enforced_by` or `cap` is refused `CONFIG_ENVELOPE_INVALID`); the cumulative cap, its per-run ledger, `ENVELOPE_CAP_REACHED` and `ENVELOPE_USAGE_UNKNOWN` are removed, and receipts the ledger wrote are neither read nor changed; `BROKER_STOPPING` is kept as part of the broker's clean stop (amendment 1 point 5, decided by the engineering manager). Amendment 1's "until it passes" statement is satisfied: the Owner may be shown the `/2` manifest (OA-12 act 3). The numbered points are unchanged.
