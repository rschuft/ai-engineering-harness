import { lazy, Suspense } from "react";
import { EmptyState } from "./EmptyState";
import { CanvasBoundary } from "../engineering/CanvasBoundary";

const CanvasMount = lazy(() => import("../engineering/CanvasMount"));

/**
 * The engineering area: Agent Canvas's native engineering view, embedded.
 * There is no Agent Server connection, so it states that and mounts Canvas
 * with no backend. Selecting an engineering session from an outcome is U-01.2.
 */
export function EngineeringArea() {
  return (
    <section
      className="owner-area owner-area--engineering"
      aria-labelledby="engineering-heading"
      data-testid="area-engineering"
    >
      <h2 id="engineering-heading" className="owner-area__title">
        Engineering
      </h2>
      <EmptyState title="No Agent Server is connected" testId="engineering-empty">
        <p>
          Engineering sessions come from an OpenHands Agent Server and are shown by Agent Canvas. The Owner host has no
          Agent Server connection, so there are no engineering sessions to show.
        </p>
        <p>How the Owner host will sign in to the Agent Server has not been decided yet.</p>
      </EmptyState>
      <div className="owner-canvas-frame" aria-label="Agent Canvas" role="region">
        <CanvasBoundary>
          <Suspense
            fallback={
              <p role="status" data-testid="canvas-loading">
                Loading Agent Canvas…
              </p>
            }
          >
            <CanvasMount />
          </Suspense>
        </CanvasBoundary>
      </div>
    </section>
  );
}
