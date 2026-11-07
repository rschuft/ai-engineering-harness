import type { ChatModelAdapter } from "@assistant-ui/react";

export const NO_CHAT_MODEL_MESSAGE =
  "No chat model is connected to the Owner host yet, so nothing was sent and no reply was generated.";

/**
 * The chat area's model adapter for assistant-ui's LocalRuntime. No model or
 * backend is connected (the conversation store and model routing are later
 * leaves, U-02.x), so it never produces a reply: a run fails with a plain
 * explanation instead of inventing one. The composer is disabled as well, so
 * a run is not expected; this is the second line of defence.
 */
export const modelFreeChatAdapter: ChatModelAdapter = {
  async run() {
    throw new Error(NO_CHAT_MODEL_MESSAGE);
  },
};
