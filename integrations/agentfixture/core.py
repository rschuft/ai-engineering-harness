"""The Agent Server fixture's cited core (plan leaf E-01.4.2, slice 5c; the one catalog E-01.7's fixture serves).

``AgentServerCore`` answers the dispatcher's requests in process, by route and by the conversation's state, from the
catalog (``observations.json``) only. Each answer is an entry of the catalog and each field of it has its provenance
class in the README's provenance table (bound to the catalog by a test): a recorded observation, a value echoed from
the request, a value derived by a rule in harness code that the production path itself runs, or the fixture's label.
A field of no class is not served. A request outside the catalog, or one whose answer would need such a field, is
**refused** with the fixture's label (status 501, ``fixture.refused`` naming why). The one source-derived entry, the
event that records the dispatcher's own initial message, is answered here, in process, and named in the label.

What the core holds, per conversation (``conversations``): ``execution_status`` (``idle`` after its create,
``finished`` once its message is received), ``runtime`` (``available`` after the create, ``missing`` after the
runtime stop), ``events`` (the message's event once received) and ``seeded``. Its scenarios advance by the requests it
receives; it has no clock, no listener and no route that reaches a guest, a model or a credential.

**The call log** (``calls``): each request the core received, ``(method, path, body)``, in order. A request a transport
event drops never reaches the core and leaves no entry. Transport events (a request that never arrives, a response
withheld, a death) and test knobs (answers no cited run gave) are wrappers or subclasses outside this module.

**The read record** (``recording``): while a ``Reads`` recorder is installed, every answer is returned as mappings that
record each key the caller reads (``get``, ``[]``, ``in``, iteration), by catalog answer and field path. The
read-binding test uses it to bind the provenance table's Read column to what the dispatch path reads. With no recorder
installed the answers are plain dicts.

SEED's answer is derived by running the harness's own ``integrations/dispatch/attempt_run.py`` ``SEED_SCRIPT`` (the
script the production path sends, compared with it exactly) over the request's payload in a scratch directory, with no
visible window (the shared no-window helper); its output's line ends are the guest's (``\\n``). Standard library only.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CATALOG_PATH = HERE / 'observations.json'
ATTEMPT_RUN = REPO / 'integrations' / 'dispatch' / 'attempt_run.py'
PYTHON = getattr(sys, '_base_executable', None) or sys.executable

CONVERSATIONS = '/api/conversations'
CONVERSATION_ID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
SEED_RE = re.compile(r"printf %s '([0-9a-f]+)' \| python -c '(.*)' '/workspace/([A-Za-z0-9][A-Za-z0-9._-]*)' "
                     r"'([0-9a-f]{64})'", re.S)
SEED_TIMEOUT_MAX_S = 300
REFUSED_STATUS = 501
SOURCE_DERIVED = ('source', 'llm_message', 'llm_message.content')


def load_catalog(path: Path = CATALOG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def field_paths(cell: str) -> list[str]:
    """The field paths a provenance row's Field cell names (one, or several separated by commas)."""
    return [part.strip().strip('`') for part in cell.split(',')]


