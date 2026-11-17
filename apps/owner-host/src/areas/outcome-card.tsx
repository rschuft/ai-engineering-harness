import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { ToolCallMessagePartComponent, ToolCallMessagePartProps } from "@assistant-ui/react";
import { REFUSAL_TEXT, SessionRefusal, type IntegrationClient, type RefusalCode } from "../identity/owner-session";
import { useShellLayout } from "../shell/layout";
import {
  LINEAGE_VERDICTS,
  ProjectionUnreadable,
  STATUS_LABEL,
  STATUS_MEANING,
  VERDICT_MEANING,
  arr,
  codeMeaning,
  fixtureBound,
  missingSources,
  obj,
  observed,
  readProjection,
  shownStatus,
  str,
  usesFixture,
  type Json,
  type Projection,
} from "./outcome-projection";

// The outcome card (plan leaf U-04.2; the I1 integration design, slice 14, R4, R6, R11 and R14).
//
// A tool UI over the Integration process's read-only outcome projection, `GET /outcomes/{outcome_id}`
// (U-04.1). It appears in the chat once the Owner's acceptance of an objective is recorded (its answer
// carries the outcome id), and is read again whenever it is shown: on a reload, a reconnect or a
// replay of the thread it asks the projection afresh, so it never shows a copy kept in the thread.
// It is read-only: its one request is that GET, with the session header, through the shell's
// Integration client; it writes nothing and never sets a Work item's status. Every value is rendered
// as plain text (R14): no markup, link or HTML is made from the projection's strings.

// Its tool name is chat-adapter.ts's OUTCOME_TOOL; its args name the outcome, `{outcome: <uuid>}`.
const OUTCOME_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type OutcomeArgs = { outcome: string };
export type OutcomeToolResult = { outcome: string };

/** The Integration client of the signed-in chat (StoredChat provides it); null when there is none. */
export const OutcomeClientContext = createContext<IntegrationClient | null>(null);

type Read =
  | { state: "loading" }
  | { state: "shown"; projection: Projection; readAt: string }
  | { state: "refused"; code: RefusalCode; text: string; detail: string | null }
  | { state: "unreadable"; why: string };

/** The projection's path for OUTCOME. */
export function outcomePath(outcome: string): string {
  return `/outcomes/${encodeURIComponent(outcome)}`;
}

function useOutcomeProjection(client: IntegrationClient | null, outcome: string | null) {
  const [read, setRead] = useState<Read>({ state: "loading" });
  const serial = useRef(0);
  const load = useCallback(async () => {
    if (client === null || outcome === null) return;
    const mine = ++serial.current;
    setRead({ state: "loading" });
    let next: Read;
    try {
      const projection = readProjection(await client.request("GET", outcomePath(outcome)));
      next = { state: "shown", projection, readAt: new Date().toISOString() };
    } catch (error) {
      if (error instanceof ProjectionUnreadable) {
        next = { state: "unreadable", why: error.why };
      } else {
        const refusal = error instanceof SessionRefusal ? error : new SessionRefusal("UNREACHABLE");
        next = { state: "refused", code: refusal.code, text: REFUSAL_TEXT[refusal.code], detail: refusal.detail };
      }
    }
    if (mine === serial.current) setRead(next);
  }, [client, outcome]);
  useEffect(() => {
    void load();
    return () => {
      serial.current++;   // an answer that arrives after the card is gone changes nothing
    };
  }, [load]);
  return { read, load };
}

/** A reference or digest as such: its text, and a button that copies it (nothing else is done with it). */
function Reference({ value, label }: { value: unknown; label: string }) {
  const [copied, setCopied] = useState<"" | "copied" | "unavailable">("");
  if (value === null || value === undefined || value === "") {
    return <span className="owner-outcome__absent">not recorded</span>;
  }
  const text = typeof value === "string" ? value : String(value);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied("copied");
    } catch {
      setCopied("unavailable");
    }
  }
  return (
    <span className="owner-outcome__reference">
      <code data-testid="outcome-reference-value">{text}</code>{" "}
      <button type="button" className="owner-outcome__copy" aria-label={`Copy ${label}`} onClick={() => void copy()}>
        {copied === "copied" ? "Copied" : copied === "unavailable" ? "Copy unavailable" : "Copy"}
      </button>
    </span>
  );
}

