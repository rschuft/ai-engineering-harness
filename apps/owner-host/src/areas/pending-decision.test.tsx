import { describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ChatModelAdapter, ChatModelRunOptions } from "@assistant-ui/react";
import { ACKNOWLEDGEMENT } from "./chat-adapter";
import { StoredChat } from "./ChatArea";
import { DECISION_TOOL, decisionArgs } from "./decision-tool";
import { INTEGRATION_ORIGIN, SESSION_HEADER, createIntegrationClient, type FetchLike } from "../identity/owner-session";
import wireText from "./fixtures/pending-decision.wire.json?raw";

// Plan leaf U-02.2: a pending decision survives closing and reopening the
// browser, once. The shell's real adapters and runtime run against a fake
// Integration process that keeps threads and messages in memory with the
// Owner conversation store's rules (the store mints the thread id and the
// seq; a message id is unique per thread; a user message is immutable; an
// assistant message's update is a new revision of the same id; nothing is
// deleted). Closing the browser is unmounting the whole chat (no runtime,
// adapter or client survives); reopening is a new mount with a new client.
// The setup's network guard refuses any real request.
//
// The requests the shell sends are compared with fixtures/pending-decision.
// wire.json (ids, times and the local thread id normalized): the Integration
// process's own test (integrations/ownerhost/tests/test_pending_decision.py)
// replays exactly those requests against a real Integration process that it
// stops and starts in between.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";
const QUESTION = { question: "Proceed with the change as stated?", options: ["Approve", "Revise"] };

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

type Stored = { seq: number; parentId: string | null; message: Record<string, any>; revision: number };
type Seen = { method: string; path: string; body: any; status: number };

class FakeIntegration {
  threads = new Map<string, { localId: string; messages: Stored[] }>();
  seen: Seen[] = [];
  private next = 0;

  constructor(readonly credential: string) {}

  fetchImpl: FetchLike = async (url, init) => {
    expect(url.startsWith(INTEGRATION_ORIGIN + "/")).toBe(true);
    const path = url.slice(INTEGRATION_ORIGIN.length);
    const header = (init.headers as Record<string, string>)[SESSION_HEADER];
    const body = init.body === undefined ? undefined : JSON.parse(init.body as string);
    const method = init.method ?? "GET";
    const [status, answer] = header === this.credential ? this.route(method, path, body) : [401, { code: "SESSION_CREDENTIAL_FOREIGN" }];
    this.seen.push({ method, path, body, status });
    return new Response(JSON.stringify(answer), { status });
  };

  posts(): Seen[] {
    return this.seen.filter((s) => s.method === "POST");
  }

  only(): { remoteId: string; messages: Stored[] } {
    const [[remoteId, thread]] = [...this.threads];
    return { remoteId, messages: thread.messages };
  }

  private route(method: string, path: string, body: any): [number, unknown] {
    let m: RegExpMatchArray | null;
    if (path === "/threads" && method === "GET") return [200, { threads: [...this.threads.keys()].map((remoteId) => ({ remoteId, status: "regular" })) }];
    if (path === "/threads" && method === "POST") {
      for (const [remoteId, t] of this.threads) if (t.localId === body.localId) return [200, { remoteId }];
      const remoteId = `0000000${++this.next}-7b4d-4e8a-9c0b-1d2e3f405162`.slice(-36);
      this.threads.set(remoteId, { localId: body.localId, messages: [] });
      return [200, { remoteId }];
    }
    if ((m = path.match(/^\/threads\/([^/]+)(\/.*)?$/))) {
      const thread = this.threads.get(decodeURIComponent(m[1]));
      if (!thread) return [404, { code: "THREAD_NOT_FOUND" }];
      const rest = m[2] ?? "";
      if (rest === "" && method === "GET") return [200, { remoteId: m[1], status: "regular" }];
      if (rest === "/messages" && method === "GET")
        return [200, { messages: thread.messages.map(({ seq, parentId, message }) => ({ seq, parentId, message })) }];
      if (rest === "/messages" || rest.startsWith("/messages/")) {
        const update = rest !== "/messages";
        const existing = thread.messages.find((s) => s.message.id === body.message.id);
        const same = existing && existing.parentId === body.parentId && JSON.stringify(existing.message) === JSON.stringify(body.message);
        const written = (s: Stored, changed: boolean) => [200, { id: s.message.id, seq: s.seq, revision: s.revision, changed }] as [number, unknown];
        if (existing && same) return written(existing, false);
        if (existing && existing.message.role === "user") return [409, { code: update ? "MESSAGE_IMMUTABLE" : "MESSAGE_ID_CONFLICT" }];
        if (existing && !update) return [409, { code: "MESSAGE_ID_CONFLICT" }];
        if (existing && existing.parentId !== body.parentId) return [409, { code: "MESSAGE_ID_CONFLICT" }];
        if (existing) {
          existing.message = body.message;
          existing.revision += 1;
          return written(existing, true);
        }
        if (update && body.message.role === "user") return [404, { code: "MESSAGE_NOT_FOUND" }];
        if (body.parentId !== null && !thread.messages.some((s) => s.message.id === body.parentId)) return [409, { code: "MESSAGE_PARENT_NOT_FOUND" }];
        const stored = { seq: thread.messages.length + 1, parentId: body.parentId, message: body.message, revision: 1 };
        thread.messages.push(stored);
        return written(stored, true);
      }
    }
    return [404, { code: "NOT_FOUND" }];
  }
}

