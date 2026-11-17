"""Objective acceptance from the Owner UI: the acceptance recorder's challenge shown as a card, and the Owner's
acceptance recorded on his own message, bound to his authenticated session (plan leaf P-04.4; decision 0025 points 8
and 9; the I1 work design R6, slice 10).

No model is called anywhere on this path. Two requests, each naming server-held ids only (the thread, a message, and
the challenge's nonce or the card the shell is writing), each answered from the Owner conversation store and the
project repository, never from text the request carries:

1. **The challenge** (``prepare``): the Owner's message ``Review acceptance: <item> of <change>`` (exactly that one
   line; ``REVIEW_LAYOUT``) names an Objective item of an intent change in the project repository. The acceptance
   recorder's ``prepare`` (P-04.1) runs in process and its challenge (the summary, a nonce and an expiry, bound to the
   revision and the proposal's sha256) is held **in this process's memory** by its nonce, with the thread, the
   request message, the card (the assistant message the shell writes it into) and the session it was issued to. It
   writes nothing. A challenge is lost when the Integration process restarts: an acceptance on it is then
   ``ACCEPTANCE_CHALLENGE_UNKNOWN`` (fail-closed), and the Owner reviews again.
2. **The acceptance** (``record``): the Owner's message ``Accept <item> of <change>``, optionally followed by a line
   break and his own words (``ACCEPT_LAYOUT``), after the card in the same thread and session. The statement is built
   from the store: ``text`` the stored bytes (decoded), ``attributedTo: owner``, ``channel: owner-ui``, ``reference:
   conversation:<thread>/<message>#sha256:<digest>`` (``lineage.message_reference``), ``recordedBy: owner``. The
   acceptance recorder records it in process with the session-binding verifier (``SessionBinding``), which re-reads
   the message from the store: a user message, author ``owner``, made under the requesting session, with that digest
   and text, and the challenge issued to that session.

In order, each refusal with a stable code, and **nothing changed** (the project repository, the conversation store,
the integration store):

- the project configuration (``components.owner_host``, capture.py's ``project_config``: ``CAPTURE_PROJECT_UNCONFIGURED``,
  ``CAPTURE_CONFIG_INVALID``); the body (``REQUEST_INVALID``);
- the message: an assistant message is ``ACCEPTANCE_MODEL_AUTHORED`` (display state the shell wrote, or a model's or an
  agent's text: never the Owner's statement), a user message not authored by ``owner`` ``STATEMENT_NOT_OWNER``; the
  request of a challenge must be an Owner message (``ACCEPTANCE_NOT_A_STATEMENT``); the sha256 of its stored bytes must
  be the request's (``ACCEPTANCE_MESSAGE_MISMATCH``); it must be made under the requesting session
  (``ACCEPTANCE_SESSION_MISMATCH``: an acceptance not made in the Owner's session); its layout
  (``ACCEPTANCE_LAYOUT_INVALID``);
- the principal and the commit identity (capture.py's ``session_principal`` and ``capture_identities``:
  ``CAPTURE_SESSION_UNRECOGNIZED``, ``COMMIT_IDENTITY_UNAVAILABLE``, ``_INVALID``, ``_PLACEHOLDER``; decision 0028: the
  commit's author and committer are the session principal's configured identity, passed to the recorder, which
  commits with it as both); the project repository (``CAPTURE_PROJECT_UNAVAILABLE``, ``CAPTURE_PROJECT_IS_HARNESS``);
- the challenge, **before the receipt is reserved**: unknown (``ACCEPTANCE_CHALLENGE_UNKNOWN``), issued to another
  session (``ACCEPTANCE_SESSION_MISMATCH``), of another thread or item (``ACCEPTANCE_CHALLENGE_MISMATCH``), the
  acceptance not after its card (``ACCEPTANCE_NOT_AFTER_CARD``: the card must be the stored assistant reply to the
  request, of the same session, and an ancestor of the acceptance), already used (``CHALLENGE_CONSUMED``: a decision
  record of the change at HEAD carries its nonce, read as the recorder reads them), expired
  (``CHALLENGE_EXPIRED``), or the proposal changed at HEAD since it was prepared (``CHALLENGE_STALE``); the change's
  x-outcomes must read (``OUTCOME_METADATA_INVALID``). Whether this is a re-acceptance (the recorder's amend, which
  keeps the outcome id) is read from x-outcomes at HEAD: the item already has its id.

Then the write-ahead receipt ``owner-ui/objective-acceptance/v1/<thread>/<message>`` is reserved in the integration
store, and the recorder makes its one commit (the decision record, the item's acceptance and, the first time, the
minted outcome id; resolved through the lineage objective resolver before the branch moves). The receipt goes to
``dispatched`` and ``confirmed`` with the commit, the outcome and the decision. **The race window**: the recorder's own
checks are the backstop for a change between those checks and its commit (another process moving the project
repository); if it refuses then, the receipt stays ``reserved`` (the integration store's receipts are never deleted)
and nothing is written to the project repository. The same message may be recorded again once the cause is repaired:
a receipt left ``reserved`` or ``dispatched`` is settled **by reading the repository first** (every local branch and
every parent: a commit whose message carries the recorder's line ``Statement: <reference> (owner-ui).``), and only
when none is found is the recorder asked again.

Idempotent by message id: a confirmed receipt answers its commit and writes nothing, only for the request it was made
for (its project, change, item, message digest and nonce: ``ACCEPTANCE_RECEIPT_CONFLICT`` otherwise). A refusal of
the integration store is ``ACCEPTANCE_STORE_UNAVAILABLE`` while nothing is committed, ``ACCEPTANCE_OUTCOME_UNKNOWN``
once a commit may be. The route runs on the event loop, so acceptances are serialized with the process's other routes.

What it never does: it opens no client socket, starts no process and calls no model; it reads no configuration file
and no credential; it imports neither the authorization recorder nor the dispatch-input commands (decision 0012's
``main-session`` channel is theirs alone).
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


capture = _load('aieh_ownerhost_capture', HERE / 'capture.py')
recorder = _load('acceptance_recorder', REPO / 'integrations' / 'owner' / 'acceptance_recorder.py')
conversation = capture.conversation
integration_store = capture.integration_store
lineage = capture.lineage
ra = capture.ra

VERSION = '1.0.0'
COMPONENT = f'owner-host-acceptance@{VERSION}'
RECEIPT_PREFIX = 'owner-ui/objective-acceptance/v1/'
RECEIPT_FORMAT = 'aieh-owner-ui-objective-acceptance/1'
ACTOR = 'owner-host-acceptance'
CHANNEL = recorder.OWNER_UI
RECORDED_BY = 'owner'
STATEMENT_ROLE, OWNER_AUTHOR = 'user', 'owner'
EXPIRY_MINUTES = recorder.DEFAULT_EXPIRY_MINUTES
MAX_HELD = 64                          # challenges held at once; the oldest is dropped first
ITEM = r'(?P<item>O[1-9][0-9]*)'
CHANGE = r'(?P<change>[a-z0-9]+(?:-[a-z0-9]+)*)'
REVIEW_LAYOUT = re.compile(rf'Review acceptance: {ITEM} of {CHANGE}')
ACCEPT_LINE = re.compile(rf'Accept {ITEM} of {CHANGE}')
NONCE = re.compile(r'[0-9a-f]{32}')
SHA256 = capture.SHA256
MESSAGE_ID = conversation.MESSAGE_ID
OUTCOME_TRAILER, DECISION_TRAILER = 'AIEH-Outcome-Id: ', 'AIEH-Decision-Id: '

STATUS = {'REQUEST_INVALID': 400, 'ACCEPTANCE_LAYOUT_INVALID': 422, 'ACCEPTANCE_MESSAGE_MISMATCH': 409,
          'ACCEPTANCE_NOT_A_STATEMENT': 409, 'ACCEPTANCE_MODEL_AUTHORED': 409, 'STATEMENT_NOT_OWNER': 409,
          'ACCEPTANCE_SESSION_MISMATCH': 403, 'ACCEPTANCE_CHALLENGE_UNKNOWN': 409,
          'ACCEPTANCE_CHALLENGE_MISMATCH': 409, 'ACCEPTANCE_NOT_AFTER_CARD': 409, 'CHALLENGE_CONSUMED': 409,
          'CHALLENGE_EXPIRED': 409, 'CHALLENGE_STALE': 409, 'ACCEPTANCE_RECEIPT_CONFLICT': 409,
          'ACCEPTANCE_STORE_UNAVAILABLE': 503, 'ACCEPTANCE_OUTCOME_UNKNOWN': 500}
REMEDIES = {
    'REQUEST_INVALID': 'send {sha256, card} for a challenge or {nonce, sha256} for an acceptance: the sha256 of the '
                       'message text\'s UTF-8 bytes (64 lower-case hex digits), the card\'s message id, the '
                       'challenge\'s nonce (32 lower-case hex digits)',
    'ACCEPTANCE_LAYOUT_INVALID': 'review with exactly "Review acceptance: O<n> of <change>"; accept with "Accept O<n> '
                                 'of <change>" on the first line, optionally followed by your own words',
    'ACCEPTANCE_MESSAGE_MISMATCH': 'the message stored under this id is not the text sent; reload the thread and send '
                                   'the stored message',
    'ACCEPTANCE_NOT_A_STATEMENT': 'review from an Owner message (a user message of the thread), not a reply',
    'ACCEPTANCE_MODEL_AUTHORED': 'a model, an agent or the Owner host cannot accept: accept with your own message',
    'STATEMENT_NOT_OWNER': 'only the Owner accepts an objective: accept with your own message',
    'ACCEPTANCE_SESSION_MISMATCH': 'accept in the session that was shown the challenge, with a message made in it: '
                                   'review again in your current session',
    'ACCEPTANCE_CHALLENGE_UNKNOWN': 'the challenge is not held (it was never issued here, or the Integration process '
                                    'restarted since): review again and accept on the new card',
    'ACCEPTANCE_CHALLENGE_MISMATCH': 'accept the item the card shows, in the thread that holds the card',
    'ACCEPTANCE_NOT_AFTER_CARD': 'accept after the card: send your acceptance from the card, in the thread\'s branch '
                                 'that holds it',
    'CHALLENGE_CONSUMED': 'a decision was already recorded on this challenge: review again for a new acceptance',
    'CHALLENGE_EXPIRED': 'review again and accept on the new card',
    'CHALLENGE_STALE': 'the proposal changed after the card was shown: review again and accept on the new card',
    'ACCEPTANCE_RECEIPT_CONFLICT': 'this message was recorded for another challenge or configuration; accept with a '
                                   'new message',
    'ACCEPTANCE_STORE_UNAVAILABLE': 'nothing was committed: start the Integration process through service.py up, which '
                                    'names the integration store, and make sure the store opens, then accept again',
    'ACCEPTANCE_OUTCOME_UNKNOWN': 'a commit may have been made and the receipt does not say so; read the project '
                                  'repository before anything else, then send the same acceptance again',
}
RECORDER_STATUS = {'PROJECT_UNAVAILABLE': 503, 'GIT_FAILED': 500, 'RESOLUTION_FAILED': 500, 'CHANGE_MISSING': 404,
                   'ITEM_NOT_OBJECTIVE': 422, 'OBJECT_NAME_INVALID': 422}


class AcceptanceRefused(Exception):
    """A refusal with a stable code and its remedy; nothing was changed unless the detail says otherwise."""

    def __init__(self, code: str, detail: str, status: int | None = None, remedy: str | None = None):
        self.code, self.detail = code, detail
        self.status = status if status is not None else STATUS[code]
        self.remedy = remedy if remedy is not None else REMEDIES[code]
        super().__init__(f'{code}: {detail}')


def _refused(exc) -> AcceptanceRefused:
    """A refusal of capture.py's shared checks or of the acceptance recorder, as this path's refusal (same code)."""
    if isinstance(exc, capture.CaptureRefused):
        return AcceptanceRefused(exc.code, exc.detail, exc.status, exc.remedy)
    return AcceptanceRefused(exc.code, exc.detail, STATUS.get(exc.code, RECORDER_STATUS.get(exc.code, 409)),
                             exc.remedy)


def receipt_key(thread_id: str, message_id: str) -> str:
    return f'{RECEIPT_PREFIX}{thread_id}/{message_id}'


def statement_line(reference: str) -> str:
    """The line of the recorder's commit message that names the statement (``acceptance_recorder.commit_message``)."""
    return f'acceptance recorder. Statement: {reference} ({CHANNEL}).'


