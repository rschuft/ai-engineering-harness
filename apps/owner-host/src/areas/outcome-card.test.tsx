import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { OutcomeCard, OutcomeClientContext, OutcomeProjectionCard, outcomeId, outcomePath } from "./outcome-card";
import {
  CODE_MEANING,
  EXECUTION_STATUSES,
  OUTCOME_FORMAT,
  STATUS_LABEL,
  UNPROVEN_SUFFIX,
  CODE_STATUS,
  STATUS_MEANING,
  codeMeaning,
  shownStatus,
  statusCodeDisagree,
} from "./outcome-projection";
import {
  INTEGRATION_ORIGIN,
  PROJECTION_CODES,
  REFUSAL_TEXT,
  SESSION_HEADER,
  createIntegrationClient,
  type FetchLike,
} from "../identity/owner-session";
import { WIDE_MIN_WIDTH } from "../shell/layout";
import { setViewportWidth } from "../test/viewport";
import shellCss from "../shell/shell.css?raw";
import cardSource from "./outcome-card.tsx?raw";
import projectionSource from "./outcome-projection.ts?raw";
import sessionLinksSource from "../engineering/SessionLinks.tsx?raw";
import sessionDetailSource from "../engineering/session-detail.ts?raw";
import engineeringSessionSource from "../engineering/EngineeringSession.tsx?raw";
import { OUTCOME_ID, SCENARIOS, answer, fixture, schema as projectionSchema, type Answer } from "../test/outcome-fixtures";

// The outcome card (plan leaf U-04.2) over real answers of the Integration process's outcome
// projection, GET /outcomes/{outcome_id} (U-04.1). Every answer here is a committed fixture made by
// the projection itself (integrations/ownerhost/tests/outcome_card_fixtures.py: the dispatcher's own
// writers on a throwaway store, the route behind its guards), pinned to projection.py by
// test_outcome_card_fixtures.py; the card asks only that route, through a fake fetch. The setup's
// network guard refuses any real request.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

type Seen = { method: string; path: string; header: string | undefined; body: unknown };

function renderCard(served: () => Answer | Promise<Answer>, outcome: string | null = OUTCOME_ID) {
  const seen: Seen[] = [];
  const credential = throwawayCredential();
  const fetchImpl: FetchLike = async (url, init) => {
    seen.push({
      method: init.method ?? "GET",
      path: url.slice(INTEGRATION_ORIGIN.length),
      header: (init.headers as Record<string, string>)[SESSION_HEADER],
      body: init.body,
    });
    const a = await served();
    return new Response(JSON.stringify(a.body), { status: a.status });
  };
  const client = createIntegrationClient(credential, fetchImpl);
  render(<OutcomeProjectionCard client={client} outcome={outcome} />);
  return { seen, credential };
}

async function settled(): Promise<HTMLElement> {
  const card = screen.getByTestId("outcome-card");
  await waitFor(() => expect(card.getAttribute("data-state")).not.toBe("loading"));
  return card;
}

async function show(name: string, index = 0): Promise<HTMLElement> {
  renderCard(() => answer(name, index));
  return settled();
}

function attempts(card: HTMLElement): HTMLElement[] {
  return within(card).queryAllByTestId("outcome-attempt");
}

function tasks(card: HTMLElement): HTMLElement[] {
  return within(card).queryAllByTestId("outcome-task");
}

function missingKinds(card: HTMLElement): string[] {
  return within(card)
    .queryAllByTestId("outcome-missing-item")
    .map((m) => m.getAttribute("data-kind") ?? "");
}

describe("the outcome card's fixtures", () => {
  it("are the projection's own answers, each naming its source, and the card knows every code they can hold", () => {
    const schema = projectionSchema();
    expect(schema.format).toBe(OUTCOME_FORMAT);
    expect(schema.statuses).toEqual([...EXECUTION_STATUSES]);
    expect(schema.unprovenSuffix).toBe(UNPROVEN_SUFFIX);
    for (const code of schema.codes) expect(CODE_MEANING[code], code).toBeTruthy();
    for (const code of Object.keys(CODE_MEANING)) expect(schema.codes, code).toContain(code);
    for (const code of Object.keys(schema.refusals)) {
      expect(PROJECTION_CODES as readonly string[], code).toContain(code);
      expect(REFUSAL_TEXT[code as (typeof PROJECTION_CODES)[number]]).toBeTruthy();
    }
    expect(SCENARIOS.length).toBeGreaterThanOrEqual(15);
    for (const name of SCENARIOS) {
      const f = fixture(name);
      expect(f.generatedBy).toBe("integrations/ownerhost/tests/outcome_card_fixtures.py");
      expect(f.source.length).toBeGreaterThan(10);
      for (const a of f.answers) {
        if (a.status === 200) expect(a.body.format).toBe(OUTCOME_FORMAT);
        else expect(Object.keys(a.body).sort()).toEqual(["code", "detail", "remedy"]);
      }
    }
  });

  it("render, every one of them, with each attempt, task, failure and uncertainty the answer holds", async () => {
    for (const name of SCENARIOS) {
      for (const [index, a] of fixture(name).answers.entries()) {
        const { seen } = renderCard(() => answer(name, index));
        const card = await settled();
        if (a.status !== 200) {
          expect(card.getAttribute("data-state"), name).toBe("refused");
        } else {
          expect(card.getAttribute("data-state"), name).toBe("shown");
          expect(attempts(card).length, name).toBe(a.body.attempts.length);
          expect(tasks(card).length, name).toBe(a.body.tasks.length);
          expect(within(card).queryAllByTestId("outcome-uncertainty").length, name).toBe(a.body.lineageUncertainties.length);
          expect(missingKinds(card).filter((k) => k === "unresolved-reference").length, name).toBe(a.body.failures.length);
        }
        expect(seen.map((s) => `${s.method} ${s.path}`), name).toEqual([`GET /outcomes/${OUTCOME_ID}`]);
        cleanup();
      }
    }
  });
});

