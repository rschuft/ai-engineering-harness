import { describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StoredChat } from "./ChatArea";
import { ACCEPTANCE_RECORD_TOOL, OUTCOME_TOOL, sha256Hex } from "./chat-adapter";
import { INTEGRATION_ORIGIN, SESSION_HEADER, createIntegrationClient, type FetchLike } from "../identity/owner-session";
import { OUTCOME_ID, answer, type Answer } from "../test/outcome-fixtures";

// The reconnect acceptance fixture of the outcome card (plan leaf U-04.2; U-04's proof: "survives
// reconnect and never marks Work complete on agent exit"). A fake Integration process keeps threads
// and messages in memory with the store's rules, answers the acceptance routes as acceptance.py does,
// and answers GET /outcomes/{id} with the projection's committed answers (outcome_card_fixtures.py).
// Once the Owner's acceptance is recorded, the reply holds the outcome's card; the shell is then torn
// down and made again (a reload), the thread read back from the store, and the card shows the same
// outcome from a fresh read of the projection, with no write. A projection that changed in between is
// shown as its new state. The setup's network guard refuses any real request.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";
const REVIEW = "Review acceptance: O1 of add-slugify";
const ACCEPT = "Accept O1 of add-slugify";
const NONCE = "c1".repeat(16);
const COMMIT = "89abcdef0123456789abcdef0123456789abcdef";

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

type Stored = { seq: number; parentId: string | null; message: any };
type Seen = { method: string; path: string; body: any; status: number };

class FakeIntegration {
  threads = new Map<string, { localId: string; messages: Stored[] }>();
  seen: Seen[] = [];
  cards = new Map<string, string>();
  /** The outcome projection's answer, as the Integration process would read it now. */
  projection: Answer = answer("reconnect", 0);
  private next = 0;

  constructor(readonly credential: string) {}

  fetchImpl: FetchLike = async (url, init) => {
    expect(url.startsWith(INTEGRATION_ORIGIN + "/")).toBe(true);
    expect((init.headers as Record<string, string>)[SESSION_HEADER]).toBe(this.credential);
    const path = url.slice(INTEGRATION_ORIGIN.length);
    const method = init.method ?? "GET";
    const body = init.body === undefined ? undefined : JSON.parse(init.body as string);
    const [status, reply] = await this.route(method, path, body);
    this.seen.push({ method, path, body, status });
    return new Response(JSON.stringify(reply), { status });
  };

  writes(): Seen[] {
    return this.seen.filter((s) => s.method !== "GET");
  }

  reads(path: string): Seen[] {
    return this.seen.filter((s) => s.method === "GET" && s.path === path);
  }

  private find(id: string): Stored | undefined {
    for (const t of this.threads.values()) {
      const found = t.messages.find((s) => s.message.id === id);
      if (found) return found;
    }
    return undefined;
  }

