"""Gate G5 of plan leaf U-01.2 as a live test: the pinned standalone Agent Canvas, served by upstream's static
server through the Owner host's start command, against the served fixture's UI face, in a real headless browser
(``browser_cdp.py``), every request to a host other than 127.0.0.1 blocked at the browser before the page loads.

Environment-gated: it runs only when ``AIEH_CANVAS_BROWSER=1`` and ``AIEH_LOCKED_OPENAPI`` (the fixture validates
the create against it) are given, with Node.js on PATH, the Owner host's dependencies installed
(``apps/owner-host/node_modules``) and Chrome or Edge installed; never in the default suite. Its ports are free
loopback ports chosen here, never 13310, 13320 or 13330. ``AIEH_CANVAS_BROWSER_OUT`` names a directory (outside the
checkout) for its report and screenshots.

The rule is G5's, unchanged (``apps/owner-host/README.md``): the view shows the fixture conversation's title and the
dispatched message, every request the fixture answered 2xx has a provenance row, and no request went to a host
other than 127.0.0.1. Canvas's onboarding is passed as a user passes it, in the browser: its telemetry-consent
dialog declined (the box unticked, then Confirm), then "Skip for now". Nothing is written into Canvas's storage from
outside.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

import browser_cdp as B
import fixture_support as S

CATEGORY = 'integration'
APP = S.REPO / 'apps' / 'owner-host'
START = APP / 'scripts' / 'canvas-standalone.mjs'
TITLE = 'FIXTURE: ai-engineering-harness/agentfixture (not a live conversation)'
MESSAGE_TEXT = 'Implement the change as designed. (U-01.2 gate G5 message)'
GATED = os.environ.get('AIEH_CANVAS_BROWSER') == '1'
REASON = ('AIEH_CANVAS_BROWSER=1 (with AIEH_LOCKED_OPENAPI, node, apps/owner-host/node_modules and Chrome or Edge) '
          'is not given: the real-browser gate never runs in the default suite')


def provenance_answers() -> set[str]:
    return {r['answer'] for r in S.SERVED['provenance']} | {r['answer'] for r in S.CATALOG['provenance']}


class Canvas:
    """The Owner host's start command on a free loopback port, routed to the fixture's free port; stopped by
    closing its standard input (its own stop), its tree killed only if that fails."""

    def __init__(self, port: int, fixture_port: int, build_dir: Path, csp: bool):
        self.argv = ['node', str(START), 'serve', '--build-dir', str(build_dir), '--port', str(port),
                     '--fixture-port', str(fixture_port)] + (['--csp'] if csp else [])
        self.build_dir = build_dir
        self.process = None

    def start(self, ceiling_s: float = B.START_CEILING_S) -> 'Canvas':
        """Starts the start command and waits, with a ceiling, for its own ready line; on any failure its process
        tree is ended before the error is raised."""
        self.process = subprocess.Popen(self.argv, cwd=APP, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, creationflags=S.NO_WINDOW)
        try:
            self.stdout, self.stderr = B.LineReader(self.process.stdout), B.LineReader(self.process.stderr)
            self.stdout.wait_for(lambda line: line.startswith('listening '), ceiling_s)
            return self
        except BaseException:
            B.kill_tree(self.process)
            raise

    def stop(self) -> int | None:
        if self.process is None:
            return None
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(S.STOP_CEILING_S)
            except subprocess.TimeoutExpired:
                B.kill_tree(self.process)
        for stream in (self.process.stdout, self.process.stderr):
            stream.close()
        return self.process.returncode


def seed(port: int) -> str:
    """The conversation created and its one message sent on the dispatcher's face, as the dispatcher sends them."""
    cid = str(uuid.uuid4())
    created = S.http(port, 'POST', '/api/conversations', key=S.SERVER.DISPATCHER_ACCESS, body=S.d1_create(cid))
    assert created['status'] == 201, created
    message = {'role': 'user', 'content': [{'type': 'text', 'text': MESSAGE_TEXT}], 'run': True}
    sent = S.http(port, 'POST', f'/api/conversations/{cid}/events', key=S.SERVER.DISPATCHER_ACCESS, body=message)
    assert 200 <= sent['status'] < 300, sent
    return cid


