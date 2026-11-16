"""Step 0 of the D1 live run: the result path's mechanics rehearsed once (D1 slice C; the engineering manager's ruling
R4; TEST ONLY; PREPARED, NOT RUN).

Not a unittest module (``discover`` never runs it). ONE process, ONE disposable guest (``create --provision``; it
refuses an instance name that exists and destroys, in ``finally``, only the instance it created), ONE disposable
fixture conversation (the profile's pinned F-04.2 fixture: no token, no message, no model call, no repository
content), a throwaway integration store (E-05.9's native fixture: a synthetic token, a fake Agent Server, nothing
reserved in the live store):

    python -I -B integrations/dispatch/tests/live_step0_rehearsal.py --profile profiles/strong-windows-qemu-whpx \
        --state-dir STATE --name NAME --out-dir DIR

It runs SEED of a synthetic tree of the demo repository's size (``synthetic_trees``), a synthetic edit made by a
dispatcher command, RESULT on the seeded tree with its exchange delivery, ``exchange_pull`` and
``verify_pulled_bundle`` (the retained verifier), the host's intake (``attempt_run.intake_result``: the commit-id
equality and the tree policy) and RESULT again without a delivery (a resumed step makes the same commit), every
command through the dispatcher's own client (``AgentServerClient`` on the profile's pinned route allowlist) and its
live transport (``GuestTransport`` over ``GuestApi``). It records what no fake can show: git and python in the
container; the bash route's output (line endings, a large output whole or cut, a switch spelling unaltered); the
argument limit (the Agent Server runs a command as ``/bin/sh -c <command>``, ``asyncio.create_subprocess_shell``
in openhands-agent-server 1.60.1 ``bash_service.py``, so one command is one argument of at most MAX_ARG_STRLEN,
131072 bytes on Linux); the delivery's exclusive ``os.link``; the ``:(top,exclude,literal)`` pathspecs and
``update-index --index-info`` (the synthetic edit writes a ``.claude`` file and changes a file under ``backlog/``);
and the fixture conversation's runtime status after its create (attempt_run's ``available``).

The synthetic edit and the probes are commands of test-only builders (``test-step0-edit``, ``test-step0-probe``),
admitted only here through ``dispatch_inputs.allow_test_builders`` (the A-slice override, reachable from tests/ only,
D1 review S6); the production builders SEED and RESULT are attempt_run's own. Records hold digests, sizes, counts and
the probes' own output (no repository content: the tree is synthetic).
"""
import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROFILE_ID = 'strong-windows-qemu-whpx'
MAX_ARG_STRLEN = 131072
EDIT_BUILDER, PROBE_BUILDER = 'test-step0-edit', 'test-step0-probe'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


tar = _load('test_attempt_run', HERE / 'test_attempt_run.py')
di, AR, store_mod = tar.di, tar.AR, tar.store_mod
di.allow_test_builders(EDIT_BUILDER, PROBE_BUILDER)        # this rehearsal only (tests/; D1 review S6)


@di.command_builder(EDIT_BUILDER)
def build_edit(repository):
    """The synthetic edit, in the seeded tree: one file changed, one added, one deleted, a .claude file written (left
    out by RESULT's pathspec exclusion) and a file under backlog/ changed (put back by update-index --index-info)."""
    script = ('import os, sys\n'
              'w = sys.argv[1]\n'
              'open(os.path.join(w, "README.md"), "a").write("step 0: a synthetic edit\\n")\n'
              'os.makedirs(os.path.join(w, "aieh_d1_demo"), exist_ok=True)\n'
              'open(os.path.join(w, "aieh_d1_demo", "step0.py"), "w").write("VALUE = 0\\n")\n'
              'os.remove(os.path.join(w, "synthetic", "file-00.txt"))\n'
              'os.makedirs(os.path.join(w, ".claude"), exist_ok=True)\n'
              'open(os.path.join(w, ".claude", "settings.local.json"), "w").write("{}\\n")\n'
              'task = [n for n in os.listdir(os.path.join(w, "backlog", "tasks"))][0]\n'
              'open(os.path.join(w, "backlog", "tasks", task), "a").write("an edit RESULT puts back\\n")\n'
              'print("AIEH-STEP0 edited")\n')
    return {'command': f"python -c '{script}' '{AR.workspace_of(repository)}'", 'timeout': 60}


@di.command_builder(PROBE_BUILDER)
def build_probe(text, timeout=120):
    """A fixed probe command (the rehearsal's own texts only)."""
    return {'command': text, 'timeout': timeout}


