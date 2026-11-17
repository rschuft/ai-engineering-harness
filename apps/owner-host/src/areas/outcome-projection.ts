// The outcome projection as the outcome card reads it (plan leaf U-04.2; the Integration process's
// `GET /outcomes/{outcome_id}`, U-04.1: integrations/ownerhost/projection.py and its README's state table).
//
// Everything here is a reading of the projection's own fields: no status is computed from anything
// else, and nothing is inferred about the Work item. An attempt's `executionStatus` is shown as one
// of the projection's five statuses; any other value is shown as unknown, never as a success. The
// constants are pinned to the projection by fixtures/outcome-projection/schema.json, which
// integrations/ownerhost/tests/test_outcome_card_fixtures.py checks against projection.py.

export const OUTCOME_FORMAT = "outcome-projection/v1";
export const EXECUTION_STATUSES = ["pending", "running", "failed", "unknown", "succeeded"] as const;
export type ExecutionStatus = (typeof EXECUTION_STATUSES)[number];
export const UNPROVEN_SUFFIX = "_UNPROVEN";
export const FIXTURE_AUTHORITY_CODE = "FIXTURE_AUTHORITY";
export const LINEAGE_VERDICTS = ["complete", "incomplete", "failed"] as const;

/** The status as the card words it. `succeeded` is a published, verified result, never "done" for the Work. */
export const STATUS_LABEL: Record<ExecutionStatus, string> = {
  pending: "Pending",
  running: "Running",
  failed: "Failed",
  unknown: "Unknown",
  succeeded: "Result published, verified at publication",
};

export const STATUS_MEANING: Record<ExecutionStatus, string> = {
  pending: "Nothing the dispatcher recorded shows it under way yet.",
  running: "The dispatcher's records show it under way.",
  failed: "The dispatcher's records show that it failed.",
  unknown: "The dispatcher's records do not determine what happened; it is not taken to be pending or failed.",
  succeeded:
    "The host verified the result and read its branch and draft pull request back when it published it; a later change on Gitea is not reflected. The Work item's own status is not changed by this.",
};

/** Each code of the projection's state table (integrations/ownerhost/README.md), in plain words. */
export const CODE_MEANING: Record<string, string> = {
  ATTEMPT_AUTHORITY_UNBOUND: "The attempt's pinned route allowlist cannot be read, so its authority is neither live nor fixture.",
  ATTEMPT_LABEL_MISSING: "A record of a fixture-bound attempt lacks its fixture label, so its authority is not shown.",
  ATTEMPT_LABEL_MISMATCH: "A record carries another authority than the attempt is bound to.",
  ATTEMPT_LABEL_ON_LIVE: "A record of a live-bound attempt carries an authority label.",
  RECORD_UNREADABLE: "A record of the attempt is in a state or form the table does not read.",
  ATTEMPT_RESERVED: "The attempt is reserved; no create is recorded.",
  CREATE_SENT: "The create is recorded sent; its answer is not recorded.",
  CREATE_OUTCOME_UNKNOWN: "The create's answer was lost.",
  ATTEMPT_FAILED: "The attempt failed before it ran (a refused create, an admission refusal or a reconciled 404).",
  LAUNCH_NOT_LAUNCHED: "The launch gate did not launch it.",
  ATTEMPT_STOPPED: "The dispatcher recorded a stop.",
  ATTEMPT_ENDED: "The attempt was ended.",
  ATTEMPT_END_UNSETTLED: "The end's outcome was not recorded.",
  ATTEMPT_ENDING: "The attempt is being ended.",
  RESULT_PUBLISHED: "The result receipt is recorded: the result was verified and read back when it was published.",
  RESULT_FAILED: "The result path failed.",
  RESULT_WRITE_UNSETTLED: "A write of the result path was refused or its answer lost.",
  RESULT_PUBLISHING: "The result is being published.",
  RESULT_VERIFIED: "The host verified the result; no publication is recorded.",
  RESULT_DELIVERED: "The attempt delivered a result (reported); the host has not verified it.",
  TURN_OUTCOME_UNKNOWN: "The message's answer was lost.",
  TURN_FAILED: "The message failed.",
  TURN_SENT: "The message is recorded delivered; no result is recorded.",
  MESSAGE_SENDING: "The message is recorded being sent; its answer is not recorded.",
  MESSAGE_RESERVED: "The message is reserved; none is recorded sent.",
  LAUNCHED: "Launched; no message is recorded.",
  CREATED: "The create is recorded answered; no later record.",
  NO_ATTEMPT: "The integration store was read and holds no attempt for this task.",
  STORE_UNAVAILABLE: "The integration store could not be read.",
  RESULT_RECEIPT_UNSETTLED: "A result-step receipt is unknown or failed: what the result step did is not recorded.",
};

