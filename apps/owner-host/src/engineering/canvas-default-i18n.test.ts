// Characterization, kept in its own file because it changes Canvas's module
// state: without a host instance, Agent Canvas 1.36.0 builds an i18next
// instance that loads translations over HTTP from the host's own origin. This
// is why CanvasMount registers a host instance first (see canvas-i18n.ts).
import { expect, it } from "vitest";
import { getDefaultI18n } from "@openhands/agent-canvas";
import { takeNetworkAttempts } from "../test/network-guard";

it("Canvas's default i18n requests /locales/en/openhands.json", async () => {
  getDefaultI18n();
  await new Promise((resolve) => setTimeout(resolve, 200));
  expect(takeNetworkAttempts()).toEqual([{ api: "fetch", target: "/locales/en/openhands.json" }]);
});
