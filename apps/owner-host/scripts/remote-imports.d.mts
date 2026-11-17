export interface StripResult {
  css: string;
  removed: string[];
}

/** The stylesheet without its remote @import rules, and the URLs removed, in order. */
export function stripRemoteImports(css: string): StripResult;