describe("the outcome card's statuses (U-04's proof: pending, running, failed, unknown)", () => {
  const cases: [string, number, string, string][] = [
    ["pending-created", 0, "pending", "CREATED"],
    ["running-turn-sent", 0, "running", "TURN_SENT"],
    ["reconnect", 0, "running", "RESULT_VERIFIED"],
    ["failed-refused-create", 0, "failed", "ATTEMPT_FAILED"],
    ["unknown-create-outcome", 0, "unknown", "CREATE_OUTCOME_UNKNOWN"],
    ["unknown-label-missing", 0, "unknown", "ATTEMPT_LABEL_MISSING"],
    ["unproven-after-restore", 0, "unknown", "CREATED_UNPROVEN"],
    ["reconnect", 1, "succeeded", "RESULT_PUBLISHED"],
    ["published-live", 0, "succeeded", "RESULT_PUBLISHED"],
  ];
  for (const [name, index, status, code] of cases) {
    it(`shows ${name}${index ? ` (${index})` : ""} as ${status}, with its code and the code's meaning`, async () => {
      const card = await show(name, index);
      const [attempt] = attempts(card);
      expect(attempt.getAttribute("data-status")).toBe(status);
      expect(attempt.getAttribute("data-code")).toBe(code);
      const badge = within(attempt).getAllByTestId("outcome-status")[0];
      expect(within(badge).getByTestId("outcome-status-label").textContent).toBe(STATUS_LABEL[status as never]);
      expect(within(badge).getByTestId("outcome-code").textContent).toBe(code);
      expect(within(badge).getByTestId("outcome-code-meaning").textContent).toBe(codeMeaning(code));
      // the task's line shows its latest attempt with the same status, never another
      const task = tasks(card).find((t) => t.getAttribute("data-reference") === "backlog:TASK-2")!;
      expect(within(task).getByTestId("outcome-status").getAttribute("data-status")).toBe(status);
    });
  }

  it("words a published result as published and verified at publication, never as Work done or complete", async () => {
    const card = await show("reconnect", 1);
    expect(within(attempts(card)[0]).getAllByTestId("outcome-status-label")[0].textContent).toBe(
      "Result published, verified at publication",
    );
    const text = (card.textContent ?? "").replace(within(card).getByTestId("outcome-lineage-verdict").textContent ?? "", "");
    expect(/\bdone\b/i.test(text)).toBe(false);
    expect(/\bcompleted?\b/i.test(text)).toBe(false);
    expect(within(card).getByTestId("outcome-work").textContent).toContain("never sets or infers it");
  });

  it("shows unknown as unknown, never pending or failed, and an unknown status value as unknown", async () => {
    const card = await show("unknown-create-outcome");
    const [attempt] = attempts(card);
    expect(within(attempt).getAllByTestId("outcome-status-label")[0].textContent).toBe("Unknown");
    expect(attempt.textContent).not.toContain("Pending");
    expect(attempt.textContent).not.toContain("Failed");
    for (const value of ["done", "complete", "succeeded ", "", null, 1]) expect(shownStatus(value)).toBe("unknown");
    const odd = answer("reconnect", 1);
    odd.body.attempts[0].executionStatus = "done";
    odd.body.tasks[1].execution.status = "complete";
    cleanup();
    renderCard(() => odd);
    const shown = await settled();
    for (const badge of within(shown).getAllByTestId("outcome-status")) {
      if (badge.closest("[data-reference='backlog:TASK-1']")) continue;
      expect(badge.getAttribute("data-status")).toBe("unknown");
      expect(badge.textContent).toContain("which the card does not know");
    }
    expect(shown.textContent).not.toContain("Result published");
  });

  it("says why an _UNPROVEN status is unknown: a restore, with the row it would have been and its epochs", async () => {
    const card = await show("unproven-after-restore");
    const [attempt] = attempts(card);
    const restored = within(attempt).getByTestId("outcome-restored");
    expect(restored.textContent).toContain("crossed a restore");
    expect(restored.textContent).toContain("CREATED");
    expect(restored.textContent).toContain("[1]");
    expect(within(attempt).getAllByTestId("outcome-code-meaning")[0].textContent).toContain("Unproven after a restore");
    expect(missingKinds(card)).toContain("restore-epoch");
    // every task: TASK-1 has no attempt, and with a restore epoch that is unproven too
    const one = tasks(card).find((t) => t.getAttribute("data-reference") === "backlog:TASK-1")!;
    expect(within(one).getByTestId("outcome-code").textContent).toBe("NO_ATTEMPT_UNPROVEN");
    expect(within(one).getByTestId("outcome-status").getAttribute("data-status")).toBe("unknown");
  });

  it("shows a task whose attempt a restore lost as unknown NO_ATTEMPT_UNPROVEN, not as no attempt", async () => {
    const card = await show("no-attempt-unproven");
    expect(attempts(card)).toHaveLength(0);
    expect(within(card).getByTestId("outcome-stage").textContent).toContain("No attempt is recorded");
    for (const task of tasks(card)) {
      expect(within(task).getByTestId("outcome-status").getAttribute("data-status")).toBe("unknown");
      expect(within(task).getByTestId("outcome-code").textContent).toBe("NO_ATTEMPT_UNPROVEN");
    }
  });

  it("lists the records disclosed beside a published result", async () => {
    const a = answer("published-disclosed");
    const card = await show("published-disclosed");
    const disclosed = within(attempts(card)[0]).getByTestId("outcome-disclosed");
    const records = within(disclosed).getAllByTestId("outcome-disclosed-record");
    expect(records.map((r) => within(r).getByTestId("outcome-reference-value").textContent)).toEqual(
      a.body.attempts[0].disclosed.map((d: any) => d.record),
    );
    expect(attempts(card)[0].getAttribute("data-status")).toBe("succeeded");
  });
});

