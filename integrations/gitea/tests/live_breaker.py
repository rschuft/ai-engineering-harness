"""The circuit breaker of the live authorization and transport suites (Owner authorization OA-16 Act C).

``test_authorization_live.py`` (``task gitea:authz``) and ``test_transport_live.py`` (``task gitea:transport``)
each hold one ``Breaker`` of their own; this module holds only the shared code (the protection auditor's
negative phase, ``test_protection_audit_live.py``, keeps its own breaker). The first unexpected acceptance of
a run trips the module's breaker: a write that must be refused answering 2xx, a push that must be refused
succeeding (or, for the protection auditor's read-only token, Gitea serving it the receive-pack
advertisement), the protected branch moving or a pull request merged. From then on every write probe of
any role, HTTP or git, calls ``check`` immediately before it is sent and is not sent: ``check`` raises, so
no ``subTest``, ``failfast`` setting or failure report decides whether a later write goes out. The module's
``tearDownModule`` then fails the run (``close_run``) and its report records the probe that tripped the
breaker and every write not sent.

``Probe`` is one write probe of the protection auditor's token in those suites: sent as it stands (each is
made non-mutating if Gitea wrongly accepted it, ``if_accepted`` says how), or, with ``method`` None, not sent
at all and reported ``UNEXERCISED`` (``if_accepted`` then says why and where it is covered).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

REMEDY = ('Remedy: stop; revoke the token of the role that was accepted at once (gitea_roles.py retire <role>, '
          'an Owner-approved act) and report')


class SecurityFailure(AssertionError):
    """An unexpected acceptance (see the module docstring). Made by ``Breaker.fail``, which trips the breaker."""


class BreakerOpen(SecurityFailure):
    """A write probe not sent because the breaker had tripped earlier in the run."""


class Probe(NamedTuple):
    action: str
    method: str | None   # an HTTP method, 'PUSH' (PATH is then the refspec), or None: not sent (UNEXERCISED)
    path: str | None
    body: object = None
    if_accepted: str = ''   # what an acceptance would do; for an unexercised probe, why it is not sent


class Breaker:
    """Tripped by the first security failure of the run; from then on no write probe is sent. RECORD receives
    a report row (the module's results list) for every write withheld."""

    def __init__(self, record):
        self.record_row = record
        self.tripped_by = None   # the first security failure's detail
        self.withheld = []       # the write probes not sent since

    def fail(self, detail) -> SecurityFailure:
        """Trip the breaker (the first detail stays) and return the failure to raise."""
        if self.tripped_by is None:
            self.tripped_by = detail
        return SecurityFailure(f'SECURITY FAILURE: {detail}. {REMEDY}')

    def check(self, action):
        """Immediately before a write probe is sent: raise BreakerOpen (and record ACTION withheld) once tripped."""
        if self.tripped_by is not None:
            self.withhold([action])
            raise BreakerOpen(f'SECURITY FAILURE earlier in this run ({self.tripped_by}): {action} was not sent, '
                              f'nor is any later write. {REMEDY}')

    def withhold(self, actions):
        for action in actions:
            self.withheld.append(action)
            self.record_row({'action': action, 'expected': 'not sent', 'status': 'not sent',
                             'message': 'the circuit breaker tripped earlier; this write was not sent'})

    def record(self) -> dict:
        return {'action': 'circuit breaker', 'tripped_by': self.tripped_by, 'not_sent': list(self.withheld)}

    def close_run(self, results: list, report: str | None):
        """A suite's tearDownModule: write the report (with the breaker's record when it tripped), then fail
        the run when it tripped."""
        tripped = self.tripped_by is not None
        if tripped:
            results.append(self.record())
        if report and results:
            Path(report).write_text(json.dumps(results, indent=1) + '\n', encoding='utf-8')
        if tripped:
            raise AssertionError(f'SECURITY FAILURE in this run: the circuit breaker tripped at {self.tripped_by}; '
                                 f'{len(self.withheld)} later write probe(s) were not sent {self.withheld}. {REMEDY}')


def sequence(breaker: Breaker, probes, send, failure=AssertionError, prefix='') -> list[str]:
    """Send each of PROBES with SEND, in order. A security failure (or the open breaker) stops the sequence at
    once: the probes after it that would be sent are recorded as not sent (PREFIX before each action) and it
    propagates. Any other FAILURE is collected and the sequence goes on; the collected messages are returned."""
    probes = list(probes)
    failures = []
    for n, probe in enumerate(probes):
        try:
            send(probe)
        except SecurityFailure:
            breaker.withhold(prefix + p.action for p in probes[n + 1:] if p.method is not None)
            raise
        except failure as exc:
            failures.append(str(exc))
    return failures
