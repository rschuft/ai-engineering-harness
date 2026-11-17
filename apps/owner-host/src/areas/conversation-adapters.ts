import { useEffect, useMemo, useRef } from "react";
import {
  useAui,
  type ExportedMessageRepositoryItem,
  type RemoteThreadListAdapter,
  type ThreadHistoryAdapter,
  type ThreadMessage,
} from "@assistant-ui/react";
import { SessionRefusal, type IntegrationClient } from "../identity/owner-session";

// The Owner chat's two assistant-ui adapters over the Integration process
// (plan leaf U-02.1; decision 0025, point 6): a RemoteThreadListAdapter for
// the threads and, per thread through its unstable_useAdapters hook, a
// ThreadHistoryAdapter for the messages. Both are thin: the Owner
// conversation store on the host assigns the thread id, keeps the message ids
// assistant-ui gives, orders the messages and keeps every byte of an Owner
// statement. Every request goes through the signed-in session's client, so it
// carries the Owner UI session header and reaches 127.0.0.1:13310 only.
//
// What the pinned runtime does (gate G2, g2-runtime-gate.test.tsx) and what
// that asks of these adapters:
// - initialize receives the local thread id (__LOCALID_...); the store mints
//   the thread id and answers it as remoteId;
// - history.append is called with each message under its native id; the
//   runtime does not serialize writes of different ids, so the adapter sends
//   one thread's writes one after another, in call order (a reply never
//   reaches the store before the statement it answers);
// - load answers every message in the store's order with no headId: the head
//   is the last message, so an edit shows its newest branch after a reload;
// - update is an upsert for assistant messages (a run paused for a tool, then
//   completed); a user message is never updated;
// - generateTitle: no model titles a thread, so the stream closes at once.

type ThreadListItemHandle = {
  getState(): { remoteId?: string | undefined };
  initialize(): Promise<{ remoteId: string }>;
};

const MESSAGE_ID = /^[0-9A-Za-z]{7}$/;

function threadPath(remoteId: string, rest = ""): string {
  return `/threads/${encodeURIComponent(remoteId)}${rest}`;
}

function invalid(): never {
  throw new SessionRefusal("ANSWER_INVALID");
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** One loaded item as the runtime takes it: the store's seq dropped, createdAt a Date again. */
function revive(raw: unknown): ExportedMessageRepositoryItem {
  if (!isObject(raw) || !isObject(raw.message)) invalid();
  const { parentId, message } = raw;
  if (parentId !== null && (typeof parentId !== "string" || !MESSAGE_ID.test(parentId))) invalid();
  if (typeof message.id !== "string" || !MESSAGE_ID.test(message.id)) invalid();
  if (message.role !== "user" && message.role !== "assistant") invalid();
  const createdAt = typeof message.createdAt === "string" ? new Date(message.createdAt) : undefined;
  if (createdAt !== undefined && Number.isNaN(createdAt.getTime())) invalid();
  return {
    parentId,
    message: { ...message, ...(createdAt ? { createdAt } : {}) } as unknown as ThreadMessage,
  };
}

/** What the store keeps of an item: the item as JSON (a Date becomes its ISO text). */
function wire(item: ExportedMessageRepositoryItem): unknown {
  return JSON.parse(JSON.stringify({ parentId: item.parentId, message: item.message }));
}

/**
 * The appends each client has sent, by message id (plan leaf P-01.3): the
 * capture is asked only once its message is stored (messageStored), since
 * the service compares the digest with the stored bytes. Message ids are the
 * runtime's own; a message loaded from the store is stored already.
 */
const appends = new WeakMap<IntegrationClient, Map<string, Promise<void>>>();

/** Resolves once the history adapter has stored message ID (at once when it was never appended here). */
export function messageStored(client: IntegrationClient, id: string): Promise<void> {
  return appends.get(client)?.get(id) ?? Promise.resolve();
}

/**
 * The history of the thread the runtime is on. THREAD resolves the thread
 * list item at each call, never once at mount (the runtime's contract).
 */
export function createHistoryAdapter(client: IntegrationClient, thread: () => ThreadListItemHandle): ThreadHistoryAdapter {
  let tail: Promise<unknown> = Promise.resolve();
  const inOrder = (write: () => Promise<void>): Promise<void> => {
    const next = tail.then(write, write);
    tail = next.catch(() => undefined);
    return next;
  };
  return {
    async load() {
      const remoteId = thread().getState().remoteId;
      if (!remoteId) return { messages: [] };
      const answer = await client.request("GET", threadPath(remoteId, "/messages"));
      if (!isObject(answer) || !Array.isArray(answer.messages)) invalid();
      return { messages: answer.messages.map(revive) };
    },
    append(item) {
      const write = inOrder(async () => {
        const { remoteId } = await thread().initialize();
        await client.request("POST", threadPath(remoteId, "/messages"), wire(item));
      });
      let sent = appends.get(client);
      if (!sent) appends.set(client, (sent = new Map()));
      sent.set(item.message.id, write);
      return write;
    },
    update(item) {
      return inOrder(async () => {
        const { remoteId } = await thread().initialize();
        await client.request("POST", threadPath(remoteId, `/messages/${encodeURIComponent(item.message.id)}`), wire(item));
      });
    },
  };
}

type TitleStream = Awaited<ReturnType<RemoteThreadListAdapter["generateTitle"]>>;

function metadata(raw: unknown) {
  if (!isObject(raw) || typeof raw.remoteId !== "string") invalid();
  if (raw.status !== "regular" && raw.status !== "archived") invalid();
  if (raw.title !== undefined && typeof raw.title !== "string") invalid();
  return {
    remoteId: raw.remoteId,
    status: raw.status,
    ...(typeof raw.title === "string" ? { title: raw.title } : {}),
  } as const;
}

/** The thread list of the Owner conversation store, for useRemoteThreadListRuntime. */
export function createThreadListAdapter(client: IntegrationClient): RemoteThreadListAdapter {
  return {
    async list() {
      const answer = await client.request("GET", "/threads");
      if (!isObject(answer) || !Array.isArray(answer.threads)) invalid();
      return { threads: answer.threads.map(metadata) };
    },
    async initialize(localId) {
      const answer = await client.request("POST", "/threads", { localId });
      if (!isObject(answer) || typeof answer.remoteId !== "string") invalid();
      return { remoteId: answer.remoteId };
    },
    async fetch(remoteId) {
      return metadata(await client.request("GET", threadPath(remoteId)));
    },
    async rename(remoteId, title) {
      await client.request("POST", threadPath(remoteId, "/title"), { title });
    },
    async archive(remoteId) {
      await client.request("POST", threadPath(remoteId, "/archive"));
    },
    async unarchive(remoteId) {
      await client.request("POST", threadPath(remoteId, "/unarchive"));
    },
    async delete(remoteId) {
      // The store deletes nothing: the Integration process answers THREAD_DELETE_REFUSED, thrown here.
      await client.request("POST", threadPath(remoteId, "/delete"));
    },
    async generateTitle() {
      // No model titles a thread: a stream that closes at once leaves the title unset (gate G2).
      return new ReadableStream({
        start(controller) {
          controller.close();
        },
      }) as TitleStream;
    },
    unstable_useAdapters: function useOwnerHistory() {
      const aui = useAui();
      const current = useRef(aui);
      useEffect(() => {
        current.current = aui;
      });
      return useMemo(() => ({ history: createHistoryAdapter(client, () => current.current.threadListItem()) }), []);
    },
  };
}
