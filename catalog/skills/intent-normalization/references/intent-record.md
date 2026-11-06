# Intent record format `intent-record/v1`

The intent record is the `## Intent Record` section of a proposal made with the
OpenSpec schema `intent-driven`. It is Markdown that people read and a small,
strict grammar that a checker can verify without a model.

## Proposal layout

The proposal has these level-2 headings: `## Intent Record`, `## Why`,
`## What Changes`, `## Capabilities`, `## Impact`. OpenSpec itself reads `## Why`
(50 to 1000 characters) and `## What Changes`; avoid using either name for any other
heading in the file, because OpenSpec finds them at any level.

## Inside `## Intent Record`

1. Header fields, one per line, before the first `###` heading:

   | Field | Required | Value |
   |---|---|---|
   | `record_format` | yes | `intent-record/v1` |
   | `normalized_by` | yes | `agent:<id>` or `person:<id>`: who wrote the record |
   | `skill` | no | `<skill name>@<x.y.z>`, e.g. `intent-normalization@1.0.0` |

2. Seven `###` sections, each exactly once: `Original Quote`, `Objective`,
   `Binding Constraints`, `Proposed Methods`, `Hypotheses`, `Acceptance Criteria`,
   `Open Clarifications`. No other `###` heading.
3. Each item is a `####` heading holding only its id, followed by field lines
   `- key: value` (one line each, value not empty). Ids are the section's prefix and
   a number from 1: `Q`, `O`, `C`, `M`, `H`, `AC`, `CL`. Ids are unique in the record.
4. A section without items contains the single line `None.`. Original Quote,
   Objective and Acceptance Criteria need at least one item.
5. Blank lines and HTML comments (`<!-- ... -->`) are ignored. Any other line is an
   error.

## Values

| Kind | Form |
|---|---|
| attribution | `owner`, `agent:<id>` or `person:<id>` (`<id>`: letters, digits, `. _ @ / + -`) |
| reference | `scheme:rest`: a lowercase scheme, a colon, then no spaces, commas or `=` (e.g. `conversation:thread-42/message-8`, `decision:0002`, `gitea:repo/pulls/7`). `missing:<what>` records an absent source. |
| item list | comma-separated item ids and references, e.g. `Q1, O1` |
| claim type | `observation`, `requirement`, `constraint`, `hypothesis`, `unknown` |
| authority | `proposed` or `accepted` |

The claim types are the blueprint's minimal semantic record (observation,
hypothesis, constraint, requirement) plus `unknown` for an open question. An accepted
decision is not an item here: it is cited as an `acceptance` reference.

## Fields per section

| Section | Required fields | Optional | claim_type | authority |
|---|---|---|---|---|
| Original Quote | `source` (reference), `attributed_to`, `claim_type`, then the quote block | | `observation` | (none) |
| Objective | `statement`, `claim_type`, `attributed_to`, `source`, `authority` | `acceptance` | `requirement` | proposed, accepted |
| Binding Constraints | `statement`, `claim_type`, `attributed_to`, `source`, `authority`, `acceptance` | | `constraint` | accepted |
| Proposed Methods | `statement`, `claim_type`, `attributed_to`, `source`, `authority` | `hypothesis` (an H id), `acceptance` | `hypothesis`, `constraint` | proposed, accepted |
| Hypotheses | `statement`, `claim_type`, `attributed_to`, `source`, `authority` | `test` | `hypothesis` | proposed |
| Acceptance Criteria | `statement`, `claim_type`, `attributed_to`, `source`, `authority` | `acceptance` | `requirement` | proposed, accepted |
| Open Clarifications | `question`, `claim_type`, `attributed_to`, `source`, `consequence`, `status` | `blocks` (O/C/M/H/AC ids), `resolution` (reference) | `unknown` | (none) |

`status` is `open` or `resolved`; `resolved` needs `resolution`.

## The quote block

After the Original Quote item's fields: an opening line of three or more backticks
followed directly by `text`, the quote, and a closing line of at least as many
backticks. The quote is every byte between the end of the opening line and the
start of the closing line, without the final line break. It must be a byte-identical
span of the source, and the fence must be longer than any run of backticks in the
quote, so that neither CommonMark nor OpenSpec ends the block early.

## Invariants

1. Each quote is a byte-identical span of the text its `source` names.
2. A Proposed Method without `acceptance` has `claim_type: hypothesis`, and a method
   that is a hypothesis names an existing H item in `hypothesis`. In particular a
   method attributed to `owner` stays a hypothesis until accepted.
3. A method whose `source` cites a quote is attributed to that quote's speaker.
4. An item that is `accepted`, or of claim type `constraint`, has an `acceptance`
   reference; an item with an `acceptance` is `accepted`. The acceptance is never the
   `source` of an Original Quote: the request cannot accept itself.
5. Every id cited in `source`, `hypothesis` or `blocks` exists in the record.

The harness checks these with `tools/check_intent_record.py` (in the
ai-engineering-harness repository). The checker verifies form and these
invariants; whether the objective is a faithful reading of the request is a matter
for review and for the Skill's behavioural qualification.

## Promotion

To make a method binding, record the acceptance where it belongs (for example the
Owner's explicit reply, or an accepted decision record), then in the proposal set the
method to `claim_type: constraint`, `authority: accepted`, `acceptance: <that
reference>`, and add a Binding Constraints item with the same acceptance and
`source: M<n>`. Keep the hypothesis item: it records what was believed and tested.
