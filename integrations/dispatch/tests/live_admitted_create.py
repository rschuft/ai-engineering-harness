"""Live check of the admitted create (plan leaf E-01.2.2 slice (b); TEST ONLY).

Not a unittest module (``discover`` never runs it). It sends one admitted create to a running
drill guest and compares the container the guest's Agent Server created with the admitted
request:

    python -I -B integrations/dispatch/tests/live_admitted_create.py \
        --profile profiles/strong-windows-qemu-whpx --state-dir STATE --name NAME [--out FILE]

The request is built exactly as slice (a)'s positive control
``test_the_checked_in_profile_declaration_admits_when_operational`` builds it: the E-01.2.1
fixture (the design repository, Backlog.md's recorded readiness, a throwaway store and
manifest, a managed root under the default TEMP) and the real ``strong-windows-qemu-whpx``
declaration with only ``status.operational`` set to true in a throwaway copy, with its pinned
create template and route allowlist. The dispatcher's order runs unchanged: resolve,
reserve_attempt, admit, send_create. Since E-01.3.1 ``send_create`` first reads ``GET
/server_info`` (decision 0001's preconditions P1 to P5) and then sends the create:
``PreconditionThenCreate`` answers the first over the drill's API channel (unauthenticated, as
conversation-smoke reads it) and passes the create to ``tools/guest.py``'s
``GuestCreateTransport``: one POST to the guest's Agent Server, as agent over the instance's
management SSH channel (no new host port, guestfwd or share). NOT RUN since that change (E-01.3.1
ran no live act). ``tools/guest.py drill`` then
reads the root conversation facts and checks the created container's mounts, caps and runtime
against the admitted ones, deletes the conversation, and writes the drill record.
"""
import argparse
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


class PreconditionThenCreate:
    """send_create's transport for the live check: ``GET /server_info`` over the drill's API
    channel, every other call (the one create) through ``create`` (GuestCreateTransport)."""

    def __init__(self, guest, api, create):
        self.guest, self.api, self.create = guest, api, create

    def __call__(self, method, path, body):
        if (method, path) == ('GET', '/server_info'):
            response, = self.guest._call(self.api, {'method': 'GET', 'path': '/server_info', 'auth': False})
            return response
        return self.create(method, path, body)


def admitted_create(transport):
    """The dispatcher's order on the fixture, the real declaration in a throwaway copy; the
    admitted request (AdmittedCreate.to_json) after send_create sent the create through
    ``transport`` once."""
    adm = _load('test_dispatch_admission', HERE / 'test_dispatch_admission.py')

    class Live(adm.AdmissionFixture):
        def runTest(self):
            pass

    Live.setUpClass()
    case = Live()
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
        data['bindings'][0]['profiles'].append(REAL_PROFILE)
        manifest = case.write_manifest(data, case.fresh('live'))
        resolved = case.resolve(case.request(profile=REAL_PROFILE), manifest)
        case.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(),
                                   actor='e-01.2.2b-live-check')
        admitted = case.admit(resolved, manifest)
        adm.di.send_create(admitted, resolved=resolved, workspaces=case.workspaces,
                           transport=transport)
        out = admitted.to_json()
        out['admission_caps'] = resolved.policy_inputs['admission']['caps']
        return out
    finally:
        case.doCleanups()
        Live.tearDownClass()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--profile', required=True)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    guest = _load('guest', REPO / 'tools' / 'guest.py')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        ctx = guest.Context(args.profile, args.state_dir)
        result = guest.drill(ctx, args.name, 'admitted-create', out_path=args.out,
                             admitted_fn=lambda transport, api: admitted_create(
                                 PreconditionThenCreate(guest, api, transport)))
    except guest.Refused as exc:
        print(f'REFUSED {exc.code}: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get('result') == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
