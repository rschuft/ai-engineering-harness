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
export type RefusalCode =
  | (typeof CREDENTIAL_CODES)[number]
  | (typeof CONVERSATION_CODES)[number]
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
        if (typeof code === "string" && code in REFUSAL_TEXT) throw new SessionRefusal(code as RefusalCode, response.status);
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
