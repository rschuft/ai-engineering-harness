import { describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, type RouteObject } from "react-router";
import { OwnerApp } from "../App";
import { ownerRoutes } from "../routes";
import { OutcomeProjectionCard } from "../areas/outcome-card";
import { useOwnerSession } from "../identity/OwnerSessionContext";
import {
  CREDENTIAL_STORAGE_KEY,
  INTEGRATION_ORIGIN,
  SESSION_HEADER,
  storeCredential,
  type FetchLike,
} from "../identity/owner-session";
import { OUTCOME_ID, answer, type Answer } from "../test/outcome-fixtures";
import { CANVAS_ORIGIN } from "./session-detail";

// The engineering session route and the outcome card's link to it (plan leaf U-01.2), in jsdom: the
// Owner reaches an attempt's session detail from its outcome card by a link, without seeing or typing
// an internal id; the route's own address holds the selection, so a refresh keeps it; the frame's
// address is the shell's constant Canvas origin and the checked conversation id, and no credential
// reaches it. A fake Integration process answers the sign-in check and the projection's committed
// answers (outcome_card_fixtures.py); the setup's network guard refuses any real request. No real
// browser is opened here (G5 waits).

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

type Seen = { url: string; method: string; header: string | undefined };

function fakeIntegration(projection: () => Answer) {
  const seen: Seen[] = [];
  const fetchImpl: FetchLike = async (url, init) => {
    seen.push({ url, method: init.method ?? "GET", header: (init.headers as Record<string, string>)[SESSION_HEADER] });
    const path = url.slice(INTEGRATION_ORIGIN.length);
    if (path === "/session" && init.method === "POST") {
      return new Response(
        JSON.stringify({ sessionId: "6f1c2a3b-4d5e-4f60-8a7b-9c0d1e2f3a4b", issuedAt: "2026-11-17T10:00:00Z", expiresAt: "2026-11-17T22:00:00Z" }),
        { status: 200 },
      );
    }
    if (path === `/outcomes/${OUTCOME_ID}` && (init.method ?? "GET") === "GET") {
      const a = projection();
      return new Response(JSON.stringify(a.body), { status: a.status });
    }
    return new Response(JSON.stringify({ code: "NOT_FOUND" }), { status: 404 });
  };
  return { seen, fetchImpl };
}

function signIn(credential: string) {
  storeCredential({
    credential,
    sessionId: "6f1c2a3b-4d5e-4f60-8a7b-9c0d1e2f3a4b",
    issuedAt: "2026-11-17T10:00:00Z",
    expiresAt: "2026-11-17T22:00:00Z",
  });
}

/** The outcome card as the chat shows it, through the signed-in shell's own Integration client. */
function CardInShell() {
  const { client } = useOwnerSession();
  return <OutcomeProjectionCard client={client} outcome={OUTCOME_ID} />;
}

function routesWithCard(): RouteObject[] {
  const [shell] = ownerRoutes;
  const children: RouteObject[] = [{ path: "card", element: <CardInShell /> }, ...(shell.children ?? [])];
  return [{ path: shell.path, element: shell.element, children }];
}

function app(path: string, fetchImpl: FetchLike) {
  const router = createMemoryRouter(routesWithCard(), { initialEntries: [path] });
  render(<OwnerApp router={router} fetchImpl={fetchImpl} />);
  return router;
}

function sessionPath(conversation: string) {
  return `/engineering/outcomes/${OUTCOME_ID}/sessions/${conversation}`;
}

async function shown(testId: string) {
  return await screen.findByTestId(testId, undefined, { timeout: 10000 });
}

