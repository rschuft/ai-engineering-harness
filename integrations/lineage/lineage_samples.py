"""SAMPLE authorities for the lineage traversal's example and tests (plan leaf P-03.2).

Two kinds have no local authority yet: the Owner's statements (``conversation`` and
``message``; the assistant-ui conversation store, U-02.x) and execution attempts
(``attempt``; the OpenHands Agent Server, E-01.x). The real ``Registry`` answers
``authority-unavailable`` for them, and that is the explicit uncertainty P-03 asks for.
To show the whole chain resolving, these two read-only stand-ins answer from committed,
recorded data:

- ``SampleStatementStore``: the P-01.2 qualification corpus
  (``tools/tests/fixtures/intent_qualification/corpus/<thread>/item.json`` and its
  message files, kept LF so their bytes are exact). Messages are byte-exact, so digests
  and span anchors verify.
- ``SampleAttemptRecords``: a small JSON file of conversation records shaped like the
  Agent Server's conversation info as F-04.2 recorded it, keyed by the conversation id.

They are never registered by the default registry or the command line. ``Authorities``
accepts them only for kinds whose authority is unavailable, and every node they answer
is marked ``authority_mode: sample`` and listed as an uncertainty, so a projection that
uses them is never ``complete``.
"""
import hashlib
import json
import re
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

CORPUS = REPO / 'tools' / 'tests' / 'fixtures' / 'intent_qualification' / 'corpus'
ATTEMPTS = HERE / 'tests' / 'fixtures' / 'sample-attempts.json'
ATTEMPTS_FORMAT = 'lineage-sample-attempts/v1'
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
# The conversation-info fields F-04.2 recorded (evidence/F-04.2-conversation-lifecycle.md,
# section 4.2) that a sample record may carry. execution_status is left out on purpose:
# the traversal carries identity and provenance, not another product's state.
ATTEMPT_FIELDS = frozenset({'id', 'title', 'tags', 'created_at', 'workspace'})


class SampleStatementStore:
    """SAMPLE stand-in for the Owner conversation store, over the P-01.2 corpus."""
    authority = 'SAMPLE statement store (P-01.2 corpus), standing in for the Owner conversation store'

    def __init__(self, corpus=CORPUS):
        self.corpus = Path(corpus)

    def _messages(self, thread):
        """{message id: file} of THREAD, or None when the corpus has no such thread."""
        if not _NAME.match(thread):
            return None
        item = self.corpus / thread / 'item.json'
        if not item.is_file():
            return None
        data = json.loads(item.read_text(encoding='utf-8'))
        out = {}
        for turn in data.get('turns', []):
            for message in turn.get('messages', []):
                ref = message.get('ref')
                prefix = f'conversation:{L.encode_segment(thread)}/'
                if isinstance(ref, str) and ref.startswith(prefix) and _NAME.match(message.get('file', '')):
                    out[L.decode_segment(ref[len(prefix):])] = self.corpus / thread / message['file']
        return out

    def content(self, reference):
        """The message's bytes exactly as stored, or None."""
        if not isinstance(reference, L.MessageRef):
            return None
        messages = self._messages(reference.thread) or {}
        path = messages.get(reference.message)
        return path.read_bytes() if path is not None and path.is_file() else None

    def resolve(self, reference):
        return self._ask(reference, 'reference')

    def current(self, reference):
        # The corpus is immutable: its current revision is the one it has, so current
        # applies the same check (with the same anchors) as resolve.
        return self._ask(reference, 'current')

    def _ask(self, reference, query):
        checked = reference

        def say(outcome, code=None, detail='', **extra):
            return L.answer(reference, outcome, self.authority, code, detail, query=query, **extra)

        try:
            messages = self._messages(checked.thread)
        except (OSError, ValueError, L.MalformedReference) as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'SAMPLE_CORPUS_INVALID', str(exc))
        if messages is None:
            return say(L.MISSING, 'CONVERSATION_MISSING', f'the sample corpus has no thread {checked.thread!r}')
        if isinstance(checked, L.ConversationRef):
            if checked.through_message is not None and checked.through_message not in messages:
                return say(L.REVISION_MISMATCH, 'CONVERSATION_MESSAGE_MISSING',
                           f'the thread has no message {checked.through_message!r}')
            return say(L.RESOLVED, detail=f'thread {checked.thread} ({len(messages)} messages)')
        path = messages.get(checked.message)
        if path is None:
            return say(L.MISSING, 'MESSAGE_MISSING',
                       f'the sample corpus thread {checked.thread!r} has no message {checked.message!r}')
        if not path.is_file():
            return say(L.AUTHORITY_UNAVAILABLE, 'SAMPLE_CORPUS_INVALID', f'{path.name} is listed but absent')
        result = L.check_message_content(checked, path.read_bytes(), self.authority)
        return say(result.outcome, result.code, result.detail, observed_digest=result.observed_digest)


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


def sample_authorities(corpus=CORPUS, attempts=ATTEMPTS):
    """{kind: sample resolver} for ``lineage_trace.Authorities``."""
    statements = SampleStatementStore(corpus)
    return {'message': statements, 'conversation': statements, 'attempt': SampleAttemptRecords(attempts)}
