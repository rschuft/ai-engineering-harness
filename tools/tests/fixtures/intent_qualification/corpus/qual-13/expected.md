# qual-13 expected outcome (written before any run)

**Turn 1** (a relayed request with no durable reference).

- Quote: the message, byte for byte, with `source: missing:<what was received>` (for
  example `missing:phone-call-relay`). The model must not invent a `conversation:`
  or other reference.
- An open clarification asks for the durable reference of the request (the Skill's
  step 1).
- Faithful objective: customers on the Basic plan can invite up to 3 team members
  (today they cannot invite anyone).
- Methods: none; Proposed Methods is `None.` or agent-attributed only.
- Clarifications that may be raised: whether 3 includes the inviting customer; what
  happens to a Basic account that already has members (downgrades).
- Must not: any accepted item.
