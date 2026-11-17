// The standalone Agent Canvas server (plan leaf U-01.2; the I1 design, R14 and R15; Proposed decision 0026 points
// 8 and 9): blueprint UI-01's fallback, Agent Canvas 1.36.0's own standalone application, served by upstream's own
// scripts/static-server.mjs on its own loopback origin (http://127.0.0.1:13330), its reverse proxy reaching only the
// served Agent Server fixture's read-only UI face (http://127.0.0.1:13320/ui). The Owner host frames it; the
// shell's origin, which holds the Owner UI session credential, never renders it.
//
//   node scripts/canvas-standalone.mjs derive [--build-dir DIR] [--port 13330] [--csp]
//   node scripts/canvas-standalone.mjs serve  [--build-dir DIR] [--port 13330] [--fixture-port 13320] [--csp]
//
// derive: checks the installed package against this app's lock (version and integrity, as `npm ci
//   --ignore-scripts` installed them), then copies the package's build/ to DIR/build with the two remote Google
//   Fonts @import rules removed (the U-01.1 ruling; scripts/remote-imports.mjs), and checks the copy byte for byte
//   against the package: exactly one file differs, by exactly those two rules, and no other file (no JavaScript
//   file) is changed, added or removed. Any other result is a refusal; nothing is served. The package itself is
//   never written.
// --csp (off by default; evidence for planning, NOT adopted: planning's reading of E-01.7 says the copy differs only
//   by the two font imports): also puts one <meta http-equiv="Content-Security-Policy"> first in the copy's
//   index.html, a default-deny policy (cspPolicy); the check then admits exactly that second difference.
// serve: derive, then run upstream's static server, unpatched, as its own process with no window:
//   --host 127.0.0.1 --port PORT --dir DIR/build, three --route prefixes (/api, /sockets, /server_info) to
//   http://127.0.0.1:FIXTURE_PORT/ui, --session-api-key with the fixture's public labelled UI-face value (not a
//   credential: decision 0026 point 9) and --disable-telemetry; its environment holds nothing of the caller's but
//   what Windows needs to start a process, and MARS_WEB=0 (upstream's DigitalOcean bridge stays unmounted). It
//   prints `listening 127.0.0.1:PORT pid N` once upstream's own ready line appears, and stops the server when it is
//   interrupted (Ctrl+C) or, when its standard input is a pipe, when that pipe closes (then it exits 0). A busy port
//   is a refusal (PORT_IN_USE), never another port.
//
// DIR defaults to node_modules/.cache/aieh-canvas-standalone (ignored, and emptied by every `npm ci`).

import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join, relative, resolve, sep } from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { stripRemoteImports } from "./remote-imports.mjs";

export const APP_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const LOOPBACK = "127.0.0.1";
export const CANVAS_PORT = 13330;
export const FIXTURE_PORT = 13320;
export const FIXTURE_UI_PREFIX = "/ui";
/** The fixture's public labelled access value for its UI face (integrations/agentfixture/server.py UI_ACCESS). */
export const FIXTURE_UI_ACCESS = "agentfixture-ui-face-public-value";
/** The prefixes Canvas calls on its backend, as upstream's own launcher routes them to an Agent Server. */
export const PROXIED_PREFIXES = ["/api", "/sockets", "/server_info"];
export const CANVAS_PACKAGE = "@openhands/agent-canvas";
export const CANVAS_VERSION = "1.36.0";
/** The packages upstream's static server loads besides Node's own modules (sirv's closure, httpxy). */
export const SERVER_PACKAGES = [CANVAS_PACKAGE, "sirv", "httpxy", "@polka/url", "mrmime", "totalist"];
export const EXPECTED_REMOTE_IMPORTS = 2;
export const READY_LINE = /^Static-server \+ proxy listening on http:\/\/127\.0\.0\.1:(\d+)\/$/;
export const DEFAULT_BUILD_DIR = join(APP_DIR, "node_modules", ".cache", "aieh-canvas-standalone");
export const INDEX = "index.html";
const HEAD = "<head>";
// What a Windows process needs to start; nothing else of the caller's environment is passed.
const KEPT_ENV = ["SystemRoot", "SYSTEMROOT", "windir", "WINDIR", "TEMP", "TMP"];

export class Refusal extends Error {
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.code = code;
    this.detail = detail;
  }
}

export function canvasPackageDir(appDir = APP_DIR) {
  return join(appDir, "node_modules", ...CANVAS_PACKAGE.split("/"));
}

