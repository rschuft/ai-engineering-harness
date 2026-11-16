import { describe, expect, it } from "vitest";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type AssistantRuntime,
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ExportedMessageRepositoryItem,
  type RemoteThreadListAdapter,
  type ThreadHistoryAdapter,
  type ThreadMessage,
} from "@assistant-ui/react";
import { useMemo, useRef } from "react";

// Gate G2 of the I1 work design (slice 4, U-02.1): the pinned assistant-ui
// (@assistant-ui/react 0.15.32, @assistant-ui/core 0.3.32) observed in jsdom,
// with no network (the setup's guard refuses every request). The backend here
// is an in-memory stand-in recording every adapter call, so each finding is
// the runtime's own behaviour, not the shell's adapters'.

type Call =
  | { op: "initialize"; localId: string }
  | { op: "load"; remoteId: string | undefined }
  | { op: "append" | "update"; remoteId: string; id: string; role: string; parentId: string | null; status: string }
  | { op: "generateTitle"; remoteId: string; messages: number }
  | { op: "run"; lastId: string | undefined; lastRole: string | undefined }
  | { op: "called"; id: string; role: string };
type Write = Extract<Call, { op: "append" | "update" }>;

class Backend {
  calls: Call[] = [];
  threads = new Map<string, { localId: string; items: ExportedMessageRepositoryItem[] }>();
  private next = 0;
  /** What load() returns for a thread: by default its items without a headId. */
  loadShape: (items: ExportedMessageRepositoryItem[]) => { headId?: string | null; messages: ExportedMessageRepositoryItem[] } = (
    items,
  ) => ({ messages: items.map((item) => JSON.parse(JSON.stringify(item))) });

  record(op: "append" | "update", remoteId: string, item: ExportedMessageRepositoryItem) {
    this.calls.push({
      op,
      remoteId,
      id: item.message.id,
      role: item.message.role,
      parentId: item.parentId,
      status: item.message.role === "assistant" ? item.message.status.type : "-",
    });
    const thread = this.threads.get(remoteId)!;
    const copy = JSON.parse(JSON.stringify(item)) as ExportedMessageRepositoryItem;
    const index = thread.items.findIndex((stored) => stored.message.id === item.message.id);
    if (index >= 0) thread.items[index] = copy;
    else thread.items.push(copy);
  }

  adapter(): RemoteThreadListAdapter {
    const backend = this;
    return {
      async list() {
        return {
          threads: [...backend.threads.keys()].map((remoteId) => ({ remoteId, status: "regular" as const })),
        };
      },
      async initialize(localId) {
        backend.calls.push({ op: "initialize", localId });
        for (const [remoteId, thread] of backend.threads) if (thread.localId === localId) return { remoteId };
        const remoteId = `thread-${++backend.next}`;
        backend.threads.set(remoteId, { localId, items: [] });
        return { remoteId };
      },
      async rename() {},
      async archive() {},
      async unarchive() {},
      async delete() {
        throw new Error("THREAD_DELETE_REFUSED");
      },
      async fetch(remoteId) {
        return { remoteId, status: "regular" };
      },
      async generateTitle(remoteId, messages) {
        backend.calls.push({ op: "generateTitle", remoteId, messages: messages.length });
        // What the pinned InMemoryThreadListAdapter returns: a stream that closes at once, with no title.
        return new ReadableStream({
          start(controller) {
            controller.close();
          },
        }) as Awaited<ReturnType<RemoteThreadListAdapter["generateTitle"]>>;
      },
      unstable_useAdapters: function useBackendAdapters() {
        const aui = useAui();
        const ref = useRef(aui);
        ref.current = aui;
        return useMemo(() => {
          const history: ThreadHistoryAdapter = {
            async load() {
              const remoteId = ref.current.threadListItem().getState().remoteId;
              backend.calls.push({ op: "load", remoteId });
              if (!remoteId) return { messages: [] };
              return backend.loadShape(backend.threads.get(remoteId)?.items ?? []);
            },
            async append(item) {
              backend.calls.push({ op: "called", id: item.message.id, role: item.message.role });
              const { remoteId } = await ref.current.threadListItem().initialize();
              backend.record("append", remoteId, item);
            },
            async update(item) {
              const { remoteId } = await ref.current.threadListItem().initialize();
              backend.record("update", remoteId, item);
            },
          };
          return { history };
        }, []);
      },
    };
  }
}

const ACK = "Recorded.";