function Plain({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="owner-outcome__absent">not recorded</span>;
  return <>{typeof value === "string" ? value : JSON.stringify(value)}</>;
}

/** Every field of a projection entry, each as given: references copyable, digests with their size. */
function Fields({ entry, label }: { entry: Json; label: string }) {
  const keys = Object.keys(entry).filter((k) => k !== "basis" && k !== "statement");
  return (
    <dl className="owner-outcome__fields">
      {keys.map((key) => {
        const value = entry[key];
        const nested = obj(value);
        return (
          <div key={key} className="owner-outcome__field">
            <dt>{key}</dt>
            <dd>
              {nested !== null ? (
                <Fields entry={nested} label={`${label} ${key}`} />
              ) : typeof value === "boolean" || typeof value === "number" ? (
                String(value)
              ) : (
                <Reference value={value} label={`${label} ${key}`} />
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export function StatusBadge({ status, code }: { status: unknown; code: unknown }) {
  const shown = shownStatus(status);
  const given = typeof status === "string" ? status : JSON.stringify(status ?? null);
  return (
    <span className={`owner-outcome__status owner-outcome__status--${shown}`} data-testid="outcome-status" data-status={shown}>
      <strong data-testid="outcome-status-label">{STATUS_LABEL[shown]}</strong>
      {shown !== status ? <> (the projection gave the status {given}, which the card does not know)</> : null}
      {": "}
      <span className="owner-outcome__status-meaning">{STATUS_MEANING[shown]}</span>{" "}
      <code data-testid="outcome-code">{str(code) ?? "no code"}</code>{" "}
      <span className="owner-outcome__code-meaning" data-testid="outcome-code-meaning">
        {codeMeaning(code)}
      </span>
    </span>
  );
}

function FixtureLabel({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <strong className="owner-outcome__fixture" data-testid={testId}>
      FIXTURE {children}
    </strong>
  );
}

function Authority({ attempt }: { attempt: Json }) {
  const authority = obj(attempt.authority) ?? {};
  const shown = authority.shown;
  if (shown === "fixture") {
    return (
      <p className="owner-outcome__authority" data-testid="outcome-authority" data-authority="fixture">
        <FixtureLabel testId="outcome-attempt-fixture-label">
          (answered by the fixture authority, bound by the pinned route allowlist): not a live run.
        </FixtureLabel>
      </p>
    );
  }
  if (shown === "live") {
    return (
      <p className="owner-outcome__authority" data-testid="outcome-authority" data-authority="live">
        Authority: live, bound by the pinned route allowlist.
      </p>
    );
  }
  return (
    <p className="owner-outcome__authority" data-testid="outcome-authority" data-authority="unknown">
      Authority unknown: shown as neither live nor fixture (<code>{str(authority.code) ?? "no code"}</code>
      {authority.reason !== undefined ? (
        <>
          , <code>{str(authority.reason) ?? JSON.stringify(authority.reason)}</code>
        </>
      ) : null}
      ). Bound to: <Plain value={authority.bound} />.{" "}
      {authority.detail !== undefined ? <Plain value={authority.detail} /> : null}
      {authority.bound === "fixture" ? (
        <>
          {" "}
          <FixtureLabel testId="outcome-attempt-fixture-label">(its binding is the fixture authority).</FixtureLabel>
        </>
      ) : null}
    </p>
  );
}

function Evidence({ attempt }: { attempt: Json }) {
  const evidence = obj(attempt.evidence);
  const result = obj(attempt.result) ?? {};
  const entries: [string, Json | null][] = [
    ["commit", obj(evidence?.commit)],
    ["diff", obj(evidence?.diff)],
    ["pull request", obj(evidence?.pullRequest)],
    ["test output", obj(evidence?.testOutput)],
    ["host's intake", obj(result.verified)],
    ["attempt's report", obj(result.reported)],
    ["attempt's tests", obj(result.tests)],
  ];
  const seen = entries.filter(([, entry]) => entry !== null) as [string, Json][];
  const verified = seen.filter(([, entry]) => observed(entry));
  const asserted = seen.filter(([, entry]) => !observed(entry));
  const records: [string, Json | null][] = [
    ["result receipt", obj(evidence?.receipt)],
    ["bundle", obj(evidence?.bundle)],
    ["lineage of the receipt", obj(evidence?.lineage)],
  ];
  return (
    <div className="owner-outcome__evidence">
      <section className="owner-outcome__observed" data-testid="outcome-observed" aria-label="Observed evidence">
        <h5>Observed evidence: what the host verified, with its source records</h5>
        {verified.length === 0 && records.every(([, r]) => r === null) ? (
          <p className="owner-outcome__absent">No evidence observed by the host is recorded.</p>
        ) : (
          <ul>
            {verified.map(([label, entry]) => (
              <li key={label} data-testid="outcome-evidence" data-basis="verified">
                <span className="owner-outcome__evidence-label">{label} (verified)</span>
                {entry.statement !== undefined ? (
                  <span className="owner-outcome__statement">
                    : <Plain value={entry.statement} />
                  </span>
                ) : null}
                <Fields entry={entry} label={label} />
              </li>
            ))}
            {records.map(([label, entry]) =>
              entry === null ? null : (
                <li key={label} data-testid="outcome-evidence" data-basis="record">
                  <span className="owner-outcome__evidence-label">{label} (the dispatcher&apos;s record)</span>
                  <Fields entry={entry} label={label} />
                </li>
              ),
            )}
          </ul>
        )}
      </section>
      <section className="owner-outcome__asserted" data-testid="outcome-asserted" aria-label="Asserted by the attempt">
        <h5>Asserted by the attempt: reported, not verified, and never a status</h5>
        {asserted.length === 0 ? (
          <p className="owner-outcome__absent">Nothing the attempt reported is recorded.</p>
        ) : (
          <ul>
            {asserted.map(([label, entry]) => (
              <li key={label} data-testid="outcome-evidence" data-basis={str(entry.basis) ?? "unstated"}>
                <span className="owner-outcome__evidence-label">
                  {label} ({str(entry.basis) ?? "basis not stated"})
                </span>
                {entry.statement !== undefined ? (
                  <span className="owner-outcome__statement">
                    : <Plain value={entry.statement} />
                  </span>
                ) : null}
                <Fields entry={entry} label={label} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function AttemptItem({ attempt }: { attempt: Json }) {
  const shownBy = obj(attempt.shownBy) ?? {};
  const disclosed = arr(attempt.disclosed);
  const status = shownStatus(attempt.executionStatus);
  return (
    <li
      className="owner-outcome__attempt"
      data-testid="outcome-attempt"
      data-status={status}
      data-code={str(attempt.executionCode) ?? ""}
      data-authority={str(obj(attempt.authority)?.shown) ?? "unknown"}
      data-fixture={fixtureBound(attempt) ? "true" : "false"}
    >
      <p className="owner-outcome__attempt-title">
        Work <code>{str(attempt.workId) ?? "?"}</code>, stage <code data-testid="outcome-stage-name">{str(attempt.stage) ?? "?"}</code>,
        attempt <Plain value={attempt.ordinal} />
      </p>
      <StatusBadge status={attempt.executionStatus} code={attempt.executionCode} />
      <p className="owner-outcome__detail">
        The projection&apos;s detail: <Plain value={attempt.detail} />
      </p>
      {attempt.restoredRow !== undefined ? (
        <p className="owner-outcome__restored" data-testid="outcome-restored">
          Why unknown: the attempt&apos;s records crossed a restore of the integration store (epochs{" "}
          {arr(attempt.restoreEpochs).length > 0 ? JSON.stringify(attempt.restoreEpochs) : <Plain value={attempt.restoreEpochs} />}
          ); without it the row would be <code>{str(attempt.restoredRow) ?? "?"}</code>.
        </p>
      ) : null}
      {attempt.cause !== undefined ? (
        <p className="owner-outcome__cause">
          Cause: <code>{str(attempt.cause) ?? JSON.stringify(attempt.cause)}</code>
        </p>
      ) : null}
      {attempt.stops !== undefined ? (
        <p className="owner-outcome__stops">
          Stops: <Plain value={attempt.stops} />
        </p>
      ) : null}
      {attempt.end !== undefined ? (
        <p className="owner-outcome__end">
          End: <Plain value={attempt.end} />
        </p>
      ) : null}
      {attempt.problems !== undefined ? (
        <p className="owner-outcome__problems">
          Launch problems: <Plain value={attempt.problems} />
        </p>
      ) : null}
      {disclosed.length > 0 ? (
        <div className="owner-outcome__disclosed" data-testid="outcome-disclosed">
          Recorded beside the published result, disclosed here and not hidden:
          <ul>
            {disclosed.map((d, i) => (
              <li key={i} data-testid="outcome-disclosed-record">
                <Reference value={d.record} label="disclosed record" /> (<Plain value={d.state} />)
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Authority attempt={attempt} />
      <p className="owner-outcome__shown-by">
        Shown by the record <Reference value={shownBy.record} label="the record that shows the status" /> (state{" "}
        <Plain value={shownBy.state} />, event <Plain value={shownBy.eventId} />
        ).
      </p>
      <Evidence attempt={attempt} />
      <div className="owner-outcome__actions" data-testid="outcome-source-actions">
        Source actions: the attempt <Reference value={attempt.operationKey} label="attempt" />, its execution{" "}
        <Reference value={attempt.executionRef} label="execution reference" />{" "}
        <button
          type="button"
          className="owner-outcome__session-detail"
          data-testid="outcome-session-detail"
          disabled
          title="The session view belongs to plan leaf U-01.2, not built yet."
        >
          Session detail: not available yet
        </button>
      </div>
    </li>
  );
}

function ProjectionView({ projection: p }: { projection: Projection }) {
  const objective = p.objective;
  const facts = obj(objective?.facts) ?? {};
  const resolution = obj(objective?.resolution) ?? {};
  const missing = missingSources(p);
  const verdict = (LINEAGE_VERDICTS as readonly string[]).includes(p.lineageVerdict)
    ? VERDICT_MEANING[p.lineageVerdict as (typeof LINEAGE_VERDICTS)[number]]
    : "A lineage verdict the card does not know.";
  return (
    <div className="owner-outcome__body" data-testid="outcome-body">
      <p className="owner-outcome__verdict" data-testid="outcome-lineage-verdict" data-verdict={p.lineageVerdict}>
        Lineage <strong>{p.lineageVerdict}</strong>: {verdict} The lineage is about the references; each
        attempt&apos;s status is the dispatcher&apos;s records.
      </p>
      <div className="owner-outcome__sections">
        <section className="owner-outcome__section" data-testid="outcome-why" aria-label="Why">
          <h4>Why: the objective</h4>
          {objective === null ? (
            <p className="owner-outcome__absent">The projection holds no objective.</p>
          ) : (
            <>
              <p className="owner-outcome__objective" data-testid="outcome-objective">
                <Plain value={facts.statement} />
              </p>
              <p>
                <Plain value={facts.item} /> of <Plain value={facts.change} />: <Reference value={objective.reference} label="objective" />{" "}
                (<Plain value={resolution.outcome} />
                {resolution.code ? (
                  <>
                    , <code>{str(resolution.code)}</code>
                  </>
                ) : null}
                )
              </p>
            </>
          )}
          <p>Owner statements:</p>
          {p.statements.length === 0 ? (
            <p className="owner-outcome__absent">None reached.</p>
          ) : (
            <ul>
              {p.statements.map((s, i) => (
                <li key={i} data-testid="outcome-statement">
                  <Reference value={s.reference} label="statement" /> (<Plain value={obj(s.resolution)?.outcome} />)
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="owner-outcome__section" data-testid="outcome-approach" aria-label="Accepted approach">
          <h4>Accepted approach: the design</h4>
          {p.designs.length === 0 ? (
            <p className="owner-outcome__absent">No design is linked.</p>
          ) : (
            <ul>
              {p.designs.map((d, i) => (
                <li key={i} data-testid="outcome-design">
                  <Reference value={d.reference} label="design" /> (<Plain value={obj(d.resolution)?.outcome} />,{" "}
                  <Plain value={d.freshness} />)
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="owner-outcome__section" data-testid="outcome-work" aria-label="Linked Work">
          <h4>Linked Work</h4>
          <p className="owner-outcome__note">
            A task&apos;s own status in Backlog.md is not part of the projection, and this card never sets or infers it: shown
            here is whether the task resolves and its latest attempt&apos;s status.
          </p>
          {p.tasks.length === 0 ? (
            <p className="owner-outcome__absent">No task is reached.</p>
          ) : (
            <ul>
              {p.tasks.map((t, i) => {
                const execution = obj(t.execution) ?? {};
                return (
                  <li key={i} data-testid="outcome-task" data-reference={str(t.reference) ?? ""}>
                    <Reference value={t.reference} label="task" />: <Plain value={t.resolution} />
                    {t.code ? (
                      <>
                        {" "}
                        (<code>{str(t.code)}</code>)
                      </>
                    ) : null}
                    , reached through <Plain value={t.reachedThrough} />. Latest attempt:{" "}
                    <StatusBadge status={execution.status} code={execution.code} />
                    {execution.detail !== undefined ? (
                      <>
                        {" "}
                        <Plain value={execution.detail} />
                      </>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        <section className="owner-outcome__section owner-outcome__section--wide" data-testid="outcome-stage" aria-label="Current stage">
          <h4>Current stage: the attempts</h4>
          {p.attempts.length === 0 ? (
            <p className="owner-outcome__absent">No attempt is recorded for this outcome.</p>
          ) : (
            <ul className="owner-outcome__attempts">
              {p.attempts.map((a, i) => (
                <AttemptItem key={i} attempt={a} />
              ))}
            </ul>
          )}
        </section>
        <section className="owner-outcome__section" data-testid="outcome-missing" aria-label="Blockers and missing sources">
          <h4>Blockers and missing sources</h4>
          {missing.length === 0 ? (
            <p>No blocker or missing source is recorded in this projection.</p>
          ) : (
            <ul>
              {missing.map((m, i) => (
                <li key={i} data-testid="outcome-missing-item" data-kind={m.kind}>
                  {m.text}
                  {m.code ? (
                    <>
                      {" "}
                      <code>{m.code}</code>
                    </>
                  ) : null}
                  {m.detail ? <> {m.detail}</> : null}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="owner-outcome__section" data-testid="outcome-uncertainties" aria-label="Lineage uncertainties">
          <h4>Lineage uncertainties</h4>
          {p.uncertainties.length === 0 ? (
            <p>None recorded.</p>
          ) : (
            <ul>
              {p.uncertainties.map((u, i) => (
                <li key={i} data-testid="outcome-uncertainty" data-code={str(u.code) ?? ""}>
                  <Reference value={u.reference} label="uncertain reference" />: <Plain value={u.reason} /> (
                  <code>{str(u.code) ?? "no code"}</code>) <Plain value={u.detail} />
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="owner-outcome__section" data-testid="outcome-coverage" aria-label="Coverage">
          <h4>Coverage</h4>
          {p.coverage === null ? (
            <p className="owner-outcome__absent">The projection carries no coverage note.</p>
          ) : (
            <p>
              {p.coverage.archivedTasksEnumerable === false ? "Archived tasks cannot be enumerated. " : null}
              <code>{str(p.coverage.code) ?? "no code"}</code> (<Plain value={p.coverage.basis} />):{" "}
              <Plain value={p.coverage.detail} />
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

/** The card for OUTCOME, read from the projection through CLIENT. */
export function OutcomeProjectionCard({
  client,
  outcome,
  toolCallId,
}: {
  client: IntegrationClient | null;
  outcome: string | null;
  toolCallId?: string;
}) {
  const layout = useShellLayout();
  const { read, load } = useOutcomeProjection(client, outcome);
  const state = client === null ? "unavailable" : outcome === null ? "unreadable" : read.state;
  const fixture = read.state === "shown" && usesFixture(read.projection);
  return (
    <div
      className="owner-outcome"
      data-testid="outcome-card"
      data-state={state}
      data-layout={layout}
      data-fixture={fixture ? "true" : "false"}
      data-tool-call-id={toolCallId}
      role="group"
      aria-label="Outcome"
    >
      <div className="owner-outcome__header">
        <p className="owner-outcome__title">
          Outcome <code data-testid="outcome-id">{outcome ?? "not named"}</code>
        </p>
        {client !== null && outcome !== null ? (
          <button type="button" className="owner-outcome__refresh" onClick={() => void load()} disabled={read.state === "loading"}>
            Read again
          </button>
        ) : null}
      </div>
      {fixture ? (
        <p className="owner-outcome__fixture-banner">
          <FixtureLabel testId="outcome-fixture-label">
            : this outcome&apos;s attempts were answered by the fixture authority, not by a live run.
          </FixtureLabel>
        </p>
      ) : null}
      <p className="owner-outcome__note">
        Read-only: shown from the Integration process&apos;s projection of the dispatcher&apos;s records. This card changes
        nothing, and what an agent claimed is listed apart from what the host observed and sets no status.
      </p>
      {client === null ? (
        <p data-testid="outcome-unavailable">Sign in to read this outcome&apos;s projection.</p>
      ) : outcome === null ? (
        <p data-testid="outcome-unreadable">The card names no outcome id, so nothing is read.</p>
      ) : read.state === "loading" ? (
        <p data-testid="outcome-loading">Reading the outcome projection…</p>
      ) : read.state === "refused" ? (
        <div className="owner-outcome__refused" data-testid="outcome-refused">
          <p>
            The projection was not read: <code data-testid="outcome-refusal-code">{read.code}</code>
          </p>
          <p>{read.text}</p>
          {read.detail ? <p className="owner-outcome__refusal-detail">{read.detail}</p> : null}
        </div>
      ) : read.state === "unreadable" ? (
        <p data-testid="outcome-unreadable">The Integration process answered something that is not an outcome projection: {read.why}</p>
      ) : (
        <>
          <ProjectionView projection={read.projection} />
          <p className="owner-outcome__read-at" data-testid="outcome-read-at">
            Read at <time dateTime={read.readAt}>{read.readAt}</time>.
          </p>
        </>
      )}
    </div>
  );
}

function outcomeOf(args: unknown): string | null {
  const outcome = obj(args)?.outcome;
  return typeof outcome === "string" && OUTCOME_ID.test(outcome) ? outcome : null;
}

/** The tool UI: the card for its args' outcome, through the chat's Integration client. */
export const OutcomeCard: ToolCallMessagePartComponent<OutcomeArgs, OutcomeToolResult> = (
  props: ToolCallMessagePartProps<OutcomeArgs, OutcomeToolResult>,
) => {
  const client = useContext(OutcomeClientContext);
  return <OutcomeProjectionCard client={client} outcome={outcomeOf(props.args)} toolCallId={props.toolCallId} />;
};
