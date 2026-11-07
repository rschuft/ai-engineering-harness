# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

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
- statement: The nightly import, including its 2 a.m. run, completes successfully each night instead of failing with out-of-memory errors.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Add retries to the nightly import: retry it up to 5 times with a 10 minute wait between attempts.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

#### M2
- statement: Find out what drives the import's peak memory at the 2 a.m. run and reduce it, or give the run enough memory, so a single attempt completes.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: Q1
- authority: proposed
- hypothesis: H2

### Hypotheses

#### H1
- statement: The out-of-memory failures are transient, for example caused by other jobs competing for memory around 2 a.m., so retrying up to 5 times with 10 minute waits (M1) lets the import complete each night and achieves O1.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Check past failed runs for memory pressure from other processes at the time of failure. Run the import again under the same conditions after a 10 minute wait and see whether it succeeds. If every attempt fails at a similar memory peak, the failure is deterministic and H1 is refuted.

#### H2
- statement: The out-of-memory failures come from the import's own peak memory use exceeding what is available, so reducing that peak or raising the limit (M2) achieves O1.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2
- authority: proposed
- test: Profile the import's memory over a full 2 a.m. run and compare the peak with the available limit and with the input data volume on failing and succeeding nights.

### Acceptance Criteria

#### AC1
- statement: Over an agreed observation period (see CL3), every scheduled nightly import run, including the 2 a.m. run, ends with a completed import recorded in its job status or logs, with no run ending in an unrecovered out-of-memory failure.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL3
- authority: proposed

#### AC2
- statement: After a nightly run completes, the imported data matches the source for that night, with no records missing or duplicated because of an earlier failed or partial attempt.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL4
- authority: proposed

#### AC3
- statement: The nightly import completes before the deadline that its downstream consumers need (see CL2).
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL2
- authority: proposed

### Open Clarifications

#### CL1
- question: Is the retry approach (5 retries, 10 minute wait) binding, or is the goal a reliable nightly import by whatever method the design finds works? If the failures turn out to be deterministic and retries would not help, should the design still use retries?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- consequence: If binding, M1 becomes a constraint and the design is limited to retries. If not, the design can evaluate M1 against other methods such as M2. Retries alone may leave the import failing every night if the out-of-memory cause is not transient.
- blocks: M1, M2
- status: open

#### CL2
- question: By what time must the nightly import finish for whoever depends on it? Five retries with 10 minute waits can delay completion by about an hour or more.
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: This decides whether the delay from retries is acceptable, and so whether M1 fits.
- blocks: AC3, M1
- status: open

#### CL3
- question: Over what period, and with what success rate, should the import count as fixed (for example 14 consecutive nights with no failed run)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: This sets the bar that AC1 checks and how long verification takes.
- blocks: AC1
- status: open

#### CL4
- question: Is the import safe to run again after it dies partway, or can a failed attempt leave partial data that a retry would duplicate or leave inconsistent?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If reruns are not safe, retries risk corrupting data, so M1 would need cleanup or idempotency work added, which changes scope and risk.
- blocks: AC2, M1
- status: open

#### CL5
- question: "Keeps dying on the 2 a.m. run": does it fail every night or only some nights, and do other runs of the import succeed?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Intermittent failures support H1 (retries can help). Failures every night, or only with larger data, point to H2 and make retries ineffective.
- blocks: H1, H2
- status: open

## Why

The nightly import keeps failing on its 2 a.m. run with out-of-memory errors, so the night's data is not imported. O1 asks that the import complete successfully each night. A reliable nightly import matters because whatever depends on that data is otherwise left stale or incomplete. The Owner's suggested fix, retries (M1), is recorded as a hypothesis to be evaluated in the design.

## What Changes

- The nightly import, including the 2 a.m. run, completes successfully each night instead of ending in an out-of-memory failure (O1, AC1).
- A completed run leaves correct data, with nothing missing or duplicated from failed attempts (AC2).
- The import finishes within the time its consumers need (AC3, pending CL2).
- The method is not yet decided. The design will evaluate the Owner's retry proposal (M1, H1) and a memory-focused alternative (M2, H2), pending CL1.

## Capabilities

### New Capabilities
- `nightly-import-reliability`: successful completion and data correctness of the scheduled nightly import.

### Modified Capabilities
None identified yet. If the nightly import already has a spec under openspec/specs/, it should be listed here instead.

## Impact

- The nightly import job and its schedule or runner configuration.
- Systems and reports that consume the imported data, and their timing (CL2).
- Possibly the import's memory use or its host's resources, depending on the design (M2).