const UNKNOWN_CODE = "A code this card does not know; it is shown as the projection gave it.";

/** The plain words of CODE; an `_UNPROVEN` code says that a restore is why it is unknown. */
export function codeMeaning(code: unknown): string {
  if (typeof code !== "string" || code.length === 0) return "No code was given.";
  if (code.endsWith(UNPROVEN_SUFFIX)) {
    const row = code.slice(0, -UNPROVEN_SUFFIX.length);
    const base = row === "NO_ATTEMPT" ? "No attempt is recorded." : CODE_MEANING[row];
    if (base !== undefined) {
      return `Unproven after a restore of the integration store: the records would read "${base}", but the restored history cannot prove that nothing later was recorded.`;
    }
    return UNKNOWN_CODE;
  }
  return CODE_MEANING[code] ?? UNKNOWN_CODE;
}

/** One of the five statuses; anything else is unknown (never pending, failed or succeeded). */
export function shownStatus(value: unknown): ExecutionStatus {
  return (EXECUTION_STATUSES as readonly unknown[]).includes(value) ? (value as ExecutionStatus) : "unknown";
}

export const VERDICT_MEANING: Record<(typeof LINEAGE_VERDICTS)[number], string> = {
  complete: "Every reference of the outcome resolves and nothing is uncertain.",
  incomplete: "The references resolve, but some sources are uncertain (listed below).",
  failed: "A reference of the outcome does not resolve (listed below).",
};

// ---------------------------------------------------------------------------------------------- reading

export type Json = Record<string, unknown>;

export function obj(value: unknown): Json | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Json) : null;
}

export function arr(value: unknown): Json[] {
  return Array.isArray(value) ? value.map((v) => obj(v) ?? {}) : [];
}

export function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export interface Projection {
  outcome: string;
  lineageVerdict: string;
  objective: Json | null;
  statements: Json[];
  designs: Json[];
  tasks: Json[];
  attempts: Json[];
  failures: Json[];
  uncertainties: Json[];
  coverage: Json | null;
  sources: Json;
}

export class ProjectionUnreadable extends Error {
  constructor(readonly why: string) {
    super(`not an ${OUTCOME_FORMAT}: ${why}`);
    this.name = "ProjectionUnreadable";
  }
}

/** The projection of ANSWER, or ProjectionUnreadable when it is not an outcome-projection/v1. */
export function readProjection(answer: unknown): Projection {
  const a = obj(answer);
  if (a === null) throw new ProjectionUnreadable("the answer is not an object");
  if (a.format !== OUTCOME_FORMAT) throw new ProjectionUnreadable(`its format is ${JSON.stringify(a.format)}`);
  for (const key of ["tasks", "attempts", "failures", "lineageUncertainties", "statements", "designs"]) {
    if (!Array.isArray(a[key])) throw new ProjectionUnreadable(`${key} is not a list`);
  }
  if (typeof a.outcome !== "string" || typeof a.lineageVerdict !== "string") {
    throw new ProjectionUnreadable("the outcome or the lineage verdict is missing");
  }
  return {
    outcome: a.outcome,
    lineageVerdict: a.lineageVerdict,
    objective: obj(a.objective),
    statements: arr(a.statements),
    designs: arr(a.designs),
    tasks: arr(a.tasks),
    attempts: arr(a.attempts),
    failures: arr(a.failures),
    uncertainties: arr(a.lineageUncertainties),
    coverage: obj(a.coverage),
    sources: obj(a.sources) ?? {},
  };
}

