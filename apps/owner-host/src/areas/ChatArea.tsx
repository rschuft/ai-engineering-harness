import { useEffect, useMemo, useRef } from "react";
import {
  ActionBarPrimitive,
  AssistantRuntimeProvider,
  BranchPickerPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  ThreadPrimitive,
  useAui,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { EmptyState } from "./EmptyState";
import {
  ACCEPTANCE_RECORD_TOOL,
  ACCEPTANCE_TOOL,
  CAPTURE_TOOL,
  OUTCOME_TOOL,
  createCapturingChatAdapter,
  modelFreeChatAdapter,
} from "./chat-adapter";
import { CaptureCard } from "./capture-card";
import { AcceptanceCard, AcceptanceRecordCard } from "./acceptance-card";
import { OutcomeCard, OutcomeClientContext } from "./outcome-card";
import { RequestForm } from "./RequestForm";
import { createThreadListAdapter } from "./conversation-adapters";
import { HUMAN_TOOL_NAMES, TOOL_COMPONENTS } from "./decision-tool";
import { useOwnerSession } from "../identity/OwnerSessionContext";
import type { IntegrationClient } from "../identity/owner-session";

function UserMessage() {
  return (
    <MessagePrimitive.Root className="owner-chat__message owner-chat__message--user">
      <MessagePrimitive.Parts />
      <ActionBarPrimitive.Root className="owner-chat__actions">
        <ActionBarPrimitive.Edit className="owner-chat__edit">Edit</ActionBarPrimitive.Edit>
      </ActionBarPrimitive.Root>
      <BranchPickerPrimitive.Root className="owner-chat__branches" hideWhenSingleBranch>
        <BranchPickerPrimitive.Previous aria-label="Previous version">‹</BranchPickerPrimitive.Previous>
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
        <BranchPickerPrimitive.Next aria-label="Next version">›</BranchPickerPrimitive.Next>
      </BranchPickerPrimitive.Root>
    </MessagePrimitive.Root>
  );
}

/**
 * The tool UIs of the chat: a pending decision (U-02.2), a captured request's card (P-01.3), and the acceptance
 * challenge and recorded acceptance cards (P-04.4), and the accepted outcome's card (U-04.2).
 */
const CHAT_TOOLS = {
  ...TOOL_COMPONENTS,
  by_name: {
    ...TOOL_COMPONENTS.by_name,
    [CAPTURE_TOOL]: CaptureCard,
    [ACCEPTANCE_TOOL]: AcceptanceCard,
    [ACCEPTANCE_RECORD_TOOL]: AcceptanceRecordCard,
    [OUTCOME_TOOL]: OutcomeCard,
  },
};

/** An assistant message: its text, and its tool calls through their tool UIs (a pending decision, U-02.2). */
function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="owner-chat__message owner-chat__message--assistant">
      <MessagePrimitive.Parts components={{ tools: CHAT_TOOLS }} />
    </MessagePrimitive.Root>
  );
}

/** An edit is sent as a new message under the same parent; the store keeps both (decision 0025, point 6). */
function EditComposer() {
  return (
    <ComposerPrimitive.Root className="owner-chat__composer owner-chat__composer--edit">
      <ComposerPrimitive.Input className="owner-chat__input" aria-label="Edit message" />
      <ComposerPrimitive.Cancel className="owner-chat__cancel">Cancel</ComposerPrimitive.Cancel>
      <ComposerPrimitive.Send className="owner-chat__send">Save as new version</ComposerPrimitive.Send>
    </ComposerPrimitive.Root>
  );
}

function ThreadListItem() {
  return (
    <ThreadListItemPrimitive.Root className="owner-chat__thread-item">
      <ThreadListItemPrimitive.Trigger className="owner-chat__thread-trigger">
        <ThreadListItemPrimitive.Title fallback="Untitled thread" />
      </ThreadListItemPrimitive.Trigger>
    </ThreadListItemPrimitive.Root>
  );
}

