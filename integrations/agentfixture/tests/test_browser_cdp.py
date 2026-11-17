"""The real-browser driver's own rules (``browser_cdp.py``, U-01.2's gate G5): what the block lets through, what the
network log calls off loopback and escaped, the browser's command line, the throwaway profile. Offline: no browser
is started here (the driver itself runs only in the gated ``test_canvas_browser.py``)."""
import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import browser_cdp as B

CATEGORY = 'unit'


class Block(unittest.TestCase):
    def test_only_http_and_ws_to_127_0_0_1_and_hostless_urls_go_through(self):
        for url in ('http://127.0.0.1:13330/', 'http://127.0.0.1:4173/x?y=1', 'ws://127.0.0.1:13330/sockets/session/a',
                    'data:image/png;base64,AA', 'blob:http://127.0.0.1:13330/uuid'):
            with self.subTest(url=url):
                self.assertTrue(B.allowed(url))
        for url in ('https://cdn.simpleicons.org/github/FFFFFF', 'https://127.0.0.1/', 'wss://127.0.0.1:1/',
                    'http://localhost:13330/', 'http://[::1]:13330/', 'http://127.0.0.2/', 'http://192.0.2.1/',
                    'ftp://127.0.0.1/', 'chrome-extension://abc/', '', 'http://127.0.0.1.example/'):
            with self.subTest(url=url):
                self.assertFalse(B.allowed(url))

    def test_off_loopback_and_escaped_read_the_network_log(self):
        log = [{'url': 'http://127.0.0.1:1/a', 'status': 200}, {'url': 'about:blank', 'status': None},
               {'url': 'https://cdn.example/x', 'status': None, 'failed': 'net::ERR_BLOCKED_BY_CLIENT'},
               {'url': 'https://cdn.example/y', 'status': 200}, {'url': 'data:,x', 'status': 200},
               {'url': 'https://cdn.example/z', 'status': 200, 'failed': 'net::ERR_ABORTED'}]
        self.assertEqual([r['url'] for r in B.off_loopback(log)],
                         ['https://cdn.example/x', 'https://cdn.example/y', 'https://cdn.example/z'])
        # a response that arrived and then failed still left loopback
        self.assertEqual([r['url'] for r in B.escaped(log)], ['https://cdn.example/y', 'https://cdn.example/z'])

    def test_the_probe_is_a_request_the_block_must_stop(self):
        self.assertFalse(B.allowed(B.PROBE_URL))
        self.assertEqual(B.host_of(B.PROBE_URL), '192.0.2.1')


class CommandLine(unittest.TestCase):
    def test_headless_quiet_a_loopback_debugger_and_the_backstop_for_everything_but_127_0_0_1(self):
        argv = B.launch_argv(Path('C:/b/chrome.exe'), Path('C:/scratch/profile'), 50123)
        for flag in ('--headless=new', '--disable-background-networking', '--disable-component-update',
                     '--no-first-run', '--disable-sync', '--disable-default-apps', '--disable-extensions',
                     '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                     '--proxy-server=http://127.0.0.1:50123', '--proxy-bypass-list=<-loopback>;127.0.0.1',
                     '--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1',
                     '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
                     f'--user-data-dir={Path("C:/scratch/profile")}'):
            self.assertIn(flag, argv)
        self.assertEqual([a for a in argv if a.startswith('--proxy-server=')], ['--proxy-server=http://127.0.0.1:50123'])
        self.assertFalse([a for a in argv if ':9' in a and a.startswith('--proxy')], 'no assumed-closed port')
        for port in (None, 0, 65536, '9'):
            with self.assertRaises(B.BrowserError):
                B.launch_argv(Path('C:/b/chrome.exe'), Path('C:/scratch/profile'), port)
        self.assertEqual(argv[0], str(Path('C:/b/chrome.exe')))
        self.assertEqual(argv[-1], 'about:blank')
        self.assertEqual(sum(a.startswith('--user-data-dir=') for a in argv), 1)

    def test_the_browser_is_chrome_or_edge_from_program_files_or_the_named_one(self):
        names = [p.name for p in B.candidates({'ProgramFiles': 'C:/PF', 'ProgramFiles(x86)': 'C:/PF86'})]
        self.assertEqual(names, ['chrome.exe', 'chrome.exe', 'msedge.exe', 'msedge.exe'])
        with self.assertRaises(B.BrowserError):
            B.find_browser('C:/no/such/browser.exe')


class Lines(unittest.TestCase):
    def test_a_ready_line_is_found_the_end_and_the_ceiling_are_errors(self):
        reader = B.LineReader(io.BytesIO(b'noise\nDevTools listening on ws://127.0.0.1:1/x\nmore\n'))
        self.assertEqual(reader.wait_for(lambda l: l.startswith('DevTools'), 30).strip(),
                         'DevTools listening on ws://127.0.0.1:1/x')
        with self.assertRaises(EOFError):
            reader.wait_for(lambda l: l.startswith('never'), 30)
        # a ceiling already passed is a timeout even when a line is there to read
        with self.assertRaises(TimeoutError):
            B.LineReader(io.BytesIO(b'ready\n')).wait_for(lambda l: True, 0)
        read, write = os.pipe()
        self.addCleanup(os.close, write)
        with self.assertRaises(TimeoutError):
            B.LineReader(os.fdopen(read, 'rb')).wait_for(lambda l: True, 0.2)


