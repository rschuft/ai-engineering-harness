"""A synthetic catalog repository for the resolver's tests (plan leaf E-05.3).

``Catalog`` holds the blobs of commits of catalog repositories in memory and answers as a
``dispatch_inputs.CatalogSource`` does: the bytes at a commit and path, or None when the commit or
the blob is absent (an entry named in ``not_regular`` raises as a symbolic link or an executable
would). ``standard()`` is the fixture's catalog: the builder and reviewer pins' agent assignments at
``PIN_COMMIT`` of ``CATALOG``, with the provider registry entry they name (the checked-in file's bytes).
Each assigns ``FIXTURE_TEMPLATE``, the create template ``strong-test-profile`` admits for both stages
(the checked-in F-04.2 fixture copied beside the synthetic profile). Since E-05.3's review (R-dev2) the
resolver requires an assignment's template to be the one the resolved profile admits, so the resolution
fixture (``test_dispatch_inputs.Fixture.assign``) gives every other profile of a binding its own pin,
``<pin>-<profile>``, assigning that profile's admitted template. It reads nothing but checked-in files,
and no git.
"""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

CATALOG = 'aieh-catalog'
PIN_COMMIT = 'c' * 40
FORMAT = 'ai-engineering-harness/catalog/agent-assignment/v1'
REGISTRY_PATH = 'integrations/dispatch/qualification/acp-registry-claude-code-1.60.1.json'
DEFAULT_PROFILE = 'strong-test-profile'
STANDARD_PINS = ('builder-pin', 'reviewer-pin')


def checked_in(path: str) -> bytes:
    return (REPO / path).read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# The template strong-test-profile admits (its F-04.2 fixture pin: the checked-in conversation-create.json copied to
# profiles/strong-test-profile/agent-server/).
FIXTURE_TEMPLATE = {
    'path': f'profiles/{DEFAULT_PROFILE}/agent-server/conversation-create.json',
    'sha256': sha256(checked_in('profiles/strong-windows-qemu-whpx/agent-server/conversation-create.json'))}


def assignment(pin: str, *, template=None, provider=REGISTRY_PATH, skills=(), acp_server='claude-code',
               provider_sha=None, change=None) -> bytes:
    """The bytes of an agent-assignment/v1 for PIN assigning TEMPLATE (``{path, sha256}``; FIXTURE_TEMPLATE by
    default) and naming the checked-in PROVIDER by its sha256 (unless PROVIDER_SHA is given); CHANGE, then, edits
    the parsed object."""
    data = {'format': FORMAT, 'id': pin,
            'provider': {'path': provider, 'sha256': provider_sha or sha256(checked_in(provider)),
                         'acp_server': acp_server},
            'create_template': dict(template or FIXTURE_TEMPLATE),
            'skills': list(skills)}
    if change is not None:
        change(data)
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


def assigned_pin(pin, profile):
    """The pin a fixture request names for PROFILE: a standard pin assigns DEFAULT_PROFILE's template, so another
    profile's request names ``<pin>-<profile>``; any other pin is itself."""
    if pin in STANDARD_PINS and profile not in (None, DEFAULT_PROFILE):
        return f'{pin}-{profile}'
    return pin


BUILDER_BYTES = assignment('builder-pin')
REVIEWER_BYTES = assignment('reviewer-pin')
BUILDER_SHA = sha256(BUILDER_BYTES)
REVIEWER_SHA = sha256(REVIEWER_BYTES)
STANDARD_SHA = {'builder-pin': BUILDER_SHA, 'reviewer-pin': REVIEWER_SHA}


class NotRegular(Exception):
    pass


class Catalog:
    """Commits of catalog repositories, in memory: ``{repository: {commit: {path: bytes}}}``."""

    def __init__(self):
        self.repositories: dict[str, dict[str, dict[str, bytes]]] = {}
        self.reads: list[tuple[str, str, str]] = []
        self.fail: Exception | None = None
        self.not_regular: set[tuple[str, str, str]] = set()

    def put(self, repository: str, commit: str, files: dict[str, bytes]) -> None:
        self.repositories.setdefault(repository, {}).setdefault(commit, {}).update(files)

    def sources(self, repository: str):
        """The catalog source of REPOSITORY, or None when this catalog has no such repository."""
        if repository not in self.repositories:
            return None
        catalog = self

        class Source:
            def read(self, commit: str, path: str):
                catalog.reads.append((repository, commit, path))
                if catalog.fail is not None:
                    raise catalog.fail
                if (repository, commit, path) in catalog.not_regular:
                    raise catalog.entry_not_regular(f'{commit}:{path} has mode 120000')
                return catalog.repositories[repository].get(commit, {}).get(path)
        return Source()

    entry_not_regular = NotRegular  # the tests set it to dispatch_inputs.CatalogEntryNotRegular


def standard() -> Catalog:
    """The fixture's catalog: builder-pin and reviewer-pin at PIN_COMMIT of CATALOG, and the registry they name."""
    catalog = Catalog()
    catalog.put(CATALOG, PIN_COMMIT, {
        'catalog/assignments/builder-pin.json': BUILDER_BYTES,
        'catalog/assignments/reviewer-pin.json': REVIEWER_BYTES,
        REGISTRY_PATH: checked_in(REGISTRY_PATH)})
    return catalog
