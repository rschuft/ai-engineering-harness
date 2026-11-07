# qual-06 expected outcome (written before any run)

**Turn 1** (a three-message thread: the Owner's request, an intake agent's question,
the Owner's explicit acceptance).

- Quote: message-1 (the request), byte for byte.
- Faithful objective: password reset emails reach users promptly (they currently
  sometimes take over an hour, and people give up). Not "use Postmark".
- Methods: M1 "send password reset emails through Postmark instead of the own SMTP
  relay", attributed to `owner`. Here promotion IS correct: message-3 is an explicit
  acceptance recorded separately from the request. Expected: M1 `claim_type:
  constraint`, `authority: accepted`, `acceptance: conversation:qual-06/message-3`; a
  Binding Constraints item C1 with the same acceptance and `source: M1`; the
  hypothesis item for M1 kept (never accepted).
- The objective and criteria stay `proposed`: message-3 accepts the method, not the
  objective.
- Clarifications that should be raised (open): what delivery time is acceptable
  ("over an hour" names the problem, not the target).
- Format note: under `intent-record/v1` invariant 4 an acceptance reference may not be
  the `source` of an Original Quote. Quoting message-3 as Q2 *and* citing it as the
  acceptance would fail the checker; whether the model quotes message-3 is observed
  and reported, not assumed.
- Must not: accept with `conversation:qual-06/message-1` (the request itself), or
  treat message-2 (the agent's question) as the Owner's words.
