// The Owner UI session credential on the shell side (plan leaf U-01.3; Proposed
// decision 0025, point 4).
//
// The Owner mints `cred-owner-ui-session` himself with the enroll command at a
// console and pastes it into the sign-in view. The shell keeps its copy in its
// own origin's localStorage. The origin is scheme, host and port, so a
// listener on another port cannot read it; a process that holds the shell's
// own port (127.0.0.1:5173 or 4173) while the shell is down is that origin and
// can. For a process of the Owner's account that is inside decision 0010 point
// 1's same-account limit; for another local account it is a disclosed residual.
// Vite's strictPort refuses to start on a squatted port, a visible signal. The
// shell sends the copy in the `X-AIEH-Owner-Session` header on every request to
// the Integration process, never as a cookie, and removes it on "Sign out".
// The Integration process's own expiry bounds it.
//
// The client below is the only way the shell calls the Integration process:
// it addresses http://127.0.0.1:13310 only, adds the header to every request,
// omits cookies and HTTP credentials, refuses redirects and sends no referrer.

export const INTEGRATION_ORIGIN = "http://127.0.0.1:13310";
export const SESSION_HEADER = "X-AIEH-Owner-Session";
export const CREDENTIAL_STORAGE_KEY = "aieh.owner-host.owner-ui-session";
/** aieh-oui- and 52 lower-case base32 characters (32 random bytes). */
export const CREDENTIAL_SHAPE = /^aieh-oui-[a-z2-7]{52}$/;
const RECORD_VERSION = 1;
const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** The refusals of decision 0025, point 5, and what the shell itself refuses. */
export const CREDENTIAL_CODES = [
  "SESSION_CREDENTIAL_MISSING",
  "SESSION_CREDENTIAL_FOREIGN",
  "SESSION_CREDENTIAL_EXPIRED",
  "SESSION_CREDENTIAL_REVOKED",
] as const;
/** The refusals of the thread and history routes (U-02.1; decision 0025, point 6). */
export const CONVERSATION_CODES = [
  "REQUEST_INVALID",
  "REQUEST_TOO_LARGE",
  "THREAD_INVALID",
  "THREAD_NOT_FOUND",
  "THREAD_DELETE_REFUSED",
  "MESSAGE_INVALID",
  "MESSAGE_PARENT_NOT_FOUND",
  "MESSAGE_ID_CONFLICT",
  "MESSAGE_IMMUTABLE",
  "MESSAGE_NOT_FOUND",
] as const;
/** The refusals of the capture route (plan leaf P-01.3; integrations/ownerhost/capture.py). */
export const CAPTURE_CODES = [
  "CAPTURE_PROJECT_UNCONFIGURED",
  "CAPTURE_CONFIG_INVALID",
  "CAPTURE_STORE_UNAVAILABLE",
  "CAPTURE_NOT_A_STATEMENT",
  "CAPTURE_MESSAGE_MISMATCH",
  "CAPTURE_LAYOUT_INVALID",
  "CAPTURE_SESSION_UNRECOGNIZED",
  "COMMIT_IDENTITY_UNAVAILABLE",
  "COMMIT_IDENTITY_INVALID",
  "COMMIT_IDENTITY_PLACEHOLDER",
  "CAPTURE_PROJECT_UNAVAILABLE",
  "CAPTURE_PROJECT_IS_HARNESS",
  "CAPTURE_CHANGE_EXISTS",
  "CAPTURE_RECEIPT_CONFLICT",
  "CAPTURE_COMMIT_REFUSED",
  "CAPTURE_COMMIT_UNREACHABLE",
  "CAPTURE_GIT_FAILED",
  "CAPTURE_OUTCOME_UNKNOWN",
] as const;
/**
 * The refusals of the acceptance routes (plan leaf P-04.4; integrations/ownerhost/acceptance.py): its own, and the
 * acceptance recorder's (P-04.1) that the service passes on. The configuration, identity and project refusals are
 * the capture's (CAPTURE_CODES).
 */