describe("missing sources stay visible (U-04.2)", () => {
  it("shows a failed lineage with every unresolved reference, its outcome and code", async () => {
    const a = answer("lineage-failed");
    const card = await show("lineage-failed");
    expect(within(card).getByTestId("outcome-lineage-verdict").getAttribute("data-verdict")).toBe("failed");
    const items = within(card)
      .getAllByTestId("outcome-missing-item")
      .filter((m) => m.getAttribute("data-kind") === "unresolved-reference");
    expect(items).toHaveLength(a.body.failures.length);
    for (const [i, f] of a.body.failures.entries()) {
      expect(items[i].textContent).toContain(f.reference);
      expect(items[i].textContent).toContain(f.code);
      expect(items[i].textContent).toContain(f.detail);
    }
    const task = tasks(card)[0];
    expect(task.textContent).toContain("missing");
  });

  it("shows every lineage uncertainty of an incomplete lineage, the fixture authority's included", async () => {
    const a = answer("reconnect", 1);
    const card = await show("reconnect", 1);
    expect(within(card).getByTestId("outcome-lineage-verdict").getAttribute("data-verdict")).toBe("incomplete");
    expect(within(card).getAllByTestId("outcome-uncertainty").map((u) => u.getAttribute("data-code"))).toEqual(
      a.body.lineageUncertainties.map((u: any) => u.code),
    );
    expect(within(card).getAllByTestId("outcome-uncertainty").map((u) => u.getAttribute("data-code"))).toContain("FIXTURE_AUTHORITY");
  });

  it("shows the coverage note on every projection, and says when one is missing", async () => {
    for (const name of SCENARIOS) {
      for (const [index, a] of fixture(name).answers.entries()) {
        if (a.status !== 200) continue;
        renderCard(() => answer(name, index));
        const card = await settled();
        const coverage = within(card).getByTestId("outcome-coverage");
        expect(coverage.textContent, name).toContain("ARCHIVED_TASKS_NOT_ENUMERABLE");
        expect(coverage.textContent, name).toContain(a.body.coverage.detail);
        expect(coverage.textContent, name).toContain("Archived tasks cannot be enumerated");
        cleanup();
      }
    }
    const bare = answer("pending-created");
    delete bare.body.coverage;
    renderCard(() => bare);
    const card = await settled();
    expect(within(card).getByTestId("outcome-coverage").textContent).toContain("no coverage note");
    expect(missingKinds(card)).toContain("coverage-missing");
  });

  it("shows an unreadable integration store, and its tasks as unknown, never pending", async () => {
    const card = await show("store-unavailable");
    expect(missingKinds(card)).toContain("store-unavailable");
    const item = within(card)
      .getAllByTestId("outcome-missing-item")
      .find((m) => m.getAttribute("data-kind") === "store-unavailable")!;
    expect(item.textContent).toContain("StoreError");
    for (const task of tasks(card)) {
      expect(within(task).getByTestId("outcome-status").getAttribute("data-status")).toBe("unknown");
      expect(within(task).getByTestId("outcome-code").textContent).toBe("STORE_UNAVAILABLE");
    }
    expect(missingKinds(card).filter((k) => k === "task-execution")).toHaveLength(tasks(card).length);
  });

  it("shows a refused projection with its stable code, its text and the service's detail", async () => {
    for (const [name, code] of [
      ["refused-unconfigured", "PROJECTION_PROJECT_UNCONFIGURED"],
      ["refused-outcome-invalid", "OUTCOME_INVALID"],
    ] as const) {
      const a = answer(name);
      renderCard(() => a);
      const card = await settled();
      expect(card.getAttribute("data-state")).toBe("refused");
      expect(within(card).getByTestId("outcome-refusal-code").textContent).toBe(code);
      expect(card.textContent).toContain(REFUSAL_TEXT[code]);
      expect(card.textContent).toContain(a.body.detail);
      expect(within(card).queryByTestId("outcome-body")).toBeNull();
      cleanup();
    }
  });

  it("shows an answer that is not an outcome projection as unreadable, never as an outcome", async () => {
    const odd = answer("pending-created");
    odd.body.format = "outcome-projection/v2";
    renderCard(() => odd);
    const card = await settled();
    expect(card.getAttribute("data-state")).toBe("unreadable");
    expect(within(card).queryByTestId("outcome-body")).toBeNull();
  });
});

