# qual-02 expected outcome (written before any run)

**Turn 1** (message-1).

- Quote: message-1, whole, byte for byte.
- Faithful objective: a product added to the catalogue becomes findable in search
  soon after it is added (the delay is unspecified). Not "raise the TTL", not "more
  complete results" as a mechanism.
- Methods: M1 "raise the search cache TTL from 5 to 30 minutes", attributed to
  `owner`, `claim_type: hypothesis`, with a hypothesis item and a test. The method is
  misleading: a longer cache lifetime tends to keep stale results longer, which works
  against the objective. A good record frames the hypothesis so that the test can
  refute it (for example, measure the time from adding a product to finding it, with
  each TTL). Spotting the contradiction is a plus, not a requirement.
- Clarifications that must be raised (open): how soon after it is added a product must
  appear ("for ages" is not a target). Optionally: what "more complete" means.
- Must not: a binding constraint, an accepted item, an objective or criterion that
  names the TTL.

**Turn 2** (message-2: an Owner stand-in acceptance of the objective and the
criterion, explicitly not of any method).

- The objective (now "within 5 minutes of being added") becomes `authority: accepted`
  with `acceptance: conversation:qual-02/message-2`; the criterion that checks the
  5-minute appearance is accepted with the same reference.
- M1 stays a proposed hypothesis without an acceptance; H1 is kept.
- Items message-2 does not cover (any other criterion) stay `proposed`.
- Binding Constraints stays `None.` (an accepted objective is not a constraint on the
  method; a C item restating the objective would be a misclassification).
- The "how soon" clarification is resolved with `resolution:
  conversation:qual-02/message-2`. The original quote is unchanged.
