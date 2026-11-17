"""The fixture composition root (plan leaf E-01.8; the I1 integration design, slice 11, R8, R10 and R11): one ready task
dispatched through the production resolver, admission, launch gate, attempt run, result intake and result path, on
the deterministic fixture transport, with every seam declaring the authority ``fixture``.

``run(request, ...)`` takes every seam from its caller (the command below, or a test) and does, in this order:

0. **The identity** (decision 0028; the engineering manager's ruling 4 of E-01.8): the result commit's author and
   committer are the commissioning user's configured identity, read as P-01.3's capture reads it:
   ``capture.project_config(<components.owner_host>)`` and ``capture.capture_identities(config,
   capture.OWNER_PRINCIPAL)`` (decision 0025's one-Owner shape). An absent or invalid identity is refused with
   capture's own stable codes (``COMMIT_IDENTITY_UNAVAILABLE``, ``COMMIT_IDENTITY_INVALID``,
   ``COMMIT_IDENTITY_PLACEHOLDER``) before anything is read, called or written. The project repository is the same
   configuration's (``project_repository``), and its id must be the request's repository (``PROJECT_NOT_REQUESTED``).
   A missing result target is ``RESULT_TARGET_UNCONFIGURED``, also before anything (the command's real target is
   U-06.1's).
1. **recover** (decision 0027): on ``DISPATCHER_BUSY`` (or any refusal), or any held row in its report, the run stops
   with that code and dispatches nothing.
2. **dispatch** (``dispatch_inputs.dispatch``), the native execution kind replayed with the fixture credential
   provider's public-seed token (R10).
3. **the attempt run** (``attempt_run.run_attempt``) with the production launch gate as its ``inspect``
   (``launch_gate.gate`` over the recorded inspect source), the fixture's exchange pull, the result journal's hook,
   and the identity; the result intake takes the fixture's cited recorded result (PB-4) through ``parse_result`` and
   ``intake_result`` unchanged, delivered by the fixture transport's delivery seam.
4. **the result path** (``result_path.publish_result``) to the injected Gitea target, the bot's token from the fixture
   credential provider, the native token held for the outbound search read from the same provider.

Every record the attempt causes carries the authority ``fixture`` (R11), written by the dispatcher's own writers from
the attempt's binding. ``RunRefused`` carries a stable code. Standard library only (with the harness's modules).

Usage (the command; the result target is decided at U-06.1, so it refuses until one is configured):

    <tools python> -I -B integrations/agentfixture/run.py dispatch --work-id TASK-1 --repository aieh-d1-demo
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DISPATCH = REPO / 'integrations' / 'dispatch'

ACTOR = 'agentfixture-composition'
PROFILE = 'fixture-d1-replay'
CATALOG_PIN = 'fixture-d1-implement'
STAGE = 'implement'
SOURCE = 'agentfixture catalog container-inspect (the recorded inspect source, R13)'
REFUSALS = {
    'RESULT_TARGET_UNCONFIGURED': 'no result target (the fake Gitea of U-06.1) is configured: nothing was run',
    'PROJECT_NOT_REQUESTED': 'the configured project repository is not the request\'s repository: nothing was run',
    'RECOVERY_HELD': 'recover held a row: nothing was dispatched',
}


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


AR = _load('attempt_run', DISPATCH / 'attempt_run.py')
di = AR.di
RP = _load('result_path', DISPATCH / 'result_path.py')
RR = _load('restart_recovery', DISPATCH / 'restart_recovery.py')
LG = _load('launch_gate', DISPATCH / 'launch_gate.py')
NT = di._native_module()
backend = _load('agentfixture_backend', HERE / 'backend.py')


def capture_module():
    """integrations/ownerhost/capture.py (P-01.3), loaded by path: its identity reader is reused, never mirrored."""
    return _load('aieh_ownerhost_capture', REPO / 'integrations' / 'ownerhost' / 'capture.py')


class RunRefused(Exception):
    """The run stopped with a stable CODE (capture's, the dispatcher's, recover's, or REFUSALS')."""

    def __init__(self, code: str, detail: str, **context):
        self.code, self.detail, self.context = code, detail, context
        super().__init__(f'{code}: {detail}')


def commissioning_identity(owner_host) -> tuple[tuple[str, str], object]:
    """((name, email), the project configuration) of OWNER_HOST, the ``components.owner_host`` mapping: the
    commissioning user's configured identity as capture reads and checks it, author and committer alike."""
    capture = capture_module()
    try:
        config = capture.project_config(owner_host)
        author, committer = capture.capture_identities(config, capture.OWNER_PRINCIPAL)
    except capture.CaptureRefused as exc:
        raise RunRefused(exc.code, str(exc)) from None
    match = capture.GIT_IDENTITY.fullmatch(author)
    if author != committer or match is None:     # capture_identities answers one checked identity twice
        raise RunRefused('COMMIT_IDENTITY_INVALID', 'the configured git identity is not "Name <email>"')
    return (match['name'], match['email']), config