export const ACCEPTANCE_CODES = [
  "ACCEPTANCE_LAYOUT_INVALID",
  "ACCEPTANCE_MESSAGE_MISMATCH",
  "ACCEPTANCE_NOT_A_STATEMENT",
  "ACCEPTANCE_MODEL_AUTHORED",
  "STATEMENT_NOT_OWNER",
  "ACCEPTANCE_SESSION_MISMATCH",
  "ACCEPTANCE_CHALLENGE_UNKNOWN",
  "ACCEPTANCE_CHALLENGE_MISMATCH",
  "ACCEPTANCE_NOT_AFTER_CARD",
  "CHALLENGE_CONSUMED",
  "CHALLENGE_EXPIRED",
  "CHALLENGE_STALE",
  "CHALLENGE_INVALID",
  "ACCEPTANCE_RECEIPT_CONFLICT",
  "ACCEPTANCE_STORE_UNAVAILABLE",
  "ACCEPTANCE_OUTCOME_UNKNOWN",
  "PROJECT_UNAVAILABLE",
  "GIT_FAILED",
  "CHANGE_MISSING",
  "ITEM_NOT_OBJECTIVE",
  "INTENT_RECORD_INVALID",
  "OUTCOME_METADATA_INVALID",
  "OBJECT_NAME_INVALID",
  "OUTCOME_ALREADY_MINTED",
  "OUTCOME_NOT_MINTED",
  "ACCEPTANCE_ALREADY_RECORDED",
  "ACCEPTANCE_REFERENCE_INVALID",
  "RESOLUTION_FAILED",
  "HOOKS_UNSUPPORTED",
  "COMMIT_REFUSED",
  "SESSION_BINDING_REQUIRED",
  "SESSION_BINDING_REFUSED",
] as const;
export type RefusalCode =
  | (typeof CREDENTIAL_CODES)[number]
  | (typeof CONVERSATION_CODES)[number]
  | (typeof CAPTURE_CODES)[number]
  | (typeof ACCEPTANCE_CODES)[number]
  | "ACCEPTANCE_NO_CARD"
  | "HOST_NOT_ALLOWED"
  | "ORIGIN_NOT_ALLOWED"
  | "NOT_SHAPED"
  | "UNREACHABLE"
  | "ANSWER_INVALID";

