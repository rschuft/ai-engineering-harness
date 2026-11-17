"""A headless browser driven over the DevTools protocol, for real-browser observations of Agent Canvas against the
fixture's UI face (plan leaf U-01.2's gate G5). A test-side helper, not a test module; the live test that uses it
(``test_canvas_browser.py``) is environment-gated and never runs in the default suite.

**The browser.** The host's installed Chrome or Edge, started headless with no window, with a throwaway profile
directory the caller names (it must be new or empty: never an existing browser profile, never the Owner's), and the
browser's own background networking off by flags (component updates, sync, default apps, extensions, phishing and
domain-reliability reports, field trials, pings). Those flags constrain the browser process's own traffic; they are
not a packet capture.

**No request leaves loopback** (the engineering manager's direction after G5's first run). Two layers, both armed
before any page loads:

1. *At the browser, logged:* the protocol's ``Fetch`` domain intercepts every request of the page and of every
   frame or worker attached to it (attached paused, and armed before it runs); a request whose host is not
   ``127.0.0.1`` is failed (``BlockedByClient``) before it is sent, and logged with its URL, resource type and
   initiator. The run's own log records each arming, and a probe request to a non-routable address
   (``PROBE_URL``) is shown blocked before the page under test is opened.
2. *Backstop, owned by the driver* (U-01.2's review, S4): every request the browser makes at all to a host other
   than ``127.0.0.1`` (WebSockets included, which ``Fetch`` does not see; ``localhost`` and ``[::1]`` included) goes to
   the driver's own ``Backstop``, a loopback listener on a kernel-chosen port named as the browser's proxy
   (``--proxy-server``; the bypass list ``<-loopback>;127.0.0.1`` drops the implicit loopback bypass and bypasses
   ``127.0.0.1`` alone). It refuses every request (403, nothing forwarded) and records it: any request that reaches it
   is a failure of the run. Name resolution is off for every host but ``127.0.0.1``
   (``--host-resolver-rules``), and WebRTC may send no UDP but through the proxy
   (``--force-webrtc-ip-handling-policy=disable_non_proxied_udp``).

The page's own network log (``Network`` domain, WebSocket included) is the evidence: ``off_loopback`` lists every
request to another host, and ``escaped`` those of them that got a response (none may); ``backstop.hits`` lists what
reached the backstop (none may).

**No leak, no hang** (S3): every wait for a process's readiness has a ceiling (a bound on a hang, never a sleep: it
waits on the ready line or the end of the stream); ``start`` ends its own browser process tree, stops the backstop and
removes the profile on any failure after the process is started.

Standard library and the tools set's ``websockets`` (its synchronous client) only.
"""
from __future__ import annotations

import base64
import itertools
import socket
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
LOOPBACK = '127.0.0.1'
# every host but 127.0.0.1 resolves to nothing (Chromium's resolver rules)
RESOLVER_RULES = 'MAP * ~NOTFOUND , EXCLUDE 127.0.0.1'
# a request the block must stop before the page under test opens (TEST-NET-1, RFC 5737: never routed)
PROBE_URL = 'http://192.0.2.1/aieh-block-probe'
BLOCKED_REASON = 'BlockedByClient'
DEVTOOLS_LINE = 'DevTools listening on '
QUIET_FLAGS = (
    '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
    '--disable-component-update', '--disable-sync', '--disable-default-apps', '--disable-extensions',
    '--disable-client-side-phishing-detection', '--disable-domain-reliability', '--disable-breakpad',
    '--disable-crash-reporter', '--disable-field-trial-config', '--no-pings', '--no-service-autorun',
    '--disable-features=OptimizationHints,MediaRouter,Translate,AutofillServerCommunication,'
    'CertificateTransparencyComponentUpdater,InterestFeedContentSuggestions,PrivacySandboxSettings4',
    '--password-store=basic', '--use-mock-keychain', '--mute-audio', '--hide-scrollbars',
    '--proxy-bypass-list=<-loopback>;127.0.0.1', f'--host-resolver-rules={RESOLVER_RULES}',
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
)
START_CEILING_S = 120   # a ceiling on a process's readiness, not an expected duration


