# Changelog: intent-normalization

The version is `metadata.version` in `SKILL.md`. Increase it with every change to
this directory: major for a change to the record format or to what the Skill
classifies differently, minor for new guidance, patch for wording. Each entry names
the record format and OpenSpec schema it produces.

## 1.1.0 (2026-11-07)

- New guidance (plan leaf P-01.2, found by the first live qualification runs): a
  method that the normalizing agent or another agent proposes cites the item it
  serves (`source: O1`, or a hypothesis or clarification), never a quote. Citing a
  quote means the method was taken from it, and `intent-record/v1` invariant 3 then
  attributes it to the quote's speaker; in 3 of 13 runs on 1.0.0 the model cited
  `Q1` for its own method and the checker failed the record (`method-attribution`).
  Added to step 3, the self-check and the grammar's invariant 3. Same record format
  `intent-record/v1` and schema `intent-driven` version 1.

## 1.0.0 (2026-11-06)

- First version (plan leaf P-01.1). Produces `intent-record/v1` in the proposal of
  the OpenSpec schema `intent-driven` version 1.
- Separates original quote, objective, binding constraints, proposed methods,
  hypotheses, acceptance criteria and open clarifications, each with claim type and
  attribution.
- Keeps quotes byte for byte; keeps the requester's methods as hypotheses until an
  acceptance recorded separately from the request; turns consequential ambiguity
  into open clarifications.
- Not yet qualified on model runs: behavioural qualification is plan leaf P-01.2.