class Backstop(unittest.TestCase):
    category = 'integration'   # a loopback listener

    def ask(self, port, data):
        with socket.create_connection(('127.0.0.1', port), timeout=30) as conn:
            conn.sendall(data)
            return conn.recv(4096)

    def test_it_refuses_every_proxy_request_records_it_and_stops(self):
        backstop = B.Backstop()
        self.addCleanup(backstop.stop)
        self.assertEqual(self.ask(backstop.port, b'GET http://cdn.example/x.png HTTP/1.1\r\nHost: cdn.example\r\n\r\n')
                         .split(b'\r\n')[0], b'HTTP/1.1 403 Forbidden')
        self.assertEqual(self.ask(backstop.port, b'CONNECT cdn.example:443 HTTP/1.1\r\nHost: cdn.example:443\r\n\r\n')
                         .split(b'\r\n')[0], b'HTTP/1.1 403 Forbidden')
        self.assertEqual(backstop.hits, [{'request': 'GET http://cdn.example/x.png HTTP/1.1', 'host': 'cdn.example'},
                                         {'request': 'CONNECT cdn.example:443 HTTP/1.1', 'host': 'cdn.example:443'}])
        port = backstop.port
        backstop.stop()
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=5).close()


class StartFailures(unittest.TestCase):
    """U-01.2's review, S3: a browser that exits, hangs or listens off loopback before it is ready leaves no process,
    no backstop and no profile behind, and the wait for it has a ceiling. The stand-in browser is this interpreter."""

    category = 'integration'   # processes and a listener

    def browser(self, script, ceiling=30):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-cdp-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, ignore_errors=True))
        launched = {'pidfile': tmp / 'pid'}

        def launcher(exe, profile, port):
            launched['port'] = port
            # the stand-in records its own pid: the interpreter may be a child of a launcher (a venv's python.exe),
            # so only the whole tree's end shows that nothing is left behind
            record = f"import os; open({str(launched['pidfile'])!r}, 'w').write(str(os.getpid())); "
            return [str(exe), '-I', '-c', record + script]
        b = B.Browser(tmp / 'profile', browser=sys.executable, launcher=launcher, start_ceiling_s=ceiling)
        return b, tmp / 'profile', launched

    def assertLeftNothing(self, b, profile, launched):
        self.assertIsNotNone(b.process.poll(), 'the stand-in browser was ended')
        if launched['pidfile'].exists():
            pid = launched['pidfile'].read_text(encoding='utf-8')
            listed = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'], capture_output=True,
                                    text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
            self.assertNotIn(f'"{pid}"', listed, 'the stand-in\'s own interpreter process was ended (the tree)')
        self.assertFalse(profile.exists(), 'the profile was removed')
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', launched['port']), timeout=5).close()

    def test_a_browser_that_exits_before_it_listens(self):
        b, profile, launched = self.browser('import sys; sys.exit(3)')
        with self.assertRaises(B.BrowserError) as caught:
            b.start()
        self.assertIn('did not listen', str(caught.exception))
        self.assertLeftNothing(b, profile, launched)

    def test_a_browser_that_never_listens_is_ended_at_the_ceiling(self):
        b, profile, launched = self.browser('import threading; threading.Event().wait()', ceiling=1.0)
        began = time.monotonic()
        with self.assertRaises(B.BrowserError) as caught:
            b.start()
        # the tree is ended at once (taskkill /T), not after the process wait's own ceiling (a bound, generously
        # under START_CEILING_S, that only a teardown which relies on that fallback exceeds)
        self.assertLess(time.monotonic() - began, B.START_CEILING_S / 2)
        self.assertIn('within 1.0 s', str(caught.exception))
        self.assertLeftNothing(b, profile, launched)

    def test_a_debugger_off_loopback_is_refused_and_ended(self):
        script = ("import sys, threading; sys.stderr.write('DevTools listening on ws://203.0.113.9:1/x\\n'); "
                  "sys.stderr.flush(); threading.Event().wait()")
        b, profile, launched = self.browser(script)
        with self.assertRaises(B.BrowserError) as caught:
            b.start()
        self.assertIn('not on loopback', str(caught.exception))
        self.assertLeftNothing(b, profile, launched)


class Profile(unittest.TestCase):
    def test_the_profile_must_be_new_or_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh = B.fresh_profile(Path(tmp) / 'new')
            self.assertTrue(fresh.is_dir())
            self.assertEqual(B.fresh_profile(fresh), fresh)
            (fresh / 'Local State').write_text('{}', encoding='utf-8')
            with self.assertRaises(B.BrowserError):
                B.fresh_profile(fresh)
            afile = Path(tmp) / 'file'
            afile.write_text('x', encoding='utf-8')
            with self.assertRaises(B.BrowserError):
                B.fresh_profile(afile)


if __name__ == '__main__':
    unittest.main()
