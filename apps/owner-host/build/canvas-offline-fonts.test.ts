import { describe, expect, it } from "vitest";
import { CANVAS_STYLESHEET_ID, canvasOfflineFonts, stripRemoteImports } from "./canvas-offline-fonts";

describe("stripRemoteImports", () => {
  it("removes remote @import rules, including quoted URLs that contain ';'", () => {
    const css = [
      '@import "https://fonts.example/css2?family=A:wght@0,100;0,200&display=swap";',
      "@import url('https://fonts.example/b.css') screen;",
      '@import "./local.css";',
      ".a{color:red}",
    ].join("\n");
    const { css: out, removed } = stripRemoteImports(css);
    expect(removed).toEqual(["https://fonts.example/css2?family=A:wght@0,100;0,200&display=swap", "https://fonts.example/b.css"]);
    expect(out).toContain('@import "./local.css";');
    expect(out).toContain(".a{color:red}");
    expect(out).not.toContain("fonts.example");
  });

  it("leaves a stylesheet without remote imports unchanged", () => {
    const css = ".a{background:url(https://x.example/i.png)}";
    expect(stripRemoteImports(css)).toEqual({ css, removed: [] });
  });
});

describe("canvasOfflineFonts plugin", () => {
  const plugin = canvasOfflineFonts();
  const transform = plugin.transform as (this: { warn: (m: string) => void }, code: string, id: string) => unknown;
  const ctx = { warn: () => {} };

  it("applies only to the Agent Canvas stylesheet module", () => {
    const css = '@import "https://fonts.googleapis.com/css2?family=Outfit";.a{}';
    expect(transform.call(ctx, css, "/app/node_modules/@openhands/agent-canvas/dist/styles.css")).toEqual({ code: ".a{}", map: null });
    expect(transform.call(ctx, css, "C:\\app\\node_modules\\@openhands\\agent-canvas\\dist\\styles.css")).toEqual({ code: ".a{}", map: null });
    expect(transform.call(ctx, css, "/app/src/shell/shell.css")).toBeNull();
    expect(transform.call(ctx, css, "/app/node_modules/@openhands/agent-canvas/dist/styles.css?raw")).toBeNull();
    expect(CANVAS_STYLESHEET_ID.test("/x/@openhands/agent-canvas/dist/styles.css")).toBe(true);
  });

  it("warns instead of failing when the pinned stylesheet no longer has remote imports", () => {
    const warnings: string[] = [];
    const result = transform.call({ warn: (m) => warnings.push(m) }, ".a{}", "/n/@openhands/agent-canvas/dist/styles.css");
    expect(result).toBeNull();
    expect(warnings).toHaveLength(1);
  });
});