def candidates(environ=os.environ) -> list[Path]:
    """Where Chrome and Edge are installed on Windows, in order of preference."""
    roots = [environ.get('ProgramFiles', r'C:\Program Files'), environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')]
    return [Path(root) / rel for rel in (r'Google\Chrome\Application\chrome.exe',
                                         r'Microsoft\Edge\Application\msedge.exe') for root in roots]


class BrowserError(RuntimeError):
    pass


def find_browser(explicit: str | None = None, environ=os.environ) -> Path:
    """The browser executable: EXPLICIT when given, else the first installed of Chrome and Edge."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise BrowserError(f'no browser at {explicit}')
        return path
    for path in candidates(environ):
        if path.is_file():
            return path
    raise BrowserError('neither Chrome nor Edge is installed')


def launch_argv(browser: Path, profile: Path, proxy_port: int, *, width: int = 1280, height: int = 900) -> list[str]:
    """The browser's command line: headless, quiet, a throwaway PROFILE, a kernel-chosen loopback debugging port,
    every non-loopback request sent to the driver's backstop on 127.0.0.1:PROXY_PORT."""
    if not isinstance(proxy_port, int) or not 0 < proxy_port < 65536:
        raise BrowserError(f'no backstop port: {proxy_port!r}')
    return [str(browser), *QUIET_FLAGS, f'--proxy-server=http://{LOOPBACK}:{proxy_port}', f'--user-data-dir={profile}',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0', f'--window-size={width},{height}',
            'about:blank']


class LineReader:
    """The lines of a process's stream, read on a thread of their own until the stream ends (so the process never
    blocks on a full pipe), and waited for with a ceiling."""

    def __init__(self, stream):
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream):
        try:
            for raw in iter(stream.readline, b''):
                self.lines.put(raw.decode('utf-8', 'replace'))
        except (OSError, ValueError):
            pass
        finally:
            self.lines.put(None)

    def wait_for(self, predicate, ceiling_s: float) -> str:
        """The first line PREDICATE accepts. EOFError when the stream ends first, TimeoutError when the ceiling (a
        bound on a hang, not an expected duration) passes first."""
        deadline = time.monotonic() + ceiling_s
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f'no ready line within {ceiling_s} s')
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise TimeoutError(f'no ready line within {ceiling_s} s') from None
            if line is None:
                raise EOFError('the stream ended before its ready line')
            if predicate(line):
                return line