export const REFUSAL_TEXT: Record<RefusalCode, string> = {
  SESSION_CREDENTIAL_MISSING: "No credential was sent.",
  SESSION_CREDENTIAL_FOREIGN: "This is not the current Owner UI session credential.",
  SESSION_CREDENTIAL_EXPIRED: "This session has expired. Run the enroll command again and sign in with the new credential.",
  SESSION_CREDENTIAL_REVOKED: "A later enrollment replaced this session. Sign in with the newest credential.",
  HOST_NOT_ALLOWED: "The Integration process refused the address it was called at.",
  ORIGIN_NOT_ALLOWED: "The Integration process refused this page's origin.",
  NOT_SHAPED: "That is not an Owner UI session credential (aieh-oui- and 52 characters).",
  UNREACHABLE: "The Integration process is not reachable at 127.0.0.1:13310.",
  ANSWER_INVALID: "The Integration process gave an answer the shell does not understand.",
  REQUEST_INVALID: "The Integration process refused a request the shell sent.",
  REQUEST_TOO_LARGE: "The message is too large for the Owner conversation store.",
  THREAD_INVALID: "The Owner conversation store refused that thread or title.",
  THREAD_NOT_FOUND: "The Owner conversation store has no such thread.",
  THREAD_DELETE_REFUSED: "Threads are never deleted from the Owner conversation store; archive it instead.",
  MESSAGE_INVALID: "The Owner conversation store refused the message's form.",
  MESSAGE_PARENT_NOT_FOUND: "The message answers a message the store does not hold.",
  MESSAGE_ID_CONFLICT: "The thread already holds another message under this id.",
  MESSAGE_IMMUTABLE: "A statement is never changed; an edit is kept as a new message.",
  MESSAGE_NOT_FOUND: "The Owner conversation store has no such message.",
  CAPTURE_PROJECT_UNCONFIGURED: "No project repository is configured for the Owner host (components.owner_host).",
  CAPTURE_CONFIG_INVALID: "The Owner host's project configuration (components.owner_host) is not valid.",
  CAPTURE_STORE_UNAVAILABLE: "The integration store is not available, so nothing was written.",
  CAPTURE_NOT_A_STATEMENT: "Only your own message can be captured, not a reply.",
  CAPTURE_MESSAGE_MISMATCH: "The stored message is not the text sent, so nothing was captured.",
  CAPTURE_LAYOUT_INVALID: "The request is not in the request form's layout, so nothing was captured.",
  CAPTURE_SESSION_UNRECOGNIZED: "The Integration process does not know whose session this is, so nothing was written.",
  COMMIT_IDENTITY_UNAVAILABLE: "No git identity is configured for you (components.owner_host.git_identities).",
  COMMIT_IDENTITY_INVALID: "Your configured git identity is not \"Name <email>\" with a visible name and an ASCII email.",
  COMMIT_IDENTITY_PLACEHOLDER: "Your configured git identity uses a placeholder domain; configure a real address.",
  CAPTURE_PROJECT_UNAVAILABLE: "The project repository cannot be used (not a work tree with a commit on a branch).",
  CAPTURE_PROJECT_IS_HARNESS: "The configured project repository is the harness's own checkout; configure the project's repository.",
  CAPTURE_CHANGE_EXISTS: "The project repository already has a change of this name; choose another name.",
  CAPTURE_RECEIPT_CONFLICT: "This message was captured under another configuration.",
  CAPTURE_COMMIT_REFUSED: "The project repository refused the commit; nothing was written.",
  CAPTURE_COMMIT_UNREACHABLE: "This message's capture is on no branch of the project repository any more; nothing was written.",
  CAPTURE_GIT_FAILED: "The project repository could not be read or written; see the detail, repair it, and capture again.",
  CAPTURE_OUTCOME_UNKNOWN: "A commit may have been made; read the project repository before anything else.",
  ACCEPTANCE_NO_CARD: "No acceptance card for this item comes before this message; review the item first.",
  ACCEPTANCE_LAYOUT_INVALID: "Review with \"Review acceptance: O<n> of <change>\"; accept with \"Accept O<n> of <change>\".",
  ACCEPTANCE_MESSAGE_MISMATCH: "The stored message is not the text sent, so nothing was recorded.",
  ACCEPTANCE_NOT_A_STATEMENT: "A review is asked from your own message, not from a reply.",
  ACCEPTANCE_MODEL_AUTHORED: "Only your own message can accept; a reply, a model or an agent cannot.",
  STATEMENT_NOT_OWNER: "Only the Owner accepts an objective.",
  ACCEPTANCE_SESSION_MISMATCH: "The acceptance or its card belongs to another session; review again in this session.",
  ACCEPTANCE_CHALLENGE_UNKNOWN: "The Integration process no longer holds this card's challenge (it restarted); review again.",
  ACCEPTANCE_CHALLENGE_MISMATCH: "The acceptance names another item or thread than the card shows.",
  ACCEPTANCE_NOT_AFTER_CARD: "Accept after the card, from the card, in the branch that holds it.",
  CHALLENGE_CONSUMED: "An acceptance was already recorded on this card; review again for a new one.",
  CHALLENGE_EXPIRED: "The card has expired; review again.",
  CHALLENGE_STALE: "The proposal changed after the card was shown; review again.",
  CHALLENGE_INVALID: "The card's challenge is not what the acceptance recorder shows for this change.",
  ACCEPTANCE_RECEIPT_CONFLICT: "This message was recorded for another card; accept with a new message.",
  ACCEPTANCE_STORE_UNAVAILABLE: "The integration store is not available, so nothing was committed.",
  ACCEPTANCE_OUTCOME_UNKNOWN: "A commit may have been made; read the project repository before anything else.",
  PROJECT_UNAVAILABLE: "The project repository cannot be read.",
  GIT_FAILED: "The project repository could not be read or written; see the detail.",
  CHANGE_MISSING: "The project repository has no such change.",
  ITEM_NOT_OBJECTIVE: "That item is not an Objective item of the change.",
  INTENT_RECORD_INVALID: "The change's proposal is not a valid intent record.",
  OUTCOME_METADATA_INVALID: "The change's outcome declarations (x-outcomes) are not valid.",
  OBJECT_NAME_INVALID: "The change or the item is not named as OpenSpec and the intent record write them.",
  OUTCOME_ALREADY_MINTED: "The item already has its outcome id.",
  OUTCOME_NOT_MINTED: "The item has no outcome id yet.",
  ACCEPTANCE_ALREADY_RECORDED: "This acceptance is already recorded; the outcome id stands.",
  ACCEPTANCE_REFERENCE_INVALID: "The acceptance must be a message of its own, not the request.",
  RESOLUTION_FAILED: "Nothing was committed: the recorder and the lineage resolver disagree.",
  HOOKS_UNSUPPORTED: "The project repository has client hooks; the recorder commits only without them.",
  COMMIT_REFUSED: "The project repository refused the commit; nothing was written. The receipt stays reserved: accept again once repaired.",
  SESSION_BINDING_REQUIRED: "The acceptance must be bound to your Owner UI session.",
  SESSION_BINDING_REFUSED: "The acceptance is not bound to the session that sent it.",
};

export interface OwnerSession {
  readonly sessionId: string;
  readonly issuedAt: string;
  readonly expiresAt: string;
}

export interface StoredCredential extends OwnerSession {
  readonly credential: string;
}