PROBES = {
    'tools': 'command -v git python python3; git --version; python --version; python3 --version; id -u; pwd',
    'line-endings': "printf 'lf\\ncrlf\\r\\nend'; printf ' tRuE '",
    'large-output': 'python -c "import sys; sys.stdout.write(\'0123456789abcdef\' * 65536)"',   # 1 MiB
}


def synthetic_trees(work_id, change):
    """The demo repository's shape with synthetic content of its size (about 25 KB in 16 files plus filler: the
    commands' sizes are the measured ones of the real demo's, SEED about 17 KB and RESULT about 58 KB)."""
    filler = {}
    seed = b'step0'
    for n in range(12):
        lines = []
        for _ in range(24):
            seed = hashlib.sha256(seed).digest()
            lines.append(seed.hex()[:48] + ' synthetic line of the step 0 tree')
        filler[f'synthetic/file-{n:02d}.txt'] = ('\n'.join(lines) + '\n').encode('ascii')
    return tar.demo_trees(work_id, change, extra=filler)


def argv_probe(size):
    """A command of SIZE bytes: a no-op holding filler, then one line naming the size."""
    head, tail = ": '", f"'; echo AIEH-STEP0 argv {size} ok"
    return head + 'a' * (size - len(head) - len(tail)) + tail