def parse_accept(content: bytes) -> tuple[str, str]:
    """(change, item) of an acceptance: ``Accept <item> of <change>`` alone, or followed by LF and the Owner's own
    words (some visible text); LF only. Anything else is ACCEPTANCE_LAYOUT_INVALID."""
    text = content.decode('utf-8')
    first, newline, rest = text.partition('\n')
    match = ACCEPT_LINE.fullmatch(first)
    if match is None or '\r' in text or (newline and not rest.strip()) or match['change'] == 'archive':
        raise AcceptanceRefused('ACCEPTANCE_LAYOUT_INVALID', 'the acceptance is not "Accept O<n> of <change>", '
                                                             'optionally followed by a line break and your own words')
    return match['change'], match['item']


def parse_review(content: bytes) -> tuple[str, str]:
    """(change, item) of a review request: exactly ``Review acceptance: <item> of <change>``."""
    match = REVIEW_LAYOUT.fullmatch(content.decode('utf-8'))
    if match is None or match['change'] == 'archive':
        raise AcceptanceRefused('ACCEPTANCE_LAYOUT_INVALID', 'the request is not "Review acceptance: O<n> of '
                                                             '<change>"')
    return match['change'], match['item']


def _timestamp(text: str) -> datetime.datetime:
    return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)