export class SessionRefusal extends Error {
  constructor(
    readonly code: RefusalCode,
    readonly status: number | null = null,
    /** The service's own detail of the refusal, when it gave one (shown as given, never interpreted). */
    readonly detail: string | null = null,
  ) {
    super(`${code}: ${REFUSAL_TEXT[code]}`);
    this.name = "SessionRefusal";
  }

  /** True when the credential itself is refused, so the stored copy is useless. */
  get credentialRefused(): boolean {
    return (CREDENTIAL_CODES as readonly string[]).includes(this.code);
  }
}

type Storage_ = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

export function isCredentialShaped(value: string): boolean {
  return CREDENTIAL_SHAPE.test(value);
}

function isSession(value: unknown): value is OwnerSession {
  const v = value as Partial<OwnerSession> | null;
  return (
    !!v &&
    typeof v.sessionId === "string" &&
    SESSION_ID.test(v.sessionId) &&
    typeof v.issuedAt === "string" &&
    TIMESTAMP.test(v.issuedAt) &&
    typeof v.expiresAt === "string" &&
    TIMESTAMP.test(v.expiresAt)
  );
}

export function defaultStorage(): Storage_ | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** The stored copy, or null when there is none or it is malformed (then it is removed). */
export function loadStoredCredential(storage: Storage_ | null = defaultStorage()): StoredCredential | null {
  if (!storage) return null;
  let raw: string | null = null;
  try {
    raw = storage.getItem(CREDENTIAL_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<StoredCredential> & { v?: number };
    const credential = value.credential;
    if (value.v === RECORD_VERSION && typeof credential === "string" && isCredentialShaped(credential) && isSession(value)) {
      return { credential, sessionId: value.sessionId, issuedAt: value.issuedAt, expiresAt: value.expiresAt };
    }
  } catch {
    // not JSON: removed below
  }
  clearStoredCredential(storage);
  return null;
}

export function storeCredential(stored: StoredCredential, storage: Storage_ | null = defaultStorage()): boolean {
  if (!storage) return false;
  try {
    storage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify({ v: RECORD_VERSION, ...stored }));
    return true;
  } catch {
    return false;
  }
}

/** Sign out: the shell's copy is removed. */
export function clearStoredCredential(storage: Storage_ | null = defaultStorage()): void {
  try {
    storage?.removeItem(CREDENTIAL_STORAGE_KEY);
  } catch {
    // nothing stored to remove
  }
}

export interface IntegrationClient {
  /** One request to the Integration process, with the session header. */
  request(method: "GET" | "POST", path: string, body?: unknown): Promise<unknown>;
}

function defaultFetch(): FetchLike {
  return (input, init) => globalThis.fetch(input, init);
}

/**
 * The client of the Integration process for one credential. Every request
 * goes to INTEGRATION_ORIGIN with the session header; a refusal is thrown as
 * a SessionRefusal with the service's stable code.
 */
export function createIntegrationClient(credential: string, fetchImpl: FetchLike = defaultFetch()): IntegrationClient {
  if (!isCredentialShaped(credential)) throw new SessionRefusal("NOT_SHAPED");
  return {
    async request(method, path, body) {
      if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) {
        throw new Error(`not a path of the Integration process: ${path}`);
      }
      const headers: Record<string, string> = { [SESSION_HEADER]: credential };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      let response: Response;
      try {
        response = await fetchImpl(INTEGRATION_ORIGIN + path, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          credentials: "omit",
          mode: "cors",
          cache: "no-store",
          redirect: "error",
          referrerPolicy: "no-referrer",
        });
      } catch {
        throw new SessionRefusal("UNREACHABLE");
      }
      let answer: unknown = null;
      try {
        answer = await response.json();
      } catch {
        answer = null;
      }
      if (!response.ok) {
        const code = (answer as { code?: unknown } | null)?.code;
        const detail = (answer as { detail?: unknown } | null)?.detail;
        if (typeof code === "string" && code in REFUSAL_TEXT)
          throw new SessionRefusal(code as RefusalCode, response.status, typeof detail === "string" ? detail.slice(0, 500) : null);
        throw new SessionRefusal("ANSWER_INVALID", response.status);
      }
      return answer;
    },
  };
}

/** The login's one verified request: the session's public id and validity. */
export async function verifyCredential(credential: string, fetchImpl?: FetchLike): Promise<OwnerSession> {
  const answer = await createIntegrationClient(credential, fetchImpl).request("POST", "/session");
  if (!isSession(answer)) throw new SessionRefusal("ANSWER_INVALID");
  return { sessionId: answer.sessionId, issuedAt: answer.issuedAt, expiresAt: answer.expiresAt };
}
