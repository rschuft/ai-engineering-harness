"""Live D1 run of plan leaves E-01.3.2, E-05.4 and E-05.5 (D1 slice C; PREPARED, NOT RUN).

Not a unittest module (``discover`` never runs it). The dispatcher's side of ``tools/guest.py``'s ``d1_run`` (its
decision rule, ``guest.D1_RUN_RULE``, is fixed before any run) over the live managed root, in ONE process, on a
running guest created with ``create --provision --inference``, the provider tunnel running and the guest's forward
held (E-05.10):

    python -I -B integrations/dispatch/tests/live_d1_run.py --profile profiles/strong-windows-qemu-whpx \
        --state-dir STATE --name NAME --request REQUEST.json --project CLONE --backlog BACKLOG \
        --expected-manifest-version 2 --expected-manifest-sha256 SHA256 --expected-policy-digest DIGEST \
        --out-dir DIR [--resume OPERATION_KEY]

``D1Dispatcher`` holds the dispatcher's acts, each through the dispatch module (the two vantages of the D1 work
design, section 2): the read-only live resolution (``dispatch_inputs.resolve_live``) and the base
(``attempt_run.read_base`` of the project clone the work source reads); ``dispatch_inputs.dispatch`` under the live
promoted manifest, loaded for that dispatch through ``load_manifest`` with the decision verifier over the live
integration store (``input_decisions.verifier``; never a cached or hand-built ``ApprovedInputs``: dispatch refuses
one, MANIFEST_NOT_PROMOTED); ``attempt_run.run_attempt`` and ``resume_result`` with ``result_path.result_hook``;
``attempt_end.end_interrupted_attempt``; the conversation's delete through ``AgentServerClient``; and
``result_path.publish_result`` to the host Gitea's demo repository.

Credentials (decision 0023 section 2.2; decision 0007 point 4): the native token is read ONCE per attempt, by the
dispatcher's read at the create (``OneNativeRead``: exactly one ``get`` of ``native_token.ENTRY``, any other name or a
second read refused and counted); the same value, held in memory, is what the verifier seals, redacts and searches
with (``on_token``). A resumed run reads it once more, in its own process, only to search with it (its fingerprint
must be the attempt's). The builder bot's token is read only by ``attempt_tokens.attempt_role_token`` inside
``publish_result``, through ``AllowedEntries`` (only ``AIEH Gitea bot builder``; any write refused and counted).
Nothing here writes a credential entry.
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ACTOR = 'd1-run'
ARG_LIMIT = 131072        # Linux MAX_ARG_STRLEN: one argument of /bin/sh -c (step 0, live: 139264 bytes refused, errno 7)
STOP_KEY = 'dispatch/attempt/{attempt_id}/stop/{kind}/{code}'
STOP_FORMAT = 'ai-engineering-harness/dispatch/attempt-stop/v1'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', HERE.parent / 'dispatch_inputs.py')
AR = _load('attempt_run', HERE.parent / 'attempt_run.py')
RP = _load('result_path', HERE.parent / 'result_path.py')
AE, NT, store = di._attempt_end(), di._native_module(), di.store


class EntryRefused(PermissionError):
    """A credential-provider call the run does not make: counted, never passed through."""


class OneNativeRead:
    """The native entry, read once (decision 0023 section 2.2): the first ``get(native_token.ENTRY)`` passes through
    and the value, when it has the token's shape, is handed to ON_TOKEN as its own in-memory ``NativeToken`` (the
    verifier's sealing, redaction and search use it); any other name, a second read, a write is refused and counted."""

    def __init__(self, provider, on_token):
        self.provider, self.on_token, self.reads, self.refused = provider, on_token, [], []

    def get(self, name):
        if name != NT.ENTRY or self.reads:
            self.refused.append(('get', name))
            raise EntryRefused(f'the D1 run reads {NT.ENTRY!r} once per attempt')
        self.reads.append(name)
        entry = self.provider.get(name)
        if isinstance(entry, tuple) and len(entry) == 2 and entry[0] == NT.ENTRY_USER and NT.is_token(entry[1]):
            self.on_token(NT.NativeToken(entry[1]))
        return entry

    def set(self, *args, **kwargs):
        self.refused.append(('set', args[0] if args else None))
        raise EntryRefused('the D1 run writes no credential entry')

    def delete(self, *args, **kwargs):
        self.refused.append(('delete', args[0] if args else None))
        raise EntryRefused('the D1 run deletes no credential entry')


