"""The stage's bot role token, delivered per attempt in the dispatcher's attempt context only (plan leaf
E-01.3.3; decision 0007 point 4 as amended by amendment 1, decision 0013 point 7;
policy/role-tokens.json).

Each attempt stage maps to exactly one Gitea bot of ``integrations/gitea/gitea_roles.py`` (``STAGE_ROLES``):
``implement`` to the builder (``aieh-bot-builder``, ``cred-gitea-bot-builder``) and ``review`` to the reviewer
(``aieh-bot-reviewer``, ``cred-gitea-bot-reviewer``). The dispatcher is the custodian of those standing bot
credentials; the token goes to the dispatcher's own attempt context, never into a conversation container:
untrusted code has no network path to Gitea, proposals leave by exchange and the dispatcher pushes as the bot
it holds custody of (decision 0013 point 7).

``attempt_role_token(integration_store, operation_key, provider=, port=, http=)`` is that context::

    with attempt_role_token(store, key, provider=provider, port=gitea_port) as delivery:
        repository.push(url, refspec, credential=delivery.credential())   # the dispatcher's own push
        log(delivery.record())                                            # fingerprints only

It takes no stage, role, bot or entry from its caller. In this order, and the first failure refuses
(``DispatchRefused``) before anything else is read or sent:

1. the attempt's dispatch record re-read from the store (``stored_inputs``: its digest, its typed identity and
   its own intent), and the attempt ``confirmed`` (its conversation exists); otherwise RESERVATION_INVALID or
   ATTEMPT_NOT_CONFIRMED, and the credential provider is not read;
2. the stored stage's role and bot (``STAGE_ROLES``), and that role's one entry ``AIEH Gitea bot <role>``,
   read through ``gitea_roles.read_token`` (no other entry is read): none is ROLE_TOKEN_MISSING, an entry
   naming another account or a value that is not a Gitea token (40 lower-case hexadecimal digits) is
   ROLE_TOKEN_MISMATCH, a provider that fails is ROLE_TOKEN_UNAVAILABLE;
3. Gitea's own view of the token, ``GET /api/v1/token`` (no scope is needed): 401 is ROLE_TOKEN_REJECTED (a
   revoked or foreign token), a lost answer or anything but a 200 token view is ROLE_TOKEN_UNVERIFIED, and a
   token that authenticates as another account or with other scopes than the role's is ROLE_TOKEN_MISMATCH.

Inside the context the token is held in memory only: ``credential()`` gives the integrations/repository
``Credential`` (``Authorization: token``, sent to the remote's origin only); ``record()`` gives
``role-token-delivery/v1`` with the token's fingerprint and never the token. While the context is open the
Agent Server client refuses any call whose path or body carries the token or its fingerprint
(ROLE_TOKEN_EXPOSURE, ``dispatch_inputs.AgentServerClient``), so nothing the dispatcher sends into the guest
can hold it. At the end the in-memory reference is dropped and ``credential()`` refuses.

Three lifecycles are kept apart (the Owner's correction of 2026-11-11; decision 0007 point 4 as amended by
amendment 1):

1. the standing bot credential, held in the host's credential provider, is issued, rotated and revoked only by
   the existing administrative authority (``gitea_roles.py provision``, ``rotate`` and ``retire``) on defined
   security and lifecycle triggers, never on routine attempt completion. Gitea 28.3.0 gives the dispatcher no
   replacement mechanism (no token lifetime; minting is the site administrator's CLI);
2. its per-attempt use is this context: obtained only for a confirmed attempt, held in memory for the bounded
   operation and released when the operation ends. Releasing the in-memory reference is NOT Gitea revocation:
   the standing token stays valid, and concurrent or later attempts of the stage keep using it. Nothing here
   revokes, mints or writes a credential entry (the package reaches no mint: tests/test_attempt_tokens.py);
3. the per-attempt inference token (decision 0015) is a separate credential, issued by the inference broker and
   revoked at attempt end; it is not handled here.

A token Gitea refuses (revoked by the administrative lifecycle, or not this instance's) is ROLE_TOKEN_REJECTED
until that lifecycle replaces the entry. During bootstrap the Owner's account can read the standing credential
(decision 0013 point 6, a disclosed same-account limit). Not here: any live run
(evidence/E-01.3.3-dispatcher-custody.md).
"""
from __future__ import annotations

import contextlib
import hashlib
import http.client as http_client
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', HERE / 'dispatch_inputs.py')
roles = _load('aieh_gitea_roles', REPO / 'integrations' / 'gitea' / 'gitea_roles.py')
DispatchRefused = di.DispatchRefused

DELIVERY_FORMAT = 'ai-engineering-harness/dispatch/role-token-delivery/v1'
# The stage-to-bot mapping: one role per stage of the integration store's closed stage set.
STAGE_ROLES = {'implement': 'builder', 'review': 'reviewer'}
if set(STAGE_ROLES) != set(di.STAGES) or not set(STAGE_ROLES.values()) <= set(roles.ROLES) \
        or len(set(STAGE_ROLES.values())) != len(STAGE_ROLES):
    raise ImportError('STAGE_ROLES must map each stage of the store to its own role of gitea_roles.ROLES')


