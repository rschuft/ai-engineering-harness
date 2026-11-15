"""A synthetic catalog repository for the resolver's tests (plan leaf E-05.3).

``Catalog`` holds the blobs of commits of catalog repositories in memory and answers as a
``dispatch_inputs.CatalogSource`` does: the bytes at a commit and path, or None when the commit or
the blob is absent. ``standard()`` is the fixture's catalog: the builder and reviewer pins'
agent assignments at ``PIN_COMMIT`` of ``CATALOG``, with the provider registry entry and the
create templates they name (the checked-in files' bytes). It reads nothing but those checked-in
files, and no git.
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
D1_TEMPLATE_PATH = 'profiles/strong-windows-qemu-whpx/agent-server/d1-create.json'
FIXTURE_TEMPLATE_PATH = 'profiles/strong-windows-qemu-whpx/agent-server/conversation-create.json'


def checked_in(path: str) -> bytes:
    return (REPO / path).read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assignment(pin: str, *, provider=REGISTRY_PATH, template=D1_TEMPLATE_PATH, skills=(), acp_server='claude-code',
               provider_sha=None, template_sha=None, change=None) -> bytes:
    """The bytes of an agent-assignment/v1 for PIN naming the checked-in files PROVIDER and TEMPLATE by their
    sha256 (unless PROVIDER_SHA or TEMPLATE_SHA is given); CHANGE, then, edits the parsed object."""
    data = {'format': FORMAT, 'id': pin,
            'provider': {'path': provider, 'sha256': provider_sha or sha256(checked_in(provider)),
                         'acp_server': acp_server},
            'create_template': {'path': template, 'sha256': template_sha or sha256(checked_in(template))},
            'skills': list(skills)}
    if change is not None:
        change(data)
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


BUILDER_BYTES = assignment('builder-pin')
REVIEWER_BYTES = assignment('reviewer-pin', template=FIXTURE_TEMPLATE_PATH)
BUILDER_SHA = sha256(BUILDER_BYTES)
REVIEWER_SHA = sha256(REVIEWER_BYTES)


class Catalog:
    """Commits of catalog repositories, in memory: ``{repository: {commit: {path: bytes}}}``."""

    def __init__(self):
        self.repositories: dict[str, dict[str, dict[str, bytes]]] = {}
        self.reads: list[tuple[str, str, str]] = []
        self.fail: Exception | None = None

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
                return catalog.repositories[repository].get(commit, {}).get(path)
        return Source()


def standard() -> Catalog:
    """The fixture's catalog: builder-pin and reviewer-pin at PIN_COMMIT of CATALOG, and the files they name."""
    catalog = Catalog()
    catalog.put(CATALOG, PIN_COMMIT, {
        'catalog/assignments/builder-pin.json': BUILDER_BYTES,
        'catalog/assignments/reviewer-pin.json': REVIEWER_BYTES,
        REGISTRY_PATH: checked_in(REGISTRY_PATH),
        D1_TEMPLATE_PATH: checked_in(D1_TEMPLATE_PATH),
        FIXTURE_TEMPLATE_PATH: checked_in(FIXTURE_TEMPLATE_PATH)})
    return catalog