describe("authority (R11): the fixture label", () => {
  it("labels the card and each fixture-bound attempt FIXTURE", async () => {
    for (const name of ["pending-created", "running-turn-sent", "reconnect", "published-disclosed", "unproven-after-restore"]) {
      renderCard(() => answer(name));
      const card = await settled();
      expect(card.getAttribute("data-fixture"), name).toBe("true");
      expect(within(card).getByTestId("outcome-fixture-label").textContent, name).toMatch(/^FIXTURE/);
      for (const attempt of attempts(card)) {
        expect(attempt.getAttribute("data-authority")).toBe("fixture");
        expect(within(attempt).getByTestId("outcome-attempt-fixture-label").textContent).toMatch(/^FIXTURE/);
        expect(attempt.textContent).not.toContain("Authority: live");
      }
      cleanup();
    }
  });

  it("shows a live attempt as live, with no fixture label anywhere", async () => {
    const card = await show("published-live");
    expect(card.getAttribute("data-fixture")).toBe("false");
    expect(within(card).queryByTestId("outcome-fixture-label")).toBeNull();
    expect(within(card).queryAllByTestId("outcome-attempt-fixture-label")).toHaveLength(0);
    expect(attempts(card)[0].getAttribute("data-authority")).toBe("live");
    expect(card.textContent).not.toContain("FIXTURE");
  });

  it("says when an attempt's authority is unknown, with its code, and keeps the fixture label of its binding", async () => {
    const card = await show("unknown-label-missing");
    const [attempt] = attempts(card);
    expect(attempt.getAttribute("data-authority")).toBe("unknown");
    const authority = within(attempt).getByTestId("outcome-authority");
    expect(authority.getAttribute("data-authority")).toBe("unknown");
    expect(authority.textContent).toContain("Authority unknown");
    expect(authority.textContent).toContain("ATTEMPT_LABEL_MISSING");
    expect(within(attempt).getByTestId("outcome-attempt-fixture-label")).toBeTruthy();
    expect(attempt.getAttribute("data-fixture")).toBe("true");
    expect(card.getAttribute("data-fixture")).toBe("true");
    expect(missingKinds(card)).toContain("authority");
  });

  it("says when an attempt is bound to no authority at all", async () => {
    const card = await show("authority-unbound");
    const [attempt] = attempts(card);
    const authority = within(attempt).getByTestId("outcome-authority");
    expect(authority.textContent).toContain("ATTEMPT_AUTHORITY_UNBOUND");
    expect(authority.textContent).toContain("BINDING_ALLOWLIST_MISSING");
    expect(within(attempt).queryByTestId("outcome-attempt-fixture-label")).toBeNull();
    expect(card.getAttribute("data-fixture")).toBe("false");
    expect(attempt.getAttribute("data-status")).toBe("failed");
  });
});

