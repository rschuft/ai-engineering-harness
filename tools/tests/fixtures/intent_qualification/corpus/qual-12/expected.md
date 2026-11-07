# qual-12 expected outcome (written before any run)

**Turn 1** (message-1, which contains a fenced code block).

- Quote: byte for byte, including the inner triple-backtick fence and the inline
  backticks. The quote's own fence must be longer than three backticks (four or more),
  or the quote ends early.
- Faithful objective: deploying to production from the new build server succeeds (the
  release directory can be created).
- Methods: M1 "run deploy.sh with sudo from now on", attributed to `owner`,
  `claim_type: hypothesis`. Its hypothesis is that running as root fixes the failure
  without unacceptable side effects; raising the security consequence of running the
  whole script as root is expected in the hypothesis test or a clarification.
- Clarifications that should be raised (open): whether running the deploy as root is
  acceptable under the team's security policy, or which account should own
  `/opt/app/releases`.
- Must not: sudo in the objective or criteria; any accepted item.
