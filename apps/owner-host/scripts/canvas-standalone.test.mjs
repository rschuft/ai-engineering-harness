// The standalone Agent Canvas server's derive step and start command (plan leaf U-01.2): the derived copy differs
// from the pinned build only as stated, the CSP option is off by default, the server's arguments and environment
// are exactly the rule's, and the start command serves upstream's own server on loopback (ephemeral ports here;
// never 13310, 13320 or 13330).
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer, request } from "node:http";
import { createServer as createNetServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import process from "node:process";
import { afterEach, describe, expect, it } from "vitest";
import {
  APP_DIR,
  CANVAS_PACKAGE,
  FIXTURE_UI_ACCESS,
  Refusal,
  canvasPackageDir,
  checkInstalled,
  checkPortFree,
  compareDerived,
  cspDirectives,
  cspPolicy,
  deriveBuild,
  injectedScript,
  inlineScripts,
  listFiles,
  parseOptions,
  serverEnvironment,
  staticServerArgs,
  withCsp,
} from "./canvas-standalone.mjs";

const FONT_A = '@import "https://fonts.googleapis.com/css2?family=Outfit:wght@100..900&display=swap";';
const FONT_B = '@import "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,100;1,700&display=swap";';
const INDEX_HTML =
  '<!DOCTYPE html><html lang="en"><head><meta charSet="utf-8"/><link rel="stylesheet" href="/assets/root.css"/>' +
  "<script>(() => { window.theme = 1; })();</script></head><body><script type=\"module\" async=\"\">import \"/assets/app.js\";</script>" +
  '<script src="/assets/other.js"></script></body></html>';

const scratch = [];
function tmp() {
  const dir = mkdtempSync(join(tmpdir(), "aieh-canvas-"));
  scratch.push(dir);
  return dir;
}
afterEach(() => {
  while (scratch.length) rmSync(scratch.pop(), { recursive: true, force: true });
});

function fakeBuild() {
  const root = join(tmp(), "pkg-build");
  mkdirSync(join(root, "assets"), { recursive: true });
  writeFileSync(join(root, "index.html"), INDEX_HTML);
  writeFileSync(join(root, "assets", "root.css"), `${FONT_A}${FONT_B}.a{color:red}`);
  writeFileSync(join(root, "assets", "app.js"), "export const x = 1;\n");
  writeFileSync(join(root, "assets", "other.js"), "console.log(1);\n");
  writeFileSync(join(root, "favicon.svg"), "<svg/>");
  return root;
}

function sha(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

describe("the derived build", () => {
  it("by default differs from the package only by the two remote font imports", () => {
    const source = fakeBuild();
    const out = tmp();
    const { dir, report } = deriveBuild(source, out);
    expect(report.changed).toEqual(["assets/root.css"]);
    expect(report.removed).toEqual([FONT_A.slice(9, -2), FONT_B.slice(9, -2)]);
    expect(report.csp).toBeNull();
    expect(readFileSync(join(dir, "assets", "root.css"), "utf8")).toBe(".a{color:red}");
    for (const file of ["index.html", "assets/app.js", "assets/other.js", "favicon.svg"]) {
      expect(sha(join(dir, file))).toBe(sha(join(source, file)));
    }
    expect(JSON.parse(readFileSync(join(out, "derived.json"), "utf8"))).toEqual(report);
  });

  it("refuses a copy in which anything else differs", () => {
    const source = fakeBuild();
    const { dir } = deriveBuild(source, tmp());
    writeFileSync(join(dir, "assets", "app.js"), "export const x = 2;\n");
    expect(() => compareDerived(source, dir)).toThrow(/CANVAS_BUILD_UNEXPECTED/);
    writeFileSync(join(dir, "assets", "app.js"), "export const x = 1;\n");
    writeFileSync(join(dir, "extra.js"), "1");
    expect(() => compareDerived(source, dir)).toThrow(/file sets differ/);
    rmSync(join(dir, "extra.js"));
    expect(compareDerived(source, dir).changed).toEqual(["assets/root.css"]);
    writeFileSync(join(dir, "assets", "root.css"), `${FONT_B}.a{color:red}`);
    expect(() => compareDerived(source, dir)).toThrow(/CANVAS_BUILD_UNEXPECTED/);
  });

  it("refuses a second changed stylesheet, and a policy that did not reach index.html", () => {
    const source = fakeBuild();
    writeFileSync(join(source, "assets", "zz.css"), ".z{}");
    const { dir } = deriveBuild(source, tmp());
    writeFileSync(join(dir, "assets", "zz.css"), ".z{color:blue}");
    expect(() => compareDerived(source, dir)).toThrow(/expected exactly one stylesheet to differ, found: assets\/root.css, assets\/zz.css/);
    const other = fakeBuild();
    const plain = deriveBuild(other, tmp());
    expect(() => compareDerived(other, plain.dir, { csp: "default-src 'self'" }))
      .toThrow(/expected exactly one stylesheet and index\.html to differ, found: assets\/root\.css$/);
  });

  it("refuses a package whose stylesheet has another number of remote imports, or one not from Google Fonts", () => {
    const one = fakeBuild();
    writeFileSync(join(one, "assets", "root.css"), `${FONT_A}.a{}`);
    expect(() => deriveBuild(one, tmp())).toThrow(/2 remote @import rules/);
    const other = fakeBuild();
    writeFileSync(join(other, "assets", "root.css"), `${FONT_A}@import "https://cdn.example/x.css";.a{}`);
    expect(() => deriveBuild(other, tmp())).toThrow(/not a Google Fonts stylesheet/);
  });

  it("never writes into the package and refuses an output that contains it", () => {
    const source = fakeBuild();
    const before = listFiles(source).map((f) => [f, sha(join(source, f))]);
    deriveBuild(source, tmp());
    expect(listFiles(source).map((f) => [f, sha(join(source, f))])).toEqual(before);
    expect(() => deriveBuild(source, join(source, ".."))).toThrow(/CANVAS_BUILD_DIR_INVALID/);
  });
});

describe("the content-security policy option (evidence for planning; off by default)", () => {
  it("is off unless asked for", () => {
    expect(parseOptions([]).csp).toBe(false);
    expect(parseOptions(["--csp"]).csp).toBe(true);
    expect(() => parseOptions(["--unknown"])).toThrow(Refusal);
  });

  it("puts one default-deny policy first in index.html, hashing every inline script and upstream's injected one", () => {
    const source = fakeBuild();
    const { dir, report } = deriveBuild(source, tmp(), { csp: true, port: 40123 });
    expect(report.changed).toEqual(["assets/root.css", "index.html"]);
    const html = readFileSync(join(dir, "index.html"), "utf8");
    expect(html.startsWith('<!DOCTYPE html><html lang="en"><head><meta http-equiv="Content-Security-Policy" content="')).toBe(true);
    expect(html).toBe(withCsp(INDEX_HTML, report.csp));
    const directives = Object.fromEntries(cspDirectives(INDEX_HTML, { port: 40123 }));
    expect(directives["default-src"]).toEqual(["'self'"]);
    expect(directives["img-src"]).toEqual(["'self'", "data:"]);
    expect(directives["connect-src"]).toEqual(["'self'", "ws://127.0.0.1:40123"]);
    expect(directives["object-src"]).toEqual(["'none'"]);
    const hashes = [...inlineScripts(INDEX_HTML), injectedScript()].map(
      (text) => `'sha256-${createHash("sha256").update(text, "utf8").digest("base64")}'`,
    );
    expect(inlineScripts(INDEX_HTML)).toHaveLength(2);
    expect(directives["script-src"]).toEqual(["'self'", ...hashes]);
    expect(report.csp).toBe(cspPolicy(INDEX_HTML, { port: 40123 }));
    expect(report.csp).not.toMatch(/unsafe-eval|\*|https?:/);
  });

  it("refuses an index.html changed beyond the policy's meta", () => {
    const source = fakeBuild();
    const { dir, report } = deriveBuild(source, tmp(), { csp: true });
    writeFileSync(join(dir, "index.html"), readFileSync(join(dir, "index.html"), "utf8") + " ");
    expect(() => compareDerived(source, dir, { csp: report.csp })).toThrow(/differs by more than the policy/);
  });
});

describe("the static server's arguments and environment", () => {
  it("are the rule's flags only: loopback, the three routes to the fixture's UI face, the public value, no telemetry", () => {
    expect(staticServerArgs({ dir: "D" })).toEqual([
      "--host", "127.0.0.1", "--port", "13330", "--dir", "D",
      "--route", "/api=http://127.0.0.1:13320/ui",
      "--route", "/sockets=http://127.0.0.1:13320/ui",
      "--route", "/server_info=http://127.0.0.1:13320/ui",
      "--session-api-key", "agentfixture-ui-face-public-value",
      "--disable-telemetry",
    ]);
    expect(FIXTURE_UI_ACCESS).toBe("agentfixture-ui-face-public-value");
    expect(() => staticServerArgs({ dir: "D", port: 0 })).toThrow(/PORT_INVALID/);
    expect(() => staticServerArgs({ dir: "" })).toThrow(/CANVAS_BUILD_DIR_INVALID/);
  });

  it("passes nothing of the caller's environment but what Windows needs, and keeps the DigitalOcean bridge off", () => {
    const env = serverEnvironment({
      SystemRoot: "C:\\Windows", TEMP: "T", PATH: "P", MARS_WEB: "1", MARS_TOKEN: "x", SESSION_API_KEY: "k",
      AGENT_CANVAS_DISABLE_TELEMETRY: "0", NODE_OPTIONS: "--require x", USERPROFILE: "U",
    });
    expect(env).toEqual({ SystemRoot: "C:\\Windows", TEMP: "T", MARS_WEB: "0" });
  });

  it("refuses a busy port (PORT_IN_USE), never another port", async () => {
    const held = createNetServer();
    await new Promise((resolve) => held.listen({ host: "127.0.0.1", port: 0, exclusive: true }, resolve));
    try {
      await expect(checkPortFree(held.address().port)).rejects.toThrow(/PORT_IN_USE/);
    } finally {
      await new Promise((resolve) => held.close(resolve));
    }
  });
});

describe("the installed package", () => {
  it("is checked against this app's lock, version and integrity", () => {
    const fake = tmp();
    const lock = { packages: {} };
    const installed = { packages: {} };
    for (const name of ["@openhands/agent-canvas", "sirv", "httpxy", "@polka/url", "mrmime", "totalist"]) {
      const entry = { version: name === CANVAS_PACKAGE ? "1.36.0" : "1.0.0", integrity: `sha512-${name}` };
      lock.packages[`node_modules/${name}`] = entry;
      installed.packages[`node_modules/${name}`] = { ...entry };
    }
    mkdirSync(join(fake, "node_modules", "@openhands", "agent-canvas"), { recursive: true });
    writeFileSync(join(fake, "node_modules", "@openhands", "agent-canvas", "package.json"), JSON.stringify({ version: "1.36.0" }));
    writeFileSync(join(fake, "package-lock.json"), JSON.stringify(lock));
    expect(() => checkInstalled(fake)).toThrow(/CANVAS_NOT_INSTALLED/);
    writeFileSync(join(fake, "node_modules", ".package-lock.json"), JSON.stringify(installed));
    expect(checkInstalled(fake)[CANVAS_PACKAGE].version).toBe("1.36.0");
    installed.packages["node_modules/httpxy"].integrity = "sha512-other";
    writeFileSync(join(fake, "node_modules", ".package-lock.json"), JSON.stringify(installed));
    expect(() => checkInstalled(fake)).toThrow(/CANVAS_INSTALL_MISMATCH/);
  });

  const installedHere = existsSync(join(canvasPackageDir(), "build", "index.html"));
  it.skipIf(!installedHere)("derives the pinned build: one stylesheet by default, and index.html too with the option", () => {
    expect(checkInstalled()[CANVAS_PACKAGE]).toEqual({
      version: "1.36.0",
      integrity: "sha512-ZumCENrBTfztpXRtRulOmTB/l/pBoOjWUO5x3ySNgOmHkV8OTkbe1WTyZoRbyEVagux/vlEyztuPgz/Ia+ecGQ==",
    });
    const source = join(canvasPackageDir(), "build");
    const plain = deriveBuild(source, tmp()).report;
    expect(plain.changed).toEqual(["assets/root-DpxuifD3.css"]);
    expect(plain.removed.every((u) => u.startsWith("https://fonts.googleapis.com/css2?family="))).toBe(true);
    const withPolicy = deriveBuild(source, tmp(), { csp: true }).report;
    expect(withPolicy.changed).toEqual(["assets/root-DpxuifD3.css", "index.html"]);
    expect(withPolicy.derivedSha256).toBe(plain.derivedSha256);
  }, 60000);
});

// -- the start command, served (a real process on ephemeral loopback ports; the fixture stood in by a stub) -----------

function get(port, path) {
  return new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, path, method: "GET" }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString("utf8") }));
    });
    req.on("error", reject);
    req.end();
  });
}