@dataclasses.dataclass
class Held:
    """A challenge as this process issued it: to SESSION, in THREAD, on the REQUEST message, shown in CARD."""
    challenge: dict
    thread: str
    request: str
    card: str
    session: str

    @property
    def subject(self) -> dict:
        return self.challenge['subject']


class SessionBinding:
    """The owner-ui channel's verifier (acceptance_recorder ``session_binding``): None when the statement is the
    stored message REFERENCE names, a user message authored by ``owner`` under SESSION_ID with that digest and text,
    and the challenge is the one held for SESSION_ID; else the reason."""

    def __init__(self, store, thread_id: str, message_id: str, session_id: str, held: Held):
        self.store, self.thread_id, self.message_id, self.session_id, self.held = (store, thread_id, message_id,
                                                                                  session_id, held)

    def __call__(self, statement, challenge):
        try:
            stored = self.store.message(self.thread_id, self.message_id)
        except conversation.ConversationRefused:
            return 'the message is not in the Owner conversation store'
        if (stored.role, stored.author) != (STATEMENT_ROLE, OWNER_AUTHOR):
            return 'the message is not an Owner statement'
        if stored.session_id != self.session_id:
            return 'the message was not made under the session making the request'
        if statement.get('reference') != lineage.message_reference(self.thread_id, self.message_id,
                                                                   stored.content).text:
            return 'the statement\'s reference is not the stored message with its digest'
        if statement.get('text') != stored.content.decode('utf-8'):
            return 'the statement\'s text is not the stored message'
        if challenge != self.held.challenge or self.held.session != self.session_id:
            return 'the challenge was not issued to the session making the request'
        return None


