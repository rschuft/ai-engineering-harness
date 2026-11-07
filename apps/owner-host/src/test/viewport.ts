// A controllable window.matchMedia for jsdom, which has none. It evaluates only
// the (min-width: Npx) and (max-width: Npx) queries the shell uses, against a
// simulated viewport width, and notifies listeners when the width changes. It
// does not lay anything out: CSS media queries and real rendering are only
// checked in a browser.

type Listener = (event: MediaQueryListEvent) => void;

interface FakeQuery {
  media: string;
  listeners: Set<Listener>;
  last: boolean;
}

let width = 1280;
const queries: FakeQuery[] = [];

// Any other query (Canvas and its bundled terminal ask for display-mode,
// prefers-color-scheme and others) reports false.
function evaluate(media: string, w: number): boolean {
  const parts = media.split(/\s+and\s+/i);
  return parts.every((part) => {
    const m = /^\s*\(\s*(min|max)-width\s*:\s*(\d+(?:\.\d+)?)px\s*\)\s*$/i.exec(part);
    if (!m) return false;
    const n = Number(m[2]);
    return m[1].toLowerCase() === "min" ? w >= n : w <= n;
  });
}

export function installMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (media: string): MediaQueryList => {
      const q: FakeQuery = { media, listeners: new Set(), last: evaluate(media, width) };
      queries.push(q);
      const list = {
        media,
        get matches() {
          return evaluate(media, width);
        },
        onchange: null,
        addEventListener: (_type: string, l: Listener) => q.listeners.add(l),
        removeEventListener: (_type: string, l: Listener) => q.listeners.delete(l),
        addListener: (l: Listener) => q.listeners.add(l),
        removeListener: (l: Listener) => q.listeners.delete(l),
        dispatchEvent: () => true,
      };
      return list as unknown as MediaQueryList;
    },
  });
}

export function setViewportWidth(next: number): void {
  width = next;
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: next });
  for (const q of queries) {
    const matches = evaluate(q.media, width);
    if (matches !== q.last) {
      q.last = matches;
      for (const l of q.listeners) l({ matches, media: q.media } as MediaQueryListEvent);
    }
  }
}

export function resetViewport(): void {
  queries.length = 0;
  setViewportWidth(1280);
}
