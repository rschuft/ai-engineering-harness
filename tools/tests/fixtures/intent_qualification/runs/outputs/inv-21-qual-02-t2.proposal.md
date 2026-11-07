# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.1.0

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
- statement: A product added to the catalogue appears in search results within 5 minutes of being added, so customers can find new stock.
- claim_type: requirement
- attributed_to: owner
- source: Q1, conversation:qual-02/message-2
- authority: accepted
- acceptance: conversation:qual-02/message-2

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
- statement: Applying M1 (a 30-minute instead of 5-minute search cache TTL) makes newly added products appear in search within 5 minutes and so achieves O1. Note: a longer TTL normally keeps cached results longer, which would be expected to delay new products further, possibly up to 30 minutes, so this claim needs testing before it is relied on.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: In a test environment, add a product and measure the time until it appears in search results with TTL 5 minutes and with TTL 30 minutes; the hypothesis holds only if the delay with 30 minutes is within 5 minutes for every added product.

#### H2
- statement: The search cache is the main cause of the delay between adding a product and it appearing in search, rather than for example index build or catalogue sync delays.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- authority: proposed
- test: Add a product and record when it reaches the catalogue store, when it reaches the search index, and when it first appears in search responses with the cache bypassed and with the cache in use; compare the delays.

#### H3
- statement: Applying M2 makes newly added products appear in search within 5 minutes of being added and so achieves O1.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2
- authority: proposed
- test: With M2 in place in a test environment, add products and measure the time until each appears in search results against the 5-minute limit in AC1.

### Acceptance Criteria

#### AC1
- statement: A product added to the catalogue appears in search results within 5 minutes of being added.
- claim_type: requirement
- attributed_to: owner
- source: O1, conversation:qual-02/message-2
- authority: accepted
- acceptance: conversation:qual-02/message-2

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
- status: resolved
- resolution: conversation:qual-02/message-2

#### CL2
- question: Is raising the search cache TTL to 30 minutes a binding requirement, or a suggestion for making new products appear sooner? A longer TTL usually keeps old results cached longer and may delay new products further; would you accept another method if it meets the goal?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If binding, M1 becomes a constraint even though it may work against O1; if not, the design can choose among M1, M2 or others based on H1 and H3.
- blocks: M1, M2
- status: resolved
- resolution: conversation:qual-02/message-2

#### CL3
- question: Beyond the accepted criterion (AC1), must products already in the catalogue stay findable and must search response time and load stay within limits, and if so which limits? Does "more complete" in your first message mean anything beyond new products appearing?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, AC1
- consequence: Decides whether AC2 is a requirement at all and what its limits are, and how much extra load from cache refreshes or re-indexing the design may add.
- blocks: AC2
- status: open

## Why

Products added to the catalogue take a long time to appear in search, so customers cannot find new stock. The Owner has accepted the objective (O1): a product added to the catalogue appears in search results within 5 minutes of being added. Meeting it lets customers find and buy new items as soon as they are listed and keeps the catalogue from looking out of date.

## What Changes

- A product added to the catalogue appears in search results within 5 minutes of being added (AC1, accepted by the Owner).
- Existing products stay findable and search performance stays within agreed limits (AC2, proposed, pending CL3).
- The Owner's earlier suggestion to raise the search cache TTL from 5 to 30 minutes (M1/H1) and an alternative, invalidating or refreshing the cache or index when products are added (M2/H3), remain hypotheses for the design to evaluate. The Owner has stated that no method is accepted and that the design should decide (CL2 resolved).

## Capabilities

### New Capabilities
- `catalogue-search/new-product-visibility`: how quickly newly added catalogue products become findable in customer search.

### Modified Capabilities

## Impact

Search caching and/or search indexing for the catalogue, the catalogue product-add flow, and search load and response times. The exact components depend on the design's evaluation of H1, H2 and H3.