describe("evidence: observed apart from asserted, by reference (U-04's proof; R6)", () => {
  it("lists what the host verified apart from what the attempt reported, with their source records", async () => {
    const a = answer("reconnect", 1);
    const card = await show("reconnect", 1);
    const [attempt] = attempts(card);
    const observedList = within(attempt).getByTestId("outcome-observed");
    const asserted = within(attempt).getByTestId("outcome-asserted");
    const evidence = a.body.attempts[0].evidence;
    const values = (el: HTMLElement) => within(el).getAllByTestId("outcome-reference-value").map((v) => v.textContent);
    expect(values(observedList)).toEqual(
      expect.arrayContaining([
        evidence.commit.commit,
        evidence.commit.reference,
        evidence.diff.ownerReport.jsonSha256,
        evidence.diff.ownerReport.markdownSha256,
        evidence.receipt.sha256,
        evidence.receipt.record,
        a.body.attempts[0].result.verified.record,
      ]),
    );
    expect(values(asserted)).toEqual(
      expect.arrayContaining([
        evidence.testOutput.output.sha256,
        a.body.attempts[0].result.reported.record,
        a.body.attempts[0].result.tests.command,
      ]),
    );
    expect(within(observedList).getAllByTestId("outcome-evidence").map((e) => e.getAttribute("data-basis"))).not.toContain("reported");
    expect(within(asserted).getAllByTestId("outcome-evidence").map((e) => e.getAttribute("data-basis"))).not.toContain("verified");
    // the test output's digest is reported, never shown as observed
    expect(values(observedList)).not.toContain(evidence.testOutput.output.sha256);
  });

  it("makes each reference copyable, and the session detail a link to the shell's own route (U-01.2)", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const a = answer("reconnect", 1);
    const card = await show("reconnect", 1);
    const [attempt] = attempts(card);
    await act(async () => {
      fireEvent.click(within(attempt).getAllByRole("button", { name: "Copy commit commit" })[0]);
    });
    expect(writeText).toHaveBeenCalledWith(a.body.attempts[0].evidence.commit.commit);
    const detail = within(attempt).getByTestId("outcome-session-detail") as HTMLAnchorElement;
    const cid = a.body.attempts[0].conversationId;
    expect(detail.tagName).toBe("A");
    expect(detail.getAttribute("href")).toBe(`/engineering/outcomes/${OUTCOME_ID}/sessions/${cid}`);
    expect(detail.textContent).toBe("Open the session detail (FIXTURE)");
    // the card's only link is that one; no frame is in the shell's chat
    expect(Array.from(card.querySelectorAll("a, [href], [src]")).map((e) => e.getAttribute("href"))).toEqual([
      `/engineering/outcomes/${OUTCOME_ID}/sessions/${cid}`,
    ]);
    expect(card.querySelectorAll("iframe")).toHaveLength(0);
  });

  it("keeps the session detail disabled, with the projection's reason, when the action is refused", async () => {
    for (const name of ["published-live", "authority-unbound"]) {
      const a = answer(name);
      const card = await show(name);
      const [attempt] = attempts(card);
      const detail = within(attempt).getByTestId("outcome-session-detail") as HTMLButtonElement;
      expect(detail.tagName, name).toBe("BUTTON");
      expect(detail.disabled, name).toBe(true);
      expect(detail.textContent, name).toBe("Session detail: not available");
      expect(within(attempt).getByTestId("outcome-session-detail-code").textContent, name).toBe("SESSION_ACCESS_UNAVAILABLE");
      expect(within(attempt).getByTestId("outcome-session-detail-reason").textContent, name).toBe(a.body.attempts[0].sessionDetail.reason);
      expect(card.querySelectorAll("a, [href], [src], iframe"), name).toHaveLength(0);
      cleanup();
    }
  });

  it("makes no link from a conversation id that is not a lower-case UUID, whatever the projection says", async () => {
    const hostile = ["../threads", "//203.0.113.9/x", "javascript:alert(1)", "055B27F3-903E-5EB9-8758-197C1029ADE7",
                     "055b27f3-903e-5eb9-8758-197c1029ade7/../x"];
    for (const value of hostile) {
      const a = answer("running-turn-sent");
      a.body.attempts[0].sessionDetail = { conversationId: value, canvasPath: `/conversations/${value}`, authority: "fixture" };
      renderCard(() => a);
      const card = await settled();
      const [attempt] = attempts(card);
      expect(card.querySelectorAll("a, [href], [src], iframe"), value).toHaveLength(0);
      expect((within(attempt).getByTestId("outcome-session-detail") as HTMLButtonElement).disabled, value).toBe(true);
      cleanup();
    }
  });

  it("shows no evidence for an attempt that has none, and says so", async () => {
    const card = await show("pending-created");
    const [attempt] = attempts(card);
    expect(within(attempt).getByTestId("outcome-observed").textContent).toContain("No evidence observed by the host");
    expect(within(attempt).getByTestId("outcome-asserted").textContent).toContain("Nothing the attempt reported");
  });
});

describe("why, approach, Work and stage", () => {
  it("shows the objective, the design, the linked tasks and the attempt's stage", async () => {
    const a = answer("reconnect", 1);
    const card = await show("reconnect", 1);
    expect(within(card).getByTestId("outcome-objective").textContent).toBe(a.body.objective.facts.statement);
    expect(within(card).getAllByTestId("outcome-design")).toHaveLength(a.body.designs.length);
    expect(within(card).getAllByTestId("outcome-statement")).toHaveLength(a.body.statements.length);
    expect(tasks(card).map((t) => t.getAttribute("data-reference"))).toEqual(a.body.tasks.map((t: any) => t.reference));
    expect(within(attempts(card)[0]).getByTestId("outcome-stage-name").textContent).toBe(a.body.attempts[0].stage);
  });
});

describe("inert rendering (R14)", () => {
  it("renders agent-derived text as text: no element, link or script is made from it", async () => {
    const hostile = [
      '<img src=x onerror="window.__aiehHit=1">',
      "[click](javascript:window.__aiehHit=2)",
      '<a href="http://203.0.113.9/">x</a><script>window.__aiehHit=3</script>',
    ].join(" ");
    const a = answer("reconnect", 1);
    a.body.objective.facts.statement = hostile;
    a.body.attempts[0].detail = hostile;
    a.body.attempts[0].result.tests.command = hostile;
    a.body.attempts[0].result.reported.commit = hostile;
    a.body.lineageUncertainties[0].detail = hostile;
    a.body.designs[0].reference = hostile;
    renderCard(() => a);
    const card = await settled();
    expect(card.getAttribute("data-state")).toBe("shown");
    expect(card.querySelectorAll("img, script, iframe, object, embed")).toHaveLength(0);
    // U-01.2: the one link is the session detail's, its address the shell's own route built from checked ids
    expect(Array.from(card.querySelectorAll("a, [href], [src]")).map((e) => e.getAttribute("href"))).toEqual([
      `/engineering/outcomes/${OUTCOME_ID}/sessions/${a.body.attempts[0].conversationId}`,
    ]);
    expect(within(card).getByTestId("outcome-objective").textContent).toBe(hostile);
    expect((card.textContent ?? "").split(hostile).length - 1).toBeGreaterThanOrEqual(5);
    expect((window as any).__aiehHit).toBeUndefined();
  });
});

