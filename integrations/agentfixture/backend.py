"""The fixture's other seams (plan leaf E-01.8; the I1 integration design, R10 and R13; decision 0026 points 2 and 5):
what a fixture attempt is given besides its transport, each declaring the authority ``fixture`` (R8 point 3), so that
the dispatcher takes it only for an attempt bound to the fixture authority and refuses it for any other.

- ``FixtureCredentials``: the fixture credential provider (R10, PB-3 as planning confirmed it). Its entries hold values
  derived from public seeds committed here, never a secret: the native token's one entry (a value of the native
  token's shape, ``native_token``) and the builder bot's (``bot_token``, the fake Gitea's own public seed,
  ``integrations/owner/tests/fake_gitea.py`` ``BOT_TOKENS``). It is read only: ``set`` and ``delete`` refuse. The host
  credential provider is never constructed on the fixture path: no module of ``integrations/credentials/`` is loaded
  (the composition root's import census, ``tests/test_dispatch.py``).
- ``RecordedInspect``: the recorded inspect source (R13): the core's ``container-inspect`` entry (cited), as the
  launch gate's ``inspect_source``.
- ``Declared``: a callable declaring an authority, for the launch gate's ``inspect`` (the gate is the production one;
  its authority is its inspect source's).
- ``Puller``: the exchange pull over the retained verifier (``tools/guest.py`` ``verify_pulled_bundle``, real git,
  decision 0014 row R6) from the fixture's exchange directory, where the fixture transport's delivery wrote the
  bundle (``transport.py``); as ``tools/guest.py``'s ``exchange_pull`` stages it, never overwritten.

Standard library only; ``tools/guest.py`` is loaded by path when a ``Puller`` is made.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
AUTHORITY = 'fixture'

# Public seeds: the values below are derived from them at run time, so that no credential-shaped literal is committed.
NATIVE_SEED = 'E-01.8 fixture credential provider: the native token entry (a public seed, not a credential)'
NATIVE_PREFIX = 'sk-ant-' + 'oat01' + '-'       # the public part of the native token's shape
NATIVE_LENGTH = 99
BOT_SEED = 'synthetic token {bot}'              # integrations/owner/tests/fake_gitea.py BOT_TOKENS


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


def _native():
    return _load('aieh_dispatch_native_token', REPO / 'integrations' / 'dispatch' / 'native_token.py')


def _roles():
    return _load('aieh_gitea_roles', REPO / 'integrations' / 'gitea' / 'gitea_roles.py')


def native_token(seed: str = NATIVE_SEED, length: int = NATIVE_LENGTH) -> str:
    """A value of the native token's shape derived from SEED: NATIVE_PREFIX and the URL-safe base64 of the seed's
    sha512, chained, LENGTH in all (the pattern of integrations/dispatch/tests/native_support.token)."""
    body = base64.urlsafe_b64encode(hashlib.sha512(seed.encode('utf-8')).digest()).decode('ascii').rstrip('=')
    while len(NATIVE_PREFIX) + len(body) < length:
        body += base64.urlsafe_b64encode(hashlib.sha512(body.encode('ascii')).digest()).decode('ascii').rstrip('=')
    return (NATIVE_PREFIX + body)[:length]


def bot_token(bot: str) -> str:
    """The fake Gitea's public-seed token of BOT (40 lower-case hex digits, Gitea's token shape)."""
    return hashlib.sha1(BOT_SEED.format(bot=bot).encode('utf-8'), usedforsecurity=False).hexdigest()


class FixtureCredentials:
    """The fixture credential provider (module docstring): ``get`` answers its public-seed entries and records the
    entry names read (``reads``); it is never written."""
    authority = AUTHORITY
    name = 'agentfixture-public-seeds'

    def __init__(self):
        native, roles = _native(), _roles()
        builder = roles.ROLES['builder']['user']
        self.entries = {native.ENTRY: (native.ENTRY_USER, native_token()),
                        roles.target('builder'): (builder, bot_token(builder))}
        self.reads: list[str] = []

    def get(self, name):
        self.reads.append(name)
        return self.entries.get(name)

    def set(self, *args, **kwargs):
        raise PermissionError('the fixture credential provider is never written')

    def delete(self, *args, **kwargs):
        raise PermissionError('the fixture credential provider is never written')


class RecordedInspect:
    """The recorded inspect source (R13): CORE's ``container_inspect`` (the catalog's cited ``container-inspect``)."""
    authority = AUTHORITY

    def __init__(self, core):
        self.core = core

    def __call__(self, conversation_id):
        return self.core.container_inspect(conversation_id)


class Declared:
    """CALL, declaring AUTHORITY (R8 point 3)."""

    def __init__(self, call, authority: str):
        self.call, self.authority = call, authority

    def __call__(self, *args, **kwargs):
        return self.call(*args, **kwargs)


def guest_module():
    return _load('aieh_tools_guest', REPO / 'tools' / 'guest.py')


INSTANCE = 'agentfixture'       # the pull's staging instance name (the replayed profile's instance-name grammar)


class Puller:
    """The exchange pull (``run_attempt``'s ``pull(name)``) from the fixture's EXCHANGE directory: the file copied into
    the staging directory of ``tools/guest.py`` (``staging_dir``: inbound, under STATE's instance directory, as
    ``exchange_pull`` stages it; an existing name is never overwritten) and verified by the retained verifier,
    ``verify_pulled_bundle`` (real git). PROFILE_DIR is the replayed execution profile's directory (its exchange and
    staging layout); STATE a guest-state directory of its own (``tools/guest.py``'s rule: outside the user's
    profile). Answers what ``exchange_pull`` answers: ``{result, staged, bundle}``."""
    authority = AUTHORITY

    def __init__(self, exchange, state, profile_dir):
        self.guest = guest_module()
        self.exchange = Path(exchange)
        self.ctx = self.guest.Context(str(profile_dir), str(state))
        self.names: list[str] = []

    def __call__(self, name: str):
        self.names.append(name)
        data = (self.exchange / name).read_bytes()
        local = self.guest.staging_dir(self.ctx, INSTANCE, 'inbound') / name
        if os.path.lexists(local):
            raise self.guest.Refused('REFUSED', f'{local} exists; never overwritten')
        local.write_bytes(data)
        try:
            bundle = self.guest.verify_pulled_bundle(self.ctx, INSTANCE, local)
        except self.guest.Refused as exc:
            bundle = {'verified': False, 'error': exc.code}
        return {'result': 'pulled' if bundle.get('verified') else 'unverified', 'bundle': bundle,
                'staged': {'path': str(local), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}
