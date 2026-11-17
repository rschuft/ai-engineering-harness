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
  | { captured: true; change: string; commit: string; created: boolean; receipt: string; workTree?: string }
  | { captured: false; code: string; text: string; detail: string | null };

// ---------------------------------------------------------------------------
// Objective acceptance (plan leaf P-04.4; integrations/ownerhost/acceptance.py).
//
// Two Owner messages in fixed layouts, each answered by the Integration
// process from its store and the project repository, never from text the
// shell sends: "Review acceptance: O<n> of <change>" asks for the acceptance
// recorder's challenge, shown on the acceptance card (ACCEPTANCE_TOOL,
// acceptance-card.tsx) in the assistant message being written, whose id the
// request names; the card's Accept form then sends, as the Owner's own
// message, exactly "Accept O<n> of <change>" and his optional words, and the
// service records it (owner-ui channel, bound to this session) on the nonce
// the card holds. The reply is the recorded card (ACCEPTANCE_RECORD_TOOL).

/** The challenge card's tool name (never run by a model). */
export const ACCEPTANCE_TOOL = "objective_acceptance";
/** The recorded acceptance's card. */
export const ACCEPTANCE_RECORD_TOOL = "objective_acceptance_recorded";

const ITEM = "O[1-9][0-9]*";
const CHANGE = "[a-z0-9]+(?:-[a-z0-9]+)*";
const REVIEW = new RegExp(`^Review acceptance: (${ITEM}) of (${CHANGE})$`);
const ACCEPT_LINE = new RegExp(`^Accept (${ITEM}) of (${CHANGE})$`);

/** The review request for ITEM of CHANGE (acceptance.py's REVIEW_LAYOUT). */
export function formatReview(change: string, item: string): string {
  return `Review acceptance: ${item} of ${change}`;
}

/** {change, item} of a review request, or null. */
export function reviewRequest(text: string): { change: string; item: string } | null {
  const m = text.match(REVIEW);
  return m ? { item: m[1], change: m[2] } : null;
}

/**
 * The acceptance message exactly as it is sent and stored: "Accept <item> of
 * <change>", and, when the Owner wrote any, a line break and his own words
 * (line breaks LF, the ends trimmed).
 */
export function formatAcceptance(change: string, item: string, words: string): string {
  const own = words.replace(/\r\n?/g, "\n").trim();
  return `Accept ${item} of ${change}` + (own.length > 0 ? `\n${own}` : "");
}

/** {change, item} of an acceptance message (acceptance.py's ACCEPT_LAYOUT), or null. */
export function acceptanceMessage(text: string): { change: string; item: string } | null {
  const newline = text.indexOf("\n");
  const first = newline < 0 ? text : text.slice(0, newline);
  if (text.includes("\r") || (newline >= 0 && text.slice(newline + 1).trim().length === 0)) return null;
  const m = first.match(ACCEPT_LINE);
  return m ? { item: m[1], change: m[2] } : null;
}

export type AcceptanceChallenge =
  | { prepared: true; nonce: string; change: string; item: string; summary: string; expiresAt: string; revision: string }
  | { prepared: false; code: string; text: string; detail: string | null };

export type AcceptanceRecord =
  | {
      recorded: true;
      change: string;
      item: string;
      outcome: string;
      minted: boolean;
      commit: string;
      statement: string;
      created: boolean;
      workTree?: string;
    }
  | { recorded: false; code: string; text: string; detail: string | null };

function refused(error: unknown): { code: string; text: string; detail: string | null } {
  const refusal = error instanceof SessionRefusal ? error : new SessionRefusal("UNREACHABLE");
  return { code: refusal.code, text: REFUSAL_TEXT[refusal.code], detail: refusal.detail };
}

function challengeAnswer(answer: unknown): AcceptanceChallenge {
  const a = answer as Record<string, unknown> | null;
  if (
    !a ||
    typeof a.nonce !== "string" ||
    !/^[0-9a-f]{32}$/.test(a.nonce) ||
    typeof a.change !== "string" ||
    typeof a.item !== "string" ||
    typeof a.summary !== "string" ||
    typeof a.expiresAt !== "string" ||
    typeof a.revision !== "string"
  ) {
    throw new SessionRefusal("ANSWER_INVALID");
  }
  return { prepared: true, nonce: a.nonce, change: a.change, item: a.item, summary: a.summary, expiresAt: a.expiresAt, revision: a.revision };
}