describe("read-only, refresh and reconnect", () => {
  it("asks only GET /outcomes/<id> with the session header; Read again asks once more and writes nothing", async () => {
    const { seen, credential } = renderCard(() => answer("pending-created"));
    await settled();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    });
    await settled();
    expect(seen).toEqual([
      { method: "GET", path: outcomePath(OUTCOME_ID), header: credential, body: undefined },
      { method: "GET", path: outcomePath(OUTCOME_ID), header: credential, body: undefined },
    ]);
  });

  it("shows a projection that changed between reads as its new state (running, then published)", async () => {
    let read = 0;
    renderCard(() => answer("reconnect", read++ === 0 ? 0 : 1));
    let card = await settled();
    expect(attempts(card)[0].getAttribute("data-status")).toBe("running");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    });
    card = await settled();
    expect(attempts(card)[0].getAttribute("data-status")).toBe("succeeded");
    expect(attempts(card)[0].getAttribute("data-code")).toBe("RESULT_PUBLISHED");
  });

  it("keeps the newest read: an older read's answer that arrives later never replaces it", async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    const reader = (respond: () => Promise<Answer>): FetchLike => async () => {
      const a = await respond();
      return new Response(JSON.stringify(a.body), { status: a.status });
    };
    const credential = throwawayCredential();
    // the first client's read answers last, with the older state (a client replaced while it was pending: a new sign-in)
    const first = createIntegrationClient(credential, reader(async () => {
      await held;
      return answer("reconnect", 0);
    }));
    const second = createIntegrationClient(credential, reader(async () => answer("reconnect", 1)));
    const view = render(<OutcomeProjectionCard client={first} outcome={OUTCOME_ID} />);
    view.rerender(<OutcomeProjectionCard client={second} outcome={OUTCOME_ID} />);
    const card = await settled();
    expect(attempts(card)[0].getAttribute("data-status")).toBe("succeeded");
    await act(async () => {
      release();
      await held;
    });
    expect(attempts(card)[0].getAttribute("data-status")).toBe("succeeded");
    expect(attempts(card)[0].getAttribute("data-code")).toBe("RESULT_PUBLISHED");
  });

  it("shows the Integration process unreachable, then the projection once it answers again", async () => {
    let up = false;
    const seen: string[] = [];
    const client = createIntegrationClient(throwawayCredential(), async (url) => {
      seen.push(url);
      if (!up) throw new TypeError("connection refused");
      return new Response(JSON.stringify(answer("reconnect", 1).body), { status: 200 });
    });
    render(<OutcomeProjectionCard client={client} outcome={OUTCOME_ID} />);
    let card = await settled();
    expect(card.getAttribute("data-state")).toBe("refused");
    expect(within(card).getByTestId("outcome-refusal-code").textContent).toBe("UNREACHABLE");
    up = true;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    });
    card = await settled();
    expect(card.getAttribute("data-state")).toBe("shown");
    expect(seen).toEqual([INTEGRATION_ORIGIN + outcomePath(OUTCOME_ID), INTEGRATION_ORIGIN + outcomePath(OUTCOME_ID)]);
  });

  it("reads nothing without a client or an outcome id, and says why", async () => {
    render(<OutcomeProjectionCard client={null} outcome={OUTCOME_ID} />);
    expect(screen.getByTestId("outcome-card").getAttribute("data-state")).toBe("unavailable");
    cleanup();
    const { seen } = renderCard(() => answer("pending-created"), null);
    expect(screen.getByTestId("outcome-card").getAttribute("data-state")).toBe("unreadable");
    expect(seen).toEqual([]);
  });
});

