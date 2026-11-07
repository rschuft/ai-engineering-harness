// CSS isolation evidence for Agent Canvas 1.36.0's stylesheet next to the
// Owner host's own stylesheet (compatibility matrix row "agent-canvas 1.36.0 /
// assistant-ui 0.15.32": "CSS isolation ([data-agent-server-ui] scope plus
// Google Fonts imports)"). Reads the upstream file as installed, unmodified.
import { describe, expect, it } from "vitest";
import canvasCss from "@openhands/agent-canvas/styles.css?raw";
import shellCss from "../shell/shell.css?raw";
import { auditCss, splitSelectorList } from "../test/css-rules";
import { stripRemoteImports } from "../../build/canvas-offline-fonts";

const SCOPE = "[data-agent-server-ui]";

function scoped(rule: { selector: string; context: string[] }): boolean {
  if (rule.context.some((c) => c.includes(SCOPE))) return true;
  return splitSelectorList(rule.selector).every((s) => s.includes(SCOPE));
}

const canvas = auditCss(canvasCss);
const shell = auditCss(shellCss);

describe("Agent Canvas stylesheet", () => {
  it("scopes every style rule under [data-agent-server-ui]", () => {
    expect(canvas.styleRules.length).toBeGreaterThan(1000);
    const unscoped = canvas.styleRules.filter((r) => !scoped(r)).map((r) => r.selector);
    expect(unscoped).toEqual([]);
  });

  it("has only keyframes and --tw-* custom property registrations as global at-rules", () => {
    const kinds = new Set(canvas.atRules.map((a) => a.split(/\s/)[0]));
    expect([...kinds].sort()).toEqual(["@keyframes", "@property"]);
    const properties = canvas.atRules.filter((a) => a.startsWith("@property")).map((a) => a.split(/\s+/)[1]);
    expect(properties.every((p) => p.startsWith("--tw-"))).toBe(true);
    expect(canvas.atRules.some((a) => a.startsWith("@font-face"))).toBe(false);
  });

  it("imports two Google Fonts stylesheets from the network, and nothing else", () => {
    expect(canvas.imports).toHaveLength(2);
    for (const statement of canvas.imports) {
      expect(statement).toMatch(/^@import "https:\/\/fonts\.googleapis\.com\/css2\?family=/);
    }
  });

  it("loses exactly those two imports in the host build, and nothing else", () => {
    const { css, removed } = stripRemoteImports(canvasCss);
    expect(removed).toHaveLength(2);
    expect(removed.every((url) => url.startsWith("https://fonts.googleapis.com/css2?family="))).toBe(true);
    expect(css).not.toMatch(/fonts\.googleapis\.com|@import/);
    expect(canvasCss.length - css.length).toBe(
      canvas.imports.reduce((n, statement) => n + statement.length, 0),
    );
    const after = auditCss(css);
    expect(after.styleRules.length).toBe(canvas.styleRules.length);
    expect(after.atRules).toEqual(canvas.atRules);
  });
});

describe("host stylesheet next to Canvas", () => {
  it("styles only html, body, #root, :root and .owner-* elements, so it cannot reach into Canvas's scope", () => {
    const offending = shell.styleRules
      .flatMap((r) => splitSelectorList(r.selector))
      .filter((s) => !/^(html|body|#root|:root|\.owner-[\w-]+)/.test(s));
    expect(offending).toEqual([]);
    expect(shell.styleRules.some((r) => /data-agent-server-ui|\.oh-|--oh-/.test(r.selector))).toBe(false);
  });

  it("names its custom properties --owner-*, disjoint from Canvas's --oh-* and --tw-* names", () => {
    const declared = [...shellCss.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]);
    expect(declared.length).toBeGreaterThan(0);
    expect(declared.every((name) => name.startsWith("--owner-"))).toBe(true);
    const canvasNames = new Set([...canvasCss.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
    expect(declared.filter((name) => canvasNames.has(name))).toEqual([]);
  });

  it("has no imports, fonts, keyframes or remote URLs, so no global name can collide with Canvas's", () => {
    expect(shell.imports).toEqual([]);
    expect(shell.atRules).toEqual([]);
    expect(shellCss).not.toMatch(/url\(|https?:\/\//);
  });
});
