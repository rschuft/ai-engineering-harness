## Context

Fixture for plan leaf P-02.1, written by the implementing agent. It completes the
OpenSpec change `qual-02-search-freshness` recorded at P-01.2 (proposal and delta
spec unchanged) so that the change is ready to apply under the `intent-driven`
schema, and so that two Backlog.md tasks can point at an exact design revision.
It is test data, not a design anyone accepted.

The accepted objective is O1 with criterion AC1: a product added to the catalogue
appears in search results within 5 minutes of being added. AC2 is still proposed
and blocked by CL3.

## Goals / Non-Goals

**Goals:**

- Meet the requirement "New products are findable within 5 minutes".
- Establish where the delay comes from before choosing a method (H2).

**Non-Goals:**

- AC2's limits on existing results and response time; they wait for CL3.

## Decisions

- **D1: Measure before changing anything.** Record when an added product reaches
  the catalogue store, the search index and the search responses, with the cache
  bypassed and in use (the test of H2). Alternative: change the cache first; rejected
  because H1 predicts that a longer TTL delays new products further.
- **D2: Refresh on add, decided by D1's measurement.** If the cache is the main
  cause, refresh or invalidate the affected cache entries when a product is added
  (M2, tested by H3). Alternative: a shorter TTL; kept as a fallback if D1 shows
  refresh on add is impractical.

## Method Evaluation

- **M1** (raise the TTL to 30 minutes, the Owner's guess): not used. H1 expects a
  longer TTL to keep stale results longer, which works against O1; the Owner
  accepted no method (CL2 resolved).
- **M2** (refresh or invalidate on add): used, subject to D1's result, through H3.

## Risks / Trade-offs

- [Refreshes add search load] -> Measure in D1 and keep the refresh to the affected
  entries; the load limits belong to AC2 and CL3.

## Open Questions

None.
