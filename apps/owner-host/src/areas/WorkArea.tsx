import { EmptyState } from "./EmptyState";

/**
 * Objectives and Work. Both surfaces are empty: no objective source (OpenSpec)
 * and no Work system (Backlog.md) is connected to the Owner host yet, and the
 * shell never shows sample records in their place.
 */
export function WorkArea() {
  return (
    <section className="owner-area owner-area--work" aria-labelledby="work-heading" data-testid="area-work">
      <h2 id="work-heading" className="owner-area__title">
        Work
      </h2>
      <div className="owner-work">
        <section className="owner-work__surface" aria-labelledby="objectives-heading" data-testid="surface-objectives">
          <h3 id="objectives-heading" className="owner-work__heading">
            Objectives
          </h3>
          <EmptyState title="No objectives to show" testId="objectives-empty">
            <p>No objective source is connected to the Owner host yet, so no objectives are listed here.</p>
          </EmptyState>
        </section>
        <section className="owner-work__surface" aria-labelledby="work-items-heading" data-testid="surface-work-items">
          <h3 id="work-items-heading" className="owner-work__heading">
            Work items
          </h3>
          <EmptyState title="No Work to show" testId="work-items-empty">
            <p>No Work system is connected to the Owner host yet, so no Work items or their status are listed here.</p>
          </EmptyState>
        </section>
      </div>
    </section>
  );
}
