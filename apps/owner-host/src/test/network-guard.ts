// Records and refuses every network attempt the browser APIs could make in the
// test environment: fetch, XMLHttpRequest, WebSocket, EventSource and
// navigator.sendBeacon. The shell must attempt none of them; setup.ts fails any
// test after which an attempt was recorded.

export interface NetworkAttempt {
  api: "fetch" | "XMLHttpRequest" | "WebSocket" | "EventSource" | "sendBeacon";
  target: string;
}

export const networkAttempts: NetworkAttempt[] = [];

function describeTarget(input: unknown): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  if (input && typeof input === "object" && "url" in input) {
    return String((input as { url: unknown }).url);
  }
  return String(input);
}

function refuse(api: NetworkAttempt["api"], target: unknown): Error {
  const attempt = { api, target: describeTarget(target) };
  networkAttempts.push(attempt);
  return new Error(`network attempt refused in tests: ${api} ${attempt.target}`);
}

export function installNetworkGuard(): void {
  const g = globalThis as Record<string, unknown>;

  g.fetch = (input: unknown) => Promise.reject(refuse("fetch", input));

  const xhr = (g.XMLHttpRequest as { prototype: Record<string, unknown> } | undefined)?.prototype;
  if (xhr) {
    xhr.open = function open(_method: string, url: unknown) {
      throw refuse("XMLHttpRequest", url);
    };
    xhr.send = function send() {
      throw refuse("XMLHttpRequest", "(send)");
    };
  }

  g.WebSocket = class RefusedWebSocket {
    constructor(url: unknown) {
      throw refuse("WebSocket", url);
    }
  };

  g.EventSource = class RefusedEventSource {
    constructor(url: unknown) {
      throw refuse("EventSource", url);
    }
  };

  const nav = g.navigator as Record<string, unknown> | undefined;
  if (nav) {
    Object.defineProperty(nav, "sendBeacon", {
      configurable: true,
      value: (url: unknown) => {
        refuse("sendBeacon", url);
        return false;
      },
    });
  }
}

export function takeNetworkAttempts(): NetworkAttempt[] {
  return networkAttempts.splice(0, networkAttempts.length);
}
