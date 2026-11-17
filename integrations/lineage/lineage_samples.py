"""SAMPLE authorities for the lineage traversal's example and tests (plan leaf P-03.2).

One kind has no local authority yet: execution attempts (``attempt``; the OpenHands Agent
Server, E-01.x). The real ``Registry`` answers ``authority-unavailable`` for it, and that is
the explicit uncertainty P-03 asks for. To show the chain reaching its attempts, one
read-only stand-in answers from committed, recorded data:

- ``SampleAttemptRecords``: a small JSON file of conversation records shaped like the
  Agent Server's conversation info as F-04.2 recorded it, keyed by the conversation id.

It is never registered by the default registry or the command line. ``Authorities``
accepts a sample only for a kind whose authority is unavailable, and every node it answers
is marked ``authority_mode: sample`` and listed as an uncertainty, so a projection that
uses it is never ``complete``.

The statement sample (``SampleStatementStore``, over the P-01.2 qualification corpus) is
retired: since plan leaf U-02.2 the ``message`` and ``conversation`` kinds are implemented
by the Owner conversation store's own resolver (``lineage_resolve.MessageResolver`` and
``ConversationResolver``), so ``Authorities`` no longer admits a sample for them. That is
the planned end of the sample (I1 work design, R5), not a regression. The attempt sample
ends the same way at E-01.5.
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name, path):
    import importlib.util
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


L = _load('lineage', HERE / 'lineage.py')

ATTEMPTS = HERE / 'tests' / 'fixtures' / 'sample-attempts.json'
ATTEMPTS_FORMAT = 'lineage-sample-attempts/v1'
# The conversation-info fields F-04.2 recorded (evidence/F-04.2-conversation-lifecycle.md,
# section 4.2) that a sample record may carry. execution_status is left out on purpose:
# the traversal carries identity and provenance, not another product's state.
ATTEMPT_FIELDS = frozenset({'id', 'title', 'tags', 'created_at', 'workspace'})


class SampleAttemptRecords:
    """SAMPLE stand-in for the OpenHands Agent Server's conversation records."""
    authority = 'SAMPLE attempt records (shaped like F-04.2 conversation info), standing in for the OpenHands Agent Server'

    def __init__(self, path=ATTEMPTS):
        self.path = Path(path)

    def _records(self):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('format') != ATTEMPTS_FORMAT or data.get('sample') is not True:
            raise ValueError(f'not a {ATTEMPTS_FORMAT} sample file')
        records = {}
        for record in data.get('records', []):
            if not isinstance(record, dict) or not set(record) <= ATTEMPT_FIELDS or 'id' not in record:
                raise ValueError(f'a sample record may carry only {sorted(ATTEMPT_FIELDS)}')
            records[record['id']] = record
        return records

    def resolve(self, reference):
        return self._ask(reference, 'reference')

    def current(self, reference):
        return self._ask(reference, 'current')

    def _ask(self, reference, query):
        def say(outcome, code=None, detail='', **extra):
            return L.answer(reference, outcome, self.authority, code, detail, query=query, **extra)

        try:
            records = self._records()
        except (OSError, ValueError) as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'SAMPLE_RECORDS_INVALID', str(exc))
        record = records.get(reference.conversation)
        if record is None:
            return say(L.MISSING, 'ATTEMPT_MISSING', f'no sample attempt record for conversation {reference.conversation}')
        if query == 'reference' and reference.event is not None:
            # F-04.2 observed no persisted event for a conversation without a message.
            return say(L.REVISION_MISMATCH, 'ATTEMPT_EVENT_MISSING',
                       f'the sample record has no event {reference.event!r}')
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=False).encode('utf-8')).hexdigest()
        return say(L.RESOLVED, detail=f'sample conversation {record["id"]}', observed_digest=digest)


def sample_authorities(attempts=ATTEMPTS):
    """{kind: sample resolver} for ``lineage_trace.Authorities``: the attempt sample only."""
    return {'attempt': SampleAttemptRecords(attempts)}