/** Whether the projection says an attempt is bound to, or answered by, the fixture authority (R11). */
export function fixtureBound(attempt: Json): boolean {
  const authority = obj(attempt.authority);
  return authority !== null && (authority.bound === "fixture" || authority.shown === "fixture");
}

/** Whether anything of the projection is the fixture's (an attempt, or a FIXTURE_AUTHORITY uncertainty). */
export function usesFixture(p: Projection): boolean {
  return p.attempts.some(fixtureBound) || p.uncertainties.some((u) => u.code === FIXTURE_AUTHORITY_CODE);
}

export interface Missing {
  kind: string;
  code: string | null;
  text: string;
  detail: string | null;
}

/**
 * Every missing source and blocker the projection holds, none dropped: each unresolved reference, an
 * integration store that was not read, a task whose latest status is failed or unknown, an attempt whose
 * authority is not shown, an open restore epoch, a missing objective, coverage or design, and a lineage
 * verdict the card does not know.
 */
export function missingSources(p: Projection): Missing[] {
  const out: Missing[] = [];
  for (const f of p.failures) {
    out.push({
      kind: "unresolved-reference",
      code: str(f.code),
      text: `The ${str(f.role) ?? "?"} reference ${str(f.reference) ?? "?"} does not resolve (${str(f.outcome) ?? "?"}).`,
      detail: str(f.detail),
    });
  }
  const store = p.sources.integrationStore;
  if (store !== "read") {
    out.push({
      kind: "store-unavailable",
      code: "STORE_UNAVAILABLE",
      text: "The integration store was not read, so no attempt's state is known.",
      detail: str(store) ?? JSON.stringify(store ?? null),
    });
  }
  if (p.sources.restoreEpochOpen === true) {
    out.push({
      kind: "restore-epoch",
      code: null,
      text: "A restore epoch of the integration store is open: an absence of records proves nothing until it closes.",
      detail: null,
    });
  }
  for (const t of p.tasks) {
    const execution = obj(t.execution) ?? {};
    const status = shownStatus(execution.status);
    if (status === "failed" || status === "unknown") {
      out.push({
        kind: "task-execution",
        code: str(execution.code),
        text: `${str(t.reference) ?? "A task"}: its latest attempt is ${STATUS_LABEL[status].toLowerCase()}.`,
        detail: str(execution.detail) ?? codeMeaning(execution.code),
      });
    }
  }
  for (const a of p.attempts) {
    const authority = obj(a.authority) ?? {};
    if (authority.shown !== "live" && authority.shown !== "fixture") {
      out.push({
        kind: "authority",
        code: str(authority.code),
        text: `The authority of attempt ${str(a.operationKey) ?? "?"} is unknown.`,
        detail: str(authority.detail) ?? str(authority.reason),
      });
    }
  }
  if (p.objective === null) {
    out.push({ kind: "objective-missing", code: null, text: "The projection holds no objective node.", detail: null });
  }
  if (p.designs.length === 0) {
    out.push({ kind: "design-missing", code: null, text: "No design is linked to the outcome.", detail: null });
  }
  if (p.coverage === null) {
    out.push({ kind: "coverage-missing", code: null, text: "The projection carries no coverage note.", detail: null });
  }
  if (!(LINEAGE_VERDICTS as readonly string[]).includes(p.lineageVerdict)) {
    out.push({ kind: "verdict-unknown", code: null, text: `The lineage verdict ${p.lineageVerdict} is not one the card knows.`, detail: null });
  }
  return out;
}

/** An evidence entry's basis, as the projection states it: verified (observed by the host) or not. */
export function observed(entry: Json | null): boolean {
  return entry !== null && entry.basis === "verified";
}
