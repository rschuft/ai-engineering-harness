import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StoredChat } from "./ChatArea";
import {
  ACCEPTANCE_RECORD_TOOL,
  ACCEPTANCE_TOOL,
  acceptanceMessage,
  cardNonce,
  formatAcceptance,
  formatReview,
  reviewRequest,
  sha256Hex,
} from "./chat-adapter";
import {
  ACCEPTANCE_CODES,
  INTEGRATION_ORIGIN,
  REFUSAL_TEXT,
  SESSION_HEADER,
  createIntegrationClient,
  type FetchLike,
} from "../identity/owner-session";

// The acceptance cards (plan leaf P-04.4) against a fake Integration process
// that keeps threads and messages in memory and answers the two acceptance
// routes as integrations/ownerhost/acceptance.py does: a challenge for a
// stored "Review acceptance" message (its sha256 compared), held by nonce with
// the card the request names; an acceptance of a stored "Accept" message on
// that nonce, once its card is stored. No model is connected; the setup's
// network guard refuses any real request.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";
const REVIEW = "Review acceptance: O1 of add-slugify";
// hashlib.sha256(REVIEW.encode('utf-8')).hexdigest(), computed by Python.
const REVIEW_SHA256 = "4ea640f0e4ce745f99b29329754634730a31e3cf1c5156250faacaaa87f9fcbf";
const WORDS = "  I accept it — as stated.\r\n";
const ACCEPT = "Accept O1 of add-slugify\nI accept it — as stated.";
// hashlib.sha256(ACCEPT.encode('utf-8')).hexdigest(), computed by Python.
const ACCEPT_SHA256 = "8e82fc30025ef2733b048729e506ca53c7a46d4a4a79ff6edc685e527f3e67ac";
const NONCE = "c1".repeat(16);
const SECOND_NONCE = "d2".repeat(16);
const COMMIT = "89abcdef0123456789abcdef0123456789abcdef";
const OUTCOME = "6a1f0c2e-3b4d-4e5f-8a9b-0c1d2e3f4a5b";
const SUMMARY = "Owner decision: accept an objective (accept-objective).\nObjective O1: Titles become URL slugs.";
const THREAD = "3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162";

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

type Seen = { method: string; path: string; body: any; status: number };

class FakeIntegration {
  messages: { parentId: string | null; message: any }[] = [];
  seen: Seen[] = [];
  cards = new Map<string, string>();       // nonce -> the card's message id
  refusal: { status: number; code: string; detail: string } | null = null;

  constructor(readonly credential: string) {}

  fetchImpl: FetchLike = async (url, init) => {
    expect(url.startsWith(INTEGRATION_ORIGIN + "/")).toBe(true);
    expect((init.headers as Record<string, string>)[SESSION_HEADER]).toBe(this.credential);
    const path = url.slice(INTEGRATION_ORIGIN.length);
    const method = init.method ?? "GET";
    const body = init.body === undefined ? undefined : JSON.parse(init.body as string);
    const [status, answer] = await this.route(method, path, body);
    this.seen.push({ method, path, body, status });
    return new Response(JSON.stringify(answer), { status });
  };

  calls(route: string): Seen[] {
    return this.seen.filter((s) => s.path.endsWith(`/${route}`));
  }

  stored(id: string) {
    return this.messages.find((s) => s.message.id === id);
  }