  private async route(method: string, path: string, body: any): Promise<[number, unknown]> {
    let m: RegExpMatchArray | null;
    if (path === `/outcomes/${OUTCOME_ID}` && method === "GET") return [this.projection.status, this.projection.body];
    if (path === "/threads" && method === "GET")
      return [200, { threads: [...this.threads.keys()].map((remoteId) => ({ remoteId, status: "regular" })) }];
    if (path === "/threads" && method === "POST") {
      for (const [remoteId, t] of this.threads) if (t.localId === body.localId) return [200, { remoteId }];
      const remoteId = `0000000${++this.next}-7b4d-4e8a-9c0b-1d2e3f405162`.slice(-36);
      this.threads.set(remoteId, { localId: body.localId, messages: [] });
      return [200, { remoteId }];
    }
    if ((m = path.match(/^\/threads\/[^/]+\/messages\/([^/]+)\/acceptance-challenge$/))) {
      const stored = this.find(decodeURIComponent(m[1]));
      if (!stored) return [404, { code: "MESSAGE_NOT_FOUND" }];
      if ((await sha256Hex(stored.message.content[0].text)) !== body.sha256) return [409, { code: "ACCEPTANCE_MESSAGE_MISMATCH" }];
      this.cards.set(NONCE, body.card);
      return [200, { nonce: NONCE, change: "add-slugify", item: "O1", revision: "0".repeat(40), proposal: "1".repeat(64),
                     summary: "Objective O1: Titles become URL slugs.", expiresAt: "2026-11-17T13:00:00Z", card: body.card,
                     request: stored.message.id }];
    }
    if ((m = path.match(/^\/threads\/[^/]+\/messages\/([^/]+)\/acceptance$/))) {
      const stored = this.find(decodeURIComponent(m[1]));
      if (!stored) return [404, { code: "MESSAGE_NOT_FOUND" }];
      if (this.cards.get(body.nonce) === undefined) return [409, { code: "ACCEPTANCE_CHALLENGE_UNKNOWN" }];
      return [200, { change: "add-slugify", item: "O1", outcome: OUTCOME_ID, minted: true, commit: COMMIT, decision: "d",
                     reference: `outcome:${OUTCOME_ID}@${COMMIT}`, statement: `conversation:x/${stored.message.id}#sha256:${body.sha256}`,
                     receipt: "r", created: true, state: "confirmed", project: "aieh-d1-demo" }];
    }
    if ((m = path.match(/^\/threads\/([^/]+)\/messages$/))) {
      const thread = this.threads.get(decodeURIComponent(m[1]));
      if (!thread) return [404, { code: "THREAD_NOT_FOUND" }];
      if (method === "GET") return [200, { messages: thread.messages }];
      const existing = thread.messages.find((s) => s.message.id === body.message.id);
      if (existing) return [200, { id: body.message.id, seq: existing.seq, revision: 1, changed: false }];
      const stored = { seq: thread.messages.length + 1, parentId: body.parentId, message: body.message };
      thread.messages.push(stored);
      return [200, { id: body.message.id, seq: stored.seq, revision: 1, changed: true }];
    }
    if ((m = path.match(/^\/threads\/([^/]+)$/)) && method === "GET") return [200, { remoteId: m[1], status: "regular" }];
    return [404, { code: "NOT_FOUND" }];
  }
}

function renderChat(fake: FakeIntegration) {
  render(<StoredChat client={createIntegrationClient(fake.credential, fake.fetchImpl)} />);
}

async function send(text: string) {
  const thread = await screen.findByTestId("chat-thread");
  await act(async () => {
    fireEvent.change(within(thread).getByRole("textbox", { name: "Message" }), { target: { value: text } });
  });
  await act(async () => {
    fireEvent.click(within(thread).getByRole("button", { name: "Send" }));
  });
}

async function outcomeCard(status: string): Promise<HTMLElement> {
  const card = await screen.findByTestId("outcome-card");
  await waitFor(() => expect(card.getAttribute("data-state")).toBe("shown"));
  await waitFor(() => expect(within(card).getAllByTestId("outcome-attempt")[0].getAttribute("data-status")).toBe(status));
  return card;
}

async function reload(fake: FakeIntegration) {
  cleanup();
  renderChat(fake);
  const item = await screen.findByRole("button", { name: "Untitled thread" });
  await act(async () => {
    fireEvent.click(item);
  });
}

async function accepted(fake: FakeIntegration): Promise<HTMLElement> {
  renderChat(fake);
  await send(REVIEW);
  const challenge = await screen.findByTestId("acceptance-card");
  await waitFor(() => expect(challenge.getAttribute("data-state")).toBe("shown"));
  await act(async () => {
    fireEvent.click(within(challenge).getByRole("button", { name: "Accept O1 of add-slugify" }));
  });
  const recorded = await screen.findByTestId("acceptance-record-card");
  await waitFor(() => expect(recorded.getAttribute("data-state")).toBe("recorded"));
  return outcomeCard("running");
}

function stored(fake: FakeIntegration): Stored[] {
  return [...fake.threads.values()].flatMap((t) => t.messages);
}

function body(card: HTMLElement): string {
  return within(card).getByTestId("outcome-body").textContent ?? "";
}