class AllowedEntries:
    """The credential provider read only for NAMES (the builder bot's entry); every other call refused and counted."""

    def __init__(self, provider, names):
        self.provider, self.names, self.reads, self.refused = provider, frozenset(names), [], []

    def get(self, name):
        if name not in self.names:
            self.refused.append(('get', name))
            raise EntryRefused(f'the D1 run does not read {name!r}')
        self.reads.append(name)
        return self.provider.get(name)

    def set(self, *args, **kwargs):
        self.refused.append(('set', args[0] if args else None))
        raise EntryRefused('the D1 run writes no credential entry')

    def delete(self, *args, **kwargs):
        self.refused.append(('delete', args[0] if args else None))
        raise EntryRefused('the D1 run deletes no credential entry')


class ResumeRefused(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


class D1Dispatcher:
    """The dispatcher's side of ``guest.d1_run`` (module docstring). Every dependency is injected: the live command
    (``main``) builds the managed root's; tests build fakes. LOAD_MANIFEST is called once for each dispatch, never
    cached; RESOLVE is the read-only live resolution ``(request) -> (ResolvedInputs, ApprovedInputs)``."""

    def __init__(self, *, request, integration_store, workspaces, work_source, project, load_manifest, resolve,
                 expected, provider, gitea_port, http=None, read_profile=di.read_profile_file,
                 read_artifact=di.read_profile_artifact, catalog_sources=di.harness_catalog_sources, run_kwargs=None):
        self.request, self.store, self.workspaces = request, integration_store, workspaces
        self.work_source, self.project, self.load_manifest, self.resolve = work_source, project, load_manifest, resolve
        self.expected, self.provider, self.gitea_port, self.http = dict(expected), provider, gitea_port, http
        self.read_profile, self.read_artifact, self.catalog_sources = read_profile, read_artifact, catalog_sources
        self.run_kwargs = dict(run_kwargs or {})
        self.base, self.loads, self.native_reads, self.bot_reads = None, 0, [], []

    def _sources(self, name):
        return self.work_source if name == self.request.get('repository') else None

    def prepare(self) -> dict:
        """(0): the live resolution, read only (nothing reserved), and the base. PASS iff the manifest's version and
        sha256 and the resolved policy digest are the expected ones and the base contains the accepted design."""
        resolved, manifest = self.resolve(self.request)
        design = resolved.policy_inputs['design']
        self.base = AR.read_base(self.project, repository=resolved.repository, design_commit=design['commit'])
        seen = {'manifest_version': manifest.version, 'manifest_sha256': manifest.sha256,
                'policy_digest': resolved.policy_digest}
        checks = {k: seen[k] == self.expected.get(k) for k in seen}
        sizes = self.command_sizes(resolved)
        checks['the SEED and RESULT commands fit one argument'] = max(sizes['seed'], sizes['result']) < ARG_LIMIT
        return {'verdict': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks, 'seen': seen,
                'expected': dict(self.expected), 'work': resolved.work_id, 'repository': resolved.repository,
                'stage': resolved.stage, 'ordinal': resolved.ordinal, 'design_revision': resolved.design_revision,
                'profile_digest': resolved.profile_digest, 'agent_manifest_digest': resolved.agent_manifest_digest,
                'operation_key': resolved.attempt_identity().operation_key,
                'conversation_id': store.conversation_id_for(resolved.attempt_identity().operation_key),
                'base_summary': self.base.summary(), 'command_bytes': sizes, 'base': self.base}

    def command_sizes(self, resolved) -> dict:
        """The bytes of the SEED and RESULT commands this base makes (the message and the attempt id of the planned
        attempt; the time's digits as now's): the Agent Server runs a command as /bin/sh -c <command>, one argument of
        at most ARG_LIMIT bytes (openhands-agent-server 1.60.1 bash_service.py, create_subprocess_shell)."""
        attempt = store.attempt_id_for(resolved.attempt_identity().operation_key)
        message = AR.commit_message(resolved, self.base, attempt)
        result = AR.build_result(self.base, attempt_id=attempt, message=message, when=int(time.time()))
        return {'seed': len(AR.build_seed(self.base).command.encode('utf-8')),
                'result': len(result.command.encode('utf-8')), 'limit': ARG_LIMIT}

    def dispatch(self, transport, on_token) -> dict:
        """(2): ``dispatch_inputs.dispatch`` under the manifest loaded now, for this dispatch, with the decision
        verifier; the native entry read once (OneNativeRead)."""
        manifest = self.load_manifest()
        self.loads += 1
        provider = OneNativeRead(self.provider, on_token)
        try:
            result = di.dispatch(self.request, manifest=manifest, work_sources=self._sources,
                                 integration_store=self.store, workspaces=self.workspaces, transport=transport,
                                 actor=ACTOR, read_profile=self.read_profile, read_artifact=self.read_artifact,
                                 native_credentials=provider, catalog_sources=self.catalog_sources)
        finally:
            self.native_reads.append({'reads': list(provider.reads), 'refused': list(provider.refused)})
        return {'operation_key': result.operation_key, 'attempt_id': result.attempt_id,
                'conversation_id': result.conversation_id, 'execution_ref': result.execution_ref,
                'http_status': result.http_status, 'created': result.created, 'native_token': result.native_token,
                'manifest': {'version': manifest.version, 'sha256': manifest.sha256, 'loaded_for_this_dispatch': True},
                'native_entry_reads': len(provider.reads)}

    def run(self, key, transport, inspect, pull, observe):
        return AR.run_attempt(self.store, key, transport=transport, base=self.base, actor=ACTOR, inspect=inspect,
                              pull=pull, observe=observe, reserve_result=RP.result_hook(self.store, key, actor=ACTOR),
                              read_artifact=self.read_artifact, defer_interruption_end=True, **self.run_kwargs)

    def record_stop(self, key, records) -> list:
        """Each observed stop's dispatcher record kept durably as it is observed (the review of B and C, B1):
        ``dispatch/attempt/<attempt id>/stop/<kind>/<code>``, its intent the attempt, kind and code (no text), the
        first ref in its confirmed detail. A repeat of the same kind and code is the same receipt."""
        attempt, written = store.attempt_id_for(key), []
        for record in AE.check_records(list(records)):
            stop_key = STOP_KEY.format(attempt_id=attempt, kind=record['kind'], code=record['code'])
            intent = {'format': STOP_FORMAT, 'attemptId': attempt, 'kind': record['kind'], 'code': record['code']}
            held = self.store.reserve(stop_key, intent, actor=ACTOR).reservation
            if held.state == 'reserved':
                di._mark(self.store, stop_key, 'reserved', 'dispatched', ACTOR, 'stop-observed', None)
                di._mark(self.store, stop_key, 'dispatched', 'confirmed', ACTOR, 'stop-observed',
                         {'ref': record['ref']})
            written.append(stop_key)
        return written

    def stops(self, key) -> list:
        """The attempt's recorded stops (kind, code), oldest first."""
        prefix = STOP_KEY.format(attempt_id=store.attempt_id_for(key), kind='', code='').rstrip('/')
        return [{'kind': json.loads(r.intent_json)['kind'], 'code': json.loads(r.intent_json)['code']}
                for r in self.store.attempts() if r.operation_key.startswith(prefix + '/')]

    def _no_stop(self, key):
        found = self.stops(key)
        if found:
            raise ResumeRefused('ATTEMPT_STOP_RECORDED', f'the attempt has {len(found)} recorded stop(s): no resume '
                                'and no result path (the engineering manager decides)')

    def _same_base(self, key):
        turn = AR.turn_record(self.store, key)
        if turn is None or turn['intent']['base']['commit'] != self.base.commit:
            raise ResumeRefused('RESUME_BASE_MOVED', 'the base read now is not the attempt\'s (its turn journal)')

    def resume(self, key, transport, pull, exists, observe):
        self._no_stop(key)
        self._same_base(key)
        return AR.resume_result(self.store, key, transport=transport, base=self.base, actor=ACTOR, pull=pull,
                                exists=exists, observe=observe,
                                reserve_result=RP.result_hook(self.store, key, actor=ACTOR),
                                read_artifact=self.read_artifact)

    def recorded(self, key):
        self._no_stop(key)
        self._same_base(key)
        return AR.recorded_result(self.store, key, base=self.base)

    def state(self, key) -> dict:
        if key is None:
            return {}
        attempt = store.attempt_id_for(key)
        turn = self.store.get(AR.TURN_KEY.format(attempt_id=attempt))
        result = self.store.get(AE.RESULT_KEY.format(attempt_id=attempt))
        intake = self.store.get(AR.INTAKE_KEY.format(attempt_id=attempt))
        return {'operation_key': key, 'attempt_id': attempt, 'conversation_id': store.conversation_id_for(key),
                'turn': getattr(turn, 'state', None), 'intake': getattr(intake, 'state', None),
                'result': getattr(result, 'state', None),
                'end': AE.end_record(self.store, attempt) is not None, 'stops': self.stops(key)}

    def end(self, key, transport, records, trigger):
        return AE.end_interrupted_attempt(self.store, key, transport=transport, actor=ACTOR, trigger=trigger,
                                          dispatcher_records=list(records), read_artifact=self.read_artifact)

    def delete(self, key, transport) -> int | None:
        """The conversation's delete, the dispatcher's act through AgentServerClient (teardown, not the close)."""
        resolved = di.stored_inputs(self.store, key, state='confirmed')
        client = AE._client(resolved, transport)(self.read_artifact)
        answer = client.call('DELETE', '/api/conversations/{conversation_id}',
                             params={'conversation_id': store.conversation_id_for(key)})
        return answer.get('status') if isinstance(answer, dict) else None

    def read_native(self, on_token, key=None):
        """A resumed run's one read: the entry read once, its fingerprint the attempt's (OUTBOUND_TOKEN_MISMATCH
        otherwise, before anything is searched or sent)."""
        held = []
        provider = OneNativeRead(self.provider, held.append)
        token = NT.read(provider)
        for copy in held:            # the wrapper's own copy: the caller holds TOKEN only (review of B and C, NIT 2)
            copy.drop()
        self.native_reads.append({'reads': list(provider.reads), 'refused': list(provider.refused), 'resumed': True})
        expected = AE.native_fingerprint(self.store, key) if key else None
        if expected is not None and token.fingerprint != expected:
            token.drop()
            raise di.DispatchRefused('OUTBOUND_TOKEN_MISMATCH', 'the native entry holds another token than the '
                                     'attempt\'s')
        on_token(token)

    def publish(self, key, verified, native, observations, extra_texts, report_dir) -> dict:
        self._no_stop(key)
        resolved = di.stored_inputs(self.store, key, state='confirmed')
        bot = AllowedEntries(self.provider, [RP.roles.target(RP.AT.STAGE_ROLES[resolved.stage])])
        try:
            outcome = RP.publish_result(self.store, key, verified=verified, native=native, provider=bot,
                                        target=RP.gitea_target(resolved.repository, self.gitea_port, http=self.http),
                                        actor=ACTOR, observations=observations, extra_texts=extra_texts,
                                        report_dir=report_dir)
        finally:
            self.bot_reads.append({'reads': list(bot.reads), 'refused': list(bot.refused)})
        regenerated = None
        if outcome.outcome == 'already-confirmed' and report_dir is not None \
                and not (Path(report_dir) / 'report.json').exists():
            regenerated = self.regenerate_report(key, resolved, verified, native, observations, outcome.receipt,
                                                 report_dir)
        return {'outcome': outcome.outcome, 'pushed': outcome.pushed, 'opened': outcome.opened,
                'receipt': outcome.receipt, 'report_dir': None if report_dir is None else str(report_dir),
                'bot_entry_reads': list(bot.reads), 'report_regenerated': regenerated}

    def regenerate_report(self, key, resolved, verified, native, observations, receipt, report_dir) -> dict:
        """A resumed run whose result journal is already confirmed but whose report was never written (review of B
        and C, NIT 6): the Owner report rebuilt from the receipt and the verified objects (a recorded result's test
        output and excluded paths are digests only, and the report says so), searched for the native token before it
        is written; its digests may differ from the receipt's (the observations are this run's)."""
        target = RP.gitea_target(resolved.repository, self.gitea_port, http=self.http)
        read = RP.read_verified(verified, resolved)
        refs = RP.lineage_refs(resolved, verified)
        tests_text, tests = RP.test_section(verified.tests)
        excluded_text, excluded = RP.exclusion_section(verified)
        pull = {k: receipt['pullRequest'][k] for k in ('number', 'url', 'state', 'draft')}
        report = RP.owner_report(resolved, verified, target, read, refs, tests=tests, excluded=excluded,
                                 tests_text=tests_text, excluded_text=excluded_text, pull=pull,
                                 search=(receipt.get('search') or {}).get('before'), observations=observations)
        report_json, report_md = RP.report_texts(report)
        texts = {'report-json': report_json, 'report-md': report_md}
        RP.require_not_found(RP.outbound_search(native, expected_fingerprint=AE.native_fingerprint(self.store, key),
                                                texts=texts), bundle_sha256=None, texts=texts)
        written = RP.write_report(report_dir, report_json, report_md)
        return {'written': written, 'from': 'the receipt and the verified objects', 'digest_only_texts':
                not isinstance(verified.tests.get('output'), str)}


def live_dispatcher(args, res):
    """The live managed root's dependencies (the Owner's config.yml, the integration store, the Backlog.md tool, the
    host credential provider, the host Gitea's record)."""
    planning, paths = di.planning, di.paths
    decisions = _load('input_decisions', REPO / 'integrations' / 'owner' / 'input_decisions.py')
    roles = RP.roles
    store_path = di.live_store_path(res)
    if not store_path.is_file():
        raise di.LiveUnavailable('STORE_MISSING', f'no integration store file at {store_path}')
    opened = store.open_store(store_path, apply_migrations=False)
    request = di._strict_loads(Path(args.request).read_text(encoding='utf-8'))
    source = di.PlanningWorkSource(planning.Backlog(planning.tool_argv(args.backlog), args.project),
                                   planning.Git(args.project))
    port = roles.host.read_host_record(roles.host.layout(res))['port']

    def load_manifest():
        return di.load_manifest(di.manifest_path(res), decisions=decisions.verifier(opened))

    def resolve(request_):
        return di.resolve_live(request_, res=res, work_source=source)
    expected = {'manifest_version': args.expected_manifest_version,
                'manifest_sha256': args.expected_manifest_sha256, 'policy_digest': args.expected_policy_digest}
    provider = _load('aieh_credential_provider', REPO / 'integrations' / 'credentials' /
                     'credential_provider.py').select_provider()
    return opened, D1Dispatcher(request=request, integration_store=opened, workspaces=res, work_source=source,
                                project=args.project, load_manifest=load_manifest, resolve=resolve, expected=expected,
                                provider=provider, gitea_port=port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for flag in ('--profile', '--state-dir', '--name', '--request', '--backlog', '--expected-manifest-sha256',
                 '--expected-policy-digest', '--out-dir'):
        parser.add_argument(flag, required=True)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--expected-manifest-version', required=True, type=int)
    parser.add_argument('--resume', help='the operation key of an attempt whose result step is resumed')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    guest = _load('guest', REPO / 'tools' / 'guest.py')
    opened = None
    try:
        res = di.paths.resolve()
        opened, dispatcher = live_dispatcher(args, res)
        ctx = guest.Context(args.profile, args.state_dir)
        result = guest.d1_run(ctx, args.name, dispatcher, out_dir=args.out_dir, resume=args.resume)
    except (guest.Refused, di.DispatchRefused, di.LiveUnavailable, di.paths.PathsError, di.planning.CannotRun) as exc:
        print(f'REFUSED {getattr(exc, "code", type(exc).__name__)}: {exc}', file=sys.stderr)
        return 1
    finally:
        if opened is not None:
            opened.close()
    summary = {k: result.get(k) for k in ('result', 'disposition', 'guest_may_be_destroyed', 'operation_key',
                                          'attempt', 'conversation', 'interruption', 'out', 'record')}
    summary['steps'] = [(s['step'].split(' ', 1)[0], s.get('verdict')) for s in result.get('steps') or []]
    summary['stop_conditions'] = [s.get('stop') for s in result.get('stop_conditions') or []]
    summary['native_entry_reads'] = dispatcher.native_reads
    summary['bot_entry_reads'] = dispatcher.bot_reads
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0 if result.get('result') == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
