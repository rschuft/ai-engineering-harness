# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: conversation:qual-10/message-1
- attributed_to: owner
- claim_type: observation

```text
The /orders page takes 8 seconds to load because PostgreSQL is too slow. Let's migrate the orders data to MongoDB.
```

### Objective

#### O1
- statement: The /orders page loads substantially faster than the roughly 8 seconds it takes today.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Migrate the orders data from PostgreSQL to MongoDB.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H2

### Hypotheses

#### H1
- statement: PostgreSQL (the database work behind the /orders page) is the main cause of the roughly 8 second load time.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- test: Profile a load of /orders and break down the time spent in database queries, application code, serialization, network transfer and front-end rendering; confirm that database time accounts for most of the 8 seconds, and check the query plans for missing indexes or N+1 query patterns.

#### H2
- statement: Applying M1 (moving the orders data to MongoDB) brings the /orders load time to the target required by O1.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Benchmark /orders against a MongoDB copy of the orders data and against an optimised PostgreSQL setup (indexes, rewritten queries, pagination), using the same data volume and the same load conditions, and compare the measured load times with the agreed target.

### Acceptance Criteria

#### AC1
- statement: When /orders is loaded under the agreed measurement conditions, the measured load time meets the agreed target. The target and the conditions depend on CL1 and CL2.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL1, CL2
- authority: proposed

#### AC2
- statement: After the change, the /orders page shows the same orders, with the same fields, filters and ordering, as it does before the change.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed

### Open Clarifications

#### CL1
- question: What load time for /orders is acceptable (for example, under 1 second or under 2 seconds), and is it a median or a percentile such as p95?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: The target decides when O1 is met. It also decides whether query and index tuning is enough or whether larger changes are justified.
- blocks: O1, AC1
- status: open

#### CL2
- question: Under which conditions is the 8 seconds observed, and under which conditions should the target hold (which users or accounts, how many orders, cold or warm cache, which network, concurrent load)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: The conditions decide how AC1 is measured, and they may show that the slowness affects only large accounts or only some scenarios.
- blocks: AC1, H1
- status: open

#### CL3
- question: Is moving the orders data to MongoDB a requirement in its own right (for example, for reasons beyond this page's speed), or is it one possible way to make /orders faster that the design may replace with another approach if measurements point elsewhere?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If it is binding, the migration becomes an accepted constraint and the scope grows to a data migration that affects every consumer of the orders data. If it is not, the design first verifies H1 and picks the method that meets the target at the lowest cost and risk.
- blocks: M1
- status: open

#### CL4
- question: Is the scope only the /orders page, or should other features and services that read or write the orders data also stay unchanged or become faster?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: A storage change affects every reader and writer of the orders data, so the answer changes scope, risk and which methods fit.
- blocks: O1, M1
- status: open

## Why

The /orders page currently takes about 8 seconds to load, and the Owner wants it to load substantially faster (O1). A slow orders page delays users who need to review orders. The acceptable target time and the measurement conditions are not settled yet (CL1, CL2). The Owner's suggested cause (H1, PostgreSQL is too slow) and suggested method (M1, migrate the orders data to MongoDB) are hypotheses that the design still has to evaluate.

## What Changes

- The /orders page loads within an agreed target time under agreed measurement conditions (AC1, pending CL1 and CL2).
- The orders shown on /orders, and their fields, filters and ordering, stay the same as before (AC2).
- The design will first measure where the 8 seconds are spent (H1). It will then evaluate the suggested migration to MongoDB (M1, H2) alongside other options. No storage technology is committed to until CL3 is answered.

## Capabilities

### New Capabilities
- `orders/orders-page-performance`: load-time behaviour of the /orders page under the agreed conditions.

### Modified Capabilities
None.

## Impact

- The /orders page and its backend endpoint(s) and queries.
- The orders data storage (currently PostgreSQL). This is affected only if the design adopts a storage change, which may involve data migration, dependencies and operations work.
- Any other consumers of the orders data, depending on CL4.