def _no_window():
    """integrations/platform/no_window.py, the shared no-window helper, loaded by path once per process:
    ``_no_window().no_window_flags()`` is CREATE_NO_WINDOW only where this process has no console."""
    module = sys.modules.get('aieh_no_window')
    if module is None:
        spec = importlib.util.spec_from_file_location(
            'aieh_no_window', REPO / 'integrations' / 'platform' / 'no_window.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['aieh_no_window'] = module
    return module


def _attempt_run():
    module = sys.modules.get('attempt_run')
    if module is None:
        spec = importlib.util.spec_from_file_location('attempt_run', ATTEMPT_RUN)
        module = importlib.util.module_from_spec(spec)
        sys.modules['attempt_run'] = module
        spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# The read record

class Reads:
    """What callers read of the answers: {(answer, path): {'present': bool, 'how': [...]}}."""

    def __init__(self):
        self.reads: dict[tuple[str, str], dict] = {}

    def note(self, answer: str, path: str, present: bool, how: str) -> None:
        held = self.reads.setdefault((answer, path), {'present': present, 'how': []})
        held['present'] = held['present'] or present
        if how not in held['how']:
            held['how'].append(how)

    def to_json(self) -> list[dict]:
        return [{'answer': a, 'path': p, **v} for (a, p), v in sorted(self.reads.items())]


RECORDER: Reads | None = None


@contextlib.contextmanager
def recording(recorder: Reads):
    """Install RECORDER for the duration: every answer made meanwhile records its reads into it."""
    global RECORDER
    before, RECORDER = RECORDER, recorder
    try:
        yield recorder
    finally:
        RECORDER = before


class _Recorded(dict):
    """A mapping of an answer that notes each key read (present or not) with its catalog answer and path."""

    def _note(self, key, how):
        recorder, answer, prefix = self.__dict__['_where']
        recorder.note(answer, prefix + str(key), dict.__contains__(self, key), how)

    def __getitem__(self, key):
        self._note(key, 'item')
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        self._note(key, 'get')
        return dict.get(self, key, default)

    def __contains__(self, key):
        self._note(key, 'in')
        return dict.__contains__(self, key)

    def _whole(self, how):
        for key in dict.keys(self):
            self._note(key, how)

    def __iter__(self):
        self._whole('iter')
        return dict.__iter__(self)

    def keys(self):
        self._whole('keys')
        return dict.keys(self)

    def items(self):
        self._whole('items')
        return dict.items(self)

    def values(self):
        self._whole('values')
        return dict.values(self)

    def __copy__(self):
        made = _Recorded(dict.items(self))
        made.__dict__['_where'] = self.__dict__['_where']
        return made

    def copy(self):
        return self.__copy__()

    def __deepcopy__(self, memo):
        made = _Recorded((k, copy.deepcopy(v, memo)) for k, v in dict.items(self))
        made.__dict__['_where'] = self.__dict__['_where']
        return made


def _wrap(value, recorder: Reads, answer: str, prefix: str):
    """VALUE with every mapping inside it recording its reads. A list's elements share the path ``<key>[]``; the
    events page's items are ``message-event`` entries of their own."""
    if isinstance(value, dict):
        made = _Recorded()
        for key, child in value.items():
            if isinstance(child, dict):
                child = _wrap(child, recorder, answer, f'{prefix}{key}.')
            elif isinstance(child, list):
                inner = ('message-event', '') if (answer, prefix + key) == ('events', 'body.items') \
                    else (answer, f'{prefix}{key}[].')
                child = [_wrap(item, recorder, *inner) for item in child]
            dict.__setitem__(made, key, child)
        made.__dict__['_where'] = (recorder, answer, prefix)
        return made
    return value


# ---------------------------------------------------------------------------
# The core

class AgentServerCore:
    """The dispatcher's face of the Agent Server, answered from the catalog by route and state (the module
    docstring). ``transport(method, path, body, **kwargs)``-callable, as the dispatch path's transport is."""

    def __init__(self, catalog: dict | None = None, *, scratch: Path | None = None):
        self.catalog = load_catalog() if catalog is None else catalog
        self.answers = self.catalog['answers']
        self.served = {(row['answer'], path) for row in self.catalog['provenance'] if row['served']
                       for path in field_paths(row['field'])}
        self.calls: list[tuple[str, str, Any]] = []
        self.conversations: dict[str, dict] = {}
        self._scratch, self._own_scratch = (Path(scratch) if scratch is not None else None), False

    # -- the call log ---------------------------------------------------------------------------------------------
    def received(self, method, path, body) -> None:
        self.calls.append((method, path, copy.deepcopy(body)))

    def __call__(self, method, path, body=None, **kwargs):
        self.received(method, path, body)
        return self.answer(method, path, body, **kwargs)

    @property
    def creates(self):
        return [call for call in self.calls if call[:2] == ('POST', CONVERSATIONS)]

    def messages(self, conversation_id: str | None = None):
        """The message requests received (``POST .../events``), of CONVERSATION_ID or of any."""
        return [call for call in self.calls if call[0] == 'POST' and call[1].endswith('/events')
                and (conversation_id is None or call[1] == f'{CONVERSATIONS}/{conversation_id}/events')]

    def close(self) -> None:
        if self._own_scratch and self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)

    # -- answers ----------------------------------------------------------------------------------------------------
    def label(self, answer: str, **extra) -> dict:
        return {**self.catalog['label'], 'answer': answer, **extra}

    def made(self, answer: str, status: int, body=None, *, has_body: bool = True, **label) -> dict:
        """An answer of the catalog: its status, its served body, the label; recording when a recorder is installed."""
        if has_body and isinstance(body, dict):
            unlisted = sorted(k for k in body if (answer, f'body.{k}') not in self.served)
            assert not unlisted, f'{answer}: body fields not served by the catalog: {unlisted}'
        made = {'status': status, **({'body': body} if has_body else {}), 'fixture': self.label(answer, **label)}
        recorder = RECORDER
        return _wrap(made, recorder, answer, '') if recorder is not None else made

    def refuse(self, reason: str) -> dict:
        """The fixture's refusal: no answer of the catalog covers the request (status 501, the label naming why)."""
        return self.made('refusal', self.answers['refusal']['status'], has_body=False, refused=reason)

    def answer(self, method, path, body=None, **kwargs):
        """The answer to one request, by route and state (no call log: ``__call__`` writes it)."""
        if not isinstance(method, str) or not isinstance(path, str):
            return self.refuse('not a request')
        route, _, query = path.partition('?')
        if (method, route) == ('GET', '/server_info') and not query:
            return self.on_server_info()
        if not route.startswith(CONVERSATIONS):
            return self.refuse(f'{method} {route}: not in the catalog')
        rest = route[len(CONVERSATIONS):]
        if rest == '' and method == 'POST' and not query:
            return self.on_create(body)
        if rest == '/count' and method == 'GET' and not query:
            return self.on_count()
        parts = rest.split('/')
        if len(parts) < 2 or parts[0] != '' or CONVERSATION_ID_RE.fullmatch(parts[1]) is None:
            return self.refuse(f'{method} {route}: not in the catalog')
        cid, tail = parts[1], '/'.join(parts[2:])
        if query and (method, tail) != ('GET', 'events/search'):
            return self.refuse(f'{method} {route}?{query}: no query is in the catalog')
        handlers = {('GET', ''): lambda: self.on_conversation(cid),
                    ('GET', 'runtime'): lambda: self.on_runtime(cid),
                    ('DELETE', 'runtime'): lambda: self.on_stop_runtime(cid),
                    ('GET', 'events/search'): lambda: self.on_events(cid, query),
                    ('POST', 'events'): lambda: self.on_message(cid, body),
                    ('POST', 'bash/execute_bash_command'): lambda: self.on_command(cid, body, **kwargs)}
        handler = handlers.get((method, tail))
        if handler is None or (kwargs and (method, tail) != ('POST', 'bash/execute_bash_command')):
            return self.refuse(f'{method} {route}: not in the catalog')
        return handler()

    def on_server_info(self):
        entry = self.answers['server-info']
        return self.made('server-info', entry['status'], copy.deepcopy(entry['body']))

    def on_create(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('conversation_id'), str) \
                or CONVERSATION_ID_RE.fullmatch(body['conversation_id']) is None:
            return self.refuse('a create without a conversation id: not in the catalog')
        cid = body['conversation_id']
        if cid in self.conversations:
            return self.refuse('a create of a conversation the server holds: not in the catalog')
        entry = self.answers['create-new']
        served = {'id': cid, **copy.deepcopy(entry['clock'])}
        observed = entry['observedRequest']
        others = {k: v for k, v in body.items() if k != 'conversation_id'}
        if others == {k: v for k, v in observed.items() if k != 'conversation_id'}:
            served.update(copy.deepcopy(entry['equalRequest']))         # F-04.2's fixture request, another id
            if body == observed:
                served.update(copy.deepcopy(entry['ownRequest']))      # F-04.2's own request
        self.conversations[cid] = {'execution_status': 'idle', 'events': [], 'runtime': 'available'}
        return self.made('create-new', entry['status'], served)

    def on_count(self):
        held = len(self.conversations)
        entry = self.answers['count']
        if held not in entry['body']:
            return self.refuse(f'a count of {held} conversations: no observation')
        return self.made('count', entry['status'], held)

    def _held(self, cid):
        return self.conversations.get(cid)

    def on_conversation(self, cid):
        held = self._held(cid)
        if held is None:
            return self.made('conversation-absent', self.answers['conversation-absent']['status'], has_body=False)
        entry = self.answers['conversation']
        status = held.get('execution_status')
        if status not in entry['execution_status']:
            return self.refuse(f'a conversation {status!r}: no observation')
        return self.made('conversation', entry['status'], {'id': cid, 'execution_status': status})

    def on_runtime(self, cid):
        held = self._held(cid)
        entry = self.answers['runtime']
        if held is None or held.get('runtime') not in entry['runtime_status']:
            return self.refuse('a runtime read with no observation for its state')
        return self.made('runtime', entry['status'], {'runtime_status': held['runtime'],
                                                      'can_resume': entry['can_resume']})

    def on_stop_runtime(self, cid):
        held = self._held(cid)
        if held is None or held.get('runtime') != 'available':
            return self.refuse('a runtime stop with no observation for its state')
        held['runtime'] = 'missing'
        entry = self.answers['runtime-stop']
        return self.made('runtime-stop', entry['status'], entry['body'])

    def on_events(self, cid, query):
        held = self._held(cid)
        if held is None or query:
            return self.refuse('an event search with no observation (an unknown conversation, or a query)')
        items = copy.deepcopy(held.get('events') or [])
        if any(not isinstance(item, dict) or item.get('kind') != 'MessageEvent' for item in items):
            return self.refuse('an event the catalog does not hold')
        entry = self.answers['events']
        label = {'sourceDerived': [f'message-event.{p}' for p in SOURCE_DERIVED]} if items else {}
        return self.made('events', entry['status'], {'items': items, 'next_page_id': entry['next_page_id']},
                         **label)

    def on_message(self, cid, body):
        held = self._held(cid)
        if held is None or held.get('events'):
            return self.refuse('a message with no observation (an unknown conversation, or a second message)')
        content = body.get('content') if isinstance(body, dict) else None
        if not isinstance(body, dict) or set(body) != {'role', 'content', 'run'} or body['role'] != 'user' \
                or body['run'] is not True or not isinstance(content, list) or not content \
                or not all(isinstance(p, dict) and p.get('type') == 'text' and isinstance(p.get('text'), str)
                           for p in content):
            return self.refuse('a message that is not the dispatcher\'s message tail')
        entry = self.answers['message-event']
        held['events'] = [{'kind': entry['kind'], 'source': entry['source'],
                           'llm_message': {'content': [{'text': part['text']} for part in content]}}]
        held['execution_status'] = 'finished'
        return self.made('message', self.answers['message']['status'], has_body=False)

    # -- SEED: the harness's own script, run over the request's payload ---------------------------------------
    def scratch(self) -> Path:
        if self._scratch is None:
            self._scratch, self._own_scratch = Path(tempfile.mkdtemp(prefix='aieh-agentfixture-')), True
        return self._scratch

    def on_command(self, cid, body, **kwargs):
        held = self._held(cid)
        if held is None or kwargs:
            return self.refuse('a command with no observation (an unknown conversation, or an exchange delivery)')
        if not isinstance(body, dict) or set(body) != {'command', 'cwd', 'timeout'} or body['cwd'] != '/workspace' \
                or type(body['timeout']) is not int or not 0 < body['timeout'] <= SEED_TIMEOUT_MAX_S \
                or not isinstance(body['command'], str):
            return self.refuse('a command that is not the harness\'s SEED command')
        match = SEED_RE.fullmatch(body['command'])
        if match is None or match.group(2) != _attempt_run().SEED_SCRIPT:
            return self.refuse('a command that is not the harness\'s SEED command')
        if held.get('seeded'):
            return self.refuse('a second SEED on the conversation: no observation')
        held['seeded'] = True
        payload, _, repository, digest = match.groups()
        where = self.scratch() / cid
        where.mkdir(parents=True, exist_ok=True)
        done = subprocess.run([PYTHON, '-I', '-c', match.group(2), str(where / repository), digest],
                              input=payload.encode('ascii'), capture_output=True, timeout=body['timeout'],
                              cwd=where, creationflags=_no_window().no_window_flags())
        stdout = done.stdout.decode('utf-8', 'replace').replace('\r\n', '\n')
        return self.made('seed', self.answers['seed']['status'], {'stdout': stdout, 'exit_code': done.returncode})
