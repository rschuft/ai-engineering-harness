# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:engineering-builder
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: conversation:thread-17/message-4
- attributed_to: owner
- claim_type: observation

```text
Customers keep complaining that the invoice PDF download times out when they pick a whole year. Just bump the gateway timeout to 10 minutes and put a Redis cache in front of the `invoices` query — that’ll fix it. It has to work for the big accounts too, and it needs to be  fast.
```

### Objective

#### O1
- statement: A customer who asks for a whole year of invoices as one PDF receives the file instead of a time-out, for every account, including the largest.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Raise the gateway timeout to 10 minutes.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

#### M2
- statement: Put a Redis cache in front of the `invoices` query.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H2

### Hypotheses

#### H1
- statement: With a 10-minute gateway timeout, a full-year download completes for every account (M1 achieves O1).
- claim_type: hypothesis
- attributed_to: owner
- source: M1, O1
- authority: proposed
- test: Time a full-year PDF for the account with the most invoices end to end; it is refuted if generation takes longer than 10 minutes or if a browser, client or load balancer gives up first.

#### H2
- statement: The `invoices` query dominates the download time and repeated requests would hit the cache, so caching it removes the time-out (M2 achieves O1).
- claim_type: hypothesis
- attributed_to: owner
- source: M2, O1
- authority: proposed
- test: Profile a full-year download to split query time from PDF rendering time, and measure how often the same account and period are requested again.

### Acceptance Criteria

#### AC1
- statement: Downloading a whole year of invoices as one PDF succeeds without a time-out for every account, including the account with the most invoices.
- claim_type: requirement
- attributed_to: owner
- source: Q1, O1
- authority: proposed

#### AC2
- statement: A whole-year download meets the speed target agreed in CL2.
- claim_type: requirement
- attributed_to: agent:engineering-builder
- source: Q1, O1, CL2
- authority: proposed

### Open Clarifications

#### CL1
- question: Does "a whole year" mean a calendar year, a fiscal year, or any 12-month range the customer picks?
- claim_type: unknown
- attributed_to: agent:engineering-builder
- source: Q1
- consequence: It fixes the largest period AC1 must cover and whether a year's document could be prepared ahead of the request.
- blocks: O1, AC1
- status: open

#### CL2
- question: What does "fast" mean for a whole-year download: a limit on the time to the complete file or to its first byte, at which percentile, and would a prepared file delivered later (a link or an email) be acceptable?
- claim_type: unknown
- attributed_to: agent:engineering-builder
- source: Q1
- consequence: It sets AC2's threshold and decides whether a synchronous download, the premise of M1, can meet the objective at all.
- blocks: AC2
- status: open

#### CL3
- question: Which accounts are "the big accounts": what is the largest number of invoices or the largest file the download must support?
- claim_type: unknown
- attributed_to: agent:engineering-builder
- source: Q1
- consequence: It bounds the load at which AC1 is tested.
- blocks: AC1
- status: open

## Why

Customers who ask for a whole year of invoices as one PDF get a time-out instead of the file (O1). The download must succeed for every account, including the largest, at a speed still to be agreed (CL2).

## What Changes

- A whole-year invoice PDF download completes for every account instead of timing out (O1, AC1).
- Its speed target is set once CL2 is answered (AC2).
- No method is chosen here. The suggested gateway timeout increase (M1) and Redis cache (M2) are hypotheses H1 and H2, to be evaluated in design.md.

## Capabilities

### New Capabilities
- `invoice-export`: downloading a customer's invoices for a chosen period as one document.

### Modified Capabilities

None.

## Impact

The invoice PDF generation and download path. Gateway timeout settings and query caching are affected only if design.md adopts M1 or M2.