  private async route(method: string, path: string, body: any): Promise<[number, unknown]> {
    let m: RegExpMatchArray | null;
    if (path === "/threads" && method === "GET") return [200, { threads: [] }];
    if (path === "/threads" && method === "POST") return [200, { remoteId: THREAD }];
    if ((m = path.match(/^\/threads\/[^/]+\/messages\/([^/]+)\/capture$/))) {
      return [200, { change: "add-slugify", commit: COMMIT, created: true, receipt: `owner-ui/intent-capture/v1/x/${m[1]}` }];
    }
    if ((m = path.match(/^\/threads\/[^/]+\/messages\/([^/]+)\/acceptance-challenge$/))) {
      const stored = this.stored(decodeURIComponent(m[1]));
      if (!stored) return [404, { code: "MESSAGE_NOT_FOUND" }];
      if (this.refusal) return [this.refusal.status, { code: this.refusal.code, detail: this.refusal.detail }];
      if ((await sha256Hex(stored.message.content[0].text)) !== body.sha256) return [409, { code: "ACCEPTANCE_MESSAGE_MISMATCH" }];
      const nonce = this.cards.size === 0 ? NONCE : SECOND_NONCE;     // a challenge per review
      this.cards.set(nonce, body.card);
      return [200, { nonce, change: "add-slugify", item: "O1", revision: "0".repeat(40), proposal: "1".repeat(64),
                     summary: `${SUMMARY} (${nonce})`, expiresAt: "2026-11-17T13:00:00Z", card: body.card,
                     request: stored.message.id }];
    }
    if ((m = path.match(/^\/threads\/[^/]+\/messages\/([^/]+)\/acceptance$/))) {
      const stored = this.stored(decodeURIComponent(m[1]));
      if (!stored) return [404, { code: "MESSAGE_NOT_FOUND" }];
      if ((await sha256Hex(stored.message.content[0].text)) !== body.sha256) return [409, { code: "ACCEPTANCE_MESSAGE_MISMATCH" }];
      const card = this.cards.get(body.nonce);
      if (card === undefined) return [409, { code: "ACCEPTANCE_CHALLENGE_UNKNOWN", detail: "not held" }];
      if (!this.stored(card) || stored.parentId !== card) return [409, { code: "ACCEPTANCE_NOT_AFTER_CARD", detail: "x" }];
      return [200, { change: "add-slugify", item: "O1", outcome: OUTCOME, minted: true, commit: COMMIT, decision: "d",
                     reference: `outcome:${OUTCOME}@${COMMIT}`,
                     statement: `conversation:${THREAD}/${stored.message.id}#sha256:${body.sha256}`,
                     receipt: "r", created: true, state: "confirmed", project: "aieh-d1-demo" }];
    }
    if ((m = path.match(/^\/threads\/[^/]+\/messages$/)) && method === "POST") {
      this.messages.push({ parentId: body.parentId, message: body.message });
      return [200, { id: body.message.id, seq: this.messages.length, revision: 1, changed: true }];
    }
    if (path.match(/^\/threads\/[^/]+\/messages$/)) return [200, { messages: [] }];
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

describe("the acceptance cards (P-04.4)", () => {
  it("keeps the layouts the service parses, and Python's digests of them are the browser's", async () => {
    expect(formatReview("add-slugify", "O1")).toBe(REVIEW);
    expect(reviewRequest(REVIEW)).toEqual({ change: "add-slugify", item: "O1" });
    expect(reviewRequest(REVIEW + " ")).toBeNull();
    expect(formatAcceptance("add-slugify", "O1", WORDS)).toBe(ACCEPT);
    expect(formatAcceptance("add-slugify", "O1", "  ")).toBe("Accept O1 of add-slugify");
    expect(acceptanceMessage(ACCEPT)).toEqual({ change: "add-slugify", item: "O1" });
    expect(acceptanceMessage("Accept O1 of add-slugify\n")).toBeNull();
    expect(acceptanceMessage("I accept O1 of add-slugify")).toBeNull();
    expect(await sha256Hex(REVIEW)).toBe(REVIEW_SHA256);
    expect(await sha256Hex(ACCEPT)).toBe(ACCEPT_SHA256);
  });

  it("shows the challenge on the card it names, and records the acceptance the Accept form sends", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    await send(REVIEW);
    const card = await screen.findByTestId("acceptance-card");
    await waitFor(() => expect(card.getAttribute("data-state")).toBe("shown"));
    expect(within(card).getByTestId("acceptance-summary").textContent).toBe(`${SUMMARY} (${NONCE})`);
    // the challenge named the review message, its digest, and the card: the assistant message the run wrote
    const [challenge] = fake.calls("acceptance-challenge");
    const review = fake.messages[0].message;
    expect(review.content).toEqual([{ type: "text", text: REVIEW }]);
    expect(challenge.path).toBe(`/threads/${THREAD}/messages/${review.id}/acceptance-challenge`);
    await waitFor(() => expect(fake.messages).toHaveLength(2));
    const reply = fake.messages[1];
    expect(challenge.body).toEqual({ sha256: REVIEW_SHA256, card: reply.message.id });
    expect(reply.parentId).toBe(review.id);
    expect(reply.message.content[0].toolName).toBe(ACCEPTANCE_TOOL);
    expect(reply.message.content[0].result.nonce).toBe(NONCE);
    // the Accept form: the preview is exactly the text sent and stored as the Owner's own message
    await act(async () => {
      fireEvent.change(within(card).getByRole("textbox", { name: "Your own words" }), { target: { value: WORDS } });
    });
    expect(within(card).getByTestId("accept-preview").textContent).toBe(ACCEPT);
    await act(async () => {
      fireEvent.click(within(card).getByRole("button", { name: "Accept O1 of add-slugify" }));
    });
    const recorded = await screen.findByTestId("acceptance-record-card");
    await waitFor(() => expect(recorded.getAttribute("data-state")).toBe("recorded"));
    expect(within(recorded).getByTestId("acceptance-outcome").textContent).toBe(OUTCOME);
    expect(within(recorded).getByTestId("acceptance-commit").textContent).toBe(COMMIT);
    const acceptance = fake.messages[2];
    expect(acceptance.message.role).toBe("user");
    expect(acceptance.message.content).toEqual([{ type: "text", text: ACCEPT }]);
    expect(acceptance.parentId).toBe(reply.message.id);
    const [accept] = fake.calls("acceptance");
    expect(accept.path).toBe(`/threads/${THREAD}/messages/${acceptance.message.id}/acceptance`);
    expect(accept.body).toEqual({ nonce: NONCE, sha256: ACCEPT_SHA256 });
    await waitFor(() => expect(fake.messages).toHaveLength(4));
    expect(fake.messages[3].message.content[0].toolName).toBe(ACCEPTANCE_RECORD_TOOL);
  });

  it("asks for the review from the capture card, as the Owner's own review message", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    await send(["Change: add-slugify", "Objective: Titles become URL slugs.", "Acceptance criteria:", "- a criterion"].join("\n"));
    const captured = await screen.findByTestId("capture-card");
    await waitFor(() => expect(captured.getAttribute("data-state")).toBe("captured"));
    await act(async () => {
      fireEvent.click(within(captured).getByRole("button", { name: REVIEW }));
    });
    const card = await screen.findByTestId("acceptance-card");
    await waitFor(() => expect(card.getAttribute("data-state")).toBe("shown"));
    await waitFor(() => expect(fake.messages).toHaveLength(4));
    expect(fake.messages[2].message.role).toBe("user");
    expect(fake.messages[2].message.content).toEqual([{ type: "text", text: REVIEW }]);
    expect(fake.calls("acceptance-challenge")[0].body.sha256).toBe(REVIEW_SHA256);
  });

  it("accepts from an older card on that card's own challenge, under that card", async () => {
    // The review's probe: two cards for the same item; the FIRST card's Accept form must send the first nonce.
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    await send(REVIEW);
    await waitFor(() => expect(fake.messages).toHaveLength(2));
    await send(REVIEW);
    await waitFor(() => expect(screen.getAllByTestId("acceptance-card")).toHaveLength(2));
    await waitFor(() => expect(fake.messages).toHaveLength(4));
    const [first] = screen.getAllByTestId("acceptance-card");
    await waitFor(() => expect(first.getAttribute("data-state")).toBe("shown"));
    expect(within(first).getByTestId("acceptance-summary").textContent).toBe(`${SUMMARY} (${NONCE})`);
    await act(async () => {
      fireEvent.click(within(first).getByRole("button", { name: "Accept O1 of add-slugify" }));
    });
    await waitFor(() => expect(fake.calls("acceptance")).toHaveLength(1));
    const firstCard = fake.messages[1].message.id;
    const acceptance = fake.messages[4];
    expect(acceptance.message.role).toBe("user");
    expect(acceptance.parentId).toBe(firstCard);
    expect(fake.calls("acceptance")[0].body.nonce).toBe(NONCE);
    expect(fake.calls("acceptance")[0].status).toBe(200);
  });

  it("shows a refused challenge with its stable code and detail, and no Accept form", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    fake.refusal = { status: 404, code: "CHANGE_MISSING", detail: "openspec/changes/add-slugify has no proposal.md" };
    renderChat(fake);
    await send(REVIEW);
    const card = await screen.findByTestId("acceptance-card");
    await waitFor(() => expect(card.getAttribute("data-state")).toBe("refused"));
    expect(within(card).getByTestId("acceptance-code").textContent).toBe("CHANGE_MISSING");
    expect(card.textContent).toContain("has no proposal.md");
    expect(within(card).queryByTestId("accept-form")).toBeNull();
  });

