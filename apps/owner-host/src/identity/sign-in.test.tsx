import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { OwnerApp } from "../App";
import { ownerRoutes } from "../routes";
import { CREDENTIAL_STORAGE_KEY, SESSION_HEADER, type FetchLike } from "./owner-session";
import { IDENTITY_STORAGE_KEY } from "./session-identity";

// The login view and Sign out (U-01.3), in the whole app, against a fake
// Integration process. The network guard refuses any real request.

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";
const SESSION = { sessionId: "3f2a9c1e-7b4d-4e8a-9c0b-1d2e3f405162", issuedAt: "2026-11-16T12:00:00Z", expiresAt: "2026-11-17T00:00:00Z" };

function throwawayCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(52));
  return "aieh-oui-" + Array.from(bytes, (b) => BASE32[b % 32]).join("");
}

function fakeIntegration(enrolled: string) {
  const seen: { url: string; header: string | undefined }[] = [];
  const fetchImpl: FetchLike = async (url, init) => {
    const header = (init.headers as Record<string, string>)[SESSION_HEADER];
    seen.push({ url, header });
    const body = header === enrolled ? SESSION : { code: header ? "SESSION_CREDENTIAL_FOREIGN" : "SESSION_CREDENTIAL_MISSING" };
    return new Response(JSON.stringify(body), { status: header === enrolled ? 200 : 401 });
  };
  return { fetchImpl, seen };
}

function renderApp(path: string, fetchImpl: FetchLike) {
  const router = createMemoryRouter(ownerRoutes, { initialEntries: [path] });
  render(<OwnerApp router={router} fetchImpl={fetchImpl} />);
  return router;
}

async function paste(value: string) {
  const field = (await screen.findByLabelText("Owner UI session credential")) as HTMLInputElement;
  expect(field.type).toBe("password");
  fireEvent.change(field, { target: { value } });
  await act(async () => {
    fireEvent.submit(within(screen.getByTestId("area-sign-in")).getByRole("form", { name: "Sign in" }));
  });
  return field;
}

describe("signing in", () => {
  it("starts signed out with no request, and offers the sign-in from the header", async () => {
    const { fetchImpl, seen } = fakeIntegration(throwawayCredential());
    renderApp("/chat", fetchImpl);
    await screen.findByTestId("area-chat");
    expect(screen.getByTestId("session-identity").textContent).toContain("Not signed in");
    expect(screen.getByTestId("sign-in-link").getAttribute("href")).toBe("/sign-in");
    expect(seen).toEqual([]);
  });

  it("verifies the pasted credential with the Integration process, keeps it in localStorage and opens the chat", async () => {
    const credential = throwawayCredential();
    const { fetchImpl, seen } = fakeIntegration(credential);
    const router = renderApp("/sign-in", fetchImpl);
    const field = await paste(`  ${credential}\n`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/chat"));
    expect(seen).toEqual([{ url: "http://127.0.0.1:13310/session", header: credential }]);
    expect(field.value).toBe("");
    expect(screen.getByTestId("session-identity").textContent).toContain("Signed in");
    expect(JSON.parse(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)!)).toEqual({ v: 1, credential, ...SESSION });
    expect(Object.keys(window.localStorage).sort()).toEqual([CREDENTIAL_STORAGE_KEY, IDENTITY_STORAGE_KEY].sort());
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
    expect(document.body.innerHTML).not.toContain(credential);
  });

  it("shows a refusal by its code and keeps nothing", async () => {
    const { fetchImpl, seen } = fakeIntegration(throwawayCredential());
    renderApp("/sign-in", fetchImpl);
    const other = throwawayCredential();
    await paste(other);
    const refusal = await screen.findByTestId("sign-in-refusal");
    expect(refusal.getAttribute("data-code")).toBe("SESSION_CREDENTIAL_FOREIGN");
    expect(seen).toHaveLength(1);
    expect(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)).toBeNull();
    expect(document.body.innerHTML).not.toContain(other);
  });

  it("refuses a value without the credential's shape before sending anything", async () => {
    const { fetchImpl, seen } = fakeIntegration(throwawayCredential());
    renderApp("/sign-in", fetchImpl);
    await paste("A".repeat(43));
    expect((await screen.findByTestId("sign-in-refusal")).getAttribute("data-code")).toBe("NOT_SHAPED");
    expect(seen).toEqual([]);
  });
});

describe("a stored copy and Sign out", () => {
  it("re-verifies a stored copy when the shell opens, with the header, and Sign out removes it", async () => {
    const credential = throwawayCredential();
    window.localStorage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify({ v: 1, credential, ...SESSION }));
    const { fetchImpl, seen } = fakeIntegration(credential);
    renderApp("/work", fetchImpl);
    await waitFor(() => expect(screen.getByTestId("session-identity").textContent).toContain("Signed in"));
    expect(seen).toEqual([{ url: "http://127.0.0.1:13310/session", header: credential }]);
    fireEvent.click(screen.getByTestId("sign-out"));
    expect(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId("session-identity").textContent).toContain("Not signed in");
    expect(screen.getByTestId("sign-in-link")).toBeTruthy();
  });

  it("drops a stored copy the service refuses (expired, revoked or foreign)", async () => {
    const stale = throwawayCredential();
    window.localStorage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify({ v: 1, credential: stale, ...SESSION }));
    const fetchImpl: FetchLike = async () => new Response(JSON.stringify({ code: "SESSION_CREDENTIAL_EXPIRED" }), { status: 401 });
    renderApp("/sign-in", fetchImpl);
    expect((await screen.findByTestId("sign-in-refusal")).getAttribute("data-code")).toBe("SESSION_CREDENTIAL_EXPIRED");
    expect(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)).toBeNull();
  });

  it("keeps a stored copy while the Integration process is unreachable", async () => {
    const credential = throwawayCredential();
    window.localStorage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify({ v: 1, credential, ...SESSION }));
    const fetchImpl: FetchLike = async () => {
      throw new TypeError("Failed to fetch");
    };
    renderApp("/sign-in", fetchImpl);
    expect((await screen.findByTestId("sign-in-refusal")).getAttribute("data-code")).toBe("UNREACHABLE");
    expect(JSON.parse(window.localStorage.getItem(CREDENTIAL_STORAGE_KEY)!).credential).toBe(credential);
  });
});
