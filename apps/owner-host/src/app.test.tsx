import { describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { OwnerApp } from "./App";
import { ownerRoutes } from "./routes";
import { AREAS } from "./areas";
import { IDENTITY_STORAGE_KEY } from "./identity/session-identity";
import { WIDE_MIN_WIDTH } from "./shell/layout";
import { takeNetworkAttempts } from "./test/network-guard";
import { setViewportWidth } from "./test/viewport";

function renderApp(path = "/") {
  const router = createMemoryRouter(ownerRoutes, { initialEntries: [path] });
  const view = render(<OwnerApp router={router} />);
  return { router, ...view };
}

function nav() {
  return screen.getByRole("navigation", { name: "Owner areas" });
}

function goTo(label: string) {
  fireEvent.click(within(nav()).getByRole("link", { name: new RegExp(`^${label}`) }));
}

function shownSessionId(): string {
  const value = screen.getByTestId("session-identity").getAttribute("data-session-id");
  expect(value).toBeTruthy();
  return value!;
}

describe("routes and navigation", () => {
  it("defines exactly the chat, Work and engineering areas", () => {
    expect(AREAS.map((a) => [a.id, a.path])).toEqual([
      ["chat", "/chat"],
      ["work", "/work"],
      ["engineering", "/engineering"],
    ]);
  });

  it("opens the chat area at the root path", async () => {
    const { router } = renderApp("/");
    expect(await screen.findByTestId("area-chat")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/chat");
  });

  it("navigates between all three areas through the persistent navigation", async () => {
    const { router } = renderApp("/chat");
    const shell = screen.getByTestId("owner-shell");
    for (const [label, testId, path] of [
      ["Work", "area-work", "/work"],
      ["Engineering", "area-engineering", "/engineering"],
      ["Chat", "area-chat", "/chat"],
      ["Engineering", "area-engineering", "/engineering"],
      ["Work", "area-work", "/work"],
    ] as const) {
      goTo(label);
      expect(await screen.findByTestId(testId)).toBeTruthy();
      expect(router.state.location.pathname).toBe(path);
      // The same shell element stays mounted: only the outlet changed.
      expect(screen.getByTestId("owner-shell")).toBe(shell);
      const current = within(nav()).getByRole("link", { current: "page" });
      expect(current.textContent).toContain(label);
    }
  });

  it("reaches every area directly by its address", async () => {
    for (const area of AREAS) {
      renderApp(area.path);
      expect(await screen.findByTestId(`area-${area.id}`)).toBeTruthy();
      cleanup();
    }
  });

  it("keeps the shell and identity on an unknown address and offers the areas", async () => {
    renderApp("/no-such-area");
    expect(await screen.findByTestId("area-not-found")).toBeTruthy();
    expect(screen.getByTestId("session-identity")).toBeTruthy();
    const links = within(screen.getByTestId("area-not-found")).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/chat", "/work", "/engineering"]);
  });
});

describe("one stable identity", () => {
  it("shows the same Owner session identity in every area", async () => {
    renderApp("/chat");
    const seen = new Set<string>();
    for (const label of ["Work", "Engineering", "Chat", "Work", "Engineering"]) {
      seen.add(shownSessionId());
      goTo(label);
      await screen.findByTestId(`area-${label.toLowerCase()}`);
    }
    seen.add(shownSessionId());
    expect(seen.size).toBe(1);
    const stored = JSON.parse(window.localStorage.getItem(IDENTITY_STORAGE_KEY)!);
    expect([...seen]).toEqual([stored.sessionId]);
    expect(screen.getByTestId("session-identity").textContent).toContain("Owner");
    expect(screen.getByTestId("session-identity").textContent).toContain("Not signed in");
  });

  it("keeps the identity across a simulated reload, on any route", async () => {
    renderApp("/work");
    await screen.findByTestId("area-work");
    const before = shownSessionId();
    cleanup(); // unmount everything: the page is gone, localStorage remains

    renderApp("/engineering");
    await screen.findByTestId("area-engineering");
    expect(shownSessionId()).toBe(before);
    cleanup();

    renderApp("/");
    await screen.findByTestId("area-chat");
    expect(shownSessionId()).toBe(before);
  });

  it("is the browser-local value: clearing site data starts a new session identity", async () => {
    renderApp("/chat");
    const first = shownSessionId();
    cleanup();
    window.localStorage.clear();
    renderApp("/chat");
    expect(shownSessionId()).not.toBe(first);
  });

  it("stores nothing but the session identity record in local storage", async () => {
    renderApp("/chat");
    goTo("Work");
    await screen.findByTestId("area-work");
    goTo("Engineering");
    await screen.findByTestId("canvas-status");
    expect(Object.keys(window.localStorage)).toEqual([IDENTITY_STORAGE_KEY]);
  });
});

describe("empty surfaces", () => {
  it("says plainly that the objective and Work surfaces are not connected, and lists nothing", async () => {
    renderApp("/work");
    const objectives = await screen.findByTestId("surface-objectives");
    const work = screen.getByTestId("surface-work-items");
    expect(within(objectives).getByTestId("objectives-empty").textContent).toMatch(/No objective source is connected/);
    expect(within(work).getByTestId("work-items-empty").textContent).toMatch(/No Work system is connected/);
    for (const surface of [objectives, work]) {
      expect(within(surface).queryAllByRole("listitem")).toEqual([]);
      expect(within(surface).queryAllByRole("article")).toEqual([]);
      expect(within(surface).queryAllByRole("link")).toEqual([]);
    }
  });

  it("mounts an empty assistant-ui thread with no model and a disabled composer", async () => {
    renderApp("/chat");
    const thread = await screen.findByTestId("chat-thread");
    expect(within(thread).getByTestId("chat-empty").textContent).toMatch(/No chat model and no conversation history/);
    const input = within(thread).getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
    expect(input.disabled).toBe(true);
    const send = within(thread).getByRole("button", { name: "Send" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(send);
    expect(thread.querySelectorAll(".owner-chat__message")).toHaveLength(0);
  });

  it("states that no Agent Server is connected and mounts Agent Canvas without one", async () => {
    renderApp("/engineering");
    const area = await screen.findByTestId("area-engineering");
    expect(within(area).getByTestId("engineering-empty").textContent).toMatch(/no Agent Server connection/);
    const status = await within(area).findByTestId("canvas-status");
    expect(status.textContent).toMatch(/Agent Canvas 1\.36\.0 is loaded without an Agent Server/);
    const canvasRoot = area.querySelector("[data-agent-server-ui]");
    expect(canvasRoot).not.toBeNull();
    expect(canvasRoot!.contains(status)).toBe(true);
    expect(within(area).queryByTestId("canvas-failed")).toBeNull();
  });
});

describe("no network", () => {
  it("attempts no network request across a full tour of the areas", async () => {
    renderApp("/");
    await screen.findByTestId("area-chat");
    for (const label of ["Work", "Engineering", "Chat", "Engineering"]) {
      goTo(label);
      await screen.findByTestId(`area-${label.toLowerCase()}`);
    }
    await screen.findByTestId("canvas-status");
    await act(() => new Promise((resolve) => setTimeout(resolve, 250)));
    expect(takeNetworkAttempts()).toEqual([]);
  });
});

describe("responsive layout (as far as jsdom allows)", () => {
  it("uses the wide layout at and above the breakpoint", async () => {
    setViewportWidth(WIDE_MIN_WIDTH);
    renderApp("/chat");
    expect(screen.getByTestId("owner-shell").getAttribute("data-layout")).toBe("wide");
    expect(within(nav()).getByRole("list").getAttribute("aria-orientation")).toBe("vertical");
    expect(screen.getByTestId("session-identity").getAttribute("data-compact")).toBe("false");
    expect(within(nav()).getByText("Objectives and Work")).toBeTruthy();
  });

  it("uses the narrow layout below the breakpoint, with the same identity and areas", async () => {
    setViewportWidth(WIDE_MIN_WIDTH - 1);
    renderApp("/chat");
    expect(screen.getByTestId("owner-shell").getAttribute("data-layout")).toBe("narrow");
    expect(within(nav()).getByRole("list").getAttribute("aria-orientation")).toBe("horizontal");
    expect(screen.getByTestId("session-identity").getAttribute("data-compact")).toBe("true");
    expect(within(nav()).queryByText("Objectives and Work")).toBeNull();
    expect(within(nav()).getAllByRole("link")).toHaveLength(3);
    goTo("Engineering");
    expect(await screen.findByTestId("area-engineering")).toBeTruthy();
  });

  it("switches layout live when the viewport crosses the breakpoint, keeping the identity", async () => {
    setViewportWidth(1280);
    renderApp("/work");
    const id = shownSessionId();
    const shell = screen.getByTestId("owner-shell");
    act(() => setViewportWidth(480));
    expect(shell.getAttribute("data-layout")).toBe("narrow");
    expect(shownSessionId()).toBe(id);
    act(() => setViewportWidth(1024));
    expect(shell.getAttribute("data-layout")).toBe("wide");
    expect(shownSessionId()).toBe(id);
    expect(screen.getByTestId("area-work")).toBeTruthy();
  });
});
