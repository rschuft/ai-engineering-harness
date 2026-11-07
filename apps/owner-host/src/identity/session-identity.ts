// The Owner's session identity in the host shell (plan leaf U-01.1).
//
// It is a local, non-secret value: a random UUID created once in this browser
// profile and kept in localStorage, so it stays the same across every route,
// every tab and every reload until the browser's site data is cleared. It is
// NOT an authenticated identity and carries no credential, token or key. How
// the Owner UI authenticates to the Agent Server and the Integration Service is
// an open finding (`fd-owner-ui-access` in security/inventory.json, carried to
// S-01.3.1); nothing here decides it.

export const IDENTITY_STORAGE_KEY = "aieh.owner-host.session-identity";
const RECORD_VERSION = 1;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export interface OwnerSessionIdentity {
  /** The role this shell serves. There is exactly one Owner. */
  readonly role: "owner";
  /** Random, non-secret session value (UUID v4 form). */
  readonly sessionId: string;
  /** When this browser profile first created the value (ISO 8601). */
  readonly createdAt: string;
  /** False when storage was unavailable: the value then lasts for this page only. */
  readonly persisted: boolean;
  /** Always false: no authentication exists yet (fd-owner-ui-access). */
  readonly authenticated: false;
}

interface StoredRecord {
  v: number;
  sessionId: string;
  createdAt: string;
}

export interface IdentitySources {
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  newId?: () => string;
  now?: () => Date;
}

function defaultStorage(): Pick<Storage, "getItem" | "setItem"> | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function parse(raw: string | null): StoredRecord | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<StoredRecord>;
    if (
      value.v === RECORD_VERSION &&
      typeof value.sessionId === "string" &&
      UUID.test(value.sessionId) &&
      typeof value.createdAt === "string" &&
      !Number.isNaN(Date.parse(value.createdAt))
    ) {
      return { v: value.v, sessionId: value.sessionId, createdAt: value.createdAt };
    }
  } catch {
    // Not JSON: replaced below.
  }
  return null;
}

/**
 * Return the stored session identity, or create, store and return a new one.
 * A malformed stored value is replaced. If storage is unavailable or refuses
 * the write, the identity is still returned, marked `persisted: false`.
 */
export function loadOrCreateSessionIdentity(sources: IdentitySources = {}): OwnerSessionIdentity {
  const storage = sources.storage === undefined ? defaultStorage() : sources.storage;
  const newId = sources.newId ?? (() => crypto.randomUUID());
  const now = sources.now ?? (() => new Date());

  let raw: string | null = null;
  try {
    raw = storage ? storage.getItem(IDENTITY_STORAGE_KEY) : null;
  } catch {
    raw = null;
  }
  const existing = parse(raw);
  if (existing) {
    return { role: "owner", sessionId: existing.sessionId, createdAt: existing.createdAt, persisted: true, authenticated: false };
  }

  const record: StoredRecord = { v: RECORD_VERSION, sessionId: newId().toLowerCase(), createdAt: now().toISOString() };
  if (!UUID.test(record.sessionId)) {
    throw new Error("session identity generator did not return a UUID");
  }
  let persisted = false;
  if (storage) {
    try {
      storage.setItem(IDENTITY_STORAGE_KEY, JSON.stringify(record));
      persisted = true;
    } catch {
      persisted = false;
    }
  }
  return { role: "owner", sessionId: record.sessionId, createdAt: record.createdAt, persisted, authenticated: false };
}

/** The short form shown in the shell: the first eight hex digits. */
export function shortSessionId(identity: OwnerSessionIdentity): string {
  return identity.sessionId.slice(0, 8);
}