function freePort() {
  return new Promise((resolve) => {
    const probe = createNetServer();
    probe.listen({ host: "127.0.0.1", port: 0 }, () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

describe.skipIf(!existsSync(join(canvasPackageDir(), "build", "index.html")))("the start command", () => {
  it("serves upstream's server on loopback, with the rule's injections and routes, and stops when its input closes", async () => {
    const seen = [];
    const stub = createServer((req, res) => {
      seen.push(req.url);
      res.writeHead(200, { "content-type": "application/json", "x-stub": "fixture" });
      res.end('{"uptime":1,"idle_time":1}');
    });
    await new Promise((resolve) => stub.listen({ host: "127.0.0.1", port: 0 }, resolve));
    const fixturePort = stub.address().port;
    let port = await freePort();
    while ([13310, 13320, 13330].includes(port)) port = await freePort();
    const buildDir = tmp();
    const child = spawn(process.execPath, [join(APP_DIR, "scripts", "canvas-standalone.mjs"), "serve", "--build-dir", buildDir,
      "--port", String(port), "--fixture-port", String(fixturePort)], { cwd: APP_DIR, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    try {
      const ready = await new Promise((resolve, reject) => {
        let out = "";
        child.stdout.on("data", (chunk) => {
          out += chunk;
          const match = /listening 127\.0\.0\.1:(\d+) pid (\d+)/.exec(out);
          if (match) resolve({ port: Number(match[1]), pid: Number(match[2]), out });
        });
        child.once("exit", (code) => reject(new Error(`exited ${code}: ${out}`)));
      });
      expect(ready.port).toBe(port);
      expect(ready.out).toContain(`Static-server + proxy listening on http://127.0.0.1:${port}/`);
      const index = await get(port, "/");
      expect(index.status).toBe(200);
      // the exact script injectedScript() reproduces (the CSP option hashes it)
      expect(index.body).toContain(`<script>${injectedScript()}</script>`);
      expect(index.body).not.toContain("Content-Security-Policy");
      const info = await get(port, "/server_info");
      expect(info.headers["x-stub"]).toBe("fixture");
      await get(port, "/api/settings");
      expect(seen).toEqual(["/ui/server_info", "/ui/api/settings"]);
      const exited = new Promise((resolve) => child.once("exit", (code) => resolve(code)));
      child.stdin.end();
      expect(await exited).toBe(0);
    } finally {
      if (child.exitCode === null) child.kill();
      await new Promise((resolve) => stub.close(resolve));
    }
  }, 60000);
});

