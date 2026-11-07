// Characterization of the pinned pair Agent Canvas 1.36.0 + assistant-ui
// 0.15.32 in one React tree, without an Agent Server (compatibility matrix row
// "agent-canvas 1.36.0 / assistant-ui 0.15.32"). These tests record upstream
// behaviour as observed; a failure after an upgrade means the evidence changed.
import { describe, expect, it } from "vitest";
import { Component, type ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import {
  AGENT_SERVER_UI_SCOPE_ATTRIBUTE,
  AgentServerUIProviders,
  ChatPanel,
  ConversationPanel,
  ConversationView,
  getI18n,
  setI18n,
} from "@openhands/agent-canvas";
import { AssistantRuntimeProvider, ThreadPrimitive, useLocalRuntime } from "@assistant-ui/react";
import canvasPackageJson from "../../node_modules/@openhands/agent-canvas/package.json?raw";
import assistantUiPackageJson from "../../node_modules/@assistant-ui/react/package.json?raw";
import reactPackageJson from "../../node_modules/react/package.json?raw";
import reactDomPackageJson from "../../node_modules/react-dom/package.json?raw";
import reactRouterPackageJson from "../../node_modules/react-router/package.json?raw";
import zustandPackageJson from "../../node_modules/zustand/package.json?raw";
import { createCanvasI18n } from "./canvas-i18n";
import { modelFreeChatAdapter } from "../areas/chat-adapter";
import { takeNetworkAttempts } from "../test/network-guard";

class Catch extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(error: Error) {
    return { error: error.message };
  }
  render() {
    return this.state.error ? <p data-testid="caught">{this.state.error}</p> : this.props.children;
  }
}

function Thread() {
  const runtime = useLocalRuntime(modelFreeChatAdapter);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root data-testid="aui-thread">
        <ThreadPrimitive.Empty>
          <p>empty thread</p>
        </ThreadPrimitive.Empty>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

function canvas(children: ReactNode) {
  const i18n = createCanvasI18n();
  setI18n(i18n);
  return (
    <AgentServerUIProviders analytics={false} i18n={i18n}>
      {children}
    </AgentServerUIProviders>
  );
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 300));

// Read from the top-level install by path, not through the packages' export
// maps (@assistant-ui/react does not export package.json).
const INSTALLED: Record<string, string> = {
  "@openhands/agent-canvas": canvasPackageJson,
  "@assistant-ui/react": assistantUiPackageJson,
  react: reactPackageJson,
  "react-dom": reactDomPackageJson,
  "react-router": reactRouterPackageJson,
  zustand: zustandPackageJson,
};

function installed(name: string): { version: string; peerDependencies?: Record<string, string> } {
  return JSON.parse(INSTALLED[name]);
}

describe("installed versions", () => {
  it("are the pinned versions", () => {
    expect(installed("@openhands/agent-canvas").version).toBe("1.36.0");
    expect(installed("@assistant-ui/react").version).toBe("0.15.32");
    expect(installed("react").version).toBe("19.3.1");
    expect(installed("react-dom").version).toBe("19.3.1");
    expect(installed("react-router").version).toBe("8.5.0");
    expect(installed("zustand").version).toBe("5.0.16");
    expect(installed("@openhands/agent-canvas").peerDependencies).toEqual({
      react: "19.3.1",
      "react-dom": "19.3.1",
      "react-router": "8.5.0",
    });
  });
});

describe("Agent Canvas and assistant-ui in one React tree, no Agent Server", () => {
  it("mounts both side by side under one router without errors or network", async () => {
    render(
      <MemoryRouter>
        <Thread />
        {canvas(
          <Catch>
            <ConversationPanel />
          </Catch>,
        )}
      </MemoryRouter>,
    );
    expect(await screen.findByText("empty thread")).toBeTruthy();
    expect(await screen.findByTestId("conversation-panel")).toBeTruthy();
    await settle();
    expect(screen.queryByTestId("caught")).toBeNull();
    expect(takeNetworkAttempts()).toEqual([]);
  });

  it("scopes Canvas under its root attribute and keeps assistant-ui outside it", async () => {
    const { container } = render(
      <MemoryRouter>
        <Thread />
        {canvas(<p data-testid="inside">inside</p>)}
      </MemoryRouter>,
    );
    expect(AGENT_SERVER_UI_SCOPE_ATTRIBUTE).toBe("data-agent-server-ui");
    const roots = container.querySelectorAll("[data-agent-server-ui]");
    expect(roots).toHaveLength(1);
    expect(roots[0].contains(screen.getByTestId("inside"))).toBe(true);
    expect(roots[0].contains(await screen.findByTestId("aui-thread"))).toBe(false);
  });

  it("with no backend, the conversation panel shows its loading skeleton, not a not-connected state", async () => {
    render(<MemoryRouter>{canvas(<ConversationPanel />)}</MemoryRouter>);
    const panel = await screen.findByTestId("conversation-panel");
    await settle();
    // Canvas disables its conversation query when no backend is registered, so
    // the list never loads and the skeleton stays. The host therefore states the
    // not-connected condition itself (EngineeringArea) and does not mount this.
    expect(within(panel).getAllByTestId("conversation-card-skeleton").length).toBeGreaterThan(0);
    expect(panel.textContent).not.toMatch(/No conversations found|No Backend Available/);
  });

  it("cannot show a session through the public exports: ConversationView ignores the host route's :conversationId", async () => {
    render(
      <MemoryRouter initialEntries={["/conversations/abc123"]}>
        <Routes>
          <Route
            path="/conversations/:conversationId"
            element={canvas(
              <Catch>
                <ConversationView />
              </Catch>,
            )}
          />
        </Routes>
      </MemoryRouter>,
    );
    // Canvas reads the conversation id from its internal navigation context,
    // whose provider 1.36.0 does not export (U-01.2 evidence).
    expect((await screen.findByTestId("caught")).textContent).toBe(
      "useConversationId must be used within a route that has a conversationId parameter",
    );
  });

  it("ChatPanel has the same requirement", async () => {
    render(
      <MemoryRouter>
        {canvas(
          <Catch>
            <ChatPanel />
          </Catch>,
        )}
      </MemoryRouter>,
    );
    expect((await screen.findByTestId("caught")).textContent).toMatch(/useConversationId must be used/);
  });

  it("uses the host's i18n instance once registered, so no translation file is fetched", async () => {
    const i18n = createCanvasI18n();
    setI18n(i18n);
    expect(getI18n()).toBe(i18n);
    expect(i18n.t("BACKEND$NO_BACKEND_AVAILABLE")).toBe("No Backend Available");
    render(<MemoryRouter>{canvas(<p>ok</p>)}</MemoryRouter>);
    await settle();
    expect(takeNetworkAttempts()).toEqual([]);
  });
});