describe("the outcome card in the chat (U-04.2)", () => {
  it("appears once an acceptance is recorded, and the thread keeps only the outcome id, never a copy of the projection", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    const card = await accepted(fake);
    expect(within(card).getByTestId("outcome-id").textContent).toBe(OUTCOME_ID);
    await waitFor(() => expect(stored(fake)).toHaveLength(4));
    const reply = stored(fake)[3].message;
    expect(stored(fake)[2].message.content).toEqual([{ type: "text", text: ACCEPT }]);
    expect(reply.content.map((p: any) => p.toolName)).toEqual([ACCEPTANCE_RECORD_TOOL, OUTCOME_TOOL]);
    expect(reply.content[1]).toMatchObject({ args: { outcome: OUTCOME_ID }, result: { outcome: OUTCOME_ID } });
    const kept = JSON.stringify(stored(fake));
    for (const projected of ["executionStatus", "lineageVerdict", "RESULT_VERIFIED", "coverage"]) {
      expect(kept.includes(projected), projected).toBe(false);
    }
    expect(fake.reads(`/outcomes/${OUTCOME_ID}`)).toHaveLength(1);
  });

  it("survives a reload: the same card from a fresh read of the projection, and nothing is written again", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    const before = body(await accepted(fake));
    await waitFor(() => expect(stored(fake)).toHaveLength(4));
    const writes = fake.writes().length;
    const reads = fake.reads(`/outcomes/${OUTCOME_ID}`).length;
    await reload(fake);
    const after = await outcomeCard("running");
    expect(body(after)).toBe(before);
    expect(fake.writes()).toHaveLength(writes);                                         // no capture, challenge or acceptance again
    expect(fake.reads(`/outcomes/${OUTCOME_ID}`)).toHaveLength(reads + 1);             // the card read the projection afresh
    expect(stored(fake)).toHaveLength(4);
    // a second reload is the same again
    await reload(fake);
    expect(body(await outcomeCard("running"))).toBe(before);
    expect(fake.writes()).toHaveLength(writes);
  });

  it("shows a projection that changed while the shell was closed as its new state", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    await accepted(fake);
    await waitFor(() => expect(stored(fake)).toHaveLength(4));
    const writes = fake.writes().length;
    fake.projection = answer("reconnect", 1);
    await reload(fake);
    const card = await outcomeCard("succeeded");
    const [attempt] = within(card).getAllByTestId("outcome-attempt");
    expect(attempt.getAttribute("data-code")).toBe("RESULT_PUBLISHED");
    expect(within(attempt).getAllByTestId("outcome-status-label")[0].textContent).toBe("Result published, verified at publication");
    expect(fake.writes()).toHaveLength(writes);
  });

  it("never marks Work complete: the card's only request is the projection's GET, whatever the attempt shows", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    fake.projection = answer("reconnect", 1);
    renderChat(fake);
    await send(REVIEW);
    const challenge = await screen.findByTestId("acceptance-card");
    await waitFor(() => expect(challenge.getAttribute("data-state")).toBe("shown"));
    await act(async () => {
      fireEvent.click(within(challenge).getByRole("button", { name: "Accept O1 of add-slugify" }));
    });
    const card = await outcomeCard("succeeded");
    await waitFor(() => expect(stored(fake)).toHaveLength(4));
    const routes = new Set(fake.seen.map((s) => `${s.method} ${s.path.replace(/\/messages\/[^/]+/, "/messages/<id>").replace(/\/threads\/[^/]+/, "/threads/<id>")}`));
    // the shell's own conversation writes and the acceptance, and otherwise only the projection's read
    const allowed = new Set([
      "GET /outcomes/" + OUTCOME_ID,
      "GET /threads",
      "GET /threads/<id>",
      "GET /threads/<id>/messages",
      "POST /threads",
      "POST /threads/<id>/messages",
      "POST /threads/<id>/messages/<id>",
      "POST /threads/<id>/messages/<id>/acceptance",
      "POST /threads/<id>/messages/<id>/acceptance-challenge",
    ]);
    expect([...routes].filter((r) => !allowed.has(r))).toEqual([]);
    expect(routes.has("GET /outcomes/" + OUTCOME_ID)).toBe(true);
    const afterCard = fake.seen.slice(fake.seen.findIndex((s) => s.path.startsWith("/outcomes/")));
    expect(afterCard.filter((s) => s.method !== "GET" && !/\/messages(\/[^/]+)?$/.test(s.path))).toEqual([]);
    expect(within(card).getByTestId("outcome-work").textContent).toContain("never sets or infers it");
  });
});