function ackModel(backend: Backend): ChatModelAdapter {
  return {
    async run({ messages }: ChatModelRunOptions) {
      const last = messages.at(-1);
      backend.calls.push({ op: "run", lastId: last?.id, lastRole: last?.role });
      return { content: [{ type: "text", text: ACK }] };
    },
  };
}

/** A model whose first answer asks the Owner through the human tool ask_owner; once answered, it acknowledges. */
function humanToolModel(backend: Backend): ChatModelAdapter {
  return {
    async run({ messages, unstable_getMessage }: ChatModelRunOptions) {
      const last = messages.at(-1);
      backend.calls.push({ op: "run", lastId: last?.id, lastRole: last?.role });
      // The model sees the thread up to the parent; the message it continues carries the tool result.
      const answered = unstable_getMessage().content.some((part) => part.type === "tool-call" && part.result !== undefined);
      if (answered) return { content: [{ type: "text", text: "Answer recorded." }] };
      // A model adapter states the pause itself: the runtime marks a settled run "complete" otherwise.
      return {
        status: { type: "requires-action", reason: "tool-calls" },
        content: [
          { type: "tool-call", toolCallId: "call-1", toolName: "ask_owner", args: { question: "Proceed?" }, argsText: '{"question":"Proceed?"}' },
        ],
      };
    },
  };
}