export function staticServerScript(appDir = APP_DIR) {
  return join(canvasPackageDir(appDir), "scripts", "static-server.mjs");
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

/**
 * The installed packages the server runs, checked against the app's lock: the lock pins Canvas at CANVAS_VERSION,
 * and npm's record of what it installed (node_modules/.package-lock.json) holds, for each package the server loads,
 * the lock's own version and integrity. Returns {package: {version, integrity}}.
 */
export function checkInstalled(appDir = APP_DIR) {
  const lock = readJson(join(appDir, "package-lock.json")).packages ?? {};
  const hiddenPath = join(appDir, "node_modules", ".package-lock.json");
  if (!existsSync(hiddenPath)) throw new Refusal("CANVAS_NOT_INSTALLED", "run npm ci --ignore-scripts in apps/owner-host");
  const installed = readJson(hiddenPath).packages ?? {};
  const out = {};
  for (const name of SERVER_PACKAGES) {
    const key = `node_modules/${name}`;
    const want = lock[key];
    const have = installed[key];
    if (!want || !have) throw new Refusal("CANVAS_NOT_INSTALLED", `${name} is not in the lock or not installed`);
    if (want.version !== have.version || !want.integrity || want.integrity !== have.integrity) {
      throw new Refusal("CANVAS_INSTALL_MISMATCH", `${name}: installed ${have.version} ${have.integrity}, locked ${want.version} ${want.integrity}`);
    }
    out[name] = { version: want.version, integrity: want.integrity };
  }
  if (out[CANVAS_PACKAGE].version !== CANVAS_VERSION) {
    throw new Refusal("CANVAS_INSTALL_MISMATCH", `${CANVAS_PACKAGE} is ${out[CANVAS_PACKAGE].version}, not ${CANVAS_VERSION}`);
  }
  const manifest = readJson(join(canvasPackageDir(appDir), "package.json"));
  if (manifest.version !== CANVAS_VERSION) {
    throw new Refusal("CANVAS_INSTALL_MISMATCH", `the installed ${CANVAS_PACKAGE} says ${manifest.version}`);
  }
  return out;
}

/** Every file under ROOT, as sorted '/'-separated relative paths. */
export function listFiles(root) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) out.push(relative(root, path).split(sep).join("/"));
      else throw new Refusal("CANVAS_BUILD_UNEXPECTED", `${path} is neither a file nor a directory`);
    }
  };
  walk(root);
  return out.sort();
}

// -- the content-security policy option (evidence for planning; off by default) ------------------------------------

