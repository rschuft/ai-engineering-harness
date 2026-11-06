# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: <agent:name@version or person:id>

<!-- Every item has an id heading and these fields:
     claim_type    observation | requirement | constraint | hypothesis | unknown
     attributed_to owner | agent:<id> | person:<id>  (whose claim it is, not who typed it)
     source        comma-separated item ids (Q1, M1, ...) or references (scheme:ref)
     authority     proposed | accepted; accepted needs `acceptance: <scheme:ref>`,
                   recorded separately from the request.
     A section with no items contains the single line: None. -->

### Original Quote

<!-- The requester's words, byte for byte, in a backtick fence with info string
     `text`, longer than any backtick run inside the quote. -->

#### Q1
- source: <scheme:durable reference, or missing:<what you received>>
- attributed_to: owner
- claim_type: observation

```text
<the requester's words, unchanged>
```

### Objective

<!-- The behaviour or outcome wanted, without a mechanism. -->

#### O1
- statement: <the desired behaviour>
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

<!-- Only constraints with an acceptance recorded separately from the request.
     An Owner's method never appears here without one. -->

None.

### Proposed Methods

<!-- Every "how" that was suggested. The requester's methods stay hypotheses. -->

#### M1
- statement: <the method as suggested>
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

### Hypotheses

#### H1
- statement: <the testable claim, e.g. applying M1 achieves O1>
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: <how to confirm or refute it>

### Acceptance Criteria

#### AC1
- statement: <an observable check that O1 is met>
- claim_type: requirement
- attributed_to: owner
- source: O1
- authority: proposed

### Open Clarifications

<!-- Ambiguities whose readings would change the objective, a criterion, scope,
     risk or the method that fits. -->

#### CL1
- question: <the question to ask>
- claim_type: unknown
- attributed_to: <agent:id>
- source: Q1
- consequence: <what changes depending on the answer>
- blocks: AC1
- status: open

## Why

<!-- 50 to 1000 characters: restate the objective (cite O1) and why it matters. -->

## What Changes

<!-- Observable behaviour that will change, from the objective and the acceptance
     criteria. Never a hypothesis as a commitment. -->

## Capabilities

### New Capabilities
<!-- Each becomes specs/<capability-path>/spec.md (kebab-case path segments). -->
- `<capability-path>`: <what the capability covers>

### Modified Capabilities
<!-- Existing capabilities whose requirements change; use the exact path under
     openspec/specs/. With no capability at all, set `skip_specs: true` in the
     change's .openspec.yaml. -->

## Impact

<!-- Affected code, APIs, dependencies, systems. -->