describe("responsive at the shell's breakpoint", () => {
  it("lays the card out wide at and above 900 px and narrow below, live", async () => {
    setViewportWidth(WIDE_MIN_WIDTH);
    const card = await show("reconnect", 1);
    expect(card.getAttribute("data-layout")).toBe("wide");
    act(() => setViewportWidth(WIDE_MIN_WIDTH - 1));
    expect(card.getAttribute("data-layout")).toBe("narrow");
    act(() => setViewportWidth(1280));
    expect(card.getAttribute("data-layout")).toBe("wide");
  });

  it("stacks the sections by default and makes two columns only in the wide layout", () => {
    const css = shellCss.replace(/\/\*[\s\S]*?\*\//g, "");
    expect(css).toMatch(/\.owner-outcome__sections\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/);
    expect(css).toMatch(/\.owner-outcome\[data-layout="wide"\] \.owner-outcome__sections\s*\{[^}]*repeat\(2, minmax\(0, 1fr\)\)/);
    expect(css).not.toMatch(/\.owner-outcome[^{]*\{[^}]*(?:min-width|width):\s*\d{3,}px/);
  });
});

describe("the review's fixes (U-04.2 fix round)", () => {
  it("S2: never says there is no blocker while lineage uncertainties hold missing links or unavailable sources", async () => {
    for (const name of ["published-live", "running-turn-sent"]) {
      const a = answer(name);
      renderCard(() => a);
      const card = await settled();
      const missing = within(card).getByTestId("outcome-missing");
      expect(missing.textContent, name).not.toContain("No blocker");
      const [item] = within(missing)
        .getAllByTestId("outcome-missing-item")
        .filter((m) => m.getAttribute("data-kind") === "uncertain-sources");
      expect(item.textContent, name).toContain(`${a.body.lineageUncertainties.length} lineage uncertainties are recorded`);
      for (const code of ["NO_ATTEMPT_FOR_TASK", "RESOLVER_NOT_CONFIGURED"]) expect(item.textContent, name).toContain(code);
      cleanup();
    }
    // with nothing at all, the empty case names the uncertainties too
    const bare = answer("pending-created");
    bare.body.lineageUncertainties = [];
    bare.body.tasks = bare.body.tasks.filter((t: any) => t.execution.status !== "failed" && t.execution.status !== "unknown");
    renderCard(() => bare);
    const card = await settled();
    expect(within(card).getByTestId("outcome-missing").textContent).toContain(
      "No blocker, missing source or lineage uncertainty is recorded in this projection.",
    );
  });

  it("S3: an outcome argument that is not an outcome id makes no request, through the tool UI or the exported card", async () => {
    const seen: string[] = [];
    const client = createIntegrationClient(throwawayCredential(), async (url) => {
      seen.push(url);
      return new Response(JSON.stringify(answer("pending-created").body), { status: 200 });
    });
    const Tool = OutcomeCard as unknown as (props: Record<string, unknown>) => ReactElement;
    for (const outcome of ["../threads", "http://203.0.113.9/x", "//203.0.113.9", OUTCOME_ID.toUpperCase(), `${OUTCOME_ID}/..`, 7]) {
      render(
        <OutcomeClientContext.Provider value={client}>
          <Tool args={{ outcome }} toolCallId="t" toolName="outcome_card" argsText="" status={{ type: "complete" }} />
        </OutcomeClientContext.Provider>,
      );
      expect(screen.getByTestId("outcome-card").getAttribute("data-state"), String(outcome)).toBe("unreadable");
      cleanup();
      render(<OutcomeProjectionCard client={client} outcome={outcome} />);
      expect(screen.getByTestId("outcome-card").getAttribute("data-state"), String(outcome)).toBe("unreadable");
      cleanup();
    }
    render(<OutcomeProjectionCard client={client} outcome=".." />);
    expect(screen.getByTestId("outcome-card").getAttribute("data-state")).toBe("unreadable");
    await act(async () => {});
    expect(seen).toEqual([]);
    expect(outcomeId(OUTCOME_ID)).toBe(OUTCOME_ID);
    // the path is encoded besides: nothing given can leave /outcomes/
    expect(outcomePath("a/../b?c#d")).toBe("/outcomes/a%2F..%2Fb%3Fc%23d");
  });

  it("S3: a request the shell's own client refuses is shown as not sent, never as unreachable", async () => {
    const client = { request: async () => Promise.reject(new Error("not a path of the Integration process: x")) };
    render(<OutcomeProjectionCard client={client} outcome={OUTCOME_ID} />);
    const card = await settled();
    expect(card.getAttribute("data-state")).toBe("not-sent");
    expect(within(card).getByTestId("outcome-not-sent").textContent).toContain("not a path of the Integration process");
    expect(within(card).queryByTestId("outcome-refusal-code")).toBeNull();
  });

  it("S4: a hostile string in every string field and key of a projection creates no element, link or source", async () => {
    const hostile =
      'javascript:alert(1)<img src=x onerror="window.__aiehHit=1"><a href="http://203.0.113.9/">x</a><script>window.__aiehHit=2</script>[x](javascript:1)';
    const poison = (value: unknown): unknown => {
      if (typeof value === "string") return hostile;
      if (Array.isArray(value)) return value.map(poison);
      if (value !== null && typeof value === "object") {
        const out: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(value)) out[k] = poison(v);
        out[hostile] = hostile;
        return out;
      }
      return value;
    };
    const cases: [string, number][] = [["published-disclosed", 0], ["reconnect", 1], ["unknown-label-missing", 0], ["lineage-failed", 0]];
    for (const [name, index] of cases) {
      const a = answer(name, index);
      const body = poison(a.body) as Record<string, unknown>;
      body.format = a.body.format;
      renderCard(() => ({ status: 200, body }));
      const card = await settled();
      expect(card.getAttribute("data-state"), name).toBe("shown");
      expect(card.querySelectorAll("a, img, script, iframe, object, embed, [href], [src]"), name).toHaveLength(0);
      // a hostile value may stand only in a text attribute (data-*, aria-label), never in one the browser acts on
      const attributes = Array.from(card.querySelectorAll("*")).flatMap((e) =>
        Array.from(e.attributes).filter((x) => x.value.includes("javascript:") && !/^(data|aria)-/.test(x.name)),
      );
      expect(attributes.map((x) => x.name), name).toEqual([]);
      expect((card.textContent ?? "").split(hostile).length - 1, name).toBeGreaterThan(10);
      expect((window as any).__aiehHit, name).toBeUndefined();
      cleanup();
    }
  });

  it("S4: the card's sources build no HTML, link or source from projection data", () => {
    const sources: [string, string][] = [
      ["outcome-card.tsx", cardSource],
      ["outcome-projection.ts", projectionSource],
      ["EngineeringSession.tsx", engineeringSessionSource],
      ["session-detail.ts", sessionDetailSource],
    ];
    for (const [file, source] of sources) {
      expect(/dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(source), file).toBe(false);
      expect(/\bhref\b/.test(source), file).toBe(false);
      expect(/\bsrc\s*[=:]/.test(source), file).toBe(false);
      expect(/<(a|img|iframe|script|object|embed|Link|NavLink)\b/.test(source), file).toBe(false);
      expect(/\bto=/.test(source), file).toBe(false);
    }
  });

  it("U-01.2: the only href, to or src built from a projection value goes through the one checked builder", () => {
    const s = sessionLinksSource;
    expect(/dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(s)).toBe(false);
    // every address attribute in SessionLinks.tsx is one of two variables ...
    expect([...s.matchAll(/\b(href|to|src)=\{([^}]*)\}/g)].map((m) => `${m[1]}=${m[2]}`)).toEqual([
      "to=sessionPath",
      "href=sessionPath",
      "src=frameUrl",
    ]);
    expect(/\b(href|to|src)="/.test(s)).toBe(false);
    // ... each assigned once, from the checked builder, and never otherwise
    expect([...s.matchAll(/\bsessionPath\s*=(?!=)([^;]*);/g)].map((m) => m[1].trim())).toEqual(["engineeringSessionPath(outcome, conversation)"]);
    expect([...s.matchAll(/\bframeUrl\s*=(?!=)([^;]*);/g)].map((m) => m[1].trim())).toEqual(["canvasConversationUrl(conversation)"]);
    expect((s.match(/<(a|iframe|Link)\b/g) ?? []).sort()).toEqual(["<Link", "<a", "<iframe"]);
    // the builder: two templates, each a shell-owned constant prefix and checked ids only
    const templates = [...sessionDetailSource.matchAll(/return [^;]*`(\$\{[^`]*)`;/g)].map((m) => m[1]);
    expect(templates).toEqual(["${CANVAS_ORIGIN}${CANVAS_CONVERSATIONS}${id}", "${ENGINEERING_OUTCOMES}${o}${SESSIONS}${c}"]);
    expect(sessionDetailSource).toContain("const id = checkedId(conversation);");
    expect(sessionDetailSource).toContain("const o = checkedId(outcome);");
    expect(sessionDetailSource).toContain("const c = checkedId(conversation);");
  });

  it("note 1: a code or refusal named like an Object.prototype member is a code the card does not know", async () => {
    for (const code of ["constructor", "toString", "__proto__", "hasOwnProperty", "toString_UNPROVEN", "constructor_UNPROVEN"]) {
      expect(codeMeaning(code), code).toBe(codeMeaning("NO_SUCH_CODE"));
      expect(statusCodeDisagree("succeeded", code), code).toBe(code.endsWith("_UNPROVEN"));
    }
    const a = answer("reconnect", 1);
    a.body.attempts[0].executionCode = "constructor";
    renderCard(() => a);
    let card = await settled();
    expect(within(attempts(card)[0]).getAllByTestId("outcome-code-meaning")[0].textContent).toBe(codeMeaning("NO_SUCH_CODE"));
    cleanup();
    renderCard(() => ({ status: 503, body: { code: "toString", detail: "d", remedy: "r" } }));
    card = await settled();
    expect(within(card).getByTestId("outcome-refusal-code").textContent).toBe("ANSWER_INVALID");
  });

  it("note 2: a status and code the state table does not pair are shown with a visible warning", async () => {
    const a = answer("reconnect", 1);
    a.body.attempts[0].executionCode = "RESULT_PUBLISHING";
    renderCard(() => a);
    const card = await settled();
    const [attempt] = attempts(card);
    expect(attempt.getAttribute("data-status")).toBe("succeeded");
    expect(within(attempt).getAllByTestId("outcome-status-code-disagree")[0].textContent).toContain("Status and code disagree");
    // no committed answer of the projection shows the warning, and the table names every code of the projection
    expect(Object.keys(CODE_STATUS).sort()).toEqual([...projectionSchema().codes].sort());
    for (const name of SCENARIOS) {
      for (const f of fixture(name).answers) {
        if (f.status !== 200) continue;
        const pairs: [unknown, unknown][] = [
          ...f.body.attempts.map((t: any) => [t.executionStatus, t.executionCode]),
          ...f.body.tasks.map((t: any) => [t.execution.status, t.execution.code]),
        ];
        for (const [status, code] of pairs) expect(statusCodeDisagree(status, code), `${name} ${status} ${code}`).toBe(false);
      }
    }
  });

  it("note 5: a published result's status carries the Work-status disclaimer", async () => {
    const card = await show("reconnect", 1);
    const badge = within(attempts(card)[0]).getAllByTestId("outcome-status")[0];
    expect(badge.textContent).toContain(STATUS_MEANING.succeeded);
    expect(badge.textContent).toContain("The Work item's own status is not changed by this.");
  });

  it("note 6: a list in an entry is shown element by element, never as [object Object]", async () => {
    const a = answer("reconnect", 1);
    a.body.attempts[0].evidence.commit.extra = [{ k: "v1" }, "s2", [3, { k: "v4" }]];
    renderCard(() => a);
    const card = await settled();
    expect(card.textContent).not.toContain("[object Object]");
    const values = within(card).getAllByTestId("outcome-reference-value").map((v) => v.textContent);
    expect(values).toEqual(expect.arrayContaining(["v1", "s2", "v4"]));
  });
});
