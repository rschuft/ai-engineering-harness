# Owner decisions

Plan group P-04, "Record Owner decisions": Owner decisions are recorded by deterministic, non-model
recorders in one shared Owner decision-record shape. This directory holds that shape and the first
recorder:

- the **Owner decision record** (`owner-decision/v1`, [`owner_decision.py`](owner_decision.py)),
  shared with the Owner authorization recorder of plan leaf P-04.2 (not built here);
- the **acceptance recorder** (plan leaf P-04.1,
  [`acceptance_recorder.py`](acceptance_recorder.py)): it records the Owner's acceptance of an
  Objective item of an intent-driven OpenSpec change and mints the outcome id, in the form of
  [decision 0008](../../decisions/0008-outcome-identity-assignment-form-and-record.md).

Standard library only, plus the shared repository-access module (Dulwich, from the Python tools set;
[decision 0014](../../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md)) and
the lineage objective resolver. Nothing here launches a process, uses the network, reads a
credential or touches the managed data root.

## Files

| Path | What |
|---|---|
| `owner_decision.py` | The shared record: its fields, the kinds, the `accept-objective` subject, `statement_verdict` and `check_record` |
| `acceptance_recorder.py` | `prepare` and `record`, the refusal codes and remedies, the edits of `proposal.md` and `.openspec.yaml`, and the command line |
| `tests/test_owner_decision.py` | The record's shape and every statement verdict (unit) |
| `tests/test_recorder_edits.py` | The recorder's edits, byte for byte, line endings included; every code has a remedy (unit) |
| `tests/test_acceptance_recorder.py` | `prepare` and `record` on throwaway fixture repositories: the resolver round trip, the id kept on re-recording, the shared shape, every refusal; the command line (integration) |
| `tests/owner_fixture.py` | The fixture project repository (two changes from the P-01.2 recording) and the example record; `--record` rewrites it |
| `tests/fixtures/accept-objective.decision.json` | The example decision record (synthetic statement, fixed clock, nonce and ids) |

## The Owner decision record (`owner-decision/v1`)

One JSON object per decision, with exactly these fields in this order:

