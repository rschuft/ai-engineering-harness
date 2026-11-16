import { describe, expect, it } from "vitest";
import {
  CREDENTIAL_STORAGE_KEY,
  clearStoredCredential,
  createIntegrationClient,
  INTEGRATION_ORIGIN,
  isCredentialShaped,
  loadStoredCredential,
  SESSION_HEADER,
  SessionRefusal,
  storeCredential,
  verifyCredential,
  type FetchLike,
} from "./owner-session";

// The shell's side of the Owner UI session credential (U-01.3). Every request
// is answered by a fake Integration process: the network guard of the test
// setup refuses any real fetch.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

const SESSION = { sessionId: "3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162", issuedAt: "2026-11-16T12:00:00Z", expiresAt: "2026-11-17T00:00:00Z" };

interface Seen {
  url: string;
  init: RequestInit;
}

function fakeIntegration(answer: (seen: Seen) => Response): { fetchImpl: FetchLike; seen: Seen[] } {
  const seen: Seen[] = [];
  const fetchImpl: FetchLike = async (url, init) => {
    const entry = { url, init };
    seen.push(entry);
    return answer(entry);
  };
  return { fetchImpl, seen };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

describe("the credential's shape", () => {
  it("is aieh-oui- and 52 lower-case base32 characters, unlike an Agent Server key", () => {
    expect(isCredentialShaped(throwawayCredential())).toBe(true);
    const agentServerKey = "A".repeat(20) + "_-" + "b".repeat(21);
    for (const value of [agentServerKey, "aieh-inf-" + "a".repeat(43), "a".repeat(40), throwawayCredential().toUpperCase(), throwawayCredential() + "a", ""]) {
      expect(isCredentialShaped(value)).toBe(false);
    }
  });
});

describe("the Integration process client", () => {
  it("sends the session header on every request, to 127.0.0.1:13310 only, without cookies, redirects or referrer", async () => {
    const credential = throwawayCredential();
    const { fetchImpl, seen } = fakeIntegration(() => json(200, SESSION));
    const client = createIntegrationClient(credential, fetchImpl);
    await client.request("POST", "/session");
    await client.request("GET", "/threads");
    await client.request("POST", "/threads", { title: "t" });
    expect(seen.map((s) => [s.init.method, s.url])).toEqual([
      ["POST", "http://127.0.0.1:13310/session"],
      ["GET", "http://127.0.0.1:13310/threads"],
      ["POST", "http://127.0.0.1:13310/threads"],
    ]);
    for (const { init } of seen) {
      expect((init.headers as Record<string, string>)[SESSION_HEADER]).toBe(credential);
      expect(init.credentials).toBe("omit");
      expect(init.redirect).toBe("error");
      expect(init.referrerPolicy).toBe("no-referrer");
      expect(init.mode).toBe("cors");
      expect(Object.keys(init.headers as object).map((h) => h.toLowerCase())).not.toContain("cookie");
    }
    expect((seen[2].init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(document.cookie).toBe("");
    expect(INTEGRATION_ORIGIN).toBe("http://127.0.0.1:13310");
  });

  it("refuses to address anything but a path of the Integration process", async () => {
    const { fetchImpl, seen } = fakeIntegration(() => json(200, {}));
    const client = createIntegrationClient(throwawayCredential(), fetchImpl);
    for (const path of ["http://evil.test/x", "//evil.test/x", "session", "/\\evil.test"]) {
      await expect(client.request("GET", path)).rejects.toThrow(/not a path/);
    }
    expect(seen).toEqual([]);
    expect(() => createIntegrationClient("not-a-credential", fetchImpl)).toThrow(SessionRefusal);
  });

  it("turns each refusal of the service into its stable code", async () => {
    for (const code of ["SESSION_CREDENTIAL_MISSING", "SESSION_CREDENTIAL_FOREIGN", "SESSION_CREDENTIAL_EXPIRED", "SESSION_CREDENTIAL_REVOKED", "ORIGIN_NOT_ALLOWED", "HOST_NOT_ALLOWED"]) {
      const { fetchImpl } = fakeIntegration(() => json(code.startsWith("SESSION") ? 401 : 403, { code }));
      const refusal = await verifyCredential(throwawayCredential(), fetchImpl).catch((e: unknown) => e);
      expect(refusal).toBeInstanceOf(SessionRefusal);
      expect((refusal as SessionRefusal).code).toBe(code);
      expect((refusal as SessionRefusal).credentialRefused).toBe(code.startsWith("SESSION"));
    }
    const unreachable = await verifyCredential(throwawayCredential(), async () => {
      throw new TypeError("Failed to fetch");
    }).catch((e: unknown) => e);
    expect((unreachable as SessionRefusal).code).toBe("UNREACHABLE");
    const odd = await verifyCredential(throwawayCredential(), async () => json(200, { sessionId: "x" })).catch((e: unknown) => e);
    expect((odd as SessionRefusal).code).toBe("ANSWER_INVALID");
  });
});

describe("the shell's copy", () => {
  it("is kept in localStorage under one key and removed by sign-out", () => {
    const storage = memoryStorage();
    const credential = throwawayCredential();
    expect(storeCredential({ credential, ...SESSION }, storage)).toBe(true);
    expect([...storage.data.keys()]).toEqual([CREDENTIAL_STORAGE_KEY]);
    expect(loadStoredCredential(storage)).toEqual({ credential, ...SESSION });
    clearStoredCredential(storage);
    expect(storage.data.size).toBe(0);
    expect(loadStoredCredential(storage)).toBeNull();
  });

  it("drops a malformed stored copy", () => {
    for (const bad of ["not json", "{}", JSON.stringify({ v: 1, credential: "x", ...SESSION }), JSON.stringify({ v: 2, credential: throwawayCredential(), ...SESSION })]) {
      const storage = memoryStorage();
      storage.setItem(CREDENTIAL_STORAGE_KEY, bad);
      expect(loadStoredCredential(storage)).toBeNull();
      expect(storage.data.size).toBe(0);
    }
  });

  it("uses window.localStorage by default, never sessionStorage or a cookie", () => {
    const credential = throwawayCredential();
    storeCredential({ credential, ...SESSION });
    expect(JSON.parse(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)!).credential).toBe(credential);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
    clearStoredCredential();
    expect(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)).toBeNull();
  });
});