def run(request, *, owner_host, integration_store, manifest, work_sources, workspaces, transport, core, credentials,
        pull, target, actor: str = ACTOR, read_profile=None, read_artifact=None, catalog_sources=None,
        report_dir=None) -> dict:
    """The composition (the module docstring's steps 0 to 4) for REQUEST; the run's summary, or RunRefused."""
    read_profile = read_profile or di.read_profile_file
    read_artifact = read_artifact or di.read_profile_artifact
    catalog_sources = catalog_sources or di.harness_catalog_sources
    identity, config = commissioning_identity(owner_host)                       # 0. before anything
    if target is None:
        raise RunRefused('RESULT_TARGET_UNCONFIGURED', REFUSALS['RESULT_TARGET_UNCONFIGURED'])
    if not isinstance(request, dict) or config.project_repository_id != request.get('repository'):
        raise RunRefused('PROJECT_NOT_REQUESTED', REFUSALS['PROJECT_NOT_REQUESTED'],
                         configured=config.project_repository_id)
    try:                                                                         # 1. recover first
        recovered = RR.recover(integration_store, transport=transport, actor=actor, read_artifact=read_artifact)
    except di.DispatchRefused as refusal:
        raise RunRefused(refusal.code, refusal.detail) from None
    if recovered['held']:
        held = recovered['held'][0]
        raise RunRefused(str(held.get('code') or 'RECOVERY_HELD'), REFUSALS['RECOVERY_HELD'],
                         held=[{'operationKey': h.get('operationKey'), 'code': h.get('code')}
                               for h in recovered['held']])
    try:
        result = di.dispatch(request, manifest=manifest, work_sources=work_sources,               # 2. dispatch
                             integration_store=integration_store, workspaces=workspaces, transport=transport,
                             actor=actor, read_profile=read_profile, read_artifact=read_artifact,
                             native_credentials=credentials, catalog_sources=catalog_sources)
        key = result.operation_key
        resolved = di.stored_inputs(integration_store, key, state='confirmed')
        base = AR.read_base(config.project_repository, repository=resolved.repository,
                            design_commit=AR._design(resolved)['commit'])
        source = backend.RecordedInspect(core)
        inspect = backend.Declared(LG.gate(integration_store, key, inspect_source=source, source=SOURCE, actor=actor,
                                           read_profile=read_profile, read_artifact=read_artifact), source.authority)
        outcome = AR.run_attempt(integration_store, key, transport=transport, base=base, actor=actor,   # 3. the run
                                 inspect=inspect, pull=pull, read_artifact=read_artifact, identity=identity,
                                 reserve_result=RP.result_hook(integration_store, key, actor=actor))
        summary = {'operationKey': key, 'attemptId': result.attempt_id, 'conversationId': result.conversation_id,
                   'dispatch': result.to_json(), 'outcome': outcome.outcome, 'recovered': len(recovered['entries'])}
        if outcome.outcome != 'verified':
            return summary
        published = RP.publish_result(integration_store, key, verified=outcome.result,        # 4. the result path
                                      native=NT.read(credentials), provider=credentials, target=target, actor=actor,
                                      report_dir=report_dir, read_artifact=read_artifact)
    except di.DispatchRefused as refusal:
        raise RunRefused(refusal.code, refusal.detail, **refusal.context) from None
    summary.update(published=published.outcome, receipt=published.receipt)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='The fixture composition (E-01.8): dispatch a ready task on the '
                                                 'deterministic fixture transport.')
    sub = parser.add_subparsers(dest='verb', required=True)
    verb = sub.add_parser('dispatch', help='dispatch one ready task through the production path on the fixture')
    verb.add_argument('--work-id', required=True)
    verb.add_argument('--repository', required=True)
    args = parser.parse_args(argv)
    # The demonstration's result target (a fake Gitea, its listener and its records) is decided at U-06.1 (the
    # engineering manager's ruling 4 of E-01.8): until then the command composes nothing and refuses.
    print(json.dumps({'code': 'RESULT_TARGET_UNCONFIGURED', 'detail': REFUSALS['RESULT_TARGET_UNCONFIGURED'],
                      'request': {'work_id': args.work_id, 'repository': args.repository, 'stage': STAGE,
                                  'profile': PROFILE, 'catalog_pin': CATALOG_PIN}}, sort_keys=True))
    return 2


if __name__ == '__main__':
    sys.exit(main())
