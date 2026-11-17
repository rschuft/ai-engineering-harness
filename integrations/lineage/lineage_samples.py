"""SAMPLE authorities for the lineage traversal's example and tests (plan leaf P-03.2): none remains.

A sample was a read-only stand-in that answered, from committed recorded data, for a kind whose
authority did not exist yet. ``lineage_trace.Authorities`` still accepts a sample only for a kind
whose authority is unavailable, marks every node it answers ``authority_mode: sample`` and lists it
as an uncertainty, so a projection that used one is never ``complete``. No kind has one now:

- the statement sample (``SampleStatementStore``, over the P-01.2 qualification corpus) is retired
  at plan leaf U-02.2: the ``message`` and ``conversation`` kinds are implemented by the Owner
  conversation store's own resolvers (I1 work design, R5);
- the attempt sample (``SampleAttemptRecords``, over a committed file shaped like F-04.2's
  conversation info) is retired at plan leaf E-01.5: the ``attempt`` kind is implemented by
  ``lineage_attempt.AttemptResolver``, which asks the Agent Server, and against the Agent Server
  fixture's cited core states its mode ``fixture`` (I1 integration design, R11).

That is the planned end of the samples, not a regression.
"""


def sample_authorities():
    """{kind: sample resolver} for ``lineage_trace.Authorities``: none remains (the module docstring)."""
    return {}