def rehearse(*, transport, raw, pull, routes_bytes, fixture_body, workdir):
    """The rehearsal against one fixture conversation: TRANSPORT the dispatcher's live transport, RAW(method, path,
    body) the probe vantage (the fixture's create, runtime read and delete), PULL(name) tools/guest.py exchange_pull.
    Returns the record; raises nothing it can record."""
    out = {'format': 'ai-engineering-harness/dispatch/step0-rehearsal/v1', 'steps': []}
    client = di.AgentServerClient(routes_bytes, transport, routes_sha256=hashlib.sha256(routes_bytes).hexdigest())
    cid = fixture_body['conversation_id']

    def record(name, ok, **detail):
        out['steps'].append(dict({'step': name, 'ok': bool(ok)}, **detail))
        return ok

    def command(made):
        answer = client.call('POST', AR.PROXY, params={'conversation_id': cid, 'tail': di.COMMAND_TAIL}, body=made)
        body = answer.get('body') if isinstance(answer.get('body'), dict) else {}
        return answer, body

    fixture = tar.OracleAttempt('dispatch_native')
    tar.OracleAttempt.setUpClass()
    fixture.setUp()
    created = False
    try:
        result = fixture.dispatch_native()                     # a throwaway store; a fake Agent Server
        key = result.operation_key
        attempt_id = store_mod.attempt_id_for(key)
        resolved = di.stored_inputs(fixture.store, key, state='confirmed')
        change = AR._design(resolved)['change']
        commits = tar.make_repository(Path(workdir) / 'synthetic', synthetic_trees(resolved.work_id, change))
        base = AR.read_base(Path(workdir) / 'synthetic', repository=resolved.repository, design_commit=commits['C2'])
        base = dataclasses.replace(base, design_commit=AR._design(resolved)['commit'])
        tar.confirm_turn(fixture.store, key, base, text='step 0: no message is sent')
        when = AR.attempt_time(fixture.store, key)
        message = AR.commit_message(resolved, base, attempt_id)
        seed, edit = AR.build_seed(base), build_edit(resolved.repository)
        made = AR.build_result(base, attempt_id=attempt_id, message=message, when=when)
        again = AR.build_result(base, attempt_id=attempt_id, message=message, when=when, deliver=False)
        sizes = {'seed': len(seed.command.encode()), 'result': len(made.command.encode()), 'limit': MAX_ARG_STRLEN}
        record('the commands built (synthetic, demo-size)', all(v < MAX_ARG_STRLEN for k, v in sizes.items()
                                                                 if k != 'limit'), sizes=sizes,
               base={'files': len(base.files), 'bundle_bytes': len(base.bundle), 'seed_sha256': base.seed_sha256})
        answer = raw('POST', '/api/conversations', fixture_body)
        created = isinstance(answer.get('status'), int) and 200 <= answer['status'] < 300
        record('the fixture conversation created', created, status=answer.get('status'))
        if not created:
            return out
        runtime = raw('GET', f'/api/conversations/{cid}/runtime', None)
        status = (runtime.get('body') or {}).get('runtime_status') if isinstance(runtime.get('body'), dict) else None
        record('its runtime status after the create is available (attempt_run RUNTIME_SERVING)',
               status == AR.RUNTIME_SERVING, observed=runtime.get('body'))
        for name, text in PROBES.items():
            answer, body = command(build_probe(text))
            stdout = body.get('stdout') if isinstance(body.get('stdout'), str) else ''
            detail = {'status': answer.get('status'), 'exit_code': body.get('exit_code'), 'chars': len(stdout),
                      'sha256': hashlib.sha256(stdout.encode('utf-8', 'surrogatepass')).hexdigest()}
            if name == 'large-output':
                ok = stdout == '0123456789abcdef' * 65536
                detail['whole'] = ok
            elif name == 'line-endings':
                detail['repr'] = repr(stdout)
                ok = answer.get('status') == 200 and body.get('exit_code') == 0
                detail['crlf_kept'], detail['switch_spelling_kept'] = '\r\n' in stdout, 'tRuE' in stdout
                # review of B and C, S4: the fixture registers no secret, so no masking applies to it here
                detail['switch_spelling_kept_note'] = 'vacuous: the fixture conversation registers no secret'
            else:
                detail['stdout'] = stdout[:2000]
                ok = body.get('exit_code') == 0 and 'git version' in stdout and 'Python 3' in stdout
            record(f'probe {name}', ok, **detail)
        for size in (MAX_ARG_STRLEN - 4096, MAX_ARG_STRLEN + 8192):
            try:
                answer, body = command(build_probe(argv_probe(size)))
                ran = f'AIEH-STEP0 argv {size} ok' in str(body.get('stdout'))
                record(f'a command of {size} bytes', ran if size < MAX_ARG_STRLEN else True, ran=ran,
                       status=answer.get('status'), exit_code=body.get('exit_code'),
                       stderr=str(body.get('stderr'))[-300:])
            except Exception as exc:  # noqa: BLE001 - recorded: the argument limit is what is observed
                record(f'a command of {size} bytes', size >= MAX_ARG_STRLEN, error=type(exc).__name__,
                       code=getattr(exc, 'code', None))
        answer, body = command(seed)
        want = f'AIEH-SEED ok {base.seed_sha256} {len(base.files)}'
        if not record('SEED', want in str(body.get('stdout')).splitlines() and body.get('exit_code') == 0,
                      status=answer.get('status'), exit_code=body.get('exit_code')):
            return out
        answer, body = command(edit)
        record('the synthetic edit', 'AIEH-STEP0 edited' in str(body.get('stdout')), exit_code=body.get('exit_code'))
        answer = client.call('POST', AR.PROXY, params={'conversation_id': cid, 'tail': di.COMMAND_TAIL}, body=made)
        try:
            printed = AR.parse_result(answer)
        except di.DispatchRefused as exc:
            record('RESULT', False, refused=exc.to_json(), delivered=answer.get('delivered'))
            return out
        reasons = sorted({e['reason'] for e in printed['excluded']})
        # review of B and C, S4: the step passes only when both exclusion paths ran
        record('RESULT, delivered (os.link, exclusive)', 'forbidden-name' in reasons and 'protected-dir' in reasons,
               delivered=printed['delivered'], excluded={'count': printed['excluded_digest']['count'],
                                                          'reasons': reasons},
               pathspec_exclusion='forbidden-name' in reasons, index_info='protected-dir' in reasons,
               tests=printed['tests']['status'], commit=printed['commit'])
        try:
            pulled = pull(printed['delivered']['name'])
        except Exception as exc:  # noqa: BLE001 - recorded in the record (S4), never raised past it
            record('exchange pull and the retained verifier', False, error=type(exc).__name__,
                   code=str(getattr(exc, 'code', ''))[:64])
            return out
        if not record('exchange pull and the retained verifier', pulled.get('result') == 'pulled',
                      staged=pulled.get('staged'), verified=(pulled.get('bundle') or {}).get('verified'),
                      pull_result=pulled.get('result')):
            return out
        try:
            verified = AR.intake_result(fixture.store, key, base=base, printed=printed, pulled=pulled,
                                        message=message, when=when)
        except di.DispatchRefused as exc:
            record('the host intake: the commit-id equality and the tree policy', False, refused=exc.to_json())
            return out
        record('the host intake: the commit-id equality and the tree policy', verified.commit == printed['commit'],
               result=verified.to_json())
        answer = client.call('POST', AR.PROXY, params={'conversation_id': cid, 'tail': di.COMMAND_TAIL}, body=again)
        try:
            reprinted = AR.parse_result(answer, delivered_expected=False)
            record('RESULT again without a delivery: the same commit', reprinted['commit'] == printed['commit'],
                   commit=reprinted['commit'])
        except di.DispatchRefused as exc:
            record('RESULT again without a delivery: the same commit', False, refused=exc.code)
        answer = client.call('POST', AR.PROXY, params={'conversation_id': cid, 'tail': di.COMMAND_TAIL}, body=made)
        record('a second delivery to the same name is refused (EXISTS)',
               (answer.get('delivered') or {}).get('error') == 'EXISTS', delivered=answer.get('delivered'))
        return out
    finally:
        if created:
            deleted = raw('DELETE', f'/api/conversations/{cid}', None)
            record('the fixture conversation deleted', deleted.get('status') in (200, 204), status=deleted.get('status'))
        fixture.doCleanups()
        tar.OracleAttempt.tearDownClass()
        out['result'] = 'PASS' if out['steps'] and all(s['ok'] for s in out['steps']) else 'FAIL'


