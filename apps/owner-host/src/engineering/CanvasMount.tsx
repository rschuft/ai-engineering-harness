// Agent Canvas, embedded as a library in the Owner host's React tree
// (blueprint #conversation, UI-01: ADOPT Canvas embedding). This module is
// loaded lazily, only when the engineering area opens, so Canvas's code and
// stylesheet stay out of the other areas.
import "@openhands/agent-canvas/styles.css";
import type { ReactNode } from "react";
import { AgentServerUIProviders, setI18n } from "@openhands/agent-canvas";
import canvasPackage from "@openhands/agent-canvas/package.json";
import { createCanvasI18n } from "./canvas-i18n";

const canvasI18n = createCanvasI18n();
// Register before any Canvas provider renders: AgentServerUIProviders reads
// the current instance on mount, and would otherwise build Canvas's default,
// HTTP-loading instance.
setI18n(canvasI18n);

export const CANVAS_VERSION: string = canvasPackage.version;

/**
 * Canvas's providers and scoped root (`[data-agent-server-ui]`). Analytics is
 * off. No backend is registered, so Canvas's own backend registry stays at its
 * "no backend" state and its queries stay disabled. `children` is the seam
 * where U-01.2 places the selected engineering session.
 */
export default function CanvasMount({ children }: { children?: ReactNode }) {
  return (
    <AgentServerUIProviders analytics={false} i18n={canvasI18n} className="owner-canvas">
      {children ?? (
        <p data-testid="canvas-status" style={{ padding: "1rem", margin: 0 }}>
          Agent Canvas {CANVAS_VERSION} is loaded without an Agent Server. It has no engineering sessions to show.
        </p>
      )}
    </AgentServerUIProviders>
  );
}