  it("asks nothing for an acceptance with no card before it", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    await send("Accept O1 of add-slugify");
    const recorded = await screen.findByTestId("acceptance-record-card");
    await waitFor(() => expect(recorded.getAttribute("data-state")).toBe("refused"));
    expect(within(recorded).getByTestId("acceptance-record-code").textContent).toBe("ACCEPTANCE_NO_CARD");
    expect(fake.calls("acceptance")).toEqual([]);
  });

  it("finds the nearest card of the item before the acceptance, never a later or another item's", () => {
    const card = (id: string, item: string, nonce: string) => ({
      id, role: "assistant",
      content: [{ type: "tool-call", toolName: ACCEPTANCE_TOOL, result: { prepared: true, change: "add-slugify", item, nonce } }],
    });
    const user = (id: string) => ({ id, role: "user", content: [{ type: "text", text: "x" }] });
    expect(cardNonce([card("a", "O1", "n1"), user("u"), card("b", "O2", "n2"), user("v")], "add-slugify", "O1")).toBe("n1");
    expect(cardNonce([card("a", "O1", "n1"), card("b", "O1", "n2"), user("v")], "add-slugify", "O1")).toBe("n2");
    expect(cardNonce([user("v")], "add-slugify", "O1")).toBeNull();
  });

  it("has a text for every refusal code of the acceptance routes", () => {
    for (const code of [...ACCEPTANCE_CODES, "ACCEPTANCE_NO_CARD" as const]) {
      expect(REFUSAL_TEXT[code], code).toBeTruthy();
    }
  });
});
