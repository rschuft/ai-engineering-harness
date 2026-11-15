# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:product-manager

### Original Quote

#### Q1
- source: harness:evidence/bootstrap-log.md#owner-decision-oa-31-2026-11-14
- attributed_to: owner
- claim_type: observation

```text
OA-25: use aieh-d1-demo, a small Python package
with unittest tests. The requested change is
to implement slugify(text) with appropriate tests.
```

### Objective

#### O1
- statement: aieh-d1-demo, a small Python package with unittest tests, implements slugify(text) with appropriate tests.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

None.

### Hypotheses

None.

### Acceptance Criteria

#### AC1
- statement: slugify is importable as aieh_d1_demo.slugify, takes one argument and returns a str; an argument that is not a str (bytes and None included) raises TypeError.
- claim_type: requirement
- attributed_to: agent:product-manager
- source: O1, CL1
- authority: accepted
- acceptance: harness:evidence/bootstrap-log.md#commitment-d1-2026-11-15

#### AC2
- statement: The text is normalized with Unicode NFKD and its combining marks are removed, so accented Latin letters, compatibility forms and ligatures become ASCII letters and digits (for example "Crème Brûlée" gives "creme-brulee", "ﬁle" gives "file", full-width "Ｈｅｌｌｏ" gives "hello"); any character still outside ASCII letters and digits is treated as a separator (AC4), so "Straße" gives "stra-e" and "日本語" gives "".
- claim_type: requirement
- attributed_to: agent:product-manager
- source: O1, CL1
- authority: accepted
- acceptance: harness:evidence/bootstrap-log.md#commitment-d1-2026-11-15

#### AC3
- statement: ASCII letters are lower-cased ("Hello World" gives "hello-world") and ASCII digits are kept ("Version 2.0" gives "version-2-0").
- claim_type: requirement
- attributed_to: agent:product-manager
- source: O1, CL1
- authority: accepted
- acceptance: harness:evidence/bootstrap-log.md#commitment-d1-2026-11-15

#### AC4
- statement: Every maximal run of characters that are not ASCII letters or digits (whitespace of any kind, punctuation, symbols, underscores and hyphens) becomes one hyphen ("a  b\t\nc" gives "a-b-c", "Hello, World!" gives "hello-world", "foo_bar--baz" gives "foo-bar-baz", "Don't stop" gives "don-t-stop").
- claim_type: requirement
- attributed_to: agent:product-manager
- source: O1, CL1
- authority: accepted
- acceptance: harness:evidence/bootstrap-log.md#commitment-d1-2026-11-15

#### AC5
- statement: The result never starts or ends with a hyphen ("  --Hello--  " gives "hello"), and an empty text or one without an ASCII letter or digit after AC2 gives the empty string ("", "   " and "!!!" each give ""), never an error.
- claim_type: requirement
- attributed_to: agent:product-manager
- source: O1, CL1
- authority: accepted
- acceptance: harness:evidence/bootstrap-log.md#commitment-d1-2026-11-15

#### AC6
- statement: Every result is empty or matches ^[a-z0-9]+(-[a-z0-9]+)*$, and slugify of a result returns it unchanged.
- claim_type: requirement
- attributed_to: agent:product-manager
- source: O1, CL1
- authority: accepted
- acceptance: harness:evidence/bootstrap-log.md#commitment-d1-2026-11-15

#### AC7
- statement: The package's unittest tests cover AC1 to AC6, use only the Python standard library and run offline with python -m unittest discover -s tests from the repository root.
- claim_type: requirement
- attributed_to: agent:product-manager
- source: O1, Q1
- authority: accepted
- acceptance: harness:evidence/bootstrap-log.md#commitment-d1-2026-11-15

### Open Clarifications

#### CL1
- question: How should slugify treat normalization, whitespace, punctuation, case, empty input and non-ASCII text?
- claim_type: unknown
- attributed_to: agent:product-manager
- source: Q1
- consequence: Decides AC1 to AC6 and every test case.
- blocks: AC1, AC2, AC3, AC4, AC5, AC6
- status: resolved
- resolution: harness:evidence/bootstrap-log.md#owner-direction-d1-planning-2026-11-15

## Why

The D1 demonstration needs one small, fully specified coding change in the aieh-d1-demo repository that an agent can implement and verify offline. The Owner named it (O1): implement slugify(text) in aieh-d1-demo with appropriate tests; on 2026-11-15 he asked for sensible, explicit behaviour for every input class and an intentionally small demonstration, and delegated the choices (CL1).

## What Changes

- aieh_d1_demo.slugify(text) turns a text into a lower-case, hyphen-separated ASCII slug (AC1 to AC6).
- Accented and compatibility characters are folded to ASCII; anything else outside ASCII letters and digits separates words; an input with nothing left gives "".
- unittest tests cover each behaviour and run offline with the standard library only (AC7).
- Nothing else changes: no options, no length limit, no dependency.

## Capabilities

### New Capabilities
- `slugify`: turning a text into a URL-safe ASCII slug.

### Modified Capabilities

## Impact

The aieh_d1_demo package gains one public function and its tests. No dependency, configuration or other module changes.