def kill_tree(process) -> None:
    """Ends PROCESS and every process it started (taskkill /T on Windows), and waits for it."""
    if process is None:
        return
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True,
                           creationflags=NO_WINDOW)
        else:
            process.kill()
    try:
        process.wait(START_CEILING_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(START_CEILING_S)


class Backstop:
    """The driver's own proxy backstop (U-01.2's review, S4): a loopback listener on a kernel-chosen port that refuses
    every request it receives (403, nothing forwarded, no name looked up) and records it (``hits``: the request line and
    the Host). The browser names it as its proxy for every host but 127.0.0.1, so a hit is a request that tried to
    leave loopback: any hit fails the run."""

    def __init__(self):
        self.hits: list[dict] = []
        self.lock = threading.Lock()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind((LOOPBACK, 0))
        self.listener.listen(64)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return   # stopped
            threading.Thread(target=self._refuse, args=(conn,), daemon=True).start()

    def _refuse(self, conn):
        with conn:
            conn.settimeout(START_CEILING_S)
            head = b''
            try:
                while b'\r\n\r\n' not in head and len(head) < 65536:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    head += chunk
            except OSError:
                pass
            lines = head.split(b'\r\n')
            host = next((l[5:].strip() for l in lines[1:] if l.lower().startswith(b'host:')), b'')
            with self.lock:
                self.hits.append({'request': lines[0].decode('latin-1')[:2000], 'host': host.decode('latin-1')[:500]})
            try:
                conn.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass

    def stop(self):
        try:
            self.listener.close()
        finally:
            self.thread.join(START_CEILING_S)


def fresh_profile(profile: Path) -> Path:
    """PROFILE must be new or an empty directory (never an existing browser profile); it is created here."""
    profile = Path(profile)
    if profile.exists() and (not profile.is_dir() or any(profile.iterdir())):
        raise BrowserError(f'{profile} is not a new or empty directory: refusing to use it as a browser profile')
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def host_of(url: str) -> str | None:
    """The network host a URL names (None for a URL that names none: data:, blob:, about:)."""
    parts = urlsplit(url or '')
    return parts.hostname if parts.scheme in ('http', 'https', 'ws', 'wss') else None


def allowed(url: str) -> bool:
    """A request the block lets through: http or ws to 127.0.0.1, or a URL with no network host (data:, blob:)."""
    parts = urlsplit(url or '')
    if parts.scheme in ('data', 'blob'):
        return True
    return parts.scheme in ('http', 'ws') and parts.hostname == LOOPBACK


def off_loopback(requests: list[dict]) -> list[dict]:
    """The logged requests to anything but 127.0.0.1 (about:, data: and blob: name no network host)."""
    out = []
    for r in requests:
        scheme = urlsplit(r.get('url') or '').scheme
        if scheme in ('data', 'blob', 'about') or not r.get('url'):
            continue
        if not allowed(r['url']):
            out.append(r)
    return out


def escaped(requests: list[dict]) -> list[dict]:
    """The off-loopback requests that got a response: a request that left loopback (none may)."""
    return [r for r in off_loopback(requests) if r.get('status') is not None]


class Browser:
    """One headless browser process and its DevTools connection: ``page()`` opens a page with the block armed,
    ``navigate``, ``wait_for_text``, ``click_text`` and ``screenshot`` act on it; ``log()`` is its network log,
    ``blocked`` the requests the block failed, ``armed`` the run's own record of each arming."""

    def __init__(self, profile: Path, *, browser: str | None = None, ceiling_s: float = 120,
                 start_ceiling_s: float = START_CEILING_S, launcher=launch_argv):
        self.profile = fresh_profile(profile)
        self.executable = find_browser(browser)
        self.ceiling_s = ceiling_s
        self.start_ceiling_s = start_ceiling_s
        self.launcher = launcher
        self.backstop = None
        self.stderr = None
        self.process = None
        self.ws = None
        self.ids = itertools.count(1)
        self.replies: dict[int, queue.Queue] = {}
        self.events: queue.Queue = queue.Queue()
        self.requests: dict[str, dict] = {}
        self.order: list[str] = []
        self.initiators: dict[str, dict] = {}
        self.sessions: set[str] = set()
        self.attached: list[dict] = []
        self.explicit: set[str] = set()
        self.blocked: list[dict] = []
        self.armed: list[dict] = []
        self.seen: list[dict] = []
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.send_lock = threading.Lock()
        self.started = time.monotonic()

    def _now(self) -> float:
        return round(time.monotonic() - self.started, 3)

    # -- process --------------------------------------------------------------------------------------------
    def start(self) -> 'Browser':
        """Starts the backstop and the browser, and connects to its DevTools endpoint. On any failure the browser's
        process tree is ended, the backstop stopped and the profile removed before the error is raised."""
        from websockets.sync.client import connect
        try:
            self.backstop = Backstop()
            self.process = subprocess.Popen(self.launcher(self.executable, self.profile, self.backstop.port),
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                            creationflags=NO_WINDOW)
            self.stderr = LineReader(self.process.stderr)
            try:   # the browser's own readiness line on its standard error, with a ceiling
                line = self.stderr.wait_for(lambda l: l.startswith(DEVTOOLS_LINE), self.start_ceiling_s)
            except (EOFError, TimeoutError) as exc:
                raise BrowserError(f'the browser did not listen: {exc}') from None
            url = line[len(DEVTOOLS_LINE):].strip()
            if host_of(url) != LOOPBACK:
                raise BrowserError(f'the DevTools endpoint is not on loopback: {url}')
            self.ws = connect(url, open_timeout=self.ceiling_s, max_size=None)
            threading.Thread(target=self._read, daemon=True).start()
            return self
        except BaseException:
            self._teardown()
            raise

    def _send(self, message: dict):
        with self.send_lock:
            self.ws.send(json.dumps(message))

    def _read(self):
        try:
            for raw in self.ws:
                message = json.loads(raw)
                if 'id' in message:
                    box = self.replies.get(message['id'])
                    if box is not None:
                        box.put(message)
                else:
                    self._event(message)
        except Exception:   # the connection closed
            pass

    def call(self, method: str, params: dict | None = None, *, session: str | None = None) -> dict:
        ident = next(self.ids)
        box = self.replies[ident] = queue.Queue()
        message = {'id': ident, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        self._send(message)
        try:
            reply = box.get(timeout=self.ceiling_s)   # a ceiling on a hang, not an expected duration
        except queue.Empty:
            raise BrowserError(f'{method}: no answer') from None
        finally:
            self.replies.pop(ident, None)
        if 'error' in reply:
            raise BrowserError(f'{method}: {reply["error"]}')
        return reply.get('result', {})

    def _post(self, method: str, params: dict, session: str):
        """A command sent from the reader thread, whose answer is not waited for."""
        self._send({'id': next(self.ids), 'method': method, 'params': params, 'sessionId': session})

    # -- the block and the network log -----------------------------------------------------------------------
    def _entry(self, key: str, **fields) -> dict:
        with self.lock:
            entry = self.requests.get(key)
            if entry is None:
                entry = self.requests[key] = {'id': key, 'url': None, 'method': None, 'status': None,
                                              'type': None, 'headers': {}, 'failed': None}
                self.order.append(key)
            entry.update({k: v for k, v in fields.items() if v is not None})
            self.changed.notify_all()
            return entry

    def _paused(self, session: str, params: dict):
        request = params['request']
        url = request['url']
        if allowed(url):
            self._post('Fetch.continueRequest', {'requestId': params['requestId']}, session)
            return
        self._post('Fetch.failRequest', {'requestId': params['requestId'], 'errorReason': BLOCKED_REASON}, session)
        initiator = self.initiators.get(f"{session}:{params.get('networkId')}") or {}
        frames = (initiator.get('stack') or {}).get('callFrames') or []
        with self.lock:
            self.blocked.append({'at': self._now(), 'url': url, 'method': request.get('method'),
                                 'type': params.get('resourceType'), 'initiator': {
                                     'type': initiator.get('type'), 'url': initiator.get('url'),
                                     'frame': (frames[0].get('url') if frames else None)},
                                 'session': session})

    def _event(self, message: dict):
        method, params = message.get('method'), message.get('params', {})
        session = message.get('sessionId') or ''
        key = f"{session}:{params.get('requestId')}"
        if method == 'Fetch.requestPaused':
            self._paused(session, params)
        elif method == 'Network.requestWillBeSent':
            self.initiators[key] = params.get('initiator') or {}
            self._entry(key, url=params['request']['url'], method=params['request']['method'],
                        type=params.get('type'), initiator=(params.get('initiator') or {}).get('type'))
        elif method == 'Network.responseReceived':
            response = params['response']
            self._entry(key, status=response.get('status'),
                        headers={k.lower(): v for k, v in (response.get('headers') or {}).items()},
                        remote=f"{response.get('remoteIPAddress')}:{response.get('remotePort')}")
        elif method == 'Network.loadingFailed':
            self._entry(key, failed=params.get('errorText') or 'failed', blockedReason=params.get('blockedReason'))
        elif method == 'Network.webSocketCreated':
            self._entry(key, url=params['url'], method='WEBSOCKET', type='WebSocket',
                        initiator=(params.get('initiator') or {}).get('type'))
        elif method == 'Network.webSocketHandshakeResponseReceived':
            response = params['response']
            self._entry(key, status=response.get('status'),
                        headers={k.lower(): v for k, v in (response.get('headers') or {}).items()})
        elif method == 'Network.webSocketFrameReceived':
            self._entry(key).setdefault('framesReceived', []).append(params['response'].get('payloadData', '')[:2000])
        elif method == 'Network.webSocketFrameSent':
            self._entry(key).setdefault('framesSent', []).append(params['response'].get('payloadData', '')[:2000])
        elif method == 'Network.webSocketFrameError':
            self._entry(key, failed=params.get('errorMessage') or 'frame error')
        elif method == 'Network.webSocketClosed':
            self._entry(key, closed=True)
        elif method == 'Target.attachedToTarget':
            # a frame or worker the page started, paused until it is armed and watched: done at once, off this thread
            threading.Thread(target=self._watch_child, args=(params['sessionId'], params.get('targetInfo', {})),
                             daemon=True).start()
        else:
            self.events.put(message)

    def wait_request(self, predicate, ceiling_s: float = 60) -> dict | None:
        """Waits on the network log's own changes until an entry satisfies PREDICATE (or the ceiling, a bound on a
        hang, passes). Returns a copy of the entry, or None."""
        deadline = time.monotonic() + ceiling_s
        with self.changed:
            while True:
                for key in self.order:
                    if predicate(self.requests[key]):
                        return dict(self.requests[key])
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.changed.wait(left)

    def log(self) -> list[dict]:
        with self.lock:
            return [dict(self.requests[k]) for k in self.order]

    # -- pages ------------------------------------------------------------------------------------------------
    def _watch(self, session: str, what: str):
        """Arms the block (Fetch, every request) and the network log on SESSION, then lets it run."""
        self.sessions.add(session)
        self.call('Fetch.enable', {'patterns': [{'urlPattern': '*', 'requestStage': 'Request'}]}, session=session)
        with self.lock:
            self.armed.append({'at': self._now(), 'session': session, 'target': what, 'block': 'Fetch.enable *'})
        self.call('Network.enable', {}, session=session)
        if what == 'page':
            self.call('Page.enable', {}, session=session)
            self.call('Log.enable', {}, session=session)
        self.call('Runtime.enable', {}, session=session)
        self.call('Target.setAutoAttach', {'autoAttach': True, 'waitForDebuggerOnStart': True, 'flatten': True},
                  session=session)
        self.call('Runtime.runIfWaitingForDebugger', {}, session=session)

    def _watch_child(self, session: str, info: dict):
        if info.get('targetId') in self.explicit:
            return   # the page this driver attached itself, armed by page()
        with self.lock:
            self.attached.append({'session': session, 'type': info.get('type'), 'url': info.get('url')})
        if session in self.sessions:
            return
        try:
            self._watch(session, info.get('type') or 'child')
        except BrowserError as exc:
            with self.lock:
                self.attached.append({'session': session, 'error': str(exc)})

    def page(self) -> str:
        """A new page target, attached (flattened) with the block armed and its network log on; then the probe:
        one request to PROBE_URL, which must be blocked before any page under test opens. Returns the session."""
        target = self.call('Target.createTarget', {'url': 'about:blank'})['targetId']
        self.explicit.add(target)
        session = self.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        self._watch(session, 'page')
        outcome = self.evaluate(session, f"fetch({json.dumps(PROBE_URL)}).then(() => 'answered', "
                                         "(e) => 'failed: ' + e.message)")
        probe = [b for b in self.blocked if b['url'] == PROBE_URL]
        with self.lock:
            self.armed.append({'at': self._now(), 'session': session, 'probe': PROBE_URL, 'outcome': outcome,
                               'blocked': bool(probe)})
        if outcome == 'answered' or not probe:
            raise BrowserError(f'the block is not armed: the probe {PROBE_URL} was {outcome}')
        return session

    def navigate(self, session: str, url: str) -> dict:
        self.call('Page.setLifecycleEventsEnabled', {'enabled': True}, session=session)
        result = self.call('Page.navigate', {'url': url}, session=session)
        if result.get('errorText'):
            raise BrowserError(f'navigate {url}: {result["errorText"]}')
        return result

    def wait_lifecycle(self, navigation: dict, name: str = 'networkIdle', ceiling_s: float | None = None) -> bool:
        """Waits for the browser's own lifecycle event NAME of the navigated frame and loader (networkIdle: no
        request in flight for 500 ms, the browser's definition). False when the ceiling (a bound on a hang) passes."""
        deadline = time.monotonic() + (ceiling_s or self.ceiling_s)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            try:
                message = self.events.get(timeout=left)
            except queue.Empty:
                return False
            self.seen.append(message)
            params = message.get('params', {})
            if (message.get('method') == 'Page.lifecycleEvent' and params.get('name') == name
                    and params.get('frameId') == navigation.get('frameId')
                    and params.get('loaderId') == navigation.get('loaderId')):
                return True

    def evaluate(self, session: str, expression: str, *, await_promise=True):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True,
                                                'awaitPromise': await_promise}, session=session)
        if 'exceptionDetails' in result:
            raise BrowserError(f'evaluate: {json.dumps(result["exceptionDetails"])[:500]}')
        return result.get('result', {}).get('value')

    def wait_for_text(self, session: str, texts: list[str], *, ceiling_ms: int = 60000) -> dict:
        """Waits, inside the page, on its own DOM mutations until its visible text holds every one of TEXTS (or the
        ceiling passes: a bound on a hang). Returns {found, text}."""
        script = """
        new Promise((resolve) => {
          const wanted = %s;
          const done = () => {
            const text = document.body ? document.body.innerText : '';
            if (wanted.every((w) => text.includes(w))) { resolve({found: true, text}); return true; }
            return false;
          };
          if (done()) return;
          const observer = new MutationObserver(() => { if (done()) observer.disconnect(); });
          observer.observe(document, {subtree: true, childList: true, characterData: true, attributes: true});
          setTimeout(() => { observer.disconnect();
            resolve({found: false, text: document.body ? document.body.innerText : ''}); }, %d);
        })""" % (json.dumps(texts), ceiling_ms)
        return self.evaluate(session, script)

    def click_css(self, session: str, selector: str, *, ceiling_ms: int = 30000) -> dict:
        """Clicks, as a user does, the first visible element matching the CSS SELECTOR once it appears."""
        return self._click(session, 'document.querySelector(%s)' % json.dumps(selector), ceiling_ms)

    def click_text(self, session: str, label: str, *, ceiling_ms: int = 30000) -> dict:
        """Clicks, as a user does (the protocol's mouse events at the element's centre), the visible button or link
        whose own text is LABEL, once it appears (or the ceiling passes). Returns where it clicked, or None."""
        finder = ("[...document.querySelectorAll('button, a, [role=button]')]"
                  ".find((e) => e.innerText.trim() === %s && e.offsetParent !== null && !e.disabled)" % json.dumps(label))
        return self._click(session, finder, ceiling_ms)

    def _click(self, session: str, finder: str, ceiling_ms: int) -> dict | None:
        script = """
        new Promise((resolve) => {
          const find = () => { const e = %s; return e && e.offsetParent !== null ? e : null; };
          const box = (e) => { e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect();
            return {x: r.x + r.width / 2, y: r.y + r.height / 2}; };
          const now = find(); if (now) { resolve(box(now)); return; }
          const observer = new MutationObserver(() => { const e = find(); if (e) { observer.disconnect(); resolve(box(e)); } });
          observer.observe(document, {subtree: true, childList: true, attributes: true});
          setTimeout(() => { observer.disconnect(); resolve(null); }, %d);
        })""" % (finder, ceiling_ms)
        point = self.evaluate(session, script)
        if point is None:
            return None
        for kind in ('mouseMoved', 'mousePressed', 'mouseReleased'):
            self.call('Input.dispatchMouseEvent', {'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left',
                                                   'clickCount': 1}, session=session)
        return point

    def console(self) -> list[dict]:
        """The page's exceptions, console errors and warnings, and the browser's own log errors and warnings for it
        (a content-security policy's violations among them) seen so far."""
        while True:
            try:
                self.seen.append(self.events.get_nowait())
            except queue.Empty:
                break
        out = []
        for message in self.seen:
            params = message.get('params', {})
            if message.get('method') == 'Runtime.exceptionThrown':
                details = params.get('exceptionDetails', {})
                out.append({'kind': 'exception', 'text': (details.get('exception') or {}).get('description')
                            or details.get('text')})
            elif message.get('method') == 'Log.entryAdded' and params['entry'].get('level') in ('error', 'warning'):
                entry = params['entry']
                out.append({'kind': f"log-{entry.get('source')}-{entry.get('level')}", 'text': (entry.get('text') or '')[:1000],
                            'url': entry.get('url')})
            elif message.get('method') == 'Runtime.consoleAPICalled' and params.get('type') in ('error', 'warning'):
                out.append({'kind': params['type'], 'text': ' '.join(str(a.get('value', a.get('description', '')))
                                                                    for a in params.get('args', []))[:1000]})
        return out

    def screenshot(self, session: str, path: Path):
        data = self.call('Page.captureScreenshot', {'format': 'png'}, session=session)['data']
        Path(path).write_bytes(base64.b64decode(data))

    def _teardown(self):
        """Ends the browser's process tree, stops the backstop and removes the profile (whatever state they are in)."""
        try:
            if self.ws is not None:
                try:
                    self.ws.close()
                except Exception:
                    pass
            kill_tree(self.process)
            if self.process is not None and self.process.stderr:
                self.process.stderr.close()
        finally:
            if self.backstop is not None:
                self.backstop.stop()
            shutil.rmtree(self.profile, ignore_errors=True)

    def close(self):
        """Closes the browser (Browser.close, then its whole process tree if it lingers), stops the backstop and
        removes the throwaway profile."""
        try:
            if self.ws is not None:
                try:
                    self.call('Browser.close')
                except Exception:
                    pass
            if self.process is not None:
                try:
                    self.process.wait(self.ceiling_s)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            self._teardown()