| Field | Value |
|---|---|
| `format` | `owner-decision/v1` |
| `decisionId` | a random UUID, version 4, canonical lower-case text |
| `kind` | `accept-objective` (P-04.1); `authorize-operation` is reserved for P-04.2, which defines its subject (until then a record of that kind is refused) |
| `subject` | what was decided on; for `accept-objective`: `change`, `item` (`O<n>`), `outcome` (the outcome id), `revision` (the commit the summary was shown at) and `proposal` (the sha256 of the change's `proposal.md` there) |
| `shown` | what the recorder presented before the decision: `summary` (the text shown), `nonce` (32 lower-case hex digits) and `expiresAt` (the challenge's expiry) |
| `statement` | the decision as stated: `text` (verbatim), `attributedTo` (`owner`), `channel` (a lower-case token, such as `main-session`) and `reference` (where the statement is kept) |
| `recordedBy` | who ran the recorder: `owner`, `agent:<id>` or `person:<id>` |
| `recordedAt` | `YYYY-MM-DDTHH:MM:SSZ` (UTC) |

Attributions and references use the intent-record/v1 grammar. The file is JSON with a two-space
indent, the fields in this order, UTF-8 kept, LF. The example is
[`tests/fixtures/accept-objective.decision.json`](tests/fixtures/accept-objective.decision.json).

The record is **clerical**. It says what was shown, what was said, who recorded it and when. It
does not authenticate the Owner: `attributedTo` and `channel` are declared by whoever transcribed
the statement, and the acceptance reference, not the record, is the proof that the Owner accepted
(decision 0008, point 2).

**How a statement is judged** (`statement_verdict`, from the statement alone, in this order):

| Verdict | When |
|---|---|
| missing | no statement, an empty `text`, or no `reference` (absent, empty or `missing:<what>`) |
| authored by a model | `attributedTo` is `agent:<id>` (an agent is a model), or the `reference` is an engineering conversation of the Agent Server (`openhands:`, the lineage `attempt` kind: a model's own transcript) |
| not attributed to the Owner | `attributedTo` is anything but `owner` (`person:<id>`, any other text, or absent) |
| malformed | a field outside the four, a `channel` that is not a lower-case token, or a `reference` outside the intent-record/v1 grammar |

`recordedBy` may be an agent: during bootstrap the Overseer transcribes the Owner's reply (the
P-04.2 bootstrap channel). Recording is clerical; accepting is the Owner's.

## The acceptance recorder (plan leaf P-04.1)

Two steps, as the Owner sees them:

1. **`prepare`** reads the change at the project repository's `HEAD` and prints a challenge
   (`owner-decision-challenge/v1`): the summary to show the Owner (the Objective item, its
   attribution and source, its current authority and outcome, the acceptance criteria that cite
   it, the proposal's sha256), a random nonce and an expiry (60 minutes by default, at most a
   week), bound to that commit and to the proposal's digest. It writes nothing.
2. **`record`** takes the challenge and the Owner's statement and, unless a refusal below
   applies, makes **one commit** on the checked-out branch, in process, through
   `repository_access.Repository.write_commit` (no hook, no process; decision 0014 sections 6
   and 8):
   - the decision record at `openspec/changes/<change>/owner-decisions/<decisionId>.json`;
   - the item set to `authority: accepted` and `acceptance: <the statement's reference>` in
     `proposal.md` (only those lines change; line endings are kept);
   - the outcome id, minted as a random UUID version 4, declared in `.openspec.yaml` as
     `x-outcomes: {<id>: {item: O<n>, acceptance: <reference>}}` (decision 0008, point 4);
   - before the branch moves, `outcome:<id>@<new commit>` must resolve through the lineage
     objective resolver with the declared change, item and acceptance; otherwise nothing visible
     changes (`RESOLUTION_FAILED`).

   The commit message ends with the trailers `AIEH-Decision-Id`, `AIEH-Outcome-Id` and
   `AIEH-Recorder: acceptance-recorder/1`.

**Minting once.** The id is minted only by `record`, only with an acceptance reference, and never
again for the same item (decision 0008, point 2). An item that already has an id is refused
(`OUTCOME_ALREADY_MINTED`); `--amend` records a new Owner acceptance of it (decision 0008, point 5),
keeping the id and rewriting the acceptance in both the item and the declaration, with a new
decision record. An objective accepted by hand without an id is minted once on its first
recording.

**The acceptance reference** must be a message of the Owner's conversation
(`conversation:<thread>/<message>`, the lineage `message` kind) or an accepted decision record
(`decision:<id>`), and never the request itself (an Original Quote's `source`; intent-record/v1
invariant 4).

### Refusals

Each refusal has a stable code and its remedy (`acceptance-recorder: CODE: detail. Remedy: ...`,
exit 2), and changes nothing: the branch, the work tree and the index are as they were.

| Code | Refused when |
|---|---|
| `ACCEPTANCE_MISSING` | the statement is missing, has no text, or names no reference |
| `ACCEPTANCE_MODEL_AUTHORED` | the statement is authored by a model (above) |
| `STATEMENT_NOT_OWNER` | the statement is attributed to anyone but the Owner |
| `STATEMENT_INVALID` | the statement is malformed (above), or its file is not JSON |
| `ACCEPTANCE_REFERENCE_INVALID` | the reference is neither an Owner message nor `decision:<id>`, or is the request itself |
| `ACCEPTANCE_ALREADY_RECORDED` | an amendment names the acceptance the item already has |
| `OUTCOME_ALREADY_MINTED` | the item already has its outcome id (re-minting); use `--amend` |
| `OUTCOME_NOT_MINTED` | `--amend` for an item without an id |
| `RECORDED_BY_INVALID`, `IDENTITY_INVALID` | `--recorded-by` is not an attribution; `--identity` is not `Name <email>` |
| `CHALLENGE_MISSING` | no challenge |
| `CHALLENGE_INVALID` | not `prepare`'s challenge for this project: another shape, an unknown revision, or a summary or digest that is not what `prepare` shows at that revision |
| `CHALLENGE_EXPIRED` | the challenge's expiry has passed |
| `CHALLENGE_CONSUMED` | a decision on the challenge's nonce is already recorded |
| `CHALLENGE_STALE` | the proposal changed after the summary was shown |
| `CHANGE_MISSING`, `ITEM_NOT_OBJECTIVE`, `OBJECT_NAME_INVALID` | no such active change; not an Objective item; an unusable change name (`archive`, a path) |
| `INTENT_RECORD_INVALID` | the proposal is not a valid intent-record/v1 record (every check but the quotes' sources), before or after the edit |
| `OUTCOME_METADATA_INVALID` | `.openspec.yaml`'s `x-outcomes` is not decision 0008's form, declares the item twice, or a committed decision record is malformed |
| `HOOKS_UNSUPPORTED` | the repository has client hooks (decision 0014 section 6) |
| `COMMIT_REFUSED` | the repository module refused the commit: the change's files have local changes, HEAD is not a branch or moved, signing is configured, or the index cannot be rewritten (`details['reason']`) |
| `RESOLUTION_FAILED` | the new commit's outcome does not resolve as declared; nothing was committed |
| `PROJECT_UNAVAILABLE`, `GIT_FAILED` | not a work tree with a commit, or Dulwich is not importable; the repository could not be read |

## Commands

From the repository root, under the tools interpreter (`<tools python>` is what
`python -I -B integrations/paths/tools_install.py --python` prints):

```
<tools python> -I -B integrations/owner/acceptance_recorder.py prepare --project DIR --change NAME --item O1 --out challenge.json
<tools python> -I -B integrations/owner/acceptance_recorder.py record --project DIR --challenge challenge.json \
    --statement statement.json --recorded-by agent:<id> --identity "Name <email>" [--amend]
<tools python> -I -B -m unittest discover -s integrations/owner/tests -v      # task owner:test
<tools python> -I -B integrations/owner/tests/owner_fixture.py [--record]     # the example record
```

`task owner:accept -- prepare ...` and `task owner:accept -- record ...` run the first two.
`statement.json` is `{"text": ..., "attributedTo": "owner", "channel": ..., "reference": ...}`.

## Not yet verified

- Any real acceptance: the recorder has run on throwaway fixture repositories only, with synthetic
  statements. No Owner acceptance has been recorded with it.
- The statement's attribution against its source: the Owner conversation store (U-02.x) does not
  exist, so whether the referenced message is the Owner's is declared, not checked.
- OpenSpec 1.16.0 on a change holding `owner-decisions/` (`openspec validate --strict`, `archive`):
  not run. The decision records move with the change on archive by construction (the whole
  folder moves), and the lineage resolver ignores them.
- Under `core.autocrlf=true` the files are written as their blob bytes (LF), where git's checkout
  would write CRLF; git's and the module's `status` report them clean (tested on a fixture).
  Filter drivers and `working-tree-encoding` on these paths: not tested.
- Task itself (the targets' commands were run directly), Linux and macOS.