class Acceptance:
    """The objective acceptance of the Integration process: its project configuration (RAW, ``components.owner_host``),
    the integration store's path, the clock (NOW: an aware datetime) and the challenges it holds."""

    def __init__(self, raw_config, integration_store_path, *, now=None):
        self.raw_config, self.integration_store_path = raw_config, integration_store_path
        self.now = now or recorder.utc_now
        self.held: dict[str, Held] = {}

    # ------------------------------------------------------------------------ shared checks

    def _config(self):
        try:
            return capture.project_config(self.raw_config)
        except capture.CaptureRefused as exc:
            raise _refused(exc) from None

    @staticmethod
    def _body(body, keys):
        if not isinstance(body, dict) or set(body) != set(keys):
            raise AcceptanceRefused('REQUEST_INVALID', f'the body must be exactly {{{", ".join(keys)}}}')
        if not isinstance(body['sha256'], str) or not SHA256.fullmatch(body['sha256']):
            raise AcceptanceRefused('REQUEST_INVALID', 'sha256 must be 64 lower-case hex digits')

    @staticmethod
    def _principal(session, stored):
        try:
            principal = capture.session_principal(session)
        except capture.CaptureRefused as exc:
            raise _refused(exc) from None
        if stored.session_id != session['sessionId']:
            raise AcceptanceRefused('ACCEPTANCE_SESSION_MISMATCH', 'the message was made under another session than '
                                                                   'the one making the request; nothing was changed')
        return principal

    @staticmethod
    def _open(config):
        try:
            return capture.open_project(config)
        except capture.CaptureRefused as exc:
            raise _refused(exc) from None

    # ------------------------------------------------------------------------ the challenge

    def prepare(self, store, thread_id: str, message_id: str, body, session: dict) -> dict:
        config = self._config()
        self._body(body, ('sha256', 'card'))
        card = body['card']
        if not isinstance(card, str) or not MESSAGE_ID.fullmatch(card) or card == message_id:
            raise AcceptanceRefused('REQUEST_INVALID', 'card must be the id of the assistant message that shows it')
        stored = store.message(thread_id, message_id)
        if (stored.role, stored.author) != (STATEMENT_ROLE, OWNER_AUTHOR):
            raise AcceptanceRefused('ACCEPTANCE_NOT_A_STATEMENT', 'the review is asked from a message that is not an '
                                                                  'Owner statement')
        if hashlib.sha256(stored.content).hexdigest() != body['sha256']:
            raise AcceptanceRefused('ACCEPTANCE_MESSAGE_MISMATCH', 'the request\'s sha256 is not the stored message\'s')
        self._principal(session, stored)
        change, item = parse_review(stored.content)
        self._open(config).close()
        now = self.now()
        try:
            challenge = recorder.prepare(config.project_repository, change, item, now=now,
                                         expires_in_minutes=EXPIRY_MINUTES)
        except recorder.RecorderError as exc:
            raise _refused(exc) from None
        self._hold(Held(challenge, thread_id, message_id, card, session['sessionId']), now)
        shown, subject = challenge['shown'], challenge['subject']
        return {'nonce': shown['nonce'], 'change': subject['change'], 'item': subject['item'],
                'revision': subject['revision'], 'proposal': subject['proposal'], 'summary': shown['summary'],
                'expiresAt': shown['expiresAt'], 'card': card, 'request': message_id}

    def _hold(self, held: Held, now) -> None:
        for nonce in [n for n, h in self.held.items() if _timestamp(h.challenge['shown']['expiresAt']) <= now]:
            del self.held[nonce]
        while len(self.held) >= MAX_HELD:
            del self.held[next(iter(self.held))]
        self.held[held.challenge['shown']['nonce']] = held

    # ------------------------------------------------------------------------ the acceptance

    def record(self, store, thread_id: str, message_id: str, body, session: dict) -> dict:
        config = self._config()
        self._body(body, ('nonce', 'sha256'))
        if not isinstance(body['nonce'], str) or not NONCE.fullmatch(body['nonce']):
            raise AcceptanceRefused('REQUEST_INVALID', 'nonce must be 32 lower-case hex digits')
        stored = store.message(thread_id, message_id)
        if stored.role != STATEMENT_ROLE:
            raise AcceptanceRefused('ACCEPTANCE_MODEL_AUTHORED', f'the message is an {stored.role} message, not the '
                                                                 'Owner\'s statement; nothing was changed')
        if stored.author != OWNER_AUTHOR:
            raise AcceptanceRefused('STATEMENT_NOT_OWNER', 'the message is not attributed to the Owner')
        digest = hashlib.sha256(stored.content).hexdigest()
        if digest != body['sha256']:
            raise AcceptanceRefused('ACCEPTANCE_MESSAGE_MISMATCH', 'the request\'s sha256 is not the stored message\'s')
        principal = self._principal(session, stored)
        try:
            _author, identity = capture.capture_identities(config, principal)
        except capture.CaptureRefused as exc:
            raise _refused(exc) from None
        change, item = parse_accept(stored.content)
        reference = lineage.message_reference(thread_id, message_id, stored.content).text
        statement = {'text': stored.content.decode('utf-8'), 'attributedTo': OWNER_AUTHOR, 'channel': CHANNEL,
                     'reference': reference}
        key = receipt_key(thread_id, message_id)
        intent = {'format': RECEIPT_FORMAT, 'component': COMPONENT, 'thread': thread_id, 'message': message_id,
                  'messageSha256': digest, 'messageSession': stored.session_id, 'statement': reference,
                  'nonce': body['nonce'], 'change': change, 'item': item,
                  'project': {'id': config.project_repository_id, 'path': str(config.project_repository)}}
        repo = self._open(config)
        progress = capture._Progress()
        try:
            path = Path(self.integration_store_path) if self.integration_store_path is not None else None
            if path is not None and path.exists():
                with integration_store.open_store(path) as receipts:
                    settled = self._settled(repo, receipts, key, intent, reference, session['sessionId'], progress)
                if settled is not None:
                    return settled
            held = self._checked(store, repo, thread_id, message_id, stored, change, item, body['nonce'],
                                 session['sessionId'])
            amend = self._amend(repo, change, item)
            if path is None:
                raise AcceptanceRefused('ACCEPTANCE_STORE_UNAVAILABLE', 'no integration store is named; nothing was '
                                                                        'changed')
            path.parent.mkdir(exist_ok=True)
            with integration_store.open_store(path) as receipts:
                return self._record(repo, receipts, key, intent, held, statement, identity, amend,
                                    SessionBinding(store, thread_id, message_id, session['sessionId'], held),
                                    session['sessionId'], progress)
        except (integration_store.StoreError, sqlite3.Error) as exc:
            code = 'ACCEPTANCE_OUTCOME_UNKNOWN' if progress.commit else 'ACCEPTANCE_STORE_UNAVAILABLE'
            written = f'the commit {progress.commit} is on the branch' if progress.commit else 'nothing was committed'
            raise AcceptanceRefused(code, f'the integration store refused: {type(exc).__name__}: {exc}; '
                                          f'{written}') from None
        finally:
            repo.close()

    def _checked(self, store, repo, thread_id, message_id, stored, change, item, nonce, session_id) -> Held:
        """The held challenge NONCE, checked against this acceptance before anything is reserved."""
        held = self.held.get(nonce)
        if held is None:
            raise AcceptanceRefused('ACCEPTANCE_CHALLENGE_UNKNOWN', 'this process holds no challenge with that nonce; '
                                                                    'nothing was changed')
        if held.session != session_id:
            raise AcceptanceRefused('ACCEPTANCE_SESSION_MISMATCH', 'the challenge was issued to another session; '
                                                                   'nothing was changed')
        if held.thread != thread_id or (held.subject['change'], held.subject['item']) != (change, item):
            raise AcceptanceRefused('ACCEPTANCE_CHALLENGE_MISMATCH', 'the challenge is of another thread or item')
        messages = {m.message_id: m for m in store.messages(thread_id)}
        card = messages.get(held.card)
        if card is None or card.role != 'assistant' or card.parent_id != held.request or card.session_id != session_id:
            raise AcceptanceRefused('ACCEPTANCE_NOT_AFTER_CARD', 'the card is not the stored reply to the review in '
                                                                 'this session')
        ancestor, seen = stored.parent_id, set()
        while ancestor is not None and ancestor != held.card and ancestor not in seen:
            seen.add(ancestor)
            ancestor = messages[ancestor].parent_id if ancestor in messages else None
        if ancestor != held.card:
            raise AcceptanceRefused('ACCEPTANCE_NOT_AFTER_CARD', 'the acceptance does not follow the card in the '
                                                                 'thread')
        shown = held.challenge['shown']
        head = repo.head().commit
        try:   # the recorder's own reading of the change's committed decision records
            recorded = recorder._recorded_decisions(repo, head, f'{capture.CHANGES_DIR}/{change}')
        except recorder.RecorderError as exc:
            raise _refused(exc) from None
        except ra.RepositoryError as exc:
            raise AcceptanceRefused('GIT_FAILED', str(exc), 500, recorder.REMEDIES['GIT_FAILED']) from None
        if any(r.get('shown', {}).get('nonce') == shown['nonce'] for r in recorded):
            raise AcceptanceRefused('CHALLENGE_CONSUMED', 'a decision was already recorded on this challenge')
        if self.now() >= _timestamp(shown['expiresAt']):
            raise AcceptanceRefused('CHALLENGE_EXPIRED', f'the challenge expired at {shown["expiresAt"]}')
        proposal = repo.read(f'{head}:{capture.CHANGES_DIR}/{change}/proposal.md')
        if proposal is None or hashlib.sha256(proposal[2]).hexdigest() != held.subject['proposal']:
            raise AcceptanceRefused('CHALLENGE_STALE', 'the proposal at HEAD is not the one the card showed')
        return held

    @staticmethod
    def _amend(repo, change, item) -> bool:
        """Whether ITEM already has its outcome id at HEAD (a re-acceptance, which keeps it)."""
        meta = repo.read(f'{repo.head().commit}:{capture.CHANGES_DIR}/{change}/.openspec.yaml')
        try:
            outcomes = recorder.R.read_x_outcomes(meta[2] if meta is not None else b'')
        except recorder.R.OutcomeMetadataInvalid as exc:
            raise AcceptanceRefused('OUTCOME_METADATA_INVALID', str(exc), 409,
                                    recorder.REMEDIES['OUTCOME_METADATA_INVALID']) from None
        return any(entry['item'] == item for entry in outcomes.values())

    def _settled(self, repo, receipts, key, intent, reference, session_id, progress):
        """The answer of an earlier acceptance of this message, or None: a confirmed receipt answers itself; one left
        reserved or dispatched is settled by reading the repository first."""
        existing = receipts.get(key)
        if existing is None:
            return None
        same_intent(existing, intent, key)
        if existing.state == 'confirmed':
            return self._answer(receipts, key, created=False)
        found = find_acceptance(repo, reference)
        if found is not None:
            progress.commit = found['commit']
            self._confirm(receipts, key, found, 'settled by reading the project repository', session_id)
            return self._answer(receipts, key, created=False)
        if existing.state == 'dispatched':
            raise AcceptanceRefused('ACCEPTANCE_OUTCOME_UNKNOWN', f'{key} is dispatched and no local branch holds '
                                                                  'its commit')
        if existing.state != 'reserved':
            raise AcceptanceRefused('ACCEPTANCE_RECEIPT_CONFLICT', f'{key} is {existing.state}')
        return None

    def _record(self, repo, receipts, key, intent, held, statement, identity, amend, binding, session_id, progress):
        try:
            receipts.reserve(key, intent, actor=ACTOR)
        except integration_store.ConflictingReservation:
            raise AcceptanceRefused('ACCEPTANCE_RECEIPT_CONFLICT', f'{key} holds another intent') from None
        try:
            result = recorder.record(Path(repo.root), held.challenge, statement, recorded_by=RECORDED_BY,
                                     identity=identity, amend=amend, now=self.now(), session_binding=binding)
        except recorder.RecorderError as exc:
            committed = exc.details.get('committed') if exc.code == 'GIT_FAILED' else None
            if committed:
                found = commit_facts(repo, committed)
                progress.commit = committed
                self._confirm(receipts, key, found, 'committed; the work tree was not brought to it', session_id)
                return self._answer(receipts, key, created=True, work_tree='not brought to the commit')
            refused = _refused(exc)
            refused.detail += (f'; the receipt {key} stays reserved and nothing was written to the project '
                               'repository: send the same acceptance again once the cause is repaired')
            raise refused from None
        progress.commit = result['commit']
        found = {'commit': result['commit'], 'outcome': result['outcome'],
                 'decision': result['decision']['decisionId'], 'minted': result['minted']}
        self._confirm(receipts, key, found, 'committed', session_id)
        return self._answer(receipts, key, created=True)

    @staticmethod
    def _confirm(receipts, key, found, reason, session_id):
        detail = {**found, 'acceptedBySession': session_id}
        if receipts.get(key).state == 'reserved':
            receipts.transition(key, 'dispatched', actor=ACTOR, reason=reason, detail=detail, expected_from='reserved')
        receipts.transition(key, 'confirmed', actor=ACTOR, reason=reason, detail=detail, expected_from='dispatched')

    @staticmethod
    def _answer(receipts, key, *, created, work_tree=None):
        """The answer, built from the receipt alone: its intent and its confirmed commit."""
        intent = json.loads(receipts.get(key).intent_json)
        confirmed = [e for e in receipts.events(key) if e.to_state == 'confirmed']
        facts = json.loads(confirmed[-1].detail_json)
        answer = {'change': intent['change'], 'item': intent['item'], 'outcome': facts['outcome'],
                  'minted': facts['minted'], 'commit': facts['commit'], 'decision': facts['decision'],
                  'reference': f'outcome:{facts["outcome"]}@{facts["commit"]}', 'statement': intent['statement'],
                  'receipt': key, 'created': created, 'state': 'confirmed', 'project': intent['project']['id']}
        if work_tree is not None:
            answer['workTree'] = work_tree
        return answer


