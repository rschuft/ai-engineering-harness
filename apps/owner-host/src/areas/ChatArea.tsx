import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
} from "@assistant-ui/react";
import { EmptyState } from "./EmptyState";
import { modelFreeChatAdapter } from "./chat-adapter";

function UserMessage() {
  return (
    <MessagePrimitive.Root className="owner-chat__message owner-chat__message--user">
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="owner-chat__message owner-chat__message--assistant">
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

/**
 * The Owner chat, built from assistant-ui's headless primitives over its
 * LocalRuntime with a model-free adapter: an empty, in-memory thread with no
 * model, history store or network behind it.
 */
export function ChatArea() {
  const runtime = useLocalRuntime(modelFreeChatAdapter);
  return (
    <section className="owner-area owner-area--chat" aria-labelledby="chat-heading" data-testid="area-chat">
      <h2 id="chat-heading" className="owner-area__title">
        Chat
      </h2>
      <AssistantRuntimeProvider runtime={runtime}>
        <ThreadPrimitive.Root className="owner-chat" data-testid="chat-thread">
          <ThreadPrimitive.Viewport className="owner-chat__viewport">
            <ThreadPrimitive.Empty>
              <EmptyState title="No conversation yet" testId="chat-empty">
                <p>
                  No chat model and no conversation history are connected to the Owner host yet. Nothing you see here
                  comes from a model or a store.
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
    </section>
  );
}
