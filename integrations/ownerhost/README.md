# The Integration process (`integrations/ownerhost/`)

Plan leaf **U-01.3**; [decision 0025](../../decisions/0025-integration-process-owner-ui-session-credential-and-owner-conversation-store.md)
(Proposed); the I1 work design ([`evidence/I1-integration-design-2026-11-16.md`](../../evidence/I1-integration-design-2026-11-16.md),
rulings R1 to R4 and R7). The Owner UI's backend on the host: a Starlette application on uvicorn (the versions the
component lock pins, in the hash-locked tools set), run under the tools interpreter, bound to `127.0.0.1:13310`
only. The Owner UI shell ([`apps/owner-host`](../../apps/owner-host/README.md)) reaches it with the Owner UI session
credential, `cred-owner-ui-session`, which the Owner mints himself at a console.

In this slice it does one thing behind the credential: `POST /session` answers the authenticated session's public id
and validity (the shell's sign-in). Threads and messages (U-02.1), capture (P-01.3), acceptance (P-04.4) and the
projection (U-04.1) attach later. It has no dispatch endpoint.

## Files

| Path | What |
|---|---|
| `app.py` | The ASGI application (`create_app`), its three request checks and its one route; `bind_listener` and `serve`, the server process |
| `session.py` | The credential's shape and verifier, and `check`, which decides one request against the session table |
| `enroll.py` | The Owner's enroll command: the console guard, minting, the session row, the one showing |
| `service.py` | The lifecycle verbs through the platform contract (decision 0011): `up`, `down`, `restart`, `status`, `inspect`, `verify`, and the supervisor |
| `tests/test_session.py` | The shape, the verifier, `check`'s four refusals (each changing nothing), every other inventory credential shape refused, enrollment (unit) |
| `tests/test_app.py` | The route-table walk, the preflight, Host and Origin, the refusals over ASGI, no cookie, the log (contract) |
| `tests/test_enroll.py` | The console guard on pipes, files and the null device, refusing before anything is resolved or written; gate G8 on a real (hidden) console in a child process (unit, integration) |
| `tests/test_service.py` | The server's environment allowlist, the configuration, readiness from the TCP table, `up`'s refusals, `down`, with a fake adapter (unit) |
| `tests/test_structure.py` | R2's structural tests: no client socket (syntax trees), the import census (a fresh interpreter), one declared port (unit, integration) |
| `tests/test_listener.py` | The real start and stop on a throwaway layout: the listener table, the host census by port, every request over HTTP, the refusals, the environment and command line read from outside, the records and logs, the live import census, no window, no orphan (integration, Windows) |
| `tests/ownerhost_support.py`, `tests/process_probe.py` | The fixtures (throwaway stores and credentials, the inventory's credential shapes built at run time) and the outside read of a process's environment block and command line |

## The credential

`cred-owner-ui-session` is `aieh-oui-` followed by 52 lower-case base32 characters (32 random bytes): not an Agent
Server key (43 URL-safe characters, no prefix), not an attempt token (`aieh-inf-`), not a provider key (`sk-ant-`),
not a Gitea token (40 hexadecimal digits). The Owner conversation store
([`integrations/conversation`](../conversation/README.md)) keeps only its **verifier** (sha256 of the domain line
`ai-engineering-harness/owner-ui-session/v1` and the credential), the session's public id, its issue time and its
expiry; the credential itself is stored nowhere. One session is current: a new enrollment supersedes it.

The shell sends it in the `X-AIEH-Owner-Session` header on every request, never as a cookie, and keeps its copy in
its own origin's `localStorage` until Sign out (decision 0025 point 4, as amended).

### enroll (the Owner's act)

```
<tools python> -I -B integrations/ownerhost/enroll.py [--hours N]       # task ownerhost:enroll
```

Run by the Owner, in his own console window. It refuses unless standard input and standard output are both console
handles (`ENROLL_NOT_INTERACTIVE`: the broker's GetConsoleMode check, reused), before it resolves the managed root,
opens the store or mints anything: plain pipes and redirected handles, an ordinary tool shell's accidental run,
obtain nothing. It then mints the credential, writes the session row (validity `--hours`, default 12, 1 to 168), and
shows the credential once on the console with the session id and expiry. Exit 0 enrolled, 2 refused. No test runs
it against the managed root; OA-32 (a) is the Owner's own enrollment.

What the guard does not do: it does not stop a process of the Owner's account that gives the command a console (one
of its own, hidden or not, or a pseudoconsole) and reads it, or that calls `enroll()` or writes the store. No console
check can tell the Owner from such a process; that is decision 0010 point 1's accepted same-account limit (decision
0025, Consequences). Each of those paths is visible to the Owner: any new enrollment supersedes his session, which
then answers `SESSION_CREDENTIAL_REVOKED` (`tests/test_enroll.py` `GuardScope` shows a hidden console passing the
guard).

## Every request

Outermost first; a refusal changes nothing, and the credential is never echoed or logged.

| Check | Refusal |
|---|---|
| `Host` is exactly `127.0.0.1:13310` | `HOST_NOT_ALLOWED` (400) |
| `Origin`, when present, is `http://127.0.0.1:4173` or `http://127.0.0.1:5173` | `ORIGIN_NOT_ALLOWED` (403) |
| CORS (Starlette's CORSMiddleware): those origins only, no credentials mode, only the session header and `Content-Type`; it answers the preflight, the one request without the credential, which carries no data | 400 for a preflight asking for another header |
| The session header: present, of the shape, matching a current, unexpired session | `SESSION_CREDENTIAL_MISSING`, `_FOREIGN`, `_REVOKED`, `_EXPIRED` (401) |

A superseded session is `_REVOKED` whether or not it has also expired; an expired current session is `_EXPIRED`; a
value that is not of the shape, or matches no enrolled verifier, or is sent twice, or whose session was issued more
than 5 minutes after now (no enrollment on this host writes one), is `_FOREIGN`. A path that is no route is refused
by the credential check first, then answers `NOT_FOUND` (404) or `METHOD_NOT_ALLOWED` (405), whose details do not
echo the path. A websocket is closed (1008): there is no websocket route, and uvicorn runs with `ws='none'`.

The service log (`<logs>/owner-host/service.log`) records each decided request as `accepted METHOD ROUTE STATUS
session=<public id>` or `refused CODE METHOD ROUTE`, where ROUTE is the path of the route the request matched or
`unmatched`, and METHOD a common method or `OTHER`: nothing the client wrote is logged verbatim, so no path can forge
a log line or carry a credential into the log. uvicorn's access log is off.

## What it never does

Decision 0025 point 2, each with its test: it opens no outbound connection (its one socket is `bind_listener`'s
listener, bound with `SO_EXCLUSIVEADDRUSE`, so no other socket binds `127.0.0.1:13310` while it is held, even with
`SO_REUSEADDR`; a socket on another address of the port is not excluded, which `up` and `verify` cover by refusing or
failing on any other holder of the port; readiness reads the kernel's TCP table, never a request);
the server process loads only `app.py`, `session.py`, the conversation store and storecore (no credential, Gitea,
authorization-recorder, dispatch or inference module); it reads no credential and no `config.yml` (service.py gives
it its two directories); its environment, and its supervisor's, is the allowlist `ENVIRONMENT_NAMES` (Windows and
the interpreter's needs, nothing else); it has no dispatch endpoint.

## The lifecycle

```
<tools python> -I -B integrations/ownerhost/service.py up|down|restart|status|inspect|verify   # task ownerhost:<verb>
```

| Verb | What |
|---|---|
| `up` | Refuses `ALREADY_RUNNING` and `PORT_IN_USE` (never another port), then starts the managed environment through the platform adapter: a supervisor with no window that joins a new kill-on-close Job Object and starts the server process inside it (`app.py serve`), and waits until the server of its own launch listens (the TCP table), at most 30 s. Concurrent `up` commands are serialized by `launch.lock`; one instance is enforced by the supervisor's `instance.lock` (below) |
| `down` | Writes the stop request the server watches for (`<state>/owner-host/stop-request`), waits on both processes (at most 15 s), and terminates the supervisor only if they have not ended; the job then ends the server |
| `restart` | The contract's, under a write-ahead transition record (`<state>/owner-host/transitions/`) |
| `status`, `inspect` | Report; change nothing |
| `verify` | The `aieh-readiness/1` record; exit 0 only when it passes: `supervisor_running`, `server_running`, `server_supervised`, `listener_on_declared_port`, `loopback_only`, `port_held_by_server` |

No `install`, `upgrade`, `uninstall` or credential verb: it runs from the checkout and is custodian of no credential.
Linux and macOS: `PLATFORM_UNSUPPORTED`.

One instance: the supervisor takes an exclusive OS lock on `<state>/owner-host/instance.lock` before it touches any
shared file and holds it for its whole life (the OS releases it when the supervisor ends, however it ends). A second
supervisor exits having started and written nothing, and its `up` is refused `ALREADY_RUNNING`. A server that exits
other than cleanly, killed included, is recorded as `failed` in `run.json`.

Data (decision 0009): `<state>/owner-host/` holds `conversation.sqlite`, `run.json` (`aieh-service-run/1`: the
supervisor and server processes, the job, the harness commit and tools lock digest, the configuration snapshot) and
`server.json` (the server's own record: process, address, port, whether its console has a window, and its live
import census at start and at stop); `<logs>/owner-host/` holds `supervisor.log`, `console.log` and `service.log`.

The supervisor is started by the platform adapter's `launch_supervisor` with the same environment allowlist as the
server, so neither holds what the starting environment holds beyond those names. It loads the Windows adapter, which
loads its credential-provider module only when a credential provider is asked for, never here: the supervisor's
import census (`supervisor_modules` in `run.json`, at start, running and stop) has nothing under
integrations/credentials, gitea, dispatch, inference or owner, and neither has the server's.

## Commands

```
<tools python> -I -B -m unittest discover -s integrations/ownerhost/tests -v   # task ownerhost:test
```

The listener tests start the real service on `127.0.0.1:13310` with a throwaway layout and stop it; they fail,
rather than skip, when the port is already held.

## Not yet verified

- The Owner's own enrollment and sign-in with his real credential (OA-32 (a)); a real browser against the service.
- Linux and macOS (the platform contract's adapters, F-06.4 and F-06.5).
- Ending with the Owner's session or a reboot (the job's declared behaviour, as for Gitea).