describe("the engineering session route", () => {
  it("shows the fixture label, the attempt's status from the projection and Canvas's view in a frame from its own origin", async () => {
    const credential = throwawayCredential();
    signIn(credential);
    const a = answer("running-turn-sent");
    const [attempt] = a.body.attempts;
    const { seen, fetchImpl } = fakeIntegration(() => a);
    app(sessionPath(attempt.conversationId), fetchImpl);
    const frame = (await shown("canvas-frame")) as HTMLIFrameElement;
    expect(frame.getAttribute("src")).toBe(`${CANVAS_ORIGIN}/conversations/${attempt.conversationId}`);
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-same-origin allow-forms");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("allow")).toBe("");
    expect(screen.getByTestId("engineering-session-fixture").textContent).toContain("FIXTURE");
    const status = within(screen.getByTestId("engineering-session-status")).getByTestId("outcome-status");
    expect(status.getAttribute("data-status")).toBe(attempt.executionStatus);
    expect(within(screen.getByTestId("engineering-session-status")).getByTestId("outcome-code").textContent).toBe(attempt.executionCode);
    // no credential reaches the frame: not in its address, not in any attribute; and the shell's only requests are to
    // the Integration process, each with the header, none to the Canvas origin
    const everything = document.documentElement.outerHTML;
    expect(everything).not.toContain(credential);
    expect(Array.from(frame.attributes).map((x) => x.value).join(" ")).not.toContain(credential);
    expect(frame.getAttribute("src")).not.toMatch(/[?#]/);
    expect(seen.length).toBeGreaterThan(0);
    for (const s of seen) {
      expect(s.url.startsWith(INTEGRATION_ORIGIN + "/"), s.url).toBe(true);
      expect(s.header).toBe(credential);
      expect(s.url.startsWith(CANVAS_ORIGIN)).toBe(false);
    }
    expect(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)).toContain(credential);
  });

  it("shows no frame, and the projection's reason, for a live-bound or unbound attempt", async () => {
    for (const name of ["published-live", "authority-unbound"]) {
      const credential = throwawayCredential();
      signIn(credential);
      const a = answer(name);
      const [attempt] = a.body.attempts;
      const { fetchImpl } = fakeIntegration(() => a);
      app(sessionPath(attempt.conversationId), fetchImpl);
      const refused = await shown("engineering-session-refused");
      expect(refused.getAttribute("data-reason"), name).toBe("SESSION_ACCESS_UNAVAILABLE");
      expect(refused.textContent, name).toContain(attempt.sessionDetail.reason);
      expect(document.querySelectorAll("iframe"), name).toHaveLength(0);
      expect(screen.queryByTestId("engineering-session-fixture"), name).toBeNull();
      cleanup();
      window.localStorage.clear();
    }
  });

  it("shows no frame and asks nothing for an address whose ids do not pass the check", async () => {
    const credential = throwawayCredential();
    signIn(credential);
    const a = answer("running-turn-sent");
    const { seen, fetchImpl } = fakeIntegration(() => a);
    const cid = a.body.attempts[0].conversationId;
    for (const path of [
      `/engineering/outcomes/${OUTCOME_ID}/sessions/${cid.toUpperCase()}`,
      `/engineering/outcomes/${OUTCOME_ID}/sessions/javascript:alert(1)`,
      `/engineering/outcomes/${OUTCOME_ID}/sessions/${encodeURIComponent("//203.0.113.9")}`,
      `/engineering/outcomes/not-an-outcome/sessions/${cid}`,
    ]) {
      app(path, fetchImpl);
      const refused = await shown("engineering-session-refused");
      expect(refused.getAttribute("data-reason"), path).toBe("NOT_AN_ID");
      expect(document.querySelectorAll("iframe"), path).toHaveLength(0);
      cleanup();
    }
    expect(seen.filter((s) => s.url.includes("/outcomes/"))).toEqual([]);
  });

  it("shows no frame when the projection's action names a conversation id the shell does not accept", async () => {
    const credential = throwawayCredential();
    signIn(credential);
    const a = answer("running-turn-sent");
    const cid = a.body.attempts[0].conversationId;
    a.body.attempts[0].sessionDetail = { conversationId: "../threads", canvasPath: "/conversations/../threads", authority: "fixture" };
    const { fetchImpl } = fakeIntegration(() => a);
    app(sessionPath(cid), fetchImpl);
    await shown("engineering-session-refused");
    expect(document.querySelectorAll("iframe, a[href*='threads']")).toHaveLength(0);
  });

  it("shows no frame for a conversation the outcome's projection does not name", async () => {
    signIn(throwawayCredential());
    const a = answer("running-turn-sent");
    const { fetchImpl } = fakeIntegration(() => a);
    app(sessionPath("11111111-2222-4333-8444-555555555555"), fetchImpl);
    const refused = await shown("engineering-session-refused");
    expect(refused.getAttribute("data-reason")).toBe("SESSION_ACCESS_UNAVAILABLE");
    expect(document.querySelectorAll("iframe")).toHaveLength(0);
  });

  it("shows no frame while signed out", async () => {
    const { fetchImpl } = fakeIntegration(() => answer("running-turn-sent"));
    app(sessionPath(answer("running-turn-sent").body.attempts[0].conversationId), fetchImpl);
    await shown("engineering-session-signed-out");
    expect(document.querySelectorAll("iframe")).toHaveLength(0);
  });
});

describe("criterion 1: from the outcome card to the session detail, without an internal id", () => {
  it("follows the card's link to the route, and a refresh of the route keeps the selection", async () => {
    const credential = throwawayCredential();
    signIn(credential);
    const a = answer("running-turn-sent");
    const [attempt] = a.body.attempts;
    const { fetchImpl } = fakeIntegration(() => a);
    const router = app("/card", fetchImpl);
    const link = (await shown("outcome-session-detail")) as HTMLAnchorElement;
    expect(link.tagName).toBe("A");
    expect(link.textContent).toBe("Open the session detail (FIXTURE)");
    // the Owner sees no id in what he clicks; the address is the shell's own route
    expect(link.textContent).not.toContain(attempt.conversationId);
    expect(link.getAttribute("href")).toBe(sessionPath(attempt.conversationId));
    await act(async () => {
      fireEvent.click(link);
    });
    await waitFor(() => expect(router.state.location.pathname).toBe(sessionPath(attempt.conversationId)));
    const frame = (await shown("canvas-frame")) as HTMLIFrameElement;
    expect(frame.getAttribute("src")).toBe(`${CANVAS_ORIGIN}/conversations/${attempt.conversationId}`);
    const where = router.state.location.pathname;
    // a refresh: the shell torn down and opened again at the same address
    cleanup();
    app(where, fetchImpl);
    const again = (await shown("canvas-frame")) as HTMLIFrameElement;
    expect(again.getAttribute("src")).toBe(`${CANVAS_ORIGIN}/conversations/${attempt.conversationId}`);
    expect(screen.getByTestId("engineering-session-fixture").textContent).toContain("FIXTURE");
  });
});
