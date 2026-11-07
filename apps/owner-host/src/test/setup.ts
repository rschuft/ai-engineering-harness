import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { installNetworkGuard, takeNetworkAttempts } from "./network-guard";
import { installMatchMedia, resetViewport } from "./viewport";

// jsdom lacks ResizeObserver, which assistant-ui's thread viewport uses for
// auto-scroll. A no-op is enough: nothing in these tests depends on sizes.
class NoopResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

installNetworkGuard();
installMatchMedia();
if (!("ResizeObserver" in globalThis)) {
  (globalThis as Record<string, unknown>).ResizeObserver = NoopResizeObserver;
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetViewport();
  takeNetworkAttempts();
});

afterEach(() => {
  cleanup();
  const attempts = takeNetworkAttempts();
  if (attempts.length > 0) {
    throw new Error(`network attempts during the test: ${JSON.stringify(attempts)}`);
  }
});
