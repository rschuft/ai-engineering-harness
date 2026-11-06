# Changelog: intent-normalization

The version is `metadata.version` in `SKILL.md`. Increase it with every change to
this directory: major for a change to the record format or to what the Skill
classifies differently, minor for new guidance, patch for wording. Each entry names
the record format and OpenSpec schema it produces.

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
