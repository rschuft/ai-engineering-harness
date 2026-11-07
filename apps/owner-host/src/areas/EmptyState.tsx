import type { ReactNode } from "react";

/**
 * A plain statement that a surface has nothing to show because its source is
 * not connected. It never shows sample or placeholder records.
 */
export function EmptyState({
  title,
  children,
  testId,
}: {
  title: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section className="owner-empty" role="status" data-testid={testId}>
      <h3 className="owner-empty__title">{title}</h3>
      <div className="owner-empty__body">{children}</div>
    </section>
  );
}
