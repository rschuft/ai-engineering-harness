// The one rule that takes Agent Canvas's remote @import rules out of a stylesheet (plan leaf U-01.1's ruling,
// applied again at U-01.2 to the standalone build). Agent Canvas 1.36.0's stylesheets start with two remote
// @import rules for Google Fonts (Outfit, IBM Plex Mono); left in, a browser would fetch from
// fonts.googleapis.com and fonts.gstatic.com. Blueprint #conversation (UI-01) anticipates this ("bundle or override
// its CSS Google Fonts imports when offline operation is required"); Canvas then renders with the fallback fonts of
// its own font stacks. The installed package is never modified: the library's stylesheet is rewritten by the
// build plugin (build/canvas-offline-fonts.ts), the standalone build is copied and its copy rewritten
// (scripts/canvas-standalone.mjs).
//
// Plain JavaScript (with remote-imports.d.mts for TypeScript) so that both the Vite plugin and the Node start
// command load the same rule.

// A quoted URL may itself contain ';' (the IBM Plex Mono weights list), so the URL is matched as a quoted string,
// optionally inside url(...).
const REMOTE_IMPORT = /@import\s+(?:url\(\s*)?(["'])(https?:\/\/[^"']*)\1\s*\)?[^;]*;/gi;

/** The stylesheet without its remote @import rules, and the URLs removed, in order. */
export function stripRemoteImports(css) {
  const removed = [];
  const out = css.replace(REMOTE_IMPORT, (_match, _quote, url) => {
    removed.push(url);
    return "";
  });
  return { css: out, removed };
}
