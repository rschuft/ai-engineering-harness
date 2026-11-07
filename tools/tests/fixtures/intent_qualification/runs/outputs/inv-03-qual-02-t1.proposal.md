# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: conversation:qual-02/message-1
- attributed_to: owner
- claim_type: observation

```text
Products we add to the catalogue don't show up in search for ages, so customers can't find new stock. Please raise the search cache TTL from 5 minutes to 30 minutes so the results are more complete.
```

### Objective

#### O1
- statement: Products newly added to the catalogue become findable by customers in search soon after they are added, so new stock can be found.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Raise the search cache TTL from 5 minutes to 30 minutes so the search results are more complete.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

#### M2
- statement: Invalidate or refresh the affected search cache entries, or the search index, when a product is added to the catalogue, instead of waiting for the TTL to expire.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed
- hypothesis: H3

### Hypotheses

#### H1
- statement: Applying M1 (a 30-minute instead of 5-minute search cache TTL) shortens the time before newly added products appear in search and so achieves O1. Note: a longer TTL normally keeps cached results longer, which would be expected to delay new products further, so this claim needs testing before it is relied on.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: In a test environment, add a product and measure the time until it appears in search results with TTL 5 minutes and with TTL 30 minutes; the hypothesis holds only if the delay is shorter with 30 minutes.

#### H2
- statement: The search cache is the main cause of the delay between adding a product and it appearing in search, rather than for example index build or catalogue sync delays.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- authority: proposed
- test: Add a product and record when it reaches the catalogue store, when it reaches the search index, and when it first appears in search responses with the cache bypassed and with the cache in use; compare the delays.

#### H3
- statement: Applying M2 makes newly added products appear in search within the target delay and so achieves O1.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2
- authority: proposed
- test: With M2 in place in a test environment, add products and measure the time until each appears in search results against the target agreed in CL1.

### Acceptance Criteria

#### AC1
- statement: When a product is added to the catalogue, a customer search that matches it returns the product within the maximum delay agreed in CL1, measured from the time the addition is saved.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL1
- authority: proposed

#### AC2
- statement: Products already in the catalogue remain findable in search with no loss of results and no unacceptable increase in search response time, within limits agreed in CL3.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL3
- authority: proposed

### Open Clarifications

#### CL1
- question: What is the longest acceptable delay between adding a product to the catalogue and it appearing in search ("for ages" is how long today, and what would be fast enough)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Sets the target in AC1 and decides which methods can meet it; a near-instant target rules out any TTL-based approach.
- blocks: AC1, H3
- status: open

#### CL2
- question: Is raising the search cache TTL to 30 minutes a binding requirement, or a suggestion for making new products appear sooner? A longer TTL usually keeps old results cached longer and may delay new products further; would you accept another method if it meets the goal?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If binding, M1 becomes a constraint even though it may work against O1; if not, the design can choose among M1, M2 or others based on H1 and H3.
- blocks: M1, M2
- status: open

#### CL3
- question: What do you mean by search results being "more complete"? Only that new products appear, or also other missing or stale results? And what limits apply to search load and response time?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Changes the scope of O1 and the limits in AC2, and how much extra load from cache refreshes is acceptable.
- blocks: O1, AC2
- status: open

## Why

Products added to the catalogue take a long time to appear in search, so customers cannot find new stock (O1). This costs sales of new items and makes the catalogue look out of date. The goal is for new products to be findable soon after they are added, without harming search for existing products.

## What Changes

- Newly added catalogue products appear in customer search results within an agreed maximum delay (AC1, target pending CL1).
- Existing products stay findable, and search performance stays within agreed limits (AC2, pending CL3).
- The Owner's suggestion to raise the search cache TTL from 5 to 30 minutes (M1/H1) and an alternative, invalidating the cache when products are added (M2/H3), are hypotheses for the design to evaluate. Neither is committed; whether M1 is binding is pending CL2.

## Capabilities

### New Capabilities
- `catalogue-search/new-product-visibility`: how quickly newly added catalogue products become findable in customer search.

### Modified Capabilities

## Impact

Search caching and/or search indexing for the catalogue, the catalogue product-add flow, and search load and response times. The exact components depend on the design's evaluation of H1, H2 and H3.