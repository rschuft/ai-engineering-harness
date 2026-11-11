"""Live custody probe of plan leaf E-01.3.3 (TEST ONLY; PREPARED, NOT RUN).

Not a unittest module (``discover`` never runs it). On a running provisioned guest it runs
``tools/guest.py``'s ``custody_probe`` under its decision rule (``guest.CUSTODY_PROBE_RULE``, fixed
before any run), supplying the dispatch chain for step (5):

    python -I -B integrations/dispatch/tests/live_custody_probe.py \
        --profile profiles/strong-windows-qemu-whpx --state-dir STATE --name NAME [--out FILE] \
        [--rotate-report FILE]

Step (5) builds two attempts exactly as ``live_admitted_create.py`` builds its request: the E-01.2.1
fixture (a throwaway design repository, Backlog.md's recorded readiness, a throwaway store and
manifest) and the real ``strong-windows-qemu-whpx`` declaration with only ``status.operational`` set
in a throwaway copy. ``dispatch`` sends one ``implement`` and one ``review`` create through the
dispatch module's live transport (``GuestTransport`` on the probe's ``GuestApi``), and each confirmed
attempt is delivered its stage's token by ``attempt_role_token`` from the Owner account's credential
provider, read only (``ReadOnlyProvider`` counts and refuses any write: a write is a stop), checked
against the live host Gitea's ``GET /api/v1/token``. The two conversations are deleted through the
same client. Records carry fingerprints only; the delivered tokens' fingerprints go to step (3).

``--rotate-report FILE`` adds the optional administrative-lifecycle step, listed apart from the
routine rule: FILE is the JSON report the Owner's own ``gitea_roles.py rotate ROLE`` printed before
this run (a separate Owner act). It passes when that report shows the old token refused (revoked, or
found already refused) with its receipt read back, and this run delivered the new token
(``admin_lifecycle_verdict``).
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
REAL_PROFILE = 'strong-windows-qemu-whpx'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


class ReadOnlyProvider:
    """The credential provider, read only: ``get`` passes through; ``set`` and ``delete`` are counted and refused
    (the probe's stop condition: no credential-provider write outside the administrative lifecycle)."""

    def __init__(self, provider):
        self.provider, self.writes = provider, 0

    def get(self, name):
        return self.provider.get(name)

    def set(self, *args, **kwargs):
        self.writes += 1
        raise PermissionError('the custody probe writes no credential entry')

    def delete(self, *args, **kwargs):
        self.writes += 1
        raise PermissionError('the custody probe deletes no credential entry')


def deliver_attempts(transport, provider, port, http=None):
    """Step (5): one implement and one review attempt dispatched through TRANSPORT on the fixture with the real
    declaration, each delivered its stage's token; both conversations deleted. Returns the records, the
    fingerprints by role, the refusals and the provider writes."""
    at = _load('attempt_tokens', HERE.parent / 'attempt_tokens.py')
    adm = _load('test_dispatch_admission', HERE / 'test_dispatch_admission.py')
    di = adm.di
    readonly = provider if isinstance(provider, ReadOnlyProvider) else ReadOnlyProvider(provider)

    class Live(adm.AdmissionFixture):
        def runTest(self):
            pass

    Live.setUpClass()
    case = Live()
    out = {'records': [], 'fingerprints': {}, 'refused': [], 'deleted': {}}
    try:
        case.setUp()
        declared = json.loads((REPO / 'profiles' / REAL_PROFILE / 'profile.json').read_bytes())
        declared['status']['operational'] = True
        directory = case.profiles / REAL_PROFILE
        directory.mkdir()
        (directory / 'profile.json').write_bytes(json.dumps(declared, indent=2).encode('utf-8'))
        adm.base.write_agent_server(directory)
        data = case.manifest_data()
        data['profiles'].append({'id': REAL_PROFILE, 'sha256': case.profile_sha(REAL_PROFILE)})
        data['designs'].append({'repository': 'other-app', 'change': adm.base.CHANGE, 'commit': case.commit})
        for binding in data['bindings']:
            binding['profiles'].append(REAL_PROFILE)
        manifest = case.write_manifest(data, case.fresh('live-custody'))
        requests = [case.request(profile=REAL_PROFILE),
                    case.request(profile=REAL_PROFILE, repository='other-app', stage='review',
                                 catalog_pin='reviewer-pin')]
        sources = {'demo-app': case.sources['demo-app'], 'other-app': case.sources['demo-app']}
        for request in requests:
            try:
                result = di.dispatch(request, manifest=manifest, work_sources=sources.get,
                                     integration_store=case.store, workspaces=case.workspaces, transport=transport,
                                     actor='e-01.3.3-custody-probe', read_profile=case.read_profile,
                                     read_artifact=case.read_artifact)
            except di.DispatchRefused as exc:
                out['refused'].append({'stage': request['stage'], 'code': exc.code})
                continue
            try:
                with at.attempt_role_token(case.store, result.operation_key, provider=readonly, port=port,
                                           http=http) as delivery:
                    record = delivery.record()
                out['records'].append(record)
                out['fingerprints'][record['role']] = record['fingerprint']
            except di.DispatchRefused as exc:
                out['refused'].append({'stage': request['stage'], 'code': exc.code})
            finally:
                routes = (directory / 'agent-server' / 'routes.json').read_bytes()
                client = di.AgentServerClient(routes, transport, routes_sha256=hashlib.sha256(routes).hexdigest())
                answer = client.call('DELETE', '/api/conversations/{conversation_id}',
                                     params={'conversation_id': result.conversation_id})
                out['deleted'][request['stage']] = answer.get('status') if isinstance(answer, dict) else None
        out['provider_writes'] = readonly.writes
        return out
    finally:
        case.doCleanups()
        Live.tearDownClass()


def admin_lifecycle_verdict(report, records):
    """The optional administrative-lifecycle step: the Owner's rotate report shows the old token refused (revoked
    now, or found already refused) and its receipt read back, and this run delivered the new token (its
    fingerprint, not the old one's)."""
    if not isinstance(report, dict):
        return 'UNKNOWN', {'reason': 'no rotate report'}
    revocation = report.get('revocation')
    refused = (isinstance(revocation, dict) and revocation.get('revoked') is True) or \
        (isinstance(revocation, str) and revocation.startswith('already refused'))
    delivered = [r for r in records or [] if r.get('role') == report.get('role')]
    detail = {'role': report.get('role'), 'old_fingerprint': report.get('old_fingerprint'),
              'new_fingerprint': report.get('new_fingerprint'), 'old_on_repository_read':
              report.get('old_on_repository_read'), 'receipt_read_back': (report.get('receipt') or {}).get('read_back'),
              'delivered': [r.get('fingerprint') for r in delivered]}
    if not delivered or report.get('new_fingerprint') is None:
        return 'UNKNOWN', detail
    ok = refused and report.get('old_on_repository_read') == 401 and detail['receipt_read_back'] is True and \
        [r.get('fingerprint') for r in delivered] == [report['new_fingerprint']] and \
        report.get('old_fingerprint') != report['new_fingerprint']
    return ('PASS' if ok else 'FAIL'), detail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--profile', required=True)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--out')
    parser.add_argument('--rotate-report')
    args = parser.parse_args(argv)
    guest = _load('guest', REPO / 'tools' / 'guest.py')
    roles = _load('aieh_gitea_roles', REPO / 'integrations' / 'gitea' / 'gitea_roles.py')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    rotate_report = json.loads(Path(args.rotate_report).read_text(encoding='utf-8')) if args.rotate_report else None
    try:
        host = roles.host
        port = host.read_host_record(host.layout(host.paths.resolve()))['port']
        provider = ReadOnlyProvider(host.credential_provider())
        memo = {}

        def attempts_fn(transport):
            memo['attempts'] = deliver_attempts(transport, provider, port)
            return memo['attempts']
        ctx = guest.Context(args.profile, args.state_dir)
        result = guest.custody_probe(ctx, args.name, attempts_fn=attempts_fn, out_path=args.out)
    except guest.Refused as exc:
        print(f'REFUSED {exc.code}: {exc}', file=sys.stderr)
        return 1
    if rotate_report is not None:
        verdict, detail = admin_lifecycle_verdict(rotate_report, (memo.get('attempts') or {}).get('records'))
        result['administrative_lifecycle'] = {'verdict': verdict, 'detail': detail,
                                              'note': 'optional, not part of the routine rule'}
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get('result') == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
