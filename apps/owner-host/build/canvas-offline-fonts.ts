import type { Plugin } from "vite";

// Agent Canvas 1.36.0's stylesheet (@openhands/agent-canvas/styles.css) starts
// with two remote @import rules for Google Fonts (Outfit, IBM Plex Mono). Left
// in, a browser opening the engineering area would fetch from
// fonts.googleapis.com and fonts.gstatic.com. The Owner host makes no
// third-party requests, so this build step drops remote @import rules from
// that one stylesheet, as blueprint #conversation (UI-01) anticipates ("bundle
// or override its CSS Google Fonts imports when offline operation is
// required"). Canvas then renders with the fallback fonts of its own font
// stacks. The installed package is not modified.

/** Matches the Canvas stylesheet module id (no query), on any OS. */
export const CANVAS_STYLESHEET_ID = /[\\/]@openhands[\\/]agent-canvas[\\/]dist[\\/]styles\.css$/;

// A quoted URL may itself contain ';' (the IBM Plex Mono weights list), so the
// URL is matched as a quoted string, optionally inside url(...).
const REMOTE_IMPORT = /@import\s+(?:url\(\s*)?(["'])(https?:\/\/[^"']*)\1\s*\)?[^;]*;/gi;

export interface StripResult {
  css: string;
  removed: string[];
}

export function stripRemoteImports(css: string): StripResult {
  const removed: string[] = [];
  const out = css.replace(REMOTE_IMPORT, (_match, _quote: string, url: string) => {
    removed.push(url);
    return "";
  });
  return { css: out, removed };
}

export function canvasOfflineFonts(): Plugin {
  return {
    name: "owner-host:canvas-offline-fonts",
    enforce: "pre",
    transform(code, id) {
      if (!CANVAS_STYLESHEET_ID.test(id)) return null;
      const { css, removed } = stripRemoteImports(code);
      if (removed.length === 0) {
        this.warn("no remote @import found in the Agent Canvas stylesheet; check this step against the pinned version");
        return null;
      }
      return { code: css, map: null };
    },
  };
}
