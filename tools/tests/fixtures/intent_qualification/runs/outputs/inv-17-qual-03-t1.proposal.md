# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.1.0

### Original Quote

#### Q1
- source: conversation:qual-03/message-1
- attributed_to: owner
- claim_type: observation

```text
The nightly import keeps dying on the 2 a.m. run with out-of-memory errors. Just add retries — retry it 5 times with a 10 minute wait between attempts. That's all it needs, don't overthink it.
```

### Objective

#### O1
- statement: The nightly import finishes successfully each night instead of ending in failure from out-of-memory errors.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Add retries to the nightly import: retry it 5 times, with a 10 minute wait between attempts.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

#### M2
- statement: Find out what drives peak memory in the 2 a.m. import run, then reduce that peak (for example by processing in smaller batches) or give the run enough memory.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: O1, H2
- authority: proposed
- hypothesis: H2

### Hypotheses

#### H1
- statement: Applying M1 achieves O1, because the out-of-memory failures are transient (for example caused by contention with other jobs at 2 a.m.), so a later attempt within 5 retries 10 minutes apart succeeds.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: From logs and metrics of past failed runs, check whether memory exhaustion depends on concurrent load (it varies between runs, and other processes use memory at 2 a.m.) or on the import's own data volume. Run the import again after a failure under the same conditions and see whether it succeeds.

#### H2
- statement: The out-of-memory failures are deterministic for the current data volume and memory limit, so identical retries (M1) would fail the same way, and applying M2 achieves O1.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: Q1, M2
- authority: proposed
- test: Measure the import's peak memory over several runs and compare it with the available limit. Rerun a failed import in isolation and see whether it fails again at the same point.

### Acceptance Criteria

#### AC1
- statement: Over an observation period of consecutive nights (length to be agreed, see CL3), every scheduled nightly import finishes successfully, and no night ends with the import failed because of out-of-memory errors.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL3
- authority: proposed

#### AC2
- statement: Each nightly import finishes by the time its output is needed (deadline to be agreed, see CL2).
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL2
- authority: proposed

#### AC3
- statement: A night on which the import still fails produces an observable failure (a logged error and an alert or status) instead of failing silently.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed

### Open Clarifications

#### CL1
- question: Are retries (5 attempts, 10 minutes apart) a binding requirement, or is the goal only that the import completes, so that another fix, such as reducing memory use, would also be acceptable?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If retries are binding, M1 becomes a constraint and the design only tunes it. If they are not, the design can choose M2 or combine both, depending on whether the failures turn out to be transient (H1) or deterministic (H2).
- blocks: M1, M2
- status: open

#### CL2
- question: By what time must the nightly import be finished? Five retries 10 minutes apart can push completion past 3 a.m. plus the import's own runtime.
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: The answer decides whether the retry schedule fits at all and sets the deadline in AC2.
- blocks: AC2, M1
- status: open

#### CL3
- question: How many consecutive successful nights show that the problem is fixed? How often does the 2 a.m. run fail today ("keeps dying": every night or intermittently)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: The answer sets the observation period in AC1. Failure every night points toward H2, intermittent failure toward H1.
- blocks: AC1, H1, H2
- status: open

#### CL4
- question: Is it safe to rerun the import after it dies partway through, or could a rerun duplicate or corrupt data already partly imported?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If reruns are not idempotent, any retry-based approach carries a risk of data corruption and needs cleanup or idempotency work. This changes scope and risk.
- blocks: M1, AC1
- status: open

## Why

The nightly import dies on its 2 a.m. run with out-of-memory errors. The objective (O1) is for the import to finish successfully every night. Downstream data depends on that run, so each failure leaves data missing or stale until someone notices and intervenes. The Owner proposed retries (M1). Whether retries fix the problem depends on whether the memory failures are transient (H1) or deterministic (H2). That has not been established yet, so the method stays a hypothesis for the design to evaluate.

## What Changes

- The nightly import finishes successfully each night instead of failing with out-of-memory errors (O1, AC1).
- The import finishes within an agreed deadline (AC2, pending CL2).
- A night on which the import still fails is visibly reported rather than failing silently (AC3).
- Candidate methods for the design to evaluate, not yet commitments:
  - Retries, 5 attempts 10 minutes apart (M1, hypothesis H1).
  - Reducing peak memory or providing enough memory (M2, hypothesis H2).

## Capabilities

### New Capabilities
- `nightly-import/reliable-completion`: successful nightly completion of the import, its completion deadline and how failures are reported.

### Modified Capabilities

None.

## Impact

- Affected: the nightly import job and its scheduler configuration, which sit behind the 2 a.m. run.
- Possibly affected: the memory limits of the host or container that runs the import.
- Affected: monitoring and alerting for the import.
- Affected if reruns are not idempotent (CL4): the downstream data the import writes.