function UserMessage() {
  return (
    <MessagePrimitive.Root data-role="user">
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}
function AssistantMessage() {
  return (
    <MessagePrimitive.Root data-role="assistant">
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function mount(adapter: RemoteThreadListAdapter, model: ChatModelAdapter, humanToolNames?: string[]) {
  const holder: { runtime?: AssistantRuntime } = {};
  function Harness() {
    const runtime = useRemoteThreadListRuntime({
      runtimeHook: function useThreadRuntime() {
        return useLocalRuntime(model, { unstable_humanToolNames: humanToolNames });
      },
      adapter,
    });
    holder.runtime = runtime;
    return (
      <AssistantRuntimeProvider runtime={runtime}>
        <ThreadPrimitive.Root>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </ThreadPrimitive.Root>
      </AssistantRuntimeProvider>
    );
  }
  render(<Harness />);
  return () => holder.runtime!;
}

function messagesOf(runtime: AssistantRuntime): ThreadMessage[] {
  return [...runtime.thread.getState().messages];
}

async function reloadInto(backend: Backend, remoteId: string, model: ChatModelAdapter, humanToolNames?: string[]) {
  cleanup();
  const runtime = mount(backend.adapter(), model, humanToolNames);
  await act(async () => {
    await runtime().threads.getLoadThreadsPromise();
  });
  await act(async () => {
    await runtime().threads.switchToThread(remoteId);
  });
  return runtime;
}

describe("gate G2: the pinned assistant-ui runtime with a history adapter", () => {
  it("appends the user message, with its id, to history before the model adapter runs, after initialize", async () => {
    const backend = new Backend();
    const runtime = mount(backend.adapter(), ackModel(backend));
    await act(async () => {
      runtime().thread.append({ role: "user", content: [{ type: "text", text: "First statement." }] });
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(2));
    const ops = backend.calls.map((c) => c.op);
    expect(ops.indexOf("initialize")).toBeLessThan(ops.indexOf("append"));
    const userAppend = backend.calls.find((c) => c.op === "append" && c.role === "user") as Write;
    const run = backend.calls.find((c) => c.op === "run") as Extract<Call, { op: "run" }>;
    const called = backend.calls.find((c) => c.op === "called" && c.role === "user") as Extract<Call, { op: "called" }>;
    // history.append is called with the user message before the model adapter runs; the run does not wait for the
    // write to land (here the write awaits initialize, so the run is recorded first).
    expect(called.id).toBe(userAppend.id);
    expect(backend.calls.indexOf(called)).toBeLessThan(backend.calls.indexOf(run));
    expect(backend.calls.indexOf(run)).toBeLessThan(backend.calls.indexOf(userAppend));
    // The id the history adapter received is the id the model sees and the thread shows.
    expect(run.lastId).toBe(userAppend.id);
    expect(messagesOf(runtime())[0].id).toBe(userAppend.id);
    expect(userAppend.id).toMatch(/^[0-9A-Za-z]{7}$/);
    expect(userAppend.parentId).toBeNull();
    // The local thread id the runtime gave initialize, and the assistant reply's id.
    const init = backend.calls.find((c) => c.op === "initialize") as Extract<Call, { op: "initialize" }>;
    expect(init.localId).toMatch(/^__LOCALID_[0-9a-z]+$/);
    const assistantAppend = backend.calls.find((c) => c.op === "append" && c.role === "assistant") as Write;
    expect(assistantAppend.id).toMatch(/^[0-9A-Za-z]{7}$/);
    expect(assistantAppend.parentId).toBe(userAppend.id);
    expect(assistantAppend.status).toBe("complete");
    expect(backend.calls.filter((c) => c.op === "update")).toEqual([]);
  });

  it("an edit and a regeneration are appends of new ids under the same parent; nothing is updated or deleted", async () => {
    const backend = new Backend();
    const runtime = mount(backend.adapter(), ackModel(backend));
    await act(async () => {
      runtime().thread.append({ role: "user", content: [{ type: "text", text: "Original." }] });
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(2));
    const [user, reply] = messagesOf(runtime());
    await act(async () => {
      const composer = runtime().thread.getMessageById(user.id).composer;
      composer.beginEdit();
      composer.setText("Edited.");
      composer.send();
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(4));
    await act(async () => {
      runtime().thread.getMessageById(messagesOf(runtime())[1].id).reload();
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(5));
    const appends = backend.calls.filter((c) => c.op === "append") as Write[];
    expect(new Set(appends.map((a) => a.id)).size).toBe(5);
    expect(appends[2]).toMatchObject({ role: "user", parentId: null });
    expect(appends[2].id).not.toBe(user.id);
    expect(appends[3]).toMatchObject({ role: "assistant", parentId: appends[2].id });
    expect(appends[4]).toMatchObject({ role: "assistant", parentId: appends[2].id });
    expect(appends[4].id).not.toBe(reply.id);
    expect(backend.calls.filter((c) => c.op === "update")).toEqual([]);
    // Switching back to the first branch writes nothing.
    const before = backend.calls.length;
    await act(async () => {
      runtime().thread.getMessageById(appends[2].id).switchToBranch({ position: "previous" });
    });
    expect(messagesOf(runtime())[0].id).toBe(user.id);
    expect(backend.calls.length).toBe(before);
  });

  it("load() without a headId shows the branch of the last message in load order", async () => {
    const backend = new Backend();
    const runtime = mount(backend.adapter(), ackModel(backend));
    await act(async () => {
      runtime().thread.append({ role: "user", content: [{ type: "text", text: "One." }] });
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(2));
    const [first] = messagesOf(runtime());
    await act(async () => {
      const composer = runtime().thread.getMessageById(first.id).composer;
      composer.beginEdit();
      composer.setText("One, edited.");
      composer.send();
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(4));
    const appends = backend.calls.filter((c) => c.op === "append") as Write[];
    const remoteId = appends[0].remoteId;

    // Without a headId: the head is the last message in the order load() returned (the edit's reply).
    let reloaded = await reloadInto(backend, remoteId, ackModel(backend));
    await waitFor(() => expect(messagesOf(reloaded()).map((m) => m.id)).toEqual([appends[2].id, appends[3].id]));
    expect(backend.calls.filter((c) => c.op === "load").at(-1)).toEqual({ op: "load", remoteId });
    // Both branches were imported: the first is reachable by switching.
    await act(async () => {
      reloaded().thread.getMessageById(appends[2].id).switchToBranch({ position: "previous" });
    });
    expect(messagesOf(reloaded()).map((m) => m.id)).toEqual([appends[0].id, appends[1].id]);

    // The same messages in another order (the first branch last): the head follows the order.
    backend.loadShape = (items) => ({ messages: [items[2], items[3], items[0], items[1]].map((i) => JSON.parse(JSON.stringify(i))) });
    reloaded = await reloadInto(backend, remoteId, ackModel(backend));
    await waitFor(() => expect(messagesOf(reloaded()).map((m) => m.id)).toEqual([appends[0].id, appends[1].id]));
  });

  it("a run paused by a human tool is appended when it pauses, updated when it completes, and a reload restores the pending call", async () => {
    const backend = new Backend();
    const human = ["ask_owner"];
    const runtime = mount(backend.adapter(), humanToolModel(backend), human);
    await act(async () => {
      runtime().thread.append({ role: "user", content: [{ type: "text", text: "Start." }] });
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(2));
    const paused = backend.calls.filter((c) => c.op === "append")[1] as Write;
    // The pause is persisted as an append of the requires-action message: no update yet.
    expect(paused).toMatchObject({ role: "assistant", status: "requires-action" });
    expect(backend.calls.filter((c) => c.op === "update")).toEqual([]);
    const remoteId = paused.remoteId;
    const stored = backend.threads.get(remoteId)!.items[1].message;
    expect(stored.role === "assistant" && stored.status).toEqual({ type: "requires-action", reason: "tool-calls" });

    // Reload: the pending call comes back from history alone, still awaiting its result.
    const reloaded = await reloadInto(backend, remoteId, humanToolModel(backend), human);
    await waitFor(() => expect(messagesOf(reloaded()).map((m) => m.id)).toEqual([backend.threads.get(remoteId)!.items[0].message.id, paused.id]));
    const restored = messagesOf(reloaded())[1];
    expect(restored.role).toBe("assistant");
    expect(restored.role === "assistant" && restored.status).toEqual({ type: "requires-action", reason: "tool-calls" });
    const part = restored.content.find((p) => p.type === "tool-call");
    expect(part).toMatchObject({ toolCallId: "call-1", toolName: "ask_owner" });
    expect(part && "result" in part ? part.result : undefined).toBeUndefined();

    // Answering it after the reload resumes the run and the completion is an update of the same id.
    const runsBefore = backend.calls.filter((c) => c.op === "run").length;
    await act(async () => {
      reloaded().thread.getMessageById(paused.id).getMessagePartByToolCallId("call-1").addToolResult({ approved: true });
    });
    await waitFor(() =>
      expect(backend.calls.some((c) => c.op === "update" && c.status === "complete")).toBe(true),
    );
    expect(backend.calls.filter((c) => c.op === "run").length).toBe(runsBefore + 1);
    const updates = backend.calls.filter((c) => c.op === "update") as Write[];
    for (const update of updates) expect(update).toMatchObject({ id: paused.id, role: "assistant", remoteId });
    expect(updates.at(-1)!.status).toBe("complete");
    const final = backend.threads.get(remoteId)!.items[1].message;
    expect(final.role === "assistant" && final.content.map((p) => p.type)).toEqual(["tool-call", "text"]);
  });

  it("per-thread history: unstable_useAdapters' history loads each thread's own messages on switch", async () => {
    const backend = new Backend();
    const runtime = mount(backend.adapter(), ackModel(backend));
    await act(async () => {
      runtime().thread.append({ role: "user", content: [{ type: "text", text: "Thread A." }] });
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(2));
    await act(async () => {
      await runtime().threads.switchToNewThread();
    });
    expect(messagesOf(runtime())).toEqual([]);
    await act(async () => {
      runtime().thread.append({ role: "user", content: [{ type: "text", text: "Thread B." }] });
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "append")).toHaveLength(4));
    const [a, b] = [...backend.threads.keys()];
    expect(a).not.toBe(b);
    expect(backend.threads.get(a)!.items.map((i) => i.parentId === null && i.message.content[0])).toContainEqual({ type: "text", text: "Thread A." });
    expect(backend.threads.get(b)!.items.map((i) => i.parentId === null && i.message.content[0])).toContainEqual({ type: "text", text: "Thread B." });
    // In one mount, a new thread's load runs before it has a remote id; switching back reuses the mounted thread.
    expect(backend.calls.filter((c) => c.op === "load")).toEqual([{ op: "load", remoteId: undefined }, { op: "load", remoteId: undefined }]);
    // After a reload, each thread's history adapter loads by its own remote id.
    const reloaded = await reloadInto(backend, a, ackModel(backend));
    await waitFor(() => expect(messagesOf(reloaded()).map((m) => m.id)).toEqual(backend.threads.get(a)!.items.map((i) => i.message.id)));
    await act(async () => {
      await reloaded().threads.switchToThread(b);
    });
    await waitFor(() => expect(messagesOf(reloaded()).map((m) => m.id)).toEqual(backend.threads.get(b)!.items.map((i) => i.message.id)));
    expect(backend.calls.filter((c) => c.op === "load" && c.remoteId !== undefined)).toEqual([
      { op: "load", remoteId: a },
      { op: "load", remoteId: b },
    ]);
  });

  it("generateTitle with no model: an empty stream that closes at once is accepted and leaves no title", async () => {
    const backend = new Backend();
    const runtime = mount(backend.adapter(), ackModel(backend));
    await act(async () => {
      runtime().thread.append({ role: "user", content: [{ type: "text", text: "Title?" }] });
    });
    await waitFor(() => expect(backend.calls.filter((c) => c.op === "generateTitle").length).toBeGreaterThan(0));
    const title = backend.calls.find((c) => c.op === "generateTitle") as Extract<Call, { op: "generateTitle" }>;
    expect(title.remoteId).toBe([...backend.threads.keys()][0]);
    await act(async () => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(runtime().threads.mainItem.getState().title).toBeUndefined();
  });
});
