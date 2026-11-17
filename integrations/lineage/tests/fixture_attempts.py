"""Dispatched attempts answered by the Agent Server fixture's cited core, for the lineage attempt resolver's tests and
the P-03.2 example (plan leaf E-01.5). Not a test module.

``FixtureAttempts(root)`` builds, under ROOT (a throwaway directory):

- a profile directory ``profiles/fixture-lineage-example/`` whose ``agent-server/routes.json`` is the checked-in
  strong-windows-qemu-whpx route allowlist with the I1 integration design's R8 point 2 declaration added
  (``"transport": {"authority": "fixture", "kind": "loopback-fixture"}``), and the F-04.2 create template beside it;
  its declaration is the checked-in profile's, those two pins re-pointed at its own files (and the D1 stage's pin
  removed, so that every stage takes the F-04.2 template). ``live=True`` writes the allowlist unchanged instead
  (bound live). ``read_artifact`` reads these files, as the dispatcher's ``read_profile_artifact`` does from the
  repository;
- ``attempt(store, work_id, ...)``: one typed attempt reserved, dispatched and confirmed in the integration store
  through the store's own API, with exactly the records the dispatcher writes (``ResolvedInputs.intent()`` with the
  admission policy ``dispatch_inputs.admission_policy`` derives from that declaration; the ``dispatched`` detail;
  the create receipt ``dispatch_inputs.create_receipt`` makes of the core's own answer to the create, which the core
  receives as ``POST /api/conversations`` with the reserved conversation id);
- ``seam(transport)``: TRANSPORT (the core, or a test's wrapper of it) as the transport of the attempts' client,
  declaring the authority their allowlist binds them to (``fixture``, or ``live`` with ``live=True``): the client
  requires the two equal (the I1 integration design, R8 point 4; the engineering manager's ruling A of E-01.8).

No dispatch is run (the resolution, the manifest and the admission are E-01.2's, tested there): the records are
built from the same constructors, so that ``dispatch_inputs.stored_inputs`` reads them as the dispatcher's.
"""
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', REPO / 'integrations' / 'dispatch' / 'dispatch_inputs.py')
AC = _load('agentfixture_core', REPO / 'integrations' / 'agentfixture' / 'core.py')
store_mod = di.store

PROFILE = 'fixture-lineage-example'
CHECKED_IN = REPO / 'profiles' / 'strong-windows-qemu-whpx'
TRANSPORT = {'authority': 'fixture', 'kind': 'loopback-fixture'}      # R8 point 2
ACTOR = 'e-01.5-lineage-test'
REPOSITORY = 'demo-app'
CATALOG_PIN = {'id': 'builder-pin', 'repository': 'aieh-catalog', 'commit': '1' * 40, 'manifest_sha256': '2' * 64}


class Seam:
    """A transport declaring its authority (R8 point 3): it calls TRANSPORT as it is."""

    def __init__(self, transport, authority):
        self.transport, self.authority = transport, authority

    def __call__(self, method, path, body=None, **kwargs):
        return self.transport(method, path, body, **kwargs)


class FixtureAttempts:
    def __init__(self, root, live=False):
        self.root = Path(root)
        self.live = live
        directory = self.root / 'profiles' / PROFILE / 'agent-server'
        directory.mkdir(parents=True, exist_ok=True)
        routes = json.loads((CHECKED_IN / 'agent-server' / 'routes.json').read_text(encoding='utf-8'))
        if not live:
            routes['transport'] = dict(TRANSPORT)
        routes_raw = (json.dumps(routes, indent=2) + '\n').encode('utf-8')
        template_raw = (CHECKED_IN / 'agent-server' / 'conversation-create.json').read_bytes()
        (directory / 'routes.json').write_bytes(routes_raw)
        (directory / 'conversation-create.json').write_bytes(template_raw)
        declared = json.loads((CHECKED_IN / 'profile.json').read_text(encoding='utf-8'))
        server = declared['provisioning']['agent_server']
        server.pop(di.STAGE_TEMPLATE_KEY, None)
        server['admission']['routes'] = {**server['admission']['routes'],
                                         'path': f'profiles/{PROFILE}/agent-server/routes.json',
                                         'sha256': hashlib.sha256(routes_raw).hexdigest()}
        server['fixture'] = {**server['fixture'], 'path': f'profiles/{PROFILE}/agent-server/conversation-create.json',
                             'sha256': hashlib.sha256(template_raw).hexdigest()}
        self.declared = declared
        self.profile_raw = (json.dumps(declared, indent=2) + '\n').encode('utf-8')
        (self.root / 'profiles' / PROFILE / 'profile.json').write_bytes(self.profile_raw)
        self.admission = di.admission_policy(declared, PROFILE)

    def read_artifact(self, path):
        return di.read_profile_artifact(path, repo_root=self.root)

    def seam(self, transport):
        return Seam(transport, di.LIVE if self.live else di.FIXTURE)

    def resolved(self, work_id, *, change, design_commit, outcome_ref, ordinal=1, stage='implement'):
        """The dispatcher's resolved record of one attempt (``ResolvedInputs``), built from its constructors."""
        design = {'repository': REPOSITORY, 'change': change, 'commit': design_commit}
        profile = {'id': PROFILE, 'sha256': hashlib.sha256(self.profile_raw).hexdigest()}
        policy = di.policy_inputs({'id': REPOSITORY}, stage, design, profile, dict(CATALOG_PIN),
                                  copy.deepcopy(self.admission))
        policy_json = di._canonical(policy)
        design_revision = f'{store_mod.DESIGN_REVISION_PREFIX}{change}@{design_commit}'
        probe = store_mod.AttemptIdentity(work_id=work_id, design_revision=design_revision, stage=stage,
                                          ordinal=ordinal, profile_digest=profile['sha256'], planned_workspace='x',
                                          policy_digest=hashlib.sha256(policy_json.encode()).hexdigest())
        attempt_id = store_mod.attempt_id_for(probe.operation_key)
        return di.ResolvedInputs(
            work_id=probe.work_id, repository=REPOSITORY, stage=stage, ordinal=ordinal,
            design_revision=design_revision, profile=PROFILE, profile_digest=profile['sha256'],
            catalog_pin=CATALOG_PIN['id'], agent_manifest_digest='3' * 64,
            planned_workspace=di.planned_workspace(REPOSITORY, probe.work_id, attempt_id),
            policy_digest=hashlib.sha256(policy_json.encode()).hexdigest(), policy_inputs_json=policy_json,
            manifest_version=1, manifest_sha256='4' * 64, outcome_ref=outcome_ref)

    def attempt(self, integration_store, core, work_id, *, change, design_commit, outcome_ref, confirm=True):
        """One attempt reserved, dispatched and (CONFIRM) confirmed by the core's answer to its create; its operation
        key and conversation id."""
        resolved = self.resolved(work_id, change=change, design_commit=design_commit, outcome_ref=outcome_ref)
        key = resolved.attempt_identity().operation_key
        integration_store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor=ACTOR)
        cid = store_mod.conversation_id_for(key)
        integration_store.transition(key, 'dispatched', actor=ACTOR, reason='create', expected_from='reserved',
                                     detail={'format': di.DISPATCHED_FORMAT, 'conversationId': cid,
                                             'route': dict(di.CREATE_ROUTE)})
        if confirm:
            answer = core('POST', '/api/conversations', {'conversation_id': cid})
            receipt = di.create_receipt(answer, cid)
            assert receipt is not None, answer
            integration_store.transition(key, 'confirmed', actor=ACTOR, reason='created', expected_from='dispatched',
                                         detail=receipt)
        return key, cid