function recordAnswer(answer: unknown): AcceptanceRecord {
  const a = answer as Record<string, unknown> | null;
  if (
    !a ||
    typeof a.change !== "string" ||
    typeof a.item !== "string" ||
    typeof a.outcome !== "string" ||
    typeof a.minted !== "boolean" ||
    typeof a.commit !== "string" ||
    !/^[0-9a-f]{40}$/.test(a.commit) ||
    typeof a.statement !== "string" ||
    typeof a.created !== "boolean" ||
    (a.workTree !== undefined && typeof a.workTree !== "string")
  ) {
    throw new SessionRefusal("ANSWER_INVALID");
  }
  const result: AcceptanceRecord = {
    recorded: true,
    change: a.change,
    item: a.item,
    outcome: a.outcome,
    minted: a.minted,
    commit: a.commit,
    statement: a.statement,
    created: a.created,
  };
  return typeof a.workTree === "string" ? { ...result, workTree: a.workTree } : result;
}

type RunMessage = { id: string; role: string; content: readonly unknown[] };

/** The nonce of the nearest card before the acceptance (in its branch) that shows CHANGE's ITEM, or null. */
export function cardNonce(messages: readonly RunMessage[], change: string, item: string): string | null {
  for (let i = messages.length - 2; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== "assistant") continue;
    for (const part of message.content as { type?: string; toolName?: string; result?: unknown }[]) {
      if (part?.type !== "tool-call" || part.toolName !== ACCEPTANCE_TOOL) continue;
      const r = part.result as Record<string, unknown> | undefined;
      if (r?.prepared === true && r.change === change && r.item === item && typeof r.nonce === "string") return r.nonce;
    }
  }
  return null;
}

function toolReply(toolCallId: string, toolName: string, args: Record<string, string>, result: unknown) {
  return {
    content: [{ type: "tool-call" as const, toolCallId, toolName, args, argsText: JSON.stringify(args), result }],
    status: { type: "complete" as const, reason: "stop" as const },
  };
}

function messagePath(remoteId: string, messageId: string, route: string): string {
  return `/threads/${encodeURIComponent(remoteId)}/messages/${encodeURIComponent(messageId)}/${route}`;
}

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
    typeof a.receipt !== "string" ||
    (a.workTree !== undefined && typeof a.workTree !== "string")
  ) {
    throw new SessionRefusal("ANSWER_INVALID");
  }
  const result: CaptureResult = { captured: true, change: a.change, commit: a.commit, created: a.created, receipt: a.receipt };
  // The commit is on the branch, and the work tree or the index does not hold its files (a process that ended
  // between the two): the card tells the Owner before he edits the project repository.
  return typeof a.workTree === "string" ? { ...result, workTree: a.workTree } : result;
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
    async run({ messages, unstable_getMessage }) {
      const last = messages[messages.length - 1];
      const text = last?.role === "user" ? messageText(last) : null;
      const review = text === null ? null : reviewRequest(text);
      const acceptance = text === null ? null : acceptanceMessage(text);
      if (last !== undefined && text !== null && review !== null) {
        // P-04.4: the challenge, shown on the card this run writes (its message id is the card's).
        const card = unstable_getMessage().id;
        const args = { messageId: last.id, change: review.change, item: review.item };
        let result: AcceptanceChallenge;
        try {
          await messageStored(client, last.id);
          const { remoteId } = await thread().initialize();
          result = challengeAnswer(
            await client.request("POST", messagePath(remoteId, last.id, "acceptance-challenge"), { sha256: await sha256Hex(text), card }),
          );
        } catch (error) {
          result = { prepared: false, ...refused(error) };
        }
        return toolReply(`acceptance-${last.id}`, ACCEPTANCE_TOOL, args, result);
      }
      if (last !== undefined && text !== null && acceptance !== null) {
        // P-04.4: the Owner's acceptance on the nonce of the card before it.
        const args = { messageId: last.id, change: acceptance.change, item: acceptance.item };
        const nonce = cardNonce(messages as readonly RunMessage[], acceptance.change, acceptance.item);
        let result: AcceptanceRecord;
        if (nonce === null) {
          result = { recorded: false, code: "ACCEPTANCE_NO_CARD", text: REFUSAL_TEXT.ACCEPTANCE_NO_CARD, detail: null };
        } else {
          try {
            await messageStored(client, last.id);
            const { remoteId } = await thread().initialize();
            result = recordAnswer(
              await client.request("POST", messagePath(remoteId, last.id, "acceptance"), { nonce, sha256: await sha256Hex(text) }),
            );
          } catch (error) {
            result = { recorded: false, ...refused(error) };
          }
        }
        return toolReply(`accepted-${last.id}`, ACCEPTANCE_RECORD_TOOL, args, result);
      }
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
