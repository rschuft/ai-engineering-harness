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
receives (by call count), never by a clock; it has no listener and no route that reaches a guest, a model or a
credential. Two of its transitions are the fixture's own scenario, marked so in the provenance table: on the message
it records the message's event and goes ``finished`` at once, and **no turn runs** (the cited values, ``finished`` and
the event, stay observations; that this request is what leads to them is the fixture's).

**The call log** (``calls``): each request the core received, ``(method, path, body)``, in order. A request a transport
event drops never reaches the core and leaves no entry. Transport events (a request that never arrives, a response
withheld, a death) and test knobs (answers no cited run gave) are wrappers or subclasses outside this module.

**The read record** (``recording``): while a ``Reads`` recorder is installed, every answer is returned as mappings
(``_Recorded``) that record, by catalog answer and field path, each key the caller reads, present or not, through
exactly these operations: ``m[k]``, ``m.get(k)``, ``k in m``, and the whole-key reads ``iter(m)``, ``reversed(m)``,
``m.keys()``, ``m.items()`` and ``m.values()`` (each key noted; ``dict(m)``, ``{**m}`` and ``json.dumps(m)`` go through
them). ``copy.copy`` and ``copy.deepcopy`` give mappings that go on recording. ``m[k] = v`` and ``del m[k]`` (a test
knob's own edit of an answer) are writes, not reads, and are not recorded. It records **fail closed**: each operation
that reads the whole answer at once or changes it, ``==``, ``!=``, ``repr``, ``str``, ``format`` (an f-string), ``|``
(either side), ``|=``, ``pop``, ``popitem``, ``setdefault``, ``update``, ``clear`` and ``copy()``, is noted as an
**opaque read** of the mapping's path (``<path>*``, how ``opaque:<operation>``) and raises ``OpaqueRead``; the
read-binding test's judgement rejects every opaque read by name. ``dict``'s own storage holds no answer value (each key
is a ``_Key`` and each value a ``_Sealed``), so an unbound ``dict`` method on a key the mapping holds (``dict.get(m,
k)``, ``dict.__getitem__``, ``dict.__contains__``, ``dict.pop``) is noted as an opaque read of that key and raises,
and one that reaches a stored key or value by other means (``dict.keys(m)``, ``dict.items(m)``, ``dict.values(m)``)
gets a ``_Key`` or ``_Sealed`` that raises on use; **not seen**: an unbound ``dict`` method on a key the mapping does
not hold (it answers as for an absent key), and ``len(m)`` or ``bool(m)``. Each read also notes its reader: the
innermost calling function outside this module and the standard library, ``<module>.<function>`` when it is in a
production module of ``integrations/dispatch/``, else ``outside:<module>.<function>`` (a test, or a test knob that
reads the core's answer before returning it). The read-binding test uses the record to bind the provenance table's
Read column, and its "where", to what the dispatch path reads. With no recorder installed the answers are plain dicts.

SEED's answer is derived by running the harness's own ``integrations/dispatch/attempt_run.py`` ``SEED_SCRIPT`` (the
script the production path sends, compared with it exactly) over the request's payload in a scratch directory, with no
visible window (the shared no-window helper); its output's line ends are the guest's (``\\n``). Its 200 is served only
for the script's exit 0: no record observes a 200 with another exit, so any other exit is refused with the label.
Standard library only.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
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

OPAQUE = 'opaque:'
DISPATCH = os.path.normcase(str(REPO / 'integrations' / 'dispatch')) + os.sep
HERE_FILE = os.path.normcase(str(Path(__file__).resolve()))


class OpaqueRead(Exception):
    """An operation that reads a recorded answer whole, or changes it, outside the reads the record names (the
    module docstring): noted as an opaque read, then raised."""


class Reads:
    """What callers read of the answers: {(answer, path): {'present': bool, 'how': [...]}}, and who read each:
    {(answer, path): {reader, ...}} (``readers``)."""

    def __init__(self):
        self.reads: dict[tuple[str, str], dict] = {}
        self.readers: dict[tuple[str, str], set[str]] = {}

    def note(self, answer: str, path: str, present: bool, how: str, by: str | None = None) -> None:
        held = self.reads.setdefault((answer, path), {'present': present, 'how': []})
        held['present'] = held['present'] or present
        if how not in held['how']:
            held['how'].append(how)
        if by is not None:
            self.readers.setdefault((answer, path), set()).add(by)

    def to_json(self) -> list[dict]:
        return [{'answer': a, 'path': p, **v} for (a, p), v in sorted(self.reads.items())]

    def readers_json(self) -> list[dict]:
        return [{'answer': a, 'path': p, 'by': sorted(v)} for (a, p), v in sorted(self.readers.items())]


_FILES: dict[str, tuple[str, str]] = {}
_STDLIB = tuple(os.path.normcase(os.path.abspath(sysconfig.get_path(name))) + os.sep
                for name in ('stdlib', 'platstdlib'))


def _kind(filename: str) -> tuple[str, str]:
    """('dispatch', stem) for a production module of integrations/dispatch (not its tests), ('skip', stem) for this
    module, the standard library or code with no file, else ('outside', stem)."""
    if filename not in _FILES:
        name = os.path.normcase(os.path.abspath(filename))
        kind = 'skip' if name == HERE_FILE or name.startswith(_STDLIB) or filename.startswith('<') else \
            'dispatch' if name.startswith(DISPATCH) and os.sep not in name[len(DISPATCH):] else 'outside'
        _FILES[filename] = (kind, Path(name).stem)
    return _FILES[filename]


def reader() -> str:
    """Who reads: the innermost calling function outside this module and the standard library, as
    ``<module>.<function>`` when it is in a production module of integrations/dispatch, else as
    ``outside:<module>.<function>`` (a test, or a test knob reading the core's answer before it returns it)."""
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        kind, stem = _kind(code.co_filename)
        if kind != 'skip':
            function = code.co_qualname.split('.<locals>')[0]
            return f'{stem}.{function}' if kind == 'dispatch' else f'outside:{stem}.{function}'
        frame = frame.f_back
    return 'outside:unknown'


def _opaque(where, path_tail: str, operation: str):
    """Note an opaque read of WHERE's mapping (PATH_TAIL ``*`` for the whole) and raise OpaqueRead."""
    recorder, answer, prefix = where
    path = prefix + path_tail
    recorder.note(answer, path, True, OPAQUE + operation, reader())
    raise OpaqueRead(f'{answer} {path}: {operation} reads the recorded answer outside the recorded reads')


class _Key:
    """A key as dict's own storage holds it in a recorded mapping: hashed as the key, equal to another ``_Key`` of the
    same key; compared with anything else (an unbound ``dict`` method's lookup) or shown, it is an opaque read."""
    __slots__ = ('key', 'where')

    def __init__(self, key, where):
        self.key, self.where = key, where

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        if type(other) is _Key:
            return self.key == other.key
        _opaque(self.where, str(self.key), 'dict-unbound')

    def __ne__(self, other):
        if type(other) is _Key:
            return self.key != other.key
        _opaque(self.where, str(self.key), 'dict-unbound')

    def __repr__(self):
        _opaque(self.where, str(self.key), 'dict-unbound')

    __str__ = __repr__

    def __format__(self, spec):
        _opaque(self.where, str(self.key), 'dict-unbound')


class _Sealed:
    """A value as dict's own storage holds it in a recorded mapping: every use is an opaque read."""
    __slots__ = ('_at',)

    def __init__(self, where, key):
        object.__setattr__(self, '_at', (where, str(key)))

    def _use(self, *args, **kwargs):
        _opaque(*object.__getattribute__(self, '_at'), 'dict-unbound')

    def __getattr__(self, name):
        _opaque(*object.__getattribute__(self, '_at'), 'dict-unbound')

    __eq__ = __ne__ = __bool__ = __len__ = __iter__ = __getitem__ = __contains__ = __repr__ = __str__ = __format__ \
        = __int__ = __float__ = __index__ = __hash__ = __call__ = _use


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
    """A mapping of an answer that notes each key read (present or not) with its catalog answer, path and reader, and
    fails closed on every other read of it (the module docstring names exactly which). Its values are held apart
    (``_data``); dict's own storage holds only ``_Key`` -> ``_Sealed``, so that ``isinstance(m, dict)``, ``len`` and
    ``bool`` answer as for the answer while no ``dict`` method reaches a value unrecorded."""
    __slots__ = ('_data', '_where')

    @classmethod
    def made(cls, data: dict, where) -> '_Recorded':
        made = cls()
        object.__setattr__(made, '_where', where)
        object.__setattr__(made, '_data', {})
        for key, value in data.items():
            made[key] = value
        return made

    def _note(self, key, how):
        recorder, answer, prefix = self._where
        recorder.note(answer, prefix + str(key), key in self._data, how, reader())

    def _whole(self, how):
        for key in list(self._data):
            self._note(key, how)

    # -- the recorded reads ---------------------------------------------------------------------------------------
    def __getitem__(self, key):
        self._note(key, 'item')
        return self._data[key]

    def get(self, key, default=None):
        self._note(key, 'get')
        return self._data.get(key, default)

    def __contains__(self, key):
        self._note(key, 'in')
        return key in self._data

    def __iter__(self):
        self._whole('iter')
        return iter(self._data)

    def __reversed__(self):
        self._whole('iter')
        return reversed(self._data)

    def keys(self):
        self._whole('keys')
        return self._data.keys()

    def items(self):
        self._whole('items')
        return self._data.items()

    def values(self):
        self._whole('values')
        return self._data.values()

    def __copy__(self):
        return _Recorded.made(dict(self._data), self._where)

    def __deepcopy__(self, memo):
        return _Recorded.made({k: copy.deepcopy(v, memo) for k, v in self._data.items()}, self._where)

    # -- writes (a test knob's edit), not reads -------------------------------------------------------------------
    def __setitem__(self, key, value):
        self._data[key] = value
        dict.__setitem__(self, _Key(key, self._where), _Sealed(self._where, key))

    def __delitem__(self, key):
        del self._data[key]
        dict.__delitem__(self, _Key(key, self._where))

    # -- fail closed: a read of the whole answer, or a change of it, outside the recorded reads ---------------------
    def _opaque(self, operation):
        _opaque(self._where, '*', operation)

    def __eq__(self, other):
        self._opaque('==')

    def __ne__(self, other):
        self._opaque('!=')

    def __repr__(self):
        self._opaque('repr')

    def __str__(self):
        self._opaque('str')

    def __format__(self, spec):
        self._opaque('format')

    def __or__(self, other):
        self._opaque('|')

    def __ror__(self, other):
        self._opaque('|')

    def __ior__(self, other):
        self._opaque('|=')

    def pop(self, *args):
        self._opaque('pop')

    def popitem(self):
        self._opaque('popitem')

    def setdefault(self, *args):
        self._opaque('setdefault')

    def update(self, *args, **kwargs):
        self._opaque('update')

    def clear(self):
        self._opaque('clear')

    def copy(self):
        self._opaque('copy')

    __hash__ = None


def _wrap(value, recorder: Reads, answer: str, prefix: str):
    """VALUE with every mapping inside it recording its reads. A list's elements share the path ``<key>[]``; the
    events page's items are ``message-event`` entries of their own."""
    if isinstance(value, dict):
        data = {}
        for key, child in value.items():
            if isinstance(child, dict):
                child = _wrap(child, recorder, answer, f'{prefix}{key}.')
            elif isinstance(child, list):
                inner = ('message-event', '') if (answer, prefix + key) == ('events', 'body.items') \
                    else (answer, f'{prefix}{key}[].')
                child = [_wrap(item, recorder, *inner) for item in child]
            data[key] = child
        return _Recorded.made(data, (recorder, answer, prefix))
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
        if done.returncode != self.answers['seed']['exit_code']:
            return self.refuse(f'a SEED whose exit is {done.returncode}: no record observes its answer')
        stdout = done.stdout.decode('utf-8', 'replace').replace('\r\n', '\n')
        return self.made('seed', self.answers['seed']['status'], {'stdout': stdout, 'exit_code': done.returncode})