class AttemptRoleToken:
    """One attempt's delivered role token. The token is never shown: ``repr`` and ``record`` carry its
    fingerprint; ``credential()`` is the only way to it, while the attempt context is open."""

    __slots__ = ('operation_key', 'stage', 'role', 'bot', 'entry', 'fingerprint', 'scopes', '_token')

    def __init__(self, *, operation_key, stage, role, bot, entry, fingerprint, scopes, token):
        self.operation_key, self.stage, self.role, self.bot = operation_key, stage, role, bot
        self.entry, self.fingerprint, self.scopes, self._token = entry, fingerprint, scopes, token

    def __repr__(self):
        return (f'AttemptRoleToken(stage={self.stage!r}, bot={self.bot!r}, fingerprint={self.fingerprint!r}, '
                f'open={self._token is not None})')

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError('a delivered role token is not serializable')

    @property
    def open(self) -> bool:
        return self._token is not None

    def credential(self):
        """The ``Credential`` for the dispatcher's own Gitea requests (``Authorization: token``)."""
        if self._token is None:
            raise ValueError('the attempt context has ended: the role token is no longer held')
        access = roles.host._load_repository_access()
        return access.Credential(username=self.bot, secret=self._token, scheme='token')

    def record(self) -> dict:
        """What a record may carry: the attempt, the stage, the bot and the token's fingerprint."""
        return {'format': DELIVERY_FORMAT, 'operationKey': self.operation_key,
                'attemptId': di.store.attempt_id_for(self.operation_key), 'stage': self.stage, 'role': self.role,
                'bot': self.bot, 'entry': self.entry, 'credential': roles.ROLES[self.role]['credential'],
                'scopes': list(self.scopes), 'fingerprint': self.fingerprint}


def _read_entry(provider, role: str, bot: str) -> str:
    entry = roles.target(role)
    try:
        token = roles.read_token(provider, role)
    except roles.GiteaError as exc:
        if exc.code == 'ENTRY_MISMATCH':
            raise DispatchRefused('ROLE_TOKEN_MISMATCH', f'{entry!r} names another account, not {bot}',
                                  entry=entry) from None
        raise DispatchRefused('ROLE_TOKEN_UNAVAILABLE', f'{entry!r}: {exc.code}', entry=entry) from None
    except Exception as exc:  # fail closed: whatever the provider raises, nothing is delivered
        raise DispatchRefused('ROLE_TOKEN_UNAVAILABLE', f'{entry!r} could not be read ({type(exc).__name__})',
                              entry=entry) from None
    if token is None:
        raise DispatchRefused('ROLE_TOKEN_MISSING', f'no credential provider entry {entry!r} for {bot}', entry=entry)
    if not isinstance(token, str) or not roles.TOKEN_SHAPE.fullmatch(token.encode('ascii', 'replace')):
        raise DispatchRefused('ROLE_TOKEN_MISMATCH', f'{entry!r} does not hold a Gitea token (40 lower-case '
                              'hexadecimal digits)', entry=entry)
    return token


def _gitea_view(port: int, token: str, bot: str, scopes, http=None) -> None:
    """Gitea's own answer about the token: it must authenticate as BOT with exactly SCOPES."""
    try:
        status, view = roles.Api(port, token, http).call('GET', '/token')
    except (OSError, http_client.HTTPException) as exc:
        raise DispatchRefused('ROLE_TOKEN_UNVERIFIED', f'GET /api/v1/token: the answer was lost '
                              f'({type(exc).__name__})') from None
    if status == 401:
        raise DispatchRefused('ROLE_TOKEN_REJECTED', f'Gitea refuses the token of {bot} (401): revoked, or not this '
                              'instance\'s')
    user = view.get('user') if isinstance(view, dict) else None
    login = user.get('login') if isinstance(user, dict) else None
    granted = view.get('scopes') if isinstance(view, dict) else None
    if status != 200 or not isinstance(login, str) or not isinstance(granted, list):
        raise DispatchRefused('ROLE_TOKEN_UNVERIFIED', f'GET /api/v1/token answered {status} without a token view',
                              status=status if type(status) is int else None)
    if login != bot:
        raise DispatchRefused('ROLE_TOKEN_MISMATCH', f'the token authenticates as {login!r}, not {bot}',
                              login=login[:64])
    if sorted(map(str, granted)) != sorted(scopes):
        raise DispatchRefused('ROLE_TOKEN_MISMATCH', f'the token\'s scopes are {sorted(map(str, granted))!r}, not '
                              f'exactly {sorted(scopes)!r}')


@contextlib.contextmanager
def attempt_role_token(integration_store, operation_key: str, *, provider, port: int, http=None):
    """The confirmed attempt's stage bot token, in the dispatcher's attempt context (module docstring)."""
    resolved = di.stored_inputs(integration_store, operation_key, state='confirmed')
    role = STAGE_ROLES[resolved.stage]
    spec = roles.ROLES[role]
    bot, scopes = spec['user'], tuple(spec['scopes'])
    token = _read_entry(provider, role, bot)
    _gitea_view(port, token, bot, scopes, http)
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    delivery = AttemptRoleToken(operation_key=operation_key, stage=resolved.stage, role=role, bot=bot,
                                entry=roles.target(role), fingerprint=roles.fingerprint(token), scopes=scopes,
                                token=token)
    del token
    di.hold_role_token(digest, delivery.fingerprint)
    try:
        yield delivery
    finally:
        # The in-memory reference is released; the standing token is not revoked (module docstring, lifecycle 2).
        delivery._token = None
        di.release_role_token(digest)
