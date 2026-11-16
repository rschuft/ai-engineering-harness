import { describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { OwnerApp } from "../App";
import { ownerRoutes } from "../routes";
import { ACKNOWLEDGEMENT } from "./chat-adapter";
import { StoredChat } from "./ChatArea";
import { createHistoryAdapter, createThreadListAdapter } from "./conversation-adapters";
import {
  CREDENTIAL_STORAGE_KEY,
  INTEGRATION_ORIGIN,
  SESSION_HEADER,
  SessionRefusal,
  createIntegrationClient,
  type FetchLike,
} from "../identity/owner-session";

// The stored, model-free chat (plan leaf U-02.1) against a fake Integration
// process that keeps threads and messages in memory with the store's rules
// (the store mints the thread id and the seq; a message id is unique per
// thread; a parent must already be stored; a user message is immutable;
// nothing is deleted). The setup's network guard refuses any real request.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";
const SESSION = { sessionId: "3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162", issuedAt: "2026-11-16T12:00:00Z", expiresAt: "2026-11-17T00:00:00Z" };

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

type Stored = { seq: number; parentId: string | null; message: Record<string, unknown> };
type Seen = { method: string; path: string; body: unknown; header: string | undefined; phase: "start" | "end"; status?: number };

class FakeIntegration {
  threads = new Map<string, { localId: string; messages: Stored[]; status: "regular" | "archived" }>();
  seen: Seen[] = [];
  /** Delays the answer to a request (method, path) by a promise, to show the order of writes. */
  hold: ((method: string, path: string, body: unknown) => Promise<void> | undefined) | null = null;
  private next = 0;

  constructor(readonly credential: string) {}

  fetchImpl: FetchLike = async (url, init) => {
    expect(url.startsWith(INTEGRATION_ORIGIN + "/")).toBe(true);
    const path = url.slice(INTEGRATION_ORIGIN.length);
    const header = (init.headers as Record<string, string>)[SESSION_HEADER];
    const body = init.body === undefined ? undefined : JSON.parse(init.body as string);
    const method = init.method ?? "GET";
    this.seen.push({ method, path, body, header, phase: "start" });
    await this.hold?.(method, path, body);
    const [status, answer] = header === this.credential ? this.route(method, path, body) : [401, { code: "SESSION_CREDENTIAL_FOREIGN" }];
    this.seen.push({ method, path, body, header, phase: "end", status });
    return new Response(JSON.stringify(answer), { status });
  };

  writes(): Seen[] {
    return this.seen.filter((s) => s.phase === "end" && s.method === "POST" && /\/messages/.test(s.path));
  }

  private route(method: string, path: string, body: any): [number, unknown] {
    let m: RegExpMatchArray | null;
    if (path === "/session" && method === "POST") return [200, SESSION];
    if (path === "/threads" && method === "GET")
      return [200, { threads: [...this.threads].map(([remoteId, t]) => ({ remoteId, status: t.status })) }];
    if (path === "/threads" && method === "POST") {
      for (const [remoteId, t] of this.threads) if (t.localId === body.localId) return [200, { remoteId }];
      const remoteId = `0000000${++this.next}-7b4d-4e8a-9c0b-1d2e3f405162`.slice(-36);
      this.threads.set(remoteId, { localId: body.localId, messages: [], status: "regular" });
      return [200, { remoteId }];
    }
    if ((m = path.match(/^\/threads\/([^/]+)(\/.*)?$/))) {
      const thread = this.threads.get(decodeURIComponent(m[1]));
      if (!thread) return [404, { code: "THREAD_NOT_FOUND" }];
      const rest = m[2] ?? "";
      if (rest === "" && method === "GET") return [200, { remoteId: m[1], status: thread.status }];
      if (rest === "/delete") return [409, { code: "THREAD_DELETE_REFUSED" }];
      if (rest === "/messages" && method === "GET") return [200, { messages: thread.messages }];
      if (rest === "/messages" || rest.startsWith("/messages/")) {
        const existing = thread.messages.find((s) => s.message.id === body.message.id);
        const same = existing && JSON.stringify(existing.message) === JSON.stringify(body.message) && existing.parentId === body.parentId;
        if (existing && same) return [200, { id: body.message.id, seq: existing.seq, revision: 1, changed: false }];
        if (existing && existing.message.role === "user") return [409, { code: rest === "/messages" ? "MESSAGE_ID_CONFLICT" : "MESSAGE_IMMUTABLE" }];
        if (existing && rest === "/messages") return [409, { code: "MESSAGE_ID_CONFLICT" }];
        if (body.parentId !== null && !thread.messages.some((s) => s.message.id === body.parentId))
          return [409, { code: "MESSAGE_PARENT_NOT_FOUND" }];
        if (existing) {
          existing.message = body.message;
          return [200, { id: body.message.id, seq: existing.seq, revision: 2, changed: true }];
        }
        const stored = { seq: thread.messages.length + 1, parentId: body.parentId, message: body.message };
        thread.messages.push(stored);
        return [200, { id: body.message.id, seq: stored.seq, revision: 1, changed: true }];
      }
    }
    return [404, { code: "NOT_FOUND" }];
  }
}

function renderChat(fake: FakeIntegration) {
  const client = createIntegrationClient(fake.credential, fake.fetchImpl);
  render(<StoredChat client={client} />);
}

async function send(text: string) {
  const thread = await screen.findByTestId("chat-thread");
  const input = within(thread).getByRole("textbox", { name: "Message" });
  await act(async () => {
    fireEvent.change(input, { target: { value: text } });
  });
  await act(async () => {
    fireEvent.click(within(thread).getByRole("button", { name: "Send" }));
  });
}

function shownMessages(): string[] {
  return Array.from(screen.getByTestId("chat-thread").querySelectorAll(".owner-chat__message")).map((el) => {
    const copy = el.cloneNode(true) as HTMLElement;
    copy.querySelectorAll(".owner-chat__actions, .owner-chat__branches").forEach((control) => control.remove());
    return copy.textContent ?? "";
  });
}

describe("the stored, model-free chat", () => {
  it("stores the Owner's message and the fixed acknowledgement through the Integration process, in order", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    await send("Persist this statement \u2014 caf\u0065\u0301 \u4e2d\u6587.");
    await waitFor(() => expect(fake.writes()).toHaveLength(2));
    const [remoteId] = [...fake.threads.keys()];
    const [user, reply] = fake.threads.get(remoteId)!.messages;
    expect(fake.threads.get(remoteId)!.localId).toMatch(/^__LOCALID_[0-9a-z]+$/);
    expect(user).toMatchObject({ seq: 1, parentId: null, message: { role: "user", attachments: [], metadata: { custom: {} } } });
    expect(user.message.content).toEqual([{ type: "text", text: "Persist this statement \u2014 caf\u0065\u0301 \u4e2d\u6587." }]);
    expect(user.message.id).toMatch(/^[0-9A-Za-z]{7}$/);
    expect(user.message.createdAt).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
    expect(reply).toMatchObject({ seq: 2, parentId: user.message.id, message: { role: "assistant", status: { type: "complete" } } });
    expect(reply.message.content).toEqual([{ type: "text", text: ACKNOWLEDGEMENT }]);
    expect(fake.seen.every((s) => s.header === fake.credential)).toBe(true);
    await waitFor(() => expect(shownMessages()).toEqual([user.message.content && "Persist this statement \u2014 caf\u0065\u0301 \u4e2d\u6587.", ACKNOWLEDGEMENT]));
  });

  it("sends one thread's writes in call order: the reply waits for the statement to be stored", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    let release!: () => void;
    const released = new Promise<void>((resolve) => (release = resolve));
    fake.hold = (method, path, body: any) =>
      method === "POST" && path.endsWith("/messages") && body?.message?.role === "user" ? released : undefined;
    renderChat(fake);
    await send("Slow to store.");
    await waitFor(() => expect(fake.seen.some((s) => s.phase === "start" && s.body && (s.body as any).message?.role === "user")).toBe(true));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 50)));
    // The acknowledgement is ready, but its append has not been sent while the statement's is in flight.
    expect(fake.seen.filter((s) => s.phase === "start" && (s.body as any)?.message?.role === "assistant")).toEqual([]);
    release();
    await waitFor(() => expect(fake.writes().map((w) => w.status)).toEqual([200, 200]));
    const [remoteId] = [...fake.threads.keys()];
    expect(fake.threads.get(remoteId)!.messages.map((s) => s.message.role)).toEqual(["user", "assistant"]);
  });

  it("a reload returns the exact messages in order without duplicate ids, edits included", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    renderChat(fake);
    await send("First statement.");
    await waitFor(() => expect(fake.writes()).toHaveLength(2));
    await act(async () => {
      fireEvent.click(within(screen.getByTestId("chat-thread")).getByRole("button", { name: "Edit" }));
    });
    const edit = await screen.findByRole("textbox", { name: "Edit message" });
    await act(async () => {
      fireEvent.change(edit, { target: { value: "First statement, edited." } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
    });
    await waitFor(() => expect(fake.writes()).toHaveLength(4));
    const [remoteId] = [...fake.threads.keys()];
    const stored = fake.threads.get(remoteId)!.messages;
    // The edit is a new message under the same parent: both statements are kept.
    expect(stored.map((s) => [s.seq, s.message.role, s.parentId])).toEqual([
      [1, "user", null],
      [2, "assistant", stored[0].message.id],
      [3, "user", null],
      [4, "assistant", stored[2].message.id],
    ]);
    await waitFor(() => expect(shownMessages()).toEqual(["First statement, edited.", ACKNOWLEDGEMENT]));

    // Reload: a new mount, the thread chosen from the list, its messages read back from the store.
    cleanup();
    const before = fake.seen.length;
    renderChat(fake);
    const item = await screen.findByRole("button", { name: "Untitled thread" });
    await act(async () => {
      fireEvent.click(item);
    });
    await waitFor(() => expect(shownMessages()).toEqual(["First statement, edited.", ACKNOWLEDGEMENT]));
    const reads = fake.seen.slice(before).filter((s) => s.phase === "end");
    expect(reads.map((s) => `${s.method} ${s.path}`)).toEqual(
      expect.arrayContaining(["GET /threads", `GET /threads/${remoteId}/messages`]),
    );
    expect(reads.filter((s) => s.method === "POST")).toEqual([]); // a reload writes nothing
    // The newest branch is shown (no headId: the last message is the head); the first statement is one step back.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Previous version" }));
    });
    await waitFor(() => expect(shownMessages()).toEqual(["First statement.", ACKNOWLEDGEMENT]));
    const ids = stored.map((s) => s.message.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("the adapters", () => {
  const thread = (remoteId: string | undefined) => ({
    getState: () => ({ remoteId }),
    initialize: async () => ({ remoteId: remoteId! }),
  });

  it("load answers the stored items with createdAt as a Date and without the store's seq", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    const client = createIntegrationClient(fake.credential, fake.fetchImpl);
    const remoteId = await createThreadListAdapter(client).initialize("__LOCALID_abc");
    const user = { id: "U000001", role: "user", createdAt: new Date("2026-11-16T12:00:00.123Z"), content: [{ type: "text", text: "Hi." }], attachments: [], metadata: { custom: {} } };
    const history = createHistoryAdapter(client, () => thread(remoteId.remoteId));
    await history.append({ parentId: null, message: user as never });
    const loaded = await history.load();
    expect(loaded).toEqual({ messages: [{ parentId: null, message: user }] });
    expect(loaded.messages[0].message.createdAt).toBeInstanceOf(Date);
    expect(await createHistoryAdapter(client, () => thread(undefined)).load()).toEqual({ messages: [] });
  });

  it("an update goes to the message's route; a refusal keeps the store's stable code", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    const client = createIntegrationClient(fake.credential, fake.fetchImpl);
    const { remoteId } = await createThreadListAdapter(client).initialize("__LOCALID_abc");
    const history = createHistoryAdapter(client, () => thread(remoteId));
    const user = { id: "U000001", role: "user", createdAt: new Date("2026-11-16T12:00:00.123Z"), content: [{ type: "text", text: "Hi." }], attachments: [], metadata: { custom: {} } };
    await history.append({ parentId: null, message: user as never });
    const assistant = { id: "A000001", role: "assistant", status: { type: "requires-action", reason: "tool-calls" }, content: [], metadata: { custom: {} } };
    await history.update!({ parentId: "U000001", message: assistant as never });
    expect(fake.seen.at(-1)).toMatchObject({ method: "POST", path: `/threads/${remoteId}/messages/A000001`, status: 200 });
    const changed = { ...user, content: [{ type: "text", text: "Changed." }] };
    await expect(history.update!({ parentId: null, message: changed as never })).rejects.toMatchObject({ code: "MESSAGE_IMMUTABLE" });
    await expect(history.append({ parentId: null, message: changed as never })).rejects.toMatchObject({ code: "MESSAGE_ID_CONFLICT" });
  });

  it("a thread delete is refused with THREAD_DELETE_REFUSED, and a title stream closes at once with no model", async () => {
    const fake = new FakeIntegration(throwawayCredential());
    const adapter = createThreadListAdapter(createIntegrationClient(fake.credential, fake.fetchImpl));
    const { remoteId } = await adapter.initialize("__LOCALID_abc");
    expect(await adapter.initialize("__LOCALID_abc")).toEqual({ remoteId });
    const refusal = await adapter.delete(remoteId).catch((error: unknown) => error);
    expect(refusal).toBeInstanceOf(SessionRefusal);
    expect((refusal as SessionRefusal).code).toBe("THREAD_DELETE_REFUSED");
    expect(await adapter.list()).toEqual({ threads: [{ remoteId, status: "regular" }] });
    const stream = await adapter.generateTitle(remoteId, []);
    expect(await stream.getReader().read()).toEqual({ done: true, value: undefined });
  });
});

describe("in the app", () => {
  it("a signed-in Owner gets the stored chat; signed out, the chat stays unconnected", async () => {
    const credential = throwawayCredential();
    const fake = new FakeIntegration(credential);
    window.localStorage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify({ v: 1, credential, ...SESSION }));
    render(<OwnerApp router={createMemoryRouter(ownerRoutes, { initialEntries: ["/chat"] })} fetchImpl={fake.fetchImpl} />);
    expect(await screen.findByTestId("chat-stored")).toBeTruthy();
    const input = within(screen.getByTestId("chat-thread")).getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
    expect(input.disabled).toBe(false);
    await waitFor(() => expect(fake.seen.some((s) => s.path === "/threads" && s.method === "GET")).toBe(true));
    cleanup();
    window.localStorage.clear();
    render(<OwnerApp router={createMemoryRouter(ownerRoutes, { initialEntries: ["/chat"] })} fetchImpl={fake.fetchImpl} />);
    expect(await screen.findByTestId("chat-empty")).toBeTruthy();
    expect(screen.queryByTestId("chat-stored")).toBeNull();
  });
});
