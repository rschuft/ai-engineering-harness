import type { Plugin } from "vite";
import { CANVAS_ORIGIN } from "../src/engineering/session-detail.ts";

// The Owner host's content-security policy (plan leaf U-01.3; Proposed decision
// 0025, R4's consequence). The shell's origin holds the Owner UI session
// credential, so a script running in it would hold the session's authority:
// the policy lets the page load code only from its own origin and connect only
// to its own origin and to the Integration process (http://127.0.0.1:13310).
// No remote source is allowed anywhere. The page may frame one origin only:
// the standalone Agent Canvas application's, http://127.0.0.1:13330 (U-01.2;
// decision 0026 point 8; R4), which is never the shell's own.
//
// Two allowances, and why:
// - style-src 'unsafe-inline': Agent Canvas and its bundled libraries (goober,
//   react-aria, xterm) insert <style> elements at run time, and Vite's dev
//   server injects CSS the same way. Styles cannot run code.
// - img-src data:: Canvas shows the agent browser's screenshots as data: URLs.
//   A data: URL fetches nothing.
// The dev server alone also allows inline scripts (the React refresh preamble
// Vite injects); the built app, served by `vite preview`, does not.

export const INTEGRATION_ORIGIN = "http://127.0.0.1:13310";
export { CANVAS_ORIGIN };

export type PolicyMode = "build" | "dev";

export function policyDirectives(mode: PolicyMode): [string, string[]][] {
  return [
    ["default-src", ["'self'"]],
    ["script-src", mode === "dev" ? ["'self'", "'unsafe-inline'"] : ["'self'"]],
    ["style-src", ["'self'", "'unsafe-inline'"]],
    ["img-src", ["'self'", "data:"]],
    ["font-src", ["'self'"]],
    ["connect-src", ["'self'", INTEGRATION_ORIGIN]],
    ["worker-src", ["'self'"]],
    ["frame-src", [CANVAS_ORIGIN]],
    ["object-src", ["'none'"]],
    ["base-uri", ["'none'"]],
    ["form-action", ["'none'"]],
  ];
}

/** The policy as a header value; a header also forbids being framed (frame-ancestors). */
export function contentSecurityPolicy(mode: PolicyMode): string {
  return [...policyDirectives(mode), ["frame-ancestors", ["'none'"]] as [string, string[]]]
    .map(([name, sources]) => `${name} ${sources.join(" ")}`)
    .join("; ");
}

/** The policy as a <meta> element allows it (frame-ancestors is ignored there, so it is left out). */
export function metaPolicy(mode: PolicyMode = "build"): string {
  return policyDirectives(mode)
    .map(([name, sources]) => `${name} ${sources.join(" ")}`)
    .join("; ");
}

export const SECURITY_HEADERS = (mode: PolicyMode): Record<string, string> => ({
  "Content-Security-Policy": contentSecurityPolicy(mode),
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
});

/** Puts the build policy into the built index.html, so it holds wherever the files are served. */
export function ownerContentSecurityPolicy(): Plugin {
  return {
    name: "owner-host:content-security-policy",
    apply: "build",
    transformIndexHtml() {
      return [
        {
          tag: "meta",
          attrs: { "http-equiv": "Content-Security-Policy", content: metaPolicy("build") },
          injectTo: "head-prepend",
        },
      ];
    },
  };
}
