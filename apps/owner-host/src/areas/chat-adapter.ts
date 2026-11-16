import type { ChatModelAdapter } from "@assistant-ui/react";

export const NO_CHAT_MODEL_MESSAGE =
  "No chat model is connected to the Owner host yet, so nothing was sent and no reply was generated.";

/**
 * The chat area's model adapter for assistant-ui's LocalRuntime while the
 * Owner is not signed in to the Integration process: nothing can be stored,
 * so a run fails with a plain explanation instead of inventing a reply. The
 * composer is disabled as well, so a run is not expected; this is the second
 * line of defence.
 */
export const modelFreeChatAdapter: ChatModelAdapter = {
  async run() {
    throw new Error(NO_CHAT_MODEL_MESSAGE);
  },
};

/** The fixed reply to every Owner message (plan leaf U-02.1): never a model's text. */
export const ACKNOWLEDGEMENT =
  "Recorded in the Owner conversation store. No chat model is connected: this is the Owner host's fixed acknowledgement, not a model's reply.";

/**
 * The model-free chat while the Owner is signed in (U-02.1): each Owner
 * message is stored, and the reply is the fixed ACKNOWLEDGEMENT, the same
 * bytes every time, so no text in the thread comes from a model. No model or
 * network is called here; the history adapter stores both messages.
 */
export const acknowledgingChatAdapter: ChatModelAdapter = {
  async run() {
    return { content: [{ type: "text", text: ACKNOWLEDGEMENT }] };
  },
};