/** The text of every inline <script> of HTML (no src attribute), in document order. */
export function inlineScripts(html) {
  return [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map((m) => m[1]);
}

/**
 * The script upstream's static server injects before </head> for this start command's flags (--session-api-key,
 * --disable-telemetry): its makeConfigInjectionScript at the pin, for a key that needs no escaping. A test serves
 * the page and finds exactly this script in it.
 */
export function injectedScript(sessionApiKey = FIXTURE_UI_ACCESS) {
  if (!/^[A-Za-z0-9-]+$/.test(sessionApiKey)) throw new Refusal("KEY_INVALID", "a key outside [A-Za-z0-9-]");
  const k = JSON.stringify(sessionApiKey);
  return (
    "(function(){" +
    `window.__AGENT_CANVAS_SESSION_API_KEY__=${k};` +
    `try{var _k='openhands-agent-server-config',_c=JSON.parse(localStorage.getItem(_k)||'{}');` +
    `if(_c.sessionApiKey!==${k}){_c.sessionApiKey=${k};localStorage.setItem(_k,JSON.stringify(_c));}}catch(e){}` +
    "window.__AGENT_CANVAS_DO_NOT_TRACK__=true;" +
    "}());"
  );
}

function scriptHash(text) {
  return `'sha256-${createHash("sha256").update(text, "utf8").digest("base64")}'`;
}

/**
 * The default-deny policy for the page served from 127.0.0.1:PORT: everything from its own origin only; inline
 * scripts only by the hashes of the page's own and the injected one; inline styles (Canvas inserts <style> elements
 * and style attributes at run time); images from itself and data: URLs; connections to itself and its own ws origin.
 * As [directive, sources] pairs.
 */
export function cspDirectives(indexHtml, { port = CANVAS_PORT } = {}) {
  const hashes = [...new Set([...inlineScripts(indexHtml), injectedScript()].map(scriptHash))];
  return [
    ["default-src", ["'self'"]],
    ["script-src", ["'self'", ...hashes]],
    ["style-src", ["'self'", "'unsafe-inline'"]],
    ["img-src", ["'self'", "data:"]],
    ["font-src", ["'self'"]],
    ["connect-src", ["'self'", `ws://${LOOPBACK}:${port}`]],
    ["worker-src", ["'self'"]],
    ["object-src", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["form-action", ["'self'"]],
  ];
}

export function cspPolicy(indexHtml, options) {
  return cspDirectives(indexHtml, options).map(([name, sources]) => `${name} ${sources.join(" ")}`).join("; ");
}

export function cspMeta(policy) {
  return `<meta http-equiv="Content-Security-Policy" content="${policy}"/>`;
}

/** INDEX_HTML with the policy's <meta> first in its <head>. */
export function withCsp(indexHtml, policy) {
  if (indexHtml.split(HEAD).length !== 2) throw new Refusal("CANVAS_BUILD_UNEXPECTED", "index.html has not exactly one <head>");
  return indexHtml.replace(HEAD, HEAD + cspMeta(policy));
}

// -- the derived copy ------------------------------------------------------------------------------------------------

/**
 * The derived copy's check, byte for byte: SOURCE and COPY hold the same files; one differs, a stylesheet whose copy
 * equals the source with exactly EXPECTED_REMOTE_IMPORTS remote @import rules taken out; with a CSP POLICY, index.html
 * differs too, by exactly that policy's <meta> first in <head>; nothing else differs. Returns the report; throws a
 * Refusal otherwise.
 */
export function compareDerived(source, copy, { csp = null } = {}) {
  const sourceFiles = listFiles(source);
  const copyFiles = listFiles(copy);
  const missing = sourceFiles.filter((f) => !copyFiles.includes(f));
  const added = copyFiles.filter((f) => !sourceFiles.includes(f));
  if (missing.length || added.length) {
    throw new Refusal("CANVAS_BUILD_UNEXPECTED", `file sets differ: missing ${missing.join(", ") || "-"}, added ${added.join(", ") || "-"}`);
  }
  const changed = sourceFiles.filter((f) => !readFileSync(join(source, f)).equals(readFileSync(join(copy, f))));
  const stylesheets = changed.filter((f) => f !== INDEX || !csp);
  if (stylesheets.length !== 1 || !stylesheets[0].endsWith(".css") || (csp && !changed.includes(INDEX))) {
    throw new Refusal("CANVAS_BUILD_UNEXPECTED", `expected exactly one stylesheet${csp ? " and index.html" : ""} to differ, found: ${changed.join(", ") || "none"}`);
  }
  const [file] = stylesheets;
  const original = readFileSync(join(source, file), "utf8");
  const { css, removed } = stripRemoteImports(original);
  const derived = readFileSync(join(copy, file));
  if (removed.length !== EXPECTED_REMOTE_IMPORTS || !Buffer.from(css, "utf8").equals(derived)) {
    throw new Refusal("CANVAS_BUILD_UNEXPECTED", `${file} differs by more than its ${EXPECTED_REMOTE_IMPORTS} remote @import rules`);
  }
  if (removed.some((url) => !url.startsWith("https://fonts.googleapis.com/"))) {
    throw new Refusal("CANVAS_BUILD_UNEXPECTED", `${file} has a remote @import that is not a Google Fonts stylesheet`);
  }
  const report = {
    files: sourceFiles.length,
    changed,
    removed,
    originalSha256: sha256(readFileSync(join(source, file))),
    derivedSha256: sha256(derived),
    csp: null,
  };
  if (csp) {
    const expected = withCsp(readFileSync(join(source, INDEX), "utf8"), csp);
    if (!Buffer.from(expected, "utf8").equals(readFileSync(join(copy, INDEX)))) {
      throw new Refusal("CANVAS_BUILD_UNEXPECTED", `${INDEX} differs by more than the policy's <meta>`);
    }
    report.csp = csp;
  }
  return report;
}

/**
 * The derived copy of SOURCE (the package's build/) at OUT/build, with the two remote @import rules removed from
 * the one stylesheet that has them and, with CSP, the policy's <meta> first in index.html; checked by
 * compareDerived. OUT/build is replaced; the package is only read.
 */
/** Whether PATH is DIR or lies under it (resolved, compared case-insensitively on Windows). */
export function within(path, dir) {
  const fold = (p) => (process.platform === "win32" ? resolve(p).toLowerCase() : resolve(p));
  const a = fold(path);
  const b = fold(dir);
  return a === b || a.startsWith(b.endsWith(sep) ? b : b + sep);
}

/** The marker derive writes beside the copy (OUT/derived.json): only a directory carrying it may be replaced. */
export function isDerivedMarker(path) {
  try {
    const marker = JSON.parse(readFileSync(path, "utf8"));
    return Array.isArray(marker.changed) && Array.isArray(marker.removed) && Number.isInteger(marker.files) && "csp" in marker;
  } catch {
    return false;
  }
}

export function deriveBuild(source, out, { csp = false, port = CANVAS_PORT } = {}) {
  const resolvedOut = resolve(out);
  const target = join(resolvedOut, "build");
  const pkg = dirname(resolve(source));
  // review S2: never inside the source package, never around it; checked before anything is written
  if (within(resolvedOut, pkg) || within(pkg, resolvedOut)) {
    throw new Refusal("CANVAS_BUILD_DIR_INVALID", `the derived copy must be outside the package (${pkg}) and must not contain it`);
  }
  // review S2: an existing build/ is replaced only when it is this step's own (its marker beside it)
  if (existsSync(target) && !isDerivedMarker(join(resolvedOut, "derived.json"))) {
    throw new Refusal("CANVAS_BUILD_DIR_INVALID", `${target} exists and is not a derived copy (no derived.json beside it): refusing to replace it`);
  }
  rmSync(target, { recursive: true, force: true });
  const policy = csp ? cspPolicy(readFileSync(join(source, INDEX), "utf8"), { port }) : null;
  for (const file of listFiles(source)) {
    const to = join(target, ...file.split("/"));
    mkdirSync(dirname(to), { recursive: true });
    let bytes = readFileSync(join(source, file));
    if (file.endsWith(".css")) {
      const { css, removed } = stripRemoteImports(bytes.toString("utf8"));
      if (removed.length > 0) bytes = Buffer.from(css, "utf8");
    } else if (file === INDEX && policy) {
      bytes = Buffer.from(withCsp(bytes.toString("utf8"), policy), "utf8");
    }
    writeFileSync(to, bytes);
  }
  const report = compareDerived(source, target, { csp: policy });
  writeFileSync(join(resolvedOut, "derived.json"), JSON.stringify(report, null, 2) + "\n");
  return { dir: target, report };
}

// -- the server ------------------------------------------------------------------------------------------------------

/** The static server's own arguments (its help text's flags only). */
export function staticServerArgs({ port = CANVAS_PORT, fixturePort = FIXTURE_PORT, dir }) {
  for (const value of [port, fixturePort]) {
    if (!Number.isInteger(value) || value < 1 || value > 65535) throw new Refusal("PORT_INVALID", String(value));
  }
  if (typeof dir !== "string" || !dir) throw new Refusal("CANVAS_BUILD_DIR_INVALID", "no directory to serve");
  const target = `http://${LOOPBACK}:${fixturePort}${FIXTURE_UI_PREFIX}`;
  const args = ["--host", LOOPBACK, "--port", String(port), "--dir", dir];
  for (const prefix of PROXIED_PREFIXES) args.push("--route", `${prefix}=${target}`);
  args.push("--session-api-key", FIXTURE_UI_ACCESS, "--disable-telemetry");
  return args;
}

/** The server process's environment: what Windows needs to start a process, and MARS_WEB=0; nothing else. */
export function serverEnvironment(env = process.env) {
  const out = {};
  for (const name of KEPT_ENV) {
    if (typeof env[name] === "string") out[name] = env[name];
  }
  out.MARS_WEB = "0";
  return out;
}

/** Refuses (PORT_IN_USE) when 127.0.0.1:PORT cannot be bound exclusively now. */
// The addresses an exclusive bind probe tries (review N6): a holder on 0.0.0.0, 127.0.0.1 or :: is found by its own
// address; a holder on any other address by the TCP table.
export const PROBE_HOSTS = ["0.0.0.0", "127.0.0.1", "::"];

function probeBind(host, port) {
  return new Promise((resolveProbe) => {
    const probe = createServer();
    probe.once("error", (error) => resolveProbe(error.code === "EADDRNOTAVAIL" || error.code === "EAFNOSUPPORT" ? null : error.code ?? "error"));
    probe.listen({ host, port, exclusive: true }, () => probe.close(() => resolveProbe(null)));
  });
}

/** The local addresses listening on PORT in a `netstat -ano` text (the platform's TCP table), any address family. */
export function listeningIn(netstat, port) {
  const out = [];
  for (const line of netstat.split(/\r?\n/)) {
    const m = /^\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\b/i.exec(line);
    if (m && Number(m[2]) === port) out.push(m[1]);
  }
  return out;
}

function tcpTable() {
  if (process.platform !== "win32") return "";
  const result = spawnSync("netstat", ["-ano", "-p", "TCP"], { encoding: "utf8", windowsHide: true, timeout: 60000 });
  const six = spawnSync("netstat", ["-ano", "-p", "TCPv6"], { encoding: "utf8", windowsHide: true, timeout: 60000 });
  return `${result.stdout ?? ""}\n${six.stdout ?? ""}`;
}

/**
 * Refuses (PORT_IN_USE) when PORT is in use on any address, as the Integration process's rule has it
 * (integrations/platform/platform_windows.py port_in_use): an exclusive bind of each of PROBE_HOSTS fails, or the
 * platform's TCP table lists a listener on the port. Never another port.
 */
export async function checkPortFree(port, { table = tcpTable } = {}) {
  for (const host of PROBE_HOSTS) {
    const code = await probeBind(host, port);
    if (code !== null) throw new Refusal("PORT_IN_USE", `${host}:${port}: ${code}`);
  }
  const listening = listeningIn(table(), port);
  if (listening.length > 0) throw new Refusal("PORT_IN_USE", `port ${port} is listening on ${listening.join(", ")}`);
}

export function parseOptions(argv) {
  const options = { buildDir: DEFAULT_BUILD_DIR, port: CANVAS_PORT, fixturePort: FIXTURE_PORT, csp: false };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    const value = argv[i + 1];
    if (flag === "--csp") {
      options.csp = true;
      continue;
    }
    if (flag === "--build-dir" && value) options.buildDir = resolve(value);
    else if (flag === "--port" && value) options.port = Number(value);
    else if (flag === "--fixture-port" && value) options.fixturePort = Number(value);
    else throw new Refusal("USAGE", `unknown or incomplete option ${flag}`);
    i++;
  }
  return options;
}

/** derive: the checks and the copy. */
export function derive(options, appDir = APP_DIR) {
  const installed = checkInstalled(appDir);
  const { dir, report } = deriveBuild(join(canvasPackageDir(appDir), "build"), options.buildDir,
    { csp: options.csp, port: options.port });
  return { installed, dir, report };
}

/** serve: derive, then upstream's static server as a child process; resolves with its exit code (0 when stopped). */
export async function serve(options, { appDir = APP_DIR, stdout = process.stdout, stderr = process.stderr, stdin = process.stdin } = {}) {
  const { dir } = derive(options, appDir);
  await checkPortFree(options.port);
  const args = [staticServerScript(appDir), ...staticServerArgs({ port: options.port, fixturePort: options.fixturePort, dir })];
  const child = spawn(process.execPath, args, {
    cwd: appDir,
    env: serverEnvironment(),
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  let ready = false;
  let stopping = false;
  let pending = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    pending += chunk;
    let at;
    while ((at = pending.indexOf("\n")) >= 0) {
      const line = pending.slice(0, at).replace(/\r$/, "");
      pending = pending.slice(at + 1);
      stdout.write(`${line}\n`);
      const match = READY_LINE.exec(line);
      if (!ready && match && Number(match[1]) === options.port) {
        ready = true;
        stdout.write(`listening ${LOOPBACK}:${options.port} pid ${child.pid}\n`);
      }
    }
  });
  child.stderr.pipe(stderr, { end: false });
  const stop = () => {
    stopping = true;
    if (child.exitCode === null && child.signalCode === null) child.kill();
  };
  const signals = ["SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"];
  for (const signal of signals) process.once(signal, stop);
  if (stdin && !stdin.isTTY) {
    stdin.on("end", stop);
    stdin.on("close", stop);
    stdin.resume();
  }
  return new Promise((resolveExit) => {
    child.once("exit", (code, signal) => {
      for (const signal of signals) process.removeListener(signal, stop);
      if (stdin && !stdin.isTTY) {
        stdin.removeListener("end", stop);
        stdin.removeListener("close", stop);
        stdin.pause();
      }
      resolveExit(stopping ? 0 : (code ?? (signal ? 1 : 0)));
    });
  });
}

export async function main(argv = process.argv.slice(2)) {
  const [verb, ...rest] = argv;
  try {
    const options = parseOptions(rest);
    if (verb === "derive") {
      const { installed, dir, report } = derive(options);
      process.stdout.write(JSON.stringify({ installed: installed[CANVAS_PACKAGE], dir, ...report }, null, 2) + "\n");
      return 0;
    }
    if (verb === "serve") return await serve(options);
    throw new Refusal("USAGE", "node scripts/canvas-standalone.mjs derive|serve [--build-dir DIR] [--port N] [--fixture-port N] [--csp]");
  } catch (error) {
    if (error instanceof Refusal) {
      process.stderr.write(`${error.message}\n`);
      return 2;
    }
    throw error;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  process.exitCode = await main();
}
