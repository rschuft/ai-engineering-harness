import type { ChatModelAdapter } from "@assistant-ui/react";
import { SessionRefusal, REFUSAL_TEXT, type IntegrationClient } from "../identity/owner-session";
import { messageStored } from "./conversation-adapters";

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

// ---------------------------------------------------------------------------
// Intent capture (plan leaf P-01.3; integrations/ownerhost/capture.py).
//
// No model is connected, so the structure of a requested change comes from
// the Owner: the request form (RequestForm.tsx) sends ONE message in a fixed
// layout, built by formatRequest. When the Owner's message is in that layout
// (it starts with REQUEST_LABELS.change), the reply is not the fixed
// acknowledgement: this adapter asks the Integration process to capture the
// stored message as an OpenSpec intent change, naming the thread and the
// message and sending the sha256 it computed of the message's text, and the
// reply is a card (CAPTURE_TOOL, capture-card.tsx) built only from the
// service's answer or refusal. The service parses the layout itself and
// refuses anything else; nothing here interprets the Owner's words.


/** The card's tool name: a tool call whose result is the capture's answer (never run by a model). */
export const CAPTURE_TOOL = "intent_capture";

/** The fixed layout's labels (capture.py parses exactly these). */
export const REQUEST_LABELS = {
  change: "Change: ",
  objective: "Objective: ",
  criteria: "Acceptance criteria:",
  criterion: "- ",
  suggestion: "Suggestion: ",
} as const;

export type RequestFields = { change: string; objective: string; criteria: string[]; suggestions: string[] };

/** One line of a field: what the Owner typed, its surrounding whitespace removed (shown in the form's preview). */
export function fieldLine(value: string): string {
  return value.replace(/[\r\n]+/g, " ").trim();
}

/**
 * The request in the fixed layout: one line each, LF between lines, no final
 * line break; empty criteria and suggestions are left out. The preview shows
 * exactly this text, and it is the message stored and quoted.
 */
export function formatRequest(fields: RequestFields): string {
  const criteria = fields.criteria.map(fieldLine).filter((c) => c.length > 0);
  const suggestions = fields.suggestions.map(fieldLine).filter((s) => s.length > 0);
  return [
    REQUEST_LABELS.change + fieldLine(fields.change),
    REQUEST_LABELS.objective + fieldLine(fields.objective),
    REQUEST_LABELS.criteria,
    ...criteria.map((c) => REQUEST_LABELS.criterion + c),
    ...suggestions.map((s) => REQUEST_LABELS.suggestion + s),
  ].join("\n");
}

/** Whether an Owner message is sent for capture: it begins with the layout's first label. */
export function isCaptureRequest(text: string): boolean {
  return text.startsWith(REQUEST_LABELS.change);
}

/** The sha256 of TEXT's UTF-8 bytes, as 64 lower-case hex digits (WebCrypto; no network). */
export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export type CaptureResult =
  | { captured: true; change: string; commit: string; created: boolean; receipt: string }
  | { captured: false; code: string; text: string; detail: string | null };

type ThreadHandle = { initialize(): Promise<{ remoteId: string }> };

function messageText(message: { content: readonly unknown[] } | undefined): string | null {
  const parts = message?.content ?? [];
  if (parts.length !== 1) return null;
  const part = parts[0] as { type?: unknown; text?: unknown };
  return part.type === "text" && typeof part.text === "string" ? part.text : null;
}

function captured(answer: unknown): CaptureResult {
  const a = answer as Record<string, unknown> | null;
  if (
    !a ||
    typeof a.change !== "string" ||
    typeof a.commit !== "string" ||
    !/^[0-9a-f]{40}$/.test(a.commit) ||
    typeof a.created !== "boolean" ||
    typeof a.receipt !== "string"
  ) {
    throw new SessionRefusal("ANSWER_INVALID");
  }
  return { captured: true, change: a.change, commit: a.commit, created: a.created, receipt: a.receipt };
}

/**
 * The signed-in chat's model adapter (no model): the fixed ACKNOWLEDGEMENT
 * for an ordinary message; for a message in the request layout, the capture
 * and its card. The capture is sent only after the history adapter has
 * stored the message (messageStored), so the service compares the digest
 * with the stored bytes; a retry, a reload or a reconnect asks again and the
 * service answers the same commit.
 */
export function createCapturingChatAdapter(client: IntegrationClient, thread: () => ThreadHandle): ChatModelAdapter {
  return {
    async run({ messages }) {
      const last = messages[messages.length - 1];
      const text = last?.role === "user" ? messageText(last) : null;
      if (last === undefined || text === null || !isCaptureRequest(text)) {
        return { content: [{ type: "text", text: ACKNOWLEDGEMENT }] };
      }
      const args = { messageId: last.id };
      let result: CaptureResult;
      try {
        await messageStored(client, last.id);
        const { remoteId } = await thread().initialize();
        const path = `/threads/${encodeURIComponent(remoteId)}/messages/${encodeURIComponent(last.id)}/capture`;
        result = captured(await client.request("POST", path, { sha256: await sha256Hex(text) }));
      } catch (error) {
        const refusal = error instanceof SessionRefusal ? error : new SessionRefusal("UNREACHABLE");
        result = { captured: false, code: refusal.code, text: REFUSAL_TEXT[refusal.code], detail: refusal.detail };
      }
      return {
        content: [
          {
            type: "tool-call",
            toolCallId: `capture-${last.id}`,
            toolName: CAPTURE_TOOL,
            args,
            argsText: JSON.stringify(args),
            result,
          },
        ],
        status: { type: "complete", reason: "stop" },
      };
    },
  };
}
