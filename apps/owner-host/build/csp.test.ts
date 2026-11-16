import { describe, expect, it } from "vitest";
import config from "../vite.config.ts";
import { contentSecurityPolicy, INTEGRATION_ORIGIN, metaPolicy, ownerContentSecurityPolicy, policyDirectives } from "./csp";

// The shell's content-security policy (U-01.3): code only from the shell's own
// origin, connections only to that origin and to the Integration process.

function sources(policy: string): Map<string, string[]> {
  return new Map(
    policy.split(";").map((part) => {
      const [name, ...rest] = part.trim().split(/\s+/);
      return [name, rest] as [string, string[]];
    }),
  );
}

const NON_SELF = (source: string) => !["'self'", "'none'", "'unsafe-inline'", "data:"].includes(source);

describe("content-security policy", () => {
  it("allows only the shell origin and the Integration process as places to connect to or load from", () => {
    for (const mode of ["build", "dev"] as const) {
      const policy = sources(contentSecurityPolicy(mode));
      const origins = [...policy.values()].flat().filter(NON_SELF);
      expect(origins).toEqual([INTEGRATION_ORIGIN]);
      expect(policy.get("connect-src")).toEqual(["'self'", "http://127.0.0.1:13310"]);
      expect(policy.get("default-src")).toEqual(["'self'"]);
      expect(policy.get("frame-src")).toEqual(["'none'"]);
      expect(policy.get("object-src")).toEqual(["'none'"]);
      expect(policy.get("base-uri")).toEqual(["'none'"]);
      expect(policy.get("frame-ancestors")).toEqual(["'none'"]);
    }
  });

  it("runs no inline script in the built app; only the dev server allows Vite's preamble", () => {
    expect(sources(contentSecurityPolicy("build")).get("script-src")).toEqual(["'self'"]);
    expect(sources(contentSecurityPolicy("dev")).get("script-src")).toEqual(["'self'", "'unsafe-inline'"]);
    expect(sources(metaPolicy()).get("script-src")).toEqual(["'self'"]);
  });

  it("puts the build policy in the built page, before anything else in its head", () => {
    const plugin = ownerContentSecurityPolicy();
    expect(plugin.apply).toBe("build");
    const transform = plugin.transformIndexHtml as () => { tag: string; attrs: Record<string, string>; injectTo: string }[];
    expect(transform()).toEqual([
      { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: metaPolicy("build") }, injectTo: "head-prepend" },
    ]);
    expect(metaPolicy()).not.toContain("frame-ancestors");
    expect(policyDirectives("build").map(([name]) => name)).toContain("connect-src");
  });

  it("is sent by both servers, which bind 127.0.0.1 only", () => {
    expect(config.server?.host).toBe("127.0.0.1");
    expect(config.preview?.host).toBe("127.0.0.1");
    expect((config.preview?.headers as Record<string, string>)["Content-Security-Policy"]).toBe(contentSecurityPolicy("build"));
    expect((config.server?.headers as Record<string, string>)["Content-Security-Policy"]).toBe(contentSecurityPolicy("dev"));
    expect((config.preview?.headers as Record<string, string>)["Referrer-Policy"]).toBe("no-referrer");
  });
});