/** A model adapter that asks the Owner one decision, then acknowledges once it is answered (no model). */
const decisionModel: ChatModelAdapter = {
  async run({ unstable_getMessage }: ChatModelRunOptions) {
    const answered = unstable_getMessage().content.some((part) => part.type === "tool-call" && part.result !== undefined);
    if (answered) return { content: [{ type: "text", text: ACKNOWLEDGEMENT }] };
    return {
      status: { type: "requires-action", reason: "tool-calls" },
      content: [{ type: "tool-call", toolCallId: "call-1", toolName: DECISION_TOOL, args: QUESTION, argsText: JSON.stringify(QUESTION) }],
    };
  },
};

/** Open the browser: a new client and a new mount of the stored chat over the same Integration process. */
function openBrowser(fake: FakeIntegration) {
  render(<StoredChat client={createIntegrationClient(fake.credential, fake.fetchImpl)} chatModel={decisionModel} />);
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

async function reopenThread(fake: FakeIntegration) {
  cleanup(); // the browser is closed: nothing of the shell's state survives
  openBrowser(fake);
  const item = await screen.findByRole("button", { name: "Untitled thread" });
  await act(async () => {
    fireEvent.click(item);
  });
}

function cards(): HTMLElement[] {
  return screen.queryAllByTestId("decision-card");
}

/** The requests that wrote, with ids, times, the thread id and the local id replaced by fixed values. */
function normalized(fake: FakeIntegration): unknown[] {
  const ids = new Map<string, string>();
  const counts = { user: 0, assistant: 0 };
  const idOf = (id: string, role: "user" | "assistant") => {
    if (!ids.has(id)) ids.set(id, `${role === "user" ? "U" : "A"}${String(++counts[role]).padStart(6, "0")}`);
    return ids.get(id)!;
  };
  const threads = new Map<string, string>();
  return fake.posts().map(({ path, body }) => {
    const m = path.match(/^\/threads\/([^/]+)(.*)$/);
    if (!m) return { method: "POST", path, body: { localId: "__LOCALID_fixture" } };
    if (!threads.has(m[1])) threads.set(m[1], "{thread}");
    const message = JSON.parse(JSON.stringify(body.message));
    message.id = idOf(message.id, message.role);
    message.createdAt = message.role === "user" ? "2026-11-16T12:00:00.000Z" : "2026-11-16T12:00:01.000Z";
    const parentId = body.parentId === null ? null : ids.get(body.parentId) ?? "unknown";
    const rest = m[2].replace(/^\/messages\/(.+)$/, (_all, id: string) => `/messages/${ids.get(decodeURIComponent(id))}`);
    return { method: "POST", path: `/threads/${threads.get(m[1])}${rest}`, body: { parentId, message } };
  });
}

describe("a pending decision across closing and reopening the browser", () => {
  it("comes back once, still pending, is answered as an update of the same message, and stays answered", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    openBrowser(fake);
    await send("Start the change.");
    await waitFor(() => expect(fake.posts().filter((p) => p.path.endsWith("/messages"))).toHaveLength(2));
    await waitFor(() => expect(cards()).toHaveLength(1));
    const [user, paused] = fake.only().messages;
    expect(user.message).toMatchObject({ role: "user", content: [{ type: "text", text: "Start the change." }] });
    expect(paused).toMatchObject({ seq: 2, parentId: user.message.id, revision: 1 });
    expect(paused.message.status).toEqual({ type: "requires-action", reason: "tool-calls" });
    expect(paused.message.content).toEqual([expect.objectContaining({ type: "tool-call", toolCallId: "call-1", toolName: DECISION_TOOL, args: QUESTION })]);
    expect(paused.message.content[0].result).toBeUndefined();
    expect(cards()[0].dataset.state).toBe("pending");

    // Close the browser and open it again: the thread and its pending call come back from the store alone, once.
    const beforeReload = fake.posts().length;
    await reopenThread(fake);
    await waitFor(() => expect(cards()).toHaveLength(1));
    const card = cards()[0];
    expect(card.dataset.state).toBe("pending");
    expect(card.dataset.toolCallId).toBe("call-1");
    expect(within(card).getByText(QUESTION.question)).toBeTruthy();
    expect(within(card).getAllByRole("button").map((b) => b.textContent)).toEqual(QUESTION.options);
    expect(screen.getAllByText("Start the change.")).toHaveLength(1);
    expect(screen.getByTestId("chat-thread").querySelectorAll(".owner-chat__message")).toHaveLength(2);
    expect(fake.posts().length).toBe(beforeReload); // reopening writes nothing
    expect(fake.only().messages.map((s) => s.message.id)).toEqual([user.message.id, paused.message.id]);

    // Answer it after the reopen: the run resumes and its completion is an update of the paused message's id.
    await act(async () => {
      fireEvent.click(within(card).getByRole("button", { name: "Approve" }));
    });
    await waitFor(() => expect(fake.only().messages[1].message.status).toMatchObject({ type: "complete" }));
    const writes = fake.posts().slice(beforeReload);
    expect(writes.length).toBeGreaterThan(0);
    for (const write of writes) {
      expect(write.path).toBe(`/threads/${fake.only().remoteId}/messages/${paused.message.id}`);
      expect(write.status).toBe(200);
    }
    const done = fake.only().messages;
    expect(done.map((s) => [s.seq, s.message.id])).toEqual([[1, user.message.id], [2, paused.message.id]]);
    expect(done[1].revision).toBeGreaterThan(1);
    expect(done[1].message.content).toEqual([
      expect.objectContaining({ type: "tool-call", toolCallId: "call-1", result: { choice: "Approve" } }),
      { type: "text", text: ACKNOWLEDGEMENT },
    ]);
    await waitFor(() => expect(cards()[0].dataset.state).toBe("answered"));

    // Reopen once more: answered, once, and nothing is written again.
    const beforeSecond = fake.posts().length;
    await reopenThread(fake);
    await waitFor(() => expect(cards()).toHaveLength(1));
    expect(cards()[0].dataset.state).toBe("answered");
    expect(within(cards()[0]).getByText("Answered: Approve")).toBeTruthy();
    expect(within(cards()[0]).queryAllByRole("button")).toEqual([]);
    expect(screen.getAllByText(ACKNOWLEDGEMENT)).toHaveLength(1);
    expect(fake.posts().length).toBe(beforeSecond);

    // What the shell sent is what the Integration process's restart test replays.
    expect(normalized(fake)).toEqual(JSON.parse(wireText).requests);
  });

  it("a decision request whose arguments are not a question and options cannot be answered", () => {
    expect(decisionArgs(QUESTION)).toEqual(QUESTION);
    for (const bad of [null, [], {}, { question: "", options: ["A"] }, { question: "Q", options: [] }, { question: "Q", options: ["A", "A"] }, { question: "Q", options: [1] }]) {
      expect(decisionArgs(bad)).toBeNull();
    }
  });
});
