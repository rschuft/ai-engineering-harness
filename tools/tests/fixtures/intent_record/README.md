# Intent record fixture (builder-produced)

**This is a test fixture, not a model qualification.** `proposal.md` was written by
hand by the implementing agent of plan leaf P-01.1, following the
`intent-normalization` Skill 1.0.0, to give the checker
(`tools/check_intent_record.py`) a known-good record. It shows that the format can
express the case; it says nothing about how a model applies the Skill. Behavioural
qualification on live model runs is plan leaf P-01.2.

- `request.txt`: a synthetic, confusing request. The requester wants a behaviour (a
  whole-year invoice PDF that downloads without a time-out, for every account),
  prescribes two dubious methods (a 10-minute gateway timeout, a Redis cache in front
  of the query), and leaves "a whole year", "the big accounts" and "fast" ambiguous.
  It contains a curly apostrophe, an em dash, a backtick span and a double space, so
  any normalisation of the quote is detectable. The reference
  `conversation:thread-17/message-4` is illustrative.
- `proposal.md`: its normalized proposal. Both methods are Owner-attributed
  hypotheses (M1, M2 with H1, H2), there are no binding constraints, and the three
  ambiguities are open clarifications.

Files here are kept LF (`.gitattributes`) because the quote is compared byte for byte.
