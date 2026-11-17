// The outcome projection's committed answers (plan leaf U-04.2), for the outcome card's tests. Each
// fixture is made by integrations/ownerhost/tests/outcome_card_fixtures.py from the Integration
// process's own route over records the dispatcher's own writers made, and is pinned to projection.py
// by integrations/ownerhost/tests/test_outcome_card_fixtures.py. Nothing in them is written by hand.

export type Answer = { status: number; body: any };
export type OutcomeFixture = { scenario: string; source: string; generatedBy: string; route: string; answers: Answer[] };

const RAW = import.meta.glob("../areas/fixtures/outcome-projection/*.json", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

function raw(name: string): string {
  const text = RAW[`../areas/fixtures/outcome-projection/${name}.json`];
  if (text === undefined) throw new Error(`no outcome projection fixture ${name}`);
  return text;
}

/** The outcome every fixture projects (the dispatch fixtures' outcome). */
export const OUTCOME_ID = "3f6a2c1d-9b4e-4f7a-8c2d-5e1b0a9f7d63";

/** Every scenario's name. */
export const SCENARIOS = Object.keys(RAW)
  .map((path) => path.replace(/^.*\/(.*)\.json$/, "$1"))
  .filter((name) => name !== "schema");

export function fixture(name: string): OutcomeFixture {
  return JSON.parse(raw(name));
}

/** A fresh copy of the INDEX-th answer of scenario NAME. */
export function answer(name: string, index = 0): Answer {
  return fixture(name).answers[index];
}

/** The projection's constants (projection.py), as exported beside the fixtures. */
export function schema(): Record<string, any> {
  return JSON.parse(raw("schema"));
}
