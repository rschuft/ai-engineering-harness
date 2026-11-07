import { describe, expect, it } from "vitest";
import { IDENTITY_STORAGE_KEY, loadOrCreateSessionIdentity, shortSessionId } from "./session-identity";

const ID_A = "3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162";
const ID_B = "8a7b6c5d-4e3f-4a1b-8c2d-0e1f2a3b4c5d";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

describe("session identity", () => {
  it("creates a local, unauthenticated Owner identity and stores only non-secret fields", () => {
    const storage = memoryStorage();
    const identity = loadOrCreateSessionIdentity({
      storage,
      newId: () => ID_A,
      now: () => new Date("2026-11-07T00:00:00Z"),
    });
    expect(identity).toEqual({
      role: "owner",
      sessionId: ID_A,
      createdAt: "2026-11-07T00:00:00.000Z",
      persisted: true,
      authenticated: false,
    });
    expect(JSON.parse(storage.data.get(IDENTITY_STORAGE_KEY)!)).toEqual({
      v: 1,
      sessionId: ID_A,
      createdAt: "2026-11-07T00:00:00.000Z",
    });
    expect([...storage.data.keys()]).toEqual([IDENTITY_STORAGE_KEY]);
  });

  it("returns the stored identity on the next load (a reload) instead of creating another", () => {
    const storage = memoryStorage();
    const first = loadOrCreateSessionIdentity({ storage, newId: () => ID_A });
    const second = loadOrCreateSessionIdentity({ storage, newId: () => ID_B });
    expect(second).toEqual(first);
    expect(second.sessionId).toBe(ID_A);
  });

  it("replaces a malformed or foreign stored value", () => {
    for (const bad of ["not json", "{}", JSON.stringify({ v: 1, sessionId: "abc", createdAt: "2026-01-01" }), JSON.stringify({ v: 2, sessionId: ID_A, createdAt: "2026-01-01T00:00:00Z" })]) {
      const storage = memoryStorage({ [IDENTITY_STORAGE_KEY]: bad });
      const identity = loadOrCreateSessionIdentity({ storage, newId: () => ID_B });
      expect(identity.sessionId).toBe(ID_B);
      expect(JSON.parse(storage.data.get(IDENTITY_STORAGE_KEY)!).sessionId).toBe(ID_B);
    }
  });

  it("still returns an identity, marked not persisted, when storage is missing or refuses writes", () => {
    const none = loadOrCreateSessionIdentity({ storage: null, newId: () => ID_A });
    expect(none).toMatchObject({ sessionId: ID_A, persisted: false, authenticated: false });

    const refusing = {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    };
    const refused = loadOrCreateSessionIdentity({ storage: refusing, newId: () => ID_B });
    expect(refused).toMatchObject({ sessionId: ID_B, persisted: false });
  });

  it("refuses a generator that does not produce a UUID", () => {
    expect(() => loadOrCreateSessionIdentity({ storage: memoryStorage(), newId: () => "owner" })).toThrow(/UUID/);
  });

  it("uses crypto.randomUUID and window.localStorage by default", () => {
    const identity = loadOrCreateSessionIdentity();
    expect(identity.sessionId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(window.localStorage.getItem(IDENTITY_STORAGE_KEY)).toContain(identity.sessionId);
    expect(loadOrCreateSessionIdentity().sessionId).toBe(identity.sessionId);
  });

  it("shows the first eight hex digits as the short form", () => {
    expect(shortSessionId(loadOrCreateSessionIdentity({ storage: null, newId: () => ID_A }))).toBe("3f2a9c1e");
  });
});
