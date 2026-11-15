## Context

aieh-d1-demo is the D1 demonstration repository: a small standard-library Python package with
unittest tests. This change adds one function, `slugify(text)`, which the D1 attempt implements
and verifies offline in the pinned image. The Owner asked for sensible, explicit behaviour and an
intentionally small demonstration (proposal Q1 and CL1).

## Goals / Non-Goals

**Goals:**

- One public function, `aieh_d1_demo.slugify(text) -> str`, with the behaviour in the spec.
- Tests for every scenario, standard library only, offline.

**Non-Goals:**

- Transliteration of scripts without an ASCII decomposition (Greek, Cyrillic, CJK and the like).
- Options: a custom separator, a maximum length, stop words or a Unicode-preserving mode.
- Any dependency, command-line entry point or packaging change.

## Decisions

1. **NFKD and removal of combining marks, standard library only.** `unicodedata.normalize("NFKD",
   text)` then drop characters for which `unicodedata.combining` is non-zero. Alternatives: a
   transliteration library (rejected: a dependency, not small); NFC only (rejected: keeps accents,
   so "Crème" would lose its "è" as a separator instead of becoming "e").
2. **One separator rule.** After normalization, every maximal run of characters that are not
   ASCII letters or digits becomes one hyphen, and leading and trailing hyphens are removed. This is
   the rule presented with the Owner's choice of the change (OA-25: lower-case, trim, collapse runs
   of non-alphanumerics to one hyphen, no leading or trailing hyphen). Alternatives: deleting
   apostrophes and other punctuation instead of separating (rejected: a second rule to explain;
   "don-t" is the accepted cost); dropping characters without an ASCII form instead of separating
   (rejected for the same reason: "Straße" gives "stra-e", stated in the spec).
3. **ASCII only.** Letters are `a`-`z` after lower-casing and digits are `0`-`9`; other Unicode
   letters and digits are separators. This makes the result form (AC6) exact and easy to test.
4. **Empty result, not an error.** An input with nothing left gives `""`; only a non-`str` argument
   raises (`TypeError`), so callers decide what an empty slug means.
5. **Layout.** The function is exported from the package top level; the module that holds it and
   the test module's name are the implementer's choice. Tests use `unittest` only.

## Method Evaluation

The proposal lists no proposed method.

## Risks / Trade-offs

- [Scripts without an ASCII form give an empty or partial slug] -> stated in the spec and the
  Non-Goals; a transliteration feature would be its own change.
- [Python's Unicode database version can change NFKD results between interpreter versions] -> the
  tests use characters whose decomposition is stable; the suite runs in the pinned image.

## Open Questions

None.
