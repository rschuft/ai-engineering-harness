"""The real-browser driver's own rules (``browser_cdp.py``, U-01.2's gate G5): what the block lets through, what the
network log calls off loopback and escaped, the browser's command line, the throwaway profile. Offline: no browser
is started here (the driver itself runs only in the gated ``test_canvas_browser.py``)."""
import tempfile
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
               {'url': 'https://cdn.example/y', 'status': 200}, {'url': 'data:,x', 'status': 200}]
        self.assertEqual([r['url'] for r in B.off_loopback(log)], ['https://cdn.example/x', 'https://cdn.example/y'])
        self.assertEqual([r['url'] for r in B.escaped(log)], ['https://cdn.example/y'])

    def test_the_probe_is_a_request_the_block_must_stop(self):
        self.assertFalse(B.allowed(B.PROBE_URL))
        self.assertEqual(B.host_of(B.PROBE_URL), '192.0.2.1')


class CommandLine(unittest.TestCase):
    def test_headless_quiet_a_loopback_debugger_and_the_dead_proxy_for_everything_but_127_0_0_1(self):
        argv = B.launch_argv(Path('C:/b/chrome.exe'), Path('C:/scratch/profile'))
        for flag in ('--headless=new', '--disable-background-networking', '--disable-component-update',
                     '--no-first-run', '--disable-sync', '--disable-default-apps', '--disable-extensions',
                     '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                     '--proxy-server=http://127.0.0.1:9', '--proxy-bypass-list=<-loopback>;127.0.0.1',
                     f'--user-data-dir={Path("C:/scratch/profile")}'):
            self.assertIn(flag, argv)
        self.assertEqual(argv[0], str(Path('C:/b/chrome.exe')))
        self.assertEqual(argv[-1], 'about:blank')
        self.assertEqual(sum(a.startswith('--user-data-dir=') for a in argv), 1)

    def test_the_browser_is_chrome_or_edge_from_program_files_or_the_named_one(self):
        names = [p.name for p in B.candidates({'ProgramFiles': 'C:/PF', 'ProgramFiles(x86)': 'C:/PF86'})]
        self.assertEqual(names, ['chrome.exe', 'chrome.exe', 'msedge.exe', 'msedge.exe'])
        with self.assertRaises(B.BrowserError):
            B.find_browser('C:/no/such/browser.exe')


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