def g5(csp: bool, out: Path) -> dict:
    """One G5 run; returns its report (written to OUT/g5-report.json)."""
    out.mkdir(parents=True, exist_ok=True)
    report = {'csp': csp}
    served = S.Served('finished', openapi=S.locked_openapi_path()).start()
    canvas = browser = None
    try:
        cid = seed(served.port)
        canvas_port = S.free_port()
        while canvas_port == 13330:
            canvas_port = S.free_port()
        canvas = Canvas(canvas_port, served.port, out / 'canvas', csp)   # assigned first: finally always stops it
        canvas.start()
        if csp:
            report['policy'] = json.loads((out / 'canvas' / 'derived.json').read_text(encoding='utf-8'))['csp']
        browser = B.Browser(out / 'profile')   # assigned first: finally always closes it
        browser.start()
        session = browser.page()
        report['armedBeforePage'] = list(browser.armed)
        before = len(served.calls())
        navigation = browser.navigate(session, f'http://127.0.0.1:{canvas_port}/conversations/{cid}')
        report['networkIdle'] = browser.wait_lifecycle(navigation, 'networkIdle', ceiling_s=90)
        browser.screenshot(session, out / '1-first-view.png')
        text = browser.evaluate(session, 'document.body ? document.body.innerText : ""')
        clicks = []
        if 'Help improve OpenHands' in text:
            clicks.append(['untick Send anonymous usage data', browser.click_css(session, 'input[name=analytics]')])
            clicks.append(['Confirm preferences', browser.click_text(session, 'Confirm preferences')])
            write = browser.wait_request(lambda e: e.get('method') not in (None, 'GET', 'OPTIONS', 'WEBSOCKET')
                                         and (e.get('status') or e.get('failed')), ceiling_s=30)
            report['consentWrite'] = write and {k: write.get(k) for k in ('method', 'url', 'status', 'failed')}
            browser.screenshot(session, out / '2-after-consent.png')
        if 'Skip for now' in browser.evaluate(session, 'document.body.innerText'):
            clicks.append(['Skip for now', browser.click_text(session, 'Skip for now')])
        report['clicks'] = clicks
        seen = browser.wait_for_text(session, [TITLE, MESSAGE_TEXT], ceiling_ms=30000)
        browser.screenshot(session, out / '3-conversation.png')
        report.update(titleShown=TITLE in seen['text'], messageShown=MESSAGE_TEXT in seen['text'],
                      visibleText=seen['text'][:5000], console=browser.console())
        log = browser.log()
        rows = provenance_answers()
        report['requests'] = []
        for r in log:
            label = r['headers'].get('x-aieh-fixture')
            answer = json.loads(label)['answer'] if label else None
            report['requests'].append({'method': r['method'], 'url': r['url'], 'status': r['status'],
                                       'failed': r['failed'], 'blockedReason': r.get('blockedReason'),
                                       'fixtureAnswer': answer, 'provenanceRows': answer in rows if answer else None})
        report['blocked'] = browser.blocked
        report['escaped'] = B.escaped(log)
        report['backstop'] = list(browser.backstop.hits)
        report['fixtureCalls'] = served.calls()[before:]
    finally:
        if browser is not None:
            browser.close()
        report['canvasExit'] = canvas.stop() if canvas is not None else None
        served.close()
    (out / 'g5-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


@unittest.skipUnless(GATED, REASON)
class GateG5(unittest.TestCase):
    category = 'integration'

    def setUp(self):
        named = os.environ.get('AIEH_CANVAS_BROWSER_OUT')
        self.out = Path(named) if named else Path(tempfile.mkdtemp(prefix='aieh-g5-'))
        if not named:
            self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def judge(self, report: dict):
        # the block was armed, and shown working, before the page under test opened
        probe = [a for a in report['armedBeforePage'] if a.get('probe') == B.PROBE_URL]
        self.assertTrue(probe and probe[0]['blocked'], report['armedBeforePage'])
        # no request left loopback, and none reached the driver's backstop proxy
        self.assertEqual(report['escaped'], [])
        self.assertEqual(report['backstop'], [])
        # every request the fixture answered 2xx has a provenance row
        self.assertEqual([r for r in report['requests'] if r['fixtureAnswer'] and r['status']
                          and 200 <= r['status'] < 300 and not r['provenanceRows']], [])
        self.assertEqual(report['canvasExit'], 0)
        # the view shows the fixture conversation's title and the dispatched message (G5's rule)
        self.assertTrue(report['titleShown'] and report['messageShown'],
                        'the conversation view did not render: ' + report['visibleText'][:300])

    def test_g5_without_the_content_security_policy(self):
        self.judge(g5(False, self.out / 'csp-off'))

    def test_g5_with_the_content_security_policy_option(self):
        self.judge(g5(True, self.out / 'csp-on'))


if __name__ == '__main__':
    unittest.main()