def write(out_dir, name, data):
    with open(Path(out_dir) / name, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(data, indent=2, sort_keys=True, default=str) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for flag in ('--profile', '--state-dir', '--name', '--out-dir'):
        parser.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if not out_dir.is_dir() or any(out_dir.iterdir()):
        print(f'{out_dir} is not an existing empty directory', file=sys.stderr)
        return 2
    g = _load('guest', REPO / 'tools' / 'guest.py')
    gt = g.dispatch_transport()
    ctx = g.Context(args.profile, args.state_dir)
    if os.path.lexists(ctx.instance_dir(args.name)):
        print(f'REFUSED: the instance {args.name} already exists; choose a new name (nothing was done)',
              file=sys.stderr)
        return 2
    verdict, started, destroy_failed = None, False, False
    try:
        try:
            created = g.create(ctx, args.name, g.READY_TIMEOUT_S, None, provision=True)
            started = True
        except g.Refused as exc:
            # ours only when create made it: its refusal of an existing directory means another process made it
            # between the check above and the create (review of B and C, NIT 8)
            started = os.path.lexists(ctx.instance_dir(args.name)) and 'never reuses' not in str(exc)
            raise
        except BaseException:
            started = os.path.lexists(ctx.instance_dir(args.name))
            raise
        write(out_dir, '1-create.json', created)
        if created.get('result') in ('unavailable', 'not-ready') or \
                (created.get('create') or {}).get('result') == 'not-ready':
            print('STOP: create did not reach readiness', file=sys.stderr)
            return 1
        write(out_dir, '2-provision.json', g.provision(ctx, args.name))
        _, record = g.running_instance(ctx, args.name)
        ssh = g.Ssh(ctx.profile, ctx.instance_dir(args.name), record['ports']['ssh'])
        api = g.GuestApi(ssh, ctx.profile)
        transport = gt.GuestTransport(api, ctx.profile, api_login=g.GUEST_API_LOGIN)

        def raw(method, path, body):
            request = {'method': method, 'path': path, 'timeout': 600}
            if body is not None:
                request['json'] = body
            (answer,) = g._call(api, request)
            return answer
        fixture_body, problems, _ = g._fixture(ctx)
        if problems:
            raise g.Refused('REFUSED', f'the pinned fixture has problems: {problems}')
        routes = (REPO / 'profiles' / PROFILE_ID / 'agent-server' / 'routes.json').read_bytes()
        work = out_dir / 'work'
        work.mkdir()
        result = rehearse(transport=transport, raw=raw, pull=lambda n: g.exchange_pull(ctx, args.name, n),
                          routes_bytes=routes, fixture_body=fixture_body, workdir=work)
        result['transport_calls'] = transport.calls
        write(out_dir, '3-rehearsal.json', result)
        verdict = result['result']
        print(f'step 0: {verdict}', file=sys.stderr)
    except g.Refused as exc:
        print(f'STOP: REFUSED {exc.code}: {exc}', file=sys.stderr)
        write(out_dir, 'stopped.json', {'code': exc.code, 'message': str(exc), 'detail': exc.detail})
    finally:
        if started:
            try:
                destroyed = g.destroy(ctx, args.name)
                write(out_dir, '4-destroy.json', destroyed)
                print(f'destroy: {destroyed.get("result")}', file=sys.stderr)
            except g.Refused as exc:
                print(f'STOP: the destroy was refused: {exc.code}: {exc}', file=sys.stderr)
                destroy_failed = True        # no return in finally: an exception in flight is never swallowed
    return 0 if verdict == 'PASS' and not destroy_failed else 1


if __name__ == '__main__':
    sys.exit(main())
