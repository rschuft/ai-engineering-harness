import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { OwnerApp } from "../App";
import { ownerRoutes } from "../routes";

// The precondition of U-01.3's review (S4): the shell's origin holds the Owner
// UI session credential, so until U-01.2 moves Agent Canvas to its own origin
// (decision 0026 point 8) the embedded Canvas has no backend and renders no
// agent-authored content. Canvas would find a backend in localStorage under
// `openhands-backends` or in `window.__AGENT_CANVAS_SESSION_API_KEY__`.

const BACKEND_MARKERS = ["openhands-backends", "__AGENT_CANVAS_SESSION_API_KEY__", "addBackend", "setActiveBackend"];

const shellSources = import.meta.glob(["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../test/**"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("the embedded Canvas has no backend", () => {
  it("configures none when the engineering area opens", async () => {
    const router = createMemoryRouter(ownerRoutes, { initialEntries: ["/engineering"] });
    render(<OwnerApp router={router} />);
    // Canvas is a lazy chunk: its first load in a fresh worker takes longer than the default wait
    await screen.findByTestId("canvas-status", undefined, { timeout: 20000 });
    expect(window.localStorage.getItem("openhands-backends")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__AGENT_CANVAS_SESSION_API_KEY__).toBeUndefined();
  }, 30000);

  it("is given none anywhere in the shell's own code", () => {
    const files = Object.keys(shellSources);
    expect(files.length).toBeGreaterThan(10);
    for (const [file, text] of Object.entries(shellSources)) {
      for (const marker of BACKEND_MARKERS) {
        expect(text.includes(marker), `${file} mentions ${marker}`).toBe(false);
      }
    }
  });
});
