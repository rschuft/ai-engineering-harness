// The outcome card end to end over HTTP (plan leaf U-04.2), the Owner host's half: driven by
// integrations/ownerhost/tests/test_outcome_card_http.py, which serves the Integration process's
// application in its own process on a free loopback port with the real projection of a published
// fixture attempt, and passes the port, a throwaway session credential and a report path in
// AIEH_OUTCOME_CARD_HTTP. Without it the test is skipped: it never runs in the shell's own suite.
//
// The card is the shell's own, with the shell's own Integration client; only the transport differs: a
// loopback node:http request to the given port (the shell's address, 127.0.0.1:13310, is never used
// here), carrying the session header and the shell's Origin as a browser would. The card is rendered,
// torn down and rendered again (a reload), and what each render shows is written to the report.
import { request } from "node:http";
import { writeFileSync } from "node:fs";
import process from "node:process";
import { createElement } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OutcomeProjectionCard } from "./outcome-card";
import { INTEGRATION_ORIGIN, SESSION_HEADER, createIntegrationClient } from "../identity/owner-session";

const GIVEN = process.env.AIEH_OUTCOME_CARD_HTTP ? JSON.parse(process.env.AIEH_OUTCOME_CARD_HTTP) : null;
const SHELL_ORIGIN = "http://127.0.0.1:5173";
const RESERVED_PORTS = [13310, 13320, 13330];

function loopbackFetch(port, seen) {
  return (url, init) =>
    new Promise((resolve, reject) => {
      if (!url.startsWith(INTEGRATION_ORIGIN + "/")) {
        reject(new Error(`not the Integration process's address: ${url}`));
        return;
      }
      const path = url.slice(INTEGRATION_ORIGIN.length);
      const headers = { ...init.headers, Origin: SHELL_ORIGIN };
      seen.push({ method: init.method ?? "GET", path, session: headers[SESSION_HEADER] !== undefined });
      const req = request({ host: "127.0.0.1", port, path, method: init.method ?? "GET", headers }, (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => resolve(new Response(Buffer.concat(chunks).toString("utf-8"), { status: res.statusCode })));
        res.on("error", reject);
      });
      req.on("error", reject);
      if (init.body !== undefined) req.write(init.body);
      req.end();
    });
}

async function rendered(client) {
  render(createElement(OutcomeProjectionCard, { client, outcome: GIVEN.outcome }));
  const card = screen.getByTestId("outcome-card");
  await waitFor(() => expect(card.getAttribute("data-state")).not.toBe("loading"), { timeout: 30000 });
  expect(card.getAttribute("data-state"), card.textContent).toBe("shown");
  const [attempt] = within(card).getAllByTestId("outcome-attempt");
  const shown = {
    state: card.getAttribute("data-state"),
    status: attempt.getAttribute("data-status"),
    code: attempt.getAttribute("data-code"),
    authority: attempt.getAttribute("data-authority"),
    fixtureLabel: within(card).queryByTestId("outcome-fixture-label") !== null,
    attemptFixtureLabel: within(attempt).queryByTestId("outcome-attempt-fixture-label") !== null,
    observed: Array.from(
      within(attempt).getByTestId("outcome-observed").querySelectorAll("[data-testid='outcome-reference-value']"),
      (el) => el.textContent,
    ),
    coverage: within(card).getByTestId("outcome-coverage").textContent,
    uncertainties: within(card)
      .getAllByTestId("outcome-uncertainty")
      .map((u) => u.getAttribute("data-code")),
    body: within(card).getByTestId("outcome-body").textContent,
  };
  cleanup();
  return shown;
}

describe("the outcome card over HTTP (U-04.2)", () => {
  (GIVEN ? it : it.skip)("renders the served projection, and the same card again after a reload", async () => {
    expect(RESERVED_PORTS).not.toContain(GIVEN.port);
    const seen = [];
    const client = createIntegrationClient(GIVEN.credential, loopbackFetch(GIVEN.port, seen));
    const first = await rendered(client);
    const second = await rendered(createIntegrationClient(GIVEN.credential, loopbackFetch(GIVEN.port, seen)));
    expect(second.body).toBe(first.body);
    expect(first.status).toBe("succeeded");
    expect(first.observed).toContain(GIVEN.commit);
    writeFileSync(
      GIVEN.report,
      JSON.stringify({ ...first, first: first.body, second: second.body, requests: seen }, null, 1),
      "utf-8",
    );
  });
});