def same_intent(reservation, intent: dict, key: str) -> None:
    """A receipt answers only the request it was made for: its project (id and path), change, item, message digest
    and nonce; else ACCEPTANCE_RECEIPT_CONFLICT, nothing changed."""
    stored = json.loads(reservation.intent_json)
    for name in ('change', 'item', 'messageSha256', 'nonce', 'statement'):
        if stored.get(name) != intent[name]:
            raise AcceptanceRefused('ACCEPTANCE_RECEIPT_CONFLICT', f'{key} was recorded with another {name}; '
                                                                   'nothing was changed')
    if stored.get('project') != intent['project']:
        raise AcceptanceRefused('ACCEPTANCE_RECEIPT_CONFLICT', f'{key} was recorded for another project; nothing was '
                                                               'changed')


def commit_facts(repo, commit: str) -> dict:
    """{commit, outcome, decision, minted} of an acceptance commit, read from the recorder's message trailers."""
    found = repo.read(commit)
    if found is None or found[1] != 'commit':
        raise AcceptanceRefused('ACCEPTANCE_OUTCOME_UNKNOWN', f'commit {commit} cannot be read')
    _parents, message = capture._parse_commit(found[2])
    lines = message.decode('utf-8', 'replace').split('\n')
    trailers = {prefix: line[len(prefix):] for line in lines
                for prefix in (OUTCOME_TRAILER, DECISION_TRAILER) if line.startswith(prefix)}
    if set(trailers) != {OUTCOME_TRAILER, DECISION_TRAILER}:
        raise AcceptanceRefused('ACCEPTANCE_OUTCOME_UNKNOWN', f'commit {commit} carries no acceptance trailers')
    return {'commit': found[0], 'outcome': trailers[OUTCOME_TRAILER], 'decision': trailers[DECISION_TRAILER],
            'minted': lines[0].startswith('Accept ')}


def find_acceptance(repo, reference: str) -> dict | None:
    """The acceptance commit of REFERENCE that a local branch reaches (every ``refs/heads/*``, every parent), found by
    the recorder's statement line; None when there is none."""
    wanted = statement_line(reference).encode('utf-8')
    queue = list(dict.fromkeys(capture.branch_tips(repo)))
    seen, read = set(queue), 0
    while queue:
        oid = queue.pop(0)
        read += 1
        if read > capture.HISTORY_CEILING:
            raise AcceptanceRefused('ACCEPTANCE_OUTCOME_UNKNOWN', f'the branches hold more than '
                                                                  f'{capture.HISTORY_CEILING} commits')
        found = repo.read(oid)
        if found is None or found[1] != 'commit':
            raise AcceptanceRefused('ACCEPTANCE_OUTCOME_UNKNOWN', f'commit {oid} cannot be read')
        parents, message = capture._parse_commit(found[2])
        if wanted in message.split(b'\n'):
            return commit_facts(repo, oid)
        for parent in parents:
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)
    return None