/** Signed out: an empty, in-memory thread with no model, store or network behind it, and a disabled composer. */
function UnconnectedChat() {
  const runtime = useLocalRuntime(modelFreeChatAdapter);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="owner-chat" data-testid="chat-thread">
        <ThreadPrimitive.Viewport className="owner-chat__viewport">
          <ThreadPrimitive.Empty>
            <EmptyState title="No conversation yet" testId="chat-empty">
              <p>
                No chat model and no conversation history are connected to the Owner host yet. Nothing you see here
                comes from a model or a store. Sign in to keep a conversation in the Owner conversation store.
              </p>
            </EmptyState>
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </ThreadPrimitive.Viewport>
        <ComposerPrimitive.Root className="owner-chat__composer">
          <ComposerPrimitive.Input
            className="owner-chat__input"
            aria-label="Message"
            placeholder="Chat is not connected yet"
            disabled
          />
          <ComposerPrimitive.Send className="owner-chat__send" disabled>
            Send
          </ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

/**
 * Signed in (U-02.1): assistant-ui's LocalRuntime under its RemoteThreadList
 * runtime, both kept in the Owner conversation store through the Integration
 * process. Messages survive a reload in the store's order; replies are the
 * fixed acknowledgement, never a model's text.
 *
 * U-02.2: a run that pauses on a human tool (owner_decision, HUMAN_TOOL_NAMES)
 * is kept as the paused assistant message, and after a browser or service
 * restart the history load brings it back with its call still pending; the
 * Owner answers it in the decision card and the completed message is an
 * update of the same id.
 *
 * P-01.3: the request form sends a requested change as one message in the
 * fixed layout; the run's model adapter (no model) then asks the Integration
 * process to capture it and replies with the capture card.
 *
 * P-04.4: a "Review acceptance: O<n> of <change>" message (the capture card's
 * review button sends one) is answered with the acceptance card, whose Accept
 * form sends the Owner's acceptance as his own message; the reply to that is
 * the recorded acceptance's card.
 *
 * U-04.2: a recorded acceptance's reply also holds the accepted outcome's
 * card, which reads the Integration process's outcome projection through
 * this chat's CLIENT each time it is shown (a reload or a replay of the
 * thread reads it again). CHAT_MODEL is the
 * run's model adapter: unless one is given, the capturing adapter, which
 * answers any other message with the fixed acknowledgement.
 */
export function StoredChat({ client, chatModel }: { client: IntegrationClient; chatModel?: ChatModelAdapter }) {
  const adapter = useMemo(() => createThreadListAdapter(client), [client]);
  const runtimeHook = useMemo(
    () =>
      function useStoredThreadRuntime() {
        const aui = useAui();
        const current = useRef(aui);
        useEffect(() => {
          current.current = aui;
        });
        const model = useMemo(
          () => chatModel ?? createCapturingChatAdapter(client, () => current.current.threadListItem()),
          [],
        );
        return useLocalRuntime(model, { unstable_humanToolNames: HUMAN_TOOL_NAMES });
      },
    [chatModel, client],
  );
  const runtime = useRemoteThreadListRuntime({ runtimeHook, adapter });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <OutcomeClientContext.Provider value={client}>
        <div className="owner-chat__layout" data-testid="chat-stored">
          <ThreadListPrimitive.Root className="owner-chat__threads" aria-label="Threads" data-testid="chat-threads">
            <ThreadListPrimitive.New className="owner-chat__new-thread">New thread</ThreadListPrimitive.New>
            <ThreadListPrimitive.Items components={{ ThreadListItem }} />
          </ThreadListPrimitive.Root>
          <ThreadPrimitive.Root className="owner-chat" data-testid="chat-thread">
            <ThreadPrimitive.Viewport className="owner-chat__viewport">
              <ThreadPrimitive.Empty>
                <EmptyState title="No messages in this thread" testId="chat-empty">
                  <p>
                    Messages are kept in the Owner conversation store. No chat model is connected: each reply is a fixed
                    acknowledgement.
                  </p>
                </EmptyState>
              </ThreadPrimitive.Empty>
              <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage, EditComposer }} />
            </ThreadPrimitive.Viewport>
            <ComposerPrimitive.Root className="owner-chat__composer">
              <ComposerPrimitive.Input className="owner-chat__input" aria-label="Message" placeholder="Write to the Owner host" />
              <ComposerPrimitive.Send className="owner-chat__send">Send</ComposerPrimitive.Send>
            </ComposerPrimitive.Root>
            <RequestForm />
          </ThreadPrimitive.Root>
        </div>
      </OutcomeClientContext.Provider>
    </AssistantRuntimeProvider>
  );
}

/**
 * The Owner chat, built from assistant-ui's headless primitives. Signed out,
 * it is an empty thread with no model, store or network; signed in, it is
 * the stored, model-free chat.
 */
export function ChatArea() {
  const { client } = useOwnerSession();
  return (
    <section className="owner-area owner-area--chat" aria-labelledby="chat-heading" data-testid="area-chat">
      <h2 id="chat-heading" className="owner-area__title">
        Chat
      </h2>
      {client ? <StoredChat client={client} /> : <UnconnectedChat />}
    </section>
  );
}
